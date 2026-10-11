"""
A tela do swing: monta o JSON que a area QUANT do terminal desenha (contrato em `quant/docs/tela_swing.md`).

O arquivo continua sendo `quant_fatores.json` (o mesmo que a carteira de fatores escrevia): as chaves de cima mantem o formato que a tela ja le
(vivo, capital, pronto, bloqueios, avisos, boleta, ordens, totais, carteira, mesa, serie, diario, fontes) e o bloco novo `swing` traz as regras em frases,
as posicoes, as candidatas do dia, o placar e a evidencia por setup. `modulo: "swing"` avisa a tela de qual robo e o arquivo.
Nada aqui calcula sinal nem decide entrada: so le o estado e escreve.
"""
import math
import numpy as np

from quant import mesa as mesa_mod
from quant.comum import agora_brt
from quant.swing import candidatas as cand_mod
from quant.swing import estado as est
from quant.swing import evidencia, posicao
from quant.swing.texto import brl, pct

PATRIMONIO_TOTAL = 100_000.0           # patrimonio da carteira (rodar_diario.CAPITAL_PADRAO): a exposicao de acoes e uma fracao dele
RECENTES = 40
MEDIDAS_ABERTAS_MAX = 150
NOTA_STOP = ("O stop é ordem a mercado simulada: sem gap, sai no último preço visto (pode ficar um pouco abaixo do stop); se o papel abrir "
             "abaixo do stop, sai na abertura, pior que o stop, e a perda passa do risco planejado. É o risco de qualquer swing trade.")


def _f(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────
# Posicoes
# ─────────────────────────────────────────────────────────────
def vista(pos, preco, hoje):
    m = est.marcar(pos, preco, hoje)
    pe = pos.get("preco_entrada")
    out = {"id": pos["id"], "setup": pos["setup"], "ticker": pos["ticker"], "modo": pos["modo"], "status": pos["status"],
           "entrada_em": pos["entrada_em"], "preco_entrada": pe, "stop": pos.get("stop"), "alvo": pos.get("alvo"), "prazo": pos["prazo"],
           "prazo_ate": pos["prazo_ate"], "qtd": pos.get("qtd"), "valor": pos.get("valor"), "porque": pos.get("porque"), "overlays": pos.get("overlays") or {},
           "variante": pos.get("variante"), "risco_rs": (pos["stop_dist"] * pos["qtd"]) if pos.get("qtd") else None, "sinal_em": pos.get("sinal_em"),
           "dist_stop_pct": (pos["stop_dist"] / pe) if pe else None, "dist_alvo_pct": (pos["alvo_dist"] / pe) if (pe and pos.get("alvo_dist")) else None}
    out.update(m)
    return out


def fechada_vista(f):
    return {k: f.get(k) for k in ("id", "setup", "ticker", "modo", "entrada_em", "saida_em", "preco_entrada", "preco_saida", "qtd", "valor", "motivo_saida",
                                  "texto_saida", "resultado_rs", "resultado_pct", "r_multiplo", "pregoes", "porque", "stop", "alvo", "prazo", "origem_saida")}


# ─────────────────────────────────────────────────────────────
# Livro de capital e placar
# ─────────────────────────────────────────────────────────────
def livro_capital(estado, fechadas, cfg, precos, hoje):
    cap0 = float(cfg["capital"])
    cap_fechadas = [f for f in fechadas if f.get("modo") == "capital" and f.get("status") == "fechada"]
    realizado = sum(float(f.get("resultado_rs") or 0.0) for f in cap_fechadas)
    abertas = [p for p in estado["posicoes"] if p.get("modo") == "capital" and p.get("status") == "aberta"]
    valor_mercado = 0.0
    custo_pago = 0.0
    nao_realizado = 0.0
    for p in abertas:
        px = _f(precos.get(p["ticker"])) or p["preco_entrada"]
        valor_mercado += px * p["qtd"]
        custo_pago += p["valor"] + p["custo_entrada"]
        nao_realizado += (px - p["preco_entrada"]) * p["qtd"] - p["custo_entrada"]
    caixa = cap0 + realizado - custo_pago
    patrimonio = caixa + valor_mercado
    hoje_s = str(hoje)
    dia = sum(float(f.get("resultado_rs") or 0.0) for f in cap_fechadas if f.get("saida_em") == hoje_s)
    return {"capital_inicial": cap0, "patrimonio": patrimonio, "caixa": caixa, "valor_posicoes": valor_mercado, "n_posicoes": len(abertas),
            "exposicao": valor_mercado / patrimonio if patrimonio > 0 else 0.0, "resultado_realizado_rs": realizado, "resultado_aberto_rs": nao_realizado,
            "resultado_rs": realizado + nao_realizado, "resultado_dia_rs": dia, "operacoes_fechadas": len(cap_fechadas),
            "sem_capital_em_uso": len(abertas) == 0 and not cap_fechadas}


def _metricas(res):
    """res: lista de resultado_pct (fracao, liquido de custos) -> acerto, expectativa, payoff."""
    r = np.array([x for x in res if x is not None and math.isfinite(x)], dtype=float)
    if len(r) == 0:
        return {"operacoes": 0, "acerto": None, "expectativa_pct": None, "payoff": None}
    ganho, perda = r[r > 0], r[r <= 0]
    payoff = float(ganho.mean() / abs(perda.mean())) if len(ganho) and len(perda) and perda.mean() != 0 else None
    return {"operacoes": int(len(r)), "acerto": float((r > 0).mean()), "expectativa_pct": float(r.mean()), "payoff": payoff}


def _passa_overlay(f, overlay):
    ov = f.get("overlays") or {}
    return overlay == "S0" or (overlay == "S1" and ov.get("top")) or (overlay == "S2" and ov.get("ibov_ok"))


def placar(fechadas, variantes):
    """Uma linha por variante (13 setups x 3 sobreposicoes) com o que o robo MEDIU ao vivo, ao lado do que a pesquisa viu."""
    medidas = [f for f in fechadas if f.get("modo") == "medida" and f.get("status") == "fechada"]
    linhas = []
    for vid, r in variantes.items():
        mine = [f for f in medidas if f["setup"] == r["nucleo"] and _passa_overlay(f, r["overlay"])]
        m = _metricas([f.get("resultado_pct") for f in mine])
        soma = sum(float(f.get("resultado_rs") or 0.0) for f in mine)
        linhas.append({"variante": vid, "setup": r["nucleo"], "sobreposicao": r["overlay"], "rotulo": r["rotulo"], **m, "resultado_rs": soma,
                       "pesquisa_descoberta": r["descoberta"], "pesquisa_validacao": r["validacao"], "status": r["status"], "status_texto": r["status_texto"],
                       "camada_de_julgamento": bool(r.get("camada_de_julgamento")), "etiqueta": r.get("etiqueta")})
    return linhas


def placar_capital(fechadas):
    cap = [f for f in fechadas if f.get("modo") == "capital" and f.get("status") == "fechada"]
    m = _metricas([f.get("resultado_pct") for f in cap])
    return {**m, "resultado_rs": sum(float(f.get("resultado_rs") or 0.0) for f in cap)}


# ─────────────────────────────────────────────────────────────
# Regras em frases
# ─────────────────────────────────────────────────────────────
def regras_gerais(cfg, exposicao_texto=None):
    r = cfg["risco"]
    return [
        "Operações de curto prazo: de 2 a 10 pregões. A saída é por stop, por alvo ou por tempo, o que vier primeiro. No 10º pregão a posição sai, sempre.",
        f"Entrada na abertura do pregão seguinte ao sinal. Cada posição arrisca {pct(r, 2)} do capital do livro ({brl(r * cfg['capital'], 0)} em "
        f"{brl(cfg['capital'], 0)}): a quantidade é o risco dividido pela distância até o stop.",
        f"Teto de {pct(cfg['teto_nome'], 0)} do capital por papel, no máximo {cfg['max_posicoes']} posições ao mesmo tempo, e a exposição total nunca passa da "
        f"exposição de ações do dia{(' (' + exposicao_texto + ')') if exposicao_texto else ''}.",
        "Só entra com capital o setup que passou na descoberta (2010-2017), na validação (2018-2021) e na prova (2022-2026). "
        "Os demais são só medidos: o robô registra o sinal e o resultado como se tivesse operado R$ 6.000, sem capital.",
        "A mesa veta (convicção -2) e prefere (convicção e setor positivos); o gestor não compra na véspera do resultado do papel, exceto nos setups de resultado.",
        "M1 e M2 medem a camada de julgamento da mesa em compras medidas de R$ 6.000: M1, os papéis com convicção +1 ou +2; M2, os vetados (convicção -2), "
        "para mostrar o que teria acontecido com eles (não é operação vendida). Sem teste histórico: só prova viva, e nunca recebem capital pela regra de evidência.",
        "Custos reais nos dois lados (corretagem, emolumentos, spread e impacto, `quant/custos.py`). Simulação: nenhuma ordem vai à corretora.",
        NOTA_STOP]


def regras_dos_setups(variantes):
    out = []
    for nid in dict.fromkeys(v["nucleo"] for v in variantes.values()):
        vs = [v for v in variantes.values() if v["nucleo"] == nid]
        forte = max(vs, key=lambda v: ["so_medido", "medindo", "liberado", "validado"].index(v["status"]))
        out.append({"setup": nid, "familia": vs[0]["familia"], "rotulo": vs[0]["rotulo"], "regra": cand_mod.frase_da_regra(nid),
                    "status": forte["status"], "status_texto": forte["status_texto"], "variantes": [v["id"] for v in vs],
                    "camada_de_julgamento": bool(vs[0].get("camada_de_julgamento")), "etiqueta": vs[0].get("etiqueta")})
    return out


def evidencia_por_setup(variantes):
    return [{"variante": v["id"], "setup": v["nucleo"], "sobreposicao": v["overlay"], "rotulo": v["rotulo"], "descoberta": v["descoberta"],
             "validacao": v["validacao"], "prova": v["prova"], "dsr": v["dsr"], "status": v["status"], "status_texto": v["status_texto"], "motivo": v["motivo"],
             "passaria_com_custo_leve": v["sensibilidade_custo_leve"],
             "camada_de_julgamento": bool(v.get("camada_de_julgamento")), "etiqueta": v.get("etiqueta")} for v in variantes.values()]


# ─────────────────────────────────────────────────────────────
# O bloco `swing` e o arquivo inteiro
# ─────────────────────────────────────────────────────────────
def bloco(estado, fechadas, boleta, variantes, cfg, hoje, precos, exposicao, avisos=None):
    precos = precos or {}
    cap_pos = [vista(p, _f(precos.get(p["ticker"])), hoje) for p in estado["posicoes"] if p.get("modo") == "capital" and p.get("status") == "aberta"]
    med_pos = [vista(p, _f(precos.get(p["ticker"])), hoje) for p in estado["posicoes"] if p.get("modo") == "medida" and p.get("status") in ("aberta", "pendente")]
    med_pos.sort(key=lambda v: (v["entrada_em"], v["setup"], v["ticker"]), reverse=True)
    lv = livro_capital(estado, fechadas, cfg, precos, hoje)
    cap_ids = evidencia.com_capital(variantes)
    boleta = boleta or {}
    linhas = boleta.get("candidatas") or []
    return {
        "v": 1,
        "estado": "com_capital" if cap_ids else "so_medido",
        "resumo_evidencia": evidencia.resumo(variantes),
        "regra_de_evidencia": evidencia.descricao_da_regra(),
        "regras": {"gerais": regras_gerais(cfg, exposicao.get("texto")), "setups": regras_dos_setups(variantes)},
        "dimensionamento": {"capital": cfg["capital"], "risco_por_operacao_pct": cfg["risco"] * 100, "risco_por_operacao_rs": cfg["risco"] * cfg["capital"],
                            "teto_por_papel_pct": cfg["teto_nome"] * 100, "max_posicoes": cfg["max_posicoes"], "prazo_max_pregoes": posicao.PRAZO_MAX,
                            "valor_por_operacao_medida_rs": cfg["valor_medido"], "exposicao_acoes_pct": (exposicao.get("fracao") or 0.0) * 100,
                            "exposicao_teto_rs": exposicao.get("teto_rs"), "exposicao_texto": exposicao.get("texto")},
        "livro": lv,
        "posicoes": cap_pos,
        "medidas_abertas": med_pos[:MEDIDAS_ABERTAS_MAX], "medidas_abertas_total": len(med_pos),
        "candidatas_hoje": {"sinal_em": boleta.get("sinal_em"), "entrada_prevista": boleta.get("data"), "total": len(linhas),
                            "com_capital": sum(1 for x in linhas if x.get("destino") == "capital"), "recusadas": sum(1 for x in linhas if x.get("destino") == "recusada"),
                            "so_medidas": sum(1 for x in linhas if x.get("destino") == "medida"),
                            "da_mesa": sum(1 for x in linhas if x.get("camada_de_julgamento")), "medidas_mesa": boleta.get("medidas_mesa"),
                            "linhas": [_linha(x) for x in linhas]},
        "placar": {"medido": placar(fechadas, variantes), "capital": placar_capital(fechadas)},
        "evidencia": evidencia_por_setup(variantes),
        "fechadas_recentes": [fechada_vista(f) for f in reversed([f for f in fechadas if f.get("status") == "fechada"][-RECENTES:])],
        "avisos": list(avisos or []) + list(cfg.get("avisos") or []),
    }


def _linha(x):
    campos = ("setup", "rotulo", "ticker", "sinal_em", "preco_ref", "stop_ref", "alvo_ref", "prazo", "adtv", "top", "ibov_ok", "porque", "destino", "motivo",
              "variante", "qtd", "valor", "risco_rs", "proximo_resultado", "resultado_antes_da_abertura", "nota_resultado", "mesa", "entrada_em",
              "visao_gerado", "etiqueta", "camada_de_julgamento")
    return {k: x.get(k) for k in campos}


def _livro_inteiro():
    """O cartao "Livro inteiro" (quant/risco/livro.py): pesos, mao e queda de cada modulo contra o orcamento. So informacao; sem arquivo, None."""
    try:
        from quant.risco import livro
        return livro.ler_bloco()
    except Exception:                                     # bloco informativo: nunca derruba a tela do swing
        return None


def tela(estado, fechadas, boleta, variantes, cfg, hoje, precos, exposicao, visao=None, motivo_visao=None, vivo=None, serie=None, avisos=None, bloqueios=None):
    """O JSON completo (chaves de cima no formato que a tela ja le + bloco `swing`)."""
    agora = agora_brt()
    avisos = [evidencia.resumo(variantes)] + [a for a in (boleta or {}).get("avisos") or []] + list(avisos or [])
    sw = bloco(estado, fechadas, boleta, variantes, cfg, hoje, precos, exposicao, avisos)
    lv = sw["livro"]
    boleta = boleta or {}
    entradas = [x for x in (boleta.get("candidatas") or []) if x.get("destino") == "capital"]
    bloqueios = list(bloqueios or boleta.get("bloqueios") or [])
    vivo_b = vivo or {"ligado": False, "fase": "aguardando_abertura", "fase_texto": "O robô de swing sobe no pregão.", "desde": None,
                      "batida": agora.isoformat(timespec="seconds"), "intervalo_s": None, "motor": {"ok": None}, "negocios_vistos": 0, "com_cotacao": 0,
                      "de": len(entradas)}
    return {
        "v": 1, "modulo": "swing", "gerado": agora.isoformat(timespec="seconds"), "vivo": vivo_b, "modo": "paper", "origem": "real",
        "capital": cfg["capital"], "pronto": bool(boleta.get("emitida")) and not bloqueios, "bloqueios": bloqueios,
        "avisos": sw["avisos"], "gate": {}, "frescor": boleta.get("frescor") or {},
        "boleta": {"data": boleta.get("data"), "id": boleta.get("id"), "emitida": bool(boleta.get("emitida")), "sinal_em": boleta.get("sinal_em"),
                   "gerado": boleta.get("gerado"), "motivo_bloqueio": [b.get("titulo") for b in bloqueios]},
        "ordens": [{"ticker": x["ticker"], "setup": x["setup"], "lado": "C", "qtd": x.get("qtd"), "preco_referencia": x["preco_ref"],
                    "stop": x["stop_ref"], "alvo": x["alvo_ref"], "prazo": x["prazo"], "porque": x["porque"]} for x in entradas],
        "totais": {"ordens": len(entradas), "financeiro_alvo": sum(float(x.get("valor") or 0.0) for x in entradas), "aberto": lv["valor_posicoes"]},
        "carteira": {"patrimonio": lv["patrimonio"], "caixa": lv["caixa"], "valor_posicoes": lv["valor_posicoes"], "n_posicoes": lv["n_posicoes"],
                     "exposicao": lv["exposicao"], "resultado_dia": lv["resultado_dia_rs"], "posicoes": sw["posicoes"]},
        "mesa": mesa_mod.bloco(visao, motivo_visao or ""),
        "livro": _livro_inteiro(),
        "swing": sw, "serie": list(serie or []), "diario": list(reversed((estado.get("diario") or [])[-200:])),
        "fontes": {"cotacoes": "motor do Autopilot Terminal (MetaTrader: último preço e abertura do dia)", "barras_oficiais": "B3 (COTAHIST)",
                   "mesa": "visão da mesa de análise", "pesquisa": "quant/saida/pesquisa_swing (pré-registro de 11/10/2026)"},
    }
