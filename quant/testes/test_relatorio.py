"""Criterios de kill e relatorio: o documento que decide continuar ou parar.

O que se testa aqui e que cada gatilho dispara no ponto certo, que slippage e giro exigem
persistencia (um mes ruim nao para o sistema), que criterio sem dado nao vira alarme falso,
e que o relatorio sempre diz a origem dos dados.
"""
import json

import numpy as np
import pandas as pd
import pytest

from quant import relatorio as rel


# ─────────────────────────────────────────────────────────────
# Criterios de kill
# ─────────────────────────────────────────────────────────────
def test_cada_criterio_dispara_no_gatilho():
    k = {x["criterio"]: x for x in rel.criterios_kill({"drawdown": 0.31})}
    assert k["drawdown"]["status"] == "disparado"
    k = {x["criterio"]: x for x in rel.criterios_kill({"drawdown": 0.21})}
    assert k["drawdown"]["status"] == "atencao"
    k = {x["criterio"]: x for x in rel.criterios_kill({"drawdown": 0.10})}
    assert k["drawdown"]["status"] == "ok"


def test_criterio_de_sentido_invertido_dispara_para_baixo():
    """Excesso sobre o CDI e universo disparam quando ficam ABAIXO do gatilho."""
    k = {x["criterio"]: x for x in rel.criterios_kill({"excesso_12m": -0.11, "universo": 90})}
    assert k["excesso_12m"]["status"] == "disparado"
    assert k["universo"]["status"] == "disparado"
    k = {x["criterio"]: x for x in rel.criterios_kill({"excesso_12m": 0.02, "universo": 150})}
    assert k["excesso_12m"]["status"] == "ok" and k["universo"]["status"] == "ok"
    k = {x["criterio"]: x for x in rel.criterios_kill({"universo": 110})}
    assert k["universo"]["status"] == "atencao"


def test_slippage_e_giro_exigem_persistencia():
    """Um mes de slippage alto e ruido; tres meses seguidos e sintoma."""
    um_mes = {x["criterio"]: x for x in rel.criterios_kill({"slippage": 2.5, "slippage_meses": 1})}
    assert um_mes["slippage"]["status"] == "atencao"
    tres = {x["criterio"]: x for x in rel.criterios_kill({"slippage": 2.5, "slippage_meses": 3})}
    assert tres["slippage"]["status"] == "disparado"
    giro = {x["criterio"]: x for x in rel.criterios_kill({"giro": 0.40, "giro_meses": 3})}
    assert giro["giro"]["status"] == "disparado"


def test_criterio_sem_medida_nao_vira_alarme_falso():
    k = rel.criterios_kill({})
    assert len(k) == len(rel.CRITERIOS)
    assert all(x["status"] == "ok" for x in k)
    assert all(x["valor"] is None for x in k)
    nan = {x["criterio"]: x for x in rel.criterios_kill({"drawdown": float("nan")})}
    assert nan["drawdown"]["status"] == "ok" and nan["drawdown"]["valor"] is None


def test_lista_de_disparados():
    k = rel.criterios_kill({"drawdown": 0.35, "universo": 80})
    assert set(rel.algum_disparado(k)) == {"drawdown", "universo"}
    assert rel.algum_disparado(rel.criterios_kill({})) == []
    assert rel.algum_disparado(None) == []


def test_criterios_sao_serializaveis():
    json.dumps(rel.criterios_kill({"drawdown": 0.1, "universo": 130}))


# ─────────────────────────────────────────────────────────────
# Desempenho
# ─────────────────────────────────────────────────────────────
def _serie(n=252, taxa=0.0004):
    dias = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame({"data": dias, "patrimonio": 100_000.0 * (1 + taxa) ** np.arange(n)})


def test_desempenho_calcula_retorno_e_excesso():
    s = _serie()
    cdi = pd.Series(0.0002, index=pd.DatetimeIndex(s["data"]))
    d = rel.desempenho(s, cdi=cdi)
    assert abs(d["retorno"] - (1.0004 ** 251 - 1)) < 1e-6
    assert abs(d["cdi"] - (1.0002 ** 252 - 1)) < 1e-6
    assert d["excesso"] > 0 and d["mdd"] == 0.0
    assert len(d["serie"]) == len(s) and d["serie"][0]["data"] == "2025-01-01"
    json.dumps(d)


def test_desempenho_sem_dado_devolve_esquema_com_nulos():
    d = rel.desempenho(None)
    assert d["retorno"] is None and d["serie"] == []
    json.dumps(d)
    assert rel.desempenho(pd.DataFrame({"data": [], "patrimonio": []}))["retorno"] is None


def test_desempenho_nao_devolve_nan():
    s = _serie(n=3)
    s.loc[1, "patrimonio"] = np.nan
    d = rel.desempenho(s)
    texto = json.dumps(d)
    assert "NaN" not in texto and "Infinity" not in texto


# ─────────────────────────────────────────────────────────────
# Relatorio
# ─────────────────────────────────────────────────────────────
PAINEL = {
    "gerado_em": "2026-09-08T21:00:00-03:00", "modo": "paper", "origem": "sintetico",
    "gate_fase1": {"passou": False, "detalhe": "nao rodado"},
    "modo_seguro": {"ativo": True, "motivos": ["COTAHIST do dia ausente"]},
    "carteira": {"patrimonio": 101234.56, "caixa": 26000.0, "exposicao": 0.743,
                 "n_posicoes": 22, "contratos_hedge": 1, "violacoes": ["piso infactivel"]},
    "fiscal": {"mes": "2026-09", "vendas_acoes_mes": 12000.0, "isencao_restante": 8000.0,
               "lucro_comum": 1500.0, "lucro_day_trade": 0.0,
               "prejuizo_acumulado_comum": 0.0, "prejuizo_acumulado_day_trade": 0.0,
               "darf": 225.0, "darf_vence": "2026-10-30", "aviso": "valide com contador"},
    "desempenho": {"retorno": 0.0123, "cdi": 0.0111, "excesso": 0.0012, "ibov": 0.02,
                   "vol": 0.14, "mdd": 0.031, "giro_mensal": 0.18, "custo_aa": 0.024},
    "kill": rel.criterios_kill({"drawdown": 0.031, "universo": 130}),
}


def test_relatorio_avisa_que_o_dado_e_sintetico():
    t = rel.montar(PAINEL)
    assert "Nenhum numero deste relatorio e resultado de estrategia" in t
    assert "NAO RODOU / NAO PASSOU" in t
    assert "Modo seguro ativo" in t and "COTAHIST do dia ausente" in t


def test_relatorio_com_dado_real_e_gate_aprovado_nao_avisa():
    bom = dict(PAINEL, origem="real", gate_fase1={"passou": True, "detalhe": "aprovado"},
               modo_seguro={"ativo": False, "motivos": []})
    t = rel.montar(bom)
    assert "Nenhum numero deste relatorio" not in t
    assert "Modo seguro ativo" not in t
    assert "passou" in t


def test_relatorio_traz_darf_carteira_e_limites():
    t = rel.montar(PAINEL)
    assert "R$ 225,00" in t and "2026-10-30" in t
    assert "22" in t and "piso infactivel" in t
    assert "0 meses de cobertura" in t                 # o aviso sobre o aluguel
    assert "contador" in t


def test_relatorio_grita_quando_um_criterio_dispara():
    ruim = dict(PAINEL, kill=rel.criterios_kill({"drawdown": 0.35}))
    t = rel.montar(ruim)
    assert "DISPARADO" in t and "drawdown" in t
    assert "perder muito dinheiro devagar" in t


def test_relatorio_de_painel_vazio_nao_quebra():
    t = rel.montar({})
    assert t.startswith("# Relatorio")
    assert rel.montar(None)


def test_grava_o_relatorio(tmp_path):
    caminho = rel.gravar(rel.montar(PAINEL), "mensal", str(tmp_path))
    assert open(caminho, encoding="utf-8").read().startswith("# Relatorio")


def test_main_sem_painel_devolve_dois(monkeypatch, tmp_path):
    monkeypatch.setattr(rel, "DIR_SAIDA", str(tmp_path))
    assert rel.main(["--periodo", "mensal"]) == 2


# ─────────────────────────────────────────────────────────────
# Formatacao: nem todo criterio e percentual
# ─────────────────────────────────────────────────────────────
def test_formato_por_criterio_evita_universo_virar_percentual():
    """33 nomes formatados como % viram '3.300%'. Cada criterio carrega o proprio formato."""
    k = {x["criterio"]: x for x in rel.criterios_kill({"universo": 33, "slippage": 1.8,
                                                       "drawdown": 0.12, "erros": 1})}
    assert k["universo"]["formato"] == "num" and k["drawdown"]["formato"] == "pct"
    assert k["slippage"]["formato"] == "x"
    assert rel.formatar_kill(k["universo"]["valor"], "num") == "33"
    assert rel.formatar_kill(k["drawdown"]["valor"], "pct") == "12.0%"
    assert rel.formatar_kill(k["slippage"]["valor"], "x") == "1.80x"


def test_todo_criterio_declara_um_formato_valido():
    for x in rel.criterios_kill({}):
        assert x["formato"] in ("pct", "x", "num"), x["criterio"]


def test_formatar_kill_trata_ausente_e_nan():
    assert rel.formatar_kill(None) == "--"
    assert rel.formatar_kill(float("nan"), "pct") == "--"
    assert rel.formatar_kill(2.0, "num") == "2"


def test_relatorio_mostra_universo_como_contagem():
    ruim = dict(PAINEL, kill=rel.criterios_kill({"universo": 33}))
    t = rel.montar(ruim)
    assert "| 33 | 100 |" in t and "3300" not in t


def test_formato_bool_vira_sim_ou_nao():
    """"Parametros intocados: 1" nao quer dizer nada para quem le a tela."""
    assert rel.formatar_kill(1, "bool") == "sim"
    assert rel.formatar_kill(0, "bool") == "nao"
    assert rel.formatar_kill(None, "bool") == "--"
