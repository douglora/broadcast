"""Treasury.gov: par yields CMT diarios (2y, 5y, 10y, 30y) do feed XML mensal.

    https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml
        ?data=daily_treasury_yield_curve&field_tdr_date_value_month=YYYYMM

Um <entry> por pregao; campos BC_2YEAR/BC_5YEAR/BC_10YEAR/BC_30YEAR (com variantes
BC_2_YEAR...). O dado do dia sai no fim da tarde de NY (~17h30-18h30 BRT; uma
hora mais tarde apos 01/11). Fallback: FRED fredgraph.csv (DGS2/DGS5/DGS10/DGS30), T+1."""

from __future__ import annotations

from datetime import date, datetime
from xml.etree import ElementTree

from livro.http import Cliente, HttpError

XML_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={serie}"
CAMPOS = {"2y": ("BC_2YEAR", "BC_2_YEAR"), "5y": ("BC_5YEAR", "BC_5_YEAR"),
          "10y": ("BC_10YEAR", "BC_10_YEAR"), "30y": ("BC_30YEAR", "BC_30_YEAR")}
FRED = {"2y": "DGS2", "5y": "DGS5", "10y": "DGS10", "30y": "DGS30"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_xml(conteudo: bytes) -> list[list]:
    """-> [[data, y2, y5, y10, y30], ...] ordenado por data."""
    raiz = ElementTree.fromstring(conteudo)
    linhas = {}
    for el in raiz.iter():
        if _local(el.tag) != "properties":
            continue
        valores = {_local(c.tag): (c.text or "").strip() for c in el}
        data_raw = valores.get("NEW_DATE") or valores.get("Date")
        if not data_raw:
            continue
        d = data_raw[:10]
        linha = [d]
        for prazo in ("2y", "5y", "10y", "30y"):
            v = None
            for nome in CAMPOS[prazo]:
                if valores.get(nome):
                    try:
                        v = float(valores[nome])
                    except ValueError:
                        v = None
                    break
            linha.append(v)
        if any(x is not None for x in linha[1:]):
            linhas[d] = linha
    return [linhas[k] for k in sorted(linhas)]


def baixar_mes(cli: Cliente, ano: int, mes: int) -> list[list]:
    r = cli.get_ok(XML_URL, params={"data": "daily_treasury_yield_curve",
                                    "field_tdr_date_value_month": f"{ano:04d}{mes:02d}"}, timeout=40)
    return parse_xml(r.content)


def parse_fred_csv(texto: str) -> dict:
    out = {}
    for linha in texto.splitlines()[1:]:
        partes = linha.strip().split(",")
        if len(partes) == 2 and partes[1] not in (".", ""):
            try:
                out[partes[0]] = float(partes[1])
            except ValueError:
                pass
    return out


def mesclar(historico: list[list], novas: list[list]) -> list[list]:
    por_data = {h[0]: h for h in historico or []}
    for n in novas:
        por_data[n[0]] = n
    return [por_data[k] for k in sorted(por_data)]


def coletar(historico: list[list] | None, cli: Cliente | None = None, meses: int = 2,
            hoje: date | None = None) -> dict:
    """Baixa os ultimos `meses` do XML (24 no backfill) e mescla com o historico."""
    cli = cli or Cliente()
    hoje = hoje or date.today()
    novas, falhas = [], []
    ano, mes = hoje.year, hoje.month
    for _ in range(meses):
        try:
            novas += baixar_mes(cli, ano, mes)
        except (HttpError, ElementTree.ParseError, ValueError) as e:
            falhas.append(f"{ano}-{mes:02d}: {e}")
        mes -= 1
        if mes == 0:
            ano, mes = ano - 1, 12
    hist = mesclar(historico or [], novas)
    fonte = "Treasury.gov CMT"
    if not novas:
        # fallback FRED (T+1)
        try:
            colunas = {}
            for prazo, serie in FRED.items():
                r = cli.get_ok(FRED_URL.format(serie=serie), timeout=40)
                colunas[prazo] = parse_fred_csv(r.text)
            datas = sorted(set().union(*[set(c) for c in colunas.values()]))
            linhas = [[d, colunas["2y"].get(d), colunas["5y"].get(d), colunas["10y"].get(d), colunas["30y"].get(d)]
                      for d in datas if d >= "2024-01-01"]
            hist = mesclar(hist, linhas)
            fonte = "FRED DGS (T+1)"
        except Exception as e:
            falhas.append(f"FRED: {e}")
    return {"fonte": fonte, "prazos": ["2y", "5y", "10y", "30y"], "historico": hist[-800:],
            "ultima_data": hist[-1][0] if hist else None, "falhas": falhas,
            "coletado_em": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}
