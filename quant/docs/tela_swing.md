# Contrato da tela: swing trades curtos (bloco `swing` do `quant_fatores.json`)

Desde 11/10/2026 o módulo de ações pode ser o **swing**: operações de curto prazo, de 2 a no máximo 10 pregões (decisão do Douglas). Quem escreve é só o robô
(`quant/swing/vivo.py` durante o pregão, `quant/swing/boleta.py` de manhã); a tela só lê. O módulo `fatores` não foi removido: com `"modulos": ["fatores", ...]` a
carteira de fatores continua gravando o mesmo arquivo, sem o bloco `swing`.

Arquivo: o mesmo da carteira de fatores, `~/Desktop/terminal-artefato/web/d/x/quant_fatores.json` (e a cópia em `cache/out/pagina/`). As chaves de cima mantêm o
formato que a tela já lê; o bloco `swing` é aditivo. **`modulo: "swing"`** avisa de qual robô é o arquivo (ausente = carteira de fatores). Regravado a cada
~10 segundos em pregão e na rodada da manhã.

## Primeira coisa que a tela mostra

`avisos[0]` e `swing.resumo_evidencia` dizem, com todas as letras, se algum setup tem capital. **Em 11/10/2026 nenhum dos 39 setups pesquisados passou nas etapas de teste**
(`swing.estado == "so_medido"`): o livro registra cada sinal e o resultado como se tivesse operado R$ 6.000, sem capital. A tela deve mostrar isso antes de
qualquer número de resultado, e nunca chamar de "carteira" ou "posição" o que é só medição.

## Chaves de cima (formato já conhecido)

| Chave | No swing |
|---|---|
| `v`, `gerado`, `modo` ("paper"), `origem` ("real"), `capital` | iguais; `capital` é o do livro de swing (R$ 60.000) |
| `modulo` | `"swing"` |
| `vivo` | `ligado`, `fase` (`aguardando_abertura`, `operando`, `encerrado`), `fase_texto`, `batida`, `intervalo_s`, `motor{ok, idade_s, mt5}`, `com_cotacao`, `de` |
| `pronto`, `bloqueios[]` | `pronto` = boleta de hoje emitida e sem bloqueio. `bloqueios[]`: `{chave, titulo, detalhe, comando}`; `dado_velho` (cotações de um pregão antigo: nenhum sinal sai) e `boleta` (a rodada da manhã não gerou a boleta) |
| `avisos[]` | texto pronto, em português, o mais importante primeiro |
| `boleta` | `data` (pregão da entrada), `id`, `emitida`, `sinal_em` (fechamento que gerou os sinais), `gerado`, `motivo_bloqueio[]` |
| `ordens[]` | só as COM capital: `ticker`, `setup`, `lado: "C"`, `qtd`, `preco_referencia`, `stop`, `alvo`, `prazo`, `porque`. **Vazio enquanto nenhum setup tem capital** |
| `totais`, `carteira` | `carteira`: `patrimonio`, `caixa`, `valor_posicoes`, `n_posicoes`, `exposicao` (fração), `resultado_dia`, `posicoes[]` (as mesmas de `swing.posicoes`) |
| `mesa` | o cartão "Visão da mesa" (`quant/mesa.py`), a mesma estrutura do módulo de fatores |
| `serie[]` | `{data, patrimonio}` do livro de capital, um ponto por pregão |
| `diario[]` | mais novo primeiro: `{hora, tipo (entrada, saida, cancelada, boleta), texto}` |
| `fontes` | texto |

As chaves específicas da carteira de fatores (`hedge`, `protecao`, `gate`...) não existem no arquivo do swing, ou vêm vazias: a tela não deve exigir nenhuma.

## O bloco `swing`

```json
"swing": {
  "v": 1,
  "estado": "so_medido",                     // ou "com_capital" (algum setup passou nas 3 etapas ou o Douglas liberou por escrito)
  "resumo_evidencia": "Nenhum dos 39 setups de swing passou ...",
  "regra_de_evidencia": "texto: quando um setup usa capital",
  "regras": {
    "gerais": ["frase", "..."],              // as regras do livro em frases (prazo, risco, teto, exposição, mesa, custos, o que acontece no stop)
    "setups": [{"setup": "C1", "familia": "c_rompimento", "rotulo": "rompimento da máxima de 20 pregões com volume",
                "regra": "frase da regra de entrada e saída", "status": "so_medido", "status_texto": "só medido (sem capital)",
                "variantes": ["C1.S0", "C1.S1", "C1.S2"],
                "camada_de_julgamento": false, "etiqueta": null}]      // 15 setups: 13 pesquisados (A1 A2 B1 B2 C1 C2 D1 D2 E1 E2 F1 F2 G1) + M1 e M2 da mesa (ver abaixo)
  },
  "dimensionamento": {"capital": 60000, "risco_por_operacao_pct": 0.5, "risco_por_operacao_rs": 300, "teto_por_papel_pct": 12, "max_posicoes": 10,
                      "prazo_max_pregoes": 10, "valor_por_operacao_medida_rs": 6000, "exposicao_acoes_pct": 59.1, "exposicao_teto_rs": 59092.8,
                      "exposicao_texto": "59% do capital: peso de 60% x mão de 0,98 pela volatilidade ..."},
  "livro": {"capital_inicial", "patrimonio", "caixa", "valor_posicoes", "n_posicoes", "exposicao", "resultado_realizado_rs", "resultado_aberto_rs",
            "resultado_rs", "resultado_dia_rs", "operacoes_fechadas", "sem_capital_em_uso"},          // só as operações COM capital
  "posicoes": [ /* posições com capital abertas, ver abaixo */ ],
  "medidas_abertas": [ /* as só medidas ainda abertas ou à espera da barra do dia (até 150, as mais novas primeiro) */ ],
  "medidas_abertas_total": 130,
  "candidatas_hoje": {"sinal_em": "2026-10-09", "entrada_prevista": "2026-10-13", "total": 130, "com_capital": 0, "recusadas": 0, "so_medidas": 130,
                      "da_mesa": 0,                                         // quantas das linhas são M1/M2
                      "medidas_mesa": null,                                 // resumo da última visão da mesa medida: {gerado, visao_em, entrada_em, m1, m2, tickers_m1, tickers_m2, sem_dado[], repetidas[]}
                      "linhas": [ /* ver abaixo */ ]},
  "placar": {"medido": [ /* 41 linhas, uma por variante: 39 pesquisadas + M1.S0 e M2.S0 */ ], "capital": {"operacoes", "acerto", "expectativa_pct", "payoff", "resultado_rs"}},
  "evidencia": [ /* 41 linhas: a pesquisa por variante (M1.S0 e M2.S0 sem pesquisa: ver abaixo) */ ],
  "fechadas_recentes": [ /* as 40 últimas operações fechadas (com capital e medidas), mais nova primeiro */ ],
  "avisos": ["texto"]
}
```

### `posicoes[]` e `medidas_abertas[]`

```json
{"id": "2026-10-13|C1|ECOR3|capital", "setup": "C1", "ticker": "ECOR3", "modo": "capital",   // "capital" ou "medida"
 "status": "aberta",                              // "aberta"; as medidas podem estar "pendente" (esperam a barra oficial do dia da entrada)
 "entrada_em": "2026-10-13", "preco_entrada": 14.75, "stop": 13.1457, "alvo": 17.1564,       // alvo = null nos setups sem alvo (G1)
 "prazo": 10, "prazo_ate": "2026-10-26",          // o último pregão do prazo; a posição sai nele, nunca depois
 "pregoes_na_posicao": 1, "pregoes_restantes": 9, // o dia da entrada é o 1º; no último dia restantes = 0
 "qtd": 100, "valor": 1475.0, "risco_rs": 160.4, "preco_atual": 14.7, "resultado_rs": -4.18, "resultado_pct": -0.0028,    // líquido do custo de entrada
 "dist_stop_pct": 0.1088, "dist_alvo_pct": 0.1631,
 "porque": "ECOR3 fechou acima da máxima dos 20 pregões anteriores (R$ 14,15) com volume 1,7 vez(es) a média: rompimento com participação.",
 "variante": "C1.S0", "overlays": {"top": true, "ibov_ok": true}, "sinal_em": "2026-10-09"}
```
`preco_atual` e `resultado_rs` são `null` sem cotação de hoje (a tela mostra "sem cotação", nunca zero). Posição `pendente`: `preco_entrada`, `stop`, `alvo`, `qtd` e
`valor` são `null`; a tela mostra só o que se sabe (setup, papel, o porquê, a entrada prevista).

### `candidatas_hoje.linhas[]`

```json
{"setup": "C1", "rotulo": "...", "ticker": "ABCB4", "sinal_em": "2026-10-09", "preco_ref": 29.56, "stop_ref": 28.0, "alvo_ref": 31.9, "prazo": 10, "adtv": 19429746.5,
 "top": true, "ibov_ok": true, "porque": "frase", "destino": "medida",         // "capital" | "medida" | "recusada"
 "motivo": "setup só medido: reprovou na descoberta: ...",                      // por que não é capital, ou por que foi recusada (veto da mesa, véspera de resultado, sem espaço...)
 "variante": null, "qtd": null, "valor": null, "risco_rs": null,                // preenchidos só quando destino = "capital"
 "proximo_resultado": null, "nota_resultado": null,
 "resultado_antes_da_abertura": null,                                              // true/false quando o terminal ou a mesa dizem o horário do resultado; null = não sabe
 "mesa": {"conviccao": 0, "setor_inclinacao": 0, "analisado": false, "gatilho_curto_prazo": null, "eventos_10_pregoes": []},
 "entrada_em": null, "visao_gerado": null, "etiqueta": null, "camada_de_julgamento": null}   // as 4 últimas só nas linhas de M1/M2 (entrada_em = abertura em que a medida entra)
```
`stop_ref` e `alvo_ref` são referência no fechamento do sinal; o stop e o alvo de verdade partem do preço da abertura em que a posição entrar.

### `placar.medido[]` e `evidencia[]`

Uma linha por variante (13 setups pesquisados × 3 sobreposições, mais M1.S0 e M2.S0: `S0` = todos os sinais, `S1` = só a metade de cima do ranking multifatorial, `S2` = só com o Ibovespa acima da média
de 200 pregões).

```json
{"variante": "C1.S1", "setup": "C1", "sobreposicao": "S1", "rotulo": "...", "operacoes": 0, "acerto": null, "expectativa_pct": null, "payoff": null, "resultado_rs": 0,
 "pesquisa_descoberta": {"operacoes", "expectativa_pct", "acerto", "payoff", "sharpe", "excesso_aa", "queda_maxima", "anos_positivos", "n_anos"},
 "pesquisa_validacao": { /* idem */ }, "status": "so_medido", "status_texto": "só medido (sem capital)"}
```
`operacoes` = operações medidas fechadas até hoje (ao vivo, a partir de 13/10/2026); `acerto`, `expectativa_pct` (média por operação, líquida de custo, fração) e
`payoff` ficam `null` com zero operações. **Não são comparáveis um a um com a pesquisa**: aqui cada sinal é uma operação de R$ 6.000, sem o limite de 10
posições que o livro da pesquisa tinha. `evidencia[]`: `variante`, `setup`, `sobreposicao`, `rotulo`, `descoberta`, `validacao`, `prova` (`null` enquanto fechada), `dsr`
(Sharpe deflacionado), `status`, `status_texto`, `motivo`, `passaria_com_custo_leve` (sensibilidade descritiva, fora do pré-registro).

`status`: `so_medido` (sem capital), `medindo` (passou nas 3 etapas; capital marcado como "medindo" até o Sharpe deflacionado chegar a 0,95), `validado`, `liberado`
(decisão escrita do Douglas, **sem evidência de teste**: a tela deve dizer isso ao lado).

### `fechadas_recentes[]`

`id`, `setup`, `ticker`, `modo`, `entrada_em`, `saida_em`, `preco_entrada`, `preco_saida`, `qtd`, `valor`, `motivo_saida` (`stop`, `gap_stop`, `alvo`, `gap_alvo`, `tempo`),
`texto_saida`, `resultado_rs`, `resultado_pct` (líquidos de custo nos dois lados), `r_multiplo` (resultado em múltiplos do risco planejado; abaixo de -1 = a perda passou do
risco, como no gap), `pregoes`, `porque`, `origem_saida` (`vivo` = o robô viu durante o pregão; `conciliacao` = refeito pela barra oficial da B3 na manhã seguinte).

## M1 e M2: a camada de julgamento da mesa (prova viva)

Pedido do Douglas ("o robô precisa pensar como gestor de fundo"): medir, com honestidade, se o julgamento da mesa tem informação. **Sem teste histórico** (julgamento escrito num
dia não tem série de 15 anos): só prova viva, daqui para a frente. Toda linha de M1/M2 leva `etiqueta: "camada de julgamento: sem teste histórico; só prova viva"` e
`camada_de_julgamento: true`; a tela deve mostrar essa etiqueta ao lado do nome do setup, no placar e na evidência.

| Setup | O que mede | Sinal |
|---|---|---|
| **M1** convicção da mesa | se os papéis que a mesa prefere sobem | uma vez por visão da mesa, cada papel com convicção **+1 ou +2** vira uma **compra medida** de R$ 6.000 |
| **M2** veto da mesa (espelho) | se o veto tem informação: **se o veto é bom, M2 perde** | uma vez por visão, cada papel com convicção **-2** vira uma **compra medida** de R$ 6.000 |

**Texto obrigatório de M2 na tela:** "mede o que teria acontecido com os papéis vetados". **Não é operação vendida** e não é recomendação: é a medição do veto.

Regras (iguais para os dois): a visão é identificada pelo `gerado` do `visao_mesa.json` e medida **uma vez** (o estado guarda as visões já medidas, em `estado.json -> visoes_medidas`);
entrada na abertura do primeiro pregão depois do `gerado` (antes das 10h de um dia de pregão: a abertura do mesmo dia); **stop em 2,0 ATR, alvo em 3,0 ATR e saída no 10º pregão no
máximo, os mesmos números do setup E1** (lidos dele); ATR e preço de referência do último fechamento antes da entrada; não repete o papel enquanto a medida anterior do mesmo
setup estiver aberta; papel sem barras no painel (fora do universo de giro, ticker novo) fica de fora e aparece em `medidas_mesa.sem_dado` com o motivo.
**Nunca recebem capital pela regra de evidência**: `status` é sempre `so_medido`, salvo `liberado` por decisão escrita do Douglas (`swing_config.json`, `"liberar": ["M1.S0"]`);
mesmo liberado, M2 não recebe capital, porque o veto da própria mesa barra a compra do papel vetado.

Elas entram no `placar.medido[]` (variantes `M1.S0` e `M2.S0`, `pesquisa_descoberta`/`pesquisa_validacao` = `null`), em `evidencia[]` e em `regras.setups[]` como as outras, e são resolvidas
pelas barras oficiais na manhã seguinte, como qualquer medida. Na boleta e em `candidatas_hoje.linhas[]` aparecem com `setup: "M1"`/`"M2"`, `destino: "medida"` e `entrada_em`.

Comando que acrescenta M1/M2 de uma visão nova a uma boleta **já emitida**, sem refazer as candidatas que estão nela (idempotente; o robô também o roda toda manhã depois da boleta):
`cd ~/Desktop/quant-b3 && PYTHONPATH=. .venv/bin/python -W ignore -m quant.swing.boleta --so-mesa`.

## Véspera do resultado (regra do gestor, sem capital hoje)

O gestor não abre compra com capital na véspera do resultado do papel (exceto nos setups D1 e D2). A data vem de `proximo_resultado` da mesa ou da ficha do terminal
(`ficha["proximo_resultado"]["proximo"]["data"]`; atenção: o `data` de cima, no mesmo dicionário, é o dia da coleta). Com `resultado_antes_da_abertura` conhecido, a véspera é um dia só: resultado
**antes da abertura** de D, a véspera é D-1; resultado **depois do fechamento** de D, a véspera é o próprio D. Sem o campo vale a janela conservadora (bloqueia se o resultado é no dia da
entrada ou no pregão seguinte). A linha da candidata mostra o motivo, por exemplo "véspera de resultado (14/10/2026, antes da abertura)".

## O que a tela deve explicar ao Douglas (sem sigla solta)

- **Stop** é a ordem que sai se o preço cair até o nível combinado; no robô é uma ordem a mercado simulada: sai no último preço visto, que pode ficar abaixo do
  stop; se o papel abrir abaixo do stop (gap), sai na abertura, pior que o stop. **Alvo** é a saída com lucro combinado. **Prazo** é o último pregão em que a posição
  pode ficar (o 10º, contando o dia da entrada).
- **ATR** (amplitude média diária dos últimos 14 pregões) é a régua do stop e do alvo.
- **Só medido** não é recomendação nem posição: é o robô registrando o que teria acontecido, para o placar crescer com dado novo.
- Nada aqui é ordem enviada à corretora: é simulação.

## De onde vêm os números e quando mudam

- Rodada da manhã (`python -m quant.robo preparar --modulo swing`, ou o primeiro passo de `dia --modulo swing`): concilia o que ficou aberto com as barras oficiais do
  dia anterior, acha os sinais do último fechamento, passa pelo gestor (mesa, véspera de resultado, tamanho, exposição) e grava a boleta e a tela.
- Pregão: o robô entra nas ordens COM capital na abertura (10h), vigia stop, alvo e prazo e regrava a tela a cada ~10 s. As operações só medidas não saem durante o
  pregão: são resolvidas pelas barras oficiais na manhã seguinte.
- Arquivos do estado: `quant/saida/swing/` (`estado.json`, `fechadas.jsonl`, `boleta/AAAA-MM-DD.json`, `serie.json`). Decisão do Douglas sobre capital e limites:
  `quant/saida/swing_config.json` (`liberar`, `risco`, `teto_nome`, `max_posicoes`, `capital`), sempre dentro de limites sensatos; sem o arquivo valem os padrões do
  pré-registro (`quant/saida/pesquisa_swing/PRE_REGISTRO.md`).
