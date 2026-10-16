"""Swing: M1 e M2, a camada de julgamento da mesa medida em prova viva (convicao +1/+2 e veto -2). Sem teste historico; nunca capital pela regra de evidencia."""
import json
from datetime import date, datetime

import pytest

from quant.comum import FUSO_BRT
from quant.swing import boleta as bol
from quant.swing import estado as est, evidencia, mesa_setups, painel, setups
from quant.testes.swing_fixture import painel_sintetico

GERADO = "2026-10-11T11:12:04-03:00"                        # domingo: o primeiro pregao depois e terca 13/10 (segunda 12/10 e feriado)


def _visao(gerado=GERADO, acoes=None):
    acoes = acoes if acoes is not None else [
        {"ticker": "AAAA3", "conviccao": 1, "tese": "Empresa A ganha escala e a margem sobe. Segunda frase que passa de duzentos caracteres " + "x" * 200},
        {"ticker": "BBBB3", "conviccao": -2, "risco": "alavancagem alta e rolagem de divida cara", "tese": "tese B"},
        {"ticker": "CCCC3", "conviccao": 0},
        {"ticker": "ZZZZ3", "conviccao": 2, "tese": "sem barras no painel"},
        {"ticker": "DDDD3", "conviccao": -1}]
    return {"gerado": gerado, "validade_dias": 7, "macro": {}, "setores": [], "acoes": acoes, "sem_analise": [], "avisos": []}


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANT_SWING_DIR", str(tmp_path / "swing"))
    monkeypatch.setenv("QUANT_SAIDA_SWING", str(tmp_path / "tela" / "quant_fatores.json"))
    monkeypatch.setattr(evidencia, "ARQ_CONFIG", str(tmp_path / "swing_config.json"))
    monkeypatch.setattr(bol, "exposicao_do_dia", lambda e: {"fracao": 0.6, "texto": "60% (teste)", "teto_rs": 60_000.0})
    visoes = {"v": _visao()}
    monkeypatch.setattr(bol.mesa_mod, "ler", lambda arq=None, hoje=None: (visoes["v"], "visão de teste") if visoes["v"] else (None, "sem visão"))
    return visoes


def _p():
    return painel_sintetico(n=330, seed=2, vol=0.01, tickers=("AAAA3", "BBBB3", "CCCC3", "DDDD3"))


AGORA = datetime(2026, 10, 11, 12, 0, tzinfo=FUSO_BRT)


# ── a entrada ─────────────────────────────────────────────────
def test_entrada_e_a_abertura_do_primeiro_pregao_depois_da_visao():
    assert mesa_setups.entrada_da_visao("2026-10-11T11:12:04-03:00") == date(2026, 10, 13)       # domingo + feriado de segunda
    assert mesa_setups.entrada_da_visao("2026-10-13T08:30:00-03:00") == date(2026, 10, 13)       # pregao, antes das 10h: a abertura desse mesmo dia
    assert mesa_setups.entrada_da_visao("2026-10-13T10:00:00-03:00") == date(2026, 10, 14)
    assert mesa_setups.entrada_da_visao("2026-10-16T18:00:00-03:00") == date(2026, 10, 19)


def test_stop_alvo_e_prazo_sao_os_do_setup_pai_lidos_dele():
    stop, alvo, prazo = mesa_setups.parametros()
    pai = setups.NUCLEOS[mesa_setups.PAI[0]][mesa_setups.PAI[1]]
    assert (stop, alvo, prazo) == (pai["stop_atr"], pai["alvo_atr"], pai["prazo"]) == (2.0, 3.0, 10)
    assert mesa_setups.PAI[1] == "E1" and "E1" in mesa_setups.regra_texto("M1")


# ── as candidatas ─────────────────────────────────────────────
def test_m1_e_m2_pegam_os_papeis_certos_e_dizem_o_que_mede(ambiente):
    p = _p()
    ind = setups.indicadores(p)
    linhas, sem_dado, repetidas = mesa_setups.gerar(p, ind, _visao(), est.vazio())
    por = {(c["setup"], c["ticker"]): c for c in linhas}
    assert set(por) == {("M1", "AAAA3"), ("M2", "BBBB3")}                              # +1/+2 em M1, -2 em M2; 0 e -1 ficam de fora
    assert sem_dado == [("ZZZZ3", "M1", "sem barras no painel (fora do universo de giro mínimo ou ticker novo)")] and repetidas == []
    m1, m2 = por[("M1", "AAAA3")], por[("M2", "BBBB3")]
    assert m1["stop_dist"] == pytest.approx(2.0 * m1["atr_real"]) and m1["alvo_dist"] == pytest.approx(3.0 * m1["atr_real"]) and m1["prazo"] == 10
    assert m2["stop_dist"] == pytest.approx(2.0 * m2["atr_real"])                      # as mesmas regras nos dois
    assert "convicção +1" in m1["porque"] and "11/10/2026 às 11h12" in m1["porque"] and len(m1["porque"]) < 420           # tese resumida, nao colada inteira
    assert m2["porque"].startswith("Mede o que teria acontecido com os papéis vetados") and "não é operação vendida" in m2["porque"] and "alavancagem" in m2["porque"]
    assert m1["etiqueta"] == mesa_setups.ETIQUETA == "camada de julgamento: sem teste histórico; só prova viva"
    assert m1["sinal_em"] == "2026-10-09"                                              # o ultimo fechamento antes da entrada


def test_nao_repete_o_papel_enquanto_a_medida_anterior_do_mesmo_setup_esta_aberta(ambiente):
    p = _p()
    ind = setups.indicadores(p)
    e = est.vazio()
    e["posicoes"].append(est.nova_pendente("M1", "AAAA3", "2026-10-02", "2026-10-05", 1.0, 2.0, 10, 2e7, porque="visao anterior"))
    e["posicoes"].append(est.nova_pendente("M1", "BBBB3", "2026-10-02", "2026-10-05", 1.0, 2.0, 10, 2e7, porque="outro setup nao conta para M2"))
    linhas, _, repetidas = mesa_setups.gerar(p, ind, _visao(), e)
    assert repetidas == [("AAAA3", "M1")] and {(c["setup"], c["ticker"]) for c in linhas} == {("M2", "BBBB3")}


# ── na boleta: uma vez por visao ──────────────────────────────
def test_boleta_nova_mede_m1_e_m2_uma_vez_e_o_estado_lembra_a_visao(ambiente):
    p = _p()
    b = bol.gerar(entrada_em="2026-10-13", p=p, agora=AGORA, usar_terminal=False)
    mesa = [c for c in b["candidatas"] if c.get("camada_de_julgamento")]
    assert {(c["setup"], c["ticker"], c["destino"]) for c in mesa} == {("M1", "AAAA3", "medida"), ("M2", "BBBB3", "medida")}
    assert b["medidas_mesa"]["m1"] == 1 and b["medidas_mesa"]["m2"] == 1 and b["medidas_mesa"]["entrada_em"] == "2026-10-13"
    assert b["medidas_mesa"]["sem_dado"][0]["ticker"] == "ZZZZ3" and any("ZZZZ3" in a for a in b["avisos"])
    e = est.carregar()
    pend = {x["id"]: x for x in e["posicoes"] if x.get("camada_de_julgamento")}
    assert set(pend) == {"2026-10-13|M1|AAAA3|medida", "2026-10-13|M2|BBBB3|medida"}
    assert pend["2026-10-13|M1|AAAA3|medida"]["status"] == "pendente" and pend["2026-10-13|M1|AAAA3|medida"]["valor_alvo"] == 6000.0
    assert e["visoes_medidas"][0]["gerado"] == GERADO
    # refazer a boleta com a mesma visao: nada repete, e as linhas da mesa continuam na boleta
    n = len(e["posicoes"])
    b2 = bol.gerar(entrada_em="2026-10-13", p=p, agora=AGORA, usar_terminal=False, refazer=True)
    assert len(est.carregar()["posicoes"]) == n and len(est.carregar()["visoes_medidas"]) == 1
    assert {(c["setup"], c["ticker"]) for c in b2["candidatas"] if c.get("camada_de_julgamento")} == {("M1", "AAAA3"), ("M2", "BBBB3")}


def test_acrescentar_a_boleta_ja_emitida_nao_refaz_as_que_estavam_la_e_e_idempotente(ambiente):
    ambiente["v"] = None                                                                    # a boleta sai ANTES de a mesa ter visao
    p = _p()
    b0 = bol.gerar(entrada_em="2026-10-13", p=p, agora=AGORA, usar_terminal=False)
    antes = json.dumps(b0["candidatas"], sort_keys=True)
    n0 = len(est.carregar()["posicoes"])
    assert b0["medidas_mesa"] is None and not [c for c in b0["candidatas"] if c.get("camada_de_julgamento")]
    r0 = bol.acrescentar_mesa(p=p, agora=AGORA, usar_terminal=False)
    assert r0["ok"] and r0["m1"] == 0 and "sem visão válida" in r0["motivo"]               # sem visao, nada a medir (e nao e erro)
    ambiente["v"] = _visao()                                                                 # a mesa grava a visao depois
    r = bol.acrescentar_mesa(p=p, agora=AGORA, usar_terminal=False)
    assert r["ok"] and not r["ja_medida"] and (r["m1"], r["m2"]) == (1, 1) and r["novas_medidas"] == 2 and r["boleta"] == "2026-10-13"
    b1 = bol.ler_boleta(date(2026, 10, 13))
    assert json.dumps(b1["candidatas"][:len(b0["candidatas"])], sort_keys=True) == antes                  # as que ja estavam: intactas, na mesma ordem
    assert len(b1["candidatas"]) == len(b0["candidatas"]) + 2 and b1["gerado"] == b0["gerado"] and b1["acrescimos"][0]["m1"] == 1
    assert len(est.carregar()["posicoes"]) == n0 + 2
    r2 = bol.acrescentar_mesa(p=p, agora=AGORA, usar_terminal=False)                       # de novo: nada
    assert r2["ok"] and r2["ja_medida"] and len(est.carregar()["posicoes"]) == n0 + 2 and len(bol.ler_boleta(date(2026, 10, 13))["candidatas"]) == len(b1["candidatas"])


def test_visao_nova_e_medida_de_novo_mas_papel_aberto_nao_repete(ambiente):
    p = _p()
    bol.gerar(entrada_em="2026-10-13", p=p, agora=AGORA, usar_terminal=False)
    ambiente["v"] = _visao(gerado="2026-10-12T09:00:00-03:00")                              # segunda e feriado: a abertura e a de terca 13/10 de novo
    r = bol.acrescentar_mesa(p=p, agora=AGORA, usar_terminal=False)
    assert r["ok"] and not r["ja_medida"] and (r["m1"], r["m2"]) == (0, 0)                  # AAAA3 em M1 e BBBB3 em M2 ainda estao pendentes: nao repete
    assert [x["gerado"] for x in est.carregar()["visoes_medidas"]] == [GERADO, "2026-10-12T09:00:00-03:00"]
    assert len(r["resumo"]["repetidas"]) == 2


def test_sem_boleta_emitida_nao_acrescenta(ambiente):
    r = bol.acrescentar_mesa(p=_p(), agora=AGORA, usar_terminal=False)
    assert not r["ok"] and "gere a boleta primeiro" in r["motivo"]


def test_painel_velho_nao_mede(ambiente):
    p = _p()
    bol.gerar(entrada_em="2026-10-13", p=p, agora=AGORA, usar_terminal=False, refazer=True)
    ambiente["v"] = _visao(gerado="2026-10-16T18:00:00-03:00")                              # entrada em 19/10: pede o fechamento de 16/10, o painel para em 09/10
    r = bol.acrescentar_mesa(p=p, agora=AGORA, usar_terminal=False)
    assert not r["ok"] or r["ja_medida"] is False
    assert "2026-10-16T18:00:00-03:00" not in [x["gerado"] for x in est.carregar()["visoes_medidas"]]


# ── capital e placar ──────────────────────────────────────────
def test_m1_m2_so_ganham_capital_por_liberacao_escrita(ambiente, tmp_path):
    b = bol.gerar(entrada_em="2026-10-13", p=_p(), agora=AGORA, usar_terminal=False)
    assert not [c for c in b["candidatas"] if c["destino"] == "capital"]
    (tmp_path / "swing_config.json").write_text(json.dumps({"liberar": ["M1.S0", "M2.S0"], "decidido_em": "2026-10-13", "motivo": "teste"}))
    ambiente["v"] = _visao(gerado="2026-10-13T08:00:00-03:00")
    b2 = bol.gerar(entrada_em="2026-10-14", p=_p(), agora=AGORA, usar_terminal=False)           # painel termina em 09/10: dado velho para 14/10 -> nao mede
    assert not b2["emitida"]
    b3 = bol.gerar(entrada_em="2026-10-13", p=_p(), agora=AGORA, usar_terminal=False, refazer=True)
    assert b3["emitida"]
    est_ = est.carregar()
    est_["visoes_medidas"] = []                                                             # forca nova medicao da mesma boleta para olhar a decisao do gestor
    est_["posicoes"] = [x for x in est_["posicoes"] if not x.get("camada_de_julgamento")]
    est.salvar(est_)
    ambiente["v"] = _visao(gerado="2026-10-11T11:12:04-03:00")
    b4 = bol.gerar(entrada_em="2026-10-13", p=_p(), agora=AGORA, usar_terminal=False, refazer=True)
    por = {c["setup"]: c for c in b4["candidatas"] if c.get("camada_de_julgamento")}
    assert por["M1"]["destino"] == "capital" and por["M1"]["qtd"] > 0                         # liberado por escrito
    assert por["M2"]["destino"] == "recusada" and "vetada pela mesa" in por["M2"]["motivo"]   # o veto da propria mesa barra a compra do vetado


def test_ordem_com_capital_que_o_so_mesa_acrescenta_leva_a_hora_do_acrescimo(ambiente, tmp_path):
    """Revisao de 15/10/2026: a hora da ordem com capital fica gravada na candidata (o robo decide abertura ou ultimo preco por ela, nao pela
    hora do arquivo). A M1 liberada que o --so-mesa acrescenta as 11h00 passou a existir as 11h00; as candidatas de antes nao mudam."""
    (tmp_path / "swing_config.json").write_text(json.dumps({"liberar": ["M1.S0"], "decidido_em": "2026-10-13", "motivo": "teste"}))
    ambiente["v"] = None
    p = _p()
    manha = datetime(2026, 10, 13, 8, 35, tzinfo=FUSO_BRT)
    b0 = bol.gerar(entrada_em="2026-10-13", p=p, agora=manha, usar_terminal=False)
    ambiente["v"] = _visao(gerado="2026-10-11T11:12:04-03:00")
    r = bol.acrescentar_mesa(p=p, agora=datetime(2026, 10, 13, 11, 0, tzinfo=FUSO_BRT), usar_terminal=False)
    assert r["ok"] and r["m1"] == 1
    b1 = bol.ler_boleta(date(2026, 10, 13))
    m1 = [c for c in b1["candidatas"] if c["setup"] == "M1"]
    assert m1 and m1[0]["destino"] == "capital" and m1[0]["capital_desde"] == "2026-10-13T11:00:00-03:00"
    assert b1["candidatas"][:len(b0["candidatas"])] == b0["candidatas"]


def test_placar_e_evidencia_trazem_m1_m2_com_a_etiqueta(ambiente):
    v = evidencia.por_variante()
    fech = [{"id": "a", "setup": "M2", "modo": "medida", "status": "fechada", "resultado_pct": -0.02, "resultado_rs": -120.0, "overlays": {"top": False, "ibov_ok": True}},
            {"id": "b", "setup": "M2", "modo": "medida", "status": "fechada", "resultado_pct": 0.01, "resultado_rs": 60.0, "overlays": {"top": False, "ibov_ok": True}}]
    linhas = {x["variante"]: x for x in painel.placar(fech, v)}
    assert len(linhas) == 41 and linhas["M2.S0"]["operacoes"] == 2 and linhas["M1.S0"]["operacoes"] == 0
    assert linhas["M2.S0"]["etiqueta"] == mesa_setups.ETIQUETA and linhas["M2.S0"]["camada_de_julgamento"] is True and linhas["A1.S0"]["camada_de_julgamento"] is False
    assert linhas["M2.S0"]["expectativa_pct"] == pytest.approx(-0.005) and linhas["M2.S0"]["pesquisa_descoberta"] is None
    regras = {r["setup"]: r for r in painel.regras_dos_setups(v)}
    assert len(regras) == 15 and "Mede o que teria acontecido com os papéis vetados" not in regras["M1"]["regra"] and "vetado" in regras["M2"]["regra"]
    assert regras["M2"]["etiqueta"] == mesa_setups.ETIQUETA and regras["A1"]["etiqueta"] is None
    ev = {x["variante"]: x for x in painel.evidencia_por_setup(v)}
    assert len(ev) == 41 and ev["M1.S0"]["etiqueta"] == mesa_setups.ETIQUETA and ev["M1.S0"]["status"] == "so_medido"


def test_m1_m2_resolvidos_pelas_barras_oficiais_como_os_outros(ambiente):
    """Uma medida da mesa e uma operacao medida comum: entra na abertura oficial e sai por stop, alvo ou tempo."""
    from quant.testes.swing_fixture import barra, painel_plano
    from quant.dados import calendario
    datas = [d for d in calendario.pregoes("2026-10-01", "2026-10-30")][:14]
    p = painel_plano(datas, tickers=("AAAA3",))
    barra(p, "AAAA3", "2026-10-14", o=20.0, h=24.0, l=19.9, c=23.5)                         # a entrada (13/10) a R$ 20; alvo 3 ATR
    e = est.vazio()
    e["posicoes"].append(est.nova_pendente("M1", "AAAA3", "2026-10-09", "2026-10-13", 2.0, 3.0, 10, 2e7, porque="t", extras={"camada_de_julgamento": True}))
    novas = est.conciliar(e, p, hoje="2026-10-20")
    assert novas[0]["setup"] == "M1" and novas[0]["motivo_saida"] == "alvo" and novas[0]["camada_de_julgamento"] is True
