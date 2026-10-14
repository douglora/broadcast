"""14/10/2026: a reabertura do MetaTrader espera so pela XP, encerra a segunda instancia orfa pelo pid e confere que a XP voltou."""
import subprocess

from quant.daytrade import ligar_fita as lf


class _Run:
    """Finge o pgrep: devolve os pids por padrao conforme a 'cena' muda a cada chamada de open/quit."""

    def __init__(self, cenas):
        self.cenas, self.chamadas, self.i = cenas, [], 0

    def __call__(self, cmd, **kw):
        self.chamadas.append(cmd)
        if cmd[0] == "pgrep":
            vivos = self.cenas[min(self.i, len(self.cenas) - 1)]
            achados = [p for padrao, p in vivos.items() if padrao == cmd[2]]
            return subprocess.CompletedProcess(cmd, 0 if achados else 1, stdout="\n".join(str(x) for x in achados) + "\n", stderr="")
        if cmd[0] in ("osascript", "open"):
            self.i += 1                                           # quit e open mudam a cena
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def test_segunda_orfa_e_encerrada_e_a_xp_volta(monkeypatch):
    # cena 0 (antes do quit): XP 100 e segunda 200 vivas; cena 1 (depois do quit): so a segunda 200, orfa; cena 2 (depois do open): XP 300 de volta
    run = _Run([{lf.PADRAO_XP: 100, lf.PADRAO_SEGUNDA: 200}, {lf.PADRAO_SEGUNDA: 200}, {lf.PADRAO_XP: 300}])
    mortos, notas = [], []
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(lf.os, "kill", lambda pid, sig: mortos.append((pid, sig)))
    monkeypatch.setattr(lf.time, "sleep", lambda s: None)
    assert lf._reabrir_metatrader(log=notas.append) is True
    assert mortos == [(200, 15)]                                      # a orfa morre pelo pid, nunca taskkill /im
    assert sum(1 for c in run.chamadas if c[0] == "open") == 1       # a XP voltou na primeira tentativa
    assert any("órfã" in n for n in notas)


def test_sem_orfa_nao_mata_nada_e_tenta_duas_vezes_se_a_xp_nao_volta(monkeypatch):
    run = _Run([{lf.PADRAO_XP: 100}, {}, {}, {}])                   # depois do quit nao sobra ninguem; a XP nunca volta
    mortos, notas = [], []
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(lf.os, "kill", lambda pid, sig: mortos.append((pid, sig)))
    monkeypatch.setattr(lf.time, "sleep", lambda s: None)
    assert lf._reabrir_metatrader(log=notas.append) is False
    assert mortos == [] and sum(1 for c in run.chamadas if c[0] == "open") == 2
    assert len([n for n in notas if "não voltou" in n]) == 2
