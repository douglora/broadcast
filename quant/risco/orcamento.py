"""
Orcamento de risco: quanto de cada classe manter, quanto arriscar em cada tese de opcoes, e se o corte por queda esta valendo.

POR QUE EXISTE. O Douglas pediu um "gestor": saber a hora de diminuir ou aumentar a mao e alocar por classe. Este modulo so CALCULA e
EXPLICA; nao opera e nao esta ligado ao robo ao vivo. Funcoes puras (sem disco, sem rede); a leitura dos dados de hoje fica separada
em `carregar_entradas`, e o CLI (`python -m quant.risco.orcamento`) imprime e grava `quant/saida/risco/orcamento.json`.

TRES COISAS:
  (i)   EXPOSICAO POR CLASSE pela regra de mao por volatilidade congelada em `PRE_REGISTRO_MAO.md`: exposicao = min(1, vol media
        historica da classe / vol dos ultimos 63 pregoes). O que sobra da classe vai para o CDI.
  (ii)  RISCO MAXIMO POR TESE do livro de opcoes (perda maxima de cada estrutura contra o limite de R$ 500 por estrutura) e o
        TOTAL EM RISCO contra o limite de 3% do capital, mais o orcamento permanente do capital protegido (1% do capital por mes, lido do proprio livro).
  (iii) CORTE POR QUEDA: a regra existe (`quant.risco.mao.MaoQueda`), mas NAO se sustentou na pesquisa (nao melhorou o Sharpe nos
        dados livres e piorou no holdout refeito: realiza prejuizo no fundo). Por isso entra DESLIGADA (`ativo=False`): o orcamento
        so mostra em que estado ela estaria, sem aplicar. Ligar exige uma decisao nova do Douglas.

O QUE E EVIDENCIA E O QUE NAO E: a regra de volatilidade corta a cauda (queda maxima e pior mes) sem mudar o Sharpe de forma
confiavel (ver `RESULTADO_MAO_E_ALOCACAO.md`); os pesos entre classes (60/30/10 por padrao) sao uma escolha, nao um resultado.
"""
import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

from quant.risco import mao

CLASSES = ("acoes", "opcoes", "dolar")
PESOS_PADRAO = {"acoes": 0.60, "opcoes": 0.30, "dolar": 0.10}     # a regra 60/30/10 da pesquisa
RISCO_POR_ESTRUTURA_RS = 500.0                                   # limite do livro de opcoes (perda maxima por estrutura)
RISCO_TOTAL_PCT = 0.03                                           # limite do livro de opcoes (total em risco, % do capital)
ORCAMENTO_PROTEGIDO_PCT = 0.01                                   # capital protegido: 1% do capital por mes (era 0,5% ate 10/10/2026, decisao do modulo de opcoes)
ARQ_SAIDA = os.path.join("quant", "saida", "risco", "orcamento.json")
MOTIVO_QUEDA_DESLIGADA = ("nao se sustentou: nos dados livres 2001-2015 nao melhorou o Sharpe (2 de 4 series) e no holdout "
                          "refeito (descritivo) baixou o Sharpe de S0 de 0,34 para 0,29; realiza prejuizo no fundo (2022: -4,3% contra +2,1%)")


def _brl(x):
    return f"R$ {x:,.0f}".replace(",", ".")


def _pc(x, casas=1):
    """Percentual com virgula decimal (formato brasileiro)."""
    return f"{x * 100:.{casas}f}%".replace(".", ",")


def _d2(x):
    return f"{x:.2f}".replace(".", ",")


# ─────────────────────────────────────────────────────────────
# (i) Exposicao por classe
# ─────────────────────────────────────────────────────────────
def exposicao_de_classe(vol_recente, vol_alvo, teto=mao.TETO):
    """(exposicao, explicacao) de UMA classe: min(teto, vol_alvo / vol_recente). Sem dado: 1,0 e diz que faltou."""
    v, a = _num(vol_recente), _num(vol_alvo)
    if v is None or a is None or v <= 0 or a <= 0:
        return 1.0, "sem volatilidade suficiente para a regra: mao cheia (1,00)"
    e = float(min(float(teto), a / v))
    if v > a:
        txt = (f"volatilidade recente de {_pc(v)} esta acima da media historica de {_pc(a)}: a mao cai para {_d2(e)} "
               f"(a regra diminui a posicao quando o mercado esta mais agitado que o normal)")
    else:
        txt = (f"volatilidade recente de {_pc(v)} esta abaixo da media historica de {_pc(a)}: mao cheia (1,00, sem alavancagem)")
    return e, txt


def _num(x):
    try:
        v = float(x)
        return v if np.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def exposicoes_por_classe(vols, alvos, teto=mao.TETO):
    """dict classe -> {'vol_recente', 'vol_alvo', 'exposicao', 'porque'} para as classes em `vols`."""
    out = {}
    for c, v in vols.items():
        e, txt = exposicao_de_classe(v, alvos.get(c), teto)
        out[c] = {"vol_recente": _num(v), "vol_alvo": _num(alvos.get(c)), "exposicao": e, "porque": txt}
    return out


def alocar(capital, pesos, exposicoes):
    """R$ por classe: capital x peso; em risco = x exposicao; o resto vai para o CDI. `exposicoes`: classe -> {'exposicao': e}.
    Classe sem exposicao informada fica cheia (1,0). Devolve dict por classe mais o total."""
    capital = float(capital)
    soma = float(sum(pesos.values()))
    out, em_risco, no_cdi = {}, 0.0, 0.0
    for c, w in pesos.items():
        wc = float(w) / soma if soma > 0 else 0.0
        cap_c = capital * wc
        e = float((exposicoes.get(c) or {}).get("exposicao", 1.0))
        risco = cap_c * e
        out[c] = {"peso": wc, "capital_rs": cap_c, "exposicao": e, "em_risco_rs": risco, "para_o_cdi_rs": cap_c - risco}
        em_risco += risco
        no_cdi += cap_c - risco
    out["_total"] = {"capital_rs": capital, "em_risco_rs": em_risco, "para_o_cdi_rs": no_cdi,
                     "exposicao_media": em_risco / capital if capital else float("nan")}
    return out


# ─────────────────────────────────────────────────────────────
# (ii) Risco do livro de opcoes
# ─────────────────────────────────────────────────────────────
def risco_opcoes(teses, capital, risco_por_estrutura=RISCO_POR_ESTRUTURA_RS, risco_total_pct=RISCO_TOTAL_PCT,
                 orcamento_protegido_pct=ORCAMENTO_PROTEGIDO_PCT):
    """Risco maximo por tese (perda maxima = `risco_rs`) e total em risco, contra os limites do livro.

    teses: lista de dicts com 'titulo' e 'risco_rs' (e, se houver, 'vencimento', 'familia', 'permanente'). A posicao
    `permanente` (o capital protegido, orcamento mensal) entra a parte, como no livro simulado: nao conta no limite de estruturas
    nem nos 3%; sem ela na lista, o orcamento e `orcamento_protegido_pct` x capital."""
    capital = float(capital)
    linhas, total, protegido = [], 0.0, 0.0
    for t in teses or []:
        r = float(t.get("risco_rs") or 0.0)
        if t.get("permanente"):                       # capital protegido: orcamento mensal permanente, fora do limite de estruturas
            protegido += r
            continue
        total += r
        linhas.append({"tese": t.get("titulo") or t.get("id"), "familia": t.get("familia"), "vencimento": t.get("vencimento"),
                       "risco_max_rs": r, "pct_do_capital": r / capital if capital else float("nan"),
                       "limite_rs": float(risco_por_estrutura), "dentro_do_limite": bool(r <= float(risco_por_estrutura) + 1e-9)})
    limite_total = float(risco_total_pct) * capital
    return {"por_tese": linhas, "n_teses": len(linhas), "total_em_risco_rs": total,
            "total_pct_do_capital": total / capital if capital else float("nan"),
            "limite_total_rs": limite_total, "folga_rs": limite_total - total, "dentro_do_limite_total": bool(total <= limite_total + 1e-9),
            "capital_protegido_mensal_rs": protegido if protegido > 0 else float(orcamento_protegido_pct) * capital,
            "pior_caso_rs": total + (protegido if protegido > 0 else float(orcamento_protegido_pct) * capital)}


# ─────────────────────────────────────────────────────────────
# (iii) Corte por queda (desligado por padrao)
# ─────────────────────────────────────────────────────────────
def corte_por_queda(patrimonio, ativo=False, limiar=mao.LIMIAR_QUEDA, fator=mao.FATOR_CORTE, recuperacao=mao.RECUPERACAO):
    """Estado do corte por queda sobre o historico de patrimonio. `ativo=False` (padrao): so informa, a exposicao nao muda."""
    p = [float(x) for x in (patrimonio if patrimonio is not None else []) if _num(x) is not None]
    m = mao.MaoQueda(limiar, fator, recuperacao)
    dec = 1.0
    for x in p:
        dec = m.passo(x)
    pico = max(p) if p else float("nan")
    queda = (pico - p[-1]) / pico if p and pico > 0 else float("nan")
    return {"ativo": bool(ativo), "estaria_cortado": bool(m.cortado), "fator_se_ativo": float(dec),
            "exposicao_aplicada": float(dec) if ativo else 1.0, "queda_atual": queda, "limiar": float(limiar),
            "motivo": ("regra ligada: " + ("mao cortada pela metade" if m.cortado else "mao cheia")) if ativo else MOTIVO_QUEDA_DESLIGADA}


# ─────────────────────────────────────────────────────────────
# Montagem
# ─────────────────────────────────────────────────────────────
def orcamento(capital, vols, alvos, teses, patrimonio=None, pesos=None, teto=mao.TETO, queda_ativa=False, agora=None):
    """O orcamento completo de hoje. Funcao pura: recebe os numeros e devolve o dict que a tela mostra."""
    pesos = dict(pesos or PESOS_PADRAO)
    expo = exposicoes_por_classe(vols, alvos, teto)
    if "opcoes" in expo and expo["opcoes"]["vol_recente"] is None:
        expo["opcoes"]["porque"] = ("o risco desta classe e o premio pago pelas opcoes (limites no bloco de opcoes), nao a volatilidade: "
                                    "mao cheia (1,00) e o caixa fica no CDI")
    queda = corte_por_queda(patrimonio, ativo=queda_ativa)
    if queda["ativo"]:
        for c in expo:
            expo[c]["exposicao"] = min(expo[c]["exposicao"], queda["exposicao_aplicada"])
    aloc = alocar(capital, pesos, expo)
    ops = risco_opcoes(teses, capital)
    porque = []
    for c in CLASSES:
        if c in expo:
            porque.append(f"{_rotulo(c)}: {expo[c]['porque']}. Capital da classe {_brl(aloc[c]['capital_rs'])}; em risco {_brl(aloc[c]['em_risco_rs'])}; "
                          f"{_brl(aloc[c]['para_o_cdi_rs'])} ficam no CDI.")
    porque.append(f"Opcoes: {ops['n_teses']} tese(s) abertas com {_brl(ops['total_em_risco_rs'])} em risco ({_pc(ops['total_pct_do_capital'], 2)} do capital; "
                  f"limite {_brl(ops['limite_total_rs'])}, folga {_brl(ops['folga_rs'])}); mais {_brl(ops['capital_protegido_mensal_rs'])} por mes de capital protegido. "
                  f"A perda maxima de cada tese e o que ela custou.")
    porque.append("Corte por queda: " + queda["motivo"] + (f". Queda atual do patrimonio: {_pc(queda['queda_atual'], 2)}." if np.isfinite(queda["queda_atual"]) else "."))
    avisos = [c for c, t in expo.items() if c != "opcoes" and (t["vol_recente"] is None or t["vol_alvo"] is None)]
    return {"gerado_em": (agora or datetime.now()).isoformat(timespec="seconds"), "capital": float(capital),
            "regra_mao": {"nome": "volatilidade", "janela": 63, "teto": float(teto),
                          "alvo": "media da propria volatilidade (63 pregoes) ate ontem", "defasagem_pregoes": mao.DEFASAGEM},
            "pesos": {c: float(w) for c, w in pesos.items()}, "classes": {c: dict(expo[c], **aloc[c]) for c in expo if c in aloc},
            "total": aloc["_total"], "opcoes": ops, "corte_por_queda": queda, "porque": porque,
            "avisos": ([f"sem volatilidade para: {', '.join(avisos)} (mao cheia por falta de dado)"] if avisos else []),
            "descritivo": "evidencia: ver RESULTADO_MAO_E_ALOCACAO.md; a regra de volatilidade corta a cauda sem melhorar o Sharpe de forma confiavel; os pesos sao uma escolha, nao um resultado"}


def _rotulo(c):
    return {"acoes": "Acoes", "opcoes": "Opcoes (capital protegido)", "dolar": "Dolar (tendencia)"}.get(c, c)


# ─────────────────────────────────────────────────────────────
# Entradas de hoje (impuro: le disco)
# ─────────────────────────────────────────────────────────────
def _vol_e_alvo(ret, janela=63):
    """(vol dos ultimos `janela` pregoes, media historica da propria vol) de uma serie de retornos diarios."""
    r = pd.Series(ret, dtype=float).dropna()
    if len(r) < janela + 2:
        return None, None
    ex = mao.exposicao_por_vol(r, janela)
    ult = ex.iloc[-1]
    return _num(ult["vol"]), _num(ult["alvo"]) if np.isfinite(ult["alvo"]) else _num(ex["vol"].mean())


def carregar_entradas(painel="quant/saida/painel.json", livro_opcoes="quant/saida/opcoes/carteira_simulada.json",
                      ptax="quant/saida/pesquisa5/dolar_dias/dados/ptax_venda_sgs1.csv", serie_vivo="quant/saida/vivo/serie.json"):
    """Capital, volatilidades de hoje, teses de opcoes e historico de patrimonio. Cada pedaco que falta vira None e um aviso."""
    avisos = {}
    p = _ler_json(painel) or {}
    capital = _num(p.get("capital")) or 100_000.0
    vols, alvos = {"acoes": None, "dolar": None}, {"acoes": None, "dolar": None}
    # acoes: carteira-alvo da boleta de hoje (pesos pelo financeiro), vol dos ultimos 63 pregoes e media historica desde 2016
    try:
        from quant import sinais as sg
        from quant.dados import cotahist, eventos
        ordens = (p.get("boleta") or {}).get("ordens") or []
        pesos = pd.Series({o["ticker"]: float(o.get("financeiro") or 0.0) for o in ordens})
        if pesos.sum() > 0:
            pesos = pesos / pesos.sum()
            cot = cotahist.carregar(2016, datetime.now().year, tickers=list(pesos.index))
            ret = sg.painel_retornos(eventos.retorno_total_limpo(cot[["ticker", "data", "fec", "fatcot"]], eventos.carregar_eventos()))
            ret = ret[[c for c in pesos.index if c in ret.columns]]
            w = pesos.reindex(ret.columns)
            disp = ret.notna()
            pond = (ret.fillna(0.0) * w).sum(axis=1) / (disp * w).sum(axis=1).where((disp * w).sum(axis=1) >= 0.5 * w.sum())
            vols["acoes"], alvos["acoes"] = _vol_e_alvo(pond.dropna())
            avisos["acoes"] = f"carteira-alvo da boleta de {(p.get('boleta') or {}).get('data')} ({len(w)} papeis)"
    except Exception as e:                                          # pragma: no cover (depende do banco local)
        avisos["acoes"] = f"sem dado de acoes ({type(e).__name__}: {e})"
    # dolar: PTAX (dado de preco, desde 2016; a prova de regra de 2022+ continua fechada)
    try:
        s = pd.read_csv(ptax, parse_dates=["data"]).set_index("data")["valor"].astype(float)
        s = s[s.index >= "2016-01-01"]
        vols["dolar"], alvos["dolar"] = _vol_e_alvo(s.pct_change())
        avisos["dolar"] = f"PTAX venda ate {s.index.max().date()}"
    except Exception as e:                                          # pragma: no cover
        avisos["dolar"] = f"sem PTAX ({type(e).__name__}: {e})"
    # opcoes: sem volatilidade propria (o risco e o orcamento); a classe fica com mao cheia
    vols["opcoes"], alvos["opcoes"] = None, None
    lo = _ler_json(livro_opcoes) or {}
    teses = [x for x in (lo.get("posicoes") or []) if x.get("estado", "aberta") == "aberta"]
    sv = _ler_json(serie_vivo) or []
    pat = [x.get("patrimonio") for x in sv] if isinstance(sv, list) else []
    return {"capital": capital, "vols": vols, "alvos": alvos, "teses": teses, "patrimonio": pat, "fontes": avisos}


def _ler_json(caminho):
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Orcamento de risco de hoje (nao liga no robo)")
    ap.add_argument("--saida", default=ARQ_SAIDA)
    ap.add_argument("--capital", type=float, default=None)
    args = ap.parse_args(argv)
    e = carregar_entradas()
    cap = args.capital or e["capital"]
    o = orcamento(cap, e["vols"], e["alvos"], e["teses"], patrimonio=e["patrimonio"])
    o["fontes"] = e["fontes"]
    os.makedirs(os.path.dirname(args.saida), exist_ok=True)
    tmp = args.saida + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(o, f, ensure_ascii=False, indent=2, default=float)
    os.replace(tmp, args.saida)
    print(f"Orcamento de risco ({o['gerado_em']}), capital {_brl(o['capital'])}")
    for c in CLASSES:
        if c in o["classes"]:
            x = o["classes"][c]
            print(f"  {_rotulo(c):28s} peso {x['peso']:.0%}  exposicao {_d2(x['exposicao'])}  em risco {_brl(x['em_risco_rs']):>12s}  no CDI {_brl(x['para_o_cdi_rs']):>12s}")
    t = o["total"]
    print(f"  {'TOTAL':28s} em risco {_brl(t['em_risco_rs'])}  no CDI {_brl(t['para_o_cdi_rs'])}  (exposicao media {_d2(t['exposicao_media'])})")
    print()
    for linha in o["porque"]:
        print("-", linha)
    for a in o["avisos"]:
        print("AVISO:", a)
    print(f"\ngravado em {args.saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
