"""
Regra do robo de day trade por LEITURA DE FLUXO (versao 1), inspirada no que Alison Correia
mostra no canal dele. Leia `quant/docs/metodo-alison-correia.md` antes: la esta o que e dele,
com a origem de cada coisa. Aqui esta o que virou regra, e a fronteira entre as duas coisas.

O QUE E DELE (aparece em varios videos, com numero):
  - opera em torno de NIVEIS (ajuste, abertura, maxima e minima do dia, preco medio) e so
    entra quando o fluxo confirma: alguem DEFENDE o nivel (absorve a agressao contraria e o
    preco nao passa) e depois o lado defensor passa a agredir; ou o nivel e PERDIDO com
    agressao a favor do rompimento;
  - stop curto, "atras do nivel": 3 pontos de mini-dolar e o mais citado, teto de 5;
  - PARCIAL cedo (1 a 5 pontos, mediana perto de 2,5), stop vai para o preco de entrada
    ("zero a zero") e o resto segue com stop movel uns 3 pontos atras;
  - lote pequeno, que so cresce com "colchao" tirado do lucro (R$ 1.000 por degrau) e volta
    quando o colchao e perdido; parar depois de 3 operacoes erradas no dia.

O QUE E NOSSO (ele nunca da o numero; sao escolhas para calibrar com dado, marcadas [NOSSO]):
  - quanto e "muita agressao": 1,5 vez a mediana do volume agredido em janelas de 30 s;
  - janela da defesa (90 s), toques minimos (5 segundos com negocio no nivel), fracao de
    agressao que confirma (60% em 15 s), distancia do gatilho (2 ticks) e de nao perseguir
    (6 ticks);
  - os numeros do MINI-INDICE: ele quase nao mostra indice; os pontos do dolar foram levados
    na proporcao do preco (3 pontos de dolar a 5.030 ~ 120 pontos de indice a 206.000).

O QUE FICOU DE FORA, porque depende de saber QUAL CORRETORA esta de cada lado (o MetaTrader
nao entrega): seguir o player pelo ranking, escalar em briga de bancos, o scalp do ajuste pelo
preco medio das corretoras. E as tecnicas que sao julgamento puro: dia de dado, leilao do
Banco Central, contra a tendencia do dia.

Como em estrategia.py, tudo e funcao pura: estado + tique + fita -> eventos.
"""
from dataclasses import dataclass, field

from quant.daytrade.estrategia import CONTRATOS, arredondar


@dataclass
class ParamAtivo:
    stop_pts: float            # stop inicial, em pontos do contrato
    parcial_pts: float         # ganho em que realiza metade
    arrasto_pts: float         # stop movel: distancia atras do melhor preco, depois da parcial
    teto_stop_pts: float       # nunca um stop maior que isto


# Mini-dolar: os numeros dele. Mini-indice: os mesmos, na proporcao do preco [NOSSO].
ATIVOS = {
    "WDOFUT": ParamAtivo(stop_pts=3.0, parcial_pts=2.5, arrasto_pts=3.0, teto_stop_pts=5.0),
    "WINFUT": ParamAtivo(stop_pts=120.0, parcial_pts=100.0, arrasto_pts=120.0, teto_stop_pts=200.0),
}


@dataclass
class ParamFluxo:
    capital: float = 100_000.0
    lote_base: int = 2                     # o minimo para poder fazer parcial (ele usa 1 a 2 minis)
    colchao_por_degrau: float = 1_000.0    # lucro acumulado que "paga" cada degrau de lote
    lote_por_degrau: int = 2
    lote_maximo: int = 10
    perdas_para_parar: int = 3             # dele: errou 3 no dia, para
    perda_maxima_dia: float = 0.01         # do Douglas: 1% do capital
    meta_dia: float = 0.01                 # do Douglas: 1% do capital
    max_operacoes: int = 8                 # por contrato, por dia (ele mostra 5 a 13 por sessao)
    espera_apos_saida_s: int = 180
    hora_inicio: str = "09:30"             # ele manda o aluno esperar a abertura assentar
    hora_ultima_entrada: str = "16:30"
    hora_zerar: str = "17:20"
    # [NOSSO] limiares da leitura
    janela_defesa_s: int = 90
    janela_tipico_s: int = 30
    mult_defesa: float = 1.5
    toques_min: int = 5
    janela_confirma_s: int = 15
    fracao_confirma: float = 0.60
    gatilho_ticks: int = 2
    perseguir_ticks: int = 6
    alcance_ticks: int = 10                # so olha niveis ate esta distancia do preco


@dataclass
class PosicaoF:
    lado: str
    contratos: int
    entrada: float
    stop: float
    hora: str
    tecnica: str
    nivel: float
    nome_nivel: str
    contratos_iniciais: int = 0
    parcial_feita: bool = False
    melhor: float = 0.0


@dataclass
class EstadoF:
    ativo: str
    posicao: PosicaoF | None = None
    operacoes: int = 0
    ultima_saida_ts: float = 0.0
    lado_dos_niveis: dict = field(default_factory=dict)   # nome do nivel -> "acima" | "abaixo" (onde o preco estava)


def lote_do_dia(acumulado, p: ParamFluxo):
    """A escada de lote dele: cada R$ 1.000 de lucro acumulado sobe um degrau; perdeu o colchao, desce."""
    degraus = int(max(acumulado, 0.0) // p.colchao_por_degrau)
    return int(min(p.lote_maximo, p.lote_base + degraus * p.lote_por_degrau))


def niveis_do_dia(cot):
    """Os niveis que ele usa e que o MetaTrader entrega: ajuste, abertura, maxima, minima, medio."""
    fora = []
    for nome, chave in (("ajuste de ontem", "ajuste"), ("fechamento de ontem", "anterior"), ("abertura", "abertura"),
                        ("máxima do dia", "maxima"), ("mínima do dia", "minima"), ("preço médio do dia", "medio")):
        v = (cot or {}).get(chave)
        if v is not None and v > 0:
            fora.append((nome, float(v)))
    return fora


def ler_fluxo(ativo, fita, preco, niveis, p: ParamFluxo):
    """Procura, nos niveis perto do preco, uma das duas leituras. Devolve o sinal ou None.

    DEFESA: muita agressao contra o nivel na janela, o preco nao passou, e agora o preco se
    afasta do nivel com o lado defensor agredindo. Entra a favor do defensor.
    PERDA: o preco estava de um lado do nivel, passou para o outro e quem agride empurra a
    favor do rompimento. Entra a favor do rompimento.
    """
    if fita is None or not fita.linhas:
        return None
    tick = CONTRATOS[ativo]["tick"]
    tipico = fita.volume_tipico(p.janela_tipico_s)
    if tipico is None:
        return None
    conf = fita.agressao(p.janela_confirma_s)
    if conf["fracao_compra"] is None:
        return None
    for nome, nivel in niveis:
        nivel = arredondar(nivel, tick)
        dist = (preco - nivel) / tick
        if abs(dist) > p.alcance_ticks:
            continue
        # DEFESA de suporte -> compra; de resistencia -> venda
        for lado_nivel, lado_op, afastou, fracao in (
                ("compra", "C", p.gatilho_ticks <= dist <= p.perseguir_ticks, conf["fracao_compra"]),
                ("venda", "V", -p.perseguir_ticks <= dist <= -p.gatilho_ticks, 1.0 - conf["fracao_compra"])):
            if not afastou or fracao < p.fracao_confirma:
                continue
            ab = fita.absorcao(nivel, lado_nivel, p.janela_defesa_s)
            if ab["furou"] or ab["toques"] < p.toques_min or ab["agredido"] < p.mult_defesa * tipico:
                continue
            return {"tecnica": "defesa", "lado": lado_op, "nivel": nivel, "nome_nivel": nome,
                    "medidas": {"agredido_no_nivel": ab["agredido"], "tipico_30s": tipico, "toques": ab["toques"],
                                "fracao_a_favor": round(fracao, 3)}}
    return None


def ler_perda(ativo, estado: EstadoF, fita, preco, niveis, p: ParamFluxo):
    """PERDA de nivel: usa de que lado do nivel o preco estava no tique anterior (guardado no estado)."""
    if fita is None or not fita.linhas:
        return None
    tick = CONTRATOS[ativo]["tick"]
    tipico = fita.volume_tipico(p.janela_tipico_s)
    conf = fita.agressao(p.janela_confirma_s)
    sinal = None
    for nome, nivel in niveis:
        nivel = arredondar(nivel, tick)
        antes = estado.lado_dos_niveis.get(nome)
        dist = (preco - nivel) / tick
        agora = "acima" if dist > 0 else ("abaixo" if dist < 0 else antes)
        if nome in ("máxima do dia", "mínima do dia", "preço médio do dia"):
            # estes andam com o preco: a perda deles ja e a regra de rompimento; aqui so os niveis FIXOS
            estado.lado_dos_niveis[nome] = agora
            continue
        if sinal is None and tipico is not None and conf["fracao_compra"] is not None and antes is not None:
            if antes == "acima" and -p.perseguir_ticks <= dist <= -p.gatilho_ticks \
                    and (1.0 - conf["fracao_compra"]) >= p.fracao_confirma and conf["total"] >= 0.5 * tipico:
                sinal = {"tecnica": "perda de nível", "lado": "V", "nivel": nivel, "nome_nivel": nome,
                         "medidas": {"fracao_a_favor": round(1.0 - conf["fracao_compra"], 3), "agredido_15s": conf["total"],
                                     "tipico_30s": tipico}}
            elif antes == "abaixo" and p.gatilho_ticks <= dist <= p.perseguir_ticks \
                    and conf["fracao_compra"] >= p.fracao_confirma and conf["total"] >= 0.5 * tipico:
                sinal = {"tecnica": "perda de nível", "lado": "C", "nivel": nivel, "nome_nivel": nome,
                         "medidas": {"fracao_a_favor": round(conf["fracao_compra"], 3), "agredido_15s": conf["total"],
                                     "tipico_30s": tipico}}
        # o lado so vira depois de o preco se afastar o bastante: encostar no nivel nao e perder
        if abs(dist) >= p.gatilho_ticks or antes is None:
            estado.lado_dos_niveis[nome] = agora
    return sinal


def _pontos(pos: PosicaoF, preco):
    return (preco - pos.entrada) if pos.lado == "C" else (pos.entrada - preco)


def _evento_saida(estado, pos, contratos, preco_saida, hora, motivo, final):
    c = CONTRATOS[estado.ativo]
    custos = 2 * c["custo"] * contratos
    pontos = _pontos(pos, preco_saida)
    return {"tipo": "saida" if final else "parcial", "ativo": estado.ativo, "lado": pos.lado, "contratos": contratos,
            "entrada": pos.entrada, "hora_entrada": pos.hora, "saida": preco_saida, "hora_saida": hora,
            "motivo": motivo, "pontos": pontos, "custos": custos, "tecnica": pos.tecnica, "nome_nivel": pos.nome_nivel,
            "resultado": pontos * c["valor_ponto"] * contratos - custos}


def passo(estado: EstadoF, ts, hora, preco, fita, niveis, p: ParamFluxo, lote, pode_entrar=True, feed_ok=True):
    """Um tique. Devolve eventos: entrada, parcial, saida.

    Conducao da posicao, na ordem dele: stop; parcial com stop no preco de entrada; stop movel.
    """
    a = ATIVOS[estado.ativo]
    tick = CONTRATOS[estado.ativo]["tick"]
    eventos = []
    pos = estado.posicao
    if pos is not None:
        if hora[:5] >= p.hora_zerar:
            saida = preco - tick if pos.lado == "C" else preco + tick
            eventos.append(_evento_saida(estado, pos, pos.contratos, saida, hora, "fim_do_dia", True))
            estado.posicao, estado.ultima_saida_ts = None, ts
            return eventos
        bateu = preco <= pos.stop if pos.lado == "C" else preco >= pos.stop
        if bateu:
            base = min(preco, pos.stop) if pos.lado == "C" else max(preco, pos.stop)
            saida = base - tick if pos.lado == "C" else base + tick
            motivo = "stop" if not pos.parcial_feita else ("zero a zero" if abs(pos.stop - pos.entrada) < 1e-9 else "stop móvel")
            eventos.append(_evento_saida(estado, pos, pos.contratos, saida, hora, motivo, True))
            estado.posicao, estado.ultima_saida_ts = None, ts
            return eventos
        pos.melhor = max(pos.melhor, preco) if pos.lado == "C" else min(pos.melhor, preco)
        if not pos.parcial_feita and _pontos(pos, preco) >= a.parcial_pts:
            metade = pos.contratos // 2
            alvo = pos.entrada + a.parcial_pts if pos.lado == "C" else pos.entrada - a.parcial_pts
            if metade >= 1:
                eventos.append(_evento_saida(estado, pos, metade, arredondar(alvo, tick), hora, "parcial", False))
                pos.contratos -= metade
            pos.parcial_feita = True
            pos.stop = pos.entrada                          # zero a zero
        if pos.parcial_feita:
            movel = pos.melhor - a.arrasto_pts if pos.lado == "C" else pos.melhor + a.arrasto_pts
            movel = arredondar(movel, tick)
            if (pos.lado == "C" and movel > pos.stop) or (pos.lado == "V" and movel < pos.stop):
                pos.stop = movel
        return eventos

    sinal_perda = ler_perda(estado.ativo, estado, fita, preco, niveis, p)   # sempre roda: mantem o lado dos niveis
    if not (pode_entrar and feed_ok) or not (p.hora_inicio <= hora[:5] < p.hora_ultima_entrada):
        return eventos
    if estado.operacoes >= p.max_operacoes or (ts - estado.ultima_saida_ts) < p.espera_apos_saida_s:
        return eventos
    sinal = ler_fluxo(estado.ativo, fita, preco, niveis, p) or sinal_perda
    if sinal is None:
        return eventos
    lado = sinal["lado"]
    entrada = arredondar(preco + tick if lado == "C" else preco - tick, tick)
    # stop atras do nivel, do tamanho que ele usa; nunca maior que o teto
    atras = sinal["nivel"] - 2 * tick if lado == "C" else sinal["nivel"] + 2 * tick
    padrao = entrada - a.stop_pts if lado == "C" else entrada + a.stop_pts
    stop = min(atras, padrao) if lado == "C" else max(atras, padrao)
    if abs(entrada - stop) > a.teto_stop_pts:
        stop = entrada - a.teto_stop_pts if lado == "C" else entrada + a.teto_stop_pts
    stop = arredondar(stop, tick)
    n = max(1, int(lote))
    estado.posicao = PosicaoF(lado=lado, contratos=n, entrada=entrada, stop=stop, hora=hora, tecnica=sinal["tecnica"],
                              nivel=sinal["nivel"], nome_nivel=sinal["nome_nivel"], contratos_iniciais=n, melhor=entrada)
    estado.operacoes += 1
    eventos.append({"tipo": "entrada", "ativo": estado.ativo, "lado": lado, "contratos": n, "entrada": entrada,
                    "stop": stop, "hora": hora, "tecnica": sinal["tecnica"], "nivel": sinal["nivel"],
                    "nome_nivel": sinal["nome_nivel"], "medidas": sinal["medidas"]})
    return eventos


def zerar(estado: EstadoF, ts, hora, preco, motivo):
    pos = estado.posicao
    if pos is None:
        return None
    tick = CONTRATOS[estado.ativo]["tick"]
    saida = preco - tick if pos.lado == "C" else preco + tick
    ev = _evento_saida(estado, pos, pos.contratos, saida, hora, motivo, True)
    estado.posicao, estado.ultima_saida_ts = None, ts
    return ev


def regras_em_texto(p: ParamFluxo):
    d, i = ATIVOS["WDOFUT"], ATIVOS["WINFUT"]
    return [
        "Leitura de fluxo: o robô só entra perto de um nível (ajuste, fechamento de ontem, abertura, máxima, mínima e preço médio do dia) "
        "e só quando os negócios confirmam.",
        f"DEFESA: em {p.janela_defesa_s} s houve agressão contra o nível de pelo menos {p.mult_defesa:g} vez o normal, o preço não passou, "
        f"e agora {p.fracao_confirma:.0%} da agressão dos últimos {p.janela_confirma_s} s é do lado que defendeu. Entra com o defensor.",
        "PERDA DE NÍVEL: o preço estava de um lado do ajuste, do fechamento ou da abertura, passou para o outro, e a agressão empurra a favor. "
        "Entra a favor do rompimento.",
        f"Stop atrás do nível: {d.stop_pts:g} pontos no mini-dólar (teto {d.teto_stop_pts:g}) e {i.stop_pts:g} no mini-índice (teto {i.teto_stop_pts:g}).",
        f"Parcial: realiza metade com {d.parcial_pts:g} pontos (dólar) ou {i.parcial_pts:g} (índice) e leva o stop para o preço de entrada.",
        f"O resto segue com stop móvel {d.arrasto_pts:g} pontos (dólar) ou {i.arrasto_pts:g} (índice) atrás do melhor preço.",
        f"Lote: {p.lote_base} contratos; sobe {p.lote_por_degrau} a cada R$ {p.colchao_por_degrau:,.0f} de lucro acumulado e desce quando o lucro é devolvido "
        f"(até {p.lote_maximo}).".replace(",", "."),
        f"Para depois de {p.perdas_para_parar} operações perdedoras no dia, ou com 1% de perda, ou com 1% de ganho (a meta).",
        f"Entradas das {p.hora_inicio} às {p.hora_ultima_entrada}; às {p.hora_zerar} zera tudo.",
        "Não copia o que depende de saber qual corretora está comprando ou vendendo: o MetaTrader não informa.",
    ]
