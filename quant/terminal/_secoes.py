"""Cada pedaco da ficha: le os arquivos do terminal e devolve (dict | None, motivo | None).

Contrato de todos os pedacos
  - `fonte`, `data` (a data DO DADO, nao a da leitura) e `idade_dias` em todo dict devolvido;
  - dado mais velho que o limite de `_leitor.LIMITES_DIAS` vira None com o motivo (nunca um numero velho vestido de novo);
  - o que o arquivo nao traz fica None dentro do dict; nada e estimado, copiado de outro dia ou preenchido de memoria;
  - percentual em pontos (7.4 = 7,4%), dinheiro em reais (unidade cheia), datas ISO.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Callable

from . import _leitor as L

TERMINAL = "Autopilot Terminal"
_CODIGO_CICLO = {"pico_provavel": 2, "pico_possivel": 1, "normal": 0, "fundo": -1}
_ORGAOS_GESTAO = ("conselho", "diretoria", "fiscal", "orgaos", "sem")        # tudo que nao e controlador nem a propria companhia
_LADO_COMPRA = re.compile(r"^compra( (\u00e0|a) (vista|termo))?$")
_LADO_VENDA = re.compile(r"^venda( (\u00e0|a) (vista|termo))?$")
JANELA_INSIDERS_DIAS = 90
CONFIANCA_MOMENTO_MIN = 0.6          # abaixo disto o "momento do resultado" estimado nao vira True/False: fica None
JANELA_NOTICIAS_DIAS = 7


class Ctx:
    """Estado de uma consulta: o dia de referencia e os indices montados uma vez (valem para varios tickers)."""

    def __init__(self, hoje: date | None = None):
        self.hoje = hoje or L.hoje()
        self._idx: dict[str, Any] = {}

    def memo(self, nome: str, fn: Callable[[], Any]) -> Any:
        if nome not in self._idx:
            self._idx[nome] = fn()
        return self._idx[nome]

    # -- indices
    def universo(self) -> dict[str, dict]:
        def f():
            d = L.ler("universo.json") or {}
            return {i["s"]: i for i in d.get("itens") or [] if isinstance(i, dict) and i.get("s")}
        return self.memo("universo", f)

    def eventos_por_ticker(self) -> dict[str, list[dict]]:
        def f():
            d = L.ler("pagina/eventos.json") or {}
            out: dict[str, list[dict]] = {}
            for x in d.get("itens") or []:
                tks = set(x.get("tickers") or [])
                if x.get("ticker"):
                    tks.add(x["ticker"])
                for t in tks:
                    out.setdefault(t, []).append(x)
            return out
        return self.memo("eventos_por_ticker", f)

    def noticias_por_ticker(self) -> dict[str, dict[str, dict]]:
        """ticker -> {id: item}, juntando o arquivo de noticias recentes (com ticker e nota de regra) e o por ativo (janela longa)."""
        def f():
            out: dict[str, dict[str, dict]] = {}
            bruto = L.ler("noticias.json") or {}
            for x in bruto.get("itens") or []:
                if not x.get("id"):
                    continue
                for t in x.get("tickers") or []:
                    out.setdefault(t, {})[x["id"]] = dict(x, _regra=True)
            longo = L.ler("noticias_ativos.json") or {}
            for t, bloco in (longo.get("ativos") or {}).items():
                for x in (bloco.get("itens") if isinstance(bloco, dict) else bloco) or []:
                    if x.get("id") and x["id"] not in out.get(t, {}):
                        out.setdefault(t, {})[x["id"]] = dict(x, _regra=False)
            return out
        return self.memo("noticias_por_ticker", f)

    def notas_agente(self) -> dict[str, Any]:
        d = L.ler_arquivo_da_cache("cache/notas_agente.json")
        return d if isinstance(d, dict) else {}


def antes_da_abertura(momento: str | None, confianca: Any) -> bool | None:
    """O resultado sai antes da abertura do pregao? True / False pelo momento estimado do terminal (moda das ultimas 8 entregas com hora);
    None quando nao ha estimativa ou a confianca (iguais / entregas com hora) e menor que CONFIANCA_MOMENTO_MIN."""
    c = L.num(confianca)
    if not momento or c is None or c < CONFIANCA_MOMENTO_MIN:
        return None
    return momento == "antes da abertura"


def _momento(x: dict) -> dict:
    """Os campos do momento do resultado de um evento do calendario (ESTIMATIVA; so e informacao da companhia quando a origem diz)."""
    m, conf = x.get("momento_estimado"), L.num(x.get("momento_confianca"))
    return {"momento_estimado": m, "momento_confianca": conf, "momento_origem": x.get("momento_origem"),
            "momento_iguais": L.inteiro(x.get("momento_iguais")), "momento_entregas": L.inteiro(x.get("momento_entregas")),
            "antes_da_abertura": antes_da_abertura(m, conf)}


def _cab(fonte: str, data: Any, c: Ctx) -> dict:
    d = L.como_data(data)
    return {"fonte": fonte, "data": d.isoformat() if d else None, "idade_dias": None if d is None else (c.hoje - d).days}


def _velho(tipo: str, dia: Any, c: Ctx, o_que: str = "o dado") -> str | None:
    """Motivo de descarte, ou None se o dado ainda vale."""
    lim = L.LIMITES_DIAS[tipo]
    d = L.como_data(dia)
    if d is None:
        return f"{o_que} sem data: nao da para saber se esta atual"
    idade = (c.hoje - d).days
    if idade > lim:
        return f"{o_que} e de {d.isoformat()} ({idade} dias), acima do limite de {lim} dias para '{tipo}'"
    return None


def _por_ativo(modulo: str, chave: str) -> Any | None:
    return L.ler(f"porativo/{modulo}/{chave}.json", memo=False)


# --------------------------------------------------------------------------- identidade

def identidade(c: Ctx, t: str) -> dict | None:
    it = c.universo().get(t)
    if not it:
        return None
    return {"nome": it.get("n"), "classe": it.get("c"), "setor": it.get("g"), "subsetor": it.get("sg"),
            "moeda": it.get("m"), "indices": it.get("idx") or [], "isin": it.get("isin")}


# --------------------------------------------------------------------------- TIR real

def sec_tir(c: Ctx, t: str) -> tuple[dict | None, str | None]:
    d = L.ler("pagina/tir.json")
    if not isinstance(d, dict) or not d.get("empresas"):
        return None, "arquivo da TIR (cache/out/pagina/tir.json) ausente ou vazio"
    e = d["empresas"].get(t)
    if e is None:
        fora = next((x for x in d.get("fora") or [] if x.get("t") == t), None)
        if fora:
            return None, f"fora do modelo de TIR: {fora.get('motivo')}"
        return None, f"o modelo de TIR nao cobre {t} (cobre {len(d['empresas'])} empresas)"
    ref = e.get("preco_data") or d.get("gerado")
    motivo = _velho("tir", ref, c, "o preco da TIR")
    if motivo:
        return None, motivo
    g = d.get("geral") or {}
    nt = g.get("ntnb") or {}
    ntnb = L.arred(nt.get("taxa"), 4)
    ciclo = e.get("ciclo_do_lucro") or {}
    nivel = ciclo.get("nivel")
    marca = "pico" if nivel in ("pico_provavel", "pico_possivel") else "fundo" if nivel == "fundo" else None
    tir = e.get("tir") or {}
    tp = e.get("tir_prudente") or {}
    cx = e.get("caixa") or {}
    # desde 11/10/2026 o numero principal do terminal e a taxa com terminal endogeno (`principal`); `menor` (a menor entre a saida
    # por P/L e a saida a NTN-B + 5) ficou so por compatibilidade e subestimava (relatorios/tir_auditoria no terminal).
    def _principal(d):
        d = d or {}
        return d.get("principal") if d.get("principal") is not None else d.get("menor")
    hoje_pct = L.pct(_principal(tir))
    out = _cab("Autopilot Terminal, modulo tir (cache/out/pagina/tir.json)", ref, c)
    out.update({
        "gerado": d.get("gerado"), "preco": L.arred(e.get("preco"), 4),
        "tir_hoje_pct": hoje_pct,
        "tir_normalizada_pct": L.pct(_principal((e.get("tir_normalizada") or {}).get("tir"))),
        "tir_pl_historico_pct": L.pct(tir.get("pl")),
        "tir_saida_conservadora_pct": L.pct(tir.get("perp")),
        "tir_prudente": {"pct": L.pct(tp.get("v")), "base": tp.get("base"), "pico": bool(tp.get("pico")) if tp else None,
                         "premio_pp": L.arred(tp.get("premio_pp"))},
        "premio_hoje_pp": None if hoje_pct is None or ntnb is None else round(hoje_pct - ntnb, 2),
        "ntnb": {"taxa_pct": ntnb, "vencimento": nt.get("venc"), "data": nt.get("data")},
        "ciclo_do_lucro": {"nivel": nivel, "marca": marca, "codigo": _CODIGO_CICLO.get(nivel), "criterios": ciclo.get("criterios") or [],
                           "razao_lucro_12m_sobre_media_5a": L.arred(ciclo.get("razao"), 3),
                           "margem_12m_pct": L.arred(ciclo.get("margem_12m")), "margem_mediana_5a_pct": L.arred(ciclo.get("margem_mediana_5a")),
                           "roe_12m_pct": L.arred(ciclo.get("roe_12m")), "roe_mediano_5a_pct": L.arred(ciclo.get("roe_mediano_5a")),
                           "nota": ciclo.get("nota")},
        "base": {"fonte": (e.get("base") or {}).get("fonte"), "casas": L.inteiro(e.get("casas")), "texto": (e.get("base") or {}).get("texto")},
        "balanco": e.get("balanco"), "balanco_idade_dias": L.inteiro(e.get("balanco_idade_dias")),
        "premissas": {"g1_pct": L.pct(e.get("g1")), "g_lp_pct": L.pct(e.get("g_lp")), "payout_pct": L.pct(e.get("payout")),
                      "roe_pct": L.pct(e.get("roe")), "mult_pl": L.arred(e.get("mult")), "k_real_pct": L.pct(e.get("k")),
                      "ciclica": e.get("ciclica"), "virada": e.get("virada"), "qualidade": e.get("qualidade")},
        "caixa": {"tir_g0_pct": L.pct(cx.get("tir_g0")), "tir_g2_pct": L.pct(cx.get("tir_g2")), "dif_pp": L.arred(cx.get("dif_pp")),
                  "diverge": cx.get("diverge"), "metodo": cx.get("metodo")} if cx else None,
        "avisos": list(e.get("avisos") or []),
    })
    return out, None


# --------------------------------------------------------------------------- consenso

def _per(est: dict | None, p: str) -> dict | None:
    for x in (est or {}).get("per") or []:
        if x.get("p") == p:
            return x
    return None


def _v(v: Any, i: int) -> float | None:
    return L.num(v[i]) if isinstance(v, list) and len(v) > i else None


def _var_pct(agora: float | None, antes: float | None) -> float | None:
    """Mesma conta do terminal: (agora - antes) / |antes|; sem valor quando o sinal troca ou a base e quase zero."""
    if agora is None or antes is None or abs(antes) < 0.005 or (agora > 0) != (antes > 0):
        return None
    return round((agora - antes) / abs(antes) * 100.0, 2)


def _lpa(p: dict | None) -> dict | None:
    if not p or not p.get("l"):
        return None
    l, tend, rev = p["l"], p.get("t") or [], p.get("v") or []
    med = _v(l, 0)
    return {"fim": p.get("fim"), "medio": L.arred(med, 4), "minimo": L.arred(_v(l, 1), 4), "maximo": L.arred(_v(l, 2), 4),
            "analistas": L.inteiro(_v(l, 3)), "um_ano_antes": L.arred(_v(l, 4), 4),
            "revisao_7d_pct": _var_pct(med, _v(tend, 0)), "revisao_30d_pct": _var_pct(med, _v(tend, 1)),
            "revisao_60d_pct": _var_pct(med, _v(tend, 2)), "revisao_90d_pct": _var_pct(med, _v(tend, 3)),
            "subiram_7d": L.inteiro(_v(rev, 0)), "cortaram_7d": L.inteiro(_v(rev, 1)),
            "subiram_30d": L.inteiro(_v(rev, 2)), "cortaram_30d": L.inteiro(_v(rev, 3)), "pl_projetado": L.arred(p.get("pl"))}


def sec_consenso(c: Ctx, t: str) -> tuple[dict | None, str | None]:
    d = _por_ativo("consenso", t)
    if not isinstance(d, dict):
        return None, "sem registro de consenso para este ticker (cache/out/porativo/consenso/)"
    via = None
    if d.get("ref"):                                   # BDR: o consenso e o do papel la fora
        via = d["ref"]
        d = _por_ativo("consenso", via)
        if not isinstance(d, dict):
            return None, f"BDR de {via}: o consenso do papel la fora ainda nao foi coletado"
    if not (d.get("alvo") or d.get("rec") or d.get("est")):
        return None, d.get("sem") or "o agregador nao tem analistas cobrindo este papel"
    col = L.como_data(d.get("col"))
    motivo = _velho("consenso", col, c, "a coleta do consenso")
    if motivo:
        return None, motivo
    out = _cab("Yahoo Finance via Autopilot Terminal, modulo consenso (agregador, nao e dado oficial)", col, c)
    alvo, rec, est = d.get("alvo") or {}, d.get("rec") or {}, d.get("est")
    pcs = rec.get("pc") or []
    out.update({
        "lastro": via, "moeda": d.get("moeda"), "preco": L.arred(d.get("preco"), 4), "preco_data": d.get("preco_t"),
        "alvo": {"medio": L.arred(alvo.get("med")), "mediano": L.arred(alvo.get("mdn")), "minimo": L.arred(alvo.get("min")),
                 "maximo": L.arred(alvo.get("max")), "analistas": L.inteiro(alvo.get("n")), "potencial_pct": L.arred(alvo.get("pot"))} if alvo else None,
        "recomendacao": {"nota_1_compra_forte_a_5_venda": L.arred(rec.get("nota")), "rotulo": rec.get("rot"),
                         "pct_compra": L.arred(pcs[0], 1) if pcs else None,
                         "pct_compra_ha_3_meses": L.arred(pcs[3], 1) if len(pcs) > 3 else None} if rec else None,
        "lpa_ano_corrente": _lpa(_per(est, "0y")), "lpa_ano_seguinte": _lpa(_per(est, "+1y")),
        "lpa_proximo_trimestre": _lpa(_per(est, "0q")),
    })
    h = d.get("hist") or {}
    ts, am = h.get("t") or [], h.get("am") or []
    pares = [(x, y) for x, y in zip(ts, am) if L.num(y) is not None]
    if len(pares) >= 2 and alvo.get("med"):
        out["alvo_desde_o_primeiro_retrato"] = {"desde": pares[0][0], "alvo_inicial": pares[0][1], "variacao_pct": _var_pct(L.num(alvo["med"]), L.num(pares[0][1])),
                                                 "retratos": len(pares)}
    avisos = list(d.get("avisos") or [])
    if alvo.get("n") is not None and alvo["n"] < 3:
        avisos.append(f"preco-alvo de {int(alvo['n'])} analista(s): nao e consenso")
    if via and d.get("moeda") and d["moeda"] != "BRL":
        avisos.append(f"alvo e lucro em {d['moeda']}, do papel la fora ({via}); nao comparar com o preco do BDR")
    out["avisos"] = avisos
    return out, None


# --------------------------------------------------------------------------- insiders

def _empresa_de(c: Ctx, t: str) -> str:
    m = (L.ler("multiplos.json") or {}).get("a", {}).get(t) or {}
    return m.get("raiz") or L.raiz_do_ticker(t)


def sec_insiders(c: Ctx, t: str) -> tuple[dict | None, str | None]:
    ident = c.universo().get(t) or {}
    if ident.get("c") not in (None, "acao_br"):
        return None, "negociacao de insiders (CVM, art. 11 da Res. 44) so existe para acao brasileira"
    d = _por_ativo("insidersbr", _empresa_de(c, t))
    if not isinstance(d, dict):
        return None, "sem formulario de negociacao de insiders para esta empresa"
    if d.get("vazio"):
        return None, d.get("aviso") or "a empresa nao entregou formulario de insiders"
    ate = d.get("ate")
    fim = L.fim_do_mes(ate) if ate else None
    motivo = _velho("insiders", fim, c, f"o ultimo formulario (mes {ate})") if fim else "formulario sem mes de referencia"
    if motivo:
        return None, motivo
    dic = d.get("dic") or {}
    orgaos = (L.ler("porativo/insidersbr/_comum.json") or {}).get("orgaos") or ["controlador", "conselho", "diretoria", "fiscal", "orgaos", "sem", "tesouraria"]
    inicio = (c.hoje - timedelta(days=JANELA_INSIDERS_DIAS)).isoformat()
    por: dict[str, dict] = {}
    compras = vendas = 0.0
    n = n_sem_preco = 0
    parcial_mes = False
    for ln in d.get("mov") or []:
        if len(ln) < 5 or not ln[0] or ln[0] < inicio or ln[0] > c.hoje.isoformat():
            continue
        ativos = dic.get("ativos") or []
        classe, papel = (ativos[ln[2]] if isinstance(ln[2], int) and ln[2] < len(ativos) else ["outro", "?"])
        if classe != "acao":
            continue
        op = (dic.get("ops") or [""])[ln[3]] if isinstance(ln[3], int) and ln[3] < len(dic.get("ops") or []) else ""
        marcas = ln[8] if len(ln) > 8 and ln[8] else 0
        qtd, preco = L.num(ln[4]), L.num(ln[5]) if len(ln) > 5 else None
        if marcas & 32:
            parcial_mes = True
        if marcas & 1 or qtd is None:                           # preco a mais de 25% do fechamento do dia: nao entra no valor
            continue
        lado = 1 if _LADO_COMPRA.match(op) else -1 if _LADO_VENDA.match(op) else None
        if lado is None:
            if marcas & 16:                                     # o formulario nao diz o sentido
                continue
            lado = 1 if qtd > 0 else -1
        if preco is None:
            n_sem_preco += 1
            continue
        valor = abs(qtd) * preco * lado
        org = orgaos[ln[1]] if isinstance(ln[1], int) and ln[1] < len(orgaos) else "sem"
        o = por.setdefault(org, {"saldo_rs": 0.0, "compras_rs": 0.0, "vendas_rs": 0.0, "negocios": 0})
        o["saldo_rs"] += valor
        o["compras_rs" if valor > 0 else "vendas_rs"] += abs(valor)
        o["negocios"] += 1
        compras += valor if valor > 0 else 0.0
        vendas += -valor if valor < 0 else 0.0
        n += 1
    out = _cab("CVM, formulario mensal de valores mobiliarios negociados (art. 11 da Res. CVM 44), via Autopilot Terminal", fim, c)
    gestao = sum(v["saldo_rs"] for k, v in por.items() if k in _ORGAOS_GESTAO)
    out.update({
        "formulario_ate": ate, "idade_dias": (c.hoje - fim).days, "entregue_em": (d.get("entrega") or {}).get("data"), "janela_dias": JANELA_INSIDERS_DIAS,
        "janela_efetiva": [inicio, fim.isoformat()],
        "saldo_90d_rs": round(compras - vendas, 0), "compras_90d_rs": round(compras, 0), "vendas_90d_rs": round(vendas, 0),
        "saldo_gestao_90d_rs": round(gestao, 0), "negocios_90d": n,
        "por_orgao": {k: {kk: (round(vv, 0) if isinstance(vv, float) else vv) for kk, vv in v.items()} for k, v in sorted(por.items())},
        "sem_preco_fora_da_conta": n_sem_preco,
        "como_ler": ["o formulario de um mes chega ate o dia 10 do mes seguinte: a janela efetiva termina no fim do mes do ultimo formulario, nao hoje",
                     "saldo = compras menos vendas em reais (quantidade x preco de cada negocio); `gestao` exclui o controlador e a propria companhia"],
        "avisos": (["parte dos negocios do periodo vem somada por mes (companhia com muitos negocios)"] if parcial_mes else [])
        + ([f"{n_sem_preco} negocio(s) sem preco no formulario ficaram fora do valor"] if n_sem_preco else []),
    })
    return out, None


# --------------------------------------------------------------------------- aluguel

def sec_aluguel(c: Ctx, t: str) -> tuple[dict | None, str | None]:
    d = L.ler("b3_aluguel.json")
    if not isinstance(d, dict) or not d.get("a"):
        return None, "arquivo de aluguel (cache/out/b3_aluguel.json) ausente ou vazio"
    motivo = _velho("aluguel", d.get("data"), c, "a posicao de aluguel")
    if motivo:
        return None, motivo
    x = d["a"].get(t)
    if x is None:
        return None, f"sem saldo alugado na B3 em {d.get('data')}"
    out = _cab("B3, BDI (BTBLoanBalance/BTBLendingOpenPosition), via Autopilot Terminal", d.get("data"), c)
    h = [L.num(v) for v in x.get("h") or [] if L.num(v) is not None]
    out.update({
        "saldo_quantidade": L.inteiro(x.get("saldo_qtd")), "saldo_rs": L.arred(x.get("saldo_rs"), 0),
        "taxa_aa_pct": L.arred(x.get("taxa"), 4), "taxa_min_aa_pct": L.arred(x.get("taxa_min"), 4), "taxa_max_aa_pct": L.arred(x.get("taxa_max"), 4),
        "taxa_calculada_no_dia": (L.num(x.get("contratos")) or 0) > 0,
        "contratos_no_dia": L.inteiro(x.get("contratos")),
        "var_1d_pct": L.arred(x.get("var_d1_pct")), "var_5d_pct": L.arred(x.get("var_5d_pct")), "var_20d_pct": L.arred(x.get("var_20d_pct")),
        "pct_float": L.arred(x.get("pct_float")), "dias_para_cobrir": L.arred(x.get("dias_para_cobrir")),
        "saldo_vs_media_21d_pct": round((h[-1] / (sum(h) / len(h)) - 1) * 100, 1) if len(h) >= 5 and sum(h) else None,
        "como_ler": ["a taxa e a do tomador, em % ao ano; sem negocio no dia a B3 repete a ultima taxa calculada (taxa_calculada_no_dia = False)"],
    })
    return out, None


# --------------------------------------------------------------------------- noticias

def _nota_regra(x: dict) -> int:
    """Mesma regra do terminal (coletor/notas.py::nota_regra) para a manchete sem nota do agente."""
    if x.get("tipo") == "cvm":
        return 2 if "fato relevante" in (x.get("titulo") or "").lower() else 1
    if x.get("tipo") == "oficial":
        return 2
    peso = x.get("peso") or 0
    return 2 if peso >= 62 else 1 if peso >= 36 else 0


def sec_noticias(c: Ctx, t: str) -> tuple[dict | None, str | None]:
    bruto = L.ler("noticias.json")
    longo = L.ler("noticias_ativos.json")
    if not isinstance(bruto, dict) and not isinstance(longo, dict):
        return None, "arquivos de noticias ausentes"
    ref = (bruto or {}).get("gerado") or (longo or {}).get("gerado")
    motivo = _velho("noticias", ref, c, "o arquivo de noticias")
    if motivo:
        return None, motivo
    notas = c.notas_agente()
    corte = datetime.combine(c.hoje - timedelta(days=JANELA_NOTICIAS_DIAS - 1), datetime.min.time(), tzinfo=L.FUSO_BRT)
    itens, soma, pont, mx, n3, n2, nag = [], 0, 0, None, 0, 0, 0
    for x in c.noticias_por_ticker().get(t, {}).values():
        try:
            ts = datetime.fromisoformat(x.get("ts"))
        except (TypeError, ValueError):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=L.FUSO_BRT)
        if ts < corte:
            continue
        r = notas.get(x.get("id") or "")
        if isinstance(r, dict) and isinstance(r.get("n"), int):
            nota, agente = max(0, min(3, r["n"])), True
        elif x.get("_regra"):
            nota, agente = _nota_regra(x), False
        else:
            nota, agente = None, False
        if nota is not None:
            pont += 1
            soma += nota
            mx = nota if mx is None else max(mx, nota)
            n3 += nota == 3
            n2 += nota == 2
            nag += agente
        itens.append({"data": ts.astimezone(L.FUSO_BRT).strftime("%Y-%m-%d"), "hora": ts.astimezone(L.FUSO_BRT).strftime("%H:%M"), "nota": nota,
                      "nota_do_agente": agente, "fonte": x.get("fonte"), "titulo": x.get("titulo"),
                      "link": x.get("link") if len(x.get("link") or "") <= 250 else None, "_ts": ts})
    itens.sort(key=lambda z: (-(z["nota"] if z["nota"] is not None else -1), -z["_ts"].timestamp()))
    top = [{k: v for k, v in i.items() if k != "_ts"} for i in itens[:5]]
    out = _cab("Autopilot Terminal (manchetes de veiculos de noticia; nota 0 a 3 de 'faz preco' do agente ou da regra do terminal)", ref, c)
    out.update({"janela_dias": JANELA_NOTICIAS_DIAS, "n_7d": len(itens), "n_pontuadas_7d": pont, "score_7d": soma if pont else None,
                "max_7d": mx, "n_nota3_7d": n3, "n_nota2_7d": n2, "n_pontuadas_pelo_agente_7d": nag, "principais": top,
                "como_ler": ["a nota do agente guarda so alguns dias e o arquivo recente cobre cerca de 72 horas: manchete mais antiga entra na contagem, sem nota",
                             "nota 3 = faz preco agora, 2 = relevante, 1 = contexto, 0 = fora do mercado; titulo e fato noticiado, nao recomendacao"]})
    return out, None


# --------------------------------------------------------------------------- eventos do ticker

def sec_proximo_resultado(c: Ctx, t: str) -> tuple[dict | None, str | None]:
    d = L.ler("pagina/eventos.json")
    if not isinstance(d, dict):
        return None, "calendario de eventos (cache/out/pagina/eventos.json) ausente"
    motivo = _velho("eventos", d.get("gerado"), c, "o calendario de eventos")
    if motivo:
        return None, motivo
    hoje_s = c.hoje.isoformat()
    meus = sorted((x for x in c.eventos_por_ticker().get(t, []) if x.get("data")), key=lambda z: (z["data"], z.get("hora") or ""))
    resultados = [x for x in meus if x.get("tipo") == "resultado"]
    prox = next((x for x in resultados if x["data"] >= hoje_s and not x.get("saiu")), None)
    ultimo = next((x for x in reversed(resultados) if x["data"] <= hoje_s and x.get("saiu")), None)
    raiz = _empresa_de(c, t)
    rea = (d.get("reacoes") or {}).get(raiz)
    out = _cab("Autopilot Terminal, modulo eventos (calendarios da CVM, RAD e Yahoo)", d.get("gerado"), c)
    ev_prox = []
    for x in meus:
        if x["data"] >= hoje_s and x.get("tipo") != "resultado":
            ev_prox.append({"data": x["data"], "tipo": x["tipo"], "hora": x.get("hora"), "dias_ate": (date.fromisoformat(x["data"]) - c.hoje).days,
                            "detalhe": x.get("det")})
    tele = next((x for x in meus if x.get("tipo") == "teleconferencia" and x["data"] >= hoje_s), None)
    out.update({
        "proximo": None if prox is None else {
            "data": prox["data"], "hora": prox.get("hora"), "periodo": prox.get("periodo"), "dias_ate": (date.fromisoformat(prox["data"]) - c.hoje).days,
            "confirmado": prox.get("confirmado"), "fonte": prox.get("fonte"), **_momento(prox),
            "teleconferencia": None if tele is None else {"data": tele["data"], "hora": tele.get("hora")}},
        "ultimo": None if ultimo is None else {"data": ultimo["data"], "hora": ultimo.get("hora"), "periodo": ultimo.get("periodo"),
                                               "reacao": ultimo.get("reacao")},
        "reacao_historica": None if not rea else {
            "resultados_medidos": L.inteiro(rea.get("n")), "media_pct": L.arred(rea.get("m")), "media_absoluta_pct": L.arred(rea.get("ma")),
            "media_contra_ibovespa_pct": L.arred(rea.get("mr")),
            "ultimos": [{"periodo": q[0], "entrega": q[1], "pregao": q[3], "ativo_pct": L.arred(q[4]), "ibovespa_pct": L.arred(q[5])}
                        for q in (rea.get("q") or [])[:4] if len(q) >= 6],
            "nota": "reacao do ativo no pregao seguinte a entrega do resultado, em %"},
        "outros_eventos": ev_prox[:6],
    })
    if prox is None and ultimo is None and not ev_prox and not rea:
        return None, f"nenhum evento de {t} no calendario do terminal"
    if prox is None:
        out["avisos"] = ["sem data de resultado futura no calendario do terminal"]
    return out, None


# --------------------------------------------------------------------------- multiplos

def sec_multiplos(c: Ctx, t: str) -> tuple[dict | None, str | None]:
    d = L.ler("multiplos.json")
    if not isinstance(d, dict) or not d.get("a"):
        return None, "arquivo de multiplos (cache/out/multiplos.json) ausente ou vazio"
    x = d["a"].get(t)
    if x is None:
        return None, "sem multiplos para este ticker (fora do universo B3 do terminal)"
    ref = x.get("preco_de") or d.get("pregao")
    motivo = _velho("multiplos", ref, c, "o preco dos multiplos")
    if motivo:
        return None, motivo
    out = _cab("Autopilot Terminal, multiplos (preco B3 + balanco CVM ITR/DFP)", ref, c)
    f = lambda k, n=2: L.arred(x.get(k), n)
    out.update({
        "tipo": x.get("tipo"), "classe": x.get("classe"), "preco": f("preco", 4), "var_dia_pct": f("var_dia_b3"), "mcap_rs": f("mcap", 0), "ev_rs": f("ev", 0),
        "liq_media_21d_rs": f("liq_21d", 0), "liq_hoje_x_media": f("liq_x_media"),
        "balanco": {"periodo": x.get("periodo"), "data_ref": x.get("data_ref"), "entrega": x.get("entrega"), "idade_dias": L.inteiro(x.get("balanco_idade_dias"))},
        "pl": f("pl"), "pl_projetado": f("pl_proj"), "pvp": f("pvp"), "psr": f("psr"), "ev_ebitda": f("ev_ebitda"), "ev_ebit": f("ev_ebit"), "p_fcl": f("p_fcl"),
        "dy_12m_pct": f("dy_12m"), "payout_12m_pct": f("payout_12m"), "lucro_yield_pct": f("lucro_yield"), "fcl_yield_pct": f("fcl_yield"),
        "roe_pct": f("roe"), "roic_pct": f("roic"), "mg_bruta_12m_pct": f("mg_bruta_12m"), "mg_ebitda_12m_pct": f("mg_ebitda_12m"),
        "mg_ebit_12m_pct": f("mg_ebit_12m"), "mg_liq_12m_pct": f("mg_liq_12m"),
        "dl_ebitda": f("dl_ebitda"), "dl_pl": f("dl_pl"), "cobertura_juros": f("cobertura_juros"), "custo_divida_pct": f("custo_divida"),
        "cresc_receita_12m_pct": f("cresc_receita_12m"), "cresc_lucro_12m_pct": f("cresc_lucro_12m"),
        "receita_12m_rs": f("receita_12m", 0), "ebitda_12m_rs": f("ebitda_12m", 0), "lucro_12m_rs": f("lucro_12m", 0), "fcl_12m_rs": f("fcl_12m", 0),
        "ult_provento": x.get("ult_provento"), "free_float_pct": f("free_float_pct"), "pesos_nos_indices": x.get("pesos"),
        "avisos": list(x.get("avisos") or []),
    })
    return out, None


# --------------------------------------------------------------------------- valuation historico

def sec_valuation(c: Ctx, t: str) -> tuple[dict | None, str | None]:
    d = _por_ativo("valuation", t)
    if not isinstance(d, dict):
        return None, "sem valuation historico para este ticker (modulo valuation)"
    motivo = _velho("valuation", d.get("data"), c, "o preco do valuation")
    if motivo:
        return None, motivo
    est = d.get("est") or {}
    out = _cab("Autopilot Terminal, modulo valuation (B3 e CVM, balanco que existia em cada data)", d.get("data"), c)

    def mult(k: str) -> dict | None:
        e = est.get(k) or {}
        cinco, dez = e.get("5") or {}, e.get("10") or {}
        if not cinco and not dez:
            return None
        return {"hoje": L.arred((d.get("hoje") or {}).get(k)),
                "percentil_5a": L.arred(cinco.get("pct"), 0), "z_5a": L.arred(cinco.get("z")), "mediana_5a": L.arred(cinco.get("mediana")),
                "media_5a": L.arred(cinco.get("media")), "meses_5a": L.inteiro(cinco.get("n")),
                "percentil_10a": L.arred(dez.get("pct"), 0), "z_10a": L.arred(dez.get("z")), "mediana_10a": L.arred(dez.get("mediana")),
                "meses_10a": L.inteiro(dez.get("n"))}

    s = d.get("setor") or {}
    pr = s.get("premio") or {}
    out.update({
        "pl": mult("pl"), "pvp": mult("pvp"), "ev_ebitda": mult("ev_ebitda"), "dy": mult("dy"),
        "contra_o_setor": None if not s else {"grupo": s.get("rot"), "nivel": s.get("nivel"), "empresas": L.inteiro(s.get("n")),
                                              "pl_pct": L.arred((pr.get("pl") or {}).get("hoje"), 1), "pvp_pct": L.arred((pr.get("pvp") or {}).get("hoje"), 1),
                                              "ev_ebitda_pct": L.arred((pr.get("ev_ebitda") or {}).get("hoje"), 1),
                                              "nota": "premio (+) ou desconto (-) do multiplo de hoje sobre a mediana do grupo, em %"},
        "como_ler": ["percentil 73 = o multiplo de hoje esta acima de 73% dos fins de mes da janela (100 = mais caro da janela)"],
        "avisos": list(d.get("avisos") or []),
    })
    return out, None


# --------------------------------------------------------------------------- divida

def sec_divida(c: Ctx, t: str) -> tuple[dict | None, str | None]:
    d = _por_ativo("divida", _empresa_de(c, t))
    if not isinstance(d, dict) or not d.get("foto"):
        tipo = ((L.ler("multiplos.json") or {}).get("a", {}).get(t) or {}).get("tipo")
        if tipo in ("financeira", "seguradora"):
            return None, "banco ou seguradora: a divida faz parte do negocio e o modulo divida nao cobre"
        return None, "sem painel de divida para esta empresa (modulo divida)"
    f = d["foto"]
    motivo = _velho("divida", f.get("data"), c, f"o balanco {f.get('periodo')}")
    if motivo:
        return None, motivo
    mi = lambda k: None if L.num(f.get(k)) is None else round(L.num(f[k]) * 1e6, 0)      # o modulo guarda em R$ milhoes
    pares = d.get("pares") or {}
    out = _cab(f"Autopilot Terminal, modulo divida ({f.get('fonte')})", f.get("data"), c)
    out.update({
        "periodo": f.get("periodo"), "entrega": (d.get("ultimo") or {}).get("entrega"), "base": d.get("base"),
        "divida_bruta_rs": mi("bruta"), "caixa_rs": mi("caixa"), "divida_liquida_rs": mi("liq"), "curto_prazo_rs": mi("cp"), "longo_prazo_rs": mi("lp"),
        "arrendamento_rs": mi("arrend"), "ebitda_12m_rs": mi("ebitda_12m"),
        "dl_ebitda": L.arred(f.get("dl_ebitda")), "cobertura_juros": L.arred(f.get("cobertura")), "cobertura_de": f.get("cobertura_de"),
        "custo_pct": L.arred(f.get("custo")), "custo_de": f.get("custo_de"), "cdi_12m_pct": L.arred(f.get("cdi_12m")),
        "curto_prazo_pct_da_divida": L.arred(f.get("cp_pct"), 1), "caixa_sobre_curto_prazo": L.arred(f.get("caixa_cp")),
        "moeda_estrangeira_pct": L.arred(f.get("me_pct"), 1),
        "moeda_da_divida_nao_aberta": f.get("me_falta"),
        "pares": None if not pares else {"grupo": pares.get("grupo"), "empresas": L.inteiro(pares.get("n")), "dl_ebitda_mediano": L.arred(pares.get("dl_ebitda")),
                                         "custo_mediano_pct": L.arred(pares.get("custo")), "curto_prazo_mediano_pct": L.arred(pares.get("cp_pct")),
                                         "cobertura_mediana": L.arred(pares.get("cobertura"))},
        "avisos": list(d.get("avisos") or []),
    })
    return out, None


# --------------------------------------------------------------------------- opcoes

def _sorriso(spot: Any, v: dict) -> dict | None:
    """Volatilidade implicita observada em tres pontos do sorriso do vencimento: no dinheiro (a menos de 2% do preco), cerca de 10% abaixo
    (put) e cerca de 10% acima (call), cada uma a no maximo 3 pontos percentuais do alvo. Nada interpolado: sem strike perto, None."""
    s = L.num(spot)
    pts = [((L.num(x["k"]) / s - 1.0) * 100.0, L.num(x["iv"])) for x in v.get("strikes") or []
           if s and L.num(x.get("k")) and L.num(x.get("iv")) is not None]
    if len(pts) < 3:
        return None

    def perto(alvo: float, tol: float) -> float | None:
        d, iv = min(pts, key=lambda p: abs(p[0] - alvo))
        return round(iv, 2) if abs(d - alvo) <= tol else None
    atm, p10, c10 = perto(0.0, 2.0), perto(-10.0, 3.0), perto(10.0, 3.0)
    return {"vencimento": v.get("venc"), "strikes_com_volatilidade": len(pts), "atm_pct": atm, "put_10_pct": p10, "call_10_pct": c10,
            "skew_10_pp": round(p10 - c10, 2) if p10 is not None and c10 is not None else None}


def sec_opcoes(c: Ctx, t: str) -> tuple[dict | None, str | None]:
    d = L.ler(f"deriv/opcoes/{t}.json", memo=False)
    if not isinstance(d, dict):
        return None, "sem opcoes listadas para este ticker no arquivo da B3 do terminal"
    motivo = _velho("opcoes", d.get("data"), c, "o arquivo de opcoes")
    if motivo:
        return None, motivo
    r = d.get("resumo") or {}
    h = d.get("hist") or {}
    vrefs = h.get("venc_ref") or []
    ivs = [(dia, L.num(v), vrefs[i] if i < len(vrefs) else None)
           for i, (dia, v) in enumerate(zip(h.get("t") or [], h.get("iv_atm") or [])) if L.num(v) is not None]
    iv = None
    if ivs:
        dia, v, venc = ivs[-1]
        validos = [x[1] for x in ivs]
        mot_iv = _velho("opcoes", dia, c, "a ultima volatilidade implicita")
        iv = {"pct": round(v, 2), "data": dia, "idade_dias": (c.hoje - date.fromisoformat(dia)).days, "vencimento": venc,
              "percentil_historico": round(sum(1 for x in validos if x <= v) / len(validos) * 100, 0), "pontos_na_historia": len(validos),
              "media_historica_pct": round(sum(validos) / len(validos), 2), "valida": mot_iv is None, "motivo_descarte": mot_iv}
        if mot_iv:
            iv = {"pct": None, **{k: iv[k] for k in ("data", "idade_dias", "vencimento", "motivo_descarte")}}
    inc = (L.ler("deriv/opcoes_resumo.json") or {}).get("incompleto")
    inc = None if not inc or (inc.get("data") or "") <= (d.get("data") or "") else {
        "data": inc.get("data"), "motivo": inc.get("motivo"), "tentativas": inc.get("tentativas"), "ultima_tentativa": inc.get("ultima_tentativa")}
    venc_ref = r.get("venc_ref")
    v_ref = next((v for v in d.get("vencimentos") or [] if v.get("venc") == venc_ref), None) or {}
    out = _cab("B3, arquivos do Boletim Diario (negocios, cadastro e posicoes em aberto), via Autopilot Terminal, modulo opcoes", d.get("data"), c)
    ofe = r.get("ofertas") or {}
    out.update({
        "ativo_preco": L.arred(d.get("spot"), 4), "var_ativo_pct": L.arred(d.get("var_spot")),
        "iv_no_dinheiro": iv, "iv_do_dia_no_resumo_pct": L.arred(r.get("iv_atm")), "movimento_esperado_pct": L.arred(r.get("mov_esperado_pct")),
        "vencimento_de_referencia": venc_ref, "pregao_completo": d.get("data"),
        "pregao_incompleto_mais_recente": inc,
        "sorriso_do_vencimento_de_referencia": _sorriso(d.get("spot"), v_ref) if v_ref else None,
        "posicao": {"oi_call": L.inteiro(r.get("oi_call")), "oi_put": L.inteiro(r.get("oi_put")), "put_call_oi": L.arred(r.get("pc_oi"), 3),
                    "variacao_oi_call": L.inteiro(r.get("doi_call")), "variacao_oi_put": L.inteiro(r.get("doi_put")),
                    "data_da_posicao": d.get("data_posicao")},
        "negocios_dia": {"vol_call": L.inteiro(r.get("vol_call")), "vol_put": L.inteiro(r.get("vol_put")), "put_call_vol": L.arred(r.get("pc_vol"), 3)},
        "no_vencimento_de_referencia": None if not v_ref else {
            "dor_maxima": L.arred(v_ref.get("dor_maxima")), "dor_maxima_dist_pct": L.arred(v_ref.get("dor_maxima_dist_pct")),
            "parede_call": v_ref.get("parede_call"), "parede_put": v_ref.get("parede_put"), "dias_uteis": L.inteiro(v_ref.get("du"))},
        "liquidez": {"vencimentos": len(d.get("vencimentos") or []), "ofertas_nos_dois_lados": L.inteiro(ofe.get("dois_lados")),
                     "ofertas_firmes": L.inteiro(ofe.get("firmes")), "spread_max_considerado": L.num(ofe.get("spread_max"))},
        "avisos": [("sem negocio de opcao no arquivo do pregao: a volatilidade implicita do dia nao foi calculada; vale a ultima com data"
                    if iv and r.get("iv_atm") is None else None),
                   (f"o pregao de {inc['data']} veio incompleto da B3 ({inc.get('motivo')}); estes numeros sao do ultimo pregao COMPLETO, {d.get('data')}"
                    if inc else None)],
    })
    out["avisos"] = [a for a in out["avisos"] if a]
    return out, None


# --------------------------------------------------------------------------- fundos que carregam o papel

def sec_fundos(c: Ctx, t: str) -> tuple[dict | None, str | None]:
    d = _por_ativo("quemtem", t)
    if not isinstance(d, dict) or not d.get("tot"):
        return None, "sem carteira de fundos para este ticker (modulo quemtem)"
    motivo = _velho("fundos", d.get("data"), c, f"a carteira dos fundos de {d.get('ref')}")
    if motivo:
        return None, motivo
    tot, pc, mov = d.get("tot") or {}, d.get("pct") or {}, d.get("mov") or {}
    out = _cab("CVM, CDA (carteira mensal dos fundos), via Autopilot Terminal, modulo quemtem", d.get("data"), c)
    out.update({
        "mes": d.get("ref"), "fundos": L.inteiro(tot.get("n")), "quantidade": L.inteiro(tot.get("q")), "valor_rs": L.arred(tot.get("v"), 0),
        "pct_das_acoes_da_classe": L.arred(pc.get("cl")), "pct_do_free_float": L.arred(pc.get("ff")),
        "movimento_no_mes": None if not mov else {"mes": mov.get("de"), "aumentaram_fundos": _v(mov.get("au"), 0), "aumentaram_quantidade": _v(mov.get("au"), 1),
                                                   "entraram_fundos": _v(mov.get("en"), 0), "reduziram_fundos": _v(mov.get("re"), 0),
                                                   "reduziram_quantidade": _v(mov.get("re"), 1), "sairam_fundos": _v(mov.get("sa"), 0)},
        "como_ler": ["a carteira dos fundos sai com 2 a 3 meses de atraso: e retrato de posicao, nao de fluxo de hoje"],
        "avisos": list(d.get("avisos") or []),
    })
    return out, None


# --------------------------------------------------------------------------- pares proximos

def sec_pares(c: Ctx, t: str) -> tuple[dict | None, str | None]:
    d = L.ler("pagina/proximos.json")
    if not isinstance(d, dict):
        return None, "arquivo de pares proximos ausente"
    motivo = _velho("pares", d.get("gerado"), c, "o arquivo de pares")
    if motivo:
        return None, motivo
    p = (d.get("p") or {}).get(t)
    v = (d.get("v") or {}).get(t)
    if not p and not v:
        return None, "sem pares proximos para este ticker"

    def acum(xs: Any) -> float | None:
        xs = [L.num(x) for x in xs or []]
        if not xs or any(x is None for x in xs):
            return None
        f = 1.0
        for x in xs:
            f *= 1 + x / 100.0
        return round((f - 1) * 100.0, 2)

    pares = [{"ticker": q[0], "correlacao": L.arred(q[1]), "mesmo_subsetor": bool(q[2]) if len(q) > 2 else None, "retorno_12d_pct": acum((d.get("v") or {}).get(q[0]))}
             for q in p or [] if len(q) >= 2]
    meu = acum(v)
    rets = [x["retorno_12d_pct"] for x in pares if x["retorno_12d_pct"] is not None]
    cal = (d.get("cal") or {}).get((c.universo().get(t) or {}).get("c") or "acao_br", "br")
    datas = (d.get("dias") or {}).get(cal) or []
    out = _cab("Autopilot Terminal, pares proximos (correlacao de 126 pregoes, historico diario)", d.get("gerado"), c)
    out.update({
        "pares": pares, "janela_correlacao_pregoes": L.inteiro(d.get("janela_pregoes")), "retorno_12d_pct": meu,
        "retorno_12d_medio_dos_pares_pct": round(sum(rets) / len(rets), 2) if rets else None,
        "retorno_12d_vs_pares_pp": round(meu - sum(rets) / len(rets), 2) if meu is not None and rets else None,
        "janela_retorno": [datas[0], datas[-1]] if datas else None,
    })
    return out, None


SECOES: dict[str, Callable[[Ctx, str], tuple[dict | None, str | None]]] = {
    "tir": sec_tir, "consenso": sec_consenso, "insiders": sec_insiders, "aluguel": sec_aluguel, "noticias": sec_noticias,
    "proximo_resultado": sec_proximo_resultado, "multiplos": sec_multiplos, "valuation": sec_valuation, "divida": sec_divida,
    "opcoes": sec_opcoes, "fundos": sec_fundos, "pares": sec_pares,
}
