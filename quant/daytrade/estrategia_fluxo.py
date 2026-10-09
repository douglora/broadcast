"""
Regra do robo de day trade por LEITURA DE FLUXO (versao 1.1), tirada do que Alison Correia
ensina e faz no canal dele. Leia `quant/docs/metodo-alison-correia.md` antes: la esta a origem
de cada coisa, com video e minuto. Aqui esta o que virou regra, e a fronteira entre o que e
dele e o que tivemos de escolher.

O QUE E DELE (segunda leitura do canal: aulas longas e lives inteiras, alem dos videos curtos):
  - le o fluxo no contrato CHEIO do dolar e executa no MINI; no cheio, negocio de 5 contratos
    e "lote de robo" e some do filtro, 50 e o lote de instituicao;
  - opera em torno de NIVEIS que anota antes: ajuste, fechamento, abertura, maxima e minima,
    preco medio do dia, e a variacao de 1% no dia (so opera contra a tendencia a partir dai);
  - DEFESA: o nivel e testado (3 vezes), batem nele com lote e ele nao cede. Primeiro nao se
    faz nada; a entrada e 1 a 3 pontos ALEM do nivel, depois de a fita mostrar que o lado que
    defendeu passou a agredir. Stop: a perda do nivel;
  - PERDA DE NIVEL: nao entra na primeira quebra. Espera a confirmacao: o preco volta ao
    nivel, nao consegue retomar e sai de novo (o suporte virou resistencia), ou a agressao a
    favor cresce com lote de instituicao. Stop 1 a 2 pontos alem do nivel perdido;
  - ROMPIMENTO: nivel batido varias vezes (3 ou mais) e rompido com fluxo, so a favor do lado
    do dia. "Rompimento tem que romper": se nao anda, sai;
  - EXAUSTAO: operar contra um movimento esticado (20 a 30 pontos em uns 10 minutos) que parou
    de renovar o extremo, com stop 1 ponto alem dele. Nas lives de 2020 e o tipo mais frequente;
  - stop "definido pelo preco, nao por pontos": fica atras do nivel, de 2 a 5 pontos, e mais
    longo em dia que anda muito (5 a 6);
  - PARCIAL de uns 2 pontos em metade do lote, stop vai para o preco de entrada, e o resto
    segue com o stop andando uns 3 pontos atras; nao ha alvo fixo;
  - risco do dia: perda maxima de R$ 1.000 e para; se estava ganhando e devolveu 20% do lucro
    do dia, para; nao opera nos primeiros minutos, cancela tudo antes do dado das 9h30, nao
    opera com o spread aberto (normal 0,5 ponto); indice so depois que as acoes abrem (10h);

O QUE E DO DOUGLAS (decisao dele em 08/10/2026): mini-dolar e mini-indice; meta de 1% ao dia;
janela das 9h15 as 13h (ultima entrada 12h50, zera as 13h); e a chave liga/desliga (chave.py).
  - lote pequeno (1 a 2 minis), que so cresce com lucro acumulado.

O QUE E NOSSO (ele recusa dar o numero; escolhas para calibrar com a fita gravada, marcadas [NOSSO]):
  - quanto e "muita agressao": 1,5 vez a mediana do volume agredido em janelas de 30 s. Ele
    diz que o lote que conta muda todo dia (50 num dia, 300 no outro);
  - a agressao que confirma (60% em 15 s) e quanto tempo vale uma perda de nivel (20 min);
  - o que e "dia rapido" (vai-e-vem tipico de 1 minuto de 3 pontos ou mais);
  - o MINI-INDICE inteiro: ele opera a sala de dolar. Do indice mostra pouco (stop de 200 e
    parcial de 100 pontos em lives de 2019 ou 2020, a data nao e dita; so depois das 10h). Esses numeros foram trazidos ao preco
    de hoje e a geometria da entrada veio do dolar, na proporcao do vai-e-vem dos dois.

O QUE FICOU DE FORA: tudo o que depende de saber QUAL CORRETORA esta de cada lado (o ranking
por corretora, o preco medio do maior comprador do dia), que o MetaTrader nao entrega, e que
nas lives ele usa em quase toda operacao relevante. E o que e julgamento: dia de dado,
leilao do Banco Central, o giro dentro da faixa do ajuste, o lote grande que atrai o preco.

Como em estrategia.py, tudo e funcao pura: estado + tique + fita -> eventos.
"""
from dataclasses import dataclass, field

from quant.daytrade.estrategia import CONTRATOS, arredondar


@dataclass
class ParamAtivo:
    stop_min_pts: float            # menor stop aceito (dele: 2 pontos em dia calmo)
    stop_teto_pts: float           # dele: "nao costumo ter stops acima de 5 pontos"
    stop_teto_rapido_pts: float    # dele: em mercado rapido aceita 5 ou 6
    folga_stop_pts: float          # "atras do nivel": quanto alem do nivel fica o stop (dele: 0,5 a 3)
    stop_rompimento_pts: float     # dele (2020): stop de rompimento de 3 pontos, "quanto menor melhor"
    parcial_pts: float             # dele: parcial de uns 2 pontos, metade do lote
    arrasto_pts: float             # dele: stop andando 2,5 a 5 pontos atras
    gatilho_pts: float             # dele: entra de 1 ...
    perseguir_pts: float           # ... a 3 pontos alem do nivel
    zona_pts: float                # "no nivel" = ate esta distancia dele
    afasta_pts: float              # [NOSSO] um teste so conta de novo depois de o preco se afastar isto
    rapido_pts: float              # [NOSSO] dia rapido: vai-e-vem tipico de 1 minuto deste tamanho ou mais
    esticada_pts: float            # dele: opera contra depois de o preco andar 20 a 30 pontos em uns 10 minutos
    spread_max_pts: float          # dele: spread normal 0,5; com 1 ponto ou mais falta volume
    hora_inicio: str
    fonte_fluxo: str               # prefixo do contrato onde se LE o fluxo (a execucao e sempre no mini)
    sem_lote_de_robo: bool         # na fonte, descartar negocio abaixo de 10 e exigir lote de instituicao


# Mini-dolar: os numeros dele. Mini-indice: os poucos numeros dele (lives de 2019 ou 2020, indice perto de 100 mil) trazidos ao preco de hoje
# (stop 200 -> 400, parcial 100 -> 200) e a geometria do dolar vezes 60, a razao do vai-e-vem [NOSSO].
# Teto do stop do indice: Cleber Rocha, que conduz a sala de indice dele, trabalha com ate ~0,1% do preco
# (50 pontos com o indice entre 45 e 80 mil); as lives do Alison mostram 0,2%. Ficou 250 (0,12%), 400 em dia rapido.
# Na fita do mini-indice tambem se descarta o negocio pequeno (menos de 10) e se pede lote de 50 ou mais batendo
# no nivel: e a versao, no mini, do filtro que Cleber usa no indice cheio (5 e robo, olha de 10 para cima) [NOSSO].
ATIVOS = {
    "WDOFUT": ParamAtivo(stop_min_pts=2.0, stop_teto_pts=5.0, stop_teto_rapido_pts=6.0, folga_stop_pts=1.0,
                         stop_rompimento_pts=3.0, parcial_pts=2.0, arrasto_pts=3.0, gatilho_pts=1.0, perseguir_pts=3.0,
                         zona_pts=0.5, afasta_pts=1.5, rapido_pts=3.0, esticada_pts=20.0, spread_max_pts=1.0,
                         hora_inicio="09:15", fonte_fluxo="DOL", sem_lote_de_robo=True),
    "WINFUT": ParamAtivo(stop_min_pts=120.0, stop_teto_pts=250.0, stop_teto_rapido_pts=400.0, folga_stop_pts=60.0,
                         stop_rompimento_pts=180.0, parcial_pts=200.0, arrasto_pts=200.0, gatilho_pts=60.0, perseguir_pts=180.0,
                         zona_pts=30.0, afasta_pts=90.0, rapido_pts=180.0, esticada_pts=800.0, spread_max_pts=15.0,
                         hora_inicio="10:05", fonte_fluxo="WIN", sem_lote_de_robo=True),
}

FIXOS = ("ajuste de ontem", "fechamento de ontem", "abertura", "1% acima do ajuste", "1% abaixo do ajuste",
         "máxima de ontem", "mínima de ontem")
EXTREMOS = {"max": "máxima do dia", "min": "mínima do dia"}


@dataclass
class ParamFluxo:
    capital: float = 100_000.0
    lote_base: int = 2                     # o minimo para poder fazer parcial (ele usa 1 a 2 minis na sala)
    colchao_por_degrau: float = 1_000.0    # lucro acumulado que "paga" cada degrau de lote
    lote_por_degrau: int = 2
    lote_maximo: int = 8                   # dele: sobe de 2 em 2 ate 7 ou 8
    perdas_para_parar: int = 3             # da sala dele (voz incerta; um parceiro diz 4)
    perda_maxima_dia_rs: float = 1_000.0   # dele: "perdi R$ 1.000, nao clico mais" (igual ao 1% do Douglas)
    meta_dia_rs: float | None = 1_000.0    # do Douglas (1%). Ele fala em "stop gain do dia" sem dar valor; em 2015 dizia nao ter meta
    devolucao_para: float = 0.20           # dele: devolveu 20% do lucro do dia, para
    devolucao_piso_rs: float = 100.0       # [NOSSO] a regra dos 20% so vale depois de o dia ter chegado a +R$ 100
    max_operacoes: int = 12                # por contrato, por dia (as lives dele tem de 10 a 17 no dolar)
    espera_apos_saida_s: int = 120         # dele: "para e respira" depois de cada operacao (o tempo e nosso)
    espera_apos_perda_s: int = 180         # ele diz "errou, respira mais", mas nas lives volta em ate 6 minutos (6 de 7 deram ganho)
    pausa_dado: tuple = ("09:28", "09:40") # dele: cancela as ordens 1 minuto antes do dado das 9h30; o ciclo do dado leva 7 a 15 minutos
    hora_ultima_entrada: str = "12:50"     # do Douglas (08/10): o robo opera das 9h15 as 13h. Bate com ele: as lives
    hora_zerar: str = "13:00"              # acabam de manha e os maiores stops dele vieram de ficar ate a tarde
    # leitura
    janela_defesa_s: int = 900             # dele: confere o volume por preco dos ultimos 10 a 30 minutos
    testes_min: int = 3                    # dele: 3 testes sem perder o nivel
    testes_max: int = 4                    # dele: nivel testado 5 vezes ou mais ele so opera a perda, nao compra o suporte
    rodadas_grandes_min: int = 1           # dele o lote de 50; [NOSSO] quantas vezes ele tem de bater no nivel
    janela_tipico_s: int = 30
    mult_defesa: float = 1.5               # [NOSSO]
    janela_confirma_s: int = 15            # [NOSSO]
    fracao_confirma: float = 0.60          # [NOSSO]
    mult_confirma: float = 0.5             # [NOSSO] a confirmacao so vale com pelo menos metade do volume normal de 15 s ...
    negocios_confirma: int = 3             # [NOSSO] ... e 3 negocios: um negocio sozinho nao e "o lado que passou a agredir"
    validade_perda_s: int = 1200           # [NOSSO] quanto tempo depois da quebra ainda vale o reteste
    firmeza_perda_s: int = 20              # [NOSSO] a "primeira quebra" que ele nao vende: os primeiros segundos
    mult_perda: float = 1.5                # [NOSSO] agressao que confirma a perda sem reteste
    fracao_perda: float = 0.70             # [NOSSO]
    testes_rompimento: int = 2             # ele ensina esperar varias batidas (3, 5, 6 a 7), mas nas 18 lives medidas o
                                           # rompimento e o tipo que menos perde (4 perdas em 24) e muitas vezes vem na 1a ou 2a
    tempo_rompimento_s: int = 120          # [NOSSO] dele a regra: rompimento que nao anda, sai
    janela_esticada_s: int = 600           # dele: "depois de subir 30 pontos em 10 minutos"
    sem_extremo_novo_s: int = 30           # [NOSSO] o movimento parou: ha quanto tempo nao renova o extremo
    fracao_exaustao: float = 0.5           # [NOSSO] no extremo a agressao a favor encolheu para menos da metade do miolo
    contras_por_extremo: int = 3           # dele: vendeu o mesmo nivel ate 3 vezes
    variacao_contra: float = 0.01          # dele: contra a tendencia so com 1% no dia
    variacao_um_lado: float = 0.015        # dele: dolar subindo 1,5% nao compra, so vende (o espelho e nosso)


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
    ts_entrada: float = 0.0
    parcial_pts: float | None = None       # None = a parcial padrao do contrato
    alvo: float | None = None              # preco em que sai de tudo; None = sem alvo
    sem_arrasto: bool = False              # True = depois da parcial o stop fica na entrada, sem andar
    tempo_max_s: float | None = None       # passou disso com a posicao aberta, sai a mercado (None = so stop, alvo ou fim da janela)
    sem_parcial: bool = False              # True = nao realiza metade no caminho nem leva o stop para a entrada


@dataclass
class EstadoF:
    ativo: str
    posicao: PosicaoF | None = None
    operacoes: int = 0
    ultima_saida_ts: float = 0.0
    ultima_foi_perda: bool = False
    lado_dos_niveis: dict = field(default_factory=dict)   # nome do nivel -> "acima" | "abaixo" (onde o preco estava)
    perdas: dict = field(default_factory=dict)            # nome do nivel -> {"ts", "lado", "retestou"}: nivel perdido, aguardando confirmacao
    extremos: dict = field(default_factory=dict)          # "max" | "min" -> {"nivel", "testes", "fora"}
    contras: dict = field(default_factory=dict)           # "alta" | "baixa" -> {"extremo", "n"}: quantas vezes ja operou contra este extremo


def lote_do_dia(acumulado, p: ParamFluxo):
    """A escada de lote dele: cada R$ 1.000 de lucro acumulado sobe um degrau; perdeu o colchao, desce."""
    degraus = int(max(acumulado, 0.0) // p.colchao_por_degrau)
    return int(min(p.lote_maximo, p.lote_base + degraus * p.lote_por_degrau))


def niveis_do_dia(cot, p: ParamFluxo | None = None):
    """Os niveis que ele anota e que o MetaTrader entrega. A variacao de 1% entra como nivel:
    e ali que ele aceita operar contra a tendencia do dia."""
    p = p or ParamFluxo()
    cot = cot or {}
    fora = []
    for nome, chave in (("ajuste de ontem", "ajuste"), ("fechamento de ontem", "anterior"), ("abertura", "abertura"),
                        ("máxima do dia", "maxima"), ("mínima do dia", "minima"), ("preço médio do dia", "medio"),
                        ("máxima de ontem", "maxima_ontem"), ("mínima de ontem", "minima_ontem")):
        v = cot.get(chave)
        if v is not None and v > 0:
            fora.append((nome, float(v)))
    base = cot.get("ajuste") or cot.get("anterior")
    if base and base > 0:
        fora.append(("1% acima do ajuste", float(base) * (1.0 + p.variacao_contra)))
        fora.append(("1% abaixo do ajuste", float(base) * (1.0 - p.variacao_contra)))
    return fora


def dia_rapido(ativo, fita):
    """Dia que anda muito pede stop mais longo: ele diz que o stop de 2 pontos de ontem nao serve hoje."""
    amp = fita.amplitude_tipica(60) if fita is not None else None
    return amp is not None and amp >= ATIVOS[ativo].rapido_pts


def fita_viva(mini, fita):
    """A fita do mini, se existe e negociou no ultimo meio minuto; senao a propria fita lida."""
    if mini is not None and mini.linhas and mini.relogio() - mini.ultimo_seg <= 30:
        return mini
    return fita


def confirmacao(fita, p: ParamFluxo):
    """Quem agride AGORA (ultimos 15 s do relogio do pregao) e se a amostra basta para dizer alguma coisa.

    A leitura de instituicao (quanto bateram no nivel, com que lote) vem do contrato cheio, como ele faz. Mas
    em 2026 o dolar cheio negocia pouco: em 08/10 as tres primeiras entradas do robo "confirmaram" com zero ou
    um negocio do cheio em 15 s. Por isso a confirmacao e lida na fita do mini quando ela existe [NOSSO].
    """
    if fita is None or not fita.linhas:
        return {"vale": False, "fracao_compra": None, "total": 0.0, "negocios": 0, "tipico": None}
    conf = fita.agressao(p.janela_confirma_s)
    tipico = fita.volume_tipico(p.janela_confirma_s)
    vale = conf["fracao_compra"] is not None and tipico is not None \
        and conf["total"] >= p.mult_confirma * tipico and conf["negocios"] >= p.negocios_confirma
    return dict(conf, tipico=tipico, vale=vale)


def ler_defesa(ativo, fita, preco, niveis, p: ParamFluxo, fita_conf=None):
    """DEFESA de um nivel. Devolve o sinal ou None.

    Na janela (15 min) o preco foi ao nivel pelo menos 3 vezes, bateram nele com volume e ele
    nao cedeu; agora o preco esta de 1 a 3 pontos alem do nivel e quem agride e o lado que
    defendeu. Entra com o defensor. Nunca no proprio nivel: ali e o teste.
    """
    if fita is None or not fita.linhas:
        return None
    a, tick = ATIVOS[ativo], CONTRATOS[ativo]["tick"]
    tipico = fita.volume_tipico(p.janela_tipico_s)
    conf = confirmacao(fita_viva(fita_conf, fita), p)
    if tipico is None or not conf["vale"]:
        return None
    zona, afasta = max(1, round(a.zona_pts / tick)), max(1, round(a.afasta_pts / tick))
    for nome, nivel in niveis:
        nivel = arredondar(nivel, tick)
        dist = preco - nivel
        for lado_nivel, lado_op, alem, fracao in (("compra", "C", dist, conf["fracao_compra"]),
                                                  ("venda", "V", -dist, 1.0 - conf["fracao_compra"])):
            if not (a.gatilho_pts - 1e-9 <= alem <= a.perseguir_pts + 1e-9) or fracao < p.fracao_confirma:
                continue
            ab = fita.absorcao(nivel, lado_nivel, p.janela_defesa_s, folga_ticks=zona, tolerancia_ticks=1)
            if ab["furou"] or ab["agredido"] < p.mult_defesa * tipico:
                continue
            testes = fita.testes(nivel, lado_nivel, p.janela_defesa_s, zona_ticks=zona, afasta_ticks=afasta)
            if testes < p.testes_min or testes > p.testes_max:
                continue
            if a.sem_lote_de_robo and fita.separa_tamanho and ab["rodadas_grandes"] < p.rodadas_grandes_min:
                continue
            return {"tecnica": "defesa", "lado": lado_op, "nivel": nivel, "nome_nivel": nome,
                    "medidas": {"testes": testes, "agredido_no_nivel": ab["agredido"], "tipico_30s": tipico,
                                "lotes_grandes_no_nivel": ab["rodadas_grandes"], "fracao_a_favor": round(fracao, 3)}}
    return None


def ler_perda(ativo, estado: EstadoF, fita, ts, preco, niveis, p: ParamFluxo, fita_conf=None):
    """PERDA de nivel, em dois tempos. Roda em todo tique porque guarda de que lado o preco esta.

    1) o preco passa para o outro lado do nivel com folga: o nivel esta PERDIDO, mas nao entra
       (ele nao vende a primeira quebra: muitas vezes o preco bate, volta, e quem vendeu cedo paga);
    2) confirma de um de dois jeitos:
       RETESTE - o preco volta ao nivel, nao retoma, e sai de novo com a agressao a favor;
       AGRESSAO - sem voltar, a agressao a favor cresce (1,5 vez o normal, 70% de um lado) e,
                  no contrato cheio, com lote de instituicao.
    """
    a, tick = ATIVOS[ativo], CONTRATOS[ativo]["tick"]
    tem_fita = fita is not None and bool(fita.linhas)
    conf = confirmacao(fita_viva(fita_conf, fita), p) if tem_fita else None
    tipico = conf["tipico"] if conf else None
    cheio = fita.agressao(p.janela_confirma_s) if tem_fita else None      # lote de instituicao: sempre da fita lida (o cheio)
    sinal = None
    for nome, nivel in niveis:
        if nome not in FIXOS:
            continue
        nivel = arredondar(nivel, tick)
        dist = preco - nivel
        antes = estado.lado_dos_niveis.get(nome)
        if antes is None:
            if abs(dist) >= a.gatilho_pts - 1e-9:
                estado.lado_dos_niveis[nome] = "acima" if dist > 0 else "abaixo"
            continue
        if antes == "acima" and dist <= -a.gatilho_pts + 1e-9:
            estado.lado_dos_niveis[nome] = "abaixo"
            estado.perdas[nome] = {"ts": ts, "lado": "V", "retestou": False}
        elif antes == "abaixo" and dist >= a.gatilho_pts - 1e-9:
            estado.lado_dos_niveis[nome] = "acima"
            estado.perdas[nome] = {"ts": ts, "lado": "C", "retestou": False}
        perda = estado.perdas.get(nome)
        if perda is None:
            continue
        if ts - perda["ts"] > p.validade_perda_s:
            estado.perdas.pop(nome, None)
            continue
        alem = -dist if perda["lado"] == "V" else dist           # quanto o preco esta alem do nivel, a favor da perda
        if alem <= a.zona_pts + 1e-9 and ts - perda["ts"] >= p.firmeza_perda_s:
            perda["retestou"] = True                              # voltou a encostar no nivel perdido
        if sinal is not None or conf is None or not conf["vale"]:
            continue
        if not (a.gatilho_pts - 1e-9 <= alem <= a.perseguir_pts + 1e-9) or ts - perda["ts"] < p.firmeza_perda_s:
            continue
        favor = (1.0 - conf["fracao_compra"]) if perda["lado"] == "V" else conf["fracao_compra"]
        grande = cheio["venda_grande"] if perda["lado"] == "V" else cheio["compra_grande"]
        como = None
        if perda["retestou"] and favor >= p.fracao_confirma:
            como = "reteste"
        elif tipico is not None and conf["total"] >= p.mult_perda * tipico and favor >= p.fracao_perda \
                and (grande > 0 or not (a.sem_lote_de_robo and fita.separa_tamanho)):
            como = "agressão"
        if como:
            sinal = {"tecnica": "perda de nível", "lado": perda["lado"], "nivel": nivel, "nome_nivel": nome,
                     "medidas": {"confirmacao": como, "fracao_a_favor": round(favor, 3), "agredido_15s": conf["total"],
                                 "tipico_15s": tipico, "lote_grande_a_favor": grande}}
    return sinal


def ler_rompimento(ativo, estado: EstadoF, fita, preco, niveis, p: ParamFluxo, contexto=None, fita_conf=None):
    """ROMPIMENTO da maxima ou da minima do dia depois de varias batidas. Roda em todo tique.

    Conta quantas vezes o preco foi ao extremo e voltou. Quando o extremo e rompido com folga:
    se ja tinha sido testado 3 vezes, a agressao empurra a favor e o dia esta desse lado (preco
    do lado certo do preco medio), entra. Com ou sem entrada, o extremo novo comeca a contar do zero.
    """
    a, tick = ATIVOS[ativo], CONTRATOS[ativo]["tick"]
    de = dict(niveis)
    tem_fita = fita is not None and bool(fita.linhas)
    conf = confirmacao(fita_viva(fita_conf, fita), p) if tem_fita else None
    tipico = conf["tipico"] if conf else None
    medio = (contexto or {}).get("medio") or de.get("preço médio do dia")
    sinal = None
    for chave, sentido in (("max", 1.0), ("min", -1.0)):
        e = estado.extremos.get(chave)
        if e is None:
            v = de.get(EXTREMOS[chave])
            if v is None:
                continue
            e = estado.extremos[chave] = {"nivel": arredondar(v, tick), "testes": 1, "fora": False}
        alem = (preco - e["nivel"]) * sentido
        if alem >= a.gatilho_pts - 1e-9:                          # rompeu
            lado = "C" if chave == "max" else "V"
            favor = None if conf is None or not conf["vale"] else \
                (conf["fracao_compra"] if lado == "C" else 1.0 - conf["fracao_compra"])
            do_lado_do_dia = medio is None or (preco > medio if lado == "C" else preco < medio)
            if sinal is None and e["testes"] >= p.testes_rompimento and alem <= a.perseguir_pts + 1e-9 \
                    and favor is not None and favor >= p.fracao_confirma and tipico is not None \
                    and conf["total"] >= tipico and do_lado_do_dia:
                sinal = {"tecnica": "rompimento", "lado": lado, "nivel": e["nivel"], "nome_nivel": EXTREMOS[chave],
                         "medidas": {"testes": e["testes"], "fracao_a_favor": round(favor, 3), "agredido_15s": conf["total"],
                                     "tipico_15s": tipico}}
            e["nivel"], e["testes"], e["fora"] = arredondar(preco, tick), 1, False
        elif alem > 0:                                            # um tick a mais: e o mesmo extremo, que se estica
            e["nivel"] = arredondar(preco, tick)
        elif alem <= -a.afasta_pts + 1e-9:
            e["fora"] = True
        elif e["fora"] and alem >= -a.zona_pts - 1e-9:
            e["testes"], e["fora"] = e["testes"] + 1, False
    return sinal


def ler_exaustao(ativo, estado: EstadoF, fita, preco, p: ParamFluxo, fita_volume=None, var=None):
    """EXAUSTAO: operar CONTRA um movimento esticado que parou. E o tipo de entrada mais frequente nas
    lives dele de 2020 (18 de 49 operacoes medidas), e a mesma leitura que os manuais de fita de fora descrevem.

    So vale com o dia ja esticado 1% para o lado do movimento: e a regra que ele diz, e nas lives em que
    operou contra com menos que isso perdeu 4 de 5. `var` e a variacao do dia contra o ajuste, em fracao.
    O preco andou 20 pontos ou mais em 10 minutos, deixou de renovar o extremo, recuou de 1 a 3 pontos,
    quem agride agora e o outro lado, e no extremo a agressao a favor do movimento tinha encolhido
    (menos da metade do que se viu no miolo da corrida). Entra contra; o stop fica 1 ponto alem do extremo.
    `fita_volume`: de onde tirar o volume por preco (a do mini, que tem mais negocio); sem ela, a propria fita.
    """
    if fita is None or not fita.linhas:
        return None
    a, tick = ATIVOS[ativo], CONTRATOS[ativo]["tick"]
    vol = fita_viva(fita_volume, fita)
    corr = vol.corrida(p.janela_esticada_s)                 # a corrida e a confirmacao saem da fita mais negociada
    conf = confirmacao(vol, p)
    if corr is None or not conf["vale"]:
        return None
    for sentido, lado_op, chave_vol in (("alta", "V", "compra"), ("baixa", "C", "venda")):
        c = corr[sentido]
        if var is None or (var < p.variacao_contra if sentido == "alta" else var > -p.variacao_contra):
            continue
        if c["tamanho"] < a.esticada_pts - 1e-9 or vol.relogio() - c["seg_extremo"] < p.sem_extremo_novo_s:
            continue
        recuo = (c["extremo"] - preco) if sentido == "alta" else (preco - c["extremo"])
        if not (a.gatilho_pts - 1e-9 <= recuo <= a.perseguir_pts + 1e-9):
            continue
        favor = (1.0 - conf["fracao_compra"]) if lado_op == "V" else conf["fracao_compra"]
        if favor < p.fracao_confirma:
            continue
        feitas = estado.contras.get(sentido) or {}
        mesmo = abs((feitas.get("extremo") or 0.0) - c["extremo"]) <= a.zona_pts + 1e-9
        if mesmo and int(feitas.get("n") or 0) >= p.contras_por_extremo:
            continue
        por_preco = vol.por_preco(p.janela_esticada_s)
        no_extremo = sum(v[chave_vol] for pr, v in por_preco.items() if abs(pr - c["extremo"]) <= a.zona_pts + 1e-9)
        miolo = max((v[chave_vol] for pr, v in por_preco.items()
                     if abs(pr - c["extremo"]) > a.zona_pts + 1e-9
                     and min(c["origem"], c["extremo"]) - 1e-9 <= pr <= max(c["origem"], c["extremo"]) + 1e-9), default=0.0)
        if miolo <= 0 or no_extremo > p.fracao_exaustao * miolo:
            continue
        return {"tecnica": "exaustão", "lado": lado_op, "nivel": arredondar(c["extremo"], tick),
                "nome_nivel": "topo da corrida" if sentido == "alta" else "fundo da corrida", "sentido": sentido,
                "medidas": {"corrida_pts": c["tamanho"], "recuo_pts": recuo, "agressao_no_extremo": no_extremo,
                            "agressao_no_miolo": miolo, "fracao_a_favor": round(favor, 3)}}
    return None


def calcular_stop(ativo, lado, entrada, nivel, tecnica, rapido):
    """Stop "definido pelo preco": atras do nivel, nunca menor que o minimo nem maior que o teto do dia."""
    a, tick = ATIVOS[ativo], CONTRATOS[ativo]["tick"]
    teto = a.stop_teto_rapido_pts if rapido else a.stop_teto_pts
    if tecnica == "rompimento":
        dist = min(a.stop_rompimento_pts, teto)
    else:
        folga = a.folga_stop_pts * (2.0 if rapido else 1.0)
        atras = nivel - folga if lado == "C" else nivel + folga
        dist = min(max(abs(entrada - atras), a.stop_min_pts), teto)
    return arredondar(entrada - dist if lado == "C" else entrada + dist, tick)


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


def _fechar(estado, pos, preco_saida, ts, hora, motivo):
    ev = _evento_saida(estado, pos, pos.contratos, preco_saida, hora, motivo, True)
    estado.posicao, estado.ultima_saida_ts = None, ts
    estado.ultima_foi_perda = ev["pontos"] < 0
    return ev


def passo(estado: EstadoF, ts, hora, preco, fita, niveis, p: ParamFluxo, lote, pode_entrar=True, feed_ok=True, contexto=None):
    """Um tique. Devolve eventos: entrada, parcial, saida.

    Conducao da posicao, na ordem dele: stop; parcial com stop no preco de entrada; stop movel.
    `contexto`: {"medio", "var" (variacao do dia, em fracao), "spread" (em pontos)}.
    """
    a = ATIVOS[estado.ativo]
    tick = CONTRATOS[estado.ativo]["tick"]
    contexto = contexto or {}
    eventos = []
    pos = estado.posicao
    # os dois leitores que guardam memoria rodam sempre, com ou sem posicao
    mini = contexto.get("fita_volume")                      # a fita do mini: confirmacao e volume por preco
    sinal_perda = ler_perda(estado.ativo, estado, fita, ts, preco, niveis, p, mini)
    sinal_romp = ler_rompimento(estado.ativo, estado, fita, preco, niveis, p, contexto, mini)
    if pos is not None:
        a_mercado = preco - tick if pos.lado == "C" else preco + tick
        if hora[:5] >= p.hora_zerar:
            eventos.append(_fechar(estado, pos, a_mercado, ts, hora, "fim_do_dia"))
            return eventos
        bateu = preco <= pos.stop if pos.lado == "C" else preco >= pos.stop
        if bateu:
            base = min(preco, pos.stop) if pos.lado == "C" else max(preco, pos.stop)
            saida = base - tick if pos.lado == "C" else base + tick
            motivo = "stop" if not pos.parcial_feita else ("zero a zero" if abs(pos.stop - pos.entrada) < 1e-9 else "stop móvel")
            eventos.append(_fechar(estado, pos, saida, ts, hora, motivo))
            return eventos
        pos.melhor = max(pos.melhor, preco) if pos.lado == "C" else min(pos.melhor, preco)
        if pos.tempo_max_s and ts - pos.ts_entrada >= pos.tempo_max_s:
            eventos.append(_fechar(estado, pos, a_mercado, ts, hora, "tempo esgotado"))
            return eventos
        if pos.tecnica == "rompimento" and not pos.parcial_feita and ts - pos.ts_entrada >= p.tempo_rompimento_s \
                and _pontos(pos, pos.melhor) < a.gatilho_pts:
            eventos.append(_fechar(estado, pos, a_mercado, ts, hora, "não andou"))   # rompimento tem que romper
            return eventos
        if pos.alvo is not None and (preco >= pos.alvo if pos.lado == "C" else preco <= pos.alvo):
            eventos.append(_fechar(estado, pos, arredondar(pos.alvo, tick), ts, hora, "alvo"))   # ordem parada: sai no preco
            return eventos
        parcial_pts = pos.parcial_pts if pos.parcial_pts is not None else a.parcial_pts
        if not pos.sem_parcial and not pos.parcial_feita and _pontos(pos, preco) >= parcial_pts:
            metade = pos.contratos // 2
            alvo = pos.entrada + parcial_pts if pos.lado == "C" else pos.entrada - parcial_pts
            if metade >= 1:
                eventos.append(_evento_saida(estado, pos, metade, arredondar(alvo, tick), hora, "parcial", False))
                pos.contratos -= metade
            pos.parcial_feita = True
            pos.stop = pos.entrada                          # zero a zero
        if pos.parcial_feita and not pos.sem_arrasto:
            movel = pos.melhor - a.arrasto_pts if pos.lado == "C" else pos.melhor + a.arrasto_pts
            movel = arredondar(movel, tick)
            if (pos.lado == "C" and movel > pos.stop) or (pos.lado == "V" and movel < pos.stop):
                pos.stop = movel
        return eventos

    hm = hora[:5]
    if not (pode_entrar and feed_ok) or not (a.hora_inicio <= hm < p.hora_ultima_entrada):
        return eventos
    passa_pela_pausa = bool((contexto.get("sinal") or {}).get("ignora_pausa"))    # o setup do dado opera justamente ali
    if p.pausa_dado and p.pausa_dado[0] <= hm < p.pausa_dado[1] and not passa_pela_pausa:
        return eventos
    espera = p.espera_apos_perda_s if estado.ultima_foi_perda else p.espera_apos_saida_s
    if estado.operacoes >= p.max_operacoes or (ts - estado.ultima_saida_ts) < espera:
        return eventos
    spread = contexto.get("spread")
    if spread is not None and spread >= a.spread_max_pts - 1e-9:
        return eventos                                      # spread aberto: falta volume, ele nao entra
    de_fora = "sinal" in contexto                           # setup de grafico: o sinal vem pronto e a fita nao decide a entrada
    if de_fora:
        sinal = contexto["sinal"]
    else:
        sinal = ler_defesa(estado.ativo, fita, preco, niveis, p, mini) or sinal_perda or sinal_romp \
            or ler_exaustao(estado.ativo, estado, fita, preco, p, mini, contexto.get("var"))
    if sinal is None:
        return eventos
    lado = sinal["lado"]
    var = contexto.get("var")
    if not de_fora and var is not None and ((var >= p.variacao_um_lado and lado == "C") or (var <= -p.variacao_um_lado and lado == "V")):
        return eventos                                      # dia esticado: so opera contra o movimento
    rapido = dia_rapido(estado.ativo, fita)
    entrada = arredondar(preco + tick if lado == "C" else preco - tick, tick)
    if sinal.get("stop_pts"):
        stop = arredondar(entrada - sinal["stop_pts"] if lado == "C" else entrada + sinal["stop_pts"], tick)
    else:
        stop = calcular_stop(estado.ativo, lado, entrada, sinal["nivel"], sinal["tecnica"], rapido)
    n = max(1, int(lote))
    alvo = None
    if sinal.get("alvo_pts"):
        alvo = arredondar(entrada + sinal["alvo_pts"] if lado == "C" else entrada - sinal["alvo_pts"], tick)
    estado.posicao = PosicaoF(lado=lado, contratos=n, entrada=entrada, stop=stop, hora=hora, tecnica=sinal["tecnica"],
                              nivel=sinal["nivel"], nome_nivel=sinal["nome_nivel"], contratos_iniciais=n, melhor=entrada,
                              ts_entrada=ts, parcial_pts=sinal.get("parcial_pts"), alvo=alvo,
                              sem_arrasto=bool(sinal.get("sem_arrasto")), tempo_max_s=sinal.get("tempo_max_s"),
                              sem_parcial=bool(sinal.get("sem_parcial")))
    estado.operacoes += 1
    estado.perdas.pop(sinal["nome_nivel"], None)
    if sinal["tecnica"] == "exaustão":                      # conta quantas vezes ja operou contra este mesmo extremo
        feitas = estado.contras.get(sinal["sentido"]) or {}
        mesmo = abs((feitas.get("extremo") or 0.0) - sinal["nivel"]) <= a.zona_pts + 1e-9
        estado.contras[sinal["sentido"]] = {"extremo": sinal["nivel"], "n": (int(feitas.get("n") or 0) + 1) if mesmo else 1}
    eventos.append({"tipo": "entrada", "ativo": estado.ativo, "lado": lado, "contratos": n, "entrada": entrada,
                    "stop": stop, "hora": hora, "tecnica": sinal["tecnica"], "nivel": sinal["nivel"],
                    "nome_nivel": sinal["nome_nivel"], "medidas": dict(sinal["medidas"], dia_rapido=rapido)})
    return eventos


def zerar(estado: EstadoF, ts, hora, preco, motivo):
    pos = estado.posicao
    if pos is None:
        return None
    tick = CONTRATOS[estado.ativo]["tick"]
    return _fechar(estado, pos, preco - tick if pos.lado == "C" else preco + tick, ts, hora, motivo)


def _rs(v):
    return f"R$ {v:,.0f}".replace(",", ".")


def _n(v):
    return f"{v:g}".replace(".", ",")


def regras_em_texto(p: ParamFluxo):
    d, i = ATIVOS["WDOFUT"], ATIVOS["WINFUT"]
    parar = [f"com {_rs(p.perda_maxima_dia_rs)} de perda no dia", f"depois de {p.perdas_para_parar} negócios perdedores",
             f"ou quando devolve {p.devolucao_para:.0%} do lucro que o dia já teve"]
    if p.meta_dia_rs:
        parar.append(f"ou ao ganhar {_rs(p.meta_dia_rs)} (a sua meta)")
    return [
        "Leitura de fluxo: no dólar o robô lê os negócios do contrato cheio, sem os lotes de robô, e simula a ordem no mini. "
        "Só entra perto de um nível: ajuste, fechamento de ontem, abertura, máxima, mínima, preço médio do dia e a variação de 1%.",
        f"DEFESA: o nível foi testado {p.testes_min} ou {p.testes_max} vezes em {p.janela_defesa_s // 60} minutos, bateram nele com volume "
        f"({_n(p.mult_defesa)} vez o normal) e ele não cedeu. Entra de {_n(d.gatilho_pts)} a {_n(d.perseguir_pts)} pontos além do nível, "
        "quando quem agride é o lado que defendeu. Nunca no próprio nível.",
        "PERDA DE NÍVEL: não entra na primeira quebra. Espera o preço voltar ao nível, falhar e sair de novo (reteste), "
        "ou a agressão a favor crescer com lote de instituição.",
        f"ROMPIMENTO: máxima ou mínima do dia batida {p.testes_rompimento} vezes ou mais e rompida com fluxo, a favor do lado do dia. "
        f"Se em {p.tempo_rompimento_s // 60} minutos não andou, sai.",
        f"EXAUSTÃO (contra o movimento): só com o dia já esticado {p.variacao_contra:.0%}. O preço andou {_n(d.esticada_pts)} pontos ou mais "
        f"em {p.janela_esticada_s // 60} minutos ({_n(i.esticada_pts)} no índice), parou de renovar o extremo, recuou e a agressão virou. Entra contra, com o stop 1 ponto além "
        f"do extremo; no máximo {p.contras_por_extremo} vezes no mesmo extremo.",
        f"Stop atrás do nível: de {_n(d.stop_min_pts)} a {_n(d.stop_teto_pts)} pontos no mini-dólar ({_n(d.stop_teto_rapido_pts)} em dia que anda muito); "
        f"de {_n(i.stop_min_pts)} a {_n(i.stop_teto_pts)} no mini-índice.",
        f"Parcial: realiza metade com {_n(d.parcial_pts)} pontos (dólar) ou {_n(i.parcial_pts)} (índice) e leva o stop para o preço de entrada.",
        f"O resto segue com o stop {_n(d.arrasto_pts)} pontos (dólar) ou {_n(i.arrasto_pts)} (índice) atrás do melhor preço. Não há alvo fixo.",
        f"Lote: {p.lote_base} contratos; sobe {p.lote_por_degrau} a cada {_rs(p.colchao_por_degrau)} de lucro acumulado e desce quando o lucro "
        f"é devolvido (até {p.lote_maximo}).",
        "Para " + ", ".join(parar) + ".",
        f"Entradas: dólar a partir das {d.hora_inicio}, índice a partir das {i.hora_inicio}, até as {p.hora_ultima_entrada}; "
        f"nada entre {p.pausa_dado[0]} e {p.pausa_dado[1]} (dado das 9h30) nem com o spread aberto. Às {p.hora_zerar} zera tudo.",
        "Não copia o que depende de saber qual corretora está comprando ou vendendo: o MetaTrader não informa.",
        "Mini-índice: adaptação nossa. Ele opera a sala de dólar e mostra pouco índice.",
    ]
