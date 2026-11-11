#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ponte com o Safra: de onde vem o numero do banco, de onde vem o da mesa, e o que explica a
diferenca. Nada aqui recomenda; a ponte mede.

O que se le (so leitura, do cache do terminal do Douglas):
  - TIR real que o Safra publica ou passa ao Douglas, com data e preco (tir_safra_ancoras.json);
  - preco-alvo, recomendacao e o crescimento de longo prazo (g) calibrado por perfil de empresa;
  - consenso de mercado (Yahoo) e a TIR que o terminal calcula pelo lucro.
E o que o Douglas informar na conversa (analista.py safra TICKER --alvo ... --tir ...), guardado em
dados_local/analista/safra/.

Como a TIR do Safra vem ao preco de hoje (a mesma regra do terminal, conferida nos numeros deles):
    r_hoje = g + (r_ref - g) x preco_ref / (preco_hoje + proventos pagos desde a data)
E o preco que zera o premio do Safra (TIR = custo de capital proprio deles, real):
    preco = (r_ref - g) x preco_ref / (Ke_real - g) - proventos
"""

from __future__ import annotations

import bisect
import datetime as dt
import json
import sqlite3
from pathlib import Path

from . import base as B
from . import tir_real as T

ANCORAS = Path.home() / "Desktop" / "terminal-artefato" / "coletor" / "tir_safra_ancoras.json"
BANCO = B.TERMINAL.parent / "banco" / "terminal.sqlite"
INFORMADO = B.CACHE / "safra"


def _f(x):
    try:
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _hist(tk):
    return B.ler_json(B.TERMINAL / "hist" / f"{tk}.json") or {}


def fechamento(h, data):
    """Fechamento (ja ajustado por desdobramento) do pregao de `data` ou do anterior."""
    ts = h.get("t") or []
    i = bisect.bisect_right(ts, data) - 1
    return (h["c"][i], ts[i]) if i >= 0 and h["c"][i] else (None, None)


def proventos(h, de, ate):
    return sum(v for d, v in (h.get("div") or []) if de < d <= ate)


def trazer(tir_ref, p_ref, g, preco, prov=0.0):
    """TIR real do Safra trazida ao preco de hoje (regra do terminal): o rendimento (r - g) escala com
    o preco pago, somados os proventos recebidos desde a data; o crescimento de longo prazo g fica."""
    return g + (tir_ref - g) * p_ref / (preco + prov)


def preco_no_ke(tir_ref, p_ref, g, ke, prov=0.0):
    """Preco em que a TIR publicada iguala o custo de capital do banco. None se o Ke nao passa de g."""
    return ((tir_ref - g) * p_ref / (ke - g) - prov) if ke > g else None


def base_de_hoje(alvo, preco_publicado, preco_ajustado):
    """Preco-alvo publicado antes de desdobramento ou bonificacao, trazido para a base de hoje.
    Compara o preco da acao no relatorio com a serie ajustada na mesma data: (alvo ajustado, fator)."""
    fator = 1.0
    if preco_publicado and preco_ajustado and not 0.9 < preco_publicado / preco_ajustado < 1.1:
        fator = preco_publicado / preco_ajustado
    return alvo / fator, fator


def informar(ticker, alvo=None, tir=None, data=None, preco=None, rec=None, fonte=None):
    """Guarda o numero que o Douglas passou na conversa (nao mexe no arquivo do terminal)."""
    tk = ticker.upper()
    arq = INFORMADO / f"{tk}.json"
    d = B.ler_json(arq) or {"ticker": tk, "itens": []}
    item = {"data": data or dt.date.today().isoformat(), "fonte": fonte or "Safra, número informado pelo assessor na conversa"}
    for k, v in (("alvo", alvo), ("tir", tir), ("preco", preco), ("rec", rec)):
        if v is not None:
            item[k] = v
    if "alvo" not in item and "tir" not in item:
        raise B.SemDado("informe --alvo (preço-alvo em R$) e/ou --tir (TIR real, em % ao ano)")
    d["itens"] = [i for i in d["itens"] if i.get("data") != item["data"]] + [item]
    B.gravar_json(arq, d)
    return item


def _g(j, tk):
    emp = (j.get("empresas") or {}).get(tk) or {}
    perfil = emp.get("perfil")
    if emp.get("g") is not None:
        return emp["g"], f"medido pelo terminal nas TIRs do próprio Safra ({emp.get('g_base', 'pares de datas')})", perfil
    if perfil and perfil in (j.get("perfis") or {}):
        pf = j["perfis"][perfil]
        return pf["g"], f"perfil '{pf.get('nome', perfil)}' do terminal", perfil
    from . import setores as S
    setor, sub = S.classificacao_b3(tk)
    tab = (j.get("setores") or {})
    if setor in tab and isinstance(tab[setor], dict):
        return tab[setor].get(sub, tab[setor].get("_", tab.get("padrao", 0.01))), f"setor da B3 ({setor} | {sub}), tabela do terminal", None
    return tab.get("padrao", 0.01), "padrão do terminal (sem perfil nem setor)", None


def _terminal(tk):
    if not BANCO.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{BANCO}?mode=ro", uri=True, timeout=5)
        r = con.execute("select data, preco, tir_hoje_pct, tir_principal_pct, caixa_tir_g0_pct, k_real_pct, tir_principal_base, "
                        "balanco, balanco_idade_dias, base_fonte, avisos "
                        "from tir where ticker=? order by data desc limit 1", (tk,)).fetchone()
        con.close()
    except sqlite3.Error:
        return None
    if not r:
        return None
    pc = lambda x: x / 100.0 if x is not None else None
    try:
        avisos = [str(x) for x in (json.loads(r[10]) if r[10] else [])]
    except (ValueError, TypeError):
        avisos = []
    return {"data": r[0], "preco": r[1], "tir_lucro_hoje": pc(r[2]), "tir_principal": pc(r[3]), "tir_caixa_g0": pc(r[4]),
            "k_real": pc(r[5]), "base": r[6], "balanco": r[7], "balanco_dias": r[8], "base_fonte": r[9], "avisos": avisos}


def carregar(ticker, preco, data_preco, ipca_longo):
    """Tudo o que ha do Safra, do consenso e do terminal sobre o ativo, trazido ao preco de hoje."""
    tk = ticker.upper()
    hoje = dt.date.today()
    dias = lambda iso: (hoje - dt.date.fromisoformat(iso[:10])).days
    j = B.ler_json(ANCORAS)
    h = _hist(tk)
    out = {"ticker": tk, "preco": preco, "tem_ancoras": bool(j), "tir": None, "alvo": None, "rec": None, "historia": [], "avisos": []}
    fund = B.ler_json(B.TERMINAL / "fund" / f"{tk}.json") or {}
    c = fund.get("consenso") or {}
    if c.get("alvo_mediano") or c.get("alvo_medio"):
        out["consenso"] = {"alvo": c.get("alvo_mediano") or c.get("alvo_medio"), "minimo": c.get("alvo_min"), "maximo": c.get("alvo_max"),
                           "casas": c.get("n"), "data": c.get("data"), "fonte": c.get("fonte", "Yahoo"), "rotulo": c.get("rotulo_pt")}
    out["terminal"] = _terminal(tk)
    inf = (B.ler_json(INFORMADO / f"{tk}.json") or {}).get("itens") or []
    if not j and not inf:
        out["avisos"].append("Arquivo de âncoras do Safra não encontrado no terminal e nada informado na conversa: sem ponte com o Safra.")
        return out
    j = j or {}
    met = j.get("metodo") or {}
    ke_nom = met.get("ke_nominal", 0.154)
    velho = met.get("dias_ancora", 100)
    out["ke_nominal"], out["ke_real"] = ke_nom, B.real(ke_nom, ipca_longo)
    out["ke_fonte"] = (met.get("ke_fonte") or "Safra, custo de capital próprio padrão").rstrip(" =")
    g, g_fonte, perfil = _g(j, tk)
    out.update(g=g, g_fonte=g_fonte, perfil=perfil)
    # ---- TIR real
    anc = [dict(a, tir=_f(a["tir"]) / 100.0) for a in (j.get("ancoras") or [])
           if a.get("t") == tk and a.get("tipo", "real") == "real" and _f(a.get("tir")) is not None]
    for i in inf:
        if i.get("tir") is not None:
            anc.append({"t": tk, "tir": _f(i["tir"]) / 100.0, "data": i["data"], "preco_data": i["data"], "preco": i.get("preco"),
                        "fonte": i["fonte"], "uso": "ancora", "origem": "douglas"})
    for a in anc:
        pd_ = a.get("preco_data") or a["data"]
        p_ref = _f(a.get("preco"))
        if p_ref is None:
            p_ref, _ = fechamento(h, pd_)
        a["p_ref"], a["preco_data"] = p_ref, pd_
    anc = sorted((a for a in anc if a["p_ref"]), key=lambda a: (a["preco_data"], a["data"]))
    out["historia"] = [{"data": a["data"], "tir": a["tir"], "preco": a["p_ref"], "repeticao": a.get("uso") == "repeticao"} for a in anc]
    uteis = [a for a in anc if a.get("uso") != "repeticao"]
    if uteis:
        a = uteis[-1]
        prov = proventos(h, a["preco_data"], data_preco)
        r_hoje = trazer(a["tir"], a["p_ref"], g, preco, prov)
        ke = out["ke_real"]
        out["tir"] = {"ref": a["tir"], "data": a["data"], "preco_data": a["preco_data"], "preco_ref": a["p_ref"], "fonte": a.get("fonte", ""),
                      "proventos": prov, "hoje": r_hoje, "dias": dias(a["data"]), "velha": dias(a["data"]) > velho,
                      "premio_sobre_ke": r_hoje - ke,
                      "preco_ke": preco_no_ke(a["tir"], a["p_ref"], g, ke, prov),
                      "rendimento_equivalente": r_hoje - g}
        if out["tir"]["velha"]:
            out["avisos"].append(f"A TIR do Safra é de {B.data_br(a['data'])} ({out['tir']['dias']} dias): trazida ao preço de hoje pela regra do "
                                 "terminal, mas o modelo do banco pode ter mudado. Se houver número mais novo, informe.")
    # ---- preco-alvo
    alvos = [dict(x) for x in ((j.get("alvos_safra") or {}).get("itens") or []) if x.get("t") == tk and _f(x.get("alvo"))]
    for i in inf:
        if i.get("alvo") is not None:
            alvos.append({"t": tk, "alvo": i["alvo"], "preco": i.get("preco"), "data": i["data"], "preco_data": i["data"],
                          "rec": i.get("rec"), "fonte": i["fonte"]})
    if alvos:
        x = sorted(alvos, key=lambda x: x["data"])[-1]
        alvo = _f(x["alvo"])
        ajustado, _ = fechamento(h, x.get("preco_data") or x["data"])
        _, fator = base_de_hoje(alvo, _f(x.get("preco")), ajustado)
        out["alvo"] = {"alvo": alvo / fator, "publicado": alvo, "fator_desdobramento": fator, "data": x["data"], "fonte": x.get("fonte", ""),
                       "preco_na_data": (_f(x.get("preco")) / fator) if _f(x.get("preco")) else ajustado, "rec": x.get("rec"),
                       "dias": dias(x["data"]), "velho": dias(x["data"]) > velho, "potencial": alvo / fator / preco - 1.0}
        if fator != 1.0:
            out["avisos"].append(f"Preço-alvo do Safra publicado como {B.reais(alvo)} antes de desdobramento ou bonificação; na base de hoje, "
                                 f"{B.reais(alvo / fator)} (fator {B.br(fator, 2)}, medido pelo preço da data contra a série ajustada).")
        if out["alvo"]["velho"]:
            out["avisos"].append(f"O preço-alvo do Safra é de {B.data_br(x['data'])} ({out['alvo']['dias']} dias): VELHO. "
                                 "Leia como referência histórica; se houver alvo novo, informe.")
    r = ((j.get("recomendacoes") or {}).get("itens") or {}).get(tk)
    recs = ([{"rec": r["rec"], "data": r["data"], "fonte": r.get("fonte", "")}] if r else []) + \
           [{"rec": i["rec"], "data": i["data"], "fonte": i["fonte"]} for i in inf if i.get("rec")]
    if recs:
        out["rec"] = sorted(recs, key=lambda x: x["data"])[-1]
    return out


def ponte(sf, tir_o=None, dam_o=None, setor=None):
    """Lado a lado: taxa exigida, retorno ao preco de hoje e preco justo de cada lente; depois, o que
    o numero do Safra exige do balanco e onde conferir."""
    p = sf["preco"]
    taxas, retornos, precos, exige, leitura = [], [], [], {}, []
    if sf.get("ke_real") is not None:
        taxas.append(("Safra: custo do capital próprio (Ke) padrão", sf["ke_real"], f"{B.pct(sf['ke_nominal'])} nominal menos a inflação longa do Focus"))
    if dam_o:
        cc = dam_o["custo"]
        taxas.append(("Damodaran: Ke real da empresa", cc["ke_real"], f"juro sem risco real {B.pct(cc['rf_real'], 2)} + beta {B.br(cc['beta'], 2)} x prêmio {B.pct(cc['premio'], 2)}"))
        if dam_o["tipo"] == "fcff":
            taxas.append(("Damodaran: custo médio de capital (WACC) real", dam_o["wacc"], "desconta o caixa da firma, antes da dívida"))
    if tir_o:
        taxas.append(("Mesa: NTN-B 2035 + prêmio exigido", tir_o["ntnb_2035"] + tir_o["premio_exigido"],
                      f"IPCA + {B.br(tir_o['ntnb_2035'] * 100, 2)}% mais {B.br(tir_o['premio_exigido'] * 100, 1)} pp (regime {tir_o['regime']})"))
    t = sf.get("tir")
    if t:
        retornos.append(("Safra: TIR real trazida ao preço de hoje", t["hoje"],
                         f"{B.pct(t['ref'])} em {B.data_br(t['data'])} a {B.reais(t['preco_ref'])}; g de longo prazo {B.pct(sf['g'], 1, True)}"))
    if tir_o:
        for c in tir_o["cenarios"]:
            retornos.append((f"Mesa: {c['nome'].lower()}", c["tir"], c["descricao"][:90]))
    tm = sf.get("terminal")
    if tm and tm.get("tir_principal") is not None:
        retornos.append(("Terminal: TIR pelo lucro (método do Safra replicado)", tm["tir_principal"],
                         f"lucro: {tm.get('base_fonte') or 'n/d'}; balanço {tm.get('balanco') or 'n/d'}; {B.data_br(tm['data'])}"))
    if tm and tm.get("tir_lucro_hoje") is not None:
        retornos.append(("Terminal: TIR pelo lucro de hoje, sem projeção", tm["tir_lucro_hoje"], f"balanço {tm.get('balanco') or 'n/d'}; {B.data_br(tm['data'])}"))
    if tm and (tm.get("avisos") or (tm.get("balanco_dias") or 0) > 120):
        partes = list(tm.get("avisos") or [])
        if (tm.get("balanco_dias") or 0) > 120:
            partes.append(f"o balanço usado é o de {tm.get('balanco')}, com {tm['balanco_dias']} dias")
        sf.setdefault("avisos", [])
        txt = "TIR pelo lucro do terminal com ressalva: " + "; ".join(partes) + ". Leia como referência, não como medida."
        if txt not in sf["avisos"]:
            sf["avisos"].append(txt)
    a = sf.get("alvo")
    if a:
        precos.append(("Safra: preço-alvo" + (" (VELHO)" if a["velho"] else ""), a["alvo"], f"{B.data_br(a['data'])}" + (f", {a['rec']}" if a.get("rec") else "")))
    if t and t.get("preco_ke"):
        precos.append(("Safra: preço em que a TIR deles iguala o Ke deles", t["preco_ke"], "conta da mesa sobre a TIR publicada"))
    c = sf.get("consenso")
    if c:
        precos.append((f"Consenso: alvo mediano de {c.get('casas') or '?'} casas", c["alvo"], f"{c['fonte']}, {B.data_br(c['data'])}"))
    if dam_o:
        precos.append(("Damodaran: preço justo", dam_o["preco_justo"], "parâmetros publicados por ele; premissas no livro"))
    if tir_o:
        if tir_o.get("preco_teto"):
            precos.append(("Mesa: preço que paga NTN-B 2035 + prêmio exigido", tir_o["preco_teto"], f"sobre o {tir_o['central']['nome'].lower()}"))
        if tir_o.get("preco_sem_premio"):
            precos.append(("Mesa: preço que paga só a NTN-B 2035", tir_o["preco_sem_premio"], "prêmio zero sobre o título"))
    # ---- o que o numero do Safra exige do balanco
    if t and tir_o:
        ins, vm = tir_o["ins"], tir_o["valor_mercado"]
        parado = tir_o["cenarios"][0]["fluxo"]
        eb = T.ebitda_para(ins, vm, t["hoje"])
        exige = {"taxa": t["hoje"], "crescimento": T.crescimento_para(parado, vm, t["hoje"]), "ebitda": eb, "ebitda_hoje": ins["ebitda0"],
                 "ebitda_delta": (eb / ins["ebitda0"] - 1.0) if eb else None,
                 "caixa_equivalente": t["rendimento_equivalente"] * vm, "caixa_mesa": tir_o["dono_hoje"],
                 "multiplo_caixa": (t["rendimento_equivalente"] * vm / tir_o["dono_hoje"]) if tir_o["dono_hoje"] > 0 else None}
    tir_nova = bool(t and t.get("preco_ke") and not t["velha"])
    alvo_ref = (a["alvo"] if a and not a["velho"] else None) or (t["preco_ke"] if tir_nova else None) or (c["alvo"] if c else None)
    alvo_nome = ("o alvo do Safra" if a and not a["velho"] else "o preço implícito na TIR do Safra" if tir_nova else "o alvo mediano do consenso")
    if dam_o and alvo_ref:
        pc = dam_o.get("preco_com")
        if pc and dam_o["tipo"] == "fcff":
            f = T._raiz(lambda x: pc(dam_o["wacc"], x) - alvo_ref, 0.3, 5.0)
            w = T._raiz(lambda x: pc(x) - alvo_ref, dam_o["g_estavel"] + 0.006, 0.30)
            exige["damodaran"] = {"alvo": alvo_ref, "nome": alvo_nome, "fator_ebit": f, "ebit": dam_o["ebit0"] * f if f else None, "wacc": w}
        elif pc:
            ke = dam_o["custo"]["ke_nominal"]
            x = T._raiz(lambda x: pc(ke, x) - alvo_ref, -2.0, 4.0)
            exige["damodaran"] = {"alvo": alvo_ref, "nome": alvo_nome, "roe_perene": (ke + x * (dam_o["roe"] - ke)) if x is not None else None}
    # ---- leitura: frases mecanicas, sem recomendacao
    if t and tir_o and tir_o["tir_base"] is not None:
        dif = t["hoje"] - tir_o["central"]["tir"] if tir_o["central"]["tir"] is not None else None
        if dif is not None:
            leitura.append(f"O Safra vê IPCA + {B.br(t['hoje'] * 100, 1)}% ao preço de hoje; a mesa, com o balanço publicado e sem projetar "
                           f"melhora, vê IPCA + {B.br(tir_o['central']['tir'] * 100, 1)}%. Diferença de {B.pp(dif)}.")
    ks = [x[1] for x in taxas if x[0].startswith(("Safra", "Damodaran: Ke"))]
    if len(ks) == 2 and (t or a):
        oque = "no lucro projetado" if (dam_o and dam_o["tipo"] == "excesso") else "no caixa projetado"
        if abs(ks[0] - ks[1]) < 0.012:
            leitura.append(f"A taxa não explica a diferença: o Safra desconta a {B.pct(ks[0])} real e o método de Damodaran chega a {B.pct(ks[1])}. "
                           f"A diferença está {oque}.")
        else:
            leitura.append(f"Parte da diferença é taxa: o Safra usa Ke real de {B.pct(ks[0])} para toda a bolsa; para esta empresa, Damodaran dá {B.pct(ks[1])} "
                           f"({B.pp(ks[1] - ks[0])}).")
    if exige.get("ebitda"):
        leitura.append(f"Para a TIR do Safra fechar com o balanço de hoje, o EBITDA recorrente teria de ser {B.mi(exige['ebitda'])} "
                       f"({B.pct(exige['ebitda_delta'], 0, True)} sobre os 12 meses)" +
                       (f", ou o caixa do dono crescer {B.pct(exige['crescimento'])} ao ano acima da inflação por 10 anos." if exige.get("crescimento") is not None else "."))
    if exige.get("multiplo_caixa"):
        leitura.append(f"Em rendimento de caixa, o número do Safra equivale a {B.mi(exige['caixa_equivalente'])} por ano para o acionista "
                       f"({B.pct(t['rendimento_equivalente'])} do valor de mercado), {B.br(exige['multiplo_caixa'], 1)}x o caixa do dono que o balanço mostra hoje "
                       f"({B.mi(exige['caixa_mesa'])}). " + ("O que falta está na projeção do banco, não no balanço." if exige["multiplo_caixa"] > 1.3 else
                                                           f"O ponto de partida é parecido; a diferença vem do crescimento de longo prazo que o banco embute ({B.pct(sf['g'], 1, True)} real ao ano)."
                                                           if exige["multiplo_caixa"] > 0.8 else "O banco parte de um caixa menor que o do balanço e cresce a partir dele."))
    d = exige.get("damodaran")
    if d and d.get("fator_ebit"):
        leitura.append(f"No método de Damodaran, {d['nome']} ({B.reais(d['alvo'])}) pede lucro operacional de {B.mi(d['ebit'])} "
                       f"({B.pct(d['fator_ebit'] - 1, 0, True)} sobre os 12 meses)" + (f" ou custo de capital de {B.pct(d['wacc'])} real." if d.get("wacc") else "."))
    elif d and d.get("roe_perene") is not None:
        leitura.append(f"No método de Damodaran, {d['nome']} ({B.reais(d['alvo'])}) pede ROE de {B.pct(d['roe_perene'])} para sempre "
                       f"(12 meses: {B.pct(dam_o['roe'])}; custo do capital: {B.pct(dam_o['custo']['ke_nominal'])}).")
    if setor and (exige or d):
        leitura.append("Onde conferir no release e no guidance: " + " ".join(f"({i}) {q}" for i, q in enumerate(setor["perguntas"][:3], 1)))
    return {"safra": sf, "taxas": taxas, "retornos": retornos, "precos": precos, "exige": exige, "leitura": leitura, "preco": p}


def texto(po):
    sf = po["safra"]
    L = [f"PONTE COM O SAFRA  {sf['ticker']}  preço {B.reais(po['preco'])}"]
    if sf.get("rec"):
        L.append(f"  Recomendação do Safra: {sf['rec']['rec']} ({B.data_br(sf['rec']['data'])})")
    for tit, linhas, fmt in (("Taxa que cada um exige (real, ao ano)", po["taxas"], B.pct),
                             ("Retorno real ao preço de hoje", po["retornos"], lambda v: "não fecha" if v is None else "IPCA + " + B.br(v * 100, 1) + "%"),
                             ("Preço justo por lente", po["precos"], B.reais)):
        if linhas:
            L += ["", f"  {tit}:"]
            for nome, v, nota in linhas:
                extra = f"  ({B.pct(v / po['preco'] - 1, 0, True)})" if fmt is B.reais else ""
                L.append(f"   {nome:<52} {fmt(v):>14}{extra}   {nota}")
    if po["leitura"]:
        L += ["", "  Leitura da ponte:"] + [f"   - {x}" for x in po["leitura"]]
    L += [f"  AVISO: {x}" for x in sf["avisos"]]
    return "\n".join(L)
