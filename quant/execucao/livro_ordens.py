"""
Livro de ordens e de execucoes (M13): o que foi MANDADO e o que foi FEITO.

Por que existe: este e o unico registro de que a carteira real existe. O backtest e
opiniao e a boleta e intencao; o fill e fato. A posicao real, o preco medio de cada nome e,
por consequencia, o imposto devido saem todos daqui - errar ou perder este arquivo custa
dinheiro de verdade. Por isso o modulo e paranoico em tres pontos: (1) nunca levanta por
arquivo ausente, vazio ou ilegivel (devolve o esquema vazio, para o painel nunca ficar sem
resposta); (2) grava com gravar_atomico, entao nunca existe CSV pela metade; e (3) e
RECONSTRUTIVEL - posicao(), operacoes() e resumo() sao funcoes puras dos fills, sem estado
escondido nem acumulador em disco, entao recomputar da sempre exatamente o mesmo numero.

Dois arquivos, os dois em quant/saida/ (gitignored: e dado financeiro pessoal, nao entra
no repositorio nem no branch de dados):

  livro_ordens.csv   uma linha por ordem EMITIDA (COLUNAS_ORDEM). Intencao. Serve para
                     medir slippage (preco_limite x preco do fill) e taxa de execucao.
  livro_fills.csv    uma linha por EXECUCAO (COLUNAS_FILL). Fato. E a fonte da posicao.

Formato: CSV com ';' (convencao do resto do pacote), ponto decimal, datas AAAA-MM-DD,
UTF-8, cabecalho na primeira linha, uma linha por registro e append no fim. Os floats sao
gravados com o repr curto do Python, que faz ida e volta sem perder centavo. Na leitura,
coluna desconhecida e ignorada e coluna ausente entra com o padrao: um arquivo escrito por
uma versao antiga continua legivel e o usuario pode editar o CSV a mao numa planilha (o
leitor tambem aceita virgula decimal e data dd/mm/aaaa, que e o que a planilha devolve).

PRECO MEDIO - a regra que produz o custo fiscal:
    compra:  qtd += q;   custo_total += q * preco + corretagem + emolumentos
    venda:   custo_total -= custo_total * q / qtd_antes;   qtd -= q
Vender NAO muda o preco medio do que sobra: e o custo medio ponderado que a Receita usa no
ganho de capital em renda variavel. Duas consequencias que sao decisao, nao acidente:
  - os custos da COMPRA entram na base (aumentam o custo de aquisicao);
  - os custos da VENDA nao entram: eles reduzem o valor liquido da venda, e quem faz essa
    conta e quant/fiscal.py, que recebe `custos` por operacao em operacoes(). Somar a
    corretagem de venda ao custo_total inflaria a base do que ficou na carteira.
Quantidade zero REMOVE a linha (posicao fechada nao e posicao) e a data_entrada morre com
ela: comprar o mesmo nome depois abre posicao nova, com o relogio de `meses` reiniciado -
que e exatamente o que a regra de 12 meses de carteira.py espera.

Suposicoes (o que da para exercitar esta em quant/testes/test_livro_ordens.py):
  - `data` e a data do PREGAO (D+0), nunca a da liquidacao (D+2): a apuracao mensal do
    fiscal e por mes de pregao. `hora` e opcional e serve so para ordenar os fills do dia;
    aceita fracao de segundo ('10:31:05.120') quando a corretora fornece.
  - `qtd` e sempre positiva e o sentido esta em `lado` ('C' ou 'V'). Guardar quantidade
    assinada economizaria uma coluna e faria a soma errada passar despercebida.
  - `qtd` e float mesmo sendo inteira na B3: evita a aritmetica int/NaN do pandas e deixa
    a porta aberta para fracionario de fundo. Compare sempre com tolerancia (TOL_QTD).
  - ordens sao idempotentes por (boleta, ticker, lado, fatia) e fills por
    (data, hora, boleta, ticker, lado, qtd, preco): registrar de novo SUBSTITUI a linha,
    nunca duplica, e a versao nova vence (permite corrigir a corretagem de um fill).
    Duas consequencias honestas: (a) reemitir uma boleta SEM uma linha que existia antes
    nao apaga a linha antiga - cancelar e explicito, com status 'cancelada'; (b) duas
    execucoes rigorosamente identicas no mesmo segundo viram uma so - se isso acontecer de
    verdade, registre uma linha unica com a quantidade somada (a corretora costuma dar
    fracao de segundo, que ja separa as duas).
  - `boleta` e o identificador da boleta noturna (ex.: '20260908'); em fill avulso pode
    ficar vazio, e a chave continua funcionando.
  - a ordem das linhas no arquivo e a ordem de REGISTRO, nao a cronologica (uma linha
    reescrita vai para o fim). Quem precisa de cronologia ordena por (data, hora), que e o
    que posicao() e operacoes() fazem, com sort estavel.
  - nao ha trava entre processos, como em quant/livro.py: rode um processo por vez, ou
    duas gravacoes simultaneas perdem uma (a ultima a gravar vence).
  - ticker fracionario da nota ('PETR4F') e normalizado para o codigo cheio ('PETR4'),
    senao a mesma posicao apareceria partida em dois nomes com precos medios diferentes.
  - registrar levanta ValueError quando a linha NAO E um fill (sem data, sem ticker, sem
    lado valido, quantidade nao positiva): e erro de quem chamou e tem que doer. Ja na
    LEITURA de um arquivo corrompido ou editado errado a mao nada levanta - a linha
    invalida e ignorada por posicao(), operacoes() e resumo(), com aviso no log, para o
    painel continuar respondendo com o resto do livro.

ACHADO: O LIVRO NAO SABE DE DESDOBRAMENTO, GRUPAMENTO NEM BONIFICACAO.
  Evento corporativo muda a quantidade sem que exista execucao, e este livro so conhece
  execucoes. Depois de um desdobro 1:2 a posicao calculada fica com METADE das acoes que a
  corretora mostra, e a divergencia nao aparece sozinha - por isso conferir() contra o
  extrato, uma vez por mes, nao e burocracia, e o unico detector. O remendo enquanto
  eventos.py nao for ligado aqui: registrar uma linha de compra com preco ZERO e a
  quantidade nova (obs='desdobramento 1:2'). Isso soma quantidade sem somar custo, que e
  exatamente o efeito fiscal do desdobro (o custo total nao muda, o preco medio cai na
  proporcao). ATENCAO: para BONIFICACAO isso esta ERRADO - a acao bonificada tem custo de
  aquisicao informado pela empresa (valor patrimonial), entao entre com esse preco, nao
  com zero. Grupamento e o caso feio: exige uma venda a preco zero, que reduz o custo
  proporcionalmente e mantem o preco medio - errado, porque no grupamento o preco medio
  deve SUBIR. Registre grupamento a mao e confira com o extrato.

ACHADO: PAPER E REAL NO MESMO ARQUIVO CONTAMINAM A POSICAO.
  posicao() nao filtra por origem de proposito (a assinatura seria uma mentira: quem
  decide o que e a carteira e o arquivo). A separacao correta e por ARQUIVO - todas as
  funcoes recebem `caminho`, entao o paper trading escreve em outro CSV - ou filtrando os
  fills antes: posicao(fills[fills['origem'] == 'real']). resumo()['origens'] existe para
  que um arquivo misturado seja percebido na primeira olhada.

O QUE PRECISA SER CONFERIDO CONTRA A REALIDADE (primeira nota de corretagem real):
  - a nota traz corretagem, taxa de liquidacao e emolumentos por NOTA, nao por linha:
    quem registra tem que ratear entre as linhas (o rateio pro rata pelo financeiro e o
    usual) - este modulo assume que o valor ja chega rateado por execucao;
  - se a soma (emolumentos + liquidacao) da nota bate com custos.TAXA_B3 (0,030% por
    lado); se nao bater, e custos.py que esta errado, nao o livro;
  - o nome exato das colunas do extrato de custodia usado em --conferir (aqui aceita-se
    ticker/papel/codigo e qtd/quantidade), e se ele lista o fracionario separado;
  - se a data da nota e a do pregao (assumido) ou a da liquidacao;
  - se a corretora lista compra e venda do mesmo papel no mesmo segundo com o mesmo preco
    (day trade fatiado), caso em que a chave de deduplicacao precisa da fracao de segundo.

Linha de comando (--conferir sai com 1 quando diverge, para caber num cron):
    python3 -m quant.execucao.livro_ordens --resumo
    python3 -m quant.execucao.livro_ordens --posicao [--ate 2026-09-30]
    python3 -m quant.execucao.livro_ordens --conferir extrato_corretora.csv
"""
import argparse
import io
import math
import os
import re
import sys
from datetime import date, datetime

import pandas as pd

from quant.comum import DIR_SAIDA, garantir_dir, gravar_atomico, log

ARQ_ORDENS = os.path.join(DIR_SAIDA, "livro_ordens.csv")
ARQ_FILLS = os.path.join(DIR_SAIDA, "livro_fills.csv")

COLUNAS_ORDEM = ["data", "boleta", "ticker", "lado", "qtd", "preco_limite", "validade",
                 "motivo", "custo_estimado", "fatia", "fracionario", "status"]
COLUNAS_FILL = ["data", "hora", "boleta", "ticker", "lado", "qtd", "preco",
                "corretagem", "emolumentos", "origem", "obs"]
COLUNAS_POSICAO = ["ticker", "qtd", "custo_total", "preco_medio", "data_entrada", "meses"]
COLUNAS_OPERACAO = ["data", "ticker", "classe", "lado", "qtd", "preco", "valor", "custos", "fonte"]
COLUNAS_CONFERENCIA = ["ticker", "qtd_livro", "qtd_corretora", "diferenca"]

ORIGENS = ("paper", "real")
STATUS = ("emitida", "executada", "parcial", "cancelada")
LADOS = ("C", "V")
CLASSES = ("acao", "etf", "bdr", "fii", "futuro", "opcao")

CHAVE_ORDEM = ("boleta", "ticker", "lado", "fatia")
CHAVE_FILL = ("data", "hora", "boleta", "ticker", "lado", "qtd", "preco")
NUMERICAS_CHAVE = ("qtd", "preco")
CASAS_CHAVE = 6               # casas do float na chave: centavo sobra, ruido de bit some

SEP = ";"
VALIDADE_PADRAO = "dia"
FATIA_PADRAO = "1/1"
STATUS_PADRAO = "emitida"
ORIGEM_PADRAO = "paper"
CLASSE_PADRAO = "acao"
TOL_QTD = 1e-9                # abaixo disso a posicao esta zerada, nao "quase zerada"

SUFIXOS_BDR = ("31", "32", "33", "34", "35", "39")
PREFIXOS_FUTURO = ("WIN", "IND", "WDO", "DOL")
RE_FRACIONARIO = re.compile(r"^([A-Z]{4}\d{1,2})F$")
RE_OPCAO = re.compile(r"^[A-Z]{4}[A-X]\d{1,3}$")
RE_FUTURO = re.compile(r"^(?:" + "|".join(PREFIXOS_FUTURO) + r")[FGHJKMNQUVXZ]\d{2}$")
RE_SUFIXO = re.compile(r"^[A-Z]{4}(\d{1,2})$")
FORMATOS_DATA = ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d", "%d/%m/%y")
RE_HORA = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?(\.\d+)?$")
VERDADEIRO = ("1", "true", "t", "sim", "s", "y", "yes", "verdadeiro")

# tipo logico de cada coluna; o que nao esta aqui e texto
TIPOS = {"data": "data", "data_entrada": "data",
         "qtd": "num", "preco": "num", "preco_limite": "num", "preco_medio": "num",
         "custo_estimado": "num", "custo_total": "num", "corretagem": "num",
         "emolumentos": "num", "valor": "num", "custos": "num",
         "qtd_livro": "num", "qtd_corretora": "num", "diferenca": "num",
         "fracionario": "bool", "meses": "inteiro"}
DTYPES = {"texto": "object", "num": "float64", "bool": "bool",
          "data": "datetime64[ns]", "inteiro": "int64"}


# ─────────────────────────────────────────────────────────────
# Conversao de campo (tolerante: o CSV pode ter sido editado a mao)
# ─────────────────────────────────────────────────────────────
def _texto(v):
    """Qualquer coisa -> str limpa. None, NaN, NaT e 'nan' viram ''."""
    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""
    if v is pd.NaT:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "nat", "none") else s


def _num(v, padrao=float("nan")):
    """Numero de CSV, planilha ou DataFrame. Aceita '1.234,56' e '10,50' (a planilha da
    corretora exporta com virgula); '10.50' continua sendo dez e meio."""
    if isinstance(v, bool):
        return padrao
    if isinstance(v, (int, float)):
        return padrao if (isinstance(v, float) and math.isnan(v)) else float(v)
    s = _texto(v).replace(" ", "").replace("R$", "")
    if not s:
        return padrao
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return padrao


def _data(v):
    """'2026-09-08', '08/09/2026', date, datetime ou Timestamp -> Timestamp; lixo -> NaT."""
    if v is None or v is pd.NaT:
        return pd.NaT
    if isinstance(v, pd.Timestamp):
        return pd.NaT if pd.isna(v) else v.normalize()
    if isinstance(v, datetime):
        return pd.Timestamp(v).normalize()
    if isinstance(v, date):
        return pd.Timestamp(v)
    s = _texto(v)
    if not s:
        return pd.NaT
    for fmt in FORMATOS_DATA:
        try:
            return pd.Timestamp(datetime.strptime(s[:10], fmt))
        except ValueError:
            continue
    return pd.NaT


def _hora(v):
    """'10:31', '10:31:05' ou '10:31:05.120' -> 'HH:MM:SS[.fff]'; vazio -> ''.

    A fracao de segundo e preservada de proposito: e ela que separa duas execucoes
    identicas no mesmo segundo na chave de deduplicacao.
    """
    s = _texto(v)
    m = RE_HORA.match(s)
    if not m:
        return s
    return f"{int(m.group(1)):02d}:{m.group(2)}:{m.group(3) or '00'}{m.group(4) or ''}"


def _flag(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return False if math.isnan(float(v)) else bool(v)
    return _texto(v).lower() in VERDADEIRO


def _lado(v):
    """'C'/'V', 'compra'/'venda', 'c'/'v' -> 'C'/'V'. Levanta em qualquer outra coisa:
    lado errado inverte o sinal do imposto, nao pode passar em silencio."""
    s = _texto(v).upper()
    if s[:1] in LADOS:
        return s[:1]
    raise ValueError(f"lado invalido: {v!r} (use {' ou '.join(LADOS)})")


def _origem(v):
    s = _texto(v).lower() or ORIGEM_PADRAO
    if s not in ORIGENS:
        raise ValueError(f"origem invalida: {v!r} (use {' ou '.join(ORIGENS)})")
    return s


def _status(v):
    s = _texto(v).lower() or STATUS_PADRAO
    if s not in STATUS:
        raise ValueError(f"status invalido: {v!r} (use {', '.join(STATUS)})")
    return s


def normalizar_ticker(v):
    """'petr4 ' -> 'PETR4'; 'PETR4F' (fracionario da nota) -> 'PETR4'.

    Sem essa unificacao a mesma posicao apareceria em dois nomes, cada um com seu preco
    medio, e o fiscal apuraria os dois separados - erro caro e silencioso.
    """
    s = _texto(v).upper().replace(" ", "")
    m = RE_FRACIONARIO.match(s)
    return m.group(1) if m else s


def classe_do_ticker(ticker, classes=None):
    """Classe fiscal do papel: usa o mapa explicito e, sem entrada, deduz pelo codigo.

    Deducao: WINZ26/INDV26 -> 'futuro'; PETRE30 (4 letras + letra de serie + strike) ->
    'opcao'; sufixo 31..35 e 39 -> 'bdr'; qualquer outro -> 'acao'.
    O SUFIXO 11 E AMBIGUO: unit (SANB11), ETF (BOVA11) e FII (HGLG11) usam o mesmo final e
    NAO da para separar pelo codigo. Aqui 11 assume 'acao', que e o caso comum na carteira
    deste sistema, e o mapa `classes` e o jeito CERTO de resolver - a diferenca nao e
    cosmetica: FII nao tem a isencao de R$20 mil e paga 20%, ETF de acoes nao tem isencao e
    paga 15%, e acao/unit tem isencao. Passe o mapa sempre que houver 11 na carteira.
    """
    t = normalizar_ticker(ticker)
    if classes:
        c = _texto(classes.get(t) or classes.get(_texto(ticker).upper())).lower()
        if c in CLASSES:
            return c
    if RE_FUTURO.match(t):
        return "futuro"
    if RE_OPCAO.match(t):
        return "opcao"
    m = RE_SUFIXO.match(t)
    if m and m.group(1) in SUFIXOS_BDR:
        return "bdr"
    return CLASSE_PADRAO


# ─────────────────────────────────────────────────────────────
# Tabelas: esquema vazio, montagem e normalizacao das entradas
# ─────────────────────────────────────────────────────────────
def _vazio(colunas):
    """DataFrame sem linhas com as colunas e os dtypes certos - o que todo leitor devolve
    quando nao ha arquivo, para quem consome nunca precisar testar None."""
    return pd.DataFrame({c: pd.Series(dtype=DTYPES[TIPOS.get(c, "texto")]) for c in colunas})


def _tipar(df, colunas):
    for c in colunas:
        tipo = TIPOS.get(c, "texto")
        if tipo == "texto":
            df[c] = [_texto(v) for v in df[c]]
        elif tipo == "bool":
            df[c] = pd.Series([_flag(v) for v in df[c]], index=df.index, dtype="bool")
        elif tipo == "data":
            df[c] = pd.to_datetime(pd.Series([_data(v) for v in df[c]], index=df.index))
        elif tipo == "inteiro":
            df[c] = pd.Series([int(_num(v, 0.0)) for v in df[c]], index=df.index, dtype="int64")
        else:
            df[c] = pd.Series([_num(v) for v in df[c]], index=df.index, dtype="float64")
    return df


def _montar(linhas, colunas):
    """Lista de dicts -> DataFrame com exatamente `colunas`, tipadas. Vazio -> esquema vazio."""
    if not linhas:
        return _vazio(colunas)
    df = pd.DataFrame(linhas)
    for c in colunas:
        if c not in df.columns:
            df[c] = None
    return _tipar(df[list(colunas)].reset_index(drop=True), colunas)


def _registros(dados):
    """DataFrame, lista de dicts, dict unico ou None -> lista de dicts."""
    if dados is None:
        return []
    if isinstance(dados, pd.DataFrame):
        return [] if dados.empty else dados.to_dict("records")
    if isinstance(dados, dict):
        return [dados]
    return [dict(r) for r in dados]


def _campo(r, *nomes, padrao=None):
    """Primeiro nome presente e nao vazio - e assim que `preco_limite` cai em `preco` e
    `custo_estimado` cai em `custo`, que sao os nomes que carteira.ordens_incrementais usa."""
    for n in nomes:
        if n in r and _texto(r[n]) != "":
            return r[n]
    return padrao


def normalizar_ordens(ordens, data, boleta):
    """Ordens de uma boleta -> DataFrame(COLUNAS_ORDEM), sem tocar em disco.

    Aceita a saida de carteira.ordens_incrementais (ticker, lado, qtd, preco, valor, custo,
    motivo, fracionario) mais o que a boleta acrescentar (preco_limite, validade, fatia,
    status). `data` e `boleta` valem para todas as linhas: uma boleta e um evento unico.
    Linha sem ticker ou com quantidade <= 0 e descartada (ordem de quantidade zero nao e
    ordem); quantidade negativa vira positiva, porque o sentido esta em `lado`.
    """
    d = _data(data)
    b = _texto(boleta)
    linhas = []
    for r in _registros(ordens):
        t = normalizar_ticker(_campo(r, "ticker", padrao=""))
        q = abs(_num(_campo(r, "qtd", "quantidade"), 0.0))
        if not t or q <= TOL_QTD:
            continue
        linhas.append({
            "data": d, "boleta": b, "ticker": t,
            "lado": _lado(_campo(r, "lado", padrao="C")),
            "qtd": q,
            "preco_limite": _num(_campo(r, "preco_limite", "preco")),
            "validade": _texto(_campo(r, "validade", padrao=VALIDADE_PADRAO)),
            "motivo": _texto(_campo(r, "motivo", padrao="")),
            "custo_estimado": _num(_campo(r, "custo_estimado", "custo"), 0.0),
            "fatia": _texto(_campo(r, "fatia", padrao=FATIA_PADRAO)),
            "fracionario": _flag(_campo(r, "fracionario", padrao=False)),
            "status": _status(_campo(r, "status", padrao=STATUS_PADRAO)),
        })
    return _montar(linhas, COLUNAS_ORDEM)


def normalizar_fills(fills):
    """Execucoes -> DataFrame(COLUNAS_FILL), sem tocar em disco. Idempotente.

    Levanta ValueError quando a linha nao e um fill: sem data, sem ticker, quantidade nao
    positiva ou preco negativo. Perder um fill em silencio e o pior defeito possivel neste
    modulo - preco ZERO e aceito de proposito (e o remendo de desdobramento do docstring).
    """
    linhas = []
    for i, r in enumerate(_registros(fills)):
        d = _data(_campo(r, "data"))
        t = normalizar_ticker(_campo(r, "ticker", "papel", "codigo", padrao=""))
        q = _num(_campo(r, "qtd", "quantidade"), float("nan"))
        p = _num(_campo(r, "preco", "preco_unitario"), float("nan"))
        if pd.isna(d) or not t or not (q > TOL_QTD) or not (p >= 0):
            raise ValueError(f"fill invalido na linha {i}: data={_texto(r.get('data'))!r} "
                             f"ticker={t!r} qtd={q!r} preco={p!r}")
        linhas.append({
            "data": d, "hora": _hora(_campo(r, "hora", padrao="")),
            "boleta": _texto(_campo(r, "boleta", padrao="")), "ticker": t,
            "lado": _lado(_campo(r, "lado", padrao="C")), "qtd": q, "preco": p,
            "corretagem": _num(_campo(r, "corretagem"), 0.0),
            "emolumentos": _num(_campo(r, "emolumentos", "taxas"), 0.0),
            "origem": _origem(_campo(r, "origem", padrao=ORIGEM_PADRAO)),
            "obs": _texto(_campo(r, "obs", padrao="")),
        })
    return _montar(linhas, COLUNAS_FILL)


def _rotulo(v):
    return v.strftime("%Y-%m-%d") if isinstance(v, pd.Timestamp) and pd.notna(v) else _texto(v)


def _chaves(df, chave, numericas=()):
    """Chave de deduplicacao de cada linha, como tupla de texto. Os numeros entram
    arredondados (CASAS_CHAVE) para o valor lido do CSV bater com o valor em memoria."""
    saida = []
    for r in df[list(chave)].to_dict("records"):
        saida.append(tuple(f"{_num(r[c], 0.0):.{CASAS_CHAVE}f}" if c in numericas else _rotulo(r[c])
                           for c in chave))
    return saida


def _anexar(antigos, novos, chave, numericas=()):
    """Concatena e resolve a chave: a linha NOVA vence a antiga (permite corrigir um
    registro reenviando-o). Nao remove linha antiga que a nova remessa nao mencionou."""
    if len(novos) == 0:
        return antigos.reset_index(drop=True)
    df = novos.reset_index(drop=True) if len(antigos) == 0 else \
        pd.concat([antigos, novos], ignore_index=True)
    manter = ~pd.Series(_chaves(df, chave, numericas), dtype=object).duplicated(keep="last")
    return df.loc[manter.values].reset_index(drop=True)


# ─────────────────────────────────────────────────────────────
# Posicao, operacoes, conferencia e resumo (puras: so leem os fills)
# ─────────────────────────────────────────────────────────────
def _meses_entre(inicio, fim):
    """Meses inteiros completos entre duas datas (o relogio de holding de carteira.py)."""
    if pd.isna(inicio) or pd.isna(fim):
        return 0
    m = (fim.year - inicio.year) * 12 + (fim.month - inicio.month)
    if fim.day < inicio.day:
        m -= 1
    return max(int(m), 0)


def _validos(fills):
    """Descarta a linha que nao da para posicionar no tempo (sem data) ou que nao diz o que
    aconteceu (sem ticker, sem lado, sem quantidade ou com preco negativo). So aparece em
    arquivo corrompido ou editado errado a mao - e o log avisa, porque fill perdido em
    silencio e o defeito mais caro daqui."""
    if len(fills) == 0:
        return fills
    ok = (fills["data"].notna() & (fills["ticker"] != "") & fills["lado"].isin(LADOS)
          & (fills["qtd"] > TOL_QTD) & (fills["preco"] >= 0))
    if not bool(ok.all()):
        log(f"livro: {int((~ok).sum())} linha(s) ignorada(s) por data, ticker, lado, "
            f"quantidade ou preco invalido")
    return fills[ok.values]


def _cronologico(fills):
    """Ordena por (data, hora) com sort estavel: empate mantem a ordem de registro, que e
    a unica informacao que sobra quando a corretora nao da hora."""
    return fills.sort_values(["data", "hora"], kind="mergesort").reset_index(drop=True)


def posicao(fills=None, ate=None, caminho=ARQ_FILLS):
    """Posicao e PRECO MEDIO por ticker a partir dos fills ate `ate` (inclusive).

    Compra soma quantidade e soma (valor + custos) ao custo total. Venda reduz a quantidade
    e reduz o custo total PROPORCIONALMENTE (custo_total * qtd_vendida / qtd_antes), que e a
    regra do preco medio: vender nao muda o preco medio do que sobra. Quantidade zero
    remove a linha - e com ela a data_entrada, entao recomprar depois reinicia o relogio.

    Venda maior que a posicao e erro do usuario (fill faltando, ticker trocado, evento
    corporativo nao registrado): a linha fica com quantidade NEGATIVA, o custo total para
    em zero e o preco medio vira NaN (preco medio de posicao negativa nao existe). Nada e
    silenciado: resumo()['posicoes_negativas'] lista esses tickers.
    """
    f = _validos(carregar_fills(caminho) if fills is None else normalizar_fills(fills))
    limite = _data(ate) if ate is not None else pd.NaT
    if len(f) and pd.notna(limite):
        f = f[f["data"] <= limite]
    if len(f) == 0:
        return _vazio(COLUNAS_POSICAO)
    f = _cronologico(f)
    estado = {}
    for r in f.to_dict("records"):
        t, q, pr = r["ticker"], float(r["qtd"]), float(r["preco"])
        e = estado.get(t) or {"qtd": 0.0, "custo": 0.0, "entrada": pd.NaT}
        if r["lado"] == "C":
            if e["qtd"] <= TOL_QTD:                     # posicao nova (ou reaberta)
                e["entrada"] = r["data"]
            e["qtd"] += q
            e["custo"] += q * pr + float(r["corretagem"]) + float(r["emolumentos"])
        else:
            antes = e["qtd"]
            if antes > TOL_QTD:
                # a fracao e limitada a 1: o excesso vendido nao pode tirar custo que nao
                # existe. Os custos da VENDA nao entram aqui (ver o docstring do modulo).
                e["custo"] -= e["custo"] * min(q, antes) / antes
            e["qtd"] -= q
        if abs(e["qtd"]) <= TOL_QTD:
            estado.pop(t, None)
        else:
            estado[t] = e
    ref = limite if pd.notna(limite) else f["data"].max()
    linhas = []
    for t in sorted(estado):
        e = estado[t]
        q = e["qtd"]
        linhas.append({"ticker": t, "qtd": q,
                       "custo_total": e["custo"] if q > TOL_QTD else 0.0,
                       "preco_medio": e["custo"] / q if q > TOL_QTD else float("nan"),
                       "data_entrada": e["entrada"],
                       "meses": _meses_entre(e["entrada"], ref)})
    return _montar(linhas, COLUNAS_POSICAO)


def operacoes(fills=None, classes=None, caminho=ARQ_FILLS):
    """Fills normalizados no formato que quant/fiscal.py consome (COLUNAS_OPERACAO).

    `classes`: dict ticker -> classe ('acao', 'etf', 'bdr', 'fii', 'futuro', 'opcao'); sem
    entrada, deduz pelo codigo (ver classe_do_ticker - o sufixo 11 assume 'acao' e o mapa
    explicito e o certo). `valor` = qtd * preco (bruto, sem custos, que e a base do ganho
    de capital); `custos` = corretagem + emolumentos, para o fiscal somar na compra e
    subtrair na venda. `fonte` e a origem do fill ('paper' ou 'real'): apuracao de imposto
    de carteira simulada nao existe, e o fiscal precisa poder separar.
    """
    f = _validos(carregar_fills(caminho) if fills is None else normalizar_fills(fills))
    if len(f) == 0:
        return _vazio(COLUNAS_OPERACAO)
    linhas = []
    for r in _cronologico(f).to_dict("records"):
        q, pr = float(r["qtd"]), float(r["preco"])
        linhas.append({"data": r["data"], "ticker": r["ticker"],
                       "classe": classe_do_ticker(r["ticker"], classes),
                       "lado": r["lado"], "qtd": q, "preco": pr, "valor": q * pr,
                       "custos": float(r["corretagem"]) + float(r["emolumentos"]),
                       "fonte": r["origem"]})
    return _montar(linhas, COLUNAS_OPERACAO)


def _serie_qtd(x):
    """DataFrame(ticker, qtd), Series indexada por ticker, dict ou None -> Series de
    quantidades por ticker, com os tickers normalizados e as repeticoes somadas (o extrato
    da corretora costuma listar o fracionario numa linha separada)."""
    if x is None:
        return pd.Series(dtype=float)
    if isinstance(x, pd.DataFrame):
        if x.empty:
            return pd.Series(dtype=float)
        col_t = next((c for c in ("ticker", "papel", "codigo") if c in x.columns), None)
        col_q = next((c for c in ("qtd", "quantidade", "qtd_livro", "qtd_corretora")
                      if c in x.columns), None)
        if col_t is None or col_q is None:
            return pd.Series(dtype=float)
        itens = zip(x[col_t], x[col_q])
    elif isinstance(x, pd.Series):
        itens = x.items()
    else:
        itens = dict(x).items()
    soma = {}
    for t, q in itens:
        t = normalizar_ticker(t)
        if t:
            soma[t] = soma.get(t, 0.0) + _num(q, 0.0)
    return pd.Series(soma, dtype=float)


def conferir(posicao_livro, posicao_corretora):
    """DataFrame(ticker, qtd_livro, qtd_corretora, diferenca) so com as linhas que divergem.

    E a conferencia que o usuario faz uma vez por mes contra o extrato da corretora - e o
    unico detector de fill esquecido, ticker trocado e evento corporativo (ver o ACHADO no
    docstring do modulo). Ticker que existe so de um lado entra com zero do outro.
    Diferenca positiva = o livro acha que tem mais do que a corretora mostra.
    """
    livro, corretora = _serie_qtd(posicao_livro), _serie_qtd(posicao_corretora)
    linhas = []
    for t in sorted(set(livro.index) | set(corretora.index)):
        ql, qc = float(livro.get(t, 0.0)), float(corretora.get(t, 0.0))
        if abs(ql - qc) > TOL_QTD:
            linhas.append({"ticker": t, "qtd_livro": ql, "qtd_corretora": qc,
                           "diferenca": ql - qc})
    return _montar(linhas, COLUNAS_CONFERENCIA)


def resumo(fills=None, caminho=ARQ_FILLS):
    """Retrato do livro em um dict, para o painel e para a linha de comando.

    `financeiro_total` e o GIRO (soma de qtd x preco de compras e vendas), nao o caixa
    liquido: e o numero que se compara com o custo total para saber quanto do dinheiro
    virou atrito. `primeiro`/`ultimo` sao textos ISO (ou None) para caberem em JSON.
    """
    f = _validos(carregar_fills(caminho) if fills is None else normalizar_fills(fills))
    if len(f) == 0:
        return {"n_fills": 0, "n_tickers": 0, "primeiro": None, "ultimo": None,
                "financeiro_total": 0.0, "custos_totais": 0.0,
                "posicoes_negativas": [], "origens": {}}
    pos = posicao(f)
    negativas = [t for t, q in zip(pos["ticker"], pos["qtd"]) if q < -TOL_QTD]
    return {"n_fills": int(len(f)),
            "n_tickers": int(f["ticker"].nunique()),
            "primeiro": _rotulo(f["data"].min()),
            "ultimo": _rotulo(f["data"].max()),
            "financeiro_total": float((f["qtd"] * f["preco"]).sum()),
            "custos_totais": float((f["corretagem"] + f["emolumentos"]).sum()),
            "posicoes_negativas": negativas,
            "origens": {k: int(v) for k, v in sorted(f["origem"].value_counts().items())}}


# ─────────────────────────────────────────────────────────────
# Disco
# ─────────────────────────────────────────────────────────────
def _ler(caminho, colunas):
    """CSV -> DataFrame(colunas). Arquivo ausente, vazio ou ilegivel devolve o esquema
    vazio e registra no log: um livro que levanta excecao derruba o painel inteiro."""
    if not caminho or not os.path.exists(caminho):
        return _vazio(colunas)
    try:
        with open(caminho, encoding="utf-8") as f:
            texto = f.read()
        if not texto.strip():
            return _vazio(colunas)
        df = pd.read_csv(io.StringIO(texto), sep=SEP, dtype=str, keep_default_na=False)
    except Exception as e:
        log(f"livro ilegivel em {caminho}: {type(e).__name__}")
        return _vazio(colunas)
    if df.empty:
        return _vazio(colunas)
    return _montar(df.to_dict("records"), colunas)


def _gravar(df, caminho, colunas):
    caminho = os.path.abspath(str(caminho))
    garantir_dir(os.path.dirname(caminho))
    gravar_atomico(caminho, df[list(colunas)].to_csv(index=False, sep=SEP,
                                                     date_format="%Y-%m-%d"))
    return caminho


def carregar_ordens(caminho=ARQ_ORDENS):
    """livro_ordens.csv -> DataFrame(COLUNAS_ORDEM). Sem arquivo, esquema vazio."""
    return _ler(caminho, COLUNAS_ORDEM)


def carregar_fills(caminho=ARQ_FILLS):
    """livro_fills.csv -> DataFrame(COLUNAS_FILL). Sem arquivo, esquema vazio."""
    return _ler(caminho, COLUNAS_FILL)


def registrar_ordens(ordens, data, boleta, caminho=ARQ_ORDENS):
    """Anexa as ordens de uma boleta. `ordens` e o DataFrame de carteira.ordens_incrementais
    (colunas ticker, lado, qtd, preco, valor, custo, motivo, fracionario) mais o que a
    boleta acrescentar. Idempotente por (boleta, ticker, lado, fatia): reemitir a mesma
    boleta substitui as linhas, nao duplica. Devolve o livro inteiro ja gravado."""
    novas = normalizar_ordens(ordens, data, boleta)
    livro = carregar_ordens(caminho)
    if len(novas) == 0:
        return livro
    livro = _anexar(livro, novas, CHAVE_ORDEM)
    _gravar(livro, caminho, COLUNAS_ORDEM)
    log(f"ordens: {len(novas)} linha(s) da boleta {_texto(boleta)} ({len(livro)} no livro)")
    return livro


def registrar_fills(fills, caminho=ARQ_FILLS):
    """Anexa execucoes. Idempotente por (data, hora, boleta, ticker, lado, qtd, preco):
    reenviar o mesmo fill substitui a linha (util para corrigir a corretagem depois que a
    nota chega), nunca duplica. Devolve o livro inteiro ja gravado."""
    novos = normalizar_fills(fills)
    livro = carregar_fills(caminho)
    if len(novos) == 0:
        return livro
    livro = _anexar(livro, novos, CHAVE_FILL, NUMERICAS_CHAVE)
    _gravar(livro, caminho, COLUNAS_FILL)
    log(f"fills: {len(novos)} execucao(oes) registrada(s) ({len(livro)} no livro)")
    return livro


def _ler_extrato(caminho):
    """Extrato de custodia da corretora (CSV com ticker e quantidade, ';' ou ',') -> Series.
    Arquivo ausente ou ilegivel devolve None, para main() poder avisar em vez de levantar."""
    if not caminho or not os.path.exists(caminho):
        return None
    try:
        with open(caminho, encoding="utf-8", errors="replace") as f:
            texto = f.read()
        sep = SEP if texto.splitlines()[0].count(SEP) else ","
        df = pd.read_csv(io.StringIO(texto), sep=sep, dtype=str, keep_default_na=False)
    except Exception as e:
        log(f"extrato ilegivel em {caminho}: {type(e).__name__}")
        return None
    df.columns = [_texto(c).lower() for c in df.columns]
    return _serie_qtd(df)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Livro de ordens e execucoes (M13)")
    ap.add_argument("--posicao", action="store_true", help="posicao e preco medio por ticker")
    ap.add_argument("--resumo", action="store_true", help="retrato do livro (padrao)")
    ap.add_argument("--conferir", default=None, metavar="CSV",
                    help="extrato da corretora (ticker;qtd) para conferir contra o livro")
    ap.add_argument("--ate", default=None, help="data limite (AAAA-MM-DD) para --posicao")
    args = ap.parse_args(argv)
    fills = carregar_fills(ARQ_FILLS)          # global lido em tempo de chamada: testavel
    if args.conferir:
        extrato = _ler_extrato(args.conferir)
        if extrato is None:
            print(f"extrato nao encontrado ou ilegivel: {args.conferir}")
            return 2
        d = conferir(posicao(fills), extrato)
        if len(d) == 0:
            print(f"livro e extrato batem ({len(fills)} fills)")
            return 0
        print(d.to_string(index=False))
        return 1
    if args.posicao:
        p = posicao(fills, ate=args.ate)
        print(p.to_string(index=False) if len(p) else "sem posicao no livro")
        return 0
    r = resumo(fills)
    print(f"fills {r['n_fills']}  tickers {r['n_tickers']}  "
          f"periodo {r['primeiro']} a {r['ultimo']}")
    print(f"financeiro R$ {r['financeiro_total']:,.2f}  custos R$ {r['custos_totais']:,.2f}  "
          f"origens {r['origens'] or '-'}")
    if r["posicoes_negativas"]:
        print("POSICOES NEGATIVAS (fill faltando ou evento corporativo nao registrado): "
              + ", ".join(r["posicoes_negativas"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
