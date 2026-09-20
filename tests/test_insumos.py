"""O material da Leitura da Mesa tem de ser calculado no runner e sobreviver a
serie curta: ativo novo nao pode virar numero errado."""

from __future__ import annotations

from datetime import date

import pandas as pd

from livro import indicadores as ind
from livro import insumos


def serie(valores, fim="2026-09-18"):
    datas = pd.bdate_range(end=fim, periods=len(valores))
    return ind.para_df([[d.date().isoformat(), v, v, v, v, v, 100] for d, v in zip(datas, valores)])


def test_amplitude_conta_acima_da_mm200_e_acha_quem_esta_na_beira(universo):
    subindo = [100.0 + i * 0.2 for i in range(260)]          # bem acima da MM200
    caindo = [150.0 - i * 0.2 for i in range(260)]           # bem abaixo
    series = {"VALE3": serie(subindo), "PETR4": serie(subindo), "BBDC4": serie(caindo)}
    a = insumos.amplitude(universo, series, date(2026, 9, 18))
    assert a["acima"] == 2 and a["total"] == 3
    assert 0.66 < a["pct"] < 0.67
    assert "BBDC4" in a["abaixo_ids"]


def test_amplitude_ignora_serie_curta_em_vez_de_chutar(universo):
    assert insumos.amplitude(universo, {"VALE3": serie([10.0] * 50)}, date(2026, 9, 18)) == {}


def test_extremos_so_com_livro_suficiente(universo):
    j = {"VALE3": {"1m": 0.10}, "PETR4": {"1m": -0.05}}
    assert insumos.extremos(universo, j) == {}                # 2 ativos nao fazem ranking
    j.update({"ITUB4": {"1m": 0.02}, "BBDC4": {"1m": -0.20}, "KLBN4": {"1m": 0.30}})
    e = insumos.extremos(universo, j, chaves=("1m",), n=2)
    assert [i[0] for i in e["1m"]["melhores"]] == ["KLBN4", "VALE3"]
    assert [i[0] for i in e["1m"]["piores"]] == ["BBDC4", "PETR4"]


def test_bloco_usa_mediana_e_nao_media(universo):
    j = {a.id: {"dia": 0.001} for a in universo.por_bloco("br")}
    alvo = universo.por_bloco("br")[0].id
    j[alvo]["dia"] = 0.50                                     # um ativo disparou sozinho
    linha = next(b for b in insumos.por_bloco(universo, j) if b["id"] == "br")
    assert abs(linha["dia"] - 0.001) < 1e-9                   # mediana nao se move


def test_pares_descolados_devolve_z_e_ignora_par_sem_serie(universo):
    a = [100.0 * (1.001 ** i) for i in range(120)]
    b = [100.0] * 110 + [100.0 * (0.99 ** i) for i in range(10)]
    out = insumos.pares_descolados(universo, {"ITUB4": serie(a), "BBDC4": serie(b)}, date(2026, 9, 18))
    assert out and out[0]["a"] == "ITUB4" and out[0]["b"] == "BBDC4"
    assert abs(out[0]["z"]) >= 1.5
    assert insumos.pares_descolados(universo, {"ITUB4": serie(a)}, date(2026, 9, 18)) == []


def test_retorno_em_nao_inventa_janela_que_o_historico_nao_alcanca():
    curta = serie([100.0 + i for i in range(60)])
    assert ind.retorno_em(curta, 1826) is None                # 5 anos sem 5 anos de dado
    media = serie([100.0 + i * 0.01 for i in range(900)])   # ~3,5 anos corridos
    assert ind.retorno_em(media, 1826) is None                # nao cobre 5 anos
    assert ind.retorno_em(media, 365) is not None
    longa = serie([100.0 + i * 0.01 for i in range(1600)])  # ~6,1 anos corridos
    assert ind.retorno_em(longa, 1826) is not None
