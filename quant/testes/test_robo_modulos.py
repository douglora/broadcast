"""Modulos lado a lado (10/10/2026): a carteira de fatores e o day trade rodam no mesmo dia, cada um no seu processo e
com o seu arquivo de tela; o modulo de mini-indice mostra as regras em prova viva."""
import json

import pytest

from quant import robo


@pytest.fixture
def modo(tmp_path, monkeypatch):
    arq = tmp_path / "modo_robo.json"
    monkeypatch.setattr(robo, "ARQ_MODO", str(arq))
    return arq


def test_sem_a_chave_modulos_vale_o_modo_antigo(modo):
    assert robo.modulos() == ["fatores"]                         # sem arquivo: a carteira, como sempre foi
    modo.write_text(json.dumps({"robo": "daytrade"}))
    assert robo.modulos() == ["daytrade"]
    modo.write_text(json.dumps({"robo": "daytrade", "modulos": []}))
    assert robo.modulos() == ["daytrade"]                        # lista vazia nao desliga tudo: cai no modo
    modo.write_text(json.dumps({"robo": "daytrade", "modulos": ["opcoes", 7]}))
    assert robo.modulos() == ["daytrade"]                        # nome desconhecido e ignorado


def test_modulos_lado_a_lado_sem_repetir(modo):
    modo.write_text(json.dumps({"robo": "daytrade", "modulos": ["fatores", "daytrade", "fatores", "x"]}))
    assert robo.modulos() == ["fatores", "daytrade"]


def test_dia_escolhe_o_caminho_pelo_modulo(modo, monkeypatch):
    chamadas = []
    monkeypatch.setattr(robo.calendario, "eh_pregao", lambda d: True)
    monkeypatch.setattr(robo, "_dia_dos_dois", lambda hoje: chamadas.append("dois") or 0)
    monkeypatch.setattr(robo, "_dia_fatores", lambda hoje: chamadas.append("fatores") or 0)
    modo.write_text(json.dumps({"robo": "daytrade", "modulos": ["fatores", "daytrade"]}))
    assert robo.dia() == 0 and chamadas == ["dois"]
    assert robo.dia(so="fatores") == 0 and chamadas == ["dois", "fatores"]     # o filho pede um modulo so
    modo.write_text(json.dumps({"robo": "fatores"}))
    assert robo.dia() == 0 and chamadas[-1] == "fatores"


def test_fim_de_semana_nao_sobe_nada(modo, monkeypatch):
    monkeypatch.setattr(robo.calendario, "eh_pregao", lambda d: False)
    monkeypatch.setattr(robo, "_dia_dos_dois", lambda hoje: pytest.fail("nao devia rodar"))
    modo.write_text(json.dumps({"modulos": ["fatores", "daytrade"]}))
    assert robo.dia() == 0


def test_os_dois_juntos_o_day_trade_sobe_a_parte_e_a_carteira_nao_o_derruba(modo, monkeypatch):
    visto = {}

    class Filho:
        def __init__(self, args, cwd=None):
            visto["args"], visto["cwd"] = args, cwd

        def wait(self):
            visto["esperou"] = True
            return 0

    monkeypatch.setattr(robo.subprocess, "Popen", Filho)

    def carteira_quebra(hoje):
        raise RuntimeError("download falhou")

    monkeypatch.setattr(robo, "_dia_fatores", carteira_quebra)
    assert robo._dia_dos_dois("2026-10-13") == 0                 # codigo 0: o agendador nao religa e nao sobe outro day trade
    assert visto["args"][-4:] == ["quant.robo", "dia", "--modulo", "daytrade"] and visto["esperou"] is True


def test_painel_do_mini_indice_com_e_sem_medicao(tmp_path, monkeypatch):
    from quant.pesquisa import prova_viva as pv
    monkeypatch.setattr(pv, "SAIDA", str(tmp_path / "prova_viva.jsonl"))          # sem medicao gravada
    regras = [{"nome": "a", "titulo": "Regra A", "desde": "2026-10-10", "historico": "h", "explicacao": "e"},
              {"nome": "b", "titulo": "Regra B", "desde": "2026-10-13"}]
    saida = tmp_path / "quant_indice.json"
    o = pv.painel(regras=regras, saidas=[str(saida)])
    assert o["tipo"] == "indice" and o["estado"] == "medindo" and [r["negocios"] for r in o["regras"]] == [0, 0]
    assert o["negocios"] == [] and o["serie"] == [] and any("Ainda não houve medição" in a for a in o["avisos"])
    assert o["regras"][0]["media_rs"] is None and "faltam 60" in o["regras"][0]["falta_para_estudo"]   # numero ausente nao vira zero
    assert json.loads(saida.read_text())["regras"][0]["explicacao"] == "e"

    fora = [{"nome": "a", "titulo": "Regra A", "desde": "2026-10-10", "negocios": 2, "acerto": 50.0, "media": 5.0, "t": None, "soma": 10.0,
             "pedir_estudo": False,
             "lista": [{"dia": "2026-10-13", "hora": "17:25", "lado": "C", "entrada": 150000.0, "pts": 120.0, "motivo": "tempo", "minutos": 25, "res": 47.4},
                       {"dia": "2026-10-14", "hora": "17:25", "lado": "V", "entrada": 151000.0, "pts": -90.0, "motivo": "tempo", "minutos": 25, "res": -37.4}]},
            {"nome": "b", "titulo": "Regra B", "erro": "o MetaTrader nao entregou as barras (esta aberto?)"}]
    o = pv.painel(fora, regras, saidas=[str(saida)])
    assert [r["negocios"] for r in o["regras"]] == [2, 0] and o["regras"][0]["total_rs"] == 10.0
    assert [g["dia"] for g in o["negocios"]] == ["2026-10-14", "2026-10-13"]      # o mais novo em cima
    assert o["serie"] == [{"dia": "2026-10-13", "resultado_rs": 47.4, "acumulado_rs": 47.4},
                          {"dia": "2026-10-14", "resultado_rs": -37.4, "acumulado_rs": 10.0}]
    assert any("Regra B" in a and "MetaTrader" in a for a in o["avisos"])
