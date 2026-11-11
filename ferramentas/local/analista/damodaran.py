#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Preco justo pelo metodo de Aswath Damodaran (NYU Stern), com os parametros que ELE publica:
premio de risco de mercado maduro (implicito no S&P 500, mensal), premio de risco do Brasil
(spread de calote pelo rating, vezes a volatilidade relativa da bolsa), beta do setor sem
divida (media de mercados emergentes) realavancado pela divida da empresa.

Empresa operacional: fluxo de caixa da firma (FCFF) descontado ao custo medio de capital (WACC),
crescimento = taxa de reinvestimento x retorno sobre o capital, 10 anos, e perpetuidade com
crescimento limitado pelo juro sem risco e SEM retorno em excesso (ROIC = WACC).
Banco e seguradora: retorno em excesso sobre o patrimonio (valor = patrimonio + valor presente
de (ROE - custo do capital proprio) x patrimonio).

Tudo em termos REAIS (reais de hoje), para conversar com a TIR real: juro sem risco real =
NTN-B de 10 anos menos o spread de calote do Brasil. O equivalente nominal sai ao lado.
Fonte dos parametros: pages.stern.nyu.edu/~adamodar (baixado, com a data de cada planilha).
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from . import base as B
from . import cvm_integral as C
from . import tir_real as T

PASTA = B.CACHE / "damodaran"
SITE = "https://pages.stern.nyu.edu/~adamodar/pc/"
ARQS = {"pais": "datasets/ctryprem.xlsx", "betas_emerg": "datasets/betaemerg.xls",
        "betas_global": "datasets/betaGlobal.xls", "erp": "implprem/ERPbymonth.xlsx"}
IMPOSTO = 0.34          # aliquota legal brasileira (IRPJ 25% + CSLL 9%), a mesma da planilha dele para o Brasil
ANOS = 10


def _arquivo(chave, dias=30):
    arq = PASTA / Path(ARQS[chave]).name
    if not arq.exists() or B.idade_horas(arq) > dias * 24:
        try:
            dados = B.http(SITE + ARQS[chave], binario=True)
            if len(dados) < 5000:
                raise ValueError("arquivo pequeno demais")
            PASTA.mkdir(parents=True, exist_ok=True)
            arq.write_bytes(dados)
        except Exception as e:
            if not arq.exists():
                raise B.SemDado(f"Damodaran: não consegui baixar {ARQS[chave]} ({str(e)[:60]}) e não há cópia local. "
                                "Sem os parâmetros publicados por ele o preço justo não sai.")
    return arq


def _iso(v):
    if isinstance(v, (dt.datetime, dt.date)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, (int, float)) and v > 30000:          # data serial do Excel
        return (dt.date(1899, 12, 30) + dt.timedelta(days=int(v))).isoformat()
    return str(v or "")[:10]


def _betas(arq):
    import xlrd
    sh = xlrd.open_workbook(str(arq)).sheet_by_name("Industry Averages")
    data, cab, out = _iso(sh.cell_value(0, 1)), None, {}
    for r in range(sh.nrows):
        linha = [sh.cell_value(r, c) for c in range(sh.ncols)]
        if cab is None:
            if str(linha[0]).strip() == "Industry Name":
                cab = {str(x).strip().lower(): i for i, x in enumerate(linha) if str(x).strip()}
            continue
        nome = str(linha[0]).strip()
        col = lambda *ks: next((linha[cab[k]] for k in ks if k in cab and isinstance(linha[cab[k]], (int, float))), None)
        if nome and col("beta") is not None:
            out[nome] = {"n": col("number of firms"), "beta": col("beta"), "de": col("d/e ratio"),
                         "sem_divida": col("unlevered beta"), "sem_divida_sem_caixa": col("unlevered beta corrected for cash")}
    if not out:
        raise B.SemDado(f"Damodaran: {arq.name} mudou de formato (não achei a tabela de setores)")
    return {"data": data, "setores": out}


def parametros(forcar=False):
    """Parametros publicados por Damodaran, com a data de cada um. Cache de 7 dias do resumo."""
    resumo = PASTA / "parametros.json"
    velho = B.ler_json(resumo)
    if velho and not forcar and B.idade_horas(resumo) < 7 * 24:
        return velho
    import warnings
    import openpyxl
    warnings.filterwarnings("ignore")
    out = {"lido_em": dt.date.today().isoformat(), "fonte": "Aswath Damodaran, NYU Stern (pages.stern.nyu.edu/~adamodar)"}
    ws = openpyxl.load_workbook(_arquivo("pais"), read_only=True, data_only=True)["ERPs by country"]
    for row in ws.iter_rows(values_only=True):
        v = [x for x in row if x is not None]
        if not v:
            continue
        if str(v[0]).startswith("Date of update") and len(v) > 1:
            out["pais_data"] = _iso(v[1])
        if str(v[0]).strip() == "Brazil" and len(v) >= 6 and "brasil" not in out:
            nums = [x for x in v[3:] if isinstance(x, (int, float))]
            out["brasil"] = {"rating": str(v[2]), "spread_calote": float(nums[0]), "premio_total": float(nums[1]),
                             "premio_pais": float(nums[2]), "cds": float(nums[3]) if len(nums) > 3 else None,
                             "premio_pais_cds": float(nums[5]) if len(nums) > 5 else None}
    if "brasil" not in out:
        raise B.SemDado("Damodaran: ctryprem.xlsx mudou de formato (não achei a linha do Brasil)")
    out["brasil"]["premio_maduro_na_planilha"] = out["brasil"]["premio_total"] - out["brasil"]["premio_pais"]
    ws = openpyxl.load_workbook(_arquivo("erp"), read_only=True, data_only=True)["Historical ERP"]
    cab, ult = None, None
    for row in ws.iter_rows(values_only=True):
        if cab is None:
            cab = [str(x or "").strip().lower() for x in row]
            continue
        if isinstance(row[0], (dt.datetime, dt.date)):
            ult = row
    if not ult:
        raise B.SemDado("Damodaran: ERPbymonth.xlsx sem linha mensal")
    def col(prefixo):
        i = next((i for i, c in enumerate(cab) if c.startswith(prefixo)), None)
        return float(ult[i]) if (i is not None and isinstance(ult[i], (int, float))) else None
    out["premio_maduro"] = col("erp (t12 m with sust") or col("erp (t12m)") or out["brasil"]["premio_maduro_na_planilha"]
    out["premio_maduro_data"] = _iso(ult[0])
    out["juro_eua_10a"], out["juro_eua_sem_risco"] = col("t.bond rate"), col("$ riskfree rate")
    out["betas_emergentes"] = _betas(_arquivo("betas_emerg"))
    out["betas_globais"] = _betas(_arquivo("betas_global"))
    B.gravar_json(resumo, out)
    return out


def beta_setor(par, industria):
    for chave, rot in (("betas_emergentes", "mercados emergentes"), ("betas_globais", "global")):
        b = par[chave]["setores"].get(industria)
        if b and b.get("sem_divida_sem_caixa"):
            return dict(b, base=rot, data=par[chave]["data"], industria=industria)
    b = par["betas_emergentes"]["setores"].get("Total Market (without financials)")
    if not b:
        raise B.SemDado(f"Damodaran: sem beta para '{industria}'")
    return dict(b, base="mercados emergentes, mercado inteiro (setor não encontrado)", data=par["betas_emergentes"]["data"],
                industria="Total Market (without financials)")


def custo_capital(par, mac, industria, d_sobre_e, livro=None, financeira=False):
    """Custo do capital proprio REAL: juro sem risco real + beta x (premio maduro + premio do Brasil)."""
    br = par["brasil"]
    rf = mac["ntnb_10a"] - br["spread_calote"]
    premio = par["premio_maduro"] + br["premio_pais"]
    b = beta_setor(par, industria)
    beta = b["beta"] if financeira else b["sem_divida_sem_caixa"] * (1.0 + (1.0 - IMPOSTO) * d_sobre_e)
    ke = rf + beta * premio
    pi = mac["ipca_longo"]
    if livro is not None:
        p, D = livro.p, f"Damodaran, {par['pais_data']}"
        p("Juro sem risco real", rf, "a.a. real", f"NTN-B de 10 anos ({B.pct(mac['ntnb_10a'], 2)}, ANBIMA) menos o spread de calote do Brasil "
          f"({B.pct(br['spread_calote'], 2)}, rating {br['rating']}, {D})", mac["ntnb_data"], B.MERCADO)
        p("Prêmio de risco de mercado maduro", par["premio_maduro"], "a.a.", "Damodaran, prêmio implícito no S&P 500 (ERPbymonth)", par["premio_maduro_data"], B.MERCADO)
        p("Prêmio de risco do Brasil", br["premio_pais"], "a.a.", f"{D}: spread de calote x volatilidade relativa da bolsa", par["pais_data"], B.MERCADO,
          f"pelo CDS seria {B.pct(br['premio_pais_cds'], 2)}" if br.get("premio_pais_cds") else "")
        if financeira:
            p("Beta do setor (com a alavancagem do setor)", beta, "x", f"Damodaran, {b['industria']}, {b['base']}, {b['n']:.0f} empresas", b["data"], B.MERCADO,
              "banco não se desalavanca: a dívida é a matéria-prima")
        else:
            p("Beta do setor sem dívida e sem caixa", b["sem_divida_sem_caixa"], "x", f"Damodaran, {b['industria']}, {b['base']}, {b['n']:.0f} empresas", b["data"], B.MERCADO)
            p("Beta realavancado", beta, "x", f"beta sem dívida x (1 + (1 - 34%) x divida/valor de mercado de {B.br(d_sobre_e, 2)})", "", B.OFICIAL)
        p("Custo do capital próprio (Ke) real", ke, "a.a. real", "juro sem risco real + beta x (prêmio maduro + prêmio do Brasil)", "", B.MERCADO,
          f"em reais nominais, com a inflação longa do Focus ({B.pct(pi, 2)}): {B.pct(B.nominal(ke, pi))}")
    return {"rf_real": rf, "premio": premio, "beta": beta, "beta_setor": b, "ke_real": ke, "ke_nominal": B.nominal(ke, pi), "inflacao": pi}


def _pib_longo(mac):
    f = (mac.get("focus") or {}).get("PIB Total") or {}
    anos = [a for a, v in f.items() if v.get("mediana") is not None]
    return (f[max(anos)]["mediana"] / 100.0, max(anos)) if anos else (None, None)


def _projetar(ebit0, imposto0, g1, roic0, wacc, g_est):
    """FCFF real por 10 anos + valor terminal. Devolve (linhas, valor terminal no ano 10)."""
    linhas, ebit = [], ebit0
    for t in range(1, ANOS + 1):
        peso = 0.0 if t <= 5 else (t - 5) / 5.0                 # anos 6 a 10: converge para a fase estavel
        g = g1 + (g_est - g1) * peso
        roic = roic0 + (wacc - roic0) * peso
        imp = imposto0 + (IMPOSTO - imposto0) * t / float(ANOS)
        ebit *= 1.0 + g
        nopat = ebit * (1.0 - imp)
        reinv = nopat * (g / roic) if (roic > 0 and g > 0) else 0.0
        linhas.append({"t": t, "g": g, "roic": roic, "imposto": imp, "ebit": ebit, "nopat": nopat, "reinvestimento": reinv, "fcff": nopat - reinv})
    nopat_t = ebit * (1.0 + g_est) * (1.0 - IMPOSTO)
    terminal = nopat_t * (1.0 - g_est / wacc) / (wacc - g_est)
    return linhas, terminal


def _valor_firma(linhas, terminal, wacc):
    return sum(l["fcff"] / (1.0 + wacc) ** l["t"] for l in linhas) + terminal / (1.0 + wacc) ** ANOS


def calcular(ticker, ins=None, industria="Total Market (without financials)", preco=None):
    """Preco justo de empresa operacional (FCFF). ins: insumos da TIR real (mesmo balanco, mesmo preco)."""
    ins = ins or T.insumos(ticker, preco=preco)
    par, mac, pv = parametros(), ins["mac"], ins["pv"]
    livro = B.Livro()
    p = livro.p
    vm, db, caixa = pv["valor_mercado"], ins["divida_bruta"], ins["caixa"] or 0.0
    cc = custo_capital(par, mac, industria, db / vm, livro)
    pi = cc["inflacao"]
    kd_real = max(ins["custo_real"], mac["ntnb_10a"])
    kd_pos = B.real(B.nominal(kd_real, pi) * (1.0 - IMPOSTO), pi)
    we = vm / (vm + db)
    wacc = we * cc["ke_real"] + (1.0 - we) * kd_pos
    p("Custo real da dívida antes do imposto", kd_real, "a.a. real", "o maior entre o custo medido no balanço e a NTN-B de 10 anos "
      "(a dívida é rolada a mercado)", ins["ltm_ate"], B.MESA, f"depois do imposto (juro nominal dedutível a 34%): {B.pct(kd_pos)} real")
    p("Peso do capital próprio", we, "do capital", "valor de mercado / (valor de mercado + dívida bruta contábil)", pv["data"], B.MERCADO)
    p("Custo médio de capital (WACC) real", wacc, "a.a. real", "média ponderada do Ke e do custo da dívida depois do imposto", "", B.MERCADO,
      f"nominal: {B.pct(B.nominal(wacc, pi))}")
    ltm = ins["tab"]["ltm"]
    ebit0 = ins["ebitda0"] - ins["da0"]
    if ebit0 <= 0:
        raise B.SemDado(f"{ticker}: lucro operacional (EBIT) negativo nos 12 meses; o FCFF de Damodaran precisa de margem normalizada, que é premissa")
    ef, ef_fonte = IMPOSTO, "sem lucro antes do imposto positivo: alíquota legal"
    if ltm.get("lair") and ltm["lair"] > 0:
        if ltm.get("ir") is not None:
            ef, ef_fonte = min(IMPOSTO, max(0.0, -ltm["ir"] / ltm["lair"])), "CVM: imposto de renda e contribuição social da DRE / lucro antes do imposto, 12 meses"
        elif ltm.get("ir_pago") is not None:
            ef, ef_fonte = min(IMPOSTO, max(0.0, ltm["ir_pago"] / ltm["lair"])), "CVM: imposto pago em caixa / lucro antes do imposto, 12 meses"
    capital = (ltm.get("divida_liquida") or 0.0) + (ltm.get("pl") or 0.0)
    if capital <= 0:
        raise B.SemDado(f"{ticker}: capital investido contábil não positivo; sem retorno sobre o capital não há como ligar crescimento a reinvestimento")
    capital *= ins["f_ltm"]
    nopat0 = ebit0 * (1.0 - ef)
    roic0 = nopat0 / capital
    capex = ins["capex5_real"] or ins["da0"]
    rr0 = min(1.0, max(0.0, (capex - ins["da0"]) / nopat0))
    g1 = min(0.10, rr0 * roic0)
    pib, pib_ano = _pib_longo(mac)
    g_est = min(cc["rf_real"], pib) if pib is not None else min(cc["rf_real"], 0.02)
    p("Lucro operacional (EBIT) de partida", ebit0, "R$ mi de hoje", "CVM: EBITDA dos 12 meses menos depreciação", ins["ltm_ate"], B.OFICIAL)
    p("Imposto efetivo sobre o lucro, hoje", ef, "do lucro", ef_fonte, ins["ltm_ate"], B.OFICIAL,
      "sobe em linha reta até a alíquota legal de 34% no ano 10 (regra de Damodaran)")
    p("Retorno sobre o capital investido (ROIC)", roic0, "a.a.", "CVM: EBIT depois do imposto efetivo / (dívida líquida + patrimônio)", ins["ltm_ate"], B.OFICIAL,
      "capital a custo histórico: em ativo antigo o ROIC real é menor que este")
    p("Taxa de reinvestimento", rr0, "do lucro operacional", "CVM: (investimento mediano de 5 anos - depreciação) / EBIT depois do imposto", ins["ltm_ate"], B.OFICIAL,
      "sem a variação do capital de giro")
    p("Crescimento real dos anos 1 a 5", g1, "a.a.", "regra de Damodaran: taxa de reinvestimento x ROIC (teto de 10%)", "", B.OFICIAL)
    p("Crescimento real na fase estável", g_est, "a.a.", "o menor entre o juro sem risco real e o PIB longo do Focus" +
      (f" ({B.pct(pib)} em {pib_ano})" if pib is not None else " (sem PIB no Focus: teto de 2%)"), mac["focus_data"], B.MESA if pib is None else B.CONSENSO)
    p("Retorno sobre o capital na fase estável = WACC", wacc, "a.a.", "regra de Damodaran: sem vantagem duradoura, o retorno em excesso some", "", B.MESA)
    linhas, terminal = _projetar(ebit0, ef, g1, roic0, wacc, g_est)
    ev = _valor_firma(linhas, terminal, wacc)
    fm = ins.get("fracao_minoritarios") or 0.0
    dl = db - caixa
    acion = (ev - dl) * (1.0 - fm)
    por_acao = pv["preco"] / vm
    justo = acion * por_acao

    def preco_com(w=wacc, fator=1.0, excesso=0.0):
        """Preco justo com outro WACC, outro lucro operacional de partida (fator) ou retorno em excesso perene."""
        ls, tv = _projetar(ebit0 * fator, ef, g1, roic0 * fator, w, g_est)
        if excesso:
            nop = ls[-1]["ebit"] * (1.0 + g_est) * (1.0 - IMPOSTO)
            tv = nop * (1.0 - g_est / (w + excesso)) / (w - g_est)
        return ((_valor_firma(ls, tv, w) - dl) * (1.0 - fm)) * por_acao

    ws, fs = (wacc - 0.01, wacc, wacc + 0.01), (0.85, 1.0, 1.15, 1.30)
    sens = {"wacc": ws, "fator_ebit": fs, "preco": [[preco_com(w, f) if w - g_est > 0.005 else None for w in ws] for f in fs]}
    fator_impl = T._raiz(lambda f: preco_com(wacc, f) - pv["preco"], 0.3, 4.0)
    wacc_impl = T._raiz(lambda w: preco_com(w) - pv["preco"], g_est + 0.006, 0.30)
    if acion <= 0:
        livro.aviso("O valor da firma calculado não cobre a dívida líquida: preço justo negativo. Com esta alavancagem, pequenas "
                    "mudanças de premissa mudam tudo; leia a sensibilidade.")
    elif ev and dl / ev > 0.6:
        livro.aviso(f"Dívida líquida é {B.pct(dl / ev, 0)} do valor da firma: 1 ponto de WACC muda o preço justo de "
                    f"{B.reais(sens['preco'][1][0])} para {B.reais(sens['preco'][1][2])}. Leia a faixa, não o ponto.")
    if ins["da0"] < 0.05 * ins["ebitda0"]:
        livro.aviso("Depreciação quase nula frente ao EBITDA: o resultado societário reconhece ativo de contrato (transmissão e "
                    "concessões), que não é caixa, e a concessão tem prazo. A perpetuidade do FCFF superestima; a régua certa "
                    "aqui é a TIR real com o fim da concessão (caso da mesa).")
    if roic0 < wacc:
        livro.aviso(f"Retorno sobre o capital medido ({B.pct(roic0)}) abaixo do custo de capital ({B.pct(wacc)}): pelo método, crescer "
                    "destrói valor. O capital está a custo histórico e o imposto efetivo pode mudar; confira a base de remuneração "
                    "regulatória antes de concluir.")
    return {"ticker": ins["ticker"], "tipo": "fcff", "preco": pv["preco"], "data_preco": pv["data"], "preco_justo": justo,
            "potencial": justo / pv["preco"] - 1.0, "valor_firma": ev, "valor_acionista": acion, "divida_liquida": dl,
            "terminal_peso": (terminal / (1.0 + wacc) ** ANOS) / ev if ev else None, "wacc": wacc, "custo": cc, "kd_real": kd_real,
            "g1": g1, "g_estavel": g_est, "roic": roic0, "reinvestimento": rr0, "imposto_efetivo": ef, "ebit0": ebit0,
            "ebit_implicito": (ebit0 * fator_impl) if fator_impl else None, "fator_implicito": fator_impl, "wacc_implicito": wacc_impl,
            "linhas": linhas, "sensibilidade": sens, "livro": livro, "parametros": par, "preco_com": preco_com}


# ------------------------------------------------------------------ bancos e seguradoras
_RX_PL = re.compile(r"^patrim[oô]nio l[ií]quido( consolidado)?$", re.I)
_RX_MIN = re.compile(r"n[aã]o controlador", re.I)


def _pl_financeira(bpp):
    """(patrimonio total, parcela dos nao controladores) no plano de contas de instituicao financeira."""
    cands = [(c, v) for c, (ds, v) in bpp.items() if _RX_PL.search(ds.strip()) and c.count(".") <= 1 and v]
    if not cands:
        return None, 0.0
    cd, pl = sorted(cands, key=lambda x: x[0].count("."))[0]
    mino = sum(v for c, (ds, v) in bpp.items() if c.startswith(cd + ".") and c.count(".") == cd.count(".") + 1 and _RX_MIN.search(ds))
    return pl, mino


def calcular_financeira(ticker, industria="Bank (Money Center)", preco=None, excesso_perene=0.0):
    """Retorno em excesso sobre o patrimonio (Damodaran), em reais nominais.
    excesso_perene: fracao do excesso de ROE de hoje que sobrevive na perpetuidade (padrao 0)."""
    from . import macro as MAC
    d = B.ativo(ticker)
    cvm = d.get("cvm_demonstracoes") or {}
    if not cvm.get("cd_cvm"):
        raise B.SemDado(f"{ticker}: sem código CVM")
    integral = C.carregar(cvm["cd_cvm"])
    tab, mac, par = C.tabela(integral), MAC.carregar(), parametros()
    livro = B.Livro()
    p = livro.p
    pv = B.preco_e_valor(d, integral, livro, preco)
    hist = []
    for fim in sorted(integral["anual"]):
        pl, mino = _pl_financeira(integral["anual"][fim].get("BPP") or {})
        o = tab["anos"][fim]
        if pl and o.get("lucro_controladores") is not None:
            hist.append({"fim": fim, "pl": pl - mino, "lucro": o["lucro_controladores"], "dividendos": o.get("dividendos_pagos")})
    it = integral.get("itr") or {}
    pl_hoje, mino = _pl_financeira((it.get("atual") or {}).get("BPP") or {}) if it.get("data", "") > (hist[-1]["fim"] if hist else "") else (None, 0.0)
    pl0 = (pl_hoje - mino) if pl_hoje else (hist[-1]["pl"] if hist else None)
    lucro = tab["ltm"].get("lucro_controladores")
    if not pl0 or lucro is None or len(hist) < 2:
        raise B.SemDado(f"{ticker}: não achei patrimônio líquido e lucro no plano de contas financeiro da CVM")
    pl_medio = (pl0 + hist[-2 if pl_hoje is None else -1]["pl"]) / 2.0
    roe0 = lucro / pl_medio
    roes = [h["lucro"] / ((h["pl"] + a["pl"]) / 2.0) for a, h in zip(hist, hist[1:]) if (h["pl"] + a["pl"]) > 0]
    pays = [h["dividendos"] / h["lucro"] for h in hist[-5:] if h.get("dividendos") and h["lucro"] > 0]
    if not pays:
        raise B.SemDado(f"{ticker}: sem dividendos pagos no fluxo de caixa da CVM para medir o payout")
    payout0 = min(1.0, B.mediana(pays))
    cc = custo_capital(par, mac, industria, 0.0, livro, financeira=True)
    ke, pi = cc["ke_nominal"], cc["inflacao"]
    pib, _ = _pib_longo(mac)
    g_est = B.nominal(min(cc["rf_real"], pib) if pib is not None else min(cc["rf_real"], 0.02), pi)
    roe_est = ke + excesso_perene * (roe0 - ke)
    p("Patrimônio líquido dos controladores", pl0, "R$ mi", "CVM, balanço mais recente", tab["saldos_em"], B.OFICIAL)
    p("ROE dos últimos 12 meses", roe0, "a.a.", f"CVM: lucro dos controladores {B.mi(lucro)} / patrimônio médio", tab["ltm_ate"], B.OFICIAL,
      "mediana de 5 anos: " + (B.pct(B.mediana(roes[-5:])) if roes else "n/d"))
    p("Payout", payout0, "do lucro", "CVM: dividendos e JCP pagos / lucro, mediana de 5 anos", tab["ltm_ate"], B.OFICIAL)
    p("ROE na fase estável", roe_est, "a.a.", "regra de Damodaran: converge para o custo do capital em 10 anos" +
      (f", mantendo {B.pct(excesso_perene, 0)} da diferença de hoje" if excesso_perene else " (sem retorno em excesso perene)"), "", B.MESA)
    p("Crescimento nominal na fase estável", g_est, "a.a.", "o menor entre juro sem risco real e PIB longo do Focus, mais a inflação longa", mac["focus_data"], B.CONSENSO)
    por_acao = pv["preco"] / pv["valor_mercado"]

    def valor(k=ke, fracao=excesso_perene, detalhe=False):
        r_est = k + fracao * (roe0 - k)
        b, v, ls = pl0, 0.0, []
        pe = max(0.0, 1.0 - g_est / r_est) if r_est > 0 else 0.0
        for t in range(1, ANOS + 1):
            w = t / float(ANOS)
            r = roe0 + (r_est - roe0) * w
            pay = payout0 + (pe - payout0) * w
            v += (r - k) * b / (1.0 + k) ** t
            ls.append({"t": t, "roe": r, "payout": pay, "patrimonio": b, "lucro": r * b, "excesso": (r - k) * b})
            b += r * b * (1.0 - pay)
        tv = (r_est - k) * b / (k - g_est) if k > g_est else 0.0
        tot = pl0 + v + tv / (1.0 + k) ** ANOS
        return (tot, ls) if detalhe else tot

    total, linhas = valor(detalhe=True)
    justo = total * por_acao
    ks, ss = (ke - 0.01, ke, ke + 0.01), (0.0, 0.5, 1.0)
    fr = T._raiz(lambda x: valor(ke, x) * por_acao - pv["preco"], -2.0, 3.0)
    if roe0 < ke:
        livro.aviso(f"ROE de 12 meses ({B.pct(roe0)}) abaixo do custo do capital ({B.pct(ke)}): o preço justo supõe que o retorno volta "
                    "ao custo do capital em 10 anos. Se não voltar, vale a linha de 100% da sensibilidade.")
    return {"ticker": ticker.upper(), "tipo": "excesso", "preco": pv["preco"], "data_preco": pv["data"], "preco_justo": justo,
            "potencial": justo / pv["preco"] - 1.0, "valor_acionista": total, "patrimonio": pl0, "p_vp": pv["valor_mercado"] / pl0,
            "p_vp_justo": total / pl0, "roe": roe0, "roe_5a": B.mediana(roes[-5:]) if roes else None, "payout": payout0, "custo": cc,
            "g_estavel": g_est, "linhas": linhas, "fracao_implicita": fr, "roe_implicito": (ke + fr * (roe0 - ke)) if fr is not None else None,
            "sensibilidade": {"ke": ks, "fracao": ss, "preco": [[valor(k, x) * por_acao for k in ks] for x in ss]},
            "livro": livro, "parametros": par, "preco_com": lambda k=ke, fracao=excesso_perene: valor(k, fracao) * por_acao}


def texto(o):
    cc = o["custo"]
    L = [f"PREÇO JUSTO (método de Damodaran)  {o['ticker']}  preço {B.reais(o['preco'])} ({B.data_br(o['data_preco'])})",
         f"  Preço justo: {B.reais(o['preco_justo'])}  ({B.pct(o['potencial'], 0, True)} sobre o preço de tela)",
         f"  Custo do capital próprio: {B.pct(cc['ke_real'])} real = {B.pct(cc['ke_nominal'])} nominal   (juro sem risco real "
         f"{B.pct(cc['rf_real'], 2)} + beta {B.br(cc['beta'], 2)} x prêmio {B.pct(cc['premio'], 2)})"]
    if o["tipo"] == "fcff":
        L += [f"  WACC real {B.pct(o['wacc'])} | ROIC {B.pct(o['roic'])} | reinvestimento {B.pct(o['reinvestimento'], 0)} do lucro operacional | "
              f"crescimento real {B.pct(o['g1'])} (anos 1 a 5) -> {B.pct(o['g_estavel'])} (estável)",
              f"  Valor da firma {B.mi(o['valor_firma'])} - dívida líquida {B.mi(o['divida_liquida'])} = acionista {B.mi(o['valor_acionista'])}"
              f"  | valor terminal = {B.pct(o['terminal_peso'], 0)} do valor da firma",
              "  O preço de tela embute: lucro operacional de " + (f"{B.mi(o['ebit_implicito'])} ({B.pct(o['fator_implicito'] - 1, 0, True)} sobre os 12 meses)"
                                                                   if o["fator_implicito"] else "n/d") +
              " ou retorno da firma de " + (B.pct(o["wacc_implicito"]) + " real" if o["wacc_implicito"] else "n/d"),
              "  Sensibilidade do preço justo (linhas: lucro operacional de partida; colunas: WACC real):",
              "            " + "  ".join(B.pct(w).rjust(9) for w in o["sensibilidade"]["wacc"])]
        for f, linha in zip(o["sensibilidade"]["fator_ebit"], o["sensibilidade"]["preco"]):
            L.append(f"   {B.pct(f - 1, 0, True):>7}  " + "  ".join((B.reais(x) if x is not None else "n/d").rjust(9) for x in linha))
    else:
        L += [f"  ROE 12 meses {B.pct(o['roe'])} | payout {B.pct(o['payout'], 0)} | P/VP de tela {B.br(o['p_vp'], 2)}x | P/VP justo {B.br(o['p_vp_justo'], 2)}x",
              "  O preço de tela embute ROE de " + (B.pct(o["roe_implicito"]) if o["roe_implicito"] is not None else "n/d") + " para sempre "
              f"(hoje {B.pct(o['roe'])}; custo do capital {B.pct(o['custo']['ke_nominal'])})",
              "  Sensibilidade do preço justo (linhas: quanto da diferença entre ROE e Ke dura para sempre; colunas: Ke nominal):",
              "            " + "  ".join(B.pct(k).rjust(9) for k in o["sensibilidade"]["ke"])]
        for x, linha in zip(o["sensibilidade"]["fracao"], o["sensibilidade"]["preco"]):
            L.append(f"   {B.pct(x, 0):>7}  " + "  ".join(B.reais(v).rjust(9) for v in linha))
    L.append("  Premissas (tipo | nome | valor | fonte):")
    for i in o["livro"].itens:
        v = i.valor
        if isinstance(v, float):
            v = B.pct(v, 2) if (i.unidade.startswith(("a.a.", "do "))) else B.br(v, 2 if abs(v) < 100 else 0)
        L.append(f"   [{i.tipo:<8}] {i.nome}: {v} {'' if i.unidade.startswith(('a.a.', 'do ')) else i.unidade} | {i.fonte} "
                 f"{B.data_br(i.data) if i.data else ''}" + (f" ({i.nota})" if i.nota else ""))
    L += [f"  AVISO: {a}" for a in o["livro"].avisos]
    return "\n".join(L)
