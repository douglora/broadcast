"""Banco Central: series SGS (PTAX, Selic meta, IPCA mensal e 12m, CDI) e
expectativas do Focus (Olinda OData). Tudo sem chave."""

from __future__ import annotations

from datetime import datetime

from livro.http import Cliente, HttpError

SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados/ultimos/{n}?formato=json"
SERIES = {
    "ptax_venda": (1, "Dolar PTAX venda", "R$"),
    "selic_meta": (432, "Meta Selic", "% a.a."),
    "ipca_mes": (433, "IPCA mensal", "%"),
    "ipca_12m": (13522, "IPCA 12 meses", "%"),
    "cdi_dia": (12, "CDI diario", "% a.d."),
}
FOCUS_URL = ("https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"
             "ExpectativasMercadoAnuais?$top=200&$orderby=Data%20desc&$format=json"
             "&$filter=Indicador%20eq%20'{ind}'%20and%20baseCalculo%20eq%200")


def parse_sgs(rows: list) -> list[dict]:
    out = []
    for row in rows or []:
        try:
            d = datetime.strptime(row["data"], "%d/%m/%Y").strftime("%Y-%m-%d")
            out.append({"data": d, "valor": float(str(row["valor"]).replace(",", "."))})
        except Exception:
            continue
    return out


def coletar_sgs(cli: Cliente | None = None, n: int = 10) -> dict:
    cli = cli or Cliente()
    out, falhas = {}, []
    for chave, (codigo, nome, unidade) in SERIES.items():
        try:
            r = cli.get_ok(SGS_URL.format(codigo=codigo, n=n), timeout=30)
            pts = parse_sgs(r.json())
            if pts:
                out[chave] = {"nome": nome, "unidade": unidade, "serie": pts, **pts[-1]}
        except (HttpError, ValueError) as e:
            falhas.append(f"{chave}: {e}")
    return {"series": out, "falhas": falhas, "coletado_em": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}


def parse_focus(rows: list, indicador: str) -> dict:
    """Mediana mais recente por ano de referencia: {ano: {mediana, data}}."""
    out = {}
    for row in rows or []:
        try:
            ano = str(row.get("DataReferencia"))
            if ano in out:
                continue
            out[ano] = {"mediana": float(row.get("Mediana")), "media": row.get("Media"),
                        "data": row.get("Data"), "respondentes": row.get("numeroRespondentes")}
        except Exception:
            continue
    return {"indicador": indicador, "por_ano": out}


def coletar_focus(cli: Cliente | None = None) -> dict:
    cli = cli or Cliente()
    out, falhas = {}, []
    for ind in ("IPCA", "Selic", "C%C3%A2mbio"):
        try:
            r = cli.get_ok(FOCUS_URL.format(ind=ind), timeout=40)
            nome = "Cambio" if ind.startswith("C") else ind
            out[nome] = parse_focus((r.json() or {}).get("value") or [], nome)
        except (HttpError, ValueError) as e:
            falhas.append(f"focus {ind}: {e}")
    return {"expectativas": out, "falhas": falhas, "coletado_em": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}
