import pytest

from quant.dados import nefin


@pytest.fixture(scope="module")
def fatores():
    pin = nefin.pin_ultimo("fatores") or nefin.baixar("fatores")
    if pin is None:
        pytest.skip("sem acesso ao raw.githubusercontent.com nesta maquina")
    return nefin.carregar_fatores(pin)


def test_fatores_carregam_e_estao_em_decimal_diario(fatores):
    assert list(fatores.columns) == nefin.FATORES
    assert str(fatores.index.min().date()) == "2001-01-02"
    assert fatores.index.max().year >= 2026
    assert fatores["Risk_Free"].between(0, 0.002).all()          # ~0,05%/dia
    assert fatores.attrs["pin"]["sha256"]


def test_momentum_e_o_fator_forte_como_no_corpus(fatores):
    est = nefin.estatisticas(fatores)
    wml, hml, smb = est["WML"], est["HML"], est["SMB"]
    assert 0.10 < wml["media_aa"] < 0.20 and wml["t"] > 3.5
    assert 0.03 < hml["media_aa"] < 0.14
    assert abs(smb["media_aa"]) < 0.05


def test_mensal_tem_uma_linha_por_mes(fatores):
    m = nefin.mensal(fatores)
    assert len(m) >= 300 and m["WML"].abs().max() < 0.5
