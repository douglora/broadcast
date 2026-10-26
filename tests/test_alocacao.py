"""Motor de asset allocation (ferramentas/local/alocacao): sem rede.

Os testes que leem o cache do terminal (curva DI, NTN-B, historico) pulam sozinhos quando ele nao existe.
Dado de cliente de teste vai para uma pasta temporaria (nunca ~/Documents/Asset Allocation).
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_DIR = os.path.join(RAIZ, "ferramentas", "local")
for p in (RAIZ, LOCAL_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from alocacao import alinha as A  # noqa: E402
from alocacao import cliente as CL  # noqa: E402
from alocacao import config as C  # noqa: E402
from alocacao import fiscal as F  # noqa: E402
from alocacao import formato as FM  # noqa: E402
from alocacao import implementacao as I  # noqa: E402
from alocacao import otimiza as O  # noqa: E402
from alocacao import simula as S  # noqa: E402

TEM_MERCADO = (C.TERMINAL / "cache" / "out" / "rf.json").exists()
precisa_mercado = pytest.mark.skipif(not TEM_MERCADO, reason="cache do terminal nao existe nesta maquina")


@pytest.fixture()
def clientes(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CLIENTES", tmp_path)
    monkeypatch.setattr(C, "CACHE", tmp_path / "_mercado")
    return tmp_path


def _cov_sintetica():
    """Covariancia plausivel: renda fixa com 1% de vol, RV com 18%, FII 12%, ouro 15%, cripto 60%."""
    vols = {"caixa": 0.002, "pos_isenta": 0.004, "ipca_isenta": 0.03, "pre_isenta": 0.035, "pos_trib": 0.004,
            "ipca_trib": 0.05, "pre_trib": 0.06, "mm": 0.05, "vgbl": 0.06, "rv_br": 0.22, "fii": 0.13,
            "rv_int": 0.17, "alt_ouro": 0.16, "cripto": 0.65}
    v = np.array([vols[c] for c in C.IDS])
    corr = np.full((len(v), len(v)), 0.25)
    np.fill_diagonal(corr, 1.0)
    return pd.DataFrame(corr * np.outer(v, v), index=C.IDS, columns=C.IDS)


def _mu_sintetico():
    ret = {"caixa": 0.113, "pos_isenta": 0.125, "ipca_isenta": 0.120, "pre_isenta": 0.118, "pos_trib": 0.108,
           "ipca_trib": 0.112, "pre_trib": 0.108, "mm": 0.112, "vgbl": 0.105, "rv_br": 0.150, "fii": 0.125,
           "rv_int": 0.130, "alt_ouro": 0.100, "cripto": 0.160}
    return np.array([ret[c] for c in C.IDS])


# --- configuracao --------------------------------------------------------------------------------
@pytest.mark.parametrize("perfil", list(C.PERFIS))
def test_modelo_do_perfil_soma_100_e_cabe_nas_bandas(perfil):
    w = np.array([C.NEUTRO[perfil][c] for c in C.IDS])
    assert w.sum() == pytest.approx(1.0, abs=1e-9)
    b = C.bandas_do_perfil(perfil)
    for i, cid in enumerate(C.IDS):
        lo, hi = b[cid]
        assert lo - 1e-9 <= w[i] <= hi + 1e-9, f"{perfil}/{cid}: {w[i]} fora de {lo}-{hi}"


def test_perfil_desconhecido_da_erro_claro():
    with pytest.raises(ValueError, match="perfil desconhecido"):
        C.bandas_do_perfil("kamikaze")


# --- fiscal --------------------------------------------------------------------------------------
def test_tabela_regressiva_cai_com_o_prazo():
    assert F.aliquota_regressiva(0.4) == pytest.approx(0.225)      # ate 180 dias
    assert F.aliquota_regressiva(0.7) == pytest.approx(0.20)       # 181 a 360 dias
    assert F.aliquota_regressiva(1.5) == pytest.approx(0.175)
    assert F.aliquota_regressiva(5) == pytest.approx(0.15)


def test_liquido_isento_nao_muda_e_regressivo_cai():
    assert F.liquido(0.12, "isento", 5) == pytest.approx(0.12)
    assert F.liquido(0.12, "regressivo", 5) == pytest.approx(0.12 * 0.85, rel=0.05)
    assert F.liquido(0.12, "regressivo", 5) < F.liquido(0.12, "isento", 5)
    # prazo mais longo => alíquota menor => líquido maior
    assert F.liquido(0.12, "regressivo", 5) > F.liquido(0.12, "regressivo", 0.5)


def test_previdencia_regressiva_chega_a_10():
    assert F.aliquota_previdencia(11) == pytest.approx(0.10)
    assert F.aliquota_previdencia(2) > F.aliquota_previdencia(11)


# --- formato -------------------------------------------------------------------------------------
def test_formato_brasileiro():
    assert FM.num(1234567.891, 2) == "1.234.567,89"
    assert FM.pct(0.1234) == "12,3%"
    assert FM.pp(0.0123) == "+1,2 p.p."
    assert FM.pp(-0.005) == "-0,5 p.p."
    assert FM.brl(5000000) == "R$ 5.000.000"
    assert FM.mi(8_250_000) == "R$ 8,2 mi" or FM.mi(8_250_000) == "R$ 8,3 mi"
    assert FM.mi(450_000) == "R$ 450 mil"


def test_probabilidade_sem_falsa_certeza():
    assert FM.prob(1.0) == "mais de 99%"
    assert FM.prob(0.9999) == "mais de 99%"
    assert FM.prob(0.0) == "menos de 1%"
    assert FM.prob(0.87) == "87%"
    assert FM.pcts(0.036) == "+3,6%"
    assert FM.pcts(-0.074) == "-7,4%"


# --- otimizador ----------------------------------------------------------------------------------
@pytest.mark.parametrize("perfil", list(C.PERFIS))
def test_candidatos_respeitam_bandas_soma_e_risco(perfil):
    r = O.restricoes_do_perfil(perfil)
    assert O.viabilidade(r) is None
    cov, mu = _cov_sintetica(), _mu_sintetico()
    cands = O.candidatos(mu, cov, r)
    assert [c["cod"] for c in cands] == ["A", "B", "C"]
    rv_idx = [C.IDS.index(c) for c in C.GRUPO_RV]
    for c in cands:
        assert c["w"] is not None, c["avisos"]
        w = c["w"]
        assert w.sum() == pytest.approx(1.0, abs=1e-6)
        assert np.all(w >= r.lo - 1e-6) and np.all(w <= r.hi + 1e-6)
        assert w[rv_idx].sum() <= r.rv_max + 1e-6
        assert np.all(w >= -1e-12)
    # a defensiva nao pode ter mais risco que a ancorada
    assert cands[2]["vol"] <= cands[0]["vol"] + 1e-6


def test_otimizador_respeita_orcamento_de_vol_quando_cabe():
    r = O.restricoes_do_perfil("moderado")
    res = O.otimizar(_mu_sintetico(), _cov_sintetica(), r)
    assert res["w"] is not None
    if res["ok"]:
        assert O.vol(res["w"], _cov_sintetica().values) <= r.vol_max + 1e-6


def test_bandas_impossiveis_viram_mensagem_e_nao_excecao():
    r = O.restricoes_do_perfil("moderado", override={"caixa": (0.9, 0.95), "rv_br": (0.5, 0.6)})
    motivo = O.viabilidade(r)
    assert motivo and "somam" in motivo
    res = O.otimizar(_mu_sintetico(), _cov_sintetica(), r)
    assert res["w"] is None and not res["ok"]


def test_arredondar_mantem_soma_100():
    r = O.restricoes_do_perfil("moderado")
    res = O.otimizar(_mu_sintetico(), _cov_sintetica(), r)
    w = O.arredondar(res["w"], r.lo, r.hi)
    assert w.sum() == pytest.approx(1.0, abs=1e-9)
    # passo de 0,5 p.p.
    assert np.allclose(np.round(w / 0.005) * 0.005, w, atol=1e-9)


def test_arredondar_com_banda_fora_da_grade_soma_exatamente_100():
    """Piso de 9,6% (dolar) nao e multiplo de 0,5 p.p.: a demo de 26/10 saiu com 100,1% e caixa R$ 539 abaixo da reserva."""
    r = O.restricoes_do_perfil("moderado", override={"rv_int": (0.096, 0.15), "caixa": (0.09, 0.20)})
    for cand in O.candidatos(_mu_sintetico(), _cov_sintetica(), r):
        w = cand["w"]
        assert w.sum() == pytest.approx(1.0, abs=1e-9), cand["cod"]
        assert w[C.IDS.index("caixa")] >= 0.09 - 1e-9
        assert w[C.IDS.index("rv_int")] >= 0.096 - 1e-9
        assert np.all(w >= r.lo - 1e-9) and np.all(w <= r.hi + 1e-9)


def test_dict_ida_e_volta():
    w = np.array([C.NEUTRO["moderado"][c] for c in C.IDS])
    assert np.allclose(O.de_dict(O.para_dict(w)), w)


# --- simulacao -----------------------------------------------------------------------------------
def _plano():
    return S.Plano(pl=5_000_000, horizonte=5, aporte_mensal=10_000, meta=7_000_000)


def test_simulacao_e_reprodutivel_com_a_mesma_semente():
    cov, mu = _cov_sintetica(), _mu_sintetico()
    w = np.array([C.NEUTRO["moderado"][c] for c in C.IDS])
    a = S.simular(w, mu, cov.values, _plano(), 0.04, n=1500, benchmark=0.10)
    b = S.simular(w, mu, cov.values, _plano(), 0.04, n=1500, benchmark=0.10)
    for k, v in a.items():
        if isinstance(v, (int, float)):
            assert v == pytest.approx(b[k]), k


def test_simulacao_mais_risco_abre_o_leque():
    cov, mu = _cov_sintetica(), _mu_sintetico()
    seguro = np.zeros(len(C.IDS))
    seguro[C.IDS.index("pos_isenta")] = 1.0
    arrojado = np.array([C.NEUTRO["arrojado"][c] for c in C.IDS])
    a = S.simular(seguro, mu, cov.values, _plano(), 0.04, n=1500)
    b = S.simular(arrojado, mu, cov.values, _plano(), 0.04, n=1500)
    assert b["final_real"][95] - b["final_real"][5] > a["final_real"][95] - a["final_real"][5]
    assert b["mdd_p95"] < a["mdd_p95"]                       # queda maxima pior (mais negativa)
    for s in (a, b):
        assert s["final_real"][5] <= s["final_real"][50] <= s["final_real"][95]
        assert 0.0 <= s["p_meta"] <= 1.0


def test_retorno_necessario_sem_meta_e_none():
    p = S.Plano(pl=1_000_000, horizonte=5, meta=None)
    assert S.retorno_necessario(p, 0.04) is None


def test_retorno_necessario_cresce_com_a_meta():
    baixo = S.retorno_necessario(S.Plano(pl=1_000_000, horizonte=5, meta=1_200_000), 0.04)
    alto = S.retorno_necessario(S.Plano(pl=1_000_000, horizonte=5, meta=2_500_000), 0.04)
    assert baixo is not None and alto is not None and alto > baixo


# --- transicao / implementacao -------------------------------------------------------------------
def test_transicao_com_carteira_atual():
    alvo = np.array([C.NEUTRO["moderado"][c] for c in C.IDS])
    atual = np.zeros(len(C.IDS))
    atual[C.IDS.index("caixa")] = 0.5
    atual[C.IDS.index("pos_trib")] = 0.5
    t = I.transicao(alvo, atual, 1_000_000)
    acoes = {p["classe"]: p["acao"] for p in t["passos"]}
    assert acoes["pos_trib"] == "reduzir"
    assert acoes["pos_isenta"] == "aumentar"
    assert t["giro"] == pytest.approx(np.abs(alvo - atual).sum() / 2.0)
    assert all(p["reais"] > 0 and p["parcelas"] >= 1 for p in t["passos"])


def test_transicao_sem_carteira_atual_e_dinheiro_novo():
    """Bug de 26/10/2026: sem carteira atual aparecia 'reduzir Caixa 90 p.p.'. Dinheiro novo so tem 'aumentar'."""
    alvo = np.array([C.NEUTRO["moderado"][c] for c in C.IDS])
    t = I.transicao(alvo, None, 5_000_000)
    assert t["passos"], "tem de haver passos"
    assert all(p["acao"] == "aumentar" for p in t["passos"])
    assert "caixa" not in {p["classe"] for p in t["passos"]}
    assert t["giro"] == pytest.approx(1.0 - alvo[C.IDS.index("caixa")])


def test_dia_de_choque_atrasa_a_trava_de_taxa():
    alvo = np.array([C.NEUTRO["moderado"][c] for c in C.IDS])
    normal = {p["classe"]: p for p in I.transicao(alvo, None, 1e6, em_choque=False)["passos"]}
    choque = {p["classe"]: p for p in I.transicao(alvo, None, 1e6, em_choque=True)["passos"]}
    assert normal["ipca_isenta"]["janela"] != choque["ipca_isenta"]["janela"]


def test_faixa_de_rebalanceamento_entre_1_5_e_5_pontos():
    assert I.faixa_rebalanceamento(0.01) == pytest.approx(0.015)
    assert I.faixa_rebalanceamento(0.10) == pytest.approx(0.02)
    assert I.faixa_rebalanceamento(0.60) == pytest.approx(0.05)


def test_esteira_de_liquidez_guarda_o_dinheiro_antes_da_data():
    ev = [{"mes": 30, "valor": -400_000, "desc": "Entrada do apartamento"}, {"mes": 6, "valor": 100_000}]
    e = I.esteira_de_liquidez(ev, 8_000_000, 0.04)
    assert len(e) == 1                                   # so retirada (valor < 0) entra
    assert e[0]["valor_futuro"] > 400_000                # corrigido pela inflacao
    assert e[0]["marcos"][-1]["quando"] == "mês 30"
    assert any(m["pct"] == 1.0 for m in e[0]["marcos"])


def test_trilha_reserva_caixa_no_ano_da_retirada():
    alvo = np.array([C.NEUTRO["moderado"][c] for c in C.IDS])
    ev = [{"mes": 30, "valor": -800_000}]
    t = I.trilha(alvo, 5_000_000, 0, 0.10, 6, 0.04, ev)
    caixa = C.IDS.index("caixa")
    assert t["composicao"][2, caixa] > t["composicao"][0, caixa]       # perto da data, mais caixa
    assert np.allclose(t["composicao"].sum(axis=1), 1.0)


# --- cliente e ficha -----------------------------------------------------------------------------
def test_ficha_nova_grava_e_atualiza(clientes):
    CL.novo("Marina Teste", **{"pessoa.idade": 48, "patrimonio.financeiro": 5_000_000})
    assert CL.existe("Marina Teste")
    assert "marina-teste" in CL.listar()
    f = CL.ler_ficha("Marina Teste")
    assert f["pessoa"]["idade"] == 48
    CL.atualizar("Marina Teste", {"risco.perfil": "moderado", "objetivo.prazo_anos": 8})
    f = CL.ler_ficha("Marina Teste")
    assert f["risco"]["perfil"] == "moderado" and f["objetivo"]["prazo_anos"] == 8
    assert CL.perfil_da_ficha(f) == "moderado"
    assert CL.horizonte_da_ficha(f) == pytest.approx(8.0)


def test_ficha_inexistente_da_erro_que_ensina_o_comando(clientes):
    with pytest.raises(Exception, match="alocar.py novo"):
        CL.ler_ficha("Fulano")


def test_proposta_versiona_e_recusa_soma_errada(clientes):
    CL.novo("Marina Teste")
    p1 = CL.gravar_proposta("Marina Teste", {"caixa": 0.5, "pos_isenta": 0.5}, "teste")
    p2 = CL.gravar_proposta("Marina Teste", {"caixa": 0.4, "pos_isenta": 0.6}, "teste")
    assert (p1["versao"], p2["versao"]) == (1, 2)
    assert CL.ler_proposta("Marina Teste")["pesos"]["pos_isenta"] == pytest.approx(0.6)
    with pytest.raises(ValueError, match="100%"):
        CL.gravar_proposta("Marina Teste", {"caixa": 0.5, "pos_isenta": 0.2}, "teste")


def test_visao_valida_classe_e_pode_ser_desativada(clientes):
    CL.novo("Marina Teste")
    with pytest.raises(ValueError, match="classe desconhecida"):
        CL.gravar_visao("Marina Teste", "bitcoin2", 1.0, "x")
    v = CL.gravar_visao("Marina Teste", "fii", 1.0, "papel paga mais que NTN-B", direcao=1)
    assert [x["id"] for x in CL.visoes_ativas("Marina Teste")] == [v["id"]]
    CL.desativar_visao("Marina Teste", v["id"])
    assert CL.visoes_ativas("Marina Teste") == []
    assert len(CL.ler_visoes("Marina Teste")) == 1                      # o histórico fica


def test_diario_registra_cada_passo(clientes):
    CL.novo("Marina Teste")
    CL.anotar("Marina Teste", "Cliente prefere isento")
    assert "Cliente prefere isento" in CL.ler_diario("Marina Teste")


def test_dado_de_cliente_nao_sai_da_pasta_de_clientes(clientes):
    CL.novo("Marina Teste")
    assert str(CL.pasta("Marina Teste")).startswith(str(clientes))


# --- veredito do alinhamento ---------------------------------------------------------------------
def _ck(status):
    return {"id": "x", "titulo": "t", "status": status, "valor": "", "limite": "", "leitura": "", "acao": ""}


def test_veredito_pior_status_manda():
    assert A.veredito([_ck("ok"), _ck("info")])["veredito"] == "ALINHADA"
    assert A.veredito([_ck("ok"), _ck("atencao")])["veredito"] == "ALINHADA COM RESSALVAS"
    assert A.veredito([_ck("ok"), _ck("atencao"), _ck("fora")])["veredito"] == "FORA DO ALINHAMENTO"
    assert A.veredito([_ck("ok"), _ck("fora")])["contagem"]["fora"] == 1


def test_escala_das_checagens():
    assert A._escala(0.5, 1.0, 2.0) == "ok"
    assert A._escala(1.5, 1.0, 2.0) == "atencao"
    assert A._escala(2.5, 1.0, 2.0) == "fora"
    assert A._escala(2.5, 2.0, 1.0, menor_e_melhor=False) == "ok"


# --- ponta a ponta com o cache do terminal -------------------------------------------------------
@precisa_mercado
def test_contexto_e_avaliacao_ponta_a_ponta(clientes):
    from alocacao import contexto as X

    CL.novo("Marina Teste", **{"pessoa.idade": 48, "patrimonio.financeiro": 5_000_000, "objetivo.prazo_anos": 8,
                               "risco.perfil": "moderado", "risco.queda_maxima_tolerada": 10,
                               "fluxo.aporte_mensal": 0})
    ctx = X.montar("Marina Teste", n_sim=1500)
    assert ctx.perfil == "moderado" and ctx.horizonte == pytest.approx(8.0)
    assert len(ctx.mu) == len(C.IDS) and ctx.cov.shape == (len(C.IDS), len(C.IDS))
    assert np.all(np.linalg.eigvalsh(ctx.cov.values) > -1e-10)           # covariancia semipositiva
    cands = O.candidatos(ctx.mu, ctx.cov, ctx.restr)
    assert cands[0]["w"] is not None
    a = X.avaliar(ctx, cands[0]["w"])
    checks = A.checar(ctx, a)
    ver = A.veredito(checks)
    assert ver["veredito"] in ("ALINHADA", "ALINHADA COM RESSALVAS", "FORA DO ALINHAMENTO")
    assert A.resumo_texto(checks, ver).startswith("**")
    # rodar de novo dá o mesmo veredito e o mesmo retorno (semente fixa)
    a2 = X.avaliar(ctx, cands[0]["w"])
    assert a2["ret"] == pytest.approx(a["ret"])
    assert A.veredito(A.checar(ctx, a2))["veredito"] == ver["veredito"]


@precisa_mercado
def test_cli_proposta_e_movimentos_sem_carteira_atual(clientes, capsys):
    import alocar

    assert alocar.main(["novo", "Marina Teste", "--set", "patrimonio.financeiro=5000000", "--set", "risco.perfil=moderado",
                        "--set", "objetivo.prazo_anos=8", "--set", "pessoa.idade=48"]) in (0, None)
    assert alocar.main(["proposta", "Marina Teste", "--candidato", "A", "--sims", "1500", "--quieto"]) in (0, None)
    capsys.readouterr()
    assert alocar.main(["movimentos", "Marina Teste"]) in (0, None)
    saida = capsys.readouterr().out
    assert "dinheiro novo" in saida
    assert "reduzir Caixa" not in saida


def test_cli_cliente_inexistente_sai_com_erro_2(clientes, capsys):
    import alocar

    assert alocar.main(["ficha", "Fulano"]) == 2
    assert "alocar.py novo" in capsys.readouterr().err
