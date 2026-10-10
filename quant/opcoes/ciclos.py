"""
Ciclos mensais: para cada vencimento mensal padrao T e cada ativo, a cadeia de opcoes vista no fechamento do
primeiro pregao depois do vencimento anterior (a entrada E), com tudo que as estrategias precisam:

  - preco do ativo na entrada (S_E) e na liquidacao (S_T, fechamento SEM ajuste da data de vencimento);
  - para cada serie: premio, ofertas de compra e de venda, negocios, volume, volatilidade implicita e delta
    (Black-Scholes proprio, bs.py, com o ponto medio das ofertas) e o strike de liquidacao K_T (ultima linha da serie);
  - o CDI acumulado e o retorno total do ativo no ciclo.

Entrada no fechamento de E com os precos de fechamento de E: as ofertas de compra e de venda sao as que ficaram no livro
no fechamento (COTAHIST). Premissa: a ordem sai nos minutos finais do pregao.
"""
import numpy as np
import pandas as pd

from quant.opcoes import bs, dados


def montar(ini="2012-01-01", fim="2026-12-31", ativos=None, du_entrada=None):
    """Tabela de cadeias de entrada (uma linha por serie mensal no dia de entrada) + tabela de ciclos.
    Devolve (cadeia, ciclos). `du_entrada`: se informado, a entrada e `du_entrada` pregoes ANTES do vencimento (vencimento
    curto) em vez do primeiro pregao depois do vencimento anterior."""
    ini, fim = pd.Timestamp(ini), pd.Timestamp(fim)
    dias = dados.dias_de_pregao()
    venc = [v for v in dados.vencimentos_padrao()]
    # ciclos: T com vencimento anterior P; entrada E = primeiro pregao depois de P
    linhas = []
    for p, t in zip(venc[:-1], venc[1:]):
        if t < ini or t > fim or t > dias[-1]:
            continue
        t_idx = dados.indice_de_dia(dias, t)
        e_idx = (t_idx - du_entrada) if du_entrada else dados.indice_de_dia(dias, p) + 1
        if e_idx >= len(dias) or t_idx >= len(dias) or dias[t_idx] != t:
            continue
        linhas.append({"P": p, "E": dias[e_idx], "T": t, "du": t_idx - e_idx, "dc": (t - dias[e_idx]).days})
    ciclos = pd.DataFrame(linhas)
    ciclos = ciclos[(ciclos["E"] >= ini)].reset_index(drop=True)

    op = dados.carregar_opcoes(max(2005, ini.year), min(2026, fim.year + 1), ativos=ativos)
    op = op[~op["semanal"]]
    cad = op.merge(ciclos[["E", "T", "du", "dc"]], left_on=["dia", "vencimento"], right_on=["E", "T"], how="inner")
    cad["mid"] = np.where(cad["oferta_compra"].notna() & cad["oferta_venda"].notna(),
                          (cad["oferta_compra"] + cad["oferta_venda"]) / 2.0, np.nan)
    cad["spread"] = (cad["oferta_venda"] - cad["oferta_compra"]) / cad["mid"]
    cad["grupo"] = cad["ativo"].map(dados.grupo_de)

    # strike de liquidacao: ultima linha da serie (codigo, vencimento) ate o vencimento
    ult = (op.sort_values("dia").groupby(["codigo", "vencimento"], sort=False)
           .agg(K_T=("exercicio", "last"), ult_dia=("dia", "last")).reset_index())
    cad = cad.merge(ult, on=["codigo", "vencimento"], how="left")
    cad["K_T_obs"] = cad["K_T"]
    cad = _ajustar_strike_final(cad)

    # precos do ativo
    fech = dados.fechamentos()
    cad["S_E"] = [fech.at[e, a] if (a in fech.columns and e in fech.index) else np.nan for e, a in zip(cad["E"], cad["ativo"])]
    cad["S_T"] = [fech.at[t, a] if (a in fech.columns and t in fech.index) else np.nan for t, a in zip(cad["T"], cad["ativo"])]

    # CDI do ciclo e juro continuo na entrada
    cdi = dados.cdi_diario()
    cdi_ciclo = {}
    for e, t in zip(ciclos["E"], ciclos["T"]):
        cdi_ciclo[(e, t)] = dados.acumular_cdi(e, t) - 1.0
    cad["cdi_ciclo"] = [cdi_ciclo[(e, t)] for e, t in zip(cad["E"], cad["T"])]
    cdi_e = np.array([cdi.get(e, np.nan) for e in cad["E"]])
    cad["r_aa"] = (1.0 + cdi_e) ** 252 - 1.0
    cad["r"] = np.log1p(cad["r_aa"])
    cad["t"] = cad["du"] / 252.0

    # volatilidade implicita e delta pelo ponto medio (se houver as duas ofertas) ou pelo ultimo negocio
    put = (cad["tipo"] == "P").values
    cad["premio_ref"] = cad["mid"].fillna(cad["fech"])
    iv = bs.vol_implicita_vet(cad["premio_ref"].values, cad["S_E"].values, cad["exercicio"].values, cad["t"].values,
                              cad["r"].values, put)
    cad["iv"] = iv
    cad["delta"] = bs.delta_vet(cad["S_E"].values, cad["exercicio"].values, cad["t"].values, cad["r"].values, iv, put)
    cad["moneyness"] = cad["exercicio"] / cad["S_E"]
    # pagamento no vencimento por acao (valor intrinseco com o preco sem ajuste da data)
    cad["payoff_T"] = np.where(put, np.maximum(cad["K_T"] - cad["S_T"], 0.0), np.maximum(cad["S_T"] - cad["K_T"], 0.0))
    cad["dias_sem_linha"] = (cad["T"] - cad["ult_dia"]).dt.days
    return cad.reset_index(drop=True), ciclos


def retorno_total_ciclo(cad):
    """Retorno total do ativo no ciclo (E -> T): fator de retorno total das acoes; BOVA11 pelo Ibovespa (indice de retorno
    total) menos 0,10% ao ano de taxa. Devolve Series indexada como `cad` (uma linha por serie) -- use drop_duplicates antes."""
    f = dados.fator_retorno_total()
    ib = dados.ibov()
    out = []
    for a, e, t, du in zip(cad["ativo"], cad["E"], cad["T"], cad["du"]):
        if a == "BOVA11":
            if e in ib.index and t in ib.index:
                out.append(ib[t] / ib[e] - 1.0 - 0.001 * du / 252.0)
            else:
                out.append(np.nan)
        elif a in f.columns and e in f.index and t in f.index:
            out.append(f.at[t, a] / f.at[e, a] - 1.0)
        else:
            out.append(np.nan)
    return pd.Series(out, index=cad.index)


def _ajustar_strike_final(cad):
    """Strike de liquidacao das series que NAO negociaram no dia do vencimento.

    A B3 ajusta o strike de TODAS as series do ativo na data-ex do provento (dividendo + JCP liquido, desdobramento,
    bonificacao), mas o COTAHIST so mostra o strike novo nas series que negociam depois. A ultima linha de uma serie que
    parou de negociar antes da data-ex traz o strike velho: usa-lo superestimaria o pagamento de uma put (K velho maior)
    e subestimaria o de uma call. Correcao: o ajuste acumulado no ciclo, medido nas series do mesmo ativo e vencimento que
    negociaram NO DIA do vencimento (K_E - K_T observado), e aplicado as demais. Aditivo (dividendo) ou multiplicativo
    (desdobramento), o que tiver menor dispersao entre as series medidas. Sem serie medida, vale a ultima linha."""
    cad = cad.copy()
    cad["K_T_corrigido"] = False
    ref = cad[cad["ult_dia"] == cad["T"]]
    if ref.empty:
        return cad
    ref = ref.assign(dif=ref["exercicio"] - ref["K_T_obs"], raz=ref["K_T_obs"] / ref["exercicio"])
    g = ref.groupby(["ativo", "T"])
    ad = g["dif"].median().rename("ad_med")
    rz = g["raz"].median().rename("rz_med")
    disp_ad = (ref["dif"] - ref.set_index(["ativo", "T"]).index.map(ad)).abs().groupby([ref["ativo"], ref["T"]]).median() / g["exercicio"].mean()
    disp_rz = (ref["raz"] - ref.set_index(["ativo", "T"]).index.map(rz)).abs().groupby([ref["ativo"], ref["T"]]).median()
    n = g.size().rename("n_ref")
    aj = pd.concat([ad, rz, disp_ad.rename("d_ad"), disp_rz.rename("d_rz"), n], axis=1).reset_index()
    cad = cad.merge(aj, on=["ativo", "T"], how="left")
    parada = (cad["ult_dia"] < cad["T"]) & cad["n_ref"].notna() & (cad["n_ref"] >= 3)
    aditivo = cad["d_ad"] <= cad["d_rz"]
    novo = np.where(aditivo, cad["exercicio"] - cad["ad_med"], cad["exercicio"] * cad["rz_med"])
    mudou = parada & (np.abs(novo - cad["K_T_obs"]) > 0.004)
    cad["K_T"] = np.where(parada, novo, cad["K_T_obs"])
    cad["K_T_corrigido"] = mudou
    return cad.drop(columns=["ad_med", "rz_med", "d_ad", "d_rz", "n_ref"])
