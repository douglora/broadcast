"""
Calendario de pregoes da B3.

Usa o calendario 'B3' do pacote bizdays (feriados oficiais da bolsa) e, para datas
fora da sua cobertura, o 'ANBIMA' (feriados bancarios, que coincidem com os da B3 na
pratica). Feriado na B3 significa: COTAHIST_D inexistente, HTTP 400 no arquivos.b3 e
ZIP vazio no tickercsv - por isso tudo que baixa por data passa por aqui antes.
"""
from datetime import date, datetime, timedelta

from bizdays import Calendar

_B3 = Calendar.load("B3")
_ANBIMA = Calendar.load("ANBIMA")


def _para_date(d):
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return datetime.strptime(str(d)[:10], "%Y-%m-%d").date()


def _cal(d):
    """B3 quando a data esta na cobertura do calendario da bolsa; senao ANBIMA."""
    d = _para_date(d)
    ini, fim = _para_date(_B3.startdate), _para_date(_B3.enddate)
    return _B3 if ini <= d <= fim else _ANBIMA


def eh_pregao(d):
    d = _para_date(d)
    return bool(_cal(d).isbizday(d))


def pregao_anterior(d):
    """Ultimo pregao estritamente antes de d."""
    d = _para_date(d) - timedelta(days=1)
    while not eh_pregao(d):
        d -= timedelta(days=1)
    return d


def proximo_pregao(d):
    """Primeiro pregao estritamente depois de d."""
    d = _para_date(d) + timedelta(days=1)
    while not eh_pregao(d):
        d += timedelta(days=1)
    return d


def ultimo_pregao_ate(d):
    """d se for pregao; senao o pregao anterior."""
    d = _para_date(d)
    return d if eh_pregao(d) else pregao_anterior(d)


def ultimo_pregao_do_mes(ano, mes):
    if mes == 12:
        d = date(ano + 1, 1, 1)
    else:
        d = date(ano, mes + 1, 1)
    return pregao_anterior(d)


def pregoes(ini, fim):
    """Lista de pregoes no intervalo fechado [ini, fim]."""
    d, fim = _para_date(ini), _para_date(fim)
    out = []
    while d <= fim:
        if eh_pregao(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def pregoes_atras(d, n):
    """Pregao n pregoes antes de d (n=0 devolve o ultimo pregao ate d)."""
    d = ultimo_pregao_ate(d)
    for _ in range(n):
        d = pregao_anterior(d)
    return d
