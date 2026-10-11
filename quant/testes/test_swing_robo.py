"""Modulo swing na rotina do robo: entra em MODULOS_VALIDOS, roda no lugar de `fatores` ao lado do day trade, e o `preparar` escolhe os passos certos.
O modulo `fatores` continua exatamente como era."""
import json

import pytest

from quant import robo


@pytest.fixture
def modo(tmp_path, monkeypatch):
    arq = tmp_path / "modo_robo.json"
    monkeypatch.setattr(robo, "ARQ_MODO", str(arq))
    monkeypatch.setattr(robo, "DIR_ROTINA", str(tmp_path / "rotina"))
    return arq


def test_swing_e_modulo_valido_e_fatores_continua(modo):
    assert "swing" in robo.MODULOS_VALIDOS and "fatores" in robo.MODULOS_VALIDOS and "daytrade" in robo.MODULOS_VALIDOS
    modo.write_text(json.dumps({"robo": "daytrade", "modulos": ["swing", "daytrade"]}))
    assert robo.modulos() == ["swing", "daytrade"]
    modo.write_text(json.dumps({"robo": "daytrade", "modulos": ["fatores", "swing", "daytrade"]}))
    assert robo.modulos() == ["fatores", "swing", "daytrade"]


def test_dia_roteia_swing(modo, monkeypatch):
    chamadas = []
    monkeypatch.setattr(robo.calendario, "eh_pregao", lambda d: True)
    monkeypatch.setattr(robo, "_dia_dos_dois", lambda hoje: chamadas.append("dois") or 0)
    monkeypatch.setattr(robo, "_dia_fatores", lambda hoje: chamadas.append("fatores") or 0)
    monkeypatch.setattr(robo, "_dia_swing", lambda hoje: chamadas.append("swing") or 0)
    modo.write_text(json.dumps({"robo": "daytrade", "modulos": ["swing", "daytrade"]}))
    assert robo.dia() == 0 and chamadas == ["dois"]                          # swing + day trade: cada um no seu processo
    assert robo.dia(so="swing") == 0 and chamadas[-1] == "swing"             # o filho (ou o ensaio) pede so o swing
    modo.write_text(json.dumps({"robo": "daytrade", "modulos": ["swing"]}))
    assert robo.dia() == 0 and chamadas[-1] == "swing"
    modo.write_text(json.dumps({"robo": "fatores"}))
    assert robo.dia() == 0 and chamadas[-1] == "fatores"                     # sem a chave: como sempre foi


def _com_filhos(monkeypatch):
    visto = {"filhos": []}

    class Filho:
        def __init__(self, args, cwd=None):
            visto["filhos"].append(args[-1])

        def wait(self):
            return 0

    monkeypatch.setattr(robo.subprocess, "Popen", Filho)
    return visto


def test_swing_e_day_trade_juntos_o_swing_roda_no_lugar_de_fatores(modo, monkeypatch):
    visto = _com_filhos(monkeypatch)
    rodou = []
    monkeypatch.setattr(robo, "_dia_swing", lambda hoje: rodou.append("swing"))
    monkeypatch.setattr(robo, "_dia_fatores", lambda hoje: rodou.append("fatores"))
    modo.write_text(json.dumps({"robo": "daytrade", "modulos": ["swing", "daytrade"]}))
    assert robo._dia_dos_dois("2026-10-13") == 0
    assert rodou == ["swing"] and visto["filhos"] == ["daytrade"]


def test_os_tres_juntos_fatores_neste_processo_e_swing_e_day_trade_filhos(modo, monkeypatch):
    visto = _com_filhos(monkeypatch)
    rodou = []
    monkeypatch.setattr(robo, "_dia_swing", lambda hoje: rodou.append("swing"))
    monkeypatch.setattr(robo, "_dia_fatores", lambda hoje: rodou.append("fatores"))
    modo.write_text(json.dumps({"modulos": ["fatores", "swing", "daytrade"]}))
    robo._dia_dos_dois("2026-10-13")
    assert rodou == ["fatores"] and sorted(visto["filhos"]) == ["daytrade", "swing"]


def test_swing_que_quebra_nao_derruba_o_day_trade(modo, monkeypatch):
    visto = _com_filhos(monkeypatch)

    def quebra(hoje):
        raise RuntimeError("sem dado")

    monkeypatch.setattr(robo, "_dia_swing", quebra)
    modo.write_text(json.dumps({"modulos": ["swing", "daytrade"]}))
    assert robo._dia_dos_dois("2026-10-13") == 0 and visto["filhos"] == ["daytrade"]


def _passos(monkeypatch, mods):
    nomes = []
    monkeypatch.setattr(robo, "passo", lambda dia, nome, args, timeout=1800, repetir=False: nomes.append(nome) or True)
    monkeypatch.setattr(robo, "_boleta_da_manha", lambda dia: None)
    monkeypatch.setattr(robo, "_boleta_swing_emitida", lambda dia: False)
    from datetime import date
    assert robo.preparar(date(2026, 10, 13), mods=mods) is True
    return nomes


def test_preparar_do_swing_faz_a_boleta_de_swing_e_nao_a_de_fatores(modo, monkeypatch):
    n = _passos(monkeypatch, ["swing"])
    assert n[-1] == "swing" and "boleta" not in n and "cotacoes" in n and "sinais" in n and "risco" in n


def test_preparar_de_fatores_nao_mudou(modo, monkeypatch):
    for mods in (["fatores"], ["daytrade"], None):
        n = _passos(monkeypatch, mods)
        assert n[-1] == "boleta" and "swing" not in n


def test_preparar_dos_dois_faz_as_duas_boletas_com_os_dados_uma_vez(modo, monkeypatch):
    n = _passos(monkeypatch, ["fatores", "swing"])
    assert n.count("cotacoes") == 1 and n[-2:] == ["boleta", "swing"]


def test_preparar_do_swing_nao_roda_de_novo_com_boleta_emitida(modo, monkeypatch):
    nomes = []
    monkeypatch.setattr(robo, "passo", lambda *a, **k: nomes.append(a[1]) or True)
    monkeypatch.setattr(robo, "_boleta_swing_emitida", lambda dia: True)
    from datetime import date
    assert robo.preparar(date(2026, 10, 13), mods=["swing"]) is True and nomes == []


def test_linha_de_comando_preparar_modulo_swing(modo, monkeypatch):
    visto = {}
    monkeypatch.setattr(robo, "preparar", lambda d, repetir=False, mods=None: visto.update(mods=mods) or True)
    assert robo.main(["preparar", "--modulo", "swing"]) == 0 and visto["mods"] == ["swing"]
    assert robo.main(["preparar"]) == 0 and visto["mods"] is None


def test_dia_swing_prepara_e_sobe_o_robo_ao_vivo(modo, monkeypatch):
    chamadas = []
    monkeypatch.setattr(robo, "preparar", lambda hoje, repetir=False, mods=None: chamadas.append(("preparar", mods)) or True)
    monkeypatch.setattr(robo, "vivo_swing", lambda ate=robo.HORA_FIM_VIVO: chamadas.append(("vivo", ate)) or 0)
    from datetime import datetime
    from quant.comum import FUSO_BRT
    monkeypatch.setattr(robo, "agora_brt", lambda: datetime(2026, 10, 13, 8, 35, tzinfo=FUSO_BRT))
    assert robo._dia_swing(robo.agora_brt().date()) == 0
    assert chamadas == [("preparar", ["swing"]), ("vivo", "18:30")]
    chamadas.clear()
    monkeypatch.setattr(robo, "agora_brt", lambda: datetime(2026, 10, 13, 19, 0, tzinfo=FUSO_BRT))
    robo._dia_swing(robo.agora_brt().date())
    assert chamadas == []                                                      # depois do fim do pregao nao sobe nada
