"""O changelog de versoes: o criterio de kill 7 com dentes.

O que se testa aqui nao e aritmetica, e disciplina. A terceira mudanca do ano tem de ser
RECUSADA; a versao nova nao pode passar a valer no dia em que foi pensada; a linha de base
nao pode consumir orcamento; e mexer num parametro sem registrar tem de aparecer, porque a
regra so vale se a falta dela for visivel.
"""
import json

import pandas as pd
import pytest

from quant import versoes as vs


C0 = {"sinais": {"pct_momentum": 50, "pesos": [0.5, 0.25, 0.25]}, "carteira": {"n": 22}}
C1 = {"sinais": {"pct_momentum": 55, "pesos": [0.5, 0.25, 0.25]}, "carteira": {"n": 22}}
C2 = {"sinais": {"pct_momentum": 55, "pesos": [0.5, 0.25, 0.25]}, "carteira": {"n": 20}}
C3 = {"sinais": {"pct_momentum": 60, "pesos": [0.6, 0.2, 0.2]}, "carteira": {"n": 20}}
BT = {"sharpe_atual": 0.30, "sharpe_novo": 0.32, "janela": "2011-2015"}


@pytest.fixture
def arq(tmp_path):
    return str(tmp_path / "versoes.jsonl")


def _base(arq, quando="2026-01-05"):
    return vs.registrar("linha de base", "fase 2 aprovada", BT, config=C0,
                        caminho=arq, quando=quando)


# ─────────────────────────────────────────────────────────────
# Linha de base
# ─────────────────────────────────────────────────────────────
def test_linha_de_base_vale_desde_ja(arq):
    """A primeira versao nao e uma mudanca: e o ponto de partida. Esperar 3 meses por ela
    deixaria o sistema 3 meses sem versao nenhuma contra a qual comparar."""
    v = _base(arq)
    assert v["linha_de_base"] is True and v["estado"] == "vigente"
    assert v["vigente_a_partir_de"] == "2026-01-05"
    assert vs.vigente(arq, "2026-01-06")["id"] == "v1"


def test_linha_de_base_nao_consome_orcamento(arq):
    _base(arq)
    assert vs.mudancas_no_ano(2026, arq) == 0
    assert vs.pode_mudar("2026-06-01", arq)[0] is True


def test_sem_versao_registrada_o_painel_diz_isso_sem_alarme(arq):
    c = vs.conferir(C0, arq)
    assert c["ok"] is False and c["versao"] is None
    assert c["motivo"] == "nenhuma versao registrada ainda"


# ─────────────────────────────────────────────────────────────
# O orcamento anual
# ─────────────────────────────────────────────────────────────
def test_terceira_mudanca_do_ano_e_recusada(arq):
    _base(arq)
    vs.registrar("momentum 50->55", "pesquisa", BT, config=C1, caminho=arq, quando="2026-03-10")
    vs.registrar("n 22->20", "pesquisa", BT, config=C2, caminho=arq, quando="2026-05-02")
    with pytest.raises(RuntimeError) as e:
        vs.registrar("mais uma", "o mes foi ruim", BT, config=C3, caminho=arq,
                     quando="2026-06-01")
    assert "orcamento de 2 mudancas de 2026 acabou" in str(e.value)
    assert "01/01/2027" in str(e.value)
    assert len(vs.historico(arq)) == 3          # a recusada nao entrou no arquivo


def test_o_orcamento_reabre_no_ano_seguinte(arq):
    _base(arq)
    vs.registrar("a", "pesquisa", BT, config=C1, caminho=arq, quando="2026-03-10")
    vs.registrar("b", "pesquisa", BT, config=C2, caminho=arq, quando="2026-05-02")
    v = vs.registrar("c", "pesquisa", BT, config=C3, caminho=arq, quando="2027-01-04")
    assert v["id"] == "v4" and "excecao" not in v


def test_forcar_grava_a_excecao_em_vez_de_esconder(arq):
    """Quebrar a regra tem de ficar escrito na propria versao: quem ler o changelog
    daqui a um ano precisa ver que houve uma terceira mudanca e em que dia."""
    _base(arq)
    vs.registrar("a", "pesquisa", BT, config=C1, caminho=arq, quando="2026-03-10")
    vs.registrar("b", "pesquisa", BT, config=C2, caminho=arq, quando="2026-05-02")
    v = vs.registrar("c", "excecao consciente", BT, config=C3, caminho=arq,
                     quando="2026-06-01", forcar=True)
    assert v["excecao"]["regra"] == "orcamento anual de mudancas"
    assert "EXCECAO A REGRA" in vs.texto(arq, "2026-12-01")


# ─────────────────────────────────────────────────────────────
# Os 3 meses em paralelo
# ─────────────────────────────────────────────────────────────
def test_versao_nova_nao_manda_no_dia_em_que_foi_pensada(arq):
    _base(arq)
    vs.registrar("momentum 50->55", "pesquisa", BT, config=C1, caminho=arq, quando="2026-03-10")
    assert vs.vigente(arq, "2026-03-11")["id"] == "v1"     # quem manda ainda e a anterior
    assert vs.vigente(arq, "2026-06-09")["id"] == "v1"
    assert vs.vigente(arq, "2026-06-10")["id"] == "v2"     # 3 meses depois, e so entao
    assert [x["id"] for x in vs.em_paralelo(arq, "2026-04-01")] == ["v2"]
    assert vs.em_paralelo(arq, "2026-07-01") == []


def test_config_da_versao_em_paralelo_nao_e_a_que_confere(arq):
    """Enquanto v2 roda em paralelo, a configuracao valida continua sendo a da v1."""
    _base(arq)
    vs.registrar("momentum 50->55", "pesquisa", BT, config=C1, caminho=arq, quando="2026-03-10")
    assert vs.conferir(C0, arq, "2026-04-01")["ok"] is True
    assert vs.conferir(C1, arq, "2026-04-01")["ok"] is False
    assert vs.conferir(C1, arq, "2026-07-01")["ok"] is True


# ─────────────────────────────────────────────────────────────
# Recusas de conteudo
# ─────────────────────────────────────────────────────────────
def test_versao_sem_backtest_e_recusada(arq):
    _base(arq)
    with pytest.raises(RuntimeError) as e:
        vs.registrar("momentum", "achismo", None, config=C1, caminho=arq, quando="2026-03-10")
    assert "diario de opinioes" in str(e.value)


def test_versao_que_nao_muda_nada_e_recusada(arq):
    _base(arq)
    with pytest.raises(RuntimeError) as e:
        vs.registrar("nada", "so para marcar", BT, config=C0, caminho=arq, quando="2026-03-10")
    assert "nenhum parametro mudou" in str(e.value)
    assert vs.mudancas_no_ano(2026, arq) == 0


# ─────────────────────────────────────────────────────────────
# Diff: "eu so mexi num percentil" vira uma lista conferivel
# ─────────────────────────────────────────────────────────────
def test_diff_desce_em_dicionarios_aninhados():
    d = {x["campo"]: (x["de"], x["para"]) for x in vs.diff_config(C1, C3)}
    assert d == {"sinais.pct_momentum": (55, 60), "carteira.n": (22, 20),
                 "sinais.pesos": ([0.5, 0.25, 0.25], [0.6, 0.2, 0.2])}


def test_diff_marca_campo_que_so_existe_de_um_lado():
    d = vs.diff_config({"a": 1}, {"a": 1, "b": 2})
    assert d == [{"campo": "b", "de": None, "para": 2}]
    assert vs.diff_config({"a": 1}, {"a": 1}) == []


def test_diff_de_configuracao_vazia_ou_invalida_nao_levanta():
    assert vs.diff_config(None, None) == []
    assert vs.diff_config(None, {"a": 1}) == [{"campo": "a", "de": None, "para": 1}]


# ─────────────────────────────────────────────────────────────
# Mudanca nao registrada: a regra so vale se a falta dela aparecer
# ─────────────────────────────────────────────────────────────
def test_parametro_mexido_sem_registro_aparece(arq):
    _base(arq)
    c = vs.conferir(C3, arq, "2026-06-01")
    assert c["ok"] is False and c["versao"] == "v1"
    assert {d["campo"] for d in c["diff"]} == {"sinais.pct_momentum", "sinais.pesos",
                                               "carteira.n"}
    assert "sem versao registrada" in c["motivo"]


def test_resumo_do_painel_e_json_nativo(arq):
    _base(arq)
    vs.registrar("momentum", "pesquisa", BT, config=C1, caminho=arq, quando="2026-03-10")
    r = vs.resumo(arq, "2026-04-01", C0)
    json.dumps(r)
    assert r["vigente"] == "v1" and r["mudancas_no_ano"] == 1 and r["limite_ano"] == 2
    assert r["em_paralelo"][0]["id"] == "v2"
    assert r["config_confere"] is True and r["cadeia_ok"] is True


def test_resumo_sem_arquivo_nao_levanta(arq):
    r = vs.resumo(arq, "2026-04-01", C0)
    json.dumps(r)
    assert r["vigente"] is None and r["pode_mudar"] is True and r["cadeia_ok"] is True


# ─────────────────────────────────────────────────────────────
# A cadeia de hash
# ─────────────────────────────────────────────────────────────
def test_cadeia_acusa_linha_editada(arq):
    _base(arq)
    vs.registrar("momentum", "pesquisa", BT, config=C1, caminho=arq, quando="2026-03-10")
    assert vs.verificar_cadeia(arq) == (True, None)
    linhas = open(arq, encoding="utf-8").read().splitlines()
    alvo = json.loads(linhas[1])
    alvo["motivo"] = "outra coisa"              # reescrever a historia
    linhas[1] = json.dumps(alvo, ensure_ascii=False)
    open(arq, "w", encoding="utf-8").write("\n".join(linhas) + "\n")
    assert vs.verificar_cadeia(arq) == (False, 1)


def test_cadeia_acusa_linha_apagada(arq):
    _base(arq)
    vs.registrar("a", "pesquisa", BT, config=C1, caminho=arq, quando="2026-03-10")
    vs.registrar("b", "pesquisa", BT, config=C2, caminho=arq, quando="2026-05-02")
    linhas = open(arq, encoding="utf-8").read().splitlines()
    open(arq, "w", encoding="utf-8").write(linhas[0] + "\n" + linhas[2] + "\n")
    assert vs.verificar_cadeia(arq)[0] is False


def test_arquivo_ausente_tem_cadeia_valida(arq):
    assert vs.verificar_cadeia(arq) == (True, None)
    assert vs.historico(arq) == [] and vs.vigente(arq) is None


# ─────────────────────────────────────────────────────────────
# Texto e CLI
# ─────────────────────────────────────────────────────────────
def test_texto_sem_versao_manda_registrar_a_linha_de_base(arq):
    t = vs.texto(arq)
    assert "Nenhuma versao registrada" in t and "linha de base" in t


def test_texto_marca_a_vigente_e_lista_o_diff(arq):
    _base(arq)
    vs.registrar("momentum 50->55", "pesquisa", BT, config=C1, caminho=arq, quando="2026-03-10")
    t = vs.texto(arq, "2026-07-01")
    assert "## v2 (VIGENTE)" in t
    assert "`sinais.pct_momentum`: 50 -> 55" in t


def test_main_conferir_sem_versao_devolve_um(monkeypatch, tmp_path):
    monkeypatch.setattr(vs, "ARQ_VERSOES", str(tmp_path / "v.jsonl"))
    assert vs.main(["--conferir"]) == 1


def test_main_registrar_com_backtest_invalido_devolve_dois(monkeypatch, tmp_path):
    monkeypatch.setattr(vs, "ARQ_VERSOES", str(tmp_path / "v.jsonl"))
    assert vs.main(["--registrar", "x", "y", "--backtest", "{nao e json"]) == 2
