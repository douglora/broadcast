"""Swing: a evidencia decide quem usa capital; o gestor veta, prefere, nao compra na vespera do resultado e respeita tamanho e exposicao."""
import json
from datetime import date

import pytest

from quant.swing import evidencia, gestor, setups


def _dv(finalistas=()):
    """Resultados de descoberta+validacao no formato do arquivo da pesquisa: so as `finalistas` passaram."""
    out = {}
    for v in setups.variantes():
        ok = v["id"] in finalistas
        out[v["id"]] = {"descoberta": {"operacoes": 300, "expectativa_pct": 0.004 if ok else -0.002, "sharpe": 0.5 if ok else -0.2},
                        "validacao": {"operacoes": 120, "expectativa_pct": 0.004 if ok else -0.002, "sharpe": 0.5 if ok else -0.2},
                        "passa": {"descoberta": ok, "validacao": ok, "finalista": ok, "falhas_descoberta": [] if ok else ["expectativa líquida por operação não é positiva"],
                                  "falhas_validacao": []},
                        "sensibilidade_custo_leve": {"passaria_dv": False}}
    return out


def _cfg(**kw):
    c = dict(evidencia.PADRAO)
    c.update(kw)
    c["avisos"] = []
    return c


# ── evidencia ─────────────────────────────────────────────────
def test_nenhum_passou_tudo_e_so_medido_e_o_resumo_diz_com_todas_as_letras():
    v = evidencia.por_variante(_dv(), {"finalistas": [], "motivo": "x"}, _cfg())
    assert evidencia.com_capital(v) == [] and all(r["status"] == "so_medido" for r in v.values())
    assert "Nenhum dos 39 setups" in evidencia.resumo(v) and "só medido" in evidencia.resumo(v)


def test_passou_nas_tres_etapas_fica_medindo_ate_o_sharpe_deflacionado_chegar_a_095():
    dv = _dv(["C1.S1"])
    prova = {"C1.S1": {"passa_prova": True, "dsr_serie_inteira": 0.60, "prova": {"operacoes": 100}}}
    v = evidencia.por_variante(dv, prova, _cfg())
    assert v["C1.S1"]["status"] == "medindo" and evidencia.com_capital(v) == ["C1.S1"]
    prova["C1.S1"]["dsr_serie_inteira"] = 0.96
    assert evidencia.por_variante(dv, prova, _cfg())["C1.S1"]["status"] == "validado"


def test_reprovou_na_prova_ou_prova_nao_aberta_nao_tem_capital():
    dv = _dv(["C1.S1"])
    v = evidencia.por_variante(dv, {"C1.S1": {"passa_prova": False, "dsr_serie_inteira": 0.9, "prova": {}}}, _cfg())
    assert v["C1.S1"]["status"] == "so_medido" and "prova" in v["C1.S1"]["motivo"]
    v = evidencia.por_variante(dv, {"finalistas": []}, _cfg())
    assert v["C1.S1"]["status"] == "so_medido" and "prova ainda não foi aberta" in v["C1.S1"]["motivo"]


def test_liberacao_do_douglas_aparece_como_tal_nunca_como_validado():
    v = evidencia.por_variante(_dv(), {"finalistas": []}, _cfg(liberar=["D1.S1"], motivo_liberacao="quero ver rodar", decidido_em="2026-10-13"))
    assert v["D1.S1"]["status"] == "liberado" and "sem evidência de teste" in v["D1.S1"]["status_texto"]
    assert evidencia.com_capital(v) == ["D1.S1"] and "liberado(s) por decisão do Douglas" in evidencia.resumo(v)


def test_aceita_respeita_a_sobreposicao():
    v = evidencia.por_variante(_dv(["C1.S1"]), {"C1.S1": {"passa_prova": True, "dsr_serie_inteira": 0.5, "prova": {}}}, _cfg())
    assert evidencia.aceita(v, "C1", top=True, ibov_ok=False) == (True, "C1.S1")
    assert evidencia.aceita(v, "C1", top=False, ibov_ok=True) == (False, None)         # S1 so vale para a metade de cima do ranking
    assert evidencia.aceita(v, "E1", top=True, ibov_ok=True) == (False, None)


def test_config_do_douglas_dentro_de_limites(tmp_path):
    arq = tmp_path / "swing_config.json"
    arq.write_text(json.dumps({"risco": 0.01, "max_posicoes": 6, "teto_nome": 0.9, "capital": "abc", "liberar": ["A1.S0"]}))
    c = evidencia.config(str(arq))
    assert c["risco"] == 0.01 and c["max_posicoes"] == 6 and c["liberar"] == ["A1.S0"]
    assert c["teto_nome"] == evidencia.PADRAO["teto_nome"] and c["capital"] == evidencia.PADRAO["capital"]        # fora do limite / ilegivel: padrao
    assert len(c["avisos"]) == 2
    assert evidencia.config(str(tmp_path / "nao_existe.json"))["risco"] == 0.005


def test_a_pesquisa_de_verdade_deixou_todos_so_medidos():
    """Guarda do estado de 11/10/2026: se isto mudar, o Douglas precisa saber (a prova foi aberta ou ha liberacao)."""
    v = evidencia.por_variante(cfg=_cfg())
    assert len(v) == 39 and evidencia.com_capital(v) == []


# ── gestor ────────────────────────────────────────────────────
def _cand(ticker="AAAA3", setup="C1", preco=20.0, stop=1.5, adtv=2e7, top=True, ibov=True, alvo=3.0, prazo=10):
    return {"setup": setup, "familia": "c_rompimento", "rotulo": "x", "ticker": ticker, "sinal_em": "2026-10-09", "preco_ref": preco, "atr_real": stop / 2,
            "stop_dist": stop, "alvo_dist": alvo, "stop_ref": preco - stop, "alvo_ref": preco + alvo, "prazo": prazo, "adtv": adtv, "top": top, "ibov_ok": ibov,
            "porque": f"{ticker} rompeu", "numeros": {}}


def _visao(acoes=(), setores=()):
    return {"gerado": "2026-10-10T23:00:00-03:00", "validade_dias": 7, "macro": {}, "setores": list(setores), "acoes": list(acoes), "sem_analise": [], "avisos": []}


def _ctx(variantes=None, visao=None, terminal=None, **kw):
    c = {"hoje": date(2026, 10, 11), "entrada_em": date(2026, 10, 13), "patrimonio": 60_000.0, "exposicao_teto_rs": 60_000.0, "valor_aberto": 0.0, "n_abertas": 0,
         "tickers_abertos": set(), "variantes": variantes or evidencia.por_variante(_dv(["C1.S0", "D1.S0"]), {"C1.S0": {"passa_prova": True, "dsr_serie_inteira": .5, "prova": {}},
                                                                                    "D1.S0": {"passa_prova": True, "dsr_serie_inteira": .5, "prova": {}}}, _cfg()),
         "cfg": _cfg(), "visao": visao, "motivo_visao": "teste", "terminal": terminal}
    c.update(kw)
    return c


def test_sem_evidencia_ninguem_entra_com_capital_e_todas_viram_medida():
    sem = evidencia.por_variante(_dv(), {"finalistas": []}, _cfg())
    r = gestor.decidir([_cand("AAAA3"), _cand("BBBB3", setup="E1")], _ctx(variantes=sem))
    assert r["entradas"] == [] and [x["destino"] for x in r["linhas"]] == ["medida", "medida"]
    assert "só medido" in r["linhas"][0]["motivo"]


def test_com_evidencia_entra_com_tamanho_pelo_risco():
    r = gestor.decidir([_cand("AAAA3")], _ctx())
    e = r["entradas"][0]
    assert e["destino"] == "capital" and e["qtd"] == 200 and e["valor"] == 4000.0 and e["risco_rs"] == pytest.approx(300.0)
    assert e["variante"] == "C1.S0"


def test_mesa_veta_conviccao_menos_2_e_diz_porque():
    v = _visao([{"ticker": "AAAA3", "conviccao": -2, "risco": "calote do controlador"}, {"ticker": "BBBB3", "conviccao": 0}])
    r = gestor.decidir([_cand("AAAA3"), _cand("BBBB3")], _ctx(visao=v))
    assert [x["ticker"] for x in r["entradas"]] == ["BBBB3"]
    vetada = next(x for x in r["linhas"] if x["ticker"] == "AAAA3")
    assert vetada["destino"] == "recusada" and "vetada pela mesa" in vetada["motivo"] and "calote" in vetada["motivo"]


def test_mesa_prefere_conviccao_positiva_quando_falta_espaco():
    v = _visao([{"ticker": "AAAA3", "conviccao": 0}, {"ticker": "BBBB3", "conviccao": 2}, {"ticker": "CCCC3", "conviccao": 1}])
    cands = [_cand("AAAA3", adtv=9e7), _cand("BBBB3", adtv=1e6), _cand("CCCC3", adtv=5e6)]
    ctx = _ctx(visao=v)
    ctx["cfg"] = _cfg(max_posicoes=2)
    r = gestor.decidir(cands, ctx)
    assert [x["ticker"] for x in r["entradas"]] == ["BBBB3", "CCCC3"]                  # maior conviccao primeiro, mesmo menos liquida
    assert next(x for x in r["linhas"] if x["ticker"] == "AAAA3")["destino"] == "recusada"


def test_preferencia_de_setor_desempata():
    v = _visao([{"ticker": "AAAA3", "conviccao": 1, "setor": "bancos"}, {"ticker": "BBBB3", "conviccao": 1, "setor": "varejo"}],
               setores=[{"setor": "bancos", "inclinacao": -1}, {"setor": "varejo", "inclinacao": 2}])
    ctx = _ctx(visao=v)
    ctx["cfg"] = _cfg(max_posicoes=1)
    assert [x["ticker"] for x in gestor.decidir([_cand("AAAA3"), _cand("BBBB3")], ctx)["entradas"]] == ["BBBB3"]


def test_nao_compra_na_vespera_do_resultado_exceto_nos_setups_de_resultado():
    v = _visao([{"ticker": "AAAA3", "proximo_resultado": "2026-10-14"}, {"ticker": "BBBB3", "proximo_resultado": "2026-10-20"},
                {"ticker": "CCCC3", "proximo_resultado": "2026-10-13"}])
    r = gestor.decidir([_cand("AAAA3"), _cand("BBBB3"), _cand("CCCC3"), _cand("AAAA3", setup="D1")], _ctx(visao=v))
    por = {(x["ticker"], x["setup"]): x for x in r["linhas"]}
    assert por[("AAAA3", "C1")]["destino"] == "recusada" and "véspera de resultado (14/10/2026)" in por[("AAAA3", "C1")]["motivo"]
    assert por[("CCCC3", "C1")]["destino"] == "recusada"                               # resultado no proprio dia da entrada
    assert por[("BBBB3", "C1")]["destino"] == "capital"                                # resultado so em 20/10: longe da vespera
    assert por[("AAAA3", "D1")]["destino"] == "capital"                                # setup de resultado opera justamente a reacao


def test_data_do_resultado_vem_do_evento_binario_da_mesa_ou_do_terminal():
    v = _visao([{"ticker": "AAAA3", "evento_binario": {"data": "2026-10-14", "descricao": "Resultado do 3T26 (data confirmada)"}},
                {"ticker": "BBBB3", "evento_binario": {"data": "2026-10-14", "descricao": "2º turno da eleição"}}])
    r = gestor.decidir([_cand("AAAA3"), _cand("BBBB3"), _cand("CCCC3")], _ctx(visao=v, terminal=_Terminal({"CCCC3": {"eventos": {"proximo_resultado": "2026-10-13"}}})))
    por = {x["ticker"]: x for x in r["linhas"]}
    assert por["AAAA3"]["destino"] == "recusada" and por["BBBB3"]["destino"] == "capital" and por["CCCC3"]["destino"] == "recusada"


def test_sem_data_do_resultado_a_regra_nao_bloqueia_e_a_operacao_leva_a_nota():
    r = gestor.decidir([_cand("AAAA3")], _ctx(visao=_visao([])))
    assert r["entradas"][0]["nota_resultado"] == "data do resultado não informada"


class _Terminal:
    def __init__(self, fichas):
        self.fichas = fichas

    def ficha(self, t):
        if t == "QUEBRA3":
            raise RuntimeError("terminal fora do ar")
        return self.fichas.get(t)


def test_ficha_do_terminal_e_guardada_na_operacao_e_o_terminal_quebrado_nao_derruba():
    t = _Terminal({"AAAA3": {"nome": "Empresa A", "eventos": {}}})
    r = gestor.decidir([_cand("AAAA3"), _cand("QUEBRA3")], _ctx(terminal=t))
    assert [x["ticker"] for x in r["entradas"]] == ["AAAA3", "QUEBRA3"] or {x["ticker"] for x in r["entradas"]} == {"AAAA3", "QUEBRA3"}
    assert next(x for x in r["entradas"] if x["ticker"] == "AAAA3")["ficha"]["nome"] == "Empresa A"
    assert next(x for x in r["entradas"] if x["ticker"] == "QUEBRA3")["ficha"] == {}
    assert gestor.terminal_modulo() is None or hasattr(gestor.terminal_modulo(), "ficha")        # opcional: sem o modulo, None


def test_terminal_e_mesa_ausentes_viram_aviso_e_o_gestor_decide_igual():
    r = gestor.decidir([_cand("AAAA3")], _ctx(visao=None, terminal=None))
    assert len(r["entradas"]) == 1 and any("Terminal indisponível" in a for a in r["avisos"]) and any("Mesa sem visão" in a for a in r["avisos"])


def test_exposicao_nunca_passa_do_teto_do_dia_nem_o_numero_de_posicoes():
    cands = [_cand(f"X{i}A3", preco=20.0, stop=1.5) for i in range(30)]
    ctx = _ctx(exposicao_teto_rs=12_000.0)                                         # a regra do livro permite so R$ 12 mil hoje
    r = gestor.decidir(cands, ctx)
    assert sum(x["valor"] for x in r["entradas"]) <= 12_000.0 and len(r["entradas"]) == 3          # 3 x R$ 4.000
    r = gestor.decidir(cands, _ctx())
    assert len(r["entradas"]) == 10 and sum(x["valor"] for x in r["entradas"]) <= 60_000.0         # no maximo 10 posicoes


def test_exposicao_ja_acima_do_teto_nao_abre_posicao_nova():
    r = gestor.decidir([_cand("AAAA3")], _ctx(exposicao_teto_rs=20_000.0, valor_aberto=25_000.0, n_abertas=5))
    assert r["entradas"] == [] and "sem espaço" in r["linhas"][0]["motivo"]


def test_um_papel_uma_posicao_com_capital():
    r = gestor.decidir([_cand("AAAA3"), _cand("AAAA3", setup="D1"), _cand("BBBB3")], _ctx(tickers_abertos={"BBBB3"}))
    assert [x["ticker"] for x in r["entradas"]] == ["AAAA3"]                         # BBBB3 ja esta no livro; AAAA3 so entra uma vez
    assert sum(1 for x in r["linhas"] if x["destino"] == "recusada") == 2


def test_lote_que_nao_cabe_no_risco_e_recusado():
    r = gestor.decidir([_cand("AAAA3", preco=20.0, stop=10.0)], _ctx())                # 300/10 = 30 acoes: menos de um lote
    assert r["entradas"] == [] and "não cabe um lote" in r["linhas"][0]["motivo"]
