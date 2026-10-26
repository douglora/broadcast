"""Da carteira de hoje a carteira alvo, e do alvo ao longo do tempo.

Tres entregas: (1) o plano de transicao em fases (o que mexer primeiro, em quantas parcelas); (2) a regra de
acompanhamento (bandas de rebalanceamento e gatilhos de revisao); (3) a trilha ao longo dos anos, com a esteira
de liquidez para retiradas grandes. Palavras: "aumentar" e "reduzir", nunca "compre/venda" (CVM 178: a
recomendacao e do assessor).
"""

from __future__ import annotations

import numpy as np

from . import config as C

RV_ENTRADA = ("rv_br", "rv_int", "fii", "cripto", "alt_ouro")
TRAVA_TAXA = ("ipca_isenta", "ipca_trib", "pre_isenta", "pre_trib")


def faixa_rebalanceamento(alvo: float) -> float:
    """Meia-largura (fracao) da banda de rebalanceamento: 20% do peso alvo, entre 1,5 e 5 pontos."""
    return float(min(max(0.20 * alvo, 0.015), 0.05))


def transicao(alvo: np.ndarray, atual: np.ndarray | None, pl: float, em_choque: bool = False,
              minimo_pp: float = 0.01) -> dict:
    """Passos para sair de `atual` e chegar em `alvo`. Sem carteira atual, o dinheiro novo entra do caixa."""
    sem_atual = atual is None
    if sem_atual:
        atual = np.zeros(len(alvo))
        atual[C.IDS.index("caixa")] = 1.0
    delta = alvo - atual
    passos = []
    for i, cid in enumerate(C.IDS):
        d = float(delta[i])
        if abs(d) < minimo_pp or (sem_atual and cid == "caixa"):    # sem carteira atual, o caixa e de onde sai o dinheiro novo
            continue
        reais = abs(d) * pl
        cls = C.POR_ID[cid]
        if d < 0:
            fase, janela, parcelas = 1, "primeiras 2 semanas", 1
            nota = "Antes de reduzir, conferir imposto a pagar (ganho latente, come-cotas) e carências/vencimentos; usar aportes e vencimentos antes de resgatar."
            if cid in ("caixa", "pos_trib"):
                fase, nota = 3, "Excesso de caixa vai sendo realocado conforme as parcelas das outras classes."
        else:
            if cid in TRAVA_TAXA:
                fase = 1
                janela = "semanas 1 a 6" if not em_choque else "semanas 2 a 8"
                parcelas = 3 if abs(d) >= 0.03 else 1
                nota = "Entrar em parcelas para não depender de um dia só de taxa" + ("; em dia de choque, esperar as taxas do balcão." if em_choque else ".")
            elif cid in RV_ENTRADA:
                fase = 2
                parcelas = 4 if abs(d) >= 0.04 else 3 if abs(d) >= 0.02 else 1
                janela = f"meses 1 a {parcelas}" if parcelas > 1 else "mês 1"
                nota = "Entrada escalonada (mensal) para reduzir o risco de comprar no pior dia; acelerar se o preço cair e o cenário não mudar."
            elif cid in ("mm", "vgbl"):
                fase, janela, parcelas = 3, "meses 2 a 6", 2
                nota = "Escolher gestor/plano com cuidado (a dispersão entre gestores é maior que entre classes); previdência: conferir taxa de carregamento e tabela."
            else:
                fase, janela, parcelas = 1, "primeiras 2 semanas", 1
                nota = "Liquidez e renda fixa pós entram logo; escolher emissores diversificados (FGC de R$ 250 mil por CPF e banco)."
        passos.append({"fase": fase, "janela": janela, "classe": cid, "curto": cls.curto,
                       "acao": "aumentar" if d > 0 else "reduzir", "pp": d * 100.0, "reais": reais,
                       "parcelas": parcelas, "por_parcela": reais / parcelas, "nota": nota})
    passos.sort(key=lambda p: (p["fase"], -abs(p["pp"])))
    giro = float(1.0 - alvo[C.IDS.index("caixa")]) if sem_atual else float(np.abs(delta).sum() / 2.0)
    return {"passos": passos, "giro": giro, "delta": delta}


def regras_acompanhamento(alvo: np.ndarray, cenario_choque_bps: float = 150.0) -> dict:
    bandas = []
    for i, cid in enumerate(C.IDS):
        if alvo[i] <= 0:
            continue
        m = faixa_rebalanceamento(float(alvo[i]))
        bandas.append({"classe": cid, "curto": C.POR_ID[cid].curto, "alvo": float(alvo[i]),
                       "min": max(float(alvo[i]) - m, 0.0), "max": float(alvo[i]) + m})
    gatilhos = [
        "Revisão semestral e a cada aniversário do plano.",
        "Qualquer classe fora da própria faixa de rebalanceamento: voltar ao alvo usando primeiro aportes e vencimentos, depois resgates.",
        f"Choque de juros de ±{cenario_choque_bps:.0f} pontos-base na curva de 3 anos, ou mudança do rating/cenário fiscal: revisão extraordinária das premissas.",
        "Mudança na vida do cliente (herança, venda de empresa, filho no exterior, aposentadoria): refazer a ficha e a proposta.",
        "Emissor de crédito com queda de rating ou notícia negativa: reavaliar a posição específica, sem esperar a revisão.",
    ]
    return {"bandas": bandas, "gatilhos": gatilhos}


def esteira_de_liquidez(eventos: list, pl: float, ipca: float) -> list[dict]:
    """Para cada retirada grande, onde o dinheiro tem de estar a cada marco antes da data."""
    out = []
    for e in eventos or []:
        v = float(e.get("valor", 0.0))
        t = int(e.get("mes", 0))
        if v >= 0 or t <= 0:
            continue
        valor = -v * (1.0 + ipca) ** (t / 12.0)
        marcos = []
        if t > 24:
            marcos.append({"quando": f"mês {t-24}", "onde": "começar a separar em RF isenta pós ou IPCA+ com vencimento até a data", "pct": 0.5})
        if t > 12:
            marcos.append({"quando": f"mês {t-12}", "onde": "100% em caixa/pós-fixado com vencimento até a data", "pct": 1.0})
        marcos.append({"quando": f"mês {t}", "onde": "disponível na data", "pct": 1.0})
        out.append({"mes": t, "descricao": e.get("desc") or e.get("descricao") or "retirada", "valor_hoje": -v,
                    "valor_futuro": valor, "marcos": marcos})
    return out


def trilha(alvo: np.ndarray, plano_pl: float, aporte_mensal: float, ret: float, anos: int, ipca: float,
           eventos: list | None = None) -> dict:
    """Composicao esperada ano a ano: alvo mantido, com a reserva de cada retirada grande segurando caixa
    no ano anterior a data. Riqueza pelo caminho esperado (retorno liquido da carteira)."""
    anos = max(int(anos), 1)
    comp = np.zeros((anos + 1, len(alvo)))
    riqueza = np.zeros(anos + 1)
    riqueza[0] = plano_pl
    caixa_i = C.IDS.index("caixa")
    ev = [(int(e.get("mes", 0)), -float(e["valor"])) for e in (eventos or []) if float(e.get("valor", 0)) < 0]
    for y in range(anos + 1):
        if y > 0:
            riqueza[y] = riqueza[y - 1] * (1.0 + ret) + aporte_mensal * 12.0 * (1.0 + ipca) ** (y - 0.5)
            for t, v in ev:
                if t == y * 12:
                    riqueza[y] -= v * (1.0 + ipca) ** y
        reserva = sum(v * (1.0 + ipca) ** (t / 12.0) for t, v in ev if y * 12 < t <= (y + 1) * 12 + 12)
        frac = min(reserva / riqueza[y], 0.8) if riqueza[y] > 0 else 0.0
        w = alvo * (1.0 - frac)
        w[caixa_i] += frac
        comp[y] = w
    return {"anos": list(range(anos + 1)), "composicao": comp, "riqueza": riqueza}
