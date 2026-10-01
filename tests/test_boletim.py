"""Boletim Diario da B3: normalizacao das tabelas, resumo, sinais e render (sem rede).

Os formatos vieram da validacao de 30/09/2026 contra arquivos.b3.com.br/bdi: tabela com
cabecalho de duas linhas, taxa de aluguel como fracao, fluxo acumulado com dois pregoes
de atraso, tabela nao publicada voltando vazia com situacao `aguardando`."""

from __future__ import annotations

from datetime import datetime, timezone

import yaml

from boletim import b3, coleta, render, resumo
from livro import universo

CFG = universo.carregar_yaml("boletim.yaml")
LIVRO = [{"id": "PETR4", "nome": "Petrobras PN", "classe": "acao"},
         {"id": "MRVE3", "nome": "MRV ON", "classe": "acao"},
         {"id": "SMAL11", "nome": "iShares Small Cap", "classe": "etf"}]
D = "2026-09-29"


def tab(nome, colunas, linhas, situacao="publicado", texto=None, filhos=None):
    t = {"nome": nome, "titulo": nome, "sla": "20:00:00", "paginas": 1, "situacao": situacao,
         "atualizado_em": f"{D}T21:00:00", "truncada": False, "texto": texto or [],
         "colunas": [{"nome": c, "titulo": c} for c in colunas], "linhas": linhas}
    if filhos:
        t["filhos"] = filhos
    return t


def trade(tk, seg, fech, osc, vol, qtd=1000, neg=10, **extra):
    r = {"RptDt": D, "TckrSymb": tk, "ISIN": f"BR{tk[:4]}ACNXX0", "SgmtNm": seg, "MinPric": str(fech), "MaxPric": str(fech),
         "TradAvrgPric": str(fech), "LastPric": str(fech).replace(".", ","), "OscnPctg": str(osc).replace(".", ","),
         "AdjstdQt": "", "AdjstdQtTax": "", "RefPric": "", "TradQty": str(neg), "FinInstrmQty": str(qtd), "NtlFinVol": str(vol)}
    r.update(extra)
    return r


def bruto(tabelas=None, arquivos=None, falhas=None):
    tabelas = tabelas or {}
    return {"pregao": D, "status": {"situacao": "publicado", "atualizado_em": f"{D}T22:00:00", "completo": {"pdf": "https://x/BDI_00.pdf"}},
            "tabelas": tabelas, "arquivos": arquivos or {}, "informativos": [],
            "index": {"tabelas": {}, "arquivos": {k: {"estado": "Final"} for k in (arquivos or {})}, "falhas": falhas or {}}}


def historico(n=12, vol=100e6, alug=50e6, fech=10.0):
    return {"pregoes": {f"2026-09-{d:02d}": {"ativos": {"PETR4": {"fech": fech, "vol": vol, "qtd": 1e6, "alug": alug}}}
                        for d in range(1, n + 1)}}


# ------------------------------------------------------------------ b3.py

def test_normalizar_tira_coluna_de_grupo_e_leva_o_grupo_para_o_titulo():
    bruta = {"name": "BTBLoanBalance", "friendlyNamePt": "Empréstimos registrados", "pageCount": 3,
             "configuration": {"SLA": "8:00:00"}, "texts": [{"textPt": "linha  um\r\nlinha dois"}],
             "columns": [{"id": 1, "name": "TckrSymb", "friendlyNamePt": "Código IF"},
                         {"id": 2, "name": "TkrAvrgRate", "friendlyNamePt": "Média ponderada", "parentId": 17},
                         {"id": 3, "name": "RptDt ", "friendlyNamePt": "Data"},
                         {"id": 17, "name": "Tkr", "friendlyNamePt": "Taxa tomador", "isGroup": True}],
             "values": [["MRVE3", 0.1287, "2026-09-29T00:00:00", None, None]]}
    t = b3.normalizar(bruta)
    assert [c["nome"] for c in t["colunas"]] == ["TckrSymb", "TkrAvrgRate", "RptDt"]
    assert t["colunas"][1]["titulo"] == "Taxa tomador: Média ponderada"
    assert t["linhas"] == [["MRVE3", 0.1287, "2026-09-29"]]
    assert t["paginas"] == 3 and t["sla"] == "8:00:00" and t["texto"] == ["linha um linha dois"]
    assert b3.registros(t)[0]["TkrAvrgRate"] == 0.1287


def test_normalizar_guarda_filhos_e_filho_acha_em_qualquer_nivel():
    bruta = {"name": "INDEXES", "columns": [], "values": [], "children": [
        {"name": "IBOVESPA", "columns": [], "values": [], "children": [
            {"name": "IbovespaDayBehavior", "columns": [{"id": 1, "name": "LastPric", "friendlyNamePt": "Fechamento"}],
             "values": [[183827, None]]}]}]}
    t = b3.normalizar(bruta)
    assert b3.filho(t, "IbovespaDayBehavior")["linhas"] == [[183827]]
    assert [f["nome"] for f in b3.folhas(t)] == ["IbovespaDayBehavior"]


def test_csv_da_api_numero_brasileiro_e_estado_do_arquivo():
    antes, regs = b3.ler_csv("Status do Arquivo: Final\nRptDt;TckrSymb;LastPric\n2026-09-29;DOLV26;5215,253\n")
    assert antes == ["Status do Arquivo: Final"] and regs[0]["TckrSymb"] == "DOLV26"
    assert b3.num(regs[0]["LastPric"]) == 5215.253
    assert b3.num("") is None and b3.num("=") == 0.0 and b3.num(7) == 7


def test_chave_empresa_casa_o_nome_do_cadastro_com_o_da_custodia():
    assert b3.chave_empresa("PETROLEO BRASILEIRO S.A. PETROBRAS") == b3.chave_empresa("PETROLEO BRASILEIRO S/A PETROBRAS")
    assert b3.chave_empresa("VALE S.A.") == "VALE"


def test_tabela_em_texto_tem_uma_linha_por_registro_e_volta_igual():
    import json
    t = tab("IOPV", ["TckrSymb", "Closing"], [["SMAL", 109.83], ["BOVA", 180.95]],
            filhos=[tab("Filha", ["A"], [[1]])])
    texto = coleta.texto_tabela(t)
    assert json.loads(texto) == t
    assert texto.count("\n") < 40


# ------------------------------------------------------------------ resumo.py

def test_volume_anormal_so_com_base_minima_e_usa_a_media_do_historico():
    arqs = {"TradeInformationConsolidated": [trade("PETR4", "CASH", 49.10, 0.77, 300e6)]}
    r = resumo.montar(bruto(arquivos=arqs), CFG, LIVRO, historico(12))
    g = r["ativos"]["PETR4"]["negocios"]
    assert g["volume_x_media"] == 3.0 and g["pregoes_na_media"] == 12
    assert [s["tipo"] for s in r["sinais"] if s["ativo"] == "PETR4"] == ["volume_anormal"]
    assert "3,0x a média de 12 pregões" in r["sinais"][0]["texto"]
    curto = resumo.montar(bruto(arquivos=arqs), CFG, LIVRO, historico(4))
    assert "volume_x_media" not in curto["ativos"]["PETR4"]["negocios"] and not curto["sinais"]


def test_aluguel_taxa_vira_percentual_e_saldo_alto_com_preco_subindo_avisa():
    tabelas = {
        "BTBLendingOpenPosition": tab("BTBLendingOpenPosition", ["TckrSymb", "Market", "StockBalance", "Balance"],
                                      [["MRVE3", "Registro", 60e6, 300e6], ["MRVE3", "Total", 65e6, 330e6]]),
        "BTBLoanBalance": tab("BTBLoanBalance", ["TckrSymb", "Market", "QtyCtrctsDay", "ValCtrctsDay", "BRLValue", "DnrAvrgRate", "TkrAvrgRate", "TkrMaxRate"],
                              [["MRVE3", "Registro", 154, 2436771, 12695576.91, 0.1287, 0.1287, 0.1406]]),
        "PreviaQuadrimestral": tab("PreviaQuadrimestral", [], [], texto=["Para Setembro a Dezembro de 2026"], filhos=[
            tab("OficialWalletIbovespa", ["TckrSymb", "QtyTheoretical", "StockParticipation"], [["MRVE3", 375e6, 0.12]])]),
    }
    arqs = {"TradeInformationConsolidated": [trade("MRVE3", "CASH", 5.38, 3.26, 45e6, qtd=8.5e6)]}
    hist = {"pregoes": {f"2026-09-{d:02d}": {"ativos": {"MRVE3": {"fech": 5.0, "alug": 64e6, "qtd": 8.5e6}}} for d in range(20, 27)}}
    r = resumo.montar(bruto(tabelas, arqs), CFG, LIVRO, hist)
    a = r["ativos"]["MRVE3"]["aluguel"]
    assert a["taxa_tomador_media"] == 12.87 and a["saldo_qtd"] == 65e6
    assert a["pct_free_float"] == 17.33 and a["novos_contratos"] == 154
    assert a["var_dia_pct"] == 1.56 and a["pregoes_para_cobrir"] == 7.6
    s = next(s for s in r["sinais"] if s["tipo"] == "aluguel_alto")
    assert "17,3% da quantidade teórica" in s["texto"] and "12,87% ao ano" in s["texto"] and "forçado a recomprar" in s["texto"]
    assert r["carteira_vigencia"] == "Para Setembro a Dezembro de 2026"


def test_fluxo_tira_o_saldo_do_dia_da_diferenca_entre_dois_acumulados():
    linhas = [["Investidor Estrangeiro", 395618061, 31.16, 386048230, 30.41], ["Institucionais", 151962677, 11.97, 159633925, 12.57]]
    tabelas = {"SharesInvesVolum": tab("SharesInvesVolum", ["TckrSymb", "Purchase", "Sales", "Partmil", "PartPer"], linhas,
                                       texto=["Dados acumulados do início do mês até o dia 28/09/2026."])}
    hist = {"pregoes": {"2026-09-28": {"fluxo": {"ate": "2026-09-25", "saldo": {"estrangeiro": 9428.4, "institucional": -7646.2}}}}}
    f = resumo.montar(bruto(tabelas), CFG, LIVRO, hist)["fluxo"]
    assert f["ate"] == "2026-09-28" and f["fonte"]["data"] == "2026-09-28"
    assert f["acumulado_no_mes"]["estrangeiro"]["saldo_mi"] == 9569.8
    assert f["periodo"]["saldo_mi"]["estrangeiro"] == 141.4
    assert f["periodo"]["de"] == "2026-09-28" == f["periodo"]["ate"]        # um pregao so: o seguinte ao acumulado anterior
    # virada de mes: o acumulado novo ja e o saldo desde o dia 1
    hist = {"pregoes": {"2026-09-28": {"fluxo": {"ate": "2026-08-31", "saldo": {"estrangeiro": 5000.0}}}}}
    f = resumo.montar(bruto(tabelas), CFG, LIVRO, hist)["fluxo"]
    assert f["periodo"]["saldo_mi"]["estrangeiro"] == 9569.8 and f["periodo"]["de"] == "2026-09-01"


def test_tabela_aguardando_vira_pendente_e_atrasada_com_linha_vale():
    tabelas = {
        "BTBLendingOpenPosition": tab("BTBLendingOpenPosition", ["TckrSymb", "Market", "StockBalance", "Balance"], [], situacao="aguardando"),
        "AnalyticalFramework2": tab("AnalyticalFramework2", ["DateRef", "TckrSymb", "Asst", "OpnIntrst", "RefValue"],
                                    [[D, "Dólar Comercial - futuro", "DOL", 1307825, 341877277.19]], situacao="atrasado"),
    }
    r = resumo.montar(bruto(tabelas, falhas={"BTBLoanBalance": "HTTP 500",
                                             "DerivativesOpenPosition": "arquivo DerivativesOpenPosition: token HTTP 400"}),
                      CFG, LIVRO, {})
    sit = r["situacao"]
    assert sit["pendentes"]["BTBLendingOpenPosition"] == "aguardando"
    assert sit["pendentes"]["BTBLoanBalance"].startswith("falhou: HTTP 500")
    # a API de download responde 400 enquanto a B3 nao libera o arquivo da madrugada: e espera, nao erro
    assert sit["pendentes"]["DerivativesOpenPosition"] == "aguardando" and "DerivativesOpenPosition" in sit["faltam"]
    assert sit["publicadas_com_atraso"] == ["AnalyticalFramework2"] and not sit["completo"]
    assert "BTBLendingOpenPosition" in sit["faltam"] and "AnalyticalFramework2" not in sit["faltam"]
    assert r["derivativos"]["quadro"]["DOL"]["contratos"] == 1307825
    assert "aluguel" not in r["ativos"]["PETR4"]


def test_parede_de_opcoes_ignora_semanal_vazia_e_da_um_sinal_por_ativo():
    cad = [{"TckrSymb": "PETR4", "SgmtNm": "CASH", "Asst": "PETR", "ISIN": "BRPETRACNPR6", "CrpnNm": "PETROLEO BRASILEIRO S.A. PETROBRAS",
            "SpcfctnCd": "PN      N2", "SctyCtgyNm": "SHARES", "MktCptlstn": "5446501379"}]
    pos = []
    for cod, tipo, venc, strike, oi in (("PETRJ1", "Call", "2026-10-02", "49,5", 50), ("PETRJ2", "Call", "2026-10-09", "50", 900000),
                                         ("PETRV1", "Put", "2026-10-09", "48", 600000), ("PETRK1", "Call", "2026-11-19", "55", 400000),
                                         ("PETRV2", "Put", "2026-10-09", "44", 500000)):
        cad.append({"TckrSymb": cod, "Asst": "PETR4", "SgmtNm": "EQUITY CALL" if tipo == "Call" else "EQUITY PUT",
                    "SctyCtgyNm": "OPTION ON EQUITIES", "XprtnDt": venc, "ExrcPric": strike, "OptnStyle": "AMER"})
        pos.append({"RptDt": D, "TckrSymb": cod, "TtlPos": str(oi)})
    arqs = {"TradeInformationConsolidated": [trade("PETR4", "CASH", 49.10, 0.77, 1e9)],
            "InstrumentsConsolidated": cad, "DerivativesOpenPosition": pos}
    r = resumo.montar(bruto(arquivos=arqs), CFG, LIVRO, {})
    o = r["ativos"]["PETR4"]["opcoes"]
    assert [v["vencimento"] for v in o["vencimentos"]] == ["2026-10-09", "2026-11-19"]      # a semanal de 02/10 ficou de fora
    assert o["vencimentos"][0]["parede_call"] == {"strike": 50.0, "posicao": 900000.0, "distancia_pct": 1.83}
    assert o["put_call"] == 0.85
    sinais = [s for s in r["sinais"] if s["tipo"] == "opcoes_parede"]
    # a put de 48 esta a 2,2% do preco e entra; a de 44 (10% abaixo) e parede, mas longe demais para virar sinal
    assert len(sinais) == 1 and "call em 50,00" in sinais[0]["texto"] and "put em 48,00" in sinais[0]["texto"]
    assert sinais[0]["numeros"]["dias_uteis"] == 8 and "a 8 dias úteis" in sinais[0]["texto"]


def test_etf_premio_sobre_a_cota_e_lacuna_quando_a_b3_nao_publica_iopv():
    tabelas = {"IOPV": tab("IOPV", ["TckrSymb", "Closing"], [["SMAL", 109.0]])}
    livro = LIVRO + [{"id": "RARA11", "nome": "Investo Terras Raras", "classe": "etf"}]
    arqs = {"TradeInformationConsolidated": [trade("SMAL11", "CASH", 109.65, 0.59, 2e8), trade("RARA11", "CASH", 15.10, 0.19, 4e5)]}
    r = resumo.montar(bruto(tabelas, arqs), CFG, livro, {})
    assert r["ativos"]["SMAL11"]["etf"]["premio_pct"] == 0.6
    assert any(s["tipo"] == "etf_premio" and s["ativo"] == "SMAL11" for s in r["sinais"])
    assert any("RARA11" in x and "IOPV" in x for x in r["lacunas"])


def test_sinal_repetido_conta_os_pregoes_seguidos():
    arqs = {"TradeInformationConsolidated": [trade("PETR4", "CASH", 49.10, 0.77, 300e6)]}
    hist = historico(12)
    hist["pregoes"]["2026-09-11"]["sinais"] = ["volume_anormal|PETR4"]
    hist["pregoes"]["2026-09-12"]["sinais"] = ["volume_anormal|PETR4"]
    r = resumo.montar(bruto(arquivos=arqs), CFG, LIVRO, hist)
    assert r["sinais"][0]["pregoes_seguidos"] == 3
    assert "volume_anormal|PETR4" in resumo.entrada_historico(r)["sinais"]


def test_rodada_parcial_nao_apaga_o_que_a_final_gravou():
    final = {"pregoes": {D: {"ativos": {"PETR4": {"fech": 49.1, "alug": 194e6, "opc": [1, 2]}}, "futuros": {}, "quadro": {"DOL": 10},
                             "indices": {}, "indicadores": {}, "sinais": ["aluguel_alto|PETR4"], "completo": True}}}
    arqs = {"TradeInformationConsolidated": [trade("PETR4", "CASH", 49.10, 0.77, 300e6)]}
    parcial = resumo.montar(bruto(arquivos=arqs), CFG, LIVRO, final)
    h = resumo.atualizar_historico(final, parcial)["pregoes"][D]
    assert h["ativos"]["PETR4"]["alug"] == 194e6 and h["ativos"]["PETR4"]["vol"] == 300e6
    assert h["quadro"] == {"DOL": 10} and h["completo"] is True and "aluguel_alto|PETR4" in h["sinais"]


def test_historico_guarda_so_a_janela():
    h = {"pregoes": {f"2026-01-{d:02d}": {} for d in range(1, 29)}}
    r = resumo.montar(bruto(), CFG, LIVRO, h)
    assert len(resumo.atualizar_historico(h, r, manter=10)["pregoes"]) == 10


def test_lacuna_fixa_da_posicao_por_investidor_esta_sempre_declarada():
    r = resumo.montar(bruto(), CFG, LIVRO, {})
    assert any("por tipo de investidor" in x and "não existe" in x for x in r["lacunas"])


def test_carteira_de_indice_vale_a_ultima_quando_a_b3_publica_vazia():
    cheia = {"PreviaQuadrimestral": tab("PreviaQuadrimestral", [], [], texto=["Para Setembro a Dezembro de 2026"], filhos=[
        tab("OficialWalletIbovespa", ["TckrSymb", "QtyTheoretical", "StockParticipation"], [["PETR4", 4410957710, 7.9991]])])}
    r1 = resumo.montar(bruto(cheia), CFG, LIVRO, {})
    hist = resumo.atualizar_historico({}, r1)
    assert hist["carteira"]["ativos"]["PETR4"]["pesos_pct"] == {"IBOV": 7.9991} and hist["carteira"]["data"] == D
    vazia = bruto({"PreviaQuadrimestral": tab("PreviaQuadrimestral", [], [])})
    vazia["pregao"] = "2026-09-30"
    r2 = resumo.montar(vazia, CFG, LIVRO, hist)
    assert r2["ativos"]["PETR4"]["indice"]["quantidade_teorica"] == 4410957710 and r2["carteira_data"] == D
    assert any("valem os pesos de 29/09" in x for x in r2["lacunas"])
    assert resumo.atualizar_historico(hist, r2)["carteira"]["data"] == D


# ------------------------------------------------------------------ render.py e config

def test_render_tem_marcador_tabelas_de_ate_4_colunas_e_numero_brasileiro():
    arqs = {"TradeInformationConsolidated": [trade("PETR4", "CASH", 49.10, 0.77, 1162760321)]}
    md = render.markdown(resumo.montar(bruto(arquivos=arqs), CFG, LIVRO, historico(12)))
    assert "[[LEITURA_DA_MESA]]" in md and "pregão de 29/09/2026 (terça)" in md
    assert "| PETR4 | 49,10 | +0,77% | 1.163 (11,63x) |" in md
    assert "**Situação: PARCIAL.**" in md and "saldo de aluguel" in md
    for linha in md.splitlines():
        if linha.startswith("|"):
            assert linha.count("|") <= 5, linha


def test_grupos_e_paridades_do_boletim_so_citam_ativos_do_livro():
    b3_do_livro = {a.id for a in universo.carregar().ativos if a.mercado == "B3"}
    citados = {tk for tks in CFG["grupos"].values() for tk in tks} | {p["ativo"] for p in CFG["paridades"]}
    assert citados <= b3_do_livro, citados - b3_do_livro
    assert b3_do_livro <= {tk for tks in CFG["grupos"].values() for tk in tks}, "ativo B3 do livro sem grupo"


# ------------------------------------------------------------------ workflow e entrada

def _workflow():
    wf = yaml.safe_load(open(".github/workflows/boletim-b3.yml", encoding="utf-8"))
    return wf, wf.get("on", wf.get(True))       # YAML 1.1 le `on` como True


def test_workflow_nunca_manda_pdf_para_o_branch_dados():
    txt = open(".github/workflows/boletim-b3.yml", encoding="utf-8").read()
    assert "--pdf pdf_artefato" in txt and "--pdf dados_branch" not in txt
    assert "path: pdf_artefato" in txt and "':!boletim_b3/**/*.pdf'" in txt


def test_agendamento_quando_ligado_e_noite_do_pregao_e_manha_seguinte():
    _, gatilhos = _workflow()
    crons = [c["cron"] for c in gatilhos.get("schedule") or []]
    assert crons in ([], ["40 0 * * 2-6", "35 11 * * 2-6"]), crons


def test_pregao_padrao_e_o_ultimo_fechado():
    import boletim_b3
    utc = lambda dia, h, m: datetime(2026, 9, dia, h, m, tzinfo=timezone.utc)      # noqa: E731
    assert boletim_b3.pregao_padrao(utc(30, 21, 0)).isoformat() == "2026-09-29"      # 18h00 BRT: ainda nao fechou
    assert boletim_b3.pregao_padrao(utc(30, 23, 0)).isoformat() == "2026-09-30"      # 20h00 BRT
    assert boletim_b3.pregao_padrao(datetime(2026, 10, 1, 0, 40, tzinfo=timezone.utc)).isoformat() == "2026-09-30"   # cron da noite
    assert boletim_b3.pregao_padrao(datetime(2026, 10, 1, 11, 35, tzinfo=timezone.utc)).isoformat() == "2026-09-30"  # cron da manha
    assert boletim_b3.pregao_padrao(utc(28, 14, 0)).isoformat() == "2026-09-25"      # segunda de manha -> sexta
    assert [d.isoformat() for d in boletim_b3.pregoes(boletim_b3.date(2026, 9, 8), 2)] == ["2026-09-04", "2026-09-08"]  # pula o 7 de setembro


def test_mesa_boletim_veredito_atual_velho_e_ausente():
    import mesa
    res = {"pregao": "2026-09-30", "gerado_em": "2026-10-01T00:45:00Z", "sinais": [1, 2],
           "situacao": {"completo": False, "faltam": ["BTBLendingOpenPosition"]}}
    agora = datetime(2026, 10, 1, 1, 0, tzinfo=timezone.utc)        # 22h00 BRT de 30/09
    linha, ok = mesa.veredito_boletim({"ultimo_pregao": "2026-09-30"}, res, agora)
    assert ok and "ATUAL" in linha and "PARCIAL (falta: BTBLendingOpenPosition)" in linha and "2 sinais" in linha
    linha, ok = mesa.veredito_boletim({}, dict(res, pregao="2026-09-28"), agora)
    assert not ok and "AUSENTE" in linha
    linha, ok = mesa.veredito_boletim({"ultimo_pregao": "2026-09-28"}, dict(res, pregao="2026-09-28"), agora)
    assert not ok and "VELHO (esperado 2026-09-30)" in linha


# ------------------------------------------------------------------ renda fixa (boletim/renda_fixa.py)

from boletim import mercado, painel, renda_fixa        # noqa: E402


def neg_rf(tipo, cod, emissor, qtd, vol, taxa, situacao="Confirmado"):
    return [D, D, tipo, emissor, cod, qtd, vol / qtd, vol, taxa, "Pre-registro - Voice", "10:00:00", D, "#1", "BRX", D, situacao, 1]


COLS_TRADE = ["RptDt", "DtRef", "InstrumentType", "Issuer", "TckrSymb", "Quantity", "Price", "Vol", "Rate", "Origin", "TradeTime",
              "TradeDate", "TradeCode", "ISIN", "SettlementDt", "Situation", "IdSer"]
CADASTRO = {
    "AESLD2": {"tipo": "DEB", "incentivada": True, "indexador": "IPCA", "pct_indexador": None, "taxa": 6.45, "vencimento": "2036-03-15"},
    "CSNAA2": {"tipo": "DEB", "incentivada": False, "indexador": "DI", "pct_indexador": 100, "taxa": 2.5, "vencimento": "2027-12-20"},
    "24H1684874": {"tipo": "CRI", "incentivada": False, "indexador": "DI", "pct_indexador": 97.5, "taxa": 0, "vencimento": "2029-08-17"},
    "CRA02300V6A": {"tipo": "CRA", "incentivada": False, "indexador": "DI", "pct_indexador": 100, "taxa": 1.6, "vencimento": "2029-11-22"},
    "RISP24": {"tipo": "DEB", "incentivada": True, "indexador": "IPCA", "pct_indexador": None, "taxa": 7.69, "vencimento": "2042-09-15"},
}


def bruto_rf(linhas, dap=((2028, "Q", "7,385"), (2031, "K", "7,63"), (2035, "K", "7,44"))):
    trades = [trade(f"DAP{letra}{str(ano)[2:]}", "FINANCIAL", 0, 0, 1e6, AdjstdQtTax=taxa) for ano, letra, taxa in dap]
    b = bruto({"Trade": tab("Trade", COLS_TRADE, linhas)}, {"TradeInformationConsolidated": trades})
    b["rf_cadastro"] = dict(CADASTRO)
    return b


def test_renda_fixa_classifica_le_a_taxa_pela_convencao_e_mede_o_premio_sobre_o_dap():
    linhas = [neg_rf("DEB", "AESLD2", "RGE SUL DISTRIBUIDORA DE ENERGIA S/A", 30000, 30e6, 7.80),
              neg_rf("DEB", "AESLD2", "RGE SUL DISTRIBUIDORA DE ENERGIA S/A", 10000, 10e6, 7.84),
              neg_rf("DEB", "CSNAA2", "COMPANHIA SIDERURGICA NACIONAL", 5000, 5e6, 17.56),
              neg_rf("CRI", "24H1684874", "RIZA SECURITIZADORA S.A.", 2000, 2e6, 98.16),
              neg_rf("CRA", "CRA02300V6A", "ECO SECURITIZADORA", 100, 170e6, 1.6),
              neg_rf("DEB", "XPTO11", "EMISSOR SEM CADASTRO", 10, 1e6, 8.0),
              neg_rf("DEB", "AESLD2", "RGE SUL DISTRIBUIDORA DE ENERGIA S/A", 99999, 99e6, 1.0, situacao="Cancelado B3"),
              neg_rf("COE", "COE1", "BANCO X", 1, 9e9, None)]
    r = resumo.montar(bruto_rf(linhas), CFG, LIVRO, {})
    rf = r["renda_fixa"]
    assert set(rf["resumo"]) == {"deb_incentivada", "deb_comum", "cri", "cra", "deb_sem_cadastro"}
    inc = rf["resumo"]["deb_incentivada"]
    assert inc["volume_rs"] == 40e6 and inc["negocios"] == 2 and inc["taxa_ipca_media"] == 7.81     # cancelado e COE ficam fora
    aes = rf["papeis"]["deb_incentivada"][0]
    assert aes["codigo"] == "AESLD2" and aes["convencao"] == "IPCA+" and aes["taxa_media"] == 7.81 and aes["prazo_anos"] == 9.46
    # DAP: 7,63% em mai/31 (4,62 anos) e 7,44% em mai/35 (8,62 anos); o papel vence alem do ultimo vertice -> 7,44%
    assert aes["premio_dap_pb"] == 37
    assert rf["papeis"]["cri"][0]["convencao"] == "% do CDI" and rf["papeis"]["cra"][0]["convencao"] == "CDI+"
    assert rf["resumo"]["deb_comum"]["premio_cdi_medio"] == 17.56
    assert rf["cobertura_cadastro_pct"] == 99.5 and rf["papeis_negociados"] == 5
    assert [m["codigo"] for m in rf["maiores_negocios"]][:2] == ["CRA02300V6A", "AESLD2"]
    assert "_linhas" not in rf and "AESLD2" in r["_apoio"]["rf_linhas"]
    # a tabela do teste foi atualizada as 21h do proprio pregao: a B3 ainda vai ajustar em D+1
    assert rf["preliminar"] is True
    b = bruto_rf(linhas)
    b["tabelas"]["Trade"]["atualizado_em"] = "2026-09-30T11:57:22"
    assert resumo.montar(b, CFG, LIVRO, {})["renda_fixa"]["preliminar"] is False


def test_renda_fixa_mede_abertura_de_taxa_contra_o_ultimo_negocio_visto_e_avisa():
    linhas = [neg_rf("DEB", "AESLD2", "RGE SUL DISTRIBUIDORA DE ENERGIA S/A", 30000, 30e6, 8.21),
              neg_rf("DEB", "RISP24", "AGUAS DO RIO 1 SPE S.A", 20000, 27e6, 12.06)]
    estado = {"AESLD2": [["2026-09-25", 7.70, 1000.0], ["2026-09-28", 7.81, 1001.0], ["2026-09-29", 9.99, 1.0]]}
    r = resumo.montar(bruto_rf(linhas), CFG, LIVRO, {}, rf_estado=estado)
    rf = r["renda_fixa"]
    ab = rf["aberturas"][0]
    assert ab["codigo"] == "AESLD2" and ab["var_taxa_pb"] == 40 and ab["comparado_com"] == "2026-09-28"     # nunca contra o proprio dia
    tipos = {s["tipo"]: s for s in r["sinais"]}
    assert "abriu 40 pb contra 28/09" in tipos["rf_abertura"]["texto"] and "IPCA+ 8,21%" in tipos["rf_abertura"]["texto"]
    assert tipos["rf_abertura"]["fonte"] == "Trade + InstrumentRegistration (preliminar)"
    assert rf["premios_altos"][0]["codigo"] == "RISP24" and rf["premios_altos"][0]["premio_dap_pb"] == 462
    assert "462 pb acima do juro real" in tipos["rf_premio_alto"]["texto"]
    novo = renda_fixa.atualizar_estado(estado, {"_linhas": r["_apoio"]["rf_linhas"]}, D)
    assert [x[0] for x in novo["AESLD2"]] == ["2026-09-25", "2026-09-28", "2026-09-29"] and novo["AESLD2"][-1][1] == 8.21
    assert novo["RISP24"] == [[D, 12.06, 1350.0]]
    velho = renda_fixa.atualizar_estado({"SUMIU11": [["2026-06-01", 7.0, 1.0]]}, {"_linhas": {}}, D)
    assert velho == {}                                                                                 # papel que nao negocia ha 75 dias sai


def test_dap_curto_fica_fora_e_a_interpolacao_e_chata_nas_pontas():
    from datetime import date
    t = {f"DAP{l}{a}": {"AdjstdQtTax": tx} for l, a, tx in (("K", "27", "5,75"), ("Q", "28", "7,385"), ("K", "31", "7,63"))}
    c = renda_fixa.curva_dap(t, date(2026, 9, 29))
    assert [p[2] for p in c] == ["DAPQ28", "DAPK31"]                # mai/27 esta a menos de um ano
    assert renda_fixa.interpolar(c, 0.5) == 7.385 and renda_fixa.interpolar(c, 30) == 7.63
    assert round(renda_fixa.interpolar(c, (c[0][0] + c[1][0]) / 2), 4) == 7.5075
    assert renda_fixa.interpolar(c[:1], 3) is None


def test_cadastro_de_renda_fixa_so_consulta_o_que_falta_e_reve_o_sem_cadastro(monkeypatch):
    from datetime import date
    pedidos = []

    def falso(cli, cod, d):
        pedidos.append(cod)
        return None if cod == "XPTO11" else {"tipo": "DEB", "incentivada": True, "indexador": "IPCA", "pct_indexador": None,
                                              "taxa": 6.0, "vencimento": "2035-01-15"}
    monkeypatch.setattr(coleta.b3, "cadastro_balcao", falso)
    monkeypatch.setattr(coleta, "Cliente", lambda: object())
    t = tab("Trade", COLS_TRADE, [neg_rf("DEB", "AESLD2", "A", 10, 5e6, 7.8), neg_rf("DEB", "XPTO11", "B", 10, 9e6, 8.0),
                                   neg_rf("CRI", "JA_TEM", "C", 10, 1e6, 1.0)])
    cache = {"JA_TEM": {"tipo": "CRI", "visto_em": "2026-09-01"}}
    info = coleta.cadastros_rf(date(2026, 9, 29), t, cache, fios=1)
    assert pedidos == ["XPTO11", "AESLD2"]                          # do maior volume para o menor; o que ja tem nao e pedido
    assert info["achados"] == 1 and info["sem_cadastro"] == 1 and cache["XPTO11"]["sem_cadastro"] and cache["AESLD2"]["visto_em"] == D
    pedidos.clear()
    coleta.cadastros_rf(date(2026, 10, 2), t, cache, fios=1)
    assert pedidos == []                                            # sem cadastro ha 3 dias: ainda nao tenta de novo
    coleta.cadastros_rf(date(2026, 10, 12), t, cache, fios=1)
    assert pedidos == ["XPTO11"]
    assert json_ok(coleta.texto_cadastro(cache)) == cache


def json_ok(texto):
    import json
    return json.loads(texto)


def test_filtro_da_tabela_vai_em_base64_e_maiusculas():
    class Falso:
        def __init__(self):
            self.urls = []

        def post(self, url, **kw):
            self.urls.append(url)
            from livro.http import Resposta
            import json
            return Resposta(200, json.dumps({"status": 4, "lastUpdateDate": "x", "table": {"name": "T", "columns": [], "values": [], "pageCount": 0}}).encode())
    from datetime import date
    cli = Falso()
    b3.tabela(cli, "InstrumentRegistration", date(2026, 9, 29), filtro="brku11")
    assert cli.urls == ["https://arquivos.b3.com.br/bdi/table/InstrumentRegistration/2026-09-29/2026-09-29/1/1000?filter=QlJLVTEx"]


# ------------------------------------------------------------------ mercado inteiro (boletim/mercado.py)

def test_serie_do_mercado_rodada_parcial_nao_apaga_aluguel_e_a_janela_corta():
    m = mercado.atualizar({}, "2026-09-28", {"PETR4": (48.7, 1000, 190000)}, {"PETR4": 4.4e9})
    m = mercado.atualizar(m, "2026-09-29", {"PETR4": (49.1, 1163, 194000), "MRVE3": (5.38, 45, 65000)}, {})
    m = mercado.atualizar(m, "2026-09-29", {"PETR4": (49.1, 1163, None)}, {})            # rodada parcial repetida
    assert m["datas"] == ["2026-09-28", "2026-09-29"] and m["teorica"] == {"PETR4": 4.4e9}
    assert m["ativos"]["PETR4"] == {"f": [48.7, 49.1], "v": [1000, 1163], "a": [190000, 194000]}
    assert m["ativos"]["MRVE3"]["a"] == [None, 65000]
    datas, cols = mercado.colunas(m, "2026-09-29")
    assert datas == ["2026-09-28"] and cols["PETR4"]["v"] == [1000]
    for d in range(1, 29):
        m = mercado.atualizar(m, f"2026-10-{d:02d}", {"PETR4": (50.0, 1, 1)}, {}, manter=5)
    assert len(m["datas"]) == 5 and len(m["ativos"]["PETR4"]["f"]) == 5 and "MRVE3" not in m["ativos"]


def test_radar_acha_volume_anormal_aluguel_alto_e_vendido_pressionado():
    tabelas = {
        "BTBLendingOpenPosition": tab("BTBLendingOpenPosition", ["TckrSymb", "Market", "StockBalance", "Balance"],
                                      [["MRVE3", "Total", 75e6, 400e6], ["PETR4", "Total", 194e6, 9.3e9], ["XPTO3", "Total", 1e6, 5e6]]),
        "BTBLoanBalance": tab("BTBLoanBalance", ["TckrSymb", "Market", "QtyCtrctsDay", "ValCtrctsDay", "BRLValue", "DnrAvrgRate", "TkrAvrgRate", "TkrMaxRate"],
                              [["MRVE3", "Registro", 10, 1e6, 5e6, 0.19, 0.1904, 0.2]]),
        "PreviaQuadrimestral": tab("PreviaQuadrimestral", [], [], filhos=[
            tab("OficialWalletIbra", ["TckrSymb", "QtyTheoretical", "StockParticipation"], [["MRVE3", 375e6, 0.07], ["PETR4", 4.4e9, 7.3]])]),
    }
    arqs = {"TradeInformationConsolidated": [trade("PETR4", "CASH", 49.10, 0.77, 3.0e9), trade("MRVE3", "CASH", 5.60, 3.26, 45e6)]}
    datas = [f"2026-09-{d:02d}" for d in range(10, 29) if d not in (12, 13, 19, 20, 26, 27)]
    merc = {"datas": datas, "teorica": {}, "ativos": {
        "PETR4": {"f": [48.0] * len(datas), "v": [1000000] * len(datas), "a": [190000] * len(datas)},
        "MRVE3": {"f": [5.0] * len(datas), "v": [60000] * len(datas), "a": [60000] * len(datas)}}}
    r = resumo.montar(bruto(tabelas, arqs), CFG, LIVRO, {}, merc=merc)
    rad = r["radar"]
    assert rad["universo"] == 3 and rad["pregoes_no_historico"] == len(datas) and rad["aluguel_total_rs"] == 400e6 + 9.3e9 + 5e6
    assert [l["ativo"] for l in rad["volume"]] == ["PETR4"] and rad["volume"][0]["volume_x_media"] == 3.0
    mrv = rad["aluguel_float"][0]
    assert mrv["ativo"] == "MRVE3" and mrv["pct_free_float"] == 20.0 and mrv["taxa"] == 19.04 and mrv["aluguel_var_dia_pct"] == 25.0
    assert [l["ativo"] for l in rad["aluguel_alta"]] == ["MRVE3"]
    assert [l["ativo"] for l in rad["vendidos_pressionados"]] == ["MRVE3"] and mrv["preco_5d_pct"] == 12.0
    assert r["_apoio"]["mercado_hoje"]["MRVE3"] == (5.6, 45000, 75000) and r["_apoio"]["teorica"]["PETR4"] == 4.4e9


def test_opcoes_do_mercado_medem_a_mudanca_de_posicao_contra_o_pregao_anterior():
    cad, pos = [], []
    for cod, under, tipo, strike, oi, cat in (("PETRJ500", "PETR4", "Call", "50", 900000, "OPTION ON EQUITIES"),
                                              ("PETRV470", "PETR4", "Put", "47", 600000, "OPTION ON EQUITIES"),
                                              ("GMATK529", "GMAT3", "Call", "5,29", 4300000, "OPTION ON EQUITIES"),
                                              ("IBOVJ190", "IBOV11", "Call", "190000", 5000, "OPTION ON INDEX")):
        cad.append({"TckrSymb": cod, "Asst": under, "SgmtNm": f"EQUITY {tipo.upper()}", "SctyCtgyNm": cat, "XprtnDt": "2026-10-16",
                    "ExrcPric": strike, "OptnStyle": "AMER"})
        pos.append({"RptDt": D, "TckrSymb": cod, "TtlPos": str(oi), "UcvrdQty": str(oi // 2), "CvrdQty": "0", "TtlBlckdPos": "0"})
    b = bruto({"INDEXES": tab("INDEXES", [], [], filhos=[tab("IBOVESPA", [], [], filhos=[
        tab("IbovespaDayBehavior", ["TckrSymb", "LastPric"], [["IBOVESPA", 183827]])])])},
        {"TradeInformationConsolidated": [trade("PETR4", "CASH", 49.10, 0.77, 1e9), trade("PETRJ500", "EQUITY CALL", 1.6, 5, 2e6)],
         "InstrumentsConsolidated": cad, "DerivativesOpenPosition": pos})
    b["pos_anterior"] = [{"TckrSymb": "PETRJ500", "TtlPos": "500000"}, {"TckrSymb": "PETRV470", "TtlPos": "700000"},
                         {"TckrSymb": "GMATK529", "TtlPos": "0"}]
    b["pos_anterior_data"] = "2026-09-28"
    r = resumo.montar(b, CFG, LIVRO, {})
    om = r["opcoes_mercado"]
    assert om["posicao_call"] == 900000 + 4300000 + 5000 and om["put_call"] == 0.12 and om["comparado_com"] == "2026-09-28"
    assert [m["codigo"] for m in om["maiores_altas"]][:2] == ["GMATK529", "PETRJ500"] and om["maiores_quedas"][0]["variacao"] == -100000
    assert om["volume_call_rs"] == 2e6 and om["por_ativo"][0]["ativo"] == "GMAT3"
    petr = r["ativos"]["PETR4"]["opcoes"]
    assert petr["maiores_altas"][0]["variacao"] == 400000 and petr["descoberta_call_pct"] == 50.0
    assert petr["vencimentos"][0]["grade"] == [[47.0, 0.0, 600000.0], [50.0, 900000.0, 0.0]]
    assert petr["mais_negociadas"][0]["codigo"] == "PETRJ500"
    ibov = r["opcoes_extras"]["IBOV11"]
    assert ibov["preco"] == 183827 and ibov["vencimentos"][0]["parede_call"]["strike"] == 190000.0      # opcao de indice usa os pontos do Ibovespa
    assert resumo.entrada_historico(r)["opcoes_extras"]["IBOV11"] == [5000.0, 0.0]


def test_dor_maxima_e_o_strike_que_menos_paga_aos_titulares():
    assert resumo._dor_maxima({40.0: 100, 50.0: 100}, {45.0: 100, 55.0: 100}) == 45.0
    assert resumo._dor_maxima({40.0: 1}, {45.0: 1}) is None


def test_corretoras_no_aluguel_somam_por_lado_e_limpam_o_nome():
    assert mercado.corretora("XP INVESTIMENTOS CCTVM S/A") == "XP Investimentos"
    assert mercado.corretora("BTG PACTUAL CTVM S/A") == "BTG Pactual" and mercado.corretora("254") == "Participante 254"
    cols = ["TckrSymb", "Quantity", "Rate", "TradeId", "MarketBTB", "EntryDate", "EntryTime", "EntrySeller", "EntrySellerNm",
            "EntryBuyer", "EntryBuyerNm", "UpdateAction", "TradeSessionId"]
    linhas = [["MRVE3", 3e6, 0.13, 1, "Balcão", D, "", "1", "INTER DISTRIBUIDORA DE TITULOS", "2", "UBS BRASIL CCTVM S/A", "Novo (0)", "Regular (1)"],
              ["MRVE3", 1e6, 0.11, 2, "Balcão", D, "", "3", "XP INVESTIMENTOS CCTVM S/A", "3", "XP INVESTIMENTOS CCTVM S/A", "Novo (0)", "Regular (1)"],
              ["SEMPRECO3", 9e9, 0.1, 3, "Balcão", D, "", "3", "X", "3", "Y", "Novo (0)", "Regular (1)"]]
    arqs = {"TradeInformationConsolidated": [trade("MRVE3", "CASH", 5.0, 1.0, 45e6)]}
    c = resumo.montar(bruto({"BTBTrade": tab("BTBTrade", cols, linhas, situacao="atrasado")}, arqs), CFG, LIVRO, {})["aluguel_corretoras"]
    assert c["volume_rs"] == 20e6 and c["tomadoras"][0] == ["UBS Brasil", 15e6, 75.0] and c["doadoras"][0][0] == "Inter"
    assert c["ativos"]["MRVE3"] == {"negocios": 2, "quantidade": 4e6, "taxa_media": 12.5,
                                    "tomadoras": [["UBS Brasil", 75.0], ["XP Investimentos", 25.0]],
                                    "doadoras": [["Inter", 75.0], ["XP Investimentos", 25.0]]}


# ------------------------------------------------------------------ painel (boletim/painel.py)

def _resumo_cheio():
    linhas_rf = [neg_rf("DEB", cod, "EMISSOR " + cod, 1000, 2e6 + i * 1e6, 7.5 + i * 0.1) for i, cod in enumerate(("AESLD2", "RISP24"))]
    b = bruto_rf(linhas_rf)
    for i in range(5):
        b["rf_cadastro"][f"DEBX{i}"] = {"tipo": "DEB", "incentivada": True, "indexador": "IPCA", "pct_indexador": None, "taxa": 6.0,
                                         "vencimento": f"20{30 + i}-05-15"}
        b["tabelas"]["Trade"]["linhas"].append(neg_rf("DEB", f"DEBX{i}", "EMISSOR X", 1000, 3e6, 7.6 + i * 0.2))
    b["arquivos"]["TradeInformationConsolidated"] += [trade("PETR4", "CASH", 49.10, 0.77, 1.1e9), trade("MRVE3", "CASH", 5.38, 3.26, 45e6),
                                                      trade("DI1F29", "FINANCIAL", 13.79, 0, 1e9, AdjstdQtTax="13,789"),
                                                      trade("DI1F32", "FINANCIAL", 14.02, 0, 1e9, AdjstdQtTax="14,023")]
    b["tabelas"]["SharesInvesVolum"] = tab("SharesInvesVolum", ["TckrSymb", "Purchase", "Sales", "Partmil", "PartPer"],
                                           [["Investidor Estrangeiro", 395618061, 31.16, 386048230, 30.41]],
                                           texto=["Dados acumulados do início do mês até o dia 25/09/2026."])
    return resumo.montar(b, CFG, LIVRO, historico(12))


def test_painel_e_autocontido_tem_o_marcador_e_segue_a_paleta_clara():
    r = _resumo_cheio()
    r.pop("_apoio")
    h = painel.pagina(r, historico(12))
    assert h.startswith("<title>Boletim B3</title>") and painel.MARCADOR_LEITURA in h and h.count(painel.MARCADOR_LEITURA) == 1
    assert "<html" not in h and "<body" not in h and "<!doctype" not in h.lower()          # o esqueleto e do Artifact
    assert 'src="http' not in h and "@import" not in h and "url(" not in h                  # nada carregado de fora
    assert "color-scheme: light" in h and "prefers-color-scheme" not in h                   # formato branco e azul: so claro
    assert "--acc:#0f4c81" in h and "Não constitui recomendação" in h
    for trecho in ('id="sinais"', 'id="fluxo"', 'id="juros"', 'id="livro"', 'id="renda-fixa"', 'id="fontes"', "PARCIAL"):
        assert trecho in h, trecho
    assert "AESLD2" in h and "IPCA+ 7,50%" in h and "Curva de crédito das debêntures incentivadas" in h
    assert "None" not in h and "nan" not in h.lower().replace("financ", "")                 # nenhum buraco vazou para a tela
    # celular: etiqueta longa quebra dentro do card (em 30/09/2026 as do radar de aluguel alargavam a pagina em 66 px)
    regra = h.split(".chip{", 1)[1].split("}", 1)[0]
    assert "max-width:100%" in regra and "nowrap" not in regra


def test_painel_parcial_empresta_o_aluguel_do_pregao_anterior_com_a_data_no_card():
    ontem = {"pregao": "2026-09-28", "situacao": {"completo": True}, "ativos": {"MRVE3": {"aluguel": {
        "saldo_qtd": 65e6, "saldo_rs": 347e6, "pct_free_float": 17.3, "taxa_tomador_media": 12.87, "var_dia_pct": -2.3}}}}
    r = _resumo_cheio()
    r.pop("_apoio")
    h = painel.pagina(r, {}, ontem)
    assert 'id="aluguel"' in h and '<span class="tag velho">dados de 28/09</span>' in h and "17,3%" in h
    assert "Esses cards mostram a posição de 28/09" in h
    sem = painel.pagina(r, {}, None)
    assert 'id="aluguel"' not in sem                                                        # sem dado, a secao some: nada de card vazio


def test_graficos_do_painel_sao_svg_com_escala_e_dica():
    g = painel.svg_strikes([[47.0, 0.0, 600000.0], [49.0, 300000.0, 200000.0], [50.0, 900000.0, 0.0]], 49.1,
                           {"strike": 50.0}, {"strike": 47.0}, 49.0)
    assert g.startswith('<svg class="graf"') and g.count("<path") == 5 and "teto" in g and "piso" in g and "preço 49,10" in g
    assert 'data-tip="Strike 50,00|call: 900.000 opções em aberto"' in g
    assert painel.svg_strikes([[1.0, 1, 1]], 1.0) == ""
    assert painel._escala(0, 100) == [0, 25, 50, 75, 100] and painel._escala(7.4, 9.9)[0] <= 7.4
    c = painel.svg_colunas_sinal([("24/09", -964.0, "a"), ("25/09", 370.0, "b"), ("28/09", 141.0, "c")])
    assert "#b3372f" in c and "#0a7d4f" in c and "−964" in c
    assert painel.compacto(1.25e9) == "1,2 bi" and painel.compacto(2400) == "2,4 mil" and painel.n(-3.5, 1, True) == "−3,5"


def test_resumo_em_texto_volta_igual_e_tem_um_bloco_por_linha():
    r = _resumo_cheio()
    r.pop("_apoio")
    texto = coleta.texto_resumo(r)
    assert json_ok(texto) == json_ok(__import__("json").dumps(r)) and texto.count("\n") == len(r) + 2


# ------------------------------------------------------------------ leitura de tabela grande (boletim/b3.py)

class _ClienteFalso:
    """Devolve a primeira pagina com `paginas` e, na exportacao, a tabela inteira."""

    def __init__(self, paginas, linhas_pagina, linhas_export, status_export=200):
        self.paginas, self.linhas_pagina, self.linhas_export, self.status_export = paginas, linhas_pagina, linhas_export, status_export
        self.chamadas = []

    def post(self, url, data=None, **kw):
        import json
        from livro.http import Resposta
        self.chamadas.append(url.rsplit("/bdi/", 1)[1])
        cols = [{"id": 1, "name": "IdSer", "friendlyNamePt": "Id"}]
        if url.endswith("/table/export"):
            assert json.loads(data) == {"Name": "Trade", "Date": D, "FinalDate": D, "ClientId": "", "Filters": {}}
            corpo = {"name": "Trade", "columns": cols, "values": [[i, None] for i in self.linhas_export], "pageCount": 0}
            return Resposta(self.status_export, json.dumps(corpo).encode() if self.status_export == 200 else b"")
        corpo = {"status": 5, "lastUpdateDate": f"{D}T20:24:31", "table": {
            "name": "Trade", "columns": cols, "values": [[i, None] for i in self.linhas_pagina], "pageCount": self.paginas}}
        return Resposta(200, json.dumps(corpo).encode())


def test_tabela_de_varias_paginas_vem_pela_exportacao_e_nunca_pagina_a_pagina():
    from datetime import date
    # a paginacao da B3 repete e pula linhas (30/09/2026: 33.681 linhas, 23.129 negocios unicos); a exportacao traz tudo
    cli = _ClienteFalso(paginas=3, linhas_pagina=[1, 2, 2], linhas_export=[1, 2, 3, 4, 5])
    t = b3.tabela(cli, "Trade", date(2026, 9, 29), max_paginas=10)
    assert [l[0] for l in t["linhas"]] == [1, 2, 3, 4, 5] and t["situacao"] == "republicado" and not t["truncada"]
    assert cli.chamadas == [f"table/Trade/{D}/{D}/1/1000", "table/export"]          # nenhuma pagina 2 ou 3
    # uma pagina so: nao precisa exportar
    cli = _ClienteFalso(paginas=1, linhas_pagina=[1, 2], linhas_export=[])
    assert len(b3.tabela(cli, "Trade", date(2026, 9, 29))["linhas"]) == 2 and cli.chamadas == [f"table/Trade/{D}/{D}/1/1000"]
    # acima do teto de paginas a tabela nao e baixada e avisa
    cli = _ClienteFalso(paginas=2000, linhas_pagina=[1], linhas_export=[1, 2])
    t = b3.tabela(cli, "Trade", date(2026, 9, 29), max_paginas=120)
    assert t["truncada"] and len(t["linhas"]) == 1 and len(cli.chamadas) == 1


def test_exportacao_que_falha_ou_vem_curta_derruba_a_tabela_em_vez_de_entregar_dado_torto():
    from datetime import date
    import pytest
    with pytest.raises(b3.B3Erro, match="exportacao de Trade"):
        b3.tabela(_ClienteFalso(3, [1, 2, 3], [], status_export=500), "Trade", date(2026, 9, 29), max_paginas=10, pausas=())
    with pytest.raises(b3.B3Erro, match="menos que a primeira pagina"):
        b3.tabela(_ClienteFalso(3, [1, 2, 3], [1]), "Trade", date(2026, 9, 29), max_paginas=10)


def test_falha_passageira_e_tentada_de_novo_e_codigo_definitivo_volta_na_hora():
    import pytest
    from livro.http import HttpError, Resposta
    esperas = []
    # a rede cai, depois o servidor responde 503, depois vem o dado (01/10/2026: a exportacao de Trade caiu por rede)
    fila = [HttpError(0, "ConnectionError", "u"), Resposta(503, b""), Resposta(200, b"{}")]

    def fn():
        x = fila.pop(0)
        if isinstance(x, Exception):
            raise x
        return x
    assert b3._pedir(fn, (1.0, 2.0), esperas.append).status == 200 and esperas == [1.0, 2.0]
    # 400 e a B3 dizendo que o arquivo ainda nao saiu: nao adianta insistir
    esperas.clear()
    assert b3._pedir(lambda: Resposta(400, b""), (1.0, 2.0), esperas.append).status == 400 and esperas == []
    # acabaram as tentativas: a falha de rede sobe e o 5xx volta como veio
    def cai():
        raise HttpError(0, "ConnectionError", "u")
    with pytest.raises(HttpError):
        b3._pedir(cai, (1.0,), esperas.append)
    assert b3._pedir(lambda: Resposta(500, b""), (1.0,), esperas.append).status == 500 and esperas == [1.0, 1.0]
    # a exportacao que cai uma vez e tentada de novo e a tabela vem inteira
    cli = _ClienteFalso(paginas=3, linhas_pagina=[1, 2, 2], linhas_export=[1, 2, 3])
    original, quedas = cli.post, [1]

    def post(url, data=None, **kw):
        if url.endswith("/table/export") and quedas:
            quedas.pop()
            raise HttpError(0, "ConnectionError", url)
        return original(url, data=data, **kw)
    cli.post = post
    from datetime import date
    assert len(b3.tabela(cli, "Trade", date(2026, 9, 29), max_paginas=10, pausas=(0.0,))["linhas"]) == 3


def test_rodada_automatica_refaz_pregao_sem_resumo_ou_com_falha_de_rede(tmp_path):
    import json
    from datetime import date
    import boletim_b3

    def pregao(dia, falhas=None, com_resumo=True, linhas=10):
        p = tmp_path / dia
        p.mkdir()
        (p / "index.json").write_text(json.dumps({"tabelas": {"X": {"linhas": linhas}}, "arquivos": {}, "falhas": falhas or {}}))
        if com_resumo:
            (p / "resumo.json").write_text("{}")
    pregao("2026-09-21")                                                                    # inteiro
    pregao("2026-09-22", {"Trade": "HTTP 0 em https://arquivos.b3.com.br/bdi/table/export"})  # rede: refaz
    pregao("2026-09-23", {"DerivativesOpenPosition": "arquivo DerivativesOpenPosition: token HTTP 400"})   # a B3 nao publicou
    pregao("2026-09-24", com_resumo=False)                                                  # coletou e o resumo quebrou: refaz
    pregao("2026-09-25", com_resumo=False, linhas=0)                                        # dia sem pregao: nao insiste
    pregao("2026-09-29", {"IOPV": "tabela IOPV: HTTP 503"})                                 # servidor: refaz
    janela = [date(2026, 9, d) for d in (21, 22, 23, 24, 25, 28, 29)]                       # 28/09 nunca foi coletado
    assert [d.day for d in boletim_b3.a_refazer(str(tmp_path), janela)] == [22, 24, 28, 29]
    assert [d.day for d in boletim_b3.a_refazer(str(tmp_path), janela, maximo=2)] == [28, 29]     # os mais novos primeiro


def test_historico_de_outra_versao_e_descartado_e_dias_auto_refaz_a_carga(tmp_path, monkeypatch):
    import json
    import boletim_b3
    velho = {"pregoes": {f"2026-09-{d:02d}": {"rf": {"cri": 1.0}} for d in range(1, 21)}}       # sem `versao`: coletor antigo
    (tmp_path / "historico.json").write_text(json.dumps(velho))
    (tmp_path / "mercado.json").write_text(json.dumps({"datas": ["2026-09-01"], "ativos": {}}))
    pedidos = []

    class Parou(Exception):
        pass

    def falso_pregoes(fim, n):
        pedidos.append(n)
        raise Parou()
    monkeypatch.setattr(boletim_b3, "pregoes", falso_pregoes)
    monkeypatch.setattr(boletim_b3.b3, "catalogo", lambda cli: [])
    monkeypatch.setattr(boletim_b3, "Cliente", lambda: type("C", (), {"tipo": "teste"})())
    try:
        boletim_b3.main(["--saida", str(tmp_path), "--dias", "auto", "--data", "2026-09-30"])
    except Parou:
        pass
    assert pedidos == [21]                                           # 20 pregoes guardados, mas de outra versao: refaz tudo
    atual = {"versao": resumo.VERSAO, "pregoes": velho["pregoes"]}
    (tmp_path / "historico.json").write_text(json.dumps(atual))
    try:
        boletim_b3.main(["--saida", str(tmp_path), "--dias", "auto", "--data", "2026-09-30"])
    except Parou:
        pass
    assert pedidos == [21, 2]
    assert resumo.atualizar_historico({}, resumo.montar(bruto(), CFG, LIVRO, {}))["versao"] == resumo.VERSAO


def test_dias_auto_refaz_o_buraco_da_janela_e_busca_a_posicao_anterior_de_cada_pregao(tmp_path, monkeypatch):
    import json
    from datetime import date
    import boletim_b3
    janela = boletim_b3.pregoes(date(2026, 9, 30), 21)
    hist = {"versao": resumo.VERSAO, "pregoes": {d.isoformat(): {} for d in janela}}
    (tmp_path / "historico.json").write_text(json.dumps(hist))
    for d in janela[:-2]:
        p = tmp_path / d.isoformat()
        p.mkdir()
        falhas = {"Trade": "HTTP 0 em https://arquivos.b3.com.br/bdi/table/export"} if d == date(2026, 9, 16) else {}
        (p / "index.json").write_text(json.dumps({"tabelas": {"X": {"linhas": 5}}, "arquivos": {}, "falhas": falhas}))
        (p / "resumo.json").write_text("{}")
    coletados, posicoes = [], []

    def falsa_coleta(cli, d, pasta, **kw):
        coletados.append(d.isoformat())
        raise RuntimeError("parou aqui")                  # o teste so quer saber que pregoes a rodada pediu

    def falso_arquivo(cli, nome, d):
        posicoes.append(d.isoformat())
        raise b3.B3Erro("sem arquivo")
    monkeypatch.setattr(boletim_b3.coleta, "coletar_pregao", falsa_coleta)
    monkeypatch.setattr(boletim_b3.b3, "arquivo", falso_arquivo)
    monkeypatch.setattr(boletim_b3.b3, "catalogo", lambda cli: [])
    monkeypatch.setattr(boletim_b3, "Cliente", lambda: type("C", (), {"tipo": "teste"})())
    assert boletim_b3.main(["--saida", str(tmp_path), "--dias", "auto", "--data", "2026-09-30"]) == 1
    assert coletados == ["2026-09-16", "2026-09-29", "2026-09-30"]
    # a base das mudancas de posicao e sempre o pregao imediatamente anterior, mesmo com a lista salteada
    assert posicoes == ["2026-09-15", "2026-09-28", "2026-09-29"]
    assert json.loads((tmp_path / "manifest.json").read_text())["refeitos"] == ["2026-09-16"]
    # com numero de dias explicito nao ha conserto: so o que foi pedido
    coletados.clear()
    boletim_b3.main(["--saida", str(tmp_path), "--dias", "1", "--data", "2026-09-30"])
    assert coletados == ["2026-09-30"]
