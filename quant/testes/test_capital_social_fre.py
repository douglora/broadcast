"""Numero de acoes antes de 2020: FRE da CVM; mesclagem que nao apaga historia; painel completo com valor de mercado.

O ITR/DFP so traz a composicao do capital de 2020 em diante. Antes disso o sinal de valor nao existia.
O FRE cobre 2010 em diante, em UNIDADES e com a data de recebimento de cada versao.
"""
import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from quant.dados import capital_social as cs
from quant.dados import painel_fundamentos as pf

GERAL = ("CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;CATEG_DOC;ID_DOC;DT_RECEB;LINK_DOC\n"
         "11.111.111/0001-11;2013-01-01;1;EMPRESA MIL;001000;FRE;100;2013-06-10;http://x\n"
         "11.111.111/0001-11;2013-01-01;2;EMPRESA MIL;001000;FRE;101;2013-11-20;http://x\n"
         "22.222.222/0001-22;2013-01-01;1;EMPRESA DOIS MIL;002000;FRE;200;2013-07-05;http://x\n"
         "33.333.333/0001-33;2013-01-01;1;SO AUTORIZADO;003000;FRE;300;2013-07-05;http://x\n")
CAPITAL = ("CNPJ_Companhia;Data_Referencia;Versao;ID_Documento;Nome_Companhia;ID_Capital_Social;Tipo_Capital;"
           "Data_Autorizacao_Aprovacao;Valor_Capital;Prazo_Integralizacao;Quantidade_Acoes_Ordinarias;"
           "Quantidade_Acoes_Preferenciais;Quantidade_Total_Acoes\n"
           "11.111.111/0001-11;2013-01-01;1;100;EMPRESA MIL;1;Capital Emitido;2013-01-10;1000.00;;900000;0;900000\n"
           "11.111.111/0001-11;2013-01-01;1;100;EMPRESA MIL;2;Capital Integralizado;2013-01-10;1000.00;;1000000;0;1000000\n"
           "11.111.111/0001-11;2013-01-01;1;100;EMPRESA MIL;3;Capital Autorizado;2013-01-10;9000.00;;9000000;0;9000000\n"
           "11.111.111/0001-11;2013-01-01;2;101;EMPRESA MIL;4;Capital Integralizado;2013-10-30;1200.00;;1200000;0;1200000\n"
           "22.222.222/0001-22;2013-01-01;1;200;EMPRESA DOIS MIL;5;Capital Subscrito;2013-02-01;800.00;;400000;100000;0\n"
           "33.333.333/0001-33;2013-01-01;1;300;SO AUTORIZADO;6;Capital Autorizado;2013-02-01;800.00;;5000;0;5000\n")


def _zip(ano=2013, geral=GERAL, capital=CAPITAL):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"fre_cia_aberta_{ano}.csv", geral.encode("latin-1"))
        z.writestr(f"fre_cia_aberta_capital_social_{ano}.csv", capital.encode("latin-1"))
    return buf.getvalue()


@pytest.fixture(scope="module")
def fre():
    return cs.ler_fre(_zip(), 2013)


# ─────────────────────────────────────────────────────────────
# Leitura do FRE
# ─────────────────────────────────────────────────────────────
def test_uma_linha_por_documento_com_o_melhor_tipo(fre):
    e = fre[fre["cd_cvm"] == 1000].sort_values("versao")
    assert e["acoes_total"].tolist() == [1_000_000.0, 1_200_000.0]       # integralizado vence emitido; autorizado nunca
    assert (e["fonte"] == "fre").all() and e["tipo"].iloc[0] == "Capital Integralizado"


def test_carimbo_point_in_time_e_a_data_de_recebimento_da_versao(fre):
    e = fre[fre["cd_cvm"] == 1000].sort_values("versao")
    assert e["disponivel_em"].tolist() == [pd.Timestamp("2013-06-10"), pd.Timestamp("2013-11-20")]
    ac = cs.acoes_em(fre, [pd.Timestamp("2013-06-09"), pd.Timestamp("2013-06-10"), pd.Timestamp("2013-12-01")], cd_cvms=[1000])
    assert ac["acoes_total"].tolist() == [1_000_000.0, 1_200_000.0]       # antes de 10/06 nao havia numero nenhum


def test_total_ausente_soma_as_classes(fre):
    assert fre[fre["cd_cvm"] == 2000]["acoes_total"].iloc[0] == 500_000.0


def test_so_capital_autorizado_nao_gera_linha(fre):
    assert 3000 not in set(fre["cd_cvm"].astype(int))


def test_zip_sem_os_arquivos_do_fre_devolve_vazio():
    assert len(cs.ler_fre(b"nao e zip", 2013)) == 0
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("outro.csv", b"a;b\n1;2\n")
    assert len(cs.ler_fre(buf.getvalue(), 2013)) == 0


# ─────────────────────────────────────────────────────────────
# Combinacao, mesclagem e escala
# ─────────────────────────────────────────────────────────────
def _linha(cd, data_ref, disp, total, fonte, versao=1):
    return {"cd_cvm": cd, "cnpj": "", "data_ref": pd.Timestamp(data_ref), "disponivel_em": pd.Timestamp(disp),
            "versao": versao, "tipo": "x", "acoes_on": np.nan, "acoes_pn": np.nan, "acoes_total": total,
            "capital": np.nan, "fonte": fonte}


def test_fre_so_entra_antes_do_corte_de_2020():
    fre = pd.DataFrame([_linha(1, "2018-01-01", "2018-06-01", 100.0, "fre"),
                        _linha(1, "2020-01-01", "2020-06-01", 999.0, "fre")])
    comp = pd.DataFrame([_linha(1, "2020-03-31", "2020-05-10", 110.0, "itr")])
    t = cs.combinar(comp, fre)
    assert sorted(t["fonte"].tolist()) == ["fre", "itr"]
    assert 999.0 not in t["acoes_total"].tolist()


def test_combinar_nao_depende_dos_anos_pedidos():
    """Pedir so os ultimos anos (a rotina diaria) nao acrescenta linha de FRE nenhuma."""
    comp = pd.DataFrame([_linha(1, "2024-03-31", "2024-05-10", 110.0, "itr")])
    assert cs.combinar(comp, cs._vazio()).equals(comp.sort_values(["cd_cvm", "data_ref", "versao"]).reset_index(drop=True))


def test_mesclar_preserva_a_historia_que_a_nova_carga_nao_trouxe():
    antigo = pd.DataFrame([_linha(1, "2015-01-01", "2015-06-01", 100.0, "fre"),
                           _linha(1, "2024-03-31", "2024-05-10", 110.0, "itr")])
    novo = pd.DataFrame([_linha(1, "2024-03-31", "2024-05-10", 111.0, "itr"),
                         _linha(1, "2024-06-30", "2024-08-10", 112.0, "itr")])
    t = cs.mesclar(antigo, novo)
    assert sorted(t["acoes_total"].tolist()) == [100.0, 111.0, 112.0]      # historia mantida; chave igual vale a nova
    assert len(cs.mesclar(None, novo)) == 2 and len(cs.mesclar(antigo, cs._vazio())) == 2


def test_linhas_do_fre_nunca_sao_multiplicadas_por_mil():
    """Uma companhia em milhares no ITR (decisao x1000) tem o FRE de antes de 2020 em unidades."""
    cap = pd.DataFrame([_linha(1, "2018-01-01", "2018-06-01", 4_255_763_000.0, "fre"),
                        _linha(1, "2024-03-31", "2024-05-10", 4_255_763.0, "itr")])
    painel = pd.DataFrame({"data": [pd.Timestamp("2024-06-30")], "cd_cvm": [1],
                           "lucro_liquido": [4_255_763_000.0], "lpa": [1.0]})
    r = cs.resolver_escala(cap, painel=painel)
    fre = r[r["fonte"].str.startswith("fre")].iloc[0]
    itr = r[r["fonte"].str.startswith("itr")].iloc[0]
    assert fre["acoes_total"] == 4_255_763_000.0 and fre["fonte"] == "fre:u"
    assert itr["acoes_total"] == 4_255_763_000.0 and itr["fonte"].startswith("itr:")


def test_companhia_so_com_fre_nao_vira_sem_decisao():
    cap = pd.DataFrame([_linha(7, "2014-01-01", "2014-06-01", 500_000.0, "fre")])
    r = cs.resolver_escala(cap)
    assert r["fonte"].iloc[0] == "fre:u" and r["acoes_total"].iloc[0] == 500_000.0


def test_main_grava_mesclando_e_nao_apaga_o_que_ja_estava(monkeypatch, tmp_path):
    arq = str(tmp_path / "capital_social.parquet")
    antigo = pd.DataFrame([_linha(1, "2015-01-01", "2015-06-01", 100.0, "fre"),
                           _linha(1, "2024-03-31", "2024-05-10", 110.0, "itr")])
    antigo.to_parquet(arq, index=False)
    monkeypatch.setattr(cs, "ARQ_PARQUET", arq)
    monkeypatch.setattr(cs, "carregar", lambda caminho=arq: pd.read_parquet(caminho))
    monkeypatch.setattr(cs, "gravar", lambda df, caminho=arq: df[cs.COLUNAS].to_parquet(caminho, index=False))
    monkeypatch.setattr(cs, "atualizar_de_demonstracoes",
                        lambda anos, tipos=("DFP", "ITR"), salvar=True:
                        pd.DataFrame([_linha(1, "2025-03-31", "2025-05-10", 120.0, "itr")]))
    chamadas = []
    monkeypatch.setattr(cs, "atualizar_de_fre", lambda anos, baixar=True: chamadas.append(list(anos)) or cs._vazio())
    assert cs.main(["--anos", "2024-2026"]) == 0
    t = pd.read_parquet(arq)
    assert sorted(t["acoes_total"].tolist()) == [100.0, 110.0, 120.0]        # a historia de 2015 sobreviveu
    assert chamadas == [[]]                                                  # rotina diaria: nenhum download de FRE


# ─────────────────────────────────────────────────────────────
# Painel completo: valor de mercado ligado
# ─────────────────────────────────────────────────────────────
def test_painel_ttm_aceita_funcao_de_valor_de_mercado():
    from quant.testes.test_painel_fundamentos import DATAS, _tabela
    df = _tabela()
    sem = pf.painel_ttm(df, DATAS)
    assert sem["valor_mercado"].isna().all()
    chamadas = []

    def vm(base):
        chamadas.append(len(base))
        return pd.DataFrame({"data": base["data"], "cd_cvm": base["cd_cvm"], "valor_mercado": 2_000_000.0})
    com = pf.painel_ttm(df, DATAS, valor_mercado=vm)
    assert chamadas and (com.dropna(subset=["valor_mercado"])["valor_mercado"] == 2_000_000.0).all()
    r = com[(com["data"] == pd.Timestamp("2024-06-28")) & (com["cd_cvm"] == 1000)].iloc[0]
    assert abs(r["bm"] - r["pl"] / 2_000_000.0) < 1e-12


def test_main_do_painel_completo_liga_o_valor_de_mercado(monkeypatch, tmp_path):
    """O `main` do painel completo passava valor_mercado=None: o sinal de valor nascia desligado."""
    from quant.testes.test_painel_fundamentos import _tabela
    capturado = {}

    def falso_painel_ttm(df, datas, **kw):
        capturado.update(kw)
        return pd.DataFrame(columns=pf.COLUNAS)
    monkeypatch.setattr(pf.cf, "carregar", lambda anos, **k: _tabela())
    monkeypatch.setattr(pf, "painel_ttm", falso_painel_ttm)
    monkeypatch.setattr(pf, "gravar", lambda painel, caminho=None: str(tmp_path / "p.parquet"))
    monkeypatch.setattr(pf, "datas_de_decisao", lambda ini, fim, hoje=None: [pd.Timestamp("2022-12-30")])
    pf.main(["--anos", "2022-2023", "--ini", "2022", "--fim", "2023"])
    assert callable(capturado.get("valor_mercado")) and capturado["valor_mercado"] is pf.valor_de_mercado
    assert capturado.get("deslocar") is True


def test_valor_de_mercado_aceita_capital_proprio():
    import inspect
    assert inspect.signature(pf.valor_de_mercado).parameters["capital"].default is None


# ─────────────────────────────────────────────────────────────
# Escala por linha (companhia que mudou de milhares para unidades, ou o contrario)
# ─────────────────────────────────────────────────────────────
def _vm(linhas):
    return pd.DataFrame([{"data": pd.Timestamp(d), "cd_cvm": c, "valor_mercado": v, "acoes_total": v / 10.0,
                          "preco": 10.0, "fonte": "itr:u"} for d, c, v in linhas])


def _pl(linhas):
    return pd.DataFrame([{"data": pd.Timestamp(d), "cd_cvm": c, "pl": v} for d, c, v in linhas])


def test_escala_mil_vezes_menor_ou_maior_e_corrigida_so_quando_o_pvp_volta_ao_plausivel():
    vm = _vm([("2021-06-30", 1, 6.5e6),      # PL 1,05 bi: P/VP 0,006 -> x1000 = 6,2: corrige
              ("2021-06-30", 2, 2.4e12),     # PL 1,58 bi: P/VP 1.500 -> /1000 = 1,5: corrige
              ("2021-06-30", 3, 3.0e9),      # P/VP 3: plausivel, nao mexe
              ("2021-06-30", 4, 2.0e6)])     # P/VP 0,0004 e x1000 = 0,4... mas veja o PL abaixo
    painel = _pl([("2021-06-30", 1, 1.05e9), ("2021-06-30", 2, 1.58e9), ("2021-06-30", 3, 1.0e9), ("2021-06-30", 4, 5.0e12)])
    out, n = cs.corrigir_escala_por_linha(vm, painel)
    v = out.set_index("cd_cvm")["valor_mercado"]
    assert n == 2
    assert abs(v[1] - 6.5e9) < 1 and abs(v[2] - 2.4e9) < 1 and v[3] == 3.0e9
    assert v[4] == 2.0e6                      # P/VP de 0,0000004: nem x1000 resolve; nao se inventa
    assert abs(out.set_index("cd_cvm")["acoes_total"][1] - 6.5e8) < 1       # as acoes andam junto


def test_pl_ausente_ou_negativo_nao_decide():
    vm = _vm([("2021-06-30", 1, 6.5e6), ("2021-06-30", 2, 6.5e6), ("2021-06-30", 3, 6.5e6)])
    painel = _pl([("2021-06-30", 1, -1.0e9), ("2021-06-30", 2, np.nan)])
    out, n = cs.corrigir_escala_por_linha(vm, painel)
    assert n == 0 and out["valor_mercado"].tolist() == [6.5e6] * 3


def test_pvp_genuinamente_extremo_nao_e_mexido():
    vm = _vm([("2021-06-30", 1, 5.0e9), ("2021-06-30", 2, 5.0e7)])        # P/VP 50 e 0,05: extremos, mas nao erro de mil vezes
    painel = _pl([("2021-06-30", 1, 1.0e8), ("2021-06-30", 2, 1.0e9)])
    out, n = cs.corrigir_escala_por_linha(vm, painel)
    assert n == 0


def test_entradas_vazias_nao_quebram():
    assert cs.corrigir_escala_por_linha(None, None) == (None, 0)
    v = _vm([("2021-06-30", 1, 1.0e9)])
    assert cs.corrigir_escala_por_linha(v, pd.DataFrame())[1] == 0
