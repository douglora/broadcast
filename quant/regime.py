"""
Regime de mercado (ALTA, NEUTRO, BAIXA) e plano de protecao em mini-indice.

POR QUE EXISTE. A carteira da INTERSECAO-PF e comprada em acoes com uma protecao fixa em
mini-indice (WIN). Em 08/10/2026 o Douglas viu o robo vendido em 1 contrato, o mercado virar e
a venda ficar no negativo sem ninguem decidir nada: a protecao nao sabia em que mercado estava
nem tinha stop. Este modulo da as duas coisas: um detector de regime que olha so o indice, e um
plano que traduz o regime em (a) quanto de acoes manter e (b) quanto de indice vender, com um
stop na perna vendida.

HIPOTESE (escrita antes de codar, ver PRE_REGISTRO.md em saida/pesquisa_carteira/):
  O indice de acoes brasileiro tem tendencia persistente em horizontes de 6 a 12 meses (ciclos de
  juro, cambio e fluxo estrangeiro duram trimestres) e a volatilidade e persistente (mercado em
  queda e mercado de vol alta). Reduzir acoes e vender indice quando preco, media longa e
  retorno de 12 meses concordam que o mercado esta em baixa corta a cauda esquerda a custo de
  perder o inicio de recuperacoes em V (2009, 2016, 2020). Do outro lado ficam quem compra a
  queda, fundos de acoes sem mandato para sair da bolsa e o varejo que compra "barato". A
  evidencia academica (momentum de serie temporal; vol-managed) e de reducao de queda maxima, nao
  de retorno medio maior: o objetivo aqui e perder menos em mercado ruim, nao ganhar mais.

CONTRATO DE NAO OLHAR O FUTURO.
  Toda funcao devolve, para a data t, um valor que depende SO de dados com data <= t. Quem usa
  o regime para operar tem de aplicar a defasagem: sinal no fechamento de t, execucao no
  fechamento do pregao seguinte (a mesma regra do backtest). `plano_protecao` ja embute essa
  defasagem na coluna `razao_exec`. `test_regime.py` prova que alterar o futuro nao muda o
  regime do passado.

DADO. O indice e qualquer serie de nivel (ou de retorno total) do mercado: aqui, o mercado NEFIN
(Rm_minus_Rf + Risk_Free composto), que e justamente o que o hedge simulado paga. A amplitude
media usa so fechamentos (|variacao diaria| media de 20 pregoes), porque o NEFIN nao tem
maxima e minima; e uma aproximacao do ATR de Wilder, menor que ele (nao ve o gap intradiario).

TODOS OS NUMEROS ABAIXO SAO CONVENCIONAIS E FORAM FIXADOS ANTES DE VER O RESULTADO. Nao existe
grade: mudar qualquer um deles e uma tentativa nova no livro (quant/livro.py).
"""
import numpy as np
import pandas as pd

ALTA, NEUTRO, BAIXA = "ALTA", "NEUTRO", "BAIXA"
ESTADOS = (ALTA, NEUTRO, BAIXA)

JANELA_CURTA = 50            # media curta (pregoes)
JANELA_LONGA = 200           # media longa
JANELA_MOM = 252             # retorno de 12 meses
JANELA_PICO = 252            # maxima de 12 meses
QUEDA_PICO = -0.10           # a menos de 10% da maxima de 12 meses conta como "perto do pico"
VOTOS_ALTA = 3               # 3 ou 4 de 4 votos: ALTA
VOTOS_BAIXA = 1              # 0 ou 1 de 4 votos: BAIXA (2 votos: NEUTRO)
CONFIRMACAO = 5              # pregoes seguidos no estado novo antes de trocar
JANELA_AMD = 20              # janela da amplitude media diaria

NOMES_VOTOS = ("acima_media_longa", "media_curta_acima", "mom12_positivo", "perto_do_pico")


# ─────────────────────────────────────────────────────────────
# Series do indice
# ─────────────────────────────────────────────────────────────
def indice_total(excesso, cdi=None):
    """Nivel (base 100) do indice de retorno total a partir do excesso diario e do CDI.

    Sem CDI usa so o excesso (indice "em excesso do CDI"); o detector funciona nos dois casos,
    mas com o CDI o nivel e o do mercado de verdade.
    """
    ex = pd.Series(excesso, dtype=float).sort_index()
    if cdi is not None:
        taxa = pd.Series(cdi, dtype=float).sort_index().reindex(ex.index)
        ex = ex + taxa
    ex = ex.dropna()
    nivel = 100.0 * (1.0 + ex).cumprod()
    nivel.name = "indice"
    return nivel


def amplitude_media(indice, janela=JANELA_AMD):
    """Media da variacao diaria absoluta (em pontos) dos ultimos `janela` pregoes."""
    s = pd.Series(indice, dtype=float)
    return s.diff().abs().rolling(janela, min_periods=janela).mean().rename("amd")


# ─────────────────────────────────────────────────────────────
# Detector
# ─────────────────────────────────────────────────────────────
def votos(indice, excesso=None, curta=JANELA_CURTA, longa=JANELA_LONGA, mom=JANELA_MOM,
          pico=JANELA_PICO, queda_pico=QUEDA_PICO):
    """Quatro votos de altista (1.0) ou nao (0.0); NaN enquanto faltar historia.

      acima_media_longa  preco acima da media de 200 pregoes
      media_curta_acima  media de 50 acima da media de 200
      mom12_positivo     retorno de 252 pregoes (em excesso do CDI se `excesso` for dado) > 0
      perto_do_pico      a menos de 10% da maxima de 252 pregoes

    Cada voto em t usa so janelas que terminam em t.
    """
    p = pd.Series(indice, dtype=float).sort_index()
    ma_l = p.rolling(longa, min_periods=longa).mean()
    ma_c = p.rolling(curta, min_periods=curta).mean()
    v = pd.DataFrame(index=p.index)
    v["acima_media_longa"] = (p > ma_l).astype(float).where(ma_l.notna())
    v["media_curta_acima"] = (ma_c > ma_l).astype(float).where(ma_l.notna() & ma_c.notna())
    if excesso is not None:
        ex = pd.Series(excesso, dtype=float).reindex(p.index)
        cum = (1.0 + ex.fillna(0.0)).cumprod()
        r12 = cum / cum.shift(mom) - 1.0
    else:
        r12 = p / p.shift(mom) - 1.0
    v["mom12_positivo"] = (r12 > 0).astype(float).where(r12.notna())
    maxima = p.rolling(pico, min_periods=pico).max()
    queda = p / maxima - 1.0
    v["perto_do_pico"] = (queda > queda_pico).astype(float).where(queda.notna())
    return v[list(NOMES_VOTOS)]


def classificar(v, alta=VOTOS_ALTA, baixa=VOTOS_BAIXA):
    """Estado bruto (sem histerese) a partir da soma dos votos. NaN onde algum voto falta."""
    completo = v.notna().all(axis=1)
    soma = v.sum(axis=1)
    out = pd.Series(NEUTRO, index=v.index, dtype=object)
    out[soma >= alta] = ALTA
    out[soma <= baixa] = BAIXA
    out[~completo] = np.nan
    out.name = "bruto"
    return out


def confirmar(bruto, dias=CONFIRMACAO):
    """Histerese por persistencia: o estado so troca depois de `dias` pregoes seguidos no novo.

    Causal: o valor em t depende so de bruto[:t+1]. O primeiro estado valido e adotado na hora.
    """
    saida = []
    atual, candidato, cont = None, None, 0
    for x in pd.Series(bruto).tolist():
        if x is None or (isinstance(x, float) and np.isnan(x)):
            saida.append(np.nan if atual is None else atual)
            continue
        if atual is None:
            atual = x
        elif x == atual:
            candidato, cont = None, 0
        else:
            if x == candidato:
                cont += 1
            else:
                candidato, cont = x, 1
            if cont >= int(dias):
                atual, candidato, cont = x, None, 0
        saida.append(atual)
    return pd.Series(saida, index=pd.Series(bruto).index, dtype=object, name="estado")


def detectar(indice, excesso=None, dias_confirmacao=CONFIRMACAO, **kw):
    """DataFrame com os quatro votos, a soma, o estado bruto e o estado confirmado."""
    v = votos(indice, excesso, **kw)
    out = v.copy()
    out["soma_votos"] = v.sum(axis=1).where(v.notna().all(axis=1))
    out["bruto"] = classificar(v)
    out["estado"] = confirmar(out["bruto"], dias_confirmacao)
    return out


def trocas(estado):
    """Quantas vezes o estado confirmado mudou (so entre estados validos)."""
    s = pd.Series(estado).dropna()
    if len(s) < 2:
        return 0
    return int((s != s.shift(1)).iloc[1:].sum())


def dias_por_estado(estado):
    s = pd.Series(estado).dropna()
    return {e: int((s == e).sum()) for e in ESTADOS}


# ─────────────────────────────────────────────────────────────
# Plano: do regime para (acoes, indice vendido)
# ─────────────────────────────────────────────────────────────
def mapa(exposicao_baixa=0.70, razao_baixa=1.0, razao_neutro=0.5, exposicao_neutro=0.70,
         exposicao_alta=0.70, razao_alta=0.0):
    """Mapa estado -> {exposicao: fracao do patrimonio em acoes, razao: nocional de indice
    vendido / valor das acoes}. ALTA = acoes cheias e protecao zero."""
    return {ALTA: {"exposicao": float(exposicao_alta), "razao": float(razao_alta)},
            NEUTRO: {"exposicao": float(exposicao_neutro), "razao": float(razao_neutro)},
            BAIXA: {"exposicao": float(exposicao_baixa), "razao": float(razao_baixa)}}


def plano_protecao(indice, estado, mp, stop_atr=None, janela_amd=JANELA_AMD, defasagem=1):
    """Plano diario da perna vendida de indice, com stop de ATR opcional.

    indice, estado: series alinhadas (estado confirmado, de `detectar`). mp: de `mapa`.
    stop_atr: None (sem stop) ou X: em BAIXA, com a venda ja em vigor, se o indice fechar acima de
      (nivel em que a venda foi montada + X x amplitude media) a protecao e REDUZIDA para a razao
      do NEUTRO ("stopada") ate o regime confirmar de novo: o stop so rearma quando o indice volta a
      fechar abaixo do nivel da venda, ou quando o regime sai de BAIXA e volta. Fechamento a
      fechamento, e o stop vale no pregao seguinte (defasagem): e mais lento que uma ordem de stop
      de verdade, ou seja conservador.
    defasagem: pregoes entre decidir (so dado ate d) e estar em vigor.

    Devolve DataFrame indexado como `indice` com:
      razao_decidida   razao de hedge decidida no fechamento de d
      razao_exec       razao em vigor DEPOIS do fechamento de d (= decidida em d - defasagem)
      exposicao_sinal  exposicao em acoes pedida pelo estado de d (usada na boleta mensal)
      stopado          o stop esta acionado em d
      referencia       nivel em que a venda em vigor foi montada
      estado           o estado de regime de d (NaN antes de haver historia: tratado como NEUTRO)
    """
    p = pd.Series(indice, dtype=float).sort_index()
    est = pd.Series(estado).reindex(p.index)
    amd = amplitude_media(p, janela_amd)
    n = len(p)
    dec = np.zeros(n)
    exe = np.zeros(n)
    exp_sinal = np.zeros(n)
    stopado = np.zeros(n, dtype=bool)
    ref_serie = np.full(n, np.nan)
    ref, parado = np.nan, False
    razao_neutro = mp[NEUTRO]["razao"]
    pv, av = p.to_numpy(), amd.to_numpy()
    for i in range(n):
        e = est.iloc[i]
        e = NEUTRO if (e is None or (isinstance(e, float) and np.isnan(e))) else e
        m = mp[e]
        exp_sinal[i] = m["exposicao"]
        exe[i] = dec[i - defasagem] if i - defasagem >= 0 else 0.0
        # referencia da venda: nivel do fechamento em que a razao em vigor SUBIU
        if i > 0 and exe[i] > exe[i - 1] + 1e-12:
            ref = pv[i]
        if exe[i] <= 0.0:
            ref = np.nan
        decidida = m["razao"]
        if stop_atr is not None and e == BAIXA and m["razao"] > razao_neutro + 1e-12:
            if parado:
                if np.isfinite(ref) and pv[i] < ref:
                    parado = False                       # voltou abaixo do nivel da venda: rearma
                else:
                    decidida = razao_neutro
            elif (np.isfinite(ref) and exe[i] >= m["razao"] - 1e-12 and np.isfinite(av[i])
                  and pv[i] > ref + float(stop_atr) * av[i]):
                parado = True
                decidida = razao_neutro
        else:
            parado = False
        dec[i] = decidida
        stopado[i] = parado
        ref_serie[i] = ref
    return pd.DataFrame({"razao_decidida": dec, "razao_exec": exe, "exposicao_sinal": exp_sinal,
                         "stopado": stopado, "referencia": ref_serie, "estado": est.values},
                        index=p.index)


def eventos_de_stop(plano):
    """Quantas vezes o stop foi acionado (transicoes False -> True)."""
    s = pd.Series(plano["stopado"]).astype(bool)
    return int((s & ~s.shift(1, fill_value=False)).sum())


# ─────────────────────────────────────────────────────────────
# Variantes pre-registradas (ver saida/pesquisa_carteira/PRE_REGISTRO.md)
# ─────────────────────────────────────────────────────────────
# Cada variante tem no maximo 3 parametros livres: razao_baixa, stop_atr, exposicao_baixa. Os
# valores sao redondos e foram escritos antes de qualquer rodada de regime. S2 e a linha de base
# "protecao fixa em nocional" (regime desligado: o estado e sempre NEUTRO).
VARIANTES = {
    "S2": {"detector": False, "exposicao_baixa": 0.70, "razao_baixa": 0.5, "stop_atr": None},
    "R1": {"detector": True, "exposicao_baixa": 0.70, "razao_baixa": 1.0, "stop_atr": None},
    "R2": {"detector": True, "exposicao_baixa": 0.70, "razao_baixa": 1.0, "stop_atr": 3.0},
    "R3": {"detector": True, "exposicao_baixa": 0.55, "razao_baixa": 1.0, "stop_atr": 3.0},
    "R4": {"detector": True, "exposicao_baixa": 0.55, "razao_baixa": 1.2, "stop_atr": 3.0},
    "R5": {"detector": True, "exposicao_baixa": 0.40, "razao_baixa": 1.0, "stop_atr": 3.0},
}


def plano_da_variante(nome, excesso, cdi=None, defasagem=1, dias_confirmacao=CONFIRMACAO):
    """Plano diario (de `plano_protecao`) de uma variante pre-registrada, so com o excesso do
    mercado e o CDI. `detector=False` fixa o estado em NEUTRO (a linha de base S2)."""
    if excesso is None or len(excesso) == 0:
        return None
    v = VARIANTES[nome]
    ex = pd.Series(excesso, dtype=float).sort_index()
    idx = indice_total(ex, None if cdi is None else pd.Series(cdi, dtype=float).reindex(ex.index))
    if v["detector"]:
        est = detectar(idx, ex.reindex(idx.index), dias_confirmacao=dias_confirmacao)["estado"]
    else:
        est = pd.Series(NEUTRO, index=idx.index, dtype=object)
    mp = mapa(exposicao_baixa=v["exposicao_baixa"], razao_baixa=v["razao_baixa"])
    return plano_protecao(idx, est, mp, stop_atr=v["stop_atr"], defasagem=defasagem)
