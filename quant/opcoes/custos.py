"""
Custo real das opcoes na simulacao. Tres partes, todas contra o resultado:

 1. CRUZAR A OFERTA. Vender na melhor oferta de COMPRA e comprar na melhor oferta de VENDA que ficaram no livro no
    fechamento (COTAHIST: PREOFC/PREOFV). Nao ha preco intermediario nem "ultimo negocio" na execucao. A variante
    `exec="meio"` (ponto medio) existe so para medir quanto do resultado e spread.
 2. EMOLUMENTOS E LIQUIDACAO DA B3. PREMISSA, nao leitura da tabela: 0,05% do premio por lado. A tabela de acoes a vista
    da B3 esta em 0,030% (0,0225% acima de R$ 3 mi/mes); a pagina da tabela de opcoes deu erro 500 em 10/10/2026 e nao
    foi lida. 0,05% e uma margem acima do a vista; sobre premio de centavos o efeito e desprezivel perto do spread.
 3. EXERCICIO. Opcao exercida paga 0,03% (referencia a vista) sobre o valor do papel na compra E na revenda do papel
    recebido (a simulacao encerra o ciclo vendendo o papel no preco de liquidacao).

Corretagem: ZERO por premissa (varias corretoras zeram em opcoes; o custo fixo por ordem some sobre R$ 100 mil de caixa).
IMPOSTO NAO ENTRA: operacao comum em opcoes paga 15% sobre o ganho liquido (day trade 20%), sem a isencao de R$ 20 mil das
acoes. Todos os retornos deste modulo sao ANTES do imposto.
"""
FEE_PREMIO = 0.0005     # por lado, sobre o premio
FEE_EXERC = 0.0003      # sobre o valor do papel (exercicio e revenda)
NEG_MIN = 30            # negocios da serie no dia de entrada
SPREAD_MAX = 0.30       # (venda - compra) / ponto medio no fechamento
DELTA_TOL = 0.05        # tolerancia em torno do delta alvo


def premio_liquido_venda(bid, mid, exec="oferta"):
    base = bid if exec == "oferta" else mid
    return base * (1.0 - FEE_PREMIO)


def premio_liquido_compra(ask, mid, exec="oferta"):
    base = ask if exec == "oferta" else mid
    return base * (1.0 + FEE_PREMIO)


def taxa_exercicio(k_t, s_t):
    return FEE_EXERC * (k_t + s_t)
