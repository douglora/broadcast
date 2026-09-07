"""
CDI diario (M6b): serie 12 do SGS do Banco Central, com cache local e fallback no NEFIN.

Por que existe: o CDI e o adversario de qualquer estrategia de acoes para pessoa fisica
(README: "CDI -0,5 a +1,0 p.p." e o cenario base). Todo excesso de retorno, todo Sharpe e
todo criterio de kill e medido contra ele, entao ele precisa estar disponivel offline,
em decimal diario, alinhado ao calendario de pregoes, sem depender do app.py.

Fonte: https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados?formato=json
         &dataInicial=dd/mm/aaaa&dataFinal=dd/mm/aaaa
       -> [{"data": "02/01/2001", "valor": "0.056978"}, ...]   (valor em % AO DIA)

Armadilhas:
  - o valor vem em PORCENTAGEM ao dia (0.0570 = 0,057%/dia ~ 15,4% a.a.); aqui tudo e
    convertido para decimal (0.000570) para compor com (1 + r).prod();
  - a API recusa janelas maiores que ~10 anos em series diarias (HTTP 400 ou lista vazia):
    baixar() quebra o periodo em blocos de BLOCO_ANOS anos;
  - a API as vezes devolve o valor com virgula decimal ou repete datas: parse_json normaliza;
  - o SGS publica o CDI de D em D+1 de manha: a serie termina normalmente no pregao anterior;
  - cache em quant/dados_brutos/bcb/sgs12.csv.gz (CSV 'data;valor' com o valor COMO VEIO
    da API, para nao perder precisao; ';' porque a API ja mandou virgula decimal): e o
    bruto da fonte, nao um derivado; entradas sem valor nao sao guardadas;
  - sem rede (b3/bcb bloqueados nesta maquina), carregar() cai para o Risk_Free do NEFIN,
    que e a mesma taxa (CDI diario) mas com a data de disponibilidade do snapshot NEFIN.
    A origem fica em serie.attrs["fonte"] para o backtest registrar.
"""
import io
import json
import os
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from quant.comum import DIR_BRUTOS, garantir_dir, gravar_gzip, http_get, ler_gzip, log

SERIE_SGS = 12
URL_SGS = ("https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados"
           "?formato=json&dataInicial={ini}&dataFinal={fim}")
DIR = os.path.join(DIR_BRUTOS, "bcb")
ARQ_CACHE = os.path.join(DIR, f"sgs{SERIE_SGS}.csv.gz")
DATA_INICIAL = date(2001, 1, 2)     # inicio dos fatores NEFIN; o SGS 12 vai ate 1986 se precisar
BLOCO_ANOS = 9                      # a API limita a ~10 anos por chamada em serie diaria
DIAS_UTEIS_ANO = 252


# ─────────────────────────────────────────────────────────────
# Funcoes puras
# ─────────────────────────────────────────────────────────────
def _para_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return pd.Timestamp(d).date()


def _data_br(d):
    return _para_date(d).strftime("%d/%m/%Y")


def _serie_vazia():
    s = pd.Series(dtype=float, name="cdi")
    s.index = pd.DatetimeIndex([], name="data")
    return s


def parse_json(lista):
    """Lista de dicts da API ({"data": "dd/mm/aaaa", "valor": "0.0570"}) -> Series decimal
    diaria (0.000570) indexada por Timestamp, ordenada, sem datas repetidas (fica a ultima).
    Aceita tambem a string JSON crua. Entradas invalidas sao descartadas."""
    if isinstance(lista, (str, bytes)):
        try:
            lista = json.loads(lista)
        except Exception:
            return _serie_vazia()
    if not isinstance(lista, list) or not lista:
        return _serie_vazia()
    df = pd.DataFrame(lista)
    if "data" not in df.columns or "valor" not in df.columns:
        return _serie_vazia()
    datas = pd.to_datetime(df["data"].astype(str).str.strip(), format="%d/%m/%Y", errors="coerce")
    valores = pd.to_numeric(df["valor"].astype(str).str.strip().str.replace(",", ".", regex=False),
                            errors="coerce")
    s = pd.Series(valores.values / 100.0, index=datas, name="cdi")
    s = s[s.index.notna() & s.notna()]
    s = s[~s.index.duplicated(keep="last")].sort_index()
    s.index.name = "data"
    return s


def _somar_anos(d, anos):
    """d + anos, recuando 29/02 para 28/02 quando o ano destino nao e bissexto."""
    try:
        return date(d.year + anos, d.month, d.day)
    except ValueError:
        return date(d.year + anos, d.month, 28)


def _blocos(ini, fim, anos=BLOCO_ANOS):
    """Divide [ini, fim] em janelas de no maximo `anos` anos (limite da API).
    Lista vazia se ini > fim."""
    out = []
    a = ini
    while a <= fim:
        b = min(fim, _somar_anos(a, anos) - timedelta(days=1))
        out.append((a, b))
        a = b + timedelta(days=1)
    return out


def _recorte(serie, ini, fim):
    if serie is None or len(serie) == 0:
        return _serie_vazia()
    s = serie
    if ini is not None:
        s = s[s.index >= pd.Timestamp(_para_date(ini))]
    if fim is not None:
        s = s[s.index <= pd.Timestamp(_para_date(fim))]
    return s


def acumular(serie, ini=None, fim=None):
    """Fator acumulado prod(1 + r) no intervalo fechado [ini, fim]. 1.0 se nao houver dados."""
    s = _recorte(serie, ini, fim).dropna()
    if len(s) == 0:
        return 1.0
    return float(np.prod(1.0 + s.values))


def anualizar(serie, ini=None, fim=None, dias_ano=DIAS_UTEIS_ANO):
    """Taxa anual equivalente do periodo (base 252 dias uteis). NaN se nao houver dados."""
    s = _recorte(serie, ini, fim).dropna()
    if len(s) == 0:
        return float("nan")
    return float(acumular(s) ** (dias_ano / len(s)) - 1.0)


# ─────────────────────────────────────────────────────────────
# Cache (bruto, como veio da API)
# ─────────────────────────────────────────────────────────────
def _csv_do_bruto(lista):
    """CSV 'data;valor' (';' porque a API ja devolveu valor com virgula decimal)."""
    linhas = ["data;valor"]
    for item in lista:
        linhas.append(f"{item['data']};{item['valor']}")
    return "\n".join(linhas) + "\n"


def _ler_csv_cache(caminho):
    return pd.read_csv(io.BytesIO(ler_gzip(caminho)), dtype=str, sep=";", keep_default_na=False)


def ler_cache(caminho=ARQ_CACHE):
    """Series decimal diaria a partir do CSV gzip do cache; vazia se nao existir."""
    if not os.path.exists(caminho):
        return _serie_vazia()
    try:
        df = _ler_csv_cache(caminho)
    except Exception as e:
        log(f"cdi: cache ilegivel ({type(e).__name__}); ignorado")
        return _serie_vazia()
    return parse_json(df.to_dict("records"))


def gravar_cache(lista, caminho=ARQ_CACHE):
    """Funde a lista bruta da API com o cache existente (a ultima ocorrencia de cada data vence)."""
    atual = []
    if os.path.exists(caminho):
        try:
            atual = _ler_csv_cache(caminho).to_dict("records")
        except Exception:
            atual = []
    por_data = {}
    for item in list(atual) + list(lista):
        if not isinstance(item, dict):
            continue          # a API mudou de formato: nao contamina o cache
        d = pd.to_datetime(str(item.get("data", "")).strip(), format="%d/%m/%Y", errors="coerce")
        v = str(item.get("valor", "") if item.get("valor") is not None else "").strip()
        if pd.isna(d) or v == "" or v.lower() == "nan":
            continue          # data invalida ou valor vazio: nao vale guardar
        por_data[d] = {"data": d.strftime("%d/%m/%Y"), "valor": v}
    ordenado = [por_data[k] for k in sorted(por_data)]
    garantir_dir(os.path.dirname(caminho))
    gravar_gzip(caminho, _csv_do_bruto(ordenado))
    return len(ordenado)


# ─────────────────────────────────────────────────────────────
# Rede
# ─────────────────────────────────────────────────────────────
def baixar(ini=DATA_INICIAL, fim=None, caminho=ARQ_CACHE):
    """Baixa o SGS 12 em blocos e atualiza o cache. Devolve a Series baixada ou None se
    nenhum bloco veio (sem rede). Blocos parciais sao gravados mesmo assim."""
    ini = _para_date(ini)
    fim = _para_date(fim) or date.today()
    if ini > fim:
        return None
    brutos = []
    for a, b in _blocos(ini, fim):
        r = http_get(URL_SGS.format(serie=SERIE_SGS, ini=_data_br(a), fim=_data_br(b)),
                     timeout=60, tentativas=2, headers={"Accept": "application/json"})
        if r is None:
            log(f"cdi: bloco {a}..{b} falhou")
            continue
        try:
            lista = r.json()
        except Exception:
            log(f"cdi: bloco {a}..{b} nao e JSON")
            continue
        if isinstance(lista, list):
            brutos.extend(lista)
    if not brutos:
        return None
    n = gravar_cache(brutos, caminho)
    s = parse_json(brutos)
    log(f"cdi: {len(s)} dias baixados ({s.index.min().date()}..{s.index.max().date()}); cache com {n}")
    return s


def fallback_nefin():
    """Risk_Free do snapshot NEFIN local (mesma taxa, ja em decimal diario). None se nao houver."""
    try:
        from quant.dados import nefin
        f = nefin.carregar_fatores()
    except Exception as e:
        log(f"cdi: sem snapshot NEFIN para fallback ({type(e).__name__})")
        return None
    s = f["Risk_Free"].astype(float).copy()
    s.name = "cdi"
    s.index = pd.DatetimeIndex(s.index, name="data")
    s.attrs["fonte"] = "nefin"
    s.attrs["avail_date"] = f.attrs.get("pin", {}).get("avail_date")
    return s


def carregar(ini=None, fim=None, caminho=ARQ_CACHE, permitir_rede=True, dias_tolerancia=5):
    """Series decimal diaria do CDI. Ordem: cache -> rede (so o que falta) -> NEFIN Risk_Free.

    Devolve None apenas se nenhuma das tres fontes existir. attrs["fonte"] diz de onde veio
    ("bcb" ou "nefin"). dias_tolerancia: quantos dias corridos o cache pode estar defasado
    antes de tentar completar pela rede."""
    s = ler_cache(caminho)
    fim_pedido = _para_date(fim) or date.today()
    ini_pedido = _para_date(ini) or DATA_INICIAL
    if permitir_rede:
        falta_ini = len(s) == 0 or s.index.min().date() > ini_pedido
        falta_fim = len(s) == 0 or s.index.max().date() < fim_pedido - timedelta(days=dias_tolerancia)
        if falta_ini or falta_fim:
            # so o que falta: a frente (ate a vespera do cache) e/ou o fim (do dia seguinte ao cache)
            a = ini_pedido if falta_ini else s.index.max().date() + timedelta(days=1)
            b = min(fim_pedido, date.today())
            if falta_ini and not falta_fim:
                b = min(b, s.index.min().date() - timedelta(days=1))
            if a <= b and baixar(a, b, caminho) is not None:
                s = ler_cache(caminho)
    if len(s) == 0:
        log("cdi: sem cache e sem rede; usando Risk_Free do NEFIN como CDI (aviso)")
        s = fallback_nefin()
        if s is None:
            return None
        return _recorte(s, ini, fim).rename("cdi").pipe(_com_attrs, s.attrs)
    out = _recorte(s, ini, fim)
    out.attrs["fonte"] = "bcb"
    return out


def _com_attrs(serie, attrs):
    serie.attrs.update(attrs)
    return serie


if __name__ == "__main__":
    s = carregar()
    if s is None:
        print("CDI indisponivel")
    else:
        print(s.attrs.get("fonte"), s.index.min().date(), s.index.max().date(), len(s),
              f"ultimos 252 dias: {anualizar(s.iloc[-252:]):.2%} a.a.")
