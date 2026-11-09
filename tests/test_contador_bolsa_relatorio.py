"""Relatorio mensal de renda variavel e DARF (camada visual do contador de bolsa): HTML, formato e PDF. Sem rede.

Os dados abaixo sao inventados (FULANO DE TAL, CPF zerado). Os testes de PDF usam o Chrome do Mac e pulam sozinhos sem ele;
todo arquivo gerado fica em tmp_path.
"""

import math
import os
import re
import sys
from pathlib import Path

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_DIR = os.path.join(RAIZ, "ferramentas", "local")
for p in (RAIZ, LOCAL_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from contador_bolsa import darf as DARF  # noqa: E402
from contador_bolsa import relatorio as REL  # noqa: E402

CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
COR = "SAFRA CORRETORA"


# ------------------------------------------------------------------ dados de exemplo (inventados)
def _acao(corretora, ticker, ativo, qtd, pm, preco, venc=None):
    inv = qtd * pm
    valor = None if preco is None else qtd * preco
    lp = None if valor is None else valor - inv
    r = {"corretora": corretora, "ticker": ticker, "ativo": ativo, "qtd": qtd, "pm": pm, "investido": inv,
         "pct": 0.0, "preco": preco, "valor": valor, "ganho_pct": None if lp is None else lp / abs(inv) * 100,
         "lp": lp}
    if venc:
        r["vencimento"] = venc
    return r


def _soma(linhas, k):
    return sum((r.get(k) or 0.0) for r in linhas)


def _linha_op(corretora, ticker, ativo, d_liq, cv, q, preco, d_est, pm, comum, day):
    return {"corretora": corretora, "ticker": ticker, "ativo": ativo,
            "liq": {"data": d_liq, "cv": cv, "qtd": q, "preco": preco, "total": q * preco},
            "estoque": {"data": d_est, "cv": "C", "qtd": q, "preco": pm, "total": q * pm},
            "comum": comum, "daytrade": day}


def _anual_exemplo() -> dict:
    """Resultados do ano, coerentes entre si (soma, impostos, despesas e liquido); numeros inventados."""
    mm = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]
    zeros = [0.0] * 12
    linhas = {
        "OP. COMUM": [1250.40, 0.0, 980.25, -2310.60, 1875.10, 95.30, -640.75, 420.0, 1130.90, 2210.45, 0.0, 0.0],
        "OP. DAYTRADE": [0.0, 85.20, 0.0, -40.0, 0.0, 0.0, 0.0, 0.0, -12.50, 198.0, 0.0, 0.0],
        "OP. F.I.I FIAGRO": [-60.0, 0.0, 0.0, 0.0, 140.30, 0.0, 0.0, 0.0, 0.0, 62.0, 0.0, 0.0],
        "PROVENTOS": [210.50, 98.75, 54.20, 190.0, 80.15, 70.0, 155.30, 120.0, 175.60, 719.30, 0.0, 0.0],
        "PROVENTOS BTC DOADOR": [0.0, 12.0, 0.0, 0.0, 3.50, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "VENDAS ISENTAS": [0.0, 3100.0] + [0.0] * 10,
        "BONIFICAÇÕES": [450.0] + [0.0] * 11,
        "INCENTIVADAS": list(zeros),
    }
    soma = [round(sum(v[i] for v in linhas.values()), 2) for i in range(12)]
    impostos = [-20.0, 0.0, -36.50, 0.0, -70.20, 0.0, 0.0, 0.0, -15.0, -650.11, 0.0, 0.0]
    despesas = [-30.0, -22.50, -18.0, -12.0, -9.50, -4.0, -6.0, -3.50, -2.0, -45.80, 0.0, 0.0]
    liquido = [round(a + b + c, 2) for a, b, c in zip(soma, impostos, despesas)]
    linhas.update({"SOMA DOS RESULTADOS": soma, "IMPOSTOS": impostos, "DESPESAS": despesas, "LÍQUIDO MÊS": liquido})
    return {"ano": 2026, "meses": mm, "nota": "",
            "linhas": [{"rotulo": rot, "valores": v, "total": round(sum(v), 2), "destaque": rot == "LÍQUIDO MÊS"}
                       for rot, v in linhas.items()]}


def dados_exemplo() -> dict:
    cor = COR
    acoes = [
        _acao(cor, "PETR4", "PETROBRAS PN N2", 1200, 31.42, 37.88),
        _acao(cor, "VALE3", "VALE ON NM", 800, 61.10, 55.35),
        _acao(cor, "ITUB4", "ITAUUNIBANCO PN N1", 1500, 28.75, 33.10),
        _acao(cor, "BBDC4", "BRADESCO PN N1", 2000, 12.64, 14.02),
        _acao(cor, "WEGE3", "WEG ON NM", 600, 39.80, 47.21),
        _acao(cor, "MGLU3", "MAGAZ LUIZA ON NM", 3500, 8.37, 9.55),
        _acao(cor, "ABEV3", "AMBEV S/A ON", 2500, 13.05, 12.31),
        _acao("XP INVESTIMENTOS CORRETORA DE CAMBIO TITULOS E VALORES MOBILIARIOS S/A", "B3SA3",
              "B3 ON NM", 1800, 11.90, 13.64),
    ]
    fii = [
        _acao(cor, "HGLG11", "FII CSHG LOG CI", 120, 158.40, 161.20),
        _acao(cor, "KNCR11", "FII KINEA CI CI", 200, 103.50, 104.85),
        _acao(cor, "XPML11", "FII XP MALLS CI", 150, 109.20, 112.04),
        _acao(cor, "MXRF11", "FII MAXI REN CI", 900, 9.85, 9.61),
        _acao(cor, "KNRI11", "FII KINEA RI CI", 100, 141.00, 146.30),
        _acao(cor, "BTLG11", "FII BTG LOG CI", 140, 99.40, 102.75),
        _acao(cor, "VISC11", "FII VINCI SC CI", 110, 118.60, 121.55),
        _acao(cor, "HGRU11", "FII CSHG RENDA URBANA CI", 90, 124.30, 128.10),
    ]
    opcoes_vendidas = [
        _acao(cor, "PETRK350", "PETRK350 PN", -1000, 0.85, 0.40, "17/11/2026"),
        _acao(cor, "VALEW600", "VALEW600 ON", -800, 1.12, 0.95, "17/11/2026"),
        _acao(cor, "ITUBW300", "ITUBW300 PN", -1500, 0.46, 0.20, "21/12/2026"),
        _acao(cor, "BBDCL140", "BBDCL140 PN", -2000, 0.38, 0.52, "21/12/2026"),
    ]
    opcoes_compradas = [_acao(cor, "BBASM480", "BBASM480 ON", 1000, 0.30, 0.45, "21/12/2026")]
    termos = [_acao(cor, "PETR4T", "TERMO PETROBRAS PN", 300, 30.10, 37.88, "17/12/2026")]
    btc = [_acao(cor, "VALE3", "VALE ON NM", -200, 60.00, 55.35)]
    fii_vendidas = [_acao(cor, "KNRI11", "FII KINEA RI CI", -10, 141.00, 146.30)]
    todas = acoes + fii + opcoes_vendidas + opcoes_compradas + termos + btc + fii_vendidas
    soma_abs = sum(abs(r["investido"]) for r in todas)
    for r in todas:
        r["pct"] = abs(r["investido"]) / soma_abs * 100

    def mercado(nome, lista):
        return {"mercado": nome, "investido": _soma(lista, "investido"), "valor": _soma(lista, "valor"),
                "lp": _soma(lista, "lp")}

    resumo = [mercado("Ações", acoes), mercado("FII", fii), mercado("Opções Vendidas", opcoes_vendidas),
              mercado("Termos", termos), mercado("Opções Compradas", opcoes_compradas),
              mercado("Ações BTC (Vendidas)", btc), mercado("FII (Vendidas)", fii_vendidas)]
    total_pos = {k: sum(r[k] for r in resumo) for k in ("investido", "valor", "lp")}

    g_venda = [
        _linha_op(cor, "PETRK320", "PETRK320 PN", "05/10/2026", "V", 1000, 0.62, "05/10/2026", 0.0, 620.0, None),
        _linha_op(cor, "VALEW580", "VALEW580 ON", "09/10/2026", "V", 800, 0.84, "09/10/2026", 0.0, 672.0, None),
        _linha_op(cor, "ITUBW290", "ITUBW290 PN", "14/10/2026", "C", 1500, 0.12, "02/09/2026", 0.51, 585.0, None),
        _linha_op(cor, "WEGEK450", "WEGEK450 ON", "20/10/2026", "V", 600, 0.55, "20/10/2026", 0.0, None, 198.0),
    ]
    g_vista = []
    nomes = [("PETR4", "PETROBRAS PN N2", 31.42, 38.10), ("VALE3", "VALE ON NM", 61.10, 56.20),
             ("ITUB4", "ITAUUNIBANCO PN N1", 28.75, 33.40), ("BBDC4", "BRADESCO PN N1", 12.64, 14.30),
             ("WEGE3", "WEG ON NM", 39.80, 46.90), ("MGLU3", "MAGAZ LUIZA ON NM", 8.37, 9.95),
             ("ABEV3", "AMBEV S/A ON", 13.05, 12.60), ("B3SA3", "B3 ON NM", 11.90, 13.80),
             ("RENT3", "LOCALIZA ON NM", 44.10, 41.30), ("SUZB3", "SUZANO S.A. ON NM", 52.60, 55.40),
             ("RADL3", "RAIADROGASIL ON NM", 24.30, 22.80), ("PRIO3", "PETRORIO ON NM", 42.90, 47.20),
             ("EGIE3", "ENGIE BRASIL ON NM", 38.10, 40.20)]
    for i in range(25):
        tk, nm, pm, pv = nomes[i % len(nomes)]
        q = 100 * (1 + i % 6)
        dia = 1 + (i % 28)
        d = f"{dia:02d}/10/2026"
        res = round(q * (pv - pm), 2)
        corr = cor if i % 5 else "XP INVESTIMENTOS CORRETORA DE CAMBIO TITULOS E VALORES MOBILIARIOS S/A"
        g_vista.append(_linha_op(corr, tk, nm, d, "V", q, pv, d, pm, res if i % 4 else None, None if i % 4 else res))
    g_fii = [
        _linha_op(cor, "MXRF11", "FII MAXI REN CI", "08/10/2026", "V", 300, 9.70, "08/10/2026", 9.85, -45.0, None),
        _linha_op(cor, "HGLG11", "FII CSHG LOG CI", "15/10/2026", "V", 20, 163.00, "15/10/2026", 158.40, 92.0, None),
        _linha_op(cor, "KNCR11", "FII KINEA CI CI", "22/10/2026", "V", 30, 104.00, "22/10/2026", 103.50, 15.0, None),
    ]
    g_exerc = [
        _linha_op(cor, "PETRK320", "PETRK320 PN", "19/10/2026", "V", 500, 32.00, "19/10/2026", 31.42, 290.0, None),
        _linha_op(cor, "VALEW580", "VALEW580 ON", "19/10/2026", "C", 300, 58.00, "19/10/2026", 61.10, None, None),
    ]
    grupos = [
        {"titulo": "Opções de Venda", "comum": 1877.0, "daytrade": 198.0, "linhas": g_venda},
        {"titulo": "Mercado à Vista", "comum": _soma(g_vista, "comum"), "daytrade": _soma(g_vista, "daytrade"),
         "linhas": g_vista},
        {"titulo": "Fii", "comum": 62.0, "daytrade": 0.0, "linhas": g_fii},
        {"titulo": "Exercício de Opções", "comum": 290.0, "daytrade": 0.0, "linhas": g_exerc},
    ]
    quadro = [
        {"tipo": "Comum", "resultado": 4251.37, "prejuizo": 0.0, "base": 4251.37, "imposto": 637.71},
        {"tipo": "Day Trade", "resultado": -103.40, "prejuizo": 103.40, "base": 0.0, "imposto": 0.0},
        {"tipo": "Fii", "resultado": 62.0, "prejuizo": 0.0, "base": 62.0, "imposto": 12.40},
        {"tipo": "Isentos", "resultado": 1320.0, "prejuizo": 0.0, "base": 0.0, "imposto": 0.0},
        {"tipo": "Total", "resultado": 5529.97, "prejuizo": 103.40, "base": 4313.37, "imposto": 650.11},
    ]
    barras = [{"rotulo": "Comum", "valor": 4251.37}, {"rotulo": "Day Trade", "valor": -103.40},
              {"rotulo": "Fii", "valor": 62.0}, {"rotulo": "Isentos", "valor": 1320.0}]

    extrato = {"periodo": "01/10/2026 até 31/10/2026", "corretora": cor, "linhas": [
        {"lancamento": "Saldo anterior", "debito": None, "credito": None, "saldo": 1500.00},
        {"lancamento": "Compra de ações (nota 4521)", "debito": -5230.40, "credito": None, "saldo": -3730.40},
        {"lancamento": "Venda de ações (nota 4533)", "debito": None, "credito": 9120.75, "saldo": 5390.35},
        {"lancamento": "Dividendos PETR4", "debito": None, "credito": 412.80, "saldo": 5803.15},
        {"lancamento": "Rendimentos HGLG11", "debito": None, "credito": 186.00, "saldo": 5989.15},
        {"lancamento": "Taxa de custódia", "debito": -18.90, "credito": None, "saldo": 5970.25},
        {"lancamento": "TED enviada", "debito": -4000.00, "credito": None, "saldo": 1970.25},
    ], "totais": {"debito": -9249.30, "credito": 9719.55, "saldo": 1970.25}}

    meses = ["11/2025", "12/2025", "01/2026", "02/2026", "03/2026", "04/2026", "05/2026", "06/2026", "07/2026",
             "08/2026", "09/2026", "10/2026"]
    vals = [310.20, 0.0, 455.10, 287.45, 612.90, 198.30, 0.0, 740.00, 523.15, 410.60, 365.00, 719.30]
    proventos = {
        "por_corretora": [{"corretora": cor, "dividendos": 412.80, "jcp": 120.50, "rendimentos": 186.00,
                           "bonificacoes": None, "reembolso_btc": 0.0, "rendimentos_btc": 0.0, "total": 719.30}],
        "total": {"dividendos": 412.80, "jcp": 120.50, "rendimentos": 186.00, "bonificacoes": None,
                  "reembolso_btc": 0.0, "rendimentos_btc": 0.0, "total": 719.30},
        "meses_12": [{"rotulo": m, "valor": v} for m, v in zip(meses, vals)],
        "total_12m": sum(vals),
        "detalhe": [{"data": "03/10/2026", "ticker": "PETR4", "tipo": "Dividendos", "valor": 412.80},
                    {"data": "10/10/2026", "ticker": "ITUB4", "tipo": "JCP", "valor": 120.50},
                    {"data": "15/10/2026", "ticker": "HGLG11", "tipo": "Rendimentos", "valor": 186.00}],
    }
    prox = ["11/2026", "12/2026", "01/2027", "02/2027", "03/2027", "04/2027", "05/2027", "06/2027", "07/2027",
            "08/2027", "09/2027", "10/2027"]
    pv = [220.0, 180.5, 0.0, 95.0, 310.0, 0.0, 142.0, 0.0, 88.0, 0.0, 260.0, 75.5]
    provisionados = {
        "proximos_12m": [{"rotulo": m, "valor": v} for m, v in zip(prox, pv)],
        "total_12m": sum(pv), "sem_data_total": 45.30,
        "por_corretora": [{"corretora": cor, "dividendos": 1100.0, "jcp": 180.5, "rendimentos": 135.8, "total": 1416.3}],
        "linhas": [{"ticker": "BBDC4", "previsao": "03/11/2026", "corretora": cor, "valor": 220.0},
                   {"ticker": "KNCR11", "previsao": "14/11/2026", "corretora": cor, "valor": 180.5},
                   {"ticker": "ITUB4", "previsao": "01/12/2026", "corretora": cor, "valor": 95.0},
                   {"ticker": "WEGE3", "previsao": "15/12/2026", "corretora": cor, "valor": 310.0},
                   {"ticker": "VALE3", "previsao": "22/12/2026", "corretora": cor, "valor": 142.0}],
        "total": 947.5,
    }
    situacao = {
        "darfs": [{"periodo": "08/2026", "codigo": "6015", "vencimento": "30/09/2026", "valor": 412.10, "situacao": "Pago"},
                  {"periodo": "09/2026", "codigo": "6015", "vencimento": "30/10/2026", "valor": 233.40, "situacao": "Pago"},
                  {"periodo": "10/2026", "codigo": "6015", "vencimento": "30/11/2026", "valor": 650.11, "situacao": "A pagar"}],
        "prejuizos": [{"tipo": "Operações comuns", "valor": 0.0}, {"tipo": "Day trade", "valor": 103.40},
                      {"tipo": "Fundos imobiliários", "valor": 0.0}],
        "alertas": ["Valor do DARF abaixo de R$ 10,00 fica acumulado para o mês seguinte.",
                    "Há uma opção vendida (BBDCL140) perto do vencimento: confira o risco de exercício.",
                    "A nota de corretagem de 22/10/2026 não bateu com o extrato; o cálculo usou a nota."],
        "conferencia": ["Posição final de PETR4 confere com a custódia da corretora em 31/10/2026.",
                        "Preço médio de ITUB4 recalculado após o desdobramento de 03/2026.",
                        "Proventos de HGLG11 conferidos com o informe do fundo.",
                        "Sem divergência entre os dois extratos do mês."],
    }
    return {
        "titular": {"nome": "FULANO DE TAL", "documento": "000.000.000-00"},
        "competencia": "10/2026", "gerado_em": "02/11/2026", "data_posicao": "31/10/2026", "corretora": cor,
        "resumo_posicao": resumo, "total_posicao": total_pos,
        "posicoes": {"acoes": acoes, "fii": fii, "opcoes_vendidas": opcoes_vendidas,
                     "opcoes_compradas": opcoes_compradas, "termos": termos, "btc": btc, "fii_vendidas": fii_vendidas},
        "operacoes": {"quadro": quadro, "barras": barras, "grupos": grupos},
        "extrato": extrato, "proventos": proventos, "provisionados": provisionados, "anual": _anual_exemplo(),
        "situacao": situacao,
    }


def dados_mes_sem_movimento() -> dict:
    """Mes sem posicao nem operacao, no formato exato que o motor entrega (listas vazias, zeros, chaves a mais)."""
    mercados = ["Ações", "FII", "Opções Vendidas", "Termos", "Opções Compradas", "Ações BTC (Vendidas)", "FII (Vendidas)"]
    zeros = {"dividendos": 0.0, "jcp": 0.0, "rendimentos": 0.0, "bonificacoes": 0.0, "reembolso_btc": 0.0,
             "rendimentos_btc": 0.0, "total": 0.0}
    meses12 = [{"rotulo": f"{(i + 11) % 12 + 1:02d}/{2025 + (i + 11) // 12}", "valor": 0.0} for i in range(12)]
    return {
        "titular": {"nome": "FULANO DE TAL", "documento": "000.000.000-00"}, "competencia": "11/2026",
        "gerado_em": "03/11/2026", "data_posicao": "03/11/2026", "corretora": COR, "parcial": True,
        "resumo_posicao": [{"mercado": m, "investido": 0.0, "valor": 0.0, "lp": 0.0} for m in mercados],
        "total_posicao": {"investido": 0.0, "valor": 0.0, "lp": 0.0},
        "posicoes": {k: [] for k in ("acoes", "fii", "opcoes_vendidas", "opcoes_compradas", "termos", "btc",
                                     "fii_vendidas")},
        "operacoes": {"quadro": [{"tipo": t, "resultado": 0.0, "prejuizo": 0.0, "base": 0.0, "imposto": 0.0}
                                 for t in ("Comum", "Day Trade", "Fii", "Isentos", "Total")],
                      "barras": [{"rotulo": r, "valor": 0.0} for r in ("BMF", "BOVESPA", "FII/FIAGRO", "OPÇÃO FLEXIVEL")],
                      "grupos": [], "comum": 0.0, "daytrade": 0.0},
        "extrato": {"periodo": "01/11/2026 até 03/11/2026", "corretora": COR, "linhas": [],
                    "totais": {"debito": 0.0, "credito": 0.0, "saldo": 0.0}},
        "proventos": {"por_corretora": [dict(zeros, corretora=COR)], "total": dict(zeros), "meses_12": meses12,
                      "total_12m": 0.0, "detalhe": []},
        "provisionados": {"proximos_12m": [dict(m) for m in meses12], "total_12m": 0.0, "sem_data_total": 0.0,
                          "por_corretora": [], "linhas": [], "total": 0.0},
        "anual": {"ano": 2026, "meses": ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"],
                  "nota": "", "linhas": [{"rotulo": k, "valores": [0.0] * 12, "total": 0.0, "destaque": k in ("SOMA", "LÍQUIDO")}
                                          for k in ("OP. COMUM", "DAYTRADE", "FII", "PROVENTOS", "BTC DOADOR",
                                                    "VENDAS ISENTAS", "BONIFICAÇÕES", "SOMA", "IMPOSTOS", "DESPESAS",
                                                    "LÍQUIDO")]},
        "situacao": {"darfs": [], "prejuizos": [{"tipo": "Comum", "valor": 0.0}, {"tipo": "Day Trade", "valor": 0.0},
                                                {"tipo": "FII", "valor": 0.0}],
                     "alertas": [], "conferencia": ["Mês em andamento: apurado até 03/11."]},
    }


def darf_exemplo() -> dict:
    return {"nome": "FULANO DE TAL", "telefone": "", "periodo_apuracao": "31/10/2026", "documento": "000.000.000-00",
            "codigo_receita": "6015", "referencia": "", "vencimento": "30/11/2026", "principal": 650.11, "multa": 0.0,
            "juros": 0.0, "total": 650.11, "mes_ref": "OUTUBRO", "ano_ref": 2026, "valido_ate": "30/11/2026",
            "observacao": ""}


@pytest.fixture(scope="module")
def pagina():
    return REL.html_relatorio(dados_exemplo())


@pytest.fixture(scope="module")
def pagina_darf():
    return DARF.html_darf(darf_exemplo())


def _paginas(html: str) -> list[str]:
    return re.findall(r'<section class="pg">.*?</section>', html, flags=re.S)


def _texto(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def _linhas_corpo(html: str) -> int:
    """Quantas linhas de corpo (<tr> dentro de <tbody>) ha no HTML."""
    return sum(t.count("<tr") for t in re.findall(r"<tbody>(.*?)</tbody>", html, flags=re.S))


# ------------------------------------------------------------------ formato
def test_formato_brasileiro():
    assert REL.brl(1234.56) == "R$ 1.234,56"
    assert REL.brl(-1234.56) == "-R$ 1.234,56"
    assert REL.brl(0) == "R$ 0,00"
    assert REL.brl(-0.001) == "R$ 0,00"
    assert REL.brl(None) == "-"
    assert REL.pct(12.3449) == "12,34 %"
    assert REL.pct(12.346) == "12,35 %"
    assert REL.pct(-5.6) == "-5,60 %"
    assert REL.pct(None) == "-"
    assert REL.qtd(1200) == "1.200"
    assert REL.qtd(-1000) == "-1.000"
    assert REL.dat(None) == "-"
    assert REL.dat("31/10/2026") == "31/10/2026"
    assert REL.num(1234567.891) == "1.234.567,89"


# ------------------------------------------------------------------ relatorio: estrutura e textos
def test_paginas_e_titulos(pagina):
    assert pagina.startswith("<!doctype html>")
    assert '<meta charset="utf-8">' in pagina
    txt = _texto(pagina)
    for trecho in ["Relatório Mensal", "OPERAÇÕES DE RENDA VARIÁVEL", "Posição de Carteira",
                   "Previsão de Resultados em 31/10/2026", "Total L &amp; P", "Posição de Ações (Compradas)",
                   "Posição de Fundos Imobiliários ou nas Cadeias Produtivas AgroIndustriais - FIAGRO (Compradas)",
                   "Posição de Opções Vendidas", "Posição de Opções Compradas", "Posição de Termos",
                   "Posição de Ações BTC (Vendidas)", "Posição de FII (Vendidas)", "Operações Finalizadas no Mês",
                   "OUTUBRO/2026", "Opções de Venda Operações Comum", "Mercado à Vista Operações Comum",
                   "Exercício de Opções", "Data Liquidação", "Data de Estoque", "Extrato Consolidado",
                   "01/10/2026 até 31/10/2026", "Lançamentos", "Totais", "Proventos Recebidos no Mês",
                   "Bonificações em ações", "Recebidos nos Últimos 12 Meses", "Detalhe dos Proventos Recebidos",
                   "Proventos Provisionados", "Próximos Recebimentos", "Total de Proventos Provisionados",
                   "Resultados Anuais 2026", "SOMA DOS RESULTADOS", "LÍQUIDO MÊS", "Situação Fiscal", "DARFs",
                   "Prejuízos a Compensar", "Alertas", "Conferência", "Disclaimer:", "Demonstrativo Mensal: 10/2026",
                   "Gerado em: 02/11/2026", "Nome: FULANO DE TAL", "CPF / CNPJ: 000.000.000-00"]:
        assert trecho in txt, trecho
    assert "Monitoramento" not in txt          # a pagina de monitoramento do modelo virou "Situação Fiscal"


def test_numeros_formatados(pagina):
    txt = _texto(pagina)
    # posicao: 1.200 PETR4 a 31,42 e a 37,88
    assert "R$ 31,42" in txt and "R$ 37,88" in txt and "1.200" in txt
    assert "R$ 37.704,00" in txt            # 1.200 x 31,42 (investido)
    assert "R$ 45.456,00" in txt            # 1.200 x 37,88 (valor de mercado)
    # negativos no formato -R$, nunca R$ -
    assert re.search(r"-R\$ \d", txt)
    assert not re.search(r"R\$ -\d", txt)
    # percentuais com espaco antes do sinal, virgula decimal
    assert re.search(r"\d,\d\d %", txt)
    assert "20,56 %" in txt                 # ganho da PETR4: (37,88 - 31,42) / 31,42
    # quadro de resultados e DARF
    assert "R$ 650,11" in txt and "R$ 637,71" in txt
    # sem formatos americanos, notacao cientifica nem lixo de Python
    assert not re.search(r"\d\.\d\d(?!\d)\s*%", txt)
    assert "e+" not in txt and "nan" not in txt.lower().split() and "None" not in txt


def test_valor_ausente_vira_traco():
    d = dados_exemplo()
    d["posicoes"]["acoes"][0].update({"preco": None, "valor": None, "ganho_pct": None, "lp": None})
    txt = _texto(REL.html_relatorio(d))
    assert "None" not in txt
    assert re.search(r"R\$ 37\.704,00 [\d,]+ % - - - ", txt)         # investido, % carteira, depois so tracos


def test_sem_marca_nem_contato_de_terceiros(pagina, pagina_darf):
    for h in (pagina, pagina_darf):
        baixo = h.lower().replace("@page", "")
        assert "http" not in baixo and "www." not in baixo and "@" not in baixo and ".com.br" not in baixo
    # o relatorio nao leva imagem nenhuma (nem logotipo); o DARF leva so o brasao da Republica
    assert "<img" not in pagina.lower() and "base64" not in pagina.lower() and "<svg" in pagina
    assert pagina_darf.lower().count("<img") <= 2
    assert "telefone" not in _texto(pagina).lower()


def test_secao_some_se_a_lista_vem_vazia():
    d = dados_exemplo()
    d["posicoes"]["fii"] = []
    d["posicoes"]["opcoes_vendidas"] = []
    h = REL.html_relatorio(d)
    assert "Fundos Imobiliários ou nas Cadeias" not in h
    assert "Posição de Opções Vendidas" not in h
    assert "Posição de Ações (Compradas)" in h
    d2 = dados_exemplo()
    d2["extrato"] = None
    d2["provisionados"] = None
    d2["situacao"] = None
    d2["anual"] = None
    h2 = REL.html_relatorio(d2)
    for titulo in ("Extrato Consolidado", "Proventos Provisionados", "Situação Fiscal", "Resultados Anuais"):
        assert titulo not in h2, titulo


def test_texto_com_caracteres_especiais_e_escapado():
    d = dados_exemplo()
    d["posicoes"]["acoes"][0]["ativo"] = 'AT&T <b>"X"</b>'
    d["situacao"]["alertas"] = ["Alerta com <script>alert(1)</script> e & comercial"]
    d["titular"]["nome"] = "FULANO & FILHOS <LTDA>"
    h = REL.html_relatorio(d)
    assert "AT&amp;T &lt;b&gt;" in h and 'AT&T <b>' not in h               # o texto do dado nunca vira marcacao
    assert "<script>" not in h and "alert(1)</script>" not in h
    assert "&lt;script&gt;alert(1)&lt;/script&gt; e &amp; comercial" in h
    assert "FULANO &amp; FILHOS &lt;LTDA&gt;" in h


def test_dados_minimos_nao_quebram():
    d = {"titular": {"nome": "FULANO DE TAL", "documento": "000.000.000-00"}, "competencia": "10/2026",
         "gerado_em": "02/11/2026", "data_posicao": "31/10/2026", "corretora": "X"}
    h = REL.html_relatorio(d)
    assert "Relatório Mensal" in h and len(_paginas(h)) >= 1


def test_mes_sem_movimento_no_formato_do_motor():
    h = REL.html_relatorio(dados_mes_sem_movimento())
    txt = _texto(h)
    assert "None" not in txt and "nan" not in txt.lower().split()
    for trecho in ["Relatório Mensal", "Sem posição em carteira nesta data", "Previsão de Resultados em 03/11/2026",
                   "Sem operações finalizadas no mês.", "NOVEMBRO/2026", "Extrato Consolidado", "Proventos Recebidos no Mês",
                   "Proventos Provisionados", "Resultados Anuais 2026", "SOMA DOS RESULTADOS", "Situação Fiscal",
                   "Nenhum DARF a pagar neste período.", "Mês em andamento: apurado até 03/11."]:
        assert trecho in txt, trecho
    assert "Posição de Ações" not in txt and "Mercado à Vista" not in txt          # sem linhas, sem tabela
    assert "Disclaimer:" in _paginas(h)[1]


def test_aviso_em_todas_as_paginas_menos_a_capa(pagina):
    pgs = _paginas(pagina)
    assert "Disclaimer:" not in pgs[0]
    for p in pgs[1:]:
        assert "Disclaimer:" in p
    assert "Confira os valores antes de pagar o DARF" in pagina
    assert "Lei 11.033/2004" in pagina


# ------------------------------------------------------------------ tabelas longas
def _dados_com_grupo_longo(n: int, corretora: str = "SAFRA") -> dict:
    d = dados_exemplo()
    linhas = [_linha_op(corretora, f"TST{i:03d}", "ATIVO DE TESTE", "05/10/2026", "V", 100, 10.0, "05/10/2026", 9.0,
                        100.0, None) for i in range(n)]
    d["operacoes"]["grupos"] = [{"titulo": "Mercado à Vista", "comum": 100.0 * n, "daytrade": 0.0, "linhas": linhas}]
    return d


def test_tabela_longa_quebra_pagina_repetindo_titulo_e_cabecalho():
    n = 60
    h = REL.html_relatorio(_dados_com_grupo_longo(n))
    com_tabela = [p for p in _paginas(h) if "Mercado à Vista Operações Comum" in _texto(p)]
    assert len(com_tabela) >= 3, "60 linhas nao cabem em duas paginas"
    for p in com_tabela:
        t = _texto(p)
        assert "Total c/ Taxas" in t and "Day Trade" in t and "Data Liquidação" in t      # cabecalho repetido
        assert "Disclaimer:" in t                                                           # e o aviso de rodape
    # nenhuma linha some nem se repete
    assert sum(_linhas_corpo(p) for p in com_tabela) == n
    for i in range(n):
        assert sum(p.count(f">TST{i:03d}<") for p in com_tabela) == 1
    # cada bloco acaba acima do rodape: topo + titulo + cabecalho + linhas de 15,758 pt
    for p in com_tabela:
        for topo, corpo in re.findall(r'left:16\.80pt;top:([\d.]+)pt"><table class="t o".*?<tbody>(.*?)</tbody>', p,
                                      flags=re.S):
            fim = float(topo) + 34.02 + corpo.count("<tr") * REL.H_LIN
            assert fim <= REL.Y_FUNDO + 0.01, (topo, fim)


def test_linha_nunca_fica_sozinha_no_fim_da_pagina():
    # uma tabela que sobra com uma linha so na pagina nova nao deve deixar o bloco anterior com uma linha so
    for n in range(20, 70):
        h = REL.html_relatorio(_dados_com_grupo_longo(n))
        com_tabela = [p for p in _paginas(h) if "Mercado à Vista Operações Comum" in _texto(p)]
        assert sum(_linhas_corpo(p) for p in com_tabela) == n
        if len(com_tabela) > 1:
            assert all(_linhas_corpo(p) >= 2 for p in com_tabela[:-1]), n


def test_provisionados_lista_longa_vai_para_pagina_propria():
    d = dados_exemplo()
    curta = REL.html_relatorio(d)
    assert sum("Próximos Recebimentos" in _texto(p) for p in _paginas(curta)) == 1
    d["provisionados"]["linhas"] = [
        {"ticker": f"TST{i:02d}", "previsao": "15/12/2026", "corretora": COR, "valor": 10.0 + i} for i in range(20)]
    d["provisionados"]["total"] = sum(10.0 + i for i in range(20))
    longa = REL.html_relatorio(d)
    pgs = [p for p in _paginas(longa) if "Próximos Recebimentos" in _texto(p)]
    assert len(pgs) == 2
    assert "+ 13 na lista completa" in _texto(pgs[0])                    # 7 linhas na pagina + 13 na lista
    assert all(f">TST{i:02d}<" in pgs[1] for i in range(20))             # a lista completa tem as 20
    assert sum(f">TST{i:02d}<" in pgs[0] for i in range(20)) == 7


def test_extrato_por_corretora_vira_um_bloco_cada():
    d = dados_exemplo()
    outro = dict(d["extrato"], corretora="OUTRA CORRETORA")
    d["extrato"] = [d["extrato"], outro]
    txt = _texto(REL.html_relatorio(d))
    assert txt.count("Taxa de custódia") == 2 and "OUTRA CORRETORA" in txt and "SAFRA CORRETORA" in txt


# ------------------------------------------------------------------ resultados anuais
def _anual_por_rotulo(html: str) -> dict:
    """{rotulo: <tr> da linha} da tabela de resultados anuais."""
    pg = [p for p in _paginas(html) if "Resultados Anuais" in p][0]
    por_rotulo = {}
    for tr in re.findall(r"<tr[^>]*>.*?</tr>", pg, flags=re.S):
        m = re.search(r"<td[^>]*>([^<]+)</td>", tr)
        if m:
            por_rotulo[m.group(1)] = tr
    return por_rotulo


def test_anual_aceita_rotulos_curtos_e_meses_em_minuscula():
    # o motor manda DAYTRADE, FII, BTC DOADOR, SOMA e LIQUIDO e os meses como "Jan": o relatorio usa os nomes do modelo
    d = dados_exemplo()
    curtos = {"OP. DAYTRADE": "DAYTRADE", "OP. F.I.I FIAGRO": "FII", "PROVENTOS BTC DOADOR": "BTC DOADOR",
              "SOMA DOS RESULTADOS": "SOMA", "LÍQUIDO MÊS": "LÍQUIDO"}
    for linha in d["anual"]["linhas"]:
        linha["rotulo"] = curtos.get(linha["rotulo"], linha["rotulo"])
        linha["destaque"] = linha["rotulo"] in ("SOMA", "LÍQUIDO")
    d["anual"]["meses"] = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
    h = REL.html_relatorio(d)
    por_rotulo = _anual_por_rotulo(h)
    assert list(por_rotulo) == ["OP. COMUM", "OP. DAYTRADE", "OP. F.I.I FIAGRO", "PROVENTOS", "PROVENTOS BTC DOADOR",
                                "VENDAS ISENTAS", "BONIFICAÇÕES", "INCENTIVADAS", "SOMA DOS RESULTADOS", "IMPOSTOS",
                                "DESPESAS", "LÍQUIDO MÊS"]
    assert por_rotulo["SOMA DOS RESULTADOS"].startswith('<tr class="f">')       # filete, sem negrito (como no modelo)
    assert por_rotulo["LÍQUIDO MÊS"].startswith('<tr class="f b z">')
    assert ">JAN</th>" in h and ">DEZ</th>" in h and ">Jan<" not in h


def test_anual_cor_vem_da_linha_como_no_modelo(pagina):
    por_rotulo = _anual_por_rotulo(pagina)
    assert list(por_rotulo)[:3] == ["OP. COMUM", "OP. DAYTRADE", "OP. F.I.I FIAGRO"]
    assert por_rotulo["IMPOSTOS"].count('class="neg"') == 13           # 12 meses + total, zeros incluidos
    assert por_rotulo["DESPESAS"].count('class="neg"') == 13
    assert por_rotulo["OP. COMUM"].count('class="neg"') == 0           # prejuizo em OP. COMUM fica azul-marinho
    assert "-R$ 2.310,60" in por_rotulo["OP. COMUM"]
    assert por_rotulo["SOMA DOS RESULTADOS"].startswith('<tr class="f">')    # filete em cima
    assert por_rotulo["LÍQUIDO MÊS"].startswith('<tr class="f b z">')        # filete, negrito e filete fino embaixo


def test_anual_marrom_pode_ser_forcado_e_none_vira_traco():
    d = dados_exemplo()
    d["anual"]["linhas"][0]["marrom"] = True
    d["anual"]["linhas"][1]["valores"][11] = None
    pg = [p for p in _paginas(REL.html_relatorio(d)) if "Resultados Anuais 2026" in p][0]
    linhas = re.findall(r"<tr[^>]*>.*?</tr>", pg, flags=re.S)
    assert linhas[1].count('class="neg"') == 13                         # 1a linha de corpo (0 e o cabecalho)
    assert linhas[2].count(">-</td>") == 1 and linhas[2].count("R$ ") == 12     # 11 meses e o total; DEZ virou "-"


# ------------------------------------------------------------------ situacao fiscal
def test_situacao_em_duas_colunas(pagina):
    pg = [p for p in _paginas(pagina) if "Situação Fiscal" in p][0]
    assert "left:17.46pt" in pg and "left:439.58pt" in pg              # tabelas na esquerda, alertas e conferencia na direita
    txt = _texto(pg)
    assert txt.index("DARFs") < txt.index("Prejuízos a Compensar") < txt.index("Alertas") < txt.index("Conferência")
    assert "A pagar" in txt and "R$ 650,11" in txt and "-R$ 103,40" in txt


def test_situacao_do_darf_so_fica_marrom_quando_e_problema():
    for txt in ("Vencido", "Em atraso", "em atraso há 3 dias", "sem pagamento no Safra", "Não pago", "Pendente"):
        assert REL._cor_situacao(txt) == "neg", txt
    for txt in ("Pago", "pago em 30/09/2026", "a pagar", "parcial, pode mudar até o fim do mês", "", None):
        assert REL._cor_situacao(txt) == "", txt


def test_situacao_listas_vazias_e_chaves_ausentes():
    d = dados_exemplo()
    d["situacao"] = {"darfs": [], "prejuizos": [], "alertas": [], "conferencia": []}
    txt = _texto(REL.html_relatorio(d))
    for frase in ("Nenhum DARF a pagar neste período.", "Sem prejuízo acumulado a compensar.",
                  "Nenhum alerta neste mês.", "Nenhuma conferência registrada."):
        assert frase in txt, frase
    d["situacao"] = {"darfs": []}
    txt = _texto(REL.html_relatorio(d))
    assert "Alertas" not in txt and "Conferência" not in txt and "DARFs" in txt


def test_situacao_longa_passa_para_a_pagina_seguinte_sem_perder_linha():
    d = dados_exemplo()
    d["situacao"]["darfs"] = [{"periodo": f"{i % 12 + 1:02d}/2026", "codigo": "6015", "vencimento": f"{i + 1:02d}/12/2026",
                               "valor": 100.0 + i, "situacao": "Vencido" if i % 4 == 0 else "Pago"} for i in range(30)]
    d["situacao"]["alertas"] = [f"Alerta numero {i + 1}: " + "frase longa de teste " * 12 for i in range(16)]
    pgs = [p for p in _paginas(REL.html_relatorio(d)) if "Período de apuração" in _texto(p)]
    assert len(pgs) >= 2
    assert sum(p.count(">6015<") for p in pgs) == 30
    assert sum(len(re.findall(r"Alerta numero \d+:", _texto(p))) for p in pgs) == 16     # nenhum alerta se perde
    assert all("Disclaimer:" in p for p in pgs)
    assert 'class="neg"' in pgs[0] and ">Vencido<" in pgs[0]            # DARF vencido em marrom
    for p in pgs:                                                       # as duas colunas terminam acima do rodape
        for topo in re.findall(r'class="a" style="left:[\d.]+pt;top:([\d.]+)pt"><table', p):
            assert float(topo) < REL.Y_FUNDO


# ------------------------------------------------------------------ codigo
def test_acentos_visiveis_e_comentarios_sem_acento():
    for modulo in (REL, DARF):
        fonte = Path(modulo.__file__).read_text(encoding="utf-8")
        for linha in fonte.splitlines():
            s = linha.strip()
            if s.startswith("#"):
                assert s.isascii(), s
            if "  # " in linha:                                  # comentario no fim da linha de codigo
                assert linha.split("  # ", 1)[1].isascii(), linha
    fonte = Path(REL.__file__).read_text(encoding="utf-8")
    assert "Relatório Mensal" in fonte and "Situação Fiscal" in fonte


def test_nada_copiado_do_modelo():
    # o gerador nao pode carregar nome, CPF, telefone nem e-mail do material de referencia
    for modulo in (REL, DARF):
        fonte = Path(modulo.__file__).read_text(encoding="utf-8")
        assert not re.search(r"\d{3}\.\d{3}\.\d{3}-\d{2}", fonte.replace("000.000.000-00", ""))
        assert not re.search(r"\d{11}", fonte)
        assert not re.search(r"\(\d{2}\)\s*\d{4,5}-\d{4}", fonte)
        assert "@" not in fonte.replace("@page", "")
        assert "http" not in fonte.lower() and ".com.br" not in fonte.lower()


# ------------------------------------------------------------------ DARF
def test_darf_campos_e_textos(pagina_darf):
    txt = _texto(pagina_darf)
    for trecho in ["MINISTÉRIO DA FAZENDA", "SECRETARIA DA RECEITA FEDERAL DO BRASIL",
                   "Documento de Arrecadação de Receitas Federais", "DARF", "01 NOME / TELEFONE",
                   "02 PERÍODO DE APURAÇÃO", "03 NÚMERO DO CPF OU CNPJ", "04 CÓDIGO DA RECEITA",
                   "05 NÚMERO DE REFERÊNCIA", "06 DATA DE VENCIMENTO", "07 VALOR DO PRINCIPAL", "08 VALOR DA MULTA",
                   "09 VALOR DOS JUROS E/OU ENCARGOS DL 1.025/69", "10 VALOR TOTAL", "11 AUTENTICAÇÃO BANCÁRIA",
                   "REF. OPERAÇÕES EM BOLSA DE VALORES OUTUBRO de 2026", "DARF válido para pagamento até 30/11/2026",
                   "Domicílio tributário do contribuinte", "NÃO RECEBER COM RASURAS", "Aprovado pela IN/RFB nº 736/2007",
                   "FULANO DE TAL", "000.000.000-00", "31/10/2026", "6015", "30/11/2026", "650,11", "1ª Via", "2ª Via",
                   "cortar nesta linha"]:
        assert trecho.lower() in txt.lower(), trecho
    assert txt.lower().count("documento de arrecadação") >= 2        # duas vias iguais
    assert pagina_darf.count('class="via"') == 2
    assert "código de barras" in txt.lower()                          # aviso: impresso sem codigo de barras
    assert "<svg" in pagina_darf and "@page { size: A4 portrait" in pagina_darf


def test_darf_as_duas_vias_sao_iguais(pagina_darf):
    vias = re.findall(r'<div class="via">(.*?)</div><svg', pagina_darf, flags=re.S)
    assert len(vias) == 2
    a, b = (_texto(v).replace("1ª Via", "").replace("2ª Via", "") for v in vias)
    assert a == b and "650,11" in a


def test_darf_valores_zerados_domicilio_e_observacao():
    c = darf_exemplo()
    c.update({"multa": 6.5, "juros": 1.25, "total": 657.86, "observacao": "Pagar pelo app do banco.",
              "domicilio": "CIDADE - UF", "telefone": "(00) 0000-0000"})
    t = _texto(DARF.html_darf(c))
    assert "6,50" in t and "1,25" in t and "657,86" in t and "Pagar pelo app do banco." in t
    assert "CIDADE - UF" in t and "FULANO DE TAL / (00) 0000-0000" in t
    c.update({"multa": None, "juros": None, "total": None})
    t = _texto(DARF.html_darf(c))
    assert t.count("R$ 0,00") >= 4                                      # multa e juros zerados nas duas vias
    assert "R$ 650,11" in t                                             # sem total, ele e a soma dos tres valores
    c["observacao"] = ""
    assert "Pagar pelo app" not in _texto(DARF.html_darf(c))


# ------------------------------------------------------------------ PDF (precisa do Chrome)
precisa_chrome = pytest.mark.skipif(not CHROME.exists(), reason="Chrome nao instalado")


def _itens_pdf(leitor):
    """[(pagina, y_do_topo, x, texto)] de todos os trechos de texto do PDF."""
    out = []
    for i, pag in enumerate(leitor.pages):
        alt = float(pag.mediabox.height)

        def vis(texto, cm, tm, fd, fs, i=i, alt=alt):
            if texto.strip():
                x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
                y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
                out.append((i, alt - y, x, texto.strip()))

        pag.extract_text(visitor_text=vis)
    return out


@precisa_chrome
def test_pdf_do_relatorio_tem_uma_pagina_por_secao(tmp_path):
    from pypdf import PdfReader

    d = dados_exemplo()
    alvo = tmp_path / "rel.pdf"
    out = REL.pdf_relatorio(d, alvo)
    assert out == alvo and alvo.exists() and alvo.stat().st_size > 10_000
    assert [p.name for p in tmp_path.iterdir()] == ["rel.pdf"]       # HTML e perfil do Chrome ficam fora
    n_html = len(_paginas(REL.html_relatorio(d)))
    leitor = PdfReader(str(alvo))
    assert len(leitor.pages) == n_html >= 10
    larg, alt = float(leitor.pages[0].mediabox.width), float(leitor.pages[0].mediabox.height)
    assert math.isclose(larg, 841.89, abs_tol=1.0) and math.isclose(alt, 595.28, abs_tol=1.0)     # A4 paisagem
    texto = " ".join((p.extract_text() or "") for p in leitor.pages)
    assert "Relatório Mensal" in texto and "FULANO DE TAL" in texto
    assert "Bonificações em ações" in texto                          # sem ligadura "fi" no texto extraido
    assert "Resultados Anuais 2026" in texto and "Situação Fiscal" in texto


@precisa_chrome
def test_pdf_tabela_longa_fica_dentro_da_pagina_e_sem_linha_perdida(tmp_path):
    from pypdf import PdfReader

    n = 60
    alvo = tmp_path / "longa.pdf"
    REL.pdf_relatorio(_dados_com_grupo_longo(n), alvo)
    itens = _itens_pdf(PdfReader(str(alvo)))
    por_pagina = {}
    for pg, y, x, t in itens:
        if re.fullmatch(r"TST\d{3}", t):
            por_pagina.setdefault(pg, []).append((y, t))
    tickers = [t for lst in por_pagina.values() for _, t in lst]
    assert sorted(tickers) == [f"TST{i:03d}" for i in range(n)]       # nenhuma linha perdida nem repetida
    assert len(por_pagina) >= 3
    for pg, lst in por_pagina.items():
        assert max(y for y, _ in lst) < REL.Y_FUNDO                  # a ultima linha acaba acima do rodape
        assert any(i[0] == pg and i[3] == "Total c/ Taxas" for i in itens)
    # nada de corpo entre o fim do conteudo e o filete do aviso (so o aviso ocupa essa faixa)
    for pg, y, x, t in itens:
        if pg > 0:
            assert not (REL.Y_FUNDO + 2 < y < 553.0), (pg, y, t)


@precisa_chrome
def test_pdf_mes_sem_movimento_tem_uma_pagina_por_secao(tmp_path):
    from pypdf import PdfReader

    d = dados_mes_sem_movimento()
    alvo = tmp_path / "vazio.pdf"
    REL.pdf_relatorio(d, alvo)
    leitor = PdfReader(str(alvo))
    assert len(leitor.pages) == len(_paginas(REL.html_relatorio(d))) == 8
    assert "Sem posição em carteira nesta data" in (leitor.pages[1].extract_text() or "")


@precisa_chrome
def test_pdf_alerta_longo_sai_inteiro_sem_reticencias(tmp_path):
    from pypdf import PdfReader

    d = dados_exemplo()
    d["situacao"]["alertas"] = [
        "A CONFERIR: " + " ".join(f"palavra{i:03d}" for i in range(70)) + " FIMDOALERTA",     # ~7 linhas de 7 pt
        "Alerta curto depois do longo."]
    alvo = tmp_path / "alerta.pdf"
    REL.pdf_relatorio(d, alvo)
    leitor = PdfReader(str(alvo))
    pg = [p for p in leitor.pages if "Situação Fiscal" in (p.extract_text() or "")][0]
    texto = re.sub(r"\s+", " ", pg.extract_text() or "")
    assert "palavra000" in texto and "palavra069" in texto and "FIMDOALERTA" in texto
    assert "…" not in texto and "..." not in texto                       # nada cortado com reticencias
    assert "Alerta curto depois do longo." in texto


@precisa_chrome
def test_pdf_com_senha_cifra_e_abre_com_a_senha(tmp_path):
    from pypdf import PdfReader

    alvo = tmp_path / "rel_senha.pdf"
    REL.pdf_relatorio(dados_exemplo(), alvo, senha="000000")
    leitor = PdfReader(str(alvo))
    assert leitor.is_encrypted
    assert leitor.decrypt("000000") != 0
    assert len(leitor.pages) >= 10
    assert "Relatório Mensal" in (leitor.pages[0].extract_text() or "")
    errado = PdfReader(str(alvo))
    assert errado.decrypt("123456") == 0


def test_pdf_do_darf_e_uma_pagina_retrato_e_leve(tmp_path):
    from pypdf import PdfReader

    alvo = tmp_path / "darf.pdf"
    out = DARF.pdf_darf(darf_exemplo(), alvo)
    assert out == alvo and 3_000 < alvo.stat().st_size < 15_000      # vai anexo no e-mail, escrito dentro da chamada
    assert [p.name for p in tmp_path.iterdir()] == ["darf.pdf"]
    leitor = PdfReader(str(alvo))
    assert len(leitor.pages) == 1 and len(leitor.pages[0].images) == 1    # o brasao das duas vias entra uma vez
    assert float(leitor.pages[0].mediabox.height) > float(leitor.pages[0].mediabox.width)
    texto = leitor.pages[0].extract_text() or ""
    assert "DARF" in texto and "650,11" in texto and texto.count("MINISTÉRIO DA FAZENDA") == 2
    assert texto.count("AUTENTICAÇÃO BANCÁRIA") == 2 and "1ª Via" in texto and "2ª Via" in texto
    cifrado = tmp_path / "darf_senha.pdf"
    DARF.pdf_darf(darf_exemplo(), cifrado, senha="000000")
    r2 = PdfReader(str(cifrado))
    assert r2.is_encrypted and r2.decrypt("000000") != 0 and len(r2.pages) == 1


def test_pdf_do_darf_valor_alinhado_a_direita_nas_duas_vias(tmp_path):
    from pypdf import PdfReader

    alvo = DARF.pdf_darf(darf_exemplo(), tmp_path / "darf.pdf")
    itens = [i for i in _itens_pdf(PdfReader(str(alvo))) if i[3] == "R$ 650,11"]
    assert len(itens) == 4                                           # principal e total, nas duas vias
    tops = sorted(round(i[1], 1) for i in itens)
    assert math.isclose(tops[2] - tops[0], DARF.VIA_DY, abs_tol=0.2)
    larg = REL._larg("R$ 650,11", 9, False)
    assert all(math.isclose(i[2] + larg, 552.9, abs_tol=0.2) for i in itens)


def test_sem_chrome_o_relatorio_da_erro_claro_e_o_darf_sai_igual(tmp_path, monkeypatch):
    monkeypatch.setattr(REL, "CHROME", tmp_path / "nao-existe")
    with pytest.raises(FileNotFoundError, match="Chrome"):
        REL.pdf_relatorio(dados_exemplo(), tmp_path / "x.pdf")
    assert DARF.pdf_darf(darf_exemplo(), tmp_path / "y.pdf").stat().st_size > 3_000    # o DARF nao usa o Chrome
