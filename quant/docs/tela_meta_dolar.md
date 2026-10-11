# Contrato da tela: objetivo do dia do mini-dólar (bloco `meta` do `quant.json`)

Desde 11/10/2026 o robô de day trade (`quant/daytrade/robo_fluxo.py`) grava, junto com o resto do `quant.json` (`tipo: "daytrade"`), o bloco `meta`.
É aditivo: nada do que a tela já lê mudou de lugar. Quem escreve é só o robô; a tela só lê.

Onde está o arquivo: `~/Desktop/terminal-artefato/web/d/x/quant.json` (e a cópia em `~/Desktop/terminal-artefato/cache/out/pagina/quant.json`),
regravado a cada ciclo do robô (`vivo.intervalo_s`, em pregão). Fora de pregão fica com o último estado.

## Duas coisas diferentes (não misturar na tela)

Em `quant/saida/risco_robo.json`, as duas em reais **líquidos de custo**:

| Chave | O que é | Valor hoje | O robô faz |
|---|---|---|---|
| `objetivo_dia_rs` | **OBJETIVO** do Douglas: 0,10% ao dia | R$ 100 | **Nada.** É só placar: o robô NÃO zera nem para ao bater. |
| `meta_dia_rs` | **TETO**: o ganho que zera tudo e para até amanhã | R$ 1.000 (1%, escolha dele de 08/10) | Bateu: zera a mercado e para o dia. |

Por quê: a medição de 11/10/2026 em 1.055 pregões (`quant/pesquisa/META_DIA.md`) mostrou que parar em R$ 100 derruba o resultado médio da regra que ganha
(reversão do dado) de R$ 34 para R$ 2 por pregão, sem reduzir a pior perda. Decisão do coordenador até o Douglas responder.
**Interruptor:** para o robô parar ao bater o objetivo, basta `meta_dia_rs: 100`. Sem `objetivo_dia_rs` não há objetivo: **o bloco `meta` não existe no arquivo** (a tela não mostra nada de objetivo).

## O bloco `meta` (só existe se houver `objetivo_dia_rs`)

```json
"meta": {
  "objetivo_rs": 100.0,             // o objetivo, em reais
  "objetivo_pct": 0.001,            // objetivo_rs / capital, fração (0,001 = 0,10%). Quem formata é a tela: "0,10% ao dia"
  "capital": 100000.0,
  "liquido": true,                  // sempre true: depois de custos
  "hoje_rs": 37.2,                  // o dia como a trava enxerga: realizado + aberto, líquido, mais as regras que já rodaram hoje
  "hoje_pct": 0.000372,
  "pct_do_objetivo": 0.372,         // hoje_rs / objetivo_rs; passa de 1,0 quando passou do objetivo; negativo no prejuízo
  "faltam_rs": 62.8,                // max(objetivo_rs - hoje_rs, 0)
  "atingido": false,                // hoje_rs >= objetivo_rs AGORA (o dia pode passar e voltar: o robô segue operando)
  "tocou_hoje": false,              // o dia chegou ao objetivo em algum momento (pico do dia)
  "teto_rs": 1000.0,                // o ganho que zera e para o dia (meta_dia_rs)
  "teto_pct": 0.01,
  "teto_batido": false,             // o TETO foi batido hoje
  "parado_ate_amanha": false,       // true SÓ quando o TETO bateu (com o interruptor ligado, teto = objetivo)
  "robo_para_ao_bater_o_objetivo": false,   // true se teto_rs <= objetivo_rs (interruptor ligado)
  "fonte": "quant/saida/risco_robo.json",
  "fonte_teto": "quant/saida/risco_robo.json",  // ou "padrao do codigo (ParamFluxo)" quando o arquivo não traz meta_dia_rs
  "placar": {
    "pregoes": 4,                   // pregões na série do robô, o de hoje incluído (entra depois do primeiro negócio ou da fita)
    "pregoes_operados": 3,          // com pelo menos uma saída
    "pregoes_bateram_o_objetivo": 2,// dias em que o resultado fechou (ou está) >= objetivo; dias sem o objetivo guardado: o resultado contra o objetivo de hoje
    "pregoes_tocaram_o_objetivo": 2,// dias em que o pico chegou ao objetivo (guardado desde 11/10; antes, igual a bateram)
    "pct_operados_que_bateram": 0.667,  // bateram / operados; null sem pregão operado
    "media_por_pregao": 255.0,      // acumulado / pregões (dia sem negócio conta zero)
    "media_por_pregao_operado": 340.0,
    "acumulado_rs": 1020.0,         // soma do resultado líquido dos pregões da série
    "melhor_dia_rs": 1200.0, "pior_dia_rs": -300.0,
    "desde": "2026-10-08",
    "pregoes_bateram_a_meta": 2     // apelido antigo de pregoes_bateram_o_objetivo
  },
  // apelidos dos nomes da primeira versão do bloco (11/10, de manhã): agora significam o OBJETIVO, não o teto
  "meta_rs": 100.0, "meta_pct": 0.001, "pct_da_meta": 0.372, "atingida": false
}
```

Campos que já existiam e continuam: `resultado.meta` e `resultado.teto` = o **teto** (R$ 1.000), `resultado.objetivo` = o objetivo (ou `null`),
`resultado.dia`, `resultado.trava` / `resultado.motivo_trava` (`"meta"` quando o teto bateu), `vivo.fase == "meta_batida"` com `vivo.fase_texto`
("Teto de ganho do dia atingido (R$ 1.005; o robô para ao ganhar R$ 1.000). Parado até amanhã.") só quando o teto bate. `serie[]` (por pregão: `data`, `resultado`,
`operacoes`, `patrimonio`; **novos**: `objetivo_rs`, `objetivo_batido`, `objetivo_tocado`, `meta_rs` e `meta_batida`, estes dois do teto). `regras.itens[]`: o primeiro item é
"Objetivo do dia: R$ 100 (0,10%). O robô não para ao bater o objetivo: no histórico de 1.055 pregões, parar em R$ 100 baixou o resultado médio de R$ 34 para R$ 2 por pregão
sem reduzir a pior perda. O ganho que zera e para o dia é R$ 1.000." Os números vêm de `quant/pesquisa/meta_dia/constantes_medicao.json` (fonte e data dentro); sem o arquivo,
o texto sai sem os números.

## Sugestão de tela (a decisão é do agente da tela)

- Uma linha de progresso do **objetivo**: `hoje_rs` de `objetivo_rs` (barra de 0 a `pct_do_objetivo`, cortada em 100%), "faltam R$ X". Passou do objetivo (`atingido`): "Objetivo do dia batido: R$ 105"
  em tom de fato, **sem** "parado": o robô segue operando.
- O **teto** só aparece como informação pequena ("para ao ganhar R$ 1.000"); `parado_ate_amanha` true → "Teto do dia atingido. Parado até amanhã."
- Placar em uma linha: "X de Y pregões bateram o objetivo · média R$ Z por pregão operado · acumulado R$ W desde DD/MM".
- Pregão sem negócio: `hoje_rs` = 0 e `pct_do_objetivo` = 0; não mostrar "0%" em vermelho.
- Sempre a palavra **simulação** (o robô não envia ordem) e que objetivo e teto são **líquidos**. Nada de "garantido", "seguro" ou recomendação.
- Prejuízo: `hoje_rs` e `pct_do_objetivo` negativos. A perda máxima do dia continua em `resultado.perda_maxima` (-R$ 1.000); semana e queda em `risco.*`.

## Casos de borda

- Sem `objetivo_dia_rs`: **sem** a chave `meta` (não é `null`): a tela não desenha o bloco. O teto continua em `resultado.meta`.
- Pregão sem fita e sem negócio: o dia ainda não está em `serie`; o `placar` conta só os anteriores. Série vazia: `placar.pregoes == 0`, médias e `desde` `null`.
- O robô lê `risco_robo.json` ao iniciar (como os outros limites): mudar o objetivo ou o teto no meio do dia só vale no próximo início.
- Interruptor ligado (`meta_dia_rs: 100`): `robo_para_ao_bater_o_objetivo` true, o robô para ao bater e `parado_ate_amanha` acompanha `teto_batido`.

## Quem testa isto

`quant/testes/test_daytrade_fluxo.py`: `test_chaves_do_arquivo_de_risco_e_os_textos_saem_do_valor`, `test_objetivo_nao_zera_o_robo_mas_o_teto_zera_e_para_ate_amanha`,
`test_interruptor_meta_dia_rs_100_faz_o_robo_parar_ao_bater_o_objetivo`, `test_sem_objetivo_nao_ha_bloco_meta_e_o_teto_segue_valendo`,
`test_tela_traz_o_bloco_do_objetivo_e_o_placar_dos_pregoes` e `test_avisos_e_fase_do_setup_de_niveis_saem_do_modo_robo`.
