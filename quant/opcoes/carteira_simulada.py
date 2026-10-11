"""
CARTEIRA SIMULADA que acompanha o ranking de assimetrias (simulacao: nenhuma ordem real).

Todo dia em que rodar, com a cadeia nova:
  1. MARCA as posicoes abertas pela oferta de compra do fechamento (perna comprada) e pela oferta de venda (perna vendida), menos
     emolumento; sem oferta, pelo ultimo negocio; no vencimento, pelo valor intrinseco. Encerra as vencidas.
  2. ABRE ate 2 posicoes novas por dia entre as primeiras do ranking cuja familia NAO esta reprovada e cuja vantagem prudente e
     POSITIVA, com perda maxima de ate R$ 500 por estrutura (lotes de 100), no maximo 6 abertas e R$ 3.000 (3% de R$ 100 mil) em risco
     somado, sem repetir ativo + vencimento ja aberto. So estrutura de risco definido (compra de opcao, trava, straddle).
  3. CAPITAL PROTEGIDO (A0) e posicao PERMANENTE a parte: todo mes, para o primeiro vencimento mensal com 15+ pregoes pela frente, o
     orcamento de 1% do capital DA CLASSE de opcoes (R$ 300 com 30% do livro; ver `orcamento_mensal`) vira calls no dinheiro de 6 ativos (PETR4, VALE, BOVA11, ITUB4, BBDC4, BBAS3), em partes
     iguais, FRACIONADAS (a pesquisa nao arredonda lote: R$ 83 por ativo nao compra um lote de 100). O resto do capital fica no CDI e
     nao e contado aqui. Esse orcamento nao entra no limite de 6 posicoes nem nos R$ 3.000. Tranche com orcamento menor que o atual e COMPLETADA com a cadeia do dia (uma vez);
     tranche aberta com orcamento MAIOR que o atual (a de outubro de 2026, R$ 1.000) fica como esta: o que foi comprado nao se desfaz, a regra nova vale da proxima.
  4. ORCAMENTO DE QUEDA DO LIVRO (quant/risco/livro.py): com o orcamento estourado, nada novo abre (nem ranking nem tese); o que esta aberto segue marcado.
IDEMPOTENTE pela data da cadeia: rodar duas vezes com a mesma cadeia nao marca nem abre nada de novo.

Estado em quant/saida/opcoes/carteira_simulada.json. Nada aqui e recomendacao (Resolucao CVM 178).
"""
import json
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from quant.comum import DIR_SAIDA
from quant.opcoes import custos as C
from quant.opcoes import dados

DIR_ESTADO = os.path.join(DIR_SAIDA, "opcoes")
ARQ_ESTADO = os.path.join(DIR_ESTADO, "carteira_simulada.json")
CAPITAL = 100_000.0
RISCO_POR_ESTRUTURA = 500.0
MAX_ABERTAS = 6
RISCO_TOTAL_MAX = 0.03 * CAPITAL
MAX_NOVAS_POR_DIA = 2
ORCAMENTO_PCT = 0.01                       # 1% por mes (o Douglas aprovou subir de 0,5% para 1% em 10/10/2026)
ORCAMENTO_MENSAL = ORCAMENTO_PCT * CAPITAL  # base antiga (capital inteiro): so vale com o livro por classes desligado
ATIVOS_CAPITAL_PROTEGIDO = ["PETR4", "VALE3", "BOVA11", "ITUB4", "BBDC4", "BBAS3"]
LOTE = 100
FEE = C.FEE_PREMIO


def orcamento_mensal():
    """Premio do capital protegido por mes: 1% do capital DA CLASSE de opcoes (R$ 300 com 30% do livro).

    CORRECAO de 11/10/2026. Em 10/10 o orcamento subiu para 1% do capital INTEIRO (R$ 1.000). Com o livro em 60/30/10 so 30% do
    capital fica no caixa que protege a estrategia, e esse caixa rende perto de 1% ao mes: gastar R$ 1.000 por mes contra uns
    R$ 300 de rendimento deixava de ser "capital protegido" (o principal cairia todo mes ruim). O premio do mes tem de caber
    no rendimento do caixa da classe. Livro por classes desligado: vale a base antiga (capital inteiro)."""
    from quant.risco import livro
    return round(ORCAMENTO_PCT * CAPITAL * livro.peso("opcoes"), 2)


def limite_risco_v1():
    """Teto de risco aberto (fora o capital protegido) da vertente ESPECULATIVA: a fatia dela no orcamento de queda das opcoes (quant/opcoes/vertentes.py).
    Nunca acima do teto antigo de R$ 3.000."""
    from quant.opcoes import vertentes
    return min(RISCO_TOTAL_MAX, vertentes.limite_risco("especulativa"))


def livro_estourado():
    """True quando o orcamento de queda do livro estourou (quant/saida/risco/livro.json, gravado pela rotina). Sem arquivo: False."""
    from quant.risco import livro
    return bool((livro.ler_bloco() or {}).get("estourou"))


def _brl(x):
    return f"{x:,.0f}".replace(",", ".")


def _t(x, nd=1):
    """Numero no formato brasileiro (virgula decimal, ponto de milhar) para texto de tela."""
    return f"{x:,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def estado_vazio(dia):
    return {"desde": str(pd.Timestamp(dia).date()), "capital": CAPITAL, "ultima_data": None, "posicoes": [], "criado_em": datetime.now().isoformat(timespec="seconds")}


def carregar_estado(dia, caminho=ARQ_ESTADO):
    if os.path.exists(caminho):
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    return estado_vazio(dia)


def gravar_estado(est, caminho=ARQ_ESTADO):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(est, f, ensure_ascii=False, indent=1)
    os.replace(tmp, caminho)


# ------------------------------------------------------------------------------------------------------------- marcacao
def _preco_perna(perna, indice, spot, dia):
    """Valor unitario (por acao) para ENCERRAR a perna hoje + a origem. Comprada: vende na oferta de compra; vendida: recompra na de venda."""
    chave = (perna["codigo"], perna["vencimento"])
    venc = pd.Timestamp(perna["vencimento"])
    if venc <= dia:
        S = spot.get(perna["ativo"])
        K = float(indice[chave]["exercicio"]) if chave in indice else float(perna["exercicio"])
        if S is None or S != S:
            return perna.get("ultimo_valor", 0.0), "sem preço do ativo (mantido o último valor)"
        intr = max(S - K, 0.0) if perna["tipo"] == "call" else max(K - S, 0.0)
        return intr, "valor intrínseco no vencimento"
    if chave in indice:
        r = indice[chave]
        if perna["lado"] == "compra":
            if r["oferta_compra"] == r["oferta_compra"] and r["oferta_compra"] > 0:
                return float(r["oferta_compra"]), "oferta de compra do fechamento"
        else:
            if r["oferta_venda"] == r["oferta_venda"] and r["oferta_venda"] > 0:
                return float(r["oferta_venda"]), "oferta de venda do fechamento"
        return float(r["fech"]), "último negócio (sem oferta no fechamento)"
    return perna.get("ultimo_valor", perna["premio_entrada"]), "série sem negócio hoje (mantido o último valor)"


def marcar(pos, indice, spot, dia):
    """Atualiza valor_hoje e resultado_rs da posicao (aberta). Devolve True se venceu e foi encerrada."""
    total = 0.0
    origens = set()
    for p in pos["pernas"]:
        v, origem = _preco_perna(p, indice, spot, dia)
        p["ultimo_valor"] = v
        origens.add(origem)
        if p["lado"] == "compra":
            total += v * (1 - FEE) * p["qtd"]
        else:
            total -= v * (1 + FEE if pd.Timestamp(p["vencimento"]) > dia else 1.0) * p["qtd"]
    pos["valor_hoje"] = round(total, 2)
    pos["resultado_rs"] = round(total - pos["custo"], 2)
    pos["marcacao"] = "; ".join(sorted(origens))
    if pd.Timestamp(pos["vencimento"]) <= dia:
        pos["estado"] = "encerrada"
        pos["fechada_em"] = str(dia.date())
        pos["valor_final"] = pos["valor_hoje"]
        return True
    return False


# ------------------------------------------------------------------------------------------------------------- abertura
def _perna_estado(p, lado, qtd, ativo):
    return {"codigo": p["codigo"], "ativo": ativo, "tipo": "put" if p["tipo"] == "P" else "call", "lado": lado, "exercicio": round(float(p["exercicio"]), 2),
            "vencimento": str(pd.Timestamp(p["vencimento"]).date()),
            "premio_entrada": round(float(p["oferta_venda"] if lado == "compra" else p["oferta_compra"]), 2), "qtd": qtd}


def abrir_do_ranking(est, M, veredito_fn, dia):
    """Ate 2 posicoes novas do ranking (familia nao reprovada, vantagem prudente > 0, risco <= R$ 500/estrutura, 6 abertas, R$ 3.000)."""
    abertas = [p for p in est["posicoes"] if p["estado"] == "aberta" and not p.get("permanente")]
    risco = sum(p["risco_rs"] for p in abertas)
    novas = []
    df = M["ranking_bruto"]
    if df.empty:
        return novas
    for _, r in df.sort_values("vantagem", ascending=False).iterrows():
        if len(novas) >= MAX_NOVAS_POR_DIA or len(abertas) + len(novas) >= MAX_ABERTAS:
            break
        if r["vantagem"] <= 0:
            break
        if veredito_fn(r)["estado"] == "reprovada":
            continue
        if any(p["ativo"] == r["ativo"] and p["vencimento"] == r["vencimento"] for p in abertas + novas):
            continue
        qtd = int(math.floor(RISCO_POR_ESTRUTURA / r["perda_maxima"] / LOTE) * LOTE)
        if qtd < LOTE:
            continue
        risco_novo = qtd * r["perda_maxima"]
        if risco + sum(n["risco_rs"] for n in novas) + risco_novo > limite_risco_v1():
            continue
        pernas = [_perna_estado(p, lado, qtd, r["ativo"]) for p, lado in r["pernas_obj"]]
        custo = qtd * r["custo"]
        novas.append({"id": f"{pd.Timestamp(dia).date()}|{r['ativo']}|{r['estrutura']}|{r['vencimento']}", "aberta_em": str(pd.Timestamp(dia).date()),
                      "titulo": f"{r['rotulo']} em {r['ativo']}, vencimento {r['vencimento']}", "ativo": r["ativo"], "estrutura": r["estrutura"], "familia": r["familia"],
                      "pernas": pernas, "qtd": qtd, "custo": round(custo, 2), "valor_hoje": round(custo, 2), "resultado_rs": 0.0, "risco_rs": round(risco_novo, 2),
                      "vencimento": r["vencimento"], "estado": "aberta", "vantagem_na_abertura_pct": round(float(r["vantagem"]), 1),
                      "marcacao": "aberta nas ofertas do fechamento (compra na oferta de venda, venda na de compra)"})
    return novas


def abrir_capital_protegido(est, M, dia):
    """Tranche mensal do capital protegido: `orcamento_mensal()` em calls no dinheiro dos 6 ativos, partes iguais, fracionadas, primeiro vencimento mensal com 15+ pregoes."""
    from quant.opcoes.assimetrias import arbitragens_du
    venc = None
    for v in dados.vencimentos_padrao():
        if v > dia and arbitragens_du(dia, v) >= 15:
            venc = v
            break
    if venc is None:
        return None
    vstr = str(venc.date())
    if any(p.get("permanente") and p["vencimento"] == vstr for p in est["posicoes"]):
        return None
    o = M["o"]
    orc = orcamento_mensal()
    parte = orc / len(ATIVOS_CAPITAL_PROTEGIDO)
    pernas, custo = [], 0.0
    for a in ATIVOS_CAPITAL_PROTEGIDO:
        el = o[(o["ativo"] == a) & (o["vencimento"] == venc) & (o["tipo"] == "C") & o["boa"] & (o["negocios"] >= C.NEG_MIN) & o["oferta_venda"].notna()]
        if el.empty:
            continue
        S = float(el["S"].iloc[0])
        el = el.assign(_d=(el["exercicio"] / S - 1).abs()).sort_values(["_d", "negocios"], ascending=[True, False])
        r = el.iloc[0]
        if r["_d"] > 0.03:
            continue
        unit = float(r["oferta_venda"]) * (1 + FEE)
        qtd = parte / unit
        p = _perna_estado(r, "compra", qtd, a)
        pernas.append(p)
        custo += qtd * unit
    if not pernas:
        return None
    return {"id": f"{pd.Timestamp(dia).date()}|capital_protegido|{vstr}", "aberta_em": str(pd.Timestamp(dia).date()),
            "titulo": f"Capital protegido: orçamento mensal de R$ {_brl(orc)} em calls no dinheiro de {len(pernas)} ativos, vencimento {vstr}",
            "ativo": "cesta (" + ", ".join(p["ativo"] for p in pernas) + ")", "estrutura": "capital_protegido", "familia": "capital_protegido", "permanente": True, "orcamento_rs": orc,
            "pernas": pernas, "qtd": None, "custo": round(custo, 2), "valor_hoje": round(custo, 2), "resultado_rs": 0.0, "risco_rs": round(custo, 2), "vencimento": vstr,
            "estado": "aberta", "marcacao": "aberta nas ofertas do fechamento; quantidades fracionadas (sem arredondar lote)",
            "nota": "O resto do capital fica no CDI e não entra nesta conta. Perda máxima do mês = o orçamento."}


def completar_orcamento(est, M, indice, spot, dia):
    """Tranche permanente aberta com orcamento menor que o atual (ex.: R$ 500 quando o orcamento passou a R$ 1.000) recebe o que falta, em partes
    iguais entre os ativos que ja tem na tranche, com as ofertas de venda da cadeia do dia. Uma vez: depois disso orcamento_rs == orcamento_mensal().
    Tranche com orcamento MAIOR que o atual nao e mexida (o que foi comprado nao se desfaz)."""
    n = 0
    o = M["o"]
    orc = orcamento_mensal()
    for pos in est["posicoes"]:
        if not pos.get("permanente") or pos["estado"] != "aberta" or pd.Timestamp(pos["vencimento"]) <= dia:
            continue
        atual = pos.get("orcamento_rs", pos["custo"])
        falta = orc - atual
        if falta <= 0.01:
            continue
        parte = falta / len(pos["pernas"])
        gasto = 0.0
        for p in pos["pernas"]:
            r = o[(o["codigo"] == p["codigo"]) & (o["vencimento"] == pd.Timestamp(p["vencimento"])) & o["oferta_venda"].notna()]
            if r.empty:
                continue
            unit = float(r["oferta_venda"].iloc[0]) * (1 + FEE)
            add = parte / unit
            p["premio_entrada"] = round((p["premio_entrada"] * p["qtd"] + float(r["oferta_venda"].iloc[0]) * add) / (p["qtd"] + add), 4)
            p["qtd"] = p["qtd"] + add
            gasto += add * unit
        if gasto > 0:
            pos["custo"] = round(pos["custo"] + gasto, 2)
            pos["risco_rs"] = round(pos["risco_rs"] + gasto, 2)
            pos["orcamento_rs"] = round(atual + gasto, 2)
            pos["complementado_em"] = str(dia.date())
            pos["titulo"] = f"Capital protegido: orçamento mensal de R$ {_brl(orc)} em calls no dinheiro de {len(pos['pernas'])} ativos, vencimento {pos['vencimento']}"
            marcar(pos, indice, spot, dia)
            n += 1
    return n


def abrir_teses(est, expressoes_teses, dia):
    """Abre a expressao escolhida de cada tese (origem mesa ou robo, probabilidade definida), mesmo teto: R$ 500 por estrutura, 6 abertas e R$ 3.000."""
    abertas = [p for p in est["posicoes"] if p["estado"] == "aberta" and not p.get("permanente")]
    risco = sum(p["risco_rs"] for p in abertas)
    novas = []
    for t in expressoes_teses or []:
        if len(abertas) + len(novas) >= MAX_ABERTAS:
            break
        pid = f"{pd.Timestamp(dia).date()}|tese|{t['id']}|{t['expressao']['nome']}"
        if any(p.get("tese_id") == t["id"] and p["estado"] == "aberta" for p in est["posicoes"]) or any(p["id"] == pid for p in est["posicoes"]):
            continue
        e = t["expressao"]
        if e.get("perda_maxima_por_acao") is None or e["perda_maxima_por_acao"] <= 0:
            continue
        qtd = int(math.floor(RISCO_POR_ESTRUTURA / e["perda_maxima_por_acao"] / LOTE) * LOTE)
        if qtd < LOTE:
            continue
        risco_novo = qtd * e["perda_maxima_por_acao"]
        if risco + sum(n["risco_rs"] for n in novas) + risco_novo > limite_risco_v1():
            continue
        pernas = [{**p, "qtd": qtd} for p in e["pernas_estado"]]
        custo = qtd * e["custo_por_acao"]
        novas.append({"id": pid, "aberta_em": str(pd.Timestamp(dia).date()), "titulo": f"Tese {t['id']}: {e['titulo']}", "ativo": t["ativo"], "estrutura": e["nome"], "familia": "tese",
                      "origem": t["origem"], "tese_id": t["id"], "pernas": pernas, "qtd": qtd, "custo": round(custo, 2), "valor_hoje": round(custo, 2), "resultado_rs": 0.0,
                      "risco_rs": round(risco_novo, 2), "vencimento": e["vencimento"], "estado": "aberta",
                      "marcacao": "aberta nas ofertas do fechamento (compra na oferta de venda, venda na de compra)"})
    return novas


def ja_v1_hoje(est, dia):
    return any(p.get("familia") == "v1_call_barata" and p["aberta_em"] == str(pd.Timestamp(dia).date()) for p in est["posicoes"])


def abrir_v1_calls(est, candidatos, dia, max_abertas_v1=2):
    """VERTENTE ESPECULATIVA: ate 1 call nova por dia do ranking de calls baratas (pontos no minimo, lista `candidatos` ja filtrada por `vertentes.aviso_ranking_v1_para_livro`),
    perda maxima = premio pago, ate R$ 500 por estrutura, `max_abertas_v1` abertas desta regra e o teto de risco da vertente. Nao repete ativo + vencimento."""
    abertas = [p for p in est["posicoes"] if p["estado"] == "aberta" and not p.get("permanente")]
    if sum(1 for p in abertas if p.get("familia") == "v1_call_barata") >= max_abertas_v1 or len(abertas) >= MAX_ABERTAS:
        return []
    risco = sum(p["risco_rs"] for p in abertas)
    for c in candidatos or []:
        r = c["pernas_obj"]
        if any(p["ativo"] == c["ativo"] and p["vencimento"] == c["vencimento"] for p in abertas):
            continue
        unit = float(r["oferta_venda"]) * (1 + FEE)
        qtd = int(math.floor(RISCO_POR_ESTRUTURA / unit / LOTE) * LOTE)
        if qtd < LOTE:
            continue
        risco_novo = qtd * unit
        if risco + risco_novo > limite_risco_v1():
            continue
        perna = _perna_estado(r, "compra", qtd, c["ativo"])
        return [{"id": f"{pd.Timestamp(dia).date()}|{c['ativo']}|call_barata|{c['vencimento']}", "aberta_em": str(pd.Timestamp(dia).date()),
                 "titulo": f"Call no dinheiro em {c['ativo']}, strike {_t(c['strike'], 2)}, vencimento {c['vencimento']} ({c['pontos']} pontos no ranking de calls baratas)",
                 "ativo": c["ativo"], "estrutura": "call_no_dinheiro", "familia": "v1_call_barata", "vertente": "especulativa", "pontos_na_abertura": c["pontos"],
                 "pernas": [perna], "qtd": qtd, "custo": round(risco_novo, 2), "valor_hoje": round(risco_novo, 2), "resultado_rs": 0.0, "risco_rs": round(risco_novo, 2),
                 "vencimento": c["vencimento"], "estado": "aberta", "marcacao": "aberta na oferta de venda do fechamento",
                 "nota": "Perda máxima = prêmio pago. " + "; ".join(c.get("porque", []))}]
    return []


# ------------------------------------------------------------------------------------------------------------- principal
def atualizar(M, veredito_fn, caminho=ARQ_ESTADO, gravar=True, teses_abrir=None, calls_v1=None):
    """Roda um dia da carteira com a cadeia M (saida de assimetrias.montar). Devolve (posicoes, resultado, estado) para o JSON.
    Marcar e abrir do ranking acontecem uma vez por data de cadeia; completar o orcamento do capital protegido e abrir teses sao idempotentes pelo proprio estado."""
    dia = pd.Timestamp(M["dia"])
    est = carregar_estado(dia, caminho)
    ja = est.get("ultima_data") == str(dia.date())
    op, sp = M["op"], M["sp"]
    indice = {(r["codigo"], str(pd.Timestamp(r["vencimento"]).date())): r for _, r in op[op["dia"] == dia].iterrows()}
    spot = {r["ativo"]: float(r["fech"]) for _, r in sp[(sp["dia"] == dia) & (sp["fatcot"] == 1)].iterrows()}
    mudou = False
    travado = livro_estourado()                 # orcamento de queda do livro estourado: nada tatico novo (o capital protegido segue, e o seguro)
    if not ja:
        for pos in est["posicoes"]:
            if pos["estado"] == "aberta":
                marcar(pos, indice, spot, dia)
        novas = [] if travado else abrir_do_ranking(est, M, veredito_fn, dia)
        cp = abrir_capital_protegido(est, M, dia)
        est["posicoes"] += novas + ([cp] if cp else [])
        est["ultima_data"] = str(dia.date())
        mudou = True
    if completar_orcamento(est, M, indice, spot, dia):
        mudou = True
    nt = [] if travado else abrir_teses(est, teses_abrir, dia)
    if nt:
        est["posicoes"] += nt
        mudou = True
    nc = [] if (travado or ja_v1_hoje(est, dia)) else abrir_v1_calls(est, calls_v1, dia)
    if nc:
        est["posicoes"] += nc
        mudou = True
    if gravar and mudou:
        gravar_estado(est, caminho)
    pos = est["posicoes"]
    aberto = sum(p["resultado_rs"] for p in pos if p["estado"] == "aberta")
    real = sum(p["resultado_rs"] for p in pos if p["estado"] == "encerrada")
    resultado = {"aberto_rs": round(aberto, 2), "realizado_rs": round(real, 2), "acumulado_rs": round(aberto + real, 2),
                 "n_abertas": sum(1 for p in pos if p["estado"] == "aberta"), "n_encerradas": sum(1 for p in pos if p["estado"] == "encerrada"),
                 "risco_em_aberto_rs": round(sum(p["risco_rs"] for p in pos if p["estado"] == "aberta"), 2), "desde": est["desde"],
                 "capital_simulado_rs": CAPITAL, "ultima_data": est["ultima_data"], "regras": f"até {MAX_NOVAS_POR_DIA} novas por dia, perda máxima de R$ {_brl(RISCO_POR_ESTRUTURA)} por estrutura, "
                 f"{MAX_ABERTAS} abertas e R$ {_brl(limite_risco_v1())} em risco (vertente especulativa); capital protegido (R$ {_brl(orcamento_mensal())} por mês, 1% do capital da classe de opções) à parte"
                 + ("; ORÇAMENTO DE QUEDA DO LIVRO ESTOURADO: nada novo abre" if travado else ""),
                 "orcamento_mensal_rs": orcamento_mensal(), "livro_estourado": travado}
    saida = [{k: p.get(k) for k in ("id", "aberta_em", "titulo", "ativo", "estrutura", "pernas", "custo", "valor_hoje", "resultado_rs", "vencimento", "estado", "familia",
                                      "qtd", "risco_rs", "marcacao", "permanente", "fechada_em", "valor_final", "vantagem_na_abertura_pct", "nota", "origem", "tese_id",
                                      "orcamento_rs", "complementado_em", "pontos_na_abertura", "motivo_fechamento")} for p in pos]
    for d, p in zip(saida, pos):
        d["vertente"] = p.get("vertente", "especulativa")
    return saida, resultado, est
