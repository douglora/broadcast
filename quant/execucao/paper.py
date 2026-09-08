"""
Paper trading (M13): preenche a boleta contra o negocio-a-negocio real e MEDE o custo.

Por que existe: `quant/custos.py` diz que a ida e volta custa de 0,3% a 1,5% e que o
meio-spread por faixa de ADTV e 25/40/80 bps. Esses tres numeros nao foram estimados nos
proprios dados - vieram da leitura da literatura e de fontes comunitarias - e o proprio
modulo de custos escreve isso no docstring: "enquanto isso nao existir, FAIXAS_SPREAD e
IMPACTO_BPS_EM_1PCT sao opiniao". Este modulo e o que transforma a opiniao em medicao:
casa cada linha da boleta contra os ticks que o arquivador ja guarda em
dados_brutos/negocios/ e devolve os dois numeros do criterio de pronto do M13 - slippage
realizado dentro de 1,5x do modelado e execucao de pelo menos 60% da quantidade pedida.

OS DOIS NUMEROS SO SIGNIFICAM ALGUMA COISA JUNTOS - e este e o achado central do modulo:
  Uma ordem LIMITADA nunca executa pior que o proprio limite. Entao `slippage_bps` medido
  contra o limite e, por construcao, <= 0 nesta simulacao: parece que a execucao e sempre
  melhor que o modelo. Nao e. O custo de uma ordem limitada nao aparece no preco, aparece
  na QUANTIDADE QUE NAO EXECUTOU - e essa parte some do relatorio se alguem olhar so o
  slippage. Por isso `medir_slippage` devolve sempre os dois campos, `slippage_bps` e
  `taxa_execucao`, e por isso `slippage_vwap_bps` (contra o VWAP do dia) existe: e a unica
  das tres medidas que pode dar um numero desfavoravel e comparavel com o modelo de custo.
  Um relatorio que celebre slippage negativo com 30% de execucao esta celebrando nao ter
  comprado.

COMO O CASAMENTO FUNCIONA (e o que ele deliberadamente NAO simula):
  - uma compra so executa contra negocios com preco <= preco_limite, a partir da hora de
    envio da boleta (10:20); venda e o espelho. Negocios antes da hora de envio sao
    ignorados: a ordem nao existia;
  - a quantidade executada e limitada a `participacao_max` (1%) do volume negociado no
    PERIODO em que a ordem esteve viva, nao do dia inteiro. Sem esse teto o paper trading
    executa 100% de tudo sempre e o numero de execucao vira decoracao;
  - os negocios sao consumidos em ordem cronologica e o preco do fill e a media ponderada
    do que foi consumido;
  - NAO ha fila de prioridade: o simulador supoe que a nossa ordem estava no book antes de
    cada negocio elegivel. Isso e OTIMISTA - no book real ha uma fila na frente. E o vies
    conhecido desta simulacao e a razao de o criterio de execucao ser 60%, e nao 90%;
  - NAO ha reprecificacao: a boleta ja traz os precos das 12:20 e 14:20, mas simular a
    reprecificacao exigiria supor que o usuario chegou no horario. Fica de fora, e isso
    torna a taxa de execucao PESSIMISTA. Os dois vieses andam em direcoes opostas e
    nenhum dos dois foi medido;
  - o custo do fill traz apenas o que e FATO (emolumentos da B3 e corretagem zero das
    corretoras consideradas). Spread e impacto NAO sao somados: eles ja estao dentro do
    preco executado, e soma-los seria contar o mesmo custo duas vezes.

CONVENCOES:
  - sinal do slippage: POSITIVO e desfavoravel (pagou mais que a referencia na compra,
    recebeu menos na venda). Vale para slippage_bps e slippage_vwap_bps;
  - sem execucao nenhuma, slippage e None e nao 0.0: zero seria dizer "executou no preco",
    que e mentira; taxa_execucao ai e 0.0, que e o numero verdadeiro;
  - nada levanta excecao: boleta vazia, bloqueada, sem negocios, com coluna faltando ou
    com texto no lugar de numero devolvem o schema certo e zeros.

Uso:
    python3 -m quant.execucao.paper --data 2026-09-08
"""
import argparse
import io
import math
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

from quant import custos as cst
from quant.comum import DIR_BRUTOS, ler_gzip, log
from quant.execucao import boleta as bo
# Os conversores tolerantes sao os MESMOS da boleta de proposito: o que a boleta leu como
# preco tem de ser o que o paper le como preco, senao a medicao compara duas leituras.
from quant.execucao.boleta import HORA_ENVIO, MAX_PARTICIPACAO, _iso, _json, _num, _reais

ORIGEM = "paper"
CORRETAGEM = 0.0              # FATO: Clear/Genial cobram zero em acoes (ver quant/custos.py)
INICIO_LEILAO = bo.INICIO_LEILAO
SUFIXO_FRACIONARIO = "F"      # o ticker do fracionario e o mesmo com F no fim
TAXA_EXECUCAO_MINIMA = 0.60   # criterio de pronto do M13
SLIPPAGE_MAX_X_MODELO = 1.5   # criterio de pronto do M13: realizado <= 1,5x o modelado
BPS = 10_000.0

COLUNAS_NEGOCIOS = ["ticker", "hora", "preco", "quantidade"]
# Copia local do contrato de quant/execucao/livro_ordens.py: este modulo tem de rodar
# enquanto aquele arquivo ainda nao existe. Quando existe, a ordem das colunas vem de la.
COLUNAS_FILL = ["data", "hora", "boleta", "ticker", "lado", "qtd", "preco",
                "corretagem", "emolumentos", "origem", "obs"]
# Nomes aceitos para cada coluna, do mais especifico ao mais generico. GrssTradAmt/TradQty/
# NtryTm/TckrSymb sao os do tickercsv cru; ticker/minuto/qtd sao os de barras_1min().
ALIASES = {"ticker": ("ticker", "TckrSymb", "tckrsymb", "papel"),
           "hora": ("hora", "minuto", "NtryTm", "ntrytm"),
           "preco": ("preco", "GrssTradAmt", "grsstradamt", "vwap", "fec"),
           "quantidade": ("quantidade", "qtd", "TradQty", "tradqty", "volume")}


# ─────────────────────────────────────────────────────────────
# Normalizacao do negocio-a-negocio (puras)
# ─────────────────────────────────────────────────────────────
def _hora(x):
    """'103015123' ou '10:30:15.123' ou '10:30' -> '10:30:15'. Ilegivel vira ''."""
    s = str(x).strip()
    if not s or s.lower() in ("nan", "none"):
        return ""
    if ":" in s:
        partes = (s.split(".")[0].split(":") + ["00", "00"])[:3]
        try:
            return ":".join(f"{int(p):02d}" for p in partes)
        except ValueError:
            return ""
    if not s.isdigit():
        return ""
    s = s.zfill(9)
    return f"{s[0:2]}:{s[2:4]}:{s[4:6]}"


def _coluna(df, chave):
    for nome in ALIASES[chave]:
        if nome in df.columns:
            return nome
    return None


def normalizar_negocios(negocios):
    """Ticks da B3 (ou barras de 1 minuto) -> DataFrame ticker, hora, preco, quantidade.

    Aceita tanto o tickercsv cru (TckrSymb, GrssTradAmt, TradQty, NtryTm) quanto a saida
    de arquivar_b3.barras_1min (ticker, minuto, vwap, qtd) - com barras cada minuto vira
    um "negocio" no VWAP do minuto, o que e mais grosseiro e deve ser dito no relatorio.
    Numero em formato brasileiro ('12,34') e tratado; linha sem preco, sem quantidade ou
    sem hora e descartada. DataFrame vazio ou None devolve o schema sem linhas.
    """
    if negocios is None or len(negocios) == 0:
        return pd.DataFrame(columns=COLUNAS_NEGOCIOS)
    d = negocios if isinstance(negocios, pd.DataFrame) else pd.DataFrame(negocios)
    if len(d) == 0:
        return pd.DataFrame(columns=COLUNAS_NEGOCIOS)
    cols = {c: _coluna(d, c) for c in COLUNAS_NEGOCIOS}
    if any(v is None for v in cols.values()):
        faltando = [c for c, v in cols.items() if v is None]
        log(f"negocios sem as colunas {faltando}; nada a casar")
        return pd.DataFrame(columns=COLUNAS_NEGOCIOS)
    from quant.dados.arquivar_b3 import numero_br
    out = pd.DataFrame({
        "ticker": d[cols["ticker"]].astype(str).str.strip().str.upper(),
        "hora": d[cols["hora"]].map(_hora),
        "preco": d[cols["preco"]].map(numero_br),
        "quantidade": d[cols["quantidade"]].map(numero_br),
    })
    if "UpdActn" in d.columns:                    # 'delete' = negocio cancelado
        out = out[~d["UpdActn"].astype(str).str.lower().str.contains("del").values]
    out = out[(out["hora"] != "") & out["preco"].gt(0) & out["quantidade"].gt(0)]
    return out.sort_values("hora", kind="stable").reset_index(drop=True)


def vwap_do_dia(barras, desde=None):
    """{ticker: VWAP} a partir das barras de 1 minuto (ou dos proprios ticks).

    Com `desde` ('HH:MM') so entra o que foi negociado a partir daquele horario. O padrao
    e o DIA INTEIRO, inclusive o leilao de abertura, ao qual a ordem das 10:20 nunca teve
    acesso: e uma referencia dura de proposito, porque o vies tem de ser contra a
    estrategia. Sem barras utilizaveis devolve {}.
    """
    d = normalizar_negocios(barras)
    if len(d) == 0:
        return {}
    if desde:
        d = d[d["hora"].str[:5] >= str(desde)[:5]]
    if len(d) == 0:
        return {}
    d = d.assign(financeiro=d["preco"] * d["quantidade"])
    g = d.groupby("ticker", sort=True).agg(financeiro=("financeiro", "sum"),
                                           qtd=("quantidade", "sum"))
    g = g[g["qtd"] > 0]
    return {t: float(v) for t, v in (g["financeiro"] / g["qtd"]).items()}


# ─────────────────────────────────────────────────────────────
# Simulacao dos fills
# ─────────────────────────────────────────────────────────────
def _colunas_fill():
    """A ordem das colunas vem do livro de ordens quando ele ja existe (import tardio)."""
    try:
        from quant.execucao import livro_ordens as lo
        return list(lo.COLUNAS_FILL)
    except ImportError:
        return list(COLUNAS_FILL)


def _tickers_da_ordem(ordem):
    """O papel e, se a ordem e fracionaria, o mesmo papel com sufixo F."""
    t = str(ordem.get("ticker", "")).strip().upper()
    if not t:
        return set()
    return {t, t + SUFIXO_FRACIONARIO} if ordem.get("fracionario") else {t}


def simular(boleta, negocios, participacao_max=MAX_PARTICIPACAO):
    """Casa cada ordem da boleta contra o negocio-a-negocio do dia.

    `negocios`: DataFrame com ticker, hora, preco e quantidade (a saida de arquivar_b3,
    crua ou em barras de 1 minuto). Uma compra so executa contra negocios com preco <=
    preco_limite a partir da hora de envio; venda e o espelho. A quantidade executada e
    limitada por `participacao_max` do volume negociado no periodo em que a ordem esteve
    viva. Devolve um DataFrame no formato COLUNAS_FILL com origem='paper', uma linha
    consolidada por ordem (as ordens sem execucao nenhuma NAO viram linha: um fill de
    quantidade zero sujaria o livro; a falta dela e o que medir_slippage conta).

    Boleta bloqueada, vazia ou sem negocios devolve o schema sem linhas.
    """
    colunas = _colunas_fill()
    b = boleta if isinstance(boleta, dict) else {}
    ordens = b.get("ordens") or []
    if not b.get("emitida", False) or not ordens:
        return pd.DataFrame(columns=colunas)
    d = normalizar_negocios(negocios)
    if len(d) == 0:
        return pd.DataFrame(columns=colunas)
    hora_envio = str(b.get("hora_envio") or HORA_ENVIO)[:5]
    part = _num(participacao_max, 0.0)
    part = part if math.isfinite(part) and part > 0 else 0.0
    vivos = d[d["hora"].str[:5] >= hora_envio]
    linhas = []
    for o in ordens:
        alvo = int(_num(o.get("qtd"), 0.0) or 0)
        limite = _num(o.get("preco_limite"))
        lado = "C" if str(o.get("lado")) == "C" else "V"
        papeis = _tickers_da_ordem(o)
        if alvo <= 0 or not math.isfinite(limite) or limite <= 0 or not papeis:
            continue
        janela = vivos[vivos["ticker"].isin(papeis)]
        if len(janela) == 0:
            continue
        volume = float(janela["quantidade"].sum())
        teto = int(math.floor(part * volume))          # teto de participacao, em acoes
        maximo = min(alvo, teto)
        if maximo <= 0:
            continue
        elegiveis = janela[janela["preco"] <= limite] if lado == "C" else janela[janela["preco"] >= limite]
        if len(elegiveis) == 0:
            continue
        # Consome os negocios elegiveis em ordem cronologica ate `maximo`: o corte e o
        # primeiro negocio em que o acumulado passa do teto, e dele leva-se so o pedaco.
        qs = elegiveis["quantidade"].to_numpy(dtype=float)
        ps = elegiveis["preco"].to_numpy(dtype=float)
        acum = np.cumsum(qs)
        corte = int(np.searchsorted(acum, maximo, side="left"))
        tomadas = qs.copy()
        if corte < len(qs):
            anterior = float(acum[corte - 1]) if corte > 0 else 0.0
            tomadas[corte] = max(maximo - anterior, 0.0)
            tomadas[corte + 1:] = 0.0
        usados = tomadas > 0
        executado = int(round(float(tomadas.sum())))
        if executado <= 0:
            continue
        financeiro = float((tomadas * ps).sum())
        n = int(usados.sum())
        hora = str(elegiveis["hora"].to_numpy()[usados][-1])
        preco = financeiro / executado
        taxa = cst.TAXA_B3_LEILAO if str(hora)[:5] >= INICIO_LEILAO else cst.TAXA_B3
        obs = [f"{n} negocios"]
        obs.append("total" if executado >= alvo else "parcial")
        if teto < alvo:
            obs.append(f"teto de {part:.2%} do volume do periodo")
        linhas.append({"data": b.get("data"), "hora": hora, "boleta": b.get("id"),
                       "ticker": str(o.get("ticker")), "lado": lado, "qtd": int(executado),
                       "preco": float(preco), "corretagem": float(CORRETAGEM),
                       "emolumentos": float(financeiro * taxa), "origem": ORIGEM,
                       "obs": "; ".join(obs)})
    return pd.DataFrame(linhas, columns=colunas)


# ─────────────────────────────────────────────────────────────
# Medicao
# ─────────────────────────────────────────────────────────────
def _sinal(lado):
    """+1 na compra, -1 na venda: transforma diferenca de preco em custo."""
    return 1.0 if str(lado) == "C" else -1.0


def _serie(df, coluna):
    """Coluna numerica do DataFrame; coluna ausente vira serie de zeros do tamanho certo."""
    if df is None or len(df) == 0 or coluna not in getattr(df, "columns", []):
        return pd.Series(np.zeros(0 if df is None else len(df)), dtype=float)
    return pd.to_numeric(df[coluna], errors="coerce").fillna(0.0).astype(float)


def medir_slippage(boleta, fills, barras=None):
    """Os dois numeros do criterio de pronto do M13, mais a decomposicao por ordem.

    Devolve dict com preco_medio_obtido, preco_limite, slippage_bps (contra o limite da
    boleta), slippage_vwap_bps (contra o VWAP do dia, so quando `barras` vier),
    taxa_execucao (quantidade executada / quantidade pedida), custo_realizado (taxas mais
    a diferenca de preco contra o limite, em R$) e `por_ordem`.

    Positivo e desfavoravel. O slippage contra o LIMITE e <= 0 por construcao (uma ordem
    limitada nao executa pior que o limite): quem julga a execucao tem de olhar
    `slippage_vwap_bps` e `taxa_execucao` juntos - ver o docstring do modulo. Sem execucao
    nenhuma os slippages sao None e a taxa e 0.0; nada levanta.
    """
    b = boleta if isinstance(boleta, dict) else {}
    ordens = b.get("ordens") or []
    f = fills if isinstance(fills, pd.DataFrame) else pd.DataFrame(fills or [])
    vwaps = vwap_do_dia(barras) if barras is not None else {}
    por_ordem, pedida, executada = [], 0.0, 0.0
    fin_exec, custo, taxas = 0.0, 0.0, 0.0
    soma_lim_pedida, soma_lim_exec = 0.0, 0.0
    for o in ordens:
        t, lado = str(o.get("ticker")), ("C" if str(o.get("lado")) == "C" else "V")
        alvo = float(_num(o.get("qtd"), 0.0) or 0.0)
        limite = _num(o.get("preco_limite"))
        if not math.isfinite(alvo) or alvo <= 0:
            continue
        sel = f                                   # filtra pelo que existir: fills feitos a mao
        if len(sel) and "ticker" in sel.columns:  # (conferencia de nota, por exemplo) podem
            sel = sel[sel["ticker"].astype(str) == t]     # nao trazer todas as colunas
        if len(sel) and "lado" in sel.columns:
            sel = sel[sel["lado"].astype(str) == lado]
        q = float(_serie(sel, "qtd").sum())
        fin = float((_serie(sel, "qtd") * _serie(sel, "preco")).sum())
        tx = float(_serie(sel, "corretagem").sum() + _serie(sel, "emolumentos").sum())
        medio = fin / q if q > 0 else float("nan")
        vwap = float(vwaps.get(t, float("nan")))
        slip = (_sinal(lado) * (medio - limite) / limite * BPS
                if q > 0 and math.isfinite(limite) and limite > 0 and math.isfinite(medio) else None)
        slip_vwap = (_sinal(lado) * (medio - vwap) / vwap * BPS
                     if q > 0 and math.isfinite(vwap) and vwap > 0 and math.isfinite(medio) else None)
        custo_preco = (_sinal(lado) * (medio - limite) * q) if (q > 0 and math.isfinite(limite)
                                                                and math.isfinite(medio)) else 0.0
        por_ordem.append({"ticker": t, "lado": lado, "qtd_pedida": alvo, "qtd_executada": q,
                          "taxa_execucao": (q / alvo) if alvo > 0 else 0.0,
                          "preco_limite": _json(limite),
                          "preco_medio_obtido": _json(medio),
                          "slippage_bps": _json(slip) if slip is not None else None,
                          "slippage_vwap_bps": _json(slip_vwap) if slip_vwap is not None else None,
                          "financeiro": fin, "taxas": tx,
                          "custo_realizado": float(tx + custo_preco)})
        pedida += alvo
        executada += q
        fin_exec += fin
        taxas += tx
        custo += custo_preco
        if math.isfinite(limite):
            soma_lim_pedida += limite * alvo
            soma_lim_exec += limite * q

    def _ponderado(chave):
        num, den = 0.0, 0.0
        for p in por_ordem:
            v = p.get(chave)
            w = abs(float(p.get("financeiro", 0.0)))
            if v is None or w <= 0:
                continue
            num += float(v) * w
            den += w
        return (num / den) if den > 0 else None

    return {"preco_medio_obtido": _json(fin_exec / executada) if executada > 0 else None,
            "preco_limite": _json(soma_lim_exec / executada) if executada > 0
                            else (_json(soma_lim_pedida / pedida) if pedida > 0 else None),
            "slippage_bps": _ponderado("slippage_bps"),
            "slippage_vwap_bps": _ponderado("slippage_vwap_bps"),
            "taxa_execucao": float(executada / pedida) if pedida > 0 else 0.0,
            "custo_realizado": float(taxas + custo),
            "qtd_pedida": float(pedida), "qtd_executada": float(executada),
            "financeiro": float(fin_exec), "taxas": float(taxas),
            "data": b.get("data"), "boleta": b.get("id"), "n_ordens": len(por_ordem),
            "por_ordem": por_ordem}


def acumular(medicoes):
    """Junta as medicoes de varios pregoes para o relatorio: media ponderada pelo FINANCEIRO.

    Ponderar pelo financeiro (e nao pela media simples dos dias) impede que um pregao com
    uma ordem de R$ 300 pese o mesmo que um pregao com R$ 30 mil - que e exatamente o erro
    que faria o relatorio de execucao dizer o contrario do que os dados dizem. A taxa de
    execucao sai das somas de quantidade, que e a definicao exata; os slippages sao medias
    ponderadas sobre os pregoes em que houve execucao. Lista vazia devolve zeros e None.
    """
    itens = [m for m in (medicoes or []) if isinstance(m, dict)]
    fin = float(sum(abs(float(_num(m.get("financeiro"), 0.0) or 0.0)) for m in itens))
    pedida = float(sum(float(_num(m.get("qtd_pedida"), 0.0) or 0.0) for m in itens))
    executada = float(sum(float(_num(m.get("qtd_executada"), 0.0) or 0.0) for m in itens))

    def _ponderado(chave):
        num, den = 0.0, 0.0
        for m in itens:
            v = m.get(chave)
            w = abs(float(_num(m.get("financeiro"), 0.0) or 0.0))
            if v is None or not math.isfinite(_num(v)) or w <= 0:
                continue
            num += float(v) * w
            den += w
        return (num / den) if den > 0 else None

    return {"n_pregoes": len(itens),
            "financeiro": fin,
            "qtd_pedida": pedida,
            "qtd_executada": executada,
            "taxa_execucao": (executada / pedida) if pedida > 0 else 0.0,
            "slippage_bps": _ponderado("slippage_bps"),
            "slippage_vwap_bps": _ponderado("slippage_vwap_bps"),
            "custo_realizado": float(sum(float(_num(m.get("custo_realizado"), 0.0) or 0.0)
                                         for m in itens))}


def veredito(medicao, modelado_bps=None, taxa_minima=TAXA_EXECUCAO_MINIMA,
             fator=SLIPPAGE_MAX_X_MODELO):
    """Traduz a medicao no criterio de pronto do M13: (passou, motivos).

    Slippage contra o VWAP dentro de `fator` x o modelado (quando ha um modelado para
    comparar) e execucao de ao menos `taxa_minima`. Sem execucao nenhuma, reprova.
    """
    m = medicao if isinstance(medicao, dict) else {}
    motivos = []
    taxa = float(_num(m.get("taxa_execucao"), 0.0) or 0.0)
    if taxa < float(taxa_minima):
        motivos.append(f"execucao de {taxa:.0%}, abaixo do minimo de {float(taxa_minima):.0%}")
    slip = m.get("slippage_vwap_bps")
    if modelado_bps is not None and slip is not None:
        teto = float(fator) * abs(float(modelado_bps))
        if float(slip) > teto:
            motivos.append(f"slippage de {float(slip):.1f} bps contra o VWAP, acima de "
                           f"{fator:g}x o modelado ({teto:.1f} bps)")
    return (not motivos), motivos


# ─────────────────────────────────────────────────────────────
# Disco
# ─────────────────────────────────────────────────────────────
def carregar_negocios(data, dir_brutos=None):
    """Le os ticks do universo do dia; na falta deles, as barras de 1 minuto.

    Sao os arquivos que quant/dados/arquivar_b3.py grava em
    dados_brutos/negocios/<data>/. Nada encontrado devolve o schema vazio, nao levanta -
    a B3 guarda o tickercsv por ~20 pregoes e um buraco no historico e normal.
    """
    d = _iso(data)
    pasta = os.path.join(dir_brutos or DIR_BRUTOS, "negocios", str(d))
    for nome in ("ticks_universo.csv.gz", "barras1m.csv.gz"):
        alvo = os.path.join(pasta, nome)
        if not os.path.exists(alvo):
            continue
        try:
            texto = ler_gzip(alvo).decode("utf-8", errors="replace")
            df = pd.read_csv(io.StringIO(texto), sep=";", dtype=str, keep_default_na=False,
                             engine="python", on_bad_lines="skip")
        except Exception as e:                      # noqa: BLE001 - arquivo truncado acontece
            log(f"falha lendo {alvo}: {type(e).__name__}")
            continue
        if nome.startswith("barras"):
            log("sem ticks do universo; usando barras de 1 minuto (casamento grosseiro)")
        return normalizar_negocios(df)
    return pd.DataFrame(columns=COLUNAS_NEGOCIOS)


def registrar(fills, caminho=None):
    """Grava os fills no livro de ordens. Import tardio: o livro pode ainda nao existir."""
    if fills is None or len(fills) == 0:
        return None
    try:
        from quant.execucao import livro_ordens as lo
    except Exception as e:                          # noqa: BLE001 - o livro pode nem existir
        log(f"livro de ordens indisponivel ({type(e).__name__}); fills nao registrados")
        return None
    return lo.registrar_fills(fills, **({"caminho": caminho} if caminho else {}))


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────
def _texto(medicao):
    def _bps(v):
        return "-" if v is None else f"{float(v):.1f} bps"
    return "\n".join([
        f"boleta {medicao.get('boleta')} ({medicao.get('data')}): "
        f"{medicao.get('n_ordens')} ordens, R$ {_reais(medicao.get('financeiro'))} executados",
        f"execucao          {float(medicao.get('taxa_execucao') or 0.0):.0%} "
        f"({medicao.get('qtd_executada'):.0f} de {medicao.get('qtd_pedida'):.0f} acoes)",
        f"slippage vs limite {_bps(medicao.get('slippage_bps'))}  "
        f"(<= 0 por construcao: ordem limitada nao executa pior que o limite)",
        f"slippage vs VWAP   {_bps(medicao.get('slippage_vwap_bps'))}  (positivo = desfavoravel)",
        f"custo realizado   R$ {_reais(medicao.get('custo_realizado'))} "
        f"(taxas R$ {_reais(medicao.get('taxas'))})",
    ])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Paper trading: preenche a boleta contra os ticks reais")
    ap.add_argument("--data", default=None, help="pregao (padrao: hoje)")
    ap.add_argument("--participacao", type=float, default=MAX_PARTICIPACAO)
    ap.add_argument("--modelado-bps", type=float, default=None,
                    help="slippage modelado em bps para o veredito de 1,5x")
    ap.add_argument("--registrar", action="store_true", help="grava os fills no livro de ordens")
    args = ap.parse_args(argv)
    d = _iso(args.data or date.today())
    b = bo.carregar(d)
    if b is None:
        print(f"sem boleta para {d}; rode python3 -m quant.execucao.boleta --data {d}")
        return 2
    negocios = carregar_negocios(d)
    if len(negocios) == 0:
        print(f"sem negocio-a-negocio arquivado para {d}; rode "
              f"python3 -m quant.dados.arquivar_b3 --data {d} --fontes negocios")
        return 2
    fills = simular(b, negocios, participacao_max=args.participacao)
    medicao = medir_slippage(b, fills, barras=negocios)
    print(_texto(medicao))
    passou, motivos = veredito(medicao, args.modelado_bps)
    for m in motivos:
        print(f"REPROVA: {m}")
    if args.registrar:
        registrar(fills)
    return 0 if passou else 1


if __name__ == "__main__":
    sys.exit(main())
