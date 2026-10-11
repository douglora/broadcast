# A meta de R$ 100 por dia no mini-dólar: o que o passado diz (11/10/2026)

Mandato do Douglas (11/10): "a parte de mini dólar precisa complementar, especulando, aqui, pode ser seguro, vamos manter um objetivo de fazer 0,10% ao dia líquido".
Sobre R$ 100 mil: **R$ 100 líquidos por dia**. Tudo é simulação. Nada de regra de entrada ou de saída foi trocado no robô: só a meta (agora lida de arquivo),
os textos e esta medição. Motor: `quant/pesquisa/meta_dia.py` (conferido contra o `historico.py` do robô: mesmos negócios, centavo a centavo, sem a meta).
Dados: barras de 1 minuto do laboratório, DESCOBERTA 10/2021 a 12/2024 (805 pregões) e VALIDAÇÃO 2025 (250). **2026 não foi aberto** (já foi prova das regras do dado e do clímax).
Regras congeladas, com os números lidos do código do robô: dado americano (2 min, gatilho 3 pontos, stop 40, 120 min), clímax (5 pontos, 3x, stop 10, alvo 80%, 20 min), teste de nível.

## Resposta direta

**0,10% ao dia NÃO é atingível com o que existe.** A única regra com vantagem estatística, a reversão do dado americano, rende em média **R$ 34 por pregão**
(0,034%; R$ 707 por mês; t 3,2) nos 1.055 pregões de 10/2021 a 12/2025, e isso sem teto. Em 2025 foi só R$ 6,6 por pregão. O dia fecha em +R$ 100 ou mais
em **19% dos pregões** (21% na descoberta, 11% em 2025); em 62% dos pregões o dado nem dá sinal.

**E a meta de R$ 100 como teto piora o que existe**: o robô zera ao tocar +R$ 100, e a média do dado cai de **+R$ 34 para +R$ 2 por pregão** (+R$ 38 por mês, t 0,4);
em 2025 fica **negativa (-R$ 7 por pregão)**. Toca a meta em 32% dos pregões, mas os 16% de negócios que não chegam lá perdem R$ 479 em média.

## Decisão de 11/10 (coordenador, até o Douglas responder): R$ 100 é OBJETIVO, não teto

A medição abaixo mostrou que parar em R$ 100 não deixa nada mais seguro (o pior dia continua em -R$ 815) e derruba a média do dado de +R$ 34 para +R$ 2 por pregão. O Douglas escreveu
"manter um **objetivo** de fazer 0,10% ao dia". Por isso são duas chaves em `quant/saida/risco_robo.json`:
`objetivo_dia_rs: 100` (só placar na tela; o robô NÃO zera nem para ao bater) e `meta_dia_rs: 1000` (o teto que zera e para, a escolha dele de 08/10, agora explícita).
**Interruptor: para o robô parar ao bater o objetivo, basta `meta_dia_rs: 100`.** Sem `objetivo_dia_rs` não há objetivo (a tela não mostra o bloco).

## O que mudou no código

| Onde | O quê |
|---|---|
| `quant/saida/risco_robo.json` | `objetivo_dia_rs: 100.0` e `meta_dia_rs: 1000.0`, com motivo e data (11/10/2026) no campo `motivo`, inclusive o interruptor. |
| `quant/daytrade/chave.py` | `risco()` devolve as duas chaves (None se ausentes ou inválidas; sem `meta_dia_rs` vale o padrão do código, R$ 1.000). |
| `quant/daytrade/robo_fluxo.py` | o robô aplica `meta_dia_rs` (teto) em `self.p.meta_dia_rs` e guarda `self.objetivo_rs` ao iniciar; só o teto zera e para; bloco `meta` (objetivo + teto + placar) no `quant.json` só quando há objetivo; a série por pregão guarda `objetivo_rs`, `objetivo_batido`, `objetivo_tocado`, `meta_rs`, `meta_batida`; os avisos e a fase do setup de níveis saem de `climax_opera`/`niveis_opera`/`dado_opera` (antes diziam que quem opera é o clímax, que está desligado). |
| `quant/daytrade/estrategia_fluxo.py` | `objetivo_em_texto`, `teto_em_texto`, `pct_texto`, `carregar_medicao`. O texto do objetivo cita os números de `quant/pesquisa/meta_dia/constantes_medicao.json` (fonte e data dentro; gerado por `meta_dia.relatorio`); sem o arquivo, sai sem os números. |
| `quant/docs/tela_meta_dolar.md` | contrato do bloco `meta` para o agente da tela (com os apelidos antigos). |
| `quant/testes/test_daytrade_fluxo.py`, `quant/testes/test_meta_dia.py` | objetivo não zera, teto zera e para até amanhã, interruptor, sem objetivo não há bloco, textos, placar, avisos do setup de níveis; motor da medição. |

Conferido no código (vale para o teto, `meta_dia_rs`, e para o placar do objetivo): a comparação (`robo_fluxo.py`, ciclo) é do **resultado líquido do dia**: o que já fechou depois de custos (`o["resultado"]` = pontos x R$ 10 x contratos
menos 2 x R$ 1,20 x contratos) mais o lucro aberto ao último preço menos o custo de ida e volta do que ainda está aberto, mais o resultado das outras regras do dia. Bateu o teto: `ef.zerar` a mercado
(1 tick pior), `trava = "meta"`, a trava fica salva no estado do dia (reiniciar o processo não religa) e o dia seguinte é outro estado. Como a saída é a mercado, o dia fecha
1 tick abaixo do gatilho (com o interruptor em R$ 100, perto de **R$ 90 a R$ 100**). A regra dos 20% de devolução (piso de R$ 100 realizados) só tem papel com o teto acima de R$ 100.

## A medida (10/2021 a 12/2025, 1.055 pregões: descoberta 805 + validação 250; 2 contratos, depois de custos e deslize)

"Fecham >= +100" é o dia SEM teto que termina em R$ 100 ou mais. "Tocam +100" é o dia COM teto em que a meta foi batida (o dia para). Entre parênteses: descoberta / validação.

| Regra | Negócios (sem / com teto) | % pregões que fecham >= +100 (sem teto) | % que tocam +100 (com teto) | Média por pregão, sem teto | Média por pregão, com teto | Por mês (21 pregões), sem / com | Pior dia | Queda máxima do acumulado, sem / com |
|---|---|---|---|---|---|---|---|---|
| A. Dado americano (opera) | 400 / 400 | 18,7% (21,1 / 10,8) | 31,9% (36,0 / 18,8) | **+33,7** (+42,1 / +6,6) | **+1,8** (+4,7 / -7,4) | +707 / +38 | -815 | -4.150 / -3.761 |
| B. Clímax lote 2 (o código liga; `modo_robo.json` diz só medido) | 1.095 / 933 | 18,3% | 28,0% | -18,0 (-15,9 / -25,0) | -17,5 | -379 / -368 | -644 | -20.014 / -18.864 |
| C. Dado + clímax (dado primeiro) | 1.073 / 928 | 27,2% | 44,8% | +23,5 (+34,0 / -10,2) | -10,4 (-4,3 / -30,1) | +493 / -218 | -1.010 | -5.453 / -12.167 |
| D. Teste de nível (só medido) | 5.171 / 2.772 | 18,0% | 58,7% | -119,8 | -65,3 | -2.516 / -1.371 | -564 | -126.137 / -68.951 |
| E. Clímax fraco 3 pts / 2,5x (só medido) | 3.058 / 2.298 | 25,4% | 44,0% | -59,5 | -48,9 | -1.249 / -1.028 | -644 | -63.432 / -52.032 |
| F. Tudo junto (dado, clímax, nível) | 4.686 / 2.420 | 27,2% | 67,3% | -65,0 | -43,1 | -1.365 / -904 | -1.010 | -68.493 / -45.524 |

Leitura:
- **Tocar +R$ 100 em muitos pregões não é ganhar dinheiro.** O teste de nível toca a meta em 59% dos pregões e perde R$ 65 por pregão com o teto (R$ 120 sem). O clímax fraco toca em 44% e perde R$ 49.
  Quem corta o ganho em R$ 95 e deixa a perda correr (stop e tempo) perde dinheiro mesmo acertando mais da metade.
- Só a regra A tem média positiva com significância (t 3,2 sem teto), e ela vem toda de 2022 a 2024 (+R$ 42, +R$ 40, +R$ 52 por pregão); 2021 (56 pregões) +R$ 7,5; **2025: +R$ 6,6**.
- Com o clímax ligado junto (C), a média cai para +R$ 23,5 sem teto e para -R$ 10 com teto; na validação, -R$ 10 e -R$ 30 por pregão.
- O teto de R$ 100 faz o teste de nível e o clímax fraco perderem um pouco menos só porque fecham o pregão mais cedo (menos negócios); não os torna positivos.
- Mês: com o dado sem teto, 9 de 51 meses (18%) passam de R$ 2.100 (21 x R$ 100); com teto, 0 de 51. Pior mês do dado: -R$ 2.328 sem teto, -R$ 1.548 com teto.

### Por ano, o dado (R$ por pregão; tentativas de 2 contratos)

| Ano | Pregões | Sem teto | Com teto de R$ 100 | % dos negócios que tocam +100 |
|---|---|---|---|---|
| 2021 (out a dez) | 56 | +7,5 | -1,8 | 86% |
| 2022 | 250 | +41,9 | -10,7 | 84% |
| 2023 | 248 | +40,3 | +18,7 | 88% |
| 2024 | 251 | +51,8 | +7,6 | 87% |
| 2025 | 250 | +6,6 | -7,4 | 76% |

## O "seguro" sem a armadilha (o dado com o teto de R$ 100)

Alvo pequeno com stop largo: acerta muito e a conta fecha perto de zero.

| | Negócios | Quanto | Média | Soma |
|---|---|---|---|---|
| Tocam +R$ 100 e saem na meta | 337 (84,3%) | | +R$ 95 | +R$ 32.082 |
| Não tocam: stop de 40 pontos | 18 | | -R$ 815 | -R$ 14.666 |
| Não tocam: saem por tempo (120 min) | 45 | | -R$ 345 | -R$ 15.506 |
| **Expectativa por negócio** | 400 | | **+R$ 4,8** | +R$ 1.910 |

- Acerto de equilíbrio com ganho de R$ 95 e perda média de R$ 479: **83,4%**. O observado é **84,2%**: margem de 0,8 ponto. Na descoberta o acerto foi 85,8% (expectativa +R$ 11 por negócio); em 2025, 75,8% contra 81,6% de equilíbrio (-R$ 30 por negócio).
- O que o teto cede: dos 337 negócios que tocam +R$ 100, **o mesmo negócio sem teto** termina em média **+R$ 195** (somados: R$ 65.712 contra R$ 32.082); 37% terminam acima de R$ 300, mas **33% terminam NEGATIVOS**. O teto troca R$ 33.630 de ganho
  futuro pela garantia de não devolver os 33%. Resultado final: sem teto +R$ 35.540 nos 400 negócios, com teto +R$ 1.910.
- O pior dia não muda (-R$ 815, o stop cheio): o teto não protege do prejuízo, só corta o ganho. Os 16% de negócios que não chegam a +R$ 100 custam R$ 479 cada.
- Sensibilidade (só informação, não é recomendação nem mudança; mudar a meta é decisão do Douglas e qualquer regra nova passa pela FILA). Média por pregão do dado conforme o teto:

| Teto | 50 | 100 | 150 | 200 | 300 | 500 | 1.000 | sem teto |
|---|---|---|---|---|---|---|---|---|
| Descoberta (805) | -4,7 | +4,7 | +12,1 | +15,2 | +21,8 | +27,1 | +42,3 | +42,1 |
| Validação 2025 (250) | -3,4 | -7,4 | -7,1 | -2,2 | -5,2 | +0,3 | +4,0 | +6,6 |

  Quanto mais baixo o teto, menos sobra: o dado é uma regra de poucos negócios grandes, e o teto de R$ 100 a transforma em quase uma moeda.
  Ponto de decisão para o Douglas: a meta de R$ 100 como **teto** (zera e para) custa ~R$ 32 por pregão do que o dado rende; como **placar/objetivo** (a tela mostra, o robô não zera) não custa nada.
  Implementado em 11/10 (decisão do coordenador até o Douglas responder): `objetivo_dia_rs: 100` é o placar e `meta_dia_rs: 1000` é o teto. Interruptor: `meta_dia_rs: 100` para parar ao bater o objetivo.

## O que foi para a FILA (pré-registro antes de rodar, só descoberta; `quant/pesquisa/FILA.md`, "Testadas")

- **Item 16, meta como trava de entrada com a posição do dado protegida em +R$ 90** em vez de zerar: média +R$ 1,3 por pregão (teto simples +R$ 4,7, sem teto +R$ 42,1). Não passa.
  Em barra de 1 minuto a proteção vale só da barra seguinte e o preço já voltou; só tique a tique diria se ajuda de verdade.
- **Item 17, teto de R$ 100 com stop de 10, 15 e 20 pontos**: -R$ 3,9 / -R$ 5,9 / -R$ 3,7 por pregão (acerto 66 / 73 / 79%). Não passa: o stop curto troca a perda grande por perda frequente.
- Horário e lote: não entraram. O clímax perde em todos os horários (inclusive a tarde, -R$ 24,7 por negócio, `quant/estudos/LEIA.md`); o lote só escala o resultado (e o stop cheio de 40 pontos já limita a 2 contratos pela perda máxima do dia).
  "Só dias de dado" já é o que o setup do dado faz (um negócio por dia, 38% dos pregões). Nenhuma hipótese nova com expectativa positiva apareceu.
- Já existiam na FILA e seguem valendo: item 11 (continuação depois do dado das 10h de NY, 5 minutos) e a prova viva do dólar em prazo de dias (14).

## Quanto o que existe entrega de verdade

| O que opera hoje no robô | Média por pregão | Por mês | Observação |
|---|---|---|---|
| Dado americano, sem teto | +R$ 34 (+R$ 42 na descoberta, +R$ 6,6 em 2025) | +R$ 707 | t 3,2; 62% dos pregões sem negócio; 19% fecham >= R$ 100 |
| Dado americano, com o teto de R$ 100 (como está agora) | +R$ 1,8 | +R$ 38 | t 0,4; negativo em 2025 |
| Clímax (se estivesse ligado) | -R$ 18 | -R$ 379 | só entra se `climax_opera` for true; está false em `modo_robo.json` |
| Teste de nível | -R$ 120 | -R$ 2.516 | só medido |

Para chegar a R$ 100 por pregão em média, o dado teria de render 3 vezes o que rendeu em 2021-2025, ou o lote subir 3 vezes (a perda máxima do dia de R$ 1.000 não comporta com stop de 40 pontos).

## Limites desta medida

- Barras de 1 minuto: dentro do minuto o lado adverso vem primeiro (stop, depois o limite de perda do dia) e a meta depois. Isso favorece quem perde e subestima os toques da meta; o sentido do erro é o conservador.
  Tique a tique, a meta e a proteção do item 16 seriam medidas melhor.
- A série do WDO do laboratório é ajustada por diferença nos contratos antigos: a regra do dado não depende do nível, a de nível depende dos números redondos (por isso o nível aqui é uma medida mais fraca).
- 2026 ficou de fora de propósito; para o dado a prova de 2026 já foi aberta (`quant/estudos/LEIA.md`: 54 negócios, +R$ 56 por negócio com 2 contratos).
- Não há imposto de day trade nem a espera de 2 a 3 minutos que o robô tem depois de cada saída (o motor usa 2 minutos).

## Rodar de novo

`cd ~/Desktop/quant-b3`; tabela por regra: `PYTHONPATH=. .venv/bin/python -W ignore -m quant.pesquisa.meta_dia 100` (grava `quant/pesquisa/meta_dia/tabela_por_regra.csv` e `resultado_por_pregao.csv`);
relatório completo (tabelas deste documento): `... -m quant.pesquisa.meta_dia relatorio`; hipóteses 16 e 17: `... -m quant.pesquisa.meta_dia_hipoteses`
(registro em `quant/pesquisa/meta_dia/tentativas.jsonl`).
