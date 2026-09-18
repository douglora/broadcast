"""Regras tecnicas de preco (v1.0): T01 MM200, T03 golden/death cross,
T04 maxima/minima de 52 semanas, T05 movimento anormal (z-score), T08 drawdown
por degraus, T13 regime de risco (VIX + score)."""

from __future__ import annotations

import math

import pandas as pd

from livro import fmt
from livro import indicadores as ind
from livro.sinais.base import Alerta, Contexto, Estado, Regra

CLASSES_PRECO = {"etf", "acao", "fx", "indice", "commodity", "cripto"}


def _ativos_preco(ctx: Contexto):
    for a in ctx.universo.ativos:
        if a.ativo and a.classe in CLASSES_PRECO and a.id in ctx.series and not a.proxy:
            yield a


def _datas(df: pd.DataFrame) -> list[str]:
    return [d.date().isoformat() for d in df.index]


def _banda(ctx: Contexto, a, regra: str, chave: str = "banda") -> float:
    if a.param("banda_mm") is not None:
        return float(a.param("banda_mm"))
    if a.classe == "cripto":
        return float(ctx.lim(regra, "banda_cripto", 0.01))
    return float(ctx.lim(regra, chave, 0.005))


def _ctx_janelas(df: pd.DataFrame) -> str:
    j = ind.janelas(df)
    return f"1m {fmt.pct(j.get('1m'))} · 6m {fmt.pct(j.get('6m'))} · YTD {fmt.pct(j.get('ytd'))}"


class T01MM200(Regra):
    id = "T01"
    familia = "preco"

    def avaliar(self, ctx, estado):
        out = []
        n = int(ctx.lim("T01_MM200", "janela", 200))
        conf = int(ctx.lim("T01_MM200", "confirmacao_sessoes", 2))
        atalho = float(ctx.lim("T01_MM200", "atalho_primeiro_dia", 0.02))
        cool = int(ctx.lim("T01_MM200", "cooldown_sessoes", 10))
        jan_incl = int(ctx.lim("T01_MM200", "inclinacao_janela", 20))
        for a in _ativos_preco(ctx):
            df = ctx.series[a.id]
            if len(df) < n + 2 or not ctx.fresco(a.id):
                continue
            s = df["adj"]
            m = ind.mm(s, n)
            if math.isnan(m.iloc[-1]):
                continue
            banda = _banda(ctx, a, "T01_MM200")
            dias = ind.dias_abaixo(s, m, banda)
            hoje = _datas(df)[-1]
            close, mm = float(df["close"].iloc[-1]), float(m.iloc[-1])
            dist = close / mm - 1.0
            lado = None
            if dias == conf or (dias == 1 and dist <= -atalho):
                lado = "perda"
            elif dias == -conf or (dias == -1 and dist >= atalho):
                lado = "retomada"
            if not lado:
                continue
            chave = f"T01:{a.id}:{lado}"
            if estado.em_cooldown(chave, _datas(df), cool):
                continue
            incl = ind.inclinacao(m, jan_incl) or 0.0
            sobe = incl > 0
            sev = "atencao" if (lado == "perda" and sobe) else "info"
            moeda = ctx.moeda_simbolo(a.id)
            if lado == "perda":
                titulo = (f"{ctx.rotulo(a.id)} fechou abaixo da média de 200 dias pela {abs(dias)}ª sessão: "
                          f"{moeda}{fmt.preco(close, a.decimais)} vs MM200 {moeda}{fmt.preco(mm, a.decimais)} ({fmt.pct(dist)})")
                por_que = ("é a linha que fundos sistemáticos usam para definir tendência; abaixo dela o fluxo vira vendedor"
                           + (f". A MM200 ainda sobe ({fmt.pct(incl)} em {jan_incl} sessões), o que torna a perda mais relevante" if sobe
                              else f". A MM200 já cai ({fmt.pct(incl)} em {jan_incl} sessões): confirma tendência de baixa, não é novidade"))
                falar = "o papel perdeu a referência de longo prazo; não é sinal de venda, é sinal de acompanhar o próximo suporte"
                anula = f"retomar {moeda}{fmt.preco(mm * (1 + banda), a.decimais)} em {conf} fechamentos"
            else:
                titulo = (f"{ctx.rotulo(a.id)} retomou a média de 200 dias pela {abs(dias)}ª sessão: "
                          f"{moeda}{fmt.preco(close, a.decimais)} vs MM200 {moeda}{fmt.preco(mm, a.decimais)} ({fmt.pct(dist)})")
                por_que = "voltar acima da MM200 reabre o papel para os modelos de tendência; o fluxo sistemático deixa de vender"
                falar = "o papel recuperou a referência de longo prazo; a tendência de baixa perdeu força"
                anula = f"perder {moeda}{fmt.preco(mm * (1 - banda), a.decimais)} em {conf} fechamentos"
            out.append(Alerta(self.id, a.id, sev, "preco", titulo, tag=lado, data=hoje,
                              corpo=[_ctx_janelas(df)], por_que=por_que, como_falar=falar, anula=anula,
                              fonte=f"Yahoo Finance fech. {fmt.data_br(hoje)}",
                              dados={"close": close, "mm200": mm, "dist": dist, "inclinacao": incl, "dias": dias}))
            estado.marcar(chave, hoje, close=close, mm200=mm)
        return out


class T03GoldenDeath(Regra):
    id = "T03"
    familia = "preco"

    def avaliar(self, ctx, estado):
        out = []
        curta = int(ctx.lim("T03_GOLDEN_DEATH", "curta", 50))
        longa = int(ctx.lim("T03_GOLDEN_DEATH", "longa", 200))
        spread_min = float(ctx.lim("T03_GOLDEN_DEATH", "spread_minimo", 0.0025))
        conf = int(ctx.lim("T03_GOLDEN_DEATH", "confirmacao_sessoes", 2))
        cool = int(ctx.lim("T03_GOLDEN_DEATH", "cooldown_sessoes", 60))
        for a in _ativos_preco(ctx):
            df = ctx.series[a.id]
            if len(df) < longa + 2 or not ctx.fresco(a.id):
                continue
            s = df["adj"]
            mc, ml = ind.mm(s, curta), ind.mm(s, longa)
            if math.isnan(ml.iloc[-1]):
                continue
            dias = ind.dias_abaixo(mc, ml, 0.0)
            spread = float(mc.iloc[-1] / ml.iloc[-1] - 1.0)
            hoje = _datas(df)[-1]
            if dias == conf and abs(spread) >= spread_min:
                lado, sev = "death", "atencao"
            elif dias == -conf and abs(spread) >= spread_min:
                lado, sev = "golden", "info"
            else:
                continue
            chave = f"T03:{a.id}"
            if estado.em_cooldown(chave, _datas(df), cool):
                continue
            close = float(df["close"].iloc[-1])
            moeda = ctx.moeda_simbolo(a.id)
            dist = close / float(ml.iloc[-1]) - 1.0
            j = ind.janelas(df)
            nome = "death cross" if lado == "death" else "golden cross"
            titulo = (f"{ctx.rotulo(a.id)} formou {nome}: MM{curta} {moeda}{fmt.preco(float(mc.iloc[-1]), a.decimais)} "
                      f"cruzou {'abaixo' if lado == 'death' else 'acima'} da MM{longa} {moeda}{fmt.preco(float(ml.iloc[-1]), a.decimais)} "
                      f"pela {conf}ª sessão; preço {moeda}{fmt.preco(close, a.decimais)}, {fmt.pct(dist)} da MM200, {fmt.pct(j.get('1a'))} em 12m")
            if lado == "death":
                por_que = "a tendência primária virou baixista pelo critério que fundos quantitativos e a imprensa usam"
                falar = "não é previsão de queda; é o mercado dizendo que a tendência de 6 meses ficou abaixo da de 1 ano"
            else:
                por_que = "a tendência primária virou altista pelo critério mais citado em research técnico"
                falar = "a média curta passou a curva longa: o movimento de recuperação ganhou corpo"
            out.append(Alerta(self.id, a.id, sev, "preco", titulo, tag=lado, data=hoje,
                              por_que=por_que, como_falar=falar,
                              fonte=f"Yahoo Finance fech. {fmt.data_br(hoje)}",
                              dados={"mm_curta": float(mc.iloc[-1]), "mm_longa": float(ml.iloc[-1]), "spread": spread}))
            estado.marcar(chave, hoje, lado=lado)
        return out


class T04MaxMin(Regra):
    id = "T04"
    familia = "preco"

    def avaliar(self, ctx, estado):
        out = []
        jan = int(ctx.lim("T04_MAX_MIN", "janela", 252))
        prog = float(ctx.lim("T04_MAX_MIN", "progresso_minimo", 0.03))
        cool = int(ctx.lim("T04_MAX_MIN", "cooldown_sessoes", 5))
        rsi_lim = float(ctx.lim("T04_MAX_MIN", "rsi_esticado", 75))
        for a in _ativos_preco(ctx):
            df = ctx.series[a.id]
            if len(df) < 60 or not ctx.fresco(a.id):
                continue
            s = df["close"]
            sub = s.iloc[-jan:]
            close = float(s.iloc[-1])
            hoje = _datas(df)[-1]
            lado = None
            if close >= float(sub.max()) and len(sub) >= 60:
                lado = "maxima"
            elif close <= float(sub.min()) and len(sub) >= 60:
                lado = "minima"
            if not lado:
                continue
            chave = f"T04:{a.id}:{lado}"
            ult = estado.get(chave) or {}
            if ult.get("nivel"):
                avanco = close / float(ult["nivel"]) - 1.0
                if (lado == "maxima" and avanco < prog) or (lado == "minima" and avanco > -prog):
                    if estado.em_cooldown(chave, _datas(df), cool) or abs(avanco) < prog:
                        continue
            rsi = ind.rsi_wilder(df["adj"])
            rsi_v = float(rsi.iloc[-1]) if not math.isnan(rsi.iloc[-1]) else None
            m200 = ind.mm(df["adj"], 200)
            dist200 = (float(df["adj"].iloc[-1] / m200.iloc[-1] - 1.0)) if len(df) >= 200 and not math.isnan(m200.iloc[-1]) else None
            j = ind.janelas(df)
            moeda = ctx.moeda_simbolo(a.id)
            serie_completa = len(sub) >= jan
            rot = "máxima de 52 semanas" if lado == "maxima" else "mínima de 52 semanas"
            if not serie_completa:
                rot = rot.replace("de 52 semanas", f"da série de {len(sub)} sessões")
            titulo = (f"{ctx.rotulo(a.id)} fechou na {rot}: {moeda}{fmt.preco(close, a.decimais)}, "
                      f"{fmt.pct(j.get('1m'))} em 1m e {fmt.pct(j.get('1a'))} em 12m")
            corpo = []
            if rsi_v is not None:
                corpo.append(f"RSI14 {fmt.num(rsi_v, 0)}" + (" (sobrecomprado)" if rsi_v >= rsi_lim else " (sobrevendido)" if rsi_v <= 100 - rsi_lim else "")
                             + (f", {fmt.pct(dist200)} da MM200" if dist200 is not None else ""))
            if lado == "maxima":
                sev = "info"
                por_que = ("máxima nova com RSI acima de 75 é momentum esticado: o mercado segue comprador, mas pausas ficam mais prováveis"
                           if rsi_v and rsi_v >= rsi_lim else "máxima de 52 semanas é o marco de momentum e de fluxo passivo mais usado")
                falar = "quem tem está bem; quem quer entrar tem melhor ponto quando o papel respirar"
            else:
                sev = "atencao"
                por_que = "mínima de 52 semanas antecipa revisão de tese: o mercado já não paga o que pagava há um ano"
                falar = "o papel está no menor nível em um ano; a pergunta é o que mudou na tese, não o preço"
            out.append(Alerta(self.id, a.id, sev, "preco", titulo, tag=lado, data=hoje, corpo=corpo,
                              por_que=por_que, como_falar=falar, fonte=f"Yahoo Finance fech. {fmt.data_br(hoje)}",
                              dados={"close": close, "rsi": rsi_v, "dist_mm200": dist200}))
            estado.marcar(chave, hoje, nivel=close)
        return out


class T05Zscore(Regra):
    id = "T05"
    familia = "preco"

    def avaliar(self, ctx, estado):
        out = []
        n = int(ctx.lim("T05_ZSCORE", "janela_sigma", 20))
        z_at = float(ctx.lim("T05_ZSCORE", "z_atencao", 2.5))
        z_cr = float(ctx.lim("T05_ZSCORE", "z_critico", 3.5))
        pisos_s = ctx.lim("T05_ZSCORE", "piso_sigma", {}) or {}
        pisos_r = ctx.lim("T05_ZSCORE", "piso_retorno", {}) or {}
        crit_r = ctx.lim("T05_ZSCORE", "retorno_critico", {}) or {}
        rep = int(ctx.lim("T05_ZSCORE", "repeticoes_regime", 3))
        jan_rep = int(ctx.lim("T05_ZSCORE", "janela_regime", 10))
        extra = float((ctx.regime or {}).get("acrescimo_sigma", 0.0))
        for a in _ativos_preco(ctx):
            df = ctx.series[a.id]
            if len(df) < n + 5 or not ctx.fresco(a.id):
                continue
            piso_s = float(a.param("piso_sigma", pisos_s.get(a.classe, 0.006)))
            piso_r = float(a.param("piso_retorno", pisos_r.get(a.classe, 0.015)))
            r_cr = float(crit_r.get(a.classe, 0.08))
            s = df["adj"]
            r = float(math.log(s.iloc[-1] / s.iloc[-2]))
            sig = ind.sigma_ex(s, n).iloc[-1]
            if math.isnan(sig):
                continue
            sig = max(float(sig), piso_s)
            z = r / sig
            if abs(z) < z_at + extra or abs(r) < piso_r:
                continue
            hoje = _datas(df)[-1]
            chave = f"T05:{a.id}"
            hist = estado.get(chave) or {}
            recentes = [d for d in hist.get("datas", []) if ind.pd.Timestamp(d) >= df.index[-jan_rep]]
            if len(recentes) >= rep:
                estado.set(chave, {"datas": (recentes + [hoje])[-10:], "regime": True})
                continue  # em regime de vol: vira linha, nao alerta
            sev = "critico" if (abs(z) >= z_cr + extra or abs(r) >= r_cr) else "atencao"
            vol = sig * math.sqrt(252)
            close = float(df["close"].iloc[-1])
            moeda = ctx.moeda_simbolo(a.id)
            ret = math.exp(r) - 1.0
            titulo = (f"{ctx.rotulo(a.id)} {fmt.pct(ret)} no dia a {moeda}{fmt.preco(close, a.decimais)}: "
                      f"movimento de {fmt.num(abs(z), 1)} desvios para uma vol de {n} dias de {fmt.pct(vol, 0, False)} a.a.")
            por_que = ("acima de 3 desvios o movimento sai do ruído e costuma vir de fato novo ou fluxo forçado"
                       if abs(z) >= 3 else "fora do padrão dos últimos 20 dias: vale procurar a causa antes de reagir")
            falar = ("o movimento de hoje é atípico para este papel; antes de mexer, saber o motivo"
                     if ret < 0 else "alta fora do padrão; costuma vir de notícia ou de fluxo, e parte dela pode devolver")
            out.append(Alerta(self.id, a.id, sev, "preco", titulo, tag="alta" if ret > 0 else "queda", data=hoje,
                              corpo=[_ctx_janelas(df)], por_que=por_que, como_falar=falar,
                              fonte=f"Yahoo Finance fech. {fmt.data_br(hoje)}",
                              dados={"retorno": ret, "z": z, "vol20": vol, "close": close}))
            estado.set(chave, {"datas": (hist.get("datas", []) + [hoje])[-10:], "data": hoje})
        return out


class T08Drawdown(Regra):
    id = "T08"
    familia = "preco"

    def avaliar(self, ctx, estado):
        out = []
        jan = int(ctx.lim("T08_DRAWDOWN", "janela", 252))
        padrao = ctx.lim("T08_DRAWDOWN", "degraus_padrao", [-10, -20, -30])
        banda = float(ctx.lim("T08_DRAWDOWN", "banda_pp", 0.5)) / 100.0
        rearme = float(ctx.lim("T08_DRAWDOWN", "rearme_pp", 5)) / 100.0
        for a in _ativos_preco(ctx):
            df = ctx.series[a.id]
            if len(df) < 60 or not ctx.fresco(a.id):
                continue
            degraus = sorted([float(x) / 100.0 for x in (a.param("degraus_drawdown") or padrao)], reverse=True)
            s = df["close"]
            dd, pico, data_pico = ind.drawdown(s, jan)
            dd_ant, _, _ = ind.drawdown(s.iloc[:-1], jan)
            if dd is None or dd_ant is None:
                continue
            hoje = _datas(df)[-1]
            chave = f"T08:{a.id}"
            st = estado.get(chave) or {}
            nivel_ativo = st.get("nivel")  # degrau ja alertado (fracao negativa)
            # rearme: se recuperou acima do degrau + 5pp, o degrau volta a valer
            if nivel_ativo is not None and dd > nivel_ativo + rearme:
                nivel_ativo = None
            disparo = None
            for deg in degraus:  # de -0.10 para -0.30
                if dd <= deg - banda and dd_ant > deg - banda:
                    if nivel_ativo is None or deg < nivel_ativo:
                        disparo = deg
            if disparo is None:
                if st.get("nivel") != nivel_ativo:
                    estado.set(chave, {**st, "nivel": nivel_ativo})
                continue
            close = float(s.iloc[-1])
            moeda = ctx.moeda_simbolo(a.id)
            j = ind.janelas(df)
            profundo = disparo <= -0.20
            sev = "critico" if profundo else "atencao"
            rot = "bear técnico" if disparo == -0.20 else "correção" if disparo == -0.10 else f"queda de {fmt.pct(disparo, 0, False)} do pico"
            titulo = (f"{ctx.rotulo(a.id)} entrou em {rot}: {fmt.pct(dd)} do pico de 52s "
                      f"({moeda}{fmt.preco(pico, a.decimais)} em {fmt.data_br(data_pico)}) a {moeda}{fmt.preco(close, a.decimais)}")
            corpo = [f"1m {fmt.pct(j.get('1m'))} · 6m {fmt.pct(j.get('6m'))} · 12m {fmt.pct(j.get('1a'))}"]
            bench = ctx.universo.serie_id(a.benchmark) if a.benchmark else None
            if bench is not None and a.benchmark in ctx.series:
                jb = ind.janelas(ctx.series[a.benchmark])
                corpo.append(f"{bench.nome if hasattr(bench, 'nome') else a.benchmark}: 1m {fmt.pct(jb.get('1m'))} · 6m {fmt.pct(jb.get('6m'))}: "
                             + ("a queda é do ativo, não do mercado" if (jb.get('6m') or 0) > (j.get('6m') or 0) + 0.10 else "o mercado caiu junto"))
            recuperar = 1.0 / (1.0 + dd) - 1.0
            por_que = (f"{fmt.pct(disparo, 0, False)} do pico é o limiar que a indústria chama de {rot}; recuperar o pico exige {fmt.pct(recuperar)}")
            falar = "o cliente sente a queda no extrato; a conversa é sobre a tese, não sobre o preço de hoje"
            out.append(Alerta(self.id, a.id, sev, "preco", titulo, tag=f"{int(disparo * 100)}", data=hoje, corpo=corpo,
                              por_que=por_que, como_falar=falar,
                              anula=f"rearma acima de {fmt.pct(disparo + rearme, 0, False)} do pico",
                              fonte=f"Yahoo Finance fech. {fmt.data_br(hoje)}",
                              dados={"dd": dd, "pico": pico, "data_pico": data_pico, "degrau": disparo}))
            estado.set(chave, {"nivel": disparo, "data": hoje})
        return out


class T13Regime(Regra):
    id = "T13"
    familia = "regime"

    def _var(self, ctx, id_, n=1):
        df = ctx.series.get(id_)
        if df is None or len(df) < n + 1:
            return None
        return float(df["close"].iloc[-1] / df["close"].iloc[-1 - n] - 1.0)

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("T13_REGIME") or {}
        comp = L.get("componentes") or {}
        vix_df = ctx.series.get("VIX")
        vix = float(vix_df["close"].iloc[-1]) if vix_df is not None and len(vix_df) else None
        vix_ant = float(vix_df["close"].iloc[-2]) if vix_df is not None and len(vix_df) > 1 else None
        vix_var = (vix / vix_ant - 1.0) if vix and vix_ant else None
        dxy = self._var(ctx, "DXY")
        brl = self._var(ctx, "USDBRL")
        btc = self._var(ctx, "BTC")
        ust10 = (ctx.curvas.get("ust") or {}).get("delta_bps", {}).get("10y")
        f35 = (ctx.curvas.get("di") or {}).get("delta_bps", {}).get("DI1F35")
        pontos = 0
        detalhes = []
        if vix is not None and (vix >= comp.get("vix_nivel", 20) or (vix_var or 0) >= comp.get("vix_var", 0.15)):
            pontos += 1
            detalhes.append(f"VIX {fmt.num(vix, 1)} ({fmt.pct(vix_var)})")
        if dxy is not None and dxy >= comp.get("dxy_var", 0.005):
            pontos += 1
            detalhes.append(f"DXY {fmt.pct(dxy)}")
        if ust10 is not None and ust10 >= comp.get("ust10_bps", 8):
            pontos += 1
            detalhes.append(f"UST 10y {fmt.bps(ust10)} bps")
        if brl is not None and brl >= comp.get("usdbrl_var", 0.01):
            pontos += 1
            detalhes.append(f"USD/BRL {fmt.pct(brl)}")
        if f35 is not None and f35 >= comp.get("di_f35_bps", 10):
            pontos += 1
            detalhes.append(f"F35 {fmt.bps(f35)} bps")
        if btc is not None and btc <= comp.get("btc_var", -0.04):
            pontos += 1
            detalhes.append(f"BTC {fmt.pct(btc)}")
        # regime de vol: VIX >= 25 ou 5+ ativos com vol20 >= 1,5x vol252
        rv = ctx.limiares.get("geral", {}).get("regime_vol", {})
        n_vol = 0
        for a in _ativos_preco(ctx):
            df = ctx.series[a.id]
            if len(df) < 260:
                continue
            v20 = ind.vol_anualizada(df["adj"], 20)
            v252 = ind.vol_anualizada(df["adj"], 252)
            if v20 and v252 and v20 >= rv.get("razao_vol", 1.5) * v252:
                n_vol += 1
        regime_vol = bool((vix is not None and vix >= rv.get("vix_minimo", 25)) or n_vol >= rv.get("ativos_minimos", 5))
        ctx.regime = {"vix": vix, "vix_var": vix_var, "score": pontos, "detalhes": detalhes, "regime_vol": regime_vol,
                      "ativos_vol_alta": n_vol, "acrescimo_sigma": rv.get("acrescimo_sigma", 0.5) if regime_vol else 0.0}
        out = []
        hoje = ctx.hoje.isoformat()
        st = estado.get("T13") or {}
        # VIX cruzando degraus
        if vix is not None and vix_ant is not None:
            for deg in L.get("vix_degraus", [20, 25, 30]):
                if vix_ant < deg <= vix and not estado.em_cooldown(f"T13:vix:{deg}", [hoje], 1):
                    if st.get(f"vix{deg}") != hoje:
                        sev = "critico" if deg >= 30 else "atencao"
                        out.append(Alerta(self.id, "VIX", sev, "regime",
                                          f"VIX cruzou {deg}: {fmt.num(vix, 1)} ({fmt.pct(vix_var)} no dia)", tag=f"vix{deg}", data=hoje,
                                          corpo=[", ".join(detalhes)] if detalhes else [],
                                          por_que="VIX acima de 20 é o mercado pagando por proteção; acima de 30 as correlações vão a 1 e o que manda é o tamanho da posição",
                                          como_falar="dia de aversão a risco: não é hora de decidir pelo preço de tela",
                                          fonte=f"Cboe via Yahoo, fech. {fmt.data_br(hoje)}", dados={"vix": vix}))
                        st[f"vix{deg}"] = hoje
        # score de risco
        mudou = pontos >= L.get("score_mudanca", 4) and (st.get("score_ontem", 0) or 0) < L.get("score_mudanca", 4)
        if mudou or pontos >= L.get("score_reforco", 5):
            if st.get("score_data") != hoje:
                sev = "critico" if pontos >= 6 else "atencao"
                out.append(Alerta(self.id, "MERCADO", sev, "regime",
                                  f"Dia de risk-off ({pontos}/6): " + " · ".join(detalhes), tag=f"score{pontos}", data=hoje,
                                  por_que="todos os canais de aversão ligados ao mesmo tempo: é venda de ativo de risco, não notícia setorial",
                                  como_falar="o dia foi de mercado, não de empresa; a carteira caiu junto com tudo",
                                  fonte=f"Yahoo, B3, Treasury.gov, fech. {fmt.data_br(hoje)}", dados={"score": pontos}))
                st["score_data"] = hoje
        st["score_ontem"] = pontos
        st["data"] = hoje
        estado.set("T13", st)
        return out


REGRAS = [T01MM200(), T03GoldenDeath(), T04MaxMin(), T05Zscore(), T08Drawdown(), T13Regime()]
