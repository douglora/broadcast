"""Insights do relatorio (pedido de 23/09): setores do dia, por que mexeu, Brent em
reais, aviso de participacao relevante, volume e extremos de 52 semanas, agenda."""

from __future__ import annotations

import json
import os
from datetime import date

import pandas as pd

from livro import atribuicao as at
from livro import cards, render

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "qualidade")


def _j(dia, conf=True, **kw):
    return {"dia": dia, "dia_confirmado": conf, **kw}


JANELAS_23_09 = {"CURY3": _j(-0.0381), "DIRR3": _j(-0.0342), "MRVE3": _j(-0.0132), "TEND3": _j(-0.060),
                 "PLPL3": _j(-0.020), "ITUB4": _j(-0.019), "BBDC4": _j(-0.022), "BBAS3": _j(-0.022),
                 "ITSA4": _j(-0.019), "PETR4": _j(0.0259), "BRENT": _j(0.0386, data="2026-09-23", ultimo=103.08),
                 "USDBRL": _j(-0.0021, conf=False, data="2026-09-23", ultimo=5.0999), "KLBN4": _j(-0.032),
                 "MMM": _j(0.0323, conf=False), "GFS": _j(-0.0443, conf=False)}
INS = {"di": {"deltas": {"DI1F28": 8.8, "DI1F30": 11.6, "DI1F35": 7.7}}}


def test_cesta_de_construtoras_23_09(universo):
    s = {c["id"]: c for c in at.cestas(universo, JANELAS_23_09, INS)}
    c = s["construtoras_mcmv"]
    assert round(c["mediana"] * 100, 2) == -3.42 and (c["subiram"], c["cairam"]) == (0, 5)
    assert c["destoou"]["id"] == "TEND3" and c["fator"] == "DI F30 +12 bps"
    b = s["bancos"]
    assert b["destoou"] == {}                    # todos a menos de 1 p.p. da mediana


def test_cesta_ignora_membro_sem_dia_confirmado(universo):
    j = dict(JANELAS_23_09)
    j["CURY3"] = _j(-0.0381, conf=False)
    c = {x["id"]: x for x in at.cestas(universo, j, INS)}["construtoras_mcmv"]
    assert "CURY3" in c["fora"] and c["n"] == 4


def test_por_que_mexeu_cury3_setorial_e_petr4_com_o_brent(universo):
    setores = at.cestas(universo, JANELAS_23_09, INS)
    itens = {x["id"]: x for x in at.por_que_mexeu(universo, JANELAS_23_09, setores, {}, [], "2026-09-23")}
    assert itens["CURY3"]["grau"] == "setorial" and "construtoras de baixa renda" in itens["CURY3"]["explicacao"]
    assert itens["PETR4"]["grau"] == "driver" and "acompanhou o Brent (+3,9%)" in itens["PETR4"]["explicacao"]
    assert itens["KLBN4"]["grau"] == "sem causa no dado"
    # dia de dois pregoes, commodity e cambio nao entram
    assert "MMM" not in itens and "GFS" not in itens and "BRENT" not in itens and "USDBRL" not in itens


def test_por_que_mexeu_le_o_aviso_de_participacao_do_dia(universo):
    setores = at.cestas(universo, JANELAS_23_09, INS)
    do_dia = [{"regra": "E03", "ativo": "DIRR3", "data": "2026-09-23", "id": "E03-DIRR3-1570676-2026-09-23",
               "dados": {"id_item": "CVM-DIRR3-1570676", "categoria": "Comunicado ao Mercado",
                         "participacao": {"detentor": "BlackRock", "percentual": 5.082, "data_cruzamento": "2026-09-18",
                                          "direcao": "aumentou", "objetivo_investimento": True}}}]
    itens = {x["id"]: x for x in at.por_que_mexeu(universo, JANELAS_23_09, setores, {}, do_dia, "2026-09-23")}
    d = itens["DIRR3"]
    assert d["grau"] == "setorial"                       # o aviso nao vira causa
    assert "BlackRock passou a ter 5,08% em 18/09" in d["explicacao"] and "não costuma explicar" in d["explicacao"]


def test_participacao_relevante_do_documento_real():
    c = json.load(open(os.path.join(FIX, "CVM-DIRR3-1570676.json"), encoding="utf-8"))
    doc = {"categoria": "Comunicado ao Mercado", "tipo": "Aquisição/Alienação de Participação Acionária Relevante",
           "assunto": c["titulo"], "texto": c["texto"]}
    p = at.participacao(doc)
    assert p["detentor"] == "BlackRock" and p["quantidade"] == 26453054 and p["percentual"] == 5.082
    assert p["data_cruzamento"] == "2026-09-18" and p["direcao"] == "aumentou" and p["objetivo_investimento"]
    assert at.participacao({"assunto": "Outros Comunicados Não Considerados Fatos Relevantes", "texto": "x"}) is None


def test_brent_em_reais_so_com_as_duas_pontas_confirmadas():
    assert at.brent_reais(JANELAS_23_09) == {"a_confirmar": "dólar"}
    ok = dict(JANELAS_23_09)
    ok["USDBRL"] = _j(0.0127, data="2026-09-23", ultimo=5.1689)
    b = at.brent_reais(ok)
    assert round(b["valor"], 2) == 532.81 and round(b["dia"] * 100, 2) == 5.18


def test_qualidade_do_dia_e_extremo_de_52_semanas():
    idx = pd.bdate_range("2025-09-01", periods=260)
    close = [30.0 + (i % 7) * 0.1 for i in range(259)] + [27.3]
    df = pd.DataFrame({"open": close, "high": [c + 0.5 for c in close], "low": [c - 0.5 for c in close],
                       "close": close, "adj": close, "volume": [1_000_000] * 259 + [1_500_000]}, index=idx)
    df.iloc[-1, df.columns.get_loc("low")] = 27.25
    q = at.qualidade_dia(df)
    assert round(q["vol_rel20"], 1) == 1.5 and q["pos_fech"] < 0.1
    assert at.extremo_52s(df) == "mínima de 52 semanas"
    assert at.contexto_curto({**q, "extremo_52s": "mínima de 52 semanas"}) == "vol 1,5x · fechou na mínima · mínima de 52 semanas"
    # barra provisoria (so fechamento, volume 0): sem contexto de volume
    df.iloc[-1, df.columns.get_loc("volume")] = 0
    assert at.qualidade_dia(df) == {}


def test_cards_levam_setores_e_por_que_mexeu(universo):
    setores = at.cestas(universo, JANELAS_23_09, INS)
    ins = {**INS, "setores": setores,
           "por_que_mexeu": at.por_que_mexeu(universo, JANELAS_23_09, setores, {}, [], "2026-09-23"),
           "brent_reais": {"a_confirmar": "dólar"}}
    assert "| Construtoras de baixa renda · DI F30 +12 bps | -3,4% | 0/5 | TEND3 -6,0% |" in cards._card_setores(ins)
    assert "ninguém (todos a menos de 1 p.p.)" in cards._card_setores(ins)
    pq = cards._card_por_que(ins)
    assert "### Por que mexeu" in pq and "| **CURY3** | -3,8% |" in pq
    assert cards._linha_brent_reais(ins) == "**Brent em reais:** a confirmar (dólar sem fechamento confirmado)."


def test_tesouro_mostra_o_delta_entre_datas_base_e_nao_dia():
    ins = {"tesouro": {"PRE2029": {"taxa": 13.85, "delta": 4.0, "apelido": "Pre 2029", "tipo": "Tesouro Prefixado"}},
           "tesouro_base": "2026-09-18", "tesouro_base_anterior": "2026-09-17"}
    txt = cards._card_curvas(ins)
    assert "| Tesouro Direto · base 18/09 | taxa | Δ 17/09→18/09 |" in txt and "Δ dia" not in txt.split("Tesouro")[1]


def test_agenda_de_empresas_enxerga_dez_pregoes():
    cal = {"eventos_macro": [], "recorrentes": [],
           "resultados": [{"ticker": "MU", "data": date(2026, 9, 30), "quando": "apos_ny", "confirmado": True}]}
    linhas = " ".join(render.agenda(cal, date(2026, 9, 18)))
    assert "resultado MU" in linhas                       # 12 dias a frente
    assert "resultado MU" not in " ".join(render.agenda(cal, date(2026, 9, 14)))    # 16 dias: fora


def test_participacao_de_venda_e_de_total_com_derivativos():
    venda = {"texto": "recebeu correspondência da Gestora X, comunicando que alienou ações e suas participações "
                      "passaram a ser inferiores a 5%, representando 4,95% do capital, configurando alienação de participação"}
    p = at.participacao({**venda, "tipo": "Aquisição/Alienação de Participação Acionária Relevante"})
    assert p["direcao"] == "reduziu" and p["percentual"] == 4.95 and p["detentor"] == "Gestora X"
    assert at.texto_participacao(p).startswith("Gestora X reduziu para 4,95%")
    deriv = {"texto": "recebeu correspondência do Fundo Y, informando participação acionária relevante: 0,90% em ações "
                      "e 5,15% em derivativos, totalizando 6,05% do capital"}
    assert at.participacao(deriv)["percentual"] == 6.05


def test_companhia_comprando_fatia_de_outra_empresa_nao_e_aviso_de_participacao():
    doc = {"categoria": "Comunicado ao Mercado", "assunto": "Aquisição de participação na Alfa Energia",
           "texto": "A Itaúsa S.A. comunica que a Companhia, em 22 de setembro de 2026, concluiu a aquisição de ações "
                    "ordinárias de emissão da Alfa Energia S.A., passando a deter 12,500% do capital, configurando "
                    "aquisição de participação acionária relevante, nos termos do artigo 12 da Resolução CVM nº 44/21."}
    assert at.participacao(doc) is None


def test_fato_relevante_nao_vira_aviso_de_participacao(universo, limiares):
    from datetime import date as _d
    from livro.sinais import eventos
    from livro.sinais.base import Contexto, Estado
    doc = {"ativo": "DIRR3", "categoria": "Fato Relevante", "assunto": "Venda de participação acionária relevante do controlador",
           "data": "2026-09-23", "protocolo": "1", "severidade": "atencao",
           "texto": "O controlador comunicou a alienação de participação acionária relevante de 10%."}
    ctx = Contexto(universo=universo, limiares=limiares, hoje=_d(2026, 9, 23), slot="fechamento", series={},
                   series_info={}, curvas={}, macro={}, falhas={}, eventos={"cvm": [doc]})
    a = eventos.E03CVM().avaliar(ctx, Estado())[0]
    assert "Fato Relevante" in a.titulo and a.severidade == "atencao" and "participacao" not in a.dados
