"""Leitura do dia que o runner ja entrega pronta: setores, "por que mexeu", Brent em
reais, participacao relevante, volume e extremos de 52 semanas.

Pedido do Douglas em 23/09 ("trazer mais dados e insights valiosos"), priorizado pela
auditoria de 23/09 com juiz independente. Tudo aqui e conta simples sobre numeros que
ja passaram pelo portao de qualidade: nada usa "dia" nao confirmado, e nenhuma causa
e inventada. Quando nao ha causa no dado, a linha diz "sem causa no dado; investigar".

Exemplo que motivou o formato (23/09): CURY3 -3,8%, DIRR3 -3,4%, MRVE3 -1,3%, com o DI
F30 +12 bps. A DIRR3 tinha no dia um aviso de participacao da BlackRock (5,08%), que
nao explica queda nenhuma; o que explica e o setor e o juro."""

from __future__ import annotations

import re
import statistics

from livro import fmt
from livro import indicadores as ind

LIMIAR_MOVIMENTO = 0.02      # |dia| a partir do qual o papel entra no "por que mexeu"
MAX_POR_QUE = 8


# ------------------------------------------------------------ setores
def _rotulo_fator(fator: str | None, ins: dict, janelas: dict) -> str:
    if not fator:
        return ""
    if fator.startswith("DI1F"):
        d = ((ins.get("di") or {}).get("deltas") or {}).get(fator)
        return f"DI F{fator[4:]} {fmt.bps(d)} bps" if d is not None else ""
    j = janelas.get(fator) or {}
    if j.get("dia") is not None and j.get("dia_confirmado", True):
        return f"{fator} {fmt.pct(j['dia'])}"
    return ""


def cestas(universo, janelas: dict, ins: dict) -> list[dict]:
    """Mediana do dia, quantos subiram e cairam e quem destoou, por cesta. So entra
    membro com dia confirmado (um pregao, dado ok)."""
    out = []
    for c in getattr(universo, "cestas", []) or []:
        membros = [(m, janelas[m]["dia"]) for m in c.get("membros", [])
                   if m in janelas and janelas[m].get("dia") is not None and janelas[m].get("dia_confirmado", True)]
        fora = [m for m in c.get("membros", []) if m not in dict(membros)]
        if len(membros) < 3:
            continue
        med = statistics.median(v for _, v in membros)
        destoou = max(membros, key=lambda x: abs(x[1] - med))
        if abs(destoou[1] - med) < 0.01:
            destoou = (None, None)       # todos a menos de 1 p.p. da mediana: ninguem destoou
        out.append({"id": c["id"], "titulo": c.get("titulo", c["id"]), "n": len(membros), "mediana": med,
                    "subiram": sum(1 for _, v in membros if v > 0), "cairam": sum(1 for _, v in membros if v < 0),
                    "destoou": ({"id": destoou[0], "dia": destoou[1], "desvio": destoou[1] - med} if destoou[0] else {}),
                    "fator": _rotulo_fator(c.get("fator"), ins, janelas), "membros": membros, "fora": fora,
                    "no_livro": [m for m, _ in membros if universo.por_id(m)]})
    return out


# ------------------------------------------------------------ participacao relevante
_MESES = {"janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
          "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}


def participacao(doc: dict) -> dict | None:
    """Aviso de participacao relevante (art. 12 da Resolucao CVM 44): quem, quanto,
    quando cruzou e o objetivo declarado. None se o documento nao e desse tipo.
    O texto da CVM vem com espacos no meio das palavras ("s etembro"), entao a busca
    tolera espaco."""
    txt = " ".join(str(doc.get(k) or "") for k in ("assunto", "tipo", "texto"))
    if not re.search(r"participa[cç][aã]o\s+acion[aá]ria\s+relevante|art(igo|\.)?\s*12\s+da\s+Resolu", txt, re.I):
        return None
    plano = re.sub(r"\s+", " ", txt)
    out = {"subtipo": "participacao_relevante"}
    m = re.search(r"correspond[eê]ncia d[ao]s? ([A-Z][\w&.,' -]{2,60}?)(?:\s*\(|,| sediad| com sede| inscrit)", plano)
    if m:
        out["detentor"] = m.group(1).strip(" ,")
    m = re.search(r"(\d{1,3}(?:[.,]\d{3})+|\d+)\s+a[cç][oõ]es\s+ordin[aá]rias", plano, re.I)
    if m:
        out["quantidade"] = int(re.sub(r"\D", "", m.group(1)))
    m = re.search(r"(?:aproximadamente|cerca de)?\s*(\d{1,2}[.,]\d{1,3})\s*%", plano)
    if m:
        out["percentual"] = float(m.group(1).replace(",", "."))
    m = re.search(r"em\s+(\d{1,2})\s+de\s+([a-zç ]{4,12}?)\s+de\s+(\d{4})", plano, re.I)
    if m:
        mes = _MESES.get(m.group(2).replace(" ", "").lower())
        if mes:
            out["data_cruzamento"] = f"{m.group(3)}-{mes:02d}-{int(m.group(1)):02d}"
    # direcao so pelo corpo do documento: o campo "tipo" da CVM e sempre
    # "Aquisicao/Alienacao de Participacao" e fazia a BlackRock "reduzir" na DIRR3
    corpo = re.sub(r"\s+", " ", str(doc.get("texto") or doc.get("assunto") or ""))
    corpo = re.sub(r"aquisi[cç][aã]o\s*/\s*aliena[cç][aã]o", "", corpo, flags=re.I)
    if re.search(r"configurando aliena|aliena[cç][aã]o de participa|redu[cç][aã]o de participa|reduziu|"
                 r"passaram a ser inferiores|inferior a 5", corpo, re.I):
        out["direcao"] = "reduziu"
    elif re.search(r"configurando aquisi|aquisi[cç][aã]o de participa|passaram a ser de|atingiu|ultrapass", corpo, re.I):
        out["direcao"] = "aumentou"
    out["objetivo_investimento"] = bool(re.search(r"estritamente de investimento|n[aã]o objetiva(ndo)? altera[cç][aã]o do controle", plano, re.I))
    return out


def texto_participacao(p: dict) -> str:
    quem = p.get("detentor") or "gestor"
    pct = f"{fmt.num(p['percentual'], 2)}%" if p.get("percentual") is not None else "participação relevante"
    quando = f" em {fmt.data_br(p['data_cruzamento'])}" if p.get("data_cruzamento") else ""
    verbo = "reduziu para" if p.get("direcao") == "reduziu" else "passou a ter"
    return f"{quem} {verbo} {pct}{quando}" + (" (objetivo: só investimento)" if p.get("objetivo_investimento") else "")


# ------------------------------------------------------------ por que mexeu
def _docs_do_dia(eventos: dict, do_dia: list[dict], hoje_iso: str) -> dict:
    """Documentos CVM/SEC do dia por ativo. Vem dos alertas E03/E04 do dia inteiro (o
    fechamento so ve na coleta os documentos NOVOS; o aviso da BlackRock de 09h50 tinha
    sido visto no intradia) e, para o que chegou agora, da propria coleta."""
    out: dict = {}
    vistos = set()
    for a in do_dia or []:
        if a.get("regra") not in ("E03", "E04") or not a.get("ativo") or str(a.get("data") or "")[:10] != hoje_iso:
            continue
        dd = a.get("dados") or {}
        chave = dd.get("id_item") or a.get("id")
        vistos.add(chave)
        if a["regra"] == "E03":
            out.setdefault(a["ativo"], []).append(("cvm", {"categoria": dd.get("categoria"), "assunto": dd.get("manchete"),
                                                           "participacao": dd.get("participacao")}))
        else:
            out.setdefault(a["ativo"], []).append(("sec", {"form": "8-K", "itens_rotulo": [str(a.get("titulo") or "")[:60]]}))
    for d in (eventos or {}).get("cvm") or []:
        if d.get("ativo") and str(d.get("data") or "")[:10] == hoje_iso and d.get("id") not in vistos:
            out.setdefault(d["ativo"], []).append(("cvm", d))
    for f in (eventos or {}).get("sec") or []:
        if f.get("ativo") and str(f.get("aceito_em") or f.get("data") or "")[:10] == hoje_iso and f.get("id") not in vistos:
            out.setdefault(f["ativo"], []).append(("sec", f))
    return out


def por_que_mexeu(universo, janelas: dict, setores: list[dict], eventos: dict, do_dia: list[dict],
                  hoje_iso: str, limiar: float = LIMIAR_MOVIMENTO) -> list[dict]:
    """Para cada papel que andou >= 2% com dia confirmado: as camadas de explicacao que
    o dado sustenta, em ordem, e o grau. Nunca soma efeitos; nunca inventa causa."""
    docs = _docs_do_dia(eventos, do_dia, hoje_iso)
    noticias = {}
    for a in do_dia or []:
        if a.get("regra") == "E05" and a.get("ativo"):
            noticias.setdefault(a["ativo"], []).append(a)
    t05 = {a.get("ativo") for a in do_dia or [] if a.get("regra") == "T05"}
    cesta_de = {}
    for s in setores:
        for m, _ in s["membros"]:
            cesta_de.setdefault(m, s)
    pares = {p["a"]: p["b"] for p in (getattr(universo, "pares", None) or [])
             if p.get("tipo") in ("produtor_commodity", "distribuidor_commodity")}
    itens = []
    for a in universo.ativos:
        j = janelas.get(a.id) or {}
        dia = j.get("dia")
        # commodity, cambio, indice e cripto sao os drivers: explicam, nao sao explicados aqui
        if dia is None or not j.get("dia_confirmado", True) or a.proxy or a.classe in ("fx", "indice", "cripto", "commodity"):
            continue
        if abs(dia) < limiar and a.id not in t05:
            continue
        camadas, grau = [], None
        s = cesta_de.get(a.id)
        if s and s["n"] >= 3:
            med = s["mediana"]
            junto = (med * dia > 0) and abs(dia - med) <= max(0.015, 0.5 * abs(dia))
            txt = f"{s['titulo'].lower()} {fmt.pct(med)} (mediana)" + (f", {s['fator']}" if s.get("fator") else "")
            if junto:
                camadas.append("andou com o setor: " + txt)
                grau = grau or "setorial"
            else:
                camadas.append(f"descolou do setor ({txt}; diferença {fmt.pct(dia - med)})")
        b = pares.get(a.id)
        if b:
            jb = janelas.get(b) or {}
            if jb.get("dia") is not None and jb.get("dia_confirmado", True) and abs(jb["dia"]) >= 0.01:
                if jb["dia"] * dia > 0:
                    camadas.append(f"acompanhou o {universo.por_id(b).apelido if universo.por_id(b) else b} ({fmt.pct(jb['dia'])})")
                    grau = grau or "driver"
                else:
                    camadas.append(f"contra o {universo.por_id(b).apelido if universo.por_id(b) else b} ({fmt.pct(jb['dia'])})")
        for tipo, d in docs.get(a.id, []):
            if tipo == "cvm":
                p = d.get("participacao") or participacao(d)
                if p:
                    camadas.append("aviso de participação: " + texto_participacao(p) + "; não costuma explicar o preço do dia")
                else:
                    camadas.append(f"{d.get('categoria', 'documento')} na CVM: {str(d.get('assunto') or d.get('tipo') or '')[:70]}")
                    if d.get("categoria") == "Fato Relevante":
                        grau = "documento"
            else:
                camadas.append(f"{d.get('form', '8-K')} na SEC: {', '.join(d.get('itens_rotulo') or [])[:70]}")
                grau = grau or "documento"
        for n in noticias.get(a.id, [])[:1]:
            camadas.append("notícia: " + str((n.get("dados") or {}).get("manchete") or n.get("titulo") or "")[:90])
            grau = grau or "notícia (conferir)"
        if not camadas or grau is None:
            if not any(c.startswith(("andou com", "acompanhou")) for c in camadas):
                grau = "sem causa no dado"
                camadas.append("investigar antes de comentar")
        itens.append({"id": a.id, "dia": dia, "explicacao": "; ".join(camadas), "grau": grau})
    itens.sort(key=lambda x: abs(x["dia"]), reverse=True)
    return itens[:MAX_POR_QUE]


# ------------------------------------------------------------ Brent em reais, volume, extremos
def brent_reais(janelas: dict) -> dict:
    """Brent em R$ por barril = Brent (US$) x dolar. So com as duas pontas confirmadas e
    na mesma data; senao, diz qual perna falta."""
    b, u = janelas.get("BRENT") or {}, janelas.get("USDBRL") or {}
    if not b or not u:
        return {}
    falta = [n for n, j in (("Brent", b), ("dólar", u)) if not j.get("dia_confirmado", True)]
    if falta or b.get("data") != u.get("data"):
        return {"a_confirmar": " e ".join(falta) or f"datas diferentes ({b.get('data')} e {u.get('data')})"}
    out = {"data": b["data"], "valor": b["ultimo"] * u["ultimo"]}
    for k in ("dia", "1m", "ytd"):
        if b.get(k) is not None and u.get(k) is not None:
            out[k] = (1 + b[k]) * (1 + u[k]) - 1
    return out


def qualidade_dia(df, ate=None) -> dict:
    """Volume do dia contra a media dos 20 anteriores e onde o preco fechou na amplitude
    do dia (0 = na minima, 1 = na maxima). So com barra completa (volume > 0, maxima
    acima da minima): a barra provisoria da B3 apos o leilao nao tem esses campos."""
    if df is None or len(df) < 22:
        return {}
    d = df.loc[:ind.pd.Timestamp(ate)] if ate is not None else df
    if len(d) < 22:
        return {}
    u = d.iloc[-1]
    vol, h, l, c = u.get("volume"), u.get("high"), u.get("low"), u.get("close")
    if not vol or vol <= 0 or h is None or l is None or not (h > l > 0):
        return {}
    media = d["volume"].iloc[-21:-1]
    media = media[media > 0].mean()
    out = {}
    if media and media > 0:
        out["vol_rel20"] = float(vol / media)
    out["pos_fech"] = float((c - l) / (h - l))
    return out


def extremo_52s(df, ate=None) -> str:
    d = df.loc[:ind.pd.Timestamp(ate)] if ate is not None else df
    if d is None or len(d) < 200:
        return ""
    s = d["close"].iloc[-252:]
    c = float(s.iloc[-1])
    if c <= float(s.min()):
        return "mínima de 52 semanas"
    if c >= float(s.max()):
        return "máxima de 52 semanas"
    return ""


def contexto_curto(j: dict) -> str:
    """'vol 1,4x · fechou na mínima' para os Destaques."""
    partes = []
    if j.get("vol_rel20") is not None and (j["vol_rel20"] >= 1.3 or j["vol_rel20"] <= 0.6):
        partes.append(f"vol {fmt.num(j['vol_rel20'], 1)}x")
    p = j.get("pos_fech")
    if p is not None:
        if p <= 0.15:
            partes.append("fechou na mínima")
        elif p >= 0.85:
            partes.append("fechou na máxima")
    if j.get("extremo_52s"):
        partes.append(j["extremo_52s"])
    return " · ".join(partes)
