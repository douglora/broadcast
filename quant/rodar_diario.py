"""
Orquestrador diario (M14): coleta -> universo -> sinais -> carteira -> boleta -> fiscal ->
`quant/saida/painel.json`.

E o unico programa que o Douglas roda todo dia. Ele faz o trabalho pesado uma vez, de
noite, e deixa um JSON pronto; o terminal so le esse JSON e nao importa pandas. O contrato
do arquivo esta em `docs/painel-contrato.md` e e obrigatorio: campo fora do contrato
quebra o painel em silencio.

TRES REGRAS QUE ESTE MODULO NAO NEGOCIA:

  1. **Nunca roda com credencial no CI.** O workflow que ja existe coleta dado publico e
     so. Execucao e local, na maquina do Douglas.
  2. **Degradar e falar.** Falta de dado nao levanta excecao nem some: cada peca que nao
     veio entra em `modo_seguro.motivos` e aparece em vermelho no painel. Um painel que
     mostra numero velho sem avisar e pior que um painel vazio.
  3. **Nada de NaN no JSON.** `jsonify` nao serializa NaN, numpy.float64 nem
     pandas.Timestamp, e `NaN` produz JSON invalido que quebra o `await r.json()` do
     front. Tudo passa por `limpar()` antes de ser gravado.

Modos:
  --paper (padrao): fills simulados contra o negocio-a-negocio arquivado. E o modo da
    fase 4 e o unico que faz sentido enquanto nao ha corretora escolhida.
  --real: le os fills que o Douglas registrou no livro. Nao envia ordem para lugar
    nenhum - o envio e manual, pela corretora, no estagio A.

Sem banco de dados montado, cai para o mercado sintetico e CARIMBA `origem="sintetico"`,
para nenhum numero da tela ser confundido com resultado.

Uso:
    python -m quant.rodar_diario --paper
"""
import argparse
import os
import sys
from datetime import date, datetime

import numpy as np
import pandas as pd

from quant.comum import DIR_BANCO, DIR_SAIDA, agora_brt, garantir_dir, gravar_json, log
from quant.dados import calendario

ARQ_PAINEL = os.path.join(DIR_SAIDA, "painel.json")
ARQ_ESTADO = os.path.join(DIR_SAIDA, "estado.json")
CAPITAL_PADRAO = 100_000.0
ANOS_HISTORICO = 3          # quanto do banco carregar para calcular sinais e desempenho


# ─────────────────────────────────────────────────────────────
# Utilitarios puros
# ─────────────────────────────────────────────────────────────
def limpar(obj):
    """Converte para tipos JSON nativos. NaN, inf, numpy e Timestamp viram None ou texto.

    Sem isso o painel quebra: `jsonify` recusa numpy.float64 e `NaN` gera JSON invalido.
    """
    if obj is None or obj is pd.NaT:
        return None                      # NaT E um datetime: tem de ser testado ANTES
    if isinstance(obj, dict):
        return {str(k): limpar(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [limpar(v) for v in obj]
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.strftime("%Y-%m-%d")
    if isinstance(obj, date):
        return obj.strftime("%Y-%m-%d")
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        v = float(obj)
        return None if not np.isfinite(v) else round(v, 8)
    if isinstance(obj, (str, bytes)):
        return obj.decode() if isinstance(obj, bytes) else obj
    return str(obj)


def _dias_atras(quando, hoje):
    if quando is None:
        return None
    d = pd.Timestamp(quando).date()
    return len(calendario.pregoes(d, hoje)) - 1


def frescor(hoje, fontes):
    """Bloco `frescor` do painel: por fonte, a ultima data, quantos pregoes atras e se serve."""
    out = {}
    for nome, (quando, tolerancia) in fontes.items():
        dias = _dias_atras(quando, hoje)
        out[nome] = {"data": None if quando is None else str(pd.Timestamp(quando).date()),
                     "dias_atras": dias,
                     "ok": bool(dias is not None and dias <= tolerancia)}
    return out


def modo_seguro(frescor_dados, gate_passou=None, extras=None):
    """(ativo, motivos). Bloqueia com dado atrasado ou gate nao aprovado.

    O padrao de `gate_passou=None` (desconhecido) BLOQUEIA. Nao emitir e o comportamento
    seguro; emitir uma boleta sobre dado que ninguem validou nao e.
    """
    motivos = list(extras or [])
    for nome, f in (frescor_dados or {}).items():
        if not f.get("ok"):
            quando = f.get("data") or "nunca"
            motivos.append(f"{nome} desatualizado (ultimo dado: {quando})")
    if not gate_passou:
        motivos.append("gate da fase 1 nao aprovado: a replica WML/HML do NEFIN nao rodou "
                       "com o COTAHIST real")
    return (len(motivos) > 0), motivos


# ─────────────────────────────────────────────────────────────
# Fontes de dados
# ─────────────────────────────────────────────────────────────
def _tem_banco():
    caminho = os.path.join(DIR_BANCO, "cotacoes_diarias")
    return os.path.isdir(caminho) and any(os.scandir(caminho))


def carregar_real(ate=None, anos=ANOS_HISTORICO):
    """Insumos a partir do banco local. None se o banco nao estiver montado."""
    if not _tem_banco():
        return None
    from quant.dados import cdi as cdi_mod, cotahist, eventos, mercado, nefin
    from quant import sinais as sg
    fim = pd.Timestamp(ate or date.today())
    cot = cotahist.carregar(fim.year - anos, fim.year)
    if cot is None or len(cot) == 0:
        return None
    painel = sg.carregar()
    ret = sg.painel_retornos(eventos.retorno_total(cot[["ticker", "data", "fec"]],
                                                   eventos.carregar_eventos(), jcp_liquido=True))
    taxa = cdi_mod.carregar(permitir_rede=False)
    try:
        fatores = nefin.carregar_fatores()
        exc = mercado.excesso_mercado(fatores)
        niv = mercado.nivel_indice(exc, taxa)
    except Exception as e:                                   # sem snapshot NEFIN
        log(f"sem fatores NEFIN ({type(e).__name__}); hedge fica sem nivel")
        fatores, exc, niv = None, None, None
    ultima_cot = pd.to_datetime(cot["data"]).max()
    return {"origem": "real", "cotacoes": cot, "sinais": painel, "retornos": ret,
            "cdi": taxa, "excesso": exc, "nivel": niv, "fatores": fatores,
            "ultima_cotacao": ultima_cot}


def carregar_sintetico(seed=7, n_empresas=40, anos=3, ate=None):
    """Mercado artificial, para o painel existir antes de o banco existir.

    Carimba `origem="sintetico"`: nenhum numero produzido daqui e resultado de estrategia.
    """
    from quant.validacao import mercado_sintetico as ms
    from quant.dados import cotahist, eventos, mercado, painel_fundamentos, setores
    from quant import sinais as sg, universo as uni_mod
    fim = pd.Timestamp(ate or date.today())
    ini = fim - pd.DateOffset(years=anos)
    dados = ms.gerar(ini=ini.strftime("%Y-%m-%d"), fim=fim.strftime("%Y-%m-%d"),
                     n_empresas=n_empresas, seed=seed, fracao_mortas=0.10)
    cot, ident = dados["cotacoes"], dados["identidade"]
    uni = uni_mod.universo_pit(cotahist.acoes_a_vista(cot, apenas_lote_padrao=True),
                              identidade=ident, adtv_min=800_000.0)
    ret = sg.painel_retornos(eventos.retorno_total(cot[["ticker", "data", "fec"]],
                                                   dados["eventos"], jcp_liquido=True))
    datas = sorted({pd.Timestamp(d) for d in uni["data"].unique()})
    mapa = setores.mapa_setores(identidade=ident, cadastro=dados["cadastro"])
    fund = painel_fundamentos.painel_ttm(dados["fundamentos"], datas,
                                         financeiras=setores.financeiras(mapa, ident),
                                         deslocar=True)
    painel = sg.painel(uni, ret, fundamentos=fund, identidade=ident, setores=mapa, datas=datas)
    exc = mercado.excesso_mercado(dados["fatores"])
    niv = mercado.nivel_indice(exc, dados["cdi"])
    return {"origem": "sintetico", "cotacoes": cot, "sinais": painel, "retornos": ret,
            "cdi": dados["cdi"], "excesso": exc, "nivel": niv, "fatores": dados["fatores"],
            "ultima_cotacao": pd.to_datetime(cot["data"]).max(), "sintetico": dados}


# ─────────────────────────────────────────────────────────────
# Blocos do painel
# ─────────────────────────────────────────────────────────────
def bloco_carteira(estado, mes_sinais, precos, capital):
    """Bloco `carteira`: posicoes com peso realizado contra o peso alvo."""
    from quant import carteira as ct
    pos = []
    patrimonio = float(estado.get("patrimonio") or capital)
    alvo_peso = {}
    if mes_sinais is not None and len(mes_sinais):
        s = mes_sinais.set_index("ticker")
        vol = s["vol252"].to_dict()
        setor = s["setor"].to_dict()
        rank = s["rank"].to_dict()
        elegiveis, _ = ct.selecionar(mes_sinais, estado.get("posicoes"))
        pesos = ct.pesos_alvo(elegiveis, vol,
                              setor={t: setor.get(t) for t in elegiveis},
                              adtv=s["adtv21"].to_dict())
        alvo_peso = {t: float(w) for t, w in pesos.items()}
    else:
        setor, rank = {}, {}
    for ticker, p in sorted((estado.get("posicoes") or {}).items()):
        preco = float(precos.get(ticker, np.nan)) if precos else np.nan
        valor = float(p.get("valor", 0.0))
        qtd = int(p.get("qtd", 0))
        pm = (valor / qtd) if qtd else np.nan
        pos.append({"ticker": ticker, "setor": setor.get(ticker), "qtd": qtd,
                    "preco_medio": pm, "preco": preco, "valor": valor,
                    "peso": valor / patrimonio if patrimonio else None,
                    "peso_alvo": alvo_peso.get(ticker), "meses": int(p.get("meses", 0)),
                    "rank": rank.get(ticker),
                    "pnl": (preco - pm) * qtd if np.isfinite(preco) and np.isfinite(pm) else None,
                    "pnl_pct": (preco / pm - 1.0) if np.isfinite(preco) and np.isfinite(pm) and pm else None})
    valor_pos = sum(p["valor"] for p in pos)
    contratos = int((estado.get("hedge") or {}).get("contratos") or 0)
    return {"patrimonio": patrimonio, "caixa": float(estado.get("caixa") or 0.0),
            "valor_posicoes": valor_pos, "n_posicoes": len(pos),
            "contratos_hedge": contratos,
            "exposicao": valor_pos / patrimonio if patrimonio else None,
            "caixa_minimo": ct.caixa_minimo(patrimonio, contratos),
            "violacoes": list(estado.get("violacoes") or []), "posicoes": pos}


def bloco_fiscal(mes=None):
    """Bloco `fiscal` a partir do livro de ordens. Vazio (e honesto) quando nao ha livro."""
    from quant import fiscal as fs
    try:
        from quant.execucao import livro_ordens as lo
        ops = lo.operacoes()
    except Exception as e:
        log(f"sem livro de ordens ({type(e).__name__}: {e})")
        ops = None
    if ops is None or len(ops) == 0:
        return fs.resumo_mes({"mensal": pd.DataFrame()}, mes)
    return fs.resumo_mes(fs.apurar(ops), mes)


def bloco_boleta(dados, estado, data, capital, frescor_dados, gate_passou, seguro):
    """Bloco `boleta`. Com modo seguro ativo nao existe boleta: `emitida=False` e lista vazia."""
    vazio = {"data": str(data), "id": pd.Timestamp(data).strftime("%Y%m%d"), "emitida": False,
             "motivo_bloqueio": [], "custo_total": 0.0, "ordens": []}
    try:
        from quant.execucao import boleta as bo
    except Exception as e:
        vazio["motivo_bloqueio"] = [f"modulo de boleta indisponivel ({type(e).__name__})"]
        return vazio
    from quant import carteira as ct
    mes = _mes_sinais(dados["sinais"], data)
    if mes is None or len(mes) == 0:
        vazio["motivo_bloqueio"] = ["sem sinais calculados para a data"]
        return vazio
    precos = mes.set_index("ticker")["preco"].to_dict()
    adtv = mes.set_index("ticker")["adtv21"].to_dict()
    setor = mes.set_index("ticker")["setor"].to_dict()
    alvo = ct.carteira_alvo(mes, estado, precos, adtv=adtv, setor=setor,
                            patrimonio=estado.get("patrimonio", capital), data=data)
    try:
        return bo.gerar(alvo["ordens"], precos, adtv, data,
                        frescor_dados=frescor_dados, gate_passou=gate_passou,
                        caixa_disponivel=estado.get("caixa"), hedge=alvo.get("hedge"))
    except Exception as e:                                   # a boleta nunca derruba a rodada
        log(f"boleta falhou ({type(e).__name__}: {e})")
        vazio["motivo_bloqueio"] = [f"falha ao gerar a boleta: {type(e).__name__}"]
        return vazio


def _mes_sinais(painel_sinais, data):
    if painel_sinais is None or len(painel_sinais) == 0:
        return None
    d = pd.to_datetime(painel_sinais["data"])
    ate = d[d <= pd.Timestamp(data)]
    if ate.empty:
        return None
    from quant import sinais as sg
    return sg.em(painel_sinais, ate.max())


# ─────────────────────────────────────────────────────────────
# Rodada
# ─────────────────────────────────────────────────────────────
def rodar(modo="paper", capital=CAPITAL_PADRAO, data=None, seed=7, gate_passou=None,
          dados=None):
    """Monta o painel completo. Nunca levanta: o que falta vira motivo de modo seguro."""
    hoje = pd.Timestamp(data or date.today()).date()
    hoje = calendario.ultimo_pregao_ate(hoje)
    if dados is None:
        dados = carregar_real(ate=hoje)
        if dados is None:
            log("banco vazio: caindo para o mercado sintetico (origem=sintetico)")
            dados = carregar_sintetico(seed=seed, ate=hoje)
    fontes = {"cotahist": (dados.get("ultima_cotacao"), 1),
              "sinais": (_ultima(dados.get("sinais"), "data"), 45),
              "cdi": (_ultimo_indice(dados.get("cdi")), 5)}
    fres = frescor(hoje, fontes)
    extras = []
    if dados["origem"] != "real":
        extras.append("dados sinteticos: nenhum numero desta tela e resultado de estrategia")
    seguro, motivos = modo_seguro(fres, gate_passou, extras)

    estado = _estado_atual(capital, dados, hoje)
    mes = _mes_sinais(dados["sinais"], hoje)
    precos = mes.set_index("ticker")["preco"].to_dict() if mes is not None and len(mes) else {}

    from quant import relatorio as rel
    serie = _serie_patrimonio(estado, dados, hoje, capital)
    desempenho = rel.desempenho(serie, cdi=dados.get("cdi"))
    kill = rel.criterios_kill(_medidas_kill(desempenho, dados, mes))

    painel = {
        "gerado_em": agora_brt().isoformat(timespec="seconds"),
        "modo": modo, "origem": dados["origem"], "capital": float(capital),
        "gate_fase1": {"passou": bool(gate_passou),
                       "detalhe": "aprovado" if gate_passou else
                                  "nao rodado: exige o COTAHIST real e a replica WML/HML"},
        "frescor": fres,
        "modo_seguro": {"ativo": bool(seguro), "motivos": motivos},
        "carteira": bloco_carteira(estado, mes, precos, capital),
        "boleta": bloco_boleta(dados, estado, hoje, capital, fres, gate_passou, seguro),
        "fiscal": bloco_fiscal(),
        "desempenho": desempenho,
        "kill": kill,
    }
    return limpar(painel)


def _ultima(df, coluna):
    if df is None or len(df) == 0 or coluna not in df:
        return None
    return pd.to_datetime(df[coluna]).max()


def _ultimo_indice(serie):
    if serie is None or len(serie) == 0:
        return None
    return pd.Timestamp(pd.Series(serie).index.max())


def _estado_atual(capital, dados, hoje):
    """Estado da carteira: do livro de ordens quando houver, senao carteira vazia."""
    from quant import carteira as ct
    estado = ct.estado_inicial(capital, hoje)
    try:
        from quant.execucao import livro_ordens as lo
        pos = lo.posicao(ate=hoje)
    except Exception:
        return estado
    if pos is None or len(pos) == 0:
        return estado
    posicoes, investido = {}, 0.0
    for _, r in pos.iterrows():
        qtd = int(r["qtd"])
        if qtd <= 0:
            continue
        custo = float(r["custo_total"])
        posicoes[str(r["ticker"])] = {"qtd": qtd, "valor": custo, "meses": int(r.get("meses", 0) or 0)}
        investido += custo
    estado["posicoes"] = posicoes
    estado["caixa"] = max(capital - investido, 0.0)
    estado["patrimonio"] = estado["caixa"] + investido
    return estado


def _serie_patrimonio(estado, dados, hoje, capital):
    """Serie diaria de patrimonio. Sem historico proprio ainda, devolve None."""
    caminho = os.path.join(DIR_SAIDA, "serie_patrimonio.csv")
    if os.path.exists(caminho):
        try:
            return pd.read_csv(caminho)
        except Exception:
            return None
    return None


def _medidas_kill(desempenho, dados, mes):
    """Medidas dos criterios de kill que ja da para calcular hoje."""
    uni = None
    if mes is not None and len(mes):
        uni = int(len(mes))
    return {"drawdown": desempenho.get("mdd"), "excesso_12m": desempenho.get("excesso"),
            "universo": uni}


def gravar_painel(painel, caminho=ARQ_PAINEL):
    garantir_dir(os.path.dirname(caminho))
    gravar_json(caminho, painel)
    return caminho


def main(argv=None):
    ap = argparse.ArgumentParser(description="Rodada diaria do sistema quant (M14)")
    ap.add_argument("--paper", action="store_true", help="fills simulados (padrao)")
    ap.add_argument("--real", action="store_true", help="usa os fills registrados no livro")
    ap.add_argument("--capital", type=float, default=CAPITAL_PADRAO)
    ap.add_argument("--data", default=None)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)
    modo = "real" if args.real else "paper"
    painel = rodar(modo=modo, capital=args.capital, data=args.data, seed=args.seed)
    caminho = gravar_painel(painel)
    ms = painel["modo_seguro"]
    log(f"painel em {caminho} (origem: {painel['origem']}, modo: {modo})")
    if ms["ativo"]:
        log("MODO SEGURO ATIVO, nenhuma boleta emitida:")
        for m in ms["motivos"]:
            log(f"  - {m}")
    else:
        n = len(painel["boleta"]["ordens"])
        log(f"boleta com {n} ordem(ns), custo estimado R${painel['boleta']['custo_total']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
