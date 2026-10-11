"""Leitura do banco historico do terminal (cache/banco/terminal.sqlite, criado por `python -m coletor.banco`)."""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

import pandas as pd

from . import _leitor as L


def _abrir() -> sqlite3.Connection | None:
    p = L.caminho_banco()
    if not p.is_file():
        return None
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=30)
    except sqlite3.Error:
        con = sqlite3.connect(str(p), timeout=30)
    return con


def tabelas_do_banco() -> list[str]:
    con = _abrir()
    if con is None:
        return []
    try:
        return sorted(r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"))
    finally:
        con.close()


def ler(tabela: str, ticker: str | None = None, desde: Any = None) -> pd.DataFrame:
    """DataFrame com as linhas de `tabela`, da mais antiga para a mais nova. Banco ausente -> DataFrame vazio com `.attrs['motivo']`."""
    con = _abrir()
    if con is None:
        df = pd.DataFrame()
        df.attrs["motivo"] = f"banco historico ainda nao existe em {L.caminho_banco()}: rode `python -m coletor.banco --gravar` no terminal"
        return df
    try:
        existentes = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        if tabela not in existentes or tabela in ("meta",):
            raise ValueError(f"tabela '{tabela}' nao existe no banco; as tabelas sao: {', '.join(sorted(x for x in existentes if x != 'meta'))}")
        colunas = [r[1] for r in con.execute(f"PRAGMA table_info({tabela})")]
        onde, args = [], []
        if ticker is not None:
            chave = "ticker" if "ticker" in colunas else "ativo" if "ativo" in colunas else None
            if chave is None:
                raise ValueError(f"a tabela '{tabela}' nao tem coluna de ticker; colunas: {', '.join(colunas)}")
            onde.append(f"{chave} = ?")
            args.append(ticker.strip().upper())
        if desde is not None:
            d = desde.isoformat() if isinstance(desde, date) else str(desde)[:10]
            col_data = "data" if "data" in colunas else None
            if col_data is None:
                raise ValueError(f"a tabela '{tabela}' nao tem coluna 'data'")
            onde.append("data >= ?")
            args.append(d)
        sql = f"SELECT * FROM {tabela}" + (" WHERE " + " AND ".join(onde) if onde else "")
        if "data" in colunas:
            sql += " ORDER BY data"
        df = pd.read_sql_query(sql, con, params=args)
    finally:
        con.close()
    df.attrs["fonte"] = f"{L.caminho_banco()} :: {tabela}"
    return df
