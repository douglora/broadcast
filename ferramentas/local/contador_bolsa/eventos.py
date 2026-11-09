"""Eventos societarios da B3 para a carteira do titular: bonificacao, desdobramento e grupamento mudam a quantidade
(e, na bonificacao, o custo); os outros (cisao, resgate, subscricao) viram aviso e pista na conferencia da custodia.

Fonte: o cadastro de empresas listadas da B3 (GetListedSupplementCompany, o mesmo da pagina de eventos corporativos
de cada empresa, que serve acao e FII), um pedido por empresa, guardado em cache/eventos/ e refeito uma vez por dia
pela rotina; o fechamento do mes so le o que ficou gravado. O fator vem como a B3 publica, conferido em 08/11/2026
com dois eventos reais (um desdobramento publicado como "200", em que cada acao virou 3, e uma bonificacao "1", de
1%): desdobramento e bonificacao em percentual de acrescimo, grupamento como multiplicador da quantidade.

Custo (REGRAS.md; IN RFB 1.585/2015, art. 58): desdobramento nao muda o custo total (acao nova a custo zero, par. 6) e o
grupamento tambem nao (nenhum dinheiro entra nem sai); bonificacao entra pelo valor capitalizado por acao que a
empresa informa (par. 1; eventos.json, "custo_unitario"); sem ele, a custo zero e A CONFERIR; restituicao de capital
em dinheiro reduz o custo (par. 8).

Na pasta do titular: eventos_b3.json (gravado aqui) e eventos.json (do titular, por cima do da B3, com a fonte):
  [{"ticker", "tipo", "data_com" (AAAA-MM-DD), "fator", "custo_unitario", "valor_por_acao", "novo_ticker",
    "ignorar", "fonte"}]
tipo: desdobramento, grupamento, bonificacao (mudam a quantidade), restituicao (valor_por_acao reduz o custo), troca
(a posicao inteira vai para novo_ticker, com o fator), aviso (so alerta) e subscricao (so pista).
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import pathlib
import re
import urllib.request

URL = 'https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/GetListedSupplementCompany/'
MUDA_QTD = {'BONIFICACAO': 'bonificacao', 'DESDOBRAMENTO': 'desdobramento', 'GRUPAMENTO': 'grupamento'}
APLICA = ('desdobramento', 'grupamento', 'bonificacao', 'restituicao', 'troca')
NOME = {'desdobramento': 'desdobramento', 'grupamento': 'grupamento', 'bonificacao': 'bonificação',
        'restituicao': 'restituição de capital', 'troca': 'troca de código', 'subscricao': 'subscrição', 'aviso': 'evento'}
# tipo do papel no ISIN (caracteres 7 a 11) -> final do ticker, quando o Open Finance nao traz o ISIN do papel
SUFIXO_ISIN = (('ACNOR', '3'), ('ACNPR', '4'), ('ACNPA', '5'), ('ACNPB', '6'), ('CDAM', '11'), ('CTF', '11'))
CLASSES = ('acao', 'fii', 'bdr', 'etf')


def ident(ev: dict) -> str:
    return f"{ev['ticker']}:{ev['tipo']}:{ev['data_com']}"


def _num(s) -> float | None:
    try:
        return float(str(s).replace('.', '').replace(',', '.'))
    except ValueError:
        return None


def _data(s) -> dt.date | None:
    try:
        return dt.datetime.strptime(str(s or ''), '%d/%m/%Y').date()
    except ValueError:
        return None


def ticker_do_isin(isin: str | None, mapa: dict) -> str | None:
    if not isin:
        return None
    if isin in mapa:
        return mapa[isin]
    m = re.fullmatch(r'BR([A-Z]{4})([A-Z0-9]{5})\w', isin)
    if not m:
        return None
    return next((m.group(1) + suf for tipo, suf in SUFIXO_ISIN if m.group(2).startswith(tipo)), None)


def _pede(cod: str) -> list:
    q = base64.b64encode(json.dumps({'issuingCompany': cod, 'language': 'pt-br'}).encode()).decode()
    req = urllib.request.Request(URL + q, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode() or 'null') or []


def empresa(cod: str, cache: pathlib.Path, hoje: dt.date, pede=None) -> list:
    """Cadastro da empresa na B3, lido no maximo uma vez por dia."""
    arq = pathlib.Path(cache) / f'{cod}.json'
    if arq.exists():
        d = json.loads(arq.read_text())
        if d.get('dia') == hoje.isoformat():
            return d['dados']
    dados = (pede or _pede)(cod)
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps({'dia': hoje.isoformat(), 'dados': dados}, ensure_ascii=False))
    return dados


def normaliza(raw: list, mapa: dict, desde: dt.date) -> list[dict]:
    """Eventos em ativos e subscricoes com data com depois de `desde` (o que veio antes ja esta na posicao de partida)."""
    out = []
    for x in raw or []:
        for it in x.get('stockDividends') or []:
            d, tk = _data(it.get('lastDatePrior')), ticker_do_isin(it.get('isinCode'), mapa)
            if not d or d <= desde or not tk:
                continue
            rot, f = (it.get('label') or '').strip().upper(), _num(it.get('factor'))
            ev = {'ticker': tk, 'data_com': d.isoformat(), 'rotulo': rot, 'isin': it.get('isinCode'),
                  'fonte': f"B3, {rot.lower()} aprovado em {it.get('approvedOn') or '-'}"}
            if rot in MUDA_QTD and f:
                ev.update(tipo=MUDA_QTD[rot], percentual=f, fator=round(f if rot == 'GRUPAMENTO' else 1 + f / 100, 10))
                novo = ticker_do_isin(it.get('assetIssued'), mapa)
                if rot == 'BONIFICACAO' and novo and novo != tk:      # bonificacao paga em outra classe
                    ev['novo_ticker'] = novo
            else:
                ev.update(tipo='aviso', fator=f)
            out.append(ev)
        for it in x.get('subscriptions') or []:
            d, tk = _data(it.get('lastDatePrior')), ticker_do_isin(it.get('isinCode'), mapa)
            if not d or d <= desde or not tk:
                continue
            ds = _data(it.get('subscriptionDate'))
            out.append({'ticker': tk, 'tipo': 'subscricao', 'data_com': d.isoformat(), 'isin': it.get('isinCode'),
                        'percentual': _num(it.get('percentage')), 'preco': _num(it.get('priceUnit')),
                        'data_subscricao': ds.isoformat() if ds else None,
                        'fonte': f"B3, subscrição aprovada em {it.get('approvedOn') or '-'}"})
    return out


def atualizar(base: pathlib.Path, tickers, mapa: dict, hoje: dt.date, desde: dt.date, pede=None) -> dict:
    """Busca na B3 os eventos das empresas dos papeis e grava eventos_b3.json (so os papeis da lista: a empresa tem ON,
    PN e unit). Empresa que nao respondeu fica com a leitura anterior, e o erro volta para a rotina avisar."""
    base = pathlib.Path(base)
    arq = base / 'eventos_b3.json'
    antes = json.loads(arq.read_text()) if arq.exists() else {}
    tks = {t for t in tickers if t}
    evs, erros = [], []
    for cod in sorted({t[:4] for t in tks}):
        try:
            evs += normaliza(empresa(cod, base / 'cache' / 'eventos', hoje, pede), mapa, desde)
        except Exception as x:      # noqa: BLE001  (rede, resposta fora do formato)
            erros.append(f'{cod} ({type(x).__name__})')
            evs += [e for e in antes.get('eventos', []) if e['ticker'][:4] == cod]
    evs = sorted({ident(e): e for e in evs if e['ticker'] in tks}.values(), key=lambda e: (e['data_com'], e['ticker']))
    out = {'lido_em': dt.datetime.now().isoformat(timespec='minutes'), 'desde': desde.isoformat(), 'eventos': evs,
           'erros': erros}
    arq.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def carrega(base: pathlib.Path) -> list[dict]:
    """Os eventos que o motor conhece: os da B3 com os do titular por cima (mesmo papel, tipo e data com: vale o do
    titular; "ignorar": true tira um evento da B3)."""
    base = pathlib.Path(base)
    b3 = json.loads((base / 'eventos_b3.json').read_text()).get('eventos', []) if (base / 'eventos_b3.json').exists() else []
    seus = json.loads((base / 'eventos.json').read_text()) if (base / 'eventos.json').exists() else []
    por_id = {ident(e): e for e in b3}
    for e in seus:
        por_id[ident(e)] = {**por_id.get(ident(e), {}), **e, 'fonte': e.get('fonte') or 'eventos.json'}
    return sorted((e for e in por_id.values() if not e.get('ignorar')), key=lambda e: (e['data_com'], e['ticker']))


def _n(x) -> str:
    """Numero curto em formato brasileiro, sem zeros a direita (3 -> '3'; 1,5 -> '1,5')."""
    return f'{float(x):.6f}'.rstrip('0').rstrip('.').replace('.', ',')


def _rs(x) -> str:
    """Valor por papel em reais: duas casas, ou ate seis quando o valor tem mais (95 -> '95,00'; 0,123456)."""
    i, _, d = f'{float(x):.6f}'.rstrip('0').partition('.')
    return f'{int(i):,}'.replace(',', '.') + ',' + d.ljust(2, '0')


def texto(ev: dict) -> str:
    """'bonificação de 1% com data com 17/12/2025' (para alerta e conferencia)."""
    d = dt.date.fromisoformat(ev['data_com'])
    t, f = ev['tipo'], ev.get('fator')
    if t == 'grupamento' and f:
        inv = 1 / f
        det = f'de {_n(round(inv))} para 1' if abs(inv - round(inv)) < 1e-6 else f'de fator {_n(f)}'
    elif t == 'desdobramento' and f:
        det = f'de 1 para {_n(f)}'
    elif t == 'bonificacao' and f:
        det = f'de {_n((f - 1) * 100)}%'
    elif t == 'restituicao':
        det = f"de R$ {_rs(ev.get('valor_por_acao') or 0)} por ação"
    elif t == 'troca':
        det = f"para {ev.get('novo_ticker')}"
    elif t == 'subscricao':
        det = f"de {_n(round(ev.get('percentual') or 0, 2))}% a R$ {_rs(ev.get('preco') or 0)} por papel"
    else:
        det = f"({(ev.get('rotulo') or '').lower()})"
    return f"{NOME.get(t, t)} {det} com data com {d:%d/%m/%Y}"
