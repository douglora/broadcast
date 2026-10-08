"""
Regra do robo de day trade (versao 0), sem rede e sem relogio: so contas.

O QUE ELA FAZ, EM PORTUGUES. Depois das 9h30, quando o preco rompe a maxima do dia formada
ate o minuto anterior E esta acima do preco medio do dia (o "VWAP" da sessao), compra; quando
rompe a minima do dia E esta abaixo do preco medio, vende. Cada operacao nasce com um stop
(a distancia vem do tamanho do vai-e-vem dos ultimos 15 minutos, com piso e teto) e um alvo de
duas vezes o risco. Andou um risco a favor, o stop sobe para o preco de entrada. Nenhuma
entrada depois das 16h30; as 17h20 tudo e zerado: nao dorme posicionado.

TRAVAS DO DIA. Perda de 1% do capital zera tudo e para ate amanha. Ganho de 1% (a meta que o
Douglas pediu) tambem zera e para: a meta e um teto para o dia, nao uma promessa.

O QUE ESTA REGRA NAO TEM: teste historico. E a versao 0, escolhida por ser simples de ler e
de conferir. O `backtest` com barras de 1 minuto vem antes de qualquer conversa sobre
dinheiro; ate la, o que a tela mostra e observacao, nao evidencia.

Tudo aqui e funcao pura: recebe o estado e um tique, devolve o estado novo e os eventos. O
robo (robo.py) cuida de rede, relogio e arquivo; o teste chama estas funcoes com numeros
escritos a mao.
"""
import math
from dataclasses import dataclass, field, asdict

# ── contratos ────────────────────────────────────────────────
# valor_ponto: reais por ponto, por contrato. tick: menor variacao de preco.
# custo: emolumentos + registro da B3 por contrato e por lado em day trade (ESTIMATIVA
# conservadora; conferir na nota de corretagem). Corretagem zero.
CONTRATOS = {
    "WINFUT": {"nome": "Mini-índice", "raiz": "WIN", "valor_ponto": 0.20, "tick": 5.0, "custo": 0.30,
               "risco_min": 150.0, "risco_max": 400.0},
    "WDOFUT": {"nome": "Mini-dólar", "raiz": "WDO", "valor_ponto": 10.0, "tick": 0.5, "custo": 1.20,
               "risco_min": 3.0, "risco_max": 8.0},
}


@dataclass
class Parametros:
    capital: float = 100_000.0
    risco_por_operacao: float = 0.0025      # 0,25% do capital por operacao
    perda_maxima_dia: float = 0.01          # 1% do capital: zera e para
    meta_dia: float = 0.01                  # 1% do capital: zera e para (meta do Douglas)
    alvo_em_riscos: float = 2.0             # alvo = 2 x o risco
    protege_em_riscos: float = 1.0          # andou 1 risco a favor: stop vai para a entrada
    max_operacoes: int = 4                  # por contrato, por dia
    max_contratos: int = 10
    espera_apos_saida_s: int = 300          # 5 minutos sem nova entrada no mesmo contrato
    janela_volatilidade_min: int = 15       # vai-e-vem dos ultimos 15 minutos define o risco
    hora_inicio: str = "09:15"              # do Douglas (08/10): opera das 9h15 as 13h. Ate aqui so se forma a faixa de abertura
    hora_ultima_entrada: str = "12:50"
    hora_zerar: str = "13:00"
    feed_parado_s: float = 15.0             # sem tique novo ha mais que isto: nao entra


@dataclass
class Posicao:
    lado: str                                # "C" comprado, "V" vendido
    contratos: int
    entrada: float
    stop: float
    alvo: float
    risco_pts: float
    hora: str
    protegido: bool = False


@dataclass
class EstadoAtivo:
    ativo: str
    posicao: Posicao | None = None
    operacoes: int = 0
    ultima_saida_ts: float = 0.0
    barras: list = field(default_factory=list)      # [[minuto_epoch, max, min, ultimo]]
    # maxima e minima do dia que o robo NAO viu (ligado no meio do pregao): vem da sessao do MetaTrader
    semente_max: float | None = None
    semente_min: float | None = None

    def como_dict(self):
        d = asdict(self)
        return d


def arredondar(preco, tick):
    return round(round(preco / tick) * tick, 6)


def atualizar_barras(estado, ts, preco, limite=600):
    """Acrescenta o tique a barra do minuto (max, min, ultimo). Guarda ate `limite` minutos."""
    minuto = int(ts // 60) * 60
    b = estado.barras
    if b and b[-1][0] == minuto:
        b[-1][1] = max(b[-1][1], preco)
        b[-1][2] = min(b[-1][2], preco)
        b[-1][3] = preco
    else:
        b.append([minuto, preco, preco, preco])
        if len(b) > limite:
            del b[: len(b) - limite]
    return estado


def referencias(estado, ts, p: Parametros):
    """Maxima e minima do dia ATE O MINUTO ANTERIOR e o vai-e-vem recente.

    O minuto corrente fica de fora de proposito: romper a maxima "do dia" contando o proprio
    tique que a formou nunca seria rompimento. Devolve (maxima, minima, amplitude) ou None
    enquanto nao ha barra fechada.
    """
    minuto = int(ts // 60) * 60
    fechadas = [x for x in estado.barras if x[0] < minuto]
    if not fechadas:
        return None
    maxima = max(x[1] for x in fechadas)
    minima = min(x[2] for x in fechadas)
    if estado.semente_max is not None:
        maxima = max(maxima, estado.semente_max)
    if estado.semente_min is not None:
        minima = min(minima, estado.semente_min)
    recentes = fechadas[-int(p.janela_volatilidade_min):]
    amplitude = max(x[1] for x in recentes) - min(x[2] for x in recentes)
    return maxima, minima, amplitude


def risco_em_pontos(ativo, amplitude):
    c = CONTRATOS[ativo]
    r = min(max(float(amplitude), c["risco_min"]), c["risco_max"])
    return arredondar(r, c["tick"])


def contratos_para(ativo, risco_pts, p: Parametros):
    c = CONTRATOS[ativo]
    reais = p.capital * p.risco_por_operacao
    n = int(math.floor(reais / (risco_pts * c["valor_ponto"]))) if risco_pts > 0 else 0
    return max(1, min(int(p.max_contratos), n))


def resultado_pontos(pos: Posicao, preco):
    return (preco - pos.entrada) if pos.lado == "C" else (pos.entrada - preco)


def resultado_reais(ativo, pos: Posicao, preco, com_custos=False):
    c = CONTRATOS[ativo]
    bruto = resultado_pontos(pos, preco) * c["valor_ponto"] * pos.contratos
    return bruto - (2 * c["custo"] * pos.contratos if com_custos else 0.0)


def _fechar(estado, preco_saida, hora, ts, motivo):
    pos = estado.posicao
    c = CONTRATOS[estado.ativo]
    custos = 2 * c["custo"] * pos.contratos
    pontos = resultado_pontos(pos, preco_saida)
    evento = {"tipo": "saida", "ativo": estado.ativo, "lado": pos.lado, "contratos": pos.contratos,
              "entrada": pos.entrada, "hora_entrada": pos.hora, "saida": preco_saida, "hora_saida": hora,
              "motivo": motivo, "pontos": pontos, "custos": custos,
              "resultado": pontos * c["valor_ponto"] * pos.contratos - custos}
    estado.posicao = None
    estado.ultima_saida_ts = ts
    return evento


def passo(estado: EstadoAtivo, ts: float, hora: str, preco: float, medio_dia, p: Parametros,
          pode_entrar=True, feed_ok=True):
    """Um tique de um contrato. Devolve a lista de eventos (entrada, protecao, saida).

    `hora` e HH:MM:SS de Brasilia; `medio_dia` e o preco medio da sessao (pode ser None);
    `pode_entrar` e False quando a trava do dia (meta ou perda) ja disparou.
    Ordem das checagens: primeiro o que protege (zerar pelo horario, stop, alvo), depois a
    entrada. Entrada e saida nunca acontecem no mesmo tique.
    """
    c = CONTRATOS[estado.ativo]
    tick = c["tick"]
    eventos = []
    ref = referencias(estado, ts, p)        # antes de por o tique na barra: o minuto corrente nao conta
    atualizar_barras(estado, ts, preco)
    pos = estado.posicao
    if pos is not None:
        if hora[:5] >= p.hora_zerar:
            saida = preco - tick if pos.lado == "C" else preco + tick      # a mercado: 1 tick contra
            eventos.append(_fechar(estado, saida, hora, ts, "fim_do_dia"))
            return eventos
        atingiu_stop = preco <= pos.stop if pos.lado == "C" else preco >= pos.stop
        if atingiu_stop:
            # stop e ordem a mercado: sai no pior entre o stop e o preco visto, 1 tick contra
            base = min(preco, pos.stop) if pos.lado == "C" else max(preco, pos.stop)
            saida = base - tick if pos.lado == "C" else base + tick
            eventos.append(_fechar(estado, saida, hora, ts, "protecao" if pos.protegido else "stop"))
            return eventos
        atingiu_alvo = preco >= pos.alvo if pos.lado == "C" else preco <= pos.alvo
        if atingiu_alvo:
            eventos.append(_fechar(estado, pos.alvo, hora, ts, "alvo"))     # ordem limitada: sai no alvo
            return eventos
        if not pos.protegido and resultado_pontos(pos, preco) >= p.protege_em_riscos * pos.risco_pts:
            pos.stop = pos.entrada
            pos.protegido = True
            eventos.append({"tipo": "protecao", "ativo": estado.ativo, "stop": pos.stop, "hora": hora})
        return eventos

    # sem posicao: procura entrada
    if not (pode_entrar and feed_ok) or ref is None:
        return eventos
    if not (p.hora_inicio <= hora[:5] < p.hora_ultima_entrada):
        return eventos
    if estado.operacoes >= p.max_operacoes or (ts - estado.ultima_saida_ts) < p.espera_apos_saida_s:
        return eventos
    if medio_dia is None or not medio_dia > 0:
        return eventos
    maxima, minima, amplitude = ref
    lado = None
    if preco >= maxima + tick and preco > medio_dia:
        lado = "C"
    elif preco <= minima - tick and preco < medio_dia:
        lado = "V"
    if lado is None:
        return eventos
    risco = risco_em_pontos(estado.ativo, amplitude)
    n = contratos_para(estado.ativo, risco, p)
    entrada = preco + tick if lado == "C" else preco - tick                 # a mercado: 1 tick contra
    stop = entrada - risco if lado == "C" else entrada + risco
    alvo = entrada + p.alvo_em_riscos * risco if lado == "C" else entrada - p.alvo_em_riscos * risco
    estado.posicao = Posicao(lado=lado, contratos=n, entrada=arredondar(entrada, tick),
                             stop=arredondar(stop, tick), alvo=arredondar(alvo, tick),
                             risco_pts=risco, hora=hora)
    estado.operacoes += 1
    eventos.append({"tipo": "entrada", "ativo": estado.ativo, "lado": lado, "contratos": n,
                    "entrada": estado.posicao.entrada, "stop": estado.posicao.stop,
                    "alvo": estado.posicao.alvo, "risco_pts": risco, "hora": hora,
                    "rompeu": maxima if lado == "C" else minima, "medio_dia": medio_dia})
    return eventos


def zerar(estado: EstadoAtivo, ts, hora, preco, motivo):
    """Fecha a posicao a mercado (trava do dia). Devolve o evento ou None."""
    if estado.posicao is None:
        return None
    tick = CONTRATOS[estado.ativo]["tick"]
    saida = preco - tick if estado.posicao.lado == "C" else preco + tick
    return _fechar(estado, saida, hora, ts, motivo)


def regras_em_texto(p: Parametros):
    """As regras como o Douglas le na tela. Muda aqui quando a regra mudar."""
    reais = lambda f: f"R$ {p.capital * f:,.0f}".replace(",", ".")       # noqa: E731
    return [
        f"Só entra das {p.hora_inicio} às {p.hora_ultima_entrada}; às {p.hora_zerar} zera tudo. Não dorme posicionado.",
        "Compra quando o preço rompe a máxima do dia (formada até o minuto anterior) e está acima do preço médio do dia.",
        "Vende quando rompe a mínima do dia e está abaixo do preço médio do dia.",
        f"Stop do tamanho do vai-e-vem dos últimos {p.janela_volatilidade_min} minutos (mini-índice: 150 a 400 pontos; "
        "mini-dólar: 3 a 8 pontos).",
        f"Alvo de {p.alvo_em_riscos:g} vezes o risco; andou {p.protege_em_riscos:g} risco a favor, o stop vai para a entrada.",
        f"Risco de {reais(p.risco_por_operacao)} por operação ({p.risco_por_operacao:.2%} do capital), até "
        f"{p.max_contratos} contratos e {p.max_operacoes} operações por contrato no dia.",
        f"Perda de {reais(p.perda_maxima_dia)} no dia ({p.perda_maxima_dia:.0%}): zera e para até amanhã.",
        f"Ganho de {reais(p.meta_dia)} no dia ({p.meta_dia:.0%}, a meta): zera e para até amanhã.",
        "Entrada e stop saem a mercado, com 1 tick contra; o alvo é ordem limitada.",
    ]
