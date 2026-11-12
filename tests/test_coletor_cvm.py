"""De quem e o ticker: o coletor escolhe a companhia da CVM pelo Formulario Cadastral (FCA),
onde a propria empresa declara os codigos de negociacao, e so cai no casamento por nome quando
o cadastro nao traz o ticker.

Nasceu do erro de 11/11/2026: CMIG4 saiu com o balanco da Cemig Distribuicao (controlada com
registro proprio na CVM) no lugar da Cemig holding, e o BDR do Nubank (ROXO34) com o da Alfa
Holdings. Tudo sem rede: o IPE e o cadastro sao linhas de brinquedo.
"""
import io
import os
import sys
import zipfile

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

try:
    import coletar_dados as CD
except Exception as e:          # ambiente sem as dependencias do coletor (yfinance, flask)
    pytest.skip(f"coletar_dados nao importa aqui: {type(e).__name__}", allow_module_level=True)

HOLDING, DISTRIB, GT = "17.155.730/0001-64", "06.981.180/0001-16", "06.981.176/0001-58"
NOMES_CEMIG = ["Companhia Energética de Minas Gerais - CEMIG", "CEMIG PN N1", "CEMIG"]


def _ipe(cnpj, nome, codigo, n=1, categoria="Fato Relevante"):
    return [{"CNPJ_Companhia": cnpj, "Nome_Companhia": nome, "Codigo_CVM": codigo, "Categoria": categoria,
             "Tipo": "", "Assunto": f"doc {i}", "Data_Entrega": f"2026-0{1 + i % 9}-15",
             "Link_Download": f"https://www.rad.cvm.gov.br/doc{codigo}_{i}"} for i in range(n)]


def _papel(cnpj, nome, ticker, fim="", ref="2026-01-01", versao="1"):
    return {"CNPJ_Companhia": cnpj, "Data_Referencia": ref, "Versao": versao, "Nome_Empresarial": nome,
            "Codigo_Negociacao": ticker, "Data_Fim_Negociacao": fim}


def _geral(*fichas):
    return {CD.so_digitos(cnpj): {"codigo_cvm": cod, "nome": nome} for cnpj, cod, nome in fichas}


IPE_CEMIG = (_ipe(HOLDING, "CIA ENERG MINAS GERAIS - CEMIG", "2453", n=3)
             + _ipe(DISTRIB, "CEMIG DISTRIBUIÇÃO S/A", "20303", n=9)
             + _ipe(GT, "CEMIG GERAÇÃO E TRANSMISSÃO S/A", "20320", n=5))
FCA_CEMIG = {"papeis": [_papel(HOLDING, "CIA ENERGETICA DE MINAS GERAIS - CEMIG", "CMIG4", versao="2"),
                        _papel(HOLDING, "CIA ENERGETICA DE MINAS GERAIS - CEMIG", "CMIG3", versao="2"),
                        _papel(DISTRIB, "CEMIG DISTRIBUICAO S.A.", "")],
             "geral": _geral((HOLDING, "2453", "CIA ENERGETICA DE MINAS GERAIS - CEMIG"),
                             (DISTRIB, "20303", "CEMIG DISTRIBUICAO S.A."))}
VAZIO = {"papeis": [], "geral": {}}


@pytest.fixture
def cvm(monkeypatch):
    """Liga o coletor a um IPE e a um cadastro de brinquedo: cvm(ipe, fca_do_ano, fca_do_ano_anterior)."""
    monkeypatch.setattr(CD.app, "log", lambda *a, **k: None)

    def ligar(ipe, fca=VAZIO, fca_anterior=VAZIO):
        ano = CD.datetime.now(CD.timezone.utc).year
        monkeypatch.setattr(CD, "_linhas_ipe", lambda a: ipe if a == ano else [])
        monkeypatch.setattr(CD, "_fca", lambda a: fca if a == ano else (fca_anterior if a == ano - 1 else VAZIO))
    return ligar


def test_holding_e_escolhida_pelo_cadastro_e_nao_a_controlada(cvm):
    cvm(IPE_CEMIG, FCA_CEMIG)
    fontes = {}
    r = CD.coletar_cvm("CMIG4", NOMES_CEMIG, fontes)
    assert r["empresa_escolhida"] == "CIA ENERG MINAS GERAIS - CEMIG"
    assert r["codigo_cvm"] == "2453" and r["cnpj"] == "17155730000164"
    assert r["casamento"].startswith("cadastro FCA")
    assert len(r["fatos_relevantes"]) == 3                                  # so os documentos da holding
    assert "CEMIG DISTRIBUIÇÃO S/A" in r["empresas_casadas"][1:]            # as parecidas ficam para conferencia
    assert "cadastro FCA" in fontes["cvm"]


def test_sem_o_cadastro_o_nome_escolhia_a_controlada(cvm):
    """O erro de 11/11, registrado: 'ENERGETICA' no Yahoo e 'ENERG' na CVM nao casam, e as
    controladas casam por prefixo. Por isso o nome so decide quando o cadastro nao tem o ticker,
    e o JSON diz que foi por nome."""
    cvm(IPE_CEMIG)
    r = CD.coletar_cvm("CMIG4", NOMES_CEMIG, {})
    assert r["empresa_escolhida"] == "CEMIG DISTRIBUIÇÃO S/A"
    assert r["casamento"].startswith("por nome") and r["cnpj"] is None


def test_cadastro_do_ano_anterior_vale_quando_o_do_ano_nao_tem_o_ticker(cvm):
    cvm(IPE_CEMIG, VAZIO, FCA_CEMIG)
    r = CD.coletar_cvm("CMIG4", NOMES_CEMIG, {})
    assert r["codigo_cvm"] == "2453"
    assert r["casamento"] == f"cadastro FCA {CD.datetime.now(CD.timezone.utc).year - 1}"


def test_ticker_no_cadastro_dispensa_o_nome(cvm):
    cvm(IPE_CEMIG, FCA_CEMIG)
    assert CD.coletar_cvm("CMIG4", [None, ""], {})["codigo_cvm"] == "2453"


def test_cadastro_ignora_papel_encerrado_formulario_velho_e_ticker_em_duas_companhias(cvm):
    a, b = "11.111.111/0001-11", "22.222.222/0001-22"
    fca = {"papeis": [_papel(a, "ALFA S.A.", "ALFA3", fim="2025-06-30"),               # deixou de negociar
                      _papel(b, "BETA S.A.", "BETA3", versao="1"),
                      _papel(b, "BETA S.A.", "BETA4", versao="2"),                     # versao nova tirou o BETA3
                      _papel(a, "ALFA S.A.", "DUPL3"), _papel(b, "BETA S.A.", "DUPL3", versao="2")],
           "geral": _geral((a, "111", "ALFA S.A."), (b, "222", "BETA S.A."))}
    cvm([], fca)
    assert CD.cadastro_do_ticker("ALFA3") is None
    assert CD.cadastro_do_ticker("BETA3") is None
    assert CD.cadastro_do_ticker("beta4")["codigo_cvm"] == "222"
    assert CD.cadastro_do_ticker("DUPL3") is None                                      # o cadastro nao decide
    assert CD.cadastro_do_ticker("") is None


def test_nucleo_igual_ganha_do_prefixo_quando_o_cadastro_nao_tem_o_ticker(cvm):
    ipe = (_ipe("00.000.000/0001-91", "BANCO DO BRASIL S.A.", "1023", n=2)
           + _ipe("33.333.333/0001-33", "BRASIL TECNOLOGIA E PARTICIPAÇÕES S.A.", "9999", n=8))
    cvm(ipe)
    r = CD.coletar_cvm("BBAS3", ["Banco do Brasil S.A.", "BRASIL ON NM", "BRASIL"], {})
    assert r["empresa_escolhida"] == "BANCO DO BRASIL S.A." and r["codigo_cvm"] == "1023"


def test_bdr_nao_casa_por_uma_palavra_do_nome(cvm):
    ipe = _ipe("44.444.444/0001-44", "ALFA HOLDINGS S.A.", "9954", n=4, categoria="Comunicado ao Mercado")
    cvm(ipe)
    fontes = {}
    r = CD.coletar_cvm("ROXO34", ["Nu Holdings Ltd.", "NU HOLDINGS DRN", None], fontes)
    assert r["empresa_escolhida"] is None and r["codigo_cvm"] is None
    assert fontes["cvm"].startswith("sem documentos casados")


def test_le_o_zip_do_formulario_cadastral_e_fica_com_a_ultima_versao():
    cab_p = "CNPJ_Companhia;Data_Referencia;Versao;Nome_Empresarial;Codigo_Negociacao;Data_Fim_Negociacao"
    cab_g = "CNPJ_Companhia;Data_Referencia;Versao;Nome_Empresarial;Codigo_CVM"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("fca_cia_aberta_valor_mobiliario_2026.csv",
                   f"{cab_p}\n{HOLDING};2026-01-01;2;CIA ENERGETICA DE MINAS GERAIS - CEMIG;CMIG4;\n".encode("latin-1"))
        z.writestr("fca_cia_aberta_geral_2026.csv",
                   (f"{cab_g}\n{HOLDING};2026-01-01;2;CIA ENERGÉTICA DE MINAS GERAIS - CEMIG;002453\n"
                    f"{HOLDING};2026-01-01;1;NOME ANTIGO;002453\n").encode("latin-1"))
        z.writestr("fca_cia_aberta_auditor_2026.csv", b"CNPJ_Companhia;Auditor\n")
    cadastro = CD._ler_fca(buf.getvalue())
    assert cadastro["papeis"][0]["Codigo_Negociacao"] == "CMIG4"
    ficha = cadastro["geral"]["17155730000164"]
    assert ficha["codigo_cvm"] == "2453" and ficha["nome"] == "CIA ENERGÉTICA DE MINAS GERAIS - CEMIG"
