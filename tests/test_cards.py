"""Os cards em markdown sao o que o Douglas le as 18h40: nao podem perder o
marcador da leitura, quebrar tabela por causa de um '|' num nome, nem esconder
um UCITS atras da sigla."""

from __future__ import annotations

import re
from datetime import date

from livro import cards


def _do_dia():
    return [
        {"regra": "T05", "ativo": "MRVE3", "severidade": "critico", "familia": "preco", "canal": "mensagem",
         "titulo": "MRVE3 -8,4% no dia a R$ 5,23", "corpo": ["1m +7,2%", "Link: https://x"],
         "por_que": "sai do ruído"},
        {"regra": "T08", "ativo": "BAC", "severidade": "atencao", "familia": "preco", "canal": "mensagem",
         "titulo": "BAC entrou em correção"},
        {"regra": "E04", "ativo": "MELI34", "severidade": "atencao", "familia": "evento", "canal": "mensagem",
         "titulo": "MELI34 · 8-K: 1.01 acordo material", "dados": {"veiculo": "SEC", "link": "https://sec.gov/a"},
         "por_que": "acordo material muda receita"},
        {"regra": "T07", "ativo": "KO", "severidade": "info", "familia": "preco", "canal": "digest", "titulo": "RSI"},
        {"regra": "E05", "ativo": "VALE3", "severidade": "info", "familia": "noticia", "canal": "digest",
         "titulo": "manchete sem materialidade"},
    ]


def _ins():
    return {
        "di": {"taxas": {"DI1F28": 13.62, "DI1F35": 14.16}, "deltas": {"DI1F28": 1.0, "DI1F35": -4.0},
               "inclinacao": 54.0, "inclinacao_delta": -4.0, "verbo": "FECHOU", "rotulo": "D0"},
        "tesouro": {"IPCA2032": {"taxa": 7.58, "delta": -3.0, "apelido": "IPCA+ 2032", "tipo": "ipca"},
                    "PRE2029": {"taxa": 13.85, "delta": 4.0, "apelido": "Pre 2029", "tipo": "prefixado"}},
        "tesouro_base": "2026-09-18", "breakeven": {"2029": 6.03}, "focus_ipca": {"ano": "2027", "mediana": 4.30},
        "ust": {"2y": 4.76, "10y": 5.01, "30y": 5.34, "2s10s": 25.0, "rotulo": "D0",
                "deltas": {"2y": 9.0, "10y": 7.0, "30y": 5.0}},
        "regime": {"vix": 14.81, "vix_var": -0.04, "score": 0},
    }


def md(u, **kw):
    janelas = {a.id: {"ultimo": 100.0, "dia": 0.012, "1s": -0.004, "1m": 0.03, "6m": 0.1,
                      "1a": 0.2, "ytd": 0.05, "data": "2026-09-18"} for a in u.ativos}
    args = dict(hoje=date(2026, 9, 18), slot="fechamento", hora_txt="18h40", relogios_txt="Yahoo 18h40",
                janelas=janelas, series_info={}, do_dia=_do_dia(), ins=_ins(),
                movers={"altas": [("ETH", 0.067)], "baixas": [("MRVE3", -0.084)]},
                agenda_l=["seg 21/09 08:25 Relatorio Focus (BCB)", "    (continuacao)"],
                lacunas=[], notas=[], fontes=["Yahoo Finance"])
    args.update(kw)
    return cards.cards_md(u, **args)


def test_marcador_da_leitura_e_cards_separados(universo):
    t = md(universo)
    assert cards.MARCADOR_LEITURA in t
    assert t.count("\n---\n") >= 6          # um separador entre cards
    assert t.startswith("## Fechamento do livro · sex 18/09")


def test_uma_tabela_por_bloco_com_as_sete_janelas(universo):
    t = md(universo)
    for bloco in universo.blocos:
        if universo.por_bloco(bloco["id"]):
            assert f"### {bloco['titulo']} · variação em %" in t
    assert "| Ativo | últ | dia | 1 sem | 1 mês | 6 m | 1 ano | ano |" in t


def test_ucits_com_nome_por_extenso_abaixo_da_tabela(universo):
    t = md(universo)
    for a in universo.ucits():
        assert a.nome in t, a.id
        assert cards.nome_curto(a) in t
    assert "UCITS" not in cards.nome_curto(universo.por_id("CSPX"))
    assert cards.nome_curto(universo.por_id("BRENT")) == "Petroleo Brent"


def test_barra_em_nome_nao_quebra_a_tabela(universo):
    a = universo.por_id("USDBRL")
    nome, a.nome = a.nome, "Dolar | Real"
    try:
        linha = cards._linha(a, {"ultimo": 5.14, "dia": -0.002}, {})
    finally:
        a.nome = nome
    # so as barras nao escapadas delimitam celula: 8 colunas -> 9 delimitadores
    assert len(re.findall(r"(?<!\\)\|", linha)) == 9
    assert "Dolar \\| Real" in linha


def test_alertas_por_severidade_e_noticia_em_card_proprio(universo):
    t = md(universo)
    assert "### Alertas do dia · 2 (1 crítico)" in t
    assert "> **CRÍTICO · T05 · MRVE3**" in t
    assert "- **T08 · BAC**" in t
    assert "### Notícias e fatos · 1" in t
    assert "[abrir a fonte](https://sec.gov/a)" in t
    assert "Mais 1 sinais de baixa prioridade" in t
    assert "estão em `noticias.md`" in t and "Outras 1" not in t


def test_curvas_e_rodape(universo):
    t = md(universo)
    assert "| DI futuro (B3) · D0 | taxa | Δ dia |" in t
    assert "| F28 | 13,62 | +1 bps |" in t
    assert "**FECHOU** · inclinação F35-F28 +54 bps (-4 no dia)" in t
    assert "Focus IPCA 2027 4,30%" in t
    assert "2s10s +25 bps" in t
    assert "Resolução CVM 178" in t
    assert "**Lacunas:** nenhuma perna falhou." in t


def _em_dolar():
    return {
        "CELULOSE_CURTA": {"nome": "Celulose fibra curta (BHKP)", "unidade": "US$/t", "semanal": True,
                           "usd": 545.0, "data": "2026-09-16", "fonte": "materia publica",
                           "variacao": -0.0268, "rotulo": "preco semanal citado em fonte publica"},
        "CELULOSE_LONGA": {"nome": "Celulose fibra longa", "unidade": "US$/t", "usd": 693.1, "cny": 4928.0,
                           "fx": 7.11, "data": "2026-09-18", "pontos": 2,
                           "rotulo": "futuro SP da SHFE em CNY/t convertido",
                           "janelas": {"dia": 0.0043, "1s": None, "1m": None}},
        "MINERIO_DALIAN": {"nome": "Minerio de ferro Dalian", "unidade": "US$/t", "usd": 100.6, "cny": 715.0,
                           "fx": 7.11, "data": "2026-09-18", "pontos": 1,
                           "rotulo": "futuro da DCE em CNY/t convertido"},
    }


def test_commodities_em_dolar_com_rotulo_de_proxy(universo):
    t = md(universo, em_dolar=_em_dolar())
    assert "### Commodities em dólar · US$/t" in t
    assert "**Celulose fibra curta (BHKP)** | 545" in t
    assert "**Celulose fibra longa** | 693" in t
    assert "**Minerio de ferro Dalian** | 101" in t
    # o rotulo de proxy nunca sai de perto do numero
    assert "futuro SP da SHFE em CNY/t convertido · CNY/t 4.928 a USD/CNY 7,11" in t
    assert "preco semanal citado em fonte publica · fonte materia publica" in t
    # sem base de comparacao, diz que nao tem, em vez de mostrar 0,0
    assert "ainda sem base de comparação" in t and "Minerio de ferro Dalian" in t
    assert "| semanal |" in t          # fibra curta nao tem variacao diaria


def test_sem_proxy_em_dolar_o_card_nao_aparece(universo):
    assert "Commodities em dólar" not in md(universo)


def test_blocos_novos_em_ordem(universo):
    t = md(universo)
    ordem = ["UCITS (USD)", "ETFs EUA (USD)", "EUA · Semicondutores e óptica",
             "EUA · Tecnologia e plataformas", "EUA · Bancos",
             "EUA · Consumo, energia e indústria", "BR (R$)", "Macro"]
    pos = [t.index(f"### {x} · variação em %") for x in ordem]
    assert pos == sorted(pos), "os cards sairam fora da ordem do config"
    for tk in ("SMH", "SOXX", "QQQ", "SPY", "XLK", "VGT", "IGV", "BOTZ"):
        assert f"**{tk}**" in t, tk
    for tk in ("META", "INTC", "AMD", "PLTR", "MRVL", "AVGO", "LITE", "COHR", "GFS", "TSLA"):
        assert f"**{tk}**" in t, tk
