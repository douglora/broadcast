"""
LIVRO DE TESES: a peca central do "gestor". Uma tese diz o que o gestor acha (ativo, direcao, horizonte, cenarios, conviccao); o livro devolve
as EXPRESSOES possiveis (papel, call, trava, put vendida, trava de credito) com a cadeia de hoje a precos executaveis e diz qual e a melhor
expressao DESTA tese pela regra abaixo.

TESE (dict)
  id, ativo, direcao ("alta"|"baixa"), horizonte_pregoes, evento {"data","descricao"} ou None,
  cenarios [{"nome","probabilidade","retorno_do_ativo_pct"}] (2 ou 3; sem cenarios usa a distribuicao historica do ativo no prazo),
  conviccao 1..3, origem ("mesa"|"douglas"|"robo"), texto, probabilidade_pendente (opcional: True = o numero e do Douglas, nada abre sozinho)

EXPRESSOES (tese de alta; a de baixa e o espelho)
  alta : papel; call no dinheiro; call fora do dinheiro (delta ~0,25); trava de alta (compra no dinheiro, vende a de delta ~0,25);
         put vendida coberta por caixa (delta ~0,25); trava de alta de credito com puts (vende delta ~0,25, compra a ~5% abaixo)
  baixa: papel vendido (a descoberto; a perda maxima e uma alta de 100%); put no dinheiro; put fora do dinheiro; trava de baixa com puts;
         trava de baixa de credito com calls (vende delta ~0,25, compra a ~5% acima)

CONTA. Entrada: compra na oferta de venda, venda na de compra, emolumento 0,05%. No horizonte da tese cada opcao e reavaliada por Black-Scholes
com a volatilidade implicita de hoje, MENOS o esmagamento historico se a tese tem evento (mediana medida nas eleicoes e nos resultados), e sai
pela metade do spread de entrada. Papel: variacao do preco. Tudo em R$ por LOTE de 100.

REGRA DE ESCOLHA (explicita e unica): entre as expressoes que CABEM no teto de perda maxima de R$ 500 por estrutura (um lote de 100) e tem valor
esperado positivo, escolhe a de MAIOR valor esperado por R$ de perda maxima. Papel puro conta a perda maxima como o preco inteiro (acao a zero)
e por isso quase nunca cabe no teto: ele aparece na tabela, com o pior cenario, mesmo assim. Se nenhuma servir, a tese fica sem expressao escolhida.
`probabilidade_que_o_preco_exige_pct`: probabilidade do cenario DE ALTA (o melhor para a direcao) que zera o valor esperado, com os outros cenarios
na proporcao que a tese deu. Compare com a probabilidade que a tese assume.
"""
import json
import math
import os

import numpy as np
import pandas as pd

from quant.comum import DIR_SAIDA
from quant.opcoes import bs, dados
from quant.opcoes import custos as C

FEE = C.FEE_PREMIO
TETO_PERDA = 500.0
LOTE = 100
ARQ_TESES_MESA = os.path.join(DIR_SAIDA, "mesa", "teses.json")
ARQ_VISAO_MESA = os.path.join(DIR_SAIDA, "mesa", "visao_mesa.json")
DELTA_FORA = 0.25
LARGURA_CREDITO = 0.05


# --------------------------------------------------------------------------------------------------------- leitura de teses
def ler_teses_mesa(caminho=ARQ_TESES_MESA):
    """Teses da mesa (lista) em quant/saida/mesa/teses.json. Arquivo ausente ou invalido: lista vazia (sem erro)."""
    try:
        with open(caminho, encoding="utf-8") as f:
            x = json.load(f)
        return [t for t in (x if isinstance(x, list) else x.get("teses", [])) if isinstance(t, dict) and t.get("ativo") and t.get("direcao") in ("alta", "baixa")]
    except (FileNotFoundError, ValueError, OSError):
        return []


def teses_da_visao_mesa(dia, caminho=ARQ_VISAO_MESA):
    """Teses automaticas dos eventos binarios da visao da mesa (campo acoes[].evento_binario). Arquivo ausente: lista vazia."""
    try:
        with open(caminho, encoding="utf-8") as f:
            v = json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return []
    out = []
    for a in (v.get("acoes") or []):
        ev = a.get("evento_binario")
        tk = a.get("ticker") or a.get("ativo")
        if not ev or not tk:
            continue
        data = ev.get("data") if isinstance(ev, dict) else None
        if data and pd.Timestamp(data) <= pd.Timestamp(dia):
            continue
        direc = (a.get("direcao") or (ev.get("direcao") if isinstance(ev, dict) else None) or "alta")
        out.append({"id": f"visao-{tk}-{data or 'sem-data'}", "ativo": tk, "direcao": direc if direc in ("alta", "baixa") else "alta", "horizonte_pregoes": 10,
                    "evento": {"data": data, "descricao": ev.get("descricao") if isinstance(ev, dict) else str(ev)}, "cenarios": None, "conviccao": 1, "origem": "robo",
                    "texto": f"Evento binário na visão da mesa para {tk}: {ev.get('descricao') if isinstance(ev, dict) else ev}. Sem cenários da mesa: usa a distribuição histórica do ativo."})
    return out


# --------------------------------------------------------------------------------------------------------- distribuicao
def retornos_historicos(tr, h, anos=10):
    x = tr[tr.index >= tr.index[-1] - pd.DateOffset(years=anos)]
    if len(x) < h + 250:
        return None
    return (x.shift(-h) / x - 1.0).dropna().values


def cenarios_da_tese(tese, tr):
    """[(nome, probabilidade, retorno)] da tese ou, sem cenarios, quantis da distribuicao historica no prazo (5 faixas de peso igual)."""
    if tese.get("cenarios"):
        c = [(x["nome"], x.get("probabilidade"), float(x["retorno_do_ativo_pct"]) / 100.0) for x in tese["cenarios"]]
        if all(p is not None for _, p, _ in c):
            tot = sum(p for _, p, _ in c)
            c = [(n, p / tot, r) for n, p, r in c]
        return c, False
    if tr is None:
        return [], True
    rh = retornos_historicos(tr, int(tese["horizonte_pregoes"]))
    if rh is None:
        return [], True
    qs = np.quantile(rh, [0.1, 0.3, 0.5, 0.7, 0.9])
    nomes = ["pior decil", "queda moderada", "mediana", "alta moderada", "melhor decil"]
    return [(n, 0.2, float(q)) for n, q in zip(nomes, qs)], True


# --------------------------------------------------------------------------------------------------------- pernas
def _liquidas(o, ativo, venc):
    return o[(o["ativo"] == ativo) & (o["vencimento"] == venc) & (o["negocios"] >= C.NEG_MIN) & o["boa"] & (o["spread"] <= C.SPREAD_MAX)]


def _por_delta(el, tipo, alvo, tol):
    x = el[el["tipo"] == tipo].assign(_d=lambda d: (d["delta"].abs() - alvo).abs())
    x = x[x["_d"] <= tol].sort_values(["_d", "negocios"], ascending=[True, False])
    return x.iloc[0] if len(x) else None


def _por_strike(el, tipo, k_alvo, tol_abs):
    x = el[el["tipo"] == tipo].assign(_d=lambda d: (d["exercicio"] - k_alvo).abs())
    x = x[x["_d"] <= tol_abs].sort_values(["_d", "negocios"], ascending=[True, False])
    return x.iloc[0] if len(x) else None


def escolher_vencimento(o, ativo, dia, du_necessario, vencs_mensais):
    """Primeiro vencimento mensal com pregoes ate o vencimento >= du_necessario e com pernas liquidas."""
    from quant.opcoes.assimetrias import arbitragens_du
    for v in vencs_mensais:
        du = arbitragens_du(dia, v)
        if du >= du_necessario and len(_liquidas(o, ativo, v)) >= 4:
            return v, du
    return None, None


# --------------------------------------------------------------------------------------------------------- valor das pernas no horizonte
def _valor_perna(S, r, du_rem, perna, iv_mult):
    """Valor de saida (R$ por acao) de uma perna no horizonte, por Black-Scholes e meio spread de entrada."""
    t = max(du_rem, 0) / 252.0
    put = perna["tipo"] == "P"
    iv = float(perna["iv"]) * iv_mult
    v = bs.preco(S, float(perna["exercicio"]), t, r, iv, put) if t > 0 else (max(float(perna["exercicio"]) - S, 0.0) if put else max(S - float(perna["exercicio"]), 0.0))
    hs = max(float(perna["spread"]), 0.0) / 2.0 if perna.get("spread") == perna.get("spread") else 0.0
    return v, hs


def _resultado_cenario(legs, S0, S_h, r, du_rem, iv_mult):
    """Resultado em R$ por acao no horizonte para uma lista de pernas [(perna, lado, preco_entrada)]. Positivo = ganho."""
    total = 0.0
    for p, lado, pe in legs:
        v, hs = _valor_perna(S_h, r, du_rem, p, iv_mult)
        if lado == "compra":
            total += v * (1 - hs) * (1 - FEE) - pe
        else:
            total += pe - v * (1 + hs) * (1 + FEE)
    return total


def montar_expressoes(tese, S0, o, ativo, venc, du, r_aa, caixa_cdi_aa=None):
    """Lista de estruturas montaveis na cadeia (um vencimento). Cada uma: nome, titulo, pernas [(linha, lado, preco_entrada)], custo, perda_maxima, caixa."""
    el = _liquidas(o, ativo, venc)
    out = []
    direc = tese["direcao"]

    def compra(p):
        return float(p["oferta_venda"]) * (1 + FEE)

    def venda(p):
        return float(p["oferta_compra"]) * (1 - FEE)

    def estr(nome, titulo, legs, custo, perda, caixa=None, ganho_max=None):
        out.append({"nome": nome, "titulo": titulo, "legs": legs, "custo": custo, "perda_maxima": perda, "caixa": caixa if caixa is not None else max(custo, 0.0), "ganho_maximo": ganho_max})

    if direc == "alta":
        estr("papel", f"Comprar {ativo} (papel)", [], S0, S0)
        c_at, c_fora = _por_delta(el, "C", 0.50, 0.12), _por_delta(el, "C", DELTA_FORA, 0.07)
        if c_at is not None:
            estr("call_no_dinheiro", f"Call no dinheiro {c_at['codigo']} (exercício {c_at['exercicio']:.2f})", [(c_at, "compra", compra(c_at))], compra(c_at), compra(c_at))
        if c_fora is not None:
            estr("call_fora_do_dinheiro", f"Call fora do dinheiro {c_fora['codigo']} (exercício {c_fora['exercicio']:.2f})", [(c_fora, "compra", compra(c_fora))], compra(c_fora), compra(c_fora))
        if c_at is not None and c_fora is not None and c_fora["exercicio"] > c_at["exercicio"]:
            deb = compra(c_at) - venda(c_fora)
            larg = float(c_fora["exercicio"] - c_at["exercicio"])
            if 0 < deb < larg:
                estr("trava_de_alta", f"Trava de alta {c_at['codigo']} / {c_fora['codigo']}", [(c_at, "compra", compra(c_at)), (c_fora, "venda", venda(c_fora))], deb, deb, ganho_max=larg - deb)
        p_v = _por_delta(el, "P", DELTA_FORA, 0.07)
        if p_v is not None:
            cred = venda(p_v)
            K = float(p_v["exercicio"])
            estr("put_vendida_coberta", f"Put vendida coberta por caixa {p_v['codigo']} (exercício {K:.2f})", [(p_v, "venda", cred)], -cred, K - cred, caixa=K, ganho_max=cred)
            p_c = _por_strike(el, "P", K - LARGURA_CREDITO * S0, 0.03 * S0)
            if p_c is not None and p_c["exercicio"] < K:
                credito = cred - compra(p_c)
                larg = K - float(p_c["exercicio"])
                if 0 < credito < larg:
                    estr("trava_de_alta_com_puts", f"Trava de alta de crédito com puts {p_v['codigo']} / {p_c['codigo']}", [(p_v, "venda", cred), (p_c, "compra", compra(p_c))], -credito, larg - credito,
                         caixa=larg - credito, ganho_max=credito)
    else:
        estr("papel_vendido", f"Vender {ativo} a descoberto (papel)", [], S0, S0)
        p_at, p_fora = _por_delta(el, "P", 0.50, 0.12), _por_delta(el, "P", DELTA_FORA, 0.07)
        if p_at is not None:
            estr("put_no_dinheiro", f"Put no dinheiro {p_at['codigo']} (exercício {p_at['exercicio']:.2f})", [(p_at, "compra", compra(p_at))], compra(p_at), compra(p_at))
        if p_fora is not None:
            estr("put_fora_do_dinheiro", f"Put fora do dinheiro {p_fora['codigo']} (exercício {p_fora['exercicio']:.2f})", [(p_fora, "compra", compra(p_fora))], compra(p_fora), compra(p_fora))
        if p_at is not None and p_fora is not None and p_fora["exercicio"] < p_at["exercicio"]:
            deb = compra(p_at) - venda(p_fora)
            larg = float(p_at["exercicio"] - p_fora["exercicio"])
            if 0 < deb < larg:
                estr("trava_de_baixa", f"Trava de baixa com puts {p_at['codigo']} / {p_fora['codigo']}", [(p_at, "compra", compra(p_at)), (p_fora, "venda", venda(p_fora))], deb, deb, ganho_max=larg - deb)
        c_v = _por_delta(el, "C", DELTA_FORA, 0.07)
        if c_v is not None:
            K = float(c_v["exercicio"])
            c_c = _por_strike(el, "C", K + LARGURA_CREDITO * S0, 0.03 * S0)
            if c_c is not None and c_c["exercicio"] > K:
                credito = venda(c_v) - compra(c_c)
                larg = float(c_c["exercicio"]) - K
                if 0 < credito < larg:
                    estr("trava_de_baixa_com_calls", f"Trava de baixa de crédito com calls {c_v['codigo']} / {c_c['codigo']}", [(c_v, "venda", venda(c_v)), (c_c, "compra", compra(c_c))], -credito,
                         larg - credito, caixa=larg - credito, ganho_max=credito)
    return out


# --------------------------------------------------------------------------------------------------------- avaliacao
def _empate_horizonte(legs, S0, r, du_rem, mult, papel=False, sinal=1):
    """Movimento do ativo (em %) no horizonte em que o resultado da estrutura cruza zero, o mais perto de zero. None se nao cruza em +-40%."""
    xs = np.linspace(-0.40, 0.40, 801)
    if papel:
        return 0.0
    v = np.array([_resultado_cenario(legs, S0, S0 * (1 + x), r, du_rem, mult) for x in xs])
    cruz = [(abs((xs[i] + xs[i + 1]) / 2), (xs[i] + xs[i + 1]) / 2) for i in range(len(xs) - 1) if v[i] == 0 or v[i] * v[i + 1] < 0]
    return None if not cruz else float(min(cruz)[1] * 100)


def _prob_exercicio_implicita(perna, S0, r, du):
    """N(d2): chance, pelo preco da propria opcao, de terminar no dinheiro no vencimento (call: acima do exercicio; put: abaixo)."""
    t = du / 252.0
    sig = float(perna["iv"])
    d2 = (math.log(S0 / float(perna["exercicio"])) + (r - 0.5 * sig * sig) * t) / (sig * math.sqrt(t))
    from scipy.special import ndtr
    return float(ndtr(d2) if perna["tipo"] == "C" else ndtr(-d2)) * 100


def _r1(x):
    return None if x is None else round(float(x), 1)


def _pernas_estado(legs, ativo):
    from quant.opcoes.carteira_simulada import _perna_estado
    return [_perna_estado(p, lado, LOTE, ativo) for p, lado, _ in legs]


def avaliar_tese(tese, M, esmagamento_pct=None, vencs_mensais=None, tr=None):
    """Devolve o bloco da tese para o JSON + a lista de expressoes. `esmagamento_pct`: queda mediana da volatilidade apos o evento (negativo, em %)."""
    dia = pd.Timestamp(M["dia"])
    ativo = tese["ativo"]
    o = M["o"]
    S0 = float(M["sp"][(M["sp"]["ativo"] == ativo) & (M["sp"]["dia"] == dia) & (M["sp"]["fatcot"] == 1)]["fech"].iloc[0]) if len(M["sp"][(M["sp"]["ativo"] == ativo) & (M["sp"]["dia"] == dia)]) else None
    base = {k: tese.get(k) for k in ("id", "ativo", "direcao", "texto", "origem", "evento", "conviccao", "horizonte_pregoes")}
    base["preco_do_ativo"] = S0
    if S0 is None:
        return {**base, "cenarios": tese.get("cenarios"), "expressoes": [], "escolhida": None, "porque": "Sem preço do ativo na cadeia de hoje."}, []
    if tr is None:
        tr = M.get("tr", {}).get(ativo)
    vencs = vencs_mensais if vencs_mensais is not None else [v for v in dados.vencimentos_padrao() if v > dia]
    h = int(tese["horizonte_pregoes"])
    venc, du = escolher_vencimento(o, ativo, dia, h + 8, vencs)
    cen, historico = cenarios_da_tese(tese, tr)
    if venc is None or not cen:
        return {**base, "cenarios": tese.get("cenarios"), "expressoes": [], "escolhida": None,
                "porque": "Sem cadeia líquida para o prazo da tese (30+ negócios, ofertas dos dois lados e spread de até 30%): nenhuma expressão foi montada."}, []
    r_aa = float(M["r_aa"])
    r = math.log1p(r_aa)
    du_rem = du - h
    tem_evento = bool(tese.get("evento"))
    mult_com = 1.0 + (esmagamento_pct or 0.0) / 100.0 if tem_evento else 1.0
    exprs = montar_expressoes(tese, S0, o, ativo, venc, du, r_aa)
    saida = []
    sinal = 1 if tese["direcao"] == "alta" else -1
    probs = [p for _, p, _ in cen]
    melhor_idx = int(np.argmax([sinal * rr for _, _, rr in cen]))
    for e in exprs:
        ganhos_com, ganhos_sem = [], []
        for nome, p, ret in cen:
            S_h = S0 * (1.0 + ret)
            if e["nome"] in ("papel", "papel_vendido"):
                g = sinal * (S_h - S0)
                ganhos_com.append(g)
                ganhos_sem.append(g)
            else:
                ganhos_com.append(_resultado_cenario(e["legs"], S0, S_h, r, du_rem, mult_com))
                ganhos_sem.append(_resultado_cenario(e["legs"], S0, S_h, r, du_rem, 1.0))
        ev = float(sum(p * g for p, g in zip(probs, ganhos_com))) if all(p is not None for p in probs) else None
        ev_sem = float(sum(p * g for p, g in zip(probs, ganhos_sem))) if ev is not None else None
        perda = float(e["perda_maxima"])
        pstar = None
        if len(cen) >= 2 and ev is not None and not historico:
            g_best = ganhos_com[melhor_idx]
            outros = [(p, g) for i, (p, g) in enumerate(zip(probs, ganhos_com)) if i != melhor_idx]
            tot = sum(p for p, _ in outros)
            g_rest = sum(p * g for p, g in outros) / tot if tot > 0 else 0.0
            if g_best > g_rest:
                x = -g_rest / (g_best - g_rest)
                pstar = float(min(max(x, 0.0), 1.0)) * 100 if g_best > 0 else None
                if g_best <= 0:
                    pstar = None
        cabe = perda * LOTE <= TETO_PERDA + 1e-9
        item = {"nome": e["nome"], "titulo": e["titulo"], "pernas": [{"codigo": p["codigo"], "tipo": "put" if p["tipo"] == "P" else "call", "lado": lado, "exercicio": round(float(p["exercicio"]), 2),
                                                                     "vencimento": str(pd.Timestamp(p["vencimento"]).date()), "premio": round(float(pe), 3), "delta": round(float(p["delta"]), 3),
                                                                     "vol_implicita": round(float(p["iv"]), 4), "negocios": int(p["negocios"])} for p, lado, pe in e["legs"]],
                "custo": round(e["custo"] * LOTE, 2), "caixa_empenhado": round(e["caixa"] * LOTE, 2), "perda_maxima": round(perda * LOTE, 2),
                "ganho_por_cenario": [{"cenario": n, "resultado_rs": round(g * LOTE, 2)} for (n, _, _), g in zip(cen, ganhos_com)],
                "valor_esperado_rs": None if ev is None else round(ev * LOTE, 2), "pior_caso_rs": round(min(ganhos_com) * LOTE, 2),
                "retorno_sobre_risco": None if (ev is None or perda <= 0) else round(ev / perda, 4),
                "probabilidade_que_o_preco_exige_pct": None if pstar is None else round(pstar, 1),
                "efeito_do_esmagamento_rs": None if ev is None else round((ev - ev_sem) * LOTE, 2), "cabe_no_teto": bool(cabe), "unidade": "R$ por lote de 100 ações",
                "movimento_de_empate_pct": _r1(_empate_horizonte(e["legs"], S0, r, du_rem, mult_com, papel=not e["legs"])),
                "prob_implicita_de_exercicio_pct": _r1(_prob_exercicio_implicita(e["legs"][0][0], S0, r, du)) if e["legs"] and len(e["legs"]) == 1 else None,
                "nota": ""}
        saida.append((item, e, ev))
    # escolha
    cand = [(it["retorno_sobre_risco"], it) for it, e, ev in saida if it["cabe_no_teto"] and ev is not None and ev > 0 and it["retorno_sobre_risco"] is not None]
    escolhida = max(cand, key=lambda x: x[0])[1]["nome"] if cand else None
    itens = [it for it, _, _ in saida]
    _notas(itens, tese, cen, historico, mult_com, escolhida)
    porque = _porque(itens, tese, escolhida, o, ativo, venc, cen, historico)
    bloco = {**base, "cenarios": tese.get("cenarios") or [{"nome": n, "probabilidade": p, "retorno_do_ativo_pct": round(r * 100, 2)} for n, p, r in cen], "cenarios_origem": "historico" if historico else "tese",
             "vencimento_usado": str(pd.Timestamp(venc).date()), "pregoes_ate_o_vencimento": du, "esmagamento_considerado_pct": esmagamento_pct if tem_evento else None,
             "expressoes": itens, "escolhida": escolhida, "porque": porque, "regra_de_escolha": "maior valor esperado por R$ de perda máxima, entre as que cabem no teto de R$ 500 por estrutura (lote de 100) e têm valor esperado positivo"}
    abrir = None
    if escolhida and tese.get("origem") in ("mesa", "robo") and not tese.get("probabilidade_pendente") and not historico:
        e_esc = next(e for it, e, ev in saida if it["nome"] == escolhida)
        if e_esc["legs"]:
            abrir = {"id": tese["id"], "ativo": ativo, "origem": tese["origem"],
                     "expressao": {"nome": escolhida, "titulo": next(i["titulo"] for i in itens if i["nome"] == escolhida), "pernas_estado": _pernas_estado(e_esc["legs"], ativo),
                                   "custo_por_acao": e_esc["custo"], "perda_maxima_por_acao": e_esc["perda_maxima"], "vencimento": str(pd.Timestamp(venc).date())}}
    return bloco, ([abrir] if abrir else [])


def _notas(itens, tese, cen, historico, mult, escolhida):
    for it in itens:
        n = []
        if not it["cabe_no_teto"]:
            n.append(f"perda máxima de R$ {it['perda_maxima']:,.0f} por lote passa do teto de R$ 500".replace(",", "."))
        if it["probabilidade_que_o_preco_exige_pct"] is not None:
            n.append(f"o preço exige {it['probabilidade_que_o_preco_exige_pct']:.0f}% de chance do cenário de alta para empatar")
        if it["efeito_do_esmagamento_rs"]:
            n.append(f"o esmagamento da volatilidade tira R$ {abs(it['efeito_do_esmagamento_rs']):,.0f} do valor esperado".replace(",", ".") if it["efeito_do_esmagamento_rs"] < 0 else f"o esmagamento da volatilidade ajuda em R$ {it['efeito_do_esmagamento_rs']:,.0f}".replace(",", "."))
        if it["nome"] == escolhida:
            n.append("é a expressão escolhida pela regra")
        it["nota"] = "; ".join(n).capitalize() + ("." if n else "")


def _porque(itens, tese, escolhida, o, ativo, venc, cen, historico):
    by = {i["nome"]: i for i in itens}
    iv = o[(o["ativo"] == ativo) & (o["vencimento"] == venc)]["iv"].median()
    if escolhida is None:
        return "Nenhuma expressão cabe no teto de R$ 500 por estrutura com valor esperado positivo nos cenários desta tese: a tabela mostra o preço de cada uma, sem escolha."
    esc = by[escolhida]
    partes = [f"{esc['titulo']} tem o maior valor esperado por R$ de perda máxima ({esc['retorno_sobre_risco']:.2f}) entre as que cabem no teto"]
    seca = by.get("call_no_dinheiro") or by.get("put_no_dinheiro")
    trava = by.get("trava_de_alta") or by.get("trava_de_baixa")
    if seca and trava and escolhida in ("trava_de_alta", "trava_de_baixa") and seca["custo"] > 0:
        menos = (1 - trava["custo"] / seca["custo"]) * 100
        bom = max(range(len(cen)), key=lambda i: cen[i][2] * (1 if tese["direcao"] == "alta" else -1))
        gs, gt = seca["ganho_por_cenario"][bom]["resultado_rs"], trava["ganho_por_cenario"][bom]["resultado_rs"]
        if gs > 0:
            partes.append(f"a trava custa {menos:.0f}% menos que a opção seca e mantém {gt / gs * 100:.0f}% do ganho no cenário bom, porque a volatilidade implícita ({iv * 100:.0f}% ao ano) deixa a opção seca cara")
    if tese.get("evento"):
        partes.append("o esmagamento da volatilidade depois do evento já está na conta")
    if historico:
        partes.append("os cenários são a distribuição histórica do ativo no prazo, não uma opinião da tese")
    return "; ".join(partes) + "."


# --------------------------------------------------------------------------------------------------------- caso do Douglas
def caso_bbas3(M, esmagamento_pct, movimento_pct, vencs_mensais=None, tr=None):
    """Caso trabalhado: BBAS3, alta, 2o turno em 25/10/2026. A probabilidade do cenario politico NAO e preenchida: o numero e do Douglas.
    Devolve (bloco principal calculado a 50%, tabela de sensibilidade 40/50/60 com tamanhos de movimento)."""
    base = {"id": "douglas-bbas3-2o-turno-2026", "ativo": "BBAS3", "direcao": "alta", "horizonte_pregoes": 14,
            "evento": {"data": "2026-10-25", "descricao": "2º turno da eleição presidencial de 2026 (domingo; reação na segunda, 26/10)"}, "conviccao": 2, "origem": "douglas",
            "texto": "Se o candidato da direita ficar na frente, as estatais (Banco do Brasil) tendem a subir muito; se não, podem cair muito. Comprar CALLS limita a perda ao prêmio. "
                     "A probabilidade do cenário político é do Douglas: a tabela mostra 40%, 50% e 60%.", "probabilidade_pendente": True}
    saidas = {}
    for p in (0.4, 0.5, 0.6):
        t = dict(base)
        t["cenarios"] = [{"nome": "direita na frente", "probabilidade": p, "retorno_do_ativo_pct": movimento_pct}, {"nome": "outro resultado", "probabilidade": round(1 - p, 4), "retorno_do_ativo_pct": -movimento_pct}]
        saidas[p] = avaliar_tese(t, M, esmagamento_pct, vencs_mensais, tr)[0]
    return saidas
