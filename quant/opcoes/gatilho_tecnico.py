"""
ITEM 5. GATILHO TECNICO DE ALTA: papel contra call no dinheiro contra trava de alta, 21 pregoes depois do gatilho.

  T1  fechamento acima da maxima dos 55 fechamentos anteriores (rompimento)
  T2  fechamento volta acima da media de 200 pregoes (ontem abaixo) com a media de 50 acima da de 5 pregoes atras
Entrada no fechamento do gatilho (primeiro por ativo; novo so 21 pregoes depois); vencimento com 15 a 30 pregoes (o mais perto de 21), segura
ate o vencimento. Call no dinheiro (+-3%) comprada na oferta de venda; trava de alta: compra a mesma e vende a ~10% acima (+-3%) na oferta de compra.
Retorno por R$ 1 empenhado, menos o CDI do prazo: papel (sobre o preco), call e trava (sobre o premio / debito).
Pergunta: dado o gatilho, a opcao melhora o retorno AJUSTADO AO RISCO (media/desvio por operacao, pior caso)?
Criterio fixo (HIPOTESES_TESES.md): media da opcao positiva e media/desvio maior que a do papel nas duas fases.
"""
import numpy as np
import pandas as pd

from quant.opcoes import custos as C
from quant.opcoes import dados, diario, metricas
from quant.opcoes import queda_forte as Q

FEE = C.FEE_PREMIO
FAMILIA = "T5_gatilho_tecnico"


def sinais_alta():
    f = dados.fator_retorno_total()
    uni = Q.universo_acoes()
    linhas, amostra = [], []
    for a in sorted(set().union(*uni.values())):
        if a not in f.columns:
            continue
        s = f[a].dropna()
        s = s[s.index >= "2010-06-01"]
        if len(s) < 400:
            continue
        m50, m200 = s.rolling(50).mean(), s.rolling(200).mean()
        t1 = s > s.shift(1).rolling(55).max()
        t2 = (s > m200) & (s.shift(1) <= m200.shift(1)) & (m50 > m50.shift(5))
        d = pd.DataFrame({"ativo": a, "dia": s.index, "T1": t1.values, "T2": t2.values})
        d = d[(d["dia"] >= "2012-01-01") & [a in uni.get(y, set()) for y in d["dia"].dt.year]]
        linhas.append(d)
        amostra.append(d.iloc[::5][["ativo", "dia"]])
    return pd.concat(linhas, ignore_index=True), pd.concat(amostra, ignore_index=True)


def avaliar(cand, tab, aj=None):
    aj = aj or diario.Ajuste()
    cf, fech_s, tr_s = Q._fatores()
    t = tab[(tab["tipo"] == "C") & (tab["negocios"] >= 30) & tab["boa"] & tab["du"].between(15, 30)]
    m = cand[["ativo", "dia"]].merge(t, on=["ativo", "dia"])
    m["dexp"] = (m["du"] - 21).abs()
    m = m[m["dexp"] == m.groupby(["ativo", "dia"])["dexp"].transform("min")]
    m = m[m["vencimento"] == m.groupby(["ativo", "dia"])["vencimento"].transform("min")]
    m["dk"] = (m["exercicio"] / m["S"] - 1.0).abs()
    atm = m[m["dk"] <= 0.03].sort_values(["ativo", "dia", "dk", "negocios"], ascending=[True, True, True, False]).drop_duplicates(["ativo", "dia"])
    out = atm[["ativo", "dia", "vencimento", "exercicio", "ask", "S", "du"]].rename(columns={"exercicio": "K", "ask": "ask_l"}).copy()
    curta = m[["ativo", "dia", "vencimento", "exercicio", "bid", "S", "negocios"]].rename(columns={"exercicio": "Ks", "bid": "bid_s"})
    j = out[["ativo", "dia", "vencimento", "K"]].merge(curta, on=["ativo", "dia", "vencimento"])
    j = j[j["Ks"] > j["K"]]
    j["d2"] = (j["Ks"] / j["S"] - 1.10).abs()
    j = j[j["d2"] <= 0.03].sort_values(["ativo", "dia", "d2", "negocios"], ascending=[True, True, True, False]).drop_duplicates(["ativo", "dia"])
    out = out.merge(j[["ativo", "dia", "Ks", "bid_s"]], on=["ativo", "dia"], how="left")
    v, q = aj.vetor(out["ativo"], out["dia"], out["vencimento"])
    out["prov"], out["evento_qtd"] = v, q
    idx = pd.MultiIndex.from_arrays([out["vencimento"], out["ativo"]])
    idx0 = pd.MultiIndex.from_arrays([out["dia"], out["ativo"]])
    out["S_T"] = fech_s.reindex(idx).values
    out["tr0"], out["trT"] = tr_s.reindex(idx0).values, tr_s.reindex(idx).values
    out["cdi_f"] = cf.reindex(out["vencimento"]).values / cf.reindex(out["dia"]).values
    out = out[~out["evento_qtd"] & out["S_T"].notna() & out["trT"].notna()].copy()
    KT = out["K"] - out["prov"]
    pay = np.maximum(out["S_T"] - KT, 0.0)
    cost = out["ask_l"] * (1 + FEE)
    out["ret_call"] = pay * (1 - FEE) / cost - out["cdi_f"]
    KsT = out["Ks"] - out["prov"]
    pays = np.maximum(out["S_T"] - KsT, 0.0)
    deb = cost - out["bid_s"] * (1 - FEE)
    ok = out["Ks"].notna() & (deb > 0) & (deb < (out["Ks"] - out["K"]))
    out["ret_trava"] = np.where(ok, (pay - pays) * (1 - FEE) / deb - out["cdi_f"], np.nan)
    out["ret_papel"] = out["trT"] / out["tr0"] - out["cdi_f"]
    return out


def rodar(abrir_prova_se_passar=True):
    tab = diario.carregar()
    sin, amostra = sinais_alta()
    aj = diario.Ajuste()
    base = avaliar(amostra, tab, aj)
    res = {"n_configuracoes": 4}
    prova = {}
    for trg in ("T1", "T2"):
        ev = _eventos(sin, trg)
        av = avaliar(ev, tab, aj)
        blocos = {"eventos_brutos": int(len(ev)), "com_opcao_liquida": int(len(av))}
        for per in ("descoberta", "validacao"):
            s, b = Q.fase(av, per), Q.fase(base, per)
            blocos[per] = {"papel": Q.resumo_grupo(s, "ret_papel"), "call_no_dinheiro": Q.resumo_grupo(s, "ret_call"), "trava_alta": Q.resumo_grupo(s, "ret_trava"),
                           "qualquer_dia_papel": Q.resumo_grupo(b, "ret_papel"), "qualquer_dia_call": Q.resumo_grupo(b, "ret_call"), "qualquer_dia_trava": Q.resumo_grupo(b, "ret_trava")}
            metricas.registrar(FAMILIA, f"{trg} call no dinheiro", per, blocos[per]["call_no_dinheiro"])
            metricas.registrar(FAMILIA, f"{trg} trava de alta", per, blocos[per]["trava_alta"])
        def passa(op):
            ok = True
            for per in ("descoberta", "validacao"):
                o, p = blocos[per][op], blocos[per]["papel"]
                if o.get("n", 0) < 20 or p.get("n", 0) < 20 or (o["media_pct"] or -1) <= 0 or (o["media_sobre_desvio"] or -9) <= (p["media_sobre_desvio"] or 9):
                    ok = False
            return ok
        blocos["passou"] = {"call_no_dinheiro": passa("call_no_dinheiro"), "trava_alta": passa("trava_alta")}
        res[trg] = blocos
        if abrir_prova_se_passar:
            for op in ("call_no_dinheiro", "trava_alta"):
                if blocos["passou"][op]:
                    s = Q.fase(av, "prova")
                    prova[f"{trg} {op}"] = {"papel": Q.resumo_grupo(s, "ret_papel"), op: Q.resumo_grupo(s, "ret_call" if op == "call_no_dinheiro" else "ret_trava")}
                    metricas.registrar(FAMILIA, f"{trg} {op}", "prova", prova[f"{trg} {op}"], nota="PROVA aberta uma vez")
    res["prova"] = prova
    return res


def _eventos(sin, trg):
    d = sin.rename(columns={trg: "sig"})
    return Q.eventos(d.assign(**{"sig": d["sig"]}), "sig", separacao=21)[["ativo", "dia"]]


if __name__ == "__main__":
    import json
    print(json.dumps(rodar(), ensure_ascii=False, indent=1)[:5000])
