"""Material de analise para a Leitura da Mesa.

A sessao nao calcula numero: ela narra. Entao o que da profundidade a leitura tem
de sair daqui, do runner, ja apurado - amplitude do livro, extremos, quem esta
perto de cruzar a media longa, quem descolou do par, onde a volatilidade abriu.
Tudo derivado das mesmas series que alimentam a tabela, sem fonte nova.
"""

from __future__ import annotations

from datetime import date

from livro import indicadores as ind


def _serie(series: dict, aid: str, ate: date | None):
    df = series.get(aid)
    if df is None or len(df) == 0:
        return None
    if ate is not None:
        df = df.loc[:ind.pd.Timestamp(ate)]
    return df if len(df) else None


def amplitude(universo, series: dict, ate: date | None = None, perto: float = 0.02) -> dict:
    """Quantos ativos do livro estao acima da media de 200 dias, e quem esta na beira.

    E a medida classica de participacao: indice subindo com poucos nomes acima da
    media longa e uma alta estreita, que e uma informacao diferente de "o indice
    subiu"."""
    acima, abaixo, beira = [], [], []
    for a in universo.ativos:
        if a.classe in ("fx", "indice") or a.proxy:
            continue
        df = _serie(series, a.id, ate)
        if df is None or len(df) < 200:
            continue
        m = ind.mm(df["adj"], 200).iloc[-1]
        if m is None or ind.pd.isna(m):
            continue
        c = float(df["adj"].iloc[-1])
        dist = c / float(m) - 1.0
        (acima if dist >= 0 else abaixo).append(a.id)
        if abs(dist) <= perto:
            beira.append({"id": a.id, "distancia": dist, "lado": "acima" if dist >= 0 else "abaixo"})
    total = len(acima) + len(abaixo)
    if not total:
        return {}
    beira.sort(key=lambda x: abs(x["distancia"]))
    return {"acima": len(acima), "total": total, "pct": len(acima) / total,
            "na_beira": beira[:6], "abaixo_ids": sorted(abaixo)}


def extremos(universo, janelas: dict, chaves=("1m", "3m", "ytd", "1a"), n: int = 3) -> dict:
    """Melhores e piores do livro em cada janela, para a leitura citar nome e numero."""
    out = {}
    for k in chaves:
        itens = [(a.id, janelas[a.id].get(k)) for a in universo.ativos
                 if a.id in janelas and janelas[a.id].get(k) is not None and not a.proxy]
        if len(itens) < 4:
            continue
        itens.sort(key=lambda x: x[1], reverse=True)
        out[k] = {"melhores": itens[:n], "piores": itens[-n:][::-1]}
    return out


def por_bloco(universo, janelas: dict) -> list[dict]:
    """Mediana do bloco em cada janela: como o grupo andou, sem o outlier mandar."""
    out = []
    for b in universo.blocos:
        ativos = [a for a in universo.por_bloco(b["id"]) if a.id in janelas]
        if not ativos:
            continue
        linha = {"id": b["id"], "titulo": b["titulo"], "n": len(ativos)}
        for k in ("dia", "1m", "3m", "ytd"):
            # mediana do DIA so com quem tem dia de verdade (um pregao, dado confirmado)
            vs = sorted(v for v in (janelas[a.id].get(k) for a in ativos
                                    if k != "dia" or janelas[a.id].get("dia_confirmado", True)) if v is not None)
            if vs:
                meio = len(vs) // 2
                linha[k] = vs[meio] if len(vs) % 2 else (vs[meio - 1] + vs[meio]) / 2
        out.append(linha)
    return out


def drawdowns(universo, series: dict, ate: date | None = None, n: int = 5) -> list[dict]:
    """Distancia do topo de 52 semanas - onde o estrago ja aconteceu."""
    itens = []
    for a in universo.ativos:
        if a.proxy or a.classe in ("fx",):
            continue
        df = _serie(series, a.id, ate)
        if df is None or len(df) < 60:
            continue
        dd, pico, data_pico = ind.drawdown(df["adj"], 252)
        if dd is None:
            continue
        itens.append({"id": a.id, "drawdown": dd, "pico": pico, "data_pico": data_pico})
    itens.sort(key=lambda x: x["drawdown"])
    return itens[:n]


def vol_abrindo(universo, series: dict, ate: date | None = None, razao: float = 1.4, n: int = 5) -> list[dict]:
    """Vol de 20 dias contra a de 60: onde o mercado passou a pagar mais para carregar."""
    itens = []
    for a in universo.ativos:
        if a.proxy:
            continue
        df = _serie(series, a.id, ate)
        if df is None or len(df) < 70:
            continue
        v20, v60 = ind.vol_anualizada(df["adj"], 20), ind.vol_anualizada(df["adj"], 60)
        if not v20 or not v60:
            continue
        if v20 / v60 >= razao:
            itens.append({"id": a.id, "vol20": v20, "vol60": v60, "razao": v20 / v60})
    itens.sort(key=lambda x: x["razao"], reverse=True)
    return itens[:n]


def pares_descolados(universo, series: dict, ate: date | None = None, n: int = 4, janela: int = 20) -> list[dict]:
    """z do spread de cada par configurado: quem esta contando outra historia.

    Mesma conta da regra T11, aqui so para a leitura ter o numero na mao mesmo
    quando o alerta nao disparou."""
    itens = []
    for p in universo.pares:
        da, db = _serie(series, p["a"], ate), _serie(series, p["b"], ate)
        if da is None or db is None or len(da) < janela + 5 or len(db) < janela + 5:
            continue
        ra = ind.retornos_log(da["adj"])
        rb = ind.retornos_log(db["adj"])
        spread = (ra - rb).dropna()
        if len(spread) < janela + 2:
            continue
        acum = spread.rolling(janela).sum()
        s = acum.dropna()
        if len(s) < janela:
            continue
        desv = float(s.tail(120).std())
        if not desv:
            continue
        z = float(s.iloc[-1]) / desv
        if abs(z) >= 1.5:
            itens.append({"a": p["a"], "b": p["b"], "tipo": p.get("tipo"), "z": z,
                          "spread": float(s.iloc[-1])})
    itens.sort(key=lambda x: abs(x["z"]), reverse=True)
    return itens[:n]


def montar(universo, series: dict, janelas: dict, ate: date | None = None) -> dict:
    """Tudo junto, para `leitura_insumos["mesa"]`."""
    return {
        "amplitude": amplitude(universo, series, ate),
        "extremos": extremos(universo, janelas),
        "blocos": por_bloco(universo, janelas),
        "drawdowns": drawdowns(universo, series, ate),
        "vol_abrindo": vol_abrindo(universo, series, ate),
        "pares_descolados": pares_descolados(universo, series, ate),
    }
