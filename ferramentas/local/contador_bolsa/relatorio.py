"""Relatorio mensal de renda variavel (imposto de renda em bolsa): HTML em A4 paisagem convertido em PDF pelo Chrome.

Camada visual do contador de bolsa. Recebe o dicionario do motor de calculo (formato na docstring de `html_relatorio`)
e devolve o HTML (uma <section> por pagina) ou grava o PDF, com senha opcional (AES-256). Nao calcula imposto: so mostra.

Paginas, na ordem: capa, posicao de carteira (rosca + resumo + tabelas), operacoes finalizadas no mes (barras + quadro +
tabelas por grupo), extrato consolidado, proventos recebidos (+ barras dos ultimos 12 meses), proventos provisionados,
resultados anuais e situacao fiscal. Tabela longa quebra de pagina repetindo titulo e cabecalho, sem cortar linha.

Visual: faixa azul no topo com nome, documento, competencia e data; titulos azul-marinho; cabecalho de tabela azul-claro;
negativos em marrom; caixa cinza de aviso no rodape de cada pagina. Fonte Helvetica/Arial.
O PDF e gravado so onde o chamador mandar: o HTML e o perfil do Chrome ficam em pasta temporaria.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import subprocess
import tempfile
import unicodedata
from html import escape
from pathlib import Path

CHROME = Path(os.environ.get("CONTADOR_BOLSA_CHROME", os.environ.get(
    "ALOCACAO_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")))

# ------------------------------------------------------------------ geometria (pontos; A4 paisagem do Chrome)
PAG_W = 841.9
PAG_H = 594.96
X0 = 16.8                 # borda esquerda das tabelas
X1 = 825.1                # borda direita
Y_FUNDO = 544.0           # o conteudo nao passa daqui (o filete do aviso fica em 549.9)
Y_CONT = 47.9             # topo do bloco numa pagina de continuacao
GAP = 19.74               # espaco entre dois blocos na mesma pagina
H_LIN = 15.758            # linha das tabelas de posicao e de operacoes
H_LIN2 = 22.0             # linha com texto em duas linhas
H_CAB = 16.012            # cabecalho simples
# geometria do bloco (titulo + tabela) por tipo de tabela: altura do titulo, espaco entre blocos e topo do bloco numa
# pagina de continuacao
GEO = {
    "p": {"tit_h": 14.28, "gap": 19.74, "y_cont": 47.9},
    "o": {"tit_h": 15.28, "gap": 18.74, "y_cont": 47.0},
}
GEO_PADRAO = GEO["p"]
TIT_BASE = 9.3            # linha de base do titulo do bloco, contada do topo do bloco

# ------------------------------------------------------------------ cores
# (texto #023463, faixa do topo #235a8e, filete de linha #d5dce3 e borda de cartao #d3d3d3 estao direto no CSS)
CAB = "#d9e8f9"
SUAVE = "#eef3f9"
NEG = "#943f2d"
ROSCA = ["#76aaf8", "#96f2ff", "#ffa819", "#8fe3b3", "#c3a6f5", "#ff9fb8", "#b3bccb"]

MESES = ["JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO", "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO",
         "NOVEMBRO", "DEZEMBRO"]

# ------------------------------------------------------------------ avisos do rodape (texto nosso)
LEI = ("conforme a Lei 11.033/2004, a Lei 8.981/1995 e a IN RFB 1.585/2015. "
       "Confira os valores antes de pagar o DARF.")
AVISO_POSICAO = ("A posição de carteira reúne os ativos em custódia no último dia do mês de referência e é valorizada "
                 "pelo preço de fechamento desse dia. Relatório calculado a partir das notas de corretagem e do extrato "
                 "do Open Finance, " + LEI)
AVISO_OPERACOES = ("A data de estoque é a da última posição do ativo em carteira até a data de liquidação. "
                   "Resultados pelo custo médio ponderado, calculados a partir das notas de corretagem e do extrato "
                   "do Open Finance, " + LEI)
AVISO_EXTRATO = ("Extrato consolidado a partir dos dados das corretoras integradas via Open Finance e das notas de "
                 "corretagem. Se algum lançamento não aparecer, a integração pode estar incompleta. " +
                 "Confira os valores antes de pagar o DARF.")
AVISO_PROVENTOS = "Valores conforme o extrato da conta; a tributação de cada provento segue a legislação vigente."
AVISO_PROVISIONADOS = "Proventos anunciados pelas empresas e ainda não pagos; valores podem mudar."
AVISO_ANUAL = ("Resultado líquido = operações finalizadas no mês + proventos recebidos - impostos e despesas. "
               "Relatório calculado a partir das notas de corretagem e do extrato do Open Finance, " + LEI)
AVISO_SITUACAO = ("Resumo dos DARFs, do prejuízo acumulado e das conferências feitas na apuração; não substitui a "
                  "orientação do contador. Confira os valores antes de pagar o DARF.")

# ------------------------------------------------------------------ largura de texto (metricas da Helvetica, AFM)
_ESPECIAIS = {0x2013: 556, 0x2014: 1000, 0x2022: 350, 0xB7: 278, 0x2026: 1000, 0x20AC: 556}


def _tabela_afm(g1, g2, g3, g4, g5, g6) -> dict:
    cods = list(range(32, 127))
    vals = list(g1) + [556] * 10 + list(g2) + list(g3) + list(g4) + list(g5) + list(g6)
    return dict(zip(cods, vals))


_REG = _tabela_afm(
    [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278],
    [278, 278, 584, 584, 584, 556, 1015],
    [667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667,
     944, 667, 667, 611],
    [278, 278, 278, 469, 556, 333],
    [556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500,
     722, 500, 500, 500],
    [334, 260, 334, 584])
_BOLD = _tabela_afm(
    [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278],
    [333, 333, 584, 584, 584, 611, 975],
    [722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667,
     944, 667, 667, 611],
    [333, 278, 333, 584, 556, 333],
    [556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556,
     778, 556, 556, 500],
    [389, 280, 389, 584])


def _larg(txt: str, pt: float, negrito: bool = False) -> float:
    """Largura aproximada do texto em pontos (acento conta como a letra-base)."""
    tab = _BOLD if negrito else _REG
    w = 0
    for ch in unicodedata.normalize("NFD", str(txt)):
        if unicodedata.combining(ch):
            continue
        w += tab.get(ord(ch)) or _ESPECIAIS.get(ord(ch), 556)
    return w * pt / 1000.0


def _quebra(txt: str, larg: float, pt: float = 8, negrito: bool = False, max_linhas: int = 2) -> list[str]:
    """Quebra por palavras em ate `max_linhas` linhas; a ultima leva o resto (o CSS corta com reticencias)."""
    linhas: list[str] = []
    atual = ""
    for p in str(txt).split():
        cand = f"{atual} {p}".strip()
        if not atual or _larg(cand, pt, negrito) <= larg:
            atual = cand
        else:
            linhas.append(atual)
            atual = p
    if atual:
        linhas.append(atual)
    if len(linhas) > max_linhas:
        linhas = linhas[:max_linhas - 1] + [" ".join(linhas[max_linhas - 1:])]
    return linhas or [""]


# ------------------------------------------------------------------ formatacao brasileira
def e(x) -> str:
    return escape(str(x if x is not None else ""))


def _milhar(x: float, casas: int) -> str:
    return f"{abs(x):,.{casas}f}".replace(",", "\0").replace(".", ",").replace("\0", ".")


def num(x, casas: int = 2) -> str:
    if x is None:
        return "-"
    x = float(x)
    if round(x, casas) == 0:
        x = 0.0
    return ("-" if x < 0 else "") + _milhar(x, casas)


def brl(x, casas: int = 2) -> str:
    """R$ 1.234,56; negativo como -R$ 1.234,56; None vira '-'."""
    if x is None:
        return "-"
    x = float(x)
    if round(x, casas) == 0:
        x = 0.0
    return ("-R$ " if x < 0 else "R$ ") + _milhar(x, casas)


def pct(x, casas: int = 2) -> str:
    """12,34 % (o numero ja vem em pontos percentuais)."""
    return "-" if x is None else num(x, casas) + " %"


def qtd(x) -> str:
    if x is None:
        return "-"
    x = float(x)
    return num(int(x), 0) if x == int(x) else num(x, 2)


def dat(x) -> str:
    if x is None or x == "":
        return "-"
    if isinstance(x, (dt.date, dt.datetime)):
        return x.strftime("%d/%m/%Y")
    return str(x)


def _neg(x) -> bool:
    return x is not None and round(float(x), 2) < 0


def _v(x, casas: int = 2):
    """Celula de valor em R$: (texto, classe) com marrom no negativo."""
    return (brl(x, casas), "neg" if _neg(x) else "")


def _perda(x):
    """Prejuizo a compensar: sempre negativo na tela (e uma perda), zero fica R$ 0,00."""
    if x is None:
        return ("-", "")
    return _v(-abs(float(x)))


def _sem_acento(txt: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(txt)) if unicodedata.category(c) != "Mn")


def _soma(linhas: list, campo: str) -> float:
    return sum(float(r.get(campo) or 0.0) for r in linhas)


def _mes_extenso(competencia: str) -> str:
    try:
        m, a = str(competencia).split("/")
        return f"{MESES[int(m) - 1]}/{a}"
    except (ValueError, IndexError):
        return str(competencia).upper()


# ------------------------------------------------------------------ CSS
CSS = """
@page { size: A4 landscape; margin: 0; }
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { background: #fff; }
body { font-family: Helvetica, Arial, sans-serif; color: #023463; font-size: 8pt; font-variant-ligatures: none;
       -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.pg { position: relative; width: 297mm; height: 209.6mm; overflow: hidden; background: #fff;
      break-after: page; page-break-after: always; }
.pg:last-child { break-after: auto; page-break-after: auto; }
.a { position: absolute; white-space: nowrap; }
.ov { position: absolute; left: 0; top: 0; }
.ov text { font-family: Helvetica, Arial, sans-serif; fill: #023463; }
.ov text.neg { fill: #943f2d; }
.fx { position: absolute; left: 0; top: 0; width: 297mm; height: 28.25pt; background: #235a8e; }
.bw { color: #fff; font-weight: 700; }
.card { position: absolute; border: .6pt solid #d3d3d3; background: #fff; }
.fio { position: absolute; left: 0; width: 297mm; height: .5pt; background: #ededed; }
.disc { position: absolute; left: 16.87pt; width: 809.18pt; background: #eef3f9; border-radius: 7pt;
        padding: 8.2pt 8.4pt 0 7.6pt; font-size: 7pt; line-height: 7.9pt; color: #023463; white-space: normal; }
.disc b { font-weight: 700; }
.neg { color: #943f2d; }
.r { text-align: right; }
.c { text-align: center; }
thead { display: table-header-group; }
tr { break-inside: avoid; page-break-inside: avoid; }
table.t { border-collapse: separate; border-spacing: 0; table-layout: fixed; }
table.t th, table.t td { padding: 0; font-size: 8pt; line-height: 9pt; font-weight: 400; text-align: left;
        vertical-align: middle; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #023463; }
table.t th { font-weight: 700; }
table.t td.neg { color: #943f2d; }
table.t th.r, table.t td.r { text-align: right; }
table.t th.c, table.t td.c { text-align: center; }
/* posicao e operacoes */
table.p th { background: #d9e8f9; height: 16.012pt; padding-top: .3pt; }
table.p td { height: 15.758pt; padding-top: .7pt; border-bottom: .5pt solid #d5dce3; }
table.o tr.g th { background: #d9e8f9; text-align: center; height: 17.01pt; padding-top: .3pt; }
table.o tr.h th { background: #eef3f9; height: 17.01pt; padding-top: .3pt; }
table.o td { height: 15.758pt; padding-top: .7pt; border-bottom: .5pt solid #d5dce3; }
table.t tr.m td { vertical-align: top; padding-top: 2.1pt; }
/* proventos */
table.q th, table.q td { background: #eef3f9; height: 20.51pt; }
table.q tr.tot td { background: #d9e8f9; font-weight: 700; height: 21.26pt; }
table.q.l td { border-bottom: .5pt solid #fff; }
/* extrato */
table.x th { background: #eef3f9; height: 20.51pt; }
table.x td { height: 20.51pt; padding-top: .7pt; border-bottom: .5pt solid #d5dce3; }
table.x tr.tot td { background: #f5f5f5; font-weight: 700; border-bottom: 0; }
/* resultados anuais */
table.n th { background: #d9e8f9; height: 22.26pt; }
table.n td { height: 17pt; font-size: 6pt; padding-top: 1.4pt; }
table.n td.l { font-size: 7pt; padding-top: .4pt; }
table.n tr.f td { border-top: 1pt solid #abbdce; padding-top: .4pt; }
table.n tr.f td.l { padding-top: 0; }
table.n tr.b td { font-weight: 700; }
table.n tr.z td { border-bottom: .5pt solid #abbdce; }
/* situacao fiscal: celulas cheias com filete branco (s) ou linhas finas sobre fundo branco (s l) */
table.s th { background: #eef3f9; height: 17.01pt; padding-top: .3pt; border-bottom: .5pt solid #fff; }
table.s td { background: #eef3f9; height: 18.43pt; font-size: 7pt; line-height: 8.6pt; border-bottom: .5pt solid #fff; }
table.s.l td { background: transparent; border-bottom: .5pt solid #d5dce3; }
"""


# ------------------------------------------------------------------ pecas de HTML e SVG
def _off(pt: float) -> float:
    """Distancia do topo da caixa (line-height = corpo) ate a linha de base do texto."""
    return 0.835 * pt


def _t(x: float, base: float, txt: str, pt: float = 8, peso: int = 400, cor: str | None = None, anc: str = "e",
       cls: str = "", raw: bool = False, larg_pag: float = PAG_W) -> str:
    """Texto posicionado pela linha de base (anc: 'e' esquerda, 'd' direita, 'c' centro)."""
    top = base - _off(pt)
    if anc == "d":
        pos = f"right:{larg_pag - x:.2f}pt"
    elif anc == "c":
        pos = f"left:{x - 200:.2f}pt;width:400pt;text-align:center"
    else:
        pos = f"left:{x:.2f}pt"
    st = f"{pos};top:{top:.2f}pt;font-size:{pt}pt;line-height:{pt}pt"
    if peso != 400:
        st += f";font-weight:{peso}"
    if cor:
        st += f";color:{cor}"
    return f'<div class="a {cls}" style="{st}">{txt if raw else e(txt)}</div>'


def _s(x: float, y: float, txt: str, pt: float = 8, peso: int = 400, cor: str | None = None, anc: str = "start") -> str:
    """Texto SVG (y e a linha de base)."""
    cls = ""
    if cor == NEG:
        cls = ' class="neg"'
        cor = None
    fill = f' fill="{cor}"' if cor else ""
    w = f' font-weight="{peso}"' if peso != 400 else ""
    return f'<text x="{x:.2f}" y="{y:.2f}" font-size="{pt}"{w}{fill} text-anchor="{anc}"{cls}>{e(txt)}</text>'


def _sv(x: float, y: float, valor, pt: float = 8, peso: int = 400, anc: str = "start", casas: int = 2) -> str:
    return _s(x, y, brl(valor, casas), pt, peso, NEG if _neg(valor) else None, anc)


def _ov(corpo: str, larg_pag: float = PAG_W, alt_pag: float = PAG_H) -> str:
    # SVG em linha no HTML5 dispensa o xmlns: o HTML final nao leva nenhum endereco de internet
    return (f'<svg class="ov" width="{larg_pag}pt" height="{alt_pag}pt" viewBox="0 0 {larg_pag} {alt_pag}">'
            f'{corpo}</svg>')


def _card(x0: float, y0: float, x1: float, y1: float) -> str:
    return (f'<div class="card" style="left:{x0:.2f}pt;top:{y0:.2f}pt;width:{x1 - x0:.2f}pt;'
            f'height:{y1 - y0:.2f}pt"></div>')


def _faixa(d: dict) -> str:
    tit = d.get("titular") or {}
    return ('<div class="fx"></div>'
            + _t(18.9, 11.0, f"Nome: {tit.get('nome', '')}", 6, 700, cls="bw")
            + _t(18.9, 21.2, f"CPF / CNPJ: {tit.get('documento', '')}", 6, 700, cls="bw")
            + _t(666.6, 11.2, f"Demonstrativo Mensal: {d.get('competencia', '')}", 6, 700, cls="bw")
            + _t(666.6, 22.2, f"Gerado em: {d.get('gerado_em', '')}", 6, 700, cls="bw"))


def _aviso(txt: str) -> str:
    return ('<div class="fio" style="top:550.1pt"></div>'
            f'<div class="disc" style="top:555.3pt;height:32.75pt"><b>Disclaimer:</b> {e(txt)}</div>')


# ------------------------------------------------------------------ tabelas
def _cols_x(xs: list[float], fim: float = X1, ini: float = X0, quebra: tuple = (), pad: float = 2.0) -> list[dict]:
    """Colunas alinhadas a esquerda a partir do x em que o texto de cada uma comeca.

    Como no modelo, a borda de cada coluna fica `pad` antes do texto (folga de 2 pt dos dois lados); a 1a coluna
    comeca em `ini`.
    """
    esq = [ini] + [x - pad for x in xs[1:]]
    bordas = esq + [fim]
    out = []
    for i, x in enumerate(xs):
        c = {"w": bordas[i + 1] - bordas[i], "a": "l", "pl": x - esq[i], "pr": pad}
        if i in quebra:
            c["q"] = True
        out.append(c)
    return out


def _td(col: dict, cel) -> str:
    txt, cls = cel if isinstance(cel, tuple) else (cel, "")
    corpo = "<br>".join(e(x) for x in txt) if isinstance(txt, list) else e(txt)
    if col.get("a") == "r":
        cls += " r"
    elif col.get("a") == "c":
        cls += " c"
    st = ""
    if col.get("pl"):
        st += f"padding-left:{col['pl']:.2f}pt;"
    if col.get("pr"):
        st += f"padding-right:{col['pr']:.2f}pt;"
    return f'<td class="{cls.strip()}" style="{st}">{corpo}</td>' if st or cls.strip() else f"<td>{corpo}</td>"


def _linha(cols: list[dict], vals: list, h1: float = H_LIN, h2: float = H_LIN2, cls: str = "") -> tuple:
    """Uma linha de corpo; devolve (html, altura). Texto que nao cabe passa para a 2a linha (altura h2)."""
    n = 1
    cels = []
    for col, v in zip(cols, vals):
        txt, c = v if isinstance(v, tuple) else (v, "")
        if col.get("q") and isinstance(txt, str):
            cap = col["w"] - col.get("pl", 0.0) - col.get("pr", 0.0) - 1.5
            ls = _quebra(txt, cap, 8, False, 2)
            n = max(n, len(ls))
            txt = ls if len(ls) > 1 else txt
        cels.append((txt, c))
    h = h1 if n == 1 else h2
    st = f' style="height:{h}pt"' if n > 1 else ""
    cl = (cls + (" m" if n > 1 else "")).strip()          # linha de 2 linhas: texto colado no topo, como no modelo
    c_tr = f' class="{cl}"' if cl else ""
    return (f"<tr{c_tr}{st}>" + "".join(_td(c, v) for c, v in zip(cols, cels)) + "</tr>", h)


def _linha_fixa(cols: list[dict], vals: list, h: float, cls: str = "") -> tuple:
    c_tr = f' class="{cls}"' if cls else ""
    return (f"<tr{c_tr}>" + "".join(_td(c, v) for c, v in zip(cols, vals)) + "</tr>", h)


def _cab(cols: list[dict], titulos: list[str], h: float = H_CAB) -> tuple:
    ths = "".join(f'<th class="{ "r" if c.get("a") == "r" else ""}" style="'
                  f'{"padding-left:%.2fpt;" % c["pl"] if c.get("pl") else ""}'
                  f'{"padding-right:%.2fpt;" % c["pr"] if c.get("pr") else ""}">{e(t)}</th>'
                  for c, t in zip(cols, titulos))
    return (f"<thead><tr>{ths}</tr></thead>", h)


def _tabela(cols: list[dict], cab_html: str, linhas: list, classe: str) -> str:
    larg = sum(c["w"] for c in cols)
    cg = "".join(f'<col style="width:{c["w"]:.2f}pt">' for c in cols)
    corpo = "".join(h for h, _ in linhas)
    return (f'<table class="t {classe}" style="width:{larg:.2f}pt"><colgroup>{cg}</colgroup>'
            f"{cab_html}<tbody>{corpo}</tbody></table>")


# ------------------------------------------------------------------ paginas e fluxo
class _Pg:
    def __init__(self, aviso: str | None, y: float, capa: bool = False):
        self.aviso = aviso
        self.itens: list[str] = []
        self.y0 = y
        self.y = y
        self.capa = capa

    def add(self, html: str) -> None:
        self.itens.append(html)


class _Doc:
    def __init__(self, dados: dict):
        self.d = dados
        self.pgs: list[_Pg] = []

    def nova(self, aviso: str | None, y: float = Y_CONT, capa: bool = False) -> _Pg:
        pg = _Pg(aviso, y, capa)
        self.pgs.append(pg)
        return pg

    def continua(self, pg: _Pg, y: float = Y_CONT) -> _Pg:
        return self.nova(pg.aviso, y)


def _bloco(x: float, y: float, titulo: str | None, cols: list[dict], cab: tuple, linhas: list, classe: str,
           tit_x: float = 18.9) -> tuple:
    """Titulo (10 pt) + tabela na posicao (x, y). Devolve (html, altura)."""
    h = ""
    topo = 0.0
    if titulo:
        h += _t(tit_x, y + TIT_BASE, titulo, 10, 700)
        topo = GEO.get(classe, GEO_PADRAO)["tit_h"]
    h += f'<div class="a" style="left:{x:.2f}pt;top:{y + topo:.2f}pt">{_tabela(cols, cab[0], linhas, classe)}</div>'
    return h, topo + cab[1] + sum(hh for _, hh in linhas)


def _fluxo(doc: _Doc, pg: _Pg, titulo: str | None, cols: list[dict], cab: tuple, linhas: list, classe: str,
           x: float = X0, tit_x: float = 18.9, gap: float | None = None) -> _Pg:
    """Coloca o bloco na pagina; sem espaco, abre pagina nova repetindo titulo e cabecalho. Devolve a pagina atual."""
    geo = GEO.get(classe, GEO_PADRAO)
    gap = geo["gap"] if gap is None else gap
    i, n = 0, len(linhas)
    topo = (geo["tit_h"] if titulo else 0.0) + cab[1]
    while i < n:
        y = pg.y
        k, soma = 0, 0.0
        while i + k < n and y + topo + soma + linhas[i + k][1] <= Y_FUNDO:
            soma += linhas[i + k][1]
            k += 1
        if k < min(2, n - i) and y > pg.y0 + 0.01:
            pg = doc.continua(pg, geo["y_cont"])
            continue
        k = max(k, 1)
        html, alt = _bloco(x, y, titulo, cols, cab, linhas[i:i + k], classe, tit_x)
        pg.add(html)
        pg.y = y + alt + gap
        i += k
        if i < n:
            pg = doc.continua(pg, geo["y_cont"])
    return pg


def _titulo_pg(txt: str, x: float = 18.5, base: float = 71.5) -> str:
    return _t(x, base, txt, 13, 700)


# ------------------------------------------------------------------ graficos em SVG
def _rosca(cx: float, cy: float, r: float, ri: float, partes: list[tuple]) -> str:
    """Rosca a partir das 3 horas, sentido horario; partes = [(valor_absoluto, cor)]."""
    partes = [(v, c) for v, c in partes if v > 0]
    tot = sum(v for v, _ in partes)
    if tot <= 0:
        return ""
    if len(partes) == 1:
        cor = partes[0][1]
        return (f'<path fill="{cor}" fill-rule="evenodd" d="M{cx - r:.2f},{cy:.2f} a{r},{r} 0 1 0 {2 * r},0 '
                f'a{r},{r} 0 1 0 {-2 * r},0 Z M{cx - ri:.2f},{cy:.2f} a{ri},{ri} 0 1 0 {2 * ri},0 '
                f'a{ri},{ri} 0 1 0 {-2 * ri},0 Z"/>')
    das = [max(v / tot * 2 * math.pi, 0.035) for v, _ in partes]
    fator = 2 * math.pi / sum(das)
    das = [a * fator for a in das]
    a0 = 0.0
    out = []
    for da, (_, cor) in zip(das, partes):
        a1 = a0 + da
        p = [(cx + rr * math.cos(a), cy + rr * math.sin(a)) for rr, a in ((r, a0), (r, a1), (ri, a1), (ri, a0))]
        grande = 1 if da > math.pi else 0
        out.append(f'<path fill="{cor}" d="M{p[0][0]:.2f},{p[0][1]:.2f} A{r},{r} 0 {grande} 1 {p[1][0]:.2f},{p[1][1]:.2f} '
                   f'L{p[2][0]:.2f},{p[2][1]:.2f} A{ri},{ri} 0 {grande} 0 {p[3][0]:.2f},{p[3][1]:.2f} Z"/>')
        a0 = a1
    return "".join(out)


def _barras_mes(barras: list[dict], x_ini: float, x_fim: float, y0: float, topo: float, rot_y: float, largura: float,
                passo: float, fill: str, pt_val: float, pt_rot: float, val_dentro: bool, negrito_val: bool) -> str:
    """Barras com valor e rotulo. y0 = linha zero (eixo); topo = y da barra mais alta (positiva).

    val_dentro: valor centrado na barra (proventos); senao acima da barra (operacoes). Aceita negativos.
    """
    n = len(barras)
    if not n:
        return ""
    vals = [float(b.get("valor") or 0.0) for b in barras]
    vmax = max([v for v in vals if v > 0] or [0.0])
    vneg = max([-v for v in vals if v < 0] or [0.0])
    altura = y0 - topo
    esc = 0.0
    if vmax + vneg > 0:
        esc = altura / (vmax + vneg)
    # com negativos o eixo sobe para caber a parte de baixo
    y_zero = y0 - vneg * esc
    cx0 = (x_ini + x_fim) / 2 - (n - 1) / 2 * passo
    out = [f'<rect x="{x_ini:.2f}" y="{y0 - 0.1:.2f}" width="{x_fim - x_ini:.2f}" height="0.9" fill="#dcdcdc"/>']
    if vneg > 0:
        out.append(f'<rect x="{x_ini:.2f}" y="{y_zero - 0.25:.2f}" width="{x_fim - x_ini:.2f}" height="0.5" fill="#c9ced6"/>')
    peso = 700 if negrito_val else 400
    for i, (b, v) in enumerate(zip(barras, vals)):
        cx = cx0 + i * passo
        h = abs(v) * esc
        cor = fill if v >= 0 else "#e8cdc6"
        if v >= 0:
            ytopo = y_zero - h
        else:
            ytopo = y_zero
        if h > 0.05:
            out.append(f'<rect x="{cx - largura / 2:.2f}" y="{ytopo:.2f}" width="{largura:.2f}" height="{max(h, 0.6):.2f}" fill="{cor}"/>')
        txt = brl(v)
        corv = NEG if v < 0 else None
        if val_dentro:
            centro = ytopo + h / 2
            if h < pt_val * 1.5:
                # barra baixa: a etiqueta fica sobre o eixo, com fundo da cor da barra
                centro = y0 - pt_val * 0.75
                if v > 0:
                    out.append(f'<rect x="{cx - largura / 2:.2f}" y="{centro - pt_val * 0.75:.2f}" width="{largura:.2f}" '
                               f'height="{pt_val * 1.5:.2f}" fill="{cor}"/>')
            out.append(_s(cx, centro + pt_val * 0.34, txt, pt_val, peso, corv, "middle"))
        else:
            # valor sempre em cima da barra; o negativo desce do eixo e a etiqueta fica acima da linha zero
            out.append(_s(cx, (ytopo if v >= 0 else y_zero) - 3.4, txt, pt_val, peso, corv, "middle"))
        out.append(_s(cx, rot_y, str(b.get("rotulo", "")), pt_rot, 700, None, "middle"))
    return "".join(out)


# ------------------------------------------------------------------ capa
def _pg_capa(doc: _Doc) -> None:
    pg = doc.nova(None, 0.0, capa=True)
    comp = doc.d.get("competencia", "")
    degraus = [(96.3, 141.5, 573.5), (288.3, 151.6, 480.4), (490.4, 152.6, 348.3), (702.0, 151.5, 143.7)]
    svg = "".join(f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{PAG_H - y + 40:.2f}" rx="10.5" ry="10.5" '
                  f'fill="none" stroke="#818caa" stroke-width="1.9"/>' for x, w, y in degraus)
    pg.add(_ov(svg))
    pg.add(_t(77.0, 353.3, f'Relatório Mensal <span style="color:#549bed">{e(comp)}</span>', 25, 700,
              cor="#132c6b", raw=True))
    pg.add(_t(77.0, 386.4, "OPERAÇÕES DE RENDA VARIÁVEL", 15, 400, cor="#132c6b"))


# ------------------------------------------------------------------ posicao de carteira
COLS_POS = [18.9, 117.9, 163.6, 253.3, 298.1, 367.3, 461.5, 516.9, 594.2, 674.7, 752.6]
COLS_POS_VENC = [18.9, 112.8, 160.6, 223.2, 277.4, 317.8, 381.7, 466.1, 523.5, 588.6, 668.7, 753.7]
TIT_POS = [
    ("acoes", "Posição de Ações (Compradas)"),
    ("fii", "Posição de Fundos Imobiliários ou nas Cadeias Produtivas AgroIndustriais - FIAGRO (Compradas)"),
    ("opcoes_vendidas", "Posição de Opções Vendidas"),
    ("opcoes_compradas", "Posição de Opções Compradas"),
    ("termos", "Posição de Termos"),
    ("btc", "Posição de Ações BTC (Vendidas)"),
    ("fii_vendidas", "Posição de FII (Vendidas)"),
]


def _cartoes_posicao(d: dict) -> str:
    resumo = d.get("resumo_posicao") or []
    tot = d.get("total_posicao") or {}
    html = _card(16.6, 77.1, 402.5, 272.0) + _card(413.9, 76.0, 824.5, 272.0)
    svg = []
    cx, cy, r, ri = 139.7, 174.4, 87.1, 34.5
    partes, leg = [], []
    for i, linha in enumerate(resumo):
        v = abs(float(linha.get("investido") or 0.0))
        partes.append((v, ROSCA[i % len(ROSCA)]))
        if v > 0:
            leg.append((linha.get("mercado", ""), v, ROSCA[i % len(ROSCA)]))
    svg.append(_rosca(cx, cy, r, ri, partes))
    soma = sum(v for _, v, _ in leg) or 1.0
    if leg:
        bloco = 12.0 + len(leg) * 10.0
        t0 = cy - bloco / 2 + 6.7
        svg.append(_s(267.3, t0, "Posição", 8, 700))
        for j, (nome, v, cor) in enumerate(leg):
            yb = t0 + 12.8 + j * 10.0
            svg.append(f'<rect x="267.3" y="{yb - 6.6:.2f}" width="15.3" height="7.6" fill="{cor}"/>')
            svg.append(_s(287.5, yb, f"{num(v / soma * 100)}% - {nome}", 8, 400, "#023463"))
    else:
        svg.append(_s((16.6 + 402.5) / 2, cy + 3.0, "Sem posição em carteira nesta data", 9, 700, anc="middle"))
    # resumo da previsao de resultados
    svg.append(_s(433.7, 101.7, f"Previsão de Resultados em {d.get('data_posicao', '')}", 8, 700))
    xs = [433.7, 534.7, 635.8, 736.7]
    for x, t in zip(xs, ("Mercado", "Valor Investido", "Valor Mercado", "L & P")):
        svg.append(_s(x, 119.7, t, 8, 700))
    pitch = 16.25
    for j, linha in enumerate(resumo):
        yb = 136.0 + j * pitch
        svg.append(_s(xs[0], yb, linha.get("mercado", ""), 8))
        for x, k in zip(xs[1:], ("investido", "valor", "lp")):
            svg.append(_sv(x, yb, linha.get(k)))
    yt = 136.0 + len(resumo) * pitch
    svg.append(_s(xs[0], yt, "Total L & P", 8, 700))
    for x, k in zip(xs[1:], ("investido", "valor", "lp")):
        svg.append(_sv(x, yt, tot.get(k), 8, 700))
    return html + _ov("".join(svg))


def _linhas_posicao(rows: list[dict], cols: list[dict], com_venc: bool) -> list:
    out = []
    for r in rows:
        vals = [r.get("corretora", ""), r.get("ticker", ""), r.get("ativo", "")]
        if com_venc:
            vals.append(dat(r.get("vencimento")))
        vals += [qtd(r.get("qtd")), brl(r.get("pm")), _v(r.get("investido")), pct(r.get("pct")), brl(r.get("preco")),
                 _v(r.get("valor")), (pct(r.get("ganho_pct")), "neg" if _neg(r.get("ganho_pct")) else ""),
                 _v(r.get("lp"))]
        out.append(_linha(cols, vals))
    return out


def _pg_posicao(doc: _Doc) -> None:
    d = doc.d
    pg = doc.nova(AVISO_POSICAO, 314.9)
    pg.add(_titulo_pg("Posição de Carteira", 18.9, 70.7))
    pg.add(_cartoes_posicao(d))
    pos = d.get("posicoes") or {}
    for chave, titulo in TIT_POS:
        rows = pos.get(chave) or []
        if not rows:
            continue
        com_venc = any(r.get("vencimento") for r in rows)
        xs = COLS_POS_VENC if com_venc else COLS_POS
        cols = _cols_x(xs, quebra=(0, 2))
        qt = "Qtd." if chave in ("fii", "fii_vendidas") else "Qtd"
        cabecalho = ["Corretora", "Ticker", "Ativo"] + (["Vencimento"] if com_venc else []) + [
            qt, "Preço Médio", "Valor Investido", "% Carteira", "Preço Mercado", "Valor Mercado", "Ganho X Ação %",
            "L & P"]
        tit = f"{titulo}: {brl(_soma(rows, 'investido'))}"
        pg = _fluxo(doc, pg, tit, cols, _cab(cols, cabecalho), _linhas_posicao(rows, cols, com_venc), "p")


# ------------------------------------------------------------------ operacoes finalizadas no mes
COLS_OPS = [18.9, 97.3, 152.0, 250.6, 301.4, 325.0, 361.0, 405.3, 477.6, 527.8, 548.4, 585.5, 629.8, 702.1, 764.5]
VAOS_OPS = [(0, 3, "Ações", X0, 248.5), (3, 8, "Data Liquidação", 248.5, 475.5), (8, 13, "Data de Estoque", 475.5, 700.0),
            (13, 15, "Resultados", 700.0, X1)]


def _cab_ops(cols: list[dict]) -> tuple:
    ths = "".join(f'<th colspan="{b - a}">{e(t)}</th>' for a, b, t, _, _ in VAOS_OPS)
    nomes = ["Corretora", "Ticker", "Ativo", "Data", "C/V", "Qtd", "Preço", "Total c/ Taxas", "Data", "C/V", "Qtd",
             "Preço", "Total c/ Taxas", "Comum", "Day Trade"]
    ths2 = "".join(f'<th style="{"padding-left:%.2fpt;" % c["pl"] if c.get("pl") else ""}">{e(t)}</th>'
                   for c, t in zip(cols, nomes))
    return (f'<thead><tr class="g">{ths}</tr><tr class="h">{ths2}</tr></thead>', 34.02)


def _cartoes_operacoes(d: dict) -> str:
    ops = d.get("operacoes") or {}
    html = _card(16.6, 77.9, 389.6, 231.5) + _card(401.5, 77.9, 822.0, 230.7)
    svg = []
    barras = ops.get("barras") or []
    n = len(barras)
    if n:
        passo = min(69.5, (376.2 - 29.5) / n)
        svg.append(_barras_mes(barras, 29.5, 376.2, 212.6, 95.8, 220.8, 54.2, passo, CAB, 7, 7, False, True))
    # quadro de resultados
    svg.append(_s(420.3, 95.7, "Resultados", 8, 700))
    svg.append(_s(722.0, 96.7, _mes_extenso(d.get("competencia", "")), 8, 700))
    xs = [420.3, 502.9, 585.4, 678.5, 761.0]
    for x, t in zip(xs, ("Operações", "Resultado Mês", "Prejuízo à Compensar", "Base Tributável", "Imposto")):
        svg.append(_s(x, 117.2, t, 8, 700))
    quadro = ops.get("quadro") or []
    pitch = 20.5 if len(quadro) <= 5 else (219.8 - 137.8) / max(len(quadro) - 1, 1)
    for j, q in enumerate(quadro):
        yb = 137.8 + j * pitch
        total = str(q.get("tipo", "")).strip().lower() == "total"
        peso = 700 if total else 400
        svg.append(_s(xs[0], yb, "Total L & P" if total else q.get("tipo", ""), 8, peso))
        svg.append(_sv(xs[1], yb, q.get("resultado"), 8, peso))
        svg.append(_sv(xs[2], yb, None if q.get("prejuizo") is None else -abs(float(q["prejuizo"])), 8, peso))
        svg.append(_sv(xs[3], yb, q.get("base"), 8, peso))
        svg.append(_sv(xs[4], yb, q.get("imposto"), 8, peso))
    return html + _ov("".join(svg))


def _linhas_ops(rows: list[dict], cols: list[dict]) -> list:
    out = []
    for r in rows:
        liq, est = r.get("liq") or {}, r.get("estoque") or {}
        comum, day = r.get("comum"), r.get("daytrade")
        vals = [r.get("corretora", ""), r.get("ticker", ""), r.get("ativo", ""),
                dat(liq.get("data")), liq.get("cv") or "-", qtd(liq.get("qtd")), brl(liq.get("preco")), brl(liq.get("total")),
                dat(est.get("data")), est.get("cv") or "-", qtd(est.get("qtd")), brl(est.get("preco")), brl(est.get("total")),
                _v(comum) if comum is not None else "-", _v(day) if day is not None else "-"]
        out.append(_linha(cols, vals))
    return out


def _pg_operacoes(doc: _Doc) -> None:
    d = doc.d
    ops = d.get("operacoes") or {}
    pg = doc.nova(AVISO_OPERACOES, 348.9)
    pg.add(_titulo_pg("Operações Finalizadas no Mês"))
    pg.add(_cartoes_operacoes(d))
    grupos = ops.get("grupos") or []
    if not grupos:
        pg.add(_t(18.9, 275.0, "Sem operações finalizadas no mês.", 10, 700))
    cols = _cols_x(COLS_OPS, quebra=(0, 2))
    for g in grupos:
        linhas = _linhas_ops(g.get("linhas") or [], cols)
        tit = (f"{g.get('titulo', '')} Operações Comum: {brl(g.get('comum'))} / "
               f"Operações Daytrade: {brl(g.get('daytrade'))}")
        if not linhas:
            continue
        pg = _fluxo(doc, pg, tit, cols, _cab_ops(cols), linhas, "o")


# ------------------------------------------------------------------ extrato consolidado
H_EXT = 20.51             # cabecalho e linhas do extrato


def _pg_extrato(doc: _Doc) -> None:
    d = doc.d
    ext = d.get("extrato")
    if not ext:
        return
    exts = ext if isinstance(ext, list) else [ext]
    pg = doc.nova(AVISO_EXTRATO, 96.18)
    pg.add(_titulo_pg("Extrato Consolidado"))
    cols = [{"w": 447.53, "a": "l", "pl": 15.0, "pr": 0.0}, {"w": 120.16, "a": "r", "pl": 0.0, "pr": 15.0},
            {"w": 120.15, "a": "r", "pl": 0.0, "pr": 15.0}, {"w": 120.16, "a": "r", "pl": 0.0, "pr": 15.0}]
    cab = _cab(cols, ["Lançamentos", "Débito", "Crédito", "Saldo"], H_EXT)
    for ex in exts:
        linhas = []
        for r in ex.get("linhas") or []:
            linhas.append(_linha_fixa(cols, [str(r.get("lancamento", "")), _v(r.get("debito")), _v(r.get("credito")),
                                             _v(r.get("saldo"))], H_EXT))
        tot = ex.get("totais")
        if tot:
            linhas.append(_linha_fixa(cols, ["Totais", _v(tot.get("debito")), _v(tot.get("credito")),
                                             _v(tot.get("saldo"))], H_EXT, "tot"))
        if not linhas:
            linhas.append(_linha_fixa(cols, ["Sem lançamentos no período", "", "", ""], H_EXT))
        # titulo do bloco: corretora e periodo (periodo alinhado a direita)
        i, n = 0, len(linhas)
        while i < n:
            y = pg.y
            topo = 20.2 + H_EXT
            k, soma = 0, 0.0
            while i + k < n and y + topo + soma + linhas[i + k][1] <= Y_FUNDO:
                soma += linhas[i + k][1]
                k += 1
            if k < min(2, n - i) and y > pg.y0 + 0.01:
                pg = doc.continua(pg)
                continue
            k = max(k, 1)
            pg.add(_t(18.5, y + 14.4, str(ex.get("corretora", "")), 10, 700)
                   + _t(809.3, y + 12.4, str(ex.get("periodo", "")), 10, 400, anc="d"))
            pg.add(f'<div class="a" style="left:16.5pt;top:{y + 20.2:.2f}pt">'
                   f'{_tabela(cols, cab[0], linhas[i:i + k], "x")}</div>')
            pg.y = y + topo + soma + GAP
            i += k
            if i < n:
                pg = doc.continua(pg)


# ------------------------------------------------------------------ proventos
COLS_PROV = [23.3, 113.3, 183.0, 252.7, 322.4, 424.1, 527.2, 643.0]
H_Q = 20.51               # cabecalho e linhas das tabelas de proventos
H_QT = 21.26              # linha de total
Y_Q = 83.12               # topo da tabela de proventos
X_Q = 21.23               # borda esquerda da tabela de proventos
X_Q1 = 711.91             # borda direita


def _bloco_grafico(pg: _Pg, dy: float, titulo: str, rotulos: list, barras: list[dict]) -> None:
    """Titulo de 13 pt + cartao com as barras dos 12 meses. `rotulos` = [(x, texto, ancora, ajuste_y)] em 10 pt negrito."""
    pg.add(_t(23.3, 206.4 + dy, titulo, 13, 700))
    pg.add(_card(21.0, 215.7 + dy, 822.2, 417.8 + dy))
    svg = [_s(x, 242.8 + dy + aj, t, 10, 700, None, anc) for x, t, anc, aj in rotulos]
    svg.append(_barras_mes(barras, 49.5, 793.0, 397.7 + dy, 282.6 + dy, 407.8 + dy, 44.8, 57.2, SUAVE, 8, 10, True,
                           False))
    pg.add(_ov("".join(svg)))


def _linhas_prov(rows: list[dict], cols: list[dict]) -> list:
    out = []
    for r in rows:
        bon = r.get("bonificacoes")
        out.append(_linha_fixa(cols, [r.get("corretora", ""), brl(r.get("dividendos")), brl(r.get("jcp")),
                                      brl(r.get("rendimentos")), "-" if bon is None else brl(bon),
                                      brl(r.get("reembolso_btc")), brl(r.get("rendimentos_btc")), brl(r.get("total"))],
                               H_Q))
    return out


def _lista_q(doc: _Doc, pg: _Pg, titulo: str, cols: list[dict], cab: tuple, linhas: list) -> _Pg:
    """Lista longa (uma pagina nova, quebra repetindo titulo e cabecalho) no estilo das tabelas de proventos."""
    return _fluxo(doc, doc.continua(pg), titulo, cols, cab, linhas, "q l", x=X_Q, tit_x=23.3)


def _pg_proventos(doc: _Doc) -> None:
    d = doc.d
    pv = d.get("proventos")
    if not pv:
        return
    pg = doc.nova(AVISO_PROVENTOS, Y_Q)
    pg.add(_titulo_pg("Proventos Recebidos no Mês", 23.3, 70.5))
    cols = _cols_x(COLS_PROV, X_Q1, X_Q)
    tit = ["Corretora", "Dividendos", "JCP", "Rendimentos", "Bonificações em ações", "Reembolso BTC Doador",
           "Rendimentos BTC Doador", "Total"]
    linhas = _linhas_prov(pv.get("por_corretora") or [], cols)
    tot = pv.get("total")
    if tot:
        t = dict(tot, corretora="TOTAL")
        l, _ = _linhas_prov([t], cols)[0]
        linhas.append((l.replace("<tr>", '<tr class="tot">', 1), H_QT))
    if not linhas:
        linhas = [_linha_fixa(cols, ["Sem dados para exibir.", "", "", "", "", "", "", ""], H_Q)]
    cab = _cab(cols, tit, H_Q)
    pg = _fluxo(doc, pg, None, cols, cab, linhas, "q", x=X_Q, gap=0.0)
    # grafico dos ultimos 12 meses (desce se a tabela passar da posicao do modelo)
    dy = max(0.0, pg.y + 22.0 - 196.0)
    if 417.8 + dy > Y_FUNDO:
        pg = doc.continua(pg)
        dy = 60.0 - 196.0
    _bloco_grafico(pg, dy, "Total de Proventos",
                   [(41.3, "Recebidos nos Últimos 12 Meses", "start", 0.0),
                    (769.3, f"Total Período {brl(pv.get('total_12m'))}", "end", 1.0)], pv.get("meses_12") or [])
    det = pv.get("detalhe") or []
    if det:
        cols_d = _cols_x([23.3, 150.0, 300.0, 460.0], X1, X_Q)
        cab_d = _cab(cols_d, ["Data", "Ticker", "Tipo", "Valor"], H_Q)
        linhas_d = [_linha_fixa(cols_d, [dat(r.get("data")), r.get("ticker", ""), r.get("tipo", ""), _v(r.get("valor"))],
                                H_Q) for r in det]
        _lista_q(doc, pg, "Detalhe dos Proventos Recebidos", cols_d, cab_d, linhas_d)


MAX_LINHAS_PROV = 8       # linhas que as tabelas de provisionados mostram na propria pagina


def _corta(rows: list, n: int) -> tuple[list, int]:
    """(linhas mostradas, quantas ficaram de fora); se passar de `n`, a ultima vaga vira o aviso '+ N'."""
    if len(rows) <= n:
        return list(rows), 0
    return list(rows[:n - 1]), len(rows) - (n - 1)


def _pg_provisionados(doc: _Doc) -> None:
    d = doc.d
    pv = d.get("provisionados")
    if not pv:
        return
    pg = doc.nova(AVISO_PROVISIONADOS, Y_Q)
    pg.add(_t(23.3, 70.5, "Proventos Provisionados", 13, 700))
    pg.add(_t(441.6, 70.5, "Próximos Recebimentos", 13, 700))
    # tabela por corretora (esquerda)
    cols_a = _cols_x([23.3, 117.7, 195.7, 273.7, 351.7], 420.56, X_Q)
    cab_a = _cab(cols_a, ["Corretora", "Dividendos", "JCP", "Rendimentos", "Total"], H_Q)
    corr = pv.get("por_corretora") or []
    mostra_a, fora_a = _corta(corr, MAX_LINHAS_PROV)
    la = [_linha_fixa(cols_a, [r.get("corretora", ""), brl(r.get("dividendos")), brl(r.get("jcp")),
                               brl(r.get("rendimentos")), brl(r.get("total"))], H_Q) for r in mostra_a]
    if fora_a:
        la.append(_linha_fixa(cols_a, [f"+ {fora_a} corretoras", "", "", "", ""], H_Q))
    if not la:
        la.append(_linha_fixa(cols_a, ["Sem dados para exibir.", "R$ 0,00", "R$ 0,00", "R$ 0,00", "R$ 0,00"], H_Q))
    tot_a = [_soma(corr, k) for k in ("dividendos", "jcp", "rendimentos", "total")]
    la.append(_linha_fixa(cols_a, ["TOTAL"] + [brl(x) for x in tot_a], H_QT, "tot"))
    pg.add(f'<div class="a" style="left:{X_Q}pt;top:{Y_Q}pt">{_tabela(cols_a, cab_a[0], la, "q")}</div>')
    # tabela de proximos recebimentos (direita): cabe a lista curta; a completa vai numa pagina propria
    linhas = pv.get("linhas") or []
    cols_b = _cols_x([441.6, 531.6, 621.6, 722.1], 819.05, 439.58)
    cab_b = _cab(cols_b, ["Ticker", "Previsão Pagamento", "Corretora", "Valor"], H_Q)
    mostra_b, fora_b = _corta(linhas, MAX_LINHAS_PROV)
    lb = [_linha_fixa(cols_b, [r.get("ticker", ""), dat(r.get("previsao")), r.get("corretora", ""), brl(r.get("valor"))],
                      H_Q) for r in mostra_b]
    if fora_b:
        lb.append(_linha_fixa(cols_b, [f"+ {fora_b} na lista completa (próxima página)", "", "", ""], H_Q))
    if not lb:
        lb.append(_linha_fixa(cols_b, ["Sem dados para exibir.", "-", "-", "R$ 0,00"], H_Q))
    total_b = pv.get("total")
    lb.append(_linha_fixa(cols_b, ["TOTAL", "", "", brl(total_b if total_b is not None else _soma(linhas, "valor"))],
                          H_QT, "tot"))
    pg.add(f'<div class="a" style="left:439.58pt;top:{Y_Q}pt">{_tabela(cols_b, cab_b[0], lb, "q")}</div>')
    # grafico dos proximos 12 meses (desce conforme o tamanho das tabelas)
    fim_tab = Y_Q + max(sum(h for _, h in la), sum(h for _, h in lb)) + H_Q
    dy = max(0.0, fim_tab + 22.0 - 196.0)
    _bloco_grafico(pg, dy, "Total de Proventos Provisionados",
                   [(41.3, "Próximos 12 Meses", "start", 0.0),
                    (151.8, f"Total: {brl(pv.get('total_12m'))}", "start", 0.0),
                    (546.0, "Sem data prevista", "start", 0.0),
                    (641.9, f"Total: {brl(pv.get('sem_data_total'))}", "start", 0.0)], pv.get("proximos_12m") or [])
    if fora_b:
        cols_c = _cols_x([23.3, 190.0, 380.0, 640.0], X1, X_Q)
        cab_c = _cab(cols_c, ["Ticker", "Previsão Pagamento", "Corretora", "Valor"], H_Q)
        lc = [_linha_fixa(cols_c, [r.get("ticker", ""), dat(r.get("previsao")), r.get("corretora", ""), _v(r.get("valor"))],
                          H_Q) for r in linhas]
        lc.append(_linha_fixa(cols_c, ["TOTAL", "", "", _v(total_b if total_b is not None else _soma(linhas, "valor"))],
                              H_QT, "tot"))
        _lista_q(doc, pg, "Próximos Recebimentos", cols_c, cab_c, lc)


# ------------------------------------------------------------------ resultados anuais
# rotulos curtos que o motor pode mandar -> rotulo do modelo (chave sem acento e em caixa alta)
ROTULOS_ANUAIS = {"DAYTRADE": "OP. DAYTRADE", "FII": "OP. F.I.I FIAGRO", "BTC DOADOR": "PROVENTOS BTC DOADOR",
                  "SOMA": "SOMA DOS RESULTADOS", "LIQUIDO": "LÍQUIDO MÊS"}


def _pg_anual(doc: _Doc) -> None:
    d = doc.d
    an = d.get("anual")
    if not an:
        return
    pg = doc.nova(an.get("nota") or AVISO_ANUAL, 80.0)
    pg.add(_titulo_pg(f"Resultados Anuais {an.get('ano', '')}"))
    meses = an.get("meses") or ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]
    meses = [str(m).upper() for m in meses]                      # o modelo escreve os meses em caixa alta
    xs = [18.9] + [135.1 + 53.27 * i for i in range(len(meses))] + [774.4]
    cols = _cols_x(xs, fim=828.6)
    cab = _cab(cols, ["Resultados"] + list(meses) + ["Total"], 22.26)
    linhas = []
    rows = an.get("linhas") or []
    for idx, r in enumerate(rows):
        rot = str(r.get("rotulo", ""))
        rot = ROTULOS_ANUAIS.get(_sem_acento(rot).upper().strip(), rot)      # nomes curtos viram os do modelo
        destaque = bool(r.get("destaque"))
        filete = r.get("filete", destaque or rot.upper().startswith("SOMA"))
        negrito = r.get("negrito", destaque and not rot.upper().startswith("SOMA"))     # no modelo so o liquido e negrito
        # como no modelo, a cor e da linha (IMPOSTOS e DESPESAS inteiras em marrom) e nao do sinal do numero
        marrom = r.get("marrom", _sem_acento(rot).upper().startswith(("IMPOSTO", "DESPESA")))
        cor = "neg" if marrom else ""
        vals = [(rot, "l")] + [(brl(x), cor) if x is not None else "-" for x in (r.get("valores") or [None] * len(meses))]
        vals += [(brl(r.get("total")), cor)]
        cls = ("f " if filete else "") + ("b " if negrito else "") + ("z " if (idx == len(rows) - 1 and destaque) else "")
        linhas.append(_linha_fixa(cols, vals, 17.0, cls.strip()))
    html = (f'<div class="a" style="left:{X0}pt;top:81.22pt">{_tabela(cols, cab[0], linhas, "n")}</div>')
    pg.add(html)


# ------------------------------------------------------------------ situacao fiscal
Y_SIT = 90.9              # topo do 1o bloco (subtitulo); a tabela comeca 14,28 pt abaixo
X_SIT_E, X_SIT_E1 = 17.46, 421.63      # coluna da esquerda: DARFs e prejuizos a compensar
X_SIT_D, X_SIT_D1 = 439.58, X1         # coluna da direita: alertas e conferencia
H_SC = 17.01              # cabecalho das tabelas da situacao fiscal
H_SL = 18.43              # linha de corpo
PASSO_S = 8.6             # entrelinha do texto de 7 pt quando a frase quebra


class _DocSombra:
    """Estoque de paginas da coluna da direita: so guarda os itens, que _pg_situacao junta as paginas da esquerda."""

    def __init__(self) -> None:
        self.pgs: list[_Pg] = []

    def continua(self, pg: _Pg, y: float = Y_CONT) -> _Pg:
        novo = _Pg(pg.aviso, y)
        self.pgs.append(novo)
        return novo


def _linha_s(cols: list[dict], vals: list, max_linhas: int = 4) -> tuple:
    """Linha das tabelas da situacao fiscal (texto de 7 pt); frase longa quebra em ate `max_linhas` e a linha cresce."""
    n = 1
    cels = []
    for col, v in zip(cols, vals):
        txt, c = v if isinstance(v, tuple) else (v, "")
        if col.get("q") and isinstance(txt, str):
            cap = col["w"] - col.get("pl", 0.0) - col.get("pr", 0.0) - 1.0
            ls = _quebra(txt, cap, 7.0, False, max_linhas)
            n = max(n, len(ls))
            txt = ls if len(ls) > 1 else txt
        cels.append((txt, c))
    h = H_SL + (n - 1) * PASSO_S
    st = f' style="height:{h:.2f}pt"' if n > 1 else ""
    return (f"<tr{st}>" + "".join(_td(c, v) for c, v in zip(cols, cels)) + "</tr>", h)


def _linha_vazia(cols: list[dict], txt: str) -> tuple:
    """Linha com uma frase so, ocupando a largura toda (tabela sem itens)."""
    pl = cols[0].get("pl", 0.0)
    return (f'<tr><td colspan="{len(cols)}" style="padding-left:{pl:.2f}pt">{e(txt)}</td></tr>', H_SL)


def _cor_situacao(txt) -> str:
    """Situacao do DARF em marrom quando e problema (vencido, em atraso, sem pagamento)."""
    t = _sem_acento(txt or "").lower()
    return "neg" if t.startswith(("venc", "atras", "em atras", "sem pagamento", "nao pago", "pendente")) else ""


def _pg_situacao(doc: _Doc) -> None:
    """Situacao fiscal: DARFs e prejuizos a compensar na coluna da esquerda, alertas e conferencia na da direita."""
    sit = doc.d.get("situacao")
    if not sit:
        return
    i0 = len(doc.pgs)
    pg_e = doc.nova(AVISO_SITUACAO, Y_SIT)
    pg_e.add(_titulo_pg("Situação Fiscal", base=80.2))
    sombra = _DocSombra()
    pg_d = _Pg(AVISO_SITUACAO, Y_SIT)
    sombra.pgs.append(pg_d)
    # coluna da esquerda
    cols_d = _cols_x([19.46, 103.0, 163.0, 243.0, 323.0], X_SIT_E1, X_SIT_E, quebra=(4,))
    cab_d = _cab(cols_d, ["Período de apuração", "Código", "Vencimento", "Valor", "Situação"], H_SC)
    ld = [_linha_s(cols_d, [r.get("periodo", ""), r.get("codigo", ""), dat(r.get("vencimento")), _v(r.get("valor")),
                            (r.get("situacao", ""), _cor_situacao(r.get("situacao")))]) for r in sit.get("darfs") or []]
    ld = ld or [_linha_vazia(cols_d, "Nenhum DARF a pagar neste período.")]
    pg_e = _fluxo(doc, pg_e, "DARFs", cols_d, cab_d, ld, "s", x=X_SIT_E, tit_x=19.4)
    cols_p = _cols_x([19.46, 200.0], X_SIT_E1, X_SIT_E)
    cab_p = _cab(cols_p, ["Tipo de operação", "Prejuízo a compensar"], H_SC)
    lp = [_linha_s(cols_p, [r.get("tipo", ""), _perda(r.get("valor"))]) for r in sit.get("prejuizos") or []]
    lp = lp or [_linha_vazia(cols_p, "Sem prejuízo acumulado a compensar.")]
    _fluxo(doc, pg_e, "Prejuízos a Compensar", cols_p, cab_p, lp, "s l", x=X_SIT_E, tit_x=19.4)
    # coluna da direita
    cols_t = _cols_x([X_SIT_D + 2.0], X_SIT_D1, X_SIT_D, quebra=(0,))
    for chave, titulo, cab_txt, vazio, classe in (
            ("alertas", "Alertas", "Aviso", "Nenhum alerta neste mês.", "s"),
            ("conferencia", "Conferência", "Verificação", "Nenhuma conferência registrada.", "s l")):
        if chave not in sit:
            continue
        # alerta e frase de contador: nao se corta (ate 12 linhas), a tabela passa para a pagina seguinte se precisar
        lt = [_linha_s(cols_t, [str(x)], 12) for x in sit.get(chave) or []] or [_linha_vazia(cols_t, vazio)]
        pg_d = _fluxo(sombra, pg_d, titulo, cols_t, _cab(cols_t, [cab_txt], H_SC), lt, classe, x=X_SIT_D,
                      tit_x=X_SIT_D + 1.9)
    # junta as paginas da direita as da esquerda (cria a pagina que faltar)
    for k, ps in enumerate(sombra.pgs):
        if i0 + k >= len(doc.pgs):
            doc.continua(doc.pgs[-1])
        doc.pgs[i0 + k].itens.extend(ps.itens)


# ------------------------------------------------------------------ API publica
def html_relatorio(dados: dict) -> str:
    """HTML do relatorio mensal (uma <section> por pagina, A4 paisagem).

    Formato de `dados` (o motor entrega isto). Capa, posicao e operacoes sempre saem (sem dados, ficam com os quadros
    vazios); extrato, proventos, provisionados, anual e situacao so saem se a chave vier preenchida:

        titular {nome, documento}; competencia "10/2026"; gerado_em "02/11/2026"; data_posicao "31/10/2026"; corretora
        resumo_posicao [{mercado, investido, valor, lp}] na ordem Ações, FII, Opções Vendidas, Termos, Opções Compradas,
            Ações BTC (Vendidas), FII (Vendidas); total_posicao {investido, valor, lp}
        posicoes {acoes, fii, opcoes_vendidas, opcoes_compradas, termos, btc, fii_vendidas}: listas de
            {corretora, ticker, ativo, qtd, pm, investido, pct, preco, valor, ganho_pct, lp} (+ vencimento nas opcoes e
            nos termos). pct e ganho_pct em pontos percentuais (12.34 vira "12,34 %"); None vira "-".
        operacoes {quadro [{tipo, resultado, prejuizo, base, imposto}], barras [{rotulo, valor}],
            grupos [{titulo, comum, daytrade, linhas [{corretora, ticker, ativo, liq{data, cv, qtd, preco, total},
            estoque{...}, comum, daytrade}]}]}. "prejuizo" aparece sempre negativo (e uma perda), qualquer que seja o sinal.
        extrato {periodo, corretora, linhas [{lancamento, debito, credito, saldo}], totais {debito, credito, saldo}}
        proventos {por_corretora [{corretora, dividendos, jcp, rendimentos, bonificacoes, reembolso_btc,
            rendimentos_btc, total}], total {...}, meses_12 [{rotulo, valor}], total_12m, detalhe [{data, ticker, tipo, valor}]}
        provisionados {proximos_12m [{rotulo, valor}], total_12m, sem_data_total, por_corretora [...], linhas [{ticker,
            previsao, corretora, valor}], total}
        anual {ano, meses [12 rotulos], linhas [{rotulo, valores [12], total, destaque}], nota}
        situacao {darfs [{periodo, codigo, vencimento, valor, situacao}], prejuizos [{tipo, valor}], alertas [str],
            conferencia [str]}

    Campos opcionais que esta camada acrescenta ao formato:
      - posicoes.fii_vendidas: lista no mesmo formato (secao "Posição de FII (Vendidas)").
      - extrato pode ser uma LISTA de extratos (um por corretora, cada um com periodo, corretora, linhas e totais).
      - proventos.detalhe: se vier preenchida, gera uma tabela "Detalhe dos Proventos Recebidos" depois do grafico.
      - provisionados.linhas: ate 8 itens cabem na propria pagina; com mais, a pagina mostra os 7 primeiros e "+ N" e a
        lista completa vai numa pagina "Próximos Recebimentos".
      - anual.meses sai em caixa alta ("Jan" vira "JAN"); rotulos curtos viram os do modelo (DAYTRADE, FII, BTC DOADOR,
        SOMA e LÍQUIDO viram OP. DAYTRADE, OP. F.I.I FIAGRO, PROVENTOS BTC DOADOR, SOMA DOS RESULTADOS e LÍQUIDO MÊS).
      - anual.linhas[*].filete (filete acima da linha), .negrito (texto em negrito) e .marrom (todos os valores da linha
        em marrom): por padrao "destaque" liga filete e negrito (a linha SOMA leva so o filete, como no modelo) e
        IMPOSTOS e DESPESAS saem em marrom (no modelo a cor e da linha, nao do sinal do numero). anual.nota, se vier, e
        o texto do aviso da pagina. Valor None vira "-"; para mostrar R$ 0,00 nos meses sem dado, mande 0.0.
      - situacao.alertas e situacao.conferencia: listas de frases (quadros na coluna da direita, ate 12 linhas por
        frase, sem cortar); lista vazia vira "Nenhum alerta neste mês."; chave ausente, o quadro nao sai. Tabela longa
        passa para a pagina seguinte repetindo o titulo e o cabecalho. Situacao de DARF que comeca com "Vencido", "Em
        atraso", "Sem pagamento", "Não pago" ou "Pendente" sai em marrom.
      - Chaves que esta camada nao conhece (por exemplo "parcial") sao ignoradas.
    """
    doc = _Doc(dados)
    _pg_capa(doc)
    _pg_posicao(doc)
    _pg_operacoes(doc)
    _pg_extrato(doc)
    _pg_proventos(doc)
    _pg_provisionados(doc)
    _pg_anual(doc)
    _pg_situacao(doc)
    paginas = []
    for pg in doc.pgs:
        corpo = _faixa(dados) + "".join(pg.itens) + (_aviso(pg.aviso) if pg.aviso else "")
        paginas.append(f'<section class="pg">{corpo}</section>')
    titulo = f"Relatório Mensal {dados.get('competencia', '')}"
    return (f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>{e(titulo)}</title>'
            f"<style>{CSS}</style></head><body>{''.join(paginas)}</body></html>")


def imprimir_pdf(arq_html: Path, arq_pdf: Path) -> Path:
    """HTML -> PDF pelo Chrome headless, sem cabecalho nem rodape do navegador."""
    if not CHROME.exists():
        raise FileNotFoundError(f"Chrome nao encontrado em {CHROME}: o PDF precisa dele (o HTML foi gravado em {arq_html})")
    with tempfile.TemporaryDirectory() as perfil:
        cmd = [str(CHROME), "--headless=new", "--disable-gpu", "--no-sandbox", f"--user-data-dir={perfil}",
               "--no-pdf-header-footer", "--run-all-compositor-stages-before-draw", f"--print-to-pdf={arq_pdf}",
               Path(arq_html).as_uri()]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if not Path(arq_pdf).exists() or Path(arq_pdf).stat().st_size < 5_000:
        raise RuntimeError(f"o Chrome nao gerou o PDF: {r.stderr[-400:]}")
    return Path(arq_pdf)


def cifrar_pdf(arq_pdf: Path, senha: str) -> Path:
    """Cifra o PDF no lugar, com AES-256 (como o fornecedor do modelo faz)."""
    from pypdf import PdfWriter

    escritor = PdfWriter(clone_from=str(arq_pdf))
    escritor.encrypt(senha, algorithm="AES-256")
    tmp = Path(arq_pdf).with_name(Path(arq_pdf).name + ".tmp")
    with open(tmp, "wb") as f:
        escritor.write(f)
    tmp.replace(arq_pdf)
    return Path(arq_pdf)


def pdf_relatorio(dados: dict, destino: Path, senha: str | None = None) -> Path:
    """Grava o PDF do relatorio em `destino` (cifrado com AES-256 se `senha` vier). O HTML fica em pasta temporaria."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    html = html_relatorio(dados)
    with tempfile.TemporaryDirectory() as tmp:
        arq = Path(tmp) / "relatorio.html"
        arq.write_text(html, encoding="utf-8")
        imprimir_pdf(arq, destino)
    if senha:
        cifrar_pdf(destino, senha)
    return destino
