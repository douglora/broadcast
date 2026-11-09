"""Notas do Safra que chegam por e-mail e o e-mail do DARF.

Entrada: a sessao busca no Gmail (conector) com a consulta de busca(), salva cada mensagem nova em formato RAW num
arquivo e importar() tira os anexos para a pasta do titular. Nota de corretagem vem num zip (NC_<conta>_DD-MM-AAAA.zip,
com o PDF dentro) e nota de aluguel em PDF solto (NotaAluguel<conta>.pdf), as duas de safracorretora@safra.com.br.
O registro importados.json guarda o sha1 de cada PDF e o ID das mensagens ja lidas: nada entra duas vezes.
raw_da_sessao() acha esse RAW pelo ID da mensagem no que a sessao ja recebeu (tool-results/ ou o registro .jsonl da
conversa), sem a sessao copiar o base64 com o Write.

Saida: email_fechamento() e email_lembrete() montam o e-mail no formato do send_message do conector (to, subject,
body, htmlBody, attachments em base64). O conector so recebe o anexo pelo texto da chamada, por isso o DARF vai no PDF
leve (poucos KB) e o relatorio mensal fica na sessao. anexo_confere() checa, pelo RAW da mensagem enviada, se o anexo
chegou identico ao arquivo.
"""

from __future__ import annotations

import base64
import datetime as dt
import email
import hashlib
import html
import io
import json
import pathlib
import re
import zipfile
from email import policy
from email.utils import parsedate_to_datetime

from .mes import br

REMETENTE = 'safracorretora@safra.com.br'
SESSOES = pathlib.Path.home() / '.claude' / 'projects'  # registro das sessoes do Claude Code
AZUL = '#0f4c81'
MESES_NOME = ('janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro',
              'novembro', 'dezembro')


# ---- entrada: notas que chegam por e-mail ----------------------------------------------------------
def _registro(base: pathlib.Path) -> dict:
    """importados.json; na primeira vez, semeado com os PDFs que ja estao nas pastas."""
    base = pathlib.Path(base)
    arq = base / 'importados.json'
    if arq.exists():
        return json.loads(arq.read_text())
    reg = {'pdfs': {}, 'gmail': []}
    for pasta in ('notas', 'aluguel'):
        for a in sorted((base / pasta).glob('*.pdf')):
            reg['pdfs'][hashlib.sha1(a.read_bytes()).hexdigest()] = f'{pasta}/{a.name}'
    return reg


def ultima_nota(base: pathlib.Path) -> dt.date | None:
    """Data da nota mais nova na pasta (pregao no nome da nota de corretagem, e-mail no nome do aluguel)."""
    base = pathlib.Path(base)
    datas = []
    for a in (base / 'notas').glob('*.pdf'):
        m = re.search(r'(\d{2})-(\d{2})-(\d{4})', a.name)
        if m:
            datas.append(dt.date(int(m[3]), int(m[2]), int(m[1])))
    for a in (base / 'aluguel').glob('*.pdf'):
        m = re.match(r'(\d{4})-(\d{2})-(\d{2})', a.name)
        if m:
            datas.append(dt.date(int(m[1]), int(m[2]), int(m[3])))
    return max(datas, default=None)


def busca(base: pathlib.Path, hoje: dt.date | None = None, folga: int = 3) -> str:
    """Consulta do Gmail para as notas novas: alguns dias antes da nota mais nova que ja esta na pasta."""
    ult = ultima_nota(base)
    desde = ult - dt.timedelta(folga) if ult else (hoje or dt.date.today()) - dt.timedelta(45)
    return f'from:{REMETENTE} has:attachment after:{desde:%Y/%m/%d}'


def novos(base: pathlib.Path, ids: list[str]) -> list[str]:
    """Dos IDs de mensagem que a busca devolveu, os que ainda nao foram importados."""
    feitos = set(_registro(base).get('gmail', []))
    return [i for i in ids if i not in feitos]


def mensagem_raw(arq: pathlib.Path) -> email.message.EmailMessage:
    """Le o arquivo que a sessao salvou do get_message em RAW (JSON com o campo raw, em base64url)."""
    txt = pathlib.Path(arq).read_text()
    try:
        raw = json.loads(txt)['raw']
    except (json.JSONDecodeError, KeyError, TypeError):
        m = re.search(r'"raw"\s*:\s*"([A-Za-z0-9_\-=]+)"', txt)
        if not m:
            raise ValueError(f'{arq}: sem o campo raw')
        raw = m.group(1)
    return email.message_from_bytes(base64.urlsafe_b64decode(raw + '=' * (-len(raw) % 4)), policy=policy.default)


def _get_message(texto: str, msg_id: str) -> dict | None:
    """O JSON do get_message em RAW, se `texto` for a resposta dele para `msg_id`."""
    texto = texto.strip()
    if not texto.startswith('{') or msg_id not in texto[:400]:
        return None
    try:
        d = json.loads(texto)
    except json.JSONDecodeError:
        return None
    return d if isinstance(d, dict) and d.get('id') == msg_id and d.get('raw') else None


def raw_da_sessao(msg_id: str, destino: pathlib.Path, sessoes: pathlib.Path | None = None,
                  horas: float = 12) -> pathlib.Path:
    """Arquivo com o RAW que o get_message devolveu a uma sessao recente, pronto para mensagem_raw().

    Resposta grande o app ja grava em <sessao>/tool-results/; a pequena (o DARF leve, a nota de aluguel) fica so no
    registro da conversa (<projeto>/<sessao>.jsonl) e e copiada para `destino`. Assim a rotina passa so o ID da
    mensagem, sem reescrever dezenas de milhares de caracteres de base64 com o Write (caro e sujeito a erro)."""
    sessoes = pathlib.Path(sessoes or SESSOES)
    limite = dt.datetime.now().timestamp() - horas * 3600

    def recentes(padrao: str) -> list[pathlib.Path]:
        arqs = [p for p in sessoes.glob(padrao) if p.stat().st_mtime >= limite]
        return sorted(arqs, key=lambda p: p.stat().st_mtime, reverse=True)

    for arq in recentes('*/*/tool-results/*get_message*.txt'):
        with open(arq, encoding='utf-8', errors='replace') as f:
            if re.search(rf'"id"\s*:\s*"{re.escape(msg_id)}"', f.read(400)):
                return arq
    for arq in recentes('*/*.jsonl'):
        achou = None
        with open(arq, encoding='utf-8', errors='replace') as f:
            for linha in f:
                if msg_id not in linha or '"raw' not in linha:
                    continue
                try:
                    cont = json.loads(linha)['message']['content']
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
                for c in cont if isinstance(cont, list) else []:
                    if not isinstance(c, dict) or c.get('type') != 'tool_result':
                        continue
                    partes = c.get('content')
                    textos = [partes] if isinstance(partes, str) else [
                        p.get('text', '') for p in partes or [] if isinstance(p, dict) and p.get('type') == 'text']
                    for t in textos:
                        achou = _get_message(t, msg_id) or achou
        if achou:
            destino = pathlib.Path(destino)
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(json.dumps({'id': msg_id, 'raw': achou['raw']}))
            return destino
    raise FileNotFoundError(f'o RAW da mensagem {msg_id} não apareceu nas sessões das últimas {horas:g} h '
                            '(rode antes o get_message com messageFormat RAW)')


def _pdfs_do_anexo(nome: str, dados: bytes) -> list[tuple[str, str, bytes]]:
    nome_min = nome.lower()
    if nome_min.endswith('.zip'):
        z = zipfile.ZipFile(io.BytesIO(dados))
        return [('nota', pathlib.Path(n).name, z.read(n)) for n in z.namelist() if n.lower().endswith('.pdf')]
    if nome_min.startswith('notaaluguel') and nome_min.endswith('.pdf'):
        return [('aluguel', nome, dados)]
    return []


def importar(arquivos: list[pathlib.Path], base: pathlib.Path, ids: list[str] | None = None) -> dict:
    """Anexos das mensagens -> notas/ e aluguel/ do titular; `ids` (do Gmail) entram no registro."""
    base = pathlib.Path(base)
    reg = _registro(base)
    cont = {'notas': [], 'aluguel': [], 'ignorados': [], 'repetidos': 0, 'avisos': []}
    for arq in arquivos:
        m = mensagem_raw(arq)
        if REMETENTE not in str(m.get('from', '')).lower():
            cont['ignorados'].append(f'{pathlib.Path(arq).name}: remetente nao e a Safra Corretora')
            continue
        quando = parsedate_to_datetime(str(m['date']))
        for parte in m.iter_attachments():
            nome = parte.get_filename() or 'sem_nome'
            pdfs = _pdfs_do_anexo(nome, parte.get_payload(decode=True) or b'')
            if not pdfs:
                cont['ignorados'].append(nome)
                continue
            for tipo, nome_pdf, dados in pdfs:
                h = hashlib.sha1(dados).hexdigest()
                if h in reg['pdfs']:
                    cont['repetidos'] += 1
                    continue
                if tipo == 'nota':
                    destino = base / 'notas' / nome_pdf
                    if destino.exists():
                        destino = destino.with_name(f'{destino.stem}_{h[:8]}.pdf')
                        cont['avisos'].append(f'{nome_pdf} chegou de novo com outro conteudo (nota retificada?): '
                                              f'gravada como {destino.name}; o motor usa a primeira, confira')
                else:
                    destino = base / 'aluguel' / f'{quando:%Y-%m-%d_%H%M}_{h[:10]}.pdf'
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_bytes(dados)
                reg['pdfs'][h] = f'{destino.parent.name}/{destino.name}'
                cont['notas' if tipo == 'nota' else 'aluguel'].append(destino.name)
    reg['gmail'] = sorted(set(reg.get('gmail', [])) | set(ids or []))
    (base / 'importados.json').write_text(json.dumps(reg, ensure_ascii=False, indent=1))
    return cont


def anexo_confere(arq_raw: pathlib.Path, arquivo: pathlib.Path) -> bool:
    """O e-mail enviado (RAW salvo pela sessao) tem um anexo identico ao arquivo local?"""
    alvo = hashlib.sha256(pathlib.Path(arquivo).read_bytes()).hexdigest()
    return any(hashlib.sha256(p.get_payload(decode=True) or b'').hexdigest() == alvo
               for p in mensagem_raw(arq_raw).iter_attachments())


# ---- saida: e-mail do fechamento e lembrete de pagamento -------------------------------------------
def _e(x) -> str:
    return html.escape(str(x))


def _rs(x) -> str:
    """R$ 1.234,56; negativo como -R$ 1.234,56, igual ao relatorio."""
    return ('-R$ ' if round(x, 2) < 0 else 'R$ ') + br(abs(x))


def _tabela(cab: list[str] | None, linhas: list[list[str]], direita: tuple = ()) -> str:
    """Tabela de ate 4 colunas, bordas finas, numero alinhado a direita (le bem no celular)."""
    def cel(tag, i, txt, extra=''):
        lado = 'right' if i in direita else 'left'
        return (f'<{tag} style="padding:6px 8px;border-bottom:1px solid #d5dce3;text-align:{lado};'
                f'white-space:nowrap;{extra}">{_e(txt)}</{tag}>')
    topo = ''
    if cab:
        topo = '<tr>' + ''.join(cel('th', i, c, f'background:#eef3f9;color:{AZUL};font-weight:600;')
                                for i, c in enumerate(cab)) + '</tr>'
    corpo = ''.join('<tr>' + ''.join(cel('td', i, c) for i, c in enumerate(lin)) + '</tr>' for lin in linhas)
    return ('<table style="border-collapse:collapse;width:100%;max-width:560px;font-size:14px;margin:6px 0 18px">'
            f'{topo}{corpo}</table>')


def _pagina(titulo: str, frase: str, blocos: list[tuple[str, str]], rodape: str) -> str:
    partes = [f'<h1 style="font-size:20px;color:{AZUL};margin:0 0 12px">{_e(titulo)}</h1>',
              '<p style="font-size:15px;line-height:1.5;margin:0 0 18px"><b>Em uma frase:</b> ' + _e(frase) + '</p>']
    for sub, corpo in blocos:
        partes.append(f'<h2 style="font-size:15px;color:{AZUL};margin:18px 0 4px">{_e(sub)}</h2>{corpo}')
    partes.append(f'<p style="font-size:12px;color:#5b6573;line-height:1.5;margin-top:22px">{rodape}</p>')
    return ('<div style="background:#ffffff;color:#1d2733;font-family:Helvetica,Arial,sans-serif;max-width:600px;'
            'padding:8px">' + ''.join(partes) + '</div>')


def _texto(titulo: str, frase: str, blocos: list[tuple[str, list[str]]], rodape: str) -> str:
    linhas = [titulo, '', 'Em uma frase: ' + frase]
    for sub, itens in blocos:
        linhas += ['', sub.upper()] + [f'  {x}' for x in itens]
    return '\n'.join(linhas + ['', re.sub(r'<[^>]+>', '', rodape)])


def _campos_pagar(darf: dict) -> list[list[str]]:
    return [['02 Período de apuração', darf['periodo_apuracao']], ['03 CPF', 'o seu (está no DARF anexo)'],
            ['04 Código da receita', darf['codigo_receita']], ['05 Número de referência', 'em branco'],
            ['06 Data de vencimento', darf['vencimento']], ['07 Valor do principal', 'R$ ' + br(darf['principal'])],
            ['08 Valor da multa', 'R$ ' + br(darf['multa'])], ['09 Valor dos juros', 'R$ ' + br(darf['juros'])],
            ['10 Valor total', 'R$ ' + br(darf['total'])]]


def _anexo(arq: pathlib.Path) -> dict:
    dados = pathlib.Path(arq).read_bytes()
    return {'filename': pathlib.Path(arq).name, 'mimeType': 'application/pdf',
            'content': base64.b64encode(dados).decode('ascii'), 'sha256': hashlib.sha256(dados).hexdigest()}


SOBRA = {'comum': 'nas operações comuns', 'daytrade': 'de day trade, que só abate lucro de day trade',
         'fii': 'de FII, que só abate lucro de FII'}


def _sobra(r: dict) -> str:
    """O prejuizo que passa para os meses seguintes, por tipo (o de day trade e o de FII so abatem lucro da mesma
    especie: IN 1.585, art. 37 e art. 65, par. 10)."""
    partes = [f"R$ {br(-l['prejuizo'])} {SOBRA[l['tipo']]}" for l in r['linhas'] if l['prejuizo'] < -0.005]
    return '; prejuízo que sobra para os próximos meses: ' + ' e '.join(partes) if partes else ''


def frase_fechamento(out: dict) -> str:
    """A frase do mes: quanto e o DARF e de onde ele vem, ou por que nao ha DARF, sempre com o prejuizo de meses
    anteriores que o mes abateu e o que sobra dele."""
    d, r, darf = out['dados'], out['apuracao'], out['darf']
    mm, aa = (int(x) for x in d['competencia'].split('/'))
    nome = f'{MESES_NOME[mm - 1]}/{aa}'
    base_trib = sum(l['base'] for l in r['linhas'])
    usado = round(sum(l['prejuizo_usado'] for l in r['linhas']), 2)
    pend_ant = round(r['devido'] - (r['imposto_bruto'] - r['irrf_usado']), 2)
    if darf:
        txt = (f"o DARF de {nome} é de R$ {br(darf['total'])} (código {darf['codigo_receita']}) e vence em "
               f"{darf['vencimento']}: lucro tributável de R$ {br(base_trib)} no mês")
        if usado:
            txt += f" (R$ {br(base_trib + usado)} menos R$ {br(usado)} de prejuízo de meses anteriores)"
        txt += f", imposto de R$ {br(r['imposto_bruto'])}"
        if r['irrf_usado']:
            txt += f" menos R$ {br(r['irrf_usado'])} de IR retido na fonte"
        if pend_ant > 0:
            txt += f' mais R$ {br(pend_ant)} de imposto de meses anteriores que ficou abaixo de R$ 10'
        return txt + _sobra(r) + '.'
    if r['devido'] > 0:
        return (f"sem DARF em {nome}: o imposto acumulado é de R$ {br(r['devido'])}, abaixo do mínimo de R$ 10,00, e "
                'passa para o próximo DARF.')
    res = sum(r['resultados'].values())
    txt = f'sem imposto a pagar em {nome}: resultado de R$ {br(res)} no mês'
    if r['resultados'].get('isento', 0) > 0:
        txt += (f", com lucro isento de R$ {br(r['resultados']['isento'])} em ações (vendas de R$ "
                f"{br(r['vendas_acoes'])} no mês, dentro do limite de R$ 20.000,00)")
    if usado:
        txt += f", com R$ {br(usado)} de lucro abatidos do prejuízo de meses anteriores"
    return txt + _sobra(r) + '.'


def email_fechamento(out: dict, darf_pdf: pathlib.Path | None, para: str, pasta_saida: str) -> dict:
    """E-mail do mes fechado: a frase, os campos para pagar sem codigo de barras, o quadro e os alertas; o DARF
    leve vai anexo (com a senha dos 5 primeiros digitos do CPF, como a IRTrade)."""
    d, darf = out['dados'], out['darf']
    mm, aa = (int(x) for x in d['competencia'].split('/'))
    nome = f'{MESES_NOME[mm - 1]}/{aa}'
    frase = frase_fechamento(out)
    frase = frase[0].upper() + frase[1:]
    quadro = [[q['tipo'], _rs(q['resultado']), _rs(q['abatido']), _rs(q['imposto'])]
              for q in d['operacoes']['quadro']]
    pos = [[x['mercado'], _rs(x['investido']), _rs(x['valor']), _rs(x['lp'])]
           for x in d['resumo_posicao'] if x['investido'] or x['valor']]
    tp = d['total_posicao']
    pos.append(['Total', _rs(tp['investido']), _rs(tp['valor']), _rs(tp['lp'])])
    alertas = [a for a in d['situacao']['alertas'] if not a.startswith(f"DARF de {d['competencia']}:")]
    blocos_h, blocos_t = [], []
    if darf:
        campos = _campos_pagar(darf)
        blocos_h.append(('Para pagar no app do banco (DARF sem código de barras)', _tabela(None, campos, (1,))))
        blocos_t.append(('Para pagar no app do banco (DARF sem código de barras)', [f'{a}: {b}' for a, b in campos]))
    cab = ['Operação', 'Resultado do mês', 'Prejuízo abatido', 'Imposto']     # o que sobra vai na frase
    blocos_h.append(('Operações do mês', _tabela(cab, quadro, (1, 2, 3))))
    blocos_t.append(('Operações do mês', [' | '.join(l) for l in quadro]))
    blocos_h.append((f"Posição em {d['data_posicao']}", _tabela(['Mercado', 'Investido', 'Valor', 'Lucro ou prejuízo'],
                                                                 pos, (1, 2, 3))))
    blocos_t.append((f"Posição em {d['data_posicao']}", [' | '.join(l) for l in pos]))
    if alertas:
        blocos_h.append(('Alertas', '<ul style="font-size:14px;line-height:1.5;padding-left:18px;margin:4px 0 18px">' +
                         ''.join(f'<li style="margin-bottom:6px">{_e(a)}</li>' for a in alertas) + '</ul>'))
        blocos_t.append(('Alertas', [f'- {a}' for a in alertas]))
    rodape = ('O relatório mensal completo (posição, operações, extrato, proventos, resumo anual e situação fiscal) '
              f'foi entregue na sessão do Claude e está salvo em {_e(pasta_saida)}. Senha dos PDFs: DARF = 5 primeiros '
              'dígitos do CPF; relatório = 4 primeiros. Apuração feita a partir das notas de corretagem do Safra e do '
              'extrato do Open Finance; confira os valores antes de pagar.')
    titulo = f"DARF de {nome}: R$ {br(darf['total'])}" if darf else f'Fechamento de {nome}: sem DARF a pagar'
    assunto = (f"DARF de {nome}: R$ {br(darf['total'])}, vence em {darf['vencimento']}" if darf
               else f'Fechamento de {nome}: sem DARF a pagar')
    return {'chave': f'fechamento-{aa}-{mm:02d}', 'to': [para], 'subject': assunto,
            'body': _texto(titulo, frase, blocos_t, rodape), 'htmlBody': _pagina(titulo, frase, blocos_h, rodape),
            'attachments': [_anexo(darf_pdf)] if darf and darf_pdf else []}


def email_lembrete(info: dict, hoje: dt.date, para: str) -> dict:
    """Lembrete de DARF ainda nao pago: info = {periodo 'MM/AAAA', valor, vencimento 'DD/MM/AAAA', faixa}."""
    mm, aa = (int(x) for x in info['periodo'].split('/'))
    nome = f'{MESES_NOME[mm - 1]}/{aa}'
    venc = dt.datetime.strptime(info['vencimento'], '%d/%m/%Y').date()
    dias = (venc - hoje).days
    quando = ('hoje' if dias == 0 else 'amanhã' if dias == 1 else f'em {dias} dias' if dias > 0
              else f'há {-dias} dias')
    verbo = 'venceu' if dias < 0 else 'vence'
    assunto = f"Lembrete: DARF de {nome} (R$ {br(info['valor'])}) {verbo} {quando}, {venc:%d/%m}"
    frase = (f"o DARF de {nome}, de R$ {br(info['valor'])}, {verbo} {quando} ({info['vencimento']}) e o pagamento "
             'ainda não apareceu na conta do Safra.')
    if dias < 0:
        frase += ' Pago depois do vencimento, ele tem multa e juros (Lei 9.430/1996, art. 61): o Sicalc da Receita calcula.'
    frase = frase[0].upper() + frase[1:]
    fim = dt.date(aa + mm // 12, mm % 12 + 1, 1) - dt.timedelta(1)
    darf = {'periodo_apuracao': f'{fim:%d/%m/%Y}', 'codigo_receita': '6015', 'vencimento': info['vencimento'],
            'principal': info['valor'], 'multa': 0.0, 'juros': 0.0, 'total': info['valor']}
    campos = _campos_pagar(darf)
    if dias < 0:
        campos[-3:] = [[c[0], 'calcular no Sicalc'] for c in campos[-3:]]
    rodape = ('O DARF em PDF foi no e-mail do fechamento do mês e está na sessão do Claude. Se já pagou por outro '
              'banco, avise na sessão para o lembrete parar.')
    titulo = f'Lembrete: DARF de {nome}'
    return {'chave': f"lembrete-{aa}-{mm:02d}-{info['faixa']}", 'to': [para], 'subject': assunto,
            'body': _texto(titulo, frase, [('Para pagar', [f'{a}: {b}' for a, b in campos])], rodape),
            'htmlBody': _pagina(titulo, frase, [('Para pagar no app do banco (DARF sem código de barras)',
                                                 _tabela(None, campos, (1,)))], rodape),
            'attachments': []}
