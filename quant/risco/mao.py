"""
A "mao" (tamanho da posicao) que se diminui e se aumenta: por volatilidade e por queda do patrimonio.

POR QUE EXISTE. O Douglas quer "saber a hora de diminuir ou aumentar a mao". Duas regras simples, sem prever direcao:

  1. MAO POR VOLATILIDADE (Moreira e Muir, 2017; Barroso e Santa-Clara, 2015). A volatilidade e persistente e o retorno
     esperado nao sobe na mesma proporcao: diminuir a posicao quando a volatilidade recente esta acima do normal e voltar quando
     cai melhora o retorno por unidade de risco e corta a cauda esquerda. Exposicao = min(teto, alvo / vol), com a vol dos
     ultimos N pregoes e o alvo igual a MEDIA DA PROPRIA vol ate o dia anterior. Sem alavancagem (teto 1,0).
  2. CORTE POR QUEDA. A mao cai pela metade quando a curva do proprio patrimonio gerenciado cai 10% desde o pico, e volta
     quando recupera metade da distancia entre o fundo e o pico (e o pico de referencia passa a ser o patrimonio daquele dia).

CONTRATO DE NAO OLHAR O FUTURO. A exposicao decidida no fechamento de t usa so dados ate t. A defasagem do projeto vale aqui:
decide no fechamento de t, executa no fechamento de t+1, rende de t+2: exposicao aplicada em t = decidida em t-2.
As duas regras sao classes INCREMENTAIS (um passo por pregao); as funcoes vetorizadas abaixo usam as mesmas classes, entao o motor
(`backtest.rodar(mao=...)`) e a conta em serie de retornos fazem exatamente a mesma coisa. Tudo e puro: sem disco, sem rede.

O que as regras NAO fazem: nao preveem retorno, nao operam sozinhas (o orcamento de risco, `orcamento.py`, so as calcula) e nao
tem custo zero: cada mudanca de exposicao custa |variacao| x taxa (mini-indice ~0,015% por unidade; acoes ~0,57%).
"""
from collections import deque

import numpy as np
import pandas as pd

DIAS_ANO = 252
JANELAS = (21, 63)
TETO = 1.0
DEFASAGEM = 2
LIMIAR_QUEDA = 0.10
FATOR_CORTE = 0.5
RECUPERACAO = 0.5
CUSTO_ACOES = 0.0057             # por unidade de exposicao negociada em acoes (custo real medido no motor: 0,567%)
CUSTO_FATOR = 2 * CUSTO_ACOES    # fator longo-curto: duas pernas


# ─────────────────────────────────────────────────────────────
# Regra 1: volatilidade
# ─────────────────────────────────────────────────────────────
class MaoVol:
    """Exposicao por volatilidade, um pregao por vez. `passo(r)` recebe o retorno do dia t e devolve a exposicao
    DECIDIDA no fechamento de t (so passado e presente)."""

    def __init__(self, janela=63, teto=TETO):
        self.janela, self.teto = int(janela), float(teto)
        self.fila = deque(maxlen=self.janela)
        self.soma_vol, self.n_vol = 0.0, 0
        self.vol, self.alvo = np.nan, np.nan

    def passo(self, r):
        r = float(r)
        self.fila.append(r if np.isfinite(r) else 0.0)
        if len(self.fila) < self.janela:
            self.vol, self.alvo = np.nan, np.nan
            return 1.0
        alvo_anterior = self.soma_vol / self.n_vol if self.n_vol else np.nan     # media das vol ate t-1
        v = float(np.std(np.asarray(self.fila), ddof=1) * np.sqrt(DIAS_ANO))
        self.vol, self.alvo = v, alvo_anterior
        self.soma_vol += v
        self.n_vol += 1
        if not (np.isfinite(alvo_anterior) and np.isfinite(v)) or v <= 0:
            return 1.0
        return float(min(self.teto, alvo_anterior / v))


def exposicao_por_vol(ret, janela=63, teto=TETO, defasagem=DEFASAGEM):
    """DataFrame(vol, alvo, decidida, aplicada) indexado como `ret`. `aplicada` = decidida deslocada `defasagem` pregoes."""
    r = pd.Series(ret, dtype=float)
    m = MaoVol(janela, teto)
    vol, alvo, dec = [], [], []
    for x in r.to_numpy():
        e = m.passo(x)
        vol.append(m.vol), alvo.append(m.alvo), dec.append(e)
    out = pd.DataFrame({"vol": vol, "alvo": alvo, "decidida": dec}, index=r.index)
    out["aplicada"] = out["decidida"].shift(int(defasagem)).fillna(1.0)
    return out


# ─────────────────────────────────────────────────────────────
# Regra 2: queda do patrimonio
# ─────────────────────────────────────────────────────────────
class MaoQueda:
    """Corte por queda, um pregao por vez. `passo(patrimonio)` recebe o patrimonio GERENCIADO do dia t e devolve a
    exposicao decidida: 1,0 ou `fator`."""

    def __init__(self, limiar=LIMIAR_QUEDA, fator=FATOR_CORTE, recuperacao=RECUPERACAO):
        self.limiar, self.fator, self.recuperacao = float(limiar), float(fator), float(recuperacao)
        self.pico, self.fundo, self.pico_no_corte = np.nan, np.nan, np.nan
        self.cortado = False

    def passo(self, patrimonio):
        e = float(patrimonio)
        if not np.isfinite(e):
            return self.fator if self.cortado else 1.0
        if not np.isfinite(self.pico):
            self.pico = e
        if not self.cortado:
            self.pico = max(self.pico, e)
            if self.pico > 0 and (self.pico - e) / self.pico >= self.limiar:
                self.cortado, self.pico_no_corte, self.fundo = True, self.pico, e
        else:
            self.fundo = min(self.fundo, e)
            distancia = self.pico_no_corte - self.fundo
            if distancia > 0 and (e - self.fundo) / distancia >= self.recuperacao:
                self.cortado = False
                self.pico = e                      # o pico de referencia recomeca no dia da volta
        return self.fator if self.cortado else 1.0


# ─────────────────────────────────────────────────────────────
# Aplicacao a uma serie de retornos
# ─────────────────────────────────────────────────────────────
def custo_da_variacao(aplicada, custo_unitario):
    """Fracao do patrimonio gasta em cada dia: |variacao da exposicao aplicada| x custo por unidade.
    `custo_unitario`: escalar ou Series alinhada."""
    a = pd.Series(aplicada, dtype=float)
    return (a.diff().abs().fillna(0.0) * custo_unitario).astype(float)


def retorno_gerenciado(ret, aplicada, rf=None, custo_unitario=0.0):
    """Retorno TOTAL diario: rf + e x r - custo. `ret` e o retorno em excesso (ou o do fator); rf, o ativo livre de risco
    (None = 0, para fatores longo-curto)."""
    r = pd.Series(ret, dtype=float)
    e = pd.Series(aplicada, dtype=float).reindex(r.index).fillna(1.0)
    base = 0.0 if rf is None else pd.Series(rf, dtype=float).reindex(r.index).fillna(0.0)
    return (base + e * r.fillna(0.0) - custo_da_variacao(e, custo_unitario)).rename("gerenciado")


def gerenciar_por_vol(ret, janela=63, teto=TETO, rf=None, custo_unitario=0.0, defasagem=DEFASAGEM):
    """Mao por volatilidade aplicada a uma serie. Devolve DataFrame(total, exposicao, vol, alvo)."""
    ex = exposicao_por_vol(ret, janela, teto, defasagem)
    tot = retorno_gerenciado(ret, ex["aplicada"], rf, custo_unitario)
    return pd.DataFrame({"total": tot, "exposicao": ex["aplicada"], "vol": ex["vol"], "alvo": ex["alvo"]})


def gerenciar_por_queda(ret, rf=None, custo_unitario=0.0, limiar=LIMIAR_QUEDA, fator=FATOR_CORTE,
                        recuperacao=RECUPERACAO, defasagem=DEFASAGEM):
    """Corte por queda aplicado a uma serie: a regra olha o patrimonio gerenciado (a propria curva), com a defasagem
    do projeto. Devolve DataFrame(total, exposicao, patrimonio)."""
    r = pd.Series(ret, dtype=float)
    base = np.zeros(len(r)) if rf is None else pd.Series(rf, dtype=float).reindex(r.index).fillna(0.0).to_numpy()
    m = MaoQueda(limiar, fator, recuperacao)
    fila = deque([1.0] * int(defasagem), maxlen=int(defasagem))     # decididas ainda nao em vigor
    e_ant, pat = 1.0, 1.0
    tot, apl, pats = [], [], []
    for i, x in enumerate(r.fillna(0.0).to_numpy()):
        e = fila[0] if defasagem else 1.0                              # decidida ha `defasagem` pregoes
        c = abs(e - e_ant) * (custo_unitario.iloc[i] if hasattr(custo_unitario, "iloc") else custo_unitario)
        t = base[i] + e * x - c
        pat *= (1.0 + t)
        dec = m.passo(pat)
        fila.append(dec)
        tot.append(t), apl.append(e), pats.append(pat)
        e_ant = e
    return pd.DataFrame({"total": tot, "exposicao": apl, "patrimonio": pats}, index=r.index)


# ─────────────────────────────────────────────────────────────
# Metricas
# ─────────────────────────────────────────────────────────────
def metricas(total, rf=None, dias_ano=DIAS_ANO):
    """Sharpe do excesso (anual), retorno e CDI anuais, queda maxima, pior mes, exposicao nao entra aqui."""
    t = pd.Series(total, dtype=float).dropna()
    base = 0.0 if rf is None else pd.Series(rf, dtype=float).reindex(t.index).fillna(0.0)
    ex = t - base
    n = len(t)
    if n < 2 or ex.std(ddof=1) == 0:
        return {"n": int(n), "sharpe": np.nan, "retorno_aa": np.nan, "excesso_aa": np.nan, "mdd": np.nan,
                "pior_mes": np.nan, "vol_aa": np.nan}
    curva = (1 + t).cumprod()
    anos = n / dias_ano
    mensal = (1 + t).resample("ME").prod() - 1 if isinstance(t.index, pd.DatetimeIndex) else pd.Series([np.nan])
    ret_aa = float(curva.iloc[-1] ** (1 / anos) - 1)
    base_aa = float((1 + base).prod() ** (1 / anos) - 1) if not np.isscalar(base) else 0.0
    return {"n": int(n), "sharpe": float(ex.mean() / ex.std(ddof=1) * np.sqrt(dias_ano)),
            "retorno_aa": ret_aa, "excesso_aa": float(ret_aa - base_aa),
            "vol_aa": float(ex.std(ddof=1) * np.sqrt(dias_ano)),
            "mdd": float((1 - curva / curva.cummax()).max()),
            "pior_mes": float(mensal.min())}


def giro_anual(aplicada, dias_ano=DIAS_ANO):
    """Soma de |variacao de exposicao| por ano."""
    a = pd.Series(aplicada, dtype=float)
    return float(a.diff().abs().fillna(0.0).sum() / (len(a) / dias_ano)) if len(a) else float("nan")
