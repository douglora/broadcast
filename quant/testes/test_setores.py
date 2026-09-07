import pandas as pd

from quant import universo as u
from quant.dados import contas_cvm as cc
from quant.dados import identidade as idn
from quant.dados import setores as st


# ─────────────────────────────────────────────────────────────
# Fixtures sinteticas no layout documentado (';', latin-1, nomes de coluna reais da CVM)
# ─────────────────────────────────────────────────────────────
CAD_CSV = (
    "CNPJ_CIA;DENOM_SOCIAL;DENOM_COMERC;DT_REG;DT_CONST;DT_CANCEL;MOTIVO_CANCEL;SIT;DT_INI_SIT;CD_CVM;SETOR_ATIV\n"
    "33.000.167/0001-01;PETROLEO BRASILEIRO S.A. PETROBRAS;PETROBRAS;1977-07-20;1953-10-03;;;ATIVO;1977-07-20;9512;Petróleo e Gás\n"
    "11.111.111/0001-11;BANCO EXEMPLO S.A.;BANCO EXEMPLO;1990-01-02;1980-01-01;;;ATIVO;1990-01-02;11111;Bancos\n"
    "22.222.222/0001-22;SEGURADORA EXEMPLO S.A.;SEG EXEMPLO;1995-03-04;1985-01-01;;;ATIVO;1995-03-04;22222;Seguradoras e Corretoras\n"
    "33.333.333/0001-33;HOLDING EXEMPLO PARTICIPACOES S.A.;HOLDING;2001-05-06;1999-01-01;;;ATIVO;2001-05-06;33333;Emp. Adm. Part. - Sem Setor Principal\n"
    "44.444.444/0001-44;VAREJO EXEMPLO S.A.;VAREJO;2005-07-08;2000-01-01;;;ATIVO;2005-07-08;44444;Comércio (Atacado e Varejo)\n"
    "55.555.555/0001-55;ENERGIA EXEMPLO S.A.;ENERGIA;2007-09-10;2003-01-01;;;ATIVO;2007-09-10;55555;Energia Elétrica\n"
    "66.666.666/0001-66;SEM SETOR NO CADASTRO S.A.;SEM SETOR;2010-11-12;2008-01-01;;;ATIVO;2010-11-12;66666;\n"
)

FCA_CSV = (
    "CNPJ_Companhia;Data_Referencia;Versao;ID_Documento;Valor_Mobiliario;Codigo_Negociacao;Mercado;"
    "Data_Inicio_Negociacao;Data_Fim_Negociacao\n"
    "33.000.167/0001-01;2024-12-31;1;1;Ações Preferenciais;PETR4;Bolsa;2000-08-09;\n"
    "11.111.111/0001-11;2024-12-31;1;2;Ações Preferenciais;BANC4;Bolsa;1995-01-02;\n"
    "22.222.222/0001-22;2024-12-31;1;3;Ações Ordinárias;SEGU3;Bolsa;1998-01-02;\n"
    "33.333.333/0001-33;2024-12-31;1;4;Ações Ordinárias;HOLD3;Bolsa;2002-01-02;\n"
    "44.444.444/0001-44;2024-12-31;1;5;Ações Ordinárias;VARE3;Bolsa;2006-01-02;\n"
    "55.555.555/0001-55;2024-12-31;1;6;Ações Ordinárias;ENER3;Bolsa;2008-01-02;\n"
    "66.666.666/0001-66;2024-12-31;1;7;Ações Ordinárias;VAZI3;Bolsa;2011-01-03;\n"
)

CURADOS_CSV = (
    "# comentario: esta linha e ignorada, como no eventos_curados.csv\n"
    "# outra linha de comentario\n"
    "cnpj;cd_cvm;setor;fonte;obs\n"
    "33.333.333/0001-33;;bancos;curadoria;Holding de controle de um banco - a CVM poe em Emp. Adm. Part.\n"
    "# ;99.999.999/0001-99;;energia;curadoria;linha comentada no meio do arquivo\n"
    ";55555;Saneamento, Serv. Água e Gás;curadoria;Sem CNPJ anotado: achado pelo CD_CVM e projetado na taxonomia\n"
)

# SETOR_ATIV cru da CVM -> bucket esperado (unico lugar do arquivo com acento, como no CSV real)
SETOR_ATIV_ESPERADO = {
    "Bancos": "bancos",
    "Intermediação Financeira": "bancos",
    "Arrendamento Mercantil": "bancos",
    "Securitização de Recebíveis": "bancos",
    "Seguradoras e Corretoras": "seguros",
    "Previdência Privada": "seguros",
    "Energia Elétrica": "energia",
    "Saneamento, Serv. Água e Gás": "utilidades",
    "Petróleo e Gás": "petroleo",
    "Petroquímicos e Borracha": "materiais",
    "Metalurgia e Siderurgia": "materiais",
    "Papel e Celulose": "materiais",
    "Extração Mineral": "materiais",
    "Química": "materiais",
    "Saúde": "saude",
    "Farmacêutico e Higiene": "saude",
    "Serviços médicos": "saude",
    "Comércio (Atacado e Varejo)": "varejo",
    "Alimentos": "consumo",
    "Bebidas e Fumo": "consumo",
    "Têxtil e Vestuário": "consumo",
    "Agricultura (Açúcar, Álcool e Cana)": "consumo",
    "Educação": "consumo",
    "Hospedagem e Turismo": "consumo",
    "Construção Civil, Mat. Constr. e Decoração": "imobiliario",
    "Comunicação e Informática": "tecnologia",
    "Telecomunicações": "tecnologia",
    "Máquinas, Equipamentos, Veículos e Peças": "industria",
    "Serviços Transporte e Logística": "industria",
    "Emp. Adm. Part. - Alimentos": "consumo",       # a holding segue o setor que a CVM nomeia
    "Emp. Adm. Part. - Energia Elétrica": "energia",
    "Emp. Adm. Part. - Sem Setor Principal": "outros",
}


def _cadastro():
    return idn.ler_cadastro(CAD_CSV.encode("latin-1"))


def _identidade():
    return idn.montar_identidade(idn.ler_fca_valor_mobiliario(FCA_CSV.encode("latin-1")), _cadastro(), None)


def _curados(tmp_path, texto=CURADOS_CSV):
    caminho = str(tmp_path / "setores_curados.csv")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(texto)
    return caminho


# ─────────────────────────────────────────────────────────────
# normalizar_setor
# ─────────────────────────────────────────────────────────────
def test_normalizar_setor_mapeia_os_setor_ativ_da_cvm():
    for setor_ativ, esperado in SETOR_ATIV_ESPERADO.items():
        assert st.normalizar_setor(setor_ativ) == esperado, setor_ativ
    # a taxonomia e fechada: nada escapa de SETORES
    assert set(SETOR_ATIV_ESPERADO.values()) <= set(st.SETORES)
    assert {s for s, _ in st.REGRAS} <= set(st.SETORES)


def test_normalizar_setor_ignora_acento_e_caixa():
    assert st.normalizar_setor("Petróleo e Gás") == st.normalizar_setor("PETROLEO E GAS") == "petroleo"
    assert st.normalizar_setor("energia elétrica") == st.normalizar_setor("ENERGIA ELETRICA") == "energia"
    assert st.normalizar_setor("  Bancos  ") == "bancos"


def test_balde_de_escape_da_cvm_e_o_desconhecido_viram_outros():
    assert st.normalizar_setor(st.CATCH_ALL_CVM) == "outros"
    assert st.CATCH_ALL_CVM in CAD_CSV                       # e o texto que a CVM escreve mesmo
    assert st.normalizar_setor("Emp. Adm. Part. - Sem Setor Principal") == "outros"
    assert st.normalizar_setor("Serviços Diversos") == "outros"
    assert st.normalizar_setor("") == st.normalizar_setor(None) == st.normalizar_setor(float("nan")) == "outros"


def test_petroleo_e_saneamento_nao_se_confundem_com_petroquimica_e_gas():
    # a ordem das REGRAS resolve as sobreposicoes de texto
    assert st.normalizar_setor("Petroquímicos e Borracha") == "materiais"      # contem 'petro'
    assert st.normalizar_setor("Saneamento, Serv. Água e Gás") == "utilidades"  # contem 'gas'
    assert st.normalizar_setor("Farmacêutico e Higiene") == "saude"            # contem 'higiene'


# ─────────────────────────────────────────────────────────────
# mapa_setores e curadoria
# ─────────────────────────────────────────────────────────────
def test_mapa_setores_do_cadastro_tem_chave_cnpj_de_14_digitos():
    mapa = st.mapa_setores(cadastro=_cadastro(), curados=st.carregar_curados("nao_existe.csv"))
    assert mapa["33000167000101"] == "petroleo" and mapa["11111111000111"] == "bancos"
    assert mapa["22222222000122"] == "seguros" and mapa["44444444000144"] == "varejo"
    assert mapa["55555555000155"] == "energia"
    assert mapa["33333333000133"] == "outros"                 # holding: o balde de escape da CVM
    assert "66666666000166" not in mapa                       # sem SETOR_ATIV: ausencia != 'outros'
    assert all(len(k) == 14 and k.isdigit() for k in mapa)
    assert set(mapa.values()) <= set(st.SETORES)


def test_curadoria_sobrepoe_a_classificacao_da_cvm(tmp_path):
    cad = _cadastro()
    curados = st.carregar_curados(_curados(tmp_path))
    sem = st.mapa_setores(cadastro=cad, curados=st.carregar_curados("nao_existe.csv"))
    com = st.mapa_setores(identidade=_identidade(), cadastro=cad, curados=curados)
    assert sem["33333333000133"] == "outros"
    assert com["33333333000133"] == "bancos"                  # curados > CVM
    # linha sem cnpj achada pelo cd_cvm, com o texto livre projetado na taxonomia
    assert sem["55555555000155"] == "energia" and com["55555555000155"] == "utilidades"
    assert com["33000167000101"] == "petroleo"                # quem nao esta na curadoria nao muda


def test_carregar_curados_pula_comentarios_e_normaliza(tmp_path):
    cur = st.carregar_curados(_curados(tmp_path))
    assert list(cur.columns) == st.COLUNAS_CURADOS and len(cur) == 2
    assert cur.iloc[0]["cnpj"] == "33333333000133" and cur.iloc[0]["setor"] == "bancos"
    assert pd.isna(cur.iloc[0]["cd_cvm"]) and cur.iloc[0]["fonte"] == "curadoria"
    assert cur.iloc[1]["cnpj"] == "" and cur.iloc[1]["cd_cvm"] == 55555
    assert cur.iloc[1]["setor"] == "utilidades"               # texto livre da curadoria cai nas REGRAS
    # arquivo ausente ou so com comentarios: esquema preservado, sem excecao
    assert list(st.carregar_curados(str(tmp_path / "nao_existe.csv")).columns) == st.COLUNAS_CURADOS
    assert len(st.carregar_curados(_curados(tmp_path, "# so comentario\n"))) == 0


def test_arquivo_curado_do_repositorio_e_valido():
    cur = st.carregar_curados()
    assert len(cur) >= 4 and (cur["fonte"] == "curadoria").all()
    assert cur["setor"].isin(st.SETORES).all()
    assert (cur["cnpj"].str.len() == 14).all() and cur["cnpj"].is_unique
    # honestidade: toda linha diz que foi anotada de memoria e precisa ser conferida
    assert cur["obs"].str.contains("memoria").all() and cur["obs"].str.contains("conferir").all()
    mapa = st.mapa_setores()                                  # curados=None LE o arquivo do repo
    assert mapa["61532644000115"] == "bancos"                 # Itausa: holding de banco
    assert mapa["03847461000192"] == "materiais"              # Bradespar: risco de minerio
    assert st.mapa_setores(curados=st.carregar_curados("nao_existe.csv")) == {}


# ─────────────────────────────────────────────────────────────
# financeiras e contas_cvm.eh_financeira
# ─────────────────────────────────────────────────────────────
def test_financeiras_sao_os_cd_cvm_de_bancos_e_seguros():
    ident = _identidade()
    mapa = st.mapa_setores(identidade=ident, curados=st.carregar_curados("nao_existe.csv"))
    assert st.financeiras(mapa, ident) == {11111, 22222}
    assert st.MACROSSETORES_FINANCEIROS == ("bancos", "seguros")
    assert st.financeiras({}, ident) == set() and st.financeiras(mapa, None) == set()


def test_financeiras_e_eh_financeira_concordam_no_cadastro():
    cad = _cadastro()
    ident = _identidade()
    financeiras = st.financeiras(st.mapa_setores(identidade=ident,
                                                 curados=st.carregar_curados("nao_existe.csv")), ident)
    for r in cad.to_dict("records"):
        pelo_texto = cc.eh_financeira(r["setor"])
        pelo_mapa = int(r["cd_cvm"]) in financeiras
        assert pelo_texto == pelo_mapa, r["setor"]
    # o mapa e de proposito MAIS largo que eh_financeira, que so ve 'banc'/'segur' no texto cru
    assert st.normalizar_setor("Intermediação Financeira") == "bancos"
    assert not cc.eh_financeira("Intermediação Financeira")


# ─────────────────────────────────────────────────────────────
# universo.setores
# ─────────────────────────────────────────────────────────────
def _universo():
    return pd.DataFrame([
        {"data": pd.Timestamp("2024-12-30"), "ticker": "PETR4", "isin": "BRPETRACNPR6",
         "empresa": "33000167000101", "adtv21": 9e8, "presenca": 1.0, "preco": 35.0, "n_pregoes": 252},
        {"data": pd.Timestamp("2024-12-30"), "ticker": "BANC4", "isin": "BRBANCACNPR0",
         "empresa": "11111111000111", "adtv21": 5e8, "presenca": 1.0, "preco": 30.0, "n_pregoes": 252},
        {"data": pd.Timestamp("2024-12-30"), "ticker": "NOVO3", "isin": "BRNOVOACNOR1",
         "empresa": "99999999000199", "adtv21": 2e6, "presenca": 1.0, "preco": 10.0, "n_pregoes": 252},
    ], columns=u.COLUNAS)


def test_universo_setores_preenche_a_coluna_pelo_mapa():
    uni = _universo()
    mapa = st.mapa_setores(cadastro=_cadastro(), curados=st.carregar_curados("nao_existe.csv"))
    com = u.setores(uni, mapa)
    assert list(com.columns) == u.COLUNAS + ["setor"]
    assert com.set_index("ticker")["setor"].to_dict() == {"PETR4": "petroleo", "BANC4": "bancos", "NOVO3": None}
    assert list(uni.columns) == u.COLUNAS                     # nao mexe no DataFrame original


def test_universo_setores_sem_mapa_e_cnpj_desconhecido_devolvem_none():
    uni = _universo()
    assert u.setores(uni)["setor"].isna().all()
    mapa = st.mapa_setores(cadastro=_cadastro(), curados=st.carregar_curados("nao_existe.csv"))
    assert mapa.get("99999999000199") is None                 # CNPJ fora do mapa: None, sem excecao
    assert u.setores(uni, mapa).set_index("ticker").loc["NOVO3", "setor"] is None
    vazio = u.setores(pd.DataFrame(columns=u.COLUNAS), mapa)
    assert list(vazio.columns) == u.COLUNAS + ["setor"] and len(vazio) == 0
    assert list(u.setores(None).columns) == u.COLUNAS + ["setor"]


def test_universo_setores_ainda_aceita_mapa_com_chave_de_ticker():
    # o segmento das carteiras de indice da B3 tem chave ticker, nao CNPJ
    com = u.setores(_universo(), {"NOVO3": "tecnologia"})
    assert com.set_index("ticker")["setor"].to_dict() == {"PETR4": None, "BANC4": None, "NOVO3": "tecnologia"}


# ─────────────────────────────────────────────────────────────
# identidade carrega o setor do cadastro
# ─────────────────────────────────────────────────────────────
def test_identidade_carrega_o_setor_do_cadastro():
    cad = _cadastro()
    assert "setor" in cad.columns
    assert cad.set_index("cnpj").loc["11111111000111", "setor"] == "Bancos"
    ident = _identidade()
    assert "setor" in idn.COLUNAS and list(ident.columns) == idn.COLUNAS
    linhas = ident.set_index("ticker")["setor"].to_dict()
    assert linhas["BANC4"] == "Bancos" and st.normalizar_setor(linhas["PETR4"]) == "petroleo"
    assert linhas["VAZI3"] == "" and linhas["HOLD3"] == st.CATCH_ALL_CVM
    assert idn.resolver(ident, "SEGU3", "2024-01-02")["setor"] == "Seguradoras e Corretoras"
    # ticker sem CNPJ (so COTAHIST) ou sem cadastro fica com "" e nao NaN
    so_fca = idn.montar_identidade(idn.ler_fca_valor_mobiliario(FCA_CSV.encode("latin-1")), None, None)
    assert (so_fca["setor"] == "").all()


# ─────────────────────────────────────────────────────────────
# esquema vazio, contagem e main
# ─────────────────────────────────────────────────────────────
def test_entradas_vazias_nao_levantam():
    vazio = st.carregar_curados("nao_existe.csv")
    assert st.mapa_setores(identidade=None, cadastro=None, curados=vazio) == {}
    assert st.mapa_setores(identidade=pd.DataFrame(), cadastro=pd.DataFrame(columns=["cnpj"]), curados=vazio) == {}
    assert st.mapa_setores(cadastro=_cadastro(), curados=pd.DataFrame()) != {}
    assert st.financeiras({}, None) == set()
    assert st.contagem({}) == {s: 0 for s in st.SETORES}
    assert st.contagem(None)["outros"] == 0


def test_contagem_conta_por_setor_e_main_imprime(capsys):
    mapa = st.mapa_setores(cadastro=_cadastro(), curados=st.carregar_curados("nao_existe.csv"))
    cont = st.contagem(mapa)
    assert list(cont) == list(st.SETORES)                     # ordem fixa, inclusive baldes vazios
    assert cont["bancos"] == 1 and cont["outros"] == 1 and sum(cont.values()) == len(mapa)
    assert st.main(["--identidade", "nao_existe.parquet"]) == 0
    saida = capsys.readouterr().out
    assert "bancos" in saida and "outros" in saida and "TOTAL" in saida
