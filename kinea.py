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
    kinea/manifest.json         o que rodou, o que achou e o que falhou

Uso:
    python kinea.py --saida dados_branch/kinea                       # 12 meses de carteira + cartas desde 2025-07
    python kinea.py --saida dados_branch/kinea --meses 6 --cartas-desde 2026-01
    python kinea.py --saida /tmp/k --so-cartas --urls "https://www.kinea.com.br/wp-content/uploads/2026/09/Carta-do-Gestor-Prev-Atlas-2026-08.pdf"

Fontes: dados abertos da CVM (Composicao e Diversificacao das Aplicacoes, a CDA
mensal de todo fundo) e o site da Kinea (www.kinea.com.br), onde as cartas saem
em PDF. Nada aqui e opiniao: e copia do que a CVM e a gestora publicaram.
Cada parte falha sozinha e o manifest registra o motivo.
"""

import argparse
import datetime
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
import zipfile

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


def texto_do_pdf(conteudo):
    from pypdf import PdfReader
    leitor = PdfReader(io.BytesIO(conteudo))
    paginas = [(p.extract_text() or "") for p in leitor.pages]
    return "\n\n".join(f"[p. {i + 1}] {t.strip()}" for i, t in enumerate(paginas)), len(paginas)


def coletar_cartas(saida, desde, urls_extras, falhas, max_cartas=160):
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
    escolhidas = []
    for url, meta in achadas.items():
        mes = mes_da_carta(url)
        if meta["descoberta"] != "informada" and (mes is None or mes < desde):
            continue
        escolhidas.append((mes or "", url, meta))
    escolhidas.sort(key=lambda x: (x[0], x[1]), reverse=True)
    cartas, textos = [], {}
    for mes, url, meta in escolhidas[:max_cartas]:
        arquivo = re.sub(r"[^A-Za-z0-9_.-]+", "_", os.path.basename(url.split("?")[0]))[:120]
        arquivo = re.sub(r"\.pdf$", ".txt", arquivo, flags=re.I)
        destino = os.path.join(pasta, arquivo)
        velho = antigo.get(url)
        if velho and os.path.exists(destino) and velho.get("chars"):
            cartas.append(velho)
            continue
        try:
            r = http_get(url, timeout=120, educado=True)
            texto, n_pag = texto_do_pdf(r.content)
        except Exception as e:
            falhas.append(f"carta {url}: {e}")
            continue
        with open(destino, "w", encoding="utf-8") as f:
            f.write(texto)
        h = hashlib.sha1(re.sub(r"\s+", " ", texto).encode("utf-8")).hexdigest()[:16]
        fundo = fundo_da_carta(url)
        primeira = next((l.strip() for l in texto.split("\n") if len(l.strip()) > 8), "")[:140]
        cartas.append({"arquivo": f"kinea/cartas/{arquivo}", "url": url, "fundo": fundo, "familia": familia(fundo),
                       "mes_ref": mes or None, "paginas": n_pag, "chars": len(texto), "sha1_texto": h,
                       "titulo": primeira, "descoberta": meta["descoberta"], "baixado_em": agora()})
        print(f"  {mes or '?'} {fundo}: {n_pag} p., {len(texto):,} chars")
    for c in cartas:
        textos.setdefault(c["sha1_texto"], c["arquivo"])
    for c in cartas:
        if textos[c["sha1_texto"]] != c["arquivo"]:
            c["texto_igual_a"] = textos[c["sha1_texto"]]
    cartas.sort(key=lambda c: (c.get("mes_ref") or "", c.get("fundo") or ""), reverse=True)
    idx = {"gerado_em": agora(), "fonte": f"{SITE} (PDF da Carta do Gestor, texto extraido com pypdf)",
           "desde": desde, "cartas": cartas, "metodos": metodos, "log": log[:60]}
    with open(os.path.join(pasta, "index.json"), "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)
    return {"cartas": len(cartas), "metodos": metodos, "meses": sorted({c.get("mes_ref") for c in cartas if c.get("mes_ref")})}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--saida", required=True, help="pasta de saida (no Actions: dados_branch/kinea)")
    ap.add_argument("--dados", default=None, help="raiz do branch dados, para ler acoes emitidas (padrao: pasta acima da saida)")
    ap.add_argument("--meses", type=int, default=12, help="quantos meses de CDA, dos mais novos")
    ap.add_argument("--tickers", default=",".join(CONSTRUTORAS), help="tickers acompanhados fundo a fundo")
    ap.add_argument("--cartas-desde", default="2025-07", help="mes de referencia inicial das cartas (AAAA-MM)")
    ap.add_argument("--urls", default="", help="URLs extras de PDF de carta, separadas por espaco")
    ap.add_argument("--so-cartas", action="store_true")
    ap.add_argument("--so-cda", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(a.saida, exist_ok=True)
    dados_dir = a.dados or os.path.dirname(os.path.abspath(a.saida.rstrip("/")))
    alvo = [t.strip().upper() for t in re.split(r"[,\s]+", a.tickers) if t.strip()]
    falhas, manifest = [], {"gerado_em": agora(), "partes": {}}
    if not a.so_cartas:
        cda = coletar_cda(a.meses, alvo, dados_dir, falhas)
        if cda:
            with open(os.path.join(a.saida, "cda.json"), "w", encoding="utf-8") as f:
                json.dump(cda, f, ensure_ascii=False, separators=(",", ":"))
            manifest["partes"]["cda"] = {"meses": cda["meses"], "posicoes": len(cda["posicoes"])}
        else:
            manifest["partes"]["cda"] = "falhou"
    if not a.so_cda:
        try:
            manifest["partes"]["cartas"] = coletar_cartas(a.saida, a.cartas_desde, a.urls.split(), falhas)
        except Exception as e:
            falhas.append(f"cartas: {type(e).__name__}: {e}")
            manifest["partes"]["cartas"] = "falhou"
    manifest["falhas"] = falhas
    with open(os.path.join(a.saida, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(json.dumps(manifest, ensure_ascii=False, indent=1)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
