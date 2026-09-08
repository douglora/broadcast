"""
Testes da boleta do dia (M13).

O teste que importa aqui e um so: com modo seguro ativo NAO sai boleta. Todos os outros
(mid, fatiamento, caixa, texto) protegem a boleta que sai; esse protege o usuario da
boleta que nao deveria ter saido. Uma folha montada sobre dado velho seria executada com a
mesma confianca de uma folha correta - ele nao tem como distinguir olhando.

Os numeros esperados estao escritos como a aritmetica que os produz (0.01 * 1_000_000 / 10)
e nao como resultado pronto: mudar uma constante do modulo tem de falhar mostrando qual
premissa mudou.
"""
import json
import os

import numpy as np
import pandas as pd

from quant.dados import calendario
from quant.execucao import boleta as bo

HOJE = calendario.ultimo_pregao_ate("2026-09-08")
COLUNAS = ["ticker", "lado", "qtd", "preco", "valor", "custo", "motivo", "fracionario"]


def _ordens(linhas):
    """DataFrame no formato de carteira.ordens_incrementais."""
    return pd.DataFrame(linhas, columns=COLUNAS)


def _uma_compra(ticker="ABCD3", qtd=200, preco=20.0, motivo="entrada", frac=False):
    return {"ticker": ticker, "lado": "C", "qtd": qtd, "preco": preco,
            "valor": qtd * preco, "custo": 0.0, "motivo": motivo, "fracionario": frac}


def _uma_venda(ticker="XPTO4", qtd=100, preco=50.0, motivo="saida_rank", frac=True):
    return {"ticker": ticker, "lado": "V", "qtd": qtd, "preco": preco,
            "valor": qtd * preco, "custo": 0.0, "motivo": motivo, "fracionario": frac}


def _frescor_bom(hoje=HOJE):
    return bo.frescor(hoje, cotahist=hoje, bdi=hoje,
                      sinais=calendario.pregoes_atras(hoje, 5), cdi=hoje)


def _frescor_velho(hoje=HOJE, atraso=3):
    return bo.frescor(hoje, cotahist=calendario.pregoes_atras(hoje, atraso), bdi=hoje,
                      sinais=calendario.pregoes_atras(hoje, 5), cdi=hoje)


# ─────────────────────────────────────────────────────────────
# Preco limite
# ─────────────────────────────────────────────────────────────
def test_preco_limite_e_o_mid_do_book():
    p, origem = bo.preco_limite(20.00, 20.10, 19.80, "C")
    assert origem == "mid" and abs(p - (20.00 + 20.10) / 2) < 1e-9
    p, origem = bo.preco_limite(20.00, 20.10, 19.80, "V")
    assert origem == "mid" and abs(p - (20.00 + 20.10) / 2) < 1e-9


def test_book_zerado_ou_ausente_cai_para_o_fechamento_e_marca_a_queda():
    # zerado: e o caso comum justamente nos iliquidos que a estrategia carrega
    p, origem = bo.preco_limite(0.0, 0.0, 19.80, "C")
    assert origem == "fechamento" and abs(p - 19.80) < 1e-9
    # so uma ponta do book nao faz mid
    p, origem = bo.preco_limite(None, 20.10, 19.80, "V")
    assert origem == "fechamento" and abs(p - 19.80) < 1e-9
    # book cruzado e dado podre, nao preco
    p, origem = bo.preco_limite(20.20, 20.10, 19.80, "C")
    assert origem == "fechamento"
    # mid a mais de MAX_DESVIO_MID do fechamento e book de um lote so
    p, origem = bo.preco_limite(1.00, 50.00, 2.00, "C")
    assert origem == "fechamento" and abs(p - 2.00) < 1e-9
    # sem book e sem fechamento nao ha preco - e a ordem nao entra na boleta
    p, origem = bo.preco_limite(float("nan"), float("nan"), None, "C")
    assert origem == "sem_preco" and not np.isfinite(p)


def test_arredondamento_do_limite_e_sempre_a_favor_do_caixa():
    # mid de 10,005: a compra nao paga o meio centavo, a venda nao o entrega
    p, _ = bo.preco_limite(10.00, 10.01, 10.00, "C")
    assert abs(p - 10.00) < 1e-9
    p, _ = bo.preco_limite(10.00, 10.01, 10.00, "V")
    assert abs(p - 10.01) < 1e-9


def test_reprecificacao_anda_na_direcao_que_executa():
    assert abs(bo.reprecificar(20.00, "C", 1) - 20.04) < 1e-9      # +0,2%
    assert abs(bo.reprecificar(20.00, "V", 1) - 19.96) < 1e-9      # -0,2%
    assert bo.reprecificar(20.00, "C", 2) > bo.reprecificar(20.00, "C", 1)
    # a agenda para antes do leilao de fechamento
    horarios = [h for h, _ in bo.agenda_reprecificacao()]
    assert horarios and all(h < bo.INICIO_LEILAO for h in horarios)


# ─────────────────────────────────────────────────────────────
# Fatiamento
# ─────────────────────────────────────────────────────────────
def test_fatiar_soma_a_quantidade_original_e_respeita_a_participacao():
    adtv, preco = 1_000_000.0, 10.0
    teto_acoes = bo.MAX_PARTICIPACAO * adtv / preco            # 1.000 acoes por pregao
    fatias = bo.fatiar(2_500, adtv, preco)
    assert sum(fatias) == 2_500
    assert len(fatias) == 3                                    # ceil(2500/1000)
    assert max(fatias) <= teto_acoes + 1e-9
    # com lote, as fatias saem multiplas de 100 e a soma continua exata
    fatias = bo.fatiar(2_500, adtv, preco, lote=bo.LOTE)
    assert sum(fatias) == 2_500 and all(f % bo.LOTE == 0 for f in fatias)
    assert max(fatias) <= teto_acoes + 1e-9


def test_ordem_grande_demais_para_o_teto_para_em_fatias_max():
    # 10.000 acoes com teto de 1.000 pediria 10 pregoes; o plano manda parar em 3
    fatias = bo.fatiar(10_000, 1_000_000.0, 10.0)
    assert len(fatias) == bo.FATIAS_MAX and sum(fatias) == 10_000


def test_ordem_pequena_nao_e_fatiada():
    # 100 acoes a R$ 20 sao R$ 2.000 contra um teto de 1% de R$ 50 mi
    assert bo.fatiar(100, 50e6, 20.0) == [100]
    assert bo.fatiar(0, 50e6, 20.0) == []
    assert bo.fatiar(-5, 50e6, 20.0) == []


def test_liquidez_desconhecida_fatia_no_maximo():
    # nao saber a liquidez tem de doer, como em quant/custos.py
    assert len(bo.fatiar(300, float("nan"), 20.0)) == bo.FATIAS_MAX
    assert len(bo.fatiar(300, 0.0, 20.0)) == bo.FATIAS_MAX
    assert sum(bo.fatiar(300, None, 20.0)) == 300


def test_fatiar_nunca_perde_nem_inventa_acao():
    rng = np.random.default_rng(20260908)
    for _ in range(300):
        qtd = int(rng.integers(1, 100_000))
        adtv = float(rng.choice([0.0, 1e5, 5e6, 50e6, float("nan")]))
        preco = float(rng.uniform(0.5, 120.0))
        fatias = bo.fatiar(qtd, adtv, preco)
        assert sum(fatias) == qtd
        assert 1 <= len(fatias) <= bo.FATIAS_MAX
        assert all(f >= 0 for f in fatias)


# ─────────────────────────────────────────────────────────────
# Frescor e modo seguro
# ─────────────────────────────────────────────────────────────
def test_frescor_conta_pregoes_e_nao_dias_corridos():
    # numa segunda-feira o COTAHIST de sexta tem 1 pregao de atraso, nao 3 dias: bloquear
    # por causa do fim de semana seria bloquear toda segunda-feira
    segunda = next(d for d in calendario.pregoes("2026-09-08", "2026-10-31")
                   if (d - calendario.pregao_anterior(d)).days >= 3)
    fr = bo.frescor(segunda, cotahist=calendario.pregao_anterior(segunda), bdi=segunda,
                    sinais=segunda, cdi=segunda)
    assert fr["cotahist"]["dias_atras"] == 1
    assert fr["cotahist"]["ok"] is True
    assert set(fr) == set(bo.FONTES)
    assert fr["cotahist"]["data"] == calendario.pregao_anterior(segunda).isoformat()


def test_frescor_de_fonte_ausente_nao_e_silencio():
    fr = bo.frescor(HOJE, cotahist=None, bdi=HOJE, sinais=HOJE, cdi=HOJE)
    assert fr["cotahist"] == {"data": None, "dias_atras": None, "ok": False}


def test_modo_seguro_bloqueia_com_cotahist_atrasado():
    fr = _frescor_velho(atraso=3)
    assert fr["cotahist"]["dias_atras"] == 3 and fr["cotahist"]["ok"] is False
    ativo, motivos = bo.modo_seguro(fr, gate_passou=True)
    assert ativo is True
    assert any("COTAHIST" in m for m in motivos)


def test_modo_seguro_bloqueia_com_fonte_obrigatoria_ausente():
    fr = bo.frescor(HOJE, cotahist=HOJE, bdi=None, sinais=HOJE, cdi=HOJE)
    ativo, motivos = bo.modo_seguro(fr, gate_passou=True)
    assert ativo is True and any("BDI" in m for m in motivos)


def test_modo_seguro_bloqueia_com_gate_desconhecido():
    ativo, motivos = bo.modo_seguro(_frescor_bom(), gate_passou=None)
    assert ativo is True
    assert any("gate" in m for m in motivos)
    # e tambem quando o gate reprovou
    ativo, motivos = bo.modo_seguro(_frescor_bom(), gate_passou=False)
    assert ativo is True and any("gate" in m for m in motivos)


def test_modo_seguro_libera_com_tudo_fresco_e_gate_aprovado():
    ativo, motivos = bo.modo_seguro(_frescor_bom(), gate_passou=True)
    assert ativo is False and motivos == []
    # o CDI atrasado NAO bloqueia: ele so alimenta o comparativo do relatorio
    fr = bo.frescor(HOJE, cotahist=HOJE, bdi=HOJE, sinais=HOJE, cdi=None)
    ativo, _ = bo.modo_seguro(fr, gate_passou=True)
    assert ativo is False


# ─────────────────────────────────────────────────────────────
# Geracao: o teste central e os cortes
# ─────────────────────────────────────────────────────────────
def test_com_modo_seguro_ativo_a_boleta_sai_sem_uma_ordem_sequer():
    ordens = _ordens([_uma_compra(), _uma_venda()])
    precos, adtv = {"ABCD3": 20.0, "XPTO4": 50.0}, {"ABCD3": 50e6, "XPTO4": 50e6}
    b = bo.gerar(ordens, precos, adtv, HOJE, frescor_dados=_frescor_velho(),
                 gate_passou=True, caixa_disponivel=1_000_000.0)
    assert b["emitida"] is False
    assert b["ordens"] == []                  # nao existe boleta parcial
    assert b["custo_total"] == 0.0
    assert any("COTAHIST" in m for m in b["motivo_bloqueio"])
    # gate desconhecido bloqueia do mesmo jeito, com todo o resto fresco
    b2 = bo.gerar(ordens, precos, adtv, HOJE, frescor_dados=_frescor_bom(),
                  gate_passou=None, caixa_disponivel=1_000_000.0)
    assert b2["emitida"] is False and b2["ordens"] == []
    # e o texto nao cita ordem nenhuma
    texto = bo.para_texto(b2)
    assert "ABCD3" not in texto and "XPTO4" not in texto
    assert "MODO SEGURO" in texto


def test_boleta_liberada_traz_as_ordens_no_formato_do_painel():
    ordens = _ordens([_uma_compra(), _uma_venda()])
    b = bo.gerar(ordens, {"ABCD3": 20.0, "XPTO4": 50.0}, {"ABCD3": 50e6, "XPTO4": 50e6},
                 HOJE, frescor_dados=_frescor_bom(), gate_passou=True,
                 book={"ABCD3": {"bid": 20.00, "ask": 20.10}}, caixa_disponivel=1_000_000.0)
    assert b["emitida"] is True and b["motivo_bloqueio"] == []
    assert b["data"] == HOJE.isoformat() and b["id"] == HOJE.strftime("%Y%m%d")
    assert len(b["ordens"]) == 2
    for o in b["ordens"]:
        assert set(bo.CAMPOS_ORDEM) <= set(o)
        assert o["validade"] == bo.VALIDADE
        assert isinstance(o["qtd"], int) and o["qtd"] > 0
    compra = next(o for o in b["ordens"] if o["ticker"] == "ABCD3")
    assert compra["origem_preco"] == "mid" and abs(compra["preco_limite"] - 20.05) < 1e-9
    venda = next(o for o in b["ordens"] if o["ticker"] == "XPTO4")
    assert venda["origem_preco"] == "fechamento"          # sem book, cai para o fechamento
    assert b["custo_total"] > 0.0
    # leilao de fechamento so acima de ADTV_LEILAO
    assert venda["leilao"] is True
    b_ilq = bo.gerar(_ordens([_uma_compra()]), {"ABCD3": 20.0}, {"ABCD3": 1e6}, HOJE,
                     frescor_dados=_frescor_bom(), gate_passou=True)
    assert b_ilq["ordens"][0]["leilao"] is False and b_ilq["ordens"][0]["iliquido"] is True


def test_compra_alem_do_caixa_disponivel_e_cortada_e_o_motivo_aparece():
    ordens = _ordens([_uma_compra("PEQU3", qtd=200, preco=20.0),      # R$ 4.000
                      _uma_compra("GRAN3", qtd=400, preco=20.0),      # R$ 8.000
                      _uma_venda("VEND3", qtd=100, preco=50.0)])
    precos = {"PEQU3": 20.0, "GRAN3": 20.0, "VEND3": 50.0}
    adtv = {t: 50e6 for t in precos}
    b = bo.gerar(ordens, precos, adtv, HOJE, frescor_dados=_frescor_bom(),
                 gate_passou=True, caixa_disponivel=5_000.0)
    tickers = [o["ticker"] for o in b["ordens"]]
    assert "PEQU3" in tickers and "GRAN3" not in tickers
    assert "VEND3" in tickers                     # venda nao depende de caixa
    assert any("GRAN3" in m for m in b["motivo_bloqueio"])
    assert b["emitida"] is True                   # corte de caixa nao bloqueia a boleta
    assert b["caixa"]["usado"] <= 5_000.0 + 1e-9
    # sem caixa informado nada e cortado, mas o aviso e explicito
    b2 = bo.gerar(ordens, precos, adtv, HOJE, frescor_dados=_frescor_bom(),
                  gate_passou=True, caixa_disponivel=None)
    assert len(b2["ordens"]) == 3
    assert any("caixa" in a for a in b2["avisos"])


def test_ordem_sem_preco_de_referencia_fica_de_fora_com_motivo():
    b = bo.gerar(_ordens([_uma_compra("SEMP3", preco=float("nan"))]), {}, {}, HOJE,
                 frescor_dados=_frescor_bom(), gate_passou=True, caixa_disponivel=1e6)
    assert b["ordens"] == []
    assert any("SEMP3" in m for m in b["motivo_bloqueio"])
    assert b["emitida"] is True


def test_boleta_vazia_nao_quebra():
    b = bo.gerar(_ordens([]), {}, {}, HOJE, frescor_dados=_frescor_bom(),
                 gate_passou=True, caixa_disponivel=10_000.0)
    assert b["emitida"] is True and b["ordens"] == [] and b["custo_total"] == 0.0
    assert isinstance(bo.para_texto(b), str) and bo.para_texto(b)
    # tudo ausente tambem nao levanta (e, sem frescor, bloqueia)
    vazia = bo.gerar(None, None, None, None)
    assert vazia["ordens"] == [] and vazia["emitida"] is False


def test_boleta_e_json_nativo_sem_nan():
    # o painel.json nao aceita NaN: jsonify produz JSON invalido e o front quebra no r.json()
    b = bo.gerar(_ordens([_uma_compra(), _uma_venda("SEMA4", preco=30.0)]),
                 {"ABCD3": 20.0, "SEMA4": 30.0}, {"ABCD3": 50e6}, HOJE,
                 frescor_dados=_frescor_bom(), gate_passou=True, caixa_disponivel=None,
                 hedge={"contratos": 1, "vencimento": "2026-10-14", "motivo": "roll"})
    texto = json.dumps(b, allow_nan=False)        # levanta se houver NaN ou Infinity
    assert "NaN" not in texto
    assert json.loads(texto)["id"] == b["id"]


# ─────────────────────────────────────────────────────────────
# Texto e disco
# ─────────────────────────────────────────────────────────────
def test_para_texto_cita_ticker_lado_quantidade_e_preco_de_cada_ordem():
    ordens = _ordens([_uma_compra("ABCD3", qtd=300, preco=20.0),
                      _uma_venda("XPTO4", qtd=100, preco=50.0)])
    b = bo.gerar(ordens, {"ABCD3": 20.0, "XPTO4": 50.0}, {"ABCD3": 50e6, "XPTO4": 50e6},
                 HOJE, frescor_dados=_frescor_bom(), gate_passou=True,
                 caixa_disponivel=1_000_000.0)
    texto = bo.para_texto(b)
    assert len(b["ordens"]) == 2
    for o in b["ordens"]:
        assert o["ticker"] in texto
        assert str(o["qtd"]) in texto
        assert ("COMPRA" if o["lado"] == "C" else "VENDA") in texto
        assert f"{o['preco_limite']:.2f}".replace(".", ",") in texto
    assert bo.HORA_ENVIO in texto                  # a hora de envio e regra, nao decoracao


def test_grava_e_le_o_json_de_volta(tmp_path):
    b = bo.gerar(_ordens([_uma_compra()]), {"ABCD3": 20.0}, {"ABCD3": 50e6}, HOJE,
                 frescor_dados=_frescor_bom(), gate_passou=True, caixa_disponivel=1e6)
    alvo = bo.gravar(b, dir_saida=str(tmp_path))
    assert os.path.exists(alvo)
    assert os.path.basename(alvo) == f"boletas_{HOJE:%Y%m%d}.json"
    lido = bo.carregar(HOJE, dir_saida=str(tmp_path))
    assert lido["id"] == b["id"] and lido["emitida"] == b["emitida"]
    assert len(lido["ordens"]) == len(b["ordens"])
    assert lido["ordens"][0]["preco_limite"] == b["ordens"][0]["preco_limite"]
    # dia sem boleta nao levanta: devolve None
    assert bo.carregar("2020-01-02", dir_saida=str(tmp_path)) is None
