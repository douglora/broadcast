# Contrato da tela: bloco `vertentes` do `quant_opcoes.json`

Para o agente da tela. Gerado por `python -m quant.opcoes.painel` (o mesmo comando de sempre; a rotina da noite já o roda). As chaves antigas (`estrategias`, `candidatas_hoje`, `posicoes`, `resultado`, `assimetrias`, `teses`, `avisos`, `termos`, `resumo`) continuam iguais; `vertentes` é uma chave nova. JSON estrito (sem NaN; campo sem dado vem `null`). Textos já saem com acento e número no formato brasileiro; os números soltos vêm como número JSON (formate na tela com vírgula decimal).

Tudo é SIMULAÇÃO. Nada diz "compre" ou "venda". Não mostrar ordem, só estrutura.

## `vertentes`: lista de 3 itens, nesta ordem

`nome` = `"especulativa"` | `"dividendo_sintetico"` | `"travas_bova"`. Cada item:

| Chave | Tipo | O que é |
|---|---|---|
| `nome` | texto | identificador estável |
| `titulo` | texto | para a aba/cartão: "Especulativa: compra de calls", "Dividendo sintético: venda de put e call coberta", "Travas com BOVA11" |
| `regra` | lista de frases | a regra em português simples, uma frase por item (mostrar como lista) |
| `evidencia` | objeto | ver abaixo |
| `ranking_hoje` | lista | o ranking do dia (colunas diferentes por vertente, abaixo) |
| `posicoes` | lista | o livro simulado da vertente (abertas e encerradas) |
| `placar` | objeto | resumo do livro |
| `limites` | objeto | limites propostos, com o texto pronto em `texto` |
| `direcao_hoje` | objeto, só em `travas_bova` | leitura de tendência de BOVA11 (`direcao`: alta, baixa ou neutra; `motivos`: frases) |

### `evidencia`
- `etiqueta`: uma de `"aprovada"`, `"medindo"`, `"reprovada no histórico: só medida"`. **Hoje nenhuma vertente pode estar "aprovada"** (a prova 2024-2026 já foi aberta antes e a confirmação vem da simulação ao vivo). Mostrar a etiqueta como selo em cor neutra/amarela para "medindo" e vermelha clara para "reprovada...".
- `resumo`: parágrafo com o que foi testado e o que passou.
- `itens`: lista de `{regra, etiqueta, numeros}`, uma linha por regra testada (cada uma com a própria etiqueta).
- `grade`: texto com o tamanho da grade pré-registrada (V2 e V3).
- `estresse_do_stop` (só V2): objeto com `atraso_0_pregoes`, `atraso_1_pregoes`, `atraso_2_pregoes` (excesso ao ano, Sharpe, pior mês e perda de março/2020). Mostrar junto do selo da V2: o stop só funciona se a saída acontecer no fechamento do gatilho.
- Regra de ouro: a tela mostra a etiqueta e o resumo na mesma altura que o ganho. Cauda (pior mês, 2020) com o mesmo destaque do retorno.

### `ranking_hoje` por vertente

**especulativa** (calls no dinheiro; ordenado por `pontos`):
`ativo`, `serie`, `vencimento`, `pregoes`, `strike`, `premio` (por opção, oferta de venda), `delta`, `preco_ativo`, `equilibrio`, `distancia_equilibrio_pct`, `prob_acima_equilibrio_preco_pct` (a que o preço embute), `prob_acima_equilibrio_historico_pct` (a empírica), `vol_implicita_pct`, `vol_realizada_252d_pct`, `percentil_vol_implicita`, `inclinacao_put_percentil` (só informativa), `gatilho_tecnico` (`"T1"`, `"T2"` ou null), `acima_media_200`, `proximo_resultado`, `pontos`, `porque` (lista de frases com os pontos), `custo_do_lote_rs`, `cabe_no_teto_por_estrutura`, `liquidez` {`negocios`, `spread_pct`}.

**dividendo_sintetico** (puts cobertas por caixa e calls cobertas; as elegíveis ao livro vêm primeiro):
`tipo` ("put coberta por caixa" ou "call coberta (exige o papel em carteira)"), `ativo`, `serie`, `vencimento`, `pregoes`, `strike`, `premio` (oferta de compra), `delta`, `preco_ativo`, `distancia_strike_pct`, `rendimento_no_prazo_pct`, `rendimento_anualizado_pct`, `garantia_do_lote_rs`, `credito_do_lote_rs`, `recompra_em_80pct` (preço de recompra que fecha 80% do prêmio), `stop_em` (null em call coberta), `prob_exercicio_preco_pct`, `prob_exercicio_historico_pct`, `percentil_vol_implicita`, `vol_implicita_pct`, `suporte_60d`, `strike_abaixo_do_suporte`, `evento_no_caminho`, `proximo_resultado`, `liquidez`, `porque` (contexto), `elegivel_livro`.

**travas_bova** (a tabela diária por vencimento de BOVA11; até 3 melhores por vencimento e por tipo, por retorno sobre o risco):
`vencimento`, `pregoes`, `trava` ("alta com put (crédito)" ou "baixa com call (crédito)"), `tipo` ("put_spread" ou "call_spread"), `strike_vendido`, `strike_comprado`, `largura`, `largura_pct`, `credito`, `risco_maximo`, `retorno_sobre_risco_pct`, `delta_vendido`, `equilibrio`, `distancia_equilibrio_pct`, `prob_ganho_maximo_preco_pct` (a que o preço embute) e `prob_ganho_maximo_historico_pct` (a empírica), `prob_lucro_preco_pct`, `prob_perda_maxima_preco_pct` e `prob_perda_maxima_historico_pct`, `valor_esperado_historico_por_lote_rs` (média do resultado do lote se o futuro se parecer com o histórico), `credito_do_lote_rs`, `risco_do_lote_rs`, `alinhada_com_a_tendencia`, `liquidez` {`negocios_minimo`, `spread_maximo_pct`}, `perna_vendida`, `perna_comprada`, `preco_ativo`.

Sugestão: duas tabelas lado a lado por vencimento (alta com put | baixa com call), com a trava alinhada à tendência em destaque e a outra marcada "contra a tendência". Mostrar sempre as duas probabilidades (preço e histórico) na mesma linha: a diferença entre elas é o que a tela quer ensinar.

### `posicoes`
Mesmo formato de `posicoes` do bloco antigo, com campos a mais: `vertente`, `garantia_rs`, `pior_caso_rs`, `stop_multiplo`, `alvo_pct` (80), `motivo_fechamento` (null enquanto aberta; "alvo: 80% do prêmio capturado", "stop: ...", "vencimento..."), `pontos_na_abertura` (só V1), `rendimento_caixa_rs` e `resultado_com_caixa_rs` (V2 e V3: o CDI da garantia entra na conta; V1 não). Posição **vendida** tem `custo` negativo (crédito recebido) e `valor_hoje` negativo (custo de fechar). `resultado_rs` é sempre `valor_hoje - custo`. Cada perna tem `lado` "compra" ou "venda". Não existe perna vendida de call sem uma comprada de strike maior na mesma posição (a tela nunca verá call descoberta).

Na vertente `especulativa` as posições vêm do livro antigo (`carteira_simulada.json`), inclusive o capital protegido (`permanente: true`) e as teses da mesa; as da V2 e V3 vêm de `quant/saida/opcoes/carteira_vertentes.json`.

### `placar`
`desde`, `n_abertas`, `n_encerradas`, `resultado_aberto_rs`, `resultado_realizado_rs`, `resultado_acumulado_rs`, `rendimento_do_caixa_rs` e `resultado_com_caixa_rs` (null na V1), `acerto_pct` (null sem encerradas), `pior_posicao_rs`, `fechadas_por` ({"alvo": n, "stop": n, "vencimento": n}), `risco_em_aberto_rs`, `limite_de_risco_rs`, `uso_do_limite_pct`, `nota`. Sem encerradas, o placar mede só marcação a mercado: dizer isso na tela.

### `limites`
Comuns: `capital_da_classe_rs`, `orcamento_de_queda_rs`, `teto_de_risco_aberto_rs`, `fracao_do_orcamento_de_queda_pct`, `texto` (frase pronta).
- V1: `perda_maxima_por_estrutura_rs`, `estruturas_abertas_no_maximo`, `novas_por_dia`, `capital_protegido_por_mes_rs`.
- V2: `garantia_maxima_rs`, `lotes_por_posicao`, `posicoes_abertas_no_maximo`, `bova11_garantia_por_lote_rs`, `bova11_lotes_que_cabem_na_garantia`, `bova11_pior_caso_historico_por_lote_rs`, `bova11_pior_caso_pct_do_livro`, `orcamento_de_queda_que_comportaria_o_pior_caso_rs` e `_pct` (o número que o Douglas decide), `bova11_perda_no_stop_simulada_por_lote_rs`, `bova11_perda_no_stop_com_atraso_de_1_pregao_por_lote_rs`, `bova11_perda_no_stop_pelo_premio_de_hoje_rs`.
- V3: `perda_maxima_por_trava_rs`, `travas_abertas_no_maximo`, `lotes_por_trava`, `exemplo_de_trava_de_hoje`.

## Termos novos em `termos`
Dividendo sintético, Put coberta por caixa, Trava de crédito, Retorno sobre o risco, Stop em múltiplo do prêmio, Roda.

## Regras de exibição
1. Selo de evidência junto do título de cada vertente; nunca esconder "reprovada no histórico: só medida".
2. Cauda ao lado do ganho: no V2 mostrar `bova11_pior_caso_*` junto do rendimento anualizado.
3. Probabilidade do preço e do histórico sempre juntas.
4. Tela de leitura no celular: tabelas de até 4 colunas, o resto no detalhe expansível. Sigla explicada na primeira vez.
5. O texto da tela nunca usa os verbos "comprar" ou "vender" como ordem: descreve a estrutura ("trava de alta com put: vende 190, compra 180").
