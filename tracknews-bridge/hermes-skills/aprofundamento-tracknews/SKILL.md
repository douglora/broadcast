---
name: aprofundamento-tracknews
description: Camada 2 do TrackNews — quando o Douglas pede "mais <id>", "mais" ou "aprofunda" sobre um alerta que chegou no grupo AutoPilot News, busca o alerta e os claims auditados no repo de estado e escreve o aprofundamento (até 1.500 caracteres) só com números lastreados, entregue no self-chat do Douglas, nunca no grupo. Nunca reescreve nem reenvia o alerta original.
version: 1.0.0
author: Douglas Lora (douglora), TrackNews
license: MIT
platforms: [linux, darwin]
metadata:
  tracknews:
    tags: [radar, aprofundamento, camada-2, self-chat]
    related_skills: [alerta-radar, digest-matinal, briefing-diario]
---

# aprofundamento-tracknews

O alerta do grupo vem pronto e auditado da nuvem: cada número dele aponta para um
claim com trecho da fonte. **Este skill não toca no alerta.** Ele responde ao pedido
de "mais" com a camada 2 — o que não coube nos 600 caracteres — e entrega **no
self-chat do Douglas**, nunca no grupo AutoPilot News.

## Quando dispara

- `mais <alert_id>` — por exemplo `mais alert-f484dd526852bb943d1c`
- `mais` ou `aprofunda` sem id — vale o **último alerta aprovado**
- `contexto do <id>`, `detalha o <id>`

## Como fazer

1. Busque o material, só leitura:

   ```bash
   python3 ~/tracknews-bridge/hermes-skills/aprofundamento-tracknews/aprofundar.py <alert_id|ultimo>
   ```

   Sai: o texto exato do alerta, os **claims auditados** (entidade, métrica, valor,
   unidade, `as_of`, trecho da fonte), a fonte com link e, se for revisão, o alerta
   pai.

2. Escreva o aprofundamento com **até 1.500 caracteres**, primeira linha obrigatória:

   ```
   Aprofundamento do alerta <alert_id>
   ```

   Depois, só o que não coube no alerta, nesta ordem e apenas o que tiver lastro:
   - **histórico e magnitude** — o número contra a série (semana, mês, ano);
   - **cadeia** — quem está do outro lado: contraparte, concorrente, elo da cadeia;
   - **o que já estava no preço** e o que não estava;
   - **o que confirma ou desmente**, com data (dado oficial, balanço, reunião);
   - **lacunas declaradas** na cara: `sem cotação no fio`, `1 fonte apenas`.

3. Entregue no **self-chat** (a conversa do Douglas consigo mesmo). Nunca no grupo.

## Regras que não se negociam

- **Número só com lastro.** Ou está na lista de claims do `aprofundar.py`, ou vem de
  pesquisa própria **citada com veículo, hora e link cru** na própria linha. Sem uma
  das duas, o número não entra.
- **Não reescrever, resumir ou reenviar o alerta.** Ele já saiu; a camada 2 cita
  (`resposta ao alerta <id>`) e acrescenta.
- **Sem negrito, itálico, riscado, asterisco ou underscore.** Ênfase é o número.
- Português do Brasil, vírgula decimal, ponto de milhar; `bps` por extenso, nunca
  misturado com `%` sem rótulo.
- Jargão traduzido: "price action" → o movimento; hawkish/dovish banidos — diga o que
  o BC fez; "yield" de fabricação de chip é taxa de rendimento de fabricação.
- **Nenhuma recomendação.** "Ficou atraente para quem busca prazo" pode; "compre" não.
  Sem promessa nem projeção de rentabilidade.
- Fonte paga (TC, TradingKey, research de banco) é uso interno: nunca verbatim.
- Se `aprofundar.py` disser que o id não está na janela, responda isso e pare — não
  reconstrua o alerta de memória.

## Exemplo de saída

```
Aprofundamento do alerta alert-f484dd526852bb943d1c
Resposta ao alerta: BTC próximo de US$ 78 mil com petróleo e juros em alta.
Magnitude: a US$ 77.795,46 (CoinGecko, 10:20), a queda de 0,4 % em 24 h é pequena; o que pesa é o nível, o menor desde a semana passada, depois de agosto fechar em alta.
Cadeia: Strategy comprou US$ 370 milhões em BTC no dia anterior (Money Times 14:18) — comprador institucional ativo no mesmo nível em que o varejo reduz alavancagem.
No preço: a correlação com Treasuries (CMT 10 anos 4,75 %, +2 bps no dia) já vinha do fim de agosto; a surpresa seria um rompimento abaixo de US$ 75 mil.
Confirma ou desmente: fluxo dos ETFs à vista (Farside, dado diário às 19:00 de Nova York) e o CPI de agosto na quarta.
Lacuna: 1 fonte para a cotação; sem dado de liquidações no fio.
```
