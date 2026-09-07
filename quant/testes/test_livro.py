import json
import os

import numpy as np
import pytest
from scipy.stats import norm

from quant import livro

CONFIG_A = {"sinal": "momentum_12_2", "n_carteira": 20, "custos_bps": 15}
CONFIG_B = {"sinal": "momentum_12_2", "n_carteira": 25, "custos_bps": 15}
CONFIG_C = {"sinal": "momentum_6_1", "n_carteira": 20, "custos_bps": 15}
CONFIG_D = {"sinal": "momentum_12_2", "n_carteira": 20, "custos_bps": 30}
PERIODO = ("2008-01-01", "2015-12-31")


@pytest.fixture(autouse=True)
def arq(tmp_path, monkeypatch):
    """Isola os dois arquivos em tmp_path. Autouse: nenhum teste alcanca o livro real,
    nem pelos globais (main, abrir_holdout). Devolve o caminho do livro isolado."""
    caminho = str(tmp_path / "livro.jsonl")
    monkeypatch.setattr(livro, "ARQ_LIVRO", caminho)
    monkeypatch.setattr(livro, "ARQ_HOLDOUT", str(tmp_path / "holdout.json"))
    return caminho


def _linhas(caminho):
    with open(caminho, encoding="utf-8") as f:
        return [linha for linha in f.read().splitlines() if linha]


def _gravar(caminho, linhas):
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("".join(linha + "\n" for linha in linhas))


def _tres(arq):
    livro.registrar(CONFIG_A, PERIODO, {"sharpe": 0.10}, "grid 1", caminho=arq)
    livro.registrar(CONFIG_B, PERIODO, {"sharpe": 0.20}, "grid 2", caminho=arq)
    livro.registrar(CONFIG_C, PERIODO, {"sharpe": 0.30}, "grid 3", caminho=arq)
    return _linhas(arq)


# ─────────────────────────────────────────────────────────────
# Funcoes puras
# ─────────────────────────────────────────────────────────────
def test_canonizar_nao_depende_da_ordem_das_chaves():
    assert livro.canonizar({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    assert livro.hash_config(CONFIG_A) == livro.hash_config(dict(reversed(list(CONFIG_A.items()))))
    assert livro.hash_config(CONFIG_A) != livro.hash_config(CONFIG_B)
    assert len(livro.hash_config(CONFIG_A)) == 64
    livro.canonizar({"data": np.datetime64("2020-01-01"), "s": {1, 2}})   # nao levanta


def test_versao_codigo_nunca_levanta(monkeypatch):
    v = livro.versao_codigo()
    assert set(v) == {"commit", "sujo"} and isinstance(v["sujo"], bool)
    assert v["commit"] is None or len(v["commit"]) == 40

    def _sem_git(*a, **k):
        raise OSError("git nao existe nesta maquina")

    monkeypatch.setattr(livro.subprocess, "run", _sem_git)
    assert livro.versao_codigo() == {"commit": None, "sujo": True}   # pessimista


def test_impressao_dados_de_arquivo_presente_e_ausente(tmp_path):
    import hashlib
    alvo = tmp_path / "cotacoes.csv"
    alvo.write_bytes(b"data;fec\n2020-01-02;10\n")
    imp = livro.impressao_dados(str(alvo))
    chave = str(alvo)
    assert imp[chave]["sha256"] == hashlib.sha256(alvo.read_bytes()).hexdigest()
    assert imp[chave]["bytes"] == len(alvo.read_bytes()) and imp[chave]["mtime"].endswith("+00:00")
    ausente = livro.impressao_dados([str(tmp_path / "nao_existe.csv")])
    assert list(ausente.values()) == [{"sha256": None, "bytes": None, "mtime": None}]
    assert livro.impressao_dados(None) == {} and livro.impressao_dados([]) == {}
    # arquivo do repositorio entra com o caminho relativo a RAIZ (nao o da maquina)
    real = os.path.join(livro.DIR_QUANT, "livro_tentativas.jsonl")
    assert "quant/livro_tentativas.jsonl" in livro.impressao_dados(real)


def test_sharpe_deflacionado_bate_com_a_conta_a_mao():
    # N = 10 tentativas, V[SR] = 0,04 (dp 0,2), SR MENSAL 0,30 em T = 120 meses, normal.
    # Phi_inv(1 - 1/10) = 1,2815515655; Phi_inv(1 - 1/(10e)) = 1,7892417646
    sr0 = 0.2 * ((1 - livro.GAMA_EULER) * 1.2815515655446004
                 + livro.GAMA_EULER * 1.7892417645816283)
    z = (0.30 - sr0) * np.sqrt(119.0) / np.sqrt(1.0 + 0.5 * 0.09)   # radicando = 1,045
    assert abs(sr0 - 0.31491966026915) < 1e-12
    assert abs(livro.sharpe_deflacionado(0.30, 120, 10, 0.04) - float(norm.cdf(z))) < 1e-12
    assert abs(livro.sharpe_deflacionado(0.30, 120, 10, 0.04) - 0.43675114562659056) < 1e-12


def test_sharpe_deflacionado_cai_com_mais_tentativas_e_mais_dispersao():
    n_crescente = [livro.sharpe_deflacionado(0.30, 120, n, 0.04) for n in (2, 5, 10, 50, 200)]
    assert all(a > b for a, b in zip(n_crescente, n_crescente[1:]))
    v_crescente = [livro.sharpe_deflacionado(0.30, 120, 10, v) for v in (0.005, 0.01, 0.04, 0.09)]
    assert all(a > b for a, b in zip(v_crescente, v_crescente[1:]))
    # cauda gorda e assimetria negativa mudam o resultado (nao sao ignoradas)
    assert livro.sharpe_deflacionado(0.30, 120, 10, 0.04, assimetria=-0.5, curtose=6.0) != \
        livro.sharpe_deflacionado(0.30, 120, 10, 0.04)
    # o erro classico: passar o SR anualizado com T em meses infla o DSR para ~1
    assert livro.sharpe_deflacionado(0.30 * np.sqrt(12), 120, 10, 0.04) > 0.99


def test_sharpe_deflacionado_devolve_nan_nos_casos_degenerados():
    assert np.isnan(livro.sharpe_deflacionado(0.3, 120, 1, 0.04))          # N <= 1
    assert np.isnan(livro.sharpe_deflacionado(0.3, 120, 0, 0.04))
    assert np.isnan(livro.sharpe_deflacionado(0.3, 120, 10, 0.0))          # V[SR] <= 0
    assert np.isnan(livro.sharpe_deflacionado(0.3, 120, 10, -1.0))
    assert np.isnan(livro.sharpe_deflacionado(0.3, 120, 10, float("nan")))  # V[SR] NaN
    assert np.isnan(livro.sharpe_deflacionado(0.3, 1, 10, 0.04))           # T <= 1
    assert np.isnan(livro.sharpe_deflacionado(2.0, 120, 10, 0.04, assimetria=3.0, curtose=1.0))
    assert np.isnan(livro.sharpe_deflacionado(0.3, 120, 1e300, 0.04))      # Phi_inv satura
    assert np.isnan(livro.sharpe_deflacionado(None, 120, 10, 0.04))        # nao numerico
    assert np.isnan(livro.sharpe_deflacionado(float("inf"), 120, 10, 0.04))


# ─────────────────────────────────────────────────────────────
# Livro: cadeia, leitura e contagem
# ─────────────────────────────────────────────────────────────
def test_registrar_anexa_e_ler_devolve_o_que_foi_gravado(arq):
    a = livro.registrar(CONFIG_A, PERIODO, {"sharpe": 0.21, "mdd": -0.32}, "grid inicial",
                        caminho=arq)
    b = livro.registrar(CONFIG_B, PERIODO, {"sharpe": 0.18}, "20 -> 25 papeis",
                        escopo="pre_registrado", caminho=arq)
    assert a["hash_anterior"] == "" and b["hash_anterior"] == a["hash"]
    assert a["escopo"] == "pesquisa" and b["escopo"] == "pre_registrado"
    assert a["hash_config"] == livro.hash_config(CONFIG_A)
    assert a["periodo"] == ["2008-01-01", "2015-12-31"]
    assert a["carimbo"].endswith("+00:00") and a["id"].startswith("t0001-")
    assert set(a["versao_codigo"]) == {"commit", "sujo"}
    df = livro.ler(arq)
    assert list(df.columns) == livro.COLUNAS and len(df) == 2
    assert df["config"].iloc[0] == CONFIG_A and df["motivo"].iloc[1] == "20 -> 25 papeis"
    assert df["resultados"].iloc[0]["mdd"] == -0.32
    assert livro.verificar_cadeia(arq) == (True, None)


def test_registrar_guarda_impressao_dos_dados_e_campos_extras(arq, tmp_path):
    entrada = tmp_path / "cotacoes.parquet"
    entrada.write_bytes(b"parquet-ish")
    linha = livro.registrar(CONFIG_A, PERIODO, {"sharpe": 0.2}, "com dados", caminho=arq,
                            extras={"dados": [str(entrada)], "estresse": {"custos_x2": 0.11},
                                    "semente": 42})
    assert linha["impressao_dados"][str(entrada)]["bytes"] == 11
    assert linha["estresse"] == {"custos_x2": 0.11} and linha["semente"] == 42
    df = livro.ler(arq)
    assert list(df.columns) == livro.COLUNAS + ["semente"] and df["semente"].iloc[0] == 42
    assert livro.verificar_cadeia(arq) == (True, None)      # o campo extra entra no hash
    # pin_nefin pode ser fixado a mao (sem snapshot na maquina ele fica None)
    l2 = livro.registrar(CONFIG_B, PERIODO, None, "pin fixo", caminho=arq,
                         extras={"pin_nefin": {"sha256": "abc"}})
    assert l2["pin_nefin"] == {"sha256": "abc"}


def test_escopo_invalido_e_recusado(arq):
    with pytest.raises(ValueError, match="escopo invalido"):
        livro.registrar(CONFIG_A, PERIODO, None, "escopo errado", escopo="producao", caminho=arq)
    assert not os.path.exists(arq)                    # nem o arquivo foi criado


def test_cadeia_detecta_linha_apagada(arq):
    linhas = _tres(arq)
    _gravar(arq, [linhas[0], linhas[2]])              # some com a do meio
    assert livro.verificar_cadeia(arq) == (False, 1)
    _gravar(arq, linhas[1:])                          # some com a primeira
    assert livro.verificar_cadeia(arq) == (False, 0)


def test_cadeia_detecta_linha_editada(arq):
    linhas = _tres(arq)
    editada = json.loads(linhas[1])
    editada["resultados"]["sharpe"] = 0.99            # o numero que interessa maquiar
    _gravar(arq, [linhas[0], json.dumps(editada, ensure_ascii=False), linhas[2]])
    assert livro.verificar_cadeia(arq) == (False, 1)
    # tambem na ULTIMA linha, onde nao ha elo seguinte e so o hash proprio denuncia
    ultima = json.loads(linhas[2])
    ultima["motivo"] = "outro motivo"
    _gravar(arq, [linhas[0], linhas[1], json.dumps(ultima, ensure_ascii=False)])
    assert livro.verificar_cadeia(arq) == (False, 2)


def test_cadeia_detecta_arquivo_reordenado_ou_ilegivel(arq):
    linhas = _tres(arq)
    _gravar(arq, [linhas[1], linhas[0], linhas[2]])
    assert livro.verificar_cadeia(arq) == (False, 0)
    _gravar(arq, [linhas[0], linhas[1], "{isso nao e json"])
    assert livro.verificar_cadeia(arq) == (False, 2)
    _gravar(arq, linhas)                               # restaurado: volta a fechar
    assert livro.verificar_cadeia(arq) == (True, None)


def test_registrar_recusa_anexar_em_cadeia_quebrada(arq):
    linhas = _tres(arq)
    _gravar(arq, [linhas[0], linhas[2]])
    with pytest.raises(ValueError, match="cadeia quebrada na linha 1"):
        livro.registrar(CONFIG_D, PERIODO, {"sharpe": 0.4}, "em cima do estrago", caminho=arq)
    assert len(_linhas(arq)) == 2                      # nada foi anexado


def test_n_tentativas_conta_configs_distintas_e_ignora_o_escopo_teste(arq):
    livro.registrar(CONFIG_A, PERIODO, {"sharpe": 0.10}, "1", caminho=arq)
    livro.registrar(CONFIG_A, PERIODO, {"sharpe": 0.10}, "mesma config, rodada de novo",
                    caminho=arq)
    livro.registrar(dict(reversed(list(CONFIG_A.items()))), PERIODO, {"sharpe": 0.10},
                    "mesma config, chaves em outra ordem", caminho=arq)
    livro.registrar(CONFIG_B, PERIODO, {"sharpe": 0.20}, "2", caminho=arq)
    livro.registrar(CONFIG_C, PERIODO, {"sharpe": 0.30}, "fixture do CI", escopo="teste",
                    caminho=arq)
    livro.registrar(CONFIG_D, PERIODO, {"sharpe": 0.05}, "congelada", escopo="pre_registrado",
                    caminho=arq)
    assert livro.n_tentativas(caminho=arq) == 3                       # A, B, D
    assert livro.n_tentativas(escopos=("teste",), caminho=arq) == 1
    assert livro.n_tentativas(escopos=None, caminho=arq) == 4         # todos os escopos
    assert livro.n_tentativas(caminho=str(arq) + ".nao_existe") == 0


def test_variancia_sharpes_precisa_de_duas_tentativas(arq):
    assert np.isnan(livro.variancia_sharpes(caminho=arq))             # livro ausente
    livro.registrar(CONFIG_A, PERIODO, {"sharpe": 0.10}, "1", caminho=arq)
    assert np.isnan(livro.variancia_sharpes(caminho=arq))             # uma so
    livro.registrar(CONFIG_A, PERIODO, {"sharpe": 0.10}, "a mesma de novo", caminho=arq)
    assert np.isnan(livro.variancia_sharpes(caminho=arq))             # mesma config: uma so
    livro.registrar(CONFIG_B, PERIODO, {"sharpe": 0.20}, "2", caminho=arq)
    livro.registrar(CONFIG_C, PERIODO, {"sharpe": 0.30}, "3", caminho=arq)
    livro.registrar(CONFIG_D, PERIODO, {"nada": 1}, "sem sharpe: fora da conta", caminho=arq)
    livro.registrar(CONFIG_D, PERIODO, {"sharpe": 9.9}, "escopo teste: fora da conta",
                    escopo="teste", caminho=arq)
    assert abs(livro.variancia_sharpes(caminho=arq) - np.var([0.1, 0.2, 0.3], ddof=1)) < 1e-15
    # sharpe_deflacionado consome exatamente esses dois numeros
    dsr = livro.sharpe_deflacionado(0.30, 120, livro.n_tentativas(caminho=arq),
                                    livro.variancia_sharpes(caminho=arq))
    assert 0.0 < dsr < 1.0


def test_ler_arquivo_ausente_devolve_esquema_vazio(tmp_path):
    caminho = str(tmp_path / "sem_livro.jsonl")
    df = livro.ler(caminho)
    assert list(df.columns) == livro.COLUNAS and len(df) == 0
    assert livro.verificar_cadeia(caminho) == (True, None)
    assert livro.n_tentativas(caminho=caminho) == 0
    assert np.isnan(livro.variancia_sharpes(caminho=caminho))


def test_livro_real_do_repositorio_esta_integro():
    # o arquivo commitado (vazio ou nao) precisa fechar a cadeia; os testes nunca o tocam
    real = os.path.join(livro.DIR_QUANT, "livro_tentativas.jsonl")
    assert livro.verificar_cadeia(real) == (True, None)
    estado = livro.holdout_estado(os.path.join(livro.DIR_QUANT, "holdout.json"))
    assert estado["periodo"] == list(livro.HOLDOUT) and estado["nota"]


# ─────────────────────────────────────────────────────────────
# Holdout
# ─────────────────────────────────────────────────────────────
def test_holdout_abre_uma_vez_so(arq, tmp_path):
    hold = str(tmp_path / "hold.json")
    inicial = livro.holdout_estado(hold)               # arquivo ausente: estado inicial
    assert inicial["aberto_em"] is None and inicial["periodo"] == list(livro.HOLDOUT)
    assert inicial["resultados"] is None and inicial["hash_config"] is None

    estado = livro.abrir_holdout(CONFIG_A, "pre-registro em docs/pre-registro.md", caminho=hold)
    assert estado["hash_config"] == livro.hash_config(CONFIG_A)
    assert estado["aberto_em"] and estado["aberto_por"]["motivo"].startswith("pre-registro")
    df = livro.ler(arq)                                # a abertura tambem entra no livro
    assert len(df) == 1 and df["escopo"].iloc[0] == "holdout"
    assert df["id"].iloc[0] == estado["id_tentativa"] and df["config"].iloc[0] == CONFIG_A
    assert df["periodo"].iloc[0] == list(livro.HOLDOUT)

    # mesma config (ate com as chaves em outra ordem): no-op, para retomar rodada que caiu
    repetido = livro.abrir_holdout(dict(reversed(list(CONFIG_A.items()))), "retomando",
                                   caminho=hold)
    assert repetido["id_tentativa"] == estado["id_tentativa"] and len(livro.ler(arq)) == 1

    # outra config: erro duro, nomeando a primeira, e nada e registrado
    with pytest.raises(RuntimeError) as exc:
        livro.abrir_holdout(CONFIG_B, "so mais uma olhadinha", caminho=hold)
    assert estado["hash_config"] in str(exc.value) and estado["id_tentativa"] in str(exc.value)
    assert len(livro.ler(arq)) == 1
    assert livro.holdout_estado(hold)["hash_config"] == estado["hash_config"]


def test_registrar_holdout_exige_holdout_aberto(arq, tmp_path):
    hold = str(tmp_path / "hold.json")
    with pytest.raises(RuntimeError, match="holdout fechado"):
        livro.registrar_holdout({"sharpe": 0.12}, caminho=hold)
    livro.abrir_holdout(CONFIG_A, "pre-registro", caminho=hold)
    estado = livro.registrar_holdout({"sharpe": 0.12, "cdi_mais_pp": -0.4}, caminho=hold)
    assert estado["resultados"]["sharpe"] == 0.12
    assert livro.holdout_estado(hold)["resultados"]["cdi_mais_pp"] == -0.4
    assert json.loads(open(hold, encoding="utf-8").read())["id_tentativa"] == estado["id_tentativa"]


# ─────────────────────────────────────────────────────────────
# Linha de comando
# ─────────────────────────────────────────────────────────────
def test_main_verificar_devolve_0_com_cadeia_boa_e_1_com_cadeia_quebrada(arq, capsys):
    linhas = _tres(arq)
    assert livro.main(["--verificar"]) == 0
    assert "cadeia: ok" in capsys.readouterr().out
    _gravar(arq, [linhas[0], linhas[2]])
    assert livro.main(["--verificar"]) == 1
    assert "QUEBRADA na linha 1" in capsys.readouterr().out
    _gravar(arq, linhas)
    assert livro.main([]) == 0                      # sem flag: verifica do mesmo jeito


def test_main_listar_e_estado_holdout(arq, capsys, tmp_path):
    assert livro.main(["--listar"]) == 0
    assert "livro vazio" in capsys.readouterr().out
    livro.registrar(CONFIG_A, PERIODO, {"sharpe": 0.2}, "grid inicial", caminho=arq)
    assert livro.main(["--listar"]) == 0
    saida = capsys.readouterr().out
    assert "grid inicial" in saida and "pesquisa" in saida
    assert livro.main(["--estado-holdout"]) == 0
    estado = json.loads(capsys.readouterr().out)
    assert estado["periodo"] == list(livro.HOLDOUT) and estado["aberto_em"] is None
