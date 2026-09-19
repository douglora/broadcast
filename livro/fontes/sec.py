"""8-K, 6-K, 10-Q e 10-K das companhias dos EUA do livro, pelo EDGAR (SEC).
Fonte primaria: o documento principal e lido por inteiro (texto do HTML).

Exige SEC_USER_AGENT com forma de contato: a SEC recusa requisicao sem
identificacao. Vale e-mail ("Nome contato@email") ou URL publica
("robo/1.0 (+https://github.com/dono/repo)"). O workflow define o padrao por URL,
que nao carrega dado pessoal, e o secret SEC_USER_AGENT tem prioridade quando o
contato precisa ser um e-mail. Sem contato algum a perna e declarada indisponivel
(lacuna), nunca inventa um."""

from __future__ import annotations

import html
import os
import re
from datetime import date, datetime, timedelta, timezone

from livro.http import Cliente, HttpError

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARQUIVO_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
FORMULARIOS_PADRAO = ["8-K", "8-K/A", "6-K", "10-Q", "10-K"]
# item do 8-K -> (rotulo, severidade)
ITENS_8K = {
    "1.01": ("acordo material assinado", "atencao"), "1.02": ("rescisao de acordo material", "atencao"),
    "1.03": ("falencia ou recuperacao", "critico"), "2.01": ("aquisicao ou venda concluida", "atencao"),
    "2.02": ("resultado do trimestre", "atencao"), "2.03": ("nova divida ou obrigacao", "info"),
    "2.04": ("aceleracao de obrigacao", "atencao"), "2.05": ("custos de reestruturacao", "atencao"),
    "2.06": ("impairment relevante", "atencao"), "3.01": ("aviso de deslistagem", "critico"),
    "3.02": ("venda de acoes nao registrada", "info"), "3.03": ("mudanca de direitos dos acionistas", "info"),
    "4.01": ("troca de auditor", "atencao"), "4.02": ("balanco nao confiavel (non-reliance)", "critico"),
    "5.01": ("mudanca de controle", "critico"), "5.02": ("entrada ou saida de diretor ou conselheiro", "atencao"),
    "5.03": ("mudanca de estatuto ou exercicio", "info"), "5.07": ("resultado das votacoes da assembleia", "info"),
    "7.01": ("Regulation FD", "info"), "8.01": ("outros eventos", "info"), "9.01": ("anexos", "ignorar"),
}
SEV_FORM = {"6-K": "info", "10-Q": "info", "10-K": "info"}
ORDEM_SEV = {"info": 0, "atencao": 1, "critico": 2}
_TAGS = re.compile(r"<[^>]+>")


# Mesmo formato de contato que o coletor do terminal ja usa com a SEC: nome do
# projeto e um contato entre parenteses. Nao carrega dado pessoal.
UA_PADRAO = "BROADCAST Livro (contato admin@theinvestpost.local)"


def variantes_ua(ua: str) -> list[str]:
    """Contatos a tentar, do declarado para os derivados do proprio GitHub Actions.

    O EDGAR devolveu 403 para User-Agent so com URL (run de 19/09), entao vale
    tentar tambem o formato 'nome contato@dominio' que a SEC documenta. O e-mail
    noreply do GitHub e publico por construcao: nao expoe endereco pessoal."""
    fora = [ua]
    if ua != UA_PADRAO:
        fora.append(UA_PADRAO)
    dono = (os.environ.get("GITHUB_REPOSITORY_OWNER") or "").strip()
    if "@" not in ua and dono:
        fora.append(f"{dono} {dono}@users.noreply.github.com")
    vistos, out = set(), []
    for c in fora:
        if c and c not in vistos:
            vistos.add(c)
            out.append(c)
    return out


def abrir_catalogo(cli: Cliente, ua: str, tickers: list[str]) -> tuple[dict, str | None, list[dict]]:
    """Tenta cada variante de contato ate o EDGAR responder. Devolve (ciks, ua_bom, tentativas)."""
    tentativas = []
    for cand in variantes_ua(ua):
        try:
            return cik_por_ticker(cli, cand, tickers), cand, tentativas + [{"ua": cand, "status": 200}]
        except HttpError as e:
            tentativas.append({"ua": cand, "status": e.status or 0, "detalhe": " ".join(str(e.body or "").split())[:300]})
    return {}, None, tentativas


ALVOS_SONDA = {
    "www/company_tickers": TICKERS_URL,
    "data/submissions": "https://data.sec.gov/submissions/",
    "www/Archives": "https://www.sec.gov/Archives/edgar/data/",
    "www/browse-edgar": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=MU&type=8-K&count=5&output=atom",
}


def sondar_hosts(cli: Cliente, uas: list[str] | str, dormir=None) -> dict:
    """Matriz contato x endpoint: diz de uma vez se o 403 e de User-Agent (muda com o
    contato) ou de faixa de IP do runner (nao muda com nada). Sem CIK: 404 tambem
    conta como alcancavel."""
    import time
    dormir = dormir or time.sleep
    if isinstance(uas, str):
        uas = [uas]
    out: dict = {}
    for nome, url in ALVOS_SONDA.items():
        por_ua = {}
        for cand in uas:
            try:
                r = cli.get(url, headers=_cabecalhos(cand), timeout=20)
                por_ua[cand[:44]] = {"status": r.status, "texto": " ".join(texto_de_html(r.content, 200).split())[:120]}
            except HttpError as e:
                por_ua[cand[:44]] = {"status": e.status or 0, "texto": " ".join(str(e.body or "").split())[:120]}
            dormir(0.4)
        out[nome] = por_ua
    return out


def user_agent() -> str | None:
    """Contato declarado: e-mail ou URL publica. Sem um dos dois, devolve None."""
    ua = (os.environ.get("SEC_USER_AGENT") or "").strip()
    tem_contato = "@" in ua or "http://" in ua or "https://" in ua
    return ua if len(ua) >= 8 and tem_contato else None


# Cabecalhos identicos aos de coletar_dados.py, que le a SEC destes mesmos runners
# com sucesso (8-K da MELI lido em 19/09). Accept-Language: None remove o cabecalho
# padrao da sessao, que o coletor que funciona nao envia.
def _cabecalhos(ua: str) -> dict:
    return {"User-Agent": ua, "Accept": "*/*", "Accept-Encoding": "gzip, deflate", "Accept-Language": None}


def cik_por_ticker(cli: Cliente, ua: str, tickers: list[str]) -> dict[str, int]:
    r = cli.get(TICKERS_URL, headers=_cabecalhos(ua), timeout=30)
    if r.status != 200:
        raise HttpError(r.status, texto_de_html(r.content, 400) or r.text[:200], TICKERS_URL)
    dados = r.json()
    alvo = {t.upper() for t in tickers}
    saida = {}
    for v in (dados.values() if isinstance(dados, dict) else dados):
        t = str(v.get("ticker", "")).upper()
        if t in alvo:
            saida[t] = int(v["cik_str"])
    return saida


def parse_submissions(payload: dict, desde: date, formularios: list[str] | None = None) -> list[dict]:
    """Filings recentes (form, data, itens, documento) a partir de `desde`."""
    formularios = formularios or FORMULARIOS_PADRAO
    rec = (payload.get("filings") or {}).get("recent") or {}
    forms = rec.get("form") or []
    saida = []
    for i, form in enumerate(forms):
        if form not in formularios:
            continue
        data = (rec.get("filingDate") or [""])[i] if i < len(rec.get("filingDate") or []) else ""
        if not data or data < desde.isoformat():
            continue
        itens = [x.strip() for x in ((rec.get("items") or [""] * len(forms))[i] or "").split(",") if x.strip()]
        acc = (rec.get("accessionNumber") or [""])[i]
        saida.append({
            "form": form, "data": data, "aceito_em": (rec.get("acceptanceDateTime") or [""])[i],
            "itens": itens, "acc": acc, "acc_sem_traco": acc.replace("-", ""),
            "doc": (rec.get("primaryDocument") or [""])[i],
            "descricao": (rec.get("primaryDocDescription") or [""])[i],
            "relatorio_de": (rec.get("reportDate") or [""])[i],
        })
    return saida


def severidade(form: str, itens: list[str]) -> tuple[str, list[str]]:
    """Severidade e rotulos dos itens do 8-K; 6-K/10-Q/10-K sao info."""
    if not form.startswith("8-K"):
        return SEV_FORM.get(form, "info"), [form]
    sev, rotulos = "info", []
    for it in itens:
        rot, s = ITENS_8K.get(it, (f"item {it}", "info"))
        if s == "ignorar":
            continue
        rotulos.append(f"{it} {rot}")
        if ORDEM_SEV.get(s, 0) > ORDEM_SEV.get(sev, 0):
            sev = s
    return sev, rotulos


def texto_de_html(payload: bytes, max_chars: int = 6000) -> str:
    s = payload.decode("utf-8", errors="ignore")
    s = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)</(p|div|tr|li|h[1-6]|br)>", "\n", s)
    s = html.unescape(_TAGS.sub(" ", s))
    s = re.sub(r"[ \t\xa0]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s).strip()
    return s[:max_chars]


def texto_filing(cli: Cliente, ua: str, cik: int, f: dict, max_chars: int = 6000) -> str | None:
    if not f.get("doc"):
        return None
    url = ARQUIVO_URL.format(cik=cik, acc=f["acc_sem_traco"], doc=f["doc"])
    try:
        r = cli.get(url, headers=_cabecalhos(ua), timeout=40)
    except HttpError:
        return None
    if r.status != 200 or not r.content:
        return None
    if f["doc"].lower().endswith(".pdf"):
        from livro.fontes.cvm import texto_de_pdf_bytes
        return texto_de_pdf_bytes(r.content, max_chars)
    return texto_de_html(r.content, max_chars) or None


def coletar(mapa: dict, cli: Cliente | None = None, hoje: date | None = None, dias: int = 3,
            formularios: list[str] | None = None, vistos: dict | None = None, max_docs: int = 6,
            ua: str | None = None, dormir=None) -> dict:
    """mapa: {ativo_do_livro: ticker_sec}. Devolve filings novos com texto (ate max_docs)."""
    import time
    dormir = dormir or time.sleep
    ua = ua or user_agent()
    if not ua:
        return {"disponivel": False, "motivo": "SEC_USER_AGENT ausente ou sem contato (e-mail ou URL)",
                "filings": [], "falhas": {}, "vistos": vistos or {}}
    cli = cli or Cliente(impersonate=False)
    hoje = hoje or datetime.now(timezone.utc).date()
    vistos = dict(vistos or {})
    desde = hoje - timedelta(days=dias)
    falhas: dict[str, str] = {}
    ciks, ua_bom, tentativas = abrir_catalogo(cli, ua, list(mapa.values()))
    if not ciks:
        motivo = "; ".join(f"{t['ua'][:40]} -> HTTP {t['status']}" for t in tentativas)
        return {"disponivel": True, "filings": [], "falhas": {"company_tickers": motivo[:300]},
                "vistos": vistos, "ciks": {}, "ua_tentativas": tentativas,
                "sonda_hosts": sondar_hosts(cli, variantes_ua(ua))}
    ua = ua_bom or ua
    novos = []
    for ativo, ticker in mapa.items():
        cik = ciks.get(ticker.upper())
        if not cik:
            falhas[ativo] = "CIK nao encontrado"
            continue
        try:
            r = cli.get(SUBMISSIONS_URL.format(cik=cik), headers=_cabecalhos(ua), timeout=30)
        except HttpError as e:
            falhas[ativo] = str(e)[:80]
            continue
        if r.status != 200:
            falhas[ativo] = f"HTTP {r.status}"
            continue
        for f in parse_submissions(r.json(), desde, formularios):
            fid = f"SEC-{ativo}-{f['acc_sem_traco'][-8:]}"
            if fid in vistos:
                continue
            sev, rotulos = severidade(f["form"], f["itens"])
            novos.append({**f, "id": fid, "ativo": ativo, "ticker": ticker, "cik": cik, "severidade": sev,
                          "itens_rotulo": rotulos, "url": ARQUIVO_URL.format(cik=cik, acc=f["acc_sem_traco"], doc=f["doc"]) if f.get("doc") else "",
                          "indice": f"https://www.sec.gov/Archives/edgar/data/{cik}/{f['acc_sem_traco']}/"})
        dormir(0.3)
    novos.sort(key=lambda f: (ORDEM_SEV.get(f["severidade"], 0), f["aceito_em"]), reverse=True)
    lidos = 0
    for f in novos:
        f["texto"] = None
        if lidos < max_docs and (f["severidade"] != "info" or f["form"].startswith("8-K")):
            f["texto"] = texto_filing(cli, ua, f["cik"], f)
            lidos += 1
            dormir(0.3)
        vistos[f["id"]] = {"data": f["data"]}
    limite = (hoje - timedelta(days=15)).isoformat()
    vistos = {k: v for k, v in vistos.items() if (v.get("data") or "9999") >= limite}
    return {"disponivel": True, "filings": novos, "falhas": falhas, "vistos": vistos, "ciks": ciks,
            "ua_usado": ua, "ua_tentativas": tentativas,
            "coletado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
