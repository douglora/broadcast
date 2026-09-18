"""Contrato das regras: Alerta, Contexto, Estado e a classe base Regra."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

SEVERIDADES = ("info", "atencao", "critico")
ROTULO = {"info": "[INFO]", "atencao": "[ATENÇÃO]", "critico": "[CRÍTICO]"}


@dataclass
class Alerta:
    regra: str
    ativo: str
    severidade: str
    familia: str            # preco | curva | cambio | commodity | cripto | regime | sistema
    titulo: str             # linha 1, sem o rotulo de severidade
    tag: str = ""           # parte do id (perda, retomada, nivel_7.0, -20 ...)
    data: str = ""          # data do gatilho (iso)
    corpo: list = field(default_factory=list)   # linhas de contexto numerico
    por_que: str = ""
    como_falar: str = ""
    anula: str = ""
    fonte: str = ""
    ativos_afetados: str = ""
    dados: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        partes = [self.regra, self.ativo, self.tag or "x", self.data or "s-d"]
        return "-".join(p.replace(" ", "_") for p in partes)

    @property
    def rotulo(self) -> str:
        return ROTULO.get(self.severidade, "[INFO]")

    def texto(self, com_rotulo: bool = True) -> str:
        linhas = [f"{self.rotulo} {self.regra} · {self.titulo}" if com_rotulo else f"{self.regra} · {self.titulo}"]
        linhas += [l for l in self.corpo if l]
        if self.por_que:
            linhas.append(f"Por que importa: {self.por_que}")
        if self.ativos_afetados:
            linhas.append(f"Ativos: {self.ativos_afetados}")
        if self.como_falar:
            linhas.append(f"Como falar: '{self.como_falar}'")
        if self.anula:
            linhas.append(f"Anula/Confirma: {self.anula}")
        if self.fonte:
            linhas.append(f"Fonte: {self.fonte}")
        return "\n".join(linhas)

    def linha_curta(self) -> str:
        return f"{self.rotulo} {self.regra} {self.titulo}"

    def para_json(self) -> dict:
        return {"id": self.id, "regra": self.regra, "ativo": self.ativo, "severidade": self.severidade,
                "familia": self.familia, "titulo": self.titulo, "tag": self.tag, "data": self.data,
                "corpo": self.corpo, "por_que": self.por_que, "como_falar": self.como_falar,
                "anula": self.anula, "fonte": self.fonte, "ativos_afetados": self.ativos_afetados,
                "dados": self.dados, "texto": self.texto()}


class Estado:
    """Dicionario persistido (livro/estado/regras_estado.json) com helpers de cooldown."""

    def __init__(self, dados: dict | None = None):
        self.d: dict = dados or {}

    def get(self, chave: str, padrao: Any = None) -> Any:
        return self.d.get(chave, padrao)

    def set(self, chave: str, valor: Any) -> None:
        self.d[chave] = valor

    def marcar(self, chave: str, data: str, **extra) -> None:
        self.d[chave] = {"data": data, **extra}

    def ultima_data(self, chave: str) -> str | None:
        v = self.d.get(chave)
        return v.get("data") if isinstance(v, dict) else None

    def em_cooldown(self, chave: str, datas: list[str], sessoes: int) -> bool:
        """True se o ultimo disparo (por data) esta a menos de `sessoes` barras da ultima barra."""
        ult = self.ultima_data(chave)
        if not ult:
            return False
        return sessoes_desde(datas, ult) < sessoes


def sessoes_desde(datas: list[str], data_iso: str) -> int:
    """Quantas barras existem depois de data_iso (0 se data_iso e a ultima)."""
    n = 0
    for d in reversed(datas):
        if d <= data_iso:
            break
        n += 1
    return n


@dataclass
class Contexto:
    universo: Any
    limiares: dict
    hoje: date                       # dia util B3 de referencia
    slot: str = "fechamento"         # intradia | fechamento | manha
    series: dict = field(default_factory=dict)      # id -> DataFrame (open high low close adj volume)
    series_info: dict = field(default_factory=dict) # id -> {data_ultima, reaproveitada, ...}
    curvas: dict = field(default_factory=dict)      # di, tesouro, ust (dicts crus)
    macro: dict = field(default_factory=dict)       # bcb, focus, proxies
    regime: dict = field(default_factory=dict)      # preenchido por T13
    eventos: dict = field(default_factory=dict)     # noticias, cvm, sec, config (fontes_noticias.yaml)
    falhas: dict = field(default_factory=dict)      # perna -> motivo
    agora_iso: str = ""

    def serie(self, id_: str) -> pd.DataFrame | None:
        return self.series.get(id_)

    def lim(self, regra: str, chave: str, padrao: Any = None) -> Any:
        return (self.limiares.get(regra) or {}).get(chave, padrao)

    def ativo(self, id_: str):
        return self.universo.por_id(id_)

    def nome(self, id_: str) -> str:
        a = self.universo.por_id(id_)
        return a.nome if a else id_

    def rotulo(self, id_: str) -> str:
        """'BBDC4' ou, para UCITS, 'VWRA (Vanguard FTSE All-World UCITS ETF USD Accumulating)'."""
        a = self.universo.por_id(id_)
        if a and a.bloco == "ucits":
            return f"{a.id} ({a.nome})"
        return id_

    def moeda_simbolo(self, id_: str) -> str:
        a = self.universo.por_id(id_)
        if not a:
            return ""
        return {"BRL": "R$ ", "USD": "US$ "}.get(a.moeda, "")

    def fresco(self, id_: str, max_dias: int = 1) -> bool:
        """Serie com barra do ultimo pregao esperado do mercado do ativo."""
        info = self.series_info.get(id_) or {}
        return bool(info.get("fresco", True))


class Regra:
    id = "R00"
    familia = "preco"
    fase = "v1"

    def avaliar(self, ctx: Contexto, estado: Estado) -> list[Alerta]:  # pragma: no cover
        return []
