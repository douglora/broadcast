"""O painel quant dentro do terminal: refresh_quant e as rotas /api/quant/*.

Nao se testa estrategia aqui. Testa-se o contrato de `quant/docs/painel-contrato.md`:

- sem `quant/saida/painel.json` a resposta e 503 com o comando que gera o arquivo;
- um arquivo que sumiu nao apaga o painel que ja estava carregado;
- cada rota devolve so o pedaco que a sua aba precisa;
- e, o principal, nenhum `NaN`, `Infinity` ou objeto exotico chega ao `jsonify` —
  seriam JSON invalido (quebra o `await r.json()` do front) ou um 500 em HTML.
"""
import datetime as dt
import json
from decimal import Decimal

import pytest

pytest.importorskip("flask")

import app as terminal


COMANDO = "python3 -m quant.rodar_diario --paper"
ROTAS = ["/api/quant/painel", "/api/quant/boleta", "/api/quant/fiscal",
         "/api/quant/desempenho", "/api/quant/paper"]


def painel_exemplo():
    """O exemplo do contrato, encurtado onde o tamanho nao importa."""
    return {
        "gerado_em": "2026-09-08T21:05:00-03:00",
        "modo": "paper",
        "origem": "sintetico",
        "capital": 100000.0,
        "gate_fase1": {"passou": False, "detalhe": "nao rodado: falta o COTAHIST real"},
        "frescor": {"cotahist": {"data": "2026-09-05", "dias_atras": 3, "ok": False}},
        "modo_seguro": {"ativo": True, "motivos": ["COTAHIST do pregao de hoje ausente"]},
        "carteira": {
            "patrimonio": 101234.56, "caixa": 26000.0, "valor_posicoes": 75234.56,
            "n_posicoes": 1, "contratos_hedge": 1, "exposicao": 0.743,
            "caixa_minimo": 25000.0, "violacoes": [],
            "posicoes": [{"ticker": "ABCD3", "setor": "energia", "qtd": 300,
                          "preco_medio": 20.10, "preco": 21.00, "valor": 6300.0,
                          "peso": 0.062, "peso_alvo": 0.055, "meses": 3, "rank": 4,
                          "pnl": 270.0, "pnl_pct": 0.0448}],
        },
        "boleta": {
            "data": "2026-09-08", "id": "20260908", "emitida": False,
            "motivo_bloqueio": ["COTAHIST do pregao de hoje ausente"],
            "custo_total": 145.0,
            "ordens": [{"ticker": "ABCD3", "lado": "C", "qtd": 300, "preco_limite": 20.55,
                        "validade": "dia", "motivo": "entrada", "custo": 12.30,
                        "fatia": "1/2", "adtv": 5200000.0, "fracionario": False}],
        },
        "paper": {
            "origem": "ensaio", "sessoes": 110, "primeira": "2026-04-01",
            "ultima": "2026-09-08", "boletas_emitidas": 110, "taxa_execucao": 1.0,
            "slippage_bps": -58.4, "slippage_vwap_bps": -55.1, "erros": 0,
            "meses_sem_erro": None, "rolls": 3, "passou": False,
            "reprovados": ["meses_sem_erro"],
            "avisos": ["ENSAIO sobre dado sintetico: isto nao e a fase 4"],
            "criterios": [{"criterio": "execucao", "valor": 1.0, "gatilho": 0.6,
                           "formato": "pct", "status": "ok"}],
        },
        "fiscal": {
            "mes": "2026-09", "vendas_acoes_mes": 12000.0, "isencao_restante": 8000.0,
            "isento": True, "lucro_comum": 1500.0, "lucro_day_trade": 0.0,
            "prejuizo_acumulado_comum": 0.0, "prejuizo_acumulado_day_trade": 0.0,
            "irrf_retido": 0.60, "darf": 0.0, "darf_vence": "2026-10-30",
            "darf_acumulado": 0.0,
            "aviso": "calculo de apoio; conferir com contador antes de recolher",
        },
        "desempenho": {
            "desde": "2026-01-02", "retorno": 0.0123, "cdi": 0.0111, "excesso": 0.0012,
            "ibov": 0.0201, "vol": 0.14, "mdd": 0.031, "giro_mensal": 0.18,
            "custo_aa": 0.024,
            "serie": [{"data": "2026-01-02", "carteira": 1.0, "cdi": 1.0, "ibov": 1.0},
                      {"data": "2026-01-03", "carteira": 1.01, "cdi": 1.0, "ibov": 0.99}],
        },
        "kill": [{"criterio": "drawdown", "rotulo": "Drawdown do pico", "valor": 0.031,
                  "gatilho": 0.20, "status": "ok",
                  "descricao": "20% reduz o gross pela metade; 30% encerra"}],
    }


def esvaziar_cache():
    """Tira a chave do cache de vez — CACHE.set(None) ainda deixaria idade no /health."""
    with terminal.CACHE._lock:
        terminal.CACHE._d.pop("quant", None)
        terminal.CACHE._stamp.pop("quant", None)


def sem_constantes(texto):
    """json.loads que recusa NaN/Infinity: JSON valido de verdade, nao o dialeto do Python."""
    def recusa(nome):
        raise AssertionError(f"constante nao-JSON no corpo da resposta: {nome}")
    return json.loads(texto, parse_constant=recusa)


def corpo(resposta):
    return sem_constantes(resposta.get_data(as_text=True))


@pytest.fixture
def cliente():
    esvaziar_cache()
    terminal.app.config["TESTING"] = True
    with terminal.app.test_client() as c:
        yield c
    esvaziar_cache()


@pytest.fixture
def arquivo_painel(tmp_path, monkeypatch):
    """Aponta o app.py para um painel.json descartavel e devolve o caminho."""
    caminho = tmp_path / "painel.json"
    monkeypatch.setattr(terminal, "PAINEL_QUANT_PATH", str(caminho))
    monkeypatch.setattr(terminal, "_quant_ausente_avisado", False)
    return caminho


def gravar(caminho, dados):
    caminho.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")


# ── refresh_quant ────────────────────────────────────────────
def test_refresh_carrega_o_arquivo_do_disco(cliente, arquivo_painel):
    gravar(arquivo_painel, painel_exemplo())
    terminal.refresh_quant()

    d = terminal.CACHE.get("quant")
    assert d["modo"] == "paper"
    assert d["origem"] == "sintetico"
    assert d["carteira"]["posicoes"][0]["ticker"] == "ABCD3"
    assert len(d["desempenho"]["serie"]) == 2


def test_arquivo_ausente_nao_apaga_o_painel_anterior(cliente, arquivo_painel):
    gravar(arquivo_painel, painel_exemplo())
    terminal.refresh_quant()
    assert terminal.CACHE.get("quant") is not None

    arquivo_painel.unlink()
    terminal.refresh_quant()          # nao pode levantar nem zerar o cache

    assert terminal.CACHE.get("quant")["modo"] == "paper"


def test_arquivo_corrompido_nao_apaga_o_painel_anterior(cliente, arquivo_painel):
    gravar(arquivo_painel, painel_exemplo())
    terminal.refresh_quant()

    arquivo_painel.write_text("{ isto nao e json", encoding="utf-8")
    terminal.refresh_quant()
    assert terminal.CACHE.get("quant")["modo"] == "paper"

    arquivo_painel.write_text("[]", encoding="utf-8")   # JSON valido, formato errado
    terminal.refresh_quant()
    assert terminal.CACHE.get("quant")["modo"] == "paper"


def test_refresh_sem_arquivo_nenhum_nao_levanta(cliente, arquivo_painel):
    terminal.refresh_quant()
    assert terminal.CACHE.get("quant") is None


# ── 503 enquanto ninguem rodou o pipeline ────────────────────
@pytest.mark.parametrize("rota", ROTAS)
def test_rota_sem_painel_devolve_503_com_o_comando(cliente, rota):
    r = cliente.get(rota)
    assert r.status_code == 503
    d = corpo(r)
    assert d["error"] == "painel nao gerado"
    assert d["comando"] == COMANDO


# ── as quatro rotas com painel carregado ─────────────────────
@pytest.fixture
def carregado(cliente, arquivo_painel):
    gravar(arquivo_painel, painel_exemplo())
    terminal.refresh_quant()
    return cliente


def test_painel_traz_tudo_menos_a_serie(carregado):
    r = carregado.get("/api/quant/painel")
    assert r.status_code == 200
    d = corpo(r)
    for chave in ("gerado_em", "modo", "origem", "gate_fase1", "frescor",
                  "modo_seguro", "carteira", "boleta", "fiscal", "desempenho", "kill"):
        assert chave in d, chave
    assert d["desempenho"]["retorno"] == 0.0123
    assert "serie" not in d["desempenho"]          # a serie so sai na aba Desempenho
    assert d["carteira"]["posicoes"][0]["peso_alvo"] == 0.055


def test_boleta_traz_ordens_e_o_modo_seguro_e_nada_de_carteira(carregado):
    r = carregado.get("/api/quant/boleta")
    assert r.status_code == 200
    d = corpo(r)
    assert d["boleta"]["id"] == "20260908"
    assert d["boleta"]["emitida"] is False
    assert d["boleta"]["motivo_bloqueio"] == ["COTAHIST do pregao de hoje ausente"]
    assert d["modo_seguro"]["ativo"] is True
    assert "carteira" not in d and "desempenho" not in d and "fiscal" not in d


def test_fiscal_traz_o_mes_e_nada_alem(carregado):
    r = carregado.get("/api/quant/fiscal")
    assert r.status_code == 200
    d = corpo(r)
    assert d["fiscal"]["mes"] == "2026-09"
    assert d["fiscal"]["isencao_restante"] == 8000.0
    assert "contador" in d["fiscal"]["aviso"]
    assert "carteira" not in d and "boleta" not in d


def test_desempenho_traz_a_serie_e_os_criterios_de_kill(carregado):
    r = carregado.get("/api/quant/desempenho")
    assert r.status_code == 200
    d = corpo(r)
    assert len(d["desempenho"]["serie"]) == 2
    assert d["desempenho"]["serie"][0]["cdi"] == 1.0
    assert d["kill"][0]["status"] == "ok"
    assert "carteira" not in d and "boleta" not in d


def test_health_lista_o_quant_depois_de_carregado(cliente, arquivo_painel):
    assert "quant" not in corpo(cliente.get("/health"))["caches"]

    gravar(arquivo_painel, painel_exemplo())
    terminal.refresh_quant()

    saude = corpo(cliente.get("/health"))
    assert saude["status"] == "ok"
    assert "quant" in saude["caches"]


# ── o que nao pode chegar ao jsonify ─────────────────────────
def test_nan_no_arquivo_vira_null_e_nao_quebra_o_json(cliente, arquivo_painel):
    # json.dumps do Python escreve NaN/Infinity como literais; json.load os aceita
    # de volta. Se passassem direto, o await r.json() do navegador estouraria.
    p = painel_exemplo()
    p["carteira"]["patrimonio"] = float("nan")
    p["desempenho"]["retorno"] = float("inf")
    p["desempenho"]["vol"] = float("-inf")
    p["desempenho"]["serie"][1]["carteira"] = float("nan")
    arquivo_painel.write_text(json.dumps(p), encoding="utf-8")   # grava NaN literal
    assert "NaN" in arquivo_painel.read_text(encoding="utf-8")

    terminal.refresh_quant()

    r = cliente.get("/api/quant/painel")
    assert r.status_code == 200
    texto = r.get_data(as_text=True)
    assert "NaN" not in texto and "Infinity" not in texto
    d = sem_constantes(texto)
    assert d["carteira"]["patrimonio"] is None
    assert d["desempenho"]["retorno"] is None
    assert d["desempenho"]["vol"] is None

    d2 = corpo(cliente.get("/api/quant/desempenho"))
    assert d2["desempenho"]["serie"][1]["carteira"] is None


def test_objeto_nao_serializavel_no_cache_nao_vira_500(cliente):
    # Cenario de defesa: alguem (um teste, um job futuro) poe no cache um payload
    # com tipos que o jsonify nao serializa. Tem de sair JSON valido, nunca HTML.
    p = painel_exemplo()
    p["gerado_em"] = dt.datetime(2026, 9, 8, 21, 5)
    p["capital"] = Decimal("100000.50")
    p["carteira"]["patrimonio"] = float("nan")
    p["carteira"]["violacoes"] = {"caixa", "setor"}          # set nao e JSON
    p["fiscal"]["darf_vence"] = dt.date(2026, 10, 30)
    terminal.CACHE.set("quant", p)

    for rota in ROTAS:
        r = cliente.get(rota)
        assert r.status_code == 200, rota
        assert r.mimetype == "application/json", rota
        corpo(r)                                             # so precisa parsear

    d = corpo(cliente.get("/api/quant/painel"))
    assert d["gerado_em"] == "2026-09-08 21:05:00"
    assert d["capital"] == pytest.approx(100000.50)
    assert d["carteira"]["patrimonio"] is None
    assert sorted(d["carteira"]["violacoes"]) == ["caixa", "setor"]
    assert d["fiscal"]["darf_vence"] == "2026-10-30"


def test_painel_fora_do_contrato_devolve_503_e_nunca_500(cliente):
    # `desempenho` deveria ser objeto; veio lista. Nada de 500 (que devolveria HTML
    # e quebraria o await r.json() do front) — 503 com o comando, como no contrato.
    terminal.CACHE.set("quant", {"modo": "paper", "desempenho": ["errado"]})
    r = cliente.get("/api/quant/painel")
    assert r.status_code == 200          # _sub() ja tolera: vira {}
    assert corpo(r)["desempenho"] == {}

    terminal.CACHE.set("quant", "isto nao e um painel")
    for rota in ROTAS:
        r = cliente.get(rota)
        assert r.status_code == 503, rota
        assert corpo(r)["comando"] == COMANDO


def test_rota_paper_traz_o_placar_da_campanha(carregado):
    d = corpo(carregado.get("/api/quant/paper"))
    assert d["paper"]["sessoes"] == 110 and d["paper"]["passou"] is False
    assert d["paper"]["criterios"][0]["formato"] == "pct"


def test_boleta_carrega_o_placar_do_paper_junto(carregado):
    """A aba Boleta e onde o placar aparece: vai na mesma resposta para nao pedir duas."""
    d = corpo(carregado.get("/api/quant/boleta"))
    assert d["paper"]["origem"] == "ensaio"
