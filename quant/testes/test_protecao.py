"""Protecao em mini-indice do robo da carteira (10/10/2026). O caso de 08/10/2026 vira teste: com metade das acoes
compradas a venda de indice nao entra; ela nunca passa do valor das acoes; e e carregada de um pregao para o outro."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from quant.execucao import protecao as pt
from quant.execucao import robo_vivo as rv

BRT = timezone(timedelta(hours=-3))
INDICE = 206_780.0                      # mini-indice de 08/10/2026: 1 contrato = R$ 41.356


@pytest.fixture(autouse=True)
def _sem_config_do_douglas(tmp_path, monkeypatch):
    """Os testes valem para a razao padrao (metade): a decisao do Douglas mora num arquivo, que aqui nao existe."""
    monkeypatch.setattr(pt, "ARQ_CONFIG", str(tmp_path / "carteira_config_que_nao_existe.json"))


def test_o_caso_de_08_10_nao_vende_indice_com_metade_das_acoes():
    assert round(pt.nocional(INDICE)) == 41356
    assert pt.contratos_alvo(0.0, INDICE, 0) == 0                    # 10h20: nada comprado ainda
    assert pt.contratos_alvo(32_700.0, INDICE, 0) == 0               # 11h26 daquele dia: R$ 32,7 mil de acoes
    assert pt.contratos_alvo(68_000.0, INDICE, 0) == 1               # livro cheio: 0,5 x 68 mil = 0,82 contrato
    assert pt.contratos_alvo(61_000.0, INDICE, 0) == 0               # 0,74 contrato: ainda nao (folga de 0,75)
    assert pt.contratos_alvo(62_100.0, INDICE, 0) == 1


def test_folga_evita_entrar_e_sair_e_nunca_fica_vendido_no_liquido():
    assert pt.contratos_alvo(55_000.0, INDICE, 1) == 1               # caiu um pouco: fica (acoes ainda cobrem o contrato)
    assert pt.contratos_alvo(41_000.0, INDICE, 1) == 0               # acoes valem menos que 1 contrato: sai na hora
    assert pt.contratos_alvo(150_000.0, INDICE, 1) == 2              # 1,81 contrato: sobe para 2
    assert pt.contratos_alvo(140_000.0, INDICE, 1) == 1              # 1,69: ainda 1
    assert pt.contratos_alvo(100_000.0, INDICE, 2) == 1              # 1,21: volta para 1
    assert pt.contratos_alvo(300_000.0, INDICE, 5) == 4              # 3,63: desce de 5 para 4
    for valor in (0, 10_000, 41_355, 41_357, 82_000, 124_500, 500_000):
        for atual in (0, 1, 2, 3):
            n = pt.contratos_alvo(float(valor), INDICE, atual)
            assert pt.nocional(INDICE, n) <= valor + 1e-6               # regra 3, para qualquer tamanho


def test_sem_preco_nao_mexe_e_boleta_sem_protecao_zera():
    assert pt.contratos_alvo(68_000.0, None, 1) == 1
    assert pt.contratos_alvo(None, INDICE, 1) == 1
    assert pt.contratos_alvo(68_000.0, INDICE, 1, permitido=False) == 0


def test_mover_e_marcar_fazem_a_conta_de_um_vendido():
    h = pt.nova(None, "2026-10-13")
    assert h["contratos"] == 0 and h["ate_ontem"] == 0.0
    d, real = pt.mover(h, 1, 200_000.0, "10:31:00")
    assert (d, real) == (1, 0.0) and h["preco_entrada"] == 200_000.0 and h["custos"] == pytest.approx(pt.CUSTO_LADO)
    pt.marcar(h, 201_000.0, 68_000.0)                                 # indice subiu 1.000 pontos: vendido perde R$ 200
    assert h["aberto"] == -200.0 and h["resultado_hoje"] == pytest.approx(-200.0 - pt.CUSTO_LADO, abs=0.01)
    assert h["cobertura"] == pytest.approx(201_000 * 0.2 / 68_000)
    d, real = pt.mover(h, 0, 199_000.0, "11:00:00")                   # recompra 1.000 pontos abaixo da venda: +R$ 200
    assert d == -1 and real == pytest.approx(200.0) and h["preco_entrada"] is None
    pt.marcar(h, 199_000.0, 30_000.0)
    assert h["aberto"] == 0.0 and h["resultado_hoje"] == pytest.approx(200.0 - 2 * pt.CUSTO_LADO, abs=0.01)


def test_carrega_de_um_pregao_para_o_outro_com_o_salto_da_noite():
    h = pt.nova(None, "2026-10-13")
    pt.mover(h, 1, 200_000.0, "10:31:00")
    pt.marcar(h, 201_000.0, 68_000.0)                                 # fecha o dia 1.000 pontos contra: -200 e o custo
    cad = pt.caderno_de(h, "2026-10-13")
    assert cad["contratos"] == 1 and cad["preco_ref"] == 201_000.0
    h2 = pt.nova(cad, "2026-10-14")                                   # pregao seguinte
    assert h2["contratos"] == 1 and h2["carregado"] is True and h2["preco_entrada"] == 201_000.0
    assert h2["ate_ontem"] == pytest.approx(h["resultado_hoje"]) and h2["realizado"] == 0.0 and h2["custos"] == 0.0
    pt.marcar(h2, 198_000.0, 68_000.0)                                # abriu 3.000 pontos abaixo: o salto da noite conta
    assert h2["aberto"] == 600.0 and h2["resultado_hoje"] == 600.0
    h3 = pt.nova(pt.caderno_de(h2, "2026-10-14"), "2026-10-14")       # robo reiniciado no MESMO dia: nao soma duas vezes
    assert h3["ate_ontem"] == pytest.approx(h2["ate_ontem"]) and h3["preco_entrada"] == 201_000.0


class _SessaoFalsa:
    def __init__(self):
        self.ordens = []

    def estado(self):
        return {"ordens": self.ordens}


def _robo(tmp_path, monkeypatch, hoje="2026-10-13", hedge_boleta=None, posicoes=None):
    monkeypatch.setattr(rv, "DIR_VIVO", str(tmp_path))
    boleta = {"data": hoje, "id": hoje.replace("-", ""), "emitida": True, "ordens": [], "hora_envio": "10:20"}
    if hedge_boleta is not None:
        boleta["hedge"] = hedge_boleta
    painel = {"capital": 100000.0, "boleta": boleta, "carteira": {"patrimonio": 100000.0, "caixa": 100000.0, "posicoes": posicoes or []}}
    r = rv.Robo(painel, hoje, saidas=[str(tmp_path / "quant_fatores.json")])
    r.sessao = _SessaoFalsa()
    return r


def _retrato(dia, hh, mm, indice, precos=None):
    quando = datetime.fromisoformat(f"{dia}T{hh:02d}:{mm:02d}:00").replace(tzinfo=BRT)
    q = {"WINFUT": [indice, 0, 0, 0, 0, 0, 0, quando.timestamp()]}
    for t, p in (precos or {}).items():
        q[t] = [p, 0, 0, 0, 0, 0, 0, quando.timestamp()]
    return {"q": q}, quando


def test_no_robo_a_protecao_espera_as_acoes_e_sai_se_elas_encolhem(tmp_path, monkeypatch):
    r = _robo(tmp_path, monkeypatch, hedge_boleta={"contratos": 1, "vencimento": "2026-12-16", "motivo": "abertura"})
    ret, agora = _retrato("2026-10-13", 10, 21, INDICE)
    r._hedge(ret, agora, "operando")
    assert r.hedge["contratos"] == 0                                  # boleta acabou de sair: nada comprado, nada vendido
    r.sessao.ordens = [{"ticker": "AAAA3", "lado": "C", "executado": 3270, "preco_medio": 10.0}]
    r._hedge(*_retrato("2026-10-13", 11, 26, INDICE, {"AAAA3": 10.0}), "operando")
    assert r.hedge["contratos"] == 0 and r.hedge["valor_acoes"] == 32700.0          # o caso de 08/10
    r.sessao.ordens = [{"ticker": "AAAA3", "lado": "C", "executado": 6800, "preco_medio": 10.0}]
    r._hedge(*_retrato("2026-10-13", 13, 0, INDICE, {"AAAA3": 10.0}), "operando")
    assert r.hedge["contratos"] == 1 and r.hedge["preco_entrada"] == INDICE and r.hedge["vencimento"] == "2026-12-16"
    assert any("Proteção: 1 contrato" in x["texto"] for x in r.diario)
    r._hedge(*_retrato("2026-10-13", 14, 0, INDICE + 1000, {"AAAA3": 10.2}), "operando")
    assert r.hedge["contratos"] == 1 and r.hedge["aberto"] == -200.0  # bolsa subiu: a protecao perde, as acoes ganham mais
    assert r._bloco_protecao()["cobertura_pct"] == pytest.approx((INDICE + 1000) * 0.2 / 69360 * 100, abs=0.1)
    r._hedge(*_retrato("2026-10-13", 15, 0, INDICE, {"AAAA3": 6.0}), "operando")    # acoes despencam para R$ 40,8 mil
    assert r.hedge["contratos"] == 0 and any("Proteção reduzida" in x["texto"] for x in r.diario)
    cad = json.loads((tmp_path / "protecao.json").read_text())
    assert cad["dia"] == "2026-10-13" and cad["contratos"] == 0


def test_no_robo_o_contrato_carregado_e_marcado_antes_da_boleta_e_sem_boleta(tmp_path, monkeypatch):
    (tmp_path / "protecao.json").write_text(json.dumps({"dia": "2026-10-13", "contratos": 1, "preco_ref": 201_000.0,
                                                         "ate_ontem": 0.0, "hoje": -150.0}))
    r = _robo(tmp_path, monkeypatch, hoje="2026-10-14", hedge_boleta={"contratos": 1},
              posicoes=[{"ticker": "AAAA3", "qtd": 6800, "preco_medio": 10.0}])
    assert r.hedge["contratos"] == 1 and r.hedge["carregado"] is True and r.hedge["ate_ontem"] == -150.0
    r._hedge(*_retrato("2026-10-14", 9, 30, 199_000.0, {"AAAA3": 10.0}), "aguardando_abertura")
    assert r.hedge["contratos"] == 1 and r.hedge["aberto"] == 400.0   # abriu 2.000 pontos abaixo: +R$ 400 antes das 10h
    assert r._bloco_protecao()["acumulado_rs"] == 250.0 and r._bloco_protecao()["stop"] is None
    r._hedge(*_retrato("2026-10-13", 9, 31, 150_000.0), "operando")   # cotacao de ontem (data errada): ignora
    assert r.hedge["preco_mercado"] == 199_000.0


def test_boleta_sem_protecao_fecha_o_que_estava_vendido(tmp_path, monkeypatch):
    (tmp_path / "protecao.json").write_text(json.dumps({"dia": "2026-10-13", "contratos": 1, "preco_ref": 200_000.0, "ate_ontem": 0.0, "hoje": 0.0}))
    r = _robo(tmp_path, monkeypatch, hoje="2026-10-14", hedge_boleta={"contratos": 0},
              posicoes=[{"ticker": "AAAA3", "qtd": 6800, "preco_medio": 10.0}])
    r._hedge(*_retrato("2026-10-14", 10, 30, 200_500.0, {"AAAA3": 10.0}), "operando")
    assert r.hedge["contratos"] == 0 and r.hedge["realizado"] == pytest.approx(-100.0)


def test_leitura_de_regime_e_so_informacao_e_nao_depende_de_rede():
    import numpy as np
    import pandas as pd

    from quant import rodar_diario as rd
    dias = pd.bdate_range("2024-01-01", periods=600)
    sobe = pd.DataFrame({"data": dias, "fec": np.linspace(100_000, 200_000, 600)})
    r = rd.bloco_regime(ibov=sobe)
    assert r["estado"] == "alta" and r["votos"] == 4 and r["so_informacao"] is True
    assert r["exposicao_acoes_pct"] == 70.0 and r["protecao_pct"] == 50.0 and len(r["indicadores"]) == 4
    cai = pd.DataFrame({"data": dias, "fec": np.linspace(200_000, 100_000, 600)})
    assert rd.bloco_regime(ibov=cai)["estado"] == "baixa"
    assert rd.bloco_regime(ibov=sobe.head(100)) is None             # historia curta: sem leitura, sem erro


def test_protecao_nao_abre_em_contrato_que_vence_em_poucos_dias():
    from quant import carteira as ct
    n, venc, motivo = ct.ajustar_hedge({"hedge": {"contratos": 0}}, "2026-10-08", 100_000.0)
    assert (n, motivo) == (1, "abertura") and str(venc) == "2026-12-16"          # o de 14/10 vencia em 4 pregoes
    n, venc, motivo = ct.ajustar_hedge({"hedge": {"contratos": 0}}, "2026-09-01", 100_000.0)
    assert str(venc) == "2026-10-14" and motivo == "abertura"                    # longe do vencimento: o proximo mesmo


def test_razao_da_protecao_vem_do_arquivo_do_douglas(tmp_path, monkeypatch):
    assert pt.razao() == 0.5                                            # sem arquivo: o padrao
    arq = tmp_path / "carteira_config.json"
    arq.write_text(json.dumps({"razao_protecao": 0.25}))
    monkeypatch.setattr(pt, "ARQ_CONFIG", str(arq))
    assert pt.razao() == 0.25
    # com 1/4, R$ 68 mil de acoes pedem 0,41 contrato: abaixo de 0,75 nao ha venda de indice
    assert pt.contratos_alvo(68_000.0, INDICE, 0) == 0
    assert pt.contratos_alvo(124_000.0, INDICE, 0) == 0                 # 0,7497: ainda nao
    assert pt.contratos_alvo(125_000.0, INDICE, 0) == 1                 # 0,756: entra o primeiro contrato
    assert pt.contratos_alvo(68_000.0, INDICE, 1) == 1                  # ja vendido: so sai abaixo de 0,25 contrato ou do valor das acoes
    assert pt.contratos_alvo(40_000.0, INDICE, 1) == 0
    h = pt.marcar(pt.nova(None, "2026-10-13"), INDICE, 68_000.0)
    assert h["alvo_fracionario"] == 0.41 and "um quarto" in pt.regra_na_tela()
    arq.write_text(json.dumps({"razao_protecao": 7}))                  # valor absurdo: volta ao padrao
    assert pt.razao() == 0.5


def test_a_tela_explica_por_que_nao_ha_venda_de_indice(tmp_path, monkeypatch):
    arq = tmp_path / "carteira_config.json"
    arq.write_text(json.dumps({"razao_protecao": 0.25}))
    monkeypatch.setattr(pt, "ARQ_CONFIG", str(arq))
    r = _robo(tmp_path, monkeypatch, hedge_boleta={"contratos": 1})
    r.sessao.ordens = [{"ticker": "AAAA3", "lado": "C", "executado": 6800, "preco_medio": 10.0}]
    r._hedge(*_retrato("2026-10-13", 13, 0, INDICE, {"AAAA3": 10.0}), "operando")
    b = r._bloco_protecao()
    assert b["contratos"] == 0 and b["razao_alvo_pct"] == 25.0 and b["alvo_em_contratos"] == 0.41
    assert "0,41 contrato" in b["explicacao"] and "só cabe por opções" in b["explicacao"]
