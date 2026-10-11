"""
Manejo de posicao vendida no historico: caminho de preco pregao a pregao da propria serie (codigo + vencimento) lido da base bruta
do COTAHIST, para testar "recomprar quando 80% do premio ja foi capturado" e "stop em multiplo do premio".

Regras fixas (HIPOTESES_VERTENTES.md, escritas antes de rodar):
  - observacao SO no fechamento de pregoes em que a serie vendida tem 10+ negocios e oferta de venda valida (acima da de compra);
  - recompra na oferta de venda do fechamento do dia da observacao mais emolumento de 0,05%;
  - M1 (alvo): recompra quando o custo de fechar a posicao e <= 20% do credito recebido;
  - M2 (alvo + stop): alem do alvo, recompra quando o custo e >= `stop` vezes o credito (3x para perna unica, 2x para trava);
  - o primeiro evento no tempo vence; sem evento, segura ate o vencimento e liquida pelo exercicio protegido;
  - trava: so se observa nos pregoes em que as DUAS pernas tem cotacao (a vendida com 10+ negocios e oferta de venda valida; a comprada
    com oferta de compra valida); o custo de fechar e a oferta de venda da vendida menos a oferta de compra da comprada (com emolumento).
    (A primeira versao creditava zero pela perna comprada sem cotacao, o que fazia o stop disparar por falta de dado; corrigido
    antes de qualquer escolha, ver HIPOTESES_VERTENTES.md);
  - o caixa rende CDI: o credito capitaliza do dia da entrada ate o da recompra, e o saldo depois da recompra segue no CDI ate T.
A parte de pregoes antes da entrada nunca e lida. O vencimento (dia T) liquida pelo pagamento, nao pela cotacao.
"""
import numpy as np
import pandas as pd

from quant.opcoes import custos as C
from quant.opcoes import dados

FEE = C.FEE_PREMIO
NEG_OBS = 10


def _cdi_acum():
    c = dados.cdi_diario()
    return (1.0 + c).cumprod()


_CF = None


def fator_cdi(d0, d1):
    """Fator de CDI acumulado nos pregoes (d0, d1]."""
    global _CF
    if _CF is None:
        _CF = _cdi_acum()
    i0 = _CF.index.searchsorted(pd.Timestamp(d0), side="right") - 1
    i1 = _CF.index.searchsorted(pd.Timestamp(d1), side="right") - 1
    a = _CF.iloc[i0] if i0 >= 0 else 1.0
    b = _CF.iloc[i1] if i1 >= 0 else 1.0
    return float(b / a)


class Caminhos:
    """Caminho (dia, compra, venda, negocios) de cada serie (codigo, vencimento) depois do dia de entrada."""

    def __init__(self, pares):
        """pares: iteravel de (codigo, vencimento)."""
        chaves = set((c, pd.Timestamp(v)) for c, v in pares)
        self.d = {}
        if not chaves:
            return
        codigos = {c for c, _ in chaves}
        anos = sorted({v.year for _, v in chaves})
        ini, fim = max(2012, anos[0] - 1), min(2026, anos[-1])
        colunas = ["dia", "codigo", "vencimento", "oferta_compra", "oferta_venda", "negocios"]
        partes = []
        for ano in range(ini, fim + 1):
            op = dados.carregar_opcoes(ano, ano, colunas=colunas)
            op = op[op["codigo"].isin(codigos)]
            partes.append(op)
        op = pd.concat(partes, ignore_index=True)
        op = op.sort_values(["codigo", "vencimento", "dia"])
        for (cod, venc), g in op.groupby(["codigo", "vencimento"], sort=False):
            if (cod, venc) in chaves:
                self.d[(cod, venc)] = (g["dia"].values.astype("datetime64[ns]"), g["oferta_compra"].values.astype(float),
                                       g["oferta_venda"].values.astype(float), g["negocios"].values.astype(int))

    def serie(self, codigo, vencimento):
        return self.d.get((codigo, pd.Timestamp(vencimento)))


def saida_perna_unica(cam, codigo, venc, entrada, credito, alvo=0.20, stop=None, atraso=0):
    """Perna vendida isolada. Devolve (dia_saida, custo_recompra, motivo) ou None (segura ate o vencimento).
    `credito` e o premio liquido recebido (oferta de compra da entrada menos emolumento).
    `atraso`: estresse do stop (e do alvo) -- executa `atraso` pregoes COM COTACAO depois do gatilho, na oferta de venda desse dia
    (0 = no proprio fechamento do gatilho). Sem cotacao depois do gatilho, segura ate o vencimento."""
    s = cam.serie(codigo, venc)
    if s is None:
        return None
    dias, bid, ask, neg = s
    ini = np.searchsorted(dias, np.datetime64(entrada), side="right")
    fimv = np.datetime64(pd.Timestamp(venc))
    for i in range(ini, len(dias)):
        if dias[i] >= fimv:
            break
        if neg[i] < NEG_OBS or not (ask[i] > 0 and ask[i] > bid[i] >= 0):
            continue
        custo = ask[i] * (1.0 + FEE)
        gatilho = "alvo" if custo <= alvo * credito else ("stop" if (stop is not None and custo >= stop * credito) else None)
        if gatilho is None:
            continue
        if atraso <= 0:
            return pd.Timestamp(dias[i]), float(custo), gatilho
        k = i
        feitos = 0
        while feitos < atraso:
            k += 1
            if k >= len(dias) or dias[k] >= fimv:
                return None
            if neg[k] >= 1 and ask[k] > 0 and ask[k] > bid[k] >= 0:
                feitos += 1
        return pd.Timestamp(dias[k]), float(ask[k] * (1.0 + FEE)), gatilho
    return None


def saida_trava(cam, cod_curta, cod_longa, venc, entrada, credito, alvo=0.20, stop=None):
    """Trava de credito (vendida + comprada). Custo de fechar = oferta de venda da vendida (+emolumento) menos oferta de compra da
    comprada (menos emolumento) quando ela existe no dia. Devolve (dia_saida, custo, motivo) ou None."""
    sc = cam.serie(cod_curta, venc)
    sl = cam.serie(cod_longa, venc)
    if sc is None or sl is None:
        return None
    dias, bid, ask, neg = sc
    ini = np.searchsorted(dias, np.datetime64(entrada), side="right")
    fimv = np.datetime64(pd.Timestamp(venc))
    for i in range(ini, len(dias)):
        if dias[i] >= fimv:
            break
        if neg[i] < NEG_OBS or not (ask[i] > 0 and ask[i] > bid[i] >= 0):
            continue
        j = np.searchsorted(sl[0], dias[i], side="left")
        if not (j < len(sl[0]) and sl[0][j] == dias[i] and sl[1][j] > 0 and sl[2][j] > sl[1][j]):
            continue                       # perna comprada sem cotacao no dia: a trava nao e observavel, nao se decide nada
        custo = max(ask[i] * (1.0 + FEE) - sl[1][j] * (1.0 - FEE), 0.0)
        if custo <= alvo * credito:
            return pd.Timestamp(dias[i]), float(custo), "alvo"
        if stop is not None and custo >= stop * credito:
            return pd.Timestamp(dias[i]), float(custo), "stop"
    return None


def pnl_com_saida(credito, entrada, venc, saida, payoff_vencimento, taxa_exercicio):
    """Resultado em R$ por opcao (ou por trava), valorizado no vencimento, com o caixa no CDI.
    saida: None (segura) ou (dia, custo, motivo). payoff_vencimento: o que se paga no vencimento (>= 0)."""
    if saida is None:
        return credito * fator_cdi(entrada, venc) - payoff_vencimento - taxa_exercicio, "vencimento"
    dia, custo, motivo = saida
    return (credito * fator_cdi(entrada, dia) - custo) * fator_cdi(dia, venc), motivo
