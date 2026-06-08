"""Redator (Gate 2): monta o prompt e rascunha o post no seu estilo.

O system prompt = voice/voice-guide.md (regras de voz + compliance + formato) +
voice/samples.md (exemplos da sua escrita, em few-shot). A pauta aprovada e os
dados entram na mensagem do usuário. Sem ANTHROPIC_API_KEY, cai em prompt-only.
"""
from __future__ import annotations

import json
import os

from .propose import Pauta

HERE = os.path.dirname(os.path.dirname(__file__))
VOICE_GUIDE = os.path.join(HERE, "voice", "voice-guide.md")
SAMPLES = os.path.join(HERE, "voice", "samples.md")

# Default seguindo a recomendação da referência da API para escrita de qualidade.
# Configurável em config.json (chave "model") ou via --model.
DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_EFFORT = "high"
DEFAULT_MAX_TOKENS = 4000


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def build_system(voice_guide: str, samples: str) -> str:
    parts = [voice_guide or "# Guia de voz\n(defina em voice/voice-guide.md)"]
    if samples:
        parts.append("# Exemplos da minha escrita (imite o ritmo, não o conteúdo)\n" + samples)
    return "\n\n".join(parts)


def build_user(pauta: Pauta) -> str:
    dados = json.dumps(pauta.data, ensure_ascii=False, indent=2)
    return (
        f"Pilar: {pauta.pillar}\n"
        f"Ângulo aprovado: {pauta.angle}\n\n"
        f"Dados do briefing (use SÓ estes números; não invente):\n{dados}\n\n"
        "Rascunhe UM único post de LinkedIn em texto corrido seguindo todas as "
        "regras do guia. Responda apenas com o texto do post — sem comentários, "
        "sem título, sem aspas."
    )


def draft_post(pauta: Pauta, model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT,
               max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    """Chama a API da Claude. Requer ANTHROPIC_API_KEY no ambiente."""
    import anthropic  # import tardio: só necessário no modo API

    client = anthropic.Anthropic()
    system = build_system(_read(VOICE_GUIDE), _read(SAMPLES))
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        system=system,
        messages=[{"role": "user", "content": build_user(pauta)}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def render_prompt_only(pauta: Pauta) -> str:
    """Sem API key: devolve o prompt pronto para colar no Claude / Claude Code."""
    system = build_system(_read(VOICE_GUIDE), _read(SAMPLES))
    return "===== SYSTEM =====\n" + system + "\n\n===== USER =====\n" + build_user(pauta)
