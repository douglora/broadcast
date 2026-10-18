"""Retrato diario da TIR de cada papel, para a PROVA VIVA da TIR nova (metodo do Safra) que o robo usa desde 19/10/2026.

Por que existe: a TIR nova nao tem historico para teste (o consenso de preco-alvo nao tem serie), o terminal regrava tir_safra.json a cada
rodada e o banco dele (cache/banco/terminal.sqlite) nao guarda a TIR nova. Sem este retrato nao haveria como medir depois se o premio
separou os papeis que andaram dos que nao andaram. So a TIR nova: a antiga nao entra em nada do robo ("o robo nao pode usar antiga",
Douglas, 18/10/2026). Dia com a TIR recusada (recalculo que falhou ou arquivo velho) fica gravado como recusado, sem numero.
So medido: nada aqui muda decisao. Uma linha JSON por dia em quant/saida/observacao/tir_diaria.jsonl; repetir o dia substitui a linha.
"""
import json
import math
import os

from quant.comum import log
from quant.observacao import DIR_OBS

ARQ_TIR = os.path.join(DIR_OBS, "tir_diaria.jsonl")
# por papel, nesta ordem: TIR (% a.a. real), premio sobre a NTN-B 2035 (pp), base ('safra' ou 'analistas'), potencial do preco-alvo (%)
COLUNAS = ("tir_prudente_pct", "tir_premio_pp", "tir_fonte", "tir_potencial_pct")


def _limpo(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return round(float(v), 2) if isinstance(v, (int, float)) else v


def _papeis(tabela):
    if tabela is None or not set(COLUNAS) <= set(getattr(tabela, "columns", [])):
        return {}
    t = tabela.loc[tabela["tir_prudente_pct"].notna(), list(COLUNAS)]
    return {tk: [_limpo(v) for v in row] for tk, row in zip(t.index, t.itertuples(index=False))}


def registrar(dia, tabela, estado, arq=None):
    """Grava o retrato do dia: a TIR de cada papel (da tabela do terminal) e o estado da conferencia (`terminal.tir_estado()`), com os papeis
    que o arquivo conhece e ficaram sem TIR. Devolve quantos papeis tem TIR (0 com a TIR recusada). Sem estado (terminal fora): nao grava."""
    if not estado:
        return 0
    papeis = _papeis(tabela) if estado.get("ok") else {}
    linha = {"dia": str(dia), "ok": bool(estado.get("ok")), "recusada": None if estado.get("ok") else estado.get("motivo"),
             "gerado": estado.get("gerado"), "conferido_em": estado.get("conferido_em"), "colunas": list(COLUNAS), "papeis": papeis,
             "sem_tir": estado.get("sem_tir") or {}}
    arq = arq or ARQ_TIR
    os.makedirs(os.path.dirname(arq), exist_ok=True)
    try:
        with open(arq, encoding="utf-8") as f:
            linhas = [json.loads(x) for x in f if x.strip()]
    except (OSError, ValueError):
        linhas = []
    linhas = [x for x in linhas if x.get("dia") != str(dia)] + [linha]
    linhas.sort(key=lambda x: x["dia"])
    tmp = arq + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for x in linhas:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    os.replace(tmp, arq)
    if linha["ok"]:
        sem = linha["sem_tir"]
        log(f"TIR de {dia}: {len(papeis)} papeis com a TIR nova (gerada em {linha['gerado']}); sem TIR entre os que ela conhece: {len(sem)}"
            + (" (" + "; ".join(f"{t}: {m}" for t, m in sem.items()) + ")" if sem else ""))
    else:
        log(f"TIR de {dia}: RECUSADA, o robo nao usa TIR hoje ({linha['recusada']})")
    return len(papeis)
