"""Swing: a boleta da manha (dado velho nao sai, medidas viram pendentes, boleta emitida nao muda) e o robo ao vivo (entrada na abertura, stop, alvo, prazo, tela)."""
import json
from datetime import datetime

import numpy as np
import pytest

from quant.comum import FUSO_BRT
from quant.swing import boleta as bol, candidatas, estado as est, evidencia, painel, setups, vivo
from quant.testes.swing_fixture import painel_sintetico


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    sw = tmp_path / "swing"
    monkeypatch.setenv("QUANT_SWING_DIR", str(sw))
    monkeypatch.setenv("QUANT_SAIDA_SWING", str(tmp_path / "tela" / "quant_fatores.json"))
    monkeypatch.setattr(evidencia, "ARQ_CONFIG", str(tmp_path / "swing_config.json"))
    monkeypatch.setattr(bol, "exposicao_do_dia", lambda e: {"fracao": 0.6, "texto": "60% (teste)", "teto_rs": 60_000.0})
    from quant import mesa
    monkeypatch.setattr(mesa, "ARQ_VISAO", str(tmp_path / "sem_mesa.json"))
    return tmp_path


def _liberar(ambiente, ids):
    (ambiente / "swing_config.json").write_text(json.dumps({"liberar": ids, "motivo": "teste", "decidido_em": "hoje"}))


def _painel_com_rompimento(n=330):
    p = painel_sintetico(n=n, seed=2, vol=0.004, tickers=("AAAA3", "BBBB3"))
    alta = p.C[:-1, 0].max()
    p.C[-1, 0] = alta * 1.05
    p.H[-1, 0] = p.C[-1, 0] * 1.001
    p.O[-1, 0] = p.C[-2, 0]
    p.V[-1, 0] = 5 * p.V[-2, 0]
    p.preco_cru[:, 0] = p.C[:, 0]
    return p


def test_rompimento_vira_candidata_com_stop_alvo_e_frase():
    p = _painel_com_rompimento()
    c = candidatas.gerar(p, setups.indicadores(p))
    c1 = [x for x in c if x["setup"] == "C1" and x["ticker"] == "AAAA3"]
    assert c1 and c1[0]["stop_dist"] > 0 and c1[0]["alvo_dist"] > c1[0]["stop_dist"] and c1[0]["prazo"] == 10
    assert "rompimento" in c1[0]["porque"] and "volume" in c1[0]["porque"] and c1[0]["top"] and c1[0]["ibov_ok"]
    assert abs(c1[0]["stop_ref"] - (c1[0]["preco_ref"] - c1[0]["stop_dist"])) < 1e-9


def test_boleta_so_medida_quando_nada_passou(ambiente):
    p = _painel_com_rompimento()
    b = bol.gerar(entrada_em="2026-10-13", p=p, agora=datetime(2026, 10, 11, 12, 0, tzinfo=FUSO_BRT), usar_terminal=False)
    assert b["emitida"] and b["bloqueios"] == [] and b["sinal_em"] == "2026-10-09" and b["estado_da_evidencia"] == "so_medido"
    assert all(c["destino"] == "medida" for c in b["candidatas"]) and b["entradas"] == []
    e = est.carregar()
    pend = [x for x in e["posicoes"] if x["status"] == "pendente"]
    assert len(pend) == len(b["candidatas"]) > 0 and all(x["modo"] == "medida" and x["valor_alvo"] == 6000.0 for x in pend)
    assert "Nenhum dos 39 setups" in b["evidencia"]
    tela = json.load(open(ambiente / "tela" / "quant_fatores.json", encoding="utf-8"))
    assert tela["modulo"] == "swing" and tela["swing"]["estado"] == "so_medido" and tela["avisos"][0].startswith("Nenhum dos 39 setups")


def test_boleta_com_dado_velho_nao_gera_sinal_e_diz_a_causa(ambiente):
    p = _painel_com_rompimento()
    b = bol.gerar(entrada_em="2026-10-20", p=p, agora=datetime(2026, 10, 18, 12, 0, tzinfo=FUSO_BRT), usar_terminal=False)    # o banco para em 09/10; o sinal pede 19/10
    assert not b["emitida"] and b["candidatas"] == [] and b["frescor"]["atual"] is False
    assert b["bloqueios"][0]["chave"] == "dado_velho" and "09/10/2026" in b["bloqueios"][0]["detalhe"] and "19/10/2026" in b["bloqueios"][0]["detalhe"]
    assert "BLOQUEADA" in bol.linha_final(b)
    assert est.carregar()["posicoes"] == []


def test_boleta_emitida_nao_muda_no_meio_do_dia_e_nao_duplica_medidas(ambiente):
    p = _painel_com_rompimento()
    agora = datetime(2026, 10, 11, 12, 0, tzinfo=FUSO_BRT)
    b1 = bol.gerar(entrada_em="2026-10-13", p=p, agora=agora, usar_terminal=False)
    n1 = len(est.carregar()["posicoes"])
    b2 = bol.gerar(entrada_em="2026-10-13", p=p, agora=agora, usar_terminal=False)
    assert b2["gerado"] == b1["gerado"] and len(est.carregar()["posicoes"]) == n1
    bol.gerar(entrada_em="2026-10-13", p=p, agora=agora, usar_terminal=False, refazer=True)
    assert len(est.carregar()["posicoes"]) == n1                                       # refazer nao duplica as medidas (mesmo id)


def test_boleta_com_setup_liberado_gera_ordem_com_capital(ambiente):
    _liberar(ambiente, ["C1.S0"])
    b = bol.gerar(entrada_em="2026-10-13", p=_painel_com_rompimento(), agora=datetime(2026, 10, 11, 12, 0, tzinfo=FUSO_BRT), usar_terminal=False)
    cap = [c for c in b["candidatas"] if c["destino"] == "capital"]
    assert len(cap) == 1 and cap[0]["setup"] == "C1" and cap[0]["qtd"] > 0 and b["estado_da_evidencia"] == "com_capital"
    assert cap[0]["risco_rs"] <= 0.005 * 60_000 + 1e-6


# ── o robo ao vivo ────────────────────────────────────────────
def _agora(hhmm, dia="2026-10-13"):
    h, m = (int(x) for x in hhmm.split(":"))
    a, me, d = (int(x) for x in dia.split("-"))
    return datetime(a, me, d, h, m, tzinfo=FUSO_BRT)


def _retrato(agora, cot):
    """cot: ticker -> (ultimo, abertura). Vetor do motor: [ultimo, var, abertura, max, min, volume, fech.anterior, hora, ...]."""
    return {"q": {t: [u, 0.0, ab, u, u, 1000.0, ab, agora.timestamp(), 0, 0, 0, 0, 0, 0, 0, 0, 0] for t, (u, ab) in cot.items()}, "mt5_idade_s": 0.2}


def _boleta_com_ordem(ambiente, ticker="AAAA3", preco=20.0, stop=2.0, alvo=4.0, prazo=10, emitida=True):
    c = {"setup": "C1", "ticker": ticker, "sinal_em": "2026-10-09", "preco_ref": preco, "stop_dist": stop, "alvo_dist": alvo, "stop_ref": preco - stop, "alvo_ref": preco + alvo,
         "prazo": prazo, "adtv": 2e7, "top": True, "ibov_ok": True, "porque": "teste", "destino": "capital", "variante": "C1.S0", "qtd": 100, "valor": 2000.0,
         "mesa": {"conviccao": 0}, "ficha": {}}
    b = {"v": 1, "data": "2026-10-13", "id": "swing-2026-10-13", "emitida": emitida, "sinal_em": "2026-10-09", "bloqueios": [] if emitida else [{"titulo": "x", "detalhe": "y"}],
         "candidatas": [c], "avisos": []}
    caminho = bol.arq_boleta("2026-10-13")
    import os
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    open(caminho, "w", encoding="utf-8").write(json.dumps(b))
    return b


def _robo(ambiente, monkeypatch, quotes, hoje="2026-10-13"):
    """RoboSwing com o motor trocado por `quotes[0]` (dict ticker -> (ultimo, abertura), mutavel entre ciclos)."""
    r = vivo.RoboSwing(hoje, saidas=[str(ambiente / "tela" / "quant_fatores.json")])
    r.exposicao = {"fracao": 0.6, "texto": "60% (teste)", "teto_rs": 60_000.0}
    r.relogio_agora = None
    monkeypatch.setattr(vivo, "ler_motor", lambda caminho, motor=None, timeout=4.0: _retrato(r.relogio_agora, quotes[0]) if quotes[0] is not None else None)
    return r


def _passo(r, hhmm, quotes, valores=None, dia="2026-10-13"):
    if valores is not None:
        quotes[0] = valores
    r.relogio_agora = _agora(hhmm, dia)
    r.ciclo(r.relogio_agora, forcar_tela=True)


def test_robo_entra_na_abertura_e_sai_no_alvo(ambiente, monkeypatch):
    _liberar(ambiente, ["C1.S0"])
    _boleta_com_ordem(ambiente)
    q = [{"AAAA3": (20.0, 20.0)}]
    r = _robo(ambiente, monkeypatch, q)
    _passo(r, "09:59", q)
    assert est.carregar()["posicoes"] == []                                            # antes das 10h nao entra
    _passo(r, "10:00", q)
    pos = [p for p in r.estado["posicoes"] if p["modo"] == "capital"][0]
    # risco de R$ 300 / stop de R$ 2 = 150 acoes, arredondado para baixo em lote de 100
    assert pos["preco_entrada"] == 20.0 and pos["qtd"] == 100 and pos["stop"] == 18.0 and pos["alvo"] == 24.0 and pos["prazo_ate"] == "2026-10-26"
    _passo(r, "12:00", q, {"AAAA3": (24.2, 20.0)})
    assert [p for p in r.estado["posicoes"] if p["modo"] == "capital"] == []
    f = est.fechadas()[0]
    assert f["motivo_saida"] == "alvo" and f["preco_saida"] == 24.0 and f["resultado_rs"] > 0
    tela = json.load(open(ambiente / "tela" / "quant_fatores.json", encoding="utf-8"))
    assert tela["swing"]["fechadas_recentes"][0]["motivo_saida"] == "alvo" and tela["swing"]["livro"]["operacoes_fechadas"] == 1


def test_robo_sai_no_stop_a_mercado_mesmo_abaixo_do_stop(ambiente, monkeypatch):
    _liberar(ambiente, ["C1.S0"])
    _boleta_com_ordem(ambiente)
    q = [{"AAAA3": (20.0, 20.0)}]
    r = _robo(ambiente, monkeypatch, q)
    _passo(r, "10:00", q)
    _passo(r, "10:40", q, {"AAAA3": (17.4, 20.0)})                                     # furou o stop (18): sai no ultimo preco visto
    f = est.fechadas()[0]
    assert f["motivo_saida"] == "stop" and f["preco_saida"] == 17.4 and f["r_multiplo"] < -1.0


def test_robo_sai_no_prazo_no_leilao_do_decimo_pregao(ambiente, monkeypatch):
    _liberar(ambiente, ["C1.S0"])
    p = est.nova_posicao("C1", "AAAA3", "2026-10-09", 20.0, 2.0, 4.0, 10, 100, "2026-10-13", 2e7, modo="capital", porque="teste")
    e = est.vazio()
    e["posicoes"].append(p)
    est.salvar(e)
    q = [{"AAAA3": (21.0, 20.8)}]
    r = _robo(ambiente, monkeypatch, q, hoje="2026-10-26")
    _passo(r, "10:30", q, dia="2026-10-26")
    assert len(r.estado["posicoes"]) == 1                                             # no ultimo dia, mas ainda antes do leilao
    _passo(r, "16:50", q, dia="2026-10-26")
    f = est.fechadas()[0]
    assert f["motivo_saida"] == "tempo" and f["pregoes"] == 10 and f["saida_em"] == "2026-10-26"


def test_robo_vigia_o_stop_mesmo_sem_boleta_e_avisa(ambiente, monkeypatch):
    p = est.nova_posicao("C1", "AAAA3", "2026-10-09", 20.0, 2.0, 4.0, 10, 100, "2026-10-13", 2e7, modo="capital", porque="teste")
    e = est.vazio()
    e["posicoes"].append(p)
    est.salvar(e)
    q = [{"AAAA3": (17.0, 17.5)}]
    r = _robo(ambiente, monkeypatch, q, hoje="2026-10-14")
    _passo(r, "10:05", q, dia="2026-10-14")
    assert est.fechadas()[0]["motivo_saida"] == "gap_stop"                               # abriu abaixo do stop no dia seguinte
    tela = json.load(open(ambiente / "tela" / "quant_fatores.json", encoding="utf-8"))
    assert tela["pronto"] is False and tela["bloqueios"][0]["chave"] == "boleta"


def test_robo_cancela_entrada_sem_cotacao_ate_as_11h(ambiente, monkeypatch):
    _liberar(ambiente, ["C1.S0"])
    _boleta_com_ordem(ambiente)
    q = [{}]
    r = _robo(ambiente, monkeypatch, q)
    _passo(r, "10:30", q)
    assert r.estado["posicoes"] == []
    _passo(r, "11:00", q)
    assert any("cancelada" in d["tipo"] for d in r.estado["diario"]) and r.estado["posicoes"] == []


def test_robo_sem_motor_nao_cai_e_diz_que_o_stop_nao_esta_vigiado(ambiente, monkeypatch):
    _boleta_com_ordem(ambiente)
    q = [None]
    r = _robo(ambiente, monkeypatch, q)
    _passo(r, "10:30", q)
    tela = json.load(open(ambiente / "tela" / "quant_fatores.json", encoding="utf-8"))
    assert any("motor de cotações" in a for a in tela["avisos"]) and tela["vivo"]["motor"]["ok"] is False


def test_robo_nao_entra_se_a_boleta_esta_bloqueada(ambiente, monkeypatch):
    _liberar(ambiente, ["C1.S0"])
    _boleta_com_ordem(ambiente, emitida=False)
    q = [{"AAAA3": (20.0, 20.0)}]
    r = _robo(ambiente, monkeypatch, q)
    _passo(r, "10:30", q)
    assert r.estado["posicoes"] == []


def test_entrada_respeita_a_exposicao_do_dia(ambiente, monkeypatch):
    _liberar(ambiente, ["C1.S0"])
    _boleta_com_ordem(ambiente)
    q = [{"AAAA3": (20.0, 20.0)}]
    r = _robo(ambiente, monkeypatch, q)
    r.exposicao = {"fracao": 0.01, "texto": "1%", "teto_rs": 600.0}                  # a regra do livro so deixa R$ 600 em acoes
    _passo(r, "10:00", q)
    assert r.estado["posicoes"] == [] and any("sem espaço" in d["texto"] for d in r.estado["diario"])


def test_contrato_da_tela_tem_todos_os_campos_das_posicoes(ambiente, monkeypatch):
    _liberar(ambiente, ["C1.S0"])
    _boleta_com_ordem(ambiente)
    q = [{"AAAA3": (20.0, 20.0)}]
    r = _robo(ambiente, monkeypatch, q)
    _passo(r, "10:00", q)
    _passo(r, "10:30", q, {"AAAA3": (20.5, 20.0)})
    tela = json.load(open(ambiente / "tela" / "quant_fatores.json", encoding="utf-8"))
    pos = tela["swing"]["posicoes"][0]
    for k in ("setup", "entrada_em", "preco_entrada", "stop", "alvo", "prazo_ate", "pregoes_na_posicao", "pregoes_restantes", "resultado_rs", "porque"):
        assert k in pos
    assert pos["pregoes_na_posicao"] == 1 and pos["pregoes_restantes"] == 9 and pos["resultado_rs"] > 0 and pos["prazo_ate"] == "2026-10-26"
    for k in ("v", "modulo", "gerado", "vivo", "pronto", "bloqueios", "avisos", "boleta", "ordens", "carteira", "swing", "serie", "diario"):
        assert k in tela
    for k in ("estado", "resumo_evidencia", "regras", "dimensionamento", "livro", "posicoes", "medidas_abertas", "candidatas_hoje", "placar", "evidencia", "fechadas_recentes"):
        assert k in tela["swing"]
    assert len(tela["swing"]["evidencia"]) == 41 and len(tela["swing"]["placar"]["medido"]) == 41      # 39 pesquisados + M1 e M2 da mesa
    assert len(tela["swing"]["regras"]["setups"]) == 15


def test_trava_de_instancia_unica(ambiente, monkeypatch):
    import fcntl
    import os
    os.makedirs(os.environ["QUANT_SWING_DIR"], exist_ok=True)
    trava = open(est.arq("robo.trava"), "w")
    fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert vivo.rodar(uma_vez=False, saidas=[str(ambiente / "t.json")]) == 3
    finally:
        trava.close()


def test_placar_conta_so_medidas_fechadas_e_respeita_a_sobreposicao(ambiente):
    v = evidencia.por_variante()
    f = []
    for i, (res, top) in enumerate([(0.03, True), (-0.01, True), (0.02, False)]):
        f.append({"id": str(i), "setup": "A1", "modo": "medida", "status": "fechada", "resultado_pct": res, "resultado_rs": res * 6000, "overlays": {"top": top, "ibov_ok": True}})
    f.append({"id": "x", "setup": "A1", "modo": "capital", "status": "fechada", "resultado_pct": 0.5, "resultado_rs": 999, "overlays": {"top": True, "ibov_ok": True}})
    f.append({"id": "y", "setup": "A1", "modo": "medida", "status": "descartada", "resultado_pct": None, "resultado_rs": 0.0, "overlays": {}})
    linhas = {x["variante"]: x for x in painel.placar(f, v)}
    assert linhas["A1.S0"]["operacoes"] == 3 and linhas["A1.S1"]["operacoes"] == 2 and linhas["A1.S2"]["operacoes"] == 3
    assert linhas["A1.S0"]["acerto"] == pytest.approx(2 / 3) and linhas["A1.S0"]["expectativa_pct"] == pytest.approx(0.04 / 3)
    assert linhas["A1.S0"]["payoff"] == pytest.approx(0.025 / 0.01)
    assert painel.placar_capital(f)["operacoes"] == 1
