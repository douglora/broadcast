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

## Testadas

(08/10/2026) Sete frentes, mais de 12 mil medicoes: ver quant/estudos/LEIA.md. Passou so a reversao do dado americano.
