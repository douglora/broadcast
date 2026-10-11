"""
Visao da mesa: a camada de julgamento (macro, setores e analise de cada empresa) sobre a selecao quantitativa.

POR QUE EXISTE. O teste longo da carteira (2016 a 2026, quant/saida/pesquisa_carteira/RESULTADO_HOLDOUT.md) mostrou que a
selecao por fatores, sozinha, nao gerou retorno alem de estar comprado em bolsa. Em 10/10/2026 o Douglas pediu: "como a
carteira e multifatorial precisamos fazer stock picking tambem dos ativos perante macro, analise bottom up, e
fundamentalista forte". A mesa de analise (o agente analista, que le balanco, release e cenario) grava
`quant/saida/mesa/visao_mesa.json`; este modulo aplica essa leitura a carteira de um jeito pequeno, explicito e auditavel:

  1. VETO: papel com conviccao -2 ("a mesa ve um problema que o filtro quantitativo nao ve") nao entra na selecao do mes.
     Se ja esta na carteira, sai pela regra normal de quem sumiu do universo.
  2. PESO: o peso 1/volatilidade de cada papel e multiplicado por (1 + 0,15 x conviccao) x (1 + 0,05 x inclinacao do
     setor), e o total volta a exposicao de antes. Conviccao +2 em setor +2 vale 1,43 vez o peso; -1 em setor -2, 0,77.
     O teto por nome continua valendo.
  3. Visao vencida (mais velha que `validade_dias`) ou ausente: NADA muda, e a tela diz isso.

O QUE ISTO NAO E. Nao ha teste historico desta camada: julgamento nao tem serie de 15 anos. Ela e medida daqui para a
frente, e toda mudanca que ela faz fica registrada (`aplicado`) com o motivo, para se poder cobrar depois. Nada aqui e
recomendacao: e a leitura interna da mesa para a simulacao.

Funcoes puras; quem le o arquivo e grava o painel e o `quant/rodar_diario.py`.
"""
import json
import os
from datetime import datetime, timedelta

import pandas as pd

from quant.comum import DIR_SAIDA

ARQ_VISAO = os.path.join(DIR_SAIDA, "mesa", "visao_mesa.json")
PASSO_CONVICCAO = 0.15          # cada ponto de conviccao mexe 15% no peso
PASSO_SETOR = 0.05              # cada ponto de inclinacao do setor mexe 5%
VETO = -2                       # conviccao que tira o papel da selecao
VALIDADE_PADRAO = 7             # dias


def _inteiro(x, lo=-2, hi=2):
    try:
        v = int(round(float(x)))
    except (TypeError, ValueError):
        return 0
    return max(lo, min(hi, v))


def ler(arq=ARQ_VISAO, hoje=None):
    """Devolve (visao, motivo). `visao` e None quando o arquivo nao existe, esta ilegivel ou venceu; `motivo` explica."""
    try:
        with open(arq, encoding="utf-8") as f:
            v = json.load(f)
    except FileNotFoundError:
        return None, "a mesa ainda não gravou a visão dela"
    except (OSError, ValueError) as e:
        return None, f"arquivo da mesa ilegível ({type(e).__name__})"
    if not isinstance(v, dict) or not v.get("gerado"):
        return None, "arquivo da mesa sem data"
    try:
        quando = datetime.fromisoformat(str(v["gerado"]))
    except ValueError:
        return None, "arquivo da mesa com data inválida"
    validade = int(v.get("validade_dias") or VALIDADE_PADRAO)
    agora = hoje if hoje is not None else datetime.now(quando.tzinfo)
    if not isinstance(agora, datetime):
        agora = datetime.combine(pd.Timestamp(agora).date(), datetime.min.time(), tzinfo=quando.tzinfo)
    if agora - quando > timedelta(days=validade):
        return None, f"visão da mesa vencida (de {quando.date()}, vale {validade} dias)"
    return v, f"visão da mesa de {quando.date()}"


def conviccoes(visao):
    """ticker -> conviccao (-2..2) dos papeis que a mesa analisou."""
    return {str(a["ticker"]).upper(): _inteiro(a.get("conviccao")) for a in (visao or {}).get("acoes") or [] if a.get("ticker")}


def inclinacoes(visao):
    """setor (minusculas) -> inclinacao (-2..2)."""
    return {str(s["setor"]).strip().lower(): _inteiro(s.get("inclinacao")) for s in (visao or {}).get("setores") or [] if s.get("setor")}


def _setor_da_mesa(setor_do_papel, incl):
    """A mesa escreve "bancos", "varejo"; o cadastro traz o macrossetor da CVM. Casa por palavra contida, sem inventar."""
    if not setor_do_papel:
        return 0
    s = str(setor_do_papel).strip().lower()
    if s in incl:
        return incl[s]
    for nome, v in incl.items():
        if nome and (nome in s or s in nome):
            return v
    return 0


def vetar(sinais_mes, visao):
    """Tira da tabela de sinais do mes os papeis com conviccao de veto. Devolve (tabela, registro)."""
    c = conviccoes(visao)
    fora = {t for t, v in c.items() if v <= VETO}
    if sinais_mes is None or not len(sinais_mes) or not fora:
        return sinais_mes, []
    acoes = {str(a.get("ticker")).upper(): a for a in (visao or {}).get("acoes") or []}
    tk = sinais_mes["ticker"].astype(str).str.upper()
    registro = [{"ticker": t, "efeito": "vetada", "porque": str((acoes.get(t) or {}).get("risco") or (acoes.get(t) or {}).get("tese") or "convicção -2 da mesa")}
                for t in sorted(fora) if (tk == t).any()]
    return sinais_mes[~tk.isin(fora)].copy(), registro


def fatores_de_peso(tickers, visao, setor=None):
    """ticker -> multiplicador do peso (1.0 = nao mexe), pela conviccao do papel e pela inclinacao do setor."""
    c, incl = conviccoes(visao), inclinacoes(visao)
    fora = {}
    for t in tickers:
        conv = c.get(str(t).upper(), 0)
        s = _setor_da_mesa((setor or {}).get(t), incl)
        fora[t] = (1.0 + PASSO_CONVICCAO * conv) * (1.0 + PASSO_SETOR * s)
    return fora


def ajustar_pesos(pesos, fatores, cap=None):
    """Aplica os multiplicadores e devolve o total a exposicao de antes. `cap`: teto por nome (o excesso e redistribuido
    entre os que ainda tem folga, em ate 5 passadas). `pesos`: Series ticker -> peso sobre o patrimonio."""
    if pesos is None or not len(pesos) or not fatores:
        return pesos
    total = float(pesos.sum())
    w = pesos.astype(float) * pd.Series({t: float(fatores.get(t, 1.0)) for t in pesos.index})
    if w.sum() <= 0:
        return pesos
    w = w * (total / w.sum())
    if cap is not None:
        for _ in range(5):
            acima = w > cap + 1e-12
            if not acima.any():
                break
            sobra = float((w[acima] - cap).sum())
            w[acima] = cap
            livre = ~acima & (w < cap - 1e-12)
            if not livre.any():
                break
            w[livre] = w[livre] + sobra * w[livre] / w[livre].sum()
    w.attrs.update(getattr(pesos, "attrs", {}))
    return w


def registro_dos_pesos(antes, depois, visao, setor=None, limiar=0.0025):
    """Lista do que a mesa mudou nos pesos (mudanca de pelo menos `limiar` do patrimonio), com o motivo."""
    c, incl = conviccoes(visao), inclinacoes(visao)
    acoes = {str(a.get("ticker")).upper(): a for a in (visao or {}).get("acoes") or []}
    fora = []
    for t in depois.index:
        d = float(depois[t]) - float(antes.get(t, 0.0))
        if abs(d) < limiar:
            continue
        conv, s = c.get(str(t).upper(), 0), _setor_da_mesa((setor or {}).get(t), incl)
        partes = []
        if conv:
            a = acoes.get(str(t).upper()) or {}
            motivo = a.get("risco") if conv < 0 else (a.get("o_que_o_preco_exige") or a.get("margem") or a.get("tese"))   # para baixo: o risco; para cima: o que sustenta
            partes.append(f"convicção {conv:+d}" + (": " + str(motivo) if motivo else ""))
        if s:
            partes.append(f"setor com inclinação {s:+d}")
        if not partes:
            partes.append("ajuste para manter a exposição total")
        fora.append({"ticker": t, "efeito": "peso aumentado" if d > 0 else "peso reduzido",
                     "de_pct": round(float(antes.get(t, 0.0)) * 100, 2), "para_pct": round(float(depois[t]) * 100, 2), "porque": "; ".join(partes)})
    return fora


def bloco(visao, motivo, aplicado=None):
    """O cartao "Visao da mesa" da tela (modulo MULTIFATORIAL)."""
    if visao is None:
        return {"ativa": False, "motivo": motivo, "aplicado": []}
    m = visao.get("macro") or {}
    return {"ativa": True, "motivo": motivo, "gerado": visao.get("gerado"), "validade_dias": visao.get("validade_dias") or VALIDADE_PADRAO,
            "macro": {"regime": m.get("regime"), "texto": m.get("texto"), "favorece": m.get("favorece") or [], "pune": m.get("pune") or [],
                      "eventos": m.get("eventos") or []},
            "setores": [{"setor": s.get("setor"), "inclinacao": _inteiro(s.get("inclinacao")), "porque": s.get("porque")} for s in visao.get("setores") or []],
            "acoes": [{"ticker": a.get("ticker"), "conviccao": _inteiro(a.get("conviccao")), "tese": a.get("tese"), "risco": a.get("risco"),
                       "evento_binario": a.get("evento_binario")} for a in visao.get("acoes") or []],
            "aplicado": list(aplicado or []),
            "regra": ("A mesa não escolhe a carteira: ela veta o papel em que vê um problema que os números não mostram (convicção -2) e "
                      "mexe no peso dos demais em até 15% por ponto de convicção e 5% por ponto do setor. Essa camada não tem teste "
                      "histórico: é medida daqui para a frente, e cada mudança fica registrada aqui com o motivo."),
            "sem_analise": visao.get("sem_analise") or [], "avisos": visao.get("avisos") or []}
