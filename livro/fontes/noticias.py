"""Noticias por ativo: descoberta no Google News (RSS por consulta), atribuicao aos
ativos do livro por palavras-chave, troca do link do Google pela URL do veiculo e
extracao do texto so onde a licenca permite (config/fontes_noticias.yaml).

Nada aqui interpreta a noticia: o runner guarda manchete, veiculo, hora, resumo,
texto (quando permitido) e link; a sessao escreve a leitura."""

from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, quote_plus, urlparse

from livro.http import Cliente, HttpError

GOOGLE_HOST = "news.google.com"
EDICOES = {"pt-BR": ("pt-BR", "BR", "BR:pt-419"), "en-US": ("en-US", "US", "US:en")}
BATCH_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute"
UA_NAVEGADOR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36")
_SIG = re.compile(r'data-n-a-sg="([^"]+)"')
_TS = re.compile(r'data-n-a-ts="([^"]+)"')
_TAGS = re.compile(r"<[^>]+>")
_ESPACOS = re.compile(r"\s+")


# ---------------------------------------------------------------- busca e RSS
def url_busca(consulta: str, lang: str = "pt-BR", janela: str = "1d") -> str:
    hl, gl, ceid = EDICOES.get(lang, EDICOES["pt-BR"])
    termos = f"{consulta} when:{janela}" if janela else consulta
    return f"https://{GOOGLE_HOST}/rss/search?q={quote_plus(termos)}&hl={hl}&gl={gl}&ceid={ceid}"


def limpar_html(texto: str) -> str:
    return _ESPACOS.sub(" ", html.unescape(_TAGS.sub(" ", texto or ""))).strip()


def parse_rss(payload: bytes) -> list[dict]:
    """Itens do RSS do Google News: titulo sem o sufixo ' - Veiculo', link (token do
    Google), veiculo (<source>), publicado (ISO UTC) e descricao em texto puro."""
    try:
        raiz = ET.fromstring(payload)
    except ET.ParseError:
        return []
    itens = []
    for it in raiz.iter("item"):
        titulo = (it.findtext("title") or "").strip()
        fonte = it.find("source")
        veiculo = (fonte.text or "").strip() if fonte is not None else ""
        url_veiculo = fonte.get("url", "") if fonte is not None else ""
        if veiculo and titulo.endswith(f" - {veiculo}"):
            titulo = titulo[: -len(veiculo) - 3].strip()
        pub = it.findtext("pubDate") or ""
        try:
            dt = parsedate_to_datetime(pub).astimezone(timezone.utc)
            publicado = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            publicado = ""
        itens.append({
            "titulo": html.unescape(titulo),
            "link": (it.findtext("link") or "").strip(),
            "veiculo": veiculo,
            "url_veiculo": url_veiculo,
            "publicado": publicado,
            "descricao": limpar_html(it.findtext("description") or "")[:600],
        })
    return itens


# ---------------------------------------------------------------- resolvedor do link
def _id_artigo(url: str) -> str | None:
    p = urlparse(url)
    if p.netloc != GOOGLE_HOST:
        return None
    partes = [x for x in p.path.split("/") if x]
    if len(partes) >= 2 and partes[-2] in ("articles", "read"):
        return partes[-1]
    return None


def _externa(url: str | None) -> bool:
    if not url:
        return False
    p = urlparse(url)
    host = p.netloc.lower()
    return p.scheme in ("http", "https") and bool(host) and host != GOOGLE_HOST and not host.endswith(".google.com")


def _decodificar_legado(id_artigo: str) -> str | None:
    import base64
    import binascii
    padded = id_artigo + "=" * (-len(id_artigo) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded)
    except (binascii.Error, ValueError):
        return None
    m = re.search(rb"https?://[\x21-\x7e]+", raw)
    if not m:
        return None
    cand = m.group(0).decode("ascii", errors="ignore")
    return cand if _externa(cand) else None


def _decodificar_batch(id_artigo: str, cli: Cliente) -> str | None:
    """Formato atual: a pagina do artigo traz assinatura e carimbo que o proprio front
    do Google manda ao batchexecute para receber a URL do veiculo."""
    pagina = cli.get(f"https://{GOOGLE_HOST}/articles/{id_artigo}", headers={"User-Agent": UA_NAVEGADOR})
    if pagina.status != 200:
        return None
    sig, ts = _SIG.search(pagina.text), _TS.search(pagina.text)
    if not sig or not ts or not ts.group(1).isdigit():
        return None
    req = ["Fbv4je",
           '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,'
           'null,null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],'
           f'"{id_artigo}",{ts.group(1)},"{sig.group(1)}"]']
    corpo = "f.req=" + quote(json.dumps([[req]]))
    r = cli.post(BATCH_URL, data=corpo, headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                                                 "User-Agent": UA_NAVEGADOR})
    if r.status != 200:
        return None
    try:
        payload = json.loads(r.text.split("\n\n", 1)[1])
        cand = json.loads(payload[0][2])[1]
    except (IndexError, KeyError, TypeError, ValueError):
        return None
    return cand if isinstance(cand, str) and _externa(cand) else None


def resolver_url(url: str, cli: Cliente) -> str:
    """Token do Google News -> URL do veiculo. Falha devolve a URL original."""
    id_artigo = _id_artigo(url)
    if id_artigo is None:
        return url
    legado = _decodificar_legado(id_artigo)
    if legado:
        return legado
    try:
        dec = _decodificar_batch(id_artigo, cli)
        if dec:
            return dec
        r = cli.get(url, headers={"User-Agent": UA_NAVEGADOR})
        return r.url if _externa(r.url) else url
    except HttpError:
        return url


# ---------------------------------------------------------------- atribuicao e materialidade
def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return _ESPACOS.sub(" ", re.sub(r"[^a-z0-9 ]+", " ", t)).strip()


def atribuir(titulo: str, descricao: str, casar: dict, excluir: dict | None = None,
             previsor: dict | None = None, excluir_global: list[str] | None = None) -> list[str]:
    """Ativos do livro citados na MANCHETE. So o titulo conta: a descricao do Google
    News repete a manchete e traz o nome do veiculo ("Portal Aqui Vale" nao e a
    Vale). `excluir` tira o ativo quando a manchete casa um padrao negativo
    ("Nvidia-backed", "Prime Video"); `previsor` tira o banco quando ele e o
    previsor macro da manchete ("Bradesco revisa projecao da Selic");
    `excluir_global` descarta a manchete inteira, para qualquer ativo: dividendo de
    acao preferencial ou depositary share nao e fato da ordinaria do livro."""
    for pg in (excluir_global or []):
        if _seguro(pg, titulo):
            return []
    achados = []
    for ativo, padroes in (casar or {}).items():
        if not any(_seguro(p, titulo) for p in padroes):
            continue
        if any(_seguro(p, titulo) for p in (excluir or {}).get(ativo, [])):
            continue
        achados.append(ativo)
    if previsor and previsor.get("padrao") and _seguro(previsor["padrao"], titulo):
        achados = [a for a in achados if a not in set(previsor.get("ativos") or [])]
    return achados


def _seguro(padrao: str, texto: str) -> bool:
    try:
        return re.search(padrao, texto) is not None
    except re.error:
        return False


DECISAO = re.compile(
    r"(?i)\b(anuncia|aprova|corta|eleva|rebaixa|reduz|fecha|assina|compra|vende|adquire|paga|distribui|lan[cç]a|"
    r"suspende|cancela|demite|nomeia|renuncia|processa|multa|conclui|recebe|divulga|registra|"
    r"announces|approves|cuts|raises|lowers|hikes|downgrades?|upgrades?|signs|buys|sells|acquires|pays|files|"
    r"reports|posts|beats|misses|suspends|cancels|names|appoints|resigns|sues|fines|settles|wins|loses|halts|"
    r"unveils|launches|completes|agrees|plunges|soars|surges|tumbles|despenca|dispara|invests?|investe|bets|aposta)\b")


def materialidade(titulo: str, descricao: str, fortes: list[str]) -> tuple[str, list[str]]:
    """ATENCAO exige gatilho forte na manchete E (numero na manchete OU verbo de decisao).
    'Por que a Coca-Cola desafia a tese de dividendos?' e info; 'Safra corta preco-alvo
    de Itau' e atencao."""
    bateu = [p for p in (fortes or []) if _seguro(p, titulo)]
    if not bateu:
        return "info", []
    if re.search(r"\d", titulo) or DECISAO.search(titulo):
        return "atencao", bateu
    return "info", bateu


def gatilho(titulo: str, descricao: str) -> str:
    """Chave de `por_que` no config para a noticia."""
    t = normalizar(f"{titulo} {descricao or ''}")
    regras = [
        ("resultado", r"\b(resultado|lucro|prejuizo|earnings|profit|revenue|receita)\b"),
        ("dividendo", r"\b(dividend|jcp|juros sobre capital|recompra|buyback)"),
        ("ma", r"\b(aquisicao|compra de|venda de|fusao|acquisition|acquire|merger|takeover|deal)\b"),
        ("rating", r"\b(rating|recomendacao|preco alvo|price target|downgrade|upgrade|rebaixa|eleva)\b"),
        ("gestao", r"\b(ceo|cfo|presidente|conselho|chairman|renuncia|resigns|steps down|appoint)\b"),
        ("juridico", r"\b(multa|processo|cade|justica|lawsuit|antitrust|ruling|settlement|fine)\b"),
        ("operacional", r"\b(greve|acidente|barragem|vazamento|strike|accident|spill|outage|recall|producao|output)\b"),
        ("oferta", r"\b(oferta|follow on|ipo|emissao|debentures|offering|bond)\b"),
        ("macro", r"\b(copom|selic|fomc|fed|federal reserve|juros|rate|inflation|inflacao|ipca|cpi)\b"),
        ("tarifa", r"\b(tarifa|tariff|sancao|sanction|export ban)\b"),
    ]
    for chave, padrao in regras:
        if re.search(padrao, t):
            return chave
    return "padrao"


# ---------------------------------------------------------------- veiculo e licenca
def veiculo_de(url: str, veiculos: list[dict], nome_feed: str = "") -> dict:
    host = urlparse(url).netloc.lower()
    for v in veiculos or []:
        for d in v.get("dominios", []):
            if host == d or host.endswith("." + d):
                return v
    return {"id": "outro", "nome": nome_feed or host or "veiculo", "licenca": "manchete"}


def texto_de_html(payload: bytes, max_chars: int = 6000) -> str:
    """Texto principal da pagina. trafilatura quando instalado; senao, paragrafos."""
    try:
        import trafilatura  # type: ignore
        txt = trafilatura.extract(payload, include_comments=False, include_tables=False, favor_precision=True)
        if txt and len(txt) > 200:
            return txt[:max_chars]
    except Exception:
        pass
    try:
        s = payload.decode("utf-8", errors="ignore")
    except Exception:
        return ""
    s = re.sub(r"(?is)<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>", " ", s)
    pars = re.findall(r"(?is)<p[^>]*>(.*?)</p>", s)
    linhas = [limpar_html(p) for p in pars]
    linhas = [l for l in linhas if len(l) > 40]
    return "\n".join(linhas)[:max_chars]


def extrair_texto(url: str, cli: Cliente, max_chars: int = 6000) -> str | None:
    try:
        r = cli.get(url, headers={"User-Agent": UA_NAVEGADOR}, timeout=25)
    except HttpError:
        return None
    if r.status != 200 or not r.content:
        return None
    return texto_de_html(r.content, max_chars) or None


def resumo_fiel(descricao: str, texto: str | None, max_linhas: int = 8) -> list[str]:
    """Linhas com numero, citacao ou decisao, tiradas do corpo (nao da manchete).
    Sem texto, usa a descricao do feed."""
    base = texto or descricao or ""
    brutas = re.split(r"(?<=[.!?])\s+", base.replace("\n", " "))
    frases: list[str] = []
    for f in brutas:
        if frases and re.search(r"\b(Inc|Ltd|Co|Corp|S\.A|Sr|Sra|Dr|No|Nº|art|Cia|vs|etc|R\$|US\$|fig|p)\.$", frases[-1]):
            frases[-1] = frases[-1] + " " + f
        else:
            frases.append(f)
    def pontos(f: str) -> int:
        p = 0
        if re.search(r"R\$|US\$|\$|%|por a[cç][aã]o|bilh|milh|billion|million", f):
            p += 2
        elif re.search(r"\d", f):
            p += 1
        if re.search(r"\"|“|”", f):
            p += 1
        if re.search(r"(?i)\bLei\b|\bart\.|§|Resolu[cç][aã]o CVM|Instru[cç][aã]o CVM", f):
            p -= 1
        if re.match(r"^[a-zà-ú]|^\d+ e \d+", f.strip()):   # fragmento comecando em minuscula ou 'art. 137 e 252'
            p -= 1
        return p
    validas = [f.strip() for f in frases if 30 <= len(f.strip()) <= 260]
    boas = [f for f in validas if pontos(f) >= 1]
    if not boas:
        boas = validas
    return boas[:max_linhas]


# ---------------------------------------------------------------- dedup entre veiculos
def _tokens(titulo: str) -> set[str]:
    """Palavras com 4+ letras e qualquer token com digito (o numero da manchete e o
    que mais identifica a mesma noticia entre veiculos)."""
    return {t for t in normalizar(titulo).split() if len(t) >= 4 or any(ch.isdigit() for ch in t)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


PRIORIDADE_LICENCA = {"integral": 0, "resumo": 1, "manchete": 2}


def consolidar(itens: list[dict], limiar: float = 0.34) -> list[dict]:
    """Mesma noticia em varios veiculos vira um item com `fontes_extras`; fica o de
    melhor licenca. Item unico ganha `fonte_unica: True`."""
    itens = sorted(itens, key=lambda i: (PRIORIDADE_LICENCA.get(i.get("licenca"), 3), i.get("publicado", "")))
    saida: list[dict] = []
    for it in itens:
        tk = _tokens(it["titulo"])
        dono = next((s for s in saida if _jaccard(tk, _tokens(s["titulo"])) >= limiar and set(s["ativos"]) & set(it["ativos"])), None)
        if dono is None:
            it["fontes_extras"] = []
            saida.append(it)
        else:
            if it.get("hash"):
                dono.setdefault("absorvidos", []).append(it["hash"])
            if it.get("veiculo") and it["veiculo"] not in dono["fontes_extras"] and it["veiculo"] != dono.get("veiculo"):
                dono["fontes_extras"].append(it["veiculo"])
            for a in it["ativos"]:
                if a not in dono["ativos"]:
                    dono["ativos"].append(a)
    for s in saida:
        s["fonte_unica"] = not s["fontes_extras"]
    return saida


def hash_url(url: str) -> str:
    """Identidade pelo endereco do veiculo (host + caminho), usada como SEGUNDA passada
    de deduplicacao: quando o veiculo EDITA a manchete (visto em 21/09, o Estadao tirou
    um "corta" repetido), o hash por titulo muda e a mesma materia volta como alerta
    novo. O endereco nao muda."""
    p = urlparse(url or "")
    base = (p.netloc or "").lower().removeprefix("www.") + (p.path or "").rstrip("/")
    return "U-" + hashlib.sha1(base.encode()).hexdigest()[:10]


def hash_item(titulo: str, veiculo: str = "") -> str:
    """Identidade do item: manchete normalizada + veiculo. NAO entra a URL: o link do
    Google News e um token que muda entre coletas, e com ele a mesma materia ganhava
    um hash novo a cada run, reaparecia depois do ack e virava alerta repetido."""
    return hashlib.sha1((normalizar(titulo) + "|" + normalizar(veiculo)).encode()).hexdigest()[:10]


# ---------------------------------------------------------------- coleta
def coletar(cfg: dict, vistos: dict | None = None, cli: Cliente | None = None, agora: datetime | None = None,
            janela: str = "1d", dormir=None) -> dict:
    """Roda todas as consultas do config, atribui, resolve links (ate max_resolver) e
    extrai texto onde a licenca e `integral`. Devolve {itens, consultas, falhas, vistos}."""
    import time
    agora = agora or datetime.now(timezone.utc)
    dormir = dormir or time.sleep
    cli = cli or Cliente(impersonate=False)
    vistos = dict(vistos or {})
    casar = cfg.get("casar") or {}
    fortes = cfg.get("materialidade_forte") or []
    veiculos = cfg.get("veiculos") or []
    janela_h = int(cfg.get("janela_horas", 36))
    corte = agora - timedelta(hours=janela_h)
    falhas: dict[str, str] = {}
    brutos: list[dict] = []
    n_consultas = 0
    so_conhecidos = bool(cfg.get("so_veiculos_conhecidos", True))
    max_por_consulta = int(cfg.get("max_por_consulta", 40))
    descartados = {"veiculo_desconhecido": 0, "sem_ativo": 0, "velho": 0, "visto": 0, "teto": 0}
    for c in cfg.get("consultas") or []:
        n_consultas += 1
        try:
            r = cli.get(url_busca(c["q"], c.get("lang", "pt-BR"), janela), timeout=25)
        except HttpError as e:
            falhas[c["id"]] = f"rede: {e}"[:120]
            continue
        if r.status != 200:
            falhas[c["id"]] = f"HTTP {r.status}"
            continue
        for it in parse_rss(r.content)[:max_por_consulta]:
            if not it["titulo"] or not it["link"]:
                continue
            if it["publicado"]:
                try:
                    if datetime.strptime(it["publicado"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) < corte:
                        descartados["velho"] += 1
                        continue
                except ValueError:
                    pass
            h = hash_item(it["titulo"], it.get("veiculo") or "")
            if h in vistos:
                descartados["visto"] += 1
                continue
            v = veiculo_de(it.get("url_veiculo") or "", veiculos, it.get("veiculo"))
            if so_conhecidos and v.get("id") == "outro":
                descartados["veiculo_desconhecido"] += 1
                continue
            ativos = atribuir(it["titulo"], it["descricao"], casar, cfg.get("excluir"),
                              cfg.get("previsor_macro"), cfg.get("excluir_global"))
            if not ativos:
                descartados["sem_ativo"] += 1
                continue
            sev, palavras = materialidade(it["titulo"], it["descricao"], fortes)
            brutos.append({**it, "hash": h, "ativos": ativos, "severidade": sev, "palavras": palavras,
                           "consulta": c["id"], "lang": c.get("lang", "pt-BR"), "licenca": v.get("licenca", "manchete"),
                           "veiculo": v.get("nome") or it.get("veiculo") or "", "veiculo_id": v.get("id", "outro"),
                           "gatilho": gatilho(it["titulo"], it["descricao"])})
        dormir(1.0)
    itens = consolidar(brutos)
    # os de atencao primeiro, mais recentes primeiro dentro do grupo
    itens.sort(key=lambda i: (0 if i["severidade"] == "atencao" else 1, -(_ts(i.get("publicado")))))
    # tetos por execucao: o que sobra fica so no vistos (nao volta) e na contagem
    max_at = int(cfg.get("max_atencao_por_run", 12))
    max_info = int(cfg.get("max_info_por_run", 15))
    at = [i for i in itens if i["severidade"] == "atencao"]
    info = [i for i in itens if i["severidade"] != "atencao"]
    for sobra in at[max_at:] + info[max_info:]:
        descartados["teto"] += 1
        for h in [sobra["hash"]] + list(sobra.get("absorvidos") or []):
            vistos[h] = {"data": (sobra.get("publicado") or agora.strftime("%Y-%m-%dT%H:%M:%SZ"))[:10], "id": f"N-{sobra['hash']}"}
    itens = at[:max_at] + info[:max_info]
    max_res = int(cfg.get("max_resolver_por_run", 15))
    max_chars = int(cfg.get("max_texto_chars", 6000))
    for i, it in enumerate(itens):
        it["url_google"] = it.pop("link")
        it["url"] = it["url_google"]
        it["texto"] = None
        it["trechos"] = []
        if i < max_res:
            it["url"] = resolver_url(it["url_google"], cli)
            hu = hash_url(it["url"])
            if _externa(it["url"]) and hu in vistos:
                # mesma materia com manchete editada: ja foi entregue sob outro hash
                it["repetida"] = True
                descartados["visto_url"] = descartados.get("visto_url", 0) + 1
                continue
            it["hash_url"] = hu
            v = veiculo_de(it["url"], veiculos, it.get("veiculo"))
            it["licenca"], it["veiculo_id"] = v.get("licenca", "manchete"), v.get("id", "outro")
            if v.get("nome"):
                it["veiculo"] = v["nome"]
            if it["licenca"] in ("integral", "resumo") and _externa(it["url"]):
                txt = extrair_texto(it["url"], cli, max_chars)
                if txt:
                    # integral: texto guardado; resumo: so trechos com numero, para a sessao resumir (nao colar)
                    it["trechos"] = resumo_fiel("", txt)
                    if it["licenca"] == "integral":
                        it["texto"] = txt
            dormir(0.5)
        it["resumo"] = it["trechos"] or resumo_fiel(it.get("descricao", ""), None)
        it["id"] = f"N-{it['hash']}"
        chaves = [it["hash"]] + list(it.get("absorvidos") or [])
        if it.get("hash_url"):
            chaves.append(it["hash_url"])
        for h in chaves:
            vistos[h] = {"data": (it.get("publicado") or agora.strftime("%Y-%m-%dT%H:%M:%SZ"))[:10], "id": it["id"]}
    # poda de vistos: 10 dias
    limite = (agora - timedelta(days=10)).strftime("%Y-%m-%d")
    vistos = {k: v for k, v in vistos.items() if (v.get("data") or "9999") >= limite}
    itens = [x for x in itens if not x.get("repetida")]
    return {"itens": itens, "consultas": n_consultas, "falhas": falhas, "vistos": vistos, "descartados": descartados,
            "coletado_em": agora.strftime("%Y-%m-%dT%H:%M:%SZ")}


def _ts(publicado: str | None) -> float:
    try:
        return datetime.strptime(publicado or "", "%Y-%m-%dT%H:%M:%SZ").timestamp()
    except ValueError:
        return 0.0
