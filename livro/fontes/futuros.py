"""Brent por contrato explicito.

O BZ=F do Yahoo e um "continuo" que troca de vencimento quando quer: a cotacao ao
vivo e a barra do dia seguem o contrato seguinte antes do historico liquidado. Em
18, 21 e 23/09/2026 o livro comparou dezembro (Z26) com novembro (X26) e publicou
-5,3%, -7,5% e -1,4% quando o Brent fez -0,9%, -3,4% e +3,9% (auditoria de 23/09).

A sonda de 23/09 no runner mostrou que o Yahoo serve os contratos explicitos da
NYMEX (BZX26.NYM, BZZ26.NYM, BZF27.NYM, cada um com 2 anos de barras) e que o X26
liquidou 103,08 em 23/09, o numero da Reuters/CNBC. Entao:

- `contrato_vigente(d)`: o 1o vencimento em d (o que as agencias chamam de Brent);
- a serie BRENT do livro = BZ=F ate pouco antes do contrato vigente virar o 1o
  vencimento, e o contrato explicito dali em diante. Assim "dia" e "1 semana" saem
  sempre dentro do MESMO contrato; janelas longas usam o nivel do 1o vencimento de
  cada data (convencao das agencias), com nota quando atravessam uma rolagem.

Vencimento (NYMEX BZ, Brent Last Day Financial, espelho do ICE Brent): ultimo dia
util do segundo mes anterior ao mes do contrato. X26 (novembro) vence 30/09/2026;
Z26 (dezembro) vence 30/10/2026."""

from __future__ import annotations

from datetime import date, timedelta

LETRAS = "FGHJKMNQUVXZ"          # janeiro .. dezembro
MESES_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
DIAS_ANTES_DA_VIGENCIA = 10       # o contrato explicito entra na serie 10 dias antes de virar 1o vencimento


def _feriados_londres() -> set:
    try:
        from livro import relogios
        return relogios.feriados("LSE")
    except Exception:
        return set()


def _ultimo_util_do_mes(ano: int, mes: int) -> date:
    prox = date(ano + (mes == 12), mes % 12 + 1, 1)
    d = prox - timedelta(days=1)
    fer = _feriados_londres()
    while d.weekday() >= 5 or d in fer:
        d -= timedelta(days=1)
    return d


def codigo(ano: int, mes: int) -> str:
    return f"{LETRAS[mes - 1]}{ano % 100:02d}"


def ano_mes(cod: str) -> tuple[int, int]:
    return 2000 + int(cod[1:3]), LETRAS.index(cod[0]) + 1


def vencimento(cod: str) -> date:
    """Ultimo dia util (Londres) do 2o mes anterior ao mes do contrato."""
    ano, mes = ano_mes(cod)
    mes_v, ano_v = mes - 2, ano
    if mes_v <= 0:
        mes_v, ano_v = mes_v + 12, ano - 1
    return _ultimo_util_do_mes(ano_v, mes_v)


def contrato_vigente(d: date) -> str:
    """O 1o vencimento em d: o menor contrato que ainda nao venceu (no dia do
    vencimento, o contrato que vence ainda e o 1o)."""
    ano, mes = d.year, d.month
    for k in range(0, 6):
        m = mes + k
        a = ano + (m - 1) // 12
        m = (m - 1) % 12 + 1
        cod = codigo(a, m)
        if vencimento(cod) >= d:
            return cod
    raise ValueError(f"sem contrato vigente para {d}")


def proximo(cod: str) -> str:
    ano, mes = ano_mes(cod)
    return codigo(ano + (mes == 12), mes % 12 + 1)


def anterior(cod: str) -> str:
    ano, mes = ano_mes(cod)
    return codigo(ano - (mes == 1), (mes - 2) % 12 + 1)


def inicio_vigencia(cod: str) -> date:
    """Primeiro dia em que `cod` e o 1o vencimento: o dia util seguinte ao vencimento do anterior."""
    d = vencimento(anterior(cod)) + timedelta(days=1)
    fer = _feriados_londres()
    while d.weekday() >= 5 or d in fer:
        d += timedelta(days=1)
    return d


def simbolo_brent(cod: str) -> str:
    return f"BZ{cod}.NYM"


def rotulo(cod: str) -> str:
    ano, mes = ano_mes(cod)
    return f"{MESES_PT[mes - 1]}/{ano % 100:02d}"


def simbolos_para(d: date) -> list[str]:
    """Vigente e o seguinte: o seguinte ja e coletado para a rolagem nao pegar a serie de surpresa."""
    v = contrato_vigente(d)
    return [simbolo_brent(v), simbolo_brent(proximo(v))]


def emendar(barras_continuo: list[list], barras_contrato: list[list], cod: str) -> tuple[list[list], str]:
    """Serie BRENT = continuo antes do corte + contrato explicito a partir do corte.
    Devolve (barras, data_do_corte). Sem barras do contrato, devolve o continuo."""
    if not barras_contrato:
        return list(barras_continuo or []), ""
    corte = (inicio_vigencia(cod) - timedelta(days=DIAS_ANTES_DA_VIGENCIA)).isoformat()
    antes = [b for b in (barras_continuo or []) if b[0] < corte]
    depois = [b for b in barras_contrato if b[0] >= corte]
    return antes + depois, corte
