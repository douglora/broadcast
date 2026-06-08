# content-agent

Agente que transforma os dados do servidor **BROADCAST** em **rascunhos** de posts
de LinkedIn, com dois pontos de aprovação seus. Estratégia completa em
[`BLUEPRINT.md`](./BLUEPRINT.md).

> Tom: **educação/comentário de mercado** (sem recomendação). O agente **rascunha**,
> **você edita e publica**.

## Instalação
```bash
cd content-agent
pip install -r requirements.txt          # anthropic + requests
cp config.example.json config.json       # e edite broadcast_base_url
export ANTHROPIC_API_KEY=sk-ant-...       # necessário só para o 'draft' via API
```

## O fluxo (3 passos)
```bash
# 1. Coleta um snapshot do servidor BROADCAST (precisa do túnel no ar)
python -m agent.cli collect

# 2. GATE 1 — vê as pautas sugeridas e escolhe um id (ex.: p2)
python -m agent.cli propose

# 3. GATE 2 — rascunha o post da pauta escolhida (você edita depois)
python -m agent.cli draft --pauta p2
```

## Rodando sem o servidor / sem API key
- **Sem snapshot real:** `propose` e `draft` caem no `sample_snapshot.json`
  (dados ilustrativos) para você ver o formato.
- **Sem `ANTHROPIC_API_KEY`** (ou com `--prompt-only`): `draft` imprime o prompt
  montado (system + user) para você colar no Claude / Claude Code.

```bash
python -m agent.cli propose
python -m agent.cli draft --pauta p1 --prompt-only
```

## A peça que faz não parecer IA
Edite **`voice/samples.md`** e cole 3–5 posts seus. É o que ensina o modelo a
escrever no seu ritmo. As regras de voz, compliance e formato estão em
**`voice/voice-guide.md`** (edite à vontade — é o "cérebro" do prompt).

## Configuração (`config.json`)
| chave                | o que é                                            |
|----------------------|----------------------------------------------------|
| `broadcast_base_url` | URL do túnel do servidor BROADCAST (ngrok/Cloudflare) |
| `model`              | modelo de redação (default `claude-opus-4-8`)      |
| `effort`             | `low` \| `medium` \| `high` \| `max` (default `high`) |
| `timeout`            | timeout de rede em segundos                        |

## Estrutura
```
content-agent/
  agent/
    broadcast_client.py   cliente da API do BROADCAST
    collect.py            tira e salva o snapshot
    propose.py            Gate 1 — heurística de pautas (sem LLM)
    draft.py              Gate 2 — rascunho via Claude (ou prompt-only)
    cli.py                collect / propose / draft
  voice/
    voice-guide.md        regras de voz, compliance e formato (system prompt)
    samples.md            seus posts (few-shot) — PREENCHA
  data/                   snapshots salvos
  sample_snapshot.json    dados ilustrativos p/ rodar offline
  config.example.json
```
