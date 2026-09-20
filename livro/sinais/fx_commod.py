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
        if estado.repetido_hoje("F01", hoje, float(df["close"].iloc[-1])):
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
        estado.marcar("F01", hoje, valor=close)
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
        if estado.repetido_hoje("F03", hoje, float(df["close"].iloc[-1])):
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
        estado.marcar("F03", hoje, valor=close)
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
            if estado.repetido_hoje(f"F06:{cid}", hoje, float(df["close"].iloc[-1])):
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
            estado.marcar(f"F06:{cid}", hoje, valor=close)
        return out


# ---------------------------------------------------------------- v1.1
class F02DXY(Regra):
    id = "F02"
    familia = "cambio"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("F02_DXY") or {}
        df = ctx.series.get("DXY")
        if df is None or len(df) < 210 or not ctx.fresco("DXY"):
            return []
        hoje = df.index[-1].date().isoformat()
        if estado.repetido_hoje("F02", hoje, float(df["close"].iloc[-1])):
            return []
        r, r5 = _var(df), _var(df, 5)
        close, ant = float(df["close"].iloc[-1]), float(df["close"].iloc[-2])
        gat, sev = [], "info"
        if r is not None and abs(r) >= L.get("var_atencao", 0.008):
            sev = "atencao"
            gat.append(f"{fmt.pct(r)} no dia")
        if r5 is not None and abs(r5) >= L.get("var_5d", 0.02):
            sev = "atencao"
            gat.append(f"{fmt.pct(r5)} em 5 sessões")
        for n in L.get("grade", [95, 100, 105, 110]):
            b = float(L.get("banda", 0.002))
            if ant < n <= close * (1 - b) or ant > n >= close * (1 + b):
                sev = "atencao"
                gat.append(f"cruzou {fmt.num(n, 0)}")
        m = ind.mm(df["adj"], int(L.get("mm_longa", 200)))
        cruz = ind.cruzou(df["adj"], m, 0.002)
        if cruz:
            gat.append(f"{'perdeu' if cruz == 'baixo' else 'retomou'} a MM200 ({fmt.num(float(m.iloc[-1]), 1)})")
        if not gat:
            return []
        estado.marcar("F02", hoje, valor=close)
        sobe = bool(r and r > 0)
        titulo = f"DXY {'sobe' if sobe else 'cai'} a {fmt.num(close, 2)} ({' · '.join(gat[:3])})"
        brl = ctx.series.get("USDBRL")
        corpo = []
        if brl is not None and len(brl) > 1:
            corpo.append(f"USD/BRL {fmt.pct(_var(brl))} no dia (real {'acompanhou' if (_var(brl) or 0) * (r or 0) > 0 else 'descolou'})")
        return [Alerta(self.id, "DXY", sev, "cambio", titulo, tag="alta" if sobe else "queda", data=hoje, corpo=corpo,
                       por_que="o DXY é o dólar contra o mundo: quando ele manda, o real segue por arrasto e os UCITS em dólar valem mais em reais",
                       como_falar=("o dólar subiu no mundo inteiro; o real cai por arrasto, não por Brasil" if sobe else "o dólar cedeu no mundo; alívio para o real e para os emergentes"),
                       fonte=f"ICE via Yahoo {fmt.data_br(hoje)}", ativos_afetados="USD/BRL " + ("↑" if sobe else "↓") + " · UCITS em R$ " + ("↑" if sobe else "↓") + " · EWY/MCHI " + ("↓" if sobe else "↑"),
                       dados={"close": close, "var": r, "var_5d": r5})]


class F04Minerio(Regra):
    id = "F04"
    familia = "commodity"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("F04_MINERIO") or {}
        df = ctx.series.get("MINERIO")
        if df is None or len(df) < 30:
            return []
        hoje = df.index[-1].date().isoformat()
        info = ctx.series_info.get("MINERIO") or {}
        if estado.repetido_hoje("F04", hoje, float(df["close"].iloc[-1])):
            return []
        r, r5 = _var(df), _var(df, 5)
        close, ant = float(df["close"].iloc[-1]), float(df["close"].iloc[-2])
        gat, sev = [], "info"
        if r is not None and abs(r) >= L.get("var_critico", 0.05):
            sev = "critico"
            gat.append(f"{fmt.pct(r)} no dia")
        elif r is not None and abs(r) >= L.get("var_atencao", 0.03):
            sev = "atencao"
            gat.append(f"{fmt.pct(r)} no dia")
        if r5 is not None and abs(r5) >= L.get("var_5d", 0.06):
            sev = "atencao" if sev == "info" else sev
            gat.append(f"{fmt.pct(r5)} em 5 sessões")
        for n in _niveis_cruzados(close, ant, float(L.get("passo_nivel", 10)), float(L.get("banda", 0.01))):
            sev = "atencao" if sev == "info" else sev
            gat.append(f"cruzou US$ {fmt.num(n, 0)}")
        if not gat:
            return []
        estado.marcar("F04", hoje, valor=close)
        sobe = bool(r and r > 0)
        titulo = f"Minério de ferro {'sobe' if sobe else 'cai'} a US$ {fmt.num(close)}/t ({' · '.join(gat[:3])}; barra de {fmt.data_br(hoje)})"
        corpo = ["Série: futuro CME liquidado no índice 62% Fe (TIO=F via Yahoo), não o físico Platts"]
        vale = ctx.series.get("VALE3")
        if vale is not None:
            corpo.append(f"VALE3 {fmt.pct(_var(vale))} no dia")
        dal = ((ctx.macro.get("proxies") or {}).get("proxies") or {}).get("DCE_I0")
        if dal and dal.get("preco"):
            corpo.append(f"Proxy Dalian {fmt.num(dal['preco'], 0)} CNY/t ({dal.get('data')})")
        return [Alerta(self.id, "MINERIO", sev, "commodity", titulo, tag="alta" if sobe else "queda", data=hoje, corpo=corpo,
                       por_que="o minério é 70% do EBITDA da Vale; US$ 10/t mudam a geração de caixa em bilhões de dólares por ano",
                       como_falar=("o minério subiu: a Vale ganha caixa, mas o mercado pergunta se a China sustenta" if sobe
                                   else "o minério caiu: pesa na Vale; a pergunta é se é estoque na China ou demanda"),
                       fonte=f"CME via Yahoo {fmt.data_br(hoje)}" + ("" if info.get("fresco", True) else " (barra anterior)"),
                       ativos_afetados="VALE3 " + ("↑" if sobe else "↓"), dados={"close": close, "var": r, "var_5d": r5})]


class F05BHKP(Regra):
    id = "F05"
    familia = "commodity"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("F05_BHKP") or {}
        prox = ctx.macro.get("proxies") or {}
        out = []
        hist = (prox.get("historico") or {}).get("SHFE_SP") or []
        if len(hist) >= 6 and hist[-1][1] and hist[-6][1]:
            data = hist[-1][0]
            var = hist[-1][1] / hist[-6][1] - 1.0
            if abs(var) >= L.get("proxy_semana", 0.03) and estado.ultima_data("F05:SHFE") != data:
                estado.marcar("F05:SHFE", data)
                out.append(Alerta(self.id, "BHKP", "info", "commodity",
                                  f"Celulose (proxy SHFE, fibra longa) {fmt.pct(var)} na semana: {fmt.num(hist[-1][1], 0)} CNY/t ({fmt.data_br(data)})",
                                  tag="proxy", data=data, corpo=["Proxy: contrato de celulose de fibra longa na SHFE, em CNY; NÃO é o BHKP (fibra curta) que Suzano e Klabin vendem"],
                                  por_que="o preço da celulose na China antecipa as listas de preço de Suzano e Klabin em 4 a 8 semanas",
                                  como_falar="a celulose na China moveu na semana; é sinal antecedente para Klabin, não o preço da Klabin",
                                  fonte=f"SHFE via Sina {fmt.data_br(data)}", ativos_afetados="KLBN4 " + ("↑" if var > 0 else "↓"),
                                  dados={"var_semana": var, "preco": hist[-1][1]}))
        bh = prox.get("bhkp_semanal") or {}
        ant = prox.get("bhkp_anterior") or {}
        if bh.get("valor") and ant.get("valor") and bh.get("data") != ant.get("data"):
            delta = float(bh["valor"]) - float(ant["valor"])
            if abs(delta) >= L.get("delta_usd_t", 20) and estado.ultima_data("F05:BHKP") != bh["data"]:
                estado.marcar("F05:BHKP", bh["data"])
                out.append(Alerta(self.id, "BHKP", "atencao", "commodity",
                                  f"BHKP {'sobe' if delta > 0 else 'cai'} US$ {fmt.num(abs(delta), 0)}/t na semana: US$ {fmt.num(bh['valor'], 0)}/t ({bh.get('fonte', '')}, {fmt.data_br(bh['data'])})",
                                  tag="semana", data=bh["data"], corpo=[f"Anterior: US$ {fmt.num(ant['valor'], 0)}/t em {fmt.data_br(ant['data'])}"],
                                  por_que="US$ 20/t na celulose de fibra curta é o passo que muda a lista de preço das produtoras",
                                  como_falar="a celulose fibra curta mudou de patamar na semana; Klabin e Suzano sentem no trimestre seguinte",
                                  fonte=f"{bh.get('fonte', 'registro manual')} {fmt.data_br(bh['data'])}", ativos_afetados="KLBN4 " + ("↑" if delta > 0 else "↓"),
                                  dados={"valor": bh["valor"], "delta": delta}))
        return out


REGRAS = [F01USDBRL(), F03Brent(), F06Cripto()]
REGRAS_V11 = [F02DXY(), F04Minerio(), F05BHKP()]
