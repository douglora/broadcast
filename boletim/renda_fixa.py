"""Renda fixa de balcao no boletim: debentures incentivadas, CRI e CRA.

De onde vem:
  `Trade`                   negocio a negocio do balcao, com a taxa de cada negocio
  `InstrumentRegistration`  cadastro do papel: incentivada (Lei 12.431), indexador, taxa de emissao,
                            vencimento. Consultado papel a papel e guardado em rf_cadastro.json.
  `Stock`, `Register`, `RepurchaseDealings`   estoque, registro e compromissadas por instrumento

A taxa do negocio vem na convencao do proprio papel:
  IPCA+     indexado ao IPCA: a taxa e o juro real do negocio (IPCA + x% ao ano)
  CDI+      indexado ao DI com 100% do indexador: a taxa e o premio sobre o CDI
  % do CDI  indexado ao DI por percentual: a taxa e o percentual do CDI
  Pre       prefixado: taxa nominal

Premio sobre o juro real de mercado: taxa do negocio menos o DAP (futuro de cupom de IPCA da B3)
interpolado no vencimento do papel. E aproximacao: compara por vencimento, nao por duration, e
papel que amortiza tem duration menor que o prazo. O DAP sai do mesmo boletim, na mesma data.

CRI e CRA: o boletim informa a securitizadora como emissor, nao o devedor do lastro.
"""

from __future__ import annotations

import re
from datetime import date

from boletim import b3

RX_DAP = re.compile(r"^DAP([FGHJKMNQUVXZ])(\d{2})$")
MESES = "FGHJKMNQUVXZ"
EM_FOCO = ("deb_incentivada", "cri", "cra")
ROTULO = {"deb_incentivada": "Debêntures incentivadas", "cri": "CRI", "cra": "CRA",
          "deb_comum": "Debêntures não incentivadas", "deb_sem_cadastro": "Debêntures sem cadastro lido"}
VALIDOS = ("confirmado", "ajustado b3")


def mil(v, casas: int = 0) -> str:
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def classe(tipo: str, cad: dict | None) -> str | None:
    if tipo == "CRI":
        return "cri"
    if tipo == "CRA":
        return "cra"
    if tipo == "DEB":
        if not cad:
            return "deb_sem_cadastro"
        return "deb_incentivada" if cad.get("incentivada") else "deb_comum"
    return None


def convencao(cad: dict | None, taxa) -> str | None:
    """Como ler a taxa do negocio, pelo indexador do cadastro."""
    idx = ((cad or {}).get("indexador") or "").upper()
    if not idx:
        return None
    if idx in ("DI", "CDI", "SELIC"):
        pct = (cad or {}).get("pct_indexador")
        if taxa is not None and taxa > 30:
            return "% do CDI"
        if taxa is None and pct not in (None, 100, 100.0) and not (cad or {}).get("taxa"):
            return "% do CDI"
        return "CDI+"
    if idx.startswith("PRE"):
        return "Pré"
    if idx.startswith("IPCA"):
        return "IPCA+"
    return idx.title() + "+"


def curva_dap(trades: dict, d: date) -> list:
    """[(anos ate o vencimento, taxa de ajuste)] do DAP, do mais curto ao mais longo."""
    pontos = []
    for tk, r in trades.items():
        m = RX_DAP.match(tk)
        taxa = b3.num(r.get("AdjstdQtTax")) if m else None
        if taxa is None:
            continue
        venc = date(2000 + int(m.group(2)), MESES.index(m.group(1)) + 1, 15)
        anos = (venc - d).days / 365.25
        if anos >= 1.0:             # o DAP curto carrega a inflacao dos proximos meses e distorce
            pontos.append((round(anos, 3), taxa, tk))
    return sorted(pontos)


def interpolar(curva: list, anos: float):
    """Taxa do DAP no prazo pedido: linear entre vertices, chata nas pontas."""
    if len(curva) < 2 or anos is None:
        return None
    if anos <= curva[0][0]:
        return curva[0][1]
    if anos >= curva[-1][0]:
        return curva[-1][1]
    for (x0, y0, _), (x1, y1, _) in zip(curva, curva[1:]):
        if x0 <= anos <= x1:
            return y0 + (y1 - y0) * (anos - x0) / (x1 - x0) if x1 > x0 else y0
    return None


def agregar(regs: list[dict]) -> dict:
    """Negocios do dia por papel: volume, PU medio e taxa media ponderada pelo volume."""
    por: dict = {}
    for r in regs:
        if r.get("InstrumentType") not in ("DEB", "CRI", "CRA") or (r.get("Situation") or "").strip().lower() not in VALIDOS:
            continue
        cod = (r.get("TckrSymb") or "").strip()
        vol, qtd, taxa = r.get("Vol") or 0.0, r.get("Quantity") or 0.0, r.get("Rate")
        p = por.setdefault(cod, {"tipo": r["InstrumentType"], "emissor": (r.get("Issuer") or "").strip(), "negocios": 0,
                                 "volume_rs": 0.0, "quantidade": 0.0, "_tv": 0.0, "_v": 0.0, "taxas": []})
        p["negocios"] += 1
        p["volume_rs"] += vol
        p["quantidade"] += qtd
        if taxa is not None:
            p["_tv"] += taxa * vol
            p["_v"] += vol
            p["taxas"].append(taxa)
    for p in por.values():
        taxas = p.pop("taxas")
        tv, v = p.pop("_tv"), p.pop("_v")
        p["taxa_media"] = round(tv / v, 4) if v else (round(sum(taxas) / len(taxas), 4) if taxas else None)
        p["taxa_min"], p["taxa_max"] = (min(taxas), max(taxas)) if taxas else (None, None)
        p["pu_medio"] = round(p["volume_rs"] / p["quantidade"], 6) if p["quantidade"] else None
        p["volume_rs"] = round(p["volume_rs"], 2)
    return por


def _anterior(estado: dict, cod: str, iso: str):
    for data, taxa, pu in sorted(estado.get(cod) or [], reverse=True):
        if data < iso:
            return data, taxa, pu
    return None, None, None


def montar(ctx) -> dict:
    """Bloco `renda_fixa` do resumo. `ctx` e o Contexto de boletim/resumo.py."""
    t = ctx.tab("Trade")
    if not t:
        return {}
    cfg = ctx.cfg.get("renda_fixa") or {}
    piso = cfg.get("volume_minimo_rs", 500000)
    if t.get("truncada"):
        ctx.lacunas.append("Renda fixa: o negócio a negócio passou do teto de páginas; os totais do dia estão incompletos.")
    por = agregar(b3.registros(t))
    cadastro = ctx.bruto.get("rf_cadastro") or {}
    estado = ctx.rf_estado
    dap = curva_dap(ctx.trades, ctx.d)

    linhas: dict = {}
    for cod, p in por.items():
        cad = cadastro.get(cod)
        cl = classe(p["tipo"], cad)
        conv = convencao(cad, p["taxa_media"])
        venc = (cad or {}).get("vencimento")
        anos = round((date.fromisoformat(venc[:10]) - ctx.d).days / 365.25, 2) if venc else None
        linha = {"codigo": cod, "classe": cl, "emissor": p["emissor"], "negocios": p["negocios"], "volume_rs": p["volume_rs"],
                 "pu_medio": p["pu_medio"], "taxa_media": p["taxa_media"], "taxa_min": p["taxa_min"], "taxa_max": p["taxa_max"],
                 "convencao": conv, "indexador": (cad or {}).get("indexador"), "taxa_emissao": (cad or {}).get("taxa"),
                 "pct_indexador": (cad or {}).get("pct_indexador"), "vencimento": venc[:10] if venc else None, "prazo_anos": anos}
        if conv == "IPCA+" and p["taxa_media"] is not None and anos and anos >= 1.0:
            ref = interpolar(dap, anos)
            if ref is not None:
                linha["premio_dap_pb"] = round((p["taxa_media"] - ref) * 100.0)
        d_ant, taxa_ant, _ = _anterior(estado, cod, ctx.iso)
        if taxa_ant is not None and p["taxa_media"] is not None and p["volume_rs"] >= piso and conv in ("IPCA+", "CDI+", "Pré"):
            linha["var_taxa_pb"], linha["comparado_com"] = round((p["taxa_media"] - taxa_ant) * 100.0), d_ant
        linhas[cod] = linha

    # ---- totais por classe
    resumo: dict = {}
    for cl in ROTULO:
        ls = [l for l in linhas.values() if l["classe"] == cl]
        if not ls:
            continue
        vol = sum(l["volume_rs"] for l in ls)
        item = {"rotulo": ROTULO[cl], "papeis": len(ls), "negocios": sum(l["negocios"] for l in ls), "volume_rs": round(vol, 0),
                "emissores": len({l["emissor"] for l in ls})}
        ipca = [l for l in ls if l["convencao"] == "IPCA+" and l["taxa_media"] is not None and l["volume_rs"] >= piso]
        if ipca:
            v = sum(l["volume_rs"] for l in ipca)
            item["taxa_ipca_media"] = round(sum(l["taxa_media"] * l["volume_rs"] for l in ipca) / v, 2)
            com_premio = [l for l in ipca if l.get("premio_dap_pb") is not None]
            if com_premio:
                vp = sum(l["volume_rs"] for l in com_premio)
                item["premio_dap_medio_pb"] = round(sum(l["premio_dap_pb"] * l["volume_rs"] for l in com_premio) / vp)
        cdi = [l for l in ls if l["convencao"] == "CDI+" and l["taxa_media"] is not None and l["volume_rs"] >= piso]
        if cdi:
            v = sum(l["volume_rs"] for l in cdi)
            item["premio_cdi_medio"] = round(sum(l["taxa_media"] * l["volume_rs"] for l in cdi) / v, 2)
        por_conv: dict = {}
        for l in ls:
            por_conv[l["convencao"] or "sem cadastro"] = por_conv.get(l["convencao"] or "sem cadastro", 0.0) + l["volume_rs"]
        item["por_indexador_pct"] = {k: round(v / vol * 100.0, 1) for k, v in sorted(por_conv.items(), key=lambda kv: -kv[1])} if vol else {}
        vols = ctx.serie("rf", cl, n=20)
        if len(vols) >= ctx.lim.get("volume_base_minima", 10):
            m = sum(vols) / len(vols)
            item["volume_media_rs"], item["volume_x_media"] = round(m, 0), (round(vol / m, 2) if m else None)
            if cl in EM_FOCO and item["volume_x_media"] and item["volume_x_media"] >= cfg.get("giro_x_media", 2.0):
                ctx.sinal("rf_giro", None, f"{ROTULO[cl]}: R$ {mil(vol / 1e6)} mi negociados no balcão, "
                          f"{mil(item['volume_x_media'], 1)}x a média de {len(vols)} pregões.", "Trade", volume_rs=vol)
        resumo[cl] = item

    top = cfg.get("top", 20)
    papeis = {cl: sorted((l for l in linhas.values() if l["classe"] == cl), key=lambda l: -l["volume_rs"])[:top] for cl in EM_FOCO}
    foco = [l for l in linhas.values() if l["classe"] in EM_FOCO]

    # ---- curva de credito incentivado: taxa x prazo
    curva = [{"codigo": l["codigo"], "emissor": l["emissor"], "anos": l["prazo_anos"], "taxa": l["taxa_media"],
              "volume_rs": l["volume_rs"], "premio_dap_pb": l.get("premio_dap_pb")}
             for l in linhas.values()
             if l["classe"] == "deb_incentivada" and l["convencao"] == "IPCA+" and l["taxa_media"] is not None
             and l["prazo_anos"] and l["prazo_anos"] > 0 and l["volume_rs"] >= piso]
    curva = sorted(curva, key=lambda x: -x["volume_rs"])[:cfg.get("curva_pontos", 140)]

    # ---- quem abriu e quem fechou taxa contra o ultimo negocio visto
    piso_mov = cfg.get("movimento_volume_minimo_rs", 1000000)
    mov = [l for l in foco if l.get("var_taxa_pb") is not None and l["volume_rs"] >= piso_mov]
    aberturas = sorted((l for l in mov if l["var_taxa_pb"] > 0), key=lambda l: -l["var_taxa_pb"])[:8]
    fechamentos = sorted((l for l in mov if l["var_taxa_pb"] < 0), key=lambda l: l["var_taxa_pb"])[:8]
    piso_sinal = cfg.get("sinal_volume_minimo_rs", 5000000)
    for l in [l for l in aberturas if l["volume_rs"] >= piso_sinal][:3]:
        if l["var_taxa_pb"] >= cfg.get("var_taxa_sinal_pb", 30):
            ctx.sinal("rf_abertura", l["codigo"],
                      f"{l['codigo']} ({l['emissor'].title()[:38]}, {ROTULO[l['classe']].lower()}): taxa média abriu "
                      f"{l['var_taxa_pb']} pb contra {b3_dm(l['comparado_com'])}, para {l['convencao']} {mil(l['taxa_media'], 2)}%, "
                      f"em R$ {mil(l['volume_rs'] / 1e6, 1)} mi.", "Trade + InstrumentRegistration",
                      var_taxa_pb=l["var_taxa_pb"], taxa=l["taxa_media"], volume_rs=l["volume_rs"])

    # ---- taxas mais altas: onde o mercado esta pedindo premio
    lim_premio, lim_cdi = cfg.get("premio_estresse_pb", 300), cfg.get("cdi_estresse", 5.0)
    estresse = sorted((l for l in foco if l["volume_rs"] >= piso_mov and (
        (l.get("premio_dap_pb") or 0) >= lim_premio or (l["convencao"] == "CDI+" and (l["taxa_media"] or 0) >= lim_cdi))),
        key=lambda l: -(l.get("premio_dap_pb") or (l["taxa_media"] or 0) * 100))[:10]
    for l in [l for l in estresse if l["volume_rs"] >= piso_sinal][:3]:
        if True:
            extra = (f", {mil(l['premio_dap_pb'])} pb acima do juro real de mercado de prazo equivalente"
                     if l.get("premio_dap_pb") is not None else "")
            ctx.sinal("rf_premio_alto", l["codigo"],
                      f"{l['codigo']} ({l['emissor'].title()[:38]}, {ROTULO[l['classe']].lower()}): negociada a "
                      f"{l['convencao']} {mil(l['taxa_media'], 2)}%{extra}, em R$ {mil(l['volume_rs'] / 1e6, 1)} mi.",
                      "Trade + InstrumentRegistration", taxa=l["taxa_media"], premio_dap_pb=l.get("premio_dap_pb"),
                      volume_rs=l["volume_rs"])

    # ---- emissores e maiores negocios
    emis: dict = {}
    for l in foco:
        e = emis.setdefault(l["emissor"], {"emissor": l["emissor"], "volume_rs": 0.0, "negocios": 0, "papeis": 0, "classes": set()})
        e["volume_rs"] += l["volume_rs"]
        e["negocios"] += l["negocios"]
        e["papeis"] += 1
        e["classes"].add(ROTULO[l["classe"]])
    emissores = sorted(emis.values(), key=lambda e: -e["volume_rs"])[:10]
    for e in emissores:
        e["classes"], e["volume_rs"] = sorted(e["classes"]), round(e["volume_rs"], 0)
    # nas incentivadas o emissor e a empresa (nas outras classes e a securitizadora): quem o mercado mais girou
    inc: dict = {}
    for l in linhas.values():
        if l["classe"] != "deb_incentivada":
            continue
        e = inc.setdefault(l["emissor"], {"emissor": l["emissor"], "volume_rs": 0.0, "negocios": 0, "papeis": 0, "_tv": 0.0, "_v": 0.0,
                                          "_pv": 0.0, "_p": 0.0})
        e["volume_rs"] += l["volume_rs"]
        e["negocios"] += l["negocios"]
        e["papeis"] += 1
        if l["convencao"] == "IPCA+" and l["taxa_media"] is not None and l["volume_rs"] >= piso:
            e["_tv"] += l["taxa_media"] * l["volume_rs"]
            e["_v"] += l["volume_rs"]
            if l.get("premio_dap_pb") is not None:
                e["_pv"] += l["premio_dap_pb"] * l["volume_rs"]
                e["_p"] += l["volume_rs"]
    emissores_inc = sorted(inc.values(), key=lambda e: -e["volume_rs"])[:10]
    for e in emissores_inc:
        tv, v, pv, pp = e.pop("_tv"), e.pop("_v"), e.pop("_pv"), e.pop("_p")
        e["taxa_ipca_media"] = round(tv / v, 2) if v else None
        e["premio_dap_medio_pb"] = round(pv / pp) if pp else None
        e["volume_rs"] = round(e["volume_rs"], 0)
    maiores = []
    for r in sorted((r for r in b3.registros(t) if r.get("InstrumentType") in ("DEB", "CRI", "CRA")
                     and (r.get("Situation") or "").strip().lower() in VALIDOS), key=lambda r: -(r.get("Vol") or 0))[:10]:
        cl = classe(r["InstrumentType"], cadastro.get(r["TckrSymb"]))
        maiores.append({"codigo": r["TckrSymb"], "emissor": (r.get("Issuer") or "").strip(), "classe": cl,
                        "volume_rs": r.get("Vol"), "taxa": r.get("Rate"), "hora": r.get("TradeTime"),
                        "convencao": convencao(cadastro.get(r["TckrSymb"]), r.get("Rate"))})

    # ---- estoque, registro e compromissadas por instrumento
    def por_instrumento(nome: str, campos: dict) -> dict:
        tb, out = ctx.tab(nome), {}
        for r in b3.registros(tb) if tb else []:
            if r.get("TckrSymb") in ("DEB", "CRI", "CRA"):
                out[r["TckrSymb"]] = {k: r.get(c) for k, c in campos.items()}
        return out

    vol_total = sum(p["volume_rs"] for p in por.values())
    vol_cad = sum(p["volume_rs"] for c, p in por.items() if cadastro.get(c) or p["tipo"] != "DEB")
    acompanhados = []
    for cod in cfg.get("papeis") or []:
        acompanhados.append(linhas.get(cod) or {"codigo": cod, "sem_negocio": True})

    return {
        "data": ctx.iso, "fonte": ctx.fonte("Trade"),
        "resumo": resumo, "papeis": papeis, "curva": curva,
        "dap": [[a, tx, tk] for a, tx, tk in dap],
        "aberturas": aberturas, "fechamentos": fechamentos, "premios_altos": estresse,
        "emissores": emissores, "emissores_incentivadas": emissores_inc, "maiores_negocios": maiores, "acompanhados": acompanhados,
        "estoque": por_instrumento("Stock", {"quantidade_em_mercado": "QuantityMarket", "volume_em_mercado_rs": "VolumeMarket",
                                             "instrumentos": "QuantityInstrument"}),
        "registro": por_instrumento("Register", {"instrumentos": "QuantityInstrument", "volume_rs": "RegisterVolume"}),
        "compromissadas": por_instrumento("RepurchaseDealings", {"negocios": "NumberOfDealings", "volume_rs": "FinancialValue",
                                                                 "prazo_medio": "AverageTerm"}),
        "cobertura_cadastro_pct": round(vol_cad / vol_total * 100.0, 1) if vol_total else None,
        "papeis_negociados": len(por),
        "nota": "CRI e CRA: o boletim informa a securitizadora, não o devedor. Prêmio sobre o DAP compara por vencimento, "
                "não por duration: é aproximação.",
        "_linhas": linhas,
    }


def b3_dm(iso) -> str:
    return f"{str(iso)[8:10]}/{str(iso)[5:7]}" if iso else "?"


def atualizar_estado(estado: dict, rf: dict, iso: str, piso: float = 500000, dias: int = 75, guardar: int = 3) -> dict:
    """Ultimas taxas vistas por papel (ate `guardar` pregoes), para medir abertura e fechamento."""
    novo = {k: [list(x) for x in v] for k, v in (estado or {}).items()}
    for cod, l in (rf.get("_linhas") or {}).items():
        if l.get("classe") not in EM_FOCO or l.get("taxa_media") is None or l.get("volume_rs", 0) < piso:
            continue
        obs = [x for x in novo.get(cod, []) if x[0] != iso] + [[iso, l["taxa_media"], l.get("pu_medio")]]
        novo[cod] = sorted(obs)[-guardar:]
    corte = date.fromordinal(date.fromisoformat(iso).toordinal() - dias).isoformat()
    return {k: v for k, v in sorted(novo.items()) if v and v[-1][0] >= corte}
