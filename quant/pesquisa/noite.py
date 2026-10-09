"""
Rotina da noite do robo de day trade (pedido do Douglas em 09/10/2026: "quero a rotina toda noite, e te dou autorizacao
para mexer no robo sozinho"). Roda depois do fechamento, nunca com o pregao aberto.

O que faz, nesta ordem, sem depender de julgamento de ninguem (as contas decidem):
  1. PLACAR: junta todos os sinais guardados pelo robo (operando ou so medindo) e o que cada um deu ou teria dado,
     por leitura (reversao do dado, climax, nivel e reacao, e as regras de laboratorio de quant/pesquisa/setups.json).
  2. PROTOCOLO: decide quem opera e quem so mede, e grava em quant/saida/modo_robo.json e em setups.json.
  3. RELATORIO: quant/saida/relatorios/noite_<data>.md, para o resumo da manha.

O PROTOCOLO (so a simulacao; nunca mexe em lote, perda maxima, meta, janela ou na chave liga/desliga do Douglas):
  - so opera a leitura APROVADA no historico (positiva na descoberta, na validacao e na prova). Reprovada: so mede.
  - REBAIXA para "so mede" a leitura que opera e, ao vivo, tem 10 ou mais negocios com soma abaixo de -R$ 1.500 ou
    media abaixo de -R$ 50 por negocio.
  - PROMOVE para "opera" a leitura aprovada que esta so medindo quando ela junta 20 ou mais sinais ao vivo com media
    positiva e t >= 1. No maximo uma promocao por noite e tres leituras operando.
  - leitura reprovada no historico que vai bem ao vivo (60+ sinais, media positiva, t >= 2) NAO e promovida: vira
    pedido de estudo no relatorio.
  - chave listada em "travado_pelo_douglas" (modo_robo.json) nao e tocada.
Toda decisao fica em quant/saida/pesquisa5/decisoes.jsonl.

Uso: python -m quant.pesquisa.noite [--ensaio]     (--ensaio: mostra o que faria, sem gravar)
"""
import argparse
import json
import os
import time

import numpy as np

from quant.comum import agora_brt, garantir_dir, gravar_atomico, ler_json
from quant.daytrade import medir, regras_lab
from quant.daytrade.robo import DIR_DT
from quant.pesquisa import lab

ARQ_MODO = os.path.join(os.path.dirname(DIR_DT), "modo_robo.json")
ARQ_DECISOES = os.path.join(lab.PASTA, "decisoes.jsonl")
DIR_RELATORIOS = os.path.join(os.path.dirname(DIR_DT), "relatorios")
# as tres leituras que o robo tem escritas a mao: a chave em modo_robo.json e o veredito do historico
PROPRIAS = {
    "reversão do dado": {"chave": "dado_opera", "aprovada": True,
                         "historico": "descoberta +R$ 116, validacao +R$ 19, prova +R$ 91 por negocio (2 contratos)"},
    "climax de volume": {"chave": "climax_opera", "aprovada": False,
                         "historico": "ganhou em 2026, perdeu R$ 16,50 por negocio de 2021 a 2025"},
    "nível e reação": {"chave": "niveis_opera", "aprovada": False, "historico": "perde cerca de R$ 23 por negocio em 888 pregoes"},
}
PROTOCOLO = {"rebaixa_negocios": 10, "rebaixa_soma": -1500.0, "rebaixa_media": -50.0, "promove_sinais": 20, "promove_t": 1.0,
             "estudo_sinais": 60, "estudo_t": 2.0, "max_operando": 3, "max_promocoes": 1}


def _t(x):
    x = np.asarray(x, dtype=float)
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 3 and x.std(ddof=1) > 0 else 0.0


def placar(pasta=DIR_DT, setup="niveis", pasta_mt5=None):
    """{tecnica: {sinais, media, t, soma, acerto, operados, soma_operados, media_operados, pregoes, ultimo}} com o que cada
    sinal guardado deu ou teria dado (2 contratos, depois de custo)."""
    fora = {}
    for x in medir.sinais(setup, pasta, pasta_mt5):
        fora.setdefault(x["tecnica"] or "?", []).append(x)
    res = {}
    for tec, lista in fora.items():
        r = [x["resultado"] for x in lista]
        op = [x["resultado"] for x in lista if x["opera"]]
        res[tec] = {"sinais": len(r), "media": round(float(np.mean(r)), 2), "t": round(_t(r), 2), "soma": round(float(np.sum(r)), 2),
                    "acerto": round(float(np.mean([v > 0 for v in r]) * 100), 1), "operados": len(op),
                    "soma_operados": round(float(np.sum(op)), 2) if op else 0.0,
                    "media_operados": round(float(np.mean(op)), 2) if op else 0.0,
                    "pregoes": len({x["dia"] for x in lista}), "ultimo": max(x["dia"] for x in lista)}
    return res


def leituras(modo, registro):
    """Todas as leituras, proprias e de laboratorio, com o estado de agora."""
    fora = []
    for tec, cfg in PROPRIAS.items():
        fora.append({"tecnica": tec, "tipo": "propria", "chave": cfg["chave"], "aprovada": cfg["aprovada"], "historico": cfg["historico"],
                     "opera": bool(modo.get(cfg["chave"], False))})
    for r in registro:
        fora.append({"tecnica": r.get("titulo") or r["nome"], "tipo": "laboratorio", "nome": r["nome"], "aprovada": bool(r.get("aprovada", True)),
                     "historico": r.get("historico") or "", "opera": r.get("estado") == "opera", "estado": r.get("estado") or "medido"})
    return fora


def decidir(lista, pl, modo, protocolo=PROTOCOLO):
    """As mudancas que o protocolo manda. Devolve [{tecnica, acao: 'rebaixa'|'promove'|'estudo', motivo}]."""
    travado = set(modo.get("travado_pelo_douglas") or [])
    fora, operando, promovidas = [], sum(1 for x in lista if x["opera"]), 0
    for x in lista:
        p = pl.get(x["tecnica"]) or {}
        if x.get("chave") in travado or x.get("nome") in travado:
            continue
        if x["opera"] and not x["aprovada"]:
            fora.append({"tecnica": x["tecnica"], "acao": "rebaixa", "motivo": f"reprovada no historico ({x['historico']})"})
            operando -= 1
        elif x["opera"] and p.get("operados", 0) >= protocolo["rebaixa_negocios"] and \
                (p["soma_operados"] <= protocolo["rebaixa_soma"] or p["media_operados"] <= protocolo["rebaixa_media"]):
            fora.append({"tecnica": x["tecnica"], "acao": "rebaixa",
                         "motivo": f"ao vivo: {p['operados']} negocios, soma R$ {p['soma_operados']:.0f}, media R$ {p['media_operados']:.0f}"})
            operando -= 1
    for x in lista:
        p = pl.get(x["tecnica"]) or {}
        if x.get("chave") in travado or x.get("nome") in travado or x["opera"]:
            continue
        bom = p.get("sinais", 0) >= protocolo["promove_sinais"] and p.get("media", 0) > 0 and p.get("t", 0) >= protocolo["promove_t"]
        if x["aprovada"] and bom and promovidas < protocolo["max_promocoes"] and operando < protocolo["max_operando"]:
            fora.append({"tecnica": x["tecnica"], "acao": "promove",
                         "motivo": f"aprovada no historico e, ao vivo, {p['sinais']} sinais com media R$ {p['media']:.0f} (t {p['t']:.1f})"})
            promovidas += 1
            operando += 1
        elif not x["aprovada"] and p.get("sinais", 0) >= protocolo["estudo_sinais"] and p.get("media", 0) > 0 and p.get("t", 0) >= protocolo["estudo_t"]:
            fora.append({"tecnica": x["tecnica"], "acao": "estudo",
                         "motivo": f"reprovada no historico, mas ao vivo {p['sinais']} sinais com media R$ {p['media']:.0f} (t {p['t']:.1f}): reestudar"})
    return fora


def aplicar(decisoes, lista, arq_modo=ARQ_MODO, arq_setups=None, arq_decisoes=ARQ_DECISOES):
    """Grava as mudancas (rebaixa e promove) nas chaves do robo e no registro das regras de laboratorio."""
    por_tec = {x["tecnica"]: x for x in lista}
    modo = ler_json(arq_modo, padrao=None) or {}
    arq_setups = arq_setups or regras_lab.ARQ_SETUPS
    try:
        with open(arq_setups, encoding="utf-8") as f:
            reg = json.load(f)
    except (OSError, ValueError):
        reg = {"regras": []}
    mudou_modo = mudou_reg = False
    quando = agora_brt().isoformat(timespec="seconds")
    for d in decisoes:
        if d["acao"] not in ("rebaixa", "promove"):
            continue
        x, liga = por_tec[d["tecnica"]], d["acao"] == "promove"
        if x["tipo"] == "propria":
            modo[x["chave"]] = liga
            mudou_modo = True
        else:
            for r in reg.get("regras") or []:
                if r.get("nome") == x["nome"]:
                    r["estado"], r["estado_desde"], r["estado_motivo"] = ("opera" if liga else "medido"), quando, d["motivo"]
                    mudou_reg = True
    if mudou_modo:
        modo.update(rotina_da_noite=quando)
        gravar_atomico(arq_modo, json.dumps(modo, ensure_ascii=False))
    if mudou_reg:
        gravar_atomico(arq_setups, json.dumps(reg, ensure_ascii=False, indent=1))
    if decisoes:
        garantir_dir(os.path.dirname(arq_decisoes))
        with open(arq_decisoes, "a", encoding="utf-8") as f:
            for d in decisoes:
                f.write(json.dumps(dict(d, quando=quando), ensure_ascii=False) + "\n")
    return mudou_modo or mudou_reg


def relatorio(lista, pl, decisoes, ensaio=False):
    agora = agora_brt()
    linhas = [f"# Rotina da noite do robo - {agora.strftime('%d/%m/%Y %H:%M')}" + (" (ENSAIO: nada foi gravado)" if ensaio else ""), ""]
    linhas.append("## O que mudou no robo")
    mud = [d for d in decisoes if d["acao"] in ("rebaixa", "promove")]
    if not mud:
        linhas.append("Nada: as leituras seguem como estavam.")
    for d in mud:
        linhas.append(f"- {d['tecnica']}: {'PASSA A OPERAR' if d['acao'] == 'promove' else 'PASSA A SO MEDIR'} ({d['motivo']}).")
    for d in decisoes:
        if d["acao"] == "estudo":
            linhas.append(f"- PEDIDO DE ESTUDO, {d['tecnica']}: {d['motivo']}.")
    linhas += ["", "## Placar ao vivo (todo sinal guardado; 2 contratos, depois de custo)", "",
               "| Leitura | Estado amanha | Sinais | Acerto | Media por sinal | Soma | Operados (soma) |", "|---|---|---|---|---|---|---|"]
    amanha = {x["tecnica"]: x["opera"] for x in lista}
    for d in mud:
        amanha[d["tecnica"]] = d["acao"] == "promove"
    for x in lista:
        p = pl.get(x["tecnica"])
        est = "opera" if amanha[x["tecnica"]] else "so mede"
        if not p:
            linhas.append(f"| {x['tecnica']} | {est} | 0 | - | - | - | - |")
            continue
        linhas.append(f"| {x['tecnica']} | {est} | {p['sinais']} em {p['pregoes']} pregoes | {p['acerto']:.0f}% | R$ {p['media']:+.2f} (t {p['t']:+.1f}) | "
                      f"R$ {p['soma']:+.0f} | {p['operados']} (R$ {p['soma_operados']:+.0f}) |")
    linhas += ["", "## O historico de cada leitura"] + [f"- {x['tecnica']}: {'APROVADA' if x['aprovada'] else 'reprovada'} - {x['historico']}" for x in lista]
    linhas += ["", "Com menos de 100 sinais por leitura, as medias ao vivo ainda sao acaso: o protocolo so age com as contagens minimas."]
    return "\n".join(linhas)


def rodar(ensaio=False, pasta=DIR_DT, arq_modo=ARQ_MODO, arq_setups=None, pasta_mt5=None):
    hm = agora_brt().strftime("%H:%M")
    if not ensaio and "09:00" <= hm < "18:30" and agora_brt().weekday() < 5:
        raise SystemExit("O pregao esta aberto: a rotina da noite nao muda o robo agora. Rode depois das 18h30, ou com --ensaio.")
    modo = ler_json(arq_modo, padrao=None) or {}
    registro = regras_lab.ler_registro(arq_setups)
    lista = leituras(modo, registro)
    pl = placar(pasta, pasta_mt5=pasta_mt5)
    decisoes = decidir(lista, pl, modo)
    if not ensaio:
        aplicar(decisoes, lista, arq_modo, arq_setups)
    texto = relatorio(lista, pl, decisoes, ensaio)
    if not ensaio:
        garantir_dir(DIR_RELATORIOS)
        gravar_atomico(os.path.join(DIR_RELATORIOS, f"noite_{agora_brt().strftime('%Y-%m-%d')}.md"), texto)
    return texto, decisoes


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Rotina da noite do robo de day trade (simulacao)")
    ap.add_argument("--ensaio", action="store_true", help="mostra o que faria, sem gravar nada")
    print(rodar(ensaio=ap.parse_args().ensaio)[0])
