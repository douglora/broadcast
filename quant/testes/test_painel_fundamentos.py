"""Fixtures no layout dos dados abertos da CVM, com duas empresas e uma reapresentacao.

O teste que importa e o de EQUIVALENCIA: o painel tem de devolver, para toda data e toda
empresa, exatamente o que o laco ingenuo com cvm_fundamentos.ttm() devolveria. Se essa
igualdade quebrar, o painel esta inventando ou perdendo informacao point-in-time.
"""
import numpy as np
import pandas as pd
import pytest

from quant.dados import cvm_fundamentos as cf
from quant.dados import painel_fundamentos as pf

CNPJ = "11.111.111/0001-11"
CNPJ2 = "22.222.222/0001-22"
FIM_TRI = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}


def _doc(cd_cvm, cnpj, ano, tri, versao, receb, acum, bal, escopo="con", ll_conta="3.11"):
    """Um documento (ITR se tri<4, DFP se tri==4) com DRE/DFC acumulados e balanco."""
    tipo = "DFP" if tri == 4 else "ITR"
    dt_refer = f"{ano}-{FIM_TRI[tri]}"
    base = dict(CNPJ_CIA=cnpj, DT_REFER=dt_refer, VERSAO=versao, DENOM_CIA=f"EMPRESA {cd_cvm}",
                CD_CVM=cd_cvm, MOEDA="REAL", ESCALA_MOEDA="MIL", ORDEM_EXERC="ÚLTIMO",
                DT_INI_EXERC=f"{ano}-01-01", DT_FIM_EXERC=dt_refer, ST_CONTA_FIXA="S")
    indice = [dict(CNPJ_CIA=cnpj, DT_REFER=dt_refer, VERSAO=versao, DENOM_CIA=f"EMPRESA {cd_cvm}",
                   CD_CVM=cd_cvm, CATEG_DOC=tipo, ID_DOC=f"{cd_cvm}{ano}{tri}{versao}",
                   DT_RECEB=receb, LINK_DOC="http://x")]

    def linha(cod, desc, valor, grupo, **kw):
        d = dict(base, GRUPO_DFP=grupo, CD_CONTA=cod, DS_CONTA=desc, VL_CONTA=f"{valor:.2f}")
        d.update(kw)
        return d
    dre = [linha("3.01", "Receita de Venda de Bens e/ou Serviços", acum["receita"], "DRE"),
           linha("3.03", "Resultado Bruto", acum["lucro_bruto"], "DRE"),
           linha("3.05", "Resultado Antes do Resultado Financeiro e dos Tributos", acum["ebit"], "DRE"),
           linha("3.06", "Resultado Financeiro", -1.0, "DRE"),
           linha(ll_conta, "Lucro/Prejuízo Consolidado do Período", acum["lucro_liquido"], "DRE"),
           linha("3.99.01.01", "ON", acum["lucro_liquido"] / 10, "DRE")]
    dfc = [linha("6.01", "Caixa Líquido Atividades Operacionais", acum["fco"], "DFC"),
           linha("6.01.01", "Caixa Gerado nas Operações", acum["fco"] + 3, "DFC"),
           linha("6.01.01.02", "Depreciação e Amortização", acum["depreciacao"], "DFC"),
           linha("6.02", "Caixa Líquido Atividades de Investimento", acum["capex"] - 2, "DFC"),
           linha("6.02.01", "Aquisição de Imobilizado", acum["capex"], "DFC")]
    bpa = [linha("1", "Ativo Total", bal["ativo"], "BPA"),
           linha("1.01", "Ativo Circulante", bal["ativo"] / 2, "BPA"),
           linha("1.01.01", "Caixa e Equivalentes de Caixa", bal["caixa"], "BPA")]
    bpp = [linha("2.01", "Passivo Circulante", bal["emprestimos_cp"] + 50, "BPP"),
           linha("2.01.04", "Empréstimos e Financiamentos", bal["emprestimos_cp"], "BPP"),
           linha("2.02.01", "Empréstimos e Financiamentos", bal["emprestimos_lp"], "BPP"),
           linha("2.03", "Patrimônio Líquido Consolidado", bal["pl"], "BPP")]
    for l in bpa + bpp:
        l.pop("DT_INI_EXERC", None)
    return tipo, ano, indice, {("DRE", escopo): dre, ("DFC_MI", escopo): dfc,
                               ("BPA", escopo): bpa, ("BPP", escopo): bpp}


def _acum(receita, lb, ebit, ll, fco, da, capex):
    return dict(receita=receita, lucro_bruto=lb, ebit=ebit, lucro_liquido=ll,
                fco=fco, depreciacao=da, capex=capex)


BAL_A = dict(ativo=1000, caixa=50, emprestimos_cp=100, emprestimos_lp=200, pl=400)
BAL_B = dict(ativo=1200, caixa=80, emprestimos_cp=100, emprestimos_lp=300, pl=500)

DOCS = [
    _doc(1000, CNPJ, 2022, 1, 1, "2022-05-10", _acum(80, 30, 15, 8, 12, 4, -6), BAL_A),
    _doc(1000, CNPJ, 2022, 2, 1, "2022-08-10", _acum(160, 60, 30, 16, 24, 8, -12), BAL_A),
    _doc(1000, CNPJ, 2022, 3, 1, "2022-11-10", _acum(240, 90, 45, 24, 36, 12, -18), BAL_A),
    _doc(1000, CNPJ, 2022, 4, 1, "2023-03-20", _acum(320, 120, 60, 32, 48, 16, -24), BAL_A),
    _doc(1000, CNPJ, 2023, 1, 1, "2023-05-10", _acum(100, 40, 20, 10, 15, 5, -8), BAL_A),
    _doc(1000, CNPJ, 2023, 2, 1, "2023-08-10", _acum(220, 90, 45, 22, 33, 10, -20), BAL_A),
    _doc(1000, CNPJ, 2023, 3, 1, "2023-11-10", _acum(350, 140, 70, 35, 50, 15, -30), BAL_A),
    _doc(1000, CNPJ, 2023, 3, 2, "2024-01-15", _acum(360, 140, 70, 35, 50, 15, -30), BAL_A),
    _doc(1000, CNPJ, 2023, 4, 1, "2024-03-20", _acum(500, 200, 100, 50, 75, 20, -45), BAL_B),
    # empresa 2000: so individual, lucro em 3.09, entrega mais tarde
    _doc(2000, CNPJ2, 2022, 4, 1, "2023-03-25", _acum(40, 10, 5, 2, 6, 1, -1), BAL_A,
         escopo="ind", ll_conta="3.09"),
    _doc(2000, CNPJ2, 2023, 1, 1, "2023-05-25", _acum(12, 4, 2, 1, 2, 1, -1), BAL_A,
         escopo="ind", ll_conta="3.09"),
    _doc(2000, CNPJ2, 2023, 2, 1, "2023-08-25", _acum(26, 9, 4, 2, 5, 2, -2), BAL_A,
         escopo="ind", ll_conta="3.09"),
    _doc(2000, CNPJ2, 2023, 3, 1, "2023-11-25", _acum(40, 14, 6, 3, 8, 3, -3), BAL_A,
         escopo="ind", ll_conta="3.09"),
    _doc(2000, CNPJ2, 2023, 4, 1, "2024-03-25", _acum(56, 20, 9, 5, 12, 4, -5), BAL_B,
         escopo="ind", ll_conta="3.09"),
]

DATAS = [pd.Timestamp(d) for d in
         ["2023-01-31", "2023-04-28", "2023-06-30", "2023-09-29", "2023-11-30",
          "2023-12-29", "2024-01-31", "2024-02-29", "2024-03-29", "2024-06-28"]]


def _tabela(docs=DOCS):
    grupos = {}
    for tipo, ano, indice, demos in docs:
        g = grupos.setdefault((tipo, ano), {"indice": [], "demos": {}})
        g["indice"] += indice
        for k, linhas in demos.items():
            g["demos"].setdefault(k, []).extend(linhas)
    partes = [cf.parse_zip(cf.montar_zip(k[0], k[1], g["indice"], g["demos"]), k[0])
              for k, g in grupos.items()]
    return pd.concat(partes, ignore_index=True)


@pytest.fixture(scope="module")
def base():
    return _tabela()


# ─────────────────────────────────────────────────────────────
# Vintages e propagacao
# ─────────────────────────────────────────────────────────────
def test_vintages_sao_os_dt_receb_distintos_por_empresa(base):
    v = pf.vintages(base)
    assert set(v) == {1000, 2000}
    esperado_1000 = sorted(pd.to_datetime(
        ["2022-05-10", "2022-08-10", "2022-11-10", "2023-03-20", "2023-05-10",
         "2023-08-10", "2023-11-10", "2024-01-15", "2024-03-20"]))
    assert v[1000] == esperado_1000
    assert v[1000] == sorted(v[1000])                       # ordenado
    assert pf.vintages(base, cd_cvm=2000).keys() == {2000}


def test_vintages_ignora_linha_sem_dt_receb(base):
    sujo = base.copy()
    sujo.loc[sujo["dt_receb"] == pd.Timestamp("2023-05-10"), "dt_receb"] = pd.NaT
    assert pd.Timestamp("2023-05-10") not in pf.vintages(sujo)[1000]


def test_resolver_propaga_o_ultimo_vintage_e_nao_o_futuro(base):
    vint = pf.painel_vintages(base)
    p = pf.resolver(vint, DATAS)
    linha = p[(p["data"] == pd.Timestamp("2023-12-29")) & (p["cd_cvm"] == 1000)].iloc[0]
    assert linha["vintage"] == pd.Timestamp("2023-11-10")    # a reapresentacao so chega em 15/01
    linha2 = p[(p["data"] == pd.Timestamp("2024-01-31")) & (p["cd_cvm"] == 1000)].iloc[0]
    assert linha2["vintage"] == pd.Timestamp("2024-01-15")


def test_empresa_sem_documento_na_data_nao_aparece(base):
    p = pf.resolver(pf.painel_vintages(base), [pd.Timestamp("2022-06-30")])
    assert set(p["cd_cvm"]) == {1000}                        # a 2000 so entrega em 2023


# ─────────────────────────────────────────────────────────────
# Equivalencia com o laco ingenuo (o teste central)
# ─────────────────────────────────────────────────────────────
def test_painel_e_identico_a_chamar_ttm_em_cada_data(base):
    painel = pf.painel_ttm(base, DATAS)
    for data in DATAS:
        for cod in (1000, 2000):
            x = cf.ttm(base, cod, data)
            linhas = painel[(painel["data"] == data) & (painel["cd_cvm"] == cod)]
            if x is None:
                # ou a empresa nao aparece, ou aparece com dt_refer nulo
                assert linhas.empty or pd.isna(linhas.iloc[0]["dt_refer"])
                continue
            assert len(linhas) == 1
            r = linhas.iloc[0]
            assert r["escopo"] == x["escopo"]
            assert pd.Timestamp(r["dt_refer"]).date() == x["dt_refer"]
            assert pd.Timestamp(r["dt_receb"]).date() == x["dt_receb"]
            for c in pf.CAMPOS_TTM:
                a, b = r[c], x[c]
                assert (np.isnan(a) and np.isnan(b)) or abs(a - b) < 1e-9, f"{c} em {data}/{cod}"


def test_metricas_do_painel_sao_as_de_cvm_fundamentos(base):
    painel = pf.painel_ttm(base, DATAS, financeiras={2000})
    for data in DATAS:
        for cod in (1000, 2000):
            x = cf.ttm(base, cod, data)
            if x is None:
                continue
            m = cf.metricas(x, valor_mercado=None, financeira=(cod == 2000))
            r = painel[(painel["data"] == data) & (painel["cd_cvm"] == cod)].iloc[0]
            for c in ("roic", "roe", "gpoa", "dl_ebitda", "margem_bruta", "margem_ebit"):
                a, b = r[c], m[c]
                assert (np.isnan(a) and np.isnan(b)) or abs(a - b) < 1e-12, f"{c} em {data}/{cod}"
            esperado = m["roe"] if cod == 2000 else m["roic"]
            a = r["retorno_capital"]
            assert (np.isnan(a) and np.isnan(esperado)) or abs(a - esperado) < 1e-12


def test_financeira_nao_recebe_roic_nem_alavancagem(base):
    painel = pf.painel_ttm(base, DATAS, financeiras={2000})
    fin = painel[painel["cd_cvm"] == 2000].dropna(subset=["dt_refer"])
    assert len(fin) > 0
    assert fin["roic"].isna().all() and fin["dl_ebitda"].isna().all()
    assert fin["financeira"].all()
    nao_fin = painel[painel["cd_cvm"] == 1000].dropna(subset=["dt_refer"])
    assert not nao_fin["financeira"].any()


# ─────────────────────────────────────────────────────────────
# Point-in-time
# ─────────────────────────────────────────────────────────────
def test_reapresentacao_so_entra_depois_de_recebida(base):
    painel = pf.painel_ttm(base, DATAS)
    antes = painel[(painel["data"] == pd.Timestamp("2023-12-29")) & (painel["cd_cvm"] == 1000)].iloc[0]
    depois = painel[(painel["data"] == pd.Timestamp("2024-01-31")) & (painel["cd_cvm"] == 1000)].iloc[0]
    # 3T23 v1: acumulado 350 -> Q3 = 350 - 220 = 130; v2: 360 -> Q3 = 140 (em milhares)
    assert abs(antes["receita"] - (100 + 120 + 130 + 80) * 1000.0) < 1e-6
    assert abs(depois["receita"] - (100 + 120 + 140 + 80) * 1000.0) < 1e-6


def test_sem_look_ahead_documento_futuro_nao_altera_o_passado(base):
    corte = pd.Timestamp("2023-12-29")
    datas_ate = [d for d in DATAS if d <= corte]
    p_ate = pf.painel_ttm(base, datas_ate)
    extra = _doc(1000, CNPJ, 2024, 1, 1, "2024-05-10", _acum(999, 400, 200, 100, 150, 40, -90), BAL_B)
    p_depois = pf.painel_ttm(_tabela(DOCS + [extra]), DATAS)
    a = p_ate.reset_index(drop=True)
    b = p_depois[p_depois["data"] <= corte].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)
    # e o futuro de fato mudou (o teste nao e vazio): TTM em 06/2024 = 2T23 + 3T23 + 4T23 + 1T24,
    # com 2T = 220-100, 3T = 360-220 (reapresentado) e 4T = 500-360
    fim = p_depois[(p_depois["data"] == pd.Timestamp("2024-06-28")) & (p_depois["cd_cvm"] == 1000)]
    assert abs(fim.iloc[0]["receita"] - (120 + 140 + 140 + 999) * 1000.0) < 1e-6


def test_deslocar_usa_o_pregao_anterior(base):
    # a DFP de 2023 chega em 20/03/2024, que foi pregao: decidir em 20/03 com ela dentro
    # e look-ahead intradiario; com deslocar=True a decisao usa a visao de 19/03.
    d = [pd.Timestamp("2024-03-20")]
    com = pf.painel_ttm(base, d, deslocar=False)
    sem = pf.painel_ttm(base, d, deslocar=True)
    r_com = com[com["cd_cvm"] == 1000].iloc[0]
    r_sem = sem[sem["cd_cvm"] == 1000].iloc[0]
    assert r_com["vintage"] == pd.Timestamp("2024-03-20")
    assert r_sem["vintage"] == pd.Timestamp("2024-01-15")
    assert r_com["receita"] != r_sem["receita"]
    # a linha continua CARIMBADA com a data de decisao, nao com a vespera: quem junta por
    # data no chamador nao pode perder a linha em silencio
    assert r_sem["data"] == pd.Timestamp("2024-03-20")
    assert set(sem["data"]) == {pd.Timestamp("2024-03-20")}


# ─────────────────────────────────────────────────────────────
# Valor de mercado, cobertura e disco
# ─────────────────────────────────────────────────────────────
def test_valor_de_mercado_alimenta_bm_e_ev_ebit(base):
    vm = pd.DataFrame({"data": [pd.Timestamp("2024-06-28")], "cd_cvm": [1000],
                       "valor_mercado": [2_000_000.0]})
    painel = pf.painel_ttm(base, DATAS, valor_mercado=vm)
    r = painel[(painel["data"] == pd.Timestamp("2024-06-28")) & (painel["cd_cvm"] == 1000)].iloc[0]
    assert abs(r["bm"] - r["pl"] / 2_000_000.0) < 1e-12
    assert abs(r["ev_ebit"] - r["ebit"] / (2_000_000.0 + r["divida_liquida"])) < 1e-12
    assert abs(r["earnings_yield"] - r["lucro_liquido"] / 2_000_000.0) < 1e-12
    # sem valor de mercado as quatro colunas ficam NaN
    outra = painel[(painel["data"] == pd.Timestamp("2024-03-29")) & (painel["cd_cvm"] == 1000)].iloc[0]
    assert np.isnan(outra["bm"]) and np.isnan(outra["ev_ebit"]) and np.isnan(outra["fcf_yield"])


def test_cobertura_conta_o_que_falta(base):
    painel = pf.painel_ttm(base, DATAS)
    c = pf.cobertura(painel)
    assert c["linhas"] == len(painel) and 0.0 < c["ttm"] <= 1.0
    assert c["valor_mercado"] == 0.0                        # nenhum valor de mercado foi dado
    assert pf.cobertura(pd.DataFrame(columns=pf.COLUNAS))["linhas"] == 0


def test_gravar_e_carregar_parquet(base, tmp_path):
    painel = pf.painel_ttm(base, DATAS)
    caminho = str(tmp_path / "painel.parquet")
    pf.gravar(painel, caminho)
    lido = pf.carregar(caminho)
    assert list(lido.columns) == pf.COLUNAS
    pd.testing.assert_frame_equal(painel.reset_index(drop=True), lido.reset_index(drop=True))
    assert pf.carregar(str(tmp_path / "nao_existe.parquet")).empty


def test_entrada_vazia_mantem_o_esquema():
    vazio = pd.DataFrame(columns=cf.COLUNAS)
    assert pf.vintages(vazio) == {}
    assert list(pf.painel_ttm(vazio, DATAS).columns) == pf.COLUNAS
    assert len(pf.painel_ttm(vazio, DATAS)) == 0
    assert len(pf.resolver(pd.DataFrame(), DATAS)) == 0
    assert len(pf.painel_ttm(None, None)) == 0
