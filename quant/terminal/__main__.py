"""CLI do leitor do terminal:  python -m quant.terminal <comando>

    ficha TICKER [--json]            o que o terminal sabe do papel (texto resumido, ou o JSON inteiro)
    tabela [TICKER ...] [--colunas a,b] [--cobertura] [--csv]
                                     uma linha por ticker (padrao: todas as acoes do terminal); --cobertura mostra quantos tem cada coluna
    eventos [--dias 10] [--tipos resultado,macro] [--pais BR] [--tickers PETR4,VALE3]
    historico TABELA [--ticker X] [--desde AAAA-MM-DD] [--linhas 20]
    status                           onde esta o terminal, que arquivos existem e a idade deles
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import pandas as pd

from . import COLUNAS_TABELA, LIMITES_DIAS, cobertura, estado, eventos, ficha, historico, tabela

COLUNAS_RESUMO = ["nome", "tir_prudente_pct", "tir_premio_pp", "ciclo_lucro", "consenso_upside_pct", "consenso_lpa_rev_30d_pct",
                  "insiders_saldo_90d_rs", "aluguel_taxa_aa", "noticia_score_7d", "dias_ate_resultado", "pl", "ev_ebitda", "div_liq_ebitda",
                  "iv_atm_pct"]


def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if abs(v) < 1e6 else f"{v:,.0f}".replace(",", ".")
    return str(v)


def _plano(d: Any, prefixo: str = "", fundo: int = 0) -> list[str]:
    """Achata um pedaco da ficha em linhas 'chave: valor' (listas viram resumo; sem despejar manchete por manchete)."""
    linhas = []
    if isinstance(d, dict):
        for k, v in d.items():
            if k in ("fonte", "data", "idade_dias", "avisos", "como_ler"):
                continue
            if isinstance(v, dict) and fundo < 2:
                sub = _plano(v, f"{prefixo}{k}.", fundo + 1)
                if sub:
                    linhas += sub
            elif isinstance(v, list):
                if v and isinstance(v[0], dict):
                    linhas.append(f"{prefixo}{k}: {len(v)} item(ns)")
                elif v:
                    linhas.append(f"{prefixo}{k}: {', '.join(map(str, v[:6]))}")
            elif v is not None:
                linhas.append(f"{prefixo}{k}: {_fmt(v)}")
    return linhas


def cmd_ficha(a: argparse.Namespace) -> int:
    f = ficha(a.ticker)
    if a.json:
        print(json.dumps(f, ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"FICHA {f['ticker']} | {f['nome'] or 'fora do universo do terminal'} | {f['classe'] or '-'} | {f['setor'] or '-'}")
    print(f"terminal: {f['terminal']} | hoje {f['hoje']} | {f['cobertura']['com_dado']} de {f['cobertura']['total']} pedacos com dado")
    for k in ("tir", "consenso", "insiders", "aluguel", "noticias", "proximo_resultado", "multiplos", "valuation", "divida", "opcoes", "fundos", "pares"):
        v = f.get(k)
        if v is None:
            print(f"\n[{k}] SEM DADO: {f['motivos'].get(k)}")
            continue
        print(f"\n[{k}] {v['fonte']} | dado de {v['data']} ({v['idade_dias']} dia(s))")
        for ln in _plano(v):
            print("   " + ln)
        for av in v.get("avisos") or []:
            print("   ! " + av)
    return 0


def cmd_tabela(a: argparse.Namespace) -> int:
    df = tabela(a.tickers or None)
    if a.cobertura:
        c = cobertura(df)
        print(f"{len(df)} tickers; coluna: com dado")
        for n, v in c.items():
            print(f"  {n:<32}{v:>5}")
        return 0
    cols = [c.strip() for c in a.colunas.split(",")] if a.colunas else COLUNAS_RESUMO
    ruins = [c for c in cols if c not in COLUNAS_TABELA]
    if ruins:
        print(f"colunas inexistentes: {', '.join(ruins)}. As validas: {', '.join(COLUNAS_TABELA)}", file=sys.stderr)
        return 2
    sub = df[cols]
    if a.csv:
        print(sub.to_csv())
    else:
        with pd.option_context("display.width", 250, "display.max_columns", 40, "display.max_rows", 400, "display.float_format", "{:,.2f}".format):
            print(sub if a.tickers else sub.head(a.linhas))
            if not a.tickers and len(sub) > a.linhas:
                print(f"... {len(sub) - a.linhas} linhas a mais (use --linhas N, --csv ou passe tickers)")
    return 0


def cmd_eventos(a: argparse.Namespace) -> int:
    ev = eventos(a.dias, tipos=a.tipos.split(",") if a.tipos else None, pais=a.pais, tickers=a.tickers.split(",") if a.tickers else None)
    for av in ev.avisos:
        print(f"! {av}", file=sys.stderr)
    print(f"{len(ev)} evento(s) nos proximos {a.dias} dias")
    for e in ev:
        extra = ""
        if e["tipo"] == "macro":
            extra = f"  [rel {e['relevancia']}] anterior {_fmt(e['anterior'])} esperado {_fmt(e['expectativa'])}"
        print(f"  {e['data']} {e['hora'] or '     '}  {e['tipo']:<18} {e['titulo']}{extra}")
    return 0


def cmd_historico(a: argparse.Namespace) -> int:
    try:
        df = historico(a.tabela, a.ticker, a.desde)
    except ValueError as ex:
        print(str(ex), file=sys.stderr)
        return 2
    if df.empty:
        print(df.attrs.get("motivo") or "nenhuma linha")
        return 0
    with pd.option_context("display.width", 250, "display.max_columns", 40):
        print(df.tail(a.linhas).to_string(index=False))
    print(f"\n{len(df)} linha(s) no total; {df['data'].min() if 'data' in df else '-'} a {df['data'].max() if 'data' in df else '-'}")
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    e = estado()
    print(f"terminal: {e['terminal']} | disponivel: {'sim' if e['disponivel'] else 'NAO'} | hoje {e['hoje']}")
    for k, v in e["arquivos"].items():
        print(f"  {k:<40}{v or 'AUSENTE'}")
    b = e["banco"]
    print(f"banco historico: {b['caminho']} | {'existe' if b['existe'] else 'NAO existe (rode python -m coletor.banco --gravar no terminal)'}")
    if b["tabelas"]:
        print("  tabelas: " + ", ".join(b["tabelas"]))
    print("limites de idade (dias): " + ", ".join(f"{k} {v}" for k, v in LIMITES_DIAS.items()))
    return 0 if e["disponivel"] else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m quant.terminal", description="Leitor do Autopilot Terminal para o robo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ficha"); p.add_argument("ticker"); p.add_argument("--json", action="store_true"); p.set_defaults(f=cmd_ficha)
    p = sub.add_parser("tabela"); p.add_argument("tickers", nargs="*"); p.add_argument("--colunas"); p.add_argument("--cobertura", action="store_true")
    p.add_argument("--csv", action="store_true"); p.add_argument("--linhas", type=int, default=25); p.set_defaults(f=cmd_tabela)
    p = sub.add_parser("eventos"); p.add_argument("--dias", type=int, default=10); p.add_argument("--tipos"); p.add_argument("--pais")
    p.add_argument("--tickers"); p.set_defaults(f=cmd_eventos)
    p = sub.add_parser("historico"); p.add_argument("tabela"); p.add_argument("--ticker"); p.add_argument("--desde")
    p.add_argument("--linhas", type=int, default=20); p.set_defaults(f=cmd_historico)
    p = sub.add_parser("status"); p.set_defaults(f=cmd_status)
    a = ap.parse_args(argv)
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())
