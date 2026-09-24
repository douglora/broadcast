"""Portao de qualidade por serie: antes de qualquer numero virar tabela, alerta,
push ou frase da Leitura da Mesa, a ultima barra passa por aqui.

Por que existe (auditoria de 23/09/2026, 15 agentes, tudo reproduzido no historico
do branch dados):
- BRENT (BZ=F): em 23/09 o livro publicou -1,4% a US$ 97,83; o Brent liquidou
  +3,86% a US$ 103,08. A barra "de 23/09" tinha volume 111 (mediana de 40 mil) e
  o regularMarketTime era 19h48 de Nova York: as duas primeiras horas da SESSAO
  SEGUINTE. Em 18 e 21/09 o livro misturou contratos (novembro x dezembro).
- USDBRL: em 23/09 o livro publicou -0,2% a R$ 5,0999; o dolar subiu 1,28%. A
  barra diaria do Yahoo ainda tinha o fechamento anterior, e a propria cotacao do
  Yahoo (meta.regularMarketPrice, R$ 5,1641 as 19h35) ja dizia o contrario.
- DXY: barra de 23/09 com amplitude de 0,015 ponto (mediana 0,36): foto de um
  instante, nao um pregao. Publicado +0,70%; o dia foi de +0,14% a +0,35%.
- MMM, GFS, IBOV e outros 17: sem a barra de 22/09. A "variacao do dia" de 23/09
  era de DOIS pregoes (MMM +3,2% "no dia" contra +0,6% real) e o T05 disparou.

O que o portao faz com a ULTIMA barra de cada serie:
- nao_confirmado + descartar: barra que nao e o pregao que diz ser (toco da sessao
  seguinte, OHLC incoerente em futuro, amplitude de foto em indice/commodity). A
  barra sai da serie antes de qualquer conta; a serie fica "velha" e a lacuna diz
  por que. Numero ausente e honesto; numero errado nao.
- nao_confirmado sem descartar: a barra e da data certa mas o valor nao bate com a
  cotacao do proprio Yahoo (cambio de 23/09). A coluna "dia" vira "a confirmar".
- suspeito: sinal fraco (volume baixo em acao, cotacao ao vivo de futuro diferente
  da barra). O numero sai com marcador e nao alimenta alerta critico.
- dia_pregoes > 1: faltou barra entre a penultima e a ultima; a variacao cobre
  mais de um pregao e nao pode ser chamada de "dia".
- parcial: cripto antes da meia-noite UTC; a barra do dia ainda esta se formando.

Tudo aqui e funcao pura sobre o dict da serie (o mesmo JSON do branch dados), para
ser testado com os commits reais de 18 a 23/09 como fixture."""

from __future__ import annotations

import re
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from livro import relogios

OK = "ok"
SUSPEITO = "suspeito"
NAO_CONFIRMADO = "nao_confirmado"
_ORDEM = {OK: 0, SUSPEITO: 1, NAO_CONFIRMADO: 2}

TOL_OHLC = 0.001          # 0,1%: arredondamento do Yahoo
VOLUME_TOCO = 0.05        # ultima barra com volume < 5% da mediana de 20
AMPLITUDE_FOTO = 0.10     # amplitude < 10% da mediana de 20: foto, nao pregao
META_DIVERGE = 0.003      # 0,3% entre a cotacao do Yahoo e o fechamento da mesma data
REABERTURA_FUTURO = {"America/New_York": 18, "America/Chicago": 17}   # Globex reabre

_CONTRATO = re.compile(r"^[A-Z]{1,4}[FGHJKMNQUVXZ]\d{2}\.(NYM|CMX|CBT|CME|NYB)$")


@dataclass
class Veredito:
    status: str = OK
    motivos: list[str] = field(default_factory=list)
    descartar_ultima: bool = False
    data_barra: str | None = None           # data da barra avaliada
    dia_pregoes: int = 1                    # >1: "dia" cobre mais de um pregao
    sem_barra: list[str] = field(default_factory=list)
    volume_provisorio: bool = False
    parcial: bool = False

    def piorar(self, status: str, motivo: str) -> None:
        if _ORDEM[status] > _ORDEM[self.status]:
            self.status = status
        if motivo and motivo not in self.motivos:
            self.motivos.append(motivo)

    def para_json(self) -> dict:
        return asdict(self)


def e_futuro(dados: dict, simbolo: str) -> bool:
    tipo = str(((dados or {}).get("meta") or {}).get("instrumentType") or "").upper()
    return tipo == "FUTURE" or simbolo.endswith("=F") or bool(_CONTRATO.match(simbolo))


def _mediana(xs: list[float]) -> float:
    xs = [x for x in xs if x is not None and x > 0]
    return statistics.median(xs) if xs else 0.0


def _num(x) -> float | None:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _fmt_int(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def _meta_local(dados: dict) -> tuple[datetime | None, float | None]:
    meta = (dados or {}).get("meta") or {}
    rmt, rmp = meta.get("regularMarketTime"), _num(meta.get("regularMarketPrice"))
    if not rmt:
        return None, rmp
    try:
        tz = ZoneInfo((dados or {}).get("tz") or "UTC")
    except Exception:
        tz = timezone.utc
    return datetime.fromtimestamp(int(rmt), tz), rmp


def _dia_util(mercado: str, d: date) -> bool:
    try:
        return relogios.eh_dia_util(mercado, d)
    except KeyError:
        return d.weekday() < 5


def _feriado_eua(d: date) -> bool:
    # ICE e FX nao tem lista propria no calendario: dia sem barra em feriado dos
    # EUA e normal (DXY em 19/06, 03/07, 07/09), nao buraco
    try:
        return d in relogios.feriados("NYSE")
    except Exception:
        return False


def dias_sem_barra(mercado: str, anterior: str, ultima: str) -> list[str]:
    """Pregoes do mercado estritamente entre `anterior` e `ultima` (ISO) que nao tem
    barra. Feriado do mercado nao conta; em ICE/FX, feriado dos EUA tambem nao."""
    if mercado == "CRIPTO":
        return []
    d0, d1 = date.fromisoformat(anterior), date.fromisoformat(ultima)
    faltam = []
    d = d0 + timedelta(days=1)
    while d < d1:
        if _dia_util(mercado, d) and not (mercado in ("ICE", "FX") and _feriado_eua(d)):
            faltam.append(d.isoformat())
        d += timedelta(days=1)
    return faltam


def limpar_fim_de_semana(barras: list[list], mercado: str) -> list[list]:
    """Barra em dia sem pregao do mercado (o Yahoo publica USDBRL no domingo): sai se
    o pregao anterior ja tem barra; se nao tem, vira a barra desse pregao. Nunca
    em cripto, que negocia todo dia."""
    if mercado == "CRIPTO" or not barras:
        return barras
    datas = {b[0] for b in barras}
    out = []
    for b in barras:
        try:
            d = date.fromisoformat(b[0])
        except (TypeError, ValueError):
            out.append(b)
            continue
        if _dia_util(mercado, d):
            out.append(b)
            continue
        try:
            util = relogios.ultimo_dia_util(mercado, d)
        except KeyError:
            util = d - timedelta(days=max(0, d.weekday() - 4))
        if util.isoformat() in datas:
            continue                           # sexta existe: o domingo sai
        datas.add(util.isoformat())
        out.append([util.isoformat(), *b[1:]])  # falta a sexta: o domingo vira sexta
    out.sort(key=lambda b: b[0])
    return out


def avaliar(dados: dict, simbolo: str, mercado: str, classe: str = "",
            agora: datetime | None = None, ate: date | None = None,
            confirmadas: dict | None = None) -> Veredito:
    """Veredito sobre a ultima barra com data <= `ate`.

    `confirmadas` = {data: 'hh:mm'} das barras cujo fechamento veio de fonte
    independente (o dolar das 17h pelo grafico de 15 minutos): nelas a cotacao do
    Yahoo de depois nao desmente nada."""
    confirmadas = confirmadas or {}
    v = Veredito()
    todas = [b for b in ((dados or {}).get("barras") or []) if b and b[0]]
    barras = [b for b in todas if b[0] <= ate.isoformat()] if ate is not None else todas
    if len(barras) < 2:
        return v
    u, pen = barras[-1], barras[-2]
    v.data_barra = u[0]
    futuro = e_futuro(dados, simbolo)
    # futuro e indice da ICE (DXY): negociam a noite, a sessao seguinte reabre as 18h ET
    continuo_eua = futuro or mercado == "ICE"
    agora = agora or datetime.now(timezone.utc)
    o, h, l, c, vol = _num(u[1]), _num(u[2]), _num(u[3]), _num(u[4]), _num(u[6])
    anteriores = barras[-21:-1]
    # a cotacao do Yahoo (meta) e da ULTIMA barra da serie; se ja existe barra depois
    # desta (a sessao seguinte, redatada pelo parser), a cotacao nao fala desta
    e_a_ultima = todas[-1][0] == u[0]
    # barra provisoria do Yahoo (so o fechamento; abertura, maxima e minima zeradas):
    # o fechamento vale, mas amplitude, OHLC e volume nao dizem nada
    provisoria = not any((_num(x) or 0) for x in (u[1], u[2], u[3]))
    if provisoria:
        v.motivos.append(f"barra de {_br(u[0])} provisória do Yahoo (só o fechamento)")

    # 1) toco: a barra "de D" e o comeco da sessao seguinte (Globex reabre as 18h ET)
    dt_meta, rmp = _meta_local(dados)
    if continuo_eua and e_a_ultima and dt_meta is not None and dt_meta.date().isoformat() == u[0]:
        reabre = REABERTURA_FUTURO.get(str(dados.get("tz")))
        if reabre is not None and dt_meta.hour >= reabre:
            v.piorar(NAO_CONFIRMADO, f"barra de {_br(u[0])} é o início da sessão seguinte "
                                     f"(última cotação {dt_meta:%H:%M} de {_cidade(dados)})")
            v.descartar_ultima = True
    med_vol = _mediana([_num(b[6]) for b in anteriores])
    if not provisoria and med_vol and vol is not None and 0 < vol < VOLUME_TOCO * med_vol:
        if futuro:
            v.piorar(NAO_CONFIRMADO, f"barra de {_br(u[0])} com volume {_fmt_int(vol)} "
                                     f"(mediana {_fmt_int(med_vol)}): não é o pregão inteiro")
            v.descartar_ultima = True
        else:
            v.piorar(SUSPEITO, f"volume de {_br(u[0])} muito abaixo da média ({_fmt_int(vol)} contra {_fmt_int(med_vol)})")

    # 2) OHLC incoerente: fechamento ou abertura fora da maxima/minima
    if not provisoria and u[0] not in confirmadas and None not in (o, h, l, c) and h >= l > 0:
        fora = (c > h * (1 + TOL_OHLC) or c < l * (1 - TOL_OHLC)
                or o > h * (1 + TOL_OHLC) or o < l * (1 - TOL_OHLC))
        if fora:
            if futuro:
                v.piorar(NAO_CONFIRMADO, f"barra de {_br(u[0])} incoerente (abertura ou fechamento fora da máxima e da mínima): mistura de contratos")
                v.descartar_ultima = True
            else:
                v.piorar(SUSPEITO, f"barra de {_br(u[0])} incoerente (fechamento fora da máxima e da mínima)")

    # 3) foto de um instante: amplitude minima em indice, commodity ou cambio
    med_amp = _mediana([(_num(b[2]) or 0) - (_num(b[3]) or 0) for b in anteriores
                        if _num(b[2]) is not None and _num(b[3]) is not None])
    if not provisoria and med_amp and h is not None and l is not None and (h - l) < AMPLITUDE_FOTO * med_amp:
        if classe in ("indice", "commodity") or futuro:
            v.piorar(NAO_CONFIRMADO, f"barra de {_br(u[0])} com amplitude de {h - l:.3f} "
                                     f"(mediana {med_amp:.3f}): foto de um instante, não o pregão")
            v.descartar_ultima = True
        elif classe != "fx":
            v.piorar(SUSPEITO, f"amplitude de {_br(u[0])} muito abaixo da média")

    # 4) a cotacao do proprio Yahoo, na MESMA data, desmente o fechamento da barra
    if u[0] not in confirmadas and e_a_ultima and dt_meta is not None and rmp and c and dt_meta.date().isoformat() == u[0] and not v.descartar_ultima:
        dif = rmp / c - 1.0
        if abs(dif) > META_DIVERGE:
            if futuro:
                v.piorar(SUSPEITO, f"cotação do Yahoo às {dt_meta:%H:%M} ({rmp:.2f}) difere {dif * 100:+.1f}% da barra: "
                                   "pode ser outro vencimento")
            else:
                v.piorar(NAO_CONFIRMADO, f"barra de {_br(u[0])} não bate com a cotação do Yahoo às "
                                         f"{dt_meta:%H:%M} ({_n(c)} contra {_n(rmp)}, {dif * 100:+.2f}%)")

    # 4b) cambio: a abertura do pregao seguinte denuncia fechamento parado. Em 23/09
    # a barra do USDBRL fechava em 5,0999 e a de 24/09 abria em 5,1625 (o dolar
    # tinha subido 1,28%); mercado continuo nao pula 1,2% entre um e outro
    if classe == "fx" and u[0] not in confirmadas and not v.descartar_ultima and c:
        depois = [b for b in todas if b[0] > u[0]]
        if depois and _num(depois[0][1]):
            salto = _num(depois[0][1]) / c - 1.0
            if abs(salto) > 0.005:
                v.piorar(NAO_CONFIRMADO, f"fechamento de {_br(u[0])} ({_n(c)}) não bate com a abertura "
                                         f"seguinte ({_n(_num(depois[0][1]))})")

    # 5) volume copiado da barra anterior: assinatura de barra de enchimento. O
    # fechamento costuma estar certo (18/09 e 22/09 do Brent); so o volume nao vale.
    if vol and _num(pen[6]) and vol == _num(pen[6]):
        v.volume_provisorio = True
        v.motivos.append(f"volume de {_br(u[0])} repetido do pregão anterior")

    # 6) buraco: a penultima barra nao e o pregao imediatamente anterior
    base = barras[-2] if not v.descartar_ultima else (barras[-3] if len(barras) >= 3 else None)
    alvo = u if not v.descartar_ultima else barras[-2]
    if base is not None:
        faltam = dias_sem_barra(mercado, base[0], alvo[0])
        if faltam:
            v.sem_barra = faltam
            v.dia_pregoes = len(faltam) + 1
            v.motivos.append(f"sem barra de {', '.join(_br(x) for x in faltam)}: a variação cobre "
                             f"{v.dia_pregoes} pregões")

    # 7) cripto: o dia (UTC) ainda nao acabou
    if mercado == "CRIPTO":
        agora_utc = agora.astimezone(timezone.utc)
        if alvo[0] == agora_utc.date().isoformat():
            v.parcial = True
            v.motivos.append(f"dia UTC em andamento ({agora_utc:%H:%M} UTC)")
    return v


def _br(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}" if iso and len(iso) >= 10 else str(iso)


def _n(x: float) -> str:
    return f"{x:,.4f}".replace(",", "X").replace(".", ",").replace("X", ".") if x < 20 else \
        f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _cidade(dados: dict) -> str:
    tz = str((dados or {}).get("tz") or "")
    return {"America/New_York": "Nova York", "America/Chicago": "Chicago", "Europe/London": "Londres"}.get(tz, tz or "UTC")


def confiavel(info: dict | None) -> bool:
    """Serie apta a virar alerta, destaque, push e frase causal: sem qualidade
    registrada (fixtures, testes antigos) conta como apta."""
    q = (info or {}).get("qualidade") or {}
    return q.get("status", OK) == OK and not q.get("parcial") and q.get("dia_pregoes", 1) == 1


def dia_valido(info: dict | None) -> bool:
    """A coluna 'dia' pode ser lida como um pregao: fresca, confiavel, um pregao so.
    Serie sem a barra do pregao esperado e velha em qualquer slot: na manha o esperado
    e o pregao de ontem, e antes a checagem so valia quando o esperado era hoje."""
    i = info or {}
    if not i.get("fresco", True):
        return False
    return confiavel(i)


def resumo(series_info: dict, universo=None) -> dict:
    """Para o manifest e o fechamento.json: o que nao esta ok, em portugues."""
    out = {"nao_confirmado": {}, "suspeito": {}, "dia_de_varios_pregoes": {}, "parcial": [], "descartadas": []}
    for id_, info in (series_info or {}).items():
        q = info.get("qualidade") or {}
        if not q:
            continue
        if q.get("status") == NAO_CONFIRMADO:
            out["nao_confirmado"][id_] = q.get("motivos", [])
        elif q.get("status") == SUSPEITO:
            out["suspeito"][id_] = q.get("motivos", [])
        if q.get("dia_pregoes", 1) > 1:
            out["dia_de_varios_pregoes"][id_] = q.get("sem_barra", [])
        if q.get("parcial"):
            out["parcial"].append(id_)
        if q.get("descartar_ultima"):
            out["descartadas"].append(f"{id_} {q.get('data_barra')}")
    return out


DRIVERS = ("BRENT", "USDBRL", "DXY", "MINERIO", "IBOV", "SPX", "VIX", "BTC")


def drivers(series_info: dict, janelas: dict) -> dict:
    """Os numeros que a Leitura da Mesa usa para explicar os outros: com status. A
    skill proibe frase causal com driver que nao esteja ok."""
    out = {}
    for d in DRIVERS:
        info = series_info.get(d)
        if info is None:
            continue
        j = janelas.get(d) or {}
        out[d] = {"ok": dia_valido(info), "data": j.get("data"), "ultimo": j.get("ultimo"),
                  "dia": j.get("dia") if dia_valido(info) else None,
                  "motivos": ((info.get("qualidade") or {}).get("motivos") or [])
                  + ([f"sem barra de {info.get('esperado')}"] if not info.get("fresco", True) else [])}
    return out


def marcador(j: dict, info: dict | None) -> tuple[str, bool]:
    """(rotulo curto para a linha da tabela, esconder o numero do dia).

    Um so vocabulario para card, painel e bloco monoespacado:
      "dado a confirmar"  -> a barra e de hoje mas o valor nao bate (cambio de 23/09): sem numero
      "dia dd/mm"         -> barra velha: o numero e do pregao dd/mm
      "2 pregões"         -> faltou barra: o numero cobre mais de um pregao
      "parcial"           -> cripto antes da meia-noite UTC
      "D-1"               -> minerio CME, que liquida com um pregao de atraso"""
    i = info or {}
    q = i.get("qualidade") or {}
    data = (j or {}).get("data") or ""
    ddmm = f"{data[8:10]}/{data[5:7]}" if len(data) >= 10 else data
    if q.get("status") == NAO_CONFIRMADO and not q.get("descartar_ultima"):
        return "dado a confirmar", True
    if not i.get("fresco", True):
        return f"dia {ddmm}", False
    if q.get("dia_pregoes", 1) > 1:
        return f"{q['dia_pregoes']} pregões", False
    if q.get("parcial"):
        return "parcial", False
    if i.get("defasado"):
        return f"D-1, {ddmm}", False
    return "", False
