"""O indice de retorno total contra o preco ajustado do terminal, mes a mes, no universo liquido inteiro (e nao so nos 15 papeis da auditoria da TIR).

Regra: retorno total nunca sobe MENOS que o preco ajustado a desdobramento e bonificacao. Se (indice_t / indice_{t-1}) / (preco_t / preco_{t-1}) < 0,95, falta evento na
tabela `eventos`. Estes testes usam o dado real (COTAHIST, `banco/eventos.parquet` e a serie mensal do terminal em `cache/out/longo/`); sem eles, pulam.

`CONHECIDOS` e a lista fechada do que sobra depois do conserto (12/10/2026), mes a mes, em dois grupos. Mes novo fora da lista REPROVA: e evento que faltou entrar.
"""
import json
import os

import pandas as pd
import pytest

from quant.dados import conferir_retorno_total as cr
from quant.dados import cotahist, eventos

AUDITORIA = os.path.join(cr.PASTA_TERMINAL, "relatorios", "tir_auditoria", "resultados.json")

# Grupo 1: o preco ajustado do Yahoo sobe 5% a 19% mais que o preco bruto no mes e NAO ha bonificacao nem desdobramento na B3 nem na CVM (FRE 17.3 e saltos do numero
# de acoes). Padrao de direito de subscricao / aumento de capital com direitos (que o Yahoo ajusta como desdobramento e o retorno total nao modela) ou de ajuste do
# proprio Yahoo; nao deu para provar qual dos dois em cada mes. 24 meses.
YAHOO_AJUSTA_SEM_EVENTO = {
    ("AMAR3", "2021-12"), ("AMBP3", "2023-10"), ("ARML3", "2026-09"), ("CSAN3", "2014-10"), ("CVCB3", "2020-07"), ("CVCB3", "2023-06"), ("EZTC3", "2015-01"),
    ("GFSA3", "2017-12"), ("GFSA3", "2019-04"), ("GFSA3", "2020-08"), ("GFSA3", "2024-03"), ("HYPE3", "2011-10"), ("IFCM3", "2022-08"), ("MRVE3", "2011-10"),
    ("MRVE3", "2018-12"), ("MULT3", "2011-07"), ("MULT3", "2015-08"), ("NATU3", "2019-05"), ("NATU3", "2026-09"), ("PCAR3", "2024-03"), ("PDGR3", "2011-10"),
    ("RENT3", "2011-07"), ("TCSA3", "2011-08"), ("TPIS3", "2017-07"),
}
# Grupo 2: a serie do Yahoo e que esta errada (parada enquanto o preco bruto andou, ou saltando 50% a 700% sem o preco bruto acompanhar: troca de codigo, erro de dado),
# mais um evento que ESTA na tabela mas cuja data-ex pelo preco caiu no mes vizinho do que o Yahoo usou (ROMI3 2022-10: bonificacao de 10% aprovada em 20/09/2022). 9 meses.
YAHOO_COM_ERRO = {
    ("AZEV4", "2021-06"), ("BRAP4", "2021-12"), ("CSNA3", "2010-04"), ("GFSA3", "2017-04"), ("GFSA3", "2022-09"), ("GGBR4", "2010-05"), ("PCAR3", "2021-03"),
    ("UGPA3", "2021-06"), ("ROMI3", "2022-10"),
}
CONHECIDOS = YAHOO_AJUSTA_SEM_EVENTO | YAHOO_COM_ERRO


@pytest.fixture(scope="module")
def dados_reais():
    if not cr.disponivel():
        pytest.skip("serie mensal do terminal (cache/out/longo) indisponivel")
    ev = eventos.carregar_eventos()
    if ev is None or not len(ev):
        pytest.skip("banco/eventos.parquet ausente")
    try:
        cot = cotahist.carregar(2005, pd.Timestamp.now().year, colunas=["data", "ticker", "codbdi", "tpmerc", "fec", "fatcot"])
    except Exception:
        pytest.skip("COTAHIST ausente")
    if cot is None or not len(cot):
        pytest.skip("COTAHIST ausente")
    cot = cot[(cot["tpmerc"].astype(str).str.strip() == "010") & (cot["codbdi"].astype(str).str.strip().str.zfill(2) == "02")]
    from quant.swing import dados
    p = dados.montar(ano_ini=2009, arq_sinais=None)
    uni = pd.DataFrame(p.uni, index=p.datas, columns=p.tickers).resample("ME").max()
    no_universo = {(t, d.strftime("%Y-%m")) for d, linha in uni.iterrows() for t in linha.index[linha.values]}
    tickers = sorted({t for t, _ in no_universo})
    rt = eventos.retorno_total_limpo(cot[cot["ticker"].isin(tickers)][["ticker", "data", "fec", "fatcot"]], ev)
    c = cr.casos(rt, tickers=tickers, eventos=ev)
    c = c[(c["mes"] >= "2010-01") & c["lado"].eq("falta evento")]
    c = c[[(t, m) in no_universo for t, m in zip(c["ticker"], c["mes"])]]
    return {"casos": c, "eventos": ev, "universo": no_universo}


def test_universo_liquido_nenhum_mes_novo_com_o_indice_abaixo_do_preco_ajustado(dados_reais):
    c = dados_reais["casos"]
    sem_explicacao = {(t, m) for t, m, e in zip(c["ticker"], c["mes"], c["explicacao"]) if e is None}
    novos = sorted(sem_explicacao - CONHECIDOS)
    assert not novos, (f"{len(novos)} mes(es) em que o indice de retorno total sobe menos de 95% do que o preco ajustado e nao ha evento registrado: {novos[:12]}. "
                       f"Falta bonificacao, desdobramento ou grupamento na tabela `eventos` (python -m quant.dados.eventos_cvm mostra o que a CVM tem).")


def test_a_lista_de_conhecidos_nao_guarda_caso_que_ja_foi_resolvido(dados_reais):
    c = dados_reais["casos"]
    ainda = {(t, m) for t, m, e in zip(c["ticker"], c["mes"], c["explicacao"]) if e is None}
    resolvidos = sorted(CONHECIDOS - ainda)
    assert not resolvidos, f"estes meses ja nao reprovam e podem sair de CONHECIDOS: {resolvidos}"


def test_os_41_casos_da_auditoria_da_tir_estao_resolvidos(dados_reais):
    if not os.path.exists(AUDITORIA):
        pytest.skip("resultados.json da auditoria ausente")
    lista = json.load(open(AUDITORIA, encoding="utf-8"))["eventos_nao_registrados"]["lista"]
    assert len(lista) == 41
    c = dados_reais["casos"]
    ainda = {(t, m) for t, m in zip(c["ticker"], c["mes"])}
    sobraram = sorted((t, d[:7]) for t, d in lista if (t, d[:7]) in ainda)
    assert not sobraram, f"da lista de 41 da auditoria ainda reprovam: {sobraram}"


@pytest.mark.parametrize("ticker,data,fator", [
    ("ITUB4", "2013-05-21", 1.10), ("ITUB4", "2014-06-06", 1.10), ("ITUB4", "2015-07-14", 1.10), ("ITUB4", "2016-10-18", 1.10),     # Itau: 4 bonificacoes de 10% que a B3 nao lista
    ("BBDC4", "2013-03-26", 1.10), ("BBDC4", "2015-03-27", 1.20), ("BBDC4", "2019-04-01", 1.20),                                       # Bradesco
    ("WEGE3", "2014-04-24", 1.30), ("WEGE3", "2015-04-01", 2.00),                                                                     # WEG: bonificacao de 30% e desdobramento 2:1
    ("CYRE3", "2026-01-02", 1.1896), ("AXIA3", "2025-12-22", 1.2628),                                                                 # a B3 traz, o leitor descartava (assetIssued x isinCode)
    ("POMO4", "2024-03-08", 1.20), ("KLBN11", "2024-05-07", 1.10),                                                                    # depois de 2023 o FRE nao tem mais o item 17.3: salto do numero de acoes
])
def test_bonificacoes_do_diagnostico_estao_na_tabela(dados_reais, ticker, data, fator):
    ev = dados_reais["eventos"]
    q = ev[(ev["ticker"] == ticker) & ev["tipo"].isin(["BONIFICACAO", "DESDOBRAMENTO", "GRUPAMENTO"])]
    perto = q[(pd.to_datetime(q["data_ex"]) - pd.Timestamp(data)).abs() <= pd.Timedelta(days=3)]
    assert len(perto) and abs(perto["fator"].iloc[0] / fator - 1) < 0.01, f"{ticker}: evento de {fator} perto de {data} nao esta na tabela: {perto[['data_ex', 'fator', 'fonte']].values.tolist()}"
