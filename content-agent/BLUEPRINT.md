# Blueprint — Agente de conteúdo BROADCAST → LinkedIn

Documento de arquitetura e estratégia. O código vive em `agent/`; o "cérebro" de
estilo vive em `voice/`. Decisões travadas com o autor: **tom de educação/comentário**
(sem recomendação), **o agente rascunha e o humano finaliza**, **texto corrido**
(não carrossel).

## 1. O ativo (por que isso funciona)
O servidor BROADCAST já expõe dado estruturado e em tempo real que a maioria dos
criadores de finanças não tem: cotações, indicadores macro, curva DI, fatos
relevantes da CVM em tempo real, resumo semanal e fundamentos. Esse é o diferencial.
O agente transforma esse dado em **pautas + rascunho**; a **voz** é do autor.

Mapa endpoint → pilar de conteúdo:

| Pilar           | Endpoints                                              |
|-----------------|--------------------------------------------------------|
| Macro BR        | `/api/indicators`, `/api/di`, `/api/spreads`, `/api/tesouro` |
| Macro EUA/global| `/api/quotes` (índices, WTI/Brent), `/api/cvm` (SEC)   |
| Resumo          | `/api/weekly_summary`                                  |
| Micro / ações   | `/api/quotes`, `/api/asset`, `/api/statusinvest`, `/api/tir` |
| Fato relevante  | `/api/alerts`, `/api/cvm`                              |

## 2. Cadência (3 posts/semana, rotação — não molde fixo)
Mesma identidade, ângulos diferentes, para o engajamento não decair:
- **Segunda — "A semana que vem"** (macro → micro): curva DI + 1-2 ações com evento.
- **Quarta — "O fato"** (micro → macro): 1 fato relevante da CVM e o que ele significa.
- **Sexta — "Fechamento"**: `weekly_summary` como base, com a leitura do autor por cima.

A mistura deve pesar no que **renova sozinho** (fatos relevantes, movimentos das
ações). Macro puro seca rápido.

## 3. Os dois pontos de aprovação (human-in-the-loop)
```
collect ─► snapshot.json
           │
           ▼
        propose ──► 5-6 pautas com dados   ── GATE 1: você escolhe o ângulo
           │
           ▼
         draft ───► rascunho no seu estilo  ── GATE 2: você edita e publica
```
- **Gate 1 (`propose`)**: heurística determinística sobre o snapshot (sem LLM).
  Ranqueia fatos relevantes > maiores movimentos > macro > EUA.
- **Gate 2 (`draft`)**: aqui entra a Claude. System prompt = `voice/voice-guide.md`
  + `voice/samples.md` (seus posts, em few-shot). Saída = rascunho para você editar.

## 4. Não parecer IA
O fosso é o dado; a voz tem que ser sua. Por isso:
- O agente rascunha, **você finaliza** — a decisão travada.
- `voice/samples.md` condiciona o modelo na sua escrita (peça mais importante).
- `voice/voice-guide.md` tem a lista de frases banidas (os "tells" de IA).
- Modelo: `claude-opus-4-8` por padrão (melhor prosa), via API com *adaptive thinking*
  e `effort` — sem `temperature` (o modelo não aceita). Configurável em `config.json`.

## 5. Compliance (CVM) — regra editorial, não remendo
O autor não é CNPI. O guia de voz **proíbe** recomendação, preço-alvo e promessa de
retorno, e **exige** uma linha de isenção. Isso está embutido no prompt desde o dia 1.
Não é aconselhamento jurídico — confirme o limite com quem entende de compliance.

## 6. Engajamento (mecânica do LinkedIn)
- 2 primeiras linhas = gancho (antes do "ver mais").
- Link externo, se houver, vai no 1º comentário (não no corpo).
- Pergunta real no fim puxa comentário; comentário pesa mais que like.
- Coluna recorrente nomeada cria hábito de audiência.
- Gráfico nativo (Chart.js do portal) como imagem reforça autoridade.

## 7. Roadmap (próximos incrementos)
1. **`statusinvest`/`tir` na pauta micro** — enriquecer movers com fundamento e
   data com/ex-dividendo (já dá pra puxar; falta plugar no `propose`).
2. **Agendador** — rodar `collect` + `propose` num horário fixo e te mandar as
   pautas (e-mail/Telegram) para o Gate 1 assíncrono.
3. **Detector de surpresa macro** — disparar pauta só quando Selic/IPCA/DI saem de
   um limiar, em vez de sempre.
4. **Memória de tema** — registrar o que já foi postado para não repetir ângulo.
5. **Publicação** — rascunho aprovado → fila de agendamento (ainda manual hoje).
