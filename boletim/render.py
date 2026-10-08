"""resumo.json -> resumo.md: a leitura do boletim em cards, pronta para a sessao colar.

Formato da casa: tabelas de ate 4 colunas (o Douglas le no celular), numero brasileiro,
sigla explicada na primeira vez, `[[LEITURA_DA_MESA]]` no lugar da manchete que a sessao
escreve. Aqui nao ha opiniao: so o que o boletim trouxe, com a data de cada bloco.
Texto de tela leva acento; o resto do arquivo segue a convencao do repositorio.
"""

from __future__ import annotations

from datetime import date

from boletim import renda_fixa

DIAS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
ROTULO_INVESTIDOR = {"estrangeiro": "Estrangeiro", "institucional": "Institucional (fundos)",
                     "pessoa_fisica": "Pessoa física", "inst_financeira": "Bancos e corretoras", "outros": "Outros"}
ROTULO_SINAL = {
    "volume_anormal": "Volume fora do padrão", "aluguel_variacao": "Aluguel mudou", "pressao_vendida": "Pressão vendida",
    "zeragem_de_vendidos": "Vendidos zerando", "aluguel_alto": "Aluguel alto", "aluguel_caro": "Aluguel caro",
    "opcoes_parede": "Parede de opções", "etf_premio": "ETF fora do valor da cota", "etf_cotas": "Criação ou resgate de cotas",
    "provento": "Provento", "subscricao": "Subscrição", "lista_do_dia": "Listas do dia", "fluxo_estrangeiro": "Fluxo estrangeiro",
    "posicao_em_aberto": "Posição em aberto", "juros": "Juros", "previa_indice": "Prévia de índice",
    "informativo": "Comunicado", "after_market": "After market", "paridade": "Paridade",
    "opcoes_posicao": "Posição em opções", "rf_abertura": "Crédito: taxa abriu", "rf_premio_alto": "Crédito: prêmio alto",
    "rf_giro": "Crédito: giro",
}
ROTULO_RF = {"deb_incentivada": "Debêntures incentivadas", "cri": "CRI", "cra": "CRA"}
NOME_PENDENTE = {
    "TradeInformationConsolidated": "negócios do pregão", "TradeInformationConsolidatedAfterHours": "negócios do after market",
    "InstrumentsConsolidated": "cadastro de instrumentos", "DerivativesOpenPosition": "posições em aberto (opções e futuros)",
    "BTBLendingOpenPosition": "saldo de aluguel", "BTBLoanBalance": "empréstimos do dia",
    "AnalyticalFramework2": "quadro de posições em aberto", "SharesInvesVolum": "fluxo por tipo de investidor",
    "BTBTrade": "aluguel por corretora", "Trade": "negócios de renda fixa",
}
NOME_INDICE = {"IBOVESPA": "Ibovespa", "SMALL CAP": "Small caps (SMLL)", "IFINANCEIRO": "Financeiro (IFNC)",
               "UTILITIES": "Utilidade pública (UTIL)", "IMOBILIARIO": "Imobiliário (IMOB)", "I DIVIDENDOS": "Dividendos (IDIV)",
               "IEE": "Energia elétrica (IEE)", "IMATBASICOS": "Materiais básicos (IMAT)", "IFIX": "Fundos imobiliários (IFIX)",
               "BDRX": "BDRs (BDRX)"}
NOME_GRUPO = {"construtoras": "Construtoras", "utilities": "Utilities", "bancos": "Bancos", "commodities": "Commodities",
              "consumo_e_distribuicao": "Consumo e distribuição", "etfs": "ETFs"}


def n(v, casas: int = 2, sinal: bool = False) -> str:
    if v is None:
        return "-"
    s = f"{v:+,.{casas}f}" if sinal else f"{v:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def p(v, casas: int = 2) -> str:
    return "-" if v is None else n(v, casas, sinal=True) + "%"


def dm(iso) -> str:
    return "-" if not iso else f"{str(iso)[8:10]}/{str(iso)[5:7]}"


def tabela(cab: list[str], linhas: list[list[str]]) -> list[str]:
    if not linhas:
        return []
    out = ["| " + " | ".join(cab) + " |", "|" + "|".join(["---"] + ["---:"] * (len(cab) - 1)) + "|"]
    out += ["| " + " | ".join(l) + " |" for l in linhas]
    return out + [""]


def _sinais(r: dict) -> list[str]:
    o = [f"## Sinais do dia ({len(r['sinais'])})", ""]
    if not r["sinais"]:
        return o + ["Nenhum sinal passou dos limiares de config/boletim.yaml.", ""]
    novos = [s for s in r["sinais"] if s.get("pregoes_seguidos", 1) == 1]
    velhos = [s for s in r["sinais"] if s.get("pregoes_seguidos", 1) > 1]
    for titulo, grupo in (("Novos hoje", novos), ("Já vinham de pregões anteriores", velhos)):
        if not grupo:
            continue
        o += [f"**{titulo}**", ""]
        for s in grupo:
            seg = f" · {s['pregoes_seguidos']}º pregão seguido" if s.get("pregoes_seguidos", 1) > 1 else ""
            o.append(f"- **{ROTULO_SINAL.get(s['tipo'], s['tipo'])}.** {s['texto']} "
                     f"_({s.get('origem') or 'B3'}, {s['fonte']}, {dm(s['data'])}{seg})_")
        o.append("")
    return o


def _futuros(fut: dict, vertices: list[str]) -> list[list[str]]:
    linhas = []
    for a in ("DI1", "DAP", "DOL", "IND"):
        itens = fut.get(a) or {}
        if a == "DI1":
            fica = [tk for tk in itens if tk in vertices] or list(itens)[:4]
        elif a == "DAP":
            fica = sorted(itens, key=lambda k: -(itens[k].get("contratos") or 0))[:2]
        else:
            fica = list(itens)[:1]
        for tk in fica:
            v = itens[tk]
            if v.get("taxa") is not None:
                nivel, var = n(v["taxa"], 3) + "%", (n(v.get("var_bps"), 1, True) + " pb" if v.get("var_bps") is not None else "-")
            else:
                nivel, var = n(v.get("ajuste"), 2), p(v.get("var_pct"))
            linhas.append([tk, nivel, var, n(v.get("em_aberto"), 0)])
    return linhas


def compacto(v) -> str:
    if v is None:
        return "-"
    for limite, sufixo in ((1e9, " bi"), (1e6, " mi"), (1e3, " mil")):
        if abs(v) >= limite:
            return n(v / limite, 1) + sufixo
    return n(v, 0)


def _taxa(t, c) -> str:
    if t is None:
        return "sem taxa"
    if c == "% do CDI":
        return f"{n(t, 1)}% do CDI"
    return f"{n(t, 2)}% pré" if c == "Pré" else f"{c or ''} {n(t, 2)}%"


def _taxa_rf(l: dict) -> str:
    """A taxa dos negocios do dia na B3."""
    return _taxa(l.get("taxa_media"), l.get("convencao"))


def _pb(v) -> str:
    """Pontos-base com sinal: inteiro quando e inteiro, uma casa quando nao (a indicativa anda em decimos)."""
    return ("0" if not v else n(v, 0 if float(v).is_integer() else 1, True)) + " pb"


def _renda_fixa(r: dict) -> list[str]:
    rf = r.get("renda_fixa") or {}
    if not rf.get("resumo"):
        return []
    pregao, anb = r["pregao"], rf.get("anbima") or {}
    b3_de = f"B3 negócios de {dm(pregao)}"

    def ref_de(l: dict) -> dict:
        return renda_fixa.referencia(l, pregao)

    def referencia(l: dict) -> str:
        """'IPCA+ 8,19% (ANBIMA indicativa de 30/09)': a taxa que vale para o papel, com a fonte e o dia."""
        ref = ref_de(l)
        return f"{_taxa(ref.get('taxa'), l.get('convencao'))} ({renda_fixa.rotulo_fonte(ref)})" if ref else "sem taxa"

    def premio(l: dict) -> str:
        ref = ref_de(l)
        if ref.get("premio_dap_pb") is None:
            return "-"
        return _pb(ref["premio_dap_pb"]) + (" na duration" if ref.get("premio_base") == "duration" else " no vencimento")

    def negocios(l: dict) -> str:
        """Os negocios do dia na B3, ao lado da indicativa; sem ela a taxa dos negocios ja e a referencia."""
        if l.get("sem_negocio"):
            return "sem negócio"
        giro = "R$ " + compacto(l.get("volume_rs"))
        return f"{_taxa_rf(l)}, {giro}" if ref_de(l).get("fonte") == "anbima" else giro

    o = ["## Renda fixa: debêntures incentivadas, CRI e CRA", ""]
    if rf.get("preliminar"):
        o += ["**Preliminar:** a B3 ajusta os negócios de balcão no dia seguinte; volumes e taxas dos negócios deste pregão ainda podem mudar.", ""]
    if anb.get("data"):
        fonte = (f"**De onde vem cada taxa:** debêntures pela taxa indicativa da ANBIMA de {dm(anb['data'])} ({n(anb.get('papeis'), 0)} papéis), "
                 f"com os negócios da B3 de {dm(pregao)} ao lado; CRI e CRA só pelos negócios da B3.")
        if anb["data"] != pregao:
            fonte += f" Sem o arquivo da ANBIMA de {dm(pregao)} até esta coleta: a variação do dia pela indicativa não foi medida."
    elif anb:
        fonte = (f"**De onde vem cada taxa:** sem taxa indicativa da ANBIMA nesta rodada ({anb.get('situacao')}); "
                 f"debêntures, CRI e CRA pelos negócios da B3 de {dm(pregao)}.")
    else:
        fonte = f"**De onde vem cada taxa:** negócios da B3 de {dm(pregao)}."
    o += [fonte, ""]
    linhas = []
    for cl, rot in ROTULO_RF.items():
        v = rf["resumo"].get(cl)
        if v:
            taxas = ([f"IPCA+ {n(v['taxa_ipca_mediana'])}%"] if v.get("taxa_ipca_mediana") is not None else []) + \
                    ([f"CDI+ {n(v['premio_cdi_mediano'])}%"] if v.get("premio_cdi_mediano") is not None else [])
            taxa = " e ".join(taxas) or "-"
            premio_cl = (n(v["premio_dap_mediano_pb"], 0, True) + " pb") if v.get("premio_dap_mediano_pb") is not None else "-"
            linhas.append([rot, "R$ " + compacto(v.get("volume_rs")), taxa, premio_cl])
    o += tabela(["Classe", "Volume do dia", "Taxa mediana", "Sobre o juro real"], linhas)
    do_dia = (rf["resumo"].get("deb_incentivada") or {}).get("negocios_do_dia") or {}
    if do_dia.get("taxa_ipca_mediana") is not None:
        o += [f"Nas incentivadas, a mediana pelos negócios do dia ({b3_de}) foi IPCA+ {n(do_dia['taxa_ipca_mediana'])}%.", ""]
    todos = rf.get("acompanhados") or []
    meus = [l for l in todos if ref_de(l) or not l.get("sem_negocio")]
    if todos:
        o += ["**Papéis acompanhados (config/boletim.yaml)**", ""]
    if meus:
        o += tabela(["Papel", "Taxa de referência", b3_de, "Sobre o juro real"],
                    [[l["codigo"] + (f" ({l['apelido']})" if l.get("apelido") else ""), referencia(l), negocios(l), premio(l)] for l in meus])
    itens = []
    for l in todos:
        a = l.get("anbima")
        if not a:
            continue
        if a.get("convencao"):          # so vem quando a ANBIMA e a B3 leem a taxa de jeitos diferentes
            itens.append(f"- {l['codigo']}, ANBIMA de {dm(a.get('data'))}: indicativa a {_taxa(a.get('indicativa'), a['convencao'])}, em convenção "
                         f"diferente da dos negócios da B3 ({l.get('convencao')}); as duas taxas não se comparam e vale a dos negócios.")
            continue
        do_cdi = " do CDI" if l.get("convencao") == "% do CDI" else ""
        partes = [f"compra {n(a['compra'])}%{do_cdi} e venda {n(a['venda'])}%{do_cdi}" if a.get("compra") is not None and a.get("venda") is not None else "",
                  f"PU R$ {n(a['pu'])}" + (f" ({n(a['pct_pu_par'], 1)}% do par)" if a.get("pct_pu_par") is not None else "") if a.get("pu") is not None else "",
                  (f"duration de {n(a['duration_anos'], 1)} anos" if a["duration_anos"] >= 1.0
                   else f"duration de {n(a['duration_anos'], 2)} ano (curta demais para medir o prêmio sobre o DAP)") if a.get("duration_anos") else "",
                  f"indicativa {_pb(a['var_pb'])} contra {dm(a.get('comparado_com'))}" if a.get("var_pb") is not None else ""]
        partes = [x for x in partes if x]
        itens.append(f"- {l['codigo']}, ANBIMA de {dm(a.get('data'))}: " + ("; ".join(partes) + "." if partes else "o arquivo lista o papel sem taxa nem preço."))
    if itens:
        o += itens + [""]
    sem = [l["codigo"] for l in todos if l not in meus]
    if sem:
        o += [f"Sem negócio neste pregão e sem taxa indicativa: {', '.join(sem)}.", ""]
    top = (rf.get("papeis") or {}).get("deb_incentivada") or []
    if top:
        o += ["**Debêntures incentivadas mais negociadas**", ""]
        o += tabela(["Papel", "Taxa de referência", b3_de, "Sobre o juro real"],
                    [[f"{l['codigo']} ({l['emissor'].title()[:28]})", referencia(l), negocios(l), premio(l)] for l in top[:8]])
    for fonte_mov, rotulo in (("anbima", "pela indicativa da ANBIMA"), ("b3", "pelos negócios da B3")):
        for chave, titulo in (("aberturas", "Abriram taxa"), ("fechamentos", "Fecharam taxa")):
            itens = [l for l in rf.get(chave) or [] if ref_de(l).get("fonte") == fonte_mov]
            if itens:
                o.append(f"**{titulo} {rotulo}:** " + "; ".join(
                    f"{l['codigo']} {_pb(ref_de(l)['var_pb'])} contra {dm(ref_de(l).get('var_contra'))}, para "
                    f"{_taxa(ref_de(l).get('taxa'), l.get('convencao'))} (R$ {compacto(l['volume_rs'])})" for l in itens[:5]) + ".")
    if rf.get("premios_altos"):
        o.append("**Prêmio alto:** " + "; ".join(
            f"{l['codigo']} a {referencia(l)}" + (f", {premio(l)}" if ref_de(l).get("premio_dap_pb") is not None else "")
            + f", R$ {compacto(l['volume_rs'])}" for l in rf["premios_altos"][:5]) + ".")
    o += ["", "Por classe, mediana das taxas de referência dos papéis. Taxa de referência: nas debêntures, a indicativa da ANBIMA quando há; "
          "nos demais papéis, a média dos negócios da B3 ponderada pelo volume. Juro real = DAP (cupom de IPCA) da mesma data: na duration "
          "do papel quando a taxa é a indicativa, no vencimento quando é a dos negócios (aproximação). Em CRI e CRA a B3 informa a "
          "securitizadora.", ""]
    return o


def _radar(r: dict) -> list[str]:
    rad, om, corr = r.get("radar") or {}, r.get("opcoes_mercado") or {}, r.get("aluguel_corretoras") or {}
    o = []
    if rad.get("aluguel_float"):
        o += ["## Radar do mercado: aluguel", ""]
        o += tabela(["Mais alugadas", "% das ações", "Taxa", "Preço em 5 pregões"],
                    [[l["ativo"], n(l.get("pct_free_float"), 1) + "%", (n(l.get("taxa")) + "%") if l.get("taxa") is not None else "-",
                      p(l.get("preco_5d_pct"))] for l in rad["aluguel_float"][:6]])
        if rad.get("aluguel_taxa"):
            o.append("**Aluguel mais caro (taxa ao ano):** " + ", ".join(f"{l['ativo']} {n(l['taxa'])}%" for l in rad["aluguel_taxa"][:6]) + ".")
        for chave, titulo in (("aluguel_alta", "Saldo alugado que mais subiu no pregão"), ("aluguel_queda", "Saldo que mais caiu"),
                              ("vendidos_pressionados", "Vendidos sob pressão (muito alugadas, preço subindo)"),
                              ("aposta_vendida_crescendo", "Aposta vendida crescendo (aluguel subindo, preço caindo)")):
            if rad.get(chave):
                campo = "aluguel_var_dia_pct" if chave.startswith("aluguel_") else "preco_5d_pct"
                o.append(f"**{titulo}:** " + ", ".join(f"{l['ativo']} {p(l.get(campo), 1)}" for l in rad[chave][:6]) + ".")
        o.append("")
    if rad.get("volume"):
        o += ["**Volume fora do padrão no mercado:** " + ", ".join(
            f"{l['ativo']} {n(l['volume_x_media'], 1)}x ({p(l.get('oscilacao_pct'))})" for l in rad["volume"][:8]) + ".", ""]
    if corr.get("tomadoras"):
        o += ["**Corretoras no aluguel do dia** (intermediário, não investidor final): lado tomador "
              + ", ".join(f"{x[0]} {n(x[2], 0)}%" for x in corr["tomadoras"][:4]) + "; lado doador "
              + ", ".join(f"{x[0]} {n(x[2], 0)}%" for x in corr["doadoras"][:4]) + ".", ""]
    if om.get("por_ativo"):
        o += ["## Opções: o mercado inteiro", "",
              f"Posição em aberto: {compacto(om.get('posicao_call'))} de calls e {compacto(om.get('posicao_put'))} de puts "
              f"(put/call {n(om.get('put_call'))}); no volume do dia, put/call {n(om.get('put_call_volume'))}.", ""]
        o += tabela(["Ativo", "Calls", "Puts", "Put/call"],
                    [[a["ativo"], compacto(a["call"]), compacto(a["put"]), n(a.get("put_call"))] for a in om["por_ativo"][:8]])
        for chave, titulo in (("maiores_altas", "Séries que mais ganharam posição"), ("maiores_quedas", "Séries que mais perderam posição")):
            if om.get(chave):
                o.append(f"**{titulo}:** " + "; ".join(
                    f"{m['codigo']} ({m['ativo']}, {m['tipo']}, strike {n(m.get('strike'))}) {n(m['variacao'] / 1e6, 2, True)} mi" for m in om[chave][:4]) + ".")
        o.append("")
    return o


def markdown(r: dict) -> str:
    d = date.fromisoformat(r["pregao"])
    sit = r["situacao"]
    o: list[str] = [f"# Boletim da B3: pregão de {d.strftime('%d/%m/%Y')} ({DIAS[d.weekday()]})", ""]
    if sit["completo"]:
        o.append(f"**Situação: COMPLETO.** Boletim {sit.get('boletim') or '?'} pela B3 em "
                 f"{str(sit.get('boletim_atualizado_em') or '?')[:16].replace('T', ' ')} (hora de Brasília).")
    else:
        falta = ", ".join(NOME_PENDENTE.get(x, x) for x in sit["faltam"])
        o.append(f"**Situação: PARCIAL.** Ainda sem: {falta}. A B3 publica esses blocos na madrugada seguinte ao pregão; "
                 f"a rodada da manhã completa.")
    o += [f"Fonte: {r['fonte']}. Gerado em {r['gerado_em']} (UTC).", "", "[[LEITURA_DA_MESA]]", ""]
    o += _sinais(r)

    # ---- indices e giro
    mer, ind, tri = r.get("mercado") or {}, r.get("indices") or {}, r.get("triangulacao") or {}
    linhas = [[NOME_INDICE.get(nome, nome), n(v.get("fechamento"), 0), p(v.get("dia_pct")), p(v.get("mes_pct"))]
              for nome, v in ind.items()]
    if linhas:
        o += ["## Índices", ""] + tabela(["Índice", "Fechamento", "Dia", "No mês"], linhas)
    if mer.get("dia"):
        o += ["## Giro do mercado de ações", ""]
        o += tabela(["", "Dia", "Média do mês", "Dia / média"],
                    [["Volume (R$ mi)", n(mer["dia"].get("volume_mi"), 0), n((mer.get("media_mes") or {}).get("volume_mi"), 0),
                      n(mer.get("volume_x_media_mes")) + "x"],
                     ["Negócios (mil)", n((mer["dia"].get("negocios") or 0) / 1e3, 0),
                      n(((mer.get("media_mes") or {}).get("negocios") or 0) / 1e3, 0), "-"]])
        seg = mer.get("segmentos") or {}
        partes = [f"{rot} R$ {n(seg[k].get('volume_mi'), 0)} mi" for k, rot in
                  (("a_vista", "à vista"), ("opcoes", "opções"), ("termo", "termo"), ("after_market", "after market")) if seg.get(k)]
        if partes:
            o += ["Mercado de ações = à vista, opções e termo (médias diárias da B3). No dia: " + ", ".join(partes) + ".", ""]

    # ---- fluxo
    f = r.get("fluxo") or {}
    if f.get("acumulado_no_mes"):
        per = f.get("periodo") or {}
        o += [f"## Fluxo por tipo de investidor (acumulado no mês até {dm(f.get('ate'))})", ""]
        if per:
            cab3 = f"Saldo em {dm(per['ate'])}" if per.get("de") == per.get("ate") else f"Saldo de {dm(per.get('de'))} a {dm(per.get('ate'))}"
        else:
            cab3 = "Saldo do último dia"
        linhas = [[ROTULO_INVESTIDOR.get(k, k), n(v["saldo_mi"], 0, True),
                   n((per.get("saldo_mi") or {}).get(k), 0, True) if per else "-",
                   n(v.get("part_compras_pct"), 1) + "%" if v.get("part_compras_pct") is not None else "-"]
                  for k, v in f["acumulado_no_mes"].items()]
        o += tabela(["Investidor", "Saldo no mês (R$ mi)", cab3 + " (R$ mi)", "Fatia das compras"], linhas)
        o += ["Saldo = compras menos vendas, somando todos os mercados da B3. A B3 divulga com dois pregões de atraso.", ""]

    # ---- futuros e posicoes
    der = r.get("derivativos") or {}
    linhas = _futuros(der.get("futuros") or {}, list((tri.get("di_var_bps") or {}).keys())
                      or ["DI1F27", "DI1F28", "DI1F29", "DI1F30", "DI1F32", "DI1F35"])
    if linhas:
        o += ["## Futuros: juros, dólar e índice", ""]
        o += tabela(["Contrato", "Ajuste", "Variação", "Contratos em aberto"], linhas)
        o += ["DI1 = DI futuro (taxa prefixada); DAP = cupom de IPCA (juro real); DOL = dólar futuro; IND = Ibovespa futuro. "
              "pb = ponto-base (0,01 ponto percentual).", ""]
    if der.get("quadro"):
        o += ["## Posições em aberto por mercado (futuros)", ""]
        o += tabela(["Mercado", "Contratos", "Variação no pregão", "Referencial (R$ mi)"],
                    [[a, n(v.get("contratos"), 0), p(v.get("var_contratos_pct")), n(v.get("referencial_mi"), 0)]
                     for a, v in der["quadro"].items()])

    # ---- grupos
    if tri.get("grupos"):
        o += ["## O livro em blocos", ""]
        o += tabela(["Grupo", "Média do dia", "Ativos"],
                    [[NOME_GRUPO.get(g, g), p(v["media_pct"]), ", ".join(f"{tk} {p(x)}" for tk, x in v["ativos"].items())]
                     for g, v in tri["grupos"].items()])
        di = tri.get("di_var_bps") or {}
        if di:
            o += ["Juros no mesmo dia: " + ", ".join(f"{tk} {n(v, 1, True)} pb" for tk, v in di.items()) + ".", ""]

    # ---- livro: negocios
    at = r.get("ativos") or {}
    linhas = []
    for tk, a in at.items():
        g = a.get("negocios")
        if g:
            x, mi = g.get("volume_x_media"), (g.get("volume_rs") or 0) / 1e6
            linhas.append([tk, n(g.get("fechamento")), p(g.get("oscilacao_pct")), n(mi, 0 if mi >= 10 else 1) + (f" ({n(x)}x)" if x else "")])
    if linhas:
        o += ["## Livro: negócios do dia", ""]
        o += tabela(["Ativo", "Fechamento (R$)", "Dia", "Volume em R$ mi (x média)"], linhas)
        o += ["x média = volume do dia dividido pela média dos pregões anteriores no histórico (até 20).", ""]

    # ---- livro: aluguel
    linhas = []
    for tk, a in at.items():
        g = a.get("aluguel")
        if g and g.get("saldo_qtd") is not None:
            mi = g["saldo_qtd"] / 1e6
            linhas.append([tk, n(mi, 1 if mi >= 1 else 2) + (f" ({n(g['pct_free_float'], 1)}%)" if g.get("pct_free_float") is not None else ""),
                           p(g.get("var_dia_pct")), (n(g.get("taxa_tomador_media")) + "%") if g.get("taxa_tomador_media") is not None else "-"])
    if linhas:
        o += ["## Livro: aluguel de ações", ""]
        o += tabela(["Ativo", "Saldo alugado em mi de ações (% do free float)", "Variação no pregão", "Taxa do tomador (ao ano)"], linhas)
        o += ["Aluguel de ações (BTC, o banco de títulos da B3): quem aluga normalmente vende a descoberto, então o saldo mede a "
              "aposta vendida. Free float aqui é a quantidade teórica da carteira de índice.", ""]

    # ---- livro: opcoes
    linhas = []
    for tk, a in at.items():
        g = a.get("opcoes") or {}
        for v in (g.get("vencimentos") or [])[:1]:
            pc, pp = v.get("parede_call") or {}, v.get("parede_put") or {}
            linhas.append([f"{tk} ({dm(v['vencimento'])})",
                           f"{n(pc.get('strike'))} ({p(pc.get('distancia_pct'), 1)})" if pc else "-",
                           f"{n(pp.get('strike'))} ({p(pp.get('distancia_pct'), 1)})" if pp else "-",
                           n(g.get("put_call"))])
    if linhas:
        o += ["## Livro: opções (vencimento relevante mais próximo)", ""]
        o += tabela(["Ativo (vencimento)", "Parede de call: strike (distância)", "Parede de put: strike (distância)", "Put/call"], linhas)
        o += ["Parede = strike (preço de exercício) com a maior posição em aberto fora do dinheiro: call acima do preço (teto), "
              "put abaixo (piso); distância é contra o fechamento. "
              "Put/call = posição em aberto de puts dividida pela de calls, todos os vencimentos. Call = opção de compra; put = de venda.", ""]

    # ---- ETFs e paridade
    linhas = []
    for tk, a in at.items():
        e = a.get("etf")
        if e:
            linhas.append([tk, n(e.get("iopv")), p(e.get("premio_pct")),
                           ("0" if not e["var_cotas"] else n(e["var_cotas"], 0, True)) if e.get("var_cotas") is not None else "-"])
    if linhas:
        o += ["## ETFs do livro", ""]
        o += tabela(["ETF", "Valor de referência da cota (IOPV)", "Prêmio ou desconto", "Cotas criadas no dia"], linhas)
    for x in r.get("paridades") or []:
        o.append(f"- Paridade: {x['ativo']} {p(x['oscilacao_pct'])} contra {x['referencia']} em reais {p(x['referencia_em_reais_pct'])} "
                 f"(lá fora {p(x['referencia_pct'])}, câmbio {p(x['cambio_pct'])}); desvio de {p(x['desvio_pct'])}. "
                 f"Fechamentos em horários diferentes: é aproximação.")
    if r.get("paridades"):
        o.append("")

    # ---- ADR
    linhas = [[tk, n(a["adr"]["acoes_em_adr"] / 1e6, 1), n(a["adr"].get("pct_da_classe"), 1) + "%" if a["adr"].get("pct_da_classe") is not None else "-",
               n((a["adr"].get("var") or 0) / 1e6, 2, True) if a["adr"].get("var") is not None else "-"]
              for tk, a in at.items() if a.get("adr") and (a["adr"].get("pct_da_classe") or 0) >= 0.5]
    if linhas:
        o += ["## Ações do livro em programa de ADR", ""]
        o += tabela(["Ativo", "Ações em ADR (mi)", "% da classe", "Variação no pregão (mi)"], linhas)
        o += ["ADR = recibo da ação negociado em Nova York. Ações entrando no programa indicam compra lá fora; saindo, venda.", ""]

    o += _radar(r)
    o += _renda_fixa(r)

    # ---- eventos
    ev = r.get("eventos") or {}
    itens = [f"- {x['ativo']}: {(x.get('tipo') or 'provento').lower()}"
             + (f" de R$ {n(x['valor'], 4)}, crédito em {dm(x.get('credito_em'))}" if x.get("valor") is not None
                else f", prazo em {dm(x.get('prazo_deposito'))}")
             for x in ev.get("proventos") or []]
    itens += [f"- {x['ativo']}: subscrição, prazo final em {dm(x.get('prazo_subscricao'))}" for x in ev.get("subscricoes") or []]
    itens += [f"- Comunicado ({dm(x.get('data'))}): {x['titulo']}" + (f" **[{', '.join(x['ativos_do_livro'])}]**" if x.get("ativos_do_livro") else "")
              for x in r.get("informativos") or []]
    if r.get("previa_indice"):
        pv = r["previa_indice"]
        itens.append(f"- {pv['previa']}ª prévia do Ibovespa: entram {', '.join(pv['entram']) or 'ninguém'}; saem {', '.join(pv['saem']) or 'ninguém'}")
    if itens:
        o += ["## Eventos e comunicados", ""] + itens + [""]

    # ---- renda fixa na plataforma eletronica (ETFs de renda fixa e papeis listados)
    rf = r.get("renda_fixa_puma") or {}
    if rf.get("negocios_puma"):
        o += [f"## Renda fixa na plataforma eletrônica ({rf['papeis_negociados']} papéis, R$ {n(rf['volume_total_rs'] / 1e6, 1)} mi)", ""]
        o += tabela(["Papel", "Último", "Negócios", "Volume (R$ mil)"],
                    [[x["codigo"], n(x.get("ultimo")), n(x.get("negocios"), 0), n((x.get("volume_rs") or 0) / 1e3, 0)] for x in rf["negocios_puma"][:6]])

    # ---- lacunas
    o += ["## Lacunas e pendências", ""]
    for k, v in (sit.get("pendentes") or {}).items():
        o.append(f"- {NOME_PENDENTE.get(k, k)}: {v}")
    if sit.get("publicadas_com_atraso"):
        o.append("- Publicadas pela B3 depois do prazo, mas com dado: " + ", ".join(sit["publicadas_com_atraso"]) + ".")
    o += [f"- {x}" for x in r.get("lacunas") or []]
    if sit.get("boletim_completo_pdf"):
        o += ["", f"Boletim completo em PDF (B3): {sit['boletim_completo_pdf']}"]
    return "\n".join(o) + "\n"
