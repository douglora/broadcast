"""O painel HTML nao pode inventar numero, quebrar no celular nem engolir o
marcador da leitura: e a pagina que o Douglas abre no telefone."""

from __future__ import annotations

import html
import re
from datetime import date

from livro import painel


def _ins():
    return {
        "di": {"taxas": {"DI1F28": 13.62, "DI1F35": 14.16}, "deltas": {"DI1F28": 1.0, "DI1F35": -4.0},
               "inclinacao": 54.0, "inclinacao_delta": -4.0, "verbo": "FECHOU", "rotulo": "D0"},
        "tesouro": {"PRE2029": {"taxa": 13.85, "delta": 4.0, "pu": 746.11, "apelido": "Pre 2029", "tipo": "prefixado"},
                    "IPCA2032": {"taxa": 7.58, "delta": -3.0, "pu": 3083.29, "apelido": "IPCA+ 2032", "tipo": "ipca"}},
        "tesouro_base": "2026-09-18",
        "breakeven": {"2029": 6.03},
        "focus_ipca": {"ano": "2027", "mediana": 4.30},
        "ust": {"2y": 4.76, "10y": 5.01, "30y": 5.34, "2s10s": 25.0, "d2s10s": -2.0, "rotulo": "D0",
                "deltas": {"2y": 9.0, "10y": 7.0, "30y": 5.0}},
        "regime": {"vix": 14.81, "vix_var": -0.0408, "score": 0},
    }


def _alertas():
    return [
        {"id": "T05-MRVE3-queda-2026-09-18", "regra": "T05", "ativo": "MRVE3", "severidade": "critico",
         "familia": "preco", "canal": "mensagem", "titulo": "MRVE3 -8,4% no dia a R$ 5,23",
         "corpo": ["1m +7,2% · 6m -27%"], "por_que": "sai do ruído", "fonte": "Yahoo Finance fech. 18/09"},
        {"id": "T08-BAC-2026-09-18", "regra": "T08", "ativo": "BAC", "severidade": "atencao",
         "familia": "preco", "canal": "mensagem", "titulo": "BAC entrou em correção"},
        {"id": "E04-MELI34-2026-09-10", "regra": "E04", "ativo": "MELI34", "severidade": "atencao",
         "familia": "evento", "canal": "mensagem", "titulo": "MELI34 · 8-K: 1.01 acordo material",
         "corpo": ["SEC EDGAR · aceito 10/09", "Link: https://www.sec.gov/Archives/edgar/x.htm"],
         "por_que": "acordo material muda receita", "dados": {"veiculo": "SEC"}},
        {"id": "E05-XX-2026-09-18", "regra": "E05", "ativo": "DI", "severidade": "info",
         "familia": "noticia", "canal": "digest", "titulo": "manchete qualquer"},
        {"id": "T07-KO-2026-09-18", "regra": "T07", "ativo": "KO", "severidade": "info",
         "familia": "preco", "canal": "digest", "titulo": "RSI"},
    ]


def pagina(u, **kw):
    janelas = {a.id: {"ultimo": 100.0, "dia": 0.012, "1s": -0.004, "1m": 0.03,
                      "6m": 0.1, "1a": 0.2, "ytd": 0.05, "data": "2026-09-18"} for a in u.ativos}
    args = dict(hoje=date(2026, 9, 18), slot="fechamento", hora_txt="18h40", relogios_txt="Yahoo 18h40",
                janelas=janelas, series_info={}, do_dia=_alertas(), ins=_ins(),
                movers={"altas": [("ETH", 0.067)], "baixas": [("MRVE3", -0.084)]},
                agenda_l=["seg 21/09 08:25 Relatorio Focus (BCB)", "    continuacao"],
                lacunas=[], notas=["Minério: proxy Dalian 715 CNY/t."],
                fontes=["Yahoo Finance", "BCB"])
    args.update(kw)
    return painel.pagina(u, **args)


def test_marcador_da_leitura_sobrevive_e_nao_vira_tag(universo):
    h = pagina(universo)
    assert painel.MARCADOR_LEITURA in h
    assert "<" not in painel.MARCADOR_LEITURA  # senao o navegador come o marcador


def test_bloco_traz_a_mediana_do_dia(universo):
    h = pagina(universo)
    assert "mediana do dia" in h and "ativos ·" in h


def test_estrutura_minima(universo):
    h = pagina(universo)
    assert h.startswith("<title>")
    assert "fonts.googleapis.com" in h
    for bloco in universo.blocos:
        if universo.por_bloco(bloco["id"]):
            assert bloco["titulo"] in h


def test_ucits_aparecem_por_extenso(universo):
    h = pagina(universo)
    for a in universo.ucits():
        assert html.escape(a.nome, quote=True) in h, a.id


def test_alertas_separados_por_severidade_e_familia(universo):
    h = pagina(universo)
    assert "MRVE3 -8,4% no dia a R$ 5,23" in h
    assert "8-K: 1.01 acordo material" in h          # noticia vai para o cartao de noticias
    assert "2 para ler" in h and "1 crítico" in h    # o info de preco nao conta como mensagem
    assert "Mais 1 sinais" in h or "Mais 1 sinal" in h


def test_curvas_sem_verde_vermelho_em_bps(universo):
    h = pagina(universo)
    assert "13,62" in h and "+1 bps" in h and "FECHOU" in h
    assert "7,58%" in h and "IPCA+ 2032" in h
    assert "2s10s +25 bps" in h
    # o delta de taxa nao pode carregar a classe de alta/baixa
    assert not re.search(r'class="cd (alta|baixa)', h)


def test_sinal_segue_o_numero_exibido():
    assert painel._sinal(0.0002) == "zero"    # exibido como 0,0%
    assert painel._sinal(-0.0002) == "zero"
    assert painel._sinal(0.012) == "alta"
    assert painel._sinal(None) == "nulo"
    assert painel._larg(0.001) == 0           # sem barra em movimento invisivel
    assert painel._larg(0.04) == 100


def test_escapa_conteudo_de_terceiros(universo):
    veneno = [{"id": "E05-X", "regra": "E05", "ativo": "VALE3", "severidade": "atencao", "familia": "noticia",
               "canal": "mensagem", "titulo": "<script>alert(1)</script> & cia",
               "dados": {"veiculo": "<b>x</b>", "link": "https://exemplo.com/a?b=1&c=2"}}]
    h = pagina(universo, do_dia=veneno)
    assert "<script>alert(1)</script>" not in h
    assert "&lt;script&gt;" in h
    assert "https://exemplo.com/a?b=1&amp;c=2" in h


def test_celular_nao_rola_de_lado(universo):
    h = pagina(universo)
    assert "overflow-x:auto" in h              # tabela larga rola dentro do cartao
    assert "@media (max-width:620px)" in h    # painel estreito ao lado do chat
    assert not re.search(r"min-width:\s*(\d{3,})px", h.replace("minmax(330px", ""))


def test_cabecalho_e_linha_tem_o_mesmo_numero_de_colunas(universo):
    """Cabecalho com 10 colunas e linha com 8 desloca tudo: o 6 m aparece sob 3 m e
    YTD e 5 anos ficam vazios. Foi o que aconteceu ao acrescentar as janelas novas."""
    import re
    h = pagina(universo)
    tabela = h.split('<section class="cartao bloco">')[1]
    cabecalho = re.search(r"<thead>(.*?)</thead>", tabela, re.S).group(1)
    linha = re.search(r"<tbody>(.*?)</tr>", tabela, re.S).group(1)
    assert len(re.findall(r"<th ", cabecalho)) == 10
    assert len(re.findall(r"<t[hd][ >]", linha)) == 10


def test_todas_as_janelas_aparecem_na_linha(universo):
    janelas = {a.id: {"ultimo": 100.0, "dia": 0.012, "1s": -0.004, "1m": 0.03, "3m": 0.077,
                      "6m": 0.1, "1a": 0.2, "ytd": 0.05, "5a": 1.234, "data": "2026-09-18"}
               for a in universo.ativos}
    h = pagina(universo, janelas=janelas)
    for v in ("+7,7%", "+123%"):      # 3 meses e 5 anos nao podem sumir
        assert v in h, v

def test_rotulo_por_slot(universo):
    """O painel e republicado em todo slot; o <h1> tem de dizer qual e, e o <title>
    NAO pode mudar (renomearia o Artifact fixado na barra lateral do Douglas)."""
    for slot, rotulo in (("manha", "Manhã do livro"),
                         ("intradia", "O livro agora"),
                         ("fechamento", "Fechamento do livro")):
        h = pagina(universo, slot=slot)
        assert f"<h1>{rotulo}</h1>" in h, slot
        assert h.startswith("<title>Livro monitorado</title>"), slot
