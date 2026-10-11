"""Formatos brasileiros para as frases do swing (milhar com ponto, decimal com virgula)."""


def br(x, casas=2):
    """1234.5 -> '1.234,50'; None/NaN -> '-'."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "-"
    if v != v:
        return "-"
    s = f"{abs(v):,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if v < 0 and float(s.replace(".", "").replace(",", ".")) != 0 else "") + s


def brl(x, casas=2):
    s = br(x, casas)
    return s if s == "-" else (f"-R$ {s[1:]}" if s.startswith("-") else f"R$ {s}")


def pct(frac, casas=1, sinal=False):
    """0.0234 -> '2,3%'; com sinal=True '+2,3%'."""
    try:
        v = float(frac) * 100.0
    except (TypeError, ValueError):
        return "-"
    if v != v:
        return "-"
    s = br(v, casas)
    return ("+" + s if sinal and v > 0 else s) + "%"
