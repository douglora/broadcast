"""
Arquivador diario de dados publicos da B3 e da CVM que a fonte NAO guarda (M0).

Por que existe: a B3 mantem o negocio-a-negocio (tickercsv) por ~20 pregoes e as
tabelas de aluguel do BDI por <= 21 dias; a composicao dos indices so existe como
"carteira do dia"; e o IPE da CVM nao traz hora de entrega. Cada dia sem arquivo e
um buraco permanente no historico. Este script roda uma vez por pregao (cron apos
21:00 BRT, quando o COTAHIST_D ja saiu e as tabelas do BDI de D-1 estao publicadas)
e grava tudo comprimido em quant/dados_brutos/<fonte>/<data>/.

Fontes:
  bdi       BTBLoanBalance, BTBLendingOpenPosition, BTBTrade (aluguel) e
            SharesInvesVolum (fluxo por investidor), referencia D-1
  negocios  tickercsv de D: barras de 1 minuto por ticker (OHLCV + VWAP + n) para
            todos os papeis e ticks brutos apenas para o universo (se houver lista)
  indices   carteira do dia e previa quadrimestral de IBOV, SMLL, IDIV, IBRA
  ipe       fatos relevantes/comunicados novos, com timestamp de captura

Uso:  python -m quant.dados.arquivar_b3 [--data AAAA-MM-DD] [--fontes bdi,negocios,indices,ipe]
                                        [--saida DIR] [--universo arquivo.txt]
Sai com codigo 1 se alguma fonte falhou (mas tenta todas). Imprime um resumo JSON.
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import zipfile
from datetime import timedelta

import pandas as pd

from quant.comum import (DIR_BRUTOS, DIR_QUANT, agora_brt, agora_iso, gravar_gzip, gravar_json,
                         http_get, http_post_json, json_b3, ler_gzip, ler_json, log, payload_b3)
from quant.dados import calendario

URL_BDI_CSV = "https://arquivos.b3.com.br/bdi/table/export/csv?lang=pt-BR"
URL_BDI_JSON = "https://arquivos.b3.com.br/bdi/table/{tabela}/{ini}/{fim}/{pagina}/{tamanho}"
URL_NEGOCIOS = "https://arquivos.b3.com.br/apinegocios/tickercsv/{data}"
URL_INDICE = "https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/{metodo}/{payload}"
URL_IPE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{ano}.csv"

TABELAS_BDI = ("BTBLoanBalance", "BTBLendingOpenPosition", "BTBTrade", "SharesInvesVolum")
INDICES = ("IBOV", "SMLL", "IDIV", "IBRA")
ARQ_IPE_VISTOS = os.path.join(DIR_BRUTOS, "ipe", "protocolos_vistos.json")


# ─────────────────────────────────────────────────────────────
# Parsers puros (testaveis sem rede)
# ─────────────────────────────────────────────────────────────
def decodificar(b):
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("latin-1", errors="replace")


def ler_csv_b3(conteudo, sep=";"):
    """CSV da B3/CVM: ';', latin-1 ou utf-8, virgula decimal, as vezes com linhas de
    status antes do cabecalho. Devolve DataFrame de strings (conversao fica para quem usa)."""
    texto = decodificar(conteudo) if isinstance(conteudo, bytes) else conteudo
    linhas = texto.splitlines()
    inicio = 0
    for i, l in enumerate(linhas[:20]):
        if l.count(sep) >= 2:
            inicio = i
            break
    corpo = "\n".join(linhas[inicio:])
    if not corpo.strip():
        return pd.DataFrame()
    return pd.read_csv(io.StringIO(corpo), sep=sep, dtype=str, keep_default_na=False,
                       engine="python", on_bad_lines="skip")


_MILHAR = re.compile(r"^-?\d{1,3}(\.\d{3})+$")


def numero_br(s):
    """'1.234,56' -> 1234.56; '4.380.195.841' -> 4380195841; '1234.5' -> 1234.5; '' -> NaN.

    Regra: virgula e o decimal; pontos sao milhar quando ha virgula ou quando o texto
    tem o formato 1.234.567 (grupos de tres digitos). Um ponto seguido de 1-2 digitos
    ou de mais de 3 digitos e decimal (formato ja em ponto).
    """
    if s is None:
        return float("nan")
    s = str(s).strip()
    if not s:
        return float("nan")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif _MILHAR.match(s):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def _hora_minuto(ntry):
    """NtryTm vem como HHMMSSmmm (9 digitos) ou HH:MM:SS(.mmm). Devolve 'HH:MM'."""
    s = str(ntry).strip()
    if ":" in s:
        return s[:5]
    s = s.zfill(9)
    return f"{s[0:2]}:{s[2:4]}"


def barras_1min(df_ticks):
    """Agrega negocios (tickercsv) em barras de 1 minuto por ticker.

    Espera colunas TckrSymb, GrssTradAmt, TradQty, NtryTm e (opcional) TradgSsnId.
    Devolve DataFrame: ticker, minuto, abe, max, min, fec, qtd, financeiro, vwap, negocios.
    """
    if df_ticks.empty:
        return pd.DataFrame(columns=["ticker", "minuto", "abe", "max", "min", "fec",
                                     "qtd", "financeiro", "vwap", "negocios"])
    d = pd.DataFrame({
        "ticker": df_ticks["TckrSymb"].astype(str).str.strip(),
        "preco": df_ticks["GrssTradAmt"].map(numero_br),
        "qtd": pd.to_numeric(df_ticks["TradQty"], errors="coerce"),
        "minuto": df_ticks["NtryTm"].map(_hora_minuto),
    })
    if "UpdActn" in df_ticks.columns:            # 'delete' = negocio cancelado
        d = d[~df_ticks["UpdActn"].astype(str).str.lower().str.contains("del").values]
    d = d.dropna(subset=["preco", "qtd"])
    d["financeiro"] = d["preco"] * d["qtd"]
    g = d.groupby(["ticker", "minuto"], sort=True)
    out = g.agg(abe=("preco", "first"), max=("preco", "max"), min=("preco", "min"),
                fec=("preco", "last"), qtd=("qtd", "sum"), financeiro=("financeiro", "sum"),
                negocios=("preco", "size")).reset_index()
    out["vwap"] = out["financeiro"] / out["qtd"]
    return out[["ticker", "minuto", "abe", "max", "min", "fec", "qtd", "financeiro", "vwap", "negocios"]]


def normalizar_carteira(obj, indice, tipo):
    """JSON de GetPortfolioDay/GetQuartelyPreview -> linhas (indice, tipo, cod, asset, type, part, theoricalQty)."""
    linhas = []
    for r in obj.get("results", []) or []:
        linhas.append({
            "indice": indice, "tipo": tipo,
            "cod": str(r.get("cod", "")).strip(),
            "asset": str(r.get("asset", "")).strip(),
            "type": str(r.get("type", "")).strip(),
            "part": numero_br(r.get("part", "")),
            "theoricalQty": numero_br(r.get("theoricalQty", "")),
        })
    return pd.DataFrame(linhas)


def filtrar_ipe_novos(df, vistos):
    """Mantem so os documentos cujo Protocolo_Entrega ainda nao foi visto."""
    if df.empty or "Protocolo_Entrega" not in df.columns:
        return df.iloc[0:0]
    mask = ~df["Protocolo_Entrega"].astype(str).isin(set(map(str, vistos)))
    return df[mask].copy()


def resumo_aluguel(df):
    """Conta linhas 'com negocio' na tabela de aluguel (a B3 repete taxa sem contrato)."""
    if df.empty:
        return {"linhas": 0, "com_contrato": 0}
    col = next((c for c in df.columns if "contrat" in c.lower() or "contract" in c.lower()), None)
    if col is None:
        return {"linhas": int(len(df)), "com_contrato": None}
    n = int((df[col].map(numero_br).fillna(0) > 0).sum())
    return {"linhas": int(len(df)), "com_contrato": n}


# ─────────────────────────────────────────────────────────────
# Coletores (rede)
# ─────────────────────────────────────────────────────────────
def _destino(saida, fonte, data, nome):
    return os.path.join(saida, fonte, str(data), nome)


def arquivar_bdi(data, saida, tabelas=TABELAS_BDI):
    """Tabelas do BDI para a data de referencia (normalmente D-1). Tenta o export CSV e,
    se falhar, as paginas JSON."""
    res = {}
    for tabela in tabelas:
        destino = _destino(saida, "bdi", data, f"{tabela}.csv.gz")
        if os.path.exists(destino):
            res[tabela] = {"status": "ja_existia"}
            continue
        corpo = {"Name": tabela, "Date": str(data), "FinalDate": str(data), "ClientId": "", "Filters": {}}
        r = http_post_json(URL_BDI_CSV, corpo)
        if r is not None and r.content and len(r.content) > 50:
            gravar_gzip(destino, r.content)
            df = ler_csv_b3(r.content)
            res[tabela] = {"status": "ok", "formato": "csv", **resumo_aluguel(df)}
            continue
        # fallback: JSON paginado
        paginas, pagina = [], 1
        while True:
            url = URL_BDI_JSON.format(tabela=tabela, ini=data, fim=data, pagina=pagina, tamanho=1000)
            rj = http_get(url)
            if rj is None:
                break
            try:
                obj = json_b3(rj.text)
            except Exception:
                break
            valores = obj.get("values") or obj.get("results") or obj.get("Values") or []
            if not valores:
                break
            paginas.extend(valores)
            total = (obj.get("page") or {}).get("totalPages") or obj.get("totalPages") or 1
            if pagina >= int(total):
                break
            pagina += 1
        if paginas:
            gravar_gzip(_destino(saida, "bdi", data, f"{tabela}.json.gz"), json.dumps(paginas, ensure_ascii=False))
            res[tabela] = {"status": "ok", "formato": "json", "linhas": len(paginas)}
        else:
            res[tabela] = {"status": "falhou"}
    return res


def _ler_zip_negocios(conteudo):
    """Devolve o texto do *.txt dentro do ZIP do tickercsv, ou None se vazio/feriado."""
    if not conteudo or len(conteudo) < 30:
        return None
    try:
        z = zipfile.ZipFile(io.BytesIO(conteudo))
    except zipfile.BadZipFile:
        return None
    nomes = [n for n in z.namelist() if n.lower().endswith((".txt", ".csv"))]
    if not nomes:
        return None
    return decodificar(z.read(nomes[0]))


def arquivar_negocios(data, saida, universo=None):
    """tickercsv de `data`: barras de 1 minuto para todos os papeis; ticks brutos so do universo."""
    destino = _destino(saida, "negocios", data, "barras1m.csv.gz")
    if os.path.exists(destino):
        return {"status": "ja_existia"}
    r = http_get(URL_NEGOCIOS.format(data=data), timeout=300)
    if r is None:
        return {"status": "falhou"}
    texto = _ler_zip_negocios(r.content)
    if texto is None:
        return {"status": "vazio (feriado ou ainda nao publicado)"}
    df = ler_csv_b3(texto)
    if df.empty or "TckrSymb" not in df.columns:
        return {"status": "formato_inesperado", "colunas": list(df.columns)[:10]}
    barras = barras_1min(df)
    gravar_gzip(destino, barras.to_csv(index=False, sep=";"))
    out = {"status": "ok", "negocios": int(len(df)), "tickers": int(barras["ticker"].nunique())}
    if universo:
        sel = df[df["TckrSymb"].astype(str).str.strip().isin(set(universo))]
        gravar_gzip(_destino(saida, "negocios", data, "ticks_universo.csv.gz"), sel.to_csv(index=False, sep=";"))
        out["ticks_universo"] = int(len(sel))
    return out


def _paginas_indice(metodo, indice):
    """Percorre as paginas do proxy de indices e devolve o JSON com todos os results."""
    todos, pagina = [], 1
    cabecalho = {}
    while True:
        payload = payload_b3({"pageNumber": pagina, "pageSize": 120, "language": "pt-br",
                              "index": indice, "segment": "1"})
        r = http_get(URL_INDICE.format(metodo=metodo, payload=payload))
        if r is None:
            return None
        try:
            obj = json_b3(r.text)
        except Exception:
            return None
        todos.extend(obj.get("results", []) or [])
        cabecalho = obj.get("header", {}) or cabecalho
        total = int((obj.get("page") or {}).get("totalPages") or 1)
        if pagina >= total:
            break
        pagina += 1
    return {"header": cabecalho, "results": todos}


def arquivar_indices(data, saida, indices=INDICES):
    res = {}
    linhas = []
    for indice in indices:
        for metodo, tipo in (("GetPortfolioDay", "carteira"), ("GetQuartelyPreview", "previa")):
            destino = _destino(saida, "indices", data, f"{indice}_{tipo}.json.gz")
            if os.path.exists(destino):
                res[f"{indice}/{tipo}"] = {"status": "ja_existia"}
                continue
            obj = _paginas_indice(metodo, indice)
            if obj is None:
                res[f"{indice}/{tipo}"] = {"status": "falhou"}
                continue
            gravar_gzip(destino, json.dumps(obj, ensure_ascii=False))
            df = normalizar_carteira(obj, indice, tipo)
            linhas.append(df)
            res[f"{indice}/{tipo}"] = {"status": "ok", "ativos": int(len(df))}
    if linhas:
        gravar_gzip(_destino(saida, "indices", data, "carteiras.csv.gz"),
                    pd.concat(linhas, ignore_index=True).to_csv(index=False, sep=";"))
    return res


def arquivar_ipe(data, saida):
    """Baixa o IPE do ano e guarda so os documentos novos, com a hora em que foram vistos."""
    ano = int(str(data)[:4])
    r = http_get(URL_IPE.format(ano=ano), timeout=120)
    if r is None:
        return {"status": "falhou"}
    df = ler_csv_b3(r.content)
    if df.empty:
        return {"status": "vazio"}
    vistos = ler_json(ARQ_IPE_VISTOS, {"protocolos": []})["protocolos"]
    novos = filtrar_ipe_novos(df, vistos)
    novos["capturado_em"] = agora_iso()
    carimbo = agora_brt().strftime("%Y-%m-%dT%H%M")
    if not novos.empty:
        gravar_gzip(_destino(saida, "ipe", data, f"novos_{carimbo}.csv.gz"), novos.to_csv(index=False, sep=";"))
    vistos = list(dict.fromkeys(list(map(str, vistos)) + novos["Protocolo_Entrega"].astype(str).tolist()))[-200000:]
    gravar_json(os.path.join(saida, "ipe", "protocolos_vistos.json"), {"protocolos": vistos})
    return {"status": "ok", "novos": int(len(novos)), "total_no_ano": int(len(df))}


def carregar_universo(caminho):
    if not caminho:
        return None
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return [l.strip().upper() for l in f if l.strip() and not l.startswith("#")]
    except FileNotFoundError:
        log(f"universo nao encontrado: {caminho}")
        return None


def rodar(data=None, saida=DIR_BRUTOS, fontes=("bdi", "negocios", "indices", "ipe"), universo=None):
    hoje = agora_brt().date()
    data = calendario.ultimo_pregao_ate(data or hoje)
    ref_bdi = calendario.pregao_anterior(data) if data == hoje else data
    resumo = {"data": str(data), "referencia_bdi": str(ref_bdi), "rodado_em": agora_iso(), "fontes": {}}
    if "bdi" in fontes:
        resumo["fontes"]["bdi"] = arquivar_bdi(ref_bdi, saida)
    if "negocios" in fontes:
        resumo["fontes"]["negocios"] = arquivar_negocios(data, saida, universo)
        # se o de hoje ainda nao saiu, garante o do pregao anterior (retencao curta)
        if resumo["fontes"]["negocios"].get("status", "").startswith(("vazio", "falhou")):
            resumo["fontes"]["negocios_anterior"] = arquivar_negocios(calendario.pregao_anterior(data), saida, universo)
    if "indices" in fontes:
        resumo["fontes"]["indices"] = arquivar_indices(data, saida)
    if "ipe" in fontes:
        resumo["fontes"]["ipe"] = arquivar_ipe(data, saida)
    gravar_json(os.path.join(saida, "resumos", f"{data}.json"), resumo)
    return resumo


def _falhou(resumo):
    def caminhar(x):
        if isinstance(x, dict):
            if x.get("status") == "falhou":
                return True
            return any(caminhar(v) for v in x.values())
        return False
    return caminhar(resumo["fontes"])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Arquiva dados publicos da B3/CVM de retencao curta")
    ap.add_argument("--data", default=None, help="pregao de referencia (padrao: ultimo pregao ate hoje)")
    ap.add_argument("--saida", default=DIR_BRUTOS)
    ap.add_argument("--fontes", default="bdi,negocios,indices,ipe")
    ap.add_argument("--universo", default=os.path.join(DIR_QUANT, "universo_atual.txt"),
                    help="lista de tickers (um por linha) para guardar ticks brutos")
    args = ap.parse_args(argv)
    resumo = rodar(args.data, args.saida, tuple(args.fontes.split(",")), carregar_universo(args.universo))
    print(json.dumps(resumo, ensure_ascii=False, indent=2))
    return 1 if _falhou(resumo) else 0


if __name__ == "__main__":
    sys.exit(main())
