"""Estado persistido no branch dados (livro/estado/): regras_estado.json (ultimo
lado/nivel/data por regra e ativo), alertas.json (fila com ack: pendente ->
entregue/expirado) e historico_alertas.jsonl (para o hit-rate mensal)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from livro.sinais.base import Alerta, Estado
from livro.universo import gravar_json, ler_json


def agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _inverso(s: str) -> tuple:
    """Chave que ordena strings ao contrario (mais recente primeiro)."""
    return tuple(-ord(c) for c in s)


class Repositorio:
    def __init__(self, raiz: str):
        self.raiz = raiz
        self.dir = os.path.join(raiz, "estado")
        os.makedirs(self.dir, exist_ok=True)
        self.regras = Estado(ler_json(os.path.join(self.dir, "regras_estado.json"), {}) or {})
        self.fila: dict = ler_json(os.path.join(self.dir, "alertas.json"), {}) or {}

    # ---- fila de alertas ----
    def registrar(self, alertas: list[Alerta], slot: str) -> list[Alerta]:
        """Entra na fila so quem nao existe (id deterministico). Devolve os novos."""
        novos = []
        for a in alertas:
            if a.id in self.fila:
                continue
            self.fila[a.id] = {**a.para_json(), "status": "pendente", "slot": slot, "gerado_em": agora_iso(),
                               "entregue_em": None, "reapresentado": 0}
            novos.append(a)
            self._historico(a, slot)
        return novos

    def marcar_entregues(self, ids: list[str]) -> int:
        n = 0
        for i in ids:
            i = i.strip()
            if i and i in self.fila and self.fila[i]["status"] != "entregue":
                self.fila[i]["status"] = "entregue"
                self.fila[i]["entregue_em"] = agora_iso()
                n += 1
        return n

    def pendentes(self, slot_atual: str | None = None) -> list[dict]:
        return [v for v in self.fila.values() if v.get("status") == "pendente"]

    def expirar(self, max_reapresentacoes: int = 2, max_dias: int = 2) -> int:
        """Pendente reapresentado 2x ou com mais de max_dias vira expirado (o Fechamento
        lista todos os alertas do dia de qualquer forma)."""
        n = 0
        hoje = agora_iso()[:10]
        for v in self.fila.values():
            if v.get("status") != "pendente":
                continue
            idade = (datetime.fromisoformat(hoje) - datetime.fromisoformat(v["gerado_em"][:10])).days
            if v.get("reapresentado", 0) >= max_reapresentacoes or idade > max_dias:
                v["status"] = "expirado"
                n += 1
        return n

    def do_dia(self, *datas: str) -> list[dict]:
        """Alertas do pregao e, quando informada, tambem da data da coleta.

        Fato relevante e filing carregam a data do documento, que pode ser anterior
        ao pregao (um 8-K de 09/09 achado em 19/09). Sem a data da coleta, o que foi
        descoberto hoje sobre um documento antigo ficava de fora do digest."""
        alvos = {d for d in datas if d}
        # severidade primeiro e, dentro dela, o mais recente na frente: num digest o
        # que acabou de aparecer e o que interessa, nao o que entrou na fila de manha
        return sorted([v for v in self.fila.values() if v.get("data") in alvos or v.get("gerado_em", "")[:10] in alvos],
                      key=lambda v: ({"critico": 0, "atencao": 1, "info": 2}.get(v.get("severidade"), 3),
                                     _inverso(v.get("gerado_em", ""))))

    def podar(self, dias: int = 30, dias_manchete: int = 2) -> None:
        """Alerta sai da fila apos `dias`; noticia ou fato que nunca virou mensagem sai
        em `dias_manchete` (senao o backlog de manchetes entope o digest do dia)."""
        corte = agora_iso()[:10]
        ano, mes, dia = map(int, corte.split("-"))
        from datetime import date, timedelta
        hoje = date(ano, mes, dia)
        limite, limite_manchete = (hoje - timedelta(days=dias)).isoformat(), (hoje - timedelta(days=dias_manchete)).isoformat()
        def fica(v: dict) -> bool:
            gerado = v.get("gerado_em", "")[:10]
            if v.get("familia") in ("noticia", "evento") and v.get("canal") != "mensagem":
                return gerado >= limite_manchete
            return gerado >= limite
        self.fila = {k: v for k, v in self.fila.items() if fica(v)}

    def _historico(self, a: Alerta, slot: str) -> None:
        linha = {"id": a.id, "regra": a.regra, "ativo": a.ativo, "severidade": a.severidade, "data": a.data,
                 "slot": slot, "gerado_em": agora_iso(), "titulo": a.titulo, "dados": a.dados}
        with open(os.path.join(self.dir, "historico_alertas.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(linha, ensure_ascii=False) + "\n")

    def salvar(self) -> None:
        gravar_json(os.path.join(self.dir, "regras_estado.json"), self.regras.d)
        gravar_json(os.path.join(self.dir, "alertas.json"), self.fila)
