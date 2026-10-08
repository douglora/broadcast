"""
Painel POINT-IN-TIME de fundamentos (pre-requisito do M8): uma linha por (data de
decisao, empresa) com o TTM e as metricas como eram conhecidos naquela data.

Por que existe: `cvm_fundamentos.ttm()` responde por (empresa, data) e custa ~60 ms.
O backtest precisa de ~200 empresas x ~186 meses = 37 mil respostas por passada, ou
seja mais de meia hora de CPU cada vez que alguem mexe num peso. Este modulo calcula
o mesmo conteudo uma vez e grava em parquet; o backtest passa a ler o painel.

A IDEIA (e por que ela e exatamente equivalente ao laco ingenuo):
  `ttm(df, cd_cvm, t)` e uma FUNCAO ESCADA em t. O unico jeito de a resposta mudar e
  chegar documento novo, e `visao_em` so enxerga documento com `dt_receb <= t`. Entao,
  entre dois `dt_receb` consecutivos da empresa, a resposta e constante. Basta calcular
  nas datas de chegada de documento ("vintages") - umas 70 em 15 anos, contra 186 meses -
  e propagar para frente ate a proxima chegada. Nao ha aproximacao nenhuma: o resultado
  e identico ao de chamar `ttm()` em cada mes, e `test_painel_fundamentos` prova isso
  campo a campo, incluindo os casos que devolvem None e as reapresentacoes.

O QUE NAO FOI FEITO, DE PROPOSITO:
  Havia a alternativa de vetorizar tudo - mapear contas em uma passada, trimestralizar
  para todos os pares de versoes de uma vez e resolver a visao por `drop_duplicates`
  ordenado. Seria mais rapido, e seria o codigo mais sutil desta fase: reapresentacao
  cruzando com a diferenca de acumulados (Q2 = 6m - 3m usa DOIS documentos, cada um com
  sua propria trilha de versoes) e exatamente onde um vazamento point-in-time silencioso
  moraria. Como o painel e gravado em cache e o custo e pago uma vez por atualizacao de
  dados, a troca "menos velocidade por muito menos risco" e obviamente boa aqui. O
  ganho de velocidade vem de duas coisas seguras: fatiar por empresa antes do laco (a
  varredura `df[df.cd_cvm == x]` sobre a tabela inteira era boa parte dos 60 ms) e nao
  repetir data que nao muda resposta.

Suposicoes (validar quando houver rede):
  - `dt_receb <= t` e INCLUSIVO em `visao_em`. Quem decide no fechamento de t tem de
    passar t = pregao anterior; este modulo NAO desloca (quem desloca e `sinais.painel`),
    mas `painel_ttm` aceita `deslocar=True` para fazer o servico.
  - Metricas de valor (bm, ev_ebit, fcf_yield, earnings_yield) exigem valor de mercado,
    que exige numero de acoes - ver `quant.dados.capital_social`. Sem ele as quatro
    colunas ficam NaN e `cobertura_valor` no resumo diz em que fracao do painel isso
    aconteceu. O sinal de valor pesa 25% do score: essa cobertura precisa ser olhada.
  - `financeiras` (conjunto de cd_cvm) vem de `quant.dados.setores`; sem ele nenhuma
    empresa e tratada como banco e o portao "DL/EBITDA <= 3 ex-financeiras" passa a
    valer para bancos, o que nao faz sentido.

Uso:
    python -m quant.dados.painel_fundamentos --anos 2010-2026 --ini 2011 --fim 2026
"""
import argparse
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

from quant.comum import DIR_BANCO, garantir_dir, log
from quant.dados import calendario, contas_cvm, cvm_fundamentos as cf

ARQ_PARQUET = os.path.join(DIR_BANCO, "painel_fundamentos.parquet")

# Campos que vem direto de ttm() (fluxos, estoques e derivados) e de metricas().
CAMPOS_TTM = (list(cf.FLUXOS_TTM) + ["ebitda", "fcf", "receita_anterior"]
              + list(cf.ESTOQUES_TTM) + ["divida_bruta", "divida_liquida"])
CAMPOS_METRICAS = ["roic", "roe", "margem_bruta", "margem_ebit", "gpoa", "dl_ebitda",
                   "crescimento_receita", "fcf_yield", "earnings_yield",
                   "bm", "ev_ebit", "retorno_capital"]
COLUNAS = (["data", "cd_cvm", "escopo", "vintage", "dt_refer", "dt_receb", "dt_balanco",
            "financeira", "valor_mercado"] + CAMPOS_TTM + CAMPOS_METRICAS)


# ─────────────────────────────────────────────────────────────
# Utilitarios puros
# ─────────────────────────────────────────────────────────────
def _ts(d):
    return pd.Timestamp(d)


def vintages(df, cd_cvm=None):
    """Datas em que a resposta de ttm() pode mudar: os dt_receb distintos da empresa.

    Devolve {cd_cvm: [Timestamp, ...]} ordenado. Linhas sem dt_receb nao entram (nunca
    entram na visao tambem). Empresa sem nenhum dt_receb sai do dicionario.
    """
    if df is None or len(df) == 0:
        return {}
    d = df[df["dt_receb"].notna()]
    if cd_cvm is not None:
        alvos = {int(x) for x in np.atleast_1d(cd_cvm)}
        d = d[d["cd_cvm"].isin(alvos)]
    if d.empty:
        return {}
    out = {}
    for cod, sub in d.groupby("cd_cvm", sort=True):
        datas = sorted(pd.to_datetime(sub["dt_receb"].unique()))
        if datas:
            out[int(cod)] = datas
    return out


def _linha_vazia():
    linha = {c: float("nan") for c in CAMPOS_TTM + CAMPOS_METRICAS}
    linha.update({"escopo": None, "dt_refer": None, "dt_receb": None, "dt_balanco": None,
                  "financeira": False, "valor_mercado": float("nan")})
    return linha


def painel_vintages(df, cd_cvms=None, financeiras=None, limite_vintages=None):
    """Uma linha por (cd_cvm, vintage) com o conteudo de ttm() naquela data.

    Fatia a tabela por empresa antes do laco (a varredura sobre a tabela inteira dominava
    o custo de ttm()). Vintages em que ttm() devolve None viram linha com NaN: e
    informacao - diz que naquele momento a empresa nao tinha 4 trimestres consecutivos.
    `financeiras`: conjunto de cd_cvm tratados como banco/seguradora.
    """
    colunas = ["cd_cvm", "vintage"] + [c for c in COLUNAS if c not in ("data", "cd_cvm", "vintage")]
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=colunas)
    fin = {int(x) for x in (financeiras or set())}
    mapa = vintages(df, cd_cvms)
    if not mapa:
        return pd.DataFrame(columns=colunas)
    linhas = []
    for cod, datas in mapa.items():
        fatia = df[df["cd_cvm"] == cod]
        if limite_vintages:
            datas = datas[-int(limite_vintages):]
        for v in datas:
            x = cf.ttm(fatia, cod, v)
            linha = _linha_vazia()
            linha["cd_cvm"] = int(cod)
            linha["vintage"] = v
            linha["financeira"] = cod in fin
            if x is not None:
                for c in CAMPOS_TTM:
                    linha[c] = x.get(c, float("nan"))
                linha["escopo"] = x["escopo"]
                linha["dt_refer"] = x["dt_refer"]
                linha["dt_receb"] = x["dt_receb"]
                linha["dt_balanco"] = x["dt_balanco"]
            linhas.append(linha)
    out = pd.DataFrame(linhas)
    for c in ("dt_refer", "dt_receb", "dt_balanco"):
        out[c] = pd.to_datetime(out[c], errors="coerce")
    out["vintage"] = pd.to_datetime(out["vintage"])
    return out[colunas].sort_values(["cd_cvm", "vintage"]).reset_index(drop=True)


def resolver(painel_vint, datas):
    """Propaga o painel de vintages para as datas de decisao (ultimo vintage <= data).

    Uma linha por (data, cd_cvm) para cada empresa que ja tinha algum documento na data.
    Empresa sem vintage <= data simplesmente nao aparece naquela data.
    """
    colunas = ["data", "cd_cvm"] + [c for c in COLUNAS if c not in ("data", "cd_cvm")]
    if painel_vint is None or len(painel_vint) == 0 or datas is None or len(datas) == 0:
        return pd.DataFrame(columns=colunas)
    alvo = pd.DataFrame({"data": sorted({_ts(d) for d in datas})})
    partes = []
    for cod, sub in painel_vint.groupby("cd_cvm", sort=True):
        sub = sub.sort_values("vintage")
        junta = pd.merge_asof(alvo, sub, left_on="data", right_on="vintage",
                              direction="backward", allow_exact_matches=True)
        junta = junta[junta["vintage"].notna()].copy()
        if junta.empty:
            continue
        junta["cd_cvm"] = int(cod)
        partes.append(junta)
    if not partes:
        return pd.DataFrame(columns=colunas)
    out = pd.concat(partes, ignore_index=True)
    out["financeira"] = out["financeira"].map(lambda x: bool(x) if x == x and x is not None else False)
    return out[colunas].sort_values(["data", "cd_cvm"]).reset_index(drop=True)


def acrescentar_metricas(painel, valor_mercado=None):
    """Calcula as metricas linha a linha reusando cvm_fundamentos.metricas.

    `valor_mercado`: DataFrame(data, cd_cvm, valor_mercado) ou None. Sem ele, bm,
    ev_ebit, fcf_yield e earnings_yield ficam NaN.
    `retorno_capital` = ROE se financeira, senao ROIC: e uma coluna so, para a mediana
    do cross-section ser tomada sobre uma populacao unica (a especificacao dizia
    "ROIC (ou ROE em financeiras) >= mediana" sem dizer de qual populacao).
    """
    if painel is None or len(painel) == 0:
        return pd.DataFrame(columns=COLUNAS)
    p = painel.copy()
    p["cd_cvm"] = pd.to_numeric(p["cd_cvm"], errors="coerce").astype("int64")
    if valor_mercado is not None and len(valor_mercado) > 0:
        vm = valor_mercado[["data", "cd_cvm", "valor_mercado"]].copy()
        vm["data"] = pd.to_datetime(vm["data"])
        vm["cd_cvm"] = pd.to_numeric(vm["cd_cvm"], errors="coerce").astype("int64")
        vm = vm.drop_duplicates(["data", "cd_cvm"], keep="last")
        p = p.drop(columns=["valor_mercado"]).merge(vm, on=["data", "cd_cvm"], how="left")
    linhas = []
    for r in p.to_dict("records"):
        vm_i = r.get("valor_mercado")
        vm_i = None if vm_i is None or (isinstance(vm_i, float) and np.isnan(vm_i)) else float(vm_i)
        if r.get("dt_refer") is None or pd.isna(r.get("dt_refer")):
            linhas.append({c: float("nan") for c in CAMPOS_METRICAS})
            continue
        base = {c: r.get(c, float("nan")) for c in CAMPOS_TTM}
        base["dt_refer"] = r.get("dt_refer")
        base["dt_receb"] = r.get("dt_receb")
        m = cf.metricas(base, valor_mercado=vm_i, financeira=bool(r.get("financeira")))
        linha = {c: m.get(c, float("nan")) for c in CAMPOS_METRICAS if c in m}
        linha["retorno_capital"] = m["roe"] if r.get("financeira") else m["roic"]
        pl = base.get("pl", float("nan"))
        dl = base.get("divida_liquida", float("nan"))
        ebit = base.get("ebit", float("nan"))
        linha["bm"] = cf._div(pl, vm_i, positivo=True) if vm_i is not None else float("nan")
        ev = (vm_i + dl) if (vm_i is not None and not np.isnan(dl)) else float("nan")
        linha["ev_ebit"] = cf._div(ebit, ev, positivo=True)
        linhas.append(linha)
    met = pd.DataFrame(linhas, index=p.index)
    for c in CAMPOS_METRICAS:
        p[c] = met[c] if c in met else float("nan")
    return p[COLUNAS].reset_index(drop=True)


def painel_ttm(df, datas, cd_cvms=None, financeiras=None, valor_mercado=None, deslocar=False):
    """Composicao completa: vintages -> propagacao -> metricas.

    `deslocar=True` resolve o painel na VESPERA de cada data de decisao (e o que evita o
    look-ahead intradiario, ja que `visao_em` e inclusivo em t) mas devolve a linha
    CARIMBADA COM A DATA DE DECISAO. O contrato e "o que se sabia para decidir em d";
    devolver a data deslocada faria a juncao por data falhar em silencio no chamador.
    """
    vint = painel_vintages(df, cd_cvms=cd_cvms, financeiras=financeiras)
    if datas is None:
        return acrescentar_metricas(resolver(vint, datas), valor_mercado=valor_mercado)
    originais = sorted({_ts(d) for d in datas})
    usadas = [_ts(calendario.pregao_anterior(d)) if deslocar else _ts(d) for d in originais]
    base = resolver(vint, usadas)
    if deslocar and len(base):
        de_para = dict(zip(usadas, originais))
        base["data"] = base["data"].map(de_para)
        base = base[base["data"].notna()].sort_values(["data", "cd_cvm"]).reset_index(drop=True)
    return acrescentar_metricas(base, valor_mercado=valor_mercado)


def cobertura(painel):
    """Fracao das linhas com cada bloco de informacao. E o numero que diz se o sinal de
    valor pode ser usado: com pouca cobertura de valor_mercado ele nao existe."""
    if painel is None or len(painel) == 0:
        return {"linhas": 0, "ttm": 0.0, "valor_mercado": 0.0, "roic_ou_roe": 0.0,
                "dl_ebitda": 0.0, "crescimento": 0.0, "lpa": 0.0}
    n = float(len(painel))
    return {
        "linhas": int(n),
        "ttm": float(painel["receita"].notna().sum() / n),
        "valor_mercado": float(painel["valor_mercado"].notna().sum() / n),
        "roic_ou_roe": float(painel["retorno_capital"].notna().sum() / n),
        "dl_ebitda": float(painel["dl_ebitda"].notna().sum() / n),
        "crescimento": float(painel["crescimento_receita"].notna().sum() / n),
        "lpa": float((painel["lpa"].notna() & (painel["lpa"] != 0)).sum() / n),
    }


# ─────────────────────────────────────────────────────────────
# Banco
# ─────────────────────────────────────────────────────────────
def gravar(painel, caminho=ARQ_PARQUET):
    garantir_dir(os.path.dirname(caminho))
    painel[COLUNAS].to_parquet(caminho, index=False)
    return caminho


def carregar(caminho=ARQ_PARQUET):
    if not os.path.exists(caminho):
        return pd.DataFrame(columns=COLUNAS)
    return pd.read_parquet(caminho)


def datas_mensais(ini, fim):
    """Ultimo pregao de cada mes entre ini e fim (anos inteiros)."""
    out = []
    for ano in range(int(ini), int(fim) + 1):
        for mes in range(1, 13):
            d = calendario.ultimo_pregao_do_mes(ano, mes)
            if d is not None:
                out.append(pd.Timestamp(d))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Monta o painel point-in-time de fundamentos")
    ap.add_argument("--anos", default="2010-2026", help="anos de DFP/ITR a carregar")
    ap.add_argument("--ini", type=int, default=2011, help="primeiro ano de datas de decisao")
    ap.add_argument("--fim", type=int, default=date.today().year)
    args = ap.parse_args(argv)
    a, b = (args.anos.split("-") + [args.anos])[:2]
    df = cf.carregar(range(int(a), int(b) + 1))
    if df is None or len(df) == 0:
        print("sem fundamentos no banco; rode python -m quant.dados.cvm_fundamentos --anos ...")
        return 2
    fin = None
    try:
        from quant.dados import identidade, setores
        ident = identidade.carregar_identidade()
        if ident is not None:
            fin = setores.financeiras(setores.mapa_setores(identidade=ident), ident)
    except Exception as e:                                      # setor e opcional aqui
        log(f"sem mapa de setores ({e}); nenhuma empresa marcada como financeira")
    datas = datas_mensais(args.ini, args.fim)
    log(f"painel: {df['cd_cvm'].nunique()} empresas, {len(datas)} datas de decisao")
    painel = painel_ttm(df, datas, financeiras=fin, deslocar=True)
    gravar(painel)
    cob = cobertura(painel)
    log(f"gravado {ARQ_PARQUET}: {cob['linhas']} linhas")
    for k, v in cob.items():
        if k != "linhas":
            log(f"  cobertura {k}: {v:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
