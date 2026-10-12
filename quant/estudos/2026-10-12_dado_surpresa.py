"""
Estudo 12/10/2026 (rodada 2): a reversao do dado contra a surpresa REAL (consenso e efetivo do calendario do MetaTrader,
exportado com o "pode" do Douglas). S = soma dos z das surpresas do marco das 8h30 de NY, com o sinal do dolar (S > 0 =
surpresa que fortalece o dolar). "Concorda" = a reacao dos 2 primeiros minutos foi no sentido da surpresa.

Cada condicao e UMA tentativa (familia dado_surpresa); roda na descoberta; so candidata abre 2025; a prova nao se abre.
Saida: quant/saida/pesquisa5/montecarlo/dado_surpresa.json
"""
import importlib.util
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from quant.dados import calendario_eua as ce  # noqa: E402
from quant.pesquisa import lab  # noqa: E402

_spec = importlib.util.spec_from_file_location("dado_cond", os.path.join(os.path.dirname(os.path.abspath(__file__)), "2026-10-12_dado_condicionado.py"))
dc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dc)
dc.FAMILIA = "dado_surpresa"
PASTA = dc.PASTA


def condicoes(f):
    S = ce.tabela_surpresa_dia().reindex(f.index)
    parte = "descoberta" if f.index.max().year <= 2024 else "validacao"
    reac = pd.read_csv(os.path.join(PASTA, f"reacao_dado_{parte}.csv"))
    mv = reac.set_index(pd.to_datetime(reac.dia)).mv.reindex(f.index)
    s, z = S.S, S.z_maior
    concorda = (np.sign(mv) == np.sign(s)) & s.notna()
    contraria = (np.sign(mv) == -np.sign(s)) & s.notna()
    c = {}
    c["concorda(|S|>=0,5)"] = (concorda & (s.abs() >= 0.5), 1)
    c["contraria(|S|>=0,5)"] = (contraria & (s.abs() >= 0.5), 1)
    c["surpresa_grande(|S|>=1)"] = (s.abs() >= 1, 1)
    c["surpresa_pequena(|S|<0,5)"] = (s.abs() < 0.5, 1)
    c["sem_consenso_no_marco"] = (s.isna(), 1)
    c["contraria_grande(|S|>=1)"] = (contraria & (s.abs() >= 1), 1)
    c["concorda_grande(|S|>=1)"] = (concorda & (s.abs() >= 1), 1)
    c["continuacao_concorda_grande"] = (concorda & (s.abs() >= 1), -1)
    c["z_principal_grande(|z|>=1,5)"] = (z.abs() >= 1.5, 1)
    for tp in ("payroll", "cpi", "ppi", "claims"):
        c[f"tipo_mt5={tp}"] = (S.tipo_principal == tp, 1)
    c["tipo_mt5=pce|varejo|pib"] = (S.tipo_principal.isin(["pce", "varejo", "pib"]), 1)
    c["tipo_mt5=outro|nenhum"] = (S.tipo_principal.isin(["outro", "nenhum"]) | S.tipo_principal.isna(), 1)
    return c


def main():
    desc, f = dc.rodar("descoberta", condicoes)
    cands = [k for k, v in desc["variantes"].items() if v["candidata"]]
    print("candidatas na descoberta:", cands or "nenhuma")
    val = dc.rodar("validacao", condicoes, so=set(cands))[0] if cands else None
    json.dump({"descoberta": desc, "validacao": val, "candidatas": cands}, open(os.path.join(PASTA, "dado_surpresa.json"), "w"), indent=1, default=str)
    print("gravado", os.path.join(PASTA, "dado_surpresa.json"))


if __name__ == "__main__":
    main()
