"""Politica anti-fadiga: severidade define o canal, teto diario, agrupamento por
regra/familia, escalada em vez de repeticao. Entrada: alertas novos do slot +
pendentes de slots anteriores. Saida: mensagens prontas (com push sugerido) e
linhas de info para o Fechamento."""

from __future__ import annotations

from collections import defaultdict

from livro.sinais.base import ROTULO

ORDEM = {"critico": 0, "atencao": 1, "info": 2}


def _sev_max(itens: list[dict]) -> str:
    return min((i.get("severidade", "info") for i in itens), key=lambda s: ORDEM.get(s, 3))


def _grupo(a: dict) -> str:
    fam = a.get("familia")
    if fam == "curva":
        return "curva"
    if fam == "cambio":
        return "cambio"
    if fam == "regime":
        return "regime"
    return f"{a.get('regra')}"


def _texto_grupo(grupo: str, itens: list[dict]) -> str:
    if len(itens) == 1:
        return itens[0]["texto"]
    sev = _sev_max(itens)
    rot = ROTULO.get(sev, "[INFO]")
    if grupo == "curva":
        cab = f"{rot} CURVA · " + " / ".join(f"{i['regra']} {i['titulo']}" for i in itens[:3])
        corpo = []
        for i in itens:
            corpo += [l for l in i.get("corpo", []) if l]
        pq = next((i["por_que"] for i in itens if i.get("por_que")), "")
        falar = next((i["como_falar"] for i in itens if i.get("como_falar")), "")
        fontes = " · ".join(sorted({i["fonte"] for i in itens if i.get("fonte")}))
        return "\n".join([cab] + corpo + ([f"Por que importa: {pq}"] if pq else []) + ([f"Como falar: '{falar}'"] if falar else []) + ([f"Fonte: {fontes}"] if fontes else []))
    regra = itens[0]["regra"]
    ativos = ", ".join(i["ativo"] for i in itens)
    linhas = [f"{rot} {regra} · {len(itens)} ativos: {ativos}"]
    for i in itens:
        linhas.append(f"· {i['titulo']}")
        for l in i.get("corpo", [])[:1]:
            linhas.append(f"  {l}")
    pq = next((i["por_que"] for i in itens if i.get("por_que")), "")
    if pq:
        linhas.append(f"Por que importa: {pq}")
    falar = next((i["como_falar"] for i in itens if i.get("como_falar")), "")
    if falar:
        linhas.append(f"Como falar: '{falar}'")
    fontes = " · ".join(sorted({i["fonte"] for i in itens if i.get("fonte")}))
    if fontes:
        linhas.append(f"Fonte: {fontes}")
    return "\n".join(linhas)


def _push(sev: str, itens: list[dict], slot_rotulo: str) -> str | None:
    if sev == "info":
        return None
    partes = []
    for i in itens[:3]:
        t = i["titulo"]
        partes.append((i["ativo"] + " " if i["ativo"] not in t[:12] else "") + t.split(":")[0][:60])
    texto = f"{ROTULO[sev]} " + " | ".join(partes)
    if len(itens) > 3:
        texto += f" +{len(itens) - 3}"
    texto = texto[:170] + " · detalhe na sessão"
    return texto


def aplicar(novos: list[dict], pendentes: list[dict], limiares: dict, slot: str, slot_rotulo: str,
            ja_emitidos_hoje: dict | None = None) -> dict:
    """Devolve {mensagens: [{severidade, grupo, ids, texto, push}], linhas_info: [...],
    suprimidos: [{id, motivo}], pendentes_reapresentados: [ids]}."""
    teto = (limiares.get("geral") or {}).get("teto_diario") or {}
    push_cfg = (limiares.get("geral") or {}).get("push") or {}
    ja = ja_emitidos_hoje or {"critico": 0, "atencao": 0}
    grupos: dict[str, list[dict]] = defaultdict(list)
    linhas_info, suprimidos = [], []
    reapresentados = []
    for a in pendentes:
        a = dict(a)
        a["reapresentacao"] = True
        grupos[_grupo(a)].append(a)
        reapresentados.append(a["id"])
    for a in novos:
        if a.get("severidade") == "info":
            linhas_info.append(a)
            continue
        grupos[_grupo(a)].append(a)
    mensagens = []
    contagem = dict(ja)
    ordenados = sorted(grupos.items(), key=lambda kv: ORDEM.get(_sev_max(kv[1]), 3))
    n_atencao_slot = 0
    for grupo, itens in ordenados:
        sev = _sev_max(itens)
        reap = any(i.get("reapresentacao") for i in itens)  # ja saiu como mensagem: nao disputa o teto de novo
        if sev == "critico":
            if not reap and contagem.get("critico", 0) >= teto.get("critico", 2):
                for i in itens:
                    suprimidos.append({"id": i["id"], "motivo": "teto diário de críticos"})
                    linhas_info.append(i)
                continue
            if not reap:
                contagem["critico"] = contagem.get("critico", 0) + 1
        elif sev == "atencao":
            if not reap and (contagem.get("atencao", 0) >= teto.get("atencao", 4) or n_atencao_slot >= teto.get("por_slot_atencao", 3)):
                for i in itens:
                    suprimidos.append({"id": i["id"], "motivo": "teto de atenção"})
                    linhas_info.append(i)
                continue
            if not reap:
                contagem["atencao"] = contagem.get("atencao", 0) + 1
                n_atencao_slot += 1
        texto = _texto_grupo(grupo, itens)
        if any(i.get("reapresentacao") for i in itens):
            texto = "(pendente de slot anterior) " + texto
        push = None
        if sev == "critico" and push_cfg.get("critico", True):
            push = _push(sev, itens, slot_rotulo)
        elif sev == "atencao" and push_cfg.get("atencao_agrupado", True):
            push = _push(sev, itens, slot_rotulo)
        mensagens.append({"severidade": sev, "grupo": grupo, "ids": [i["id"] for i in itens], "texto": texto, "push": push})
    # push agrupado de atencao: um so por slot
    pushes_at = [m for m in mensagens if m["severidade"] == "atencao" and m["push"]]
    if len(pushes_at) > 1:
        resumo = f"{slot_rotulo}: {len(pushes_at)} alertas de atenção — " + ", ".join(m["grupo"] + " " + ",".join(sorted({i.split('-')[1] for i in m['ids']})) for m in pushes_at)
        for m in pushes_at:
            m["push"] = None
        pushes_at[0]["push"] = resumo[:170] + " · detalhe na sessão"
    return {"mensagens": mensagens, "linhas_info": linhas_info, "suprimidos": suprimidos,
            "pendentes_reapresentados": reapresentados, "contagem": contagem}
