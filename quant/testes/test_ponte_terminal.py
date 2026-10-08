"""
A ponte do quant para o terminal: o contrato que a aba QUANT consome.

O que estes testes protegem e a unica regra que governa a ponte: NUNCA INVENTAR. Peca que
falta nao pode virar zero nem o valor de ontem - tem de virar bloqueio nomeado, com o
comando que resolve. Um painel de operacao que mostra numero onde nao ha dado e pior que um
painel vazio, porque o numero parece resultado.

O segundo teste em importancia e o da ORDEM dos bloqueios. Ela e a ordem de dependencia
real: sem banco nao ha gate, sem gate nao sai boleta. Mostrar os tres sem ordem faria
alguem tentar o terceiro primeiro e concluir que o sistema esta quebrado.
"""
import json

import pytest

from quant import ponte_terminal as pt


@pytest.fixture
def tudo_faltando(monkeypatch):
    monkeypatch.setattr(pt, "estado_do_banco",
                        lambda: {"ok": False, "estado": "pulada", "detalhe": "sem COTAHIST"})
    monkeypatch.setattr(pt, "estado_do_gate",
                        lambda: {"passou": None, "motivo": "nunca rodou"})
    monkeypatch.setattr(pt, "estado_da_boleta",
                        lambda: {"existe": False, "motivo": "nao gerada"})
    monkeypatch.setattr(pt, "estado_da_campanha", lambda: {"sessoes": 0})


@pytest.fixture
def tudo_pronto(monkeypatch):
    monkeypatch.setattr(pt, "estado_do_banco",
                        lambda: {"ok": True, "estado": "ok", "detalhe": "22 anos seguidos"})
    monkeypatch.setattr(pt, "estado_do_gate",
                        lambda: {"passou": True, "motivo": "aprovado em 2026-10-08"})
    monkeypatch.setattr(pt, "estado_da_boleta",
                        lambda: {"existe": True, "emitida": True, "ordens": [{"ticker": "ABCD3"}],
                                 "modo_seguro": {"ativo": False, "motivos": []}})
    monkeypatch.setattr(pt, "estado_da_campanha", lambda: {"sessoes": 12})


# ─────────────────────────────────────────────────────────────
# A ordem dos bloqueios e a ordem de dependencia
# ─────────────────────────────────────────────────────────────
def test_bloqueios_saem_na_ordem_de_dependencia(tudo_faltando):
    p = pt.payload()
    assert [b["chave"] for b in p["bloqueios"]] == ["banco", "gate", "boleta"]


def test_cada_bloqueio_traz_o_comando_que_resolve(tudo_faltando):
    p = pt.payload()
    por_chave = {b["chave"]: b for b in p["bloqueios"]}
    assert "primeira_carga" in por_chave["banco"]["comando"]
    assert "replica_nefin" in por_chave["gate"]["comando"]
    assert "rodar_diario" in por_chave["boleta"]["comando"]


def test_modo_seguro_ativo_e_bloqueio_sem_comando(monkeypatch, tudo_pronto):
    """Modo seguro nao se resolve com comando: resolve-se consertando o que o motivou."""
    monkeypatch.setattr(pt, "estado_da_boleta",
                        lambda: {"existe": True, "emitida": False,
                                 "modo_seguro": {"ativo": True, "motivos": ["BDI ausente"]}})
    b = pt.payload()["bloqueios"][0]
    assert b["chave"] == "boleta" and b["comando"] is None
    assert "BDI ausente" in b["detalhe"]


# ─────────────────────────────────────────────────────────────
# `pronto` e o interruptor da aba
# ─────────────────────────────────────────────────────────────
def test_pronto_so_quando_nada_bloqueia(tudo_pronto):
    p = pt.payload()
    assert p["pronto"] is True and p["bloqueios"] == []


def test_um_bloqueio_basta_para_nao_estar_pronto(monkeypatch, tudo_pronto):
    monkeypatch.setattr(pt, "estado_do_gate", lambda: {"passou": False, "motivo": "reprovou"})
    p = pt.payload()
    assert p["pronto"] is False
    assert [b["chave"] for b in p["bloqueios"]] == ["gate"]


def test_gate_desconhecido_bloqueia_igual_a_reprovado(monkeypatch, tudo_pronto):
    """None e False sao estados diferentes, mas os dois impedem operar."""
    for veredito in (None, False):
        monkeypatch.setattr(pt, "estado_do_gate", lambda v=veredito: {"passou": v, "motivo": "x"})
        assert pt.payload()["pronto"] is False


# ─────────────────────────────────────────────────────────────
# Serializavel: a aba le isto pela ponte MCP
# ─────────────────────────────────────────────────────────────
def test_payload_e_json_puro(tudo_faltando):
    json.dumps(pt.payload())


def test_payload_real_tambem_serializa():
    """Sem monkeypatch nenhum, contra o disco de verdade: nada de NaN nem Timestamp."""
    json.dumps(pt.payload())


def test_texto_nao_levanta_com_tudo_faltando(tudo_faltando):
    t = pt.texto()
    assert "NAO PRONTO" in t and "primeira_carga" in t


# ─────────────────────────────────────────────────────────────
# Erro de programacao tem de quebrar alto, nao virar estado
# ─────────────────────────────────────────────────────────────
def test_funcao_da_campanha_renomeada_quebra_em_vez_de_dizer_zero(monkeypatch):
    """Se `carregar_sessoes` sumir, isto tem de levantar no teste - nao reportar
    '0 sessoes' e deixar o painel mentir por meses."""
    from quant.execucao import campanha
    monkeypatch.delattr(campanha, "carregar_sessoes")
    with pytest.raises(AttributeError):
        pt.estado_da_campanha()


def test_registro_ilegivel_vira_estado_e_nao_excecao(monkeypatch):
    from quant.execucao import campanha

    def explode():
        raise OSError("disco")

    monkeypatch.setattr(campanha, "carregar_sessoes", explode)
    assert pt.estado_da_campanha()["sessoes"] == 0


def test_banco_que_explode_nao_derruba_a_ponte(monkeypatch):
    from quant.dados import conferir

    def explode():
        raise RuntimeError("parquet corrompido")

    monkeypatch.setattr(conferir, "checar_cobertura_de_precos", explode)
    b = pt.estado_do_banco()
    assert b["ok"] is False and "RuntimeError" in b["detalhe"]


# ─────────────────────────────────────────────────────────────
# A sessao ao vivo entra no payload
# ─────────────────────────────────────────────────────────────
def test_sessao_ao_vivo_entra_e_sem_ela_o_campo_e_none(tudo_pronto):
    import pandas as pd
    from quant.execucao import boleta as bo
    from quant.execucao import paper_vivo as pv

    assert pt.payload()["sessao"] is None

    b = {"data": "2026-10-08", "id": "20261008", "emitida": True, "motivo_bloqueio": [],
         "custo_total": 0.0, "hora_envio": bo.HORA_ENVIO, "validade": bo.VALIDADE,
         "ordens": [{"ticker": "ABCD3", "lado": "C", "qtd": 100, "preco_limite": 10.0,
                     "validade": bo.VALIDADE, "motivo": "entrada", "custo": 0.0,
                     "fatia": "1/1", "adtv": 50e6, "fracionario": False}]}
    s = pv.Sessao(b)
    s.aplicar(pd.DataFrame([{"ticker": "ABCD3", "hora": "10:30:00",
                             "preco": 9.95, "quantidade": 100_000.0}]))
    p = pt.payload(sessao=s)
    assert p["sessao"]["totais"]["qtd_executada"] == 100
    json.dumps(p)
