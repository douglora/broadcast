# Fila de hipoteses do robo de day trade (mini-dolar)

A rotina da noite pega daqui ate 3 hipoteses por noite, de cima para baixo, testa SO na descoberta (quant/pesquisa/lab.py,
metodo em quant/saida/pesquisa5/BRIEF.md) e move a linha para "Testadas" com os numeros. Hipotese nova entra no fim de
"A testar". Nada sai daqui apagado: o "nao" tambem e resultado.

## A testar

6. Dados novos da B3 (quant/saida/pesquisa5/b3_dolar/LEIA.md, quando existir): posicao em aberto no dolar por tipo de
   participante (estrangeiro, banco, institucional) de ontem contra o comportamento do pregao de hoje (gap, direcao da
   manha, reversao do dado); PTAX das quatro janelas contra o preco do futuro na hora; corretoras na fita (20 pregoes).

7. Pistas da segunda rodada que dependem de dado diario da B3 (so quando a rotina tiver acumulado mais pregoes e houver
   leitura ao vivo desse dado): preco x contratos em aberto de ontem (familia posicao, regra_A) e rolagem adiantada
   (regra_C). Validar com parametros congelados em 2025 e 2026 antes de qualquer coisa.
8. Reacao a anuncio EXTRA do Banco Central no mesmo dia (venda a vista ou swap fora da agenda): 15 casos em 3 anos; rever
   quando houver mais casos (o arquivo de atuacoes e atualizado pela rotina).

9. PROVA VIVA do mini-indice, fim do dia (quant/pesquisa/regras/win_fim_do_dia.py: a tendencia do dia continua nos ultimos
   30 minutos; descoberta n 800, +R$ 15,30 por negocio, t 6,6, 7 de 7 semestres; REPROVADA na validacao de 2025: -R$ 4,47,
   acerto de 40%). A prova de 2026 NAO foi aberta. A regra opera todo dia: de tempos em tempos (a cada 20 pregoes), puxar
   as barras novas do WIN no MetaTrader e medir so os pregoes de 10/10/2026 em diante, com os parametros congelados (tempo
   25, stop 500, janela 09:00-18:30). Se a prova viva juntar 60+ negocios com media positiva e t >= 2, vira pedido de estudo.
10. O mesmo empurrao do fim do dia no mini-dolar (pista da familia win_estrutura: +R$ 8,50 por negocio, t 1,6, 7 de 7
   semestres, N=50, tempo=40, stop=60): so depois de a prova viva do indice dizer se o efeito ainda existe.

14. PROVA VIVA do dolar em prazo de dias (tendencia `tsm_media`, parametros congelados em 10/10/2026): rodar
   `quant/saida/pesquisa5/dolar_dias/coletar.py` e `sinal_hoje.py` todo dia util e comparar, so com pregoes de 13/10/2026 em
   diante, com o resultado que a regra teria dado. Precisa do pacote yfinance no .venv. Nada opera.
15. Dados gratuitos do dolar ainda sem teste (lista em `dolar_dias/RESULTADO.md`, parte 3): expectativas Focus, fluxo
   cambial contratado do BC, posicao de BRL no CME (CFTC), cambio real (IPCA x CPI), estoque de swap cambial do BC, e a curva
   de cupom cambial 2002-2021 da B3.
12. Fluxo de agressao REAL por contrato (quant/saida/pesquisa5/fluxo_mt5/RESULTADO.md): o MetaTrader da XP so marca o
   agressor no contrato vigente, e o contrato vencido some do servidor. Ha 28 pregoes do WDOX26 e 42 do WINV26 gravados
   por minuto; a fita diaria do robo acumula o mini-dolar dai para a frente. So testar leitura de fluxo com agressor real
   quando houver 120+ pregoes (por volta de 03/2027); ate la, NAO garimpar os 28 pregoes.

## Testadas

(08/10/2026) Sete frentes, mais de 12 mil medicoes: ver quant/estudos/LEIA.md. Passou so a reversao do dado americano.

(09/10/2026) Segunda rodada, com os dados da B3 e do Banco Central (quant/saida/pesquisa5/BRIEF_B3.md; notas em
quant/saida/pesquisa5/{ptax_bc,posicao,corretoras}/RESULTADO.md). Nenhuma candidata.
- PTAX das 4 janelas, base futuro x a vista, cupom cambial, estoque de swap, leiloes agendados do BC (~420 medicoes): nada
  acima do custo. Futuro "caro" contra a PTAX da janela continua, nao volta (correlacao 0,03 a 0,11). Leilao agendado nao
  tem hora nem pico nas barras; anuncio extra do BC no mesmo dia: so 15 casos (pista, t 1,0 a 1,5).
- Contratos em aberto x preco, rolagem, ajuste como ima, varejo x institucional, opcoes (dor maxima, strike carregado)
  (~2.000 medicoes): nada passa o nulo. O ajuste NAO e ima (tocar o ajuste e tao provavel quanto tocar o nivel-espelho).
  Pistas pequenas: preco e contratos em aberto de ontem subindo juntos -> segue (n 62, t 1,7 ate 12h50; t 2,2 a 2,8 ate
  16h59); rolagem adiantada -> compra ate 10h30 (n 81, t 2,7). Dependem de dado diario da B3: nao rodam ao vivo ainda.
- Penultimo dia util do mes, comprar de manha (apareceu em 3 frentes; descoberta n 39, +R$ 262, t 2,8): REPROVADA na
  prova com parametros congelados: 2025 -R$ 85 (n 12), 2026 +R$ 193 (n 9); fora da descoberta +R$ 34 (t 0,3).
- Corretoras na fita (12 pregoes de descoberta, ~1.100 medicoes): banco local compra COM o preco; XP, formadores e BTG
  compram CONTRA (12 de 12 pregoes), mas depois que a corretora para o preco nao se mexe. Detector de ordem trabalhada na
  fita anonima: nao funciona (AUC 0,50 a 0,55). Pista: fluxo do BTG nos 30 min anteriores -> +3 a +4 pontos nos 15 a 30
  min seguintes (11 de 12 pregoes), mas a corretora so sai depois do fechamento: nao e operavel com o que temos.
  VALIDACAO nos 8 pregoes guardados (29/09 a 08/10), parametros congelados: REPROVADA (media +0,50 ponto em 30 min, 5 de 8
  pregoes; pedia 6 de 8 e mais de 1,05). O fato estavel se repetiu em 7 a 8 dos 8: banco local com o preco; XP, varejo e
  formadores contra. A familia fecha sem pista viva; os ticks seguem sendo baixados porque a B3 so guarda 20 pregoes.

(09/10/2026, noite) Terceira rodada: mini-indice e acoes (quant/saida/pesquisa5/BRIEF_3.md; notas em
quant/saida/pesquisa5/{win_eventos,win_estrutura,acoes_eventos,acoes_relativo}/RESULTADO.md). Nenhuma regra aprovada.
- WIN, eventos de hora marcada (~9.700 medicoes): a reversao do dado americano NAO funciona medida no proprio indice; usar a
  reacao do DOLAR para operar o indice da +R$ 41 por negocio (t 2,4, 7 de 7 semestres), mas e a mesma aposta do setup do
  dolar (97% dos mesmos dias, correlacao 0,49): nao e regra independente. Abertura das acoes as 10h, abertura de NY, leilao
  de fechamento, vencimentos, rebalanceamento: nada acima do custo ou sem amostra.
- WIN, estrutura (~3.400 medicoes): UMA candidata forte na descoberta, a tendencia do dia continua nos ultimos 30 minutos
  (t 6,6), REPROVADA na validacao de 2025 (ver item 9 de "A testar"). O pico de volume de 9 minutos antes do fim continua
  la em 2025; a direcao deixou de acompanhar a tendencia do dia. Reversao de barra grande, valor justo contra dolar/juros/
  S&P, razao de variancia, abertura, momentum da primeira meia hora: reais e iguais ao custo, ou nada.
- Acoes, eventos e leiloes (~900 medicoes, 14 ativos): gap de abertura continua mais do que fecha; primeira meia hora, ultima
  hora, vencimento de opcoes, fim de mes: no maximo 5 pontos-base brutos contra 11 de custo. Nenhuma candidata.
- Acoes, valor relativo (~1.000 medicoes): reversao do residuo contra o indice (teto de 3 pontos-base), pares (2 a 8 contra
  22 de custo das duas pontas), ordenacao, lider e seguidor (o indice e o Itau antecipam as outras em 1 a 5 pontos-base):
  tudo real e 3 a 5 vezes menor que o custo. Nenhuma candidata.
- Dado: as series de acoes do MetaTrader sao AJUSTADAS por diferenca (o nivel antigo das pagadoras de dividendo fica
  deslocado: PETR4 a R$ 8,43 em out/2021); medir em reais normalizados ou em 2023-24. A ultima barra das acoes traz o preco
  do leilao de fechamento: cortar essa barra e as 3 anteriores.

(09/10/2026, 21h-22h) Quarta rodada: MULTIFATOR (quant/saida/pesquisa5/BRIEF_4.md; notas e `modelo.py::sinais(parte)` em
quant/saida/pesquisa5/{multi_win,multi_wdo,multi_acoes}/). Soma de 18 a 68 fatores por mercado, regressao ridge com pesos
reestimados todo mes sobre 18 meses, medida so fora da amostra (04/2023 a 12/2024, 436 pregoes). Nenhuma candidata.
- Mini-indice: correlacao previsao x retorno 0,063 (t 3,8), mas toda ela vem do fim do pregao (tendencia do dia + distancia
  ao fim); barra grande, valor justo e "dolar na frente" somam zero (correlacao -0,003 a +0,009). Melhor regra: 206
  negocios, +R$ 12,26 (t 2,5), R$ 5,80 por pregao; a regra simples do fim do dia rende o dobro na mesma janela (e falhou
  em 2025). Cauda de 1%: +19,7 pontos liquidos (t 2,5).
- Mini-dolar: correlacao 0,022 a 0,024; caudas liquidas negativas no desenho do plano. Melhor soma (v3, H60, K2): 98
  negocios, +R$ 67,60 (t por pregao 1,9), mas 43 deles coincidem com a regra aprovada do dado; sem eles +R$ 34,70 (t 1,1).
  O que carrega: dado de NY e o empurrao do fim do pregao. Valor justo, barra grande e fluxo do cheio somam zero.
- Acoes (painel de 14 ativos): correlacao 0,036 (t 6,8, real e estavel), mas a cauda rende 1,3 a 2,7 pontos-base brutos
  contra 11 a 14 de custo; com a regra de 2 ou 3 vezes o custo o modelo nao abre nenhum negocio.
- Conclusao: os efeitos pequenos nao se somam; cada um ja e quase tudo o que ha. A unica assimetria que aparece de novo e o
  empurrao do fim do pregao (indice e dolar), que mudou de sinal em 2025: vai para a prova viva (item 9 de "A testar").

(10/10/2026) Quinta rodada: o metodo Chan + Lopez de Prado (quant/pesquisa/METODO.md; ferramentas em quant/pesquisa/ldp.py;
contas em quant/estudos/2026-10-10_metricas_ldp.py e 2026-10-10_fim_do_pregao_meta.py).
- Regua nova na regra aprovada (reversao do dado, gatilho 3): Sharpe anual liquido 1,82 na descoberta, 0,45 em 2025, 1,06 em
  2026; 1,50 nos 5 anos; 0,72 fora da descoberta (443 pregoes). Sharpe deflacionado nos 5 anos: 0,80 com 100 tentativas,
  0,43 com 2.500, 0,20 com 35.000. NAO passa no criterio novo (pede Sharpe > 1 fora da amostra e deflacionado > 0,95).
  Continua sendo a melhor evidencia do dolar, positiva nos 6 anos, mas e uma vantagem fraca.
- Fim do pregao no mini-indice: Sharpe 3,68 de 2021 a 2024 (real: deflacionado 0,94 com 2.500 tentativas mesmo incluindo
  2025). Meta-rotulagem minima declarada antes (so opera se a media dos ultimos 60 pregoes da propria regra for positiva):
  10/2021 a 12/2025 Sharpe 2,88, queda maxima R$ 1.476, deflacionado 0,96 com 35.000 tentativas, permutacao p 0,000,
  plato em 40/60/80. PROVA FINAL DE 2026, aberta UMA vez em 10/10/2026: REPROVADA. Primaria: Sharpe -3,65, acerto de 38%,
  -R$ 17,68 por pregao (o efeito INVERTEU); com o filtro: 52 negocios, -R$ 14,35 por negocio, Sharpe -1,17 (o filtro limitou
  a queda a R$ 880 contra R$ 3.769, mas nao salvou). 2026 esta gasto para esta regra.
- Variante adaptativa (opera no lado que vem dando certo nos ultimos 60 pregoes; `regra_adaptativa`), declarada DEPOIS de
  ver 2026: descritivo nos 5 anos Sharpe 2,28, com 2025 -R$ 2,70 e 2026 +R$ 0,80 por pregao. Nao ha dado antigo que a prove:
  so a prova viva (desde 13/10/2026).

(10/10/2026, tarde) O resto do metodo: meta-rotulagem do setup do dado e barras de volume (notas em
quant/saida/pesquisa5/{meta_dado,barras_volume}/RESULTADO.md). Nenhuma candidata; a prova de 2026 NAO foi aberta para elas.
- Meta-rotulagem do dado (864 eventos de reacao >= 1 ponto, 10/2021-12/2025, validacao combinatoria 6/2 com purga, 15
  divisoes, 66 configuracoes): o secundario NAO melhora o primario. Sharpe mediano das divisoes 0,64 (8 caracteristicas,
  logistica, corte 0,55) contra 1,56 da regra simples de gatilho 3; ganha em 4 de 15 divisoes; em 2025 todas as variantes
  perdem. So o tamanho da reacao carrega informacao (AUC 0,55; as outras 7 juntas 0,494). Volume, confirmacao do indice e
  dos juros, regime e payroll parecem informativos na amostra inteira e somem fora dela. Mantido o gatilho de 3 pontos.
- Barras de volume (WIN e WDO, 7 hipoteses, 50/100/200 barras por pregao contra barras de tempo, ~3.400 simulacoes): a barra
  de volume nao muda o quadro. WDO: Sharpe mediano fora da amostra de -1,3 a -1,5 (o custo e 31% do desvio de uma barra).
  WIN: -0,26 em volume e -0,47 em tempo. Barra rapida e direcional REVERTE, nao continua.
  Pista pos-hoc, nao candidata: WIN, 5 barras de volume seguidas na mesma direcao ate as 11h, seguir por 4 barras: 465
  negocios, +R$ 15,08 (t 2,07), Sharpe 1,03, 2025 positivo, plato de +-20%, deflacionado 0,04 a 0,07; no WDO e negativo.
  Parametros congelados em quant/saida/pesquisa5/barras_volume/modelo.py: candidata a PROVA VIVA (escrever como regra de
  quant/pesquisa/regras/ e por em provas_vivas.json), nao a prova de 2026.
- Conta que vale para tudo: com ~1.050 pregoes, passar o Sharpe deflacionado de 0,95 exige Sharpe anual acima de ~2,05 com
  100 tentativas e ~2,7 com 8.500. Regra de Sharpe 1 nao passa por historico; so por dado novo.
- Defeito corrigido: `ldp.barras_de_volume` datava a barra um minuto antes de ela estar completa (um minuto de futuro).

(09/10/2026, rotina da noite) Itens 1, 2 e 3 da fila, so na descoberta (805 pregoes; scripts em
quant/saida/pesquisa5/noite/2026-10-09/). Nenhuma candidata.
- Item 1, reversao de horas depois de evento de NY (abertura da bolsa 9h30, dados das 10h, Fed 14h so em dias de FOMC;
  reacao de 2 e 5 minutos, limiares de 3 e 5 pontos e de 1,5 vez a media; saida em 30/60/120 min; 54 triagens brutas):
  MORTA. Abertura de NY: +0,6 a +2,1 pontos brutos, t no maximo 1,5, sinal troca de ano para ano. Dados das 10h com
  reacao de 2 minutos: t no maximo 1,0. Fed: so 16 a 21 dias, sem amostra. Pista nao prevista: dados das 10h medidos em 5
  minutos CONTINUAM (nao revertem), t -2,1 no sentido contrario ao testado: virou item 11 de "A testar".
- Item 2, tarde de dia coerente (dolar, juros DI27/DI29 e mini-indice no mesmo sentido desde a abertura; dolar continua das
  12h30 as 17h00; 363 dias com sinal; 4 variantes): MORTA. Bruto -0,5 a +1,3 pontos, t no maximo 0,95, e a regra coerente
  nao supera o controle que olha so o dolar (+0,2 a +0,4 pontos, t 0,3 a 0,8). Coerencia nao acrescenta nada.
- Item 3, primeira meia hora grande continua de 13h00 a 17h20 (limiar normalizado em z = reacao / media dos 20 pregoes
  anteriores; z de 1,0, 1,5 e 2,0; 12 triagens + 2 simulacoes): MORTA. Na triagem bruta so z >= 1,0 aparece (+2,3 pontos
  em 120 min, t 2,5, n 323), sem dose-resposta (z >= 2,0 e mais fraco). Com custo, stop 40 e saida em 120 min: +R$ 11,55
  por negocio (t 0,6, 3 de 7 semestres); saindo as 17h20: +R$ 38,14 (t 1,5, 5 de 7 semestres, 2023S2 -R$ 98). Nao e
  candidata (pedia t 3). sem_futuro: passou.

### 10/10/2026, tarde: dolar global e fluxo de agressao (pedido do Douglas: "verifique a viabilidade para o daytrade")

- O dolar la fora anda na frente do mini-dolar? (quant/saida/pesquisa5/global_lidera/; barras de 1 minuto da demo da
  MetaQuotes: peso mexicano, rand, yuan, euro, iene, S&P, ouro; descoberta 02/2024 a 12/2024, 227 pregoes): MORTA em 1
  minuto. Correlacao no mesmo minuto de 0,37 com o peso; com o minuto anterior la fora, zero (-0,009 a +0,006). Nos 1% de
  minutos mais fortes o mundo mandava 3,72 pontos e o mini-dolar fez 3,51 no mesmo minuto (seguinte: -0,11). O "atraso"
  contra a cesta rende +0,45 a +0,84 ponto bruto (t 3 a 4), menos que o custo: 8 simulacoes a mercado de -R$ 17,71 a
  -R$ 28,93 por negocio e 6 com entrada parada de -R$ 8,42 a -R$ 19,68. Validacao e prova nao abertas.
- Saldo de agressao por minuto antecipa o mini-dolar? (quant/saida/pesquisa5/fluxo_mt5/; serie continua WDO$N do
  MetaTrader da XP, agressor inferido pela regra do tique, descoberta 07/2025 a 12/2025, 119 pregoes; 25 triagens): MORTA
  na triagem. Nenhuma continuacao; devolucao de 0,1 a 0,7 ponto em 1 a 20 minutos (melhor t: -4,4 no saldo de 5 minutos,
  -0,61 ponto em 10 minutos), menor que o custo de 1,2 ponto. Absorcao: n 117, nada.
- Dolar global em SEGUNDOS (um preco por segundo de 5 pregoes, 05 a 09/10/2026, WDOX26 contra USDMXN, USDZAR, EURUSD, USDJPY e
  US500; `global_lidera/segundos.py`; descritivo): MORTA. O pico da correlacao de retornos de 5 segundos e em 0 segundo e
  cai igual para os dois lados. Nos 0,2% maiores trancos la fora o mini-dolar anda 0,6 a 0,9 ponto DURANTE os mesmos 5
  segundos; entrando 1 a 5 segundos depois sobra -0,05 a -0,55 ponto antes do custo de 1,2 ponto.
- Mini contra cheio, WDO x DOL (`quant/saida/pesquisa5/dolar_arbitragem/`; negocio a negocio da B3 em milissegundo, 23
  pregoes): MORTA para quem tem 200 a 500 ms. Os dois precos sao iguais em 59% do tempo e o ajuste termina em ate 20 ms.
  Diferenca de 2,5 pontos ou mais (o custo do par): 1 a 2 vezes por dia, 50 ms de duracao. Robo simulado com atraso de
  200/500 ms: negativo com custo realista nos 30 cenarios. Rolagem (28 a 30/09): diferencial oscila 0,44 ponto, nunca
  chega ao custo. Convergencia do contrato que vence para a PTAX: existe (0,4 ponto), pequena demais.
- Dolar com prazo de DIAS (`quant/saida/pesquisa5/dolar_dias/`; PTAX em excesso do carrego, 2000 a 2021, 34 tentativas):
  NENHUMA passou. Tendencia (momentum de 21/63/126 dias) teve Sharpe 1,1 a 1,2 em 2000-2015 e caiu para 0,16 a 0,26 em
  2016-2021 (queda maxima de 17% a 28%); carrego, DXY, EMBI, VIX, commodities, fim de mes, Copom e Fed: nada na validacao.
  A prova 2022-09/2026 NAO foi aberta. Candidata a prova viva (so medir): `tsm_media`, via `dolar_dias/sinal_hoje.py`.

(11/10/2026) META DO DIA DE R$ 100 LIQUIDOS NO MINI-DOLAR (mandato do Douglas: "pode ser seguro... 0,10% ao dia liquido"). Medicao completa em
`quant/pesquisa/META_DIA.md` (motor em `quant/pesquisa/meta_dia.py`, conferido contra o `historico.py` do robo: mesmos negocios). Descoberta 10/2021-12/2024
(805 pregoes) e validacao 2025 (250); 2026 nao foi aberto. Duas hipoteses pre-registradas ANTES de rodar, so descoberta; nenhuma passou:
- Item 16, meta como trava de entrada com a posicao do dado protegida em +R$ 90 (em vez de zerar): media por pregao +R$ 1,3 (t 0,2) contra +R$ 4,7 do teto
  simples e +R$ 42,1 do dado sem teto; 338 negocios, acerto 82,5%, ganho medio R$ 90, perda media R$ 408; pior dia -R$ 815; queda maxima R$ 5.482.
  NAO PASSA (pedia superar +R$ 4,7). Em barra de 1 minuto a protecao vale so a partir da barra seguinte e o preco ja voltou: ela vira o teto simples
  um pouco pior: 7 negocios correm ate o tempo (media +R$ 665), 12 que o teto simples fecharia em +R$ 95 saem da protecao perto de zero (media -R$ 16) e os
  outros 271 ganham R$ 90 em vez de R$ 95; so tique a tique diria se a protecao ajuda de verdade.
- Item 17, teto de R$ 100 com stop de 10, 15 e 20 pontos (em vez de 40): media por pregao -R$ 3,9 (stop 10, acerto 66%), -R$ 5,9 (stop 15, acerto 73%) e
  -R$ 3,7 (stop 20, acerto 79%); pior dia -R$ 215, -R$ 315, -R$ 415. NAO PASSA (pedia superar +R$ 4,7): o stop curto troca perda grande por perda
  frequente e a conta fica negativa. A reacao ao dado ainda anda 10 a 20 pontos contra antes de voltar, como a hipotese contraria dizia.
- Pre-registro (texto original):
  16. [PRE-REGISTRO 11/10/2026, ANTES de rodar; mandato do Douglas: meta do mini-dolar de R$ 100 liquidos por dia, "pode ser seguro"]
     META COMO TRAVA DE ENTRADA COM A POSICAO DO DADO PROTEGIDA (em vez de zerar a mercado). Mecanismo: o ganho do setup do dado esta nos
     negocios que correm (saida por tempo: media de +R$ 184), e zerar em +R$ 100 troca isso por +R$ 95 em 85% dos negocios e deixa os 15% que nao
     chegam la perderem R$ 487 (medida de 11/10 em `quant/pesquisa/META_DIA.md`). Regra: as mesmas entradas do dado (congeladas: 2 min, gatilho 3
     pontos, stop 40, tempo 120, 2 contratos); ao PRIMEIRO toque de +R$ 100 liquidos no dia (aberto, como o robo mede), o robo NAO zera: leva o stop
     para o preco em que o dia ainda fecha em +R$ 90 liquidos depois do deslize de 1 tick (vale a partir da barra seguinte), nao abre entrada nova, e
     a posicao segue ate o tempo (120 min) ou ate a trava. Quem esta do outro lado: o mesmo do dado (quem exagerou a reacao ao numero). Parametros: 1
     (o nivel da trava, +R$ 90); a meta (+R$ 100) e do Douglas. Descoberta 10/2021-12/2024 (805 pregoes), depois validacao 2025, depois a prova so se
     passar; 2026 NAO se abre (ja foi prova do dado). Criterio para passar da descoberta: media por pregao acima da do teto simples (+R$ 4,7) E nao
     pior que o dado sem teto no pior dia, E pelo menos 30% dos pregoes com +R$ 100 tocados; para ser candidata a robo: media por pregao >= R$ 40 na
     descoberta e positiva na validacao, t >= 2. Precisaria de mudanca de regra de SAIDA no robo (nao feita).
  17. [PRE-REGISTRO 11/10/2026, ANTES de rodar] ALVO CURTO COM STOP CURTO no setup do dado (a ideia de "seguro" do Douglas): as mesmas entradas
     do dado, saida pela meta de +R$ 100 liquidos (zera a mercado) e stop de 10, 15 ou 20 pontos em vez de 40 (3 configuracoes; cada stop e uma
     tentativa). Mecanismo: se o preco quase nunca anda mais de 10 a 20 pontos contra a entrada antes de devolver 5,5 pontos, o stop curto troca a
     perda de R$ 487 por R$ 230 a R$ 450 e a expectativa sobe. Hipotese contraria (a que eu espero): a reacao ao dado e justamente o movimento
     que ainda pode se estender 15 a 20 pontos antes de voltar, e um stop curto troca o acerto de 85% por 60% sem pagar a diferenca. Mesma regra de
     descoberta/validacao/prova do item 16; passa da descoberta se a media por pregao superar a do teto simples com o stop de 40 (+R$ 4,7) e o
     pior dia ficar acima de -R$ 500.


## 12/10/2026: estudo completo da estrategia (pedido do Douglas; relatorio em quant/saida/relatorios/2026-10-12_estudo_completo_robo.html)

Metodo da sessao: tudo com os custos do laboratorio, descoberta 10/2021-12/2024 e validacao 2025 quando a regra ja tinha aberto
a validacao; 2026 NAO foi relido por nenhuma regra. Tentativas desta sessao: 2 (tipo de dia V1/V2) + 1 (overnight R1) + 2 eventos
(anuncios, pre-FOMC) + 3 (tendencia do indice) + 3 (tendencia do DI) = 11 simulacoes/eventos novos no registro.jsonl (familias
calendario_tipo_dia, anomalias_literatura, tendencia_indice, tendencia_juros). Monte Carlo e caminhos do livro nao sao tentativas.
Scripts em quant/estudos/2026-10-12_*.py; saidas em quant/saida/pesquisa5/montecarlo/.

### Testadas (12/10/2026)
- Reversao do dado, Monte Carlo (2021-2025, 400 negocios): +R$ 88,85 por negocio, t 3,2, Sharpe 1,57, DSR 0,48 com 1.000 tentativas e
  0,16 com 35 mil. Bootstrap por blocos (10 mil anos de 95 negocios): ano medio +R$ 8,4 mil, P(ano negativo) 4% a 6%, queda maxima
  mediana -R$ 2,9 mil (p05 -5,3 mil), P(queda > 10 mil) 0,03% a 0,2%; na serie real 0 semanas estouraram os R$ 2.000. Permutacao (400 regras
  aleatorias, mesma hora e numero de entradas): placebo -R$ 22,86 (o custo), a regra z 4,3, p < 0,0025. ATENCAO: inclui a descoberta;
  so 2025 e +R$ 26 por negocio.
- Reversao do dado por TIPO DE DIA (calendario do BLS + pedidos de auxilio; BEA/Census = lacuna): descoberta payroll +R$ 223 (n 34),
  ppi +189 (26), outro BLS +165 (41), cpi +75 (31), claims +68 (51), sem dado conhecido +57 (155). Validacao: sem dado -R$ 21 (31),
  payroll +153 (6), ppi +259 (5), cpi +40 (10). V1 (so dia com dado) 183 neg +R$ 137 (t 3,2, 7/7) mas R$ 31 por pregao contra 42 da base;
  2025: +R$ 74 (n 31, R$ 9,2/pregao contra 6,6 da base). V2 (payroll/cpi/ppi) 91 neg +R$ 163 (t 2,6, 5/7), 2025 +R$ 125 (n 21).
  VEREDITO: pelo pre-registro "nao agrega" (perde por pregao na descoberta); o rotulo `tipo_do_dia` entra em cada sinal ao vivo (so
  medido) e a prova viva por tipo decide. A regra que opera NAO mudou.
- Overnight x intradia (BOVA11, 2021-2024): overnight +5,0 pb por dia (t 2,0), intradia -3,4 pb; regra "compra 16h54, vende abertura"
  -2,8 pb liquido depois de 7,8 pb de custo: REPROVADA (validacao nao aberta).
- Dias de anuncio americano no BOVA11 (Savor-Wilson): -4,3 pb contra -2,8 pb nos demais (t -0,2): nada. Pre-FOMC (Lucca-Moench):
  +12,4 pb contra +2,2 pb, 13 de 24 positivos, t 0,55: inconclusivo (pista: amostra cresce 8 por ano).
- Tendencia de meses no INDICE (NEFIN Rm, vol alvo 10%, 2001-2010 e 2011-2015): 12-1 Sharpe 0,10 e 0,08; 6-1 0,08 e 0,01; 3-1 -0,02 e
  -0,13. REPROVADA (G3 para o indice).
- Tendencia em JUROS (DI de 2 anos, 2005-2015 e 2016-2020, o que a Kadima declara fazer): N=63 ?, N=126 Sharpe 0,33 e -0,58, N=252 0,35
  e -0,23. REPROVADA. DI como sinal do indice/dolar em 20 pregoes: sinal troca entre as janelas: nada estavel.
- Mecanismo da surpresa (payroll e CPI 2021-2025, 95 dias, efetivo contra o anterior pela API do BLS): a reacao de 2 minutos tem o sinal
  "certo" em 58% dos dias; nas reacoes > 3 pontos (81) a devolucao media em 2 horas e 8,3 pontos: 6,3 quando a reacao concorda com a
  surpresa e 11,3 quando contraria. PISTA (nao e regra): a reacao contra o sentido da surpresa devolve mais. Com consenso de verdade
  (ForexFactory arquivado toda semana desde 12/10/2026, ou calendario do MetaTrader), medir em prova viva.
- Caminhos do livro 60/30/10 (series mensais 2016-2021, 10 mil caminhos de 12 meses): queda do livro mediana 4%, p95 14%, p99 18%; acoes
  estouram a fatia de 17% em 3% dos caminhos; opcoes e dolar nunca estouram; P(12 meses abaixo do CDI) 22%.

### A testar (novas, 12/10/2026)
16. Limiar do dado relativo a volatilidade (reacao / amplitude tipica dos 20 pregoes) em vez de 3 pontos fixos (pista do digest; nao testado).
17. Execucao passiva calibrada com o negocio a negocio real (20 pregoes da B3 + livro do MetaTrader): o "0,26 ponto" da ordem parada e artefato do
    fill do laboratorio; sem calibracao, os efeitos reais menores que o custo (reversao de barra, valor justo, 16h00) nao podem ser julgados.
18. Reacao contra o sentido da surpresa (item acima) como filtro do setup do dado: so com consenso arquivado (prova viva).
19. Opcoes A0 (capital protegido) e A1 (straddle barato): refazer com t agrupado por mes, tabela de eventos corrigida (315 bonificacoes), IR e mais ativos.
20. Prova viva dos eventos raros congelados: anuncio extra do BC (n 15), fade do dado de quinta com ordem passiva (n 45), 1o pregao de jan/mai/set.
21. Camada de observacao (quant/observacao, desde 12/10/2026): 17 sinais macro/micro/grafico/fundamento, termometro G20, dose G23 e placar
    G19/G2, tudo so medido; com 60 leituras pontuadas por sinal (~3 meses) o placar diz quem tem informacao.

## 12/10/2026, rodada 2 (consenso do MetaTrader, regimes, meta-rotulo, analogos)

Testadas e fechadas (60 tentativas; detalhe em `quant/estudos/LEIA.md`):
- Reversao do dado condicionada a 26 estados macro/micro/intradiarios: nenhuma candidata (todas com t >= 3 tem n < 200).
- Rompimento da faixa de abertura no WIN por regime: reprovado.
- Reversao do dado contra a surpresa real: contra a surpresa rende 3x mais que a favor (n 56); sem candidata.
- Meta-rotulo com e sem surpresa: AUC ~0,5; reprovado.
- Dias analogos: sem informacao.

Pistas abertas (so medindo; entram na prova viva pelo rotulo, nunca pela regra):
22. Dia seguinte a uma perda do setup do dado (+R$ 176/neg na descoberta, 7/7): cobrar na prova viva com o rotulo do resultado de ontem.
23. Gap da noite > 10 pontos e vol realizada do dolar alta: rotulos `usdbrl_vol_regime` (observacao) e gap (falta ao vivo: a fita nao tem o fechamento de ontem).
24. Reacao contra a surpresa real (|S| >= 0,5): juntar a surpresa do MetaTrader ao placar por dia; se em 2026 (prova viva) repetir a razao 3:1, pre-registrar V2 "dose maior contra a surpresa" e so entao pedir o "pode".
25. Dias sem consenso no marco rendem menos (+55): separar no placar; nao filtrar (perde por pregao).
- Rodada 3 (12/10): saidas alternativas da reversao do dado (alvo, stop movel, tempo, stop): 10 tentativas, nenhuma melhor que a saida congelada; alvo curto sobe o acerto e derruba o resultado. Fechado.
26. Prova viva das variantes do dado (`dado_variantes.py`, desde 13/10/2026): cobrar no painel da prova viva; gate 60 negocios, t >= 2 e acima de `dado_base` nos mesmos pregoes.

(12/10/2026, rotina da noite) Itens 4, 5 e 11 da fila, so na descoberta (805 pregoes; scripts em
quant/saida/pesquisa5/noite/2026-10-12/). O item 6 ficou de fora: posicao por tipo de participante nao existe de graca, PTAX
ja foi testada e as corretoras ja fecharam sem pista viva. Nenhuma candidata nova.
- Item 4, manha de volatilidade alta (faixa de 9h00 a 9h14 no tercil alto dos 20 pregoes anteriores, corte conhecido as 9h15):
  MORTA. Reversao do dado (gatilho 3, stop 40, tempo 120): nos dias de faixa alta n 123, +R$ 56 por negocio (t 1,0, 5 de 7
  semestres); nos outros dias n 206, +R$ 130 (t 3,5). O filtro PIORA a regra aprovada, nao melhora. Barra grande (variacao
  >= 5 pontos e volume >= 3 vezes, entra contra, stop 10, alvo 4, 20 min): faixa alta n 287, -R$ 14,60 (t -1,9, 2 de 7
  semestres); outros dias -R$ 19,40 (t -3,6). Perde nos dois regimes.
- Item 5, fim da janela de ajuste (movimento de 15h50 a 15h59 no decil alto, corte movel de 60 pregoes; aposta contra na barra
  das 16h00): MORTA. Bruto real (+1,5 a +1,8 pontos, 82 sinais, t 2,5 a 5,7) mas so 0,1 sinal por pregao: a mercado sobra
  +R$ 8,40 por negocio (t 0,7, 4 de 7 semestres); com 10 minutos +R$ 7,50 (t 0,5). Entrada parada 0,5 ponto alem do
  fechamento das 15h59: nenhum negocio executado.
- Item 11, continuacao depois do dado das 10h de NY (reacao em 5 minutos, limiar 5 pontos, segue, stop 40, 120 min): MORTA.
  n 260, acerto 45%, +R$ 12,50 por negocio (t 0,5), 4 de 7 semestres; 2021 -R$ 81, 2023 -R$ 17, 2024 -R$ 9; compra perde
  (-R$ 17,70) e so a venda ganha (+R$ 40,90). A pista de t 2 da noite de 09/10 nao se sustentou com custo.

## 14/10/2026: revisao do pregao e ajuste da estrategia (pedido do Douglas: "ajuste a estrategia... se esforce")

A partir de hoje a rotina da noite roda a REVISAO DO PREGAO (quant/pesquisa/revisao.py) antes do protocolo e escreve o caderno de
erros (quant/saida/revisao/). Padrao de erro de contexto (c), de saida (d) ou alerta (a) que aparece num segundo pregao abre
item aqui sozinho, marcado "[revisao: <chave>]". Estudo: quant/estudos/2026-10-14_ajuste_estrategia.py (familia
dado_limiar_relativo, 3 tentativas); regua: quant/estudos/2026-10-14_distribuicoes.py -> quant/pesquisa/distribuicoes.json.
- Item 16, limiar do dado relativo a volatilidade (|reacao| > k x mediana da amplitude diaria dos 20 pregoes anteriores; k pelo
  casamento de contagem com os 3 pontos, sem olhar resultado): MORTA. k (n 337) +R$ 77,80/neg, R$ 32,60/pregao, t 2,6, 6 de 7;
  0,8k R$ 27,90/pregao; 1,25k R$ 34,80/pregao; a regra que opera (3 pontos fixos) da R$ 42,10/pregao, t 3,3, 7 de 7. Pior em
  todos; 2025 nao foi aberto.
- O pregao de 14/10 (venda do dado a 5.054, saida por tempo, -R$ 154,80) ficou no percentil 33 dos 400 negocios de 2021-2025
  (media +R$ 88,85; 54% dos perdedores chegaram a andar 8 pontos a favor antes). Contexto a favor em todos os rotulos (CPI,
  reacao > 10, venda, 9h30). Saida por tempo 60 teria perdido R$ 100 a menos HOJE; no historico rende R$ 42 contra R$ 100 da
  congelada. Nada muda na regra.
- CUSTO DAS REGRAS REPROVADAS COM AS TRAVAS DO DIA (2021-2025, 1.055 pregoes, parametros vivos, 9h15-18h10): nivel e reacao
  -R$ 128,60 por pregao (5,3 negocios, -R$ 24/neg, para nas 3 perdas em 96% dos dias, mediana as 11h05; 25% dos pregoes
  positivos); climax -R$ 43,90 por pregao; reversao do dado +R$ 33,70. Com o nivel operando, a trava de 3 perdas do dia
  bloqueia o fim do pregao do mini-indice (17h53) em 96% dos pregoes.
- CONFLITO NO INVERNO AMERICANO (02/11/2026 a 08/03/2027: dado as 10h30, entrada 10h32): em 2021-2025, 45 de 125 sinais do
  dado (36%) seriam bloqueados pelas outras regras (37 pela trava de 3 perdas/R$ 1.000, 8 por posicao aberta do nivel);
  esses 45 somam +R$ 10.184 (media +R$ 226). Nivel e climax estao em "travado_pelo_douglas": a decisao e dele.
27. (decisao do Douglas, nao hipotese) Nivel e reacao e climax: desligar, ou manter so medindo de manha nos dias de dado as 10h30.
   Numeros acima. Sem a decisao, nada muda (protocolo nao toca chave travada).
   DECIDIDO (16/10/2026, 08h55, "pode fazer"): nivel e reacao e climax DESLIGADOS em modo_robo.json (seguem so medidos e na
   lista travado_pelo_douglas, para a rotina nao religar). Valem a partir do proximo inicio do robo (19/10, 08h35): o processo
   de 16/10 tinha subido as 08h47 com os dois ligados e o robo le as chaves so ao subir.

(16/10/2026, noite) Pesquisa da noite: nenhuma hipotese testada, por falta de dado. Item 6: a posicao por tipo de participante
NAO existe de graca (b3_dolar/2_posicoes_participante/LEIA_ISTO.txt), PTAX e corretoras na fita ja foram testadas em 09/10.
Item 7: depende de leitura ao vivo que ainda nao existe. Item 8: ainda so 15 casos. Itens 9 e 10: seguem na prova viva (4
negocios do mini-indice desde 13/10, cedo demais). Item 14: o pacote yfinance nao esta no .venv e a rotina nao instala
dependencia. Nenhuma tentativa nova entrou no registro.

## 17/10/2026: revisao da semana (08 a 16/10) pedida pelo Douglas

- Climax com liga/desliga por regime (opera so quando a media dos proprios negocios nos ultimos 60 pregoes encerrados e
  positiva; quant/estudos/2026-10-17_climax_regime.py, familia climax_regime, 3 tentativas): MORTA na descoberta. Sem filtro
  1.862 negocios, -R$ 17,86/neg, 0 de 7 semestres positivos; com o filtro de 60 pregoes 141 negocios, -R$ 17,50/neg (t -1,4);
  40 pregoes -R$ 17,36; 120 pregoes nunca liga. 2025 nao foi aberto. Ao vivo (09 a 16/10) os 14 sinais medidos acertaram 13
  (+R$ 48,50 por sinal): coerente com 2026 ser diferente de 2021-2025, nao com um filtro que se ache no passado. Segue so
  medindo; com 60 sinais ao vivo, media positiva e t >= 2 vira pedido de estudo (protocolo da noite) e a decisao e do Douglas.
- Semana ao vivo (sinais medidos, 2 contratos): nivel e reacao 140 sinais, -R$ 43,30 por sinal, acerto 31% (pior que os 5 anos);
  reversao do dado 1 sinal (14/10, -R$ 154,80, percentil 33); fim do pregao do mini-indice (prova viva, variante adaptativa)
  4 negocios, +R$ 299 com 2 contratos, mas o robo nunca a rodou ao vivo (so percorria o WDOFUT; conserto da varredura de 15/10).
