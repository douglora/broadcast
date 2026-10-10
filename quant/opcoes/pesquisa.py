"""
Corredor da pesquisa de opcoes (METODO.md): DESCOBERTA ate 2019, VALIDACAO 2020-2023 so do que passou na descoberta (parametros
congelados), PROVA 2024-2026 uma vez, no fim, so do que passou na validacao.

A prova so roda por `rodar_prova()`, que le `congeladas.json` (escrito por `congelar()` depois da validacao) e recusa
configuracao que nao esteja la. Toda configuracao avaliada entra em tentativas.jsonl.

Uso (da raiz do repositorio):
  PYTHONPATH=. .venv/bin/python -W ignore -m quant.opcoes.pesquisa descoberta
  PYTHONPATH=. .venv/bin/python -W ignore -m quant.opcoes.pesquisa validacao
"""
import json
import os
import sys

import numpy as np
import pandas as pd

from quant.opcoes import custos as C
from quant.opcoes import dados, metricas, motor
from quant.opcoes.base import DIR_DADOS, DIR_OPC

PERIODOS = {"descoberta": ("2012-01-01", "2019-12-31"), "validacao": ("2020-01-01", "2023-12-31"),
            "prova": ("2024-01-01", "2026-12-31")}
CESTA = ["PETR4", "VALE", "ITUB4", "BBAS3", "BBDC4"]
CESTA_COM_BOVA = CESTA + ["BOVA11"]
ARQ_CONGELADAS = os.path.join(DIR_OPC, "congeladas.json")
N_FIXO = {}        # familia -> numero de configuracoes da familia (rodada final: DSR com o N total, nao o acumulado ate ali)

# criterio de passagem de fase (fixado antes de olhar a validacao): excesso sobre o CDI positivo, Sharpe > 0,3, >= 30 operacoes
SHARPE_MIN_FASE = 0.3
OPS_MIN_FASE = 30
# aprovacao final (METODO.md, item 7): Sharpe > 1, Sharpe deflacionado > 0,95, >= 100 operacoes fora da amostra
SHARPE_MIN_FINAL = 1.0
DSR_MIN_FINAL = 0.95
OPS_MIN_FINAL = 100


def carregar():
    cad = pd.read_parquet(os.path.join(DIR_DADOS, "cadeia_preparada.parquet"))
    cic = pd.read_parquet(os.path.join(DIR_DADOS, "ciclos.parquet"))
    return cad, cic


def passa_fase(m):
    return (m.get("n_ops", 0) >= OPS_MIN_FASE and m.get("excesso_anual_pct", -1) > 0 and m.get("sharpe", -9) > SHARPE_MIN_FASE)


def avaliar(familia, config, periodo, serie, coluna="ex", registrar=True, nota=None):
    """serie: DataFrame por ciclo (T, E, cdi, n_ops e a coluna de excesso). Devolve dicionario de metricas."""
    a, b = PERIODOS[periodo]
    if len(serie) == 0:
        return {"n_ciclos": 0, "n_ops": 0}
    ntent = N_FIXO.get(familia) or (metricas.n_tentativas(familia) + (0 if (familia, config) in {(t["familia"], t["config"]) for t in metricas.ler_tentativas()} else 1))
    com_op = (serie["n_ops"] > 0).values if "n_ops" in serie else None
    anos = serie["du"].sum() / 252.0 if "du" in serie else None
    m = metricas.calcular(serie[coluna].values, serie["cdi"].values, com_op, serie["E"].iloc[0], serie["T"].iloc[-1], n_tentativas=ntent, anos=anos)
    if registrar:
        metricas.registrar(familia, config, periodo, m, nota)
    return m


def resumo(m):
    return {k: m.get(k) for k in ("n_ciclos", "n_ops", "retorno_anual_pct", "excesso_anual_pct", "sharpe",
                                   "queda_maxima_pct", "pior_mes_pct", "meses_positivos_pct", "sharpe_deflacionado")}


# ----------------------------------------------------------------------------------------------- venda de put (a)
def configs_put():
    cfg = []
    for d in (0.15, 0.20, 0.25, 0.30):
        for nome, grupos in [("cesta", CESTA)] + [(g, [g]) for g in CESTA]:
            cfg.append({"delta": d, "universo": nome, "grupos": grupos, "exec": "oferta", "liq": "padrao", "vrp": None, "tend": False})
        cfg.append({"delta": d, "universo": "cesta", "grupos": CESTA, "exec": "meio", "liq": "padrao", "vrp": None, "tend": False})
        cfg.append({"delta": d, "universo": "cesta", "grupos": CESTA, "exec": "oferta", "liq": "rigorosa", "vrp": None, "tend": False})
        cfg.append({"delta": d, "universo": "cesta", "grupos": CESTA, "exec": "oferta", "liq": "padrao", "vrp": 1.1, "tend": False})
        cfg.append({"delta": d, "universo": "cesta", "grupos": CESTA, "exec": "oferta", "liq": "padrao", "vrp": None, "tend": True})
    return cfg


def nome_put(c):
    return (f"put delta={c['delta']:.2f} universo={c['universo']} exec={c['exec']} liq={c['liq']}"
            + (f" vrp>={c['vrp']}" if c["vrp"] else "") + (" tendencia=acima_mm200" if c.get("tend") else ""))


def rodar_put(cad, cic, c, periodo, registrar=True, nota=None):
    neg, spr = (100, 0.15) if c["liq"] == "rigorosa" else (C.NEG_MIN, C.SPREAD_MAX)
    base = cad
    if c["vrp"]:
        base = cad[(cad["vrp"] >= c["vrp"])]            # filtro por serie de ativo-ciclo: iv_atm/rv20 na entrada
    if c.get("tend"):
        base = base[base["acima_mm200"] == 1.0]         # so vende put com o indice de retorno total acima da media de 200 pregoes
    t = motor.venda_put(base, c["grupos"], c["delta"], c["exec"], neg, spr)
    a, b = PERIODOS[periodo]
    s = motor.serie_por_ciclo(t, cad, cic, c["grupos"], a, b)
    m = avaliar("put", nome_put(c), periodo, s, registrar=registrar, nota=nota)
    return m, t, s


def descoberta_put(cad, cic):
    res = []
    for c in configs_put():
        m, _, _ = rodar_put(cad, cic, c, "descoberta")
        res.append({"cfg": nome_put(c), **resumo(m), "passa": passa_fase(m)})
    return pd.DataFrame(res)


# ----------------------------------------------------------------------------------------------- call coberta (b)
def configs_call():
    cfg = []
    for d in (0.20, 0.30, 0.40):
        for ex in ("oferta", "meio"):
            cfg.append({"delta": d, "universo": "cesta", "grupos": CESTA, "exec": ex})
    for g in CESTA:
        cfg.append({"delta": 0.30, "universo": g, "grupos": [g], "exec": "oferta"})
    return cfg


def nome_call(c):
    return f"call coberta delta={c['delta']:.2f} universo={c['universo']} exec={c['exec']}"


def serie_coberta(base, cic, periodo):
    a, b = PERIODOS[periodo]
    base = base[(base["T"] >= pd.Timestamp(a)) & (base["T"] <= pd.Timestamp(b))]
    g = base.groupby("T").agg(ex_cob=("ex_coberta", "mean"), ex_acao=("ex_acao", "mean"), n_ops=("com_call", "sum"),
                              n_grupos=("grupo", "nunique"), E=("E", "first"), cdi=("cdi_ciclo", "first")).reset_index()
    g = g.merge(cic[["T", "du"]], on="T", how="left")
    return g.sort_values("T").reset_index(drop=True)


def rodar_call(cad, cic, c, periodo, registrar=True, nota=None):
    base = motor.call_coberta(cad, c["grupos"], c["delta"], c["exec"])
    s = serie_coberta(base, cic, periodo)
    if len(s) < 3:
        return {"n_ciclos": len(s)}, base, s
    ntent = N_FIXO.get("call") or (metricas.n_tentativas("call") + (0 if (("call", nome_call(c)) in {(t["familia"], t["config"]) for t in metricas.ler_tentativas()}) else 1))
    com_op = (s["n_ops"] > 0).values
    anos = s["du"].sum() / 252.0
    mc = metricas.calcular(s["ex_cob"].values, s["cdi"].values, com_op, s["E"].iloc[0], s["T"].iloc[-1], n_tentativas=ntent, anos=anos)
    ma = metricas.calcular(s["ex_acao"].values, s["cdi"].values, None, s["E"].iloc[0], s["T"].iloc[-1], anos=anos)
    m = {**mc, "acao_sharpe": ma["sharpe"], "acao_excesso_anual_pct": ma["excesso_anual_pct"], "acao_retorno_anual_pct": ma["retorno_anual_pct"],
         "acao_queda_maxima_pct": ma["queda_maxima_pct"], "acao_pior_mes_pct": ma["pior_mes_pct"],
         "delta_sharpe": round(mc["sharpe"] - ma["sharpe"], 3), "delta_excesso_aa": round(mc["excesso_anual_pct"] - ma["excesso_anual_pct"], 2),
         "delta_queda_max": round(mc["queda_maxima_pct"] - ma["queda_maxima_pct"], 2),
         "pct_ciclos_exercida": round(float(base[(base["T"] >= pd.Timestamp(PERIODOS[periodo][0])) & (base["T"] <= pd.Timestamp(PERIODOS[periodo][1]))]["exercida"].fillna(False).astype(bool).mean() * 100), 1)}
    if registrar:
        metricas.registrar("call", nome_call(c), periodo, m, nota)
    return m, base, s


def passa_fase_call(m):
    return m.get("n_ops", 0) >= OPS_MIN_FASE and m.get("delta_sharpe", -9) >= 0.10 and m.get("delta_queda_max", -9) >= 0


def descoberta_call(cad, cic):
    res = []
    for c in configs_call():
        m, _, _ = rodar_call(cad, cic, c, "descoberta")
        res.append({"cfg": nome_call(c), **{k: m.get(k) for k in ("n_ciclos", "n_ops", "retorno_anual_pct", "sharpe", "acao_retorno_anual_pct",
                    "acao_sharpe", "delta_sharpe", "delta_excesso_aa", "queda_maxima_pct", "acao_queda_maxima_pct", "delta_queda_max", "pct_ciclos_exercida")},
                    "passa": passa_fase_call(m)})
    return pd.DataFrame(res)


# ----------------------------------------------------------------------------------------------- trava de alta de credito com puts (e)
def configs_trava():
    cfg = []
    for d in (0.20, 0.30):
        for w in (0.05, 0.10):
            for ex in ("oferta", "meio"):
                cfg.append({"delta": d, "largura": w, "universo": "cesta", "grupos": CESTA, "exec": ex})
    return cfg


def nome_trava(c):
    return f"trava put delta={c['delta']:.2f} largura={c['largura']:.2f} universo={c['universo']} exec={c['exec']}"


def rodar_trava(cad, cic, c, periodo, registrar=True, nota=None):
    t = motor.trava_put(cad, c["grupos"], c["delta"], c["largura"], c["exec"])
    a, b = PERIODOS[periodo]
    s = motor.serie_por_ciclo(t, cad, cic, c["grupos"], a, b)
    m = avaliar("trava", nome_trava(c), periodo, s, registrar=registrar, nota=nota)
    if len(t):
        tt = t[(t["T"] >= pd.Timestamp(a)) & (t["T"] <= pd.Timestamp(b))]
        m["perda_total_pct"] = round(float(tt["perda_total"].mean() * 100), 1) if len(tt) else None
    return m, t, s


def descoberta_trava(cad, cic):
    res = []
    for c in configs_trava():
        m, _, _ = rodar_trava(cad, cic, c, "descoberta")
        res.append({"cfg": nome_trava(c), **resumo(m), "perda_total_pct": m.get("perda_total_pct"), "passa": passa_fase(m)})
    return pd.DataFrame(res)


# ----------------------------------------------------------------------------------------------- congelar e prova
def congelar(configs, motivo=""):
    """Grava as configuracoes que PASSARAM da validacao (parametros congelados). So estas podem ir para a prova."""
    with open(ARQ_CONGELADAS, "w", encoding="utf-8") as f:
        json.dump({"congeladas": list(configs), "motivo": motivo}, f, ensure_ascii=False, indent=1)


def rodar_prova(familia, cfg_nome, serie_prova):
    """Avalia UMA configuracao congelada em 2024-2026. Recusa configuracao que nao esteja em congeladas.json."""
    try:
        lista = json.load(open(ARQ_CONGELADAS, encoding="utf-8")).get("congeladas", [])
    except FileNotFoundError:
        lista = []
    if cfg_nome not in lista:
        raise PermissionError(f"prova recusada: '{cfg_nome}' nao passou da validacao (congeladas: {len(lista)})")
    return avaliar(familia, cfg_nome, "prova", serie_prova)


if __name__ == "__main__":
    fase = sys.argv[1] if len(sys.argv) > 1 else "descoberta"
    cad, cic = carregar()
    if fase == "descoberta":
        r = descoberta_put(cad, cic)
        pd.set_option("display.width", 250)
        print(r.to_string())
        print(descoberta_call(cad, cic).to_string())
        print(descoberta_trava(cad, cic).to_string())
