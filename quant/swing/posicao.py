"""
Regras de uma posicao de swing, sem I/O: validacao do prazo e a decisao de saida ao vivo.

A posicao e um dict (ver `estado.nova_posicao`) com: setup, ticker, entrada_em, preco_entrada, stop, alvo, prazo, prazo_ate, qtd, porque.
Aqui ficam as duas coisas que nao podem sair erradas e que os testes cobrem: o prazo nunca passa de 10 pregoes e a ordem em que stop, alvo e
tempo valem.

SAIDA AO VIVO (simulacao, nenhuma ordem vai a corretora):
  - STOP e ordem a mercado simulada. Se a abertura do dia ja esta abaixo do stop (gap contra), a saida e na abertura, PIOR que o stop
    (a perda passa do risco planejado: e o risco de swing e a tela diz isso). Sem gap, sai no ultimo preco visto, que pode ficar um pouco
    abaixo do stop.
  - ALVO e ordem limitada: sai no preco do alvo; se o papel abre acima dele, sai na abertura.
  - TEMPO: no ultimo pregao do prazo (o 10o no maximo, contando o dia da entrada como 1o), a saida e no leilao de fechamento, simulada no
    ultimo preco visto a partir de `HORA_TEMPO`. Posicao que passou do prazo (robo desligado no dia) sai assim que for vista.
  - No dia da entrada so o stop e o alvo valem (nao ha "gap" no dia em que se entrou): igual a pesquisa.
"""
import pandas as pd

PRAZO_MAX = 10
HORA_TEMPO = "16:50"


def _d(x):
    return pd.Timestamp(x).date()


def validar(prazo, stop_dist, alvo_dist=None):
    """Levanta ValueError se a operacao viola o desenho: prazo de 1 a 10 pregoes, stop acima de zero, alvo (se houver) acima de zero."""
    if not (1 <= int(prazo) <= PRAZO_MAX):
        raise ValueError(f"prazo de {prazo} pregões: swing curto é de 1 a {PRAZO_MAX}")
    if not (stop_dist and float(stop_dist) > 0):
        raise ValueError("swing sem stop não existe: a distância do stop tem de ser maior que zero")
    if alvo_dist is not None and float(alvo_dist) <= 0:
        raise ValueError("a distância do alvo, quando há alvo, tem de ser maior que zero")
    return True


def decidir_saida(pos, ultimo, abertura, hoje, hm, sair_em=None, hora_evento=None):
    """(preco, motivo) se a posicao deve sair agora, ou None. `hm`: 'HH:MM' do relogio de Brasilia. Ordem: gap, stop, alvo, evento, tempo.
    `sair_em` (AAAA-MM-DD, decisao escrita do Douglas em swing_config.json): nesse dia, a partir de `hora_evento` (HH:MM; padrao o
    leilao de fechamento, `HORA_TEMPO`), a posicao sai no ultimo preco, antes de um evento binario (eleicao); se o robo so acordar
    depois, sai no primeiro preco (21/10/2026). No Mac que desliga as 13h a hora vem da configuracao (12:40)."""
    h = _d(hoje)
    primeiro_dia = h == _d(pos["entrada_em"])
    stop, alvo = float(pos["stop"]), pos.get("alvo")
    alvo = None if alvo is None else float(alvo)
    if abertura and abertura > 0 and not primeiro_dia:
        if abertura <= stop:
            return float(abertura), "gap_stop"
        if alvo is not None and abertura >= alvo:
            return float(abertura), "gap_alvo"
    if ultimo is not None and ultimo > 0:
        if ultimo <= stop:
            return float(ultimo), "stop"
        if alvo is not None and ultimo >= alvo:
            return float(alvo), "alvo"
        if sair_em and _d(pos["entrada_em"]) <= _d(sair_em):          # posicao aberta depois do evento nao e alcancada pela chave
            dia_evento = _d(sair_em)
            if h > dia_evento or (h == dia_evento and hm >= (hora_evento or HORA_TEMPO)):
                return float(ultimo), "evento"
        limite = _d(pos["prazo_ate"])
        if h > limite or (h == limite and hm >= HORA_TEMPO):
            return float(ultimo), "tempo"
    return None


def escolher_saida_parcial(posicoes, precos, fracao):
    """Saida parcial antes de um evento binario (`sair_antes_de_fracao` < 1): (ids que saem, ids que ficam). Sai a fracao do
    FINANCEIRO do livro (e o financeiro que o salto de abertura atinge; o stop nao protege de salto), comecando pelas maiores
    posicoes, ate cobrir a fracao; o resto fica com stop, alvo e prazo normais. `precos`: ticker -> ultimo (sem preco, vale o de
    entrada). fracao >= 1 sai tudo; havendo posicoes, ao menos uma sai. Decisao do Douglas em 21/10/2026 ('2- Mecanismo')."""
    f = float(fracao)
    linhas = []
    for p in posicoes:
        preco = precos.get(p["ticker"]) or p.get("preco_entrada") or 0.0
        linhas.append((float(p.get("qtd") or 0) * float(preco), p["id"]))
    if not linhas:
        return [], []
    total = sum(v for v, _ in linhas)
    if f >= 1.0 or total <= 0:
        return [i for _, i in linhas], []
    linhas.sort(key=lambda x: (-x[0], x[1]))
    sair, acumulado = [], 0.0
    for v, i in linhas:
        if sair and acumulado >= f * total - 1e-9:
            break
        sair.append(i)
        acumulado += v
    manter = [i for _, i in linhas if i not in sair]
    return sair, manter
