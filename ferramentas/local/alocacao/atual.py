"""Carteira atual do cliente: leitura do extrato (planilha ou PDF) e mapeamento para as 14 classes.

A leitura e a identificacao de fundos reaproveitam o `raiox` do terminal (mesma planilha modelo, mesma base de
fundos da CVM). Aqui entra so o que o raio-x nao faz: dizer em qual das 14 classes de alocacao cada posicao cai,
com a razao e a confianca, para o Douglas corrigir o que ficou duvidoso (arquivo `mapa.csv` na pasta do cliente:
`nome como esta no extrato;id_da_classe`).
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

from . import config as C


def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.lower().strip())


def _raiox():
    if str(C.TERMINAL) not in sys.path:
        sys.path.insert(0, str(C.TERMINAL))
    try:
        from raiox import base, entrada  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"nao consegui carregar o raio-x do terminal em {C.TERMINAL}: {e}") from e
    return entrada, base


ETF_RV_BR = {"BOVA11", "SMAL11", "DIVO11", "BOVV11", "PIBB11", "BRAX11", "ECOO11", "FIND11", "MATB11", "ISUS11", "GOVE11"}
ETF_RV_INT = {"IVVB11", "NASD11", "SPXI11", "WRLD11", "EURP11", "XINA11", "ACWI11", "TECK11", "BNDX11", "USTK11"}
ETF_OURO = {"GOLD11", "OZ1D11"}
ETF_CRIPTO = {"HASH11", "QBTC11", "BITH11", "ETHE11", "QETH11", "SOLH11", "XRPH11", "BITI11"}
ETF_IPCA = {"IMAB11", "B5P211", "IB5M11", "IMBB11", "NTNB11", "IMAB11"}
ETF_PRE = {"IRFM11", "FIXA11", "PREF11"}
ETF_POS = {"LFTS11", "FIXA11", "SELIC11"}

_RE_PRE = re.compile(r"^\s*(?:pre|prefixad\w*)\b|\b(pre|prefixad\w*)\b|^\s*\d+[,.]?\d*\s*%\s*(a\.?a\.?)?\s*$")


def _indexador(p: dict) -> str:
    """pos | ipca | pre, lido do nome e da coluna de taxa."""
    t = _norm(" ".join(str(p.get(k) or "") for k in ("nome", "taxa", "tipo")))
    if "ipca" in t or "ntn-b" in t or "ntnb" in t or "inflacao" in t or "igpm" in t or "igp-m" in t:
        return "ipca"
    if "cdi" in t or "selic" in t or "di +" in t or "pos" in t.split():
        return "pos"
    if re.search(r"\b(pre|prefixad\w*)\b", t) or re.search(r"(?<![\d,.])\d{1,2}[,.]\d{1,2}\s*%\s*(a\.?a\.?)?\s*$", _norm(p.get("taxa"))):
        return "pre"
    return "pos"


def classe_da_posicao(p: dict) -> tuple[str, str, str]:
    """(classe, motivo, confianca) para uma posicao ja classificada pelo raio-x."""
    nome = _norm(p.get("nome"))
    t = p.get("tipo_raiox") or "outro"
    tk = (p.get("ticker") or "").upper()
    cat = _norm((p.get("fundo") or {}).get("categoria"))
    blob = f" {nome} {cat} "

    if t == "caixa":
        return "caixa", "conta/saldo disponivel", "alta"
    if t == "tesouro":
        if "selic" in blob or "lft" in blob:
            return "caixa", "Tesouro Selic funciona como caixa", "alta"
        if any(k in blob for k in ("ipca", "ntn-b", "ntnb", "renda+", "educa+")):
            return "ipca_trib", "Tesouro IPCA+", "alta"
        if any(k in blob for k in ("prefixado", "ltn", "ntn-f")):
            return "pre_trib", "Tesouro Prefixado", "alta"
        return "ipca_trib", "titulo publico sem indexador legivel: confira", "baixa"
    if t == "previdencia":
        return "vgbl", "previdencia", "alta"
    if t == "coe":
        if any(k in blob for k in ("s&p", "nasdaq", "acoes", "exterior", "global", "bolsa")):
            return "rv_int", "COE atrelado a bolsa externa", "media"
        return "mm", "COE: estrategia estruturada, tratado como multimercado", "baixa"
    if t == "bancario":
        isento = any(k in blob for k in ("lca", "lci", "lig", "lcd", "letra de credito")) and "lf" not in blob.split()
        idx = _indexador(p)
        cid = {"pos": "pos_isenta" if isento else "pos_trib", "ipca": "ipca_isenta" if isento else "ipca_trib",
               "pre": "pre_isenta" if isento else "pre_trib"}[idx]
        return cid, f"produto bancario {'isento' if isento else 'tributavel'} {idx}", "alta" if p.get("taxa") else "media"
    if t == "credito":
        isento = any(k in blob for k in ("cri", "cra", "incentivad", "infra", "12.431", "12431"))
        idx = _indexador(p)
        cid = {"pos": "pos_isenta" if isento else "pos_trib", "ipca": "ipca_isenta" if isento else "ipca_trib",
               "pre": "pre_isenta" if isento else "pre_trib"}[idx]
        return cid, f"credito privado {'isento' if isento else 'tributavel'} {idx}", "media"
    if t == "acao":
        return "rv_br", "acao da B3", "alta"
    if t == "bdr":
        return "rv_int", "BDR (ativo no exterior)", "alta"
    if t == "fii":
        return "fii", "fundo imobiliario", "alta"
    if t == "etf":
        if tk in ETF_OURO: return "alt_ouro", "ETF de ouro", "alta"
        if tk in ETF_CRIPTO: return "cripto", "ETF de cripto", "alta"
        if tk in ETF_RV_INT: return "rv_int", "ETF de bolsa no exterior", "alta"
        if tk in ETF_IPCA: return "ipca_trib", "ETF de titulos IPCA+", "media"
        if tk in ETF_PRE: return "pre_trib", "ETF de pre-fixados", "media"
        if tk in ETF_POS: return "pos_trib", "ETF pos-fixado", "media"
        if tk in ETF_RV_BR: return "rv_br", "ETF de bolsa brasileira", "alta"
        return "rv_br", "ETF nao reconhecido: confira", "baixa"
    if t in ("fundo", "outro"):
        if any(k in blob for k in ("fii", "fundos imobiliarios", "imobiliario")) and tk.endswith("11"):
            return "fii", "fundo imobiliario", "media"
        if any(k in blob for k in ("bitcoin", "cripto", "crypto", "ethereum")):
            return "cripto", "fundo de cripto", "media"
        if any(k in blob for k in ("ouro", "gold")):
            return "alt_ouro", "fundo de ouro", "media"
        if any(k in blob for k in ("exterior", "global", "internacional", "nasdaq", "s&p", "ucits", "world", "mundo", "dolar", "cambial")):
            return "rv_int", "fundo com exposicao ao exterior/dolar", "media"
        if any(k in blob for k in ("infra", "incentivad")):
            return "ipca_isenta", "fundo de infraestrutura (debentures incentivadas)", "media"
        if "previdencia" in blob:
            return "vgbl", "previdencia", "alta"
        if "multimercado" in blob or " fim " in blob or "macro" in blob or "long short" in blob or "long & short" in blob:
            return "mm", "multimercado", "alta" if "multimercado" in cat else "media"
        if "acoes" in blob or " fia " in blob or "small caps" in blob or "dividendos" in blob:
            return "rv_br", "fundo de acoes", "alta" if "acoes" in cat else "media"
        if "renda fixa" in blob or " rf " in blob or "di " in blob or "credito privado" in blob or "fidc" in blob:
            if "inflacao" in blob or "ipca" in blob or "ima-b" in blob or "ima b" in blob:
                return "ipca_trib", "fundo de renda fixa indexado a inflacao", "media"
            if re.search(r"\b(pre|prefixad\w*|irf-m)\b", blob):
                return "pre_trib", "fundo de renda fixa pre-fixada", "media"
            return "pos_trib", "fundo de renda fixa pos-fixada/credito", "media"
        return "mm", "fundo nao classificado: tratado como multimercado, confira", "baixa"
    return "mm", "posicao nao reconhecida: confira", "baixa"


def _ler_mapa(pasta: Path) -> dict[str, str]:
    arq = Path(pasta) / "mapa.csv"
    out = {}
    if arq.exists():
        for ln in arq.read_text(encoding="utf-8-sig").splitlines():
            if ";" in ln:
                a, b = ln.split(";", 1)
                if b.strip() in C.POR_ID:
                    out[_norm(a)] = b.strip()
    return out


def importar(arquivo: Path, pasta_cliente: Path | None = None) -> dict:
    """Le o extrato, classifica e devolve a carteira atual por classe, com emissores, FGC e escada de prazo."""
    entrada, base = _raiox()
    arquivo = Path(arquivo)
    brutas = entrada.ler(arquivo)
    ajuste_cnpj = entrada.ajustes(arquivo.parent)
    mapa = _ler_mapa(pasta_cliente or arquivo.parent)
    posicoes, a_conferir = [], []
    for p in brutas:
        q = base.classificar(p, ajuste_cnpj)
        cid, motivo, conf = classe_da_posicao(q)
        forcado = mapa.get(_norm(q.get("nome")))
        if forcado:
            cid, motivo, conf = forcado, "classe definida no mapa.csv", "alta"
        item = {"nome": q.get("nome"), "valor": float(q.get("valor") or 0.0), "classe": cid, "motivo": motivo,
                "confianca": conf, "emissor": q.get("emi_nome"), "fgc": bool(q.get("fgc")),
                "prazo_dias": q.get("prazo"), "vencimento": q.get("vencimento"), "taxa": q.get("taxa"),
                "tipo_raiox": q.get("tipo_raiox")}
        posicoes.append(item)
        if conf == "baixa" or q.get("aviso"):
            a_conferir.append(f"{item['nome']}: {q.get('aviso') or motivo} -> {C.POR_ID[cid].curto}")
    total = sum(x["valor"] for x in posicoes)
    valores = {cid: 0.0 for cid in C.IDS}
    for x in posicoes:
        valores[x["classe"]] += x["valor"]
    pesos = {cid: (v / total if total else 0.0) for cid, v in valores.items()}
    emissores: dict[str, float] = {}
    fgc_por_emissor: dict[str, float] = {}
    for x in posicoes:
        if x["emissor"] and x["tipo_raiox"] in ("bancario", "credito", "coe"):
            emissores[x["emissor"]] = emissores.get(x["emissor"], 0.0) + x["valor"]
        if x["fgc"] and x["emissor"]:
            fgc_por_emissor[x["emissor"]] = fgc_por_emissor.get(x["emissor"], 0.0) + x["valor"]
    escada = {"ate_5d": 0.0, "ate_30d": 0.0, "ate_90d": 0.0, "ate_360d": 0.0, "mais": 0.0}
    for x in posicoes:
        d = x["prazo_dias"]
        d = 9999 if d is None else d
        k = "ate_5d" if d <= 5 else "ate_30d" if d <= 30 else "ate_90d" if d <= 90 else "ate_360d" if d <= 360 else "mais"
        escada[k] += x["valor"]
    return {"arquivo": str(arquivo), "total": total, "posicoes": posicoes, "valores": valores, "pesos": pesos,
            "emissores": emissores, "fgc_por_emissor": fgc_por_emissor, "escada": escada, "a_conferir": a_conferir}
