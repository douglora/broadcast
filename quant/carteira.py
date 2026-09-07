"""
Construcao de carteira (M10): do ranking de `sinais.py` para uma carteira-alvo em
quantidades inteiras, com hedge de indice e regra de rebalanceamento incremental.

Por que incremental: o gestor entrevistado descreve ter abandonado rebalanceamento por
calendario e passado a atualizar diariamente "so para aquelas acoes que distorceram tanto
que a gente sabe que pos custo transacional vale a pena executar". Com R$100 mil e
meio-spread de 25 a 80 bps, girar por girar consome o alfa inteiro. Aqui isso vira uma
regra dura: so negocia quando o desvio em reais supera LIMIAR_CUSTO vezes o custo
estimado da propria ordem.

DECISOES QUE A ESPECIFICACAO DEIXOU EM ABERTO, fixadas aqui:
  - Cap 6% e piso 3% sao percentuais do PATRIMONIO TOTAL, nao do book comprado. Com 22
    nomes o piso soma 66%, que e quase exatamente a exposicao alvo de 65-70%: e o que
    torna as duas regras coerentes.
  - A regra de 3x custo NAO se aplica a saida por falha de portao obrigatorio. Aplicar
    manteria para sempre um nome que reprovou em fluxo de caixa ou alavancagem so porque
    a posicao e pequena demais para pagar a corretagem. Aplica-se a entrada, ao ajuste e
    a saida por rank. A regra de 1,5 p.p. so vale para ajuste de quem ja esta na carteira.
  - O teto de 12 meses de holding NAO forca venda: revoga a histerese. O nome volta a
    disputar vaga pelo rank como se fosse novo; se continua no topo, fica sem custo
    nenhum. A leitura literal ("vende aos 12 meses") produz um mes de carteira zerada
    quando varios nomes entraram juntos, e recompra tudo no mes seguinte pagando spread
    duas vezes por nada.
  - Quando o piso e infactivel (n x piso > exposicao, o que acontece com 25 nomes), o
    piso e reduzido proporcionalmente e a violacao e REPORTADA em `attrs['violacoes']`.
    Violar em silencio seria pior que nao ter regra.

ACHADO: A REGRA DE "3x CUSTO" DO PLANO E VAZIA COMO ESTA ESCRITA.
  A secao 7 diz "trade so quando |peso alvo - peso atual| x capital > 3 x custo estimado".
  Mas o custo estimado E uma fracao do proprio valor negociado: custo = c x valor, com c
  entre 0,3% e 1,5% neste modelo. A condicao vira `valor > 3 x c x valor`, ou seja
  `1 > 3c`, verdadeira para qualquer c abaixo de 33%. A regra NUNCA barra nada.
  A implementacao mantem a regra como escrita (e a especificacao aprovada, e ela custa
  nada), e `test_carteira` prova a vacuidade em vez de esconde-la. O que de fato limita o
  giro sao duas outras coisas: a regra de 1,5 p.p. para ajuste, que estava no plano, e
  VALOR_MIN_ORDEM, que NAO estava e foi acrescentada aqui - sem um piso absoluto o
  arredondamento de lote gera ordens de dezenas de reais que sao puro atrito. Isso e uma
  mudanca de desenho, esta sinalizada, e o numero (R$500) e conservador e ajustavel.

O QUE ESTE MODULO DELIBERADAMENTE NAO FAZ:
  - Nao gira entre classes da mesma empresa. O seletor de classe de `sinais.py` decide na
    ENTRADA e o estado guarda a escolha em `classe_travada`. Trocar de classe depois
    realiza ganho, paga spread duas vezes e consome a isencao de R$20 mil por CPF.
  - Nao dimensiona o hedge continuamente. Sao 1 contrato ate R$200 mil de patrimonio e 2
    acima, mexendo so no roll ou quando o beta de 60 pregoes sai da banda. Perseguir beta
    neutro com um contrato de R$35 mil de nocional e ilusao de precisao.

AVISO SOBRE O PESO 1/VOL: com 22 nomes, piso de 3% e exposicao de 70%, quase todo nome
encosta no piso e o peso por inverso da volatilidade quase nao se expressa. `diagnostico()`
mede isso (`fracao_no_piso` e `dispersao`) para o relatorio do backtest poder dizer se o
sinal de baixo risco esta fazendo alguma coisa ou e decoracao.
"""
import argparse
import sys

import numpy as np
import pandas as pd

from quant import custos as cst
from quant.dados import calendario

N_ALVO = 22
BANDA = (18, 25)
CAP_NOME = 0.06
PISO_NOME = 0.03
CAP_SETOR = 0.25
CAP_ILIQUIDOS = 0.40
ADTV_ILIQUIDO = 5_000_000.0
EXPOSICAO_ALVO = 0.70
CAIXA_MIN = 0.25
RANK_SAIDA = 40.0
MESES_MAX = 12
LIMIAR_CUSTO = 3.0            # do plano; ver o ACHADO no docstring: nao barra nada
LIMIAR_PESO = 0.015
VALOR_MIN_ORDEM = 500.0       # acrescentado aqui, fora do plano (ver ACHADO)
BETA_BANDA = (0.15, 0.55)
PREGOES_ROLL = 5
CAPITAL_2_CONTRATOS = 200_000.0
MARGEM_CONTRATO = 5_000.0
LOTE = 100
PRECO_MAX_LOTE = 30.0
MAX_ITER_PESOS = 20

COLUNAS_ORDEM = ["ticker", "lado", "qtd", "preco", "valor", "custo", "motivo", "fracionario"]
MOTIVOS_SAIDA = ("saida_gate", "saida_rank", "saida_prazo", "saida_universo")


# ─────────────────────────────────────────────────────────────
# Estado
# ─────────────────────────────────────────────────────────────
def estado_inicial(patrimonio, data=None):
    return {"data": data, "caixa": float(patrimonio), "patrimonio": float(patrimonio),
            "posicoes": {}, "classe_travada": {},
            "hedge": {"contratos": 0, "vencimento": None, "nivel_entrada": np.nan}}


def pesos_atuais(estado, precos):
    """Peso de cada posicao sobre o patrimonio, a precos correntes."""
    pat = float(estado.get("patrimonio") or 0.0)
    if pat <= 0:
        return pd.Series(dtype=float)
    itens = {t: p["qtd"] * float(precos.get(t, np.nan)) / pat for t, p in estado["posicoes"].items()}
    return pd.Series(itens, dtype=float)


# ─────────────────────────────────────────────────────────────
# Selecao com histerese
# ─────────────────────────────────────────────────────────────
def portao_obrigatorio(linha_ou_df):
    """Portoes 1, 2 e 3 (momento, qualidade, crescimento). As exclusoes 4, 5 e 6 valem
    para ENTRAR, nao obrigam a sair: quem ja carrega um nome nao vende porque ele entrou
    no decil caro do mes."""
    d = linha_ou_df
    return (d["passa_momentum"].astype(bool) & d["passa_qualidade"].astype(bool)
            & d["passa_crescimento"].astype(bool))


def selecionar(sinais_mes, posicoes=None, n=N_ALVO, banda=BANDA,
               rank_saida=RANK_SAIDA, meses_max=MESES_MAX):
    """Escolhe os nomes do mes com histerese.

    Devolve (lista de tickers, dict ticker -> motivo de saida). Quem ja esta na carteira
    so sai por falha de portao obrigatorio, por rank pior que `rank_saida`, por ter sumido
    do universo, ou por perder a disputa depois que o teto de `meses_max` meses revogou a
    histerese (ver o comentario no corpo: o teto nao forca venda, tira o passe livre).
    """
    posicoes = posicoes or {}
    if sinais_mes is None or len(sinais_mes) == 0:
        return [], {t: "saida_universo" for t in posicoes}
    s = sinais_mes.set_index("ticker")
    obrig = portao_obrigatorio(s)
    saidas, mantidos, reavaliar = {}, [], []
    for t, p in posicoes.items():
        if t not in s.index:
            saidas[t] = "saida_universo"
        elif not bool(obrig.get(t, False)):
            saidas[t] = "saida_gate"
        elif not np.isfinite(s.loc[t, "rank"]) or float(s.loc[t, "rank"]) > float(rank_saida):
            saidas[t] = "saida_rank"
        elif int(p.get("meses", 0)) >= int(meses_max):
            # Teto de 12 meses NAO forca venda: revoga a HISTERESE. O nome perde o direito
            # de ficar so por estar entre os ranks 23 e 40 e volta a disputar vaga como se
            # fosse novo. Se continua no topo, nao ha trade nenhum - forcar a venda e
            # recomprar no mesmo mes seria custo puro, e um mes em que todos os nomes
            # completassem 12 meses juntos zeraria a carteira.
            reavaliar.append(t)
        else:
            mantidos.append(t)
    def _rank(t):
        r = s.loc[t, "rank"] if t in s.index else np.nan
        return float(r) if np.isfinite(r) else 1e9
    # candidatos: quem esta em reavaliacao e os elegiveis de fora, todos disputando por rank
    novos = [t for t in s[s["elegivel"].astype(bool)].sort_values("rank").index
             if t not in mantidos and t not in saidas and t not in reavaliar]
    disputa = sorted(reavaliar + novos, key=_rank)
    alvo = list(mantidos)
    for t in disputa:
        if len(alvo) >= int(n):
            break
        alvo.append(t)
    for t in reavaliar:
        if t not in alvo:
            saidas[t] = "saida_prazo"
    if len(alvo) > banda[1]:
        ordenado = sorted(alvo, key=_rank)
        for t in ordenado[banda[1]:]:
            if t in posicoes:
                saidas[t] = "saida_rank"
        alvo = ordenado[:banda[1]]
    return alvo, saidas


# ─────────────────────────────────────────────────────────────
# Pesos
# ─────────────────────────────────────────────────────────────
def _preencher(bruto, cap, piso, exposicao, fixos=None):
    """Distribui `exposicao` proporcionalmente a `bruto`, fixando quem bate no cap ou no
    piso e redistribuindo o resto entre os livres, ate ninguem mais violar.

    E o unico jeito de cap e piso valerem ao mesmo tempo: normalizar depois de cortar
    (o que a versao ingenua faz) devolve pesos abaixo do piso.
    """
    fixos = dict(fixos or {})
    w = pd.Series(0.0, index=bruto.index, dtype=float)
    for t, v in fixos.items():
        w[t] = v
    livres = [t for t in bruto.index if t not in fixos]
    resto = exposicao - sum(fixos.values())
    for _ in range(MAX_ITER_PESOS):
        if not livres:
            break
        base = bruto[livres].clip(lower=0.0)
        soma = base.sum()
        prop = base / soma * resto if soma > 0 else pd.Series(resto / len(livres), index=livres)
        estourou = [t for t in livres if prop[t] > cap + 1e-12]
        furou = [t for t in livres if prop[t] < piso - 1e-12]
        if estourou:
            for t in estourou:
                w[t] = cap
                resto -= cap
            livres = [t for t in livres if t not in estourou]
            continue
        if furou:
            for t in furou:
                w[t] = piso
                resto -= piso
            livres = [t for t in livres if t not in furou]
            continue
        for t in livres:
            w[t] = prop[t]
        break
    return w


def pesos_alvo(tickers, vol, setor=None, adtv=None, exposicao=EXPOSICAO_ALVO,
               cap=CAP_NOME, piso=PISO_NOME, cap_setor=CAP_SETOR,
               cap_iliquidos=CAP_ILIQUIDOS, adtv_iliquido=ADTV_ILIQUIDO):
    """Pesos sobre o PATRIMONIO: 1/vol, com cap e piso por nome, teto por setor e teto
    para o balde iliquido.

    `attrs['violacoes']` lista as restricoes que nao puderam ser satisfeitas juntas -
    violar em silencio seria pior que nao ter regra.
    """
    tickers = list(tickers)
    if not tickers:
        s = pd.Series(dtype=float)
        s.attrs["violacoes"] = []
        return s
    v = pd.Series({t: float(vol.get(t, np.nan)) if vol is not None else np.nan for t in tickers})
    mediana = v[v > 0].median()
    v = v.where(v > 0, mediana if np.isfinite(mediana) else 1.0)
    bruto = 1.0 / v
    violacoes = []
    piso_ef, cap_ef = float(piso), float(cap)
    n = len(tickers)
    if n * piso_ef > exposicao + 1e-12:
        piso_ef = exposicao / n
        violacoes.append(f"piso {piso:.1%} infactivel com {n} nomes; usado {piso_ef:.2%}")
    if n * cap_ef < exposicao - 1e-12:
        cap_ef = exposicao / n
        violacoes.append(f"cap {cap:.1%} nao cobre a exposicao com {n} nomes; usado {cap_ef:.2%}")
    w = _preencher(bruto, cap_ef, piso_ef, exposicao)
    # tetos de grupo: fixa o grupo estourado no teto e redistribui o resto
    grupos = {t: (setor.get(t) if setor else None) for t in tickers}
    ilq = {t: bool(adtv is not None and float(adtv.get(t, np.inf)) < adtv_iliquido) for t in tickers}
    for _ in range(MAX_ITER_PESOS):
        fixos, estourou = {}, False
        chaves = {g for g in grupos.values() if g is not None}
        for chave in chaves:
            membros = [t for t in tickers if grupos[t] == chave]
            soma = float(w[membros].sum())
            if soma > cap_setor + 1e-9:
                escala = cap_setor / soma
                fixos.update({t: max(w[t] * escala, 0.0) for t in membros})
                estourou = True
        membros_ilq = [t for t in tickers if ilq[t]]
        teto_ilq = cap_iliquidos * exposicao
        if membros_ilq and float(w[membros_ilq].sum()) > teto_ilq + 1e-9:
            escala = teto_ilq / float(w[membros_ilq].sum())
            for t in membros_ilq:
                fixos[t] = max(w[t] * escala, 0.0)
            estourou = True
        if not estourou:
            break
        if len(fixos) >= n:
            w = pd.Series(fixos)
            break
        w = _preencher(bruto, cap_ef, piso_ef, exposicao, fixos=fixos)
    if w.sum() > 0 and abs(w.sum() - exposicao) > 1e-9:
        violacoes.append(f"exposicao {w.sum():.2%} diferente do alvo {exposicao:.0%}")
    for chave in {g for g in grupos.values() if g is not None}:
        membros = [t for t in tickers if grupos[t] == chave]
        if membros and float(w[membros].sum()) > cap_setor + 1e-6:
            violacoes.append(f"setor {chave} em {w[membros].sum():.1%} acima do teto {cap_setor:.0%}")
    if (w > cap_ef + 1e-6).any():
        violacoes.append("cap por nome estourado apos os tetos de grupo")
    w.attrs["violacoes"] = violacoes
    return w


def diagnostico(pesos, piso=PISO_NOME):
    """Mede se o peso 1/vol esta fazendo alguma coisa (ver o aviso no docstring do modulo)."""
    if pesos is None or len(pesos) == 0:
        return {"n": 0, "fracao_no_piso": float("nan"), "dispersao": float("nan"),
                "maior": float("nan"), "violacoes": []}
    p = pd.Series(pesos)
    return {"n": int(len(p)),
            "fracao_no_piso": float((p <= piso + 1e-9).mean()),
            "dispersao": float(p.max() / p.min()) if p.min() > 0 else float("inf"),
            "maior": float(p.max()),
            "violacoes": list(p.attrs.get("violacoes", []))}


def arredondar_lotes(pesos, precos, patrimonio, lote=LOTE, preco_max_lote=PRECO_MAX_LOTE):
    """Converte pesos em quantidades inteiras. Lote de 100 ate `preco_max_lote`, acima
    disso fracionario (que custa mais spread, e por isso e reportado).

    Devolve DataFrame(ticker, qtd, preco, valor, peso_alvo, peso_real, fracionario,
    erro_lote_pp) - `erro_lote_pp` e quanto o arredondamento afastou do peso desejado.
    """
    colunas = ["ticker", "qtd", "preco", "valor", "peso_alvo", "peso_real", "fracionario", "erro_lote_pp"]
    if pesos is None or len(pesos) == 0 or patrimonio <= 0:
        return pd.DataFrame(columns=colunas)
    linhas = []
    for t, w in pd.Series(pesos).items():
        pr = float(precos.get(t, np.nan)) if precos is not None else np.nan
        if not np.isfinite(pr) or pr <= 0:
            continue
        desejado = float(w) * float(patrimonio)
        usa_lote = pr <= preco_max_lote
        passo = lote if usa_lote else 1
        qtd = int(round(desejado / pr / passo)) * passo
        if qtd <= 0 and desejado > 0:
            qtd = passo if desejado >= 0.5 * passo * pr else 0
        valor = qtd * pr
        linhas.append({"ticker": t, "qtd": int(qtd), "preco": pr, "valor": valor,
                       "peso_alvo": float(w), "peso_real": valor / float(patrimonio),
                       "fracionario": not usa_lote,
                       "erro_lote_pp": (valor / float(patrimonio) - float(w)) * 100.0})
    return pd.DataFrame(linhas, columns=colunas)


# ─────────────────────────────────────────────────────────────
# Hedge de indice
# ─────────────────────────────────────────────────────────────
def contratos_hedge(patrimonio, capital_2=CAPITAL_2_CONTRATOS):
    """1 contrato ate `capital_2` de patrimonio, 2 acima. Sem dimensionamento continuo."""
    if patrimonio is None or not np.isfinite(patrimonio) or patrimonio <= 0:
        return 0
    return 2 if float(patrimonio) >= float(capital_2) else 1


def ajustar_hedge(estado, data, patrimonio, beta60=None, banda=BETA_BANDA,
                  pregoes_roll=PREGOES_ROLL, capital_2=CAPITAL_2_CONTRATOS):
    """Decide contratos e vencimento. Devolve (contratos, vencimento, motivo).

    motivo em {'roll', 'beta', 'tamanho', 'abertura', 'manter'}. So mexe no roll, quando o
    beta de 60 pregoes sai da banda, ou quando o patrimonio cruza o limiar de 2 contratos.
    """
    h = estado.get("hedge") or {}
    atual = int(h.get("contratos") or 0)
    venc = h.get("vencimento")
    alvo = contratos_hedge(patrimonio, capital_2)
    d = pd.Timestamp(data).date() if data is not None else None
    if atual == 0:
        return alvo, calendario.proximo_vencimento_indice(d) if d else None, "abertura"
    if venc is not None and d is not None:
        limite = calendario.pregoes_atras(venc, int(pregoes_roll))
        if d >= limite:
            return alvo, calendario.proximo_vencimento_indice(venc), "roll"
    if alvo != atual:
        return alvo, venc, "tamanho"
    if beta60 is not None and np.isfinite(beta60) and not (banda[0] <= float(beta60) <= banda[1]):
        return alvo, venc, "beta"
    return atual, venc, "manter"


def caixa_minimo(patrimonio, contratos, margem_contrato=MARGEM_CONTRATO, minimo=CAIXA_MIN):
    """Caixa exigido: o maior entre a fracao minima e a margem dos contratos de indice."""
    if patrimonio is None or patrimonio <= 0:
        return 0.0
    return float(max(float(minimo) * patrimonio, abs(int(contratos)) * float(margem_contrato)))


# ─────────────────────────────────────────────────────────────
# Ordens incrementais
# ─────────────────────────────────────────────────────────────
def ordens_incrementais(estado, alvo_qtd, precos, adtv, patrimonio, saidas=None,
                        estresse=1.0, limiar_custo=LIMIAR_CUSTO, limiar_peso=LIMIAR_PESO,
                        valor_min=VALOR_MIN_ORDEM, preco_max_lote=PRECO_MAX_LOTE):
    """Ordens que sobrevivem a regra de custo.

    `alvo_qtd`: dict/Series ticker -> quantidade alvo. `saidas`: dict ticker -> motivo,
    vindo de `selecionar`. Saida por portao obrigatorio ignora TODOS os filtros; entrada,
    ajuste e saida por rank passam pela regra de `limiar_custo` (que na pratica nao corta
    nada - ver o ACHADO no docstring do modulo) e pelo piso absoluto `valor_min`; ajuste
    ainda exige desvio de peso acima de `limiar_peso`.
    """
    saidas = saidas or {}
    alvo = pd.Series(alvo_qtd, dtype=float) if not isinstance(alvo_qtd, pd.Series) else alvo_qtd.astype(float)
    posicoes = estado.get("posicoes") or {}
    linhas = []
    for t in sorted(set(alvo.index) | set(posicoes)):
        pr = float(precos.get(t, np.nan)) if precos is not None else np.nan
        if not np.isfinite(pr) or pr <= 0:
            continue
        p = posicoes.get(t) or {}
        # A posicao e medida em VALOR, nao em quantidade: o valor evolui por retorno TOTAL
        # (com provento e desdobramento) e a quantidade nao. Vender `qtd x preco bruto`
        # deixava residuo de valor que era descartado no fechamento da posicao - um
        # vazamento silencioso proporcional ao dividendo acumulado e brutal em desdobramento.
        valor_atual = float(p.get("valor", float(p.get("qtd", 0.0)) * pr))
        q_alvo = float(alvo.get(t, 0.0))
        valor_alvo = q_alvo * pr
        if q_alvo <= 0:
            delta_valor = -valor_atual                      # saida total: vende a posicao inteira
        else:
            delta_valor = valor_alvo - valor_atual
        valor = abs(delta_valor)
        if valor < 1e-9:
            continue
        frac = pr > preco_max_lote
        adtv_t = float(adtv.get(t, np.nan)) if adtv is not None else np.nan
        custo = cst.custo_ordem(valor, adtv_t, fracionario=frac, estresse=estresse)["total"]
        if t in saidas:
            motivo = saidas[t]
        elif valor_atual <= 1e-9:
            motivo = "entrada"
        elif q_alvo <= 0:
            motivo = "saida_rank"
        else:
            motivo = "ajuste"
        if motivo != "saida_gate":
            if valor <= float(limiar_custo) * custo:      # do plano; na pratica nunca corta
                continue
            if valor < float(valor_min):                  # acrescentado: piso absoluto
                continue
            if motivo == "ajuste" and patrimonio > 0:
                if valor / float(patrimonio) <= float(limiar_peso):
                    continue
        linhas.append({"ticker": t, "lado": "C" if delta_valor > 0 else "V",
                       "qtd": int(round(valor / pr)), "preco": pr, "valor": valor,
                       "custo": float(custo), "motivo": motivo, "fracionario": bool(frac)})
    return pd.DataFrame(linhas, columns=COLUNAS_ORDEM)


def carteira_alvo(sinais_mes, estado, precos, adtv=None, setor=None, patrimonio=None,
                  exposicao=EXPOSICAO_ALVO, n=N_ALVO, estresse=1.0, data=None, beta60=None):
    """Orquestrador do mes: selecao -> pesos -> lotes -> ordens -> hedge.

    Devolve um dict com `tickers`, `pesos`, `alvo`, `ordens`, `hedge`, `caixa_minimo`,
    `diagnostico` e `n_efetivo`. `n_efetivo` e o numero de nomes que a estrategia
    REALMENTE conseguiu carregar: se cair abaixo da banda, o backtest nao esta testando a
    estrategia descrita e o relatorio precisa mostrar isso.
    """
    patrimonio = float(patrimonio if patrimonio is not None else estado.get("patrimonio", 0.0))
    tickers, saidas = selecionar(sinais_mes, estado.get("posicoes"), n=n)
    vol = {}
    if sinais_mes is not None and len(sinais_mes):
        vol = sinais_mes.set_index("ticker")["vol252"].to_dict()
    w = pesos_alvo(tickers, vol, setor=setor, adtv=adtv, exposicao=exposicao)
    alvo = arredondar_lotes(w, precos, patrimonio)
    alvo_qtd = alvo.set_index("ticker")["qtd"] if len(alvo) else pd.Series(dtype=float)
    ordens = ordens_incrementais(estado, alvo_qtd, precos, adtv, patrimonio,
                                 saidas=saidas, estresse=estresse)
    contratos, venc, motivo = ajustar_hedge(estado, data, patrimonio, beta60=beta60)
    return {"tickers": tickers, "saidas": saidas, "pesos": w, "alvo": alvo, "ordens": ordens,
            "hedge": {"contratos": contratos, "vencimento": venc, "motivo": motivo},
            "caixa_minimo": caixa_minimo(patrimonio, contratos),
            "diagnostico": diagnostico(w), "n_efetivo": len(tickers)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Carteira-alvo do mes (M10)")
    ap.add_argument("--patrimonio", type=float, default=100_000.0)
    ap.add_argument("--data", default=None)
    args = ap.parse_args(argv)
    from quant import sinais as sg
    s = sg.carregar()
    if s is None or len(s) == 0:
        print("sem sinais no banco; rode python -m quant.sinais")
        return 2
    d = pd.Timestamp(args.data) if args.data else pd.to_datetime(s["data"]).max()
    mes = sg.em(s, d)
    precos = mes.set_index("ticker")["preco"].to_dict()
    adtv = mes.set_index("ticker")["adtv21"].to_dict()
    setor = mes.set_index("ticker")["setor"].to_dict()
    r = carteira_alvo(mes, estado_inicial(args.patrimonio, d), precos, adtv=adtv,
                      setor=setor, patrimonio=args.patrimonio, data=d)
    print(f"data {d.date()}  n_efetivo {r['n_efetivo']}  hedge {r['hedge']['contratos']} contratos")
    print(r["alvo"].to_string(index=False))
    if r["diagnostico"]["violacoes"]:
        print("violacoes:", "; ".join(r["diagnostico"]["violacoes"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
