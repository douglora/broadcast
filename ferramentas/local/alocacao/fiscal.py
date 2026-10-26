"""Imposto por veiculo e mapa de blindagem do IRPFM.

As aliquotas sao as regras gerais vigentes que o Douglas usa nos relatorios (tabela
regressiva da renda fixa, come-cotas de 15% nos fundos de longo prazo, 15% de ganho de
capital em acoes, 20% nos FIIs, tabela regressiva da previdencia). O IRPFM (Lei 15.270/2025)
segue a leitura do relatorio do Tonial de abril/2026; vale conferir com o tributarista antes
de levar a numero ao cliente: o relatorio sempre diz isso na metodologia.
"""

from __future__ import annotations

from . import config as C

# Aliquota regressiva da renda fixa por prazo da aplicacao (dias corridos).
REGRESSIVA = [(180, 0.225), (360, 0.20), (720, 0.175), (10**9, 0.15)]
# Previdencia (tabela regressiva do plano): anos -> aliquota sobre o ganho.
PREVIDENCIA = [(2, 0.35), (4, 0.30), (6, 0.25), (8, 0.20), (10, 0.15), (10**9, 0.10)]

ALIQ_FUNDO_COTA = 0.15      # come-cotas (fundo de longo prazo); aproximacao anual do efeito
ALIQ_GANHO = 0.15           # acoes (swing), ETF, ouro e cripto; internacional pela Lei 14.754/2023
ALIQ_FII_GANHO = 0.20       # ganho de capital de FII; rendimento mensal e isento para PF
ALIQ_CAIXA = 0.175          # reserva de liquidez: resgates em prazos curtos e mistos (media de 17,5%)
DY_FII_PADRAO = 0.095       # parte do retorno do FII que sai como rendimento isento (quando nao ha dado)

TRIBUTOS = {"caixa", "isento", "regressivo", "fundo_cota", "previdencia", "ganho_15", "fii"}


def aliquota_regressiva(prazo_anos: float) -> float:
    dias = prazo_anos * 365.0
    for limite, aliq in REGRESSIVA:
        if dias <= limite:
            return aliq
    return 0.15


def aliquota_previdencia(prazo_anos: float) -> float:
    for limite, aliq in PREVIDENCIA:
        if prazo_anos <= limite:
            return aliq
    return 0.10


def liquido(ret_bruto: float, tributo: str, anos: float, dy_fii: float = DY_FII_PADRAO) -> float:
    """Retorno anualizado depois do imposto, supondo que a posicao e mantida `anos` anos e
    resgatada no fim (fundos: come-cotas anual). `ret_bruto` em fracao a.a."""
    anos = max(float(anos), 0.25)
    r = float(ret_bruto)
    if tributo == "isento":
        return r
    if tributo == "caixa":
        return r * (1.0 - ALIQ_CAIXA)
    if tributo == "fundo_cota":
        return r * (1.0 - ALIQ_FUNDO_COTA)
    if tributo == "fii":
        dy = min(dy_fii, max(r, 0.0))
        apreciacao = r - dy
        return dy + apreciacao * (1.0 - ALIQ_FII_GANHO) if apreciacao > 0 else r
    if tributo in ("regressivo", "previdencia", "ganho_15"):
        aliq = {"regressivo": aliquota_regressiva(anos), "previdencia": aliquota_previdencia(anos),
                "ganho_15": ALIQ_GANHO}[tributo]
        acumulado = (1.0 + r) ** anos - 1.0
        if acumulado <= 0:
            return r
        return (1.0 + acumulado * (1.0 - aliq)) ** (1.0 / anos) - 1.0
    raise ValueError(f"tributo desconhecido: {tributo}")


def aliquota_efetiva(ret_bruto: float, tributo: str, anos: float) -> float:
    """Quanto do retorno bruto o imposto come (0 a 1), para a tabela de eficiencia fiscal."""
    if ret_bruto <= 0:
        return 0.0
    return max(0.0, 1.0 - liquido(ret_bruto, tributo, anos) / ret_bruto)


def mapa_irpfm(pesos: dict[str, float]) -> dict:
    """Fatia da carteira por tipo de blindagem contra o IRPFM, pelo veiculo de cada classe:
    excluido da base (LCA, LCI, CRA, CRI, FI-Infra, incentivadas), diferido (previdencia),
    neutralizado (retencao de 15% absorve a aliquota maxima de 10%) e exposto (renda variavel,
    FIIs, exterior e cripto: ganho e rendimento entram na base)."""
    out = {"excluido": 0.0, "diferido": 0.0, "neutralizado": 0.0, "exposto": 0.0}
    for cid, w in pesos.items():
        out[C.POR_ID[cid].blindagem] += float(w)
    out["protegido"] = out["excluido"] + out["diferido"] + out["neutralizado"]
    return out
