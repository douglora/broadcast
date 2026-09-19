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


# ---------------------------------------------------------------- RAD (consulta externa, intradiario)
RAD_URL = "https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx/ListarDocumentos"
RAD_PAGINA = "https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx"
_TR = re.compile(r"(?is)<tr[^>]*>(.*?)</tr>")
_TD = re.compile(r"(?is)<td[^>]*>(.*?)</td>")
_TAGS = re.compile(r"<[^>]+>")


def _limpa(s: str) -> str:
    import html as _h
    return re.sub(r"\s+", " ", _h.unescape(_TAGS.sub(" ", s or ""))).strip()


def rad_corpo(de: date, ate: date, categoria: str = "TODAS", periodo: str = "2", extras: dict | None = None) -> str:
    import json
    corpo = {
        "dataDe": de.strftime("%d/%m/%Y"), "dataAte": ate.strftime("%d/%m/%Y"), "empresa": "",
        "setorAtividade": "-1", "categoriaEmissor": "-1", "situacaoEmissor": "-1", "tipoParticipante": "-1",
        "dataReferencia": "", "categoria": categoria, "periodo": periodo, "horaIni": "", "horaFim": "",
        "palavraChave": "", "ultimaDtRef": "false", "tipoApresentacao": "-1", "especieDocumento": "-1",
        "token": "", "versaoCaptcha": "", "tipoEmpresa": "0",
    }
    corpo.update(extras or {})
    return json.dumps(corpo)


_FALTA_PARAM = re.compile(r"missing value for parameter: \W*([A-Za-z_]+)")


def parse_rad_html(html_rows: str) -> list[dict]:
    """Linhas da tabela da consulta externa: codigo CVM, empresa, categoria, tipo,
    especie, data de referencia, data de entrega, protocolo (do link do IPE)."""
    linhas = []
    for tr in _TR.findall(html_rows or ""):
        tds = _TD.findall(tr)
        if len(tds) < 7:
            continue
        cel = [_limpa(x) for x in tds]
        m = re.search(r"NumeroProtocoloEntrega=(\d+)", tr)
        prot = m.group(1) if m else ""
        linhas.append({
            "codigo": cel[0].lstrip("0"), "empresa": cel[1], "categoria": cel[2], "tipo": cel[3], "especie": cel[4],
            "data_referencia": data_iso(cel[5]), "entregue_em": cel[6], "data": data_iso(cel[6]), "protocolo": prot,
            "link": f"https://www.rad.cvm.gov.br/ENET/frmExibirArquivoIPEExterno.aspx?NumeroProtocoloEntrega={prot}" if prot else "",
        })
    return linhas


def _rad_post(cli: Cliente, corpo: str) -> tuple[int, str]:
    r = cli.post(RAD_URL, data=corpo,
                 headers={"Content-Type": "application/json; charset=UTF-8", "X-Requested-With": "XMLHttpRequest",
                          "Referer": RAD_PAGINA, "Accept": "application/json, text/javascript, */*; q=0.01"}, timeout=60)
    return r.status, r.text


def _rad_parse(texto: str) -> tuple[str, dict]:
    """Devolve (html das linhas, meta). O WebMethod responde {"d": {"dados": "<tr>..", ...}}
    ou {"d": "<tr>.."}; em erro, {"Message": "..."}."""
    import json
    meta: dict = {}
    try:
        payload = json.loads(texto)
    except ValueError:
        return (texto if "<tr" in texto else ""), meta
    if isinstance(payload, dict) and "Message" in payload and "d" not in payload:
        meta["mensagem"] = str(payload.get("Message"))[:200]
        return "", meta
    d = payload.get("d", payload) if isinstance(payload, dict) else payload
    if isinstance(d, dict):
        meta["total_registros"] = d.get("totalRegistros") or d.get("TotalRegistros")
        return (d.get("dados") or d.get("Dados") or ""), meta
    if isinstance(d, str):
        return d, meta
    return "", meta


_DATA_HORA = re.compile(r"^(\d{2}/\d{2}/\d{4})(?:\s+(\d{2}:\d{2}))?$")
_SEPARADORES = ["$&&*", "$&&&$", "$&&$", "\r\n", "\n", "$$$"]   # o RAD real usa '$&&*' entre registros
CATEGORIAS_RAD = {"Fato Relevante", "Comunicado ao Mercado", "Aviso aos Acionistas", "Assembleia", "Valores Mobiliários Negociados e Detidos",
                  "Reunião da Administração", "Calendário de Eventos Corporativos", "Política de Negociação", "Dados Econômico-Financeiros",
                  "Documentos de Oferta de Distribuição Pública", "Comunicado sobre Transações entre Partes Relacionadas", "Outros Comunicados",
                  "Apresentações a analistas/agentes do mercado", "Estatuto Social", "Escrituras e aditamentos de debêntures", "Informe do Código de Governança"}


def parse_rad_dados(dados: str) -> tuple[list[dict], dict]:
    """O WebMethod devolve `dados` como string com campos separados por '$&'
    (codigo CVM com DV, empresa, categoria, tipo, especie, datas, ...). O separador
    de registro e detectado entre os candidatos; a ordem dos campos e inferida:
    categoria = campo com nome de categoria conhecido, datas = campos dd/mm/aaaa
    (a segunda, com hora, e a entrega), protocolo = NumeroProtocoloEntrega= ou o
    ultimo campo so de digitos."""
    diag: dict = {"tamanho": len(dados or "")}
    if not dados:
        return [], diag
    contagens = {s: dados.count(s) for s in _SEPARADORES}
    sep = max(contagens, key=contagens.get) if max(contagens.values()) > 0 else None
    diag["separador"] = sep
    diag["contagens"] = {k: v for k, v in contagens.items() if v}
    registros = dados.split(sep) if sep else [dados]
    linhas = []
    for reg in registros:
        if "$&" not in reg:
            continue
        campos = [_limpa(re.sub(r"(?is)<spanorder>.*?</spanorder>", "", c)) for c in reg.split("$&")]
        if len(campos) < 5:
            continue
        cat = next((c for c in campos if c in CATEGORIAS_RAD), None)
        if cat is None:
            cat = next((c for c in campos[2:5] if c and c != "-"), campos[2] if len(campos) > 2 else "")
        i_cat = campos.index(cat) if cat in campos else 2
        datas = [(i, m) for i, c in enumerate(campos) if (m := _DATA_HORA.match(c))]
        entrega = next(((i, m) for i, m in datas if m.group(2)), datas[-1] if datas else None)
        ref = next(((i, m) for i, m in datas if entrega is None or i != entrega[0]), None)
        m = re.search(r"NumeroProtocoloEntrega=(\d+)", reg)
        prot = m.group(1) if m else next((c for c in reversed(campos) if c.isdigit() and len(c) >= 5), "")
        i_fim = entrega[0] if entrega else (ref[0] if ref else len(campos))
        meio = [c for c in campos[i_cat + 1:i_fim] if c and c != "-" and "<" not in c and not _DATA_HORA.match(c)]
        codigo = re.sub(r"\D", "", campos[0]).lstrip("0")
        md = re.search(r"OpenDownloadDocumentos\('(\d+)','(\d+)','(\d+)','(\w+)'\)", reg)
        download = (f"https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?Tela=ext&numSequencia={md.group(1)}"
                    f"&numVersao={md.group(2)}&numProtocolo={md.group(3)}&descTipo={md.group(4)}&CodigoInstituicao=1") if md else ""
        linhas.append({
            "codigo": codigo, "empresa": campos[1], "categoria": cat, "tipo": meio[0] if meio else "",
            "especie": meio[1] if len(meio) > 1 else "",
            "data_referencia": data_iso(ref[1].group(1)) if ref else "",
            "entregue_em": (entrega[1].group(0) if entrega else ""), "data": data_iso(entrega[1].group(1)) if entrega else "",
            "protocolo": prot, "download": download,
            "link": f"https://www.rad.cvm.gov.br/ENET/frmExibirArquivoIPEExterno.aspx?NumeroProtocoloEntrega={prot}" if prot else "",
        })
    diag["registros"] = len(registros)
    diag["primeiros"] = [[c[:60] for c in r.split("$&")][:14] for r in registros[:2]]
    diag["amostra"] = dados[:1500]
    return linhas, diag


def rad_listar(cli: Cliente, de: date, ate: date, max_tentativas: int = 14) -> dict:
    """POST no WebMethod da consulta externa. O servico exige o conjunto exato de
    parametros: quando a resposta acusa 'missing value for parameter X', o
    parametro entra com '0' e a chamada repete; combinacoes de categoria/periodo/
    tipoEmpresa sao tentadas ate vir linha. Tudo fica em `diagnostico.tentativas`."""
    from collections import Counter
    diag: dict = {"url": RAD_URL, "de": de.isoformat(), "ate": ate.isoformat(), "tentativas": []}
    extras: dict = {}
    combos = [("TODAS", "2", "0"), ("IPE_-1_-1_-1", "2", "0"), ("TODAS", "1", "0")]
    linhas: list[dict] = []
    n = 0
    for categoria, periodo, tipo_emp in combos:
        repetir = True
        while repetir and n < max_tentativas:
            repetir = False
            n += 1
            corpo = rad_corpo(de, ate, categoria, periodo, {**extras, "tipoEmpresa": tipo_emp})
            try:
                status, texto = _rad_post(cli, corpo)
            except HttpError as e:
                diag["tentativas"].append({"categoria": categoria, "periodo": periodo, "tipoEmpresa": tipo_emp, "erro": str(e)[:120]})
                continue
            html_rows, meta = _rad_parse(texto)
            if "<tr" in (html_rows or ""):
                linhas = parse_rad_html(html_rows)
            else:
                linhas, dd = parse_rad_dados(html_rows or "")
                meta = {**meta, "dados": dd}
            t = {"categoria": categoria, "periodo": periodo, "tipoEmpresa": tipo_emp, "status": status,
                 "linhas": len(linhas), **meta, "inicio": texto[:220]}
            diag["tentativas"].append(t)
            falta = _FALTA_PARAM.search(meta.get("mensagem") or texto.replace("\\u0027", "'")) if (status != 200 or "Message" in texto[:60]) else None
            if falta and falta.group(1) not in extras:
                extras[falta.group(1)] = "0"
                repetir = True
                continue
            if status == 200 and linhas:
                diag.update({"status": status, "linhas": len(linhas), "categoria": categoria, "periodo": periodo,
                             "tipoEmpresa": tipo_emp, "extras": extras,
                             "categorias": dict(Counter(l["categoria"] for l in linhas).most_common(10))})
                return {"linhas": linhas, "diagnostico": diag}
    diag.update({"status": "sem linhas", "linhas": 0, "extras": extras})
    return {"linhas": [], "diagnostico": diag}


def docs_de_linhas(linhas: list[dict], alvos: dict, desde: date, categorias: dict | None = None) -> tuple[list[dict], dict]:
    """Mesmo casamento do IPE (codigo ou nucleo do nome) sobre as linhas do RAD."""
    categorias = categorias or CATEGORIAS_PADRAO
    por_codigo = {str(v.get("codigo")): a for a, v in alvos.items() if v.get("codigo")}
    por_nome = {nucleo(n): a for a, v in alvos.items() for n in v.get("nomes", [])}
    docs, casadas = [], {}
    for l in linhas:
        if not l["data"] or l["data"] < desde.isoformat() or l["categoria"] not in categorias:
            continue
        ativo = por_codigo.get(l["codigo"]) or por_nome.get(nucleo(l["empresa"]))
        if not ativo:
            continue
        casadas.setdefault(ativo, set()).add(l["empresa"])
        sev = categorias[l["categoria"]]
        assunto = l.get("tipo") or l["categoria"]
        if l["categoria"] == "Comunicado ao Mercado" and COMUNICADO_FORTE.search(assunto):
            sev = "atencao"
        prot = l["protocolo"] or hashlib.sha1(f"{l['empresa']}|{l['entregue_em']}|{assunto}".encode()).hexdigest()[:8]
        docs.append({"id": f"CVM-{ativo}-{prot}", "ativo": ativo, "empresa": l["empresa"], "codigo": l["codigo"],
                     "categoria": l["categoria"], "tipo": l["tipo"], "especie": l["especie"], "assunto": assunto[:300],
                     "data": l["data"], "entregue_em": l["entregue_em"], "link": l["link"], "protocolo": prot,
                     "download": l.get("download", ""), "severidade": sev, "versao": "", "origem": "rad"})
    return docs, {a: sorted(v) for a, v in casadas.items()}


def assunto_de_texto(texto: str | None, categoria: str = "", empresa: str = "") -> str:
    """Primeira frase util do documento (pula cabecalho com CNPJ, nome da companhia e
    o titulo 'FATO RELEVANTE'), para o RAD que nao traz o campo Assunto."""
    if not texto:
        return ""
    nuc_emp = nucleo(empresa)
    # tira o cabecalho: linhas em caixa alta, CNPJ/NIRE, 'Companhia Aberta', titulo do documento
    linhas_uteis = []
    for l in texto.split("\n"):
        s = l.strip()
        if not s:
            continue
        n = normalizar(s)
        cabecalho = (not re.search(r"[a-zà-ú]", s)) or re.search(r"CNPJ|NIRE|COMPANHIA ABERTA|CAPITAL ABERTO|C[OÓ]DIGO CVM", n) \
            or n.startswith(("FATO RELEVANTE", "COMUNICADO AO MERCADO", "AVISO AOS ACIONISTAS"))
        if cabecalho and (not linhas_uteis or len(s) < 60):
            continue
        linhas_uteis.append(s)
    corpo = " ".join(linhas_uteis)
    # abreviacoes juridicas nao encerram frase: art. 157, nº 6.404, S.A., Ltda., Cia.
    corpo = re.sub(r"(?i)\b(arts?|n[º°o]|inc|par|res|sr|sra|dr|dra|ltda|cia|s\.a|s/a)\.\s+", lambda m: m.group(0).rstrip() + "\x01", corpo)
    candidatas = []
    for bruto in re.split(r"(?<=[.!?:])\s+", corpo):
        l = re.sub(r"\s+", " ", bruto.replace("\x01", " ")).strip(" -–•*")
        if len(l) < 25 or not re.search(r"[a-zà-ú]", l) or re.match(r"^\d", l):   # cabecalho ou fragmento numerico nao e assunto
            continue
        n = normalizar(l)
        if re.search(r"CNPJ|NIRE|COMPANHIA ABERTA|CAPITAL ABERTO|C[OÓ]DIGO CVM", n) or n.startswith(("FATO RELEVANTE", "COMUNICADO AO MERCADO", "AVISO AOS ACIONISTAS")):
            continue
        if nuc_emp and n.startswith(nuc_emp) and len(n) < len(nuc_emp) + 15:
            continue
        # rodape de PDF do RI (site, e-mail, telefone, 'para mais informacoes') nao e assunto
        if re.search(r"(?i)(www\.|https?://|\S+@\S+|para mais informa|demais informa[cç][oõ]es|"
                     r"rela[cç][oõ]es com investidores|\+55\s*\(?\d|tel\.?\s*:?\s*\+?\d)", l):
            continue
        candidatas.append(l)
        if len(candidatas) >= 6:
            break
    if not candidatas:
        return ""
    escolhida = next((c for c in candidatas if re.search(r"(?i)\b(informa|comunica|anuncia|aprov\w*|celebr\w*|conclu\w*|assin\w*|receb\w*|divulg\w*|esclarec\w*|decid\w*|autoriz\w*|vem informar|vêm informar)\b", c)), candidatas[0])
    # corta o preambulo juridico: fica o que vem depois de 'informar que' / 'comunicar que' / 'que'
    m = re.search(r"(?i)\b(?:informar|comunicar|informa|comunica|anuncia)\s+(?:aos? seus acionistas e ao mercado em geral\s+)?que\s+(.*)", escolhida)
    preambulo = escolhida[: m.start()] if m else ""
    juridico = re.search(r"(?i)em atendimento|nos termos|\bLei\b|\bart\.|Resolu[cç][aã]o|Instru[cç][aã]o", preambulo) is not None
    if m and len(m.group(1)) >= 20 and (m.start() > 120 or juridico):
        escolhida = m.group(1)[0].upper() + m.group(1)[1:]
    return escolhida[:160].rstrip(",;")


def texto_pdf(cli: Cliente, link: str, max_bytes: int = 6_000_000, max_chars: int = 8000,
              alternativas: list[str] | None = None, diag: dict | None = None) -> str | None:
    """Texto do PDF do IPE (pypdf). Tenta o link de exibicao e, se nao vier PDF, as
    URLs alternativas (download direto). `diag` recebe status, tipo e inicio de
    cada resposta para ajustar no run real."""
    for url in [u for u in [link] + list(alternativas or []) if u]:
        try:
            r = cli.get(url, timeout=60)
        except HttpError as e:
            if diag is not None:
                diag[url[:80]] = f"erro {str(e)[:60]}"
            continue
        tipo = (r.headers or {}).get("content-type", "")
        if diag is not None:
            diag[url[:80]] = f"{r.status} {tipo[:40]} {len(r.content)}B {r.content[:60]!r}"
        if r.status != 200 or not r.content or len(r.content) > max_bytes:
            continue
        txt = texto_de_pdf_bytes(r.content, max_chars)
        if txt:
            return txt
        # pagina HTML com o PDF embutido (iframe/object/meta refresh)
        m = re.search(r"""(?i)(?:src|href|url)=["']?([^"'\s>]+\.pdf[^"'\s>]*)""", r.content[:20000].decode("utf-8", "ignore"))
        if m:
            alvo = m.group(1)
            if alvo.startswith("/"):
                alvo = "https://www.rad.cvm.gov.br" + alvo
            elif not alvo.startswith("http"):
                alvo = "https://www.rad.cvm.gov.br/ENET/" + alvo
            try:
                r2 = cli.get(alvo, timeout=60)
                if diag is not None:
                    diag[alvo[:80]] = f"{r2.status} {(r2.headers or {}).get('content-type', '')[:40]} {len(r2.content)}B"
                if r2.status == 200:
                    txt = texto_de_pdf_bytes(r2.content, max_chars)
                    if txt:
                        return txt
            except HttpError:
                pass
    return None


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
            categorias: dict | None = None, vistos: dict | None = None, max_pdf: int = 8, com_ipe: bool = True) -> dict:
    """Documentos novos (id nao visto) das companhias do livro nos ultimos `dias`,
    com o texto do PDF para fato relevante e comunicado forte."""
    cli = cli or Cliente(impersonate=False)
    hoje = hoje or datetime.now(timezone.utc).date()
    vistos = dict(vistos or {})
    desde = hoje - timedelta(days=dias)
    anos = {hoje.year, desde.year}
    docs, casadas, falhas, diag = [], {}, {}, {}
    # 1) intradiario: consulta externa (RAD) para a janela
    try:
        rad = rad_listar(cli, desde, hoje)
        diag["rad"] = rad["diagnostico"]
        d, c = docs_de_linhas(rad["linhas"], alvos, desde, categorias)
        docs += d
        for a, nomes in c.items():
            casadas[a] = sorted(set(casadas.get(a, [])) | set(nomes))
    except Exception as e:
        diag["rad"] = {"erro": f"{type(e).__name__}: {str(e)[:100]}"}
    # 2) base aberta (IPE, atraso de dias): completa o que o RAD nao trouxe
    for ano in (sorted(anos) if com_ipe else []):
        texto = baixar_ipe(cli, ano)
        if not texto:
            falhas[f"ipe_{ano}"] = "IPE indisponivel"
            continue
        try:
            diag[str(ano)] = diagnostico(texto, desde)
        except Exception as e:
            diag[str(ano)] = {"erro": f"{type(e).__name__}: {str(e)[:80]}"}
        d, c = parse_ipe(texto, alvos, desde, categorias)
        ja = {x["id"] for x in docs}
        docs += [x for x in d if x["id"] not in ja]
        for a, nomes in c.items():
            casadas.setdefault(a, [])
            casadas[a] = sorted(set(casadas[a]) | set(nomes))
    docs.sort(key=lambda d: (d.get("entregue_em") or "", d["id"]), reverse=True)
    novos = [d for d in docs if d["id"] not in vistos]
    # documentos ja vistos cujo PDF ainda nao foi lido: tenta de novo (ate 3 vezes) e devolve como 'atualizado'
    retentar = [d for d in docs if d["id"] in vistos and vistos[d["id"]].get("texto") is not True
                and vistos[d["id"]].get("tentativas", 0) < 3
                and (d["categoria"] == "Fato Relevante" or d["severidade"] == "atencao")]
    lidos = 0

    def _ler(d: dict) -> None:
        d["pdf_diag"] = {}
        d["texto"] = texto_pdf(cli, d["link"], alternativas=[d.get("download", "")], diag=d["pdf_diag"])
        if d.get("texto") and (not d.get("assunto") or d["assunto"] == d["categoria"] or d.get("origem") == "rad"):
            novo = assunto_de_texto(d["texto"], d["categoria"], d.get("empresa", ""))
            if novo:
                d["assunto"] = novo

    for d in novos:
        d["texto"] = None
        quer_pdf = d["categoria"] == "Fato Relevante" or d["severidade"] == "atencao"
        if lidos < max_pdf and quer_pdf:
            _ler(d)
            lidos += 1
        vistos[d["id"]] = {"data": d["data"], "texto": (bool(d.get("texto")) if quer_pdf else None), "tentativas": 1 if quer_pdf else 0}
    atualizados = []
    for d in retentar:
        if lidos >= max_pdf:
            break
        _ler(d)
        lidos += 1
        v = vistos[d["id"]]
        v["tentativas"] = v.get("tentativas", 0) + 1
        if d.get("texto"):
            v["texto"] = True
            d["atualizado"] = True
            atualizados.append(d)
    limite = (hoje - timedelta(days=15)).isoformat()
    vistos = {k: v for k, v in vistos.items() if (v.get("data") or "9999") >= limite}
    return {"docs": novos + atualizados, "todos": len(docs), "empresas_casadas": casadas, "falhas": falhas, "vistos": vistos,
            "atualizados": len(atualizados), "retentados": len(retentar),
            "diagnostico": diag, "coletado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
