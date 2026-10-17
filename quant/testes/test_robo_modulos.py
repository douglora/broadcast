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


def test_ligar_diz_a_janela_que_vale_hoje(modo, tmp_path, monkeypatch, capsys):
    """Achado 84 (15/10/2026): o 'Robô - ligar' dizia 'opera das 9h15 às 13h'; desde 13/10 a janela vai até 18h10 (zera 18h24)."""
    from quant.daytrade import chave
    monkeypatch.setattr(chave, "ARQ_CHAVE", str(tmp_path / "chave.json"))       # a chave de verdade e do Douglas
    monkeypatch.setattr(chave, "ARQ_JANELA", str(tmp_path / "janela.json"))
    modo.write_text(json.dumps({"hora_ultima_entrada": "18:10", "hora_zerar": "18:24"}))
    assert robo.main(["ligar"]) == 0
    saida = capsys.readouterr().out
    assert "Robô LIGADO" in saida and "9h15 às 18h10; zera tudo às 18h24" in saida and "13h" not in saida
    modo.write_text(json.dumps({}))                                              # sem as chaves: a janela de 08/10
    robo.main(["ligar"])
    assert "9h15 às 12h50; zera tudo às 13h00" in capsys.readouterr().out
    assert json.loads((tmp_path / "chave.json").read_text())["ligado"] is True


def test_manha_refaz_o_painel_de_opcoes_com_a_cadeia_de_ontem(modo, monkeypatch):
    """Achado 82 (15/10/2026): o painel de opcoes so rodava na rotina da noite, antes de a B3 publicar o arquivo do dia, e o pregao
    inteiro ficava com a cadeia de dois pregoes atras. Agora roda de manha, depois das boletas, e a falha dele so avisa."""
    from datetime import date
    feitos = []
    monkeypatch.setattr(robo, "passo", lambda dia, nome, args, timeout=0, repetir=False: feitos.append((nome, args, repetir)) or nome != "opcoes")
    monkeypatch.setattr(robo, "_boleta_swing_emitida", lambda dia: False)
    assert robo.preparar(date(2026, 10, 15), mods=["swing", "daytrade"]) is True          # a falha do painel nao reprova a manha
    nomes = [n for n, _a, _r in feitos]
    assert nomes[-2:] == ["swing", "opcoes"] and feitos[-1][1] == ["-m", "quant.opcoes.painel"] and feitos[-1][2] is False
    feitos.clear()                                                                     # robo religado com a boleta de swing ja emitida
    monkeypatch.setattr(robo, "_boleta_swing_emitida", lambda dia: True)
    assert robo.preparar(date(2026, 10, 15), mods=["swing", "daytrade"]) is True
    assert [n for n, _a, _r in feitos] == ["observacao", "prova_viva", "opcoes"] and feitos[-1][2] is False   # uma vez por dia


def test_fim_do_expediente_vem_do_modo(modo):
    # 17/10/2026, o Douglas: "so consigo deixar o mac ligado das 9 as 13h"
    assert robo.fim_do_expediente() == robo.HORA_FIM_VIVO                    # sem a chave: o fim do pregao, como sempre foi
    modo.write_text(json.dumps({"fim_do_expediente": "12:55"}))
    assert robo.fim_do_expediente() == "12:55"
    for ruim in ("25:00", "8:30", "19:00", "", None, 7):
        modo.write_text(json.dumps({"fim_do_expediente": ruim}))
        assert robo.fim_do_expediente() == robo.HORA_FIM_VIVO


def test_processo_de_ontem_que_acorda_hoje_sai_com_erro_para_o_agendador_religar(modo, monkeypatch):
    from datetime import datetime, timedelta, timezone
    brt = timezone(timedelta(hours=-3))
    relogio = [datetime(2026, 10, 19, 12, 50, tzinfo=brt)]
    monkeypatch.setattr(robo, "agora_brt", lambda: relogio[0])
    monkeypatch.setattr(robo.calendario, "eh_pregao", lambda d: True)

    def dormiu(hoje):                                                         # o Mac dormiu as 13h e so acordou no dia seguinte
        relogio[0] = datetime(2026, 10, 20, 9, 0, tzinfo=brt)
        return 0
    monkeypatch.setattr(robo, "_dia_dos_dois", dormiu)
    modo.write_text(json.dumps({"robo": "daytrade", "modulos": ["swing", "daytrade"]}))
    assert robo.dia() == 1                                                     # o launchd (KeepAlive) religa e o pregao de hoje comeca do zero
    monkeypatch.setattr(robo, "_dia_dos_dois", lambda hoje: 0)
    assert robo.dia() == 0                                                     # o dia normal sai com 0
    relogio[0] = datetime(2026, 10, 19, 12, 50, tzinfo=brt)
    monkeypatch.setattr(robo, "_dia_fatores", dormiu)
    assert robo.dia(so="fatores") == 0                                         # o filho nao decide: quem sai com 1 e o processo principal
