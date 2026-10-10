# Metodo de pesquisa do robo (em vigor desde 10/10/2026)

O Douglas trouxe este metodo em 10/10/2026 (escrito numa conversa dele com outro assistente) e pediu: "processe e introduza
o prompt, faca os backtesting e me diga se vamos conseguir ter essa estrategia vencedora, seja honesto". Ele passa a valer
para toda pesquisa nova, a da rotina da noite inclusive. Dois referenciais:

- Ernest Chan (Quantitative Trading; Algorithmic Trading): a IDEIA. Reversao a media e momentum intradiarios com mecanismo
  economico, custo real e execucao realista.
- Marcos Lopez de Prado (Advances in Financial Machine Learning): o RIGOR. Como nao se enganar com sobreajuste e falsa
  descoberta.

Objetivo: estrategia robusta fora da amostra, com risco controlado. NAO se otimiza para retorno diario fixo. Otimiza-se
para Sharpe liquido de custos, queda maxima aceitavel e estabilidade entre regimes.

## As regras de trabalho e onde cada uma mora no codigo

1. HIPOTESE ANTES DE CODIGO. Toda estrategia comeca com 2 a 3 linhas: por que a vantagem existiria na B3 e quem esta do
   outro lado. Sem hipotese, descarta. (Ja era a regra do `quant/saida/pesquisa5/BRIEF.md`.)
2. REGISTRO DE TENTATIVAS. Toda configuracao avaliada entra em `quant/saida/pesquisa5/registro.jsonl` (`lab.avaliar` grava
   sozinho). O numero acumulado de tentativas entra no Sharpe deflacionado (`ldp.dsr`): resultado bom depois de 200
   tentativas vale menos que depois de 5. Ate 09/10/2026 o projeto ja tinha olhado mais de 35 mil medicoes e cerca de 2.500
   simulacoes completas: todo Sharpe novo e deflacionado contra isso.
3. DADOS E ROTULOS.
   - Barras de volume alem das de tempo (`ldp.barras_de_volume`), e comparar.
   - Rotulo de tripla barreira: alvo, stop e tempo maximo. E exatamente o que `lab.negocios` simula (stop, alvo, tempo).
   - Meta-rotulagem: um modelo primario simples (a regra) da o lado; um modelo secundario decide SE entra e o tamanho.
   - Diferenciacao fracionaria so quando a caracteristica nao for estacionaria; no day trade quase tudo ja e retorno ou
     desvio (estacionario).
4. VALIDACAO.
   - Nunca k-fold comum. Validacao combinatoria com purga e embargo por pregao (`ldp.cpcv`).
   - Um periodo final intocado, usado UMA vez. Situacao honesta do projeto: 2026 (parte `prova` do laboratorio) ja foi
     aberto uma vez para cada uma destas regras: reversao do dado (gatilhos 4 e 3), fuga do VWAP as 10h, penultimo dia util.
     Para qualquer estrategia NOVA, 2026 continua intocado e so pode ser aberto uma vez, no fim. O intocado de verdade, daqui
     para a frente, e o dado novo (`quant/pesquisa/prova_viva.py`).
   - Treino e validacao cruzada: descoberta + validacao (10/2021 a 12/2025). Prova final: 2026.
   - Passo a passo no tempo (walk-forward) com retreino periodico.
   - Por regime: volatilidade alta e baixa, tendencia e lateral, eventos (Copom, payroll, eleicao).
5. REALISMO. Taxas da B3, 1 tick contra por lado nas ordens a mercado (ja nas contas de `lab.ESPEC`), ordem parada so
   executa se o preco passa 1 tick, leiloes, rolagem, horario. Sem olhar o futuro: `lab.sem_futuro` em toda regra.
6. NAO SE PERDER NO TESTE. No maximo 3 a 5 parametros por estrategia. Sensibilidade: cada parametro +-20% e a estrategia
   tem de continuar lucrativa (plato, nao pico). Teste de permutacao. Se depois de N rodadas nada passa, PARA, relata e
   propoe hipotese nova em vez de forcar ajuste.
7. CRITERIOS DE APROVACAO (todos fora da amostra, liquidos de custo):
   - Sharpe deflacionado maior que 0,95 (probabilidade de o Sharpe ser verdadeiro, ja descontadas as tentativas) e Sharpe
     anual maior que 1.
   - Queda maxima dentro do limite: proposta de 10% do capital (R$ 10 mil em R$ 100 mil) na escala em que a estrategia vai
     operar.
   - Pelo menos 100 negocios fora da amostra.
   - Funciona em 2 dos 3 mercados (indice, dolar, acoes), ou ha explicacao clara de por que so em um.
8. RISCO. Tamanho da posicao pela volatilidade (alvo de risco por negocio), perda maxima do dia e da semana que desligam o
   robo, e no maximo meio Kelly. No robo desde 10/10/2026 (capital de R$ 100 mil):
   - perda maxima do DIA: R$ 1.000 (1%) ou 3 negocios perdedores; para ate o pregao seguinte;
   - perda maxima da SEMANA: R$ 2.000 (2%); para ate segunda-feira;
   - QUEDA maxima desde o pico do acumulado: R$ 10.000 (10%); para ate o Douglas mandar religar;
   - LOTE: o stop cheio de um negocio nunca passa da perda maxima do dia (com stop de 40 pontos no mini-dolar cabem 2
     contratos, R$ 815). O meio Kelly calculado com a media medida daria muito mais que isso; como a media medida pode ser
     zero (o Sharpe fora da amostra e 0,72), quem manda no tamanho e o limite de perda, nao o Kelly.
   Os dois limites longos ficam em `quant/saida/risco_robo.json` (arquivo do Douglas) e a tela mostra semana e queda.

## Entregavel de cada rodada

Hipotese, parametros, metricas dentro e fora da amostra, numero acumulado de tentativas e Sharpe deflacionado; curva de
capital, queda e distribuicao do resultado por negocio; e o parecer critico: o que pode estar errado no resultado.

## O que este metodo NAO faz

Ele nao cria vantagem. As ferramentas de Lopez de Prado servem para descartar o que e acaso; as ideias de Chan ja foram, em
boa parte, testadas nas quatro rodadas de 08 e 09/10/2026 (gap de abertura, faixa de abertura, momentum da primeira meia
hora, reversao do residuo entre acoes, pares, valor justo entre mercados, reversao de barra grande): `quant/pesquisa/FILA.md`,
secao "Testadas". O que o metodo acrescenta de novo e (a) a meta-rotulagem sobre as duas unicas regras com mecanismo e
evidencia (reversao do dado americano; empurrao do fim do pregao), (b) as barras de volume e (c) a conta formal do Sharpe
deflacionado.
