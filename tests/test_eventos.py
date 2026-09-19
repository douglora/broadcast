import json
import os
from datetime import date, datetime, timezone

from livro import politica, universo as uni
from livro.fontes import cvm, noticias, sec
from livro.sinais import eventos
from livro.sinais.base import Contexto, Estado

RAW = os.path.join(os.path.dirname(__file__), "fixtures", "raw")


def _cfg():
    return uni.carregar_yaml("fontes_noticias.yaml")


def test_parse_rss_e_atribuicao():
    itens = noticias.parse_rss(open(os.path.join(RAW, "googlenews_sample.xml"), "rb").read())
    assert len(itens) == 6
    p = itens[0]
    assert p["titulo"].startswith("Petrobras anuncia dividendos") and not p["titulo"].endswith("Money Times")
    assert p["veiculo"] == "Money Times" and p["publicado"] == "2026-09-18T21:05:00Z"
    casar = _cfg()["casar"]
    assert noticias.atribuir(p["titulo"], p["descricao"], casar) == ["PETR4"]
    # "Vale a pena" nao e a Vale; "Vale fecha acordo" e
    assert "VALE3" not in noticias.atribuir(itens[2]["titulo"], "", casar)
    assert "TESOURO" in noticias.atribuir(itens[2]["titulo"], "", casar)
    assert noticias.atribuir(itens[3]["titulo"], "", casar) == ["VALE3"]
    sev, _ = noticias.materialidade(p["titulo"], p["descricao"], _cfg()["materialidade_forte"])
    assert sev == "atencao"
    sev2, _ = noticias.materialidade(itens[4]["titulo"], "", _cfg()["materialidade_forte"])
    assert sev2 == "info"
    assert noticias.gatilho(p["titulo"], "") == "dividendo"
    # descricao nao atribui ("Portal Aqui Vale" e o veiculo, nao a Vale)
    assert noticias.atribuir("Novo hotel em Sao Jose dos Campos tera investimento de R$ 70 milhoes", "Portal Aqui Vale", casar) == []
    # gatilho forte sem numero nem verbo de decisao e info; com verbo e atencao
    f = _cfg()["materialidade_forte"]
    assert noticias.materialidade("Why Does Coca-Cola (NYSE:KO) Challenge The Dividend Stocks Story?", "", f)[0] == "info"
    assert noticias.materialidade("Safra corta preço-alvo de Itaú, Bradesco e Banco do Brasil", "", f)[0] == "atencao"
    assert noticias.materialidade("Mercado está subestimando os dividendos da Petrobras? XP vê distorção", "", f)[0] == "info"
    # exclusoes e banco previsor
    ex, pv = _cfg()["excluir"], _cfg()["previsor_macro"]
    assert noticias.atribuir("Nvidia-Backed Data Center Firm Nscale Files Publicly for US IPO", "", casar, ex, pv) == []
    assert noticias.atribuir("Nvidia posts record revenue on data center demand", "", casar, ex, pv) == ["NVDA"]
    assert noticias.atribuir("Prime Video's Off Campus TV Show Lands Amazon a Big Lawsuit", "", casar, ex, pv) == []
    assert noticias.atribuir("Até onde a Selic pode cair em 2026? Bradesco revisa projeção e aponta condição-chave", "", casar, ex, pv) == ["DI"]
    assert set(noticias.atribuir("Safra corta preço-alvo de Itaú, Bradesco e Banco do Brasil", "", casar, ex, pv)) == {"ITUB4", "BBDC4", "BBAS3"}


def test_consolidar_junta_veiculos_e_licenca():
    a = {"titulo": "Petrobras anuncia dividendos de R$ 8,7 bilhões referentes ao 2º trimestre", "ativos": ["PETR4"], "licenca": "resumo", "veiculo": "InfoMoney", "publicado": "2026-09-18T21:20:00Z"}
    b = {"titulo": "Petrobras aprova dividendos de R$ 8,7 bi referentes ao 2º trimestre", "ativos": ["PETR4"], "licenca": "integral", "veiculo": "Money Times", "publicado": "2026-09-18T21:05:00Z"}
    c = {"titulo": "Bradesco terá novo aplicativo em outubro", "ativos": ["BBDC4"], "licenca": "manchete", "veiculo": "Estadao", "publicado": "2026-09-18T18:00:00Z"}
    out = noticias.consolidar([a, b, c])
    assert len(out) == 2
    petro = next(o for o in out if o["ativos"] == ["PETR4"])
    assert petro["licenca"] == "integral" and petro["fontes_extras"] == ["InfoMoney"] and not petro["fonte_unica"]
    assert next(o for o in out if o["ativos"] == ["BBDC4"])["fonte_unica"]


def test_veiculo_licenca_e_texto_html():
    v = noticias.veiculo_de("https://www.moneytimes.com.br/x/", _cfg()["veiculos"])
    assert v["licenca"] == "integral"
    assert noticias.veiculo_de("https://valor.globo.com/x", _cfg()["veiculos"])["licenca"] == "resumo"
    assert noticias.veiculo_de("https://site-desconhecido.com/x", _cfg()["veiculos"], "Site")["licenca"] == "manchete"
    txt = noticias.texto_de_html(open(os.path.join(RAW, "artigo_sample.html"), "rb").read())
    assert "8,7 bilhões" in txt and "menu menu" not in txt and "var x" not in txt
    resumo = noticias.resumo_fiel("", txt)
    assert resumo and all(any(ch.isdigit() for ch in l) or '"' in l for l in resumo)


def test_resolver_url_legado_sem_rede():
    import base64
    blob = base64.urlsafe_b64encode(b"\x08\x13\x12Zhttps://www.moneytimes.com.br/petrobras-dividendos/\xd2\x01\x00").decode().rstrip("=")
    assert noticias.resolver_url(f"https://news.google.com/rss/articles/{blob}?oc=5", None) == "https://www.moneytimes.com.br/petrobras-dividendos/"
    assert noticias.resolver_url("https://www.valor.com/x", None) == "https://www.valor.com/x"


def test_parse_ipe_casa_por_codigo_e_nome():
    texto = open(os.path.join(RAW, "ipe_sample.csv"), encoding="utf-8").read()
    docs, casadas = cvm.parse_ipe(texto, _cfg()["cvm"], date(2026, 9, 15), _cfg()["cvm_categorias"])
    ids = {d["id"] for d in docs}
    assert "CVM-PETR4-1234567" in ids and "CVM-BBDC4-1234569" in ids and "CVM-BBAS3-1234570" in ids
    assert not any(d["ativo"] == "VALE3" for d in docs), "documento antigo nao entra"
    assert not any("AGRO" in d["empresa"] for d in docs), "'BRASIL' nao pode casar Brasil Agro"
    assert not any(d["categoria"] == "Assembleia" for d in docs)
    petro = next(d for d in docs if d["id"] == "CVM-PETR4-1234567")
    assert petro["severidade"] == "atencao" and petro["protocolo"] == "1234567"
    brad = next(d for d in docs if d["ativo"] == "BBDC4")
    assert brad["severidade"] == "atencao"   # comunicado com 'guidance'
    assert casadas["PETR4"] == ["PETROLEO BRASILEIRO S.A. PETROBRAS"]
    assert cvm.texto_de_pdf_bytes(b"nao e pdf") is None


def test_parse_submissions_e_severidade():
    payload = json.load(open(os.path.join(RAW, "sec_submissions_sample.json"), encoding="utf-8"))
    fs = sec.parse_submissions(payload, date(2026, 9, 16))
    assert [f["form"] for f in fs] == ["8-K", "8-K"]
    assert sec.severidade("8-K", ["2.02", "9.01"]) == ("atencao", ["2.02 resultado do trimestre"])
    assert sec.severidade("8-K", ["4.02"])[0] == "critico"
    assert sec.severidade("10-K", [])[0] == "info"
    assert sec.texto_de_html(b"<html><body><p>Revenue was $14.2 billion</p><script>x</script></body></html>") == "Revenue was $14.2 billion"
    r = sec.coletar({"MU": "MU"}, ua=None)
    assert r["disponivel"] is False and "SEC_USER_AGENT" in r["motivo"]


def test_regras_de_evento_geram_alertas(universo, limiares):
    ev = {"noticias": json.load(open("tests/fixtures/eventos/noticias.json"))["itens"],
          "cvm": json.load(open("tests/fixtures/eventos/cvm.json"))["docs"],
          "sec": json.load(open("tests/fixtures/eventos/sec.json"))["filings"], "config": _cfg()}
    ctx = Contexto(universo=universo, limiares=limiares, hoje=date(2026, 9, 18), eventos=ev, agora_iso="2026-09-18T22:41:00Z")
    al = []
    for r in eventos.REGRAS:
        al += r.avaliar(ctx, Estado())
    ids = {a.id for a in al}
    assert "E05-PETR4-abc1234567-2026-09-18" in ids and "E03-PETR4-1234567-2026-09-18" in ids and "E04-MU-26000090-2026-09-18" in ids
    n = next(a for a in al if a.regra == "E05" and a.ativo == "PETR4")
    assert n.severidade == "atencao" and "Do texto:" in n.texto() and "Money Times" in n.corpo[0] and "+ InfoMoney" in n.corpo[0]
    assert len(n.texto()) <= 1100 and "Link: https://www.moneytimes.com.br" in n.texto()
    assert "compre" not in n.texto().lower()
    c = next(a for a in al if a.regra == "E03")
    assert "Fato Relevante" in c.titulo and "Do documento:" in c.texto() and "R$ 0,67" in c.texto()
    s = next(a for a in al if a.regra == "E04")
    assert s.severidade == "atencao" and "2.02" in s.titulo and "$14.2 billion" in s.texto()
    # politica: cada noticia e mensagem propria; info vira linha; orcamento proprio
    r = politica.aplicar([a.para_json() for a in al], [], limiares, "intradia", "intradia", {"critico": 0, "atencao": 4})
    msgs = {m["ids"][0]: m for m in r["mensagens"]}
    assert n.id in msgs and c.id in msgs and s.id in msgs, "teto tecnico cheio nao suprime noticia/evento"
    assert all(i["severidade"] == "info" for i in r["linhas_info"]) and any(i["ativo"] == "BBDC4" for i in r["linhas_info"])
    pushes = [m["push"] for m in r["mensagens"] if m.get("push")]
    assert len(pushes) == 1 and "detalhe na sessão" in pushes[0] and "E03 PETR4" in pushes[0] and "evento:" not in pushes[0]


class _CliFalso:
    """Devolve o RSS de amostra para qualquer GET; POST falha (resolvedor cai no link do Google)."""
    def __init__(self):
        self.payload = open(os.path.join(RAW, "googlenews_sample.xml"), "rb").read()
        self.chamadas = 0

    def get(self, url, **kw):
        from livro.http import Resposta
        self.chamadas += 1
        return Resposta(200, self.payload, {}, url)

    def post(self, url, **kw):
        from livro.http import HttpError
        raise HttpError(0, "sem rede", url)


def test_coletar_noticias_filtra_e_consolida():
    cfg = dict(_cfg())
    cfg["consultas"] = [{"id": "teste", "lang": "pt-BR", "q": "x"}]
    cli = _CliFalso()
    r = noticias.coletar(cfg, {}, cli=cli, agora=datetime(2026, 9, 18, 22, 0, tzinfo=timezone.utc), dormir=lambda s: None)
    ativos = {tuple(i["ativos"]) for i in r["itens"]}
    assert ("PETR4",) in ativos and ("VALE3",) in ativos and ("BBDC4",) in ativos
    assert not any("KLBN4" in i["ativos"] for i in r["itens"]), "materia velha nao entra"
    petro = next(i for i in r["itens"] if i["ativos"] == ["PETR4"])
    assert petro["fontes_extras"] == ["InfoMoney"] and petro["severidade"] == "atencao" and petro["licenca"] == "integral"
    assert petro["id"].startswith("N-") and petro["hash"] in r["vistos"]
    assert r["descartados"]["velho"] == 1 and r["consultas"] == 1
    # segunda rodada com os mesmos vistos nao devolve nada
    r2 = noticias.coletar(cfg, r["vistos"], cli=cli, agora=datetime(2026, 9, 18, 22, 30, tzinfo=timezone.utc), dormir=lambda s: None)
    assert r2["itens"] == [] and r2["descartados"]["visto"] >= 3


def test_cvm_data_iso_e_diagnostico():
    assert cvm.data_iso("18/09/2026") == "2026-09-18" and cvm.data_iso("2026-09-18 19:02:11") == "2026-09-18"
    texto = open(os.path.join(RAW, "ipe_sample.csv"), encoding="utf-8").read()
    d = cvm.diagnostico(texto, date(2026, 9, 15))
    assert d["linhas"] == 6 and d["na_janela"] == 5 and d["categorias_janela"]["Fato Relevante"] == 2
    assert d["max_data_entrega"] == "2026-09-18" and d["ultimos_5"][0][0] == "2026-09-18"
    assert d["amostra"] and d["amostra"][0]["Codigo_CVM"] == "9512"


def test_politica_reapresentado_nao_repete_push(limiares):
    a = {"id": "T04-UGPA3-maxima-2026-09-18", "regra": "T04", "ativo": "UGPA3", "severidade": "atencao", "familia": "preco",
         "titulo": "UGPA3 algo", "corpo": [], "por_que": "", "como_falar": "", "fonte": "f", "texto": "x"}
    r = politica.aplicar([], [a], limiares, "intradia", "intradia", {"critico": 0, "atencao": 0})
    assert len(r["mensagens"]) == 1 and r["mensagens"][0]["push"] is None and r["mensagens"][0]["texto"].startswith("(pendente")


def test_parse_rad_html_e_docs():
    html = ('<tr><td>009512</td><td>PETRÓLEO BRASILEIRO S.A. - PETROBRAS</td><td>Fato Relevante</td><td>Fato Relevante</td>'
            '<td>-</td><td>18/09/2026</td><td>18/09/2026 19:02</td><td>AC</td><td>1</td><td>AP</td>'
            '<td><i onclick="OpenPopUpVer(\'frmExibirArquivoIPEExterno.aspx?NumeroProtocoloEntrega=1234567\')"></i></td></tr>'
            '<tr><td>020036</td><td>BRASIL AGRO</td><td>Fato Relevante</td><td>Fato Relevante</td><td>-</td><td>18/09/2026</td>'
            '<td>18/09/2026 10:00</td><td>AC</td><td>1</td><td>AP</td><td><i onclick="OpenPopUpVer(\'x?NumeroProtocoloEntrega=1\')"></i></td></tr>'
            '<tr><td>000906</td><td>BCO BRADESCO S.A.</td><td>Assembleia</td><td>AGE</td><td>Edital</td><td>18/09/2026</td>'
            '<td>18/09/2026 11:00</td><td>AC</td><td>1</td><td>AP</td><td></td></tr>')
    linhas = cvm.parse_rad_html(html)
    assert len(linhas) == 3 and linhas[0]["codigo"] == "9512" and linhas[0]["protocolo"] == "1234567" and linhas[0]["data"] == "2026-09-18"
    docs, casadas = cvm.docs_de_linhas(linhas, _cfg()["cvm"], date(2026, 9, 16), _cfg()["cvm_categorias"])
    assert [d["id"] for d in docs] == ["CVM-PETR4-1234567"] and docs[0]["origem"] == "rad" and docs[0]["severidade"] == "atencao"
    assert "PETR4" in casadas
    corpo = cvm.rad_corpo(date(2026, 9, 16), date(2026, 9, 18))
    assert '"dataDe": "16/09/2026"' in corpo and '"categoria": "TODAS"' in corpo


def test_rad_listar_repoe_parametro_que_falta():
    """Simula o WebMethod: 500 'missing value for parameter' ate receber tipoEmpresa e saoPaulo; depois devolve linhas."""
    import json as _json
    from livro.http import Resposta
    html = ('<tr><td>009512</td><td>PETROBRAS</td><td>Fato Relevante</td><td>Fato Relevante</td><td>-</td><td>18/09/2026</td>'
            '<td>18/09/2026 19:02</td><td>AC</td><td>1</td><td>AP</td><td><i onclick="x(\'a?NumeroProtocoloEntrega=77\')"></i></td></tr>')

    class Cli:
        def __init__(self):
            self.corpos = []

        def post(self, url, data=None, headers=None, timeout=None):
            self.corpos.append(_json.loads(data))
            if "saoPaulo" not in self.corpos[-1]:
                return Resposta(500, b'{"Message":"Invalid web service call, missing value for parameter: \\u0027saoPaulo\\u0027."}', {}, url)
            if self.corpos[-1]["categoria"] != "TODAS":
                return Resposta(200, b'{"d":{"dados":"","totalRegistros":0}}', {}, url)
            return Resposta(200, _json.dumps({"d": {"dados": html, "totalRegistros": 1}}).encode(), {}, url)

    cli = Cli()
    r = cvm.rad_listar(cli, date(2026, 9, 15), date(2026, 9, 18))
    assert r["linhas"] and r["linhas"][0]["protocolo"] == "77"
    assert r["diagnostico"]["extras"] == {"saoPaulo": "0"} and len(cli.corpos) == 2
    assert cli.corpos[-1]["tipoEmpresa"] == "0" and cli.corpos[-1]["saoPaulo"] == "0"


def test_parse_rad_dados_formato_string():
    dados = ("00951-2$&PETRÓLEO BRASILEIRO S.A. - PETROBRAS$&Fato Relevante$& - $&<spanOrder>20260918</spanOrder>18/09/2026$&"
             "<spanOrder>202609181902</spanOrder>18/09/2026 19:02$&Ativo$&1$&AP$&<i onclick=OpenPopUpVer('frmExibirArquivoIPEExterno.aspx?NumeroProtocoloEntrega=1234567')> </i><i onclick=OpenDownloadDocumentos('1092871','1','1234567','IPE')> </i>$&Documento Diversos$&&*"
             "00090-6$&BCO BRADESCO S.A.$&Comunicado ao Mercado$&Esclarecimentos sobre consultas CVM/B3$&<spanOrder>x</spanOrder> - $&17/09/2026$&17/09/2026 08:30$&Ativo$&1$&AP$&9876543$&Documento Diversos$&&*"
             "02205-5$&MARISA LOJAS S.A.$&Assembleia$&AGO$&Edital$&18/09/2026$&18/09/2026 10:00$&Ativo$&1$&AP$&111$&Documento Diversos")
    linhas, diag = cvm.parse_rad_dados(dados)
    assert diag["separador"] == "$&&*" and len(linhas) == 3
    p = linhas[0]
    assert p["codigo"] == "9512" and p["categoria"] == "Fato Relevante" and p["data"] == "2026-09-18" and p["entregue_em"] == "18/09/2026 19:02"
    assert p["protocolo"] == "1234567" and p["data_referencia"] == "2026-09-18"
    assert p["tipo"] == "" and p["especie"] == ""   # datas nao viram tipo/assunto
    b = linhas[1]
    assert b["codigo"] == "906" and b["tipo"].startswith("Esclarecimentos") and b["protocolo"] == "9876543"
    docs, casadas = cvm.docs_de_linhas(linhas, _cfg()["cvm"], date(2026, 9, 16), _cfg()["cvm_categorias"])
    assert {d["ativo"] for d in docs} == {"PETR4", "BBDC4"} and next(d for d in docs if d["ativo"] == "BBDC4")["severidade"] == "info"
    petro = next(d for d in docs if d["ativo"] == "PETR4")
    assert petro["assunto"] == "Fato Relevante" and "numSequencia=1092871" in petro["download"] and "numProtocolo=1234567" in petro["download"]


def test_assunto_de_texto_pula_cabecalho():
    txt = ("PETRÓLEO BRASILEIRO S.A. – PETROBRAS\nCNPJ/ME 33.000.167/0001-01\nCOMPANHIA ABERTA\nFATO RELEVANTE\n"
           "A Petrobras informa que seu Conselho de Administração aprovou a distribuição de R$ 8,7 bilhões em dividendos. "
           "O pagamento ocorrerá em duas parcelas.")
    a = cvm.assunto_de_texto(txt, "Fato Relevante", "PETRÓLEO BRASILEIRO S.A. - PETROBRAS")
    assert a.startswith("A Petrobras informa que seu Conselho") and "CNPJ" not in a
    assert cvm.assunto_de_texto(None) == ""


def test_cvm_retenta_pdf_de_documento_visto():
    """Primeiro run: PDF nao veio (texto False). Segundo run: PDF vem, doc volta como 'atualizado'."""
    from livro.http import Resposta
    html = ("00951-2$&PETROLEO BRASILEIRO S.A. PETROBRAS$&Fato Relevante$& - $& - $&18/09/2026$&18/09/2026 19:02$&Ativo$&1$&AP$&"
            "<i onclick=OpenPopUpVer('frmExibirArquivoIPEExterno.aspx?NumeroProtocoloEntrega=555')> </i>$&Documento Diversos")
    import json as _json

    class Cli:
        def __init__(self, pdf_ok):
            self.pdf_ok = pdf_ok

        def post(self, url, data=None, headers=None, timeout=None):
            return Resposta(200, _json.dumps({"d": {"dados": html}}).encode(), {}, url)

        def get(self, url, **kw):
            if "NumeroProtocoloEntrega" in url and self.pdf_ok:
                return Resposta(200, b"%PDF-1.4 fake", {"content-type": "application/pdf"}, url)
            return Resposta(200, b"<html>viewer</html>", {"content-type": "text/html"}, url)

    alvos = {"PETR4": {"codigo": 9512, "nomes": ["PETROBRAS"]}}
    r1 = cvm.coletar(alvos, cli=Cli(False), hoje=date(2026, 9, 18), dias=2, com_ipe=False)
    assert len(r1["docs"]) == 1 and r1["docs"][0]["texto"] is None and r1["vistos"]["CVM-PETR4-555"]["texto"] is False
    assert r1["docs"][0]["pdf_diag"]
    # segundo run: pypdf nao le o PDF falso, mas o caminho de retentativa e exercitado (tentativas sobe)
    r2 = cvm.coletar(alvos, cli=Cli(True), hoje=date(2026, 9, 18), dias=2, vistos=r1["vistos"], com_ipe=False)
    assert r2["retentados"] == 1 and r2["vistos"]["CVM-PETR4-555"]["tentativas"] == 2
    # vistos no formato antigo (so data) tambem entram na retentativa
    r3 = cvm.coletar(alvos, cli=Cli(True), hoje=date(2026, 9, 18), dias=2, vistos={"CVM-PETR4-555": {"data": "2026-09-18"}}, com_ipe=False)
    assert r3["retentados"] == 1


def test_assunto_e_resumo_de_fato_relevante_real():
    txt = ("COMPANHIA DE SANEAMENTO BÁSICO\nDO ESTADO DE SÃO PAULO – SABESP\nCompanhia Aberta\nCNPJ/MF nº 43.776.517/0001-80\n\n"
           "FATO RELEVANTE CONJUNTO\n\nA COMPANHIA DE SANEAMENTO BÁSICO DO ESTADO DE SÃO PAULO – SABESP (“Sabesp”) e a EMAE, em atendimento ao art. 157, "
           "§ 4º, da Lei nº 6.404, vêm informar que o prazo para o exercício do direito de retirada dos acionistas da EMAE termina em 20 de outubro de 2026. "
           "Nos termos do artigo 137 e 252, § 2º, da Lei das S.A., a Incorporação de Ações enseja o direito de retirada. "
           "O valor de reembolso é de R$ 12,34 por ação, conforme o balanço de 30 de junho de 2026.")
    a = cvm.assunto_de_texto(txt, "Fato Relevante", "CIA SANEAMENTO BASICO EST SAO PAULO")
    assert a.startswith("O prazo para o exercício do direito de retirada"), a
    r = noticias.resumo_fiel("", txt)
    assert any("R$ 12,34" in l for l in r) and not any(l.startswith("137 e 252") for l in r)
    assert r[0].startswith("A COMPANHIA") or r[0].startswith("O valor") or "20 de outubro" in r[0]


def test_sec_user_agent_aceita_email_ou_url(monkeypatch):
    """A SEC exige contato declarado; vale e-mail ou URL publica, nunca UA generico."""
    monkeypatch.setenv("SEC_USER_AGENT", "broadcast-livro/1.0 (+https://github.com/douglora/broadcast)")
    assert sec.user_agent().startswith("broadcast-livro/1.0")
    monkeypatch.setenv("SEC_USER_AGENT", "Fulano fulano@exemplo.com")
    assert sec.user_agent() == "Fulano fulano@exemplo.com"
    for ruim in ("", "   ", "python-requests/2.31", "bot"):
        monkeypatch.setenv("SEC_USER_AGENT", ruim)
        assert sec.user_agent() is None
    monkeypatch.delenv("SEC_USER_AGENT")
    assert sec.user_agent() is None and sec.coletar({"MU": "MU"})["disponivel"] is False


def test_sec_tenta_variantes_de_contato(monkeypatch):
    """403 no contato por URL nao pode parar a perna: tenta o formato de e-mail publico."""
    from livro.http import HttpError, Resposta
    monkeypatch.setenv("GITHUB_REPOSITORY_OWNER", "douglora")
    monkeypatch.setenv("GITHUB_REPOSITORY", "douglora/broadcast")
    vs = sec.variantes_ua("broadcast-livro/1.0 (+https://github.com/douglora/broadcast)")
    assert vs[1] == sec.UA_PADRAO and "@users.noreply.github.com" in vs[2] and "douglaslora" not in " ".join(vs)
    assert sec.variantes_ua("Fulano fulano@exemplo.com") == ["Fulano fulano@exemplo.com", sec.UA_PADRAO]
    # cabecalhos iguais aos do coletor que funciona
    h = sec._cabecalhos("X")
    assert h["Accept"] == "*/*" and h["Accept-Language"] is None

    class Cli:
        def __init__(self):
            self.uas = []

        def get(self, url, headers=None, **kw):
            ua = (headers or {}).get("User-Agent", "")
            self.uas.append(ua)
            if "@" not in ua:
                raise HttpError(403, "Your Request Originates from an Undeclared Automated Tool", url)
            return Resposta(200, b'{"0":{"cik_str":723125,"ticker":"MU","title":"MICRON"}}', {}, url)

    cli = Cli()
    ciks, bom, tent = sec.abrir_catalogo(cli, "broadcast-livro/1.0 (+https://github.com/douglora/broadcast)", ["MU"])
    assert ciks == {"MU": 723125} and "@" in bom and bom == sec.UA_PADRAO
    assert tent[0]["status"] == 403 and tent[-1]["status"] == 200 and len(cli.uas) == 2


def test_sonda_hosts_monta_a_matriz():
    from livro.http import HttpError, Resposta

    class Cli:
        def get(self, url, headers=None, **kw):
            ua = (headers or {}).get("User-Agent", "")
            if "data.sec.gov" in url and "@" in ua:
                return Resposta(404, b"<html><body>Not Found</body></html>", {}, url)
            raise HttpError(403, "Undeclared Automated Tool", url)

    m = sec.sondar_hosts(Cli(), ["robo/1.0 (+https://x)", "Fulano f@x.com"], dormir=lambda s: None)
    assert set(m) == set(sec.ALVOS_SONDA)
    assert m["data/submissions"]["Fulano f@x.com"]["status"] == 404
    assert m["data/submissions"]["robo/1.0 (+https://x)"]["status"] == 403
    assert m["www/company_tickers"]["Fulano f@x.com"]["status"] == 403
