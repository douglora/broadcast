#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Inspecao SOMENTE LEITURA do Hermes, para o heartbeat.

Responde, sem expor segredo, telefone ou id de chat:
  - o que o bridge.js faz com o texto antes de enviar (formatOutgoingMessage,
    splitLongMessage, buildTextSendPayload);
  - quais skills o Hermes tem (nome + descricao) e o SKILL.md inteiro das que
    parecem definir formato de post/noticia;
  - quais crons internos o Hermes tem (arquivos de agenda) e o que a doc diz;
  - o que os logs do Hermes registraram hoje sobre envios e crons.

Imprime um JSON. Nao muda nada.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date
from pathlib import Path

HERMES = Path.home() / ".hermes"
EXCLUIR = ("node_modules", ".git", "website", "tests", "__pycache__", ".venv", "venv")
LIMITE_LINHA = 160


def mascara(texto: str) -> str:
    texto = re.sub(r"\d{10,}@(g\.us|c\.us|s\.whatsapp\.net|lid)", r"<id>@\1", texto or "")
    texto = re.sub(r"\+?\d{2}\s?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4}", "<fone>", texto)
    texto = re.sub(r"(key|token|secret|senha|pass|bearer|authorization)([=: \"']+)[^\s\"',}]+",
                   r"\1\2<omitido>", texto, flags=re.I)
    return texto


def le(caminho: Path, max_linhas: int) -> list[str]:
    try:
        linhas = caminho.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [mascara(l)[:LIMITE_LINHA] for l in linhas[:max_linhas]]


def bloco_js(linhas: list[str], inicio: int, max_linhas: int = 80) -> list[str]:
    """Do inicio ate fechar as chaves da funcao (contagem simples de { })."""
    saida, nivel, aberto = [], 0, False
    for l in linhas[inicio: inicio + max_linhas]:
        saida.append(mascara(l)[:LIMITE_LINHA])
        nivel += l.count("{") - l.count("}")
        if "{" in l:
            aberto = True
        if aberto and nivel <= 0:
            break
    return saida


def funcoes_do_bridge() -> dict:
    achado = HERMES / "hermes-agent/scripts/whatsapp-bridge/bridge.js"
    if not achado.is_file():
        for c in HERMES.rglob("bridge.js"):
            if "whatsapp" in str(c) and "node_modules" not in str(c):
                achado = c
                break
    if not achado.is_file():
        return {"erro": "bridge.js nao encontrado"}
    try:
        linhas = achado.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as erro:
        return {"erro": str(erro)[:80]}
    saida = {"arquivo": str(achado), "linhas_total": len(linhas)}
    for nome in ("formatOutgoingMessage", "splitLongMessage", "buildTextSendPayload"):
        padrao = re.compile(rf"(function\s+{nome}\b|(const|let|var)\s+{nome}\s*=)")
        for i, l in enumerate(linhas):
            if padrao.search(l):
                saida[nome] = bloco_js(linhas, i)
                break
        else:
            # pode vir de um modulo importado
            for i, l in enumerate(linhas):
                if nome in l and ("require(" in l or "import " in l):
                    saida[nome] = ["(importado) " + mascara(l)[:LIMITE_LINHA]]
                    break
            else:
                saida[nome] = ["(nao encontrado no bridge.js)"]
    return saida


def pasta_skills() -> Path | None:
    for c in HERMES.rglob("briefing-diario"):
        if c.is_dir() and not any(x in c.parts for x in EXCLUIR):
            return c.parent
    for nome in ("skills",):
        for c in HERMES.rglob(nome):
            if c.is_dir() and not any(x in c.parts for x in EXCLUIR) and any(c.glob("*/SKILL.md")):
                return c
    return None


def skills() -> dict:
    pasta = pasta_skills()
    if not pasta:
        return {"erro": "pasta de skills nao localizada"}
    inventario, completas = [], {}
    gatilho = re.compile(r"autopilot|news|noticia|notícia|post|formato|radar|alerta|digest|broadcast|grupo|whats",
                         re.I)
    for skill_md in sorted(pasta.glob("*/SKILL.md"))[:60]:
        nome = skill_md.parent.name
        cabecalho = le(skill_md, 14)
        descricao = next((l for l in cabecalho if l.lower().startswith("description:")), "")
        inventario.append({"skill": nome, "descricao": descricao[:LIMITE_LINHA]})
        if gatilho.search(nome) or gatilho.search(descricao):
            completas[nome] = le(skill_md, 220)
    return {"pasta": str(pasta), "inventario": inventario, "completas": completas}


def crons() -> dict:
    saida = {"arquivos": [], "doc": []}
    candidatos = []
    for c in HERMES.rglob("*"):
        if not c.is_file() or any(x in c.parts for x in EXCLUIR):
            continue
        nome = c.name.lower()
        if ("cron" in nome or "schedule" in nome or "jobs" in nome) and c.suffix in (".json", ".yaml", ".yml", ".toml", ".jsonl", ".db", ".sqlite"):
            candidatos.append(c)
    for c in candidatos[:12]:
        item = {"arquivo": str(c), "bytes": c.stat().st_size}
        if c.suffix in (".json", ".yaml", ".yml", ".toml", ".jsonl"):
            item["inicio"] = le(c, 60)
        saida["arquivos"].append(item)
    doc = HERMES / "hermes-agent/website/docs/developer-guide/cron-internals.md"
    if doc.is_file():
        saida["doc"] = le(doc, 90)
    return saida


def logs_de_hoje() -> dict:
    hoje = date.today().isoformat()
    pasta = HERMES / "logs"
    saida = {}
    if not pasta.is_dir():
        return {"erro": "sem ~/.hermes/logs"}
    padrao = re.compile(r"send|enviad|outgoing|cron_|group|grupo|@g\.us|AutoPilot", re.I)
    for log in sorted(pasta.glob("*.log"))[:8]:
        try:
            linhas = log.read_text(encoding="utf-8", errors="replace").splitlines()[-4000:]
        except OSError:
            continue
        uteis = [mascara(l)[:LIMITE_LINHA] for l in linhas if hoje in l[:30] and padrao.search(l)]
        if uteis:
            saida[log.name] = uteis[-40:]
    return saida


def main() -> int:
    if not HERMES.is_dir():
        print(json.dumps({"erro": "~/.hermes nao existe"}))
        return 0
    print(json.dumps({
        "bridge_funcoes": funcoes_do_bridge(),
        "skills": skills(),
        "crons": crons(),
        "logs_hoje": logs_de_hoje(),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
