"""Leitura do banco historico do terminal (SQLite criado por `python -m coletor.banco`) e a CLI do pacote."""
import sqlite3
from datetime import date

import pytest

from quant import terminal as T
from quant.terminal import __main__ as cli
from quant.testes.terminal_fixture import montar_terminal

HOJE = date(2026, 10, 12)


@pytest.fixture
def raiz(tmp_path, monkeypatch):
    montar_terminal(tmp_path)
    monkeypatch.setenv("AUTOPILOT_TERMINAL", str(tmp_path))
    monkeypatch.setattr("quant.terminal._leitor.hoje", lambda: HOJE)             # a CLI usa o relogio: fixa o dia para o teste nao envelhecer
    T.limpar_cache()
    yield tmp_path
    T.limpar_cache()


@pytest.fixture
def banco(raiz):
    """Banco no esquema do terminal (so as colunas que os testes usam)."""
    p = raiz / "cache" / "banco" / "terminal.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE meta (chave TEXT PRIMARY KEY, valor TEXT)")
    con.execute("CREATE TABLE tir (data TEXT, ticker TEXT, tir_prudente_pct REAL, origem TEXT, PRIMARY KEY (data, ticker))")
    con.execute("CREATE TABLE opcoes_ativo (data TEXT, ativo TEXT, iv_atm_pct REAL, origem TEXT, PRIMARY KEY (data, ativo))")
    con.execute("CREATE TABLE tir_geral (data TEXT PRIMARY KEY, ntnb_taxa_pct REAL)")
    con.executemany("INSERT INTO tir VALUES (?,?,?,?)", [("2026-10-10", "PETR4", 17.0, "retrato"), ("2026-10-08", "PETR4", 16.0, "retrato"),
                                                         ("2026-10-09", "PETR4", 16.5, "hist"), ("2026-10-09", "VALE3", 12.0, "retrato")])
    con.executemany("INSERT INTO opcoes_ativo VALUES (?,?,?,?)", [("2026-10-08", "PETR4", 31.4, "hist"), ("2026-10-09", "BOVA11", 20.0, "retrato")])
    con.execute("INSERT INTO tir_geral VALUES ('2026-10-10', 6.71)")
    con.commit()
    con.close()
    return p


def test_historico_filtra_por_ticker_e_vem_em_ordem_de_data(banco):
    df = T.historico("tir", "PETR4")
    assert list(df["data"]) == ["2026-10-08", "2026-10-09", "2026-10-10"] and list(df["tir_prudente_pct"]) == [16.0, 16.5, 17.0]
    assert set(df["origem"]) == {"retrato", "hist"}


def test_historico_desde_e_ticker_em_minusculas(banco):
    df = T.historico("tir", "petr4", desde="2026-10-09")
    assert list(df["data"]) == ["2026-10-09", "2026-10-10"]
    assert list(T.historico("tir", desde=date(2026, 10, 10))["data"]) == ["2026-10-10"]


def test_historico_sem_ticker_traz_a_tabela_toda(banco):
    assert len(T.historico("tir")) == 4 and len(T.historico("tir_geral")) == 1


def test_tabela_de_opcoes_filtra_pela_coluna_ativo(banco):
    df = T.historico("opcoes_ativo", "PETR4")
    assert len(df) == 1 and df.iloc[0]["iv_atm_pct"] == 31.4


def test_ticker_em_tabela_sem_coluna_de_ticker_e_erro(banco):
    with pytest.raises(ValueError, match="coluna de ticker"):
        T.historico("tir_geral", "PETR4")


def test_tabela_inexistente_e_erro_de_programacao(banco):
    with pytest.raises(ValueError, match="nao existe no banco"):
        T.historico("inventada")
    with pytest.raises(ValueError):
        T.historico("meta")                                                         # tabela interna nao se le por aqui


def test_sem_banco_devolve_vazio_com_o_motivo_e_nao_levanta(raiz):
    df = T.historico("tir", "PETR4")
    assert df.empty and "ainda nao existe" in df.attrs["motivo"] and "coletor.banco" in df.attrs["motivo"]


def test_historico_nao_escreve_no_banco(banco):
    antes = banco.stat().st_mtime_ns
    T.historico("tir", "PETR4")
    assert banco.stat().st_mtime_ns == antes


# ---------------------------------------------------------------- CLI
def test_cli_ficha_texto_e_json(raiz, capsys, monkeypatch):
    assert cli.main(["ficha", "PETR4"]) == 0
    out = capsys.readouterr().out
    assert "FICHA PETR4" in out and "[tir]" in out and "tir_prudente.pct" in out and "11,68" in out
    assert cli.main(["ficha", "PETR4", "--json"]) == 0
    import json
    assert json.loads(capsys.readouterr().out)["tir"]["tir_prudente"]["premio_pp"] == 11.68


def test_cli_ficha_mostra_o_motivo_do_que_falta(raiz, capsys):
    cli.main(["ficha", "DIRR3"])
    assert "[consenso] SEM DADO" in capsys.readouterr().out


def test_cli_tabela_cobertura_e_colunas(raiz, capsys):
    assert cli.main(["tabela", "PETR4", "BBAS3", "--colunas", "pl,tir_prudente_pct"]) == 0
    out = capsys.readouterr().out
    assert "PETR4" in out and "5.41" in out
    assert cli.main(["tabela", "--cobertura"]) == 0
    assert "tir_prudente_pct" in capsys.readouterr().out
    assert cli.main(["tabela", "PETR4", "--colunas", "nao_existe"]) == 2


def test_cli_eventos_e_status(raiz, capsys):
    assert cli.main(["eventos", "--dias", "10"]) == 0
    assert "6 evento(s)" in capsys.readouterr().out
    assert cli.main(["status"]) == 0
    assert "disponivel: sim" in capsys.readouterr().out


def test_cli_historico_sem_banco_diz_o_que_fazer(raiz, capsys):
    assert cli.main(["historico", "tir"]) == 0
    assert "coletor.banco" in capsys.readouterr().out
