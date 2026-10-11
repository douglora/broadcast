"""
Candidatas de swing do dia: os sinais dos 13 setups (nucleos) no ULTIMO fechamento do painel, com stop, alvo e prazo, as marcas das sobreposicoes
(metade de cima do ranking, Ibovespa acima da media de 200) e a frase do "porque".

Usa exatamente as mesmas funcoes da pesquisa (`setups.sinais`, sobreposicao S0) e le a linha do ultimo dia: nada aqui e regra nova. A entrada seria
na abertura do pregao seguinte; stop e alvo saem em multiplos do ATR (amplitude media de 14 pregoes) e o prazo e o do setup, de 4 a 10 pregoes.
"""
import numpy as np

from quant.swing import mesa_setups, setups
from quant.swing.texto import br, pct


def nucleos_s0():
    """As 13 variantes sem sobreposicao: o sinal bruto de cada setup. As sobreposicoes viram marcas em cada sinal."""
    return [v for v in setups.variantes() if v["overlay"] == "S0"]


def _frase(v, p, ind, i, j, ev_lin=None):
    t = p.tickers[j]
    fam, par = v["familia"], v["params"]
    C = p.C
    num = {}
    if fam == "a_pullback":
        n = par["drop_n"]
        d = float(ind[f"drop{n}"][i, j])
        num = {"queda_em_atr": d, "pregoes": n}
        txt = (f"{t} está em tendência de alta (preço acima da média de 50 pregões, que está acima da de 200) e caiu {br(d, 1)} vezes a oscilação diária "
               f"média (ATR) em {n} pregões: o setup aposta em repique de curto prazo.")
    elif fam == "b_reversao":
        n = par["drop_n"]
        d = float(ind[f"drop{n}"][i, j])
        num = {"queda_em_atr": d, "pregoes": n}
        txt = (f"{t} caiu {br(d, 1)} vezes a oscilação diária média (ATR) em {n} pregões e perdeu as médias de 20 e 50 pregões: "
               f"o setup aposta em reversão rápida depois do exagero.")
    elif fam == "c_rompimento":
        hi = float(ind["hi20_ant"][i, j] * p.preco_cru[i, j] / p.C[i, j])          # na escala do preco real de hoje
        vol = float(p.V[i, j] / ind["vol_ant"][i, j]) if ind["vol_ant"][i, j] else float("nan")
        num = {"maxima_20": hi, "volume_x": vol}
        txt = (f"{t} fechou acima da máxima dos 20 pregões anteriores (R$ {br(hi)}) com volume {br(vol, 1)} vez(es) a média: "
               f"rompimento com participação.")
    elif fam == "d_resultado":
        c0, c1 = float(C[i - 2, j]), float(C[i, j])
        r2 = c1 / c0 - 1.0 if c0 > 0 else float("nan")
        num = {"reacao_2d": r2}
        if v["nucleo"] == "D1":
            va = ind["vol_ant"][i - 1, j]
            vx = float(np.nanmean(p.V[i - 1:i + 1, j]) / va) if va and va > 0 else float("nan")
            num["volume_x"] = vx
            txt = (f"{t} reagiu {pct(r2, 1, True)} em dois pregões à divulgação do resultado (entregue à CVM) com volume {br(vx, 1)} vez(es) a média: "
                   f"o setup aposta na continuação da reação nos pregões seguintes.")
        else:
            y = float(ev_lin) if ev_lin is not None and ev_lin == ev_lin else float("nan")
            num["lucro_yoy"] = y
            txt = (f"{t} divulgou lucro dos 12 meses {pct(y, 0, True)} acima do de um ano antes e o preço subiu {pct(r2, 1, True)} em dois pregões: "
                   f"o setup aposta na continuação.")
    elif fam == "e_forca_relativa":
        n = par["n"]
        rs = float(ind[f"rs{n}"][i, j])
        num = {"forca_relativa": rs, "janela": n}
        txt = (f"{t} está entre os 10% mais fortes do universo contra o Ibovespa em {n} pregões ({pct(rs, 1, True)} a mais que o índice) e acima da "
               f"média de 20: o setup aposta que a força continua.")
    elif fam == "f1_gap":
        g = float(ind["gap"][i, j])
        vol = float(p.V[i, j] / ind["vol_ant"][i, j]) if ind["vol_ant"][i, j] else float("nan")
        num = {"gap": g, "volume_x": vol}
        txt = (f"{t} abriu com gap de alta de {pct(g, 1)}, fechou perto da máxima do dia e negociou {br(vol, 1)} vez(es) o volume médio: "
               f"o setup aposta na continuação do movimento.")
    else:
        txt = f"Virada de mês: {t} está acima da média de 200 pregões; setup sazonal de {par['prazo']} pregões, sem alvo, só stop e prazo."
    return txt, num


def gerar(p, ind, eventos=None, i=-1):
    """Lista de candidatas no fechamento do indice `i` (padrao: o ultimo dia do painel). Cada uma e um dict simples (JSON)."""
    n = len(p.datas)
    i = i % n
    ev_yoy = {}
    if eventos is not None and len(eventos):
        for r in eventos.itertuples():
            ev_yoy[(r.ticker, int(r.i_evento))] = r.lucro_yoy
    out = []
    for v in nucleos_s0():
        sinal = setups.sinais(p, ind, v, eventos)[i]
        for j in np.nonzero(sinal)[0]:
            t = p.tickers[j]
            atr = float(ind["atr"][i, j])
            cru, c_aj = p.preco_cru[i, j], p.C[i, j]
            if not (np.isfinite(cru) and np.isfinite(c_aj) and c_aj > 0 and atr > 0):
                continue
            escala = float(cru / c_aj)
            par = v["params"]
            stop_dist = float(par["stop_atr"] * atr * escala)
            alvo_dist = float(par["alvo_atr"] * atr * escala) if par.get("alvo_atr") else None
            frase, numeros = _frase(v, p, ind, i, j, ev_yoy.get((t, i - 1)))
            out.append({
                "setup": v["nucleo"], "familia": v["familia"], "rotulo": setups.ROTULOS.get(v["familia"], v["familia"]), "ticker": t,
                "sinal_em": str(p.datas[i].date()), "preco_ref": float(cru), "atr_real": float(atr * escala), "stop_dist": stop_dist, "alvo_dist": alvo_dist,
                "stop_ref": float(cru - stop_dist), "alvo_ref": None if alvo_dist is None else float(cru + alvo_dist),
                "prazo": int(par["prazo"]), "adtv": float(p.adtv[i, j]), "top": bool(p.top[i, j]), "ibov_ok": bool(p.ibov_ok[i]),
                "porque": frase, "numeros": {k: (None if x != x else float(x)) for k, x in numeros.items()}})
    return out


def frase_da_regra(nucleo):
    """A regra do setup em uma frase (para a tela), sem numero de ticker."""
    if nucleo in ("M1", "M2"):
        return mesa_setups.regra_texto(nucleo)
    for v in nucleos_s0():
        if v["nucleo"] != nucleo:
            continue
        par = v["params"]
        fam = v["familia"]
        saida = (f"Stop em {br(par['stop_atr'], 1)} ATR" + (f", alvo em {br(par['alvo_atr'], 1)} ATR" if par.get("alvo_atr") else ", sem alvo") +
                 f", saída por tempo em {par['prazo']} pregões.")
        if fam == "a_pullback":
            r = f"Tendência de alta (preço > média de 50 > média de 200) e queda de {br(par['drop_atr'], 1)} ATR em {par['drop_n']} pregões."
        elif fam == "b_reversao":
            r = f"Queda de {br(par['drop_atr'], 1)} ATR em {par['drop_n']} pregões e preço abaixo das médias de 20 e 50."
        elif fam == "c_rompimento":
            r = f"Fechamento acima da máxima dos 20 pregões anteriores, acima da média de 50, com volume de {br(par['vol_x'], 1)}x a média."
        elif fam == "d_resultado" and nucleo == "D1":
            r = f"Dois pregões depois da entrega do resultado à CVM: alta de pelo menos {pct(par['reacao_min'], 0)} e volume de {br(par['vol_x'], 1)}x a média."
        elif fam == "d_resultado":
            r = f"Resultado entregue com lucro dos 12 meses pelo menos {pct(par['lucro_yoy_min'], 0)} acima do ano anterior e preço subindo na reação."
        elif fam == "e_forca_relativa":
            r = f"Entre os 10% de maior retorno em {par['n']} pregões contra o Ibovespa, retorno positivo e acima da média de 20."
        elif fam == "f1_gap":
            r = f"Gap de alta de pelo menos {pct(par['gap'], 0)}, fechamento no terço de cima da barra e volume de {br(par['vol_x'], 1)}x a média."
        else:
            r = "Terceiro pregão antes do último do mês, preço acima da média de 200."
        return r + " " + saida
    return ""
