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

