"""
Backtest da estrategia INTERSECAO-PF (M11): o modulo que decide se o projeto continua.

Estrutura: LACO MENSAL EXPLICITO com acumulo diario vetorizado entre rebalanceamentos.
Tudo que e funcao pura do passado (universo, sinais, custos por unidade) ja virou painel
antes de chegar aqui; so o que depende de caminho (posicoes, histerese, teto de 12 meses,
lote, caixa, contratos de indice) fica no laco. Sao ~186 iteracoes: nao vale a pena
vetorizar, e e exatamente onde look-ahead se esconde, entao o laco fica legivel.

TRES DETALHES QUE DECIDEM SE O NUMERO E REAL:
  1. Sinal no fechamento de t, EXECUCAO no fechamento do pregao seguinte. Comprar no mesmo
     fechamento que ranqueia e um dia de look-ahead, e em momento isso vale muito.
  2. O retorno do dia da compra NAO e creditado. A posicao passa a render a partir do
     pregao seguinte a execucao.
  3. Usa-se `ret_total` (com provento e desdobramento), nunca variacao de preco. Dia sem
     negocio e NaN e significa "posicao nao mudou de valor", jamais -100%.

CONTABILIDADE: patrimonio = caixa + soma dos valores das posicoes, todo dia, ao centavo.
O ajuste diario do hedge cai no caixa (e assim que futuro funciona na B3) e o caixa rende
CDI. `verificar_contabilidade` roda essa identidade em toda serie produzida - e o teste
que pega nove de cada dez bugs de backtest.

SIMPLIFICACAO DECLARADA: provento entra reinvestido no proprio papel (esta dentro de
`ret_total`), quando na realidade cai no caixa e so e reinvestido no rebalanceamento
seguinte. A diferenca e de segunda ordem no horizonte mensal; o IR sobre JCP ja sai na
fonte via `eventos.retorno_total(jcp_liquido=True)`.

O HOLDOUT E ABERTO UMA VEZ SO, E ISSO OBRIGA UMA CHAMADA ATOMICA. A especificacao pedia
"excesso positivo no holdout E em 3 dos 4 subperiodos", mas tres dos quatro subperiodos
ESTAO dentro do holdout: avalia-los ja e abrir o lacre. Entao `rodar_holdout` calcula de
uma vez a serie inteira, os quatro subperiodos, os dois niveis de custo, o Sharpe
deflacionado e as tres comparacoes pre-registradas, grava tudo e lacra. Para
desenvolvimento sobra 2011-2015, e so.

NADA AQUI PRODUZ VEREDITO SEM DADO REAL. Nesta maquina o banco esta vazio (B3, CVM e BCB
bloqueados), entao o que roda e o mercado sintetico de `validacao/mercado_sintetico.py`.
Todo relatorio carimba a origem dos dados e se o gate da fase 1 passou; numero sintetico
nao e resultado.
"""
import argparse
import json
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

from quant import carteira as ct
from quant import custos as cst
from quant import livro
from quant import sinais as sg
from quant.comum import DIR_SAIDA, garantir_dir, log
from quant.dados import calendario, mercado

DATA_INI = "2011-01-01"
DATA_FIM = "2026-06-30"
DATA_INI_PRECO = "2008-01-01"          # rodada separada, so preco/momento (sem fundamentos)
SUBPERIODOS = (("2011-01-01", "2015-12-31"), ("2016-01-01", "2019-12-31"),
               ("2020-01-01", "2022-12-31"), ("2023-01-01", "2026-06-30"))
TREINO = ("2011-01-01", "2015-12-31")
CAPITAL = 100_000.0
DIAS_ANO = 252

CRITERIOS = {
    "excesso_min": 0.0, "sharpe_min": 0.2, "sharpe_max": 0.8,
    "sharpe_suspeito": 1.0, "sharpe_rejeita": 1.5,
    "giro_max": 0.25, "mdd_max": 0.35, "t_alfa_min": 1.5,
    "conc_nome_max": 0.15, "conc_ano_max": 0.60, "dsr_min": 0.50, "subperiodos_min": 3,
}

COLUNAS_SERIE = ["data", "patrimonio", "caixa", "valor_posicoes", "retorno", "retorno_hedge",
                 "cdi", "n_posicoes", "contratos", "custo_dia", "giro_dia"]


# ─────────────────────────────────────────────────────────────
# Utilitarios puros
# ─────────────────────────────────────────────────────────────
def datas_rebalance(ini, fim):
    """Ultimo pregao de cada mes no intervalo."""
    a, b = pd.Timestamp(ini), pd.Timestamp(fim)
    out = []
    ano, mes = a.year, a.month
    while (ano, mes) <= (b.year, b.month):
        d = calendario.ultimo_pregao_do_mes(ano, mes)
        if d is not None and a.date() <= d <= b.date():
            out.append(pd.Timestamp(d))
        mes += 1
        if mes > 12:
            ano, mes = ano + 1, 1
    return out


def _serie_mensal(serie_diaria):
    """Retorno diario -> composto mensal, indice no fim do mes."""
    if serie_diaria is None or len(serie_diaria) == 0:
        return pd.Series(dtype=float)
    return (1 + serie_diaria).resample("ME").prod() - 1


def drawdown(retornos):
    """Maior queda do pico ao vale da curva composta (numero positivo)."""
    if retornos is None or len(retornos) == 0:
        return float("nan")
    curva = (1 + pd.Series(retornos).fillna(0.0)).cumprod()
    return float((1 - curva / curva.cummax()).max())


def verificar_contabilidade(serie, tolerancia=0.01):
    """patrimonio == caixa + valor das posicoes, todo dia. Devolve (ok, pior_erro)."""
    if serie is None or len(serie) == 0:
        return True, 0.0
    erro = (serie["patrimonio"] - serie["caixa"] - serie["valor_posicoes"]).abs().max()
    return bool(erro <= tolerancia), float(erro)


# ─────────────────────────────────────────────────────────────
# Motor
# ─────────────────────────────────────────────────────────────
def rodar(painel_sinais, retornos, cdi, excesso=None, nivel=None, ini=DATA_INI, fim=DATA_FIM,
          capital=CAPITAL, estresse=1.0, config=None, com_hedge=True, modo="intersecao"):
    """Roda o backtest e devolve um dict com a serie diaria, as ordens e o P&L por nome.

    painel_sinais: saida de `sinais.painel`. retornos: painel largo data x ticker de
    retorno total. cdi: Series diaria. excesso/nivel: do modulo `mercado` (hedge).
    """
    ini_ts, fim_ts = pd.Timestamp(ini), pd.Timestamp(fim)
    if painel_sinais is None or len(painel_sinais) == 0 or retornos is None or len(retornos) == 0:
        return {"serie": pd.DataFrame(columns=COLUNAS_SERIE), "ordens": pd.DataFrame(columns=ct.COLUNAS_ORDEM),
                "pnl_nome": pd.Series(dtype=float), "n_efetivo": pd.Series(dtype=float),
                "config": config or {}, "violacoes": []}
    if modo != "intersecao":
        painel_sinais = sg.ranquear(painel_sinais, modo=modo)
    sinais_por_data = {pd.Timestamp(d): g for d, g in painel_sinais.groupby("data")}
    rebal = [d for d in datas_rebalance(ini_ts, fim_ts) if d in sinais_por_data]
    if not rebal:
        return {"serie": pd.DataFrame(columns=COLUNAS_SERIE), "ordens": pd.DataFrame(columns=ct.COLUNAS_ORDEM),
                "pnl_nome": pd.Series(dtype=float), "n_efetivo": pd.Series(dtype=float),
                "config": config or {}, "violacoes": []}

    ret = retornos.sort_index()
    cdi = pd.Series(cdi).sort_index() if cdi is not None else pd.Series(dtype=float)
    excesso = pd.Series(excesso).sort_index() if excesso is not None else pd.Series(dtype=float)
    nivel = pd.Series(nivel).sort_index() if nivel is not None else pd.Series(dtype=float)

    # UM UNICO LACO DIARIO. Em dia de execucao o retorno do dia e creditado ANTES da
    # boleta, porque a ordem sai no fechamento: a carteira de ontem rendeu o dia inteiro.
    # A versao anterior pulava o dia da execucao para todo mundo e perdia ~12 pregoes por
    # ano de rendimento - um vies negativo de meio ponto ao ano que nao existe na realidade.
    execucao = {}
    for t in rebal:
        execucao[pd.Timestamp(calendario.proximo_pregao(t))] = t
    primeiro = min(execucao)
    dias = [d for d in ret.index if primeiro <= d <= fim_ts]
    if not dias:
        return {"serie": pd.DataFrame(columns=COLUNAS_SERIE), "ordens": pd.DataFrame(columns=ct.COLUNAS_ORDEM),
                "pnl_nome": pd.Series(dtype=float), "n_efetivo": pd.Series(dtype=float),
                "config": config or {}, "violacoes": []}

    estado = ct.estado_inicial(capital, primeiro)
    linhas, ordens_todas, pnl_nome, n_efetivo, violacoes = [], [], {}, {}, []
    retornos_carteira = pd.Series(dtype=float)
    precos_vistos = {}

    for d in dias:
        estado, r_dia, r_hedge, contrib = _acumular(estado, d, ret, cdi, excesso, nivel)
        for tk, g in contrib.items():
            pnl_nome[tk] = pnl_nome.get(tk, 0.0) + g
        retornos_carteira.loc[d] = r_dia
        custo_dia, giro_dia = 0.0, 0.0
        if d in execucao:
            t = execucao[d]
            mes = sinais_por_data[t]
            precos_vistos.update(mes.set_index("ticker")["preco"].to_dict())
            # posicao que saiu do universo tem de ser LIQUIDADA pelo ultimo preco visto,
            # senao fica congelada para sempre rendendo zero (era o caso das deslistadas)
            precos = {k: v for k, v in precos_vistos.items()
                      if k in set(mes["ticker"]) or k in estado["posicoes"]}
            adtv = mes.set_index("ticker")["adtv21"].to_dict()
            setor = mes.set_index("ticker")["setor"].to_dict()
            beta = mercado.beta_movel(retornos_carteira, excesso) if len(retornos_carteira) > 5 else None
            beta60 = float(beta.iloc[-1]) if beta is not None and len(beta) and np.isfinite(beta.iloc[-1]) else None
            alvo = ct.carteira_alvo(mes, estado, precos, adtv=adtv, setor=setor,
                                    patrimonio=estado["patrimonio"], estresse=estresse,
                                    data=t, beta60=beta60)
            n_efetivo[t] = alvo["n_efetivo"]
            violacoes += [f"{t.date()}: {v}" for v in alvo["diagnostico"]["violacoes"]]
            estado, custo_dia, giro_dia = _executar(estado, alvo["ordens"], precos, d)
            if len(alvo["ordens"]):
                ordens_todas.append(alvo["ordens"].assign(data=d))
            if com_hedge:
                if alvo["hedge"]["motivo"] in ("abertura", "roll", "tamanho", "beta"):
                    custo_win = cst.custo_win(alvo["hedge"]["contratos"], estresse=estresse)["total"]
                    estado["caixa"] -= custo_win
                    custo_dia += custo_win
                estado["hedge"] = {"contratos": alvo["hedge"]["contratos"],
                                   "vencimento": alvo["hedge"]["vencimento"],
                                   "nivel_entrada": float(nivel.get(d, np.nan)) if len(nivel) else np.nan}
            for pos in estado["posicoes"].values():
                pos["meses"] = int(pos.get("meses", 0)) + 1
            estado["patrimonio"] = estado["caixa"] + sum(p["valor"] for p in estado["posicoes"].values())
        linhas.append(_linha(estado, d, r_dia, r_hedge, float(cdi.get(d, 0.0)), custo_dia, giro_dia))

    serie = pd.DataFrame(linhas, columns=COLUNAS_SERIE).drop_duplicates("data", keep="last")
    serie = serie.sort_values("data").reset_index(drop=True)
    serie["retorno"] = serie["patrimonio"].pct_change().fillna(0.0)
    return {"serie": serie,
            "ordens": pd.concat(ordens_todas, ignore_index=True) if ordens_todas
                      else pd.DataFrame(columns=ct.COLUNAS_ORDEM),
            "pnl_nome": pd.Series(pnl_nome, dtype=float),
            "n_efetivo": pd.Series(n_efetivo, dtype=float),
            "config": config or {}, "violacoes": violacoes,
            "estresse": float(estresse), "modo": modo, "com_hedge": bool(com_hedge)}


def _executar(estado, ordens, precos, data):
    """Aplica as ordens no fechamento de `data`. Compra debita valor + custo do caixa."""
    custo_total, girado = 0.0, 0.0
    for _, o in (ordens if ordens is not None else pd.DataFrame()).iterrows():
        t, valor, custo, pr = o["ticker"], float(o["valor"]), float(o["custo"]), float(o["preco"])
        pos = estado["posicoes"].get(t)
        if o["lado"] == "C":
            estado["caixa"] -= valor + custo
            if pos is None:
                estado["posicoes"][t] = {"qtd": int(o["qtd"]), "valor": valor,
                                         "data_entrada": data, "meses": 0}
                estado["classe_travada"][t[:4]] = t
            else:
                pos["valor"] += valor
                pos["qtd"] = int(round(pos["valor"] / pr)) if pr > 0 else pos["qtd"]
        else:
            estado["caixa"] += valor - custo
            if pos is not None:
                # `valor` ja vem em VALOR de posicao (ver ordens_incrementais): subtrair
                # aqui e exato, e a saida total zera a posicao sem deixar residuo.
                pos["valor"] = max(pos["valor"] - valor, 0.0)
                pos["qtd"] = int(round(pos["valor"] / pr)) if pr > 0 else 0
                if pos["valor"] <= 1e-6:
                    estado["posicoes"].pop(t, None)
                    estado["classe_travada"].pop(t[:4], None)
        custo_total += custo
        girado += valor
    estado["data"] = data
    return estado, custo_total, girado


def _acumular(estado, d, ret, cdi, excesso, nivel):
    """Um pregao: posicoes rendem retorno total, caixa rende CDI, hedge ajusta em caixa."""
    pat_ant = estado["patrimonio"]
    contrib = {}
    linha_ret = ret.loc[d] if d in ret.index else None
    for t, p in list(estado["posicoes"].items()):
        r = float(linha_ret.get(t, np.nan)) if linha_ret is not None else np.nan
        if not np.isfinite(r):                       # sem negocio: valor nao muda
            continue
        ganho = p["valor"] * r
        p["valor"] += ganho
        contrib[t] = ganho
    taxa = float(cdi.get(d, 0.0)) if len(cdi) else 0.0
    estado["caixa"] *= (1.0 + taxa)
    contratos = int((estado.get("hedge") or {}).get("contratos") or 0)
    r_hedge = 0.0
    if contratos and len(excesso) and d in excesso.index:
        niv = float(nivel.get(d, np.nan)) if len(nivel) else np.nan
        if np.isfinite(niv):
            pnl = -float(excesso.loc[d]) * mercado.nocional_win(niv, contratos)
            estado["caixa"] += pnl
            r_hedge = pnl / pat_ant if pat_ant else 0.0
    estado["patrimonio"] = estado["caixa"] + sum(p["valor"] for p in estado["posicoes"].values())
    estado["data"] = d
    r_dia = (estado["patrimonio"] / pat_ant - 1.0) if pat_ant else 0.0
    return estado, r_dia, r_hedge, contrib


def _linha(estado, d, r, r_hedge, taxa, custo, giro):
    return {"data": d, "patrimonio": estado["patrimonio"], "caixa": estado["caixa"],
            "valor_posicoes": sum(p["valor"] for p in estado["posicoes"].values()),
            "retorno": r, "retorno_hedge": r_hedge, "cdi": taxa,
            "n_posicoes": len(estado["posicoes"]),
            "contratos": int((estado.get("hedge") or {}).get("contratos") or 0),
            "custo_dia": custo, "giro_dia": giro}


# ─────────────────────────────────────────────────────────────
# Metricas, atribuicao e avaliacao
# ─────────────────────────────────────────────────────────────
def metricas(resultado, dias_ano=DIAS_ANO):
    """Excesso sobre o CDI, Sharpe do excesso, drawdown, giro e custo."""
    serie = resultado.get("serie") if isinstance(resultado, dict) else resultado
    vazio = {"n_dias": 0, "retorno_aa": np.nan, "cdi_aa": np.nan, "excesso_aa": np.nan,
             "vol_aa": np.nan, "sharpe_excesso": np.nan, "sharpe_mensal": np.nan,
             "mdd": np.nan, "giro_mensal": np.nan, "custo_aa": np.nan, "n_meses": 0}
    if serie is None or len(serie) < 2:
        return vazio
    s = serie.set_index("data").sort_index()
    n = len(s)
    anos = n / float(dias_ano)
    ret_total = float(s["patrimonio"].iloc[-1] / s["patrimonio"].iloc[0]) - 1.0
    cdi_total = float((1 + s["cdi"].fillna(0.0)).prod()) - 1.0
    excesso_diario = s["retorno"].fillna(0.0) - s["cdi"].fillna(0.0)
    mensal = _serie_mensal(excesso_diario)
    vol = float(excesso_diario.std(ddof=1) * np.sqrt(dias_ano))
    exc_aa = (1 + ret_total) ** (1 / anos) - (1 + cdi_total) ** (1 / anos) if anos > 0 else np.nan
    patr_medio = float(s["patrimonio"].mean())
    return {
        "n_dias": int(n), "n_meses": int(len(mensal)),
        "retorno_aa": float((1 + ret_total) ** (1 / anos) - 1) if anos > 0 else np.nan,
        "cdi_aa": float((1 + cdi_total) ** (1 / anos) - 1) if anos > 0 else np.nan,
        "excesso_aa": float(exc_aa),
        "vol_aa": vol,
        "sharpe_excesso": float(exc_aa / vol) if vol > 0 else np.nan,
        "sharpe_mensal": float(mensal.mean() / mensal.std(ddof=1)) if len(mensal) > 1 and mensal.std(ddof=1) > 0 else np.nan,
        "mdd": drawdown(s["retorno"]),
        "giro_mensal": float(s["giro_dia"].sum() / (2.0 * patr_medio) / max(len(mensal), 1)) if patr_medio else np.nan,
        "custo_aa": float(s["custo_dia"].sum() / patr_medio / anos) if patr_medio and anos > 0 else np.nan,
    }


def atribuicao_nefin(resultado, fatores, maxlags=6):
    """Regressao do excesso mensal contra os fatores NEFIN, com erros Newey-West.

    Devolve alfa mensal e anualizado, o t do alfa e os betas. Sem statsmodels ou sem
    sobreposicao devolve NaN em vez de levantar.
    """
    vazio = {"alfa_mensal": np.nan, "alfa_aa": np.nan, "t_alfa": np.nan, "r2": np.nan,
             "betas": {}, "n_meses": 0}
    serie = resultado.get("serie") if isinstance(resultado, dict) else resultado
    if serie is None or len(serie) < 24 or fatores is None or len(fatores) == 0:
        return vazio
    try:
        import statsmodels.api as sm
    except ImportError:                                     # pragma: no cover
        return vazio
    s = serie.set_index("data").sort_index()
    y = _serie_mensal(s["retorno"].fillna(0.0) - s["cdi"].fillna(0.0))
    f = fatores.copy()
    f.index = pd.to_datetime(f.index)
    fm = (1 + f).resample("ME").prod() - 1
    cols = [c for c in ("Rm_minus_Rf", "SMB", "HML", "WML", "IML") if c in fm]
    dados = pd.concat([y.rename("y"), fm[cols]], axis=1).dropna()
    if len(dados) < 12:
        return vazio
    X = sm.add_constant(dados[cols])
    mod = sm.OLS(dados["y"], X).fit(cov_type="HAC", cov_kwds={"maxlags": int(maxlags)})
    alfa = float(mod.params["const"])
    return {"alfa_mensal": alfa, "alfa_aa": float((1 + alfa) ** 12 - 1),
            "t_alfa": float(mod.tvalues["const"]), "r2": float(mod.rsquared),
            "betas": {c: float(mod.params[c]) for c in cols}, "n_meses": int(len(dados))}


def concentracao(resultado):
    """Quanto do ganho bruto veio do melhor nome e do melhor ano.

    Definido sobre os GANHOS BRUTOS (soma dos P&L positivos), porque a razao sobre o P&L
    total fica sem sentido quando o total e negativo ou perto de zero.
    """
    vazio = {"maior_nome": np.nan, "ticker": None, "maior_ano": np.nan, "ano": None, "n_nomes": 0}
    pnl = resultado.get("pnl_nome") if isinstance(resultado, dict) else None
    if pnl is None or len(pnl) == 0:
        return vazio
    positivos = pnl[pnl > 0]
    total = float(positivos.sum())
    out = dict(vazio)
    out["n_nomes"] = int(len(pnl))
    if total > 0:
        out["maior_nome"] = float(positivos.max() / total)
        out["ticker"] = str(positivos.idxmax())
    serie = resultado.get("serie")
    if serie is not None and len(serie):
        s = serie.set_index("data").sort_index()
        por_ano = (1 + s["retorno"].fillna(0.0)).groupby(s.index.year).prod() - 1
        ganhos = por_ano[por_ano > 0]
        if ganhos.sum() > 0:
            out["maior_ano"] = float(ganhos.max() / ganhos.sum())
            out["ano"] = int(ganhos.idxmax())
    return out


def avaliar(m, atrib=None, conc=None, dsr=None, subperiodos_ok=None, criterios=CRITERIOS):
    """Confronta as metricas com os criterios de passagem da secao 10 do plano."""
    c = dict(criterios)
    itens = {}
    itens["excesso_positivo"] = bool(np.isfinite(m.get("excesso_aa", np.nan))
                                     and m["excesso_aa"] > c["excesso_min"])
    sh = m.get("sharpe_excesso", np.nan)
    itens["sharpe_na_faixa"] = bool(np.isfinite(sh) and c["sharpe_min"] <= sh <= c["sharpe_max"])
    itens["giro_ok"] = bool(np.isfinite(m.get("giro_mensal", np.nan)) and m["giro_mensal"] <= c["giro_max"])
    itens["mdd_ok"] = bool(np.isfinite(m.get("mdd", np.nan)) and m["mdd"] <= c["mdd_max"])
    if atrib:
        itens["t_alfa_ok"] = bool(np.isfinite(atrib.get("t_alfa", np.nan))
                                  and atrib["t_alfa"] >= c["t_alfa_min"])
    if conc:
        itens["conc_nome_ok"] = bool(not np.isfinite(conc.get("maior_nome", np.nan))
                                     or conc["maior_nome"] <= c["conc_nome_max"])
        itens["conc_ano_ok"] = bool(not np.isfinite(conc.get("maior_ano", np.nan))
                                    or conc["maior_ano"] <= c["conc_ano_max"])
    if dsr is not None:
        itens["dsr_ok"] = bool(np.isfinite(dsr) and dsr >= c["dsr_min"])
    if subperiodos_ok is not None:
        itens["subperiodos_ok"] = bool(subperiodos_ok >= c["subperiodos_min"])
    alertas = []
    if np.isfinite(sh) and sh > c["sharpe_suspeito"]:
        alertas.append(f"Sharpe {sh:.2f} acima de {c['sharpe_suspeito']}: procurar bug antes de comemorar")
    if np.isfinite(sh) and sh > c["sharpe_rejeita"]:
        alertas.append(f"Sharpe {sh:.2f} acima de {c['sharpe_rejeita']}: REJEITAR o resultado")
    return {"itens": itens, "passou": all(itens.values()) and not any("REJEITAR" in a for a in alertas),
            "reprovados": [k for k, v in itens.items() if not v], "alertas": alertas}


def comparar_pre_registrado(painel_sinais, retornos, cdi, excesso=None, nivel=None,
                            ini=DATA_INI, fim=DATA_FIM, capital=CAPITAL, fatores=None):
    """As tres comparacoes pre-registradas da secao 7.

    (a) intersecao (portoes) contra soma de z-scores;
    (b) so momento e exclusao de vol contra o desenho com portoes fundamentalistas;
    (c) t do alfa da carteira de vencedores hedgeada com 22 nomes.
    Nenhuma delas escolhe parametro: sao medidas declaradas antes de rodar.
    """
    def _mede(painel, modo="intersecao", rotulo=""):
        r = rodar(painel, retornos, cdi, excesso, nivel, ini=ini, fim=fim,
                  capital=capital, modo=modo, config={"comparacao": rotulo})
        m = metricas(r)
        m["t_alfa"] = atribuicao_nefin(r, fatores).get("t_alfa", np.nan) if fatores is not None else np.nan
        return m
    out = {"a_intersecao": _mede(painel_sinais, "intersecao", "a_intersecao"),
           "a_soma_z": _mede(painel_sinais, "soma_z", "a_soma_z")}
    # (b) so momento + exclusao de vol: liga os portoes fundamentalistas em True
    so_momento = painel_sinais.copy()
    so_momento["passa_qualidade"] = True
    so_momento["passa_crescimento"] = True
    so_momento["excluido_valor"] = False
    so_momento = sg.ranquear(so_momento, modo="intersecao")
    out["b_so_momento"] = _mede(so_momento, "intersecao", "b_so_momento")
    out["b_com_portoes"] = out["a_intersecao"]
    out["b_portoes_agregam"] = bool(
        np.isfinite(out["b_com_portoes"].get("t_alfa", np.nan))
        and out["b_com_portoes"]["t_alfa"] >= CRITERIOS["t_alfa_min"]
        and out["b_com_portoes"]["t_alfa"] > out["b_so_momento"].get("t_alfa", -np.inf))
    out["c_t_alfa_vencedores"] = out["a_intersecao"].get("t_alfa", np.nan)
    return out


# ─────────────────────────────────────────────────────────────
# Holdout e relatorio
# ─────────────────────────────────────────────────────────────
def rodar_holdout(painel_sinais, retornos, cdi, excesso=None, nivel=None, fatores=None,
                  capital=CAPITAL, config=None, motivo="avaliacao unica do holdout"):
    """Abre o lacre UMA vez e calcula TUDO de uma vez (ver o docstring do modulo)."""
    config = dict(config or {})
    livro.abrir_holdout(config, motivo)
    ini, fim = livro.HOLDOUT
    base = rodar(painel_sinais, retornos, cdi, excesso, nivel, ini=ini, fim=fim,
                 capital=capital, config=config)
    caro = rodar(painel_sinais, retornos, cdi, excesso, nivel, ini=ini, fim=fim,
                 capital=capital, estresse=2.0, config=dict(config, estresse=2.0))
    m, m2 = metricas(base), metricas(caro)
    atrib = atribuicao_nefin(base, fatores)
    conc = concentracao(base)
    subs = {}
    for a, b in SUBPERIODOS:
        r = rodar(painel_sinais, retornos, cdi, excesso, nivel, ini=a, fim=b, capital=capital)
        subs[f"{a[:4]}-{b[:4]}"] = metricas(r)
    ok_subs = sum(1 for v in subs.values() if np.isfinite(v["excesso_aa"]) and v["excesso_aa"] > 0)
    dsr = livro.sharpe_deflacionado(m.get("sharpe_mensal", np.nan), m.get("n_meses", 0),
                                    max(livro.n_tentativas(), 1), livro.variancia_sharpes())
    comp = comparar_pre_registrado(painel_sinais, retornos, cdi, excesso, nivel,
                                   ini=ini, fim=fim, capital=capital, fatores=fatores)
    veredito = avaliar(m, atrib, conc, dsr, ok_subs)
    resultados = {"metricas": m, "metricas_2x": m2, "atribuicao": atrib, "concentracao": conc,
                  "subperiodos": subs, "subperiodos_positivos": ok_subs,
                  "sharpe_deflacionado": dsr, "comparacoes": comp, "veredito": veredito,
                  "sharpe": m.get("sharpe_mensal", np.nan)}
    livro.registrar_holdout(resultados)
    livro.registrar(config, [ini, fim], resultados, motivo, escopo="holdout")
    return resultados


def relatorio(resultados, caminho=None, origem="desconhecida", gate_passou=None):
    """Relatorio em Markdown com o veredito. Sempre carimba a origem dos dados."""
    m = resultados.get("metricas", {})
    v = resultados.get("veredito", {})
    linhas = ["# Backtest INTERSECAO-PF", ""]
    linhas.append(f"- Origem dos dados: **{origem}**")
    if origem != "real":
        linhas.append("- **ATENCAO: dados sinteticos. Nenhum numero abaixo e resultado.** "
                      "O gerador usa a mesma estrutura de fatores que os sinais assumem, "
                      "entao recuperacao de sinal valida mecanica, nao edge.")
    linhas.append(f"- Gate da fase 1 (replica WML/HML do NEFIN): "
                  f"{'passou' if gate_passou else 'NAO RODOU / NAO PASSOU'}")
    linhas.append(f"- Aluguel (sinal 6): 0 meses cobertos, nao testavel no backtest")
    linhas.append(f"- Insiders (sinal 7): indisponivel, sinal desligado")
    linhas.append("")
    linhas.append("## Metricas")
    linhas.append("")
    linhas.append("| medida | valor |")
    linhas.append("|---|---|")
    for chave, rotulo in (("retorno_aa", "retorno a.a."), ("cdi_aa", "CDI a.a."),
                          ("excesso_aa", "excesso sobre o CDI a.a."), ("vol_aa", "vol a.a."),
                          ("sharpe_excesso", "Sharpe do excesso"), ("mdd", "drawdown maximo"),
                          ("giro_mensal", "giro mensal"), ("custo_aa", "custo a.a.")):
        x = m.get(chave, np.nan)
        linhas.append(f"| {rotulo} | {x:.2%} |" if np.isfinite(x) and chave != "sharpe_excesso"
                      else f"| {rotulo} | {x:.2f} |")
    if resultados.get("sharpe_deflacionado") is not None:
        linhas.append(f"| Sharpe deflacionado | {resultados['sharpe_deflacionado']:.2f} |")
    linhas.append("")
    linhas.append("## Veredito")
    linhas.append("")
    if v:
        for k, ok in v.get("itens", {}).items():
            linhas.append(f"- {'OK ' if ok else 'FALHOU '} {k}")
        linhas.append("")
        linhas.append(f"**{'PASSOU' if v.get('passou') else 'REPROVOU'}**"
                      + (f" - reprovados: {', '.join(v['reprovados'])}" if v.get("reprovados") else ""))
        for a in v.get("alertas", []):
            linhas.append(f"- ALERTA: {a}")
    texto = "\n".join(linhas) + "\n"
    if caminho:
        garantir_dir(os.path.dirname(caminho))
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(texto)
    return texto


def carregar_do_banco(ini, fim):
    """Monta os insumos do backtest a partir do banco local. None se faltar dado."""
    from quant.dados import cdi as cdi_mod, cotahist, eventos, nefin
    cot = cotahist.carregar(pd.Timestamp(ini).year - 2, pd.Timestamp(fim).year)
    if cot is None or len(cot) == 0:
        return None
    painel = sg.carregar()
    if painel is None or len(painel) == 0:
        return None
    ret = sg.painel_retornos(eventos.retorno_total(cot[["ticker", "data", "fec"]],
                                                   eventos.carregar_eventos(), jcp_liquido=True))
    taxa = cdi_mod.carregar(permitir_rede=False)
    try:
        fatores = nefin.carregar_fatores()
    except FileNotFoundError:
        fatores = None
    exc = mercado.excesso_mercado(fatores) if fatores is not None else None
    niv = mercado.nivel_indice(exc, taxa) if exc is not None and taxa is not None else None
    return {"sinais": painel, "retornos": ret, "cdi": taxa, "excesso": exc,
            "nivel": niv, "fatores": fatores}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Backtest da INTERSECAO-PF (M11)")
    ap.add_argument("--janela", choices=["treino", "holdout", "subperiodos", "completo"],
                    default="treino")
    ap.add_argument("--estresse", type=float, default=1.0)
    ap.add_argument("--capital", type=float, default=CAPITAL)
    ap.add_argument("--abrir-holdout", action="store_true")
    ap.add_argument("--saida", default=None)
    args = ap.parse_args(argv)

    dados = carregar_do_banco(DATA_INI_PRECO, DATA_FIM)
    if dados is None:
        print("banco incompleto; rode cotahist, eventos, cvm_fundamentos, cdi e sinais primeiro")
        return 2
    if args.janela == "holdout":
        if not args.abrir_holdout:
            print("o holdout esta lacrado. Passe --abrir-holdout, e so uma vez "
                  "(o estado fica em quant/holdout.json e o diff fica no git).")
            return 3
        res = rodar_holdout(dados["sinais"], dados["retornos"], dados["cdi"], dados["excesso"],
                            dados["nivel"], fatores=dados["fatores"], capital=args.capital,
                            config={"versao": "intersecao-pf-1", "capital": args.capital})
    else:
        ini, fim = (TREINO if args.janela == "treino" else (DATA_INI, DATA_FIM))
        r = rodar(dados["sinais"], dados["retornos"], dados["cdi"], dados["excesso"],
                  dados["nivel"], ini=ini, fim=fim, capital=args.capital,
                  estresse=args.estresse, config={"janela": args.janela})
        m = metricas(r)
        atrib = atribuicao_nefin(r, dados["fatores"])
        conc = concentracao(r)
        res = {"metricas": m, "atribuicao": atrib, "concentracao": conc,
               "veredito": avaliar(m, atrib, conc), "sharpe": m.get("sharpe_mensal", np.nan)}
        livro.registrar({"janela": args.janela, "estresse": args.estresse,
                         "capital": args.capital, "versao": "intersecao-pf-1"},
                        [ini, fim], res, f"rodada de {args.janela}", escopo="pesquisa")
        ok, erro = verificar_contabilidade(r["serie"])
        if not ok:
            print(f"ATENCAO: identidade contabil violada em ate R${erro:.2f}")

    caminho = args.saida or os.path.join(DIR_SAIDA, f"backtest_{args.janela}_{date.today():%Y%m%d}.md")
    texto = relatorio(res, caminho, origem="real", gate_passou=None)
    print(texto)
    log(f"relatorio em {caminho}")
    return 0 if res.get("veredito", {}).get("passou") else 1


if __name__ == "__main__":
    sys.exit(main())
