"""A ficha do leitor do Autopilot Terminal: o que ela devolve, de onde, com que idade, e o que NUNCA faz (inventar).

Todos os arquivos do terminal vem de `terminal_fixture.py` (pasta temporaria, formato real, numeros contados a mao): estes testes nao
leem o cache de verdade. `hoje` fixo em 2026-10-12 para a idade dos dados ser previsivel.
"""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from quant import terminal as T
from quant.testes.terminal_fixture import montar_terminal

HOJE = date(2026, 10, 12)
FUSO = timezone(timedelta(hours=-3))


@pytest.fixture
def raiz(tmp_path, monkeypatch):
    montar_terminal(tmp_path)
    monkeypatch.setenv("AUTOPILOT_TERMINAL", str(tmp_path))
    T.limpar_cache()
    yield tmp_path
    T.limpar_cache()


def ficha(t="PETR4", hoje=HOJE):
    return T.ficha(t, hoje=hoje)


# ---------------------------------------------------------------- disponibilidade
def test_disponivel_com_terminal_e_sem(raiz, tmp_path_factory, monkeypatch):
    assert T.disponivel() is True
    vazio = tmp_path_factory.mktemp("vazio")
    monkeypatch.setenv("AUTOPILOT_TERMINAL", str(vazio))
    T.limpar_cache()
    assert T.disponivel() is False


def test_sem_terminal_a_ficha_nao_levanta_e_diz_por_que(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_TERMINAL", str(tmp_path / "nao_existe"))
    T.limpar_cache()
    f = T.ficha("PETR4", hoje=HOJE)
    assert f["disponivel"] is False
    secoes = [k for k in f["motivos"]]
    assert set(secoes) >= {"tir", "consenso", "insiders", "aluguel", "noticias", "proximo_resultado", "multiplos"}
    assert all(f[k] is None for k in secoes) and "nao encontrado" in f["motivos"]["tir"]


def test_caminho_do_terminal_vem_da_variavel_de_ambiente(raiz):
    assert str(T.caminho_terminal()) == str(raiz)


# ---------------------------------------------------------------- identidade e estrutura
def test_identidade_e_cobertura(raiz):
    f = ficha()
    assert f["nome"] == "Petrobras PN" and f["classe"] == "acao_br" and f["subsetor"].startswith("Exploracao") and "IBOV" in f["indices"]
    assert f["cobertura"]["total"] == 12 and f["cobertura"]["com_dado"] == 12 and f["motivos"] == {}


def test_todo_pedaco_com_dado_traz_fonte_data_e_idade(raiz):
    f = ficha()
    for k in ("tir", "consenso", "insiders", "aluguel", "noticias", "proximo_resultado", "multiplos", "valuation", "divida", "opcoes", "fundos", "pares"):
        assert f[k]["fonte"] and f[k]["data"] and isinstance(f[k]["idade_dias"], int), k


# ---------------------------------------------------------------- TIR (so a nova, pelo metodo do Safra; a antiga nao e lida desde 19/10/2026)
def test_tir_em_pontos_percentuais_e_premio_sobre_a_ntnb_2035(raiz):
    t = ficha()["tir"]
    assert t["tir_prudente"]["pct"] == 18.39 and t["tir_prudente"]["premio_pp"] == 11.68 and t["fonte_tir"] == "analistas"
    assert t["ntnb"] == {"taxa_pct": 6.71, "vencimento": "2035-05-15", "data": "2026-10-09"} and t["tir_prudente"]["ntnb"] == t["ntnb"]
    assert t["idade_dias"] == 3 and t["data"] == "2026-10-09" and "tir_safra.json" in t["fonte"] and t["gerado"] == "2026-10-12T08:30:00-03:00"
    assert t["ciclo_do_lucro"] == {"nivel": "normal", "marca": None, "codigo": 0}
    assert t["analistas"]["n"] == 13 and t["analistas"]["potencial_pct"] == 4.1 and t["confianca"] == "analistas"
    assert t["avisos"] == ["preco-alvo de 13 casas"] and "tir: preco-alvo de 13 casas" in ficha()["avisos"]
    assert not any(k in t for k in ("tir_hoje_pct", "caixa", "premissas", "tir_antiga"))     # nada do modelo antigo


def test_tir_marca_pico_e_fundo_de_lucro(raiz):
    d = ficha("DIRR3")["tir"]
    assert d["ciclo_do_lucro"]["marca"] == "pico" and d["ciclo_do_lucro"]["codigo"] == 2
    assert d["tir_prudente"]["pct"] == 10.0 and d["tir_prudente"]["base"] == "safra" and d["tir_prudente"]["pico"] is True
    assert d["safra"]["tir_pct"] == 10.1 and d["confianca"] == "alta"
    p = ficha("PRIO3")["tir"]
    assert p["ciclo_do_lucro"]["marca"] == "fundo" and p["ciclo_do_lucro"]["codigo"] == -1
    assert p["tir_prudente"]["premio_pp"] == pytest.approx(15.0 - 6.71)             # sem o campo do premio: TIR menos a NTN-B 2035


def test_tir_fora_do_modelo_ou_so_na_antiga_fica_sem_tir(raiz):
    f = ficha("ENEV3")
    assert f["tir"] is None and "sem preco-alvo" in f["motivos"]["tir"]
    f = ficha("BBAS3")
    assert f["tir"] is None and "nao cobre BBAS3" in f["motivos"]["tir"]
    f = ficha("VALE3")                                                              # tem TIR so no arquivo antigo: o robo nao usa
    assert f["tir"] is None and "nao cobre VALE3" in f["motivos"]["tir"] and "antiga" not in f["motivos"]["tir"]


def test_tir_velha_e_recusada_com_o_motivo(raiz):
    f = ficha(hoje=date(2026, 10, 20))                                             # gerada em 12/10 08h30: 192 h
    assert f["tir"] is None and "TIR recusada" in f["motivos"]["tir"] and "36 h" in f["motivos"]["tir"]
    assert ficha(hoje=date(2026, 10, 13))["tir"] is not None                       # 13/10 9h: 24 h e o ultimo pregao e 09/10 (12/10 e feriado)
    f = T.ficha("PETR4", agora=datetime(2026, 10, 13, 19, 0, tzinfo=FUSO))        # 13/10 depois das 18h: o pregao do dia ja fechou
    assert f["tir"] is None and "antes do fim do ultimo pregao encerrado (13/10, 18h)" in f["motivos"]["tir"]


# ---------------------------------------------------------------- consenso
def test_consenso_e_revisao_do_lucro_com_a_conta_do_terminal(raiz):
    c = ficha()["consenso"]
    assert c["alvo"]["medio"] == 58.31 and c["alvo"]["analistas"] == 13 and c["alvo"]["potencial_pct"] == 4.1
    l = c["lpa_ano_corrente"]
    assert l["medio"] == 14.0 and l["revisao_30d_pct"] == pytest.approx(16.67, abs=0.01) and l["revisao_90d_pct"] == 40.0 and l["revisao_7d_pct"] == 0.0
    assert l["subiram_30d"] == 3 and l["cortaram_30d"] == 1 and l["analistas"] == 4
    assert c["recomendacao"]["pct_compra"] == 92.3 and c["recomendacao"]["pct_compra_ha_3_meses"] == 84.6
    assert c["alvo_desde_o_primeiro_retrato"]["desde"] == "2026-10-01" and c["alvo_desde_o_primeiro_retrato"]["variacao_pct"] == pytest.approx(4.12, abs=0.01)
    assert c["idade_dias"] == 1 and "agregador" in c["fonte"]


def test_consenso_de_bdr_vem_do_lastro_em_dolar_e_avisa(raiz):
    c = ficha("NVDC34")["consenso"]
    assert c["lastro"] == "NVDA" and c["moeda"] == "USD" and c["alvo"]["medio"] == 240.0
    assert any("USD" in a for a in c["avisos"])


def test_consenso_sem_cobertura_e_none_com_o_motivo_do_agregador(raiz):
    f = ficha("DIRR3")
    assert f["consenso"] is None and "analistas" in f["motivos"]["consenso"]


def test_consenso_de_um_ou_dois_analistas_avisa_que_nao_e_consenso(raiz, tmp_path):
    p = tmp_path / "cache" / "out" / "porativo" / "consenso" / "PETR4.json"
    d = json.loads(p.read_text())
    d["alvo"]["n"] = 2
    p.write_text(json.dumps(d))
    T.limpar_cache()
    assert any("nao e consenso" in a for a in ficha()["consenso"]["avisos"])


def test_consenso_velho_vira_none(raiz):
    f = ficha(hoje=date(2026, 10, 17))                                             # coletado em 11/10: 6 dias, limite 4
    assert f["consenso"] is None and "limite de 4" in f["motivos"]["consenso"]


# ---------------------------------------------------------------- insiders
def test_insiders_saldo_em_reais_com_as_contas_feitas_a_mao(raiz):
    i = ficha()["insiders"]
    # janela 14/07 a 31/08. controlador vende 1.000 x 40 (-40.000); diretoria compra 500 x 41 (+20.500); conselho vende 200 x 42 (-8.400).
    # fora da conta: 10/07 (antes da janela), preco 25% longe do fechamento, nao-acao e negocio sem preco.
    assert i["saldo_90d_rs"] == -27900 and i["compras_90d_rs"] == 20500 and i["vendas_90d_rs"] == 48400
    assert i["saldo_gestao_90d_rs"] == 12100 and i["negocios_90d"] == 3
    assert i["por_orgao"]["controlador"]["saldo_rs"] == -40000 and i["por_orgao"]["diretoria"]["saldo_rs"] == 20500
    assert i["formulario_ate"] == "2026-08" and i["data"] == "2026-08-31" and i["idade_dias"] == 42
    assert any("sem preco" in a for a in i["avisos"])
    assert i["janela_efetiva"] == ["2026-07-14", "2026-08-31"]


def test_insiders_velho_vira_none(raiz):
    f = ficha(hoje=date(2026, 12, 1))                                              # fim de agosto + 92 dias, limite 75
    assert f["insiders"] is None and "limite de 75" in f["motivos"]["insiders"]


def test_insiders_so_existe_para_acao_brasileira(raiz):
    f = ficha("NVDA")
    assert f["insiders"] is None and "acao brasileira" in f["motivos"]["insiders"]


# ---------------------------------------------------------------- aluguel
def test_aluguel_taxa_posicao_e_se_a_taxa_e_do_dia(raiz):
    a = ficha()["aluguel"]
    assert a["taxa_aa_pct"] == 0.05 and a["saldo_quantidade"] == 200000000 and a["taxa_calculada_no_dia"] is True
    assert a["var_20d_pct"] == -28.0 and a["pct_float"] == 4.6 and a["saldo_vs_media_21d_pct"] == 0.0
    d = ficha("DIRR3")["aluguel"]
    assert d["taxa_calculada_no_dia"] is False and d["saldo_vs_media_21d_pct"] is None            # sem historico no arquivo: nao inventa
    assert ficha("PRIO3")["aluguel"] is None and "sem saldo alugado" in ficha("PRIO3")["motivos"]["aluguel"]


def test_aluguel_velho_vira_none(raiz):
    assert ficha(hoje=date(2026, 10, 15))["aluguel"] is None


# ---------------------------------------------------------------- noticias
def test_noticias_pontuadas_contagem_e_soma_a_mao(raiz):
    n = ficha()["noticias"]
    # janela de 7 dias a partir de 06/10: a (nota 3, agente), b (2, agente), c (peso 5 -> regra 0), e (do arquivo por ativo, sem nota); z e de setembro
    assert n["n_7d"] == 4 and n["n_pontuadas_7d"] == 3 and n["score_7d"] == 5 and n["max_7d"] == 3
    assert n["n_nota3_7d"] == 1 and n["n_nota2_7d"] == 1 and n["n_pontuadas_pelo_agente_7d"] == 2
    assert [x["nota"] for x in n["principais"]] == [3, 2, 0, None]
    assert n["principais"][0]["titulo"] == "Petrobras sobe" and n["principais"][0]["nota_do_agente"] is True and n["principais"][2]["nota_do_agente"] is False


def test_noticias_ticker_sem_noticia_nao_inventa_score(raiz):
    n = ficha("BBAS3")["noticias"]
    assert n["n_7d"] == 0 and n["score_7d"] is None and n["max_7d"] is None and n["principais"] == []


def test_noticias_arquivo_velho_vira_none(raiz):
    assert ficha(hoje=date(2026, 10, 16))["noticias"] is None


# ---------------------------------------------------------------- resultado e eventos do papel
def test_proximo_resultado_e_reacao_historica(raiz):
    r = ficha()["proximo_resultado"]
    assert r["proximo"]["data"] == "2026-11-10" and r["proximo"]["periodo"] == "3T26" and r["proximo"]["dias_ate"] == 29 and r["proximo"]["confirmado"] is True
    assert r["reacao_historica"]["media_absoluta_pct"] == 3.14 and r["reacao_historica"]["ultimos"][0]["ativo_pct"] == -2.99
    assert r["outros_eventos"][0]["tipo"] == "provento_ex" and r["outros_eventos"][0]["dias_ate"] == 1


def test_momento_do_resultado_e_estimativa_com_confianca(raiz):
    r = ficha()["proximo_resultado"]["proximo"]
    assert r["momento_estimado"] == "ap\u00f3s o fechamento" and r["momento_confianca"] == 1.0 and r["momento_iguais"] == 8 and r["momento_entregas"] == 8
    assert r["momento_origem"] == "estimado pelo hist\u00f3rico de entregas" and r["antes_da_abertura"] is False


def test_antes_da_abertura_true_false_ou_none_pela_confianca(raiz):
    assert ficha("PRIO3")["proximo_resultado"]["proximo"]["antes_da_abertura"] is True                  # antes da abertura, 6 de 8 (0,75)
    assert ficha("DIRR3")["proximo_resultado"]["proximo"]["antes_da_abertura"] is None                  # 3 de 6 (0,5): abaixo de 0,6, sem palpite
    b = ficha("BBAS3")["proximo_resultado"]["proximo"]
    assert b["antes_da_abertura"] is False and b["momento_origem"] == "informado pela companhia"        # informado no comunicado: durante o pregao


def test_papel_sem_nada_no_calendario_e_none(raiz):
    f = ficha("NVDC34")
    assert f["proximo_resultado"] is None and "nenhum evento" in f["motivos"]["proximo_resultado"]


# ---------------------------------------------------------------- multiplos, valuation, divida
def test_multiplos_e_banco_sem_ev_ebitda(raiz):
    m = ficha()["multiplos"]
    assert m["pl"] == 5.41 and m["ev_ebitda"] == 3.98 and m["dl_ebitda"] == 1.14 and m["balanco"]["idade_dias"] == 103 and m["mcap_rs"] == 774311188173
    b = ficha("BBAS3")["multiplos"]
    assert b["pl"] == 9.71 and b["ev_ebitda"] is None and b["dl_ebitda"] is None                  # banco: o terminal nao calcula; fica None


def test_valuation_contra_a_propria_historia(raiz):
    v = ficha()["valuation"]
    assert v["pl"]["percentil_5a"] == 73 and v["pl"]["z_5a"] == 0.35 and v["pvp"]["percentil_5a"] == 97
    assert v["contra_o_setor"]["pl_pct"] == -56.1 and v["contra_o_setor"]["empresas"] == 8


def test_divida_em_reais_e_moeda_nao_aberta_fica_dita(raiz):
    d = ficha()["divida"]
    assert d["divida_liquida_rs"] == 312769000000 and d["dl_ebitda"] == 1.14 and d["custo_pct"] == 7.95 and d["curto_prazo_pct_da_divida"] == 16.5
    assert d["moeda_estrangeira_pct"] is None and "nao abre" in d["moeda_da_divida_nao_aberta"]
    assert d["pares"]["dl_ebitda_mediano"] == 1.74
    b = ficha("BBAS3")
    assert b["divida"] is None and "banco" in b["motivos"]["divida"]


# ---------------------------------------------------------------- opcoes
def test_opcoes_iv_e_a_ultima_com_data_nao_a_de_ontem_disfarcada(raiz):
    o = ficha()["opcoes"]
    iv = o["iv_no_dinheiro"]
    # o ultimo pregao COMPLETO e 08/10 (arquivo e `data`); o resumo desse dia nao trouxe IV, entao vale a de 07/10, dita com a data
    assert o["pregao_completo"] == "2026-10-08" and o["idade_dias"] == 4
    assert iv["pct"] == 32.0 and iv["data"] == "2026-10-07" and iv["idade_dias"] == 5 and iv["vencimento"] == "2026-10-16" and iv["valida"] is True
    assert iv["percentil_historico"] == 50.0 and iv["media_historica_pct"] == 32.5 and iv["pontos_na_historia"] == 4
    assert o["iv_do_dia_no_resumo_pct"] is None and any("volatilidade implicita do dia nao foi calculada" in a for a in o["avisos"])
    assert o["posicao"]["put_call_oi"] == 1.12 and o["no_vencimento_de_referencia"]["dor_maxima_dist_pct"] == -14.98
    assert o["liquidez"]["ofertas_nos_dois_lados"] == 323


def test_opcoes_pregao_incompleto_da_b3_fica_de_fora_e_o_aviso_diz_qual(raiz):
    o = ficha()["opcoes"]
    inc = o["pregao_incompleto_mais_recente"]
    assert inc["data"] == "2026-10-09" and inc["tentativas"] == 3 and "41%" in inc["motivo"]
    assert any("veio incompleto da B3" in a and "2026-10-08" in a for a in o["avisos"]) and any("opcoes: o pregao de 2026-10-09" in a for a in ficha()["avisos"])


def test_opcoes_pregao_incompleto_antigo_ou_resolvido_nao_aparece(raiz, tmp_path):
    p = tmp_path / "cache" / "out" / "deriv" / "opcoes_resumo.json"
    d = json.loads(p.read_text())
    d["incompleto"]["data"] = "2026-10-08"                                         # nao e mais novo que o pregao completo: nada a dizer
    p.write_text(json.dumps(d))
    T.limpar_cache()
    assert ficha()["opcoes"]["pregao_incompleto_mais_recente"] is None


def test_opcoes_sorriso_observado_sem_interpolar(raiz):
    s = ficha()["opcoes"]["sorriso_do_vencimento_de_referencia"]
    # strikes 50,4 (-10,0%) iv 40; 55,9 (-0,2%) iv 31; 58,8 (+5%) iv 30,5; 61,6 (+10,0%) iv 30; o strike de 70 nao tem iv e fica fora
    assert s["atm_pct"] == 31.0 and s["put_10_pct"] == 40.0 and s["call_10_pct"] == 30.0 and s["skew_10_pp"] == 10.0 and s["strikes_com_volatilidade"] == 4
    assert s["vencimento"] == "2026-10-16"


def test_opcoes_iv_velha_nao_vale_mesmo_com_o_arquivo_em_dia(raiz):
    o = ficha(hoje=date(2026, 10, 13))["opcoes"]                                   # arquivo de 08/10: 5 dias (vale); IV de 07/10: 6 dias (nao vale)
    assert o is not None and o["iv_no_dinheiro"]["pct"] is None and "limite de 5" in o["iv_no_dinheiro"]["motivo_descarte"]
    assert ficha(hoje=date(2026, 10, 20))["opcoes"] is None


def test_ativo_sem_opcoes_e_none(raiz):
    assert ficha("DIRR3")["opcoes"] is None


# ---------------------------------------------------------------- fundos e pares
def test_fundos_e_pares(raiz):
    fu = ficha()["fundos"]
    assert fu["fundos"] == 978 and fu["pct_das_acoes_da_classe"] == 7.03 and fu["movimento_no_mes"]["aumentaram_fundos"] == 295
    p = ficha()["pares"]
    assert p["retorno_12d_pct"] == 2.01 and p["pares"][0]["ticker"] == "PRIO3" and p["pares"][0]["retorno_12d_pct"] == -1.0
    assert p["retorno_12d_vs_pares_pp"] == 3.01 and p["janela_retorno"] == ["2026-10-08", "2026-10-09"]


# ---------------------------------------------------------------- nunca inventar nem quebrar
def test_arquivo_em_formato_inesperado_vira_none_com_o_erro_nunca_excecao(raiz, tmp_path):
    (tmp_path / "cache" / "out" / "b3_aluguel.json").write_text(json.dumps({"data": "2026-10-09", "a": {"PETR4": "isto nao e um registro"}}))
    T.limpar_cache()
    f = ficha()
    assert f["aluguel"] is None and "erro ao ler" in f["motivos"]["aluguel"]
    assert f["tir"] is not None                                                    # o resto da ficha segue


def test_arquivo_corrompido_ou_ausente_e_none(raiz, tmp_path):
    (tmp_path / "cache" / "out" / "multiplos.json").write_text("{ quebrado")
    T.limpar_cache()
    f = ficha()
    assert f["multiplos"] is None and "ausente ou vazio" in f["motivos"]["multiplos"]


def test_ticker_fora_do_universo_nao_levanta(raiz):
    f = ficha("XXXX9")
    assert f["nome"] is None and "identidade" in f["motivos"]
    assert all(f[k] is None for k in ("tir", "consenso", "insiders", "aluguel", "multiplos", "valuation", "divida", "opcoes", "fundos", "pares"))


def test_ticker_em_minusculas_e_com_espacos(raiz):
    assert ficha("  petr4 ")["ticker"] == "PETR4" and ficha(" petr4 ")["tir"] is not None


def test_a_ficha_serializa_em_json(raiz):
    assert json.loads(json.dumps(ficha(), default=str))["ticker"] == "PETR4"


def test_cache_acompanha_a_mudanca_do_arquivo(raiz, tmp_path):
    assert ficha()["multiplos"]["pl"] == 5.41
    p = tmp_path / "cache" / "out" / "multiplos.json"
    d = json.loads(p.read_text())
    d["a"]["PETR4"]["pl"] = 9.99
    d["a"]["PETR4"]["avisos"] = ["mudou"]
    p.write_text(json.dumps(d))
    assert ficha()["multiplos"]["pl"] == 9.99                                      # o arquivo mudou (tamanho e hora): o cache nao segura o valor velho


