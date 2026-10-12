"""
Escada de dose de risco (regra G23, inspirada nas fichas Apolo/Chronos/Atlas da Kinea): tres degraus de volatilidade alvo
do livro, 1 : 2,5 : 4 (1,5%, 4% e 6% ao ano). Degrau medio com o termometro calmo e sem evento binario em ate 5 pregoes;
baixo em alerta ou com evento binario proximo; zero em estresse; o degrau alto so existe depois de 36 meses de prova viva
(G16), entao hoje nunca e recomendado.

SO MEDIDO: a saida e uma RECOMENDACAO gravada ao lado da mao que o livro usa de fato (risco_livro.json e o orcamento de
risco), para que o placar compare depois. Nada aqui muda exposicao, lote ou chave.
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd

from quant.dados import calendario_eua as ce

DEGRAUS = {"zero": 0.0, "baixo": 1.5, "medio": 4.0, "alto": 6.0}
EVENTOS_FIXOS = (("2026-10-25", "2o turno da eleicao presidencial"),)
JANELA_EVENTO = 5          # pregoes


def _pregoes_ate(hoje, dia):
    return int(np.busday_count(pd.Timestamp(hoje).date(), pd.Timestamp(dia).date()))


def eventos_proximos(hoje, mapa_eua=None, copom=None, extras=()):
    """Eventos binarios nos proximos JANELA_EVENTO pregoes: eleicao (fixa), Copom (wirp), payroll e CPI (calendario dos EUA)."""
    hoje = pd.Timestamp(hoje).date()
    fora = []
    for d, nome in list(EVENTOS_FIXOS) + list(extras):
        n = _pregoes_ate(hoje, d)
        if 0 <= n <= JANELA_EVENTO:
            fora.append({"data": str(d), "evento": nome, "pregoes": n})
    if copom and copom[0]:
        n = _pregoes_ate(hoje, copom[0])
        if 0 <= n <= JANELA_EVENTO:
            fora.append({"data": str(copom[0])[:10], "evento": "Copom", "pregoes": n})
    for k in range(JANELA_EVENTO + 1):
        d = hoje + timedelta(days=k)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        t = ce.tipo_do_dia(d, mapa_eua)
        if t in ("payroll", "cpi") and not any(x["data"] == str(d) and x["evento"] == t for x in fora):
            fora.append({"data": str(d), "evento": t, "pregoes": _pregoes_ate(hoje, d)})
    return sorted(fora, key=lambda x: x["pregoes"])


def degrau(estado_termometro, eventos):
    if estado_termometro == "estresse":
        return "zero", "termometro em estresse: sem risco novo"
    if estado_termometro == "sem leitura":
        return "baixo", "termometro sem leitura: dose baixa por cautela"
    if eventos:
        e = eventos[0]
        return "baixo", f"evento binario em {e['pregoes']} pregao(oes) ({e['evento']} em {e['data']}): dose baixa"
    if estado_termometro == "alerta":
        return "baixo", "termometro em alerta: dose baixa"
    return "medio", "termometro calmo e sem evento proximo: dose media"


def recomendar(hoje, termometro, mapa_eua=None, copom=None, vol_ibov_20d=None, mao_atual=None):
    """Recomendacao do dia (so medida). `vol_ibov_20d` em fracao a.a. converte o degrau em exposicao equivalente em bolsa;
    `mao_atual` (0 a 1) e o que o livro usa hoje, para o placar comparar."""
    evs = eventos_proximos(hoje, mapa_eua, copom)
    nome, motivo = degrau(termometro.get("estado"), evs)
    vol_alvo = DEGRAUS[nome]
    expo = None
    if vol_ibov_20d and vol_ibov_20d > 0:
        expo = round(min(1.0, vol_alvo / 100.0 / float(vol_ibov_20d)), 3)
    return {"degrau": nome, "vol_alvo_aa_pct": vol_alvo, "motivo": motivo, "eventos_proximos": evs,
            "exposicao_equivalente_bolsa": expo, "mao_atual_do_livro": mao_atual,
            "nota": "Recomendacao so medida (G23): o livro continua com a mao da regra de volatilidade; o degrau alto exige 36 meses de prova viva."}
