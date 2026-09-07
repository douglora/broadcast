"""
COTAHIST da B3 (M2): serie historica diaria oficial, desde 1986, com papeis deslistados.

Formato: registro de largura fixa com 245 caracteres (latin-1), tipos 00 (cabecalho),
01 (cotacao) e 99 (rodape). Precos vem com duas casas decimais implicitas (dividir
por 100). Nao ha ajuste por proventos: o ajuste e feito depois, em eventos.py, como
retorno total a partir da data-ex.

Convencoes de uso:
  - universo de ACOES = CODBDI '02' (lote padrao) e TPMERC '010' (a vista);
  - a serie de precos de um papel deve seguir o ISIN por TODOS os CODBDI (uma empresa
    que entra em recuperacao judicial vai para CODBDI 08 e continua negociando -
    filtrar por '02' na serie apagaria justamente as piores perdas);
  - excluir o fracionario (TPMERC '020' / CODBDI '96') para nao duplicar.

Uso: python -m quant.dados.cotahist --anos 2005-2026     (baixa e monta o parquet)
"""
import argparse
import io
import os
import sys
import zipfile
from datetime import date

import pandas as pd

from quant.comum import DIR_BANCO, DIR_BRUTOS, garantir_dir, gravar_atomico, http_get, log

URL_ANUAL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{ano}.ZIP"
URL_DIARIO = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D{ddmmaaaa}.ZIP"
URL_MENSAL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_M{mmaaaa}.ZIP"

TAMANHO_REGISTRO = 245

# (nome, inicio, fim) em posicoes base-0, conforme o layout oficial SeriesHistoricas_Layout.pdf
LAYOUT = [
    ("tipreg", 0, 2), ("data", 2, 10), ("codbdi", 10, 12), ("ticker", 12, 24), ("tpmerc", 24, 27),
    ("nome", 27, 39), ("especi", 39, 49), ("prazot", 49, 52), ("moeda", 52, 56),
    ("abe", 56, 69), ("max", 69, 82), ("min", 82, 95), ("med", 95, 108), ("fec", 108, 121),
    ("bid", 121, 134), ("ask", 134, 147), ("negocios", 147, 152), ("qtd", 152, 170),
    ("volume", 170, 188), ("preexe", 188, 201), ("indopc", 201, 202), ("datven", 202, 210),
    ("fatcot", 210, 217), ("ptoexe", 217, 230), ("isin", 230, 242), ("dismes", 242, 245),
]
CAMPOS_PRECO = ("abe", "max", "min", "med", "fec", "bid", "ask", "preexe", "volume")
CAMPOS_INTEIRO = ("negocios", "qtd", "fatcot", "dismes")

CODBDI = {
    "02": "LOTE PADRAO", "05": "SANCIONADAS", "06": "CONCORDATARIAS", "07": "REC. EXTRAJUDICIAL",
    "08": "REC. JUDICIAL", "09": "RAET", "10": "DIREITOS E RECIBOS", "11": "INTERVENCAO",
    "12": "FUNDOS IMOBILIARIOS", "14": "CERT.INVEST/TIT.DIV.PUBLICA", "18": "OBRIGACOES",
    "22": "BONUS PRIVADOS", "26": "APOLICES/TIT.PUBLICOS", "32": "EXERC. OPC. INDICES",
    "33": "EXERC. OPC. INDICES", "38": "EXERC. OPCOES", "42": "EXERC. OPCOES", "46": "LEILAO",
    "48": "LEILAO", "49": "LEILAO", "50": "LEILAO", "51": "LEILAO", "52": "LEILAO", "53": "LEILAO",
    "54": "LEILAO", "56": "LEILAO", "58": "LEILAO", "60": "OUTROS", "61": "PERMUTA", "62": "META",
    "66": "TERMO", "68": "DEBENTURES", "70": "DEBENTURES", "71": "FUTURO", "74": "FUTURO",
    "75": "OPC. INDICES", "78": "OPC. INDICES", "82": "OPCOES", "83": "OPCOES", "84": "BOVESPAFIX",
    "90": "SOMA FIX", "96": "FRACIONARIO", "99": "TOTAL",
}
TPMERC = {"010": "VISTA", "012": "EXERC. OPC. COMPRA", "013": "EXERC. OPC. VENDA", "017": "LEILAO",
          "020": "FRACIONARIO", "030": "TERMO", "050": "FUTURO C/ RETENCAO", "060": "FUTURO",
          "070": "OPCOES COMPRA", "080": "OPCOES VENDA"}
# Empresas em situacao especial continuam sendo acoes: entram na SERIE, mas nao no universo de compra.
CODBDI_ACOES_SERIE = ("02", "05", "06", "07", "08", "09", "11")
CODBDI_UNIVERSO = ("02",)


def _texto(conteudo):
    if isinstance(conteudo, bytes):
        return conteudo.decode("latin-1")
    return conteudo


def _texto_do_zip(conteudo):
    z = zipfile.ZipFile(io.BytesIO(conteudo))
    nomes = [n for n in z.namelist() if n.upper().endswith(".TXT")] or z.namelist()
    return z.read(nomes[0]).decode("latin-1")


def parse(conteudo):
    """Texto (ou bytes latin-1) do COTAHIST -> DataFrame de registros tipo 01, ja tipado.

    Aceita linhas com 245 ou 246 caracteres (com/sem CR). Ignora cabecalho e rodape.
    """
    texto = _texto(conteudo)
    linhas = [l for l in texto.splitlines() if l.startswith("01") and len(l) >= TAMANHO_REGISTRO]
    if not linhas:
        return pd.DataFrame(columns=[c for c, _, _ in LAYOUT])
    colspecs = [(i, f) for _, i, f in LAYOUT]
    nomes = [c for c, _, _ in LAYOUT]
    df = pd.read_fwf(io.StringIO("\n".join(linhas)), colspecs=colspecs, names=nomes,
                     dtype=str, header=None)
    for c in nomes:
        df[c] = df[c].fillna("").astype(str).str.strip()
    df["data"] = pd.to_datetime(df["data"], format="%Y%m%d", errors="coerce").dt.date
    for c in CAMPOS_PRECO:
        df[c] = pd.to_numeric(df[c], errors="coerce") / 100.0
    df["ptoexe"] = pd.to_numeric(df["ptoexe"], errors="coerce") / 1e6
    for c in CAMPOS_INTEIRO:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    df["datven"] = pd.to_datetime(df["datven"].where(df["datven"] != "99991231"), format="%Y%m%d",
                                  errors="coerce").dt.date
    return df.drop(columns=["tipreg"])


def parse_zip(conteudo):
    return parse(_texto_do_zip(conteudo))


def acoes_a_vista(df, apenas_lote_padrao=False):
    """Recorte de acoes negociadas a vista (TPMERC 010), sem fracionario.

    apenas_lote_padrao=True (CODBDI 02) serve para o universo investivel;
    False mantem tambem RJ/concordata/intervencao para a serie de precos nao sumir.
    """
    codigos = CODBDI_UNIVERSO if apenas_lote_padrao else CODBDI_ACOES_SERIE
    m = (df["tpmerc"] == "010") & (df["codbdi"].isin(codigos))
    return df[m].copy()


# ─────────────────────────────────────────────────────────────
# Download e banco
# ─────────────────────────────────────────────────────────────
def caminho_bruto(ano):
    return os.path.join(DIR_BRUTOS, "cotahist", f"COTAHIST_A{ano}.ZIP")


def baixar_anual(ano, forcar=False):
    """Baixa o ZIP anual (mantem o bruto em dados_brutos/cotahist). O ano corrente e
    rebaixado sempre que forcar=True ou quando o arquivo local tem mais de 1 dia."""
    destino = caminho_bruto(ano)
    if os.path.exists(destino) and not forcar:
        if ano < date.today().year:
            return destino
    r = http_get(URL_ANUAL.format(ano=ano), timeout=600)
    if r is None or len(r.content) < 1000:
        log(f"cotahist {ano}: download falhou")
        return destino if os.path.exists(destino) else None
    gravar_atomico(destino, r.content)
    log(f"cotahist {ano}: {len(r.content)/1e6:.1f} MB")
    return destino


def baixar_diario(dia):
    """ZIP diario COTAHIST_Dddmmaaaa; None em feriado/ainda nao publicado."""
    r = http_get(URL_DIARIO.format(ddmmaaaa=dia.strftime("%d%m%Y")), timeout=120)
    if r is None or len(r.content) < 100:
        return None
    return r.content


def caminho_parquet(ano):
    return os.path.join(DIR_BANCO, "cotacoes_diarias", f"ano={ano}", "parte.parquet")


def gravar_ano(df, ano):
    """Grava as acoes a vista (todos os CODBDI de acao) do ano em parquet, sem duplicatas."""
    d = acoes_a_vista(df, apenas_lote_padrao=False)
    d = d.sort_values(["data", "ticker"]).drop_duplicates(["data", "ticker"], keep="last")
    destino = caminho_parquet(ano)
    garantir_dir(os.path.dirname(destino))
    d.to_parquet(destino, index=False)
    return len(d)


def atualizar(anos):
    """Baixa (se preciso) e converte cada ano para parquet. Devolve {ano: linhas}."""
    out = {}
    for ano in anos:
        zip_local = baixar_anual(ano)
        if not zip_local:
            out[ano] = None
            continue
        with open(zip_local, "rb") as f:
            df = parse_zip(f.read())
        out[ano] = gravar_ano(df, ano)
        log(f"cotahist {ano}: {out[ano]} registros de acoes a vista")
    return out


def carregar(ano_ini, ano_fim, tickers=None, colunas=None):
    partes = []
    for ano in range(ano_ini, ano_fim + 1):
        p = caminho_parquet(ano)
        if os.path.exists(p):
            df = pd.read_parquet(p, columns=colunas)
            if tickers is not None:
                df = df[df["ticker"].isin(set(tickers))]
            partes.append(df)
    if not partes:
        return pd.DataFrame()
    return pd.concat(partes, ignore_index=True)


def montar_registro(campos):
    """Monta uma linha de 245 caracteres a partir de um dict (para fixtures e testes).
    Numericos sao alinhados a direita com zeros; textos a esquerda com espacos."""
    linha = [" "] * TAMANHO_REGISTRO
    for nome, ini, fim in LAYOUT:
        v = campos.get(nome, "")
        largura = fim - ini
        if nome in CAMPOS_PRECO or nome in CAMPOS_INTEIRO or nome in ("ptoexe", "tipreg"):
            s = str(v).rjust(largura, "0")[-largura:]
        else:
            s = str(v).ljust(largura)[:largura]
        linha[ini:fim] = list(s)
    return "".join(linha)


def _anos(expr):
    if "-" in expr:
        a, b = expr.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in expr.split(",")]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Baixa o COTAHIST e monta o parquet de cotacoes diarias")
    ap.add_argument("--anos", default=f"2005-{date.today().year}", help="ex.: 2005-2026 ou 2024,2025")
    args = ap.parse_args(argv)
    res = atualizar(_anos(args.anos))
    falhas = [a for a, n in res.items() if n is None]
    print(res)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
