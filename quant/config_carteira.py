"""
Decisoes do Douglas sobre a carteira de acoes, fora do codigo: `quant/saida/carteira_config.json`.

    {"razao_protecao": 0.25,                      fracao das acoes protegida em mini-indice (quant/execucao/protecao.py)
     "exposicao_acoes": 0.35,                     fracao do patrimonio em acoes (padrao: carteira.EXPOSICAO_ALVO, 0,70)
     "exposicao_ate": "2026-10-25",               opcional: ate esta data (inclusive) vale `exposicao_acoes`...
     "exposicao_depois": 0.70,                    ...e depois dela volta a este valor (padrao: EXPOSICAO_ALVO)
     "motivo": "..."}

A exposicao com data existe para a entrada escalonada antes de evento binario (por exemplo, metade da mao ate o 2o turno
de 25/10/2026 e o resto depois). Valor fora de 0 a 1, arquivo ausente ou ilegivel: vale o padrao do codigo.

ORDEM DE QUEM MANDA NA EXPOSICAO: (1) `exposicao_acoes` escrita aqui, que e uma ordem direta do Douglas; (2) o livro por
classes (`quant/saida/risco_livro.json`, quant/risco/livro.py): peso da classe de acoes x mao pela volatilidade; (3) o padrao
do codigo. Em 11/10/2026 ele mandou a carteira entrar cheia e ligou o livro por classes: vale o (2), 60% x a mao do dia.
"""
import json
import os

import pandas as pd

from quant.comum import DIR_SAIDA

ARQ = os.path.join(DIR_SAIDA, "carteira_config.json")


def ler(arq=None):
    try:
        with open(arq or ARQ, encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def _fracao(x, padrao):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return padrao
    return v if 0.0 <= v <= 1.0 else padrao


def exposicao_acoes(hoje=None, arq=None, padrao=None, arq_livro=None, arq_orcamento=None):
    """Fracao do patrimonio em acoes que vale em `hoje`. Devolve (valor, texto explicando de onde veio)."""
    if padrao is None:
        from quant import carteira as ct
        padrao = ct.EXPOSICAO_ALVO
    c = ler(arq)
    if "exposicao_acoes" not in c:
        from quant.risco import livro
        v, txt = livro.exposicao_acoes(hoje, arq_livro, arq_orcamento)
        if v is not None:
            return float(v), txt
        return float(padrao), "padrão da carteira"
    v = _fracao(c.get("exposicao_acoes"), padrao)
    ate = c.get("exposicao_ate")
    if ate:
        d = pd.Timestamp(hoje).date() if hoje is not None else pd.Timestamp.now().date()
        try:
            limite = pd.Timestamp(ate).date()
        except (ValueError, TypeError):
            limite = None
        if limite is not None and d > limite:
            depois = _fracao(c.get("exposicao_depois"), padrao)
            return float(depois), f"depois de {limite.strftime('%d/%m/%Y')}: {depois * 100:.0f}% (decisão do Douglas)"
        if limite is not None:
            return float(v), f"{v * 100:.0f}% até {limite.strftime('%d/%m/%Y')} (decisão do Douglas)"
    return float(v), f"{v * 100:.0f}% (decisão do Douglas)"
