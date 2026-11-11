#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Graficos em SVG puro para o relatorio do analista, no padrao visual aprovado pelo Douglas em
11/11/2026 (o mesmo do agente de FIIs: azul-marinho, Montserrat, fundo branco, grade discreta,
numero escrito em cima do dado). Sem biblioteca de grafico: o SVG vai embutido no HTML e sai
igual no celular, no PDF e no Artifact.

Quatro formas, escolhidas pelo que o dado pede:
  barras_h   comparar lentes contra uma referencia (retorno x NTN-B, preco justo x preco de tela)
  cascata    de onde sai e para onde vai o caixa (do EBITDA ao caixa do dono)
  colunas    historia e projecao ano a ano
  pontos     uma serie com poucas datas e o numero em cada ponto (TIR do Safra no tempo)
"""

from __future__ import annotations

import html
import math

COR = {"acc": "#101a5c", "azul": "#0070c0", "ink": "#12183f", "mut": "#5d6577", "line": "#dfe4ec", "grade": "#e9edf3",
       "pos": "#0a7d4f", "neg": "#b3372f", "claro": "#9db7d5", "cinza": "#aab3c2", "fundo": "#ffffff"}
W = 760
FAM = "Montserrat,'Helvetica Neue',Arial,sans-serif"
FS, FS_ROT, FS_VAL = 14, 14.5, 15


def _esc(s):
    return html.escape(str(s), quote=True)


def _n(v):
    return f"{v:.1f}".rstrip("0").rstrip(".")


def _t(x, y, txt, fs=FS, cor="mut", ancora="start", peso=400, italico=False, halo=False):
    st = ' font-style="italic"' if italico else ""
    if halo:                                                   # contorno branco: a linha do grafico nao corta o numero
        st += f' stroke="{COR["fundo"]}" stroke-width="4" stroke-linejoin="round" paint-order="stroke"'
    return (f'<text x="{_n(x)}" y="{_n(y)}" font-size="{_n(fs)}" font-weight="{peso}" fill="{COR.get(cor, cor)}" '
            f'text-anchor="{ancora}"{st}>{_esc(txt)}</text>')


def largura(txt, fs, negrito=False):
    return len(str(txt)) * fs * (0.60 if negrito else 0.56)


def quebrar(txt, max_car):
    out, atual = [], ""
    for p in str(txt).split():
        if atual and len(atual) + 1 + len(p) > max_car:
            out.append(atual)
            atual = p
        else:
            atual = (atual + " " + p).strip()
    return out + ([atual] if atual else [])


def passo_bonito(amplitude, alvo=5):
    if amplitude <= 0:
        return 1.0
    bruto = amplitude / alvo
    mag = 10 ** math.floor(math.log10(bruto))
    for m in (1, 2, 2.5, 5, 10):
        if bruto <= m * mag:
            return m * mag
    return 10 * mag


def faixa(vmin, vmax, alvo=5):
    """(inferior, superior, passo) com folga, sempre incluindo o zero."""
    vmin, vmax = min(0.0, vmin), max(0.0, vmax)
    if vmax == vmin:
        vmax = vmin + 1.0
    p = passo_bonito(vmax - vmin, alvo)
    return math.floor(vmin / p) * p, math.ceil(vmax / p) * p, p


def _svg(altura, corpo, descricao):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {_n(altura)}" role="img" aria-label="{_esc(descricao)}" '
            f'font-family="{FAM}"><rect width="{W}" height="{_n(altura)}" fill="{COR["fundo"]}"/>' + "".join(corpo) + "</svg>")


def barras_h(itens, fmt, ref=None, ref_rotulo="", descricao=""):
    """itens: [{'rotulo', 'valor' (None = nao fecha), 'cor', 'nota'}]. ref: linha vertical de referencia."""
    xl, x0, x1, alt_l = 8, 300, W - 110, 46
    vals = [i["valor"] for i in itens if i.get("valor") is not None] + ([ref] if ref is not None else [])
    lo, hi, _ = faixa(min(vals), max(vals) * 1.02)
    ex = lambda v: x0 + (v - lo) / (hi - lo) * (x1 - x0)
    topo = 34 if ref is not None else 12
    xr = ex(ref) if ref is not None else None
    corpo, valores, y = [], [], topo          # valores: escritos por ultimo, por cima da linha de referencia
    for i in itens:
        linhas = quebrar(i["rotulo"], 36)[:2]
        yc = y + alt_l / 2.0
        for k, ln in enumerate(linhas):
            corpo.append(_t(xl, yc + 5 + (k - (len(linhas) - 1) / 2.0) * 17, ln, FS_ROT, "ink", peso=600 if i.get("forte") else 500))
        v = i.get("valor")
        if v is None:
            corpo.append(_t(x0 + 6, yc + 5, i.get("nota") or "não fecha", FS, "mut", italico=True))
        else:
            xa, xb = sorted((ex(0.0), ex(v)))
            corpo.append(f'<rect x="{_n(xa)}" y="{_n(y + 9)}" width="{_n(max(2.0, xb - xa))}" height="{alt_l - 18}" fill="{COR.get(i.get("cor", "acc"))}"/>')
            fora = xb + 7 if v >= 0 else xa - 7
            lw = largura(fmt(v), FS_VAL, True)
            ea, eb = (fora, fora + lw) if v >= 0 else (fora - lw, fora)
            if xr is not None and ea - 4 <= xr <= eb + 4:
                # a linha de referencia passaria por cima do numero: fundo branco atras dele
                valores.append(f'<rect x="{_n(ea - 3)}" y="{_n(yc - 9)}" width="{_n(lw + 6)}" height="20" fill="{COR["fundo"]}"/>')
            valores.append(_t(fora, yc + 5.5, fmt(v), FS_VAL, "ink", "start" if v >= 0 else "end", 700))
        y += alt_l
    base = y + 4
    corpo.insert(0, f'<line x1="{_n(ex(0.0))}" y1="{topo - 4}" x2="{_n(ex(0.0))}" y2="{_n(base)}" stroke="{COR["line"]}" stroke-width="1.2"/>')
    if ref is not None:
        corpo.append(f'<line x1="{_n(xr)}" y1="{topo - 8}" x2="{_n(xr)}" y2="{_n(base)}" stroke="{COR["neg"]}" stroke-width="1.6" stroke-dasharray="5 4"/>')
        anc = "middle" if 150 < xr < W - 150 else ("start" if xr <= 150 else "end")
        corpo.append(_t(xr, 16, f"{ref_rotulo}: {fmt(ref)}", FS, "neg", anc, 700))
    return _svg(base + 6, corpo + valores, descricao)


def cascata(passos, fmt, descricao=""):
    """passos: [{'rotulo', 'valor', 'total': bool}]. O primeiro e o ultimo sao totais; os do meio somam."""
    x0, x1, topo, plot_h = 14, W - 14, 30, 215
    n = len(passos)
    acum, niveis = 0.0, []
    for p in passos:
        if p.get("total"):
            niveis.append((0.0, p["valor"]))
            acum = p["valor"]
        else:
            niveis.append((acum, acum + p["valor"]))
            acum += p["valor"]
    lo, hi, _ = faixa(min(min(a, b) for a, b in niveis), max(max(a, b) for a, b in niveis) * 1.04)
    ey = lambda v: topo + (hi - v) / (hi - lo) * plot_h
    lw = (x1 - x0) / n
    bw = min(86.0, lw * 0.62)
    corpo = [f'<line x1="{x0}" y1="{_n(ey(0))}" x2="{x1}" y2="{_n(ey(0))}" stroke="{COR["mut"]}" stroke-width="1"/>']
    for k, (p, (a, b)) in enumerate(zip(passos, niveis)):
        xc = x0 + lw * (k + 0.5)
        ya, yb = sorted((ey(a), ey(b)))
        cor = "acc" if p.get("total") else ("pos" if p["valor"] >= 0 else "neg")
        corpo.append(f'<rect x="{_n(xc - bw / 2)}" y="{_n(ya)}" width="{_n(bw)}" height="{_n(max(2.0, yb - ya))}" fill="{COR[cor]}"/>')
        corpo.append(_t(xc, ya - 7, fmt(p["valor"]), FS_VAL, "ink", "middle", 700))
        if k < n - 1 and not passos[k + 1].get("total"):
            corpo.append(f'<line x1="{_n(xc + bw / 2)}" y1="{_n(ey(b))}" x2="{_n(xc + lw - bw / 2)}" y2="{_n(ey(b))}" stroke="{COR["cinza"]}" stroke-width="1" stroke-dasharray="3 3"/>')
        for j, ln in enumerate(quebrar(p["rotulo"], max(9, int(lw / 8.2)))[:3]):
            corpo.append(_t(xc, topo + plot_h + 20 + j * 17, ln, FS - 0.5, "ink", "middle", 600 if p.get("total") else 500))
    return _svg(topo + plot_h + 20 + 3 * 17, corpo, descricao)


def colunas(categorias, series, fmt, fmt_eixo=None, descricao="", rotular=True):
    """series: [{'nome', 'valores' (None permitido), 'cor'}]. Colunas agrupadas, legenda no topo."""
    fmt_eixo = fmt_eixo or fmt
    x0, x1, topo, plot_h = 62, W - 10, 44, 240
    vals = [v for s in series for v in s["valores"] if v is not None]
    lo, hi, passo = faixa(min(vals), max(vals) * 1.06)
    ey = lambda v: topo + (hi - v) / (hi - lo) * plot_h
    corpo, v = [], lo
    while v <= hi + passo * 1e-6:
        corpo.append(f'<line x1="{x0}" y1="{_n(ey(v))}" x2="{x1}" y2="{_n(ey(v))}" stroke="{COR["mut"] if abs(v) < passo * 1e-6 else COR["grade"]}" stroke-width="1"/>')
        corpo.append(_t(x0 - 8, ey(v) + 5, fmt_eixo(v), FS - 1, "mut", "end"))
        v += passo
    xl = 62.0
    for s in series:
        corpo.append(f'<rect x="{_n(xl)}" y="8" width="14" height="14" fill="{COR.get(s["cor"], s["cor"])}"/>')
        corpo.append(_t(xl + 20, 20, s["nome"], FS, "ink", peso=500))
        xl += 20 + largura(s["nome"], FS) + 26
    n, m = len(categorias), len(series)
    lw = (x1 - x0) / n
    bw = min(46.0, lw * 0.78 / m)
    for k, cat in enumerate(categorias):
        xc = x0 + lw * (k + 0.5)
        for j, s in enumerate(series):
            val = s["valores"][k]
            if val is None:
                continue
            xb = xc + (j - m / 2.0) * bw
            ya, yb = sorted((ey(0.0), ey(val)))
            corpo.append(f'<rect x="{_n(xb + 1)}" y="{_n(ya)}" width="{_n(bw - 2)}" height="{_n(max(1.5, yb - ya))}" fill="{COR.get(s["cor"], s["cor"])}"/>')
            if rotular and (m == 1 or lw / m > 40):
                corpo.append(_t(xb + bw / 2, (ya - 5) if val >= 0 else (yb + 15), fmt(val), FS - 2.5, "ink", "middle", 600))
        corpo.append(_t(xc, topo + plot_h + 20, cat, FS - 0.5, "ink", "middle", 500))
    return _svg(topo + plot_h + 30, corpo, descricao)


def pontos(itens, fmt, refs=(), descricao=""):
    """itens: [{'x' (rotulo), 'valor', 'nota' (segunda linha do eixo)}], na ordem do tempo. refs: [(valor, rotulo, cor)]."""
    x0, x1, topo, plot_h = 62, W - 40, 34, 220
    vals = [i["valor"] for i in itens] + [r[0] for r in refs]
    lo, hi, passo = faixa(min(vals) * 0.98, max(vals) * 1.06)
    if min(vals) > 0 and min(vals) > (hi - lo) * 0.5:          # serie longe do zero: nao desperdicar o grafico
        p = passo_bonito(max(vals) - min(vals), 4)
        lo, hi, passo = math.floor(min(vals) / p) * p - p, math.ceil(max(vals) / p) * p + p, p
    ey = lambda v: topo + (hi - v) / (hi - lo) * plot_h
    n = len(itens)
    ex = lambda k: x0 + 30 + (x1 - x0 - 60) * (k / (n - 1) if n > 1 else 0.5)
    corpo, v = [], lo
    while v <= hi + passo * 1e-6:
        corpo.append(f'<line x1="{x0}" y1="{_n(ey(v))}" x2="{x1}" y2="{_n(ey(v))}" stroke="{COR["grade"]}" stroke-width="1"/>')
        corpo.append(_t(x0 - 8, ey(v) + 5, fmt(v), FS - 1, "mut", "end"))
        v += passo
    for val, rot, cor in refs:
        corpo.append(f'<line x1="{x0}" y1="{_n(ey(val))}" x2="{x1}" y2="{_n(ey(val))}" stroke="{COR.get(cor, cor)}" stroke-width="1.5" stroke-dasharray="6 4"/>')
    xl = x1                                                    # legenda das referencias em cima, fora da area dos pontos
    for val, rot, cor in reversed(list(refs)):
        txt = f"{rot}: {fmt(val)}"
        corpo.append(_t(xl, 15, txt, FS - 1, cor, "end", 700))
        xl -= largura(txt, FS - 1, 700) + 8
        corpo.append(f'<line x1="{_n(xl - 26)}" y1="10" x2="{_n(xl)}" y2="10" stroke="{COR.get(cor, cor)}" stroke-width="1.5" stroke-dasharray="6 4"/>')
        xl -= 44
    d = " ".join(("M" if k == 0 else "L") + f"{_n(ex(k))},{_n(ey(i['valor']))}" for k, i in enumerate(itens))
    corpo.append(f'<path d="{d}" fill="none" stroke="{COR["acc"]}" stroke-width="2.4"/>')
    passo_x = max(1, int(math.ceil(n / 8.0)))
    rotulos = []
    for k, i in enumerate(itens):
        corpo.append(f'<circle cx="{_n(ex(k))}" cy="{_n(ey(i["valor"]))}" r="4.5" fill="{COR["fundo"]}" stroke="{COR["acc"]}" stroke-width="2.4"/>')
        if k % passo_x == 0 or k == n - 1:
            x, y, val = ex(k), ey(i["valor"]), i["valor"]
            if k == n - 1 and n > 1:                           # ultimo ponto: numero a direita, fora do caminho da linha
                rotulos.append(_t(x + 10, y + 5, fmt(val), FS - 1, "ink", "start", 700, halo=True))
            else:                                              # fundo de vale: numero embaixo; o resto, em cima
                viz = [itens[j]["valor"] for j in (k - 1, k + 1) if 0 <= j < n]
                vale = bool(viz) and all(val < w for w in viz)
                rotulos.append(_t(x, y + 21 if vale else y - 11, fmt(val), FS - 1, "ink", "middle", 700, halo=True))
            corpo.append(_t(ex(k), topo + plot_h + 20, i["x"], FS - 1.5, "ink", "middle", 500))
            if i.get("nota"):
                corpo.append(_t(ex(k), topo + plot_h + 37, i["nota"], FS - 2.5, "mut", "middle"))
    return _svg(topo + plot_h + 46, corpo + rotulos, descricao)


def linha_tempo(serie, fmt, refs=(), descricao="", fmt_eixo=None):
    """serie: [(data ISO, valor)] longa (diaria). Linha fina, anos no eixo, ultimo valor escrito. refs: [(valor, rotulo, cor)].
    fmt escreve o ultimo valor e as referencias; fmt_eixo (opcional) escreve a grade com menos casas."""
    fmt_eixo = fmt_eixo or fmt
    x0, x1, topo, plot_h = 62, W - 96, 22, 185
    if len(serie) > 420:
        k = len(serie) // 400 + 1
        serie = serie[::k] + ([serie[-1]] if serie[-1] != serie[::k][-1] else [])
    vals = [v for _, v in serie] + [r[0] for r in refs]
    p = passo_bonito(max(vals) - min(vals), 4)
    lo, hi = math.floor(min(vals) / p) * p, math.ceil(max(vals) / p) * p
    ey = lambda v: topo + (hi - v) / (hi - lo) * plot_h
    n = len(serie)
    ex = lambda k: x0 + (x1 - x0) * k / (n - 1)
    corpo, v = [], lo
    while v <= hi + p * 1e-6:
        corpo.append(f'<line x1="{x0}" y1="{_n(ey(v))}" x2="{x1}" y2="{_n(ey(v))}" stroke="{COR["grade"]}" stroke-width="1"/>')
        corpo.append(_t(x0 - 8, ey(v) + 5, fmt_eixo(v), FS - 1, "mut", "end"))
        v += p
    ano = None
    for k, (d, _) in enumerate(serie):
        if d[:4] != ano:
            ano = d[:4]
            if k > 0 or d[5:7] == "01":
                corpo.append(f'<line x1="{_n(ex(k))}" y1="{topo + plot_h}" x2="{_n(ex(k))}" y2="{topo + plot_h + 5}" stroke="{COR["mut"]}" stroke-width="1"/>')
                corpo.append(_t(ex(k) + 3, topo + plot_h + 20, ano, FS - 1, "ink", "start", 500))
    for val, rot, cor in refs:
        corpo.append(f'<line x1="{x0}" y1="{_n(ey(val))}" x2="{x1}" y2="{_n(ey(val))}" stroke="{COR.get(cor, cor)}" stroke-width="1.4" stroke-dasharray="6 4"/>')
        corpo.append(_t(x0 + 6, ey(val) - 6, f"{rot}: {fmt(val)}", FS - 1.5, cor, "start", 600))
    d = " ".join(("M" if k == 0 else "L") + f"{_n(ex(k))},{_n(ey(val))}" for k, (_, val) in enumerate(serie))
    corpo.append(f'<path d="{d}" fill="none" stroke="{COR["acc"]}" stroke-width="2"/>')
    ult = serie[-1][1]
    corpo.append(f'<circle cx="{_n(x1)}" cy="{_n(ey(ult))}" r="4.5" fill="{COR["acc"]}"/>')
    corpo.append(_t(x1 + 9, ey(ult) + 5.5, fmt(ult), FS_VAL, "acc", "start", 700))
    return _svg(topo + plot_h + 30, corpo, descricao)
