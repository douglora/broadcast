"""Regras de cambio, commodities e cripto (v1.0): F01 USD/BRL, F03 Brent, F06 BTC/ETH."""

from __future__ import annotations

import math

from livro import fmt
from livro import indicadores as ind
from livro.sinais.base import Alerta, Contexto, Estado, Regra


def _var(df, n=1):
    if df is None or len(df) <= n:
        return None
    return float(df["close"].iloc[-1] / df["close"].iloc[-1 - n] - 1.0)


def _niveis_cruzados(a: float, b: float, passo: float, banda: float) -> list[float]:
    """Niveis multiplos de `passo` entre b (anterior) e a (atual), com banda relativa."""
    out = []
    lo, hi = min(a, b), max(a, b)
    k = math.floor(lo / passo)
    while k * passo <= hi + 1e-9:
        nivel = round(k * passo, 6)
        if lo < nivel <= hi:
            if (a > b and a >= nivel * (1 + banda)) or (a < b and a <= nivel * (1 - banda)):
                out.append(nivel)
        k += 1
    return out


class F01USDBRL(Regra):
    id = "F01"
    familia = "cambio"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("F01_USDBRL") or {}
        df = ctx.series.get("USDBRL")
        if df is None or len(df) < 70 or not ctx.fresco("USDBRL"):
            return []
        hoje = df.index[-1].date().isoformat()
        if estado.ultima_data("F01") == hoje:
            return []
        r = _var(df)
        r5 = _var(df, 5)
        close, ant = float(df["close"].iloc[-1]), float(df["close"].iloc[-2])
        gatilhos, sev = [], "info"
        if r is not None and abs(r) >= L.get("var_critico", 0.025):
            sev = "critico"
            gatilhos.append(f"{fmt.pct(r)} no dia")
        elif r is not None and abs(r) >= L.get("var_atencao", 0.015):
            sev = "atencao"
            gatilhos.append(f"{fmt.pct(r)} no dia")
        if r5 is not None and abs(r5) >= L.get("var_5d", 0.03):
            sev = "atencao" if sev == "info" else sev
            gatilhos.append(f"{fmt.pct(r5)} em 5 sessões")
        niveis = _niveis_cruzados(close, ant, float(L.get("passo_nivel", 0.10)), float(L.get("banda", 0.003)))
        psico = {float(x) for x in L.get("niveis_psicologicos", [5.0, 5.5, 6.0])}
        for n in niveis:
            if n in psico:
                sev = "atencao" if sev == "info" else sev
                gatilhos.append(f"cruzou R$ {fmt.num(n)}")
            elif not gatilhos:
                gatilhos.append(f"cruzou R$ {fmt.num(n)}")
        # decomposicao domestica vs DXY
        dxy = ctx.series.get("DXY")
        dom = None
        if dxy is not None and len(dxy) > 60 and r is not None:
            rd = _var(dxy)
            b = ind.beta(df["close"], dxy["close"], int(L.get("beta_janela", 60)))
            if rd is not None:
                residuo = r - (b or 0.0) * rd
                if (abs(r) >= L.get("domestico_min_brl", 0.008) and abs(rd) >= L.get("domestico_min_dxy", 0.003) and (r > 0) != (rd > 0)) \
                        or abs(residuo) >= L.get("residuo_min", 0.01):
                    dom = f"DXY {fmt.pct(rd)} no dia: movimento doméstico (risco Brasil), resíduo {fmt.pct(residuo)}"
                    st = estado.get("F01:domestico") or {"dias": 0}
                    st["dias"] = st.get("dias", 0) + 1 if st.get("data") and ind.pd.Timestamp(st["data"]) >= df.index[-2] else 1
                    st["data"] = hoje
                    estado.set("F01:domestico", st)
                    if st["dias"] >= L.get("dias_domestico_critico", 3):
                        sev = "critico"
                        gatilhos.append(f"{st['dias']} dias seguidos de movimento doméstico")
                    elif sev == "info" and abs(r) >= 0.008:
                        sev = "atencao"
                        if not gatilhos:
                            gatilhos.append(f"{fmt.pct(r)} contra o dólar global")
                else:
                    dom = f"DXY {fmt.pct(rd)} no dia: movimento global"
        if not gatilhos:
            return []
        titulo = f"Real {'cai' if r and r > 0 else 'sobe'}: USD/BRL {fmt.num(close, 4)} ({' · '.join(gatilhos[:3])})"
        corpo = [dom] if dom else []
        ptax = ((ctx.macro.get("bcb") or {}).get("series") or {}).get("ptax_venda")
        if ptax:
            corpo.append(f"PTAX {fmt.data_br(ptax.get('data'))}: {fmt.num(ptax.get('valor'), 4)}")
        j = ind.janelas(df)
        corpo.append(f"1m {fmt.pct(j.get('1m'))} · 6m {fmt.pct(j.get('6m'))} · YTD {fmt.pct(j.get('ytd'))}")
        por_que = ("BRL e DI piorando juntos com DXY fraco é prêmio de risco Brasil; só reverte com sinal fiscal" if dom and "doméstico" in dom
                   else "separar dólar global de risco Brasil é a primeira resposta ao cliente quando o câmbio mexe")
        falar = ("o dólar subiu por Brasil, não pelo mundo: é prêmio de risco doméstico" if dom and "doméstico" in dom and r and r > 0
                 else "o câmbio acompanhou o dólar no mundo; não é notícia brasileira")
        estado.marcar("F01", hoje)
        return [Alerta(self.id, "USDBRL", sev, "cambio", titulo, tag="alta" if r and r > 0 else "queda", data=hoje, corpo=corpo,
                       por_que=por_que, como_falar=falar, fonte=f"Yahoo Finance {fmt.data_br(hoje)}; BCB PTAX",
                       ativos_afetados="UCITS em R$ " + ("↑" if r and r > 0 else "↓") + " · exportadoras (VALE3, KLBN4) " + ("↑" if r and r > 0 else "↓"),
                       dados={"close": close, "var": r, "var_5d": r5})]


class F03Brent(Regra):
    id = "F03"
    familia = "commodity"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("F03_BRENT") or {}
        df = ctx.series.get("BRENT")
        if df is None or len(df) < 30 or not ctx.fresco("BRENT"):
            return []
        hoje = df.index[-1].date().isoformat()
        if estado.ultima_data("F03") == hoje:
            return []
        r, r5 = _var(df), _var(df, 5)
        close, ant = float(df["close"].iloc[-1]), float(df["close"].iloc[-2])
        gatilhos, sev = [], "info"
        if r is not None and abs(r) >= L.get("var_critico", 0.05):
            sev = "critico"
            gatilhos.append(f"{fmt.pct(r)} no dia")
        elif r is not None and abs(r) >= L.get("var_atencao", 0.03):
            sev = "atencao"
            gatilhos.append(f"{fmt.pct(r)} no dia")
        if r5 is not None and abs(r5) >= L.get("var_5d", 0.08):
            sev = "atencao" if sev == "info" else sev
            gatilhos.append(f"{fmt.pct(r5)} em 5 sessões")
        for n in _niveis_cruzados(close, ant, float(L.get("passo_nivel", 10)), float(L.get("banda", 0.01))):
            sev = "atencao" if sev == "info" else sev
            gatilhos.append(f"cruzou US$ {fmt.num(n, 0)}")
        if not gatilhos:
            return []
        titulo = f"Brent {'sobe' if r and r > 0 else 'cai'} a US$ {fmt.num(close)} ({' · '.join(gatilhos[:3])})"
        corpo = []
        brl = ctx.series.get("USDBRL")
        if brl is not None and len(brl) > 1:
            em_reais = close * float(brl["close"].iloc[-1])
            ant_reais = ant * float(brl["close"].iloc[-2])
            corpo.append(f"Em reais: R$ {fmt.num(em_reais, 0)}/barril ({fmt.pct(em_reais / ant_reais - 1)})")
        for ativo in ("PETR4", "CVX", "UGPA3"):
            d = ctx.series.get(ativo)
            v = _var(d)
            if v is not None:
                corpo.append(f"{ativo} {fmt.pct(v)} no dia")
        por_que = ("queda do barril reduz receita de exportação e paridade de importação; PETR4 tende a cair menos pela política de preços" if r and r < 0
                   else "barril mais caro amplia receita em dólar das produtoras e pressiona o IPCA via combustíveis")
        falar = ("o petróleo caiu forte; para a Petrobras o efeito é diluído pela política de preços" if r and r < 0
                 else "o petróleo subiu: bom para Petrobras e Chevron, ruim para inflação e para a Ultrapar")
        estado.marcar("F03", hoje)
        seta = "↑" if r and r > 0 else "↓"
        return [Alerta(self.id, "BRENT", sev, "commodity", titulo, tag="alta" if r and r > 0 else "queda", data=hoje, corpo=corpo,
                       por_que=por_que, como_falar=falar, fonte=f"ICE via Yahoo {fmt.data_br(hoje)}",
                       ativos_afetados=f"PETR4 {seta} · CVX {seta} · UGPA3 {'↓' if seta == '↑' else '↑'}",
                       dados={"close": close, "var": r, "var_5d": r5})]


class F06Cripto(Regra):
    id = "F06"
    familia = "cripto"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("F06_CRIPTO") or {}
        out = []
        for cid in ("BTC", "ETH"):
            df = ctx.series.get(cid)
            if df is None or len(df) < 30:
                continue
            hoje = df.index[-1].date().isoformat()
            if estado.ultima_data(f"F06:{cid}") == hoje:
                continue
            r, r7 = _var(df), _var(df, 7)
            close, ant = float(df["close"].iloc[-1]), float(df["close"].iloc[-2])
            gatilhos, sev = [], "info"
            if r is not None and abs(r) >= L.get("var_critico", 0.12):
                sev = "critico"
                gatilhos.append(f"{fmt.pct(r)} em 24h")
            elif r is not None and abs(r) >= L.get("var_atencao", 0.07):
                sev = "atencao"
                gatilhos.append(f"{fmt.pct(r)} em 24h")
            if r7 is not None and abs(r7) >= L.get("var_7d", 0.15):
                sev = "atencao" if sev == "info" else sev
                gatilhos.append(f"{fmt.pct(r7)} em 7 dias")
            passo = float((L.get("passo_nivel") or {}).get(cid, 5000 if cid == "BTC" else 250))
            for n in _niveis_cruzados(close, ant, passo, float(L.get("banda", 0.01))):
                gatilhos.append(f"cruzou US$ {fmt.num(n, 0)}")
            # fim de semana: segunda de manha (slot manha) compara dom vs sex
            if ctx.slot == "manha" and ctx.hoje.weekday() == 0 and len(df) >= 4:
                dom, sex = df.iloc[-1], df.iloc[-3]
                rf = float(dom["close"] / sex["close"] - 1.0)
                lim = float((L.get("fim_de_semana") or {}).get(cid, 0.05))
                if abs(rf) >= lim:
                    sev = "atencao" if sev == "info" else sev
                    gatilhos.append(f"{fmt.pct(rf)} no fim de semana")
            if not gatilhos:
                continue
            titulo = f"{cid} {'sobe' if r and r > 0 else 'cai'} a US$ {fmt.num(close, 0)} ({' · '.join(gatilhos[:3])})"
            corpo = []
            cndx = ctx.series.get("CNDX")
            if cndx is not None and len(cndx) > 60:
                a = ind.retornos_log(df["adj"]).rename("a")
                b = ind.retornos_log(cndx["adj"]).rename("b")
                j = ind.pd.concat([a, b], axis=1).dropna().iloc[-60:]
                if len(j) > 30:
                    corpo.append(f"Correlação 60d com CNDX (Nasdaq 100): {fmt.num(float(j['a'].corr(j['b'])), 2)}")
            por_que = "cripto negocia 7 dias e é o termômetro de risco antes dos futuros; movimentos grandes contaminam CNDX e nomes de risco"
            falar = "é o ativo mais sensível ao apetite por risco do dia; mede o humor, não a tese"
            out.append(Alerta(self.id, cid, sev, "cripto", titulo, tag="alta" if r and r > 0 else "queda", data=hoje, corpo=corpo,
                              por_que=por_que, como_falar=falar, fonte=f"Yahoo Finance (fechamento UTC) {fmt.data_br(hoje)}",
                              dados={"close": close, "var": r, "var_7d": r7}))
            estado.marcar(f"F06:{cid}", hoje)
        return out


REGRAS = [F01USDBRL(), F03Brent(), F06Cripto()]
