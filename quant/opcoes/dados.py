"""
Leitores da base de opcoes (parquet gerado por base.py), do CDI (SGS 12), do Ibovespa e do retorno total das acoes.

Tudo em memoria, sem rede (o CDI vem do cache de quant/dados_brutos/bcb; o Ibovespa, de ibov_diario.parquet, baixado
uma vez do Yahoo ^BVSP). Armadilhas tratadas aqui:

  - VENCIMENTO MENSAL. Ate abril/2021 vencia na TERCEIRA SEGUNDA-FEIRA; desde maio/2021, na terceira sexta-feira (conferido
    nos dados: 2012-2020 todo vencimento padrao cai na segunda, 2022-2026 na sexta). Em vez de calcular pela regra, o
    vencimento mensal padrao de cada mes e a data de maior volume entre as series sem sufixo W. Semanais (codigo termina
    em W1..W5) ficam na base marcadas e fora das estrategias mensais.
  - VALE5 virou VALE3. Ate 2017 as opcoes mais liquidas eram as de VALE5; o grupo "VALE" escolhe, em cada ciclo, o ativo com
    mais volume de opcoes no dia de entrada.
  - SERIE SEM NEGOCIO. O COTAHIST so tem linha de serie negociada no dia; nao ha preco velho na entrada. No vencimento a
    serie que nao negociou vale o valor intrinseco.
  - EXERCICIO AJUSTADO. O strike da B3 e protegido (ajustado por provento): vale o strike da ULTIMA linha da serie antes do
    vencimento, comparado ao preco SEM ajuste da acao (o que a B3 liquida).
"""
import glob
import os
from functools import lru_cache

import numpy as np
import pandas as pd

from quant.comum import DIR_BANCO
from quant.opcoes.base import DIR_DADOS, DIR_OPC

GRUPOS = {"VALE3": "VALE", "VALE5": "VALE"}
ARQ_EVENTOS = os.path.join(DIR_BANCO, "eventos.parquet")


def grupo_de(ativo):
    return GRUPOS.get(ativo, ativo)


@lru_cache(maxsize=1)
def cdi_diario():
    """Serie diaria do CDI em decimal (0,0005 = 0,05% ao dia), indexada por data. SGS 12 do Banco Central."""
    from quant.dados import cdi
    s = cdi.carregar(permitir_rede=False)
    s = pd.Series(s).sort_index()
    s.index = pd.to_datetime(s.index)
    return s.astype(float)


@lru_cache(maxsize=1)
def ibov():
    d = pd.read_parquet(os.path.join(DIR_DADOS, "ibov_diario.parquet"))
    return d.set_index("dia")["fech"].astype(float)


@lru_cache(maxsize=1)
def dias_de_pregao():
    """Pregoes da B3 (datas em que o Ibovespa fechou), ordenados."""
    return pd.DatetimeIndex(ibov().index)


def carregar_opcoes(ano_ini=2012, ano_fim=2026, ativos=None, colunas=None):
    partes = []
    for ano in range(ano_ini, ano_fim + 1):
        f = os.path.join(DIR_DADOS, f"opcoes_{ano}.parquet")
        if not os.path.exists(f):
            continue
        d = pd.read_parquet(f, columns=colunas)
        if ativos is not None:
            d = d[d["ativo"].isin(ativos)]
        partes.append(d)
    d = pd.concat(partes, ignore_index=True)
    for c in ("ativo", "tipo"):
        if c in d.columns:
            d[c] = d[c].astype(str)
    return d


def carregar_ativos(ano_ini=2005, ano_fim=2026, ativos=None):
    partes = []
    for ano in range(ano_ini, ano_fim + 1):
        f = os.path.join(DIR_DADOS, f"ativo_{ano}.parquet")
        if os.path.exists(f):
            d = pd.read_parquet(f)
            if ativos is not None:
                d = d[d["ativo"].isin(ativos)]
            partes.append(d)
    return pd.concat(partes, ignore_index=True)


def vencimentos_mensais(op):
    """Vencimento padrao de cada mes = data de maior volume entre as series sem W. `op` precisa de 'vencimento', 'volume',
    'semanal'. Devolve lista ordenada de Timestamps."""
    m = op[~op["semanal"]].groupby("vencimento")["volume"].sum().reset_index()
    m["ym"] = m["vencimento"].dt.to_period("M")
    pad = m.sort_values("volume", ascending=False).drop_duplicates("ym").sort_values("vencimento")
    return list(pad["vencimento"])


@lru_cache(maxsize=1)
def vencimentos_padrao():
    """Mensais 2005-2026 calculados sobre a base INTEIRA (a base por ano enxerga so os vencimentos que negociaram nele)."""
    op = carregar_opcoes(2005, 2026, colunas=["vencimento", "volume", "semanal"])
    return vencimentos_mensais(op)


def acumular_cdi(d0, d1):
    """Fator de CDI acumulado nos pregoes (d0, d1]."""
    c = cdi_diario()
    return float((1.0 + c[(c.index > d0) & (c.index <= d1)]).prod())


def indice_de_dia(dias, d):
    return int(np.searchsorted(dias.values, np.datetime64(d)))


@lru_cache(maxsize=1)
def fator_retorno_total():
    """Indice de retorno total por (ativo, dia) de todas as acoes e ETFs da base, em DataFrame largo (colunas = ativo).
    Acoes: precos do COTAHIST + eventos (dividendo, JCP, desdobramento...) da quant/banco/eventos.parquet.
    BOVA11 e ETFs sem evento na tabela: ficam so com o preco (use o Ibovespa, que e de retorno total, para o BOVA11)."""
    from quant.dados import eventos as ev
    sp = carregar_ativos(2005, 2026)
    sp = sp[sp["fech"] > 0]
    e = pd.read_parquet(ARQ_EVENTOS)
    precos = sp.rename(columns={"ativo": "ticker", "dia": "data"})[["ticker", "data", "fech", "fatcot"]].rename(columns={"fech": "fec"})
    rt = ev.retorno_total_limpo(precos, e)
    f = rt.pivot_table(index="data", columns="ticker", values="fator_acum", aggfunc="last")
    f.index = pd.to_datetime(f.index)
    return f.sort_index()


@lru_cache(maxsize=1)
def fechamentos():
    """Fechamento SEM ajuste (o que a B3 liquida) por dia x ativo, em DataFrame largo."""
    sp = carregar_ativos(2005, 2026)
    sp = sp[(sp["fech"] > 0) & (sp["fatcot"] == 1)]
    f = sp.pivot_table(index="dia", columns="ativo", values="fech", aggfunc="last")
    return f.sort_index()


def dias_estendidos(ate="2028-12-31"):
    """Pregoes conhecidos (Ibovespa) mais os dias uteis futuros pelo calendario de feriados da B3. Serve para contar pregoes
    ate vencimentos que ainda nao aconteceram (sem isso, vencimento alem do ultimo pregao conhecido vira 'ultimo indice')."""
    from quant.dados import calendario
    base = dias_de_pregao()
    fut = calendario.pregoes((base[-1] + pd.Timedelta(days=1)).date(), pd.Timestamp(ate).date())
    return base.append(pd.DatetimeIndex(pd.to_datetime(fut)))
