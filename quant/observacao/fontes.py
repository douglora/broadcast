"""
Leitura (so leitura) do que o terminal guarda em cache/out. Tudo tolerante: arquivo ausente ou estragado vira None ou
serie vazia, nunca excecao. O caminho do terminal vem de AUTOPILOT_TERMINAL (padrao ~/Desktop/terminal-artefato).
"""
import json
import os
import sqlite3

import pandas as pd


def raiz():
    return os.path.expanduser(os.environ.get("AUTOPILOT_TERMINAL", "~/Desktop/terminal-artefato"))


def cache_out():
    return os.path.join(raiz(), "cache", "out")


def _json(caminho):
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def serie(simbolo, campo="c", pasta=None):
    """Serie diaria (indice = data) de hist/<SIMBOLO>.json. `campo`: c (fechamento), ac (ajustado), o, h, l, v; sem o campo
    pedido, tenta tx/taxa (Tesouro Direto, DI1) e c."""
    d = _json(os.path.join(pasta or os.path.join(cache_out(), "hist"), f"{simbolo}.json"))
    if not isinstance(d, dict) or not isinstance(d.get("t"), list):
        return pd.Series(dtype=float)
    campo = next((k for k in (campo, "tx", "taxa", "c", "ac") if isinstance(d.get(k), list) and len(d[k]) == len(d["t"])), None)
    if campo is None:
        return pd.Series(dtype=float)
    s = pd.Series(d[campo], index=pd.to_datetime(d["t"]), dtype=float).dropna()
    return s[~s.index.duplicated(keep="last")].sort_index()


def rf(pasta=None):
    return _json(os.path.join(pasta or cache_out(), "rf.json")) or {}


def macro(pasta=None):
    return _json(os.path.join(pasta or cache_out(), "macro.json")) or {}


def indicador(id_, m=None):
    """{valor, data, anterior} de um indicador de macro.json pelo id (selic_meta, treasury_10a, vix...)."""
    for x in (m if m is not None else macro()).get("indicadores") or []:
        if x.get("id") == id_:
            return x
    return None


def focus(indicador_nome="IPCA", ano=None, m=None):
    """Item do Focus (mediana, ha_1_sem, ha_4_sem) para o indicador e o ano (padrao: o ano corrente do arquivo)."""
    f = (m if m is not None else macro()).get("focus") or {}
    itens = [x for x in f.get("itens") or [] if x.get("indicador") == indicador_nome]
    if not itens:
        return None
    if ano is None:
        ano = min(int(x.get("ano") or 0) for x in itens if x.get("ano"))
    for x in itens:
        if int(x.get("ano") or 0) == int(ano):
            return dict(x, focus_data=f.get("data"))
    return None


def spread_serie(chave="hy", r=None):
    """Serie diaria de um spread de rf.json (hy, ig, real10, implicita10), em pontos percentuais."""
    s = ((r if r is not None else rf()).get("spreads") or {}).get("series") or {}
    v = s.get(chave)
    if isinstance(v, dict) and isinstance(v.get("t"), list):
        vals = v.get("v") if isinstance(v.get("v"), list) else v.get("y")
        if isinstance(vals, list) and len(vals) == len(v["t"]):
            return pd.Series(vals, index=pd.to_datetime(v["t"]), dtype=float).dropna().sort_index()
    if isinstance(v, list) and v and isinstance(v[0], (list, tuple)) and len(v[0]) >= 2:
        return pd.Series([float(x[1]) for x in v], index=pd.to_datetime([x[0] for x in v])).dropna().sort_index()
    return pd.Series(dtype=float)


def di_taxa(du_alvo=504, r=None):
    """Taxa da curva DI de hoje interpolada no prazo `du_alvo` (dias uteis; 504 = ~2 anos), e a data. (taxa, data) ou (None, None)."""
    di = (r if r is not None else rf()).get("di") or {}
    curva = (di.get("curvas") or {}).get("hoje")
    if not isinstance(curva, list) or len(curva) < 2:
        return None, None
    pts = sorted((float(a), float(b)) for a, b in curva if a is not None and b is not None)
    if du_alvo <= pts[0][0]:
        return pts[0][1], di.get("data")
    for (d0, t0), (d1, t1) in zip(pts, pts[1:]):
        if d0 <= du_alvo <= d1:
            return t0 + (t1 - t0) * (du_alvo - d0) / max(d1 - d0, 1e-9), di.get("data")
    return pts[-1][1], di.get("data")


def fluxo_estrangeiro(pasta=None):
    """Serie diaria do saldo do investidor estrangeiro na B3 (R$), de b3.json (bloco fluxo.serie_dia)."""
    b = _json(os.path.join(pasta or cache_out(), "b3.json")) or {}
    sd = (b.get("fluxo") or {}).get("serie_dia") or {}
    t = sd.get("t") if isinstance(sd, dict) else None
    if not isinstance(t, list):
        return pd.Series(dtype=float)
    vals = None
    for k in ("estrangeiro", "saldo", "v", "y", "valor"):
        if isinstance(sd.get(k), list) and len(sd[k]) == len(t):
            vals = sd[k]
            break
    if vals is None:
        for k, v in sd.items():
            if k != "t" and isinstance(v, list) and len(v) == len(t) and all(isinstance(x, (int, float)) or x is None for x in v):
                vals = v
                break
    if vals is None:
        return pd.Series(dtype=float)
    return pd.Series(vals, index=pd.to_datetime(t), dtype=float).dropna().sort_index()


def wirp(pasta=None):
    return _json(os.path.join(pasta or cache_out(), "pagina", "wirp.json")) or {}


def copom_proximo(w=None):
    """(data, movimento implicito em bps) da proxima reuniao do Copom, pelo wirp.json; (None, None) sem dado."""
    c = (w if w is not None else wirp()).get("copom") or {}
    for r in c.get("reunioes") or []:
        if not isinstance(r, dict):
            continue
        data = r.get("data") or r.get("dia")
        bps = next((r[k] for k in ("movimento_bps", "implicito_bps", "bps", "esperado_bps", "passo_bps") if isinstance(r.get(k), (int, float))), None)
        if data:
            return str(data)[:10], bps
    return None, None


def tabela_terminal():
    """A tabela do leitor do terminal (quant.terminal): uma linha por ticker. None quando o terminal nao responde."""
    try:
        from quant import terminal
        if not terminal.disponivel():
            return None
        return terminal.tabela()
    except Exception:
        return None


def cartas_tom(hoje, meses=3, caminho=None):
    """Tom das cartas de gestores dos ultimos `meses`: paginas com palavras de cautela contra paginas com palavras de
    oportunidade, no indice local (cache/cartas/cartas.sqlite, so leitura). {cautela, oportunidade, docs} ou None."""
    arq = caminho or os.path.join(raiz(), "cache", "cartas", "cartas.sqlite")
    if not os.path.exists(arq):
        return None
    desde = (pd.Timestamp(hoje) - pd.DateOffset(months=meses)).strftime("%Y-%m")
    try:
        c = sqlite3.connect(f"file:{arq}?mode=ro", uri=True)
        q = ("SELECT count(*) FROM paginas p JOIN docs d ON d.id = p.doc_id WHERE substr(d.data, 1, 7) >= ? AND paginas MATCH ?")
        cautela = c.execute(q, (desde, "cautela OR cautelos* OR defensiv* OR reduzimos OR reduz* OR risco")).fetchone()[0]
        oport = c.execute(q, (desde, "oportunidade* OR construtiv* OR aumentamos OR otimist* OR assimetri*")).fetchone()[0]
        docs = c.execute("SELECT count(*) FROM docs WHERE substr(data, 1, 7) >= ?", (desde,)).fetchone()[0]
        c.close()
        return {"cautela": int(cautela), "oportunidade": int(oport), "docs": int(docs), "desde": desde}
    except sqlite3.Error:
        return None
