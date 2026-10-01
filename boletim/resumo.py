"""Resumo do pregao: os numeros do boletim com fonte e data, cruzados com o livro, e os sinais.

Entra o bruto de boletim/coleta.py; sai `resumo.json` (e a entrada do pregao no historico
compacto, que sustenta media de 20 pregoes e variacao de um dia para o outro).

Regras da casa que este modulo cumpre:
- Nenhum numero sem fonte e data: cada bloco leva `fonte` (tabela ou arquivo da B3) e a data
  a que o numero se refere, que nem sempre e a do pregao (o fluxo por investidor sai com dois
  pregoes de atraso; a carteira de indice vale por quadrimestre).
- Lacuna declarada, nunca placeholder: o que a B3 ainda nao publicou vai para `pendentes`
  com a situacao que ela informa; o que nao existe no boletim vai para `lacunas`.
- A sessao nao calcula regra: os sinais saem daqui, com os limiares de config/boletim.yaml.
- Nada de "compre/venda" (Resolucao CVM 178): sinal e fato com numero, nao recomendacao.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import date

from livro import relogios

from boletim import FONTE, b3, renda_fixa
from boletim import mercado as mkt       # `mercado` aqui embaixo e a funcao do giro do dia

RX_FUTURO = re.compile(r"^([A-Z0-9]{3})([FGHJKMNQUVXZ])(\d{2})$")
RX_ATE = re.compile(r"at[ée] o dia (\d{2})/(\d{2})/(\d{4})", re.I)
TIPOS_INVESTIDOR = (("estrangeiro", "estrangeiro"), ("institucional", "institucionais"),
                    ("pessoa_fisica", "individuais"), ("inst_financeira", "instituicoes financeiras"),
                    ("outros", "outros"))
GENERICAS = {"BANCO", "MERCADO", "ISHARES", "INVESTO", "CIA", "COMPANHIA"}
# sinais que saem todo pregao por natureza: sao a leitura do dia, nao um estado que se arrasta
DIARIOS = {"fluxo_estrangeiro", "lista_do_dia"}
NOME_LISTA = {"maiores_altas_ibov": "maiores altas do Ibovespa", "maiores_baixas_ibov": "maiores baixas do Ibovespa",
              "maiores_altas_mercado": "maiores altas do mercado", "maiores_baixas_mercado": "maiores baixas do mercado",
              "mais_negociadas": "mais negociadas à vista", "opcoes_compra_mais_negociadas": "calls mais negociadas",
              "opcoes_venda_mais_negociadas": "puts mais negociadas", "termo_mais_negociadas": "mais negociadas a termo"}
LACUNAS_FIXAS = [
    "Posição em aberto de derivativos por tipo de investidor (estrangeiro, institucional, pessoa física): "
    "não existe no Boletim Diário do Mercado; procurado nas 69 tabelas e no texto dos 11 cadernos em 30/09/2026.",
    "Fluxo por tipo de investidor sai acumulado no mês e com dois pregões de atraso; o saldo de um dia é a "
    "diferença entre dois acumulados seguidos.",
]


def r2(v, casas: int = 2):
    return None if v is None else round(v, casas)


def pct(novo, velho):
    if novo is None or not velho:
        return None
    return round((novo / velho - 1.0) * 100.0, 2)


def mil(v, casas: int = 0) -> str:
    """1234567.8 -> '1.234.568' (milhar com ponto, decimal com virgula)."""
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def brp(v, casas: int = 2) -> str:
    """Percentual com sinal, no formato brasileiro: 1.5 -> '+1,50%'."""
    return f"{v:+.{casas}f}%".replace(".", ",")


def dm(iso) -> str:
    return f"{str(iso)[8:10]}/{str(iso)[5:7]}" if iso else "?"


def media(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


class Contexto:
    def __init__(self, bruto: dict, cfg: dict, livro: list[dict], hist: dict, series_dir: str | None = None):
        self.bruto, self.cfg, self.livro, self.series_dir = bruto, cfg, livro, series_dir
        self.hist = hist
        self.d = date.fromisoformat(bruto["pregao"])
        self.iso = bruto["pregao"]
        self.lim = cfg.get("limiares") or {}
        self.ids = [a["id"] for a in livro]
        self.pendentes: dict = {}
        self.atrasadas: list = []
        self.lacunas: list = []
        self.sinais: list = []
        # pregoes anteriores, do mais novo para o mais velho
        self.antes = [(k, v) for k, v in sorted((hist.get("pregoes") or {}).items(), reverse=True) if k < self.iso]
        self.trades: dict = {}
        self.cad: dict = {}
        self.opc_cad: dict = {}          # {ativo-objeto: {codigo da opcao: (tipo, vencimento, strike, estilo)}} do livro e extras
        self.opc_todas: dict = {}        # {codigo da opcao: (ativo-objeto, tipo, vencimento, strike)} do mercado inteiro
        self.pos: dict = {}
        self.pos_anterior: dict = {r["TckrSymb"]: r for r in bruto.get("pos_anterior") or []}
        self.mudancas_oi: list = []
        self.rf_estado: dict = {}
        self.isin: dict = {}

    # ---- acesso ao bruto
    def tab(self, nome: str):
        t = self.bruto["tabelas"].get(nome)
        if t is None:
            self.pendentes[nome] = "falhou: " + (self.bruto["index"]["falhas"].get(nome) or "sem resposta")
            return None
        if t["situacao"] in b3.PRONTA:
            return t
        # a B3 marca como atrasada a tabela que saiu depois do prazo; se trouxe linhas, vale
        if t["situacao"] == "atrasado" and any(True for _ in b3.folhas(t)):
            if nome not in self.atrasadas:
                self.atrasadas.append(nome)
            return t
        self.pendentes[nome] = t["situacao"]
        return None

    def arq(self, nome: str):
        regs = self.bruto["arquivos"].get(nome)
        if regs is None:
            self.pendentes[nome] = "falhou: " + (self.bruto["index"]["falhas"].get(nome) or "sem resposta")
        return regs

    def fonte(self, nome: str, data: str | None = None) -> dict:
        t = self.bruto["tabelas"].get(nome) or {}
        a = self.bruto["index"]["arquivos"].get(nome) or {}
        return {"tabela": nome, "data": data or self.iso,
                "atualizado_em": t.get("atualizado_em"), "situacao": t.get("situacao") or a.get("estado")}

    # ---- historico
    def anterior(self, *chaves, n: int = 1):
        """Valor de `chaves` no n-esimo pregao anterior que o tenha. Devolve (data, valor)."""
        achados = 0
        for k, v in self.antes:
            x = v
            for c in chaves:
                x = x.get(c) if isinstance(x, dict) else None
                if x is None:
                    break
            if x is not None:
                achados += 1
                if achados == n:
                    return k, x
        return None, None

    def serie(self, *chaves, n: int = 20) -> list:
        out = []
        for _, v in self.antes:
            x = v
            for c in chaves:
                x = x.get(c) if isinstance(x, dict) else None
                if x is None:
                    break
            if x is not None:
                out.append(x)
            if len(out) >= n:
                break
        return out

    def sinal(self, tipo: str, ativo: str | None, texto: str, fonte: str, data: str | None = None, **nums):
        self.sinais.append({"tipo": tipo, "ativo": ativo, "texto": texto,
                            "fonte": fonte, "data": data or self.iso, "numeros": nums})


# ------------------------------------------------------------------ negocios e cadastro

def negocios(ctx: Contexto) -> dict:
    regs = ctx.arq("TradeInformationConsolidated")
    if regs is None:
        return {}
    ctx.trades = {r["TckrSymb"]: r for r in regs}
    out = {}
    for tk in ctx.ids:
        r = ctx.trades.get(tk)
        if not r or r.get("SgmtNm") != "CASH":
            continue
        ctx.isin[tk] = r.get("ISIN")
        vol = b3.num(r.get("NtlFinVol"))
        item = {"fechamento": b3.num(r.get("LastPric")), "oscilacao_pct": b3.num(r.get("OscnPctg")),
                "minimo": b3.num(r.get("MinPric")), "maximo": b3.num(r.get("MaxPric")),
                "medio": b3.num(r.get("TradAvrgPric")), "negocios": b3.num(r.get("TradQty")),
                "quantidade": b3.num(r.get("FinInstrmQty")), "volume_rs": vol}
        vols = ctx.serie("ativos", tk, "vol", n=20)
        item["pregoes_na_media"] = len(vols)
        if len(vols) >= ctx.lim.get("volume_base_minima", 10):
            m = media(vols)
            item["volume_media_rs"] = r2(m, 0)
            item["volume_x_media"] = r2(vol / m) if vol and m else None
            if (item["volume_x_media"] and item["volume_x_media"] >= ctx.lim.get("volume_x_media", 2.0)
                    and vol >= ctx.lim.get("volume_sinal_minimo_rs", 5e6)):
                ctx.sinal("volume_anormal", tk,
                          f"{tk} girou {mil(item['volume_x_media'], 1)}x a média de {len(vols)} pregões "
                          f"(R$ {mil(vol / 1e6)} mi contra R$ {mil(m / 1e6)} mi), com o preço em {brp(item['oscilacao_pct'])} no dia.",
                          "TradeInformationConsolidated", volume_rs=vol, media_rs=r2(m, 0), oscilacao_pct=item["oscilacao_pct"])
        _, f5 = ctx.anterior("ativos", tk, "fech", n=5)
        item["var_5d_pct"] = pct(item["fechamento"], f5)
        out[tk] = item
    return out


def cadastro(ctx: Contexto) -> dict:
    regs = ctx.arq("InstrumentsConsolidated")
    if regs is None:
        return {}
    alvo = set(ctx.ids)
    extras = set(ctx.cfg.get("opcoes_extras") or [])
    out = {}
    for r in regs:
        tk, cat = r.get("TckrSymb"), r.get("SctyCtgyNm")
        if cat in ("OPTION ON EQUITIES", "OPTION ON INDEX"):
            under = r.get("Asst")
            tipo = "call" if r.get("SgmtNm") == "EQUITY CALL" else "put"
            venc, strike = r.get("XprtnDt"), b3.num(r.get("ExrcPric"))
            ctx.opc_todas[tk] = (under, tipo, venc, strike)
            if under in alvo or under in extras:
                ctx.opc_cad.setdefault(under, {})[tk] = (tipo, venc, strike, r.get("OptnStyle"))
        elif tk in alvo and r.get("SgmtNm") == "CASH":
            ctx.cad[tk] = r
            ctx.isin.setdefault(tk, r.get("ISIN"))
            out[tk] = {"empresa": (r.get("CrpnNm") or "").strip(), "especificacao": " ".join((r.get("SpcfctnCd") or "").split()),
                       "categoria": cat, "isin": r.get("ISIN"), "quantidade_emitida": b3.num(r.get("MktCptlstn"))}
    return out


# ------------------------------------------------------------------ opcoes

def _dor_maxima(calls: dict, puts: dict):
    """Preco de exercicio em que os titulares, somados, recebem menos no vencimento."""
    strikes = sorted(set(calls) | set(puts))
    if len(strikes) < 3:
        return None
    melhor, menor = None, None
    for s in strikes:
        dor = sum(q * (s - k) for k, q in calls.items() if s > k) + sum(q * (k - s) for k, q in puts.items() if s < k)
        if menor is None or dor < menor:
            melhor, menor = s, dor
    return melhor


def opcoes(ctx: Contexto, neg: dict, ind: dict) -> tuple[dict, dict]:
    """Opcoes por ativo-objeto: (do livro, extras como IBOV e BOVA11)."""
    regs = ctx.arq("DerivativesOpenPosition")
    if regs is not None:
        ctx.pos = {r["TckrSymb"]: r for r in regs}
    lim = ctx.lim
    n_venc, n_strikes = lim.get("opcoes_vencimentos", 2), lim.get("opcoes_strikes", 5)
    grade_pct, grade_n = lim.get("opcoes_grade_pct", 20.0), lim.get("opcoes_grade_strikes", 25)
    do_livro, extras = {}, {}
    for tk, series in ctx.opc_cad.items():
        fech = (neg.get(tk) or {}).get("fechamento")
        if fech is None and tk.startswith("IBOV"):          # opcao sobre o indice: o preco e o Ibovespa em pontos
            fech = (ind.get("IBOVESPA") or {}).get("fechamento")
        if fech is None:
            r = ctx.trades.get(tk)
            fech = b3.num(r.get("LastPric")) if r and r.get("SgmtNm") == "CASH" else None
        por_venc: dict = {}
        tot = {"call": 0.0, "put": 0.0}
        desc = {"call": 0.0, "put": 0.0}
        vol = {"call": 0.0, "put": 0.0}
        nneg = {"call": 0.0, "put": 0.0}
        negociadas = []
        for cod, (tipo, venc, strike, _estilo) in series.items():
            t = ctx.trades.get(cod)
            p = ctx.pos.get(cod)
            oi = b3.num(p.get("TtlPos")) if p else None
            if t and b3.num(t.get("TradQty")):
                v = b3.num(t.get("NtlFinVol")) or 0.0
                vol[tipo] += v
                nneg[tipo] += b3.num(t.get("TradQty")) or 0.0
                negociadas.append({"codigo": cod, "tipo": tipo, "vencimento": venc, "strike": strike,
                                   "ultimo": b3.num(t.get("LastPric")), "oscilacao_pct": b3.num(t.get("OscnPctg")),
                                   "volume_rs": v, "negocios": b3.num(t.get("TradQty")), "posicao": oi})
            if not oi or not venc or venc < ctx.iso or strike is None:
                continue
            tot[tipo] += oi
            desc[tipo] += b3.num(p.get("UcvrdQty")) or 0.0
            v = por_venc.setdefault(venc, {"call": {}, "put": {}})
            v[tipo][strike] = v[tipo].get(strike, 0.0) + oi
        item = {"preco": fech, "volume_call_rs": r2(vol["call"], 0), "volume_put_rs": r2(vol["put"], 0),
                "negocios_call": nneg["call"], "negocios_put": nneg["put"],
                "mais_negociadas": sorted(negociadas, key=lambda x: -x["volume_rs"])[:6]}
        if regs is not None:
            item.update(posicao_call=tot["call"], posicao_put=tot["put"],
                        put_call=r2(tot["put"] / tot["call"]) if tot["call"] else None,
                        descoberta_call_pct=r2(desc["call"] / tot["call"] * 100.0, 1) if tot["call"] else None,
                        descoberta_put_pct=r2(desc["put"] / tot["put"] * 100.0, 1) if tot["put"] else None,
                        vencimentos=[],
                        todos_vencimentos=[[v, sum(por_venc[v]["call"].values()), sum(por_venc[v]["put"].values())]
                                           for v in sorted(por_venc)[:10]])
            _, ant = ctx.anterior("ativos", tk, "opc") if tk in ctx.ids else ctx.anterior("opcoes_extras", tk)
            if ant:
                item["var_posicao_call_pct"], item["var_posicao_put_pct"] = pct(tot["call"], ant[0]), pct(tot["put"], ant[1])
                item["put_call_anterior"] = r2(ant[1] / ant[0]) if ant[0] else None
            # serie semanal com posicao pequena nao e parede: so entra vencimento com fatia relevante
            total = tot["call"] + tot["put"]
            piso = total * lim.get("opcoes_fatia_minima_pct", 10.0) / 100.0
            relevantes = [v for v in sorted(por_venc)
                          if sum(por_venc[v]["call"].values()) + sum(por_venc[v]["put"].values()) >= piso]
            avisou = False
            for venc in relevantes[:n_venc]:
                v = por_venc[venc]
                du = relogios.dias_uteis_b3(ctx.d, date.fromisoformat(venc[:10]))
                bloco = {"vencimento": venc, "dias_uteis": du,
                         "posicao_call": sum(v["call"].values()), "posicao_put": sum(v["put"].values()),
                         "dor_maxima": _dor_maxima(v["call"], v["put"])}
                perto = []
                for tipo in ("call", "put"):
                    top = sorted(v[tipo].items(), key=lambda kv: -kv[1])[:n_strikes]
                    bloco[f"strikes_{tipo}"] = [[k, q] for k, q in top]
                    if not fech:
                        continue
                    # parede e fora do dinheiro: call acima do preco (teto), put abaixo (piso). Posicao grande
                    # dentro do dinheiro costuma ser operacao estruturada (box, financiamento), nao barreira.
                    fora = [(k, q) for k, q in v[tipo].items() if (k >= fech if tipo == "call" else k <= fech)]
                    if fora:
                        k, q = max(fora, key=lambda kv: kv[1])
                        dist = round((k / fech - 1.0) * 100.0, 2)
                        bloco[f"parede_{tipo}"] = {"strike": k, "posicao": q, "distancia_pct": dist}
                        if abs(dist) <= lim.get("opcoes_dist_parede_pct", 5.0):
                            perto.append(f"{tipo} em {mil(k, 2)} ({mil(q)} opções, {brp(dist, 1)} do preço)")
                if fech:
                    # grade para o grafico: strikes perto do preco, os de maior posicao
                    perto_do_preco = [k for k in set(v["call"]) | set(v["put"]) if abs(k / fech - 1.0) * 100.0 <= grade_pct]
                    fica = sorted(perto_do_preco, key=lambda k: -(v["call"].get(k, 0) + v["put"].get(k, 0)))[:grade_n]
                    bloco["grade"] = [[k, v["call"].get(k, 0.0), v["put"].get(k, 0.0)] for k in sorted(fica)]
                    if bloco["dor_maxima"]:
                        bloco["dor_maxima_dist_pct"] = round((bloco["dor_maxima"] / fech - 1.0) * 100.0, 2)
                item["vencimentos"].append(bloco)
                if perto and not avisou and du <= lim.get("opcoes_dias_uteis_venc", 10):
                    avisou = True
                    ctx.sinal("opcoes_parede", tk,
                              f"{tk} fechou a {mil(fech, 2)} com o vencimento de {dm(venc)} a {du} dias úteis e a maior "
                              f"posição em aberto de " + " e de ".join(perto) + ".",
                              "DerivativesOpenPosition + InstrumentsConsolidated", vencimento=venc, dias_uteis=du,
                              parede_call=bloco.get("parede_call"), parede_put=bloco.get("parede_put"))
        if any(item.get(k) for k in ("volume_call_rs", "volume_put_rs", "posicao_call", "posicao_put")):
            (do_livro if tk in ctx.ids else extras)[tk] = item
    return do_livro, extras


def mudancas_por_ativo(ctx: Contexto, opc: dict, extras: dict) -> None:
    """Pendura em cada ativo as series que mais ganharam e mais perderam posicao em aberto no dia."""
    piso = ctx.lim.get("opcoes_var_posicao_rs", 30e6)
    candidatos = []
    for tk, item in list(opc.items()) + list(extras.items()):
        meus = [m for m in ctx.mudancas_oi if m["ativo"] == tk]
        if not meus:
            continue
        item["maiores_altas"] = sorted((m for m in meus if m["variacao"] > 0), key=lambda m: -m["variacao"])[:5]
        item["maiores_quedas"] = sorted((m for m in meus if m["variacao"] < 0), key=lambda m: m["variacao"])[:5]
        preco = item.get("preco")
        if tk in ctx.ids and preco and item["maiores_altas"]:
            m = item["maiores_altas"][0]
            if m["variacao"] * preco >= piso:
                candidatos.append((m["variacao"] * preco, tk, m))
    for _, tk, m in sorted(candidatos, key=lambda x: -x[0])[:3]:
        preco, k = (opc.get(tk) or extras.get(tk) or {}).get("preco"), m["strike"]
        fundo = preco and k and ((m["tipo"] == "call" and k < 0.85 * preco) or (m["tipo"] == "put" and k > 1.15 * preco))
        ctx.sinal("opcoes_posicao", tk,
                  f"{tk}: a {m['tipo']} {m['codigo']} (strike {mil(m['strike'], 2)}, vencimento {dm(m['vencimento'])}) ganhou "
                  f"{mil(m['variacao'])} opções em aberto no dia, para {mil(m['posicao'])}."
                  + (" Strike bem dentro do dinheiro: costuma ser operação estruturada, não aposta de direção." if fundo else ""),
                  "DerivativesOpenPosition", variacao=m["variacao"], posicao=m["posicao"], strike=m["strike"])


# ------------------------------------------------------------------ aluguel (BTC)

def aluguel(ctx: Contexto, neg: dict, carteiras: dict) -> dict:
    pos_tab, novos_tab = ctx.tab("BTBLendingOpenPosition"), ctx.tab("BTBLoanBalance")
    alvo = set(ctx.ids)
    out: dict = {}
    if pos_tab:
        if pos_tab.get("truncada"):
            ctx.lacunas.append("BTBLendingOpenPosition passou do teto de páginas: aluguel pode estar incompleto.")
        for r in b3.registros(pos_tab):
            tk = r.get("TckrSymb")
            if tk not in alvo:
                continue
            item = out.setdefault(tk, {"por_mercado": {}})
            if r.get("Market") == "Total":
                item["saldo_qtd"], item["saldo_rs"] = r.get("StockBalance"), r.get("Balance")
            else:
                item["por_mercado"][r.get("Market")] = r.get("StockBalance")
    if novos_tab:
        if novos_tab.get("truncada"):
            ctx.lacunas.append("BTBLoanBalance passou do teto de páginas: empréstimos do dia podem estar incompletos.")
        for r in b3.registros(novos_tab):
            tk = r.get("TckrSymb")
            if tk not in alvo:
                continue
            item = out.setdefault(tk, {"por_mercado": {}})
            item["novos_contratos"] = item.get("novos_contratos", 0) + (r.get("QtyCtrctsDay") or 0)
            item["novos_qtd"] = item.get("novos_qtd", 0) + (r.get("ValCtrctsDay") or 0)
            item["novos_rs"] = r2(item.get("novos_rs", 0) + (r.get("BRLValue") or 0), 0)
            # a taxa e por ativo (media ponderada de todas as modalidades), repetida em cada linha
            for campo, chave in (("TkrAvrgRate", "taxa_tomador_media"), ("TkrMaxRate", "taxa_tomador_max"),
                                 ("DnrAvrgRate", "taxa_doador_media")):
                if r.get(campo) is not None:
                    item[chave] = round(r[campo] * 100.0, 4)      # fracao -> % ao ano
    for tk, item in out.items():
        if not item["por_mercado"]:
            item.pop("por_mercado")
        qtd = item.get("saldo_qtd")
        if qtd is None:
            continue
        d1, a1 = ctx.anterior("ativos", tk, "alug")
        _, a5 = ctx.anterior("ativos", tk, "alug", n=5)
        item["var_dia_pct"], item["var_5d_pct"] = pct(qtd, a1), pct(qtd, a5)
        item["comparado_com"] = d1
        teorica = (carteiras.get(tk) or {}).get("quantidade_teorica")
        if teorica:
            item["pct_free_float"] = r2(qtd / teorica * 100.0)
        qtds = ctx.serie("ativos", tk, "qtd", n=20)
        giro = media(qtds + [(neg.get(tk) or {}).get("quantidade")])
        if giro:
            item["pregoes_para_cobrir"] = r2(qtd / giro, 1)
        _aluguel_sinais(ctx, tk, item, neg.get(tk) or {})
    return out


def _aluguel_sinais(ctx: Contexto, tk: str, a: dict, n: dict) -> None:
    lim, fonte = ctx.lim, "BTBLendingOpenPosition"
    vd, v5, p5, osc = a.get("var_dia_pct"), a.get("var_5d_pct"), n.get("var_5d_pct"), n.get("oscilacao_pct")
    mi = (a.get("saldo_qtd") or 0) / 1e6
    # saldo pequeno oscila muito em percentual e nao diz nada
    relevante = (a.get("saldo_rs") or 0) >= lim.get("aluguel_saldo_minimo_rs", 5e6)
    if relevante and vd is not None and abs(vd) >= lim.get("aluguel_var_dia_pct", 10.0):
        ctx.sinal("aluguel_variacao", tk,
                  f"{tk}: saldo alugado {'subiu' if vd > 0 else 'caiu'} {mil(abs(vd), 1)}% em um pregão, para {mil(mi, 1)} mi de ações"
                  + (f", com o preço em {brp(osc)} no dia." if osc is not None else "."),
                  fonte, var_dia_pct=vd, saldo_qtd=a.get("saldo_qtd"), oscilacao_pct=osc)
    if relevante and v5 is not None and p5 is not None:
        if v5 >= lim.get("aluguel_var_5d_pct", 25.0) and p5 <= -lim.get("preco_var_5d_pct", 3.0):
            ctx.sinal("pressao_vendida", tk,
                      f"{tk}: em 5 pregões o saldo alugado subiu {mil(v5, 1)}% e o preço caiu {mil(abs(p5), 1)}%: "
                      f"posição vendida crescendo junto com a queda.", fonte, aluguel_var_5d_pct=v5, preco_var_5d_pct=p5)
        if v5 <= -lim.get("aluguel_var_5d_pct", 25.0) and p5 >= lim.get("preco_var_5d_pct", 3.0):
            ctx.sinal("zeragem_de_vendidos", tk,
                      f"{tk}: em 5 pregões o saldo alugado caiu {mil(abs(v5), 1)}% e o preço subiu {mil(p5, 1)}%: "
                      f"vendidos devolvendo o papel na alta.", fonte, aluguel_var_5d_pct=v5, preco_var_5d_pct=p5)
    ff, taxa = a.get("pct_free_float"), a.get("taxa_tomador_media")
    if ff is not None and ff >= lim.get("aluguel_pct_float_alto", 5.0):
        texto = f"{tk}: saldo alugado de {mil(mi, 1)} mi de ações, {mil(ff, 1)}% da quantidade teórica do índice"
        if a.get("pregoes_para_cobrir"):
            texto += f" e {mil(a['pregoes_para_cobrir'], 1)} pregões de giro"
        if taxa is not None:
            texto += f"; taxa média do tomador de {mil(taxa, 2)}% ao ano"
        texto += "."
        if p5 is not None and p5 >= lim.get("preco_var_5d_pct", 3.0):
            texto += (f" O preço subiu {mil(p5, 1)}% em 5 pregões: aluguel alto com preço subindo é o quadro em que o "
                      f"vendido costuma ser forçado a recomprar.")
        ctx.sinal("aluguel_alto", tk, texto, fonte, pct_free_float=ff, pregoes_para_cobrir=a.get("pregoes_para_cobrir"),
                  taxa_tomador_media=taxa, preco_var_5d_pct=p5)
    elif taxa is not None and taxa >= lim.get("aluguel_taxa_alta", 5.0):
        ctx.sinal("aluguel_caro", tk, f"{tk}: taxa média do tomador no aluguel em {mil(taxa, 2)}% ao ano: papel disputado por vendidos.",
                  "BTBLoanBalance", taxa_tomador_media=taxa)


# ------------------------------------------------------------------ indices e carteiras

def indices(ctx: Contexto) -> dict:
    t = ctx.tab("INDEXES")
    if not t:
        return {}
    ordem = list(ctx.cfg.get("indices") or ["IBOVESPA"])
    quero = set(ordem)
    out = {}
    for grupo in sorted(t.get("filhos") or [], key=lambda g: ordem.index(g.get("nome")) if g.get("nome") in quero else 99):
        if grupo.get("nome") not in quero:
            continue
        item = {}
        for f in grupo.get("filhos") or []:
            regs = b3.registros(f)
            if not regs:
                continue
            r = regs[0]
            if f["nome"].endswith("DayBehavior"):
                item.update(fechamento=r.get("LastPric"), abertura=r.get("OpenPric"), minimo=r.get("MinPric"), maximo=r.get("MaxPric"))
            elif f["nome"].endswith("ClosingEvolution"):
                for campo, chave in (("InDay", "dia_pct"), ("InTheWeek", "semana_pct"), ("InTheMonth", "mes_pct"), ("InTheYear", "ano_pct")):
                    if isinstance(r.get(campo), (int, float)):
                        item[chave] = round(r[campo] * 100.0, 2)
            elif f["nome"].endswith("ActionsBehavior"):
                item.update(altas=r.get("ActNmbrHigh"), baixas=r.get("ActNmbrLow"))
        if item:
            out[grupo["nome"]] = item
    return out


def carteiras(ctx: Contexto) -> dict:
    """Peso de cada ativo do livro nos indices e a quantidade teorica (aproximacao do free float)."""
    t = ctx.tab("PreviaQuadrimestral")
    guardada = ctx.hist.get("carteira") or {}
    if not t or not any(True for _ in b3.folhas(t)):
        # a carteira vale pelo quadrimestre: se a B3 nao publicou hoje (14/09/2026 veio vazia), fica a ultima
        if guardada.get("ativos"):
            ctx.lacunas.append(f"Carteira de índice: a B3 não publicou a tabela neste pregão; valem os pesos de {dm(guardada.get('data'))}.")
            return dict(guardada["ativos"], _vigencia=guardada.get("vigencia"), _data=guardada.get("data"))
        return {}
    alvo = set(ctx.ids)
    out: dict = {}
    for sigla, nome in (ctx.cfg.get("carteiras") or {}).items():
        f = b3.filho(t, nome)
        for r in b3.registros(f) if f else []:
            tk = r.get("TckrSymb")
            if tk in alvo:
                item = out.setdefault(tk, {"pesos_pct": {}})
                item["pesos_pct"][sigla] = r.get("StockParticipation")
                item.setdefault("quantidade_teorica", r.get("QtyTheoretical"))
    vig = next((x for x in t.get("texto") or [] if x.lower().startswith("para ")), None)
    if out:
        out["_vigencia"], out["_data"] = vig, ctx.iso
    return out


def previas(ctx: Contexto, cart: dict) -> dict:
    """Previa da carteira do Ibovespa, quando a B3 publica (tres por quadrimestre)."""
    t, oficial = ctx.tab("Previa"), ctx.bruto["tabelas"].get("PreviaQuadrimestral")
    if not t or not oficial:
        return {}
    for n, nome in ((3, "WalletIbovespa3"), (2, "WalletIbovespa2"), (1, "WalletIbovespa")):
        f = b3.filho(t, nome)
        regs = b3.registros(f) if f else []
        if not regs:
            continue
        nova = {r["TckrSymb"]: r.get("StockParticipation") for r in regs}
        of = b3.filho(oficial, "OficialWalletIbovespa")
        atual = {r["TckrSymb"]: r.get("StockParticipation") for r in b3.registros(of)} if of else {}
        res = {"previa": n, "indice": "IBOV", "entram": sorted(set(nova) - set(atual)), "saem": sorted(set(atual) - set(nova)),
               "livro": {tk: {"atual_pct": atual.get(tk), "previa_pct": nova.get(tk)} for tk in ctx.ids if tk in nova or tk in atual},
               "fonte": ctx.fonte("Previa")}
        mexe = [tk for tk in ctx.ids if tk in res["entram"] or tk in res["saem"]]
        ctx.sinal("previa_indice", None,
                  f"{n}ª prévia do Ibovespa publicada: entram {', '.join(res['entram']) or 'ninguém'}; saem {', '.join(res['saem']) or 'ninguém'}."
                  + (f" Do livro: {', '.join(mexe)}." if mexe else " Nenhum ativo do livro entra ou sai."),
                  "Previa", entram=res["entram"], saem=res["saem"])
        return res
    return {}


# ------------------------------------------------------------------ fluxo por tipo de investidor

def fluxo(ctx: Contexto) -> dict:
    t = ctx.tab("SharesInvesVolum")
    if not t or not t["linhas"]:
        return {}
    m = RX_ATE.search(" ".join(t.get("texto") or []))
    ate = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None
    if not ate:
        ctx.lacunas.append("SharesInvesVolum sem a frase 'até o dia': a data de referência do fluxo ficou sem confirmação.")
    mes: dict = {}
    for r in b3.registros(t):
        nome = b3.sem_acento(r.get("TckrSymb") or "").lower()
        chave = next((k for k, trecho in TIPOS_INVESTIDOR if trecho in nome), None)
        if chave and r.get("Purchase") is not None and r.get("Partmil") is not None:
            c, v = r["Purchase"] / 1000.0, r["Partmil"] / 1000.0      # R$ mil -> R$ milhoes
            mes[chave] = {"compras_mi": r2(c, 1), "vendas_mi": r2(v, 1), "saldo_mi": r2(c - v, 1),
                          "part_compras_pct": r.get("Sales"), "part_vendas_pct": r.get("PartPer")}
    out = {"ate": ate, "acumulado_no_mes": mes, "fonte": ctx.fonte("SharesInvesVolum", ate),
           "nota": "Compras e vendas somam todos os mercados da B3 (à vista, opções, termo), acumuladas no mês."}
    d_ant, ant = None, None
    for k, v in ctx.antes:
        f = v.get("fluxo") or {}
        if f.get("ate") and ate and f["ate"] < ate:
            d_ant, ant = k, f
            break
    if ant and ate:
        mesmo_mes = ant["ate"][:7] == ate[:7]
        dia = {}
        for chave, x in mes.items():
            base = (ant.get("saldo") or {}).get(chave)
            if not mesmo_mes:
                dia[chave] = x["saldo_mi"]
            elif base is not None:
                dia[chave] = r2(x["saldo_mi"] - base, 1)
        inicio = relogios.proximo_dia_util("B3", date.fromisoformat(ant["ate"])).isoformat() if mesmo_mes else ate[:8] + "01"
        out["periodo"] = {"de": min(inicio, ate), "ate": ate, "saldo_mi": dia,
                          "nota": ("saldo entre os dois acumulados" if mesmo_mes else "virada de mês: saldo desde o dia 1"),
                          "comparado_com_pregao": d_ant}
        est = dia.get("estrangeiro")
        if est is not None:
            acum = (mes.get("estrangeiro") or {}).get("saldo_mi")
            ctx.sinal("fluxo_estrangeiro", None,
                      f"Estrangeiro {'comprou' if est >= 0 else 'vendeu'} R$ {mil(abs(est))} mi líquidos "
                      + (f"em {dm(ate)}" if out["periodo"]["de"] == ate else f"de {dm(out['periodo']['de'])} a {dm(ate)}")
                      + f"; no mês, até {dm(ate)}, saldo de "
                      f"{'+' if (acum or 0) >= 0 else '-'}R$ {mil(abs(acum or 0))} mi.",
                      "SharesInvesVolum", ate, saldo_periodo_mi=est, saldo_mes_mi=acum)
    return out


# ------------------------------------------------------------------ mercado e derivativos

def mercado(ctx: Contexto) -> dict:
    out: dict = {}
    t = ctx.tab("DailyAverageStocks")
    if t:
        for r in b3.registros(t):
            chave = {"Dia": "dia", "Mês": "media_mes", "Mês anterior": "media_mes_anterior", "Ano": "media_ano"}.get(r.get("TckrSymb"))
            if chave:
                out[chave] = {"negocios": r.get("NmbrTradesDay"), "volume_mi": r.get("VlmTradedDay")}
        if out.get("dia") and out.get("media_mes"):
            out["volume_x_media_mes"] = r2(out["dia"]["volume_mi"] / out["media_mes"]["volume_mi"]) if out["media_mes"]["volume_mi"] else None
        out["fonte"] = ctx.fonte("DailyAverageStocks")
    t = ctx.tab("StocksOperationSummary")
    if t:
        nomes = {"TOTAL A VISTA": "a_vista", "TERMO": "termo", "TOTAL DE OPCOES": "opcoes", "TOTAL GERAL": "total",
                 "PARTIC. AFTER MARKET": "after_market"}
        seg = {}
        for r in b3.registros(t):
            chave = nomes.get((r.get("TckrSymb") or "").strip())
            if chave:
                seg[chave] = {"negocios": r.get("NmbrTradesDay"), "volume_mi": r2((r.get("ValueInThousand") or 0) / 1000.0, 1),
                              "part_pct": r.get("Part2")}
        out["segmentos"] = seg
    t = ctx.tab("DailyAverageDerivatives2")
    if t:
        der = {}
        for r in b3.registros(t):
            chave = {"Dia": "dia", "Mês": "media_mes", "Ano": "media_ano"}.get(r.get("TckrSymb"))
            if chave:
                der[chave] = {"contratos": r2(r.get("TotalWithMinis"), 0), "contratos_sem_minis": r2(r.get("TotalNoMinis"), 0)}
        out["derivativos_contratos"] = der
    return out


def derivativos(ctx: Contexto) -> dict:
    out: dict = {"quadro": {}, "futuros": {}}
    t = ctx.tab("AnalyticalFramework2")
    if t:
        quero = set(ctx.cfg.get("quadro_ativos") or [])
        for r in b3.registros(t):
            a = r.get("Asst")
            if a in quero and (r.get("TckrSymb") or "").rstrip().endswith("- futuro"):
                item = {"mercado": r["TckrSymb"], "contratos": r.get("OpnIntrst"), "referencial_mi": r2((r.get("RefValue") or 0) / 1000.0, 1)}
                d1, ant = ctx.anterior("quadro", a)
                item["var_contratos_pct"], item["comparado_com"] = pct(item["contratos"], ant), d1
                out["quadro"][a] = item
                v = item["var_contratos_pct"]
                if (v is not None and abs(v) >= ctx.lim.get("quadro_var_pct", 5.0)
                        and a in (ctx.cfg.get("quadro_sinal") or quero)):
                    ctx.sinal("posicao_em_aberto", a,
                              f"{item['mercado']}: contratos em aberto {'subiram' if v > 0 else 'caíram'} {mil(abs(v), 1)}% em um pregão, "
                              f"para {mil(item['contratos'])}.", "AnalyticalFramework2", var_contratos_pct=v, contratos=item["contratos"])
        for r in b3.registros(t):
            a, texto = r.get("Asst"), (r.get("TckrSymb") or "").rstrip().lower()
            lado = "call" if texto.endswith("- compra") else ("put" if texto.endswith("- venda") else None)
            if a in quero and lado and "opç" in texto:
                o = out.setdefault("quadro_opcoes", {}).setdefault(a, {"mercado": r["TckrSymb"].rsplit(" - ", 1)[0]})
                o[lado] = (o.get(lado) or 0) + (r.get("OpnIntrst") or 0)
        for o in (out.get("quadro_opcoes") or {}).values():
            o["put_call"] = r2(o["put"] / o["call"]) if o.get("call") and o.get("put") is not None else None
        out["fonte_quadro"] = ctx.fonte("AnalyticalFramework2")
    cfgf = ctx.cfg.get("futuros") or {}
    vertices = set(ctx.cfg.get("di_vertices") or [])
    por_ativo: dict = {}
    for tk, r in ctx.trades.items():
        m = RX_FUTURO.match(tk)
        if not m or m.group(1) not in cfgf or r.get("SgmtNm") != "FINANCIAL" or not b3.num(r.get("TradQty")):
            continue
        p = ctx.pos.get(tk) or {}
        item = {"ajuste": b3.num(r.get("AdjstdQt")), "taxa": b3.num(r.get("AdjstdQtTax")), "ultimo": b3.num(r.get("LastPric")),
                "negocios": b3.num(r.get("TradQty")), "contratos": b3.num(r.get("FinInstrmQty")), "volume_rs": b3.num(r.get("NtlFinVol")),
                "em_aberto": b3.num(p.get("OpnIntrst")), "var_em_aberto": b3.num(p.get("VartnOpnIntrst"))}
        d1, ant = ctx.anterior("futuros", tk)
        if ant:
            if cfgf[m.group(1)].get("curva") and item["taxa"] is not None and ant.get("taxa") is not None:
                item["var_bps"] = round((item["taxa"] - ant["taxa"]) * 100.0, 1)
            elif item["ajuste"] and ant.get("aj"):
                item["var_pct"] = pct(item["ajuste"], ant["aj"])
            item["comparado_com"] = d1
        por_ativo.setdefault(m.group(1), {})[tk] = item
    for a, itens in por_ativo.items():
        if cfgf[a].get("curva"):
            fica = {tk for tk in itens if tk in vertices} | set(sorted(itens, key=lambda k: -(itens[k]["contratos"] or 0))[:6])
        else:
            fica = set(sorted(itens, key=lambda k: -(itens[k]["contratos"] or 0))[:2])
        out["futuros"][a] = {tk: itens[tk] for tk in sorted(fica, key=_ordem_venc)}
    for tk in sorted(vertices, key=_ordem_venc):
        v = ((out["futuros"].get("DI1") or {}).get(tk) or {}).get("var_bps")
        if v is not None and abs(v) >= ctx.lim.get("di_var_bps", 10.0):
            ctx.sinal("juros", tk, f"{tk}: taxa de ajuste {'abriu' if v > 0 else 'fechou'} {mil(abs(v))} pontos-base, para "
                      f"{mil(out['futuros']['DI1'][tk]['taxa'], 2)}%.", "TradeInformationConsolidated", var_bps=v)
    return out


def _ordem_venc(tk: str):
    m = RX_FUTURO.match(tk)
    return (int(m.group(3)), "FGHJKMNQUVXZ".index(m.group(2))) if m else (99, 0)


def indicadores(ctx: Contexto) -> dict:
    out: dict = {}
    t = ctx.tab("EconomicIndicators")
    if t:
        quero = ctx.cfg.get("indicadores") or {}
        for r in b3.registros(t):
            s = r.get("IndcSymb")
            if s in quero and s not in out and r.get("IndxVal") is not None:
                out[s] = {"rotulo": quero[s], "valor": r["IndxVal"], "data": r.get("RptDt")}
                _, ant = ctx.anterior("indicadores", s)
                out[s]["var_pct"] = pct(r["IndxVal"], ant)
        out["fonte"] = ctx.fonte("EconomicIndicators")
    t = ctx.tab("DIover")
    if t and t["linhas"]:
        r = b3.registros(t)[0]
        out["selic_meta"] = {"valor": r.get("SelicRate"), "data": r.get("RptDt")}
        out["di_over"] = {"valor": r.get("Average"), "data": r.get("RptDt")}
    return out


# ------------------------------------------------------------------ ETFs, listas, eventos

def etfs(ctx: Contexto, neg: dict, cad: dict) -> dict:
    t = ctx.tab("IOPV")
    iopv = {r["TckrSymb"]: r for r in b3.registros(t)} if t else {}
    out = {}
    for a in ctx.livro:
        if a.get("classe") != "etf":
            continue
        tk = a["id"]
        item: dict = {}
        fech = (neg.get(tk) or {}).get("fechamento")
        r = iopv.get(tk[:4])
        if r and r.get("Closing") and fech:
            item["iopv"] = r["Closing"]
            item["premio_pct"] = round((fech / r["Closing"] - 1.0) * 100.0, 2)
            if abs(item["premio_pct"]) >= ctx.lim.get("etf_premio_pct", 0.5):
                ctx.sinal("etf_premio", tk, f"{tk} fechou a R$ {mil(fech, 2)}, {'prêmio' if item['premio_pct'] > 0 else 'desconto'} de "
                          f"{mil(abs(item['premio_pct']), 2)}% sobre o valor de referência da cota (R$ {mil(r['Closing'], 2)}).",
                          "IOPV", premio_pct=item["premio_pct"], iopv=r["Closing"], fechamento=fech)
        elif t:
            item["iopv"] = None
            ctx.lacunas.append(f"{tk}: a B3 não publica valor de referência da cota (IOPV) para este ETF no boletim.")
        cotas = (cad.get(tk) or {}).get("quantidade_emitida")
        if cotas:
            item["cotas"] = cotas
            d1, ant = ctx.anterior("ativos", tk, "cotas")
            if ant:
                item["var_cotas"], item["comparado_com"] = cotas - ant, d1
                if cotas != ant:
                    ctx.sinal("etf_cotas", tk, f"{tk}: cotas emitidas {'subiram' if cotas > ant else 'caíram'} "
                              f"{mil(abs(cotas - ant))} (para {mil(cotas)}): {'criação' if cotas > ant else 'resgate'} de cotas.",
                              "InstrumentsConsolidated", var_cotas=cotas - ant, cotas=cotas)
        if item:
            out[tk] = item
    return out


def destaques(ctx: Contexto) -> dict:
    listas = (("IbovespaStockBiggestHighs", "maiores_altas_ibov"), ("IbovespaStockBiggestLow", "maiores_baixas_ibov"),
              ("InCashMarketBiggestHighs", "maiores_altas_mercado"), ("InCashMarketBiggestLow", "maiores_baixas_mercado"),
              ("InCash", "mais_negociadas"), ("OptionsPurshase", "opcoes_compra_mais_negociadas"),
              ("OptionsSelling", "opcoes_venda_mais_negociadas"), ("Forward", "termo_mais_negociadas"))
    raizes = {}
    for tk in ctx.ids:
        raizes.setdefault(tk[:4], []).append(tk)
    out: dict = {"livro_nas_listas": []}
    for nome, chave in listas:
        t = ctx.tab(nome)
        if not t:
            continue
        linhas, vistos = [], set()
        for r in b3.registros(t):
            cod = (r.get("TckrSymb") or "").strip()
            if cod in vistos:
                continue
            vistos.add(cod)
            valor = next((r[k] for k in ("Oscillation", "OscillationDesc", "VlmTradedDay") if r.get(k) is not None), None)
            linhas.append([cod, valor])
            do_livro = [cod] if cod in ctx.ids else (raizes.get(cod[:4]) if chave.startswith("opcoes") else None)
            if do_livro:
                out["livro_nas_listas"].append({"lista": chave, "posicao": len(linhas), "codigo": cod, "ativos": do_livro, "valor": valor})
        out[chave] = linhas[:10]
    return out


def eventos(ctx: Contexto, cad: dict) -> dict:
    por_isin = {v: k for k, v in ctx.isin.items() if v}
    out: dict = {"proventos": [], "subscricoes": [], "adr": {}}
    t = ctx.tab("ProventionCreditVariable")
    if t:
        for r in b3.registros(t):
            tk = por_isin.get((r.get("Code") or "")[:12])
            if tk:
                out["proventos"].append({"ativo": tk, "tipo": r.get("EarningsType"), "valor": r.get("Value"),
                                         "aprovado_em": r.get("DateAge"), "credito_em": r.get("CreditDate")})
                ctx.sinal("provento", tk, f"{tk}: crédito de {(r.get('EarningsType') or 'provento').lower()} de R$ {mil(r.get('Value') or 0, 4)} "
                          f"por ação em {dm(r.get('CreditDate'))}.", "ProventionCreditVariable", valor=r.get("Value"))
        out["proventos_no_dia"] = len(t["linhas"])
    t = ctx.tab("DeadlineDepositSecurities")
    if t:
        for r in b3.registros(t):
            tk = por_isin.get((r.get("Code") or "")[:12])
            if tk:
                out["proventos"].append({"ativo": tk, "tipo": r.get("Earnings"), "prazo_deposito": r.get("UpdateDate")})
                ctx.sinal("provento", tk, f"{tk}: {(r.get('Earnings') or 'provento').lower()} com prazo de depósito de títulos em {dm(r.get('UpdateDate'))}.",
                          "DeadlineDepositSecurities")
    t = ctx.tab("FugibleCustody")
    if t:
        for r in b3.registros(t):
            tk = por_isin.get((r.get("IsinOrigin") or "")[:12])
            if tk:
                out["subscricoes"].append({"ativo": tk, "prazo_subscricao": r.get("SbscrptnDeadline"), "prazo_cessao": r.get("DeadlineAssgnmnt")})
                ctx.sinal("subscricao", tk, f"{tk}: direito de subscrição em aberto, prazo final {dm(r.get('SbscrptnDeadline'))}.", "FugibleCustody")
    t = ctx.tab("Custody")
    if t:
        chaves = {}
        for tk, c in cad.items():
            if c.get("empresa") and c.get("categoria") == "SHARES":
                chaves[(b3.chave_empresa(c["empresa"]), (c.get("especificacao") or "").split(" ")[0])] = tk
        for r in b3.registros(t):
            tk = chaves.get((b3.chave_empresa(r.get("TckrSymb") or ""), (r.get("Type") or "").split(" ")[0]))
            if tk and r.get("QtyStocks") is not None:
                item = {"acoes_em_adr": r["QtyStocks"]}
                d1, ant = ctx.anterior("ativos", tk, "adr")
                if ant:
                    item["var"], item["comparado_com"] = r["QtyStocks"] - ant, d1
                emit = (cad.get(tk) or {}).get("quantidade_emitida")
                if emit:
                    item["pct_da_classe"] = r2(r["QtyStocks"] / emit * 100.0)
                out["adr"][tk] = item
        out["fonte_adr"] = ctx.fonte("Custody")
    return out


def termo_e_after(ctx: Contexto, neg: dict) -> tuple[dict, dict]:
    termo: dict = {}
    t = ctx.tab("ForwardMarket")
    if t:
        for r in b3.registros(t):
            tk = (r.get("TckrSymb") or "")[:-1] if (r.get("TckrSymb") or "").endswith("T") else None
            if tk in ctx.ids:
                x = termo.setdefault(tk, {"negocios": 0, "quantidade": 0, "prazos": []})
                x["negocios"] += r.get("Num") or 0
                x["quantidade"] += r.get("TradQty") or 0
                x["prazos"].append(r.get("Term"))
    after: dict = {}
    regs = ctx.arq("TradeInformationConsolidatedAfterHours")
    for r in regs or []:
        tk = r.get("TckrSymb")
        if tk in ctx.ids:
            medio, fech = b3.num(r.get("TradAvrgPric")), (neg.get(tk) or {}).get("fechamento")
            item = {"preco_medio": medio, "quantidade": b3.num(r.get("FinInstrmQty")), "volume_rs": b3.num(r.get("NtlFinVol")),
                    "var_sobre_fechamento_pct": pct(medio, fech)}
            after[tk] = item
            v = item["var_sobre_fechamento_pct"]
            if v is not None and abs(v) >= ctx.lim.get("after_var_pct", 1.0):
                ctx.sinal("after_market", tk, f"{tk}: preço médio do after market a {brp(v)} do fechamento "
                          f"(R$ {mil(medio, 2)} contra R$ {mil(fech, 2)}), em R$ {mil((item['volume_rs'] or 0) / 1e3)} mil.",
                          "TradeInformationConsolidatedAfterHours", var_pct=v, volume_rs=item["volume_rs"])
    return termo, after


def informativos(ctx: Contexto) -> list:
    termos = {}
    for a in ctx.livro:
        palavras = b3.sem_acento(a.get("nome") or "").upper().split()
        if not palavras:
            continue
        termo = palavras[0] if palavras[0] not in GENERICAS else " ".join(palavras[:3])
        if len(termo) >= 3:
            termos[a["id"]] = re.compile(rf"\b{re.escape(termo)}\b")
    out = []
    for i in ctx.bruto.get("informativos") or []:
        titulo = b3.sem_acento(i.get("titulo") or "").upper()
        achou = [tk for tk, rx in termos.items() if rx.search(titulo)]
        out.append({"titulo": i.get("titulo"), "secao": i.get("secao"), "data": i.get("data"), "vence": i.get("vence"),
                    "link": i.get("link"), "ativos_do_livro": achou})
        if achou:
            ctx.sinal("informativo", achou[0], f"Comunicado no boletim cita {', '.join(achou)}: {i.get('titulo')}.", "informations")
    return out


def renda_fixa_puma(ctx: Contexto) -> dict:
    """Papeis de renda fixa negociados na plataforma eletronica (Puma): os de maior volume."""
    t = ctx.tab("DebenturesBusiness")
    if not t:
        return {}
    regs = sorted(b3.registros(t), key=lambda r: -(r.get("Volume") or 0))
    return {"negocios_puma": [{"codigo": r.get("TckrSymb"), "nome": (r.get("Company") or "").strip(), "ultimo": r.get("Final"),
                               "negocios": r.get("Neg"), "volume_rs": r.get("Volume")} for r in regs[:10]],
            "papeis_negociados": len(regs), "volume_total_rs": r2(sum(r.get("Volume") or 0 for r in regs), 0),
            "fonte": ctx.fonte("DebenturesBusiness")}


# ------------------------------------------------------------------ paridade e triangulacao

def _var_serie(caminho: str, iso: str):
    """Variacao percentual da barra de `iso` contra a barra anterior, numa serie do livro."""
    try:
        with open(caminho, encoding="utf-8") as f:
            barras = json.load(f).get("barras") or []
    except (OSError, ValueError):
        return None
    for i, b in enumerate(barras):
        if b[0] == iso and i > 0 and b[4] and barras[i - 1][4]:
            return (b[4] / barras[i - 1][4] - 1.0) * 100.0
    return None


def paridades(ctx: Contexto, neg: dict) -> list:
    out = []
    for p in ctx.cfg.get("paridades") or []:
        tk = p["ativo"]
        osc = (neg.get(tk) or {}).get("oscilacao_pct")
        if osc is None:
            continue
        if not ctx.series_dir:
            ctx.lacunas.append(f"Paridade de {tk} contra {p['referencia']} x câmbio: séries do livro fora do alcance desta rodada.")
            continue
        ref = _var_serie(os.path.join(ctx.series_dir, f"{p['referencia']}.json"), ctx.iso)
        fx = _var_serie(os.path.join(ctx.series_dir, f"{p['cambio']}.json"), ctx.iso)
        if ref is None or fx is None:
            falta = p["referencia"] if ref is None else p["cambio"]
            ctx.lacunas.append(f"Paridade de {tk}: sem a barra de {dm(ctx.iso)} de {falta} nas séries do livro.")
            continue
        justo = ((1 + ref / 100.0) * (1 + fx / 100.0) - 1.0) * 100.0
        item = {"ativo": tk, "oscilacao_pct": osc, "referencia": p["referencia"], "referencia_pct": r2(ref),
                "cambio_pct": r2(fx), "referencia_em_reais_pct": r2(justo), "desvio_pct": r2(osc - justo),
                "nota": "fechamentos em horários diferentes; é aproximação", "fonte": "B3 (ativo) e series do livro (referencia e cambio)"}
        out.append(item)
        if abs(item["desvio_pct"]) >= ctx.lim.get("paridade_desvio_pct", 1.5):
            ctx.sinal("paridade", tk, f"{tk} fez {brp(osc)} contra {brp(justo)} de {p['referencia']} em reais "
                      f"({brp(ref)} lá fora, câmbio {brp(fx)}): descolamento de {brp(item['desvio_pct'])[:-1]} ponto no dia.",
                      "TradeInformationConsolidated + series do livro", desvio_pct=item["desvio_pct"])
    return out


def triangulacao(ctx: Contexto, neg: dict, ind: dict, der: dict, indic: dict) -> dict:
    grupos = {}
    for nome, tks in (ctx.cfg.get("grupos") or {}).items():
        oscs = {tk: neg[tk]["oscilacao_pct"] for tk in tks if tk in neg and neg[tk].get("oscilacao_pct") is not None}
        if oscs:
            grupos[nome] = {"media_pct": r2(media(list(oscs.values()))), "ativos": oscs}
    di = {tk: v.get("var_bps") for tk, v in (der.get("futuros", {}).get("DI1") or {}).items()
          if tk in (ctx.cfg.get("di_vertices") or []) and v.get("var_bps") is not None}
    dol = next(iter((der.get("futuros", {}).get("DOL") or {}).items()), (None, {}))
    return {"ibovespa_pct": (ind.get("IBOVESPA") or {}).get("dia_pct"), "grupos": grupos, "di_var_bps": di,
            "dolar_futuro": {"codigo": dol[0], "var_pct": dol[1].get("var_pct"), "ajuste": dol[1].get("ajuste")} if dol[0] else None,
            "ptax_var_pct": (indic.get("RTDOLT1") or {}).get("var_pct")}


# ------------------------------------------------------------------ montagem

def montar(bruto: dict, cfg: dict, livro: list[dict], hist: dict, series_dir: str | None = None,
           merc: dict | None = None, rf_estado: dict | None = None) -> dict:
    ctx = Contexto(bruto, cfg, livro, hist, series_dir)
    ctx.rf_estado = rf_estado or {}
    neg = negocios(ctx)
    cad = cadastro(ctx)
    cart = carteiras(ctx)
    vigencia, data_carteira = cart.pop("_vigencia", None), cart.pop("_data", None)
    ind = indices(ctx)
    opc, opc_extras = opcoes(ctx, neg, ind)
    opc_mercado = mkt.opcoes_mercado(ctx)
    mudancas_por_ativo(ctx, opc, opc_extras)
    alug = aluguel(ctx, neg, cart)
    rad, coluna_hoje, teorica = mkt.radar(ctx, merc or {})
    em_destaque = set(ctx.ids)
    for chave in ("aluguel_alta", "aluguel_float", "aluguel_taxa", "vendidos_pressionados", "aposta_vendida_crescendo"):
        em_destaque |= {l["ativo"] for l in rad.get(chave) or []}
    corr = mkt.corretoras(ctx, sorted(em_destaque))
    rf = renda_fixa.montar(ctx)
    rf_linhas = rf.pop("_linhas", {}) if rf else {}
    flx = fluxo(ctx)
    mer = mercado(ctx)
    der = derivativos(ctx)
    indic = indicadores(ctx)
    etf = etfs(ctx, neg, cad)
    dest = destaques(ctx)
    evt = eventos(ctx, cad)
    termo, after = termo_e_after(ctx, neg)
    prev = previas(ctx, cart)
    info = informativos(ctx)
    puma = renda_fixa_puma(ctx)
    par = paridades(ctx, neg)

    ativos = {}
    for a in livro:
        tk = a["id"]
        item = {"nome": a.get("nome")}
        for chave, fonte in (("negocios", neg), ("cadastro", cad), ("aluguel", alug), ("opcoes", opc), ("indice", cart),
                             ("etf", etf), ("termo", termo), ("after_market", after), ("adr", evt["adr"])):
            if fonte.get(tk):
                item[chave] = fonte[tk]
        item["sinais"] = [s["tipo"] for s in ctx.sinais if s["ativo"] == tk]
        if tk not in neg and "TradeInformationConsolidated" in bruto["arquivos"]:
            ctx.lacunas.append(f"{tk}: sem negócio no mercado à vista em {dm(ctx.iso)}.")
        ativos[tk] = item

    por_lista: dict = {}
    for l in dest.get("livro_nas_listas") or []:
        por_lista.setdefault(NOME_LISTA.get(l["lista"], l["lista"]), []).append(f"{l['codigo']} ({l['posicao']}º)")
    if por_lista:
        ctx.sinal("lista_do_dia", None, "Do livro nas listas do boletim: "
                  + "; ".join(f"{k}: {', '.join(v)}" for k, v in por_lista.items()) + ".", "tabelas de maiores oscilacoes")

    # sinal de estado (aluguel alto, parede de opcoes) repete todo dia: conta ha quantos pregoes vem
    for s in ctx.sinais:
        chave, seguidos = f"{s['tipo']}|{s['ativo']}", 1
        for _, v in ctx.antes:
            if s["tipo"] in DIARIOS or chave not in (v.get("sinais") or []):
                break
            seguidos += 1
        s["pregoes_seguidos"] = seguidos

    cad_status = bruto.get("status") or {}
    essenciais = ("TradeInformationConsolidated", "InstrumentsConsolidated", "DerivativesOpenPosition",
                  "BTBLendingOpenPosition", "BTBLoanBalance", "AnalyticalFramework2", "SharesInvesVolum")
    faltam = [n for n in essenciais if n in ctx.pendentes]
    return {
        "pregao": ctx.iso, "gerado_em": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "fonte": FONTE,
        "situacao": {"completo": not faltam, "faltam": faltam, "pendentes": dict(sorted(ctx.pendentes.items())),
                     "publicadas_com_atraso": sorted(ctx.atrasadas),
                     "boletim": cad_status.get("situacao"), "boletim_atualizado_em": cad_status.get("atualizado_em"),
                     "boletim_completo_pdf": (cad_status.get("completo") or {}).get("pdf"),
                     "arquivo_de_negocios": (bruto["index"]["arquivos"].get("TradeInformationConsolidated") or {}).get("estado")},
        "livro": [{"id": a["id"], "nome": a.get("nome"), "classe": a.get("classe")} for a in livro],
        "grupos": cfg.get("grupos") or {},
        "mercado": mer, "indices": ind, "fluxo": flx, "derivativos": der, "indicadores": indic,
        "triangulacao": triangulacao(ctx, neg, ind, der, indic), "paridades": par,
        "ativos": ativos, "carteira_vigencia": vigencia, "carteira_data": data_carteira, "previa_indice": prev, "destaques": dest,
        "eventos": {k: v for k, v in evt.items() if k != "adr"}, "informativos": info,
        "renda_fixa": rf, "renda_fixa_puma": puma,
        "radar": rad, "opcoes_mercado": opc_mercado, "opcoes_extras": opc_extras, "aluguel_corretoras": corr,
        "sinais": ctx.sinais, "lacunas": LACUNAS_FIXAS + ctx.lacunas,
        # estado para os arquivos de apoio; quem chama tira antes de gravar o resumo
        "_apoio": {"mercado_hoje": coluna_hoje, "teorica": teorica, "rf_linhas": rf_linhas},
    }


def entrada_historico(resumo: dict) -> dict:
    """O minimo de cada pregao que os proximos precisam: media de volume, variacoes de um dia."""
    ativos = {}
    for tk, a in resumo["ativos"].items():
        n, al, o = a.get("negocios") or {}, a.get("aluguel") or {}, a.get("opcoes") or {}
        item = {"fech": n.get("fechamento"), "osc": n.get("oscilacao_pct"), "vol": n.get("volume_rs"), "qtd": n.get("quantidade"),
                "alug": al.get("saldo_qtd"), "taxa": al.get("taxa_tomador_media"),
                "opc": [o["posicao_call"], o["posicao_put"]] if o.get("posicao_call") is not None else None,
                "cotas": (a.get("etf") or {}).get("cotas"), "adr": (a.get("adr") or {}).get("acoes_em_adr")}
        item = {k: v for k, v in item.items() if v is not None}
        if item:
            ativos[tk] = item
    fut = {tk: {"aj": v.get("ajuste"), "taxa": v.get("taxa"), "oi": v.get("em_aberto")}
           for itens in (resumo["derivativos"].get("futuros") or {}).values() for tk, v in itens.items()}
    out = {"ativos": ativos, "futuros": fut,
           "quadro": {a: v.get("contratos") for a, v in (resumo["derivativos"].get("quadro") or {}).items()},
           "indices": {k: [v.get("fechamento"), v.get("dia_pct")] for k, v in (resumo.get("indices") or {}).items()},
           "indicadores": {k: v["valor"] for k, v in (resumo.get("indicadores") or {}).items()
                           if isinstance(v, dict) and "valor" in v and k.startswith("RT")},
           "volume_mi": ((resumo.get("mercado") or {}).get("dia") or {}).get("volume_mi"),
           "rf": {cl: v.get("volume_rs") for cl, v in ((resumo.get("renda_fixa") or {}).get("resumo") or {}).items()},
           "aluguel_total": (resumo.get("radar") or {}).get("aluguel_total_rs"),
           "opcoes_extras": {tk: [o["posicao_call"], o["posicao_put"]] for tk, o in (resumo.get("opcoes_extras") or {}).items()
                             if o.get("posicao_call") is not None},
           "opcoes_mercado": ([resumo["opcoes_mercado"]["posicao_call"], resumo["opcoes_mercado"]["posicao_put"]]
                              if (resumo.get("opcoes_mercado") or {}).get("posicao_call") is not None else None),
           "sinais": sorted({f"{x['tipo']}|{x['ativo']}" for x in resumo.get("sinais") or []}),
           "completo": resumo["situacao"]["completo"]}
    f = resumo.get("fluxo") or {}
    if f.get("ate"):
        out["fluxo"] = {"ate": f["ate"], "saldo": {k: v["saldo_mi"] for k, v in f["acumulado_no_mes"].items()}}
    return out


def atualizar_historico(hist: dict, resumo: dict, manter: int = 70) -> dict:
    pregoes = dict(hist.get("pregoes") or {})
    nova, velha = entrada_historico(resumo), pregoes.get(resumo["pregao"]) or {}
    # rodada parcial (noite) nao apaga o que a rodada final (manha) ja gravou
    for chave in ("ativos", "futuros"):
        for tk, item in (velha.get(chave) or {}).items():
            base = nova[chave].setdefault(tk, {})
            for k, v in item.items():
                base.setdefault(k, v)
    for chave in ("quadro", "indices", "indicadores", "rf", "opcoes_extras"):
        for k, v in (velha.get(chave) or {}).items():
            if nova[chave].get(k) is None:
                nova[chave][k] = v
    nova["sinais"] = sorted(set(nova["sinais"]) | set(velha.get("sinais") or []))
    for chave in ("fluxo", "volume_mi", "aluguel_total", "opcoes_mercado"):
        if nova.get(chave) is None and velha.get(chave) is not None:
            nova[chave] = velha[chave]
    nova["completo"] = bool(nova["completo"] or velha.get("completo"))
    pregoes[resumo["pregao"]] = nova
    fica = sorted(pregoes)[-manter:]
    carteira = hist.get("carteira") or {}
    pesos = {tk: a["indice"] for tk, a in resumo["ativos"].items() if a.get("indice")}
    if pesos and (resumo.get("carteira_data") or "") >= (carteira.get("data") or ""):
        carteira = {"data": resumo["carteira_data"], "vigencia": resumo.get("carteira_vigencia"), "ativos": pesos}
    return {"fonte": FONTE, "atualizado_em": resumo["gerado_em"], "carteira": carteira,
            "pregoes": {k: pregoes[k] for k in fica}}
