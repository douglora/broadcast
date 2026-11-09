"""Leitor das notas de emprestimo de acoes (BTC) do Safra: remuneracao bruta, IRRF e corretagem de cada
contrato liquidado. Le so os campos da operacao; nome, endereco e documento do cliente ficam de fora.

No extrato do Open Finance o mesmo contrato aparece em duas linhas: "TAXA REEMBOLSO BTB DOADOR" (bruto
menos IRRF) e "CORRETAGEM BTB". A nota da a remuneracao bruta e o IRRF separados, como o relatorio mostra.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import re

import pypdf

from .notas import data_br, num

CAMPOS = {
    'lado': r'Lado:\s*\n\s*(\w+)', 'abertura': r'Abertura:\s*\n\s*(\d\d/\d\d/\d{4})',
    'vencimento': r'Vencimento:\s*\n\s*(\d\d/\d\d/\d{4})', 'papel': r'Papel:\s*\n\s*([A-Z0-9]{5,6})',
    'qtd': r'Qtd\. Liquidação:\s*\n\s*([\d.]+)', 'taxa': r'Taxa:\s*\n\s*([\d,]+)%',
}
RESUMO = {'bruto': 'Valor Bruto', 'emolumentos': 'Emolumentos', 'irrf': r'I\.R\.R\.F', 'execucao': 'Execução',
          'clearing': 'Clearing', 'liquido': 'Valor Líquido'}
VALOR = r'(-?\d{1,3}(?:\.\d{3})*,\d{2})'


def ler_pdf(arq: pathlib.Path) -> list[dict]:
    """Um dict por contrato da nota (a nota pode ter mais de uma pagina, uma por contrato)."""
    out = []
    for pg in pypdf.PdfReader(str(arq)).pages:
        t = pg.extract_text() or ''
        if 'NOTA DE EMPRÉSTIMO' not in t or 'Resumo Financeiro' not in t:
            continue
        cab = re.search(r'Página\s*\n\s*(\d\d/\d\d/\d{4})[^\n]*\n\s*(\d\d/\d\d/\d{4})\s*\n\s*(\d+)', t)
        c = {'emissao': data_br(cab.group(1)), 'liquidacao': data_br(cab.group(2)), 'nota': cab.group(3)} if cab else {}
        for k, rx in CAMPOS.items():
            m = re.search(rx, t)
            c[k] = m.group(1) if m else None
        for k in ('abertura', 'vencimento'):
            c[k] = data_br(c[k]) if c[k] else None
        c['qtd'] = int(c['qtd'].replace('.', '')) if c['qtd'] else 0
        resumo = t.split('Resumo Financeiro', 1)[1]
        for k, rot in RESUMO.items():
            m = re.search(rot + r'\s*\n?\s*' + VALOR, resumo)
            c[k] = num(m.group(1)) if m else 0.0
        c['arquivo'] = pathlib.Path(arq).name
        out.append(c)
    return out


def ler_pasta(pasta: pathlib.Path) -> list[dict]:
    vistos, out = set(), []
    for arq in sorted(pathlib.Path(pasta).glob('*.pdf')):
        for c in ler_pdf(arq):
            k = (c.get('nota'), c.get('papel'), c.get('abertura'), c.get('qtd'))
            if k not in vistos:
                vistos.add(k)
                out.append(c)
    return sorted(out, key=lambda c: (c.get('liquidacao') or dt.date.min, c.get('papel') or ''))
