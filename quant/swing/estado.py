"""
Estado do livro de swing: posicoes abertas (com capital e so medidas), operacoes fechadas e a conciliacao com as barras oficiais da B3.

Arquivos em `quant/saida/swing/` (pasta trocavel pela variavel de ambiente QUANT_SWING_DIR, que e como o ensaio roda sem tocar nos arquivos de verdade):
  estado.json       posicoes (abertas, pendentes de entrada) e a data da ultima conciliacao
  fechadas.jsonl    uma linha por operacao fechada (com capital ou so medida), para o placar e para o banco de dados que o Douglas quer crescendo

DOIS MODOS:
  - "capital": a operacao usa dinheiro do livro (setup com evidencia, ou liberado por decisao do Douglas). Entra ao vivo, na abertura do dia, e o
    robo vigia o stop durante o pregao. Ordem que so existiu depois da abertura entra no ultimo preco (`entrada_fora_da_abertura`); na conciliacao,
    do dia dela so conta o fechamento.
  - "medida": a operacao e simulada com valor padrao (R$ 6.000) so para medir o setup, sem capital. Cada sinal vira UMA operacao medida por setup. Ela
    nasce "pendente" na boleta da manha e e resolvida pelas barras OFICIAIS (abertura, maxima, minima, fechamento) na conciliacao da manha seguinte,
    com a mesma regra da pesquisa: e isso que faz o placar ser comparavel com os 15 anos testados. As sobreposicoes (metade de cima do ranking,
    Ibovespa acima da media de 200) vao marcadas na operacao e filtradas na hora de contar o placar.

SAIDA (mesma regra do pre-registro): stop, alvo ou tempo (no maximo 10 pregoes, o dia da entrada e o 1o). `saida_da_operacao` e a versao de UMA operacao da regra
de `simulador.operacoes`; um teste confere que as duas dao o mesmo resultado.
"""
import json
import os

import numpy as np
import pandas as pd

from quant import custos as cst
from quant.comum import DIR_SAIDA, agora_brt, garantir_dir, gravar_atomico
from quant.dados import calendario
from quant.swing import posicao as pos_mod
from quant.swing.tamanho import LOTE, PRECO_MAX_LOTE

DIR = os.environ.get("QUANT_SWING_DIR") or os.path.join(DIR_SAIDA, "swing")
VALOR_MEDIDO = 6_000.0
MOTIVOS = {"stop": "stop atingido", "gap_stop": "stop atingido com gap (saiu na abertura, pior que o stop)", "alvo": "alvo atingido",
           "gap_alvo": "alvo atingido na abertura", "tempo": "prazo de pregões esgotado"}


def arq(nome):
    return os.path.join(os.environ.get("QUANT_SWING_DIR") or DIR, nome)


def _d(x):
    return pd.Timestamp(x).date()


# ─────────────────────────────────────────────────────────────
# Datas
# ─────────────────────────────────────────────────────────────
def prazo_ate(entrada_em, prazo):
    """Data do pregao em que o prazo vence: o dia da entrada e o 1o. prazo=1 vence no proprio dia."""
    d = _d(entrada_em)
    for _ in range(int(prazo) - 1):
        d = calendario.proximo_pregao(d)
    return d


def pregoes_na_posicao(entrada_em, hoje):
    """Quantos pregoes a posicao ja viveu, contando o dia da entrada e o de hoje (>= 1 depois da entrada)."""
    e, h = _d(entrada_em), _d(hoje)
    if h < e:
        return 0
    return len(calendario.pregoes(e, h))


def pregoes_restantes(entrada_em, hoje, prazo):
    return max(int(prazo) - pregoes_na_posicao(entrada_em, hoje), 0)


# ─────────────────────────────────────────────────────────────
# Posicao
# ─────────────────────────────────────────────────────────────
def _custo_lado(valor, adtv, preco):
    return cst.custo_ordem(valor, adtv, fracionario=bool(preco > PRECO_MAX_LOTE))["total"] if valor > 0 else 0.0


def nova_posicao(setup, ticker, sinal_em, preco_entrada, stop_dist, alvo_dist, prazo, qtd, entrada_em, adtv, modo="medida", porque="",
                 overlays=None, ficha=None, preco_ref=None, origem="vivo", extras=None):
    """Posicao aberta. `stop_dist` e `alvo_dist` (R$ por acao, preco real) vem do ATR do dia do sinal; o stop e o alvo partem do preco de entrada."""
    alvo_dist = None if alvo_dist in (None, 0) else float(alvo_dist)
    pos_mod.validar(prazo, stop_dist, alvo_dist)
    pe = float(preco_entrada)
    valor = float(qtd) * pe
    custo = _custo_lado(valor, adtv, pe)
    out = {"id": f"{_d(entrada_em)}|{setup}|{ticker}|{modo}", "setup": setup, "ticker": ticker, "modo": modo, "status": "aberta",
           "sinal_em": str(_d(sinal_em)), "entrada_em": str(_d(entrada_em)), "preco_ref": preco_ref, "preco_entrada": pe,
           "stop_dist": float(stop_dist), "alvo_dist": alvo_dist,
           "stop": round(pe - float(stop_dist), 4), "alvo": None if alvo_dist is None else round(pe + alvo_dist, 4),
           "prazo": int(prazo), "prazo_ate": str(prazo_ate(entrada_em, prazo)), "qtd": int(qtd), "valor": valor, "adtv": float(adtv or 0.0),
           "custo_entrada": float(custo), "porque": porque, "overlays": overlays or {}, "ficha": ficha or {}, "origem_entrada": origem}
    if extras:
        out.update(extras)
    return out


def nova_pendente(setup, ticker, sinal_em, entrada_em, stop_dist, alvo_dist, prazo, adtv, porque="", overlays=None, preco_ref=None, ficha=None,
                  valor=VALOR_MEDIDO, extras=None):
    """Operacao medida que ainda nao entrou: espera a barra oficial do dia da entrada para ter abertura, stop e alvo."""
    alvo_dist = None if alvo_dist in (None, 0) else float(alvo_dist)
    pos_mod.validar(prazo, stop_dist, alvo_dist)
    out = {"id": f"{_d(entrada_em)}|{setup}|{ticker}|medida", "setup": setup, "ticker": ticker, "modo": "medida", "status": "pendente",
           "sinal_em": str(_d(sinal_em)), "entrada_em": str(_d(entrada_em)), "preco_ref": preco_ref, "stop_dist": float(stop_dist), "alvo_dist": alvo_dist,
           "prazo": int(prazo), "prazo_ate": str(prazo_ate(entrada_em, prazo)), "valor_alvo": float(valor), "adtv": float(adtv or 0.0),
           "porque": porque, "overlays": overlays or {}, "ficha": ficha or {}}
    if extras:
        out.update(extras)
    return out


def marcar(pos, preco, hoje):
    """Campos que a tela mostra: pregoes na posicao, restantes e resultado em aberto (sem custo de saida)."""
    if pos.get("status") == "pendente" or pos.get("preco_entrada") is None:
        return {"pregoes_na_posicao": 0, "pregoes_restantes": int(pos["prazo"]), "preco_atual": preco, "resultado_rs": None, "resultado_pct": None}
    n = pregoes_na_posicao(pos["entrada_em"], hoje)
    r = (float(preco) - pos["preco_entrada"]) * pos["qtd"] - pos["custo_entrada"] if preco is not None else None
    return {"pregoes_na_posicao": n, "pregoes_restantes": max(int(pos["prazo"]) - n, 0), "preco_atual": preco,
            "resultado_rs": None if r is None else float(r), "resultado_pct": None if r is None or not pos["valor"] else float(r / pos["valor"])}


def fechar(pos, preco_saida, motivo, dia, origem="vivo"):
    """Posicao fechada: resultado liquido dos custos dos dois lados."""
    v_saida = float(preco_saida) * pos["qtd"]
    c_out = _custo_lado(v_saida, pos.get("adtv"), pos["preco_entrada"])
    liquido = v_saida - pos["valor"] - pos["custo_entrada"] - c_out
    risco = pos["stop_dist"] * pos["qtd"]
    out = dict(pos)
    out.update({"status": "fechada", "saida_em": str(_d(dia)), "preco_saida": float(preco_saida), "motivo_saida": motivo, "texto_saida": MOTIVOS.get(motivo, motivo),
                "custo_saida": float(c_out), "resultado_rs": float(liquido), "resultado_pct": float(liquido / pos["valor"]) if pos["valor"] else None,
                "r_multiplo": float(liquido / risco) if risco > 0 else None, "pregoes": pregoes_na_posicao(pos["entrada_em"], dia), "origem_saida": origem})
    return out


# ─────────────────────────────────────────────────────────────
# A regra de saida de UMA operacao (mesma de simulador.operacoes)
# ─────────────────────────────────────────────────────────────
def saida_da_operacao(O, H, L, C, stop, alvo, prazo):
    """(k, preco, motivo) da primeira saida entre as barras dadas (k=0 e o dia da entrada, entrada na abertura O[0]), ou None se ainda nao saiu.
    Gap contra o stop: sai na abertura; gap a favor do alvo: sai na abertura; stop e alvo na mesma barra: vale o stop; prazo: fechamento do pregao `prazo`."""
    n = min(len(O), int(prazo))
    for k in range(n):
        o, h, l, c = O[k], H[k], L[k], C[k]
        if k >= 1 and o <= stop:
            return k, float(o), "gap_stop"
        if k >= 1 and alvo is not None and o >= alvo:
            return k, float(o), "gap_alvo"
        if l <= stop:
            return k, float(stop), "stop"
        if alvo is not None and h >= alvo:
            return k, float(alvo), "alvo"
        if k == int(prazo) - 1:
            return k, float(c), "tempo"
    return None


# ─────────────────────────────────────────────────────────────
# Arquivos
# ─────────────────────────────────────────────────────────────
def vazio():
    return {"posicoes": [], "conciliado_ate": None, "diario": [], "criado_em": agora_brt().isoformat(timespec="seconds")}


def carregar(caminho=None):
    try:
        with open(caminho or arq("estado.json"), encoding="utf-8") as f:
            e = json.load(f)
        if isinstance(e, dict) and isinstance(e.get("posicoes"), list):
            e.setdefault("diario", [])
            return e
    except (OSError, ValueError):
        pass
    return vazio()


def salvar(estado, caminho=None):
    c = caminho or arq("estado.json")
    garantir_dir(os.path.dirname(c))
    estado["atualizado_em"] = agora_brt().isoformat(timespec="seconds")
    estado["diario"] = estado.get("diario", [])[-300:]
    gravar_atomico(c, json.dumps(estado, ensure_ascii=False, indent=1, default=str))


def anotar(estado, tipo, texto, quando=None):
    estado.setdefault("diario", []).append({"hora": (quando or agora_brt()).strftime("%Y-%m-%d %H:%M:%S"), "tipo": tipo, "texto": texto})


def anexar_fechada(pos, caminho=None):
    """Uma linha por operacao fechada. Idempotente pelo id: a mesma operacao nao entra duas vezes."""
    c = caminho or arq("fechadas.jsonl")
    garantir_dir(os.path.dirname(c))
    if pos["id"] in {x.get("id") for x in fechadas(c)}:
        return False
    with open(c, "a", encoding="utf-8") as f:
        f.write(json.dumps(pos, ensure_ascii=False, default=str) + "\n")
    return True


def fechadas(caminho=None):
    out = []
    try:
        with open(caminho or arq("fechadas.jsonl"), encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if linha:
                    try:
                        out.append(json.loads(linha))
                    except ValueError:
                        continue
    except OSError:
        pass
    return out


def adicionar(estado, pos):
    """Poe a posicao no estado, sem duplicar (mesmo id = mesma operacao). Devolve True se entrou."""
    if any(x["id"] == pos["id"] for x in estado["posicoes"]) or pos["id"] in {x.get("id") for x in fechadas()}:
        return False
    estado["posicoes"].append(pos)
    return True


# ─────────────────────────────────────────────────────────────
# Conciliacao com as barras oficiais
# ─────────────────────────────────────────────────────────────
def _quantidade_medida(valor, preco):
    lote = LOTE if preco <= PRECO_MAX_LOTE else 1
    return int(valor / preco // lote) * lote


def conciliar(estado, painel, hoje=None):
    """Refaz com as barras oficiais do COTAHIST (`painel`, de `dados.montar`) o que o robo ao vivo nao viu.

    - Pendentes (operacoes medidas): quando a barra do dia da entrada existe, entram na abertura oficial e seguem a regra de saida da pesquisa.
    - Abertas: qualquer posicao que as barras mostram ja ter saido (stop, alvo ou prazo) e fechada na data e preco da barra.
    So conta barras COMPLETAS (datas anteriores a `hoje`). Papel que sumiu do painel, ou barra sem negocio, deixa a posicao como esta;
    pendente que nao pode entrar (sem negocio no dia, dado invalido) vai para o arquivo como "descartada" com o motivo.
    Devolve a lista das operacoes que fecharam agora."""
    hoje = _d(hoje) if hoje is not None else _d(agora_brt())
    datas = painel.datas
    fim = int((datas < pd.Timestamp(hoje)).sum())              # barras completas: datas < hoje
    novas, restantes = [], []
    for pos in estado["posicoes"]:
        if pos.get("status") not in ("aberta", "pendente") or pos["ticker"] not in painel.tickers:
            restantes.append(pos)
            continue
        j = painel.tickers.index(pos["ticker"])
        i0 = int(np.searchsorted(datas.values, np.datetime64(pd.Timestamp(pos["entrada_em"]))))
        if i0 >= fim or datas[i0].date() != _d(pos["entrada_em"]):
            restantes.append(pos)                              # a barra do dia da entrada ainda nao existe
            continue
        sl = slice(i0, min(i0 + int(pos["prazo"]), fim))
        O, H, L, C = (a[sl, j] for a in (painel.O, painel.H, painel.L, painel.C))
        if pos["status"] == "pendente":
            if not np.isfinite(O[0]) or O[0] <= 0 or not np.isfinite(painel.preco_cru[i0, j]) or not np.isfinite(painel.C[i0, j]) or painel.C[i0, j] <= 0:
                novas.append(_descartar(pos, "sem negócio no dia da entrada", datas[i0].date()))
                continue
            preco_real = float(O[0] * painel.preco_cru[i0, j] / painel.C[i0, j])
            qtd = _quantidade_medida(pos["valor_alvo"], preco_real)
            if qtd <= 0:
                novas.append(_descartar(pos, "valor padrão não compra nem um lote", datas[i0].date()))
                continue
            base = {k: v for k, v in pos.items() if k not in ("status", "valor_alvo")}
            pos = nova_posicao(pos["setup"], pos["ticker"], pos["sinal_em"], preco_real, pos["stop_dist"], pos["alvo_dist"], pos["prazo"], qtd,
                               pos["entrada_em"], pos["adtv"], modo="medida", porque=pos["porque"], overlays=pos["overlays"], ficha=pos["ficha"],
                               preco_ref=pos.get("preco_ref"), origem="conciliacao")
            for k, v in base.items():                                # o que veio com o sinal (conviccao da mesa, etiqueta da camada de julgamento...) acompanha a operacao
                pos.setdefault(k, v)
        ruim = painel.ruim[sl, j]
        ruim_ou_vazio = ~(np.isfinite(O) & np.isfinite(H) & np.isfinite(L) & np.isfinite(C)) | ruim
        n = len(O)
        ate = int(np.argmax(ruim_ou_vazio)) if ruim_ou_vazio.any() else n          # primeira barra invalida: a regra da pesquisa descarta a operacao
        e = O[0] if n else np.nan
        if pos.get("entrada_fora_da_abertura") and n:
            # entrou no meio do pregao (ordem liberada depois da abertura): a base e o preco de entrada no mesmo ajuste das barras, e do dia da
            # entrada so vale o fechamento, que e posterior a entrada (a maxima e a minima podem ser de antes dela)
            cru, aj = painel.preco_cru[i0, j], painel.C[i0, j]
            if not (np.isfinite(cru) and np.isfinite(aj) and cru > 0 and aj > 0):
                restantes.append(pos)
                continue
            e = pos["preco_entrada"] * aj / cru
            H, L = H.copy(), L.copy()
            H[0] = L[0] = C[0]
        r = saida_da_operacao(O[:ate] / e, H[:ate] / e, L[:ate] / e, C[:ate] / e, 1.0 - pos["stop_dist"] / pos["preco_entrada"],
                              None if pos["alvo"] is None else 1.0 + pos["alvo_dist"] / pos["preco_entrada"], pos["prazo"]) if ate > 0 else None
        if r is None:
            if ate < n and pos["modo"] == "medida":
                novas.append(_descartar(pos, "dia com dado inválido na janela da operação", datas[i0].date()))
            else:
                restantes.append(pos)
            continue
        k, preco_rel, motivo = r
        novas.append(fechar(pos, preco_rel * pos["preco_entrada"], motivo, datas[i0 + k].date(), origem="conciliacao"))
    estado["posicoes"] = [p for p in restantes]
    estado["conciliado_ate"] = str(datas[fim - 1].date()) if fim else estado.get("conciliado_ate")
    for f in novas:
        anexar_fechada(f)
    return novas


def _descartar(pos, motivo, dia):
    out = dict(pos)
    out.update({"status": "descartada", "motivo_descarte": motivo, "saida_em": str(_d(dia)), "resultado_rs": 0.0, "resultado_pct": None})
    return out
