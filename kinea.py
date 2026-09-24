#!/usr/bin/env python3
"""
Kinea: carteira dos fundos na CVM e cartas do gestor na integra.

Roda no GitHub Actions (workflow kinea.yml), que tem internet aberta, e grava
em kinea/ no branch `dados`. A sessao do Claude le por raw.githubusercontent.com
com `python3 mesa.py kinea`.

    kinea/cda.json              posicoes em acoes dos fundos Kinea (bloco 4 da CDA da CVM),
                                mes a mes: construtoras fundo a fundo, total da casa, PL e
                                as maiores posicoes em bolsa
    kinea/cartas/index.json     cartas do gestor achadas (fundo, mes, familia, url, paginas)
    kinea/cartas/<arquivo>.txt  texto integral de cada carta, extraido do PDF
    kinea/videos/index.json     videos do canal no YouTube (lives mensais, Kinea Expresso, podcasts):
                                titulo, data, descricao e a legenda em texto com marca de tempo
    kinea/videos/<data>_<id>.txt
    kinea/docs/index.json       PDFs do site que nao sao carta (apresentacao da live, relatorios) e
                                posts do blog que falam do tema, com o texto
    kinea/imagens/*.jpg         paginas de "principais posicoes" das cartas e das lives em imagem:
                                ali as empresas aparecem como logotipo e o texto do PDF nao traz o nome
    kinea/manifest.json         o que rodou, o que achou e o que falhou

Uso:
    python kinea.py --saida dados_branch/kinea                       # 12 meses de carteira + cartas desde 2025-07 + midia
    python kinea.py --saida dados_branch/kinea --meses 6 --cartas-desde 2026-01
    python kinea.py --saida /tmp/k --partes cartas --urls "https://www.kinea.com.br/wp-content/uploads/2026/09/Carta-do-Gestor-Prev-Atlas-2026-08.pdf"
    python kinea.py --saida /tmp/k --partes midia --videos 10

Fontes: dados abertos da CVM (Composicao e Diversificacao das Aplicacoes, a CDA
mensal de todo fundo), o site da Kinea (www.kinea.com.br), onde as cartas e as
apresentacoes saem em PDF, e o canal da Kinea no YouTube (legenda publicada
pelo proprio YouTube). Nada aqui e opiniao: e copia do que a CVM e a gestora
publicaram. Cada parte falha sozinha e o manifest registra o motivo.
"""

import argparse
import datetime
import hashlib
import html
import io
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
import zipfile
from urllib.parse import quote

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
CDA_BASE = os.environ.get("KINEA_CDA_BASE", "https://dados.cvm.gov.br/dados/FI/DOC/CDA/DADOS/")
SITE = os.environ.get("KINEA_SITE", "https://www.kinea.com.br").rstrip("/")
FILTRO_GESTORA = "KINEA"

# Construtoras e incorporadoras da B3: o que a mesa acompanha fundo a fundo
CONSTRUTORAS = ["CURY3", "DIRR3", "TEND3", "PLPL3", "MRVE3", "CYRE3", "EZTC3", "MDNE3", "LAVV3", "EVEN3",
                "TRIS3", "MTRE3", "JHSF3", "MELK3", "HBOR3", "GFSA3", "RSID3"]

# Fundos cuja carta costuma trazer a parte de bolsa (sufixos vistos nos PDFs do site)
SLUGS_PADRAO = ["Atlas", "Atlas-Geral", "Prev-Atlas", "Atlas-II-Itau-Sub-III", "Chronos", "Chronos-Geral",
                "Chronos-Alocadores-Sub-II", "Apolo", "Apolo-Geral", "Apolo-Itau-Sub-II", "Prev-Sigma", "Sigma",
                "Prev-XTR", "Prev-Multimercado", "Gama", "Gama-Geral", "Prev-Acoes"]

FAMILIAS = [("acoes", r"gama|acoes"),
            ("multimercado", r"atlas|chronos|apolo|sigma|xtr|artemis|tls|multimercado"),
            ("renda_fixa", r"ipca|dakar|rf|renda.fixa|andes|alpes|nepal|himalaia|mont.blanc|incentivado|oportunidade|prev.cp"),
            ("infra", r"ipv|infra")]

# Cartas por mes e familia. O texto macro se repete entre os fundos da mesma familia (mudam so as
# tabelas de desempenho), entao poucas cartas representativas cobrem o mes; o resto vira ruido.
POR_MES = {"multimercado": 4, "acoes": 3}
PRIORIDADE = [r"atlas.*geral|^atlas$", r"chronos.*geral|^chronos$", r"apolo.*geral|^apolo$", r"^sigma$|prev sigma",
              r"gama.*geral|^gama$", r"^prev acoes$", r"artemis.*geral"]

_ULTIMA_KINEA = [0.0]


def agora():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def http_get(url, stream=False, timeout=90, tentativas=3, educado=False):
    """GET com UA de navegador, tres tentativas e pausa curta entre pedidos ao site da gestora."""
    if educado:
        espera = 0.4 - (time.time() - _ULTIMA_KINEA[0])
        if espera > 0:
            time.sleep(espera)
        _ULTIMA_KINEA[0] = time.time()
    erro = None
    for i in range(tentativas):
        try:
            r = requests.get(url, headers={"User-Agent": UA, "Accept": "*/*"}, timeout=timeout, stream=stream)
            if r.status_code == 200:
                return r
            erro = f"HTTP {r.status_code}"
            if r.status_code in (403, 404, 410):
                break
        except requests.RequestException as e:
            erro = f"{type(e).__name__}: {e}"
        time.sleep(2 * (i + 1))
    raise RuntimeError(erro or "falhou")


# ---------------------------------------------------------------------------
# CDA: carteira mensal dos fundos na CVM
# ---------------------------------------------------------------------------

def meses_cda(listagem_html):
    """Meses (AAAAMM) com zip mensal na pasta de dados abertos da CDA, do mais novo ao mais antigo."""
    return sorted(set(re.findall(r"cda_fi_(\d{6})\.zip", listagem_html)), reverse=True)


def _num(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _coluna(cols, *nomes):
    for n in nomes:
        if n in cols:
            return n
    return None


def _sem_acento(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()


def eh_acao(ticker, aplicacao):
    """Acao ou BDR a vista: fora opcoes, futuros, termo e swap (WINV26 e DI1F27 tem cara de ticker)."""
    a = _sem_acento(aplicacao)
    if not re.fullmatch(r"[A-Z]{4}\d{1,2}", ticker or ""):
        return False
    if any(k in a for k in ("opc", "futur", "termo", "swap", "emprest")):
        return False
    return "aco" in a or "bdr" in a or "depository" in a or "recibo" in a


def _linhas_kinea(z, membros):
    """Linhas dos CSVs do zip cujo DENOM_SOCIAL tem 'KINEA', lidas em blocos para nao estourar memoria."""
    import pandas as pd
    fatias = []
    for membro in membros:
        with z.open(membro) as f:
            texto = io.TextIOWrapper(f, encoding="latin-1", newline="")
            for bloco in pd.read_csv(texto, sep=";", dtype=str, chunksize=200_000, on_bad_lines="skip"):
                col = _coluna(bloco.columns, "DENOM_SOCIAL")
                if col is None:
                    break
                fatias.append(bloco[bloco[col].fillna("").str.upper().str.contains(FILTRO_GESTORA)])
    if not fatias:
        return None
    return pd.concat(fatias, ignore_index=True)


def ler_cda_mes(caminho_zip, aaaamm, alvo):
    """Posicoes da Kinea num zip mensal da CDA: construtoras, maiores posicoes em acoes, PL e confidenciais."""
    out = {"mes": f"{aaaamm[:4]}-{aaaamm[4:]}", "posicoes": [], "pl": {}, "maiores_acoes": [],
           "total_acoes": 0.0, "confidenciais": None, "colunas": {}}
    with zipfile.ZipFile(caminho_zip) as z:
        nomes = z.namelist()
        blc4 = [n for n in nomes if re.search(r"BLC_4", n, re.I)]
        pl = [n for n in nomes if re.search(r"_PL_", n, re.I)]
        confid = [n for n in nomes if re.search(r"CONFID", n, re.I)]
        out["arquivos"] = sorted(nomes)
        if pl:
            df = _linhas_kinea(z, pl)
            if df is not None and len(df):
                c_cnpj = _coluna(df.columns, "CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO")
                c_pl = _coluna(df.columns, "VL_PATRIM_LIQ")
                for _, r in df.iterrows():
                    v = _num(r.get(c_pl))
                    if v is not None:
                        out["pl"][r.get(c_cnpj)] = v
        if blc4:
            df = _linhas_kinea(z, blc4)
            if df is not None and len(df):
                cols = df.columns
                c = {"cnpj": _coluna(cols, "CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"),
                     "fundo": _coluna(cols, "DENOM_SOCIAL"),
                     "tipo": _coluna(cols, "TP_FUNDO_CLASSE", "TP_FUNDO"),
                     "ativo": _coluna(cols, "CD_ATIVO"),
                     "aplic": _coluna(cols, "TP_APLIC"),
                     "qt": _coluna(cols, "QT_POS_FINAL"),
                     "valor": _coluna(cols, "VL_MERC_POS_FINAL"),
                     "qt_compra": _coluna(cols, "QT_AQUIS_NEGOC"),
                     "qt_venda": _coluna(cols, "QT_VENDA_NEGOC")}
                out["colunas"] = {k: v for k, v in c.items() if v}
                somas = {}
                for _, r in df.iterrows():
                    tk = str(r.get(c["ativo"]) or "").strip().upper()
                    valor = _num(r.get(c["valor"])) or 0.0
                    aplic = str(r.get(c["aplic"]) or "")
                    a_vista = eh_acao(tk, aplic)
                    if a_vista and valor > 0:
                        somas[tk] = somas.get(tk, 0.0) + valor
                        out["total_acoes"] += valor
                    if tk in alvo:
                        cnpj = r.get(c["cnpj"])
                        pl_f = out["pl"].get(cnpj)
                        out["posicoes"].append({
                            "ticker": tk, "cnpj": cnpj, "fundo": str(r.get(c["fundo"]) or "").strip(),
                            "tipo_fundo": r.get(c["tipo"]) if c["tipo"] else None, "aplicacao": aplic, "a_vista": a_vista,
                            "qt": _num(r.get(c["qt"])), "valor": valor,
                            "qt_comprada_mes": _num(r.get(c["qt_compra"])) if c["qt_compra"] else None,
                            "qt_vendida_mes": _num(r.get(c["qt_venda"])) if c["qt_venda"] else None,
                            "pl_fundo": pl_f, "pct_pl": (valor / pl_f) if pl_f else None})
                out["maiores_acoes"] = [[tk, round(v, 2)] for tk, v in sorted(somas.items(), key=lambda x: -x[1])[:40]]
        if confid:
            df = _linhas_kinea(z, confid)
            if df is not None:
                c_val = _coluna(df.columns, "VL_MERC_POS_FINAL")
                c_apl = _coluna(df.columns, "TP_APLIC")
                out["confidenciais"] = {
                    "linhas": int(len(df)),
                    "valor": round(sum(_num(v) or 0 for v in df[c_val]), 2) if c_val else None,
                    "aplicacoes": sorted(set(str(x) for x in df[c_apl].dropna()))[:12] if c_apl else []}
            else:
                out["confidenciais"] = {"linhas": 0}
    out["total_acoes"] = round(out["total_acoes"], 2)
    return out


def baixar_para_arquivo(url, destino):
    r = http_get(url, stream=True, timeout=300)
    n = 0
    with open(destino, "wb") as f:
        for pedaco in r.iter_content(1 << 20):
            f.write(pedaco)
            n += len(pedaco)
    return n


def acoes_emitidas(dados_dir, tickers):
    """Acoes em circulacao de cada ticker, do JSON do coletor (Yahoo); None quando o ticker nao esta no branch."""
    res = {}
    for tk in tickers:
        caminho = os.path.join(dados_dir, "ativos", f"{tk}.json")
        try:
            d = json.load(open(caminho, encoding="utf-8"))
            info = (d.get("yahoo") or {}).get("info") or {}
            res[tk] = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
        except Exception:
            res[tk] = None
    return res


def coletar_cda(meses, alvo, dados_dir, falhas):
    print(f"== CDA: pasta {CDA_BASE}")
    try:
        listagem = http_get(CDA_BASE, timeout=60).text
    except Exception as e:
        falhas.append(f"cda: listagem da CVM: {e}")
        return None
    disponiveis = meses_cda(listagem)[:meses]
    if not disponiveis:
        falhas.append("cda: nenhum zip mensal na listagem da CVM")
        return None
    emitidas = acoes_emitidas(dados_dir, alvo)
    resultado = {"gerado_em": agora(), "fonte": "CVM dados abertos, FI/DOC/CDA (cda_fi_AAAAMM.zip): blocos BLC_4 e PL",
                 "gestora": FILTRO_GESTORA, "tickers_alvo": alvo, "acoes_emitidas": emitidas,
                 "meses": [], "posicoes": [], "total_por_mes": {}, "maiores_acoes": {}, "total_acoes": {},
                 "confidenciais": {}, "pl_fundos": {}}
    for aaaamm in sorted(disponiveis):
        url = f"{CDA_BASE}cda_fi_{aaaamm}.zip"
        with tempfile.TemporaryDirectory() as tmp:
            destino = os.path.join(tmp, "cda.zip")
            try:
                n = baixar_para_arquivo(url, destino)
                mes = ler_cda_mes(destino, aaaamm, alvo)
            except Exception as e:
                falhas.append(f"cda {aaaamm}: {type(e).__name__}: {e}")
                continue
        m = mes["mes"]
        print(f"  {m}: {n / 1e6:.0f} MB | {len(mes['posicoes'])} posicoes em construtoras | "
              f"{len(mes['pl'])} fundos Kinea com PL | acoes R$ {mes['total_acoes'] / 1e6:,.0f} mi")
        resultado["meses"].append(m)
        resultado["posicoes"].extend({"mes": m, **p} for p in mes["posicoes"])
        resultado["maiores_acoes"][m] = mes["maiores_acoes"]
        resultado["total_acoes"][m] = mes["total_acoes"]
        resultado["confidenciais"][m] = mes["confidenciais"]
        resultado["pl_fundos"][m] = {"fundos": len(mes["pl"]), "soma": round(sum(mes["pl"].values()), 2)}
        tot = {}
        for p in mes["posicoes"]:
            if not p.get("a_vista"):
                continue
            t = tot.setdefault(p["ticker"], {"qt": 0.0, "valor": 0.0, "fundos": 0})
            t["qt"] += p["qt"] or 0
            t["valor"] += p["valor"] or 0
            t["fundos"] += 1
        for tk, t in tot.items():
            t["valor"] = round(t["valor"], 2)
            t["pct_empresa"] = (t["qt"] / emitidas[tk]) if emitidas.get(tk) else None
            t["pct_acoes_kinea"] = (t["valor"] / mes["total_acoes"]) if mes["total_acoes"] else None
        resultado["total_por_mes"][m] = tot
    return resultado


# ---------------------------------------------------------------------------
# Cartas do gestor: PDF no site da Kinea -> texto integral
# ---------------------------------------------------------------------------

RX_PDF = re.compile(r"""href=["']([^"']+?\.pdf)(?:\?[^"']*)?["']""", re.I)
RX_MES = re.compile(r"(20\d{2})[-_](0[1-9]|1[0-2])\.pdf$", re.I)


def mes_da_carta(url):
    m = RX_MES.search(url.split("?")[0])
    return f"{m.group(1)}-{m.group(2)}" if m else None


def fundo_da_carta(url):
    nome = os.path.basename(url.split("?")[0])
    nome = re.sub(r"\.pdf$", "", nome, flags=re.I)
    nome = re.sub(r"^Carta[-_ ]do[-_ ]Gestor[-_ ]?", "", nome, flags=re.I)
    nome = RX_MES.sub("", nome + ".pdf").rstrip("-_ ")
    return nome.replace("-", " ").replace("_", " ").strip() or None


def familia(fundo):
    f = _sem_acento(fundo)
    for nome, rx in FAMILIAS:
        if re.search(rx, f):
            return nome
    return "outros"


def _e_carta(url):
    base = os.path.basename(url.split("?")[0]).lower()
    return base.endswith(".pdf") and "carta" in base


def _absoluta(href):
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return SITE + href
    return href


def descobrir_por_api(achadas, log):
    """WordPress REST: anexos PDF com 'carta' no nome (fonte mais completa quando a API esta aberta)."""
    n = 0
    for pagina in range(1, 21):
        url = f"{SITE}/wp-json/wp/v2/media?search=carta&per_page=100&page={pagina}&mime_type=application/pdf"
        try:
            itens = http_get(url, timeout=60, educado=True).json()
        except Exception as e:
            log.append(f"api wp-json pagina {pagina}: {e}")
            break
        if not isinstance(itens, list) or not itens:
            break
        for it in itens:
            src = it.get("source_url") or ""
            if _e_carta(src) and src not in achadas:
                achadas[src] = {"descoberta": "wp-json", "publicado_em": (it.get("date") or "")[:10]}
                n += 1
        if len(itens) < 100:
            break
    return n


def descobrir_por_categoria(achadas, log, max_posts=120):
    """Pagina de categoria 'carta do gestor' e os posts dela: links de PDF de carta."""
    n, posts, vistos = 0, [], set()
    for pagina in range(1, 16):
        url = f"{SITE}/blog/categoria/carta-do-gestor/" + (f"page/{pagina}/" if pagina > 1 else "")
        try:
            html = http_get(url, timeout=60, educado=True).text
        except Exception as e:
            log.append(f"categoria pagina {pagina}: {e}")
            break
        novos = 0
        for href in RX_PDF.findall(html):
            href = _absoluta(href)
            if _e_carta(href) and href not in achadas:
                achadas[href] = {"descoberta": "categoria"}
                n += 1
        for href in re.findall(r"""href=["'](%s/blog/[^"'#?]+/)["']""" % re.escape(SITE), html):
            if "/categoria/" in href or "/tag/" in href or "/page/" in href or href in vistos:
                continue
            vistos.add(href)
            posts.append(href)
            novos += 1
        if not novos:
            break
    for post in posts[:max_posts]:
        try:
            html = http_get(post, timeout=60, educado=True).text
        except Exception as e:
            log.append(f"post {post}: {e}")
            continue
        for href in RX_PDF.findall(html):
            href = _absoluta(href)
            if _e_carta(href) and href not in achadas:
                achadas[href] = {"descoberta": "post", "post": post}
                n += 1
    return n


def _meses_entre(desde, ate):
    a, m = int(desde[:4]), int(desde[5:7])
    fim = (int(ate[:4]), int(ate[5:7]))
    while (a, m) <= fim:
        yield a, m
        m += 1
        if m == 13:
            a, m = a + 1, 1


def descobrir_por_padrao(achadas, desde, log, slugs=SLUGS_PADRAO):
    """Monta o endereco pelo padrao do site (pasta do mes seguinte) para os meses sem carta achada."""
    hoje = datetime.date.today()
    ultimo = (hoje.replace(day=1) - datetime.timedelta(days=1)).strftime("%Y-%m")
    com_carta = {mes_da_carta(u) for u in achadas}
    inicio = max(desde, (hoje.replace(day=1) - datetime.timedelta(days=270)).strftime("%Y-%m"))
    n, recusas = 0, 0
    for a, m in _meses_entre(inicio, ultimo):
        ref = f"{a}-{m:02d}"
        if ref in com_carta:
            continue
        pastas = []
        for delta in (1, 0, 2):
            aa, mm = a + (m + delta - 1) // 12, (m + delta - 1) % 12 + 1
            pastas.append(f"{aa}/{mm:02d}")
        for slug in slugs:
            for pasta in pastas:
                url = f"{SITE}/wp-content/uploads/{pasta}/Carta-do-Gestor-{slug}-{a}-{m:02d}.pdf"
                if recusas >= 10:
                    log.append("padrao: site recusou 10 pedidos seguidos; parei de chutar enderecos")
                    return n
                time.sleep(0.2)
                try:
                    r = requests.head(url, headers={"User-Agent": UA}, timeout=30, allow_redirects=True)
                except requests.RequestException as e:
                    log.append(f"padrao {url}: {type(e).__name__}")
                    recusas += 1
                    continue
                recusas = recusas + 1 if r.status_code in (403, 429) or r.status_code >= 500 else 0
                if r.status_code == 200 and "pdf" in (r.headers.get("Content-Type") or "").lower():
                    achadas[url] = {"descoberta": "padrao"}
                    n += 1
                    break
    return n


def selecionar_cartas(achadas, desde, familias, por_mes=POR_MES):
    """Poucas cartas por mes e familia, na ordem de PRIORIDADE; as informadas a mao entram todas."""
    grupos = {}
    for url, meta in achadas.items():
        mes = mes_da_carta(url) or ""
        fundo = fundo_da_carta(url)
        fam = familia(fundo)
        if meta["descoberta"] == "informada":
            grupos.setdefault(("informada", mes), []).append((0, url, meta))
            continue
        if not mes or mes < desde or fam not in familias:
            continue
        nome = _sem_acento(fundo)
        prio = next((i for i, rx in enumerate(PRIORIDADE) if re.search(rx, nome)), len(PRIORIDADE))
        grupos.setdefault((fam, mes), []).append((prio, url, meta))
    escolhidas = []
    for (fam, mes), itens in grupos.items():
        itens.sort(key=lambda x: (x[0], x[1]))
        limite = None if fam == "informada" else por_mes.get(fam, 2)
        # A primeira do grupo representa o mes: dela sai a pagina de posicoes em imagem
        escolhidas.extend((mes, url, dict(meta, representante=(i == 0 and fam != "informada")))
                          for i, (_, url, meta) in enumerate(itens[:limite]))
    escolhidas.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return escolhidas


def texto_do_pdf(conteudo):
    from pypdf import PdfReader
    leitor = PdfReader(io.BytesIO(conteudo))
    paginas = [(p.extract_text() or "") for p in leitor.pages]
    return "\n\n".join(f"[p. {i + 1}] {t.strip()}" for i, t in enumerate(paginas)), len(paginas)


def coletar_cartas(saida, desde, urls_extras, falhas, familias=("multimercado", "acoes"), max_cartas=300):
    pasta = os.path.join(saida, "cartas")
    os.makedirs(pasta, exist_ok=True)
    antigo = {}
    try:
        antigo = {c["url"]: c for c in json.load(open(os.path.join(pasta, "index.json"), encoding="utf-8"))["cartas"]}
    except Exception:
        pass
    log, achadas = [], {}
    metodos = {"wp-json": descobrir_por_api(achadas, log), "categoria": descobrir_por_categoria(achadas, log)}
    for u in urls_extras:
        if u and u not in achadas:
            achadas[u] = {"descoberta": "informada"}
    metodos["padrao"] = descobrir_por_padrao(achadas, desde, log)
    metodos["informadas"] = sum(1 for v in achadas.values() if v["descoberta"] == "informada")
    print(f"== cartas: {len(achadas)} PDFs achados {metodos}")
    escolhidas = selecionar_cartas(achadas, desde, set(familias))
    print(f"   escolhidas {len(escolhidas)} (familias {sorted(familias)}, ate {POR_MES} por mes)")
    pasta_img = os.path.join(saida, "imagens", "cartas")
    os.makedirs(pasta_img, exist_ok=True)
    cartas, textos = [], {}
    for mes, url, meta in escolhidas[:max_cartas]:
        arquivo = re.sub(r"[^A-Za-z0-9_.-]+", "_", os.path.basename(url.split("?")[0]))[:120]
        arquivo = re.sub(r"\.pdf$", ".txt", arquivo, flags=re.I)
        destino = os.path.join(pasta, arquivo)
        velho = antigo.get(url)
        conteudo = None
        if velho and os.path.exists(destino) and velho.get("chars"):
            entrada = velho
        else:
            try:
                conteudo = http_get(url, timeout=120, educado=True).content
                texto, n_pag = texto_do_pdf(conteudo)
            except Exception as e:
                falhas.append(f"carta {url}: {e}")
                continue
            with open(destino, "w", encoding="utf-8") as f:
                f.write(texto)
            h = hashlib.sha1(re.sub(r"\s+", " ", texto).encode("utf-8")).hexdigest()[:16]
            fundo = fundo_da_carta(url)
            primeira = next((l.strip() for l in texto.split("\n") if len(l.strip()) > 8), "")[:140]
            entrada = {"arquivo": f"kinea/cartas/{arquivo}", "url": url, "fundo": fundo, "familia": familia(fundo),
                       "mes_ref": mes or None, "paginas": n_pag, "chars": len(texto), "sha1_texto": h,
                       "titulo": primeira, "descoberta": meta["descoberta"], "baixado_em": agora()}
            print(f"  {mes or '?'} {fundo}: {n_pag} p., {len(texto):,} chars")
        if meta.get("representante") and "imagens" not in entrada:
            try:
                if conteudo is None:
                    conteudo = http_get(url, timeout=120, educado=True).content
                entrada["imagens"] = paginas_de_posicoes(conteudo, arquivo[:-4], pasta_img, "kinea/imagens/cartas")
            except Exception as e:
                falhas.append(f"imagens da carta {url}: {type(e).__name__}: {e}")
        cartas.append(entrada)
    for c in cartas:
        textos.setdefault(c["sha1_texto"], c["arquivo"])
    for c in cartas:
        if textos[c["sha1_texto"]] != c["arquivo"]:
            c["texto_igual_a"] = textos[c["sha1_texto"]]
    cartas.sort(key=lambda c: (c.get("mes_ref") or "", c.get("fundo") or ""), reverse=True)
    no_indice = {os.path.basename(c["arquivo"]) for c in cartas}
    for nome in os.listdir(pasta):
        if nome.endswith(".txt") and nome not in no_indice:
            os.remove(os.path.join(pasta, nome))
    usadas = {os.path.basename(i["arquivo"]) for c in cartas for i in c.get("imagens") or []}
    for nome in os.listdir(pasta_img):
        if nome not in usadas:
            os.remove(os.path.join(pasta_img, nome))
    idx = {"gerado_em": agora(), "fonte": f"{SITE} (PDF da Carta do Gestor, texto extraido com pypdf)",
           "desde": desde, "cartas": cartas, "metodos": metodos, "log": log[:60]}
    with open(os.path.join(pasta, "index.json"), "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)
    return {"cartas": len(cartas), "metodos": metodos, "meses": sorted({c.get("mes_ref") for c in cartas if c.get("mes_ref")})}


# ---------------------------------------------------------------------------
# Midia: paginas de posicoes em imagem, documentos avulsos do site e videos do
# canal no YouTube com a legenda em texto
# ---------------------------------------------------------------------------

CANAL = os.environ.get("KINEA_CANAL", "https://www.youtube.com/@KineaInvestimentos")
# PDFs do site que nao sao carta: apresentacao da live mensal, relatorios de research
TERMOS_DOCS = ["live", "mochileiro", "research", "estudo", "panorama", "cenario"]
RX_DOC_UTIL = re.compile(r"live|mochileiro|research|estudo|panorama|cenario", re.I)
# Posts do blog que valem o texto (a Kinea publica relatorio como post, alem do PDF)
TERMOS_POSTS = ["mochileiro", "minha casa", "construtoras", "live economia", "eleicao", "bolsa"]
# Paginas em que as posicoes aparecem como logotipo (o texto do PDF nao traz o nome da empresa)
RX_POSICOES = re.compile(r"PRINCIPAIS\s+POSI[CÇ][OÕ]ES|POSICIONAMENTO\s+EM\s+A[CÇ][OÕ]ES|\bConstrutoras\b", re.I)
RX_YOUTUBE = re.compile(r"(?:youtube(?:-nocookie)?\.com/(?:embed/|watch\?v=|live/)|youtu\.be/)([\w-]{11})")
# Clientes do YouTube tentados em ordem: o padrao do yt-dlp e os alternativos. No Actions o YouTube
# costuma listar a legenda e so entrega-la com PO token (provedor bgutil, iniciado pelo workflow).
CLIENTES_YT = [None, ["mweb"], ["web"], ["tv"], ["web_safari"], ["android_vr"]]
# Videos de fundo listado (FII, CRI, agro, infra, credito) nao falam de acao: ficam fora
RX_VIDEO_FORA = re.compile(r"\bK[A-Z]{2,4}11\b|\bFII|Fiagro|\bCRI\b|Multifamily|Cr[eé]dito Privado|Private Credit|Renda Fixa|"
                           r"Fixed Income|Infraestrutura|Infrastructure|Imobili|Real Estate|Assembleia|Extraordin|Buyback|"
                           r"Recompra|Agro|Alternativ", re.I)
RX_VIDEO_DENTRO = re.compile(r"Economia e Mercados|Economy and Markets|Multimercado|Multi-Strategy|A[cç][oõ]es|Equity|"
                             r"Expresso|Kaf[eé]|Insights|Carta|Letter|Bolsa|Stock", re.I)


def paginas_de_posicoes(conteudo, base, pasta_img, prefixo, max_paginas=6, largura=1400):
    """Renderiza em JPEG as paginas de posicoes do PDF. Devolve [{pagina, arquivo}], vazio se nao houver."""
    import pymupdf
    doc = pymupdf.open(stream=conteudo, filetype="pdf")
    feitas = []
    for i, pag in enumerate(doc):
        if len(feitas) >= max_paginas:
            break
        if not RX_POSICOES.search(pag.get_text() or ""):
            continue
        z = largura / max(pag.rect.width, 1)
        pix = pag.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
        nome = f"{base}-p{i + 1:02d}.jpg"
        with open(os.path.join(pasta_img, nome), "wb") as f:
            f.write(pix.tobytes("jpeg", jpg_quality=80))
        feitas.append({"pagina": i + 1, "arquivo": f"{prefixo}/{nome}"})
    doc.close()
    return feitas


def texto_do_html(h):
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", h or "")
    h = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</div>", "\n", h)
    t = html.unescape(re.sub(r"<[^>]+>", " ", h))
    t = re.sub(r"[ \t\xa0]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def _wp_json(caminho, log):
    try:
        itens = http_get(f"{SITE}/wp-json/wp/v2/{caminho}", timeout=60, educado=True).json()
        return itens if isinstance(itens, list) else []
    except Exception as e:
        log.append(f"wp-json {caminho[:80]}: {e}")
        return []


def _rendered(v):
    """Campo do WordPress que costuma vir como {"rendered": ...}, mas pode vir texto ou lista."""
    if isinstance(v, dict):
        return _rendered(v.get("rendered") or v.get("raw") or "")
    if isinstance(v, list):
        return " ".join(_rendered(x) for x in v)
    return v if isinstance(v, str) else ""


def _itens_dict(itens, onde, log):
    bons = [it for it in itens if isinstance(it, dict)]
    if len(bons) < len(itens):
        log.append(f"{onde}: {len(itens) - len(bons)} itens fora do formato ({type(itens[0]).__name__})")
    return bons


def descobrir_documentos(desde, log):
    """PDFs que nao sao carta e posts do blog, pela busca do WordPress. Devolve (pdfs, posts)."""
    pdfs, posts = {}, {}
    for termo in TERMOS_DOCS:
        for pagina in range(1, 4):
            itens = _wp_json(f"media?search={quote(termo)}&per_page=100&page={pagina}&mime_type=application/pdf", log)
            for it in _itens_dict(itens, f"media '{termo}'", log):
                src = _rendered(it.get("source_url"))
                data = _rendered(it.get("date"))[:10]
                titulo = html.unescape(re.sub(r"<[^>]+>", "", _rendered(it.get("title"))))
                if (not src.lower().split("?")[0].endswith(".pdf") or _e_carta(src) or data[:7] < desde
                        or src in pdfs or not RX_DOC_UTIL.search(_sem_acento(os.path.basename(src) + " " + titulo))):
                    continue
                pdfs[src] = {"url": src, "publicado_em": data, "titulo": titulo.strip(), "achado_por": f"busca '{termo}'"}
            if len(itens) < 100:
                break
    for termo in TERMOS_POSTS:
        itens = _wp_json(f"posts?search={quote(termo)}&per_page=30&_fields=id,date,link,title,content", log)
        for it in _itens_dict(itens, f"posts '{termo}'", log):
            data = _rendered(it.get("date"))[:10]
            link = _rendered(it.get("link"))
            if not link or data[:7] < desde or link in posts:
                continue
            corpo = _rendered(it.get("content"))
            titulo = html.unescape(re.sub(r"<[^>]+>", "", _rendered(it.get("title")))).strip()
            posts[link] = {"url": link, "publicado_em": data, "titulo": titulo, "achado_por": f"busca '{termo}'",
                           "texto": texto_do_html(corpo), "videos": sorted(set(RX_YOUTUBE.findall(corpo)))}
            for href in RX_PDF.findall(corpo):
                href = _absoluta(href)
                if not _e_carta(href) and href not in pdfs:
                    pdfs[href] = {"url": href, "publicado_em": data, "titulo": titulo, "achado_por": f"post {link}"}
    return pdfs, posts


def _nome_arquivo(url, sufixo=""):
    nome = re.sub(r"[^A-Za-z0-9_.-]+", "_", os.path.basename(url.rstrip("/").split("?")[0]))[:100] or "doc"
    return re.sub(r"\.pdf$", "", nome, flags=re.I) + sufixo


def coletar_documentos(saida, desde, falhas):
    pasta = os.path.join(saida, "docs")
    pasta_img = os.path.join(saida, "imagens", "docs")
    os.makedirs(pasta, exist_ok=True)
    os.makedirs(pasta_img, exist_ok=True)
    antigo = {}
    try:
        antigo = {d["url"]: d for d in json.load(open(os.path.join(pasta, "index.json"), encoding="utf-8"))["docs"]}
    except Exception:
        pass
    log = []
    pdfs, posts = descobrir_documentos(desde, log)
    print(f"== documentos: {len(pdfs)} PDFs e {len(posts)} posts desde {desde}")
    docs = []
    for url, meta in sorted(pdfs.items(), key=lambda x: x[1]["publicado_em"], reverse=True)[:40]:
        # O mesmo nome de arquivo volta todo mes (Apresentacao-Live-Mensal.pdf): a data entra no nome
        arquivo = f"{meta['publicado_em']}_{_nome_arquivo(url)}"
        destino = os.path.join(pasta, arquivo + ".txt")
        velho = antigo.get(url)
        if velho and os.path.exists(destino) and velho.get("chars") and "imagens" in velho:
            docs.append(velho)
            continue
        try:
            conteudo = http_get(url, timeout=120, educado=True).content
            texto, n_pag = texto_do_pdf(conteudo)
        except Exception as e:
            falhas.append(f"doc {url}: {e}")
            continue
        with open(destino, "w", encoding="utf-8") as f:
            f.write(texto)
        entrada = dict(meta, tipo="pdf", arquivo=f"kinea/docs/{arquivo}.txt", paginas=n_pag, chars=len(texto),
                       baixado_em=agora())
        try:
            entrada["imagens"] = paginas_de_posicoes(conteudo, arquivo, pasta_img, "kinea/imagens/docs")
        except Exception as e:
            falhas.append(f"imagens do doc {url}: {type(e).__name__}: {e}")
        docs.append(entrada)
        print(f"  {meta['publicado_em']} {meta['titulo'][:60]}: {n_pag} p., {len(entrada.get('imagens') or [])} pag. de posicoes")
    for url, meta in sorted(posts.items(), key=lambda x: x[1]["publicado_em"], reverse=True)[:40]:
        arquivo = f"{meta['publicado_em']}_post_{_nome_arquivo(url)}"
        texto = meta.pop("texto")
        with open(os.path.join(pasta, arquivo + ".txt"), "w", encoding="utf-8") as f:
            f.write(f"# {meta['titulo']}\n# {url} | {meta['publicado_em']}\n\n{texto}")
        docs.append(dict(meta, tipo="post", arquivo=f"kinea/docs/{arquivo}.txt", chars=len(texto)))
    no_indice = {os.path.basename(d["arquivo"]) for d in docs}
    for nome in os.listdir(pasta):
        if nome.endswith(".txt") and nome not in no_indice:
            os.remove(os.path.join(pasta, nome))
    usadas = {os.path.basename(i["arquivo"]) for d in docs for i in d.get("imagens") or []}
    for nome in os.listdir(pasta_img):
        if nome not in usadas:
            os.remove(os.path.join(pasta_img, nome))
    docs.sort(key=lambda d: d.get("publicado_em") or "", reverse=True)
    with open(os.path.join(pasta, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"gerado_em": agora(), "fonte": f"{SITE} (busca do WordPress: {', '.join(TERMOS_DOCS + TERMOS_POSTS)})",
                   "desde": desde, "docs": docs, "log": log[:40]}, f, ensure_ascii=False, indent=1)
    return {"pdfs": sum(1 for d in docs if d["tipo"] == "pdf"), "posts": sum(1 for d in docs if d["tipo"] == "post"),
            "imagens": len(usadas)}


def _hms(seg):
    return f"{seg // 3600:02d}:{seg % 3600 // 60:02d}:{seg % 60:02d}"


RX_TEMPO_VTT = re.compile(r"^(\d{2,}):(\d{2}):(\d{2})[.,]\d{3}\s+-->")


def texto_da_legenda(vtt, janela=30):
    """VTT do YouTube -> texto corrido, uma linha a cada ~30 s com a marca de tempo do inicio.
    A legenda automatica repete a linha anterior em cada bloco (rolagem): cada linha entra uma vez."""
    saida, grupo, grupo_t, recentes = [], [], None, []
    # So linha vazia separa blocos: a legenda automatica abre cada bloco com uma linha de um espaco
    for bloco in re.split(r"\n{2,}", (vtt or "").replace("\r", "")):
        t, linhas = None, []
        for l in bloco.strip().split("\n"):
            m = RX_TEMPO_VTT.match(l.strip())
            if m:
                t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            elif t is not None:
                l = html.unescape(re.sub(r"<[^>]+>", "", l)).strip()
                if l:
                    linhas.append(l)
        if t is None:
            continue
        for l in linhas:
            if l in recentes:
                continue
            recentes = (recentes + [l])[-3:]
            if grupo and t - grupo_t >= janela:
                saida.append(f"[{_hms(grupo_t)}] {' '.join(grupo)}")
                grupo = []
            if not grupo:
                grupo_t = t
            grupo.append(l)
    if grupo:
        saida.append(f"[{_hms(grupo_t)}] {' '.join(grupo)}")
    return "\n".join(saida)


def _ydl(extra, clientes=None):
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "socket_timeout": 30, "retries": 3,
            "ignore_no_formats_error": True, "http_headers": {"Accept-Language": "pt-BR,pt;q=0.9"}}
    opts.update(extra)
    # Titulo e descricao no idioma original (sem isso o YouTube traduz para o ingles no servidor dos EUA)
    opts["extractor_args"] = {"youtube": {"lang": ["pt"]}}
    if clientes:
        opts["extractor_args"]["youtube"]["player_client"] = clientes
    return yt_dlp.YoutubeDL(opts)


def listar_videos(canal, n, log):
    """Os n mais novos de cada aba do canal (ao vivo e videos), sem baixar nada."""
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        log.append("yt-dlp nao instalado")
        return []
    vistos, lista = set(), []
    for aba in ("streams", "videos"):
        try:
            with _ydl({"extract_flat": "in_playlist", "playlistend": n}) as y:
                info = y.extract_info(f"{canal.rstrip('/')}/{aba}", download=False)
        except Exception as e:
            log.append(f"lista {aba}: {type(e).__name__}: {str(e)[:200]}")
            continue
        for e in (info or {}).get("entries") or []:
            if e.get("id") and e["id"] not in vistos:
                vistos.add(e["id"])
                lista.append({"id": e["id"], "titulo": e.get("title"), "aba": aba})
    return lista


def videos_do_rss(canal, log):
    """Feed RSS do canal: os 15 mais novos com titulo e descricao originais (e o plano B se a listagem falhar)."""
    try:
        pagina = http_get(canal, timeout=60).text
        cid = re.search(r'"(?:externalId|channelId)":"(UC[\w-]{22})"', pagina) or re.search(r"channel/(UC[\w-]{22})", pagina)
        xml = http_get(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid.group(1)}", timeout=60).text
    except Exception as e:
        log.append(f"rss: {type(e).__name__}: {str(e)[:200]}")
        return []
    lista = []
    for bloco in re.findall(r"(?s)<entry>(.*?)</entry>", xml):
        vid = re.search(r"<yt:videoId>([\w-]{11})</yt:videoId>", bloco)
        if not vid:
            continue
        tit = re.search(r"(?s)<title>(.*?)</title>", bloco)
        pub = re.search(r"<published>([\d-]{10})", bloco)
        desc = re.search(r"(?s)<media:description>(.*?)</media:description>", bloco)
        lista.append({"id": vid.group(1), "titulo": html.unescape(tit.group(1)) if tit else None, "aba": "rss",
                      "data": pub.group(1) if pub else None,
                      "descricao": html.unescape(desc.group(1))[:3000] if desc else ""})
    return lista


def legenda_do_video(vid, pasta_tmp):
    """Metadados e legenda em portugues (a manual se houver, senao a automatica). Devolve (info, vtt, tipo, lingua).
    So conclui "sem legenda" quando nenhum cliente lista legenda; legenda listada e nao entregue vira erro."""
    url = f"https://www.youtube.com/watch?v={vid}"
    ultimo, melhor, listada = "sem tentativa", None, False
    for clientes in CLIENTES_YT:
        nome = "/".join(clientes or ["padrao"])
        for f in os.listdir(pasta_tmp):
            if f.startswith(vid):
                os.remove(os.path.join(pasta_tmp, f))
        try:
            with _ydl({"writesubtitles": True, "writeautomaticsub": True, "subtitleslangs": ["pt.*"],
                       "subtitlesformat": "vtt", "outtmpl": os.path.join(pasta_tmp, "%(id)s.%(ext)s"),
                       "sleep_interval_subtitles": 1}, clientes) as y:
                info = y.extract_info(url, download=True)
        except Exception as e:
            ultimo = f"{nome}: {type(e).__name__}: {str(e)[:220]}"
            continue
        if melhor is None or (info.get("duration") and not melhor.get("duration")):
            melhor = info
        manuais = set((info.get("subtitles") or {}).keys())
        achados = {f.split(".")[-2]: os.path.join(pasta_tmp, f) for f in os.listdir(pasta_tmp)
                   if f.startswith(vid + ".") and f.endswith(".vtt")}
        ordem = sorted(achados, key=lambda l: (l not in manuais, l != "pt-orig", l != "pt", l))
        if ordem:
            lingua = ordem[0]
            with open(achados[lingua], encoding="utf-8", errors="replace") as f:
                return info, f.read(), ("manual" if lingua in manuais else "automatica"), lingua
        if info.get("automatic_captions") or info.get("subtitles"):
            listada = True
            ultimo = f"{nome}: legenda listada mas nao entregue (o YouTube pede PO token)"
        else:
            ultimo = f"{nome}: nenhuma legenda listada"
    if melhor is not None and not listada:
        return melhor, None, None, None
    raise RuntimeError(ultimo)


def videos_do_site(log):
    """IDs de video embutidos na pagina de videos do site da Kinea (lista curada pela gestora)."""
    try:
        return sorted(set(RX_YOUTUBE.findall(http_get(f"{SITE}/videos/", timeout=60, educado=True).text)))
    except Exception as e:
        log.append(f"pagina de videos do site: {e}")
        return []


def _fora_do_tema(titulo):
    t = titulo or ""
    return bool(RX_VIDEO_FORA.search(t)) and not RX_VIDEO_DENTRO.search(t)


def coletar_videos(saida, canal, n, dias, falhas):
    pasta = os.path.join(saida, "videos")
    os.makedirs(pasta, exist_ok=True)
    antigo = {}
    try:
        antigo = {v["id"]: v for v in json.load(open(os.path.join(pasta, "index.json"), encoding="utf-8"))["videos"]}
    except Exception:
        pass
    log = []
    lista = listar_videos(canal, n, log)
    origem = "yt-dlp"
    # O RSS do canal traz titulo e descricao originais (sem traducao) dos 15 mais novos
    rss = {v["id"]: v for v in videos_do_rss(canal, log)}
    if not lista:
        lista, origem = list(rss.values()), "rss"
    vistos = {v["id"] for v in lista}
    lista += [{"id": v, "titulo": None, "aba": "site"} for v in videos_do_site(log) if v not in vistos]
    print(f"== videos: {len(lista)} listados ({origem}, rss com {len(rss)}) em {canal}", flush=True)
    limite = (datetime.date.today() - datetime.timedelta(days=dias)).isoformat()
    velhos_na_aba, videos, fora = set(), [], 0
    with tempfile.TemporaryDirectory() as tmp:
        for item in lista:
            vid, aba = item["id"], item["aba"]
            r = rss.get(vid) or {}
            titulo = r.get("titulo") or item.get("titulo")
            if _fora_do_tema(titulo):
                fora += 1
                continue
            v = antigo.get(vid)
            if v and (v.get("chars") or (v.get("legenda") == "sem legenda" and v.get("coleta") == 2)):
                videos.append(v)
                continue
            if aba in velhos_na_aba:
                continue
            entrada = {"id": vid, "titulo": titulo, "aba": aba, "url": f"https://www.youtube.com/watch?v={vid}",
                       "data": r.get("data") or item.get("data"), "descricao": r.get("descricao") or item.get("descricao", ""),
                       "coleta": 2}
            try:
                info, vtt, tipo, lingua = legenda_do_video(vid, tmp)
                d = info.get("upload_date") or info.get("release_date") or ""
                entrada.update({"titulo": r.get("titulo") or info.get("title") or entrada["titulo"],
                                "data": f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else entrada["data"],
                                "duracao_min": round((info.get("duration") or 0) / 60) or None,
                                "descricao": (r.get("descricao") or info.get("description") or entrada["descricao"] or "")[:3000],
                                "capitulos": [{"t": int(c.get("start_time") or 0), "titulo": c.get("title")}
                                              for c in info.get("chapters") or []],
                                "ao_vivo": info.get("was_live") or info.get("live_status") in ("was_live", "post_live")})
            except Exception as e:
                entrada["erro"] = str(e)[:300]
                vtt = tipo = lingua = None
            if entrada.get("data") and entrada["data"] < limite:
                if aba != "site":
                    velhos_na_aba.add(aba)  # a aba vem do mais novo ao mais antigo: o resto e mais velho ainda
                continue
            if vtt:
                texto = texto_da_legenda(vtt)
                arquivo = f"{entrada.get('data') or 'sem-data'}_{vid}.txt"
                with open(os.path.join(pasta, arquivo), "w", encoding="utf-8") as f:
                    f.write(f"# {entrada['titulo']}\n# {entrada['url']} | {entrada.get('data')} | "
                            f"{entrada.get('duracao_min') or '?'} min | legenda {tipo} ({lingua})\n\n{texto}\n")
                entrada.update({"arquivo": f"kinea/videos/{arquivo}", "legenda": tipo, "lingua": lingua, "chars": len(texto)})
            elif "erro" not in entrada:
                entrada["legenda"] = "sem legenda"
            videos.append(entrada)
            print(f"  {entrada.get('data') or '?'} {str(entrada.get('titulo'))[:70]}: "
                  f"{entrada.get('legenda') or 'falhou'} {entrada.get('chars', 0):,} chars "
                  f"{(entrada.get('erro') or '')[:120]}", flush=True)
            time.sleep(2)
    # Os que ja estavam guardados e sairam da lista dos mais novos continuam (ate 120 videos)
    ids = {v["id"] for v in videos}
    videos += [v for k, v in antigo.items() if k not in ids and v.get("chars")]
    videos.sort(key=lambda v: v.get("data") or "", reverse=True)
    videos = videos[:120]
    no_indice = {os.path.basename(v["arquivo"]) for v in videos if v.get("arquivo")}
    for nome in os.listdir(pasta):
        if nome.endswith(".txt") and nome not in no_indice:
            os.remove(os.path.join(pasta, nome))
    erros = [v for v in videos if v.get("erro")]
    if erros and not any(v.get("chars") for v in videos):
        falhas.append(f"videos: nenhuma legenda baixada; ultimo erro: {erros[0]['erro'][:200]}")
    with open(os.path.join(pasta, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"gerado_em": agora(), "canal": canal, "listagem": origem, "fora_do_tema": fora,
                   "fonte": "YouTube (legenda publicada pelo proprio YouTube; a automatica e transcricao de maquina "
                            "e pode errar nome proprio)", "videos": videos, "log": log[:40]}, f, ensure_ascii=False, indent=1)
    return {"videos": len(videos), "com_legenda": sum(1 for v in videos if v.get("chars")), "erros": len(erros),
            "fora_do_tema": fora, "listagem": origem}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--saida", required=True, help="pasta de saida (no Actions: dados_branch/kinea)")
    ap.add_argument("--dados", default=None, help="raiz do branch dados, para ler acoes emitidas (padrao: pasta acima da saida)")
    ap.add_argument("--meses", type=int, default=12, help="quantos meses de CDA, dos mais novos")
    ap.add_argument("--tickers", default=",".join(CONSTRUTORAS), help="tickers acompanhados fundo a fundo")
    ap.add_argument("--cartas-desde", default="2025-07", help="mes de referencia inicial das cartas (AAAA-MM)")
    ap.add_argument("--urls", default="", help="URLs extras de PDF de carta, separadas por espaco")
    ap.add_argument("--familias", default="multimercado,acoes", help="familias de carta a guardar (multimercado, acoes, renda_fixa, infra, outros)")
    ap.add_argument("--partes", default="cda,cartas,midia", help="o que coletar: cda, cartas, midia (videos, documentos, imagens)")
    ap.add_argument("--so-cartas", action="store_true", help="atalho antigo para --partes cartas")
    ap.add_argument("--so-cda", action="store_true", help="atalho antigo para --partes cda")
    ap.add_argument("--canal", default=CANAL, help="canal da Kinea no YouTube")
    ap.add_argument("--videos", type=int, default=20, help="quantos videos mais novos por aba do canal (ao vivo e videos)")
    ap.add_argument("--videos-dias", type=int, default=200, help="ignora video mais velho que isso")
    ap.add_argument("--docs-desde", default="2026-01", help="mes inicial dos documentos avulsos do site (AAAA-MM)")
    a = ap.parse_args(argv)
    partes = {p.strip() for p in a.partes.split(",") if p.strip()}
    if a.so_cartas:
        partes = {"cartas"}
    if a.so_cda:
        partes = {"cda"}
    os.makedirs(a.saida, exist_ok=True)
    dados_dir = a.dados or os.path.dirname(os.path.abspath(a.saida.rstrip("/")))
    alvo = [t.strip().upper() for t in re.split(r"[,\s]+", a.tickers) if t.strip()]
    # O manifest guarda a ultima rodada de cada parte: rodar so as cartas nao apaga o registro da CDA
    try:
        manifest = json.load(open(os.path.join(a.saida, "manifest.json"), encoding="utf-8"))
    except Exception:
        manifest = {}
    manifest.setdefault("partes", {})
    manifest.update({"gerado_em": agora(), "rodou": sorted(partes)})
    falhas = []

    def registra(nome, fn):
        try:
            r = fn()
        except Exception as e:
            falhas.append(f"{nome}: {type(e).__name__}: {e}")
            r = "falhou"
        manifest["partes"][nome] = {"em": agora(), "resultado": r}

    if "cda" in partes:
        def _cda():
            cda = coletar_cda(a.meses, alvo, dados_dir, falhas)
            if not cda:
                return "falhou"
            with open(os.path.join(a.saida, "cda.json"), "w", encoding="utf-8") as f:
                json.dump(cda, f, ensure_ascii=False, separators=(",", ":"))
            return {"meses": cda["meses"], "posicoes": len(cda["posicoes"])}
        registra("cda", _cda)
    if "cartas" in partes:
        familias = tuple(f.strip() for f in a.familias.split(",") if f.strip())
        registra("cartas", lambda: coletar_cartas(a.saida, a.cartas_desde, a.urls.split(), falhas, familias))
    if "midia" in partes:
        registra("documentos", lambda: coletar_documentos(a.saida, a.docs_desde, falhas))
        registra("videos", lambda: coletar_videos(a.saida, a.canal, a.videos, a.videos_dias, falhas))
    manifest["falhas"] = falhas
    with open(os.path.join(a.saida, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(json.dumps(manifest, ensure_ascii=False, indent=1)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
