"""Painel do contador de bolsa: pagina local no estilo do painel da IRTrade, com os numeros do motor.

    python3 ferramentas/local/irbolsa.py painel            grava saida/painel.html (abre no app ou no navegador)
    python3 ferramentas/local/irbolsa.py painel --servir   serve em http://127.0.0.1:5059, com o simulador

Nao calcula imposto: refaz cada mes com mes.fecha_mes(gravar=False) (os fechados da janela de 12 meses e o mes em
curso), le o retrato do painel da IRTrade (irtrade/AAAA-MM-DD.json), as conferencias anotadas (conferencias.json) e a
leitura do e-CAC (ecac.json, quando houver) e monta as paginas: inicio com os cartoes do painel da IRTrade, carteira,
resultados do mes, consolidado, meu IR (fichas da declaracao), proventos, DARF, monitoramento de CPF, pendencias,
conferencia com a IRTrade, simulador, documentos e guia.

O documento e o telefone do titular nunca entram na pagina: a montagem confere e recusa. O servidor so escuta em
127.0.0.1, so atende Host local e nao grava nada (o simulador roda o fechamento do mes sem gravar).
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import threading
import time
import urllib.parse
import webbrowser
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import aluguel, apuracao, ativos, eventos, mes, notas, precos
from .mes import MESES, br

PORTA = 5059
CACHE_S = 300                 # o servidor refaz a pagina depois disso, ou no botao "Atualizar"
ECAC = 'https://cav.receita.fazenda.gov.br/autenticacao/login'
CERTIDAO = 'https://servicos.receitafederal.gov.br/servico/certidoes/#/home'
MEU_IR = 'https://www.gov.br/receitafederal/pt-br/assuntos/meu-imposto-de-renda'
ATRASO = ('https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/pagamentos-e-parcelamentos/'
          'pagamento-em-atraso')
SICALC = ('https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/pagamentos-e-parcelamentos/'
          'darf-calculo-e-impressao-programa-sicalc-1/darf-calculo-e-impressao-programa-sicalc')
PDF_OK = re.compile(r'(Relatorio mensal|DARF) \d{1,2}-\d{4}\.pdf')
TICKER_OK = re.compile(r'[A-Z0-9]{4,12}')
CSP = ("default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
# colunas do consolidado de 12 meses (as do retrato da IRTrade) e a linha da tabela anual do motor que cada uma le
COLS_12M = ('comum', 'daytrade', 'fii', 'incentivadas', 'vendas_isentas', 'bonificacoes', 'proventos', 'btc')
DO_ANUAL = {'comum': 'OP. COMUM', 'daytrade': 'DAYTRADE', 'fii': 'FII', 'vendas_isentas': 'VENDAS ISENTAS',
            'bonificacoes': 'BONIFICAÇÕES', 'proventos': 'PROVENTOS', 'btc': 'BTC DOADOR', 'impostos': 'IMPOSTOS',
            'despesas': 'DESPESAS'}
ROTULOS_12M = {'comum': 'Operações comuns', 'daytrade': 'Day trade', 'fii': 'FII', 'incentivadas': 'Incentivadas',
               'vendas_isentas': 'Vendas isentas', 'bonificacoes': 'Bonificações', 'proventos': 'Proventos',
               'btc': 'Aluguel de ações (BTC)'}
# ficha "Renda variavel" da declaracao, nas colunas do retrato da IRTrade
FICHA_RV = (
    ('Operações comuns', None), ('Mercado à vista', 'vista_comum'), ('Opções', 'opcao_comum'),
    ('Resultado do mês', 'resultado_comum'), ('Resultado negativo até o mês anterior', 'negativo_anterior_comum'),
    ('Base de cálculo', 'base_comum'), ('Prejuízo a compensar', 'prejuizo_comum'), ('Imposto devido', 'imposto_comum'),
    ('Day trade', None), ('Mercado à vista', 'vista_dt'), ('Opções', 'opcao_dt'), ('Resultado do mês', 'resultado_dt'),
    ('Resultado negativo até o mês anterior', 'negativo_anterior_dt'), ('Base de cálculo', 'base_dt'),
    ('Prejuízo a compensar', 'prejuizo_dt'), ('Imposto devido', 'imposto_dt'),
    ('Consolidação do mês', None), ('Total do imposto devido', 'imposto_total'), ('IR na fonte no mês', 'irrf_mes'),
    ('IR na fonte de meses anteriores', 'irrf_anterior'), ('IR na fonte a compensar', 'irrf_compensar'),
    ('IR na fonte do day trade', 'irrf_dt'), ('Imposto a pagar', 'imposto_pagar'), ('Imposto pago', 'imposto_pago'))
NOMES_PROVENTO = {
    'DIVIDENDOS': 'Dividendos', 'JUROS S/ CAPITAL': 'Juros sobre capital próprio (JCP)', 'RENDIMENTOS': 'Rendimentos',
    'REEMBOLSO BTC DOADOR': 'Reembolso de proventos das ações alugadas',
    'RENDIMENTOS BTC DOADOR': 'Remuneração do aluguel de ações (já sem o IR)',
    'DESPESAS OPERACIONAIS - BTC': 'Corretagem do aluguel', 'REMUNERAÇÃO BTC TOMADOR': 'Aluguel pago como tomador'}
CUSTOS_ALUGUEL = ('DESPESAS OPERACIONAIS - BTC', 'REMUNERAÇÃO BTC TOMADOR')      # saem da conta: nao sao rendimento
CORES = ('#244b77', '#0d99ff', '#76aaf8', '#8fe3b3', '#ffa819', '#c3a6f5', '#ff9fb8')
MENU = (('inicio', 'Início'), ('carteira', 'Carteira'), ('resultados', 'Resultados'), ('consolidado', 'Consolidado'),
        ('meuir', 'Meu IR'), ('proventos', 'Proventos'), ('darf', 'DARF'), ('cpf', 'Monitoramento de CPF'),
        ('pendencias', 'Pendências'), ('conferencia', 'Conferência'), ('simulador', 'Simulador'),
        ('documentos', 'Documentos'), ('guia', 'Guia'))
NIVEL = {'erro': 0, 'alerta': 1, 'info': 2}
AJUSTADO = ('"IRTrade, ajustado": o número dela com a decisão que você tomou depois, que vale daí em diante '
            '(página Conferência).')


# ------------------------------------------------------------------ formatacao (como o painel da IRTrade)
def e(x) -> str:
    return escape(str(x if x is not None else ''))


def rs(x, zero: str = '-') -> str:
    """R$ 1.234,56 e -R$ 1.234,56; zero vira '-' (ou `zero`), como nos cartoes da IRTrade."""
    if x is None:
        return '-'
    x = round(float(x), 2)
    if x == 0:
        return zero
    return ('-R$ ' if x < 0 else 'R$ ') + br(abs(x))


def val(x, zero: str = '-') -> str:
    """Resultado com cor: verde no lucro, vinho no prejuizo."""
    t = e(rs(x, zero))
    if x is None or round(float(x), 2) == 0:
        return t
    return f'<span class="{"pos" if x > 0 else "neg"}">{t}</span>'


def num(x, casas: int = 2) -> str:
    if x is None:
        return '-'
    x = round(float(x), casas)
    t = e(br(x + 0.0, casas))
    return f'<span class="neg">{t}</span>' if x < 0 else t


def qt(x) -> str:
    if x is None:
        return '-'
    x = float(x)
    return br(x, 0) if x == int(x) else br(x, 2)


def pc(x) -> str:
    return '-' if x is None else br(float(x), 2) + ' %'


def dia(x) -> str:
    if not x:
        return '-'
    if isinstance(x, (dt.date, dt.datetime)):
        return x.strftime('%d/%m/%Y')
    s = str(x)
    return f'{s[8:10]}/{s[5:7]}/{s[:4]}' if re.match(r'\d{4}-\d{2}-\d{2}', s) else s


def curto(x) -> str:
    a = abs(float(x or 0))
    t = br(a / 1e6, 2) + ' mi' if a >= 1e6 else br(a / 1e3, 1) + ' mil' if a >= 1e3 else br(a, 0)
    return ('-' if x and x < 0 else '') + 'R$ ' + t


def rotulo(a: int, m: int) -> str:
    return f'{MESES[m - 1]}/{a % 100:02d}'


def comp(a: int, m: int) -> str:
    return f'{m:02d}/{a}'


def quando(dias: int) -> str:
    if dias < 0:
        return f'venceu há {-dias} dia' + ('s' if dias < -1 else '')
    return 'vence hoje' if dias == 0 else 'vence amanhã' if dias == 1 else f'faltam {dias} dias'


def pdf_href(nome: str) -> str:
    return urllib.parse.quote(nome)


# ------------------------------------------------------------------ icones de linha (24x24, cor do texto)
ICONES = {
    'inicio': '<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
    'carteira': '<rect x="3" y="6" width="18" height="14" rx="2"/><path d="M3 10h18M16 15h2"/>',
    'grafico': '<path d="M4 20V11M10 20V5M16 20v-8M21 20H3"/>',
    'moeda': ('<circle cx="12" cy="12" r="9"/><path d="M14.8 9.4c-.5-.9-1.5-1.4-2.8-1.4-1.6 0-2.8.8-2.8 2s1.2 1.6 '
              '2.8 1.9 2.8.8 2.8 2-1.2 2.1-2.8 2.1c-1.3 0-2.4-.5-2.9-1.4M12 6.5v11"/>'),
    'recibo': '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6M9 16h3"/>',
    'escudo': '<path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
    'alerta': '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17h.01"/>',
    'doc': '<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5M10 13h6M10 17h6"/>',
    'calc': ('<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 7h8M8 11h1M12 11h1M16 11h0M8 15h1M12 15h1'
             'M8 18h1M12 18h1M16 15v3"/>'),
    'elo': ('<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/>'
            '<path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>'),
    'livro': '<path d="M4 5h6a2 2 0 0 1 2 2v13a2 2 0 0 0-2-2H4zM20 5h-6a2 2 0 0 0-2 2v13a2 2 0 0 1 2-2h6z"/>',
    'balanca': '<path d="M12 4v16M6 7h12M6 7l-3 7h6zM18 7l-3 7h6zM8 20h8"/>',
    'queda': '<path d="M3 7l6 6 4-4 8 8"/><path d="M21 12v5h-5"/>',
    'relogio': '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    'presente': ('<rect x="3" y="9" width="18" height="12" rx="1"/><path d="M12 9v12M3 13h18M12 9c-1.5-3.5-5.5-4-5.5-1.5'
                 'S10 9 12 9zm0 0c1.5-3.5 5.5-4 5.5-1.5S14 9 12 9z"/>'),
    'pessoa': '<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/>',
    'pasta': '<path d="M3 6h6l2 2h10v11H3z"/>',
    'ok': '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>',
    'lupa': '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
}


def ic(nome: str) -> str:
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true">{ICONES.get(nome, "")}</svg>')


# ------------------------------------------------------------------ pecas de HTML
def card(titulo: str, corpo: str, icone: str = '', classe: str = '', acao: str = '') -> str:
    return (f'<article class="card {classe}"><header><h2>{ic(icone) if icone else ""}{e(titulo)}</h2>{acao}</header>'
            f'{corpo}</article>')


def _cel(i: int, c: str, nums, tag: str = 'td') -> str:
    return f'<{tag} class="n">{c}</{tag}>' if i in nums else f'<{tag}>{c}</{tag}>'


def tabela(cab, linhas, nums=(), total=None, vazio: str = 'Nada no período.', classes=None) -> str:
    """`linhas` e `total` com celulas ja em HTML; `nums` = indices das colunas de numero (alinhadas a direita);
    `classes` = classe de cada linha ("grupo" para a linha de titulo de um bloco)."""
    if not linhas and not total:
        return f'<p class="vazio">{e(vazio)}</p>'
    h = ''.join(_cel(i, e(c), nums, 'th') for i, c in enumerate(cab))
    corpo = []
    for k, ln in enumerate(linhas):
        cl = (classes or {}).get(k) if isinstance(classes, dict) else None
        corpo.append((f'<tr class="{cl}">' if cl else '<tr>') + ''.join(_cel(i, c, nums) for i, c in enumerate(ln)) +
                     '</tr>')
    if total:
        corpo.append('<tr class="total">' + ''.join(_cel(i, c, nums) for i, c in enumerate(total)) + '</tr>')
    return f'<div class="rolagem"><table><thead><tr>{h}</tr></thead><tbody>{"".join(corpo)}</tbody></table></div>'


def botao(txt: str, href: str, contorno: bool = False, fora: bool = False, id_: str = '') -> str:
    alvo = ' target="_blank" rel="noopener noreferrer"' if fora else ''
    ident = f' id="{id_}"' if id_ else ''
    return f'<a class="botao{" contorno" if contorno else ""}" href="{e(href)}"{alvo}{ident}>{e(txt)}</a>'


def chip_longo(txt: str, tipo: str) -> str:
    """Chip com o texto ate o primeiro ': ' e o resto embaixo, quebrando linha (o chip inteiro cortava na tela
    estreita)."""
    curto, _, resto = txt.partition(': ')
    return chip(curto, tipo) + (f'<small class="q rot">{e(resto)}</small>' if resto else '')


def chip(txt: str, tipo: str = 'info') -> str:
    return f'<span class="chip {tipo}">{e(txt)}</span>'


def kv(pares) -> str:
    """[(rotulo, valor em HTML)] ou [(rotulo, valor, True)] para a linha de total."""
    out = []
    for p in pares:
        forte = ' class="forte"' if len(p) > 2 and p[2] else ''
        out.append(f'<dt{forte}>{e(p[0])}</dt><dd{forte}>{p[1]}</dd>')
    return '<dl class="kv">' + ''.join(out) + '</dl>'


def lista(itens) -> str:
    """[(chip em HTML ou '', texto em HTML)]."""
    if not itens:
        return '<p class="vazio">Nada pendente.</p>'
    return '<ul class="lista">' + ''.join(f'<li>{c}<span>{t}</span></li>' for c, t in itens) + '</ul>'


def pagina(id_: str, titulo: str, sub: str, corpo: str) -> str:
    return (f'<section class="pagina" id="p-{id_}"><h1>{e(titulo)}</h1>' + (f'<p class="sub">{sub}</p>' if sub else '') +
            corpo + '</section>')


def barras(itens, vazio: str = 'Sem dado no período.') -> str:
    """[(rotulo, valor, observacao)]: uma barra por linha (le bem no celular), zero no meio quando ha negativo."""
    vals = [float(v) for _, v, _ in itens if v]
    if not vals:
        return f'<p class="vazio">{e(vazio)}</p>'
    vmax, vmin = max(vals + [0.0]), min(vals + [0.0])
    amp = (vmax - vmin) or 1.0
    z = -vmin / amp * 100
    out = []
    for rot, v, obs in itens:
        barra = ''
        if v is not None and round(float(v), 2) != 0:
            w = abs(float(v)) / amp * 100
            esq = z if v > 0 else z - w
            barra = (f'<span class="b-barra {"pos" if v > 0 else "neg"}" '
                     f'style="left:{esq:.2f}%;width:{max(w, 0.6):.2f}%"></span>')
        eixo = f'<span class="b-eixo" style="left:{z:.2f}%"></span>' if vmin < 0 else ''
        nota = f'<small>{e(obs)}</small>' if obs else ''
        out.append(f'<div class="b-linha"><span class="b-rot">{e(rot)}{nota}</span><span class="b-trilho">{eixo}{barra}'
                   f'</span><span class="b-val">{val(v, "R$ 0,00") if v is not None else "sem dado"}</span></div>')
    return '<div class="barras">' + ''.join(out) + '</div>'


def rosca(fatias, centro: str, sub: str) -> str:
    """[(rotulo, valor)] em rosca (circunferencia 100: o traco de cada fatia e a fatia em %)."""
    total = sum(v for _, v in fatias) or 1.0
    segs, acum, leg = [], 0.0, []
    for i, (rot, v) in enumerate(fatias):
        p = v / total * 100
        cor = CORES[i % len(CORES)]
        segs.append(f'<circle r="15.9155" cx="21" cy="21" fill="none" stroke="{cor}" stroke-width="5.2" '
                    f'stroke-dasharray="{p:.3f} {100 - p:.3f}" stroke-dashoffset="{25 - acum:.3f}"/>')
        acum += p
        leg.append(f'<li><i style="background:{cor}"></i><span>{e(rot)}</span><b>{e(rs(v))}</b>'
                   f'<small>{e(pc(p))} do total</small></li>')
    svg = (f'<svg class="rosca" viewBox="0 0 42 42" role="img" aria-label="{e(sub)}: {e(centro)}">'
           '<circle r="15.9155" cx="21" cy="21" fill="none" stroke="#eef2f7" stroke-width="5.2"/>' + ''.join(segs) +
           f'<text x="21" y="21" text-anchor="middle" font-size="3.9" font-weight="700" fill="#0a2b51">{e(centro)}</text>'
           f'<text x="21" y="25.6" text-anchor="middle" font-size="2.5" fill="#5b6b80">{e(sub)}</text></svg>')
    return f'<div class="rosca-caixa">{svg}<ul class="legenda">{"".join(leg)}</ul></div>'


# ------------------------------------------------------------------ leitura dos dados
def _ler(arq: pathlib.Path, padrao, avisos: list):
    if not arq.exists():
        return padrao
    try:
        return json.loads(arq.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError) as x:
        avisos.append(f'{arq.name} não pôde ser lido ({type(x).__name__}) e ficou de fora do painel.')
        return padrao


def _janela(ano: int, mm: int, n: int = 12) -> list[tuple[int, int]]:
    out = []
    for i in range(n - 1, -1, -1):
        a, m = divmod(ano * 12 + mm - 1 - i, 12)
        out.append((a, m + 1))
    return out


def _seguinte(a: int, m: int) -> tuple[int, int]:
    return a + m // 12, m % 12 + 1


def _dia_preco(out: dict | None) -> str | None:
    for c in (out or {}).get('dados', {}).get('situacao', {}).get('conferencia', []):
        m = re.match(r'Preços de fechamento de (\d\d/\d\d/\d{4})', c)
        if m:
            return m.group(1)
    return None


def _quadro(out: dict) -> dict:
    return {q['tipo']: q for q in out['dados']['operacoes']['quadro']}


def _resultado_total(out: dict) -> float:
    return float(sum(out['apuracao']['resultados'].values()))


def _lista_darfs(hist, snap, ests, cur, of, reg, hoje) -> list[dict]:
    """Todos os DARFs que se conhece (pagina DARF da IRTrade, historico e fechamentos do agente) com a situacao: pago
    (informado ou achado no Open Finance), abaixo de R$ 10, sem dado (venceu antes do inicio do extrato), sem
    pagamento achado ou a pagar."""
    ini_of = min((t['data'] for t in of), default=None)
    por: dict[str, dict] = {}
    for d in snap.get('darfs', []):
        por[d['periodo']] = {'periodo': d['periodo'], 'tipo': d.get('tipo', 'RV'), 'valor': float(d['valor']),
                             'vencimento': None, 'fonte': 'IRTrade'}
    for d in hist.get('darfs', []):
        ant = por.get(d['periodo'], {})
        por[d['periodo']] = {'periodo': d['periodo'], 'tipo': ant.get('tipo', 'RV'), 'valor': float(d['valor']),
                             'vencimento': d.get('vencimento'), 'fonte': d.get('fonte', 'IRTrade')}
    for x in ests:
        if x['resumo'].get('darf'):
            p = comp(x['ano'], x['mes'])
            ant = por.get(p)
            por[p] = {'periodo': p, 'tipo': 'RV', 'valor': float(x['resumo']['darf']),
                      'vencimento': x['resumo']['vencimento'], 'fonte': 'agente',
                      'irtrade': ant['valor'] if ant and ant['fonte'] == 'IRTrade' else None}
    parcial = None
    if cur and cur['out']['apuracao']['darf'] and cur['out']['dados']['parcial']:
        r = cur['out']['apuracao']
        parcial = {'periodo': comp(r['ano'], r['mes']), 'tipo': 'RV', 'valor': float(r['darf']),
                   'vencimento': r['vencimento'].strftime('%d/%m/%Y'), 'fonte': 'agente, parcial'}
    pagos = reg.get('pagos') or {}
    itens = []
    for d in list(por.values()) + ([parcial] if parcial else []):
        mm, aa = (int(x) for x in d['periodo'].split('/'))
        venc = (dt.datetime.strptime(d['vencimento'], '%d/%m/%Y').date() if d.get('vencimento')
                else apuracao.vencimento_darf(aa, mm))
        dias = (venc - hoje).days
        info = pagos.get(f'{aa}-{mm:02d}')
        t = None if info or d is parcial else (
            mes.pagamento_darf(of, mes.fim_do_mes(aa, mm), d['valor']) if of else None)
        if d is parcial:
            sit, cl = 'parcial: o mês ainda não acabou', 'cinza'
        elif info:
            sit, cl = (f"pago em {dia(info['data'])}" if info.get('data') else 'pago, sem a data') + \
                f" ({info.get('fonte', 'informado')})", 'ok'
        elif t:
            sit, cl = f"pago em {t['data']:%d/%m/%Y} (Open Finance)", 'ok'
        elif d['valor'] < apuracao.DARF_MINIMO:
            sit, cl = 'abaixo de R$ 10: soma no imposto dos meses seguintes (Lei 9.430/1996, art. 68)', 'info'
        elif not of or (ini_of and venc < ini_of):
            sit, cl = 'sem dado: venceu antes do início do Open Finance', 'cinza'
        elif dias < 0:
            sit, cl = 'sem pagamento achado', 'erro'
        else:
            sit, cl = f'a pagar: {quando(dias)}', 'alerta'
        itens.append({**d, 'venc': venc, 'vencimento': venc.strftime('%d/%m/%Y'), 'dias': dias, 'situacao': sit,
                      'classe': cl, 'pago_em': (info or {}).get('data') or (t['data'].isoformat() if t else None)})
    return sorted(itens, key=lambda x: (int(x['periodo'][3:]), int(x['periodo'][:2])), reverse=True)


def _classe_alerta(a: str) -> tuple[str, str]:
    if a.startswith('A CONFERIR'):
        return 'A conferir', 'alerta'
    if a.startswith(('Nota ', 'Liquidação')):
        return 'Nota', 'erro'
    if a.startswith('Custódia '):
        return 'Custódia', 'alerta'
    if a.startswith('Vencimento de '):
        return 'Vencimento', 'info' if 'nenhuma está do lado' in a else 'alerta'
    if a.startswith('Na B3: '):
        return 'Evento', 'info'
    if ' vence em ' in a and ('(put de' in a or '(call de' in a):
        return 'Opção', 'alerta' if 'exercício gera' in a else 'info'
    if a.startswith(('Open Finance', 'Sem preço', 'Sem o extrato', 'Eventos da B3')):
        return 'Dado', 'alerta'
    return 'Aviso', 'info'


def _opcoes(out: dict | None, base: pathlib.Path, hoje: dt.date) -> list[dict]:
    """Cada opcao da carteira com o subjacente no fechamento e o que o exercicio faria (IN 1.585, art. 60)."""
    if not out:
        return []
    pos = [p for p in out['estado']['posicoes'] if p['classe'] == 'opcao' and p['qtd']]
    if not pos:
        return []
    dp = _dia_preco(out) or out['dados']['data_posicao']
    pregao = dt.datetime.strptime(dp, '%d/%m/%Y').date()
    subs = sorted({p['subjacente'] for p in pos if p.get('subjacente')})
    cot = precos.fechamento(pregao, subs, base / 'cache' / 'precos') if subs else {}
    precos_op = {ln['ticker']: ln for k in ('opcoes_vendidas', 'opcoes_compradas') for ln in out['dados']['posicoes'][k]}
    res = []
    for p in sorted(pos, key=lambda p: (p.get('vencimento') or '9999', p['ticker'])):
        venc = dt.date.fromisoformat(p['vencimento']) if p.get('vencimento') else None
        sub = cot.get(p.get('subjacente') or '')
        k, q = p.get('strike'), p['qtd']
        tipo = 'put' if p.get('tipo_opcao') == 'put' else 'call'
        dentro = None
        if sub and k:
            dentro = sub['preco'] < k if tipo == 'put' else sub['preco'] > k
        premio = -p['custo'] if q < 0 else p['custo']
        custo_acao = None
        if q < 0 and k:       # lancador: put -> compra com o premio no custo; call -> venda com o premio no preco
            custo_acao = k - premio / abs(q) if tipo == 'put' else k + premio / abs(q)
        txt = ''
        if q < 0 and dentro:
            lado = 'compra' if tipo == 'put' else 'venda'
            txt = (f'Se ficar assim, o exercício gera a {lado} de {qt(abs(q))} {p["subjacente"]} a R$ {br(k)} '
                   f'(R$ {br(abs(q) * k)})' +
                   (f'; custo para o imposto de R$ {br(custo_acao)} por ação (strike menos o prêmio recebido, '
                    'IN RFB 1.585/2015, art. 60, § 1º).' if tipo == 'put' else
                    f'; preço de venda para o imposto de R$ {br(custo_acao)} por ação (strike mais o prêmio, '
                    'IN RFB 1.585/2015, art. 60, II).'))
        elif q < 0 and dentro is False:
            txt = 'Fora do dinheiro: se ficar assim, vira pó no vencimento e o prêmio fica como ganho (art. 60, § 3º).'
        res.append({'ticker': p['ticker'], 'tipo': tipo, 'sub': p.get('subjacente'), 'strike': k, 'venc': venc,
                    'dias': (venc - hoje).days if venc else None, 'qtd': q, 'premio': premio,
                    'preco': (precos_op.get(p['ticker']) or {}).get('preco'), 'sub_preco': sub['preco'] if sub else None,
                    'sub_dia': sub['dia'] if sub else None, 'dentro': dentro, 'custo_acao': custo_acao, 'texto': txt})
    return res


def _rotina_parada(ultima: str | None, hoje: dt.date) -> list[str]:
    """A tarefa agendada roda em dia util; sem rodada desde antes do ultimo dia util, ela parou."""
    d = dt.date.fromisoformat(ultima[:10]) if ultima else None
    if not d or d >= mes.ultimo_pregao(hoje - dt.timedelta(1)):
        return []
    return [f'A rotina diária do contador não roda desde {d:%d/%m}: ela precisa do Mac ligado e do app do Claude aberto '
            'de manhã (dias úteis, 9h10). Quando voltar a rodar, ela busca as notas e fecha os meses que ficaram para '
            'trás.']


def _eventos_b3(base: pathlib.Path, hoje: dt.date, parada: bool, avisos: list) -> dict:
    """Ultima leitura dos eventos societarios na B3 (eventos_b3.json, gravado pela rotina) e os eventos que o motor
    conhece; leitura velha so vira alerta quando a rotina esta rodando (parada, o alerta da rotina ja diz)."""
    lido = _ler(base / 'eventos_b3.json', {}, avisos)
    em = dt.datetime.fromisoformat(lido['lido_em']) if lido.get('lido_em') else None
    al = []
    if em and lido.get('erros'):
        al.append(f"Eventos da B3 sem resposta na leitura de {em:%d/%m} para {', '.join(lido['erros'])}: vale a leitura "
                  'anterior dessas empresas.')
    if em and not parada and em.date() < mes.ultimo_pregao(hoje - dt.timedelta(1)):
        al.append(f'Eventos da B3 não são lidos desde {em:%d/%m}: a rotina diária lê a B3 em todo dia útil; sem a leitura, '
                  'bonificação, desdobramento ou grupamento novo não entra na carteira.')
    return {'lido_em': em, 'desde': lido.get('desde'), 'erros': lido.get('erros') or [], 'lista': eventos.carrega(base),
            'alertas': al}


def _pendencias(cur, fechadas, darfs, avisos, conf, opcoes, ecac=None, saude=None) -> list[dict]:
    """Lista unica (pagina Pendencias, cartao Ola, quadrinho do CPF e selo do menu contam esta mesma lista)."""
    out = []

    def add(tipo, texto, nivel, origem):
        if texto and not any(x['texto'] == texto for x in out):
            out.append({'tipo': tipo, 'texto': texto, 'nivel': nivel, 'origem': origem})

    for a in (saude or {}).get('of') or []:
        add('Integração', a, 'erro' if 'venceu em' in a else 'alerta', 'Open Finance')
    for a in (saude or {}).get('rotina') or []:
        add('Integração', a, 'alerta', 'rotina diária')
    for a in (saude or {}).get('eventos') or []:
        add('Integração', a, 'alerta', 'eventos da B3')

    for d in darfs:
        if d['classe'] == 'erro':
            add('DARF', f"DARF de {d['periodo']} (R$ {br(d['valor'])}, venceu em {d['vencimento']}): não achei o "
                'pagamento na conta do Safra pelo Open Finance. Se pagou por outro banco, avise na sessão para eu '
                'registrar; se não pagou, dá para pagar com multa e juros calculados pelo Sicalc (Lei 9.430/1996, '
                'art. 61).', 'erro', 'DARFs')
    sem = [d for d in darfs if d['classe'] == 'cinza' and 'Open Finance' in d['situacao']]
    if sem:
        add('DARF', f"{len(sem)} DARFs da IRTrade ({sem[-1]['periodo']} a {sem[0]['periodo']}) venceram antes do início "
            'do Open Finance: o pagamento deles não dá para conferir por aqui. Quem confirma é o comprovante de pagamento '
            'do e-CAC; a situação fiscal sem pendência não prova que o DARF foi pago.',
            'info', 'DARFs')
    if cur:
        r = cur['out']['apuracao']
        for a in cur['out']['dados']['situacao']['alertas']:
            if a.startswith(('DARF de ', 'Vendas de ações no mês até agora')):
                continue
            tipo, nivel = _classe_alerta(a)
            add(tipo, a, nivel, f"mês {comp(r['ano'], r['mes'])}")
    for v in fechadas:
        r = v['out']['apuracao']
        for a in v['out']['dados']['situacao']['alertas']:
            if a.startswith(('A CONFERIR', 'Nota ', 'Liquidação')):
                tipo, nivel = _classe_alerta(a)
                add(tipo, a, nivel, f"mês {comp(r['ano'], r['mes'])}")
    for a in avisos:
        add('Dado', a, 'alerta', 'painel')
    for o in opcoes:      # REGRAS.md, "a conferir" 3
        if o['qtd'] < 0 and o['tipo'] == 'put' and o['dentro'] and o['dias'] is not None and 0 <= o['dias'] <= 31:
            add('A conferir', f"Exercício de {o['ticker']} em {dia(o['venc'])}: conferir se a nota do Safra traz a "
                f"compra de {o['sub']} como exercício (mercado \"EXERC OPC VENDA\") e se o custo ficou em "
                f"R$ {br(o['custo_acao'])} por ação (strike menos o prêmio, IN RFB 1.585/2015, art. 60, § 1º).",
                'alerta', 'regras a conferir')
    for _, _, rat in _rateios(conf):
        if rat.get('decisao') == 'pendente' and rat.get('texto'):
            add('Decisão', rat['texto'], 'alerta', 'conferência com a IRTrade')
    for x in (ecac or {}).get('pendencias') or []:
        add('Receita', f"{x.get('descricao') or '-'}: {x.get('situacao') or ''}".rstrip(': '), 'alerta', 'e-CAC')
    for x in (ecac or {}).get('debitos') or []:
        add('Receita', f"Débito no e-CAC: {x.get('descricao') or '-'}" +
            (f", R$ {br(x['valor'])}" if isinstance(x.get('valor'), (int, float)) else '') +
            (f", vencimento {x['vencimento']}" if x.get('vencimento') else '') + '.', 'erro', 'e-CAC')
    for x in (ecac or {}).get('lacunas') or []:     # tela do e-CAC que nao abriu na leitura: lacuna declarada
        add('Receita', x, 'info', 'e-CAC')
    return sorted(out, key=lambda x: NIVEL[x['nivel']])


def _rateios(conf: dict | None):
    """Notas com a venda dividida entre operacao comum e day trade, anotadas em conferencias.json como
    "nota_<numero>" (o que a nota mostra) e "rateio_<numero>" (a decisao): (numero, texto, rateio)."""
    nums = {m.group(1) for k in conf or {} if (m := re.fullmatch(r'(?:nota|rateio)_(\d+)', k))}
    for n in sorted(nums):
        yield n, str(conf.get(f'nota_{n}') or ''), conf.get(f'rateio_{n}') or {}


def _valores_anual(an: dict) -> dict:
    return {k: float(an.get(DO_ANUAL[k], 0.0) or 0.0) if k in DO_ANUAL else 0.0 for k in COLS_12M + ('despesas', 'impostos')}


def _doze(janela, visoes, fechados, atual, snap, hist, limite_hist) -> list[dict]:
    """Os 12 meses do consolidado: fechamento do agente, mes em curso, retrato da IRTrade (so meses que ela
    consolidou) e, por ultimo, o historico do relatorio da IRTrade."""
    cs = snap.get('consolidado_12m') or {}
    idx = {k: i for i, k in enumerate(cs.get('colunas', []))}
    linhas_snap = {row[idx['mes']]: row for row in cs.get('linhas', [])} if 'mes' in idx else {}
    ult_cons = snap.get('ultimo_consolidado') or ''
    ajs = mes.ajustes_irtrade(hist)
    out = []
    for a, m in janela:
        chave = f'{a}-{m:02d}'
        vals, fonte = None, 'sem dado'
        if (a, m) in fechados:
            vals, fonte = _valores_anual(fechados[(a, m)]['anual']), 'agente'
        elif (a, m) == atual and (a, m) in visoes:
            vals, fonte = _valores_anual(visoes[(a, m)]['out']['estado']['anual']), 'agente, parcial'
        elif chave in linhas_snap and chave <= ult_cons:
            row = linhas_snap[chave]
            vals = {k: float(row[idx[k]] or 0.0) if k in idx else 0.0 for k in COLS_12M + ('despesas', 'impostos')}
            fonte = 'IRTrade'
        elif str(a) in hist.get('anual', {}) and (a, m) <= limite_hist:
            an = hist['anual'][str(a)]
            vals = {k: float((an.get(DO_ANUAL[k]) or [0.0] * 12)[m - 1] or 0.0) if k in DO_ANUAL else 0.0
                    for k in COLS_12M + ('despesas', 'impostos')}
            fonte = 'IRTrade (relatório)'
        if vals is None:
            out.append({'mes': (a, m), 'fonte': fonte, 'vals': None, 'soma': None, 'id': None, 'liquido': None})
            continue
        meus = [x for x in ajs if (x['ano'], x['mes']) == (a, m)] if fonte.startswith('IRTrade') else []
        for x in meus:      # decisao do titular sobre o numero dela (historico.json, 'ajustes')
            vals[x['tipo']] = round(vals[x['tipo']] + x['delta'], 2)
        if meus:
            fonte += ', ajustado'
        soma = sum(vals[k] for k in COLS_12M)
        idd = vals['impostos'] + vals['despesas']
        out.append({'mes': (a, m), 'fonte': fonte, 'vals': vals, 'soma': soma, 'id': idd, 'liquido': soma + idd})
    return out


def _ajusta_rv(row: dict, ajs: list[dict], carry: dict) -> str:
    """Linha da ficha da IRTrade com os ajustes do mes e com o prejuizo que um ajuste de mes anterior mudou (`carry`,
    por tipo); refaz resultado, base, prejuizo e imposto. Imposto a pagar e pago ficam como ela emitiu: se o imposto
    devido mudar, a fonte avisa (pede DARF complementar, conta que o painel nao faz). Devolve o sufixo da fonte."""
    imp0, mudou = row.get('imposto_total') or 0.0, False
    for tipo, sfx in (('comum', 'comum'), ('daytrade', 'dt')):
        meus = [x for x in ajs if x['tipo'] == tipo]
        if not meus and not carry[tipo]:
            continue
        mudou = True
        for x in meus:
            k = f"{'opcao' if x['classe'] == 'opcao' else 'vista'}_{sfx}"
            row[k] = round((row.get(k) or 0.0) + x['delta'], 2)
        res = round((row.get(f'resultado_{sfx}') or 0.0) + sum(x['delta'] for x in meus), 2)
        ant = round((row.get(f'negativo_anterior_{sfx}') or 0.0) + carry[tipo], 2)
        prej_ir = row.get(f'prejuizo_{sfx}') or 0.0
        base_ = round(max(res + ant, 0.0), 2)
        row.update({f'resultado_{sfx}': res, f'negativo_anterior_{sfx}': ant, f'base_{sfx}': base_,
                    f'prejuizo_{sfx}': round(min(res + ant, 0.0), 2),
                    f'imposto_{sfx}': round(base_ * apuracao.ALIQ[tipo], 2)})
        carry[tipo] = round(row[f'prejuizo_{sfx}'] - prej_ir, 2)
    if not mudou:
        return ''
    row['imposto_total'] = round((row.get('imposto_comum') or 0.0) + (row.get('imposto_dt') or 0.0), 2)
    return ', ajustado' + (' (o imposto do mês mudou)' if abs(row['imposto_total'] - imp0) > 0.004 else '')


def _ficha_rv(snap, visoes, darfs, ano: int, ate: int, ajs=()) -> list[tuple]:
    rv = snap.get('renda_variavel_2026') if ano == 2026 else None
    idx = {k: i for i, k in enumerate((rv or {}).get('colunas', []))}
    ult_cons = snap.get('ultimo_consolidado') or ''
    pagos = {d['periodo'] for d in darfs if d['classe'] == 'ok'}
    carry = {'comum': 0.0, 'daytrade': 0.0}
    out = []
    for m in range(1, ate + 1):
        v = visoes.get((ano, m))
        if v:
            r = v['out']['apuracao']
            lin = {ln['tipo']: ln for ln in r['linhas']}
            encs = r['encerramentos']

            def parte(tipo, opcao):
                return sum(x.resultado for x in encs if x.tipo == tipo and (x.classe == 'opcao') == opcao)
            c, d_ = lin['comum'], lin['daytrade']
            row = {'vista_comum': parte('comum', False), 'opcao_comum': parte('comum', True),
                   'resultado_comum': c['resultado'], 'negativo_anterior_comum': c['prejuizo_anterior'],
                   'base_comum': c['base'], 'prejuizo_comum': c['prejuizo'], 'imposto_comum': c['imposto'],
                   'vista_dt': parte('daytrade', False), 'opcao_dt': parte('daytrade', True),
                   'resultado_dt': d_['resultado'], 'negativo_anterior_dt': d_['prejuizo_anterior'],
                   'base_dt': d_['base'], 'prejuizo_dt': d_['prejuizo'], 'imposto_dt': d_['imposto'],
                   'imposto_total': c['imposto'] + d_['imposto'], 'irrf_mes': r['irrf_mes'],
                   'irrf_anterior': round(r['saldo'].irrf + r['irrf_usado'] - r['irrf_mes'], 2),
                   'irrf_compensar': r['saldo'].irrf, 'irrf_dt': None, 'imposto_pagar': r['darf'],
                   'imposto_pago': r['darf'] if comp(ano, m) in pagos else 0.0}
            out.append((m, row, 'agente, parcial' if v['out']['dados']['parcial'] else 'agente'))
        elif rv and m <= len(rv['linhas']) and f'{ano}-{m:02d}' <= ult_cons:
            row = {k: rv['linhas'][m - 1][i] for k, i in idx.items()}
            suf = _ajusta_rv(row, [x for x in ajs if (x['ano'], x['mes']) == (ano, m)], carry)
            out.append((m, row, 'IRTrade' + suf))
        else:
            out.append((m, None, 'sem dado'))
    return out


def _ficha_fii(snap, hist, visoes, ano: int, ate: int, limite_hist) -> tuple[list, str | None]:
    """FII mes a mes: 20% com prejuizo que so compensa FII (IN 1.585, art. 37). Meses da IRTrade refeitos a partir
    do saldo do fim do ano anterior; meses do agente direto da apuracao."""
    prej = (snap.get(f'saldos_fim_{ano - 1}') or {}).get('fii')
    cs = snap.get('consolidado_12m') or {}
    idx = {k: i for i, k in enumerate(cs.get('colunas', []))}
    linhas_snap = {row[idx['mes']]: row for row in cs.get('linhas', [])} if 'mes' in idx else {}
    ult_cons = snap.get('ultimo_consolidado') or ''
    fii_hist = ((hist.get('anual') or {}).get(str(ano)) or {}).get('FII')
    out, confere = [], None
    for m in range(1, ate + 1):
        v = visoes.get((ano, m))
        if v:
            ln = {x['tipo']: x for x in v['out']['apuracao']['linhas']}['fii']
            out.append((m, ln['resultado'], ln['prejuizo_anterior'], ln['base'], ln['prejuizo'], ln['imposto'], 'agente'))
            prej = ln['prejuizo']
            continue
        chave = f'{ano}-{m:02d}'
        res = None
        if chave in linhas_snap and chave <= ult_cons and 'fii' in idx:
            res = float(linhas_snap[chave][idx['fii']] or 0.0)
        elif fii_hist and (ano, m) <= limite_hist:
            res = float(fii_hist[m - 1] or 0.0)
        if res is None or prej is None:
            out.append((m, None, None, None, None, None, 'sem dado'))
            continue
        meus = [x for x in mes.ajustes_irtrade(hist) if (x['ano'], x['mes'], x['tipo']) == (ano, m, 'fii')]
        res = round(res + sum(x['delta'] for x in meus), 2)
        acum = res + prej
        base_, novo = max(acum, 0.0), min(acum, 0.0)
        imp = round(base_ * apuracao.ALIQ['fii'], 2)
        out.append((m, res, prej, base_, novo, imp, 'IRTrade, ajustado' if meus else 'IRTrade'))
        prej = novo
    darf_mai = (snap.get('fii_2026') or {}).get('darf_mai') if ano == 2026 else None
    if darf_mai is not None and len(out) >= 5 and out[4][5] is not None:
        confere = (f'Refeito aqui, maio dá R$ {br(out[4][5])} de imposto de FII: '
                   + ('confere com o DARF de 05/2026 da IRTrade.' if abs(out[4][5] - darf_mai) < 0.005 else
                      f'a IRTrade cobrou R$ {br(darf_mai)}.'))
    return out, confere


def _proventos_ano(of, ano: int, hoje: dt.date) -> list[tuple]:
    """[(linha do extrato, nome, valor, lancamentos)] do ano, na ordem de NOMES_PROVENTO."""
    if not of:
        return []
    lanc = mes.lancamentos_bolsa(of, dt.date(ano, 1, 1), min(hoje, dt.date(ano, 12, 31)), [])
    tipos: dict[str, list] = {}
    for t in lanc:
        g = tipos.setdefault(t['linha'], [0.0, 0])
        g[0] += t['valor']
        g[1] += 1
    return [(k, NOMES_PROVENTO[k], round(tipos[k][0], 2), tipos[k][1]) for k in NOMES_PROVENTO if k in tipos]


def _tabela_proventos(pr: list[tuple]) -> str:
    """Proventos recebidos com o total e, separados, os custos do aluguel de acoes (o liquido no fim)."""
    rec = [x for x in pr if x[0] not in CUSTOS_ALUGUEL]
    cus = [x for x in pr if x[0] in CUSTOS_ALUGUEL]
    linhas, classes = [[e(n), e(str(q)), val(v)] for _, n, v, q in rec], {}
    total = ['Total recebido', '', val(sum(x[2] for x in rec))] if rec else None
    if rec and cus:
        classes[len(linhas)] = 'total'
        linhas.append(total)
        classes[len(linhas)] = 'grupo'
        linhas.append(['Custos do aluguel de ações', '', ''])
        linhas += [[e(n), e(str(q)), val(v)] for _, n, v, q in cus]
        total = ['Líquido', '', val(sum(x[2] for x in pr))]
    return tabela(('Tipo', 'Lançamentos', 'Valor'), linhas, (1, 2), total, vazio='Sem lançamentos no Open Finance.',
                  classes=classes)


def _documentos(base: pathlib.Path, visoes: dict, of: list) -> list[dict]:
    todas = notas.ler_pasta(base / 'notas', ativos.carrega_extra(base / 'tickers.json')) + mes.manuais(base)
    casadas, faltando = set(), set()
    for v in visoes.values():
        con = v['out']['conciliacao']
        if con:
            casadas |= {n.numero for _, n in con['casadas'] if n.numero != 'manual'}
            faltando |= {n.numero for n in con['sem_lancamento']}
    ultimo_of = max((t['data'] for t in of), default=None)
    ini = min((dt.date(a, m, 1) for a, m in visoes), default=None)
    out = []
    for n in sorted(todas, key=lambda n: (n.pregao, n.numero), reverse=True):
        if n.numero == 'manual':
            sit = ('lançamento à mão', 'info')
        elif n.numero in casadas:
            sit = ('conferida no Open Finance', 'ok')
        elif n.numero in faltando and ultimo_of and n.liquidacao and n.liquidacao <= ultimo_of:
            sit = ('liquidação não achada no Open Finance', 'erro')
        elif n.liquidacao and ultimo_of and n.liquidacao > ultimo_of:
            sit = (f'liquida em {n.liquidacao:%d/%m}: o Open Finance ainda não leu', 'alerta')
        elif ini and n.pregao < ini:
            sit = ('mês anterior ao agente', 'cinza')
        else:
            sit = ('sem conferência', 'cinza')
        out.append({'numero': n.numero, 'pregao': n.pregao, 'liquidacao': n.liquidacao, 'liquido': n.liquido,
                    'negocios': len(n.negocios), 'irrf': n.irrf, 'situacao': sit})
    return out


def _conferencia(snap, conf, fechados) -> dict:
    """Agente x IRTrade: os meses que os dois apuraram (ao vivo, do retrato) e o cartao de 12 meses dela."""
    res = {'meses': [], 'doze': None}
    rv = snap.get('renda_variavel_2026') or {}
    idx = {k: i for i, k in enumerate(rv.get('colunas', []))}
    extrato = mes.meses_irtrade(snap)
    for (a, m), est in sorted(fechados.items()):
        if a != 2026 or not idx or m > len(rv.get('linhas', [])):
            continue
        row = {k: rv['linhas'][m - 1][i] for k, i in idx.items()}
        if not row.get('resultado_comum') and not row.get('imposto_pagar'):
            continue
        irrf_ir = round((row.get('irrf_mes') or 0) + (row.get('irrf_anterior') or 0) - (row.get('irrf_compensar') or 0), 2)
        rs_ = est['resumo']
        ext = extrato.get(f'{a}-{m:02d}') or {}
        res['meses'].append({'mes': (a, m), 'linhas': [
            ('Resultado das operações comuns', row.get('resultado_comum'), rs_['resultados'].get('comum')),
            ('Resultado do day trade', row.get('resultado_dt'), rs_['resultados'].get('daytrade')),
            ('Imposto do mês', row.get('imposto_total'), rs_['imposto_bruto']),
            ('IR retido abatido', irrf_ir, rs_['irrf_usado']),
            ('DARF', row.get('imposto_pagar'), rs_['darf'])] + [
            (nome[0].upper() + nome[1:], ext[chave], est['anual'].get(linha))
            for linha, chave, nome in mes.CONFERE_EXTRATO if chave in ext]})
    cs = snap.get('consolidado_12m') or {}
    ci = {k: i for i, k in enumerate(cs.get('colunas', []))}
    if cs.get('linhas') and ci:
        bruto = sum(float(row[ci[k]] or 0) for row in cs['linhas'] for k in COLS_12M if k in ci)
        idd = sum(float(row[ci['impostos']] or 0) + float(row[ci['despesas']] or 0) for row in cs['linhas'])
        res['doze'] = {'bruto': round(bruto, 2), 'id': round(idd, 2), 'liquido': round(bruto + idd, 2),
                       'meses': (cs['linhas'][0][ci['mes']], cs['linhas'][-1][ci['mes']]),
                       'irtrade': (conf or {}).get('irtrade_12m')}
    return res


def dados(base: pathlib.Path, bruto: dict | None = None, hoje: dt.date | None = None) -> dict:
    """Tudo o que a pagina mostra, ja calculado pelo motor (nada aqui grava)."""
    base = pathlib.Path(base)
    hoje = hoje or dt.date.today()
    avisos: list[str] = []
    tit = json.loads((base / 'titular.json').read_text())
    hist = _ler(base / 'historico.json', {}, avisos)
    conf = _ler(base / 'conferencias.json', {}, avisos)
    ecac = _ler(base / 'ecac.json', None, avisos)
    reg = _ler(base / 'estado' / 'diario.json', {}, avisos)
    retratos = sorted((base / 'irtrade').glob('*.json')) if (base / 'irtrade').is_dir() else []
    snap = _ler(retratos[-1], {}, avisos) if retratos else {}
    of = mes.transacoes_of(bruto) if bruto else []
    part = _ler(base / 'partida.json', {}, avisos)
    ests = mes.estados(base)
    fechados = {(x['ano'], x['mes']): x for x in ests}
    if ests:
        ultimo = (ests[-1]['ano'], ests[-1]['mes'])
    else:
        d0 = dt.date.fromisoformat(part['data'])
        ultimo = (d0.year, d0.month)
    limite_hist = (dt.date.fromisoformat(part['data']).year, dt.date.fromisoformat(part['data']).month) \
        if part.get('data') else (0, 0)
    atual = _seguinte(*ultimo)
    janela = _janela(*atual)
    visoes: dict[tuple, dict] = {}
    for am in janela:
        if am not in fechados:
            continue
        out = mes.fecha_mes(base, am[0], am[1], bruto, hoje, gravar=False)
        est, r = fechados[am], out['apuracao']
        prej = {k: float(v) for k, v in r['saldo'].prejuizos.items()}
        if abs(r['darf'] - est['resumo']['darf']) > 0.005 or \
                any(abs(prej[k] - est['saldo']['prejuizos'].get(k, 0.0)) > 0.005 for k in prej):
            avisos.append(f"{comp(*am)}: o fechamento gravado tem DARF de R$ {br(est['resumo']['darf'])}; refeito agora, "
                          f"com as notas e o Open Finance de hoje, dá R$ {br(r['darf'])}. A rotina diária refaz o "
                          'fechamento e manda o e-mail CORRIGIDO até o vencimento.')
        visoes[am] = {'out': out, 'status': 'fechado', 'estado': est}
    cur = None
    if dt.date(atual[0], atual[1], 1) <= hoje:
        out = mes.fecha_mes(base, atual[0], atual[1], bruto, hoje, gravar=False)
        cur = {'out': out, 'status': 'parcial' if out['dados']['parcial'] else 'a fechar', 'estado': None}
        visoes[atual] = cur
        if not out['dados']['parcial']:
            avisos.append(f'{comp(*atual)} já acabou e ainda não foi fechado: a rotina diária fecha quando o Open '
                          'Finance ler o último dia útil do mês.')
        if mes.fim_do_mes(*_seguinte(*atual)) < hoje:
            avisos.append('Há mais de um mês sem fechamento: a rotina diária fecha um por vez, em ordem.')
    ult = visoes.get(ultimo) if ultimo in fechados else None
    ref = cur or ult
    darfs = _lista_darfs(hist, snap, ests, cur, of, reg, hoje)
    vigente = next((x for x in darfs if x['periodo'] == comp(*ultimo) and x['fonte'] == 'agente'), None) \
        if ultimo in fechados else None
    opcoes = _opcoes(ref['out'] if ref else None, base, hoje)
    fechadas = [v for am, v in sorted(visoes.items()) if v['status'] == 'fechado']
    saude = {'of': mes.saude_of(bruto, hoje), 'rotina': _rotina_parada(reg.get('ultima'), hoje)}
    evb3 = _eventos_b3(base, hoje, bool(saude['rotina']), avisos)
    saude['eventos'] = evb3['alertas']
    avisos += mes.confere_irtrade(base)
    pend = _pendencias(cur, fechadas, darfs, avisos, conf, opcoes, ecac, saude)
    ano_ir = atual[0] if cur else ultimo[0]
    ate_ir = atual[1] if cur and atual[0] == ano_ir else 12 if ano_ir < hoje.year else ultimo[1]
    ficha_fii, confere_fii = _ficha_fii(snap, hist, visoes, ano_ir, ate_ir, limite_hist)
    lido = dt.datetime.fromisoformat(bruto['lido_em']) if bruto and bruto.get('lido_em') else None
    return {
        'hoje': hoje, 'gerado': dt.datetime.now(), 'nome': (tit.get('nome') or '').split()[0].title(),
        'corretora': tit.get('corretora', 'SAFRA CORRETORA'), 'avisos': avisos, 'atual': atual, 'ultimo': ultimo,
        'janela': janela, 'visoes': visoes, 'fechados': fechados, 'cur': cur, 'ult': ult, 'ref': ref,
        'darfs': darfs, 'vigente': vigente, 'opcoes': opcoes, 'pendencias': pend,
        'doze': _doze(janela, visoes, fechados, atual, snap, hist, limite_hist),
        'ano_ir': ano_ir, 'ficha_rv': _ficha_rv(snap, visoes, darfs, ano_ir, ate_ir, mes.ajustes_irtrade(hist)),
        'ficha_fii': ficha_fii, 'confere_fii': confere_fii, 'proventos_ano': _proventos_ano(of, ano_ir, hoje),
        'documentos': _documentos(base, visoes, of),
        'aluguel': aluguel.ler_pasta(base / 'aluguel') if (base / 'aluguel').is_dir() else [],
        'arquivos': [(p.name, dt.datetime.fromtimestamp(p.stat().st_mtime)) for p in
                     sorted((base / 'saida').glob('*.pdf')) if PDF_OK.fullmatch(p.name)] if (base / 'saida').is_dir()
        else [],
        'emails': reg.get('emails') or {}, 'rotina': reg.get('ultima'), 'saude': saude, 'conf': conf,
        'conferencia': _conferencia(snap, conf, fechados), 'ecac': ecac, 'eventos': evb3,
        'snap': {k: snap.get(k) for k in ('lido_em', 'ultimo_consolidado', 'ultima_nota', 'provisionados')},
        'of_lido': lido, 'of_ini': min((t['data'] for t in of), default=None),
        'of_fim': max((t['data'] for t in of), default=None), 'dia_preco': _dia_preco(ref['out'] if ref else None),
    }


# ------------------------------------------------------------------ paginas
def _status_mes(v: dict) -> str:
    if v['status'] == 'fechado':
        g = (v.get('estado') or {}).get('gerado_em')
        return chip(f'fechado em {dia(g)}' if g else 'fechado', 'ok')
    if v['status'] == 'parcial':
        return chip(f"parcial até {dia(v['out']['estado']['corte'])}", 'alerta')
    return chip('mês acabou: espera o fechamento', 'alerta')


def _pdfs_mes(d: dict, a: int, m: int) -> str:
    nomes = {n for n, _ in d['arquivos']}
    rel, darf = f'Relatorio mensal {m}-{a}.pdf', f'DARF {m}-{a}.pdf'
    bs = []
    if darf in nomes:
        bs.append(botao('Imprimir DARF', pdf_href(darf)))
    if rel in nomes:
        bs.append(botao('Relatório mensal (PDF)', pdf_href(rel), contorno=True))
    return f'<div class="botoes">{"".join(bs)}</div>' if bs else ''


def _pior(ps: list[dict]) -> str:
    """Cor do chip pela pendencia mais grave ('ok' quando nao ha nenhuma)."""
    return min((p['nivel'] for p in ps), key=NIVEL.get, default='ok')


def _cartao_cpf(d: dict) -> str:
    ec = d['ecac'] or {}
    decl = ec.get('declaracoes') or []
    if decl:
        u = decl[0]
        t1 = (chip(str(u.get('situacao') or '-'), 'ok' if 'process' in str(u.get('situacao', '')).lower() else 'alerta') +
              f"<p>Exercício {e(u.get('exercicio'))}, {e(u.get('tipo') or '')}</p>")
    else:
        t1 = chip('Não consultada', 'cinza') + '<p>precisa do seu login gov.br no e-CAC</p>'
    erros = [x for x in d['darfs'] if x['classe'] == 'erro']
    deb_rf = ec.get('debitos') or []
    if erros or deb_rf:
        soma = sum(x['valor'] for x in erros)
        t2 = (chip(f'{len(erros) + len(deb_rf)} a conferir', 'erro') +
              (f'<p>{len(erros)} DARF{"s" if len(erros) != 1 else ""} sem pagamento achado no Safra ({e(rs(soma))})</p>'
               if erros else '') +
              (f'<p>{len(deb_rf)} débito{"s" if len(deb_rf) != 1 else ""} no e-CAC</p>' if deb_rf else ''))
    else:
        t2 = chip('Nenhum achado', 'ok') + '<p>pelo Open Finance' + (' e pelo e-CAC' if ec else '') + '</p>'
    n = len(d['pendencias'])
    t3 = chip(f'{n} pendência{"s" if n != 1 else ""}', _pior(d['pendencias'])) + '<p>notas, opções, regras a conferir</p>'
    return ('<div class="tiles">'
            f'<a class="tile" href="#cpf">{ic("doc")}<b>Declaração IR</b>{t1}</a>'
            f'<a class="tile" href="#darf">{ic("recibo")}<b>Débitos (DARFs)</b>{t2}</a>'
            f'<a class="tile" href="#pendencias">{ic("alerta")}<b>Pendências</b>{t3}</a></div>')


def _previsao(out: dict) -> list[tuple]:
    tipos = {p['ticker']: p.get('tipo_opcao') for p in out['estado']['posicoes']}
    tabs = out['dados']['posicoes']
    grupos = {'Ações': tabs['acoes'], 'FII': tabs['fii'], 'Opção de Compra': [], 'Opção de Venda': [],
              'Termo': tabs['termos'], 'Outros': tabs['btc'] + tabs['fii_vendidas']}
    for ln in tabs['opcoes_vendidas'] + tabs['opcoes_compradas']:
        grupos['Opção de Venda' if tipos.get(ln['ticker']) == 'put' else 'Opção de Compra'].append(ln)
    out_ = []
    for rot, ls in grupos.items():
        inv = sum(x['investido'] for x in ls)
        vl = sum(x['valor'] or 0.0 for x in ls)
        out_.append((rot, inv, vl, vl - inv, any(x['valor'] is None for x in ls)))
    return out_


def _pg_inicio(d: dict) -> str:
    cur, ult, ref, vig = d['cur'], d['ult'], d['ref'], d['vigente']
    cards = []
    # 1. Ola
    itens = []
    if vig:
        pago = vig['classe'] == 'ok'
        itens.append((chip('pago' if pago else 'a pagar', 'ok' if pago else 'alerta'),
                      f"DARF de {e(vig['periodo'])}: <b>{e(rs(vig['valor']))}</b>, código {apuracao.CODIGO_DARF}, "
                      f"vence em {e(vig['vencimento'])}" + ('' if pago else f" ({e(quando(vig['dias']))})")))
    elif ult:
        itens.append((chip('sem DARF', 'ok'), f"{e(comp(*d['ultimo']))} fechado sem imposto a pagar."))
    if cur:
        r = cur['out']['apuracao']
        itens.append((chip('em curso', 'info'),
                      f"{e(comp(r['ano'], r['mes']))} apurado até {e(dia(cur['out']['estado']['corte']))}: " +
                      (f"imposto de {e(rs(r['devido']))} se fechasse hoje." if r['devido'] else
                       'sem imposto até agora.')))
    erros = [x for x in d['darfs'] if x['classe'] == 'erro']
    if erros:
        itens.append((chip(f'{len(erros)} DARFs', 'erro'),
                      'antigos sem pagamento achado no Open Finance: ' + e(', '.join(x['periodo'] for x in erros)) +
                      '. <a href="#darf">Ver DARFs</a>'))
    if d['pendencias']:
        n = len(d['pendencias'])
        itens.append((chip(f"{n} pendência{'s' if n != 1 else ''}", _pior(d['pendencias'])),
                      '<a href="#pendencias">Ver pendências</a>'))
    lido = f"Open Finance lido em {d['of_lido']:%d/%m às %Hh%M}" if d['of_lido'] else 'Sem leitura do Open Finance'
    cards.append(card(f"Olá, {d['nome']}" if d['nome'] else 'Olá', lista(itens) + f'<p class="nota">{e(lido)}; '
                      f"preços da B3 de {e(d['dia_preco'] or '-')}.</p>", 'pessoa'))
    # 2. Documentos pendentes?
    sem_nota = [t for v in d['visoes'].values() if v['out']['conciliacao'] for t in v['out']['conciliacao']['sem_nota']]
    docs_erro = [x for x in d['documentos'] if x['situacao'][1] == 'erro']
    esperando = [x for x in d['documentos'] if x['situacao'][1] == 'alerta']
    conferidas = sum(1 for x in d['documentos'] if x['situacao'][1] == 'ok')
    falta = [(chip('falta nota', 'erro'), f"Liquidação de {e(rs(t['valor']))} em {t['data']:%d/%m} sem nota no e-mail.")
             for t in sem_nota]
    falta += [(chip('sem lançamento', 'erro'), f"Nota {e(x['numero'])} de {x['pregao']:%d/%m} não aparece no Open "
               'Finance.') for x in docs_erro]
    espera = [(chip('aguardando', 'info'), f"Nota {e(x['numero'])} de {x['pregao']:%d/%m}: {e(x['situacao'][0])}.")
              for x in esperando]
    corpo = lista(falta) if falta else (
        f'<p class="tudo-ok">{ic("ok")}<span>Nenhum documento pendente: {conferidas} notas conferidas com as '
        'liquidações do Open Finance.</span></p>')
    if espera:
        corpo += '<h3>Aguardando a liquidação</h3>' + lista(espera)
    cards.append(card('Documentos pendentes?', corpo, 'doc', acao=botao('Ver notas', '#documentos', contorno=True)))
    # 3. Ultimo mes consolidado
    if ult:
        r = ult['out']['apuracao']
        corpo = (f'<p class="rot">Competência {e(comp(*d["ultimo"]))} {_status_mes(ult)}</p>' + kv([
            ('Resultado das operações', val(_resultado_total(ult['out']), 'R$ 0,00')),
            ('Prejuízo anterior abatido', e(rs(sum(x['prejuizo_usado'] for x in r['linhas']), 'R$ 0,00'))),
            ('Imposto', e(rs(r['imposto_bruto'], 'R$ 0,00'))), ('IR retido abatido', e(rs(r['irrf_usado'], 'R$ 0,00'))),
            ('DARF', e(rs(r['darf'], 'R$ 0,00')), True)]) + _pdfs_mes(d, *d['ultimo']))
    else:
        corpo = '<p class="vazio">Nenhum mês fechado pelo agente ainda.</p>'
    cards.append(card('Último Mês Consolidado', corpo, 'grafico'))
    # 4. DARF do mes
    if vig:
        sit = chip(vig['situacao'], vig['classe'])
        corpo = (f'<p class="rot">Competência {e(vig["periodo"])} · código {apuracao.CODIGO_DARF}</p>'
                 f'<p class="grande">{e(rs(vig["valor"]))}</p><p>Vence em <b>{e(vig["vencimento"])}</b> {sit}</p>' +
                 _pdfs_mes(d, *d['ultimo']) +
                 '<p class="nota">No app do Safra: Pagamentos &gt; Tributos &gt; DARF, digitando os campos 02 a 10 '
                 '(<a href="#darf">ver os campos</a>). PDF com senha: os 5 primeiros dígitos do CPF.</p>')
    else:
        corpo = (f'<p class="rot">Competência {e(comp(*d["ultimo"]))}</p><p class="grande">R$ 0,00</p>'
                 '<p class="nota">Sem imposto a pagar no último mês fechado.</p>')
    cards.append(card('DARF do Mês', corpo, 'recibo'))
    # 5. Prejuizos a compensar
    if ref:
        pj = ref['out']['apuracao']['saldo'].prejuizos
        corpo = kv([('Operações comuns', val(pj.get('comum', 0.0), 'R$ 0,00')),
                    ('Day trade', val(pj.get('daytrade', 0.0), 'R$ 0,00')), ('FII', val(pj.get('fii', 0.0), 'R$ 0,00'))]) + (
            f"<p class=\"nota\">Saldo depois de {e(comp(*(d['atual'] if cur else d['ultimo'])))}"
            f"{' (parcial)' if cur and cur['out']['dados']['parcial'] else ''}. Prejuízo comum abate lucro de ações, "
            'opções e termo; o de day trade só abate day trade; o de FII só abate FII (IN RFB 1.585/2015, art. 64 e '
            'parágrafo único; art. 65, § 10; art. 37).</p>')
    else:
        corpo = '<p class="vazio">Sem apuração.</p>'
    cards.append(card('Prejuízos a Compensar', corpo, 'queda'))
    # 6. Monitoramento de CPF
    cards.append(card('Monitoramento de CPF', _cartao_cpf(d), 'escudo',
                      acao=botao('Ver tudo', '#cpf', contorno=True)))
    # 7. Posicao de carteira
    if ref:
        dd = ref['out']['dados']
        fatias = [(x['mercado'], abs(x['investido'])) for x in dd['resumo_posicao'] if abs(x['investido']) > 0.004]
        tot = sum(v for _, v in fatias)
        vendida = any(x['investido'] < -0.004 for x in dd['resumo_posicao'])
        corpo = rosca(fatias, curto(tot), 'investido') + (
            f'<p class="nota">{e(d["corretora"])} · posição de {e(dd["data_posicao"])}, pelo valor investido (como a '
            'IRTrade).' + (' A opção vendida entra pelo prêmio recebido, sem o sinal; por isso o total passa o da '
                           'Previsão de Resultados, que desconta esse prêmio.' if vendida else '') + '</p>')
    else:
        corpo = '<p class="vazio">Sem posição.</p>'
    cards.append(card('Posição de Carteira', corpo, 'carteira',
                      acao=botao('Ver carteira', '#carteira', contorno=True)))
    # 8. Previsao de resultados
    if ref:
        pv = _previsao(ref['out'])
        linhas = [[e(r_), e(rs(i)), e(rs(v)) + (' *' if s else ''), val(lp)] for r_, i, v, lp, s in pv]
        tot = [sum(x[k] for x in pv) for k in (1, 2, 3)]
        corpo = tabela(('Mercado', 'Investido', 'Valor atual', 'Resultado'), linhas, (1, 2, 3),
                       ['Total', e(rs(tot[0])), e(rs(tot[1])), val(tot[2])]) + (
            '<p class="nota">Resultado se tudo fosse encerrado pelo fechamento de ' + e(d['dia_preco'] or '-') +
            ', antes de taxas e imposto' + ('; * há ativo sem preço' if any(x[4] for x in pv) else '') + '.</p>')
    else:
        corpo = '<p class="vazio">Sem posição.</p>'
    cards.append(card('Previsão de Resultados', corpo, 'grafico'))
    # 9. Proventos provisionados
    cards.append(card('Proventos Provisionados', _provisionados(d), 'presente'))
    # 10. Vendas isentas
    if cur:
        r = cur['out']['apuracao']
        vend = r['vendas_acoes']
        lim = apuracao.LIMITE_ISENCAO
        estourou = vend > lim
        corpo = (kv([('Limite do mês', e(rs(lim))), ('Vendido em ações à vista', e(rs(vend, 'R$ 0,00'))),
                     ('Ainda cabe na isenção', e(rs(max(lim - vend, 0.0), 'R$ 0,00')), True)]) +
                 f'<div class="medidor{" estourou" if estourou else ""}"><span style="width:{min(vend / lim * 100, 100):.1f}%">'
                 '</span></div>' +
                 ('<p class="nota"><b>Passou de R$ 20.000,00:</b> o lucro das ações vendidas no mês é tributado.</p>'
                  if estourou else '') +
                 '<p class="nota">Só ações no mercado à vista (IN RFB 1.585/2015, art. 59, I). Ficam de fora day trade, '
                 'ETF de ações, fundo ou clube de ações e a venda por exercício de opção ou no vencimento do termo '
                 '(§ 2º).</p>')
    else:
        corpo = '<p class="vazio">Sem mês em curso.</p>'
    cards.append(card('Vendas Isentas', corpo, 'moeda'))
    # 11. Resultados do mes atual
    if cur:
        q = _quadro(cur['out'])
        linhas = [[e(t), val(q[t]['resultado']), e(rs(q[t]['base'])), e(rs(q[t]['imposto']))]
                  for t in ('Comum', 'Day Trade', 'Fii', 'Isentos')]
        r = cur['out']['apuracao']
        corpo = (f'<p class="rot">{e(comp(r["ano"], r["mes"]))} {_status_mes(cur)}</p>' +
                 tabela(('Tipo', 'Resultado', 'Base', 'Imposto'), linhas, (1, 2, 3),
                        ['Total', val(q['Total']['resultado']), e(rs(q['Total']['base'])), e(rs(q['Total']['imposto']))]) +
                 f"<p class=\"nota\">Se o mês fechasse hoje: DARF de {e(rs(r['darf'], 'R$ 0,00'))}"
                 f"{', vence em ' + r['vencimento'].strftime('%d/%m/%Y') if r['darf'] else ''}.</p>")
    else:
        corpo = '<p class="vazio">Sem mês em curso.</p>'
    cards.append(card('Resultados do Mês Atual', corpo, 'calc',
                      acao=botao('Detalhes', '#resultados', contorno=True)))
    # 12. Resultados consolidados (barras do liquido)
    j0, j1 = d['janela'][0], d['janela'][-1]
    itens = [(rotulo(*x['mes']), x['liquido'], x['fonte'] if x['fonte'] != 'IRTrade' else '') for x in d['doze']]
    cards.append(card(f'Resultados Consolidados {rotulo(*j0)} - {rotulo(*j1)}', barras(itens) +
                      '<p class="nota">Resultado líquido do mês: operações + proventos + aluguel - impostos e despesas. '
                      'Sem marca: números da IRTrade; "agente": apurado aqui.</p>', 'grafico',
                      acao=botao('Tabela', '#consolidado', contorno=True)))
    # 13. Resultados dos ultimos 12 meses
    tot = {k: sum((x['vals'] or {}).get(k, 0.0) for x in d['doze']) for k in COLS_12M + ('impostos', 'despesas')}
    soma = sum(tot[k] for k in COLS_12M)
    idd = tot['impostos'] + tot['despesas']
    pares = [(ROTULOS_12M[k], val(tot[k])) for k in COLS_12M if k != 'incentivadas' or tot[k]]
    pares += [('Soma', val(soma), True), ('Impostos e despesas', val(idd)), ('Líquido', val(soma + idd), True)]
    ir12 = (d['conf'] or {}).get('irtrade_12m') or {}
    nota = ''
    if ir12.get('liquido') is not None:
        nota = (f"<p class=\"nota\">A IRTrade mostra líquido de {e(rs(ir12['liquido']))} neste cartão porque desconta "
                'impostos e despesas duas vezes (<a href="#conferencia">ver a conferência</a>).</p>')
    cards.append(card('Resultados dos Últimos 12 Meses', kv(pares) + nota, 'moeda'))
    # 14. Proventos provisionados dos proximos 12 meses + recebidos
    a0 = d['atual']
    a1 = divmod(a0[0] * 12 + a0[1] - 1 + 11, 12)
    rec = []
    if ref:
        rec = [(rotulo(int(x['rotulo'][3:]), int(x['rotulo'][:2])), x['valor'], '')
               for x in ref['out']['dados']['proventos']['meses_12']]
    cards.append(card(f'Proventos Provisionados {rotulo(*a0)} - {rotulo(a1[0], a1[1] + 1)}', _provisionados(d, curto_=True) +
                      '<h3>Recebidos nos últimos 12 meses</h3>' + barras(rec), 'presente',
                      acao=botao('Proventos', '#proventos', contorno=True)))
    # 15. Guia rapido
    cards.append(card('Guia Rápido', _guia_curto(), 'livro', acao=botao('Guia', '#guia', contorno=True)))
    # 16. Integracoes
    cards.append(card('Integrações', _integracoes(d), 'elo'))
    return '<div class="grade">' + ''.join(cards) + '</div>'


def _provisionados(d: dict, curto_: bool = False) -> str:
    prov = (d['snap'] or {}).get('provisionados')
    if prov:
        linhas = [[e(x.get('ticker')), e(x.get('tipo')), e(dia(x.get('data_com'))), e(dia(x.get('pagamento'))),
                   e(rs(x.get('valor')))] for x in prov]
        return tabela(('Ativo', 'Tipo', 'Data com', 'Pagamento', 'Valor'), linhas, (4,)) + (
            f"<p class=\"nota\">Da página de proventos provisionados da IRTrade, lida em {e(dia(d['snap'].get('lido_em')))}."
            '</p>')
    if curto_:
        return '<p class="vazio">Sem dado de proventos anunciados (detalhe no cartão acima).</p>'
    return ('<p class="vazio">Sem dado: o Open Finance só mostra o que já caiu na conta e a nota de corretagem não traz '
            'provento anunciado. Este cartão precisa de uma fonte de proventos anunciados (data com, data de pagamento '
            'e valor por ação); quando houver, ele mostra aqui.</p>')


def _guia_curto() -> str:
    return ('<ol class="passos">'
            '<li>As notas do Safra chegam por e-mail e o agente importa sozinho, em dias úteis às 9h10.</li>'
            '<li>No começo do mês o agente fecha o anterior: relatório mensal e DARF em PDF, na sessão e no e-mail.</li>'
            '<li>Pague no app do Safra: Pagamentos &gt; Tributos &gt; DARF, campos 02 a 10 (sem código de barras).</li>'
            '<li>Pagou por outro banco? Diga na sessão: "paguei o DARF de 10/2026 em 25/11".</li>'
            '<li>Antes de vender, teste no <a href="#simulador">simulador</a> quanto de imposto a venda gera.</li></ol>')


def _integracoes(d: dict) -> str:
    docs = [x for x in d['documentos'] if x['numero'] != 'manual']
    ult_nota = max((x['pregao'] for x in docs), default=None)
    uc = d['snap'].get('ultimo_consolidado') or ''
    uc = f'{uc[5:7]}/{uc[:4]}' if re.fullmatch(r'\d{4}-\d{2}', uc) else uc or '-'
    ev = d['eventos']
    linhas = [
        ['Notas de corretagem (e-mail do Safra)', chip('ligado', 'ok') if docs else chip('sem notas', 'alerta'),
         e(f'{len(docs)} notas; última de {ult_nota:%d/%m/%Y}' if ult_nota else '-')],
        ['Notas de aluguel de ações (BTC)', chip('ligado', 'ok') if d['aluguel'] else chip('sem notas', 'cinza'),
         e(f"{len(d['aluguel'])} contratos")],
        ['Open Finance (conta do Safra)', chip('sem leitura', 'erro') if not d['of_lido'] else
         chip('atenção', 'alerta') if d['saude']['of'] else chip('ligado', 'ok'),
         e(f"lido em {d['of_lido']:%d/%m às %Hh%M}; lançamentos de {d['of_ini']:%d/%m/%Y} a {d['of_fim']:%d/%m/%Y}")
         if d['of_lido'] and d['of_ini'] else '-'],
        ['Preços de fechamento (B3)', chip('ligado', 'ok') if d['dia_preco'] else chip('sem preço', 'alerta'),
         e(d['dia_preco'] or '-')],
        ['Eventos societários (B3)', chip('sem leitura', 'alerta') if not ev['lido_em'] else
         chip('atenção', 'alerta') if d['saude'].get('eventos') else chip('ligado', 'ok'),
         e(f"lido em {ev['lido_em']:%d/%m às %Hh%M}; " + _n_eventos(len(ev['lista'])) + f" desde {dia(ev['desde'])}")
         if ev['lido_em'] else 'a rotina lê a B3 em todo dia útil'],
        ['IRTrade (retrato do painel)', chip('lido', 'info') if d['snap'].get('lido_em') else chip('sem retrato', 'cinza'),
         e(f"lido em {dia(d['snap']['lido_em'])}; consolidado até {uc}") if d['snap'].get('lido_em') else '-'],
        ['e-CAC (Receita Federal)', chip('lido', 'ok') if d['ecac'] else chip('não conectado', 'cinza'),
         e(f"lido em {dia(d['ecac'].get('lido_em'))}") if d['ecac'] else 'precisa do seu login gov.br'],
        ['Rotina diária do agente', chip('sem rodada', 'alerta') if not d['rotina'] else
         chip('parada', 'alerta') if d['saude']['rotina'] else chip('ligada', 'ok'),
         e(f"última rodada {dia(d['rotina'])} às {d['rotina'][11:16]}") if d['rotina'] else '-'],
    ]
    for ln in linhas:      # o texto da ultima coluna quebra linha em vez de cortar na tela estreita
        ln[2] = f'<span class="q">{ln[2]}</span>'
    return tabela(('Fonte', 'Situação', 'Último dado'), linhas)


def _n_eventos(n: int) -> str:
    return 'nenhum evento' if not n else f'{n} evento' + ('s' if n > 1 else '')


def _card_custodia(cus: dict | None) -> str:
    """Posicao do banco no Open Finance x a do motor no mesmo dia (mes.confere_custodia)."""
    if not cus:
        return ''
    n, k = len(cus['ok']), len(cus['divergencias'])
    cab = (f"Custódia do Safra de {cus['data']:%d/%m/%Y} (Open Finance) contra o motor no mesmo dia: {n} "
           f"{'posição bate' if n == 1 else 'posições batem'} ({cus['acoes']} em ações e {cus['fii']} em FII).")
    if not k:
        return card('Custódia no banco', f"<p>{chip('confere', 'ok')} {e(cab)}</p>"
                    '<p class="nota">O motor anda nota a nota; o banco pode contar o negócio pelo pregão ou pela '
                    'liquidação, e vale qualquer um dos dois.</p>', 'escudo')
    linhas = [[f'<b>{e(x["ticker"])}</b>', e(qt(x['banco'])), e(qt(x['motor'])),
               '<span class="q">' + e('; '.join(x['pistas'])) + '</span>'] for x in cus['divergencias']]
    return card('Custódia no banco', f"<p>{chip(f'{k} diferença' + ('s' if k > 1 else ''), 'alerta')} {e(cab)}</p>" +
                tabela(('Papel', 'No banco', 'No motor', 'Pode ser'), linhas, (1, 2)) +
                '<p class="nota">Enquanto a causa não aparece, o imposto do mês pode estar errado: nota que não chegou '
                'muda o resultado; papel emprestado não muda.</p>', 'escudo', 'largo')


def _card_eventos(ev: dict, aplicados: list) -> str:
    """Eventos societarios da B3 nos papeis da carteira: os que o motor conhece e se ja entraram na posicao."""
    lido = f"lido em {ev['lido_em']:%d/%m às %Hh%M}" if ev['lido_em'] else 'ainda sem leitura'
    desde = dia(ev['desde']) if ev['desde'] else 'a posição de partida'
    feitos = {a['id'] for a in aplicados}
    itens = [(chip('aplicado', 'ok') if eventos.ident(x) in feitos else chip(eventos.NOME.get(x['tipo'], x['tipo']), 'info'),
              e(f"{x['ticker']}: {eventos.texto(x)}") + f'<small class="q rot">{e(x.get("fonte") or "-")}</small>')
             for x in ev['lista']]
    corpo = (f'<p class="rot">{e(lido[0].upper() + lido[1:])}; data com depois de {e(desde)}.</p>' + lista(itens) if itens
             else f'<p>{chip("nenhum", "ok")} Nenhum evento societário nos papéis da carteira com data com depois de '
                  f'{e(desde)} ({e(lido)}).</p>')
    if ev['erros']:
        corpo += f"<p>{chip('sem resposta', 'alerta')} {e(', '.join(ev['erros']))}: vale a leitura anterior.</p>"
    return card('Eventos da B3', corpo + '<p class="nota">Bonificação, desdobramento e grupamento entram na carteira no fim '
                'do dia com; o custo segue a IN RFB 1.585/2015, art. 58 (bonificação pelo valor capitalizado; '
                'desdobramento e grupamento sem mudar o custo total). Os outros eventos viram aviso. Fonte: cadastro de '
                'empresas listadas da B3.</p>', 'presente')


def _card_vencimento(v: dict | None) -> str:
    """Os caminhos das opcoes lancadas que vencem no mes (mes.cenarios_vencimento): DARF, dinheiro e o que fica."""
    if not v:
        return ''
    ops, n = v['opcoes'], len(v['opcoes'])
    linhas = []
    for c in v['cenarios']:
        ex = c['exercidas']
        nome = (('Viram pó' if n > 1 else 'Vira pó') if not ex else ('Todas exercidas' if n > 1 else 'Exercida')
                if len(ex) == n else 'Só ' + ' e '.join(ex) + (' exercidas' if len(ex) > 1 else ' exercida'))
        fica = '<br>'.join(e(f"{qt(x['qtd'])} {t} a PM {rs(x['pm'])}") for t, x in c['posicoes'].items()) or 'nada muda'
        linhas.append([e(nome) + (' ' + chip('provável', 'info') if c['provavel'] else ''), e(rs(c['darf'], 'R$ 0,00')),
                       val(c['caixa'], 'nada'), fica])
    dias = ' e '.join(sorted({f"{o['vencimento']:%d/%m}" for o in ops}))
    puts = [o for o in ops if o['tipo'] == 'put']
    calls = [o for o in ops if o['tipo'] == 'call']
    notas_ = []
    if puts:
        notas_.append('Custo por ação para o imposto se for exercida (strike menos o prêmio, IN RFB 1.585/2015, art. 60, '
                      '§ 1º): ' + ' e '.join(f"{o['subjacente']} {rs(o['unitario'])}" for o in puts) + '.')
    if calls:
        notas_.append('Preço de venda para o imposto se for exercida (strike mais o prêmio, art. 60, II): ' +
                      ' e '.join(f"{o['subjacente']} {rs(o['unitario'])}" for o in calls) + '.')
    if v['sem_preco']:
        notas_.append('Sem preço de ' + ', '.join(v['sem_preco']) + ' para dizer o lado do strike.')
    else:
        d = max(o['dia_preco'] for o in ops)
        notas_.append(f'Provável = o caminho das que estão do lado do exercício no fechamento de {d:%d/%m}.')
    if v['conta']:
        notas_.append(f"Conta corrente: {rs(v['conta']['saldo'], 'R$ 0,00')}" +
                      (f" em {v['conta']['em']:%d/%m às %Hh%M} (Open Finance)." if v['conta']['em'] else '.'))
    titulo = f"Vencimento de {dias}: " + ('os dois caminhos' if len(v['cenarios']) == 2 else 'os caminhos')
    return card(titulo, tabela(('Caminho', 'DARF do mês', 'Dinheiro na liquidação', 'Fica na carteira'), linhas, (1, 2)) +
                ''.join(f'<p>{e(x)}</p>' for x in notas_) +
                f"<p class=\"nota\">{e(v['nota'])} DARF do mês = o parcial até o vencimento. Negativo = sai da conta.</p>",
                'relogio', 'largo')


def _pg_carteira(d: dict) -> str:
    ref = d['ref']
    if not ref:
        return '<p class="vazio">Sem posição.</p>'
    dd = ref['out']['dados']
    tot = dd['total_posicao']
    inv_abs = sum(abs(x['investido']) for x in dd['resumo_posicao']) or 1.0
    res = [[e(x['mercado']), e(rs(x['investido'])), e(rs(x['valor'])), val(x['lp']), e(pc(abs(x['investido']) / inv_abs * 100))]
           for x in dd['resumo_posicao'] if abs(x['investido']) > 0.004 or abs(x['valor']) > 0.004]
    cards = [card('Resumo por mercado', tabela(('Mercado', 'Investido', 'Valor atual', 'Resultado', '% investido'), res,
                                               (1, 2, 3, 4), ['Total', e(rs(tot['investido'])), e(rs(tot['valor'])),
                                                              val(tot['lp']), '100,00 %']) +
                  f'<p class="nota">{e(dd["corretora"])} · posição de {e(dd["data_posicao"])}; preços de fechamento da B3 '
                  f'de {e(d["dia_preco"] or "-")}. Opção vendida entra com o prêmio recebido em negativo.</p>',
                  'carteira', 'largo')]
    cards += [x for x in (_card_custodia(ref['out'].get('custodia')),
                          _card_eventos(d['eventos'], ref['out'].get('eventos') or [])) if x]
    est = {p['ticker']: p for p in ref['out']['estado']['posicoes']}
    for chave, titulo in (('acoes', 'Ações, ETF e BDR'), ('fii', 'Fundos imobiliários (FII)'),
                          ('btc', 'Ações vendidas (BTC)'), ('fii_vendidas', 'FII vendidos')):
        ls = dd['posicoes'][chave]
        if not ls:
            continue
        linhas = [[f'<b>{e(x["ticker"])}</b>', e(x['ativo']), e(qt(x['qtd'])), e(rs(x['pm'])), e(rs(x['investido'])),
                   e(rs(x['preco'])), e(rs(x['valor'])), val(x['lp']), e(pc(x['ganho_pct']))] for x in ls]
        s = mes._soma(ls)
        cards.append(card(titulo, tabela(('Ativo', 'Nome', 'Qtd', 'Preço médio', 'Investido', 'Preço', 'Valor', 'Resultado',
                                          '%'), linhas, (2, 3, 4, 5, 6, 7, 8),
                                         ['Total', '', '', '', e(rs(s['investido'])), '', e(rs(s['valor'])), val(s['lp']), '']),
                          'carteira', 'largo'))
    for chave, titulo in (('opcoes_vendidas', 'Opções vendidas (lançadas)'), ('opcoes_compradas', 'Opções compradas')):
        ls = dd['posicoes'][chave]
        if not ls:
            continue
        linhas = []
        for x in ls:
            p = est.get(x['ticker'], {})
            linhas.append([f'<b>{e(x["ticker"])}</b>', e('put' if p.get('tipo_opcao') == 'put' else 'call'),
                           e(p.get('subjacente') or '-'), e(rs(p.get('strike'))), e(x['vencimento'] or '-'), e(qt(x['qtd'])),
                           e(rs(x['investido'])), e(rs(x['preco'])), e(rs(x['valor'])), val(x['lp'])])
        s = mes._soma(ls)
        cards.append(card(titulo, tabela(('Opção', 'Tipo', 'Ativo-objeto', 'Strike', 'Vencimento', 'Qtd', 'Prêmio',
                                          'Preço', 'Valor', 'Resultado'), linhas, (3, 5, 6, 7, 8, 9),
                                         ['Total', '', '', '', '', '', e(rs(s['investido'])), '', e(rs(s['valor'])),
                                          val(s['lp'])]), 'carteira', 'largo'))
    if d['opcoes']:
        blocos = []
        for o in d['opcoes']:      # um bloco por opcao: a tabela de 9 colunas cortava o texto na tela estreita
            st = (chip('no dinheiro', 'alerta') if o['dentro'] else chip('fora do dinheiro', 'ok') if o['dentro'] is False
                  else chip('sem strike' if o['sub_preco'] and not o['strike'] else 'sem preço', 'cinza'))
            dist = (f"{br((o['sub_preco'] / o['strike'] - 1) * 100, 1)} %" if o['sub_preco'] and o['strike'] else '-')
            venc = e(dia(o['venc'])) + (f' <small class="rot">({e(quando(o["dias"]))})</small>' if o['dias'] is not None
                                        else '')
            blocos.append(
                f'<div class="opc"><div class="opc-cab"><b>{e(o["ticker"])}</b><span class="rot">{e(o["tipo"])} de '
                f'{e(o["sub"] or "-")}</span>{st}</div>' +
                kv([('Vencimento', venc), (f'{o["sub"] or "Ativo-objeto"} no fechamento', e(rs(o['sub_preco']))),
                    ('Strike', e(rs(o['strike']))), ('Distância do strike', e(dist))]) +
                (f'<p>{e(o["texto"])}</p>' if o['texto'] else '') + '</div>')
        cards.append(card('Opções até o vencimento', '<div class="opcs">' + ''.join(blocos) + '</div>' +
                          '<p class="nota">Distância = quanto o ativo-objeto está acima (+) ou abaixo (-) do strike no último '
                          'fechamento. Exercício de put lançada exige o dinheiro da compra na conta na liquidação.</p>',
                          'relogio', 'largo'))
    v = _card_vencimento(ref['out'].get('vencimento'))
    if v:
        cards.append(v)
    return '<div class="grade">' + ''.join(cards) + '</div>'


def _bloco_mes(d: dict, am: tuple, v: dict, visivel: bool) -> str:
    out = v['out']
    dd, r = out['dados'], out['apuracao']
    c = comp(*am)
    q = _quadro(out)
    linhas = [[e(t), val(q[t]['resultado']), e(rs(q[t]['abatido'])), e(rs(q[t]['base'])), e(rs(q[t]['imposto'])),
               val(q[t]['prejuizo']) if t != 'Isentos' else '-'] for t in ('Comum', 'Day Trade', 'Fii', 'Isentos')]
    tot = q['Total']
    quadro = tabela(('Tipo', 'Resultado', 'Prejuízo abatido', 'Base de cálculo', 'Imposto', 'Prejuízo a compensar'),
                    linhas, (1, 2, 3, 4, 5), ['Total', val(tot['resultado']), e(rs(tot['abatido'])), e(rs(tot['base'])),
                                              e(rs(tot['imposto'])), val(tot['prejuizo'])])
    darf_txt = (e(rs(r['darf'])) if r['darf'] else
                ('abaixo de R$ 10: passa para o mês seguinte' if r['devido'] > 0 else 'sem DARF'))
    imp = kv([('Imposto do mês', e(rs(r['imposto_bruto'], 'R$ 0,00'))),
              ('IR retido nas notas do mês', e(rs(r['irrf_mes'], 'R$ 0,00'))),
              ('IR retido abatido (mês e saldo)', e(rs(r['irrf_usado'], 'R$ 0,00'))),
              ('Imposto devido', e(rs(r['devido'], 'R$ 0,00'))), ('DARF (código 6015)', darf_txt, True),
              ('Vencimento', e(r['vencimento'].strftime('%d/%m/%Y'))),
              ('Vendas de ações à vista', e(rs(r['vendas_acoes'], 'R$ 0,00')) + ' ' +
               (chip('isento até R$ 20 mil', 'ok') if r['isento_mes'] else chip('acima de R$ 20 mil', 'alerta')))])
    grupos = []
    for g in dd['operacoes']['grupos']:
        ls = []
        for x in g['linhas']:
            marca = {'vencimento': ' (vencimento)', 'exercicio': ' (exercício)'}.get(x['mercado'], '')
            ls.append([f'<b>{e(x["ticker"])}</b>{e(marca)}', e(x['liq']['data']), e(x['liq']['cv']), e(qt(x['liq']['qtd'])),
                       e(rs(x['liq']['preco'])), e(rs(x['liq']['total'])), e(x['estoque']['data'] or '-'),
                       e(rs(x['estoque']['preco'])), e(rs(x['estoque']['total'])), val(x['comum']), val(x['daytrade'])])
        grupos.append(f'<h3>{e(g["titulo"])}</h3>' + tabela(
            ('Ativo', 'Data', 'C/V', 'Qtd', 'Preço', 'Total', 'Estoque', 'Preço médio', 'Total do estoque', 'Comum',
             'Day trade'), ls, (3, 4, 5, 7, 8, 9, 10), ['Total', '', '', '', '', '', '', '', '', val(g['comum']),
                                                         val(g['daytrade'])]))
    al = [a for a in dd['situacao']['alertas'] if not a.startswith('DARF de ') or a.startswith(f'DARF de {c}:')]
    alertas = lista([(chip(*_classe_alerta(a)) if not a.startswith('DARF de') else chip('DARF', 'alerta'),
                      e(a)) for a in al]) if al else '<p class="vazio">Sem alertas.</p>'
    conf = '<details><summary>Como este mês foi apurado</summary><ul>' + ''.join(
        f'<li>{e(x)}</li>' for x in dd['situacao']['conferencia']) + '</ul></details>'
    corpo = ('<div class="grade">' +
             card(f'Apuração de {c}', f'<p class="rot">{_status_mes(v)}</p>' + quadro + _pdfs_mes(d, *am), 'calc', 'largo') +
             card('Imposto e DARF', imp, 'recibo') + card('Alertas do mês', alertas + conf, 'alerta') +
             card('Operações finalizadas no mês', ''.join(grupos) or '<p class="vazio">Nenhuma operação encerrada no mês.'
                  '</p>', 'grafico', 'largo') + '</div>')
    return f'<div class="bloco-mes" data-comp="{e(c)}"{"" if visivel else " hidden"}>{corpo}</div>'


def _pg_resultados(d: dict) -> str:
    vs = sorted(d['visoes'].items(), reverse=True)
    if not vs:
        return '<p class="vazio">Sem mês apurado.</p>'
    padrao = vs[0][0]
    if d['cur'] and not d['cur']['out']['apuracao']['encerramentos'] and d['ult']:
        padrao = d['ultimo']
    opts = ''.join(f'<option value="{e(comp(*am))}"{" selected" if am == padrao else ""}>{e(comp(*am))} · '
                   f'{e("fechado" if v["status"] == "fechado" else v["status"])}</option>' for am, v in vs)
    sel = f'<div class="seletor"><label class="rot" for="sel-mes">Competência</label><select id="sel-mes" ' \
          f'data-alvo="bloco-mes">{opts}</select></div>'
    return sel + ''.join(_bloco_mes(d, am, v, am == padrao) for am, v in vs)


def _pg_consolidado(d: dict) -> str:
    cols = [k for k in COLS_12M if k != 'incentivadas' or any((x['vals'] or {}).get(k) for x in d['doze'])]
    linhas, tot = [], {k: 0.0 for k in cols + ['id', 'liquido']}
    for x in d['doze']:
        if not x['vals']:
            linhas.append([e(rotulo(*x['mes']))] + ['-'] * (len(cols) + 2) + [chip('sem dado', 'cinza')])
            continue
        for k in cols:
            tot[k] += x['vals'][k]
        tot['id'] += x['id']
        tot['liquido'] += x['liquido']
        linhas.append([e(rotulo(*x['mes']))] + [val(x['vals'][k]) for k in cols] + [val(x['id']), val(x['liquido'])] +
                      [chip(x['fonte'], 'info' if x['fonte'] in ('IRTrade', 'IRTrade, ajustado') else 'ok'
                            if x['fonte'] == 'agente' else 'alerta' if 'parcial' in x['fonte'] else 'cinza')])
    cab = ['Mês'] + [ROTULOS_12M[k] for k in cols] + ['Impostos e despesas', 'Líquido', 'Fonte']
    total = ['Total'] + [val(tot[k]) for k in cols] + [val(tot['id']), val(tot['liquido']), '']
    j0, j1 = d['janela'][0], d['janela'][-1]
    corpo = card(f'Resultados consolidados {rotulo(*j0)} - {rotulo(*j1)}', tabela(
        cab, linhas, tuple(range(1, len(cols) + 3)), total) +
        '<p class="nota">Líquido = operações + proventos + aluguel + bonificações - impostos e despesas. Meses até o último '
        'que a IRTrade consolidou vêm dela; daí em diante, do agente (notas do Safra e Open Finance). Impostos = o DARF '
        'do mês.' + (f' {AJUSTADO}' if any('ajustado' in x['fonte'] for x in d['doze']) else '') + '</p>',
        'grafico', 'largo')
    ir12 = (d['conf'] or {}).get('irtrade_12m')
    if ir12:
        corpo += card('Por que o líquido difere do cartão da IRTrade', f'<p>{e(ir12.get("texto"))}</p>', 'balanca', 'largo')
    return '<div class="grade">' + corpo + '</div>'


def _pg_meuir(d: dict) -> str:
    ano = d['ano_ir']
    fr = d['ficha_rv']
    cab = ['Ficha Renda Variável'] + [MESES[m - 1] for m, _, _ in fr]
    linhas, classes = [], {}
    for rot, k in FICHA_RV:
        if k is None:
            classes[len(linhas)] = 'grupo'
            linhas.append([e(rot)] + [''] * len(fr))
            continue
        linhas.append([e(rot)] + [num(row.get(k)) if row and row.get(k) is not None else '-' for _, row, _ in fr])
    classes[len(linhas)] = 'grupo'
    linhas.append(['Fonte'] + [e(f) for _, _, f in fr])
    rv = card(f'Renda variável {ano}: operações comuns e day trade', tabela(cab, linhas, tuple(range(1, len(fr) + 1)),
                                                                            classes=classes) +
              '<p class="nota">Os campos da ficha "Renda Variável" da declaração, mês a mês. Meses da IRTrade como ela '
              'apurou; meses do agente, pela lei (todas as taxas da nota no custo). No agente o DARF 6015 junta comum, day '
              'trade e FII; na declaração o FII vai na ficha própria (abaixo). IR na fonte do day trade: o agente usa o IR '
              'retido de cada nota, sem separar.' + (f' {AJUSTADO}' if any('ajustado' in f for _, _, f in fr) else '') +
              '</p>', 'doc', 'largo')
    ff = d['ficha_fii']
    cab = ['Fundos imobiliários'] + [MESES[x[0] - 1] for x in ff]
    rotulos = ('Resultado do mês', 'Resultado negativo até o mês anterior', 'Base de cálculo', 'Prejuízo a compensar',
               'Imposto devido (20%)')
    linhas = [[e(rot)] + [num(x[i + 1]) for x in ff] for i, rot in enumerate(rotulos)]
    linhas.append(['Fonte'] + [e(x[6]) for x in ff])
    fii = card(f'Fundos imobiliários {ano}', tabela(cab, linhas, tuple(range(1, len(ff) + 1)), classes={5: 'grupo'}) +
               (f'<p class="nota">{e(d["confere_fii"])}</p>' if d['confere_fii'] else '') +
               '<p class="nota">20% sobre o ganho; prejuízo de FII só compensa ganho de FII (IN RFB 1.585/2015, art. 37).'
               '</p>', 'doc', 'largo')
    ref = d['ref']
    bens = ''
    if ref:
        pos = sorted((p for p in ref['out']['estado']['posicoes'] if p['qtd'] > 0 and p['classe'] != 'opcao'),
                     key=lambda p: (p['classe'], p['ticker']))
        linhas = [[f'<b>{e(p["ticker"])}</b>', e(p['ativo']), e({'acao': 'ação', 'fii': 'FII', 'etf': 'ETF', 'bdr': 'BDR'}
                                                                  .get(p['classe'], p['classe'])),
                   e(qt(p['qtd'])), e(rs(p['custo'])), e(rs(p['custo'] / p['qtd']))] for p in pos]
        bens = card('Bens e direitos: posição a custo', tabela(
            ('Ativo', 'Nome', 'Tipo', 'Qtd', 'Custo total', 'Preço médio'), linhas, (3, 4, 5),
            ['Total', '', '', '', e(rs(sum(p['custo'] for p in pos))), '']) +
            f'<p class="nota">Posição de {e(ref["out"]["dados"]["data_posicao"])} pelo custo de aquisição, com as taxas '
            '(IN RFB 1.585/2015, art. 58). A declaração pede a de 31/12; depois do fechamento de dezembro esta tabela '
            'mostra a de 31/12.</p>', 'pasta', 'largo')
    rend = card(f'Rendimentos recebidos em {ano}', _tabela_proventos(d['proventos_ano']) +
                f'<p class="nota">Do extrato do Open Finance (lançamentos de {e(dia(d["of_ini"]))} em diante), pelo valor '
                'que caiu na conta, já sem o IR retido na fonte quando há. Confira com o informe de rendimentos do '
                'Safra: é ele que vale na declaração.</p>', 'presente', 'largo')
    return '<div class="grade">' + rv + fii + bens + rend + '</div>'


def _pg_proventos(d: dict) -> str:
    ref = d['ref']
    cards = []
    if ref:
        pv = ref['out']['dados']['proventos']
        t = pv['total']
        r = ref['out']['apuracao']
        cards.append(card(f"Proventos de {comp(r['ano'], r['mes'])}" + (' (até agora)' if ref['out']['dados']['parcial'] else ''),
                          kv([('Dividendos', val(t['dividendos'])), ('JCP', val(t['jcp'])),
                              ('Rendimentos', val(t['rendimentos'])), ('Reembolso do aluguel', val(t['reembolso_btc'])),
                              ('Remuneração do aluguel', val(t['rendimentos_btc'])), ('Total', val(t['total']), True)]),
                          'presente'))
        rec = [(rotulo(int(x['rotulo'][3:]), int(x['rotulo'][:2])), x['valor'], '') for x in pv['meses_12']]
        cards.append(card('Recebidos nos últimos 12 meses', barras(rec) +
                          f"<p class=\"nota\">Total de 12 meses: {e(rs(pv['total_12m'], 'R$ 0,00'))}.</p>", 'grafico'))
    cards.append(card(f"{d['ano_ir']} por tipo", _tabela_proventos(d['proventos_ano']) +
                      '<p class="nota">Pelo valor que caiu na conta. O informe de rendimentos do Safra é o que vale na '
                      'declaração.</p>', 'moeda'))
    cards.append(card('Proventos provisionados', _provisionados(d), 'relogio'))
    return '<div class="grade">' + ''.join(cards) + '</div>'


def _pg_darf(d: dict) -> str:
    cards = []
    vig = d['vigente']
    if vig:
        a, m = d['ultimo']
        campos = tabela(('Campo', 'O que digitar'), [
            ['02 Período de apuração', e(mes.fim_do_mes(a, m).strftime('%d/%m/%Y'))],
            ['03 CPF', 'o seu CPF (está no DARF em PDF)'], ['04 Código da receita', apuracao.CODIGO_DARF],
            ['05 Número de referência', 'em branco'], ['06 Data de vencimento', e(vig['vencimento'])],
            ['07 Valor do principal', e(rs(vig['valor']))], ['08 Multa', 'R$ 0,00 (no prazo)'],
            ['09 Juros', 'R$ 0,00 (no prazo)'], ['10 Valor total', f'<b>{e(rs(vig["valor"]))}</b>']])
        cards.append(card(f"DARF de {vig['periodo']}", f'<p class="grande">{e(rs(vig["valor"]))}</p>'
                          f'<p>Vence em <b>{e(vig["vencimento"])}</b> {chip(vig["situacao"], vig["classe"])}</p>' + campos +
                          _pdfs_mes(d, a, m) +
                          '<p class="nota">App do Safra: Pagamentos &gt; Tributos &gt; DARF. O DARF em PDF abre com os 5 '
                          'primeiros dígitos do CPF; o relatório, com os 4 primeiros. Não há código de barras: só o Sicalc '
                          'e o banco geram.</p>', 'recibo', 'largo'))
    linhas = []
    for x in d['darfs']:
        dif = (f"<br><small class=\"rot\">IRTrade: {e(rs(x['irtrade']))}</small>"
               if x.get('irtrade') is not None and abs(x['irtrade'] - x['valor']) > 0.004 else '')
        linhas.append([e(x['periodo']), e(x['tipo']), e(rs(x['valor'])) + dif, e(x['vencimento']),
                       chip_longo(x['situacao'], x['classe']), e(x['fonte'])])
    erros = [x for x in d['darfs'] if x['classe'] == 'erro']
    resumo = ''
    if erros:
        resumo = (f'<p class="aviso erro"><b>{len(erros)} DARFs vencidos sem pagamento achado</b>, '
                  f'{e(rs(sum(x["valor"] for x in erros)))} sem multa e juros: '
                  f'{e(", ".join(x["periodo"] for x in erros))}. Se pagou por outro banco, diga na sessão "paguei o DARF de '
                  'MM/AAAA em DD/MM" e eu registro; se não pagou, o Sicalc calcula a multa (0,33% por dia, até 20%) e os juros '
                  '(Lei 9.430/1996, art. 61).</p>')
    cards.append(card('Todos os DARFs', resumo + tabela(('Período', 'Tipo', 'Valor', 'Vencimento', 'Situação', 'Fonte'),
                                                        linhas, (2,)) +
                      '<div class="botoes">' + botao('Sicalc (DARF com multa e juros)', SICALC, fora=True) +
                      botao('Pagamento em atraso (Receita)', ATRASO, contorno=True, fora=True) + '</div>' +
                      '<p class="nota">Pago = débito de DARF na conta do Safra pelo Open Finance (ou informado por você). '
                      'O Open Finance começa em ' + e(dia(d['of_ini'])) + ': DARF que venceu antes disso fica "sem dado". '
                      'Código 6015 para ações, opções, day trade e FII.</p>', 'recibo', 'largo'))
    return '<div class="grade">' + ''.join(cards) + '</div>'


def _certidao(c: dict | None) -> str:
    """Detalhe da certidao: a validade quando ha uma emitida; senao o que a situacao fiscal disse."""
    if not c:
        return 'emitida no site da Receita'
    if c.get('validade'):
        return e(f"válida até {dia(c['validade'])}")
    return e(c.get('situacao') or 'sem certidão emitida')


def _pg_cpf(d: dict) -> str:
    ec = d['ecac'] or {}
    cards = [card('Monitoramento de CPF', _cartao_cpf(d) +
                  '<p class="nota">Débitos e pendências que o agente vê sozinho: DARFs no Open Finance, notas, opções e '
                  'regras a conferir. Declaração, débitos e pendências na Receita (malha, débito em aberto, certidão) só '
                  'com o seu login gov.br no e-CAC.</p>', 'escudo', 'largo')]
    erros = [x for x in d['darfs'] if x['classe'] == 'erro']
    n_ok = sum(1 for x in d['darfs'] if x['classe'] == 'ok')
    n_sem = sum(1 for x in d['darfs'] if x['classe'] == 'cinza' and 'Open Finance' in x['situacao'])
    docs = [x for x in d['documentos'] if x['numero'] != 'manual']
    extrato = [
        ['DARFs pagos (Open Finance)', chip(f'{len(erros)} sem pagamento', 'erro') if erros else chip('em dia', 'ok'),
         e(f'{n_ok} pagos, {len(erros)} sem pagamento achado, {n_sem} sem dado' +
           (f" (lido às {d['of_lido']:%Hh%M})" if d['of_lido'] else '')),
         e(dia(d['of_lido'].date())) if d['of_lido'] else '-'],
        ['Notas de corretagem', chip('conferidas', 'ok') if not any(x['situacao'][1] == 'erro' for x in docs)
         else chip('falta conferir', 'erro'), e(f"{sum(1 for x in docs if x['situacao'][1] == 'ok')} conferidas no Open Finance"),
         e(dia(d['rotina'])) if d['rotina'] else '-'],
        ['Declaração IR (e-CAC)', chip('consultada', 'ok') if ec.get('declaracoes') else chip('não consultada', 'cinza'),
         (e(f"{len(ec['declaracoes'])} declarações") if ec.get('declaracoes') else 'a tela não abriu na última leitura')
         if ec else 'precisa do login gov.br',
         e(dia(ec.get('lido_em'))) if ec else '-'],
        ['Débitos na Receita (e-CAC)', (chip(f"{len(ec['debitos'])} em aberto", 'erro') if ec.get('debitos') else
                                        chip('nenhum', 'ok')) if ec else chip('não consultado', 'cinza'), e('situação fiscal do CPF') if ec else 'precisa do login gov.br',
         e(dia(ec.get('lido_em'))) if ec else '-'],
        ['Pendências na Receita (e-CAC)', (chip(f"{len(ec['pendencias'])} em aberto", 'alerta') if ec.get('pendencias')
                                           else chip('nenhuma', 'ok')) if ec else chip('não consultado', 'cinza'),
         e('malha e pendências de declaração') if ec else 'precisa do login gov.br', e(dia(ec.get('lido_em'))) if ec else '-'],
        ['Certidão de débitos (CND)', chip(str((ec.get('certidao') or {}).get('tipo') or 'não consultada'),
                                           'ok' if ec.get('certidao') else 'cinza'),
         _certidao(ec.get('certidao')),
         e(dia(ec.get('lido_em'))) if ec.get('certidao') else '-'],
    ]
    for ln in extrato:      # o detalhe quebra linha em vez de empurrar a data para fora da tela estreita
        ln[2] = f'<span class="q">{ln[2]}</span>'
    cards.append(card('Extrato de Processamento', tabela(('Tipo de consulta', 'Situação', 'Detalhe', 'Quando'), extrato),
                      'lupa', 'largo'))
    decl = ec.get('declaracoes') or []
    linhas = [[e(f"{x.get('exercicio') or '-'} / {x.get('ano_calendario') or '-'}"), e(x.get('tipo') or '-'),
               chip(str(x.get('situacao') or '-'), 'ok' if 'process' in str(x.get('situacao', '')).lower() else 'alerta')]
              for x in decl]
    if not linhas:
        linhas = [[e(f'{d["hoje"].year} / {d["hoje"].year - 1}'), '-', chip('não consultada', 'cinza')]]
    cards.append(card('Declaração IR', tabela(('Exercício / Calendário', 'Tipo de declaração', 'Situação'), linhas), 'doc'))
    deb = [[e(x['periodo']), e(rs(x['valor'])), e(x['vencimento']), chip('sem pagamento achado', 'erro')] for x in erros]
    deb += [[e(x.get('descricao') or '-'), e(rs(x.get('valor'))), e(x.get('vencimento') or '-'),
             chip(str(x.get('situacao') or 'e-CAC'), 'erro')] for x in ec.get('debitos') or []]
    cards.append(card('Débitos (DARFs)', tabela(('Débito', 'Valor', 'Vencimento', 'Situação'), deb, (1,),
                                                vazio='Nenhum débito em aberto achado.'), 'recibo'))
    cards.append(card('Pendências', lista([(chip(p['tipo'], p['nivel']), e(p['texto'])) for p in d['pendencias'][:6]]) +
                      (f'<p class="nota"><a href="#pendencias">Ver as {len(d["pendencias"])} pendências</a></p>'
                       if len(d['pendencias']) > 6 else ''), 'alerta'))
    cards.append(card('Ligar a consulta à Receita', (
        '<ol class="passos"><li>Abra o e-CAC no navegador do app do Claude e entre com o seu gov.br (a senha e a '
        'verificação são suas: eu não digito nem respondo).</li><li>Diga na sessão "li o e-CAC" ou "monitora meu CPF".'
        '</li><li>Eu leio as telas da declaração, da situação fiscal e das pendências, só leitura, e guardo o resultado '
        'no seu Mac (ecac.json, fora do git). O painel passa a mostrar tudo aqui.</li></ol>'
        '<div class="botoes">' + botao('Abrir o e-CAC', ECAC, fora=True) +
        botao('Certidão de débitos', CERTIDAO, contorno=True, fora=True) +
        botao('Meu Imposto de Renda', MEU_IR, contorno=True, fora=True) + '</div>'), 'escudo', 'largo'))
    return '<div class="grade">' + ''.join(cards) + '</div>'


def _pg_pendencias(d: dict) -> str:
    ps = d['pendencias']
    cont = {n: sum(1 for p in ps if p['nivel'] == n) for n in NIVEL}
    resumo = ('<p>' + ' '.join(chip(f'{cont[n]} {rot}', n) for n, rot in
                               (('erro', 'urgentes'), ('alerta', 'para olhar'), ('info', 'informativas'))) + '</p>')
    itens = [(chip(p['tipo'], p['nivel']), e(p['texto']) + f' <small class="rot">· {e(p["origem"])}</small>') for p in ps]
    return '<div class="grade">' + card('Pendências', resumo + lista(itens), 'alerta', 'largo') + '</div>'


def _pg_conferencia(d: dict) -> str:
    conf = d['conf'] or {}
    cards = []
    st = conf.get('setembro_2026')
    if st:
        linhas = [[e(x['item']), val(x['irtrade'], 'R$ 0,00'), val(x['agente'], 'R$ 0,00'),
                   f'<span class="q">{e(x["veredito"])}</span>'] for x in st['linhas']]
        cards.append(card('Setembro/2026: agente × IRTrade', f'<p>{e(st["veredito"])}</p>' +
                          tabela(('Item', 'IRTrade', 'Agente', 'Veredito'), linhas, (1, 2)) +
                          f'<p class="nota">{e(st.get("nota"))}</p>', 'balanca', 'largo'))
    for m in d['conferencia']['meses']:
        linhas = []
        for rot, ir, ag in m['linhas']:
            dif = None if ir is None or ag is None else ag - ir
            linhas.append([e(rot), val(ir, 'R$ 0,00'), val(ag, 'R$ 0,00'), val(dif, 'igual')])
        txt = (conf.get('outubro_2026') or {}).get('texto') if m['mes'] == (2026, 10) else ''
        cards.append(card(f"{MESES[m['mes'][1] - 1]}/{m['mes'][0]}: agente × IRTrade (ao vivo)",
                          tabela(('Item', 'IRTrade', 'Agente', 'Diferença'), linhas, (1, 2, 3)) +
                          (f'<p class="nota">{e(txt)}</p>' if txt else ''), 'balanca', 'largo'))
    ir = conf.get('irtrade_12m') or {}
    if all(isinstance(ir.get(k), (int, float)) for k in COLS_12M + ('impostos_despesas',)):
        soma = round(sum(ir[k] for k in COLS_12M), 2)      # os itens do proprio cartao, somados
        idd = ir['impostos_despesas']
        linhas = [['Soma das parcelas', val(ir.get('soma')), val(soma)],
                  ['Impostos e despesas', val(idd), val(idd)],
                  ['Líquido', val(ir.get('liquido')), val(round(soma + idd, 2))]]
        cards.append(card('Cartão "Resultados dos Últimos 12 Meses"', tabela(
            ('Linha', 'Cartão da IRTrade', 'Conta com os itens do cartão'), linhas, (1, 2)) +
            f'<p class="nota">{e(ir.get("texto"))}</p>', 'balanca'))
    for num, txt, rat in _rateios(conf):
        if not txt:
            continue
        decisao = chip('decisão pendente', 'alerta') if rat.get('decisao') == 'pendente' else \
            chip(str(rat.get('decisao')), 'ok')
        cards.append(card(f'Nota {num}: divisão da venda', f'<p>{e(txt)}</p><p>{decisao} {e(rat.get("texto"))}</p>',
                          'doc'))
    if not cards:
        cards.append(card('Conferência', '<p class="vazio">Sem conferência anotada.</p>', 'balanca'))
    return '<div class="grade">' + ''.join(cards) + '</div>'


def _pg_simulador(d: dict) -> str:
    cur = d['cur']
    if not cur or not cur['out']['dados']['parcial']:
        return '<div class="grade">' + card('Simulador', '<p class="vazio">O simulador vale para o mês em curso, que ainda '
                                            'não abriu.</p>', 'calc', 'largo') + '</div>'
    dd = cur['out']['dados']
    opts = []
    for k in ('acoes', 'fii', 'opcoes_vendidas', 'opcoes_compradas', 'btc', 'fii_vendidas'):
        for x in dd['posicoes'][k]:
            p = f' data-preco="{e(br(x["preco"]))}"' if x['preco'] else ''
            opts.append(f'<option value="{e(x["ticker"])}"{p}>{e(x["ticker"])} · {e(qt(x["qtd"]))} · preço médio '
                        f'{e(rs(x["pm"]))}</option>')
    r = cur['out']['apuracao']
    cabe = max(apuracao.LIMITE_ISENCAO - r['vendas_acoes'], 0.0)
    form = (f'<form class="sim" id="form-sim"><label>Ativo<select name="ticker">{"".join(opts)}</select></label>'
            '<label>Operação<select name="cv"><option value="V">Venda</option><option value="C">Compra</option>'
            '</select></label><label>Quantidade<input name="qtd" inputmode="numeric" value="100"></label>'
            '<label>Preço (R$)<input name="preco" inputmode="decimal"></label>'
            '<button class="botao" type="submit">Simular</button></form>')
    corpo = (f'<p>Teste uma operação de hoje dentro de {e(comp(r["ano"], r["mes"]))} e veja o resultado, o imposto e a '
             f'isenção antes de mandar a ordem. Ainda cabem <b>{e(rs(cabe, "R$ 0,00"))}</b> de vendas de ações na isenção '
             'deste mês.</p>' + form + '<div id="sim-saida" class="so-servidor"></div>' +
             '<p class="aviso so-arquivo">O simulador roda pelo servidor do painel: abra http://127.0.0.1:5059 '
             '(python3 ferramentas/local/irbolsa.py painel --servir).</p>' +
             '<p class="nota">Simulação sem taxas nem o IR retido de 0,005%, que diminuem um pouco o resultado. Nada é '
             'gravado.</p>')
    return '<div class="grade">' + card('Simulador de operação', corpo, 'calc', 'largo') + '</div>'


def _pg_documentos(d: dict) -> str:
    docs = d['documentos']
    linhas = [[e(x['numero']), e(dia(x['pregao'])), e(dia(x['liquidacao'])), val(x['liquido']), e(str(x['negocios'])),
               e(rs(x['irrf'])), chip_longo(*x['situacao'])] for x in docs]
    cards = [card('Notas de corretagem', tabela(('Nota', 'Pregão', 'Liquidação', 'Líquido', 'Negócios', 'IR retido',
                                                 'Conferência'), linhas, (3, 4, 5), vazio='Nenhuma nota importada.') +
                  '<p class="nota">Cada nota é conferida com a liquidação do mesmo valor e dia no Open Finance; nota que '
                  'liquida depois da última leitura espera a próxima.</p>', 'doc', 'largo')]
    al = [[e(c.get('nota')), e(c.get('papel')), e(c.get('lado')), e(dia(c.get('abertura'))), e(dia(c.get('vencimento'))),
           e(dia(c.get('liquidacao'))), e(qt(c.get('qtd'))), e(rs(c.get('bruto'))), e(rs(c.get('irrf'))),
           e(rs(c.get('liquido')))] for c in sorted(d['aluguel'], key=lambda c: (c.get('liquidacao') or dt.date.min),
                                                    reverse=True)]
    cards.append(card('Notas de aluguel de ações (BTC)', tabela(
        ('Nota', 'Ativo', 'Lado', 'Abertura', 'Vencimento', 'Liquidação', 'Qtd', 'Bruto', 'IR', 'Líquido'), al,
        (6, 7, 8, 9), vazio='Nenhuma nota de aluguel.'), 'doc', 'largo'))
    arq = [[e(n), e(f'{t:%d/%m/%Y %Hh%M}'), botao('Abrir', pdf_href(n), contorno=True)] for n, t in
           sorted(d['arquivos'], key=lambda x: x[1], reverse=True)]
    cards.append(card('Relatórios e DARFs gerados', tabela(('Arquivo', 'Gerado em', ''), arq, vazio='Nenhum PDF ainda.') +
                      '<p class="nota">Senhas: relatório = 4 primeiros dígitos do CPF; DARF = 5 primeiros.</p>', 'pasta'))
    em = [[e(v.get('assunto') or k), e(dia((v.get('em') or '')[:10])) + (f" às {e(v['em'][11:16])}" if v.get('em') else ''),
           chip('anexo conferido', 'ok') if v.get('anexo_conferido') else chip('enviado', 'info')]
          for k, v in sorted(d['emails'].items(), reverse=True) if isinstance(v, dict)]
    cards.append(card('E-mails enviados', tabela(('Assunto', 'Quando', 'Situação'), em, vazio='Nenhum e-mail registrado.'),
                      'doc', 'largo'))
    return '<div class="grade">' + ''.join(cards) + '</div>'


def _pg_guia(d: dict) -> str:
    termos = (
        ('DARF', 'guia de pagamento de tributo federal; o de bolsa é o código 6015.'),
        ('Operação comum', 'compra e venda em dias diferentes ("swing trade"): 15% sobre o lucro do mês.'),
        ('Day trade', 'compra e venda do mesmo ativo no mesmo dia: 20%, com prejuízo que só abate day trade.'),
        ('Prejuízo a compensar', 'perda que abate o lucro dos meses seguintes, sem prazo.'),
        ('IR retido ("dedo-duro")', '0,005% das vendas e 1% do lucro do day trade; abate o DARF.'),
        ('Isenção de R$ 20 mil', 'lucro com ações à vista isento no mês em que as vendas de ações não passam de R$ 20 mil.'),
        ('BTC', 'aluguel de ações na B3 (Banco de Títulos); a remuneração de quem empresta é tributada como renda fixa, '
                'com retenção pela B3, e não entra no DARF (IN RFB 1.585/2015, art. 73).'),
        ('Sicalc', 'programa da Receita que calcula o DARF com multa e juros.'),
        ('e-CAC', 'portal da Receita com a declaração, os débitos e as pendências do CPF (login gov.br).'),
        ('Open Finance', 'leitura autorizada do extrato do banco: é por ele que o agente confere notas e DARFs pagos.'))
    regras = (
        ('15% nas operações comuns', 'IN RFB 1.585/2015, art. 57'), ('20% no day trade', 'art. 65'),
        ('20% no FII, prejuízo só com FII', 'art. 37'), ('Custo médio ponderado, com as taxas', 'arts. 56 e 58'),
        ('Isenção de R$ 20 mil em ações à vista', 'art. 59, I'), ('Vencimento: último dia útil do mês seguinte', 'art. 56, § 5º'),
        ('DARF abaixo de R$ 10 soma nos meses seguintes', 'Lei 9.430/1996, art. 68'),
        ('Atraso: multa de 0,33% ao dia até 20% e juros', 'Lei 9.430/1996, art. 61'))
    cards = [card('Como o agente trabalha', _guia_curto(), 'livro'),
             card('Regras aplicadas', tabela(('Regra', 'Onde está'), [[e(a), e(b)] for a, b in regras]), 'balanca'),
             card('Termos', kv([(a, e(b)) for a, b in termos]).replace('<dl class="kv">', '<dl class="kv termos">'), 'livro',
                  'largo'),
             card('Comandos (para a sessão)', '<pre class="cmd">python3 ferramentas/local/irbolsa.py painel --servir\n'
                  'python3 ferramentas/local/irbolsa.py apurar\npython3 ferramentas/local/irbolsa.py diario\n'
                  'python3 ferramentas/local/irbolsa.py pago 2026-10 2026-11-25</pre>', 'calc', 'largo')]
    return '<div class="grade">' + ''.join(cards) + '</div>'


# ------------------------------------------------------------------ montagem
CSS = """
:root{--fundo:#f3f4f6;--card:#fff;--tinta:#0a2b51;--titulo:#244b77;--azul:#0d99ff;--verde:#2e7d4f;--vinho:#9b1c3a;
--barra:#b3d4f5;--barra-neg:#e89a9a;--cab:#d9e8f9;--linha:#e4e9f0;--suave:#5b6b80;--ambar:#8a5200;--ambar-fundo:#fff3dc;
--vinho-fundo:#fbe8ec;--verde-fundo:#e5f3ea;--azul-fundo:#e8f2fd;--cinza-fundo:#eef0f3;color-scheme:light}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;background:var(--fundo)}
body{margin:0;background:var(--fundo);color:var(--tinta);
font:14px/1.45 "Montserrat","Avenir Next","Helvetica Neue",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
[hidden]{display:none!important}
a{color:#0b7fd6}
.topo{background:linear-gradient(90deg,#0a2b51,#244b77);color:#fff;padding:14px 24px;display:flex;align-items:center;
justify-content:space-between;gap:8px 16px;flex-wrap:wrap}
.marca{display:flex;align-items:center;gap:10px;font-weight:700;font-size:17px}
.marca svg{width:26px;height:26px}
.marca small{display:block;font-weight:500;font-size:11.5px;opacity:.78}
.topo .direita{display:flex;align-items:center;gap:12px;font-size:12.5px;flex-wrap:wrap}
.topo .botao{background:transparent;border-color:rgba(255,255,255,.65);color:#fff}
.menu{position:sticky;top:0;z-index:5;background:#fff;border-bottom:1px solid var(--linha);display:flex;gap:2px;
overflow-x:auto;padding:0 16px;scrollbar-width:none}
.menu::-webkit-scrollbar{display:none}
.menu a{flex:0 0 auto;color:var(--titulo);text-decoration:none;font-weight:600;font-size:13px;padding:12px 11px 10px;
border-bottom:3px solid transparent;white-space:nowrap}
.menu a.ativo{border-bottom-color:var(--azul);color:var(--tinta)}
.menu .conta{display:inline-block;min-width:18px;padding:0 5px;margin-left:5px;border-radius:9px;background:var(--vinho);
color:#fff;font-size:10.5px;line-height:18px;text-align:center}
main{max-width:1280px;margin:0 auto;padding:22px 24px 40px}
.pagina>h1{font-size:21px;color:var(--titulo);margin:2px 0 4px}
.pagina>.sub{color:var(--suave);margin:0 0 18px;font-size:13px}
.grade{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:18px;align-items:start}
.tudo-ok{display:flex;gap:8px;align-items:flex-start}
.opcs{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:12px}
.opc{border:1px solid var(--linha);border-radius:10px;padding:12px 14px}
.opc-cab{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:0 0 10px}
.opc-cab .chip{margin-left:auto}
.opc .kv{grid-template-columns:auto 1fr}
.opc p{font-size:12.5px;color:var(--suave);margin:10px 0 0}
.tudo-ok svg{width:20px;height:20px;flex:none;color:var(--verde)}
.card{background:var(--card);border-radius:14px;padding:18px 20px;min-width:0;
box-shadow:0 1px 2px rgba(10,43,81,.06),0 6px 18px rgba(10,43,81,.06)}
.card.largo{grid-column:1/-1}
.card>header{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:0 0 12px}
.card h2{display:flex;align-items:center;gap:8px;margin:0;font-size:17.5px;font-weight:700;color:var(--titulo)}
.card h2 svg{width:21px;height:21px;flex:none}
.card h3{font-size:14px;color:var(--titulo);margin:16px 0 8px}
.card p{margin:6px 0}
.grande{font-size:28px;font-weight:700;letter-spacing:-.01em;margin:2px 0!important}
.rot{color:var(--suave);font-size:12px}
.pos{color:var(--verde)}.neg{color:var(--vinho)}
.botao{display:inline-block;background:var(--azul);color:#fff;border:1px solid var(--azul);border-radius:50px;
padding:8px 16px;font-family:inherit;font-size:11px;font-weight:600;line-height:1.2;letter-spacing:.03em;
text-decoration:none;cursor:pointer;white-space:nowrap}
.botao.contorno{background:#fff;color:#0b7fd6}
.botoes{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.rolagem{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th{background:var(--cab);font-weight:600;text-align:left;padding:7px 9px;white-space:nowrap}
th:first-child{border-radius:8px 0 0 8px}th:last-child{border-radius:0 8px 8px 0}
td{padding:7px 9px;border-bottom:1px solid var(--linha);white-space:nowrap;vertical-align:top}
td .q{display:block;white-space:normal;min-width:180px;max-width:460px}
.n{text-align:right;font-variant-numeric:tabular-nums}
tr.total td{font-weight:700;border-bottom:0;border-top:2px solid var(--cab)}
tr.grupo td{background:#f5f8fc;font-weight:700;color:var(--titulo)}
.chip{display:inline-block;border-radius:50px;padding:2px 10px;font-size:11px;font-weight:600;white-space:nowrap}
.lista .chip,td .chip{white-space:nowrap}
.chip.ok{background:var(--verde-fundo);color:var(--verde)}.chip.erro{background:var(--vinho-fundo);color:var(--vinho)}
.chip.alerta{background:var(--ambar-fundo);color:var(--ambar)}.chip.info{background:var(--azul-fundo);color:var(--titulo)}
.chip.cinza{background:var(--cinza-fundo);color:var(--suave)}
.lista{list-style:none;margin:0;padding:0}
.lista li{display:flex;gap:10px;align-items:flex-start;padding:9px 0;border-bottom:1px solid var(--linha);font-size:13px}
.lista li:last-child{border-bottom:0}
.lista li>.chip{flex:none;margin-top:1px}
.kv{display:grid;grid-template-columns:1fr auto;gap:7px 14px;margin:0;font-size:13px}
.kv dt{color:var(--suave)}.kv dd{margin:0;text-align:right;font-weight:600;font-variant-numeric:tabular-nums}
.kv dt.forte,.kv dd.forte{color:var(--tinta);font-weight:700;border-top:1px solid var(--linha);padding-top:7px}
.kv.termos{grid-template-columns:minmax(120px,220px) 1fr}.kv.termos dd{text-align:left;font-weight:400}
.kv.termos dt{color:var(--tinta);font-weight:600}
.tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.tile{border:1px solid var(--linha);border-radius:12px;padding:12px 10px;text-align:center;text-decoration:none;
color:inherit;display:block}
.tile svg{width:26px;height:26px;color:var(--titulo)}
.tile b{display:block;font-size:12.5px;margin:6px 0}
.tile p{margin:6px 0 0;font-size:11.5px;color:var(--suave)}
.medidor{height:10px;background:#e8eef6;border-radius:6px;overflow:hidden;margin:10px 0 6px}
.medidor span{display:block;height:100%;background:var(--azul);border-radius:6px}
.medidor.estourou span{background:var(--vinho)}
.barras{display:flex;flex-direction:column;gap:7px}
.b-linha{display:grid;grid-template-columns:76px minmax(0,1fr) 112px;align-items:center;gap:10px;font-size:12px}
.b-rot{color:var(--suave);white-space:nowrap}
.b-rot small{display:block;font-size:10px;line-height:1.1}
.b-trilho{position:relative;height:12px;background:#f1f4f8;border-radius:6px}
.b-barra{position:absolute;top:0;bottom:0;border-radius:6px}
.b-barra.pos{background:var(--barra)}.b-barra.neg{background:var(--barra-neg)}
.b-eixo{position:absolute;top:-3px;bottom:-3px;width:1px;background:#9fb0c4}
.b-val{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.rosca-caixa{display:flex;align-items:center;gap:18px;flex-wrap:wrap}
.rosca{width:150px;height:150px;flex:none}
.legenda{list-style:none;margin:0;padding:0;flex:1;min-width:180px;font-size:12.5px}
.legenda li{display:grid;grid-template-columns:12px 1fr auto;gap:2px 8px;align-items:center;padding:4px 0}
.legenda i{width:10px;height:10px;border-radius:3px;display:block}
.legenda small{grid-column:2/4;color:var(--suave)}
.aviso{border-radius:12px;padding:11px 14px;margin:0 0 16px;font-size:13px;background:var(--ambar-fundo);color:#5c3a00}
.aviso.erro{background:var(--vinho-fundo);color:#5b1022}
.nota{color:var(--suave);font-size:12px;margin:10px 0 0!important}
.vazio{color:var(--suave);font-size:13px;margin:4px 0}
details{margin-top:12px;font-size:12.5px}
summary{cursor:pointer;color:var(--titulo);font-weight:600}
details ul{margin:8px 0 0;padding-left:18px;color:var(--suave)}
.passos{margin:0;padding-left:20px;font-size:13px}.passos li{margin:0 0 8px}
pre.cmd{background:#f5f8fc;border-radius:10px;padding:12px 14px;font-size:12px;overflow-x:auto;margin:0}
select,input{font:inherit;color:var(--tinta);padding:8px 10px;border:1px solid #cfd8e3;border-radius:8px;background:#fff;
width:100%;min-width:0}
form.sim{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;align-items:end;margin:14px 0}
form.sim label{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--suave)}
form.sim .botao{font-size:12px;padding:10px 18px}
#sim-saida{margin-top:8px}
.seletor{display:flex;align-items:center;gap:10px;margin:0 0 16px;flex-wrap:wrap}
.seletor select{width:auto}
.so-arquivo{display:none}.arquivo .so-arquivo{display:block}.arquivo .so-servidor{display:none!important}
footer{max-width:1280px;margin:0 auto;padding:0 24px 32px;color:var(--suave);font-size:11.5px}
@media (max-width:640px){.topo{padding:12px 16px}main{padding:16px 16px 32px}.grade{grid-template-columns:minmax(0,1fr)}
.card{padding:16px}.tiles{grid-template-columns:minmax(0,1fr)}.grande{font-size:25px}footer{padding:0 16px 28px}
.b-linha{grid-template-columns:56px minmax(0,1fr) 96px;gap:8px;font-size:11.5px}.rosca{width:128px;height:128px}
.kv.termos{grid-template-columns:1fr}}
@media print{.menu,.so-servidor,.topo .botao{display:none!important}.pagina{display:block!important}}
"""

JS = """
(function(){
var raiz=document.documentElement;
if(raiz.getAttribute('data-modo')!=='servidor'){raiz.classList.add('arquivo');}
function mostra(){
  var id=(location.hash||'#inicio').slice(1);
  if(!document.getElementById('p-'+id)){id='inicio';}
  var ps=document.querySelectorAll('.pagina');
  for(var i=0;i<ps.length;i++){ps[i].hidden=(ps[i].id!=='p-'+id);}
  var ls=document.querySelectorAll('.menu a');
  for(var j=0;j<ls.length;j++){ls[j].classList.toggle('ativo',ls[j].getAttribute('href')==='#'+id);}
}
window.addEventListener('hashchange',function(){mostra();window.scrollTo(0,0);});
mostra();
var sels=document.querySelectorAll('select[data-alvo]');
for(var k=0;k<sels.length;k++){(function(s){s.addEventListener('change',function(){
  var bs=document.querySelectorAll('.'+s.getAttribute('data-alvo'));
  for(var i=0;i<bs.length;i++){bs[i].hidden=(bs[i].getAttribute('data-comp')!==s.value);}
});})(sels[k]);}
var at=document.getElementById('atualizar');
if(at){at.addEventListener('click',function(ev){ev.preventDefault();at.textContent='Atualizando...';
  fetch('/atualizar',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})
  .then(function(){location.reload();}).catch(function(){at.textContent='Falhou: tente de novo';});});}
var f=document.getElementById('form-sim');
if(f){
  var tk=f.querySelector('[name=ticker]'),pr=f.querySelector('[name=preco]');
  var preco=function(){var o=tk.options[tk.selectedIndex];if(o&&o.getAttribute('data-preco')){pr.value=o.getAttribute('data-preco');}};
  tk.addEventListener('change',preco);preco();
  f.addEventListener('submit',function(ev){
    ev.preventDefault();
    if(raiz.classList.contains('arquivo')){return;}
    var saida=document.getElementById('sim-saida');
    saida.innerHTML='<p class="vazio">Calculando...</p>';
    var corpo={ticker:tk.value,cv:f.querySelector('[name=cv]').value,qtd:f.querySelector('[name=qtd]').value,preco:pr.value};
    fetch('/simular',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(corpo)})
    .then(function(r){return r.json();})
    .then(function(j){saida.innerHTML=j.html||'';})
    .catch(function(){saida.innerHTML='<p class="vazio">O servidor do painel não respondeu.</p>';});
  });
}
})();
"""


def html(d: dict, modo: str = 'arquivo') -> str:
    n_pend = len(d['pendencias'])
    menu = ''.join(f'<a href="#{k}">{e(t)}' + (f'<span class="conta">{n_pend}</span>' if k == 'pendencias' and n_pend
                                               else '') + '</a>' for k, t in MENU)
    avisos = ''.join(f'<p class="aviso">{e(a)}</p>' for a in d['avisos'])
    subs = {
        'inicio': 'Os cartões do painel da IRTrade, com os números do agente.',
        'carteira': 'Posição por mercado, valorizada pelo fechamento da B3.',
        'resultados': 'Apuração e operações finalizadas de cada mês.',
        'consolidado': 'Resultado líquido mês a mês nos últimos 12 meses.',
        'meuir': 'O que vai na declaração: fichas de renda variável e FII, bens e rendimentos.',
        'proventos': 'Dividendos, JCP, rendimentos e aluguel de ações recebidos.',
        'darf': 'O DARF a pagar, como pagar e a situação de todos os DARFs.',
        'cpf': 'Declaração IR, débitos (DARFs) e pendências do CPF.',
        'pendencias': 'Tudo o que precisa de atenção, do mais urgente para o informativo.',
        'conferencia': 'Os números do agente contra os da IRTrade, item a item.',
        'simulador': 'Quanto de imposto uma operação gera antes de você mandar a ordem.',
        'documentos': 'Notas de corretagem e de aluguel, PDFs e e-mails.',
        'guia': 'Como o agente trabalha, as regras e os termos.'}
    paginas = {'inicio': _pg_inicio, 'carteira': _pg_carteira, 'resultados': _pg_resultados,
               'consolidado': _pg_consolidado, 'meuir': _pg_meuir, 'proventos': _pg_proventos, 'darf': _pg_darf,
               'cpf': _pg_cpf, 'pendencias': _pg_pendencias, 'conferencia': _pg_conferencia,
               'simulador': _pg_simulador, 'documentos': _pg_documentos, 'guia': _pg_guia}
    corpo = ''.join(pagina(k, dict(MENU)[k], e(subs[k]), (avisos if k == 'inicio' else '') + paginas[k](d))
                    for k, _ in MENU)
    g = d['gerado']
    return (
        f'<!doctype html><html lang="pt-BR" data-modo="{e(modo)}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light">'
        f'<title>Contador de bolsa</title><style>{CSS}</style></head><body>'
        f'<header class="topo"><div class="marca">{ic("recibo")}<div>Contador de bolsa<small>imposto de renda das '
        f'operações em bolsa · {e(d["corretora"])}</small></div></div><div class="direita"><span>Olá, {e(d["nome"])} · '
        f'atualizado em {g:%d/%m/%Y às %Hh%M}</span><a class="botao so-servidor" href="#" id="atualizar">Atualizar</a>'
        f'</div></header><nav class="menu" aria-label="Páginas">{menu}</nav><main>{corpo}</main>'
        '<footer>Números do motor do contador de bolsa: notas de corretagem do Safra, Open Finance e preços da B3, com as '
        'regras lidas na IN RFB 1.585/2015 e na Lei 9.430/1996. Painel local: fica neste Mac. Não substitui o contador; '
        f'confira antes de pagar.</footer><script>{JS}</script></body></html>')


def _confere_sem_documento(pag: str, base: pathlib.Path, bruto: dict | None) -> None:
    tit = json.loads((pathlib.Path(base) / 'titular.json').read_text())
    doc = re.sub(r'\D', '', tit.get('documento') or (mes.documento_of(bruto) if bruto else ''))
    proibidos = []
    if len(doc) == 11:
        proibidos += [doc, f'{doc[:3]}.{doc[3:6]}.{doc[6:9]}-{doc[9:]}']
    tel = re.sub(r'\D', '', str(tit.get('telefone') or ''))
    if len(tel) >= 8:
        proibidos.append(tel)
    if any(p in pag for p in proibidos):
        raise RuntimeError('o painel saiu com o documento ou o telefone do titular: nada foi gravado')


def montar(base: pathlib.Path, bruto: dict | None = None, hoje: dt.date | None = None, modo: str = 'arquivo') -> str:
    pag = html(dados(base, bruto, hoje), modo)
    _confere_sem_documento(pag, base, bruto)
    return pag


def gera(base: pathlib.Path, bruto: dict | None = None, hoje: dt.date | None = None) -> pathlib.Path:
    """Grava saida/painel.html (os PDFs do mes ficam na mesma pasta, e os links da pagina sao relativos)."""
    base = pathlib.Path(base)
    pag = montar(base, bruto, hoje)
    (base / 'saida').mkdir(parents=True, exist_ok=True)
    arq = base / 'saida' / 'painel.html'
    tmp = arq.with_name('painel.html.tmp')
    tmp.write_text(pag, encoding='utf-8')
    tmp.replace(arq)
    return arq


# ------------------------------------------------------------------ simulador
def _numero(txt, inteiro: bool = False):
    s = str(txt if txt is not None else '').strip().replace('R$', '').replace(' ', '')
    if inteiro:
        s = s.replace('.', '')
    elif ',' in s:
        s = s.replace('.', '').replace(',', '.')
    return int(s) if inteiro else float(s)


def simular(base: pathlib.Path, bruto: dict | None, hoje: dt.date, pedido: dict) -> dict:
    """Refaz o mes em curso com uma operacao a mais, de hoje, sem gravar: quanto ela muda o resultado, o imposto, o
    DARF e a isencao de R$ 20 mil."""
    base = pathlib.Path(base)
    tk = str(pedido.get('ticker') or '').upper().strip()
    cv = str(pedido.get('cv') or '').upper().strip()
    if not TICKER_OK.fullmatch(tk) or cv not in ('C', 'V'):
        return {'erro': 'Escolha o ativo e se é compra ou venda.'}
    try:
        qtd, preco = _numero(pedido.get('qtd'), inteiro=True), _numero(pedido.get('preco'))
    except ValueError:
        return {'erro': 'Quantidade e preço precisam ser números (ex.: 1000 e 62,02).'}
    if not 0 < qtd <= 10_000_000 or not 0 < preco < 1_000_000:
        return {'erro': 'Quantidade ou preço fora do razoável.'}
    ests = mes.estados(base)
    if ests:
        atual = _seguinte(ests[-1]['ano'], ests[-1]['mes'])
    else:
        d0 = dt.date.fromisoformat(json.loads((base / 'partida.json').read_text())['data'])
        atual = _seguinte(d0.year, d0.month)
    if not dt.date(atual[0], atual[1], 1) <= hoje <= mes.fim_do_mes(*atual):
        return {'erro': f'O mês em apuração ({comp(*atual)}) não é o de hoje: o simulador volta quando ele for fechado.'}
    antes = mes.fecha_mes(base, atual[0], atual[1], bruto, hoje, gravar=False)
    pos = {p['ticker']: p for p in antes['estado']['posicoes']}
    p = pos.get(tk)
    if not p:
        return {'erro': f'{tk} não está na carteira: o simulador testa vender, recomprar ou aumentar o que você já tem.'}
    if cv == 'V' and p['qtd'] > 0 and qtd > p['qtd']:
        return {'erro': f"Você tem {qt(p['qtd'])} {tk}: vender mais que isso seria venda a descoberto."}
    if cv == 'C' and p['qtd'] < 0 and qtd > -p['qtd']:
        return {'erro': f"A posição vendida é de {qt(-p['qtd'])} {tk}: a recompra passa disso."}
    valor = round(qtd * preco, 2)
    mercado = 'VISTA' if p['classe'] != 'opcao' else ('OPCAO DE VENDA' if p.get('tipo_opcao') == 'put' else 'OPCAO DE COMPRA')
    nt = notas.Nota('simulacao', hoje, 'simulação')
    nt.liquido = valor if cv == 'V' else -valor
    nt.negocios.append(notas.Negocio(hoje, 'simulacao', 10 ** 6, cv, mercado, None, p['ativo'], qtd, preco, valor, tk,
                                     p['ativo'], p['classe'], p.get('strike'), p.get('tipo_opcao'), p.get('subjacente')))
    depois = mes.fecha_mes(base, atual[0], atual[1], bruto, hoje, gravar=False, extras=[nt])
    r0, r1 = antes['apuracao'], depois['apuracao']
    dres = {k: round(float(r1['resultados'][k]) - float(r0['resultados'][k]), 2) for k in r0['resultados']}
    p1 = next((x for x in depois['estado']['posicoes'] if x['ticker'] == tk), None)
    avisos = []
    if r0['isento_mes'] and not r1['isento_mes']:
        avisos.append('Com esta venda as vendas de ações do mês passam de R$ 20.000,00: o lucro das ações vendidas no mês '
                      'inteiro deixa de ser isento (IN RFB 1.585/2015, art. 59, I).')
    if dres.get('daytrade'):
        avisos.append('Parte da operação vira day trade (compra e venda do mesmo ativo hoje): 20% e prejuízo só com day '
                      'trade (IN RFB 1.585/2015, art. 65).')
    return {'ok': True, 'ticker': tk, 'cv': cv, 'qtd': qtd, 'preco': preco, 'valor': valor, 'resultado': dres,
            'resultado_total': round(sum(dres.values()), 2), 'imposto_antes': r0['devido'], 'imposto_depois': r1['devido'],
            'darf_antes': r0['darf'], 'darf_depois': r1['darf'], 'vencimento': r1['vencimento'].strftime('%d/%m/%Y'),
            'vendas_antes': r0['vendas_acoes'], 'vendas_depois': r1['vendas_acoes'], 'isento_antes': r0['isento_mes'],
            'isento_depois': r1['isento_mes'], 'competencia': comp(*atual),
            'prejuizos': {k: round(float(v), 2) for k, v in r1['saldo'].prejuizos.items()},
            'qtd_depois': p1['qtd'] if p1 else 0, 'pm_depois': abs(p1['custo'] / p1['qtd']) if p1 and p1['qtd'] else None,
            'avisos': avisos}


def html_simulacao(s: dict) -> str:
    if s.get('erro'):
        return f'<p class="aviso erro">{e(s["erro"])}</p>'
    nomes = {'comum': 'operação comum', 'daytrade': 'day trade', 'fii': 'FII', 'isento': 'isento'}
    partes = ', '.join(f'{nomes[k]} {rs(v)}' for k, v in s['resultado'].items() if v)
    pares = [('Operação', e(f"{'Venda' if s['cv'] == 'V' else 'Compra'} de {qt(s['qtd'])} {s['ticker']} a "
                            f"R$ {br(s['preco'])} = R$ {br(s['valor'])}")),
             ('Resultado desta operação', val(s['resultado_total'], 'R$ 0,00') +
              (f' <small class="rot">({e(partes)})</small>' if partes and len([v for v in s['resultado'].values() if v]) > 1
               else '')),
             ('Vendas de ações no mês', e(f"{rs(s['vendas_antes'], 'R$ 0,00')} → {rs(s['vendas_depois'], 'R$ 0,00')}")),
             ('Isenção de R$ 20 mil', chip('continua', 'ok') if s['isento_depois'] else
              chip('perde a isenção', 'erro') if s['isento_antes'] else chip('já não valia', 'cinza')),
             (f"Imposto de {s['competencia']} se fechasse hoje", e(f"{rs(s['imposto_antes'], 'R$ 0,00')} → "
                                                                  f"{rs(s['imposto_depois'], 'R$ 0,00')}")),
             ('DARF', e(f"{rs(s['darf_antes'], 'R$ 0,00')} → {rs(s['darf_depois'], 'R$ 0,00')}") +
              (f" <small class=\"rot\">vence {e(s['vencimento'])}</small>" if s['darf_depois'] else ''), True),
             ('Prejuízo a compensar depois', e(f"comum {rs(s['prejuizos'].get('comum'), 'R$ 0,00')} · day trade "
                                               f"{rs(s['prejuizos'].get('daytrade'), 'R$ 0,00')} · FII "
                                               f"{rs(s['prejuizos'].get('fii'), 'R$ 0,00')}"))]
    if s['cv'] == 'C' and s['pm_depois']:
        pares.append(('Preço médio depois', e(f"R$ {br(s['pm_depois'])} ({qt(s['qtd_depois'])} {s['ticker']})")))
    av = ''.join(f'<p class="aviso">{e(a)}</p>' for a in s['avisos'])
    return av + kv(pares)


# ------------------------------------------------------------------ servidor local
class Servidor:
    """A pagina pronta (refeita a cada CACHE_S ou no botao Atualizar) e o simulador, para o servidor HTTP local."""

    def __init__(self, base: pathlib.Path, of_arq: pathlib.Path, porta: int = PORTA, hoje: dt.date | None = None):
        self.base, self.of_arq, self.porta, self.hoje = pathlib.Path(base), pathlib.Path(of_arq), porta, hoje
        self.trava = threading.Lock()
        self._pagina, self._quando = None, 0.0

    def bruto(self) -> dict | None:
        return json.loads(self.of_arq.read_text()) if self.of_arq.exists() else None

    def dia(self) -> dt.date:
        return self.hoje or dt.date.today()

    def pagina(self, refazer: bool = False) -> str:
        with self.trava:
            if refazer or self._pagina is None or time.time() - self._quando > CACHE_S:
                self._pagina = montar(self.base, self.bruto(), self.dia(), modo='servidor')
                self._quando = time.time()
            return self._pagina

    def simula(self, pedido: dict) -> dict:
        with self.trava:
            s = simular(self.base, self.bruto(), self.dia(), pedido)
        return {**s, 'html': html_simulacao(s)}

    def hosts(self) -> set[str]:
        return {f'127.0.0.1:{self.porta}', f'localhost:{self.porta}'}

    def pdf(self, nome: str) -> bytes | None:
        if not PDF_OK.fullmatch(nome):
            return None
        arq = self.base / 'saida' / nome
        return arq.read_bytes() if arq.is_file() else None


def _handler(app: Servidor):
    class H(BaseHTTPRequestHandler):
        server_version = 'contador-bolsa'
        sys_version = ''

        def log_message(self, fmt, *args):      # nada de caminho ou valor no terminal
            pass

        def _manda(self, codigo: int, corpo: bytes, tipo: str) -> None:
            self.send_response(codigo)
            self.send_header('Content-Type', tipo)
            self.send_header('Content-Length', str(len(corpo)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Frame-Options', 'DENY')
            if tipo.startswith('text/html'):
                self.send_header('Content-Security-Policy', CSP)
            self.end_headers()
            self.wfile.write(corpo)

        def _texto(self, codigo: int, txt: str) -> None:
            self._manda(codigo, txt.encode(), 'text/plain; charset=utf-8')

        def do_GET(self):
            if self.headers.get('Host') not in app.hosts():
                return self._texto(403, 'host recusado')
            cam = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
            if cam in ('/', '/index.html', '/painel.html'):
                return self._manda(200, app.pagina().encode('utf-8'), 'text/html; charset=utf-8')
            corpo = app.pdf(cam.lstrip('/'))
            if corpo is not None:
                return self._manda(200, corpo, 'application/pdf')
            return self._texto(404, 'nao encontrado')

        def do_POST(self):
            origem = self.headers.get('Origin')
            if self.headers.get('Host') not in app.hosts() or \
                    (origem is not None and origem not in {f'http://{h}' for h in app.hosts()}):
                return self._texto(403, 'origem recusada')
            if not (self.headers.get('Content-Type') or '').startswith('application/json'):
                return self._texto(415, 'use JSON')
            try:
                n = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                n = -1
            if n < 0:           # tamanho negativo ou nao numerico: read(-1) esperaria o fim da conexao
                return self._texto(400, 'tamanho invalido')
            if n > 10_000:
                return self._texto(413, 'pedido grande demais')
            try:
                pedido = json.loads(self.rfile.read(n) or b'{}')
            except json.JSONDecodeError:
                return self._texto(400, 'JSON invalido')
            cam = urllib.parse.urlsplit(self.path).path
            if cam == '/simular' and isinstance(pedido, dict):
                corpo = json.dumps(app.simula(pedido), ensure_ascii=False, default=str).encode()
                return self._manda(200, corpo, 'application/json; charset=utf-8')
            if cam == '/atualizar':
                app.pagina(refazer=True)
                return self._manda(200, b'{"ok": true}', 'application/json; charset=utf-8')
            return self._texto(404, 'nao encontrado')
    return H


def servir(base: pathlib.Path, of_arq: pathlib.Path, porta: int = PORTA, hoje: dt.date | None = None,
           abrir: bool = False) -> None:
    app = Servidor(base, of_arq, porta, hoje)
    app.pagina()                                # falha aqui (dado ruim) antes de abrir a porta
    srv = ThreadingHTTPServer(('127.0.0.1', porta), _handler(app))
    print(f'painel do contador de bolsa em http://127.0.0.1:{porta} (Ctrl+C para parar)', flush=True)
    if abrir:
        webbrowser.open(f'http://127.0.0.1:{porta}')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
