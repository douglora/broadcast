"""Cliente fino para a API do servidor BROADCAST (The Invest Post).

O servidor (app.py) roda na máquina do administrador e é exposto via ngrok ou
Cloudflare Tunnel. Aqui só consumimos os endpoints que o front (index.html) já
usa, então nada de novo precisa ser construído no backend.
"""
from __future__ import annotations

import time
from typing import Any


class BroadcastClient:
    def __init__(self, base_url: str, timeout: float = 10.0, retries: int = 2):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries

    def _get(self, path: str, params: dict | None = None) -> Any:
        import requests  # import tardio: só necessário quando há rede de verdade

        url = self.base_url + path
        last = None
        for attempt in range(self.retries + 1):
            try:
                r = requests.get(url, params=params, timeout=self.timeout)
                r.raise_for_status()
                return r.json()
            except Exception as e:  # rede instável / endpoint fora do ar
                last = e
                if attempt < self.retries:
                    time.sleep(2 ** attempt)
        raise RuntimeError(f"Falha ao buscar {path}: {last}")

    # Endpoints sem argumento ------------------------------------------------
    def quotes(self):          return self._get("/api/quotes")
    def indicators(self):      return self._get("/api/indicators")
    def di(self):              return self._get("/api/di")
    def alerts(self):          return self._get("/api/alerts")
    def cvm(self):             return self._get("/api/cvm")
    def weekly_summary(self):  return self._get("/api/weekly_summary")
    def watchlist(self):       return self._get("/api/watchlist")
    def tir_all(self):         return self._get("/api/tir/all")

    # Endpoints com argumento ------------------------------------------------
    def statusinvest(self, ticker: str, type_: str = "acao_br"):
        return self._get("/api/statusinvest", {"ticker": ticker, "type": type_})

    def asset(self, ticker: str, period: str = "1mo"):
        return self._get("/api/asset", {"ticker": ticker, "period": period})
