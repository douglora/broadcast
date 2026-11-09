"""Dias uteis e o juro composto no metodo do simulador do Safra (cockpit de LF, prints de 28/10/2026).

Taxa ao ano e base 252: o fator e (1 + taxa) ** (dias uteis / 252), com os feriados nacionais da ANBIMA. O bruto e
o imposto saem truncados no centavo, e o liquido e o bruto menos o imposto. Conferido nos dois prints do Douglas:
R$ 100 mil a 14,45% de 21/08/2026 a 22/08/2030 (999 dias uteis) dao R$ 160.140,52 liquidos; R$ 70 mil a 14,52% de
25/08/2026 a 27/11/2035 (2.316 dias uteis) dao R$ 217.354,28. Sete anos de calendario nao sao 7 anos de juro: de
28/10/2026 a 28/10/2033 sao 1.755 dias uteis, 6,96 anos base 252.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from functools import lru_cache

from . import fiscal as F


def pascoa(ano: int) -> date:
    """Domingo de Pascoa (algoritmo de Meeus/Jones/Butcher)."""
    b, c, d = ano % 19, ano // 100, ano % 100
    e, f, g = c // 4, c % 4, (c + 8) // 25
    h = (c - g + 1) // 3
    i = (19 * b + c - e - h + 15) % 30
    k, l = d // 4, d % 4
    m = (32 + 2 * f + 2 * k - i - l) % 7
    n = (b + 11 * i + 22 * m) // 451
    mes, dia = (i + m - 7 * n + 114) // 31, (i + m - 7 * n + 114) % 31 + 1
    return date(ano, mes, dia)


@lru_cache(maxsize=None)
def feriados(ano: int) -> frozenset:
    """Feriados nacionais da ANBIMA: os fixos, Carnaval (segunda e terca), Sexta-feira Santa, Corpus Christi e,
    desde 2024, o 20 de novembro."""
    p = pascoa(ano)
    fs = {date(ano, 1, 1), p - timedelta(48), p - timedelta(47), p - timedelta(2), date(ano, 4, 21), date(ano, 5, 1),
          p + timedelta(60), date(ano, 9, 7), date(ano, 10, 12), date(ano, 11, 2), date(ano, 11, 15), date(ano, 12, 25)}
    if ano >= 2024:
        fs.add(date(ano, 11, 20))
    return frozenset(fs)


def dias_uteis(ini: date, fim: date) -> int:
    """Dias uteis de `ini` (conta) ate `fim` (nao conta), como o simulador conta da aplicacao ao vencimento."""
    n, d = 0, ini
    while d < fim:
        if d.weekday() < 5 and d not in feriados(d.year):
            n += 1
        d += timedelta(1)
    return n


def mais_anos(d: date, anos: int) -> date:
    """A mesma data `anos` anos depois (29/02 vira 28/02)."""
    try:
        return d.replace(year=d.year + anos)
    except ValueError:
        return d.replace(year=d.year + anos, day=28)


def anos_252(ini: date, fim: date) -> float:
    """O prazo em anos de juro: dias uteis / 252."""
    return dias_uteis(ini, fim) / 252.0


def _trunca(x: float) -> float:
    return math.floor(x * 100.0 + 1e-6) / 100.0


def simular(valor: float, taxa: float, ini: date, fim: date, aliquota: float | None = None) -> dict:
    """O titulo no vencimento, como o simulador do Safra: bruto, imposto (tabela regressiva pelos dias corridos se
    `aliquota` nao vier; 0 para isento), liquido, lucro, rentabilidade e taxa liquida ao ano (base 252)."""
    du = dias_uteis(ini, fim)
    aliq = F.aliquota_regressiva((fim - ini).days / 365.0) if aliquota is None else float(aliquota)
    bruto = _trunca(valor * (1.0 + taxa) ** (du / 252.0))
    ir = _trunca(aliq * max(0.0, bruto - valor))
    liq = round(bruto - ir, 2)
    return {"du": du, "dc": (fim - ini).days, "anos": du / 252.0, "aliquota": aliq, "bruto": bruto, "ir": ir,
            "liquido": liq, "lucro": round(liq - valor, 2), "rent": liq / valor - 1.0,
            "taxa_liq": (liq / valor) ** (252.0 / du) - 1.0 if du else 0.0}
