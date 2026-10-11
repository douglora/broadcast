"""
Protecao da carteira em mini-indice, ao vivo (simulacao): quantos contratos vender e quando mexer.

POR QUE EXISTE. Em 08/10/2026 o robo vendeu 1 mini-indice as 10h20, no mesmo instante em que mandou comprar 22 acoes.
A venda do indice executou na hora; as compras eram ordens com limite e metade nao executou, porque o mercado abriu
subindo. As 11h26 havia R$ 32,7 mil de acoes compradas contra R$ 41,1 mil de indice vendido: o livro estava VENDIDO no
liquido num mercado que subia, e a perna de protecao perdia sozinha. O Douglas viu e cobrou: "quando o mercado virou ele
nao stopou a venda e comecou a ficar no negativo". O defeito era de tamanho, nao de stop: a protecao era "1 contrato ate
R$ 200 mil de patrimonio", sem olhar quanto de acao ja tinha sido comprado nem quanto vale 1 contrato hoje (com o indice
perto de 206 mil pontos, R$ 41 mil: 60% de um livro de R$ 68 mil).

AS REGRAS (valem para qualquer tamanho de carteira e qualquer nivel do indice):
  1. A venda de indice acompanha o que JA ESTA COMPRADO: alvo = RAZAO x valor das acoes carregadas agora.
  2. Contrato e inteiro, entao ha folga para nao ficar entrando e saindo: so passa de n para n+1 contratos quando a conta
     chega a n + 0,75; so volta de n para n-1 quando cai a n - 0,75.
  3. NUNCA vendido no liquido: o valor vendido em indice nao passa do valor das acoes carregadas. Se passar (acao vendida,
     queda forte das acoes), a protecao e reduzida na hora, sem esperar a folga.
  4. A protecao e carregada de um pregao para o outro pelo preco de referencia (como o ajuste diario de um futuro), e o
     resultado dela entra no patrimonio. Antes, ela nascia de novo todo dia e o resultado da noite se perdia.
  5. NAO ha stop de preco na protecao. Protecao perde quando a bolsa sobe, e e para isso que as acoes estao compradas. No
     teste de 2012 a 2015 o stop de 3 amplitudes medias custou R$ 3,5 mil na perna de indice e nao melhorou nada
     (quant/saida/pesquisa_carteira/RESULTADO.md). O que impede a protecao de "ficar sozinha no negativo" sao as regras 1 e 3.

Funcoes puras: quem guarda estado e o robo (quant/execucao/robo_vivo.py).
"""
import json
import math
import os

from quant import custos
from quant.comum import DIR_SAIDA

RAZAO = 0.5                                   # venda de indice = metade do valor das acoes carregadas
FOLGA = 0.75                                  # fracao de contrato que a conta precisa passar para mexer
VALOR_PONTO = custos.WIN_VALOR_PONTO          # R$ por ponto do mini-indice
CUSTO_LADO = custos.WIN_TARIFA_LADO + custos.WIN_TICK_PONTOS * custos.WIN_VALOR_PONTO   # tarifa + 1 tick contra, por contrato

# Decisoes do Douglas sobre a carteira ficam neste arquivo (fora do codigo): {"razao_protecao": 0.25, "motivo": "..."}.
ARQ_CONFIG = os.path.join(DIR_SAIDA, "carteira_config.json")


def razao(arq=None):
    """Fracao do valor das acoes que fica vendida em mini-indice. Padrao RAZAO; o Douglas muda em carteira_config.json
    (em 10/10/2026 ele pediu 1/4, depois de ver no teste longo que a protecao pesada custou retorno)."""
    try:
        with open(arq or ARQ_CONFIG, encoding="utf-8") as f:
            v = float((json.load(f) or {}).get("razao_protecao"))
        return v if 0.0 <= v <= 1.0 else RAZAO
    except (OSError, ValueError, TypeError):
        return RAZAO


def regra_na_tela(r=None):
    r = razao() if r is None else float(r)
    fracao = {0.5: "metade", 0.25: "um quarto", 1.0: "o total", 0.0: "nada"}.get(round(r, 4), f"{r * 100:.0f}%".replace(".", ","))
    return (f"A venda de mini-índice acompanha as ações já compradas: o alvo é {fracao} do valor delas, em contratos inteiros "
            "(só entra quando a conta chega a três quartos de um contrato), e o valor vendido nunca passa do valor das ações. "
            "Ela é carregada de um dia para o outro. Não tem stop de preço: é proteção, perde quando a bolsa sobe e as ações "
            "ganham; o que conta é a soma das duas.")


REGRA_NA_TELA = regra_na_tela(RAZAO)


def nocional(preco, contratos=1, valor_ponto=VALOR_PONTO):
    """Valor em reais de `contratos` mini-indices ao preco (pontos) dado."""
    return float(preco) * float(valor_ponto) * int(contratos)


def contratos_alvo(valor_acoes, preco, atual, razao=None, folga=FOLGA, permitido=True):
    """Quantos contratos de mini-indice devem ficar vendidos agora.

    `valor_acoes`: valor de mercado das acoes carregadas (R$). `preco`: mini-indice em pontos. `atual`: contratos vendidos
    agora. `permitido=False` (boleta do dia sem protecao): zera. Sem preco ou sem valor, nao mexe.
    """
    atual = max(0, int(atual or 0))
    if not permitido:
        return 0
    if preco is None or valor_acoes is None or not (float(preco) > 0):
        return atual
    valor = max(float(valor_acoes), 0.0)
    um = nocional(preco)
    r = globals()["razao"]() if razao is None else float(razao)
    x = r * valor / um                                # contratos "fracionarios" que a razao pede
    alvo = atual
    if x >= atual + folga:
        alvo = int(math.floor(x + (1.0 - folga) + 1e-9))
    elif x <= atual - folga:
        alvo = max(0, int(math.ceil(x - (1.0 - folga) - 1e-9)))
    return max(0, min(alvo, int(math.floor(valor / um + 1e-9))))      # regra 3: nunca vendido no liquido


def mover(h, alvo, preco, quando=None):
    """Leva a posicao `h` (dict do robo) de h['contratos'] para `alvo` ao `preco`. Devolve (delta, resultado_realizado)."""
    atual = int(h.get("contratos") or 0)
    alvo = max(0, int(alvo))
    d = alvo - atual
    if d == 0:
        return 0, 0.0
    realizado = 0.0
    if d > 0:                                          # vende mais: novo preco medio da venda
        base = float(h.get("preco_entrada") or 0.0) * atual
        h["preco_entrada"] = (base + float(preco) * d) / alvo
    else:                                              # recompra parte (ou tudo)
        realizado = (float(h.get("preco_entrada") or preco) - float(preco)) * VALOR_PONTO * (-d)
        h["realizado"] = float(h.get("realizado") or 0.0) + realizado
        if alvo == 0:
            h["preco_entrada"] = None
    h["custos"] = float(h.get("custos") or 0.0) + abs(d) * CUSTO_LADO
    h["contratos"] = alvo
    if quando is not None:
        h["hora"] = quando
    return d, realizado


def marcar(h, preco, valor_acoes=None):
    """Atualiza o resultado da posicao ao preco de agora. Tudo em reais; vendido ganha quando o indice cai."""
    n = int(h.get("contratos") or 0)
    h["preco_mercado"] = preco
    ent = h.get("preco_entrada")
    h["aberto"] = round((float(ent) - float(preco)) * VALOR_PONTO * n, 2) if (n and ent is not None and preco is not None) else 0.0
    h["resultado_hoje"] = round(float(h["aberto"]) + float(h.get("realizado") or 0.0) - float(h.get("custos") or 0.0), 2)
    if valor_acoes is not None:
        h["valor_acoes"] = round(float(valor_acoes), 2)
        # o que a razao pede em contratos, antes de arredondar: a tela usa para explicar por que ha (ou nao ha) venda
        h["alvo_fracionario"] = round(razao() * float(valor_acoes) / nocional(preco), 2) if (preco and float(preco) > 0) else None
        h["cobertura"] = (nocional(preco, n) / float(valor_acoes)) if (n and preco and float(valor_acoes) > 0) else (0.0 if not n else None)
    return h


def nova(caderno=None, hoje=None):
    """Posicao do dia a partir do que ficou do pregao anterior (`caderno`: o arquivo protecao.json). Contratos carregados
    entram pelo preco de referencia de ontem: o resultado de hoje comeca dali, com o salto da noite incluido."""
    c = caderno if isinstance(caderno, dict) else {}
    mesmo_dia = hoje is not None and str(c.get("dia")) == str(hoje)
    n = int(c.get("contratos") or 0)
    ref = c.get("preco_ref")
    if not ref:
        n = 0
    ate_ontem = float(c.get("ate_ontem") or 0.0) + (0.0 if mesmo_dia else float(c.get("hoje") or 0.0))
    ent = c.get("preco_entrada") if (mesmo_dia and c.get("preco_entrada")) else ref     # reinicio no mesmo dia: mantem a entrada
    return {"ativo": "WINFUT", "lado": "V", "contratos": n, "preco_entrada": (float(ent) if n else None),
            "hora": None, "carregado": bool(n), "preco_mercado": None, "aberto": 0.0,
            "realizado": float(c.get("realizado_hoje") or 0.0) if mesmo_dia else 0.0,
            "custos": float(c.get("custos_hoje") or 0.0) if mesmo_dia else 0.0,
            "resultado_hoje": 0.0, "ate_ontem": round(ate_ontem, 2), "multiplicador": VALOR_PONTO}


def caderno_de(h, hoje):
    """O que fica gravado para o pregao seguinte."""
    return {"dia": str(hoje), "contratos": int(h.get("contratos") or 0), "preco_ref": h.get("preco_mercado"),
            "ate_ontem": float(h.get("ate_ontem") or 0.0), "hoje": float(h.get("resultado_hoje") or 0.0),
            "realizado_hoje": float(h.get("realizado") or 0.0), "custos_hoje": float(h.get("custos") or 0.0),
            "preco_entrada": h.get("preco_entrada")}
