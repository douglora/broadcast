#!/usr/bin/env python3
"""Coletor do Boletim Diario do Mercado da B3 (BDI).

Roda no GitHub Actions (internet aberta; a sessao do Claude nao alcanca a B3) e
grava em boletim_b3/ no branch dados:

  boletim_b3/<AAAA-MM-DD>/pdf/BDI_<NN>[-<S>].pdf   cadernos do boletim, como a B3 publica
  boletim_b3/<AAAA-MM-DD>/pdf/BDI_<NN>[-<S>].txt   texto extraido de cada caderno
  boletim_b3/<AAAA-MM-DD>/arquivos/<Nome>.csv      arquivos do boletim (api/download), quando pequenos
  boletim_b3/<AAAA-MM-DD>/index.json               o que veio do pregao: cadernos, arquivos, tamanhos, horas
  boletim_b3/descoberta/                           paginas e endpoints que a B3 expoe (validacao do coletor)
  boletim_b3/manifest.json                         ultima rodada: o que veio e o que falhou

URLs (B3, sem cadastro):
  pagina   https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/consultas/boletim-diario/boletim-diario-do-mercado/
  cadernos https://arquivos.b3.com.br/bdi/download/bdi/AAAA-MM-DD/BDI_NN[-S]_AAAAMMDD.pdf
  arquivos https://arquivos.b3.com.br/api/download/requestname?fileName=<Nome>&date=AAAA-MM-DD -> token
           https://arquivos.b3.com.br/api/download/?token=<token> -> CSV ';'

A sessao do Claude le com `python3 mesa.py boletim`.
Uso: python boletim_b3.py --saida dados_branch/boletim_b3 [--data AAAA-MM-DD] [--dias 1] [--partes descoberta,pdf,arquivos]
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urljoin

from livro import relogios
from livro.http import Cliente, HttpError

PAGINA = ("https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/"
          "consultas/boletim-diario/boletim-diario-do-mercado/")
PESQUISA = ("https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/"
            "historico/boletins-diarios/pesquisa-por-pregao/pesquisa-por-pregao/")
BDI_SPA = ("https://arquivos.b3.com.br/bdi/", "https://arquivos.b3.com.br/bdi/tabelas?lang=pt-BR")
PDF_URL = "https://arquivos.b3.com.br/bdi/download/bdi/{iso}/{nome}_{compacta}.pdf"
TOKEN_URL = "https://arquivos.b3.com.br/api/download/requestname"
DOWNLOAD_URL = "https://arquivos.b3.com.br/api/download/"

# Cadernos: BDI_NN e as secoes BDI_NN-S. Vistos em 2025/26: 01, 02, 02-0, 03-1, 03-3, 03-4, 05, 07.
CADERNOS = range(0, 13)
SECOES = range(0, 10)

# Arquivos do boletim pela API de download. TradeInformationConsolidated ja e usado
# pelo livro (DI futuro); os demais sao candidatos que a rodada de descoberta valida.
ARQUIVOS = (
    "TradeInformationConsolidated", "TradeInformationConsolidatedAfterHours", "InstrumentsConsolidated",
    "LendingOpenPosition", "LendingTradesConsolidated", "DerivativesOpenPosition", "EconomicIndicatorPrice",
    "OTCTradeInformationConsolidated", "OTCInstrumentsConsolidated", "MarginScenarioLiquidAssets",
    "PriceReport", "IndexComposition", "InvestorParticipation", "ParticipantsTradeInformation",
    "OptionsOpenPosition", "SecuritiesLendingPosition", "LoanBalance", "ForwardOpenPosition",
    "FutureOpenPosition", "SwapOpenPosition", "DailyBulletin", "BDI",
)
LIMITE_CSV_INTEIRO = 3_000_000      # acima disso grava so cabecalho e amostra
RX_URL = re.compile(r"""(?:https?:)?//[^\s"'<>()\\]+|["'](/[A-Za-z0-9_\-./{}$?=&:]{3,})["']""")
RX_PALAVRAS = re.compile(r"bdi|download|table|tabela|api/|csv|pdf|xlsx|zip|token|requestname", re.I)


def agora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gravar(caminho: str, conteudo, binario: bool = False) -> None:
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    if binario:
        with open(caminho, "wb") as f:
            f.write(conteudo)
    else:
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(conteudo if isinstance(conteudo, str) else json.dumps(conteudo, ensure_ascii=False, indent=1))


def texto_pdf(dados: bytes) -> tuple[str, int]:
    try:
        from pypdf import PdfReader
        leitor = PdfReader(io.BytesIO(dados))
        paginas = [(p.extract_text() or "") for p in leitor.pages]
        return "\n\f\n".join(paginas), len(paginas)
    except Exception as e:
        return f"[texto ilegivel: {type(e).__name__}: {e}]", 0


def pregoes(data_ini: date, n: int) -> list[date]:
    """n pregoes B3 terminando em data_ini (ou no dia util anterior), do mais novo ao mais velho."""
    out, d = [], relogios.ultimo_dia_util("B3", data_ini)
    while len(out) < n:
        out.append(d)
        d = relogios.dia_util_anterior("B3", d)
    return out


# ------------------------------------------------------------------ descoberta

def _urls(texto: str, base: str) -> list[str]:
    achados = set()
    for m in RX_URL.finditer(texto):
        u = m.group(1) or m.group(0)
        if u.startswith("//"):
            u = "https:" + u
        if RX_PALAVRAS.search(u):
            achados.add(urljoin(base, u) if u.startswith("/") else u)
    return sorted(achados)


def _strings_js(js: str) -> list[str]:
    """Literais de string do bundle que parecem rota, tabela ou arquivo."""
    lits = set(re.findall(r"""["'`]([^"'`\n]{3,160})["'`]""", js))
    return sorted(s for s in lits if RX_PALAVRAS.search(s) or re.fullmatch(r"[A-Z][A-Za-z]{6,60}", s))


def _janelas(js: str, termo: str, raio: int = 220, max_n: int = 40) -> list[str]:
    out = []
    for m in re.finditer(re.escape(termo), js):
        out.append(js[max(0, m.start() - raio): m.end() + raio].replace("\n", " "))
        if len(out) >= max_n:
            break
    return out


def descobrir(cli: Cliente, saida: str) -> dict:
    """Abre a pagina do boletim e o aplicativo do BDI, segue iframes e scripts e guarda
    as rotas que aparecem. E o que valida o coletor quando a B3 muda o site."""
    pasta = os.path.join(saida, "descoberta")
    rel: dict = {"paginas": {}, "scripts": {}, "falhas": []}
    fila = [PAGINA, PESQUISA, *BDI_SPA]
    vistas: set = set()
    while fila and len(vistas) < 12:
        url = fila.pop(0)
        if url in vistas:
            continue
        vistas.add(url)
        try:
            r = cli.get(url, headers={"Accept": "text/html,application/xhtml+xml,*/*"}, timeout=40)
        except HttpError as e:
            rel["falhas"].append(f"{url}: {e.body[:120]}")
            continue
        html = r.text
        nome = re.sub(r"[^A-Za-z0-9]+", "_", url.split("//", 1)[-1])[:90]
        gravar(os.path.join(pasta, f"{nome}.html"), html)
        iframes = [urljoin(r.url or url, s) for s in re.findall(r"<iframe[^>]+src=[\"']([^\"']+)", html, re.I)]
        scripts = [urljoin(r.url or url, s) for s in re.findall(r"<script[^>]+src=[\"']([^\"']+)", html, re.I)]
        rel["paginas"][url] = {"status": r.status, "url_final": r.url, "bytes": len(r.content),
                               "titulo": (re.search(r"<title>(.*?)</title>", html, re.S | re.I) or [None, ""])[1].strip()[:200],
                               "iframes": iframes, "scripts": scripts, "urls": _urls(html, r.url or url)[:300]}
        fila.extend(i for i in iframes if i not in vistas)
        for s in scripts:
            if "arquivos.b3.com.br" not in s and "boletim" not in s.lower() and "bdi" not in s.lower():
                continue
            if s in rel["scripts"]:
                continue
            try:
                rs = cli.get(s, timeout=60)
            except HttpError as e:
                rel["falhas"].append(f"{s}: {e.body[:120]}")
                continue
            js = rs.text
            info = {"status": rs.status, "bytes": len(rs.content), "urls": _urls(js, s)[:400],
                    "strings": _strings_js(js)[:1500]}
            for termo in ("table", "download", "requestname", "/bdi", "api/", ".pdf", ".csv"):
                info[f"perto_de:{termo}"] = _janelas(js, termo)
            rel["scripts"][s] = info
    gravar(os.path.join(pasta, "descoberta.json"), rel)
    return {"paginas": {u: v["status"] for u, v in rel["paginas"].items()},
            "scripts": len(rel["scripts"]), "falhas": rel["falhas"][:10]}


# ------------------------------------------------------------------ cadernos em PDF

def _baixar_pdf(cli: Cliente, d: date, nome: str):
    url = PDF_URL.format(iso=d.isoformat(), nome=nome, compacta=d.strftime("%Y%m%d"))
    try:
        r = cli.get(url, headers={"Accept": "application/pdf,*/*"}, timeout=60)
    except HttpError as e:
        return url, None, f"rede: {e.body[:60]}"
    if r.status != 200:
        return url, None, f"HTTP {r.status}"
    if not r.content.startswith(b"%PDF"):
        return url, None, f"nao e PDF ({r.headers.get('content-type', '?')}, {len(r.content)} bytes)"
    return url, r, None


def cadernos(cli: Cliente, d: date, pasta: str, espaco: float = 0.15) -> dict:
    """Testa BDI_NN e BDI_NN-S do pregao; grava PDF e texto do que existir."""
    achados, sondas = {}, {}
    candidatos = []
    for nn in CADERNOS:
        candidatos.append(f"BDI_{nn:02d}")
        candidatos.extend(f"BDI_{nn:02d}-{s}" for s in SECOES)
    for nome in candidatos:
        url, r, erro = _baixar_pdf(cli, d, nome)
        time.sleep(espaco)
        if erro:
            sondas[nome] = erro
            continue
        texto, paginas = texto_pdf(r.content)
        gravar(os.path.join(pasta, "pdf", f"{nome}.pdf"), r.content, binario=True)
        gravar(os.path.join(pasta, "pdf", f"{nome}.txt"), texto)
        titulo = " ".join(texto.strip().split()[:40])[:240]
        achados[nome] = {"url": url, "bytes": len(r.content), "paginas": paginas,
                         "last_modified": r.headers.get("last-modified"), "titulo": titulo}
    erros = {}
    for v in sondas.values():
        erros[v] = erros.get(v, 0) + 1
    return {"cadernos": achados, "sondas_sem_arquivo": erros}


# ------------------------------------------------------------------ arquivos da API de download

def _arquivo(cli: Cliente, nome: str, d: date):
    r = cli.get(TOKEN_URL, params={"fileName": nome, "date": d.isoformat()}, timeout=40)
    if r.status != 200:
        return None, f"token HTTP {r.status}: {r.text[:80]}"
    try:
        corpo = r.json() or {}
    except Exception:
        return None, f"token nao e JSON: {r.text[:80]}"
    token = corpo.get("token")
    if not token:
        return None, f"sem token: {json.dumps(corpo)[:120]}"
    r2 = cli.get(DOWNLOAD_URL, params={"token": token}, timeout=180)
    if r2.status != 200:
        return None, f"download HTTP {r2.status}"
    return (r2, corpo), None


def arquivos(cli: Cliente, d: date, pasta: str, nomes=ARQUIVOS) -> dict:
    achados, falhas = {}, {}
    for nome in nomes:
        try:
            res, erro = _arquivo(cli, nome, d)
        except HttpError as e:
            res, erro = None, f"rede: {e.body[:60]}"
        if erro:
            falhas[nome] = erro
            continue
        r, corpo = res
        bruto = r.content
        ext = "zip" if bruto[:2] == b"PK" else "csv"
        texto = bruto.decode("utf-8-sig", errors="replace") if ext == "csv" else ""
        linhas = texto.splitlines() if texto else []
        info = {"bytes": len(bruto), "tipo": ext, "linhas": len(linhas), "token_resposta": {k: v for k, v in corpo.items() if k != "token"},
                "content_type": r.headers.get("content-type"), "disposition": r.headers.get("content-disposition"),
                "cabecalho": linhas[:3], "amostra": linhas[3:8]}
        if ext == "csv" and len(bruto) <= LIMITE_CSV_INTEIRO:
            gravar(os.path.join(pasta, "arquivos", f"{nome}.csv"), texto)
            info["gravado"] = "inteiro"
        else:
            info["gravado"] = "so amostra (grande demais para o branch)"
        achados[nome] = info
        time.sleep(0.3)
    return {"arquivos": achados, "falhas": falhas}


# ------------------------------------------------------------------ principal

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--saida", default="boletim_b3")
    ap.add_argument("--data", default="", help="AAAA-MM-DD (vazio = ultimo pregao B3)")
    ap.add_argument("--dias", type=int, default=1, help="quantos pregoes para tras, a partir da data")
    ap.add_argument("--partes", default="descoberta,pdf,arquivos")
    a = ap.parse_args(argv)
    partes = {p.strip() for p in a.partes.split(",") if p.strip()}
    cli = Cliente()
    ini = date.fromisoformat(a.data) if a.data else relogios.data_pregao_b3()
    manifest = {"gerado_em": agora(), "cliente_http": cli.tipo, "partes": {}, "pregoes": {}, "falhas": []}

    if "descoberta" in partes:
        try:
            manifest["partes"]["descoberta"] = descobrir(cli, a.saida)
        except Exception as e:
            manifest["falhas"].append(f"descoberta: {type(e).__name__}: {e}")

    for d in pregoes(ini, max(1, a.dias)):
        pasta = os.path.join(a.saida, d.isoformat())
        idx: dict = {"pregao": d.isoformat(), "coletado_em": agora()}
        if "pdf" in partes:
            try:
                idx.update(cadernos(cli, d, pasta))
            except Exception as e:
                manifest["falhas"].append(f"{d} pdf: {type(e).__name__}: {e}")
        if "arquivos" in partes:
            try:
                res = arquivos(cli, d, pasta)
                idx["arquivos"] = res["arquivos"]
                idx["arquivos_falhas"] = res["falhas"]
            except Exception as e:
                manifest["falhas"].append(f"{d} arquivos: {type(e).__name__}: {e}")
        gravar(os.path.join(pasta, "index.json"), idx)
        manifest["pregoes"][d.isoformat()] = {"cadernos": sorted(idx.get("cadernos", {})),
                                              "arquivos": sorted(idx.get("arquivos", {}))}
        print(f"{d}: {len(idx.get('cadernos', {}))} cadernos, {len(idx.get('arquivos', {}))} arquivos", flush=True)

    gravar(os.path.join(a.saida, "manifest.json"), manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=1)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
