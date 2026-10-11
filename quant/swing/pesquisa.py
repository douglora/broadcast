"""
Pesquisa dos swing trades: roda as 39 variantes pre-registradas (`quant/saida/pesquisa_swing/PRE_REGISTRO.md`) em tres etapas:

  python -m quant.swing.pesquisa dv       descoberta (2010-2017) e validacao (2018-2021) de TODAS as variantes; painel cortado em 2021-12-31
  python -m quant.swing.pesquisa prova    prova (2022-01 a 2026-09), UMA vez, so para quem passou descoberta E validacao
  python -m quant.swing.pesquisa relatorio

A prova nunca e calculada para quem nao e finalista, e o painel da etapa `dv` nem carrega 2022 em diante. Cada etapa registra suas tentativas
em `quant/livro_tentativas.jsonl` com escopo proprio ("swing"), sem mexer na contagem das outras familias.
"""
import argparse
import hashlib
import json
import os
import sys

import numpy as np
import pandas as pd

from quant import livro
from quant.comum import DIR_SAIDA, log
from quant.swing import dados, setups, simulador

PASTA = os.path.join(DIR_SAIDA, "pesquisa_swing")
ARQ_PRE = os.path.join(PASTA, "PRE_REGISTRO.md")
ARQ_DV = os.path.join(PASTA, "resultados_dv.json")
ARQ_PROVA = os.path.join(PASTA, "resultados_prova.json")
ARQ_FUNDAMENTOS = os.path.join(DIR_SAIDA, "pesquisa_carteira", "sinais_2011_2026_fundamentos.parquet")
PERIODOS_DV = {"descoberta": ("2010-01-01", "2017-12-31"), "validacao": ("2018-01-01", "2021-12-31"), "dv": ("2010-01-01", "2021-12-31")}
PERIODO_PROVA = ("2022-01-01", "2026-12-31")
N_VARIANTES = 39

# criterios do pre-registro
CRIT = {"descoberta": dict(ops=200, sharpe=0.30, anos=5), "validacao": dict(ops=80, sharpe=0.30, anos=3), "prova": dict(ops=80, sharpe=0.30, anos=0)}


def avaliar(m, etapa):
    """(passou, motivos_de_reprovacao) pelos criterios escritos antes."""
    c = CRIT[etapa]
    falhas = []
    if m.get("operacoes", 0) < c["ops"]:
        falhas.append(f"menos de {c['ops']} operações ({m.get('operacoes', 0)})")
    if not (np.isfinite(m.get("expectativa_pct", np.nan)) and m["expectativa_pct"] > 0):
        falhas.append("expectativa líquida por operação não é positiva")
    if not (np.isfinite(m.get("sharpe", np.nan)) and m["sharpe"] >= c["sharpe"]):
        falhas.append(f"Sharpe do excesso abaixo de {c['sharpe']:.2f}")
    if c["anos"] and m.get("anos_positivos", 0) < c["anos"]:
        falhas.append(f"excesso positivo em {m.get('anos_positivos', 0)} de {m.get('n_anos', 0)} anos (pede {c['anos']})")
    return (not falhas), falhas


def _series(p):
    return pd.Series(p.cdi, index=p.datas), pd.Series(p.ibov_c, index=p.datas)


def _limpo(x):
    if isinstance(x, dict):
        return {str(k): _limpo(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_limpo(v) for v in x]
    if isinstance(x, (np.floating,)):
        return None if not np.isfinite(x) else float(x)
    if isinstance(x, float):
        return None if not np.isfinite(x) else x
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


def rodar_variante(p, ind, v, eventos, periodos, faixas=None):
    sig = setups.sinais(p, ind, v, eventos)
    par = v["params"]
    ops = simulador.operacoes(p, sig, par["stop_atr"], par.get("alvo_atr"), par["prazo"], ind["atr"])
    cdi, ib = _series(p)
    out = {"sinais_total": int(sig.sum()), "operacoes_validas": int(len(ops))}
    for nome, (ini, fim) in periodos.items():
        res = simulador.livro(p, ops, ini, fim, faixas=faixas)
        out[nome] = simulador.metricas(res, cdi, ib)
    return out


def dsr_de(m_sharpe_mensal, n_meses, sharpes_todos, n=N_VARIANTES):
    v = float(np.var([x for x in sharpes_todos if np.isfinite(x)], ddof=1)) if len([x for x in sharpes_todos if np.isfinite(x)]) > 1 else float("nan")
    return livro.sharpe_deflacionado(m_sharpe_mensal, n_meses, n, v)


def etapa_dv(com_livro=True, sensibilidade=True):
    log("pesquisa swing: descoberta e validacao (painel cortado em 2021-12-31)")
    p = dados.montar(ate="2021-12-31", arq_sinais=None)
    assert p.datas[-1] <= pd.Timestamp("2021-12-31")
    ind = setups.indicadores(p)
    ev = setups.eventos_resultado(p, arq_fundamentos=ARQ_FUNDAMENTOS)
    log(f"eventos de resultado: {len(ev)}")
    res = {}
    for v in setups.variantes():
        r = rodar_variante(p, ind, v, ev, PERIODOS_DV)
        r["variante"] = {k: v[k] for k in ("id", "familia", "nucleo", "overlay", "params")}
        pd_, fd_ = avaliar(r["descoberta"], "descoberta")
        pv_, fv_ = avaliar(r["validacao"], "validacao")
        r["passa"] = {"descoberta": pd_, "validacao": pv_, "falhas_descoberta": fd_, "falhas_validacao": fv_, "finalista": bool(pd_ and pv_)}
        res[v["id"]] = r
        log(f"{v['id']:8s} D: ops {r['descoberta']['operacoes']:4d} exp {r['descoberta']['expectativa_pct']:+.4f} sharpe {r['descoberta']['sharpe']:+.2f} | "
            f"V: ops {r['validacao']['operacoes']:4d} exp {r['validacao']['expectativa_pct']:+.4f} sharpe {r['validacao']['sharpe']:+.2f} | finalista {r['passa']['finalista']}")
    sh = [r["dv"]["sharpe_mensal"] for r in res.values()]
    for r in res.values():
        r["dsr_dv"] = dsr_de(r["dv"]["sharpe_mensal"], r["dv"]["n_meses"], sh)
    if sensibilidade:
        log("sensibilidade (NAO pre-registrada): custo leve para papel de giro > R$ 100 mi")
        for v in setups.variantes():
            r = rodar_variante(p, ind, v, ev, {"descoberta": PERIODOS_DV["descoberta"], "validacao": PERIODOS_DV["validacao"]}, faixas=simulador.FAIXAS_LEVES)
            pd_, _ = avaliar(r["descoberta"], "descoberta")
            pv_, _ = avaliar(r["validacao"], "validacao")
            res[v["id"]]["sensibilidade_custo_leve"] = {"descoberta": r["descoberta"], "validacao": r["validacao"], "passaria_dv": bool(pd_ and pv_)}
    os.makedirs(PASTA, exist_ok=True)
    with open(ARQ_DV, "w", encoding="utf-8") as f:
        json.dump(_limpo(res), f, ensure_ascii=False, indent=1)
    if com_livro:
        _registrar(res, "descoberta+validacao", [PERIODOS_DV["dv"][0], PERIODOS_DV["dv"][1]])
    return res


def _registrar(res, etapa, periodo):
    sha = hashlib.sha256(open(ARQ_PRE, "rb").read()).hexdigest() if os.path.exists(ARQ_PRE) else None
    for vid, r in res.items():
        m = r["dv"] if etapa == "descoberta+validacao" else r["prova"]
        cfg = {"familia": "swing", "etapa": etapa, "variante": vid, "params": r["variante"]["params"], "overlay": r["variante"]["overlay"],
               "capital": simulador.CAPITAL, "risco": simulador.RISCO, "teto_nome": simulador.TETO_NOME, "max_pos": simulador.MAX_POSICOES}
        resumo = {"sharpe": m.get("sharpe_mensal"), "sharpe_anual": m.get("sharpe"), "expectativa_pct": m.get("expectativa_pct"), "operacoes": m.get("operacoes"),
                  "excesso_aa": m.get("excesso_aa"), "queda_maxima": m.get("queda_maxima"), "acerto": m.get("acerto"), "payoff": m.get("payoff"),
                  "finalista": r.get("passa", {}).get("finalista"), "dsr": r.get("dsr_dv")}
        livro.registrar(cfg, periodo, _limpo(resumo), f"swing {etapa}: {vid}", escopo="swing",
                        extras={"pre_registro_sha256": sha, "familia": "swing", "prova_aberta": etapa == "prova"})


def etapa_prova(com_livro=True):
    dv = json.load(open(ARQ_DV, encoding="utf-8"))
    final = [vid for vid, r in dv.items() if r["passa"]["finalista"]]
    log(f"pesquisa swing: prova para {len(final)} finalista(s): {final}")
    if os.path.exists(ARQ_PROVA):
        log("a prova JA foi aberta (resultados_prova.json existe); nao roda de novo")
        return json.load(open(ARQ_PROVA, encoding="utf-8"))
    if not final:
        res = {"finalistas": [], "motivo": "nenhuma variante passou a descoberta e a validacao: a prova continua fechada"}
        with open(ARQ_PROVA, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        return res
    p = dados.montar()
    ind = setups.indicadores(p)
    ev = setups.eventos_resultado(p, arq_fundamentos=ARQ_FUNDAMENTOS)
    res = {}
    for vid in final:
        v = next(x for x in setups.variantes() if x["id"] == vid)
        r = rodar_variante(p, ind, v, ev, {"prova": PERIODO_PROVA, "serie_inteira": ("2010-01-01", PERIODO_PROVA[1])})
        ok, falhas = avaliar(r["prova"], "prova")
        r["passa_prova"] = ok
        r["falhas_prova"] = falhas
        r["variante"] = {k: v[k] for k in ("id", "familia", "nucleo", "overlay", "params")}
        r["dsr_serie_inteira"] = dsr_de(r["serie_inteira"]["sharpe_mensal"], r["serie_inteira"]["n_meses"],
                                        [x["dv"]["sharpe_mensal"] for x in dv.values()])
        res[vid] = r
        log(f"{vid}: prova ops {r['prova']['operacoes']} exp {r['prova']['expectativa_pct']:+.4f} sharpe {r['prova']['sharpe']:+.2f} -> {'PASSOU' if ok else 'reprovou'}")
    with open(ARQ_PROVA, "w", encoding="utf-8") as f:
        json.dump(_limpo(res), f, ensure_ascii=False, indent=1)
    if com_livro:
        for vid, r in res.items():
            r["dv"] = r["prova"]
        _registrar(res, "prova", list(PERIODO_PROVA))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description="Pesquisa dos swing trades (simulacao)")
    ap.add_argument("etapa", choices=["dv", "prova"])
    ap.add_argument("--sem-livro", action="store_true")
    ap.add_argument("--sem-sensibilidade", action="store_true")
    a = ap.parse_args(argv)
    if a.etapa == "dv":
        etapa_dv(com_livro=not a.sem_livro, sensibilidade=not a.sem_sensibilidade)
    else:
        etapa_prova(com_livro=not a.sem_livro)
    return 0


if __name__ == "__main__":
    sys.exit(main())
