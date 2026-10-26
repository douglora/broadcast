"""Formatacao no padrao brasileiro (virgula decimal, ponto de milhar) para texto e relatorio."""

from __future__ import annotations


def _sep(s: str) -> str:
    return s.replace(",", "\0").replace(".", ",").replace("\0", ".")


def num(x: float, casas: int = 1) -> str:
    return _sep(f"{x:,.{casas}f}")


def pct(x: float, casas: int = 1) -> str:
    return num(x * 100.0, casas) + "%"


def pp(x: float, casas: int = 1) -> str:
    """Diferenca em pontos percentuais, com sinal: pp(0.0123) -> '+1,2 p.p.'."""
    return _sep(f"{x*100:+,.{casas}f}") + " p.p."


def brl(x: float, casas: int = 0) -> str:
    return "R$ " + num(x, casas)


def mi(x: float, casas: int = 1) -> str:
    """R$ em milhoes: 8_250_000 -> 'R$ 8,3 mi'; abaixo de 1 mi mostra em mil."""
    if abs(x) >= 1_000_000:
        return f"R$ {num(x/1e6, casas)} mi"
    return f"R$ {num(x/1e3, 0)} mil"


def prob(x: float, casas: int = 0) -> str:
    """Probabilidade sem falsa certeza: 100% vira 'mais de 99%', 0% vira 'menos de 1%'."""
    if x >= 0.995:
        return "mais de 99%"
    if x <= 0.005:
        return "menos de 1%"
    return pct(x, casas)


def pcts(x: float, casas: int = 1) -> str:
    """Percentual com sinal: +3,6% ou -7,4%."""
    return _sep(f"{x*100:+,.{casas}f}") + "%"
