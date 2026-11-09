"""Fechamento do mes: junta notas, Open Finance, precos da B3 e o historico no formato do relatorio
mensal (dados de relatorio.html_relatorio) e do DARF (campos de darf.html_darf).

Pasta do titular, fora do git (~/.autopilot/contador-bolsa/<titular>/):
  titular.json        nome, documento, corretora, email e custos ('lei' ou 'irtrade')
  partida.json        posicao, prejuizos e IRRF no ultimo dia do mes anterior ao primeiro apurado aqui
  historico.json      tabela anual, proventos de 12 meses e DARFs dos meses que vieram da IRTrade
  tickers.json        nome do papel na nota -> ticker, para papel fora da tabela de ativos.py
  manuais.json        negocio sem nota no e-mail, lancado a mao com a fonte (liquidacao do Open Finance)
  eventos_b3.json     eventos societarios da B3 nos papeis da carteira (eventos.py); eventos.json, os do titular
  notas/  aluguel/    notas de corretagem e de emprestimo de acoes em PDF
  estado/AAAA-MM.json fechamento de cada mes, ponto de partida do mes seguinte (o do mes em curso e .parcial)
  saida/              relatorio e DARF em PDF
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import pathlib
import re
import unicodedata
from collections import defaultdict

from alocacao.dias import feriados

from . import aluguel, apuracao, ativos, eventos, notas, precos
from .apuracao import Carteira, Saldo

MESES = ('Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez')
MESES_EXTENSO = ('JANEIRO', 'FEVEREIRO', 'MARÇO', 'ABRIL', 'MAIO', 'JUNHO', 'JULHO', 'AGOSTO', 'SETEMBRO', 'OUTUBRO',
                 'NOVEMBRO', 'DEZEMBRO')
LINHAS_ANUAIS = ('OP. COMUM', 'DAYTRADE', 'FII', 'PROVENTOS', 'BTC DOADOR', 'VENDAS ISENTAS', 'BONIFICAÇÕES',
                 'SOMA', 'IMPOSTOS', 'DESPESAS', 'LÍQUIDO')
LINHA_DO_TIPO = {'comum': 'OP. COMUM', 'daytrade': 'DAYTRADE', 'fii': 'FII'}
NOME_DO_TIPO = {'comum': 'operações comuns', 'daytrade': 'day trade', 'fii': 'FII'}
# descricao do lancamento no Open Finance (sem acento) -> linha do extrato do relatorio
OF_REGRAS = [
    (r'^JUROS S(OBRE|/)? ?CAP', 'JUROS S/ CAPITAL'), (r'^DIVIDENDO', 'DIVIDENDOS'), (r'^RENDIMENTOS$', 'RENDIMENTOS'),
    (r'^CREDITO EMPRESTIMO BOVESPA', 'REEMBOLSO BTC DOADOR'), (r'^TAXA REEMBOLSO BTB DOADOR', 'RENDIMENTOS BTC DOADOR'),
    (r'^CORRETAGEM BTB', 'DESPESAS OPERACIONAIS - BTC'), (r'^REMUNERA\S* BTB', 'REMUNERAÇÃO BTC TOMADOR'),
]
LIQUIDACOES = re.compile(r'^LIQUIDACAO (NOTA RENDA VARIAVEL|DE OPCAO BOVESPA)')
PAGAMENTO_DARF = re.compile(r'DARF|RECEITA FED|TRIBUTO')
VENCE_30_12 = ('O DARF de novembro vence em 30/12, não em 31/12: na Agenda Tributária da Receita (dezembro de 2024 e '
               'de 2025, ADE Corat 28/2025) o código 6015 de novembro vence em 30/12, e 31/12 só tem declarações.')


def br(x: float, casas: int = 2) -> str:
    return f'{x:,.{casas}f}'.replace(',', '#').replace('.', ',').replace('#', '.')


def _limpo(s: str) -> str:
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', s.upper()).strip()


def livre(arq: pathlib.Path) -> pathlib.Path:
    """O proprio caminho, ou com " (2)", " (3)"... se ja existir: versao guardada nunca sobrescreve outra."""
    n, alvo = 2, pathlib.Path(arq)
    while alvo.exists():
        alvo = pathlib.Path(arq).with_name(f'{pathlib.Path(arq).stem} ({n}){pathlib.Path(arq).suffix}')
        n += 1
    return alvo


def fim_do_mes(ano: int, mes: int) -> dt.date:
    return dt.date(ano + mes // 12, mes % 12 + 1, 1) - dt.timedelta(1)


def ultimo_pregao(ate: dt.date) -> dt.date:
    d = ate
    while d.weekday() >= 5 or d in feriados(d.year):
        d -= dt.timedelta(1)
    return d


def transacoes_of(bruto: dict) -> list[dict]:
    def lista(o):
        if isinstance(o, list):
            for x in o:
                if isinstance(x, dict) and 'amount' in x:
                    yield x
                else:
                    yield from lista(x)
        elif isinstance(o, dict):
            for v in o.values():
                yield from lista(v)
    out = []
    for c in bruto.get('conexoes', []):
        for t in lista(c.get('transacoes')):
            out.append({'data': dt.date.fromisoformat(str(t.get('date'))[:10]), 'valor': round(float(t.get('amount') or 0), 2),
                        'descricao': _limpo(t.get('description'))})
    return out


def documento_of(bruto: dict) -> str:
    for c in (bruto or {}).get('conexoes', []):
        doc = re.sub(r'\D', '', str((c.get('identidade') or {}).get('document') or ''))
        if doc:
            return doc
    return ''


RENOVAR_DIAS = 30       # autorizacao do Open Finance a menos disso de vencer vira aviso
OF_OK = ('UPDATED', 'UPDATING')


def _local(txt) -> dt.datetime | None:
    try:
        t = dt.datetime.fromisoformat(str(txt).replace('Z', '+00:00'))
    except ValueError:
        return None
    return t.astimezone().replace(tzinfo=None) if t.tzinfo else t


def saude_of(bruto: dict | None, hoje: dt.date) -> list[str]:
    """O que impede o Open Finance de trazer dado novo: leitura parada desde antes do ultimo dia util, conexao com
    erro, banco sem dado novo, erro na ultima leitura e autorizacao perto de vencer (a renovacao e do titular). O texto
    so muda quando o problema muda, e o diario avisa uma vez so."""
    if not bruto:
        return []
    out, limite = [], ultimo_pregao(hoje - dt.timedelta(1))
    lido = _local(bruto.get('lido_em'))
    if lido and lido.date() < limite:
        out.append(f'Open Finance sem leitura nova desde {lido:%d/%m às %Hh%M}: quem lê é o terminal (agente '
                   'br.autopilot.terminal); sem ele não entram proventos, aluguel nem o pagamento do DARF.')
    for x in bruto.get('erros') or []:
        txt = re.sub(r'\d{3}\.?\d{3}\.?\d{3}-?\d{2}', '<CPF>', str(x))[:160]
        out.append(f'Open Finance: a última leitura deu erro ({txt}).')
    for c in bruto.get('conexoes', []):
        it = c.get('item') or {}
        nome = (it.get('connector') or {}).get('name') or 'conexão'
        st = it.get('status')
        if st and st not in OF_OK:
            out.append(f"Open Finance ({nome}): a conexão está em {st} ({it.get('executionStatus') or '-'}). Se "
                       'continuar no dia seguinte, reconecte no MeuPluggy, autorizando de novo no app do Safra.')
        banco = _local(it.get('lastUpdatedAt'))
        if banco and banco.date() < limite:
            out.append(f'Open Finance ({nome}): o banco não manda dado novo desde {banco:%d/%m às %Hh%M}.')
        vence = _local(it.get('consentExpiresAt'))
        if vence:
            dias = (vence.date() - hoje).days
            if dias < 0:
                out.append(f'A autorização do Open Finance ({nome}) venceu em {vence:%d/%m/%Y}: sem ela não entra '
                           'nada do banco. Renove no MeuPluggy, autorizando de novo no app do Safra.')
            elif dias <= RENOVAR_DIAS:
                out.append(f'A autorização do Open Finance ({nome}) vence em {vence:%d/%m/%Y}: renove antes no '
                           'MeuPluggy, autorizando de novo no app do Safra.')
    return out


def lancamentos_bolsa(of: list[dict], ini: dt.date, fim: dt.date, ja_contados: list[dict]) -> list[dict]:
    """Lancamentos de proventos e aluguel do periodo com a linha do extrato; tira os que o relatorio anterior
    ja contou (a IRTrade data o reembolso pelo evento e o banco credita no dia util seguinte)."""
    tirar = [(dt.date.fromisoformat(j['data']), round(j['valor'], 2), _limpo(j['descricao'])) for j in ja_contados]
    out = []
    for t in of:
        if not ini <= t['data'] <= fim:
            continue
        rot = next((r for rx, r in OF_REGRAS if re.match(rx, t['descricao'])), None)
        if not rot:
            continue
        k = (t['data'], t['valor'], t['descricao'])
        if k in tirar:
            tirar.remove(k)
            continue
        out.append({**t, 'linha': rot})
    return out


# ---- custodia e conta corrente ---------------------------------------------------------------------
SUBSCRICAO = re.compile(r'^[A-Z]{4}(1|2|9|10|12|13|14|15)$')       # direito e recibo de subscricao
CORTES = (('pregão', 0, True), ('pregão', 0, False), ('liquidação', 1, True), ('liquidação', 1, False))


def custodia_of(bruto: dict | None) -> dict | None:
    """Posicao em bolsa no banco pelo Open Finance (acoes, FII, BDR e ETF; opcao fica de fora): papel -> quantidade
    e ISIN, com o dia da posicao."""
    itens, dias = {}, []
    for c in (bruto or {}).get('conexoes', []):
        for x in c.get('investimentos') or []:
            cod = str(x.get('code') or '').upper().strip()
            if x.get('type') != 'EQUITY' or not cod or ativos.SERIE.match(cod):
                continue
            d = _local(x.get('date'))
            if d:
                dias.append(d.date())
            q = float(x.get('quantity') or 0)
            if q > 0:
                it = itens.setdefault(cod, {'qtd': 0, 'isin': x.get('isin'), 'subtipo': x.get('subtype')})
                it['qtd'] += int(round(q))
    return {'data': max(dias), 'itens': itens} if dias else None


def isin_of(bruto: dict | None) -> dict:
    """ISIN -> codigo de negociacao dos papeis que o banco ja mostrou (para ler os eventos da B3, que vem por ISIN)."""
    return {x['isin']: str(x['code']).upper() for c in (bruto or {}).get('conexoes', []) for x in c.get('investimentos') or []
            if x.get('type') == 'EQUITY' and x.get('isin') and x.get('code')}


def saldo_conta_of(bruto: dict | None) -> dict | None:
    """Saldo da conta corrente no Open Finance e a hora em que o banco o informou."""
    for c in (bruto or {}).get('conexoes', []):
        for a in c.get('contas') or []:
            if a.get('type') == 'BANK' and a.get('subtype') == 'CHECKING_ACCOUNT' and a.get('balance') is not None:
                return {'saldo': round(float(a['balance']), 2), 'em': _local(a.get('updatedAt'))}
    return None


def confere_custodia(cust: dict | None, cart: Carteira, todas: list, corte: dt.date, evs: list = ()) -> dict | None:
    """Posicao do banco no dia da custodia x a do motor no mesmo dia. O motor anda nota a nota ate `corte`; para voltar
    ao dia da custodia ele desfaz os negocios depois dele. O banco pode contar o negocio pelo pregao ou pela liquidacao,
    e a posicao do dia pode ser a da abertura ou a do fechamento: vale qualquer um dos quatro cortes. Divergencia vira
    alerta com as pistas (nota que nao chegou, exercicio sem nota, evento da B3, subscricao, aluguel)."""
    if not cust:
        return None
    dia = cust['data']
    movs = defaultdict(list)
    for nt in todas:
        if nt.pregao > corte:
            continue
        for n in nt.negocios:
            tk = n.subjacente if n.exercicio else n.ticker
            if tk and (n.exercicio or n.classe in eventos.CLASSES):
                movs[tk].append((nt.pregao, nt.liquidacao or nt.pregao, n.qtd if n.cv == 'C' else -n.qtd))
    final = {p.ticker: p.qtd for p in cart.pos.values() if p.classe in eventos.CLASSES}
    aplicados = defaultdict(list)
    for a in cart.eventos_aplicados:
        aplicados[a['alvo']].append(a)
    tks = ({t for t, q in final.items() if q > 0} | set(cust['itens']) |
           {t for t, ms in movs.items() if any(m[0] >= dia or m[1] >= dia for m in ms)})
    ok, divs = [], []
    for tk in sorted(tks):
        cortes = {final.get(tk, 0) - sum(m[2] for m in movs.get(tk, ()) if (m[i] > dia if incl else m[i] >= dia))
                  for _, i, incl in CORTES}
        for a in aplicados.get(tk, ()):      # evento perto do dia: o banco pode mostrar antes dele
            if dt.date.fromisoformat(a['data_com']) >= dia - dt.timedelta(7):
                cortes |= {v - a['novas'] for v in cortes}
        b = cust['itens'].get(tk, {}).get('qtd', 0)
        if b in cortes:
            if b > 0:
                ok.append(tk)
            continue
        motor = min(cortes, key=lambda v: (abs(v - b), -v))
        dif, pistas = b - motor, []
        if SUBSCRICAO.match(tk):
            sub = [e for e in evs if e.get('tipo') == 'subscricao' and e['ticker'][:4] == tk[:4]]
            pistas.append('direito ou recibo de subscrição' + (f' ({eventos.texto(sub[-1])})' if sub else '') +
                          ': o motor só conta a compra quando a nota chegar')
        else:
            for p in cart.pos.values():
                venc = [e for e in cart.encerramentos if e.ticker == p.ticker and e.mercado == 'vencimento'
                        and e.qtd == abs(dif)]
                if p.classe == 'opcao' and p.subjacente == tk and venc and \
                        (dif > 0) == (p.tipo_opcao == 'put') and venc[-1].est_cv == 'V':
                    pistas.append(f'exercício de {p.ticker} em {venc[-1].liq_data:%d/%m} sem a nota (o motor tratou a '
                                  'opção como vencida sem exercício)')
            perto = [e for e in evs if e['ticker'] == tk and e.get('tipo') != 'subscricao'
                     and abs((dt.date.fromisoformat(e['data_com']) - dia).days) <= 30]
            if perto:
                pistas.append(f'evento da B3 ({eventos.texto(perto[-1])})')
            pistas.append('compra sem nota no e-mail, transferência de outra corretora ou bonificação' if dif > 0 else
                          'venda sem nota no e-mail, transferência para outra corretora ou ações emprestadas (se o banco '
                          'as tira da posição até a devolução)')
        divs.append({'ticker': tk, 'banco': b, 'motor': motor, 'pistas': pistas})
    classe = {p.ticker: p.classe for p in cart.pos.values()}
    n_fii = sum(1 for t in ok if classe.get(t) == 'fii' or cust['itens'].get(t, {}).get('subtipo') == 'REAL_ESTATE_FUND')
    return {'data': dia, 'ok': ok, 'acoes': len(ok) - n_fii, 'fii': n_fii, 'divergencias': divs}


# ---- conciliacao -----------------------------------------------------------------------------------
def concilia(todas: list, of: list[dict], desde: dt.date, ate: dt.date) -> dict:
    """Cada liquidacao de bolsa no Open Finance tem de ter uma nota com o mesmo valor e a mesma data de
    liquidacao. Liquidacao sem nota = nota que nao chegou por e-mail (o imposto sai errado sem ela). Nota que liquida
    depois de `ate` fica para a conciliacao do mes da liquidacao: o extrato daqui nao a alcanca (nota de 29/10/2026
    que liquidou em 03/11 aparecia como faltando no Open Finance no fechamento de outubro)."""
    livres = {}
    for n in todas:
        if n.liquidacao:
            livres.setdefault((n.liquidacao, round(n.liquido, 2)), []).append(n)
    casadas, sem_nota = [], []
    for t in sorted(of, key=lambda t: t['data']):
        if desde <= t['data'] <= ate and LIQUIDACOES.match(t['descricao']):
            ns = livres.get((t['data'], t['valor']))
            if ns:
                casadas.append((t, ns.pop(0)))
            else:
                sem_nota.append(t)
    # o banco as vezes debita o IR da venda de opcao em separado ("IR BOVESPA"): casa no mesmo dia por ate R$ 1
    for t in list(sem_nota):
        perto = [(k, ns) for k, ns in livres.items() if ns and k[0] == t['data'] and abs(k[1] - t['valor']) <= 1.0]
        if perto:
            k, ns = min(perto, key=lambda x: abs(x[0][1] - t['valor']))
            casadas.append((t, ns.pop(0)))
            sem_nota.remove(t)
    ultimo_of = max((t['data'] for t in of), default=None)
    pendentes = [n for ns in livres.values() for n in ns if desde <= n.liquidacao <= ate and n.numero != 'manual']
    return {'casadas': casadas, 'sem_nota': sem_nota, 'ultimo_of': ultimo_of,
            'sem_lancamento': sorted(pendentes, key=lambda n: n.liquidacao)}


def pagamento_darf(of: list[dict], periodo_fim: dt.date, valor: float) -> dict | None:
    """Debito de DARF na conta depois do fim do periodo, do valor do DARF ate 25% acima (multa e juros)."""
    for t in sorted(of, key=lambda t: t['data']):
        if (t['data'] > periodo_fim and PAGAMENTO_DARF.search(t['descricao'])
                and valor - 0.01 <= -t['valor'] <= valor * 1.25 + 0.01):
            return t
    return None


def estados(base: pathlib.Path) -> list[dict]:
    """Fechamentos definitivos ja gravados (o parcial do mes em andamento fica de fora)."""
    pasta = pathlib.Path(base) / 'estado'
    if not pasta.exists():
        return []
    return [json.loads(a.read_text()) for a in sorted(pasta.glob('*.json')) if re.fullmatch(r'\d{4}-\d{2}\.json', a.name)]


def ajustes_irtrade(hist: dict) -> list[dict]:
    """Decisoes do titular que mudam um resultado que a IRTrade apurou (historico.json, 'ajustes': mes AAAA-MM, tipo
    comum/daytrade/fii, classe vista/opcao, antes, depois, motivo). O numero dela fica como ela publicou; quem le o mes
    dela (tabela anual, painel) soma `delta` no resultado do tipo."""
    out = []
    for x in hist.get('ajustes') or []:
        a, m = (int(v) for v in x['mes'].split('-'))
        out.append({'ano': a, 'mes': m, 'tipo': x['tipo'], 'classe': x.get('classe') or 'vista',
                    'delta': round(x['depois'] - x['antes'], 2), 'motivo': x.get('motivo') or ''})
    return out


CONFERE_EXTRATO = (('PROVENTOS', 'proventos', 'proventos'), ('BTC DOADOR', 'btc', 'aluguel de ações (BTC doador)'),
                   ('DESPESAS', 'despesas', 'despesas de aluguel'))


def retrato_irtrade(base: pathlib.Path) -> dict:
    """O retrato mais novo do painel da IRTrade (irtrade/AAAA-MM-DD.json), ou {}."""
    pasta = pathlib.Path(base) / 'irtrade'
    arqs = sorted(pasta.glob('*.json')) if pasta.is_dir() else []
    return json.loads(arqs[-1].read_text()) if arqs else {}


def meses_irtrade(snap: dict) -> dict[str, dict]:
    """Proventos, aluguel e despesas de cada mes no retrato: o consolidado de 12 meses ate o ultimo mes que ela
    consolidou e, por cima, a leitura mes a mes da API dela (`meses_api`, sem os meses que ela marcou como parciais)."""
    out = {}
    cs = snap.get('consolidado_12m') or {}
    ci = {k: i for i, k in enumerate(cs.get('colunas', []))}
    if 'mes' in ci:
        for row in cs.get('linhas', []):
            if row[ci['mes']] <= (snap.get('ultimo_consolidado') or ''):
                out[row[ci['mes']]] = {k: float(row[ci[k]] or 0.0) for _, k, _ in CONFERE_EXTRATO if k in ci}
    api = snap.get('meses_api') or {}
    ai = {k: i for i, k in enumerate(api.get('colunas', []))}
    if 'mes' in ai:
        for row in api.get('linhas', []):
            if row[ai['mes']] not in (api.get('parcial') or []):
                out[row[ai['mes']]] = {k: float(row[ai[k]] or 0.0) for _, k, _ in CONFERE_EXTRATO if k in ai}
    return out


def confere_irtrade(base: pathlib.Path, tolerancia: float = 0.05) -> list[str]:
    """Mes fechado pelo agente x o mesmo mes no retrato da IRTrade: proventos, aluguel de acoes e despesas saem dos
    mesmos creditos do banco nos dois, entao diferenca e erro de um lado (resultado das operacoes e DARF tem diferenca
    de metodo, explicada na pagina Conferencia, e ficam fora daqui). Pegou, em 07/11/2026, um reembolso de aluguel
    marcado por engano como ja contado no mes anterior (partida.json, of_ja_contado)."""
    base = pathlib.Path(base)
    deles = meses_irtrade(retrato_irtrade(base))
    out = []
    for e in estados(base):
        ir = deles.get(f"{e['ano']}-{e['mes']:02d}")
        for linha, chave, nome in CONFERE_EXTRATO:
            if not ir or chave not in ir:
                continue
            ag = float(e['anual'].get(linha, 0.0) or 0.0)
            if abs(ag - ir[chave]) > tolerancia:
                out.append(f"{e['mes']:02d}/{e['ano']}: {nome} do agente R$ {br(ag)}, IRTrade R$ {br(ir[chave])} "
                           f"(diferença de R$ {br(ag - ir[chave])}). Os dois saem dos mesmos créditos do banco: confira "
                           "o Open Finance do mês e as marcas de lançamento já contado da partida.json.")
    return out


def manuais(base: pathlib.Path) -> list:
    """manuais.json: [{"pregao", "liquidacao", "cv", "ticker", "ativo", "classe", "qtd", "total", "fonte"}];
    total ja com custos (a liquidacao do banco)."""
    arq = pathlib.Path(base) / 'manuais.json'
    out = []
    for i, m in enumerate(json.loads(arq.read_text()) if arq.exists() else []):
        d = dt.date.fromisoformat(m['pregao'])
        nt = notas.Nota('manual', d, m.get('fonte', 'manual'))
        nt.liquidacao = dt.date.fromisoformat(m['liquidacao']) if m.get('liquidacao') else None
        nt.liquido = -m['total'] if m['cv'] == 'C' else m['total']
        nt.negocios.append(notas.Negocio(d, 'manual', i, m['cv'], 'VISTA', None, m['ativo'], m['qtd'], m['total'] / m['qtd'],
                                         m['total'], m['ticker'], m['ativo'], m.get('classe', 'acao')))
        out.append(nt)
    return out


# ---- fechamento ------------------------------------------------------------------------------------
def partida(base: pathlib.Path, ano: int, mes: int) -> tuple[list, Saldo, str, dict]:
    ant = dt.date(ano, mes, 1) - dt.timedelta(1)
    est = pathlib.Path(base) / 'estado' / f'{ant:%Y-%m}.json'
    if est.exists():
        e = json.loads(est.read_text())
        return ([apuracao.posicao_de_dict(p) for p in e['posicoes']], Saldo(**e['saldo']),
                f'fechamento de {ant:%m/%Y} do agente', {})
    p = json.loads((pathlib.Path(base) / 'partida.json').read_text())
    if p['data'] != ant.isoformat():
        raise SystemExit(f"partida.json e de {p['data']}; para apurar {mes:02d}/{ano} falta o fechamento de {ant:%m/%Y}")
    return ([apuracao.posicao_de_dict(x) for x in p['posicoes']],
            Saldo(dict(p['prejuizos']), p.get('irrf', 0.0), p.get('pendente', 0.0)), p.get('origem', 'partida.json'), p)


def _contexto(base: pathlib.Path, ano: int, mes: int, extras: list | None = None) -> dict:
    """O que o fechamento le uma vez so (partida, notas ja rateadas e eventos); `_roda` apura sobre ele quantas vezes
    precisar (o fechamento e os cenarios do vencimento). Evento com data com entre a partida e o comeco do mes que
    nenhum fechamento viu (a B3 publicou depois) e aplicado no primeiro dia do mes."""
    base = pathlib.Path(base)
    tit = json.loads((base / 'titular.json').read_text())
    ini = dt.date(ano, mes, 1)
    posicoes, saldo, origem, part = partida(base, ano, mes)
    extra = ativos.carrega_extra(base / 'tickers.json')
    todas = notas.ler_pasta(base / 'notas', extra) + manuais(base) + list(extras or [])
    excluir = notas.IRTRADE_EXCLUI if tit.get('custos') == 'irtrade' else ()
    for n in todas:
        n.rateia(excluir)
    apuracao.infere_datas(posicoes, todas, ini)
    evs = eventos.carrega(base)
    pj = base / 'partida.json'
    piso = json.loads(pj.read_text())['data'] if pj.exists() else ini.isoformat()
    vistos = {i for e in estados(base) if (e['ano'], e['mes']) < (ano, mes) for i in e.get('eventos') or []}
    atrasados = [e for e in evs if e.get('tipo') in eventos.APLICA and piso < e['data_com'] < ini.isoformat()
                 and eventos.ident(e) not in vistos]
    return {'base': base, 'tit': tit, 'ano': ano, 'mes': mes, 'ini': ini, 'posicoes': posicoes, 'saldo': saldo,
            'origem': origem, 'part': part, 'todas': todas, 'excluir': excluir, 'eventos': evs, 'atrasados': atrasados}


def _roda(ctx: dict, ate: dt.date, extras: list = ()) -> tuple[Carteira, list, dict]:
    """Carteira do mes ate `ate` (as notas do contexto mais `extras`) e a apuracao; a partida nao muda."""
    cart = Carteira(copy.deepcopy(ctx['posicoes']))
    for ev in ctx['atrasados']:
        cart.eventos_vistos.append(eventos.ident(ev))
        cart.evento(ev, ctx['ini'])
    do_mes = [n for n in ctx['todas'] + list(extras) if ctx['ini'] <= n.pregao <= ate]
    cart.processa(do_mes, ate=ate, desde=ctx['ini'], eventos_=ctx['eventos'])
    return cart, do_mes, apuracao.apura_mes(cart, ctx['ano'], ctx['mes'], ctx['saldo'])


def _confere_series(pos: list, pregao: dt.date, base: pathlib.Path, conferencia: list) -> None:
    """Strike, vencimento, tipo e ativo-objeto de cada opcao da carteira pelo cadastro de instrumentos da B3 do pregao:
    completa o que a posicao nao trouxe (a de partida, tirada da IRTrade, vem sem strike) e segue o strike que a B3
    ajustou por provento do ativo-objeto, porque o exercicio sai pelo strike do dia."""
    opc = [p for p in pos if p.classe == 'opcao']
    cad = precos.series(pregao, [p.ticker for p in opc], base / 'cache' / 'precos') if opc else {}
    for p in opc:
        s = cad.get(p.ticker)
        if not s:
            continue
        d, novos = f"{s['dia'][8:10]}/{s['dia'][5:7]}", []
        if p.strike is None and s['strike']:
            p.strike = s['strike']
            novos.append(f"strike R$ {br(s['strike'])}")
        elif p.strike and s['strike'] and abs(p.strike - s['strike']) >= 0.005:
            conferencia.append(f"Strike de {p.ticker} ajustado pela B3 de R$ {br(p.strike)} para R$ {br(s['strike'])} "
                               f"(cadastro de instrumentos de {d}): a B3 ajusta o strike quando o ativo-objeto paga "
                               'provento, e o exercício sai pelo strike novo.')
            p.strike = s['strike']
        if not p.vencimento and s['vencimento']:
            p.vencimento = dt.date.fromisoformat(s['vencimento'])
            novos.append(f'vencimento {p.vencimento:%d/%m/%Y}')
        if not p.tipo_opcao and s['tipo'] in ('put', 'call'):
            p.tipo_opcao = s['tipo']
            novos.append(s['tipo'])
        if not p.subjacente and s['subjacente']:
            p.subjacente = s['subjacente']
            novos.append(f"ativo-objeto {s['subjacente']}")
        if novos:
            conferencia.append(f"{p.ticker}: {', '.join(novos)} pelo cadastro de instrumentos da B3 de {d} (a posição veio "
                               f"sem {'esse dado' if len(novos) == 1 else 'esses dados'}).")


def cenarios_vencimento(ctx: dict, cart: Carteira, corte: dt.date, pregao: dt.date, bruto: dict | None = None) -> dict | None:
    """As opcoes lancadas que ainda vencem neste mes, pelos dois caminhos da lei (IN 1.585, art. 60): viram po (o premio
    vira ganho no vencimento) ou sao exercidas (o premio entra no custo da compra ou no preco da venda do ativo-objeto).
    Cada caminho e o mes refeito ate o vencimento com o exercicio no strike, sem outras operacoes e sem as taxas do
    exercicio; o "provavel" e o caminho das que estao do lado do exercicio no ultimo fechamento."""
    fim = fim_do_mes(ctx['ano'], ctx['mes'])
    abertas = sorted((p for p in cart.posicoes() if p.classe == 'opcao' and p.qtd < 0 and p.vencimento and p.strike
                      and p.subjacente and corte < p.vencimento <= fim), key=lambda p: (p.vencimento, p.ticker))
    if not abertas:
        return None
    ate = max(p.vencimento for p in abertas)
    cot = precos.fechamento(pregao, sorted({p.subjacente for p in abertas}), ctx['base'] / 'cache' / 'precos')
    ops = []
    for p in abertas:
        q, k, put, s = abs(p.qtd), p.strike, p.tipo_opcao == 'put', cot.get(p.subjacente)
        premio = round(-p.custo, 2)
        ops.append({'ticker': p.ticker, 'tipo': p.tipo_opcao, 'subjacente': p.subjacente, 'strike': k, 'qtd': q,
                    'vencimento': p.vencimento, 'premio': premio, 'preco': s['preco'] if s else None,
                    'dia_preco': dt.date.fromisoformat(s['dia']) if s else None,
                    'dentro': bool(s) and (s['preco'] < k if put else s['preco'] > k),
                    'caixa': round(-q * k if put else q * k, 2),
                    'unitario': round((q * k - premio) / q if put else (q * k + premio) / q, 4)})

    def caminho(exercidas: set) -> dict:
        extras = []
        for i, o in enumerate(o for o in ops if o['ticker'] in exercidas):
            put = o['tipo'] == 'put'
            nt = notas.Nota('cenario', o['vencimento'], 'cenário')
            nt.negocios.append(notas.Negocio(
                o['vencimento'], 'cenario', i, 'C' if put else 'V', 'EXERC OPC VENDA' if put else 'EXERC OPC COMPRA',
                None, o['ticker'], o['qtd'], o['strike'], round(o['qtd'] * o['strike'], 2), o['ticker'], o['ticker'],
                'opcao', o['strike'], o['tipo'], o['subjacente'], True))
            extras.append(nt)
        c, _, r = _roda(ctx, ate, extras)
        subs = sorted({o['subjacente'] for o in ops if o['ticker'] in exercidas})
        return {'exercidas': sorted(exercidas), 'darf': r['darf'], 'devido': r['devido'],
                'imposto': r['imposto_bruto'], 'caixa': round(sum(o['caixa'] for o in ops if o['ticker'] in exercidas), 2),
                'posicoes': {t: {'qtd': c.pos[t].qtd, 'pm': c.pos[t].pm} for t in subs if t in c.pos}}

    todas_ = {o['ticker'] for o in ops}
    provavel = {o['ticker'] for o in ops if o['dentro']}
    sem_preco = [o['ticker'] for o in ops if o['preco'] is None]
    cens = [caminho(set()), caminho(todas_)]
    if provavel not in (set(), todas_):
        cens.append(caminho(provavel))
    for c in cens:
        c['provavel'] = not sem_preco and c['exercidas'] == sorted(provavel)
    return {'ate': ate, 'opcoes': ops, 'cenarios': cens, 'conta': saldo_conta_of(bruto), 'sem_preco': sem_preco,
            'nota': 'Sem outras operações até o vencimento e sem as taxas do exercício, que vêm na nota.'}


def _texto_vencimento(v: dict) -> str:
    """Uma linha para os alertas: os dois caminhos, o dinheiro e a conta corrente."""
    ops, cens = v['opcoes'], {tuple(c['exercidas']): c for c in v['cenarios']}
    po, ex = cens[()], cens[tuple(sorted(o['ticker'] for o in ops))]
    nomes = ' e '.join(o['ticker'] for o in ops)
    tipos = {o['tipo'] for o in ops}
    rot = 'puts lançadas' if tipos == {'put'} else 'calls lançadas' if tipos == {'call'} else 'opções lançadas'
    um = len(ops) == 1
    dias = sorted({o['vencimento'] for o in ops})
    premio = sum(o['premio'] for o in ops)
    obj = ' e '.join(f"{br(o['qtd'], 0)} {o['subjacente']}" for o in ops)
    compra = [o for o in ops if o['tipo'] == 'put']
    txt = (f"Vencimento de {' e '.join(f'{d:%d/%m}' for d in dias)} ({nomes}, {rot if not um else rot[:-1]}): "
           f"se {'virar' if um else 'virarem'} pó, o prêmio de R$ {br(premio)} vira ganho e o DARF parcial do mês fica "
           f"em R$ {br(po['darf'])}; se {'for exercida' if um else 'forem exercidas'}, o DARF fica em R$ {br(ex['darf'])} e ")
    if compra and len(compra) == len(ops):
        txt += f"a compra de {obj} pede R$ {br(-ex['caixa'])} na liquidação"
    elif not compra:
        txt += f"a venda de {obj} rende R$ {br(ex['caixa'])} na liquidação"
    else:
        txt += f"o exercício movimenta R$ {br(ex['caixa'])} na liquidação (negativo = sai da conta)"
    txt += ' (custo por ação: ' + ' e '.join(f"{o['subjacente']} R$ {br(o['unitario'])}" for o in compra) + ')' if compra else ''
    lado = [o for o in ops if o['dentro']]
    if v['sem_preco']:
        txt += '. Sem preço de ' + ', '.join(v['sem_preco']) + ' para dizer o lado do strike'
    elif ops:
        d = max(o['dia_preco'] for o in ops)
        if lado:
            txt += (f". Com o fechamento de {d:%d/%m}, " + ' e '.join(
                f"{o['subjacente']} ({br(o['preco'])}) está {'abaixo' if o['tipo'] == 'put' else 'acima'} do strike de "
                f"{br(o['strike'])}" for o in lado))
        else:
            txt += f'. Com o fechamento de {d:%d/%m}, nenhuma está do lado do exercício'
    if v['conta'] and v['conta']['em']:
        txt += f". A conta corrente tinha R$ {br(v['conta']['saldo'])} em {v['conta']['em']:%d/%m} (Open Finance)"
    return txt + '.'


def _linha_pos(p, cot: dict | None, total: float, corretora: str) -> dict:
    preco = cot['preco'] if cot else None
    valor = p.qtd * preco if preco is not None else None
    lp = valor - p.custo if valor is not None else None
    return {'corretora': corretora, 'ticker': p.ticker, 'ativo': p.ativo, 'qtd': p.qtd, 'pm': p.pm, 'investido': p.custo,
            'pct': abs(p.custo) / abs(total) * 100 if total else 0.0, 'preco': preco, 'valor': valor,
            'ganho_pct': lp / abs(p.custo) * 100 if lp is not None and p.custo else None, 'lp': lp,
            'vencimento': p.vencimento.strftime('%d/%m/%Y') if p.vencimento else None}


def _tabela(pos: list, cot: dict, corretora: str) -> list[dict]:
    total = sum(p.custo for p in pos)
    return [_linha_pos(p, cot.get(p.ticker), total, corretora) for p in sorted(pos, key=lambda p: p.ticker)]


def _soma(linhas: list[dict]) -> dict:
    inv = sum(x['investido'] for x in linhas)
    val = sum(x['valor'] or 0.0 for x in linhas)
    return {'investido': inv, 'valor': val, 'lp': val - inv}


def _fmt_data(d):
    return d.strftime('%d/%m/%Y') if d else None


def _rotulo(ano: int, mes: int) -> str:
    return f'{mes:02d}/{ano}'


def _eventos_no_mes(ctx: dict, cart: Carteira, corte: dt.date, alertas: list, conferencia: list) -> None:
    """Eventos da B3 no fechamento: o que o motor aplicou (com a fonte), o que pede conferencia (bonificacao sem
    valor, fracao, evento que ele nao aplica, evento atrasado com negocio no meio) e os proximos 60 dias."""
    ano, mes = ctx['ano'], ctx['mes']
    for a in cart.eventos_aplicados:
        quando = (f" (a B3 publicou depois do fechamento de {a['data_com'][5:7]}/{a['data_com'][:4]}; aplicado no "
                  f"começo de {mes:02d}/{ano})" if a['atrasado'] else '')
        if a['tipo'] in ('desdobramento', 'grupamento'):
            linha = (f"{br(a['antes'], 0)} → {br(a['depois'], 0)} {a['ticker']}, o custo total não muda (preço médio "
                     f"de R$ {br(a['pm_antes'])} para R$ {br(a['pm_depois'])})")
        elif a['tipo'] == 'bonificacao':
            linha = f"+{br(a['novas'], 0)} {a['alvo']}" + (
                f" a R$ {br(a['valor'] / a['novas'])} cada (valor capitalizado informado pela empresa)"
                if a['novas'] and not a['sem_custo'] else ' a custo zero')
        elif a['tipo'] == 'restituicao':
            linha = f"o custo de {a['ticker']} cai R$ {br(a['valor'])}"
        else:
            linha = f"{br(a['antes'], 0)} {a['ticker']} viraram {br(a['depois'], 0)} {a['alvo']} com o mesmo custo"
        conferencia.append(f"Evento da B3 aplicado em {a['ticker']}: {a['texto']}{quando}: {linha}. Fonte: {a['fonte']}.")
        if a['tipo'] == 'bonificacao' and a['sem_custo'] and a['novas']:
            alertas.append(f"A CONFERIR: as {br(a['novas'], 0)} {a['alvo']} da {a['texto']} entraram a custo zero, porque "
                           'a B3 não publica o valor capitalizado por ação. Custo zero é o caminho mais conservador (mais '
                           'imposto na venda); com o valor do aviso aos acionistas, lance custo_unitario em eventos.json '
                           '(IN RFB 1.585/2015, art. 58, § 1º).')
        if a['fracao'] > 0.0001:
            alertas.append(f"A CONFERIR: no {a['texto']} de {a['ticker']} sobrou fração de {br(a['fracao'], 4)} ação, que "
                           'ficou fora da quantidade; quando o valor da fração cair na conta, confira no aviso aos '
                           'acionistas como ela entra no imposto.')
        if a['atrasado']:
            dc = dt.date.fromisoformat(a['data_com'])
            mexeu = sorted({n.pregao for nt in ctx['todas'] for n in nt.negocios
                            if a['ticker'] in (n.ticker, n.subjacente) and dc < n.pregao < ctx['ini']})
            if mexeu:
                alertas.append(f"A CONFERIR: o {a['texto']} de {a['ticker']} saiu na B3 depois do fechamento de "
                               f"{dc:%m/%Y}, e houve negócio com o papel depois da data com ({', '.join(f'{d:%d/%m}' for d in mexeu)}): "
                               f'refaça o mês (irbolsa.py fechar {dc:%Y-%m}) para o resultado usar a quantidade e o custo novos.')
    for ev in cart.eventos_avisos:
        if ev['tipo'] == 'subscricao':
            alertas.append(f"Na B3: {eventos.texto(ev)} em {ev['ticker']}. Se subscrever, a compra entra quando a nota "
                           'chegar; sem nota, lance em manuais.json.')
        else:
            alertas.append(f"A CONFERIR: a B3 publicou {eventos.texto(ev)} em {ev['ticker']}, que estava na carteira; o "
                           'motor não mexe na posição sozinho. Se mudou a quantidade ou o custo, lance em eventos.json com '
                           'o tipo, o fator e a fonte.')
    tem = {p.ticker for p in cart.posicoes() if p.qtd > 0}
    for ev in ctx['eventos']:
        d = dt.date.fromisoformat(ev['data_com'])
        if ev['ticker'] in tem and corte < d <= corte + dt.timedelta(60):
            alertas.append(f"Na B3: {eventos.texto(ev)} em {ev['ticker']}; " + (
                'a data com é o último dia para ter o papel e receber o direito.' if ev['tipo'] == 'subscricao' else
                'o motor aplica no fim do dia com.' if ev['tipo'] in eventos.APLICA else
                'o motor não mexe na posição sozinho: se mudar a quantidade ou o custo, lance em eventos.json.'))


def fecha_mes(base: pathlib.Path, ano: int, mes: int, bruto: dict | None = None, hoje: dt.date | None = None,
              gravar: bool = True, extras: list | None = None) -> dict:
    """`extras`: notas a mais, fora da pasta (o simulador do painel passa a operacao que ele quer testar)."""
    base = pathlib.Path(base)
    ctx = _contexto(base, ano, mes, extras)
    tit, saldo, origem, part, todas, excluir = (ctx[k] for k in ('tit', 'saldo', 'origem', 'part', 'todas', 'excluir'))
    hist = json.loads((base / 'historico.json').read_text()) if (base / 'historico.json').exists() else {}
    corretora = tit.get('corretora', 'SAFRA CORRETORA')
    ini, fim = dt.date(ano, mes, 1), fim_do_mes(ano, mes)
    hoje = hoje or dt.date.today()
    corte = min(fim, hoje)
    parcial = hoje <= fim                       # no ultimo dia do mes o pregao ainda nao acabou
    cart, do_mes, r = _roda(ctx, corte)
    res = {k: float(v) for k, v in r['resultados'].items()}
    alertas, conferencia = [], [f'Posição de partida: {origem}.']
    alertas += [f'Nota {n.numero} de {n.pregao:%d/%m}: {e}' for n in do_mes for e in n.erros]
    alertas += cart.alertas
    conferencia += cart.conferencia
    _eventos_no_mes(ctx, cart, corte, alertas, conferencia)

    # ---- posicao e precos
    pregao = ultimo_pregao(min(fim, hoje - dt.timedelta(1)))
    pos = cart.posicoes()
    cot = precos.fechamento(pregao, [p.ticker for p in pos], base / 'cache' / 'precos')
    dia_preco = max((dt.date.fromisoformat(c['dia']) for c in cot.values()), default=pregao)
    if dia_preco < pregao:      # o arquivo da B3 so sai a noite, depois do pregao
        conferencia.append(f'O arquivo de negócios da B3 de {pregao:%d/%m} ainda não saiu: vale o de {dia_preco:%d/%m}.')
    conferencia.append(f"Preços de fechamento de {dia_preco:%d/%m/%Y} ({'último pregão' if parcial else 'último pregão do mês'}), "
                       'do arquivo de negócios da B3.')
    sem_preco = [p.ticker for p in pos if p.ticker not in cot]
    if sem_preco:
        alertas.append('Sem preço de fechamento na B3 para ' + ', '.join(sem_preco) + ': valor de mercado fica em branco.')
    velhos = [f"{t} ({c['dia'][8:10]}/{c['dia'][5:7]})" for t, c in sorted(cot.items())
              if c['fonte'] == 'ultimo' and c['dia'] != dia_preco.isoformat()]
    if velhos:
        conferencia.append(f'Sem negócio em {dia_preco:%d/%m}; vale o último negócio: ' + ', '.join(velhos) + '.')
    refs = [t for t, c in sorted(cot.items()) if c['fonte'] == 'ref']
    if refs:
        conferencia.append('Sem negócio nos últimos 15 pregões; vale o preço de referência da B3: ' + ', '.join(refs) + '.')
    _confere_series(pos, pregao, base, conferencia)
    acoes = [p for p in pos if p.classe in ('acao', 'bdr', 'etf') and p.qtd > 0]
    fiis = [p for p in pos if p.classe == 'fii' and p.qtd > 0]
    opc_v = [p for p in pos if p.classe == 'opcao' and p.qtd < 0]
    opc_c = [p for p in pos if p.classe == 'opcao' and p.qtd > 0]
    vend_a = [p for p in pos if p.classe in ('acao', 'bdr', 'etf') and p.qtd < 0]
    vend_f = [p for p in pos if p.classe == 'fii' and p.qtd < 0]
    tabs = {'acoes': _tabela(acoes, cot, corretora), 'fii': _tabela(fiis, cot, corretora),
            'opcoes_vendidas': _tabela(opc_v, cot, corretora), 'opcoes_compradas': _tabela(opc_c, cot, corretora),
            'termos': [], 'btc': _tabela(vend_a, cot, corretora), 'fii_vendidas': _tabela(vend_f, cot, corretora)}
    resumo = [{'mercado': rot, **_soma(tabs[k])} for rot, k in (
        ('Ações', 'acoes'), ('FII', 'fii'), ('Opções Vendidas', 'opcoes_vendidas'), ('Termos', 'termos'),
        ('Opções Compradas', 'opcoes_compradas'), ('Ações BTC (Vendidas)', 'btc'), ('FII (Vendidas)', 'fii_vendidas'))]
    total_pos = {k: sum(x[k] for x in resumo) for k in ('investido', 'valor', 'lp')}

    # ---- operacoes finalizadas
    novo = r['saldo'].prejuizos
    quadro = [{'tipo': rot, 'resultado': res[k], 'prejuizo': novo.get(k, 0.0) if k != 'isento' else 0.0,
               'base': next((ln['base'] for ln in r['linhas'] if ln['tipo'] == k), 0.0),
               'imposto': next((ln['imposto'] for ln in r['linhas'] if ln['tipo'] == k), 0.0),
               'abatido': next((ln['prejuizo_usado'] for ln in r['linhas'] if ln['tipo'] == k), 0.0)}
              for rot, k in (('Comum', 'comum'), ('Day Trade', 'daytrade'), ('Fii', 'fii'), ('Isentos', 'isento'))]
    quadro.append({'tipo': 'Total', **{c: sum(q[c] for q in quadro)
                                       for c in ('resultado', 'prejuizo', 'base', 'imposto', 'abatido')}})
    grupos = {}
    for e in apuracao.agrupa(r['encerramentos']):
        g = grupos.setdefault(e.grupo, {'titulo': e.grupo, 'comum': 0.0, 'daytrade': 0.0, 'linhas': []})
        dtr = e.tipo == 'daytrade'
        g['daytrade' if dtr else 'comum'] += e.resultado
        g['linhas'].append({
            'corretora': corretora, 'ticker': e.ticker, 'ativo': e.ativo, 'tipo': e.tipo, 'mercado': e.mercado,
            'liq': {'data': _fmt_data(e.liq_data), 'cv': e.liq_cv, 'qtd': e.qtd, 'preco': e.liq_preco, 'total': e.liq_total},
            'estoque': {'data': _fmt_data(e.est_data), 'cv': e.est_cv, 'qtd': e.qtd, 'preco': e.est_preco, 'total': e.est_total},
            'comum': None if dtr else e.resultado, 'daytrade': e.resultado if dtr else None})
    ordem = ('Mercado à Vista', 'Opções de Compra', 'Opções de Venda', 'Fundos Imobiliários')
    grupos = [grupos[k] for k in ordem if k in grupos]
    barras = [{'rotulo': 'BMF', 'valor': 0.0}, {'rotulo': 'BOVESPA', 'valor': res['comum'] + res['daytrade'] + res['isento']},
              {'rotulo': 'FII/FIAGRO', 'valor': res['fii']}, {'rotulo': 'OPÇÃO FLEXIVEL', 'valor': 0.0}]
    if any(not e.est_data for e in r['encerramentos']):
        conferencia.append('Data de estoque "-": a posição foi montada antes das notas que estão no e-mail '
                           '(o custo médio vem da posição de partida).')

    # ---- extrato, proventos e aluguel
    of = transacoes_of(bruto) if bruto else []
    contados = part.get('of_ja_contado', []) if part else []
    for j in contados:
        if ini.isoformat() <= j['data'] <= fim.isoformat():
            conferencia.append(f"Lançamento {j['descricao']} de R$ {br(j['valor'])} em {j['data'][8:10]}/{j['data'][5:7]} "
                               f"fica de fora: {j.get('motivo') or 'o relatório anterior já contou'}.")
    lanc = lancamentos_bolsa(of, ini, corte, contados)
    contratos = [c for c in aluguel.ler_pasta(base / 'aluguel') if (c.get('lado') or '').lower().startswith('doador')]
    btc_bruto = btc_ir = 0.0
    sem_nota_btc = []
    for t in [x for x in lanc if x['linha'] == 'RENDIMENTOS BTC DOADOR']:
        cs = [c for c in contratos if c.get('liquidacao') == t['data']]
        if cs and abs(sum(c['bruto'] + c['irrf'] for c in cs) - t['valor']) < 0.011:
            btc_bruto += sum(c['bruto'] for c in cs)
            btc_ir += sum(c['irrf'] for c in cs)
        else:
            btc_bruto += t['valor']
            sem_nota_btc.append(t)
    if sem_nota_btc:
        conferencia.append('Aluguel de ações sem nota no e-mail (' + ', '.join(
            f"{t['data']:%d/%m} R$ {br(t['valor'])}" for t in sorted(sem_nota_btc, key=lambda t: t['data'])) +
            '): entra o valor líquido do banco, com o IR já descontado.')
    soma = lambda rot: round(float(sum(x['valor'] for x in lanc if x['linha'] == rot)), 2)  # noqa: E731
    debito_bolsa = sum(n.liquido for n in do_mes if n.liquido < 0)
    credito_bolsa = sum(n.liquido for n in do_mes if n.liquido > 0)
    linhas_ext = {'OPERAÇÕES BOLSA': (debito_bolsa, credito_bolsa), 'RENDIMENTOS BTC DOADOR': (btc_ir, btc_bruto)}
    for rot in ('JUROS S/ CAPITAL', 'DIVIDENDOS', 'RENDIMENTOS', 'REEMBOLSO BTC DOADOR', 'DESPESAS OPERACIONAIS - BTC',
                'REMUNERAÇÃO BTC TOMADOR'):
        deb = round(sum(x['valor'] for x in lanc if x['linha'] == rot and x['valor'] < 0), 2)
        cred = round(sum(x['valor'] for x in lanc if x['linha'] == rot and x['valor'] > 0), 2)
        linhas_ext[rot] = (deb, cred)
    ext = [{'lancamento': k, 'debito': d, 'credito': c, 'saldo': d + c}
           for k, (d, c) in sorted(linhas_ext.items()) if abs(d) + abs(c) > 0.0001]
    extrato = {'periodo': f'{ini:%d/%m/%Y} até {corte:%d/%m/%Y}', 'corretora': corretora, 'linhas': ext,
               'totais': {'debito': sum(x['debito'] for x in ext), 'credito': sum(x['credito'] for x in ext),
                          'saldo': sum(x['saldo'] for x in ext)}}
    prov = {'dividendos': soma('DIVIDENDOS'), 'jcp': soma('JUROS S/ CAPITAL'), 'rendimentos': soma('RENDIMENTOS'),
            'bonificacoes': round(sum(a['valor'] for a in cart.eventos_aplicados if a['tipo'] == 'bonificacao'
                                      and ini.isoformat() <= a['data_com'] <= fim.isoformat()), 2),
            'reembolso_btc': soma('REEMBOLSO BTC DOADOR'), 'rendimentos_btc': soma('RENDIMENTOS BTC DOADOR')}
    prov_total = round(sum(prov.values()), 2)
    despesas = soma('DESPESAS OPERACIONAIS - BTC') + soma('REMUNERAÇÃO BTC TOMADOR')
    hist_prov = {x['rotulo']: x['valor'] for x in hist.get('proventos_12m', [])}
    for e in estados(base):
        hist_prov[_rotulo(e['ano'], e['mes'])] = e['proventos_total']
    hist_prov[_rotulo(ano, mes)] = prov_total
    meses_12 = []
    for i in range(11, -1, -1):
        a, m = divmod(ano * 12 + mes - 1 - i, 12)
        meses_12.append({'rotulo': _rotulo(a, m + 1), 'valor': hist_prov.get(_rotulo(a, m + 1), 0.0)})
    proventos = {'por_corretora': [{'corretora': corretora, **prov, 'total': prov_total}],
                 'total': {**prov, 'total': prov_total}, 'meses_12': meses_12,
                 'total_12m': round(sum(x['valor'] for x in meses_12), 2), 'detalhe': []}
    proximos = []
    for i in range(12):
        a, m = divmod(ano * 12 + mes - 1 + i, 12)
        proximos.append({'rotulo': _rotulo(a, m + 1), 'valor': 0.0})
    provisionados = {'proximos_12m': proximos, 'total_12m': 0.0, 'sem_data_total': 0.0, 'por_corretora': [],
                     'linhas': [], 'total': 0.0}

    # ---- tabela anual
    col = {'OP. COMUM': res['comum'], 'DAYTRADE': res['daytrade'], 'FII': res['fii'],
           'PROVENTOS': prov['dividendos'] + prov['jcp'] + prov['rendimentos'],
           'BTC DOADOR': prov['reembolso_btc'] + prov['rendimentos_btc'], 'VENDAS ISENTAS': res['isento'],
           'BONIFICAÇÕES': prov['bonificacoes']}
    col['SOMA'] = sum(col.values())
    col['IMPOSTOS'] = -r['darf']
    col['DESPESAS'] = despesas
    col['LÍQUIDO'] = col['SOMA'] + col['IMPOSTOS'] + col['DESPESAS']
    anual_hist = {k: list(v) + [0.0] * (12 - len(v)) for k, v in hist.get('anual', {}).get(str(ano), {}).items()}
    do_agente = {e['mes'] for e in estados(base) if e['ano'] == ano}
    ajs = [x for x in ajustes_irtrade(hist) if x['ano'] == ano and x['mes'] < mes and x['mes'] not in do_agente]
    for x in ajs:       # o resultado do tipo muda, e a SOMA e o LIQUIDO com ele
        for k in (LINHA_DO_TIPO[x['tipo']], 'SOMA', 'LÍQUIDO'):
            v = anual_hist.setdefault(k, [0.0] * 12)
            v[x['mes'] - 1] = round(v[x['mes'] - 1] + x['delta'], 2)
    for e in estados(base):
        if e['ano'] == ano and e['mes'] < mes:
            for k, v in e['anual'].items():
                anual_hist.setdefault(k, [0.0] * 12)[e['mes'] - 1] = v
    linhas_anuais = []
    for k in LINHAS_ANUAIS:
        vals = list(anual_hist.get(k) or [0.0] * 12)[:12]
        vals[mes - 1] = col[k]
        vals[mes:] = [0.0] * (12 - mes)
        linhas_anuais.append({'rotulo': k, 'valores': vals, 'total': sum(vals), 'destaque': k in ('SOMA', 'LÍQUIDO')})
    fonte_hist = hist.get('fonte')
    anual = {'ano': ano, 'meses': list(MESES), 'linhas': linhas_anuais,
             'nota': ('Resultado líquido = operações finalizadas + proventos - impostos e despesas. ' +
                      (f'{fonte_hist}; ' if fonte_hist else '') +
                      ''.join(f"{NOME_DO_TIPO[x['tipo']]} de {x['mes']:02d}/{ano} com ajuste de R$ {br(x['delta'])}"
                              f"{' (' + x['motivo'] + ')' if x['motivo'] else ''}; " for x in ajs) +
                      f'{MESES[mes - 1]}/{ano} apurado a partir das notas de corretagem e do Open Finance' +
                      (f', parcial até {corte:%d/%m}.' if parcial else '.'))}

    # ---- situacao fiscal e alertas
    venc = r['vencimento']
    darfs = []
    reg = pathlib.Path(base) / 'estado' / 'diario.json'     # DARF pago fora do Safra (irbolsa.py pago), com ou sem data
    pagos = (json.loads(reg.read_text()).get('pagos') or {}) if reg.exists() else {}
    for d in hist.get('darfs', []) + [
            {'periodo': _rotulo(e['ano'], e['mes']), 'valor': e['resumo']['darf'], 'vencimento': e['resumo']['vencimento']}
            for e in estados(base) if e['resumo'].get('darf') and (e['ano'], e['mes']) != (ano, mes)]:
        mm, aa = (int(x) for x in d['periodo'].split('/'))
        vd = dt.datetime.strptime(d['vencimento'], '%d/%m/%Y').date()
        pago = pagamento_darf(of, fim_do_mes(aa, mm), d['valor']) if of else None
        info = pagos.get(f'{aa}-{mm:02d}')
        if info:
            sit = f"pago em {dt.date.fromisoformat(info['data']):%d/%m/%Y}" if info.get('data') else 'pago, sem a data'
        elif pago:
            sit = f"pago em {pago['data']:%d/%m/%Y}"
        elif vd < hoje:
            sit = 'sem pagamento no Safra'
            alertas.append(f"DARF de {d['periodo']} (R$ {br(d['valor'])}, venceu em {d['vencimento']}): não achei o "
                           'pagamento na conta do Safra pelo Open Finance. Se pagou por outro banco, ignore; se não '
                           'pagou, ainda dá para pagar com multa e juros (Lei 9.430/1996, art. 61).')
        else:
            sit = 'a pagar'
        darfs.append({'periodo': d['periodo'], 'codigo': apuracao.CODIGO_DARF, 'vencimento': d['vencimento'],
                      'valor': d['valor'], 'situacao': sit})
    if r['darf']:
        darfs.append({'periodo': _rotulo(ano, mes), 'codigo': apuracao.CODIGO_DARF, 'vencimento': _fmt_data(venc),
                      'valor': r['darf'], 'situacao': 'parcial, pode mudar até o fim do mês' if parcial else 'a pagar'})
    elif r['devido'] > 0:
        conferencia.append(f"Imposto de R$ {br(r['devido'])} abaixo de R$ 10,00: não vira DARF e passa para o mês "
                           'seguinte (Lei 9.430/1996, art. 68).')
    if r['irrf_usado']:
        conferencia.append(f"IR retido na fonte abatido do imposto: R$ {br(r['irrf_mes'])} das notas do mês" +
                           (f' + R$ {br(saldo.irrf)} de saldo de meses anteriores' if saldo.irrf else '') + '.')
    if not excluir:
        conferencia.append('Custo de cada operação com todas as taxas da nota, inclusive ISS, PIS/COFINS e taxa de '
                           'transferência (IN RFB 1.585/2015, art. 56, §§ 3º e 4º).')
    prejuizos = [{'tipo': 'Comum', 'valor': novo['comum']}, {'tipo': 'Day Trade', 'valor': novo['daytrade']},
                 {'tipo': 'FII', 'valor': novo['fii']}]
    con = concilia(todas, of, ini, corte) if of else None
    if con:
        for t in con['sem_nota']:
            alertas.append(f"Liquidação de bolsa de R$ {br(t['valor'])} em {t['data']:%d/%m} sem nota no e-mail: o "
                           'imposto do mês pode estar errado. Peça a nota ao Safra ou lance em manuais.json.')
        for n in con['sem_lancamento']:
            if con['ultimo_of'] and n.liquidacao <= con['ultimo_of']:
                alertas.append(f'Nota {n.numero} ({n.pregao:%d/%m}, R$ {br(n.liquido)}) devia ter liquidado em '
                               f'{n.liquidacao:%d/%m} e não aparece no Open Finance.')
        if con['ultimo_of'] and con['ultimo_of'] < pregao:
            alertas.append(f"Open Finance com lançamentos só até {con['ultimo_of']:%d/%m}: proventos e aluguel depois "
                           'disso ainda não entraram.')
    elif not of:
        alertas.append('Sem o extrato do Open Finance: proventos, aluguel e conciliação das notas ficaram de fora.')
    for p in sorted(opc_v + opc_c, key=lambda p: (p.vencimento or dt.date.max, p.ticker)):
        if not p.vencimento or not 0 <= (p.vencimento - corte).days <= 31:
            continue
        tipo = 'put' if p.tipo_opcao == 'put' else 'call'
        txt = f'{p.ticker} ({tipo} de {p.subjacente}' + (f', strike {br(p.strike)}' if p.strike else '') + \
              f') vence em {p.vencimento:%d/%m}'
        sub = precos.fechamento(pregao, [p.subjacente], base / 'cache' / 'precos').get(p.subjacente) if p.subjacente else None
        if sub:
            txt += f"; {p.subjacente} fechou a {br(sub['preco'])} em {sub['dia'][8:10]}/{sub['dia'][5:7]}"
            dentro = p.strike and ((tipo == 'put' and sub['preco'] < p.strike) or (tipo == 'call' and sub['preco'] > p.strike))
            if dentro and p.qtd < 0:
                lado = 'compra' if tipo == 'put' else 'venda'
                txt += (f", {'abaixo' if tipo == 'put' else 'acima'} do strike: se ficar assim, o exercício gera a {lado} "
                        f"de {br(abs(p.qtd), 0)} {p.subjacente} a {br(p.strike)} (R$ {br(abs(p.qtd) * p.strike)})")
        alertas.append(txt + '.')
    vendas = r['vendas_acoes']
    duv = r['duvidas']
    if duv['vendas_daytrade']:
        alertas.append(f"A CONFERIR: as vendas de ações do mês (R$ {br(vendas)}) incluem R$ {br(duv['vendas_daytrade'])} de "
                       'day trade; com elas o mês passa de R$ 20.000,00 e o lucro das ações é tributado, sem elas seria '
                       'isento. O cálculo contou o day trade, que é o caminho mais conservador: confirme com o contador.')
    if duv['units_isentas']:
        alertas.append('A CONFERIR: o lucro de ' + ', '.join(duv['units_isentas']) + ' (units) entrou como isento, junto '
                       'com as ações; a IN RFB 1.585/2015, art. 59, fala em ações e não cita units. Confirme com o contador.')
    cus = venc_op = None
    if parcial and not extras:      # o banco e o vencimento falam do mes em curso, e o simulador nao mexe neles
        cus = confere_custodia(custodia_of(bruto), cart, todas, corte, ctx['eventos'])
        if cus and not cus['divergencias'] and cus['ok']:
            onde = (f"na posição de {cus['ok'][0]}" if len(cus['ok']) == 1 else
                    f"nas {len(cus['ok'])} posições: {cus['acoes']} em ações e {cus['fii']} em FII")
            conferencia.append(f"Custódia do Safra de {cus['data']:%d/%m} (Open Finance) bate com o motor {onde}.")
        for d in (cus or {}).get('divergencias', []):
            alertas.append(f"Custódia de {d['ticker']} no Safra em {cus['data']:%d/%m} (Open Finance): "
                           f"{br(d['banco'], 0)} no banco, {br(d['motor'], 0)} no motor. Pode ser: " +
                           '; '.join(d['pistas']) + '.')
        venc_op = cenarios_vencimento(ctx, cart, corte, pregao, bruto)
        if venc_op:
            alertas.append(_texto_vencimento(venc_op))
    if parcial:
        conferencia.insert(0, f'Mês em andamento: apurado até {corte:%d/%m}; o DARF só fecha depois do último pregão.')
        alertas.append(f'Vendas de ações no mês até agora: R$ {br(vendas)}. Até R$ 20.000,00 no mês o lucro em ações é '
                       'isento; acima disso o lucro do mês inteiro é tributado.')
    elif r['darf']:
        dias = (venc - hoje).days
        alertas.insert(0, f"DARF de {_rotulo(ano, mes)}: R$ {br(r['darf'])}, código {apuracao.CODIGO_DARF}, vence em "
                          f"{venc:%d/%m/%Y}" + (f' (faltam {dias} dias).' if dias >= 0 else f' (VENCIDO há {-dias} dias).'))
    if r['darf'] and venc != apuracao.ultimo_dia_util(venc.year, venc.month):
        conferencia.append(VENCE_30_12)
    situacao = {'darfs': darfs, 'prejuizos': prejuizos, 'alertas': alertas, 'conferencia': conferencia}

    doc = re.sub(r'\D', '', tit.get('documento') or documento_of(bruto))
    doc_fmt = f'{doc[:3]}.{doc[3:6]}.{doc[6:9]}-{doc[9:]}' if len(doc) == 11 else doc
    dados = {
        'titular': {'nome': tit['nome'], 'documento': doc_fmt}, 'competencia': _rotulo(ano, mes),
        'gerado_em': hoje.strftime('%d/%m/%Y'), 'data_posicao': (pregao if parcial else fim).strftime('%d/%m/%Y'),
        'corretora': corretora, 'parcial': parcial, 'resumo_posicao': resumo, 'total_posicao': total_pos, 'posicoes': tabs,
        'operacoes': {'quadro': quadro, 'barras': barras, 'grupos': grupos, 'comum': res['comum'], 'daytrade': res['daytrade']},
        'extrato': extrato, 'proventos': proventos, 'provisionados': provisionados, 'anual': anual, 'situacao': situacao,
    }
    darf = None
    if r['darf']:
        darf = {'nome': tit['nome'], 'telefone': tit.get('telefone', ''), 'periodo_apuracao': fim.strftime('%d/%m/%Y'),
                'documento': doc_fmt, 'codigo_receita': apuracao.CODIGO_DARF, 'referencia': '',
                'vencimento': venc.strftime('%d/%m/%Y'), 'principal': r['darf'], 'multa': 0.0, 'juros': 0.0,
                'total': r['darf'], 'competencia': _rotulo(ano, mes), 'parcial': parcial,
                'mes_ref': MESES_EXTENSO[mes - 1], 'ano_ref': ano, 'valido_ate': venc.strftime('%d/%m/%Y'),
                'observacao': f'Ganhos líquidos em operações na bolsa (renda variável), {MESES[mes - 1].lower()}/{ano}.'}
    estado = {'ano': ano, 'mes': mes, 'corte': corte.isoformat(), 'parcial': parcial, 'origem': origem,
              'posicoes': [apuracao.posicao_dict(p) for p in pos],
              'saldo': {'prejuizos': novo, 'irrf': r['saldo'].irrf, 'pendente': r['saldo'].pendente},
              'resumo': {'resultados': res, 'imposto_bruto': r['imposto_bruto'], 'irrf_mes': r['irrf_mes'],
                         'irrf_usado': r['irrf_usado'], 'devido': r['devido'], 'darf': r['darf'],
                         'vencimento': _fmt_data(venc), 'vendas_acoes': vendas, 'isento_mes': r['isento_mes']},
              'anual': {k: col[k] for k in LINHAS_ANUAIS}, 'proventos_total': prov_total,
              'eventos': sorted(set(cart.eventos_vistos)), 'gerado_em': dt.datetime.now().isoformat(timespec='seconds')}
    if gravar:
        (base / 'estado').mkdir(parents=True, exist_ok=True)
        arq = base / 'estado' / (f'{ano}-{mes:02d}.parcial.json' if parcial else f'{ano}-{mes:02d}.json')
        if arq.exists() and not parcial:
            antes = json.loads(arq.read_text())
            if {k: v for k, v in antes.items() if k != 'gerado_em'} != \
                    json.loads(json.dumps({k: v for k, v in estado.items() if k != 'gerado_em'})):
                # refazer um mes fechado guarda a versao anterior (nada some)
                (base / 'estado' / 'anteriores').mkdir(exist_ok=True)
                arq.rename(livre(base / 'estado' / 'anteriores' /
                                 f"{arq.stem} {antes.get('gerado_em', '')[:16].replace(':', '')}.json"))
        arq.write_text(json.dumps(estado, ensure_ascii=False, indent=1))
    return {'dados': dados, 'darf': darf, 'estado': estado, 'apuracao': r, 'conciliacao': con, 'custodia': cus,
            'vencimento': venc_op, 'eventos': cart.eventos_aplicados}
