"""Le o relatorio mensal da IRTrade (texto das paginas, PDF ja aberto) para importar a posicao de partida
e conferir o motor: posicao por ativo, quadro do mes e operacoes finalizadas.

O texto vem com uma celula por linha; cada linha de tabela comeca em "SAFRA CORRETORA".
"""

from __future__ import annotations

import datetime as dt
import re

from .apuracao import Posicao
from .ativos import SUFIXO

SECOES = {'Posição de Ações': 'acao', 'Posição de Fundos': 'fii', 'Posição de Opções Vendidas': 'opcao',
          'Posição de Opções Compradas': 'opcao'}
LETRAS_CALL = 'ABCDEFGHIJKL'


def brl(s: str) -> float:
    s = s.replace('R$', '').replace(' ', '').replace('%', '')
    neg = s.startswith('-')
    v = float(s.lstrip('-').replace('.', '').replace(',', '.'))
    return -v if neg else v


def linhas(texto: str) -> list[tuple[str, list[str]]]:
    """(secao, celulas) de cada linha de tabela."""
    secao, atual, out = '', None, []
    for c in (x.strip() for x in texto.split('\n')):
        if not c:
            continue
        for rot, cl in SECOES.items():
            if c.startswith(rot):
                secao = cl
        if c.startswith('SAFRA'):
            if atual:
                out.append(atual)
            atual = (secao, [])
            continue
        if c == 'CORRETORA' and atual and not atual[1]:
            continue
        if atual is not None:
            if re.match(r'^(Posição|Opções de|Mercado à Vista|Disclaimer|Fii|Day Trade|Ações$|Data Liq|Corretora$)', c):
                out.append(atual)
                atual = None
            else:
                atual[1].append(c)
    if atual:
        out.append(atual)
    return out


def posicoes(textos: list[str]) -> list[Posicao]:
    out = []
    for t in textos:
        for secao, cel in linhas(t):
            if secao in ('acao', 'fii') and len(cel) >= 10 and re.match(r'^[A-Z0-9]{5,6}$', cel[0]):
                out.append(Posicao(cel[0], cel[1], secao, int(cel[2].replace('.', '')), brl(cel[4])))
            elif secao == 'opcao' and len(cel) >= 11 and re.match(r'^\d\d/\d\d/\d{4}$', cel[2]):
                tk, classe = cel[0], cel[1].split()[-1]
                out.append(Posicao(tk, cel[1], 'opcao', int(cel[3].replace('.', '')), brl(cel[5]),
                                   vencimento=dt.datetime.strptime(cel[2], '%d/%m/%Y').date(),
                                   tipo_opcao='call' if tk[4] in LETRAS_CALL else 'put',
                                   subjacente=tk[:4] + SUFIXO.get(classe, '3')))
    vistos, uniq = set(), []
    for p in out:
        if p.ticker not in vistos:
            vistos.add(p.ticker)
            uniq.append(p)
    return uniq


def operacoes(texto: str) -> list[dict]:
    """Linhas de "Operacoes finalizadas no mes": ticker, data, qtd, total do fechamento e do estoque, resultado."""
    out = []
    for _, cel in linhas(texto):
        if len(cel) >= 13 and re.match(r'^\d\d/\d\d/\d{4}$', cel[2]) and cel[3] in 'CV':
            comum = None if cel[12] == '-' else brl(cel[12])
            dtr = None if len(cel) < 14 or cel[13] == '-' else brl(cel[13])
            out.append({'ticker': cel[0], 'data': cel[2], 'cv': cel[3], 'qtd': int(cel[4].replace('.', '')),
                        'liq_total': brl(cel[6]), 'est_data': cel[7], 'est_total': brl(cel[11]),
                        'comum': comum, 'daytrade': dtr})
    return out
