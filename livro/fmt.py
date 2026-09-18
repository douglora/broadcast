"""Formatacao brasileira de numeros para as saidas do livro."""

from __future__ import annotations


def num(x: float | None, dec: int = 2) -> str:
    """1234.5 -> '1.234,50'; None -> '-'."""
    if x is None:
        return "-"
    s = f"{x:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def preco(x: float | None, decimais: int | None = None) -> str:
    """Preco de tela: 4 casas se pedido, 0 casas acima de 1.000, senao 2."""
    if x is None:
        return "-"
    if decimais is not None:
        return num(x, decimais)
    return num(x, 0) if abs(x) >= 1000 else num(x, 2)


def pct(x: float | None, dec: int = 1, sinal: bool = True, sufixo: str = "%") -> str:
    """Fracao -> '+1,2%'; sem decimal a partir de |10|; None -> '-'."""
    if x is None:
        return "-"
    v = x * 100.0
    d = 0 if abs(round(v, dec)) >= 10 else dec
    s = num(abs(v), d)
    pref = ("+" if v > 0 else "-" if v < 0 else "") if sinal else ("-" if v < 0 else "")
    if not sinal and v < 0:
        s = num(v, d)
        pref = ""
    return f"{pref}{s}{sufixo}"


def pct_col(x: float | None, largura: int = 5) -> str:
    """Coluna da tabela: '+1,2', ' +13', '-0,4', sem o simbolo %, alinhada a direita."""
    if x is None:
        return "-".rjust(largura)
    return pct(x, 1, True, "").rjust(largura)


def bps(x: float | None, dec: int = 0, sinal: bool = True) -> str:
    if x is None:
        return "-"
    s = num(abs(x), dec)
    pref = ("+" if x > 0 else "-" if x < 0 else "") if sinal else ""
    return f"{pref}{s}"


def taxa(x: float | None, dec: int = 2) -> str:
    return "-" if x is None else num(x, dec)


def seta(x: float | None) -> str:
    if x is None:
        return ""
    return "↑" if x > 0 else "↓" if x < 0 else "="


def data_br(iso: str | None, com_ano: bool = False) -> str:
    if not iso:
        return "-"
    a, m, d = iso[:10].split("-")
    return f"{d}/{m}/{a}" if com_ano else f"{d}/{m}"


DIAS = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]


def dia_semana(d) -> str:
    return DIAS[d.weekday()]
