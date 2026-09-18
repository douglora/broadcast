"""Regras de curva (v1.0): C01 DI movimento em bps, C04 Tesouro juro real por
grade, C05 Tesouro variacao de PU, C07 UST movimento e niveis.

Relogios: DI = ajuste B3 do pregao (publicado apos 18h BRT); Tesouro = data-base
do Tesouro Transparente (D-1 pela manha); UST = CMT do Treasury (fim da tarde
de NY). Nunca misturar os tres na mesma comparacao."""

from __future__ import annotations

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


REGRAS = [C01DIMovimento(), C04TesouroJuroReal(), C05TesouroVariacaoPU(), C07UST()]
