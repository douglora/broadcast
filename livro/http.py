"""Cliente HTTP do runner: impressao digital de navegador quando ha curl_cffi,
fallback para requests, e rodadas de retry so para 429/5xx/rede.

Receita herdada do coletor Yahoo do tracknews: em 03/09/2026 um runner do
GitHub recebeu HTTP 429 em 45 series em menos de 3 s; minutos depois outro
runner recebeu 200 em tudo. Por isso (1) sessao com impersonate='chrome',
(2) repetir so os itens que falharam por limite ou rede, com espera, e
(3) registrar o codigo HTTP de cada falha.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8",
}
RETRY_PAUSES = (20.0, 45.0)
RETRYABLE = {429, 500, 502, 503, 504}
TIMEOUT = 25


class HttpError(Exception):
    """Resposta fora de 2xx, com codigo e comeco do corpo."""

    def __init__(self, status: int, body: str = "", url: str = ""):
        super().__init__(f"HTTP {status} em {url[:80]}")
        self.status = status
        self.body = body[:200]
        self.url = url

    @property
    def retryable(self) -> bool:
        return self.status in RETRYABLE


@dataclass
class Resposta:
    status: int
    content: bytes
    headers: dict = field(default_factory=dict)
    url: str = ""

    @property
    def text(self) -> str:
        try:
            return self.content.decode("utf-8")
        except UnicodeDecodeError:
            return self.content.decode("latin-1", errors="replace")

    def json(self) -> Any:
        import json
        return json.loads(self.content)


class Cliente:
    """GET com sessao de navegador (curl_cffi) ou requests. Nunca levanta por
    codigo HTTP: devolve Resposta; quem chama decide. Excecoes de rede viram
    HttpError(status=0)."""

    def __init__(self, impersonate: bool = True, timeout: int = TIMEOUT):
        self.timeout = timeout
        self.tipo = "requests"
        self._s = None
        if impersonate:
            try:
                from curl_cffi import requests as cr  # type: ignore
                self._s = cr.Session(impersonate="chrome", timeout=timeout)
                self.tipo = "curl_cffi"
            except Exception:
                self._s = None
        if self._s is None:
            import requests
            self._s = requests.Session()
            self._s.headers.update(HEADERS)

    def get(self, url: str, params: dict | None = None, headers: dict | None = None,
            timeout: int | None = None) -> Resposta:
        kw: dict = {}
        if params:
            kw["params"] = params
        if headers:
            kw["headers"] = {**HEADERS, **headers} if self.tipo == "requests" else headers
        kw["timeout"] = timeout or self.timeout
        try:
            r = self._s.get(url, **kw)
        except Exception as e:  # rede, TLS, timeout
            raise HttpError(0, f"{type(e).__name__}: {e}", url)
        hdrs = {}
        try:
            hdrs = {k.lower(): v for k, v in dict(r.headers).items()}
        except Exception:
            pass
        return Resposta(int(r.status_code), bytes(r.content), hdrs, str(getattr(r, "url", url)))

    def post(self, url: str, data: str | bytes | None = None, headers: dict | None = None,
             timeout: int | None = None) -> Resposta:
        kw: dict = {"timeout": timeout or self.timeout}
        if data is not None:
            kw["data"] = data
        if headers:
            kw["headers"] = {**HEADERS, **headers} if self.tipo == "requests" else headers
        try:
            r = self._s.post(url, **kw)
        except Exception as e:
            raise HttpError(0, f"{type(e).__name__}: {e}", url)
        hdrs = {}
        try:
            hdrs = {k.lower(): v for k, v in dict(r.headers).items()}
        except Exception:
            pass
        return Resposta(int(r.status_code), bytes(r.content), hdrs, str(getattr(r, "url", url)))

    def get_ok(self, url: str, **kw) -> Resposta:
        """GET que exige 2xx; levanta HttpError caso contrario."""
        r = self.get(url, **kw)
        if not 200 <= r.status < 300:
            raise HttpError(r.status, r.text, url)
        return r


def com_rodadas(fn: Callable[[Any], Any], itens: Iterable[Any],
                pausas: tuple = RETRY_PAUSES, dormir: Callable[[float], None] = time.sleep,
                espaco: float = 0.0) -> tuple[dict, dict]:
    """Aplica fn a cada item; repete os que falharam por 429/5xx/rede em rodadas
    com espera. Devolve (resultados, falhas) indexados pelo item. Falha que nao e
    retryable (404, parse) fica registrada na primeira rodada e nao repete."""
    resultados: dict = {}
    falhas: dict = {}
    pendentes = list(itens)
    rodada = 0
    while pendentes:
        proximos = []
        for item in pendentes:
            try:
                resultados[item] = fn(item)
                falhas.pop(item, None)
            except HttpError as e:
                falhas[item] = f"HTTP {e.status}" if e.status else f"rede: {e.body[:60]}"
                if e.retryable or e.status == 0:
                    proximos.append(item)
            except Exception as e:  # parse ou dado inesperado: nao repete
                falhas[item] = f"{type(e).__name__}: {str(e)[:80]}"
            if espaco:
                dormir(espaco)
        if not proximos or rodada >= len(pausas):
            break
        dormir(pausas[rodada])
        rodada += 1
        pendentes = proximos
    return resultados, falhas
