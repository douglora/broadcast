import io
import zipfile
from datetime import date

import pandas as pd

from quant.dados import cotahist as ch
from quant.dados import identidade as idn


# ─────────────────────────────────────────────────────────────
# Fixtures sinteticas no layout documentado (';', latin-1, datas AAAA-MM-DD)
# ─────────────────────────────────────────────────────────────
FCA_CSV = (
    "CNPJ_Companhia;Data_Referencia;Versao;ID_Documento;Valor_Mobiliario;Sigla_Classe_Acao_Preferencial;"
    "Classe_Acao_Preferencial;Codigo_Negociacao;Composicao_BDR_Unit;Mercado;Sigla_Entidade_Administradora;"
    "Entidade_Administradora;Data_Inicio_Negociacao;Data_Fim_Negociacao;Segmento\n"
    "33.000.167/0001-01;2023-12-31;1;1001;Ações Ordinárias;;;PETR3;;Bolsa;BVMF;B3 S.A.;2000-08-09;;Nível 2\n"
    "33.000.167/0001-01;2023-12-31;1;1001;Ações Preferenciais;;;PETR4;;Bolsa;BVMF;B3 S.A.;2000-08-09;;Nível 2\n"
    "33.000.167/0001-01;2024-12-31;2;1002;Ações Preferenciais;;;PETR4;;Bolsa;BVMF;B3 S.A.;2000-08-09;;Nível 2\n"
    "11.111.111/0001-11;2019-12-31;1;2001;Ações Ordinárias;;;XPTO3;;Bolsa;BVMF;B3 S.A.;2015-03-02;2020-06-30;Novo Mercado\n"
    "22.222.222/0001-22;2023-12-31;1;3001;Ações Ordinárias;;;XPTO3;;Bolsa;BVMF;B3 S.A.;2021-01-04;;Novo Mercado\n"
    "02.916.265/0001-60;2024-12-31;1;4001;Ações Ordinárias;;;JBSS3;;Bolsa;BVMF;B3 S.A.;2007-03-29;;Novo Mercado\n"
    "33.000.167/0001-01;2023-12-31;1;1001;Debêntures;;;;;Balcão Organizado;;;;;\n"
)

CAD_CSV = (
    "CNPJ_CIA;DENOM_SOCIAL;DENOM_COMERC;DT_REG;DT_CONST;DT_CANCEL;MOTIVO_CANCEL;SIT;DT_INI_SIT;CD_CVM;SETOR_ATIV\n"
    "33.000.167/0001-01;PETROLEO BRASILEIRO S.A. PETROBRAS;PETROBRAS;1977-07-20;1953-10-03;;;ATIVO;1977-07-20;9512;Petróleo e Gás\n"
    "11.111.111/0001-11;XPTO ANTIGA S.A.;XPTO;2015-01-10;2010-01-01;2020-07-15;Incorporação;CANCELADA;2020-07-15;11111;Comércio\n"
    "22.222.222/0001-22;XPTO NOVA S.A.;XPTO;2020-12-01;2018-01-01;;;ATIVO;2020-12-01;22222;Serviços\n"
    "02.916.265/0001-60;JBS S.A.;JBS;2007-03-15;1953-01-01;;;ATIVO;2007-03-15;20575;Alimentos\n"
    "02.916.265/0001-60;JBS S.A.;JBS;2007-03-15;1953-01-01;;;SUSPENSO;2006-01-01;20575;Alimentos\n"
)


def _linha(**kw):
    base = dict(tipreg="01", data="20241227", codbdi="02", ticker="PETR4", tpmerc="010",
                nome="PETROBRAS", especi="PN      N2", prazot="", moeda="R$",
                abe="3550", max="3570", min="3540", med="3555", fec="3566", bid="3565", ask="3567",
                negocios="12345", qtd="100000", volume="355500000", preexe="0", indopc="0",
                datven="99991231", fatcot="1", ptoexe="0", isin="BRPETRACNPR6", dismes="103")
    base.update(kw)
    return ch.montar_registro(base)


def _cotahist():
    linhas = []
    for d in ("20200102", "20200601", "20200630"):
        linhas.append(_linha(data=d, ticker="XPTO3", isin="BRXPTOACNOR1", nome="XPTO ANTIGA"))
    for d in ("20210104", "20210601", "20241227"):
        linhas.append(_linha(data=d, ticker="XPTO3", isin="BRXPTNACNOR9", nome="XPTO NOVA"))
    for d in ("20200102", "20241227"):
        linhas.append(_linha(data=d, ticker="PETR4"))
        linhas.append(_linha(data=d, ticker="JBSS3", isin="BRJBSSACNOR8"))
    linhas.append(_linha(data="20050103", ticker="VELH3", isin="BRVELHACNOR0", nome="VELHA S.A."))
    linhas.append(_linha(data="20080103", ticker="VELH3", isin="BRVELHACNOR0", nome="VELHA S.A."))
    return ch.parse("\n".join(linhas))


def _identidade():
    return idn.montar_identidade(idn.ler_fca_valor_mobiliario(FCA_CSV.encode("latin-1")),
                                 idn.ler_cadastro(CAD_CSV.encode("latin-1")), _cotahist())


# ─────────────────────────────────────────────────────────────
# Parsers
# ─────────────────────────────────────────────────────────────
def test_ler_fca_tolerante_a_nomes_e_descarta_sem_ticker():
    fca = idn.ler_fca_valor_mobiliario(FCA_CSV.encode("latin-1"))
    assert set(fca["ticker"]) == {"PETR3", "PETR4", "XPTO3", "JBSS3"}      # debenture sem codigo cai
    assert (fca["cnpj"].str.len() == 14).all() and fca["cnpj"].iloc[0] == "33000167000101"
    r = fca[(fca["ticker"] == "XPTO3") & (fca["cnpj"] == "11111111000111")].iloc[0]
    assert r["data_ini"] == pd.Timestamp("2015-03-02") and r["data_fim"] == pd.Timestamp("2020-06-30")
    # nomes de coluna diferentes (case, sem acento) tambem funcionam
    alt = FCA_CSV.replace("CNPJ_Companhia", "cnpj_companhia").replace("Codigo_Negociacao", "CODIGO NEGOCIAÇÃO")
    assert len(idn.ler_fca_valor_mobiliario(alt.encode("latin-1"))) == len(fca)


def test_ler_cadastro_uma_linha_por_cnpj_preferindo_ativo():
    cad = idn.ler_cadastro(CAD_CSV.encode("latin-1"))
    assert cad["cnpj"].is_unique and len(cad) == 4
    jbs = cad[cad["cnpj"] == "02916265000160"].iloc[0]
    assert jbs["situacao"] == "ATIVO" and jbs["cd_cvm"] == 20575
    assert cad[cad["cnpj"] == "33000167000101"].iloc[0]["denominacao"].startswith("PETROLEO")


def test_extrair_valor_mobiliario_do_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("fca_cia_aberta_geral_2024.csv", "CNPJ_Companhia;Nome\n1;a\n")
        z.writestr("fca_cia_aberta_valor_mobiliario_2024.csv", FCA_CSV.encode("latin-1"))
    csv = idn.extrair_valor_mobiliario(buf.getvalue(), 2024)
    assert csv is not None and csv.startswith(b"CNPJ_Companhia")
    assert idn.extrair_valor_mobiliario(b"nao e zip") is None


def test_data_cvm_aceita_iso_e_br():
    assert idn.data_cvm("2023-04-27") == pd.Timestamp("2023-04-27")
    assert idn.data_cvm("27/04/2023") == pd.Timestamp("2023-04-27")
    assert pd.isna(idn.data_cvm("")) and pd.isna(idn.data_cvm(None))


# ─────────────────────────────────────────────────────────────
# mapa_isin e montagem
# ─────────────────────────────────────────────────────────────
def test_mapa_isin_separa_trechos_quando_o_isin_muda():
    m = idn.mapa_isin(_cotahist())
    x = m[m["ticker"] == "XPTO3"].reset_index(drop=True)
    assert len(x) == 2
    assert x.loc[0, "isin"] == "BRXPTOACNOR1" and x.loc[0, "data_fim"] == pd.Timestamp("2020-06-30")
    assert not x.loc[0, "aberto"]
    assert x.loc[1, "isin"] == "BRXPTNACNOR9" and x.loc[1, "data_ini"] == pd.Timestamp("2021-01-04")
    assert x.loc[1, "aberto"]
    v = m[m["ticker"] == "VELH3"].iloc[0]
    assert not v["aberto"] and v["data_fim"] == pd.Timestamp("2008-01-03")   # morreu: ultimo trecho mas antigo


def test_montar_identidade_colunas_e_juncao():
    ident = _identidade()
    assert list(ident.columns) == idn.COLUNAS
    p4 = ident[ident["ticker"] == "PETR4"].iloc[0]
    assert p4["isin"] == "BRPETRACNPR6" and p4["cnpj"] == "33000167000101" and p4["cd_cvm"] == 9512
    assert p4["denominacao"].startswith("PETROLEO") and p4["fonte"] == "fca+cotahist"
    assert pd.isna(p4["data_fim"])
    p3 = ident[ident["ticker"] == "PETR3"].iloc[0]           # no FCA mas sem cotacao na amostra
    assert p3["fonte"] == "fca" and p3["isin"] is None
    velha = ident[ident["ticker"] == "VELH3"].iloc[0]         # so no COTAHIST (pre-FCA)
    assert velha["fonte"] == "cotahist" and velha["cnpj"] == "" and velha["data_fim"] == pd.Timestamp("2008-01-03")


def test_point_in_time_ticker_reutilizado_por_outra_empresa():
    ident = _identidade()
    antes = idn.resolver(ident, "XPTO3", "2020-03-01")
    depois = idn.resolver(ident, "XPTO3", date(2021, 3, 1))
    assert antes["cnpj"] == "11111111000111" and antes["isin"] == "BRXPTOACNOR1"
    assert depois["cnpj"] == "22222222000122" and depois["isin"] == "BRXPTNACNOR9"
    assert idn.resolver(ident, "XPTO3", "2020-09-01") is None          # entre as vigencias: ninguem
    assert idn.resolver(ident, "XPTO3", "2014-01-01") is None          # antes de existir
    assert idn.empresa_de(ident, "XPTO3", "2020-03-01") != idn.empresa_de(ident, "XPTO3", "2021-03-01")
    assert idn.empresa_de(ident, "VELH3", "2006-01-01") == "BRVELH"    # sem CNPJ: emissor do ISIN
    assert idn.empresa_de(ident, "VELH3", "2009-01-01") is None


def test_overrides_fecham_vigencia_como_dados():
    ident = _identidade()
    assert idn.resolver(ident, "JBSS3", "2025-06-06")["fonte"].endswith("+override")
    assert idn.resolver(ident, "JBSS3", "2025-06-09") is None
    assert idn.OVERRIDES["JBSS3"]["data_fim"] == "2025-06-06"
    assert idn.OVERRIDES["BRFS3"]["sucessor"] == "MBRF3" and idn.OVERRIDES["MRFG3"]["sucessor"] == "MBRF3"
    assert idn.OVERRIDES["STBP3"]["data_fim"] == "2025-10-03"
    # override nunca reabre: uma vigencia fechada antes segue fechada
    sem = idn.montar_identidade(idn.ler_fca_valor_mobiliario(FCA_CSV.encode("latin-1")),
                                idn.ler_cadastro(CAD_CSV.encode("latin-1")), _cotahist(), overrides={})
    assert idn.resolver(sem, "JBSS3", "2025-06-09") is not None
    assert idn.resolver(idn.aplicar_overrides(sem, {"XPTO3": {"data_fim": "2030-01-01"}}), "XPTO3", "2020-09-01") is None


def test_montar_identidade_sem_cotahist_e_vazio():
    fca = idn.ler_fca_valor_mobiliario(FCA_CSV.encode("latin-1"))
    cad = idn.ler_cadastro(CAD_CSV.encode("latin-1"))
    ident = idn.montar_identidade(fca, cad, None)
    assert set(ident["fonte"].str.replace("+override", "")) == {"fca"}
    assert idn.resolver(ident, "PETR4", "2024-01-01")["cd_cvm"] == 9512
    vazio = idn.montar_identidade(None, None, None)
    assert list(vazio.columns) == idn.COLUNAS and len(vazio) == 0
    assert idn.resolver(vazio, "PETR4", "2024-01-01") is None


def test_gravar_e_carregar_parquet(tmp_path):
    ident = _identidade()
    caminho = str(tmp_path / "identidade.parquet")
    idn.gravar_identidade(ident, caminho)
    lido = idn.carregar_identidade(caminho)
    assert len(lido) == len(ident) and idn.resolver(lido, "PETR4", "2024-01-01")["isin"] == "BRPETRACNPR6"


# ─────────────────────────────────────────────────────────────
# classificar_papel
# ─────────────────────────────────────────────────────────────
def test_classificar_papel():
    assert idn.classificar_papel("PETR4", "BRPETRACNPR6") == "acao"
    assert idn.classificar_papel("B3SA3") == "acao"
    assert idn.classificar_papel("AAPL34", "BRAAPLBDR004") == "bdr"
    assert idn.classificar_papel("M1TA34") == "bdr"
    assert idn.classificar_papel("SANB11", "BRSANBCDAM13", "02") == "unit"
    assert idn.classificar_papel("TAEE11") == "unit"
    assert idn.classificar_papel("BOVA11", "BRBOVACTF003", "02") == "etf"
    assert idn.classificar_papel("HGLG11", "BRHGLGCTF003", "12") == "fii"
    assert idn.classificar_papel("HGLG11", "BRHGLGCTF003", 12) == "fii"
    assert idn.classificar_papel("VALE1", None, "10") == "direito"
    assert idn.classificar_papel("PETR2") == "direito"
    assert idn.classificar_papel("PETRA100") == "outro"
    assert idn.classificar_papel("") == "outro"


def test_fca_sem_data_fim_de_deslistada_nao_captura_ticker_reutilizado():
    """Empresa deslistada para de entregar FCA e a ultima versao fica com Data_Fim VAZIA.
    Sem esta regra, a XPTO ANTIGA (cnpj 111...) ficaria vigente para sempre e casaria com o
    ISIN da XPTO NOVA a partir de 2021 (duas empresas para o mesmo ticker/ISIN/data)."""
    fca_txt = FCA_CSV.replace("2015-03-02;2020-06-30", "2015-03-02;")          # Data_Fim vazia
    fca = idn.ler_fca_valor_mobiliario(fca_txt.encode("latin-1"))
    assert pd.isna(fca[(fca["ticker"] == "XPTO3") & (fca["cnpj"] == "11111111000111")].iloc[0]["data_fim"])
    # (a) com DT_CANCEL no cadastro: fecha no cancelamento (2020-07-15)
    ident = idn.montar_identidade(fca, idn.ler_cadastro(CAD_CSV.encode("latin-1")), _cotahist())
    x = ident[ident["ticker"] == "XPTO3"]
    assert len(x) == 2 and x["cnpj"].tolist() == ["11111111000111", "22222222000122"]
    assert idn.resolver(ident, "XPTO3", "2021-03-01")["cnpj"] == "22222222000122"
    assert idn.resolver(ident, "XPTO3", "2020-03-01")["cnpj"] == "11111111000111"
    assert idn.resolver(ident, "XPTO3", "2020-12-01") is None
    # (b) sem DT_CANCEL: dois CNPJs nunca dividem um ticker -> a antiga fecha na vespera da nova
    cad_txt = CAD_CSV.replace("2020-07-15;Incorporação;CANCELADA", ";;CANCELADA")
    ident = idn.montar_identidade(fca, idn.ler_cadastro(cad_txt.encode("latin-1")), _cotahist())
    x = ident[ident["ticker"] == "XPTO3"]
    assert len(x) == 2 and idn.resolver(ident, "XPTO3", "2021-03-01")["cnpj"] == "22222222000122"
    # sem COTAHIST a vigencia do FCA antigo termina em 2021-01-03
    so_fca = idn.montar_identidade(fca, idn.ler_cadastro(cad_txt.encode("latin-1")), None)
    assert idn.resolver(so_fca, "XPTO3", "2021-01-03")["cnpj"] == "11111111000111"
    assert idn.resolver(so_fca, "XPTO3", "2021-01-04")["cnpj"] == "22222222000122"
    # a regra so encurta: uma vigencia ja fechada antes nao e mexida
    ident = _identidade()
    assert ident[(ident["ticker"] == "XPTO3") & (ident["cnpj"] == "11111111000111")].iloc[0]["data_fim"] == pd.Timestamp("2020-06-30")
