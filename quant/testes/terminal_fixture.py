"""Um mini Autopilot Terminal em pasta temporaria, com o formato real dos arquivos (conferido em 11/10/2026) e numeros pequenos,
para os testes de `quant.terminal` nao dependerem do cache de verdade. Os valores esperados dos testes foram contados a mao."""
import json
from pathlib import Path

HOJE = "2026-10-12"          # segunda-feira; os testes passam hoje=date(2026, 10, 12)


def _g(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def montar_terminal(raiz: Path) -> Path:
    out = raiz / "cache" / "out"
    _g(out / "universo.json", {"itens": [
        {"s": "PETR4", "n": "Petrobras PN", "c": "acao_br", "g": "Petroleo, Gas e Biocombustiveis", "sg": "Exploracao, Refino e Distribuicao", "m": "BRL",
         "idx": ["IBOV", "IDIV"], "isin": "BRPETRACNPR6"},
        {"s": "PRIO3", "n": "Prio ON", "c": "acao_br", "g": "Petroleo, Gas e Biocombustiveis", "sg": "Exploracao, Refino e Distribuicao", "m": "BRL", "idx": ["IBOV"]},
        {"s": "BBAS3", "n": "Banco do Brasil ON", "c": "acao_br", "g": "Financeiro", "sg": "Bancos", "m": "BRL", "idx": ["IBOV"]},
        {"s": "DIRR3", "n": "Direcional ON", "c": "acao_br", "g": "Consumo Ciclico", "sg": "Incorporacoes", "m": "BRL", "idx": []},
        {"s": "NVDC34", "n": "Nvidia BDR", "c": "bdr", "g": "Tecnologia", "sg": "Semicondutores", "m": "BRL", "idx": []},
        {"s": "NVDA", "n": "Nvidia", "c": "acao_us", "g": "Tecnologia", "sg": "Semicondutores", "m": "USD", "idx": []}]})

    # ---- TIR NOVA (a unica que o robo le desde 19/10/2026): PETR4 normal (analistas); DIRR3 em pico (numero do Safra); PRIO3 em fundo de
    #      lucro, sem o campo do premio (o leitor conta TIR menos a NTN-B 2035); ENEV3 fora da conta; VALE3 so na antiga (fica SEM TIR)
    _g(out / "pagina" / "tir_safra.json", {
        "gerado": "2026-10-12T08:30:00-03:00", "metodo": "safra_v2", "ntnb": {"venc": "2035-05-15", "taxa": 6.71, "data": "2026-10-09"},
        "empresas": {
            "PETR4": {"t": "PETR4", "base": "analistas", "tipo": "real", "tir": 0.18389, "premio_ntnb35_pp": 11.68, "preco": 56.0, "preco_data": "2026-10-09",
                      "analistas": {"alvo_medio": 58.31, "n": 13, "potencial": 0.041, "coleta": "2026-10-11"}, "safra": None, "confianca": "analistas",
                      "avisos": ["preco-alvo de 13 casas"], "ciclo_do_lucro": "normal"},
            "DIRR3": {"t": "DIRR3", "base": "safra", "tipo": "real", "tir": 0.10, "premio_ntnb35_pp": 3.29, "preco": 12.3, "preco_data": "2026-10-09",
                      "analistas": {"alvo_medio": 14.0, "n": 3, "potencial": 0.138, "coleta": "2026-10-11"},
                      "safra": {"tir": 10.1, "data": "2026-10-08", "fonte": "Safra, numero passado ao Douglas"}, "confianca": "alta", "avisos": [],
                      "ciclo_do_lucro": "pico_provavel"},
            "PRIO3": {"t": "PRIO3", "base": "analistas", "tipo": "real", "tir": 0.15, "preco": 40.0, "preco_data": "2026-10-09",
                      "analistas": {"alvo_medio": 50.0, "n": 8, "potencial": 0.25, "coleta": "2026-10-11"}, "confianca": "analistas", "avisos": [],
                      "ciclo_do_lucro": "fundo"}},
        "fora": [{"t": "ENEV3", "n": "Eneva ON", "motivo": "sem preco-alvo dos analistas"}]})

    # ---- TIR ANTIGA: continua no disco do terminal, mas o robo NAO le (os testes conferem que VALE3, so daqui, fica sem TIR)
    _g(out / "pagina" / "tir.json", {
        "gerado": "2026-10-12T09:00:00-03:00", "horizonte": 10,
        "geral": {"ntnb": {"venc": "2037-05-15", "taxa": 6.71, "data": "2026-10-09"}, "k_real": 0.1171},
        "empresas": {
            "PETR4": {"t": "PETR4", "preco": 56.0, "preco_data": "2026-10-09", "balanco": "2026T2", "balanco_idade_dias": 103, "casas": 1, "g1": -0.06986,
                      "payout": 0.9, "roe": 0.3031, "mult": 5.35, "k": 0.1171, "qualidade": "consenso", "ciclica": True, "virada": False,
                      "base": {"fonte": "consenso", "texto": "consenso de 1 casa"}, "avisos": ["consenso de 1 casa: nao e consenso de verdade"],
                      "ciclo_do_lucro": {"nivel": "normal", "criterios": [], "razao": 0.99, "margem_12m": 24.32, "margem_mediana_5a": 23.56},
                      "tir": {"pl": 0.18389, "perp": 0.21013, "menor": 0.18389}, "tir_normalizada": {"tir": {"menor": 0.11542}},
                      "tir_prudente": {"v": 0.18389, "base": "hoje", "pico": False, "premio_pp": 11.68},
                      "caixa": {"tir_g0": 0.2332, "tir_g2": 0.2532, "dif_pp": -4.93, "diverge": False, "metodo": "fcl"}},
            "DIRR3": {"t": "DIRR3", "preco": 12.3, "preco_data": "2026-10-09", "casas": 3, "qualidade": "consenso",
                      "ciclo_do_lucro": {"nivel": "pico_provavel", "criterios": ["lucro 2x a media"], "razao": 2.1},
                      "tir": {"menor": 0.30}, "tir_normalizada": {"tir": {"menor": 0.10}},
                      "tir_prudente": {"v": 0.10, "base": "normalizada", "pico": True, "premio_pp": 3.29}},
            "VALE3": {"t": "VALE3", "preco": 60.0, "preco_data": "2026-10-09", "ciclo_do_lucro": {"nivel": "fundo", "razao": 0.4},
                      "tir": {"menor": 0.20}, "tir_prudente": {"v": 0.20, "base": "hoje", "pico": False, "premio_pp": 13.29}}},
        "fora": [{"t": "ENEV3", "n": "Eneva ON", "motivo": "sem payout: menos de 3 anos de dividendos"}]})

    # ---- consenso: PETR4 (1 analista no LPA), NVDA (USD), BDR aponta para NVDA, DIRR3 sem cobertura
    _g(out / "porativo" / "consenso" / "PETR4.json", {
        "s": "PETR4", "col": "2026-10-11T17:32:04-03:00", "moeda": "BRL", "preco": 56.0, "preco_t": "2026-10-09",
        "alvo": {"med": 58.31, "mdn": 58.5, "min": 47.0, "max": 65.0, "n": 13, "pot": 4.1},
        "rec": {"nota": 1.46, "rot": "Compra forte", "pc": [92.3, 92.3, 92.3, 84.6]},
        "est": {"per": [
            {"p": "0y", "fim": "2026-12-31", "l": [14.0, 13.0, 15.0, 4, 10.0, 40.0], "t": [14.0, 12.0, 11.0, 10.0], "v": [1, 0, 3, 1], "pl": 4.0},
            {"p": "+1y", "fim": "2027-12-31", "l": [13.0, 13.0, 13.0, 1, 14.0, -7.1], "t": [13.0, 13.0, 13.0, 13.0], "pl": 4.3}]},
        "hist": {"t": ["2026-10-01", "2026-10-10"], "am": [56.0, 58.31]}})
    _g(out / "porativo" / "consenso" / "NVDA.json", {
        "s": "NVDA", "col": "2026-10-11T17:00:00-03:00", "moeda": "USD", "preco": 200.0, "preco_t": "2026-10-09",
        "alvo": {"med": 240.0, "min": 150.0, "max": 300.0, "n": 40, "pot": 20.0}, "rec": {"nota": 1.3, "rot": "Compra forte", "pc": [95.0]}})
    _g(out / "porativo" / "consenso" / "NVDC34.json", {"s": "NVDC34", "ref": "NVDA", "y": "NVDA"})
    _g(out / "porativo" / "consenso" / "DIRR3.json", {"s": "DIRR3", "col": "2026-10-11T17:40:46-03:00", "sem": "o agregador nao tem analistas cobrindo este papel"})

    # ---- insiders (contas a mao no teste)
    _g(out / "porativo" / "insidersbr" / "_comum.json", {"orgaos": ["controlador", "conselho", "diretoria", "fiscal", "orgaos", "sem", "tesouraria"]})
    _g(out / "porativo" / "insidersbr" / "PETR.json", {
        "raiz": "PETR", "ate": "2026-08", "data": "2026-09-10", "entrega": {"mes": "2026-08", "data": "2026-09-10"}, "tickers": ["PETR3", "PETR4"],
        "dic": {"ativos": [["acao", "PETR4"], ["acao", "PETR3"], ["outro", "Outros COTA FGTS"]],
                "ops": ["venda \u00e0 vista", "compra \u00e0 vista", "compra", "venda"]},
        "mov": [["2026-07-31", 0, 0, 0, -1000, 40.0, None, 1, 0],           # controlador vende 1.000 a 40  -> -40.000
                ["2026-07-20", 2, 0, 1, 500, 41.0, None, 1, 0],            # diretoria compra 500 a 41      -> +20.500
                ["2026-07-10", 1, 0, 1, 100, 40.0, None, 1, 0],            # antes da janela de 90 dias (comeca em 14/07)
                ["2026-08-05", 1, 0, 3, -200, 42.0, None, 1, 0],           # conselho vende 200 a 42        -> -8.400
                ["2026-08-06", 2, 0, 1, 300, 90.0, None, 1, 1],            # preco longe do fechamento: fora da conta
                ["2026-08-07", 2, 2, 1, 10, 5.0, None, 1, 0],              # nao e acao
                ["2026-08-08", 2, 0, 2, 50, None, None, 1, 0]]})           # sem preco: conta so como aviso

    # ---- aluguel, multiplos
    _g(out / "b3_aluguel.json", {"data": "2026-10-09", "datas": ["2026-10-08", "2026-10-09"], "a": {
        "PETR4": {"saldo_qtd": 200000000, "saldo_rs": 10000000000, "taxa": 0.05, "taxa_min": 0.01, "taxa_max": 0.5, "contratos": 375, "var_d1_pct": -1.0,
                  "var_5d_pct": 3.0, "var_20d_pct": -28.0, "pct_float": 4.6, "dias_para_cobrir": 4.5, "h": [190000000, 200000000, 210000000, 200000000, 200000000]},
        "DIRR3": {"saldo_qtd": 28000000, "saldo_rs": 300000000, "taxa": 0.02, "contratos": 0, "pct_float": 8.8, "dias_para_cobrir": 2.1}}})
    _g(out / "multiplos.json", {"pregao": "2026-10-09", "a": {
        "PETR4": {"raiz": "PETR", "tipo": "geral", "classe": "PN", "preco": 56.0, "preco_de": "2026-10-09", "mcap": 774311188173, "liq_21d": 2340827433, "var_dia_b3": 0.93,
                  "periodo": "2026T2", "balanco_idade_dias": 103, "pl": 5.41, "pvp": 1.5, "ev_ebitda": 3.98, "dl_ebitda": 1.14, "dy_12m": 6.53, "roe": 30.31,
                  "mg_liq_12m": 24.32, "cresc_lucro_12m": 72.38, "avisos": []},
        "BBAS3": {"raiz": "BBAS", "tipo": "financeira", "classe": "ON", "preco": 24.64, "preco_de": "2026-10-09", "pl": 9.71, "pvp": 0.78, "ev_ebitda": None, "dl_ebitda": None},
        "DIRR3": {"raiz": "DIRR", "tipo": "geral", "classe": "ON", "preco": 12.3, "preco_de": "2026-10-09", "pl": 7.47, "ev_ebitda": 5.91, "dl_ebitda": 0.47}}})

    # ---- noticias e notas do agente
    _g(out / "noticias.json", {"gerado": "2026-10-12T08:00:00-03:00", "janela_horas": 72, "itens": [
        {"id": "aaaaaaaaaa", "ts": "2026-10-11T04:17:11-03:00", "fonte": "Estadao", "tipo": "midia", "peso": 40, "titulo": "Petrobras sobe", "tickers": ["PETR4"]},
        {"id": "bbbbbbbbbb", "ts": "2026-10-10T14:35:16-03:00", "fonte": "Valor", "tipo": "midia", "peso": 70, "titulo": "Petrobras e dividendos", "tickers": ["PETR4"]},
        {"id": "cccccccccc", "ts": "2026-10-10T10:00:00-03:00", "fonte": "Blog", "tipo": "midia", "peso": 5, "titulo": "Petrobras no ranking", "tickers": ["PETR4"]},
        {"id": "zzzzzzzzzz", "ts": "2026-09-20T10:00:00-03:00", "fonte": "Velho", "tipo": "midia", "peso": 90, "titulo": "velho demais", "tickers": ["PETR4"]}]})
    _g(out / "noticias_ativos.json", {"gerado": "2026-10-12T08:00:00-03:00", "ativos": {"PETR4": {"itens": [
        {"id": "eeeeeeeeee", "ts": "2026-10-08T10:00:00-03:00", "fonte": "Outro", "titulo": "sem nota"}]}}})
    _g(raiz / "cache" / "notas_agente.json", {"aaaaaaaaaa": {"n": 3, "t": 1}, "bbbbbbbbbb": {"n": 2, "t": 1}})

    # ---- calendario e agenda
    _g(out / "pagina" / "eventos.json", {"gerado": "2026-10-12T07:00:00-03:00", "itens": [
        {"data": "2026-11-10", "tipo": "resultado", "ticker": "PETR4", "empresa": "Petrobras", "periodo": "3T26", "confirmado": True, "pais": "BR", "raiz": "PETR",
         "fonte": "CVM", "indices": ["IBOV"], "momento_estimado": "ap\u00f3s o fechamento", "momento_confianca": 1.0, "momento_iguais": 8, "momento_entregas": 8,
         "momento_origem": "estimado pelo hist\u00f3rico de entregas"},
        {"data": "2026-10-29", "tipo": "resultado", "ticker": "PRIO3", "empresa": "Prio", "periodo": "3T26", "confirmado": True, "pais": "BR", "raiz": "PRIO",
         "momento_estimado": "antes da abertura", "momento_confianca": 0.75, "momento_iguais": 6, "momento_entregas": 8,
         "momento_origem": "estimado pelo hist\u00f3rico de entregas"},
        {"data": "2026-10-30", "tipo": "resultado", "ticker": "DIRR3", "empresa": "Direcional", "periodo": "3T26", "confirmado": False, "pais": "BR", "raiz": "DIRR",
         "momento_estimado": "antes da abertura", "momento_confianca": 0.5, "momento_iguais": 3, "momento_entregas": 6,
         "momento_origem": "estimado pelo hist\u00f3rico de entregas"},
        {"data": "2026-10-28", "tipo": "resultado", "ticker": "BBAS3", "empresa": "Banco do Brasil", "periodo": "3T26", "confirmado": True, "pais": "BR", "raiz": "BBAS",
         "momento_estimado": "durante o preg\u00e3o", "momento_confianca": 1.0, "momento_origem": "informado pela companhia"},
        {"data": "2026-10-14", "hora": "09:00", "tipo": "resultado", "ticker": "JPM", "empresa": "JPMorgan", "periodo": "3T26", "confirmado": True, "pais": "US"},
        {"data": "2026-10-16", "tipo": "vencimento_opcoes", "ticker": None, "empresa": "Opcoes sobre acoes (B3)", "periodo": "out/26", "confirmado": True, "pais": "BR"},
        {"data": "2026-10-13", "tipo": "provento_ex", "ticker": "PETR4", "tickers": ["PETR3", "PETR4"], "empresa": "Petrobras", "confirmado": True, "pais": "BR",
         "det": "JCP de R$ 0,47 por acao"},
        {"data": "2026-10-20", "tipo": "assembleia", "ticker": "BBAS3", "empresa": "Banco do Brasil", "pais": "BR"},
        {"data": "2026-10-05", "tipo": "resultado", "ticker": "VELHO3", "empresa": "Velho", "periodo": "2T26", "pais": "BR", "saiu": True},
        {"data": "2026-12-30", "tipo": "resultado", "ticker": "LONGE3", "empresa": "Longe", "periodo": "4T26", "pais": "BR"}],
        "reacoes": {"PETR": {"t": "PETR4", "n": 8, "m": -0.44, "ma": 3.14, "mr": -0.08,
                             "q": [["2T26", "2026-08-06", None, "2026-08-07", -2.99, -1.73, 1], ["1T26", "2026-05-11", None, "2026-05-12", -1.62, -0.86, 2]]}}})
    _g(out / "pagina" / "agenda.json", {"gerado": "2026-10-12T07:00:00-03:00", "eventos": [
        {"id": "BR-ipca-2026-10-14", "pais": "BR", "dia": "2026-10-14", "hora": "09:00", "evento": "IPCA (mes)", "indicador": "ipca", "relevancia": 3,
         "expectativa": 0.5, "efetivo": None, "anterior": 0.82, "unidade": "%", "saiu": False, "fonte": "IBGE"},
        {"id": "US-cpi-2026-10-14", "pais": "US", "dia": "2026-10-14", "hora": "09:30", "evento": "CPI (mes)", "indicador": "cpi", "relevancia": 3, "anterior": 0.3,
         "expectativa": 0.3, "efetivo": 0.4, "surpresa": 0.1, "exp_fonte": "manual: Bloomberg, copiado em 2026-10-13 (cache/manual/consenso_eua.csv)",
         "unidade": "%", "saiu": True, "fonte": "BLS"},
        {"id": "BR-focus-2026-10-26", "pais": "BR", "dia": "2026-10-26", "hora": "08:30", "evento": "Focus", "indicador": "focus", "relevancia": 2, "saiu": False}]})

    # ---- valuation, divida, opcoes, fundos, pares
    _g(out / "porativo" / "valuation" / "PETR4.json", {
        "s": "PETR4", "data": "2026-10-09", "hoje": {"pl": 5.41, "pvp": 1.5, "ev_ebitda": 3.98, "dy": 6.53},
        "est": {"pl": {"5": {"n": 60, "media": 4.57, "mediana": 4.35, "pct": 73.0, "z": 0.35}, "10": {"n": 94, "mediana": 5.35, "pct": 51.0, "z": -0.39}},
                "pvp": {"5": {"n": 60, "mediana": 1.13, "pct": 97.0, "z": 2.15}},
                "ev_ebitda": {"5": {"n": 60, "mediana": 3.06, "pct": 90.0, "z": 1.3}}},
        "setor": {"rot": "Exploracao, Refino e Distribuicao", "nivel": "subsetor", "n": 8, "premio": {"pl": {"hoje": -56.1}, "pvp": {"hoje": 14.0}}}})
    _g(out / "porativo" / "divida" / "PETR.json", {
        "ultimo": {"entrega": "2026-08-06"}, "base": "consolidado",
        "foto": {"periodo": "2026T2", "data": "2026-06-30", "fonte": "CVM, ITR 2T26", "bruta": 366533.0, "caixa": 53764.0, "liq": 312769.0, "cp": 60490.0,
                 "dl_ebitda": 1.14, "ebitda_12m": 273323.0, "cobertura": 17.02, "cobertura_de": "juros pagos", "custo": 7.95, "cp_pct": 16.5, "caixa_cp": 0.89,
                 "me_falta": "A companhia nao abre os emprestimos por moeda."},
        "pares": {"grupo": "Exploracao, Refino e Distribuicao", "n": 8, "dl_ebitda": 1.74, "custo": 10.08}})
    _g(out / "deriv" / "opcoes" / "PETR4.json", {
        "s": "PETR4", "data": "2026-10-08", "data_posicao": "2026-10-08", "spot": 56.0, "var_spot": 0.93,
        "resumo": {"oi_call": 369766200, "oi_put": 413901100, "pc_oi": 1.12, "doi_call": 425000, "doi_put": 10732800, "venc_ref": "2026-10-16", "vol_call": 0,
                   "ofertas": {"dois_lados": 323, "firmes": 113, "spread_max": 40.0}},
        "vencimentos": [{"venc": "2026-10-16", "du": 4, "dor_maxima": 47.61, "dor_maxima_dist_pct": -14.98, "parede_call": {"k": 59.86, "dist_pct": 6.89},
                         "parede_put": {"k": 49.61, "dist_pct": -11.41},
                         "strikes": [{"k": 50.4, "iv": 40.0}, {"k": 55.9, "iv": 31.0}, {"k": 58.8, "iv": 30.5}, {"k": 61.6, "iv": 30.0}, {"k": 70.0}]}],
        "hist": {"t": ["2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"], "iv_atm": [33.0, 34.0, 31.0, 32.0, None],
                 "venc_ref": ["2026-10-16"] * 4 + [None]}})
    _g(out / "deriv" / "opcoes_resumo.json", {
        "data": "2026-10-08", "incompleto": {"data": "2026-10-09", "motivo": "arquivo de negocios com 30.342 linhas de opcao, 41% da mediana", "tentativas": 3,
                                              "ultima_tentativa": "2026-10-11T12:00:00-03:00"}})
    _g(out / "porativo" / "quemtem" / "PETR4.json", {
        "s": "PETR4", "ref": "2026-06", "data": "2026-06-30", "tot": {"n": 978, "q": 382706152, "v": 18634708275},
        "pct": {"cl": 7.03, "ff": 11.0}, "mov": {"de": "2026-06", "au": [295, 26251857], "en": [181, 23209203], "re": [299, -44811553], "sa": [77, -5812008]}})
    _g(out / "pagina" / "proximos.json", {
        "gerado": "2026-10-12T07:00:00-03:00", "janela_pregoes": 126, "cal": {"acao_br": "br", "bdr": "br", "acao_us": "us"},
        "dias": {"br": ["2026-10-08", "2026-10-09"], "us": ["2026-10-08", "2026-10-09"]},
        "p": {"PETR4": [["PRIO3", 0.7, 1]]},
        "v": {"PETR4": [1.0, 1.0], "PRIO3": [-1.0, 0.0]}})
    return raiz
