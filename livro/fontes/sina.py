"""Proxies asiaticos de commodities via Sina (hq.sinajs.cn), sempre rotulados:
SP0 = celulose SHFE (fibra LONGA, CNY/t) - proxy direcional, NAO e BHKP;
I0 = minerio de ferro Dalian (CNY/t). Codigo I0 a confirmar na sonda."""

from __future__ import annotations

import re
from datetime import datetime

from livro.http import Cliente, HttpError

URL = "https://hq.sinajs.cn/list={codigo}"
HEADERS = {"Referer": "https://finance.sina.com.cn/"}
PROXIES = {
    "SHFE_SP": {"codigo": "nf_SP0", "rotulo": "celulose SHFE (fibra longa, CNY/t) - proxy; nao e BHKP"},
    "DCE_I0": {"codigo": "nf_I0", "rotulo": "minerio de ferro Dalian (CNY/t) - proxy"},
}


def parse(texto: str) -> dict:
    m = re.search(r'="(.*)"', texto)
    if not m:
        raise ValueError("payload Sina inesperado")
    campos = m.group(1).split(",")
    if len(campos) < 18:
        raise ValueError("payload Sina curto")
    return {"preco": float(campos[8]) if campos[8] else None, "data": campos[17], "campos": len(campos)}


def coletar(cli: Cliente | None = None) -> dict:
    cli = cli or Cliente(impersonate=False)
    out, falhas = {}, []
    for pid, cfg in PROXIES.items():
        try:
            r = cli.get(URL.format(codigo=cfg["codigo"]), headers=HEADERS, timeout=20)
            if r.status != 200:
                raise HttpError(r.status, r.text, URL)
            dados = parse(r.content.decode("gbk", errors="replace"))
            out[pid] = {**dados, "rotulo": cfg["rotulo"], "codigo": cfg["codigo"]}
        except Exception as e:
            falhas.append(f"{pid}: {type(e).__name__}: {str(e)[:60]}")
    return {"proxies": out, "falhas": falhas, "coletado_em": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}


# ---------------------------------------------------------------- CNY/t -> US$/t
# O Douglas pediu celulose e minerio em dolar. O que existe de graca e diario sao
# os futuros asiaticos em CNY: converte-se pelo USD/CNY (CNY=X) do MESMO dia, e o
# rotulo de proxy anda junto com o numero.
ITENS_USD = {
    "CELULOSE_LONGA": {"proxy": "SHFE_SP", "nome": "Celulose fibra longa",
                       "rotulo": "futuro SP da SHFE (fibra longa) em CNY/t convertido; nao e preco de lista NBSK"},
    "MINERIO_DALIAN": {"proxy": "DCE_I0", "nome": "Minerio de ferro Dalian",
                       "rotulo": "futuro da DCE em CNY/t convertido; o CFR 62% em US$ e a linha MINERIO"},
}


def _taxa_em(fx_df, data: str):
    """USD/CNY do dia, ou do pregao anterior mais proximo."""
    import pandas as pd
    if fx_df is None or len(fx_df) == 0:
        return None
    col = "adj" if "adj" in fx_df.columns else "close"
    try:
        v = fx_df[col].asof(pd.Timestamp(data))
    except (KeyError, TypeError, ValueError):
        return None
    return float(v) if v is not None and not pd.isna(v) and float(v) > 0 else None


def em_dolar(proxies: dict, fx_df=None, hoje=None) -> dict:
    """Serie em US$/t de cada proxy asiatico + a fibra curta (BHKP) semanal.

    Devolve {id: {nome, rotulo, unidade, usd, cny, fx, data, pontos, janelas}}.
    `janelas` so aparece com dois pontos ou mais: o historico dos proxies comeca
    no dia em que o livro entrou no ar, e dia/semana/mes vao preenchendo."""
    from livro import indicadores as ind
    out = {}
    hist = proxies.get("historico") or {}
    atuais = proxies.get("proxies") or {}
    for pid, cfg in ITENS_USD.items():
        pontos = []
        for data, cny in (hist.get(cfg["proxy"]) or []):
            taxa = _taxa_em(fx_df, data)
            if taxa and cny:
                pontos.append((data, float(cny) / taxa))
        atual = atuais.get(cfg["proxy"]) or {}
        if not pontos and not atual.get("preco"):
            continue
        item = {"nome": cfg["nome"], "rotulo": cfg["rotulo"], "unidade": "US$/t",
                "cny": atual.get("preco"), "data": atual.get("data"), "pontos": len(pontos)}
        if atual.get("data"):
            item["fx"] = _taxa_em(fx_df, atual["data"])
        if pontos:
            item["usd"] = pontos[-1][1]
            item["data"] = pontos[-1][0]
            if len(pontos) >= 2:
                df = ind.de_precos([d for d, _ in pontos], [v for _, v in pontos])
                item["janelas"] = ind.janelas(df, ate=hoje)
        elif item.get("fx") and atual.get("preco"):
            item["usd"] = float(atual["preco"]) / item["fx"]
        out[pid] = item
    bhkp, ant = proxies.get("bhkp_semanal"), proxies.get("bhkp_anterior")
    if bhkp and bhkp.get("valor"):
        item = {"nome": "Celulose fibra curta (BHKP)", "unidade": "US$/t", "semanal": True,
                "usd": bhkp.get("valor"), "data": bhkp.get("data"), "fonte": bhkp.get("fonte"),
                "rotulo": "preco semanal citado em fonte publica; nao ha serie diaria gratuita"}
        if ant and ant.get("valor"):
            item["variacao"] = float(bhkp["valor"]) / float(ant["valor"]) - 1
            item["anterior"] = ant.get("valor")
        out["CELULOSE_CURTA"] = item
    return out
