"""
Eventos de QUANTIDADE (bonificacao, desdobramento, grupamento) que a lista da B3 nao traz, completados com a CVM e datados pelo preco.

O DEFEITO (achado em 11/10/2026 pela auditoria da TIR): o indice de retorno total subia menos que o preco ajustado em 41 meses de 15 papeis
(ITUB4, BBDC4, WEGE3, ITSA4, LREN3, CMIG4, SLCE3, ...). Retorno total nunca sobe menos que o preco; quando sobe, falta na tabela de eventos uma
bonificacao ou um desdobramento e o indice "cai" na data-ex como se fosse prejuizo (bonificacao de 10% = -9,1%; desdobramento 1:2 = -50%).
Tres causas, em ordem de tamanho:

  1. A LISTA DA B3 TEM BURACOS. `GetListedSupplementCompany` nao devolve toda bonificacao antiga (Itau: so 4 das ~10 desde 2007; Bradesco: a de 2022 e
     nenhuma entre 2010 e 2021; WEG: 2018 e 2021, nao 2014 e 2015). Nao e truncamento por tamanho: o evento simplesmente nao esta na resposta.
     Aqui entra a segunda fonte, a CVM: FRE item 17.3 (`fre_cia_aberta_capital_social_desdobramento_AAAA.csv`: data da assembleia e quantidade de
     acoes antes e depois) e, para 2024 em diante (o FRE novo nao tem mais esse item), os SALTOS EXATOS do numero de acoes entre dois trimestres
     (`capital_social.parquet`): igual nas classes e numa proporcao redonda (1,10, 1,20, 2:1, 1:10...).
  2. O LEITOR DESCARTAVA O EVENTO DE QUEM RECEBE (corrigido em `eventos.py`): na bonificacao a B3 informa em `assetIssued` a classe das acoes
     NOVAS e em `isinCode` a do titular. CYRE3 (18,96% em 2025), AXIA3 (26,3%), RENT3, BPAC11, SANB3 saiam por isso.
  3. SO CONFERENCIA, NAO CAUSA: o preco do COTAHIST nao traz ajuste (`fatcot` e fator de lote, nao de bonificacao).

COMO UM EVENTO DA CVM VIRA LINHA DA TABELA. A CVM da o que (fator = acoes depois / antes) e quando, em termos de assembleia; nao da a data-ex. A
data-ex vem do PRECO: o dia, na janela, em que o retorno bruto (com o provento em dinheiro do dia e sem a mediana do mercado) multiplicado pelo fator
fica mais perto de 1. Contra os eventos de 7% ou mais que a B3 JA traz (129 casos) esse metodo acerta o dia (a 3 dias) em 89% das vezes (115). Por isso:
  - so entra evento de pelo menos 5% (`K_MIN`): abaixo disso o salto some no ruido do dia e nao ha como datar; o vies de nao aplicar e menor que 5%;
  - o escore do melhor dia (|ln(retorno x fator)|) tem de ser <= 0,06 (<= 0,03 entre 5% e 7%); papel que nao mostra o salto nao recebe o evento
    (classe que nao participou, unit que mudou de composicao);
  - evento que a tabela ja tem (qualquer fonte, fator a 15%, dentro da janela) nao e repetido;
  - o fator gravado e o da CVM, arredondado para a proporcao redonda quando fica a 0,6% dela (1,0957 -> 1,10);
  - a linha leva em `obs` o escore e a margem sobre o 2o melhor dia: margem pequena = data incerta (o retorno acumulado esta certo, o dia pode estar
    algumas semanas fora).
Fonte gravada: `cvm_fre` ou `cvm_capital`; prioridade menor que a B3 em `consolidar`. A rotina diaria (`eventos.carga_em_lote`) chama `completar`
depois de juntar as fontes; `python -m quant.dados.eventos_cvm --gravar` aplica sobre o parquet existente (guardando antes uma copia).
"""
import argparse
import io
import math
import os
import sys
import zipfile

import numpy as np
import pandas as pd

from quant.comum import DIR_BANCO, DIR_BRUTOS, agora_iso, log
from quant.dados import calendario

DIR_FRE = os.path.join(DIR_BRUTOS, "cvm_fre")
TIPOS_QUANTIDADE = ("BONIFICACAO", "DESDOBRAMENTO", "GRUPAMENTO")
TIPOS_DINHEIRO = ("DIVIDENDO", "JCP", "RENDIMENTO")

K_MIN = 1.05                       # eventos menores que isto nao se datam pelo preco (ruido do dia) e nao entram
K_PEQUENO = 1.07                   # entre K_MIN e isto o criterio de escore e mais duro
SCORE_MAX = 0.06                   # evento entre 7% e 50%: o melhor dia pode errar o fator em ate 6% (ruido do dia + provento + mercado)
SCORE_MAX_PEQUENO = 0.03           # evento de 5% a 7%: tem de aparecer limpo
SCORE_MAX_GRANDE = 0.10            # desdobramento, grupamento ou bonificacao de 50% ou mais: um salto desse tamanho nao e ruido
SCORE_MAX_CAPITAL = 0.05           # o salto do numero de acoes so da o trimestre (~110 dias de janela): o preco tem de confirmar, mas o fator ja e exato (0,3%, igual nas classes)
JANELA_FRE = (-5, 330)             # dias a partir da assembleia em que se procura a data-ex
TOLERANCIA_REDONDA = 0.006
MIN_PAPEIS_MERCADO = 10            # papeis com retorno no dia para a mediana do mercado valer
PENALIDADE_ATRASO = 0.02           # preferencia por data perto da assembleia (o ex costuma vir logo depois): 0,02 x ln(1 + dias/10), escolhido numa grade de 3 valores
INFERIR_DESDE = "2023-10-01"       # o FRE novo (2024 em diante) nao tem o item 17.3: a partir daqui o evento vem do salto do numero de acoes
TOLERANCIA_REDONDA_CAPITAL = 0.003 # a classe que fixa a proporcao tem de ficar a 0,3% de um valor redondo
TOLERANCIA_CLASSES = 0.015         # a outra classe (e o total, com tesouraria e emissao pequena) a 1,5% da mesma proporcao
JA_REGISTRADO = 0.15               # fator da tabela a 15% do da CVM, dentro da janela = e o mesmo evento
GRADE = (1.05, 1.10, 1.15, 1.20, 1.25, 1.30, 1.40, 1.50, 1.75, 2.0, 3.0, 4.0, 5.0, 8.0, 10.0, 4 / 3, 5 / 4, 6 / 5, 11 / 10, 3 / 2)
GRADE_REVERSA = (2, 3, 4, 5, 8, 10, 20, 50, 100)


# ─────────────────────────────────────────────────────────────
# Funcoes puras
# ─────────────────────────────────────────────────────────────
def proporcao_redonda(k, tol=TOLERANCIA_REDONDA):
    """k -> o valor redondo mais proximo da grade (bonificacao de 5 a 100%, desdobramento 2:1 a 10:1, grupamento 1:2 a 1:100) se fica a `tol` dele; senao None."""
    if not (k and k > 0 and math.isfinite(k)):
        return None
    candidatos = list(GRADE) + [1.0 / n for n in GRADE_REVERSA]
    melhor = min(candidatos, key=lambda x: abs(math.log(k / x)))
    return melhor if abs(math.log(k / melhor)) <= tol else None


def k_final(k):
    """Fator a gravar: o redondo quando o da CVM fica a 0,6% dele (a CVM soma emissao e cancelamento do mesmo ato: 1,0957 e na verdade 10%); senao o da CVM."""
    r = proporcao_redonda(k)
    return float(r) if r is not None else float(k)


def teto_de_escore(K, fonte="cvm_fre"):
    """Escore maximo (|ln|) aceito para o melhor dia: mais folga para evento grande (nao se confunde com ruido), menos para evento pequeno e para o salto de capital."""
    if fonte == "cvm_capital":
        return SCORE_MAX_CAPITAL
    if abs(math.log(K)) >= math.log(1.5):
        return SCORE_MAX_GRANDE
    return SCORE_MAX_PEQUENO if 1 / K_PEQUENO < K < K_PEQUENO else SCORE_MAX


def tipo_do_evento(k, tipos_fre=""):
    if k < 1:
        return "GRUPAMENTO"
    return "BONIFICACAO" if "onifica" in str(tipos_fre) or k < 1.9 else "DESDOBRAMENTO"


# ─────────────────────────────────────────────────────────────
# Fontes da CVM
# ─────────────────────────────────────────────────────────────
def ler_fre(pasta=DIR_FRE, anos=None):
    """FRE item 17.3 de todos os anos: DataFrame(cnpj, aprov, tipo, antes, depois, versao, ano_arq). Anos sem o arquivo (FRE novo) sao ignorados."""
    linhas = []
    if not os.path.isdir(pasta):
        return pd.DataFrame(columns=["cnpj", "aprov", "tipo", "antes", "depois", "versao", "ano_arq", "nome"])
    for nome in sorted(os.listdir(pasta)):
        if not (nome.startswith("fre_cia_aberta_") and nome.endswith(".zip")):
            continue
        ano = int(nome.split("_")[-1][:4])
        if anos is not None and ano not in anos:
            continue
        with zipfile.ZipFile(os.path.join(pasta, nome)) as z:
            alvo = [n for n in z.namelist() if "capital_social_desdobramento_20" in n and "classe" not in n]
            if not alvo:
                continue
            d = pd.read_csv(io.BytesIO(z.read(alvo[0])), sep=";", encoding="latin1", dtype=str)
        d["ano_arq"] = ano
        linhas.append(d)
    if not linhas:
        return pd.DataFrame(columns=["cnpj", "aprov", "tipo", "antes", "depois", "versao", "ano_arq", "nome"])
    f = pd.concat(linhas, ignore_index=True)
    out = pd.DataFrame({
        "cnpj": f["CNPJ_Companhia"].str.replace(r"\D", "", regex=True),
        "aprov": pd.to_datetime(f["Data_Aprovacao"], errors="coerce"),
        "tipo": f["Tipo_Evento"],
        "antes": pd.to_numeric(f["Quantidade_Total_Acoes_Antes_Aprovacao"], errors="coerce"),
        "depois": pd.to_numeric(f["Quantidade_Total_Acoes_Depois_Aprovacao"], errors="coerce"),
        "versao": pd.to_numeric(f["Versao"], errors="coerce"),
        "ano_arq": f["ano_arq"], "nome": f["Nome_Companhia"]})
    return out


def eventos_fre(fre):
    """FRE bruto -> um evento por (cnpj, data da assembleia): k = acoes depois / antes, com grupamento e desdobramento do mesmo dia compostos (os
    bancos fizeram os dois em 2011 para acabar com fracoes: o produto e 1 e o evento some). Versoes repetidas do FRE: vale a mais nova."""
    if fre is None or not len(fre):
        return pd.DataFrame(columns=["cnpj", "aprov", "K", "tipos", "fonte", "nome"])
    f = fre.dropna(subset=["aprov", "antes", "depois"])
    f = f[(f["antes"] > 0) & (f["depois"] > 0)].copy()
    f["k"] = f["depois"] / f["antes"]
    f = f.sort_values(["cnpj", "aprov", "tipo", "versao", "ano_arq"]).drop_duplicates(["cnpj", "aprov", "tipo"], keep="last")
    g = f.groupby(["cnpj", "aprov"]).agg(K=("k", "prod"), tipos=("tipo", lambda s: "+".join(sorted(set(s)))), nome=("nome", "first")).reset_index()
    g = g[(g["K"] - 1).abs() > 0.02]
    g["fonte"] = "cvm_fre"
    return g


def saltos_de_capital(capital, desde=INFERIR_DESDE):
    """Saltos exatos do numero de acoes entre dois trimestres seguidos de `capital_social.parquet`, de `desde` em diante: proporcao redonda e igual
    nas classes (ON e PN saltam o mesmo %). Devolve DataFrame(cnpj, aprov=ref anterior, ate=ref nova, K, fonte)."""
    cols = ["cnpj", "aprov", "ate", "K", "tipos", "fonte", "nome"]
    if capital is None or not len(capital):
        return pd.DataFrame(columns=cols)
    c = capital.copy()
    c["data_ref"] = pd.to_datetime(c["data_ref"])
    c = c.sort_values(["cd_cvm", "data_ref", "versao"]).drop_duplicates(["cd_cvm", "data_ref"], keep="last")
    linhas = []
    for cd, g in c.groupby("cd_cvm"):
        g = g.sort_values("data_ref")
        tot, on, pn, d = g["acoes_total"].to_numpy(float), g["acoes_on"].to_numpy(float), g["acoes_pn"].to_numpy(float), g["data_ref"].to_numpy()
        cnpj = str(g["cnpj"].iloc[-1])
        for i in range(1, len(g)):
            if pd.Timestamp(d[i]) < pd.Timestamp(desde) or not (tot[i - 1] > 0 and tot[i] > 0):
                continue
            tem_on, tem_pn = on[i - 1] > 0 and on[i] > 0, pn[i - 1] > 0 and pn[i] > 0
            razoes = ([on[i] / on[i - 1]] if tem_on else []) + ([pn[i] / pn[i - 1]] if tem_pn else []) + [tot[i] / tot[i - 1]]
            rk = next((x for x in (proporcao_redonda(r, TOLERANCIA_REDONDA_CAPITAL) for r in razoes) if x is not None), None)
            if rk is None or abs(rk - 1) < 1e-9 or any(abs(r / rk - 1) > TOLERANCIA_CLASSES for r in razoes):
                continue
            linhas.append({"cnpj": "".join(ch for ch in cnpj if ch.isdigit()), "aprov": pd.Timestamp(d[i - 1]), "ate": pd.Timestamp(d[i]), "K": float(rk),
                           "tipos": "salto do numero de acoes", "fonte": "cvm_capital", "nome": ""})
    return pd.DataFrame(linhas, columns=cols)


# ─────────────────────────────────────────────────────────────
# Datacao pelo preco
# ─────────────────────────────────────────────────────────────
class Precos:
    """Razao de preco diaria por ticker (preco por acao do COTAHIST, com os eventos de quantidade que a tabela JA tem), o provento em dinheiro do dia e a
    mediana do mercado. Constroi uma vez e serve a todos os candidatos. O escore de um dia para um fator K e |ln((razao x K + provento/preco anterior)) - mercado|:
    a mesma conta do retorno total, que e o que o evento tem de acertar."""

    def __init__(self, cot, eventos):
        p = pd.DataFrame({"ticker": cot["ticker"].astype(str).str.upper(), "data": pd.to_datetime(cot["data"]), "fec": pd.to_numeric(cot["fec"], errors="coerce")})
        if "fatcot" in cot:
            fat = pd.to_numeric(cot["fatcot"], errors="coerce")
            p["fec"] = p["fec"] / fat.where(fat > 0, 1.0).fillna(1.0).to_numpy()
        p = p[p["fec"] > 0].sort_values(["ticker", "data"]).drop_duplicates(["ticker", "data"], keep="last").reset_index(drop=True)
        p["prev"] = p.groupby("ticker")["fec"].shift(1)
        p["gap"] = p.groupby("ticker")["data"].diff().dt.days
        ev = eventos if eventos is not None and len(eventos) else pd.DataFrame(columns=["ticker", "tipo", "data_ex", "valor", "fator"])
        ev = ev.assign(ticker=ev["ticker"].astype(str).str.upper(), data_ex=pd.to_datetime(ev["data_ex"]))
        din = ev[ev["tipo"].isin(TIPOS_DINHEIRO)].groupby(["ticker", "data_ex"])["valor"].sum().rename("div").reset_index().rename(columns={"data_ex": "data"})
        qtd = ev[ev["tipo"].isin(TIPOS_QUANTIDADE) & (ev["fator"] > 0)].groupby(["ticker", "data_ex"])["fator"].prod().rename("fq").reset_index().rename(columns={"data_ex": "data"})
        p = p.merge(din, on=["ticker", "data"], how="left").merge(qtd, on=["ticker", "data"], how="left")
        p["div"] = pd.to_numeric(p["div"], errors="coerce").fillna(0.0)
        p["fq"] = pd.to_numeric(p["fq"], errors="coerce").fillna(1.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            p["rp"] = p["fec"] * p["fq"] / p["prev"]               # razao de preco, ja com os eventos de quantidade que a tabela tem
            p["rd"] = p["div"] / p["prev"]                         # provento em dinheiro do dia, em fracao do preco anterior
            p["lr"] = np.log(p["rp"] + p["rd"])
        ok = p["gap"].le(5) & p["lr"].between(-0.22, 0.22)
        g = p.loc[ok].groupby("data")["lr"]
        mercado = g.median().where(g.size() >= MIN_PAPEIS_MERCADO)       # com poucos papeis a mediana seria o proprio papel e apagaria o evento
        p["m"] = p["data"].map(mercado).fillna(0.0)
        self.series = {t: (g["data"].to_numpy(), g["rp"].to_numpy(), g["rd"].to_numpy(), g["m"].to_numpy(), g["gap"].to_numpy()) for t, g in p.groupby("ticker")}

    def tem(self, ticker):
        return ticker in self.series

    def datar(self, ticker, aprov, ini, fim, K):
        """(data_ex, escore, margem) do melhor dia entre `ini` e `fim`; None se nao ha dias. escore = |ln(retorno ajustado x K)|; margem = diferenca para o
        melhor outro dia (a 3 ou mais dias dele)."""
        s = self.series.get(ticker)
        if s is None:
            return None
        d, rp, rd, mkt, gap = s
        i0 = int(np.searchsorted(d, np.datetime64(pd.Timestamp(ini))))
        i1 = int(np.searchsorted(d, np.datetime64(pd.Timestamp(fim)), side="right"))
        if i1 - i0 < 3:
            return None
        sl = slice(i0, i1)
        with np.errstate(divide="ignore", invalid="ignore"):
            base = np.abs(np.log(rp[sl] * K + rd[sl]) - mkt[sl])      # (preco x fator + provento) / preco anterior, menos o mercado: perto de 0 no dia do evento
        lag = np.clip((d[sl] - np.datetime64(pd.Timestamp(aprov))).astype("timedelta64[D]").astype(float), 0, None)
        sc = base + PENALIDADE_ATRASO * np.log1p(lag / 10.0)
        invalido = ~np.isfinite(sc) | (gap[sl] > 10)
        sc = np.where(invalido, np.inf, sc)
        if not np.isfinite(sc).any():
            return None
        j = int(np.argmin(sc))
        melhor_dia = d[sl][j]
        longe = np.abs((d[sl] - melhor_dia).astype("timedelta64[D]").astype(float)) >= 3
        outros = sc[longe]
        margem = float(np.min(outros) - sc[j]) if len(outros) and np.isfinite(np.min(outros)) else float("inf")
        return pd.Timestamp(melhor_dia), float(base[j]), margem


# ─────────────────────────────────────────────────────────────
# Completar a tabela
# ─────────────────────────────────────────────────────────────
def _registrado(q_por_ticker, ticker, K, ini, fim):
    q = q_por_ticker.get(ticker)
    if q is None:
        return False
    w = q[(q["data_ex"] >= pd.Timestamp(ini) - pd.Timedelta(days=10)) & (q["data_ex"] <= pd.Timestamp(fim) + pd.Timedelta(days=30))]
    return bool(len(w) and (np.abs(np.log(w["fator"] / K)) <= JA_REGISTRADO).any())


def completar(eventos, cot=None, identidade=None, fre=None, capital=None):
    """Acrescenta a `eventos` (tabela da B3 ja consolidada) os eventos de quantidade da CVM que ela nao tem, datados pelo preco.

    Devolve (novos, diagnostico): `novos` no formato da tabela `eventos` (fonte cvm_fre / cvm_capital); `diagnostico` com TODOS os candidatos e o destino de
    cada um (aplicado, ja_registrado, pequeno, sem_salto_no_preco, sem_ticker)."""
    from quant.dados import cotahist, eventos as ev_mod, identidade as id_mod
    if cot is None:
        cot = cotahist.carregar(2005, pd.Timestamp.now().year, colunas=["data", "ticker", "codbdi", "tpmerc", "fec", "fatcot"])
        cot = cot[(cot["tpmerc"].astype(str).str.strip() == "010") & (cot["codbdi"].astype(str).str.strip().str.zfill(2) == "02")]
    ident = identidade if identidade is not None else id_mod.carregar_identidade()
    fre = eventos_fre(ler_fre() if fre is None else fre)
    if capital is None:
        arq = os.path.join(DIR_BANCO, "capital_social.parquet")
        capital = pd.read_parquet(arq) if os.path.exists(arq) else None
    saltos = saltos_de_capital(capital)
    precos = Precos(cot, eventos)
    ev = eventos if eventos is not None and len(eventos) else ev_mod._tabela_vazia()
    q = ev[ev["tipo"].isin(TIPOS_QUANTIDADE) & (ev["fator"] > 0)].assign(data_ex=lambda x: pd.to_datetime(x["data_ex"]))
    q_por_ticker = {t: g[["data_ex", "fator"]] for t, g in q.groupby("ticker")}
    tickers_do_cnpj = ident.groupby("cnpj")["ticker"].apply(lambda s: sorted(set(s))).to_dict()
    por_raiz = {}
    for t in precos.series:
        por_raiz.setdefault(t[:4], []).append(t)
    for cnpj, ts in list(tickers_do_cnpj.items()):                # a mesma companhia negocia outras classes (KLBN3 e KLBN4 junto de KLBN11) que a identidade nem sempre lista
        tickers_do_cnpj[cnpj] = sorted(set(ts) | {x for t in ts for x in por_raiz.get(t[:4], [])})
    cand = []
    for r in fre.itertuples():
        a = pd.Timestamp(r.aprov)
        cand.append((r.cnpj, a, a + pd.Timedelta(days=JANELA_FRE[0]), a + pd.Timedelta(days=JANELA_FRE[1]), r.K, r.tipos, "cvm_fre", r.nome))
    for r in saltos.itertuples():
        a = pd.Timestamp(r.aprov)
        cand.append((r.cnpj, a, a - pd.Timedelta(days=5), pd.Timestamp(r.ate) + pd.Timedelta(days=20), r.K, r.tipos, "cvm_capital", r.nome))
    novas, diag = [], []
    carimbo = agora_iso()
    for cnpj, aprov, ini, fim, K, tipos, fonte, nome in cand:
        if aprov < pd.Timestamp("2004-06-01"):
            continue
        tks = [t for t in tickers_do_cnpj.get(cnpj, []) if precos.tem(t)]
        if not tks:
            diag.append(dict(cnpj=cnpj, ticker=None, aprov=aprov, K=K, fonte=fonte, destino="sem_ticker"))
            continue
        for t in tks:
            base = dict(cnpj=cnpj, ticker=t, aprov=aprov, K=K, fonte=fonte)
            if abs(math.log(K)) < math.log(K_MIN):
                diag.append(dict(base, destino="pequeno"))
                continue
            if K < 1 and proporcao_redonda(K) is None:               # reducao de acoes que nao e grupamento (cancelamento de tesouraria: Ambev 2013, Assai 2020): o preco nao muda
                diag.append(dict(base, destino="reducao_nao_e_grupamento"))
                continue
            if _registrado(q_por_ticker, t, K, ini, fim):
                diag.append(dict(base, destino="ja_registrado"))
                continue
            if fonte == "cvm_capital" and any(abs(math.log(K / x.K)) <= 0.02 and x.cnpj == cnpj and abs((x.aprov - aprov).days) <= 400 for x in fre.itertuples()):
                diag.append(dict(base, destino="ja_na_cvm_fre"))
                continue
            m = precos.datar(t, aprov, ini, fim, K)
            if m is None:
                diag.append(dict(base, destino="sem_preco"))
                continue
            dia, score, margem = m
            teto = teto_de_escore(K, fonte)
            if score > teto:
                diag.append(dict(base, destino="sem_salto_no_preco", data_ex=dia, escore=score, margem=margem))
                continue
            kf = k_final(K)
            incerta = margem < 0.01
            novas.append({"ticker": t, "tipo": tipo_do_evento(kf, tipos), "data_com": pd.Timestamp(calendario.pregao_anterior(dia.date())), "data_ex": dia, "valor": float("nan"),
                          "fator": kf, "data_aprov": aprov, "fonte": fonte, "carimbo": carimbo,
                          "obs": f"{'FRE item 17.3' if fonte == 'cvm_fre' else 'salto do numero de acoes'}; k da CVM {K:.4f}; data-ex pelo preco: "
                                 f"escore {score:.3f}, margem {margem:.3f}{' (DATA INCERTA)' if incerta else ''}"})
            diag.append(dict(base, destino="aplicado", data_ex=dia, escore=score, margem=margem, fator=kf, incerta=incerta))
    novos = pd.DataFrame(novas, columns=ev_mod.COLUNAS)
    if len(novos):
        novos = ev_mod._montar(novos.to_dict("records"))
    return novos, pd.DataFrame(diag)


def completar_tabela(eventos, **kw):
    """`eventos` + os que `completar` achou, consolidados sem duplicar. Devolve (tabela, diagnostico)."""
    from quant.dados import eventos as ev_mod
    novos, diag = completar(eventos, **kw)
    if not len(novos):
        return eventos, diag
    return ev_mod.consolidar(eventos, novos), diag


def main(argv=None):
    ap = argparse.ArgumentParser(description="Completa banco/eventos.parquet com bonificacoes, desdobramentos e grupamentos da CVM")
    ap.add_argument("--gravar", action="store_true", help="grava o parquet corrigido; antes guarda a copia eventos_antes_cvm_AAAAMMDD.parquet ao lado (nunca sobrescreve copia)")
    a = ap.parse_args(argv)
    from quant.dados import eventos as ev_mod
    ev = ev_mod.carregar_eventos()
    nova, diag = completar_tabela(ev)
    log(f"eventos da CVM: {diag['destino'].value_counts().to_dict() if len(diag) else {}}; {len(nova) - len(ev)} linha(s) nova(s)")
    if a.gravar and len(nova) > len(ev):
        copia = os.path.join(DIR_BANCO, f"eventos_antes_cvm_{pd.Timestamp.now():%Y%m%d}.parquet")
        if not os.path.exists(copia):
            ev.to_parquet(copia, index=False)
            log(f"copia do parquet antigo: {copia}")
        ev_mod.gravar_eventos(nova)
        log("banco/eventos.parquet gravado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
