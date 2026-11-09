"""Cadastro dos ativos das notas: nome do papel na nota -> ticker, classe e nome curto.

A nota da corretora traz o nome de pregao do papel ("SANEPAR PN N2", "FII XP MALLS CI ER"), nao o
ticker. O nome curto do relatorio e o nome sem o nivel de governanca (NM, N1, N2) e sem a
marca de evento (EJ ex-juros, ED ex-dividendos, ER ex-rendimento...). A raiz do ticker sai de
nomes_pregao.json: o nome de pregao e o codigo dos papeis das carteiras do dia dos indices da B3
(dado publico; refeita por atualizar_nomes()). Nome que nao esta nela vira alerta: acrescente no
tickers.json do titular.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import pathlib
import re
import urllib.request

NIVEIS = {'NM', 'N1', 'N2', 'MA', 'MB', 'M2'}
EVENTOS = {'EJ', 'ED', 'ER', 'EDJ', 'EDR', 'ERJ', 'ATZ', 'EX', 'ES', 'EB', 'EG', 'EC', 'EBJ', 'EJB', 'EDB',
           'EGS', 'ESJ', 'ERS', 'ERB', 'EJS', 'EBR'}
OBS = re.compile(r'^(?:[#ADFHTICPXYLB82]|#?D#?|FM|/?EJ|/?EX|/?ED|FM/\w+)$')
SUFIXO = {'ON': '3', 'PN': '4', 'PNA': '5', 'PNB': '6', 'UNT': '11', 'CI': '11', 'DRN': '34', 'DR3': '35'}

# raiz do ticker pelo nome de pregao (dado publico de mercado, gravado por atualizar_nomes)
NOMES_PREGAO = pathlib.Path(__file__).with_name('nomes_pregao.json')
INDICES = ('IBOV', 'IBRA', 'SMLL', 'IFIX', 'BDRX')
URL_INDICE = 'https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/GetPortfolioDay/'


def _carteira_indice(indice: str) -> list[dict]:
    q = base64.b64encode(json.dumps({'language': 'pt-br', 'pageNumber': 1, 'pageSize': 500, 'index': indice,
                                     'segment': '1'}).encode()).decode()
    req = urllib.request.Request(URL_INDICE + q, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode() or '{}').get('results') or []


def atualizar_nomes(destino: pathlib.Path = NOMES_PREGAO, hoje: dt.date | None = None, pede=None) -> dict:
    """Refaz a tabela de nomes de pregao com as carteiras do dia dos indices da B3 (o nome que a nota traz e o
    codigo do papel). Nome com duas raizes fica de fora: a nota nao diz qual delas."""
    raizes: dict[str, set] = {}
    for ind in INDICES:
        for x in (pede or _carteira_indice)(ind):
            nome, cod = (x.get('asset') or '').strip(), (x.get('cod') or '').strip()
            if nome and re.fullmatch(r'[A-Z0-9]{4}\d{1,2}', cod):
                raizes.setdefault(nome, set()).add(cod[:4])
    out = {'fonte': f"B3, carteira do dia dos indices {', '.join(INDICES)} (nome de pregao e codigo), lida em "
                    f"{hoje or dt.date.today():%d/%m/%Y}",
           'nomes': {n: min(r) for n, r in sorted(raizes.items()) if len(r) == 1}}
    pathlib.Path(destino).write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    return out


def _nomes(arq: pathlib.Path = NOMES_PREGAO) -> dict:
    try:
        return json.loads(pathlib.Path(arq).read_text())['nomes']
    except (OSError, ValueError, KeyError):
        return {}


EMPRESAS = _nomes()
# ticker do ativo-objeto pela raiz e classe da opcao ("PETRX300 PN 30,00" -> PETR4)
SERIE = re.compile(r'^[A-Z]{4}[A-X]\d{2,4}(?:[A-Z]\d?)?$')        # PETRX30, PETRA235, PETRA235W1
PAPEL = re.compile(r'^[A-Z]{4}\d{1,2}$')
ETF_NOMES = ('ISHARE', 'ETF', 'IT NOW', 'TREND', 'BB ETF', 'INVESTO')


def limpa_nome(espec: str) -> tuple[str, str]:
    """'SANEPAR PN EJ N2' -> ('SANEPAR', 'PN'): nome da empresa e classe, sem nivel nem evento. O que vem
    depois da classe (evento, nivel, observacao) cai fora; antes dela e nome ("FII JS A FIN" tem um "A")."""
    toks = espec.split()
    for i, t in enumerate(toks):
        if t in SUFIXO and i > 0:
            return ' '.join(x for x in toks[:i] if x not in EVENTOS), t
    return ' '.join(t for t in toks if t not in NIVEIS and t not in EVENTOS and not OBS.match(t)), ''


def classe_do_nome(nome: str, classe: str) -> str:
    if nome.startswith(('FII ', 'FIAGRO')):
        return 'fii'
    if classe in ('DRN', 'DR3'):
        return 'bdr'
    if any(x in nome for x in ETF_NOMES):
        return 'etf'
    return 'acao'


def carrega_extra(arq: pathlib.Path | None) -> dict:
    """tickers.json do titular: {"NOME CLASSE": "TICK11"} para nome fora da tabela."""
    if arq and arq.exists():
        return json.loads(arq.read_text())
    return {}


def identifica(mercado: str, espec: str, extra: dict | None = None) -> dict:
    """Ticker, classe, nome curto e, nas opcoes, strike, tipo e ativo-objeto."""
    extra = extra or {}
    if mercado.startswith(('OPCAO', 'EXERC')):
        toks = espec.split()
        m = re.search(r'\b(ON|PN|PNA|PNB|UNT|CI)\s+([\d.]+,\d+)', espec)
        cl = m.group(1) if m else ''
        strike = float(m.group(2).replace('.', '').replace(',', '.')) if m else None
        tipo = 'call' if ('COMPRA' in mercado) else 'put'
        serie = next((t for t in toks if SERIE.match(t)), None)
        if not serie and mercado.startswith('OPCAO') and re.match(r'^[A-Z]{4}', toks[0]):
            serie = toks[0]                 # negocio de opcao sempre comeca pela serie
        if serie:
            return {'ticker': serie, 'ativo': f'{serie} {cl}'.strip(), 'classe': 'opcao', 'strike': strike,
                    'tipo_opcao': tipo, 'subjacente': serie[:4] + SUFIXO.get(cl, '3'),
                    'exercicio': mercado.startswith('EXERC')}
        # exercicio que so traz o ativo-objeto ("PETROBRAS PN N2" ou "PETR4"): a serie sai da carteira
        # (Carteira._serie), pelo ativo-objeto, tipo e strike
        nome, cl2 = limpa_nome(espec)
        sub = next((t for t in toks if PAPEL.match(t)), None) or extra.get(f'{nome} {cl2}'.strip())
        if not sub and nome in EMPRESAS:
            sub = EMPRESAS[nome] + SUFIXO.get(cl2 or cl, '3')
        return {'ticker': sub, 'ativo': f"{sub or espec} (exercício)", 'classe': 'opcao', 'strike': strike,
                'tipo_opcao': tipo, 'subjacente': sub, 'exercicio': mercado.startswith('EXERC')}
    nome, cl = limpa_nome(espec)
    chave = f'{nome} {cl}'.strip()
    ticker = extra.get(chave)
    if not ticker and nome in EMPRESAS and cl in SUFIXO:
        ticker = EMPRESAS[nome] + SUFIXO[cl]
    return {'ticker': ticker, 'ativo': chave, 'classe': classe_do_nome(nome, cl), 'strike': None, 'tipo_opcao': None,
            'subjacente': None, 'exercicio': False}


def vencimento_opcao(mes_ano: str, feriados) -> dt.date:
    """Vencimento das opcoes da B3: terceira sexta-feira do mes, ou o dia util anterior se for feriado
    (novembro de 2026: dia 20 e feriado, vence 19/11)."""
    mes, ano = int(mes_ano[:2]), 2000 + int(mes_ano[3:5])
    d = dt.date(ano, mes, 1)
    while d.weekday() != 4:
        d += dt.timedelta(1)
    d += dt.timedelta(14)
    while d.weekday() >= 5 or d in feriados(d.year):
        d -= dt.timedelta(1)
    return d
