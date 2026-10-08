"""
Numero de acoes em circulacao (pre-requisito do sinal de valor, M8), do FCA da CVM.

Por que existe: B/M, EV/EBIT, FCF yield e earnings yield precisam de VALOR DE MERCADO, e
valor de mercado precisa de quantidade de acoes. O pacote inteiro nao tinha essa
informacao: o COTAHIST traz preco, a CVM traz balanco, e ninguem traz quantas acoes
existem. Sem este modulo o sinal de valor - 25% do score e uma das seis exclusoes da
secao 7 - simplesmente nao existe.

Fonte primaria: `fca_cia_aberta_capital_social_{ano}.csv`, dentro do mesmo zip anual do
FCA que `identidade.py` ja baixa (nenhum download novo). Fonte de reserva: estimar a
quantidade por `lucro_liquido / LPA` a partir do painel de fundamentos.

SUPOSICOES GRANDES (validar na primeira rodada com rede - estao em
docs/validar-com-fonte-real.md):
  1. O nome do CSV e as colunas. Foram escritos a partir da documentacao do FCA
     (CNPJ_Companhia, Data_Referencia, Versao, Codigo_CVM, Tipo_Capital, Valor_Capital,
     Quantidade_Acoes_Ordinarias, Quantidade_Acoes_Preferenciais, Quantidade_Total_Acoes).
     A leitura e tolerante (`coluna()` aceita varios nomes), mas se o arquivo nao existir
     com esse padrao o modulo devolve vazio e o sinal de valor se desliga sozinho.
  2. `Tipo_Capital`: usamos o capital INTEGRALIZADO, com "subscrito" e "emitido" como
     alternativas nessa ordem. "Autorizado" NUNCA entra - e o teto estatutario, nao o
     que existe.
  3. POINT-IN-TIME: este CSV nao traz data de recebimento. O FCA e anual e entregue
     meses depois da data de referencia, entao aplicamos `DIAS_ATRASO` (padrao 150 dias)
     sobre a `Data_Referencia` para estimar quando o numero ficou publico. E uma
     estimativa CONSERVADORA (atrasa a informacao); se estiver curta demais, ha
     look-ahead no sinal de valor. Precisa ser cruzada com a data de entrega real.
  4. Recompra e emissao entre duas entregas do FCA nao aparecem: a quantidade so muda
     uma vez por ano. Isso subestima a variacao do valor de mercado de quem recompra.
  5. `valor_mercado` multiplica a quantidade TOTAL de acoes (ON + PN + units) pelo preco
     da UNICA classe que o universo manteve. Quando ON e PN negociam a precos diferentes
     isso erra o valor de mercado pela diferenca entre as classes. E o erro conhecido e
     aceito aqui; a alternativa (somar classe a classe) exige preco de todas as classes,
     inclusive das que nao passam no filtro de liquidez.

Uso:
    python -m quant.dados.capital_social --anos 2010-2026
"""
import argparse
import io
import os
import sys
import zipfile
from datetime import date

import numpy as np
import pandas as pd

from quant.comum import DIR_BANCO, DIR_BRUTOS, garantir_dir, gravar_atomico, http_get, log
from quant.dados import identidade

ARQ_INTERNO = "fca_cia_aberta_capital_social_{ano}.csv"
ARQ_PARQUET = os.path.join(DIR_BANCO, "capital_social.parquet")
DIAS_ATRASO = 150                     # SUPOSICAO: atraso entre data de referencia e publicidade
PRIORIDADE_TIPO = ("integralizado", "subscrito", "emitido")
COLUNAS = ["cd_cvm", "cnpj", "data_ref", "disponivel_em", "versao", "tipo",
           "acoes_on", "acoes_pn", "acoes_total", "capital", "fonte"]


# ─────────────────────────────────────────────────────────────
# Utilitarios puros
# ─────────────────────────────────────────────────────────────
def _vazio():
    df = pd.DataFrame(columns=COLUNAS)
    for c in ("data_ref", "disponivel_em"):
        df[c] = pd.to_datetime(df[c])
    return df


def _num(serie):
    """Quantidade de acoes: inteiro grande, as vezes com separador de milhar."""
    s = serie.astype(str).str.strip().str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce")


def rank_tipo(tipo):
    """Menor e melhor. Capital autorizado devolve None: e teto estatutario, nao acao emitida."""
    t = str(tipo or "").strip().lower()
    if "autorizado" in t:
        return None
    for i, chave in enumerate(PRIORIDADE_TIPO):
        if chave in t:
            return i
    return len(PRIORIDADE_TIPO)


def ler_capital_social(conteudo, dias_atraso=DIAS_ATRASO):
    """CSV do FCA -> DataFrame(COLUNAS), uma linha por (cd_cvm, data_ref) com o melhor tipo.

    `disponivel_em = data_ref + dias_atraso` e o carimbo point-in-time estimado.
    """
    df = identidade._ler_csv_cvm(conteudo)
    if df is None or df.empty:
        return _vazio()
    c_cnpj = identidade.coluna(df, "CNPJ_Companhia", "CNPJ_CIA", "CNPJ")
    c_cd = identidade.coluna(df, "Codigo_CVM", "CD_CVM")
    c_data = identidade.coluna(df, "Data_Referencia", "DT_REFER", "Data_Autorizacao_Ou_Aprovacao")
    c_ver = identidade.coluna(df, "Versao", "VERSAO")
    c_tipo = identidade.coluna(df, "Tipo_Capital", "Tipo")
    c_on = identidade.coluna(df, "Quantidade_Acoes_Ordinarias", "Qtd_Acoes_Ordinarias")
    c_pn = identidade.coluna(df, "Quantidade_Acoes_Preferenciais", "Qtd_Acoes_Preferenciais")
    c_tot = identidade.coluna(df, "Quantidade_Total_Acoes", "Qtd_Total_Acoes")
    c_cap = identidade.coluna(df, "Valor_Capital", "Valor")
    if c_data is None or (c_tot is None and c_on is None):
        return _vazio()
    out = pd.DataFrame({
        "cd_cvm": pd.to_numeric(df[c_cd], errors="coerce").astype("Int64") if c_cd else pd.NA,
        "cnpj": df[c_cnpj].map(identidade.cnpj_limpo) if c_cnpj else "",
        "data_ref": df[c_data].map(identidade.data_cvm),
        "versao": pd.to_numeric(df[c_ver], errors="coerce").fillna(1).astype(int) if c_ver else 1,
        "tipo": df[c_tipo].astype(str).str.strip() if c_tipo else "",
        "acoes_on": _num(df[c_on]) if c_on else np.nan,
        "acoes_pn": _num(df[c_pn]) if c_pn else np.nan,
        "acoes_total": _num(df[c_tot]) if c_tot else np.nan,
        "capital": _num(df[c_cap]) if c_cap else np.nan,
    })
    out["fonte"] = "fca"
    # total ausente: soma das classes conhecidas
    soma = out[["acoes_on", "acoes_pn"]].sum(axis=1, min_count=1)
    out["acoes_total"] = out["acoes_total"].where(out["acoes_total"] > 0, soma)
    out = out[out["data_ref"].notna() & (out["acoes_total"] > 0)]
    if out.empty:
        return _vazio()
    out["_rank"] = out["tipo"].map(rank_tipo)
    out = out[out["_rank"].notna()]
    if out.empty:
        return _vazio()
    out = (out.sort_values(["cd_cvm", "data_ref", "_rank", "versao"])
              .drop_duplicates(["cd_cvm", "data_ref"], keep="first").drop(columns=["_rank"]))
    out["disponivel_em"] = out["data_ref"] + pd.Timedelta(days=int(dias_atraso))
    return out[COLUNAS].sort_values(["cd_cvm", "data_ref"]).reset_index(drop=True)


def estimar_por_lpa(painel, min_lpa=0.01):
    """Reserva: acoes = lucro_liquido / LPA, a partir do painel de fundamentos.

    So aceita |LPA| >= min_lpa (a CVM publica 0,00 com frequencia) e exige lucro e LPA de
    mesmo sinal. `disponivel_em` e a propria data do painel, que ja e point-in-time.
    """
    if painel is None or len(painel) == 0:
        return _vazio()
    p = painel[["data", "cd_cvm", "lucro_liquido", "lpa", "dt_refer"]].copy()
    p = p[p["lpa"].abs() >= float(min_lpa)]
    p = p[p["lucro_liquido"].notna() & (np.sign(p["lucro_liquido"]) == np.sign(p["lpa"]))]
    if p.empty:
        return _vazio()
    out = pd.DataFrame({
        "cd_cvm": pd.to_numeric(p["cd_cvm"], errors="coerce").astype("Int64"),
        "cnpj": "",
        "data_ref": pd.to_datetime(p["dt_refer"]),
        "disponivel_em": pd.to_datetime(p["data"]),
        "versao": 1,
        "tipo": "estimado_lpa",
        "acoes_on": np.nan, "acoes_pn": np.nan,
        "acoes_total": (p["lucro_liquido"] / p["lpa"]).astype(float),
        "capital": np.nan,
        "fonte": "lpa",
    })
    out = out[out["acoes_total"] > 0]
    return out[COLUNAS].sort_values(["cd_cvm", "disponivel_em"]).reset_index(drop=True)


def acoes_em(capital, datas, cd_cvms=None):
    """Quantidade conhecida em cada data: ultimo registro com disponivel_em <= data.

    Devolve DataFrame(data, cd_cvm, acoes_total, fonte, data_ref).
    """
    colunas = ["data", "cd_cvm", "acoes_total", "fonte", "data_ref"]
    if capital is None or len(capital) == 0 or datas is None or len(datas) == 0:
        return pd.DataFrame(columns=colunas)
    cap = capital.dropna(subset=["disponivel_em"]).copy()
    cap["cd_cvm"] = pd.to_numeric(cap["cd_cvm"], errors="coerce").astype("Int64")
    if cd_cvms is not None:
        cap = cap[cap["cd_cvm"].isin({int(x) for x in cd_cvms})]
    if cap.empty:
        return pd.DataFrame(columns=colunas)
    alvo = pd.DataFrame({"data": sorted({pd.Timestamp(d) for d in datas})})
    partes = []
    for cod, sub in cap.groupby("cd_cvm", sort=True):
        sub = sub.sort_values(["disponivel_em", "versao"])
        j = pd.merge_asof(alvo, sub[["disponivel_em", "acoes_total", "fonte", "data_ref"]],
                          left_on="data", right_on="disponivel_em", direction="backward")
        j = j[j["acoes_total"].notna()].copy()
        if j.empty:
            continue
        j["cd_cvm"] = int(cod)
        partes.append(j)
    if not partes:
        return pd.DataFrame(columns=colunas)
    return pd.concat(partes, ignore_index=True)[colunas].sort_values(["data", "cd_cvm"]).reset_index(drop=True)


def valor_mercado(acoes, precos):
    """DataFrame(data, cd_cvm, valor_mercado) = acoes_total x preco da classe do universo.

    `precos`: DataFrame(data, cd_cvm, preco). Ver a suposicao 5 do docstring do modulo:
    multiplicar o total de acoes pelo preco de uma classe erra quando ON e PN divergem.
    """
    colunas = ["data", "cd_cvm", "valor_mercado", "acoes_total", "preco", "fonte"]
    if acoes is None or len(acoes) == 0 or precos is None or len(precos) == 0:
        return pd.DataFrame(columns=colunas)
    a = acoes.copy()
    p = precos.copy()
    for d in (a, p):
        d["data"] = pd.to_datetime(d["data"])
        d["cd_cvm"] = pd.to_numeric(d["cd_cvm"], errors="coerce").astype("Int64")
    j = a.merge(p[["data", "cd_cvm", "preco"]], on=["data", "cd_cvm"], how="inner")
    if j.empty:
        return pd.DataFrame(columns=colunas)
    j["valor_mercado"] = j["acoes_total"] * j["preco"]
    j = j[j["valor_mercado"] > 0]
    return j[colunas].sort_values(["data", "cd_cvm"]).reset_index(drop=True)


# ─────────────────────────────────────────────────────────────
# Composicao do capital nos zips de ITR e DFP (a fonte que existe de verdade)
# ─────────────────────────────────────────────────────────────
# A primeira carga real (08/10/2026) mostrou que o zip do FCA NAO traz capital social. Quem
# traz e o proprio ITR/DFP: `<tipo>_cia_aberta_composicao_capital_<ano>.csv`, com as acoes do
# capital integralizado e as em tesouraria, por (CNPJ, data de referencia, versao). E melhor
# que o FCA em tudo: e trimestral (pega recompra e emissao) e tem data de ENTREGA de verdade
# (DT_RECEB do documento), entao o carimbo point-in-time deixa de ser estimado.
#
# A ARMADILHA E A ESCALA. O formulario deixa a companhia informar em unidades ou em milhares, e
# o CSV nao diz qual: o Banco do Brasil informa 5.730.834.040 (unidades) e a Vale 4.255.763
# (milhares). `resolver_escala` decide por companhia, com tres evidencias, nesta ordem:
#   1. lucro liquido / LPA do painel de fundamentos (quando |LPA| >= 0,01): a razao contra a
#      quantidade informada cai perto de 1 (unidades) ou perto de 1.000 (milhares);
#   2. preco/valor patrimonial: so uma das duas escalas deixa o P/VP entre 0,1 e 30;
#   3. piso de valor de mercado: papel do universo liquido nao vale menos de R$ 50 milhoes.
# Sem evidencia nenhuma fica em unidades e a fonte sai marcada `?`: o valor de mercado dessa
# companhia nao entra no sinal de valor (melhor ausente do que mil vezes errado).
ARQ_COMPOSICAO = "{tipo}_cia_aberta_composicao_capital_{ano}.csv"
ARQ_GERAL = "{tipo}_cia_aberta_{ano}.csv"
FAIXA_UNIDADE = (0.5, 2.0)
FAIXA_MILHAR = (500.0, 2000.0)
PVP_PLAUSIVEL = (0.1, 30.0)
VALOR_MERCADO_MINIMO = 50e6


def ler_composicao(zip_bytes, tipo, ano):
    """Zip anual do ITR ou do DFP -> DataFrame(COLUNAS) com as acoes EX-TESOURARIA, na escala
    que a companhia informou (ainda nao resolvida). Uma linha por (cd_cvm, data_ref, versao)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        return _vazio()
    tipo = str(tipo).lower()
    nomes = {n.lower(): n for n in z.namelist()}
    n_comp = nomes.get(ARQ_COMPOSICAO.format(tipo=tipo, ano=ano))
    n_geral = nomes.get(ARQ_GERAL.format(tipo=tipo, ano=ano))
    if not n_comp or not n_geral:
        return _vazio()
    comp = identidade._ler_csv_cvm(z.read(n_comp))
    geral = identidade._ler_csv_cvm(z.read(n_geral))
    if comp is None or comp.empty or geral is None or geral.empty:
        return _vazio()
    chave = ["CNPJ_CIA", "DT_REFER", "VERSAO"]
    if any(c not in comp.columns for c in chave + ["QT_ACAO_TOTAL_CAP_INTEGR"]) or \
            any(c not in geral.columns for c in chave + ["CD_CVM", "DT_RECEB"]):
        return _vazio()
    j = comp.merge(geral[chave + ["CD_CVM", "DT_RECEB"]].drop_duplicates(chave), on=chave, how="left")
    total = _num(j["QT_ACAO_TOTAL_CAP_INTEGR"])
    tes = _num(j["QT_ACAO_TOTAL_TESOURO"]).fillna(0.0) if "QT_ACAO_TOTAL_TESOURO" in j else 0.0
    out = pd.DataFrame({
        "cd_cvm": pd.to_numeric(j["CD_CVM"], errors="coerce").astype("Int64"),
        "cnpj": j["CNPJ_CIA"].map(identidade.cnpj_limpo),
        "data_ref": j["DT_REFER"].map(identidade.data_cvm),
        "disponivel_em": j["DT_RECEB"].map(identidade.data_cvm),
        "versao": pd.to_numeric(j["VERSAO"], errors="coerce").fillna(1).astype(int),
        "tipo": "integralizado",
        "acoes_on": _num(j["QT_ACAO_ORDIN_CAP_INTEGR"]) if "QT_ACAO_ORDIN_CAP_INTEGR" in j else np.nan,
        "acoes_pn": _num(j["QT_ACAO_PREF_CAP_INTEGR"]) if "QT_ACAO_PREF_CAP_INTEGR" in j else np.nan,
        "acoes_total": total - tes,
        "capital": np.nan,
        "fonte": tipo,
    })
    out = out[out["cd_cvm"].notna() & out["data_ref"].notna() & out["disponivel_em"].notna()
              & (out["acoes_total"] > 0)]
    return out[COLUNAS].sort_values(["cd_cvm", "data_ref", "versao"]).reset_index(drop=True)


def atualizar_de_demonstracoes(anos, tipos=("DFP", "ITR")):
    """Le a composicao do capital dos zips de ITR/DFP que `cvm_fundamentos` ja baixou.
    Nenhum download novo. Devolve a tabela (escala ainda como informada) e grava o parquet."""
    from quant.dados import cvm_fundamentos as cf
    partes = []
    for ano in anos:
        for tipo in tipos:
            caminho = cf.caminho_bruto(tipo, ano)
            if not os.path.exists(caminho):
                continue
            try:
                with open(caminho, "rb") as f:
                    df = ler_composicao(f.read(), tipo, ano)
            except Exception as e:
                log(f"capital {tipo} {ano}: leitura falhou ({type(e).__name__}: {e})")
                continue
            if len(df):
                partes.append(df)
    if not partes:
        return _vazio()
    todo = pd.concat(partes, ignore_index=True)
    todo = (todo.sort_values(["cd_cvm", "data_ref", "versao", "disponivel_em"])
                .drop_duplicates(["cd_cvm", "data_ref", "versao"], keep="last").reset_index(drop=True))
    gravar(todo)
    return todo


def resolver_escala(capital, painel=None, precos=None):
    """Poe `acoes_total` em UNIDADES, companhia a companhia. Ver o comentario do bloco.

    painel: painel de fundamentos (data, cd_cvm, lucro_liquido, lpa, pl). precos:
    DataFrame(data, cd_cvm, preco). Devolve copia do capital com `acoes_total` (e ON/PN)
    multiplicadas por 1 ou 1.000 e `fonte` acrescida de `:lpa`, `:pvp`, `:piso` (como a
    escala foi decidida) ou `:?` (nao decidida; fica como informada).
    """
    if capital is None or len(capital) == 0:
        return _vazio()
    cap = capital.copy()
    cap["cd_cvm"] = pd.to_numeric(cap["cd_cvm"], errors="coerce").astype("Int64")
    ult = cap.sort_values(["cd_cvm", "disponivel_em", "versao"]).groupby("cd_cvm").tail(1).set_index("cd_cvm")
    q = ult["acoes_total"].astype(float)
    decisao = {}                                   # cd_cvm -> (fator, como)
    # 1) lucro / LPA
    if painel is not None and len(painel) and {"cd_cvm", "lucro_liquido", "lpa"} <= set(painel.columns):
        p = painel[["data", "cd_cvm", "lucro_liquido", "lpa"]].dropna()
        p = p[(p["lpa"].abs() >= 0.01) & (np.sign(p["lucro_liquido"]) == np.sign(p["lpa"]))]
        if len(p):
            p = p.assign(cd_cvm=pd.to_numeric(p["cd_cvm"], errors="coerce").astype("Int64"),
                         por_lpa=p["lucro_liquido"] / p["lpa"])
            for cod, g in p.groupby("cd_cvm"):
                if cod not in q.index or not q[cod] > 0:
                    continue
                r = (g["por_lpa"] / q[cod]).astype(float)
                un = int(((r >= FAIXA_UNIDADE[0]) & (r <= FAIXA_UNIDADE[1])).sum())
                mil = int(((r >= FAIXA_MILHAR[0]) & (r <= FAIXA_MILHAR[1])).sum())
                if un > mil:
                    decisao[int(cod)] = (1.0, "lpa")
                elif mil > un:
                    decisao[int(cod)] = (1000.0, "lpa")
    # 2 e 3) preco: P/VP plausivel, depois piso de valor de mercado
    if precos is not None and len(precos):
        pr = precos.copy()
        pr["cd_cvm"] = pd.to_numeric(pr["cd_cvm"], errors="coerce").astype("Int64")
        pr = pr.sort_values("data").groupby("cd_cvm").tail(1).set_index("cd_cvm")["preco"].astype(float)
        pl = None
        if painel is not None and len(painel) and "pl" in painel:
            pp = painel[["data", "cd_cvm", "pl"]].dropna()
            pp = pp.assign(cd_cvm=pd.to_numeric(pp["cd_cvm"], errors="coerce").astype("Int64"))
            pl = pp.sort_values("data").groupby("cd_cvm").tail(1).set_index("cd_cvm")["pl"].astype(float)
        for cod in q.index:
            if int(cod) in decisao or cod not in pr.index or not (q[cod] > 0 and pr[cod] > 0):
                continue
            vm1 = q[cod] * pr[cod]
            if pl is not None and cod in pl.index and pl[cod] > 0:
                ok1 = PVP_PLAUSIVEL[0] <= vm1 / pl[cod] <= PVP_PLAUSIVEL[1]
                ok2 = PVP_PLAUSIVEL[0] <= vm1 * 1000.0 / pl[cod] <= PVP_PLAUSIVEL[1]
                if ok1 != ok2:
                    decisao[int(cod)] = (1.0 if ok1 else 1000.0, "pvp")
                    continue
            if vm1 < VALOR_MERCADO_MINIMO:
                decisao[int(cod)] = (1000.0, "piso")
    fator = cap["cd_cvm"].map(lambda c: decisao.get(int(c), (1.0, "?"))[0] if pd.notna(c) else 1.0)
    como = cap["cd_cvm"].map(lambda c: decisao.get(int(c), (1.0, "?"))[1] if pd.notna(c) else "?")
    for c in ("acoes_on", "acoes_pn", "acoes_total"):
        cap[c] = cap[c].astype(float) * fator.astype(float)
    cap["fonte"] = cap["fonte"].astype(str) + ":" + como.astype(str)
    cap.attrs["escala"] = {"companhias": int(len(q)),
                           "por_lpa": sum(1 for v in decisao.values() if v[1] == "lpa"),
                           "por_pvp": sum(1 for v in decisao.values() if v[1] == "pvp"),
                           "por_piso": sum(1 for v in decisao.values() if v[1] == "piso"),
                           "em_milhares": sum(1 for v in decisao.values() if v[0] == 1000.0),
                           "sem_decisao": int(len(q)) - len(decisao)}
    return cap


# ─────────────────────────────────────────────────────────────
# Download e banco
# ─────────────────────────────────────────────────────────────
def extrair_csv(zip_bytes, ano=None):
    """Bytes do fca_cia_aberta_{ano}.zip -> conteudo do CSV de capital social, ou None."""
    try:
        z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        return None
    alvo = ARQ_INTERNO.format(ano=ano).lower() if ano else None
    nomes = [n for n in z.namelist() if (alvo and n.lower().endswith(alvo))]
    if not nomes:
        nomes = [n for n in z.namelist() if "capital_social" in n.lower()]
    return z.read(nomes[0]) if nomes else None


def baixar(ano, forcar=False):
    """Le o capital social do zip anual do FCA (baixa o zip se preciso). None em falha."""
    destino = identidade.caminho_fca(ano)
    if not os.path.exists(destino) or forcar:
        r = http_get(identidade.URL_FCA.format(ano=ano), timeout=300)
        if r is None or len(r.content) < 1000:
            log(f"capital_social {ano}: download do FCA falhou")
            if not os.path.exists(destino):
                return None
        else:
            garantir_dir(os.path.dirname(destino))
            gravar_atomico(destino, r.content)
    with open(destino, "rb") as f:
        csv = extrair_csv(f.read(), ano)
    if csv is None:
        log(f"capital_social {ano}: zip do FCA sem capital_social")
        return None
    try:
        return ler_capital_social(csv)
    except Exception as e:
        log(f"capital_social {ano}: parse falhou ({type(e).__name__}: {e})")
        return None


def gravar(df, caminho=ARQ_PARQUET):
    garantir_dir(os.path.dirname(caminho))
    df[COLUNAS].to_parquet(caminho, index=False)
    return caminho


def carregar(caminho=ARQ_PARQUET):
    if not os.path.exists(caminho):
        return _vazio()
    return pd.read_parquet(caminho)


def atualizar(anos, forcar=False):
    partes = []
    for ano in anos:
        df = baixar(ano, forcar=forcar)
        if df is not None and len(df):
            partes.append(df)
            log(f"capital_social {ano}: {len(df)} empresas")
    if not partes:
        return _vazio()
    todo = pd.concat(partes, ignore_index=True)
    todo = (todo.sort_values(["cd_cvm", "data_ref", "versao"])
                .drop_duplicates(["cd_cvm", "data_ref"], keep="last").reset_index(drop=True))
    gravar(todo)
    return todo


def _anos(expr):
    if "-" in expr:
        a, b = expr.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in expr.split(",")]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Numero de acoes em circulacao (FCA da CVM)")
    ap.add_argument("--anos", default=f"2010-{date.today().year}")
    ap.add_argument("--forcar", action="store_true")
    args = ap.parse_args(argv)
    df = atualizar_de_demonstracoes(_anos(args.anos))
    if df.empty:
        df = atualizar(_anos(args.anos), forcar=args.forcar)      # caminho antigo (FCA), por via das duvidas
    if df.empty:
        print("nenhum capital social lido; o sinal de valor vai depender da reserva por LPA")
        return 1
    print(f"{len(df)} registros, {df['cd_cvm'].nunique()} empresas, "
          f"{df['data_ref'].min().date()} a {df['data_ref'].max().date()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
