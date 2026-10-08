"""
Identidade point-in-time dos papeis da B3 (M3): ticker <-> ISIN <-> CNPJ / CD_CVM.

Por que existe: o ticker NAO e uma chave estavel. Ele muda de nome (MRFG3 virou MBRF3),
e reutilizado por outra empresa anos depois, some em incorporacao/OPA (BRFS3, JBSS3,
STBP3) e a mesma empresa tem varias classes (PETR3/PETR4, SANB3/SANB4/SANB11). Um
backtest que junta precos do COTAHIST com fundamentos da CVM precisa saber, PARA CADA
DATA, qual ISIN e qual CNPJ estavam por tras de um ticker - senao mistura empresas,
conta a mesma empresa duas vezes ("uma classe por empresa") ou deixa a deslistada
sumir do universo sem registrar a perda.

Fontes (todas publicas, nenhuma exige chave):
  (a) FCA da CVM: fca_cia_aberta_{ano}.zip -> fca_cia_aberta_valor_mobiliario_{ano}.csv
      da a relacao CNPJ x Codigo_Negociacao x Data_Inicio/Fim_Negociacao. E um documento
      anual (uma versao por entrega), entao o mesmo ticker aparece em varios anos/versoes;
      fica a versao mais recente por (cnpj, ticker). Colunas sao procuradas por nome
      aproximado (case-insensitive, sem acento) porque a CVM ja renomeou colunas.
  (b) cad_cia_aberta.csv da CVM: CNPJ -> CD_CVM, DENOM_SOCIAL, situacao.
  (c) COTAHIST (M2): cada linha traz o ISIN, entao a propria serie de precos da as
      vigencias ticker -> ISIN (mapa_isin). Esta e a fonte mais confiavel para a chave
      de precos, e e a unica que cobre o que foi deslistado antes do FCA existir (2010).

Armadilhas:
  - datas da CVM vem em AAAA-MM-DD, mas o parser aceita dd/mm/aaaa tambem;
  - o FCA do ano X so e entregue em X (ou X+1): um ticker novo aparece "atrasado".
    Como identidade nao e sinal (nao entra no ranking), usar a versao mais recente do
    mapa e aceitavel DESDE QUE as vigencias (data_ini/data_fim) sejam respeitadas;
  - empresa deslistada para de entregar FCA e a ultima versao fica com Data_Fim VAZIA
    ("vigente" para sempre). Se o ticker e reutilizado, a vigencia antiga e fechada no dia
    anterior ao inicio da nova (dois CNPJs nunca dividem um ticker) e o DT_CANCEL do
    cadastro tambem encerra a vigencia;
  - eventos que a fonte automatica nao registra ficam em OVERRIDES, como dados, com o
    campo `validado` dizendo se a data ja foi conferida contra a fonte;
  - o COTAHIST nao diz se um papel "ainda existe": o ultimo trecho de um ticker e
    considerado aberto se a ultima cotacao esta a menos de DIAS_ABERTO dias do fim da
    amostra (senao e um papel morto, com data_fim = ultima cotacao).

Saida: quant/banco/identidade.parquet com as colunas
  ticker, isin, cnpj, cd_cvm, denominacao, setor, mercado, data_ini, data_fim, fonte
(data_fim NaT = vigente; `setor` e o SETOR_ATIV cru do cadastro - texto livre e grosseiro
da CVM, "" quando o CNPJ nao esta no cadastro; a taxonomia fechada sai de
quant/dados/setores.py). Uso: python -m quant.dados.identidade --anos 2010-2026
"""
import argparse
import io
import os
import re
import sys
import unicodedata
import zipfile
from datetime import date, datetime

import numpy as np
import pandas as pd

from quant.comum import DIR_BANCO, DIR_BRUTOS, agora_brt, garantir_dir, gravar_atomico, gravar_gzip, http_get, ler_gzip, log

URL_FCA = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_{ano}.zip"
URL_CAD = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"
ARQ_VALOR_MOBILIARIO = "fca_cia_aberta_valor_mobiliario_{ano}.csv"
ARQ_PARQUET = os.path.join(DIR_BANCO, "identidade.parquet")
DIR_FCA = os.path.join(DIR_BRUTOS, "cvm_fca")
DIR_CAD = os.path.join(DIR_BRUTOS, "cvm_cad")

COLUNAS = ["ticker", "isin", "cnpj", "cd_cvm", "denominacao", "setor", "mercado", "data_ini", "data_fim", "fonte"]
DIAS_ABERTO = 45          # ultimo trecho do COTAHIST e "vigente" se cotou ha menos de 45 dias do fim da amostra
FCA_ANO_INICIAL = 2010    # o FCA substituiu o IAN a partir de 2010

# Casos que a fonte automatica nao registra (ou registra atrasado). SAO DADOS, nao codigo:
# ticker -> {data_fim (ultimo pregao com negociacao), sucessor, motivo, validado}.
# `validado=False` significa que a data foi anotada de memoria e precisa ser conferida
# contra o COTAHIST/FCA quando houver rede.
OVERRIDES = {
    "BRFS3": {"data_fim": "2025-09-22", "sucessor": "MBRF3", "validado": False,
              "motivo": "BRF incorporada pela Marfrig em 2025 (MBRF Global Foods)"},
    "MRFG3": {"data_fim": "2025-09-22", "sucessor": "MBRF3", "validado": False,
              "motivo": "Marfrig trocou o codigo para MBRF3 na incorporacao da BRF (mesmo CNPJ)"},
    "JBSS3": {"data_fim": "2025-06-06", "sucessor": "JBSS32", "validado": False,
              "motivo": "JBS migrou a listagem para a NYSE; na B3 ficou o BDR JBSS32 a partir de 09/06/2025"},
    "STBP3": {"data_fim": "2025-10-03", "sucessor": None, "validado": False,
              "motivo": "Santos Brasil: resgate das acoes remanescentes apos OPA da CMA CGM"},
}

# ─────────────────────────────────────────────────────────────
# Utilitarios puros
# ─────────────────────────────────────────────────────────────
_TICKER = re.compile(r"^[A-Z][A-Z0-9]{3}(\d{1,2})[A-Z]?$")


def _sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c))


def _chave(nome):
    return re.sub(r"[^a-z0-9]", "", _sem_acento(nome).lower())


def coluna(df, *candidatos, obrigatoria=False):
    """Acha uma coluna por nome aproximado: igualdade apos normalizar (minusculas, sem
    acento, sem '_'), depois 'contem'. Devolve o nome real ou None."""
    chaves = {_chave(c): c for c in df.columns}
    for cand in candidatos:
        k = _chave(cand)
        if k in chaves:
            return chaves[k]
    for cand in candidatos:
        k = _chave(cand)
        for kc, real in chaves.items():
            if k in kc:
                return real
    if obrigatoria:
        raise KeyError(f"nenhuma coluna parecida com {candidatos} em {list(df.columns)[:12]}")
    return None


def data_cvm(s):
    """'2023-04-27', '27/04/2023', '20230427' ou vazio -> Timestamp/NaT."""
    if s is None:
        return pd.NaT
    s = str(s).strip()
    if not s or s.lower() in ("nan", "nat", "none"):
        return pd.NaT
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return pd.Timestamp(datetime.strptime(s[:19] if "%H" in fmt else s[:10], fmt))
        except ValueError:
            continue
    return pd.NaT


def cnpj_limpo(s):
    """Mantem so digitos e completa com zeros a esquerda ate 14 (CVM omite zeros as vezes)."""
    d = re.sub(r"\D", "", str(s or ""))
    return d.zfill(14) if d else ""


def _para_ts(d):
    if d is None or (isinstance(d, float) and np.isnan(d)):
        return pd.NaT
    if isinstance(d, pd.Timestamp):
        return d.normalize()
    if isinstance(d, datetime):
        return pd.Timestamp(d.date())
    if isinstance(d, date):
        return pd.Timestamp(d)
    return data_cvm(d)


def sufixo(ticker):
    """'PETR4' -> '4'; 'AAPL34' -> '34'; 'BOVA11' -> '11'; 'PETR4F' -> '4'; invalido -> None."""
    m = _TICKER.match(str(ticker).strip().upper())
    return m.group(1) if m else None


def classificar_papel(ticker, isin=None, codbdi=None):
    """'acao' | 'unit' | 'bdr' | 'etf' | 'fii' | 'direito' | 'outro'.

    Regras (ordem importa):
      - CODBDI 10 (direitos e recibos) ou sufixo 1/2/9/10 -> direito;
      - sufixo 31..39 ou ISIN com 'BDR' -> bdr;
      - sufixo 11: CODBDI 12 -> fii; ISIN com 'CTF' (certificado de fundo) -> etf, salvo
        CODBDI 12; senao -> unit (ISIN de units na B3 e 'CDAM' - certificado de deposito
        de acoes - e nao 'ACN'; ambos sao aceitos);
      - sufixo 3..8 -> acao;
      - resto -> outro.
    """
    t = str(ticker).strip().upper()
    isin = (isin or "").strip().upper()
    codbdi = str(codbdi).strip().zfill(2) if codbdi not in (None, "") else None
    suf = sufixo(t)
    if codbdi == "10":
        return "direito"
    if suf is None:
        return "outro"
    if suf in ("1", "2", "9", "10"):
        return "direito"
    if suf in {str(n) for n in range(31, 40)} or "BDR" in isin:
        return "bdr"
    if suf == "11":
        if codbdi == "12":
            return "fii"
        if "CTF" in isin:
            return "etf"
        return "unit"
    if suf in ("3", "4", "5", "6", "7", "8"):
        return "acao"
    return "outro"


# ─────────────────────────────────────────────────────────────
# Parsers puros das fontes
# ─────────────────────────────────────────────────────────────
def _ler_csv_cvm(conteudo):
    from quant.dados.arquivar_b3 import ler_csv_b3
    return ler_csv_b3(conteudo)


def ler_fca_valor_mobiliario(conteudo):
    """CSV fca_cia_aberta_valor_mobiliario -> DataFrame(cnpj, ticker, valor_mobiliario, mercado,
    data_ini, data_fim, data_referencia, versao). Linhas sem codigo de negociacao sao descartadas.

    SUPOSICAO sobre o layout (a validar com rede): colunas CNPJ_Companhia, Data_Referencia,
    Versao, Valor_Mobiliario, Codigo_Negociacao, Mercado, Data_Inicio_Negociacao,
    Data_Fim_Negociacao; datas em AAAA-MM-DD; separador ';' e latin-1.
    """
    df = _ler_csv_cvm(conteudo)
    if df.empty:
        return pd.DataFrame(columns=["cnpj", "ticker", "valor_mobiliario", "mercado", "data_ini",
                                     "data_fim", "data_referencia", "versao"])
    c_cnpj = coluna(df, "CNPJ_Companhia", "CNPJ_CIA", "CNPJ", obrigatoria=True)
    c_tick = coluna(df, "Codigo_Negociacao", "CD_NEGOCIACAO", "Codigo", obrigatoria=True)
    c_vm = coluna(df, "Valor_Mobiliario", "TP_VALOR_MOBILIARIO")
    c_merc = coluna(df, "Mercado", "TP_MERCADO")
    c_ini = coluna(df, "Data_Inicio_Negociacao", "DT_INI_NEGOCIACAO", "Inicio_Negociacao")
    c_fim = coluna(df, "Data_Fim_Negociacao", "DT_FIM_NEGOCIACAO", "Fim_Negociacao")
    c_ref = coluna(df, "Data_Referencia", "DT_REFER")
    c_ver = coluna(df, "Versao", "VERSAO")
    out = pd.DataFrame({
        "cnpj": df[c_cnpj].map(cnpj_limpo),
        "ticker": df[c_tick].astype(str).str.strip().str.upper(),
        "valor_mobiliario": df[c_vm].astype(str).str.strip() if c_vm else "",
        "mercado": df[c_merc].astype(str).str.strip() if c_merc else "",
        "data_ini": df[c_ini].map(data_cvm) if c_ini else pd.NaT,
        "data_fim": df[c_fim].map(data_cvm) if c_fim else pd.NaT,
        "data_referencia": df[c_ref].map(data_cvm) if c_ref else pd.NaT,
        "versao": pd.to_numeric(df[c_ver], errors="coerce") if c_ver else np.nan,
    })
    out = out[(out["ticker"] != "") & out["ticker"].str.match(r"^[A-Z0-9]{4,}\d")]
    return out.reset_index(drop=True)


def ler_cadastro(conteudo):
    """cad_cia_aberta.csv -> DataFrame(cnpj, cd_cvm, denominacao, situacao, setor, data_reg,
    data_cancel), uma linha por CNPJ (prefere a situacao ATIVO / mais recente)."""
    df = _ler_csv_cvm(conteudo)
    if df.empty:
        return pd.DataFrame(columns=["cnpj", "cd_cvm", "denominacao", "situacao", "setor", "data_reg", "data_cancel"])
    c_cnpj = coluna(df, "CNPJ_CIA", "CNPJ_Companhia", "CNPJ", obrigatoria=True)
    c_cd = coluna(df, "CD_CVM", "Codigo_CVM", obrigatoria=True)
    c_den = coluna(df, "DENOM_SOCIAL", "Denominacao_Social", "DENOM")
    c_sit = coluna(df, "SIT", "Situacao")
    c_dtsit = coluna(df, "DT_INI_SIT")
    c_setor = coluna(df, "SETOR_ATIV", "Setor")
    c_reg = coluna(df, "DT_REG", "Data_Registro")
    c_can = coluna(df, "DT_CANCEL", "Data_Cancelamento")
    out = pd.DataFrame({
        "cnpj": df[c_cnpj].map(cnpj_limpo),
        "cd_cvm": pd.to_numeric(df[c_cd], errors="coerce").astype("Int64"),
        "denominacao": df[c_den].astype(str).str.strip() if c_den else "",
        "situacao": df[c_sit].astype(str).str.strip().str.upper() if c_sit else "",
        "setor": df[c_setor].astype(str).str.strip() if c_setor else "",
        "data_reg": df[c_reg].map(data_cvm) if c_reg else pd.NaT,
        "data_cancel": df[c_can].map(data_cvm) if c_can else pd.NaT,
        "_dt_sit": df[c_dtsit].map(data_cvm) if c_dtsit else pd.NaT,
    })
    out = out[out["cnpj"] != ""]
    out["_ativo"] = (out["situacao"] == "ATIVO").astype(int)
    out = (out.sort_values(["cnpj", "_ativo", "_dt_sit"], na_position="first")
              .drop_duplicates("cnpj", keep="last")
              .drop(columns=["_ativo", "_dt_sit"]))
    return out.reset_index(drop=True)


def extrair_valor_mobiliario(zip_bytes, ano=None):
    """Bytes do fca_cia_aberta_{ano}.zip -> conteudo (bytes) do CSV de valores mobiliarios, ou None."""
    try:
        z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        return None
    alvo = ARQ_VALOR_MOBILIARIO.format(ano=ano).lower() if ano else None
    nomes = [n for n in z.namelist() if (alvo and n.lower().endswith(alvo)) or
             (not alvo and "valor_mobiliario" in n.lower())]
    if not nomes:
        nomes = [n for n in z.namelist() if "valor_mobiliario" in n.lower()]
    if not nomes:
        return None
    return z.read(nomes[0])


def mapa_isin(df_cotahist, dias_aberto=DIAS_ABERTO):
    """Vigencias ticker -> ISIN a partir das linhas do COTAHIST (colunas data, ticker, isin).

    Um trecho novo comeca quando o ISIN do ticker muda. Devolve DataFrame(ticker, isin,
    data_ini, data_fim, aberto, n_dias): data_fim e a ultima cotacao do trecho; `aberto`
    marca o ultimo trecho do ticker quando ele cotou a menos de `dias_aberto` dias do fim
    da amostra (papel presumidamente vivo).
    """
    vazio = pd.DataFrame(columns=["ticker", "isin", "data_ini", "data_fim", "aberto", "n_dias"])
    if df_cotahist is None or len(df_cotahist) == 0:
        return vazio
    d = pd.DataFrame({
        "ticker": df_cotahist["ticker"].astype(str).str.strip().str.upper(),
        "isin": df_cotahist["isin"].astype(str).str.strip().str.upper(),
        "data": pd.to_datetime(df_cotahist["data"]),
    })
    d = d[(d["isin"] != "") & (d["isin"] != "NAN")].sort_values(["ticker", "data"])
    if d.empty:
        return vazio
    mudou = (d["ticker"] != d["ticker"].shift()) | (d["isin"] != d["isin"].shift())
    d["trecho"] = mudou.cumsum()
    g = d.groupby(["trecho", "ticker", "isin"], sort=True).agg(data_ini=("data", "min"), data_fim=("data", "max"),
                                                                n_dias=("data", "size")).reset_index()
    fim_amostra = d["data"].max()
    ultimo = ~g.duplicated("ticker", keep="last")
    g["aberto"] = ultimo & (g["data_fim"] >= fim_amostra - pd.Timedelta(days=dias_aberto))
    return g.drop(columns=["trecho"]).sort_values(["ticker", "data_ini"]).reset_index(drop=True)


# ─────────────────────────────────────────────────────────────
# Montagem da tabela
# ─────────────────────────────────────────────────────────────
def _vazia():
    df = pd.DataFrame(columns=COLUNAS)
    df["data_ini"] = pd.to_datetime(df["data_ini"])
    df["data_fim"] = pd.to_datetime(df["data_fim"])
    return df


def _fca_consolidado(df_fca):
    """Uma linha por (cnpj, ticker): versao mais recente (data_referencia, versao) do FCA."""
    if df_fca is None or len(df_fca) == 0:
        return pd.DataFrame(columns=["cnpj", "ticker", "mercado", "data_ini", "data_fim"])
    f = df_fca.copy()
    f["data_ini"] = f["data_ini"].map(_para_ts)
    f["data_fim"] = f["data_fim"].map(_para_ts)
    f["_ref"] = f["data_referencia"].map(_para_ts) if "data_referencia" in f else pd.NaT
    f["_ver"] = pd.to_numeric(f["versao"], errors="coerce") if "versao" in f else 0
    f = f.sort_values(["cnpj", "ticker", "_ref", "_ver"], na_position="first")
    ult = f.drop_duplicates(["cnpj", "ticker"], keep="last")
    # a data de inicio mais antiga entre as versoes e mais confiavel que a da ultima versao
    ini = f.groupby(["cnpj", "ticker"])["data_ini"].min().rename("data_ini_min")
    ult = ult.merge(ini, left_on=["cnpj", "ticker"], right_index=True, how="left")
    ult["data_ini"] = ult["data_ini_min"].where(ult["data_ini_min"].notna(), ult["data_ini"])
    cols = ["cnpj", "ticker", "mercado", "data_ini", "data_fim"]
    return _fechar_ticker_reutilizado(ult[cols].reset_index(drop=True))


def _fechar_ticker_reutilizado(fca):
    """Dois CNPJs nao podem ter o mesmo ticker ao mesmo tempo. Uma empresa deslistada para de
    entregar FCA e a sua ultima versao fica com Data_Fim_Negociacao VAZIA (= "vigente"); se o
    ticker e reutilizado por outra empresa, a vigencia antiga e fechada no dia anterior ao
    inicio da nova. So encurta, nunca estende."""
    if fca is None or len(fca) == 0:
        return fca
    fca = fca.sort_values(["ticker", "data_ini"], na_position="first").reset_index(drop=True)
    for _, idx in fca.groupby("ticker").indices.items():
        if len(idx) < 2:
            continue
        for a, b in zip(idx[:-1], idx[1:]):
            if fca.at[a, "cnpj"] == fca.at[b, "cnpj"] or pd.isna(fca.at[b, "data_ini"]):
                continue
            limite = fca.at[b, "data_ini"] - pd.Timedelta(days=1)
            fim = fca.at[a, "data_fim"]
            if pd.isna(fim) or fim > limite:
                fca.at[a, "data_fim"] = limite
    return fca


def _intersecao(a_ini, a_fim, b_ini, b_fim):
    ini = max([x for x in (a_ini, b_ini) if pd.notna(x)], default=pd.NaT)
    fins = [x for x in (a_fim, b_fim) if pd.notna(x)]
    fim = min(fins) if fins else pd.NaT
    return ini, fim


def montar_identidade(df_fca, df_cad, df_cotahist=None, overrides=OVERRIDES):
    """Junta FCA (ticker x cnpj x vigencia), cadastro (cnpj -> cd_cvm/denominacao/setor) e, se
    houver, o COTAHIST (ticker -> ISIN por vigencia). Devolve a tabela `identidade`.

    fonte: 'fca+cotahist' (ticker casou nas duas), 'fca' (sem ISIN na amostra de precos),
    'cotahist' (papel sem FCA, p.ex. deslistado antes de 2010; cnpj vazio) - e o campo
    recebe o sufixo '+override' quando OVERRIDES fechou a vigencia.
    """
    fca = _fca_consolidado(df_fca)
    if len(fca) and df_cad is not None and len(df_cad) and "data_cancel" in df_cad.columns:
        # registro cancelado na CVM (incorporacao, OPA, fechamento de capital) encerra a vigencia
        canc = df_cad.drop_duplicates("cnpj").set_index("cnpj")["data_cancel"].map(_para_ts)
        dc = fca["cnpj"].map(canc)
        fecha = dc.notna() & (fca["data_fim"].isna() | (fca["data_fim"] > dc))
        fca.loc[fecha, "data_fim"] = dc[fecha]
    isins = mapa_isin(df_cotahist) if df_cotahist is not None else pd.DataFrame(columns=["ticker"])
    linhas = []
    usados = set()
    for r in fca.itertuples(index=False):
        base = {"ticker": r.ticker, "cnpj": r.cnpj, "mercado": r.mercado, "data_ini": r.data_ini,
                "data_fim": r.data_fim}
        trechos = isins[isins["ticker"] == r.ticker] if len(isins) else isins
        casou = False
        for t in trechos.itertuples(index=False):
            t_fim = pd.NaT if t.aberto else t.data_fim
            ini, fim = _intersecao(r.data_ini, r.data_fim, t.data_ini, t_fim)
            if pd.notna(ini) and pd.notna(fim) and fim < ini:
                continue
            casou = True
            usados.add((t.ticker, t.isin, t.data_ini))
            linhas.append({**base, "isin": t.isin, "data_ini": ini, "data_fim": fim, "fonte": "fca+cotahist"})
        if not casou:
            linhas.append({**base, "isin": None, "fonte": "fca"})
    if len(isins):
        for t in isins.itertuples(index=False):
            if (t.ticker, t.isin, t.data_ini) in usados:
                continue
            linhas.append({"ticker": t.ticker, "isin": t.isin, "cnpj": "", "mercado": "",
                           "data_ini": t.data_ini, "data_fim": pd.NaT if t.aberto else t.data_fim,
                           "fonte": "cotahist"})
    if not linhas:
        return _vazia()
    ident = pd.DataFrame(linhas)
    # cadastro
    cols_cad = ["cnpj", "cd_cvm", "denominacao", "setor"]
    # reindex (e nao df_cad[cols]) porque um cadastro antigo pode nao trazer `setor`: coluna ausente vira NaN
    cad = df_cad.reindex(columns=cols_cad).drop_duplicates("cnpj") if df_cad is not None and len(df_cad) \
        else pd.DataFrame(columns=cols_cad)
    ident = ident.merge(cad, on="cnpj", how="left")
    ident["cnpj"] = ident["cnpj"].fillna("").astype(str)
    ident["cd_cvm"] = pd.to_numeric(ident["cd_cvm"], errors="coerce").astype("Int64")
    ident["denominacao"] = ident["denominacao"].fillna("").astype(str)
    ident["setor"] = ident["setor"].fillna("").astype(str)
    ident["data_ini"] = pd.to_datetime(ident["data_ini"])
    ident["data_fim"] = pd.to_datetime(ident["data_fim"])
    ident = aplicar_overrides(ident, overrides)
    return ident[COLUNAS].sort_values(["ticker", "data_ini"]).reset_index(drop=True)


def aplicar_overrides(ident, overrides=OVERRIDES):
    """Fecha vigencias conforme OVERRIDES (data_fim = ultimo pregao negociado). So encurta:
    nunca reabre nem estende uma vigencia que a fonte ja fechou antes."""
    if not overrides or ident is None or len(ident) == 0:
        return ident
    ident = ident.copy()
    for ticker, o in overrides.items():
        fim = _para_ts(o.get("data_fim"))
        if pd.isna(fim):
            continue
        m = (ident["ticker"] == ticker) & (ident["data_fim"].isna() | (ident["data_fim"] > fim)) \
            & (ident["data_ini"].isna() | (ident["data_ini"] <= fim))
        ident.loc[m, "data_fim"] = fim
        ident.loc[m, "fonte"] = ident.loc[m, "fonte"].astype(str) + "+override"
    return ident


def resolver(identidade, ticker, data):
    """Linha vigente do ticker em `data` como dict, ou None. Respeita data_ini <= data <= data_fim
    (data_fim NaT = ainda vigente). Em empate prefere quem tem ISIN e a vigencia mais recente."""
    if identidade is None or len(identidade) == 0:
        return None
    ts = _para_ts(data)
    d = identidade[identidade["ticker"] == str(ticker).strip().upper()]
    if d.empty:
        return None
    ini_ok = d["data_ini"].isna() | (d["data_ini"] <= ts)
    fim_ok = d["data_fim"].isna() | (d["data_fim"] >= ts)
    d = d[ini_ok & fim_ok]
    if d.empty:
        return None
    d = d.assign(_isin=d["isin"].notna() & (d["isin"].astype(str) != ""),
                 _cnpj=d["cnpj"].notna() & (d["cnpj"].astype(str) != "")
                 ).sort_values(["_isin", "_cnpj", "data_ini"], kind="stable")
    r = d.iloc[-1]
    out = {}
    for c in COLUNAS:
        v = r[c] if c in r else None      # parquet gravado por uma versao anterior pode nao ter a coluna
        if c in ("data_ini", "data_fim"):
            out[c] = None if pd.isna(v) else pd.Timestamp(v).date()
        elif c == "cd_cvm":
            out[c] = None if pd.isna(v) else int(v)
        else:
            out[c] = None if (v is None or (isinstance(v, float) and np.isnan(v))) else v
    return out


def empresa_de(identidade, ticker, data):
    """Chave de empresa para 'uma classe por empresa': o CNPJ vigente; sem CNPJ, o emissor do
    ISIN (6 primeiros caracteres, ex. 'BRPETR' - PETR3 e PETR4 compartilham). None se nada."""
    r = resolver(identidade, ticker, data)
    if r is None:
        return None
    if r.get("cnpj"):
        return r["cnpj"]
    if r.get("isin") and len(str(r["isin"])) >= 6:
        return str(r["isin"])[:6]
    return None


# ─────────────────────────────────────────────────────────────
# Rede e banco
# ─────────────────────────────────────────────────────────────
def caminho_fca(ano):
    return os.path.join(DIR_FCA, f"fca_cia_aberta_{ano}.zip")


def baixar_fca(ano, forcar=False):
    """Baixa o zip anual do FCA (bruto em dados_brutos/cvm_fca) e devolve o DataFrame de
    ler_fca_valor_mobiliario, ou None. Anos passados nao sao rebaixados sem forcar."""
    destino = caminho_fca(ano)
    if not (os.path.exists(destino) and not forcar and ano < date.today().year):
        r = http_get(URL_FCA.format(ano=ano), timeout=300)
        if r is None or len(r.content) < 1000:
            log(f"fca {ano}: download falhou")
            if not os.path.exists(destino):
                return None
        else:
            gravar_atomico(destino, r.content)
            log(f"fca {ano}: {len(r.content)/1e6:.1f} MB")
    with open(destino, "rb") as f:
        csv = extrair_valor_mobiliario(f.read(), ano)
    if csv is None:
        log(f"fca {ano}: zip sem valor_mobiliario")
        return None
    try:
        return ler_fca_valor_mobiliario(csv)
    except Exception as e:
        log(f"fca {ano}: parse falhou ({type(e).__name__}: {e})")
        return None


def baixar_cadastro():
    """Baixa cad_cia_aberta.csv (gzip com carimbo do dia em dados_brutos/cvm_cad) -> DataFrame ou None."""
    r = http_get(URL_CAD, timeout=120)
    if r is None or len(r.content) < 1000:
        log("cadastro cvm: download falhou")
        ult = os.path.join(DIR_CAD, "cad_cia_aberta_ultimo.csv.gz")
        return ler_cadastro(ler_gzip(ult)) if os.path.exists(ult) else None
    garantir_dir(DIR_CAD)
    gravar_gzip(os.path.join(DIR_CAD, f"cad_cia_aberta_{agora_brt():%Y%m%d}.csv.gz"), r.content)
    gravar_gzip(os.path.join(DIR_CAD, "cad_cia_aberta_ultimo.csv.gz"), r.content)
    try:
        return ler_cadastro(r.content)
    except Exception as e:
        log(f"cadastro cvm: parse falhou ({type(e).__name__}: {e})")
        return None


def gravar_identidade(df, caminho=ARQ_PARQUET):
    garantir_dir(os.path.dirname(caminho))
    d = df.copy()
    d["cd_cvm"] = pd.to_numeric(d["cd_cvm"], errors="coerce").astype("Int64")
    d.to_parquet(caminho, index=False)
    return caminho


def carregar_identidade(caminho=ARQ_PARQUET):
    if not os.path.exists(caminho):
        return None
    return pd.read_parquet(caminho)


def atualizar(anos, ano_ini_cotahist=None):
    """Baixa FCA (anos) + cadastro, le o COTAHIST local e grava identidade.parquet."""
    from quant.dados import cotahist
    fcas = [f for f in (baixar_fca(a) for a in anos) if f is not None and len(f)]
    df_fca = pd.concat(fcas, ignore_index=True) if fcas else None
    df_cad = baixar_cadastro()
    df_cot = cotahist.carregar(ano_ini_cotahist or 1986, date.today().year, colunas=["data", "ticker", "isin"])
    ident = montar_identidade(df_fca, df_cad, df_cot if len(df_cot) else None)
    gravar_identidade(ident)
    log(f"identidade: {len(ident)} vigencias, {ident['ticker'].nunique()} tickers")
    return ident


def main(argv=None):
    ap = argparse.ArgumentParser(description="Monta o mapa point-in-time ticker/ISIN/CNPJ")
    ap.add_argument("--anos", default=f"{FCA_ANO_INICIAL}-{date.today().year}")
    args = ap.parse_args(argv)
    a, b = args.anos.split("-") if "-" in args.anos else (args.anos, args.anos)
    ident = atualizar(range(int(a), int(b) + 1))
    return 0 if len(ident) else 1


if __name__ == "__main__":
    sys.exit(main())
