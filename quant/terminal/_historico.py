"""Leitura do banco historico do terminal (cache/banco/terminal.sqlite, criado por `python -m coletor.banco`)."""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

import pandas as pd

from . import _leitor as L


# Tabela `tir` (esquema v3 do banco, 12/10/2026): o numero principal da TIR e o terminal endogeno (V5a). As colunas canonicas vem primeiro; as antigas
# (a "menor entre P/L e perpetuidade") seguem na tabela como LEGADO, e `conta` diz com qual definicao o `tir_prudente_pct` de cada linha saiu.
CANONICAS_TIR = ("tir_principal_pct", "tir_principal_norm_pct", "tir_principal_prudente_pct", "tir_principal_base", "premio_principal_pp", "conta")
LEGADO_TIR = ("tir_hoje_pct", "tir_pl_pct", "tir_perp_pct", "tir_normalizada_pct", "tir_prudente_pct", "tir_prudente_base", "premio_pp", "premio_hoje_pp")
NOTA_TIR = ("TIR: use as colunas tir_principal_* e premio_principal_pp (terminal endogeno, a conta da tela). tir_hoje_pct, tir_normalizada_pct, tir_pl_pct, "
            "tir_perp_pct, tir_prudente_pct, tir_prudente_base, premio_pp e premio_hoje_pp sao LEGADO (a menor entre P/L e perpetuidade, que subestimava); "
            "`conta` diz so com qual definicao o tir_prudente_pct (legado) de cada linha foi calculado ('endogena' ou 'menor_das_duas'); as colunas tir_principal_* "
            "sao SEMPRE a conta endogena, em qualquer linha, e e nelas que a serie nao mistura definicoes.")


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
    if tabela == "tir":
        df = _organizar_tir(df)
    df.attrs["fonte"] = f"{L.caminho_banco()} :: {tabela}"
    return df


def _organizar_tir(df: pd.DataFrame) -> pd.DataFrame:
    """`tir`: as colunas canonicas (conta do terminal endogeno) logo depois de data e ticker; o legado fica onde estava e e documentado em `.attrs`."""
    cols = list(df.columns)
    can = [c for c in CANONICAS_TIR if c in cols]
    frente = [c for c in ("data", "ticker") if c in cols]
    novo = df[frente + can + [c for c in cols if c not in frente and c not in can]]
    novo.attrs["canonicas"] = can
    novo.attrs["legado"] = [c for c in LEGADO_TIR if c in cols]
    novo.attrs["nota"] = NOTA_TIR
    if len(can) < len(CANONICAS_TIR):
        novo.attrs["motivo"] = ("o banco ainda esta no esquema anterior (sem as colunas canonicas da TIR): rode no terminal "
                                "`python -m coletor.banco --preencher --so tir`; ate la, tir_prudente_pct e a conta antiga")
    return novo
