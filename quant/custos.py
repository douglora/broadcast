"""
Custos de execucao (M9): quanto do retorno bruto some entre a decisao e a posicao montada.

Por que existe: no cenario base do plano a estrategia entrega "CDI -0,5 a +1,0 p.p." e os
custos somam 1,1-1,6% a.a. O custo nao e um detalhe de implementacao, ele tem a MESMA ordem
de grandeza do alfa esperado; errar 50 bps a.a. aqui troca o sinal do veredito. Este modulo
concentra a conta num lugar so, sem tocar em dados nem em rede, para que o backtest (M11), a
regra de rebalanceamento incremental ("so negocia quando o ganho passa de 3x o custo", M10) e
o relatorio de execucao usem exatamente os mesmos numeros, e para que mudar uma premissa seja
mudar uma constante deste arquivo. Modulo folha de proposito: nada em quant importa daqui
para dentro, e daqui so saem dicionarios e DataFrames.

O que e FATO (tabela publicada) e o que e ESTIMATIVA (modelo declarado):
  - FATO, B3: emolumentos + liquidacao ~0,030% por lado no swing trade, 0,032% no leilao de
    fechamento e 0,023% no day trade. Corretagem e custodia sao zero nas corretoras
    consideradas (Clear/Genial), e por isso CORRETAGEM tem padrao ZERO. Ela e um valor
    FIXO POR ORDEM, e num desenho de rebalanceamento incremental — muitas ordens pequenas —
    esse formato e o mais caro que existe. `corretagem_maxima()` da o teto: com o excesso
    do cenario base, poucos reais por ordem. Tabela de banco inviabiliza o desenho, e essa
    conta tem de ser feita ANTES de abrir a conta, nao depois.
  - FATO, WIN: R$ 0,25-0,42 por contrato por lado (usado R$ 0,35) e R$ 0,20 por ponto do
    mini indice. O tick de slippage (5 pontos = R$ 1,00) e ESTIMATIVA conservadora.
  - FATO, IR: JCP tem 15% retidos na fonte. NEFIN e StatusInvest publicam o provento BRUTO,
    entao qualquer backtest alimentado por eles superestima o retorno; jcp_liquido() e o
    haircut que falta.
  - ESTIMATIVA, meio-spread por faixa de ADTV: 25 bps acima de R$ 20 mi/dia, 40 bps entre
    R$ 5 e 20 mi, 80 bps abaixo de R$ 5 mi. Small caps iliquidas tem spread cheio de 0,5-2%,
    e mesmo em nome liquido o slippage medido foi de +8 a +12 bps. NAO ha book no COTAHIST:
    nenhum destes tres numeros foi estimado nos proprios dados, eles vem da leitura da
    literatura e de fontes comunitarias de 2026.
  - ESTIMATIVA, fracionario: +20 bps, porque o livro fracionario e outro livro, com menos
    profundidade que o de lote padrao. ~30% das ordens de uma carteira de R$ 100 mil caem la.
  - ESTIMATIVA, impacto: 10 bps quando a ordem e 1% do ADTV, crescendo com a RAIZ da
    participacao (dobrar a ordem multiplica o impacto por 1,41, nao por 2). Forma funcional
    classica (Almgren, Kissell); a calibragem e um chute ancorado, nao uma medicao.
  - ESTIMATIVA, aluguel (so MVP-2, perna short): max(taxa, piso) x markup x valor x dias/252.
    O piso de 0,5% a.a. e o markup de 1,4-3,0x sobre a taxa do doador vem de fontes
    comunitarias; PF paga mais que institucional pelo mesmo papel.

Convencoes:
  - tudo em DECIMAL (0.0025 = 25 bps = 0,25%) dentro do modulo; `bps` so aparece como campo
    de saida, ja multiplicado por 10.000, para leitura humana;
  - todo custo e por LADO (uma ordem). Ida e volta e chamar duas vezes; um roll de WIN e
    fechar + abrir, dois lados;
  - o valor da ordem entra em modulo: compra e venda custam igual, o sinal e de quem chama;
  - `estresse` (o "modo 2x custos" do plano) multiplica SOMENTE os componentes ESTIMADOS
    (spread, fracionario, impacto). A taxa da B3 e publicada: dobrar uma tabela de
    emolumentos nao e cenario de estresse, e erro de modelagem. Ver custo_ordem();
  - entrada degenerada (valor 0, ADTV ausente, DataFrame vazio, texto no lugar de numero)
    devolve resultado com o schema certo e zeros, nunca excecao: este modulo roda dentro de
    um loop de backtest e nao pode derrubar a rodada por causa de uma linha suja;
  - ADTV desconhecido cai sempre na faixa MAIS CARA e ordem sem ADTV recebe o teto de
    impacto: nao saber a liquidez tem que doer, senao o backtest aprende a comprar o que
    nao tem preco.

O que precisa ser validado contra fonte real antes de operar:
  - a tabela de emolumentos e liquidacao vigente na B3 (as tres taxas acima e se ha minimo
    por ordem ou por nota);
  - corretagem, custodia e taxa de fracionario da corretora efetivamente aberta, por escrito;
  - o custo realizado no paper trading (fase 4 do plano) contra o tickercsv: o criterio de
    aprovacao e slippage realizado dentro de 1,5x do modelado por faixa de ADTV. Enquanto
    isso nao existir, FAIXAS_SPREAD e IMPACTO_BPS_EM_1PCT sao opiniao;
  - a tarifa por contrato de WIN da corretora e o tick efetivo observado no roll;
  - taxa de aluguel (tomador), markup real e tarifa minima por contrato, se o MVP-2 existir.
"""
import argparse
import math
import sys

import numpy as np
import pandas as pd

CORRETAGEM = 0.0              # R$ por ORDEM. Zero em Clear/Genial/Rico/Inter; NAO em banco
CUSTODIA_MES = 0.0            # R$ por mes; zero nas corretoras consideradas
TAXA_B3 = 0.00030             # emolumentos + liquidacao, por lado, swing trade
TAXA_B3_LEILAO = 0.00032      # leilao de fechamento
TAXA_B3_DAYTRADE = 0.00023    # day trade (nao usado pela estrategia; aqui para o M12/fiscal)
FAIXAS_SPREAD = ((20e6, 0.0025), (5e6, 0.0040), (0.0, 0.0080))   # (adtv minimo, meio-spread)
ADICIONAL_FRACIONARIO = 0.0020
IMPACTO_BPS_EM_1PCT = 10.0    # impacto = 10 * sqrt(participacao / 1%) bps
IMPACTO_TETO = 0.02           # 200 bps: teto do modelo de impacto (ver impacto())
WIN_VALOR_PONTO = 0.20        # R$ por ponto do mini indice
WIN_TARIFA_LADO = 0.35        # R$ por contrato por lado
WIN_TICK_PONTOS = 5.0         # 1 tick de slippage
IR_JCP = 0.15
ALUGUEL_PISO = 0.005
ALUGUEL_MARKUP = (1.4, 3.0)   # faixa; usa-se o ponto medio (ver custo_aluguel)
ALUGUEL_TARIFA = 0.0
DIAS_UTEIS_ANO = 252
# Ordens por ano que a estrategia gera, medidas no ensaio sintetico de 110 pregoes da fase 4
# (85 ordens = 0,77 por pregao x 252). E uma ESTIMATIVA sobre mercado artificial: serve para
# dimensionar a corretagem antes de abrir conta, e tem de ser refeita com o giro real.
ORDENS_ANO_ESTIMADAS = 195
BPS = 10_000.0

CHAVES_ORDEM = ("b3", "corretagem", "spread", "fracionario", "impacto", "total", "bps")
COLUNAS_ORDEM = ["ticker", "valor", "adtv", "fracionario", "leilao"]
COLUNAS_CUSTO = ["custo_" + k for k in CHAVES_ORDEM]
COLUNAS_CARTEIRA = COLUNAS_ORDEM + COLUNAS_CUSTO

_VERDADEIRO = ("1", "true", "t", "sim", "s", "y", "yes")


# ─────────────────────────────────────────────────────────────
# Numeros tolerantes (puras)
# ─────────────────────────────────────────────────────────────
def _num(x, padrao=float("nan")):
    """float(x) sem levantar: texto ilegivel, None ou lista viram `padrao` (NaN)."""
    if x is None or isinstance(x, (list, tuple, dict, set)):
        return padrao
    try:
        v = float(x)
    except (TypeError, ValueError):
        return padrao
    return v


def _valor(x):
    """Modulo do numero, 0.0 se ausente/ilegivel. Compra e venda custam igual."""
    v = _num(x)
    return abs(v) if math.isfinite(v) else 0.0


def _fator(estresse):
    """Multiplicador de estresse saneado: NaN, texto ou negativo viram 1.0 (sem estresse)."""
    e = _num(estresse)
    return e if math.isfinite(e) and e >= 0 else 1.0


def _flag(x):
    """Bandeira tolerante: None, NaN, 0, '' e 'nao' sao False. NaN NAO pode virar True
    (bool(nan) e True em Python), senao uma coluna faltante marcaria toda ordem como
    fracionaria."""
    if x is None:
        return False
    if isinstance(x, float) and math.isnan(x):
        return False
    if isinstance(x, str):
        return x.strip().lower() in _VERDADEIRO
    return bool(x)


def _faixas(faixas=FAIXAS_SPREAD):
    """Faixas normalizadas ((adtv_minimo, meio_spread), ...), da mais liquida para a menos."""
    return sorted(((float(a), float(b)) for a, b in faixas), key=lambda f: -f[0])


def _pior_spread(faixas=FAIXAS_SPREAD):
    """Meio-spread da faixa mais cara: o default para ADTV desconhecido."""
    valores = [float(b) for _, b in faixas]
    return max(valores) if valores else 0.0


# ─────────────────────────────────────────────────────────────
# Spread e impacto
# ─────────────────────────────────────────────────────────────
def meio_spread(adtv, faixas=FAIXAS_SPREAD):
    """Meio-spread em decimal (0.0025 = 25 bps) pela faixa de ADTV do papel.

    Aceita escalar ou pandas Series e devolve o mesmo formato (Series com o mesmo indice;
    lista/array devolvem array). Os limites pertencem a faixa MAIS BARATA: com o default,
    adtv = R$ 20 mi paga 25 bps e adtv = R$ 5 mi paga 40 bps. O limite e arbitrario e quem
    esta exatamente nele ja negocia como a faixa de cima.

    ADTV ausente (NaN), negativo ou ilegivel cai na faixa MAIS CARA. Nao saber a liquidez
    e equivalente a supor a pior, nunca a melhor: o vies tem que ser contra a estrategia.
    """
    fx = _faixas(faixas)
    pior = _pior_spread(faixas)
    if isinstance(adtv, pd.Series):
        v = pd.to_numeric(adtv, errors="coerce").to_numpy(dtype=float)
        cond = [v >= minimo for minimo, _ in fx]
        vals = [spread for _, spread in fx]
        out = np.select(cond, vals, default=pior) if cond else np.full(len(v), pior)
        return pd.Series(out, index=adtv.index, name="meio_spread", dtype=float)
    if isinstance(adtv, (list, tuple, np.ndarray, pd.Index)):
        return meio_spread(pd.Series(list(adtv), dtype="object"), faixas).to_numpy()
    x = _num(adtv)
    if not math.isfinite(x):
        return pior
    for minimo, spread in fx:
        if x >= minimo:
            return spread
    return pior


def impacto(valor, adtv, bps_em_1pct=IMPACTO_BPS_EM_1PCT, teto=IMPACTO_TETO):
    """Impacto de mercado em decimal: bps_em_1pct * sqrt(participacao / 1%) / 10.000.

    participacao = valor da ordem / ADTV. A raiz e a forma funcional classica (Almgren,
    Kissell): dobrar a ordem multiplica o impacto por ~1,41. Com o default, 1% do ADTV
    custa 10 bps e 4% custa 20 bps.

    Casos degenerados (o modulo nunca devolve inf, que viraria NaN no backtest):
      - adtv <= 0, NaN ou ilegivel -> `teto` (2%). Papel sem liquidez conhecida e caro;
      - valor <= 0, NaN ou ilegivel -> 0.0 (nao ha ordem, nao ha impacto);
      - o resultado tambem e limitado por `teto`: para passar de 2% seria preciso negociar
        mais de 400x o ADTV do dia, faixa em que o modelo e ficcao, nao estimativa.
    """
    a = _num(adtv)
    if not math.isfinite(a) or a <= 0:
        return float(teto)
    v = _num(valor)
    if not math.isfinite(v) or v <= 0:
        return 0.0
    participacao = abs(v) / a
    bruto = float(bps_em_1pct) * math.sqrt(participacao / 0.01) / BPS
    return min(bruto, float(teto))


# ─────────────────────────────────────────────────────────────
# Custo por ordem e por lado de WIN
# ─────────────────────────────────────────────────────────────
def custo_ordem(valor, adtv, fracionario=False, leilao=False, estresse=1.0,
                taxa_b3=TAXA_B3, taxa_b3_leilao=TAXA_B3_LEILAO, faixas=FAIXAS_SPREAD,
                adicional_fracionario=ADICIONAL_FRACIONARIO, bps_em_1pct=IMPACTO_BPS_EM_1PCT,
                corretagem=CORRETAGEM):
    """Custo de UM LADO de uma ordem de acao, em R$, decomposto.

    Devolve {b3, corretagem, spread, fracionario, impacto, total, bps}: tudo em R$ menos
    `bps`, que e total/valor x 10.000 (0.0 quando nao ha valor). Ida e volta = duas chamadas.

    `corretagem` e um valor FIXO POR ORDEM, nao um percentual — e e por isso que ela e
    perigosa nesta estrategia: o rebalanceamento incremental gera muitas ordens pequenas, e
    um custo fixo por ordem pesa proporcionalmente mais quanto menor a ordem. Ver
    `corretagem_maxima()`: com o excesso esperado do cenario base, o teto por ordem fica na
    casa de POUCOS REAIS. Corretora que cobra tabela de banco inviabiliza o desenho.

    `estresse` multiplica SOMENTE spread, fracionario e impacto - os componentes ESTIMADOS.
    A taxa da B3 e publicada: dobra-la nao seria cenario de estresse, seria inventar uma
    tabela de emolumentos que nao existe. Por isso o teste de robustez do backtest ("passa
    com 2x custos?") continua sendo um teste sobre o MODELO de execucao, que e a parte
    incerta, e o componente `b3` sai identico com estresse 1 ou 2.

    `leilao=True` usa a taxa do leilao de fechamento (mais cara). Ordem invalida (valor
    ausente/ilegivel) devolve todos os campos zerados, nunca excecao.
    """
    v = _valor(valor)
    e = _fator(estresse)
    b3 = v * (float(taxa_b3_leilao) if _flag(leilao) else float(taxa_b3))
    # corretagem so existe se houver ordem: valor zero nao gera cobranca
    corr = max(_num(corretagem, 0.0), 0.0) if v > 0 else 0.0
    corr = corr if math.isfinite(corr) else 0.0
    spread = v * meio_spread(adtv, faixas) * e
    frac = v * float(adicional_fracionario) * e if _flag(fracionario) else 0.0
    imp = v * impacto(v, adtv, bps_em_1pct) * e
    total = b3 + corr + spread + frac + imp
    return {"b3": b3, "corretagem": corr, "spread": spread, "fracionario": frac,
            "impacto": imp, "total": total, "bps": (total / v * BPS) if v > 0 else 0.0}


def corretagem_maxima(excesso_pp, capital, ordens_ano):
    """Quanto a corretora pode cobrar POR ORDEM antes de comer o excesso esperado.

    A pergunta que decide a corretora, e a resposta costuma assustar: no cenario base do
    plano o excesso liquido sobre o CDI e de ~0,3 p.p. ao ano. Sobre R$ 100 mil isso e
    R$ 300 no ano inteiro. Dividido por ~250 ordens, sobra pouco mais de R$ 1 por ordem.
    Nao e um argumento contra cobrar corretagem: e a constatacao de que uma tabela de
    banco (R$ 15-25 por ordem) custa 10 a 20 vezes o ganho esperado da estrategia.

    Devolve {excesso_reais, ordens_ano, por_ordem}. `por_ordem` e None quando nao ha
    ordens (nao da para dividir), e 0.0 quando nao ha excesso a defender.
    """
    exc = max(_num(excesso_pp, 0.0), 0.0)
    exc = exc if math.isfinite(exc) else 0.0
    cap = max(_valor(capital), 0.0)
    n = _num(ordens_ano, 0.0)
    n = int(n) if math.isfinite(n) and n > 0 else 0
    reais = cap * exc / 100.0
    return {"excesso_reais": reais, "ordens_ano": n,
            "por_ordem": (reais / n) if n > 0 else None}


def custo_corretagem_ano(por_ordem, ordens_ano, capital):
    """O outro lado da mesma conta: o que uma tabela custa por ano, em R$ e em % do capital.

    Devolve {reais_ano, pct_capital}. `pct_capital` e None sem capital.
    """
    tarifa = max(_num(por_ordem, 0.0), 0.0)
    tarifa = tarifa if math.isfinite(tarifa) else 0.0
    n = _num(ordens_ano, 0.0)
    n = int(n) if math.isfinite(n) and n > 0 else 0
    cap = max(_valor(capital), 0.0)
    reais = tarifa * n
    return {"reais_ano": reais, "pct_capital": (reais / cap) if cap > 0 else None}


def custo_win(contratos, estresse=1.0, tarifa_lado=WIN_TARIFA_LADO,
              tick_pontos=WIN_TICK_PONTOS, valor_ponto=WIN_VALOR_PONTO):
    """Custo de UM LADO do hedge em mini indice, em R$: {tarifa, tick, total}.

    tarifa = |contratos| x R$ 0,35 (FATO, tabela da corretora); tick = |contratos| x 5
    pontos x R$ 0,20 (ESTIMATIVA de slippage de 1 tick). So o tick e multiplicado por
    `estresse`, pela mesma razao do custo_ordem: tarifa e preco de tabela.

    Um roll bimestral e fechar + abrir, isto e, dois lados.
    """
    n = _valor(contratos)
    tarifa = n * float(tarifa_lado)
    tick = n * float(tick_pontos) * float(valor_ponto) * _fator(estresse)
    return {"tarifa": tarifa, "tick": tick, "total": tarifa + tick}


# ─────────────────────────────────────────────────────────────
# Proventos e aluguel
# ─────────────────────────────────────────────────────────────
def jcp_liquido(valor_bruto, ir=IR_JCP):
    """JCP liquido do IR retido na fonte (15%).

    Existe porque NEFIN e StatusInvest publicam o provento BRUTO: um backtest alimentado
    por eles ganha 15% do JCP que o investidor nunca recebe (0,2-0,4 p.p. a.a. no plano).
    Dividendos NAO passam por aqui (isentos ate a regra de 2026 de IRRF 10% acima de
    R$ 50 mil/mes do mesmo pagador, que e do M12 e depende do CPF, nao do papel).
    """
    v = _num(valor_bruto)
    if not math.isfinite(v):
        return 0.0
    return v * (1.0 - float(ir))


def _markup_medio(markup=ALUGUEL_MARKUP):
    """Ponto medio da faixa de markup. Escalar tambem e aceito."""
    if isinstance(markup, (list, tuple, np.ndarray, pd.Series)):
        vals = [float(x) for x in markup]
        if not vals:
            return 1.0
        return (min(vals) + max(vals)) / 2.0
    m = _num(markup)
    return m if math.isfinite(m) else 1.0


def custo_aluguel(taxa, valor, dias, piso=ALUGUEL_PISO, markup=ALUGUEL_MARKUP,
                  tarifa=ALUGUEL_TARIFA, dias_ano=DIAS_UTEIS_ANO):
    """Custo em R$ do aluguel (BTC) da perna short do MVP-2, para `dias` uteis de posicao.

    custo = max(taxa, piso) x markup_medio x valor x dias/252 + tarifa.

    `taxa` e a taxa anual do DOADOR (o numero publico do BDI da B3, em decimal: 0.02 = 2%
    a.a.). O tomador PF nao paga essa taxa: paga um multiplo dela. O markup e uma FAIXA
    (1,4x a 3,0x segundo fontes comunitarias, porque a divisao entre doador e corretora
    varia por corretora) e aqui usa-se o PONTO MEDIO - 2,2x no default. O ponto medio e
    escolha, nao medicao: para cenario pessimista passe markup=ALUGUEL_MARKUP[1].

    O piso de 0,5% a.a. impede que um papel com taxa publicada perto de zero (tipico de
    papel sem contrato no dia) pareca de graca. `tarifa` e a taxa fixa por contrato da
    corretora, se houver. Sem posicao (valor <= 0) ou sem prazo (dias <= 0) o custo e 0,
    inclusive a tarifa: nao ha contrato para cobrar.
    """
    v = _valor(valor)
    d = _valor(dias)
    if v <= 0 or d <= 0:
        return 0.0
    t = _num(taxa)
    t = float(piso) if not math.isfinite(t) else max(t, float(piso))
    return t * _markup_medio(markup) * v * (d / float(dias_ano)) + float(tarifa)


# ─────────────────────────────────────────────────────────────
# Carteira de ordens
# ─────────────────────────────────────────────────────────────
def custo_carteira(ordens, estresse=1.0, **kw):
    """Precifica uma boleta inteira: copia de `ordens` com as colunas COLUNAS_CUSTO.

    `ordens`: DataFrame com ticker, valor, adtv e, opcionalmente, fracionario e leilao
    (booleanos). Colunas que faltarem sao criadas com o default (valor/adtv NaN -> a linha
    custa 0 e cai na faixa mais cara; bandeiras -> False). Colunas extras do chamador sao
    preservadas. `kw` vai inteiro para custo_ordem (taxa_b3, faixas, ...).

    DataFrame vazio ou None devolve o schema COLUNAS_CARTEIRA sem linhas. O total em R$
    fica em .attrs["custo_total"] e tambem sai de total_carteira() - attrs se perde em
    quase toda operacao do pandas, entao a funcao e a forma confiavel.
    """
    if ordens is None or len(ordens) == 0:
        return pd.DataFrame(columns=COLUNAS_CARTEIRA)
    out = ordens.copy()
    for col, padrao in (("ticker", None), ("valor", np.nan), ("adtv", np.nan),
                        ("fracionario", False), ("leilao", False)):
        if col not in out.columns:
            out[col] = padrao
    custos = [custo_ordem(v, a, fracionario=f, leilao=l, estresse=estresse, **kw)
              for v, a, f, l in zip(out["valor"], out["adtv"], out["fracionario"], out["leilao"])]
    for chave in CHAVES_ORDEM:
        out["custo_" + chave] = [float(c[chave]) for c in custos]
    extras = [c for c in out.columns if c not in COLUNAS_CARTEIRA]
    out = out[COLUNAS_ORDEM + extras + COLUNAS_CUSTO]
    out.attrs["custo_total"] = float(sum(c["total"] for c in custos))
    out.attrs["estresse"] = _fator(estresse)
    return out


def total_carteira(custos, coluna="custo_total"):
    """Soma em R$ da coluna de custo de uma carteira ja precificada. 0.0 se vazia ou sem
    a coluna (a boleta que ninguem precificou custa zero, nao levanta)."""
    if custos is None or len(custos) == 0 or coluna not in getattr(custos, "columns", []):
        return 0.0
    return float(pd.to_numeric(custos[coluna], errors="coerce").fillna(0.0).sum())


# ─────────────────────────────────────────────────────────────
# CLI: tabela de sanidade
# ─────────────────────────────────────────────────────────────
def _adtv_exemplo(faixas=FAIXAS_SPREAD):
    """[(adtv_minimo, meio_spread, adtv_exemplo)] para a tabela do CLI: o exemplo e o
    proprio piso da faixa e, na faixa sem piso, uma fracao do piso da faixa de cima."""
    fx = _faixas(faixas)
    out = []
    for i, (minimo, spread) in enumerate(fx):
        adtv = minimo if minimo > 0 else (fx[i - 1][0] / 2.5 if i > 0 else 0.0)
        out.append((minimo, spread, adtv))
    return out


def _veredito_corretora(por_ordem, ordens_ano, capital):
    """A conta que decide a corretora, impressa para conferencia humana.

    Devolve 0 quando a tarifa cabe no cenario OTIMISTA, 1 quando so cabe no otimista mas
    nao no base, e 2 quando nao cabe em nenhum — o codigo de saida serve para script.
    """
    tab = custo_corretagem_ano(por_ordem, ordens_ano, capital)
    print(f"corretora: R$ {por_ordem:,.2f} por ordem | {ordens_ano} ordens/ano estimadas | "
          f"capital R$ {capital:,.2f}")
    print(f"  custo de corretagem: R$ {tab['reais_ano']:,.2f} por ano"
          + (f" = {tab['pct_capital']:.2%} a.a. do capital" if tab["pct_capital"] is not None else ""))
    print()
    print(f"{'cenario':>28} {'excesso a.a.':>14} {'em R$':>12} {'teto por ordem':>16} {'veredito':>12}")
    pior = 0
    for rotulo, exc in (("pessimista (0 p.p.)", 0.0), ("base (+0,3 p.p.)", 0.3),
                        ("otimista (+4 p.p.)", 4.0)):
        r = corretagem_maxima(exc, capital, ordens_ano)
        teto = r["por_ordem"]
        cabe = teto is not None and por_ordem <= teto
        if not cabe:
            pior += 1
        print(f"{rotulo:>28} {exc:>13.1f}p {r['excesso_reais']:>12,.0f} "
              f"{('R$ ' + format(teto, ',.2f')) if teto is not None else '--':>16} "
              f"{('cabe' if cabe else 'NAO CABE'):>12}")
    print()
    if pior >= 3:
        print("VEREDITO: a tarifa come o ganho esperado em TODOS os cenarios, inclusive o")
        print("otimista. Com este desenho — rebalanceamento incremental, muitas ordens")
        print("pequenas — a estrategia trabalha para a corretora. Negocie a tabela ou mude")
        print("de corretora antes de escrever mais uma linha de codigo.")
    elif pior == 2:
        print("VEREDITO: so sobra ganho no cenario OTIMISTA, que tem ~25% de probabilidade")
        print("subjetiva. Isso e apostar na cauda boa para pagar a corretagem.")
    else:
        print("VEREDITO: a tarifa cabe no cenario base. Confirme a tabela POR ESCRITO,")
        print("incluindo fracionario, custodia e a tarifa por contrato de WIN.")
    print()
    print("Lembrete: esta conta usa o giro estimado da estrategia, nao o seu giro real.")
    print(f"Reestime com --ordens-ano depois de 2 meses de paper trading.")
    return 0 if pior == 0 else (1 if pior < 3 else 2)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Custo modelado de ida e volta por faixa de ADTV (M9), para conferencia humana")
    ap.add_argument("--valor", type=float, default=10_000.0, help="valor financeiro da ordem em R$")
    ap.add_argument("--estresse", type=float, default=1.0,
                    help="multiplicador dos componentes estimados (2 = modo '2x custos')")
    ap.add_argument("--fracionario", action="store_true", help="ordem no livro fracionario (+20 bps)")
    ap.add_argument("--contratos", type=float, default=1.0, help="contratos de WIN por lado")
    ap.add_argument("--corretagem", type=float, default=None, metavar="REAIS",
                    help="tarifa da corretora por ORDEM: imprime o veredito e sai")
    ap.add_argument("--ordens-ano", type=int, default=ORDENS_ANO_ESTIMADAS,
                    help=f"ordens por ano da estrategia (padrao {ORDENS_ANO_ESTIMADAS})")
    ap.add_argument("--capital", type=float, default=100_000.0)
    args = ap.parse_args(argv)

    if args.corretagem is not None:
        return _veredito_corretora(args.corretagem, args.ordens_ano, args.capital)

    print(f"ordem de R$ {args.valor:,.2f} | estresse {args.estresse:g} | "
          f"fracionario: {'sim' if args.fracionario else 'nao'} | B3 {TAXA_B3 * BPS:.1f} bps por lado")
    print(f"{'adtv (R$)':>14} {'spread':>9} {'part':>8} {'b3':>8} {'spread':>9} {'frac':>8} "
          f"{'impacto':>9} {'ida':>9} {'ida bps':>8} {'ida+volta':>10} {'bps':>8}")
    for _, spread, adtv in _adtv_exemplo():
        c = custo_ordem(args.valor, adtv, fracionario=args.fracionario, estresse=args.estresse)
        part = args.valor / adtv if adtv > 0 else float("nan")
        print(f"{adtv:>14,.0f} {spread * BPS:>6.0f}bps {part:>8.2%} {c['b3']:>8.2f} "
              f"{c['spread']:>9.2f} {c['fracionario']:>8.2f} {c['impacto']:>9.2f} "
              f"{c['total']:>9.2f} {c['bps']:>8.1f} {2 * c['total']:>10.2f} {2 * c['bps']:>8.1f}")
    w = custo_win(args.contratos, estresse=args.estresse)
    print(f"WIN {args.contratos:g} contrato(s), um lado: tarifa R$ {w['tarifa']:.2f} + "
          f"tick R$ {w['tick']:.2f} = R$ {w['total']:.2f} (roll = 2 lados)")
    print(f"JCP R$ 1.000,00 brutos -> R$ {jcp_liquido(1000.0):,.2f} liquidos (IR {IR_JCP:.0%} na fonte)")
    print(f"aluguel MVP-2 (taxa 2% a.a., R$ {args.valor:,.2f}, 21 dias uteis, markup medio "
          f"{_markup_medio():g}x): R$ {custo_aluguel(0.02, args.valor, 21):,.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
