"""Leitor das notas de corretagem da B3 no padrao SINACOR (as do Safra).

Um PDF pode trazer mais de uma nota (acoes e opcoes saem em notas separadas) e uma nota pode
ocupar mais de uma folha. O leitor junta as folhas pelo numero da nota, devolve os negocios na
ordem em que aparecem e o resumo financeiro, que fica na ultima folha de cada nota. Toda nota
e conferida: soma dos negocios contra o "Valor Liquido das operacoes" e liquido contra
valor - taxas - IRRF. Nota que nao fecha vai para `Nota.erros`.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import re
from dataclasses import dataclass, field

import pypdf

from . import ativos

RE_NEGOCIO = re.compile(
    r'^(?:B3|1-BOVESPA|BOVESPA)\s+RV\s+LISTADO\s+(?P<cv>[CV])\s+'
    r'(?P<merc>VISTA|FRACIONARIO|OPCAO DE COMPRA|OPCAO DE VENDA|EXERC OPC COMPRA|EXERC OPC VENDA|TERMO|LEILAO)\s*'
    r'(?P<venc>\d\d/\d\d)?\s+(?P<espec>.+?)\s+(?P<qtd>\d{1,3}(?:\.\d{3})*)\s+'
    r'(?P<preco>\d{1,3}(?:\.\d{3})*,\d{2,8})\s+(?P<valor>\d{1,3}(?:\.\d{3})*,\d{2})\s+(?P<dc>[DC])\s*$')

# custos da nota (chave, rotulo); "Clearing" com valor e a corretagem, o titulo da secao nao tem valor
TAXAS = [
    ('liquidacao', r'Taxa de liquidação'), ('registro', r'Taxa de registro'),
    ('termo_opcoes', r'Taxa de termo/opções'), ('ana', r'Taxa A\.N\.A\.'), ('emolumentos', r'Emolumentos'),
    ('transferencia', r'Taxa de transferência de Ativos'), ('corretagem', r'Clearing'),
    ('execucao', r'Execução(?! casa)'), ('execucao_casa', r'Execução casa'), ('iss', r'ISS[^\n\d]*'),
    ('pis_cofins', r'Pis Cofins'), ('outras', r'Outras'),
]
# a IRTrade deixa estes custos fora do custo das operacoes (conferido nas notas de setembro de 2026);
# a lei manda descontar todo custo necessario a operacao (IN 1.585, art. 56, par. 3), entao o padrao e incluir
IRTRADE_EXCLUI = ('iss', 'pis_cofins', 'transferencia')
VALOR = r'(-?\d{1,3}(?:\.\d{3})*,\d{2})'


def num(s: str) -> float:
    return float(s.replace('.', '').replace(',', '.'))


def data_br(s: str) -> dt.date:
    return dt.datetime.strptime(s, '%d/%m/%Y').date()


@dataclass
class Negocio:
    pregao: dt.date
    nota: str
    ordem: int
    cv: str
    mercado: str
    vencimento: str | None
    especificacao: str
    qtd: int
    preco: float
    valor: float
    ticker: str | None
    ativo: str
    classe: str
    strike: float | None = None
    tipo_opcao: str | None = None
    subjacente: str | None = None
    exercicio: bool = False
    taxas: float = 0.0          # custos da nota rateados pelo valor (preenchido em `rateia`)

    @property
    def liquido(self) -> float:
        """Venda: valor menos custos; compra: valor mais custos."""
        return self.valor - self.taxas if self.cv == 'V' else self.valor + self.taxas


@dataclass
class Nota:
    numero: str
    pregao: dt.date
    arquivo: str
    negocios: list = field(default_factory=list)
    resumo: dict = field(default_factory=dict)
    taxas: dict = field(default_factory=dict)
    irrf: float = 0.0
    irrf_base: float = 0.0
    liquidacao: dt.date | None = None
    liquido: float = 0.0          # credito positivo, debito negativo
    erros: list = field(default_factory=list)

    def custos(self, excluir: tuple = ()) -> float:
        return sum(v for k, v in self.taxas.items() if k not in excluir)

    def rateia(self, excluir: tuple = ()) -> None:
        """IN RFB 1.585/2015, art. 56, par. 4: custos do dia rateados pelo valor financeiro de cada operacao."""
        total = sum(n.valor for n in self.negocios)
        c = self.custos(excluir)
        for n in self.negocios:
            n.taxas = c * n.valor / total if total else 0.0


def _resumo(t: str, rotulo: str) -> float | None:
    m = re.search(r'^' + rotulo + r'\s*' + VALOR, t, re.M)
    return num(m.group(1)) if m else None


def ler_pdf(arq: pathlib.Path, extra: dict | None = None) -> list[Nota]:
    r = pypdf.PdfReader(str(arq))
    folhas: dict[str, list[str]] = {}
    for pg in r.pages:
        t = pg.extract_text() or ''
        m = re.search(r'Nr Nota\s*\n\s*(\d+)', t)
        if m:
            folhas.setdefault(m.group(1), []).append(t)
    notas = []
    for nr, textos in folhas.items():
        pregao = data_br(re.search(r'Data pregão\s*\n\s*(\d\d/\d\d/\d{4})', textos[0]).group(1))
        nota = Nota(nr, pregao, pathlib.Path(arq).name)
        for t in textos:
            for linha in t.split('\n'):
                m = RE_NEGOCIO.match(re.sub(r'\s+', ' ', linha.strip()))
                if not m:
                    continue
                info = ativos.identifica(m['merc'], m['espec'], extra)
                nota.negocios.append(Negocio(
                    pregao, nr, len(nota.negocios), m['cv'], m['merc'], m['venc'], m['espec'],
                    int(m['qtd'].replace('.', '')), num(m['preco']), num(m['valor']), **info))
                if not info['ticker']:
                    nota.erros.append(f"papel sem ticker: '{m['espec']}' (acrescente no tickers.json)")
        final = next((t for t in reversed(textos) if re.search(r'Líquido para \d\d/\d\d/\d{4}\s+' + VALOR, t)), None)
        if final is None:
            nota.erros.append('resumo financeiro nao encontrado')
            notas.append(nota)
            continue
        for chave, rot in (('vendas_vista', 'Vendas à vista'), ('compras_vista', 'Compras à vista'),
                           ('opcoes_compras', 'Opções - Compras'), ('opcoes_vendas', 'Opções - vendas'),
                           ('valor_operacoes', 'Valor das operações')):
            nota.resumo[chave] = _resumo(final, rot) or 0.0
        m = re.search(r'Valor Líquido das operações\s*' + VALOR + r'\|\s*([DC])', final)
        nota.resumo['valor_liquido'] = (num(m.group(1)) * (1 if m.group(2) == 'C' else -1)) if m else 0.0
        for chave, rot in TAXAS:
            v = _resumo(final, rot)
            if v:
                nota.taxas[chave] = v
        m = re.search(r'I\.R\.R\.F s/ operações base\s*' + VALOR + r'\s+' + VALOR, final)
        if m:
            nota.irrf_base, nota.irrf = num(m.group(1)), num(m.group(2))
        m = re.search(r'Líquido para (\d\d/\d\d/\d{4})\s+' + VALOR + r'\|\s*([DC])', final)
        nota.liquidacao = data_br(m.group(1))
        nota.liquido = num(m.group(2)) * (1 if m.group(3) == 'C' else -1)
        soma = sum(n.valor if n.cv == 'V' else -n.valor for n in nota.negocios)
        if abs(soma - nota.resumo['valor_liquido']) > 0.005:
            nota.erros.append(f'negocios somam {soma:.2f} e a nota diz {nota.resumo["valor_liquido"]:.2f}')
        esperado = nota.resumo['valor_liquido'] - nota.custos() - nota.irrf
        if abs(esperado - nota.liquido) > 0.015:
            nota.erros.append(f'liquido {nota.liquido:.2f} difere de valor - custos - IRRF ({esperado:.2f})')
        notas.append(nota)
    return notas


def ler_pasta(pasta: pathlib.Path, extra: dict | None = None) -> list[Nota]:
    """Todas as notas da pasta, sem repetir numero de nota, em ordem de pregao."""
    vistas, notas = set(), []
    for arq in sorted(pathlib.Path(pasta).glob('*.pdf')):
        for n in ler_pdf(arq, extra):
            if n.numero not in vistas:
                vistas.add(n.numero)
                notas.append(n)
    return sorted(notas, key=lambda n: (n.pregao, n.numero))
