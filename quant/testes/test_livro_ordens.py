"""
Livro de ordens e fills: ida e volta em disco, idempotencia, preco medio e conferencia.

Aqui nao se testa estrategia nenhuma: testa-se que o registro do que foi mandado e do que
foi executado sobrevive a gravacao, nao duplica, e que a posicao recomputada dos fills da
sempre o mesmo numero - que e o que sustenta a apuracao fiscal.

Nenhum teste toca quant/saida/: a fixture troca os dois caminhos globais por tmp_path
(protege main(), que le os globais) e todas as chamadas passam `caminho=` explicito.
"""
import os

import numpy as np
import pandas as pd
import pytest

from quant import carteira as ct
from quant.execucao import livro_ordens as lo


@pytest.fixture(autouse=True)
def arqs(tmp_path, monkeypatch):
    """Isola os dois arquivos em tmp_path e devolve (caminho das ordens, caminho dos fills)."""
    ordens = str(tmp_path / "livro_ordens.csv")
    fills = str(tmp_path / "livro_fills.csv")
    monkeypatch.setattr(lo, "ARQ_ORDENS", ordens)
    monkeypatch.setattr(lo, "ARQ_FILLS", fills)
    return ordens, fills


def _ordens(qtd=100, ticker="PETR4", lado="C", motivo="entrada"):
    """Uma boleta no formato exato de carteira.ordens_incrementais."""
    return pd.DataFrame([{"ticker": ticker, "lado": lado, "qtd": qtd, "preco": 10.50,
                          "valor": qtd * 10.50, "custo": 4.20, "motivo": motivo,
                          "fracionario": False}], columns=ct.COLUNAS_ORDEM)


def _fill(data, ticker="PETR4", lado="C", qtd=100, preco=10.0, **kw):
    linha = {"data": data, "hora": kw.pop("hora", "10:00:00"), "boleta": kw.pop("boleta", "20260908"),
             "ticker": ticker, "lado": lado, "qtd": qtd, "preco": preco,
             "corretagem": kw.pop("corretagem", 0.0), "emolumentos": kw.pop("emolumentos", 0.0),
             "origem": kw.pop("origem", "paper"), "obs": kw.pop("obs", "")}
    linha.update(kw)
    return linha


def _duas_compras(af):
    """100 a 10 com R$5 de custo e 100 a 20 com R$5: o exemplo do preco medio."""
    lo.registrar_fills([_fill("2026-09-09", qtd=100, preco=10.0, corretagem=5.0),
                        _fill("2026-09-10", qtd=100, preco=20.0, emolumentos=5.0)], caminho=af)


# ─────────────────────────────────────────────────────────────
# Ida e volta em disco
# ─────────────────────────────────────────────────────────────
def test_ida_e_volta_de_ordens_preserva_as_colunas_e_os_padroes(arqs):
    ao, _ = arqs
    lo.registrar_ordens(_ordens(), "2026-09-08", "20260908", caminho=ao)
    o = lo.carregar_ordens(caminho=ao)
    assert list(o.columns) == lo.COLUNAS_ORDEM
    assert len(o) == 1 and o["ticker"].iloc[0] == "PETR4" and o["lado"].iloc[0] == "C"
    assert o["data"].iloc[0] == pd.Timestamp("2026-09-08") and o["boleta"].iloc[0] == "20260908"
    assert abs(o["qtd"].iloc[0] - 100) < 1e-12
    assert abs(o["preco_limite"].iloc[0] - 10.50) < 1e-12      # cai em `preco` da carteira
    assert abs(o["custo_estimado"].iloc[0] - 4.20) < 1e-12     # cai em `custo` da carteira
    assert o["validade"].iloc[0] == lo.VALIDADE_PADRAO
    assert o["fatia"].iloc[0] == lo.FATIA_PADRAO
    assert o["status"].iloc[0] == "emitida" and o["fracionario"].iloc[0] is np.False_


def test_ida_e_volta_de_fills_preserva_as_colunas_e_os_valores(arqs):
    _, af = arqs
    lo.registrar_fills([_fill("2026-09-09", preco=10.37, corretagem=4.20, emolumentos=0.31,
                              origem="real", obs="nota 12345")], caminho=af)
    f = lo.carregar_fills(caminho=af)
    assert list(f.columns) == lo.COLUNAS_FILL
    assert f["data"].iloc[0] == pd.Timestamp("2026-09-09") and f["hora"].iloc[0] == "10:00:00"
    assert abs(f["preco"].iloc[0] - 10.37) < 1e-12
    assert abs(f["corretagem"].iloc[0] - 4.20) < 1e-12
    assert abs(f["emolumentos"].iloc[0] - 0.31) < 1e-12
    assert f["origem"].iloc[0] == "real" and f["obs"].iloc[0] == "nota 12345"
    assert os.path.exists(af)


def test_o_arquivo_gravado_e_csv_com_ponto_e_virgula_e_cabecalho(arqs):
    _, af = arqs
    lo.registrar_fills([_fill("2026-09-09")], caminho=af)
    linhas = open(af, encoding="utf-8").read().splitlines()
    assert linhas[0] == lo.SEP.join(lo.COLUNAS_FILL)
    assert linhas[1].split(lo.SEP)[0] == "2026-09-09"


def test_aceita_a_saida_de_carteira_ordens_incrementais(arqs):
    """Contrato com quant/carteira.py: as colunas que ela produz bastam para registrar."""
    ao, _ = arqs
    o = lo.registrar_ordens(_ordens(motivo="saida_gate", lado="V"), "2026-09-08", "b", caminho=ao)
    assert list(_ordens().columns) == ct.COLUNAS_ORDEM
    assert o["motivo"].iloc[0] == "saida_gate" and o["lado"].iloc[0] == "V"


# ─────────────────────────────────────────────────────────────
# Idempotencia
# ─────────────────────────────────────────────────────────────
def test_reemitir_a_mesma_boleta_substitui_as_linhas_sem_duplicar(arqs):
    ao, _ = arqs
    lo.registrar_ordens(_ordens(qtd=100), "2026-09-08", "20260908", caminho=ao)
    lo.registrar_ordens(_ordens(qtd=100), "2026-09-08", "20260908", caminho=ao)
    assert len(lo.carregar_ordens(caminho=ao)) == 1
    lo.registrar_ordens(_ordens(qtd=300), "2026-09-08", "20260908", caminho=ao)
    o = lo.carregar_ordens(caminho=ao)
    assert len(o) == 1 and abs(o["qtd"].iloc[0] - 300) < 1e-12   # a versao nova vence


def test_boletas_e_fatias_diferentes_sao_linhas_diferentes(arqs):
    ao, _ = arqs
    lo.registrar_ordens(_ordens(), "2026-09-08", "20260908", caminho=ao)
    lo.registrar_ordens(_ordens(), "2026-09-09", "20260909", caminho=ao)
    lo.registrar_ordens(_ordens().assign(fatia="2/2"), "2026-09-09", "20260909", caminho=ao)
    assert len(lo.carregar_ordens(caminho=ao)) == 3


def test_registrar_o_mesmo_fill_duas_vezes_nao_duplica(arqs):
    _, af = arqs
    f = _fill("2026-09-09", qtd=100, preco=10.0)
    lo.registrar_fills([f], caminho=af)
    lo.registrar_fills([f], caminho=af)
    lo.registrar_fills([f, f], caminho=af)
    assert len(lo.carregar_fills(caminho=af)) == 1


def test_reenviar_o_fill_com_a_corretagem_da_nota_corrige_a_linha(arqs):
    _, af = arqs
    lo.registrar_fills([_fill("2026-09-09")], caminho=af)
    lo.registrar_fills([_fill("2026-09-09", corretagem=4.20)], caminho=af)
    f = lo.carregar_fills(caminho=af)
    assert len(f) == 1 and abs(f["corretagem"].iloc[0] - 4.20) < 1e-12


def test_horas_diferentes_no_mesmo_dia_sao_fills_diferentes(arqs):
    _, af = arqs
    lo.registrar_fills([_fill("2026-09-09", hora="10:00:00"),
                        _fill("2026-09-09", hora="10:00:05")], caminho=af)
    assert len(lo.carregar_fills(caminho=af)) == 2


# ─────────────────────────────────────────────────────────────
# Preco medio
# ─────────────────────────────────────────────────────────────
def test_preco_medio_de_duas_compras_inclui_os_custos_na_base(arqs):
    _, af = arqs
    _duas_compras(af)
    p = lo.posicao(caminho=af)
    assert list(p.columns) == lo.COLUNAS_POSICAO
    assert len(p) == 1 and p["ticker"].iloc[0] == "PETR4"
    assert abs(p["qtd"].iloc[0] - 200) < 1e-12
    assert abs(p["custo_total"].iloc[0] - (100 * 10 + 5 + 100 * 20 + 5)) < 1e-12
    assert abs(p["preco_medio"].iloc[0] - (100 * 10 + 5 + 100 * 20 + 5) / 200) < 1e-12


def test_venda_nao_muda_o_preco_medio_e_reduz_o_custo_proporcionalmente(arqs):
    _, af = arqs
    _duas_compras(af)
    lo.registrar_fills([_fill("2026-09-11", lado="V", qtd=50, preco=30.0)], caminho=af)
    p = lo.posicao(caminho=af)
    assert abs(p["qtd"].iloc[0] - (200 - 50)) < 1e-12
    assert abs(p["custo_total"].iloc[0] - (100 * 10 + 5 + 100 * 20 + 5) * 150 / 200) < 1e-12
    assert abs(p["preco_medio"].iloc[0] - (100 * 10 + 5 + 100 * 20 + 5) / 200) < 1e-12


def test_custo_da_venda_nao_entra_na_base_do_que_sobra(arqs):
    """Corretagem de venda reduz o valor liquido da venda (conta do fiscal), nao aumenta o
    custo de aquisicao do que ficou na carteira."""
    _, af = arqs
    _duas_compras(af)
    lo.registrar_fills([_fill("2026-09-11", lado="V", qtd=50, preco=30.0,
                              corretagem=4.20, emolumentos=0.90)], caminho=af)
    p = lo.posicao(caminho=af)
    assert abs(p["custo_total"].iloc[0] - (100 * 10 + 5 + 100 * 20 + 5) * 150 / 200) < 1e-12


def test_vender_tudo_remove_a_linha(arqs):
    _, af = arqs
    _duas_compras(af)
    lo.registrar_fills([_fill("2026-09-11", lado="V", qtd=200, preco=30.0)], caminho=af)
    p = lo.posicao(caminho=af)
    assert len(p) == 0 and list(p.columns) == lo.COLUNAS_POSICAO


def test_recomprar_depois_de_zerar_abre_posicao_nova(arqs):
    _, af = arqs
    lo.registrar_fills([_fill("2026-01-15", qtd=100, preco=10.0),
                        _fill("2026-03-10", lado="V", qtd=100, preco=12.0),
                        _fill("2026-06-20", qtd=100, preco=15.0)], caminho=af)
    p = lo.posicao(ate="2026-09-08", caminho=af)
    assert p["data_entrada"].iloc[0] == pd.Timestamp("2026-06-20")
    assert abs(p["preco_medio"].iloc[0] - 15.0) < 1e-12
    assert p["meses"].iloc[0] == (9 - 6) - 1        # 20/06 a 08/09: dois meses cheios


def test_meses_conta_do_inicio_da_posicao_ate_a_data_de_referencia(arqs):
    _, af = arqs
    lo.registrar_fills([_fill("2026-01-15", qtd=100, preco=10.0)], caminho=af)
    assert lo.posicao(ate="2026-09-08", caminho=af)["meses"].iloc[0] == (9 - 1) - 1
    assert lo.posicao(ate="2026-09-15", caminho=af)["meses"].iloc[0] == (9 - 1)


def test_vender_mais_do_que_tem_deixa_quantidade_negativa_e_resumo_avisa(arqs):
    _, af = arqs
    lo.registrar_fills([_fill("2026-09-09", qtd=100, preco=10.0),
                        _fill("2026-09-10", lado="V", qtd=150, preco=12.0)], caminho=af)
    p = lo.posicao(caminho=af)
    assert len(p) == 1 and abs(p["qtd"].iloc[0] - (100 - 150)) < 1e-12
    assert abs(p["custo_total"].iloc[0]) < 1e-12          # nao sobra custo do que nao existe
    assert np.isnan(p["preco_medio"].iloc[0])             # preco medio de posicao negativa
    assert lo.resumo(caminho=af)["posicoes_negativas"] == ["PETR4"]


def test_posicao_ate_ignora_fills_posteriores(arqs):
    _, af = arqs
    _duas_compras(af)
    p = lo.posicao(ate="2026-09-09", caminho=af)
    assert abs(p["qtd"].iloc[0] - 100) < 1e-12
    assert abs(p["preco_medio"].iloc[0] - (100 * 10 + 5) / 100) < 1e-12
    assert len(lo.posicao(ate="2026-09-08", caminho=af)) == 0     # antes do primeiro fill


def test_fills_registrados_fora_de_ordem_sao_processados_em_ordem_cronologica(arqs):
    """A venda chega ao livro antes da compra; o preco medio nao pode depender disso."""
    _, af = arqs
    lo.registrar_fills([_fill("2026-09-11", lado="V", qtd=50, preco=30.0)], caminho=af)
    _duas_compras(af)
    p = lo.posicao(caminho=af)
    assert abs(p["qtd"].iloc[0] - 150) < 1e-12
    assert abs(p["preco_medio"].iloc[0] - (100 * 10 + 5 + 100 * 20 + 5) / 200) < 1e-12


def test_posicao_e_reconstrutivel_do_disco_e_da_memoria(arqs):
    _, af = arqs
    _duas_compras(af)
    lo.registrar_fills([_fill("2026-09-11", lado="V", qtd=50, preco=30.0, ticker="VALE3")],
                       caminho=af)
    do_disco = lo.posicao(caminho=af)
    da_memoria = lo.posicao(fills=lo.carregar_fills(caminho=af))
    assert do_disco.equals(da_memoria) and do_disco.equals(lo.posicao(caminho=af))


def test_ticker_fracionario_da_nota_soma_na_mesma_posicao(arqs):
    _, af = arqs
    lo.registrar_fills([_fill("2026-09-09", ticker="PETR4", qtd=100, preco=10.0),
                        _fill("2026-09-09", ticker="petr4f", qtd=7, preco=10.0,
                              hora="10:01:00")], caminho=af)
    p = lo.posicao(caminho=af)
    assert len(p) == 1 and p["ticker"].iloc[0] == "PETR4"
    assert abs(p["qtd"].iloc[0] - (100 + 7)) < 1e-12


# ─────────────────────────────────────────────────────────────
# Operacoes para o fiscal
# ─────────────────────────────────────────────────────────────
def test_operacoes_tem_as_colunas_do_fiscal_com_valor_e_custos(arqs):
    _, af = arqs
    lo.registrar_fills([_fill("2026-09-09", qtd=100, preco=10.37, corretagem=4.20,
                              emolumentos=0.31, origem="real")], caminho=af)
    op = lo.operacoes(caminho=af)
    assert list(op.columns) == lo.COLUNAS_OPERACAO
    assert len(op) == 1 and op["lado"].iloc[0] == "C" and op["fonte"].iloc[0] == "real"
    assert op["data"].iloc[0] == pd.Timestamp("2026-09-09")
    assert abs(op["valor"].iloc[0] - 100 * 10.37) < 1e-12
    assert abs(op["custos"].iloc[0] - (4.20 + 0.31)) < 1e-12


def test_operacoes_deduz_a_classe_pelo_codigo_e_o_mapa_explicito_vence(arqs):
    _, af = arqs
    lo.registrar_fills([_fill("2026-09-09", ticker="PETR4"),
                        _fill("2026-09-09", ticker="AAPL34", hora="10:01:00"),
                        _fill("2026-09-09", ticker="HGLG11", hora="10:02:00"),
                        _fill("2026-09-09", ticker="WINZ26", hora="10:03:00"),
                        _fill("2026-09-09", ticker="PETRE30", hora="10:04:00")], caminho=af)
    classe = dict(zip(lo.operacoes(caminho=af)["ticker"], lo.operacoes(caminho=af)["classe"]))
    assert classe["PETR4"] == "acao" and classe["AAPL34"] == "bdr"
    assert classe["WINZ26"] == "futuro" and classe["PETRE30"] == "opcao"
    assert classe["HGLG11"] == "acao"                       # 11 e ambiguo: assume acao
    com_mapa = lo.operacoes(classes={"HGLG11": "fii"}, caminho=af)
    assert com_mapa.set_index("ticker").loc["HGLG11", "classe"] == "fii"


def test_operacoes_sem_fills_devolve_o_esquema_vazio(arqs):
    _, af = arqs
    op = lo.operacoes(fills=[], caminho=af)
    assert len(op) == 0 and list(op.columns) == lo.COLUNAS_OPERACAO


# ─────────────────────────────────────────────────────────────
# Conferencia contra a corretora e resumo
# ─────────────────────────────────────────────────────────────
def test_conferir_mostra_so_as_divergencias(arqs):
    _, af = arqs
    lo.registrar_fills([_fill("2026-09-09", ticker="PETR4", qtd=100, preco=10.0),
                        _fill("2026-09-09", ticker="VALE3", qtd=200, preco=60.0,
                              hora="10:01:00")], caminho=af)
    p = lo.posicao(caminho=af)
    d = lo.conferir(p, {"PETR4": 100, "VALE3": 200, "ITUB4": 300})
    assert list(d.columns) == lo.COLUNAS_CONFERENCIA
    assert d["ticker"].tolist() == ["ITUB4"]
    assert abs(d["qtd_livro"].iloc[0] - 0.0) < 1e-12
    assert abs(d["diferenca"].iloc[0] - (0 - 300)) < 1e-12
    d2 = lo.conferir(p, {"PETR4": 200, "VALE3": 200})       # desdobramento nao registrado
    assert d2["ticker"].tolist() == ["PETR4"]
    assert abs(d2["diferenca"].iloc[0] - (100 - 200)) < 1e-12


def test_conferir_devolve_vazio_quando_o_livro_bate_com_o_extrato(arqs):
    _, af = arqs
    lo.registrar_fills([_fill("2026-09-09", qtd=100, preco=10.0)], caminho=af)
    extrato = pd.DataFrame([{"ticker": "PETR4", "quantidade": "100"}])
    d = lo.conferir(lo.posicao(caminho=af), extrato)
    assert len(d) == 0 and list(d.columns) == lo.COLUNAS_CONFERENCIA


def test_resumo_conta_fills_periodo_giro_custos_e_origens(arqs):
    _, af = arqs
    lo.registrar_fills([_fill("2026-09-09", qtd=100, preco=10.0, corretagem=4.20),
                        _fill("2026-09-11", ticker="VALE3", qtd=50, preco=60.0,
                              emolumentos=0.90, origem="real")], caminho=af)
    r = lo.resumo(caminho=af)
    assert r["n_fills"] == 2 and r["n_tickers"] == 2
    assert r["primeiro"] == "2026-09-09" and r["ultimo"] == "2026-09-11"
    assert abs(r["financeiro_total"] - (100 * 10.0 + 50 * 60.0)) < 1e-12
    assert abs(r["custos_totais"] - (4.20 + 0.90)) < 1e-12
    assert r["origens"] == {"paper": 1, "real": 1} and r["posicoes_negativas"] == []


# ─────────────────────────────────────────────────────────────
# Ausencia de arquivo, entrada vazia e erro do usuario
# ─────────────────────────────────────────────────────────────
def test_arquivo_ausente_devolve_o_esquema_vazio_em_todo_leitor(tmp_path):
    ausente = str(tmp_path / "nao_existe.csv")
    assert list(lo.carregar_ordens(caminho=ausente).columns) == lo.COLUNAS_ORDEM
    assert list(lo.carregar_fills(caminho=ausente).columns) == lo.COLUNAS_FILL
    assert list(lo.posicao(caminho=ausente).columns) == lo.COLUNAS_POSICAO
    assert list(lo.operacoes(caminho=ausente).columns) == lo.COLUNAS_OPERACAO
    assert len(lo.carregar_ordens(caminho=ausente)) == 0
    assert lo.resumo(caminho=ausente) == {"n_fills": 0, "n_tickers": 0, "primeiro": None,
                                          "ultimo": None, "financeiro_total": 0.0,
                                          "custos_totais": 0.0, "posicoes_negativas": [],
                                          "origens": {}}
    assert not os.path.exists(ausente)                      # ler nao cria arquivo


def test_arquivo_ilegivel_nao_levanta(arqs):
    _, af = arqs
    open(af, "w", encoding="utf-8").write("isto nao e um csv de fills\n\x00\n")
    assert len(lo.carregar_fills(caminho=af)) >= 0          # so nao pode levantar
    assert list(lo.posicao(caminho=af).columns) == lo.COLUNAS_POSICAO


def test_linha_corrompida_no_meio_do_arquivo_e_ignorada_sem_derrubar_o_resto(arqs):
    """Arquivo editado errado a mao: a linha invalida some da posicao (com aviso no log) e
    o resto do livro continua respondendo."""
    _, af = arqs
    lo.registrar_fills([_fill("2026-09-09", qtd=100, preco=10.0)], caminho=af)
    with open(af, "a", encoding="utf-8") as f:
        f.write(lo.SEP.join(["", "", "", "", "", "", "", "", "", "", ""]) + "\n")
    assert len(lo.carregar_fills(caminho=af)) == 2          # o leitor e fiel ao arquivo
    p = lo.posicao(caminho=af)
    assert len(p) == 1 and abs(p["qtd"].iloc[0] - 100) < 1e-12
    assert lo.resumo(caminho=af)["n_fills"] == 1
    assert len(lo.operacoes(caminho=af)) == 1


def test_registrar_nada_nao_cria_arquivo(arqs):
    ao, af = arqs
    assert len(lo.registrar_ordens(None, "2026-09-08", "b", caminho=ao)) == 0
    assert len(lo.registrar_ordens(pd.DataFrame(), "2026-09-08", "b", caminho=ao)) == 0
    assert len(lo.registrar_fills([], caminho=af)) == 0
    assert not os.path.exists(ao) and not os.path.exists(af)


def test_ordem_de_quantidade_zero_nao_e_ordem(arqs):
    ao, _ = arqs
    assert len(lo.registrar_ordens(_ordens(qtd=0), "2026-09-08", "b", caminho=ao)) == 0


def test_lado_status_e_origem_invalidos_levantam(arqs):
    ao, af = arqs
    with pytest.raises(ValueError):
        lo.registrar_ordens(_ordens().assign(lado="X"), "2026-09-08", "b", caminho=ao)
    with pytest.raises(ValueError):
        lo.registrar_ordens(_ordens().assign(status="mandada"), "2026-09-08", "b", caminho=ao)
    with pytest.raises(ValueError):
        lo.registrar_fills([_fill("2026-09-09", origem="simulado")], caminho=af)


def test_fill_sem_data_ou_sem_quantidade_levanta(arqs):
    _, af = arqs
    with pytest.raises(ValueError):
        lo.registrar_fills([_fill("", qtd=100)], caminho=af)
    with pytest.raises(ValueError):
        lo.registrar_fills([_fill("2026-09-09", qtd=0)], caminho=af)
    assert not os.path.exists(af)


def test_csv_editado_a_mao_com_virgula_decimal_e_data_br_ainda_le(arqs):
    """O usuario abre o livro no Excel e salva: virgula decimal e dd/mm/aaaa voltam."""
    _, af = arqs
    open(af, "w", encoding="utf-8").write(
        lo.SEP.join(lo.COLUNAS_FILL) + "\n"
        + lo.SEP.join(["09/09/2026", "10:00:00", "b", "PETR4", "C", "100", "10,50",
                       "4,20", "0,31", "real", "editado a mao"]) + "\n")
    f = lo.carregar_fills(caminho=af)
    assert f["data"].iloc[0] == pd.Timestamp("2026-09-09")
    assert abs(f["preco"].iloc[0] - 10.50) < 1e-12
    assert abs(lo.posicao(caminho=af)["custo_total"].iloc[0] - (100 * 10.50 + 4.20 + 0.31)) < 1e-12


# ─────────────────────────────────────────────────────────────
# Linha de comando
# ─────────────────────────────────────────────────────────────
def test_main_resumo_sem_dados_devolve_zero(arqs, capsys):
    assert lo.main(["--resumo"]) == 0
    assert lo.main([]) == 0                                  # o padrao e o resumo
    assert "fills 0" in capsys.readouterr().out


def test_main_posicao_e_conferir(arqs, tmp_path, capsys):
    _, af = arqs
    lo.registrar_fills([_fill("2026-09-09", qtd=100, preco=10.0)], caminho=af)
    assert lo.main(["--posicao"]) == 0
    assert "PETR4" in capsys.readouterr().out
    extrato = tmp_path / "extrato.csv"
    extrato.write_text("ticker;qtd\nPETR4;100\n", encoding="utf-8")
    assert lo.main(["--conferir", str(extrato)]) == 0
    extrato.write_text("ticker;qtd\nPETR4;50\n", encoding="utf-8")
    assert lo.main(["--conferir", str(extrato)]) == 1        # divergiu: sai com 1
    assert lo.main(["--conferir", str(tmp_path / "nao_existe.csv")]) == 2
