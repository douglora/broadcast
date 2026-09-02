#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Autoteste da ponte. Nao toca no WAHA, nao envia nada, nao le o repo de estado:
exercita as regras que nao podem quebrar (limites, silencio, fila, parser).

    python3 autoteste.py
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

os.environ.setdefault("TRACKNEWS_BRIDGE_HOME", tempfile.mkdtemp(prefix="ponte-teste-"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bridge  # noqa: E402

FALHAS: list[str] = []


def checa(condicao: bool, descricao: str) -> None:
    print(("  ok   " if condicao else "  FALHA") + f"  {descricao}")
    if not condicao:
        FALHAS.append(descricao)


def cfg_base() -> dict:
    return copy.deepcopy(bridge.DEFAULTS)


def em(hora: int, minuto: int = 0, dia: int = 15) -> datetime:
    return datetime(2026, 8, dia, hora, minuto, tzinfo=bridge.TZ)


def historico(*momentos: datetime) -> dict:
    return {"alertas": {
        f"a{i}": {"resultado": "enviado", "enviado_em": m.isoformat()}
        for i, m in enumerate(momentos)
    }}


def teste_silencio() -> None:
    print("\n[silencio 22:00-06:30 America/Sao_Paulo]")
    cfg = cfg_base()
    checa(not bridge.em_silencio(cfg, em(21, 59)), "21:59 fora do silencio")
    checa(bridge.em_silencio(cfg, em(22, 0)), "22:00 em silencio")
    checa(bridge.em_silencio(cfg, em(3, 0)), "03:00 em silencio (cruza a meia-noite)")
    checa(bridge.em_silencio(cfg, em(6, 29)), "06:29 em silencio")
    checa(not bridge.em_silencio(cfg, em(6, 30)), "06:30 libera")
    pode, motivo, liberado = bridge.avalia_limites(cfg, {"alertas": {}}, em(23, 0))
    checa(not pode and "silencio" in motivo, "23:00 bloqueia com motivo de silencio")
    checa(liberado is not None and liberado.hour == 6 and liberado.minute == 30,
          "silencio informa que libera as 06:30")


def teste_espacamento() -> None:
    print("\n[espacamento minimo de 10 min]")
    cfg = cfg_base()
    agora = em(10, 0)
    pode, motivo, _ = bridge.avalia_limites(cfg, historico(agora - timedelta(minutes=9)), agora)
    checa(not pode and "espacamento" in motivo, "9 min depois do ultimo: bloqueia")
    pode, _, _ = bridge.avalia_limites(cfg, historico(agora - timedelta(minutes=10)), agora)
    checa(pode, "10 min depois do ultimo: libera")


def teste_teto_hora() -> None:
    print("\n[teto de 4 por hora]")
    cfg = cfg_base()
    agora = em(15, 0)
    quatro = historico(*[agora - timedelta(minutes=m) for m in (55, 40, 25, 12)])
    pode, motivo, _ = bridge.avalia_limites(cfg, quatro, agora)
    checa(not pode and "hora" in motivo, "4 na ultima hora: bloqueia a quinta")
    tres = historico(*[agora - timedelta(minutes=m) for m in (55, 40, 12)])
    checa(bridge.avalia_limites(cfg, tres, agora)[0], "3 na ultima hora: libera")
    antigas = historico(*[agora - timedelta(minutes=m) for m in (200, 190, 180, 170)])
    checa(bridge.avalia_limites(cfg, antigas, agora)[0], "janela e movel: envios velhos nao contam")


def teste_teto_dia() -> None:
    print("\n[teto de 12 por dia]")
    cfg = cfg_base()
    agora = em(20, 0)
    doze = historico(*[em(7, 0) + timedelta(minutes=30 * i) for i in range(12)])
    pode, motivo, liberado = bridge.avalia_limites(cfg, doze, agora)
    checa(not pode and "dia" in motivo, "12 no dia: bloqueia a decima terceira")
    checa(liberado is not None and liberado.day == 16, "teto diario libera so no dia seguinte")
    ontem = historico(*[em(7, 0, dia=14) + timedelta(minutes=30 * i) for i in range(12)])
    checa(bridge.avalia_limites(cfg, ontem, agora)[0], "12 de ontem nao contam para hoje")


def teste_kill_switch() -> None:
    print("\n[kill switch]")
    cfg = cfg_base()
    bridge.PAUSED_PATH.parent.mkdir(parents=True, exist_ok=True)
    bridge.PAUSED_PATH.touch()
    try:
        pode, motivo, _ = bridge.avalia_limites(cfg, {"alertas": {}}, em(10, 0))
        checa(not pode and "PAUSED" in motivo, "arquivo PAUSED bloqueia tudo")
    finally:
        bridge.PAUSED_PATH.unlink()
    checa(bridge.avalia_limites(cfg, {"alertas": {}}, em(10, 0))[0], "sem PAUSED, volta a liberar")


def item(alert_id: str, revisao: str, minutos_atras: int) -> dict:
    return {
        "alert_id": alert_id, "text": f"texto {alert_id}", "priority": "MEDIUM",
        "revision_type": revisao, "parent_alert_id": None, "story_id": "s",
        "recorded_at": em(10, 0) - timedelta(minutes=minutos_atras),
        "source_url": None, "origem": "teste",
    }


def teste_ordem_da_fila() -> None:
    print("\n[ordem da fila]")
    fila = bridge.ordena_fila([
        item("novo-antigo", "NEW", 60),
        item("correcao", "CORRECTED", 1),
        item("novo-recente", "NEW", 5),
        item("retratacao", "RETRACTED", 0),
    ])
    ids = [i["alert_id"] for i in fila]
    checa(ids[:2] == ["correcao", "retratacao"], "correcao e retratacao vao na frente")
    checa(ids[2:] == ["novo-antigo", "novo-recente"], "o resto e FIFO por recorded_at")


def teste_simulacao() -> None:
    print("\n[simulacao dos limites]")
    cfg = cfg_base()
    agora = em(9, 0)
    fila = [item(f"a{i}", "NEW", 60 - i) for i in range(6)]
    sairiam, ficariam = bridge.simula_limites(cfg, fila, {"alertas": {}}, agora)
    checa(len(sairiam) + len(ficariam) == len(fila), "nada some da simulacao")
    checa(len(sairiam) == 6, "6 alertas cabem no dia com 10 min de espacamento")
    horas = [q.strftime("%H:%M") for _, q in sairiam]
    checa(horas[:4] == ["09:00", "09:10", "09:20", "09:30"],
          f"espacamento de 10 min respeitado ({horas[:4]})")
    # a quinta nao pode sair as 09:40: isso seria a quinta dentro de uma hora.
    # Ela espera a janela movel abrir, uma hora depois da primeira.
    checa(horas[4] == "10:00", f"teto de 4/hora empurra a quinta para 10:00 (veio {horas[4]})")
    checa(horas[5] == "10:10", f"e a sexta segue o espacamento (veio {horas[5]})")

    tarde = em(21, 55)
    sairiam2, ficariam2 = bridge.simula_limites(cfg, fila[:3], {"alertas": {}}, tarde)
    checa(len(sairiam2) == 1 and len(ficariam2) == 2,
          "as 21:55 so a primeira sai; as outras ficam na fila (nao sao descartadas)")
    checa(all("silencio" in motivo for _, motivo in ficariam2),
          "o motivo registrado e o silencio noturno")


def teste_parser() -> None:
    print("\n[parser do JSONL]")
    linhas = [
        # item bloqueado: nao tem a chave "alert"
        {"item": {"id": "x"}, "claims": [], "recorded_at": "2026-08-29T10:00:00+00:00",
         "gate": {"allowed": False, "action": "block", "reasons": ["sem entidade"]}},
        # alerta segurado pela nuvem
        {"alert": {"alert_id": "seg", "text": "nao pode sair", "revision_type": "NEW"},
         "gate": {"allowed": False, "action": "hold", "reasons": ["espacamento"]},
         "recorded_at": "2026-08-29T11:00:00+00:00"},
        # alerta aprovado
        {"alert": {"alert_id": "ok1", "text": "pode sair", "revision_type": "NEW",
                   "priority": "MEDIUM"},
         "gate": {"allowed": True, "action": "review_only", "reasons": []},
         "recorded_at": "2026-08-29T12:00:00+00:00"},
        # aprovado mas sem texto: invalido
        {"alert": {"alert_id": "vazio", "text": "  ", "revision_type": "NEW"},
         "gate": {"allowed": True, "action": "review_only"},
         "recorded_at": "2026-08-29T12:30:00+00:00"},
        # reemissao do mesmo alert_id: a ultima ocorrencia vence
        {"alert": {"alert_id": "ok1", "text": "versao final", "revision_type": "NEW"},
         "gate": {"allowed": True, "action": "review_only"},
         "recorded_at": "2026-08-29T13:00:00+00:00"},
    ]
    conteudo = "\n".join(json.dumps(l, ensure_ascii=False) for l in linhas) + "\nlinha quebrada\n"
    cfg = cfg_base()
    original = bridge.le_arquivo_do_estado
    bridge.le_arquivo_do_estado = lambda c, caminho: conteudo if caminho.endswith(".jsonl") else None
    try:
        aprovados, estat = bridge.coleta_aprovados(cfg)
    finally:
        bridge.le_arquivo_do_estado = original
    ids = sorted(i["alert_id"] for i in aprovados)
    checa(ids == ["ok1"], f"so o aprovado com texto entra na fila (veio {ids})")
    checa(aprovados[0]["text"] == "versao final", "reemissao do mesmo id: a ultima vence")
    checa(estat["segurados"] >= 1, "alerta em hold e contado como segurado, nao enviado")
    checa(estat["invalidas"] >= 2, "linha quebrada e alerta sem texto sao descartados")

    # Digest matinal: vem de outputs/digest/<dia>.md, entra na fila como item
    # proprio, dedup por dia, e o .longo.md (camada privada) nunca entra.
    digest = "*Digest 01/09*\n\n*O que mudou*\nlinha 1\n\n"
    lidos = []

    def falso(c, caminho):
        lidos.append(caminho)
        if caminho.endswith(".jsonl"):
            return conteudo
        if caminho.endswith(".md") and "digest" in caminho and ".longo" not in caminho:
            return digest
        return None

    bridge.le_arquivo_do_estado = falso
    try:
        com_digest, estat2 = bridge.coleta_aprovados(cfg)
    finally:
        bridge.le_arquivo_do_estado = original
    digests = [i for i in com_digest if i["revision_type"] == "DIGEST"]
    checa(len(digests) >= 1 and estat2["digests"] == len(digests),
          f"digest matinal entra na fila como item proprio ({len(digests)} na janela)")
    checa(all(i["alert_id"].startswith("digest-") for i in digests),
          "digest tem id proprio por dia (dedup)")
    checa(all(i["text"] == digest.rstrip() for i in digests),
          "texto do digest sai igual ao arquivo, so sem quebras finais")
    checa(not any(".longo" in c for c in lidos),
          "o .longo.md (camada privada) nunca e lido para o grupo")
    checa(all(not i["text"].startswith("[SILENT]") for i in com_digest),
          "digest [SILENT] nao vira mensagem")


def teste_mascara() -> None:
    print("\n[segredos]")
    rotulo = bridge.mascara("5511999999999-1600000000@g.us")
    checa("5511999999999" not in rotulo and rotulo.startswith("id:"),
          "o id do grupo nunca aparece em claro")


def main() -> int:
    print("autoteste da ponte TrackNews")
    for teste in (teste_silencio, teste_espacamento, teste_teto_hora, teste_teto_dia,
                  teste_kill_switch, teste_ordem_da_fila, teste_simulacao,
                  teste_parser, teste_mascara):
        teste()
    print()
    if FALHAS:
        print(f"{len(FALHAS)} FALHA(S):")
        for f in FALHAS:
            print(f"  - {f}")
        return 1
    print("tudo passou.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
