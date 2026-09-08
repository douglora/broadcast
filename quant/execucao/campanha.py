"""
Campanha de paper trading (Fase 4): a rotina rodada pregao a pregao, com o registro que
decide se o sistema pode receber dinheiro de verdade.

O QUE A FASE 4 E: de 3 a 6 meses executando a rotina como se fosse real, cobrindo pelo
menos um roll do mini-indice e um rebalanceamento de indice. Isso e tempo de CALENDARIO e
nao pode ser comprimido. O que este modulo entrega e a maquina que roda todo dia, o
registro que ela acumula e a avaliacao dos criterios de passagem — mais um ENSAIO
sobre o mercado sintetico, que prova que o laco fecha e nada mais.

  Ensaio != campanha. Um ensaio sobre dado sintetico nao mede slippage de verdade: mede
  que boleta vira fill, que fill vira posicao e que posicao vira a boleta do dia seguinte
  sem quebrar. `avaliar()` marca `origem` em todo resultado exatamente para essa confusao
  nao acontecer depois.

CRITERIOS DE PASSAGEM (secao 10 do plano, "Fase 4"), avaliados por `avaliar()`:
  1. slippage realizado <= 1,5x o modelado — medido contra o VWAP do dia inteiro;
  2. taxa de execucao >= 60%;
  3. zero erros operacionais em 2 meses seguidos;
  4. cobertura de calendario: 3 meses, 60 pregoes, >= 1 roll do mini-indice e
     >= 1 rebalanceamento de indice (jan, mai, set);
  5. nenhum parametro alterado durante a campanha.

Viram nove linhas no placar porque cada um se decompoe no que da para medir separado; o
front mostra as nove com valor, gatilho e semaforo.

O CRITERIO 3 DEPENDE DE VOCE. "Erro operacional" e ordem enviada errada, ordem esquecida,
preco digitado errado, margem chamada sem caixa. Nada disso da para o programa detectar
sozinho: ele so sabe o que executou, nao o que voce quis executar. Por isso existe
`registrar_erro()` e um diario em `quant/saida/diario_erros.csv`. Um diario vazio nao
significa zero erros — significa que ninguem anotou. Por isso o mes so conta depois de
ASSINADO (`conferir_mes`): sem assinatura `meses_sem_erro` vem None e o criterio nao passa.

ACHADO (limitacao conhecida): o caixa da campanha e creditado no ato da venda, e nao em
D+2. `bo.gerar` recebe `estado["caixa"]` como caixa disponivel, entao uma venda de hoje
pode financiar uma compra de hoje — o que a B3 nao permite. No ensaio isso quase nao
aparece porque as ordens sao pequenas perto do caixa, mas com carteira cheia e um dia de
rebalanceamento grande a campanha compraria mais do que a corretora deixaria. Corrigir
exige carregar a fila de liquidacao no estado; enquanto nao existir, a taxa de execucao
medida e OTIMISTA por esse lado.

O CRITERIO 5 e verificado por hash: `avaliar()` compara o hash da configuracao no inicio
da campanha com o de agora. Mexer num percentil no meio do paper zera a campanha, e e
para zerar mesmo — o paper so vale se testar UMA versao.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

from quant.comum import DIR_SAIDA, garantir_dir, gravar_atomico, log
from quant.dados import calendario
from quant.execucao import boleta as bo
from quant.execucao import paper

ARQ_SESSOES = os.path.join(DIR_SAIDA, "campanha_sessoes.csv")
# O ensaio NUNCA escreve no registro da campanha: sessao sintetica misturada com sessao
# real contamina o placar da fase 4 e nao ha como separar depois.
ARQ_SESSOES_ENSAIO = os.path.join(DIR_SAIDA, "campanha_sessoes_ensaio.csv")
ARQ_ERROS = os.path.join(DIR_SAIDA, "diario_erros.csv")
ARQ_CONFIG = os.path.join(DIR_SAIDA, "campanha_config.json")
ARQ_CONFERENCIAS = os.path.join(DIR_SAIDA, "campanha_conferencias.csv")

COLUNAS_SESSAO = ["data", "boleta", "emitida", "motivo_bloqueio", "n_ordens",
                  "qtd_pedida", "qtd_executada", "taxa_execucao", "financeiro",
                  "slippage_bps", "slippage_vwap_bps", "custo_estimado", "custo_realizado",
                  "n_fills", "patrimonio", "n_posicoes", "contratos", "hedge_motivo",
                  "origem"]
COLUNAS_ERRO = ["data", "tipo", "descricao", "impacto"]
COLUNAS_CONFERENCIA = ["mes", "conferido_em", "observacao"]
TIPOS_ERRO = ("ordem_errada", "ordem_esquecida", "preco_errado", "quantidade_errada",
              "margem_chamada", "parametro_alterado", "dado_velho", "outro")

CRITERIOS = {
    "sessoes_min": 60,          # ~3 meses de pregoes
    "meses_min": 3,
    "execucao_min": 0.60,
    "slippage_max_x": 1.5,      # do modelado
    "erros_max": 0,
    "meses_sem_erro": 2,
    "rolls_min": 1,             # ao menos um roll do mini-indice
    "rebalances_min": 1,        # ao menos um rebalanceamento de indice
}
MESES_REBALANCE_INDICE = (1, 5, 9)   # a B3 reequilibra as carteiras teoricas em jan, mai e set
NEGOCIOS_POR_PREGAO = 40             # granularidade da fita sintetica do ensaio


# ─────────────────────────────────────────────────────────────
# Utilitarios puros
# ─────────────────────────────────────────────────────────────
def _vazio(colunas):
    return pd.DataFrame(columns=colunas)


def _anexar(atuais, novas):
    """concat que nao reclama de quadro vazio (o pandas 2 avisa sobre o dtype das colunas)."""
    if atuais is None or len(atuais) == 0:
        return novas.copy()
    return pd.concat([atuais, novas], ignore_index=True)


def hash_config(config):
    """Impressao digital da configuracao, para provar que nada mudou durante a campanha."""
    texto = json.dumps(config or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(texto.encode()).hexdigest()[:16]


def config_da_estrategia():
    """Todo parametro que muda o que a estrategia faz. Mexer em qualquer um zera a campanha."""
    from quant import carteira as ct
    from quant import custos as cst
    from quant import sinais as sg
    return {
        "sinais": {"pct_momentum": sg.PCT_MOMENTUM, "pct_gpoa": sg.PCT_GPOA,
                   "quartil_crescimento": sg.QUARTIL_CRESCIMENTO,
                   "decil_valor": sg.DECIL_VALOR, "decil_vol": sg.DECIL_VOL,
                   "dl_ebitda_max": sg.DL_EBITDA_MAX, "pesos": sg.PESOS,
                   "mom": [sg.MOM_INI, sg.MOM_FIM, sg.MOM6_INI]},
        "carteira": {"n": ct.N_ALVO, "banda": list(ct.BANDA), "cap": ct.CAP_NOME,
                     "piso": ct.PISO_NOME, "cap_setor": ct.CAP_SETOR,
                     "cap_iliquidos": ct.CAP_ILIQUIDOS, "exposicao": ct.EXPOSICAO_ALVO,
                     "rank_saida": ct.RANK_SAIDA, "meses_max": ct.MESES_MAX,
                     "limiar_custo": ct.LIMIAR_CUSTO, "limiar_peso": ct.LIMIAR_PESO,
                     "valor_min": ct.VALOR_MIN_ORDEM},
        "custos": {"b3": cst.TAXA_B3, "spread": [list(f) for f in cst.FAIXAS_SPREAD],
                   "fracionario": cst.ADICIONAL_FRACIONARIO},
        "boleta": {"hora": bo.HORA_ENVIO, "participacao": bo.MAX_PARTICIPACAO,
                   "adtv_fatiar": bo.ADTV_FATIAR},
    }


def rebalances_indice(ini, fim):
    """Quantos rebalanceamentos de carteira teorica a janela cobre (jan, mai e set)."""
    a, b = pd.Timestamp(ini), pd.Timestamp(fim)
    if a > b:
        return 0
    meses = pd.period_range(a.to_period("M"), b.to_period("M"), freq="M")
    return int(sum(1 for m in meses if m.month in MESES_REBALANCE_INDICE))


def fita_sintetica(cotacoes, data, seed=0, n=NEGOCIOS_POR_PREGAO):
    """Fita de negocios plausivel a partir da barra diaria. SO PARA O ENSAIO.

    Com dado real quem manda e `paper.carregar_negocios(data)`, que le o negocio-a-negocio
    que o arquivador guarda. Aqui os precos passeiam entre a minima e a maxima do dia e o
    volume e repartido igualmente pelas negociacoes — o suficiente para a ordem limitada
    ter de decidir se executa, e nada alem disso. Nao mede slippage de verdade.
    """
    if cotacoes is None or len(cotacoes) == 0:
        return _vazio(paper.COLUNAS_NEGOCIOS)
    d = cotacoes[pd.to_datetime(cotacoes["data"]) == pd.Timestamp(data)]
    if d.empty:
        return _vazio(paper.COLUNAS_NEGOCIOS)
    rng = np.random.default_rng(int(pd.Timestamp(data).strftime("%Y%m%d")) + int(seed))
    horas = [f"{10 + (i * 7) // 60:02d}:{(i * 7) % 60:02d}:00" for i in range(n)]
    linhas = []
    for _, r in d.iterrows():
        abe, mx, mn, fec = (float(r.get(c, np.nan)) for c in ("abe", "max", "min", "fec"))
        if not np.isfinite(fec) or fec <= 0:
            continue
        abe = abe if np.isfinite(abe) and abe > 0 else fec
        mx = mx if np.isfinite(mx) and mx > 0 else max(abe, fec)
        mn = mn if np.isfinite(mn) and mn > 0 else min(abe, fec)
        # caminho: abre, passeia dentro da faixa do dia, fecha no fechamento
        passo = rng.uniform(0.0, 1.0, n)
        precos = mn + (mx - mn) * passo
        precos[0], precos[-1] = abe, fec
        qtd_total = float(r.get("qtd", 0) or 0)
        por_negocio = max(qtd_total / n, 1.0)
        for h, p in zip(horas, precos):
            linhas.append({"ticker": r["ticker"], "hora": h, "preco": round(float(p), 2),
                           "quantidade": por_negocio})
    return pd.DataFrame(linhas, columns=paper.COLUNAS_NEGOCIOS)


def _ultima_data(df, coluna="data", ate=None):
    if df is None or len(df) == 0 or coluna not in df:
        return None
    d = pd.to_datetime(df[coluna])
    if ate is not None:
        d = d[d <= pd.Timestamp(ate)]
    return None if d.empty else d.max().date()


def frescor_do_dia(dados, data):
    """Idade das fontes no formato que `boleta.modo_seguro` cobra.

    NO ENSAIO O MERCADO SINTETICO FAZ O PAPEL DE TODAS AS FONTES. Nao existe BDI
    sintetico, e o BDI e fonte obrigatoria: sem ele a boleta bloqueia todo pregao, nenhuma
    ordem e emitida e o ensaio nao prova nada. Carimbar o BDI com a data da cotacao e uma
    licenca do ensaio e SO DELE — com dado real (`origem="real"`) o BDI vem do arquivador
    e a ausencia dele tem de continuar bloqueando, que e o comportamento testado na fase 3.
    """
    data = pd.Timestamp(data)
    cot = _ultima_data(dados.get("cotacoes"), "data", ate=data)
    sin = _ultima_data(dados.get("sinais"), "data", ate=data)
    cdi = dados.get("cdi")
    cdi_d = None
    if cdi is not None and len(cdi):
        idx = pd.to_datetime(pd.Index(cdi.index))
        idx = idx[idx <= data]
        cdi_d = None if idx.empty else idx.max().date()
    if str(dados.get("origem")) == "real":
        bdi = dados.get("ultima_bdi")
        bdi = pd.Timestamp(bdi).date() if bdi is not None else None
    else:
        bdi = cot
    return bo.frescor(data.date(), cotahist=cot, bdi=bdi, sinais=sin, cdi=cdi_d)


# ─────────────────────────────────────────────────────────────
# Diario de erros operacionais
# ─────────────────────────────────────────────────────────────
def registrar_erro(data, tipo, descricao, impacto=0.0, caminho=ARQ_ERROS):
    """Anota um erro operacional. Quem anota e o humano: o programa nao sabe o que voce quis."""
    tipo = str(tipo).strip().lower()
    if tipo not in TIPOS_ERRO:
        raise ValueError(f"tipo de erro desconhecido: {tipo}; use um de {TIPOS_ERRO}")
    linha = {"data": str(pd.Timestamp(data).date()), "tipo": tipo,
             "descricao": str(descricao).replace(";", ","), "impacto": float(impacto)}
    novo = _anexar(carregar_erros(caminho), pd.DataFrame([linha]))
    novo = novo.drop_duplicates(["data", "tipo", "descricao"], keep="last")
    _gravar_csv(novo[COLUNAS_ERRO], caminho)
    return linha


def carregar_erros(caminho=ARQ_ERROS):
    if not os.path.exists(caminho):
        return _vazio(COLUNAS_ERRO)
    try:
        d = pd.read_csv(caminho, sep=";")
    except Exception:
        return _vazio(COLUNAS_ERRO)
    for c in COLUNAS_ERRO:
        if c not in d:
            d[c] = None
    return d[COLUNAS_ERRO]


def conferir_mes(mes, observacao="", caminho=ARQ_CONFERENCIAS):
    """Assina um mes como conferido: a rotina rodou e voce olhou se houve erro.

    E o unico jeito honesto de o criterio 3 ("zero erros operacionais em 2 meses") poder
    ser satisfeito. Diario vazio nao prova nada — pode ser mes limpo ou mes em que ninguem
    anotou. So o humano sabe, entao e o humano que assina, mes a mes.
    """
    linha = {"mes": str(pd.Period(pd.Timestamp(str(mes) + "-01" if len(str(mes)) == 7
                                               else str(mes)), "M")),
             "conferido_em": str(date.today()), "observacao": str(observacao).replace(";", ",")}
    novo = _anexar(carregar_conferencias(caminho), pd.DataFrame([linha]))
    novo = novo.drop_duplicates("mes", keep="last").sort_values("mes")
    _gravar_csv(novo[COLUNAS_CONFERENCIA], caminho)
    return linha


def carregar_conferencias(caminho=ARQ_CONFERENCIAS):
    if not os.path.exists(caminho):
        return _vazio(COLUNAS_CONFERENCIA)
    try:
        d = pd.read_csv(caminho, sep=";")
    except Exception:
        return _vazio(COLUNAS_CONFERENCIA)
    for c in COLUNAS_CONFERENCIA:
        if c not in d:
            d[c] = None
    return d[COLUNAS_CONFERENCIA]


def meses_sem_erro(erros, ate=None, conferidos=None):
    """Quantos meses seguidos, ate `ate`, foram CONFERIDOS e terminaram sem erro anotado.

    Sem meses assinados devolve None: "nao da para afirmar" — que e diferente de zero. Um
    mes so conta quando alguem assinou que olhou (`conferir_mes`) e nao anotou erro nele.
    """
    fim = pd.Timestamp(ate or date.today()).to_period("M")
    if conferidos is None or len(conferidos) == 0:
        return None                      # None = nao da para afirmar; ver `avaliar`
    assinados = {str(m) for m in (conferidos["mes"].dropna()
                                  if isinstance(conferidos, pd.DataFrame) else conferidos)}
    com_erro = set()
    if erros is not None and len(erros):
        com_erro = {str(pd.Period(pd.Timestamp(d), "M")) for d in erros["data"].dropna()}
    m = fim
    if str(m) not in assinados and str(m) not in com_erro:
        # o mes corrente ainda esta rodando e por isso nao foi assinado; isso nao pode
        # zerar uma sequencia limpa de meses fechados. Mes com erro anotado NAO e pulado.
        m = m - 1
    n = 0
    while str(m) in assinados and str(m) not in com_erro and n < 240:
        n += 1
        m = m - 1
    return n


# ─────────────────────────────────────────────────────────────
# Uma sessao
# ─────────────────────────────────────────────────────────────
def rodar_sessao(dados, estado, data, capital, gate_passou=None, negocios=None,
                 origem="ensaio", estresse=1.0, frescor_dados=None):
    """Um pregao inteiro: sinais -> carteira -> boleta -> fills -> posicao.

    Devolve (registro da sessao, estado atualizado, boleta, fills). Nunca levanta: sessao
    que nao produz boleta vira uma linha com `emitida=False` e o motivo.
    """
    from quant import carteira as ct
    from quant import rodar_diario as rd

    data = pd.Timestamp(data)
    registro = {c: None for c in COLUNAS_SESSAO}
    registro.update({"data": str(data.date()), "boleta": data.strftime("%Y%m%d"),
                     "emitida": False, "motivo_bloqueio": "", "n_ordens": 0,
                     "qtd_pedida": 0.0, "qtd_executada": 0.0, "taxa_execucao": None,
                     "financeiro": 0.0, "custo_estimado": 0.0, "custo_realizado": 0.0,
                     "n_fills": 0, "origem": origem,
                     "patrimonio": float(estado.get("patrimonio") or capital),
                     "n_posicoes": len(estado.get("posicoes") or {}),
                     "contratos": int((estado.get("hedge") or {}).get("contratos") or 0),
                     "hedge_motivo": ""})

    mes = rd._mes_sinais(dados.get("sinais"), data)
    if mes is None or len(mes) == 0:
        registro["motivo_bloqueio"] = "sem sinais para a data"
        return registro, estado, None, _vazio(paper.COLUNAS_FILL)

    precos = rd.precos_do_dia(dados, data, mes)   # fechamento do dia, nao o do painel mensal
    adtv = mes.set_index("ticker")["adtv21"].to_dict()
    setor = mes.set_index("ticker")["setor"].to_dict()
    fres = frescor_dados if frescor_dados is not None else frescor_do_dia(dados, data)
    alvo = ct.carteira_alvo(mes, estado, precos, adtv=adtv, setor=setor,
                            patrimonio=estado.get("patrimonio", capital),
                            estresse=estresse, data=data)
    registro["hedge_motivo"] = str(alvo["hedge"].get("motivo") or "")
    b = bo.gerar(alvo["ordens"], precos, adtv, data, frescor_dados=fres,
                 gate_passou=gate_passou, caixa_disponivel=estado.get("caixa"),
                 hedge=alvo.get("hedge"), estresse=estresse)
    registro["emitida"] = bool(b.get("emitida"))
    registro["motivo_bloqueio"] = "; ".join(b.get("motivo_bloqueio") or [])
    registro["n_ordens"] = len(b.get("ordens") or [])
    registro["custo_estimado"] = float(b.get("custo_total") or 0.0)
    if b.get("emitida"):
        # O hedge tem de ser gravado no dia em que a boleta sai, TENHA OU NAO ordem de acao.
        # Enquanto isso morava dentro de `_aplicar_fills`, um dia sem ordem nenhuma deixava o
        # vencimento antigo no estado e o roll reaparecia na sessao seguinte, e na seguinte,
        # ate cair um pregao com fill — tres "rolls" registrados para um roll so.
        estado = _aplicar_hedge(estado, alvo)
        registro["contratos"] = int((estado.get("hedge") or {}).get("contratos") or 0)
    if not b.get("emitida") or not b.get("ordens"):
        return registro, estado, b, _vazio(paper.COLUNAS_FILL)

    if negocios is None:
        negocios = fita_sintetica(dados.get("cotacoes"), data)
    fills = paper.simular(b, negocios)
    registro["n_fills"] = len(fills)
    # `barras=negocios` e o que faz nascer o slippage contra o VWAP. Sem ele so existe o
    # slippage contra o LIMITE, que e <= 0 por construcao (ordem limitada nunca executa
    # pior que o limite) e por isso nao serve para julgar execucao nenhuma.
    medida = paper.medir_slippage(b, fills, barras=negocios)
    for chave in ("qtd_pedida", "qtd_executada", "taxa_execucao", "financeiro",
                  "slippage_bps", "slippage_vwap_bps", "custo_realizado"):
        registro[chave] = medida.get(chave)
    estado = _aplicar_fills(estado, fills, precos)
    registro["patrimonio"] = float(estado["patrimonio"])
    registro["n_posicoes"] = len(estado["posicoes"])
    registro["contratos"] = int((estado.get("hedge") or {}).get("contratos") or 0)
    return registro, estado, b, fills


def _aplicar_fills(estado, fills, precos):
    """Aplica as execucoes ao estado, em VALOR (a posicao evolui por retorno total)."""
    for _, f in (fills if fills is not None else _vazio(paper.COLUNAS_FILL)).iterrows():
        t = str(f["ticker"])
        valor = float(f["qtd"]) * float(f["preco"])
        custo = float(f.get("corretagem", 0.0) or 0.0) + float(f.get("emolumentos", 0.0) or 0.0)
        pos = estado["posicoes"].get(t)
        if str(f["lado"]).upper().startswith("C"):
            estado["caixa"] -= valor + custo
            if pos is None:
                estado["posicoes"][t] = {"qtd": int(f["qtd"]), "valor": valor, "meses": 0}
            else:
                pos["qtd"] += int(f["qtd"])
                pos["valor"] += valor
        else:
            estado["caixa"] += valor - custo
            if pos is not None:
                pos["qtd"] -= int(f["qtd"])
                pos["valor"] = max(pos["valor"] - valor, 0.0)
                if pos["qtd"] <= 0 or pos["valor"] <= 1e-6:
                    estado["posicoes"].pop(t, None)
    estado["patrimonio"] = estado["caixa"] + sum(p["valor"] for p in estado["posicoes"].values())
    return estado


def _aplicar_hedge(estado, alvo):
    """Grava a decisao de hedge no estado. Sem isso o roll nunca termina (ver rodar_sessao)."""
    h = (alvo or {}).get("hedge") or {}
    estado["hedge"] = {"contratos": int(h.get("contratos") or 0),
                       "vencimento": h.get("vencimento"), "nivel_entrada": np.nan}
    return estado


# ─────────────────────────────────────────────────────────────
# Campanha
# ─────────────────────────────────────────────────────────────
def rodar_campanha(dados, ini, fim, capital=100_000.0, gate_passou=None, origem="ensaio",
                   estresse=1.0, retornos=None, verboso=False):
    """Roda a rotina pregao a pregao e devolve o DataFrame de sessoes.

    Entre um pregao e o outro a posicao rende o retorno total do dia, exatamente como no
    backtest: sem isso a campanha nunca rebalancearia nada, porque os pesos nunca sairiam
    do lugar.
    """
    from quant import carteira as ct
    estado = ct.estado_inicial(capital, pd.Timestamp(ini))
    ret = retornos if retornos is not None else dados.get("retornos")
    dias = [pd.Timestamp(d) for d in calendario.pregoes(ini, fim)]
    linhas = []
    for i, d in enumerate(dias):
        if i > 0 and ret is not None and len(ret) and d in ret.index:
            estado = _render(estado, ret.loc[d])
        registro, estado, _b, _f = rodar_sessao(dados, estado, d, capital,
                                                gate_passou=gate_passou, origem=origem,
                                                estresse=estresse)
        linhas.append(registro)
        if verboso and (i % 10 == 0 or registro["emitida"]):
            log(f"{d.date()} emitida={registro['emitida']} ordens={registro['n_ordens']} "
                f"exec={registro['taxa_execucao']}")
    return pd.DataFrame(linhas, columns=COLUNAS_SESSAO)


def _render(estado, retornos_do_dia):
    for t, p in list(estado["posicoes"].items()):
        r = float(retornos_do_dia.get(t, np.nan)) if retornos_do_dia is not None else np.nan
        if np.isfinite(r):
            p["valor"] *= (1.0 + r)
    estado["patrimonio"] = estado["caixa"] + sum(p["valor"] for p in estado["posicoes"].values())
    return estado


# ─────────────────────────────────────────────────────────────
# Avaliacao dos criterios da fase 4
# ─────────────────────────────────────────────────────────────
def avaliar(sessoes, erros=None, config_inicial=None, config_atual=None,
            modelado_bps=None, criterios=CRITERIOS, origem=None, conferidos=None):
    """Os criterios de passagem da fase 4, cada um com o numero corrente e o veredito.

    `origem` ('ensaio' ou 'real') e carimbado no resultado: passar num ensaio sobre dado
    sintetico nao e passar na fase 4, e `passou` so fica True com origem real.
    """
    c = dict(criterios)
    s = sessoes if sessoes is not None else _vazio(COLUNAS_SESSAO)
    emitidas = _emitidas(s)
    origem = origem or (str(s["origem"].iloc[0]) if len(s) and "origem" in s else "ensaio")

    pedida = float(pd.to_numeric(emitidas.get("qtd_pedida"), errors="coerce").fillna(0).sum()) if len(emitidas) else 0.0
    executada = float(pd.to_numeric(emitidas.get("qtd_executada"), errors="coerce").fillna(0).sum()) if len(emitidas) else 0.0
    taxa = (executada / pedida) if pedida > 0 else None
    # Contra o VWAP, e sem abs(): positivo e desfavoravel, e execucao MELHOR que o
    # modelado nao pode virar reprovacao so por estar longe do numero modelado.
    slip = _ponderado(emitidas, "slippage_vwap_bps", "financeiro")
    razao_slip = (max(slip, 0.0) / abs(modelado_bps)) if (slip is not None and modelado_bps) else None

    n_erros = int(len(erros)) if erros is not None else 0
    sem_erro = meses_sem_erro(erros, ate=s["data"].max() if len(s) else None,
                              conferidos=conferidos)
    rolls = _blocos(s["hedge_motivo"], "roll") if len(s) else 0
    reb = rebalances_indice(s["data"].min(), s["data"].max()) if len(s) else 0
    meses = int(pd.to_datetime(s["data"]).dt.to_period("M").nunique()) if len(s) else 0
    params_ok = (config_inicial is None or config_atual is None or config_inicial == config_atual)

    itens = {
        "sessoes": {"valor": int(len(s)), "gatilho": c["sessoes_min"],
                    "ok": len(s) >= c["sessoes_min"], "formato": "num"},
        "meses": {"valor": meses, "gatilho": c["meses_min"],
                  "ok": meses >= c["meses_min"], "formato": "num"},
        "execucao": {"valor": taxa, "gatilho": c["execucao_min"],
                     "ok": bool(taxa is not None and taxa >= c["execucao_min"]),
                     "formato": "pct"},
        "slippage": {"valor": razao_slip, "gatilho": c["slippage_max_x"],
                     "ok": bool(razao_slip is None or razao_slip <= c["slippage_max_x"]),
                     "formato": "x"},
        "erros": {"valor": n_erros, "gatilho": c["erros_max"],
                  "ok": n_erros <= c["erros_max"], "formato": "num"},
        "meses_sem_erro": {"valor": sem_erro, "gatilho": c["meses_sem_erro"],
                           "ok": bool(sem_erro is not None and sem_erro >= c["meses_sem_erro"]),
                           "formato": "num"},
        "rolls": {"valor": rolls, "gatilho": c["rolls_min"],
                  "ok": rolls >= c["rolls_min"], "formato": "num"},
        "rebalances_indice": {"valor": reb, "gatilho": c["rebalances_min"],
                              "ok": reb >= c["rebalances_min"], "formato": "num"},
        "parametros_estaveis": {"valor": 1 if params_ok else 0, "gatilho": 1,
                                "ok": bool(params_ok), "formato": "bool"},
    }
    avisos = []
    if conferidos is None or len(conferidos) == 0:
        avisos.append("nenhum mes foi conferido e assinado: diario de erros vazio pode ser "
                      "mes limpo ou mes em que ninguem anotou, e so voce sabe qual e. "
                      "Assine com `python3 -m quant.execucao.campanha --conferir AAAA-MM`.")
    if modelado_bps is None:
        avisos.append("sem o custo modelado nao da para dizer se o slippage ficou dentro de "
                      "1,5x; o criterio passa por omissao.")
    if origem != "real":
        avisos.append("ENSAIO sobre dado sintetico: isto nao e a fase 4, e a prova de que o "
                      "laco fecha. A fase 4 sao 3 a 6 meses de calendario com dado real.")
        avisos.append("o slippage do ensaio e ficcao, e costuma sair FAVORAVEL: a fita "
                      "sintetica passeia dentro da faixa do dia e o simulador so casa "
                      "negocio dentro do limite, entao o preco obtido tende a ficar melhor "
                      "que o VWAP. Nao leia esse numero como execucao boa.")
    return {"origem": origem, "itens": itens,
            "passou": bool(all(v["ok"] for v in itens.values()) and origem == "real"),
            "reprovados": [k for k, v in itens.items() if not v["ok"]],
            "avisos": avisos}


def _emitidas(s):
    if s is None or len(s) == 0:
        return _vazio(COLUNAS_SESSAO)
    return s[s["emitida"].astype(bool)]


def _blocos(serie, valor):
    """Quantas vezes `valor` COMECA na serie. Um roll que ficou pendente tres pregoes
    seguidos (boleta bloqueada, por exemplo) e um roll, nao tres."""
    n, antes = 0, None
    for x in (str(v) for v in serie):
        if x == valor and antes != valor:
            n += 1
        antes = x
    return n


def _ponderado(df, coluna, peso):
    if df is None or len(df) == 0 or coluna not in df:
        return None
    v = pd.to_numeric(df[coluna], errors="coerce")
    w = pd.to_numeric(df.get(peso), errors="coerce").abs()
    m = v.notna() & w.notna() & (w > 0)
    if not m.any():
        return None
    return float((v[m] * w[m]).sum() / w[m].sum())


def resumo(sessoes, erros=None, avaliacao=None, conferidos=None):
    """Bloco `paper` do painel (ver docs/painel-contrato.md), em tipos JSON nativos."""
    s = sessoes if sessoes is not None else _vazio(COLUNAS_SESSAO)
    a = avaliacao or avaliar(s, erros, conferidos=conferidos)
    def num(x, casas=6):
        if x is None:
            return None
        v = float(x)
        return None if not np.isfinite(v) else round(v, casas)
    return {
        "origem": a["origem"],
        "sessoes": int(len(s)),
        "primeira": str(s["data"].min()) if len(s) else None,
        "ultima": str(s["data"].max()) if len(s) else None,
        "boletas_emitidas": int(s["emitida"].astype(bool).sum()) if len(s) else 0,
        "taxa_execucao": num(a["itens"]["execucao"]["valor"]),
        "slippage_bps": num(_ponderado(_emitidas(s), "slippage_bps", "financeiro"), 2),
        "slippage_vwap_bps": num(_ponderado(_emitidas(s), "slippage_vwap_bps", "financeiro"), 2),
        "erros": int(a["itens"]["erros"]["valor"]),
        "meses_sem_erro": a["itens"]["meses_sem_erro"]["valor"],
        "rolls": int(a["itens"]["rolls"]["valor"]),
        "passou": bool(a["passou"]),
        "reprovados": list(a["reprovados"]),
        "avisos": list(a["avisos"]),
        "criterios": [{"criterio": k, "valor": num(v["valor"]), "gatilho": num(v["gatilho"]),
                       "formato": v["formato"], "status": "ok" if v["ok"] else "disparado"}
                      for k, v in a["itens"].items()],
    }


# ─────────────────────────────────────────────────────────────
# Disco
# ─────────────────────────────────────────────────────────────
def _gravar_csv(df, caminho):
    garantir_dir(os.path.dirname(caminho))
    gravar_atomico(caminho, df.to_csv(index=False, sep=";"))
    return caminho


def registrar_sessoes(sessoes, caminho=ARQ_SESSOES):
    """Anexa sessoes ao registro da campanha, sem duplicar por data."""
    novo = _anexar(carregar_sessoes(caminho), sessoes)
    novo = novo.drop_duplicates("data", keep="last").sort_values("data")
    return _gravar_csv(novo[COLUNAS_SESSAO], caminho)


def carregar_sessoes(caminho=ARQ_SESSOES):
    if not os.path.exists(caminho):
        return _vazio(COLUNAS_SESSAO)
    try:
        d = pd.read_csv(caminho, sep=";")
    except Exception:
        return _vazio(COLUNAS_SESSAO)
    for c in COLUNAS_SESSAO:
        if c not in d:
            d[c] = None
    return d[COLUNAS_SESSAO]


def abrir_campanha(config=None, caminho=ARQ_CONFIG):
    """Fixa a configuracao no inicio da campanha. Reabrir com config diferente e um erro:
    o paper so vale se testar UMA versao do sistema."""
    cfg = config or config_da_estrategia()
    h = hash_config(cfg)
    if os.path.exists(caminho):
        atual = json.load(open(caminho, encoding="utf-8"))
        if atual.get("hash") != h:
            raise RuntimeError(
                f"a configuracao mudou durante a campanha (era {atual.get('hash')}, virou {h}). "
                "Isso zera o paper: comece uma campanha nova ou desfaca a mudanca.")
        return atual
    estado = {"aberta_em": str(date.today()), "hash": h, "config": cfg}
    garantir_dir(os.path.dirname(caminho))
    gravar_atomico(caminho, json.dumps(estado, ensure_ascii=False, indent=2))
    return estado


def estado_campanha(caminho=ARQ_CONFIG):
    if not os.path.exists(caminho):
        return None
    try:
        return json.load(open(caminho, encoding="utf-8"))
    except Exception:
        return None


def rodar_do_dia(data=None, capital=100_000.0, gate_passou=None, dados=None,
                registrar=True):
    """A sessao de um pregao REAL, rodada depois do fechamento.

    A boleta sai de manha (`rodar_diario --paper`); os fills so podem ser medidos com a
    fita do dia, que o arquivador guarda a noite. Por isso a campanha tem dois momentos, e
    este e o segundo: casa a boleta contra o negocio-a-negocio, grava os fills no livro de
    ordens e registra a linha da campanha.

    Devolve (registro, mensagem). Sem dado real ou sem fita, NAO inventa: devolve
    (None, motivo). Fill imaginado e pior que fill nenhum — ele entra no placar da fase 4.
    """
    from quant import rodar_diario as rd
    data = pd.Timestamp(data or date.today())
    data = pd.Timestamp(calendario.ultimo_pregao_ate(data.date()))
    if dados is None:
        dados = rd.carregar_real(ate=data)
    if dados is None:
        return None, ("sem banco montado: a campanha da fase 4 exige dado real. "
                      "Rode a coleta antes, ou use --ensaio para o ensaio sintetico.")
    negocios = paper.carregar_negocios(data.date())
    if negocios is None or len(negocios) == 0:
        return None, (f"sem o negocio-a-negocio de {data.date()}: nao da para medir "
                      "execucao nenhuma. Arquive a fita do dia e rode de novo.")
    estado = rd._estado_atual(capital, dados, data.date())
    registro, _estado, _b, fills = rodar_sessao(dados, estado, data, capital,
                                                gate_passou=gate_passou,
                                                negocios=negocios, origem="real")
    if registrar:
        if fills is not None and len(fills):
            paper.registrar(fills)
        registrar_sessoes(pd.DataFrame([registro], columns=COLUNAS_SESSAO))
    return registro, "ok"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Campanha de paper trading (fase 4)")
    ap.add_argument("--ensaio", action="store_true",
                    help="roda um ensaio sobre o mercado sintetico (nao e a fase 4)")
    ap.add_argument("--sessao", nargs="?", const="hoje", metavar="DATA",
                    help="registra a sessao real do dia (rodar apos o fechamento)")
    ap.add_argument("--registrar", action="store_true",
                    help="com --ensaio, grava as sessoes no registro SEPARADO do ensaio")
    ap.add_argument("--ini", default=None)
    ap.add_argument("--fim", default=None)
    ap.add_argument("--capital", type=float, default=100_000.0)
    ap.add_argument("--erro", nargs=3, metavar=("DATA", "TIPO", "DESCRICAO"),
                    help="anota um erro operacional no diario")
    ap.add_argument("--conferir", metavar="AAAA-MM",
                    help="assina um mes como conferido (voce olhou e nao houve erro)")
    ap.add_argument("--status", action="store_true", help="avalia a campanha registrada")
    args = ap.parse_args(argv)

    if args.erro:
        linha = registrar_erro(args.erro[0], args.erro[1], args.erro[2])
        print(f"erro anotado: {linha}")
        return 0
    if args.sessao:
        d = None if args.sessao == "hoje" else args.sessao
        registro, msg = rodar_do_dia(d, capital=args.capital)
        if registro is None:
            print(msg)
            return 2
        print(json.dumps(registro, indent=2, ensure_ascii=False, default=str))
        return 0
    if args.conferir:
        linha = conferir_mes(args.conferir)
        print(f"mes conferido: {linha}")
        return 0
    if args.status:
        s, e, cf = carregar_sessoes(), carregar_erros(), carregar_conferencias()
        a = avaliar(s, e, conferidos=cf if len(cf) else None)
        print(json.dumps(resumo(s, e, a), indent=2, ensure_ascii=False))
        return 0 if a["passou"] else 1
    if not args.ensaio:
        print("use --sessao para registrar o pregao de hoje, --ensaio para o ensaio "
              "sintetico, --status para avaliar, --erro para anotar um erro operacional "
              "ou --conferir para assinar um mes")
        return 2

    from quant import rodar_diario as rd
    fim = pd.Timestamp(args.fim or date.today())
    ini = pd.Timestamp(args.ini) if args.ini else fim - pd.DateOffset(months=5)
    dados = rd.carregar_sintetico(seed=7, n_empresas=60, anos=3, ate=fim)
    log(f"ensaio de {ini.date()} a {fim.date()} sobre dado SINTETICO")
    sessoes = rodar_campanha(dados, ini, fim, capital=args.capital, gate_passou=True,
                             origem="ensaio", verboso=True)
    if args.registrar:
        registrar_sessoes(sessoes, ARQ_SESSOES_ENSAIO)
        log(f"sessoes do ensaio em {ARQ_SESSOES_ENSAIO} (fora do registro da campanha)")
    cf = carregar_conferencias()
    a = avaliar(sessoes, carregar_erros(), origem="ensaio",
                conferidos=cf if len(cf) else None)
    print(json.dumps(resumo(sessoes, None, a), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
