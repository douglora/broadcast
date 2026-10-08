"""A campanha de paper trading: a maquina que roda todo pregao e o placar da fase 4.

Tres coisas se testam aqui. Primeiro, que o laco FECHA: boleta vira fill, fill vira
posicao, posicao vira a boleta do dia seguinte. Segundo, que o placar nao mente — um
ensaio sobre mercado sintetico nunca "passa" na fase 4, diario de erros vazio nao vira
zero erro, e slippage favoravel nao vira reprovacao. Terceiro, os dois achados que o
primeiro ensaio produziu: preco de ordem vindo do painel MENSAL e roll que se repetia.

Roda sobre poucos papeis e poucas semanas, para a suite continuar rapida.
"""
import json
import os

import numpy as np
import pandas as pd
import pytest

from quant import rodar_diario as rd
from quant.execucao import campanha as cp


# ─────────────────────────────────────────────────────────────
# Configuracao e hash (criterio 5: nenhum parametro alterado)
# ─────────────────────────────────────────────────────────────
def test_hash_ignora_ordem_das_chaves_e_muda_com_o_valor():
    a = cp.hash_config({"n": 22, "cap": 0.06})
    b = cp.hash_config({"cap": 0.06, "n": 22})
    assert a == b
    assert cp.hash_config({"n": 23, "cap": 0.06}) != a


def test_config_da_estrategia_cobre_sinais_carteira_custos_e_boleta():
    c = cp.config_da_estrategia()
    assert set(c) == {"sinais", "carteira", "custos", "boleta"}
    assert c["carteira"]["n"] > 0 and c["sinais"]["pesos"]
    json.dumps(c, default=str)


def test_reabrir_campanha_com_parametro_mexido_levanta(tmp_path):
    arq = str(tmp_path / "config.json")
    cp.abrir_campanha({"n": 22}, caminho=arq)
    assert cp.abrir_campanha({"n": 22}, caminho=arq)["hash"] == cp.hash_config({"n": 22})
    with pytest.raises(RuntimeError) as e:
        cp.abrir_campanha({"n": 25}, caminho=arq)
    assert "zera o paper" in str(e.value)
    assert cp.estado_campanha(arq)["hash"] == cp.hash_config({"n": 22})   # nao sobrescreveu


def test_estado_de_campanha_inexistente_e_none(tmp_path):
    assert cp.estado_campanha(str(tmp_path / "nao_existe.json")) is None


# ─────────────────────────────────────────────────────────────
# Cobertura de calendario: rolls e rebalanceamentos
# ─────────────────────────────────────────────────────────────
def test_rebalanceamento_de_indice_conta_janeiro_maio_e_setembro():
    assert cp.rebalances_indice("2026-01-02", "2026-06-30") == 2      # jan e mai
    assert cp.rebalances_indice("2026-02-02", "2026-04-30") == 0
    assert cp.rebalances_indice("2026-08-01", "2026-09-30") == 1      # set
    assert cp.rebalances_indice("2026-06-30", "2026-01-02") == 0      # janela invertida


def test_roll_pendente_por_tres_pregoes_conta_como_um_roll():
    """ACHADO: enquanto o hedge so era gravado no dia em que havia fill, o motivo 'roll'
    reaparecia pregao apos pregao e a campanha registrava tres rolls onde houve um."""
    serie = ["abertura", "manter", "roll", "roll", "roll", "manter", "roll"]
    assert cp._blocos(serie, "roll") == 2
    assert cp._blocos([], "roll") == 0


# ─────────────────────────────────────────────────────────────
# Fita sintetica (so do ensaio)
# ─────────────────────────────────────────────────────────────
def _cotacoes():
    return pd.DataFrame([
        {"ticker": "AAAA3", "data": pd.Timestamp("2026-03-02"), "abe": 10.0, "max": 10.5,
         "min": 9.8, "fec": 10.2, "qtd": 100_000},
        {"ticker": "BBBB4", "data": pd.Timestamp("2026-03-02"), "abe": 30.0, "max": 31.0,
         "min": 29.5, "fec": 30.7, "qtd": 40_000},
    ])


def test_fita_sintetica_respeita_a_faixa_do_dia_e_fecha_no_fechamento():
    f = cp.fita_sintetica(_cotacoes(), "2026-03-02", n=20)
    assert list(f.columns) == list(cp.paper.COLUNAS_NEGOCIOS)
    a = f[f["ticker"] == "AAAA3"]
    assert len(a) == 20
    assert a["preco"].min() >= 9.8 - 1e-9 and a["preco"].max() <= 10.5 + 1e-9
    assert a["preco"].iloc[0] == 10.0 and a["preco"].iloc[-1] == 10.2
    assert abs(a["quantidade"].sum() - 100_000) < 1.0


def test_fita_de_dia_sem_pregao_vem_vazia_e_nao_levanta():
    assert len(cp.fita_sintetica(_cotacoes(), "2026-03-03")) == 0
    assert len(cp.fita_sintetica(None, "2026-03-02")) == 0


# ─────────────────────────────────────────────────────────────
# Diario de erros (criterio 3: depende do humano)
# ─────────────────────────────────────────────────────────────
def test_anota_erro_e_recusa_tipo_inventado(tmp_path):
    arq = str(tmp_path / "erros.csv")
    cp.registrar_erro("2026-03-02", "ordem_esquecida", "esqueci a venda de AAAA3", -120.0, arq)
    d = cp.carregar_erros(arq)
    assert len(d) == 1 and d.iloc[0]["tipo"] == "ordem_esquecida"
    assert float(d.iloc[0]["impacto"]) == -120.0
    with pytest.raises(ValueError):
        cp.registrar_erro("2026-03-02", "cachorro_comeu", "x", 0.0, arq)


def test_erro_repetido_nao_duplica(tmp_path):
    arq = str(tmp_path / "erros.csv")
    for _ in range(3):
        cp.registrar_erro("2026-03-02", "preco_errado", "digitei 10,20 em vez de 12,00", 0, arq)
    assert len(cp.carregar_erros(arq)) == 1


def test_diario_vazio_nao_afirma_zero_erro():
    """Diario vazio pode ser mes limpo ou mes em que ninguem anotou. O criterio nao passa
    de graca: sem mes assinado `meses_sem_erro` fica None e o aviso diz por que."""
    assert cp.meses_sem_erro(cp._vazio(cp.COLUNAS_ERRO)) is None
    a = cp.avaliar(cp._vazio(cp.COLUNAS_SESSAO), None)
    assert a["itens"]["meses_sem_erro"]["valor"] is None
    assert not a["itens"]["meses_sem_erro"]["ok"]
    assert any("ninguem anotou" in x for x in a["avisos"])


def test_so_mes_assinado_conta_como_mes_sem_erro():
    """Quem assina que o mes foi conferido e o humano; o programa nao tem como saber."""
    erros = pd.DataFrame([{"data": "2026-01-15", "tipo": "outro", "descricao": "x", "impacto": 0}])
    assinados = ["2026-01", "2026-02", "2026-03", "2026-04"]
    assert cp.meses_sem_erro(erros, ate="2026-04-30", conferidos=assinados) == 3   # fev, mar, abr
    assert cp.meses_sem_erro(erros, ate="2026-01-31", conferidos=assinados) == 0
    # mes rodado mas nao assinado nao conta
    assert cp.meses_sem_erro(erros, ate="2026-04-30", conferidos=["2026-03"]) == 1


def test_mes_corrente_ainda_rodando_nao_zera_a_sequencia():
    """Em 15 de junho ninguem assinou junho ainda; abril e maio limpos e assinados valem 2.
    Mas se junho JA tem erro anotado, ele quebra a sequencia na hora."""
    limpo = cp.meses_sem_erro(cp._vazio(cp.COLUNAS_ERRO), ate="2026-06-15",
                              conferidos=["2026-04", "2026-05"])
    assert limpo == 2
    erro_no_mes = pd.DataFrame([{"data": "2026-06-10", "tipo": "ordem_errada",
                                 "descricao": "x", "impacto": 0}])
    assert cp.meses_sem_erro(erro_no_mes, ate="2026-06-15",
                             conferidos=["2026-04", "2026-05"]) == 0


def test_assinatura_de_mes_grava_e_nao_duplica(tmp_path):
    arq = str(tmp_path / "conf.csv")
    cp.conferir_mes("2026-03", "rotina rodada todo dia, nenhuma ordem errada", arq)
    cp.conferir_mes("2026-03", "reconferido", arq)
    cp.conferir_mes("2026-04", "", arq)
    d = cp.carregar_conferencias(arq)
    assert list(d["mes"]) == ["2026-03", "2026-04"] and len(d) == 2
    assert d.iloc[0]["observacao"] == "reconferido"
    assert len(cp.carregar_conferencias(str(tmp_path / "nada.csv"))) == 0


# ─────────────────────────────────────────────────────────────
# Frescor: a licenca do ensaio, e so dele
# ─────────────────────────────────────────────────────────────
def test_no_ensaio_o_mercado_sintetico_carimba_o_bdi():
    dados = {"origem": "sintetico", "cotacoes": _cotacoes(), "sinais": None, "cdi": None}
    f = cp.frescor_do_dia(dados, "2026-03-02")
    assert f["cotahist"]["data"] == "2026-03-02" and f["bdi"]["data"] == "2026-03-02"


def test_com_dado_real_bdi_ausente_continua_bloqueando():
    """A licenca do ensaio nao pode vazar para producao: sem BDI de verdade, a boleta para."""
    from quant.execucao import boleta as bo
    dados = {"origem": "real", "cotacoes": _cotacoes(), "sinais": None, "cdi": None}
    f = cp.frescor_do_dia(dados, "2026-03-02")
    assert f["bdi"]["data"] is None and f["bdi"]["ok"] is False
    ativo, motivos = bo.modo_seguro(f, gate_passou=True)
    assert ativo and any("BDI" in m for m in motivos)


# ─────────────────────────────────────────────────────────────
# Avaliacao dos criterios
# ─────────────────────────────────────────────────────────────
def _sessoes(n=70, ini="2026-01-02", execucao=0.9, slip_vwap=8.0, hedge="manter"):
    dias = pd.bdate_range(ini, periods=n)
    linhas = []
    for i, d in enumerate(dias):
        linhas.append({c: None for c in cp.COLUNAS_SESSAO})
        linhas[-1].update({"data": str(d.date()), "boleta": d.strftime("%Y%m%d"),
                           "emitida": True, "motivo_bloqueio": "", "n_ordens": 2,
                           "qtd_pedida": 100.0, "qtd_executada": 100.0 * execucao,
                           "taxa_execucao": execucao, "financeiro": 3000.0,
                           "slippage_bps": -5.0, "slippage_vwap_bps": slip_vwap,
                           "custo_estimado": 20.0, "custo_realizado": 18.0, "n_fills": 2,
                           "patrimonio": 100_000.0, "n_posicoes": 20, "contratos": 1,
                           "hedge_motivo": hedge if i == 10 else "manter", "origem": "real"})
    return pd.DataFrame(linhas, columns=cp.COLUNAS_SESSAO)


def _erros_zerados():
    return cp._vazio(cp.COLUNAS_ERRO)


def _assinados(ini="2026-01", n=6):
    return [str(pd.Period(ini, "M") + i) for i in range(n)]


def test_ensaio_nunca_passa_na_fase_4():
    """Mesmo com todos os numeros bonitos: passar num ensaio sintetico nao e passar."""
    s = _sessoes(hedge="roll")
    s["origem"] = "ensaio"
    a = cp.avaliar(s, _erros_zerados(), modelado_bps=40.0, origem="ensaio",
                   conferidos=_assinados())
    assert a["itens"]["execucao"]["ok"] and a["itens"]["slippage"]["ok"]
    assert a["passou"] is False
    assert any("nao e a fase 4" in x for x in a["avisos"])


def test_campanha_real_completa_passa():
    s = _sessoes(n=70, hedge="roll")
    a = cp.avaliar(s, _erros_zerados(), modelado_bps=40.0, conferidos=_assinados(),
                   config_inicial={"n": 22}, config_atual={"n": 22}, origem="real")
    assert a["reprovados"] == [] and a["passou"] is True


def test_execucao_abaixo_de_60_por_cento_reprova():
    a = cp.avaliar(_sessoes(execucao=0.45, hedge="roll"), _erros_zerados(),
                   modelado_bps=40.0, origem="real", conferidos=_assinados())
    assert "execucao" in a["reprovados"]


def test_slippage_favoravel_nao_reprova():
    """Slippage e medido contra o VWAP e positivo e desfavoravel. Executar MELHOR que o
    modelado nao pode virar reprovacao — era o que o abs() fazia."""
    a = cp.avaliar(_sessoes(slip_vwap=-90.0, hedge="roll"), _erros_zerados(),
                   modelado_bps=40.0, origem="real", conferidos=_assinados())
    assert a["itens"]["slippage"]["valor"] == 0.0 and a["itens"]["slippage"]["ok"]
    ruim = cp.avaliar(_sessoes(slip_vwap=90.0, hedge="roll"), _erros_zerados(),
                      modelado_bps=40.0, origem="real", conferidos=_assinados())
    assert not ruim["itens"]["slippage"]["ok"]      # 90/40 = 2,25x, acima de 1,5x


def test_sem_custo_modelado_o_slippage_passa_por_omissao_mas_avisa():
    a = cp.avaliar(_sessoes(hedge="roll"), _erros_zerados(), modelado_bps=None,
                   origem="real", conferidos=_assinados())
    assert a["itens"]["slippage"]["valor"] is None and a["itens"]["slippage"]["ok"]
    assert any("passa por omissao" in x for x in a["avisos"])


def test_um_erro_operacional_reprova_o_criterio():
    erros = pd.DataFrame([{"data": "2026-02-10", "tipo": "ordem_errada",
                           "descricao": "comprei em vez de vender", "impacto": -300.0}])
    a = cp.avaliar(_sessoes(hedge="roll"), erros, modelado_bps=40.0, origem="real",
                   conferidos=_assinados())
    assert "erros" in a["reprovados"] and a["itens"]["erros"]["valor"] == 1


def test_parametro_alterado_no_meio_da_campanha_reprova():
    a = cp.avaliar(_sessoes(hedge="roll"), _erros_zerados(), modelado_bps=40.0,
                   conferidos=_assinados(),
                   config_inicial={"n": 22}, config_atual={"n": 25}, origem="real")
    assert "parametros_estaveis" in a["reprovados"] and a["passou"] is False


def test_campanha_curta_reprova_por_tempo_de_calendario():
    """3 a 6 meses e tempo de CALENDARIO: nao da para comprimir rodando mais rapido."""
    a = cp.avaliar(_sessoes(n=20, hedge="roll"), _erros_zerados(), modelado_bps=40.0,
                   origem="real", conferidos=_assinados())
    assert "sessoes" in a["reprovados"] and "meses" in a["reprovados"]


def test_sem_roll_e_sem_rebalanceamento_reprova():
    a = cp.avaliar(_sessoes(n=40, ini="2026-02-02"), _erros_zerados(), modelado_bps=40.0,
                   origem="real", conferidos=_assinados())
    assert "rolls" in a["reprovados"] and "rebalances_indice" in a["reprovados"]


def test_avaliacao_de_campanha_vazia_nao_levanta():
    a = cp.avaliar(None, None)
    assert a["passou"] is False and len(a["itens"]) == 9


# ─────────────────────────────────────────────────────────────
# Resumo: o bloco `paper` do painel
# ─────────────────────────────────────────────────────────────
def test_resumo_e_json_nativo_sem_nan():
    s = _sessoes(hedge="roll")
    s.loc[3, "slippage_vwap_bps"] = np.nan
    r = cp.resumo(s, _erros_zerados(), conferidos=_assinados())
    texto = json.dumps(r)
    assert "NaN" not in texto and "Infinity" not in texto
    assert r["sessoes"] == 70 and r["rolls"] == 1
    assert all(c["formato"] in ("pct", "x", "num", "bool") for c in r["criterios"])


def test_resumo_de_campanha_vazia_tem_o_esquema():
    r = cp.resumo(None)
    assert r["sessoes"] == 0 and r["primeira"] is None and r["passou"] is False
    json.dumps(r)


# ─────────────────────────────────────────────────────────────
# Disco
# ─────────────────────────────────────────────────────────────
def test_registro_de_sessoes_nao_duplica_o_mesmo_pregao(tmp_path):
    arq = str(tmp_path / "sessoes.csv")
    s = _sessoes(n=5)
    cp.registrar_sessoes(s, arq)
    cp.registrar_sessoes(s, arq)
    lido = cp.carregar_sessoes(arq)
    assert len(lido) == 5 and list(lido.columns) == cp.COLUNAS_SESSAO


def test_carregar_sessoes_inexistente_devolve_vazio(tmp_path):
    assert len(cp.carregar_sessoes(str(tmp_path / "nada.csv"))) == 0


# ─────────────────────────────────────────────────────────────
# O laco fecha: ensaio ponta a ponta sobre o mercado sintetico
# ─────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def ensaio():
    fim = pd.Timestamp("2026-03-31")
    dados = rd.carregar_sintetico(seed=7, n_empresas=30, anos=2, ate=fim)
    sessoes = cp.rodar_campanha(dados, "2026-03-02", fim, capital=100_000.0,
                                gate_passou=True, origem="ensaio")
    return dados, sessoes


def test_ensaio_emite_boleta_todo_pregao(ensaio):
    _dados, s = ensaio
    assert len(s) >= 15
    assert s["emitida"].astype(bool).all()


def test_ensaio_executa_ordens_e_monta_posicao(ensaio):
    """O teste que prova que o laco fecha: boleta -> fill -> posicao."""
    _dados, s = ensaio
    assert int(s["n_fills"].sum()) > 0
    assert int(s["n_posicoes"].iloc[-1]) > 0
    assert float(s["financeiro"].astype(float).sum()) > 0


def test_ordem_e_precificada_no_fechamento_do_dia_e_nao_no_painel_mensal(ensaio):
    """ACHADO do primeiro ensaio: com o preco vindo do painel MENSAL, a ordem saia com
    limite de semanas atras e nao executava nunca. Se voltar, a taxa de execucao despenca."""
    _dados, s = ensaio
    com_ordem = s[s["n_ordens"].astype(float) > 0]
    assert len(com_ordem) > 0
    taxa = pd.to_numeric(com_ordem["taxa_execucao"], errors="coerce").mean()
    assert taxa > 0.5, f"taxa media de {taxa:.0%}: o preco da ordem provavelmente esta velho"


def test_hedge_e_gravado_mesmo_num_pregao_sem_ordem_de_acao(ensaio):
    _dados, s = ensaio
    sem_ordem = s[s["n_ordens"].astype(float) == 0]
    if len(sem_ordem):
        assert (sem_ordem["contratos"].astype(float) >= 0).all()
    assert cp._blocos(s["hedge_motivo"], "abertura") == 1


def test_sessao_do_ensaio_e_serializavel(ensaio):
    _dados, s = ensaio
    json.dumps(cp.resumo(s, None))


# ─────────────────────────────────────────────────────────────
# A sessao real: recusa em vez de inventar
# ─────────────────────────────────────────────────────────────
def test_sessao_real_sem_banco_recusa(monkeypatch):
    monkeypatch.setattr(rd, "carregar_real", lambda ate=None, **k: None)
    registro, msg = cp.rodar_do_dia("2026-09-08", registrar=False)
    assert registro is None and "dado real" in msg


def test_sessao_real_sem_a_fita_do_dia_recusa(monkeypatch):
    """Fill imaginado entra no placar da fase 4 e contamina a decisao de por dinheiro."""
    monkeypatch.setattr(rd, "carregar_real",
                        lambda ate=None, **k: {"origem": "real", "cotacoes": _cotacoes()})
    monkeypatch.setattr(cp.paper, "carregar_negocios",
                        lambda data, **k: cp._vazio(cp.paper.COLUNAS_NEGOCIOS))
    registro, msg = cp.rodar_do_dia("2026-09-08", registrar=False)
    assert registro is None and "negocio-a-negocio" in msg
