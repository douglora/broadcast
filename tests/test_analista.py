"""Testes do analista (ferramentas/local/analista): a conta da TIR real, Damodaran, a ponte com o
Safra, a leitura da CVM, o momento economico, os graficos e a montagem do relatorio.

Tudo sem rede. Os numeros de conferencia sao formulas fechadas (perpetuidade, Gordon, anuidade,
Fisher): se a conta do motor nao bater com a formula do livro-texto, o teste cai.
Os dois testes do fim leem o cache do terminal e a coleta local e pulam sozinhos se nao houver.
"""
import datetime as dt
import importlib.util
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_DIR = os.path.join(RAIZ, "ferramentas", "local")
for p in (RAIZ, LOCAL_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from analista import base as B                      # noqa: E402
from analista import cvm_integral as C              # noqa: E402
from analista import damodaran as D                 # noqa: E402
from analista import graficos as G                  # noqa: E402
from analista import macro as MAC                   # noqa: E402
from analista import relatorio as R                 # noqa: E402
from analista import safra as SF                    # noqa: E402
from analista import setores as S                   # noqa: E402
from analista import tir_real as T                  # noqa: E402

ANO0 = dt.date.today().year
PERTO = lambda a, b, tol=1e-6: abs(a - b) <= tol * max(1.0, abs(b))


def _ins(**kw):
    """Empresa de brinquedo: EBITDA 1.000, 80% vira caixa, depreciacao 200, sem divida.
    Caixa do dono parado = 0,8 x 1.000 - 200 = 600 por ano, para sempre."""
    ins = {"mac": {"ntnb_2035": 0.07, "ipca_longo": 0.035,
                   "ipca_focus": {ANO0: 0.045, ANO0 + 1: 0.04, ANO0 + 2: 0.038}},
           "ebitda0": 1000.0, "conv": 0.8, "m_cap": 0.0, "custo_real": 0.07, "divida0": 0.0,
           "fracao_minoritarios": 0.0, "da0": 200.0}
    ins.update(kw)
    return ins


# ------------------------------------------------------------------ matematica de base
def test_fisher_ida_e_volta():
    assert PERTO(B.real(0.1540, 0.04), 1.1540 / 1.04 - 1.0)
    assert PERTO(B.nominal(B.real(0.1375, 0.049), 0.049), 0.1375)
    # juro real nao e a subtracao: 15,4% com 4% de inflacao e 10,96%, nao 11,4%
    assert abs(B.real(0.154, 0.04) - 0.1096) < 1e-4


def test_tir_de_um_fluxo_simples():
    assert PERTO(B.tir([(1, 110.0)], 100.0), 0.10, 1e-7)
    assert PERTO(B.tir([(1, 10.0), (2, 110.0)], 100.0), 0.10, 1e-7)       # titulo ao par
    assert PERTO(B.vpl(0.10, [(1, 10.0), (2, 110.0)]), 100.0)


def test_tir_sem_troca_de_sinal_nao_inventa():
    assert B.tir([(1, -10.0), (2, -5.0)], 100.0) is None


def test_mediana_e_formato_brasileiro():
    assert B.mediana([3, None, 1, 2]) == 2
    assert B.mediana([1, 2, 3, 4]) == 2.5
    assert B.mediana([]) is None
    assert B.br(1234567.891, 2) == "1.234.567,89"
    assert B.pct(0.0772, 2) == "7,72%"
    assert B.pp(-0.021) == "-2,1 pp"
    assert B.reais(17.7) == "R$ 17,70"
    assert B.mi(12900.0) == "R$ 12,9 bi" and B.mi(340.0) == "R$ 340 mi"
    assert B.data_br("2026-11-11") == "11/11/2026"
    assert B.pct(None) == "n/d"


# ------------------------------------------------------------------ TIR real: o caixa do dono
def test_lista_repete_o_ultimo():
    assert T._lista(5, 3) == [5, 5, 5]
    assert T._lista([1, 2], 4) == [1, 2, 2, 2]
    assert T._lista([1, 2], 4, depois=0) == [1, 2, 0, 0]


def test_caixa_parado_e_perpetuidade():
    """Caixa constante para sempre: TIR = caixa / preco. 600 / 6.000 = 10%."""
    fx = T.fluxo(_ins())
    assert all(PERTO(l["dono"], 600.0) for l in fx["linhas"]) and PERTO(fx["tipo"]["dono"], 600.0)
    assert len(fx["linhas"]) == T.HORIZONTE
    assert PERTO(T.valor_presente(fx, 0.10), 6000.0)
    assert PERTO(T.tir_do_fluxo(fx, 6000.0), 0.10, 1e-7)
    assert PERTO(T.tir_do_fluxo(fx, 12000.0), 0.05, 1e-7)                 # preco dobra, a TIR cai pela metade


def test_crescimento_perpetuo_bate_com_gordon():
    """Caixa crescendo 2% real para sempre, sem custo de crescer: valor = D1 / (r - g)."""
    fx = T.fluxo(_ins(), g=0.02, g_t=0.02)
    assert PERTO(fx["linhas"][0]["dono"], 612.0)
    assert PERTO(T.valor_presente(fx, 0.10), 612.0 / 0.08)
    assert PERTO(T.tir_do_fluxo(fx, 612.0 / 0.08), 0.10, 1e-7)


def test_crescer_custa_capital():
    """m_cap = 3: cada real de EBITDA novo pede R$ 3 de investimento a mais no ano."""
    fx = T.fluxo(_ins(m_cap=3.0), g=0.05)
    l1 = fx["linhas"][0]
    assert PERTO(l1["ebitda"], 1050.0)
    assert PERTO(l1["investimento"], 0.2 * 1050.0 + 50.0 * 3.0)
    assert PERTO(l1["dono"], 0.8 * 1050.0 - (210.0 + 150.0))
    assert fx["tipo"]["g"] == 0.0 and PERTO(fx["tipo"]["investimento"], 0.2 * fx["tipo"]["ebitda"])   # perpetuidade sem crescer


def test_concessao_com_data_de_fim():
    """Concessao que acaba: anuidade de n anos mais a indenizacao no fim, sem perpetuidade."""
    n, r = 5, 0.08
    fx = T.fluxo(_ins(), fim=ANO0 + n, residual=1000.0)
    assert fx["n"] == n and len(fx["linhas"]) == n
    anuidade = 600.0 * (1.0 - (1.0 + r) ** -n) / r
    assert PERTO(T.valor_presente(fx, r), anuidade + 1000.0 / (1.0 + r) ** n)
    v = anuidade + 1000.0 / (1.0 + r) ** n
    assert PERTO(T.tir_do_fluxo(fx, v), r, 1e-7)
    # sem valor residual e pagando mais que a soma dos caixas, o retorno e negativo (e a conta mostra)
    seco = T.fluxo(_ins(), fim=ANO0 + n)
    assert T.tir_do_fluxo(seco, 3500.0) < 0


def test_divida_rolada_paga_so_o_juro_real():
    """Divida de 2.000 a 7% real, rolada: custa 140 por ano; minoritario leva a parte dele."""
    fx = T.fluxo(_ins(divida0=2000.0))
    assert all(PERTO(l["custo_divida"], 140.0) and PERTO(l["divida_nova"], 0.0) for l in fx["linhas"])
    assert PERTO(fx["linhas"][0]["dono"], 460.0)
    fm = T.fluxo(_ins(divida0=2000.0, fracao_minoritarios=0.10))
    assert PERTO(fm["linhas"][0]["dono"], 414.0) and PERTO(fm["linhas"][0]["minoritarios"], 46.0)


def test_divida_acompanha_o_ebitda_quando_cresce():
    """Alavancagem constante: EBITDA +5% -> divida +5%, e a divida nova entra no caixa do dono."""
    fx = T.fluxo(_ins(divida0=2000.0), g=0.05)
    l1 = fx["linhas"][0]
    assert PERTO(l1["divida"], 2100.0) and PERTO(l1["divida_nova"], 100.0)
    assert PERTO(l1["dono"], 0.8 * 1050.0 - 0.2 * 1050.0 - 140.0 + 100.0)


def test_custo_da_divida_converge_para_a_ntnb():
    fx = T.fluxo(_ins(divida0=2000.0, custo_real=0.11))
    rds = [l["custo_real_divida"] for l in fx["linhas"]]
    assert PERTO(rds[0], 0.11) and PERTO(rds[2], 0.09) and PERTO(rds[4], 0.07) and PERTO(rds[9], 0.07)
    fixo = T.fluxo(_ins(divida0=2000.0, custo_real=0.11), custo_div=0.11)
    assert all(PERTO(l["custo_real_divida"], 0.11) for l in fixo["linhas"])


def test_sem_rolagem_a_divida_encolhe_em_termos_reais():
    fx = T.fluxo(_ins(divida0=2000.0), rolagem=False)
    pi = 0.04                                                             # Focus do ano seguinte
    l1 = fx["linhas"][0]
    assert PERTO(l1["ipca"], pi)
    assert PERTO(l1["divida"], 2000.0 / 1.04)
    assert PERTO(l1["custo_divida"], B.nominal(0.07, pi) * 2000.0 / 1.04)
    assert l1["dono"] < T.fluxo(_ins(divida0=2000.0))["linhas"][0]["dono"]    # paga a correcao em dinheiro


def test_inflacao_do_ano_usa_focus_e_depois_a_longa():
    mac = _ins()["mac"]
    assert MAC.inflacao_ano(mac, ANO0 + 1) == 0.04
    assert MAC.inflacao_ano(mac, ANO0 + 9) == 0.035
    assert MAC.inflacao_ano(mac, ANO0 - 3) == 0.045


def test_premissa_de_ebitda_e_de_investimento_ano_a_ano():
    fx = T.fluxo(_ins(), ebitda=[1100.0, 1200.0], capex=[500.0])
    assert PERTO(fx["linhas"][0]["ebitda"], 1100.0) and PERTO(fx["linhas"][1]["ebitda"], 1200.0)
    assert PERTO(fx["linhas"][2]["ebitda"], 1200.0)                       # depois do plano, parado
    assert all(PERTO(l["investimento"], 500.0) for l in fx["linhas"])
    assert PERTO(fx["tipo"]["investimento"], 0.2 * 1200.0)                # perpetuidade volta a reposicao


def test_tir_zera_o_valor_presente():
    """A definicao: descontado pela TIR, o caixa vale exatamente o preco pago."""
    for kw, valor in (({}, 5200.0), ({"g": 0.03}, 7400.0), ({"g": [0.06, 0.04, 0.02], "g_t": 0.01}, 9100.0)):
        fx = T.fluxo(_ins(divida0=1500.0, custo_real=0.09, m_cap=2.5), **kw)
        r = T.tir_do_fluxo(fx, valor)
        assert r is not None and PERTO(T.valor_presente(fx, r), valor, 1e-7)


def test_tir_nao_fecha_quando_nao_ha_caixa():
    fx = T.fluxo(_ins(conv=0.15))                                         # caixa do dono negativo
    assert fx["tipo"]["dono"] < 0 and T.tir_do_fluxo(fx, 5000.0) is None
    assert T.tir_do_fluxo(T.fluxo(_ins()), 0.0) is None
    assert T.crescimento_para(fx, 5000.0, 0.10) is None


def test_conta_reversa_devolve_o_que_entrou():
    fx = T.fluxo(_ins())
    v = T.valor_presente(fx, 0.10, 0.03)
    assert PERTO(T.crescimento_para(fx, v, 0.10), 0.03, 1e-6)
    assert PERTO(T.crescimento_para(fx, 6000.0, 0.10), 0.0, 1e-6)        # ja entrega 10%: nao precisa crescer
    assert T.crescimento_para(fx, 6000.0, 0.12) > 0                       # para render mais, tem de crescer
    assert T.valor_presente(fx, 0.02, 0.0) != float("inf")
    assert T.valor_presente(T.fluxo(_ins(), g_t=0.05), 0.05) == float("inf")


def test_preco_para_uma_taxa():
    fx = T.fluxo(_ins())
    assert PERTO(T.preco_para(fx, 6000.0, 20.0, 0.10), 20.0)
    assert PERTO(T.preco_para(fx, 6000.0, 20.0, 0.12), 20.0 * (600.0 / 0.12) / 6000.0)
    assert T.preco_para(T.fluxo(_ins(conv=0.15)), 6000.0, 20.0, 0.10) is None


def test_ebitda_que_o_preco_exige():
    """Sem divida, caixa = 0,6 x EBITDA para sempre: EBITDA exigido = valor x taxa / 0,6."""
    assert PERTO(T.ebitda_para(_ins(), 6000.0, 0.12), 1200.0, 1e-6)
    assert PERTO(T.ebitda_para(_ins(), 6000.0, 0.10), 1000.0, 1e-6)


def test_tendencia_ignora_um_ano_fora_da_curva():
    serie = [(t, 100.0 * 1.05 ** t) for t in range(8)]
    assert PERTO(T.tendencia(serie), 0.05, 1e-9)
    serie[3] = (3, 30.0)                                                  # um ano ruim nao muda a tendencia
    assert abs(T.tendencia(serie) - 0.05) < 0.01
    assert T.tendencia(serie[:3]) is None


def test_previsibilidade():
    hist = [{"ano": 2020 + i, "ebitda": 100.0 + 3 * i} for i in range(6)]
    ins = {"hist_real": hist, "convs": [(0.80, 2021), (0.84, 2022)]}
    ok = T.previsibilidade(ins, previsivel=True)
    assert ok["aviso"] is False and ok["veredito"].startswith("previs")
    assert T.previsibilidade(ins, previsivel=False)["aviso"] is True       # setor ciclico avisa sempre
    hist2 = [dict(h) for h in hist]
    hist2[3]["ebitda"] = 60.0
    q = T.previsibilidade({"hist_real": hist2, "convs": []}, previsivel=True)
    assert q["aviso"] is True and q["ano"] == 2023 and q["pior_queda_anual"] < -0.25
    assert "-" not in q["frase"].split("caiu")[1][:6]                      # "caiu 43%", nunca "caiu -43%"


def test_premissa_sem_fonte_nao_entra(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "PREMISSAS", tmp_path)
    assert T.ler_premissas("XXXX3") is None
    (tmp_path / "XXXX3.json").write_text(json.dumps({"itens": {"g": {"valor": 0.03, "fonte": ""}}}), encoding="utf-8")
    with pytest.raises(B.SemDado):
        T.ler_premissas("XXXX3")
    (tmp_path / "XXXX3.json").write_text(json.dumps({"itens": {"chute": {"valor": 1, "fonte": "release"}}}), encoding="utf-8")
    with pytest.raises(B.SemDado):
        T.ler_premissas("XXXX3")
    bom = {"itens": {"g": {"valor": 0.03, "fonte": "Release 3T26, p. 4", "data": "2026-11-05", "tipo": "GUIDANCE"}}}
    (tmp_path / "XXXX3.json").write_text(json.dumps(bom), encoding="utf-8")
    assert T.ler_premissas("xxxx3")["itens"]["g"]["valor"] == 0.03


def test_livro_de_premissas_guarda_tipo_e_separa_as_da_mesa():
    lv = B.Livro()
    lv.p("NTN-B 2035", 0.0772, "a.a. real", "ANBIMA", "2026-11-10", B.MERCADO)
    lv.p("Perpetuidade sem crescimento", 0.0, "a.a.", "premissa da mesa")
    lv.aviso("a"); lv.aviso("a")
    assert [i.nome for i in lv.da_mesa()] == ["Perpetuidade sem crescimento"]
    assert lv.avisos == ["a"] and lv.lista()[0]["tipo"] == "MERCADO"


# ------------------------------------------------------------------ Damodaran
PAR = {"brasil": {"spread_calote": 0.03, "premio_pais": 0.04, "rating": "Ba1"}, "premio_maduro": 0.045,
       "pais_data": "2026-07-01", "premio_maduro_data": "2026-11-01",
       "betas_emergentes": {"data": "2026-01-05", "setores": {
           "Power": {"sem_divida_sem_caixa": 0.50, "beta": 0.80, "n": 120},
           "Total Market (without financials)": {"sem_divida_sem_caixa": 0.70, "beta": 0.95, "n": 9000}}},
       "betas_globais": {"data": "2026-01-05", "setores": {"Utility (Water)": {"sem_divida_sem_caixa": 0.40, "beta": 0.60, "n": 30}}}}
MACD = {"ntnb_10a": 0.075, "ipca_longo": 0.035, "ntnb_data": "2026-11-10"}


def test_custo_do_capital_real():
    cc = D.custo_capital(PAR, MACD, "Power", 0.5)
    beta = 0.50 * (1.0 + (1.0 - 0.34) * 0.5)
    assert PERTO(cc["rf_real"], 0.045) and PERTO(cc["premio"], 0.085)
    assert PERTO(cc["beta"], beta) and PERTO(cc["ke_real"], 0.045 + beta * 0.085)
    assert PERTO(cc["ke_nominal"], B.nominal(cc["ke_real"], 0.035))
    sem = D.custo_capital(PAR, MACD, "Power", 0.0)
    assert PERTO(sem["beta"], 0.50) and sem["ke_real"] < cc["ke_real"]     # mais divida, mais risco para o dono


def test_banco_usa_o_beta_do_setor_sem_realavancar():
    assert PERTO(D.custo_capital(PAR, MACD, "Power", 3.0, financeira=True)["beta"], 0.80)


def test_beta_do_setor_cai_para_o_global_e_depois_para_o_mercado():
    assert D.beta_setor(PAR, "Power")["base"] == "mercados emergentes"
    assert D.beta_setor(PAR, "Utility (Water)")["base"] == "global"
    assert D.beta_setor(PAR, "Setor que nao existe")["industria"] == "Total Market (without financials)"
    vazio = dict(PAR, betas_emergentes={"data": "x", "setores": {}}, betas_globais={"data": "x", "setores": {}})
    with pytest.raises(B.SemDado):
        D.beta_setor(vazio, "Power")


def test_custo_do_capital_registra_as_premissas():
    lv = B.Livro()
    D.custo_capital(PAR, MACD, "Power", 0.5, lv)
    nomes = " | ".join(i.nome for i in lv.itens)
    assert "Juro sem risco real" in nomes and "Beta realavancado" in nomes and "Ke" in nomes
    assert all(i.fonte for i in lv.itens)


def test_valor_terminal_quando_o_retorno_iguala_o_custo():
    """ROIC = WACC na fase estavel: crescer nao cria valor, o terminal e NOPAT / WACC com qualquer g."""
    for g_est in (0.0, 0.01, 0.025):
        linhas, terminal = D._projetar(1000.0, 0.34, 0.03, 0.15, 0.09, g_est)
        nopat_11 = linhas[-1]["ebit"] * (1.0 + g_est) * (1.0 - D.IMPOSTO)
        assert PERTO(terminal, nopat_11 / 0.09)


def test_fcff_sem_crescimento_e_perpetuidade():
    linhas, terminal = D._projetar(1000.0, 0.34, 0.0, 0.09, 0.09, 0.0)
    assert all(PERTO(l["fcff"], 660.0) and l["reinvestimento"] == 0.0 for l in linhas)
    assert PERTO(D._valor_firma(linhas, terminal, 0.09), 660.0 / 0.09)


def test_reinvestimento_e_crescimento_sobre_retorno():
    linhas, _ = D._projetar(1000.0, 0.34, 0.04, 0.16, 0.09, 0.02)
    l1 = linhas[0]
    assert PERTO(l1["ebit"], 1040.0) and PERTO(l1["reinvestimento"], l1["nopat"] * 0.04 / 0.16)
    assert PERTO(linhas[4]["g"], 0.04) and PERTO(linhas[9]["g"], 0.02)     # 5 anos de g, 5 de convergencia
    assert PERTO(linhas[9]["roic"], 0.09)


def test_imposto_converge_para_a_aliquota_legal():
    linhas, _ = D._projetar(1000.0, 0.20, 0.0, 0.09, 0.09, 0.0)
    assert PERTO(linhas[0]["imposto"], 0.214) and PERTO(linhas[-1]["imposto"], 0.34)


def test_pib_longo_do_focus():
    mac = {"focus": {"PIB Total": {2026: {"mediana": 1.8}, 2029: {"mediana": 2.0}, 2030: {"mediana": None}}}}
    assert D._pib_longo(mac) == (0.02, 2029)
    assert D._pib_longo({}) == (None, None)


def test_patrimonio_de_instituicao_financeira():
    bpp = {"2": ("Passivo Total", 9000.0), "2.07": ("Patrimônio Líquido Consolidado", 1000.0),
           "2.07.01": ("Patrimônio Líquido Atribuído ao Controlador", 950.0),
           "2.07.02": ("Patrimônio Líquido Atribuído aos Não Controladores", 50.0)}
    assert D._pl_financeira(bpp) == (1000.0, 50.0)
    assert D._pl_financeira({"2": ("Passivo Total", 1.0)}) == (None, 0.0)


# ------------------------------------------------------------------ ponte com o Safra
def test_tir_do_safra_trazida_ao_preco_de_hoje():
    """Regra do terminal: o rendimento (TIR - g) encolhe na proporcao em que o preco sobe."""
    r = SF.trazer(0.127, 16.00, -0.011, 17.70)
    assert PERTO(r, -0.011 + 0.138 * 16.00 / 17.70) and 0.113 < r < 0.114
    assert PERTO(SF.trazer(0.127, 16.00, -0.011, 16.00), 0.127)           # mesmo preco, mesma TIR
    assert SF.trazer(0.127, 16.00, -0.011, 14.00) > 0.127                 # caiu, rende mais
    assert PERTO(SF.trazer(0.127, 16.00, -0.011, 17.00, 0.70), r)         # provento recebido conta como preco


def test_preco_em_que_a_tir_iguala_o_ke():
    p = SF.preco_no_ke(0.127, 16.00, -0.011, 0.11)
    assert PERTO(SF.trazer(0.127, 16.00, -0.011, p), 0.11)
    assert PERTO(SF.preco_no_ke(0.127, 16.00, -0.011, 0.11, 0.50), p - 0.50)
    assert SF.preco_no_ke(0.127, 16.00, 0.12, 0.11) is None


def test_alvo_publicado_antes_de_desdobramento():
    assert SF.base_de_hoje(100.0, 50.0, 25.0) == (50.0, 2.0)              # desdobrou 2 por 1 depois do relatorio
    assert SF.base_de_hoje(19.5, 16.0, 15.6) == (19.5, 1.0)               # diferenca de centavos nao e desdobramento
    assert SF.base_de_hoje(19.5, None, 15.6) == (19.5, 1.0)


def test_fechamento_e_proventos_do_historico():
    h = {"t": ["2026-01-02", "2026-01-05", "2026-01-06"], "c": [10.0, 11.0, 12.0],
         "div": [["2026-01-03", 0.5], ["2026-02-01", 0.3]]}
    assert SF.fechamento(h, "2026-01-04") == (10.0, "2026-01-02")         # fim de semana: pregao anterior
    assert SF.fechamento(h, "2026-01-06") == (12.0, "2026-01-06")
    assert SF.fechamento(h, "2025-12-30") == (None, None)
    assert PERTO(SF.proventos(h, "2026-01-03", "2026-02-01"), 0.3)        # depois da data, ate hoje
    assert PERTO(SF.proventos(h, "2026-01-01", "2026-12-31"), 0.8)
    assert SF._f("19,50") == 19.5 and SF._f(None) is None


# ------------------------------------------------------------------ leitura da CVM
def test_juros_pagos_nao_confunde_com_dividendo_nem_com_principal():
    dfc = {"6.03.01": ("Juros pagos de empréstimos e financiamentos", -100.0),
           "6.03.02": ("Dividendos e juros sobre o capital próprio pagos", -50.0),
           "6.03.03": ("Amortização de principal e juros de debêntures", -30.0),
           "6.03.04": ("Pagamento de encargos de dívidas", -20.0),
           "6.03.05": ("Juros pagos (estorno)", 5.0)}
    v, usados = C._soma(dfc, "6.03", C.RX["juros"], C.RX["juros_fora"], "-")
    assert v == -120.0 and len(usados) == 2
    v, _ = C._soma(dfc, "6.03", C.RX["div"], None, "-")
    assert v == -50.0


@pytest.mark.parametrize("linha,entra", [
    ("Juros e variações monetárias sobre empréstimos", True),
    ("Encargos de dívidas", True),
    ("Variação monetária e cambial de debêntures", True),
    ("Despesas com juros", True),
    ("Juros sobre aplicações financeiras", False),
    ("Juros e atualização de depósitos judiciais", False),
    ("Variação monetária de contingências", False),
    ("Juros pagos sobre empréstimos", False),
    ("Atualização monetária do ativo financeiro da concessão", False),
])
def test_encargos_da_divida_por_competencia(linha, entra):
    achou = bool(C.RX["encargos"].search(linha)) and not C.RX["encargos_fora"].search(linha)
    assert achou is entra


def test_capex_pega_ativo_de_contrato_e_ignora_venda():
    dfc = {"6.02.01": ("Aquisição de imobilizado e intangível", -300.0),
           "6.02.02": ("Adições ao ativo de contrato", -200.0),
           "6.02.03": ("Recebimento pela venda de imobilizado", 40.0),
           "6.02.04": ("Aplicações financeiras", -500.0)}
    v, _ = C._soma(dfc, "6.02", C.RX["capex"], C.RX["capex_fora"], "-")
    assert v == -500.0


def test_soma_so_as_folhas():
    bloco = {"6.01.01": ("Depreciação e amortização", 100.0), "6.01.01.01": ("Depreciação", 60.0),
             "6.01.01.02": ("Amortização", 40.0)}
    assert sorted(C._folhas(bloco, "6.01")) == ["6.01.01.01", "6.01.01.02"]
    v, _ = C._soma(bloco, "6.01", C.RX["da"])
    assert v == 100.0                                                     # nao soma pai e filha (seria 200)


def test_padronizar_demonstracoes():
    dem = {"DRE": {"3.01": ("Receita", 5000.0), "3.05": ("Resultado antes do financeiro", 1500.0),
                   "3.06": ("Resultado financeiro", -400.0), "3.11": ("Lucro consolidado", 800.0),
                   "3.11.01": ("Atribuído a controladores", 0.0), "3.11.02": ("Atribuído a não controladores", 0.0),
                   "3.99.01.01": ("ON", 0.80)},
           "DVA": {"7.04.01": ("Depreciação, amortização e exaustão", -300.0)},
           "DFC_MI": {"6.01": ("Caixa das operações", 1700.0), "6.02.01": ("Aquisição de imobilizado", -600.0),
                      "6.03.01": ("Dividendos pagos", -350.0), "6.03.02": ("Recompra de ações", -90.0)},
           "BPA": {"1": ("Ativo total", 20000.0), "1.01.01": ("Caixa", 700.0), "1.01.02": ("Aplicações", 300.0)},
           "BPP": {"2.01.04": ("Empréstimos CP", 1000.0), "2.02.01": ("Empréstimos LP", 5000.0),
                   "2.03": ("Patrimônio líquido", 8000.0), "2.03.09": ("Não controladores", 500.0)}}
    o = C.padronizar(dem)
    assert o["ebitda"] == 1800.0 and o["da"] == 300.0
    assert o["lucro_controladores"] == 800.0                              # abertura zerada nao e lucro zero
    assert o["receitas_financeiras"] is None and o["despesas_financeiras"] is None
    assert o["capex"] == 600.0 and o["dividendos_pagos"] == 350.0 and o["recompras"] == 90.0
    assert o["divida_liquida"] == 5000.0 and o["pl_controladores"] == 7500.0 and o["lpa"] == 0.80


def _integral(total):
    return {"acoes": {"total": total, "tesouraria": 0.0, "on": total, "pn": 0.0, "total_ex_tesouraria": total},
            "anual": {"2025-12-31": {"DRE": {"3.11": ("Lucro", 2000.0), "3.11.01": ("Controladores", 2000.0),
                                             "3.99.01.01": ("ON", 2.0)}}}, "itr": {}}


def test_numero_de_acoes_em_milhares_e_corrigido():
    """Lucro de R$ 2.000 mi e R$ 2,00 por acao = 1 bilhao de acoes. A CVM traz 1.000.000: esta em milhares."""
    a = C.escala_acoes(_integral(1_000_000.0))["acoes"]
    assert a["escala"] == 1000 and a["total"] == 1e9 and a["total_ex_tesouraria"] == 1e9
    b = C.escala_acoes(_integral(1e9))["acoes"]
    assert b["escala"] == 1 and b["total"] == 1e9
    assert C.escala_acoes(C.escala_acoes(_integral(1_000_000.0)))["acoes"]["total"] == 1e9   # nao corrige duas vezes


# ------------------------------------------------------------------ momento economico e setores
def _mac(ntnb, rev, juro=0.06):
    return {"ntnb_2035": ntnb, "revisao_4s": dict(rev, ano=ANO0 + 1), "juro_real_ex_ante": juro}


def test_regime_hostil_neutro_e_favoravel():
    h = MAC.regime(_mac(0.0772, {"IPCA": 0.60, "Selic": 0.50, "PIB": -0.25}, 0.09))
    assert h["nome"] == "hostil" and h["pontos"] == -6 and h["premio_exigido"] == 0.05 and len(h["motivos"]) == 5
    n = MAC.regime(_mac(0.055, {"IPCA": 0.05}))                           # revisao pequena nao conta
    assert n["nome"] == "neutro" and n["premio_exigido"] == 0.04
    f = MAC.regime(_mac(0.045, {"IPCA": -0.20, "PIB": 0.15}))
    assert f["nome"] == "favoravel" and f["premio_exigido"] == 0.035
    d = MAC.regime(_mac(0.065, {}))
    assert d["nome"] == "desfavoravel" and d["premio_exigido"] == 0.045


def test_interpolacao_da_curva():
    curva = [(2030, 7.5), (2035, 7.7), (2040, 7.9), (None, 1.0)]
    assert PERTO(MAC._interp(curva, 2032.5), 7.6)
    assert MAC._interp(curva, 2020) == 7.5 and MAC._interp(curva, 2050) == 7.9
    assert MAC._interp([], 2030) is None


def test_todo_setor_tem_roteiro_completo():
    for sid, s in S.SETORES.items():
        for campo in ("nome", "previsivel", "metodo", "indicadores", "armadilhas", "perguntas", "damodaran"):
            assert campo in s, f"setor {sid} sem '{campo}'"
        assert s["indicadores"] and s["armadilhas"] and s["perguntas"], sid
    for raiz, sid in S._POR_RAIZ.items():
        assert sid in S.SETORES, f"raiz {raiz} aponta para setor inexistente {sid}"
    for _, sid in S._B3:
        assert sid in S.SETORES


def test_setor_pelo_ticker_sem_rede():
    assert S.identificar("CPLE3")["previsivel"] is True
    assert S.identificar("TAEE11")["id"] == "eletrica_transmissao"
    assert S.identificar("SBSP3.SA")["id"] == "saneamento"
    assert S.identificar("ITUB4")["id"] == "bancos"


# ------------------------------------------------------------------ graficos e relatorio
def _xml(svg):
    assert svg.lstrip().startswith("<svg")
    ET.fromstring(svg)
    return svg


def test_graficos_geram_svg_valido():
    pc = lambda v: B.br(v, 1) + "%"
    _xml(G.barras_h([{"rotulo": "Caixa parado & <teste>", "valor": 5.6, "cor": "acc", "nota": "piso"},
                     {"rotulo": "Não fecha", "valor": None, "cor": "mut"}], pc, 7.7, "NTN-B 2035", "retornos"))
    _xml(G.cascata([{"rotulo": "EBITDA", "valor": 1000.0, "total": True}, {"rotulo": "Imposto", "valor": -200.0},
                    {"rotulo": "Caixa do dono", "valor": 800.0, "total": True}], lambda v: B.br(v, 0), "cascata"))
    _xml(G.colunas(["2027", "2028"], [{"nome": "Caixa", "valores": [1.0, None], "cor": "acc"},
                                      {"nome": "EBITDA", "valores": [-2.0, 3.0], "cor": "nav"}], lambda v: B.br(v, 0)))
    _xml(G.pontos([{"x": "16/10/26", "valor": 11.3, "nota": "R$ 16,00"}, {"x": "11/11/26", "valor": 13.3, "nota": "R$ 14,00"}],
                  pc, [(11.0, "Ke real do Safra", "nav")], "tir no tempo"))
    serie = [((dt.date(2021, 1, 4) + dt.timedelta(days=3 * i)).isoformat(), 4.0 + (i % 50) / 20.0) for i in range(600)]
    _xml(G.linha_tempo(serie, pc, [(5.0, "média", "mut")], "ntnb"))


def test_eixo_com_passo_redondo():
    lo, hi, passo = G.faixa(0.0, 13.3)
    assert lo <= 0.0 and hi >= 13.3 and passo in (1, 2, 2.5, 5, 10, 20, 25, 50)
    assert G.quebrar("uma frase longa que precisa quebrar em duas linhas", 20)[0] != ""


def test_texto_do_analista_sem_fonte_derruba_a_montagem(tmp_path):
    arq = tmp_path / "texto.json"
    arq.write_text(json.dumps({"tese": ["a", ""], "gestao": [{"tema": "margem", "disse": "x", "entregou": "y", "fonte": ""}]}), encoding="utf-8")
    with pytest.raises(B.SemDado):
        R.ler_texto("XXXX3", arq)
    arq.write_text(json.dumps({"tese": ["a", ""], "gestao": [{"tema": "", "disse": "", "entregou": "", "fonte": ""}],
                               "noticias": [{"data": "2026-11-05", "titulo": "t", "leitura": "l", "fonte": "Release 3T26, p. 2"}]}), encoding="utf-8")
    t = R.ler_texto("XXXX3", arq)
    assert t["tese"] == ["a"] and "gestao" not in t and len(t["noticias"]) == 1
    assert R.ler_texto("XXXX3", tmp_path / "nao_existe.json") == {}


def test_numero_da_barra_fica_por_cima_da_linha_de_referencia():
    # 6,6% termina colado na linha da NTN-B (7,7%): o numero ganha fundo branco e e desenhado depois da linha
    pc = lambda v: B.br(v, 1) + "%"
    svg = _xml(G.barras_h([{"rotulo": "Caixa parado", "valor": 5.6, "cor": "acc"}, {"rotulo": "Ritmo atual", "valor": 6.6, "cor": "acc"},
                           {"rotulo": "Safra", "valor": 13.3, "cor": "nav"}], pc, 7.7, "NTN-B 2035", "retornos"))
    assert svg.index("stroke-dasharray") < svg.index(">6,6%<") and svg.index("stroke-dasharray") < svg.index(">13,3%<")
    assert svg.count(f'height="20" fill="{G.COR["fundo"]}"') >= 1


def test_linha_do_tempo_escreve_o_ultimo_valor_com_as_casas_pedidas():
    serie = [((dt.date(2025, 1, 2) + dt.timedelta(days=i)).isoformat(), 7.0 + i / 100.0) for i in range(79)]
    svg = _xml(G.linha_tempo(serie, lambda v: B.br(v, 2) + "%", descricao="ntnb", fmt_eixo=lambda v: B.br(v, 1) + "%"))
    assert ">7,78%<" in svg and ">7,0%<" in svg and ">7,00%<" not in svg


def test_historia_da_ntnb_2035_prefere_o_titulo_com_juros_semestrais(tmp_path):
    # a regua e a NTN-B 2035 com cupom; o Tesouro IPCA+ 2035 sem cupom rende alguns centesimos a mais e so entra se o outro faltar
    (tmp_path / "TD-IPCA-2035.json").write_text(json.dumps({"t": ["2026-11-11"], "tx": [7.82]}), encoding="utf-8")
    h, nome = MAC.serie_td(tmp_path)
    assert h["tx"] == [7.82] and "sem cupom" in nome
    (tmp_path / "TD-IPCA-JS-2035.json").write_text(json.dumps({"t": ["2026-11-11"], "tx": [7.78]}), encoding="utf-8")
    h, nome = MAC.serie_td(tmp_path)
    assert h["tx"] == [7.78] and "Juros Semestrais" in nome
    assert MAC.serie_td(tmp_path / "vazio") == ({}, "")


def test_resumido_corta_o_texto_do_analista_e_avisa():
    gestao = [{"tema": f"t{i}", "disse": "d", "entregou": "e", "fonte": "Release 2T26, p. 2"} for i in range(6)]
    itens, nota = R._corte(gestao, "gestao", profundo=False)
    assert [x["tema"] for x in itens] == ["t0", "t1", "t2"] and "Mais 3 linhas" in nota
    itens, nota = R._corte(gestao, "gestao", profundo=True)
    assert len(itens) == 6 and nota == ""
    assert R._corte(gestao[:3], "gestao", profundo=False) == (gestao[:3], "")
    assert "Mais 1 linha " in R._corte(gestao[:4], "noticias", profundo=False)[1]
    html_res = R._sec_texto({"gestao": gestao}, False)
    assert "t2" in html_res and "t3" not in html_res and "relatório profundo" in html_res
    assert "t5" in R._sec_texto({"gestao": gestao}, True)


def test_fonte_do_texto_do_analista_vai_dentro_da_ultima_coluna():
    # tabela de 3 colunas (cabe no celular): a fonte sai em letra pequena embaixo da leitura
    h = R._sec_texto({"gestao": [{"tema": "Divida", "disse": "2,8x", "entregou": "2,9x", "fonte": "Release 2T26, p. 12"}]}, True)
    assert h.count("<th>") == 3 and "<small>Fonte: Release 2T26, p. 12</small>" in h


def test_resumido_corta_a_ponte_e_os_limites_da_conta():
    assert R.CORTE_RESUMIDO == {"gestao": 3, "setor": 4, "noticias": 3, "ponte": 4, "avisos": 2}
    itens, nota = R._corte(list("abcdef"), "ponte", profundo=False)
    assert itens == list("abcd") and nota == "Mais 2 pontos no relatório profundo."
    itens, nota = R._corte(list("abc"), "avisos", profundo=False)
    assert itens == list("ab") and nota == "Mais 1 limite desta conta no relatório profundo."


def test_glossario_so_traz_o_termo_que_aparece_no_relatorio():
    corpo = "<p>A TIR real ficou 2,1 pp abaixo da NTN-B 2035; o EBITDA cresceu e a receita anual permitida (RAP) subiu.</p>"
    usa = R.termos_usados(corpo)
    assert usa == ["TIR real", "NTN-B 2035", "EBITDA", "pp", "RAP"]
    assert "WACC" not in usa and "Ke" not in usa                       # nao aparecem: nao entram
    assert "Ke" not in R.termos_usados("<p>O parque eolico gerou menos.</p>")   # sigla nao casa dentro de palavra
    assert R.termos_usados("<p>o caixa do dono e o prêmio</p>") == ["Prêmio", "Caixa do dono"]
    assert R._termos("<p>sem termo nenhum</p>") == ""
    for k, v in R.TERMOS.items():
        assert v.endswith(".") and len(v) < 140, k


def test_tabela_pequena_nao_se_divide_entre_paginas():
    assert 'class="tab curta"' in R._tab(["Ano", "Caixa"], [[str(2027 + i), "2.608"] for i in range(10)])
    assert 'class="tab curta"' not in R._tab(["Ano", "Caixa"], [[str(2027 + i), "2.608"] for i in range(13)])
    assert 'class="tab curta"' not in R._tab(["Tema", "Leitura"], [["Divida", "x" * 300], ["Caixa", "y" * 300]])
    assert 'class="tab curta"' in R._tab(["O que acompanha", "Por que"], [["Base de remuneracao e data da revisao", "degrau de receita contratado"]] * 7)
    assert 'class="tab curta"' not in R._tab(["Ano"], [])


def test_grafico_de_pontos_nao_escreve_o_numero_em_cima_da_linha():
    itens = [{"x": f"d{k}", "valor": v} for k, v in enumerate([0.127, 0.117, 0.102, 0.105, 0.100, 0.135, 0.137, 0.127, 0.113])]
    svg = G.pontos(itens, lambda v: f"{v * 100:.1f}%", refs=[(0.11, "Ke", "neg")])
    _xml(svg)
    pos = {m.group(3): (float(m.group(1)), float(m.group(2)), m.group(0))
           for m in re.finditer(r'<text x="([\d.]+)" y="([\d.]+)"[^>]*>([\d.]+%)</text>', svg) if "paint-order" in m.group(0)}
    cy = {round(float(x), 1): float(y) for x, y in re.findall(r'<circle cx="([\d.]+)" cy="([\d.]+)"', svg)}
    y_de = lambda rot: cy[min(cy, key=lambda x: abs(x - pos[rot][0]))]
    assert pos["10.2%"][1] > y_de("10.2%") and pos["10.0%"][1] > y_de("10.0%")      # fundo de vale: numero embaixo
    assert pos["13.7%"][1] < y_de("13.7%") and pos["12.7%"][1] < y_de("12.7%")      # topo: numero em cima
    assert 'text-anchor="start"' in pos["11.3%"][2]                                # ultimo ponto: numero a direita
    assert max(float(x) for x in cy) < pos["11.3%"][0] < G.W


def test_resumido_que_passa_da_meta_sai_no_modo_compacto(tmp_path, monkeypatch):
    chamadas, contagem = [], iter([8, 6])
    monkeypatch.setattr(R, "pasta", lambda tk: tmp_path)
    monkeypatch.setattr(R, "montar", lambda tk, modo, texto=None, contexto=None, preco=None, compacta=False:
                        (chamadas.append(compacta) or f"<figure></figure>{compacta}", {"ticker": "XXXX3"}))
    monkeypatch.setattr(R, "para_pdf", lambda arq: tmp_path / "x.pdf")
    monkeypatch.setattr(R, "conta_paginas", lambda pdf: next(contagem))
    o = R.gravar("XXXX3", "resumido", pdf=True)
    assert chamadas == [False, True] and o["compacta"] is True
    assert (tmp_path / "XXXX3_resumido.html").read_text(encoding="utf-8").endswith("True")
    chamadas.clear()
    monkeypatch.setattr(R, "conta_paginas", lambda pdf: 14)
    assert R.gravar("XXXX3", "profundo", pdf=True)["compacta"] is False and chamadas == [False]   # o profundo nao encolhe
    css = (R.ESTILO / "estilo.css").read_text(encoding="utf-8")
    assert ".compacta" in css and ".curta" in css and ".junto" in css


def test_roteiro_do_setor_nao_usa_sigla_sem_explicar():
    for chave, s in S.SETORES.items():
        visivel = " ".join([s["metodo"]] + [a + " " + b for a, b in s["indicadores"]] + s["armadilhas"] + s["perguntas"])
        assert "BRL" not in visivel, chave


def test_frases_do_relatorio():
    assert "2,1 pp abaixo" in R._contra(-0.021) and "neg" in R._contra(-0.021)
    assert "1,3 pp acima" in R._contra(0.013) and "pos" in R._contra(0.013)
    P = B.Premissa
    assert R._valor_livro(P("NTN-B", 0.0772, "a.a. real")) == "7,72% a.a. real"
    assert R._valor_livro(P("Payout", 0.46, "do lucro")) == "46,0% do lucro"
    assert R._valor_livro(P("Beta", 0.665, "x")) == "0,67x"
    assert R._valor_livro(P("EBITDA", 5566.0, "R$ mi")).startswith("R$ 5.566")
    assert R._valor_livro(P("Rating", "Ba1", "")) == "Ba1"


def test_numero_em_formato_brasileiro_na_linha_de_comando():
    spec = importlib.util.spec_from_file_location("analista_cli", os.path.join(LOCAL_DIR, "analista.py"))
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    assert cli._num("19,50") == 19.5 and cli._num("1.234,5") == 1234.5 and cli._num("19.50") == 19.5
    assert cli._num("11,3%") == 11.3 and cli._num("R$ 15,80") == 15.8 and cli._num(None) is None
    assert cli._ipca(0.056) == "IPCA + 5,6%" and cli._ipca(None) == "não fecha"


# ------------------------------------------------------------------ com o dado de verdade (pula sem cache)
TEM_TERMINAL = B.TERMINAL.exists()
TEM_COPEL = (B.LOCAL / "ativos" / "CPLE3.json").exists() and (B.CACHE / "integral").exists()


@pytest.mark.skipif(not TEM_TERMINAL, reason="sem o cache do terminal neste computador")
def test_momento_economico_real_e_plausivel():
    try:
        m = MAC.carregar()
    except B.SemDado as e:
        pytest.skip(f"cache do terminal incompleto: {e}")
    assert 0.02 < m["ntnb_2035"] < 0.15 and 0.01 < m["ipca_longo"] < 0.12
    assert m["regime"]["nome"] in ("hostil", "desfavoravel", "neutro", "favoravel")
    assert 0.03 <= m["regime"]["premio_exigido"] <= 0.05


@pytest.mark.skipif(not (TEM_TERMINAL and TEM_COPEL), reason="sem a coleta local da Copel")
def test_copel_de_ponta_a_ponta_fecha_a_conta():
    """Com o dado de verdade: a TIR de cada cenario zera o valor presente contra o valor de mercado,
    todo numero do livro tem fonte e a conta reversa devolve o preco de tela na propria TIR."""
    try:
        o = T.calcular("CPLE3", previsivel=True)
    except B.SemDado as e:
        pytest.skip(f"dado local incompleto: {e}")
    vm = o["valor_mercado"]
    for c in o["cenarios"]:
        assert c["tir"] is not None and -0.05 < c["tir"] < 0.40
        assert PERTO(T.valor_presente(c["fluxo"], c["tir"]), vm, 1e-6)
        assert PERTO(c["premio"], c["tir"] - o["ntnb_2035"])
    assert all(i.fonte for i in o["livro"].itens), [i.nome for i in o["livro"].itens if not i.fonte]
    ref = o["central"]["fluxo"]
    assert PERTO(T.preco_para(ref, vm, o["preco"], o["central"]["tir"]), o["preco"], 1e-5)
    assert o["preco_teto"] < o["preco_sem_premio"]                        # exigir premio baixa o preco que se aceita pagar
