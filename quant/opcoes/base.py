"""
Base de opcoes por dia, montada a partir do COTAHIST anual da B3 (quant/dados_brutos/cotahist/COTAHIST_AAAA.ZIP).

O COTAHIST traz uma linha por serie NEGOCIADA no dia. Nao existe linha para serie sem negocio: por isso aqui nao ha
"preco velho" no dia de entrada (toda linha tem ultimo negocio), mas tambem nao ha preco no vencimento de serie que
nao negociou: o valor na data de vencimento e calculado pelo valor intrinseco (ver motor.py).

Saidas (parquet, uma por ano, em quant/saida/pesquisa5/opcoes/dados/):
  opcoes_AAAA.parquet    uma linha por serie negociada no dia
      dia, codigo, ativo (ticker do ativo-objeto, pelo ISIN), tipo ('C' ou 'P'), exercicio (ajustado por provento NAQUELE dia),
      vencimento, fech (ultimo negocio), abre, max, min, medio, oferta_compra, oferta_venda (NaN quando nao ficou
      oferta no fechamento), negocios, quantidade, volume (R$), fatcot, mensal (vencimento mensal padrao do mes),
      semanal (codigo termina em W1..W5), europeia (codigo termina em E)
  ativo_AAAA.parquet     fechamento do ativo-objeto a vista (acoes lote padrao e ETFs): dia, ativo, isin, fech, abre, max,
      min, oferta_compra, oferta_venda, negocios, volume, fatcot

Uso:  PYTHONPATH=. .venv/bin/python -W ignore -m quant.opcoes.base --anos 2005-2026
"""
import argparse
import io
import os
import re
import sys
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from quant.comum import DIR_BRUTOS, DIR_SAIDA, garantir_dir

DIR_OPC = os.path.join(DIR_SAIDA, "pesquisa5", "opcoes")
DIR_DADOS = os.path.join(DIR_OPC, "dados")

# posicoes base-0 do layout oficial (as mesmas de quant/dados/cotahist.py)
CAMPOS = {
    "data": (2, 10), "codbdi": (10, 12), "codigo": (12, 24), "tpmerc": (24, 27), "prazot": (49, 52),
    "abe": (56, 69), "max": (69, 82), "min": (82, 95), "med": (95, 108), "fec": (108, 121),
    "bid": (121, 134), "ask": (134, 147), "negocios": (147, 152), "qtd": (152, 170), "volume": (170, 188),
    "preexe": (188, 201), "datven": (202, 210), "fatcot": (210, 217), "isin": (230, 242),
}


def _coluna(m, nome):
    a, b = CAMPOS[nome]
    return np.ascontiguousarray(m[:, a:b]).view(f"S{b - a}").ravel()


def _num(m, nome, escala=1.0):
    x = _coluna(m, nome)
    return x.astype(np.int64).astype(np.float64) / escala


def _txt(m, nome):
    return np.char.strip(_coluna(m, nome).astype(str))


def _data(m, nome):
    return pd.to_datetime(_coluna(m, nome).astype(str), format="%Y%m%d", errors="coerce")


def _linhas(raw):
    """Matriz (n, comprimento da linha) de bytes. Comprimento = 245 + fim de linha (1 ou 2)."""
    L = raw.index(b"\n") + 1
    if len(raw) % L != 0:
        raw = raw[: (len(raw) // L) * L]
    return np.frombuffer(raw, dtype=np.uint8).reshape(-1, L)


def _ler_zip(ano):
    caminho = os.path.join(DIR_BRUTOS, "cotahist", f"COTAHIST_A{ano}.ZIP")
    z = zipfile.ZipFile(caminho)
    return z.read(z.namelist()[0])


def extrair(raw):
    """Bytes do TXT do COTAHIST (anual ou diario) -> (opcoes, ativo) como DataFrames tipados."""
    m = _linhas(raw)
    tipo_reg = np.ascontiguousarray(m[:, 0:2]).view("S2").ravel()
    m = m[tipo_reg == b"01"]
    tp = _coluna(m, "tpmerc")
    bdi = _coluna(m, "codbdi")

    # ---------------- ativo-objeto a vista: acoes lote padrao (02) e ETFs/fundos listados (14) -> serie de fechamento
    sel_v = (tp == b"010") & ((bdi == b"02") | (bdi == b"14"))
    mv = m[sel_v]
    spot = pd.DataFrame({
        "dia": _data(mv, "data"), "ativo": _txt(mv, "codigo"), "isin": _txt(mv, "isin"),
        "fech": _num(mv, "fec", 100.0), "abre": _num(mv, "abe", 100.0), "max": _num(mv, "max", 100.0),
        "min": _num(mv, "min", 100.0), "oferta_compra": _num(mv, "bid", 100.0), "oferta_venda": _num(mv, "ask", 100.0),
        "negocios": _num(mv, "negocios").astype(np.int64), "volume": _num(mv, "volume", 100.0),
        "fatcot": _num(mv, "fatcot").astype(np.int64),
    })
    for c in ("oferta_compra", "oferta_venda"):
        spot.loc[spot[c] <= 0, c] = np.nan
    spot["fatcot"] = spot["fatcot"].where(spot["fatcot"] > 0, 1)

    # ---------------- opcoes de compra (070) e de venda (080) sobre acoes e ETFs (codbdi 78 = call, 82 = put)
    sel_o = ((tp == b"070") | (tp == b"080")) & ((bdi == b"78") | (bdi == b"82"))
    mo = m[sel_o]
    op = pd.DataFrame({
        "dia": _data(mo, "data"), "codigo": _txt(mo, "codigo"),
        "tipo": np.where(_coluna(mo, "tpmerc") == b"070", "C", "P"),
        "isin": _txt(mo, "isin"),
        "exercicio": _num(mo, "preexe", 100.0), "vencimento": _data(mo, "datven"),
        "fech": _num(mo, "fec", 100.0), "abre": _num(mo, "abe", 100.0), "max": _num(mo, "max", 100.0),
        "min": _num(mo, "min", 100.0), "medio": _num(mo, "med", 100.0),
        "oferta_compra": _num(mo, "bid", 100.0), "oferta_venda": _num(mo, "ask", 100.0),
        "negocios": _num(mo, "negocios").astype(np.int64), "quantidade": _num(mo, "qtd").astype(np.int64),
        "volume": _num(mo, "volume", 100.0), "fatcot": _num(mo, "fatcot").astype(np.int64),
    })
    for c in ("oferta_compra", "oferta_venda"):
        op.loc[op[c] <= 0, c] = np.nan

    # ativo-objeto pelo ISIN: ticker do lote padrao/ETF com esse ISIN cujo prefixo casa com o codigo da opcao
    isin_tk = {}
    base = spot.groupby(["isin", "ativo"])["volume"].sum().reset_index().sort_values("volume", ascending=False)
    for isin, ativo in zip(base["isin"], base["ativo"]):
        isin_tk.setdefault(isin, []).append(ativo)

    def achar(isin, cod):
        c = isin_tk.get(isin)
        if not c:
            return None
        if len(c) == 1:
            return c[0]
        pref = [a for a in c if a.startswith(cod[:4])]
        return pref[0] if pref else c[0]

    chaves = op[["isin", "codigo"]].copy()
    chaves["pref"] = chaves["codigo"].str[:4]
    mapa = {}
    for isin, pref in chaves[["isin", "pref"]].drop_duplicates().itertuples(index=False):
        mapa[(isin, pref)] = achar(isin, pref)
    op["ativo"] = [mapa.get((i, c[:4])) for i, c in zip(op["isin"], op["codigo"])]
    op = op[op["ativo"].notna()].drop(columns="isin")

    op["semanal"] = op["codigo"].str.contains(r"W\d$", regex=True)
    op["europeia"] = op["codigo"].str.contains(r"E$", regex=True) & ~op["semanal"]
    op["fatcot"] = op["fatcot"].where(op["fatcot"] > 0, 1)

    # vencimento mensal padrao do mes = a data de vencimento com mais volume entre as series sem W
    # (dados.vencimentos_padrao recalcula isso sobre a base inteira; aqui vale o que o proprio arquivo enxerga)
    nao_w = op[~op["semanal"]]
    v = nao_w.groupby("vencimento")["volume"].sum().reset_index()
    v["ym"] = v["vencimento"].dt.to_period("M")
    padrao = v.sort_values("volume", ascending=False).drop_duplicates("ym")
    op["mensal"] = op["vencimento"].isin(set(padrao["vencimento"])) & ~op["semanal"]

    cols = ["dia", "codigo", "ativo", "tipo", "exercicio", "vencimento", "fech", "abre", "max", "min", "medio",
            "oferta_compra", "oferta_venda", "negocios", "quantidade", "volume", "fatcot", "mensal", "semanal", "europeia"]
    op = op[cols].sort_values(["dia", "ativo", "vencimento", "tipo", "exercicio"]).reset_index(drop=True)
    for c in ("exercicio", "fech", "abre", "max", "min", "medio", "oferta_compra", "oferta_venda"):
        op[c] = op[c].astype(np.float32)
    op["negocios"] = op["negocios"].astype(np.int32)
    op["tipo"] = op["tipo"].astype("category")
    op["ativo"] = op["ativo"].astype("category")
    spot = spot.sort_values(["ativo", "dia"]).reset_index(drop=True)
    return op, spot


def extrair_indice(raw):
    """Opcoes sobre o INDICE Ibovespa (CODBDI 74 = call, 75 = put): premio e exercicio em PONTOS, valor de R$ 1 por ponto.
    Entram numa base a parte (indice_AAAA.parquet) porque vencem na quarta-feira mais proxima do dia 15 e, ate 2019, so nos
    meses pares; misturar com as de acao quebraria a deteccao do vencimento mensal."""
    m = _linhas(raw)
    tipo_reg = np.ascontiguousarray(m[:, 0:2]).view("S2").ravel()
    m = m[tipo_reg == b"01"]
    tp = _coluna(m, "tpmerc")
    bdi = _coluna(m, "codbdi")
    sel = ((tp == b"070") | (tp == b"080")) & ((bdi == b"74") | (bdi == b"75"))
    mo = m[sel]
    d = pd.DataFrame({
        "dia": _data(mo, "data"), "codigo": _txt(mo, "codigo"),
        "tipo": np.where(_coluna(mo, "tpmerc") == b"070", "C", "P"),
        "exercicio": _num(mo, "preexe", 100.0), "vencimento": _data(mo, "datven"),
        "fech": _num(mo, "fec", 100.0), "oferta_compra": _num(mo, "bid", 100.0), "oferta_venda": _num(mo, "ask", 100.0),
        "negocios": _num(mo, "negocios").astype(np.int64), "volume": _num(mo, "volume", 100.0),
    })
    for c in ("oferta_compra", "oferta_venda"):
        d.loc[d[c] <= 0, c] = np.nan
    d["ativo"] = "IBOV"
    return d[d["exercicio"] > 0].sort_values(["dia", "vencimento", "tipo", "exercicio"]).reset_index(drop=True)


def extrair_zip_diario(conteudo_zip):
    """Bytes de um COTAHIST_Dddmmaaaa.ZIP -> (opcoes, ativo)."""
    z = zipfile.ZipFile(io.BytesIO(conteudo_zip))
    return extrair(z.read(z.namelist()[0]))


def processar_ano(ano):
    """Le o COTAHIST do ano e grava opcoes_AAAA.parquet e ativo_AAAA.parquet. Devolve (ano, n_opcoes, n_ativo)."""
    raw = _ler_zip(ano)
    op, spot = extrair(raw)
    garantir_dir(DIR_DADOS)
    extrair_indice(raw).to_parquet(os.path.join(DIR_DADOS, f"indice_{ano}.parquet"), index=False)
    op.to_parquet(os.path.join(DIR_DADOS, f"opcoes_{ano}.parquet"), index=False)
    spot.to_parquet(os.path.join(DIR_DADOS, f"ativo_{ano}.parquet"), index=False)
    return ano, len(op), len(spot)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--anos", default="2005-2026")
    ap.add_argument("--trabalhadores", type=int, default=4)
    a = ap.parse_args(argv)
    i, f = (int(x) for x in a.anos.split("-"))
    anos = list(range(i, f + 1))
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=a.trabalhadores) as ex:
        for ano, n_o, n_s in ex.map(processar_ano, anos):
            print(f"{ano}: {n_o:>9,} linhas de opcoes, {n_s:>7,} de ativo  ({time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    sys.exit(main())
