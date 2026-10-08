"""Fixtures sinteticas no layout dos dados abertos da CVM (CSV ';' latin-1, ESCALA MIL).

Empresa 1000 (consolidado): 2022 com trimestres iguais (receita 80/tri) e 2023 com
acumulados 100 / 220 / 350 (v1) ou 360 (v2, reapresentacao do 3T) / 500 (DFP).
Empresa 2000: so individual (lucro liquido em 3.09).
"""
import numpy as np
import pandas as pd
import pytest

from quant.dados import contas_cvm
from quant.dados import cvm_fundamentos as cf

CNPJ = "11.111.111/0001-11"
CNPJ2 = "22.222.222/0001-22"
FIM_TRI = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}


def _doc(cd_cvm, cnpj, ano, tri, versao, receb, acum, bal, escopo="con", escala="MIL", ll_conta="3.11"):
    """Um documento (ITR se tri<4, DFP se tri==4) com DRE/DFC acumulados e balanco."""
    tipo = "DFP" if tri == 4 else "ITR"
    dt_refer = f"{ano}-{FIM_TRI[tri]}"
    base = dict(CNPJ_CIA=cnpj, DT_REFER=dt_refer, VERSAO=versao, DENOM_CIA=f"EMPRESA {cd_cvm}",
                CD_CVM=cd_cvm, MOEDA="REAL", ESCALA_MOEDA=escala, ORDEM_EXERC="ÚLTIMO",
                DT_INI_EXERC=f"{ano}-01-01", DT_FIM_EXERC=dt_refer, ST_CONTA_FIXA="S")
    indice = [dict(CNPJ_CIA=cnpj, DT_REFER=dt_refer, VERSAO=versao, DENOM_CIA=f"EMPRESA {cd_cvm}",
                   CD_CVM=cd_cvm, CATEG_DOC=tipo, ID_DOC=f"{cd_cvm}{ano}{tri}{versao}", DT_RECEB=receb,
                   LINK_DOC="http://x")]

    def linha(cod, desc, valor, grupo, **kw):
        d = dict(base, GRUPO_DFP=grupo, CD_CONTA=cod, DS_CONTA=desc, VL_CONTA=f"{valor:.2f}")
        d.update(kw)
        return d
    dre = [linha("3.01", "Receita de Venda de Bens e/ou Serviços", acum["receita"], "DRE"),
           linha("3.03", "Resultado Bruto", acum["lucro_bruto"], "DRE"),
           linha("3.05", "Resultado Antes do Resultado Financeiro e dos Tributos", acum["ebit"], "DRE"),
           linha("3.06", "Resultado Financeiro", -1.0, "DRE"),
           linha(ll_conta, "Lucro/Prejuízo Consolidado do Período", acum["lucro_liquido"], "DRE"),
           linha("3.99", "Lucro por Ação - (Reais / Ação)", 0.0, "DRE"),
           linha("3.99.01", "Lucro Básico por Ação", 0.0, "DRE"),
           linha("3.99.01.01", "ON", acum["lucro_liquido"] / 10, "DRE")]
    dfc = [linha("6.01", "Caixa Líquido Atividades Operacionais", acum["fco"], "DFC"),
           linha("6.01.01", "Caixa Gerado nas Operações", acum["fco"] + 3, "DFC"),
           linha("6.01.01.01", "Lucro Líquido", acum["lucro_liquido"], "DFC"),
           linha("6.01.01.02", "Depreciação e Amortização", acum["depreciacao"], "DFC"),
           linha("6.02", "Caixa Líquido Atividades de Investimento", acum["capex"] - 2, "DFC"),
           linha("6.02.01", "Aquisição de Imobilizado", acum["capex"], "DFC"),
           linha("6.02.02", "Aplicações Financeiras", -2.0, "DFC")]
    # balanco: sem DT_INI_EXERC; PENULTIMO (comparativo) entra so para provar que e ignorado
    bpa = [linha("1", "Ativo Total", bal["ativo"], "BPA"),
           linha("1.01", "Ativo Circulante", bal["ativo"] / 2, "BPA"),
           linha("1.01.01", "Caixa e Equivalentes de Caixa", bal["caixa"], "BPA"),
           linha("1.01.02", "Aplicações Financeiras", bal["aplicacoes"], "BPA"),
           linha("1", "Ativo Total", 1.0, "BPA", ORDEM_EXERC="PENÚLTIMO", DT_FIM_EXERC=f"{ano-1}-12-31")]
    bpp = [linha("2.01", "Passivo Circulante", bal["emprestimos_cp"] + 50, "BPP"),
           linha("2.01.04", "Empréstimos e Financiamentos", bal["emprestimos_cp"], "BPP"),
           linha("2.02.01", "Empréstimos e Financiamentos", bal["emprestimos_lp"], "BPP"),
           linha("2.03", "Patrimônio Líquido Consolidado", bal["pl"], "BPP")]
    for l in bpa + bpp:
        l.pop("DT_INI_EXERC", None)
    return tipo, ano, indice, {("DRE", escopo): dre, ("DFC_MI", escopo): dfc, ("BPA", escopo): bpa, ("BPP", escopo): bpp}


def _acum(receita, lb, ebit, ll, fco, da, capex):
    return dict(receita=receita, lucro_bruto=lb, ebit=ebit, lucro_liquido=ll, fco=fco, depreciacao=da, capex=capex)


BAL_2023 = dict(ativo=1200, caixa=80, aplicacoes=40, emprestimos_cp=100, emprestimos_lp=300, pl=500)
BAL_2022 = dict(ativo=1000, caixa=50, aplicacoes=30, emprestimos_cp=100, emprestimos_lp=200, pl=400)

DOCS = [
    # 2022: cada trimestre com receita 80, LB 30, EBIT 15, LL 8, FCO 12, D&A 4, capex -6
    _doc(1000, CNPJ, 2022, 1, 1, "2022-05-10", _acum(80, 30, 15, 8, 12, 4, -6), BAL_2022),
    _doc(1000, CNPJ, 2022, 2, 1, "2022-08-10", _acum(160, 60, 30, 16, 24, 8, -12), BAL_2022),
    _doc(1000, CNPJ, 2022, 3, 1, "2022-11-10", _acum(240, 90, 45, 24, 36, 12, -18), BAL_2022),
    _doc(1000, CNPJ, 2022, 4, 1, "2023-03-20", _acum(320, 120, 60, 32, 48, 16, -24), BAL_2022),
    # 2023
    _doc(1000, CNPJ, 2023, 1, 1, "2023-05-10", _acum(100, 40, 20, 10, 15, 5, -8), BAL_2022),
    _doc(1000, CNPJ, 2023, 2, 1, "2023-08-10", _acum(220, 90, 45, 22, 33, 10, -20), BAL_2022),
    _doc(1000, CNPJ, 2023, 3, 1, "2023-11-10", _acum(350, 140, 70, 35, 50, 15, -30), BAL_2022),
    _doc(1000, CNPJ, 2023, 3, 2, "2024-01-15", _acum(360, 140, 70, 35, 50, 15, -30), BAL_2022),   # reapresentacao
    _doc(1000, CNPJ, 2023, 4, 1, "2024-03-20", _acum(500, 200, 100, 50, 75, 20, -45), BAL_2023),
    # empresa 2000: so individual, lucro em 3.09
    _doc(2000, CNPJ2, 2023, 4, 1, "2024-03-25", _acum(40, 10, 5, 2, 6, 1, -1), BAL_2022, escopo="ind", ll_conta="3.09"),
]


def _zips():
    """Agrupa os documentos por (tipo, ano) e monta um zip por grupo, como a CVM publica."""
    grupos = {}
    for tipo, ano, indice, demos in DOCS:
        g = grupos.setdefault((tipo, ano), {"indice": [], "demos": {}})
        g["indice"] += indice
        for k, linhas in demos.items():
            g["demos"].setdefault(k, []).extend(linhas)
    return {k: cf.montar_zip(k[0], k[1], g["indice"], g["demos"]) for k, g in grupos.items()}


@pytest.fixture(scope="module")
def fundamentos():
    partes = [cf.parse_zip(conteudo, tipo) for (tipo, ano), conteudo in _zips().items()]
    return pd.concat(partes, ignore_index=True)


def _valor(df, cd_cvm, dt_refer, conta, versao=None, demo=None):
    m = (df.cd_cvm == cd_cvm) & (df.dt_refer == pd.Timestamp(dt_refer)) & (df.conta == conta) & (df.ordem_exerc == "ULTIMO")
    if versao is not None:
        m &= df.versao == versao
    if demo is not None:
        m &= df.demo == demo
    return df.loc[m, "valor_reais"]


# ── (1) parse e escala ──────────────────────────────────────
def test_parse_zip_aplica_escala_mil_e_traz_dt_receb(fundamentos):
    df = fundamentos
    assert list(df.columns) == cf.COLUNAS
    ativo = _valor(df, 1000, "2023-12-31", "1", demo="BPA")
    assert ativo.tolist() == [1200 * 1000.0]                         # MIL -> reais
    assert _valor(df, 1000, "2023-12-31", "3.99.01.01").tolist() == [5.0]      # LPA em reais/acao: 50/10 = 5,00 SEM escala
    linha = df[(df.cd_cvm == 1000) & (df.dt_refer == "2023-09-30") & (df.versao == 2)].iloc[0]
    assert linha["dt_receb"] == pd.Timestamp("2024-01-15") and linha["tipo"] == "ITR"
    assert linha["descricao"] and "�" not in "".join(df["descricao"].unique())   # latin-1 decodificado
    dre = df[(df.cd_cvm == 1000) & (df.demo == "DRE") & (df.dt_refer == "2023-09-30") & (df.ordem_exerc == "ULTIMO")]
    assert set(dre["meses"].dropna().astype(int)) == {9}
    assert df.loc[df.demo == "BPA", "meses"].isna().all()
    assert (df.loc[(df.demo == "BPA") & (df.conta == "1"), "ordem_exerc"] == "PENULTIMO").sum() == len(DOCS)


def test_escala_unidade_nao_multiplica():
    tipo, ano, indice, demos = _doc(1000, CNPJ, 2023, 1, 1, "2023-05-10", _acum(100, 40, 20, 10, 15, 5, -8), BAL_2022,
                                    escala="UNIDADE")
    df = cf.parse_zip(cf.montar_zip(tipo, ano, indice, demos), tipo)
    assert _valor(df, 1000, "2023-03-31", "3.01").tolist() == [100.0]


def test_valor_aceita_ponto_decimal_e_virgula():
    assert cf._valor("1234567.00") == 1234567.0
    assert cf._valor("1.234") == 1.234              # LPA: ponto e decimal, nunca milhar
    assert cf._valor("1.234.567,89") == 1234567.89
    assert cf._valor("1.234.567") == 1234567.0      # grupos de 3 sem virgula: milhar (numero_br)
    assert cf._valor("-1.234.567") == -1234567.0
    assert np.isnan(cf._valor("")) and np.isnan(cf._valor("abc")) and np.isnan(cf._valor(None))


def test_data_aceita_iso_e_dd_mm_aaaa():
    d = cf._data(pd.Series(["2024-03-20", "20/03/2024", "2024-03-20 15:30:00", "", "lixo"]))
    assert d.tolist()[:3] == [pd.Timestamp("2024-03-20")] * 3
    assert d.isna().tolist()[3:] == [True, True]


def test_parse_indice_duplicado_fica_com_o_maior_dt_receb():
    """Se o indice repetir (cd_cvm, dt_refer, versao) com DT_RECEB diferentes, o conservador
    e considerar o documento conhecido so na data mais tardia (nunca antecipar)."""
    base = dict(CNPJ_CIA=CNPJ, DT_REFER="2023-12-31", VERSAO=1, DENOM_CIA="X", CD_CVM=1000,
                CATEG_DOC="DFP", ID_DOC="1", LINK_DOC="")
    z = cf.montar_zip("dfp", 2023, [dict(base, DT_RECEB="2024-03-20"), dict(base, DT_RECEB="2024-03-01"),
                                    dict(base, DT_RECEB="")], {})
    import zipfile, io
    idx = cf.parse_indice(zipfile.ZipFile(io.BytesIO(z)).read("dfp_cia_aberta_2023.csv"))
    assert len(idx) == 1 and idx["dt_receb"].iloc[0] == pd.Timestamp("2024-03-20")


# ── (2) point-in-time: versoes ──────────────────────────────
def test_visao_em_usa_versao_recebida_ate_t(fundamentos):
    df = fundamentos
    antes = cf.visao_em(df, "2023-11-01")                # 3T23 ainda nao recebido
    assert _valor(antes, 1000, "2023-09-30", "3.01").empty
    entre = cf.visao_em(df, "2023-12-01")                # v1 recebida em 10/11, v2 so em 15/01
    assert _valor(entre, 1000, "2023-09-30", "3.01").tolist() == [350_000.0]
    depois = cf.visao_em(df, "2024-02-01")
    assert _valor(depois, 1000, "2023-09-30", "3.01").tolist() == [360_000.0]
    assert len(depois[(depois.cd_cvm == 1000) & (depois.dt_refer == "2023-09-30") & (depois.conta == "3.01")]) == 1


def test_visao_em_descarta_linhas_sem_dt_receb(fundamentos):
    df = fundamentos.copy()
    df.loc[df.dt_refer == "2023-12-31", "dt_receb"] = pd.NaT
    v = cf.visao_em(df, "2030-01-01")
    assert (v.dt_refer == "2023-12-31").sum() == 0


# ── (3) trimestralizacao ────────────────────────────────────
def test_trimestralizar_por_diferenca(fundamentos):
    q = cf.trimestralizar(cf.visao_em(fundamentos, "2024-04-01"))
    rec = q[(q.cd_cvm == 1000) & (q.conta == "3.01")].set_index("dt_refer")
    assert rec.loc["2023-03-31", "valor_reais"] == 100_000.0                     # Q1 = acumulado
    assert rec.loc["2023-06-30", "valor_reais"] == (220 - 100) * 1000.0          # Q2 = 6m - Q1
    assert rec.loc["2023-09-30", "valor_reais"] == (360 - 220) * 1000.0          # Q3 = 9m(v2) - 6m
    assert rec.loc["2023-12-31", "valor_reais"] == (500 - 360) * 1000.0          # Q4 = DFP - 9m
    assert rec.loc["2023-12-31", "trimestre"] == 4
    # dt_receb do trimestre = a peca mais tardia (Q4 depende da DFP recebida em 20/03/2024)
    assert rec.loc["2023-12-31", "dt_receb"] == pd.Timestamp("2024-03-20")
    assert rec.loc["2023-06-30", "dt_receb"] == pd.Timestamp("2023-08-10")
    # com a visao v1 (antes da reapresentacao) Q4 nao existe e Q3 usa 350
    q1 = cf.trimestralizar(cf.visao_em(fundamentos, "2023-12-01"))
    r1 = q1[(q1.cd_cvm == 1000) & (q1.conta == "3.01")].set_index("dt_refer")
    assert r1.loc["2023-09-30", "valor_reais"] == (350 - 220) * 1000.0
    assert pd.Timestamp("2023-12-31") not in r1.index
    # balanco nao e trimestralizado
    assert not q["demo"].isin(cf.DEMOS_BALANCO).any()


def _docs_com_trimestre_isolado():
    """ITR no layout REAL: alem da linha acumulada (01/01-30/06) o 2T e o 3T trazem a linha
    do trimestre isolado (01/04-30/06, 01/07-30/09) com o mesmo DT_FIM e ORDEM ULTIMO."""
    docs = []
    for tri, receb, acum in [(1, "2023-05-10", _acum(100, 40, 20, 10, 15, 5, -8)),
                             (2, "2023-08-10", _acum(220, 90, 45, 22, 33, 10, -20)),
                             (3, "2023-11-10", _acum(350, 140, 70, 35, 50, 15, -30)),
                             (4, "2024-03-20", _acum(500, 200, 100, 50, 75, 20, -45))]:
        tipo, ano, idx, demos = _doc(1000, CNPJ, 2023, tri, 1, receb, acum, BAL_2023)
        if tri in (2, 3):
            ini = {2: "2023-04-01", 3: "2023-07-01"}[tri]
            for k in (("DRE", "con"), ("DFC_MI", "con")):
                isoladas = []
                for l in demos[k]:
                    d = dict(l, DT_INI_EXERC=ini, VL_CONTA=f"{float(l['VL_CONTA']) / 2:.2f}")   # valor qualquer
                    isoladas.append(d)
                demos[k] = demos[k] + isoladas
        docs.append((tipo, ano, idx, demos))
    return docs


def test_trimestralizar_ignora_linha_do_trimestre_isolado_do_itr():
    grupos = {}
    for tipo, ano, indice, demos in _docs_com_trimestre_isolado():
        g = grupos.setdefault((tipo, ano), {"indice": [], "demos": {}})
        g["indice"] += indice
        for k, linhas in demos.items():
            g["demos"].setdefault(k, []).extend(linhas)
    df = pd.concat([cf.parse_zip(cf.montar_zip(k[0], k[1], g["indice"], g["demos"]), k[0])
                    for k, g in grupos.items()], ignore_index=True)
    # as linhas isoladas estao na tabela longa (dt_ini 01/04 e 01/07) ...
    assert (df.dt_ini == "2023-04-01").any() and (df.dt_ini == "2023-07-01").any()
    q = cf.trimestralizar(cf.visao_em(df, "2024-04-01"))
    rec = q[(q.cd_cvm == 1000) & (q.conta == "3.01")]
    # ... mas so a acumulada entra: um trimestre por dt_refer, sempre por diferenca
    assert rec.groupby("dt_refer").size().tolist() == [1, 1, 1, 1]
    assert rec.set_index("dt_refer")["trimestre"].tolist() == [1, 2, 3, 4]
    assert rec.set_index("dt_refer")["valor_reais"].tolist() == [100_000.0, 120_000.0, 130_000.0, 150_000.0]
    x = cf.ttm(df, 1000, "2024-04-01")
    assert x["receita"] == 500_000.0
    assert x["capex"] == -45_000.0 and x["depreciacao"] == 20_000.0     # somas por descricao nao dobram
    assert x["fco"] == 75_000.0 and x["lpa"] == 5.0


def test_parse_zip_sem_indice_deixa_dt_receb_nat_e_fora_da_visao():
    tipo, ano, indice, demos = _doc(1000, CNPJ, 2023, 1, 1, "2023-05-10", _acum(100, 40, 20, 10, 15, 5, -8), BAL_2022)
    df = cf.parse_zip(cf.montar_zip(tipo, ano, [], demos), tipo)
    assert len(df) > 0 and df["dt_receb"].isna().all() and str(df["dt_receb"].dtype).startswith("datetime64")
    assert cf.visao_em(df, "2030-01-01").empty and cf.ttm(df, 1000, "2030-01-01") is None


# ── (4) TTM point-in-time ───────────────────────────────────
def test_ttm_soma_quatro_trimestres_e_ignora_o_futuro(fundamentos):
    df = fundamentos
    # em 01/04/2024 os 4 trimestres de 2023 estao disponiveis (DFP recebida em 20/03)
    x = cf.ttm(df, 1000, "2024-04-01")
    assert x is not None and x["escopo"] == "con"
    assert x["trimestres"][-1] == pd.Timestamp("2023-12-31").date() and x["dt_refer"] == pd.Timestamp("2023-12-31").date()
    assert x["receita"] == 500_000.0 and x["lucro_bruto"] == 200_000.0 and x["ebit"] == 100_000.0
    assert x["lucro_liquido"] == 50_000.0 and x["fco"] == 75_000.0 and x["capex"] == -45_000.0
    assert x["depreciacao"] == 20_000.0 and x["ebitda"] == 120_000.0 and x["fcf"] == 30_000.0
    assert x["lpa"] == 5.0                                            # soma dos 4 LPAs trimestrais, sem escala MIL
    assert x["ativo"] == 1_200_000.0 and x["caixa"] == 120_000.0 and x["pl"] == 500_000.0
    assert x["divida_bruta"] == 400_000.0 and x["divida_liquida"] == 280_000.0
    assert x["receita_anterior"] == 320_000.0                         # 4 trimestres de 2022
    assert x["dt_receb"] == pd.Timestamp("2024-03-20").date()
    # em 01/03/2024 a DFP 2023 ainda nao chegou: janela = 4T22..3T23 (3T23 ja na versao 2)
    y = cf.ttm(df, 1000, "2024-03-01")
    assert y["trimestres"][-1] == pd.Timestamp("2023-09-30").date()
    assert y["receita"] == (80 + 100 + 120 + 140) * 1000.0
    assert y["ativo"] == 1_000_000.0                                    # balanco do 3T23 (BAL_2022)
    # em 01/12/2023 a reapresentacao do 3T ainda nao existe: Q3 = 350 - 220
    z = cf.ttm(df, 1000, "2023-12-01")
    assert z["receita"] == (80 + 100 + 120 + 130) * 1000.0
    assert z["dt_receb"] == pd.Timestamp("2023-11-10").date()


def test_ttm_devolve_none_sem_quatro_trimestres(fundamentos):
    assert cf.ttm(fundamentos, 1000, "2023-01-01") is None          # so 3 trimestres de 2022
    assert cf.ttm(fundamentos, 1000, "2023-04-01")["receita"] == 320_000.0   # DFP 2022 chegou em 20/03
    assert cf.ttm(fundamentos, 2000, "2025-01-01") is None          # empresa 2000 so tem a DFP
    assert cf.ttm(fundamentos, 9999, "2025-01-01") is None


def test_ttm_nao_pula_trimestre_faltante(fundamentos):
    df = fundamentos[~((fundamentos.cd_cvm == 1000) & (fundamentos.dt_refer == "2023-06-30"))]
    # sem o 2T23 nao da para derivar Q2 nem Q3 (9m - 6m); a janela mais recente seria
    # 4T22, 1T23, 4T23 -> nao consecutivos -> None em vez de somar o que tem
    assert cf.ttm(df, 1000, "2024-04-01") is None


def test_escopo_individual_quando_nao_ha_consolidado(fundamentos):
    v = cf.visao_em(fundamentos[fundamentos.cd_cvm == 2000], "2025-01-01")
    assert cf.escopo_padrao(v) == "ind"
    d = v[(v.dt_refer == "2023-12-31")]
    assert contas_cvm.extrair(d, "lucro_liquido") == 2_000.0          # 3.09 no individual


# ── (5) metricas ────────────────────────────────────────────
def test_metricas_conferidas_a_mao(fundamentos):
    x = cf.ttm(fundamentos, 1000, "2024-04-01")
    m = cf.metricas(x, valor_mercado=600_000.0)
    assert abs(m["dl_ebitda"] - 280 / 120) < 1e-12
    assert abs(m["gpoa"] - 200 / 1200) < 1e-12
    assert abs(m["roic"] - 100 * 0.66 / (280 + 500)) < 1e-12
    assert abs(m["roe"] - 50 / 500) < 1e-12
    assert abs(m["margem_bruta"] - 0.4) < 1e-12
    assert abs(m["crescimento_receita"] - (500 / 320 - 1)) < 1e-12
    assert abs(m["fcf_yield"] - 30 / 600) < 1e-12
    assert np.isnan(cf.metricas(x)["fcf_yield"])
    fin = cf.metricas(x, financeira=True)
    assert np.isnan(fin["roic"]) and np.isnan(fin["dl_ebitda"]) and abs(fin["roe"] - 0.1) < 1e-12
    assert cf.metricas(None) is None


def test_metricas_sem_crescimento_com_menos_de_8_trimestres(fundamentos):
    x = cf.ttm(fundamentos, 1000, "2023-04-01")     # so os 4 trimestres de 2022
    assert np.isnan(x["receita_anterior"]) and np.isnan(cf.metricas(x)["crescimento_receita"])


def test_metricas_nao_inventam_retorno_com_denominador_negativo_ou_zero(fundamentos):
    x = dict(cf.ttm(fundamentos, 1000, "2024-04-01"))
    x["pl"], x["lucro_liquido"] = -100_000.0, -20_000.0          # PL negativo e prejuizo: ROE "positivo" seria lixo
    x["divida_liquida"] = 50_000.0                                # capital = DL + PL < 0
    x["ebitda"] = -1.0
    m = cf.metricas(x)
    assert np.isnan(m["roe"]) and np.isnan(m["roic"]) and np.isnan(m["dl_ebitda"])
    y = dict(cf.ttm(fundamentos, 1000, "2024-04-01"))
    y["receita"], y["ativo"] = 0.0, float("nan")
    m = cf.metricas(y, valor_mercado=0.0)
    assert np.isnan(m["margem_bruta"]) and np.isnan(m["gpoa"]) and np.isnan(m["fcf_yield"])


# ── contas_cvm ──────────────────────────────────────────────
def test_extrair_nao_soma_pai_com_filho_e_ignora_acentos():
    linhas = pd.DataFrame({
        "demo": ["DFC_MI"] * 4,
        "conta": ["6.01.01.02", "6.01.01.02.01", "6.01.01.02.02", "6.02.01"],
        "descricao": ["Depreciação e Amortização", "Depreciação", "Amortização", "Aquisição de imobilizado"],
        "valor_reais": [10.0, 6.0, 4.0, -7.0],
    })
    assert contas_cvm.extrair(linhas, "depreciacao") == 10.0
    assert contas_cvm.extrair(linhas, "capex") == -7.0
    assert np.isnan(contas_cvm.extrair(linhas, "receita"))


def test_extrair_prefere_dfc_indireto_e_excecoes_sobrescrevem():
    linhas = pd.DataFrame({
        "demo": ["DFC_MD", "DFC_MI", "DRE"],
        "conta": ["6.01", "6.01", "3.13"],
        "descricao": ["FCO metodo direto", "FCO metodo indireto", "Lucro do periodo (plano proprio)"],
        "valor_reais": [1.0, 2.0, 9.0],
    })
    assert contas_cvm.extrair(linhas, "fco") == 2.0
    assert np.isnan(contas_cvm.extrair(linhas, "lucro_liquido", cd_cvm=77))
    contas_cvm.EXCECOES[77] = {"lucro_liquido": {"codigos": ["3.13"]}}
    try:
        assert contas_cvm.extrair(linhas, "lucro_liquido", cd_cvm=77) == 9.0
        assert np.isnan(contas_cvm.extrair(linhas, "lucro_liquido", cd_cvm=78))
    finally:
        contas_cvm.EXCECOES.pop(77)


def test_eh_financeira():
    assert contas_cvm.eh_financeira("Bancos")
    assert contas_cvm.eh_financeira("Seguradoras e Corretoras")
    assert not contas_cvm.eh_financeira("Petróleo e Gás")
    assert not contas_cvm.eh_financeira(None)


# ── banco (parquet) ─────────────────────────────────────────
def test_gravar_e_carregar_parquet(fundamentos, tmp_path, monkeypatch):
    monkeypatch.setattr(cf, "DIR_PARQUET", str(tmp_path))
    n23 = cf.gravar_ano(fundamentos, 2023)
    n22 = cf.gravar_ano(fundamentos, 2022)
    assert n22 + n23 == len(fundamentos)
    de_volta = cf.carregar([2022, 2023, 2024])
    assert len(de_volta) == len(fundamentos) and list(de_volta.columns) == cf.COLUNAS
    assert cf.ttm(de_volta, 1000, "2024-04-01")["receita"] == 500_000.0
    assert cf.carregar([2022], cd_cvm=2000).empty
    assert cf.carregar([1999]).empty
    sub = cf.carregar([2023], cd_cvm=[2000], colunas=["conta", "valor_reais"])
    assert list(sub.columns) == ["conta", "valor_reais"] and len(sub) == (fundamentos.cd_cvm == 2000).sum()
    # ano sem nada: parquet vazio tipado, e a concat com anos cheios continua usavel na visao
    assert cf.gravar_ano(fundamentos.iloc[0:0], 2021) == 0
    tudo = cf.carregar([2021, 2022, 2023])
    assert len(tudo) == len(fundamentos) and cf.ttm(tudo, 1000, "2024-04-01")["receita"] == 500_000.0


def test_baixar_nunca_levanta_e_devolve_none_em_falha(tmp_path, monkeypatch):
    monkeypatch.setattr(cf, "DIR_CVM", str(tmp_path))
    monkeypatch.setattr(cf, "http_get", lambda *a, **k: None)
    assert cf.baixar("DFP", 2023) is None
    assert not list(tmp_path.iterdir())

    class Resp:
        content = b"<html>erro</html>" * 100
    monkeypatch.setattr(cf, "http_get", lambda *a, **k: Resp())
    assert cf.baixar("DFP", 2023) is None                           # nao e zip: nao grava lixo
    assert not list(tmp_path.iterdir())

    tipo, ano, indice, demos = _doc(1000, CNPJ, 2023, 4, 1, "2024-03-20", _acum(500, 200, 100, 50, 75, 20, -45), BAL_2023)
    conteudo = cf.montar_zip(tipo, ano, indice, demos) + b"\0" * 2000
    chamadas = []

    class Zip:
        content = conteudo
    monkeypatch.setattr(cf, "http_get", lambda url, **k: chamadas.append(url) or Zip())
    caminho = cf.baixar("DFP", 2023)
    assert caminho == cf.caminho_bruto("DFP", 2023) and open(caminho, "rb").read() == conteudo
    assert chamadas == ["https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_2023.zip"]
    # com o arquivo local e a rede fora, devolve o que ja tem (ano antigo nem tenta a rede)
    monkeypatch.setattr(cf, "http_get", lambda *a, **k: None)
    assert cf.baixar("DFP", 2023) == caminho
    # atualizar usa o zip local (ano antigo: sem rede) e grava o parquet; tipo sem arquivo nem rede -> None
    monkeypatch.setattr(cf, "DIR_PARQUET", str(tmp_path / "banco"))
    res = cf.atualizar([2023], tipos=("DFP",))
    assert res[2023] > 0 and len(cf.carregar([2023])) == res[2023]
    assert cf.atualizar([2023], tipos=("ITR",)) == {2023: None}


def test_parse_zip_tolerante_a_lixo():
    assert cf.parse_zip(b"nao e zip", "DFP").empty
    assert cf.parse_zip(cf.montar_zip("dfp", 2020, [], {}), "DFP").empty
