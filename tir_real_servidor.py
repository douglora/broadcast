#!/usr/bin/env python3
"""
TIR Real — modelo DDM prospectivo para acoes brasileiras.

Os quatro dicionarios abaixo sao a base editavel do modelo. Eles seguem os
nomes usados pelo fluxo de atualizacao por research (FORWARD_EPS_SAFRA,
PAYOUT_HISTORICO, PL_MEDIO_HISTORICO, SAFRA_ANALISE), entao podem ser
atualizados direto quando sair relatorio novo.

Metodo: projeta o lucro por acao, distribui pelo payout historico, calcula o
valor terminal por P/L medio e resolve a taxa que iguala tudo ao preco de tela.
A TIR real desconta a inflacao (IPCA 12m) da TIR nominal por Fisher.
"""

# LPA projetado (R$/acao) — 2025E e 2026E
FORWARD_EPS_SAFRA = {
    "PETR4": {"2025": 9.10,  "2026": 8.60},
    "VALE3": {"2025": 8.40,  "2026": 8.90},
    "ITUB4": {"2025": 4.15,  "2026": 4.60},
    "BBDC4": {"2025": 2.35,  "2026": 2.75},
    "BBAS3": {"2025": 8.90,  "2026": 9.30},
    "ABEV3": {"2025": 1.02,  "2026": 1.12},
    "WEGE3": {"2025": 1.58,  "2026": 1.80},
    "B3SA3": {"2025": 1.05,  "2026": 1.15},
    "BPAC11": {"2025": 4.20, "2026": 4.80},
    "ITSA4": {"2025": 1.45,  "2026": 1.60},
    "PRIO3": {"2025": 5.60,  "2026": 6.40},
    "SUZB3": {"2025": 4.10,  "2026": 4.80},
    "RENT3": {"2025": 2.20,  "2026": 2.90},
    "EQTL3": {"2025": 2.60,  "2026": 3.00},
    "RADL3": {"2025": 1.05,  "2026": 1.25},
    "TOTS3": {"2025": 1.30,  "2026": 1.55},
    "SBSP3": {"2025": 5.40,  "2026": 6.10},
    "VIVT3": {"2025": 2.90,  "2026": 3.30},
    "GGBR4": {"2025": 2.10,  "2026": 2.45},
    "CSNA3": {"2025": 0.90,  "2026": 1.40},
    "KLBN11": {"2025": 1.30, "2026": 1.55},
    "UGPA3": {"2025": 1.85,  "2026": 2.10},
    "VBBR3": {"2025": 2.40,  "2026": 2.70},
    "CSAN3": {"2025": 1.10,  "2026": 1.60},
    "ELET3": {"2025": 3.20,  "2026": 3.80},
    "TAEE11": {"2025": 3.10, "2026": 3.30},
}

# Payout historico (% do lucro distribuido)
PAYOUT_HISTORICO = {
    "PETR4": 45, "VALE3": 60, "ITUB4": 60, "BBDC4": 50, "BBAS3": 45,
    "ABEV3": 85, "WEGE3": 55, "B3SA3": 75, "BPAC11": 35, "ITSA4": 85,
    "PRIO3": 0,  "SUZB3": 25, "RENT3": 25, "EQTL3": 30, "RADL3": 30,
    "TOTS3": 45, "SBSP3": 30, "VIVT3": 75, "GGBR4": 40, "CSNA3": 30,
    "KLBN11": 45, "UGPA3": 45, "VBBR3": 45, "CSAN3": 30, "ELET3": 30,
    "TAEE11": 90,
}

# P/L medio historico — usado como multiplo terminal
PL_MEDIO_HISTORICO = {
    "PETR4": 6.0,  "VALE3": 6.5,  "ITUB4": 9.5,  "BBDC4": 9.0,  "BBAS3": 6.0,
    "ABEV3": 16.0, "WEGE3": 30.0, "B3SA3": 15.0, "BPAC11": 12.0, "ITSA4": 8.5,
    "PRIO3": 8.0,  "SUZB3": 9.0,  "RENT3": 18.0, "EQTL3": 13.0, "RADL3": 28.0,
    "TOTS3": 28.0, "SBSP3": 12.0, "VIVT3": 15.0, "GGBR4": 8.0,  "CSNA3": 8.0,
    "KLBN11": 12.0, "UGPA3": 12.0, "VBBR3": 9.0, "CSAN3": 10.0, "ELET3": 11.0,
    "TAEE11": 11.0,
}

# Leitura do analista — rating, TIR real alvo e nota qualitativa
SAFRA_ANALISE = {
    "PETR4": {"rating": "COMPRA",  "tir_alvo": 15.0, "nota": "Fluxo de caixa forte e dividendo elevado; risco de interferencia em precos."},
    "VALE3": {"rating": "COMPRA",  "tir_alvo": 14.0, "nota": "Valuation descontado; sensivel ao minerio de ferro e a demanda chinesa."},
    "ITUB4": {"rating": "COMPRA",  "tir_alvo": 12.0, "nota": "ROE consistente acima de 20% com inadimplencia controlada."},
    "BBDC4": {"rating": "NEUTRO",  "tir_alvo": 11.0, "nota": "Recuperacao de rentabilidade em curso, ainda abaixo dos pares."},
    "BBAS3": {"rating": "COMPRA",  "tir_alvo": 16.0, "nota": "Multiplo baixo e payout alto; atencao a carteira do agro."},
    "ABEV3": {"rating": "NEUTRO",  "tir_alvo": 9.0,  "nota": "Geracao de caixa solida, crescimento de volume limitado."},
    "WEGE3": {"rating": "NEUTRO",  "tir_alvo": 8.0,  "nota": "Qualidade reconhecida, mas multiplo nao deixa margem de seguranca."},
    "B3SA3": {"rating": "NEUTRO",  "tir_alvo": 10.0, "nota": "Volume negociado ainda fraco; competicao no radar."},
    "BPAC11": {"rating": "COMPRA", "tir_alvo": 13.0, "nota": "Crescimento de receita acima do setor."},
    "ITSA4": {"rating": "COMPRA",  "tir_alvo": 12.5, "nota": "Desconto de holding acima da media historica."},
    "PRIO3": {"rating": "COMPRA",  "tir_alvo": 17.0, "nota": "Custo de extracao baixo; execucao em Wahoo e o principal gatilho."},
    "SUZB3": {"rating": "NEUTRO",  "tir_alvo": 11.0, "nota": "Ciclo de celulose pressionado, alavancagem em queda."},
    "RENT3": {"rating": "COMPRA",  "tir_alvo": 14.0, "nota": "Repactuacao de tarifas e juros menores ajudam o retorno."},
    "EQTL3": {"rating": "COMPRA",  "tir_alvo": 12.0, "nota": "Base regulatoria crescente com boa execucao em distribuicao."},
    "SBSP3": {"rating": "COMPRA",  "tir_alvo": 13.0, "nota": "Privatizacao destrava eficiencia; risco regulatorio residual."},
    "TAEE11": {"rating": "NEUTRO", "tir_alvo": 9.5,  "nota": "Dividendo previsivel, crescimento organico limitado."},
}

HORIZONTE_ANOS = 5
CRESCIMENTO_MAX = 0.15
CRESCIMENTO_MIN = -0.05


def _npv(rate, fluxos, preco):
    """Valor presente dos fluxos menos o preco pago."""
    total = -preco
    for t, cf in fluxos:
        total += cf / ((1.0 + rate) ** t)
    return total


def _irr(fluxos, preco, lo=-0.90, hi=1.50, tol=1e-7):
    """Bisseccao — estavel para fluxos com uma unica troca de sinal."""
    f_lo = _npv(lo, fluxos, preco)
    f_hi = _npv(hi, fluxos, preco)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = _npv(mid, fluxos, preco)
        if abs(f_mid) < tol:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def calcular_tir(ticker, preco, ipca=4.5):
    """
    Devolve o dicionario de TIR para um ticker, ou {'error': ...} se faltar
    dado de entrada. 'preco' e a cotacao de tela; 'ipca' e a inflacao 12m.
    """
    tk = (ticker or "").upper().replace(".SA", "")
    eps = FORWARD_EPS_SAFRA.get(tk)
    if not eps:
        return {"error": f"Sem projecao de LPA para {tk}"}
    if not preco or preco <= 0:
        return {"error": f"Sem preco de tela para {tk}"}

    eps_2025 = float(eps["2025"])
    eps_2026 = float(eps["2026"])
    payout = float(PAYOUT_HISTORICO.get(tk, 40)) / 100.0
    pl_terminal = float(PL_MEDIO_HISTORICO.get(tk, 10.0))

    # Crescimento implicito entre 2025E e 2026E, com trava para nao extrapolar
    if eps_2025 > 0:
        g = (eps_2026 / eps_2025) - 1.0
    else:
        g = 0.0
    g = max(CRESCIMENTO_MIN, min(CRESCIMENTO_MAX, g))

    fluxos = []
    eps_t = eps_2026
    for ano in range(1, HORIZONTE_ANOS + 1):
        if ano > 1:
            eps_t *= (1.0 + g)
        div = eps_t * payout
        cf = div
        if ano == HORIZONTE_ANOS:
            cf += pl_terminal * eps_t * (1.0 + g)   # valor terminal
        fluxos.append((ano, cf))

    r = _irr(fluxos, float(preco))
    if r is None:
        return {"error": f"TIR nao convergiu para {tk}"}

    tir_nominal = r * 100.0
    tir_real = ((1.0 + r) / (1.0 + float(ipca) / 100.0) - 1.0) * 100.0

    out = {
        "ticker": tk,
        "tir_real": round(tir_real, 2),
        "tir_nominal": round(tir_nominal, 2),
        "eps_2025": round(eps_2025, 2),
        "eps_2026": round(eps_2026, 2),
        "payout": round(payout * 100, 1),
        "pl_terminal": round(pl_terminal, 2),
        "preco_usado": round(float(preco), 2),
        "crescimento_aa": round(g * 100, 2),
        "ipca_usado": round(float(ipca), 2),
    }
    if tk in SAFRA_ANALISE:
        out["analise"] = SAFRA_ANALISE[tk]
    return out


def tickers_cobertos():
    return sorted(FORWARD_EPS_SAFRA.keys())
