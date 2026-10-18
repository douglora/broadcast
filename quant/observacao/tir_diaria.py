"""Retrato diario da TIR de cada papel, para a PROVA VIVA da TIR nova (metodo do Safra) que o robo usa desde 19/10/2026.

Por que existe: a TIR nova nao tem historico para teste (o consenso de preco-alvo nao tem serie), o terminal regrava tir_safra.json a cada
rodada e o banco dele (cache/banco/terminal.sqlite) so guarda a TIR antiga. Sem este retrato nao haveria como medir depois se o premio da
TIR nova separou os papeis que andaram dos que nao andaram. Grava a TIR que o robo usa e a antiga ao lado, para comparar as duas no mesmo
dia. So medido: nada aqui muda decisao. Uma linha JSON por dia em quant/saida/observacao/tir_diaria.jsonl; repetir o dia substitui a linha.
"""
import json
import math
import os

from quant.observacao import DIR_OBS

ARQ_TIR = os.path.join(DIR_OBS, "tir_diaria.jsonl")
# por papel, nesta ordem: TIR do robo (% a.a. real), premio dela (pp), fonte ('safra', 'analistas', 'antiga'), TIR antiga, premio antigo, potencial
COLUNAS = ("tir_prudente_pct", "tir_premio_pp", "tir_fonte", "tir_antiga_pct", "tir_antiga_premio_pp", "tir_potencial_pct")


def _limpo(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return round(float(v), 2) if isinstance(v, (int, float)) else v


def registrar(dia, tabela, arq=None):
    """Grava o retrato do dia a partir da tabela do terminal. Devolve quantos papeis entraram (0 sem tabela ou sem as colunas)."""
    if tabela is None or not set(COLUNAS) <= set(getattr(tabela, "columns", [])):
        return 0
    t = tabela.loc[tabela["tir_prudente_pct"].notna() | tabela["tir_antiga_pct"].notna(), list(COLUNAS)]
    if t.empty:
        return 0
    arq = arq or ARQ_TIR
    os.makedirs(os.path.dirname(arq), exist_ok=True)
    try:
        with open(arq, encoding="utf-8") as f:
            linhas = [json.loads(x) for x in f if x.strip()]
    except (OSError, ValueError):
        linhas = []
    linhas = [x for x in linhas if x.get("dia") != str(dia)]
    linhas.append({"dia": str(dia), "colunas": list(COLUNAS), "papeis": {tk: [_limpo(v) for v in row] for tk, row in zip(t.index, t.itertuples(index=False))}})
    linhas.sort(key=lambda x: x["dia"])
    tmp = arq + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for x in linhas:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    os.replace(tmp, arq)
    return len(t)
