"""A carga inicial em um comando, e a conferencia do que chegou.

Nao se testa rede aqui: os coletores sao substituidos por funcoes de mentira. O que se
testa e a ORQUESTRACAO — que a ordem e respeitada, que falha de rede e repetida mas codigo
de saida != 0 nao e, que o relatorio final diz a verdade sobre o estado do banco, e que
`--continuar` nao pula passo cujo destino ficou vazio.

Na conferencia, o teste que mais importa e o das deslistadas: banco sem JBSS3 tem de
FALHAR, com a palavra "sobrevivencia" no texto, porque esse e o erro que nao quebra nada e
so faz o backtest ficar bonito.
"""
import json
import os

import pandas as pd
import pytest

from quant import primeira_carga as pc
from quant.dados import conferir as cf


# ─────────────────────────────────────────────────────────────
# Orquestracao
# ─────────────────────────────────────────────────────────────
def test_a_ordem_dos_passos_respeita_as_dependencias():
    """identidade depois de cotahist, eventos depois de identidade, painel por ultimo."""
    nomes = [p[0] for p in pc.PASSOS]
    assert nomes.index("cotahist") < nomes.index("identidade")
    assert nomes.index("identidade") < nomes.index("eventos")
    assert nomes.index("cvm") < nomes.index("painel")
    assert nomes.index("setores") < nomes.index("painel")


def test_o_gate_nao_depende_dos_fundamentos():
    """Da para rodar o gate so com preco, identidade, evento e NEFIN — e isso e de
    proposito: descobrir cedo que o preco esta errado vale mais que esperar a CVM."""
    assert set(pc.OBRIGATORIOS_DO_GATE) == {"nefin", "cotahist", "identidade", "eventos", "cdi"}


def test_falha_de_rede_e_repetida(monkeypatch):
    tentativas = {"n": 0}

    def cai_duas_vezes(anos):
        tentativas["n"] += 1
        if tentativas["n"] < 3:
            raise ConnectionError("conexao resetada")
        return 0

    monkeypatch.setattr(pc.time, "sleep", lambda s: None)
    codigo, erro = pc.rodar_passo("x", "d", cai_duas_vezes, (2020, 2026))
    assert codigo == 0 and erro == "" and tentativas["n"] == 3


def test_codigo_de_saida_nao_zero_nao_e_repetido(monkeypatch):
    """Coletor que devolve 1 ja tentou e concluiu que nao deu; insistir so gasta tempo."""
    chamadas = {"n": 0}

    def devolve_um(anos):
        chamadas["n"] += 1
        return 1

    monkeypatch.setattr(pc.time, "sleep", lambda s: None)
    codigo, _ = pc.rodar_passo("x", "d", devolve_um, (2020, 2026))
    assert codigo == 1 and chamadas["n"] == 1


def test_desiste_depois_das_tentativas(monkeypatch):
    monkeypatch.setattr(pc.time, "sleep", lambda s: None)

    def sempre_cai(anos):
        raise TimeoutError("a fonte nao respondeu")

    codigo, erro = pc.rodar_passo("x", "d", sempre_cai, (2020, 2026), tentativas=2)
    assert codigo == 1 and "TimeoutError" in erro


def test_pasta_vazia_nao_conta_como_passo_feito(tmp_path):
    """Coletor que criou o diretorio e morreu na primeira requisicao deixaria o
    --continuar pular o passo para sempre."""
    vazia = tmp_path / "vazia"
    vazia.mkdir()
    assert pc._feito(str(vazia)) is False
    (vazia / "algo.parquet").write_text("x")
    assert pc._feito(str(vazia)) is True
    arquivo = tmp_path / "zero.parquet"
    arquivo.write_text("")
    assert pc._feito(str(arquivo)) is False
    assert pc._feito(None) is False and pc._feito(str(tmp_path / "nao_existe")) is False


# ─────────────────────────────────────────────────────────────
# Retomada: a unidade e o ano, nao o passo
# ─────────────────────────────────────────────────────────────
def _parquets(pasta, anos, pregoes=246):
    """Escreve um parquet por ano no layout real e devolve a funcao de caminho."""
    for ano in anos:
        alvo = pasta / f"ano={ano}" / "parte.parquet"
        alvo.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"data": pd.date_range(f"{ano}-01-02", periods=pregoes, freq="B")}
                     ).to_parquet(alvo, index=False)
    return lambda ano: str(pasta / f"ano={ano}" / "parte.parquet")


def test_passo_por_ano_com_buraco_nao_esta_completo(tmp_path, monkeypatch):
    """A REGRESSAO QUE IMPORTA. Carga interrompida em 2015 deixa 2005-2014 no disco. Se
    "a pasta tem alguma coisa" contasse como concluido, o clique seguinte pularia o passo e
    o banco ficaria com dez anos de buraco para sempre — sem nada quebrar."""
    from quant.dados import cotahist
    monkeypatch.setattr(cotahist, "caminho_parquet", _parquets(tmp_path, [2005, 2006, 2007]))
    assert pc.completo(pc._dest_cotahist, (2005, 2010)) is False
    assert pc.faltando(pc._dest_cotahist, (2005, 2010)) == [2008, 2009, 2010]


def test_janela_completa_e_pulada_pelo_continuar(tmp_path, monkeypatch):
    """O outro lado: carga terminada nao pode ser refeita do zero a cada clique."""
    from quant.dados import cotahist
    monkeypatch.setattr(cotahist, "caminho_parquet", _parquets(tmp_path, range(2005, 2011)))
    assert pc.faltando(pc._dest_cotahist, (2005, 2010)) == []
    assert pc.completo(pc._dest_cotahist, (2005, 2010)) is True


def test_janela_invertida_nao_conta_como_completa(tmp_path, monkeypatch):
    """--anos 2026-2005 gera zero anos esperados; "nada falta" nao pode virar "esta pronto"."""
    from quant.dados import cotahist
    monkeypatch.setattr(cotahist, "caminho_parquet", _parquets(tmp_path, []))
    assert pc.completo(pc._dest_cotahist, (2026, 2005)) is False


def test_o_destino_vem_de_quem_escreve(tmp_path, monkeypatch):
    """O guarda contra o defeito original: este modulo declarava "banco/cotacoes" enquanto o
    coletor gravava em "banco/cotacoes_diarias/ano=AAAA/". O caminho declarado nunca existia,
    e por isso o passo mais caro nunca era pulado nem reportado como pronto."""
    from quant.dados import cotahist, cvm_fundamentos
    from quant.dados.eventos import ARQ_PARQUET as ARQ_EVENTOS
    from quant.dados.identidade import ARQ_PARQUET as ARQ_IDENTIDADE
    assert pc._dest_cotahist((2020, 2021)) == [(2020, cotahist.caminho_parquet(2020)),
                                               (2021, cotahist.caminho_parquet(2021))]
    assert pc._dest_identidade((2020, 2021)) == [("", ARQ_IDENTIDADE)]
    assert pc._dest_eventos((2020, 2021)) == [("", ARQ_EVENTOS)]
    # a CVM comeca em 2010 e a conta e UMA SO: se o passo e o destino divergissem,
    # `--continuar` esperaria para sempre por um ano que nao existe
    assert pc._dest_cvm((2005, 2011)) == [(2010, cvm_fundamentos.caminho_parquet(2010)),
                                          (2011, cvm_fundamentos.caminho_parquet(2011))]
    # e o modulo nao pode voltar a montar caminho de banco por conta propria: sem
    # DIR_BANCO no namespace, nao ha com o que montar
    assert not hasattr(pc, "DIR_BANCO")


def test_setores_roda_sempre_porque_nao_grava_nada(monkeypatch):
    """setores.main le a identidade e imprime a contagem; nao ha artefato para retomar."""
    destino = dict((p[0], p[4]) for p in pc.PASSOS)["setores"]
    assert destino is None
    assert pc.completo(destino, (2005, 2026)) is False


def test_continuar_roda_o_furado_e_pula_o_completo(tmp_path, monkeypatch, capsys):
    """O caminho que o duplo-clique percorre, ponta a ponta. Um teste que so olhasse
    `completo()` nao pegaria erro no `main` — e foi la que apareceu um, escondido atras de
    um nome local que sombreava a funcao `faltando`."""
    from quant.dados import cotahist
    monkeypatch.setattr(cotahist, "caminho_parquet", _parquets(tmp_path, [2005, 2006, 2009]))
    chamou = []
    monkeypatch.setattr(pc, "PASSOS", [
        ("cotahist", "precos", lambda anos: (chamou.append(anos), 0)[1], True, pc._dest_cotahist)])
    monkeypatch.setattr(pc, "OBRIGATORIOS_DO_GATE", ["cotahist"])

    assert pc.main(["--continuar", "--anos", "2005-2009"]) == 0
    assert chamou == [(2005, 2009)]                      # rodou: faltavam 2007 e 2008
    assert "2007, 2008" in capsys.readouterr().out

    _parquets(tmp_path, [2007, 2008])
    chamou.clear()
    assert pc.main(["--continuar", "--anos", "2005-2009"]) == 0
    assert chamou == []                                  # completo: pulou
    assert "ja esta completo" in capsys.readouterr().out


def test_listar_diz_quais_anos_faltam(tmp_path, monkeypatch, capsys):
    from quant.dados import cotahist
    monkeypatch.setattr(cotahist, "caminho_parquet", _parquets(tmp_path, [2005, 2007]))
    pc.main(["--listar", "--anos", "2005-2007"])
    saida = capsys.readouterr().out
    assert "faltam 1 de 3: 2006" in saida


# ─────────────────────────────────────────────────────────────
# Relatorio: ele tem de dizer a verdade sobre o estado do banco
# ─────────────────────────────────────────────────────────────
def test_relatorio_manda_rodar_o_gate_quando_o_obrigatorio_esta_pronto():
    ok = {n: {"codigo": 0, "erro": ""} for n in pc.OBRIGATORIOS_DO_GATE}
    t = pc.relatorio(ok)
    assert "replica_nefin" in t and "conferir" in t
    assert "NAO pode rodar" not in t


def test_relatorio_bloqueia_quando_falta_obrigatorio():
    parcial = {n: {"codigo": 0, "erro": ""} for n in pc.OBRIGATORIOS_DO_GATE}
    parcial["cotahist"] = {"codigo": 1, "erro": "ConnectionError: fonte fora do ar"}
    t = pc.relatorio(parcial)
    assert "O gate da fase 1 NAO pode rodar" in t and "cotahist" in t
    assert "--continuar" in t and "ConnectionError" in t


def test_passo_opcional_que_falha_nao_bloqueia_o_gate():
    r = {n: {"codigo": 0, "erro": ""} for n in pc.OBRIGATORIOS_DO_GATE}
    r["cvm"] = {"codigo": 1, "erro": "falhou"}
    assert "NAO pode rodar" not in pc.relatorio(r)


def test_listar_nao_executa_nada(capsys):
    assert pc.main(["--listar"]) == 0
    saida = capsys.readouterr().out
    assert "cotahist" in saida and "obrigatorio" in saida


def test_passo_inventado_e_recusado(capsys):
    assert pc.main(["--so", "nao_existe"]) == 2
    assert "desconhecido" in capsys.readouterr().out


def test_anos_malformado_e_recusado(capsys):
    assert pc.main(["--anos", "ontem"]) == 2
    assert "AAAA-AAAA" in capsys.readouterr().out


# ─────────────────────────────────────────────────────────────
# Conferencia do banco
# ─────────────────────────────────────────────────────────────
def _cot(precos, data="2024-12-27"):
    return pd.DataFrame([{"ticker": t, "data": pd.Timestamp(data), "fec": p}
                         for t, p in precos.items()])


def test_precos_de_referencia_batem(monkeypatch):
    from quant.dados import cotahist
    monkeypatch.setattr(cotahist, "carregar",
                        lambda *a, **k: _cot(cf.PRECOS_REFERENCIA))
    r = cf.checar_precos_de_referencia()
    assert all(x["estado"] == cf.OK for x in r)


def test_preco_errado_acusa_o_parser(monkeypatch):
    """Offset errado no campo fixo faz os tres precos sairem errados por fator redondo."""
    from quant.dados import cotahist
    cem_vezes = {t: p * 100 for t, p in cf.PRECOS_REFERENCIA.items()}
    monkeypatch.setattr(cotahist, "carregar", lambda *a, **k: _cot(cem_vezes))
    r = cf.checar_precos_de_referencia()
    assert all(x["estado"] == cf.FALHOU for x in r)
    assert any("offset" in x["detalhe"] for x in r)


def test_deslistada_ausente_e_falha_e_diz_o_nome_do_problema(monkeypatch):
    """O teste mais importante do modulo: banco sem empresa morta tem vies."""
    from quant.dados import cotahist
    monkeypatch.setattr(cotahist, "carregar",
                        lambda *a, **k: _cot({"JBSS3": 36.21}, data="2025-06-06"))
    r = {x["checagem"]: x for x in cf.checar_deslistadas()}
    assert r["deslistada JBSS3"]["estado"] == cf.OK
    assert r["deslistada BRFS3"]["estado"] == cf.FALHOU
    assert "SOBREVIVENCIA" in r["deslistada BRFS3"]["detalhe"].upper()


def test_banco_sem_cotacao_e_pulada_e_nao_reprova(monkeypatch):
    from quant.dados import cotahist
    monkeypatch.setattr(cotahist, "carregar", lambda *a, **k: pd.DataFrame())
    assert all(x["estado"] == cf.PULADA for x in cf.checar_deslistadas())
    assert all(x["estado"] == cf.PULADA for x in cf.checar_precos_de_referencia())


def test_fator_fora_da_tolerancia_reprova(monkeypatch):
    from quant.dados import nefin
    monkeypatch.setattr(nefin, "carregar_fatores", lambda *a, **k: pd.DataFrame({"x": [1.0]}))
    monkeypatch.setattr(nefin, "estatisticas", lambda *a, **k: {
        "WML": {"media_aa": 0.60, "t": 9.0},          # 60% a.a.: escala errada
        "HML": {"media_aa": 0.082, "t": 2.8},
        "SMB": {"media_aa": -0.008, "t": -0.2},
        "Rm_minus_Rf": {"media_aa": 0.038, "t": 0.8},
        "_periodo": {"ini": "2001-01-02", "fim": "2026-07-03", "dias": 6321}})
    r = {x["checagem"]: x for x in cf.checar_fatores_nefin()}
    assert r["fator WML"]["estado"] == cf.FALHOU
    assert "escala" in r["fator WML"]["detalhe"]
    assert r["fator HML"]["estado"] == cf.OK


def test_checagem_que_quebra_nao_derruba_as_outras(monkeypatch):
    monkeypatch.setattr(cf, "CHECAGENS", (("explode", lambda: 1 / 0),
                                          ("boa", lambda: [cf._res("boa", cf.OK, "")])))
    r = cf.rodar_tudo()
    assert {x["estado"] for x in r} == {cf.PULADA, cf.OK}
    assert any("a propria checagem falhou" in x["detalhe"] for x in r)


def test_saida_da_conferencia_e_serializavel(monkeypatch):
    monkeypatch.setattr(cf, "CHECAGENS", (("boa", lambda: [cf._res("boa", cf.OK, "tudo certo")]),))
    json.dumps(cf.rodar_tudo())


def test_codigo_de_saida_um_quando_algo_falha(monkeypatch, capsys):
    monkeypatch.setattr(cf, "CHECAGENS", (("ruim", lambda: [cf._res("ruim", cf.FALHOU, "x")]),))
    assert cf.main([]) == 1
    assert "NAO SIGA" in capsys.readouterr().out


def test_codigo_zero_e_proximo_passo_quando_tudo_passa(monkeypatch, capsys):
    monkeypatch.setattr(cf, "CHECAGENS", (("boa", lambda: [cf._res("boa", cf.OK, "x")]),))
    assert cf.main([]) == 0
    assert "replica_nefin" in capsys.readouterr().out


# ─────────────────────────────────────────────────────────────
# Cobertura: anos inteiros faltando no meio da serie
# ─────────────────────────────────────────────────────────────
def _precos(tmp_path, monkeypatch, anos, pregoes=246):
    from quant.dados import cotahist
    monkeypatch.setattr(cotahist, "caminho_parquet", _parquets(tmp_path, anos, pregoes))


def test_buraco_no_meio_da_serie_falha_e_nomeia_os_anos(tmp_path, monkeypatch):
    """Sem esta checagem, um banco sem 2012-2013 passa em tudo aqui e morre no gate, onde a
    mensagem culpa "o banco esta errado" sem dizer que faltam anos."""
    _precos(tmp_path, monkeypatch, [2008, 2009, 2010, 2011, 2014, 2015])
    r = cf.checar_cobertura_de_precos()
    assert r[0]["estado"] == cf.FALHOU
    assert "2012, 2013" in r[0]["detalhe"] and "--continuar" in r[0]["detalhe"]


def test_serie_seguida_passa(tmp_path, monkeypatch):
    _precos(tmp_path, monkeypatch, range(2008, 2015))
    r = cf.checar_cobertura_de_precos()
    assert [x["estado"] for x in r] == [cf.OK]
    assert "2008 a 2014" in r[0]["detalhe"]


def test_banco_sem_precos_e_pulada_e_nao_reprova(tmp_path, monkeypatch):
    """"Ainda nao carreguei" nao pode virar "banco errado": e a diferenca entre esperar e parar."""
    _precos(tmp_path, monkeypatch, [])
    r = cf.checar_cobertura_de_precos()
    assert [x["estado"] for x in r] == [cf.PULADA]


def test_serie_que_comeca_tarde_demais_para_o_gate_reprova(tmp_path, monkeypatch):
    """Sem buraco, mas comecando em 2015: o gate roda de 2008 e nao teria o que comparar."""
    _precos(tmp_path, monkeypatch, range(2015, 2020))
    r = cf.checar_cobertura_de_precos()
    assert [x["checagem"] for x in r] == ["cobertura de precos", "inicio da serie"]
    assert r[0]["estado"] == cf.OK and r[1]["estado"] == cf.FALHOU
    assert "2008" in r[1]["detalhe"]


def test_ano_truncado_e_acusado(tmp_path, monkeypatch):
    """Parquet com 12 pregoes num ano fechado e ano pela metade, nao ano carregado."""
    from quant.dados import cotahist
    caminho = _parquets(tmp_path, range(2008, 2013))
    _parquets(tmp_path, [2011], pregoes=12)
    monkeypatch.setattr(cotahist, "caminho_parquet", caminho)
    r = cf.checar_cobertura_de_precos()
    curto = [x for x in r if x["checagem"] == "ano 2011"]
    assert len(curto) == 1 and curto[0]["estado"] == cf.FALHOU
    assert "12 pregoes" in curto[0]["detalhe"]
