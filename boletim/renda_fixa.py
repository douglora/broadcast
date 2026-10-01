"""Renda fixa de balcao no boletim: debentures incentivadas, CRI e CRA.

De onde vem:
  `Trade`                   negocio a negocio do balcao da B3, com a taxa de cada negocio
  `InstrumentRegistration`  cadastro do papel: incentivada (Lei 12.431), indexador, taxa de emissao,
                            vencimento. Consultado papel a papel e guardado em rf_cadastro.json.
  `Stock`, `Register`, `RepurchaseDealings`   estoque, registro e compromissadas por instrumento
  ANBIMA                    taxa indicativa, de compra e de venda, PU e duration de cada debenture, no
                            arquivo diario do mercado secundario (boletim/anbima.py). So debentures.

A taxa vem na convencao do proprio papel, na B3 e na ANBIMA:
  IPCA+     indexado ao IPCA: a taxa e o juro real (IPCA + x% ao ano)
  CDI+      indexado ao DI com 100% do indexador: a taxa e o premio sobre o CDI
  % do CDI  indexado ao DI por percentual: a taxa e o percentual do CDI
  Pre       prefixado: taxa nominal

Em DI a taxa do negocio vem na convencao que o cadastro do papel descreve, e e ele quem decide a leitura:
  DI + taxa (100% do indexador e taxa de emissao maior que zero): premio sobre o CDI, por mais alta que seja;
  percentual do DI (percentual diferente de 100, sem taxa): percentual do CDI, por mais baixa que seja.
Ate 01/10/2026 so a grandeza da taxa decidia (acima de 30, percentual do CDI), e errava nas duas pontas. Papel
em DI + taxa que negocia em estresse sai acima de 30: BRKMA6 (DI + 1,75%) fez R$ 15,0 mi a 54,33 em 30/09/2026
com o PU a 44% do par, e isso e CDI + 54,33%. E negocio fora de preco em papel de percentual sai abaixo de 30:
o CRI 25G5827604 (109% do DI) saiu a 1,94 em 29/09 com o PU 45% acima dos outros negocios do dia, e isso e
1,94% do CDI, nao premio. Medido nos 21 pregoes de 01/09 a 30/09/2026 (12.204 leituras de papel em DI): 66
erradas. 65 em 12 papeis de DI + taxa (4 debentures, 7 CRA e 1 CRI), lidas como percentual: em 10 deles a taxa
varia muito de um negocio para outro e o preco cai quando ela sobe (correlacao de -0,90 a -1,00 entre taxa e
PU); os outros 2 so negociaram numa faixa estreita, acima de 30. E 1 em papel de percentual, lida como premio.
Nas 544 debentures em DI que tambem estao no arquivo da ANBIMA, o cadastro deu a convencao dela em todas.
A grandeza da taxa so decide quando o cadastro nao decide: 100% do indexador sem taxa (papel a 100% do CDI),
percentual com taxa, sem percentual, ou percentual de ate 30 (cadastro torto). Nesses papeis os 3.796 negocios
com taxa do periodo sairam todos acima de 30, entre 83 e 149.

Duas taxas por debenture, cada uma com fonte e data:
  negocios do dia  media dos negocios da B3 ponderada pelo volume (`taxa_media`). Em papel com muito
                   negocio pequeno ela pende para a taxa do varejo, que compra a taxa menor: medido
                   em 01/10/2026, na media de 5 pregoes EQPA18 saia a IPCA+7,70% e CGOS16 a 8,16%,
                   com as indicativas de 30/09 em 8,16% e 8,19%.
  indicativa       a da ANBIMA (`anbima.indicativa`), referencia do mercado profissional.
`ref` e a taxa que vale para comparar papel com papel: a indicativa quando ha, a dos negocios quando
nao ha (CRI, CRA e debenture fora do arquivo da ANBIMA). Curva de credito, medianas, premios altos e
quem abriu e fechou taxa saem de `ref`; a taxa dos negocios fica ao lado.

Premio sobre o juro real de mercado: taxa menos o DAP (futuro de cupom de IPCA da B3) da mesma data,
interpolado no prazo do papel. Com a indicativa o prazo e a duration da ANBIMA, que e a comparacao
certa para papel que amortiza (`premio_base: duration`); duration abaixo de um ano fica sem premio,
porque o DAP curto carrega a inflacao dos proximos meses, e nao ganha o do vencimento no lugar. Sem a
indicativa (ou se a ANBIMA nao der a duration) o prazo e o vencimento, e papel que amortiza tem prazo
medio menor que o vencimento: e aproximacao (`premio_base: vencimento`).

Abertura e fechamento de taxa: pela indicativa, de um arquivo da ANBIMA para o seguinte; sem ela, a
media dos negocios contra o ultimo pregao em que o papel negociou acima do volume minimo. So em IPCA+,
CDI+ e prefixado: em percentual do CDI a diferenca nao e ponto-base de taxa.

CRI e CRA: o boletim informa a securitizadora como emissor, nao o devedor do lastro.

Preliminar: a B3 ajusta o negocio a negocio de balcao no dia seguinte (em 30/09/2026 o volume de
incentivadas do dia mudou de R$ 3,6 bi para R$ 2,2 bi entre duas rodadas da noite; o de 29/09
fechou as 11h57 de 30/09). Ate a tabela ser atualizada depois das 11h de D+1, o bloco leva
`preliminar: true` e os sinais dizem "(preliminar)" na fonte.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from livro import relogios

from boletim import anbima, b3

RX_DAP = re.compile(r"^DAP([FGHJKMNQUVXZ])(\d{2})$")
MESES = "FGHJKMNQUVXZ"
EM_FOCO = ("deb_incentivada", "cri", "cra")
SINGULAR = {"deb_incentivada": "debênture incentivada", "cri": "CRI", "cra": "CRA"}
ROTULO = {"deb_incentivada": "Debêntures incentivadas", "cri": "CRI", "cra": "CRA",
          "deb_comum": "Debêntures não incentivadas", "deb_sem_cadastro": "Debêntures sem cadastro lido"}
ROTULO_FONTE = {"anbima": "ANBIMA indicativa", "b3": "B3 negócios"}
VALIDOS = ("confirmado", "ajustado b3")
COM_VARIACAO = ("IPCA+", "CDI+", "Pré")       # convencoes em que a diferenca entre duas taxas e ponto-base de taxa
CORTE_PCT_CDI = 30.0                          # papel em DI cujo cadastro nao decide: taxa acima disto e percentual do CDI


def mil(v, casas: int = 0) -> str:
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pb(v) -> str:
    """Pontos-base em texto: inteiro quando e inteiro, uma casa quando nao (a indicativa anda em decimos)."""
    return mil(v, 0 if float(v).is_integer() else 1)


def mediana(xs: list):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2.0


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
    """Como ler a taxa do negocio, pelo indexador do cadastro. A B3 da a taxa na convencao do proprio papel: em DI
    o cadastro diz se ela e premio sobre o CDI ou percentual do CDI, e a grandeza da taxa so decide quando ele nao diz."""
    idx = ((cad or {}).get("indexador") or "").upper()
    if not idx:
        return None
    if idx in ("DI", "CDI", "SELIC"):
        pct, emissao = b3.num(cad.get("pct_indexador")), b3.num(cad.get("taxa"))
        com_taxa = (emissao or 0) > 0
        # DI + taxa: a taxa do negocio e o premio sobre o CDI, por mais alta que seja. Papel em estresse negocia acima
        # de 30 (BRKMA6 a 54,33 em 30/09/2026, com o PU a 44% do par) e nao vira percentual do CDI
        if pct == 100 and com_taxa:
            return "CDI+"
        # Percentual do DI, sem taxa: a taxa do negocio e percentual do CDI, por mais baixa que seja. Negocio fora de
        # preco sai abaixo de 30 (25G5827604, 109% do DI, a 1,94 em 29/09/2026, com o PU 45% acima dos outros negocios
        # do dia) e nao vira premio. Percentual de ate 30 no cadastro (ha papel com 1 e com 3) e cadastro torto: nao decide
        if pct not in (None, 100) and pct > CORTE_PCT_CDI and not com_taxa:
            return "% do CDI"
        # O cadastro nao decide (100% sem taxa, percentual com taxa, sem percentual): vale a grandeza da taxa
        if taxa is not None and taxa > CORTE_PCT_CDI:
            return "% do CDI"
        if taxa is None and pct not in (None, 100) and not com_taxa:
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


def premio(taxa, dap: list, anos):
    """Taxa menos o DAP interpolado no prazo, em pontos-base. Prazo abaixo de um ano fica sem premio:
    o DAP curto carrega a inflacao dos proximos meses."""
    if taxa is None or not anos or anos < 1.0:
        return None
    ref = interpolar(dap, anos)
    return None if ref is None else round((taxa - ref) * 100.0)


def _anos(venc, d: date):
    return round((date.fromisoformat(venc[:10]) - d).days / 365.25, 2) if venc else None


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


# ------------------------------------------------------------------ ANBIMA e a taxa de referencia

def indicativa(a: dict, antes: dict | None, data: str, data_antes: str | None, dap: list) -> dict:
    """O que a ANBIMA publicou do papel no arquivo de `data`, com o premio sobre o juro real da mesma
    data (`dap`) e a variacao da indicativa contra o arquivo anterior. `--` e `N/D` ficam nulos."""
    du, taxa = a.get("duration_du"), a.get("indicativa")
    out = {"data": data, "indicativa": taxa, "compra": a.get("compra"), "venda": a.get("venda"), "pu": a.get("pu"),
           "duration_du": du, "duration_anos": round(du / anbima.DIAS_UTEIS_ANO, 2) if du else None}
    extras = {"desvio": a.get("desvio"), "pct_pu_par": a.get("pct_pu_par"), "repac_venc": a.get("repac_venc"),
              "ntnb_ref": a.get("ntnb_ref")}
    if a.get("convencao") == "IPCA+" and taxa is not None and dap:
        extras["premio_dap_duration_pb"] = premio(taxa, dap, out["duration_anos"])
        # a taxa da ANBIMA vale ate a data da coluna Repac./Venc., que pode vir antes do vencimento do cadastro
        extras["premio_dap_pb"] = premio(taxa, dap, _anos(a.get("repac_venc"), date.fromisoformat(data)))
    if (antes and taxa is not None and antes.get("indicativa") is not None
            and a.get("convencao") in COM_VARIACAO and antes.get("convencao") == a.get("convencao")):
        extras["var_pb"], extras["comparado_com"] = round((taxa - antes["indicativa"]) * 100.0, 1), data_antes
    out.update({k: v for k, v in extras.items() if v is not None})
    return out


def _ref_b3(l: dict, pregao: str | None) -> dict | None:
    if l.get("taxa_media") is None:
        return None
    ref = {"taxa": l["taxa_media"], "fonte": "b3", "data": pregao}
    if l.get("premio_dap_pb") is not None:
        ref["premio_dap_pb"], ref["premio_base"] = l["premio_dap_pb"], "vencimento"
    if l.get("var_taxa_pb") is not None:
        ref["var_pb"], ref["var_contra"] = l["var_taxa_pb"], l.get("comparado_com")
    return ref


def _ref(l: dict, pregao: str, usa_anbima: bool, no_dia: bool) -> dict | None:
    """A taxa que vale para comparar o papel: a indicativa da ANBIMA quando ha, senao a dos negocios.
    A variacao pela indicativa so entra quando o arquivo e do proprio pregao (`no_dia`): a de um
    arquivo mais antigo ja foi contada no pregao dele.

    O premio da indicativa e medido na duration e so nela: com duration abaixo de um ano o papel fica
    sem premio, em vez de ganhar o do vencimento com o rotulo trocado. So quando a ANBIMA nao da a
    duration vale o vencimento, e `premio_base` diz isso."""
    a = l.get("anbima") or {}
    if not usa_anbima or a.get("indicativa") is None:
        return _ref_b3(l, pregao)
    ref = {"taxa": a["indicativa"], "fonte": "anbima", "data": a["data"]}
    if a.get("duration_anos"):
        if a.get("premio_dap_duration_pb") is not None:
            ref["premio_dap_pb"], ref["premio_base"] = a["premio_dap_duration_pb"], "duration"
    elif a.get("premio_dap_pb") is not None:
        ref["premio_dap_pb"], ref["premio_base"] = a["premio_dap_pb"], "vencimento"
    if no_dia and a.get("var_pb") is not None:
        ref["var_pb"], ref["var_contra"] = a["var_pb"], a.get("comparado_com")
    return ref


def referencia(l: dict, pregao: str | None = None) -> dict:
    """`ref` do papel, para quem le o resumo. Resumo gravado antes de a ANBIMA entrar (01/10/2026) nao
    tem o campo: ali so havia os negocios da B3 do proprio pregao."""
    return l.get("ref") or _ref_b3(l, pregao) or {}


def rotulo_fonte(ref: dict) -> str:
    """De onde vem a taxa e de que dia, como a tela escreve: ANBIMA indicativa de 30/09, ou B3 e os negocios de 30/09."""
    return f"{ROTULO_FONTE.get(ref.get('fonte'), ROTULO_FONTE['b3'])} de {b3_dm(ref.get('data'))}"


def _medias(ls: list, piso: float, pega) -> dict:
    """Media ponderada pelo volume e mediana das taxas IPCA+ e CDI+ dos papeis acima do volume minimo.
    `pega(l)` devolve (taxa, premio sobre o DAP) do papel: os de `ref` ou os dos negocios da B3."""
    out: dict = {}
    ipca = [(tx, pr, l["volume_rs"]) for l in ls if l["convencao"] == "IPCA+" and l["volume_rs"] >= piso
            for tx, pr in [pega(l)] if tx is not None]
    if ipca:
        v = sum(w for _, _, w in ipca)
        out["taxa_ipca_media"] = round(sum(tx * w for tx, _, w in ipca) / v, 2)
        # a mediana nao se deixa levar por um negocio grande fora da curva
        out["taxa_ipca_mediana"] = round(mediana([tx for tx, _, _ in ipca]), 2)
        med = mediana([pr for _, pr, _ in ipca])
        out["premio_dap_mediano_pb"] = round(med) if med is not None else None
        out["papeis_ipca"] = len(ipca)
        com_premio = [(pr, w) for _, pr, w in ipca if pr is not None]
        if com_premio:
            out["premio_dap_medio_pb"] = round(sum(pr * w for pr, w in com_premio) / sum(w for _, w in com_premio))
    cdi = [(tx, l["volume_rs"]) for l in ls if l["convencao"] == "CDI+" and l["volume_rs"] >= piso
           for tx, _ in [pega(l)] if tx is not None]
    if cdi:
        out["premio_cdi_medio"] = round(sum(tx * w for tx, w in cdi) / sum(w for _, w in cdi), 2)
        out["premio_cdi_mediano"] = round(mediana([tx for tx, _ in cdi]), 2)
    return out


def _da_ref(l: dict) -> tuple:
    r = l.get("ref") or {}
    return r.get("taxa"), r.get("premio_dap_pb")


def _da_b3(l: dict) -> tuple:
    return l.get("taxa_media"), l.get("premio_dap_pb")


def _fontes(ls: list, piso: float) -> dict:
    """Quantos papeis acima do volume minimo tem a taxa de cada fonte."""
    out: dict = {}
    for l in ls:
        r = l.get("ref")
        if r and l["volume_rs"] >= piso:
            out[r["fonte"]] = out.get(r["fonte"], 0) + 1
    return out


def _dias_uteis_ate_a_coleta(ctx):
    """Quantos dias uteis separam o pregao da rodada, na hora de Brasilia (a rodada da noite roda a 00h40 UTC
    do dia seguinte). None se o bruto nao diz quando foi coletado."""
    quando = str((ctx.bruto.get("index") or {}).get("coletado_em") or "")[:19]
    try:
        return relogios.dias_uteis_b3(ctx.d, relogios.brt(datetime.strptime(quando, "%Y-%m-%dT%H:%M:%S")).date())
    except ValueError:
        return None


def _lacunas_anbima(ctx, anb: dict, data_anb, tem_dap: bool, dias_atras: int) -> None:
    sit, hoje = anb.get("situacao"), b3_dm(ctx.iso)
    if not anb:
        ctx.lacunas.append("ANBIMA: taxas indicativas não coletadas nesta rodada; debêntures pelos negócios da B3.")
    elif sit == "falhou":
        ctx.lacunas.append(f"ANBIMA: a leitura das taxas indicativas falhou nesta rodada ({anb.get('erro') or 'sem resposta'}); "
                           "debêntures pelos negócios da B3.")
    elif sit == "ausente":
        ctx.lacunas.append(f"ANBIMA: sem arquivo de taxas indicativas de {hoje} nem dos {dias_atras} dias úteis anteriores "
                           "no site (ela guarda poucos dias); debêntures pelos negócios da B3.")
    elif sit == "anterior":
        resposta = (anb.get("tentativas") or {}).get(ctx.iso)
        dias = _dias_uteis_ate_a_coleta(ctx)
        espera = "fica sem medida até ele chegar"
        if resposta == "falhou":
            motivo, espera = f"não pôde ser lido ({anb.get('erro') or 'sem resposta'})", "não foi medida"
        elif resposta == "nao tentado":
            motivo, espera = "não foi tentado (a ANBIMA não respondeu nesta rodada)", "não foi medida"
        elif dias is None or dias == 0:
            motivo = "ainda não foi publicado"
        elif dias <= 2:
            motivo = "não tinha sido publicado até esta coleta"
        else:
            motivo, espera = "não está no site da ANBIMA (ela guarda poucos dias)", "não foi medida"
        ctx.lacunas.append(f"ANBIMA: o arquivo de taxas indicativas de {hoje} {motivo}; as debêntures usam as indicativas de "
                           f"{b3_dm(data_anb)}, e a variação do dia pela indicativa {espera}.")
        if not tem_dap:
            ctx.lacunas.append(f"ANBIMA: sem a curva do DAP de {b3_dm(data_anb)} para medir o prêmio das indicativas dessa data.")
    elif not (anb.get("anterior") or {}).get("data"):
        ctx.lacunas.append(f"ANBIMA: sem o arquivo anterior ao de {b3_dm(data_anb)}"
                           + (f" ({anb['erro']})" if anb.get("erro") else "") + "; a variação da indicativa não foi medida.")
    elif anb.get("erro"):
        ctx.lacunas.append(f"ANBIMA: leitura incompleta nesta rodada ({anb['erro']}).")


def montar(ctx) -> dict:
    """Bloco `renda_fixa` do resumo. `ctx` e o Contexto de boletim/resumo.py."""
    t = ctx.tab("Trade")
    if not t:
        return {}
    cfg = ctx.cfg.get("renda_fixa") or {}
    piso = cfg.get("volume_minimo_rs", 500000)
    if t.get("truncada"):
        ctx.lacunas.append("Renda fixa: o negócio a negócio passou do teto de páginas; os totais do dia estão incompletos.")
    ajuste = f"{relogios.proximo_dia_util('B3', ctx.d).isoformat()}T11:00"
    preliminar = (t.get("atualizado_em") or "") < ajuste
    fonte_sinal = "Trade + InstrumentRegistration" + (" (preliminar)" if preliminar else "")
    por = agregar(b3.registros(t))
    cadastro = ctx.bruto.get("rf_cadastro") or {}
    estado = ctx.rf_estado
    dap = curva_dap(ctx.trades, ctx.d)

    # ---- ANBIMA: o arquivo que vale para este pregao e o publicado antes dele
    anb = ctx.bruto.get("anbima") or {}
    arq, arq_antes = anb.get("arquivo") or {}, anb.get("anterior") or {}
    ind, ind_antes, data_anb = arq.get("papeis") or {}, arq_antes.get("papeis") or {}, arq.get("data")
    no_dia = bool(data_anb) and data_anb == ctx.iso
    # o premio da indicativa e contra o juro real da mesma data: o DAP deste pregao ou o do pregao do arquivo
    dap_anb = dap if no_dia else [tuple(x) for x in anb.get("dap") or []]
    _lacunas_anbima(ctx, anb, data_anb, bool(dap_anb), (cfg.get("anbima") or {}).get("dias_atras", 3))

    def linha_de(cod: str, p: dict | None) -> dict:
        """O papel no pregao. `p` sao os negocios do dia na B3; None para o papel acompanhado que nao
        negociou e esta no arquivo da ANBIMA."""
        cad, a = cadastro.get(cod), ind.get(cod)
        tipo = p["tipo"] if p else ((cad or {}).get("tipo") or "DEB")
        a = a if tipo == "DEB" else None
        taxa = p["taxa_media"] if p else None
        conv_b3 = convencao(cad, taxa)
        conv = conv_b3 or (a or {}).get("convencao")
        venc = (cad or {}).get("vencimento") or (a or {}).get("repac_venc")
        anos = _anos(venc, ctx.d)
        linha = {"codigo": cod, "classe": classe(tipo, cad),
                 "emissor": p["emissor"] if p else ((cad or {}).get("emissor") or (a or {}).get("nome") or ""),
                 "negocios": p["negocios"] if p else 0, "volume_rs": p["volume_rs"] if p else 0.0,
                 "pu_medio": p["pu_medio"] if p else None, "taxa_media": taxa,
                 "taxa_min": p["taxa_min"] if p else None, "taxa_max": p["taxa_max"] if p else None,
                 "convencao": conv, "indexador": (cad or {}).get("indexador"),
                 "taxa_emissao": (cad or {}).get("taxa") if cad else (a or {}).get("taxa_emissao"),
                 "pct_indexador": (cad or {}).get("pct_indexador"), "vencimento": venc[:10] if venc else None, "prazo_anos": anos}
        if not p:
            linha["sem_negocio"] = True
        if conv == "IPCA+":
            pr = premio(taxa, dap, anos)
            if pr is not None:
                linha["premio_dap_pb"] = pr
        if p:
            d_ant, taxa_ant, _ = _anterior(estado, cod, ctx.iso)
            if taxa_ant is not None and taxa is not None and p["volume_rs"] >= piso and conv in COM_VARIACAO:
                linha["var_taxa_pb"], linha["comparado_com"] = round((taxa - taxa_ant) * 100.0), d_ant
        if a:
            x = indicativa(a, ind_antes.get(cod), data_anb, arq_antes.get("data"), dap_anb)
            if a.get("convencao") != conv:          # as duas fontes leem a taxa de jeitos diferentes: nao se comparam
                x["convencao"] = a.get("convencao")
            linha["anbima"] = x
            if conv == "IPCA+":
                pr = premio(taxa, dap, x["duration_anos"])
                if pr is not None:
                    linha["premio_dap_duration_pb"] = pr
        ref = _ref(linha, ctx.iso, bool(a) and a.get("convencao") == conv, no_dia)
        if ref:
            linha["ref"] = ref
        return linha

    linhas: dict = {cod: linha_de(cod, p) for cod, p in por.items()}

    # ---- totais por classe
    resumo: dict = {}
    for cl in ROTULO:
        ls = [l for l in linhas.values() if l["classe"] == cl]
        if not ls:
            continue
        vol = sum(l["volume_rs"] for l in ls)
        item = {"rotulo": ROTULO[cl], "papeis": len(ls), "negocios": sum(l["negocios"] for l in ls), "volume_rs": round(vol, 0),
                "emissores": len({l["emissor"] for l in ls})}
        item.update(_medias(ls, piso, _da_ref))
        fontes = _fontes(ls, piso)
        if fontes:
            item["taxa_fontes"] = fontes
        if fontes.get("anbima"):
            # com a indicativa na referencia, a media e a mediana dos negocios da B3 ficam ao lado
            item["negocios_do_dia"] = _medias(ls, piso, _da_b3)
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
                          f"{mil(item['volume_x_media'], 1)}x a média de {len(vols)} pregões.",
                          "Trade" + (" (preliminar)" if preliminar else ""), volume_rs=vol)
        resumo[cl] = item

    top = cfg.get("top", 20)
    papeis = {cl: sorted((l for l in linhas.values() if l["classe"] == cl), key=lambda l: -l["volume_rs"])[:top] for cl in EM_FOCO}
    foco = [l for l in linhas.values() if l["classe"] in EM_FOCO]

    # ---- papeis acompanhados: aparecem mesmo sem negocio no dia quando a ANBIMA traz a indicativa
    acompanhados = []
    for cod in cfg.get("papeis") or []:
        acompanhados.append(linhas.get(cod) or (linha_de(cod, None) if cod in ind else {"codigo": cod, "sem_negocio": True}))

    # ---- curva de credito incentivado: taxa de referencia x prazo (duration da ANBIMA quando ha)
    curva = []
    for l in linhas.values():
        r = l.get("ref") or {}
        if l["classe"] != "deb_incentivada" or l["convencao"] != "IPCA+" or r.get("taxa") is None or l["volume_rs"] < piso:
            continue
        # a indicativa entra no prazo medio do papel; se a ANBIMA nao deu a duration, o ponto nao tem lugar no eixo
        na_duration = r["fonte"] == "anbima"
        prazo = l["anbima"].get("duration_anos") if na_duration else l["prazo_anos"]
        if not prazo or prazo <= 0:
            continue
        ponto = {"codigo": l["codigo"], "emissor": l["emissor"], "anos": prazo, "taxa": r["taxa"], "volume_rs": l["volume_rs"],
                 "premio_dap_pb": r.get("premio_dap_pb"), "fonte": r["fonte"], "base": "duration" if na_duration else "vencimento"}
        if r["fonte"] == "anbima" and l["taxa_media"] is not None:
            ponto["taxa_b3"] = l["taxa_media"]
        curva.append(ponto)
    curva = sorted(curva, key=lambda x: -x["volume_rs"])[:cfg.get("curva_pontos", 140)]

    # ---- quem abriu e quem fechou taxa: primeiro pela indicativa da ANBIMA, depois pelos negocios da B3
    piso_mov = cfg.get("movimento_volume_minimo_rs", 3000000)
    piso_sinal = cfg.get("sinal_volume_minimo_rs", 5000000)
    parada = cfg.get("movimento_minimo_pb", 1.0)        # abaixo disso a taxa nao abriu nem fechou: ficou parada
    aberturas, fechamentos = [], []
    for fonte in ("anbima", "b3"):
        mov = [l for l in foco if l["volume_rs"] >= piso_mov and (l.get("ref") or {}).get("var_pb") is not None
               and l["ref"]["fonte"] == fonte]
        aberturas += sorted((l for l in mov if l["ref"]["var_pb"] >= parada), key=lambda l: -l["ref"]["var_pb"])[:8]
        fechamentos += sorted((l for l in mov if l["ref"]["var_pb"] <= -parada), key=lambda l: l["ref"]["var_pb"])[:8]

    def nome(l: dict) -> str:
        return f"{l['codigo']} ({b3.nome_curto(l['emissor'], 38)}, {SINGULAR.get(l['classe'], 'debênture')})"

    def negocios_do_dia(l: dict) -> str:
        if l.get("sem_negocio"):
            return f"sem negócio na B3 em {b3_dm(ctx.iso)}"
        if l["taxa_media"] is None:
            return f"R$ {mil(l['volume_rs'] / 1e6, 1)} mi negociados na B3 em {b3_dm(ctx.iso)}, sem taxa"
        return (f"na B3, negócios de {b3_dm(ctx.iso)} a {l['convencao']} {mil(l['taxa_media'], 2)}% "
                f"em R$ {mil(l['volume_rs'] / 1e6, 1)} mi")

    limite, avisados = cfg.get("var_taxa_sinal_pb", 30), set()

    def avisa_abertura(l: dict) -> None:
        r = l["ref"]
        if r["var_pb"] < limite or l["codigo"] in avisados:
            return
        avisados.add(l["codigo"])
        if r["fonte"] == "anbima":
            ctx.sinal("rf_abertura", l["codigo"],
                      f"{nome(l)}: a taxa indicativa da ANBIMA abriu {pb(r['var_pb'])} pb de {b3_dm(r['var_contra'])} para "
                      f"{b3_dm(r['data'])}, para {l['convencao']} {mil(r['taxa'], 2)}%; {negocios_do_dia(l)}.",
                      "taxa indicativa de debêntures", r["data"], origem="ANBIMA",
                      var_taxa_pb=r["var_pb"], taxa=r["taxa"], taxa_negocios=l["taxa_media"], volume_rs=l["volume_rs"])
        else:
            ctx.sinal("rf_abertura", l["codigo"],
                      f"{nome(l)}: taxa média dos negócios da B3 abriu {pb(r['var_pb'])} pb contra {b3_dm(r['var_contra'])}, "
                      f"para {l['convencao']} {mil(r['taxa'], 2)}%, em R$ {mil(l['volume_rs'] / 1e6, 1)} mi.", fonte_sinal,
                      var_taxa_pb=r["var_pb"], taxa=r["taxa"], volume_rs=l["volume_rs"])

    for fonte in ("anbima", "b3"):
        for l in [l for l in aberturas if l["ref"]["fonte"] == fonte and l["volume_rs"] >= piso_sinal][:3]:
            avisa_abertura(l)
    # a indicativa nao depende do volume do dia: papel acompanhado avisa mesmo com giro pequeno ou sem negocio
    for l in acompanhados:
        r = l.get("ref") or {}
        if r.get("fonte") == "anbima" and r.get("var_pb") is not None:
            avisa_abertura(l)

    # ---- taxas mais altas: onde o mercado esta pedindo premio
    lim_premio, lim_cdi = cfg.get("premio_estresse_pb", 300), cfg.get("cdi_estresse", 5.0)
    estresse = sorted((l for l in foco if l["volume_rs"] >= piso_mov and (
        (_da_ref(l)[1] or 0) >= lim_premio or (l["convencao"] == "CDI+" and (_da_ref(l)[0] or 0) >= lim_cdi))),
        key=lambda l: -(_da_ref(l)[1] or (_da_ref(l)[0] or 0) * 100))[:10]
    for l in [l for l in estresse if l["volume_rs"] >= piso_sinal][:3]:
        r = l["ref"]
        if r["fonte"] == "anbima":
            onde = (f"na duration de {mil(l['anbima']['duration_anos'], 1)} anos" if r.get("premio_base") == "duration"
                    else "de prazo equivalente")
            extra = (f", {mil(r['premio_dap_pb'])} pb acima do juro real de mercado {onde}" if r.get("premio_dap_pb") is not None else "")
            ctx.sinal("rf_premio_alto", l["codigo"],
                      f"{nome(l)}: taxa indicativa da ANBIMA de {b3_dm(r['data'])} a {l['convencao']} {mil(r['taxa'], 2)}%{extra}; "
                      f"{negocios_do_dia(l)}.", "taxa indicativa de debêntures (ANBIMA) e DAP (B3)", r["data"], origem="ANBIMA e B3",
                      taxa=r["taxa"], premio_dap_pb=r.get("premio_dap_pb"), premio_base=r.get("premio_base"),
                      taxa_negocios=l["taxa_media"], volume_rs=l["volume_rs"])
        else:
            extra = (f", {mil(r['premio_dap_pb'])} pb acima do juro real de mercado de prazo equivalente"
                     if r.get("premio_dap_pb") is not None else "")
            ctx.sinal("rf_premio_alto", l["codigo"],
                      f"{nome(l)}: negociada a {l['convencao']} {mil(r['taxa'], 2)}%{extra}, em R$ {mil(l['volume_rs'] / 1e6, 1)} mi.",
                      fonte_sinal, taxa=r["taxa"], premio_dap_pb=r.get("premio_dap_pb"), volume_rs=l["volume_rs"])

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
        e = inc.setdefault(l["emissor"], {"emissor": l["emissor"], "volume_rs": 0.0, "negocios": 0, "papeis": 0, "_ls": []})
        e["volume_rs"] += l["volume_rs"]
        e["negocios"] += l["negocios"]
        e["papeis"] += 1
        e["_ls"].append(l)
    emissores_inc = sorted(inc.values(), key=lambda e: -e["volume_rs"])[:10]
    for e in emissores_inc:
        ls = e.pop("_ls")
        m = _medias(ls, piso, _da_ref)
        e["taxa_ipca_media"], e["premio_dap_medio_pb"] = m.get("taxa_ipca_media"), m.get("premio_dap_medio_pb")
        fontes = _fontes([l for l in ls if l["convencao"] == "IPCA+"], piso)
        if fontes:
            e["taxa_fontes"] = fontes
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

    # ---- de onde vieram as indicativas e quanto do dia elas cobrem
    meta = {"fonte": anbima.FONTE, "pedido": ctx.iso, "situacao": anb.get("situacao") or "nao coletado"}
    if arq:
        incentivadas = [l for l in linhas.values() if l["classe"] == "deb_incentivada"]
        vol_inc = sum(l["volume_rs"] for l in incentivadas)
        vol_ind = sum(l["volume_rs"] for l in incentivadas if (l.get("ref") or {}).get("fonte") == "anbima")
        meta.update(data=data_anb, publicado_em=arq.get("publicado_em"), papeis=len(ind), url=arq.get("url"),
                    comparado_com=arq_antes.get("data"),
                    cobertura_incentivadas_pct=round(vol_ind / vol_inc * 100.0, 1) if vol_inc else None)
        if not no_dia and dap_anb:
            meta["dap"] = [[a, tx, tk] for a, tx, tk in dap_anb]
    for chave in ("tentativas", "erro"):
        if anb.get(chave):
            meta[chave] = anb[chave]

    return {
        "data": ctx.iso, "fonte": ctx.fonte("Trade"), "preliminar": preliminar, "anbima": meta,
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
        "nota": "Debêntures: a taxa de referência (`ref`) é a indicativa da ANBIMA quando há, com o prêmio sobre o DAP medido na "
                "duration (sem prêmio quando a duration é menor que um ano); a média dos negócios da B3 fica ao lado (`taxa_media`). "
                "CRI e CRA: só negócios da B3, que informa a securitizadora, não o devedor; prêmio sobre o DAP por vencimento, "
                "que é aproximação.",
        "_linhas": linhas,
    }


def b3_dm(iso) -> str:
    return f"{str(iso)[8:10]}/{str(iso)[5:7]}" if iso else "?"


def atualizar_estado(estado: dict, rf: dict, iso: str, piso: float = 500000, dias: int = 75, guardar: int = 3) -> dict:
    """Ultimas taxas dos negocios da B3 vistas por papel (ate `guardar` pregoes), para medir abertura e
    fechamento onde nao ha indicativa. A variacao da indicativa sai de dois arquivos da ANBIMA."""
    novo = {k: [list(x) for x in v] for k, v in (estado or {}).items()}
    for cod, l in (rf.get("_linhas") or {}).items():
        if l.get("classe") not in EM_FOCO or l.get("taxa_media") is None or l.get("volume_rs", 0) < piso:
            continue
        obs = [x for x in novo.get(cod, []) if x[0] != iso] + [[iso, l["taxa_media"], l.get("pu_medio")]]
        novo[cod] = sorted(obs)[-guardar:]
    corte = date.fromordinal(date.fromisoformat(iso).toordinal() - dias).isoformat()
    return {k: v for k, v in sorted(novo.items()) if v and v[-1][0] >= corte}
