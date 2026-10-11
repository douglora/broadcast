"""
Tabela DIARIA de opcoes liquidas (base dos itens 2, 3 e 5 da terceira etapa) e liquidacao no vencimento para entradas em qualquer dia.

  opcoes_diarias.parquet   uma linha por serie com 10+ negocios no dia, ofertas validas ou nao (flag `boa`), 10 a 45 pregoes ate o vencimento,
                           nos ativos do universo (25 de maior volume do ano anterior + BOVA11): ativo, dia, codigo, tipo, vencimento, exercicio,
                           bid, ask, fech, mid, delta, iv, negocios, spread, boa, du, S, r

LIQUIDACAO para entrada em qualquer dia D (nao so a do primeiro pregao do ciclo): o exercicio protegido da B3 cai no valor do provento entre D e o
vencimento T. Aqui K_T = K_D - proventos com data-ex em (D, T] (dividendo + JCP liquido de 15% + rendimento, tabela quant/banco/eventos.parquet),
e a operacao e DESCARTADA se houver desdobramento, grupamento, bonificacao ou subscricao na janela (o ajuste e multiplicativo e nao e estimado).
Conferido contra o exercicio de liquidacao corrigido do ciclo mensal (ciclos.py): ver `conferir_ajuste`.
"""
import os

import numpy as np
import pandas as pd

from quant.comum import DIR_BANCO
from quant.opcoes import dados
from quant.opcoes import painel_vol as pv
from quant.opcoes.base import DIR_DADOS

ARQ = os.path.join(DIR_DADOS, "opcoes_diarias.parquet")
TIPOS_DINHEIRO = ("DIVIDENDO", "JCP", "RENDIMENTO")
TIPOS_QTD = ("DESDOBRAMENTO", "GRUPAMENTO", "BONIFICACAO", "SUBSCRICAO")
IR_JCP = 0.15


def construir(ano_ini=2012, ano_fim=2026):
    import os as _os
    uni = pv.universo()
    dias = dados.dias_estendidos()
    cdi = dados.cdi_diario()
    cdi_aa = ((1.0 + cdi.reindex(dias).ffill()) ** 252 - 1.0)
    partes = []
    for ano in range(ano_ini, ano_fim + 1):
        op = dados.carregar_opcoes(ano, ano)
        op = op[op["ativo"].isin(uni)]
        sp = pd.read_parquet(_os.path.join(DIR_DADOS, f"ativo_{ano}.parquet"))
        sp = sp[(sp["fatcot"] == 1) & (sp["fech"] > 0) & sp["ativo"].isin(uni)]
        spot = sp.set_index(["ativo", "dia"])["fech"]
        spot = spot[~spot.index.duplicated(keep="last")]
        o = pv.preparar_opcoes(op, spot, cdi_aa, dias)
        o = o[(o["negocios"] >= 10) & (o["du"] >= 10) & (o["du"] <= 45)]
        o["bid"] = o["oferta_compra"]
        o["ask"] = o["oferta_venda"]
        o["mid"] = (o["bid"] + o["ask"]) / 2.0
        cols = ["ativo", "dia", "codigo", "tipo", "vencimento", "exercicio", "bid", "ask", "fech", "mid", "delta", "iv", "negocios", "spread", "boa", "du", "S", "r"]
        partes.append(o[cols])
        print(ano, len(partes[-1]), flush=True)
    t = pd.concat(partes, ignore_index=True)
    for c in ("exercicio", "bid", "ask", "fech", "mid", "delta", "iv", "spread", "S", "r"):
        t[c] = t[c].astype("float32")
    t["ativo"] = t["ativo"].astype("category")
    t.to_parquet(ARQ, index=False)
    return t


def carregar():
    t = pd.read_parquet(ARQ)
    t["ativo"] = t["ativo"].astype(str)
    return t


# --------------------------------------------------------------------------------------------------- ajuste de proventos
class Ajuste:
    """Soma de proventos (ex-data em (d0, d1]) por ativo e deteccao de evento de quantidade."""

    def __init__(self):
        e = pd.read_parquet(os.path.join(DIR_BANCO, "eventos.parquet"))
        e = e[e["data_ex"].notna()].copy()
        e["v"] = np.where(e["tipo"] == "JCP", e["valor"].fillna(0) * (1 - IR_JCP), np.where(e["tipo"].isin(("DIVIDENDO", "RENDIMENTO")), e["valor"].fillna(0), 0.0))
        e["qtd"] = e["tipo"].isin(TIPOS_QTD)
        self.por = {}
        for t, g in e.sort_values("data_ex").groupby("ticker"):
            self.por[t] = (g["data_ex"].values.astype("datetime64[ns]"), np.cumsum(g["v"].values), np.cumsum(g["qtd"].values.astype(int)))

    def entre(self, ticker, d0, d1):
        """(soma de proventos em (d0, d1], houve evento de quantidade?)"""
        if ticker not in self.por:
            return 0.0, False
        datas, cv, cq = self.por[ticker]
        i0 = np.searchsorted(datas, np.datetime64(d0), side="right")
        i1 = np.searchsorted(datas, np.datetime64(d1), side="right")
        v0 = cv[i0 - 1] if i0 > 0 else 0.0
        v1 = cv[i1 - 1] if i1 > 0 else 0.0
        q0 = cq[i0 - 1] if i0 > 0 else 0
        q1 = cq[i1 - 1] if i1 > 0 else 0
        return float(v1 - v0), bool(q1 - q0 > 0)

    def vetor(self, ativos, d0, d1):
        v, q = [], []
        for a, x, y in zip(ativos, d0, d1):
            vv, qq = self.entre(a, x, y)
            v.append(vv)
            q.append(qq)
        return np.array(v), np.array(q)


def conferir_ajuste(n=3000, seed=1):
    """Compara K_T estimado pelos proventos com o exercicio de liquidacao corrigido do ciclo mensal (cadeia_preparada). Devolve estatisticas."""
    cad = pd.read_parquet(os.path.join(DIR_DADOS, "cadeia_preparada.parquet"))
    cad = cad[(cad["negocios"] >= 30) & cad["K_T_corrigido"].notna() & (cad["delta"].abs().between(0.15, 0.35))]
    cad = cad.sample(min(n, len(cad)), random_state=seed)
    aj = Ajuste()
    v, q = aj.vetor(cad["ativo"], cad["E"], cad["T"])
    kt_est = cad["exercicio"].values - v
    ok = ~q
    dif = (kt_est - cad["K_T"].values)[ok]
    rel = np.abs(dif) / cad["exercicio"].values[ok]
    return {"n": int(ok.sum()), "descartadas_por_evento_de_quantidade": int(q.sum()), "dif_media_rs": float(dif.mean()), "dif_abs_mediana_rs": float(np.median(np.abs(dif))),
            "dif_abs_p95_rs": float(np.quantile(np.abs(dif), 0.95)), "dif_rel_mediana_pct": float(np.median(rel) * 100), "dif_rel_p95_pct": float(np.quantile(rel, 0.95) * 100)}


if __name__ == "__main__":
    construir()
