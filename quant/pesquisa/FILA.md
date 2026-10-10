# Fila de hipoteses do robo de day trade (mini-dolar)

A rotina da noite pega daqui ate 3 hipoteses por noite, de cima para baixo, testa SO na descoberta (quant/pesquisa/lab.py,
metodo em quant/saida/pesquisa5/BRIEF.md) e move a linha para "Testadas" com os numeros. Hipotese nova entra no fim de
"A testar". Nada sai daqui apagado: o "nao" tambem e resultado.

## A testar

4. Manha de volatilidade alta (pista da frente maquina: o pouco que ha de previsivel vive ali): repetir a regra do setup
   proprio e as reversoes de barra grande so nos dias em que a faixa dos primeiros 15 minutos esta no tercil alto dos 20
   pregoes anteriores.
5. Fim da janela de ajuste (15h50 a 16h00): o preco devolve 0,5 ponto na barra das 16h00 (t -7,3, real mas menor que o
   custo). Ha versao com movimento grande (decil alto: 1,8 ponto) que pague com entrada parada?
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

11. Continuacao (nao reversao) depois do dado das 10h de NY (pista da noite de 09/10, nao prevista): medindo a reacao em 5
   minutos (nao em 2), o preco CONTINUA na direcao da reacao por 60 a 120 minutos (bruto +2,0 a +2,7 pontos, t 1,9 a 2,1, n
   287, 3 de 4 anos). Mecanismo: dado de 10h (ISM, confianca, vendas) traz informacao que o mercado leva minutos para
   digerir, ao contrario do dado das 8h30, que e exagerado. Testar com lab.avaliar, parametros redondos (r=5, thr=5, stop 40,
   tempo 120), t por pregao; se nao for candidata na descoberta, nao vai a validacao.

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
