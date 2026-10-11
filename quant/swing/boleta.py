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
from quant.swing import candidatas, dados, estado as est, evidencia, gestor, painel, setups

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
    fechadas = est.fechadas()
    lv = painel.livro_capital(estado, fechadas, cfg, {}, hoje)
    abertas_cap = [x for x in estado["posicoes"] if x.get("modo") == "capital" and x.get("status") == "aberta"]
    exposicao = exposicao_do_dia(entrada_em)
    ctx = {"hoje": hoje, "entrada_em": entrada_em, "patrimonio": lv["patrimonio"], "exposicao_teto_rs": exposicao["teto_rs"],
           "valor_aberto": sum(x["valor"] for x in abertas_cap), "n_abertas": len(abertas_cap), "tickers_abertos": {x["ticker"] for x in abertas_cap},
           "variantes": variantes, "cfg": cfg, "visao": visao, "motivo_visao": motivo_visao, "terminal": term}
    dec = gestor.decidir(todas, ctx)
    avisos += dec["avisos"]
    # as operacoes MEDIDAS: uma por sinal, valor padrao, resolvidas pelas barras oficiais na conciliacao seguinte
    novas = 0
    for c in dec["linhas"]:
        pend = est.nova_pendente(c["setup"], c["ticker"], c["sinal_em"], entrada_em, c["stop_dist"], c["alvo_dist"], c["prazo"], c["adtv"], porque=c["porque"],
                                 overlays={"top": c["top"], "ibov_ok": c["ibov_ok"]}, preco_ref=c["preco_ref"], valor=cfg["valor_medido"],
                                 extras={"conviccao_mesa": c["mesa"]["conviccao"]})
        novas += int(est.adicionar(estado, pend))
    est.anotar(estado, "boleta", f"Boleta de {entrada_em}: {len(todas)} candidata(s), {len(dec['entradas'])} com capital, {novas} medida(s) nova(s)", agora)
    est.salvar(estado)
    boleta = {"v": 1, "data": str(entrada_em), "id": f"swing-{entrada_em}", "emitida": not bloqueios, "gerado": agora.isoformat(timespec="seconds"),
              "sinal_em": str(ultimo) if atual else None, "frescor": frescor, "bloqueios": bloqueios, "avisos": avisos,
              "evidencia": evidencia.resumo(variantes), "estado_da_evidencia": "com_capital" if evidencia.com_capital(variantes) else "so_medido",
              "cfg": {k: cfg[k] for k in ("capital", "risco", "teto_nome", "max_posicoes", "valor_medido")}, "exposicao": exposicao,
              "mesa": {"ativa": visao is not None, "motivo": motivo_visao}, "terminal": term is not None,
              "candidatas": dec["linhas"], "entradas": [x["ticker"] + "|" + x["setup"] for x in dec["entradas"]],
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
    a = ap.parse_args(argv)
    b = gerar(entrada_em=a.data, refazer=a.refazer, gravar_tela=not a.sem_tela)
    print(linha_final(b))
    return 0 if b.get("emitida") else 1


if __name__ == "__main__":
    sys.exit(main())
