#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Balancos integrais da CVM (dados abertos): TODAS as linhas de DRE, balanco, fluxo de
caixa e valor adicionado, de ate 12 exercicios (DFP) mais o acumulado do ano (ITR), e o
numero de acoes do capital. O coletor da mesa guarda 26 contas e 3 anos; valuation pede
depreciacao, investimento, dividendos pagos, juros pagos e historia longa.

Tudo em R$ milhoes. Nada e estimado: conta que a empresa nao publica fica None, com aviso.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
import zipfile

from . import base as B

URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{T}/DADOS/{t}_cia_aberta_{ano}.zip"
DEMS = ("DRE", "BPA", "BPP", "DFC_MI", "DFC_MD", "DVA")
VERSAO_CACHE = 5


def _zip(tipo, ano):
    """Caminho do zip no cache (baixa quando falta; ano corrente e anterior renovam a cada 20 h)."""
    arq = B.CACHE / "cvm_zip" / f"{tipo}_{ano}.zip"
    recente = ano >= dt.date.today().year - 1
    if arq.exists() and (not recente or B.idade_horas(arq) < 20):
        return arq
    try:
        dados = B.http(URL.format(T=tipo.upper(), t=tipo.lower(), ano=ano), timeout=240, binario=True)
    except B.SemDado:
        return arq if arq.exists() else None
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_bytes(dados)
    return arq


def _linhas(z, nome, cds, inicio=False):
    """Linhas (dict) do CSV `nome` que pertencem a companhia (filtro textual antes do csv).
    inicio=True casa pelo comeco da linha (CNPJ, nos arquivos sem o codigo CVM)."""
    try:
        txt = z.read(nome).decode("latin-1")
    except KeyError:
        return []
    cab, _, corpo = txt.partition("\n")
    if inicio:
        marcas = tuple(f"{c};" for c in cds)
        sel = [l for l in corpo.split("\n") if l.startswith(marcas)]
    else:
        marcas = [f";{c};" for c in cds]
        sel = [l for l in corpo.split("\n") if any(m in l for m in marcas)]
    if not sel:
        return []
    return list(csv.DictReader(io.StringIO(cab + "\n" + "\n".join(sel)), delimiter=";"))


def _valor(r):
    try:
        v = float(r["VL_CONTA"])
    except (KeyError, ValueError):
        return None
    esc = (r.get("ESCALA_MOEDA") or "").upper()
    if r["CD_CONTA"].startswith("3.99"):
        return v                      # lucro por acao: reais por acao, sem escala
    return v / 1000.0 if esc.startswith("MIL") else v / 1e6


def _ler_zip(arq, tipo, ano, cds):
    """{dem: {(ordem, ini, fim): {cd: [ds, valor]}}} + documentos + capital, de um zip."""
    out = {"dems": {}, "docs": [], "capital": []}
    cnpjs = set()
    if not arq:
        return out
    with zipfile.ZipFile(arq) as z:
        nomes = z.namelist()
        pref = f"{tipo}_cia_aberta_"
        for dem in DEMS:
            linhas = []
            for escopo in ("con", "ind"):
                linhas = _linhas(z, f"{pref}{dem}_{escopo}_{ano}.csv", cds)
                if linhas:
                    break
            if not linhas:
                continue
            cnpjs.add(linhas[0]["CNPJ_CIA"])
            ult = {}
            for r in linhas:                          # ultima versao de cada data de referencia
                k = r["DT_REFER"]
                ult[k] = max(ult.get(k, 0), int(r.get("VERSAO") or 0))
            blocos = out["dems"].setdefault(dem, {})
            for r in linhas:
                if int(r.get("VERSAO") or 0) != ult[r["DT_REFER"]]:
                    continue
                ordem = "U" if (r.get("ORDEM_EXERC") or "").upper().startswith(("Ú", "U")) else "P"
                chave = f"{ordem}|{r.get('DT_INI_EXERC') or ''}|{r['DT_FIM_EXERC']}|{escopo}"
                v = _valor(r)
                if v is not None:
                    blocos.setdefault(chave, {})[r["CD_CONTA"]] = [r["DS_CONTA"].strip(), v]
        for r in _linhas(z, f"{pref}{ano}.csv", cds):
            out["docs"].append({"data": r["DT_REFER"], "versao": int(r.get("VERSAO") or 0),
                                "recebido": r.get("DT_RECEB"), "link": r.get("LINK_DOC")})
        cap = [n for n in nomes if "composicao_capital" in n]
        for r in (_linhas(z, cap[0], cnpjs, inicio=True) if (cap and cnpjs) else []):
            try:
                tot = float(r.get("QT_ACAO_TOTAL_CAP_INTEGR") or 0)
                tes = float(r.get("QT_ACAO_TOTAL_TESOURO") or 0)
            except ValueError:
                continue
            if tot > 0:
                out["capital"].append({"data": r["DT_REFER"], "versao": int(r.get("VERSAO") or 0),
                                       "total": tot, "tesouraria": tes,
                                       "on": float(r.get("QT_ACAO_ORDIN_CAP_INTEGR") or 0),
                                       "pn": float(r.get("QT_ACAO_PREF_CAP_INTEGR") or 0)})
    return out


# ------------------------------------------------------------------ contas padronizadas
RX = {
    "capex": re.compile(r"imobiliz|intang|ativos? (de|do) contrato|ativos? contratua|infraestrutura|"
                        r"concess|ativo financeiro (da concess|indeniz)|adi[cç][oõ]es? (ao|a|em)|obras em andamento", re.I),
    "capex_fora": re.compile(r"venda|aliena|recebimento|resgate|baixa|redu[cç][aã]o de capital|dividend|aplica[cç]", re.I),
    "div": re.compile(r"dividend|juros sobre (o )?capital|\bjcp\b|jscp|proventos pagos", re.I),
    "juros": re.compile(r"(juros|encargos)[^;]{0,70}(pagos?|liquidados?)\b|pagamentos?[^;]{0,70}\b(juros|encargos)\b|"
                        r"(amortiza[cç][aã]o|liquida[cç][aã]o) (de|dos) (juros|encargos)", re.I),
    # dividendo e JCP nao sao juros; linha que mistura principal e juros nao serve (nao da para separar)
    "juros_fora": re.compile(r"dividend|capital pr[oó]prio|\bjcp\b|jscp|principal|recebiment", re.I),
    "ir_pago": re.compile(r"(imposto de renda|irpj|ir e (cs|contribui)).*pag|pagamento.*(imposto de renda|irpj)", re.I),
    "recompra": re.compile(r"recompra|a[cç][oõ]es em tesouraria|aquisi[cç][aã]o de a[cç][oõ]es pr[oó]prias", re.I),
    "aumento_capital": re.compile(r"aumento de capital|integraliza[cç][aã]o de capital|emiss[aã]o de a[cç][oõ]es|oferta (p[uú]blica )?de a[cç][oõ]es", re.I),
    "da": re.compile(r"deprecia|amortiza|exaust", re.I),
    # encargo da divida por COMPETENCIA (ajuste do lucro no fluxo de caixa indireto): juros mais a
    # correcao monetaria que fica no principal. "Juros pagos" nao mostra a correcao da divida em IPCA.
    "encargos": re.compile(
        r"(encargos|juros)[^;]{0,60}(varia[cç]|monet|cambi)|"
        r"varia[cç](?:[aã]o|[oõ]es) (monet[aá]rias?|cambiais?)[^;]{0,50}(juros|encargos|empr[eé]st|financiam|deb[eê]nt|d[ií]vida)|"
        r"(juros|encargos)[^;]{0,45}\b(de|sobre|dos|das|com) (empr[eé]st|financiam|deb[eê]nt|d[ií]vida)|"
        r"despesas? (de|com) juros|juros (apropriados|incorridos|provisionados|passivos)", re.I),
    "encargos_fora": re.compile(r"aplica[cç]|receita|clientes|dep[oó]sitos? judicia|conting|provis|lit[ií]g|benef[ií]cio|"
                                r"p[oó]s.emprego|atuarial|outorga|uso do bem|recebid|pagos?\b|\bppp\b|parceria|arrendament|"
                                r"\bmora\b|parcelament|tribut|fornecedor", re.I),
    # renda do caixa tirada do caixa operacional (ajuste negativo do lucro) e juros recebidos nele
    "renda_aplic": re.compile(r"rendiment[^;]{0,50}(aplica|t[ií]tulos|financeir|caixa)|"
                              r"(receita|renda|juros|ganho)[^;]{0,40}(aplica[cç][oõ]es financeiras|t[ií]tulos e valores)", re.I),
    "juros_recebidos": re.compile(r"(juros|rendimentos?)[^;]{0,50}recebid|recebimentos?[^;]{0,40}(juros|rendiment)", re.I),
}


def _nivel(cd):
    return cd.count(".") + 1


def _folhas(bloco, prefixo):
    """Contas sob `prefixo` que nao tem filha (evita somar pai e filha)."""
    cds = [c for c in bloco if c.startswith(prefixo + ".")]
    return [c for c in cds if not any(o.startswith(c + ".") for o in cds)]


def _soma(bloco, prefixo, rx, fora=None, sinal=None):
    tot, usados = 0.0, []
    for c in _folhas(bloco, prefixo):
        ds, v = bloco[c]
        if not rx.search(ds) or (fora and fora.search(ds)):
            continue
        if sinal == "-" and v > 0:
            continue
        if sinal == "+" and v < 0:
            continue
        tot += v
        usados.append(f"{c} {ds}")
    return (tot if usados else None), usados


def padronizar(dem):
    """De um exercicio (dict {DRE: bloco, BPA: ..}) para as contas que o valuation usa."""
    dre, bpa, bpp = dem.get("DRE") or {}, dem.get("BPA") or {}, dem.get("BPP") or {}
    dfc = dem.get("DFC_MI") or dem.get("DFC_MD") or {}
    dva = dem.get("DVA") or {}
    g = lambda b, c: (b.get(c) or [None, None])[1]
    o, de_onde = {}, {}
    o["receita"], o["ebit"], o["resultado_financeiro"] = g(dre, "3.01"), g(dre, "3.05"), g(dre, "3.06")
    o["lair"], o["ir"] = g(dre, "3.07"), g(dre, "3.08")
    o["lucro"] = g(dre, "3.11") if g(dre, "3.11") is not None else g(dre, "3.09")
    lc, lm = g(dre, "3.11.01"), g(dre, "3.11.02")
    # ha companhia que deixa a abertura 3.11.01/3.11.02 zerada no DFP: zero nos dois com lucro nao e dado
    em_branco = (lc in (None, 0.0)) and (lm in (None, 0.0)) and bool(o["lucro"])
    o["lucro_controladores"] = o["lucro"] if (lc is None or em_branco) else lc
    rf, dfin = g(dre, "3.06.01"), g(dre, "3.06.02")
    if not rf and not dfin and o["resultado_financeiro"]:
        rf = dfin = None                              # abertura nao preenchida: nao e zero, e ausente
    o["receitas_financeiras"], o["despesas_financeiras"] = rf, dfin
    lpas = [v for c, (ds, v) in sorted(dre.items()) if c.startswith("3.99.01.") and v]
    o["lpa"] = lpas[0] if lpas else None
    o["fco"], o["fci"], o["fcfin"] = g(dfc, "6.01"), g(dfc, "6.02"), g(dfc, "6.03")
    # depreciacao: DVA 7.04.01 e padrao; reserva: ajuste do lucro no fluxo de caixa indireto
    da = g(dva, "7.04.01") if g(dva, "7.04.01") is not None else g(dva, "7.04")
    if da is not None:
        o["da"], de_onde["da"] = abs(da), ["DVA 7.04.01"]
    else:
        v, us = _soma(dfc, "6.01.01", RX["da"])
        o["da"], de_onde["da"] = (abs(v) if v is not None else None), us
    v, us = _soma(dfc, "6.02", RX["capex"], RX["capex_fora"], "-")
    o["capex"], de_onde["capex"] = (abs(v) if v is not None else None), us
    v, us = _soma(dfc, "6.03", RX["div"], None, "-")
    o["dividendos_pagos"], de_onde["dividendos_pagos"] = (abs(v) if v is not None else None), us
    jo, uo = _soma(dfc, "6.01", RX["juros"], RX["juros_fora"], "-")
    jf, uf = _soma(dfc, "6.03", RX["juros"], RX["juros_fora"], "-")
    v, _ = _soma(dfc, "6.01", RX["ir_pago"], None, "-")
    o["ir_pago"] = abs(v) if v is not None else None
    o["juros_pagos_operacional"] = abs(jo) if jo is not None else None
    o["juros_pagos_financiamento"] = abs(jf) if jf is not None else None
    de_onde["juros_pagos"] = uo + uf
    o["juros_no_financiamento"] = any(re.search(r"juros|encargos", ds, re.I) and not RX["div"].search(ds) and v < 0
                                      for c, (ds, v) in dfc.items() if c.startswith("6.03."))
    v, us = _soma(dfc, "6.03", RX["recompra"], None, "-")
    o["recompras"] = abs(v) if v is not None else None
    v, us = _soma(dfc, "6.01.01", RX["encargos"], RX["encargos_fora"], "+")
    o["encargos_divida"], de_onde["encargos_divida"] = v, us
    v, us = _soma(dfc, "6.01.01", RX["renda_aplic"], None, "-")
    o["renda_caixa_ajuste"], de_onde["renda_caixa_ajuste"] = (abs(v) if v is not None else None), us
    v, us = _soma(dfc, "6.01", RX["juros_recebidos"], RX["div"], "+")
    o["juros_recebidos_operacional"], de_onde["juros_recebidos"] = v, us
    o["outras_receitas_op"], o["outras_despesas_op"] = g(dre, "3.04.04"), g(dre, "3.04.05")
    o["equivalencia"], o["ir_corrente"] = g(dre, "3.04.06"), g(dre, "3.08.01")
    v, us = _soma(dfc, "6.03", RX["aumento_capital"], None, "+")
    o["aumento_capital"] = v
    o["caixa"] = (g(bpa, "1.01.01") or 0.0) + (g(bpa, "1.01.02") or 0.0) if bpa else None
    o["divida_bruta"] = (g(bpp, "2.01.04") or 0.0) + (g(bpp, "2.02.01") or 0.0) if bpp else None
    o["divida_liquida"] = (o["divida_bruta"] - o["caixa"]) if (o["divida_bruta"] is not None and o["caixa"] is not None) else None
    o["pl"], o["minoritarios"] = g(bpp, "2.03"), g(bpp, "2.03.09") or 0.0
    o["pl_controladores"] = (o["pl"] - o["minoritarios"]) if o["pl"] is not None else None
    o["ativo_total"] = g(bpa, "1")
    o["imobilizado_intangivel"] = sum(x for x in (g(bpa, "1.02.03"), g(bpa, "1.02.04")) if x) or None
    o["juros_dva"] = g(dva, "7.08.03.01")
    o["jcp_dva"], o["dividendos_dva"] = g(dva, "7.08.04.01"), g(dva, "7.08.04.02")
    if o["ebit"] is not None and o["da"] is not None:
        o["ebitda"] = o["ebit"] + o["da"]
    o["_de_onde"] = de_onde
    return o


def _cds(cd_cvm):
    n = str(cd_cvm).lstrip("0")
    return {n, n.zfill(6), n.zfill(5)}


def escala_acoes(integral):
    """A CVM publica o numero de acoes sem dizer se esta em unidades ou em milhares (cada companhia
    escolhe). Confere com o lucro por acao da propria DRE: lucro / LPA da o numero de acoes. Se o
    publicado for ~1.000 vezes menor, esta em milhares e e corrigido (com registro)."""
    a = integral.get("acoes")
    if not a or a.get("escala"):
        return integral
    blocos = []
    it = integral.get("itr") or {}
    if (it.get("atual") or {}).get("DRE"):
        blocos.append(it["atual"]["DRE"])
    blocos += [integral["anual"][f].get("DRE") or {} for f in sorted(integral["anual"], reverse=True)[:2]]
    a["escala"], a["escala_fonte"] = 1, "sem lucro por ação para conferir"
    for dre in blocos:
        o = padronizar({"DRE": dre})
        if o.get("lpa") and o.get("lucro_controladores") and o["lucro_controladores"] / o["lpa"] > 0:
            implicito = o["lucro_controladores"] * 1e6 / o["lpa"]
            razao = a["total"] / implicito
            if 0.0004 < razao < 0.0025:
                for k in ("total", "tesouraria", "on", "pn", "total_ex_tesouraria"):
                    a[k] = a[k] * 1000.0
                a["escala"] = 1000
            a["escala_fonte"] = f"lucro / lucro por ação da DRE = {implicito / 1e6:,.0f} milhões de ações".replace(",", ".")
            break
    return integral


def carregar(cd_cvm, anos=11, forcar=False):
    """Demonstracoes integrais da companhia. Cache por companhia (20 h)."""
    arq = B.CACHE / "integral" / f"{str(cd_cvm).lstrip('0')}.json"
    velho = B.ler_json(arq)
    if velho and not forcar and velho.get("versao") == VERSAO_CACHE and B.idade_horas(arq) < 20 and velho.get("anos") >= anos:
        return escala_acoes(velho)
    cds = _cds(cd_cvm)
    hoje = dt.date.today()
    out = {"versao": VERSAO_CACHE, "cd_cvm": str(cd_cvm), "anos": anos, "gerado": dt.datetime.now().isoformat(timespec="seconds"),
           "anual": {}, "anual_escopo": {}, "docs": [], "avisos": [], "acoes": None}
    capital = []
    for ano in range(hoje.year - anos, hoje.year + 1):
        z = _ler_zip(_zip("dfp", ano), "dfp", ano, cds)
        capital += z["capital"]
        out["docs"] += [dict(x, tipo="DFP") for x in z["docs"]]
        dem_ano, escopo = {}, ""
        for dem, blocos in z["dems"].items():
            # exercicio corrente: ordem U; quando ha varios (nao deve), o de maior data final
            ch = sorted((k for k in blocos if k.startswith("U|")), key=lambda k: k.split("|")[2])
            if ch:
                dem_ano[dem] = blocos[ch[-1]]
                fim, escopo = ch[-1].split("|")[2], ch[-1].split("|")[3]
        if dem_ano:
            out["anual"][fim] = dem_ano
            out["anual_escopo"][fim] = escopo
    # ITR do ano corrente (e do anterior se o corrente ainda nao tem nada): acumulado e balanco
    itr = None
    for ano in (hoje.year, hoje.year - 1):
        z = _ler_zip(_zip("itr", ano), "itr", ano, cds)
        capital += z["capital"]
        out["docs"] += [dict(x, tipo="ITR") for x in z["docs"]]
        if z["dems"] and itr is None:
            itr = z["dems"]
    out["itr"] = _acumulados(itr) if itr else None
    if capital:
        c = sorted(capital, key=lambda x: (x["data"], x["versao"]))[-1]
        out["acoes"] = dict(c, total_ex_tesouraria=c["total"] - c["tesouraria"])
    if not out["anual"]:
        raise B.SemDado(f"CVM sem DFP para o código {cd_cvm} (companhia nova, estrangeira ou código errado)")
    out["docs"].sort(key=lambda x: (x["data"], x["versao"]))
    B.gravar_json(arq, out)
    return escala_acoes(out)


def _acumulados(dems):
    """Do ITR mais novo: acumulado do ano (U), o mesmo acumulado um ano antes (P) e o balanco."""
    out = {"atual": {}, "anterior": {}, "data": None}
    fim = max(k.split("|")[2] for b in dems.values() for k in b if k.startswith("U|"))
    out["data"] = fim
    for dem, blocos in dems.items():
        if dem in ("BPA", "BPP"):
            ch = [k for k in blocos if k.startswith("U|") and k.split("|")[2] == fim]
            if ch:
                out["atual"][dem] = blocos[ch[0]]
            continue
        us = [k for k in blocos if k.startswith("U|") and k.split("|")[2] == fim]
        if us:                                    # acumulado = menor data inicial
            out["atual"][dem] = blocos[min(us, key=lambda k: k.split("|")[1])]
        ps = [k for k in blocos if k.startswith("P|")]
        if ps:
            fim_p = max(k.split("|")[2] for k in ps)
            ps = [k for k in ps if k.split("|")[2] == fim_p]
            out["anterior"][dem] = blocos[min(ps, key=lambda k: k.split("|")[1])]
            out["data_anterior"] = fim_p
    return out


FLUXOS = ("receita", "ebit", "resultado_financeiro", "lair", "ir", "lucro", "lucro_controladores", "fco", "fci",
          "fcfin", "da", "capex", "dividendos_pagos", "juros_pagos_operacional", "juros_pagos_financiamento",
          "recompras", "aumento_capital", "ebitda", "receitas_financeiras", "despesas_financeiras", "juros_dva",
          "encargos_divida", "outras_receitas_op", "outras_despesas_op", "equivalencia", "ir_corrente", "ir_pago",
          "renda_caixa_ajuste", "juros_recebidos_operacional")
SALDOS = ("caixa", "divida_bruta", "divida_liquida", "pl", "minoritarios", "pl_controladores", "ativo_total",
          "imobilizado_intangivel")


def tabela(integral):
    """Serie anual padronizada + ultimos 12 meses.
    {"anos": {fim: contas}, "ltm": contas, "ltm_ate": data, "saldos_em": data}"""
    anos = {fim: padronizar(dem) for fim, dem in sorted(integral["anual"].items())}
    ultimo = sorted(anos)[-1]
    ltm, ate, saldos_em, composicao = dict(anos[ultimo]), ultimo, ultimo, "exercício completo (DFP)"
    it = integral.get("itr")
    if it and it.get("data") and it["data"] > ultimo and it.get("anterior"):
        a, p = padronizar(it["atual"]), padronizar(it["anterior"])
        base_ano = anos[ultimo]
        ltm = {}
        for k in FLUXOS:
            x, y, zb = a.get(k), p.get(k), base_ano.get(k)
            ltm[k] = (zb + x - y) if None not in (x, y, zb) else None
        for k in SALDOS:
            ltm[k] = a.get(k)
        ltm["_de_onde"] = a.get("_de_onde")
        ate, saldos_em = it["data"], it["data"]
        composicao = f"DFP {ultimo[:4]} + acumulado até {B.data_br(it['data'])} - acumulado até {B.data_br(it.get('data_anterior'))}"
    # a renda do caixa passa pelo caixa operacional? Olha o demonstrativo mais novo: se o lucro e
    # ajustado tirando o rendimento das aplicacoes e nao ha "juros recebidos" de volta, ela fica fora.
    novo = padronizar(it["atual"]) if (it and it.get("data") and it["data"] > ultimo) else anos[ultimo]
    aj, rec = novo.get("renda_caixa_ajuste"), novo.get("juros_recebidos_operacional") or 0.0
    ltm["renda_caixa_fora"] = None if not aj else bool(rec < 0.5 * aj)
    return {"anos": anos, "ltm": ltm, "ltm_ate": ate, "saldos_em": saldos_em, "ltm_composicao": composicao}


def saldo_medio(tab, chave):
    """Media do saldo `chave` na janela dos ultimos 12 meses (interpolacao linear entre os
    balancos conhecidos). Devolve (media, inicio_da_janela)."""
    pts = sorted((dt.date.fromisoformat(f), o.get(chave)) for f, o in tab["anos"].items() if o.get(chave) is not None)
    fim = dt.date.fromisoformat(tab["saldos_em"])
    if tab["ltm"].get(chave) is not None and (not pts or pts[-1][0] < fim):
        pts.append((fim, tab["ltm"][chave]))
    if not pts:
        return None, None
    ini = fim.replace(year=fim.year - 1)
    def em(d):
        if d <= pts[0][0]:
            return pts[0][1]
        for (d0, v0), (d1, v1) in zip(pts, pts[1:]):
            if d0 <= d <= d1:
                return v0 + (v1 - v0) * (d - d0).days / max(1, (d1 - d0).days)
        return pts[-1][1]
    marcos = [ini] + [d for d, _ in pts if ini < d < fim] + [fim]
    area = sum((em(a) + em(b)) / 2.0 * (b - a).days for a, b in zip(marcos, marcos[1:]))
    return area / max(1, (fim - ini).days), ini.isoformat()


def imprimir(integral, dem="DRE", n=5, nivel=3):
    """Demonstracao inteira, linha a linha, dos ultimos n exercicios. Abaixo do nivel 2 o codigo
    da conta muda de sentido de um ano para outro: a linha e casada pela descricao."""
    fins = sorted(integral["anual"])[-n:]
    chave = dem
    if dem == "DFC":
        chave = "DFC_MI" if any("DFC_MI" in integral["anual"][f] for f in fins) else "DFC_MD"
    linhas, ordem = {}, {}
    for f in fins:
        for cd, (ds, v) in (integral["anual"][f].get(chave) or {}).items():
            if _nivel(cd) > nivel:
                continue
            pai = ".".join(cd.split(".")[:2])
            k = (cd, "") if _nivel(cd) <= 2 else (pai, ds.strip().lower())
            linhas.setdefault(k, {"ds": ds, "v": {}})["v"][f] = v
            ordem[k] = [int(x) for x in cd.split(".")]          # posicao do ano mais novo
            linhas[k]["cd"] = cd
    print(f"{dem} consolidada, R$ milhões".ljust(60) + "  ".join(f[:4].rjust(11) for f in fins))
    for k in sorted(linhas, key=lambda k: ordem[k]):
        L = linhas[k]
        vals = [L["v"].get(f) for f in fins]
        if all(v in (None, 0.0) for v in vals):
            continue
        print(f"{L['cd']:<12} {L['ds'][:46]:<46} " + "  ".join((B.br(v, 0) if v is not None else "-").rjust(11) for v in vals))
