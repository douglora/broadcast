"""Eventos dos proximos dias: janela, ordem, filtros e o aviso quando o calendario esta velho."""
import json
from datetime import date

import pytest

from quant import terminal as T
from quant.testes.terminal_fixture import montar_terminal

HOJE = date(2026, 10, 12)


@pytest.fixture
def raiz(tmp_path, monkeypatch):
    montar_terminal(tmp_path)
    monkeypatch.setenv("AUTOPILOT_TERMINAL", str(tmp_path))
    T.limpar_cache()
    yield tmp_path
    T.limpar_cache()


def test_janela_de_10_dias_e_a_ordem(raiz):
    ev = T.eventos(10, hoje=HOJE)
    # de 12/10 a 22/10: sai o resultado de novembro, o ja passado (05/10), o de dezembro e o Focus de 26/10
    assert [(e["data"], e["tipo"], e["ticker"]) for e in ev] == [
        ("2026-10-13", "provento_ex", "PETR4"), ("2026-10-14", "macro", None), ("2026-10-14", "resultado", "JPM"), ("2026-10-14", "macro", None),
        ("2026-10-16", "vencimento_opcoes", None), ("2026-10-20", "assembleia", "BBAS3")]
    assert ev.avisos == []


def test_campos_do_evento_de_empresa_e_de_macro(raiz):
    ev = T.eventos(10, hoje=HOJE)
    prov = ev[0]
    assert prov["dias_ate"] == 1 and prov["tickers"] == ["PETR3", "PETR4"] and "JCP" in prov["detalhe"] and prov["titulo"].startswith("Data ex")
    ipca = next(e for e in ev if e["titulo"] == "IPCA (mes)")
    assert ipca["pais"] == "BR" and ipca["relevancia"] == 3 and ipca["expectativa"] == 0.5 and ipca["anterior"] == 0.82 and ipca["efetivo"] is None and ipca["hora"] == "09:00"
    jpm = next(e for e in ev if e["ticker"] == "JPM")
    assert jpm["pais"] == "US" and jpm["titulo"] == "Resultado 3T26 - JPMorgan"


def test_janela_maior_traz_o_resultado_da_petrobras(raiz):
    ev = T.eventos(30, hoje=HOJE)
    r = [e for e in ev if e["tipo"] == "resultado" and e["ticker"] == "PETR4"]
    assert len(r) == 1 and r[0]["data"] == "2026-11-10" and r[0]["dias_ate"] == 29 and r[0]["periodo"] == "3T26"


def test_filtros_de_pais_tipo_e_ticker(raiz):
    assert {e["pais"] for e in T.eventos(10, hoje=HOJE, pais="BR")} == {"BR"}
    assert [e["tipo"] for e in T.eventos(10, hoje=HOJE, tipos=["assembleia"])] == ["assembleia"]
    so_petr = T.eventos(30, hoje=HOJE, tickers=["petr4"])
    assert {e["tipo"] for e in so_petr} == {"provento_ex", "resultado"} and all("PETR4" in e["tickers"] or e["ticker"] == "PETR4" for e in so_petr)


def test_calendario_velho_e_descartado_com_aviso(raiz):
    ev = T.eventos(10, hoje=date(2026, 10, 20))
    assert list(ev) == [] and len(ev.avisos) == 2 and "limite de 3" in ev.avisos[0]


def test_sem_terminal_devolve_lista_vazia_com_aviso(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_TERMINAL", str(tmp_path / "x"))
    T.limpar_cache()
    ev = T.eventos(10, hoje=HOJE)
    assert list(ev) == [] and len(ev.avisos) == 2


def test_evento_macro_traz_a_surpresa_e_a_fonte_da_expectativa(raiz):
    cpi = next(e for e in T.eventos(10, hoje=HOJE) if e["titulo"] == "CPI (mes)")
    assert cpi["expectativa"] == 0.3 and cpi["efetivo"] == 0.4 and cpi["surpresa"] == 0.1 and cpi["expectativa_fonte"].startswith("manual: Bloomberg")


def test_evento_de_resultado_traz_o_momento_estimado(raiz):
    r = next(e for e in T.eventos(30, hoje=HOJE) if e["ticker"] == "PRIO3" and e["tipo"] == "resultado")
    assert r["momento_estimado"] == "antes da abertura" and r["momento_confianca"] == 0.75 and r["antes_da_abertura"] is True
    assert next(e for e in T.eventos(30, hoje=HOJE) if e["ticker"] == "DIRR3" and e["tipo"] == "resultado")["antes_da_abertura"] is None


def test_sem_data_ex_futura_o_aviso_vem_do_arquivo_do_terminal(raiz):
    assert T.eventos(10, hoje=HOJE).avisos == []                                    # o fixture tem uma data ex futura (13/10)
    p = raiz / "cache" / "out" / "pagina" / "eventos.json"
    d = json.loads(p.read_text())
    d["fontes"] = {"proventos": {"data_com_futura": 0, "nota": "sem data ex futura porque a fonte nao tem: a B3 so lista depois da aprovacao"}}
    p.write_text(json.dumps(d))
    T.limpar_cache()
    ev = T.eventos(10, hoje=HOJE)
    assert len(ev.avisos) == 1 and ev.avisos[0].startswith("sem data ex de provento futura") and "aprovacao" in ev.avisos[0]
    assert T.eventos(10, hoje=HOJE, tipos=["macro"]).avisos == []                    # quem nao pediu provento nao recebe o aviso
