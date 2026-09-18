#!/usr/bin/env python3
"""
Grupos de pares para a mesa de analise.

Cada ticker pertence a um grupo principal (o primeiro em que aparece). Quando o
coletor roda com --pares auto, ele coleta o ticker pedido e todos os pares do
grupo, e grava um comparativo em comparativos/<grupo>.json no branch `dados`.

Tipo do grupo:
  financeiro  -> compare P/L, P/VP, ROE, DY e lucro; margens operacionais e
                 EV/EBITDA nao fazem sentido.
  operacional -> compare EV/EBITDA, margens, alavancagem, crescimento.

BDR_SUBJACENTE traz o simbolo nos EUA quando ele nao e as 4 primeiras letras
do BDR (ROXO34 -> NU). Os demais BDRs seguem a regra das 4 letras (MELI34 -> MELI).

Uso na linha de comando (imprime o grupo e os pares):
    python pares.py MELI34
"""

import json
import sys

PARES = {
    "bancos": {
        "nome": "Bancos", "tipo": "financeiro",
        "tickers": ["ITUB4", "BBDC4", "BBAS3", "SANB11", "BPAC11", "ROXO34"],
    },
    "fintechs": {
        "nome": "Fintechs e pagamentos", "tipo": "financeiro",
        "tickers": ["ROXO34", "INBR32", "STOC31", "PAGS", "XPBR31"],
    },
    "seguros": {
        "nome": "Seguradoras", "tipo": "financeiro",
        "tickers": ["BBSE3", "CXSE3", "PSSA3", "IRBR3"],
    },
    "ecommerce": {
        "nome": "Varejo digital e marketplaces", "tipo": "operacional",
        "tickers": ["MELI34", "MGLU3", "BHIA3", "AMER3", "AMZO34"],
    },
    "varejo_moda": {
        "nome": "Varejo de moda e calcados", "tipo": "operacional",
        "tickers": ["LREN3", "AZZA3", "CEAB3", "GUAR3", "VIVA3"],
    },
    "varejo_alimentar": {
        "nome": "Varejo alimentar", "tipo": "operacional",
        "tickers": ["ASAI3", "CRFB3", "PCAR3", "GMAT3"],
    },
    "farmacias": {
        "nome": "Farmacias", "tipo": "operacional",
        "tickers": ["RADL3", "PGMN3", "PNVL3"],
    },
    "petroleo": {
        "nome": "Petroleo e gas", "tipo": "operacional",
        "tickers": ["PETR4", "PETR3", "PRIO3", "BRAV3", "RECV3"],
    },
    "combustiveis": {
        "nome": "Distribuicao de combustiveis e etanol", "tipo": "operacional",
        "tickers": ["VBBR3", "UGPA3", "RAIZ4", "CSAN3"],
    },
    "mineracao_siderurgia": {
        "nome": "Mineracao e siderurgia", "tipo": "operacional",
        "tickers": ["VALE3", "CMIN3", "GGBR4", "CSNA3", "USIM5"],
    },
    "papel_celulose": {
        "nome": "Papel e celulose", "tipo": "operacional",
        "tickers": ["SUZB3", "KLBN11"],
    },
    "industriais": {
        "nome": "Bens de capital e industriais", "tipo": "operacional",
        "tickers": ["WEGE3", "EMBR3", "TUPY3", "POMO4", "RAPT4"],
    },
    "eletricas": {
        "nome": "Energia eletrica", "tipo": "operacional",
        "tickers": ["ELET3", "CPLE6", "CMIG4", "EGIE3", "EQTL3", "ENGI11", "TAEE11", "CPFE3", "AURE3"],
    },
    "saneamento": {
        "nome": "Saneamento", "tipo": "operacional",
        "tickers": ["SBSP3", "CSMG3", "SAPR11"],
    },
    "alimentos_bebidas": {
        "nome": "Alimentos e bebidas", "tipo": "operacional",
        "tickers": ["ABEV3", "JBSS32", "BRFS3", "MRFG3", "BEEF3", "MDIA3", "SMTO3"],
    },
    "saude": {
        "nome": "Saude", "tipo": "operacional",
        "tickers": ["RDOR3", "HAPV3", "FLRY3", "ONCO3", "DASA3", "ODPV3"],
    },
    "telecom": {
        "nome": "Telecomunicacoes", "tipo": "operacional",
        "tickers": ["VIVT3", "TIMS3"],
    },
    "construcao": {
        "nome": "Construcao civil", "tipo": "operacional",
        "tickers": ["CYRE3", "EZTC3", "MRVE3", "DIRR3", "CURY3", "TEND3", "PLPL3"],
    },
    "shoppings": {
        "nome": "Shoppings e propriedades", "tipo": "operacional",
        "tickers": ["MULT3", "IGTI11", "ALOS3", "LOGG3"],
    },
    "transporte": {
        "nome": "Transporte e infraestrutura", "tipo": "operacional",
        "tickers": ["RAIL3", "MOTV3", "ECOR3", "STBP3", "AZUL4"],
    },
    "agro": {
        "nome": "Agronegocio", "tipo": "operacional",
        "tickers": ["SLCE3", "AGRO3", "TTEN3", "SOJA3"],
    },
    "educacao": {
        "nome": "Educacao", "tipo": "operacional",
        "tickers": ["COGN3", "YDUQ3", "ANIM3", "CSED3"],
    },
    "tecnologia_br": {
        "nome": "Tecnologia Brasil", "tipo": "operacional",
        "tickers": ["TOTS3", "LWSA3", "INTB3", "POSI3"],
    },
    "big_techs": {
        "nome": "Big techs (BDRs)", "tipo": "operacional",
        "tickers": ["AAPL34", "MSFT34", "GOGL34", "AMZO34", "M1TA34", "NVDC34", "TSLA34", "NFLX34"],
    },
    "semicondutores": {
        "nome": "Semicondutores (BDRs)", "tipo": "operacional",
        "tickers": ["NVDC34", "A1MD34", "ITLC34", "TSMC34", "AVGO34"],
    },
    "bancos_eua": {
        "nome": "Bancos dos EUA (BDRs)", "tipo": "financeiro",
        "tickers": ["JPMC34", "BOAC34", "WFCO34", "CTGP34", "GSGI34", "MSBR34"],
    },
    "consumo_eua": {
        "nome": "Consumo dos EUA (BDRs)", "tipo": "operacional",
        "tickers": ["COCA34", "PEPB34", "PGCO34", "WALM34", "MCDC34", "NIKE34", "SBUB34", "DISB34"],
    },
    "farma_eua": {
        "nome": "Farmaceuticas dos EUA (BDRs)", "tipo": "operacional",
        "tickers": ["JNJB34", "PFIZ34", "MRCK34", "ABBV34", "LILY34", "AMGN34"],
    },
    "energia_eua": {
        "nome": "Petroleo dos EUA (BDRs)", "tipo": "operacional",
        "tickers": ["EXXO34", "CHVX34"],
    },
}

# BDR -> simbolo da acao-mae nos EUA, quando as 4 letras do BDR nao bastam
BDR_SUBJACENTE = {
    "ROXO34": "NU", "INBR32": "INTR", "STOC31": "STNE", "XPBR31": "XP", "JBSS32": "JBS",
    "GOGL34": "GOOGL", "GOGL35": "GOOG", "AMZO34": "AMZN", "M1TA34": "META", "NVDC34": "NVDA",
    "A1MD34": "AMD", "ITLC34": "INTC", "TSMC34": "TSM", "AVGO34": "AVGO", "BERK34": "BRK-B",
    "JPMC34": "JPM", "BOAC34": "BAC", "WFCO34": "WFC", "CTGP34": "C", "GSGI34": "GS", "MSBR34": "MS",
    "VISA34": "V", "MSCD34": "MA", "COCA34": "KO", "PEPB34": "PEP", "PGCO34": "PG", "WALM34": "WMT",
    "MCDC34": "MCD", "NIKE34": "NKE", "SBUB34": "SBUX", "DISB34": "DIS", "HOME34": "HD",
    "JNJB34": "JNJ", "PFIZ34": "PFE", "MRCK34": "MRK", "ABBV34": "ABBV", "LILY34": "LLY", "AMGN34": "AMGN",
    "ABTT34": "ABT", "EXXO34": "XOM", "CHVX34": "CVX", "BABA34": "BABA", "UBER34": "UBER",
}


def grupo_de(ticker):
    """Chave do grupo principal do ticker, ou None."""
    tk = ticker.upper()
    for chave, g in PARES.items():
        if tk in g["tickers"]:
            return chave
    return None


def pares_de(ticker):
    """Pares do ticker (sem ele mesmo), pelo grupo principal."""
    chave = grupo_de(ticker)
    if not chave:
        return []
    tk = ticker.upper()
    return [t for t in PARES[chave]["tickers"] if t != tk]


def grupos_de(ticker):
    """Todos os grupos em que o ticker aparece."""
    tk = ticker.upper()
    return [chave for chave, g in PARES.items() if tk in g["tickers"]]


if __name__ == "__main__":
    for tk in sys.argv[1:] or ["MELI34"]:
        chave = grupo_de(tk)
        print(json.dumps({"ticker": tk.upper(), "grupo": chave,
                          "nome": PARES[chave]["nome"] if chave else None,
                          "tipo": PARES[chave]["tipo"] if chave else None,
                          "pares": pares_de(tk), "outros_grupos": grupos_de(tk)[1:]},
                         ensure_ascii=False))
