"""Fixtures no layout documentado do FCA (CSV ';' latin-1, cabecalho com acento).

O modulo e a unica fonte de numero de acoes do pacote, e o numero de acoes e a unica
porta de entrada do valor de mercado, que e a unica porta de entrada do sinal de valor.
Se o formato real divergir, o esperado e que o painel fique VAZIO e o sinal se desligue,
nunca que ele produza um numero errado em silencio - varios testes aqui checam isso.
"""
import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from quant.dados import capital_social as cs

CABECALHO = ("CNPJ_Companhia;Data_Referencia;Versao;Nome_Companhia;Codigo_CVM;Tipo_Capital;"
             "Valor_Capital;Quantidade_Acoes_Ordinarias;Quantidade_Acoes_Preferenciais;"
             "Quantidade_Total_Acoes\n")

LINHAS = [
    # empresa 1000: integralizado e autorizado no mesmo ano; o autorizado tem de ser ignorado
    "11.111.111/0001-11;2022-12-31;1;EMPRESA MIL;1000;Capital Integralizado;500000,00;1.000.000;0;1.000.000",
    "11.111.111/0001-11;2022-12-31;1;EMPRESA MIL;1000;Capital Autorizado;900000,00;9.000.000;0;9.000.000",
    "11.111.111/0001-11;2023-12-31;1;EMPRESA MIL;1000;Capital Integralizado;500000,00;1.200.000;0;1.200.000",
    # empresa 2000: so subscrito, com ON e PN e sem coluna total preenchida
    "22.222.222/0001-22;2023-12-31;1;EMPRESA DOIS MIL;2000;Capital Subscrito;800000,00;400.000;100.000;0",
    # lixo: sem data e com zero acoes
    ";;1;SEM DATA;3000;Capital Integralizado;1;10;0;10",
    "44.444.444/0001-44;2023-12-31;1;ZERADA;4000;Capital Integralizado;0;0;0;0",
]
CSV = (CABECALHO + "\n".join(LINHAS) + "\n").encode("latin-1")


def _zip(nome="fca_cia_aberta_capital_social_2023.csv", conteudo=CSV):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("fca_cia_aberta_2023.csv", b"indice qualquer")
        z.writestr(nome, conteudo)
    return buf.getvalue()


@pytest.fixture(scope="module")
def cap():
    return cs.ler_capital_social(CSV)


# ─────────────────────────────────────────────────────────────
# Leitura do CSV
# ─────────────────────────────────────────────────────────────
def test_le_quantidade_com_separador_de_milhar(cap):
    r = cap[(cap["cd_cvm"] == 1000) & (cap["data_ref"] == pd.Timestamp("2022-12-31"))].iloc[0]
    assert r["acoes_total"] == 1_000_000.0 and r["acoes_on"] == 1_000_000.0
    assert r["capital"] == 500_000.0 and r["fonte"] == "fca"


def test_capital_autorizado_nunca_entra(cap):
    linhas = cap[cap["cd_cvm"] == 1000]
    assert len(linhas) == 2                                  # 2022 e 2023, nenhuma autorizada
    assert not linhas["tipo"].str.lower().str.contains("autorizado").any()
    assert linhas["acoes_total"].max() == 1_200_000.0        # nao pegou os 9 milhoes


def test_total_ausente_vira_soma_das_classes(cap):
    r = cap[cap["cd_cvm"] == 2000].iloc[0]
    assert r["acoes_total"] == 400_000.0 + 100_000.0


def test_linha_sem_data_ou_com_zero_acoes_e_descartada(cap):
    assert 3000 not in set(cap["cd_cvm"].dropna())
    assert 4000 not in set(cap["cd_cvm"].dropna())


def test_disponivel_em_atrasa_a_data_de_referencia(cap):
    r = cap[(cap["cd_cvm"] == 1000) & (cap["data_ref"] == pd.Timestamp("2023-12-31"))].iloc[0]
    assert r["disponivel_em"] == pd.Timestamp("2023-12-31") + pd.Timedelta(days=cs.DIAS_ATRASO)


def test_rank_tipo_ordena_e_recusa_autorizado():
    assert cs.rank_tipo("Capital Integralizado") == 0
    assert cs.rank_tipo("Capital Subscrito") == 1
    assert cs.rank_tipo("Capital Emitido") == 2
    assert cs.rank_tipo("Capital Autorizado") is None
    assert cs.rank_tipo("qualquer outro") == len(cs.PRIORIDADE_TIPO)


def test_formato_desconhecido_devolve_vazio_e_nao_levanta():
    assert cs.ler_capital_social(b"nao e csv").empty
    assert cs.ler_capital_social(b"").empty
    sem_colunas = b"A;B;C\n1;2;3\n"
    out = cs.ler_capital_social(sem_colunas)
    assert out.empty and list(out.columns) == cs.COLUNAS


# ─────────────────────────────────────────────────────────────
# Point-in-time e valor de mercado
# ─────────────────────────────────────────────────────────────
def test_acoes_em_nao_enxerga_o_futuro(cap):
    disponivel = pd.Timestamp("2023-12-31") + pd.Timedelta(days=cs.DIAS_ATRASO)
    antes = cs.acoes_em(cap, [disponivel - pd.Timedelta(days=1)])
    depois = cs.acoes_em(cap, [disponivel])
    assert antes[antes["cd_cvm"] == 1000].iloc[0]["acoes_total"] == 1_000_000.0
    assert depois[depois["cd_cvm"] == 1000].iloc[0]["acoes_total"] == 1_200_000.0


def test_empresa_sem_registro_disponivel_nao_aparece(cap):
    cedo = cs.acoes_em(cap, [pd.Timestamp("2022-01-01")])
    assert len(cedo) == 0


def test_valor_mercado_multiplica_acoes_por_preco(cap):
    d = pd.Timestamp("2024-06-28")
    acoes = cs.acoes_em(cap, [d])
    precos = pd.DataFrame({"data": [d, d], "cd_cvm": [1000, 2000], "preco": [10.0, 4.0]})
    vm = cs.valor_mercado(acoes, precos)
    assert set(vm["cd_cvm"]) == {1000, 2000}
    assert vm[vm["cd_cvm"] == 1000].iloc[0]["valor_mercado"] == 1_200_000.0 * 10.0
    assert vm[vm["cd_cvm"] == 2000].iloc[0]["valor_mercado"] == 500_000.0 * 4.0


def test_valor_mercado_sem_preco_devolve_vazio_com_esquema(cap):
    vazio = cs.valor_mercado(cs.acoes_em(cap, [pd.Timestamp("2024-06-28")]), pd.DataFrame())
    assert len(vazio) == 0 and "valor_mercado" in vazio.columns


def test_estimativa_por_lpa_recusa_lpa_zero_e_sinal_trocado():
    painel = pd.DataFrame({
        "data": pd.to_datetime(["2024-06-28"] * 4),
        "cd_cvm": [1, 2, 3, 4],
        "lucro_liquido": [1000.0, 1000.0, -1000.0, 1000.0],
        "lpa": [2.0, 0.0, 2.0, -2.0],
        "dt_refer": pd.to_datetime(["2024-03-31"] * 4),
    })
    out = cs.estimar_por_lpa(painel)
    assert set(out["cd_cvm"]) == {1}                          # 2 tem LPA zero, 3 e 4 trocam de sinal
    assert out.iloc[0]["acoes_total"] == 1000.0 / 2.0
    assert out.iloc[0]["fonte"] == "lpa" and out.iloc[0]["disponivel_em"] == pd.Timestamp("2024-06-28")
    assert cs.estimar_por_lpa(pd.DataFrame()).empty


# ─────────────────────────────────────────────────────────────
# Zip e disco
# ─────────────────────────────────────────────────────────────
def test_extrai_o_csv_do_zip_por_nome_exato_e_por_substring():
    assert cs.extrair_csv(_zip(), 2023) == CSV
    assert cs.extrair_csv(_zip("outro_capital_social_2023.csv")) == CSV
    assert cs.extrair_csv(_zip("fca_cia_aberta_valor_mobiliario_2023.csv")) is None
    assert cs.extrair_csv(b"nao e zip") is None


def test_baixar_sem_rede_devolve_none(monkeypatch, tmp_path):
    monkeypatch.setattr(cs, "http_get", lambda *a, **k: None)
    monkeypatch.setattr(cs.identidade, "caminho_fca", lambda ano: str(tmp_path / f"fca_{ano}.zip"))
    assert cs.baixar(2023) is None


def test_gravar_e_carregar_parquet(cap, tmp_path):
    caminho = str(tmp_path / "capital.parquet")
    cs.gravar(cap, caminho)
    lido = cs.carregar(caminho)
    assert list(lido.columns) == cs.COLUNAS and len(lido) == len(cap)
    assert cs.carregar(str(tmp_path / "nao_existe.parquet")).empty
