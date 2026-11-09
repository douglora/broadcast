"""Linha de comando do contador de bolsa: python3 ferramentas/local/irbolsa.py <comando> (-h para a ajuda).

A pasta do titular fica em ~/.autopilot/contador-bolsa/douglas (ou CONTADOR_BOLSA_TITULAR, ou --titular) e o extrato
do Open Finance em ~/.autopilot/clientes/douglas-lora/bruto.json (ou CONTADOR_BOLSA_OF, ou --of), que o terminal
atualiza as 8h e as 19h. Nada aqui imprime o documento do titular: ele so vai para o DARF e para a senha dos PDFs.

O registro da rotina (estado/diario.json) guarda os meses fechados, os e-mails enviados, os pagamentos informados, os
lancamentos do Open Finance ja vistos e os alertas ja mostrados, para a sessao so trazer o que e novo.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import webbrowser

from alocacao.dias import feriados

from . import apuracao, darf, eventos, gmail, mes, relatorio
from .mes import br

TITULAR = pathlib.Path(os.environ.get('CONTADOR_BOLSA_TITULAR') or
                       pathlib.Path.home() / '.autopilot/contador-bolsa/douglas')
OPEN_FINANCE = pathlib.Path(os.environ.get('CONTADOR_BOLSA_OF') or
                            pathlib.Path.home() / '.autopilot/clientes/douglas-lora/bruto.json')
ESPERA_OF = 3            # dias uteis depois do fim do mes que o fechamento espera o Open Finance ler o ultimo dia util
EMAIL_ATE_DIAS = 45      # fechamento mais velho que isso nao gera e-mail pendente
JANELA_OF = 60           # dias do extrato do Open Finance comparados de uma rodada para a outra


# ---- apoio ---------------------------------------------------------------------------------------
def _comp(txt: str) -> tuple[int, int]:
    m = re.fullmatch(r'(\d{4})-(\d{1,2})', txt or '')
    if not m or not 1 <= int(m[2]) <= 12:
        raise argparse.ArgumentTypeError('use AAAA-MM, por exemplo 2026-10')
    return int(m[1]), int(m[2])


def _bruto(arq: pathlib.Path) -> dict | None:
    return json.loads(pathlib.Path(arq).read_text()) if pathlib.Path(arq).exists() else None


def _titular(base: pathlib.Path) -> dict:
    return json.loads((base / 'titular.json').read_text())


def _documento(base: pathlib.Path, bruto: dict | None) -> str:
    doc = re.sub(r'\D', '', _titular(base).get('documento') or (mes.documento_of(bruto) if bruto else ''))
    if len(doc) != 11:
        raise SystemExit('documento do titular nao encontrado (titular.json ou Open Finance): o DARF e a senha dos '
                         'PDFs precisam dele')
    return doc


def _guarda(arq: pathlib.Path) -> None:
    """Arquivo que vai ser refeito vai para anteriores/ com a data dele (nada some)."""
    if arq.exists():
        pasta = arq.parent / 'anteriores'
        pasta.mkdir(exist_ok=True)
        arq.rename(mes.livre(pasta / f'{arq.stem} {dt.datetime.fromtimestamp(arq.stat().st_mtime):%Y-%m-%d %H%M}{arq.suffix}'))


def _reg(base: pathlib.Path) -> dict:
    arq = base / 'estado' / 'diario.json'
    reg = json.loads(arq.read_text()) if arq.exists() else {}
    for k in ('fechamentos', 'emails', 'pagos', 'avisados'):
        reg.setdefault(k, {})
    return reg


def _grava_reg(base: pathlib.Path, reg: dict) -> None:
    (base / 'estado').mkdir(parents=True, exist_ok=True)
    (base / 'estado' / 'diario.json').write_text(json.dumps(reg, ensure_ascii=False, indent=1))


def _agora() -> str:
    return dt.datetime.now().isoformat(timespec='seconds')


def _uteis_entre(d0: dt.date, d1: dt.date) -> int:
    """Dias uteis depois de d0 ate d1, inclusive."""
    n, d = 0, d0 + dt.timedelta(1)
    while d <= d1:
        n += d.weekday() < 5 and d not in feriados(d.year)
        d += dt.timedelta(1)
    return n


def nomes(ano: int, mm: int) -> tuple[str, str]:
    """Nome dos PDFs, como o da IRTrade ("Relatorio mensal 9-2026.pdf")."""
    return f'Relatorio mensal {mm}-{ano}.pdf', f'DARF {mm}-{ano}.pdf'


def meses_abertos(base: pathlib.Path, hoje: dt.date) -> list[tuple[int, int]]:
    """Meses que ja acabaram e ainda nao tem fechamento, a partir do ultimo fechado (ou da partida)."""
    feitos = sorted(a.name[:7] for a in (base / 'estado').glob('*.json') if re.fullmatch(r'\d{4}-\d{2}\.json', a.name))
    if feitos:
        ano, mm = int(feitos[-1][:4]), int(feitos[-1][5:7])
    else:
        d = dt.date.fromisoformat(json.loads((base / 'partida.json').read_text())['data'])
        ano, mm = d.year, d.month
    out = []
    while True:
        ano, mm = ano + mm // 12, mm % 12 + 1
        if mes.fim_do_mes(ano, mm) >= hoje:
            return out
        out.append((ano, mm))


def _tickers_carteira(base: pathlib.Path, bruto: dict | None) -> set[str]:
    """Papeis da carteira para os eventos da B3: os dois ultimos estados (o fechado e o parcial), ou a partida, mais a
    custodia do banco no Open Finance."""
    pasta = base / 'estado'
    arqs = sorted(a for a in pasta.glob('*.json') if re.fullmatch(r'\d{4}-\d{2}(\.parcial)?\.json', a.name)) \
        if pasta.is_dir() else []
    fontes = [json.loads(a.read_text())['posicoes'] for a in arqs[-2:]]
    if not fontes and (base / 'partida.json').exists():
        fontes = [json.loads((base / 'partida.json').read_text())['posicoes']]
    tks = {p['ticker'] for ps in fontes for p in ps if p.get('classe') in eventos.CLASSES and p.get('qtd', 0) > 0}
    cust = mes.custodia_of(bruto)
    return tks | set(cust['itens'] if cust else ())


def atualiza_eventos(base: pathlib.Path, bruto: dict | None, hoje: dt.date) -> tuple[dict | None, list[str]]:
    """Le na B3 os eventos societarios dos papeis da carteira (uma vez por dia por empresa); falha vira alerta e o
    fechamento usa a ultima leitura gravada."""
    p = base / 'partida.json'
    desde = dt.date.fromisoformat(json.loads(p.read_text())['data']) if p.exists() else hoje.replace(day=1)
    try:
        out = eventos.atualizar(base, _tickers_carteira(base, bruto), mes.isin_of(bruto), hoje, desde)
    except Exception as x:      # noqa: BLE001  (a rotina segue com a leitura anterior)
        return None, [f'Eventos da B3 não lidos hoje ({type(x).__name__}): o fechamento usa a última leitura gravada.']
    al = [f"Eventos da B3 sem resposta hoje para {', '.join(out['erros'])}: vale a leitura anterior dessas empresas."] \
        if out['erros'] else []
    return out, al


def texto_eventos(base: pathlib.Path, lido: dict | None) -> str:
    evs = eventos.carrega(base)
    cab = 'EVENTOS DA B3 NA CARTEIRA' + (f" (lidos em {dt.datetime.fromisoformat(lido['lido_em']):%d/%m %Hh%M})"
                                         if lido else ' (última leitura gravada)')
    if not evs:
        return cab + ': nenhum depois da posição de partida.'
    return '\n'.join([cab] + [f"  {dt.date.fromisoformat(e['data_com']):%d/%m/%Y} {e['ticker']:8} {eventos.texto(e)} "
                              f"({e.get('fonte') or '-'})" for e in evs])


def texto_vencimento(v: dict | None, comp: str) -> str:
    if not v:
        return f'VENCIMENTO {comp}: nenhuma opção lançada vence até o fim do mês.'
    L = [f"VENCIMENTO {comp} (até {v['ate']:%d/%m}): {v['nota']}"]
    for o in v['opcoes']:
        lado = ('sem preço do ativo-objeto' if o['preco'] is None else
                f"{o['subjacente']} a {br(o['preco'])} em {o['dia_preco']:%d/%m}, " +
                ('do lado do exercício' if o['dentro'] else 'do lado do pó'))
        L.append(f"  {o['ticker']}: {o['tipo']} lançada de {br(o['qtd'], 0)} {o['subjacente']}, strike {br(o['strike'])}, "
                 f"prêmio R$ {br(o['premio'])}, vence {o['vencimento']:%d/%m}; {lado}")
    for c in v['cenarios']:
        nome = ('nenhuma exercida' if not c['exercidas'] else 'exercidas: ' + ', '.join(c['exercidas']))
        pos = '; '.join(f"{t} {br(x['qtd'], 0)} a PM R$ {br(x['pm'])}" for t, x in c['posicoes'].items())
        din = (f"sai R$ {br(-c['caixa'])} da conta na liquidação" if c['caixa'] < 0 else
               f"entra R$ {br(c['caixa'])} na conta na liquidação" if c['caixa'] > 0 else 'nenhum dinheiro na liquidação')
        L.append(f"  {'[provável] ' if c['provavel'] else ''}{nome}: DARF R$ {br(c['darf'])} (imposto R$ "
                 f"{br(c['imposto'])}), {din}" + (f'; fica {pos}' if pos else ''))
    if v['conta']:
        L.append(f"  Conta corrente: R$ {br(v['conta']['saldo'])}" +
                 (f" em {v['conta']['em']:%d/%m às %Hh%M} (Open Finance)" if v['conta']['em'] else ''))
    return '\n'.join(L)


def _resumo(out: dict) -> dict:
    d, r = out['dados'], out['apuracao']
    return {'competencia': d['competencia'], 'parcial': d['parcial'], 'darf': r['darf'], 'devido': r['devido'],
            'imposto': r['imposto_bruto'], 'irrf_usado': r['irrf_usado'],
            'vencimento': r['vencimento'].strftime('%d/%m/%Y'), 'vendas_acoes': r['vendas_acoes'],
            'resultados': {k: round(float(v), 2) for k, v in r['resultados'].items()},
            'prejuizos': {k: round(float(v), 2) for k, v in r['saldo'].prejuizos.items()},
            'frase': gmail.frase_fechamento(out),
            'arquivos': {k: str(v) if v else None for k, v in out.get('arquivos', {}).items()}}


# ---- fechar e e-mail -----------------------------------------------------------------------------
def fechar(base: pathlib.Path, bruto: dict | None, ano: int, mm: int, hoje: dt.date, senha: bool = True,
           pdf: bool = True, motivo: str | None = None) -> dict:
    """Grava o fechamento do mes e gera em saida/ o relatorio mensal (senha: 4 primeiros digitos do CPF) e o DARF
    (senha: 5 primeiros), como a IRTrade faz. `motivo` diz por que um mes ja fechado foi refeito (vai no e-mail
    CORRIGIDO); sem ele, o e-mail diz que chegou nota ou lancamento novo."""
    if hoje <= mes.fim_do_mes(ano, mm):
        raise SystemExit(f'{mm:02d}/{ano} ainda nao acabou: use "apurar" para ver a parcial')
    out = mes.fecha_mes(base, ano, mm, bruto, hoje, gravar=True)
    arqs = {'relatorio': None, 'darf': None}
    if pdf:
        doc = _documento(base, bruto)
        rel_nome, darf_nome = nomes(ano, mm)
        arqs['relatorio'] = base / 'saida' / rel_nome
        _guarda(arqs['relatorio'])
        relatorio.pdf_relatorio(out['dados'], arqs['relatorio'], doc[:4] if senha else None)
        if out['darf']:
            arqs['darf'] = base / 'saida' / darf_nome
            _guarda(arqs['darf'])
            darf.pdf_darf(out['darf'], arqs['darf'], doc[:5] if senha else None)
    out['arquivos'] = arqs
    reg = _reg(base)
    comp = f'{ano}-{mm:02d}'
    ant = reg['fechamentos'].get(comp, {})
    reg['fechamentos'][comp] = {'em': _agora(), 'darf': out['apuracao']['darf'], 'pdf': pdf,
                                'versao': ant.get('versao', 0) + 1, 'darf_antes': ant.get('darf'), 'motivo': motivo}
    _grava_reg(base, reg)
    return out


def _grava_email(base: pathlib.Path, msg: dict) -> pathlib.Path:
    """Grava o e-mail em saida/email/: o .json completo (para conferir o envio) e o .txt que a sessao le para chamar
    o send_message (linhas curtas; o anexo em base64 vai em linhas de 1000 caracteres, para juntar sem quebra)."""
    pasta = base / 'saida' / 'email'
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / f"{msg['chave']}.json").write_text(json.dumps(msg, ensure_ascii=False, indent=1))
    partes = [f"PARA: {', '.join(msg['to'])}", f"ASSUNTO: {msg['subject']}", '--- body ---', msg['body'],
              '--- htmlBody ---', msg['htmlBody'].replace('><', '>\n<')]
    for i, a in enumerate(msg['attachments'], 1):
        b64 = a['content']
        linhas = [b64[k:k + 1000] for k in range(0, len(b64), 1000)]
        partes += [f"--- anexo {i}: filename={a['filename']} mimeType={a['mimeType']} ({len(b64)} caracteres em "
                   f"{len(linhas)} linhas: junte as linhas sem quebra no campo content) ---"] + linhas
    partes.append('--- fim ---')
    arq = pasta / f"{msg['chave']}.txt"
    arq.write_text('\n'.join(partes) + '\n')
    return arq


def montar_email(base: pathlib.Path, bruto: dict | None, ano: int, mm: int, hoje: dt.date) -> pathlib.Path:
    est = base / 'estado' / f'{ano}-{mm:02d}.json'
    if not est.exists():
        raise SystemExit(f'{mm:02d}/{ano} ainda nao foi fechado: rode "fechar {ano}-{mm:02d}"')
    out = mes.fecha_mes(base, ano, mm, bruto, hoje, gravar=False)
    gravado = json.loads(est.read_text())['resumo']['darf']
    if abs(out['apuracao']['darf'] - gravado) > 0.005:
        raise SystemExit(f"o DARF de {mm:02d}/{ano} mudou (R$ {br(gravado)} -> R$ {br(out['apuracao']['darf'])}): "
                         'rode "fechar" de novo antes do e-mail')
    darf_pdf = base / 'saida' / nomes(ano, mm)[1]
    if out['darf'] and not darf_pdf.exists():
        raise SystemExit(f'falta o DARF em PDF ({darf_pdf.name}): rode "fechar {ano}-{mm:02d}"')
    msg = gmail.email_fechamento(out, darf_pdf if out['darf'] else None, _titular(base)['email'], str(base / 'saida'))
    f = _reg(base)['fechamentos'].get(f'{ano}-{mm:02d}', {})
    if f.get('versao', 1) > 1:
        msg['chave'] += f"-v{f['versao']}"
        msg['subject'] = 'CORRIGIDO: ' + msg['subject']
        aviso = (f"Este e-mail substitui o anterior: o fechamento foi refeito porque "
                 f"{f.get('motivo') or 'chegou nota ou lançamento novo'}. DARF antes: R$ {br(f.get('darf_antes') or 0)}.")
        msg['body'] = aviso + '\n\n' + msg['body']
        msg['htmlBody'] = f'<p style="color:#b42318;font-weight:600">{aviso}</p>' + msg['htmlBody']
    return _grava_email(base, msg)


def enviado(base: pathlib.Path, arq_json: pathlib.Path, raw: pathlib.Path | None = None,
            msg_id: str | None = None) -> tuple[bool | None, list]:
    """Registra o envio; com o RAW da mensagem enviada, confere se cada anexo chegou identico ao arquivo."""
    msg = json.loads(pathlib.Path(arq_json).read_text())
    ok, faltam = None, []
    if raw:
        recebidos = {hashlib.sha256(p.get_payload(decode=True) or b'').hexdigest()
                     for p in gmail.mensagem_raw(raw).iter_attachments()}
        faltam = [a['filename'] for a in msg['attachments'] if a['sha256'] not in recebidos]
        ok = not faltam
    reg = _reg(base)
    reg['emails'][msg['chave']] = {'em': _agora(), 'assunto': msg['subject'], 'anexo_conferido': ok,
                                   **({'id': msg_id} if msg_id else {})}
    _grava_reg(base, reg)
    return ok, faltam


# ---- rotina diaria -------------------------------------------------------------------------------
def _de_bolsa(t: dict) -> str | None:
    """Rotulo do lancamento do Open Finance que interessa ao contador (None se nao interessa)."""
    d = t['descricao']
    if mes.LIQUIDACOES.search(d):
        return 'liquidação de bolsa'
    if d.startswith('IR BOVESPA'):
        return 'IR retido em opção'
    for padrao, linha in mes.OF_REGRAS:
        if re.search(padrao, d):
            return linha.lower()
    if mes.PAGAMENTO_DARF.search(d):
        return 'pagamento de tributo'
    return None


def _chave_mov(t: dict) -> str:
    return f"{t['data']:%Y-%m-%d}|{t['valor']:.2f}|{t['descricao']}"


def _chave_alerta(a: str) -> str:
    return re.sub(r'\s*\((faltam \d+ dias?|hoje|amanhã)\)', '', a)[:100]


def _quando(dias: int) -> str:
    return 'hoje' if dias == 0 else 'amanhã' if dias == 1 else f'faltam {dias} dias'


def _darfs(base: pathlib.Path, of: list, reg: dict, hoje: dt.date) -> tuple[list, list, list]:
    """Situacao de cada DARF (os da IRTrade e os fechados aqui): itens, alertas e lembretes a mandar."""
    hist = json.loads((base / 'historico.json').read_text()) if (base / 'historico.json').exists() else {}
    lista = [(d['periodo'], d['valor'], d['vencimento'], 'IRTrade') for d in hist.get('darfs', [])]
    lista += [(f"{e['mes']:02d}/{e['ano']}", e['resumo']['darf'], e['resumo']['vencimento'], 'agente')
              for e in mes.estados(base) if e['resumo'].get('darf')]
    itens, alertas, lembretes = [], [], []
    for periodo, valor, venc_txt, fonte in lista:
        mm, aa = (int(x) for x in periodo.split('/'))
        comp = f'{aa}-{mm:02d}'
        venc = dt.datetime.strptime(venc_txt, '%d/%m/%Y').date()
        pago = reg['pagos'].get(comp)
        if not pago:
            t = mes.pagamento_darf(of, mes.fim_do_mes(aa, mm), valor) if of else None
            pago = {'data': t['data'].isoformat(), 'fonte': 'Open Finance', 'valor': -t['valor']} if t else None
        dias = (venc - hoje).days
        itens.append({'periodo': periodo, 'valor': valor, 'vencimento': venc_txt, 'dias': dias, 'pago': pago,
                      'fonte': fonte})
        if pago:
            if not reg['avisados'].get(f'pago-{comp}'):
                quando = f"em {dt.date.fromisoformat(pago['data']):%d/%m/%Y}" if pago.get('data') else 'sem a data'
                alertas.append(f"DARF de {periodo} (R$ {br(valor)}) pago {quando} ({pago['fonte']}).")
                reg['avisados'][f'pago-{comp}'] = _agora()
            continue
        if dias >= 0:
            alertas.append(f'DARF de {periodo}: R$ {br(valor)}, código {apuracao.CODIGO_DARF}, vence em {venc_txt} '
                           f'({_quando(dias)}); o pagamento ainda não apareceu na conta.')
        else:
            alertas.append(f'DARF de {periodo} (R$ {br(valor)}, venceu em {venc_txt}): não achei o pagamento na conta '
                           'do Safra pelo Open Finance. Se pagou por outro banco, avise para eu registrar; se não pagou, '
                           'ainda dá para pagar com multa e juros (Lei 9.430/1996, art. 61).')
        faixa = ('dia' if dias == 0 else 'vespera' if dias == 1 else 'semana' if 1 < dias <= 5 else
                 'vencido' if dias < 0 else None)
        if faixa and fonte == 'agente':
            lembretes.append({'periodo': periodo, 'valor': valor, 'vencimento': venc_txt, 'faixa': faixa})
    return itens, alertas, lembretes


def diario(base: pathlib.Path, bruto: dict | None, hoje: dt.date, pdf: bool = True) -> dict:
    """Rotina de todo dia: fecha o mes que acabou (quando o Open Finance ja leu o ultimo dia util dele), refaz o ultimo
    fechamento se chegou nota nova antes do vencimento do DARF, apura o mes em curso, acompanha os DARFs, lista os
    lancamentos novos do Open Finance e monta os e-mails pendentes (fechamento e lembrete de pagamento)."""
    base = pathlib.Path(base)
    reg = _reg(base)
    primeira = 'vistos' not in reg
    of = mes.transacoes_of(bruto) if bruto else []
    lido = dt.datetime.fromisoformat(bruto['lido_em']) if bruto and bruto.get('lido_em') else None
    res = {'hoje': hoje.isoformat(), 'open_finance_lido_em': lido.isoformat(timespec='minutes') if lido else None,
           'fechados': [], 'refeitos': [], 'parcial': None, 'darfs': [], 'movimentos': [], 'alertas': [], 'novos': [],
           'emails': []}
    alertas: list[str] = []
    if not bruto:
        alertas.append(f'Sem o extrato do Open Finance ({OPEN_FINANCE}): nada de proventos, aluguel nem conciliação.')
    alertas += mes.saude_of(bruto, hoje)
    if pdf:         # 0. eventos societarios da B3 (rede); sem pdf e conferencia, e o fechamento usa o que esta gravado
        lidos, al = atualiza_eventos(base, bruto, hoje)
        alertas += al
        res['eventos'] = {'lido_em': lidos['lido_em'], 'n': len(lidos['eventos'])} if lidos else None

    def sem_darf(lista):   # os alertas de DARF saem de _darfs(), um por DARF
        return [a for a in lista if not a.startswith('DARF de ')]

    # 1. meses que acabaram, em ordem
    for ano, mm in meses_abertos(base, hoje):
        ult = apuracao.ultimo_dia_util(ano, mm)
        pronto = lido is not None and lido.date() > ult
        if not pronto and _uteis_entre(mes.fim_do_mes(ano, mm), hoje) < ESPERA_OF:
            alertas.append(f'Fechamento de {mm:02d}/{ano} esperando o Open Finance ler o último dia útil do mês '
                           f'({ult:%d/%m})' + (f'; última leitura em {lido:%d/%m às %Hh%M}.' if lido else '.'))
            break
        out = fechar(base, bruto, ano, mm, hoje, pdf=pdf)
        if not pronto:
            alertas.append(f'{mm:02d}/{ano} fechado sem o Open Finance do fim do mês: proventos e aluguel dos últimos '
                           'dias podem faltar (o fechamento é refeito se mudar o DARF).')
        res['fechados'].append(_resumo(out))
        alertas += sem_darf(out['dados']['situacao']['alertas'])
        reg = _reg(base)

    # 2. ultimo fechamento refeito se o DARF ou o prejuizo mudou antes do vencimento
    feitos = sorted(a.name[:7] for a in (base / 'estado').glob('*.json') if re.fullmatch(r'\d{4}-\d{2}\.json', a.name))
    if feitos and not res['fechados']:
        ano, mm = int(feitos[-1][:4]), int(feitos[-1][5:7])
        if hoje <= apuracao.vencimento_darf(ano, mm):
            est = json.loads((base / 'estado' / f'{feitos[-1]}.json').read_text())
            novo = mes.fecha_mes(base, ano, mm, bruto, hoje, gravar=False)
            prej = {k: float(v) for k, v in novo['apuracao']['saldo'].prejuizos.items()}
            if abs(novo['apuracao']['darf'] - est['resumo']['darf']) > 0.005 or \
                    any(abs(prej[k] - est['saldo']['prejuizos'].get(k, 0.0)) > 0.005 for k in prej):
                out = fechar(base, bruto, ano, mm, hoje, pdf=pdf)
                res['refeitos'].append({**_resumo(out), 'darf_antes': est['resumo']['darf']})
                reg = _reg(base)

    # 3. mes em curso
    ini = dt.date(hoje.year, hoje.month, 1)
    ant = ini - dt.timedelta(1)
    partida = json.loads((base / 'partida.json').read_text()) if (base / 'partida.json').exists() else {}
    if (base / 'estado' / f'{ant:%Y-%m}.json').exists() or partida.get('data') == ant.isoformat():
        p = mes.fecha_mes(base, hoje.year, hoje.month, bruto, hoje, gravar=True)
        res['parcial'] = _resumo(p)
        alertas += sem_darf(p['dados']['situacao']['alertas'])

    # 4. DARFs
    res['darfs'], al, lembretes = _darfs(base, of, reg, hoje)
    alertas = al + alertas

    # 5. lancamentos novos do Open Finance que interessam ao contador (o banco pode lancar com data de dias atras;
    # o registro guarda a janela de JANELA_OF dias, e so ela e comparada)
    vistos = set(reg.get('vistos', []))
    rel = [t for t in of if _de_bolsa(t) and t['data'] >= hoje - dt.timedelta(JANELA_OF)]
    for t in sorted(rel, key=lambda t: (t['data'], t['descricao'])):
        if _chave_mov(t) not in vistos and (not primeira or t['data'] >= hoje - dt.timedelta(4)):
            res['movimentos'].append({'data': t['data'].isoformat(), 'valor': t['valor'], 'descricao': t['descricao'],
                                      'tipo': _de_bolsa(t)})
    reg['vistos'] = sorted(_chave_mov(t) for t in rel)

    # 6. alertas novos (os que nao estavam na rodada anterior), com a conferencia dos meses fechados x IRTrade
    alertas += mes.confere_irtrade(base)
    unicos = list(dict.fromkeys(alertas))
    antes = set(reg.get('alertas', []))
    res['alertas'] = unicos
    res['novos'] = [a for a in unicos if _chave_alerta(a) not in antes]
    reg['alertas'] = [_chave_alerta(a) for a in unicos]

    # 7. e-mails pendentes: fechamento (com o DARF anexo) e lembrete de pagamento
    if pdf:
        for comp, f in sorted(reg['fechamentos'].items()):
            chave = f'fechamento-{comp}' + (f"-v{f['versao']}" if f.get('versao', 1) > 1 else '')
            novo_ok = dt.datetime.fromisoformat(f['em']).date() >= hoje - dt.timedelta(EMAIL_ATE_DIAS)
            if chave not in reg['emails'] and f.get('pdf', True) and novo_ok:
                arq = montar_email(base, bruto, int(comp[:4]), int(comp[5:]), hoje)
                res['emails'].append({'chave': arq.stem, 'arquivo': str(arq), 'motivo': 'fechamento do mês'})
        tit = _titular(base)
        for lb in lembretes:
            msg = gmail.email_lembrete(lb, hoje, tit['email'])
            if msg['chave'] not in reg['emails']:
                arq = _grava_email(base, msg)
                res['emails'].append({'chave': msg['chave'], 'arquivo': str(arq), 'motivo': 'lembrete de pagamento'})
    reg['ultima'] = _agora()
    _grava_reg(base, reg)
    if pdf:      # o painel (saida/painel.html) acompanha a rotina; falha nele nao derruba a rotina
        try:
            from . import painel
            res['painel'] = str(painel.gera(base, bruto, hoje))
        except Exception as x:      # noqa: BLE001
            res['painel_erro'] = f'{type(x).__name__}: {x}'
    return res


# ---- texto para a sessao -------------------------------------------------------------------------
def _linhas_alerta(itens: list[str]) -> list[str]:
    return [f'  - {a}' for a in itens]


def texto_apuracao(out: dict) -> str:
    d, r = out['dados'], out['apuracao']
    estado = f"parcial até {d['data_posicao']}" if d['parcial'] else 'mês fechado'
    L = [f"APURAÇÃO {d['competencia']} ({estado}) | {d['titular']['nome']} | {d['corretora']}",
         'Em uma frase: ' + gmail.frase_fechamento(out), '',
         'OPERAÇÕES DO MÊS (resultado | prejuízo abatido | prejuízo que sobra | base | imposto)']
    for q in d['operacoes']['quadro']:
        L.append(f"  {q['tipo']:10} {br(q['resultado']):>14} {br(q['abatido']):>14} {br(q['prejuizo']):>14} "
                 f"{br(q['base']):>14} {br(q['imposto']):>12}")
    if r['darf']:
        L.append(f"DARF: R$ {br(r['darf'])} (imposto {br(r['imposto_bruto'])} - IR retido {br(r['irrf_usado'])}), "
                 f"código {apuracao.CODIGO_DARF}, vence em {r['vencimento']:%d/%m/%Y}")
    else:
        L.append(f"DARF: nenhum (devido R$ {br(r['devido'])})")
    L += ['', f"POSIÇÃO EM {d['data_posicao']} (investido | valor | lucro ou prejuízo)"]
    for x in d['resumo_posicao']:
        if x['investido'] or x['valor']:
            L.append(f"  {x['mercado']:22} {br(x['investido']):>14} {br(x['valor']):>14} {br(x['lp']):>13}")
    tp = d['total_posicao']
    L.append(f"  {'Total':22} {br(tp['investido']):>14} {br(tp['valor']):>14} {br(tp['lp']):>13}")
    L += ['', 'ALERTAS'] + _linhas_alerta(d['situacao']['alertas'])
    L += ['', 'CONFERÊNCIA'] + _linhas_alerta(d['situacao']['conferencia'])
    c = out.get('conciliacao')
    if c:
        L += ['', f"CONCILIAÇÃO: {len(c['casadas'])} liquidações casadas com nota; sem nota: "
                  f"{len(c['sem_nota'])}; Open Finance até {c['ultimo_of']:%d/%m/%Y}" if c['ultimo_of'] else '']
    return '\n'.join(L)


def texto_diario(res: dict) -> str:
    hoje = dt.date.fromisoformat(res['hoje'])
    lido = res['open_finance_lido_em']
    cab = f"CONTADOR DE BOLSA, {hoje:%d/%m/%Y}" + (f" (Open Finance lido em {dt.datetime.fromisoformat(lido):%d/%m %Hh%M})"
                                                 if lido else ' (sem Open Finance)')
    prox = min((x for x in res['darfs'] if not x['pago'] and x['dias'] >= 0), key=lambda x: x['dias'], default=None)
    if not (res['fechados'] or res['refeitos'] or res['movimentos'] or res['novos'] or res['emails']):
        return (cab + ': sem novidade' + (f"; próximo DARF {prox['periodo']} R$ {br(prox['valor'])}, vence "
                                          f"{prox['vencimento']} ({_quando(prox['dias'])})" if prox else '') +
                f"; {len(res['alertas'])} alertas já avisados continuam valendo.")
    L = [cab]
    for f in res['refeitos']:       # correcao vem antes de tudo (CLAUDE.md, regra 5)
        L.append(f"CORREÇÃO {f['competencia']}: o fechamento mudou porque chegou nota ou lançamento novo; DARF de "
                 f"R$ {br(f['darf_antes'])} para R$ {br(f['darf'])}. Agora {f['frase']}")
        L += [f'  {k}: {v}' for k, v in f['arquivos'].items() if v]
    for f in res['fechados']:
        L.append(f"FECHADO AGORA {f['competencia']}: {f['frase']}")
        L += [f'  {k}: {v}' for k, v in f['arquivos'].items() if v]
    p = res['parcial']
    if p:
        rs = p['resultados']
        L.append(f"MÊS EM CURSO {p['competencia']}: resultado comum R$ {br(rs['comum'])}, day trade R$ {br(rs['daytrade'])}, "
                 f"FII R$ {br(rs['fii'])}, isento R$ {br(rs['isento'])}; vendas de ações R$ {br(p['vendas_acoes'])}; "
                 f"imposto se o mês fechasse hoje: R$ {br(p['devido'])}.")
    pend = [x for x in res['darfs'] if not x['pago']]
    if pend:
        L.append('DARFs sem pagamento achado: ' + ' | '.join(
            f"{x['periodo']} R$ {br(x['valor'])} " + (f"vence {x['vencimento']} ({_quando(x['dias'])})" if x['dias'] >= 0
                                                       else f"venceu {x['vencimento']}") for x in pend))
    if res['movimentos']:
        L.append(f"MOVIMENTOS NOVOS NO OPEN FINANCE ({len(res['movimentos'])})")
        L += [f"  {dt.date.fromisoformat(m['data']):%d/%m} {m['tipo']}: R$ {br(m['valor'])}" for m in res['movimentos']]
    L.append(f"ALERTAS NOVOS ({len(res['novos'])})")
    L += _linhas_alerta(res['novos'])
    velhos = len(res['alertas']) - len(res['novos'])
    if velhos:
        L.append(f'Mais {velhos} alertas já avisados continuam valendo (a lista inteira: diario --json).')
    if res['emails']:
        L.append(f"E-MAILS A ENVIAR ({len(res['emails'])})")
        L += [f"  - {e['chave']} ({e['motivo']}): {e['arquivo']}" for e in res['emails']]
    return '\n'.join(L)


# ---- main ----------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog='irbolsa', description='Contador de bolsa: apuração, relatório mensal, DARF e '
                                 'rotina diária com o Open Finance e as notas do e-mail.')
    ap.add_argument('--titular', type=pathlib.Path, default=TITULAR, help='pasta do titular')
    ap.add_argument('--of', type=pathlib.Path, default=OPEN_FINANCE, help='bruto.json do Open Finance')
    ap.add_argument('--hoje', type=dt.date.fromisoformat, default=None, help='data da rodada (AAAA-MM-DD)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('apurar', help='apuração do mês na tela, sem gravar (padrão: o mês em curso)')
    s.add_argument('comp', nargs='?', type=_comp)
    s.add_argument('--json', action='store_true')
    s = sub.add_parser('fechar', help='grava o fechamento e gera o relatório e o DARF em PDF em saida/')
    s.add_argument('comp', type=_comp)
    s.add_argument('--sem-senha', action='store_true', help='PDFs sem senha (só para conferência)')
    s.add_argument('--motivo', help='por que o mês já fechado foi refeito (vai no e-mail CORRIGIDO)')
    s = sub.add_parser('diario', help='rotina de todo dia')
    s.add_argument('--json', action='store_true')
    s.add_argument('--sem-pdf', action='store_true')
    s = sub.add_parser('email', help='monta o e-mail do fechamento (arquivo para o send_message do Gmail)')
    s.add_argument('comp', type=_comp)
    s = sub.add_parser('enviado', help='registra o e-mail enviado; com --id (ou --raw) confere o anexo')
    s.add_argument('arquivo', type=pathlib.Path, help='o .json (ou o .txt) do e-mail em saida/email/')
    s.add_argument('--id', dest='msg_id', help='ID da mensagem enviada: o RAW sai do get_message que a sessão já rodou')
    s.add_argument('--raw', type=pathlib.Path, help='RAW da mensagem enviada, salvo do get_message')
    s = sub.add_parser('pago', help='registra DARF pago fora da conta do Safra')
    s.add_argument('comp', type=_comp)
    s.add_argument('data', type=dt.date.fromisoformat, nargs='?', help='sem a data quando ele so diz que pagou')
    s.add_argument('--fonte', default='informado na sessão')
    sub.add_parser('busca', help='consulta do Gmail para as notas novas')
    s = sub.add_parser('novos', help='dos IDs de mensagem do Gmail, os que ainda não foram importados')
    s.add_argument('ids', nargs='+')
    s = sub.add_parser('importar-email', help='tira as notas dos e-mails salvos em RAW')
    s.add_argument('arquivos', nargs='*', type=pathlib.Path, help='sem arquivo, o RAW de cada --id sai da sessão')
    s.add_argument('--id', dest='ids', action='append', default=[], help='ID da mensagem no Gmail (repita)')
    s = sub.add_parser('eventos', help='lê na B3 os eventos societários dos papéis da carteira e lista os que valem')
    s.add_argument('--sem-rede', action='store_true', help='só lista o que já está gravado')
    s = sub.add_parser('vencimento', help='opções lançadas que vencem no mês: DARF e dinheiro se virarem pó ou exercidas')
    s.add_argument('comp', nargs='?', type=_comp)
    s = sub.add_parser('painel', help='painel no estilo da IRTrade: grava saida/painel.html (ou serve, com o simulador)')
    s.add_argument('--servir', action='store_true', help='serve em http://127.0.0.1:PORTA, só neste Mac')
    s.add_argument('--porta', type=int, default=5059)
    s.add_argument('--abrir', action='store_true', help='abre no navegador')
    a = ap.parse_args(argv)

    base, hoje = a.titular.expanduser(), a.hoje or dt.date.today()
    try:
        if a.cmd == 'importar-email' and not a.arquivos:
            a.arquivos = [gmail.raw_da_sessao(i, base / 'entrada' / f'{i}.json') for i in a.ids]
        if a.cmd == 'enviado' and a.msg_id and not a.raw:
            a.raw = gmail.raw_da_sessao(a.msg_id, base / 'entrada' / f'{a.msg_id}.json')
    except FileNotFoundError as e:
        print('ERRO:', e)
        return 1
    if a.cmd == 'importar-email' and not a.arquivos:
        ap.error('importar-email: passe os arquivos do RAW ou --id')
    if a.cmd in ('busca', 'novos', 'importar-email'):
        if a.cmd == 'busca':
            print(gmail.busca(base, hoje))
        elif a.cmd == 'novos':
            print('\n'.join(gmail.novos(base, a.ids)) or '(nenhum novo)')
        else:
            r = gmail.importar(a.arquivos, base, a.ids)
            print(f"notas novas: {len(r['notas'])} {r['notas']} | aluguel novo: {len(r['aluguel'])} | "
                  f"repetidos: {r['repetidos']} | ignorados: {r['ignorados']}")
            for x in r['avisos']:
                print('AVISO:', x)
        return 0
    if a.cmd == 'pago':
        reg = _reg(base)
        reg['pagos'][f'{a.comp[0]}-{a.comp[1]:02d}'] = {'data': a.data.isoformat() if a.data else None,
                                                        'fonte': a.fonte}
        _grava_reg(base, reg)
        print(f'DARF de {a.comp[1]:02d}/{a.comp[0]} registrado como pago ' +
              (f'em {a.data:%d/%m/%Y}.' if a.data else '(sem a data).'))
        return 0
    if a.cmd == 'enviado':
        arq = a.arquivo.with_suffix('.json')
        ok, faltam = enviado(base, arq, a.raw, a.msg_id)
        print(f'registrado: {arq.stem}' + ('' if ok is None else ' | anexo conferido' if ok else
                                           f' | ANEXO DIFERENTE do arquivo: {faltam}'))
        return 2 if ok is False else 0
    if a.cmd == 'painel':
        from . import painel
        if a.servir:      # o servidor rele o Open Finance a cada atualizacao da pagina
            painel.servir(base, a.of.expanduser(), a.porta, a.hoje, a.abrir)
        else:
            arq = painel.gera(base, _bruto(a.of), hoje)
            print(f'painel: {arq}')
            if a.abrir:
                webbrowser.open(arq.as_uri())
        return 0
    bruto = _bruto(a.of)
    if a.cmd == 'eventos':
        lidos, al = (None, []) if a.sem_rede else atualiza_eventos(base, bruto, hoje)
        print(texto_eventos(base, lidos))
        for x in al:
            print('AVISO:', x)
        return 0
    if a.cmd == 'vencimento':
        ano, mm = a.comp or (hoje.year, hoje.month)
        out = mes.fecha_mes(base, ano, mm, bruto, hoje, gravar=False)
        print(texto_vencimento(out['vencimento'], f'{mm:02d}/{ano}'))
        return 0
    if a.cmd == 'apurar':
        ano, mm = a.comp or (hoje.year, hoje.month)
        out = mes.fecha_mes(base, ano, mm, bruto, hoje, gravar=False)
        print(json.dumps(_resumo(out), ensure_ascii=False, indent=1) if a.json else texto_apuracao(out))
    elif a.cmd == 'fechar':
        out = fechar(base, bruto, *a.comp, hoje, senha=not a.sem_senha, motivo=a.motivo)
        print(texto_apuracao(out))
        print('\nARQUIVOS')
        print('\n'.join(f'  {k}: {v}' for k, v in out['arquivos'].items() if v))
    elif a.cmd == 'diario':
        res = diario(base, bruto, hoje, pdf=not a.sem_pdf)
        print(json.dumps(res, ensure_ascii=False, indent=1, default=str) if a.json else texto_diario(res))
    elif a.cmd == 'email':
        print(montar_email(base, bruto, *a.comp, hoje))
    return 0
