"""
Placar da camada de observacao (regras G19 e G2): cada leitura gravada e confrontada, `horizonte` pregoes depois, com o
que o mercado fez (indice e swing: hist/IBOV; dolar: hist/USDBRL). Por sinal: n leituras pontuadas, acerto (sinal da
leitura igual ao sinal do retorno), media do retorno a favor da leitura, t, e o estado:

  medindo      menos de 60 leituras pontuadas (nada a dizer ainda)
  informativo  60+ leituras, media a favor positiva e t >= 2 (tem informacao; so com o "pode" do Douglas vira dose)
  fraco        60+ leituras sem media positiva com t >= 2
  aposentado   60+ leituras, acerto <= 50% e t <= 0 (G2); volta a "medindo" se as 40 leituras seguintes tiverem media positiva

Cartao de cenario (G19): quant/saida/mesa/cartao_cenario.json, escrito pela mesa com cenarios, probabilidades (somam 1)
e gatilhos mensuraveis {serie, limiar, sentido ("acima"/"abaixo"), data_verificacao}. Passada a data, o cenario
realizado e o unico cujos gatilhos todos dispararam (ou "nenhum"); Brier = soma de (p_i - o_i)^2 (0 = perfeito,
2 = o pior). Comparado com o cartao ingenuo (probabilidades iguais).
"""
import json
import os
from datetime import date

import numpy as np
import pandas as pd

from quant.observacao import ARQ_LEITURAS, ARQ_PLACAR, DIR_OBS, fontes

MIN_LEITURAS = 60
VOLTA = 40
PROXY = {"indice": "IBOV", "swing": "IBOV", "dolar": "USDBRL"}


def registrar(dia, sinais, termometro, dose, arq=None):
    """Grava a leitura do dia (uma linha JSON por dia; repetir o dia substitui a linha)."""
    arq = arq or ARQ_LEITURAS
    os.makedirs(os.path.dirname(arq), exist_ok=True)
    linhas = [x for x in carregar(arq) if x.get("dia") != str(dia)]
    linhas.append({"dia": str(dia), "sinais": sinais, "termometro": {k: termometro.get(k) for k in ("estado", "pontos", "desconhecidas")},
                   "dose": {k: dose.get(k) for k in ("degrau", "vol_alvo_aa_pct", "mao_atual_do_livro")}})
    linhas.sort(key=lambda x: x["dia"])
    tmp = arq + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for x in linhas:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    os.replace(tmp, arq)
    return len(linhas)


def carregar(arq=None):
    try:
        with open(arq or ARQ_LEITURAS, encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]
    except (OSError, ValueError):
        return []


def retorno_a_frente(serie, dia, h):
    """Retorno (fracao) da serie do fechamento de `dia` (ou do pregao anterior) ate h pregoes depois; None se ainda nao ha."""
    if serie is None or not len(serie):
        return None
    idx = serie.index.searchsorted(pd.Timestamp(dia), side="right") - 1
    if idx < 0 or idx + h >= len(serie):
        return None
    return float(serie.iloc[idx + h] / serie.iloc[idx] - 1.0)


def _t(x):
    x = np.asarray(x, dtype=float)
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 3 and x.std(ddof=1) > 0 else float("nan")


def _estado(acertos, a_favor, anteriores=None):
    n = len(a_favor)
    if n < MIN_LEITURAS:
        return "medindo"
    media, t = float(np.mean(a_favor)), _t(a_favor)
    acerto = float(np.mean(acertos))
    if acerto <= 0.5 and t <= 0:
        ult = a_favor[-VOLTA:]
        if len(ult) >= VOLTA and float(np.mean(ult)) > 0:
            return "medindo"                                    # G2: 40 leituras de sombra positivas trazem de volta
        return "aposentado"
    if media > 0 and t >= 2.0:
        return "informativo"
    return "fraco"


def pontuar(registros, series=None):
    """Tabela por sinal. `series`: {"IBOV": Series, "USDBRL": Series} (padrao: do terminal)."""
    series = series if series is not None else {k: fontes.serie(k) for k in set(PROXY.values())}
    por_sinal = {}
    for reg in registros:
        for s in reg.get("sinais") or []:
            if not s.get("leitura"):
                continue
            r = retorno_a_frente(series.get(PROXY.get(s.get("modulo"), "IBOV")), reg["dia"], int(s.get("horizonte") or 10))
            if r is None:
                por_sinal.setdefault(s["id"], {"pendentes": 0, "acertos": [], "a_favor": [], "modulo": s.get("modulo"), "grupo": s.get("grupo")})["pendentes"] += 1
                continue
            d = por_sinal.setdefault(s["id"], {"pendentes": 0, "acertos": [], "a_favor": [], "modulo": s.get("modulo"), "grupo": s.get("grupo")})
            d["acertos"].append(int(np.sign(r) == np.sign(s["leitura"])))
            d["a_favor"].append(float(s["leitura"]) * r)
    fora = []
    for id_, d in sorted(por_sinal.items()):
        n = len(d["a_favor"])
        fora.append({"id": id_, "grupo": d["grupo"], "modulo": d["modulo"], "n": n, "pendentes": d["pendentes"],
                     "acerto_pct": round(float(np.mean(d["acertos"])) * 100, 1) if n else None,
                     "media_a_favor_pct": round(float(np.mean(d["a_favor"])) * 100, 3) if n else None,
                     "t": round(_t(d["a_favor"]), 2) if n > 3 else None,
                     "estado": _estado(d["acertos"], d["a_favor"]) if n else "medindo",
                     "falta": max(0, MIN_LEITURAS - n)})
    return fora


def brier(cartao, series=None, hoje=None):
    """Pontua o cartao (G19) se a data de verificacao ja passou. Devolve {realizado, brier, brier_ingenuo, gatilhos} ou None."""
    if not isinstance(cartao, dict) or not cartao.get("cenarios"):
        return None
    hoje = pd.Timestamp(hoje or date.today())
    series = series if series is not None else {}
    cen = cartao["cenarios"]
    probs = np.array([float(c.get("probabilidade") or 0.0) for c in cen])
    if probs.sum() <= 0:
        return None
    probs = probs / probs.sum()
    resultados, detalhe = [], []
    for c in cen:
        gat = c.get("gatilhos") or []
        ok = []
        for g in gat:
            dv = pd.Timestamp(g.get("data_verificacao") or cartao.get("data_verificacao") or hoje)
            if dv > hoje:
                return None                                        # ainda nao e hora
            s = series.get(g.get("serie"))
            if s is None:
                s = fontes.serie(str(g.get("serie")))
            if s is None or not len(s):
                ok.append(None)
                continue
            i = s.index.searchsorted(dv, side="right") - 1
            if i < 0:
                ok.append(None)
                continue
            v = float(s.iloc[i])
            lim = float(g.get("limiar"))
            disp = v >= lim if g.get("sentido", "acima") == "acima" else v <= lim
            ok.append(bool(disp))
            detalhe.append({"cenario": c.get("nome"), "serie": g.get("serie"), "valor": round(v, 4), "limiar": lim, "sentido": g.get("sentido", "acima"), "disparou": bool(disp)})
        resultados.append(bool(gat) and all(x is True for x in ok))
    realizado = [c.get("nome") for c, r in zip(cen, resultados) if r]
    o = np.array([1.0 if r else 0.0 for r in resultados])
    if o.sum() != 1:                                               # zero ou mais de um cenario "ganhou": o cartao nao discrimina
        return {"realizado": realizado or ["nenhum"], "brier": None, "brier_ingenuo": None, "gatilhos": detalhe,
                "nota": "cartao sem cenario unico realizado: gatilhos nao discriminam"}
    ing = np.full(len(cen), 1.0 / len(cen))
    return {"realizado": realizado, "brier": round(float(((probs - o) ** 2).sum()), 4), "brier_ingenuo": round(float(((ing - o) ** 2).sum()), 4),
            "gatilhos": detalhe, "melhor_que_ingenuo": bool(((probs - o) ** 2).sum() < ((ing - o) ** 2).sum())}


def montar(registros=None, series=None, cartao=None, hoje=None, gravar=True):
    registros = registros if registros is not None else carregar()
    obj = {"gerado": pd.Timestamp.now().isoformat(timespec="seconds"), "leituras": len(registros),
           "de": registros[0]["dia"] if registros else None, "ate": registros[-1]["dia"] if registros else None,
           "sinais": pontuar(registros, series), "cartao": brier(cartao, series, hoje) if cartao else None,
           "regra": (f"Sinal vira 'informativo' com {MIN_LEITURAS}+ leituras pontuadas, media a favor positiva e t >= 2; 'aposentado' (G2) com acerto <= 50% e t <= 0, "
                     f"voltando com {VOLTA} leituras positivas. Nada aqui muda capital: so com o 'pode' escrito do Douglas.")}
    if gravar:
        os.makedirs(DIR_OBS, exist_ok=True)
        tmp = ARQ_PLACAR + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        os.replace(tmp, ARQ_PLACAR)
    return obj


def texto(obj):
    linhas = [f"PLACAR DA OBSERVACAO: {obj['leituras']} dia(s) de leitura" + (f" ({obj['de']} a {obj['ate']})" if obj.get("de") else "") + "."]
    for s in obj["sinais"]:
        if s["n"]:
            linhas.append(f"- {s['id']} ({s['modulo']}): {s['n']} pontuadas, acerto {s['acerto_pct']}%, media a favor {s['media_a_favor_pct']:+.2f}%"
                          + (f" (t {s['t']:+.1f})" if s["t"] is not None else "") + f": {s['estado']}" + (f", faltam {s['falta']}" if s["falta"] else ""))
        else:
            linhas.append(f"- {s['id']} ({s['modulo']}): {s['pendentes']} leitura(s) esperando o horizonte")
    if not obj["sinais"]:
        linhas.append("- nenhum sinal pontuado ainda (o horizonte de 10 a 20 pregoes ainda nao passou)")
    c = obj.get("cartao")
    if c:
        linhas.append(f"- cartao de cenario: realizado {c['realizado']}, Brier {c.get('brier')} (ingenuo {c.get('brier_ingenuo')})")
    return "\n".join(linhas)
