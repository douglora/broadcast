"""Toda pergunta de tempo em um lugar: dia util por mercado, 'este mercado ja
fechou hoje?' em BRT calculado com zoneinfo (imune ao horario de verao dos
EUA/UK), ultimo pregao, base do YTD e vencimento do DI.

Fonte dos feriados e horarios: config/calendario.yaml."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from livro.universo import carregar_yaml

BRT = ZoneInfo("America/Sao_Paulo")
_CAL: dict | None = None


def calendario() -> dict:
    global _CAL
    if _CAL is None:
        _CAL = carregar_yaml("calendario.yaml")
    return _CAL


def _d(x) -> date:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return datetime.strptime(str(x)[:10], "%Y-%m-%d").date()


def feriados(mercado: str) -> set:
    return {_d(x) for x in (calendario().get("feriados", {}).get(mercado) or [])}


def mercado_cfg(mercado: str) -> dict:
    m = calendario()["mercados"].get(mercado)
    if not m:
        raise KeyError(f"mercado desconhecido: {mercado}")
    return m


def eh_dia_util(mercado: str, d) -> bool:
    d = _d(d)
    m = mercado_cfg(mercado)
    if d.weekday() not in m.get("dias", [0, 1, 2, 3, 4]):
        return False
    return d not in feriados(mercado)


def ultimo_dia_util(mercado: str, d) -> date:
    """d se for dia util; senao o dia util anterior."""
    d = _d(d)
    while not eh_dia_util(mercado, d):
        d -= timedelta(days=1)
    return d


def dia_util_anterior(mercado: str, d) -> date:
    d = _d(d) - timedelta(days=1)
    return ultimo_dia_util(mercado, d)


def proximo_dia_util(mercado: str, d) -> date:
    d = _d(d) + timedelta(days=1)
    while not eh_dia_util(mercado, d):
        d += timedelta(days=1)
    return d


def fechamento_local(mercado: str, d) -> datetime:
    """Hora de fechamento do pregao de d, no fuso do mercado (meio pregao respeitado)."""
    d = _d(d)
    m = mercado_cfg(mercado)
    tz = ZoneInfo(m["tz"])
    hh, mm = (m["fecha"].split(":") + ["0"])[:2]
    meio = {_d(x) for x in (calendario().get("meio_pregao", {}).get(mercado) or [])}
    if d in meio:
        hh, mm = ("13", "00") if mercado == "NYSE" else ("12", "30")
    return datetime.combine(d, time(int(hh), int(mm)), tzinfo=tz)


def fechamento_brt(mercado: str, d) -> datetime:
    return fechamento_local(mercado, d).astimezone(BRT)


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def fechou(mercado: str, agora: datetime | None = None, d=None) -> bool:
    """True se o pregao de d (padrao: hoje em BRT) ja encerrou no instante 'agora'."""
    agora = agora or agora_utc()
    if agora.tzinfo is None:
        agora = agora.replace(tzinfo=timezone.utc)
    d = _d(d) if d else agora.astimezone(BRT).date()
    if not eh_dia_util(mercado, d):
        return True
    if mercado_cfg(mercado).get("continuo"):
        # mercados continuos: consideramos 'fechado' apos o corte diario em BRT
        corte = datetime.combine(d, time(18, 0), tzinfo=BRT)
        return agora >= corte
    return agora >= fechamento_local(mercado, d).astimezone(timezone.utc)


def data_referencia(mercado: str, agora: datetime | None = None) -> date:
    """Ultimo pregao cuja barra diaria deveria existir: hoje se ja fechou, senao o anterior."""
    agora = agora or agora_utc()
    hoje = agora.astimezone(BRT).date()
    if eh_dia_util(mercado, hoje):
        return hoje if fechou(mercado, agora, hoje) else dia_util_anterior(mercado, hoje)
    return ultimo_dia_util(mercado, hoje)


def data_pregao_b3(agora: datetime | None = None) -> date:
    """Dia util B3 corrente em BRT (hoje se for dia util, senao o anterior)."""
    agora = agora or agora_utc()
    return ultimo_dia_util("B3", agora.astimezone(BRT).date())


def base_ytd(datas: list[str], ano: int) -> int | None:
    """Indice da ultima barra <= 31/12/(ano-1) na lista ordenada de datas ISO."""
    limite = f"{ano - 1}-12-31"
    idx = None
    for i, d in enumerate(datas):
        if d <= limite:
            idx = i
        else:
            break
    return idx


def indice_ref(datas: list[str], alvo: date) -> int | None:
    """Indice da ultima barra com data <= alvo."""
    alvo_s = alvo.isoformat()
    idx = None
    for i, d in enumerate(datas):
        if d <= alvo_s:
            idx = i
        else:
            break
    return idx


def vencimento_di(codigo: str) -> date:
    """DI1F28 -> 1o dia util B3 de janeiro de 2028."""
    letra = codigo[3]
    ano = 2000 + int(codigo[4:6])
    meses = {"F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6, "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12}
    d = date(ano, meses[letra], 1)
    while not eh_dia_util("B3", d):
        d += timedelta(days=1)
    return d


def dias_uteis_b3(d1, d2) -> int:
    """Dias uteis B3 em (d1, d2]: conta a partir do dia seguinte a d1 ate d2 inclusive."""
    d1, d2 = _d(d1), _d(d2)
    n, d = 0, d1 + timedelta(days=1)
    while d <= d2:
        if eh_dia_util("B3", d):
            n += 1
        d += timedelta(days=1)
    return n


def brt(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BRT)


def fmt_brt(dt: datetime | None, com_data: bool = False) -> str:
    if dt is None:
        return "-"
    b = brt(dt)
    return b.strftime("%d/%m %Hh%M") if com_data else b.strftime("%Hh%M")
