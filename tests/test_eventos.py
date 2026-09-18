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
    assert d["amostra"] and d["amostra"][0]["Codigo_CVM"] == "9512"


def test_politica_reapresentado_nao_repete_push(limiares):
    a = {"id": "T04-UGPA3-maxima-2026-09-18", "regra": "T04", "ativo": "UGPA3", "severidade": "atencao", "familia": "preco",
         "titulo": "UGPA3 algo", "corpo": [], "por_que": "", "como_falar": "", "fonte": "f", "texto": "x"}
    r = politica.aplicar([], [a], limiares, "intradia", "intradia", {"critico": 0, "atencao": 0})
    assert len(r["mensagens"]) == 1 and r["mensagens"][0]["push"] is None and r["mensagens"][0]["texto"].startswith("(pendente")
