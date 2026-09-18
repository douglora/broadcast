"""Carrega config/livro.yaml e responde perguntas sobre o universo: ativos por
bloco, simbolo Yahoo <-> id, nome por extenso, parametros por ativo, curvas,
pares e benchmarks. Tudo que a tabela e as regras precisam saber sobre 'o que
e cada coisa' passa por aqui."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from livro import CONFIG_DIR

CLASSES = {"etf", "acao", "fx", "indice", "commodity", "cripto"}


def nome_seguro(simbolo: str) -> str:
    """Simbolo Yahoo -> nome de arquivo (^BVSP -> _BVSP, USDBRL=X -> USDBRL_X)."""
    return "".join(c if (c.isalnum() or c in ".-") else "_" for c in simbolo)


@dataclass
class Ativo:
    id: str
    nome: str
    apelido: str
    bloco: str
    classe: str
    yahoo: str
    moeda: str
    mercado: str
    isin: str | None = None
    benchmark: str | None = None
    nota: str = ""
    o_que_negocia: str = ""
    ativo: bool = True
    proxy: bool = False
    decimais: int | None = None
    params: dict = field(default_factory=dict)

    @property
    def arquivo(self) -> str:
        return nome_seguro(self.yahoo)

    def param(self, chave: str, padrao: Any = None) -> Any:
        return self.params.get(chave, padrao)


@dataclass
class Benchmark:
    id: str
    nome: str
    yahoo: str
    mercado: str
    moeda: str

    @property
    def arquivo(self) -> str:
        return nome_seguro(self.yahoo)


class Universo:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.blocos: list[dict] = cfg.get("blocos", [])
        self.ativos: list[Ativo] = []
        campos = {"id", "nome", "apelido", "bloco", "classe", "yahoo", "moeda", "mercado",
                  "isin", "benchmark", "nota", "o_que_negocia", "ativo", "proxy", "decimais"}
        for a in cfg.get("ativos", []):
            base = {k: v for k, v in a.items() if k in campos}
            params = {k: v for k, v in a.items() if k not in campos}
            at = Ativo(**base, params=params)
            if at.classe not in CLASSES:
                raise ValueError(f"classe desconhecida em {at.id}: {at.classe}")
            self.ativos.append(at)
        self.benchmarks: list[Benchmark] = [Benchmark(**b) for b in cfg.get("benchmarks", [])]
        self.pares: list[dict] = cfg.get("pares", [])
        self.curvas: dict = cfg.get("curvas", {})
        self.proxies: dict = cfg.get("proxies", {})
        self.sugestoes: list[dict] = cfg.get("sugestoes_ucits", [])
        self._por_id = {a.id: a for a in self.ativos}
        self._bench_por_id = {b.id: b for b in self.benchmarks}
        self._por_yahoo = {a.yahoo: a for a in self.ativos}
        for b in self.benchmarks:
            self._por_yahoo.setdefault(b.yahoo, b)

    # --- consultas ---
    def por_bloco(self, bloco: str, so_ativos: bool = True) -> list[Ativo]:
        return [a for a in self.ativos if a.bloco == bloco and (a.ativo or not so_ativos)]

    def por_id(self, id_: str) -> Ativo | None:
        return self._por_id.get(id_)

    def bench(self, id_: str) -> Benchmark | None:
        return self._bench_por_id.get(id_)

    def por_yahoo(self, simbolo: str):
        return self._por_yahoo.get(simbolo)

    def serie_id(self, id_: str):
        """Ativo ou benchmark pelo id (para pares e forca relativa)."""
        return self._por_id.get(id_) or self._bench_por_id.get(id_)

    def simbolos_yahoo(self, incluir_benchmarks: bool = True) -> list[str]:
        out = [a.yahoo for a in self.ativos if a.ativo]
        if incluir_benchmarks:
            out += [b.yahoo for b in self.benchmarks]
        vistos, uniq = set(), []
        for s in out:
            if s not in vistos:
                vistos.add(s)
                uniq.append(s)
        return uniq

    def ucits(self) -> list[Ativo]:
        return self.por_bloco("ucits")

    def titulo_bloco(self, bloco: str) -> str:
        for b in self.blocos:
            if b["id"] == bloco:
                return b.get("titulo", bloco)
        return bloco

    def para_json(self) -> dict:
        """Copia renderizada para o branch dados (a sessao le sem precisar da main)."""
        return {
            "versao": self.cfg.get("versao"),
            "atualizado_em": self.cfg.get("atualizado_em"),
            "blocos": self.blocos,
            "ativos": [{
                "id": a.id, "nome": a.nome, "apelido": a.apelido, "bloco": a.bloco,
                "classe": a.classe, "yahoo": a.yahoo, "moeda": a.moeda, "mercado": a.mercado,
                "isin": a.isin, "benchmark": a.benchmark, "nota": a.nota,
                "o_que_negocia": a.o_que_negocia, "ativo": a.ativo, "proxy": a.proxy,
            } for a in self.ativos],
            "benchmarks": [b.__dict__ for b in self.benchmarks],
            "pares": self.pares,
            "curvas": self.curvas,
            "proxies": self.proxies,
            "sugestoes_ucits": self.sugestoes,
        }


def carregar(caminho: str | None = None) -> Universo:
    caminho = caminho or os.path.join(CONFIG_DIR, "livro.yaml")
    with open(caminho, encoding="utf-8") as f:
        return Universo(yaml.safe_load(f))


def carregar_yaml(nome: str) -> dict:
    with open(os.path.join(CONFIG_DIR, nome), encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def normalizar_ticker(texto: str) -> str:
    """'KLNB4' -> 'KLBN4', 'AMZ' -> 'AMZN', 'BOFA' -> 'BAC', 'SML11' -> 'SMAL11'."""
    aliases = {"KLNB4": "KLBN4", "AMZ": "AMZN", "BOFA": "BAC", "SML11": "SMAL11",
               "ELET3": "AXIA3", "MELI": "MELI34"}
    t = re.sub(r"\.SA$", "", (texto or "").strip().upper())
    return aliases.get(t, t)


def gravar_json(caminho: str, dados: Any) -> None:
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, caminho)


def ler_json(caminho: str, padrao: Any = None) -> Any:
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return padrao
