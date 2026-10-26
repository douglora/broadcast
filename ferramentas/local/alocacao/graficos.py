"""Graficos do relatorio em SVG embutido (sem matplotlib): leves, nitidos em qualquer tela e no PDF.

Visual: fundo branco, tinta azul-marinho, linhas finas, rotulos em caixa alta com espacamento (estilo das
simulacoes da LF). Cada funcao devolve uma string <svg> pronta para colar no HTML.
"""

from __future__ import annotations

import math
from html import escape

import numpy as np

from . import config as C
from .formato import num, pct, pp

INK = "#0d1b3e"
AZUL = "#1f4e9c"
AZUL_CLARO = "#dce6f5"
AZUL_MEDIO = "#b4c9e8"
OURO = "#b39b6b"
CINZA = "#8a96ad"
LINHA = "#d9e0ec"
VERDE = "#1f7a5a"
VERMELHO = "#b3402a"
FONTE = "Menlo, 'SF Mono', monospace"
FONTE_TXT = "'Avenir Next', 'Helvetica Neue', Arial, sans-serif"


def _svg(w: float, h: float, corpo: str, extra: str = "") -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="100%" '
            f'style="display:block;max-width:100%;font-family:{FONTE_TXT}" {extra}>{corpo}</svg>')


def _t(x, y, txt, tam=8.5, cor=CINZA, ancora="start", peso="400", fonte=FONTE, extra="") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{tam}" fill="{cor}" text-anchor="{ancora}" '
            f'font-weight="{peso}" font-family="{fonte}" {extra}>{escape(str(txt))}</text>')


def _escala(v, v0, v1, p0, p1):
    return p0 + (v - v0) * (p1 - p0) / (v1 - v0) if v1 != v0 else p0


def _ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    if hi <= lo:
        return [lo]
    bruto = (hi - lo) / max(n, 1)
    mag = 10 ** math.floor(math.log10(bruto))
    passo = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= bruto)
    ini = math.ceil(lo / passo) * passo
    out, v = [], ini
    while v <= hi + 1e-9:
        out.append(round(v, 10))
        v += passo
    return out


# ------------------------------------------------------------------------------------------------------
def donut(pesos: dict, centro_1: str = "", centro_2: str = "", tam: int = 260, minimo: float = 0.004) -> str:
    """Rosca por classe, na ordem e nas cores de config.CLASSES."""
    cx = cy = tam / 2
    r_ext, r_int = tam * 0.46, tam * 0.30
    itens = [(c, pesos.get(c.id, 0.0)) for c in C.CLASSES if pesos.get(c.id, 0.0) > minimo]
    total = sum(p for _, p in itens) or 1.0
    ang = -math.pi / 2
    partes = []
    for c, p in itens:
        frac = p / total
        a1 = ang + frac * 2 * math.pi
        gap = 0.012 if len(itens) > 1 else 0.0
        a0, a1g = ang + gap, a1 - gap
        large = 1 if (a1g - a0) > math.pi else 0
        x0, y0 = cx + r_ext * math.cos(a0), cy + r_ext * math.sin(a0)
        x1, y1 = cx + r_ext * math.cos(a1g), cy + r_ext * math.sin(a1g)
        x2, y2 = cx + r_int * math.cos(a1g), cy + r_int * math.sin(a1g)
        x3, y3 = cx + r_int * math.cos(a0), cy + r_int * math.sin(a0)
        d = (f"M{x0:.2f},{y0:.2f} A{r_ext},{r_ext} 0 {large} 1 {x1:.2f},{y1:.2f} "
             f"L{x2:.2f},{y2:.2f} A{r_int},{r_int} 0 {large} 0 {x3:.2f},{y3:.2f} Z")
        partes.append(f'<path d="{d}" fill="{c.cor}"/>')
        if frac >= 0.06:
            am = (ang + a1) / 2
            rx = (r_ext + r_int) / 2
            partes.append(_t(cx + rx * math.cos(am), cy + rx * math.sin(am) + 3, f"{frac*100:.0f}%".replace(".", ","), 9,
                             "#ffffff", "middle", "600", FONTE_TXT))
        ang = a1
    if centro_1:
        partes.append(_t(cx, cy - 2, centro_1, tam * 0.075, INK, "middle", "600", "Charter, Georgia, serif"))
    if centro_2:
        partes.append(_t(cx, cy + tam * 0.07, centro_2, 8, CINZA, "middle", "400", FONTE))
    return _svg(tam, tam, "".join(partes))


def barras_pp(delta_pp: dict, largura: int = 640, altura_linha: int = 22) -> str:
    """Barras horizontais divergentes de variacao em pontos percentuais (aumentar azul, reduzir cinza)."""
    itens = [(C.POR_ID[k], v) for k, v in delta_pp.items() if abs(v) >= 0.05]
    itens.sort(key=lambda x: -x[1])
    n = len(itens)
    if n == 0:
        return _svg(largura, 40, _t(10, 24, "sem movimentos relevantes", 10, CINZA))
    mn = max([-v for _, v in itens if v < 0], default=0.0)
    mp = max([v for _, v in itens if v > 0], default=0.0)
    esq, dir_, topo = 190, 70, 8
    rot_neg = 64 if mn else 0                      # espaco para o rotulo das barras que apontam para a esquerda
    k = (largura - esq - dir_ - rot_neg) / ((mn + mp) or 1.0)
    meio = esq + rot_neg + mn * k
    h = topo * 2 + n * altura_linha
    p = [f'<line x1="{meio:.1f}" x2="{meio:.1f}" y1="{topo}" y2="{h-topo}" stroke="{LINHA}" stroke-width="1"/>']
    for i, (c, v) in enumerate(itens):
        y = topo + i * altura_linha
        w = abs(v) * k
        x = meio if v >= 0 else meio - w
        p.append(_t(esq - 10, y + altura_linha / 2 + 3, c.curto, 10, INK, "end", "400", FONTE_TXT))
        p.append(f'<rect x="{x:.1f}" y="{y+4}" width="{max(w,1):.1f}" height="{altura_linha-8}" rx="2" fill="{AZUL if v>=0 else CINZA}"/>')
        tx = meio + w + 6 if v >= 0 else meio - w - 6
        p.append(_t(tx, y + altura_linha / 2 + 3, pp(v / 100.0, 1), 9, INK, "start" if v >= 0 else "end", "600", FONTE))
    return _svg(largura, h, "".join(p))


def barras_duplas(rotulos: list, a: list, b: list, nome_a: str, nome_b: str, largura: int = 640, linha: int = 28,
                  fmt=lambda v: pct(v, 1)) -> str:
    """Duas barras por categoria (ex.: atual x proposta, peso x risco)."""
    n = len(rotulos)
    esq, dir_, topo = 170, 60, 26
    maxv = max(max(a + b), 1e-9)
    h = topo + n * linha + 6
    util = largura - esq - dir_
    p = [f'<rect x="{esq}" y="6" width="9" height="9" rx="1.5" fill="{AZUL_MEDIO}"/>', _t(esq + 14, 14, nome_a, 8.5, CINZA),
         f'<rect x="{esq+110}" y="6" width="9" height="9" rx="1.5" fill="{AZUL}"/>', _t(esq + 124, 14, nome_b, 8.5, CINZA)]
    for i, r in enumerate(rotulos):
        y = topo + i * linha
        p.append(_t(esq - 10, y + 17, r, 10, INK, "end", "400", FONTE_TXT))
        wa, wb = a[i] / maxv * util, b[i] / maxv * util
        p.append(f'<rect x="{esq}" y="{y+3}" width="{max(wa,0.5):.1f}" height="8" rx="1.5" fill="{AZUL_MEDIO}"/>')
        p.append(f'<rect x="{esq}" y="{y+13}" width="{max(wb,0.5):.1f}" height="8" rx="1.5" fill="{AZUL}"/>')
        p.append(_t(esq + wa + 5, y + 10.5, fmt(a[i]), 8, CINZA))
        p.append(_t(esq + wb + 5, y + 20.5, fmt(b[i]), 8, INK, peso="600"))
    return _svg(largura, h, "".join(p))


def fronteira(curva: list, pontos: list, largura: int = 640, altura: int = 300) -> str:
    """Retorno x volatilidade: fronteira eficiente (linha) e carteiras marcadas.
    curva = [(vol, ret)], pontos = [{'nome','vol','ret','cor','destaque'}], valores em fracao."""
    esq, dir_, topo, base = 56, 20, 16, 40
    todos = [(v, r) for v, r in curva] + [(p["vol"], p["ret"]) for p in pontos]
    vmin, vmax = 0.0, max(v for v, _ in todos) * 1.12
    rmin = min(r for _, r in todos) - 0.004
    rmax = max(r for _, r in todos) + 0.004
    X = lambda v: _escala(v * 100, vmin * 100, vmax * 100, esq, largura - dir_)
    Y = lambda r: _escala(r * 100, rmin * 100, rmax * 100, altura - base, topo)
    p = []
    for t in _ticks(rmin * 100, rmax * 100, 5):
        y = Y(t / 100)
        p.append(f'<line x1="{esq}" x2="{largura-dir_}" y1="{y:.1f}" y2="{y:.1f}" stroke="{LINHA}" stroke-width="0.7"/>')
        p.append(_t(esq - 8, y + 3, f"{num(t,1)}%", 8, CINZA, "end"))
    for t in _ticks(vmin * 100, vmax * 100, 6):
        x = X(t / 100)
        p.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{topo}" y2="{altura-base}" stroke="{LINHA}" stroke-width="0.5" stroke-dasharray="2 3"/>')
        p.append(_t(x, altura - base + 16, f"{num(t,1)}%", 8, CINZA, "middle"))
    p.append(_t((esq + largura - dir_) / 2, altura - 6, "RISCO (VOLATILIDADE AO ANO)", 8, CINZA, "middle", extra='letter-spacing="1.6"'))
    p.append(f'<text transform="translate(12,{(topo+altura-base)/2}) rotate(-90)" font-size="8" fill="{CINZA}" text-anchor="middle" font-family="{FONTE}" letter-spacing="1.6">RETORNO LÍQUIDO AO ANO</text>')
    if curva:
        pts = " ".join(f"{X(v):.1f},{Y(r):.1f}" for v, r in curva)
        p.append(f'<polyline points="{pts}" fill="none" stroke="{AZUL}" stroke-width="2" stroke-linejoin="round"/>')
        p.append(_t(X(curva[-1][0]) - 8, Y(curva[-1][1]) - 8, "fronteira eficiente", 8.5, AZUL, "end", extra='font-style="italic"'))
    for q in pontos:
        x, y = X(q["vol"]), Y(q["ret"])
        r = 6.5 if q.get("destaque") else 5
        p.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{q.get("cor", INK)}" stroke="#fff" stroke-width="1.5"/>')
        dx = q.get("dx", 10)
        p.append(_t(x + dx, y + q.get("dy", 4), q["nome"], 9, INK, "start" if dx >= 0 else "end", "600" if q.get("destaque") else "400", FONTE_TXT))
    return _svg(largura, altura, "".join(p))


def fan(sim: dict, meta_real: float | None, largura: int = 640, altura: int = 300, pl: float | None = None) -> str:
    """Leque de percentis do patrimonio em reais de hoje."""
    fr = sim["faixa_real"]
    T = sim["meses"]
    anos = sim["anos"]
    esq, dir_, topo, base = 62, 70, 16, 34
    ymax = max(fr[95].max(), meta_real or 0) * 1.05
    ymin = min(fr[5].min(), (pl or fr[5][0])) * 0.92
    X = lambda m: _escala(m / 12.0, 0, anos, esq, largura - dir_)
    Y = lambda v: _escala(v, ymin, ymax, altura - base, topo)
    p = []
    for t in _ticks(ymin / 1e6, ymax / 1e6, 5):
        y = Y(t * 1e6)
        p.append(f'<line x1="{esq}" x2="{largura-dir_}" y1="{y:.1f}" y2="{y:.1f}" stroke="{LINHA}" stroke-width="0.7"/>')
        p.append(_t(esq - 8, y + 3, f"R$ {num(t,1)} mi", 8, CINZA, "end"))
    passo = 1 if anos <= 12 else 2
    for a in range(0, int(anos) + 1, passo):
        x = X(a * 12)
        p.append(_t(x, altura - base + 16, f"{a}a" if a else "hoje", 8, CINZA, "middle"))
    ms = list(range(0, T + 1))

    def faixa(lo, hi, cor):
        sup = " ".join(f"{X(m):.1f},{Y(hi[m]):.1f}" for m in ms)
        inf = " ".join(f"{X(m):.1f},{Y(lo[m]):.1f}" for m in reversed(ms))
        return f'<polygon points="{sup} {inf}" fill="{cor}"/>'
    p.append(faixa(fr[5], fr[95], AZUL_CLARO))
    p.append(faixa(fr[25], fr[75], AZUL_MEDIO))
    p.append(f'<polyline points="{" ".join(f"{X(m):.1f},{Y(fr[50][m]):.1f}" for m in ms)}" fill="none" stroke="{INK}" stroke-width="2.2" stroke-linejoin="round"/>')
    if meta_real:
        y = Y(meta_real)
        p.append(f'<line x1="{esq}" x2="{largura-dir_}" y1="{y:.1f}" y2="{y:.1f}" stroke="{OURO}" stroke-width="1.6" stroke-dasharray="6 4"/>')
        p.append(_t(largura - dir_ + 6, y - 3, "META", 8, OURO, "start", "700", extra='letter-spacing="1.4"'))
        p.append(_t(largura - dir_ + 6, y + 8, f"R$ {num(meta_real/1e6,1)} mi", 8, OURO))
    for q, rot in ((95, "P95"), (50, "MEDIANA"), (5, "P5")):
        v = fr[q][T]
        p.append(_t(largura - dir_ + 6, Y(v) + (3 if not (meta_real and abs(Y(v) - Y(meta_real)) < 14) else 14), f"{rot} {num(v/1e6,1)}", 8, INK if q == 50 else CINZA, "start", "600" if q == 50 else "400"))
    return _svg(largura, altura, "".join(p))


def barras_estresse(cenarios: list, largura: int = 640, linha: int = 30) -> str:
    """Impacto instantaneo de cada cenario na carteira (barras divergentes, vermelho/azul)."""
    n = len(cenarios)
    esq, dir_, topo = 210, 70, 6
    maxv = max(abs(c["total"]) for c in cenarios) or 0.01
    meio = esq + (largura - esq - dir_) * (0.62 if min(c["total"] for c in cenarios) < 0 else 0.1)
    esp_neg, esp_pos = meio - esq - 58, largura - dir_ - meio - 4     # 58: espaco do rotulo das barras negativas
    h = topo * 2 + n * linha
    p = [f'<line x1="{meio}" x2="{meio}" y1="{topo}" y2="{h-topo}" stroke="{LINHA}"/>']
    for i, c in enumerate(cenarios):
        y = topo + i * linha
        v = c["total"]
        w = abs(v) / maxv * (esp_neg if v < 0 else esp_pos)
        x = meio - w if v < 0 else meio
        p.append(_t(esq - 12, y + linha / 2 + 3, c["nome"], 9.5, INK, "end", "400", FONTE_TXT))
        p.append(f'<rect x="{x:.1f}" y="{y+6}" width="{max(w,1):.1f}" height="{linha-12}" rx="2" fill="{VERMELHO if v<0 else AZUL}"/>')
        tx = x - 6 if v < 0 else x + w + 6
        p.append(_t(tx, y + linha / 2 + 3, f"{v*100:+.1f}%".replace(".", ","), 9, INK, "end" if v < 0 else "start", "600"))
    return _svg(largura, h, "".join(p))


def curva_di(viva: list, ajuste: list, ntnb: list, largura: int = 640, altura: int = 250) -> str:
    """Curva DI (ajuste e, se houver, ultimo negocio) e juro real da NTN-B, por prazo em anos."""
    esq, dir_, topo, base = 50, 90, 14, 34
    series = []
    if ajuste:
        series.append(("DI ajuste de ontem", [(du / 252.0, t) for du, t in ajuste if du / 252.0 <= 10.5], CINZA, "5 4"))
    if viva:
        series.append(("DI agora", [(du / 252.0, t) for du, t in viva if du / 252.0 <= 10.5], AZUL, ""))
    if ntnb:
        series.append(("NTN-B real (ANBIMA)", [(a, t) for a, t in ntnb if a <= 10.5], OURO, ""))
    todos = [t for _, pts, *_ in series for _, t in pts]
    ymin, ymax = math.floor(min(todos)) - 0.5, math.ceil(max(todos)) + 0.5
    X = lambda a: _escala(a, 0, 10.5, esq, largura - dir_)
    Y = lambda v: _escala(v, ymin, ymax, altura - base, topo)
    p = []
    for t in _ticks(ymin, ymax, 5):
        y = Y(t)
        p.append(f'<line x1="{esq}" x2="{largura-dir_}" y1="{y:.1f}" y2="{y:.1f}" stroke="{LINHA}" stroke-width="0.7"/>')
        p.append(_t(esq - 8, y + 3, f"{num(t,1)}%", 8, CINZA, "end"))
    for a in (0, 2, 4, 6, 8, 10):
        p.append(_t(X(a), altura - base + 16, f"{a}a", 8, CINZA, "middle"))
    for nome, pts, cor, dash in series:
        pts = sorted(pts)
        pontos = " ".join(f"{X(a):.1f},{Y(t):.1f}" for a, t in pts)
        tracejado = f'stroke-dasharray="{dash}"' if dash else ""
        p.append(f'<polyline points="{pontos}" fill="none" stroke="{cor}" stroke-width="2" {tracejado} stroke-linejoin="round"/>')
        a, t = pts[-1]
        p.append(_t(X(a) + 6, Y(t) + 3, nome, 8, cor, "start", "600"))
    return _svg(largura, altura, "".join(p))


def empilhado(trilha: dict, largura: int = 640, altura: int = 250) -> str:
    """Composicao por ano (barras empilhadas, 100%)."""
    anos = trilha["anos"]
    comp = trilha["composicao"]
    esq, dir_, topo, base = 40, 10, 10, 30
    n = len(anos)
    larg = (largura - esq - dir_) / n
    barra = min(larg * 0.66, 46)
    p = []
    for t in (0, 25, 50, 75, 100):
        y = _escala(t, 0, 100, altura - base, topo)
        p.append(f'<line x1="{esq}" x2="{largura-dir_}" y1="{y:.1f}" y2="{y:.1f}" stroke="{LINHA}" stroke-width="0.6"/>')
        p.append(_t(esq - 6, y + 3, f"{t}%", 8, CINZA, "end"))
    for i, a in enumerate(anos):
        x = esq + i * larg + (larg - barra) / 2
        acc = 0.0
        for j, c in enumerate(C.CLASSES):
            v = float(comp[i][j])
            if v <= 0.002:
                continue
            y1 = _escala(acc * 100, 0, 100, altura - base, topo)
            y2 = _escala((acc + v) * 100, 0, 100, altura - base, topo)
            p.append(f'<rect x="{x:.1f}" y="{y2:.1f}" width="{barra:.1f}" height="{y1-y2:.1f}" fill="{c.cor}"/>')
            acc += v
        if n <= 16 or a % (2 if n <= 26 else 5) == 0:
            p.append(_t(x + barra / 2, altura - base + 15, "hoje" if a == 0 else f"{a}a", 8, CINZA, "middle"))
    return _svg(largura, altura, "".join(p))


def escada_liquidez(liq: dict, largura: int = 640) -> str:
    """Uma barra empilhada: quanto sai em D+1, ate D+5, ate D+30, ate D+90 e acima."""
    rot = [("d1", "D+1", "#0d1b3e"), ("d5", "até D+5", AZUL), ("d30", "até D+30", "#7aa3e0"), ("d90", "até D+90", AZUL_MEDIO), ("mais", "acima", LINHA)]
    esq, dir_ = 10, 10
    util = largura - esq - dir_
    x = esq
    p = []
    for k, nome, cor in rot:
        v = liq.get(k, 0.0)
        if v <= 0.0005:
            continue
        w = v * util
        p.append(f'<rect x="{x:.1f}" y="22" width="{w:.1f}" height="30" fill="{cor}"/>')
        if w > 34:
            p.append(_t(x + w / 2, 41, f"{v*100:.0f}%".replace(".", ","), 10, "#fff" if cor not in (LINHA, AZUL_MEDIO) else INK, "middle", "600", FONTE_TXT))
        p.append(_t(x + 2, 14, nome, 7.5, CINZA, extra='letter-spacing="1"'))
        x += w
    return _svg(largura, 62, "".join(p))


def barras_retorno(prem: list, bench: float, largura: int = 640, linha: int = 26) -> str:
    """Retorno bruto e liquido esperado por classe, com a linha do 100% CDI tributado."""
    n = len(prem)
    esq, dir_, topo = 170, 70, 26
    maxv = max(max(x["bruto"] for x in prem), bench) * 1.05
    util = largura - esq - dir_
    h = topo + n * linha + 12
    p = [f'<rect x="{esq}" y="6" width="9" height="9" rx="1.5" fill="{AZUL_MEDIO}"/>', _t(esq + 14, 14, "bruto", 8.5, CINZA),
         f'<rect x="{esq+70}" y="6" width="9" height="9" rx="1.5" fill="{AZUL}"/>', _t(esq + 84, 14, "líquido de imposto", 8.5, CINZA)]
    xb = esq + bench / maxv * util
    p.append(f'<line x1="{xb:.1f}" x2="{xb:.1f}" y1="{topo-4}" y2="{h-6}" stroke="{OURO}" stroke-width="1.4" stroke-dasharray="5 3"/>')
    p.append(_t(xb + 4, topo - 8, f"100% CDI líquido {pct(bench,1)}", 8, OURO, "start", "700"))
    for i, x in enumerate(prem):
        y = topo + i * linha
        p.append(_t(esq - 10, y + 15, x["classe"], 10, INK, "end", "400", FONTE_TXT))
        p.append(f'<rect x="{esq}" y="{y+3}" width="{x["bruto"]/maxv*util:.1f}" height="7" rx="1.5" fill="{AZUL_MEDIO}"/>')
        p.append(f'<rect x="{esq}" y="{y+12}" width="{x["liquido"]/maxv*util:.1f}" height="7" rx="1.5" fill="{AZUL}"/>')
        p.append(_t(esq + x["liquido"] / maxv * util + 5, y + 19, pct(x["liquido"], 1), 8.5, INK, "start", "600", extra='stroke="#fff" stroke-width="3" paint-order="stroke"'))
    return _svg(largura, h, "".join(p))
