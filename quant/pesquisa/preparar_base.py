"""Monta a base do laboratorio: le as series longas de 1 minuto que o MetaTrader exportou (arquivos
autopilot_historia_<SIMBOLO>_M2.csv; o "M2" e so o nome, as barras sao de 1 minuto) e grava um arquivo por ativo e por
parte (descoberta, validacao, prova) em quant/saida/pesquisa5/. Uso: python -m quant.pesquisa.preparar_base"""
import os

import pandas as pd

from quant.daytrade import fluxo as fx
from quant.daytrade import historico as h
from quant.pesquisa import lab

ARQUIVOS = {"WDO": "WDOSD", "WDO_SEM_AJUSTE": "WDOSN", "DOL": "DOLSN", "WIN": "WINSN", "DI27": "DI1F27", "DI29": "DI1F29", "DI1": "DI1SN",
            "WSP": "WSPSN", "PETR4": "PETR4", "VALE3": "VALE3",
            # 09/10/2026: o Douglas liberou mini-indice e acoes; as mais liquidas e o ETF do Ibovespa
            "ITUB4": "ITUB4", "BBDC4": "BBDC4", "BBAS3": "BBAS3", "B3SA3": "B3SA3", "ABEV3": "ABEV3", "WEGE3": "WEGE3", "PRIO3": "PRIO3",
            "PETR3": "PETR3", "SUZB3": "SUZB3", "RENT3": "RENT3", "BOVA11": "BOVA11", "ITSA4": "ITSA4"}


def ler(simbolo, pasta=fx.PASTA_MT5):
    arq = os.path.join(pasta, f"autopilot_historia_{simbolo}_M2.csv")
    return h.carregar(arq) if os.path.exists(arq) else None


def main():
    bases = {nome: ler(s) for nome, s in ARQUIVOS.items()}
    wdo, cru = bases.get("WDO"), bases.pop("WDO_SEM_AJUSTE", None)
    if wdo is not None and cru is not None:
        wdo["nivel"] = cru["c"].reindex(wdo.index)                 # o preco de tela do dia (serie sem ajuste)
    for nome, m in bases.items():
        if m is None:
            print(f"{nome:<6} sem arquivo")
            continue
        m = m[~m.index.duplicated(keep="last")].sort_index()
        linha = f"{nome:<6} {len(m):>7} barras, {m.index[0]} a {m.index[-1]}"
        for parte, (de, ate) in lab.PARTES.items():
            p = m[(m.index >= de) & (m.index < pd.Timestamp(ate) + pd.Timedelta(days=1))]
            os.makedirs(os.path.join(lab.PASTA, parte), exist_ok=True)
            p.to_pickle(os.path.join(lab.PASTA, parte, f"{nome}.pkl"))
            linha += f" | {parte} {len(set(p.index.date))} pregoes"
        print(linha)


if __name__ == "__main__":
    main()
