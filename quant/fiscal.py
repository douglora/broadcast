"""
Apuracao de imposto de renda sobre renda variavel para pessoa fisica (M12).

O QUE ESTE MODULO E E O QUE ELE NAO E. Ele calcula e mostra a conta linha a linha para
que ela POSSA SER CONFERIDA. Ele nao declara nada, nao emite guia e nao substitui
contador. Errar imposto para menos gera multa e juros sobre o contribuinte, e o
contribuinte aqui e o Douglas, nao o programa. Por isso `memoria_calculo()` existe e por
isso todo relatorio repete o aviso.

AS REGRAS QUE ESTAO CODIFICADAS (base: secao 4 do plano, apurada em 2026 sem acesso a
fonte oficial - cada numero e uma constante nomeada, com a fonte no comentario, para
poder ser corrigida num lugar so):

  - 15% sobre o ganho liquido mensal em operacoes COMUNS de renda variavel.
  - 20% sobre o ganho liquido mensal em DAY TRADE.
  - Isencao quando o total de vendas de ACOES A VISTA do CPF no mes fica em ate
    R$20 mil. So acoes: ETF, BDR, fundo imobiliario, futuro e day trade NAO contam para o
    teto nem sao isentos. Passou de R$20 mil, o lucro do mes inteiro em acoes e tributado.
  - Prejuizo compensa sem prazo, mas SO dentro do compartimento: comum com comum, day
    trade com day trade.
  - FUTUROS entram na base COMUM. O fato gerador e o AJUSTE DIARIO, nao o encerramento da
    posicao: por isso `apurar` recebe `ajustes_futuros` separado das operacoes.
  - IRRF de 0,005% sobre o valor das vendas comuns (o "dedo-duro") e de 1% sobre o lucro
    do day trade; os dois sao deduzidos do imposto devido.
  - DARF codigo 6015, vencimento no ultimo dia util do mes seguinte, valor minimo de
    R$10: abaixo disso nao se recolhe, ACUMULA para o mes seguinte.
  - JCP e tributado a 15% na fonte e nao entra no DARF. Dividendo e isento, exceto o IRRF
    de 10% sobre o que passar de R$50 mil por mes do mesmo pagador (Lei 15.270/2025).

DUAS DECISOES DE ENGENHARIA QUE MUDAM O RESULTADO:

  1. DAY TRADE E DETECTADO, NAO DECLARADO. Comprar e vender o mesmo papel no mesmo pregao
     muda a aliquota de 15% para 20% e troca o compartimento de prejuizo. Confiar num
     rotulo seria ingenuo: um fill parcial de manha seguido de um ajuste de posicao a
     tarde cria day trade sem ninguem ter pedido. `classificar_day_trade` separa pela
     propria movimentacao - a parte casada do dia e day trade, o residuo e comum.
  2. PREJUIZO EM MES ISENTO E CONTROVERSO. A Receita ja sustentou as duas leituras: que o
     prejuizo de um mes isento pode ser compensado adiante, e que nao pode. O modulo
     calcula DOS DOIS JEITOS, adota a conservadora (nao compensa) como padrao e devolve a
     diferenca em reais em `apurar(...)["divergencia_prejuizo_isento"]`, para a conversa
     com o contador ser sobre um numero e nao sobre uma duvida.

SUPOSICOES A VALIDAR:
  - O vencimento do DARF usa o ultimo PREGAO do mes seguinte como aproximacao do ultimo
    dia util bancario. Nos meses em que os dois diferem, a data sai um dia deslocada.
  - A isencao e por CPF e vale para todas as corretoras. Sem `vendas_externas` informado,
    o teto de R$20 mil e calculado so com o que passou por aqui, e o erro e para MENOS
    imposto, que e o erro caro. `isencao_disponivel()` existe para lembrar disso.
  - Custos (corretagem e emolumentos) entram no preco medio na compra e reduzem o produto
    da venda. Nao ha tratamento de aluguel de acoes (o MVP-1 nao tem ponta vendida).

Uso:
    python -m quant.fiscal --ano 2026
"""
import argparse
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

from quant.comum import DIR_SAIDA, garantir_dir, log
from quant.dados import calendario

# Aliquotas e limites — 2026
ALIQUOTA_COMUM = 0.15               # ganho liquido mensal em operacoes comuns
ALIQUOTA_DAY_TRADE = 0.20           # ganho liquido mensal em day trade
ISENCAO_VENDAS_MES = 20_000.0       # teto de vendas de acoes a vista por CPF no mes
IRRF_COMUM = 0.00005                # 0,005% sobre o valor da venda comum
IRRF_DAY_TRADE = 0.01               # 1% sobre o lucro do day trade
DARF_MINIMO = 10.0                  # abaixo disso acumula para o mes seguinte
CODIGO_DARF = "6015"
IR_JCP = 0.15                       # retido na fonte, fora do DARF
IRRF_DIVIDENDO = 0.10               # Lei 15.270/2025, acima do limite mensal por pagador
LIMITE_DIVIDENDO_MES = 50_000.0

CLASSES_ISENTAVEIS = ("acao",)      # so acao a vista entra no teto e na isencao
CLASSES = ("acao", "etf", "bdr", "fii", "futuro", "opcao")
COMPARTIMENTOS = ("comum", "day_trade")

ARQ_APURACAO = os.path.join(DIR_SAIDA, "fiscal_apuracao.csv")
ARQ_MEMORIA = os.path.join(DIR_SAIDA, "fiscal_memoria.csv")
ARQ_REVAR = os.path.join(DIR_SAIDA, "fiscal_revar.csv")

AVISO = ("calculo de apoio; confira a memoria de calculo e valide com contador antes de "
         "recolher qualquer DARF")

COLUNAS_OPERACAO = ["data", "ticker", "classe", "lado", "qtd", "preco", "valor", "custos", "fonte"]
COLUNAS_REALIZADA = ["data", "mes", "ticker", "classe", "modalidade", "qtd", "preco_venda",
                     "preco_medio", "valor_venda", "custos", "resultado"]
COLUNAS_APURACAO = [
    "mes", "vendas_acoes", "vendas_comuns", "isento",
    "resultado_acoes", "resultado_comum_bruto", "resultado_comum_tributavel",
    "resultado_day_trade", "ajuste_futuros",
    "prejuizo_ant_comum", "prejuizo_ant_day_trade",
    "base_comum", "base_day_trade", "imposto_comum", "imposto_day_trade", "imposto_total",
    "irrf_comum", "irrf_day_trade", "irrf_total",
    "darf_bruto", "darf_acumulado_ant", "darf_devido", "darf_a_acumular", "darf_vence",
    "prejuizo_comum", "prejuizo_day_trade",
]


# ─────────────────────────────────────────────────────────────
# Utilitarios puros
# ─────────────────────────────────────────────────────────────
def _vazio(colunas):
    return pd.DataFrame(columns=colunas)


def _mes(serie):
    return pd.to_datetime(serie).dt.to_period("M").astype(str)


def normalizar(operacoes):
    """Padroniza a tabela de operacoes: tipos, lado em C/V, classe conhecida, valor e custos."""
    if operacoes is None or len(operacoes) == 0:
        return _vazio(COLUNAS_OPERACAO)
    d = operacoes.copy()
    d["data"] = pd.to_datetime(d["data"])
    d["ticker"] = d["ticker"].astype(str).str.strip().str.upper()
    d["lado"] = d["lado"].astype(str).str.strip().str.upper().str[0]
    d["classe"] = (d["classe"].astype(str).str.strip().str.lower()
                   if "classe" in d else "acao")
    d.loc[~d["classe"].isin(CLASSES), "classe"] = "acao"
    d["qtd"] = pd.to_numeric(d["qtd"], errors="coerce").fillna(0.0).abs()
    d["preco"] = pd.to_numeric(d["preco"], errors="coerce")
    d["valor"] = (pd.to_numeric(d["valor"], errors="coerce")
                  if "valor" in d else d["qtd"] * d["preco"])
    d["valor"] = d["valor"].where(d["valor"].notna(), d["qtd"] * d["preco"])
    d["custos"] = pd.to_numeric(d.get("custos", 0.0), errors="coerce").fillna(0.0)
    d["fonte"] = d.get("fonte", "")
    d = d[(d["qtd"] > 0) & d["preco"].notna() & d["lado"].isin(("C", "V"))]
    return d[COLUNAS_OPERACAO].sort_values(["data", "ticker", "lado"]).reset_index(drop=True)


def classificar_day_trade(operacoes):
    """Separa cada (dia, ticker) na parte casada (day trade) e no residuo (comum).

    A quantidade de day trade e min(comprado, vendido) no dia. Ela e avaliada pelos precos
    MEDIOS de compra e de venda do proprio dia; o que sobra de um lado vira operacao comum,
    tambem ao preco medio do dia. Custos sao rateados pela quantidade.

    Devolve a tabela de operacoes com uma coluna `modalidade`, possivelmente com mais
    linhas que a entrada (uma ordem parcialmente casada vira duas).
    """
    ops = normalizar(operacoes)
    if ops.empty:
        return ops.assign(modalidade=pd.Series(dtype=str))
    linhas = []
    for (dia, ticker), g in ops.groupby([ops["data"].dt.normalize(), "ticker"], sort=True):
        classe = g["classe"].iloc[0]
        fonte = g["fonte"].iloc[0]
        for lado in ("C", "V"):
            sub = g[g["lado"] == lado]
            if sub.empty:
                continue
            qtd = float(sub["qtd"].sum())
            valor = float(sub["valor"].sum())
            custos = float(sub["custos"].sum())
            preco_medio = valor / qtd if qtd else np.nan
            oposto = g[g["lado"] == ("V" if lado == "C" else "C")]["qtd"].sum()
            q_dt = min(qtd, float(oposto))
            for modalidade, q in (("day_trade", q_dt), ("comum", qtd - q_dt)):
                if q <= 1e-9:
                    continue
                fatia = q / qtd
                linhas.append({"data": dia, "ticker": ticker, "classe": classe, "lado": lado,
                               "qtd": q, "preco": preco_medio, "valor": valor * fatia,
                               "custos": custos * fatia, "fonte": fonte,
                               "modalidade": modalidade})
    out = pd.DataFrame(linhas, columns=COLUNAS_OPERACAO + ["modalidade"])
    return out.sort_values(["data", "ticker", "modalidade", "lado"]).reset_index(drop=True)


def realizar(operacoes):
    """Resultado por venda, com preco medio movel dentro do compartimento comum.

    Compra soma quantidade e (valor + custos) ao custo total. Venda realiza
    qtd * (preco_venda - preco_medio) - custos da venda, e reduz o custo total
    proporcionalmente, que e a regra do preco medio (vender nao muda o preco medio do que
    sobra). Day trade e apurado no proprio dia, sem tocar no preco medio da posicao comum -
    e o que separa os dois compartimentos.
    """
    ops = classificar_day_trade(operacoes)
    if ops.empty:
        return _vazio(COLUNAS_REALIZADA)
    linhas = []
    posicao = {}                                   # ticker -> [qtd, custo_total]
    for dia, g_dia in ops.groupby(ops["data"], sort=True):
        # day trade primeiro: resolve dentro do dia e nao mexe na posicao carregada
        dt = g_dia[g_dia["modalidade"] == "day_trade"]
        for ticker, g in dt.groupby("ticker", sort=True):
            compra = g[g["lado"] == "C"]
            venda = g[g["lado"] == "V"]
            if compra.empty or venda.empty:
                continue
            q = float(min(compra["qtd"].sum(), venda["qtd"].sum()))
            pm_c = float(compra["valor"].sum() / compra["qtd"].sum())
            pm_v = float(venda["valor"].sum() / venda["qtd"].sum())
            custos = float(compra["custos"].sum() + venda["custos"].sum())
            linhas.append({"data": dia, "mes": str(pd.Period(dia, "M")), "ticker": ticker,
                           "classe": g["classe"].iloc[0], "modalidade": "day_trade", "qtd": q,
                           "preco_venda": pm_v, "preco_medio": pm_c, "valor_venda": pm_v * q,
                           "custos": custos, "resultado": q * (pm_v - pm_c) - custos})
        comum = g_dia[g_dia["modalidade"] == "comum"]
        for _, r in comum[comum["lado"] == "C"].iterrows():
            q, c = posicao.get(r["ticker"], [0.0, 0.0])
            posicao[r["ticker"]] = [q + r["qtd"], c + r["valor"] + r["custos"]]
        for _, r in comum[comum["lado"] == "V"].iterrows():
            q, c = posicao.get(r["ticker"], [0.0, 0.0])
            pm = (c / q) if q > 0 else 0.0
            qv = float(r["qtd"])
            resultado = r["valor"] - pm * qv - r["custos"]
            posicao[r["ticker"]] = [q - qv, c - pm * qv]
            if posicao[r["ticker"]][0] <= 1e-9:
                posicao[r["ticker"]] = [max(posicao[r["ticker"]][0], 0.0), 0.0]
            linhas.append({"data": dia, "mes": str(pd.Period(dia, "M")), "ticker": r["ticker"],
                           "classe": r["classe"], "modalidade": "comum", "qtd": qv,
                           "preco_venda": float(r["preco"]), "preco_medio": pm,
                           "valor_venda": float(r["valor"]), "custos": float(r["custos"]),
                           "resultado": float(resultado)})
    out = pd.DataFrame(linhas, columns=COLUNAS_REALIZADA)
    return out.sort_values(["data", "ticker", "modalidade"]).reset_index(drop=True)


def posicao_media(operacoes, ate=None):
    """Posicao e preco medio por ticker no compartimento comum (para conferencia)."""
    ops = classificar_day_trade(operacoes)
    if ops.empty:
        return pd.DataFrame(columns=["ticker", "qtd", "custo_total", "preco_medio"])
    ops = ops[ops["modalidade"] == "comum"]
    if ate is not None:
        ops = ops[ops["data"] <= pd.Timestamp(ate)]
    pos = {}
    for _, r in ops.sort_values("data").iterrows():
        q, c = pos.get(r["ticker"], [0.0, 0.0])
        if r["lado"] == "C":
            pos[r["ticker"]] = [q + r["qtd"], c + r["valor"] + r["custos"]]
        else:
            pm = (c / q) if q > 0 else 0.0
            pos[r["ticker"]] = [q - r["qtd"], max(c - pm * r["qtd"], 0.0)]
    linhas = [{"ticker": t, "qtd": q, "custo_total": c, "preco_medio": (c / q) if q > 0 else np.nan}
              for t, (q, c) in sorted(pos.items()) if abs(q) > 1e-9]
    return pd.DataFrame(linhas, columns=["ticker", "qtd", "custo_total", "preco_medio"])


def vencimento_darf(mes):
    """Ultimo dia util do mes seguinte. SUPOSICAO: usa o ultimo pregao como aproximacao."""
    p = pd.Period(str(mes), "M") + 1
    return calendario.ultimo_pregao_do_mes(p.year, p.month)


# ─────────────────────────────────────────────────────────────
# Apuracao mensal
# ─────────────────────────────────────────────────────────────
def apurar(operacoes, vendas_externas=None, ajustes_futuros=None,
           prejuizo_isento_compensa=False, prejuizo_inicial=None, meses=None):
    """Apuracao mes a mes, com compensacao de prejuizo e DARF.

    `vendas_externas`: dict {"AAAA-MM": valor} com vendas de acoes a vista do MESMO CPF
    feitas fora deste sistema. Sem isso o teto de R$20 mil sai subestimado e o imposto
    calculado fica menor que o devido.
    `ajustes_futuros`: DataFrame(data, valor, custos) com o AJUSTE DIARIO dos futuros, que
    e o fato gerador; entra na base comum.
    `prejuizo_inicial`: dict {"comum": x, "day_trade": y} com prejuizo trazido de antes.

    Devolve dict com `mensal` (DataFrame COLUNAS_APURACAO), `realizadas`, `divergencia_
    prejuizo_isento` e `aviso`.
    """
    realizadas = realizar(operacoes)
    ajustes = _ajustes_mensais(ajustes_futuros)
    externas = {str(k): float(v) for k, v in (vendas_externas or {}).items()}
    todos = sorted(set(realizadas["mes"]) | set(ajustes) | set(externas))
    if meses:
        todos = sorted(set(todos) | {str(m) for m in meses})
    if not todos:
        return {"mensal": _vazio(COLUNAS_APURACAO), "realizadas": realizadas,
                "divergencia_prejuizo_isento": 0.0, "aviso": AVISO}
    linhas = _apurar_meses(realizadas, ajustes, externas, todos,
                           prejuizo_isento_compensa, prejuizo_inicial)
    alternativa = _apurar_meses(realizadas, ajustes, externas, todos,
                                not prejuizo_isento_compensa, prejuizo_inicial)
    dif = float(pd.DataFrame(alternativa)["imposto_total"].sum()
                - pd.DataFrame(linhas)["imposto_total"].sum())
    return {"mensal": pd.DataFrame(linhas, columns=COLUNAS_APURACAO),
            "realizadas": realizadas,
            "divergencia_prejuizo_isento": dif,
            "prejuizo_isento_compensa": bool(prejuizo_isento_compensa),
            "aviso": AVISO}


def _ajustes_mensais(ajustes_futuros):
    """DataFrame(data, valor, custos) -> {mes: resultado liquido dos ajustes}."""
    if ajustes_futuros is None or len(ajustes_futuros) == 0:
        return {}
    a = ajustes_futuros.copy()
    a["data"] = pd.to_datetime(a["data"])
    a["valor"] = pd.to_numeric(a["valor"], errors="coerce").fillna(0.0)
    a["custos"] = pd.to_numeric(a.get("custos", 0.0), errors="coerce").fillna(0.0)
    a["mes"] = _mes(a["data"])
    return (a.groupby("mes").apply(lambda g: float(g["valor"].sum() - g["custos"].sum()),
                                   include_groups=False).to_dict())


def _apurar_meses(realizadas, ajustes, externas, meses, prejuizo_isento_compensa, prejuizo_inicial):
    inicial = dict(prejuizo_inicial or {})
    prej = {"comum": float(inicial.get("comum", 0.0)),
            "day_trade": float(inicial.get("day_trade", 0.0))}
    acumulado_darf = 0.0
    linhas = []
    for mes in meses:
        g = realizadas[realizadas["mes"] == mes] if len(realizadas) else realizadas
        comum = g[g["modalidade"] == "comum"] if len(g) else g
        dt = g[g["modalidade"] == "day_trade"] if len(g) else g
        acoes = comum[comum["classe"].isin(CLASSES_ISENTAVEIS)] if len(comum) else comum

        vendas_acoes = float(acoes["valor_venda"].sum()) + externas.get(mes, 0.0)
        vendas_comuns = float(comum["valor_venda"].sum()) if len(comum) else 0.0
        resultado_acoes = float(acoes["resultado"].sum()) if len(acoes) else 0.0
        resultado_comum = float(comum["resultado"].sum()) if len(comum) else 0.0
        resultado_dt = float(dt["resultado"].sum()) if len(dt) else 0.0
        ajuste = float(ajustes.get(mes, 0.0))
        resultado_comum += ajuste

        isento = vendas_acoes <= ISENCAO_VENDAS_MES and vendas_acoes > 0
        if isento:
            # o lucro em acoes sai da base; o prejuizo em acoes so sai se a leitura
            # conservadora estiver ligada (ver o docstring do modulo)
            tira = resultado_acoes if (resultado_acoes > 0 or not prejuizo_isento_compensa) else 0.0
            tributavel = resultado_comum - tira
        else:
            tributavel = resultado_comum

        prej_ant = dict(prej)
        if tributavel > 0:
            usado = min(-prej["comum"], tributavel) if prej["comum"] < 0 else 0.0
            base_comum = tributavel - usado
            prej["comum"] += usado
        else:
            prej["comum"] += tributavel
            base_comum = 0.0

        if resultado_dt > 0:
            usado_dt = min(-prej["day_trade"], resultado_dt) if prej["day_trade"] < 0 else 0.0
            base_dt = resultado_dt - usado_dt
            prej["day_trade"] += usado_dt
        else:
            prej["day_trade"] += resultado_dt
            base_dt = 0.0

        imposto_comum = max(base_comum, 0.0) * ALIQUOTA_COMUM
        imposto_dt = max(base_dt, 0.0) * ALIQUOTA_DAY_TRADE
        irrf_comum = vendas_comuns * IRRF_COMUM
        irrf_dt = max(resultado_dt, 0.0) * IRRF_DAY_TRADE
        imposto_total = imposto_comum + imposto_dt
        darf_bruto = max(imposto_total - irrf_comum - irrf_dt, 0.0)
        total_com_acumulado = darf_bruto + acumulado_darf
        if total_com_acumulado >= DARF_MINIMO:
            darf_devido, a_acumular = total_com_acumulado, 0.0
        else:
            darf_devido, a_acumular = 0.0, total_com_acumulado
        acumulado_darf = a_acumular

        linhas.append({
            "mes": mes, "vendas_acoes": vendas_acoes, "vendas_comuns": vendas_comuns,
            "isento": bool(isento), "resultado_acoes": resultado_acoes,
            "resultado_comum_bruto": resultado_comum,
            "resultado_comum_tributavel": tributavel, "resultado_day_trade": resultado_dt,
            "ajuste_futuros": ajuste,
            "prejuizo_ant_comum": prej_ant["comum"],
            "prejuizo_ant_day_trade": prej_ant["day_trade"],
            "base_comum": max(base_comum, 0.0), "base_day_trade": max(base_dt, 0.0),
            "imposto_comum": imposto_comum, "imposto_day_trade": imposto_dt,
            "imposto_total": imposto_total,
            "irrf_comum": irrf_comum, "irrf_day_trade": irrf_dt,
            "irrf_total": irrf_comum + irrf_dt,
            "darf_bruto": darf_bruto, "darf_acumulado_ant": total_com_acumulado - darf_bruto,
            "darf_devido": darf_devido, "darf_a_acumular": a_acumular,
            "darf_vence": str(vencimento_darf(mes)),
            "prejuizo_comum": prej["comum"], "prejuizo_day_trade": prej["day_trade"],
        })
    return linhas


def isencao_disponivel(apuracao, mes):
    """Quanto ainda cabe no teto de R$20 mil no mes, contando o que ja foi vendido.

    Numero negativo significa que o teto ja estourou e o lucro do mes inteiro em acoes
    esta tributado.
    """
    mensal = apuracao["mensal"] if isinstance(apuracao, dict) else apuracao
    if mensal is None or len(mensal) == 0:
        return ISENCAO_VENDAS_MES
    linha = mensal[mensal["mes"] == str(mes)]
    if linha.empty:
        return ISENCAO_VENDAS_MES
    return float(ISENCAO_VENDAS_MES - linha.iloc[0]["vendas_acoes"])


def proventos_retidos(proventos):
    """Imposto retido na fonte sobre proventos. NAO entra no DARF; e informativo.

    `proventos`: DataFrame(data, ticker, tipo, valor, pagador). JCP paga 15% na fonte;
    dividendo e isento, exceto o IRRF de 10% sobre o que passar de R$50 mil por mes do
    mesmo pagador (Lei 15.270/2025).
    """
    colunas = ["mes", "tipo", "pagador", "valor_bruto", "retido", "valor_liquido"]
    if proventos is None or len(proventos) == 0:
        return _vazio(colunas)
    p = proventos.copy()
    p["data"] = pd.to_datetime(p["data"])
    p["mes"] = _mes(p["data"])
    p["tipo"] = p["tipo"].astype(str).str.strip().str.upper()
    p["valor"] = pd.to_numeric(p["valor"], errors="coerce").fillna(0.0)
    p["pagador"] = p.get("pagador", p["ticker"].astype(str).str[:4])
    linhas = []
    for (mes, tipo, pagador), g in p.groupby(["mes", "tipo", "pagador"], sort=True):
        bruto = float(g["valor"].sum())
        if tipo == "JCP":
            retido = bruto * IR_JCP
        elif tipo in ("DIVIDENDO", "RENDIMENTO"):
            retido = max(bruto - LIMITE_DIVIDENDO_MES, 0.0) * IRRF_DIVIDENDO
        else:
            retido = 0.0
        linhas.append({"mes": mes, "tipo": tipo, "pagador": pagador, "valor_bruto": bruto,
                       "retido": retido, "valor_liquido": bruto - retido})
    return pd.DataFrame(linhas, columns=colunas)


def memoria_calculo(apuracao):
    """A conta linha a linha, para ser conferida por um humano.

    E o entregavel que importa deste modulo: sem memoria de calculo, o numero do DARF e
    um chute com aparencia de certeza.
    """
    colunas = ["mes", "etapa", "descricao", "valor"]
    mensal = apuracao["mensal"] if isinstance(apuracao, dict) else apuracao
    if mensal is None or len(mensal) == 0:
        return _vazio(colunas)
    linhas = []
    for _, r in mensal.iterrows():
        m = r["mes"]
        def add(etapa, desc, valor):
            linhas.append({"mes": m, "etapa": etapa, "descricao": desc, "valor": float(valor)})
        add("1 vendas", "vendas de acoes a vista no mes (CPF)", r["vendas_acoes"])
        add("1 vendas", f"teto da isencao ({ISENCAO_VENDAS_MES:.0f})", ISENCAO_VENDAS_MES)
        add("2 isencao", "isento" if r["isento"] else "tributado", 1.0 if r["isento"] else 0.0)
        add("3 resultado", "resultado em acoes", r["resultado_acoes"])
        add("3 resultado", "ajuste diario de futuros (base comum)", r["ajuste_futuros"])
        add("3 resultado", "resultado comum bruto", r["resultado_comum_bruto"])
        add("3 resultado", "resultado comum tributavel", r["resultado_comum_tributavel"])
        add("3 resultado", "resultado day trade", r["resultado_day_trade"])
        add("4 prejuizo", "prejuizo comum acumulado apos o mes", r["prejuizo_comum"])
        add("4 prejuizo", "prejuizo day trade acumulado apos o mes", r["prejuizo_day_trade"])
        add("5 base", "base comum", r["base_comum"])
        add("5 base", "base day trade", r["base_day_trade"])
        add("6 imposto", f"comum a {ALIQUOTA_COMUM:.0%}", r["imposto_comum"])
        add("6 imposto", f"day trade a {ALIQUOTA_DAY_TRADE:.0%}", r["imposto_day_trade"])
        add("7 irrf", f"IRRF de {IRRF_COMUM:.3%} sobre vendas comuns", r["irrf_comum"])
        add("7 irrf", f"IRRF de {IRRF_DAY_TRADE:.0%} sobre lucro de day trade", r["irrf_day_trade"])
        add("8 darf", f"DARF {CODIGO_DARF} bruto", r["darf_bruto"])
        add("8 darf", f"acumulado de meses abaixo de R${DARF_MINIMO:.0f}", r["darf_acumulado_ant"])
        add("8 darf", "a recolher", r["darf_devido"])
        add("8 darf", "fica acumulado para o mes seguinte", r["darf_a_acumular"])
    return pd.DataFrame(linhas, columns=colunas)


def resumo_mes(apuracao, mes=None):
    """Bloco `fiscal` do painel (ver docs/painel-contrato.md), com tipos JSON nativos."""
    mensal = apuracao["mensal"] if isinstance(apuracao, dict) else apuracao
    vazio = {"mes": str(mes) if mes else None, "vendas_acoes_mes": 0.0,
             "isencao_restante": ISENCAO_VENDAS_MES, "isento": True,
             "lucro_comum": 0.0, "lucro_day_trade": 0.0,
             "prejuizo_acumulado_comum": 0.0, "prejuizo_acumulado_day_trade": 0.0,
             "irrf_retido": 0.0, "darf": 0.0, "darf_vence": None, "darf_acumulado": 0.0,
             "aviso": AVISO}
    if mensal is None or len(mensal) == 0:
        return vazio
    mes = str(mes) if mes else str(mensal["mes"].iloc[-1])
    linha = mensal[mensal["mes"] == mes]
    if linha.empty:
        return vazio
    r = linha.iloc[0]
    def num(x):
        v = float(x)
        return None if not np.isfinite(v) else round(v, 2)
    return {"mes": mes, "vendas_acoes_mes": num(r["vendas_acoes"]),
            "isencao_restante": num(ISENCAO_VENDAS_MES - r["vendas_acoes"]),
            "isento": bool(r["isento"]),
            "lucro_comum": num(r["resultado_comum_tributavel"]),
            "lucro_day_trade": num(r["resultado_day_trade"]),
            "prejuizo_acumulado_comum": num(r["prejuizo_comum"]),
            "prejuizo_acumulado_day_trade": num(r["prejuizo_day_trade"]),
            "irrf_retido": num(r["irrf_total"]), "darf": num(r["darf_devido"]),
            "darf_vence": str(r["darf_vence"]), "darf_acumulado": num(r["darf_a_acumular"]),
            "aviso": AVISO}


# ─────────────────────────────────────────────────────────────
# Disco
# ─────────────────────────────────────────────────────────────
def gravar(apuracao, dir_saida=DIR_SAIDA):
    """Grava apuracao e memoria de calculo. Devolve os caminhos."""
    garantir_dir(dir_saida)
    a = os.path.join(dir_saida, os.path.basename(ARQ_APURACAO))
    m = os.path.join(dir_saida, os.path.basename(ARQ_MEMORIA))
    apuracao["mensal"].to_csv(a, index=False, sep=";", decimal=",")
    memoria_calculo(apuracao).to_csv(m, index=False, sep=";", decimal=",")
    return {"apuracao": a, "memoria": m}


def exportar_revar(apuracao, caminho=ARQ_REVAR):
    """CSV com uma linha por mes para conferir contra o ReVar da Receita/B3.

    O ReVar cruza operacoes informadas pelas corretoras; a conferencia que interessa e se
    o resultado mensal bate. Divergencia aqui e sinal de operacao faltando no livro.
    """
    mensal = apuracao["mensal"] if isinstance(apuracao, dict) else apuracao
    colunas = ["mes", "vendas_acoes", "resultado_comum_tributavel", "resultado_day_trade",
               "imposto_total", "irrf_total", "darf_devido", "codigo_darf", "vencimento"]
    if mensal is None or len(mensal) == 0:
        out = _vazio(colunas)
    else:
        out = mensal[["mes", "vendas_acoes", "resultado_comum_tributavel",
                      "resultado_day_trade", "imposto_total", "irrf_total",
                      "darf_devido"]].copy()
        out["codigo_darf"] = CODIGO_DARF
        out["vencimento"] = mensal["darf_vence"].values
    garantir_dir(os.path.dirname(caminho))
    out.to_csv(caminho, index=False, sep=";", decimal=",")
    return caminho


def main(argv=None):
    ap = argparse.ArgumentParser(description="Apuracao de IR sobre renda variavel (M12)")
    ap.add_argument("--ano", type=int, default=date.today().year)
    ap.add_argument("--externas", default=None, help="CSV mes;valor com vendas de acoes fora daqui")
    args = ap.parse_args(argv)
    from quant.execucao import livro_ordens as lo
    ops = lo.operacoes()
    if ops is None or len(ops) == 0:
        print("sem operacoes no livro; rode python -m quant.rodar_diario --paper primeiro")
        return 2
    externas = {}
    if args.externas and os.path.exists(args.externas):
        ext = pd.read_csv(args.externas, sep=";")
        externas = dict(zip(ext.iloc[:, 0].astype(str), pd.to_numeric(ext.iloc[:, 1])))
    apuracao = apurar(ops, vendas_externas=externas)
    mensal = apuracao["mensal"]
    mensal = mensal[mensal["mes"].str.startswith(str(args.ano))]
    if mensal.empty:
        print(f"nenhum mes apurado em {args.ano}")
        return 1
    print(mensal[["mes", "vendas_acoes", "isento", "resultado_comum_tributavel",
                  "resultado_day_trade", "darf_devido", "darf_vence"]].to_string(index=False))
    caminhos = gravar(apuracao)
    exportar_revar(apuracao)
    print(f"\n{AVISO}")
    if abs(apuracao["divergencia_prejuizo_isento"]) > 0.005:
        print(f"ATENCAO: a leitura alternativa sobre prejuizo em mes isento mudaria o imposto "
              f"em R${apuracao['divergencia_prejuizo_isento']:.2f} no periodo. Leve ao contador.")
    log(f"apuracao em {caminhos['apuracao']}, memoria em {caminhos['memoria']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
