"""
Utilitarios compartilhados do pacote quant: caminhos, HTTP tolerante, log e escrita atomica.

Nao importa o app.py de proposito: os coletores precisam rodar em CI e em maquina
sem Flask. As funcoes seguem a mesma filosofia do terminal (nunca levantam excecao
de rede; devolvem None e registram no log).
"""
import base64
import gzip
import json
import os
import time
from datetime import datetime, timedelta, timezone

import requests

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # pasta do repositorio
DIR_QUANT = os.path.join(RAIZ, "quant")
DIR_BRUTOS = os.path.join(DIR_QUANT, "dados_brutos")   # arquivos como vieram da fonte (gzip)
DIR_BANCO = os.path.join(DIR_QUANT, "banco")           # parquet/sqlite derivados (gitignored)
DIR_SAIDA = os.path.join(DIR_QUANT, "saida")           # boletas, relatorios

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HTTP_TIMEOUT = 60
FUSO_BRT = timezone(timedelta(hours=-3))


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def agora_brt():
    return datetime.now(FUSO_BRT)


def agora_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def garantir_dir(caminho):
    os.makedirs(caminho, exist_ok=True)
    return caminho


def _sessao():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "*/*"})
    return s


SESSAO = _sessao()


def http_get(url, timeout=HTTP_TIMEOUT, headers=None, tentativas=3, espera=2.0, **kw):
    """GET tolerante: devolve o Response com status 200 ou None. Nunca levanta excecao.

    Repete em falha de rede e em 5xx; nao repete em 4xx (feriado na B3 costuma dar 400).
    """
    h = dict(headers or {})
    for i in range(tentativas):
        try:
            r = SESSAO.get(url, headers=h, timeout=timeout, **kw)
            if r.status_code == 200:
                return r
            log(f"HTTP {r.status_code} em {url[:110]}")
            if 400 <= r.status_code < 500:
                return None
        except Exception as e:
            log(f"falha em {url[:110]}: {type(e).__name__}")
        if i + 1 < tentativas:
            time.sleep(espera * (i + 1))
    return None


def http_post_json(url, corpo, timeout=HTTP_TIMEOUT, headers=None, tentativas=3, espera=2.0):
    """POST com corpo JSON, mesma tolerancia do http_get."""
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    for i in range(tentativas):
        try:
            r = SESSAO.post(url, data=json.dumps(corpo), headers=h, timeout=timeout)
            if r.status_code == 200:
                return r
            log(f"HTTP {r.status_code} em {url[:110]}")
            if 400 <= r.status_code < 500:
                return None
        except Exception as e:
            log(f"falha em {url[:110]}: {type(e).__name__}")
        if i + 1 < tentativas:
            time.sleep(espera * (i + 1))
    return None


def payload_b3(dicionario):
    """Os proxies da B3 (sistemaswebb3-listados) recebem o JSON em base64 na URL."""
    return base64.b64encode(json.dumps(dicionario, separators=(",", ":")).encode("utf-8")).decode("ascii")


def json_b3(texto):
    """A B3 as vezes devolve o JSON envolto em aspas (string JSON de um JSON)."""
    obj = json.loads(texto)
    if isinstance(obj, str):
        obj = json.loads(obj)
    return obj


def gravar_atomico(caminho, conteudo):
    """Grava bytes (ou str) num arquivo temporario e renomeia: nunca deixa arquivo pela metade."""
    garantir_dir(os.path.dirname(caminho))
    if isinstance(conteudo, str):
        conteudo = conteudo.encode("utf-8")
    tmp = caminho + ".tmp"
    with open(tmp, "wb") as f:
        f.write(conteudo)
    os.replace(tmp, caminho)
    return caminho


def gravar_gzip(caminho, conteudo):
    if isinstance(conteudo, str):
        conteudo = conteudo.encode("utf-8")
    return gravar_atomico(caminho, gzip.compress(conteudo, compresslevel=6))


def ler_gzip(caminho):
    with gzip.open(caminho, "rb") as f:
        return f.read()


def gravar_json(caminho, dados):
    return gravar_atomico(caminho, json.dumps(dados, ensure_ascii=False, indent=2))


def ler_json(caminho, padrao=None):
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return padrao
