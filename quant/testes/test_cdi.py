import json
import os

import pandas as pd
import pytest

from quant.dados import cdi

# Fixture no formato documentado da API do SGS (valor em % ao dia, data dd/mm/aaaa)
FIXTURE = [
    {"data": "02/01/2024", "valor": "0.043739"},
    {"data": "03/01/2024", "valor": "0.043739"},
    {"data": "04/01/2024", "valor": "0,043739"},     # virgula decimal: a API ja fez isso
    {"data": "05/01/2024", "valor": "0.043739"},
    {"data": "05/01/2024", "valor": "0.043740"},     # data repetida: fica a ultima
    {"data": "08/01/2024", "valor": "0.043740"},
    {"data": "xx/01/2024", "valor": "0.05"},         # lixo: descartado
    {"data": "09/01/2024", "valor": ""},             # sem valor: descartado
]


def test_parse_json_converte_para_decimal_diario():
    s = cdi.parse_json(FIXTURE)
    assert s.index.is_monotonic_increasing and not s.index.duplicated().any()
    assert str(s.index[0].date()) == "2024-01-02" and len(s) == 5
    assert abs(s.iloc[0] - 0.00043739) < 1e-12
    assert abs(s.loc["2024-01-04"] - 0.00043739) < 1e-12         # virgula decimal aceita
    assert abs(s.loc["2024-01-05"] - 0.00043740) < 1e-12         # duplicata: ultima vence
    assert cdi.parse_json(json.dumps(FIXTURE)).equals(s)         # aceita a string JSON crua
    assert len(cdi.parse_json([])) == 0 and len(cdi.parse_json("nao e json")) == 0


def test_acumular_e_anualizar():
    s = cdi.parse_json(FIXTURE)
    fator = cdi.acumular(s, "2024-01-02", "2024-01-05")
    esperado = (1.00043739 ** 3) * 1.00043740
    assert abs(fator - esperado) < 1e-12
    assert cdi.acumular(s, "2030-01-01", "2030-12-31") == 1.0          # sem dados: fator neutro
    aa = cdi.anualizar(s)
    assert 0.11 < aa < 0.12                                            # 0,0437%/dia ~ 11,6% a.a.
    assert pd.isna(cdi.anualizar(s, "2030-01-01", "2030-12-31"))


def test_blocos_respeitam_limite_da_api():
    from datetime import date
    b = cdi._blocos(date(2001, 1, 2), date(2026, 9, 7))
    assert b[0][0] == date(2001, 1, 2) and b[-1][1] == date(2026, 9, 7)
    assert all((fim - ini).days < 366 * cdi.BLOCO_ANOS for ini, fim in b)
    assert all(b[i][1].toordinal() + 1 == b[i + 1][0].toordinal() for i in range(len(b) - 1))


def test_blocos_atravessam_29_de_fevereiro():
    from datetime import date
    # cache terminando em 28/02/2024 -> proximo bloco comeca em 29/02: date(2033, 2, 29) nao existe
    b = cdi._blocos(date(2024, 2, 29), date(2040, 1, 1))
    assert b[0] == (date(2024, 2, 29), date(2033, 2, 27)) and b[-1][1] == date(2040, 1, 1)
    assert cdi._blocos(date(2024, 3, 1), date(2024, 2, 1)) == []


def test_carregar_nunca_levanta_com_cache_terminando_em_28_02(monkeypatch, tmp_path):
    caminho = str(tmp_path / "sgs12.csv.gz")
    cdi.gravar_cache([{"data": "02/01/2001", "valor": "0.05"}, {"data": "28/02/2024", "valor": "0.04"}], caminho)
    monkeypatch.setattr(cdi, "http_get", lambda *a, **k: None)
    s = cdi.carregar(caminho=caminho)
    assert s.attrs["fonte"] == "bcb" and len(s) == 2


def test_carregar_com_cache_completo_nao_vai_a_rede(monkeypatch, tmp_path):
    caminho = str(tmp_path / "sgs12.csv.gz")
    cdi.gravar_cache(FIXTURE, caminho)
    chamadas = []
    monkeypatch.setattr(cdi, "baixar", lambda *a, **k: chamadas.append(a) or None)
    s = cdi.carregar("2024-01-02", "2024-01-10", caminho=caminho, permitir_rede=True)
    assert not chamadas and len(s) == 5
    # so falta a frente: pede apenas ate a vespera do cache
    cdi.carregar("2023-12-01", "2024-01-10", caminho=caminho, permitir_rede=True)
    assert len(chamadas) == 1 and str(chamadas[0][1]) == "2024-01-01"


def test_gravar_cache_ignora_itens_que_nao_sao_dict(tmp_path):
    caminho = str(tmp_path / "sgs12.csv.gz")
    assert cdi.gravar_cache(["lixo", None, {"data": "02/01/2024", "valor": "0.05"}], caminho) == 1


def test_cache_bruto_gravar_e_ler(tmp_path):
    caminho = str(tmp_path / "sgs12.csv.gz")
    assert cdi.gravar_cache(FIXTURE[:3], caminho) == 3
    # segunda gravacao funde e sobrescreve datas repetidas
    assert cdi.gravar_cache(FIXTURE[3:], caminho) == 5
    s = cdi.ler_cache(caminho)
    assert len(s) == 5 and abs(s.loc["2024-01-05"] - 0.00043740) < 1e-12
    assert len(cdi.ler_cache(str(tmp_path / "nao_existe.csv.gz"))) == 0


def test_baixar_sem_rede_devolve_none(monkeypatch, tmp_path):
    monkeypatch.setattr(cdi, "http_get", lambda *a, **k: None)
    assert cdi.baixar("2024-01-01", "2024-01-31", caminho=str(tmp_path / "x.csv.gz")) is None


def test_baixar_com_rede_simulada_grava_cache(monkeypatch, tmp_path):
    class Resp:
        def json(self):
            return FIXTURE

    monkeypatch.setattr(cdi, "http_get", lambda *a, **k: Resp())
    caminho = str(tmp_path / "sgs12.csv.gz")
    s = cdi.baixar("2024-01-01", "2024-01-31", caminho=caminho)
    assert len(s) == 5 and os.path.exists(caminho)
    assert cdi.ler_cache(caminho).equals(s)


def test_carregar_usa_cache_sem_rede(monkeypatch, tmp_path):
    caminho = str(tmp_path / "sgs12.csv.gz")
    cdi.gravar_cache(FIXTURE, caminho)
    chamadas = []
    monkeypatch.setattr(cdi, "baixar", lambda *a, **k: chamadas.append(a) or None)
    s = cdi.carregar("2024-01-03", "2024-01-05", caminho=caminho, permitir_rede=False)
    assert s.attrs["fonte"] == "bcb" and len(s) == 3 and not chamadas
    # com rede permitida mas cache defasado, tenta completar (baixar falha -> segue com o cache)
    s2 = cdi.carregar(caminho=caminho, permitir_rede=True)
    assert len(chamadas) == 1 and len(s2) == 5 and s2.attrs["fonte"] == "bcb"


def test_fallback_nefin_quando_nao_ha_cache_nem_rede(monkeypatch, tmp_path):
    from quant.dados import nefin
    if nefin.pin_ultimo("fatores") is None:
        pytest.skip("sem snapshot NEFIN local")
    monkeypatch.setattr(cdi, "baixar", lambda *a, **k: None)
    s = cdi.carregar("2024-01-01", "2024-12-31", caminho=str(tmp_path / "vazio.csv.gz"))
    assert s is not None and s.attrs["fonte"] == "nefin"
    assert s.index.min().year == 2024 and s.index.max().year == 2024
    assert 0.09 < cdi.anualizar(s) < 0.13                    # CDI 2024 ~ 10,9% a.a.
    # POINT-IN-TIME: a serie do fallback carrega a data de disponibilidade do snapshot
    assert s.attrs["avail_date"] == nefin.pin_ultimo("fatores")["avail_date"]
    assert s.index.max().date() <= pd.Timestamp(s.attrs["avail_date"]).date()


def test_carregar_devolve_none_sem_nenhuma_fonte(monkeypatch, tmp_path):
    monkeypatch.setattr(cdi, "baixar", lambda *a, **k: None)
    monkeypatch.setattr(cdi, "fallback_nefin", lambda: None)
    assert cdi.carregar(caminho=str(tmp_path / "vazio.csv.gz")) is None
