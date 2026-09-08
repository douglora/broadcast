"""A rodada diaria: o que o Douglas executa todo dia e o que alimenta o painel.

O teste central e o do MODO SEGURO: com dado atrasado ou sem o gate da fase 1 aprovado,
nao pode sair boleta nenhuma, e o motivo tem de estar escrito. Depois vem o contrato do
JSON: o painel e lido por um terminal que nao importa pandas, entao NaN, numpy ou
Timestamp no arquivo quebram a tela em silencio.

Roda sobre o mercado sintetico com poucos papeis e poucos anos, para a suite continuar rapida.
"""
import json
import os
from datetime import date

import numpy as np
import pandas as pd
import pytest

from quant import rodar_diario as rd


# ─────────────────────────────────────────────────────────────
# limpar(): o contrato do JSON
# ─────────────────────────────────────────────────────────────
def test_limpar_troca_nan_e_infinito_por_nulo():
    assert rd.limpar(float("nan")) is None
    assert rd.limpar(float("inf")) is None
    assert rd.limpar(np.float64("nan")) is None
    assert rd.limpar(np.nan) is None


def test_limpar_converte_numpy_e_datas():
    assert rd.limpar(np.int64(5)) == 5 and isinstance(rd.limpar(np.int64(5)), int)
    assert rd.limpar(np.float64(1.5)) == 1.5 and isinstance(rd.limpar(np.float64(1.5)), float)
    assert rd.limpar(np.bool_(True)) is True
    assert rd.limpar(pd.Timestamp("2026-09-08")) == "2026-09-08"
    assert rd.limpar(date(2026, 9, 8)) == "2026-09-08"
    assert rd.limpar(pd.NaT) is None


def test_limpar_desce_em_dicionarios_e_listas():
    bruto = {"a": [np.float64(1.0), float("nan")], "b": {"c": pd.Timestamp("2026-01-02")}}
    limpo = rd.limpar(bruto)
    assert limpo == {"a": [1.0, None], "b": {"c": "2026-01-02"}}
    texto = json.dumps(limpo)
    assert "NaN" not in texto and "Infinity" not in texto


# ─────────────────────────────────────────────────────────────
# Frescor e modo seguro
# ─────────────────────────────────────────────────────────────
def test_frescor_conta_pregoes_e_nao_dias_corridos():
    """07/09/2026 e feriado e cai numa segunda: a sexta 04/09 E o pregao anterior a
    terca 08/09, entao o dado de sexta esta fresco. Contar dia corrido daria 4 e o
    sistema bloquearia sem motivo."""
    hoje = date(2026, 9, 8)
    f = rd.frescor(hoje, {"cotahist": (date(2026, 9, 4), 1)})
    assert f["cotahist"]["dias_atras"] == 1 and f["cotahist"]["ok"]
    g = rd.frescor(hoje, {"cotahist": (date(2026, 9, 8), 1)})
    assert g["cotahist"]["dias_atras"] == 0 and g["cotahist"]["ok"]
    velho = rd.frescor(hoje, {"cotahist": (date(2026, 9, 1), 1)})
    assert velho["cotahist"]["dias_atras"] == 4 and not velho["cotahist"]["ok"]


def test_fonte_ausente_nao_esta_ok():
    f = rd.frescor(date(2026, 9, 8), {"bdi": (None, 1)})
    assert f["bdi"]["data"] is None and f["bdi"]["ok"] is False


def test_modo_seguro_bloqueia_com_dado_atrasado():
    f = {"cotahist": {"data": "2026-09-01", "dias_atras": 5, "ok": False}}
    ativo, motivos = rd.modo_seguro(f, gate_passou=True)
    assert ativo and any("cotahist" in m for m in motivos)


def test_modo_seguro_bloqueia_quando_o_gate_e_desconhecido():
    """O padrao e nao saber, e nao saber tem de bloquear: emitir boleta sobre dado que
    ninguem validou nao e comportamento seguro."""
    f = {"cotahist": {"data": "2026-09-08", "dias_atras": 0, "ok": True}}
    assert rd.modo_seguro(f, gate_passou=None)[0]
    assert rd.modo_seguro(f, gate_passou=False)[0]
    ativo, motivos = rd.modo_seguro(f, gate_passou=True)
    assert not ativo and motivos == []


def test_modo_seguro_repassa_motivos_extras():
    f = {"cotahist": {"data": "2026-09-08", "dias_atras": 0, "ok": True}}
    ativo, motivos = rd.modo_seguro(f, gate_passou=True, extras=["dados sinteticos"])
    assert ativo and "dados sinteticos" in motivos


# ─────────────────────────────────────────────────────────────
# Rodada completa sobre o mercado sintetico
# ─────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def painel():
    dados = rd.carregar_sintetico(seed=5, n_empresas=25, anos=2)
    return rd.rodar(modo="paper", capital=100_000.0, seed=5, dados=dados)


def test_painel_tem_todos_os_blocos_do_contrato(painel):
    esperado = {"gerado_em", "modo", "origem", "capital", "gate_fase1", "frescor",
                "modo_seguro", "carteira", "boleta", "paper", "versao", "fiscal",
                "desempenho", "kill"}
    assert set(painel) == esperado


def test_painel_e_json_valido_sem_nan(painel):
    texto = json.dumps(painel)
    assert "NaN" not in texto and "Infinity" not in texto and "Timestamp" not in texto


def test_dado_sintetico_e_carimbado_e_bloqueia(painel):
    assert painel["origem"] == "sintetico"
    assert painel["modo_seguro"]["ativo"]
    assert any("sintetic" in m for m in painel["modo_seguro"]["motivos"])
    assert painel["gate_fase1"]["passou"] is False


def test_com_modo_seguro_ativo_nao_sai_boleta(painel):
    """O teste que mais importa: boleta com dado velho e pior que boleta nenhuma."""
    assert painel["modo_seguro"]["ativo"]
    assert painel["boleta"]["emitida"] is False
    assert painel["boleta"]["ordens"] == []


def test_blocos_carteira_e_fiscal_tem_o_esquema(painel):
    c = painel["carteira"]
    for chave in ("patrimonio", "caixa", "valor_posicoes", "n_posicoes", "contratos_hedge",
                  "exposicao", "caixa_minimo", "violacoes", "posicoes"):
        assert chave in c
    f = painel["fiscal"]
    for chave in ("mes", "vendas_acoes_mes", "isencao_restante", "darf", "aviso"):
        assert chave in f
    assert "contador" in f["aviso"]


def test_criterios_de_kill_vem_avaliados(painel):
    from quant import relatorio as rel
    assert len(painel["kill"]) == len(rel.CRITERIOS)
    assert all(k["status"] in ("ok", "atencao", "disparado") for k in painel["kill"])


def test_universo_pequeno_dispara_o_criterio(painel):
    """25 empresas sinteticas ficam bem abaixo dos 100 nomes que a estrategia pressupoe;
    o painel tem de dizer isso em vez de fingir que esta tudo bem."""
    uni = [k for k in painel["kill"] if k["criterio"] == "universo"][0]
    assert uni["status"] == "disparado" and uni["valor"] < 100


def test_grava_e_le_o_painel(painel, tmp_path):
    caminho = str(tmp_path / "painel.json")
    rd.gravar_painel(painel, caminho)
    lido = json.load(open(caminho, encoding="utf-8"))
    assert lido["origem"] == painel["origem"] and set(lido) == set(painel)


def test_rodada_sem_banco_nao_levanta(monkeypatch):
    """Sem banco montado a rodada cai para o sintetico em vez de quebrar."""
    monkeypatch.setattr(rd, "_tem_banco", lambda: False)
    assert rd.carregar_real() is None


def test_estado_sem_livro_comeca_do_zero(painel):
    c = painel["carteira"]
    assert c["patrimonio"] == 100_000.0
    assert c["n_posicoes"] == 0 and c["posicoes"] == []


# ─────────────────────────────────────────────────────────────
# Preco do dia: o achado do primeiro ensaio da fase 4
# ─────────────────────────────────────────────────────────────
def _cot():
    return pd.DataFrame([
        {"ticker": "AAAA3", "data": pd.Timestamp("2026-02-27"), "fec": 15.76},
        {"ticker": "AAAA3", "data": pd.Timestamp("2026-03-05"), "fec": 16.46},
        {"ticker": "BBBB4", "data": pd.Timestamp("2026-03-05"), "fec": 30.10},
        {"ticker": "CCCC3", "data": pd.Timestamp("2025-11-10"), "fec": 8.00},
    ])


def _painel_mensal():
    return pd.DataFrame([{"ticker": "AAAA3", "data": pd.Timestamp("2026-02-27"), "preco": 15.76},
                         {"ticker": "CCCC3", "data": pd.Timestamp("2026-02-27"), "preco": 7.90}])


def test_preco_da_ordem_vem_da_cotacao_e_nao_do_painel_mensal():
    """O painel de sinais e mensal. Precificar a ordem por ele congela o limite no ultimo
    pregao do mes anterior: no ensaio da fase 4 saiu compra a 15,76 num papel que negociou
    o dia inteiro entre 16,43 e 16,49, reemitida todo dia e nunca executada."""
    p = rd.precos_do_dia({"cotacoes": _cot()}, "2026-03-05", _painel_mensal())
    assert p["AAAA3"] == 16.46 and p["BBBB4"] == 30.10


def test_papel_sem_negocio_na_janela_mantem_o_preco_do_painel():
    p = rd.precos_do_dia({"cotacoes": _cot()}, "2026-03-05", _painel_mensal())
    assert p["CCCC3"] == 7.90                 # cotacao de novembro esta fora da janela


def test_preco_do_dia_nao_enxerga_o_futuro():
    p = rd.precos_do_dia({"cotacoes": _cot()}, "2026-02-27", _painel_mensal())
    assert p["AAAA3"] == 15.76 and "BBBB4" not in p


def test_preco_do_dia_sem_cotacao_nao_levanta():
    assert rd.precos_do_dia({}, "2026-03-05") == {}
    assert rd.precos_do_dia(None, "2026-03-05", _painel_mensal())["AAAA3"] == 15.76


def test_bloco_paper_sem_campanha_tem_zero_sessoes(monkeypatch, tmp_path):
    """Nao ter comecado o paper e um estado, nao um erro: o bloco existe e diz zero.

    Os caminhos vao para tmp_path de proposito: o bloco le arquivos reais de quant/saida/,
    e um ensaio rodado na maquina faria este teste passar ou falhar por acidente."""
    from quant.execucao import campanha as cp
    for atributo in ("ARQ_SESSOES", "ARQ_SESSOES_ENSAIO", "ARQ_ERROS", "ARQ_CONFERENCIAS",
                     "ARQ_CONFIG"):
        monkeypatch.setattr(cp, atributo, str(tmp_path / atributo.lower()))
    p = rd.bloco_paper({"origem": "sintetico"})
    assert p["sessoes"] == 0 and p["passou"] is False
    assert isinstance(p["criterios"], list)


def test_bloco_paper_carimba_o_ensaio_como_ensaio(monkeypatch, tmp_path):
    """Com campanha real vazia o painel mostra o ensaio — dizendo que e ensaio."""
    from quant.execucao import campanha as cp
    arq = str(tmp_path / "ensaio.csv")
    linha = {c: None for c in cp.COLUNAS_SESSAO}
    linha.update({"data": "2026-04-01", "emitida": True, "n_ordens": 2, "qtd_pedida": 100.0,
                  "qtd_executada": 100.0, "taxa_execucao": 1.0, "financeiro": 3000.0,
                  "hedge_motivo": "abertura", "origem": "ensaio"})
    cp.registrar_sessoes(pd.DataFrame([linha], columns=cp.COLUNAS_SESSAO), arq)
    monkeypatch.setattr(cp, "ARQ_SESSOES", str(tmp_path / "vazio.csv"))
    monkeypatch.setattr(cp, "ARQ_SESSOES_ENSAIO", arq)
    monkeypatch.setattr(cp, "ARQ_ERROS", str(tmp_path / "erros.csv"))
    monkeypatch.setattr(cp, "ARQ_CONFERENCIAS", str(tmp_path / "conf.csv"))
    monkeypatch.setattr(cp, "ARQ_CONFIG", str(tmp_path / "config.json"))
    p = rd.bloco_paper({"origem": "sintetico"})
    assert p["sessoes"] == 1 and p["origem"] == "ensaio" and p["passou"] is False


def test_bloco_versao_sem_changelog_diz_que_falta_a_linha_de_base(monkeypatch, tmp_path):
    """Nao ter registrado a v1 e um estado, nao um erro — mas tem de aparecer."""
    from quant import versoes as vr
    monkeypatch.setattr(vr, "ARQ_VERSOES", str(tmp_path / "versoes.jsonl"))
    v = rd.bloco_versao()
    assert v["vigente"] is None and v["config_confere"] is False
    assert v["mudancas_no_ano"] == 0 and v["pode_mudar"] is True
    json.dumps(v)
