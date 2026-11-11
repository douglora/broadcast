#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Momento economico para o valuation: Focus (mediana e revisao em 4 semanas), Selic, juro
real, curva de NTN-B (a regua da TIR), DI longo, inflacao implicita e a leitura mecanica do
terreno para a bolsa. Tudo lido do cache do terminal (BCB, ANBIMA, B3, Tesouro), com data.

O regime nao muda o fluxo de caixa de uma empresa: muda a regua (NTN-B), a inflacao que
corrige o fluxo, o custo do capital e o premio que se exige. E e foto: expectativa muda toda
semana, por isso a REVISAO do Focus pesa tanto quanto o nivel.
"""

from __future__ import annotations

import datetime as dt
import sys

from . import base as B


def _interp(curva, x):
    pts = sorted((float(a), float(b)) for a, b in curva if a is not None and b is not None)
    if not pts:
        return None
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 > x0 else y0
    return pts[-1][1]


def carregar():
    """Foto do momento economico. Levanta SemDado se o cache do terminal nao estiver la."""
    if str(B.AQUI.parent) not in sys.path:
        sys.path.insert(0, str(B.AQUI.parent))
    try:
        from alocacao import mercado
        M = mercado.carregar()
    except Exception as e:
        raise B.SemDado(f"cache do terminal ilegível ({str(e)[:80]}): sem Focus e sem NTN-B não há valuation")
    if not M.ntnb or not M.focus:
        raise B.SemDado("cache do terminal sem curva de NTN-B ou sem Focus")
    bruto = B.ler_json(B.TERMINAL / "macro.json", {}) or {}
    hoje = dt.date.today()
    o = {"consulta": hoje.isoformat(), "veredito_dado": M.veredito, "avisos": list(M.avisos or [])[:4],
         "selic": M.selic_meta, "cdi": M.cdi, "ipca_12m": M.ipca_12m,
         "focus_data": M.focus_data, "ntnb_data": M.ntnb_data, "ntnb_curva": M.ntnb}
    # Focus com revisao
    foc = {}
    for it in ((bruto.get("focus") or {}).get("itens") or []):
        foc.setdefault(it["indicador"], {})[int(it["ano"])] = {
            "mediana": it.get("mediana"), "ha_4_sem": it.get("ha_4_sem"), "ha_1_sem": it.get("ha_1_sem")}
    if not foc:
        foc = {k: {int(a): {"mediana": v, "ha_4_sem": None} for a, v in d.items()} for k, d in M.focus.items()}
    o["focus"] = foc
    # NTN-B: 2035 (regua do Safra e do Douglas), 10 anos e a mais longa
    anos_2035 = (dt.date(2035, 5, 15) - hoje).days / 365.25
    o["ntnb_2035"] = _interp(M.ntnb, anos_2035) / 100.0
    o["ntnb_10a"] = _interp(M.ntnb, 10.0) / 100.0
    longa = max(M.ntnb, key=lambda p: p[0])
    o["ntnb_longa"], o["ntnb_longa_anos"] = longa[1] / 100.0, longa[0]
    o["di_10a"] = M.di_aa(10.0) / 100.0
    o["di_5a"] = M.di_aa(5.0) / 100.0
    o["implicita_10a"] = B.real(o["di_10a"], o["ntnb_10a"])
    o["ust10"] = (M.ust10 or 0) / 100.0 or None
    o["tir_bolsa_mediana"], o["tir_bolsa_data"] = M.tir_mediana_real, M.tir_data
    # trajetoria de inflacao para as projecoes: Focus ano a ano; depois, o ultimo ano do Focus
    ipca = {a: v["mediana"] / 100.0 for a, v in sorted((foc.get("IPCA") or {}).items()) if v.get("mediana") is not None}
    if not ipca:
        raise B.SemDado("Focus sem IPCA")
    o["ipca_focus"] = ipca
    o["ipca_longo"] = ipca[max(ipca)]
    # juro real ex-ante de 12 meses: Selic e IPCA esperados para o fim do ano seguinte
    prox = hoje.year + 1
    sel = ((foc.get("Selic") or {}).get(prox) or {}).get("mediana")
    ip = ((foc.get("IPCA") or {}).get(prox) or {}).get("mediana")
    o["juro_real_ex_ante"] = B.real((M.selic_meta + (sel or M.selic_meta)) / 200.0, (ip or M.ipca_12m) / 100.0)
    # revisoes em 4 semanas (pontos percentuais), ano seguinte
    def rev(ind, ano=prox):
        x = (foc.get(ind) or {}).get(ano) or {}
        if x.get("mediana") is None or x.get("ha_4_sem") is None:
            return None
        return x["mediana"] - x["ha_4_sem"]
    o["revisao_4s"] = {"IPCA": rev("IPCA"), "Selic": rev("Selic"), "PIB": rev("PIB Total"), "ano": prox}
    # onde a NTN-B 2035 esta na propria historia (Tesouro Direto, desde 2021). A regua e o titulo
    # COM juros semestrais (NTN-B); o Tesouro IPCA+ 2035 sem cupom (NTN-B Principal) so entra se o
    # outro faltar, e a figura diz qual serie e. A taxa do Tesouro Direto e a de resgate: fica
    # alguns centesimos acima da indicativa da ANBIMA, que e a regua da conta.
    h, serie_nome = serie_td(B.TERMINAL / "hist")
    if h.get("t") and h.get("tx"):
        serie = [(t, x) for t, x in zip(h["t"], h["tx"]) if x is not None]
        o["ntnb_2035_hist"] = serie
        o["ntnb_2035_hist_nome"] = serie_nome
        o["ntnb_2035_hist_ult"] = {"data": serie[-1][0], "taxa": serie[-1][1] / 100.0}
        txs = [x for _, x in serie]
        atual = txs[-1]
        o["ntnb_2035_percentil"] = sum(1 for x in txs if x <= atual) / len(txs)
        o["ntnb_2035_media"] = sum(txs) / len(txs) / 100.0
        o["ntnb_2035_desde"] = serie[0][0]
    o["regime"] = regime(o)
    return o


SERIES_NTNB_2035 = (("TD-IPCA-JS-2035", "Tesouro IPCA+ com Juros Semestrais 2035 (a NTN-B 2035)"),
                    ("TD-IPCA-2035", "Tesouro IPCA+ 2035 sem cupom"))


def serie_td(pasta):
    """Historia da NTN-B 2035 no cache do terminal: (json, nome). Prefere o titulo com juros semestrais."""
    for arq, nome in SERIES_NTNB_2035:
        h = B.ler_json(pasta / f"{arq}.json", {}) or {}
        if h.get("t") and h.get("tx"):
            return h, nome
    return {}, ""


def regime(o):
    """Leitura MECANICA do terreno para a bolsa. Regra escrita, para poder ser cobrada depois."""
    pontos, motivos = 0, []
    n = o["ntnb_2035"]
    if n >= 0.07:
        pontos -= 2; motivos.append(f"NTN-B 2035 paga IPCA + {B.br(n * 100, 2)}%: a renda fixa real concorre de frente com a bolsa")
    elif n >= 0.06:
        pontos -= 1; motivos.append(f"NTN-B 2035 em IPCA + {B.br(n * 100, 2)}%, acima do que a bolsa costuma aguentar sem desconto")
    elif n < 0.05:
        pontos += 1; motivos.append(f"NTN-B 2035 em IPCA + {B.br(n * 100, 2)}%: juro real baixo empurra dinheiro para a bolsa")
    r = o["revisao_4s"]
    for nome, chave, corte, ruim_se_sobe in (("inflação", "IPCA", 0.10, True), ("Selic", "Selic", 0.25, True), ("PIB", "PIB", 0.10, False)):
        v = r.get(chave)
        if v is None or abs(v) < corte:
            continue
        subiu = v > 0
        pontos += -1 if subiu == ruim_se_sobe else 1
        motivos.append(f"Focus revisou {nome} de {r['ano']} em {B.br(v, 2, True)} pp em 4 semanas")
    if o["juro_real_ex_ante"] >= 0.08:
        pontos -= 1; motivos.append(f"juro real de 12 meses em {B.pct(o['juro_real_ex_ante'])}: dívida cara e consumo fraco")
    nome = "hostil" if pontos <= -3 else "desfavoravel" if pontos <= -1 else "neutro" if pontos == 0 else "favoravel"
    # premio minimo que a mesa exige sobre a NTN-B, pelo regime (as falas do Octavio dao 4,5 a 7 pp)
    exige = {"hostil": 0.05, "desfavoravel": 0.045, "neutro": 0.04, "favoravel": 0.035}[nome]
    return {"nome": nome, "pontos": pontos, "motivos": motivos, "premio_exigido": exige}


def inflacao_ano(o, ano):
    f = o["ipca_focus"]
    return f.get(ano, o["ipca_longo"] if ano > max(f) else f[min(f)])


def texto(o):
    """Bloco curto para a conversa."""
    r, f = o["regime"], o["focus"]
    prox = o["revisao_4s"]["ano"]
    def linha(ind, rot, un="%"):
        x = (f.get(ind) or {}).get(prox) or {}
        if x.get("mediana") is None:
            return None
        rv = "" if x.get("ha_4_sem") is None else f" (há 4 semanas: {B.br(x['ha_4_sem'], 2)})"
        return f"  {rot} {prox}: {B.br(x['mediana'], 2)}{un}{rv}"
    L = [f"MOMENTO ECONÔMICO  (Focus de {B.data_br(o['focus_data'])}, NTN-B ANBIMA de {B.data_br(o['ntnb_data'])}; dado {o['veredito_dado']})",
         f"  Terreno para a bolsa: {r['nome'].upper()} ({r['pontos']:+d} pontos na regra da mesa)"]
    L += [f"   - {m}" for m in r["motivos"]]
    L += [x for x in (linha("IPCA", "IPCA"), linha("Selic", "Selic", "% a.a."), linha("PIB Total", "PIB")) if x]
    L.append(f"  Selic {B.br(o['selic'], 2)}% | IPCA 12m {B.br(o['ipca_12m'], 2)}% | juro real 12m a frente {B.pct(o['juro_real_ex_ante'])}")
    L.append(f"  NTN-B 2035: IPCA + {B.br(o['ntnb_2035'] * 100, 2)}% | longa ({B.br(o['ntnb_longa_anos'], 0)} anos): IPCA + {B.br(o['ntnb_longa'] * 100, 2)}%"
             + (f" | percentil {B.br(o['ntnb_2035_percentil'] * 100, 0)} desde {o['ntnb_2035_desde'][:4]}" if o.get("ntnb_2035_percentil") is not None else ""))
    L.append(f"  DI 10 anos {B.pct(o['di_10a'], 2)} | inflação implícita 10 anos {B.pct(o['implicita_10a'], 2)} (Focus longo: {B.pct(o['ipca_longo'], 2)})")
    if o.get("tir_bolsa_mediana"):
        L.append(f"  TIR real mediana da bolsa (método Safra, terminal, {B.data_br(o['tir_bolsa_data'])}): {B.pct(o['tir_bolsa_mediana'])} "
                 f"= prêmio de {B.pp(o['tir_bolsa_mediana'] - o['ntnb_2035'])} sobre a NTN-B 2035")
    L.append(f"  Prêmio mínimo que a mesa exige neste regime: {B.pp(r['premio_exigido'])} sobre a NTN-B 2035")
    return "\n".join(L)
