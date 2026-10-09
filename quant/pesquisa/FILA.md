# Fila de hipoteses do robo de day trade (mini-dolar)

A rotina da noite pega daqui ate 3 hipoteses por noite, de cima para baixo, testa SO na descoberta (quant/pesquisa/lab.py,
metodo em quant/saida/pesquisa5/BRIEF.md) e move a linha para "Testadas" com os numeros. Hipotese nova entra no fim de
"A testar". Nada sai daqui apagado: o "nao" tambem e resultado.

## A testar

1. Reversao de HORAS depois de evento com hora marcada, alem do dado das 8h30 de NY: decisao do Fed (15h ou 16h de Brasilia
   conforme o horario de verao dos EUA), dado das 10h de NY, abertura da bolsa de NY (9h30 de la). Mesma forma do setup
   proprio: reacao dos 2 a 5 primeiros minutos, entrar contra, segurar 60 a 120 minutos. (Frente calendario: "a reversao
   util e de horas, nao de minutos".)
2. Tarde de dia coerente: juros (DI27/DI29), mini-indice e dolar na mesma direcao de risco desde a abertura; o dolar
   continua das 12h30 as 17h00? (Frente intermercado: +5,5 pontos nos dias de aversao, t 2,3, n 111: fraco, reavaliar com
   regime definido antes.) Exige outros ativos: se passar, fica como candidata sem ir ao vivo ate haver barras ao vivo deles.
3. Primeira meia hora grande continua de 13h00 a 17h20 (+4,2 pontos, t 3,0 na frente regime; nao se sustentou com limiar
   fixo): testar com limiar em desvios da volatilidade dos 20 pregoes anteriores.
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
