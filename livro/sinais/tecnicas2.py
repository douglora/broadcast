"""Regras tecnicas v1.1: T02 MM50/MM100 (qualificadas pela MM200), T06 acumulado
de 5 sessoes, T07 RSI14 nos extremos, T09 volume anormal com preco, T10 forca
relativa contra o benchmark, T11 divergencia de pares, T12 sequencias."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from livro import fmt
from livro import indicadores as ind
from livro.sinais.base import Alerta, Contexto, Estado, Regra
from livro.sinais.tecnicas import _ativos_preco, _banda, _ctx_janelas, _datas


def _fonte(hoje: str) -> str:
    return f"Yahoo Finance fech. {fmt.data_br(hoje)}"


class T02MM50100(Regra):
    id = "T02"
    familia = "preco"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("T02_MM50_100") or {}
        curta, media = int(L.get("curta", 50)), int(L.get("media", 100))
        conf, cool = int(L.get("confirmacao_sessoes", 2)), int(L.get("cooldown_sessoes", 10))
        out = []
        for a in _ativos_preco(ctx):
            df = ctx.series[a.id]
            if len(df) < 205 or not ctx.fresco(a.id):
                continue
            s = df["adj"]
            m50, m100, m200 = ind.mm(s, curta), ind.mm(s, media), ind.mm(s, 200)
            if math.isnan(m200.iloc[-1]):
                continue
            banda = _banda(ctx, a, "T02_MM50_100")
            d50, d100 = ind.dias_abaixo(s, m50, banda), ind.dias_abaixo(s, m100, banda)
            gat = []
            if d50 == conf:
                gat.append(f"perdeu a MM{curta}")
            elif d50 == -conf:
                gat.append(f"retomou a MM{curta}")
            if d100 == conf:
                gat.append(f"perdeu a MM{media}")
            elif d100 == -conf:
                gat.append(f"retomou a MM{media}")
            if not gat:
                continue
            hoje = _datas(df)[-1]
            chave = f"T02:{a.id}"
            if estado.em_cooldown(chave, _datas(df), cool):
                continue
            close, mm200 = float(df["close"].iloc[-1]), float(m200.iloc[-1])
            acima200 = close > mm200
            perda = any(g.startswith("perdeu") for g in gat)
            sev = "atencao" if (perda and acima200 and len(gat) == 2) else "info"
            if perda:
                qual = "ainda acima da MM200 (tendência longa preservada)" if acima200 else "já abaixo da MM200 (confirma tendência de baixa)"
            else:
                qual = "acima da MM200 (tendência longa preservada)" if acima200 else "ainda abaixo da MM200 (repique dentro da baixa)"
            moeda = ctx.moeda_simbolo(a.id)
            titulo = f"{ctx.rotulo(a.id)} {' e '.join(gat)} pela {conf}ª sessão: {moeda}{fmt.preco(close, a.decimais)}, {qual}"
            corpo = [f"MM{curta} {moeda}{fmt.preco(float(m50.iloc[-1]), a.decimais)} · MM{media} {moeda}{fmt.preco(float(m100.iloc[-1]), a.decimais)} · MM200 {moeda}{fmt.preco(mm200, a.decimais)}",
                     _ctx_janelas(df)]
            por_que = ("as médias de 50 e 100 são os gatilhos de curto e médio prazo dos modelos de tendência; perder as duas com a MM200 preservada é correção dentro de alta"
                       if perda else "retomar a média curta é o primeiro sinal de que a correção acabou")
            falar = ("o papel corrige, mas a tendência longa está de pé; o nível a vigiar é a MM200" if (perda and acima200)
                     else "o papel acumula perda de referências; a leitura é de tendência de baixa" if perda
                     else "o papel voltou acima da média curta; o momento de curto prazo melhorou")
            out.append(Alerta(self.id, a.id, sev, "preco", titulo, tag="_".join(g.split()[0] for g in gat), data=hoje, corpo=corpo,
                              por_que=por_que, como_falar=falar, fonte=_fonte(hoje),
                              dados={"close": close, "mm50": float(m50.iloc[-1]), "mm100": float(m100.iloc[-1]), "mm200": mm200}))
            estado.marcar(chave, hoje)
        return out


class T06Acumulado(Regra):
    id = "T06"
    familia = "preco"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("T06_ACUMULADO_5D") or {}
        n, jan = int(L.get("sessoes", 5)), int(L.get("janela_sigma", 20))
        z_at, z_cr, cool = float(L.get("z_atencao", 2.5)), float(L.get("z_critico", 3.5)), int(L.get("cooldown_sessoes", 5))
        pisos = (ctx.limiares.get("T05_ZSCORE") or {}).get("piso_sigma") or {}
        out = []
        for a in _ativos_preco(ctx):
            df = ctx.series[a.id]
            if len(df) < jan + n + 2 or not ctx.fresco(a.id):
                continue
            s = df["adj"]
            r_n = ind.retorno_n(s, n)
            sig = ind.sigma_ex(s, jan)
            if r_n is None or sig.empty or math.isnan(sig.iloc[-1]):
                continue
            piso = float(a.param("piso_sigma") or pisos.get(a.classe, 0.0))
            sd = max(float(sig.iloc[-1]), piso) * math.sqrt(n)
            if sd == 0:
                continue
            z = math.log(1 + r_n) / sd
            if abs(z) < z_at:
                continue
            hoje = _datas(df)[-1]
            chave = f"T06:{a.id}"
            if estado.em_cooldown(chave, _datas(df), cool):
                continue
            sev = "critico" if abs(z) >= z_cr else "atencao"
            moeda = ctx.moeda_simbolo(a.id)
            close = float(df["close"].iloc[-1])
            titulo = (f"{ctx.rotulo(a.id)} {fmt.pct(r_n)} em {n} sessões a {moeda}{fmt.preco(close, a.decimais)}: "
                      f"movimento de {fmt.num(abs(z), 1)} desvios para a vol de {jan} dias")
            por_que = "o movimento acumulado da semana saiu do ruído mesmo sem um dia isolado extremo: costuma refletir reprecificação, não fluxo de um dia"
            falar = "o papel andou muito na semana; antes de comentar, achar o motivo (resultado, notícia, setor)"
            out.append(Alerta(self.id, a.id, sev, "preco", titulo, tag="alta" if r_n > 0 else "queda", data=hoje,
                              corpo=[_ctx_janelas(df)], por_que=por_que, como_falar=falar, fonte=_fonte(hoje),
                              dados={"retorno_5d": r_n, "z": z}))
            estado.marcar(chave, hoje)
        return out


class T07RSI(Regra):
    id = "T07"
    familia = "preco"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("T07_RSI") or {}
        n, alto, baixo, cool = int(L.get("janela", 14)), float(L.get("sobrecomprado", 75)), float(L.get("sobrevendido", 25)), int(L.get("cooldown_sessoes", 10))
        out = []
        for a in _ativos_preco(ctx):
            df = ctx.series[a.id]
            if len(df) < n + 5 or not ctx.fresco(a.id):
                continue
            rsi = ind.rsi_wilder(df["adj"], n)
            hoje_v, ontem_v = float(rsi.iloc[-1]), float(rsi.iloc[-2])
            if math.isnan(hoje_v) or math.isnan(ontem_v):
                continue
            if hoje_v >= alto and ontem_v < alto:
                lado = "sobrecomprado"
            elif hoje_v <= baixo and ontem_v > baixo:
                lado = "sobrevendido"
            else:
                continue
            hoje = _datas(df)[-1]
            chave = f"T07:{a.id}:{lado}"
            if estado.em_cooldown(chave, _datas(df), cool):
                continue
            moeda = ctx.moeda_simbolo(a.id)
            close = float(df["close"].iloc[-1])
            titulo = f"{ctx.rotulo(a.id)} entrou em {lado}: RSI{n} {fmt.num(hoje_v, 0)} a {moeda}{fmt.preco(close, a.decimais)}"
            por_que = ("RSI acima de 75 marca momento esticado: o mercado segue comprador, mas pausas ficam mais prováveis" if lado == "sobrecomprado"
                       else "RSI abaixo de 25 marca capitulação de curto prazo: o vendedor forçado costuma ter saído")
            falar = ("está esticado; quem quer entrar tem melhor ponto quando respirar" if lado == "sobrecomprado"
                     else "está sobrevendido; é o ponto em que a queda costuma perder força, não uma garantia de virada")
            out.append(Alerta(self.id, a.id, "info", "preco", titulo, tag=lado, data=hoje, corpo=[_ctx_janelas(df)],
                              por_que=por_que, como_falar=falar, fonte=_fonte(hoje), dados={"rsi": hoje_v}))
            estado.marcar(chave, hoje)
        return out


class T09Volume(Regra):
    id = "T09"
    familia = "preco"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("T09_VOLUME") or {}
        n, mult = int(L.get("mediana_sessoes", 20)), float(L.get("multiplo", 2.5))
        r_min, r_at, cool = float(L.get("retorno_minimo", 0.01)), float(L.get("retorno_atencao", 0.03)), int(L.get("cooldown_sessoes", 3))
        classes = set(L.get("classes") or ["acao", "etf"])
        blocos_x = set(L.get("blocos_excluidos") or ["ucits"])
        out = []
        for a in _ativos_preco(ctx):
            if a.classe not in classes or a.bloco in blocos_x:
                continue
            df = ctx.series[a.id]
            if len(df) < n + 2 or "volume" not in df or not ctx.fresco(a.id):
                continue
            vol = df["volume"].astype(float)
            med = float(vol.iloc[-n - 1:-1].median())
            v = float(vol.iloc[-1])
            if med <= 0 or v < mult * med:
                continue
            r = float(df["adj"].iloc[-1] / df["adj"].iloc[-2] - 1.0)
            if abs(r) < r_min:
                continue
            hoje = _datas(df)[-1]
            chave = f"T09:{a.id}"
            if estado.em_cooldown(chave, _datas(df), cool):
                continue
            sev = "atencao" if abs(r) >= r_at else "info"
            moeda = ctx.moeda_simbolo(a.id)
            close = float(df["close"].iloc[-1])
            titulo = (f"{ctx.rotulo(a.id)} {fmt.pct(r)} com volume {fmt.num(v / med, 1)}x a mediana de {n} sessões, "
                      f"a {moeda}{fmt.preco(close, a.decimais)}")
            por_que = "preço com volume é movimento com convicção: alguém grande mudou de posição; sem volume seria só ruído"
            falar = ("o papel subiu com volume forte: entrou dinheiro novo, não é só recompra de vendido" if r > 0
                     else "o papel caiu com volume forte: houve venda grande; olhar se saiu fato relevante ou notícia")
            out.append(Alerta(self.id, a.id, sev, "preco", titulo, tag="alta" if r > 0 else "queda", data=hoje,
                              corpo=[_ctx_janelas(df)], por_que=por_que, como_falar=falar, fonte=_fonte(hoje),
                              dados={"volume": v, "mediana": med, "retorno": r}))
            estado.marcar(chave, hoje)
        return out


class T10ForcaRelativa(Regra):
    id = "T10"
    familia = "preco"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("T10_FORCA_RELATIVA") or {}
        n, ext = int(L.get("janela", 20)), int(L.get("extremo_sessoes", 63))
        v_info, v_at, cool = float(L.get("variacao_info", 0.08)), float(L.get("variacao_atencao", 0.12)), int(L.get("cooldown_sessoes", 10))
        out = []
        for a in _ativos_preco(ctx):
            if not a.benchmark or a.benchmark == a.id:
                continue
            b = ctx.series.get(a.benchmark)
            df = ctx.series[a.id]
            if b is None or len(df) < ext + n + 2 or not ctx.fresco(a.id):
                continue
            rs = ind.forca_relativa(df["adj"], b["adj"])
            if len(rs) < ext + n + 1:
                continue
            var = ind.retorno_n(rs, n)
            if var is None or abs(var) < v_info:
                continue
            sub = rs.iloc[-ext:]
            extremo = "máximo" if rs.iloc[-1] >= sub.max() else ("mínimo" if rs.iloc[-1] <= sub.min() else None)
            if not extremo:
                continue
            hoje = _datas(df)[-1]
            chave = f"T10:{a.id}:{extremo}"
            if estado.em_cooldown(chave, _datas(df), cool):
                continue
            sev = "atencao" if abs(var) >= v_at else "info"
            ra, rb = ind.retorno_n(df["adj"], n), ind.retorno_n(b["adj"], n)
            bench = ctx.universo.serie_id(a.benchmark)
            nome_b = getattr(bench, "nome", a.benchmark) or a.benchmark
            titulo = (f"{ctx.rotulo(a.id)} no {extremo} de força relativa em {ext} sessões contra {a.benchmark}: "
                      f"{fmt.pct(ra)} vs {fmt.pct(rb)} em {n} sessões ({fmt.pct(var)} relativo)")
            por_que = ("descolar do benchmark é o que separa história própria de movimento de mercado; no máximo relativo, o papel lidera o grupo" if extremo == "máximo"
                       else "no mínimo relativo, o papel é o pior do grupo: ou há fato próprio ou o mercado o elegeu como funding")
            falar = (f"o papel está andando mais que o {a.benchmark}; a pergunta é o que justifica" if extremo == "máximo"
                     else f"o papel fica para trás do {a.benchmark}; o problema é específico, não de mercado")
            out.append(Alerta(self.id, a.id, sev, "preco", titulo, tag=extremo, data=hoje,
                              corpo=[f"Benchmark: {nome_b}", _ctx_janelas(df)], por_que=por_que, como_falar=falar,
                              fonte=_fonte(hoje), dados={"rs_var": var, "ret_ativo": ra, "ret_bench": rb}))
            estado.marcar(chave, hoje)
        return out


class T11Pares(Regra):
    id = "T11"
    familia = "preco"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("T11_PARES") or {}
        n, hist = int(L.get("janela", 20)), int(L.get("historico", 252))
        z_min, z_at, conf, cool = float(L.get("z_minimo", 2.0)), float(L.get("z_atencao", 3.0)), int(L.get("confirmacao_sessoes", 2)), int(L.get("cooldown_sessoes", 10))
        out = []
        for par in ctx.universo.pares or []:
            ia, ib = par.get("a"), par.get("b")
            da, db = ctx.series.get(ia), ctx.series.get(ib)
            if da is None or db is None or not ctx.fresco(ia):
                continue
            rs = ind.forca_relativa(da["adj"], db["adj"])
            if len(rs) < hist + n + conf:
                continue
            var = rs.pct_change(n).dropna()
            base = var.iloc[-hist:]
            mu, sd = float(base.mean()), float(base.std())
            if sd == 0 or math.isnan(sd):
                continue
            z = (var - mu) / sd
            ult = z.iloc[-conf:]
            if not (all(ult >= z_min) or all(ult <= -z_min)):
                continue
            zv = float(z.iloc[-1])
            hoje = _datas(da)[-1]
            chave = f"T11:{ia}:{ib}"
            if estado.em_cooldown(chave, _datas(da), cool):
                continue
            sev = "atencao" if abs(zv) >= z_at else "info"
            ra, rb = ind.retorno_n(da["adj"], n), ind.retorno_n(db["adj"], n)
            rot_b = ctx.rotulo(ib) if ctx.universo.por_id(ib) else ib
            lado = "à frente de" if zv > 0 else "atrás de"
            titulo = (f"{ctx.rotulo(ia)} descolou {lado} {rot_b}: {fmt.pct(ra)} vs {fmt.pct(rb)} em {n} sessões "
                      f"(z {fmt.num(zv, 1)} em {hist} sessões, {conf}º dia)")
            tipo = par.get("tipo", "")
            por_que = {"produtor_commodity": "produtor e commodity andam juntos no médio prazo; o descolamento ou antecipa a commodity ou embute fato da empresa",
                       "distribuidor_commodity": "o distribuidor ganha margem quando o insumo cai; descolar do Brent mostra se o mercado precifica isso",
                       "pares_setor": "dois nomes do mesmo setor, com o mesmo pano de fundo macro, descolando é história própria: resultado, guidance, evento",
                       "holding": "holding e controlada convergem; o desconto que abre demais costuma fechar",
                       "acao_indice": "ação e índice do setor divergindo é sinal de fluxo específico",
                       "etf_indice": "ETF descolando do índice local é câmbio ou fluxo estrangeiro, não a bolsa do país",
                       "etf_acao": "o ETF do país e a maior ação divergindo mostra se o tema é a China ou a empresa",
                       "etf_etf": "o Nasdaq descolando do S&P mede o apetite por crescimento contra o resto",
                       "exportador_cambio": "exportadora e câmbio: se o real cai e a ação não sobe, o mercado vê custo ou volume pior",
                       "cripto": "BTC e ETH divergindo mede se o dinheiro busca beta ou reserva"}.get(tipo, "os dois ativos costumam andar juntos; o descolamento pede explicação")
            falar = f"{ia} e {ib} costumam andar juntos e descolaram nas últimas {n} sessões; vale entender o motivo antes de comentar"
            out.append(Alerta(self.id, ia, sev, "preco", titulo, tag=f"{ib}_{'acima' if zv > 0 else 'abaixo'}", data=hoje,
                              corpo=[_ctx_janelas(da)], por_que=por_que, como_falar=falar, fonte=_fonte(hoje),
                              ativos_afetados=f"{ia} · {ib}", dados={"z": zv, "ret_a": ra, "ret_b": rb, "par": [ia, ib], "tipo": tipo}))
            estado.marcar(chave, hoje)
        return out


class T12Sequencia(Regra):
    id = "T12"
    familia = "preco"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("T12_SEQUENCIA") or {}
        degraus = sorted(int(x) for x in (L.get("degraus") or [6, 8, 10]))
        tol, cool = float(L.get("tolerancia", 0.0005)), int(L.get("cooldown_sessoes", 3))
        out = []
        for a in _ativos_preco(ctx):
            df = ctx.series[a.id]
            if len(df) < max(degraus) + 2 or not ctx.fresco(a.id):
                continue
            n, acum = ind.sequencia(df["adj"], tol)
            if abs(n) not in degraus:
                continue
            hoje = _datas(df)[-1]
            chave = f"T12:{a.id}:{abs(n)}"
            if estado.ultima_data(chave) == hoje or estado.em_cooldown(chave, _datas(df), cool):
                continue
            sev = "info" if abs(n) == degraus[0] else "atencao"
            moeda = ctx.moeda_simbolo(a.id)
            close = float(df["close"].iloc[-1])
            lado = "altas" if n > 0 else "quedas"
            titulo = f"{ctx.rotulo(a.id)}: {abs(n)} {lado} seguidas ({fmt.pct(acum)} acumulado) a {moeda}{fmt.preco(close, a.decimais)}"
            por_que = "sequências longas são raras e concentram o risco de reversão; a partir de 8 o mercado costuma comentar"
            falar = (f"são {abs(n)} altas seguidas; o movimento está maduro, o próximo dia de realização não muda a tese" if n > 0
                     else f"são {abs(n)} quedas seguidas; costuma vir um repique técnico, mas é repique, não virada")
            out.append(Alerta(self.id, a.id, sev, "preco", titulo, tag=f"{lado}_{abs(n)}", data=hoje, corpo=[_ctx_janelas(df)],
                              por_que=por_que, como_falar=falar, fonte=_fonte(hoje), dados={"n": n, "acumulado": acum}))
            estado.marcar(chave, hoje)
        return out


REGRAS = [T02MM50100(), T06Acumulado(), T07RSI(), T09Volume(), T10ForcaRelativa(), T11Pares(), T12Sequencia()]
