"""Testes do gerador de mercado sintetico (quant/validacao/mercado_sintetico.py).

O gerador precisa estar CERTO antes de qualquer coisa ser validada atraves dele: se o
esquema, o ajuste por proventos ou o point-in-time estiverem errados aqui, todo resultado
medido em cima destes dados e ficcao. Por isso os testes cobram o gerador direto:

  (1) esquema coluna a coluna contra os modulos reais (cotahist, eventos, cvm_fundamentos,
      identidade, nefin) e leitura de volta do banco gravado pelos leitores de producao;
  (2) a estrutura plantada e recuperavel por regressao direta - e o CONTROLE NULO (sem
      premio plantado) nao acha nada;
  (3) as armadilhas que o mercado real tem: deslistagem, recuperacao judicial (CODBDI 08),
      desdobramento que parte o preco, ESCALA_MOEDA misturada, acumulados trimestrais,
      reapresentacao (VERSAO 2) e o vazamento plantado (dt_receb = dt_refer).

Parametros pequenos de proposito (12 a 14 empresas, 3 a 6 anos): a geracao completa
(120 empresas, 17 anos) leva ~9 s e nao cabe num teste.
"""
import datetime
import os

import numpy as np
import pandas as pd
import pytest

from quant import custos, universo
from quant.dados import contas_cvm, cotahist, eventos, identidade, nefin
from quant.dados import cvm_fundamentos as cf
from quant.validacao import mercado_sintetico as ms

INI, FIM, N_EMPRESAS, SEMENTE = "2018-01-01", "2020-12-31", 12, 3
INI_LONGO, FIM_LONGO = "2015-01-01", "2020-12-31"


@pytest.fixture(scope="module")
def dados():
    return ms.gerar(ini=INI, fim=FIM, n_empresas=N_EMPRESAS, seed=SEMENTE)


def _ols(y, x):
    """Regressao simples y = a + b*x -> (b, t de b) com erro padrao classico."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    X = np.column_stack([np.ones(len(x)), x])
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    resid = y - X @ beta
    s2 = float(resid @ resid) / (len(x) - 2)
    erro = float(np.sqrt(s2 * np.linalg.inv(X.T @ X)[1, 1]))
    return float(beta[1]), float(beta[1] / erro)


def _linha_cotahist():
    """Um registro COTAHIST de verdade (245 caracteres) para servir de referencia de esquema."""
    campos = dict(tipreg="01", data="20241227", codbdi="02", ticker="PETR4", tpmerc="010",
                  nome="PETROBRAS", especi="PN      N2", prazot="", moeda="R$", abe="3550",
                  max="3570", min="3540", med="3555", fec="3566", bid="3565", ask="3567",
                  negocios="100", qtd="1000", volume="356600", preexe="0", indopc="0",
                  datven="99991231", fatcot="1", ptoexe="0", isin="BRPETRACNPR6", dismes="0")
    return cotahist.parse(cotahist.montar_registro(campos))


CAD_CSV = (
    "CNPJ_CIA;DENOM_SOCIAL;DT_REG;DT_CANCEL;SIT;DT_INI_SIT;CD_CVM;SETOR_ATIV\n"
    "33.000.167/0001-01;PETROLEO BRASILEIRO S.A.;1977-07-20;;ATIVO;1977-07-20;9512;Petróleo e Gás\n"
).encode("latin-1")


# ─────────────────────────────────────────────────────────────
# (1) Esquema: coluna a coluna contra os modulos reais
# ─────────────────────────────────────────────────────────────
def test_cotacoes_tem_o_esquema_do_cotahist(dados):
    ref = _linha_cotahist()
    c = dados["cotacoes"]
    assert set(c.columns) >= set(ref.columns)
    # mesmos tipos que o parser real produz (data vira datetime.date, precos float, Int64...)
    assert {k: str(v) for k, v in c[ref.columns].dtypes.items()} == {k: str(v) for k, v in ref.dtypes.items()}
    assert isinstance(c["data"].iloc[0], datetime.date)
    assert (c["tpmerc"] == "010").all()
    assert set(c["codbdi"]) <= set(cotahist.CODBDI_ACOES_SERIE)
    assert not c.duplicated(["data", "ticker"]).any()
    assert (c["fec"] > 0).all() and (c["volume"] > 0).all()
    # o recorte de acoes a vista nao descarta nada do que geramos
    assert len(cotahist.acoes_a_vista(c, apenas_lote_padrao=False)) == len(c)


def test_eventos_fundamentos_identidade_e_fatores_tem_o_esquema_real(dados):
    assert list(dados["eventos"].columns) == eventos.COLUNAS
    assert set(dados["eventos"]["tipo"]) <= set(eventos.TIPOS)
    assert list(dados["fundamentos"].columns) == cf.COLUNAS
    assert list(dados["identidade"].columns) == identidade.COLUNAS
    assert list(dados["fatores"].columns) == nefin.FATORES
    assert dados["fatores"].index.name == "Date"
    assert dados["fatores"].dtypes.eq(float).all()
    # cadastro: o mesmo formato que identidade.ler_cadastro devolve
    assert list(dados["cadastro"].columns) == list(identidade.ler_cadastro(CAD_CSV).columns)
    cdi = dados["cdi"]
    assert cdi.name == "cdi" and cdi.index.name == "data" and (cdi > 0).all()
    assert len(cdi) == len(dados["fatores"])


def test_fundamentos_saem_do_parser_real_da_cvm(dados):
    f = dados["fundamentos"]
    assert set(f["demo"]) == {"BPA", "BPP", "DRE", "DFC_MI"}
    assert set(f["tipo"]) == {"DFP", "ITR"}
    assert set(f["ordem_exerc"]) == {"ULTIMO", "PENULTIMO"}       # comparativo existe e e ignorado
    assert set(f["escopo"]) <= {"con", "ind"} and f["escopo"].nunique() == 2
    # acumulados: ITR de 3/6/9 meses e DFP de 12 (e o trimestre isolado que o real tambem traz)
    itr = f[(f["tipo"] == "ITR") & (f["demo"] == "DRE")]
    assert set(itr["meses"].dropna().unique()) == {3, 6, 9}
    assert set(f.loc[(f["tipo"] == "DFP") & (f["demo"] == "DRE"), "meses"].dropna().unique()) == {12}
    assert (f["dt_receb"] > f["dt_refer"]).all()
    assert f["valor_reais"].notna().all()


def test_escala_moeda_misturada_e_aplicada(dados):
    """MIL, UNIDADE e MILHAO convivem; o LPA (3.99*) NAO leva escala."""
    emp = dados["gabarito"]["empresas"]
    assert set(emp["escala"]) == {"MIL", "UNIDADE", "MILHAO"}
    f = dados["fundamentos"]
    for _, e in emp.iterrows():
        lpa = f[(f["cd_cvm"] == e["cd_cvm"]) & (f["conta"] == "3.99.01.01")]["valor_reais"]
        assert lpa.abs().max() < 1000.0        # em reais por acao, nunca multiplicado por 1000
    receita = f[(f["conta"] == "3.01") & (f["demo"] == "DRE")]["valor_reais"]
    assert receita.min() > 1e6                 # em reais, ja com a escala aplicada


# ─────────────────────────────────────────────────────────────
# (2) Banco em disco e carregadores reais
# ─────────────────────────────────────────────────────────────
def test_gravar_banco_e_lido_de_volta_pelos_leitores_reais(tmp_path, dados):
    contagem = ms.gravar_banco(dados, tmp_path)
    assert os.path.exists(tmp_path / "eventos.parquet") and os.path.exists(tmp_path / "identidade.parquet")
    assert os.path.exists(tmp_path / "cotacoes_diarias" / "ano=2019" / "parte.parquet")
    assert os.path.exists(tmp_path / "fundamentos_pit" / "ano=2019" / "parte.parquet")
    assert sum(v for k, v in contagem.items() if k.startswith("cotacoes")) == len(dados["cotacoes"])
    with ms.banco_em(tmp_path):
        cot = cotahist.carregar(2018, 2020)
        fun = cf.carregar(range(2017, 2021))
    assert len(cot) == len(dados["cotacoes"]) and len(fun) == len(dados["fundamentos"])
    pd.testing.assert_frame_equal(cot, dados["cotacoes"])
    chave = ["cd_cvm", "tipo", "dt_refer", "versao", "demo", "escopo", "conta", "dt_ini", "ordem_exerc"]
    a = fun.sort_values(chave).reset_index(drop=True)
    b = dados["fundamentos"].sort_values(chave).reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)
    ev = eventos.carregar_eventos(str(tmp_path / "eventos.parquet"))
    ident = identidade.carregar_identidade(str(tmp_path / "identidade.parquet"))
    assert len(ev) == len(dados["eventos"]) and len(ident) == len(dados["identidade"])


def test_instalar_aponta_os_carregadores_para_a_memoria(monkeypatch, dados):
    ms.instalar(monkeypatch, dados)
    cot = cotahist.carregar(2018, 2020)
    assert len(cot) == len(dados["cotacoes"])
    assert cotahist.carregar(2019, 2019)["data"].map(lambda d: d.year).eq(2019).all()
    tk = dados["gabarito"]["papeis"]["ticker"].iloc[0]
    assert set(cotahist.carregar(2018, 2020, tickers=[tk])["ticker"]) == {tk}
    assert list(cotahist.carregar(2018, 2018, colunas=["data", "fec"]).columns) == ["data", "fec"]
    cod = int(dados["gabarito"]["empresas"]["cd_cvm"].iloc[0])
    assert set(cf.carregar([2019], cd_cvm=cod)["cd_cvm"]) == {cod}
    assert len(identidade.carregar_identidade()) == len(dados["identidade"])
    assert len(eventos.carregar_eventos()) == len(dados["eventos"])


def test_main_gera_e_grava_e_recusa_o_banco_real(tmp_path, capsys):
    destino = tmp_path / "banco_sintetico"
    assert ms.main(["--dir", str(destino), "--ini", INI, "--fim", FIM, "--n-empresas", "6",
                    "--seed", "1"]) == 0
    assert os.path.exists(destino / "identidade.parquet")
    assert "linhas_cotacoes" in capsys.readouterr().out
    assert ms.main(["--dir", os.path.join(os.path.dirname(ms.DIR_PADRAO), "banco")]) == 2


# ─────────────────────────────────────────────────────────────
# (3) A estrutura plantada e recuperavel - e o controle nulo nao acha nada
# ─────────────────────────────────────────────────────────────
def _coef_momento(lambda_mom, seed=11):
    """Regressao direta dos retornos gerados na caracteristica de momento defasada."""
    d = ms.gerar(ini=INI_LONGO, fim=FIM_LONGO, n_empresas=14, seed=seed, lambda_mom=lambda_mom)
    ret = eventos.retorno_total(d["cotacoes"], d["eventos"])
    ret["ano_mes"] = ret["data"].dt.year * 100 + ret["data"].dt.month
    carac = d["gabarito"]["caracteristicas"]
    carac = carac[carac["vivo"] & (carac["mom"] != 0)]
    junto = ret.merge(carac[["ano_mes", "ticker", "mom"]], on=["ano_mes", "ticker"], how="inner")
    assert len(junto) > 5000
    return _ols(junto["ret_total"], junto["mom"])


def test_premio_de_momento_plantado_aparece_na_regressao():
    coef, t = _coef_momento(0.0015)
    assert coef > 0.0005 and t > 3.0


def test_controle_nulo_nao_produz_premio_de_momento():
    """O teste que carrega informacao: sem premio plantado, nada pode ser 'descoberto'."""
    coef, t = _coef_momento(0.0)
    assert abs(t) < 2.5 and abs(coef) < 0.0005


def test_o_substrato_nao_fabrica_alfa(dados):
    """A carteira igualmente ponderada de TODOS os papeis tem alfa zero contra os fatores
    gerados. E a fundacao do controle nulo: se o proprio mercado sintetico ja tivesse alfa,
    um backtest sem premio plantado poderia "achar" algo sem estar errado."""
    fat = dados["fatores"]
    carteira = dados["gabarito"]["retornos"].mean(axis=1)
    excesso = (carteira - fat["Risk_Free"]).dropna()
    beta, _ = _ols(excesso, fat.loc[excesso.index, "Rm_minus_Rf"])
    residuo = excesso - beta * fat.loc[excesso.index, "Rm_minus_Rf"]
    t_alfa = float(residuo.mean() / (residuo.std(ddof=1) / np.sqrt(len(residuo))))
    assert abs(t_alfa) < 2.0
    assert abs(float(residuo.mean()) * 252) < 0.04       # menos de 4 p.p. ao ano de ruido


def test_fatores_trazem_o_mercado_e_o_cdi_verdadeiros(dados):
    """Rm_minus_Rf E o excesso de mercado gerado e Risk_Free E o CDI: a atribuicao tem gabarito."""
    fat, cdi = dados["fatores"], dados["cdi"]
    assert np.allclose(fat["Risk_Free"].to_numpy(), cdi.to_numpy())
    pap = dados["gabarito"]["papeis"].sort_values("adtv", ascending=False).iloc[0]
    ret = dados["gabarito"]["retornos"][pap["ticker"]]
    excesso = ret - fat["Risk_Free"].to_numpy()
    beta, _ = _ols(excesso, fat["Rm_minus_Rf"])
    assert abs(beta - float(pap["beta"])) < 0.25


def test_serie_continua_valida_com_premio_absurdo():
    """Um lambda em ordem de grandeza errada nao pode gerar preco infinito ou NaN: o que
    sai daqui tem de continuar sendo um COTAHIST possivel (o gerador avisa no log)."""
    d = ms.gerar(ini=INI, fim=FIM, n_empresas=6, seed=1, lambda_mom=0.9)
    c = d["cotacoes"]
    assert np.isfinite(c["fec"]).all() and (c["fec"] >= ms.PRECO_PISO).all()
    assert (c["fec"] <= ms.PRECO_TETO).all()
    assert np.isfinite(c["volume"]).all() and c["qtd"].notna().all()
    assert d["gabarito"]["retornos"].to_numpy().min() >= ms.RETORNO_LIMITES[0]
    # com premio na ordem certa nada e truncado
    sao = ms.gerar(ini=INI, fim=FIM, n_empresas=6, seed=1, lambda_mom=0.0006)
    r = sao["gabarito"]["retornos"].to_numpy()
    assert r.min() > ms.RETORNO_LIMITES[0] and r.max() < ms.RETORNO_LIMITES[1]


# ─────────────────────────────────────────────────────────────
# (4) Reprodutibilidade
# ─────────────────────────────────────────────────────────────
def test_mesma_semente_da_frames_identicos_e_semente_diferente_nao():
    a = ms.gerar(ini=INI, fim=FIM, n_empresas=6, seed=5)
    b = ms.gerar(ini=INI, fim=FIM, n_empresas=6, seed=5)
    for chave in ("cotacoes", "eventos", "fundamentos", "identidade", "cadastro", "fatores"):
        pd.testing.assert_frame_equal(a[chave], b[chave])
    pd.testing.assert_series_equal(a["cdi"], b["cdi"])
    pd.testing.assert_frame_equal(a["gabarito"]["empresas"], b["gabarito"]["empresas"])
    c = ms.gerar(ini=INI, fim=FIM, n_empresas=6, seed=6)
    assert not a["cotacoes"]["fec"].equals(c["cotacoes"]["fec"])
    assert not a["gabarito"]["empresas"]["beta"].equals(c["gabarito"]["empresas"]["beta"])


# ─────────────────────────────────────────────────────────────
# (5) Sobrevivencia, liquidez e uma classe por empresa
# ─────────────────────────────────────────────────────────────
def test_mortas_deslistam_no_meio_da_amostra_e_passam_por_recuperacao_judicial(dados):
    c = dados["cotacoes"]
    gab = dados["gabarito"]["papeis"]
    ultimo = c.groupby("ticker")["data"].max()
    fim = c["data"].max()
    mortas = gab.dropna(subset=["data_fim"])
    assert len(mortas) >= 1
    for _, p in mortas.iterrows():
        assert ultimo[p["ticker"]] < fim - pd.Timedelta(days=90)
        assert ultimo[p["ticker"]] == pd.Timestamp(p["data_fim"]).date()
        # estava viva antes: aparece em anos anteriores ao da morte
        anos = {d.year for d in c.loc[c["ticker"] == p["ticker"], "data"]}
        assert min(anos) < pd.Timestamp(p["data_fim"]).year
    # a serie de uma empresa em recuperacao judicial continua, em CODBDI 08
    rj = c[c["codbdi"] == "08"]
    assert len(rj) > 0 and set(rj["ticker"]) <= set(mortas["ticker"])
    tk = rj["ticker"].iloc[0]
    assert len(cotahist.acoes_a_vista(c[c["ticker"] == tk], apenas_lote_padrao=True)) \
        < len(cotahist.acoes_a_vista(c[c["ticker"] == tk], apenas_lote_padrao=False))


def test_liquidez_cobre_as_tres_faixas_de_custo(dados):
    """As tres faixas de custos.FAIXAS_SPREAD precisam existir, senao o teto de iliquidez
    e os 80 bps nunca chegam a valer no backtest."""
    adtv = dados["gabarito"]["papeis"]["adtv"]
    assert (adtv >= 20e6).sum() >= 1 and ((adtv >= 5e6) & (adtv < 20e6)).sum() >= 1
    assert (adtv < 5e6).sum() >= 1
    assert len({custos.meio_spread(a) for a in adtv}) == 3


def test_pares_on_pn_dividem_a_empresa_e_o_universo_escolhe_uma_classe(dados):
    gab = dados["gabarito"]
    pares = gab["empresas"].dropna(subset=["ticker_pn"])
    assert len(pares) >= 1
    ident = dados["identidade"].set_index("ticker")
    for _, e in pares.iterrows():
        on, pn = ident.loc[e["ticker_on"]], ident.loc[e["ticker_pn"]]
        assert on["cnpj"] == pn["cnpj"] and on["cd_cvm"] == pn["cd_cvm"]
        assert on["isin"] != pn["isin"]
    uni = universo.universo_pit(dados["cotacoes"], identidade=dados["identidade"])
    assert len(uni) > 0
    assert not uni.duplicated(["data", "empresa"]).any()
    assert uni.groupby("data")["ticker"].nunique().min() >= 3
    assert (uni["adtv21"] >= universo.ADTV_MIN).all() and (uni["preco"] >= universo.PRECO_MIN).all()


def test_financeiras_sao_marcadas_no_cadastro(dados):
    cad = dados["cadastro"].set_index("cd_cvm")
    emp = dados["gabarito"]["empresas"]
    assert emp["financeira"].sum() >= 1
    for _, e in emp.iterrows():
        assert contas_cvm.eh_financeira(cad.loc[e["cd_cvm"], "setor"]) == bool(e["financeira"])
    # banco nao tem 3.03 (resultado bruto): o extrator real devolve NaN, nao um numero errado
    fin = int(emp[emp["financeira"]]["cd_cvm"].iloc[0])
    f = dados["fundamentos"]
    assert f[(f["cd_cvm"] == fin) & (f["conta"] == "3.03")].empty
    x = cf.ttm(f, fin, pd.Timestamp("2019-12-20"))
    assert x is not None and np.isnan(x["lucro_bruto"]) and x["receita"] > 0


# ─────────────────────────────────────────────────────────────
# (6) Eventos corporativos contra a serie de precos
# ─────────────────────────────────────────────────────────────
def test_desdobramento_parte_o_preco_e_retorno_total_conserta(dados):
    esp = dados["gabarito"]["eventos_especiais"]["desdobramento"]
    ev = dados["eventos"]
    linha = ev[(ev["ticker"] == esp["ticker"]) & (ev["tipo"] == "DESDOBRAMENTO")]
    assert len(linha) == 1 and float(linha["fator"].iloc[0]) == 2.0
    c = dados["cotacoes"]
    c = c[c["ticker"] == esp["ticker"]]
    ret = eventos.retorno_total(c, ev).set_index("data")
    dia = ret.loc[esp["data_ex"]]
    verdade = float(dados["gabarito"]["retornos"].loc[esp["data_ex"], esp["ticker"]])
    assert dia["ret_preco"] < -0.45                       # o preco de tela cai pela metade
    assert abs(dia["ret_total"] - verdade) < 5e-3         # o retorno total nao ve o desdobramento
    assert abs(dia["ret_total"]) < 0.15


def test_bonificacao_de_dez_por_cento_entra_no_retorno_total(dados):
    esp = dados["gabarito"]["eventos_especiais"]["bonificacao"]
    ev = dados["eventos"]
    linha = ev[(ev["ticker"] == esp["ticker"]) & (ev["tipo"] == "BONIFICACAO")]
    assert len(linha) == 1 and abs(float(linha["fator"].iloc[0]) - 1.10) < 1e-12
    c = dados["cotacoes"]
    ret = eventos.retorno_total(c[c["ticker"] == esp["ticker"]], ev).set_index("data")
    dia = ret.loc[esp["data_ex"]]
    verdade = float(dados["gabarito"]["retornos"].loc[esp["data_ex"], esp["ticker"]])
    assert dia["ret_total"] - dia["ret_preco"] > 0.08     # 10% de acoes a mais
    assert abs(dia["ret_total"] - verdade) < 5e-3


def test_proventos_e_precos_concordam_ao_longo_de_toda_a_serie(dados):
    """A serie e gerada NAO ajustada: retorno_total tem de devolver exatamente o retorno
    plantado, dividendo a dividendo. Um fator errado apareceria aqui."""
    ev = dados["eventos"]
    assert set(ev["tipo"]) >= {"DIVIDENDO", "JCP"}
    assert (ev.loc[ev["tipo"].isin(eventos.TIPOS_DINHEIRO), "valor"] > 0).all()
    assert ev.loc[ev["tipo"].isin(eventos.TIPOS_DINHEIRO), "fator"].isna().all()
    pagadoras = set(ev.loc[ev["tipo"] == "DIVIDENDO", "ticker"])
    assert len(pagadoras) >= 3
    tk = dados["gabarito"]["papeis"].sort_values("adtv", ascending=False)["ticker"].iloc[0]
    c = dados["cotacoes"]
    ret = eventos.retorno_total(c[c["ticker"] == tk], ev).set_index("data")["ret_total"]
    verdade = dados["gabarito"]["retornos"][tk]
    junto = pd.concat([ret.rename("calc"), verdade.rename("verd")], axis=1).dropna()
    assert len(junto) > 500
    assert float((junto["calc"] - junto["verd"]).abs().max()) < 5e-3


# ─────────────────────────────────────────────────────────────
# (7) Point-in-time: atraso de recebimento, reapresentacao e vazamento
# ─────────────────────────────────────────────────────────────
def test_ttm_real_consome_os_documentos_gerados(dados):
    f = dados["fundamentos"]
    emp = dados["gabarito"]["empresas"]
    t = pd.Timestamp("2019-12-20")
    resultados = {int(c): cf.ttm(f, int(c), t) for c in emp["cd_cvm"]}
    assert sum(x is not None for x in resultados.values()) >= 0.8 * len(emp)
    for cod, x in resultados.items():
        if x is None:
            continue
        e = emp[emp["cd_cvm"] == cod].iloc[0]
        assert x["receita"] > 0 and x["pl"] > 0 and x["ativo"] > x["pl"]
        assert len(x["trimestres"]) == 4 and x["dt_receb"] <= t.date()
        assert abs(x["ebitda"] - (x["ebit"] + x["depreciacao"])) < 1.0
        # o LPA (sem escala) e o lucro (com escala) tem de fechar: prova a ESCALA_MOEDA
        assert abs(x["lpa"] * float(e["n_acoes"]) / x["lucro_liquido"] - 1.0) < 0.05
        # somas por descricao (D&A, capex) nao contam em dobro a linha do trimestre isolado
        # (a folga de 1e-4 e o arredondamento de VL_CONTA em 2 casas; contar em dobro daria ~1,5x)
        assert abs(x["depreciacao"] / x["receita"] / ms.DEPRECIACAO_SOBRE_RECEITA - 1.0) < 1e-4
        assert abs(x["capex"] / x["receita"] / -ms.CAPEX_SOBRE_RECEITA - 1.0) < 1e-4


def test_atraso_de_recebimento_e_respeitado():
    d = ms.gerar(ini=INI, fim=FIM, n_empresas=6, seed=2, atraso_receb_dias=90, restatement=False)
    f = d["fundamentos"]
    assert set((f["dt_receb"] - f["dt_refer"]).dt.days.unique()) == {90}


def test_reapresentacao_so_muda_o_ttm_depois_do_dt_receb(dados):
    """A VERSAO 2 derruba o lucro; antes do dt_receb dela, visao_em tem de mostrar a VERSAO 1."""
    rest = dados["gabarito"]["restatements"]
    assert len(rest) >= 1
    r = rest.iloc[0]
    f = dados["fundamentos"]
    doc = f[(f["cd_cvm"] == r["cd_cvm"]) & (f["dt_refer"] == r["dt_refer"]) & (f["tipo"] == "DFP")]
    assert set(doc["versao"]) == {1, 2}
    antes = cf.ttm(f, int(r["cd_cvm"]), r["dt_receb_v2"] - pd.Timedelta(days=1))
    depois = cf.ttm(f, int(r["cd_cvm"]), r["dt_receb_v2"])
    assert antes is not None and depois is not None
    roe_antes = antes["lucro_liquido"] / antes["pl"]
    roe_depois = depois["lucro_liquido"] / depois["pl"]
    assert roe_antes > 0.10 > roe_depois                  # a reapresentacao vira um filtro de qualidade
    assert roe_depois < 0.5 * roe_antes
    assert antes["receita"] == depois["receita"]          # so o lucro foi reapresentado


def test_vazar_publica_no_mesmo_dia_da_referencia():
    vaz = ms.gerar(ini=INI, fim=FIM, n_empresas=6, seed=2, vazar=True)
    normal = ms.gerar(ini=INI, fim=FIM, n_empresas=6, seed=2)
    assert (vaz["fundamentos"]["dt_receb"] == vaz["fundamentos"]["dt_refer"]).all()
    assert not (normal["fundamentos"]["dt_receb"] == normal["fundamentos"]["dt_refer"]).any()
    # com vazamento, o balanco do 4T ja esta disponivel no dia 31/12
    t = pd.Timestamp("2019-12-31")
    cod = int(vaz["gabarito"]["empresas"]["cd_cvm"].iloc[0])
    com = cf.ttm(vaz["fundamentos"], cod, t)
    sem = cf.ttm(normal["fundamentos"], cod, t)
    assert com["dt_refer"] > sem["dt_refer"]


# ─────────────────────────────────────────────────────────────
# (8) Gabarito
# ─────────────────────────────────────────────────────────────
def test_gabarito_descreve_a_verdade_plantada(dados):
    g = dados["gabarito"]
    emp, pap = g["empresas"], g["papeis"]
    assert len(emp) == N_EMPRESAS and len(pap) >= N_EMPRESAS
    for coluna in ("beta", "q", "v", "cd_cvm", "cnpj", "setor", "financeira", "data_fim", "vencedora"):
        assert coluna in emp.columns
    assert emp["cd_cvm"].is_unique and emp["cnpj"].is_unique
    assert abs(float(emp["q"].mean())) < 1e-9 and abs(float(emp["v"].std(ddof=0)) - 1.0) < 0.15
    assert g["parametros"]["seed"] == SEMENTE and g["parametros"]["n_empresas"] == N_EMPRESAS
    assert set(g["retornos"].columns) == set(pap["ticker"])
    assert not bool(emp["vencedora"].any())               # sem premio plantado nao ha vencedora
    ganhadoras = ms.gerar(ini=INI, fim=FIM, n_empresas=6, seed=2, lambda_qual=0.0004)
    assert bool(ganhadoras["gabarito"]["empresas"]["vencedora"].any())
