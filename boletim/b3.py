"""Rotas do Boletim Diario do Mercado (BDI) da B3. Nada aqui exige cadastro.

O que a pagina https://www.b3.com.br/.../boletim-diario-do-mercado/ mostra e um iframe
do aplicativo https://arquivos.b3.com.br/bdi/tabelas, e e dele que saem as rotas:

  situacao  GET  /bdi/download/status?dateRef=AAAA-MM-DD
            cadernos em PDF (completo BDI_00 e subcapitulos), situacao e hora de cada um
  PDF       GET  /bdi/download/bdi/AAAA-MM-DD/BDI_NN[-S]_AAAAMMDD.pdf
            o completo passa de 50 MB e 1.800 paginas: so o link vai para o branch
  tabela    POST /bdi/table/<Nome>/<data>/<data>/<pagina>/<linhas>   corpo {}
            JSON tipado; no maximo 1000 linhas por pagina (2000 devolve 400). A paginacao repete e
            pula linhas: so a primeira pagina e usada (situacao, hora, numero de paginas)
  inteira   POST /bdi/table/export   corpo {"Name", "Date", "FinalDate", "ClientId": "", "Filters": {}}
            a tabela toda numa resposta (92 mil linhas em 5 s); e por aqui que vem tabela grande
            ?filter=<base64 do codigo em maiusculas> devolve so as linhas daquele codigo
            (casamento exato na coluna-chave; e a caixa de busca do aplicativo)
  catalogo  GET  /bdi/table/classifications     arvore de capitulos e tabelas
  avisos    GET  /bdi/table/classification/<id>/informations?date=AAAA-MM-DD
  arquivo   GET  /api/download/requestname?fileName=<Nome>&date=AAAA-MM-DD -> token
            GET  /api/download/?token=<token>   CSV ';' com cabecalho tecnico
            (respondem: TradeInformationConsolidated, ...AfterHours,
             InstrumentsConsolidated, DerivativesOpenPosition, MarginScenarioLiquidAssets)

Tabela que a B3 ainda nao publicou volta vazia com situacao `aguardando` ou `atrasado`,
nunca com o dado do pregao anterior. Horas sao as que a B3 informa (hora de Brasilia).
"""

from __future__ import annotations

import base64
import csv
import io
import json
import os
import re
import unicodedata
from datetime import date

from livro.http import Cliente, HttpError

BDI = "https://arquivos.b3.com.br/bdi"
PDF_URL = BDI + "/download/bdi/{iso}/{arquivo}"
TOKEN_URL = "https://arquivos.b3.com.br/api/download/requestname"
DOWNLOAD_URL = "https://arquivos.b3.com.br/api/download/"
TAKE = 1000

# ETableStatus do aplicativo
SITUACAO = {0: "indefinido", 1: "aguardando", 2: "publicando", 3: "atrasado",
            4: "publicado", 5: "republicado", 6: "ignorado"}
PRONTA = ("publicado", "republicado")
JSON_HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}


class B3Erro(Exception):
    """A B3 respondeu fora do esperado (codigo HTTP, corpo vazio, formato novo)."""


def _data(v):
    """'2026-09-29T00:00:00' -> '2026-09-29'; hora diferente de zero fica como veio."""
    if isinstance(v, str) and len(v) >= 19 and v[10:19] == "T00:00:00" and v[4] == "-":
        return v[:10]
    return v


def _json(r, onde: str):
    if r.status != 200:
        raise B3Erro(f"{onde}: HTTP {r.status}")
    if not r.content:
        raise B3Erro(f"{onde}: resposta vazia")
    try:
        return r.json()
    except Exception as e:
        raise B3Erro(f"{onde}: nao e JSON ({type(e).__name__})")


# ------------------------------------------------------------------ cadernos

def situacao_cadernos(cli: Cliente, d: date) -> dict:
    """Cadernos do pregao: situacao, hora da ultima atualizacao e link do PDF."""
    j = _json(cli.get(f"{BDI}/download/status", params={"dateRef": d.isoformat()}, timeout=40), "status")

    def link(url: str):
        nome = os.path.basename(url or "")
        return (nome, PDF_URL.format(iso=d.isoformat(), arquivo=nome)) if nome else ("", "")

    cadernos = []
    for c in sorted(j.get("chapters") or [], key=lambda x: x.get("order") or 0):
        arquivo, url = link(c.get("url"))
        cadernos.append({"id": c.get("id"), "nome": c.get("name"), "pai": c.get("parentId"),
                         "situacao": (c.get("statusName") or "").lower(), "errata": bool(c.get("errata")),
                         "atualizado_em": c.get("lastUpdateDate"), "arquivo": arquivo, "pdf": url})
    arquivo, url = link(j.get("url"))
    return {"pregao": d.isoformat(), "situacao": (j.get("statusName") or "").lower(),
            "errata": bool(j.get("errata")), "atualizado_em": j.get("lastUpdateDate"),
            "completo": {"arquivo": arquivo, "pdf": url}, "cadernos": cadernos}


# ------------------------------------------------------------------ tabelas

def normalizar(t: dict) -> dict:
    """Tabela do aplicativo -> {nome, titulo, colunas, linhas, filhos}. Colunas de grupo
    (cabecalho de duas linhas) somem e o titulo do grupo entra no titulo da coluna."""
    cols = t.get("columns") or []
    grupos = {c.get("id"): (c.get("friendlyNamePt") or "").strip() for c in cols if c.get("isGroup")}
    folhas = [(i, c) for i, c in enumerate(cols) if not c.get("isGroup")]
    colunas = []
    for _, c in folhas:
        titulo = (c.get("friendlyNamePt") or "").strip()
        if c.get("parentId") in grupos:
            titulo = f"{grupos[c['parentId']]}: {titulo}"
        colunas.append({"nome": (c.get("name") or "").strip(), "titulo": titulo})
    linhas = [[_data(v[i]) if i < len(v) else None for i, _ in folhas] for v in (t.get("values") or [])]
    textos = [re.sub(r"\s+", " ", x.get("textPt") or "").strip() for x in (t.get("texts") or [])]
    out = {"nome": t.get("name"), "titulo": (t.get("friendlyNamePt") or "").strip(),
           "sla": (t.get("configuration") or {}).get("SLA"), "paginas": t.get("pageCount") or 0,
           "colunas": colunas, "linhas": linhas, "texto": [x for x in textos if x]}
    filhos = [normalizar(f) for f in (t.get("children") or [])]
    if filhos:
        out["filhos"] = filhos
    return out


def tabela(cli: Cliente, nome: str, d: date, max_paginas: int = 1, filtro: str | None = None) -> dict:
    """Uma tabela do BDI no pregao d, inteira.

    A primeira pagina da a situacao, a hora e o numero de paginas. Tabela de mais de uma pagina
    vem pela exportacao (`POST /bdi/table/export`), que devolve tudo numa resposta so. A leitura
    pagina a pagina NAO e confiavel: em 30/09/2026 a tabela `Trade` devolveu 33.681 linhas com so
    23.129 negocios unicos (linhas repetidas entre paginas e outras de fora, entre elas um negocio
    de R$ 1,1 bi). `truncada` avisa quando ha mais paginas que o teto e a tabela nao foi baixada.
    `filtro` e o codigo exato (ticker, codigo IF) na coluna-chave; so vale para a primeira pagina.
    """
    iso = d.isoformat()
    busca = "?filter=" + base64.b64encode(filtro.upper().encode()).decode() if filtro else ""
    r = cli.post(f"{BDI}/table/{nome}/{iso}/{iso}/1/{TAKE}{busca}", data="{}", headers=JSON_HEADERS, timeout=90)
    j = _json(r, f"tabela {nome}")
    if not isinstance(j.get("table"), dict):
        raise B3Erro(f"tabela {nome}: resposta sem `table`")
    out = normalizar(j["table"])
    out["situacao"] = SITUACAO.get(j.get("status"), str(j.get("status")))
    out["atualizado_em"] = j.get("lastUpdateDate")
    out["truncada"] = out["paginas"] > max_paginas
    if out["paginas"] > 1 and not out["truncada"] and not filtro:
        corpo = json.dumps({"Name": nome, "Date": iso, "FinalDate": iso, "ClientId": "", "Filters": {}})
        inteira = _json(cli.post(f"{BDI}/table/export", data=corpo, headers=JSON_HEADERS, timeout=300), f"exportacao de {nome}")
        linhas = normalizar(inteira)["linhas"]
        if len(linhas) < len(out["linhas"]):
            raise B3Erro(f"exportacao de {nome}: {len(linhas)} linhas, menos que a primeira pagina ({len(out['linhas'])})")
        out["linhas"] = linhas
    return out


def registros(tab: dict) -> list[dict]:
    """Linhas de uma tabela normalizada como dicionarios pelo nome tecnico da coluna."""
    nomes = [c["nome"] for c in tab.get("colunas") or []]
    return [dict(zip(nomes, linha)) for linha in tab.get("linhas") or []]


def filho(tab: dict, nome: str) -> dict | None:
    """Procura uma tabela filha pelo nome, em qualquer profundidade."""
    for f in tab.get("filhos") or []:
        if f.get("nome") == nome:
            return f
        achou = filho(f, nome)
        if achou:
            return achou
    return None


def folhas(tab: dict):
    """Todas as tabelas com linhas dentro de uma tabela de grupo."""
    if tab.get("linhas"):
        yield tab
    for f in tab.get("filhos") or []:
        yield from folhas(f)


def cadastro_balcao(cli: Cliente, codigo: str, d: date) -> dict | None:
    """Cadastro de um papel de renda fixa de balcao (debenture, CRI, CRA) pelo codigo IF.
    E daqui que sai se a debenture e incentivada (Lei 12.431), o indexador e o vencimento."""
    for r in registros(tabela(cli, "InstrumentRegistration", d, filtro=codigo)):
        if (r.get("TckrSymb") or "").upper() == codigo.upper():
            # so o que a leitura usa: o cache guarda milhares de papeis
            return {"tipo": r.get("InstrumentType"), "incentivada": str(r.get("Encouraged")).lower() == "true",
                    "indexador": (r.get("Indexer") or "").strip() or None, "pct_indexador": r.get("IndexerPercentage"),
                    "taxa": r.get("AdditionalFee"), "vencimento": r.get("Maturity")}
    return None


def catalogo(cli: Cliente) -> list[dict]:
    """Capitulos e tabelas que o BDI expoe hoje. Serve para notar tabela nova ou removida."""
    j = _json(cli.get(f"{BDI}/table/classifications", timeout=60), "classifications")
    por_id = {c.get("id"): c for c in j}

    def caminho(c):
        partes = []
        while c:
            partes.append(c.get("name") or "")
            c = por_id.get(c.get("parentId"))
        return " > ".join(reversed(partes))

    out = []
    for c in j:
        for nome, meta in (c.get("tables") or {}).items():
            out.append({"capitulo": caminho(c), "capitulo_id": c.get("id"), "tabela": nome,
                        "titulo": (meta.get("friendlyNamePt") or "").strip(),
                        "historico": bool(meta.get("hasHistory")), "limite": meta.get("limitDate") or ""})
    return sorted(out, key=lambda x: (x["capitulo"], x["tabela"]))


def capitulos(cli: Cliente) -> list[dict]:
    j = _json(cli.get(f"{BDI}/table/classifications", timeout=60), "classifications")
    return [{"id": c.get("id"), "nome": c.get("name")} for c in j]


def informativos(cli: Cliente, capitulo_id: str, d: date) -> list[dict]:
    """Leiloes, comunicados e editais anexados a um capitulo no pregao."""
    j = _json(cli.get(f"{BDI}/table/classification/{capitulo_id}/informations",
                      params={"date": d.isoformat()}, timeout=40), "informations")
    out = []
    for s in j.get("sections") or []:
        for i in s.get("informations") or []:
            out.append({"secao": s.get("name"), "titulo": (i.get("titlePt") or "").strip(),
                        "data": _data(i.get("dateRef")), "vence": _data(i.get("dueDate")),
                        "arquivo": i.get("fileName"), "paginas": [i.get("startPage"), i.get("endPage")],
                        "link": f"{BDI}/download/bdi-files/{d.isoformat()}/{i.get('fileName')}" if i.get("fileName") else ""})
    return out


# ------------------------------------------------------------------ arquivos (API de download)

def arquivo(cli: Cliente, nome: str, d: date) -> tuple[str, dict]:
    """CSV da API de download. Devolve (texto, meta). Levanta B3Erro se o dia nao tem o arquivo."""
    r = cli.get(TOKEN_URL, params={"fileName": nome, "date": d.isoformat()}, timeout=40)
    if r.status != 200:
        raise B3Erro(f"arquivo {nome}: token HTTP {r.status}")
    try:
        corpo = r.json() or {}
    except Exception:
        raise B3Erro(f"arquivo {nome}: token nao e JSON")
    if not corpo.get("token"):
        raise B3Erro(f"arquivo {nome}: sem token")
    r2 = cli.get(DOWNLOAD_URL, params={"token": corpo["token"]}, timeout=240)
    if r2.status != 200:
        raise B3Erro(f"arquivo {nome}: download HTTP {r2.status}")
    try:
        texto = r2.content.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = r2.content.decode("latin-1")
    return texto, {"arquivo": ((corpo.get("file") or {}).get("name") or nome), "bytes": len(r2.content)}


def ler_csv(texto: str) -> tuple[list[str], list[dict]]:
    """(linhas antes do cabecalho, registros). O cabecalho e a primeira linha que comeca por RptDt."""
    linhas = texto.splitlines()
    inicio = next((i for i, l in enumerate(linhas[:6]) if l.startswith("RptDt")), None)
    if inicio is None:
        raise B3Erro("CSV sem cabecalho RptDt")
    return linhas[:inicio], list(csv.DictReader(io.StringIO("\n".join(linhas[inicio:])), delimiter=";"))


def num(v):
    """Numero do CSV da B3 ('5215,253') ou valor ja numerico. Vazio -> None."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if not s or s == "=":
        return 0.0 if s == "=" else None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


_RUIDO = re.compile(r"\b(S\.?/?A\.?|CIA\.?|COMPANHIA|HOLDING|PARTICIPACOES|DE|DO|DA|E)\b")


def nome_curto(s: str, limite: int = 34) -> str:
    """'CEMIG DISTRIBUICAO S/A' -> 'Cemig Distribuicao'; corta com reticencias no limite."""
    s = " ".join(str(s or "").replace(" S.A.", "").replace(" S/A.", "").replace(" S/A", "").replace(" S.A", "").split()).title()
    for a, b in ((" De ", " de "), (" Do ", " do "), (" Da ", " da "), (" E ", " e "), (" Dos ", " dos "), (" Das ", " das ")):
        s = s.replace(a, b)
    return s if len(s) <= limite else s[:limite - 1].rstrip() + "…"


def chave_empresa(nome: str) -> str:
    """Nome de empresa reduzido para casar tabelas que nao trazem codigo (ADR, proventos)."""
    s = sem_acento(nome).upper()
    s = re.sub(r"[^A-Z0-9 ]+", " ", _RUIDO.sub(" ", s.replace("S/A", " ").replace("S.A.", " ").replace("S.A", " ")))
    return " ".join(_RUIDO.sub(" ", s).split())
