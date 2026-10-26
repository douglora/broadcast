"""Alinhamento da proposta com o cliente: a regua que diz, ponto a ponto, se a estrategia esta alinhada.

Cada checagem devolve um status (ok, atencao, fora ou info), o valor, o limite, a leitura em uma frase e, quando
nao esta ok, o que mexer. O veredito final conta as checagens. Os limites sao da mesa e estao a vista; o que o
cliente declarou na ficha (queda maxima, reserva, bandas) sempre vale mais que o padrao do perfil.
"""

from __future__ import annotations

import numpy as np

from . import cliente as CL
from . import config as C
from .contexto import Contexto
from .formato import brl, num, pct as _pct_f, pp as _pp, prob as _prob

SIMBOLO = {"ok": "✅", "atencao": "🟡", "fora": "🔴", "info": "ℹ️"}
ROTULO = {"ok": "alinhado", "atencao": "atenção", "fora": "fora", "info": "informativo"}


def _pct(x: float, casas: int = 1) -> str:
    return _pct_f(x, casas)


def _c(id_: str, titulo: str, status: str, valor: str, limite: str, leitura: str, acao: str = "") -> dict:
    return {"id": id_, "titulo": titulo, "status": status, "valor": valor, "limite": limite, "leitura": leitura, "acao": acao}


def _escala(v: float, ok: float, atencao: float, menor_e_melhor: bool = True) -> str:
    if menor_e_melhor:
        return "ok" if v <= ok else "atencao" if v <= atencao else "fora"
    return "ok" if v >= ok else "atencao" if v >= atencao else "fora"


def checar(ctx: Contexto, a: dict) -> list[dict]:
    """Roda todas as checagens para a avaliacao `a` (saida de contexto.avaliar)."""
    f = ctx.ficha
    w = a["w"]
    sim = a["sim"]
    ck: list[dict] = []
    nome_cls = lambda cid: C.POR_ID[cid].curto

    # 1. retorno contra o que o cliente precisa -------------------------------------------------------------
    if sim["p_meta"] is not None:
        st = _escala(sim["p_meta"], 0.75, 0.50, menor_e_melhor=False)
        nec = a["retorno_necessario"]
        necessario = f"o plano exige {_pct(nec)} ao ano (nominal) e a carteira rende {_pct(a['ret'])}" if nec is not None else "a meta nao fecha nem a 100% ao ano"
        ck.append(_c("retorno", "Chance de atingir a meta", st, _prob(sim["p_meta"], 0), "75% ou mais",
                     f"Em {num(sim['n'], 0)} trajetórias, {_prob(sim['p_meta'], 0)} chegam à meta de {brl(f['objetivo']['meta_patrimonio'])} (em reais de hoje); {necessario}.",
                     "" if st == "ok" else "Aumente o aporte, alongue o prazo, reduza a meta ou aceite mais risco (veja a fronteira)."))
    else:
        ck.append(_c("retorno", "Retorno esperado", "info", f"{_pct(a['ret_real'])} real", "sem meta na ficha",
                     f"Sem meta de patrimônio na ficha, avaliei só o retorno: {_pct(a['ret'])} nominal e {_pct(a['ret_real'])} acima da inflação, líquidos de imposto.",
                     "Defina a meta de patrimônio para medir a chance de chegar lá."))
    st = "ok" if a["excesso"] >= 0 else "atencao"
    ck.append(_c("excesso", "Retorno contra ficar no CDI", st, _pp(a["excesso"], 2),
                 "acima de zero",
                 f"A carteira rende {_pct(a['ret'])} líquido contra {_pct(ctx.bench)} de 100% do CDI tributado: {'paga' if a['excesso']>=0 else 'NÃO paga'} o risco extra.",
                 "" if st == "ok" else "Revise as classes de risco, ou aceite a diferença como custo de uma proteção (dólar, liquidez, sucessão)."))

    # 2. queda maxima ---------------------------------------------------------------------------------------
    pior = a["estresse"]["pior"]
    queda = max(abs(pior["total"]) if pior else 0.0, abs(sim["mdd_p95"]))
    lim = ctx.queda_limite
    st = _escala(queda, lim, lim * 1.25)
    ck.append(_c("queda", "Queda máxima (pico ao vale)", st, f"-{_pct(queda)}", f"até {_pct(lim)}",
                 f"No pior cenário testado ({pior['nome'] if pior else 'n/d'}) a carteira cai {_pct(abs(pior['total']) if pior else 0)}; "
                 f"o carrego repõe em ~{int(pior['meses_para_recuperar']) if pior else 0} meses. Nas simulações, em 1 de cada 20 trajetórias a maior queda passa de {_pct(abs(sim['mdd_p95']))}.",
                 "" if st == "ok" else "Reduza renda variável/cripto/crédito longo ou aumente o limite com o cliente, por escrito."))

    # 3. volatilidade ------------------------------------------------------------------------------------------
    vmax = ctx.restr.vol_max or C.PERFIS[ctx.perfil]["vol_alvo"]
    st = _escala(a["vol"], vmax, vmax * 1.2)
    ck.append(_c("vol", "Volatilidade", st, _pct(a["vol"]), f"até {_pct(vmax)}",
                 f"Oscilação típica de {_pct(a['vol'])} ao ano contra um orçamento de {_pct(vmax)} do perfil {C.ROTULOS_PERFIL[ctx.perfil].lower()}."))

    # 4. bandas -----------------------------------------------------------------------------------------------------
    fora = []
    for i, cid in enumerate(C.IDS):
        lo, hi = ctx.restr.lo[i], ctx.restr.hi[i]
        if w[i] < lo - 0.0026 or w[i] > hi + 0.0026:
            fora.append(f"{nome_cls(cid)} {_pct(w[i])} (banda {_pct(lo,0)} a {_pct(hi,0)})")
    rv_max = ctx.restr.rv_max
    if a["rv"] > rv_max + 0.0026:
        fora.append(f"renda variável {_pct(a['rv'])} (teto {_pct(rv_max,0)})")
    ck.append(_c("bandas", "Bandas do perfil e do cliente", "ok" if not fora else "fora", f"{len(fora)} fora" if fora else "dentro", "todas dentro",
                 "Todas as classes dentro das bandas." if not fora else "Fora da banda: " + "; ".join(fora) + ".",
                 "" if not fora else "Reponha dentro da banda ou documente a exceção (suitability)."))

    # 5. liquidez -------------------------------------------------------------------------------------------------------
    pl = ctx.plano.pl
    reserva = CL.reserva_necessaria(f)
    saidas_12m = sum(-float(e["valor"]) for e in (f["fluxo"].get("eventos") or []) if e.get("mes", 99) <= 12 and e.get("valor", 0) < 0)
    if (f["fluxo"].get("aporte_mensal") or 0) < 0:
        saidas_12m += -float(f["fluxo"]["aporte_mensal"]) * 12
    necessidade = (reserva or 0.0) + saidas_12m - (f["liquidez"].get("obrigacoes_12m") or 0.0) * (1 if reserva else 0)
    caixa = float(w[C.IDS.index("caixa")]) * pl
    macio = caixa + float(w[C.IDS.index("pos_trib")]) * pl
    if reserva is None and saidas_12m == 0:
        ck.append(_c("liquidez", "Liquidez e reserva", "info", f"caixa {_pct(w[C.IDS.index('caixa')])}", "defina a despesa mensal",
                     "Sem a despesa mensal na ficha não dá para dimensionar a reserva.", "Pergunte quanto o cliente gasta por mês."))
    else:
        nec = max(necessidade, 0.0)
        tol = 0.002 * pl
        st = "ok" if caixa >= nec - tol else "atencao" if macio >= nec - tol else "fora"
        ck.append(_c("liquidez", "Liquidez e reserva", st, f"{brl(caixa)} em caixa", brl(nec),
                     f"A reserva ({int(f['liquidez'].get('reserva_meses') or 0)} meses de despesa + saídas dos próximos 12 meses) pede {brl(nec)}; o caixa da proposta tem {brl(caixa)}.",
                     "" if st == "ok" else "Aumente o caixa (Tesouro Selic ou CDB com liquidez diária) até cobrir a reserva."))
    # 6. concentracao ---------------------------------------------------------------------------------------------------------
    st = _escala(a["maior_classe"], 0.50, 0.65)
    ck.append(_c("concentracao", "Concentração por classe", st, f"{_pct(a['maior_classe'])} em {nome_cls(a['maior_classe_id'])}", "até 50%",
                 f"A maior classe pesa {_pct(a['maior_classe'])}. Para caber no FGC (R$ 250 mil por CPF e por banco), a renda fixa de banco/crédito pede ao menos {a['emissores_fgc']} emissores (estimativa).",
                 "" if st == "ok" else "Reparta entre classes parecidas e entre emissores."))
    if a["emissores_fgc"] > 15:
        ck.append(_c("fgc", "Emissores para caber no FGC", "atencao", str(a["emissores_fgc"]), "até 15",
                     f"São necessários cerca de {a['emissores_fgc']} emissores para ficar sob o garantidor; é muita operação.", "Considere Tesouro, fundos de crédito e debêntures com análise própria."))

    # 7. fiscal / IRPFM -------------------------------------------------------------------------------------------------------
    renda = f["fluxo"].get("renda_anual_para_irpfm")
    prot = a["irpfm"]["protegido"]
    if renda is None:
        ck.append(_c("irpfm", "IRPFM (Lei 15.270/2025)", "info", f"{_pct(prot,0)} protegido", "informe a renda anual",
                     f"{_pct(prot,0)} da carteira está em veículo que o IRPFM não alcança ou neutraliza; para saber se importa, preciso da renda anual do cliente.",
                     "Pergunte a renda anual total."))
    elif renda < 600_000:
        ck.append(_c("irpfm", "IRPFM (Lei 15.270/2025)", "info", f"renda {brl(renda)}", "alcança acima de R$ 600 mil/ano",
                     "Renda anual abaixo do corte de R$ 600 mil: o imposto mínimo não deve alcançar o cliente (confirmar com o tributarista).", ""))
    else:
        st = _escala(prot, 0.70, 0.50, menor_e_melhor=False)
        ck.append(_c("irpfm", "IRPFM (Lei 15.270/2025)", st, f"{_pct(prot,0)} protegido", "70% ou mais",
                     f"Com renda de {brl(renda)} por ano, o cliente entra no imposto mínimo; {_pct(a['irpfm']['excluido'],0)} da carteira está fora da base (isentos), {_pct(a['irpfm']['diferido'],0)} diferido (previdência) e {_pct(a['irpfm']['exposto'],0)} exposto.",
                     "" if st == "ok" else "Leve mais para isentos (LCA, CRA, CRI, incentivadas) e previdência, sem perder a liquidez."))

    # 8. moeda ---------------------------------------------------------------------------------------------------------------------
    need = float(f["moeda"].get("despesas_em_dolar_pct") or 0.0) / 100.0   # a ficha guarda em % (20 = 20%)
    if need > 0:
        ok = 0.8 * need <= a["usd"] <= need + 0.15
        ck.append(_c("moeda", "Exposição ao dólar", "ok" if ok else "atencao", _pct(a["usd"]), f"~{_pct(need,0)} das despesas em dólar",
                     f"{_pct(a['usd'])} da carteira está em ativos em dólar contra {_pct(need,0)} de despesas na moeda.",
                     "" if ok else "Ajuste o dólar para cobrir o gasto futuro na moeda (renda variável internacional, ouro, UCITS)."))
    else:
        st = "ok" if a["usd"] <= 0.30 else "atencao" if a["usd"] <= 0.50 else "fora"
        ck.append(_c("moeda", "Exposição ao dólar", st, _pct(a["usd"]), "até 30% sem despesa em dólar",
                     f"{_pct(a['usd'])} em ativos dólar. Sem despesa na moeda, dólar além de uma proteção vira aposta cambial."))

    # 9. dependencia do CDI ------------------------------------------------------------------------------------------------------
    st = "ok" if a["cdi_dep"] <= 0.60 else "atencao"
    ck.append(_c("juros", "Dependência do CDI alto", st, _pct(a["cdi_dep"], 0), "até 60%",
                 f"{_pct(a['cdi_dep'],0)} da carteira rende CDI e {_pct(a['travado'],0)} está travado em taxa (IPCA+/pré). Se o CDI médio vier abaixo da curva, a parte pós perde; veja a sensibilidade na simulação.",
                 "" if st == "ok" else "Trave parte em IPCA+ ou pré enquanto a taxa está alta."))

    # 10. diversificacao pelo risco ------------------------------------------------------------------------------------------------
    top = float(np.max(a["rc"]))
    topc = C.IDS[int(np.argmax(a["rc"]))]
    st = _escala(top, 0.50, 0.65)
    ck.append(_c("risco", "Diversificação do risco", st, f"{_pct(top,0)} do risco em {nome_cls(topc)}", "até 50%",
                 f"Uma classe responde por {_pct(top,0)} do risco total; o número efetivo de apostas independentes é {num(a['enb'], 1)}.",
                 "" if st == "ok" else f"Reduza {nome_cls(topc)} ou aumente classes de comportamento diferente."))

    # 11. custos ---------------------------------------------------------------------------------------------------------------------
    st = _escala(a["custo"], 0.007, 0.011)
    ck.append(_c("custos", "Custos embutidos", st, f"{_pct(a['custo'],2)} ao ano", "até 0,70%",
                 f"Custo médio ponderado de {_pct(a['custo'],2)} ao ano (já descontado do retorno esperado).",
                 "" if st == "ok" else "Prefira ETFs e títulos diretos onde o gestor não agrega."))

    # 12. visoes do Douglas --------------------------------------------------------------------------------------------------------------
    for v in ctx.visoes:
        cid = v["classe"]
        if cid in C.POR_ID and v.get("direcao", 0) != 0:
            i = C.IDS.index(cid)
            dist = (w[i] - float(ctx.w_modelo[i])) * 100.0
            alvo = v["direcao"]
            movido = dist * alvo
            lo, hi = ctx.restr.lo[i], ctx.restr.hi[i]
            na_borda = (alvo > 0 and w[i] >= hi - 0.0026) or (alvo < 0 and w[i] <= lo + 0.0026)
            st = "ok" if movido >= 0.5 else "fora" if movido <= -0.5 else "atencao"
            leitura = f"Visão: {'mais' if alvo>0 else 'menos'} {nome_cls(cid)} ({v['tese']}). A proposta está {_pp(dist/100.0)} do modelo do perfil"
            leitura += " (no limite da banda)." if na_borda else "."
            ck.append(_c(f"visao_{v['id']}", f"Visão: {'mais' if alvo>0 else 'menos'} {nome_cls(cid)}", st, _pp(dist / 100.0),
                         "no sentido da visão", leitura,
                         "" if st == "ok" else ("Mexa a banda do cliente ou a proposta para refletir a visão." if st == "atencao" else "A proposta anda no sentido contrário à visão: revise.")))

    # 13. sucessao e protecao ------------------------------------------------------------------------------------------------------------------
    suc = f["sucessao"]
    dep = f["pessoa"].get("dependentes") or 0
    if all(suc.get(k) is None for k in suc):
        ck.append(_c("sucessao", "Sucessão e proteção", "info", "não informado", "—",
                     "Sem informação de testamento, holding, seguro ou previdência: fora do escopo desta alocação, mas muda a recomendação.", "Pergunte."))
    else:
        falta = dep > 0 and not suc.get("seguro_de_vida") and w[C.IDS.index("vgbl")] < 0.01
        ck.append(_c("sucessao", "Sucessão e proteção", "atencao" if falta else "ok", "dependentes: %s" % dep, "—",
                     "Há dependentes sem seguro de vida e sem previdência: avalie VGBL/PGBL e seguro." if falta else "Sem pendência óbvia."))

    # 14. dados ------------------------------------------------------------------------------------------------------------------------------------
    lac = CL.lacunas(f)
    crit = [x for x in lac if x["peso"] == 1]
    imp = [x for x in lac if x["peso"] == 2]
    st = "fora" if crit else "atencao" if imp else "ok"
    ck.append(_c("dados", "Completude da ficha", st, f"{len(crit)} críticas, {len(imp)} importantes", "nenhuma crítica",
                 "Faltam dados críticos: " + "; ".join(x["pergunta"] for x in crit[:2]) if crit else
                 ("Faltam informações que mudam a proposta: " + "; ".join(x["pergunta"] for x in imp[:2]) if imp else "Ficha completa."),
                 "" if st == "ok" else "Pergunte ao cliente antes de fechar."))

    # 15. mercado -------------------------------------------------------------------------------------------------------------------------------------
    m = ctx.mercado
    if m.veredito != "ATUAL" or m.em_choque:
        msg = "Dado de mercado velho: " + "; ".join(m.avisos[:2]) if m.veredito != "ATUAL" else \
            f"Mercado em choque hoje (DI de 3 anos {m.choque_bps:+.0f} bps contra o último ajuste): taxas de IPCA+ e pré são estimativas até o balcão confirmar."
        ck.append(_c("mercado", "Dado de mercado", "atencao", m.veredito + (" · em choque" if m.em_choque else ""), "atual e sem choque", msg,
                     "Confirme taxas no balcão antes de levar números ao cliente."))
    else:
        ck.append(_c("mercado", "Dado de mercado", "ok", "ATUAL", "atual", f"Curva DI de {m.di_data}, NTN-B de {m.ntnb_data}, Focus de {m.focus_data}."))
    return ck


def veredito(checks: list[dict]) -> dict:
    n = {"ok": 0, "atencao": 0, "fora": 0, "info": 0}
    for c in checks:
        n[c["status"]] += 1
    if n["fora"]:
        v, cor = "FORA DO ALINHAMENTO", "fora"
    elif n["atencao"]:
        v, cor = "ALINHADA COM RESSALVAS", "atencao"
    else:
        v, cor = "ALINHADA", "ok"
    return {"veredito": v, "status": cor, "contagem": n}


def resumo_texto(checks: list[dict], ver: dict) -> str:
    """Bloco curto para colar na conversa (celular): uma linha por checagem."""
    linhas = [f"**{ver['veredito']}** — {ver['contagem']['ok']} ✅ · {ver['contagem']['atencao']} 🟡 · {ver['contagem']['fora']} 🔴"]
    for c in checks:
        if c["status"] == "info":
            continue
        linhas.append(f"{SIMBOLO[c['status']]} **{c['titulo']}**: {c['valor']} (limite {c['limite']}). {c['leitura']}" + (f" → {c['acao']}" if c["acao"] else ""))
    return "\n".join(linhas)
