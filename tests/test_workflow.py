"""O agendamento do livro.yml tem de resolver para o modo certo.

Em 23/09 a auditoria achou os crons de 08h20 e 18h05 BRT caindo em MODO=intradia,
porque o `case` do workflow ainda casava as strings dos crons antigos."""

from __future__ import annotations

import yaml

from datetime import datetime, timezone

from livro.agenda_modo import modo_do_cron, modo_efetivo


def _crons():
    wf = yaml.safe_load(open(".github/workflows/livro.yml", encoding="utf-8"))
    gatilhos = wf.get("on", wf.get(True))       # YAML 1.1 le `on` como True
    return [c["cron"] for c in gatilhos["schedule"]]


def test_todo_cron_do_workflow_resolve_para_um_modo_de_proposito():
    modos = {c: modo_do_cron(c) for c in _crons()}
    assert sorted(modos.values()) == ["fechamento", "intradia", "manha"], modos


def test_fechamento_e_manha_pelos_crons_atuais():
    crons = _crons()
    assert modo_do_cron(next(c for c in crons if c.split()[1] == "21")) == "fechamento"
    assert modo_do_cron(next(c for c in crons if c.split()[1] == "11")) == "manha"


def test_minuto_nao_muda_o_modo():
    for m in ("0", "5", "28", "59"):
        assert modo_do_cron(f"{m} 21 * * 1-5") == "fechamento"
        assert modo_do_cron(f"{m} 11 * * 1-5") == "manha"
    assert modo_do_cron("5 13-20 * * 1-5") == "intradia"
    assert modo_do_cron("") == "intradia"


def test_workflow_usa_o_resolvedor_e_nao_um_case_de_strings():
    txt = open(".github/workflows/livro.yml", encoding="utf-8").read()
    assert "python -m livro.agenda_modo" in txt
    assert '"28 21 * * 1-5")' not in txt and '"50 9 * * 1-5")' not in txt


def _utc(dia, h, m):
    return datetime(2026, 9, dia, h, m, tzinfo=timezone.utc)


def test_rodada_atrasada_vale_pela_hora_em_que_dispara():
    # 24/09: o cron das 08h20 BRT saiu as 12h49 e rodou como manha no meio do pregao
    assert modo_efetivo("20 11 * * 1-5", _utc(24, 15, 49)) == "intradia"
    assert modo_efetivo("20 11 * * 1-5", _utc(24, 11, 25)) == "manha"
    # fechamento atrasado para a noite continua fechamento; para o pregao seguinte, nao
    assert modo_efetivo("5 21 * * 1-5", _utc(25, 1, 13)) == "fechamento"
    assert modo_efetivo("5 21 * * 1-5", _utc(25, 13, 30)) == "intradia"
    # intradia fora do pregao so busca noticia e nao troca o slot do fechamento
    assert modo_efetivo("5 13-20 * * 1-5", _utc(24, 21, 30)) == "eventos"
    assert modo_efetivo("5 13-20 * * 1-5", _utc(24, 13, 10)) == "intradia"
    # manha atrasada ate depois do fechamento: so noticia
    assert modo_efetivo("20 11 * * 1-5", _utc(24, 21, 40)) == "eventos"
