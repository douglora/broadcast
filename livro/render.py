"""Renderiza o que a sessao vai apenas narrar: Fechamento (BLOCO A e BLOCO B),
alertas.md, intradia.md, manha.md e o JSON com os insumos da Leitura da Mesa.

Regras de forma: blocos monoespacados de ate 52 colunas; numeros brasileiros;
UCITS por extenso na legenda; campo ausente e omitido e vai para LACUNAS;
nunca N/D, ?, 0 ou numero velho como se fosse de hoje."""

from __future__ import annotations

import textwrap
from datetime import date, timedelta

from livro import fmt
from livro import qualidade as qa
from livro import indicadores as ind
from livro import relogios

LARGURA = 52
MARCADOR_LEITURA = "<<LEITURA_DA_MESA>>"


def quebrar(texto: str, indent: str = "  ", largura: int = LARGURA) -> list[str]:
    return textwrap.wrap(texto, width=largura, subsequent_indent=indent, break_long_words=False,
                         break_on_hyphens=False) or [""]


# ---------------------------------------------------------------- BLOCO B
def linha_tabela(a, j: dict, modo: str = "completo", marcado: bool = False) -> str:
    ultimo = fmt.preco(j.get("ultimo"), a.decimais)
    # "*" = ver LACUNAS; vai DENTRO da coluna do ticker para a linha nao passar de 52
    ident = (a.id[:5] + "*") if marcado else a.id[:6]
    if modo == "celular":
        apelido = (a.apelido or "")[:6]
        cols = [j.get("dia"), j.get("1s"), j.get("1m"), j.get("ytd")]
        return f"{ident:<6} {apelido:<6}{ultimo:>7}" + "".join(fmt.pct_col(c, 5) for c in cols)
    apelido = (a.apelido or "")[:7]
    cols = [j.get("dia"), j.get("1s"), j.get("1m"), j.get("6m"), j.get("1a"), j.get("ytd")]
    return f"{ident:<6} {apelido:<7}{ultimo:>8}" + "".join(fmt.pct_col(c, 5) for c in cols)


def cabecalho_tabela(modo: str = "completo") -> str:
    if modo == "celular":
        return f"{'VARIAÇÃO %':<13}{'últ':>7}{'dia':>5}{'1s':>5}{'1m':>5}{'YTD':>5}"
    return f"{'VARIAÇÃO %':<14}{'últ':>8}{'dia':>5}{'1s':>5}{'1m':>5}{'6m':>5}{'1a':>5}{'YTD':>5}"


def bloco_b(universo, janelas: dict, series_info: dict, modo: str = "completo") -> tuple[str, list[str]]:
    """Tabela por bloco; devolve (texto, lacunas)."""
    linhas = [cabecalho_tabela(modo)]
    lacunas = []
    for bloco in universo.blocos:
        ativos = universo.por_bloco(bloco["id"])
        if not ativos:
            continue
        largura = 41 if modo == "celular" else LARGURA
        linhas.append(bloco["titulo"][:largura])
        for a in ativos:
            j = janelas.get(a.id)
            info = series_info.get(a.id) or {}
            if not j:
                lacunas.append(f"{a.id} sem série")
                continue
            rot, ocultar = qa.marcador(j, info)
            vazio = {k: None for k in ("ultimo", "dia", "1s", "1m", "3m", "6m", "1a", "ytd")}
            l = linha_tabela(a, {**j, **vazio} if ocultar else j, modo, marcado=bool(rot))
            if info.get("esperado_hoje") and not info.get("fresco", True):
                lacunas.append(f"{a.id} sem barra de {fmt.data_br(info.get('esperado'))} (última {fmt.data_br(j.get('data'))})")
            linhas.append(l)
    return "\n".join(linhas), lacunas


def legenda_ucits(universo) -> str:
    partes = []
    for a in universo.ucits():
        nota = f" — {a.nota}" if a.nota and "NAO" in a.nota.upper() else ""
        partes.append(f"{a.id} {a.nome}{nota}")
    hip = universo.por_bloco("hipotese")
    txt = "UCITS por extenso: " + " · ".join(partes) + "."
    if hip:
        txt += " Hipótese: " + " · ".join(f"{a.id} {a.nome}" for a in hip) + " (ETFs dos EUA, a confirmar)."
    return "\n".join(quebrar(txt, indent="", largura=LARGURA))


# ---------------------------------------------------------------- curvas
def _hist_di(curvas: dict, codigo: str) -> list:
    return ((curvas.get("di") or {}).get("historico") or {}).get(codigo) or []


def curvas_linhas(curvas: dict, universo, macro: dict, regime: dict, hoje: date) -> tuple[list[str], list[str], dict]:
    """Linhas do bloco CURVAS + lacunas + insumos para a leitura."""
    linhas, lacunas, ins = [], [], {}
    di = curvas.get("di") or {}
    codigos = [v["codigo"] for v in (universo.curvas.get("di", {}).get("vertices") or [])]
    ult = di.get("ultimo_pregao")
    if ult and any(_hist_di(curvas, c) for c in codigos):
        rot = "D0" if ult == hoje.isoformat() else f"ajuste {fmt.data_br(ult)}"
        partes, deltas = [], {}
        for c in codigos:
            h = _hist_di(curvas, c)
            if not h:
                continue
            d1 = ind.bps(h[-1][1], h[-2][1]) if len(h) > 1 else None
            d5 = ind.bps(h[-1][1], h[-6][1]) if len(h) > 5 else None
            deltas[c] = (h[-1][1], d1, d5)
            partes.append(f"{c[3:]} {fmt.taxa(h[-1][1])} ({fmt.bps(d1)}·{fmt.bps(d5)})")
        linhas += quebrar(f"DI ({rot}, Δ dia·sem bps) " + " ".join(partes), indent="    ")
        f28, f35 = _hist_di(curvas, "DI1F28"), _hist_di(curvas, "DI1F35")
        if f28 and f35:
            incl = ind.bps(f35[-1][1], f28[-1][1])
            incl_ant = ind.bps(f35[-2][1], f28[-2][1]) if len(f28) > 1 and len(f35) > 1 else None
            soma = sum((d[1] or 0) for d in deltas.values())
            verbo = "ABRIU" if soma > 2 else "FECHOU" if soma < -2 else "estável"
            linhas.append(f"    {verbo}; F35-F28 {fmt.bps(incl)} bps" + (f" ({fmt.bps(incl - incl_ant)})" if incl_ant is not None else ""))
            ins["di"] = {"deltas": {k: v[1] for k, v in deltas.items()}, "inclinacao": incl, "verbo": verbo, "ultimo": ult,
                         "taxas": {k: v[0] for k, v in deltas.items()}, "delta5": {k: v[2] for k, v in deltas.items()},
                         "inclinacao_delta": (incl - incl_ant) if incl_ant is not None else None, "rotulo": rot}
    else:
        lacunas.append("DI sem ajuste B3 (regras de curva DI desligadas)")
    tes = curvas.get("tesouro") or {}
    titulos = tes.get("titulos") or {}
    if titulos:
        base = tes.get("data_base")
        pre, ipca = [], []
        for tid, t in titulos.items():
            h = [x for x in (t.get("historico") or []) if x[1] is not None]
            if not h:
                continue
            d1 = ind.bps(h[-1][1], h[-2][1]) if len(h) > 1 else None
            if len(h) > 1:
                # o "delta" do Tesouro e entre as duas ultimas datas-base, nao "no dia"
                ins["tesouro_base_anterior"] = h[-2][0]
            item = f"{t.get('apelido', tid)} {fmt.taxa(h[-1][1])} ({fmt.bps(d1)})"
            (pre if "prefixado" in t.get("tipo", "").lower() else ipca).append(item)
            ins.setdefault("tesouro", {})[tid] = {"taxa": h[-1][1], "delta": d1, "pu": h[-1][2],
                                                  "apelido": t.get("apelido", tid), "tipo": t.get("tipo", "")}
        ant = ins.get("tesouro_base_anterior")
        linhas += quebrar(f"TD (base {fmt.data_br(base)}"
                          + (f", Δ desde {fmt.data_br(ant)}" if ant else "") + ") " + " · ".join(pre + ipca), indent="    ")
        ins["tesouro_base"] = base
        # breakevens
        bes = []
        for be in (universo.curvas.get("tesouro", {}).get("breakevens") or []):
            p, i = titulos.get(be["pre"]), titulos.get(be["ipca"])
            if p and i and p.get("historico") and i.get("historico"):
                v = ind.breakeven(p["historico"][-1][1], i["historico"][-1][1])
                bes.append(f"{be['rotulo']} {fmt.taxa(v)}%")
                ins.setdefault("breakeven", {})[be["rotulo"]] = v
        focus = ((macro.get("focus") or {}).get("expectativas") or {}).get("IPCA") or {}
        ano_prox = str(hoje.year + 1)
        f_ipca = (focus.get("por_ano") or {}).get(ano_prox, {}).get("mediana")
        if f_ipca:
            ins["focus_ipca"] = {"ano": ano_prox, "mediana": f_ipca}
        if bes:
            linhas += quebrar("    Implícita " + " · ".join(bes) + (f" vs Focus IPCA {ano_prox} {fmt.taxa(f_ipca)}%" if f_ipca else ""), indent="    ")
    else:
        lacunas.append("Tesouro sem dado")
    ust = curvas.get("ust") or {}
    h = ust.get("historico") or []
    if h:
        prazos = ust.get("prazos") or ["2y", "5y", "10y", "30y"]
        idx = {p: i + 1 for i, p in enumerate(prazos)}
        u, ant = h[-1], (h[-2] if len(h) > 1 else None)
        partes = []
        for p in ("2y", "10y", "30y"):
            v = u[idx[p]]
            d = ind.bps(v, ant[idx[p]]) if ant and v is not None and ant[idx[p]] is not None else None
            partes.append(f"{p} {fmt.taxa(v)} ({fmt.bps(d)})")
        s2s10 = ind.bps(u[idx["10y"]], u[idx["2y"]]) if u[idx["10y"]] is not None and u[idx["2y"]] is not None else None
        s2s10_ant = ind.bps(ant[idx["10y"]], ant[idx["2y"]]) if ant and ant[idx["10y"]] is not None and ant[idx["2y"]] is not None else None
        rot = "D0" if u[0] == hoje.isoformat() else f"CMT {fmt.data_br(u[0])}"
        linhas += quebrar(f"UST ({rot}) " + " · ".join(partes) + (f" · 2s10s {fmt.bps(s2s10)}" + (f" ({fmt.bps(s2s10 - s2s10_ant)})" if s2s10_ant is not None else "") if s2s10 is not None else ""), indent="    ")
        ins["ust"] = {"2y": u[idx["2y"]], "10y": u[idx["10y"]], "30y": u[idx["30y"]], "2s10s": s2s10, "data": u[0],
                      "rotulo": rot, "d2s10s": (s2s10 - s2s10_ant) if (s2s10 is not None and s2s10_ant is not None) else None,
                      "deltas": {p: (ind.bps(u[idx[p]], ant[idx[p]]) if ant and u[idx[p]] is not None and ant[idx[p]] is not None else None)
                                 for p in ("2y", "10y", "30y")}}
    else:
        lacunas.append("UST sem dado")
    if regime:
        vix = regime.get("vix")
        txt = f"Regime: score risco {regime.get('score', 0)} de {regime.get('avaliados', 6)}"
        if vix is not None:
            txt = f"Regime: VIX {fmt.num(vix, 1)} ({fmt.pct(regime.get('vix_var'))}) · score risco {regime.get('score', 0)} de {regime.get('avaliados', 6)}"
        if regime.get("regime_vol"):
            txt += " · regime de vol LIGADO"
        linhas += quebrar(txt, indent="    ")
        ins["regime"] = regime
    return linhas, lacunas, ins


# ---------------------------------------------------------------- agenda
def agenda_extras(agenda_json: dict, calendario: dict) -> list[tuple]:
    """(data, texto) para resultados que so o Yahoo trouxe e para ex-dividendos."""
    ja = {(r["ticker"], str(r["data"])[:10]) for r in (calendario.get("resultados") or [])}
    out = []
    for r in (agenda_json or {}).get("resultados") or []:
        if (r["ticker"], r["data"]) in ja:
            continue
        d = relogios._d(r["data"])
        out.append((d, f"{fmt.dia_semana(d)} {fmt.data_br(d.isoformat())} resultado {r['ticker']} ({r.get('fonte', 'Yahoo')}, {'confirmado' if r.get('confirmado') else 'estimado'})"))
    for e in (agenda_json or {}).get("ex_dividendos") or []:
        d = relogios._d(e["data"])
        v = f" {e.get('moeda', '')} {fmt.num(e['valor'], 2)}".rstrip() if e.get("valor") else ""
        out.append((d, f"{fmt.dia_semana(d)} {fmt.data_br(d.isoformat())} ex-dividendo {e['ticker']}{v} (último provento, Yahoo)"))
    return out


def agenda(calendario: dict, hoje: date, dias: int = 6, so_confianca: tuple = ("alta", "media"), extras: list | None = None,
           dias_empresas: int = 14, incluir_hoje: bool = False) -> list[str]:
    """Macro nos proximos `dias`; resultado e data-com dos ativos do livro em ate
    `dias_empresas` corridos (~10 pregoes): o resultado da MU em 30/09 so aparecia a
    partir de 24/09 com a janela unica de 6 dias. `incluir_hoje` (manha): a agenda
    comeca no proprio dia; em 24/09 a manha perdeu o RPM das 09h e o leilao das 11h."""
    fim = hoje + timedelta(days=dias)
    fim_emp = hoje + timedelta(days=dias_empresas)
    ini = hoje - timedelta(days=1) if incluir_hoje else hoje
    e_empresa = lambda t: (" resultado " in t) or (" ex-dividendo " in t)
    itens = [(d, t) for d, t in (extras or []) if ini < d <= (fim_emp if e_empresa(t) else fim)]
    for e in calendario.get("eventos_macro") or []:
        d = relogios._d(e["data"])
        if ini < d <= fim:
            conf = e.get("confianca", "media")
            sufixo = "" if conf in so_confianca else " (a confirmar)"
            hora = f" {e['hora_brt']}" if e.get("hora_brt") else ""
            itens.append((d, f"{fmt.dia_semana(d)} {fmt.data_br(d.isoformat())}{hora} {e['evento']}{sufixo}"))
    for r in calendario.get("resultados") or []:
        d = relogios._d(r["data"])
        if ini < d <= fim_emp:
            quando = {"apos_ny": "após NY", "antes_ny": "antes de NY", "apos_b3": "após B3", "madrugada": "madrugada"}.get(r.get("quando"), "")
            conf = "confirmado" if r.get("confirmado") else "estimado"
            itens.append((d, f"{fmt.dia_semana(d)} {fmt.data_br(d.isoformat())} resultado {r['ticker']} ({quando}, {conf})"))
    for rec in calendario.get("recorrentes") or []:
        d = ini + timedelta(days=1)
        while d <= fim:
            if d.weekday() == rec["dia_semana"]:
                itens.append((d, f"{fmt.dia_semana(d)} {fmt.data_br(d.isoformat())} {rec['hora_brt']} {rec['evento']}"))
            d += timedelta(days=1)
    itens.sort(key=lambda x: x[0])
    # teto por tipo, para a agenda de empresas nao expulsar o Copom (e vice-versa)
    macro = [x for x in itens if not e_empresa(x[1])][:8]
    emp = [x for x in itens if e_empresa(x[1])][:8]
    out = []
    for _, t in sorted(macro + emp, key=lambda x: x[0]):
        out += quebrar(t, indent="    ")
    return out


# ---------------------------------------------------------------- alertas
def alertas_md(resultado: dict, do_dia: list[dict], slot_rotulo: str) -> str:
    linhas = [f"ALERTAS · {slot_rotulo}", ""]
    if not resultado["mensagens"]:
        linhas.append("Nenhum alerta novo neste slot.")
    for m in resultado["mensagens"]:
        linhas.append(m["texto"])
        if m.get("push"):
            linhas.append(f"Push: {m['push']}")
        linhas.append(f"ids: {', '.join(m['ids'])}")
        linhas.append("")
    if resultado["linhas_info"]:
        linhas.append("Info (só linha no Fechamento):")
        for i in resultado["linhas_info"]:
            linhas.append(f"· {i['regra']} {i['titulo']}")
        linhas.append("")
    if resultado["suprimidos"]:
        linhas.append("Suprimidos pelo teto (viram linha do Fechamento): " + ", ".join(f"{s['id']} ({s['motivo']})" for s in resultado["suprimidos"]))
    if do_dia:
        manchetes = [a for a in do_dia if a.get("familia") in ("noticia", "evento") and a.get("canal") != "mensagem"]
        linhas.append("")
        linhas.append("Alertas do dia (todos, com status):")
        for a in do_dia:
            if a in manchetes:
                continue
            linhas.append(f"· {a['status']:<9} {a['rotulo'] if 'rotulo' in a else ''}{a['regra']} {a['ativo']} — {a['titulo'][:80]}")
        if manchetes:
            linhas.append(f"· (+{len(manchetes)} notícias só manchete, em noticias.md)")
    return "\n".join(linhas).rstrip() + "\n"


def noticias_md(do_dia: list[dict], data_br: str, pernas: dict | None = None) -> str:
    """Todas as noticias e fatos do dia (cards completos), para 'noticias' na sessao."""
    fatos = [a for a in do_dia if a.get("familia") in ("noticia", "evento")]
    L = [f"NOTÍCIAS E FATOS · {data_br}", ""]
    if pernas:
        L.append("Pernas: " + " · ".join(f"{k} {v}" for k, v in pernas.items() if k in ("noticias", "cvm", "sec")))
        L.append("")
    if not fatos:
        L.append("Nenhuma noticia ou fato relevante atribuido ao livro hoje.")
        return "\n".join(L) + "\n"
    grupos = [("FATOS RELEVANTES E COMUNICADOS (CVM)", lambda a: a["regra"] == "E03"),
              ("SEC (8-K, 6-K, 10-Q, 10-K)", lambda a: a["regra"] == "E04"),
              ("NOTÍCIAS COM MATERIALIDADE", lambda a: a["regra"] == "E05" and a.get("severidade") != "info"),
              ("OUTRAS NOTÍCIAS (só manchete)", lambda a: a["regra"] == "E05" and a.get("severidade") == "info")]
    for titulo, filtro in grupos:
        itens = [a for a in fatos if filtro(a)]
        if not itens:
            continue
        L.append(f"## {titulo} ({len(itens)})")
        L.append("")
        for a in itens:
            if titulo.startswith("OUTRAS"):
                if itens.index(a) >= 60:
                    L.append(f"· (+{len(itens) - 60} manchetes; lista completa em eventos/noticias.json)")
                    break
                d = a.get("dados") or {}
                L.append(f"· {a['ativo']} {d.get('manchete') or a['titulo']} ({d.get('veiculo', '')}) {d.get('url', '')}".rstrip())
            else:
                L.append(a.get("texto") or a["titulo"])
                L.append(f"id: {a['id']} · status: {a.get('status', '')}" + (" · íntegra disponível" if (a.get('dados') or {}).get('texto_disponivel') else ""))
                L.append("")
        L.append("")
    return "\n".join(L).rstrip() + "\n"


def linha_sem_novidade(slot_rotulo: str, hora_coleta: str, obs: str, proximo: str) -> str:
    return f"{slot_rotulo} · sem alerta novo · coleta {hora_coleta} OK" + (f" ({obs})" if obs else "") + (f" · próximo {proximo}" if proximo else "")


# ---------------------------------------------------------------- fechamento
def bloco_a(hoje: date, relogios_txt: str, do_dia: list[dict], em_vigor: list[str], movers: dict,
            curvas_l: list[str], agenda_l: list[str], lacunas: list[str], fontes: list[str],
            parcial: bool = False, exemplo: bool = False, slot: str = "fechamento", hora: str = "") -> str:
    L = []
    if slot == "manha":
        L.append(f"MANHÃ DO LIVRO · {fmt.dia_semana(hoje)} {fmt.data_br(hoje.isoformat())} · {hora or '08h30'} BRT (curvas D-1)")
    else:
        L.append(f"FECHAMENTO DO LIVRO · {fmt.dia_semana(hoje)} {fmt.data_br(hoje.isoformat())} · {hora or '18h40'} BRT" + (" · PARCIAL" if parcial else ""))
    L += quebrar("Relógios: " + relogios_txt, indent="  ")
    L.append("")
    # noticia e fato que nao viraram mensagem (info ou cortados pelo teto) vivem em
    # noticias.md, nao no digest: sem isso o backlog do dia inteiro entra no cabecalho
    so_manchete = [a for a in do_dia if a.get("familia") in ("noticia", "evento") and a.get("canal") != "mensagem"]
    do_dia = [a for a in do_dia if a not in so_manchete]
    crit = sum(1 for a in do_dia if a.get("severidade") == "critico")
    L.append(f"ALERTAS DO DIA ({len(do_dia)}" + (f" · {crit} crítico{'s' if crit > 1 else ''}" if crit else "") + ")")
    if not do_dia:
        L.append("nenhum")
    for a in do_dia[:8]:
        L += quebrar(f"{fmt_rotulo(a.get('severidade'))} {a['regra']} {a['titulo']}", indent="          ")
    if len(do_dia) > 8:
        L.append(f"(+{len(do_dia) - 8} em alertas.md)")
    if em_vigor:
        L += quebrar("Em vigor/Anulados: " + " · ".join(em_vigor), indent="  ")
    L.append("")
    if movers.get("altas"):
        L += quebrar("ALTAS  " + " · ".join(f"{i} {fmt.pct(v)}" for i, v in movers["altas"]), indent="       ")
    if movers.get("baixas"):
        L += quebrar("BAIXAS " + " · ".join(f"{i} {fmt.pct(v)}" for i, v in movers["baixas"]), indent="       ")
    L.append("")
    fatos = [a for a in do_dia if a.get("familia") in ("noticia", "evento")]
    if fatos or so_manchete:
        # a contagem de manchetes sem materialidade assusta e nao muda decisao: vive em noticias.md
        L += quebrar(f"NOTÍCIAS E FATOS ({len(fatos)} com materialidade · noticias.md)", indent="  ")
        for a in fatos[:6]:
            d = a.get("dados") or {}
            veic = d.get("veiculo") or ""
            L += quebrar(f"· {a['ativo']} {d.get('manchete') or a['titulo']}" + (f" ({veic})" if veic else ""), indent="  ")
        if len(fatos) > 6:
            L.append(f"  (+{len(fatos) - 6})")
        L.append("")
    L.append("CURVAS · taxa (Δ bps)")
    L += curvas_l or ["sem dado de curva"]
    L.append("")
    L.append("LEITURA DA MESA")
    L.append(MARCADOR_LEITURA)
    L.append("")
    L.append("AGENDA")
    L += agenda_l or ["sem evento nos próximos dias"]
    L.append("")
    if lacunas:
        L += quebrar("LACUNAS: " + "; ".join(lacunas) + ".", indent="  ")
    else:
        L.append("LACUNAS: nenhuma perna falhou.")
    L += quebrar("Fontes: " + " · ".join(fontes), indent="  ")
    return "\n".join(L)


def fmt_rotulo(sev: str | None) -> str:
    return {"critico": "[CRÍTICO]", "atencao": "[ATENÇÃO]", "info": "[INFO]   "}.get(sev or "info", "[INFO]   ")


def movers(janelas: dict, universo, n: int = 5) -> dict:
    # so entra quem tem "dia" de verdade: um pregao, dado confirmado, barra de hoje
    # (em 23/09 MMM +3,2% e GFS -4,4% eram dois pregoes e foram parar no push)
    itens = [(i, j["dia"]) for i, j in janelas.items() if j.get("dia") is not None and j.get("dia_confirmado", True)
             and universo.por_id(i) and not universo.por_id(i).proxy]
    itens.sort(key=lambda x: x[1], reverse=True)
    return {"altas": [x for x in itens[:n] if x[1] > 0], "baixas": [x for x in sorted(itens, key=lambda x: x[1])[:n] if x[1] < 0]}


def fechamento_md(a: str, b: str, legenda: str, notas: list[str]) -> str:
    partes = ["BLOCO A", "```", a, "```", "", "BLOCO B", "```", b, "```", legenda]
    if notas:
        partes.append("\n".join(quebrar(" ".join(notas), indent="", largura=LARGURA)))
    return "\n".join(partes) + "\n"
