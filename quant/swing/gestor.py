"""
O gestor de swing: decide, entre as candidatas do dia, o que entra com capital, o que e so medido e o que fica de fora, e por que.

COMO UM GESTOR DE FUNDO PENSA (e o que isto escreve em regra, tudo declarado antes e registrado em cada operacao):
  1. EVIDENCIA PRIMEIRO. So entra com capital o setup que a pesquisa deixou usar (`evidencia.aceita`). Hoje nenhum passou: todas as candidatas
     viram operacoes so medidas, sem capital. O gestor continua rodando para o dia em que algum passar (ou o Douglas liberar por escrito).
  2. A MESA PODE VETAR E PREFERIR (`quant/mesa.py`, `visao_mesa.json`): conviccao -2 veta o papel; entre candidatas, vem primeiro a de conviccao
     maior, depois a de setor com inclinacao maior e, empatado, a mais liquida. Camada de julgamento SEM teste historico: e medida daqui para a frente.
  3. NAO COMPRAR NA VESPERA DO RESULTADO. Se o balanco do papel sai no dia da entrada ou no pregao seguinte, a compra nao abre, exceto nos setups
     de resultado (D1 e D2), que operam justamente a reacao. A data vem do campo `proximo_resultado` da mesa; se a mesa nao trouxe, do terminal
     (`terminal.ficha(ticker)`); se nenhum dos dois sabe a data, a regra nao bloqueia e a operacao leva a nota "data do resultado nao informada".
  4. TAMANHO PELO RISCO (`tamanho.py`): 0,5% do capital do livro por operacao, teto de 12% por papel, no maximo 10 posicoes e exposicao total
     nunca acima de `config_carteira.exposicao_acoes(hoje)` do patrimonio. Em exposicao menor que a ja usada nao abre posicao nova (nao vende o que ja tem:
     swing curto acaba sozinho em ate 10 pregoes).
  5. UM PAPEL, UMA POSICAO COM CAPITAL. Se o papel ja esta no livro, a candidata de outro setup nao soma risco no mesmo nome.

`gatilho_curto_prazo` e `eventos_10_pregoes` da mesa, e a ficha do terminal, ficam GUARDADOS na operacao e aparecem na tela, mas nao mudam a
decisao (so `proximo_resultado` e a conviccao mexem). O terminal e opcional: sem ele, o gestor decide igual, com a nota "terminal indisponivel".
"""
from datetime import date

import pandas as pd

from quant import mesa
from quant.dados import calendario
from quant.swing import evidencia, tamanho

JANELA_VESPERA = 1                      # pregoes depois do dia da entrada em que um resultado ainda conta como "vespera"
SETUPS_DE_RESULTADO = ("D1", "D2")


def _data(x):
    """'2026-11-05', dict com 'data' ou date -> date; qualquer outra coisa -> None."""
    if isinstance(x, dict):
        x = x.get("data")
    if isinstance(x, date):
        return x
    try:
        return pd.Timestamp(str(x)[:10]).date() if x else None
    except (ValueError, TypeError):
        return None


def terminal_modulo():
    """O modulo `quant.terminal` se existir e disser que esta disponivel; senao None. Nunca levanta."""
    try:
        from quant import terminal
        disp = getattr(terminal, "disponivel", None)
        if callable(disp) and disp():
            return terminal
    except Exception:
        pass
    return None


def ficha_do_terminal(terminal, ticker):
    """Ficha do papel no terminal, ou None. Qualquer erro vira None: o terminal nunca derruba o gestor."""
    if terminal is None:
        return None
    try:
        f = terminal.ficha(ticker)
        return f if isinstance(f, dict) else None
    except Exception:
        return None


def _resultado_da_ficha(ficha):
    if not isinstance(ficha, dict):
        return None
    for chave in ("proximo_resultado", "proximo_balanco"):
        d = _data(ficha.get(chave))
        if d:
            return d
    for sub in ficha.values():
        if isinstance(sub, dict):
            for chave in ("proximo_resultado", "proximo_balanco"):
                d = _data(sub.get(chave))
                if d:
                    return d
    return None


def info_da_mesa(visao, ticker):
    """Tudo o que a mesa disse do papel (zeros e None quando ela nao analisou)."""
    vazio = {"conviccao": 0, "setor_inclinacao": 0, "analisado": False, "proximo_resultado": None, "gatilho": None, "eventos": [], "risco": None}
    if not visao:
        return vazio
    a = next((x for x in visao.get("acoes") or [] if str(x.get("ticker")).upper() == ticker.upper()), None)
    if a is None:
        return vazio
    incl = mesa.inclinacoes(visao)
    res = _data(a.get("proximo_resultado"))
    if res is None:
        eb = a.get("evento_binario")
        if isinstance(eb, dict) and str(eb.get("descricao") or "").strip().lower().startswith("resultado"):
            res = _data(eb.get("data"))
    return {"conviccao": mesa._inteiro(a.get("conviccao")), "setor_inclinacao": mesa._setor_da_mesa(a.get("setor"), incl), "analisado": True,
            "proximo_resultado": res, "gatilho": a.get("gatilho_curto_prazo"), "eventos": a.get("eventos_10_pregoes") or [], "risco": a.get("risco")}


def vespera_de_resultado(res, entrada_em, janela=JANELA_VESPERA):
    """True se o resultado sai no dia da entrada ou em ate `janela` pregoes depois dele."""
    if res is None:
        return False
    limite = entrada_em
    for _ in range(janela):
        limite = calendario.proximo_pregao(limite)
    return entrada_em <= res <= limite


def decidir(candidatas, ctx):
    """Decide o destino de cada candidata.

    ctx: hoje, entrada_em (date), patrimonio (R$ do livro de capital), exposicao_teto_rs, valor_aberto, n_abertas, tickers_abertos (set),
         variantes (de `evidencia.por_variante`), cfg (de `evidencia.config`), visao (dict ou None), terminal (modulo ou None).
    Devolve {"linhas": [...todas as candidatas com destino...], "entradas": [...com capital...], "avisos": [...]}."""
    cfg, variantes = ctx["cfg"], ctx["variantes"]
    term = ctx.get("terminal")
    entrada_em = ctx["entrada_em"]
    patrimonio = float(ctx["patrimonio"])
    teto_rs = min(float(ctx["exposicao_teto_rs"]), patrimonio * tamanho.EXPO_MAX)
    aberto, n_abertas = float(ctx["valor_aberto"]), int(ctx["n_abertas"])
    ocupados = set(ctx.get("tickers_abertos") or ())
    avisos = []
    if ctx.get("visao") is None:
        avisos.append("Mesa sem visão válida (" + str(ctx.get("motivo_visao") or "ausente") + "): sem veto nem preferência da mesa.")
    if term is None:
        avisos.append("Terminal indisponível: o gestor decide sem a ficha do papel e sem a data do resultado vinda do terminal.")
    linhas = []
    pendentes = []
    for c in candidatas:
        linha = dict(c)
        linha.update({"destino": "medida", "motivo": None, "variante": None})
        mi = info_da_mesa(ctx.get("visao"), c["ticker"])
        linha["mesa"] = {"conviccao": mi["conviccao"], "setor_inclinacao": mi["setor_inclinacao"], "analisado": mi["analisado"],
                         "gatilho_curto_prazo": mi["gatilho"], "eventos_10_pregoes": mi["eventos"]}
        ok, vid = evidencia.aceita(variantes, c["setup"], c["top"], c["ibov_ok"])
        if not ok:
            r = next((x for x in variantes.values() if x["nucleo"] == c["setup"]), None)
            linha["motivo"] = "setup só medido: " + (r["motivo"] if r else "sem evidência")
            linhas.append(linha)
            continue
        linha["variante"] = vid
        linha["destino"] = "capital?"
        linhas.append(linha)
        pendentes.append((linha, mi))
    pendentes.sort(key=lambda lm: (-lm[1]["conviccao"], -lm[1]["setor_inclinacao"], -(lm[0].get("adtv") or 0.0)))
    entradas = []
    for linha, mi in pendentes:
        t, setup = linha["ticker"], linha["setup"]

        def recusar(motivo, linha=linha):
            linha["destino"], linha["motivo"] = "recusada", motivo

        if t in ocupados:
            recusar("o papel já está no livro com capital")
            continue
        if mi["conviccao"] <= mesa.VETO:
            recusar("vetada pela mesa (convicção -2)" + (f": {mi['risco']}" if mi["risco"] else ""))
            continue
        ficha = ficha_do_terminal(term, t)
        res = mi["proximo_resultado"] or _resultado_da_ficha(ficha)
        if setup not in SETUPS_DE_RESULTADO and vespera_de_resultado(res, entrada_em):
            recusar(f"véspera de resultado ({res.strftime('%d/%m/%Y')}); só os setups de resultado operam isso")
            continue
        qtd, valor = tamanho.quantidade(patrimonio, linha["preco_ref"], linha["stop_dist"], cfg["risco"], cfg["teto_nome"])
        if qtd <= 0:
            recusar("não cabe um lote dentro do risco por operação e do teto por papel")
            continue
        if not tamanho.cabe(valor, aberto, teto_rs, n_abertas, None, 1.0, cfg["max_posicoes"]):
            recusar("sem espaço: número máximo de posições ou exposição de ações no limite")
            continue
        linha.update({"destino": "capital", "qtd": qtd, "valor": valor, "proximo_resultado": str(res) if res else None,
                      "ficha": ficha or {}, "nota_resultado": None if res else "data do resultado não informada",
                      "risco_rs": float(qtd * linha["stop_dist"])})
        aberto += valor
        n_abertas += 1
        ocupados.add(t)
        entradas.append(linha)
    return {"linhas": linhas, "entradas": entradas, "avisos": avisos}
