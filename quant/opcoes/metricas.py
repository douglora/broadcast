"""
Metricas dos ciclos mensais e registro de tentativas (tentativas.jsonl).

Cada estrategia produz, por ciclo mensal (vencimento T), o retorno EXCEDENTE sobre o CDI (`ex`) sobre o capital empenhado
e o CDI do ciclo (`cdi`). Ciclo sem operacao (nenhuma serie passou no filtro de liquidez) entra com excesso zero: o dinheiro
ficou no CDI. Isso e conservador e evita premiar a estrategia por pular os meses ruins de liquidez.

  anos                  quando informado (soma dos pregoes dos ciclos / 252), anualiza so o tempo em que o capital esteve
                        no ciclo; sem ele usa o intervalo de calendario (o pregao entre o vencimento e a entrada seguinte
                        fica de fora dos ciclos e subestimaria o retorno anual em cerca de 5%)
  retorno_anual_pct     retorno total anualizado (CDI + excesso) sobre o capital empenhado, composto por ciclo
  excesso_anual_pct     retorno anual menos o CDI composto nos mesmos ciclos
  sharpe                media/desvio do excesso por ciclo, anualizado pelo numero de ciclos por ano
  queda_maxima_pct      maior queda da curva de retorno total, medida nos fechamentos de cada ciclo (a perda DENTRO do
                        mes pode ser maior: nao marcamos a mercado a serie diaria)
  pior_mes_pct          pior retorno total de um ciclo
  meses_positivos_pct   % dos ciclos COM operacao em que o excesso foi positivo
  sharpe_deflacionado   ldp.dsr do excesso por ciclo, descontando o numero de configuracoes testadas na familia
"""
import json
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from quant.opcoes.base import DIR_OPC
from quant.pesquisa import ldp

ARQ_TENTATIVAS = os.path.join(DIR_OPC, "tentativas.jsonl")
FORCAR = False        # True na rodada final: regrava linhas ja existentes (o arquivo e so de acrescentar; vale a ultima)


def curva(ex, cdi):
    return np.cumprod(1.0 + np.asarray(cdi, dtype=float) + np.asarray(ex, dtype=float))


def calcular(ex, cdi, com_op=None, inicio=None, fim=None, n_tentativas=None, anos=None):
    """ex, cdi: arrays por ciclo (mesma ordem cronologica). com_op: bool por ciclo. inicio/fim: datas (para anualizar)."""
    ex = np.asarray(ex, dtype=float)
    cdi = np.asarray(cdi, dtype=float)
    n = len(ex)
    if n < 3:
        return {"n_ciclos": n, "n_ops": int(np.sum(com_op)) if com_op is not None else n}
    com_op = np.ones(n, dtype=bool) if com_op is None else np.asarray(com_op, dtype=bool)
    if anos is None:
        anos = max((pd.Timestamp(fim) - pd.Timestamp(inicio)).days / 365.25, 0.5) if inicio is not None else n / 12.0
    anos = max(float(anos), 0.5)
    tot = curva(ex, cdi)
    ret_aa = tot[-1] ** (1.0 / anos) - 1.0
    cdi_aa = float(np.prod(1.0 + cdi)) ** (1.0 / anos) - 1.0
    por_ano = n / anos
    sd = ex.std(ddof=1)
    sharpe = float(ex.mean() / sd * math.sqrt(por_ano)) if sd > 0 else 0.0
    pico = np.maximum.accumulate(np.concatenate([[1.0], tot]))[1:]
    qm = float((tot / pico - 1.0).min())
    r_mes = cdi + ex
    out = {
        "n_ciclos": int(n), "n_ops": int(com_op.sum()),
        "retorno_anual_pct": round(ret_aa * 100, 2), "cdi_anual_pct": round(cdi_aa * 100, 2),
        "excesso_anual_pct": round((ret_aa - cdi_aa) * 100, 2),
        "sharpe": round(sharpe, 3), "queda_maxima_pct": round(qm * 100, 2),
        "pior_mes_pct": round(float(r_mes.min()) * 100, 2), "melhor_mes_pct": round(float(r_mes.max()) * 100, 2),
        "meses_positivos_pct": round(float((ex[com_op] > 0).mean() * 100), 1) if com_op.any() else None,
        "excesso_medio_mes_pct": round(float(ex.mean() * 100), 3),
    }
    if n_tentativas:
        d = ldp.dsr(ex, n_tentativas)
        out["sharpe_deflacionado"] = round(float(d), 3) if d == d else None
        out["n_tentativas"] = int(n_tentativas)
    return out


def fatiar(df, ini, fim):
    """Recorta um DataFrame por ciclo com coluna T entre as datas (inclusive)."""
    return df[(df["T"] >= pd.Timestamp(ini)) & (df["T"] <= pd.Timestamp(fim))]


# ---------------------------------------------------------------- registro de tentativas
def ler_tentativas():
    if not os.path.exists(ARQ_TENTATIVAS):
        return []
    with open(ARQ_TENTATIVAS, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def n_tentativas(familia=None):
    """Numero de CONFIGURACOES distintas (chave = familia + config) avaliadas. Uma configuracao olhada em tres periodos conta uma vez."""
    ch = set()
    for t in ler_tentativas():
        if familia is None or t.get("familia") == familia:
            ch.add((t.get("familia"), t.get("config")))
    return len(ch)


def registrar(familia, config, periodo, metricas, nota=None):
    """Acrescenta uma linha em tentativas.jsonl. `config` e um texto curto e estavel (ex.: 'put delta=0.20 ativo=PETR4 exec=oferta')."""
    os.makedirs(DIR_OPC, exist_ok=True)
    if not FORCAR:
        for t in ler_tentativas():                   # idempotente: mesma familia + config + periodo nao entra duas vezes
            if t.get("familia") == familia and t.get("config") == config and t.get("periodo") == periodo:
                return t
    linha = {"quando": datetime.now().isoformat(timespec="seconds"), "familia": familia, "config": config,
             "periodo": periodo, "metricas": metricas}
    if nota:
        linha["nota"] = nota
    with open(ARQ_TENTATIVAS, "a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")
    return linha
