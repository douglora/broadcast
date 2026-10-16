"""
A boleta de swing da manha: concilia o que ficou aberto com as barras oficiais, acha os sinais do ultimo fechamento, passa pelo gestor e grava
a boleta do proximo pregao (`swing/boleta/AAAA-MM-DD.json`) e a tela.

    python -m quant.swing.boleta                 # para o proximo pregao (hoje, se ainda nao abriu)
    python -m quant.swing.boleta --data 2026-10-13 --refazer

O QUE SAI: (1) a lista das candidatas com o destino de cada uma (capital, so medida ou recusada com o motivo); (2) as operacoes MEDIDAS, que entram
no estado como pendentes e sao resolvidas pelas barras oficiais na conciliacao da manha seguinte; (3) as ordens com capital, que o robo ao vivo
(`python -m quant.robo dia --modulo swing`) executa na abertura, em simulacao. Hoje nenhum setup passou na pesquisa: nao ha ordem com capital,
so medicao (a primeira linha da tela diz isso).

DADO VELHO NAO SAI: se o ultimo pregao do banco nao e o anterior ao dia da entrada, a boleta fica bloqueada com a causa e as datas, e nenhum
sinal e gerado em cima de um fechamento antigo.
"""
import argparse
import json
import os
import sys

import pandas as pd

from quant import mesa as mesa_mod
from quant.comum import DIR_BANCO, agora_brt, garantir_dir, gravar_atomico, log
from quant.dados import calendario
from quant.swing.texto import brl
from quant.swing import candidatas, dados, estado as est, evidencia, gestor, mesa_setups, painel, setups

ARQ_SINAIS_VIVO = os.path.join(DIR_BANCO, "sinais.parquet")
ARQ_FUNDAMENTOS_VIVO = os.path.join(DIR_BANCO, "painel_fundamentos.parquet")
ANOS_DE_HISTORICO = 2


def arq_boleta(entrada_em):
    return est.arq(os.path.join("boleta", f"{entrada_em}.json"))


def ler_boleta(entrada_em):
    try:
        with open(arq_boleta(entrada_em), encoding="utf-8") as f:
            b = json.load(f)
        return b if isinstance(b, dict) else None
    except (OSError, ValueError):
        return None


def proxima_entrada(agora=None):
    """Dia do pregao em que as ordens de hoje entram: hoje, se e pregao e ainda nao abriu (antes das 10h); senao o proximo pregao."""
    agora = agora or agora_brt()
    hoje = agora.date()
    if calendario.eh_pregao(hoje) and agora.strftime("%H:%M") < "10:00":
        return hoje
    return calendario.proximo_pregao(hoje)


def saidas_da_tela():
    env = os.environ.get("QUANT_SAIDA_SWING")
    if env:
        return [os.path.expanduser(x) for x in env.split(":") if x]
    from quant.execucao import robo_vivo
    return list(robo_vivo.SAIDAS_PADRAO)


def exposicao_do_dia(entrada_em):
    """(fracao, texto, teto em R$) da exposicao de acoes que vale na data, pela regra do Douglas/livro por classes."""
    try:
        from quant import config_carteira
        fr, texto = config_carteira.exposicao_acoes(entrada_em)
    except Exception as e:                                       # nunca derruba a boleta: cai no padrao da carteira
        from quant import carteira as ct
        fr, texto = float(ct.EXPOSICAO_ALVO), f"padrão da carteira (a regra do livro não respondeu: {type(e).__name__})"
    return {"fracao": float(fr), "texto": texto, "teto_rs": float(fr) * painel.PATRIMONIO_TOTAL}


def montar_painel(hoje, arq_sinais=None):
    sinais = arq_sinais or (ARQ_SINAIS_VIVO if os.path.exists(ARQ_SINAIS_VIVO) else None)
    return dados.montar(ano_ini=hoje.year - ANOS_DE_HISTORICO, arq_sinais=sinais)


def _contexto(estado, cfg, variantes, entrada_em, hoje, visao, motivo_visao, term, exposicao):
    """O que o gestor precisa saber do livro de capital neste momento."""
    lv = painel.livro_capital(estado, est.fechadas(), cfg, {}, hoje)
    abertas_cap = [x for x in estado["posicoes"] if x.get("modo") == "capital" and x.get("status") == "aberta"]
    return {"hoje": hoje, "entrada_em": entrada_em, "patrimonio": lv["patrimonio"], "exposicao_teto_rs": exposicao["teto_rs"],
            "valor_aberto": sum(x["valor"] for x in abertas_cap), "n_abertas": len(abertas_cap), "tickers_abertos": {x["ticker"] for x in abertas_cap},
            "variantes": variantes, "cfg": cfg, "visao": visao, "motivo_visao": motivo_visao, "terminal": term}


def _ctx_depois(ctx, dec):
    """O mesmo contexto, ja contando as entradas com capital decididas (para o proximo lote de candidatas)."""
    novo = dict(ctx)
    novo["valor_aberto"] = ctx["valor_aberto"] + sum(x["valor"] for x in dec["entradas"])
    novo["n_abertas"] = ctx["n_abertas"] + len(dec["entradas"])
    novo["tickers_abertos"] = set(ctx["tickers_abertos"]) | {x["ticker"] for x in dec["entradas"]}
    return novo


def marcar_capital_desde(linhas, agora, anterior=None):
    """Anota em cada ordem com capital QUANDO ela passou a existir (`capital_desde`). E por esse campo que o robo ao vivo decide se a ordem
    entra na abertura ou no ultimo preco (achado 9). A hora em que o arquivo foi gravado nao serve: o passo --so-mesa regrava a boleta no meio
    do dia por outro motivo (revisao de 15/10/2026). Refazer a boleta mantem a hora da ordem que ja tinha capital na boleta anterior."""
    antes = {}
    if anterior and anterior.get("emitida"):
        for c in anterior.get("candidatas") or []:
            if c.get("destino") == "capital":
                antes[(c.get("setup"), c.get("ticker"))] = c.get("capital_desde") or anterior.get("gerado")
    quando = agora.isoformat(timespec="seconds")
    for c in linhas:
        if c.get("destino") == "capital" and not c.get("capital_desde"):
            c["capital_desde"] = antes.get((c.get("setup"), c.get("ticker"))) or quando
    return linhas


def _pendente_de(c, entrada_em, cfg):
    """A operacao medida de uma candidata. As da mesa (M1, M2) entram na abertura do primeiro pregao depois da visao (`entrada_em` da linha)."""
    extras = {"conviccao_mesa": c["mesa"]["conviccao"]}
    if c.get("camada_de_julgamento"):
        extras.update({"camada_de_julgamento": True, "etiqueta": c.get("etiqueta"), "visao_gerado": c.get("visao_gerado")})
    return est.nova_pendente(c["setup"], c["ticker"], c["sinal_em"], c.get("entrada_em") or entrada_em, c["stop_dist"], c["alvo_dist"], c["prazo"], c["adtv"],
                             porque=c["porque"], overlays={"top": c["top"], "ibov_ok": c["ibov_ok"]}, preco_ref=c["preco_ref"], valor=cfg["valor_medido"], extras=extras)


def medir_mesa(estado, p, ind, visao, motivo_visao, cfg, variantes, ctx, agora):
    """M1 e M2 da visao da mesa em vigor, UMA vez por visao (o `gerado` fica anotado em `estado["visoes_medidas"]`: repetir a chamada nao repete nada).

    Devolve {"linhas", "entradas", "avisos", "resumo", "ja_medida"}. As linhas ja passaram pelo gestor (que so da capital por liberacao escrita) e
    ainda nao viraram operacao pendente: quem chama faz isso e salva o estado."""
    vazio = {"linhas": [], "entradas": [], "avisos": [], "resumo": None, "ja_medida": False}
    if visao is None:
        return vazio
    gerado = str(visao["gerado"])
    ja = next((x for x in estado.get("visoes_medidas") or [] if x.get("gerado") == gerado), None)
    if ja:
        return dict(vazio, ja_medida=True, resumo=ja)
    entrada_m = mesa_setups.entrada_da_visao(gerado)
    i = mesa_setups.indice_antes_da_entrada(p, entrada_m)
    if i is None:
        return dict(vazio, avisos=[f"M1/M2 da visão de {mesa_setups.quando(gerado)} não medidas: as cotações não chegam ao pregão anterior a {entrada_m.strftime('%d/%m/%Y')}."])
    if ind is None:
        ind = setups.indicadores(p)
    linhas, sem_dado, repetidas = mesa_setups.gerar(p, ind, visao, estado, i=i)
    for c in linhas:
        c["entrada_em"] = str(entrada_m)
    dec = gestor.decidir(linhas, dict(ctx, entrada_em=entrada_m))
    n1, n2 = sum(1 for c in dec["linhas"] if c["setup"] == "M1"), sum(1 for c in dec["linhas"] if c["setup"] == "M2")
    resumo = {"gerado": gerado, "visao_em": mesa_setups.quando(gerado), "entrada_em": str(entrada_m), "m1": n1, "m2": n2,
              "tickers_m1": [c["ticker"] for c in dec["linhas"] if c["setup"] == "M1"], "tickers_m2": [c["ticker"] for c in dec["linhas"] if c["setup"] == "M2"],
              "sem_dado": [{"ticker": t, "setup": s, "motivo": m} for t, s, m in sem_dado], "repetidas": [{"ticker": t, "setup": s} for t, s in repetidas],
              "medido_em": agora.isoformat(timespec="seconds")}
    avisos = [f"{t} ({s}) fora da medição da mesa: {m}." for t, s, m in sem_dado]
    estado.setdefault("visoes_medidas", []).append(resumo)
    est.anotar(estado, "mesa", f"Visão da mesa de {resumo['visao_em']}: M1 {n1} papel(éis) com convicção +1/+2, M2 {n2} vetado(s) (medidas de compra, entrada em "
                               f"{entrada_m.strftime('%d/%m/%Y')}); {len(sem_dado)} sem barras", agora)
    return {"linhas": dec["linhas"], "entradas": dec["entradas"], "avisos": avisos, "resumo": resumo, "ja_medida": False}


def acrescentar_mesa(p=None, agora=None, visao_arq=None, gravar_tela=True, terminal=None, usar_terminal=True):
    """Acrescenta M1 e M2 da visao em vigor a boleta JA EMITIDA do pregao de entrada, sem refazer nenhuma das candidatas que ja estao nela.
    Idempotente: a mesma visao (`gerado`) nunca e medida duas vezes. Devolve {"ok", "motivo", "m1", "m2", "ja_medida", ...}."""
    agora = agora or agora_brt()
    hoje = agora.date()
    visao, motivo_visao = mesa_mod.ler(arq=visao_arq or mesa_mod.ARQ_VISAO, hoje=None)
    if visao is None:
        return {"ok": True, "ja_medida": False, "sem_visao": True, "m1": 0, "m2": 0, "motivo": f"sem visão válida da mesa ({motivo_visao}): nada a medir"}
    entrada_m = mesa_setups.entrada_da_visao(visao["gerado"])
    b = ler_boleta(entrada_m)
    if b is None or not b.get("emitida"):
        return {"ok": False, "motivo": f"não há boleta emitida de {entrada_m}; gere a boleta primeiro (python -m quant.swing.boleta)"}
    estado = est.carregar()
    ja = next((x for x in estado.get("visoes_medidas") or [] if x.get("gerado") == str(visao["gerado"])), None)
    if ja:
        return {"ok": True, "ja_medida": True, "motivo": "a visão de " + ja["visao_em"] + " já foi medida", "m1": ja["m1"], "m2": ja["m2"], "resumo": ja}
    cfg = evidencia.config()
    variantes = evidencia.por_variante(cfg=cfg)
    p = p if p is not None else montar_painel(hoje)
    term = terminal if terminal is not None else (gestor.terminal_modulo() if usar_terminal else None)
    exposicao = b.get("exposicao") or exposicao_do_dia(entrada_m)
    ctx = _contexto(estado, cfg, variantes, entrada_m, hoje, visao, motivo_visao, term, exposicao)
    m = medir_mesa(estado, p, None, visao, motivo_visao, cfg, variantes, ctx, agora)
    if m["resumo"] is None:
        return {"ok": False, "motivo": (m["avisos"] or ["não foi possível medir a visão"])[0]}
    novas = sum(int(est.adicionar(estado, _pendente_de(c, entrada_m, cfg))) for c in m["linhas"])
    est.salvar(estado)
    ja_na_boleta = {(c["setup"], c["ticker"]) for c in b["candidatas"]}
    b["candidatas"] += marcar_capital_desde([c for c in m["linhas"] if (c["setup"], c["ticker"]) not in ja_na_boleta], agora)   # as de antes nao mudam
    b["entradas"] = list(b.get("entradas") or []) + [x["ticker"] + "|" + x["setup"] for x in m["entradas"]]
    b["medidas_mesa"] = m["resumo"]
    b["avisos"] = list(b.get("avisos") or []) + [a for a in m["avisos"] if a not in (b.get("avisos") or [])]
    b.setdefault("acrescimos", []).append({"quando": agora.isoformat(timespec="seconds"), "o_que": f"M1/M2 da visão da mesa de {m['resumo']['visao_em']}",
                                           "m1": m["resumo"]["m1"], "m2": m["resumo"]["m2"], "nao_refez": "as candidatas que já estavam na boleta ficaram como estavam"})
    gravar_atomico(arq_boleta(entrada_m), json.dumps(b, ensure_ascii=False, indent=1, default=str))
    if gravar_tela:
        escrever_tela(estado, b, variantes, cfg, hoje, exposicao, visao, motivo_visao)
    return {"ok": True, "ja_medida": False, "motivo": "acrescentadas à boleta de " + str(entrada_m), "m1": m["resumo"]["m1"], "m2": m["resumo"]["m2"],
            "novas_medidas": novas, "resumo": m["resumo"], "boleta": str(entrada_m)}


def gerar(entrada_em=None, refazer=False, p=None, agora=None, visao_arq=None, gravar_tela=True, terminal=None, usar_terminal=True):
    """Gera (e grava) a boleta. Devolve o dict da boleta."""
    agora = agora or agora_brt()
    hoje = agora.date()
    entrada_em = pd.Timestamp(entrada_em).date() if entrada_em else proxima_entrada(agora)
    anterior = ler_boleta(entrada_em)
    if anterior and anterior.get("emitida") and not refazer:
        log(f"swing: a boleta de {entrada_em} já foi emitida; fica a primeira")
        return anterior
    cfg = evidencia.config()
    variantes = evidencia.por_variante(cfg=cfg)
    esperado = calendario.pregao_anterior(entrada_em)
    bloqueios, avisos = [], []
    p = p if p is not None else montar_painel(hoje)
    ultimo = p.datas[-1].date()
    atual = ultimo >= esperado
    frescor = {"ultimo_pregao_no_banco": str(ultimo), "pregao_esperado": str(esperado), "atual": bool(atual)}
    if not atual:
        bloqueios.append({"chave": "dado_velho", "titulo": "Dado de mercado velho",
                          "detalhe": f"O último pregão nas cotações é {ultimo.strftime('%d/%m/%Y')}, mas o sinal de {entrada_em.strftime('%d/%m/%Y')} "
                                     f"pede o de {esperado.strftime('%d/%m/%Y')}. Nenhum sinal sai em cima de fechamento antigo.",
                          "comando": "python -m quant.robo preparar --repetir"})
    estado = est.carregar()
    fechadas_agora = est.conciliar(estado, p, hoje=hoje)
    for f in fechadas_agora:
        if f["status"] == "fechada":
            est.anotar(estado, "saida", f"{f['ticker']} ({f['setup']}, {f['modo']}): {f['texto_saida']}, {brl(f['resultado_rs'])} (barras oficiais)", agora)
    visao, motivo_visao = mesa_mod.ler(arq=visao_arq or mesa_mod.ARQ_VISAO, hoje=None)
    term = terminal if terminal is not None else (gestor.terminal_modulo() if usar_terminal else None)
    todas = []
    if atual:
        ind = setups.indicadores(p)
        arq_f = ARQ_FUNDAMENTOS_VIVO if os.path.exists(ARQ_FUNDAMENTOS_VIVO) else None
        ev = setups.eventos_resultado(p, arq_fundamentos=arq_f)
        if arq_f is None:
            avisos.append("Painel de fundamentos ausente: o setup D2 (lucro dos 12 meses) não dispara; D1 segue normal.")
        todas = candidatas.gerar(p, ind, ev)
    exposicao = exposicao_do_dia(entrada_em)
    ctx = _contexto(estado, cfg, variantes, entrada_em, hoje, visao, motivo_visao, term, exposicao)
    dec = gestor.decidir(todas, ctx)
    avisos += dec["avisos"]
    mesa_m = {"linhas": [], "entradas": [], "avisos": [], "resumo": None}
    if atual and visao is not None:
        mesa_m = medir_mesa(estado, p, ind, visao, motivo_visao, cfg, variantes, _ctx_depois(ctx, dec), agora)
        dec["linhas"] += mesa_m["linhas"]
        dec["entradas"] += mesa_m["entradas"]
        if mesa_m["ja_medida"] and anterior:                       # boleta refeita: as linhas da mesa ja medidas continuam nela
            dec["linhas"] += [c for c in anterior.get("candidatas") or [] if c.get("camada_de_julgamento") and c.get("visao_gerado") == str(visao["gerado"])]
        avisos += [a for a in mesa_m["avisos"] if a not in avisos]
    marcar_capital_desde(dec["linhas"], agora, anterior)
    # as operacoes MEDIDAS: uma por sinal, valor padrao, resolvidas pelas barras oficiais na conciliacao seguinte
    novas = 0
    for c in dec["linhas"]:
        novas += int(est.adicionar(estado, _pendente_de(c, entrada_em, cfg)))
    est.anotar(estado, "boleta", f"Boleta de {entrada_em}: {len(dec['linhas'])} candidata(s) ({len(mesa_m['linhas'])} da mesa), {len(dec['entradas'])} com capital, "
                                 f"{novas} medida(s) nova(s)", agora)
    est.salvar(estado)
    boleta = {"v": 1, "data": str(entrada_em), "id": f"swing-{entrada_em}", "emitida": not bloqueios, "gerado": agora.isoformat(timespec="seconds"),
              "sinal_em": str(ultimo) if atual else None, "frescor": frescor, "bloqueios": bloqueios, "avisos": avisos,
              "evidencia": evidencia.resumo(variantes), "estado_da_evidencia": "com_capital" if evidencia.com_capital(variantes) else "so_medido",
              "cfg": {k: cfg[k] for k in ("capital", "risco", "teto_nome", "max_posicoes", "valor_medido")}, "exposicao": exposicao,
              "mesa": {"ativa": visao is not None, "motivo": motivo_visao}, "terminal": term is not None,
              "candidatas": dec["linhas"], "entradas": [x["ticker"] + "|" + x["setup"] for x in dec["entradas"]], "medidas_mesa": mesa_m["resumo"],
              "conciliadas": [{k: f.get(k) for k in ("id", "ticker", "setup", "modo", "status", "motivo_saida", "resultado_rs", "saida_em")} for f in fechadas_agora]}
    garantir_dir(os.path.dirname(arq_boleta(entrada_em)))
    gravar_atomico(arq_boleta(entrada_em), json.dumps(boleta, ensure_ascii=False, indent=1, default=str))
    if gravar_tela:
        escrever_tela(estado, boleta, variantes, cfg, hoje, exposicao, visao, motivo_visao)
    return boleta


def escrever_tela(estado, boleta, variantes, cfg, hoje, exposicao, visao, motivo_visao, vivo=None, precos=None, serie=None):
    from quant.execucao import robo_vivo
    obj = painel.tela(estado, est.fechadas(), boleta, variantes, cfg, hoje, precos or {}, exposicao, visao=visao, motivo_visao=motivo_visao, vivo=vivo,
                      serie=serie)
    return robo_vivo.gravar_estado(obj, saidas_da_tela())


def linha_final(b):
    if not b.get("emitida"):
        return "swing: BOLETA BLOQUEADA — " + "; ".join(x["detalhe"] for x in b.get("bloqueios") or [])
    n = len(b["candidatas"])
    cap = sum(1 for c in b["candidatas"] if c["destino"] == "capital")
    return (f"swing: boleta de {b['data']} (sinais de {b['sinal_em']}): {n} candidata(s), {cap} com capital, {n} medida(s). "
            f"{b['evidencia']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Boleta de swing da manha (simulacao)")
    ap.add_argument("--data", default=None, help="AAAA-MM-DD do pregao de entrada (padrao: o proximo)")
    ap.add_argument("--refazer", action="store_true", help="refaz mesmo que a boleta do dia ja tenha sido emitida")
    ap.add_argument("--sem-tela", action="store_true")
    ap.add_argument("--so-mesa", action="store_true", help="so acrescenta M1 e M2 da visao da mesa em vigor a boleta ja emitida (idempotente); nao refaz nada")
    a = ap.parse_args(argv)
    if a.so_mesa:
        r = acrescentar_mesa(gravar_tela=not a.sem_tela)
        print("swing mesa: " + r["motivo"] + (f" — M1: {r['m1']} medida(s), M2: {r['m2']} medida(s)" if r.get("ok") else ""))
        return 0 if r.get("ok") else 1
    b = gerar(entrada_em=a.data, refazer=a.refazer, gravar_tela=not a.sem_tela)
    print(linha_final(b))
    return 0 if b.get("emitida") else 1


if __name__ == "__main__":
    sys.exit(main())
