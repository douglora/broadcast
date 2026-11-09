"""Motor do contador de bolsa: apuracao do imposto, fechamento do mes, rotina diaria e e-mail do DARF. Sem rede e sem
o Chrome (precos da B3 e PDF do relatorio trocados por respostas locais).

Os dados sao inventados (FULANO DE TAL, CPF zerado). As contas seguem o REGRAS.md da skill contador-bolsa (IN RFB
1.585/2015, Lei 8.981/1995 e Lei 9.430/1996); cada teste diz a regra que cobra. Todo arquivo gerado fica em tmp_path.
"""

import base64
import datetime as dt
import hashlib
import json
import os
import pathlib
import sys
from email.message import EmailMessage

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_DIR = os.path.join(RAIZ, "ferramentas", "local")
for p in (RAIZ, LOCAL_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from contador_bolsa import apuracao, ativos, cli, eventos, gmail, mes, notas, precos, relatorio  # noqa: E402
from contador_bolsa.apuracao import Carteira, Posicao, Saldo  # noqa: E402

D = dt.date


# ------------------------------------------------------------------ apoio
def neg(dia, cv, ticker, qtd, preco, ordem=0, classe="acao", mercado="VISTA", venc=None, **kw):
    return notas.Negocio(dia, "teste", ordem, cv, mercado, venc, ticker, qtd, preco, round(qtd * preco, 2), ticker,
                         ticker, classe, **kw)


def nota(dia, *negs, irrf=0.0):
    nt = notas.Nota(f"{dia:%Y%m%d}", dia, "teste.pdf", list(negs))
    nt.irrf = irrf
    return nt


def pos(ticker, qtd, custo, classe="acao", **kw):
    return Posicao(ticker, ticker, classe, qtd, custo, **kw)


def carteira(posicoes, lista, ate, desde):
    cart = Carteira(posicoes)
    cart.processa(lista, ate=ate, desde=desde)
    return cart


def apura(posicoes, lista, ano, mm, saldo=None):
    """Processa o mes inteiro e apura: (carteira, apuracao)."""
    cart = carteira(posicoes, lista, mes.fim_do_mes(ano, mm), D(ano, mm, 1))
    return cart, apuracao.apura_mes(cart, ano, mm, saldo or Saldo())


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


# ------------------------------------------------------------------ apuracao
def test_custo_medio_ponderado_e_darf_com_ir_retido():
    # Lei 8.981, art. 72, par. 2; IN 1.585, arts. 57, 58 e 63, par. 8
    cart, r = apura([], [nota(D(2026, 10, 1), neg(D(2026, 10, 1), "C", "VALE3", 1000, 50.0)),
                         nota(D(2026, 10, 5), neg(D(2026, 10, 5), "C", "VALE3", 1000, 60.0)),
                         nota(D(2026, 10, 20), neg(D(2026, 10, 20), "V", "VALE3", 500, 70.0), irrf=1.75)], 2026, 10)
    assert r["resultados"]["comum"] == pytest.approx(7500.0)                 # 500 x (70 - 55)
    assert (r["imposto_bruto"], r["irrf_usado"], r["darf"]) == (1125.0, 1.75, 1123.25)
    assert r["vencimento"] == D(2026, 11, 30) and not r["isento_mes"]
    p = cart.pos["VALE3"]
    assert p.qtd == 1500 and p.custo == pytest.approx(82500.0) and p.pm == pytest.approx(55.0)
    assert p.data_estoque == D(2026, 10, 5)


def test_custos_da_nota_rateados_pelo_valor():
    # IN 1.585, art. 56, par. 4
    dia = D(2026, 10, 5)
    nt = nota(dia, neg(dia, "C", "VALE3", 100, 60.0), neg(dia, "C", "PETR4", 100, 30.0, ordem=1))
    nt.taxas = {"liquidacao": 2.00, "emolumentos": 0.70}
    nt.rateia()
    assert [round(n.taxas, 2) for n in nt.negocios] == [1.80, 0.90]
    assert nt.negocios[0].liquido == pytest.approx(6001.80)                  # compra: valor mais custos
    nt.taxas = {"liquidacao": 2.10, "iss": 0.60}                              # a IRTrade deixa o ISS de fora
    nt.rateia(notas.IRTRADE_EXCLUI)
    assert [round(n.taxas, 2) for n in nt.negocios] == [1.40, 0.70]


def test_mes_isento_lucro_isento_e_prejuizo_continua_compensavel():
    # IN 1.585, art. 59, I e par. 1, com o art. 64
    lista = [nota(D(2026, 10, 9), neg(D(2026, 10, 9), "V", "ITUB4", 500, 28.0)),
             nota(D(2026, 11, 10), neg(D(2026, 11, 10), "V", "ITUB4", 500, 40.0))]
    cart = carteira([pos("ITUB4", 1000, 30000.0)], lista, D(2026, 11, 30), D(2026, 10, 1))
    out = apuracao.apura_mes(cart, 2026, 10, Saldo())
    assert out["isento_mes"] and out["vendas_acoes"] == 14000.0
    assert out["resultados"]["comum"] == -1000.0 and out["resultados"]["isento"] == 0.0    # prejuizo nao vira isento
    assert out["saldo"].prejuizos["comum"] == -1000.0 and out["darf"] == 0.0
    nov = apuracao.apura_mes(cart, 2026, 11, out["saldo"])
    assert nov["vendas_acoes"] == 20000.0 and nov["isento_mes"]                             # ate R$ 20 mil, inclusive
    assert nov["resultados"]["isento"] == 5000.0 and nov["resultados"]["comum"] == 0.0
    assert nov["saldo"].prejuizos["comum"] == -1000.0 and nov["darf"] == 0.0              # lucro isento nao gasta prejuizo


def test_day_trade_20_por_cento_com_ir_de_1_e_prejuizo_comum_nao_compensa():
    # IN 1.585, art. 65, caput e pars. 8, 10 e 11
    dia = D(2026, 10, 14)
    _, r = apura([], [nota(dia, neg(dia, "C", "PETR4", 1000, 30.0), neg(dia, "V", "PETR4", 1000, 31.0, ordem=1),
                           irrf=10.0)], 2026, 10, Saldo({"comum": -5000.0, "daytrade": 0.0, "fii": 0.0}))
    assert r["resultados"]["daytrade"] == 1000.0
    assert (r["imposto_bruto"], r["darf"]) == (200.0, 190.0)
    assert r["saldo"].prejuizos["comum"] == -5000.0
    assert r["duvidas"]["vendas_daytrade"] == 0.0          # sem lucro em acoes a vista, a isencao nao muda o imposto


def test_day_trade_nao_mexe_no_estoque_anterior():
    # IN 1.585, art. 65, pars. 1 a 3
    dia = D(2026, 10, 14)
    cart, r = apura([pos("BBAS3", 1000, 25000.0)],
                    [nota(dia, neg(dia, "C", "BBAS3", 500, 26.0), neg(dia, "V", "BBAS3", 500, 27.0, ordem=1))], 2026, 10)
    assert [(e.tipo, e.resultado) for e in r["encerramentos"]] == [("daytrade", 500.0)]
    assert cart.pos["BBAS3"].qtd == 1000 and cart.pos["BBAS3"].custo == 25000.0


def test_a_conferir_day_trade_decide_a_isencao():
    # REGRAS.md, "a conferir" 1: o day trade entra no total de vendas (caminho conservador) e vira alerta
    _, r = apura([pos("VALE3", 1000, 40000.0)],
                 [nota(D(2026, 10, 7), neg(D(2026, 10, 7), "V", "VALE3", 300, 50.0)),
                  nota(D(2026, 10, 14), neg(D(2026, 10, 14), "C", "PETR4", 170, 28.0),
                       neg(D(2026, 10, 14), "V", "PETR4", 170, 30.0, ordem=1))], 2026, 10)
    assert r["vendas_acoes"] == 20100.0 and not r["isento_mes"]
    assert r["duvidas"]["vendas_daytrade"] == 5100.0
    assert (r["resultados"]["comum"], r["resultados"]["daytrade"]) == (3000.0, 340.0)
    assert r["imposto_bruto"] == 518.0                                        # 15% de 3.000 + 20% de 340


def test_a_conferir_unit_isenta():
    # REGRAS.md, "a conferir" 2
    _, r = apura([pos("TAEE11", 500, 17500.0)], [nota(D(2026, 10, 7), neg(D(2026, 10, 7), "V", "TAEE11", 400, 40.0))],
                 2026, 10)
    assert r["resultados"]["isento"] == 2000.0 and r["duvidas"]["units_isentas"] == ["TAEE11"]


def test_fii_20_por_cento_e_so_compensa_prejuizo_de_fii():
    # IN 1.585, art. 37
    _, r = apura([pos("HGLG11", 100, 16000.0, classe="fii")],
                 [nota(D(2026, 10, 7), neg(D(2026, 10, 7), "V", "HGLG11", 100, 162.0, classe="fii"))], 2026, 10,
                 Saldo({"comum": -3000.0, "daytrade": 0.0, "fii": -100.0}))
    assert r["resultados"]["fii"] == 200.0 and r["vendas_acoes"] == 0.0     # FII nao entra nos R$ 20 mil
    assert (r["imposto_bruto"], r["darf"]) == (20.0, 20.0)
    assert r["saldo"].prejuizos == {"comum": -3000.0, "daytrade": 0.0, "fii": 0.0}


def test_prejuizo_anterior_abatido_inteiro_em_parte_ou_nada():
    # IN 1.585, art. 64: o lucro do mes consome o prejuizo anterior e o que nao cabe passa para os meses seguintes
    casos = ((60.0, 4000.0, 0.0, 6000.0),          # lucro de 10.000 abate os 4.000 inteiros
             (53.0, 3000.0, -1000.0, 0.0),         # lucro de 3.000 abate 3.000 e sobram 1.000
             (48.0, 0.0, -6000.0, 0.0))            # prejuizo de 2.000 no mes nao abate nada e soma ao anterior
    for preco, usado, sobra, base in casos:
        _, r = apura([pos("VALE3", 1000, 50000.0)], [nota(D(2026, 10, 20), neg(D(2026, 10, 20), "V", "VALE3", 1000, preco))],
                     2026, 10, Saldo({"comum": -4000.0, "daytrade": 0.0, "fii": 0.0}))
        (c,) = [ln for ln in r["linhas"] if ln["tipo"] == "comum"]
        assert (c["prejuizo_usado"], c["prejuizo"], c["base"]) == (usado, sobra, base), preco


def test_opcao_que_vence_sem_exercicio():
    # IN 1.585, art. 60, par. 3: o premio e ganho do lancador e perda do titular na data do vencimento
    dia = D(2026, 10, 1)
    kw = dict(classe="opcao", mercado="OPCAO DE COMPRA", venc="10/26", strike=35.0, tipo_opcao="call",
              subjacente="PETR4")
    cart, r = apura([], [nota(dia, neg(dia, "V", "PETRJ350", 1000, 0.30, **kw))], 2026, 10)
    (e,) = r["encerramentos"]
    assert (e.mercado, e.liq_data, e.resultado) == ("vencimento", D(2026, 10, 16), 300.0)   # 3a sexta de outubro
    assert r["imposto_bruto"] == 45.0 and cart.posicoes() == []
    _, r = apura([], [nota(dia, neg(dia, "C", "PETRJ350", 1000, 0.20, **kw))], 2026, 10)
    assert r["resultados"]["comum"] == -200.0 and r["saldo"].prejuizos["comum"] == -200.0


def test_exercicio_de_put_lancada_premio_reduz_o_custo():
    # IN 1.585, art. 60, II, e par. 1 (REGRAS.md, "a conferir" 3: conferir na nota real de 19/11)
    put = pos("DIRRW100", -1000, -400.0, classe="opcao", vencimento=D(2026, 11, 19), strike=10.0, tipo_opcao="put",
              subjacente="DIRR3")
    dia = D(2026, 11, 19)
    ex = neg(dia, "C", "DIRRW100", 1000, 10.0, classe="opcao", mercado="EXERC OPC VENDA", strike=10.0,
             tipo_opcao="put", subjacente="DIRR3", exercicio=True)
    cart, r = apura([put], [nota(dia, ex)], 2026, 11)
    acao = cart.pos["DIRR3"]
    assert acao.qtd == 1000 and acao.custo == pytest.approx(9600.0) and acao.pm == pytest.approx(9.60)
    assert cart.pos["DIRRW100"].qtd == 0 and r["encerramentos"] == []             # o premio foi para o custo


def test_exercicio_de_call_lancada_vende_a_acao_e_nao_e_isento():
    # IN 1.585, art. 59, par. 2, e art. 60, II: alienacao por exercicio nao tem a isencao; o premio soma ao preco
    call = pos("VALEJ600", -1000, -1000.0, classe="opcao", vencimento=D(2026, 10, 16), strike=60.0, tipo_opcao="call",
               subjacente="VALE3")
    dia = D(2026, 10, 16)
    ex = neg(dia, "V", "VALEJ600", 1000, 60.0, classe="opcao", mercado="EXERC OPC COMPRA", strike=60.0,
             tipo_opcao="call", subjacente="VALE3", exercicio=True)
    cart, r = apura([pos("VALE3", 1000, 50000.0), call], [nota(dia, ex)], 2026, 10)
    (e,) = r["encerramentos"]
    assert (e.ticker, e.mercado, e.tipo, e.resultado) == ("VALE3", "exercicio", "comum", 11000.0)
    assert r["imposto_bruto"] == 1650.0 and cart.posicoes() == []


def test_darf_abaixo_de_10_reais_passa_para_o_mes_seguinte():
    # Lei 9.430, art. 68
    kw = dict(classe="opcao", mercado="OPCAO DE COMPRA", strike=35.0, tipo_opcao="call", subjacente="PETR4")
    lista = [nota(D(2026, 10, 1), neg(D(2026, 10, 1), "V", "PETRJ350", 1000, 0.04, venc="10/26", **kw)),
             nota(D(2026, 11, 3), neg(D(2026, 11, 3), "V", "PETRK350", 1000, 0.04, venc="11/26", **kw))]
    cart = carteira([], lista, D(2026, 11, 30), D(2026, 10, 1))
    out = apuracao.apura_mes(cart, 2026, 10, Saldo())
    assert (out["devido"], out["darf"], out["saldo"].pendente) == (6.0, 0.0, 6.0)
    nov = apuracao.apura_mes(cart, 2026, 11, out["saldo"])
    assert (nov["devido"], nov["darf"], nov["saldo"].pendente) == (12.0, 12.0, 0.0)


def test_ir_retido_que_sobra_abate_no_mes_seguinte():
    # IN 1.585, art. 63, par. 8
    lista = [nota(D(2026, 10, 7), neg(D(2026, 10, 7), "V", "ITUB4", 1000, 25.0), irrf=1.25),
             nota(D(2026, 11, 9), neg(D(2026, 11, 9), "V", "ITUB4", 1000, 30.0), irrf=1.50)]
    cart = carteira([pos("ITUB4", 2000, 50000.0)], lista, D(2026, 11, 30), D(2026, 10, 1))
    out = apuracao.apura_mes(cart, 2026, 10, Saldo())
    assert out["imposto_bruto"] == 0.0 and out["saldo"].irrf == 1.25
    nov = apuracao.apura_mes(cart, 2026, 11, out["saldo"])
    assert (nov["irrf_usado"], nov["darf"], nov["saldo"].irrf) == (2.75, 747.25, 0.0)


@pytest.mark.parametrize("ano, mm, venc", [
    (2026, 4, D(2026, 5, 29)), (2026, 9, D(2026, 10, 30)), (2026, 10, D(2026, 11, 30)), (2026, 11, D(2026, 12, 30)),
    (2026, 12, D(2027, 1, 29)), (2024, 11, D(2024, 12, 30)), (2025, 11, D(2025, 12, 30)), (2028, 11, D(2028, 12, 29))])
def test_vencimento_no_ultimo_dia_util_do_mes_seguinte(ano, mm, venc):
    # IN 1.585, art. 56, par. 5; 31/12 nao conta (Agenda Tributaria de dezembro de 2024 e de 2025: 6015 em 30/12)
    assert apuracao.vencimento_darf(ano, mm) == venc


# ------------------------------------------------------------------ apoios da rotina e do e-mail
def test_apoios_da_rotina():
    assert cli._uteis_entre(D(2026, 10, 31), D(2026, 11, 4)) == 2                # 02/11 e feriado
    assert cli.nomes(2026, 10) == ("Relatorio mensal 10-2026.pdf", "DARF 10-2026.pdf")
    a = "DARF de 10/2026: R$ 1.350,00, código 6015, vence em 30/11/2026 ({}); o pagamento ainda não apareceu na conta."
    chaves = {cli._chave_alerta(a.format(q)) for q in ("faltam 27 dias", "faltam 2 dias", "amanhã", "hoje")}
    assert len(chaves) == 1                                                       # a contagem nao repete o aviso
    assert [gmail._rs(v) for v in (-512.34, 0.0, -0.001, 1350.0)] == ["-R$ 512,34", "R$ 0,00", "R$ 0,00", "R$ 1.350,00"]


def test_email_gravado_em_linhas_que_se_juntam_sem_perder_nada(tmp_path):
    dados = os.urandom(2500)
    b64 = base64.b64encode(dados).decode()
    msg = {"chave": "fechamento-2026-10", "to": ["fulano@example.com"], "subject": "DARF", "body": "corpo",
           "htmlBody": "<p>a</p><p>b</p>", "attachments": [{"filename": "DARF 10-2026.pdf",
                                                             "mimeType": "application/pdf", "content": b64,
                                                             "sha256": hashlib.sha256(dados).hexdigest()}]}
    linhas = cli._grava_email(tmp_path, msg).read_text().split("\n")
    i = next(k for k, l in enumerate(linhas) if l.startswith("--- anexo 1:"))
    fim = linhas.index("--- fim ---")
    assert fim - i - 1 == 4 and all(len(l) <= 1000 for l in linhas[i + 1:fim])
    assert base64.b64decode("".join(linhas[i + 1:fim])) == dados
    assert json.loads((tmp_path / "saida" / "email" / "fechamento-2026-10.json").read_text()) == msg


def _raw(pasta, nome, dados):
    """O que a sessao salva do get_message em RAW: JSON com a mensagem inteira em base64url."""
    m = EmailMessage()
    m["To"], m["Subject"] = "fulano@example.com", "DARF"
    m.set_content("corpo")
    m.add_attachment(dados, maintype="application", subtype="pdf", filename=nome)
    arq = pasta / f"raw-{hashlib.sha256(dados).hexdigest()[:8]}.json"
    arq.write_text(json.dumps({"raw": base64.urlsafe_b64encode(m.as_bytes()).decode().rstrip("=")}))
    return arq


def test_enviado_confere_o_anexo_que_chegou(tmp_path):
    dados = b"%PDF-1.4 darf de teste"
    arq = tmp_path / "msg.json"
    arq.write_text(json.dumps({"chave": "fechamento-2026-10", "subject": "DARF", "attachments": [
        {"filename": "DARF 10-2026.pdf", "sha256": hashlib.sha256(dados).hexdigest()}]}))
    assert cli.enviado(tmp_path, arq, _raw(tmp_path, "DARF 10-2026.pdf", dados)) == (True, [])
    assert cli.enviado(tmp_path, arq, _raw(tmp_path, "DARF 10-2026.pdf", b"outro")) == (False, ["DARF 10-2026.pdf"])
    reg = json.loads((tmp_path / "estado" / "diario.json").read_text())
    assert reg["emails"]["fechamento-2026-10"]["anexo_conferido"] is False


def _sessao(sessoes, texto):
    """Registro (.jsonl) de uma sessao do Claude Code com a resposta do get_message no texto da conversa."""
    proj = sessoes / "-Users-fulano-projeto"
    proj.mkdir(parents=True, exist_ok=True)
    pedido = {"type": "assistant", "message": {"content": [{"type": "text", "text": "get_message RAW"}]}}
    resposta = {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": texto}]}]}}
    (proj / "sessao-1.jsonl").write_text(json.dumps(pedido) + "\n" + json.dumps(resposta) + "\n")
    return proj


def test_raw_do_get_message_sai_da_sessao_sem_copia(tmp_path):
    """Resposta pequena so existe no registro da conversa; a grande o app ja grava em tool-results/."""
    dados = b"%PDF-1.4 darf de teste"
    raw = json.loads(_raw(tmp_path, "DARF 10-2026.pdf", dados).read_text())["raw"]
    sessoes = tmp_path / "projects"
    proj = _sessao(sessoes, json.dumps({"historyId": "1", "id": "18aa00bb11cc22dd", "raw": raw}))
    destino = tmp_path / "entrada" / "18aa00bb11cc22dd.json"
    assert gmail.raw_da_sessao("18aa00bb11cc22dd", destino, sessoes) == destino
    assert [p.get_payload(decode=True) for p in gmail.mensagem_raw(destino).iter_attachments()] == [dados]
    grande = proj / "sessao-2" / "tool-results" / "mcp-x-get_message-1.txt"
    grande.parent.mkdir(parents=True)
    grande.write_text(json.dumps({"historyId": "2", "id": "18ee33ff44aa55bb", "raw": raw}, separators=(",", ":")))
    assert gmail.raw_da_sessao("18ee33ff44aa55bb", tmp_path / "entrada" / "x.json", sessoes) == grande
    with pytest.raises(FileNotFoundError):
        gmail.raw_da_sessao("18ffffffffffffff", tmp_path / "entrada" / "y.json", sessoes)


def test_enviado_e_importar_pelo_id_da_mensagem(tmp_path, monkeypatch, capsys):
    dados = b"%PDF-1.4 darf de teste"
    raw = json.loads(_raw(tmp_path, "DARF 10-2026.pdf", dados).read_text())["raw"]
    monkeypatch.setattr(gmail, "SESSOES", tmp_path / "projects")
    _sessao(tmp_path / "projects", json.dumps({"id": "18aa00bb11cc22dd", "raw": raw}))
    base = tmp_path / "titular"
    arq = base / "saida" / "email" / "fechamento-2026-10.json"
    arq.parent.mkdir(parents=True)
    arq.write_text(json.dumps({"chave": "fechamento-2026-10", "subject": "DARF", "attachments": [
        {"filename": "DARF 10-2026.pdf", "sha256": hashlib.sha256(dados).hexdigest()}]}))
    assert cli.main(["--titular", str(base), "enviado", str(arq), "--id", "18aa00bb11cc22dd"]) == 0
    assert "anexo conferido" in capsys.readouterr().out
    reg = json.loads((base / "estado" / "diario.json").read_text())
    assert reg["emails"]["fechamento-2026-10"]["id"] == "18aa00bb11cc22dd"
    assert cli.main(["--titular", str(base), "enviado", str(arq), "--id", "18ffffffffffffff"]) == 1
    assert "ERRO" in capsys.readouterr().out
    # o anexo do teste nao e nota do Safra: a mensagem entra no registro e nenhum PDF vai para notas/
    assert cli.main(["--titular", str(base), "importar-email", "--id", "18aa00bb11cc22dd"]) == 0
    assert "notas novas: 0" in capsys.readouterr().out
    assert gmail.novos(base, ["18aa00bb11cc22dd"]) == []


# ------------------------------------------------------------------ fechamento e rotina (pasta do titular inventada)
VENDA_VALE = {"pregao": "2026-10-20", "liquidacao": "2026-10-21", "cv": "V", "ticker": "VALE3", "ativo": "VALE ON",
              "classe": "acao", "qtd": 1000, "total": 60000.0, "fonte": "teste"}
ITUB = [{"pregao": "2026-10-26", "liquidacao": "2026-10-28", "cv": "C", "ticker": "ITUB4", "ativo": "ITAU UNIBANCO PN",
         "classe": "acao", "qtd": 100, "total": 3000.0, "fonte": "teste"},
        {"pregao": "2026-10-27", "liquidacao": "2026-10-29", "cv": "V", "ticker": "ITUB4", "ativo": "ITAU UNIBANCO PN",
         "classe": "acao", "qtd": 100, "total": 3500.0, "fonte": "teste"}]


def _manuais(base, lista):
    (base / "manuais.json").write_text(json.dumps(lista))


def _titular(tmp_path, manuais):
    """1.000 VALE3 a R$ 50.000 e R$ 1.000 de prejuizo comum em 30/09; as notas entram por manuais.json."""
    base = tmp_path / "titular"
    base.mkdir()
    (base / "titular.json").write_text(json.dumps({"nome": "FULANO DE TAL", "documento": "000.000.000-00",
                                                   "corretora": "SAFRA CORRETORA", "email": "fulano@example.com"}))
    (base / "partida.json").write_text(json.dumps({
        "data": "2026-09-30", "origem": "teste", "posicoes": [apuracao.posicao_dict(pos("VALE3", 1000, 50000.0))],
        "prejuizos": {"comum": -1000.0, "daytrade": 0.0, "fii": 0.0}, "irrf": 0.0, "pendente": 0.0}))
    _manuais(base, manuais)
    return base


def _of(lido_em, *extra):
    t = [{"date": "2026-10-15", "amount": 120.0, "description": "DIVIDENDOS VALE"},
         {"date": "2026-10-21", "amount": 60000.0, "description": "LIQUIDACAO NOTA RENDA VARIAVEL"},
         {"date": "2026-10-30", "amount": 50.0, "description": "Dividendos ITUB"}] + list(extra)
    return {"lido_em": lido_em, "conexoes": [{"transacoes": t}]}


def test_fechamento_do_mes_com_open_finance(tmp_path):
    base = _titular(tmp_path, [VENDA_VALE])
    out = mes.fecha_mes(base, 2026, 10, _of("2026-11-03T08:00:00"), D(2026, 11, 3), gravar=False)
    assert out["apuracao"]["darf"] == 1350.0                     # (10.000 - 1.000 de prejuizo anterior) x 15%
    d = out["darf"]
    assert (d["periodo_apuracao"], d["vencimento"], d["codigo_receita"], d["documento"]) == \
        ("31/10/2026", "30/11/2026", "6015", "000.000.000-00")
    assert out["dados"]["proventos"]["total"]["dividendos"] == 170.0 and not out["dados"]["parcial"]
    assert len(out["conciliacao"]["casadas"]) == 1 and out["conciliacao"]["sem_nota"] == []
    assert out["dados"]["situacao"]["alertas"][0].startswith(
        "DARF de 10/2026: R$ 1.350,00, código 6015, vence em 30/11/2026")
    assert not (base / "estado").exists()                         # gravar=False nao grava nada


def test_frase_e_email_dizem_o_prejuizo_abatido_e_o_que_sobra(tmp_path):
    # o fechamento diz quanto prejuizo anterior saiu do lucro e quanto sobra, por tipo (IN 1.585, art. 64 e art. 65,
    # par. 10): so com "prejuizo a compensar R$ 0,00" no quadro, o prejuizo usado parecia esquecido (03/11/2026)
    base = _titular(tmp_path, [VENDA_VALE])
    p = json.loads((base / "partida.json").read_text())
    (base / "partida.json").write_text(json.dumps({**p, "prejuizos": {"comum": -1000.0, "daytrade": -300.0, "fii": 0.0}}))
    out = mes.fecha_mes(base, 2026, 10, None, D(2026, 11, 3), gravar=False)
    frase = gmail.frase_fechamento(out)
    assert frase.startswith("o DARF de outubro/2026 é de R$ 1.350,00 (código 6015) e vence em 30/11/2026: lucro "
                            "tributável de R$ 9.000,00 no mês (R$ 10.000,00 menos R$ 1.000,00 de prejuízo de meses "
                            "anteriores), imposto de R$ 1.350,00")
    assert frase.endswith("; prejuízo que sobra para os próximos meses: R$ 300,00 de day trade, que só abate lucro "
                          "de day trade.")
    msg = gmail.email_fechamento(out, None, "fulano@example.com", str(base / "saida"))
    assert "Prejuízo abatido" in msg["htmlBody"] and "  Comum | R$ 10.000,00 | R$ 1.000,00 | R$ 1.350,00" in msg["body"]
    # lucro menor que o prejuizo: sem imposto, e a frase diz o que abateu e o que sobra
    _manuais(base, [{**VENDA_VALE, "total": 50500.0}])
    frase = gmail.frase_fechamento(mes.fecha_mes(base, 2026, 10, None, D(2026, 11, 3), gravar=False))
    assert frase == ("sem imposto a pagar em outubro/2026: resultado de R$ 500,00 no mês, com R$ 500,00 de lucro "
                     "abatidos do prejuízo de meses anteriores; prejuízo que sobra para os próximos meses: R$ 500,00 "
                     "nas operações comuns e R$ 300,00 de day trade, que só abate lucro de day trade.")


def test_liquidacao_sem_nota_vira_alerta(tmp_path):
    base = _titular(tmp_path, [])
    out = mes.fecha_mes(base, 2026, 10, _of("2026-11-03T08:00:00"), D(2026, 11, 3), gravar=False)
    assert out["apuracao"]["darf"] == 0.0
    assert any(a.startswith("Liquidação de bolsa de R$ 60.000,00 em 21/10 sem nota no e-mail")
               for a in out["dados"]["situacao"]["alertas"])


def test_darf_de_novembro_vence_em_30_12_com_a_fonte(tmp_path):
    # REGRAS.md, DARF: na Agenda Tributaria o 6015 de novembro vence em 30/12 (era o "a conferir" 4 ate 08/11/2026)
    base = _titular(tmp_path, [{**VENDA_VALE, "pregao": "2026-11-10", "liquidacao": "2026-11-11"}])
    p = json.loads((base / "partida.json").read_text())
    (base / "partida.json").write_text(json.dumps({**p, "data": "2026-10-31"}))
    out = mes.fecha_mes(base, 2026, 11, None, D(2026, 12, 3), gravar=False)
    sit = out["dados"]["situacao"]
    assert sit["alertas"][0].startswith("DARF de 11/2026: R$ 1.350,00, código 6015, vence em 30/12/2026")
    assert out["darf"]["vencimento"] == "30/12/2026" and mes.VENCE_30_12 in sit["conferencia"]
    assert not any("31/12" in a for a in sit["alertas"])


def test_refazer_o_mes_varias_vezes_guarda_todas_as_versoes(tmp_path):
    base = _titular(tmp_path, [VENDA_VALE])
    for manuais in ([VENDA_VALE], [VENDA_VALE] + ITUB[:1], [VENDA_VALE] + ITUB):     # tres versoes no mesmo minuto
        _manuais(base, manuais)
        mes.fecha_mes(base, 2026, 10, None, D(2026, 11, 3))
    guardados = sorted((base / "estado" / "anteriores").glob("2026-10 *.json"))
    assert sorted(len(json.loads(a.read_text())["posicoes"]) for a in guardados) == [0, 1]
    assert json.loads((base / "estado" / "2026-10.json").read_text())["resumo"]["darf"] == 1425.0


def test_rotina_diaria_fecha_avisa_uma_vez_e_corrige(tmp_path):
    base = _titular(tmp_path, [VENDA_VALE])
    # 1a rodada, 03/11: fecha outubro; dos movimentos antigos do Open Finance, so os dos ultimos 4 dias
    res = cli.diario(base, _of("2026-11-03T08:00:00"), D(2026, 11, 3), pdf=False)
    (f,) = res["fechados"]
    assert (f["competencia"], f["darf"], f["vencimento"]) == ("10/2026", 1350.0, "30/11/2026")
    assert [m["data"] for m in res["movimentos"]] == ["2026-10-30"]
    assert cli.texto_diario(res).split("\n")[1].startswith(
        "FECHADO AGORA 10/2026: o DARF de outubro/2026 é de R$ 1.350,00")
    # 2a rodada, mesmo dia: nada novo, uma linha so
    txt = cli.texto_diario(cli.diario(base, _of("2026-11-03T08:00:00"), D(2026, 11, 3), pdf=False))
    assert "\n" not in txt and "sem novidade" in txt and "próximo DARF 10/2026 R$ 1.350,00" in txt
    # 3a rodada, 04/11: o banco lancou um JCP com data de 28/10; o aviso do DARF nao se repete so pela contagem
    of = _of("2026-11-04T08:00:00", {"date": "2026-10-28", "amount": 85.0, "description": "JUROS S/CAPITAL ITUB"},
             {"date": "2026-11-03", "amount": -10.0, "description": "PIX ENVIADO"})
    res = cli.diario(base, of, D(2026, 11, 4), pdf=False)
    assert [(m["data"], m["tipo"]) for m in res["movimentos"]] == [("2026-10-28", "juros s/ capital")]
    assert res["novos"] == [] and res["refeitos"] == []
    # 4a rodada, 05/11: chegam as notas de ITUB4 de 26 e 27/10; outubro e refeito e a correcao abre o texto
    _manuais(base, [VENDA_VALE] + ITUB)
    res = cli.diario(base, of, D(2026, 11, 5), pdf=False)
    (f,) = res["refeitos"]
    assert (f["darf_antes"], f["darf"]) == (1350.0, 1425.0)                   # + 500 de lucro x 15%
    assert cli.texto_diario(res).split("\n")[1].startswith("CORREÇÃO 10/2026: o fechamento mudou")
    assert len(list((base / "estado" / "anteriores").glob("2026-10 *.json"))) == 1
    assert json.loads((base / "estado" / "2026-10.json").read_text())["resumo"]["darf"] == 1425.0


def _item(**kw):
    return {"connector": {"name": "BancoTeste"}, "status": "UPDATED", "executionStatus": "SUCCESS",
            "lastUpdatedAt": "2026-11-06T21:00:00", "consentExpiresAt": "2027-10-13T15:00:00Z", **kw}


def test_open_finance_parado_com_erro_ou_autorizacao_vencendo_vira_alerta_uma_vez(tmp_path):
    # o Open Finance traz o pagamento do DARF, os proventos e o aluguel: parado, com erro ou com a autorizacao perto de
    # vencer, a rotina avisa sozinha (pedido de 04/11/2026: tudo automatico, sem ele ter de conferir)
    of = _of("2026-11-06T22:00:00")
    of["conexoes"][0]["item"] = _item()
    assert mes.saude_of(of, D(2026, 11, 9)) == []          # segunda: a leitura de sexta a noite ainda vale
    assert mes.saude_of(None, D(2026, 11, 9)) == []
    of["lido_em"] = "2026-11-05T22:00:00"
    of["conexoes"][0]["item"] = _item(lastUpdatedAt="2026-11-05T21:00:00")
    assert mes.saude_of(of, D(2026, 11, 9)) == [
        "Open Finance sem leitura nova desde 05/11 às 22h00: quem lê é o terminal (agente br.autopilot.terminal); "
        "sem ele não entram proventos, aluguel nem o pagamento do DARF.",
        "Open Finance (BancoTeste): o banco não manda dado novo desde 05/11 às 21h00."]
    of = _of("2026-11-09T08:00:00")
    of["erros"] = ["falha na conta do titular 000.000.000-00"]
    of["conexoes"][0]["item"] = _item(status="LOGIN_ERROR", executionStatus="ERROR",
                                      lastUpdatedAt="2026-11-09T08:00:00", consentExpiresAt="2026-12-01T15:00:00Z")
    al = mes.saude_of(of, D(2026, 11, 9))
    assert al == [
        "Open Finance: a última leitura deu erro (falha na conta do titular <CPF>).",
        "Open Finance (BancoTeste): a conexão está em LOGIN_ERROR (ERROR). Se continuar no dia seguinte, reconecte no "
        "MeuPluggy, autorizando de novo no app do Safra.",
        "A autorização do Open Finance (BancoTeste) vence em 01/12/2026: renove antes no MeuPluggy, autorizando de novo "
        "no app do Safra."]
    of["conexoes"][0]["item"]["consentExpiresAt"] = "2026-11-01T15:00:00Z"
    assert mes.saude_of(of, D(2026, 11, 9))[-1].startswith("A autorização do Open Finance (BancoTeste) venceu em 01/11")
    # na rotina: aparece uma vez entre os novos e depois continua valendo sem repetir
    base = _titular(tmp_path, [VENDA_VALE])
    res = cli.diario(base, of, D(2026, 11, 9), pdf=False)
    assert all(a in res["novos"] for a in mes.saude_of(of, D(2026, 11, 9)))
    res = cli.diario(base, of, D(2026, 11, 9), pdf=False)
    assert res["novos"] == [] and any(a.startswith("A autorização do Open Finance (BancoTeste) venceu em 01/11/2026")
                                      for a in res["alertas"])


def test_rotina_monta_o_email_com_o_darf_leve_e_o_corrigido(tmp_path):
    from pypdf import PdfReader

    base = _titular(tmp_path, [VENDA_VALE])
    of = _of("2026-11-03T08:00:00")
    (e,) = cli.diario(base, of, D(2026, 11, 3))["emails"]
    assert (e["chave"], e["motivo"]) == ("fechamento-2026-10", "fechamento do mês")
    msg = json.loads(pathlib.Path(e["arquivo"]).with_suffix(".json").read_text())
    assert msg["to"] == ["fulano@example.com"] and "R$ 1.350,00" in msg["subject"] and "30/11/2026" in msg["subject"]
    (anexo,) = msg["attachments"]
    pdf = base / "saida" / "DARF 10-2026.pdf"
    assert anexo["filename"] == pdf.name and base64.b64decode(anexo["content"]) == pdf.read_bytes()
    assert len(anexo["content"]) < 20_000                         # cabe dentro da chamada do conector do Gmail
    leitor = PdfReader(str(pdf))
    assert leitor.is_encrypted and leitor.decrypt("00000") != 0     # senha: 5 primeiros digitos do CPF
    assert "1.350,00" in leitor.pages[0].extract_text()
    assert "000.000.000-00" not in msg["body"] + msg["htmlBody"]   # o CPF so vai dentro do PDF com senha
    # enviado e conferido: a rodada seguinte nao pede o mesmo e-mail
    assert cli.enviado(base, pathlib.Path(e["arquivo"]).with_suffix(".json"),
                       _raw(tmp_path, pdf.name, pdf.read_bytes())) == (True, [])
    assert cli.diario(base, of, D(2026, 11, 3))["emails"] == []
    # nota nova refaz o mes: o e-mail sai de novo, marcado como corrigido, e o PDF antigo vai para anteriores/
    _manuais(base, [VENDA_VALE] + ITUB)
    (e,) = cli.diario(base, of, D(2026, 11, 5))["emails"]
    msg = json.loads(pathlib.Path(e["arquivo"]).with_suffix(".json").read_text())
    assert e["chave"] == "fechamento-2026-10-v2" and msg["subject"].startswith("CORRIGIDO: ")
    assert msg["body"].startswith("Este e-mail substitui o anterior") and "R$ 1.425,00" in msg["subject"]
    assert len(list((base / "saida" / "anteriores").glob("DARF 10-2026 *.pdf"))) == 1


def test_mes_refeito_por_decisao_leva_o_motivo_no_email_corrigido(tmp_path):
    base = _titular(tmp_path, [VENDA_VALE])
    of = _of("2026-11-03T08:00:00")
    cli.diario(base, of, D(2026, 11, 3))
    # decisao do titular muda o ponto de partida (prejuizo comum de 1.000 para 500): outubro e refeito com o motivo
    p = json.loads((base / "partida.json").read_text())
    p["prejuizos"]["comum"] = -500.0
    (base / "partida.json").write_text(json.dumps(p))
    motivo = "a nota 1 passou a ser dividida pelo valor de cada operação"
    assert cli.fechar(base, of, 2026, 10, D(2026, 11, 3), motivo=motivo)["apuracao"]["darf"] == 1425.0
    msg = json.loads(cli.montar_email(base, of, 2026, 10, D(2026, 11, 3)).with_suffix(".json").read_text())
    assert msg["subject"].startswith("CORRIGIDO: ") and "R$ 1.425,00" in msg["subject"]
    assert msg["body"].startswith(f"Este e-mail substitui o anterior: o fechamento foi refeito porque {motivo}. "
                                  "DARF antes: R$ 1.350,00.")
    # a rodada seguinte pede esse mesmo e-mail (versao 2) e nao refaz o mes de novo
    res = cli.diario(base, of, D(2026, 11, 3))
    assert res["refeitos"] == [] and [e["chave"] for e in res["emails"]] == ["fechamento-2026-10-v2"]


def test_ajuste_decidido_sobre_mes_da_irtrade_entra_na_tabela_anual(tmp_path):
    # o titular trocou a divisao que a IRTrade fez de uma nota pela proporcional; o numero dela fica como ela
    # publicou e o ajuste entra na leitura, com SOMA e LIQUIDO junto e a nota da tabela dizendo o que mudou
    base = _titular(tmp_path, [VENDA_VALE])
    linhas = {k: [0.0] * 9 for k in mes.LINHAS_ANUAIS}
    linhas |= {"DAYTRADE": [0.0] * 8 + [-100.0], "DESPESAS": [0.0] * 8 + [-0.50], "SOMA": [0.0] * 8 + [-100.0],
               "LÍQUIDO": [0.0] * 8 + [-100.50]}
    (base / "historico.json").write_text(json.dumps({
        "fonte": "Jan a Set/2026 conforme a IRTrade", "anual": {"2026": linhas},
        "ajustes": [{"mes": "2026-09", "tipo": "daytrade", "classe": "opcao", "antes": -100.0, "depois": -98.0,
                     "motivo": "divisão proporcional da nota 1"}]}))
    an = mes.fecha_mes(base, 2026, 10, _of("2026-11-03T08:00:00"), D(2026, 11, 3), gravar=False)["dados"]["anual"]
    v = {x["rotulo"]: x["valores"][8] for x in an["linhas"]}
    assert (v["DAYTRADE"], v["SOMA"], v["LÍQUIDO"]) == (-98.0, -98.0, -98.5)
    assert "IRTrade; day trade de 09/2026 com ajuste de R$ 2,00 (divisão proporcional da nota 1); Out/2026" in an["nota"]
    assert json.loads((base / "historico.json").read_text())["anual"]["2026"]["DAYTRADE"][8] == -100.0


# ------------------------------------------------------------------ eventos da B3, custodia e vencimento
def _partida(base, *posicoes, data="2026-09-30", prejuizos=None):
    p = json.loads((base / "partida.json").read_text())
    p.update(data=data, posicoes=[apuracao.posicao_dict(x) for x in posicoes])
    if prejuizos is not None:
        p["prejuizos"] = prejuizos
    (base / "partida.json").write_text(json.dumps(p))


def _custodia(of, dia, *itens):
    """Posicao do banco no Open Finance: (codigo, quantidade) em `dia`."""
    of["conexoes"][0]["investimentos"] = [
        {"type": "EQUITY", "code": c, "quantity": q, "date": f"{dia}T00:00:00", "isin": None,
         "subtype": "REAL_ESTATE_FUND" if c.endswith("11") else "STOCK"} for c, q in itens]
    return of


# o cadastro da B3 como ele vem (fator em texto, com virgula; data com em lastDatePrior)
B3_FULA = [{"stockDividends": [
    {"label": "DESDOBRAMENTO", "factor": "200,00000000000", "lastDatePrior": "15/10/2026", "isinCode": "BRFULAACNOR1",
     "approvedOn": "01/10/2026", "assetIssued": "BRFULAACNOR1"},
    {"label": "BONIFICACAO", "factor": "10,00000000000", "lastDatePrior": "16/10/2026", "isinCode": "BRFULAACNPR8",
     "approvedOn": "01/10/2026", "assetIssued": "BRFULAACNOR1"},
    {"label": "RESG TOTAL RV", "factor": "100,00000000000", "lastDatePrior": "20/10/2026", "isinCode": "BRFULAACNOR1",
     "approvedOn": "02/10/2026"},
    {"label": "DESDOBRAMENTO", "factor": "4.900,00000000000", "lastDatePrior": "30/09/2026", "isinCode": "BRFULAACNOR1",
     "approvedOn": "01/09/2026"}],
    "subscriptions": [
    {"percentage": "5,64895175262", "priceUnit": "110,93000000000", "lastDatePrior": "21/10/2026",
     "isinCode": "BRFULACTF001", "subscriptionDate": "30/10/2026", "approvedOn": "05/10/2026"}]}]
B3_BELT = [{"stockDividends": [{"label": "GRUPAMENTO", "factor": "0,10000000000", "lastDatePrior": "19/10/2026",
                                "isinCode": "BRBELTBDR005", "approvedOn": "03/10/2026"}]}]


def test_eventos_da_b3_lidos_como_a_b3_publica():
    # desdobramento e bonificacao vem em percentual de acrescimo; grupamento como multiplicador; o que veio ate a
    # partida ja esta na posicao; ISIN que a regra nao decide (BDR) sai do que o banco mostrou
    evs = {eventos.ident(e): e for e in eventos.normaliza(B3_FULA + B3_BELT, {"BRBELTBDR005": "BELT34"}, D(2026, 9, 30))}
    assert sorted(evs) == ["BELT34:grupamento:2026-10-19", "FULA11:subscricao:2026-10-21", "FULA3:aviso:2026-10-20",
                           "FULA3:desdobramento:2026-10-15", "FULA4:bonificacao:2026-10-16"]
    assert [evs[k].get("fator") for k in sorted(evs)] == [0.1, None, 100.0, 3.0, 1.1]
    assert evs["FULA4:bonificacao:2026-10-16"]["novo_ticker"] == "FULA3"           # bonificacao paga em ON
    assert "novo_ticker" not in evs["FULA3:desdobramento:2026-10-15"]
    assert evs["FULA3:desdobramento:2026-10-15"]["fonte"] == "B3, desdobramento aprovado em 01/10/2026"
    assert [eventos.texto(evs[k]) for k in sorted(evs)] == [
        "grupamento de 10 para 1 com data com 19/10/2026", "subscrição de 5,65% a R$ 110,93 por papel com data com 21/10/2026",
        "evento (resg total rv) com data com 20/10/2026", "desdobramento de 1 para 3 com data com 15/10/2026",
        "bonificação de 10% com data com 16/10/2026"]
    assert eventos.ticker_do_isin("BRBELTBDR005", {}) is None and eventos.ticker_do_isin("BRFULACDAM10", {}) == "FULA11"
    assert eventos.texto({"ticker": "X", "tipo": "restituicao", "data_com": "2026-10-01", "valor_por_acao": 0.123456}) == \
        "restituição de capital de R$ 0,123456 por ação com data com 01/10/2026"


def test_eventos_da_b3_uma_leitura_por_dia_e_falha_fica_com_a_anterior(tmp_path):
    pedidos = []

    def pede(cod):
        pedidos.append(cod)
        return {"FULA": B3_FULA}.get(cod, [])

    tks = {"FULA3", "FULA11", "BELT34", None}
    out = eventos.atualizar(tmp_path, tks, {}, D(2026, 11, 9), D(2026, 9, 30), pede)
    ids = [eventos.ident(e) for e in out["eventos"]]
    assert ids == ["FULA3:desdobramento:2026-10-15", "FULA3:aviso:2026-10-20", "FULA11:subscricao:2026-10-21"]
    assert pedidos == ["BELT", "FULA"] and out["erros"] == []                   # FULA4 nao esta na carteira
    eventos.atualizar(tmp_path, tks, {}, D(2026, 11, 9), D(2026, 9, 30), pede)
    assert pedidos == ["BELT", "FULA"]                                          # mesmo dia: le o que ficou gravado

    def falha(cod):
        raise OSError("sem rede")

    out = eventos.atualizar(tmp_path, tks, {}, D(2026, 11, 10), D(2026, 9, 30), falha)
    assert out["erros"] == ["BELT (OSError)", "FULA (OSError)"]
    assert [eventos.ident(e) for e in out["eventos"]] == ids                    # vale a leitura anterior
    # o eventos.json do titular vai por cima: completa a fonte, tira o que nao vale e acrescenta o que a B3 nao traz
    (tmp_path / "eventos.json").write_text(json.dumps([
        {"ticker": "FULA3", "tipo": "desdobramento", "data_com": "2026-10-15", "fonte": "aviso aos acionistas"},
        {"ticker": "FULA3", "tipo": "aviso", "data_com": "2026-10-20", "ignorar": True},
        {"ticker": "FULA11", "tipo": "restituicao", "data_com": "2026-10-25", "valor_por_acao": 0.5}]))
    evs = eventos.carrega(tmp_path)
    assert [(eventos.ident(e), e["fonte"]) for e in evs] == [
        ("FULA3:desdobramento:2026-10-15", "aviso aos acionistas"),
        ("FULA11:subscricao:2026-10-21", "B3, subscrição aprovada em 05/10/2026"),
        ("FULA11:restituicao:2026-10-25", "eventos.json")]
    assert evs[0]["fator"] == 3.0                                               # o fator da B3 continua


def test_evento_muda_quantidade_e_custo_como_a_in_1585_manda():
    # IN 1.585, art. 58: bonificacao pelo valor capitalizado (par. 1), desdobramento sem mudar o custo (par. 6),
    # restituicao de capital reduz o custo (par. 8); grupamento sem dinheiro entrando nem saindo; fracao fora
    cart = Carteira([pos("AAAA3", 1000, 10000.0), pos("BBBB3", 1005, 10050.0), pos("CCCC4", 1000, 20000.0),
                     pos("HHHH4", 1000, 30000.0), pos("DDDD3", 1000, 30000.0), pos("GGGG3", 100, 500.0),
                     pos("EEEE3", 500, 5000.0)])
    dia = D(2026, 10, 15)
    for tk, tipo, kw in (("AAAA3", "desdobramento", {"fator": 3.0}), ("BBBB3", "grupamento", {"fator": 0.1}),
                         ("CCCC4", "bonificacao", {"fator": 1.1, "custo_unitario": 12.5}),
                         ("HHHH4", "bonificacao", {"fator": 1.1, "novo_ticker": "HHHH3"}),
                         ("DDDD3", "restituicao", {"valor_por_acao": 2.0}), ("GGGG3", "restituicao", {"valor_por_acao": 6.0}),
                         ("EEEE3", "troca", {"novo_ticker": "FFFF3", "fator": 1.0}), ("ZZZZ3", "desdobramento", {"fator": 2.0})):
        cart.evento({"ticker": tk, "tipo": tipo, "data_com": dia.isoformat(), "fonte": "teste", **kw}, dia)
    p = {t: (x.qtd, x.custo) for t, x in cart.pos.items()}
    assert p == {"AAAA3": (3000, 10000.0), "BBBB3": (100, 10050.0), "CCCC4": (1100, 21250.0), "HHHH4": (1000, 30000.0),
                 "HHHH3": (100, 0.0), "DDDD3": (1000, 28000.0), "GGGG3": (100, 0.0), "EEEE3": (0, 0.0),
                 "FFFF3": (500, 5000.0)}
    reg = {a["ticker"]: a for a in cart.eventos_aplicados}
    assert "ZZZZ3" not in reg                                                   # sem posicao, nada a aplicar
    assert (reg["BBBB3"]["novas"], reg["BBBB3"]["fracao"]) == (-905, 0.5)
    assert (reg["HHHH4"]["alvo"], reg["HHHH4"]["sem_custo"], reg["CCCC4"]["sem_custo"]) == ("HHHH3", True, False)
    assert reg["CCCC4"]["valor"] == 1250.0 and not any(a["atrasado"] for a in cart.eventos_aplicados)
    assert cart.alertas == ["A CONFERIR: a restituição de capital de GGGG3 em 15/10/2026 (R$ 600,00) passa do custo da "
                            "posição; o custo ficou em zero."]


def test_evento_entra_no_fim_do_dia_com_depois_dos_negocios_do_dia():
    # quem compra na data com recebe o desdobramento; a venda depois sai do preco medio novo
    dc = D(2026, 10, 9)
    ev = {"ticker": "AAAA3", "tipo": "desdobramento", "data_com": dc.isoformat(), "fator": 2.0, "fonte": "teste"}
    cart = Carteira([pos("AAAA3", 900, 9000.0)])
    cart.processa([nota(dc, neg(dc, "C", "AAAA3", 100, 12.0)), nota(D(2026, 10, 20), neg(D(2026, 10, 20), "V", "AAAA3", 600, 5.0))],
                  ate=D(2026, 10, 31), desde=D(2026, 10, 1), eventos_=[ev])
    (e,) = cart.encerramentos
    assert e.resultado == pytest.approx(-60.0)                                  # 3.000 - 600 x 10.200 / 2.000
    assert (cart.pos["AAAA3"].qtd, cart.pos["AAAA3"].custo) == (1400, pytest.approx(7140.0))
    assert cart.eventos_vistos == ["AAAA3:desdobramento:2026-10-09"]


def test_fechamento_aplica_os_eventos_e_pede_o_que_falta(tmp_path):
    base = _titular(tmp_path, [])
    _partida(base, pos("VALE3", 1000, 50000.0), pos("AAAA3", 1005, 10050.0), pos("FULA11", 100, 10000.0, classe="fii"))
    evs = [{"ticker": "VALE3", "tipo": "bonificacao", "data_com": "2026-10-15", "fator": 1.1, "fonte": "teste"},
           {"ticker": "AAAA3", "tipo": "grupamento", "data_com": "2026-10-16", "fator": 0.1, "fonte": "teste"},
           {"ticker": "FULA11", "tipo": "subscricao", "data_com": "2026-10-20", "percentual": 10.0, "preco": 95.0,
            "fonte": "teste"},
           {"ticker": "VALE3", "tipo": "desdobramento", "data_com": "2026-11-20", "fator": 2.0, "fonte": "teste"}]
    (base / "eventos.json").write_text(json.dumps(evs))
    out = mes.fecha_mes(base, 2026, 10, None, D(2026, 11, 3), gravar=False)
    assert {p["ticker"]: (p["qtd"], p["custo"]) for p in out["estado"]["posicoes"]} == \
        {"VALE3": (1100, 50000.0), "AAAA3": (100, 10050.0), "FULA11": (100, 10000.0)}
    assert out["estado"]["eventos"] == ["AAAA3:grupamento:2026-10-16", "FULA11:subscricao:2026-10-20",
                                        "VALE3:bonificacao:2026-10-15"]
    sit = out["dados"]["situacao"]
    assert any(a.startswith("A CONFERIR: as 100 VALE3 da bonificação de 10% com data com 15/10/2026 entraram a custo zero")
               for a in sit["alertas"])
    assert any(a.startswith("A CONFERIR: no grupamento de 10 para 1 com data com 16/10/2026 de AAAA3 sobrou fração de "
                            "0,5000 ação") for a in sit["alertas"])
    assert ("Na B3: subscrição de 10% a R$ 95,00 por papel com data com 20/10/2026 em FULA11. Se subscrever, a compra "
            "entra quando a nota chegar; sem nota, lance em manuais.json.") in sit["alertas"]
    assert "Na B3: desdobramento de 1 para 2 com data com 20/11/2026 em VALE3; o motor aplica no fim do dia com." \
        in sit["alertas"]
    assert ("Evento da B3 aplicado em AAAA3: grupamento de 10 para 1 com data com 16/10/2026: 1.005 → 100 AAAA3, o custo "
            "total não muda (preço médio de R$ 10,00 para R$ 100,50). Fonte: teste.") in sit["conferencia"]
    # com o valor capitalizado do aviso aos acionistas, a bonificacao entra no custo e na linha BONIFICACOES do ano
    evs[0]["custo_unitario"] = 8.0
    (base / "eventos.json").write_text(json.dumps(evs))
    out = mes.fecha_mes(base, 2026, 10, None, D(2026, 11, 3), gravar=False)
    vale = next(p for p in out["estado"]["posicoes"] if p["ticker"] == "VALE3")
    assert (vale["qtd"], vale["custo"]) == (1100, 50800.0) and out["estado"]["anual"]["BONIFICAÇÕES"] == 800.0
    assert not any("custo zero" in a for a in out["dados"]["situacao"]["alertas"])
    assert ("Evento da B3 aplicado em VALE3: bonificação de 10% com data com 15/10/2026: +100 VALE3 a R$ 8,00 cada (valor "
            "capitalizado informado pela empresa). Fonte: teste.") in out["dados"]["situacao"]["conferencia"]


def test_evento_publicado_depois_do_fechamento_entra_no_mes_seguinte_e_pede_refazer(tmp_path):
    compra = {"pregao": "2026-10-20", "liquidacao": "2026-10-22", "cv": "C", "ticker": "VALE3", "ativo": "VALE ON",
              "classe": "acao", "qtd": 200, "total": 11000.0, "fonte": "teste"}
    base = _titular(tmp_path, [compra])
    mes.fecha_mes(base, 2026, 10, None, D(2026, 11, 3))                          # outubro fechado sem o evento
    (base / "eventos.json").write_text(json.dumps([{"ticker": "VALE3", "tipo": "desdobramento", "data_com": "2026-10-15",
                                                    "fator": 2.0, "fonte": "teste"}]))
    nov = mes.fecha_mes(base, 2026, 11, None, D(2026, 11, 10), gravar=False)
    assert [(p["ticker"], p["qtd"], p["custo"]) for p in nov["estado"]["posicoes"]] == [("VALE3", 2400, 61000.0)]
    sit = nov["dados"]["situacao"]
    assert any(a.startswith("A CONFERIR: o desdobramento de 1 para 2 com data com 15/10/2026 de VALE3 saiu na B3 depois do "
                            "fechamento de 10/2026, e houve negócio com o papel depois da data com (20/10): refaça o mês "
                            "(irbolsa.py fechar 2026-10)") for a in sit["alertas"])
    assert any("(a B3 publicou depois do fechamento de 10/2026; aplicado no começo de 11/2026): 1.200 → 2.400 VALE3" in c
               for c in sit["conferencia"])
    # outubro refeito: o desdobramento vem antes da compra de 20/10, e novembro nao aplica de novo
    out = mes.fecha_mes(base, 2026, 10, None, D(2026, 11, 10))
    assert [(p["ticker"], p["qtd"], p["custo"]) for p in out["estado"]["posicoes"]] == [("VALE3", 2200, 61000.0)]
    assert out["estado"]["eventos"] == ["VALE3:desdobramento:2026-10-15"]
    nov = mes.fecha_mes(base, 2026, 11, None, D(2026, 11, 10), gravar=False)
    assert [(p["ticker"], p["qtd"]) for p in nov["estado"]["posicoes"]] == [("VALE3", 2200)]
    assert not any("refaça o mês" in a for a in nov["dados"]["situacao"]["alertas"])


def test_custodia_do_banco_contra_o_motor_com_as_pistas():
    # o banco pode contar a compra de 09/11 (liquida em 11/11) pelo pregao ou pela liquidacao: 800 e 1.000 batem
    put = pos("CCCCW100", -300, -90.0, classe="opcao", vencimento=D(2026, 11, 6), strike=10.0, tipo_opcao="put",
              subjacente="CCCC3")
    compra = nota(D(2026, 11, 9), neg(D(2026, 11, 9), "C", "AAAA3", 200, 10.0))
    compra.liquidacao = D(2026, 11, 11)
    cart = carteira([pos("AAAA3", 800, 8000.0), pos("CCCC3", 300, 3000.0), pos("EEEE3", 400, 4000.0),
                     pos("FULA11", 100, 10000.0, classe="fii"), put], [compra], D(2026, 11, 10), D(2026, 11, 1))
    evs = [{"ticker": "FULA11", "tipo": "subscricao", "data_com": "2026-10-20", "percentual": 10.0, "preco": 95.0}]
    for aaaa in (800, 1000):
        of = _custodia(_of("2026-11-10T08:00:00"), "2026-11-10", ("AAAA3", aaaa), ("CCCC3", 600), ("DDDD3", 100),
                       ("FULA12", 20), ("FULA11", 100), ("CCCCW100", 300), ("EEEE3", 0))
        cus = mes.confere_custodia(mes.custodia_of(of), cart, [compra], D(2026, 11, 10), evs)
        assert (cus["data"], cus["ok"], cus["acoes"], cus["fii"]) == (D(2026, 11, 10), ["AAAA3", "FULA11"], 1, 1)
    div = {x["ticker"]: x for x in cus["divergencias"]}
    assert sorted(div) == ["CCCC3", "DDDD3", "EEEE3", "FULA12"]                 # a opcao fica de fora
    assert (div["CCCC3"]["banco"], div["CCCC3"]["motor"]) == (600, 300)
    assert div["CCCC3"]["pistas"] == ["exercício de CCCCW100 em 06/11 sem a nota (o motor tratou a opção como vencida "
                                      "sem exercício)", "compra sem nota no e-mail, transferência de outra corretora ou "
                                      "bonificação"]
    assert div["DDDD3"]["pistas"] == ["compra sem nota no e-mail, transferência de outra corretora ou bonificação"]
    assert (div["EEEE3"]["banco"], div["EEEE3"]["motor"]) == (0, 400)
    assert div["EEEE3"]["pistas"] == ["venda sem nota no e-mail, transferência para outra corretora ou ações emprestadas "
                                      "(se o banco as tira da posição até a devolução)"]
    assert div["FULA12"]["pistas"] == ["direito ou recibo de subscrição (subscrição de 10% a R$ 95,00 por papel com data "
                                       "com 20/10/2026): o motor só conta a compra quando a nota chegar"]
    assert mes.custodia_of({"conexoes": [{"investimentos": []}]}) is None


def test_custodia_no_fechamento_parcial(tmp_path):
    base = _titular(tmp_path, [])
    of = _custodia(_of("2026-10-28T08:00:00"), "2026-10-27", ("VALE3", 1000))
    of["conexoes"][0]["investimentos"][0]["isin"] = "BRVALEACNOR0"
    assert mes.isin_of(of) == {"BRVALEACNOR0": "VALE3"}
    out = mes.fecha_mes(base, 2026, 10, of, D(2026, 10, 28), gravar=False)
    assert out["custodia"]["ok"] == ["VALE3"]
    assert "Custódia do Safra de 27/10 (Open Finance) bate com o motor na posição de VALE3." in \
        out["dados"]["situacao"]["conferencia"]
    of["conexoes"][0]["investimentos"][0]["quantity"] = 900.0
    out = mes.fecha_mes(base, 2026, 10, of, D(2026, 10, 28), gravar=False)
    assert ("Custódia de VALE3 no Safra em 27/10 (Open Finance): 900 no banco, 1.000 no motor. Pode ser: venda sem nota no "
            "e-mail, transferência para outra corretora ou ações emprestadas (se o banco as tira da posição até a "
            "devolução).") in out["dados"]["situacao"]["alertas"]
    assert mes.fecha_mes(base, 2026, 10, of, D(2026, 11, 3), gravar=False)["custodia"] is None   # mes fechado nao confere


def _cotacoes(monkeypatch, **cot):
    monkeypatch.setattr(precos, "fechamento", lambda dia, tickers, cache=None, volta=15: {
        t: {"preco": cot[t], "fonte": "ultimo", "dia": "2026-11-09"} for t in tickers if t in cot})


def _opcoes(tmp_path):
    """Partida de 31/10 sem prejuizo: 500 AAAA3 a R$ 10 e duas puts lancadas que vencem em 19/11 (AAAAW100 strike 10,
    premio R$ 300; BBBBW200 strike 20, premio R$ 250); conta corrente com R$ 1.234,56."""
    base = _titular(tmp_path, [])
    put = dict(classe="opcao", vencimento=D(2026, 11, 19), tipo_opcao="put")
    _partida(base, pos("AAAA3", 500, 5000.0), pos("AAAAW100", -1000, -300.0, strike=10.0, subjacente="AAAA3", **put),
             pos("BBBBW200", -500, -250.0, strike=20.0, subjacente="BBBB3", **put), data="2026-10-31",
             prejuizos={"comum": 0.0, "daytrade": 0.0, "fii": 0.0})
    of = _of("2026-11-10T08:00:00")
    of["conexoes"][0]["contas"] = [{"type": "BANK", "subtype": "CHECKING_ACCOUNT", "balance": 1234.56,
                                    "updatedAt": "2026-11-10T07:30:00"}]
    return base, of


def test_vencimento_os_caminhos_com_darf_dinheiro_e_custo(tmp_path, monkeypatch):
    # IN 1.585, art. 60: sem exercicio o premio e ganho no vencimento (par. 3); exercida, a put lancada vira compra no
    # strike e o premio reduz o custo (II e par. 1); provavel = o caminho das que estao do lado do exercicio
    base, of = _opcoes(tmp_path)
    _cotacoes(monkeypatch, AAAA3=9.5, BBBB3=21.0)
    out = mes.fecha_mes(base, 2026, 11, of, D(2026, 11, 10), gravar=False)
    v = out["vencimento"]
    cen = {tuple(c["exercidas"]): c for c in v["cenarios"]}
    po, todas, prov = cen[()], cen[("AAAAW100", "BBBBW200")], cen[("AAAAW100",)]
    assert (po["darf"], po["caixa"], po["posicoes"], po["provavel"]) == (82.5, 0.0, {}, False)       # 15% de 550
    assert (todas["darf"], todas["caixa"], todas["provavel"]) == (0.0, -20000.0, False)
    assert {t: (x["qtd"], round(x["pm"], 2)) for t, x in todas["posicoes"].items()} == \
        {"AAAA3": (1500, 9.8), "BBBB3": (500, 19.5)}
    assert (prov["darf"], prov["caixa"], prov["provavel"]) == (37.5, -10000.0, True)                 # 15% de 250
    assert [o["unitario"] for o in v["opcoes"]] == [9.7, 19.5]
    assert v["conta"] == {"saldo": 1234.56, "em": dt.datetime(2026, 11, 10, 7, 30)}
    (al,) = [a for a in out["dados"]["situacao"]["alertas"] if a.startswith("Vencimento de ")]
    assert al == ("Vencimento de 19/11 (AAAAW100 e BBBBW200, puts lançadas): se virarem pó, o prêmio de R$ 550,00 vira "
                  "ganho e o DARF parcial do mês fica em R$ 82,50; se forem exercidas, o DARF fica em R$ 0,00 e a compra "
                  "de 1.000 AAAA3 e 500 BBBB3 pede R$ 20.000,00 na liquidação (custo por ação: AAAA3 R$ 9,70 e BBBB3 "
                  "R$ 19,50). Com o fechamento de 09/11, AAAA3 (9,50) está abaixo do strike de 10,00. A conta corrente "
                  "tinha R$ 1.234,56 em 10/11 (Open Finance).")
    assert out["apuracao"]["darf"] == 0.0 and not (base / "estado").exists()      # o mes de verdade nao muda
    txt = cli.texto_vencimento(v, "11/2026").split("\n")
    assert txt[0] == ("VENCIMENTO 11/2026 (até 19/11): Sem outras operações até o vencimento e sem as taxas do exercício, "
                      "que vêm na nota.")
    assert txt[1] == ("  AAAAW100: put lançada de 1.000 AAAA3, strike 10,00, prêmio R$ 300,00, vence 19/11; AAAA3 a 9,50 "
                      "em 09/11, do lado do exercício")
    assert txt[-2].startswith("  [provável] exercidas: AAAAW100: DARF R$ 37,50 (imposto R$ 37,50), sai R$ 10.000,00 da "
                              "conta na liquidação; fica AAAA3 ")
    assert any(x.startswith("  nenhuma exercida: ") and x.endswith(", nenhum dinheiro na liquidação") for x in txt)
    assert txt[-1] == "  Conta corrente: R$ 1.234,56 em 10/11 às 07h30 (Open Finance)"
    # as duas fora do dinheiro: dois caminhos, e o provavel e virar po
    _cotacoes(monkeypatch, AAAA3=10.5, BBBB3=21.0)
    v = mes.fecha_mes(base, 2026, 11, of, D(2026, 11, 10), gravar=False)["vencimento"]
    assert [(c["exercidas"], c["provavel"]) for c in v["cenarios"]] == [([], True), (["AAAAW100", "BBBBW200"], False)]
    assert "Com o fechamento de 09/11, nenhuma está do lado do exercício." in mes._texto_vencimento(v)
    # sem preco do ativo-objeto: os caminhos saem, sem dizer qual e o provavel
    _cotacoes(monkeypatch, AAAA3=9.5)
    v = mes.fecha_mes(base, 2026, 11, of, D(2026, 11, 10), gravar=False)["vencimento"]
    assert v["sem_preco"] == ["BBBBW200"] and not any(c["provavel"] for c in v["cenarios"])
    assert "Sem preço de BBBBW200 para dizer o lado do strike" in mes._texto_vencimento(v)
    assert cli.texto_vencimento(None, "12/2026") == "VENCIMENTO 12/2026: nenhuma opção lançada vence até o fim do mês."


def test_raiz_do_ticker_sai_do_nome_de_pregao_das_carteiras_da_b3(tmp_path):
    # a tabela vem das carteiras do dia dos indices da B3; nome com duas raizes fica de fora (a nota nao diz qual)
    cart = {"IBOV": [{"cod": "AAAA3", "asset": "EMPRESA A", "type": "ON NM"}, {"cod": "AAAA4", "asset": "EMPRESA A"},
                     {"cod": "BBBB3", "asset": "DUAS"}, {"cod": "CCCC3", "asset": "DUAS"}],
            "IFIX": [{"cod": "DDDD11", "asset": "FII FUNDO D", "type": "CI"}, {"cod": "XXXX", "asset": "SEM CODIGO"}]}
    out = ativos.atualizar_nomes(tmp_path / "nomes.json", D(2026, 11, 9), pede=lambda i: cart.get(i, []))
    assert out["nomes"] == {"EMPRESA A": "AAAA", "FII FUNDO D": "DDDD"} and "09/11/2026" in out["fonte"]
    assert ativos._nomes(tmp_path / "nomes.json") == out["nomes"] and ativos._nomes(tmp_path / "falta.json") == {}
    # a tabela gravada no pacote: nome de pregao da nota -> ticker (acao e FII), e o tickers.json do titular por cima
    for espec, tk in (("AMBEV S/A ON", "ABEV3"), ("WEG ON NM", "WEGE3"), ("MAGAZ LUIZA ON NM", "MGLU3"),
                      ("FII HGLG PAX CI ER", "HGLG11"), ("FII KINEA RI CI", "KNCR11")):
        assert ativos.identifica("VISTA", espec)["ticker"] == tk
    assert ativos.identifica("VISTA", "FULANO SA ON")["ticker"] is None
    assert ativos.identifica("VISTA", "FULANO SA ON", {"FULANO SA ON": "FULA3"})["ticker"] == "FULA3"


def test_exercicio_sem_a_serie_na_nota_casa_pela_carteira():
    # REGRAS.md, "a conferir" 3: se a nota do exercicio trouxer so o ativo-objeto, a serie sai da carteira
    i = ativos.identifica("EXERC OPC VENDA", "PETROBRAS PN N2")
    assert (i["ticker"], i["subjacente"], i["tipo_opcao"], i["exercicio"]) == ("PETR4", "PETR4", "put", True)
    assert ativos.identifica("EXERC OPC VENDA", "PETR4")["subjacente"] == "PETR4"
    assert ativos.identifica("EXERC OPC VENDA", "FULANO SA ON")["ticker"] is None
    dia = D(2026, 11, 19)
    put = dict(classe="opcao", vencimento=dia, tipo_opcao="put", subjacente="AAAA3")
    ex = neg(dia, "C", "AAAA3", 1000, 10.0, classe="opcao", mercado="EXERC OPC VENDA", tipo_opcao="put",
             subjacente="AAAA3", exercicio=True)
    cart, r = apura([pos("AAAA3", 500, 5000.0), pos("AAAAW100", -1000, -300.0, strike=10.0, **put)], [nota(dia, ex)], 2026, 11)
    assert (cart.pos["AAAA3"].qtd, cart.pos["AAAA3"].custo) == (1500, pytest.approx(14700.0))
    assert cart.pos["AAAAW100"].qtd == 0 and r["encerramentos"] == [] and cart.alertas == []
    assert cart.conferencia == ["Exercício de AAAA3 a R$ 10,00 em 19/11: a nota não trouxe a série; casado com AAAAW100 "
                                "pelo ativo-objeto, tipo e strike."]
    # duas series longe do preco do exercicio: nao adivinha, avisa
    ex = neg(dia, "C", "AAAA3", 1000, 11.0, classe="opcao", mercado="EXERC OPC VENDA", tipo_opcao="put",
             subjacente="AAAA3", exercicio=True)
    cart, _ = apura([pos("AAAAW100", -1000, -300.0, strike=10.0, **put), pos("AAAAW120", -1000, -500.0, strike=12.0, **put)],
                    [nota(dia, ex)], 2026, 11)
    assert cart.alertas == ["19/11/2026: exercício de AAAA3 sem a série na carteira"]


def test_rotina_le_os_eventos_da_b3_e_avisa_quando_a_b3_nao_responde(tmp_path, monkeypatch):
    base = _titular(tmp_path, [])
    of = _custodia(_of("2026-11-03T08:00:00"), "2026-11-03", ("FULA11", 10))
    assert cli._tickers_carteira(base, of) == {"VALE3", "FULA11"}                  # partida mais a custodia do banco
    pedidos = []
    monkeypatch.setattr(eventos, "_pede", lambda cod: pedidos.append(cod) or [])
    res = cli.diario(base, of, D(2026, 11, 3))
    assert pedidos == ["FULA", "VALE"] and res["eventos"]["n"] == 0
    assert json.loads((base / "eventos_b3.json").read_text())["desde"] == "2026-09-30"

    def falha(cod):
        raise OSError("sem rede")

    monkeypatch.setattr(eventos, "_pede", falha)
    res = cli.diario(base, _of("2026-11-04T08:00:00"), D(2026, 11, 4))
    assert "Eventos da B3 sem resposta hoje para VALE (OSError): vale a leitura anterior dessas empresas." in res["alertas"]
    assert cli.texto_eventos(base, None) == ("EVENTOS DA B3 NA CARTEIRA (última leitura gravada): nenhum depois da posição "
                                             "de partida.")
    (base / "eventos.json").write_text(json.dumps([{"ticker": "VALE3", "tipo": "desdobramento", "data_com": "2026-11-20",
                                                    "fator": 2.0, "fonte": "aviso aos acionistas"}]))
    assert cli.texto_eventos(base, None).split("\n")[1] == \
        "  20/11/2026 VALE3    desdobramento de 1 para 2 com data com 20/11/2026 (aviso aos acionistas)"


def test_strike_pelo_cadastro_de_instrumentos_da_b3(tmp_path, monkeypatch):
    # a posicao de partida da IRTrade vem sem strike, e a B3 ajusta o strike quando o ativo-objeto paga provento: o
    # cadastro de instrumentos do pregao completa e corrige; so as series pedidas ficam guardadas
    linhas = [{"TckrSymb": "AAAAW100", "Asst": "AAAA3", "OptnTp": "Put", "ExrcPric": "9,80", "XprtnDt": "2026-11-19",
               "OptnStyle": "EURO"},
              {"TckrSymb": "BBBBW200", "Asst": "BBBB3", "OptnTp": "Put", "ExrcPric": "20,00", "XprtnDt": "2026-11-19",
               "OptnStyle": "AMER"},
              {"TckrSymb": "AAAA3", "Asst": "AAAA", "OptnTp": "", "ExrcPric": "", "XprtnDt": "9999-12-31"}]
    pedidos = []

    def inst(dia):
        pedidos.append(dia)
        return linhas if dia == D(2026, 11, 6) else None                       # o de 09/11 ainda nao saiu

    monkeypatch.setattr(precos, "_instrumentos", inst)
    cache = tmp_path / "cache"
    s = precos.series(D(2026, 11, 9), ["BBBBW200", "AAAA3", "ZZZZW1"], cache)
    assert s == {"BBBBW200": {"strike": 20.0, "vencimento": "2026-11-19", "tipo": "put", "subjacente": "BBBB3",
                              "estilo": "amer", "dia": "2026-11-06"}}
    assert pedidos == [D(2026, 11, 9), D(2026, 11, 6)]                         # fim de semana nao conta
    assert precos.series(D(2026, 11, 6), ["ZZZZW1", "BBBBW200"], cache) == s
    assert pedidos == [D(2026, 11, 9), D(2026, 11, 6)]                         # guardado: nao baixa de novo
    assert precos.series(D(2026, 11, 9), [], cache) == {}
    # no fechamento: completa a serie que veio sem strike e segue o strike ajustado
    base, of = _opcoes(tmp_path)
    _cotacoes(monkeypatch, AAAA3=9.5, BBBB3=21.0)
    p = json.loads((base / "partida.json").read_text())
    for x in p["posicoes"]:
        if x["ticker"] == "BBBBW200":
            x.update(strike=None, vencimento=None, subjacente=None)
    (base / "partida.json").write_text(json.dumps(p))
    monkeypatch.setattr(precos, "_instrumentos", lambda dia: linhas)
    out = mes.fecha_mes(base, 2026, 11, of, D(2026, 11, 10), gravar=False)
    est = {x["ticker"]: x for x in out["estado"]["posicoes"]}
    assert (est["AAAAW100"]["strike"], est["BBBBW200"]["strike"], est["BBBBW200"]["vencimento"],
            est["BBBBW200"]["subjacente"]) == (9.8, 20.0, "2026-11-19", "BBBB3")
    conf = out["dados"]["situacao"]["conferencia"]
    assert ("Strike de AAAAW100 ajustado pela B3 de R$ 10,00 para R$ 9,80 (cadastro de instrumentos de 09/11): a B3 "
            "ajusta o strike quando o ativo-objeto paga provento, e o exercício sai pelo strike novo.") in conf
    assert ("BBBBW200: strike R$ 20,00, vencimento 19/11/2026, ativo-objeto BBBB3 pelo cadastro de instrumentos da B3 de "
            "09/11 (a posição veio sem esses dados).") in conf
    todas = next(c for c in out["vencimento"]["cenarios"] if len(c["exercidas"]) == 2)
    assert todas["caixa"] == -19800.0                                           # 1.000 x 9,80 + 500 x 20,00
