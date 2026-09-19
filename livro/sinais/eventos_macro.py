"""Agenda: E01 resultado (D-3, D-1, D0), E02 ex-dividendo (D-1), M01 evento macro
do dia/de amanha, M03 Focus da segunda-feira (mediana vs pesquisa anterior).
Le ctx.eventos['agenda'] (fontes/agenda.py + calendario.yaml), ctx.eventos
['calendario'] e ctx.macro['focus']. Nunca inventa consenso: sem fonte, diz
'consenso nao disponivel'."""

from __future__ import annotations

import math
import re
from datetime import date, timedelta

from livro import fmt, relogios
from livro import indicadores as ind
from livro.sinais.base import Alerta, Contexto, Estado, Regra

QUANDO = {"apos_ny": "após o fechamento de NY", "antes_ny": "antes da abertura de NY", "apos_b3": "após o fechamento da B3",
          "madrugada": "de madrugada (horário de Brasília)", "": "horário não confirmado"}


def _dias_uteis_ate(mercado: str, hoje: date, alvo: date) -> int | None:
    """Sessoes do mercado estritamente depois de hoje ate alvo (0 se alvo == hoje)."""
    if alvo < hoje:
        return None
    n, d = 0, hoje
    while d < alvo:
        d += timedelta(days=1)
        if relogios.eh_dia_util(mercado, d):
            n += 1
        if n > 60:
            break
    return n


def _mercado(ctx: Contexto, ativo: str) -> str:
    a = ctx.ativo(ativo)
    return (a.mercado if a else "B3") or "B3"


class E01Resultado(Regra):
    id = "E01"
    familia = "evento"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("E01_RESULTADO") or {}
        antecedencia = [int(x) for x in (L.get("antecedencia") or [3, 1, 0])]
        vol_n = int(L.get("vol_sessoes", 20))
        agenda = (ctx.eventos or {}).get("agenda") or {}
        out = []
        for r in agenda.get("resultados") or []:
            ativo = r.get("ticker")
            if not ativo or not ctx.ativo(ativo):
                continue
            try:
                alvo = date.fromisoformat(str(r["data"])[:10])
            except ValueError:
                continue
            n = _dias_uteis_ate(_mercado(ctx, ativo), ctx.hoje, alvo)
            if n is None or n not in antecedencia:
                continue
            tag = "D0" if n == 0 else f"D-{n}"
            sev = "atencao" if n == 1 else "info"
            df = ctx.series.get(ativo)
            corpo = [f"{fmt.dia_semana(alvo)} {fmt.data_br(alvo.isoformat())} · {QUANDO.get(r.get('quando', ''), r.get('quando', ''))} · "
                     f"{'confirmado' if r.get('confirmado') else 'estimado'} ({r.get('fonte', '')})"]
            if df is not None and len(df) > vol_n + 2:
                vol = ind.vol_anualizada(df["adj"], vol_n)
                if vol:
                    corpo.append(f"Vol de {vol_n} dias {fmt.pct(vol, 0)} a.a. ⇒ movimento típico de 1 dia ±{fmt.pct(vol / math.sqrt(252), 1, False)}")
                j = ind.janelas(df)
                corpo.append(f"Chega ao resultado com 1m {fmt.pct(j.get('1m'))} · 6m {fmt.pct(j.get('6m'))} · YTD {fmt.pct(j.get('ytd'))}")
            corpo.append("Consenso: não disponível (sem fonte licenciada); usar o release e o guidance anterior")
            if r.get("nota"):
                corpo.append(f"Nota: {r['nota']}")
            quando_txt = {"D0": "sai hoje", "D-1": "sai na próxima sessão", "D-3": "sai em 3 sessões"}.get(tag, f"sai em {n} sessões")
            titulo = f"{ctx.rotulo(ativo)}: resultado {quando_txt} ({fmt.data_br(alvo.isoformat())})"
            por_que = "resultado é o evento que mais move o papel em um dia; a vol implícita e o posicionamento sobem antes e caem depois"
            falar = ("o resultado sai amanhã; o movimento típico do papel num dia é o da vol acima, e o mercado costuma exagerar na abertura" if n == 1
                     else "o resultado sai hoje; conversar com cliente depois do release, não antes" if n == 0
                     else "resultado na próxima semana; é a hora de rever o que o mercado espera")
            out.append(Alerta(self.id, ativo, sev, "evento", titulo, tag=tag, data=ctx.hoje.isoformat(), corpo=corpo,
                              por_que=por_que, como_falar=falar, fonte=r.get("fonte", "config/calendario.yaml"),
                              dados={"data_resultado": alvo.isoformat(), "sessoes": n, "confirmado": bool(r.get("confirmado")),
                                     "veiculo": "agenda", "manchete": titulo, "ativos": [ativo]}))
        return out


class E02ExDividendo(Regra):
    id = "E02"
    familia = "evento"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("E02_EX_DIVIDENDO") or {}
        ant = int(L.get("antecedencia", 1))
        agenda = (ctx.eventos or {}).get("agenda") or {}
        out = []
        for e in agenda.get("ex_dividendos") or []:
            ativo = e.get("ticker")
            if not ativo or not ctx.ativo(ativo):
                continue
            try:
                alvo = date.fromisoformat(str(e["data"])[:10])
            except ValueError:
                continue
            n = _dias_uteis_ate(_mercado(ctx, ativo), ctx.hoje, alvo)
            if n is None or n != ant:
                continue
            valor = e.get("valor")
            df = ctx.series.get(ativo)
            close = float(df["close"].iloc[-1]) if df is not None and len(df) else None
            yld = (valor / close) if valor and close else None
            v_txt = f"{e.get('moeda', '')} {fmt.num(valor, 2)}".strip() if valor else "valor a confirmar"
            titulo = f"{ctx.rotulo(ativo)} fica ex-dividendo em {fmt.data_br(alvo.isoformat())}: {v_txt}" + (f" ({fmt.pct(yld, 2, False)} do preço)" if yld else "")
            corpo = [f"Último provento pago como referência; pagamento {fmt.data_br(e['pagamento']) if e.get('pagamento') else 'a confirmar'}. {e.get('nota', '')}".strip()]
            out.append(Alerta(self.id, ativo, "info", "evento", titulo, tag="ex", data=ctx.hoje.isoformat(), corpo=corpo,
                              por_que="no dia ex o preço abre descontado do provento; a queda não é perda, é o caixa que muda de bolso",
                              como_falar="quem tem o papel hoje recebe; amanhã o preço abre ajustado pelo provento",
                              fonte="Yahoo Finance (calendário); conferir aviso aos acionistas",
                              dados={"data_ex": alvo.isoformat(), "valor": valor, "yield": yld, "veiculo": "agenda", "manchete": titulo, "ativos": [ativo]}))
        return out


class M01AgendaMacro(Regra):
    id = "M01"
    familia = "evento"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("M01_AGENDA_MACRO") or {}
        chaves = [str(x) for x in (L.get("alta_relevancia") or [])]
        cal = (ctx.eventos or {}).get("calendario") or {}
        out = []
        amanha = relogios.proximo_dia_util("B3", ctx.hoje)
        for e in cal.get("eventos_macro") or []:
            try:
                d = date.fromisoformat(str(e.get("data"))[:10])
            except ValueError:
                continue
            if d == ctx.hoje:
                quando, tag = "hoje", "D0"
            elif d == amanha:
                quando, tag = "amanhã", "D-1"
            else:
                continue
            evento = str(e.get("evento", ""))
            relevante = any(re.search(rf"(?i)\b{re.escape(k)}\b", evento) for k in chaves)
            sev = "atencao" if (relevante and tag == "D0") else "info"
            hora = f" às {e['hora_brt']}" if e.get("hora_brt") else ""
            titulo = f"Agenda: {evento} {quando}{hora} ({fmt.data_br(d.isoformat())})"
            corpo = self._no_preco(ctx)
            out.append(Alerta(self.id, "MACRO", sev, "evento", titulo, tag=f"{tag}_{fmt.data_br(d.isoformat()).replace('/', '')}",
                              data=ctx.hoje.isoformat(), corpo=corpo,
                              por_que="evento macro de alta relevância reprecifica a curva inteira; o que importa é a surpresa contra o que está no preço",
                              como_falar=f"{evento.split('(')[0].strip()} sai {quando}; o mercado já precifica o consenso, a reação vem da surpresa",
                              fonte="config/calendario.yaml", ativos_afetados="DI · Tesouro · USD/BRL" if e.get("pais") == "BR" else "UST · DXY · UCITS",
                              dados={"evento": evento, "data": d.isoformat(), "pais": e.get("pais"), "veiculo": "agenda", "manchete": titulo, "ativos": []}))
        return out

    @staticmethod
    def _no_preco(ctx: Contexto) -> list[str]:
        partes = []
        di = (ctx.curvas.get("di") or {}).get("historico") or {}
        for c in ("DI1F28", "DI1F35"):
            h = di.get(c) or []
            if h and h[-1][1] is not None:
                partes.append(f"{c[3:]} {fmt.taxa(h[-1][1])}%")
        tes = ((ctx.curvas.get("tesouro") or {}).get("titulos") or {})
        pre, ipca = tes.get("PRE2029"), tes.get("IPCA2029")
        if pre and ipca and pre.get("historico") and ipca.get("historico"):
            be = ind.breakeven(pre["historico"][-1][1], ipca["historico"][-1][1])
            partes.append(f"implícita 2029 {fmt.taxa(be)}%")
        foc = ((ctx.macro.get("focus") or {}).get("expectativas") or {}).get("IPCA") or {}
        ano = str(ctx.hoje.year + 1)
        if (foc.get("por_ano") or {}).get(ano):
            partes.append(f"Focus IPCA {ano} {fmt.taxa(foc['por_ano'][ano]['mediana'])}%")
        return [("O que está no preço: " + " · ".join(partes)) if partes else "O que está no preço: curva não disponível neste slot"]


class M03Focus(Regra):
    id = "M03"
    familia = "evento"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("M03_FOCUS") or {}
        foc = ((ctx.macro.get("focus") or {}).get("expectativas") or {})
        if not foc:
            return []
        data_pesq = None
        for ind_nome in ("IPCA", "Selic", "Cambio"):
            for ano, v in ((foc.get(ind_nome) or {}).get("por_ano") or {}).items():
                if v.get("data"):
                    data_pesq = max(data_pesq or "", str(v["data"])[:10])
        if not data_pesq or estado.ultima_data("M03") == data_pesq:
            return []
        if (ctx.hoje - date.fromisoformat(data_pesq)).days > 7:
            return []
        anos = [str(ctx.hoje.year), str(ctx.hoje.year + 1)]
        linhas, sev = [], "info"
        for ind_nome, rot, escala in (("IPCA", "IPCA", "bps"), ("Selic", "Selic fim de ano", "bps"), ("Cambio", "Câmbio fim de ano", "R$")):
            partes = []
            for ano in anos:
                v = ((foc.get(ind_nome) or {}).get("por_ano") or {}).get(ano)
                if not v:
                    continue
                med, ant = v.get("mediana"), (v.get("anterior") or {}).get("mediana")
                if escala == "bps":
                    delta = ind.bps(med, ant) if ant is not None else None
                    d_txt = f" ({fmt.bps(delta)} bps)" if delta is not None else ""
                    partes.append(f"{ano} {fmt.taxa(med)}%{d_txt}")
                    lim = L.get("bps_ipca_atencao", 10) if ind_nome == "IPCA" else L.get("bps_selic_atencao", 25)
                    if delta is not None and abs(delta) >= lim:
                        sev = "atencao"
                else:
                    delta = (med - ant) if ant is not None else None
                    d_txt = f" ({'+' if delta > 0 else ''}{fmt.num(delta, 2)})" if delta is not None else ""
                    partes.append(f"{ano} R$ {fmt.num(med, 2)}{d_txt}")
                    if delta is not None and abs(delta) >= float(L.get("cambio_atencao", 0.05)):
                        sev = "atencao"
            if partes:
                linhas.append(f"{rot}: " + " · ".join(partes))
        if not linhas:
            return []
        estado.marcar("M03", data_pesq)
        titulo = f"Focus de {fmt.data_br(data_pesq)}: " + linhas[0]
        return [Alerta(self.id, "MACRO", sev, "evento", titulo, tag="focus", data=data_pesq, corpo=linhas[1:],
                       por_que="a mediana do Focus é a régua do Copom; mudança de 10 bps no IPCA ou 25 bps na Selic muda a leitura da curva",
                       como_falar="o mercado revisou as projeções; comparar com o que a curva de juros já precifica",
                       fonte=f"BCB Focus (Olinda) {fmt.data_br(data_pesq)}", ativos_afetados="DI · Tesouro · USD/BRL",
                       dados={"data": data_pesq, "veiculo": "Focus", "manchete": titulo, "ativos": []})]


REGRAS = [E01Resultado(), E02ExDividendo(), M01AgendaMacro(), M03Focus()]
