"""Painel do contador de bolsa: a pagina montada com um titular inventado, o simulador, o servidor local e a
conciliacao de nota que liquida no mes seguinte. Sem rede (precos da B3 e PDF do relatorio trocados por respostas
locais).

Os dados sao inventados (FULANO DE TAL, CPF zerado). Todo arquivo gerado fica em tmp_path.
"""

import datetime as dt
import http.client
import json
import os
import pathlib
import re
import sys
import threading
from http.server import ThreadingHTTPServer

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_DIR = os.path.join(RAIZ, "ferramentas", "local")
for p in (RAIZ, LOCAL_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from contador_bolsa import apuracao, cli, eventos, mes, notas, painel, precos, relatorio  # noqa: E402
from contador_bolsa.apuracao import Posicao  # noqa: E402

D = dt.date
HOJE = D(2026, 11, 3)
VENDA_VALE = {"pregao": "2026-10-20", "liquidacao": "2026-10-21", "cv": "V", "ticker": "VALE3", "ativo": "VALE ON",
              "classe": "acao", "qtd": 1000, "total": 60000.0, "fonte": "teste"}
LIQ_0311 = {"date": "2026-11-03", "amount": -3000.0, "description": "LIQUIDACAO NOTA RENDA VARIAVEL"}


@pytest.fixture(autouse=True)
def sem_rede(monkeypatch):
    monkeypatch.setattr(precos, "fechamento", lambda dia, tickers, cache=None, volta=15: {})
    monkeypatch.setattr(precos, "pregao", lambda dia, cache=None: {})
    monkeypatch.setattr(eventos, "_pede", lambda cod: [])           # cadastro de eventos da B3
    monkeypatch.setattr(precos, "_instrumentos", lambda dia: None)   # cadastro de instrumentos da B3

    def relatorio_falso(dados, destino, senha=None):
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(b"%PDF-1.4 relatorio de teste")
        return destino

    monkeypatch.setattr(relatorio, "pdf_relatorio", relatorio_falso)


# ------------------------------------------------------------------ apoio
def _of(*extra, lido_em="2026-11-03T08:00:00"):
    t = [{"date": "2026-10-15", "amount": 120.0, "description": "DIVIDENDOS VALE"},
         {"date": "2026-10-21", "amount": 60000.0, "description": "LIQUIDACAO NOTA RENDA VARIAVEL"}] + list(extra)
    return {"lido_em": lido_em, "conexoes": [{"transacoes": t}]}


def _titular(tmp_path, fechar=True):
    """2.000 VALE3 a R$ 50 e R$ 1.000 de prejuizo comum em 30/09; venda de 1.000 VALE3 a R$ 60 em 20/10 (DARF de
    outubro de R$ 1.350,00: 10.000 menos 1.000 de prejuizo, a 15%); outubro fechado como a rotina diaria faz."""
    base = tmp_path / "titular"
    base.mkdir()
    (base / "titular.json").write_text(json.dumps({"nome": "FULANO DE TAL", "documento": "000.000.000-00",
                                                   "telefone": "(11) 98888-7777", "corretora": "SAFRA CORRETORA",
                                                   "email": "fulano@example.com"}))
    (base / "partida.json").write_text(json.dumps({
        "data": "2026-09-30", "origem": "teste",
        "posicoes": [apuracao.posicao_dict(Posicao("VALE3", "VALE ON", "acao", 2000, 100000.0))],
        "prejuizos": {"comum": -1000.0, "daytrade": 0.0, "fii": 0.0}, "irrf": 0.0, "pendente": 0.0}))
    (base / "manuais.json").write_text(json.dumps([VENDA_VALE]))
    if fechar:
        mes.fecha_mes(base, 2026, 10, _of(), HOJE)
    return base


def _nota(numero, pregao, liquidacao, cv, ticker, qtd, preco):
    valor = round(qtd * preco, 2)
    nt = notas.Nota(numero, pregao, "teste.pdf")
    nt.liquidacao, nt.liquido = liquidacao, valor if cv == "V" else -valor
    nt.negocios.append(notas.Negocio(pregao, numero, 0, cv, "VISTA", None, ticker, qtd, preco, valor, ticker, ticker,
                                     "acao"))
    return nt


# ------------------------------------------------------------------ conciliacao (motor)
def test_nota_que_liquida_no_mes_seguinte_concilia_no_mes_da_liquidacao(tmp_path):
    # a nota de 29/10/2026 que liquidou em 03/11 aparecia como faltando no Open Finance no fechamento de outubro
    nt = _nota("900001", D(2026, 10, 29), D(2026, 11, 3), "C", "ITUB4", 100, 30.0)
    of = mes.transacoes_of(_of(LIQ_0311))
    out = mes.concilia([nt], of, D(2026, 10, 1), D(2026, 10, 31))
    assert out["sem_lancamento"] == [] and out["ultimo_of"] == D(2026, 11, 3)
    nov = mes.concilia([nt], of, D(2026, 11, 1), D(2026, 11, 30))
    assert [n.numero for _, n in nov["casadas"]] == ["900001"] and nov["sem_nota"] == nov["sem_lancamento"] == []
    # no fechamento de outubro a compra entra no mes do pregao e nao vira alerta de nota sem lancamento
    base = _titular(tmp_path, fechar=False)
    r = mes.fecha_mes(base, 2026, 10, _of(LIQ_0311), HOJE, gravar=False, extras=[nt])
    assert not any("900001" in a for a in r["dados"]["situacao"]["alertas"])
    assert any(p["ticker"] == "ITUB4" and p["qtd"] == 100 for p in r["estado"]["posicoes"])
    assert r["apuracao"]["darf"] == 1350.0 and not (base / "estado").exists()


# ------------------------------------------------------------------ pagina
def test_painel_mostra_o_darf_e_nunca_o_documento(tmp_path):
    base = _titular(tmp_path)
    (base / "irtrade").mkdir()
    (base / "irtrade" / "2026-11-03.json").write_text(json.dumps({"lido_em": "2026-11-03T14:00:00",
                                                                  "ultimo_consolidado": "2026-09"}))
    d = painel.dados(base, _of(), HOJE)
    assert (d["ultimo"], d["atual"], d["cur"]["status"]) == ((2026, 10), (2026, 11), "parcial")
    v = d["vigente"]
    assert (v["valor"], v["vencimento"], v["situacao"], v["classe"]) == \
        (1350.0, "30/11/2026", "a pagar: faltam 27 dias", "alerta")
    assert d["proventos_ano"] == [("DIVIDENDOS", "Dividendos", 120.0, 1)]
    pag = painel.montar(base, _of(), HOJE)
    assert "R$ 1.350,00" in pag and "30/11/2026" in pag and "consolidado até 09/2026" in pag
    for k, _ in painel.MENU:                                       # as 13 paginas do menu
        assert f'id="p-{k}"' in pag
    for proibido in ("000.000.000-00", "00000000000", "98888-7777", "11988887777"):
        assert proibido not in pag
    assert not re.search(r"""\bsrc\s*=\s*["']?(https?:)?//""", pag)   # nada de fora carrega na pagina
    assert "@import" not in pag and "url(http" not in pag
    with pytest.raises(RuntimeError):
        painel._confere_sem_documento("<p>CPF 000.000.000-00</p>", base, None)
    arq = painel.gera(base, _of(), HOJE)
    assert arq == base / "saida" / "painel.html" and not arq.with_name("painel.html.tmp").exists()


def test_pendencias_uma_lista_so_e_o_ecac_entra_nela(tmp_path):
    base = _titular(tmp_path)
    (base / "ecac.json").write_text(json.dumps({
        "lido_em": "2026-11-03T10:00:00",
        "declaracoes": [{"exercicio": 2026, "ano_calendario": 2025, "tipo": "Original", "situacao": "Processada"}],
        "debitos": [{"descricao": "IRPF 2026", "valor": 123.45, "vencimento": "30/04/2026", "situacao": "em aberto"}],
        "pendencias": [{"descricao": "Declaração em malha", "situacao": "aguardando"}],
        "certidao": {"tipo": "positiva", "validade": "2026-12-01"}}))
    d = painel.dados(base, _of(), HOJE)
    ps = d["pendencias"]
    niveis = {p["texto"]: p["nivel"] for p in ps}
    assert niveis["Débito no e-CAC: IRPF 2026, R$ 123,45, vencimento 30/04/2026."] == "erro"
    assert niveis["Declaração em malha: aguardando"] == "alerta"
    assert [p["nivel"] for p in ps] == sorted((p["nivel"] for p in ps), key=painel.NIVEL.get)   # urgente primeiro
    assert painel._pior(ps) == "erro" and painel._pior([]) == "ok"
    # selo do menu, cartao Ola e quadrinho do CPF contam a mesma lista
    n = len(ps)
    pag = painel.html(d)
    assert f'<span class="conta">{n}</span>' in pag
    assert len(re.findall(rf'<span class="chip erro">{n} pendências</span>', pag)) >= 2
    cpf = painel._pg_cpf(d)
    assert "válida até 01/12/2026" in cpf and "1 em aberto" in cpf and "Processada" in cpf



def test_ecac_com_tela_fora_do_ar_vira_lacuna_e_certidao_sem_validade_diz_a_situacao(tmp_path):
    base = _titular(tmp_path)
    (base / "ecac.json").write_text(json.dumps({
        "lido_em": "2026-11-07T08:50:00", "declaracoes": [], "debitos": [], "pendencias": [],
        "certidao": {"tipo": "negativa", "validade": None, "situacao": "sem pendência para emitir"},
        "lacunas": ["Comprovantes de pagamento do e-CAC fora do ar em 07/11 (erro 503)."]}))
    d = painel.dados(base, _of(), HOJE)
    (lac,) = [p for p in d["pendencias"] if p["origem"] == "e-CAC"]
    assert lac["nivel"] == "info" and lac["texto"].startswith("Comprovantes de pagamento")
    cpf = painel._pg_cpf(d)
    assert "sem pendência para emitir" in cpf and "válida até -" not in cpf
    assert "a tela não abriu na última leitura" in cpf and "0 declarações" not in cpf



def test_darf_pago_sem_a_data_sai_das_pendencias(tmp_path, capsys):
    base = _titular(tmp_path)
    (base / "historico.json").write_text(json.dumps({"darfs": [
        {"periodo": "03/2026", "valor": 100.0, "vencimento": "30/04/2026", "fonte": "IRTrade"}]}))
    of = _of({"date": "2026-04-01", "amount": 10.0, "description": "PIX RECEBIDO"})    # extrato desde antes do vencimento
    d = painel.dados(base, of, HOJE)
    assert any(p["texto"].startswith("DARF de 03/2026") for p in d["pendencias"])
    assert cli.main(["--titular", str(base), "pago", "2026-03", "--fonte", "informado pelo titular"]) == 0
    assert "pago (sem a data)" in capsys.readouterr().out
    d = painel.dados(base, of, HOJE)
    (x,) = [x for x in d["darfs"] if x["periodo"] == "03/2026"]
    assert x["classe"] == "ok" and x["situacao"] == "pago, sem a data (informado pelo titular)"
    assert not any(p["texto"].startswith("DARF de 03/2026") for p in d["pendencias"])
    # o relatorio mensal (situacao fiscal) le o mesmo registro: em 07/11/2026 ele ainda dizia "sem pagamento no Safra"
    r = mes.fecha_mes(base, 2026, 10, of, HOJE, gravar=False)["dados"]["situacao"]
    (x,) = [x for x in r["darfs"] if x["periodo"] == "03/2026"]
    assert x["situacao"] == "pago, sem a data" and not any(a.startswith("DARF de 03/2026") for a in r["alertas"])


def test_open_finance_com_problema_e_rotina_parada_viram_pendencia(tmp_path):
    base = _titular(tmp_path)
    (base / "estado").mkdir(exist_ok=True)
    (base / "estado" / "diario.json").write_text(json.dumps({"ultima": "2026-11-03T09:21:00"}))
    of = _of(lido_em="2026-11-04T08:00:00")
    of["conexoes"][0]["item"] = {"connector": {"name": "BancoTeste"}, "status": "UPDATED",
                                 "lastUpdatedAt": "2026-11-04T07:00:00", "consentExpiresAt": "2026-11-20T15:00:00Z"}
    d = painel.dados(base, of, D(2026, 11, 4))                    # rodou ontem: rotina em dia
    assert d["saude"]["rotina"] == [] and [p["origem"] for p in d["pendencias"]].count("Open Finance") == 1
    assert "atenção" in painel._integracoes(d) and "parada" not in painel._integracoes(d)
    d = painel.dados(base, of, D(2026, 11, 6))                    # sem rodada na quarta nem na quinta
    (rot,) = [p for p in d["pendencias"] if p["origem"] == "rotina diária"]
    assert rot["texto"].startswith("A rotina diária do contador não roda desde 03/11") and rot["nivel"] == "alerta"
    assert "parada" in painel._integracoes(d)
    of["conexoes"][0]["item"]["consentExpiresAt"] = "2026-11-01T15:00:00Z"
    d = painel.dados(base, of, D(2026, 11, 4))
    assert d["pendencias"][0]["origem"] == "Open Finance" and d["pendencias"][0]["nivel"] == "erro"


def test_proventos_separam_os_custos_do_aluguel():
    pr = [("DIVIDENDOS", "Dividendos", 100.0, 2), ("RENDIMENTOS BTC DOADOR", "Remuneração do aluguel", 50.0, 1),
          ("DESPESAS OPERACIONAIS - BTC", "Corretagem do aluguel", -5.0, 1)]
    h = painel._tabela_proventos(pr)
    assert h.index("Total recebido") < h.index("Custos do aluguel de ações") < h.index("Corretagem do aluguel") \
        < h.index("Líquido")
    assert "R$ 150,00" in h and "-R$ 5,00" in h and "R$ 145,00" in h
    h = painel._tabela_proventos(pr[:2])                           # sem custo: so o total recebido
    assert "R$ 150,00" in h and "Líquido" not in h and "Custos do aluguel" not in h


def test_conferencia_do_cartao_de_12_meses_soma_os_itens_do_proprio_cartao(tmp_path):
    # o cartao da IRTrade mostrou a soma ja sem impostos e descontou os impostos de novo no liquido (03/11/2026)
    base = _titular(tmp_path)
    itens = dict.fromkeys(painel.COLS_12M, 0.0) | {"comum": 1000.0, "proventos": 500.0}
    (base / "conferencias.json").write_text(json.dumps({"irtrade_12m": {
        **itens, "soma": 1400.0, "impostos_despesas": -100.0, "liquido": 1300.0}}))
    h = painel._pg_conferencia(painel.dados(base, _of(), HOJE))
    assert re.search(r"Soma das parcelas.*?R\$ 1\.400,00.*?R\$ 1\.500,00", h)
    assert re.search(r"Líquido</td>.*?R\$ 1\.300,00.*?R\$ 1\.400,00", h)


def test_ajuste_decidido_vale_no_consolidado_e_na_ficha_do_ir(tmp_path):
    # o retrato da IRTrade fica como ela mostrou; o ajuste do titular (historico.json) entra no consolidado e na ficha
    # "Renda Variavel", e o prejuizo que ele muda passa para o mes seguinte dela
    base = _titular(tmp_path)
    cols = ["mes", "vista_dt", "opcao_dt", "resultado_dt", "negativo_anterior_dt", "base_dt", "prejuizo_dt",
            "imposto_dt", "imposto_total", "imposto_pagar"]
    rv = [[m, 0, 0, 0, -500.0, 0, -500.0, 0, 0, 0] for m in range(1, 8)] + \
         [[8, 0, -100.0, -100.0, -500.0, 0, -600.0, 0, 0, 0], [9, 50.0, 0, 50.0, -600.0, 0, -550.0, 0, 0, 0]]
    cs = [[f"2026-{m:02d}", 0, -100.0 if m == 8 else 0, 0, 0] for m in range(1, 10)]
    (base / "irtrade").mkdir()
    (base / "irtrade" / "2026-11-03.json").write_text(json.dumps({
        "ultimo_consolidado": "2026-09", "renda_variavel_2026": {"colunas": cols, "linhas": rv},
        "consolidado_12m": {"colunas": ["mes", "comum", "daytrade", "despesas", "impostos"], "linhas": cs}}))
    (base / "historico.json").write_text(json.dumps({"ajustes": [
        {"mes": "2026-08", "tipo": "daytrade", "classe": "opcao", "antes": -100.0, "depois": -98.0}]}))
    d = painel.dados(base, _of(), HOJE)
    ago = next(x for x in d["doze"] if x["mes"] == (2026, 8))
    assert (ago["vals"]["daytrade"], ago["fonte"]) == (-98.0, "IRTrade, ajustado")
    fr = {m: (row, f) for m, row, f in d["ficha_rv"]}
    row, f = fr[8]
    assert (row["opcao_dt"], row["resultado_dt"], row["prejuizo_dt"], row["imposto_dt"], f) == \
        (-98.0, -98.0, -598.0, 0.0, "IRTrade, ajustado")
    row, f = fr[9]                                  # setembro dela parte do prejuizo ajustado
    assert (row["negativo_anterior_dt"], row["prejuizo_dt"], f) == (-598.0, -548.0, "IRTrade, ajustado")
    assert fr[7][1] == "IRTrade" and fr[10][1].startswith("agente")
    assert painel.AJUSTADO in painel._pg_meuir(d) and painel.AJUSTADO in painel._pg_consolidado(d)
    assert json.loads((base / "irtrade" / "2026-11-03.json").read_text())["renda_variavel_2026"]["linhas"][7][2] \
        == -100.0


def test_mes_fechado_diferente_da_irtrade_em_proventos_ou_aluguel_vira_pendencia(tmp_path):
    # 07/11/2026: o reembolso de aluguel de 01/10 estava marcado como ja contado no mes anterior, e o aluguel de outubro
    # do agente saiu abaixo do da IRTrade sem nenhum aviso; proventos, aluguel e despesas saem dos mesmos
    # creditos do banco nos dois, entao qualquer diferenca vira pendencia
    reembolso = {"date": "2026-10-01", "amount": 40.0, "description": "CREDITO EMPRESTIMO BOVESPA"}
    base = _titular(tmp_path, fechar=False)
    p = json.loads((base / "partida.json").read_text())
    p["of_ja_contado"] = [{"data": "2026-10-01", "descricao": "CREDITO EMPRESTIMO BOVESPA", "valor": 40.0}]
    (base / "partida.json").write_text(json.dumps(p))
    mes.fecha_mes(base, 2026, 10, _of(reembolso), HOJE)
    (base / "irtrade").mkdir()
    (base / "irtrade" / "2026-11-03.json").write_text(json.dumps({
        "ultimo_consolidado": "2026-09",
        "renda_variavel_2026": {"colunas": ["mes", "resultado_comum", "imposto_pagar"],
                                "linhas": [[m, 0, 0] for m in range(1, 10)] + [[10, 10000.0, 1350.0]]},
        "meses_api": {"colunas": ["mes", "proventos", "btc", "despesas"], "parcial": ["2026-11"],
                      "linhas": [["2026-10", 120.0, 40.0, 0.0], ["2026-11", 0.0, 99.0, 0.0]]}}))
    (aviso,) = mes.confere_irtrade(base)                           # novembro e parcial: fica de fora
    assert aviso.startswith("10/2026: aluguel de ações (BTC doador) do agente R$ 0,00, IRTrade R$ 40,00")
    d = painel.dados(base, _of(reembolso), HOJE)
    assert any(x["texto"] == aviso and x["nivel"] == "alerta" for x in d["pendencias"])
    (out,) = d["conferencia"]["meses"]
    assert ("Aluguel de ações (BTC doador)", 40.0, 0.0) in out["linhas"] and ("Proventos", 120.0, 120.0) in out["linhas"]
    assert aviso in cli.diario(base, _of(reembolso), HOJE)["alertas"]
    p["of_ja_contado"] = []                                        # marca tirada e mes refeito: some o aviso
    (base / "partida.json").write_text(json.dumps(p))
    mes.fecha_mes(base, 2026, 10, _of(reembolso), HOJE)
    assert mes.confere_irtrade(base) == []
    assert json.loads((base / "estado" / "2026-10.json").read_text())["anual"]["BTC DOADOR"] == 40.0


def test_chip_longo_quebra_o_texto_depois_dos_dois_pontos():
    h = painel.chip_longo("a pagar: faltam 27 dias", "alerta")
    assert h == painel.chip("a pagar", "alerta") + '<small class="q rot">faltam 27 dias</small>'
    assert painel.chip_longo("conferida no Open Finance", "ok") == painel.chip("conferida no Open Finance", "ok")


def test_rotina_diaria_grava_o_painel_junto(tmp_path):
    base = _titular(tmp_path, fechar=False)
    res = cli.diario(base, _of(), HOJE)
    assert "painel_erro" not in res and "R$ 1.350,00" in pathlib.Path(res["painel"]).read_text()


# ------------------------------------------------------------------ simulador
def test_simulador_mostra_imposto_isencao_e_o_vencimento_de_30_12(tmp_path):
    base = _titular(tmp_path)
    s = painel.simular(base, _of(), HOJE, {"ticker": "vale3", "cv": "V", "qtd": "1.000", "preco": "65,00"})
    assert s["ok"] and s["valor"] == 65000.0 and s["resultado"]["comum"] == 15000.0      # 1.000 x (65 - 50)
    assert (s["darf_antes"], s["darf_depois"], s["vencimento"]) == (0.0, 2250.0, "30/12/2026")   # REGRAS.md, DARF
    assert s["isento_antes"] and not s["isento_depois"]
    assert s["avisos"][0].startswith("Com esta venda as vendas de ações do mês passam de R$ 20.000,00")
    assert len(s["avisos"]) == 1
    h = painel.html_simulacao(s)
    assert "perde a isenção" in h and "R$ 2.250,00" in h
    # venda pequena fica na isencao (IN RFB 1.585/2015, art. 59, I)
    s = painel.simular(base, _of(), HOJE, {"ticker": "VALE3", "cv": "V", "qtd": "100", "preco": "65"})
    assert s["resultado"]["isento"] == 1500.0 and s["darf_depois"] == 0.0 and s["avisos"] == []
    # compra: o preco medio novo
    s = painel.simular(base, _of(), HOJE, {"ticker": "VALE3", "cv": "C", "qtd": "1000", "preco": "70"})
    assert (s["qtd_depois"], s["pm_depois"]) == (2000, 60.0)
    # nada grava: o mes em curso continua sem fechamento
    assert sorted(p.name for p in (base / "estado").iterdir()) == ["2026-10.json"]


@pytest.mark.parametrize("pedido, erro", [
    ({"ticker": "PETR4", "cv": "V", "qtd": "100", "preco": "30"}, "PETR4 não está na carteira"),
    ({"ticker": "VALE3", "cv": "V", "qtd": "1001", "preco": "65"}, "venda a descoberto"),
    ({"ticker": "VALE3", "cv": "V", "qtd": "dez", "preco": "65"}, "precisam ser números"),
    ({"ticker": "VALE3", "cv": "X", "qtd": "10", "preco": "65"}, "compra ou venda"),
    ({"ticker": "VALE3", "cv": "V", "qtd": "0", "preco": "65"}, "fora do razoável"),
    ({"ticker": "../x", "cv": "V", "qtd": "10", "preco": "65"}, "compra ou venda"),
])
def test_simulador_recusa_pedido_errado(tmp_path, pedido, erro):
    s = painel.simular(_titular(tmp_path), _of(), HOJE, pedido)
    assert erro in s["erro"]


def test_simulador_so_no_mes_em_apuracao(tmp_path):
    s = painel.simular(_titular(tmp_path), _of(), D(2026, 12, 2), {"ticker": "VALE3", "cv": "V", "qtd": "10",
                                                                  "preco": "65"})
    assert s["erro"].startswith("O mês em apuração (11/2026) não é o de hoje")


# ------------------------------------------------------------------ servidor local
@pytest.fixture
def servidor(tmp_path):
    base = _titular(tmp_path)
    (base / "saida").mkdir(exist_ok=True)
    (base / "saida" / "DARF 10-2026.pdf").write_bytes(b"%PDF-1.4 darf de teste")
    (tmp_path / "of.json").write_text(json.dumps(_of()))
    app = painel.Servidor(base, tmp_path / "of.json", porta=0, hoje=HOJE)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), painel._handler(app))
    app.porta = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield app.porta
    finally:
        srv.shutdown()
        srv.server_close()


def _pede(porta, metodo, caminho, corpo=None, cab=None):
    c = http.client.HTTPConnection("127.0.0.1", porta, timeout=60)
    try:
        c.request(metodo, caminho, body=corpo, headers=cab or {})
        r = c.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    finally:
        c.close()


def _cru(porta, cab):
    """POST sem corpo, com os cabecalhos como vierem (Content-Length inclusive)."""
    c = http.client.HTTPConnection("127.0.0.1", porta, timeout=60)
    try:
        c.putrequest("POST", "/simular")
        for k, v in cab.items():
            c.putheader(k, v)
        c.endheaders()
        return c.getresponse().status
    finally:
        c.close()


def test_servidor_so_atende_local_e_so_os_pdfs_do_mes(servidor):
    st, cab, corpo = _pede(servidor, "GET", "/")
    assert st == 200 and "R$ 1.350,00" in corpo.decode()
    assert cab["X-Frame-Options"] == "DENY" and cab["Cache-Control"] == "no-store"
    assert "default-src 'none'" in cab["Content-Security-Policy"] and cab["X-Content-Type-Options"] == "nosniff"
    st, cab, corpo = _pede(servidor, "GET", "/DARF%2010-2026.pdf")
    assert (st, cab["Content-Type"], corpo) == (200, "application/pdf", b"%PDF-1.4 darf de teste")
    for caminho in ("/titular.json", "/../titular.json", "/%2e%2e/titular.json", "/saida/DARF%2010-2026.pdf",
                    "/DARF%2010-2026.pdf%00", "/DARF%2010-2026.pdf/../../titular.json", "/DARF%2011-2026.pdf"):
        assert _pede(servidor, "GET", caminho)[0] == 404, caminho
    assert _pede(servidor, "GET", "/", cab={"Host": "evil.example"})[0] == 403


def test_simulador_pelo_servidor_so_com_json_da_propria_pagina(servidor):
    pedido = json.dumps({"ticker": "VALE3", "cv": "V", "qtd": "100", "preco": "65"}).encode()
    js = {"Content-Type": "application/json"}
    st, _, corpo = _pede(servidor, "POST", "/simular", pedido, {**js, "Origin": f"http://127.0.0.1:{servidor}"})
    r = json.loads(corpo)
    assert st == 200 and r["ok"] and r["resultado"]["isento"] == 1500.0 and "<dl" in r["html"]
    assert _pede(servidor, "POST", "/simular", None, {"Content-Type": "text/plain"})[0] == 415
    assert _pede(servidor, "POST", "/simular", None, {**js, "Origin": "http://evil.example"})[0] == 403
    assert _pede(servidor, "POST", "/simular", None, {**js, "Host": "evil.example"})[0] == 403
    assert _pede(servidor, "POST", "/simular", b"{nao e json", js)[0] == 400
    assert _pede(servidor, "POST", "/outra", pedido, js)[0] == 404
    assert _cru(servidor, {**js, "Content-Length": "10001"}) == 413
    assert _cru(servidor, {**js, "Content-Length": "abc"}) == 400
    assert _cru(servidor, {**js, "Content-Length": "-5"}) == 400


# ------------------------------------------------------------------ custodia, eventos da B3 e vencimento
def _titular_opcoes(tmp_path, monkeypatch):
    """Partida de 31/10 sem prejuizo: 500 AAAA3 a R$ 10 e duas puts lancadas que vencem em 19/11 (AAAAW100 strike 10,
    BBBBW200 strike 20); o banco mostra as 500 AAAA3 e R$ 1.234,56 na conta; a B3 publicou um desdobramento de AAAA3."""
    base = _titular(tmp_path, fechar=False)
    put = dict(vencimento=D(2026, 11, 19), tipo_opcao="put")
    pos = [Posicao("AAAA3", "AAAA ON", "acao", 500, 5000.0),
           Posicao("AAAAW100", "AAAA3 put", "opcao", -1000, -300.0, strike=10.0, subjacente="AAAA3", **put),
           Posicao("BBBBW200", "BBBB3 put", "opcao", -500, -250.0, strike=20.0, subjacente="BBBB3", **put)]
    p = json.loads((base / "partida.json").read_text())
    p.update(data="2026-10-31", posicoes=[apuracao.posicao_dict(x) for x in pos],
             prejuizos={"comum": 0.0, "daytrade": 0.0, "fii": 0.0})
    (base / "partida.json").write_text(json.dumps(p))
    (base / "manuais.json").write_text("[]")
    cot = {"AAAA3": 9.5, "BBBB3": 21.0}
    monkeypatch.setattr(precos, "fechamento", lambda dia, tickers, cache=None, volta=15: {
        t: {"preco": cot[t], "fonte": "ultimo", "dia": "2026-11-09"} for t in tickers if t in cot})
    of = _of(lido_em="2026-11-10T08:00:00")
    of["conexoes"][0].update(
        investimentos=[{"type": "EQUITY", "subtype": "STOCK", "code": "AAAA3", "quantity": 500,
                        "date": "2026-11-10T00:00:00", "isin": None}],
        contas=[{"type": "BANK", "subtype": "CHECKING_ACCOUNT", "balance": 1234.56, "updatedAt": "2026-11-10T07:30:00"}])
    (base / "eventos_b3.json").write_text(json.dumps({
        "lido_em": "2026-11-10T09:10", "desde": "2026-10-31", "erros": [],
        "eventos": [{"ticker": "AAAA3", "tipo": "desdobramento", "data_com": "2026-11-20", "fator": 2.0,
                     "fonte": "B3, desdobramento aprovado em 05/11/2026"}]}))
    return base, of


def test_carteira_mostra_custodia_eventos_e_os_caminhos_do_vencimento(tmp_path, monkeypatch):
    base, of = _titular_opcoes(tmp_path, monkeypatch)
    d = painel.dados(base, of, D(2026, 11, 10))
    pag = painel._pg_carteira(d)
    for txt in ("Custódia no banco", '<span class="chip ok">confere</span>', "1 posição bate",
                "AAAA3: desdobramento de 1 para 2 com data com 20/11/2026", "B3, desdobramento aprovado em 05/11/2026",
                "Vencimento de 19/11: os caminhos", "Viram pó", "Todas exercidas", "Só AAAAW100 exercida",
                '<span class="chip info">provável</span>', "R$ 82,50", "R$ 37,50", "1.500 AAAA3 a PM R$ 9,80",
                "AAAA3 R$ 9,70 e BBBB3 R$ 19,50", "Conta corrente: R$ 1.234,56 em 10/11 às 07h30 (Open Finance)."):
        assert txt in pag, txt
    pg = painel.html(d)
    for txt in ('<span class="chip alerta">Vencimento</span>', '<span class="chip info">Evento</span>',
                '<span class="chip alerta">Opção</span>', '<span class="chip info">Opção</span>'):
        assert txt in pg, txt
    assert 'class="chip Opção"' not in pg and 'class="chip Vencimento"' not in pg     # o nivel e a classe, o rotulo e o texto
    assert "lido em 10/11 às 09h10; 1 evento desde 31/10/2026" in painel._integracoes(d)


def test_eventos_da_b3_sem_resposta_ou_sem_leitura_viram_pendencia(tmp_path):
    base = _titular(tmp_path)
    assert painel._eventos_b3(base, HOJE, False, [])["alertas"] == []                 # nunca lido: a linha da integracao diz
    arq = base / "eventos_b3.json"
    arq.write_text(json.dumps({"lido_em": "2026-10-29T09:10", "desde": "2026-09-30", "erros": ["VALE (OSError)"],
                               "eventos": []}))
    erro = "Eventos da B3 sem resposta na leitura de 29/10 para VALE (OSError): vale a leitura anterior dessas empresas."
    velho = ("Eventos da B3 não são lidos desde 29/10: a rotina diária lê a B3 em todo dia útil; sem a leitura, "
             "bonificação, desdobramento ou grupamento novo não entra na carteira.")
    assert painel._eventos_b3(base, HOJE, False, [])["alertas"] == [erro, velho]
    assert painel._eventos_b3(base, HOJE, True, [])["alertas"] == [erro]              # rotina parada: o alerta dela basta
    d = painel.dados(base, _of(), HOJE)
    assert [p["texto"] for p in d["pendencias"] if p["origem"] == "eventos da B3"] == [erro, velho]
    arq.write_text(json.dumps({"lido_em": "2026-10-30T09:10", "desde": "2026-09-30", "erros": [], "eventos": []}))
    assert painel._eventos_b3(base, HOJE, False, [])["alertas"] == []                 # 02/11 foi feriado: 30/10 vale
    d = painel.dados(base, _of(), HOJE)
    assert "Nenhum evento societário nos papéis da carteira com data com depois de 30/09/2026" in painel._pg_carteira(d)
    assert "lido em 30/10 às 09h10; nenhum evento desde 30/09/2026" in painel._integracoes(d)


@pytest.mark.parametrize("alerta, esperado", [
    ("Custódia de VALE3 no Safra em 27/10 (Open Finance): 900 no banco, 1.000 no motor.", ("Custódia", "alerta")),
    ("Vencimento de 19/11 (AAAAW100, put lançada): se virar pó... Com o fechamento de 09/11, nenhuma está do lado do "
     "exercício.", ("Vencimento", "info")),
    ("Vencimento de 19/11 (AAAAW100, put lançada): se virar pó... AAAA3 (9,50) está abaixo do strike de 10,00.",
     ("Vencimento", "alerta")),
    ("Na B3: subscrição de 10% a R$ 95,00 por papel com data com 20/10/2026 em FULA11.", ("Evento", "info")),
    ("Eventos da B3 sem resposta hoje para VALE (OSError): vale a leitura anterior dessas empresas.", ("Dado", "alerta")),
    ("A CONFERIR: as 100 VALE3 da bonificação de 10% entraram a custo zero.", ("A conferir", "alerta")),
    ("AAAAW100 (put de AAAA3, strike 10,00) vence em 19/11; AAAA3 fechou a 9,50 em 09/11, abaixo do strike: se ficar "
     "assim, o exercício gera a compra de 1.000 AAAA3.", ("Opção", "alerta")),
    ("BBBBW200 (put de BBBB3, strike 20,00) vence em 19/11; BBBB3 fechou a 21,00 em 09/11.", ("Opção", "info")),
])
def test_cada_alerta_tem_o_chip_certo(alerta, esperado):
    assert painel._classe_alerta(alerta) == esperado


def test_opcao_sem_strike_diz_sem_strike_ate_o_cadastro_da_b3_completar(tmp_path, monkeypatch):
    base, of = _titular_opcoes(tmp_path, monkeypatch)
    p = json.loads((base / "partida.json").read_text())
    p["posicoes"][2]["strike"] = None                                           # BBBBW200, como a IRTrade manda
    (base / "partida.json").write_text(json.dumps(p))
    assert '<span class="chip cinza">sem strike</span>' in painel._pg_carteira(painel.dados(base, of, D(2026, 11, 10)))
    monkeypatch.setattr(precos, "_instrumentos", lambda dia: [
        {"TckrSymb": "BBBBW200", "Asst": "BBBB3", "OptnTp": "Put", "ExrcPric": "20,00", "XprtnDt": "2026-11-19",
         "OptnStyle": "EURO"}])
    d = painel.dados(base, of, D(2026, 11, 10))
    pag = painel._pg_carteira(d)
    assert "sem strike" not in pag and "Todas exercidas" in pag
    assert ("BBBBW200: strike R$ 20,00 pelo cadastro de instrumentos da B3 de 09/11 (a posição veio sem esse dado)."
            in d["ref"]["out"]["dados"]["situacao"]["conferencia"])


def test_nota_com_venda_dividida_sai_da_conferencia_pelo_numero():
    # a conferencia guarda "nota_<numero>" (o que a nota mostra) e "rateio_<numero>" (a decisao); o painel nao conhece
    # nenhum numero de nota de antemao
    conf = {"nota_123456": "venda de 01/09 com parte em day trade", "outra": 1,
            "rateio_123456": {"decisao": "pendente", "texto": "escolher a divisão"},
            "rateio_999": {"decisao": "proporcional", "texto": "dividido"}}
    assert list(painel._rateios(conf)) == [("123456", "venda de 01/09 com parte em day trade", conf["rateio_123456"]),
                                           ("999", "", conf["rateio_999"])]
    assert list(painel._rateios(None)) == []
