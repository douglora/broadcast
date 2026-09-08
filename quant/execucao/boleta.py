"""
Boleta do dia (M13): a folha de ordens que o usuario executa NA MAO, e o modo seguro.

Por que existe: no estagio A do plano (paper trading e os primeiros 6 meses ao vivo) nao
ha robo nenhum. O sistema roda a noite, produz uma folha com ticker, lado, quantidade,
preco limite, validade, motivo e custo, e de manha o usuario digita isso na corretora em
10-15 minutos. A folha e o unico ponto de contato entre o modelo e o dinheiro de verdade,
entao ela tem uma propriedade que vale mais que todas as outras: ou esta certa, ou nao
existe. Uma boleta montada sobre o COTAHIST de anteontem seria executada com a mesma
confianca de uma boleta correta - o usuario nao tem como distinguir olhando - e por isso
o modo seguro nao emite boleta parcial, nao emite boleta com aviso, nao emite nada.

REGRAS DE OPERACAO (secao 5 do diagnostico-e-plano, "Execucao e corretora"), cada uma
virou uma constante deste arquivo com o motivo no comentario:
  - ordens SEMPRE limitadas ao mid do book, enviadas ~10:20 (HORA_ENVIO), validade dia;
  - reprecificar +0,2% a cada 2 horas (REPRECIFICACAO, HORAS_REPRECIFICACAO) - a boleta
    ja traz os precos reprecificados calculados, para o usuario nao fazer conta no celular;
  - nomes com ADTV < R$ 5 mi fatiados em 2-3 pregoes, cada fatia <= 1% do ADTV
    (ADTV_FATIAR, FATIAS_MAX, MAX_PARTICIPACAO);
  - NUNCA ordem a mercado em small cap: a boleta marca `iliquido` e o texto avisa;
  - leilao de fechamento so para o futuro de indice e para nomes acima de R$ 20 mi/dia
    (ADTV_LEILAO); nos demais o leilao e uma armadilha de spread;
  - compras so com caixa ja liquidado, D+2 (LIQUIDACAO): a venda de hoje NAO paga a compra
    de hoje. O que nao couber no caixa sai da boleta e o corte aparece em motivo_bloqueio.

O QUE E FATO E O QUE E DECISAO DESTE MODULO:
  - FATO (plano): os horarios, os percentuais e a liquidacao D+2 acima.
  - DECISAO: o mid arredonda A FAVOR DO CAIXA (compra arredonda o centavo para baixo,
    venda para cima). Um limite arredondado contra o caixa vira meio centavo de slippage
    sistematico em toda ordem.
  - DECISAO: book cruzado (bid > ask) ou mid distante mais de MAX_DESVIO_MID do fechamento
    e tratado como book podre e NAO vira preco: cai para o fechamento e marca a queda.
    Um mid inventado a partir de um book de 1 lote some dentro do preco e vira slippage
    escondido, que e exatamente o numero que o paper trading existe para medir.
  - DECISAO: sem ADTV conhecido a ordem e fatiada no maximo (FATIAS_MAX). Nao saber a
    liquidez tem que doer, como em quant/custos.py; o vies e sempre contra a estrategia.
  - DECISAO: quando o caixa nao cobre todas as compras, entram primeiro as MENORES, para
    caber o maior numero de ordens. O que fica de fora nao guarda estado: amanha a regra
    incremental de carteira.py enxerga a posicao ainda por montar e gera o resto sozinha.
  - DECISAO: `gate_passou=None` (desconhecido) BLOQUEIA. O padrao de um sistema que mexe
    em dinheiro nao pode ser "na duvida, opera".

ACHADO: O FATIAMENTO QUASE NUNCA DISPARA COM R$ 100 MIL.
  Uma posicao de 4,5% de um patrimonio de R$ 100 mil e R$ 4.500; 1% do ADTV de um nome de
  R$ 5 mi/dia e R$ 50.000. A ordem e onze vezes menor que o teto de participacao, entao
  MAX_PARTICIPACAO so morde com ADTV abaixo de ~R$ 450 mil/dia (fora do universo) ou com
  patrimonio dez vezes maior. A regra fica implementada e testada porque custa nada e o
  capital cresce, mas quem ler o relatorio de execucao nao deve concluir que "o fatiamento
  esta funcionando": ele nao esta sendo exercitado. O que de fato protege o preco no
  tamanho atual e o limite no mid, nao o fatiamento.

ACHADO: O FATIAMENTO NAO TEM MEMORIA, E ISSO E DE PROPOSITO.
  A boleta emite a PRIMEIRA fatia e esquece o resto. Nao ha fila de fatias pendentes em
  disco. Amanha o ciclo inteiro roda de novo, a posicao aparece parcialmente montada e
  ordens_incrementais() gera o restante - ja com o preco de amanha e ja passando pelos
  filtros de custo. Uma fila persistida executaria fatia 2/3 de uma decisao que o modelo
  talvez ja tenha revogado.

SUPOSICOES QUE PRECISAM DE FONTE REAL (ver quant/docs/validar-com-fonte-real.md):
  - que a corretora aceita ordem limitada com validade dia em acao e em fracionario sem
    plano pago (o plano diz que so WIN/WDO foi verificado);
  - o horario exato do leilao de fechamento e se o limite sobrevive ao leilao;
  - se ha minimo de corretagem por nota que torne a fatia pequena antieconomica.

Uso:
    python3 -m quant.execucao.boleta --capital 100000 --caixa 26000 --gate-aprovado
"""
import argparse
import math
import os
import sys
from datetime import date, datetime

import numpy as np
import pandas as pd

from quant import custos as cst
from quant.comum import DIR_BRUTOS, DIR_SAIDA, garantir_dir, gravar_json, ler_json, log
from quant.dados import calendario

HORA_ENVIO = "10:20"          # plano: ordens enviadas ~10:20, ja passado o ruido da abertura
REPRECIFICACAO = 0.002        # plano: +0,2% a cada 2 horas, na direcao que executa
HORAS_REPRECIFICACAO = 2
MAX_PARTICIPACAO = 0.01       # cada fatia vale no maximo 1% do ADTV
ADTV_FATIAR = 5_000_000.0     # abaixo disso a ordem e dividida em 2 ou 3 pregoes
FATIAS_MAX = 3
ADTV_LEILAO = 20_000_000.0    # leilao de fechamento so acima disso
DIAS_FRESCOR = 1              # o COTAHIST e o BDI tem de ser do ultimo pregao
LIQUIDACAO = 2                # D+2: a venda de hoje nao paga a compra de hoje

VALIDADE = "dia"              # plano: nada de ordem que sobrevive ao pregao
INICIO_LEILAO = "16:55"       # pregao continuo 10:00-16:55, leilao 16:55-17:00
LOTE = 100                    # lote padrao da B3; fatia alinhada ao lote evita cair no fracionario
MAX_DESVIO_MID = 0.20         # mid a mais de 20% do fechamento e book podre, nao preco
CENTAVO = 0.01
BPS = 10_000.0

# Tolerancia de atraso por fonte, em PREGOES. COTAHIST e BDI sao diarios e mandam na
# decisao do dia; sinais e mensal (o rebalanceamento e mensal, entao um mes de idade e
# normal); o CDI so alimenta o comparativo do relatorio e atrasa por conta do BCB.
TOLERANCIA_FRESCOR = {"cotahist": DIAS_FRESCOR, "bdi": DIAS_FRESCOR, "sinais": 30, "cdi": 5}
FONTES = ("cotahist", "bdi", "sinais", "cdi")
FONTES_OBRIGATORIAS = ("cotahist", "bdi", "sinais")   # sem uma destas nao ha boleta
MOTIVOS_HEDGE_ORDEM = ("abertura", "roll", "tamanho")  # o que vira ordem de WIN na folha

CAMPOS_ORDEM = ["ticker", "lado", "qtd", "preco_limite", "validade", "motivo", "custo",
                "fatia", "adtv", "fracionario", "origem_preco", "iliquido", "leilao",
                "financeiro", "limite_reprecificado"]
LADOS = ("C", "V")


# ─────────────────────────────────────────────────────────────
# Numeros e datas tolerantes (puras)
# ─────────────────────────────────────────────────────────────
def _num(x, padrao=float("nan")):
    """float(x) sem levantar: None, texto ilegivel ou colecao viram `padrao`."""
    if x is None or isinstance(x, (list, tuple, dict, set)):
        return padrao
    try:
        v = float(x)
    except (TypeError, ValueError):
        return padrao
    return v


def _positivo(x):
    """True so para numero finito e maior que zero (NaN e None sao False)."""
    v = _num(x)
    return bool(math.isfinite(v) and v > 0)


def _json(x):
    """Converte para tipo JSON nativo: NaN/inf viram None (o painel nao aceita NaN).

    Inteiro continua inteiro: quantidade de acoes e de contratos e numero inteiro, e
    "300.0 acoes" numa boleta lida as pressas e um convite a erro de digitacao.
    """
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        v = float(x)
        return v if math.isfinite(v) else None
    return x


def _data(d):
    """Qualquer coisa parecida com data -> datetime.date. Devolve None se nao der."""
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    try:
        return datetime.strptime(str(d)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        try:
            return pd.Timestamp(d).date()
        except Exception:
            return None


def _iso(d):
    x = _data(d)
    return x.isoformat() if x is not None else None


def _reais(v):
    """1234.5 -> '1.234,50' (a boleta e lida por humano brasileiro no celular)."""
    x = _num(v)
    if not math.isfinite(x):
        return "-"
    return f"{x:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


# ─────────────────────────────────────────────────────────────
# Preco limite e reprecificacao
# ─────────────────────────────────────────────────────────────
def _arredondar(preco, lado):
    """Arredonda ao centavo A FAVOR DO CAIXA: compra para baixo, venda para cima.

    Meio centavo em toda ordem e slippage sistematico; o vies do arredondamento tem de
    ser sempre a favor de quem paga.
    """
    if not _positivo(preco):
        return float("nan")
    passos = float(preco) / CENTAVO
    n = math.floor(passos + 1e-9) if lado == "C" else math.ceil(passos - 1e-9)
    return round(n * CENTAVO, 2)


def preco_limite(bid, ask, fec, lado, folga=0.0):
    """Preco limite da ordem: o mid do book. Devolve (preco, origem).

    origem e 'mid', 'fechamento' ou 'sem_preco', e existe porque a queda para o fechamento
    PRECISA aparecer na boleta e no relatorio de slippage. Se bid ou ask vierem zerados ou
    ausentes - o que e comum justamente nos iliquidos que a estrategia carrega - um mid
    inventado vira slippage escondido dentro do preco, e o paper trading passa a medir a
    propria invencao. Tambem cai para o fechamento quando o book esta cruzado (bid > ask)
    ou quando o mid esta a mais de MAX_DESVIO_MID do fechamento: book de um lote so.

    `folga` afasta o limite na direcao que executa (compra paga mais, venda recebe menos);
    e o mesmo mecanismo da reprecificacao das 12:20. O arredondamento ao centavo e sempre
    a favor do caixa. Sem book e sem fechamento devolve (nan, 'sem_preco') - nunca levanta.
    """
    lado = "C" if str(lado).upper().startswith("C") else "V"
    b, a, f = _num(bid), _num(ask), _num(fec)
    origem = "sem_preco"
    preco = float("nan")
    if _positivo(b) and _positivo(a) and a >= b:
        mid = (b + a) / 2.0
        distante = _positivo(f) and abs(mid - f) / f > float(MAX_DESVIO_MID)
        if not distante:
            preco, origem = mid, "mid"
    if origem != "mid" and _positivo(f):
        preco, origem = f, "fechamento"
    if not _positivo(preco):
        return float("nan"), "sem_preco"
    g = _num(folga, 0.0)
    g = g if math.isfinite(g) else 0.0
    preco = preco * (1.0 + g) if lado == "C" else preco * (1.0 - g)
    return _arredondar(preco, lado), origem


def reprecificar(preco, lado, passos=1, passo=REPRECIFICACAO):
    """Preco depois de `passos` reprecificacoes de `passo` na direcao que executa."""
    if not _positivo(preco):
        return float("nan")
    lado = "C" if str(lado).upper().startswith("C") else "V"
    n = max(int(passos), 0)
    fator = (1.0 + float(passo)) ** n if lado == "C" else (1.0 - float(passo)) ** n
    return _arredondar(float(preco) * fator, lado)


def _somar_horas(hora, horas):
    """'10:20' + 2 -> '12:20'. Devolve None quando passa do fim do pregao continuo."""
    try:
        h, m = (int(x) for x in str(hora).split(":")[:2])
    except (ValueError, TypeError):
        return None
    total = h * 60 + m + int(round(float(horas) * 60))
    nova = f"{total // 60:02d}:{total % 60:02d}"
    return nova if nova < INICIO_LEILAO else None


def agenda_reprecificacao(hora_envio=HORA_ENVIO, horas=HORAS_REPRECIFICACAO,
                          passo=REPRECIFICACAO, maximo=4):
    """[(hora, passos)] das reprecificacoes que ainda cabem no pregao continuo.

    Com os defaults: 12:20 (1 passo, +0,2%) e 14:20 (2 passos, +0,4%). Depois das 16:55 e
    leilao, e leilao so vale para os nomes acima de ADTV_LEILAO - nao se reprecifica para
    dentro dele.
    """
    out, hora = [], hora_envio
    for passos in range(1, int(maximo) + 1):
        hora = _somar_horas(hora, horas)
        if hora is None:
            break
        out.append((hora, passos))
    return out


# ─────────────────────────────────────────────────────────────
# Fatiamento
# ─────────────────────────────────────────────────────────────
def _repartir(qtd, n):
    """Divide `qtd` inteiro em `n` partes o mais iguais possiveis; a soma e exata."""
    n = max(int(n), 1)
    base, resto = divmod(int(qtd), n)
    return [base + 1 if i < resto else base for i in range(n)]


def fatiar(qtd, adtv, preco, max_participacao=MAX_PARTICIPACAO, fatias_max=FATIAS_MAX,
           lote=None):
    """Divide a ordem em ate `fatias_max` pregoes quando ela passa de `max_participacao`
    do ADTV. Devolve a lista de quantidades, cuja soma e SEMPRE a quantidade original.

    A conta e em ACOES, nao em reais: qmax = floor(max_participacao x adtv / preco) e o
    numero de acoes que cabe num pregao, e n = ceil(qtd / qmax). Fazer em reais e depois
    converter deixaria a ultima fatia um centavo acima do teto.

    ADTV ou preco desconhecidos devolvem `fatias_max` fatias: nao saber a liquidez custa
    caro por padrao (mesma politica de quant/custos.py). Quando nem `fatias_max` fatias
    cabem no teto, devolve `fatias_max` mesmo assim - o teto e o alvo, nao uma promessa;
    quem chama registra a violacao (gerar() poe em `avisos`).

    `lote` alinha as fatias ao lote padrao quando a quantidade e multipla dele, para nao
    transformar 300 acoes em duas ordens de 150 que caem metade no livro fracionario.
    """
    q = int(_num(qtd, 0.0)) if math.isfinite(_num(qtd, float("nan"))) else 0
    if q <= 0:
        return []
    nmax = max(int(fatias_max), 1)
    part = _num(max_participacao, 0.0)
    if not _positivo(adtv) or not _positivo(preco) or not (math.isfinite(part) and part > 0):
        return _repartir(q, nmax)                      # liquidez desconhecida: fatia no maximo
    qmax = int(math.floor(float(part) * float(adtv) / float(preco)))
    if qmax <= 0:
        return _repartir(q, nmax)
    if q <= qmax:
        return [q]
    n = min(int(math.ceil(q / qmax)), nmax)
    if lote and int(lote) > 1 and q % int(lote) == 0:
        lotes = _repartir(q // int(lote), n)
        return [x * int(lote) for x in lotes]
    return _repartir(q, n)


def participacao(qtd, adtv, preco):
    """Fracao do ADTV que a ordem representa. NaN quando a liquidez e desconhecida."""
    if not _positivo(adtv) or not _positivo(preco) or not _positivo(qtd):
        return float("nan")
    return float(qtd) * float(preco) / float(adtv)


# ─────────────────────────────────────────────────────────────
# Frescor dos dados e modo seguro
# ─────────────────────────────────────────────────────────────
def dias_pregao(de, ate):
    """Pregoes de atraso entre `de` e `ate` (0 = mesmo pregao). None se a data nao parseia.

    Conta em PREGOES, nao em dias corridos: numa segunda-feira o COTAHIST de sexta tem 1
    pregao de atraso, nao 3 dias, e bloquear a boleta por causa do fim de semana seria
    bloquear toda segunda-feira.
    """
    d0, d1 = _data(de), _data(ate)
    if d0 is None or d1 is None:
        return None
    d0, d1 = calendario.ultimo_pregao_ate(d0), calendario.ultimo_pregao_ate(d1)
    if d0 >= d1:
        return 0
    return max(len(calendario.pregoes(d0, d1)) - 1, 0)


def _liquidacao(data, dias=LIQUIDACAO):
    """Data em que a compra de hoje liquida (D+2 em PREGOES). None se a data nao parseia."""
    d = _data(data)
    if d is None:
        return None
    for _ in range(max(int(dias), 0)):
        d = calendario.proximo_pregao(d)
    return d


def frescor(hoje, cotahist=None, bdi=None, sinais=None, cdi=None,
            tolerancia=None):
    """Idade de cada fonte, no formato do bloco `frescor` de docs/painel-contrato.md.

    Devolve {fonte: {"data": "AAAA-MM-DD"|None, "dias_atras": int|None, "ok": bool}}.
    Fonte ausente entra com data None, dias_atras None e ok False - ausencia nunca vira
    silencio, ela vira bloqueio la em modo_seguro().
    """
    tol = dict(TOLERANCIA_FRESCOR if tolerancia is None else tolerancia)
    valores = {"cotahist": cotahist, "bdi": bdi, "sinais": sinais, "cdi": cdi}
    out = {}
    for fonte in FONTES:
        d = _data(valores.get(fonte))
        if d is None:
            out[fonte] = {"data": None, "dias_atras": None, "ok": False}
            continue
        atraso = dias_pregao(d, hoje)
        limite = int(tol.get(fonte, DIAS_FRESCOR))
        out[fonte] = {"data": d.isoformat(),
                      "dias_atras": None if atraso is None else int(atraso),
                      "ok": bool(atraso is not None and atraso <= limite)}
    return out


def modo_seguro(frescor, gate_passou=None, obrigatorias=FONTES_OBRIGATORIAS,
                tolerancia=None):
    """(ativo, motivos). ATIVO significa BLOQUEADO: nao sai boleta nenhuma.

    Bloqueia quando falta qualquer fonte obrigatoria, quando uma delas esta atrasada
    (COTAHIST do ultimo pregao inclusive) ou quando o gate da fase 1 nao foi aprovado.
    `gate_passou=None` - desconhecido - TAMBEM bloqueia: um sistema que mexe em dinheiro
    nao pode ter "na duvida, opera" como padrao, e a estrategia so vale enquanto a
    replicacao dos fatores do NEFIN passa.
    """
    tol = dict(TOLERANCIA_FRESCOR if tolerancia is None else tolerancia)
    fr = frescor if isinstance(frescor, dict) else {}
    motivos = []
    for fonte in obrigatorias:
        info = fr.get(fonte)
        nome = fonte.upper()
        if not isinstance(info, dict) or info.get("data") is None:
            motivos.append(f"{nome} ausente: nao ha dado do ultimo pregao")
            continue
        if not bool(info.get("ok")):
            atraso = info.get("dias_atras")
            limite = int(tol.get(fonte, DIAS_FRESCOR))
            quanto = "idade desconhecida" if atraso is None else f"{int(atraso)} pregoes de atraso"
            motivos.append(f"{nome} desatualizado ({quanto}; limite {limite})")
    if gate_passou is None:
        motivos.append("gate da fase 1 nao verificado (desconhecido bloqueia por padrao)")
    elif not bool(gate_passou):
        motivos.append("gate da fase 1 nao aprovado")
    return bool(motivos), motivos


# ─────────────────────────────────────────────────────────────
# Geracao da boleta
# ─────────────────────────────────────────────────────────────
def _linhas(ordens):
    """DataFrame/lista de ordens (carteira.COLUNAS_ORDEM) -> lista de dicts saneada."""
    if ordens is None:
        return []
    if isinstance(ordens, pd.DataFrame):
        registros = ordens.to_dict("records") if len(ordens) else []
    elif isinstance(ordens, dict):
        registros = [ordens]
    else:
        registros = list(ordens)
    out = []
    for r in registros:
        if not isinstance(r, dict):
            continue
        t = str(r.get("ticker", "")).strip().upper()
        qtd = _num(r.get("qtd"), 0.0)
        if not t or not math.isfinite(qtd) or int(qtd) <= 0:
            continue
        lado = "C" if str(r.get("lado", "C")).upper().startswith("C") else "V"
        out.append({"ticker": t, "lado": lado, "qtd": int(qtd),
                    "motivo": str(r.get("motivo", "") or "ajuste"),
                    "fracionario": bool(r.get("fracionario", False)),
                    "preco": _num(r.get("preco")), "valor": _num(r.get("valor"))})
    return out


def _book_do(book, ticker):
    """(bid, ask) do book do ticker, aceitando dict de dicts ou dict de tuplas."""
    if not isinstance(book, dict):
        return float("nan"), float("nan")
    b = book.get(ticker)
    if isinstance(b, dict):
        return _num(b.get("bid")), _num(b.get("ask"))
    if isinstance(b, (list, tuple)) and len(b) >= 2:
        return _num(b[0]), _num(b[1])
    return float("nan"), float("nan")


def _custo_hedge(hedge):
    """Custo estimado do ajuste de hedge. Roll e dois lados (fecha e abre)."""
    if not isinstance(hedge, dict):
        return 0.0
    motivo = str(hedge.get("motivo", "manter"))
    if motivo not in MOTIVOS_HEDGE_ORDEM:
        return 0.0
    contratos = _num(hedge.get("contratos"), 0.0)
    if not math.isfinite(contratos) or contratos == 0:
        return 0.0
    lados = 2 if motivo == "roll" else 1
    return float(cst.custo_win(abs(contratos))["total"]) * lados


def gerar(ordens, precos, adtv, data, frescor_dados=None, gate_passou=None,
          book=None, caixa_disponivel=None, hedge=None, estresse=1.0):
    """Boleta do dia, no formato do bloco `boleta` de docs/painel-contrato.md.

    Devolve dict com data, id, emitida, motivo_bloqueio, custo_total e ordens[], mais os
    campos de apoio que o texto e o painel usam (hora_envio, reprecificacao, frescor,
    modo_seguro, caixa, hedge, avisos). Tudo em tipo JSON nativo: nada de NaN, que
    quebraria o jsonify do terminal.

    Com MODO SEGURO ATIVO devolve emitida=False e ordens VAZIA. Nao existe boleta parcial:
    uma folha com metade das ordens seria executada com a mesma confianca de uma folha
    inteira, e o usuario nao tem como saber qual metade faltou.

    As compras entram ate o caixa JA LIQUIDADO (`caixa_disponivel`, D+2); as menores
    primeiro, para caber o maior numero de ordens. O que nao couber sai da boleta e o
    corte aparece em `motivo_bloqueio`, com nome e valor. `caixa_disponivel=None` significa
    "nao informado": nada e cortado e um aviso diz isso com todas as letras.
    """
    d_iso = _iso(data) or _iso(date.today())
    fr = dict(frescor_dados) if isinstance(frescor_dados, dict) else {}
    ativo, motivos = modo_seguro(fr, gate_passou)
    agenda = agenda_reprecificacao()
    boleta = {
        "data": d_iso,
        "id": (d_iso or "").replace("-", ""),
        "emitida": not ativo,
        "motivo_bloqueio": list(motivos),
        "custo_total": 0.0,
        "ordens": [],
        "hora_envio": HORA_ENVIO,
        "validade": VALIDADE,
        "reprecificacao": {"passo": REPRECIFICACAO, "horas": HORAS_REPRECIFICACAO,
                           "horarios": [h for h, _ in agenda]},
        "liquidacao": {"dias": LIQUIDACAO, "data": _iso(_liquidacao(d_iso))},
        "modo_seguro": {"ativo": bool(ativo), "motivos": list(motivos)},
        "frescor": fr,
        "gate_fase1": {"passou": None if gate_passou is None else bool(gate_passou)},
        "caixa": {"disponivel": _json(caixa_disponivel), "usado": 0.0, "sobra": _json(caixa_disponivel)},
        "hedge": None,
        "avisos": [],
    }
    if ativo:
        return boleta                                   # nao existe boleta parcial

    precos = precos or {}
    adtv = adtv or {}
    candidatas, avisos = [], []
    for linha in _linhas(ordens):
        t, lado = linha["ticker"], linha["lado"]
        fec = _num(precos.get(t), linha["preco"])
        bid, ask = _book_do(book, t)
        limite, origem = preco_limite(bid, ask, fec, lado)
        if not _positivo(limite):
            boleta["motivo_bloqueio"].append(
                f"{t}: sem preco de referencia (book e fechamento ausentes); fora da boleta")
            continue
        a = _num(adtv.get(t))
        fatias = fatiar(linha["qtd"], a, limite, lote=None if linha["fracionario"] else LOTE)
        qtd = int(fatias[0]) if fatias else 0
        if qtd <= 0:
            continue
        if len(fatias) > 1 and participacao(qtd, a, limite) > MAX_PARTICIPACAO + 1e-12:
            avisos.append(f"{t}: mesmo em {len(fatias)} fatias a ordem passa de "
                          f"{MAX_PARTICIPACAO:.0%} do ADTV")
        financeiro = qtd * limite
        custo = cst.custo_ordem(financeiro, a, fracionario=linha["fracionario"],
                                estresse=estresse)["total"]
        iliquido = not _positivo(a) or float(a) < ADTV_FATIAR
        candidatas.append({
            "ticker": t, "lado": lado, "qtd": qtd, "preco_limite": float(limite),
            "validade": VALIDADE, "motivo": linha["motivo"], "custo": float(custo),
            "fatia": f"1/{len(fatias)}", "adtv": _json(a),
            "fracionario": bool(linha["fracionario"]), "origem_preco": origem,
            "iliquido": bool(iliquido),
            "leilao": bool(_positivo(a) and float(a) >= ADTV_LEILAO),
            "financeiro": float(financeiro),
            "limite_reprecificado": [
                {"hora": h, "preco": _json(reprecificar(limite, lado, passos))}
                for h, passos in agenda],
        })
        if origem == "fechamento":
            avisos.append(f"{t}: book ausente ou inconsistente; limite no fechamento")

    vendas = [o for o in candidatas if o["lado"] == "V"]
    compras = sorted([o for o in candidatas if o["lado"] == "C"],
                     key=lambda o: (o["financeiro"] + o["custo"], o["ticker"]))
    caixa = _num(caixa_disponivel)
    aceitas, usado = list(vendas), 0.0
    if not math.isfinite(caixa):
        aceitas += compras
        if compras:
            avisos.append("caixa liquidado nao informado: as compras nao foram limitadas")
    else:
        for o in compras:
            necessario = o["financeiro"] + o["custo"]
            if usado + necessario <= caixa + 1e-9:
                aceitas.append(o)
                usado += necessario
            else:
                boleta["motivo_bloqueio"].append(
                    f"{o['ticker']}: compra de R$ {_reais(o['financeiro'])} fora do caixa "
                    f"liquidado em D+{LIQUIDACAO} (disponivel R$ {_reais(max(caixa - usado, 0.0))})")
    # Vendas primeiro: sao elas que geram o caixa (ainda que so em D+2) e sao as ordens que
    # o usuario nao pode deixar de executar se o tempo da manha acabar.
    aceitas.sort(key=lambda o: (0 if o["lado"] == "V" else 1, o["ticker"]))
    custo_hedge = _custo_hedge(hedge)
    boleta["ordens"] = [{k: _json(v) for k, v in o.items()} for o in aceitas]
    boleta["custo_total"] = float(sum(o["custo"] for o in aceitas) + custo_hedge)
    boleta["caixa"] = {"disponivel": _json(caixa), "usado": float(usado),
                       "sobra": _json(caixa - usado if math.isfinite(caixa) else float("nan"))}
    if isinstance(hedge, dict):
        boleta["hedge"] = {"contratos": _json(hedge.get("contratos")),
                           "vencimento": _iso(hedge.get("vencimento")),
                           "motivo": str(hedge.get("motivo", "manter")),
                           "custo": float(custo_hedge),
                           "leilao": True}      # o futuro de indice pode ir ao leilao
    boleta["avisos"] = avisos
    return boleta


# ─────────────────────────────────────────────────────────────
# Texto para o celular
# ─────────────────────────────────────────────────────────────
def para_texto(boleta):
    """A boleta legivel que o usuario le no celular de manha, sem depender do painel.

    Uma ordem por bloco: lado, ticker, quantidade, preco limite e os precos ja
    reprecificados. Boleta bloqueada imprime os motivos e NENHUMA ordem.
    """
    if not isinstance(boleta, dict):
        return "BOLETA INVALIDA"
    linhas = []
    cab = f"BOLETA {boleta.get('data')} (id {boleta.get('id')})"
    if not boleta.get("emitida", False):
        linhas.append(cab + " - NAO EMITIDA")
        linhas.append("MODO SEGURO ATIVO: nenhuma ordem hoje. Motivos:")
        for m in boleta.get("motivo_bloqueio", []) or ["(sem motivo registrado)"]:
            linhas.append(f"  - {m}")
        linhas.append("Nao execute nada por conta propria: dado velho vira ordem errada.")
        return "\n".join(linhas)
    ordens = boleta.get("ordens", []) or []
    linhas.append(f"{cab} - {len(ordens)} ordem(ns) - custo estimado "
                  f"R$ {_reais(boleta.get('custo_total', 0.0))}")
    rep = boleta.get("reprecificacao", {}) or {}
    passo = f"{float(rep.get('passo', REPRECIFICACAO)):.1%}".replace(".", ",")
    linhas.append(f"enviar as {boleta.get('hora_envio', HORA_ENVIO)}, limite no mid, "
                  f"validade {boleta.get('validade', VALIDADE)}; reprecificar {passo} a cada "
                  f"{rep.get('horas', HORAS_REPRECIFICACAO)}h "
                  f"({', '.join(rep.get('horarios', [])) or 'sem reprecificacao'})")
    liq = boleta.get("liquidacao", {}) or {}
    linhas.append(f"compras liquidam em D+{liq.get('dias', LIQUIDACAO)} ({liq.get('data')})")
    if not ordens:
        linhas.append("")
        linhas.append("Nada a executar hoje: a carteira ja esta no alvo.")
    for i, o in enumerate(ordens, 1):
        lado = "COMPRA" if str(o.get("lado")) == "C" else "VENDA "
        linhas.append("")
        linhas.append(f"{i:>2}. {lado} {o.get('ticker')}  {o.get('qtd')} @ "
                      f"R$ {_reais(o.get('preco_limite'))}  ({o.get('origem_preco')}, "
                      f"fatia {o.get('fatia')}, {o.get('motivo')}, custo R$ {_reais(o.get('custo'))})")
        rp = o.get("limite_reprecificado") or []
        if rp:
            linhas.append("    reprecificar: " + " | ".join(
                f"{r.get('hora')} R$ {_reais(r.get('preco'))}" for r in rp))
        marcas = []
        if o.get("fracionario"):
            marcas.append("FRACIONARIO (livro raso, spread maior)")
        if o.get("iliquido"):
            marcas.append("ILIQUIDO: nunca a mercado")
        marcas.append("pode ir ao leilao de fechamento" if o.get("leilao")
                      else "NAO usar o leilao de fechamento")
        linhas.append("    " + " | ".join(marcas))
    h = boleta.get("hedge")
    if isinstance(h, dict) and str(h.get("motivo")) in MOTIVOS_HEDGE_ORDEM:
        linhas.append("")
        linhas.append(f"HEDGE: {h.get('motivo')} para {h.get('contratos')} contrato(s) de WIN, "
                      f"vencimento {h.get('vencimento')} (custo R$ {_reais(h.get('custo', 0.0))})")
    for a in boleta.get("avisos", []) or []:
        linhas.append(f"aviso: {a}")
    for m in boleta.get("motivo_bloqueio", []) or []:
        linhas.append(f"cortado: {m}")
    return "\n".join(linhas)


# ─────────────────────────────────────────────────────────────
# Disco
# ─────────────────────────────────────────────────────────────
def caminho(data, dir_saida=None):
    """quant/saida/boletas_AAAAMMDD.json (DIR_SAIDA e gitignored: a boleta e dado pessoal)."""
    d = _iso(data) or _iso(date.today())
    return os.path.join(dir_saida or DIR_SAIDA, f"boletas_{d.replace('-', '')}.json")


def gravar(boleta, dir_saida=None):
    """Grava a boleta (atomico, via comum.gravar_json) e devolve o caminho."""
    alvo = caminho(boleta.get("data") if isinstance(boleta, dict) else None, dir_saida)
    garantir_dir(os.path.dirname(alvo))
    gravar_json(alvo, boleta)
    return alvo


def carregar(data, dir_saida=None):
    """Le a boleta do dia. Devolve None se o arquivo nao existe (nao levanta)."""
    return ler_json(caminho(data, dir_saida), None)


def registrar(boleta, caminho=None):
    """Escreve as ordens da boleta no livro de ordens (quant/execucao/livro_ordens.py).

    Importado tarde de proposito (idioma do replica_nefin.rodar_gate): este modulo tem de
    importar e rodar mesmo enquanto o livro nao existe. Sem o livro, devolve None e loga -
    perder o registro e ruim, mas nao emitir a boleta por causa dele seria pior.
    """
    if not isinstance(boleta, dict) or not boleta.get("ordens"):
        return None
    try:
        from quant.execucao import livro_ordens as lo
    except Exception as e:                          # noqa: BLE001 - o livro pode nem existir
        log(f"livro de ordens indisponivel ({type(e).__name__}); boleta nao registrada")
        return None
    linhas = []
    for o in boleta["ordens"]:
        linhas.append({"data": boleta.get("data"), "boleta": boleta.get("id"),
                       "ticker": o.get("ticker"), "lado": o.get("lado"), "qtd": o.get("qtd"),
                       "preco_limite": o.get("preco_limite"), "validade": o.get("validade"),
                       "motivo": o.get("motivo"), "custo_estimado": o.get("custo"),
                       "fatia": o.get("fatia"), "fracionario": o.get("fracionario"),
                       "status": "emitida"})
    df = pd.DataFrame(linhas, columns=lo.COLUNAS_ORDEM)
    extra = {"caminho": caminho} if caminho else {}
    return lo.registrar_ordens(df, boleta.get("data"), boleta.get("id"), **extra)


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────
def _ultima_data_bdi(dir_brutos=None):
    """Ultima pasta datada em dados_brutos/bdi/. O arquivador grava uma por pregao."""
    pasta = os.path.join(dir_brutos or DIR_BRUTOS, "bdi")
    try:
        datas = [_data(n) for n in os.listdir(pasta)]
    except OSError:
        return None
    validas = [d for d in datas if d is not None]
    return max(validas) if validas else None


def _ultima_data_cotahist(hoje):
    """Ultima data do parquet do COTAHIST do ano corrente (le so a coluna `data`)."""
    try:
        from quant.dados import cotahist
        p = cotahist.caminho_parquet(_data(hoje).year)
        if not os.path.exists(p):
            return None
        d = pd.read_parquet(p, columns=["data"])
        return pd.to_datetime(d["data"]).max().date() if len(d) else None
    except Exception as e:                          # noqa: BLE001 - CLI nao pode derrubar
        log(f"COTAHIST indisponivel: {type(e).__name__}")
        return None


def _frescor_do_banco(hoje):
    """Data mais recente de cada fonte no banco. Fonte que nao carrega vira None (= bloqueio)."""
    datas = {"cotahist": _ultima_data_cotahist(hoje), "bdi": _ultima_data_bdi(),
             "sinais": None, "cdi": None}
    try:
        from quant import sinais as sg
        s = sg.carregar()
        if s is not None and len(s):
            datas["sinais"] = pd.to_datetime(s["data"]).max().date()
    except Exception as e:                          # noqa: BLE001
        log(f"sinais indisponiveis: {type(e).__name__}")
    try:
        from quant.dados import cdi
        c = cdi.carregar(permitir_rede=False)       # frescor nao vai a rede: mede o banco
        if c is not None and len(c):
            datas["cdi"] = pd.Timestamp(c.index.max()).date()
    except Exception as e:                          # noqa: BLE001
        log(f"CDI indisponivel: {type(e).__name__}")
    return frescor(hoje, **datas)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Boleta do dia (M13): a folha que se executa na mao")
    ap.add_argument("--data", default=None, help="pregao da boleta (padrao: ultimo pregao ate hoje)")
    ap.add_argument("--capital", type=float, default=100_000.0)
    ap.add_argument("--caixa", type=float, default=None,
                    help="caixa JA LIQUIDADO em D+2; sem isto as compras nao sao limitadas")
    ap.add_argument("--gate-aprovado", action="store_true",
                    help="declara que o gate da fase 1 passou; sem isto a boleta e bloqueada")
    ap.add_argument("--nao-gravar", action="store_true")
    args = ap.parse_args(argv)

    from quant import carteira as ct
    from quant import sinais as sg
    d = calendario.ultimo_pregao_ate(args.data or date.today())
    s = sg.carregar()
    if s is None or len(s) == 0:
        print("sem sinais no banco; rode python3 -m quant.sinais")
        return 2
    mes = sg.em(s, pd.Timestamp(d))
    precos = mes.set_index("ticker")["preco"].to_dict()
    adtvs = mes.set_index("ticker")["adtv21"].to_dict()
    setor = mes.set_index("ticker")["setor"].to_dict()
    r = ct.carteira_alvo(mes, ct.estado_inicial(args.capital, d), precos, adtv=adtvs,
                         setor=setor, patrimonio=args.capital, data=d)
    b = gerar(r["ordens"], precos, adtvs, d,
              frescor_dados=_frescor_do_banco(d),
              gate_passou=True if args.gate_aprovado else None,
              caixa_disponivel=args.caixa, hedge=r["hedge"])
    print(para_texto(b))
    if not args.nao_gravar:
        alvo = gravar(b)
        registrar(b)
        print(f"\ngravado em {alvo}")
    return 0 if b["emitida"] else 1


if __name__ == "__main__":
    sys.exit(main())
