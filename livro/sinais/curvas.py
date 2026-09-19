"""Regras de curva (v1.0): C01 DI movimento em bps, C04 Tesouro juro real por
grade, C05 Tesouro variacao de PU, C07 UST movimento e niveis.

Relogios: DI = ajuste B3 do pregao (publicado apos 18h BRT); Tesouro = data-base
do Tesouro Transparente (D-1 pela manha); UST = CMT do Treasury (fim da tarde
de NY). Nunca misturar os tres na mesma comparacao."""

from __future__ import annotations

import re

from livro import fmt
from livro import indicadores as ind
from livro.sinais.base import Alerta, Contexto, Estado, Regra


def _serie_di(ctx: Contexto, codigo: str) -> list[list]:
    return ((ctx.curvas.get("di") or {}).get("historico") or {}).get(codigo) or []


def _delta(hist: list[list], n: int = 1, idx: int = 1) -> float | None:
    if len(hist) <= n:
        return None
    a, b = hist[-1][idx], hist[-1 - n][idx]
    return ind.bps(a, b) if a is not None and b is not None else None


def _sequencia_bps(hist: list[list], ignora: float) -> tuple[int, float]:
    n, sinal, acum = 0, 0, 0.0
    for i in range(len(hist) - 1, 0, -1):
        d = ind.bps(hist[i][1], hist[i - 1][1])
        if d is None:
            break
        if abs(d) < ignora:
            continue
        sg = 1 if d > 0 else -1
        if sinal == 0:
            sinal = sg
        if sg != sinal:
            break
        n += 1
        acum += d
    return n * sinal, acum


class C01DIMovimento(Regra):
    id = "C01"
    familia = "curva"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("C01_DI_MOVIMENTO") or {}
        di = ctx.curvas.get("di") or {}
        codigos = [v["codigo"] for v in (ctx.universo.curvas.get("di", {}).get("vertices") or [])]
        if not di.get("historico"):
            return []
        ultimo = di.get("ultimo_pregao")
        if not ultimo or ultimo < ctx.hoje.isoformat():
            ctx.falhas.setdefault("di", f"ajuste B3 de {ctx.hoje.isoformat()} ainda não publicado (último {ultimo})")
            return []
        linhas, gatilhos, deltas, sev = [], [], {}, "info"
        for c in codigos:
            h = _serie_di(ctx, c)
            if not h or h[-1][0] != ultimo:
                continue
            d1 = _delta(h, 1)
            d5 = _delta(h, 5)
            seq, acum = _sequencia_bps(h, float(L.get("ignora_bps", 2)))
            deltas[c] = d1
            linhas.append(f"{c[3:]} {fmt.taxa(h[-1][1])} ({fmt.bps(d1)})")
            if d1 is not None and abs(d1) >= L.get("bps_critico", 25):
                sev = "critico"
                gatilhos.append(f"{c[3:]} {fmt.bps(d1)} bps no dia")
            elif d1 is not None and abs(d1) >= L.get("bps_atencao", 15):
                sev = "atencao" if sev != "critico" else sev
                gatilhos.append(f"{c[3:]} {fmt.bps(d1)} bps no dia")
            if d5 is not None and abs(d5) >= L.get("bps_5d", 40):
                sev = "atencao" if sev != "critico" else sev
                gatilhos.append(f"{c[3:]} {fmt.bps(d5)} bps em 5 pregões")
            if abs(seq) >= L.get("sequencia_min", 4) and abs(acum) >= L.get("sequencia_bps", 30):
                sev = "critico" if abs(acum) >= L.get("sequencia_critico_bps", 60) else ("atencao" if sev != "critico" else sev)
                gatilhos.append(f"{c[3:]} {abs(seq)} pregões seguidos ({fmt.bps(acum)} bps)")
        di["delta_bps"] = deltas
        if not gatilhos:
            return []
        if estado.ultima_data("C01") == ultimo:
            return []
        f28, f35 = _serie_di(ctx, "DI1F28"), _serie_di(ctx, "DI1F35")
        incl = incl_ant = None
        if f28 and f35 and len(f28) > 1 and len(f35) > 1:
            incl = ind.bps(f35[-1][1], f28[-1][1])
            incl_ant = ind.bps(f35[-2][1], f28[-2][1])
        direcao = [d for d in deltas.values() if d is not None]
        abriu = sum(direcao) > 0
        titulo = f"A curva {'ABRIU' if abriu else 'FECHOU'}: " + " · ".join(gatilhos[:3]) + f" (ajuste B3 {fmt.data_br(ultimo)})"
        corpo = ["DI " + " · ".join(linhas)]
        if incl is not None:
            corpo.append(f"Inclinação F35-F28 {fmt.bps(incl)} bps ({fmt.bps(incl - incl_ant) if incl_ant is not None else '-'})")
        ust10 = (ctx.curvas.get("ust") or {}).get("delta_bps", {}).get("10y")
        if ust10 is not None:
            corpo.append(f"UST 10y {fmt.bps(ust10)} bps no dia: " + ("movimento importado" if abs(ust10) >= 8 and (ust10 > 0) == abriu else "movimento doméstico"))
        por_que = ("a curva é o preço do dinheiro no Brasil; longo abrindo com curto parado é prêmio de risco, não Selic"
                   if incl is not None and incl_ant is not None and incl > incl_ant and abriu else
                   "delta em bps e inclinação são o que toda mesa de renda fixa reporta e o que explica a marcação do Tesouro ao cliente")
        falar = ("o prefixado longo marcou a mercado para baixo; quem carrega até o vencimento não mudou de taxa" if abriu
                 else "a curva fechou: o prefixado valorizou na marcação; o cupom contratado não muda")
        estado.marcar("C01", ultimo)
        return [Alerta(self.id, "DI", sev, "curva", titulo, tag="abriu" if abriu else "fechou", data=ultimo, corpo=corpo,
                       por_que=por_que, como_falar=falar, fonte=f"ajuste B3 {fmt.data_br(ultimo)}",
                       ativos_afetados="Tesouro IPCA+ longo PU " + ("↓" if abriu else "↑") + " · Pré 2031 " + ("↓" if abriu else "↑") + " · EQTL3/ALUP4/SAPR4 " + ("↓" if abriu else "↑"),
                       dados={"deltas": deltas, "inclinacao": incl})]


def _titulos(ctx: Contexto) -> dict:
    return (ctx.curvas.get("tesouro") or {}).get("titulos") or {}


class C04TesouroJuroReal(Regra):
    id = "C04"
    familia = "curva"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("C04_TESOURO_JURO_REAL") or {}
        grade = [float(x) for x in L.get("grade", [6.0, 6.5, 7.0, 7.5, 8.0])]
        criticos = {float(x) for x in L.get("criticos", [7.0, 8.0])}
        banda = float(L.get("banda_bps", 3)) / 100.0
        cool = int(L.get("cooldown_datas", 10))
        out = []
        for tid, t in _titulos(ctx).items():
            if not t.get("tipo", "").lower().startswith("tesouro ipca"):
                continue
            h = t.get("historico") or []
            if len(h) < 3:
                continue
            base, taxa, pu = h[-1][0], h[-1][1], h[-1][2]
            ant = h[-2][1]
            if taxa is None or ant is None:
                continue
            ant2 = h[-3][1] if len(h) >= 3 else None
            for nivel in grade:
                if nivel in criticos:
                    # niveis criticos exigem 2 datas-base consecutivas do mesmo lado
                    if ant2 is None:
                        continue
                    cima = ant2 < nivel and ant >= nivel + banda and taxa >= nivel + banda
                    baixo = ant2 > nivel and ant <= nivel - banda and taxa <= nivel - banda
                else:
                    cima = ant < nivel <= taxa - banda
                    baixo = ant > nivel >= taxa + banda
                if not (cima or baixo):
                    continue
                chave = f"C04:{tid}:{nivel}"
                datas = [x[0] for x in h]
                if estado.em_cooldown(chave, datas, cool):
                    continue
                hist_taxas = [x[1] for x in h if x[1] is not None]
                pctl = ind.percentil(hist_taxas, taxa)
                dv01 = ind.dv01_empirico([x[1] for x in h[-60:]], [x[2] for x in h[-60:]])
                sev = "critico" if nivel in criticos else "atencao"
                titulo = (f"{t.get('apelido', tid)} {'rompe' if cima else 'volta abaixo de'} {fmt.taxa(nivel)}% real: "
                          f"{fmt.taxa(taxa)}% ({fmt.bps(ind.bps(taxa, ant))} bps), base {fmt.data_br(base)}")
                corpo = []
                if pu:
                    corpo.append(f"PU R$ {fmt.num(pu)}" + (f"; cada 10 bps move ~{fmt.pct(dv01, 1, False)} do PU" if dv01 else ""))
                if pctl is not None:
                    corpo.append(f"Desde 2010, {fmt.num(100 - pctl, 0)}% dos dias tiveram taxa maior neste título")
                por_que = "juro real acima de 6-7% é o argumento central do assessor brasileiro para renda fixa; cada 0,50 pp muda o discurso"
                falar = (f"o Tesouro IPCA+ passou a pagar {fmt.taxa(taxa)}% acima da inflação; é nível raro, não rotina" if cima
                         else f"o juro real cedeu abaixo de {fmt.taxa(nivel)}%: quem comprou nos níveis maiores está marcando ganho")
                out.append(Alerta(self.id, tid, sev, "curva", titulo, tag=f"{'cima' if cima else 'baixo'}_{nivel}", data=base, corpo=corpo,
                                  por_que=por_que, como_falar=falar, fonte=f"Tesouro Transparente, base {fmt.data_br(base)}",
                                  dados={"taxa": taxa, "nivel": nivel, "percentil": pctl, "pu": pu}))
                estado.marcar(chave, base)
        return out


class C05TesouroVariacaoPU(Regra):
    id = "C05"
    familia = "curva"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("C05_TESOURO_VARIACAO_PU") or {}
        titulos = _titulos(ctx)
        if not titulos:
            return []
        base = max([t["historico"][-1][0] for t in titulos.values() if t.get("historico")] or [""])
        if not base or estado.ultima_data("C05") == base:
            return []
        gatilhos, linhas, sev = [], [], "info"
        for tid, t in titulos.items():
            h = [x for x in (t.get("historico") or []) if x[1] is not None]
            if len(h) < 6 or h[-1][0] != base:
                continue
            d1 = ind.bps(h[-1][1], h[-2][1])
            pu1, pu0 = h[-1][2], h[-2][2]
            var_pu = (pu1 / pu0 - 1.0) if pu1 and pu0 else None
            pu_max5 = max([x[2] for x in h[-6:-1] if x[2]] or [0])
            dd5 = (pu1 / pu_max5 - 1.0) if pu1 and pu_max5 else None
            linhas.append(f"{t.get('apelido', tid)} {fmt.taxa(h[-1][1])} ({fmt.bps(d1)})" + (f" PU {fmt.pct(var_pu)}" if var_pu is not None and abs(var_pu) >= 0.005 else ""))
            lim_dd = (L.get("drawdown_5d") or {}).get(tid, (L.get("drawdown_5d") or {}).get("padrao", 0.03))
            lim_dd_c = (L.get("drawdown_5d_critico") or {}).get(tid, (L.get("drawdown_5d_critico") or {}).get("padrao", 0.05))
            if d1 is not None and abs(d1) >= L.get("bps_critico", 25):
                sev = "critico"
                gatilhos.append(f"{t.get('apelido', tid)} {'ABRE' if d1 > 0 else 'FECHA'} {fmt.bps(d1, 0, False)} bps" + (f" (PU {fmt.pct(var_pu)})" if var_pu is not None else ""))
            elif d1 is not None and abs(d1) >= L.get("bps_atencao", 15):
                sev = "atencao" if sev != "critico" else sev
                gatilhos.append(f"{t.get('apelido', tid)} {'ABRE' if d1 > 0 else 'FECHA'} {fmt.bps(d1, 0, False)} bps" + (f" (PU {fmt.pct(var_pu)})" if var_pu is not None else ""))
            if dd5 is not None and dd5 <= -lim_dd:
                sev = "critico" if dd5 <= -lim_dd_c else ("atencao" if sev != "critico" else sev)
                gatilhos.append(f"{t.get('apelido', tid)} PU {fmt.pct(dd5)} em 5 datas-base")
        if not gatilhos:
            return []
        titulo = " · ".join(gatilhos[:3]) + f" (base {fmt.data_br(base)})"
        abriu = any("ABRE" in g for g in gatilhos)
        por_que = ("abertura crescente com o prazo é venda de duration, não revisão de inflação; o cliente vê o PU cair no extrato" if abriu
                   else "fechamento de taxa é ganho de marcação; quem carrega até o vencimento não mudou de rentabilidade")
        falar = ("quem comprou para carregar não perdeu nada: o PU marca a mercado, a taxa contratada é a mesma" if abriu
                 else "a marcação a mercado veio a favor; o rendimento contratado segue igual")
        estado.marcar("C05", base)
        return [Alerta(self.id, "TESOURO", sev, "curva", titulo, tag="abriu" if abriu else "fechou", data=base,
                       corpo=["TD " + " · ".join(linhas)], por_que=por_que, como_falar=falar,
                       fonte=f"Tesouro Transparente, base {fmt.data_br(base)}", dados={"gatilhos": gatilhos})]


class C07UST(Regra):
    id = "C07"
    familia = "curva"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("C07_UST") or {}
        ust = ctx.curvas.get("ust") or {}
        h = ust.get("historico") or []
        if len(h) < 6:
            return []
        prazos = ust.get("prazos") or ["2y", "5y", "10y", "30y"]
        idx = {p: i + 1 for i, p in enumerate(prazos)}
        ult = h[-1]
        deltas = {}
        for p in prazos:
            i = idx[p]
            deltas[p] = ind.bps(ult[i], h[-2][i]) if ult[i] is not None and h[-2][i] is not None else None
        ust["delta_bps"] = deltas
        ust["ultima_data"] = ult[0]
        if estado.ultima_data("C07") == ult[0]:
            return []
        gatilhos, sev = [], "info"
        for p in ("2y", "10y", "30y"):
            d = deltas.get(p)
            if d is None:
                continue
            if abs(d) >= L.get("bps_critico", 20):
                sev = "critico"
                gatilhos.append(f"{p} {fmt.bps(d)} bps")
            elif abs(d) >= L.get("bps_atencao", 10):
                sev = "atencao" if sev != "critico" else sev
                gatilhos.append(f"{p} {fmt.bps(d)} bps")
        i10 = idx["10y"]
        d5 = ind.bps(ult[i10], h[-6][i10]) if ult[i10] is not None and h[-6][i10] is not None else None
        if d5 is not None and abs(d5) >= L.get("bps_5d_10y", 25):
            sev = "atencao" if sev != "critico" else sev
            gatilhos.append(f"10y {fmt.bps(d5)} bps em 5 pregões")
        banda = float(L.get("banda_bps", 3)) / 100.0
        for p in ("10y", "30y", "2y"):
            i = idx[p]
            a, b = ult[i], h[-2][i]
            if a is None or b is None:
                continue
            for nivel in L.get("grade", [3.5, 4.0, 4.5, 5.0, 5.5]):
                if b < nivel <= a - banda or b > nivel >= a + banda:
                    crit = float(nivel) >= float(L.get("critico_nivel", 5.0)) and p != "2y"
                    sev = "critico" if crit else ("atencao" if sev != "critico" else sev)
                    gatilhos.append(f"{p} cruzou {fmt.taxa(nivel)}%")
        if not gatilhos:
            return []
        y2, y10, y30 = ult[idx["2y"]], ult[i10], ult[idx["30y"]]
        s2s10 = ind.bps(y10, y2) if y10 is not None and y2 is not None else None
        abriu = (deltas.get("10y") or 0) > 0
        titulo = f"UST {'ABRIU' if abriu else 'FECHOU'}: " + " · ".join(gatilhos[:3]) + f" ({fmt.data_br(ult[0])})"
        corpo = [f"2y {fmt.taxa(y2)} · 10y {fmt.taxa(y10)} · 30y {fmt.taxa(y30)}" + (f" · 2s10s {fmt.bps(s2s10)} bps" if s2s10 is not None else "")]
        dur = float(L.get("duration_iuaa", 6.0))
        d10 = deltas.get("10y") or 0.0
        efeito = -dur * d10 / 10000.0
        corpo.append(f"Transmissão: IUAA (iShares US Aggregate Bond, duração ~{fmt.num(dur, 0)}) ≈ {fmt.pct(efeito)}; " +
                     ("pressiona múltiplo de CNDX/RBOT, fortalece DXY e pesa no real" if abriu else "alivia CNDX/RBOT e o real"))
        por_que = "o 10 anos americano é a taxa de desconto do mundo; toda nota de estratégia global abre por ele"
        falar = ("o juro americano subiu: o bond em dólar marca para baixo e as ações de crescimento perdem múltiplo" if abriu
                 else "o juro americano caiu: bond em dólar valoriza e o apetite por risco melhora")
        estado.marcar("C07", ult[0])
        return [Alerta(self.id, "UST", sev, "curva", titulo, tag="abriu" if abriu else "fechou", data=ult[0], corpo=corpo,
                       por_que=por_que, como_falar=falar, fonte=f"Treasury.gov CMT {fmt.data_br(ult[0])}",
                       ativos_afetados=("IUAA ↓ · CNDX ↓ · RBOT ↓ · USD/BRL ↑" if abriu else "IUAA ↑ · CNDX ↑ · RBOT ↑ · USD/BRL ↓"),
                       dados={"deltas": deltas, "2s10s": s2s10})]


# ---------------------------------------------------------------- v1.1
def _serie_alinhada(hist_a: list[list], hist_b: list[list], idx: int = 1) -> list[tuple[str, float]]:
    """[(data, a - b)] nas datas comuns (taxas em %)."""
    b = {h[0]: h[idx] for h in hist_b if h[idx] is not None}
    return [(h[0], h[idx] - b[h[0]]) for h in hist_a if h[idx] is not None and h[0] in b]


def _extremo(vals: list[float], janela: int) -> str | None:
    sub = vals[-janela:]
    if len(sub) < 20:
        return None
    if vals[-1] >= max(sub):
        return "máxima"
    if vals[-1] <= min(sub):
        return "mínima"
    return None


def _niveis_pp(a: float, b: float, passo: float, banda: float) -> list[float]:
    """Multiplos de `passo` cruzados entre b (anterior) e a (atual), com banda em pp."""
    lo, hi = min(a, b), max(a, b)
    k = int(lo // passo) * passo
    out = []
    while k <= hi + passo:
        if b < k <= a - banda or b > k >= a + banda:
            out.append(round(k, 2))
        k += passo
    return out


class C02Inclinacao(Regra):
    id = "C02"
    familia = "curva"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("C02_INCLINACAO") or {}
        di = ctx.curvas.get("di") or {}
        ultimo = di.get("ultimo_pregao")
        if not di.get("historico") or not ultimo or ultimo < ctx.hoje.isoformat():
            return []
        if estado.ultima_data("C02") == ultimo:
            return []
        out, linhas, gatilhos, sev = [], [], [], "info"
        for longo, curto in (L.get("pares") or [["DI1F35", "DI1F28"], ["DI1F30", "DI1F28"]]):
            s = _serie_alinhada(_serie_di(ctx, longo), _serie_di(ctx, curto))
            if len(s) < 7:
                continue
            vals = [v * 100.0 for _, v in s]   # bps
            hoje_v, ont, v5 = vals[-1], vals[-2], vals[-6]
            d1, d5 = hoje_v - ont, hoje_v - v5
            rot = f"{longo[3:]}-{curto[3:]}"
            dl = _delta(_serie_di(ctx, longo)) or 0.0
            dc = _delta(_serie_di(ctx, curto)) or 0.0
            forma = ("bear steepening (longo abriu mais)" if d1 > 0 and dl > 0 else "bull steepening (curto fechou mais)" if d1 > 0
                     else "bull flattening (longo fechou mais)" if d1 < 0 and dl < 0 else "bear flattening (curto abriu mais)")
            linhas.append(f"{rot} {fmt.bps(hoje_v)} bps ({fmt.bps(d1)} dia · {fmt.bps(d5)} 5 pregões)")
            if abs(d1) >= L.get("bps_dia", 10):
                sev = "atencao"
                gatilhos.append(f"{rot} {fmt.bps(d1)} bps no dia: {forma}")
            elif abs(d5) >= L.get("bps_5d", 20):
                sev = "atencao"
                gatilhos.append(f"{rot} {fmt.bps(d5)} bps em 5 pregões")
            banda = float(L.get("banda_zero_bps", 2))
            if (ont > banda and hoje_v <= -banda) or (ont < -banda and hoje_v >= banda):
                sev = "atencao"
                gatilhos.append(f"{rot} {'inverteu' if hoje_v < 0 else 'desinverteu'} (cruzou zero)")
            ext = _extremo(vals, int(L.get("extremo_sessoes", 252)))
            if ext:
                gatilhos.append(f"{rot} na {ext} de {min(len(vals), int(L.get('extremo_sessoes', 252)))} pregões")
        if not gatilhos:
            return []
        estado.marcar("C02", ultimo)
        titulo = "Inclinação da curva DI: " + " · ".join(gatilhos[:3])
        por_que = "a inclinação separa o que é Copom (curto) do que é prêmio fiscal (longo); steepening com o curto parado é prêmio de risco, não juro"
        falar = "a curva mudou de forma, não só de nível: o prazo longo está pagando mais (ou menos) prêmio em relação ao curto"
        return [Alerta(self.id, "DI", sev, "curva", titulo, tag="inclinacao", data=ultimo, corpo=linhas, por_que=por_que,
                       como_falar=falar, fonte=f"B3 ajuste {fmt.data_br(ultimo)}", ativos_afetados="Tesouro Pré · IPCA+ longos · bancos",
                       dados={"gatilhos": gatilhos})]


class C03NiveisJuro(Regra):
    id = "C03"
    familia = "curva"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("C03_NIVEIS_JURO") or {}
        passo, banda = float(L.get("passo_pp", 0.5)), float(L.get("banda_bps", 3)) / 100.0
        ext_n = int(L.get("extremo_sessoes", 252))
        out = []
        di = ctx.curvas.get("di") or {}
        ultimo = di.get("ultimo_pregao")
        if di.get("historico") and ultimo and ultimo >= ctx.hoje.isoformat() and estado.ultima_data("C03:DI") != ultimo:
            gat, sev = [], "info"
            for v in (ctx.universo.curvas.get("di", {}).get("vertices") or []):
                h = _serie_di(ctx, v["codigo"])
                if len(h) < 2 or h[-1][1] is None or h[-2][1] is None:
                    continue
                for n in _niveis_pp(h[-1][1], h[-2][1], passo, banda):
                    sev = "atencao"
                    gat.append(f"{v['codigo'][3:]} cruzou {fmt.taxa(n)}% ({'para cima' if h[-1][1] > h[-2][1] else 'para baixo'}, agora {fmt.taxa(h[-1][1])}%)")
                ext = _extremo([x[1] for x in h if x[1] is not None], ext_n)
                if ext:
                    gat.append(f"{v['codigo'][3:]} na {ext} de {min(len(h), ext_n)} pregões: {fmt.taxa(h[-1][1])}%")
            if gat:
                estado.marcar("C03:DI", ultimo)
                out.append(Alerta(self.id, "DI", sev, "curva", "DI em nível: " + " · ".join(gat[:3]), tag="di", data=ultimo,
                                  corpo=gat[3:6], por_que="números redondos e extremos de um ano são onde o mercado revisa alocação; o DI de 2035 em nova máxima é o mercado cobrando prêmio fiscal",
                                  como_falar="a taxa cruzou um nível que o mercado observa; vale dizer o que mudou no cenário para justificar",
                                  fonte=f"B3 ajuste {fmt.data_br(ultimo)}", dados={"gatilhos": gat}))
        tes = (ctx.curvas.get("tesouro") or {})
        titulos = tes.get("titulos") or {}
        base = tes.get("data_base")
        if base and titulos and estado.ultima_data("C03:TD") != base:
            gat, sev = [], "info"
            for tid in (L.get("titulos_pre") or ["PRE2029", "PRE2031", "PRE2032"]):
                h = (titulos.get(tid) or {}).get("historico") or []
                if len(h) < 2 or h[-1][1] is None or h[-2][1] is None:
                    continue
                apelido = (titulos.get(tid) or {}).get("apelido", tid)
                for n in _niveis_pp(h[-1][1], h[-2][1], passo, banda):
                    sev = "atencao"
                    gat.append(f"{apelido} cruzou {fmt.taxa(n)}% (agora {fmt.taxa(h[-1][1])}%)")
                ext = _extremo([x[1] for x in h if x[1] is not None], ext_n)
                if ext:
                    gat.append(f"{apelido} na {ext} de {min(len(h), ext_n)} bases: {fmt.taxa(h[-1][1])}%")
            if gat:
                estado.marcar("C03:TD", base)
                out.append(Alerta(self.id, "TESOURO", sev, "curva", "Prefixado em nível: " + " · ".join(gat[:3]), tag="td", data=base,
                                  corpo=gat[3:6], por_que="o prefixado em número redondo é a taxa que o cliente memoriza; extremos de um ano mudam a conversa de alongamento",
                                  como_falar="o prefixado cruzou um nível referência; é o momento de rever se o prazo compensa o risco",
                                  fonte=f"Tesouro Transparente, base {fmt.data_br(base)}", dados={"gatilhos": gat}))
        return out


class C06Implicita(Regra):
    id = "C06"
    familia = "curva"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("C06_IMPLICITA") or {}
        tes = ctx.curvas.get("tesouro") or {}
        titulos, base = tes.get("titulos") or {}, tes.get("data_base")
        if not titulos or not base or estado.ultima_data("C06") == base:
            return []
        focus = (((ctx.macro.get("focus") or {}).get("expectativas") or {}).get("IPCA") or {}).get("por_ano") or {}
        linhas, gatilhos, sev = [], [], "info"
        passo, banda = float(L.get("passo_pp", 0.5)), float(L.get("banda_bps", 3)) / 100.0
        for be in (ctx.universo.curvas.get("tesouro", {}).get("breakevens") or []):
            hp = (titulos.get(be["pre"]) or {}).get("historico") or []
            hi = (titulos.get(be["ipca"]) or {}).get("historico") or []
            ipca_por_data = {h[0]: h[1] for h in hi if h[1] is not None}
            serie = [(h[0], ind.breakeven(h[1], ipca_por_data[h[0]])) for h in hp if h[1] is not None and h[0] in ipca_por_data]
            if len(serie) < 6:
                continue
            vals = [v for _, v in serie]
            hoje_v, ont, sem = vals[-1], vals[-2], vals[-6]
            d_sem = ind.bps(hoje_v, sem)
            rot = be.get("rotulo", "")
            ano = re.search(r"20\d\d", rot)
            ano_f = ano.group(0) if ano and ano.group(0) in focus else (max(focus) if focus else None)
            foc_txt, gap = "", None
            if ano_f:
                gap = ind.bps(hoje_v, focus[ano_f]["mediana"])
                foc_txt = f" vs Focus IPCA {ano_f} {fmt.taxa(focus[ano_f]['mediana'])}% ({fmt.bps(gap)} bps)"
            linhas.append(f"Implícita {rot}: {fmt.taxa(hoje_v)}% ({fmt.bps(d_sem)} bps na semana){foc_txt}")
            if d_sem is not None and abs(d_sem) >= L.get("bps_semana", 20):
                sev = "atencao"
                gatilhos.append(f"implícita {rot} {fmt.bps(d_sem)} bps na semana")
            for n in _niveis_pp(hoje_v, ont, passo, banda):
                sev = "atencao"
                gatilhos.append(f"implícita {rot} cruzou {fmt.taxa(n)}%")
            if gap is not None and abs(gap) >= L.get("bps_vs_focus_atencao", 150) and not any(rot in g for g in gatilhos):
                gatilhos.append(f"implícita {rot} {fmt.bps(gap)} bps acima do Focus" if gap > 0 else f"implícita {rot} {fmt.bps(gap)} bps abaixo do Focus")
        if not gatilhos:
            return []
        estado.marcar("C06", base)
        titulo = "Inflação implícita: " + " · ".join(gatilhos[:3])
        return [Alerta(self.id, "TESOURO", sev, "curva", titulo, tag="implicita", data=base, corpo=linhas,
                       por_que="a implícita é o IPCA que o mercado cobra para trocar IPCA+ por prefixado; acima do Focus, o prefixado paga prêmio; abaixo, o IPCA+ é o seguro barato",
                       como_falar="o prefixado embute uma inflação de X%; se o cliente acredita em menos que isso, o pré ganha; se acredita em mais, o IPCA+",
                       fonte=f"Tesouro Transparente base {fmt.data_br(base)}; BCB Focus", ativos_afetados="Tesouro Pré ↔ IPCA+",
                       dados={"gatilhos": gatilhos})]


class C082s10s(Regra):
    id = "C08"
    familia = "curva"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("C08_2S10S") or {}
        ust = ctx.curvas.get("ust") or {}
        h = ust.get("historico") or []
        if len(h) < 7:
            return []
        prazos = ust.get("prazos") or ["2y", "5y", "10y", "30y"]
        i2, i10 = prazos.index("2y") + 1, prazos.index("10y") + 1
        s = [(x[0], (x[i10] - x[i2]) * 100.0) for x in h if x[i2] is not None and x[i10] is not None]
        if len(s) < 7 or estado.ultima_data("C08") == s[-1][0]:
            return []
        vals = [v for _, v in s]
        hoje_v, ont, v5 = vals[-1], vals[-2], vals[-6]
        d1, d5 = hoje_v - ont, hoje_v - v5
        gat, sev = [], "info"
        if abs(d1) >= L.get("bps_dia", 10):
            sev = "atencao"
            gat.append(f"{fmt.bps(d1)} bps no dia")
        elif abs(d5) >= L.get("bps_5d", 20):
            sev = "atencao"
            gat.append(f"{fmt.bps(d5)} bps em 5 pregões")
        banda = float(L.get("banda_zero_bps", 2))
        if (ont > banda and hoje_v <= -banda) or (ont < -banda and hoje_v >= banda):
            sev = "atencao"
            gat.append("inverteu (cruzou zero)" if hoje_v < 0 else "desinverteu (voltou a positivo)")
        ext = _extremo(vals, int(L.get("extremo_sessoes", 252)))
        if ext:
            gat.append(f"na {ext} de {min(len(vals), int(L.get('extremo_sessoes', 252)))} pregões")
        if not gat:
            return []
        estado.marcar("C08", s[-1][0])
        titulo = f"UST 2s10s {fmt.bps(hoje_v)} bps: " + " · ".join(gat[:3]) + f" ({fmt.data_br(s[-1][0])})"
        return [Alerta(self.id, "UST", sev, "curva", titulo, tag="2s10s", data=s[-1][0],
                       corpo=[f"2y {fmt.taxa(h[-1][i2])} · 10y {fmt.taxa(h[-1][i10])}"],
                       por_que="a inclinação americana é o termômetro de ciclo: steepening com o 2y caindo é o mercado pedindo cortes; inversão prolongada precede desaceleração",
                       como_falar="a curva americana mudou de forma; o mercado está reprecificando o ritmo do Fed, e isso chega ao dólar e aos UCITS",
                       fonte=f"Treasury.gov CMT {fmt.data_br(s[-1][0])}", ativos_afetados="IUAA · IB01 · DXY · CNDX",
                       dados={"2s10s": hoje_v, "d1": d1, "d5": d5})]


REGRAS = [C01DIMovimento(), C04TesouroJuroReal(), C05TesouroVariacaoPU(), C07UST()]
REGRAS_V11 = [C02Inclinacao(), C03NiveisJuro(), C06Implicita(), C082s10s()]
