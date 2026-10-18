"""A TIR que o robo usa desde 19/10/2026: so a nova do terminal (metodo do Safra), recalculada antes de ler e conferida ("o robo nao pode usar
antiga, sempre tem que ser TIR atualizada", Douglas, 18/10/2026). O terminal de mentira e o de `terminal_fixture.py`; o recalculo de verdade
nunca roda nos testes (conftest): aqui ele e trocado por funcoes que regravam o arquivo, falham ou contam as chamadas."""
import json
import subprocess
from datetime import date, datetime, timedelta, timezone

import pytest

from quant import terminal as T
from quant.terminal import _leitor as L
from quant.terminal import _tir
from quant.terminal._tir import recalcular as RECALCULAR_DE_VERDADE      # importado antes do conftest trocar a funcao
from quant.testes.terminal_fixture import montar_terminal

FUSO = timezone(timedelta(hours=-3))
NOVE_DE_12 = datetime(2026, 10, 12, 9, 0, tzinfo=FUSO)                   # 12/10/2026 e feriado: o ultimo pregao encerrado e 09/10


@pytest.fixture
def raiz(tmp_path, monkeypatch):
    montar_terminal(tmp_path)
    monkeypatch.setenv("AUTOPILOT_TERMINAL", str(tmp_path))
    T.limpar_cache()
    yield tmp_path
    T.limpar_cache()


def _arquivo(raiz):
    return raiz / "cache" / "out" / "pagina" / "tir_safra.json"


def _regravar(raiz, gerado, **por_papel):
    """Regrava a TIR nova como o recalculo do terminal faria: `gerado` novo e, por papel, os campos trocados."""
    d = json.loads(_arquivo(raiz).read_text(encoding="utf-8"))
    d["gerado"] = gerado.isoformat()
    for t, campos in por_papel.items():
        d["empresas"][t].update(campos)
    _arquivo(raiz).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def _checagens():
    try:
        return [json.loads(x) for x in open(_tir.ARQ_CHECAGENS, encoding="utf-8") if x.strip()]
    except OSError:
        return []


def test_so_a_tir_nova_e_lida_nunca_a_antiga(raiz, monkeypatch):
    lidos = []
    ler = L.ler
    monkeypatch.setattr(L, "ler", lambda rel, **kw: lidos.append(str(rel)) or ler(rel, **kw))
    assert T.ficha("PETR4", agora=NOVE_DE_12)["tir"]["tir_prudente"]["pct"] == 18.39
    f = T.ficha("VALE3", agora=NOVE_DE_12)                                            # so no arquivo antigo: sem TIR, sem reserva
    assert f["tir"] is None and "nao cobre VALE3" in f["motivos"]["tir"]
    T.tabela(agora=NOVE_DE_12)
    assert "pagina/tir_safra.json" in lidos and not any(x.endswith("pagina/tir.json") for x in lidos)


def test_o_recalculo_roda_antes_da_leitura_e_uma_vez_por_conferencia(raiz, monkeypatch):
    chamadas = []

    def recalculo():
        chamadas.append(1)
        _regravar(raiz, NOVE_DE_12 - timedelta(minutes=1), PETR4={"tir": 0.25, "premio_ntnb35_pp": 18.29})
    monkeypatch.setattr(_tir, "recalcular", recalculo)
    assert T.ficha("PETR4", agora=NOVE_DE_12)["tir"]["tir_prudente"]["pct"] == 25.0    # o numero do arquivo regravado: leu depois do recalculo
    df = T.tabela(agora=NOVE_DE_12 + timedelta(minutes=5))
    assert df.loc["PETR4", "tir_premio_pp"] == 18.29 and len(chamadas) == 1          # 4 papeis em 10 minutos: um recalculo so
    T.tabela(agora=NOVE_DE_12 + timedelta(minutes=11))
    assert len(chamadas) == 2                                                         # passou de 10 minutos: confere de novo
    assert [x["ok"] for x in _checagens()] == [True, True] and _checagens()[0]["hora"] == "09:00:00"


def test_recalculo_que_falha_deixa_o_dia_inteiro_sem_tir(raiz, monkeypatch, capsys):
    monkeypatch.setattr(_tir, "recalcular", lambda: "o recalculo saiu com codigo 1: so 12 empresas montaram")
    f = T.ficha("PETR4", agora=NOVE_DE_12)
    assert f["tir"] is None and "recalculo da TIR no terminal falhou" in f["motivos"]["tir"] and "so 12 empresas" in f["motivos"]["tir"]
    assert "TIR RECUSADA" in capsys.readouterr().out
    assert _checagens()[-1]["ok"] is False and "so 12 empresas" in _checagens()[-1]["motivo"]
    monkeypatch.setattr(_tir, "recalcular", lambda: None)                             # o terminal voltou, mas o dia ja foi recusado
    T.limpar_cache()
    f = T.ficha("PETR4", agora=NOVE_DE_12 + timedelta(hours=3))
    assert f["tir"] is None and "recusada hoje as 09:00:00" in f["motivos"]["tir"] and "resto do dia" in f["motivos"]["tir"]
    assert len(_checagens()) == 1                                                     # o dia recusado nem roda o recalculo de novo
    amanha = datetime(2026, 10, 13, 9, 0, tzinfo=FUSO)                                # no dia seguinte tudo recomeca
    monkeypatch.setattr(_tir, "recalcular", lambda: _regravar(raiz, amanha - timedelta(minutes=2)))
    assert T.ficha("PETR4", agora=amanha)["tir"]["tir_prudente"]["pct"] == 18.39


def test_arquivo_que_o_recalculo_nao_renovou_e_recusado(raiz, monkeypatch):
    agora = datetime(2026, 10, 14, 9, 0, tzinfo=FUSO)                                 # o recalculo "deu certo" mas o arquivo segue de 12/10
    t = T.tir_estado(agora=agora)
    assert t["ok"] is False and "acima do limite de 36 h" in t["motivo"] and t["sem_tir"] == {}
    assert T.tabela(agora=agora)["tir_prudente_pct"].isna().all()


def test_preco_velho_tira_so_aquele_papel(raiz, monkeypatch):
    monkeypatch.setattr(_tir, "recalcular", lambda: _regravar(raiz, NOVE_DE_12, PETR4={"preco_data": "2026-10-08"}))
    f = T.ficha("PETR4", agora=NOVE_DE_12)
    assert f["tir"] is None and "preco da TIR nova de PETR4 e de 08/10, antes do ultimo pregao encerrado (09/10)" in f["motivos"]["tir"]
    assert T.ficha("DIRR3", agora=NOVE_DE_12)["tir"]["tir_prudente"]["pct"] == 10.0
    t = T.tir_estado(agora=NOVE_DE_12)
    assert t["ok"] and t["empresas"] == 3 and t["ultimo_pregao"] == "2026-10-09"
    assert set(t["sem_tir"]) == {"ENEV3", "PETR4"} and "sem preco-alvo" in t["sem_tir"]["ENEV3"]


def test_o_recalculo_de_verdade_chama_o_comando_do_terminal(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_TERMINAL", str(tmp_path))
    assert "nao existe" in RECALCULAR_DE_VERDADE()                                    # sem o Python do terminal: falha com o motivo
    py = tmp_path / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("")
    vistos = []

    def rodar(args, **kw):
        vistos.append((args, kw.get("cwd")))
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(_tir.subprocess, "run", rodar)
    assert RECALCULAR_DE_VERDADE() is None
    assert vistos == [([str(py), "-m", "coletor.tir_safra"], str(tmp_path))]
    monkeypatch.setattr(_tir.subprocess, "run", lambda args, **kw: subprocess.CompletedProcess(args, 1, "", "linha 1\ntir_safra: so 12 empresas"))
    assert RECALCULAR_DE_VERDADE() == "o recalculo saiu com codigo 1: tir_safra: so 12 empresas"

    def demora(args, **kw):
        raise subprocess.TimeoutExpired(args, kw.get("timeout"))
    monkeypatch.setattr(_tir.subprocess, "run", demora)
    assert "passou de 120 s" in RECALCULAR_DE_VERDADE()


def test_ultimo_pregao_encerrado_vira_as_18h():
    assert _tir.ultimo_pregao_encerrado(datetime(2026, 10, 13, 17, 59, tzinfo=FUSO)) == date(2026, 10, 9)    # 12/10 feriado
    assert _tir.ultimo_pregao_encerrado(datetime(2026, 10, 13, 18, 0, tzinfo=FUSO)) == date(2026, 10, 13)
    assert _tir.ultimo_pregao_encerrado(datetime(2026, 10, 18, 12, 0, tzinfo=FUSO)) == date(2026, 10, 16)    # domingo
