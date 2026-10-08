"""
Demonstracoes financeiras POINT-IN-TIME da CVM (M5): DFP anual (desde 2010) e ITR
trimestral (desde ~2011), no formato longo "uma linha por conta".

Por que existe: todo backtest de fundamentos que usa o balanco "como esta hoje" sofre
de look-ahead - reapresentacoes, correcoes e o proprio atraso de entrega (a DFP de
dezembro sai em marco/abril) mudam o numero que estava disponivel no dia. A CVM
publica, junto com cada documento, a data em que o RECEBEU (DT_RECEB) e a VERSAO;
guardamos as duas e so deixamos usar uma linha quando dt_receb <= t (visao_em).

Fonte: https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{DFP|ITR}/DADOS/{dfp|itr}_cia_aberta_{ano}.zip
Dentro do zip: {tipo}_cia_aberta_{ano}.csv (indice: CNPJ_CIA, DT_REFER, VERSAO, DENOM_CIA,
CD_CVM, CATEG_DOC, ID_DOC, DT_RECEB, LINK_DOC) e um CSV por demonstracao e escopo,
{tipo}_cia_aberta_{BPA|BPP|DRE|DFC_MD|DFC_MI|DMPL|DVA}_{con|ind}_{ano}.csv, com CNPJ_CIA,
DT_REFER, VERSAO, DENOM_CIA, CD_CVM, GRUPO_DFP, MOEDA, ESCALA_MOEDA, ORDEM_EXERC,
[DT_INI_EXERC,] DT_FIM_EXERC, CD_CONTA, DS_CONTA, VL_CONTA, ST_CONTA_FIXA. CSV ';' latin-1.

Armadilhas:
  - ESCALA_MOEDA 'MIL' e o normal: multiplicamos por 1000 e guardamos tudo em reais.
  - DRE e DFC do ITR sao ACUMULADOS no ano (DT_INI_EXERC = inicio do exercicio). O valor
    do trimestre e obtido por diferenca (trimestralizar): Q2 = 6m - Q1, Q3 = 9m - 6m e
    Q4 = DFP anual - 9m. Q4 so existe depois que a DFP foi recebida.
  - ORDEM_EXERC 'PENULTIMO' e o comparativo do ano anterior, ja reapresentado; fica na
    tabela mas nunca entra em ttm() - usar o comparativo seria olhar o futuro.
  - O ITR real traz, alem da linha acumulada (DT_INI_EXERC = inicio do exercicio), a
    linha do TRIMESTRE ISOLADO (DT_INI_EXERC = inicio do trimestre, ex. 01/04-30/06).
    trimestralizar() usa SO a acumulada (menor DT_INI por conta e DT_FIM); sem isso a
    isolada vira um "Q1" espurio e capex/D&A (somas por descricao) contam em dobro.
  - Uma reapresentacao gera VERSAO 2 com DT_RECEB posterior; visao_em(t) escolhe a
    maior versao recebida ate t, por (cd_cvm, tipo, dt_refer). dt_receb <= t e
    INCLUSIVO: um documento recebido no dia t conta como conhecido em t. Quem decide
    carteira no fechamento de t deve chamar com t = pregao anterior (a CVM recebe
    documentos ate depois do fechamento) - o modulo nao faz esse deslocamento.
  - LPA ('3.99*') vem em reais por acao e NAO recebe ESCALA_MOEDA (CONTAS_SEM_ESCALA);
    todo o resto do documento e multiplicado por 1000 quando a escala e MIL.
  - Sem DT_RECEB no indice a linha e descartada da visao (nao da para provar quando
    ficou disponivel).
  - Escopo: consolidado ('con') quando a empresa entrega; senao individual ('ind').
  - O zip anual de referencia X contem TODAS as versoes de documentos com DT_REFER em X,
    inclusive as recebidas em X+1 ou X+2, por isso particionamos o parquet por ano de
    DT_REFER e sempre reprocessamos o ano inteiro.

Uso: python -m quant.dados.cvm_fundamentos --anos 2010-2026
"""
import argparse
import io
import os
import re
import sys
import zipfile
from datetime import date

import numpy as np
import pandas as pd

from quant.comum import DIR_BANCO, DIR_BRUTOS, garantir_dir, gravar_atomico, http_get, log
from quant.dados.arquivar_b3 import ler_csv_b3, numero_br
from quant.dados import contas_cvm

URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{TIPO}/DADOS/{tipo}_cia_aberta_{ano}.zip"
DIR_CVM = os.path.join(DIR_BRUTOS, "cvm")
DIR_PARQUET = os.path.join(DIR_BANCO, "fundamentos_pit")

TIPOS = ("DFP", "ITR")
DEMOS = ("BPA", "BPP", "DRE", "DFC_MD", "DFC_MI")      # DMPL/DVA tem outro layout: fora por enquanto
DEMOS_BALANCO = ("BPA", "BPP")
DEMOS_FLUXO = ("DRE", "DFC_MD", "DFC_MI")
ESCALAS = {"MIL": 1000.0, "UNIDADE": 1.0, "MILHAO": 1e6}
CONTAS_SEM_ESCALA = ("3.99",)      # prefixos de CD_CONTA em reais por acao (LPA): escala nao se aplica

COLUNAS = ["cd_cvm", "cnpj", "tipo", "dt_refer", "dt_receb", "versao", "demo", "escopo", "conta",
           "descricao", "valor_reais", "dt_ini", "dt_fim", "ordem_exerc", "meses"]
COLUNAS_INDICE = ["CNPJ_CIA", "DT_REFER", "VERSAO", "DENOM_CIA", "CD_CVM", "CATEG_DOC", "ID_DOC",
                  "DT_RECEB", "LINK_DOC"]
COLUNAS_DEMO = ["CNPJ_CIA", "DT_REFER", "VERSAO", "DENOM_CIA", "CD_CVM", "GRUPO_DFP", "MOEDA",
                "ESCALA_MOEDA", "ORDEM_EXERC", "DT_INI_EXERC", "DT_FIM_EXERC", "CD_CONTA",
                "DS_CONTA", "VL_CONTA", "ST_CONTA_FIXA"]

_NOME_CSV = re.compile(r"^(dfp|itr)_cia_aberta_(?:([A-Za-z_]+)_(con|ind)_)?(\d{4})\.csv$", re.IGNORECASE)

FLUXOS_TTM = ("receita", "lucro_bruto", "ebit", "resultado_financeiro", "lucro_liquido", "fco", "fci",
              "capex", "depreciacao", "lpa")
ESTOQUES_TTM = ("ativo", "ativo_circulante", "passivo_circulante", "caixa", "emprestimos_cp",
                "emprestimos_lp", "pl")


# ─────────────────────────────────────────────────────────────
# Parsers puros (testaveis sem rede)
# ─────────────────────────────────────────────────────────────
def _data(serie):
    """DT_* vem em ISO (2023-12-31) nos dados abertos; aceita tambem dd/mm/aaaa."""
    s = serie.astype(str).str.strip().str[:10]
    d = pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")
    faltando = d.isna() & (s != "")
    if faltando.any():
        d[faltando] = pd.to_datetime(s[faltando], format="%d/%m/%Y", errors="coerce")
    return d


def _valor(s):
    """VL_CONTA: '1234567.00' (ponto decimal, sem milhar) ou '1.234.567,00'. Nunca trata
    um ponto isolado como milhar - '1.234' aqui e 1,234 (LPA), nao 1234."""
    s = "" if s is None else str(s).strip()
    if not s:
        return float("nan")
    if "," in s:
        return numero_br(s)
    try:
        return float(s)
    except ValueError:
        return numero_br(s)      # '1.234.567' (grupos de 3 sem virgula) -> 1234567; lixo -> NaN


def _meses(dt_ini, dt_fim):
    m = (dt_fim.dt.year - dt_ini.dt.year) * 12 + (dt_fim.dt.month - dt_ini.dt.month) + 1
    return m.astype("Int64")


def _vazio(colunas=COLUNAS):
    """DataFrame vazio com os dtypes de COLUNAS (para concat/parquet nao virarem object)."""
    tipos = {"cd_cvm": "int64", "cnpj": "object", "tipo": "object", "dt_refer": "datetime64[ns]",
             "dt_receb": "datetime64[ns]", "versao": "int64", "demo": "object", "escopo": "object",
             "conta": "object", "descricao": "object", "valor_reais": "float64",
             "dt_ini": "datetime64[ns]", "dt_fim": "datetime64[ns]", "ordem_exerc": "object", "meses": "Int64"}
    return pd.DataFrame({c: pd.Series(dtype=tipos[c]) for c in colunas})


def parse_indice(conteudo):
    """CSV indice do zip -> DataFrame (cd_cvm, cnpj, dt_refer, versao, dt_receb, denom, categ)."""
    df = ler_csv_b3(conteudo)
    if df.empty or "DT_RECEB" not in df.columns:
        return pd.DataFrame(columns=["cd_cvm", "cnpj", "dt_refer", "versao", "dt_receb", "denom", "categ"])
    out = pd.DataFrame({
        "cd_cvm": pd.to_numeric(df["CD_CVM"], errors="coerce").astype("Int64"),
        "cnpj": df["CNPJ_CIA"].astype(str).str.strip(),
        "dt_refer": _data(df["DT_REFER"]),
        "versao": pd.to_numeric(df["VERSAO"], errors="coerce").astype("Int64"),
        "dt_receb": _data(df["DT_RECEB"]),
        "denom": df.get("DENOM_CIA", pd.Series([""] * len(df))).astype(str).str.strip(),
        "categ": df.get("CATEG_DOC", pd.Series([""] * len(df))).astype(str).str.strip(),
    })
    out = out.dropna(subset=["cd_cvm", "dt_refer", "versao"])
    # o mesmo (empresa, referencia, versao) nao deveria repetir; se repetir fica o MAIOR dt_receb
    # (conservador: so consideramos o documento conhecido quando a ultima entrega chegou)
    out = out.sort_values("dt_receb", na_position="first")
    return out.drop_duplicates(["cd_cvm", "dt_refer", "versao"], keep="last")


def parse_demo(conteudo, tipo, demo, escopo):
    """CSV de uma demonstracao/escopo -> DataFrame longo (sem dt_receb; vem do indice)."""
    df = ler_csv_b3(conteudo)
    if df.empty or "CD_CONTA" not in df.columns:
        return _vazio([c for c in COLUNAS if c != "dt_receb"])
    escala = df["ESCALA_MOEDA"].map(contas_cvm.normalizar_texto).str.upper().map(ESCALAS) \
        if "ESCALA_MOEDA" in df.columns else pd.Series(1.0, index=df.index)
    if escala.isna().any():
        desconhecidas = sorted(set(df.loc[escala.isna(), "ESCALA_MOEDA"]))
        log(f"cvm {tipo} {demo}/{escopo}: ESCALA_MOEDA desconhecida {desconhecidas}; assumindo UNIDADE")
        escala = escala.fillna(1.0)
    conta = df["CD_CONTA"].astype(str).str.strip()
    sem_escala = conta.map(lambda c: any(c == p or c.startswith(p + ".") for p in CONTAS_SEM_ESCALA))
    escala = escala.where(~sem_escala, 1.0)
    dt_fim = _data(df["DT_FIM_EXERC"])
    if "DT_INI_EXERC" in df.columns and demo in DEMOS_FLUXO:
        dt_ini = _data(df["DT_INI_EXERC"])
    elif demo in DEMOS_FLUXO:
        # DFP sem DT_INI_EXERC: exercicio de 12 meses terminando em DT_FIM_EXERC
        dt_ini = (dt_fim - pd.DateOffset(years=1) + pd.DateOffset(days=1))
    else:
        dt_ini = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    out = pd.DataFrame({
        "cd_cvm": pd.to_numeric(df["CD_CVM"], errors="coerce").astype("Int64"),
        "cnpj": df["CNPJ_CIA"].astype(str).str.strip(),
        "tipo": tipo.upper(),
        "dt_refer": _data(df["DT_REFER"]),
        "versao": pd.to_numeric(df["VERSAO"], errors="coerce").astype("Int64"),
        "demo": demo.upper(),
        "escopo": escopo.lower(),
        "conta": conta,
        "descricao": df["DS_CONTA"].astype(str).str.strip(),
        "valor_reais": df["VL_CONTA"].map(_valor) * escala,
        "dt_ini": dt_ini,
        "dt_fim": dt_fim,
        "ordem_exerc": df["ORDEM_EXERC"].map(contas_cvm.normalizar_texto).str.upper()
        if "ORDEM_EXERC" in df.columns else "ULTIMO",
    })
    out["meses"] = _meses(out["dt_ini"], out["dt_fim"]) if demo in DEMOS_FLUXO else pd.Series(pd.NA, index=out.index, dtype="Int64")
    return out.dropna(subset=["cd_cvm", "dt_refer", "versao"])


def parse_zip(conteudo, tipo, demos=DEMOS):
    """Bytes do zip anual -> DataFrame longo fundamentos (COLUNAS), com dt_receb do indice.

    Linhas sem documento correspondente no indice ficam com dt_receb NaT (e sao
    descartadas por visao_em). Devolve DataFrame vazio (com colunas) se o zip nao tem
    o que esperamos.
    """
    try:
        z = zipfile.ZipFile(io.BytesIO(conteudo))
    except zipfile.BadZipFile:
        return _vazio()
    indice, partes = None, []
    for nome in z.namelist():
        m = _NOME_CSV.match(os.path.basename(nome))
        if not m:
            continue
        tipo_arq, demo, escopo, _ano = m.groups()
        if tipo_arq.upper() != tipo.upper():
            continue
        if demo is None:
            indice = parse_indice(z.read(nome))
        elif demo.upper() in demos:
            partes.append(parse_demo(z.read(nome), tipo, demo, escopo))
    partes = [p for p in partes if not p.empty]
    if not partes:
        return _vazio()
    df = pd.concat(partes, ignore_index=True)
    if indice is None or indice.empty:
        log(f"cvm {tipo}: zip sem indice ({tipo.lower()}_cia_aberta_ANO.csv); dt_receb fica NaT e nada entra na visao")
        df["dt_receb"] = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    else:
        df = df.merge(indice[["cd_cvm", "dt_refer", "versao", "dt_receb"]],
                      on=["cd_cvm", "dt_refer", "versao"], how="left")
    df["cd_cvm"] = df["cd_cvm"].astype("int64")
    df["versao"] = df["versao"].astype("int64")
    return df[COLUNAS].sort_values(["cd_cvm", "dt_refer", "versao", "demo", "escopo", "conta"]).reset_index(drop=True)


def montar_zip(tipo, ano, indice, demos):
    """Monta um zip no layout da CVM a partir de listas de dicts (para fixtures e testes).

    indice: lista de dicts com as chaves de COLUNAS_INDICE (faltantes ficam vazias);
    demos:  {(demo, escopo): [dicts com as chaves de COLUNAS_DEMO]}.
    Grava CSV ';' latin-1, como a fonte.
    """
    tipo = tipo.lower()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{tipo}_cia_aberta_{ano}.csv", _csv(indice, COLUNAS_INDICE))
        for (demo, escopo), linhas in demos.items():
            cols = COLUNAS_DEMO if tipo == "itr" or demo in DEMOS_FLUXO else [c for c in COLUNAS_DEMO if c != "DT_INI_EXERC"]
            z.writestr(f"{tipo}_cia_aberta_{demo}_{escopo}_{ano}.csv", _csv(linhas, cols))
    return buf.getvalue()


def _csv(linhas, colunas):
    texto = ";".join(colunas) + "\n"
    for l in linhas:
        texto += ";".join(str(l.get(c, "")) for c in colunas) + "\n"
    return texto.encode("latin-1")


# ─────────────────────────────────────────────────────────────
# Point-in-time, trimestralizacao e TTM (puros)
# ─────────────────────────────────────────────────────────────
def visao_em(df, t):
    """Para cada (cd_cvm, tipo, dt_refer) a maior VERSAO com dt_receb <= t.

    Reapresentacoes so entram quando recebidas; linhas sem dt_receb nunca entram.
    """
    t = pd.Timestamp(t)
    if df.empty:
        return df.copy()
    d = df[df["dt_receb"].notna() & (df["dt_receb"] <= t)]
    if d.empty:
        return d.copy()
    vmax = d.groupby(["cd_cvm", "tipo", "dt_refer"])["versao"].transform("max")
    return d[d["versao"] == vmax].copy()


def trimestralizar(df):
    """Converte DRE/DFC acumulados (ITR 3/6/9 meses e DFP 12 meses) em valores do trimestre.

    Espera uma VISAO (uma versao por documento). Q1 = 3m; Q2 = 6m - 3m; Q3 = 9m - 6m;
    Q4 = 12m - 9m. So gera o trimestre quando os dois acumulados existem. dt_receb do
    trimestre = a mais tardia das duas pecas; dt_refer = fim do trimestre.
    Devolve: cd_cvm, cnpj, escopo, demo, conta, descricao, dt_refer, dt_receb, trimestre, valor_reais.
    """
    colunas = ["cd_cvm", "cnpj", "escopo", "demo", "conta", "descricao", "dt_refer", "dt_receb",
               "trimestre", "valor_reais"]
    f = df[df["demo"].isin(DEMOS_FLUXO) & (df["ordem_exerc"] == "ULTIMO") & df["dt_ini"].notna()]
    f = f[f["meses"].isin([3, 6, 9, 12])]
    if f.empty:
        return pd.DataFrame(columns=colunas)
    chave = ["cd_cvm", "cnpj", "escopo", "demo", "conta", "dt_ini"]
    base = ["cd_cvm", "cnpj", "escopo", "demo", "conta"]
    # O ITR real traz, para o mesmo DT_FIM, a linha acumulada (dt_ini = inicio do exercicio)
    # e a do trimestre isolado (dt_ini = inicio do trimestre). Fica so a de MENOR dt_ini
    # por (conta, dt_fim); entre duplicatas exatas fica a de dt_receb mais recente.
    f = f.assign(meses=f["meses"].astype(int)).sort_values(
        base + ["dt_fim", "dt_ini", "dt_receb"], ascending=[True] * (len(base) + 2) + [False])
    f = f.drop_duplicates(base + ["dt_fim"], keep="first")
    f = f.drop_duplicates(chave + ["meses"], keep="first")
    piv = f.set_index(chave + ["meses"])[["valor_reais", "dt_receb", "dt_fim", "descricao"]].unstack("meses")
    partes = []
    anterior = 0
    for n, m in enumerate((3, 6, 9, 12), start=1):
        if ("valor_reais", m) not in piv.columns:
            anterior = m
            continue
        v = piv[("valor_reais", m)]
        receb = piv[("dt_receb", m)]
        if anterior:
            if ("valor_reais", anterior) not in piv.columns:
                anterior = m
                continue
            v = v - piv[("valor_reais", anterior)]
            receb = pd.concat([receb, piv[("dt_receb", anterior)]], axis=1).max(axis=1)
        q = pd.DataFrame({"valor_reais": v, "dt_receb": receb, "dt_refer": piv[("dt_fim", m)],
                          "descricao": piv[("descricao", m)], "trimestre": n}).dropna(subset=["valor_reais"])
        partes.append(q.reset_index())
        anterior = m
    if not partes:
        return pd.DataFrame(columns=colunas)
    out = pd.concat(partes, ignore_index=True)
    return out[colunas].sort_values(["cd_cvm", "escopo", "demo", "conta", "dt_refer"]).reset_index(drop=True)


def escopo_padrao(df_empresa):
    """'con' se a empresa entrega consolidado (em qualquer periodo), senao 'ind'."""
    return "con" if (df_empresa["escopo"] == "con").any() else "ind"


def _consecutivos(datas):
    """True se as datas (fins de trimestre) estao a 3 meses uma da outra."""
    idx = [d.year * 12 + d.month for d in datas]
    return all(b - a == 3 for a, b in zip(idx, idx[1:]))


def ttm(df, cd_cvm, t, escopo=None):
    """Numeros dos ultimos 12 meses (4 trimestres) de `cd_cvm` como eram conhecidos em `t`.

    Fluxos (receita, lucro_bruto, ebit, ebitda, lucro_liquido, fco, capex, fcf, lpa...) =
    soma dos 4 ultimos trimestres consecutivos com dt_receb <= t; estoques (ativo, caixa,
    divida_bruta, divida_liquida, pl) = ultimo balanco recebido ate t. Se houver 8
    trimestres, `receita_anterior` e o TTM de 4 trimestres antes (para crescimento).
    Devolve None se nao houver 4 trimestres consecutivos. `df` pode ser a tabela completa
    ou uma visao - a visao em t e aplicada aqui de qualquer forma (PIT).
    """
    t = pd.Timestamp(t)
    d = df[df["cd_cvm"] == cd_cvm]
    if d.empty:
        return None
    v = visao_em(d, t)
    if v.empty:
        return None
    escopo = escopo or escopo_padrao(v)
    v = v[v["escopo"] == escopo]
    q = trimestralizar(v)
    if q.empty:
        return None
    fins = sorted(q.loc[q["demo"] == "DRE", "dt_refer"].unique())
    if len(fins) < 4 or not _consecutivos(fins[-4:]):
        return None
    ultimos = fins[-4:]
    out = {"cd_cvm": int(cd_cvm), "escopo": escopo, "t": t.date(), "trimestres": [pd.Timestamp(x).date() for x in ultimos],
           "dt_refer": pd.Timestamp(ultimos[-1]).date()}
    usados = q[q["dt_refer"].isin(ultimos)]
    dt_receb = usados["dt_receb"].max()
    for nome in FLUXOS_TTM:
        soma, faltou = 0.0, False
        for fim in ultimos:
            x = contas_cvm.extrair(usados[usados["dt_refer"] == fim], nome, cd_cvm)
            if np.isnan(x):
                faltou = True
                break
            soma += x
        out[nome] = float("nan") if faltou else soma
    out["ebitda"] = out["ebit"] + out["depreciacao"]
    out["fcf"] = out["fco"] + out["capex"]
    if len(fins) >= 8 and _consecutivos(fins[-8:]):
        ant = q[q["dt_refer"].isin(fins[-8:-4])]
        vals = [contas_cvm.extrair(ant[ant["dt_refer"] == fim], "receita", cd_cvm) for fim in fins[-8:-4]]
        out["receita_anterior"] = float("nan") if any(np.isnan(x) for x in vals) else float(sum(vals))
    else:
        out["receita_anterior"] = float("nan")
    # estoques: ultimo balanco disponivel
    b = v[v["demo"].isin(DEMOS_BALANCO) & (v["ordem_exerc"] == "ULTIMO")]
    if b.empty:
        for nome in ESTOQUES_TTM:
            out[nome] = float("nan")
        out["dt_balanco"] = None
    else:
        ultimo = b["dt_refer"].max()
        b = b[b["dt_refer"] == ultimo]
        for nome in ESTOQUES_TTM:
            out[nome] = contas_cvm.extrair(b, nome, cd_cvm)
        out["dt_balanco"] = pd.Timestamp(ultimo).date()
        dt_receb = max(dt_receb, b["dt_receb"].max())
    cp = 0.0 if np.isnan(out["emprestimos_cp"]) else out["emprestimos_cp"]
    lp = 0.0 if np.isnan(out["emprestimos_lp"]) else out["emprestimos_lp"]
    out["divida_bruta"] = cp + lp
    out["divida_liquida"] = out["divida_bruta"] - (0.0 if np.isnan(out["caixa"]) else out["caixa"])
    out["dt_receb"] = pd.Timestamp(dt_receb).date()
    return out


def _div(a, b, positivo=False):
    """a/b com NaN em vez de excecao. positivo=True exige b > 0: ROE com PL negativo e
    lucro negativo daria retorno positivo - um numero sem sentido que entraria no ranking."""
    if a is None or b is None or np.isnan(a) or np.isnan(b) or b == 0 or (positivo and b <= 0):
        return float("nan")
    return float(a / b)


def metricas(ttm_dict, valor_mercado=None, financeira=False):
    """Indicadores a partir do dict de ttm(). Para financeiras ROIC/dl_ebitda nao fazem
    sentido (fica NaN) e o retorno relevante e o ROE."""
    if ttm_dict is None:
        return None
    x = ttm_dict
    nopat = x["ebit"] * (1 - contas_cvm.ALIQUOTA_IR)
    capital = x["divida_liquida"] + x["pl"]
    ebitda = x["ebitda"]
    out = {
        "roic": float("nan") if financeira else _div(nopat, capital, positivo=True),
        "roe": _div(x["lucro_liquido"], x["pl"], positivo=True),
        "margem_bruta": _div(x["lucro_bruto"], x["receita"], positivo=True),
        "margem_ebit": _div(x["ebit"], x["receita"], positivo=True),
        "gpoa": _div(x["lucro_bruto"], x["ativo"], positivo=True),
        "dl_ebitda": float("nan") if financeira else _div(x["divida_liquida"], ebitda, positivo=True),
        "crescimento_receita": _div(x["receita"], x["receita_anterior"], positivo=True) - 1,
        "fcf_yield": _div(x["fcf"], valor_mercado, positivo=True) if valor_mercado is not None else float("nan"),
        "earnings_yield": _div(x["lucro_liquido"], valor_mercado, positivo=True) if valor_mercado is not None else float("nan"),
        "financeira": bool(financeira),
        "dt_refer": x["dt_refer"], "dt_receb": x["dt_receb"],
    }
    return out


# ─────────────────────────────────────────────────────────────
# Download e banco
# ─────────────────────────────────────────────────────────────
def caminho_bruto(tipo, ano):
    return os.path.join(DIR_CVM, f"{tipo.lower()}_cia_aberta_{ano}.zip")


def baixar(tipo, ano, forcar=False):
    """Baixa o zip anual da CVM para quant/dados_brutos/cvm/ (o zip ja e comprimido; nao
    gzipamos de novo). Devolve o caminho local ou None. Anos passados nao sao rebaixados
    a menos que forcar=True - mas atencao: reapresentacoes entram no zip do ano de
    referencia, entao vale rebaixar os 2 ultimos anos periodicamente."""
    destino = caminho_bruto(tipo, ano)
    if os.path.exists(destino) and not forcar and ano < date.today().year - 1:
        return destino
    r = http_get(URL.format(TIPO=tipo.upper(), tipo=tipo.lower(), ano=ano), timeout=600)
    if r is None or len(r.content) < 1000 or not r.content.startswith(b"PK"):
        log(f"cvm {tipo} {ano}: download falhou")
        return destino if os.path.exists(destino) else None
    gravar_atomico(destino, r.content)
    log(f"cvm {tipo} {ano}: {len(r.content)/1e6:.1f} MB")
    return destino


def caminho_parquet(ano):
    return os.path.join(DIR_PARQUET, f"ano={ano}", "parte.parquet")


def gravar_ano(df, ano):
    """Grava o longo do ano (DFP + ITR com dt_refer no ano) em parquet. Devolve linhas."""
    if df.empty:
        d = _vazio()
    else:
        d = df[df["dt_refer"].dt.year == ano]
        fora = len(df) - len(d)
        if fora:
            log(f"cvm {ano}: {fora} linhas com dt_refer fora de {ano} descartadas (zip anual nao e por ano de referencia?)")
    destino = caminho_parquet(ano)
    garantir_dir(os.path.dirname(destino))
    d.to_parquet(destino, index=False)
    return int(len(d))


def atualizar(anos, tipos=TIPOS, forcar=False):
    """Baixa (se preciso) DFP e ITR de cada ano e grava o parquet. {ano: linhas ou None}."""
    out = {}
    for ano in anos:
        partes, falhou = [], False
        for tipo in tipos:
            local = baixar(tipo, ano, forcar)
            if not local:
                falhou = True
                continue
            with open(local, "rb") as f:
                partes.append(parse_zip(f.read(), tipo))
        if not partes:
            out[ano] = None
            continue
        df = pd.concat(partes, ignore_index=True)
        out[ano] = gravar_ano(df, ano)
        log(f"cvm {ano}: {out[ano]} linhas{' (parcial: um tipo falhou)' if falhou else ''}")
    return out


def carregar(anos, cd_cvm=None, colunas=None):
    """Le os parquets dos anos pedidos (ano de dt_refer). cd_cvm: int ou iteravel para filtrar;
    colunas: subconjunto de COLUNAS (cd_cvm e incluido se houver filtro)."""
    partes = []
    ler = None if colunas is None else list(dict.fromkeys(list(colunas) + (["cd_cvm"] if cd_cvm is not None else [])))
    for ano in anos:
        p = caminho_parquet(ano)
        if os.path.exists(p):
            df = pd.read_parquet(p, columns=ler)
            if cd_cvm is not None:
                cods = {int(cd_cvm)} if np.isscalar(cd_cvm) else {int(c) for c in cd_cvm}
                df = df[df["cd_cvm"].isin(cods)]
                if colunas is not None:
                    df = df[list(colunas)]
            partes.append(df)
    if not partes:
        return _vazio(list(colunas) if colunas is not None else COLUNAS)
    return pd.concat(partes, ignore_index=True)


def _anos(expr):
    if "-" in expr:
        a, b = expr.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in expr.split(",")]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Baixa DFP/ITR da CVM e monta o parquet point-in-time")
    ap.add_argument("--anos", default=f"2010-{date.today().year}")
    ap.add_argument("--tipos", default="DFP,ITR")
    ap.add_argument("--forcar", action="store_true")
    args = ap.parse_args(argv)
    res = atualizar(_anos(args.anos), tuple(args.tipos.split(",")), args.forcar)
    print(res)
    return 1 if any(v is None for v in res.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
