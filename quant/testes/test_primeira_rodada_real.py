"""
O que a primeira rodada com dado real (08/10/2026) obrigou a consertar, um teste por achado.
Cada caso tem a conta feita a mao no comentario: se a regra mudar, o numero esperado muda junto.
"""
import io
import zipfile
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from quant.comum import agora_brt
from quant.dados import calendario, capital_social as cs, contas_cvm, eventos
from quant.execucao import paper, robo_vivo


# ── retorno total limpo ──────────────────────────────────────
def _precos(linhas):
    return pd.DataFrame(linhas, columns=["ticker", "data", "fec", "fatcot"])


def test_salto_sem_evento_vira_nan_e_entra_na_lista():
    # 10 -> 10,10 (+1%) -> 101 (+900%, grupamento que nenhuma fonte trouxe) -> 102,01 (+1%)
    p = _precos([("AAAA3", "2024-01-02", 10.0, 1), ("AAAA3", "2024-01-03", 10.10, 1),
                 ("AAAA3", "2024-01-04", 101.0, 1), ("AAAA3", "2024-01-05", 102.01, 1)])
    rt = eventos.retorno_total_limpo(p, eventos._tabela_vazia())
    r = rt["ret_total"].tolist()
    assert np.isnan(r[0]) and r[1] == pytest.approx(0.01) and np.isnan(r[2]) and r[3] == pytest.approx(0.01)
    lim = rt.attrs["limpeza"]
    assert lim["saltos"] == 1 and lim["lista_saltos"][0]["ticker"] == "AAAA3"
    # o indice de retorno total pula o salto: 1 x 1,01 x 1 x 1,01
    assert rt["fator_acum"].iloc[-1] == pytest.approx(1.01 * 1.01)


def test_queda_de_metade_sem_evento_tambem_sai():
    p = _precos([("BBBB3", "2024-01-02", 40.0, 1), ("BBBB3", "2024-01-03", 19.0, 1)])   # -52,5%
    rt = eventos.retorno_total_limpo(p, eventos._tabela_vazia())
    assert np.isnan(rt["ret_total"].iloc[1]) and rt.attrs["limpeza"]["saltos"] == 1


def test_ticker_reaproveitado_recomeca_a_serie():
    # mesmo codigo, 5 anos de buraco: o primeiro retorno da volta compara dois papeis e nao existe
    p = _precos([("NATU3", "2019-12-16", 35.0, 1), ("NATU3", "2019-12-17", 36.0, 1),
                 ("NATU3", "2025-07-02", 10.19, 1), ("NATU3", "2025-07-03", 10.29, 1)])
    rt = eventos.retorno_total_limpo(p, eventos._tabela_vazia())
    r = rt["ret_total"].tolist()
    assert np.isnan(r[2]) and r[3] == pytest.approx(10.29 / 10.19 - 1)
    assert rt.attrs["limpeza"]["buracos"] == 1 and rt.attrs["limpeza"]["saltos"] == 0


def test_lote_de_mil_usa_preco_por_acao():
    # cotado por lote de mil (fatcot 1000) a 50,00 = 0,05 por acao; no dia do grupamento de 1000:1
    # passa a cotar por acao a 51,00. Com o evento (fator 0,001): (51 x 0,001) / 0,05 - 1 = +2%.
    p = _precos([("CCCC4", "2007-01-02", 50.0, 1000), ("CCCC4", "2007-01-03", 51.0, 1)])
    ev = eventos._montar([{"ticker": "CCCC4", "tipo": "GRUPAMENTO", "data_com": pd.Timestamp("2007-01-02"),
                           "data_ex": pd.Timestamp("2007-01-03"), "valor": float("nan"), "fator": 0.001,
                           "data_aprov": pd.NaT, "fonte": "b3_suplemento", "carimbo": "", "obs": ""}])
    rt = eventos.retorno_total_limpo(p, ev)
    assert rt["ret_total"].iloc[1] == pytest.approx(0.02)
    assert rt.attrs["limpeza"]["saltos"] == 0


def test_calendario_aceita_data_fora_da_cobertura():
    # provento de 1994 e data-sentinela da B3: nao levanta, cai na regra do dia de semana
    assert calendario.eh_pregao("1900-01-02") in (True, False)
    assert calendario.eh_pregao("9999-12-31") in (True, False)


# ── PL pela descricao (plano de contas de banco) ─────────────
def _bpp(linhas):
    return pd.DataFrame([{"demo": "BPP", "conta": c, "descricao": d, "valor_reais": v} for c, d, v in linhas])


def test_pl_de_banco_vem_da_conta_com_o_nome_certo():
    # Banco do Brasil, 2T26: 2.03 e "Provisoes" (R$ 40,4 bi); o PL esta em 2.07 (R$ 190,8 bi)
    banco = _bpp([("2", "Passivo Total", 2588.1e9), ("2.03", "Provisões", 40.4e9),
                  ("2.07", "Patrimônio Líquido Consolidado", 190.8e9),
                  ("2.07.01", "Patrimônio Líquido Atribuído ao Controlador", 187.0e9)])
    assert contas_cvm.extrair(banco, "pl") == pytest.approx(190.8e9)


def test_pl_de_empresa_comum_continua_no_2_03():
    emp = _bpp([("2.01", "Passivo Circulante", 181.4e9), ("2.02", "Passivo Não Circulante", 615.8e9),
                ("2.03", "Patrimônio Líquido Consolidado", 481.9e9)])
    assert contas_cvm.extrair(emp, "pl") == pytest.approx(481.9e9)
    # sem descricao reconhecivel, cai no codigo
    sem_nome = _bpp([("2.03", "PL", 7.0e9)])
    assert contas_cvm.extrair(sem_nome, "pl") == pytest.approx(7.0e9)


# ── numero de acoes: composicao do capital e escala ──────────
def _zip_itr(ano=2026):
    geral = ("CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;CATEG_DOC;ID_DOC;DT_RECEB;LINK_DOC\n"
             "00.000.000/0001-91;2026-06-30;1;BCO BRASIL S.A.;1023;ITR;1;2026-08-13;x\n"
             "33.592.510/0001-54;2026-06-30;1;VALE S.A.;4170;ITR;2;2026-07-30;x\n")
    comp = ("CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;QT_ACAO_ORDIN_CAP_INTEGR;QT_ACAO_PREF_CAP_INTEGR;"
            "QT_ACAO_TOTAL_CAP_INTEGR;QT_ACAO_ORDIN_TESOURO;QT_ACAO_PREF_TESOURO;QT_ACAO_TOTAL_TESOURO\n"
            "00.000.000/0001-91;2026-06-30;1;BCO BRASIL S.A.;5730834040;0;5730834040;22370399;0;22370399\n"
            "33.592.510/0001-54;2026-06-30;1;VALE S.A.;4255763;0;4255763;183397;0;183397\n")
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w") as z:
        z.writestr(f"itr_cia_aberta_{ano}.csv", geral.encode("latin-1"))
        z.writestr(f"itr_cia_aberta_composicao_capital_{ano}.csv", comp.encode("latin-1"))
    return mem.getvalue()


def test_composicao_do_capital_sai_ex_tesouraria_com_data_de_entrega():
    df = cs.ler_composicao(_zip_itr(), "ITR", 2026)
    bb = df[df["cd_cvm"] == 1023].iloc[0]
    assert bb["acoes_total"] == 5730834040 - 22370399                  # ex-tesouraria
    assert bb["disponivel_em"] == pd.Timestamp("2026-08-13")           # DT_RECEB, nao data + 150 dias
    assert bb["fonte"] == "itr"


def test_escala_unidades_ou_milhares_por_companhia():
    cap = cs.ler_composicao(_zip_itr(), "ITR", 2026)
    # BB: lucro 15,4 bi e LPA 2,70 -> 5,70 bi de acoes: razao 1,0 contra o informado (unidades)
    # Vale: lucro 8,69 bi e LPA 2,13 -> 4,08 bi de acoes: razao ~1.002 contra 4.072.366 (milhares)
    painel = pd.DataFrame([
        {"data": pd.Timestamp("2026-10-07"), "cd_cvm": 1023, "lucro_liquido": 15.4e9, "lpa": 2.70, "pl": 190.8e9},
        {"data": pd.Timestamp("2026-10-07"), "cd_cvm": 4170, "lucro_liquido": 8.69e9, "lpa": 2.13, "pl": 201.5e9}])
    r = cs.resolver_escala(cap, painel=painel)
    bb = r[r["cd_cvm"] == 1023].iloc[0]
    vale = r[r["cd_cvm"] == 4170].iloc[0]
    assert bb["acoes_total"] == pytest.approx(5708463641.0) and bb["fonte"] == "itr:lpa"
    assert vale["acoes_total"] == pytest.approx((4255763 - 183397) * 1000.0) and vale["fonte"] == "itr:lpa"
    assert r.attrs["escala"]["em_milhares"] == 1


def test_escala_pelo_preco_quando_nao_ha_lpa():
    cap = cs.ler_composicao(_zip_itr(), "ITR", 2026)
    painel = pd.DataFrame([{"data": pd.Timestamp("2026-10-07"), "cd_cvm": 4170,
                            "lucro_liquido": float("nan"), "lpa": float("nan"), "pl": 201.5e9}])
    precos = pd.DataFrame([{"data": pd.Timestamp("2026-10-07"), "cd_cvm": 4170, "preco": 68.75}])
    r = cs.resolver_escala(cap, painel=painel, precos=precos)
    vale = r[r["cd_cvm"] == 4170].iloc[0]
    # em unidades o P/VP seria 4,07 mi x 68,75 / 201,5 bi = 0,0014; em milhares, 1,39: so milhares cabe
    assert vale["fonte"] == "itr:pvp" and vale["acoes_total"] == pytest.approx(4072366000.0)
    # sem evidencia nenhuma fica como informado e marcado: nao entra no valor de mercado
    assert r[r["cd_cvm"] == 1023].iloc[0]["fonte"] == "itr:?"


# ── reprecificacao e fita derivada ───────────────────────────
def test_reprecificacao_segue_os_degraus_da_boleta():
    boleta = {"emitida": True, "data": "2026-10-08", "id": "20261008", "hora_envio": "10:20",
              "ordens": [{"ticker": "ALPA4", "lado": "C", "qtd": 200, "preco_limite": 15.26,
                          "limite_reprecificado": [{"hora": "12:20", "preco": 15.29}]}]}
    fita = pd.DataFrame([{"ticker": "ALPA4", "hora": "10:30:00", "preco": 15.28, "quantidade": 50000},
                         {"ticker": "ALPA4", "hora": "12:21:00", "preco": 15.28, "quantidade": 50000}])
    # sem reprecificar, 15,28 esta acima do limite de 15,26 o dia inteiro: nada executa
    assert len(paper.simular(boleta, fita)) == 0
    # com reprecificacao, so o negocio das 12:21 (limite 15,29) serve; teto de 1% de 100.000 = 1.000 >= 200
    f = paper.simular(boleta, fita, reprecificar=True)
    assert int(f["qtd"].iloc[0]) == 200 and f["preco"].iloc[0] == pytest.approx(15.28)
    assert str(f["hora"].iloc[0]) == "12:21:00"


def _retrato(hh, mm, ss, ticker, preco, volume, medio=None):
    t = datetime(2026, 10, 8, hh, mm, ss, tzinfo=agora_brt().tzinfo)
    return {"q": {ticker: [preco, 0, None, None, None, volume, preco, t.timestamp(), None, None, None, 10, None,
                           medio if medio is not None else preco]}}, t


def test_fita_derivada_do_volume_acumulado():
    L = robo_vivo.Leitor(["PETR4"], adtv={"PETR4": 2.2e9})
    assert L.negocios(*_retrato(9, 55, 0, "PETR4", 54.33, None)) == []          # antes da abertura, sem volume
    assert L.negocios(*_retrato(9, 58, 0, "PETR4", 54.33, 76397)) == []         # resto de ontem: nao e negocio
    # 10:05: leilao de abertura e primeiros minutos chegam como UM negocio, contado do zero (o volume
    # de ontem nao serviu de base). E de antes do envio da boleta (10:20), entao nao casa ordem nenhuma.
    n = L.negocios(*_retrato(10, 5, 0, "PETR4", 54.20, 100000, 54.20))
    assert len(n) == 1 and n[0]["quantidade"] == 100000 and n[0]["preco"] == pytest.approx(54.20)
    # 5.000 acoes a 54,10 de media: medio do dia = (100.000 x 54,20 + 5.000 x 54,10) / 105.000
    medio = (100000 * 54.20 + 5000 * 54.10) / 105000
    n = L.negocios(*_retrato(10, 21, 0, "PETR4", 54.12, 105000, round(medio, 6)))
    assert len(n) == 1 and n[0]["quantidade"] == 5000 and n[0]["preco"] == pytest.approx(54.10, abs=0.005)


def test_volume_da_vespera_que_reaparece_e_descartado():
    L = robo_vivo.Leitor(["VTRU3"], adtv={"VTRU3": 13.8e6})
    # 09:41, motor reiniciado: as 831.100 acoes de ontem aparecem com a hora de agora. Nada entra.
    assert L.negocios(*_retrato(9, 41, 25, "VTRU3", 17.85, 831100)) == []
    assert len(L.negocios(*_retrato(10, 5, 0, "VTRU3", 17.80, 5000))) == 1      # abertura, contada do zero
    assert len(L.negocios(*_retrato(10, 21, 0, "VTRU3", 17.82, 5300))) == 1
    # 2 segundos depois o volume vira o de ontem (831.100): R$ 14,7 mi de uma vez, mais que o giro do dia
    assert L.negocios(*_retrato(10, 21, 2, "VTRU3", 17.82, 831100)) == [] and L.descartes == 1
    assert L.negocios(*_retrato(10, 21, 4, "VTRU3", 17.82, 5400)) == []         # volta: nova base, sem negocio
    assert len(L.negocios(*_retrato(10, 21, 6, "VTRU3", 17.83, 5600))) == 1


def test_fases_do_pregao():
    tz = agora_brt().tzinfo
    f = lambda h, m: robo_vivo.fase_do_relogio(datetime(2026, 10, 8, h, m, tzinfo=tz), "10:20")   # noqa: E731
    assert [f(9, 50), f(10, 5), f(10, 20), f(16, 59), f(17, 0)] == [
        "aguardando_abertura", "aguardando_envio", "operando", "operando", "encerrado"]
