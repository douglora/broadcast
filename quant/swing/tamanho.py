"""
Tamanho da operacao de swing: risco por operacao, teto por nome, numero maximo de posicoes e exposicao total.

POR QUE ESTES NUMEROS (pre-registro de 11/10/2026; o gestor de fundo pensa em risco, nao em valor):
  - RISCO 0,5% do capital do livro por operacao (R$ 300 em R$ 60 mil). Se o stop for atingido, perde-se 0,5%; 20 stops seguidos (impossivel com
    10 posicoes) custariam ~10%. E o padrao de mesas de risco de fundo (0,25% a 1%); 1% dobraria a oscilacao sem evidencia que a sustente.
  - TETO POR NOME 12% do capital: com stop de 2 ATR (~5% do preco) a conta do risco pede ~10% do capital; o teto 12% corta so papel de
    ATR muito pequeno, onde o gap noturno passa do stop com mais frequencia.
  - NO MAXIMO 10 POSICOES: com 10 posicoes de ~10% a exposicao chega a ~100% do capital da classe; mais que isso e alavancar ou fatiar abaixo do lote.
  - EXPOSICAO TOTAL <= capital da classe, que e `config_carteira.exposicao_acoes(hoje)` x patrimonio (60% x mao do dia): nunca alem disso.
  - LOTE de 100 ate R$ 30 e unidade acima (fracionario custa mais; `custos.custo_ordem` cobra).
O stop e o que define o tamanho: quantidade = risco em R$ / (distancia do stop em R$ por acao, em preco REAL). Em gap contra o stop a perda passa do risco planejado.
"""
CAPITAL = 60_000.0
RISCO = 0.005
TETO_NOME = 0.12
MAX_POSICOES = 10
EXPO_MAX = 1.0
LOTE = 100
PRECO_MAX_LOTE = 30.0


def quantidade(patrimonio, preco_real, dist_real, risco=RISCO, teto_nome=TETO_NOME, lote=None):
    """(quantidade, valor) pela regra do risco, limitada pelo teto por nome e arredondada para baixo em lote. (0, 0.0) se nao couber."""
    if not (patrimonio and patrimonio > 0 and preco_real and preco_real > 0 and dist_real and dist_real > 0):
        return 0, 0.0
    lote = lote or (LOTE if preco_real <= PRECO_MAX_LOTE else 1)
    qtd = int((risco * patrimonio) / dist_real // lote) * lote
    valor = min(qtd * preco_real, teto_nome * patrimonio)
    qtd = int(valor / preco_real // lote) * lote
    if qtd < lote:
        return 0, 0.0
    return int(qtd), float(qtd * preco_real)


def cabe(valor, valor_aberto, patrimonio, n_abertas, caixa=None, expo_max=EXPO_MAX, max_pos=MAX_POSICOES):
    """True se a nova posicao respeita numero maximo, exposicao bruta e (se informado) o caixa."""
    if n_abertas >= max_pos:
        return False
    if valor_aberto + valor > expo_max * patrimonio + 1e-9:
        return False
    if caixa is not None and valor > caixa:
        return False
    return True


def risco_rs(patrimonio, risco=RISCO):
    return float(risco) * float(patrimonio)
