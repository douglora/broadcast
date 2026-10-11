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
    ret = sg.painel_retornos(eventos.retorno_total_limpo(cot[["ticker", "data", "fec", "fatcot"]],
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


def bloco_paper(dados=None):
    """Bloco `paper`: o placar da campanha de paper trading (fase 4).

    Le o registro acumulado em `quant/saida/`. Sem campanha aberta devolve o esqueleto com
    zero sessoes — que e o estado honesto de quem ainda nao comecou, nao um erro.
    """
    try:
        from quant.execucao import campanha as cp
    except Exception as e:
        log(f"sem modulo de campanha ({type(e).__name__})")
        return {"origem": "nenhuma", "sessoes": 0, "passou": False, "criterios": [],
                "avisos": [f"modulo de campanha indisponivel ({type(e).__name__})"]}
    try:
        sessoes, origem = cp.carregar_sessoes(), None
        if not len(sessoes):
            # sem campanha real, mostra o ensaio — carimbado como ensaio, que e o que ele e
            sessoes, origem = cp.carregar_sessoes(cp.ARQ_SESSOES_ENSAIO), "ensaio"
        erros = cp.carregar_erros()
        conf = cp.carregar_conferencias()
        aval = cp.avaliar(sessoes, erros, conferidos=conf, origem=origem,
                          config_inicial=(cp.estado_campanha() or {}).get("config"),
                          config_atual=cp.config_da_estrategia() if len(sessoes) else None)
        return cp.resumo(sessoes, erros, aval)
    except Exception as e:                                   # o painel nunca cai por isso
        log(f"campanha falhou ({type(e).__name__}: {e})")
        return {"origem": "nenhuma", "sessoes": 0, "passou": False, "criterios": [],
                "avisos": [f"falha ao ler a campanha: {type(e).__name__}"]}


def bloco_versao():
    """Bloco `versao`: qual versao do sistema manda hoje e se o codigo bate com ela.

    Sem changelog ainda, devolve o esqueleto dizendo que nao ha linha de base — que e o
    estado normal de quem nao registrou a v1, e nao um erro.
    """
    try:
        from quant import versoes as vr
        return vr.resumo()
    except Exception as e:                                   # o painel nunca cai por isso
        log(f"changelog de versoes indisponivel ({type(e).__name__}: {e})")
        return {"vigente": None, "descricao": None, "desde": None, "em_paralelo": [],
                "mudancas_no_ano": 0, "limite_ano": 2, "pode_mudar": True,
                "motivo_bloqueio": None, "config_confere": False, "divergencia": [],
                "aviso": f"changelog indisponivel ({type(e).__name__})",
                "cadeia_ok": True, "cadeia_quebra": None}


MESA_DO_DIA = {}        # o cartao "Visao da mesa" montado junto com a boleta; `main` o leva para o painel


def bloco_boleta(dados, estado, data, capital, frescor_dados, gate_passou, seguro, usar_mesa=True):
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
    precos = precos_do_dia(dados, data, mes)
    adtv = mes.set_index("ticker")["adtv21"].to_dict()
    setor = mes.set_index("ticker")["setor"].to_dict()
    # Visao da mesa (quant/mesa.py): veto do que a mesa marcou com conviccao -2 e ajuste pequeno de peso. So quando ha
    # visao fresca; sem ela a carteira e a de sempre. `usar_mesa=False` (testes, dado sintetico) desliga.
    visao, motivo_mesa, aplicado, ajuste = None, None, [], None
    if usar_mesa and dados.get("origem") == "real":
        from quant import mesa
        visao, motivo_mesa = mesa.ler(hoje=None)
        if visao is not None:
            mes, aplicado = mesa.vetar(mes, visao)
            antes = {}

            def ajuste(w, _visao=visao, _setor=setor, _antes=antes):
                _antes.update({t: float(v) for t, v in w.items()})
                return mesa.ajustar_pesos(w, mesa.fatores_de_peso(list(w.index), _visao, _setor), cap=ct.CAP_NOME)
    # Fracao do patrimonio em acoes: o padrao do codigo, ou a decisao do Douglas em carteira_config.json (inclusive a
    # entrada escalonada com data). Em dado sintetico e nos testes vale sempre o padrao.
    exposicao = ct.EXPOSICAO_ALVO
    if usar_mesa and dados.get("origem") == "real":
        from quant import config_carteira
        exposicao, _ = config_carteira.exposicao_acoes(data)
    alvo = ct.carteira_alvo(mes, estado, precos, adtv=adtv, setor=setor, exposicao=exposicao,
                            patrimonio=estado.get("patrimonio", capital), data=data, ajuste_pesos=ajuste)
    if usar_mesa and dados.get("origem") == "real":
        from quant import mesa
        if visao is not None and len(alvo.get("pesos", [])):
            aplicado = aplicado + mesa.registro_dos_pesos(alvo["pesos_sem_ajuste"], alvo["pesos"], visao, setor)
        MESA_DO_DIA.clear()
        MESA_DO_DIA.update(mesa.bloco(visao, motivo_mesa, aplicado))
    try:
        return bo.gerar(alvo["ordens"], precos, adtv, data,
                        frescor_dados=frescor_dados, gate_passou=gate_passou,
                        caixa_disponivel=estado.get("caixa"), hedge=alvo.get("hedge"))
    except Exception as e:                                   # a boleta nunca derruba a rodada
        log(f"boleta falhou ({type(e).__name__}: {e})")
        vazio["motivo_bloqueio"] = [f"falha ao gerar a boleta: {type(e).__name__}"]
        return vazio


def precos_do_dia(dados, data, mes_sinais=None, janela=15):
    """Ultimo fechamento disponivel ate `data`: ticker -> preco.

    ACHADO DA FASE 4. O painel de sinais e MENSAL. Usar o `preco` dele para precificar
    ordem e posicao congela tudo no ultimo pregao do mes anterior: no dia 20, o limite de
    compra sai defasado tres semanas. No primeiro ensaio da campanha isso apareceu escrito
    — ordem de compra com limite 15,76 num papel que negociou o dia inteiro entre 16,43 e
    16,49, reemitida todo pregao, nunca executada. Ranking, vol, ADTV e setor continuam
    vindo do painel mensal, que e o certo; PRECO vem da cotacao mais recente.

    `janela` limita a varredura aos ultimos dias corridos para nao reprocessar o historico
    inteiro a cada pregao da campanha.
    """
    precos = {}
    cot = (dados or {}).get("cotacoes")
    if cot is not None and len(cot) and {"ticker", "data", "fec"} <= set(cot.columns):
        d = cot[["ticker", "data", "fec"]].copy()
        d["data"] = pd.to_datetime(d["data"])
        fim = pd.Timestamp(data)
        d = d[(d["data"] <= fim) & (d["data"] >= fim - pd.Timedelta(days=int(janela)))]
        if len(d):
            ult = d.sort_values("data").groupby("ticker")["fec"].last()
            precos = {str(t): float(v) for t, v in ult.items()
                      if np.isfinite(float(v)) and float(v) > 0}
    if mes_sinais is not None and len(mes_sinais) and "preco" in mes_sinais:
        # papel que nao negociou na janela mantem o preco do painel, com o aviso implicito
        # de que e velho: sem isso ele sumiria da carteira por falta de preco.
        for t, v in mes_sinais.set_index("ticker")["preco"].items():
            t = str(t)
            if t not in precos and np.isfinite(float(v)) and float(v) > 0:
                precos[t] = float(v)
    return precos


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
    if dados["origem"] == "real":
        # A boleta exige o BDI do ultimo pregao (FONTES_OBRIGATORIAS) e este bloco nunca o
        # informava: com banco real, gate aprovado e BDI arquivado, a boleta saia bloqueada
        # por "BDI ausente" para sempre (primeira rodada real, 08/10/2026).
        try:
            from quant.execucao import boleta as bo
            fontes["bdi"] = (bo._ultima_data_bdi(), 1)
        except Exception as e:
            log(f"sem data do BDI ({type(e).__name__}: {e})")
            fontes["bdi"] = (None, 1)
    fres = frescor(hoje, fontes)
    extras = []
    if dados["origem"] != "real":
        extras.append("dados sinteticos: nenhum numero desta tela e resultado de estrategia")
    seguro, motivos = modo_seguro(fres, gate_passou, extras)

    estado = _estado_atual(capital, dados, hoje)
    mes = _mes_sinais(dados["sinais"], hoje)
    precos = precos_do_dia(dados, hoje, mes)

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
        "paper": bloco_paper(dados),
        "versao": bloco_versao(),
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


def _exposicao_de_hoje(hoje=None):
    from quant import config_carteira
    return config_carteira.exposicao_acoes(hoje)[0]


def bloco_regime(ibov=None, hoje=None):
    """Leitura de regime do Ibovespa para o cartao "Regime do mercado" da tela. SO INFORMACAO: nao mexe na carteira nem
    na protecao. O Douglas pediu em 10/10/2026 que o robo lesse o momento do mercado (alta ou baixa) para dosar acoes e
    venda de indice; os testes de 2012 a 2015 e de 2016 a 2026 (periodo final, aberto em 10/10/2026) mostraram que mexer
    na protecao por esta leitura PIOROU o resultado (quant/saida/pesquisa_carteira/RESULTADO.md e RESULTADO_HOLDOUT.md),
    entao ela fica medida e a vista, como as leituras "so medido" do robo
    de day trade, ate haver evidencia. `ibov`: DataFrame (data, fec); sem ele, baixa do Yahoo. Devolve None sem dado."""
    import pandas as pd

    from quant import carteira as ct
    from quant import regime as rg
    from quant.dados import mercado
    from quant.execucao import protecao
    try:
        if ibov is None:
            fim = pd.Timestamp(hoje).date() if hoje is not None else agora_brt().date()
            ibov = mercado.baixar_ibov_yahoo(ini=fim - pd.Timedelta(days=900), fim=fim)
        if ibov is None or len(ibov) < rg.JANELA_PICO + rg.CONFIRMACAO + 5:
            return None
        s = pd.Series(pd.to_numeric(ibov["fec"], errors="coerce").to_numpy(), index=pd.to_datetime(ibov["data"])).dropna().sort_index()
        d = rg.detectar(s)
        ok = d.dropna(subset=["estado"])
        if not len(ok):
            return None
        u = ok.iloc[-1]
        mesmo = (ok["estado"] == u["estado"]).to_numpy()
        estado = str(u["estado"]).lower()                  # a tela usa alta | neutro | baixa
        i = len(mesmo) - 1
        while i > 0 and mesmo[i - 1]:
            i -= 1
        ultimo = float(s.loc[ok.index[-1]])
        ml, mc = float(s.rolling(rg.JANELA_LONGA).mean().iloc[-1]), float(s.rolling(rg.JANELA_CURTA).mean().iloc[-1])
        r12 = float(s.iloc[-1] / s.iloc[-1 - rg.JANELA_MOM] - 1.0) if len(s) > rg.JANELA_MOM else None
        pico = float(s.iloc[-1] / s.rolling(rg.JANELA_PICO).max().iloc[-1] - 1.0)
        pts = lambda x: f"{x:,.0f}".replace(",", ".")                     # noqa: E731
        pct = lambda x: f"{x * 100:+.1f}%".replace(".", ",")              # noqa: E731
        fav = lambda v: "a favor da alta" if v == 1.0 else "contra"       # noqa: E731
        votos = int(u["soma_votos"]) if pd.notna(u["soma_votos"]) else None
        nomes = {"alta": "ALTA", "neutro": "NEUTRO", "baixa": "BAIXA"}
        return {
            "estado": estado, "desde": str(ok.index[i].date()), "data": str(ok.index[-1].date()), "votos": votos,
            "so_informacao": True,
            "texto": (f"Leitura {nomes.get(estado, estado.upper())}: {votos} de 4 sinais de tendência do Ibovespa a favor da alta. "
                      "É só informação: nos dois testes (2012 a 2015 e 2016 a 2026), aumentar ou zerar a proteção por esta "
                      "leitura piorou o resultado; em 2020 as variantes com regime perderam de 21% a 27%, contra +0,5% da "
                      f"carteira sem proteção. A carteira segue com {_exposicao_de_hoje(hoje) * 100:.0f}% em ações e a proteção em mini-índice no nível que o "
                      f"Douglas definiu ({protecao.razao() * 100:.0f}% do valor das ações)."),
            "exposicao_acoes_pct": round(_exposicao_de_hoje(hoje) * 100.0, 1), "protecao_pct": round(protecao.razao() * 100.0, 1),
            "indicadores": [
                {"nome": "Ibovespa contra a média de 200 pregões", "valor": f"{pts(ultimo)} contra {pts(ml)}", "leitura": fav(u["acima_media_longa"])},
                {"nome": "Média de 50 contra a de 200 pregões", "valor": f"{pts(mc)} contra {pts(ml)}", "leitura": fav(u["media_curta_acima"])},
                {"nome": "Retorno de 12 meses", "valor": pct(r12) if r12 is not None else "sem dado", "leitura": fav(u["mom12_positivo"])},
                {"nome": "Distância da máxima de 12 meses", "valor": pct(pico), "leitura": fav(u["perto_do_pico"])},
            ],
            "fonte": "Ibovespa diário (Yahoo); detector em quant/regime.py",
        }
    except Exception as e:                                  # a leitura e enfeite: nunca derruba a rodada da manha
        log(f"regime: sem leitura ({type(e).__name__}: {e})")
        return None


def gravar_painel(painel, caminho=ARQ_PAINEL):
    garantir_dir(os.path.dirname(caminho))
    gravar_json(caminho, painel)
    return caminho


def main(argv=None):
    from quant.validacao import gate
    ap = argparse.ArgumentParser(description="Rodada diaria do sistema quant (M14)")
    ap.add_argument("--paper", action="store_true", help="fills simulados (padrao)")
    ap.add_argument("--real", action="store_true", help="usa os fills registrados no livro")
    ap.add_argument("--capital", type=float, default=CAPITAL_PADRAO)
    ap.add_argument("--data", default=None)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)
    modo = "real" if args.real else "paper"
    # O gate e quem diz se passou, nao uma flag: `modo_seguro` existe para nao aceitar
    # declaracao humana. Sem artefato, `passou` vem None e a boleta fica bloqueada.
    passou, motivo_gate = gate.ler()
    log(motivo_gate)
    painel = rodar(modo=modo, capital=args.capital, data=args.data, seed=args.seed,
                   gate_passou=passou)
    regime = bloco_regime(hoje=args.data)
    if regime is not None:
        painel["regime"] = regime
    if MESA_DO_DIA:
        painel["mesa"] = dict(MESA_DO_DIA)
    if modo == "paper":                                    # o livro inteiro: pesos, mao e queda contra o orcamento (quant/risco/livro.py)
        try:
            from quant.risco import livro
            painel["livro"] = livro.ler_bloco() or livro.montar(args.capital or 100_000.0, hoje=args.data, gravar_historico=False)
        except Exception as e:                             # bloco informativo: nunca derruba a boleta
            log(f"bloco do livro nao montou: {type(e).__name__}: {e}")
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
