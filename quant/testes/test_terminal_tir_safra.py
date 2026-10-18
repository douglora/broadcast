"""A TIR que o robo usa desde 19/10/2026: a nova do terminal (metodo do Safra, cache/out/pagina/tir_safra.json), com a TIR prudente antiga
(cache/out/pagina/tir.json) como reserva etiquetada para o papel que a nova nao cobre. O terminal de mentira e o de `terminal_fixture.py`
(so a TIR antiga); estes testes gravam por cima a TIR nova, com numeros contados a mao."""
import json
from datetime import date

import pytest

from quant import terminal as T
from quant.testes.terminal_fixture import montar_terminal

HOJE = date(2026, 10, 12)


def _empresa(t, tir, premio, base="analistas", confianca="analistas", ciclo="normal", potencial=0.10, n=12, avisos=()):
    return {"t": t, "base": base, "tipo": "real", "tir": tir, "premio_ntnb35_pp": premio, "preco": 50.0, "preco_data": "2026-10-09",
            "analistas": {"alvo_medio": 55.0, "n": n, "potencial": potencial, "coleta": "2026-10-11"},
            "safra": {"tir": 11.7, "data": "2026-10-08", "fonte": "Safra"} if base == "safra" else None,
            "confianca": confianca, "avisos": list(avisos), "ciclo_do_lucro": ciclo}


def gravar_tir_safra(raiz, empresas, preco_data="2026-10-09"):
    for e in empresas.values():
        e["preco_data"] = preco_data
    d = {"gerado": "2026-10-12T09:00:00-03:00", "metodo": "safra_v2", "ntnb": {"venc": "2035-05-15", "taxa": 6.9, "data": "2026-10-09"},
         "empresas": empresas, "fora": [{"t": "ENEV3", "motivo": "sem preco-alvo"}]}
    p = raiz / "cache" / "out" / "pagina" / "tir_safra.json"
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    T.limpar_cache()


@pytest.fixture
def raiz(tmp_path, monkeypatch):
    montar_terminal(tmp_path)
    monkeypatch.setenv("AUTOPILOT_TERMINAL", str(tmp_path))
    T.limpar_cache()
    yield tmp_path
    T.limpar_cache()


@pytest.fixture
def com_nova(raiz):
    gravar_tir_safra(raiz, {
        "PETR4": _empresa("PETR4", 0.103305, 3.43, potencial=0.0117, n=13, avisos=["alvo de 13 casas"]),
        "DIRR3": _empresa("DIRR3", 0.1178, 4.88, base="safra", confianca="alta", ciclo="pico_provavel"),
        "PRIO3": _empresa("PRIO3", 0.15, None, ciclo="fundo")})                     # so na TIR nova; premio sem campo: TIR menos a NTN-B 2035
    return raiz


def test_sem_o_arquivo_novo_tudo_e_a_antiga_com_etiqueta(raiz):
    t = T.ficha("PETR4", hoje=HOJE)["tir"]
    assert t["fonte_tir"] == "antiga" and "tir_safra.json" in t["reserva"] and "ausente" in t["reserva"]
    assert t["tir_prudente"]["pct"] == 18.39 and t["tir_prudente"]["fonte"] == "antiga" and t["tir_prudente"]["ntnb"]["vencimento"] == "2037-05-15"
    assert t["tir_antiga"]["pct"] == 18.39 and t["tir_safra"] is None
    r = T.tabela(["PETR4"], hoje=HOJE).loc["PETR4"]
    assert r["tir_fonte"] == "antiga" and r["tir_prudente_pct"] == 18.39 and r["tir_premio_pp"] == 11.68 and r["tir_antiga_pct"] == 18.39


def test_papel_na_tir_nova_usa_a_nova_e_guarda_a_antiga_ao_lado(com_nova):
    t = T.ficha("PETR4", hoje=HOJE)["tir"]
    assert t["fonte_tir"] == "analistas" and t["reserva"] is None and "tir_safra.json" in t["fonte"] and t["idade_dias"] == 3
    assert t["tir_prudente"] == {"pct": 10.33, "base": "analistas", "pico": False, "premio_pp": 3.43, "fonte": "analistas",
                                 "ntnb": {"taxa_pct": 6.9, "vencimento": "2035-05-15", "data": "2026-10-09"}}
    assert t["tir_antiga"]["pct"] == 18.39 and t["tir_antiga"]["premio_pp"] == 11.68
    assert t["tir_hoje_pct"] == 18.39                                              # o modelo antigo continua visivel quando cobre o papel
    assert t["avisos"] == ["alvo de 13 casas"] and any("1 casa" in a for a in t["avisos_tir_antiga"])
    r = T.tabela(["PETR4"], hoje=HOJE).loc["PETR4"]
    assert r["tir_prudente_pct"] == 10.33 and r["tir_premio_pp"] == 3.43 and r["tir_fonte"] == "analistas" and r["tir_confianca"] == "analistas"
    assert r["tir_potencial_pct"] == 1.17 and r["tir_analistas_n"] == 13 and r["tir_antiga_pct"] == 18.39 and r["tir_antiga_premio_pp"] == 11.68


def test_base_safra_e_pico_vem_da_tir_nova(com_nova):
    d = T.ficha("DIRR3", hoje=HOJE)["tir"]
    assert d["fonte_tir"] == "safra" and d["tir_prudente"]["pct"] == 11.78 and d["tir_prudente"]["pico"] is True
    assert d["tir_safra"]["safra"]["tir_pct"] == 11.7 and d["tir_safra"]["confianca"] == "alta"
    assert d["tir_antiga"]["base"] == "normalizada" and d["tir_antiga"]["pct"] == 10.0


def test_papel_so_na_tir_nova_tem_ciclo_e_premio_contado(com_nova):
    p = T.ficha("PRIO3", hoje=HOJE)["tir"]
    assert p["tir_prudente"]["pct"] == 15.0 and p["tir_prudente"]["premio_pp"] == pytest.approx(15.0 - 6.9)
    assert p["ciclo_do_lucro"]["codigo"] == -1 and p["ciclo_do_lucro"]["marca"] == "fundo" and p["tir_antiga"] is None
    r = T.tabela(["PRIO3"], hoje=HOJE).loc["PRIO3"]
    assert r["ciclo_lucro"] == -1.0 and r["tir_fonte"] == "analistas" and r["tir_antiga_pct"] != r["tir_antiga_pct"]   # NaN: sem antiga


def test_papel_fora_da_nova_cai_na_reserva_antiga_com_o_motivo(com_nova):
    v = T.ficha("VALE3", hoje=HOJE)["tir"]
    assert v["fonte_tir"] == "antiga" and "nao cobre VALE3" in v["reserva"] and v["tir_prudente"]["pct"] == 20.0
    f = T.ficha("BBAS3", hoje=HOJE)                                                # em nenhuma das duas
    assert f["tir"] is None and "TIR nova" in f["motivos"]["tir"] and "TIR antiga" in f["motivos"]["tir"]
    f = T.ficha("ENEV3", hoje=HOJE)
    assert f["tir"] is None and "sem preco-alvo" in f["motivos"]["tir"] and "sem payout" in f["motivos"]["tir"]


def test_tir_nova_velha_vira_reserva_e_as_duas_velhas_viram_none(com_nova):
    gravar_tir_safra(com_nova, {"PETR4": _empresa("PETR4", 0.103305, 3.43)}, preco_data="2026-10-01")
    t = T.ficha("PETR4", hoje=HOJE)["tir"]
    assert t["fonte_tir"] == "antiga" and "11 dias" in t["reserva"] and t["tir_prudente"]["pct"] == 18.39
    f = T.ficha("PETR4", hoje=date(2026, 10, 20))
    assert f["tir"] is None and "TIR nova" in f["motivos"]["tir"] and "TIR antiga" in f["motivos"]["tir"]
