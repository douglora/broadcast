"""
Setups M1 e M2: a camada de julgamento da mesa, medida em prova viva (decisao do Douglas, 11/10/2026: "o robo precisa pensar como gestor de fundo").

NAO TEM TESTE HISTORICO, e nao pode ter: a visao da mesa e um julgamento escrito num dia; nao existe serie de 15 anos dela. Por isso M1 e M2 so
sao medidos daqui para a frente ("camada de julgamento: sem teste historico; so prova viva") e NUNCA recebem capital pela regra de evidencia:
so por liberacao escrita do Douglas (`quant/saida/swing_config.json`, "liberar": ["M1.S0"]).

  M1 "conviccao da mesa": cada papel com conviccao +1 ou +2 na visao vira uma operacao medida de COMPRA de R$ 6.000.
  M2 "veto da mesa" (espelho): cada papel com conviccao -2 vira uma operacao medida de COMPRA, com as mesmas regras. Se o veto tem informacao, M2 perde.
     E a medicao do veto, NAO uma operacao vendida: mede o que teria acontecido com os papeis vetados.

REGRAS (iguais para os dois):
  - Uma vez por visao da mesa, identificada pelo campo `gerado` do `visao_mesa.json` (o estado guarda as visoes ja medidas: rodar de novo nao repete).
  - Entrada na abertura do primeiro pregao DEPOIS do `gerado` (se o `gerado` caiu num pregao antes das 10h, a abertura desse mesmo dia).
  - Stop, alvo e prazo iguais aos do setup E1 (`PAI`): stop de 2,0 ATR, alvo de 3,0 ATR e saida no 10o pregao no maximo. ATR e preco de referencia
    do ultimo fechamento ANTES da entrada.
  - Nao repete o mesmo papel enquanto a medida anterior do mesmo setup estiver aberta ou a espera da entrada.
  - Papel sem barras no painel (fora do universo de giro, ticker novo) fica de fora e a tela diz qual e por que.
"""
from datetime import datetime

import numpy as np
import pandas as pd

from quant.dados import calendario
from quant.swing import setups

PAI = ("e_forca_relativa", "E1")            # a regra de saida (stop, alvo, prazo) e a deste setup ja existente
FAMILIA = "m_mesa"
ETIQUETA = "camada de julgamento: sem teste histórico; só prova viva"
ROTULOS = {
    "M1": "convicção da mesa (compra medida dos papéis com convicção +1 ou +2)",
    "M2": "veto da mesa (mede o que teria acontecido com os papéis vetados: compra medida dos papéis com convicção -2)",
}
CONVICCAO_MIN_M1 = 1
CONVICCAO_VETO = -2


def parametros():
    """(stop_atr, alvo_atr, prazo) do setup pai, lidos de `setups.NUCLEOS` (nao copiados): se o pai mudar, muda junto."""
    par = setups.NUCLEOS[PAI[0]][PAI[1]]
    return par["stop_atr"], par["alvo_atr"], par["prazo"]


def regra_texto(nucleo):
    stop, alvo, prazo = parametros()
    saida = f"Entrada na abertura do primeiro pregão depois da visão; stop em {stop:g} ATR, alvo em {alvo:g} ATR, saída no {prazo}º pregão no máximo (mesmos números do {PAI[1]})."
    if nucleo == "M1":
        r = "Uma vez por visão da mesa, cada papel com convicção +1 ou +2 vira uma compra medida de R$ 6.000."
    else:
        r = ("Uma vez por visão da mesa, cada papel com convicção -2 (vetado) vira uma compra medida de R$ 6.000: mede o que teria acontecido com os papéis vetados. "
             "Não é operação vendida. Se o veto tem informação, esta medição perde.")
    return f"{r} {saida} Não repete o papel enquanto a medida anterior estiver aberta. {ETIQUETA[0].upper() + ETIQUETA[1:]}."


def linhas_de_evidencia(cfg):
    """As linhas M1.S0 e M2.S0 no formato de `evidencia.por_variante`. Capital so por liberacao escrita do Douglas."""
    liberar = set(cfg.get("liberar") or [])
    out = {}
    for nid in ("M1", "M2"):
        vid = f"{nid}.S0"
        status, motivo = "so_medido", ETIQUETA
        if vid in liberar:
            status = "liberado"
            motivo = "decisão do Douglas" + (f" ({cfg.get('decidido_em')})" if cfg.get("decidido_em") else "") + "; " + ETIQUETA
        out[vid] = {"id": vid, "familia": FAMILIA, "nucleo": nid, "overlay": "S0", "rotulo": ROTULOS[nid], "descoberta": None, "validacao": None, "prova": None,
                    "dsr": None, "status": status, "motivo": motivo, "sensibilidade_custo_leve": False, "etiqueta": ETIQUETA, "camada_de_julgamento": True}
    return out


def entrada_da_visao(gerado):
    """Dia do primeiro pregao depois do `gerado` (ISO com fuso). Antes das 10h de um dia de pregao, a abertura desse mesmo dia."""
    t = datetime.fromisoformat(str(gerado))
    d = t.date()
    if calendario.eh_pregao(d) and t.strftime("%H:%M") < "10:00":
        return d
    return calendario.proximo_pregao(d)


def quando(gerado):
    t = datetime.fromisoformat(str(gerado))
    return t.strftime("%d/%m/%Y às %Hh%M")


def papeis(visao):
    """{'M1': [(ticker, conviccao, dict da mesa)], 'M2': [...]} na ordem em que a mesa escreveu."""
    out = {"M1": [], "M2": []}
    for a in (visao or {}).get("acoes") or []:
        t = str(a.get("ticker") or "").upper()
        try:
            c = int(round(float(a.get("conviccao"))))
        except (TypeError, ValueError):
            continue
        if not t:
            continue
        if c >= CONVICCAO_MIN_M1:
            out["M1"].append((t, c, a))
        elif c <= CONVICCAO_VETO:
            out["M2"].append((t, c, a))
    return out


def _resumo(txt, n=210):
    txt = " ".join(str(txt or "").split())
    if len(txt) <= n:
        return txt
    corte = txt[:n].rsplit(" ", 1)[0]
    return corte + "…"


def _abertas(estado, setup, ticker):
    return any(p.get("setup") == setup and p.get("ticker") == ticker and p.get("status") in ("aberta", "pendente") for p in estado["posicoes"])


def gerar(p, ind, visao, estado, i=-1):
    """Candidatas M1/M2 da visao, calculadas no fechamento do indice `i` do painel (o ultimo ANTES da entrada).
    Devolve (linhas, sem_dado, repetidas): `sem_dado` = [(ticker, setup, motivo)] sem barras; `repetidas` = [(ticker, setup)] com medida anterior aberta."""
    stop_atr, alvo_atr, prazo = parametros()
    gerado = visao["gerado"]
    n = len(p.datas)
    i = i % n
    linhas, sem_dado, repetidas = [], [], []
    for nid, lista in papeis(visao).items():
        for t, conv, a in lista:
            if t not in p.tickers:
                sem_dado.append((t, nid, "sem barras no painel (fora do universo de giro mínimo ou ticker novo)"))
                continue
            j = p.tickers.index(t)
            atr, cru, c_aj = ind["atr"][i, j], p.preco_cru[i, j], p.C[i, j]
            if not (np.isfinite(atr) and atr > 0 and np.isfinite(cru) and np.isfinite(c_aj) and c_aj > 0):
                sem_dado.append((t, nid, "sem histórico suficiente para o ATR no último fechamento"))
                continue
            if _abertas(estado, nid, t):
                repetidas.append((t, nid))
                continue
            escala = float(cru / c_aj)
            stop_dist, alvo_dist = float(stop_atr * atr * escala), float(alvo_atr * atr * escala)
            adtv = float(p.adtv[i, j])
            if adtv <= 0:
                adtv = float(np.nanmean(p.V[max(i - 20, 0):i + 1, j]))
            quem = f"a mesa deu convicção {conv:+d} a {t} na visão de {quando(gerado)}"
            if nid == "M1":
                porque = f"{quem[0].upper() + quem[1:]}: {_resumo(a.get('tese'))} Compra medida de R$ 6.000, sem teste histórico."
            else:
                porque = (f"Mede o que teria acontecido com os papéis vetados: {quem}"
                          + (f" (risco: {_resumo(a.get('risco'), 160)})" if a.get("risco") else "") + ". Compra medida de R$ 6.000, não é operação vendida.")
            linhas.append({
                "setup": nid, "familia": FAMILIA, "rotulo": ROTULOS[nid], "ticker": t, "sinal_em": str(p.datas[i].date()), "preco_ref": float(cru),
                "atr_real": float(atr * escala), "stop_dist": stop_dist, "alvo_dist": alvo_dist, "stop_ref": float(cru - stop_dist), "alvo_ref": float(cru + alvo_dist),
                "prazo": int(prazo), "adtv": adtv, "top": bool(p.top[i, j]), "ibov_ok": bool(p.ibov_ok[i]), "porque": porque,
                "numeros": {"conviccao": float(conv)}, "visao_gerado": str(gerado), "etiqueta": ETIQUETA, "camada_de_julgamento": True})
    return linhas, sem_dado, repetidas


def indice_antes_da_entrada(p, entrada_m):
    """Indice do ultimo fechamento do painel estritamente antes de `entrada_m`; None se o painel nao chega ate o pregao anterior a entrada."""
    esperado = pd.Timestamp(calendario.pregao_anterior(entrada_m))
    if p.datas[-1] < esperado:
        return None
    return int((p.datas <= esperado).sum()) - 1
