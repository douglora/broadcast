"""Cards em markdown do fechamento, para a sessao colar direto no chat.

Mesma coleta do BLOCO A/BLOCO B, mas em markdown nativo (fonte normal do app,
sem monoespacado e sem rolagem lateral): um card por bloco do livro, um por
curva, alertas, noticias e agenda. O runner escreve todos os numeros; a sessao
so troca `[[LEITURA_DA_MESA]]` pela manchete. Escolha do Douglas em 19/09.
"""

from __future__ import annotations

import re
from datetime import date

from livro import fmt

MARCADOR_LEITURA = "[[LEITURA_DA_MESA]]"
COLUNAS = ("dia", "1s", "1m", "6m", "1a", "ytd")
TITULOS_COL = ("dia", "1 sem", "1 mês", "6 m", "1 ano", "ano")


def _esc(texto) -> str:
    """Markdown de tabela: a barra vertical quebra a celula."""
    return re.sub(r"\s+", " ", str(texto or "")).replace("|", "\\|").strip()


def nome_curto(a) -> str:
    """'Vanguard FTSE All-World UCITS ETF USD Accumulating' -> 'Vanguard FTSE
    All-World'; 'Petroleo Brent (ICE, 1o vencimento)' -> 'Petroleo Brent'.
    Corta o jargao do involucro e o parentese, que sao o que alarga a coluna no
    celular; nada e abreviado nem inventado, e o nome inteiro segue no rodape."""
    n = a.nome or a.apelido or a.id
    return n.split(" UCITS")[0].split(" (")[0].strip()


def _v(x) -> str:
    return fmt.pct(x, sufixo="")


def _linha(a, j: dict, info: dict) -> str:
    atraso = " ·" if (info.get("esperado_hoje") and not info.get("fresco", True)) else ""
    celulas = [f"**{_esc(a.id)}** {_esc(nome_curto(a))}{atraso}",
               _esc(fmt.preco(j.get("ultimo"), a.decimais)),
               f"**{_v(j.get('dia'))}**"]
    celulas += [_v(j.get(c)) for c in COLUNAS[1:]]
    return "| " + " | ".join(celulas) + " |"


def _card_bloco(universo, bloco: dict, janelas: dict, series_info: dict) -> str:
    ativos = [a for a in universo.por_bloco(bloco["id"]) if a.id in janelas]
    if not ativos:
        return ""
    cab = "| " + " | ".join(["Ativo", "últ", *TITULOS_COL]) + " |"
    sep = "|---|" + "---:|" * (len(TITULOS_COL) + 1)
    linhas = [_linha(a, janelas[a.id], series_info.get(a.id) or {}) for a in ativos]
    out = "\n".join([f"### {_esc(bloco['titulo'])} · variação em %", "", cab, sep, *linhas])
    if bloco["id"] == "ucits":
        out += "\n\n" + "Nomes completos: " + " · ".join(
            f"**{_esc(a.id)}** {_esc(a.nome)}" for a in ativos) + "."
    return out


def _card_alertas(do_dia: list[dict]) -> str:
    msg = [a for a in do_dia if a.get("canal") == "mensagem" and a.get("familia") not in ("noticia", "evento")]
    crit = [a for a in msg if a.get("severidade") == "critico"]
    aten = [a for a in msg if a.get("severidade") == "atencao"]
    resto = [a for a in do_dia if a.get("canal") != "mensagem" and a.get("familia") not in ("noticia", "evento")]
    titulo = f"### Alertas do dia · {len(msg)}" + (f" ({len(crit)} crítico{'s' if len(crit) != 1 else ''})" if crit else "")
    L = [titulo, ""]
    if not msg:
        L.append("Nenhuma regra disparou hoje.")
    for a in crit:
        L.append(f"> **CRÍTICO · {_esc(a.get('regra'))} · {_esc(a.get('ativo'))}** — {_esc(a.get('titulo'))}")
        for l in [x for x in (a.get("corpo") or []) if x and not x.startswith("Link:")][:3]:
            L.append(f"> {_esc(l.lstrip(' –'))}")
        if a.get("por_que"):
            L.append(f"> *Por que importa:* {_esc(a['por_que'])}")
        L.append("")
    for a in aten:
        L.append(f"- **{_esc(a.get('regra'))} · {_esc(a.get('ativo'))}** {_esc(a.get('titulo'))}")
    if resto:
        L += ["", f"*Mais {len(resto)} sinais de baixa prioridade em `alertas.md`.*"]
    return "\n".join(L)


def _card_destaques(movers: dict) -> str:
    L = ["### Destaques do dia", ""]
    for chave, rot in (("altas", "Altas"), ("baixas", "Baixas")):
        itens = movers.get(chave) or []
        if itens:
            L.append(f"**{rot}** " + " · ".join(f"{_esc(i)} {fmt.pct(v)}" for i, v in itens))
    return "\n".join(L) if len(L) > 2 else ""


def _tabela_taxas(titulo: str, quando: str, linhas: list[tuple], rodape: str = "") -> str:
    if not linhas:
        return ""
    cab = f"| {_esc(titulo)}{' · ' + _esc(quando) if quando else ''} | taxa | Δ dia |"
    out = [cab, "|---|---:|---:|"]
    out += [f"| {_esc(r)} | {_esc(t)} | {_esc(d)} |" for r, t, d in linhas]
    if rodape:
        out += ["", rodape]
    return "\n".join(out)


def _card_commodities(em_dolar: dict | None) -> str:
    """Celulose (as duas fibras) e minerio em US$/t, sempre com o rotulo de proxy."""
    if not em_dolar:
        return ""
    ordem = ("CELULOSE_CURTA", "CELULOSE_LONGA", "MINERIO_DALIAN")
    itens = [(k, em_dolar[k]) for k in ordem if k in em_dolar]
    if not itens:
        return ""
    L = ["### Commodities em dólar · US$/t", "",
         "| Referência | US$/t | dia | 1 sem | 1 mês | leitura |"]
    L.append("|---|---:|---:|---:|---:|---|")
    notas = []
    for k, v in itens:
        j = v.get("janelas") or {}
        if v.get("semanal"):
            dia, sem, mes = "semanal", _v(v.get("variacao")), "-"
        else:
            dia, sem, mes = _v(j.get("dia")), _v(j.get("1s")), _v(j.get("1m"))
        quando = fmt.data_br(v.get("data")) if v.get("data") else "-"
        L.append(f"| **{_esc(v.get('nome'))}** | {_esc(fmt.num(v.get('usd'), 0))} | {dia} | {sem} | {mes} | {_esc(quando)} |")
        if v.get("rotulo"):
            notas.append(f"**{_esc(v.get('nome'))}**: {_esc(v['rotulo'])}"
                         + (f" · CNY/t {fmt.num(v['cny'], 0)} a USD/CNY {fmt.num(v.get('fx'), 2)}" if v.get("cny") and v.get("fx") else "")
                         + (f" · fonte {_esc(v['fonte'])}" if v.get("fonte") else ""))
    poucos = [v.get("nome") for _, v in itens if not v.get("semanal") and (v.get("pontos") or 0) < 2]
    if poucos:
        notas.append("Histórico próprio destes proxies começou em 18/09/2026: as janelas de dia, semana e mês "
                     "vão preenchendo conforme os pregões passam — " + _esc(", ".join(poucos)) + " ainda sem base de comparação.")
    return "\n".join(L + [""] + [f"- {n}" for n in notas])


def _card_curvas(ins: dict) -> str:
    if not ins:
        return ""
    partes = []
    di = ins.get("di") or {}
    if di.get("taxas"):
        linhas = [(c[3:], fmt.taxa(t), f"{fmt.bps((di.get('deltas') or {}).get(c))} bps")
                  for c, t in di["taxas"].items()]
        d = di.get("inclinacao_delta")
        rod = (f"**{_esc(di.get('verbo', ''))}** · inclinação F35-F28 {fmt.bps(di.get('inclinacao'))} bps"
               + (f" ({fmt.bps(d)} no dia)" if d is not None else ""))
        partes.append(_tabela_taxas("DI futuro (B3)", di.get("rotulo", ""), linhas, rod))
    tes = ins.get("tesouro") or {}
    if tes:
        ordem = sorted(tes.items(), key=lambda kv: ("prefixado" not in (kv[1].get("tipo") or "").lower(), kv[0]))
        linhas = [(v.get("apelido", k), fmt.taxa(v.get("taxa")) + "%", f"{fmt.bps(v.get('delta'))} bps")
                  for k, v in ordem]
        be, foc = ins.get("breakeven") or {}, ins.get("focus_ipca") or {}
        rod = ""
        if be:
            rod = "Inflação implícita " + " · ".join(f"{r} {fmt.taxa(v)}%" for r, v in be.items())
            if foc.get("mediana"):
                rod += f" · Focus IPCA {foc.get('ano')} {fmt.taxa(foc['mediana'])}%"
        base = f"base {fmt.data_br(ins.get('tesouro_base'))}" if ins.get("tesouro_base") else ""
        partes.append(_tabela_taxas("Tesouro Direto", base, linhas, rod))
    ust = ins.get("ust") or {}
    if ust.get("10y") is not None:
        d = ust.get("deltas") or {}
        linhas = [(p, fmt.taxa(ust.get(p)), f"{fmt.bps(d.get(p))} bps") for p in ("2y", "10y", "30y")]
        rod = ""
        if ust.get("2s10s") is not None:
            rod = f"2s10s {fmt.bps(ust['2s10s'])} bps" + (
                f" ({fmt.bps(ust.get('d2s10s'))} no dia)" if ust.get("d2s10s") is not None else "")
        partes.append(_tabela_taxas("Treasury (EUA)", ust.get("rotulo", ""), linhas, rod))
    reg = ins.get("regime") or {}
    if reg:
        itens = []
        if reg.get("vix") is not None:
            itens.append(f"VIX {fmt.num(reg['vix'], 1)} ({fmt.pct(reg.get('vix_var'))})")
        itens.append(f"score de risco {reg.get('score', 0)}/6")
        if reg.get("regime_vol"):
            itens.append("**regime de vol LIGADO**")
        partes.append("**Regime** " + " · ".join(itens))
    if not partes:
        return ""
    return "### Curvas de juro\n\n" + "\n\n".join(p for p in partes if p)


def _link_de(a: dict) -> str:
    d = a.get("dados") or {}
    url = d.get("link") or d.get("url") or ""
    if not url:
        for l in (a.get("corpo") or []):
            if l.startswith("Link: "):
                url = l[6:].strip()
    return f" [abrir a fonte]({url})" if url.startswith("http") else ""


def _card_noticias(do_dia: list[dict]) -> str:
    itens = [a for a in do_dia if a.get("familia") in ("noticia", "evento") and a.get("canal") == "mensagem"]
    so_manchete = [a for a in do_dia if a.get("familia") in ("noticia", "evento") and a.get("canal") != "mensagem"]
    if not itens:
        return ""
    L = [f"### Notícias e fatos · {len(itens)}", ""]
    for a in itens:
        d = a.get("dados") or {}
        marca = d.get("veiculo") or {"E04": "SEC", "E03": "CVM"}.get(a.get("regra"), "")
        quando = d.get("hora") or fmt.data_br(a.get("data"))
        sel = " · ".join(x for x in (marca, quando) if x)
        L.append(f"- **{_esc(a.get('ativo'))}** {_esc(d.get('manchete') or a.get('titulo'))}"
                 + (f" ({_esc(sel)})" if sel else "") + _link_de(a))
        if a.get("por_que"):
            L.append(f"  *Por que importa:* {_esc(a['por_que'])}")
    if so_manchete:
        # sem a contagem: o numero de manchetes descartadas assusta e nao muda decisao
        L += ["", "*As manchetes que citaram o livro sem número ou decisão nova estão em `noticias.md`.*"]
    return "\n".join(L)


def _card_agenda(agenda_l: list[str]) -> str:
    if not agenda_l:
        return ""
    linhas: list[str] = []
    for l in agenda_l:
        if l.startswith("    ") and linhas:
            linhas[-1] += " " + l.strip()
        else:
            linhas.append(l.strip())
    L = ["### Agenda", ""]
    for l in linhas:
        m = re.match(r"^(\w{3} \d{2}/\d{2})(?: (\d{2}:\d{2}))? (.*)$", l)
        if m:
            hora = f" {m.group(2)}" if m.group(2) else ""
            L.append(f"- **{_esc(m.group(1))}**{hora} — {_esc(m.group(3))}")
        else:
            L.append(f"- {_esc(l)}")
    return "\n".join(L)


def _rodape(universo, relogios_txt: str, lacunas: list[str], notas: list[str], fontes: list[str]) -> str:
    L = ["### Como ler", ""]
    L.append(f"**Relógios:** {_esc(relogios_txt)}")
    L.append("**Lacunas:** " + (_esc("; ".join(lacunas)) + "." if lacunas else "nenhuma perna falhou."))
    iuaa = next((a.nota for a in universo.ucits() if a.nota and "NAO" in (a.nota or "").upper()), "")
    if iuaa:
        L.append(f"**IUAA:** {_esc(iuaa)}")
    hip = universo.por_bloco("hipotese")
    if hip:
        L.append("**Hipótese:** " + " · ".join(f"**{_esc(a.id)}** {_esc(a.nome)}" for a in hip)
                 + " — ETFs dos EUA, a confirmar.")
    for n in notas:
        L.append(_esc(n))
    L.append(f"**Fontes:** {_esc(' · '.join(fontes))}.")
    L.append("*Uso interno da mesa. Organização e comparação de dados públicos, "
             "não é recomendação de investimento (Resolução CVM 178).*")
    return "\n".join(L)


def cards_md(universo, hoje: date, slot: str, hora_txt: str, relogios_txt: str, janelas: dict,
             series_info: dict, do_dia: list[dict], ins: dict, movers: dict, agenda_l: list[str],
             lacunas: list[str], notas: list[str], fontes: list[str], parcial: bool = False,
             em_dolar: dict | None = None) -> str:
    rotulo = "Manhã do livro" if slot == "manha" else "Fechamento do livro"
    cab = (f"## {rotulo} · {fmt.dia_semana(hoje)} {fmt.data_br(hoje.isoformat())} · {hora_txt} BRT"
           + (" · PARCIAL" if parcial else ""))
    blocos = [_card_bloco(universo, b, janelas, series_info) for b in universo.blocos]
    partes = [cab, MARCADOR_LEITURA, _card_alertas(do_dia), _card_destaques(movers),
              *blocos, _card_commodities(em_dolar), _card_curvas(ins),
              _card_noticias(do_dia), _card_agenda(agenda_l),
              _rodape(universo, relogios_txt, lacunas, notas, fontes)]
    return "\n\n---\n\n".join(p for p in partes if p) + "\n"
