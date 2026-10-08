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


# Vencimento do futuro de indice (IND cheio e WIN mini) - usado pelo hedge de beta em
# quant/dados/mercado.py. Meses PARES apenas: nao existe contrato em mes impar.
MESES_VENCIMENTO_INDICE = (2, 4, 6, 8, 10, 12)
DIA_ANCORA_VENCIMENTO = 15
QUARTA_FEIRA = 2                 # date.weekday(): segunda = 0


def vencimento_indice(ano, mes):
    """Data de vencimento do futuro de Ibovespa (IND/WIN) do mes par dado.

    Regra aplicada: a quarta-feira mais proxima do dia 15 do mes de vencimento e, se
    essa quarta nao for pregao, o PREGAO ANTERIOR (ultimo_pregao_ate). Meses impares
    levantam ValueError porque nao existe contrato neles.

    SUPOSICAO (nao validada contra fonte oficial nesta maquina, que nao tem rede para a
    B3) - registrar em quant/docs/validar-com-fonte-real.md:
      1. que a regra e mesmo "quarta-feira mais proxima do dia 15" (e nao, por exemplo,
         a terceira quarta-feira do mes: as duas coincidem em quase todo mes, mas nao
         quando o dia 1 cai numa quarta - ai a terceira quarta e dia 15 e a quarta mais
         proxima do 15 tambem e dia 15, e quando o mes comeca numa quinta a terceira
         quarta e dia 21 e esta funcao devolve dia 18);
      2. o desempate quando a quarta nao e pregao: aqui recuamos para o pregao anterior;
         a B3 pode adiar para o pregao SEGUINTE. O caso concreto e outubro quando o dia
         15 cai num sabado: a quarta mais proxima e 12/10 (Nossa Senhora Aparecida,
         feriado) e esta funcao devolve 11/10 - se a regra real for adiar, seria 13/10.
         Ocorre em 2005, 2011, 2016, 2022, 2033... (a cada ~5/6 anos);
      3. que o vencimento e o mesmo para IND e WIN (o mini segue o cheio) e que ele nao
         muda por ajuste extraordinario de calendario da B3.
    Enquanto isso nao for validado, o backtest deve tratar a data de rolagem com folga
    (rolar 1 ou 2 pregoes antes do vencimento) para que um erro de 1 dia nao mude o
    resultado.
    """
    ano, mes = int(ano), int(mes)
    if mes not in MESES_VENCIMENTO_INDICE:
        raise ValueError(f"nao existe vencimento de futuro de indice no mes {mes} "
                         f"(meses validos: {MESES_VENCIMENTO_INDICE})")
    ancora = date(ano, mes, DIA_ANCORA_VENCIMENTO)
    adiante = (QUARTA_FEIRA - ancora.weekday()) % 7      # dias ate a proxima quarta
    atras = (ancora.weekday() - QUARTA_FEIRA) % 7        # dias desde a quarta anterior
    # adiante + atras = 7 quando o dia 15 nao e quarta, entao nunca ha empate
    quarta = ancora + timedelta(days=adiante) if adiante <= atras else ancora - timedelta(days=atras)
    return ultimo_pregao_ate(quarta)


def proximo_vencimento_indice(d):
    """Primeiro vencimento de futuro de indice ESTRITAMENTE depois de d.

    Pula para o proximo mes par - inclusive virando o ano (depois do vencimento de
    dezembro vem o de fevereiro seguinte).
    """
    d = _para_date(d)
    ano, mes = d.year, d.month + (d.month % 2)           # arredonda para o mes par >= mes de d
    for _ in range(len(MESES_VENCIMENTO_INDICE) + 2):    # no maximo um ano a frente
        v = vencimento_indice(ano, mes)
        if v > d:
            return v
        mes += 2
        if mes > 12:
            ano, mes = ano + 1, 2
    raise ValueError(f"nenhum vencimento encontrado depois de {d}")   # inalcancavel
