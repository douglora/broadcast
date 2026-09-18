"""Fatos relevantes, comunicados ao mercado e avisos aos acionistas das companhias
do livro, pelo IPE (dados abertos da CVM). Fonte primaria: o PDF e lido por inteiro.

Casamento por Codigo_CVM (primario) ou nucleo do nome (fallback), como em
coletar_dados.coletar_cvm; o runner grava `empresas_casadas` para conferencia."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
import zipfile
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from livro.http import Cliente, HttpError

IPE_ZIP = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{ano}.zip"
IPE_CSV = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{ano}.csv"
GENERICAS = {"S", "A", "SA", "S.A.", "S/A", "HOLDING", "PARTICIPACOES", "CIA", "COMPANHIA", "DO", "DA", "DE",
             "DOS", "DAS", "E", "ON", "PN", "N1", "N2", "NM", "UNT", "BCO", "BANCO"}
CATEGORIAS_PADRAO = {"Fato Relevante": "atencao", "Comunicado ao Mercado": "info", "Aviso aos Acionistas": "info"}
# comunicado ao mercado so vira atencao com um destes no assunto
COMUNICADO_FORTE = re.compile(r"(?i)guidance|proje[cç]|aquisi[cç]|venda|dividend|jcp|juros sobre|recompra|resultado|"
                              r"oferta|emiss[aã]o|acordo|contrato|multa|processo|renuncia|ren[uú]ncia|elei[cç]|nomea")


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9 ]+", " ", t.upper())
    return re.sub(r"\s+", " ", t).strip()


def nucleo(nome: str) -> str:
    return " ".join(p for p in normalizar(nome).split() if p not in GENERICAS)


def baixar_ipe(cli: Cliente, ano: int) -> str | None:
    try:
        r = cli.get(IPE_ZIP.format(ano=ano), timeout=120)
        if r.status == 200 and r.content:
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                nome = next((n for n in z.namelist() if n.lower().endswith(".csv")), None)
                if nome:
                    return z.read(nome).decode("latin-1")
    except (HttpError, zipfile.BadZipFile, OSError):
        pass
    try:
        r = cli.get(IPE_CSV.format(ano=ano), timeout=60)
        return r.content.decode("latin-1") if r.status == 200 and r.content else None
    except HttpError:
        return None


def _campo(row: dict, *nomes: str) -> str:
    for n in nomes:
        for k, v in row.items():
            if k and k.strip().lower() == n.lower():
                return (v or "").strip()
    return ""


def data_iso(valor: str) -> str:
    """'2026-09-18 19:02:11' | '18/09/2026' | '2026-09-18T19:02' -> '2026-09-18'."""
    v = (valor or "").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", v)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", v)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return v[:10]


def diagnostico(texto: str, desde: date, amostra: str = "PETROBRAS") -> dict:
    """O que o arquivo tem: colunas, linhas, categorias na janela e amostra de uma
    companhia conhecida. Gravado em eventos/cvm.json para conferir o casamento."""
    from collections import Counter
    leitor = csv.DictReader(io.StringIO(texto), delimiter=";")
    cats, n, na_janela, amostras = Counter(), 0, 0, []
    max_entrega, max_ref, ultimos = "", "", []
    for row in leitor:
        n += 1
        entrega = data_iso(_campo(row, "Data_Entrega"))
        ref = data_iso(_campo(row, "Data_Referencia"))
        data = entrega or ref
        if entrega > max_entrega:
            max_entrega = entrega
        if ref > max_ref:
            max_ref = ref
        if data >= desde.isoformat():
            na_janela += 1
            cats[_campo(row, "Categoria")] += 1
        if amostra in normalizar(_campo(row, "Nome_Companhia")) and len(amostras) < 3:
            amostras.append({k: _campo(row, k) for k in ("Nome_Companhia", "Codigo_CVM", "Categoria", "Data_Entrega", "Data_Referencia")})
        ultimos.append((entrega, _campo(row, "Nome_Companhia")[:40], _campo(row, "Categoria")))
    ultimos = sorted(ultimos, reverse=True)[:5]
    return {"colunas": leitor.fieldnames, "linhas": n, "na_janela": na_janela, "max_data_entrega": max_entrega,
            "max_data_referencia": max_ref, "ultimos_5": ultimos,
            "categorias_janela": dict(cats.most_common(12)), "amostra": amostras}


def protocolo_de(link: str) -> str:
    q = parse_qs(urlparse(link).query)
    for k, v in q.items():
        if k.lower().startswith("numeroprotocolo") and v:
            return v[0]
    return ""


def parse_ipe(texto: str, alvos: dict, desde: date, categorias: dict | None = None) -> tuple[list[dict], dict]:
    """Documentos das companhias do livro entregues a partir de `desde`.
    alvos: {ativo: {codigo, nomes: [nucleos]}}. Devolve (docs, empresas_casadas)."""
    categorias = categorias or CATEGORIAS_PADRAO
    por_codigo = {str(v.get("codigo")): a for a, v in alvos.items() if v.get("codigo")}
    por_nome = {}
    for a, v in alvos.items():
        for n in v.get("nomes", []):
            por_nome[nucleo(n)] = a
    docs, casadas = [], {}
    leitor = csv.DictReader(io.StringIO(texto), delimiter=";")
    for row in leitor:
        data = data_iso(_campo(row, "Data_Entrega") or _campo(row, "Data_Referencia"))
        if not data or data < desde.isoformat():
            continue
        cat = _campo(row, "Categoria")
        if cat not in categorias:
            continue
        empresa = _campo(row, "Nome_Companhia")
        codigo = _campo(row, "Codigo_CVM", "CD_CVM").lstrip("0")
        ativo = por_codigo.get(codigo) or por_nome.get(nucleo(empresa))
        if not ativo:
            continue
        casadas.setdefault(ativo, set()).add(empresa)
        assunto = _campo(row, "Assunto")
        link = _campo(row, "Link_Download")
        sev = categorias[cat]
        if cat == "Comunicado ao Mercado" and COMUNICADO_FORTE.search(assunto or ""):
            sev = "atencao"
        prot = protocolo_de(link) or hashlib.sha1(f"{empresa}|{data}|{assunto}".encode()).hexdigest()[:8]
        docs.append({
            "id": f"CVM-{ativo}-{prot}", "ativo": ativo, "empresa": empresa, "codigo": codigo, "categoria": cat,
            "tipo": _campo(row, "Tipo"), "especie": _campo(row, "Especie"), "assunto": assunto[:300],
            "data": data, "entregue_em": _campo(row, "Data_Entrega"), "link": link, "protocolo": prot,
            "severidade": sev, "versao": _campo(row, "Versao"),
        })
    docs.sort(key=lambda d: (d["entregue_em"], d["id"]), reverse=True)
    return docs, {a: sorted(v) for a, v in casadas.items()}


def texto_pdf(cli: Cliente, link: str, max_bytes: int = 6_000_000, max_chars: int = 8000) -> str | None:
    """Texto do PDF do IPE (pypdf). Devolve None se nao baixar, nao for PDF ou for
    imagem sem texto."""
    if not link:
        return None
    try:
        r = cli.get(link, timeout=60)
    except HttpError:
        return None
    if r.status != 200 or not r.content or len(r.content) > max_bytes:
        return None
    return texto_de_pdf_bytes(r.content, max_chars)


def texto_de_pdf_bytes(dados: bytes, max_chars: int = 8000) -> str | None:
    if not dados.startswith(b"%PDF"):
        return None
    try:
        from pypdf import PdfReader  # type: ignore
        leitor = PdfReader(io.BytesIO(dados))
        partes = []
        for pagina in leitor.pages[:12]:
            partes.append(pagina.extract_text() or "")
        txt = re.sub(r"[ \t]+", " ", "\n".join(partes))
        txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
        return txt[:max_chars] or None
    except Exception:
        return None


def coletar(alvos: dict, cli: Cliente | None = None, hoje: date | None = None, dias: int = 3,
            categorias: dict | None = None, vistos: dict | None = None, max_pdf: int = 8) -> dict:
    """Documentos novos (id nao visto) das companhias do livro nos ultimos `dias`,
    com o texto do PDF para fato relevante e comunicado forte."""
    cli = cli or Cliente(impersonate=False)
    hoje = hoje or datetime.now(timezone.utc).date()
    vistos = dict(vistos or {})
    desde = hoje - timedelta(days=dias)
    anos = {hoje.year, desde.year}
    docs, casadas, falhas, diag = [], {}, {}, {}
    for ano in sorted(anos):
        texto = baixar_ipe(cli, ano)
        if not texto:
            falhas[f"ipe_{ano}"] = "IPE indisponivel"
            continue
        try:
            diag[str(ano)] = diagnostico(texto, desde)
        except Exception as e:
            diag[str(ano)] = {"erro": f"{type(e).__name__}: {str(e)[:80]}"}
        d, c = parse_ipe(texto, alvos, desde, categorias)
        docs += d
        for a, nomes in c.items():
            casadas.setdefault(a, [])
            casadas[a] = sorted(set(casadas[a]) | set(nomes))
    novos = [d for d in docs if d["id"] not in vistos]
    lidos = 0
    for d in novos:
        d["texto"] = None
        if lidos < max_pdf and (d["categoria"] == "Fato Relevante" or d["severidade"] == "atencao"):
            d["texto"] = texto_pdf(cli, d["link"])
            lidos += 1
        vistos[d["id"]] = {"data": d["data"]}
    limite = (hoje - timedelta(days=15)).isoformat()
    vistos = {k: v for k, v in vistos.items() if (v.get("data") or "9999") >= limite}
    return {"docs": novos, "todos": len(docs), "empresas_casadas": casadas, "falhas": falhas, "vistos": vistos,
            "diagnostico": diag, "coletado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
