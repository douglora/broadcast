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
