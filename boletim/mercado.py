"""Renda variavel do mercado inteiro: radar de volume e de aluguel, opcoes e corretoras.

O livro e o foco, mas o que acontece fora dele e contexto e ideia. O universo do radar e o
IBrA (Indice Brasil Amplo, cerca de 190 acoes com liquidez) mais os ativos B3 do livro.

Guarda em `mercado.json` so o que os proximos pregoes precisam: fechamento, volume e saldo
alugado de cada ativo do universo nos ultimos pregoes (colunas alinhadas a `datas`).
"""

from __future__ import annotations

import re

from boletim import b3

RX_CORRETORA = re.compile(r"\b(C{1,2}T?V?M|CTVM|CCVM|DTVM|S[./]?A\.?|LTDA\.?|CV|CTCV|DISTRIBUIDORA DE TITUL\w*|"
                          r"CORRETORA DE (CAMBIO|TITULOS|VALORES)\w*|E VALORES MOBILIARIOS|WEALTH MANAGEMEN\w*)\b|[-–]\s*BTG P\w*")


def pct(novo, velho):
    if novo is None or not velho:
        return None
    return round((novo / velho - 1.0) * 100.0, 2)


def corretora(nome) -> str:
    """'XP INVESTIMENTOS CCTVM S/A' -> 'XP Investimentos'."""
    s = RX_CORRETORA.sub(" ", str(nome or "").upper())
    s = " ".join(s.replace(".", " ").split())
    if s.isdigit() or not s:
        return f"Participante {nome}"
    return " ".join(p if len(p) <= 3 and p not in ("DE", "DO", "DA") else p.capitalize() for p in s.split())


# ------------------------------------------------------------------ serie compacta do universo

def colunas(merc: dict, antes_de: str) -> tuple[list, dict]:
    """(datas < antes_de, {ativo: {f: [...], v: [...], a: [...]}}) alinhados."""
    datas = merc.get("datas") or []
    idx = [i for i, d in enumerate(datas) if d < antes_de]
    out = {}
    for tk, s in (merc.get("ativos") or {}).items():
        out[tk] = {k: [s[k][i] if i < len(s.get(k) or []) else None for i in idx] for k in ("f", "v", "a")}
    return [datas[i] for i in idx], out


def atualizar(merc: dict, iso: str, hoje: dict, teorica: dict, manter: int = 26) -> dict:
    """Grava a coluna do pregao `iso` (substitui se ja existe) e corta a janela."""
    datas = list(merc.get("datas") or [])
    por: dict = {}
    for tk, s in (merc.get("ativos") or {}).items():
        por[tk] = {d: [s[k][i] if i < len(s.get(k) or []) else None for k in ("f", "v", "a")] for i, d in enumerate(datas)}
    for tk, (f, v, a) in hoje.items():
        velho = (por.setdefault(tk, {}).get(iso) or [None, None, None])
        # rodada parcial (sem aluguel) nao apaga o saldo que a rodada completa gravou
        por[tk][iso] = [f if f is not None else velho[0], v if v is not None else velho[1], a if a is not None else velho[2]]
    datas = sorted(set(datas) | {iso})[-manter:]
    ativos = {}
    for tk in sorted(por):
        col = [por[tk].get(d) or [None, None, None] for d in datas]
        if any(x is not None for c in col for x in c):
            ativos[tk] = {"f": [c[0] for c in col], "v": [c[1] for c in col], "a": [c[2] for c in col]}
    return {"datas": datas, "teorica": teorica or merc.get("teorica") or {}, "ativos": ativos}


def _ultimo(xs: list, n: int = 1):
    """n-esimo valor nao nulo, do fim para o comeco."""
    achados = 0
    for x in reversed(xs):
        if x is not None:
            achados += 1
            if achados == n:
                return x
    return None


# ------------------------------------------------------------------ radar

def radar(ctx, merc: dict) -> tuple[dict, dict, dict]:
    """(radar, coluna de hoje para mercado.json, quantidade teorica por ativo)."""
    cfg = ctx.cfg.get("radar") or {}
    carteira = ctx.bruto["tabelas"].get("PreviaQuadrimestral")
    ibra = b3.filho(carteira, (ctx.cfg.get("carteiras") or {}).get("IBRA", "OficialWalletIbra")) if carteira else None
    teorica = {r["TckrSymb"]: r.get("QtyTheoretical") for r in b3.registros(ibra)} if ibra else {}
    if not teorica:
        teorica = dict(merc.get("teorica") or {})
    universo = sorted(set(teorica) | set(ctx.ids))

    saldo, taxa = {}, {}
    pos_tab, novos_tab = ctx.tab("BTBLendingOpenPosition"), ctx.tab("BTBLoanBalance")
    total_rs = 0.0
    for r in b3.registros(pos_tab) if pos_tab else []:
        if r.get("Market") == "Total":
            saldo[r["TckrSymb"]] = (r.get("StockBalance"), r.get("Balance"))
            total_rs += r.get("Balance") or 0.0
    for r in b3.registros(novos_tab) if novos_tab else []:
        if r.get("TkrAvrgRate") is not None:
            taxa[r["TckrSymb"]] = round(r["TkrAvrgRate"] * 100.0, 2)

    _, hist = colunas(merc, ctx.iso)
    hoje, linhas = {}, []
    for tk in universo:
        r = ctx.trades.get(tk)
        if r and r.get("SgmtNm") != "CASH":
            r = None
        fech = b3.num(r.get("LastPric")) if r else None
        vol = b3.num(r.get("NtlFinVol")) if r else None
        alug_qtd, alug_rs = saldo.get(tk, (None, None))
        hoje[tk] = (fech, round(vol / 1e3) if vol else None, round(alug_qtd / 1e3) if alug_qtd else None)
        h = hist.get(tk) or {"f": [], "v": [], "a": []}
        vols = [x for x in h["v"][-20:] if x]
        media = sum(vols) / len(vols) * 1e3 if len(vols) >= ctx.lim.get("volume_base_minima", 10) else None
        a1, a5 = _ultimo(h["a"]), _ultimo(h["a"], 5)
        f5 = _ultimo(h["f"], 5)
        item = {"ativo": tk, "fechamento": fech, "oscilacao_pct": b3.num(r.get("OscnPctg")) if r else None,
                "volume_rs": vol, "volume_x_media": round(vol / media, 2) if vol and media else None,
                "preco_5d_pct": pct(fech, f5), "saldo_rs": alug_rs,
                "aluguel_var_dia_pct": pct(alug_qtd / 1e3, a1) if alug_qtd else None,
                "aluguel_var_5d_pct": pct(alug_qtd / 1e3, a5) if alug_qtd else None,
                "taxa": taxa.get(tk), "do_livro": tk in ctx.ids}
        if alug_qtd and teorica.get(tk):
            item["pct_free_float"] = round(alug_qtd / teorica[tk] * 100.0, 2)
        if alug_qtd and media and fech:
            item["pregoes_de_giro"] = round(alug_qtd / (media / fech), 1)
        linhas.append(item)

    def topo(filtro, chave, n=10, inverso=True):
        ls = [l for l in linhas if filtro(l) and l.get(chave) is not None]
        return sorted(ls, key=lambda l: -l[chave] if inverso else l[chave])[:n]

    vol_min, saldo_min = cfg.get("volume_minimo_rs", 20e6), cfg.get("saldo_minimo_rs", 50e6)
    out = {
        "universo": len(universo), "fonte_universo": "IBrA (carteira teórica da B3) e ativos B3 do livro",
        "volume": topo(lambda l: (l["volume_rs"] or 0) >= vol_min and (l["volume_x_media"] or 0) >= cfg.get("volume_x_media", 2.0),
                       "volume_x_media"),
        "aluguel_alta": topo(lambda l: (l["saldo_rs"] or 0) >= saldo_min and (l["aluguel_var_dia_pct"] or 0) >= cfg.get("aluguel_var_dia_pct", 5.0),
                             "aluguel_var_dia_pct"),
        "aluguel_queda": topo(lambda l: (l["saldo_rs"] or 0) >= saldo_min and (l["aluguel_var_dia_pct"] or 0) <= -cfg.get("aluguel_var_dia_pct", 5.0),
                              "aluguel_var_dia_pct", inverso=False),
        "aluguel_float": topo(lambda l: (l["saldo_rs"] or 0) >= cfg.get("saldo_minimo_float_rs", 20e6), "pct_free_float", n=12),
        "aluguel_taxa": topo(lambda l: (l["saldo_rs"] or 0) >= cfg.get("saldo_minimo_float_rs", 20e6), "taxa"),
        "vendidos_pressionados": topo(lambda l: (l.get("pct_free_float") or 0) >= cfg.get("float_alto_pct", 8.0)
                                      and (l["preco_5d_pct"] or 0) >= cfg.get("preco_5d_pct", 5.0), "preco_5d_pct", n=8),
        "aposta_vendida_crescendo": topo(lambda l: (l["saldo_rs"] or 0) >= saldo_min
                                         and (l["aluguel_var_5d_pct"] or 0) >= cfg.get("aluguel_var_5d_pct", 20.0)
                                         and (l["preco_5d_pct"] or 0) <= -cfg.get("preco_5d_pct", 5.0), "aluguel_var_5d_pct", n=8),
        "aluguel_total_rs": round(total_rs, 0) if pos_tab else None, "papeis_com_aluguel": len(saldo) if pos_tab else None,
        "pregoes_no_historico": len(colunas(merc, ctx.iso)[0]),
    }
    ant = ctx.anterior("aluguel_total")
    if out["aluguel_total_rs"] and ant[1]:
        out["aluguel_total_var_pct"], out["comparado_com"] = pct(out["aluguel_total_rs"], ant[1]), ant[0]
    return out, hoje, teorica


# ------------------------------------------------------------------ opcoes do mercado

def opcoes_mercado(ctx) -> dict:
    """Posicao em aberto de todas as opcoes sobre acoes e indice: por ativo e as maiores mudancas."""
    if not ctx.pos or not ctx.opc_todas:
        return {}
    por: dict = {}
    series = {}
    por_venc: dict = {}
    for cod, (under, tipo, venc, strike) in ctx.opc_todas.items():
        p = ctx.pos.get(cod)
        oi = b3.num(p.get("TtlPos")) if p else None
        if not oi or not venc or venc < ctx.iso:
            continue
        series[cod] = oi
        a = por.setdefault(under, {"ativo": under, "call": 0.0, "put": 0.0})
        a[tipo] += oi
        v = por_venc.setdefault(venc[:10], {"call": 0.0, "put": 0.0})
        v[tipo] += oi
    total_c, total_p = sum(a["call"] for a in por.values()), sum(a["put"] for a in por.values())
    ativos = sorted(por.values(), key=lambda a: -(a["call"] + a["put"]))[:(ctx.cfg.get("radar") or {}).get("opcoes_ativos", 12)]
    for a in ativos:
        a["put_call"] = round(a["put"] / a["call"], 2) if a["call"] else None
        a["do_livro"] = a["ativo"] in ctx.ids
    out = {"posicao_call": total_c, "posicao_put": total_p, "put_call": round(total_p / total_c, 2) if total_c else None,
           "series_com_posicao": len(series), "por_ativo": ativos,
           # calendario: onde a posicao do mercado vence (os seis maiores vencimentos, em ordem de data)
           "por_vencimento": [[v, por_venc[v]["call"], por_venc[v]["put"]] for v in sorted(
               sorted(por_venc, key=lambda v: -(por_venc[v]["call"] + por_venc[v]["put"]))[:6])]}
    vc = vp = 0.0
    for cod, (under, tipo, _, _) in ctx.opc_todas.items():
        t = ctx.trades.get(cod)
        if t:
            v = b3.num(t.get("NtlFinVol")) or 0.0
            vc, vp = (vc + v, vp) if tipo == "call" else (vc, vp + v)
    out.update(volume_call_rs=round(vc, 0), volume_put_rs=round(vp, 0),
               put_call_volume=round(vp / vc, 2) if vc else None)
    ant = ctx.pos_anterior
    if ant:
        mud = []
        for cod, oi in series.items():
            antes = b3.num((ant.get(cod) or {}).get("TtlPos")) or 0.0
            if oi != antes:
                under, tipo, venc, strike = ctx.opc_todas[cod]
                mud.append({"codigo": cod, "ativo": under, "tipo": tipo, "vencimento": venc, "strike": strike,
                            "posicao": oi, "variacao": oi - antes, "do_livro": under in ctx.ids})
        for cod, p in ant.items():
            if cod in ctx.opc_todas and cod not in series:
                antes = b3.num(p.get("TtlPos")) or 0.0
                under, tipo, venc, strike = ctx.opc_todas[cod]
                if antes and venc and venc >= ctx.iso:
                    mud.append({"codigo": cod, "ativo": under, "tipo": tipo, "vencimento": venc, "strike": strike,
                                "posicao": 0.0, "variacao": -antes, "do_livro": under in ctx.ids})
        out["maiores_altas"] = sorted(mud, key=lambda m: -m["variacao"])[:10]
        out["maiores_quedas"] = sorted(mud, key=lambda m: m["variacao"])[:10]
        out["comparado_com"] = ctx.bruto.get("pos_anterior_data")
        ctx.mudancas_oi = mud
    return out


# ------------------------------------------------------------------ corretoras no aluguel

def corretoras(ctx, destaque: list[str]) -> dict:
    """Quem doou e quem tomou acoes emprestadas no dia, por corretora (tabela BTBTrade)."""
    t = ctx.tab("BTBTrade")
    if not t or not t["linhas"]:
        return {}
    if t.get("truncada"):
        ctx.lacunas.append("Aluguel por corretora: a tabela passou do teto de páginas; a contagem do dia está incompleta.")
    alvo = set(destaque)
    tom, doa, por_ativo, total = {}, {}, {}, 0.0
    for r in b3.registros(t):
        tk, qtd = r.get("TckrSymb"), r.get("Quantity") or 0.0
        preco = b3.num((ctx.trades.get(tk) or {}).get("LastPric"))
        if not preco or not qtd:
            continue
        rs = qtd * preco
        total += rs
        t_nome, d_nome = corretora(r.get("EntryBuyerNm") or r.get("EntryBuyer")), corretora(r.get("EntrySellerNm") or r.get("EntrySeller"))
        tom[t_nome] = tom.get(t_nome, 0.0) + rs
        doa[d_nome] = doa.get(d_nome, 0.0) + rs
        if tk in alvo:
            a = por_ativo.setdefault(tk, {"negocios": 0, "quantidade": 0.0, "tom": {}, "doa": {}, "_tq": 0.0})
            a["negocios"] += 1
            a["quantidade"] += qtd
            a["_tq"] += (r.get("Rate") or 0.0) * qtd
            a["tom"][t_nome] = a["tom"].get(t_nome, 0.0) + qtd
            a["doa"][d_nome] = a["doa"].get(d_nome, 0.0) + qtd

    def topo(d: dict, base: float, n: int) -> list:
        return [[k, round(v / base * 100.0, 1)] for k, v in sorted(d.items(), key=lambda kv: -kv[1])[:n]] if base else []

    ativos = {}
    for tk, a in por_ativo.items():
        q = a["quantidade"]
        ativos[tk] = {"negocios": a["negocios"], "quantidade": q, "taxa_media": round(a["_tq"] / q * 100.0, 2) if q else None,
                      "tomadoras": topo(a["tom"], q, 3), "doadoras": topo(a["doa"], q, 3)}
    return {"volume_rs": round(total, 0), "negocios": len(t["linhas"]),
            "tomadoras": [[k, round(v, 0), round(v / total * 100.0, 1)] for k, v in sorted(tom.items(), key=lambda kv: -kv[1])[:8]],
            "doadoras": [[k, round(v, 0), round(v / total * 100.0, 1)] for k, v in sorted(doa.items(), key=lambda kv: -kv[1])[:8]],
            "ativos": ativos, "fonte": ctx.fonte("BTBTrade"),
            "nota": "Corretora é o intermediário: mostra por onde o aluguel passou, não quem é o investidor final. "
                    "Valor = quantidade emprestada no dia vezes o fechamento."}
