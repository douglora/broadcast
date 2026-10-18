"""Leitura do banco historico do terminal (SQLite criado por `python -m coletor.banco`) e a CLI do pacote."""
import sqlite3
from datetime import date, datetime, time

import pytest

from quant import terminal as T
from quant.terminal import __main__ as cli
from quant.terminal._leitor import FUSO_BRT
from quant.testes.terminal_fixture import montar_terminal

HOJE = date(2026, 10, 12)


@pytest.fixture
def raiz(tmp_path, monkeypatch):
    montar_terminal(tmp_path)
    monkeypatch.setenv("AUTOPILOT_TERMINAL", str(tmp_path))
    monkeypatch.setattr("quant.terminal._leitor.hoje", lambda: HOJE)             # a CLI usa o relogio: fixa o dia para o teste nao envelhecer
    monkeypatch.setattr("quant.terminal._leitor.agora", lambda: datetime.combine(HOJE, time(9, 0), FUSO_BRT))   # e a hora (a TIR confere horas)
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


# ---- tabela `tir` no esquema v3: colunas canonicas (conta do terminal endogeno) primeiro, legado documentado
@pytest.fixture
def banco_v3(raiz):
    p = raiz / "cache" / "banco" / "terminal.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE meta (chave TEXT PRIMARY KEY, valor TEXT)")
    con.execute("CREATE TABLE tir (data TEXT, ticker TEXT, tir_hoje_pct REAL, tir_normalizada_pct REAL, tir_prudente_pct REAL, premio_pp REAL, "
                "ciclo_nivel TEXT, tir_principal_pct REAL, tir_principal_norm_pct REAL, tir_principal_prudente_pct REAL, tir_principal_base TEXT, "
                "premio_principal_pp REAL, conta TEXT, origem TEXT, PRIMARY KEY (data, ticker))")
    con.executemany("INSERT INTO tir VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        # reconstruida antiga: a conta antiga no legado, a canonica preenchida depois
        ("2022-06-30", "PETR4", 29.57, 5.48, 5.48, 1.2, "pico_provavel", 24.04, 7.74, 7.74, "normalizada", 3.1, "menor_das_duas", "reconstruida"),
        # retrato novo: tudo pela conta nova
        ("2026-10-11", "PETR4", 18.39, 10.74, 18.48, 11.77, "normal", 18.48, 12.77, 18.48, "hoje", 11.77, "endogena", "retrato")])
    con.commit()
    con.close()
    return p


def test_tir_devolve_as_colunas_canonicas_logo_depois_de_data_e_ticker(banco_v3):
    df = T.historico("tir", "PETR4")
    assert list(df.columns[:8]) == ["data", "ticker", "tir_principal_pct", "tir_principal_norm_pct", "tir_principal_prudente_pct",
                                    "tir_principal_base", "premio_principal_pp", "conta"]
    assert list(df["data"]) == ["2022-06-30", "2026-10-11"] and list(df["tir_principal_prudente_pct"]) == [7.74, 18.48]


def test_tir_o_legado_continua_la_e_a_conta_diz_qual_definicao(banco_v3):
    df = T.historico("tir", "PETR4")
    assert {"tir_hoje_pct", "tir_normalizada_pct", "tir_prudente_pct", "premio_pp"} <= set(df.columns)
    assert list(df["conta"]) == ["menor_das_duas", "endogena"] and list(df["tir_prudente_pct"]) == [5.48, 18.48]
    # a serie canonica nunca mistura definicoes; a antiga mistura (por isso e legado): na mesma data de 2022 as duas diferem
    assert df.loc[0, "tir_principal_prudente_pct"] != df.loc[0, "tir_prudente_pct"]


def test_tir_documenta_o_legado_nos_attrs(banco_v3):
    df = T.historico("tir")
    assert df.attrs["canonicas"] == ["tir_principal_pct", "tir_principal_norm_pct", "tir_principal_prudente_pct", "tir_principal_base",
                                     "premio_principal_pp", "conta"]
    assert "tir_prudente_pct" in df.attrs["legado"] and "tir_hoje_pct" in df.attrs["legado"]
    assert "LEGADO" in df.attrs["nota"] and "menor_das_duas" in df.attrs["nota"] and "SEMPRE a conta endogena" in df.attrs["nota"] and "motivo" not in df.attrs


def test_tir_filtros_continuam_valendo(banco_v3):
    assert list(T.historico("tir", desde="2026-01-01")["data"]) == ["2026-10-11"]
    assert len(T.historico("tir", "VALE3")) == 0


def test_tir_banco_ainda_no_esquema_antigo_avisa_em_vez_de_inventar(banco):
    df = T.historico("tir", "PETR4")                                            # a tabela do fixture antigo nao tem as canonicas
    assert "tir_principal_prudente_pct" not in df.columns and "tir_prudente_pct" in df.columns
    assert "--preencher --so tir" in df.attrs["motivo"] and df.attrs["legado"] == ["tir_prudente_pct"]


def test_outras_tabelas_nao_ganham_attrs_de_tir(banco):
    assert "canonicas" not in T.historico("tir_geral").attrs and "canonicas" not in T.historico("opcoes_ativo").attrs


def test_cli_historico_tir_imprime_a_nota(banco_v3, capsys):
    assert cli.main(["historico", "tir", "--ticker", "PETR4"]) == 0
    out = capsys.readouterr().out
    assert "tir_principal_pct" in out and "nota:" in out and "LEGADO" in out
