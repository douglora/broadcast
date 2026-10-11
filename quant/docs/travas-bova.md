# Travas com BOVA11: manual do robô (simulação)

Escrito em 11/10/2026. Tudo aqui é SIMULAÇÃO e descrição de mecânica: nenhuma ordem real, nada de "compre" ou "venda" (Resolução CVM 178). O que a B3 publica está citado com a fonte; o que não deu para confirmar está na seção "Lacunas".

## Em uma frase

Trava é vender uma opção e comprar outra, mais longe, do mesmo tipo e vencimento: o crédito recebido é o ganho máximo, a distância entre os preços de exercício menos o crédito é a perda máxima, e o risco fica definido de antemão. No histórico de 2020-2023 as 72 travas de crédito testadas com BOVA11 **não pagaram o risco** (a vertente é medida em simulação, não aprovada).

## 1. Mecânica

Preços em R$ por opção. Um lote do livro simulado é 100 opções.

| Trava | Monta | Ganha o crédito se | Perde no máximo | Equilíbrio |
|---|---|---|---|---|
| Alta com put (crédito) | vende put em K1, compra put em K2 < K1 | BOVA11 fica acima de K1 no vencimento | (K1 - K2) - crédito | K1 - crédito |
| Baixa com call (crédito) | vende call em K1, compra call em K2 > K1 | BOVA11 fica abaixo de K1 | (K2 - K1) - crédito | K1 + crédito |
| Alta com call (débito) | compra call em K1, vende call em K2 > K1 | BOVA11 sobe até K2 | o débito pago | K1 + débito |
| Baixa com put (débito) | compra put em K1, vende put em K2 < K1 | BOVA11 cai até K2 | o débito pago | K1 - débito |

Crédito executável = oferta de compra da perna vendida menos oferta de venda da perna comprada, menos o emolumento (a simulação usa 0,05% do prêmio por lado e 0,03% do valor do papel no exercício; corretagem e imposto não entram). O retorno sobre o risco é crédito dividido pela perda máxima: 25% quer dizer ganhar R$ 25 se tudo der certo contra R$ 100 de risco.

Exemplo com a cadeia de 07/10/2026 (BOVA11 a R$ 201,25, vencimento 19/11/2026, 29 pregões): vender a put de exercício 190 (oferta de compra R$ 1,99) e comprar a de 181 (oferta de venda R$ 1,00) rende crédito de uns R$ 0,99 por opção contra largura de R$ 9,00: perda máxima R$ 8,01, retorno sobre o risco de uns 12%. O ganho máximo (R$ 99 por lote) só acontece se BOVA11 ficar acima de R$ 190 em 19/11; abaixo de R$ 181 perde-se R$ 801 por lote. A tabela do dia na tela traz, para cada trava, **a probabilidade que o preço embute** (N(d2) de Black-Scholes com a volatilidade implícita de cada perna; só serve para probabilidade, nunca para preço) e **a empírica** (frequência, em 15 anos de Ibovespa de retorno total, de o índice terminar acima do exercício no mesmo número de pregões).

## 2. Estilo de exercício e exercício automático

Fonte: página da B3 "Options on ETF" (https://www.b3.com.br/en_us/products-and-services/trading/equities/options-on-etf.htm) e o arquivo de cadastro de instrumentos da B3 de 01/10/2026 (`InstrumentsConsolidated`, campo `OptnStyle`).

- A B3 informa que o estilo das opções sobre ETF varia por série ("europeu ou americano"), com preço mínimo de R$ 0,01, vencimento na terceira sexta-feira e exercício automático das opções dentro do dinheiro no vencimento (o investidor pode pedir bloqueio).
- No cadastro de 01/10/2026, as **puts de BOVA11 são todas europeias** (1.485 séries). As **calls misturam os dois estilos** (686 europeias e 799 americanas, contando as semanais). A coluna de estilo do COTAHIST (arquivo de cotações) vem como "falso" para todas as séries de BOVA11, então não serve para saber o estilo: use o cadastro de instrumentos ou a plataforma.
- Consequência: vender **call americana** abre o risco de exercício antes do vencimento; uma trava com call vendida deve usar série europeia (conferir o estilo da série na plataforma antes de qualquer decisão). Put vendida de BOVA11 não tem esse risco.

## 3. Garantia (margem)

A regra oficial de margem da B3 para travas **não foi confirmada** (só fontes secundárias, que dizem que a câmara reconhece a trava e exige perto de largura x quantidade; a chamada de margem é calculada diariamente pela B3 para cada conta). Na simulação, a garantia de uma trava de crédito é a perda máxima (largura menos crédito) e entra no teto de risco da vertente. A garantia de uma put vendida coberta por caixa é o exercício inteiro (R$ 195 x 100 = R$ 19.500 por lote).

## 4. Distribuição de rendimentos e data-ex

BOVA11 distribui rendimentos. Nos dados do COTAHIST de 2005-2026 o exercício das séries de BOVA11 **não mudou** entre a entrada e o vencimento em nenhum dos 165 ciclos mensais estudados (8.849 séries), isto é, os dados não mostram ajuste de exercício por distribuição. A regra da B3 sobre isso para ETF **não foi confirmada**; vale a leitura dos dados, com a ressalva. Efeito prático: perto da data-ex, a cota cai o valor do rendimento sem o exercício acompanhar, o que favorece quem comprou put e quem vendeu call (e vice-versa).

## 5. Liquidez por exercício e por vencimento

O filtro do robô: 30 negócios ou mais da série no dia, oferta de compra e de venda válidas e spread até 30% do ponto médio, nas duas pernas. Em 07/10/2026 passavam: vencimento de 16/10, 15 calls e 11 puts; 19/11, 14 calls e 13 puts; 18/12, 6 calls e 5 puts. Os exercícios líquidos não são todos os da grade (vão de R$ 1 em R$ 1 em alguns trechos e ficam ralos longe do dinheiro), então a largura da trava é limitada pelo que existe: uma trava de 3% a 6% de largura (R$ 6 a R$ 12 com BOVA11 perto de R$ 200) só aparece quando há duas séries líquidas à distância certa.

Custo real: o spread entre compra e venda das duas pernas pesa muito perto do crédito. Medido em 134 travas de BOVA11 de 2020-2023 (delta 0,20, largura 3%), no primeiro pregão em que as duas pernas tinham cotação depois da entrada, **fechar a trava custava em mediana 1,45 vez o crédito recebido** (e em 24% dos casos já 2 vezes ou mais), só por cruzar as ofertas. É por isso que o stop em 2 vezes o crédito disparou em mais da metade das operações da pesquisa.

## 6. Regras do robô nesta vertente (livro simulado)

- **Direção**: alta se o fechamento está acima da média de 200 pregões e a média de 50 sobe frente a 5 pregões atrás; baixa se o contrário; senão neutra. Alta -> trava de alta com put; baixa -> trava de baixa com call; neutra -> as duas servem. A tela mostra os números da leitura.
- **Escolha**: delta da perna vendida entre 0,15 e 0,25; largura entre 3% e 6% do preço; 1 lote de 100; melhor retorno sobre o risco entre as que passam na liquidez e cabem no teto (R$ 900 de perda máxima por trava e R$ 900 somados).
- **Saída**: recompra a trava quando ela vale 20% do crédito (80% capturado) ou no vencimento; stop quando custa 2 vezes o crédito. Só se decide em pregão em que as duas pernas têm cotação do dia e a vendida tem 10 negócios ou mais (como foi testado).
- **Travas a débito** só com gatilho de direção (rompimento da máxima de 55 pregões ou volta acima/abaixo da média de 200); nunca por padrão.
- **Evidência**: reprovada no histórico, só medida (ver `RESULTADO_VERTENTES.md`). Nenhuma configuração da grade de 76 passou o critério da validação.

## 7. O que fazer perto do vencimento (lista para o Douglas, não ordem)

1. A partir de uns 5 pregões do vencimento, o prêmio restante é pequeno e o risco de "pino" (BOVA11 fechando bem em cima do exercício vendido) é todo da perna vendida. Capturar os 80% antes é o objetivo da regra.
2. Se BOVA11 está dentro do dinheiro na perna vendida e o prêmio não caiu, a decisão é fechar a trava por inteiro (comprar a vendida, vender a comprada) em vez de deixar o exercício automático acontecer: a simulação cobra a taxa de exercício (0,03% do valor) em cada perna dentro do dinheiro; como a corretora liquida as duas pernas de uma trava exercida não foi confirmado.
3. Não deixar a perna comprada vencer sozinha se a vendida foi fechada: sobra uma opção comprada que só vale se estiver dentro do dinheiro.
4. Call americana vendida: não carregar atravessando a data-ex sem checar o estilo da série.
5. A pesquisa assume saída no fechamento do pregão em que o gatilho aparece, com as ofertas daquele fechamento; perto do vencimento as ofertas ficam ralas e o preço real pode ser pior.

## 8. Lacunas (o que NÃO foi confirmado)

- Regra oficial de margem da B3 para travas (usada: garantia = perda máxima).
- Quantidade de cotas por opção e lote padrão de negociação das opções de BOVA11 (usada: 100 por lote, como no restante do livro; o cadastro traz lote de alocação 1 e os campos de multiplicador vazios).
- Ajuste do exercício por distribuição de rendimento de ETF (os dados mostram nenhum ajuste; regra da B3 não lida).
- Corretagem, taxas da corretora e imposto de renda sobre opções: fora da simulação.
- Rolagem e "roda" (aceitar o exercício e lançar call coberta) não foram testadas no histórico.
- Preço de execução do stop em dia de pânico (março de 2020 teve interrupções de negociação): a pesquisa executa no fechamento do dia em que o gatilho dispara; com um pregão de atraso a perda dobra (ver `RESULTADO_VERTENTES.md`).
