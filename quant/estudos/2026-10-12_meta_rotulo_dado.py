"""
Estudo 12/10/2026 (rodada 2): meta-rotulo (Lopez de Prado, Advances in Financial ML, cap. 3) para a reversao do dado.

O modelo primario (a regra congelada) decide a direcao. Um modelo secundario aprende, SO com o que se sabe no instante do
sinal (tamanho da reacao, gap da noite, deriva pre-dado, regime macro, tipo do dado do dia, resultado de ontem...), a
probabilidade de o negocio dar lucro; essa probabilidade vira a dose (0, 1 ou 2 contratos). Walk-forward na descoberta:
treina so no passado e testa no bloco seguinte (6 blocos; o primeiro so treina). Limiares de dose fixados de antemao.
So abre 2025 (uma vez) se a dose melhorou o total E o t fora da amostra na descoberta. Cada modelo x dose e uma tentativa
registrada (familia meta_rotulo). Nada aqui muda a regra: a dose e "so medindo" ate o Douglas dizer "pode".

Saida: quant/saida/pesquisa5/montecarlo/meta_rotulo_dado.json (+ probabilidades por negocio em .csv)
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from quant.dados import calendario_eua as ce  # noqa: E402
from quant.pesquisa import lab, regimes  # noqa: E402
from quant.saida.pesquisa5.calendario import regras  # noqa: E402

PASTA = os.path.join(lab.PASTA, "montecarlo")
FAMILIA = "meta_rotulo" + (" (com surpresa)" if "--com-surpresa" in sys.argv else "")
PARAM = dict(r=2, thr=3.0)
SAIDA = dict(stop=40.0, alvo=None, tempo=120)
TIPOS = ("payroll", "cpi", "ppi", "outro_bls", "claims", "nenhum")
BLOCOS = 6
DOSES = {"tudo_ou_nada(p>=0,5)": lambda p: np.where(p >= 0.5, 2, 0),
         "escada(0,4|0,6)": lambda p: np.where(p >= 0.6, 2, np.where(p >= 0.4, 1, 0))}
COM_SURPRESA = "--com-surpresa" in sys.argv
MACRO = ("vix_nivel", "dxy_ret20", "usdbrl_ret10", "usdbrl_vol20", "risco_score", "spy_ret1", "ust10_chg10", "hyg_ret5", "brent_ret10")


def intradiarias(m, base):
    d, h, verao = lab.dia(m), lab.hm(m), regras._verao_eua(m)
    df = pd.DataFrame({"dia": pd.to_datetime(d), "h": h, "o": m["o"].to_numpy(float), "c": m["c"].to_numpy(float),
                       "hi": m["h"].to_numpy(float), "lo": m["l"].to_numpy(float), "verao": verao})
    g = df.groupby("dia")
    abre, fecha, amp = g.o.first(), g.c.last(), g.hi.max() - g.lo.min()
    df["marco"] = np.where(df.verao, "09:28", "10:28")
    pre = df[df.h == df.marco].groupby("dia").c.last()
    f = pd.DataFrame({"gap": abre - fecha.shift(1), "deriva": pre - abre, "amp20": amp.rolling(20).mean().shift(1), "verao": g.verao.first().astype(float)})
    res = base.groupby(pd.to_datetime(base.dia)).res.sum()
    f["res_ontem"] = res.reindex(f.index).ffill(limit=10).shift(1)
    return f


def montar(parte, mapa):
    """X (uma linha por negocio, so informacao disponivel no sinal), y (lucro?) e a tabela de negocios."""
    m = lab.carregar("WDO", parte)
    r = lab.avaliar(m, regras.reverte_dado_ny(m, **PARAM), nome=f"dado base (meta) [{parte}]", familia=FAMILIA, registrar=False, **SAIDA)
    t = lab.medir(r["negocios"])
    t["dia"] = pd.to_datetime(t.dia)
    h, verao = lab.hm(m), regras._verao_eua(m)
    alvo = np.where(verao, "09:31", "10:31")
    mv = regras._mov(m, 2)
    idx = np.where(h == alvo)[0]
    reac = pd.Series(mv[idx], index=pd.to_datetime(lab.dia(m)[idx]))
    f = regimes.no_dia(regimes.tabela(), sorted(set(pd.to_datetime(lab.dia(m))))).join(intradiarias(m, t))
    fx = f.reindex(t.dia)
    X = pd.DataFrame(index=range(len(t)))
    rr = reac.reindex(t.dia).to_numpy()
    X["mv_abs"] = np.abs(rr)
    X["deriva_concorda"] = (np.sign(fx.deriva.to_numpy()) == np.sign(rr)).astype(float)
    X["gap_concorda"] = (np.sign(fx.gap.to_numpy()) == np.sign(rr)).astype(float)
    X["gap_abs"] = fx.gap.abs().to_numpy()
    X["deriva_abs"] = fx.deriva.abs().to_numpy()
    X["amp20"] = fx.amp20.to_numpy()
    X["res_ontem"] = fx.res_ontem.to_numpy()
    X["verao"] = fx.verao.to_numpy()
    for c in MACRO:
        X[c] = fx[c].to_numpy()
    tipos = [ce.tipo_do_dia(d.date(), mapa) for d in t.dia]
    for tp in TIPOS:
        X[f"tipo_{tp}"] = [1.0 if x == tp else 0.0 for x in tipos]
    X["dow"] = t.dia.dt.dayofweek.to_numpy().astype(float)
    if COM_SURPRESA:                                   # surpresa real do calendario do MetaTrader (S e z do evento principal)
        St = ce.tabela_surpresa_dia().reindex(t.dia)
        X["S"] = St.S.to_numpy()
        X["S_abs"] = St.S.abs().to_numpy()
        X["concorda_S"] = np.where(St.S.notna().to_numpy(), (np.sign(St.S.to_numpy()) == np.sign(rr)).astype(float), 0.5)
        X["z_principal"] = St.z_maior.to_numpy()
    y = (t.res > 0).astype(int).to_numpy()
    return X, y, t.reset_index(drop=True)


def modelos():
    return {"logistica": lambda: make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=2000)),
            "arvores": lambda: GradientBoostingClassifier(n_estimators=150, max_depth=2, learning_rate=0.05, min_samples_leaf=20, subsample=0.8, random_state=7)}


def walk_forward(X, y, fabrica):
    n = len(X)
    p = np.full(n, np.nan)
    cortes = np.linspace(0, n, BLOCOS + 1).astype(int)
    for b in range(1, BLOCOS):
        tr, te = slice(0, cortes[b]), slice(cortes[b], cortes[b + 1])
        med = X.iloc[tr].median()
        mdl = fabrica()
        mdl.fit(X.iloc[tr].fillna(med), y[tr])
        p[te] = mdl.predict_proba(X.iloc[te].fillna(med))[:, 1]
    return p


def medir_dose(t, p, dose):
    ok = ~np.isnan(p)
    k = dose(p[ok]).astype(float)
    res2 = t.res.to_numpy()[ok]
    res_k = res2 * k / 2.0                           # custo e resultado proporcionais ao numero de contratos
    oper = k > 0
    base = {"n": int(ok.sum()), "total": round(float(res2.sum()), 0), "rs_por_negocio": round(float(res2.mean()), 1), "t": round(lab._t(pd.Series(res2)), 2)}
    dose_r = {"n_operados": int(oper.sum()), "contratos_medios": round(float(k.mean()), 2), "total": round(float(res_k.sum()), 0),
              "rs_por_operado": round(float(res_k[oper].mean()), 1) if oper.any() else None,
              "t": round(lab._t(pd.Series(res_k[oper])), 2) if oper.sum() > 3 else None,
              "acerto_operados": round(float((res_k[oper] > 0).mean() * 100), 1) if oper.any() else None}
    try:
        auc = round(float(roc_auc_score((res2 > 0).astype(int), p[ok])), 3)
    except ValueError:
        auc = None
    return base, dose_r, auc


def registrar(nome, resumo):
    linha = dict(resumo)
    linha.update(nome=nome, familia=FAMILIA, ativo="WDO", quando=time.strftime("%Y-%m-%d %H:%M:%S"), tipo="meta_rotulo")
    with open(lab.REGISTRO, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(linha, ensure_ascii=False, default=str) + "\n")


def main():
    os.makedirs(PASTA, exist_ok=True)
    mapa = ce.tipos_por_dia()
    X, y, t = montar("descoberta", mapa)
    out = {"descoberta": {"n": int(len(t)), "colunas": list(X.columns)}, "validacao": {}}
    melhor = None
    probs = pd.DataFrame({"dia": t.dia, "res": t.res})
    for nome_m, fab in modelos().items():
        p = walk_forward(X, y, fab)
        probs[f"p_{nome_m}"] = p
        for nome_d, dose in DOSES.items():
            base, dr, auc = medir_dose(t, p, dose)
            chave = f"{nome_m} | {nome_d}"
            melhora = dr["total"] > base["total"] and (dr["t"] or -9) >= base["t"]
            out["descoberta"][chave] = {"base_mesmos_negocios": base, "dose": dr, "auc_fora_da_amostra": auc, "melhora": bool(melhora)}
            registrar(f"meta-rotulo {chave} [descoberta walk-forward]", {"base": base, "dose": dr, "auc": auc, "melhora": bool(melhora)})
            print(f"descoberta {chave:40s} AUC={auc} base: total={base['total']:.0f} t={base['t']} | dose: oper={dr['n_operados']} total={dr['total']:.0f} t={dr['t']} melhora={melhora}")
            if melhora and (melhor is None or dr["total"] > melhor[2]):
                melhor = (nome_m, nome_d, dr["total"])
    # o que a logistica aprendeu (coeficientes padronizados, ajuste em toda a descoberta): para explicar, nao para operar
    med = X.median()
    lg = modelos()["logistica"]()
    lg.fit(X.fillna(med), y)
    coef = dict(zip(X.columns, np.round(lg.named_steps["logisticregression"].coef_[0], 3)))
    out["descoberta"]["coeficientes_logistica"] = dict(sorted(coef.items(), key=lambda kv: -abs(kv[1])))
    gb = modelos()["arvores"]()
    gb.fit(X.fillna(med), y)
    out["descoberta"]["importancias_arvores"] = dict(sorted(zip(X.columns, np.round(gb.feature_importances_, 3)), key=lambda kv: -kv[1]))
    probs.to_csv(os.path.join(PASTA, "meta_rotulo_dado_probs_descoberta.csv"), index=False)
    if melhor:
        nome_m, nome_d, _ = melhor
        print("abrindo 2025 uma vez para:", nome_m, nome_d)
        Xv, yv, tv = montar("validacao", mapa)
        mdl = modelos()[nome_m]()
        mdl.fit(X.fillna(med), y)
        pv = mdl.predict_proba(Xv.fillna(med))[:, 1]
        base, dr, auc = medir_dose(tv, pv, DOSES[nome_d])
        out["validacao"] = {"modelo": nome_m, "dose": nome_d, "base": base, "dose_resultado": dr, "auc": auc}
        registrar(f"meta-rotulo {nome_m} | {nome_d} [validacao 2025]", {"base": base, "dose": dr, "auc": auc})
        print(f"validacao  {nome_m} | {nome_d}: AUC={auc} base total={base['total']:.0f} t={base['t']} | dose oper={dr['n_operados']} total={dr['total']:.0f} t={dr['t']}")
        pd.DataFrame({"dia": tv.dia, "res": tv.res, "p": pv}).to_csv(os.path.join(PASTA, "meta_rotulo_dado_probs_validacao.csv"), index=False)
    else:
        print("nenhum modelo/dose melhorou fora da amostra na descoberta: 2025 nao foi aberto")
    arq = os.path.join(PASTA, "meta_rotulo_dado" + ("_com_surpresa" if COM_SURPRESA else "") + ".json")
    json.dump(out, open(arq, "w"), indent=1, default=str)
    print("gravado", arq)


if __name__ == "__main__":
    main()
