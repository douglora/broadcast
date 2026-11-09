"""Apuracao mensal do imposto de renda em bolsa da pessoa fisica, a partir das notas.

Regras (lidas no texto oficial; artigo e data no REGRAS.md da skill contador-bolsa):
- custo medio ponderado (Lei 8.981/1995, art. 72, par. 2; IN RFB 1.585/2015, art. 58);
- custos da nota rateados pelo valor financeiro de cada operacao (IN 1.585, art. 56, par. 4);
- day trade: mesmo dia, mesmo ativo, mesma corretora; o estoque anterior nao entra; casa a
  primeira compra com a primeira venda (art. 65, par. 1 a 3); exercicio + venda no mesmo dia
  nao e day trade (par. 13); 20% e IRRF de 1% (art. 65, caput e par. 11);
- comum 15% (art. 57); FII 20%, prejuizo de FII so compensa FII (art. 37);
- isencao de acoes no mercado a vista ate R$ 20 mil de vendas no mes (art. 59), que nao vale
  para day trade, ETF, BDR nem alienacao por exercicio (par. 2); no mes isento so o lucro e
  isento: o prejuizo das acoes a vista continua compensavel (art. 59, par. 1, e art. 64);
- opcoes: resultado no encerramento da serie; sem encerramento nem exercicio, o premio e ganho
  do lancador e perda do titular na data do vencimento (art. 60, par. 3); no exercicio o premio
  vai para o custo ou para o preco do ativo-objeto (art. 60, II, a a d);
- prejuizo comum compensa comum, day trade so day trade (art. 64);
- IRRF deduz do imposto do mes e o que sobra fica para os meses seguintes (art. 63, par. 8);
- imposto abaixo de R$ 10 nao vira DARF: soma no mes seguinte (Lei 9.430/1996, art. 68);
- eventos societarios no fim do dia com (eventos.py): desdobramento e grupamento mudam so a quantidade, bonificacao
  entra pelo valor capitalizado, restituicao de capital reduz o custo (art. 58, par. 1, 6 e 8).
"""

from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from dataclasses import asdict, dataclass, field

from alocacao.dias import feriados

from . import ativos, eventos

ALIQ = {'comum': 0.15, 'daytrade': 0.20, 'fii': 0.20}
LIMITE_ISENCAO = 20000.0
DARF_MINIMO = 10.0
CODIGO_DARF = '6015'


@dataclass
class Posicao:
    ticker: str
    ativo: str
    classe: str
    qtd: int = 0
    custo: float = 0.0              # comprado: custo total com taxas; vendido: -(premio liquido recebido)
    data_estoque: dt.date | None = None
    vencimento: dt.date | None = None
    strike: float | None = None
    tipo_opcao: str | None = None
    subjacente: str | None = None

    @property
    def pm(self) -> float:
        return abs(self.custo / self.qtd) if self.qtd else 0.0


@dataclass
class Encerramento:
    """Uma linha de "Operacoes finalizadas": a operacao que encerra (liq) contra o estoque."""
    ticker: str
    ativo: str
    classe: str
    grupo: str
    qtd: int
    liq_data: dt.date
    liq_cv: str
    liq_total: float
    est_data: dt.date | None
    est_cv: str
    est_total: float
    resultado: float
    tipo: str                         # comum, daytrade, fii, isento
    mercado: str = 'vista'            # vista, opcao, vencimento, exercicio

    @property
    def liq_preco(self) -> float:
        return self.liq_total / self.qtd if self.qtd else 0.0

    @property
    def est_preco(self) -> float:
        return self.est_total / self.qtd if self.qtd else 0.0


def _br(x: float) -> str:
    return f'{x:,.2f}'.replace(',', '#').replace('.', ',').replace('#', '.')


def grupo_de(classe: str, tipo_opcao: str | None) -> str:
    if classe == 'opcao':
        return 'Opções de Compra' if tipo_opcao == 'call' else 'Opções de Venda'
    return 'Fundos Imobiliários' if classe == 'fii' else 'Mercado à Vista'


class Carteira:
    def __init__(self, posicoes: list[Posicao] | None = None):
        self.pos: dict[str, Posicao] = {p.ticker: p for p in (posicoes or [])}
        self.encerramentos: list[Encerramento] = []
        self.alertas: list[str] = []
        self.vendas_acoes: dict[tuple, float] = defaultdict(float)   # (ano, mes) -> vendas a vista de acoes
        self.vendas_units: dict[tuple, float] = defaultdict(float)   # parte das vendas que e de units (final 11)
        self.vendas_daytrade: dict[tuple, float] = defaultdict(float)  # parte das vendas que e de day trade (bruto)
        self.irrf: dict[tuple, float] = defaultdict(float)
        self.notas_mes: dict[tuple, list] = defaultdict(list)
        self.conferencia: list[str] = []
        self.eventos_aplicados: list[dict] = []
        self.eventos_vistos: list[str] = []      # eventos com data com no periodo processado, com ou sem posicao
        self.eventos_avisos: list[dict] = []     # evento que o motor nao aplica (cisao, subscricao...) em papel da carteira

    # ---- posicao -------------------------------------------------------------------------------
    def _pos(self, n) -> Posicao:
        p = self.pos.get(n.ticker)
        if p is None:
            venc = ativos.vencimento_opcao(n.vencimento, feriados) if n.classe == 'opcao' and n.vencimento else None
            p = Posicao(n.ticker, n.ativo, n.classe, vencimento=venc, strike=n.strike, tipo_opcao=n.tipo_opcao,
                        subjacente=n.subjacente)
            self.pos[n.ticker] = p
        return p

    def _encerra(self, p: Posicao, dia, cv, q, total_liq, est_cv, total_est, resultado, mercado):
        tipo = 'fii' if p.classe == 'fii' else 'comum'
        self.encerramentos.append(Encerramento(
            p.ticker, p.ativo, p.classe, grupo_de(p.classe, p.tipo_opcao), q, dia, cv, total_liq,
            p.data_estoque, est_cv, total_est, resultado, tipo, mercado))

    def _aplica(self, dia, n, q, valor, mercado):
        """Lote de `q` unidades que sobrou do day trade; `valor` ja tem os custos (compra: +, venda: -)."""
        p = self._pos(n)
        if n.cv == 'C':
            if p.qtd < 0:                                   # recompra de opcao lancada
                qf = min(q, -p.qtd)
                abertura = -p.custo * qf / -p.qtd
                fech = valor * qf / q
                self._encerra(p, dia, 'C', qf, fech, 'V', abertura, abertura - fech, mercado)
                p.custo += abertura
                p.qtd += qf
                q, valor = q - qf, valor - fech
            if q:
                p.qtd += q
                p.custo += valor
                p.data_estoque = dia
        else:
            if p.qtd > 0:
                qf = min(q, p.qtd)
                custo = p.custo * qf / p.qtd
                rec = valor * qf / q
                self._encerra(p, dia, 'V', qf, rec, 'C', custo, rec - custo, mercado)
                p.custo -= custo
                p.qtd -= qf
                q, valor = q - qf, valor - rec
            if q:
                p.qtd -= q
                p.custo -= valor
                p.data_estoque = dia
        if p.qtd == 0:
            p.custo = 0.0

    def _serie(self, dia, n):
        """A serie exercida: pelo codigo da nota; se a nota so traz o ativo-objeto (REGRAS.md, "a conferir" 3), pela
        opcao da carteira com o mesmo ativo-objeto e tipo, de preferencia vencendo no dia, com o strike mais perto do
        preco do exercicio (o strike da B3 pode ter sido ajustado por provento)."""
        opc = self.pos.get(n.ticker)
        if opc and opc.classe == 'opcao' and opc.qtd:
            return opc
        cand = [p for p in self.pos.values() if p.classe == 'opcao' and p.qtd and p.subjacente == n.subjacente
                and p.tipo_opcao == n.tipo_opcao]
        cand = [p for p in cand if p.vencimento == dia] or cand
        if not cand:
            return None
        opc = min(cand, key=lambda p: abs((p.strike or n.preco) - n.preco))
        if len(cand) > 1 and abs((opc.strike or n.preco) - n.preco) > 0.05 * n.preco:
            return None
        self.conferencia.append(f'Exercício de {n.subjacente} a R$ {_br(n.preco)} em {dia:%d/%m}: a nota não trouxe '
                                f'a série; casado com {opc.ticker} pelo ativo-objeto, tipo e strike.')
        return opc

    def _exercicio(self, dia, n):
        """Exercicio: a nota traz a compra/venda do ativo-objeto no strike; o premio da serie vai para o
        custo (compra) ou para o preco (venda), art. 60, II."""
        opc = self._serie(dia, n)
        premio = 0.0
        if opc and opc.qtd:
            q = min(n.qtd, abs(opc.qtd))
            premio = opc.custo * q / abs(opc.qtd)
            opc.custo -= premio
            opc.qtd += q if opc.qtd < 0 else -q
        else:
            self.alertas.append(f'{dia:%d/%m/%Y}: exercício de {n.ticker} sem a série na carteira')
        sub = ativos.identifica('VISTA', '')
        sub.update(ticker=n.subjacente, ativo=n.subjacente, classe='acao')
        obj = type(n)(**{**n.__dict__, **sub, 'mercado': 'VISTA', 'exercicio': False})
        valor = (n.valor + n.taxas + premio) if n.cv == 'C' else (n.valor - n.taxas - premio)
        self._aplica(dia, obj, n.qtd, valor, 'exercicio')

    # ---- dia a dia ------------------------------------------------------------------------------
    def processa_dia(self, dia: dt.date, notas_do_dia: list) -> None:
        negs = []
        for nota in notas_do_dia:
            self.irrf[(dia.year, dia.month)] += nota.irrf
            self.notas_mes[(dia.year, dia.month)].append(nota)
            negs.extend(nota.negocios)
        for n in negs:
            if n.classe == 'acao' and n.cv == 'V' and n.mercado in ('VISTA', 'FRACIONARIO'):
                self.vendas_acoes[(dia.year, dia.month)] += n.valor
                if n.ticker.endswith('11'):
                    self.vendas_units[(dia.year, dia.month)] += n.valor
        por_ticker: dict[str, list] = {}
        for n in negs:
            if n.exercicio:
                self._exercicio(dia, n)
                continue
            por_ticker.setdefault(n.ticker, []).append(n)
        for tk, ops in por_ticker.items():
            lotes = [[n, n.qtd] for n in ops]
            compras = [lt for lt in lotes if lt[0].cv == 'C']
            vendas = [lt for lt in lotes if lt[0].cv == 'V']
            qdt = min(sum(lt[1] for lt in compras), sum(lt[1] for lt in vendas))
            if qdt:
                self._day_trade(dia, compras, vendas, qdt)
            for n, q in lotes:
                if q:
                    self._aplica(dia, n, q, n.liquido * q / n.qtd, 'opcao' if n.classe == 'opcao' else 'vista')

    def _day_trade(self, dia, compras, vendas, qdt):
        """Primeira compra com a primeira venda (art. 65, par. 3); uma linha por ativo e dia."""
        i = j = 0
        resto, custo, receita, bruto_venda = qdt, 0.0, 0.0, 0.0
        while resto:
            c, v = compras[i], vendas[j]
            q = min(c[1], v[1], resto)
            custo += c[0].liquido * q / c[0].qtd
            receita += v[0].liquido * q / v[0].qtd
            bruto_venda += v[0].valor * q / v[0].qtd
            c[1] -= q
            v[1] -= q
            resto -= q
            i += c[1] == 0
            j += v[1] == 0
        n0 = compras[0][0]
        p = self._pos(n0)
        if p.classe == 'acao' and n0.mercado in ('VISTA', 'FRACIONARIO'):
            self.vendas_daytrade[(dia.year, dia.month)] += bruto_venda
        abre_compra = compras[0][0].ordem <= vendas[0][0].ordem
        liq_cv, liq_tot, est_cv, est_tot = ('V', receita, 'C', custo) if abre_compra else ('C', custo, 'V', receita)
        self.encerramentos.append(Encerramento(
            p.ticker, p.ativo, p.classe, grupo_de(p.classe, p.tipo_opcao), qdt, dia, liq_cv, liq_tot, dia, est_cv,
            est_tot, receita - custo, 'daytrade', 'opcao' if p.classe == 'opcao' else 'vista'))

    def vence(self, dia: dt.date) -> None:
        """Opcao que chegou ao vencimento sem encerramento nem exercicio (art. 60, par. 3)."""
        for p in self.pos.values():
            if p.classe == 'opcao' and p.qtd and p.vencimento and p.vencimento <= dia:
                vendida = p.qtd < 0
                self.encerramentos.append(Encerramento(
                    p.ticker, p.ativo, p.classe, grupo_de(p.classe, p.tipo_opcao), abs(p.qtd), p.vencimento,
                    'C' if vendida else 'V', 0.0, p.data_estoque, 'V' if vendida else 'C', abs(p.custo), -p.custo,
                    'comum', 'vencimento'))
                p.qtd, p.custo = 0, 0.0

    def evento(self, ev: dict, dia: dt.date) -> None:
        """Evento societario no fim do dia com (eventos.py; IN 1.585, art. 58): desdobramento e grupamento mudam so a
        quantidade; bonificacao soma as acoes novas pelo valor capitalizado informado (sem ele, custo zero e o registro
        diz); restituicao de capital reduz o custo; troca leva a posicao para o novo codigo. Fracao nao vira acao."""
        p = self.pos.get(ev['ticker'])
        if not p or p.qtd <= 0:
            return
        if ev.get('tipo') not in eventos.APLICA:
            self.eventos_avisos.append({**ev, 'qtd': p.qtd})
            return
        reg = {'id': eventos.ident(ev), 'ticker': p.ticker, 'tipo': ev['tipo'], 'data_com': ev['data_com'],
               'texto': eventos.texto(ev), 'fonte': ev.get('fonte') or '', 'antes': p.qtd, 'pm_antes': p.pm,
               'novas': 0, 'fracao': 0.0, 'valor': 0.0, 'alvo': p.ticker, 'sem_custo': False,
               'atrasado': dia.isoformat() > ev['data_com']}     # saiu na B3 depois do fechamento do mes da data com
        tipo, f = ev['tipo'], float(ev.get('fator') or 1.0)
        if tipo in ('desdobramento', 'grupamento'):
            nova = p.qtd * f
            q = math.floor(nova + 1e-9)
            reg.update(novas=q - p.qtd, fracao=round(nova - q, 6))
            p.qtd = q
            if not q:
                p.custo = 0.0
        elif tipo == 'bonificacao':
            nova = p.qtd * (f - 1)
            q = math.floor(nova + 1e-9)
            alvo = p
            if ev.get('novo_ticker') and ev['novo_ticker'] != p.ticker:
                alvo = self.pos.setdefault(ev['novo_ticker'], Posicao(ev['novo_ticker'], ev['novo_ticker'], p.classe))
            cu = ev.get('custo_unitario')
            valor = round(q * float(cu), 2) if cu is not None else 0.0
            alvo.qtd += q
            alvo.custo += valor
            alvo.data_estoque = alvo.data_estoque or dia
            reg.update(novas=q, fracao=round(nova - q, 6), valor=valor, alvo=alvo.ticker, sem_custo=cu is None)
        elif tipo == 'restituicao':
            v = round(p.qtd * float(ev.get('valor_por_acao') or 0.0), 2)
            reg['valor'] = v
            if v > p.custo:
                self.alertas.append(f'A CONFERIR: a restituição de capital de {p.ticker} em {dia:%d/%m/%Y} (R$ '
                                    f'{_br(v)}) passa do custo da posição; o custo ficou em zero.')
            p.custo = max(p.custo - v, 0.0)
        elif tipo == 'troca':
            novo = ev['novo_ticker']
            nova = p.qtd * f
            q = math.floor(nova + 1e-9)
            np_ = self.pos.setdefault(novo, Posicao(novo, ev.get('novo_ativo') or novo, p.classe))
            np_.qtd += q
            np_.custo += p.custo
            np_.data_estoque = np_.data_estoque or p.data_estoque
            reg.update(novas=q, fracao=round(nova - q, 6), alvo=novo)
            p.qtd, p.custo = 0, 0.0
        alvo = self.pos[reg['alvo']]
        reg.update(depois=alvo.qtd, pm_depois=alvo.pm)
        self.eventos_aplicados.append(reg)

    def processa(self, notas: list, ate: dt.date, desde: dt.date | None = None, eventos_: list | None = None) -> None:
        por_dia: dict[dt.date, list] = defaultdict(list)
        for nt in notas:
            if (desde is None or nt.pregao >= desde) and nt.pregao <= ate:
                por_dia[nt.pregao].append(nt)
        evs: dict[dt.date, list] = defaultdict(list)
        for ev in eventos_ or ():
            evs[dt.date.fromisoformat(ev['data_com'])].append(ev)
        dia = desde or (min(por_dia) if por_dia else ate)
        while dia <= ate:
            if dia in por_dia:
                self.processa_dia(dia, por_dia[dia])
            self.vence(dia)
            for ev in evs.get(dia, ()):
                self.eventos_vistos.append(eventos.ident(ev))
                self.evento(ev, dia)
            dia += dt.timedelta(1)

    def posicoes(self) -> list[Posicao]:
        return [p for p in self.pos.values() if p.qtd]


# ---- apuracao do mes ---------------------------------------------------------------------------
def ultimo_dia_util(ano: int, mes: int) -> dt.date:
    d = (dt.date(ano + mes // 12, mes % 12 + 1, 1) - dt.timedelta(1))
    while d.weekday() >= 5 or d in feriados(d.year):
        d -= dt.timedelta(1)
    return d


def vencimento_darf(ano: int, mes: int) -> dt.date:
    """Ultimo dia util do mes seguinte ao da apuracao (IN 1.585, art. 56, par. 5). 31/12 nao conta: na Agenda
    Tributaria da Receita de dezembro de 2024 e de 2025 (ADE Corat 28/2025) o 6015 de novembro vence em 30/12 e o dia
    31/12 so tem declaracoes (lidas em 08/11/2026; REGRAS.md, DARF)."""
    d = ultimo_dia_util(ano + mes // 12, mes % 12 + 1)
    if (d.month, d.day) == (12, 31):
        d -= dt.timedelta(1)
        while d.weekday() >= 5 or d in feriados(d.year):
            d -= dt.timedelta(1)
    return d


@dataclass
class Saldo:
    """O que passa de um mes para o outro."""
    prejuizos: dict = field(default_factory=lambda: {'comum': 0.0, 'daytrade': 0.0, 'fii': 0.0})
    irrf: float = 0.0                 # IRRF ainda nao usado
    pendente: float = 0.0             # imposto abaixo de R$ 10 ainda nao pago


def apura_mes(cart: Carteira, ano: int, mes: int, saldo: Saldo) -> dict:
    encs = [e for e in cart.encerramentos if (e.liq_data.year, e.liq_data.month) == (ano, mes)]
    vendas = cart.vendas_acoes[(ano, mes)]
    isento_mes = vendas <= LIMITE_ISENCAO
    a_vista = [e for e in encs if e.classe == 'acao' and e.mercado == 'vista' and e.tipo == 'comum']
    lucro_vista = sum(e.resultado for e in a_vista)
    if isento_mes and lucro_vista > 0:                           # prejuizo do mes isento fica em comum
        for e in a_vista:
            e.tipo = 'isento'
    # o que a lei nao diz com todas as letras e muda o imposto do mes vira alerta (REGRAS.md, "a conferir"); sem lucro
    # nas acoes a vista, isento ou nao da no mesmo
    vendas_dt = cart.vendas_daytrade[(ano, mes)]
    cruza = (vendas <= LIMITE_ISENCAO) != (vendas - vendas_dt <= LIMITE_ISENCAO)
    duvidas = {'vendas_daytrade': vendas_dt if cruza and lucro_vista > 0 else 0.0,
               'units_isentas': sorted({e.ticker for e in encs if e.tipo == 'isento' and e.ticker.endswith('11')})}
    res = {k: sum(e.resultado for e in encs if e.tipo == k) for k in ('comum', 'daytrade', 'fii', 'isento')}
    linhas, imposto, novo = [], 0.0, dict(saldo.prejuizos)
    for k in ('comum', 'daytrade', 'fii'):
        acum = res[k] + saldo.prejuizos.get(k, 0.0)
        base = max(acum, 0.0)
        novo[k] = min(acum, 0.0)
        imp = round(base * ALIQ[k], 2)
        imposto += imp
        linhas.append({'tipo': k, 'resultado': res[k], 'prejuizo_anterior': saldo.prejuizos.get(k, 0.0),
                       'prejuizo': novo[k], 'base': base, 'imposto': imp,
                       # quanto do prejuizo anterior o lucro do mes consumiu (zero se o mes deu prejuizo)
                       'prejuizo_usado': round(max(novo[k] - saldo.prejuizos.get(k, 0.0), 0.0), 2)})
    irrf_mes = round(cart.irrf[(ano, mes)], 2)
    irrf_disp = irrf_mes + saldo.irrf
    usado = min(irrf_disp, imposto)
    devido = round(imposto - usado + saldo.pendente, 2)
    darf = devido if devido >= DARF_MINIMO else 0.0
    return {
        'ano': ano, 'mes': mes, 'encerramentos': encs, 'linhas': linhas, 'resultados': res,
        'vendas_acoes': vendas, 'isento_mes': isento_mes, 'duvidas': duvidas, 'imposto_bruto': imposto, 'irrf_mes': irrf_mes,
        'irrf_usado': usado, 'devido': devido, 'darf': darf, 'vencimento': vencimento_darf(ano, mes),
        'saldo': Saldo(novo, round(irrf_disp - usado, 2), devido if darf == 0 else 0.0),
    }


def agrupa(encs: list[Encerramento]) -> list[Encerramento]:
    """Uma linha por ativo, dia, lado e tipo, como no relatorio (os lotes de 100 de uma ordem viram uma linha)."""
    out: dict[tuple, Encerramento] = {}
    for e in encs:
        k = (e.ticker, e.liq_data, e.liq_cv, e.tipo, e.mercado)
        if k in out:
            a = out[k]
            a.qtd += e.qtd
            a.liq_total += e.liq_total
            a.est_total += e.est_total
            a.resultado += e.resultado
        else:
            out[k] = Encerramento(**e.__dict__)
    return sorted(out.values(), key=lambda e: (e.grupo, e.liq_data, e.ticker))


def infere_datas(posicoes: list[Posicao], notas: list, antes_de: dt.date) -> None:
    """Data de estoque das posicoes importadas: ultimo pregao, nas notas que existem, em que a posicao cresceu.
    Opcao importada sem strike ganha o strike da ultima nota da serie (o relatorio da IRTrade nao traz)."""
    for p in posicoes:
        lado = 'C' if p.qtd > 0 else 'V'
        negs = [n for nt in notas if nt.pregao < antes_de for n in nt.negocios if n.ticker == p.ticker]
        datas = [n.pregao for n in negs if n.cv == lado]
        if datas and not p.data_estoque:
            p.data_estoque = max(datas)
        com_strike = [n for n in negs if n.strike]
        if p.classe == 'opcao' and not p.strike and com_strike:
            p.strike = max(com_strike, key=lambda n: n.pregao).strike


def posicao_dict(p: Posicao) -> dict:
    d = asdict(p)
    for k in ('data_estoque', 'vencimento'):
        d[k] = d[k].isoformat() if d[k] else None
    return d


def posicao_de_dict(d: dict) -> Posicao:
    d = dict(d)
    for k in ('data_estoque', 'vencimento'):
        d[k] = dt.date.fromisoformat(d[k]) if d.get(k) else None
    return Posicao(**d)
