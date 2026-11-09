"""DARF (Documento de Arrecadacao de Receitas Federais) em A4 retrato: duas vias iguais, sem codigo de barras.

O desenho e uma lista de primitivas (texto, linha, retangulo, brasao) com as posicoes em pontos, e sai de dois jeitos:
- `html_darf`: HTML posicionado como o do relatorio (para ver na tela e comparar com o modelo);
- `pdf_darf`: PDF leve, sem o Chrome (pdfleve.py: Helvetica padrao do PDF e o brasao pequeno `brasao_leve.png`), com
  poucos KB, porque o DARF vai anexo no e-mail e o anexo e escrito dentro da chamada do conector do Gmail.
O brasao da Republica vem de `brasao.png` (HTML) e `brasao_leve.png` (PDF), ao lado deste modulo; sem o arquivo, o
DARF sai igual, so sem o brasao.

Campos de `c` (dicionario do motor):
    nome, telefone ("" se nao houver), periodo_apuracao "31/10/2026", documento (CPF ou CNPJ ja formatado),
    codigo_receita "6015", referencia ("" se nao houver), vencimento, principal, multa, juros, total, mes_ref "OUTUBRO",
    ano_ref 2026, valido_ate, observacao (opcional: frase curta que sai embaixo das vias).
Campo opcional acrescentado: domicilio ("CIDADE - UF"), que sai em "Domicilio tributario do contribuinte".
Multa ou juros ausentes saem como R$ 0,00; sem `total`, ele e a soma dos tres valores.
"""

from __future__ import annotations

import base64
from pathlib import Path

from . import pdfleve
from .relatorio import _ov, _quebra, _t, brl, cifrar_pdf, dat

PAG_W = 595.28
PAG_H = 841.89
VIA_DY = 356.9            # distancia entre a 1a e a 2a via
BRASAO = Path(__file__).with_name("brasao.png")
BRASAO_LEVE = Path(__file__).with_name("brasao_leve.png")

CSS = """
@page { size: A4 portrait; margin: 0; }
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { background: #fff; }
body { font-family: Helvetica, Arial, sans-serif; color: #000; font-size: 9pt;
       -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.pg { position: relative; width: 210mm; height: 296.6mm; overflow: hidden; background: #fff; }
.via { position: absolute; left: 0; top: 0; width: 210mm; height: 296.6mm; }
.a { position: absolute; white-space: nowrap; }
.ov { position: absolute; left: 0; top: 0; }
.ov text { font-family: Helvetica, Arial, sans-serif; fill: #000; }
img.br { position: absolute; }
"""

# linhas do quadro da direita: (rotulo, numero, topo, altura, linhas do rotulo)
LINHAS = [
    ("02", 41.7, 27.0, ["PERÍODO DE APURAÇÃO"]),
    ("03", 68.7, 27.0, ["NÚMERO DO CPF OU CNPJ"]),
    ("04", 95.7, 27.1, ["CÓDIGO DA RECEITA"]),
    ("05", 122.8, 27.0, ["NÚMERO DE REFERÊNCIA"]),
    ("06", 149.8, 27.0, ["DATA DE VENCIMENTO"]),
    ("07", 176.8, 27.0, ["VALOR DO PRINCIPAL"]),
    ("08", 203.8, 27.0, ["VALOR DA MULTA"]),
    ("09", 230.8, 34.5, ["VALOR DOS JUROS E/OU", "ENCARGOS DL 1.025/69"]),
    ("10", 265.3, 27.1, ["VALOR TOTAL"]),
]


def _valores(c: dict) -> list[str]:
    principal = float(c.get("principal") or 0.0)
    multa = float(c.get("multa") or 0.0)
    juros = float(c.get("juros") or 0.0)
    total = c.get("total")
    total = principal + multa + juros if total is None else float(total)
    return [dat(c.get("periodo_apuracao")), str(c.get("documento") or ""), str(c.get("codigo_receita") or ""),
            str(c.get("referencia") or ""), dat(c.get("vencimento")), brl(principal), brl(multa), brl(juros),
            brl(total)]


# ---- desenho: ('t', x, base, texto, pt, negrito, anc) | ('l', x0, y0, x1, y1, larg) | ('r', x, y, w, h, larg)
#      | ('img', x, y, w, h); y a partir do topo da pagina, texto pela linha de base
def _via(c: dict, n: int) -> list[tuple]:
    dy = (n - 1) * VIA_DY

    def t(x, base, txt, pt=9, negrito=False, anc="e"):
        return ("t", x, base + dy, txt, pt, negrito, anc)

    def ln(x0, y0, x1, y1, larg=1.0):
        return ("l", x0, y0 + dy, x1, y1 + dy, larg)

    els = [("img", 39.2, 43.6 + dy, 44.9, 47.2)]
    # molduras: quadro da esquerda, quadro da direita e divisorias
    els += [("r", 32.3, 41.7 + dy, 275.1, 250.7, 1.0), ("r", 307.4, 41.7 + dy, 247.3, 250.7, 1.0),
            ln(424.7, 41.7, 424.7, 292.4)]
    els += [ln(307.4, topo, 554.7, topo) for _, topo, _, _ in LINHAS[1:]]
    els += [ln(32.3, 122.8, 307.4, 122.8), ln(32.3, 155.5, 307.4, 155.5)]
    # linha de corte, com o texto no meio
    els += [ln(31.9, 345.6, 400.7, 345.6, 0.5), ln(466.9, 345.6, 552.2, 345.6, 0.5)]
    els += [t(33.9, 37.9, "Aprovado pela IN/RFB nº 736/2007", 7), t(552.4, 37.9, f"{n}ª Via", 7, anc="d"),
            t(91.8, 55.8, "MINISTÉRIO DA FAZENDA", 10, True),
            t(91.8, 72.7, "SECRETARIA DA RECEITA FEDERAL DO BRASIL", 9, True),
            t(91.8, 88.5, "Documento de Arrecadação de Receitas Federais", 8, True), t(91.8, 109.0, "DARF", 12, True)]
    # campo 01
    nome = str(c.get("nome") or "")
    tel = str(c.get("telefone") or "").strip()
    els += [t(33.9, 136.9, "01", 10, True), t(47.8, 136.9, "NOME / TELEFONE", 7),
            t(47.5, 146.2, f"{nome} / {tel}" if tel else nome, 8)]
    # texto livre do lado esquerdo
    els += [t(33.9, 179.7, "REF. OPERAÇÕES EM BOLSA DE VALORES", 9, True),
            t(33.9, 189.7, f"{c.get('mes_ref', '')} de {c.get('ano_ref', '')}", 9, True),
            t(33.9, 209.7, f"DARF válido para pagamento até {dat(c.get('valido_ate'))}", 9, True),
            t(33.9, 229.1, "Domicílio tributário do contribuinte:", 7)]
    if c.get("domicilio"):
        els.append(t(33.9, 238.7, str(c["domicilio"]), 9, True))
    els.append(t(33.9, 268.8, "NÃO RECEBER COM RASURAS", 9, True))
    # campos 02 a 10
    for (num, topo, alt, rot), val in zip(LINHAS, _valores(c)):
        els += [t(309.4, topo + 11.1, num, 10, True), t(323.3, topo + 11.1, rot[0], 7)]
        if len(rot) > 1:
            els.append(t(309.4, topo + 19.5, rot[1], 7))
        if val:
            els.append(t(552.9, topo + (20.4 if alt > 30 else 16.6), val, 9, anc="d"))
    # campo 11 e linha de corte
    els += [t(358.2, 303.4, "11", 10, True), t(372.1, 303.4, "AUTENTICAÇÃO BANCÁRIA (Somente nas 1ª e 2ª vias)", 7),
            t(403.6, 348.2, "cortar nesta linha", 7)]
    return els


def _rodape(c: dict) -> list[tuple]:
    els = [("r", 32.6, 729.2, 519.8, 16.5, 0.5),
           ("t", PAG_W / 2, 739.2, "DARF emitido em duas vias. Recorte nas linhas indicadas e efetue o pagamento na rede "
            "bancária autorizada.", 8, False, "c"),
           ("t", 108.8, 768.9, "DARF impresso sem código de barras. Para pagar, use o código da receita, o período de "
            "apuração,", 8, False, "e"),
           ("t", 108.8, 777.9, "o vencimento e o valor total informados acima.", 8, False, "e")]
    obs = str(c.get("observacao") or "").strip()
    if obs:
        for i, linha in enumerate(_quebra(obs, 400.0, 8, False, 2)):
            els.append(("t", 108.8, 795.9 + i * 9.0, linha, 8, False, "e"))
    return els


# ---- HTML ------------------------------------------------------------------------------------------
def _html(els: list[tuple], brasao_uri: str | None) -> str:
    """Textos e brasao em elementos posicionados; linhas e retangulos num SVG por cima."""
    html, svg = [], []
    for el in els:
        if el[0] == "t":
            _, x, base, txt, pt, negrito, anc = el
            html.append(_t(x, base, txt, pt, 700 if negrito else 400, anc=anc, larg_pag=PAG_W))
        elif el[0] == "l":
            _, x0, y0, x1, y1, larg = el
            svg.append(f'<path d="M{x0:.2f},{y0:.2f} L{x1:.2f},{y1:.2f}" stroke="#000" stroke-width="{larg}" fill="none"/>')
        elif el[0] == "r":
            _, x, y, w, h, larg = el
            svg.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{w}" height="{h}" stroke="#000" stroke-width="{larg}" '
                       'fill="none"/>')
        elif brasao_uri:
            _, x, y, w, h = el
            html.append(f'<img class="br" src="{brasao_uri}" style="left:{x}pt;top:{y:.2f}pt;width:{w}pt;height:{h}pt">')
    return "".join(html) + _ov("".join(svg), PAG_W, PAG_H)


def _brasao_uri() -> str | None:
    try:
        return "data:image/png;base64," + base64.b64encode(BRASAO.read_bytes()).decode("ascii")
    except OSError:
        return None


def html_darf(c: dict) -> str:
    """HTML do DARF em A4 retrato: via 1 em cima, via 2 embaixo (iguais), aviso de recorte e nota de impressao."""
    uri = _brasao_uri()
    corpo = "".join(f'<div class="via">{_html(_via(c, n), uri)}</div>' for n in (1, 2))
    return ('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>DARF</title>'
            f'<style>{CSS}</style></head><body><section class="pg">{corpo}{_html(_rodape(c), None)}</section>'
            '</body></html>')


# ---- PDF leve --------------------------------------------------------------------------------------
def pdf_darf(c: dict, destino: Path, senha: str | None = None) -> Path:
    """Grava o DARF em PDF (uma pagina A4 retrato, poucos KB) em `destino`; cifra com AES-256 se `senha` vier."""
    destino = Path(destino)
    pg = pdfleve.Pagina(PAG_W, PAG_H)
    png = BRASAO_LEVE.read_bytes() if BRASAO_LEVE.exists() else None
    for el in _via(c, 1) + _via(c, 2) + _rodape(c):
        if el[0] == "t":
            _, x, base, txt, pt, negrito, anc = el
            pg.texto(x, base, txt, pt, negrito, anc)
        elif el[0] == "l":
            pg.linha(*el[1:])
        elif el[0] == "r":
            pg.retangulo(*el[1:])
        elif png:
            pg.imagem(png, *el[1:])
    pdfleve.gravar([pg], destino, "DARF")
    if senha:
        cifrar_pdf(destino, senha)
    return destino
