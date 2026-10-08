"""
A chave liga/desliga do robo de day trade. E do Douglas: ele desliga e religa quando quiser.

Um arquivo so (quant/saida/robo_chave.json). Os dois robos (regra antiga e regra de fluxo) olham
a chave a cada ciclo: desligado, zeram o que estiver aberto e nao entram mais ate ele religar.
A chave vale ate ser mudada de novo (nao volta sozinha no dia seguinte).

Uso: python -m quant.robo desligar | ligar | estado
"""
import json
import os

from quant.comum import DIR_SAIDA, agora_brt, garantir_dir, gravar_atomico, ler_json

ARQ_CHAVE = os.path.join(DIR_SAIDA, "robo_chave.json")


def ler(arquivo=None):
    """{"ligado": bool, "desde": iso | None, "motivo": str}. Sem arquivo, ou arquivo estragado, vale LIGADO."""
    d = ler_json(arquivo or ARQ_CHAVE, padrao=None)
    if not isinstance(d, dict):
        return {"ligado": True, "desde": None, "motivo": ""}
    return {"ligado": d.get("ligado") is not False, "desde": d.get("desde"), "motivo": str(d.get("motivo") or "")}


def gravar(ligado, motivo="", arquivo=None):
    arquivo = arquivo or ARQ_CHAVE
    garantir_dir(os.path.dirname(arquivo))
    d = {"ligado": bool(ligado), "desde": agora_brt().isoformat(timespec="seconds"), "motivo": motivo}
    gravar_atomico(arquivo, json.dumps(d, ensure_ascii=False))
    return d


def hora_de(d):
    """'13:20 de 08/10' a partir do carimbo da chave."""
    try:
        data, hora = str(d.get("desde") or "").split("T")
        a, m, dia = data.split("-")
        return f"{hora[:5]} de {dia}/{m}"
    except ValueError:
        return "hora não registrada"


# ── a janela de operacao, tambem do Douglas ──────────────────────────────────────────────────────
ARQ_JANELA = os.path.join(DIR_SAIDA, "janela_robo.json")
JANELA_PADRAO = {"inicio": "09:15", "ultima_entrada": "12:50", "zerar": "13:00"}   # decisao dele em 08/10/2026


def janela(dia, arquivo=None):
    """A janela do dia: {"inicio", "ultima_entrada", "zerar", "motivo"}.

    O arquivo guarda a janela normal e as excecoes por data ({"excecoes": {"AAAA-MM-DD": {...}}}).
    Sem arquivo vale JANELA_PADRAO. Horario fora do formato HH:MM e ignorado.
    """
    d = ler_json(arquivo or ARQ_JANELA, padrao=None)
    d = d if isinstance(d, dict) else {}
    fora = dict(JANELA_PADRAO, motivo="")
    for origem in (d, (d.get("excecoes") or {}).get(str(dia)) or {}):
        for k in ("inicio", "ultima_entrada", "zerar"):
            v = origem.get(k)
            if isinstance(v, str) and len(v) == 5 and v[2] == ":" and v.replace(":", "").isdigit():
                fora[k] = v
        if origem is not d and origem:
            fora["motivo"] = str(origem.get("motivo") or "exceção do dia")
    return fora


# ── quais contratos o robo opera, tambem do Douglas ──────────────────────────────────────────────
ARQ_ATIVOS = os.path.join(DIR_SAIDA, "ativos_robo.json")


def ativos_ligados(todos, arquivo=None):
    """Os contratos que o robo opera, na ordem de `todos`. Sem arquivo (ou arquivo sem a lista) valem todos."""
    d = ler_json(arquivo or ARQ_ATIVOS, padrao=None)
    lista = d.get("ativos") if isinstance(d, dict) else None
    if not isinstance(lista, list):
        return tuple(todos)
    return tuple(a for a in todos if a in lista)
