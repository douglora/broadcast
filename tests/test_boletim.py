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


def test_agendamento_e_noite_do_pregao_e_manha_seguinte_e_nao_ha_gatilho_de_push():
    _, gatilhos = _workflow()
    crons = [c["cron"] for c in gatilhos.get("schedule") or []]
    assert crons == ["40 0 * * 2-6", "35 11 * * 2-6"], crons          # 21h40 BRT do pregao e 08h35 BRT do dia seguinte
    assert "push" not in gatilhos and "workflow_dispatch" in gatilhos   # em producao so o relogio e o disparo manual


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


def test_mesa_boletim_parcial_mostra_aluguel_e_opcoes_do_pregao_anterior_com_a_data(capsys):
    import mesa
    venc = {"vencimento": "2026-10-16", "dias_uteis": 12, "posicao_call": 100.0, "posicao_put": 80.0, "strikes_call": [[8.3, 60.0]],
            "strikes_put": [[5.4, 50.0]], "parede_call": {"strike": 8.3, "posicao": 60.0, "distancia_pct": 5.0},
            "parede_put": {"strike": 5.4, "posicao": 50.0, "distancia_pct": -4.0}, "dor_maxima": 5.5, "dor_maxima_dist_pct": 0.5}
    ontem = {"pregao": "2026-09-29", "situacao": {"completo": True},
             "ativos": {"MRVE3": {"aluguel": {"saldo_qtd": 64964248, "saldo_rs": 346998400.0, "pct_free_float": 17.34, "taxa_tomador_media": 12.87},
                                  "opcoes": {"posicao_call": 100.0, "posicao_put": 80.0, "put_call": 0.8, "vencimentos": [venc]}}},
             "radar": {"aluguel_total_rs": 171.8e9, "aluguel_float": [{"ativo": "MOVI3", "pct_free_float": 24.4}]},
             "opcoes_mercado": {"put_call": 0.79, "put_call_volume": 0.64, "por_ativo": [{"ativo": "BBAS3", "call": 398e6, "put": 322e6, "put_call": 0.81}]}}
    hoje = {"pregao": "2026-09-30", "situacao": {"completo": False}, "sinais": [],
            "ativos": {"MRVE3": {"nome": "MRV ON", "negocios": {"fechamento": 5.47, "oscilacao_pct": 1.67},
                                 "opcoes": {"volume_call_rs": 0.9e6, "volume_put_rs": 1.7e6}}},
            "radar": {"universo": 154, "volume": [{"ativo": "ISAE4", "volume_x_media": 12.4}]}}
    assert mesa._boletim_ativo("MRVE3", hoje, {}, ontem) == 0
    tela = capsys.readouterr().out
    assert "2026-09-29)" + mesa.EMPRESTADO in tela and "17,34" in tela and "12,87% a.a." in tela           # aluguel de ontem, com a data
    assert "volume do dia (2026-09-30): call R$ 0,9 mi" in tela and "vencimento 2026-10-16" in tela     # volume de hoje, posicao de ontem
    assert mesa._boletim_opcoes("MRVE3", hoje, {}, ontem) == 0
    tela = capsys.readouterr().out
    assert "opcoes de MRVE3 em 2026-09-29" in tela and mesa.EMPRESTADO in tela and "teto (maior call acima do preco): 8,30" in tela
    assert mesa._boletim_radar(hoje, ontem) == 0
    tela = capsys.readouterr().out
    assert "aluguel total R$ 171,8 bi em 2026-09-29" in tela and "ISAE4 12,4x" in tela and "MOVI3 24,4%" in tela and "opcoes de 2026-09-29" in tela
    # sem o pregao anterior (ou com o pregao completo) nada e emprestado e o aluguel sai como ainda nao publicado
    assert mesa._boletim_radar(hoje) == 0
    tela = capsys.readouterr().out
    assert "aluguel ainda nao publicado pela B3" in tela and mesa.EMPRESTADO not in tela


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


# Em DI a taxa do negocio vem na convencao do cadastro, e so a grandeza dela decidia a leitura (acima de 30, percentual do CDI).
# Medido em 01/10/2026 no bruto de 21 pregoes. Papel em DI + taxa em estresse sai acima de 30: BRKMA6 (DI + 1,75%) fez 14 negocios
# e R$ 15,0 mi a 54,33 em 30/09, com o PU a 44% do par; CSNAA1 (DI + 1,65%) saiu a 29,12 num dia e a 50,06 em outro; o CRA02400CI3
# (DI + 5%) a 5,00 com o PU a 652 e a 37,48 com o PU a 509. E negocio fora de preco em papel de percentual sai abaixo de 30: o CRI
# 25G5827604 (109% do DI) saiu a 1,35 em 28/09 com o PU a 1.453, contra 110 e 113,1 com o PU a 1.001 e a 991. Cadastros reais.
CADASTRO_DI = {
    "BRKMA6": {"tipo": "DEB", "incentivada": False, "indexador": "DI", "pct_indexador": 100, "taxa": 1.75, "vencimento": "2029-05-12"},
    "CSNAA1": {"tipo": "DEB", "incentivada": False, "indexador": "DI", "pct_indexador": 100, "taxa": 1.65, "vencimento": "2028-11-10"},
    "AALM12": {"tipo": "DEB", "incentivada": False, "indexador": "DI", "pct_indexador": 100, "taxa": 1.6, "vencimento": "2030-10-02"},
    "KLBNA2": {"tipo": "DEB", "incentivada": False, "indexador": "DI", "pct_indexador": 114.65, "taxa": None, "vencimento": "2029-03-19"},
    "DMCA11": {"tipo": "DEB", "incentivada": False, "indexador": "DI", "pct_indexador": 100, "taxa": None, "vencimento": "2030-04-10"},
    "25G5827604": {"tipo": "CRI", "incentivada": False, "indexador": "DI", "pct_indexador": 109, "taxa": 0, "vencimento": "2029-12-19"},
    "CRA02400CI3": {"tipo": "CRA", "incentivada": False, "indexador": "DI", "pct_indexador": 100, "taxa": 5, "vencimento": "2028-11-21"},
    "CRA024004H7": {"tipo": "CRA", "incentivada": False, "indexador": "DI", "pct_indexador": 100, "taxa": 0, "vencimento": "2029-04-12"},
}
NEGOCIOS_BRKMA6 = [neg_rf("DEB", "BRKMA6", "BRASKEM S/A", 2275, 1.07e6, 54.3298) for _ in range(14)]


def test_em_di_o_cadastro_decide_se_a_taxa_e_premio_sobre_o_cdi_ou_percentual_do_cdi(capsys):
    import mesa
    conv = renda_fixa.convencao
    brkm, csna, cra = CADASTRO_DI["BRKMA6"], CADASTRO_DI["CSNAA1"], CADASTRO_DI["CRA02400CI3"]
    # o cadastro diz DI + taxa: a taxa do negocio e premio sobre o CDI dos dois lados do corte de 30
    assert [conv(brkm, t) for t in (1.9, 54.3298, 115.6776)] == ["CDI+"] * 3
    assert conv(csna, 29.1166) == conv(csna, 50.0633) == "CDI+"                # o papel nao troca de leitura de um dia para o outro
    assert conv(cra, 5.0) == conv(cra, 37.4796) == "CDI+"                      # vale igual para CRI e CRA com DI + taxa no cadastro
    # o cadastro diz percentual do DI, sem taxa: a taxa do negocio e percentual do CDI dos dois lados do corte
    assert conv(CADASTRO["24H1684874"], 98.16) == conv(CADASTRO["24H1684874"], 14.4487) == "% do CDI"      # 97,5% do indexador
    assert conv(CADASTRO_DI["KLBNA2"], 102.94) == conv(CADASTRO_DI["KLBNA2"], None) == "% do CDI"
    cri = CADASTRO_DI["25G5827604"]
    assert conv(cri, 113.1) == conv(cri, 1.35) == "% do CDI"                   # negocio fora de preco nao vira premio sobre o CDI
    # o cadastro nao decide: ai, e so ai, vale a grandeza da taxa, e o corte e 30
    cem = CADASTRO_DI["CRA024004H7"]                                           # 100% do indexador sem taxa
    assert [conv(cem, t) for t in (101.2, 45.0, 30.01)] == ["% do CDI"] * 3 and conv(CADASTRO_DI["DMCA11"], 148.96) == "% do CDI"
    assert [conv(cem, t) for t in (30.0, 12.0, 0.9, None)] == ["CDI+"] * 4
    hibrido = {"indexador": "DI", "pct_indexador": 110, "taxa": 1.0}           # percentual com taxa
    plii = {"indexador": "DI", "pct_indexador": None, "taxa": 2.5}             # PLII11: sem percentual
    assert conv(hibrido, 50.0) == conv(plii, 50.0) == "% do CDI" and conv(hibrido, 2.0) == conv(plii, 2.6) == "CDI+"
    torto = {"indexador": "DI", "pct_indexador": 3, "taxa": None}              # 26H3987638: "3% do DI" nao e remuneracao
    assert (conv(torto, 3.1), conv(torto, 104.0), conv(torto, None)) == ("CDI+", "% do CDI", "% do CDI")
    # numero que chegar como texto no cadastro nao derruba o pregao
    assert conv({"indexador": "DI", "pct_indexador": "100", "taxa": "1,75"}, 54.3298) == "CDI+"
    assert conv({"indexador": "DI", "pct_indexador": "109", "taxa": ""}, 1.35) == "% do CDI"

    linhas = NEGOCIOS_BRKMA6 + [
        neg_rf("DEB", "CSNAA2", "COMPANHIA SIDERURGICA NACIONAL", 5000, 5e6, 1.20),
        neg_rf("DEB", "AALM12", "AURA ALMAS MINERACAO S.A.", 4000, 4e6, 0.75),
        neg_rf("DEB", "CSNAA1", "COMPANHIA SIDERURGICA NACIONAL", 12, 7572.6, 51.2123),
        neg_rf("CRI", "24H1684874", "RIZA SECURITIZADORA S.A.", 2000, 2e6, 98.16),
        # um negocio grande fora de preco puxa a media do CRI de 109% do DI para 6,85: nao e CDI + 6,85%
        neg_rf("CRI", "25G5827604", "RIZA SECURITIZADORA S.A.", 4000, 5.8e6, 1.35),
        neg_rf("CRI", "25G5827604", "RIZA SECURITIZADORA S.A.", 300, 0.3e6, 113.1),
        neg_rf("CRA", "CRA024004H7", "RIZA SECURITIZADORA S.A.", 3000, 3.2e6, 101.2),
        neg_rf("CRA", "CRA02400CI3", "CANAL COMPANHIA DE SECURITIZACAO", 12000, 6e6, 37.4796)]
    b = bruto_rf(linhas)
    b["rf_cadastro"].update(CADASTRO_DI)
    # o CRA saiu a 5,00, a taxa de emissao, no ultimo pregao em que negociou
    r = resumo.montar(b, CFG, LIVRO, {}, rf_estado={"CRA02400CI3": [["2026-09-28", 5.0, 652.0]]})
    rf, todos = r["renda_fixa"], r["_apoio"]["rf_linhas"]
    assert todos["BRKMA6"]["convencao"] == todos["CSNAA1"]["convencao"] == "CDI+" and todos["BRKMA6"]["taxa_media"] == 54.3298
    com = rf["resumo"]["deb_comum"]
    assert com["por_indexador_pct"] == {"CDI+": 100.0}                         # os R$ 15,0 mi da BRKMA6 nao viram "% do CDI"
    # a media ponderada pelo volume carrega o papel em estresse (R$ 15,0 mi a 54,33 em R$ 24,0 mi); a mediana e o centro do dia
    assert com["premio_cdi_medio"] == 34.31 and com["premio_cdi_mediano"] == 1.2
    assert {m["convencao"] for m in rf["maiores_negocios"] if m["codigo"] == "BRKMA6"} == {"CDI+"}
    # CRI e CRA de percentual do CDI seguem percentual, mesmo com a media do dia abaixo de 30...
    assert [(l["codigo"], l["convencao"], l["taxa_media"]) for l in rf["papeis"]["cri"]] == [
        ("25G5827604", "% do CDI", 6.8459), ("24H1684874", "% do CDI", 98.16)]
    assert rf["resumo"]["cri"]["por_indexador_pct"] == {"% do CDI": 100.0} and "premio_cdi_medio" not in rf["resumo"]["cri"]
    # ...e o CRA com DI + taxa no cadastro passa a aparecer como estresse: so ele, nao o CRI de negocio fora de preco
    assert [(l["codigo"], l["convencao"]) for l in rf["papeis"]["cra"]] == [("CRA02400CI3", "CDI+"), ("CRA024004H7", "% do CDI")]
    assert rf["resumo"]["cra"]["por_indexador_pct"] == {"CDI+": 65.2, "% do CDI": 34.8} and rf["resumo"]["cra"]["premio_cdi_medio"] == 37.48
    assert [l["codigo"] for l in rf["premios_altos"]] == ["CRA02400CI3"]
    textos = {s["tipo"]: s["texto"] for s in r["sinais"] if s["tipo"].startswith("rf_")}
    assert textos["rf_premio_alto"] == "CRA02400CI3 (Canal Companhia de Securitizacao, CRA): negociada a CDI+ 37,48%, em R$ 6,0 mi."
    # premio sobre o CDI tem variacao em pontos-base: o papel que sai da taxa de emissao para o estresse entra em quem abriu taxa
    assert [(l["codigo"], l["var_taxa_pb"], l["comparado_com"]) for l in rf["aberturas"]] == [("CRA02400CI3", 3248, "2026-09-28")]
    assert textos["rf_abertura"] == ("CRA02400CI3 (Canal Companhia de Securitizacao, CRA): taxa média dos negócios da B3 abriu 3.248 pb "
                                     "contra 28/09, para CDI+ 37,48%, em R$ 6,0 mi.")
    assert len([s for s in r["sinais"] if s["tipo"].startswith("rf_")]) == 2
    r.pop("_apoio")
    assert mesa._boletim_rf(r) == 0
    tela = capsys.readouterr().out
    classe = next(l for l in tela.splitlines() if l.strip().startswith("debentures nao incentivadas"))
    assert "| CDI+ mediano 1,20% medio 34,31% |" in classe                     # a linha da classe mostra as duas
    assert "CDI+ 37,48%" in tela and "6,8% do CDI" in tela and "CDI+ 6,85%" not in tela and "37,5% do CDI" not in tela


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


# ------------------------------------------------------------------ taxa indicativa da ANBIMA (boletim/anbima.py)

from boletim import anbima        # noqa: E402

# Linhas do arquivo de 30/09/2026 como a ANBIMA publicou: titulo, linha em branco, cabecalho e uma debenture por linha.
ANBIMA_TXT = "\n".join([
    "ANBIMA - Associação Brasileira das Entidades dos Mercados Financeiro e de Capitais", "",
    "Código@Nome@Repac./  Venc.@Índice/ Correção@Taxa de Compra@Taxa de Venda@Taxa Indicativa@Desvio Padrão"
    "@Intervalo Indicativo Minimo@Intervalo Indicativo Máximo@PU@% PU Par / % VNE@Duration@% Reune@Referência NTN-B",
    "ABSP12@AGUAS DE BOMBINHAS SANEAMENTO SPE S.A. (*) (**)@15/10/2026@DI + 1,95%@--@--@--@--@--@--@N/D@N/D@N/D@@",
    "AEGE16@EQUIPAV SANEAMENTO S.A. (*) (**)@11/03/2034@DI + 3,9%@7,0501@4@5,4784@0,1485@5,3299@5,6271@957,678788@94,9469@859,14@@",
    "CGOS16@EQUATORIAL GOIAS DISTRIBUIDORA DE ENERGIA S.A. (*)@15/05/2036@IPCA + 6,4895%@8,4875@7,9828@8,1894@0,085@8,1044@8,2745"
    "@1027,553709@90,6615@1544,4@@15/05/2035",
    "CGOS28@EQUATORIAL GOIAS DISTRIBUIDORA DE ENERGIA S.A. (*)@15/09/2036@IPCA + 6,6493%@8,3863@8,0699@8,2311@0,1023@8,1289@8,3335"
    "@999,149414@90,8754@1623,09@15@15/05/2035",
    "EQPA18@EQUATORIAL PARA DISTRIBUIDORA DE ENERGIA S.A. (*)@15/12/2036@IPCA + 7,7477%@8,4517@7,9168@8,1553@0,0858@8,0695@8,2411"
    "@1082,129302@97,6454@1585,81@@15/05/2035",
    "KLBNA2@KLABIN S.A.@19/06/2029@114,65% do DI@105,1@103,9@104,5@0,2@104,3@104,7@1.010,25@100,2@610@@",
    "ENMTC4@ENERGISA MATO GROSSO - DISTRIBUIDORA DE ENERGIA S.A. (*)@15/05/2032@PREFIXADO 13,7%@14,5609@13,9189@14,3552@0,1484"
    "@14,2068@14,5038@1026,801941@97,7788@982,27@10@"]) + "\n"
CADASTRO_2036 = {
    "CGOS16": {"tipo": "DEB", "incentivada": True, "indexador": "IPCA", "pct_indexador": None, "taxa": 6.48, "vencimento": "2036-05-15"},
    "CGOS28": {"tipo": "DEB", "incentivada": True, "indexador": "IPCA", "pct_indexador": None, "taxa": 6.64, "vencimento": "2036-09-15"},
    "EQPA18": {"tipo": "DEB", "incentivada": True, "indexador": "IPCA", "pct_indexador": None, "taxa": 7.74, "vencimento": "2036-12-15"},
}
GOIAS, PARA = "EQUATORIAL GOIAS DISTRIBUIDORA DE ENERGIA S.A.", "EQUATORIAL PARA DISTRIBUIDORA DE ENERGIA S.A."


class _Anbima:
    """O servidor da ANBIMA de mentira: {AAMMDD: texto, codigo HTTP ou excecao}. Dia que nao esta aqui responde 404."""

    def __init__(self, dias):
        self.dias, self.pedidos = dias, []

    def get(self, url, **kw):
        from livro.http import Resposta
        assert url.startswith("https://www.anbima.com.br/informacoes/merc-sec-debentures/arqs/db") and url.endswith(".txt")
        dia = url[-10:-4]
        self.pedidos.append(dia)
        x = self.dias.get(dia, 404)
        if isinstance(x, Exception):
            raise x
        if isinstance(x, int):
            return Resposta(x, b'<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"><html><title>404 - File or directory not found.</title></html>')
        return Resposta(200, x.encode("latin-1"), {"last-modified": "Wed, 30 Sep 2026 22:56:25 GMT"})


def test_anbima_le_o_arquivo_pelo_titulo_das_colunas_com_virgula_decimal_traco_e_nd():
    p = anbima.ler(ANBIMA_TXT.encode("latin-1").decode("latin-1"))          # o arquivo vem em latin-1
    assert list(p) == ["ABSP12", "AEGE16", "CGOS16", "CGOS28", "EQPA18", "KLBNA2", "ENMTC4"]
    c = p["CGOS16"]
    assert c["nome"] == GOIAS                                                # as marcas (*) e (**) saem do nome
    assert (c["indicativa"], c["compra"], c["venda"], c["desvio"]) == (8.1894, 8.4875, 7.9828, 0.085)
    assert (c["pu"], c["pct_pu_par"], c["duration_du"], c["pct_reune"]) == (1027.553709, 90.6615, 1544.4, None)
    assert (c["repac_venc"], c["ntnb_ref"], c["convencao"], c["taxa_emissao"]) == ("2036-05-15", "2035-05-15", "IPCA+", 6.4895)
    assert p["CGOS28"]["pct_reune"] == 15.0
    # `--` e `N/D` sao papel que a ANBIMA lista sem taxa nem preco: nulo, nunca zero
    assert all(p["ABSP12"][k] is None for k in ("compra", "venda", "indicativa", "pu", "pct_pu_par", "duration_du"))
    assert p["AEGE16"]["venda"] == 4.0 and p["AEGE16"]["convencao"] == "CDI+" and p["AEGE16"]["taxa_emissao"] == 3.9
    assert (p["KLBNA2"]["convencao"], p["KLBNA2"]["taxa_emissao"], p["KLBNA2"]["indicativa"], p["KLBNA2"]["pu"]) == ("% do CDI", 114.65, 104.5, 1010.25)
    assert (p["ENMTC4"]["convencao"], p["ENMTC4"]["taxa_emissao"], p["ENMTC4"]["ntnb_ref"]) == ("Pré", 13.7, None)
    # a mesma convencao que a renda fixa da ao negocio da B3: as duas taxas so se comparam quando falam a mesma lingua
    assert renda_fixa.convencao(CADASTRO_2036["CGOS16"], 8.2) == c["convencao"]
    # so vira numero o que e numero no formato do arquivo: `inf`, `nan` e notacao cientifica nao entram no resumo
    assert [anbima._num(v) for v in ("inf", "nan", "1e3", "12,", ",5", "abc")] == [None] * 6 and anbima._num("-0,25") == -0.25
    torto = anbima.ler(ANBIMA_TXT.replace("@1544,4@", "@inf@"))["CGOS16"]
    assert torto["duration_du"] is None and torto["indicativa"] == 8.1894
    # coluna nova ou fora de ordem nao troca um numero por outro: a leitura e pelo titulo
    outra_ordem = "Taxa Indicativa@Coluna Nova@Código@Índice/ Correção\n8,1894@x@CGOS16@IPCA + 6,4895%\n"
    assert anbima.ler(outra_ordem)["CGOS16"]["indicativa"] == 8.1894 and anbima.ler(outra_ordem)["CGOS16"]["compra"] is None


def test_anbima_pagina_de_erro_ou_formato_novo_nao_vira_dado():
    import pytest
    with pytest.raises(anbima.AnbimaErro, match="sem o cabecalho"):
        anbima.ler("<!DOCTYPE html><html><title>404 - File or directory not found.</title></html>")
    with pytest.raises(anbima.AnbimaErro, match="sem a coluna indicativa"):
        anbima.ler("Código@Nome@Índice/ Correção@Taxa\nCGOS16@X@IPCA + 6%@8,19\n")
    with pytest.raises(anbima.AnbimaErro, match="sem nenhuma debenture"):
        anbima.ler(ANBIMA_TXT.split("ABSP12")[0])


def test_anbima_404_e_arquivo_que_ainda_nao_saiu_e_vale_o_anterior_com_a_data_dele():
    from datetime import date
    cli = _Anbima({"260929": ANBIMA_TXT, "260928": ANBIMA_TXT, "260925": ANBIMA_TXT})        # o de 30/09 ainda nao foi publicado
    cache = {}
    ontem = anbima.do_pregao(cli, date(2026, 9, 29), cache, pausas=())
    assert ontem["situacao"] == "publicado" and ontem["arquivo"]["data"] == "2026-09-29" and ontem["anterior"]["data"] == "2026-09-28"
    assert ontem["arquivo"]["publicado_em"] == "2026-09-30T19:56:25"            # Last-Modified na hora de Brasilia
    assert ontem["arquivo"]["url"].endswith("/arqs/db260929.txt") and ontem["arquivo"]["papeis"]["CGOS16"]["indicativa"] == 8.1894
    hoje = anbima.do_pregao(cli, date(2026, 9, 30), cache, pausas=())
    assert hoje["situacao"] == "anterior" and "erro" not in hoje                 # 404 e espera, nao e erro
    assert hoje["arquivo"]["data"] == "2026-09-29" and hoje["anterior"]["data"] == "2026-09-28"
    assert hoje["tentativas"] == {"2026-09-30": "nao publicado", "2026-09-29": "publicado", "2026-09-28": "publicado"}
    assert cli.pedidos == ["260929", "260928", "260930"]                         # cada arquivo e pedido uma vez so na rodada
    assert anbima.situacao(hoje) == {"situacao": "anterior", "data": "2026-09-29", "papeis": 7, "publicado_em": "2026-09-30T19:56:25",
                                     "comparado_com": "2026-09-28", "tentativas": hoje["tentativas"]}
    # segunda-feira sem arquivo: o anterior e o de sexta, e o que vem antes dele e o de quinta (nao ha: 404)
    cli = _Anbima({"260925": ANBIMA_TXT})
    seg = anbima.do_pregao(cli, date(2026, 9, 28), {}, dias_atras=2, pausas=())
    assert seg["arquivo"]["data"] == "2026-09-25" and seg["anterior"] is None and cli.pedidos == ["260928", "260925", "260924", "260923"]
    # nada na janela: ausente, sem erro
    vazio = anbima.do_pregao(_Anbima({}), date(2026, 9, 30), {}, dias_atras=1, pausas=())
    assert vazio["situacao"] == "ausente" and vazio["arquivo"] is None and "erro" not in vazio
    assert vazio["tentativas"] == {"2026-09-30": "nao publicado", "2026-09-29": "nao publicado"}


def test_anbima_falha_de_leitura_cai_para_o_arquivo_anterior_e_site_fora_do_ar_nao_e_tentado_a_cada_pregao():
    from datetime import date
    import pytest
    from livro.http import HttpError
    caiu = HttpError(0, "ConnectionError", "u")
    # o arquivo do dia nao pode ser lido, mas o de ontem a rodada ja tem: vale o de ontem, com a data dele e o motivo
    cli = _Anbima({"260930": caiu, "260929": ANBIMA_TXT, "260928": ANBIMA_TXT})
    cache = {}
    anbima.do_pregao(cli, date(2026, 9, 29), cache, pausas=())
    r = anbima.do_pregao(cli, date(2026, 9, 30), cache, pausas=())
    assert r["situacao"] == "anterior" and r["arquivo"]["data"] == "2026-09-29" and r["anterior"]["data"] == "2026-09-28"
    assert r["erro"] == "arquivo de 2026-09-30: falha de rede"
    assert r["tentativas"] == {"2026-09-30": "falhou", "2026-09-29": "publicado", "2026-09-28": "publicado"}
    anbima.do_pregao(cli, date(2026, 9, 30), cache, pausas=())
    assert cli.pedidos == ["260929", "260928", "260930"]                         # o que falhou nao e pedido de novo na rodada
    # nenhum arquivo ao alcance: falhou, com o motivo
    cli = _Anbima({"260929": caiu, "260930": caiu})
    cache = {}
    r = anbima.do_pregao(cli, date(2026, 9, 29), cache, pausas=())
    assert r["situacao"] == "falhou" and r["arquivo"] is None and r["erro"] == "arquivo de 2026-09-29: falha de rede"
    assert r["tentativas"] == {"2026-09-29": "falhou", "2026-09-28": "nao publicado", "2026-09-25": "nao publicado", "2026-09-24": "nao publicado"}
    r = anbima.do_pregao(cli, date(2026, 9, 30), cache, pausas=())
    assert r["situacao"] == "falhou" and r["erro"] == "arquivo de 2026-09-30: falha de rede"
    assert r["tentativas"] == {"2026-09-30": "falhou", "2026-09-29": "falhou", "2026-09-28": "nao publicado", "2026-09-25": "nao publicado"}
    # dois arquivos sem resposta da rede: a ANBIMA esta fora do ar e a rodada para de procurar (a rodada seguinte tenta)
    pedidos = list(cli.pedidos)
    r = anbima.do_pregao(cli, date(2026, 10, 1), cache, pausas=())
    assert r["situacao"] == "falhou" and r["tentativas"]["2026-10-01"] == "nao tentado" and cli.pedidos == pedidos
    assert r["erro"] == "arquivo de 2026-09-30: falha de rede"
    r = anbima.do_pregao(cli, date(2026, 10, 6), cache, pausas=())                 # longe dos que falharam: nada e tentado
    assert r["situacao"] == "falhou" and set(r["tentativas"].values()) == {"nao tentado"} and cli.pedidos == pedidos
    assert r["erro"] == "sem resposta da rede em outros arquivos da rodada; este ficou sem tentativa"
    # codigo HTTP e pagina no lugar do arquivo respondem na hora: sao falha, mas nao desligam a ANBIMA para a rodada
    cli = _Anbima({"260930": 503, "260929": 403, "260928": "<html>manutencao</html>"})
    cache = {}
    r = anbima.do_pregao(cli, date(2026, 9, 30), cache, pausas=())
    assert r["situacao"] == "falhou" and r["erro"] == "arquivo de 2026-09-30: HTTP 503"
    assert r["tentativas"] == {"2026-09-30": "falhou", "2026-09-29": "falhou", "2026-09-28": "falhou", "2026-09-25": "nao publicado"}
    assert cache[anbima._FALHAS]["sem_rede"] == 0 and "sem o cabecalho" in cache[anbima._FALHAS]["motivos"]["2026-09-28"]
    # o arquivo anterior falhou: a variacao sai contra o que vier antes dele, com a data dele, e o motivo fica anotado
    cli = _Anbima({"260928": caiu, "260925": ANBIMA_TXT, "260929": ANBIMA_TXT, "260930": ANBIMA_TXT})
    cache = {}
    r = anbima.do_pregao(cli, date(2026, 9, 29), cache, pausas=())
    assert r["situacao"] == "publicado" and r["anterior"]["data"] == "2026-09-25" and r["erro"] == "arquivo de 2026-09-28: falha de rede"
    r = anbima.do_pregao(cli, date(2026, 9, 30), cache, pausas=())
    assert r["situacao"] == "publicado" and r["anterior"]["data"] == "2026-09-29" and "erro" not in r
    # `dias_atras` zero nao procura arquivo mais antigo para o pregao, mas o anterior (base da variacao) e sempre procurado
    cli = _Anbima({"260929": ANBIMA_TXT, "260930": ANBIMA_TXT})
    r = anbima.do_pregao(cli, date(2026, 9, 30), {}, dias_atras=0, pausas=())
    assert r["situacao"] == "publicado" and r["anterior"]["data"] == "2026-09-29"
    assert anbima.do_pregao(_Anbima({"260929": ANBIMA_TXT}), date(2026, 9, 30), {}, dias_atras=0, pausas=())["situacao"] == "ausente"
    # falha passageira e tentada de novo antes de desistir (uma vez so: o arquivo e enriquecimento)
    quedas = [HttpError(0, "ConnectionError", "u")]

    class Instavel(_Anbima):
        def get(self, url, **kw):
            if quedas:
                raise quedas.pop()
            return super().get(url, **kw)
    assert anbima.baixar(Instavel({"260930": ANBIMA_TXT}), date(2026, 9, 30), pausas=(0.0,))["papeis"]["EQPA18"]["indicativa"] == 8.1553
    quedas.append(HttpError(0, "ConnectionError", "u"))
    with pytest.raises(HttpError):
        anbima.baixar(Instavel({"260930": ANBIMA_TXT}), date(2026, 9, 30), pausas=())
    assert len(anbima.PAUSAS) == 1


def test_coleta_guarda_a_anbima_fora_das_falhas_para_nao_mandar_refazer_a_b3(monkeypatch, tmp_path):
    import json
    from datetime import date
    import boletim_b3

    def sem_rede(*a, **k):
        raise b3.B3Erro("sem rede no teste")
    for nome in ("situacao_cadernos", "tabela", "arquivo", "capitulos"):
        monkeypatch.setattr(coleta.b3, nome, sem_rede)
    pedidos = []

    def falso(cli, d, cache, dias_atras):
        pedidos.append((d.isoformat(), dias_atras))
        return {"pregao": d.isoformat(), "situacao": "falhou", "arquivo": None, "anterior": None,
                "tentativas": {d.isoformat(): "falhou"}, "erro": "arquivo de 2026-09-29: falha de rede"}
    monkeypatch.setattr(coleta.anbima, "do_pregao", falso)
    pasta = tmp_path / "2026-09-29"
    b = coleta.coletar_pregao(object(), date(2026, 9, 29), str(pasta), pausa=0, log=lambda *a: None, anbima_cache={}, anbima_dias_atras=2)
    assert pedidos == [("2026-09-29", 2)] and b["anbima"]["situacao"] == "falhou"
    idx = json.loads((pasta / "index.json").read_text())
    assert idx["anbima"] == {"situacao": "falhou", "tentativas": {"2026-09-29": "falhou"}, "erro": "arquivo de 2026-09-29: falha de rede"}
    assert "anbima" not in idx["falhas"] and "Trade" in idx["falhas"]
    # ...e por isso um pregao antigo em que so a ANBIMA falhou nao entra na lista de pregoes a refazer
    idx["falhas"], idx["tabelas"] = {}, {"X": {"linhas": 5}}
    (pasta / "index.json").write_text(json.dumps(idx))
    (pasta / "resumo.json").write_text("{}")
    assert boletim_b3.a_refazer(str(tmp_path), [date(2026, 9, 29)]) == []
    # sem o cache (config com a ANBIMA desligada) ela nem e consultada
    b = coleta.coletar_pregao(object(), date(2026, 9, 29), None, pausa=0, log=lambda *a: None)
    assert "anbima" not in b and "anbima" not in b["index"] and len(pedidos) == 1


# ------------------------------------------------------------------ renda fixa com a indicativa (boletim/renda_fixa.py)

def anbima_do_pregao(papeis, data=D, antes=None, data_antes="2026-09-28", situacao="publicado", **extra):
    """O que a coleta deixa em bruto['anbima']: o arquivo que vale para o pregao e o publicado antes dele."""
    return dict({"pregao": D, "situacao": situacao,
                 "arquivo": {"data": data, "papeis": papeis, "publicado_em": f"{data}T19:56:25", "url": f"https://anbima/db{data}.txt"},
                 "anterior": {"data": data_antes, "papeis": antes} if antes is not None else None,
                 "tentativas": {data: "publicado"}}, **extra)


def indicativas(**delta):
    """As indicativas do arquivo de teste e as do dia anterior: `delta` e quanto cada papel abriu, em pontos-base."""
    hoje = anbima.ler(ANBIMA_TXT)
    antes = {c: dict(p, indicativa=round(p["indicativa"] - delta.get(c, 0.0) / 100.0, 4) if p["indicativa"] is not None else None)
             for c, p in hoje.items()}
    return hoje, antes


def bruto_2036(linhas, anb=None, cadastro=None):
    b = bruto_rf(linhas)
    b["rf_cadastro"].update(cadastro or CADASTRO_2036)
    if anb is not None:
        b["anbima"] = anb
    return b


# O caso medido em 01/10/2026: na EQPA18 muito negocio pequeno a taxa baixa puxa a media para 7,70%; a CGOS16 sai a 8,16%.
NEGOCIOS_2036 = [neg_rf("DEB", "EQPA18", PARA, 250, 250e3, 7.60) for _ in range(8)] + [
    neg_rf("DEB", "EQPA18", PARA, 500, 500e3, 8.10), neg_rf("DEB", "CGOS16", GOIAS, 3000, 3e6, 8.16)]


def test_indicativa_da_anbima_e_a_referencia_e_a_taxa_dos_negocios_fica_ao_lado():
    hoje, antes = indicativas(CGOS16=9.7, EQPA18=11.0)
    r = resumo.montar(bruto_2036(NEGOCIOS_2036, anbima_do_pregao(hoje, antes=antes)), CFG, LIVRO, {})
    rf = r["renda_fixa"]
    eqpa, cgos = (next(l for l in rf["papeis"]["deb_incentivada"] if l["codigo"] == c) for c in ("EQPA18", "CGOS16"))
    # pelos negocios da B3 as duas estariam a 46 pontos-base uma da outra; pela indicativa, a 3
    assert (eqpa["taxa_media"], cgos["taxa_media"]) == (7.7, 8.16) and eqpa["negocios"] == 9
    assert eqpa["ref"] == {"taxa": 8.1553, "fonte": "anbima", "data": D, "premio_dap_pb": 60, "premio_base": "duration",
                           "var_pb": 11.0, "var_contra": "2026-09-28"}
    assert cgos["ref"]["taxa"] == 8.1894 and round((cgos["ref"]["taxa"] - eqpa["ref"]["taxa"]) * 100) == 3
    # o que a ANBIMA publicou do papel fica guardado, com a data do arquivo
    a = cgos["anbima"]
    assert {k: a[k] for k in ("data", "indicativa", "compra", "venda", "pu", "duration_du", "duration_anos")} == {
        "data": D, "indicativa": 8.1894, "compra": 8.4875, "venda": 7.9828, "pu": 1027.553709, "duration_du": 1544.4, "duration_anos": 6.13}
    assert (a["pct_pu_par"], a["desvio"], a["repac_venc"], a["ntnb_ref"], a["var_pb"], a["comparado_com"]) == (
        90.6615, 0.085, "2036-05-15", "2035-05-15", 9.7, "2026-09-28")
    # premio sobre o DAP: 7,63% em mai/31 (4,62 anos) e 7,44% em mai/35 (8,62 anos). Na duration de 6,13 anos o juro real e
    # 7,56%; no vencimento (9,62 anos, alem do ultimo vertice) e 7,44%. Papel que amortiza: os dois numeros nao sao o mesmo
    assert (a["premio_dap_duration_pb"], a["premio_dap_pb"]) == (63, 75) and cgos["ref"]["premio_dap_pb"] == 63
    # a taxa dos negocios tambem ganha o premio na duration; o campo antigo segue por vencimento
    assert (cgos["premio_dap_pb"], cgos["premio_dap_duration_pb"]) == (72, 60)
    assert (eqpa["premio_dap_pb"], eqpa["premio_dap_duration_pb"]) == (26, 15)
    # a classe usa a referencia e guarda a dos negocios ao lado
    inc = rf["resumo"]["deb_incentivada"]
    assert inc["taxa_fontes"] == {"anbima": 2} and inc["taxa_ipca_mediana"] == 8.17 and inc["premio_dap_mediano_pb"] == 62
    assert inc["negocios_do_dia"]["taxa_ipca_mediana"] == 7.93 and inc["negocios_do_dia"]["premio_dap_mediano_pb"] == 49
    # a curva de credito usa a indicativa e o prazo medio; a taxa dos negocios vai junto para a dica do grafico
    ponto = next(p for p in rf["curva"] if p["codigo"] == "EQPA18")
    assert ponto == {"codigo": "EQPA18", "emissor": PARA, "anos": 6.29, "taxa": 8.1553, "volume_rs": 2.5e6, "premio_dap_pb": 60,
                     "fonte": "anbima", "base": "duration", "taxa_b3": 7.7}
    meta = rf["anbima"]
    assert (meta["situacao"], meta["data"], meta["comparado_com"], meta["papeis"], meta["cobertura_incentivadas_pct"]) == (
        "publicado", D, "2026-09-28", 7, 100.0) and "dap" not in meta
    assert not any("ANBIMA" in x for x in r["lacunas"])
    # a referencia de quem nao negociou abaixo de 30 pb nao vira sinal
    assert not [s for s in r["sinais"] if s["tipo"] == "rf_abertura"]


def test_abertura_de_taxa_vem_da_indicativa_e_cri_e_cra_seguem_pelos_negocios():
    cad = dict(CADASTRO_2036, **{"24IPCA": {"tipo": "CRI", "incentivada": False, "indexador": "IPCA", "pct_indexador": None,
                                             "taxa": 8.0, "vencimento": "2034-08-17"}})
    linhas = [neg_rf("DEB", "EQPA18", PARA, 250, 250e3, 7.60) for _ in range(8)] + [
        neg_rf("DEB", "EQPA18", PARA, 5000, 5e6, 8.10), neg_rf("DEB", "CGOS16", GOIAS, 6000, 6e6, 8.19),
        neg_rf("DEB", "CGOS28", GOIAS, 4000, 4e6, 8.20), neg_rf("CRI", "24IPCA", "OPEA SECURITIZADORA S/A", 7000, 7e6, 9.40)]
    # nos negocios a EQPA18 "abre" 45 pb contra o ultimo pregao (mudou a mistura de negocio pequeno e grande);
    # na indicativa ela andou 3,1 pb. Quem abriu de verdade foi a CGOS16: 35 pb na indicativa
    estado = {"EQPA18": [["2026-09-28", 7.51, 1000.0]], "CGOS16": [["2026-09-28", 8.17, 1000.0]], "24IPCA": [["2026-09-28", 9.00, 1000.0]]}
    hoje, antes = indicativas(EQPA18=3.1, CGOS16=35.0, CGOS28=0.4)
    r = resumo.montar(bruto_2036(linhas, anbima_do_pregao(hoje, antes=antes), cad), CFG, LIVRO, {}, rf_estado=estado)
    rf = r["renda_fixa"]
    eqpa = next(l for l in rf["papeis"]["deb_incentivada"] if l["codigo"] == "EQPA18")
    assert eqpa["var_taxa_pb"] == 45 and eqpa["ref"]["var_pb"] == 3.1            # as duas medidas ficam; a que vale e a da indicativa
    # primeiro os medidos pela indicativa, depois os medidos pelos negocios; 0,4 pb e taxa parada, nao abertura
    assert [(l["codigo"], l["ref"]["fonte"], l["ref"]["var_pb"]) for l in rf["aberturas"]] == [
        ("CGOS16", "anbima", 35.0), ("EQPA18", "anbima", 3.1), ("24IPCA", "b3", 40)]
    assert rf["fechamentos"] == []
    sinais = [s for s in r["sinais"] if s["tipo"] == "rf_abertura"]
    assert [(s["ativo"], s.get("origem"), s["data"]) for s in sinais] == [("CGOS16", "ANBIMA", D), ("24IPCA", None, D)]
    assert sinais[0]["texto"] == ("CGOS16 (Equatorial Goias Distribuidora de Ene…, debênture incentivada): a taxa indicativa da ANBIMA "
                                  "abriu 35 pb de 28/09 para 29/09, para IPCA+ 8,19%; na B3, negócios de 29/09 a IPCA+ 8,19% em R$ 6,0 mi.")
    assert sinais[0]["fonte"] == "taxa indicativa de debêntures" and sinais[0]["numeros"]["var_taxa_pb"] == 35.0
    assert "taxa média dos negócios da B3 abriu 40 pb contra 28/09" in sinais[1]["texto"] and sinais[1]["fonte"].startswith("Trade")
    assert "(ANBIMA, taxa indicativa de debêntures, 29/09)" in render.markdown(r) and "(B3, Trade + InstrumentRegistration" in render.markdown(r)


def test_papel_acompanhado_aparece_pela_indicativa_mesmo_sem_negocio_e_avisa_sem_depender_do_giro():
    cfg = dict(CFG, renda_fixa=dict(CFG["renda_fixa"], papeis=["CGOS28", "CGOS16", "NAOTEM11"]))
    hoje, antes = indicativas(CGOS28=31.0, CGOS16=-2.0)
    linhas = [neg_rf("DEB", "CGOS16", GOIAS, 300, 300e3, 7.56)]                  # um negocio pequeno; a CGOS28 nem negociou
    r = resumo.montar(bruto_2036(linhas, anbima_do_pregao(hoje, antes=antes)), cfg, LIVRO, {})
    c28, c16, fora = r["renda_fixa"]["acompanhados"]
    assert c28["sem_negocio"] and c28["negocios"] == 0 and c28["taxa_media"] is None and c28["classe"] == "deb_incentivada"
    assert c28["emissor"] == GOIAS and c28["vencimento"] == "2036-09-15" and c28["convencao"] == "IPCA+"
    assert c28["ref"] == {"taxa": 8.2311, "fonte": "anbima", "data": D, "premio_dap_pb": 69, "premio_base": "duration",
                          "var_pb": 31.0, "var_contra": "2026-09-28"}
    assert c28["anbima"]["pu"] == 999.149414 and c28["anbima"]["duration_anos"] == 6.44
    assert "sem_negocio" not in c16 and c16["taxa_media"] == 7.56 and c16["ref"]["taxa"] == 8.1894 and c16["ref"]["var_pb"] == -2.0
    assert fora == {"codigo": "NAOTEM11", "sem_negocio": True}                  # fora da B3 e da ANBIMA: lacuna, nao linha inventada
    s = [s for s in r["sinais"] if s["tipo"] == "rf_abertura"]
    assert len(s) == 1 and s[0]["ativo"] == "CGOS28" and s[0]["origem"] == "ANBIMA"
    assert s[0]["texto"].endswith("abriu 31 pb de 28/09 para 29/09, para IPCA+ 8,23%; sem negócio na B3 em 29/09.")
    # quem nao negociou nao entra nos totais do dia nem na curva
    assert r["renda_fixa"]["resumo"]["deb_incentivada"]["papeis"] == 1 and r["renda_fixa"]["papeis_negociados"] == 1
    assert r["renda_fixa"]["curva"] == []                                        # a CGOS16 ficou abaixo do volume minimo


def test_arquivo_da_anbima_de_outro_pregao_leva_a_data_dele_e_nao_mede_a_variacao_do_dia():
    hoje, antes = indicativas(CGOS16=35.0)
    dap_de_ontem = [[1.88, 7.40, "DAPQ28"], [4.62, 7.60, "DAPK31"], [8.62, 7.50, "DAPK35"]]
    anb = anbima_do_pregao(hoje, data="2026-09-28", antes=antes, data_antes="2026-09-25", situacao="anterior", dap=dap_de_ontem)
    b = bruto_2036(NEGOCIOS_2036, anb)
    b["index"]["coletado_em"] = "2026-09-30T00:41:00Z"                           # a rodada das 21h40 do proprio pregao
    r = resumo.montar(b, CFG, LIVRO, {})
    rf = r["renda_fixa"]
    cgos = next(l for l in rf["papeis"]["deb_incentivada"] if l["codigo"] == "CGOS16")
    # vale a indicativa de 28/09, com a data; o premio e contra o DAP de 28/09 (7,56% em 6,13 anos), nao contra o de hoje
    assert cgos["ref"] == {"taxa": 8.1894, "fonte": "anbima", "data": "2026-09-28", "premio_dap_pb": 63, "premio_base": "duration"}
    assert cgos["anbima"]["var_pb"] == 35.0 and cgos["anbima"]["comparado_com"] == "2026-09-25"      # fica guardada, com as datas dela
    assert rf["aberturas"] == [] and not [s for s in r["sinais"] if s["tipo"] == "rf_abertura"]      # a de 28/09 ja foi contada em 28/09
    assert rf["anbima"]["situacao"] == "anterior" and rf["anbima"]["data"] == "2026-09-28" and rf["anbima"]["dap"] == dap_de_ontem
    assert any("o arquivo de taxas indicativas de 29/09 ainda não foi publicado; as debêntures usam as indicativas de 28/09" in x
               for x in r["lacunas"])
    # a rodada da manha seguinte ainda pode estar esperando; dias depois, o arquivo ja saiu do site
    b["index"]["coletado_em"] = "2026-09-30T11:36:00Z"
    assert any("de 29/09 não tinha sido publicado até esta coleta; as debêntures usam as indicativas de 28/09, e a variação do dia pela "
               "indicativa fica sem medida até ele chegar." in x for x in resumo.montar(b, CFG, LIVRO, {})["lacunas"])
    b["index"]["coletado_em"] = "2026-10-05T12:00:00Z"
    assert any("de 29/09 não está no site da ANBIMA (ela guarda poucos dias); as debêntures usam as indicativas de 28/09, e a variação do "
               "dia pela indicativa não foi medida." in x for x in resumo.montar(b, CFG, LIVRO, {})["lacunas"])
    # o arquivo do pregao existia mas nao pode ser lido: o motivo e a falha, nao a espera
    b["anbima"] = dict(anb, tentativas={D: "falhou", "2026-09-28": "publicado"}, erro="arquivo de 2026-09-29: HTTP 403")
    assert any("de 29/09 não pôde ser lido (arquivo de 2026-09-29: HTTP 403); as debêntures usam as indicativas de 28/09" in x
               for x in resumo.montar(b, CFG, LIVRO, {})["lacunas"])
    # sem a curva do DAP daquela data a indicativa sai sem premio, e isso fica escrito
    r = resumo.montar(bruto_2036(NEGOCIOS_2036, dict(anb, dap=None)), CFG, LIVRO, {})
    cgos = next(l for l in r["renda_fixa"]["papeis"]["deb_incentivada"] if l["codigo"] == "CGOS16")
    assert cgos["ref"] == {"taxa": 8.1894, "fonte": "anbima", "data": "2026-09-28"}
    assert any("sem a curva do DAP de 28/09" in x for x in r["lacunas"]) and "dap" not in r["renda_fixa"]["anbima"]


def test_sem_anbima_a_renda_fixa_volta_para_os_negocios_da_b3_e_declara_a_lacuna():
    falhou = {"pregao": D, "situacao": "falhou", "arquivo": None, "anterior": None, "tentativas": {D: "falhou"},
              "erro": "arquivo de 2026-09-29: falha de rede"}
    r = resumo.montar(bruto_2036(NEGOCIOS_2036, falhou), CFG, LIVRO, {})
    rf = r["renda_fixa"]
    eqpa = next(l for l in rf["papeis"]["deb_incentivada"] if l["codigo"] == "EQPA18")
    assert eqpa["ref"] == {"taxa": 7.7, "fonte": "b3", "data": D, "premio_dap_pb": 26, "premio_base": "vencimento"} and "anbima" not in eqpa
    assert rf["resumo"]["deb_incentivada"]["taxa_fontes"] == {"b3": 2} and "negocios_do_dia" not in rf["resumo"]["deb_incentivada"]
    assert rf["anbima"] == {"fonte": anbima.FONTE, "pedido": D, "situacao": "falhou", "tentativas": {D: "falhou"},
                            "erro": "arquivo de 2026-09-29: falha de rede"}
    assert any(x == "ANBIMA: a leitura das taxas indicativas falhou nesta rodada (arquivo de 2026-09-29: falha de rede); "
                    "debêntures pelos negócios da B3." for x in r["lacunas"])
    assert {p["fonte"] for p in rf["curva"]} == {"b3"} and {p["base"] for p in rf["curva"]} == {"vencimento"}
    ausente = {"pregao": D, "situacao": "ausente", "arquivo": None, "anterior": None, "tentativas": {D: "nao publicado"}}
    r = resumo.montar(bruto_2036(NEGOCIOS_2036, ausente), CFG, LIVRO, {})
    assert any("sem arquivo de taxas indicativas de 29/09 nem dos 3 dias úteis anteriores" in x for x in r["lacunas"])
    # rodada que nao consultou a ANBIMA (config desligada): tambem fica dito
    r = resumo.montar(bruto_2036(NEGOCIOS_2036), CFG, LIVRO, {})
    assert r["renda_fixa"]["anbima"]["situacao"] == "nao coletado" and any("não coletadas nesta rodada" in x for x in r["lacunas"])
    # arquivo do dia sem o anterior: ha taxa de referencia, nao ha variacao
    hoje, _ = indicativas()
    r = resumo.montar(bruto_2036(NEGOCIOS_2036, anbima_do_pregao(hoje)), CFG, LIVRO, {})
    cgos = next(l for l in r["renda_fixa"]["papeis"]["deb_incentivada"] if l["codigo"] == "CGOS16")
    assert cgos["ref"]["fonte"] == "anbima" and "var_pb" not in cgos["ref"] and any("sem o arquivo anterior ao de 29/09" in x for x in r["lacunas"])


def test_se_o_cruzamento_com_a_anbima_quebrar_o_pregao_sai_so_com_a_b3_e_nao_fica_sem_resumo(monkeypatch):
    hoje, antes = indicativas(CGOS16=35.0)
    hoje["EQPA18"]["repac_venc"] = "31/02/2036"                                  # um dado torto que a leitura deixou passar

    def quebra(*a, **k):
        raise TypeError("campo inesperado")
    monkeypatch.setattr(renda_fixa, "indicativa", quebra)
    linhas = NEGOCIOS_2036 + [neg_rf("DEB", "CGOS16", GOIAS, 6000, 6e6, 8.16)]
    r = resumo.montar(bruto_2036(linhas, anbima_do_pregao(hoje, antes=antes)), CFG, LIVRO, {})
    rf = r["renda_fixa"]
    assert rf["anbima"]["situacao"] == "falhou" and rf["anbima"]["erro"] == "cruzamento com os negocios: TypeError: campo inesperado"
    assert {l["ref"]["fonte"] for l in rf["papeis"]["deb_incentivada"]} == {"b3"} and rf["resumo"]["deb_incentivada"]["volume_rs"] == 11.5e6
    lacunas = [x for x in r["lacunas"] if "ANBIMA" in x]
    assert lacunas == ["ANBIMA: a leitura das taxas indicativas falhou nesta rodada (cruzamento com os negocios: TypeError: campo inesperado); "
                       "debêntures pelos negócios da B3."]                       # uma vez so: a tentativa que quebrou nao deixa rastro
    assert not [s for s in r["sinais"] if s.get("origem")]
    # a leitura do arquivo ja recusa data que nao existe, em vez de deixar o resumo tropecar nela
    assert anbima._data("31/02/2036") is None and anbima._data("15/05/2036") == "2036-05-15" and anbima._data("") is None


def test_indicativa_em_outra_convencao_ou_sem_taxa_nao_substitui_a_dos_negocios():
    hoje, antes = indicativas()
    # o cadastro da B3 diz DI e o arquivo da ANBIMA diz IPCA: as duas taxas nao falam a mesma lingua
    cad = dict(CADASTRO_2036, CGOS16=dict(CADASTRO_2036["CGOS16"], indexador="DI", pct_indexador=100),
               ABSP12={"tipo": "DEB", "incentivada": True, "indexador": "DI", "pct_indexador": 100, "taxa": 1.95, "vencimento": "2026-10-15"})
    linhas = [neg_rf("DEB", "CGOS16", GOIAS, 3000, 3e6, 1.20), neg_rf("DEB", "ABSP12", "AGUAS DE BOMBINHAS", 1000, 1e6, 2.10)]
    rf = resumo.montar(bruto_2036(linhas, anbima_do_pregao(hoje, antes=antes), cad), CFG, LIVRO, {})["renda_fixa"]
    cgos, absp = (next(l for l in rf["papeis"]["deb_incentivada"] if l["codigo"] == c) for c in ("CGOS16", "ABSP12"))
    assert cgos["convencao"] == "CDI+" and cgos["ref"] == {"taxa": 1.2, "fonte": "b3", "data": D}
    assert cgos["anbima"]["indicativa"] == 8.1894 and cgos["anbima"]["convencao"] == "IPCA+"        # guardada, mas nao usada
    # a ANBIMA lista o papel com `--`: nao ha indicativa, vale a taxa dos negocios
    assert absp["anbima"]["indicativa"] is None and absp["anbima"]["pu"] is None and absp["ref"]["fonte"] == "b3"
    # resumo gravado antes de a ANBIMA entrar nao tem `ref`: a leitura monta a referencia com os negocios do proprio pregao
    antigo = {"codigo": "X", "taxa_media": 7.81, "premio_dap_pb": 37, "var_taxa_pb": 40, "comparado_com": "2026-09-28"}
    assert renda_fixa.referencia(antigo, D) == {"taxa": 7.81, "fonte": "b3", "data": D, "premio_dap_pb": 37, "premio_base": "vencimento",
                                                "var_pb": 40, "var_contra": "2026-09-28"}
    assert renda_fixa.referencia({"codigo": "X", "sem_negocio": True}, D) == {}
    assert renda_fixa.rotulo_fonte(cgos["ref"]) == "B3 negócios de 29/09"
    assert renda_fixa.rotulo_fonte({"fonte": "anbima", "data": "2026-09-30"}) == "ANBIMA indicativa de 30/09"


# As duas linhas como a ANBIMA publicou em 30/09/2026: a BRKMA6 sem taxa (so o PU, a 44% do par) e a CSNAA1 com indicativa.
ANBIMA_ESTRESSE = (ANBIMA_TXT
                   + "BRKMA6@BRASKEM S/A (*)@12/05/2029@DI + 1,75%@--@--@--@--@--@--@470,622409@44,3826@N/D@35@\n"
                   + "CSNAA1@COMPANHIA SIDERÚRGICA NACIONAL (*) (**)@10/11/2028@DI + 1,65%@--@17@17,0439@0,2372@16,8067@17,2812"
                     "@875,78364@82,5742@335,23@@\n")


def test_debenture_em_di_mais_taxa_em_estresse_fala_a_lingua_da_anbima_e_a_indicativa_vale(capsys):
    import mesa
    hoje = anbima.ler(ANBIMA_ESTRESSE)
    antes = {c: dict(p, indicativa=17.0739) if c == "CSNAA1" else p for c, p in hoje.items()}
    cfg = dict(CFG, renda_fixa=dict(CFG["renda_fixa"], papeis=["CSNAA1", "BRKMA6"]))
    linhas = NEGOCIOS_BRKMA6 + [neg_rf("DEB", "CSNAA1", "COMPANHIA SIDERURGICA NACIONAL", 12, 7572.6, 51.2123)]
    r = resumo.montar(bruto_2036(linhas, anbima_do_pregao(hoje, antes=antes), CADASTRO_DI), cfg, LIVRO, {})
    r.pop("_apoio")
    csna, brkm = r["renda_fixa"]["acompanhados"]
    # 51,21 lido como percentual do CDI nao falava a lingua da ANBIMA (DI + 1,65%), e a indicativa ficava de fora da referencia
    assert csna["convencao"] == "CDI+" and "convencao" not in csna["anbima"] and csna["taxa_media"] == 51.2123
    assert csna["ref"] == {"taxa": 17.0439, "fonte": "anbima", "data": D, "var_pb": -3.0, "var_contra": "2026-09-28"}
    # a ANBIMA lista a BRKMA6 sem taxa: vale a dos negocios, lida como premio sobre o CDI, e o PU em % do par fica guardado
    assert brkm["convencao"] == "CDI+" and "convencao" not in brkm["anbima"] and brkm["anbima"]["pct_pu_par"] == 44.3826
    assert brkm["ref"] == {"taxa": 54.3298, "fonte": "b3", "data": D}
    assert mesa._boletim_rf(r) == 0
    tela = capsys.readouterr().out
    assert "ANBIMA indicativa de 29/09: CDI+ 17,04%" in tela and "B3 negocios de 29/09: CDI+ 51,21%" in tela
    assert "B3 negocios de 29/09: CDI+ 54,33%" in tela and "CONVENCAO DIFERENTE" not in tela and "do CDI" not in tela
    md = render.markdown(r)
    assert "| CSNAA1 | CDI+ 17,04% (ANBIMA indicativa de 29/09) | CDI+ 51,21%, R$ 7,6 mil | - |" in md
    assert "| BRKMA6 | CDI+ 54,33% (B3 negócios de 29/09) | R$ 15,0 mi | - |" in md
    assert "- BRKMA6, ANBIMA de 29/09: PU R$ 470,62 (44,4% do par)." in md and "convenção diferente" not in md
    ficha = _secao_rf(painel.pagina(r, {})).split("Papéis que você acompanha", 1)[1].split("Mais negociados do dia", 1)[0]
    assert "CDI+ 17,04%" in ficha and "CDI+ 54,33%" in ficha and "do CDI" not in ficha


def test_dap_da_indicativa_de_outro_pregao_vem_do_resumo_guardado_daquele_pregao(tmp_path):
    import json
    import boletim_b3
    (tmp_path / "2026-09-28").mkdir()
    (tmp_path / "2026-09-28" / "resumo.json").write_text(json.dumps({"renda_fixa": {"dap": [[1.88, 7.4, "DAPQ28"], [4.62, 7.6, "DAPK31"]]}}))
    b = {"pregao": D, "anbima": {"situacao": "anterior", "arquivo": {"data": "2026-09-28", "papeis": {}}}}
    boletim_b3.dap_da_indicativa(str(tmp_path), b)
    assert b["anbima"]["dap"] == [[1.88, 7.4, "DAPQ28"], [4.62, 7.6, "DAPK31"]]
    # arquivo do proprio pregao usa o DAP do proprio pregao: nada a buscar; sem o resumo guardado, lista vazia e a lacuna sai no resumo
    b = {"pregao": D, "anbima": {"situacao": "publicado", "arquivo": {"data": D, "papeis": {}}}}
    boletim_b3.dap_da_indicativa(str(tmp_path), b)
    assert "dap" not in b["anbima"]
    b = {"pregao": D, "anbima": {"situacao": "anterior", "arquivo": {"data": "2026-09-25", "papeis": {}}}}
    boletim_b3.dap_da_indicativa(str(tmp_path), b)
    assert b["anbima"]["dap"] == []
    boletim_b3.dap_da_indicativa(str(tmp_path), {"pregao": D})                   # rodada sem ANBIMA nao quebra


# Casos de borda achados na revisao de 01/10/2026: prazo medio abaixo de um ano, indicativa sem duration, taxa em
# percentual do CDI, papel que a ANBIMA lista sem taxa e papel fora dos dois lugares.
ANBIMA_BORDAS = (ANBIMA_TXT
                 + "CTGE11@CTG BRASIL GERACAO S.A. (*)@15/11/2028@IPCA + 5,5%@6,2@5,9@6,0604@0,05@6,0104@6,1104@512,3@99,1@242,07@@15/08/2028\n"
                 + "SEMD11@SEM DURATION S.A.@15/05/2033@IPCA + 6%@8,1@7,9@8,0@0,05@7,95@8,05@1000@99@N/D@@\n"
                 + "RISP24@AGUAS DO RIO 1 SPE S.A (*)@15/09/2042@IPCA + 7,69%@12,3@11,9@12,06@0,2@11,86@12,26@1350,5@80,1@2000@@15/05/2035\n")
CADASTRO_BORDAS = dict(
    CADASTRO_2036, RISP24=CADASTRO["RISP24"],
    CTGE11={"tipo": "DEB", "incentivada": True, "indexador": "IPCA", "pct_indexador": None, "taxa": 5.5, "vencimento": "2028-11-15"},
    SEMD11={"tipo": "DEB", "incentivada": True, "indexador": "IPCA", "pct_indexador": None, "taxa": 6.0, "vencimento": "2033-05-15"},
    KLBNA2={"tipo": "DEB", "incentivada": False, "indexador": "DI", "pct_indexador": 114.65, "taxa": 0, "vencimento": "2029-06-19"})
NEGOCIOS_BORDAS = [neg_rf("DEB", "CTGE11", "CTG BRASIL GERACAO S.A.", 4000, 4e6, 6.10), neg_rf("DEB", "SEMD11", "SEM DURATION S.A.", 4000, 4e6, 8.05),
                   neg_rf("DEB", "CGOS16", GOIAS, 3000, 3e6, 8.16), neg_rf("DEB", "RISP24", "AGUAS DO RIO 1 SPE S.A", 20000, 27e6, 12.50)]


def _resumo_bordas(**anb):
    cfg = dict(CFG, renda_fixa=dict(CFG["renda_fixa"], papeis=["CTGE11", "KLBNA2", "ABSP12", "NAOTEM11"]))
    hoje = anbima.ler(ANBIMA_BORDAS)
    # a KLBNA2 sobe 0,40 ponto de percentual do CDI de um arquivo para o outro; o resto fica parado
    antes = {c: dict(p, indicativa=round(p["indicativa"] - 0.4, 4) if c == "KLBNA2" else p["indicativa"]) for c, p in hoje.items()}
    bloco = anbima_do_pregao(hoje, antes=antes, **anb) if anb.get("situacao") != "falhou" else dict(
        {"pregao": D, "arquivo": None, "anterior": None}, **anb)
    r = resumo.montar(bruto_2036(NEGOCIOS_BORDAS, bloco, CADASTRO_BORDAS), cfg, LIVRO, {})
    r.pop("_apoio")
    return r


def test_premio_da_indicativa_e_na_duration_e_prazo_medio_abaixo_de_um_ano_fica_sem_premio():
    r = _resumo_bordas()
    rf = r["renda_fixa"]
    por = {l["codigo"]: l for l in rf["papeis"]["deb_incentivada"]}
    # CTGE11: prazo medio de 0,96 ano e Repac./Venc. a 2,1 anos. O DAP nao serve de referencia abaixo de um ano: o papel
    # fica sem premio, em vez de ganhar o do vencimento (-135 pb contra o DAP de 2,1 anos) com o rotulo de "duration"
    ctge = por["CTGE11"]
    assert ctge["anbima"]["duration_anos"] == 0.96 and "premio_dap_duration_pb" not in ctge["anbima"] and ctge["anbima"]["premio_dap_pb"] == -135
    assert ctge["ref"] == {"taxa": 6.0604, "fonte": "anbima", "data": D, "var_pb": 0.0, "var_contra": "2026-09-28"}
    # SEMD11: a ANBIMA deu a taxa e nao deu a duration (N/D): ai vale o vencimento, e `premio_base` diz isso
    assert por["SEMD11"]["anbima"]["duration_anos"] is None
    assert (por["SEMD11"]["ref"]["premio_dap_pb"], por["SEMD11"]["ref"]["premio_base"]) == (47, "vencimento")
    assert (por["RISP24"]["ref"]["premio_dap_pb"], por["RISP24"]["ref"]["premio_base"]) == (459, "duration")
    # curva: a indicativa vai no prazo medio (mesmo curto, sem premio); sem duration o ponto nao tem lugar no eixo
    assert [(p["codigo"], p["anos"], p["base"], p["premio_dap_pb"]) for p in rf["curva"]] == [
        ("RISP24", 7.94, "duration", 459), ("CTGE11", 0.96, "duration", None), ("CGOS16", 6.13, "duration", 63)]
    # a mediana de premio da classe sai dos tres papeis que tem premio: 47, 63 e 459
    assert rf["resumo"]["deb_incentivada"]["premio_dap_mediano_pb"] == 63 and rf["resumo"]["deb_incentivada"]["papeis_ipca"] == 4
    s = _secao_rf(painel.pagina(r, {}))
    assert '–<span class="peq">prazo médio abaixo de um ano</span>' in s                    # na tabela, a lacuna com o motivo
    assert "prazo médio de 0,96 ano: curto demais para o DAP servir de referência" in s     # na ficha do papel acompanhado
    assert '<span class="peq">no vencimento</span>' in s
    g, _ = painel.svg_dispersao(rf["curva"] + [dict(rf["curva"][0], codigo="OUTRO11", anos=5.0)], rf["dap"], {"anbima": D, "b3": D, "dap": D})
    assert "IPCA + 6,06% · ANBIMA indicativa de 29/09|prazo médio de 0,96 anos (duration)|B3 negócios de 29/09: IPCA + 6,10%, R$ 4,0 mi" in g
    md = render.markdown(r)
    assert "| CTGE11 | IPCA+ 6,06% (ANBIMA indicativa de 29/09) | IPCA+ 6,10%, R$ 4,0 mi | - |" in md
    assert "duration de 0,96 ano (curta demais para medir o prêmio sobre o DAP); indicativa 0 pb contra 28/09." in md
    assert "IPCA+ 8,00% (ANBIMA indicativa de 29/09) | IPCA+ 8,05%, R$ 4,0 mi | +47 pb no vencimento |" in md


def test_taxa_em_percentual_do_cdi_nao_tem_variacao_em_pontos_base_nem_sinal_de_abertura(capsys):
    import mesa
    r = _resumo_bordas()
    klbn = next(l for l in r["renda_fixa"]["acompanhados"] if l["codigo"] == "KLBNA2")
    # 104,10% -> 104,50% do CDI: 0,40 ponto de percentual do CDI nao e "40 pb" de taxa
    assert klbn["convencao"] == "% do CDI" and klbn["ref"] == {"taxa": 104.5, "fonte": "anbima", "data": D}
    assert "var_pb" not in klbn["anbima"] and not [s for s in r["sinais"] if s["tipo"] == "rf_abertura"]
    s = _secao_rf(painel.pagina(r, {}))
    assert '<div class="val">104,5% do CDI</div><div class="pe">ANBIMA indicativa de 29/09</div>' in s
    assert "em % do CDI · a quanto o mercado compra e a quanto vende · ANBIMA de 29/09" in s
    assert "- KLBNA2, ANBIMA de 29/09: compra 105,10% do CDI e venda 103,90% do CDI; PU R$ 1.010,25 (100,2% do par); duration de 2,4 anos." in render.markdown(r)
    assert mesa._boletim_rf(r) == 0
    tela = capsys.readouterr().out
    assert "ANBIMA indicativa de 29/09: 104,5% do CDI" in tela
    assert "var: sem medida contra 28/09 (papel sem taxa naquele arquivo, ou taxa em percentual do CDI)" in tela


def test_papel_acompanhado_sem_taxa_nenhuma_e_declarado_com_o_motivo_certo_nas_tres_leituras(capsys):
    import mesa
    r = _resumo_bordas()
    md = render.markdown(r)
    assert "- ABSP12, ANBIMA de 29/09: o arquivo lista o papel sem taxa nem preço." in md         # nunca o item vazio
    assert "Sem negócio neste pregão e sem taxa indicativa: ABSP12, NAOTEM11." in md             # o papel nao some do texto
    assert "Sem negócio neste pregão e sem taxa indicativa: ABSP12, NAOTEM11." in _secao_rf(painel.pagina(r, {}))
    assert mesa._boletim_rf(r) == 0
    tela = capsys.readouterr().out
    assert "ANBIMA indicativa de 29/09: sem taxa" in tela and "var: papel sem taxa neste arquivo" in tela
    assert "sem taxa de referencia neste pregao: sem negocio na B3 e o papel esta sem taxa no arquivo da ANBIMA" in tela
    assert "sem taxa de referencia neste pregao: sem negocio na B3 e o papel nao esta no arquivo da ANBIMA" in tela
    assert "prazo medio abaixo de um ano: sem premio na duration" in tela and "| -135 pb no vencimento" in tela
    # com a leitura da ANBIMA em falha, o motivo e a falha: nao se diz que o papel esta fora do arquivo
    fora = _resumo_bordas(situacao="falhou", erro="arquivo de 2026-09-29: HTTP 403")
    assert mesa._boletim_rf(fora) == 0
    tela = capsys.readouterr().out
    assert tela.count("sem taxa de referencia neste pregao: sem negocio na B3 e a leitura da ANBIMA falhou nesta rodada") == 3
    assert "fora do arquivo" not in tela and "nao esta no arquivo" not in tela
    assert "Sem negócio neste pregão e sem taxa indicativa: KLBNA2, ABSP12, NAOTEM11." in render.markdown(fora)


def test_sinal_de_premio_alto_com_arquivo_de_outro_pregao_diz_o_dia_da_indicativa_e_o_dia_dos_negocios():
    r = _resumo_bordas(data="2026-09-28", data_antes="2026-09-25", situacao="anterior",
                       tentativas={D: "nao publicado", "2026-09-28": "publicado", "2026-09-25": "publicado"},
                       dap=[[1.88, 7.40, "DAPQ28"], [4.62, 7.60, "DAPK31"], [8.62, 7.50, "DAPK35"]])
    s = next(s for s in r["sinais"] if s["tipo"] == "rf_premio_alto")
    assert s["texto"] == ("RISP24 (Aguas do Rio 1 Spe, debênture incentivada): taxa indicativa da ANBIMA de 28/09 a IPCA+ 12,06%, 454 pb acima "
                          "do juro real de mercado na duration de 7,9 anos; na B3, negócios de 29/09 a IPCA+ 12,50% em R$ 27,0 mi.")
    assert (s["data"], s["origem"]) == ("2026-09-28", "ANBIMA e B3")                              # a data do sinal e a da indicativa


def test_indicativa_em_outra_convencao_e_escrita_na_convencao_da_anbima(capsys):
    import mesa
    hoje, antes = indicativas()
    cfg = dict(CFG, renda_fixa=dict(CFG["renda_fixa"], papeis=["CGOS16"]))
    cad = dict(CADASTRO_2036, CGOS16=dict(CADASTRO_2036["CGOS16"], indexador="DI", pct_indexador=100))
    r = resumo.montar(bruto_2036([neg_rf("DEB", "CGOS16", GOIAS, 3000, 3e6, 1.20)], anbima_do_pregao(hoje, antes=antes), cad), cfg, LIVRO, {})
    r.pop("_apoio")
    assert mesa._boletim_rf(r) == 0
    tela = capsys.readouterr().out
    assert "ANBIMA indicativa de 29/09: IPCA+ 8,19%" in tela and "ANBIMA indicativa de 29/09: CDI+ 8,19%" not in tela
    assert "[CONVENCAO DIFERENTE: a ANBIMA escreve a taxa em IPCA+ e a B3 em CDI+; nao se comparam, vale a dos negocios]" in tela
    assert "vale para comparar: B3 negocios de 29/09" in tela
    assert ("- CGOS16, ANBIMA de 29/09: indicativa a IPCA+ 8,19%, em convenção diferente da dos negócios da B3 (CDI+); as duas taxas não se "
            "comparam e vale a dos negócios.") in render.markdown(r)
    ficha = _secao_rf(painel.pagina(r, {})).split("Papéis que você acompanha", 1)[1].split("Mais negociados do dia", 1)[0]
    assert "CDI+ 1,20%" in ficha and "8,19" not in ficha and "Compra · venda" not in ficha       # a ficha fica so com a taxa que vale


def test_texto_ou_painel_que_quebra_nao_leva_junto_o_resumo_o_historico_e_o_manifest(tmp_path, monkeypatch):
    import json
    import boletim_b3
    hoje, antes = indicativas()

    def falsa_coleta(cli, d, pasta, **kw):
        return bruto_2036(NEGOCIOS_2036, anbima_do_pregao(hoje, antes=antes))

    def sem_arquivo(cli, nome, d):
        raise b3.B3Erro("sem arquivo")

    def quebra(*a, **k):
        raise OverflowError("cannot convert float infinity to integer")
    monkeypatch.setattr(boletim_b3.coleta, "coletar_pregao", falsa_coleta)
    monkeypatch.setattr(boletim_b3.b3, "arquivo", sem_arquivo)
    monkeypatch.setattr(boletim_b3.b3, "catalogo", lambda cli: [])
    monkeypatch.setattr(boletim_b3, "Cliente", lambda: type("C", (), {"tipo": "teste"})())
    monkeypatch.setattr(boletim_b3.painel, "pagina", quebra)
    assert boletim_b3.main(["--saida", str(tmp_path), "--dias", "1", "--data", D]) == 0
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["ultimo_pregao"] == D and D in manifest["pregoes"]
    assert any(f.startswith(f"{D}: resumo.md ou painel.html: OverflowError") for f in manifest["falhas"])
    assert json.loads((tmp_path / D / "resumo.json").read_text())["renda_fixa"]["anbima"]["situacao"] == "publicado"
    assert D in json.loads((tmp_path / "historico.json").read_text())["pregoes"] and not (tmp_path / "painel.html").exists()


# ------------------------------------------------------------------ fonte e dia de cada taxa na tela

def _resumo_2036(anb="publicado"):
    cfg = dict(CFG, renda_fixa=dict(CFG["renda_fixa"], papeis=["CGOS16", "CGOS28"]))
    cad = dict(CADASTRO_2036, **{"24IPCA": {"tipo": "CRI", "incentivada": False, "indexador": "IPCA", "pct_indexador": None,
                                             "taxa": 8.0, "vencimento": "2034-08-17"}})
    for i in range(4):
        cad[f"DEBX{i}"] = {"tipo": "DEB", "incentivada": True, "indexador": "IPCA", "pct_indexador": None, "taxa": 6.0,
                           "vencimento": f"20{31 + i}-05-15"}
    linhas = NEGOCIOS_2036 + [neg_rf("DEB", f"DEBX{i}", "EMISSOR X", 4000, 4e6, 7.6 + i * 0.2) for i in range(4)] + [
        neg_rf("CRI", "24IPCA", "OPEA SECURITIZADORA S/A", 7000, 7e6, 9.40)]
    hoje, antes = indicativas(CGOS16=35.0, EQPA18=-12.5)
    estado = {"24IPCA": [["2026-09-28", 9.00, 1000.0]], "DEBX3": [["2026-09-28", 8.50, 1000.0]]}
    if anb == "publicado":
        bloco = anbima_do_pregao(hoje, antes=antes)
    elif anb == "anterior":
        bloco = anbima_do_pregao(hoje, data="2026-09-28", antes=antes, data_antes="2026-09-25", situacao="anterior",
                                 dap=[[1.88, 7.40, "DAPQ28"], [4.62, 7.60, "DAPK31"], [8.62, 7.50, "DAPK35"]])
    else:
        bloco = {"pregao": D, "situacao": "falhou", "arquivo": None, "anterior": None, "erro": "arquivo de 2026-09-29: falha de rede"}
    r = resumo.montar(bruto_2036(linhas, bloco, cad), cfg, LIVRO, {}, rf_estado=estado)
    r.pop("_apoio")
    return r


def _secao_rf(h):
    return h.split('<section id="renda-fixa">', 1)[1].split("</section>", 1)[0]


def test_painel_diz_de_onde_vem_cada_taxa_anbima_indicativa_ou_b3_negocios_com_o_dia():
    r = _resumo_2036()
    h = painel.pagina(r, {})
    s = _secao_rf(h)
    assert '<span class="tag">ANBIMA indicativa de 29/09</span> Debêntures: taxa de referência do mercado profissional, de 7 papéis' in s
    assert "no arquivo publicado em 29/09 às 19h56" in s and "Cobre 26% do volume de incentivadas negociado no dia." in s
    assert '<span class="tag">B3 negócios de 29/09</span> CRI e CRA, e a taxa dos negócios do dia das debêntures' in s
    # papel acompanhado: a indicativa, compra e venda, PU, duration e, ao lado, os negocios do dia
    ficha = s.split("Papéis que você acompanha", 1)[1].split("Mais negociados do dia", 1)[0]
    for trecho in ("IPCA+ 8,19%", "ANBIMA indicativa de 29/09 · +35 pb vs 28/09", "8,49% · 7,98%", "ANBIMA de 29/09", "R$ 1.027,55",
                   "90,7% do valor ao par", "contra o DAP de 29/09 na duration de 6,1 anos", "+75 pb no vencimento",
                   '<div class="rot">B3 negócios de 29/09</div><div class="val">IPCA+ 8,16%</div>', "R$ 3,0 mi em 1 negócio",
                   '<span class="mut">sem negócio</span>', "vence em 15/09/2036"):
        assert trecho in ficha, trecho
    # tabela dos mais negociados: referencia com a fonte, e os negocios do dia ao lado
    tabela = s.split("Mais negociados do dia", 1)[1]
    assert "<th class=\"n\">Taxa de referência</th><th class=\"n\">B3 negócios de 29/09</th>" in tabela
    assert 'IPCA+ 8,16%<span class="peq">ANBIMA indicativa de 29/09</span>' in tabela        # EQPA18 pela indicativa (8,1553)
    assert 'IPCA+ 7,70%<span class="peq">R$ 2,5 mi · 9 negócios</span>' in tabela           # ...e pelos negocios
    assert 'IPCA+ 7,60%<span class="peq">B3 negócios de 29/09</span>' in tabela             # DEBX0 nao esta no arquivo da ANBIMA
    assert '<span class="peq">na duration de 6,3 anos</span>' in tabela and '<span class="peq">no vencimento</span>' in tabela
    # quem abriu e fechou: um card por fonte
    assert 'Debêntures: quem abriu e quem fechou taxa <span class="tag">ANBIMA indicativa de 29/09</span>' in s
    assert "Variação da taxa indicativa da ANBIMA de 28/09 para 29/09" in s
    assert 'CRI, CRA e debêntures sem indicativa: quem abriu e quem fechou taxa <span class="tag">B3 negócios de 29/09</span>' in s
    # grafico: circulo cheio para a indicativa, vazado para quem so tem negocio; a dica diz a fonte e o dia
    assert "ANBIMA indicativa de 29/09, no prazo médio" in s and "B3 negócios de 29/09, no vencimento" in s
    assert "IPCA + 8,16% · ANBIMA indicativa de 29/09|prazo médio de 6,3 anos (duration)|+60 pb sobre o DAP|B3 negócios de 29/09: IPCA + 7,70%, R$ 2,5 mi" in s
    assert s.count('stroke="#c2702a"') == 4 and "IPCA + 7,60% · B3 negócios de 29/09|4,6 anos até o vencimento" in s
    # indicador do topo, numeros ao lado da curva e emissores tambem dizem a fonte e o dia; a mediana e a media misturam as duas
    assert "volume na B3; taxa: ANBIMA indicativa de 29/09 (B3 negócios onde não há)" in h
    assert '<div class="pe">ANBIMA indicativa de 29/09; B3 negócios de 29/09 onde não há; ponderada pelo volume na B3</div>' in s
    assert "cada taxa contra o DAP do seu dia: na duration com a indicativa, no vencimento sem ela" in s
    assert '<span class="peq">ANBIMA indicativa de 29/09 em 1 de 1 série</span>' in s and '<span class="peq">B3 negócios de 29/09</span>' in s
    # sinal e rodape dizem de quem e o dado
    assert '<span class="ref">ANBIMA · taxa indicativa de debêntures · 29/09</span>' in h
    assert "Taxas indicativas de debêntures: ANBIMA, mercado secundário de debêntures" in h and "dados públicos da B3 e da ANBIMA" in h
    assert "None" not in h and "nan" not in h.lower().replace("financ", "")


def test_painel_com_anbima_atrasada_ou_fora_do_ar_mostra_a_data_certa_e_a_lacuna():
    tarde = _resumo_2036("anterior")
    s = _secao_rf(painel.pagina(tarde, {}))
    assert '<span class="tag velho">ANBIMA indicativa de 28/09</span>' in s                  # etiqueta amarela: dado de outro pregao
    assert "Sem o arquivo de 29/09 até esta coleta: a variação do dia pela indicativa não foi medida." in s
    assert "A variação do dia pela taxa indicativa sai quando a ANBIMA publicar o arquivo de 29/09" in s
    assert "contra o DAP de 28/09 na duration de 6,1 anos" in s and "juro real de mercado (DAP de 28/09)" in s
    assert "ANBIMA indicativa de 29/09" not in s
    fora = _resumo_2036("fora")
    h = painel.pagina(fora, {})
    s = _secao_rf(h)
    assert '<span class="tag velho">ANBIMA sem indicativa</span> Taxa indicativa das debêntures: a leitura falhou nesta rodada.' in s
    assert '<span class="tag">B3 negócios de 29/09</span> Debêntures, CRI e CRA' in s and "ANBIMA indicativa de" not in s
    assert 'Quem abriu e quem fechou taxa <span class="tag">B3 negócios de 29/09</span>' in s and 'stroke="#c2702a"' not in s
    assert "ANBIMA: a leitura das taxas indicativas falhou nesta rodada" in h and "dados públicos da B3. Não" in h


def test_resumo_de_antes_da_anbima_continua_legivel_no_painel_no_texto_e_no_mesa(capsys):
    import copy
    import mesa
    r = copy.deepcopy(_resumo_2036("fora"))
    rf = r["renda_fixa"]
    rf.pop("anbima")                                                                # o formato gravado ate 01/10/2026

    def limpa(x):
        if isinstance(x, dict):
            for k in ("ref", "anbima", "fonte", "base", "taxa_fontes", "negocios_do_dia", "sem_negocio"):
                if k != "fonte" or "anos" in x:
                    x.pop(k, None)
            for v in x.values():
                limpa(v)
        elif isinstance(x, list):
            for v in x:
                limpa(v)
    limpa(rf)
    assert rf["fonte"]["tabela"] == "Trade" and "ref" not in rf["papeis"]["deb_incentivada"][0]
    s = _secao_rf(painel.pagina(r, {}))
    assert "B3 negócios de 29/09" in s and "ANBIMA" not in s and 'IPCA+ 7,70%<span class="peq">B3 negócios de 29/09</span>' in s
    md = render.markdown(r)
    assert "**De onde vem cada taxa:** negócios da B3 de 29/09." in md and "IPCA+ 7,70% (B3 negócios de 29/09)" in md
    assert mesa._boletim_rf(r) == 0
    tela = capsys.readouterr().out
    assert "ANBIMA: este resumo e de antes de a taxa indicativa entrar no boletim; so negocios da B3" in tela
    assert "B3 negocios de 29/09" in tela and "ANBIMA indicativa" not in tela.replace("taxa ref = a que vale", "").split("\n-- por classe")[1]


def test_resumo_em_texto_diz_a_fonte_de_cada_taxa_em_tabelas_de_ate_4_colunas():
    md = render.markdown(_resumo_2036())
    assert ("**De onde vem cada taxa:** debêntures pela taxa indicativa da ANBIMA de 29/09 (7 papéis), com os negócios da B3 de 29/09 "
            "ao lado; CRI e CRA só pelos negócios da B3.") in md
    assert "| Papel | Taxa de referência | B3 negócios de 29/09 | Sobre o juro real |" in md
    assert "| CGOS16 | IPCA+ 8,19% (ANBIMA indicativa de 29/09) | IPCA+ 8,16%, R$ 3,0 mi | +63 pb na duration |" in md
    assert "| CGOS28 | IPCA+ 8,23% (ANBIMA indicativa de 29/09) | sem negócio | +69 pb na duration |" in md
    assert ("- CGOS16, ANBIMA de 29/09: compra 8,49% e venda 7,98%; PU R$ 1.027,55 (90,7% do par); duration de 6,1 anos; "
            "indicativa +35 pb contra 28/09.") in md
    # DEBX0 vence em mai/31, em cima do vertice de 7,63% do DAP: 7,60% fica 3 pb abaixo do juro real
    assert "| DEBX0 (Emissor X) | IPCA+ 7,60% (B3 negócios de 29/09) | R$ 4,0 mi | -3 pb no vencimento |" in md
    assert "- CGOS28, ANBIMA de 29/09: compra 8,39% e venda 8,07%; PU R$ 999,15 (90,9% do par); duration de 6,4 anos; indicativa 0 pb contra 28/09." in md
    assert "**Abriram taxa pela indicativa da ANBIMA:** CGOS16 +35 pb contra 28/09, para IPCA+ 8,19% (R$ 3,0 mi)." in md
    assert "**Abriram taxa pelos negócios da B3:** 24IPCA +40 pb contra 28/09, para IPCA+ 9,40% (R$ 7,0 mi)." in md
    assert "**Fecharam taxa pelos negócios da B3:** DEBX3 −30 pb" in md or "**Fecharam taxa pelos negócios da B3:** DEBX3 -30 pb" in md
    assert "Nas incentivadas, a mediana pelos negócios do dia (B3 negócios de 29/09) foi IPCA+" in md
    for linha in md.splitlines():
        if linha.startswith("|"):
            assert linha.count("|") <= 5, linha
    tarde = render.markdown(_resumo_2036("anterior"))
    assert "pela taxa indicativa da ANBIMA de 28/09" in tarde and "Sem o arquivo da ANBIMA de 29/09 até esta coleta" in tarde
    assert "sem taxa indicativa da ANBIMA nesta rodada (falhou)" in render.markdown(_resumo_2036("fora"))


def test_mesa_boletim_rf_mostra_a_fonte_e_o_dia_de_cada_taxa(capsys):
    import mesa
    assert mesa._boletim_rf(_resumo_2036()) == 0
    tela = capsys.readouterr().out
    assert "B3 negocios de 29/09: tabelas Trade + InstrumentRegistration [PRELIMINAR" in tela
    assert "ANBIMA indicativa de 29/09: 7 debentures, arquivo publicado em 2026-09-29T19:56:25; variacao contra 28/09" in tela
    # papel acompanhado: indicativa, compra, venda, PU, duration, premio nas duas bases e os negocios do dia
    assert ("ANBIMA indicativa de 29/09: IPCA+ 8,19% | compra 8,49% venda 7,98% | PU 1.027,55 (90,66% do par) | duration 1.544 dias uteis "
            "(6,13 anos) | var +35 pb contra 28/09") in tela
    assert "premio da indicativa sobre o DAP de 29/09: +63 pb na duration | +75 pb no vencimento" in tela
    assert "B3 negocios de 29/09: IPCA+ 8,16% (min 8,16 max 8,16) | R$ 3,00 mi em 1 negocios" in tela
    assert "B3 negocios de 29/09: sem negocio" in tela and "vale para comparar: ANBIMA indicativa de 29/09" in tela
    # tabela: a taxa de referencia com a fonte e, ao lado, a dos negocios
    linha = next(l for l in tela.splitlines() if l.strip().startswith("EQPA18"))
    assert "IPCA+ 8,16%  ANBIMA indicativa de 29/09" in linha and "IPCA+ 7,70%" in linha and "+60 dur" in linha and "-12,5" in linha
    linha = next(l for l in tela.splitlines() if l.strip().startswith("DEBX0"))
    assert "IPCA+ 7,60%  B3 negocios de 29/09" in linha and " = " in linha and "venc" in linha
    assert "-- abriram taxa pela indicativa da ANBIMA de 29/09 contra 28/09" in tela
    assert "-- abriram taxa pelos negocios da B3 de 29/09 contra o ultimo pregao com volume" in tela
    assert mesa._boletim_rf(_resumo_2036("anterior")) == 0
    tela = capsys.readouterr().out
    assert "ANBIMA indicativa de 28/09" in tela and "[ARQUIVO DE OUTRO PREGAO: o de 29/09 nao estava no site na coleta" in tela
    assert "abertura e fechamento pela indicativa: sem medida, a rodada nao tinha o arquivo da ANBIMA de 29/09" in tela
    assert mesa._boletim_rf(_resumo_2036("fora")) == 0
    tela = capsys.readouterr().out
    assert "ANBIMA: sem taxa indicativa nesta rodada (falhou: arquivo de 2026-09-29: falha de rede); debentures pelos negocios da B3" in tela
    assert "vale para comparar: B3 negocios de 29/09" in tela
