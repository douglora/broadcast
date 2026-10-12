"""
Estudo 12/10/2026 (rodada 2): a reversao do dado condicionada ao regime macro e micro e ao que se sabe antes do sinal.

Pergunta: o estado do mundo na abertura (VIX, dolar global, tendencia do dolar aqui, vol realizada, apetite a risco, gap da
noite, deriva pre-dado, resultado de ontem) separa os dias em que a reversao do dado rende dos dias em que nao rende?
Cada condicao e UMA tentativa registrada no ledger (familia dado_condicionado). Disciplina do METODO: tudo roda na
descoberta (10/2021-12/2024); so o que passa em lab.candidata e olhado na validacao (2025), uma vez; a prova (2026) nao
se abre. Tambem testa a continuacao (operar A FAVOR da reacao) nos regimes de estresse e um rompimento de abertura no
mini-indice por regime (familia win_regime).

Saida: quant/saida/pesquisa5/montecarlo/dado_condicionado.json
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from quant.pesquisa import lab, regimes  # noqa: E402
from quant.saida.pesquisa5.calendario import regras  # noqa: E402

PARAM = dict(r=2, thr=3.0)
SAIDA = dict(stop=40.0, alvo=None, tempo=120)
FAMILIA = "dado_condicionado"
PASTA = os.path.join(lab.PASTA, "montecarlo")


def intradiarias(m, base):
    """Por dia, o que se sabe antes do marco: gap da noite (abertura 9:00 contra o ultimo fechamento do dia anterior), deriva
    pre-dado (fechamento 2 barras antes do marco contra a abertura), amplitude media dos 20 dias anteriores e o resultado do
    setup no dia anterior (base = negocios do setup sem condicao)."""
    d, h, verao = lab.dia(m), lab.hm(m), regras._verao_eua(m)
    df = pd.DataFrame({"dia": pd.to_datetime(d), "h": h, "o": m["o"].to_numpy(float), "c": m["c"].to_numpy(float),
                       "hi": m["h"].to_numpy(float), "lo": m["l"].to_numpy(float), "verao": verao})
    g = df.groupby("dia")
    abre, fecha, amp = g.o.first(), g.c.last(), g.hi.max() - g.lo.min()
    df["marco"] = np.where(df.verao, "09:28", "10:28")
    pre = df[df.h == df.marco].groupby("dia").c.last()
    f = pd.DataFrame({"gap": abre - fecha.shift(1), "deriva": pre - abre, "amp20": amp.rolling(20).mean().shift(1)})
    res = base.groupby(pd.to_datetime(base.dia)).res.sum()
    f["res_ontem"] = res.reindex(f.index).ffill(limit=10).shift(1)   # resultado do ultimo setup operado antes de hoje
    return f


def por_dia(m, mascara_dia):
    """Vetor por barra (1.0 nos dias em que a mascara e True)."""
    d = pd.to_datetime(lab.dia(m))
    ok = pd.Series(mascara_dia).reindex(d).fillna(False).to_numpy(dtype=bool)
    return ok.astype(float)


def rodar(parte, condicoes_fn, registrar=True, so=None):
    m = lab.carregar("WDO", parte)
    s0 = regras.reverte_dado_ny(m, **PARAM)
    base = lab.avaliar(m, s0, nome=f"dado base (re-run) [{parte}]", familia=FAMILIA, registrar=False, **SAIDA)
    t0 = lab.medir(base["negocios"])
    pregoes = len(set(lab.dia(m)))
    f = regimes.no_dia(regimes.tabela(), sorted(set(pd.to_datetime(lab.dia(m)))))
    intra = intradiarias(m, t0)
    f = f.join(intra, how="left")
    # vol e amplitude altas contra a mediana movel de 1 ano (ponto no tempo)
    f["vol_alta"] = f.usdbrl_vol20 > f.usdbrl_vol20.rolling(252, min_periods=120).median().shift(1)
    f["amp_alta"] = f.amp20 > f.amp20.rolling(252, min_periods=120).median().shift(1)
    conds = condicoes_fn(f)
    out = {"parte": parte, "pregoes": pregoes, "base": {k: base[k] for k in ("n", "rs_por_negocio", "t", "total", "semestres_positivos", "por_ano")}, "variantes": {}}
    for nome, (mascara, lado) in conds.items():
        if so is not None and nome not in so:
            continue
        s = s0 * por_dia(m, mascara) * lado
        r = lab.avaliar(m, s, nome=f"dado | {nome} [{parte}]", familia=FAMILIA, registrar=registrar, **SAIDA)
        dias_ok = int(mascara.sum())
        out["variantes"][nome] = {k: r.get(k) for k in ("n", "rs_por_negocio", "t", "total", "acerto", "semestres_positivos", "por_ano")}
        out["variantes"][nome].update({"dias_na_condicao": dias_ok, "rs_por_pregao": round(r["total"] / max(pregoes, 1), 1) if r.get("n") else 0.0,
                                       "candidata": bool(lab.candidata(r)) if r.get("n") else False})
        print(f"{parte:10s} {nome:34s} n={r.get('n', 0):4d} R$/neg={r.get('rs_por_negocio', 0):7.1f} t={r.get('t', 0):5.2f} total={r.get('total', 0):8.0f} sem={r.get('semestres_positivos', '-')} cand={out['variantes'][nome]['candidata']}")
    return out, f


def condicoes(f):
    """Nome -> (mascara por dia, lado: +1 reversao, -1 continuacao). Limiares fixos de antemao."""
    c = {}
    for reg in ("calmo", "normal", "estresse"):
        c[f"regime_vol={reg}"] = (f.regime_vol == reg, 1)
    c["dxy_tend_alta"] = (f.dolar_tend > 0, 1)
    c["dxy_tend_baixa"] = (f.dolar_tend < 0, 1)
    c["usdbrl_10d_alta"] = (f.usdbrl_ret10 > 0, 1)
    c["usdbrl_10d_baixa"] = (f.usdbrl_ret10 <= 0, 1)
    c["usdbrl_vol_alta"] = (f.vol_alta == True, 1)       # noqa: E712
    c["usdbrl_vol_baixa"] = (f.vol_alta == False, 1)     # noqa: E712
    c["risco_on(>=3)"] = (f.risco_score >= 3, 1)
    c["risco_off(<=1)"] = (f.risco_score <= 1, 1)
    c["spy_ontem_grande(>1%)"] = (f.spy_ret1.abs() > 1.0, 1)
    c["spy_ontem_calmo(<=1%)"] = (f.spy_ret1.abs() <= 1.0, 1)
    c["vix_subindo_10d"] = (f.vix_var10 > 0, 1)
    c["vix_caindo_10d"] = (f.vix_var10 <= 0, 1)
    c["gap_grande(>10pts)"] = (f.gap.abs() > 10, 1)
    c["gap_pequeno(<=10pts)"] = (f.gap.abs() <= 10, 1)
    c["deriva_pre_dado_grande(>8pts)"] = (f.deriva.abs() > 8, 1)
    c["deriva_pre_dado_pequena(<=8pts)"] = (f.deriva.abs() <= 8, 1)
    c["amp20_alta"] = (f.amp_alta == True, 1)            # noqa: E712
    c["amp20_baixa"] = (f.amp_alta == False, 1)          # noqa: E712
    c["ontem_ganhou"] = (f.res_ontem > 0, 1)
    c["ontem_perdeu"] = (f.res_ontem <= 0, 1)
    c["continuacao_todos"] = (f.vix_nivel.notna(), -1)
    c["continuacao_estresse"] = (f.regime_vol == "estresse", -1)
    c["continuacao_vol_alta"] = (f.vol_alta == True, -1)  # noqa: E712
    return c


def orb_win(m, minutos=30, ate="11:30"):
    """Rompimento da faixa de abertura do mini-indice: faixa das barras 09:00-09:29; primeiro fechamento acima (compra) ou
    abaixo (venda) entre 09:30 e `ate`; stop = tamanho da faixa (vetor por barra). Um sinal por dia."""
    d, h = lab.dia(m), lab.hm(m)
    c = m["c"].to_numpy(float)
    df = pd.DataFrame({"d": d, "h": h, "hi": m["h"].to_numpy(float), "lo": m["l"].to_numpy(float), "c": c})
    fim_faixa = f"09:{minutos - 1:02d}"
    faixa = df[(df.h >= "09:00") & (df.h <= fim_faixa)].groupby("d").agg(hi=("hi", "max"), lo=("lo", "min"))
    hi = faixa.hi.reindex(df.d).to_numpy(); lo = faixa.lo.reindex(df.d).to_numpy()
    janela = (df.h.to_numpy() > fim_faixa) & (df.h.to_numpy() <= ate)
    bruto = np.where(janela & (c > hi), 1.0, np.where(janela & (c < lo), -1.0, 0.0))
    s = pd.Series(bruto).groupby(d).transform(lambda x: (x != 0).cumsum())
    s = np.where((s.to_numpy() == 1) & (bruto != 0), bruto, 0.0)   # so o primeiro rompimento do dia
    stop = np.nan_to_num(hi - lo, nan=300.0)
    return s, np.clip(stop, 150.0, 1500.0)


def rodar_win(parte, registrar=True):
    m = lab.carregar("WIN", parte)
    f = regimes.no_dia(regimes.tabela(), sorted(set(pd.to_datetime(lab.dia(m)))))
    s, stop = orb_win(m)
    pregoes = len(set(lab.dia(m)))
    out = {}
    conds = {"orb30_todos": f.vix_nivel.notna(), "orb30_estresse": f.regime_vol == "estresse", "orb30_calmo": f.regime_vol == "calmo",
             "orb30_spy_ontem_grande": f.spy_ret1.abs() > 1.0, "orb30_risco_off": f.risco_score <= 1}
    for nome, mascara in conds.items():
        r = lab.avaliar(m, s * por_dia(m, mascara), nome=f"WIN {nome} [{parte}]", familia="win_regime", registrar=registrar, stop=stop, alvo=None, tempo=120, ativo="WIN")
        out[nome] = {k: r.get(k) for k in ("n", "rs_por_negocio", "t", "total", "acerto", "semestres_positivos")}
        out[nome]["candidata"] = bool(lab.candidata(r)) if r.get("n") else False
        print(f"{parte:10s} WIN {nome:26s} n={r.get('n', 0):4d} R$/neg={r.get('rs_por_negocio', 0):7.1f} t={r.get('t', 0):5.2f} total={r.get('total', 0):8.0f} sem={r.get('semestres_positivos', '-')}")
    return out


def main():
    os.makedirs(PASTA, exist_ok=True)
    desc, f = rodar("descoberta", condicoes)
    cands = [k for k, v in desc["variantes"].items() if v["candidata"]]
    print("candidatas na descoberta:", cands or "nenhuma")
    val = None
    if cands:
        val, _ = rodar("validacao", condicoes, so=set(cands))
    win = {"descoberta": rodar_win("descoberta")}
    cands_win = [k for k, v in win["descoberta"].items() if v["candidata"]]
    if cands_win:
        win["validacao"] = {k: v for k, v in rodar_win("validacao").items() if k in cands_win}
    json.dump({"descoberta": desc, "validacao": val, "win": win, "candidatas": cands, "candidatas_win": cands_win},
              open(os.path.join(PASTA, "dado_condicionado.json"), "w"), indent=1, default=str)
    f.to_csv(os.path.join(PASTA, "dado_condicionado_estado_por_dia.csv"))
    print("gravado", os.path.join(PASTA, "dado_condicionado.json"))


if __name__ == "__main__":
    main()
