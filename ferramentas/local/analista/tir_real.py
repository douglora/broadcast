#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TIR real implicita: a taxa de retorno REAL (acima da inflacao) que o preco de hoje
entrega a quem compra a acao, medida pelo caixa que sobra para o acionista, e o premio
dela sobre a NTN-B. E a regua de Octavio Magalhaes (Guepardo) nas falas publicas dele:
projetar o fluxo de caixa da empresa por dez anos, falar em retorno real (IPCA + X%) e
comparar com a NTN-B. O que ele NAO publicou (qual fluxo, valor terminal, premio minimo)
aqui e escolha da mesa e sai rotulado como tal. Nao e "a TIR da Guepardo".

Serve para empresa de caixa previsivel (energia, saneamento, concessao com receita
corrigida por contrato). Em empresa ciclica a conta roda, mas sai com aviso.

Modelo, tudo em reais de hoje (R$ milhoes), ano a ano (t = 1..N, padrao N = 10):
  caixa operacional = conv x EBITDA_t         conv = (caixa operacional + juros pagos nele) / EBITDA,
                                              mediana de 5 exercicios e dos 12 meses (ja depois do
                                              imposto pago e do capital de giro)
  investimento      = reposicao (depreciacao) + crescimento (capital por real de EBITDA novo)
  custo da divida   = custo REAL x divida bruta do ano anterior
                      (custo real = encargo por competencia / divida media, descontada a inflacao
                      do mesmo periodo; converge para a NTN-B em 5 anos, porque a divida vence e
                      e rolada a mercado)
  divida            = cresce junto com o EBITDA (alavancagem constante)
  caixa do dono     = caixa operacional - investimento - custo da divida + divida nova
  depois do ano N   = perpetuidade com crescimento real g_T (padrao 0), ou fim da concessao com
                      valor residual informado
  TIR real          = taxa que iguala o valor presente desse fluxo ao valor de mercado

Por que custo REAL da divida: com a divida mantida constante em termos reais, a empresa
rola a correcao monetaria; o que sai do bolso do dono e so o juro acima da inflacao. E por
que competencia: "juros pagos" nao mostra a correcao da divida em IPCA, que fica no principal.
"""

from __future__ import annotations

import datetime as dt
import math

from . import base as B
from . import cvm_integral as C
from . import macro as MAC

HORIZONTE = 10
CONVERGE = 5          # anos para o custo real da divida chegar a NTN-B (premissa da mesa)
PREMISSAS = B.CACHE / "premissas"
CHAVES = ("ebitda0", "ebitda", "g", "capex", "conv", "custo_real_divida", "fim", "residual", "g_t", "k_manut", "m_cap")


def _defl(tab, ipca):
    """Serie anual em reais do ultimo IPCA publicado: [(fim, contas_reais, fator)]."""
    out = []
    for fim, o in tab["anos"].items():
        f = B.fator_ipca(fim[:7], serie=ipca)
        out.append((fim, {k: (v * f if isinstance(v, (int, float)) and not isinstance(v, bool) else v) for k, v in o.items()}, f))
    return out


def tendencia(pontos):
    """Crescimento anual pela mediana das inclinacoes entre todos os pares (Theil-Sen) do log:
    um ano fora da curva nao muda o resultado. pontos = [(tempo_em_anos, valor > 0)]."""
    pts = [(t, math.log(v)) for t, v in pontos if v and v > 0]
    incl = [(y2 - y1) / (t2 - t1) for i, (t1, y1) in enumerate(pts) for (t2, y2) in pts[i + 1:] if t2 > t1]
    return (math.exp(B.mediana(incl)) - 1.0) if len(pts) >= 4 else None


def _anos(iso):
    d = dt.date.fromisoformat(iso)
    return d.year + (d.timetuple().tm_yday - 1) / 365.25


def insumos(ticker, livro=None, d=None, integral=None, mac=None, preco=None):
    """Tudo o que a conta usa, tirado dos balancos integrais (CVM), do preco e do momento economico."""
    livro = livro or B.Livro()
    d = d or B.ativo(ticker)
    cvm = d.get("cvm_demonstracoes") or {}
    if not cvm.get("cd_cvm"):
        raise B.SemDado(f"{ticker}: sem código CVM no JSON (BDR ou empresa estrangeira: esta conta usa DFP e ITR da CVM)")
    if cvm.get("plano_de_contas") == "instituicao_financeira":
        raise B.SemDado(f"{ticker}: banco ou seguradora. Não existe caixa do acionista por EBITDA aqui; use o comando "
                        "damodaran (retorno em excesso sobre o patrimônio).")
    integral = integral or C.carregar(cvm["cd_cvm"])
    tab = C.tabela(integral)
    mac = mac or MAC.carregar()
    ipca = B.ipca_mensal()
    pv = B.preco_e_valor(d, integral, livro, preco)
    ltm, serie = tab["ltm"], _defl(tab, ipca)
    f_ltm = B.fator_ipca(tab["ltm_ate"][:7], serie=ipca)
    falta = [k for k in ("ebitda", "fco", "da", "divida_bruta") if ltm.get(k) is None]
    if falta:
        raise B.SemDado(f"{ticker}: balanço sem {', '.join(falta)} nos últimos 12 meses (CVM)")
    if ltm["ebitda"] <= 0:
        raise B.SemDado(f"{ticker}: EBITDA negativo nos últimos 12 meses; não há caixa previsível para medir")
    fonte_ltm = f"CVM, {tab['ltm_composicao']}"
    p = livro.p
    # ---- caixa operacional antes dos juros
    jo, jf = ltm.get("juros_pagos_operacional"), ltm.get("juros_pagos_financiamento")
    pagos = (jo or 0.0) + (jf or 0.0)
    if jo is None and jf is None and not ltm.get("juros_no_financiamento"):
        livro.aviso("O fluxo de caixa não abre 'juros pagos' em linha própria: tratei o caixa operacional como se já "
                    "estivesse antes dos juros SEM somar nada de volta. Se os juros estão dentro dele, a TIR aqui está "
                    "subestimada; confira a nota do fluxo de caixa.")
    fco_pre = ltm["fco"] + (jo or 0.0)
    convs = []
    for fim, o, _ in serie[-5:]:
        if o.get("ebitda") and o["ebitda"] > 0 and o.get("fco") is not None:
            convs.append(((o["fco"] + (o.get("juros_pagos_operacional") or 0.0)) / o["ebitda"], fim[:4]))
    conv_ltm = fco_pre / ltm["ebitda"]
    if tab["ltm_ate"] != serie[-1][0]:
        convs.append((conv_ltm, "12m"))
    conv = B.mediana([c for c, _ in convs])
    # ---- custo da divida por competencia, em termos reais
    db = ltm["divida_bruta"]
    db_media, ini = C.saldo_medio(tab, "divida_bruta")
    ipca_janela = B.fator_ipca(ini[:7], tab["ltm_ate"][:7], ipca) - 1.0 if ini else None
    enc = ltm.get("encargos_divida")
    teto = abs(ltm.get("despesas_financeiras") or 0.0) or abs(ltm.get("juros_dva") or 0.0)
    nominal = fonte_custo = None
    if db_media and db_media > 1.0:
        if enc and enc >= 0.8 * pagos and (not teto or enc <= 1.1 * teto):
            nominal = enc / db_media
            fonte_custo = "CVM, fluxo de caixa: " + "; ".join(x.split(" ", 1)[1][:60] for x in (ltm.get("_de_onde") or {}).get("encargos_divida", [])[:2])
        elif teto:
            nominal, fonte_custo = teto / db_media, "CVM, despesa financeira total da DRE (3.06.02)"
            livro.aviso("O fluxo de caixa não abre o encargo da dívida por competência: usei a despesa financeira TOTAL da "
                        "DRE, que inclui itens que não são dívida. O custo da dívida aqui é teto e a TIR, piso.")
        elif pagos:
            nominal, fonte_custo = pagos / db_media, "CVM, juros pagos no fluxo de caixa"
            livro.aviso("Custo da dívida medido só pelos juros pagos (sem a correção monetária do principal): pode estar "
                        "subestimado se há dívida em IPCA.")
    if nominal is None:
        raise B.SemDado(f"{ticker}: não há como medir o custo da dívida (sem encargos, sem despesa financeira e sem juros "
                        "pagos na CVM). Sem isso a TIR não sai.")
    custo_real = B.real(nominal, ipca_janela)
    ntnb = mac["ntnb_2035"]
    if custo_real < ntnb - 0.02 or custo_real > ntnb + 0.06:
        livro.aviso(f"O custo real da dívida medido ({B.pct(custo_real)}) está longe da NTN-B 2035 ({B.pct(ntnb)}): pode haver "
                    "dívida subsidiada, ganho ou perda cambial ou marcação a mercado na linha de encargos. A conta leva o "
                    "custo para a NTN-B em 5 anos; veja a linha de estresse com o custo medido para sempre.")
    # a divida que custa: liquida do caixa quando a renda do caixa NAO passa pelo caixa operacional
    caixa = ltm.get("caixa") or 0.0
    renda_fora = bool(ltm.get("renda_caixa_fora"))
    base_div = max(0.0, db - caixa) if renda_fora else db
    # o EBITDA e consolidado (100% das controladas); o valor de mercado e so do acionista da holding
    fm = 0.0
    if ltm.get("pl") and ltm["pl"] > 0 and (ltm.get("minoritarios") or 0.0) > 0:
        fm = min(0.9, ltm["minoritarios"] / ltm["pl"])
        if fm > 0.01:
            p("Fatia dos sócios minoritários das controladas", fm, "do caixa", "CVM: participação de não controladores / "
              "patrimônio líquido total (2.03.09 / 2.03)", tab["saldos_em"], B.OFICIAL,
              "o caixa do dono é multiplicado por 1 menos essa fatia; é aproximação pelo valor contábil")
    ebitda0, da0 = ltm["ebitda"] * f_ltm, ltm["da"] * f_ltm
    if da0 < 0.05 * ebitda0:
        livro.aviso(f"A depreciação ({B.mi(da0)}) é menos de 5% do EBITDA: a empresa contabiliza a concessão como ativo de "
                    "contrato ou financeiro (transmissão, por exemplo). O EBITDA contábil não é caixa e o investimento passa "
                    "pelo caixa operacional; a conta usa a conversão de caixa medida, mas concessão tem data para acabar: "
                    "informe 'fim' e 'residual' no caso da mesa, senão a perpetuidade superestima.")
    ic = (ltm.get("divida_liquida") or 0.0) + (ltm.get("pl") or 0.0)
    m_cap = ic / ltm["ebitda"] if ic > 0 else None
    capex5 = B.mediana([o.get("capex") for _, o, _ in serie[-5:]])
    p("EBITDA dos últimos 12 meses", ebitda0, "R$ mi de hoje", fonte_ltm + " (lucro antes do resultado financeiro e do imposto + depreciação)", tab["ltm_ate"], B.OFICIAL)
    p("Depreciação e amortização 12 meses", da0, "R$ mi de hoje", "CVM, demonstração do valor adicionado 7.04.01", tab["ltm_ate"], B.OFICIAL)
    p("Conversão de caixa (caixa operacional antes dos juros / EBITDA)", conv, "x",
      "CVM, mediana de " + ", ".join(f"{a} {B.br(c, 2)}" for c, a in convs), tab["ltm_ate"], B.OFICIAL,
      "já depois do imposto pago e do capital de giro")
    p("Dívida bruta", db, "R$ mi", "CVM: empréstimos e financiamentos (2.01.04 + 2.02.01)", tab["saldos_em"], B.OFICIAL,
      f"caixa e aplicações: {B.mi(caixa)}; " + ("o fluxo de caixa tira o rendimento das aplicações do caixa operacional, "
      "então a conta cobra o custo só sobre a dívida líquida" if renda_fora else "a renda do caixa já está dentro do caixa "
      "operacional, então a conta cobra o custo sobre a dívida bruta"))
    if nominal is not None:
        p("Custo nominal da dívida em 12 meses", nominal, "a.a.", fonte_custo + f" / dívida bruta média {B.mi(db_media)}",
          tab["ltm_ate"], B.OFICIAL, f"juros pagos em caixa no período: {B.mi(pagos)}")
        p("Custo real da dívida em 12 meses", custo_real, "a.a.", f"custo nominal descontado o IPCA do mesmo período ({B.pct(ipca_janela, 2)})",
          tab["ltm_ate"], B.OFICIAL)
    # ---- historia em reais de hoje
    hist = []
    for fim, o, _ in serie:
        fco_h = o.get("fco")
        hist.append({"ano": fim[:4], "fim": fim, "receita": o.get("receita"), "ebitda": o.get("ebitda"), "fco": fco_h,
                     "capex": o.get("capex"), "da": o.get("da"), "lucro": o.get("lucro_controladores"),
                     "dividendos": o.get("dividendos_pagos"), "divida_liquida": o.get("divida_liquida"),
                     "fco_pre": (fco_h + (o.get("juros_pagos_operacional") or 0.0)) if fco_h is not None else None,
                     "livre": (fco_h - (o.get("juros_pagos_financiamento") or 0.0) - o["capex"]) if (fco_h is not None and o.get("capex") is not None) else None})
    limpo = lambda o, f=1.0: ((o["ebitda"] - (o.get("outras_receitas_op") or 0.0) - (o.get("outras_despesas_op") or 0.0)) * f
                              if o.get("ebitda") else None)
    pts = [(_anos(fim), limpo(o)) for fim, o, _ in serie[-5:]]
    if tab["ltm_ate"] != serie[-1][0]:
        pts.append((_anos(tab["ltm_ate"]), limpo(ltm, f_ltm)))
    g_hist = tendencia(pts)        # EBITDA sem "outras receitas e despesas", em reais de hoje (informativo)
    # ---- alertas de qualidade do numero
    orc, odp = ltm.get("outras_receitas_op") or 0.0, ltm.get("outras_despesas_op") or 0.0
    if orc > 0.05 * ltm["ebitda"] or abs(odp) > 0.10 * ltm["ebitda"]:
        livro.aviso(f"O EBITDA dos 12 meses carrega {B.mi(orc)} de outras receitas e {B.mi(abs(odp))} de outras despesas "
                    "operacionais (DRE 3.04.04 e 3.04.05). Confira no release o que é não recorrente; o EBITDA recorrente "
                    "entra pela premissa ebitda0, com a página do release.")
    if ltm.get("lair") and ltm["lair"] > 0 and ltm.get("ir_pago") is not None and ltm["ir_pago"] / ltm["lair"] < 0.15:
        livro.aviso(f"O imposto de renda pago em caixa foi {B.pct(ltm['ir_pago'] / ltm['lair'], 0)} do lucro antes do imposto "
                    "(alíquota legal: 34%). Se a diferença for crédito temporário, o caixa futuro é menor que o medido.")
    if da0 and capex5 and capex5 / da0 > 1.5:
        livro.aviso(f"O investimento mediano dos últimos 5 anos ({B.mi(capex5)}, em reais de hoje) é {B.br(capex5 / da0, 1)}x a "
                    "depreciação. O caso 'caixa parado' supõe que repor a depreciação basta para manter o EBITDA: a "
                    "depreciação é a custo histórico e costuma ficar abaixo do custo de reposição. O teste "
                    "'investindo o que investe hoje, sem crescer' mostra o outro extremo.")
    return {"ticker": ticker.upper().replace(".SA", ""), "pv": pv, "tab": tab, "mac": mac, "livro": livro, "hist_real": hist,
            "ebitda0": ebitda0, "da0": da0, "conv": conv, "convs": convs, "conv_ltm": conv_ltm, "juros_pagos": pagos,
            "divida0": base_div, "fracao_minoritarios": fm, "divida_bruta": db, "base_divida": "liquida" if renda_fora else "bruta",
            "caixa": caixa, "divida_liquida": ltm.get("divida_liquida"),
            "custo_nominal": nominal, "custo_real": custo_real, "ipca_janela": ipca_janela, "m_cap": m_cap,
            "capex5_real": capex5, "capex_ltm": (ltm.get("capex") or 0.0) * f_ltm, "g_hist": g_hist,
            "lucro_ltm": ltm.get("lucro_controladores"), "div_ltm": ltm.get("dividendos_pagos"),
            "pl": ltm.get("pl_controladores"), "ltm_ate": tab["ltm_ate"], "f_ltm": f_ltm, "d": d, "integral": integral}


def _lista(x, n, depois=None):
    """Numero ou lista -> lista de n valores (lista curta repete o ultimo, ou `depois`)."""
    if isinstance(x, (list, tuple)):
        xs = list(x)
        return (xs + [xs[-1] if depois is None else depois] * n)[:n]
    return [x] * n


def fluxo(ins, ebitda=None, g=0.0, g_t=0.0, k_manut=1.0, m_cap=None, capex=None, conv=None, custo_div=None,
          rolagem=True, n=HORIZONTE, fim=None, residual=0.0, ebitda0=None, divida0=None):
    """Caixa do dono ano a ano, em reais de hoje.
    ebitda: lista do EBITDA por ano (premissa); senao cresce g (numero ou lista) sobre ebitda0.
    capex: investimento TOTAL por ano (numero = constante; lista = plano); senao reposicao + crescimento.
    custo_div: custo real da divida (numero ou lista); senao converge do medido para a NTN-B 2035.
    rolagem=False: a empresa nao rola a correcao monetaria (divida nominal parada, encolhe em termos reais)."""
    mac = ins["mac"]
    ano0 = dt.date.today().year
    if fim:
        n = max(1, int(fim) - ano0)
    e0 = ins["ebitda0"] if ebitda0 is None else ebitda0
    gs = _lista(g, n)
    conv = ins["conv"] if conv is None else conv
    m_cap = ins["m_cap"] if m_cap is None else m_cap
    if custo_div is None:
        a, b = ins["custo_real"], mac["ntnb_2035"]
        rds = [a + (b - a) * min(1.0, (t - 1) / float(CONVERGE - 1)) for t in range(1, n + 2)]
    else:
        rds = _lista(custo_div, n + 1)
    caps = None if capex is None else _lista(capex, n)
    e_ant, d_ant = e0, (ins["divida0"] if divida0 is None else divida0)
    fm = ins.get("fracao_minoritarios") or 0.0
    alav = d_ant / e0 if e0 else 0.0
    da_e = ins["da0"] / ins["ebitda0"]
    linhas = []
    for t in range(1, n + 2):                      # o ano n+1 e o ano-tipo da perpetuidade
        gt = gs[t - 1] if t <= n else g_t
        e = ebitda[t - 1] if (ebitda and t <= len(ebitda)) else e_ant * (1.0 + gt)
        gt = e / e_ant - 1.0 if e_ant else 0.0
        pi = MAC.inflacao_ano(mac, ano0 + t)
        oper = conv * e
        manut = k_manut * da_e * e
        cresc = max(0.0, e - e_ant) * (m_cap or 0.0)
        inv = caps[t - 1] if (caps and t <= n) else manut + cresc
        rd = rds[t - 1]
        if rolagem:
            d = alav * e
            custo, nova = rd * d_ant, d - d_ant
        else:
            d = d_ant / (1.0 + pi)
            custo, nova = B.nominal(rd, pi) * d_ant / (1.0 + pi), 0.0
        total = oper - inv - custo + nova
        linhas.append({"t": t, "ano": ano0 + t, "g": gt, "ipca": pi, "ebitda": e, "caixa_oper": oper, "investimento": inv,
                       "custo_real_divida": rd, "custo_divida": custo, "divida_nova": nova, "divida": d,
                       "minoritarios": total * fm, "dono": total * (1.0 - fm)})
        e_ant, d_ant = e, d
    return {"linhas": linhas[:n], "tipo": linhas[n], "n": n, "g_t": g_t, "fim": fim, "residual": residual}


def valor_presente(fx, r, h=0.0):
    """Valor presente do caixa do dono a taxa r. h: crescimento real extra do caixa do dono (so
    nos anos explicitos), para a conta reversa e a sensibilidade."""
    v = sum(l["dono"] * (1.0 + h) ** l["t"] / (1.0 + r) ** l["t"] for l in fx["linhas"])
    n = fx["n"]
    if fx["fim"]:
        term = fx["residual"]
    else:
        if r - fx["g_t"] <= 1e-7:
            return float("inf")
        term = fx["tipo"]["dono"] * (1.0 + h) ** n / (r - fx["g_t"])
    return v + term / (1.0 + r) ** n


def _raiz(f, lo, hi, n=200):
    a, b = f(lo), f(hi)
    if a != a or b != b or a * b > 0:
        return None
    for _ in range(n):
        m = (lo + hi) / 2.0
        c = f(m)
        if a * c <= 0:
            hi, b = m, c
        else:
            lo, a = m, c
    return (lo + hi) / 2.0


def tir_do_fluxo(fx, valor, h=0.0):
    """Taxa real que iguala o valor presente do caixa do dono ao valor de mercado (bissecao)."""
    if valor <= 0:
        return None
    if not fx["fim"] and fx["tipo"]["dono"] <= 0:
        return None
    lo = (fx["g_t"] + 1e-6) if not fx["fim"] else -0.9
    return _raiz(lambda r: valor_presente(fx, r, h) - valor, lo, 2.0)


def crescimento_para(fx, valor, taxa):
    """Conta reversa: quanto o caixa do dono precisa crescer ao ano, acima da inflacao, nos anos
    explicitos, para o preco de hoje entregar `taxa` real."""
    if not fx["fim"] and fx["tipo"]["dono"] <= 0:
        return None
    return _raiz(lambda h: valor_presente(fx, taxa, h) - valor, -0.5, 1.5)


def preco_para(fx, valor, preco, taxa):
    v = valor_presente(fx, taxa)
    return None if v in (float("inf"),) or v <= 0 else v / valor * preco


def ebitda_para(ins, valor, taxa, **kw):
    """Conta reversa pelo nivel: o EBITDA recorrente de partida que faz o caixa parado entregar
    `taxa` real ao valor de mercado de hoje (a divida fica a de hoje)."""
    f = _raiz(lambda x: valor_presente(fluxo(ins, ebitda0=ins["ebitda0"] * x, **kw), taxa) - valor, 0.3, 6.0)
    return None if f is None else ins["ebitda0"] * f


def ler_premissas(ticker):
    """Premissas documentadas do ativo (dados_local/analista/premissas/TICKER.json). Cada item:
    {"valor": ..., "fonte": "documento e pagina", "data": "AAAA-MM-DD", "tipo": "OFICIAL|GUIDANCE|CONSENSO|MESA"}.
    Premissa sem fonte nao entra na conta."""
    arq = PREMISSAS / f"{ticker.upper()}.json"
    d = B.ler_json(arq)
    if not d:
        return None
    itens = d.get("itens") or {}
    for k, x in itens.items():
        if k not in CHAVES:
            raise B.SemDado(f"{arq.name}: premissa desconhecida '{k}' (aceitas: {', '.join(CHAVES)})")
        if not isinstance(x, dict) or "valor" not in x or not str(x.get("fonte") or "").strip():
            raise B.SemDado(f"{arq.name}: premissa '{k}' sem valor ou sem fonte. Premissa sem documento não entra.")
    return d


ROTULO = {"ebitda0": ("EBITDA recorrente de partida", "R$ mi"), "ebitda": ("EBITDA por ano", "R$ mi de hoje"),
          "g": ("Crescimento real do EBITDA", "a.a."), "capex": ("Investimento total por ano", "R$ mi de hoje"),
          "conv": ("Conversão de caixa", "x"), "custo_real_divida": ("Custo real da dívida", "a.a."),
          "fim": ("Fim da concessão (o fluxo para aqui)", "ano"), "residual": ("Valor residual no fim da concessão", "R$ mi de hoje"),
          "g_t": ("Crescimento real depois do ano 10", "a.a."), "k_manut": ("Investimento de reposição / depreciação", "x"),
          "m_cap": ("Investimento por real de EBITDA novo", "x")}


def _cenario(nome, descricao, fx, vm, ntnb):
    r = tir_do_fluxo(fx, vm)
    return {"nome": nome, "descricao": descricao, "tir": r, "premio": (r - ntnb) if r is not None else None, "fluxo": fx}


def calcular(ticker, ins=None, premissas=None, preco=None, previsivel=None, alvos=None):
    """Conta completa. premissas: dict no formato do arquivo do ativo (padrao: le o arquivo).
    alvos: [(rotulo, taxa_real)] para a conta reversa (ex.: a TIR que o Safra publica)."""
    ins = ins or insumos(ticker, preco=preco)
    livro, mac, pv = ins["livro"], ins["mac"], ins["pv"]
    vm, ntnb = pv["valor_mercado"], mac["ntnb_2035"]
    exige = mac["regime"]["premio_exigido"]
    p = livro.p
    p("NTN-B 2035 (régua)", ntnb, "a.a. real", "ANBIMA, taxa indicativa (cache do terminal)", mac["ntnb_data"], B.MERCADO)
    p("Crescimento real no caso 'caixa parado'", 0.0, "a.a.", "premissa da mesa: o piso é a empresa não crescer", "", B.MESA)
    p("Investimento de reposição = depreciação contábil", 1.0, "x", "premissa da mesa: repor o que se desgasta", "", B.MESA)
    p("Depois do ano 10: perpetuidade sem crescimento real", 0.0, "a.a.", "premissa da mesa (Octavio Magalhães não publica "
      "valor terminal); com data de fim da concessão, use a premissa 'fim'", "", B.MESA)
    p("Custo real da dívida converge para a NTN-B 2035 em 5 anos", ntnb, "a.a.", "premissa da mesa: a dívida vence e é "
      "rolada a mercado, sem prêmio de crédito", mac["ntnb_data"], B.MESA)
    if ins["m_cap"]:
        p("Investimento por real de EBITDA novo", ins["m_cap"], "x", "CVM: (dívida líquida + patrimônio) / EBITDA de hoje",
          ins["ltm_ate"], B.OFICIAL, "crescer custa o mesmo capital por real de EBITDA que a empresa já tem")
    cen = []
    parado = fluxo(ins)
    cen.append(_cenario("Caixa parado", "EBITDA não cresce acima da inflação; investe só a depreciação", parado, vm, ntnb))
    # investindo no ritmo atual: o que passa da depreciacao vira EBITDA novo com o retorno que o capital ja tem
    if ins["capex5_real"] and ins["m_cap"] and ins["capex5_real"] > ins["da0"]:
        g_inv = (ins["capex5_real"] - ins["da0"]) / (ins["m_cap"] * ins["ebitda0"])
        cen.append(_cenario("Investindo no ritmo atual",
                            f"mantém o investimento dos últimos 5 anos ({B.mi(ins['capex5_real'])} por ano); o que passa da "
                            f"depreciação vira EBITDA novo com o retorno que o capital já rende: +{B.pct(g_inv)} ao ano por 10 anos",
                            fluxo(ins, g=g_inv), vm, ntnb))
        p("Crescimento real do EBITDA no caso 'investindo no ritmo atual'", g_inv, "a.a.",
          "calculado: (investimento mediano de 5 anos - depreciação) / (capital por real de EBITDA x EBITDA)", ins["ltm_ate"], B.MESA)
    pr = ler_premissas(ins["ticker"]) if premissas is None else premissas
    mesa = None
    if pr and pr.get("itens"):
        it, kw = pr["itens"], {}
        for k, x in it.items():
            rot, un = ROTULO[k]
            p(rot + " (caso da mesa)", x["valor"], un, x["fonte"], x.get("data", ""), x.get("tipo", B.GUIDANCE), x.get("nota", ""))
        for k in ("ebitda", "g", "capex", "conv", "fim", "residual", "g_t", "k_manut", "m_cap"):
            if k in it:
                kw[k] = it[k]["valor"]
        if "custo_real_divida" in it:
            kw["custo_div"] = it["custo_real_divida"]["valor"]
        if "ebitda0" in it:
            kw["ebitda0"] = it["ebitda0"]["valor"] * ins["f_ltm"]
        mesa = fluxo(ins, **kw)
        cen.append(_cenario("Caso da mesa", pr.get("resumo") or "premissas documentadas no release e no guidance (ver o livro)", mesa, vm, ntnb))
    base = cen[0]
    # ---- quanto a resposta muda quando uma premissa muda (sempre sobre o caixa parado)
    def var(nome, **kw):
        r = tir_do_fluxo(fluxo(ins, **kw), vm)
        return {"nome": nome, "tir": r, "delta": (r - base["tir"]) if (r is not None and base["tir"] is not None) else None}
    estresse = [var("Conversão de caixa dos últimos 12 meses (" + B.br(ins["conv_ltm"], 2) + "x)", conv=ins["conv_ltm"]),
                var("Custo real da dívida fica no medido para sempre (" + B.pct(ins["custo_real"]) + ")", custo_div=ins["custo_real"]),
                var("Dívida rolada à NTN-B desde já (" + B.pct(ntnb, 2) + ")", custo_div=ntnb),
                var("Sem rolar a correção monetária da dívida", rolagem=False)]
    if ins["caixa"] and ins["divida_bruta"]:
        outra = ins["divida_bruta"] if ins["base_divida"] == "liquida" else max(0.0, ins["divida_bruta"] - ins["caixa"])
        estresse.append(var("Custo cobrado sobre a dívida " + ("bruta" if ins["base_divida"] == "liquida" else "líquida do caixa")
                            + " (" + B.mi(outra) + ")", divida0=outra))
    if ins["capex5_real"] and ins["da0"]:
        estresse.append(var("Investindo o que investe hoje (" + B.br(ins["capex5_real"] / ins["da0"], 1) + "x a depreciação), sem crescer",
                            k_manut=ins["capex5_real"] / ins["da0"]))
    # ---- conta reversa e precos
    ref = mesa or parado
    alvos = [("NTN-B 2035 + prêmio exigido (" + B.pp(exige) + ")", ntnb + exige)] + list(alvos or [])
    reversa = [{"rotulo": rot, "taxa": tx, "crescimento": crescimento_para(parado, vm, tx), "ebitda": ebitda_para(ins, vm, tx),
                "preco": preco_para(ref, vm, pv["preco"], tx)} for rot, tx in alvos]
    hs, ps = (0.0, 0.02, 0.04, 0.06, 0.08), (0.8, 0.9, 1.0, 1.1, 1.2)
    sens = {"h": hs, "precos": [pv["preco"] * x for x in ps],
            "tir": [[tir_do_fluxo(parado, vm * x, h) for x in ps] for h in hs]}
    prev = previsibilidade(ins, previsivel)
    if prev["aviso"]:
        livro.aviso(prev["frase"])
    le = lentes(ins, vm)
    return {"ticker": ins["ticker"], "valor_mercado": vm, "preco": pv["preco"], "data_preco": pv["data"],
            "ntnb_2035": ntnb, "premio_exigido": exige, "regime": mac["regime"]["nome"], "cenarios": cen,
            "tir_base": base["tir"], "premio_base": base["premio"], "central": cen[-1] if mesa else base,
            "estresse": estresse, "reversa": reversa, "sensibilidade": sens, "lentes": le, "previsibilidade": prev,
            "preco_teto": reversa[0]["preco"], "preco_sem_premio": preco_para(ref, vm, pv["preco"], ntnb),
            "dono_hoje": parado["tipo"]["dono"], "ins": ins, "livro": livro, "tem_mesa": bool(mesa)}


def lentes(ins, vm):
    """Rendimentos simples sobre o valor de mercado, so com numero publicado: conferencia, nao TIR."""
    out = {}
    if ins.get("lucro_ltm"):
        out["lucro_sobre_preco"] = ins["lucro_ltm"] / vm
        try:
            pi12 = B.ipca_12m()
            pi12 = (pi12[0] if isinstance(pi12, (tuple, list)) else pi12) / 100.0
        except Exception:
            pi12 = None
        if pi12 and ins.get("divida0"):                    # o juro nominal paga inflacao que, em termos reais, e amortizacao
            out["lucro_real_sobre_preco"] = (ins["lucro_ltm"] + pi12 * ins["divida0"] * (1.0 - (ins.get("fracao_minoritarios") or 0.0))) / vm
    if ins.get("div_ltm") is not None:
        out["dividendos_pagos_sobre_preco"] = ins["div_ltm"] / vm
    h = [x["dividendos"] for x in ins["hist_real"][-5:] if x.get("dividendos") is not None]
    if h:
        out["dividendos_mediana_5a_sobre_preco"] = B.mediana(h) / vm
    hh = [x["livre"] for x in ins["hist_real"][-5:] if x.get("livre") is not None]
    if hh:
        out["caixa_livre_5a_sobre_preco"] = B.mediana(hh) / vm
    return out


def previsibilidade(ins, previsivel=None):
    """O caixa e previsivel? O setor decide (previsivel=True/False vem do roteiro do setor); a
    historia confere: queda anual do EBITDA real e amplitude da conversao de caixa."""
    eb = [(h["ano"], h["ebitda"]) for h in ins["hist_real"] if h.get("ebitda") and h["ebitda"] > 0]
    quedas = [(b / a - 1.0, ano) for (_, a), (ano, b) in zip(eb, eb[1:])]
    pior, ano = min(quedas) if quedas else (None, None)
    negativos = sum(1 for h in ins["hist_real"] if (h.get("ebitda") or 0) <= 0)
    cs = [c for c, _ in ins["convs"]]
    amp = (max(cs) - min(cs)) if cs else None
    oscilou = bool(negativos) or (pior is not None and pior < -0.25)
    if previsivel is False:
        v, fr, av = "cíclico", ("FORA DO PONTO FORTE: setor de caixa cíclico. A TIR por caixa normalizado é referência fraca; "
                                "cruze com o ciclo e com o preço justo de Damodaran."), True
    elif oscilou and previsivel:
        v, av = "previsível com ressalva", True
        fr = (f"Setor de caixa previsível, mas o EBITDA publicado caiu {B.pct(abs(pior), 0)} em {ano} em termos reais. Em empresa "
              "regulada isso costuma ser item não recorrente (provisão, ganho de um ano só), não ciclo: confira no release "
              "antes de confiar na média.")
    elif oscilou:
        v, av = "oscilante", True
        fr = (f"O EBITDA real já caiu {B.pct(abs(pior), 0)} em um ano ({ano})" if pior is not None else "Houve ano de EBITDA negativo") + \
             ": leia a TIR como faixa, não como ponto, e confira se foi item não recorrente ou ciclo."
    else:
        v, av = "previsível", False
        fr = "Caixa previsível: sem queda anual do EBITDA real acima de 25% na história lida" + \
             (f" (pior ano: {B.pct(pior, 0)} em {ano})." if pior is not None else ".")
    return {"veredito": v, "frase": fr, "aviso": av, "pior_queda_anual": pior, "ano": ano, "amplitude_conversao": amp, "anos": len(eb)}


def texto(o):
    """Saida para a conversa (o relatorio usa o dict)."""
    fx = o["central"]["fluxo"]
    L = [f"TIR REAL IMPLÍCITA  {o['ticker']}  preço {B.reais(o['preco'])} ({B.data_br(o['data_preco'])})  valor de mercado {B.mi(o['valor_mercado'])}",
         "  método da mesa, inspirado nas falas públicas de Octavio Magalhães (fluxo de 10 anos, retorno real, régua NTN-B)",
         f"  {o['previsibilidade']['frase']}", "",
         f"  NTN-B 2035: IPCA + {B.br(o['ntnb_2035'] * 100, 2)}%   |   prêmio que a mesa exige neste regime ({o['regime']}): {B.pp(o['premio_exigido'])}", ""]
    for c in o["cenarios"]:
        L.append(f"  {c['nome']:<28} {('IPCA + ' + B.br(c['tir'] * 100, 1) + '%') if c['tir'] is not None else 'não fecha':>13}"
                 f"   prêmio sobre a NTN-B: {B.pp(c['premio']) if c['premio'] is not None else 'n/d':>8}   {c['descricao']}")
    L += ["", "  O que o preço exige (crescimento real do caixa do dono por 10 anos, partindo do caixa parado):"]
    for r in o["reversa"]:
        L.append(f"   {r['rotulo']:<46} IPCA + {B.br(r['taxa'] * 100, 1)}%: "
                 + (f"crescer {B.pct(r['crescimento'])} ao ano" if r["crescimento"] is not None else "não fecha")
                 + (f"   |   ou EBITDA de {B.mi(r['ebitda'])}" if r.get("ebitda") else "")
                 + (f"   |   ou, sem crescer, preço de {B.reais(r['preco'])}" if r.get("preco") else ""))
    L += ["", f"  Caixa do dono, R$ milhões de hoje ({o['central']['nome'].lower()}):",
          "    ano   EBITDA  caixa oper.  investimento  custo real da dívida  dívida nova  caixa do dono"]
    for l in fx["linhas"]:
        L.append(f"   {l['ano']}  {B.br(l['ebitda'], 0):>7}  {B.br(l['caixa_oper'], 0):>10}  {B.br(l['investimento'], 0):>12}  "
                 f"{B.br(l['custo_divida'], 0):>10} ({B.pct(l['custo_real_divida'])})  {B.br(l['divida_nova'], 0):>11}  {B.br(l['dono'], 0):>13}")
    t = fx["tipo"]
    L.append("   depois: " + (f"fim da concessão em {fx['fim']}, residual {B.mi(fx['residual'])}" if fx["fim"] else
                              f"perpetuidade, caixa do dono {B.br(t['dono'], 0)} crescendo {B.pct(fx['g_t'])} real"))
    L += ["", "  Quanto a resposta muda (sobre o caixa parado):"]
    for e in o["estresse"]:
        L.append(f"   {e['nome']:<74} {('IPCA + ' + B.br(e['tir'] * 100, 1) + '%') if e['tir'] is not None else 'não fecha':>13}  ({B.pp(e['delta'])})")
    le = o["lentes"]
    L += ["", "  Conferência (rendimento simples sobre o valor de mercado, só número publicado):"]
    for k, rot in (("lucro_sobre_preco", "lucro 12 meses"), ("lucro_real_sobre_preco", "lucro 12 meses + correção monetária da dívida (lucro real)"), ("dividendos_pagos_sobre_preco", "dividendos e JCP pagos em 12 meses"),
                   ("dividendos_mediana_5a_sobre_preco", "dividendos pagos, mediana real de 5 anos"),
                   ("caixa_livre_5a_sobre_preco", "caixa operacional menos investimento total, mediana de 5 anos")):
        if k in le:
            L.append(f"   {rot:<62} {B.pct(le[k])}")
    s = o["sensibilidade"]
    L += ["", "  Sensibilidade da TIR real (linhas: crescimento real do caixa do dono por 10 anos; colunas: preço):",
          "   cresc.   " + "  ".join(B.reais(x).rjust(9) for x in s["precos"])]
    for h, linha in zip(s["h"], s["tir"]):
        L.append(f"   {B.pct(h, 0, True):>6}   " + "  ".join((B.pct(x) if x is not None else "n/d").rjust(9) for x in linha))
    L += ["", "  Premissas (tipo | nome | valor | fonte):"]
    for i in o["livro"].itens:
        v = i.valor
        if isinstance(v, float):
            v = B.pct(v, 2) if i.unidade.startswith("a.a.") else B.br(v, 2 if abs(v) < 100 else 0)
        elif isinstance(v, (list, tuple)):
            v = ", ".join(B.br(x, 0) if abs(x) > 5 else B.pct(x) for x in v)
        un = "" if i.unidade.startswith("a.a.") else i.unidade
        L.append(f"   [{i.tipo:<8}] {i.nome}: {v} {un} | {i.fonte} {B.data_br(i.data) if i.data else ''}" + (f" ({i.nota})" if i.nota else ""))
    for a in o["livro"].avisos:
        L.append(f"  AVISO: {a}")
    return "\n".join(L)
