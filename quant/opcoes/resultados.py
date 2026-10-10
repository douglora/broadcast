"""
Rodada final da pesquisa de opcoes: roda TODAS as familias com os parametros fixados, grava `resultados.json` e as
linhas de `tentativas.jsonl` (regrava a ultima versao de cada configuracao). Nada aqui e digitado a mao: o RESULTADO.md
e o painel leem este arquivo.

Corredor (METODO.md): descoberta ate 2019; validacao 2020-2023 so do que passou; prova 2024-2026 so do que passou na validacao.
Nenhuma familia passou da descoberta, entao a prova 2024-2026 NAO foi aberta para nenhuma estrategia de renda. Excecoes
declaradas no RESULTADO.md: (1) o diagnostico previo da venda de put (registrado em tentativas.jsonl); (2) a protecao com
opcoes de BOVA11 e o pozinho "sem condicao" sao DESCRITIVOS (custo e distribuicao), parametros fixados a priori, sem selecao.

  PYTHONPATH=. .venv/bin/python -W ignore -m quant.opcoes.resultados
"""
import json
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from quant.opcoes import dados, metricas, motor, pozinho, protecao
from quant.opcoes import pesquisa as P
from quant.opcoes.base import DIR_DADOS, DIR_OPC

ARQ = os.path.join(DIR_OPC, "resultados.json")
P.PERIODOS["bova_desc"] = ("2020-01-01", "2022-12-31")      # BOVA11 so tem opcao liquida a partir de 2020
P.PERIODOS["bova_val"] = ("2023-01-01", "2023-12-31")


def py(x):
    if isinstance(x, dict):
        return {k: py(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [py(v) for v in x]
    if isinstance(x, (np.floating,)):
        return None if np.isnan(x) else float(x)
    if isinstance(x, float):
        return None if x != x else x
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if isinstance(x, (pd.Timestamp, datetime)):
        return x.isoformat()
    return x


def linhas(df):
    return py(df.to_dict("records"))


def put_cesta(cad, cic):
    P.N_FIXO["put"] = len(P.configs_put())
    tab = P.descoberta_put(cad, cic)
    ok = tab[tab["cfg"].str.contains("universo=cesta") & tab["cfg"].str.contains("exec=oferta") & (tab["n_ops"] >= P.OPS_MIN_FASE)]
    ok = ok[~ok["cfg"].str.contains("liq=rigorosa|vrp|tendencia")] if len(ok) > 4 else ok
    melhor_cfg = ok.sort_values("sharpe", ascending=False).iloc[0]["cfg"]
    c = next(c for c in P.configs_put() if P.nome_put(c) == melhor_cfg)
    m, t, s = P.rodar_put(cad, cic, c, "descoberta", registrar=False)
    # estresse: ciclo de marco de 2020 (vencimento 16/03/2020) -- DESCRITIVO, fora do corredor
    est = {}
    ts = t[t["T"] == pd.Timestamp("2020-03-16")]
    sc = motor.serie_por_ciclo(t, cad, cic, c["grupos"], "2020-03-01", "2020-03-31")
    est["config"] = melhor_cfg
    est["ciclo_cesta_pct"] = round(float(sc["ex"].iloc[0] + sc["cdi"].iloc[0]) * 100, 2) if len(sc) else None
    est["por_ativo"] = [{"grupo": r.grupo, "codigo": r.codigo, "exercicio": round(float(r.exercicio), 2), "S_E": round(float(r.S_E), 2),
                         "S_T": round(float(r.S_T), 2), "perda_pct_do_strike": round(float(-r.pnl_acao / r.exercicio * 100), 1)}
                        for r in ts.itertuples()]
    # pior ciclo da descoberta
    pior = s.sort_values("ex").iloc[0]
    # premio medio e pagamento medio da melhor configuracao (para mostrar a cauda com o mesmo destaque)
    tt = t[(t["T"] >= pd.Timestamp(P.PERIODOS["descoberta"][0])) & (t["T"] <= pd.Timestamp(P.PERIODOS["descoberta"][1]))]
    cauda = {"premio_medio_pct_do_strike": round(float((tt["premio_recebido"] / tt["exercicio"]).mean() * 100), 2),
             "pagamento_medio_pct_do_strike": round(float((tt["payoff_T"] / tt["exercicio"]).mean() * 100), 2),
             "pct_exercidas": round(float(tt["exercida"].mean() * 100), 1),
             "pior_operacao_pct_do_strike": round(float((tt["pnl_acao"] / tt["exercicio"]).min() * 100), 1),
             "pior_operacao": f"{tt.loc[(tt['pnl_acao'] / tt['exercicio']).idxmin(), 'grupo']} {tt.loc[(tt['pnl_acao'] / tt['exercicio']).idxmin(), 'T'].date()}",
             "pior_ciclo_da_cesta_pct": round(float(pior["ex"] + pior["cdi"]) * 100, 2), "pior_ciclo_data": str(pior["T"].date())}
    return {"tabela": linhas(tab), "melhor": {"config": melhor_cfg, **P.resumo(m)}, "estresse_mar2020": est, "cauda": cauda,
            "passou": bool(tab["passa"].any()), "n_configs": int(len(tab))}


def put_bova(cad, cic):
    P.N_FIXO["put_bova"] = 8
    G = ["BOVA11"]
    lin = []
    for d in (0.15, 0.20, 0.25, 0.30):
        for ex in ("oferta", "meio"):
            t = motor.venda_put(cad, G, d, ex)
            row = {"cfg": f"put BOVA11 delta={d:.2f} exec={ex}"}
            for per in ("bova_desc", "bova_val"):
                a, b = P.PERIODOS[per]
                s = motor.serie_por_ciclo(t, cad, cic, G, a, b)
                m = P.avaliar("put_bova", row["cfg"], per, s)
                row[per] = P.resumo(m)
            row["passa_desc"] = P.passa_fase(row["bova_desc"])
            lin.append(row)
    # ciclo de marco de 2020 para BOVA11, delta 0,20
    t = motor.venda_put(cad, G, 0.20, "oferta")
    r = t[t["T"] == pd.Timestamp("2020-03-16")]
    est = None
    if len(r):
        r = r.iloc[0]
        est = {"codigo": r["codigo"], "exercicio": round(float(r["exercicio"]), 2), "S_E": round(float(r["S_E"]), 2),
               "S_T": round(float(r["S_T"]), 2), "perda_pct_do_strike": round(float(-r["pnl_acao"] / r["exercicio"] * 100), 1)}
    return {"tabela": py(lin), "estresse_mar2020": est, "passou": any(x["passa_desc"] for x in lin)}


def call_coberta(cad, cic):
    P.N_FIXO["call"] = len(P.configs_call())
    tab = P.descoberta_call(cad, cic)
    # pior ciclo da cesta com a melhor configuracao (maior delta_sharpe entre as da cesta)
    return {"tabela": linhas(tab), "passou": bool(tab["passa"].any())}


def trava(cad, cic):
    P.N_FIXO["trava"] = len(P.configs_trava())
    tab = P.descoberta_trava(cad, cic)
    return {"tabela": linhas(tab), "passou": bool(tab["passa"].any())}


def pozinhos():
    t = pd.read_parquet(os.path.join(DIR_DADOS, "pozinhos.parquet"))
    PER = {"descoberta": P.PERIODOS["descoberta"], "validacao": P.PERIODOS["validacao"]}
    conds = {"sem condicao": lambda x: x["mult"].notna(),
             "vol. implicita menor que a realizada (vrp<0,9)": lambda x: x["vrp"] < 0.9,
             "vol. implicita maior que a realizada (vrp>=1,2)": lambda x: x["vrp"] >= 1.2,
             "depois de queda forte (10 pregoes <= -10%)": lambda x: x["ret10"] <= -0.10,
             "com resultado trimestral na janela": lambda x: x["resultado_na_janela"] == 1,
             "sem resultado trimestral na janela": lambda x: x["resultado_na_janela"] == 0}
    base, cond = [], []
    for per, (a, b) in PER.items():
        x = t[(t["T"] >= a) & (t["T"] <= b)]
        for modo in ("inicio", "curto"):
            for teto in (0.10, 0.20):
                for tipo in ("C", "P"):
                    y = x[(x["modo"] == modo) & (x["teto"] == teto) & (x["tipo"] == tipo)]
                    st = pozinho.estatisticas(y, "")
                    st.update({"periodo": per, "modo": modo, "teto": teto, "tipo": tipo})
                    base.append(st)
                    metricas.registrar("pozinho", f"pozinho {modo} teto={teto} tipo={tipo} sem condicao", per, st)
        x0 = x[(x["modo"] == "inicio") & (x["teto"] == 0.20)]
        for tipo in ("C", "P"):
            for nome, f in conds.items():
                y = x0[x0["tipo"] == tipo]
                y = y[f(y)]
                st = pozinho.estatisticas(y, "", n_boot=300)
                st.update({"periodo": per, "condicao": nome, "tipo": tipo, "modo": "inicio", "teto": 0.20})
                cond.append(st)
                if nome != "sem condicao":
                    metricas.registrar("pozinho", f"pozinho inicio teto=0.2 tipo={tipo} condicao={nome}", per, st)
    # criterio de passagem: EV positivo na descoberta E na validacao, com >= 300 bilhetes em cada
    passou = []
    cdf = pd.DataFrame(cond)
    for (tipo, nome), g in cdf.groupby(["tipo", "condicao"]):
        d, v = g[g["periodo"] == "descoberta"], g[g["periodo"] == "validacao"]
        if len(d) and len(v) and d.iloc[0].get("n", 0) >= 300 and v.iloc[0].get("n", 0) >= 300 and d.iloc[0]["ev_pct"] > 0 and v.iloc[0]["ev_pct"] > 0:
            passou.append(f"{tipo} {nome}")
    # DESCRITIVO: o bilhete sem condicao em toda a amostra, 2012-2026, por ano de vencimento
    desc = []
    for modo in ("inicio", "curto"):
        for tipo in ("C", "P"):
            y = t[(t["modo"] == modo) & (t["teto"] == 0.20) & (t["tipo"] == tipo)]
            st = pozinho.estatisticas(y, "")
            st.update({"modo": modo, "tipo": tipo, "teto": 0.20, "periodo": "2012-2026 (descritivo)"})
            desc.append(st)
    por_ano = []
    y = t[(t["modo"] == "inicio") & (t["teto"] == 0.20)]
    for ano, g in y.groupby("ano"):
        for tipo in ("C", "P"):
            gg = g[g["tipo"] == tipo]
            if len(gg):
                por_ano.append({"ano": int(ano), "tipo": tipo, "n": int(len(gg)), "ev_pct": round((gg["mult"].mean() - 1) * 100, 1),
                                "pct_ge5x": round(float((gg["mult"] >= 5).mean() * 100), 1)})
    # quanto do EV positivo de puts vem de poucos ciclos (marco de 2020)
    ycp = y[y["tipo"] == "P"]
    g = ycp.groupby("T")["mult"].agg(["sum", "count"])
    sem = g.drop(index=[i for i in g.index if str(i.date()) == "2020-03-16"], errors="ignore")
    ev_sem_mar20 = float(sem["sum"].sum() / sem["count"].sum() - 1) * 100
    return {"base": py(base), "condicoes": py(cond), "passou": passou, "descritivo": py(desc), "por_ano_inicio_teto20": py(por_ano),
            "puts_inicio_teto20_ev_sem_mar2020_pct": round(ev_sem_mar20, 1), "n_configs": 18}


def protecoes(cad, cic):
    c = protecao.simular(cad, cic)
    out = {"bova11": {}}
    for nome, (a, b) in {"2020-2023": ("2020-01-01", "2023-12-31"), "2024-2026": ("2024-01-01", "2026-12-31"),
                         "2020-2026": ("2020-01-01", "2026-12-31")}.items():
        tab = protecao.tabela(c, a, b)
        out["bova11"][nome] = py(tab.reset_index().to_dict("records"))
        for e in protecao.ESTRATEGIAS:
            metricas.registrar("protecao", f"BOVA11 {e}", nome, py(tab.loc[e].to_dict()))
    out["bova11"]["por_ano"] = {str(a): protecao.janela(c, f"{a}-01-01", f"{a}-12-31") for a in range(2020, 2027)}
    out["bova11"]["janelas"] = {"crash_2020 (ciclo que vence em 16/03/2020)": protecao.janela(c, "2020-03-16", "2020-03-16"),
                                "2020 inteiro": protecao.janela(c, "2020-01-01", "2020-12-31"),
                                "2021-2022": protecao.janela(c, "2021-01-01", "2022-12-31")}
    ano = c[c["T"].dt.year >= 2021].groupby(c["T"].dt.year)["custo_put_pct"].sum()
    out["bova11"]["custo_bruto_put_pct_por_ano"] = {str(k): round(float(v), 1) for k, v in ano.items()}
    out["bova11"]["premio_medio_pct"] = round(float(c["custo_put_pct"].mean()), 2)
    out["bova11"]["strike_medio_pct"] = round(float(c["k_put_pct"].mean()), 1)
    out["bova11"]["meses_sem_put_liquida"] = int((~c["tem_put"]).sum())
    out["bova11"]["meses_sem_colar"] = int((~c["tem_colar"]).sum())
    out["bova11"]["meses_sem_trava"] = int((~c["tem_trava"]).sum())
    # custo em anos de alta (ex-2020): quanto cada variante rendeu a menos que a carteira nua, por ano, mediana
    dif = {}
    for e in ("put", "trava", "colar", "win50", "win100"):
        v = []
        for a in range(2020, 2027):
            j = protecao.janela(c, f"{a}-01-01", f"{a}-12-31")
            v.append(j[e] - j["nu"])
        dif[e] = {"mediana_dif_ano_pp": round(float(np.median(v)), 1), "pior_ano_pp": round(float(min(v)), 1), "melhor_ano_pp": round(float(max(v)), 1)}
    out["bova11"]["diferenca_para_a_carteira_nua_por_ano"] = dif
    ci = protecao.simular_indice(2013, 2019)
    tab = protecao.tabela(ci, "2013-01-01", "2019-12-31")
    out["indice_2013_2019"] = {"tabela": py(tab.reset_index().to_dict("records")),
                               "por_ano": {str(a): protecao.janela(ci, f"{a}-01-01", f"{a}-12-31") for a in range(2013, 2020)},
                               "janela_2015": protecao.janela(ci, "2015-01-01", "2015-12-31"),
                               "ciclos": int(len(ci)), "ciclos_preco_estimado": int((ci["estimado"] == True).sum()),  # noqa: E712
                               "premio_medio_pct_do_indice_por_ciclo": round(float(ci["custo_put_pct"].mean()), 2)}
    for e in protecao.ESTRATEGIAS:
        metricas.registrar("protecao", f"IBOV opcoes de indice {e}", "2013-2019", py(tab.loc[e].to_dict()))
    return out


def main():
    metricas.FORCAR = True
    cad, cic = P.carregar()
    R = {"gerado": datetime.now(timezone(timedelta(hours=-3))).isoformat(timespec="seconds"), "periodos": P.PERIODOS}
    R["put_cesta"] = put_cesta(cad, cic)
    R["put_bova11"] = put_bova(cad, cic)
    R["call_coberta"] = call_coberta(cad, cic)
    R["trava_put"] = trava(cad, cic)
    R["pozinho"] = pozinhos()
    R["protecao"] = protecoes(cad, cic)
    por_fam = {}
    for t in metricas.ler_tentativas():
        por_fam.setdefault(t["familia"], set()).add(t["config"])
    R["tentativas"] = {"por_familia": {k: len(v) for k, v in por_fam.items()}, "total_configuracoes": int(sum(len(v) for v in por_fam.values())),
                       "linhas_no_arquivo": len(metricas.ler_tentativas())}
    with open(ARQ, "w", encoding="utf-8") as f:
        json.dump(py(R), f, ensure_ascii=False, indent=1)
    print("gravado", ARQ, R["tentativas"])
    return R


if __name__ == "__main__":
    main()
