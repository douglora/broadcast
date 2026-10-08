"""
O veredito do gate em disco, e a impressao que o mantem honesto.

O que estes testes protegem: `boleta.modo_seguro` bloqueia quando `gate_passou is None`, de
proposito. Antes deste modulo nao havia artefato nenhum, entao `rodar_diario --paper` e
`campanha --sessao` passavam None sempre e nasciam bloqueados PARA SEMPRE - o comando da
rotina da manha nunca produziria boleta, nem com o banco carregado e o gate aprovado.

O teste que mais importa e `test_banco_que_mudou_invalida_o_gate`. Sem ele, um gate aprovado
em marco continuaria valendo em setembro sobre um banco recarregado - e um veredito que
descreve um banco que nao existe mais e pior que veredito nenhum, porque parece valido.
"""
import json

import pytest

from quant.dados import cotahist
from quant.validacao import gate


@pytest.fixture
def banco(tmp_path, monkeypatch):
    """Um banco de mentira com os parquets dos anos que o gate leria."""
    monkeypatch.setattr(cotahist, "DIR_BANCO", str(tmp_path))

    def escrever(ano, conteudo=b"x" * 100):
        p = tmp_path / "cotacoes_diarias" / f"ano={ano}" / "parte.parquet"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(conteudo)
        return p

    return escrever


@pytest.fixture
def arq(tmp_path):
    return str(tmp_path / "gate_fase1.json")


def _resultado(passou=True):
    return {"WML": {"correlacao": 0.94, "diferenca_pp": 1.2, "n_meses": 216,
                    "passou": passou},
            "passou": passou}


# ─────────────────────────────────────────────────────────────
# Desconhecido bloqueia: os quatro jeitos de nao saber
# ─────────────────────────────────────────────────────────────
def test_sem_arquivo_e_desconhecido_e_diz_o_comando(arq):
    passou, motivo = gate.ler(arq)
    assert passou is None
    assert "replica_nefin" in motivo


def test_arquivo_ilegivel_e_desconhecido(arq):
    with open(arq, "w") as f:
        f.write("{isto nao e json")
    assert gate.ler(arq)[0] is None


def test_versao_desconhecida_bloqueia(arq, banco):
    banco(2006); banco(2007); banco(2008)
    gate.gravar(_resultado(True), 2008, 2008, caminho=arq)
    corpo = json.load(open(arq))
    corpo["versao"] = 999
    json.dump(corpo, open(arq, "w"))
    passou, motivo = gate.ler(arq)
    assert passou is None and "999" in motivo


def test_janela_faltando_bloqueia(arq, banco):
    banco(2008)
    gate.gravar(_resultado(True), 2008, 2008, caminho=arq)
    corpo = json.load(open(arq))
    del corpo["janela"]
    json.dump(corpo, open(arq, "w"))
    assert gate.ler(arq)[0] is None


# ─────────────────────────────────────────────────────────────
# O teste central: o banco mudou, o gate caducou
# ─────────────────────────────────────────────────────────────
def test_banco_que_mudou_invalida_o_gate(arq, banco):
    """Recarregar um ano muda os fatores. O veredito antigo passa a descrever um banco
    que nao existe mais - e tem de voltar a bloquear."""
    banco(2006); banco(2007); banco(2008)
    gate.gravar(_resultado(True), 2008, 2008, caminho=arq)
    assert gate.ler(arq)[0] is True                      # antes de mexer, vale

    banco(2008, b"y" * 250)                              # ano regravado, tamanho diferente
    passou, motivo = gate.ler(arq)
    assert passou is None
    assert "banco diferente" in motivo


def test_ano_acrescentado_invalida_o_gate(arq, banco):
    """Gate rodado com buraco nao pode continuar valendo depois que o buraco foi tapado:
    com o ano a mais o resultado seria outro."""
    banco(2006); banco(2008)                             # 2007 ausente
    gate.gravar(_resultado(True), 2008, 2008, caminho=arq)
    assert gate.ler(arq)[0] is True
    banco(2007)
    assert gate.ler(arq)[0] is None


def test_ano_removido_invalida_o_gate(arq, banco, tmp_path):
    banco(2006); banco(2007); banco(2008)
    gate.gravar(_resultado(True), 2008, 2008, caminho=arq)
    (tmp_path / "cotacoes_diarias" / "ano=2007" / "parte.parquet").unlink()
    assert gate.ler(arq)[0] is None


def test_banco_intocado_mantem_o_veredito(arq, banco):
    banco(2006); banco(2007); banco(2008)
    gate.gravar(_resultado(True), 2008, 2008, caminho=arq)
    for _ in range(3):
        assert gate.ler(arq)[0] is True                  # ler nao muda nada


# ─────────────────────────────────────────────────────────────
# Reprovado e reprovado, nao desconhecido
# ─────────────────────────────────────────────────────────────
def test_gate_reprovado_devolve_false_e_nao_none(arq, banco):
    """False e None bloqueiam os dois, mas dizem coisas diferentes: um gate que REPROVOU
    significa banco errado, e o painel tem de falar isso, nao 'ainda nao rodou'."""
    banco(2006); banco(2007); banco(2008)
    gate.gravar(_resultado(False), 2008, 2008, caminho=arq)
    passou, motivo = gate.ler(arq)
    assert passou is False
    assert "REPROVOU" in motivo


# ─────────────────────────────────────────────────────────────
# A impressao
# ─────────────────────────────────────────────────────────────
def test_impressao_cobre_a_janela_com_historico(banco, tmp_path):
    """O gate carrega ini-2 para ter historico de momento; a impressao tem de cobrir
    os mesmos anos, senao ela descreve uma janela diferente da que foi lida."""
    banco(2006); banco(2007); banco(2008)
    antes = gate.impressao_do_banco(2008, 2008)
    banco(2006, b"z" * 400)                              # mexe so no historico
    assert gate.impressao_do_banco(2008, 2008) != antes


def test_impressao_e_estavel(banco):
    banco(2008)
    assert gate.impressao_do_banco(2008, 2008) == gate.impressao_do_banco(2008, 2008)


def test_banco_inteiro_ausente_nao_levanta(tmp_path, monkeypatch):
    monkeypatch.setattr(cotahist, "DIR_BANCO", str(tmp_path / "nao_existe"))
    assert isinstance(gate.impressao_do_banco(2008, 2010), str)


# ─────────────────────────────────────────────────────────────
# Gravar e ler
# ─────────────────────────────────────────────────────────────
def test_grava_os_numeros_do_fator(arq, banco):
    banco(2006); banco(2007); banco(2008)
    corpo = gate.gravar(_resultado(True), 2008, 2008, caminho=arq, hoje="2026-10-08")
    assert corpo["rodado_em"] == "2026-10-08"
    assert corpo["janela"] == [2008, 2008]
    assert corpo["fatores"]["WML"]["correlacao"] == 0.94
    assert corpo["fatores"]["WML"]["diferenca_pp"] == 1.2


def test_resumo_e_serializavel_para_o_painel(arq, banco):
    banco(2006); banco(2007); banco(2008)
    gate.gravar(_resultado(True), 2008, 2008, caminho=arq)
    r = gate.resumo(arq)
    json.dumps(r)
    assert r["passou"] is True and r["fatores"]["WML"]["passou"] is True


def test_resumo_sem_arquivo_nao_levanta(arq):
    r = gate.resumo(arq)
    json.dumps(r)
    assert r["passou"] is None


# ─────────────────────────────────────────────────────────────
# O que o gate destrava: modo_seguro deixa de bloquear por ele
# ─────────────────────────────────────────────────────────────
def test_o_veredito_lido_destrava_o_modo_seguro(arq, banco):
    """O fecho do circuito: o que `ler()` devolve e exatamente o que `modo_seguro` espera."""
    from quant.execucao import boleta as bo
    banco(2006); banco(2007); banco(2008)
    gate.gravar(_resultado(True), 2008, 2008, caminho=arq)
    passou, _ = gate.ler(arq)

    frescor = {f: {"data": "2026-10-08", "dias_atras": 0, "ok": True}
               for f in bo.FONTES_OBRIGATORIAS}
    ativo, motivos = bo.modo_seguro(frescor, gate_passou=passou)
    assert ativo is False and motivos == []

    ativo_sem, motivos_sem = bo.modo_seguro(frescor, gate_passou=None)
    assert ativo_sem is True
    assert any("gate" in m for m in motivos_sem)
