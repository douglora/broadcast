"""
Estudo 14/10/2026: a REGUA da revisao do pregao. Pedido do Douglas ("todo pregao ele tem que rever a estrategia e ver onde
ele errou"): para dizer se a perda de um dia e erro ou variancia, a revisao compara o resultado de cada negocio com a
distribuicao historica da propria regra, com os parametros que estao no robo. Nada aqui escolhe parametro: e descricao.

Janela: descoberta + validacao (10/2021 a 12/2025). 2026 fica de fora (ja aberto para a regra do dado; nao abrir mais).
Grava quant/pesquisa/distribuicoes.json (versionado: a revisao de toda noite le dali e nao reabre a reserva).

Regras medidas (as que o robo roda ao vivo):
  - reversao do dado (congelada: 2 min, gatilho 3, stop 40, tempo 120, 2 contratos), com o caminho de cada negocio
    (o melhor e o pior ponto a favor) e o contexto (tamanho da reacao, tipo do dia, lado, horario, deriva antes do dado);
  - nivel e reacao (os parametros vivos de robo_fluxo.NIVEIS, janela 9h15-18h10, 2 contratos), em precos SEM ajuste;
  - climax de volume (robo_fluxo.CLIMAX, janela 9h15-18h10, 2 contratos);
  - fim do pregao no mini-indice, lado que vem dando certo (1 contrato).
Uso: python quant/estudos/2026-10-14_distribuicoes.py
"""
import importlib.util
import json
import os
import sys
import time

import numpy as np
import pandas as pd

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)
from quant.daytrade import estrategias_hist as eh  # noqa: E402
from quant.daytrade import historico as h  # noqa: E402
from quant.daytrade import robo_fluxo as rf  # noqa: E402
from quant.dados import calendario_eua as ce  # noqa: E402
from quant.pesquisa import lab  # noqa: E402
from quant.saida.pesquisa5.calendario import regras  # noqa: E402

SAIDA = os.path.join(RAIZ, "quant", "pesquisa", "distribuicoes.json")
QUANTIS = [1, 2, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 98, 99]


def _base():
    m = pd.concat([lab.carregar("WDO", "descoberta"), lab.carregar("WDO", "validacao")])
    return m[~m.index.duplicated()].sort_index()


def _sem_ajuste(m):
    """Precos de tela (o nivel antigo vem deslocado na serie ajustada; o deslocamento e constante no dia)."""
    x = m.copy()
    if "nivel" in x:
        desl = (x["nivel"] - x["c"]).to_numpy()
        for k in ("o", "h", "l", "c"):
            x[k] = x[k].to_numpy() + desl
    return x[["o", "h", "l", "c", "n", "v"]]


def _sequencias(res):
    """Sequencias de perdas: a maior, e com que frequencia aparece uma sequencia de k perdas seguidas (k = 1..10),
    contada como fracao das posicoes da serie em que termina uma sequencia de pelo menos k perdas."""
    perdeu = np.asarray(res) <= 0
    corrida, maior, conta = 0, 0, np.zeros(11)
    for p in perdeu:
        corrida = corrida + 1 if p else 0
        maior = max(maior, corrida)
        for k in range(1, 11):
            if corrida >= k:
                conta[k] += 1
    n = max(len(perdeu), 1)
    return {"maior": int(maior), "freq_k": {str(k): round(float(conta[k] / n), 4) for k in range(1, 11)}}


def _resumo(res, extra=None):
    r = np.asarray(res, dtype=float)
    if not len(r):
        return {"n": 0}
    sd = r.std(ddof=1) if len(r) > 1 else 0.0
    out = {"n": int(len(r)), "media": round(float(r.mean()), 2), "desvio": round(float(sd), 2),
           "t": round(float(r.mean() / (sd / np.sqrt(len(r)))), 2) if sd > 0 else None,
           "acerto": round(float((r > 0).mean() * 100), 1), "ganho_medio": round(float(r[r > 0].mean()), 1) if (r > 0).any() else None,
           "perda_media": round(float(r[r <= 0].mean()), 1) if (r <= 0).any() else None,
           "quantis": {str(q): round(float(np.percentile(r, q)), 1) for q in QUANTIS}, "sequencias": _sequencias(r)}
    if extra:
        out.update(extra)
    return out


def _caminho(m, t):
    """O melhor e o pior ponto a favor de cada negocio, enquanto a posicao esteve aberta (barras de 1 minuto)."""
    idx = {ts: i for i, ts in enumerate(m.index)}
    h_, l_ = m["h"].to_numpy(), m["l"].to_numpy()
    melhor, pior = [], []
    for x in t.itertuples():
        i = idx.get(pd.Timestamp(f"{x.dia} {x.hora}"))
        if i is None:
            melhor.append(np.nan), pior.append(np.nan)
            continue
        a, b = i + 1, i + 1 + int(x.minutos)
        lado = 1.0 if x.lado == "C" else -1.0
        hh, ll = h_[a:b + 1], l_[a:b + 1]
        fav = (hh - x.entrada) if lado > 0 else (x.entrada - ll)
        con = (ll - x.entrada) if lado > 0 else (x.entrada - hh)
        melhor.append(float(np.max(fav)) if len(fav) else np.nan)
        pior.append(float(np.min(con)) if len(con) else np.nan)
    return np.array(melhor), np.array(pior)


def dado(m):
    s = regras.reverte_dado_ny(m, r=2, thr=3.0)
    mv = regras._mov(m, 2)
    t = lab.medir(lab.negocios(m, s, 40.0, None, 120))
    ts = pd.to_datetime(t.dia.astype(str) + " " + t.hora)
    pos = m.index.get_indexer(ts)
    t["reacao"] = np.abs(mv[pos])
    mapa = ce.tipos_por_dia()
    t["tipo_do_dia"] = [ce.tipo_do_dia(d, mapa) for d in t.dia]
    t["ano"] = pd.to_datetime(t.dia).dt.year
    t["melhor_pts"], t["pior_pts"] = _caminho(m, t)
    c = m["c"].to_numpy()
    d = lab.dia(m)
    primeiro = pd.Series(c).groupby(d).transform("first").to_numpy()
    t["deriva_pre_dado"] = [round(float(c[p - 2] - primeiro[p - 2]), 1) if p >= 2 else np.nan for p in pos]
    desc = t[pd.to_datetime(t.dia) <= pd.Timestamp("2024-12-31")]

    def grupos(col, cortes=None, rot=None, base=desc):
        x = base.copy()
        if cortes is not None:
            x[col] = pd.cut(x[col], cortes, labels=rot)
        out = {}
        for k, g in x.groupby(col, observed=True):
            out[str(k)] = {"n": int(len(g)), "media": round(float(g.res.mean()), 1), "acerto": round(float((g.res > 0).mean() * 100), 1),
                           "t": round(float(lab._t(g.res)), 2) if len(g) > 3 else None}
        return out

    contexto = {"reacao": grupos("reacao", [3, 6, 10, 999], ["3-6", "6-10", ">10"]), "tipo_do_dia": grupos("tipo_do_dia"),
                "lado": grupos("lado"), "hora": grupos("hora"), "saida": grupos("saida"),
                "deriva_pre_dado": grupos("deriva_pre_dado", [-999, -10, -3, 3, 10, 999], ["< -10", "-10 a -3", "-3 a 3", "3 a 10", "> 10"])}
    contexto_2025 = {"reacao": grupos("reacao", [3, 6, 10, 999], ["3-6", "6-10", ">10"], base=t[t.ano == 2025]),
                     "tipo_do_dia": grupos("tipo_do_dia", base=t[t.ano == 2025])}
    perdedores = t[t.res <= 0]
    caminho = {"perdedores_que_chegaram_a_ganhar": {str(k): round(float((perdedores.melhor_pts >= k).mean() * 100), 1) for k in (3, 5, 8, 10, 15)},
               "melhor_pts_quantis": {str(q): round(float(np.nanpercentile(t.melhor_pts, q)), 1) for q in (10, 25, 50, 75, 90)},
               "pior_pts_quantis": {str(q): round(float(np.nanpercentile(t.pior_pts, q)), 1) for q in (10, 25, 50, 75, 90)}}
    por_ano = {int(a): {"n": int(len(g)), "media": round(float(g.res.mean()), 1)} for a, g in t.groupby("ano")}
    pregoes = len(set(lab.dia(m)))
    return _resumo(t.res, {"pregoes": pregoes, "por_pregao": round(len(t) / pregoes, 3), "por_ano": por_ano, "contexto_descoberta": contexto,
                           "contexto_2025": contexto_2025, "caminho": caminho, "contratos": 2,
                           "lista": [round(float(x), 1) for x in t.res]})


def niveis(m):
    p = dict(rf.NIVEIS)
    est = eh.NivelReacao(**p)
    reg = h.RegrasDoDia(inicio="09:15", ultima_entrada="18:10", zerar="18:24", contratos=2, meta_rs=None, perda_maxima_rs=None,
                        perdas_para_parar=None, max_operacoes=60, espera_min=2)
    neg = h.simular(_sem_ajuste(m), est, reg, h.Custos())
    res = [x.resultado for x in neg]
    pregoes = len(set(lab.dia(m)))
    return _resumo(res, {"pregoes": pregoes, "por_pregao": round(len(res) / pregoes, 2), "contratos": 2,
                         "por_ano": {int(a): {"n": int(len(g)), "media": round(float(np.mean(g)), 1)}
                                     for a, g in pd.Series(res, index=[pd.Timestamp(x.dia).year for x in neg]).groupby(level=0)}})


def climax(m):
    spec = importlib.util.spec_from_file_location("cal", os.path.join(RAIZ, "quant", "estudos", "2026-10-08_calibrar_climax.py"))
    cal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cal)
    cal.m1 = m
    cal.o, cal.hi, cal.lo, cal.c, cal.v = (m[k].to_numpy() for k in ("o", "h", "l", "c", "v"))
    cal.hm = np.array(m.index.strftime("%H:%M"))
    cal.dia = np.array(m.index.date)
    cal.vrel = (m.v / m.groupby(cal.dia).v.transform(lambda s: s.shift(1).rolling(30, min_periods=3).mean())).to_numpy()
    cal.dias = sorted(set(cal.dia))
    cal.fim_do_dia = np.r_[cal.dia[1:] != cal.dia[:-1], True]
    c = rf.CLIMAX
    d = cal.medir(cal.negocios(c["tranco"], c["vol"], c["alvo_devolve"], c["stop_fixo"], c["tempo_max"], ini="09:15", ult="18:10", zerar="18:24"))
    pregoes = len(cal.dias)
    return _resumo(d.res, {"pregoes": pregoes, "por_pregao": round(len(d) / pregoes, 2), "contratos": 2})


def fim_do_dia_win():
    spec = importlib.util.spec_from_file_location("wfd", os.path.join(RAIZ, "quant", "pesquisa", "regras", "win_fim_do_dia.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    w = pd.concat([lab.carregar("WIN", "descoberta"), lab.carregar("WIN", "validacao")])
    w = w[~w.index.duplicated()].sort_index()
    s = mod.regra_adaptativa(w)
    t = lab.medir(lab.negocios(w, s, 500.0, None, 25, ini="09:00", ult="18:30", zerar="18:30", tick=5.0), contratos=1, espec=lab.ESPEC["WIN"])
    pregoes = len(set(lab.dia(w)))
    return _resumo(t.res, {"pregoes": pregoes, "por_pregao": round(len(t) / pregoes, 3), "contratos": 1,
                           "aviso": "variante nascida depois de 2026 ser visto; o historico aqui e so a regua, nao prova"})


def main():
    t0 = time.time()
    m = _base()
    print(f"base WDO: {len(m)} barras, {len(set(lab.dia(m)))} pregoes ({time.time() - t0:.0f} s)", flush=True)
    out = {"gerado": time.strftime("%Y-%m-%d %H:%M"), "janela": "10/2021 a 12/2025 (descoberta + validacao; 2026 fora)",
           "como_ler": "resultado por negocio em reais, depois de custo; quantis = percentis do resultado; sequencias.freq_k = fracao das "
                       "posicoes da serie historica que terminam uma sequencia de k ou mais perdas", "regras": {}}
    for nome, f in (("reversão do dado", lambda: dado(m)), ("climax de volume", lambda: climax(m)),
                    ("fim do pregão (mini-índice, lado que vem dando certo)", fim_do_dia_win), ("nível e reação", lambda: niveis(m))):
        t1 = time.time()
        try:
            out["regras"][nome] = f()
        except Exception as e:
            out["regras"][nome] = {"n": 0, "erro": f"{type(e).__name__}: {e}"}
        r = out["regras"][nome]
        print(f"{nome}: n {r.get('n')} media {r.get('media')} acerto {r.get('acerto')} t {r.get('t')} ({time.time() - t1:.0f} s) {r.get('erro') or ''}", flush=True)
        with open(SAIDA, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1)
    print("gravado", SAIDA)


if __name__ == "__main__":
    main()
