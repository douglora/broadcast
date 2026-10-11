# Gestores de referencia: o que ensinam e o que vale na bolsa brasileira

Estudo de 10/10/2026 para o Douglas. Simons (Renaissance), Octavio Magalhaes (Guepardo), Christian Keleti (Alpha Key) e Warren Buffett (Berkshire). Pesquisa em fonte publica, traducao para a B3 e regras testaveis (G1 a G18) para os quatro modulos do robo (carteira de acoes, mini-dolar, mini-indice, opcoes). Tudo e SIMULACAO. Nada aqui e recomendacao de compra ou venda (Resolucao CVM 178) nem promessa de resultado.

Nomes, conferidos nas fontes: o gestor da Guepardo e Octavio Ferreira de Magalhaes (site da gestora; a imprensa ora escreve Octavio, ora com acento agudo no a). Nao e Guimaraes. O da Alpha Key e Christian Caradonna Keleti (Formulario de Referencia da gestora), com Ch, nao Cr. Detalhe que muda a leitura: no Formulario de Referencia de 31/12/2020, a decisao final de investimento da Alpha Key e do Diretor de Gestao, Bruno Rignel; Keleti e CEO e co-gestor, e o comite de investimento (que se reune todo dia) e quem leva as ideias. O estilo Alpha Key e produto de comite, nao so de uma pessoa.

Adendo de 11/10/2026: as secoes 5A, 5B e 5C acrescentam Marco Freire e Ruy Alves (Kinea) como referencias de pensamento macro e as regras G19 a G27 (livro de swing de ate 10 pregoes, alocacao entre classes, opcoes e mini-dolar). A lente para a visao semanal da mesa esta em `quant/saida/mesa/lente_kinea.md` e `lente_kinea.json`.

Rotulos usados: [CONF] confirmado em fonte que abri; [SEC] so em fonte secundaria (resumo de terceiros, blog, agregador); [NC] nao confirmei; [MINHA] inferencia ou desenho meu, nao e o que o gestor disse. Os numeros entre colchetes tipo [S12] remetem a lista de fontes no fim.

---

## 0. Em uma pagina

**Ideia central de cada um, em uma frase:**
- **Simons:** achar muitos sinais minusculos, medi-los com custo real e deixar um modelo unico decidir, sem opiniao humana por cima. Funciona porque ele tinha escala de dados, execucao e alavancagem barata, nada disso cabe em R$ 100 mil.
- **Octavio (Guepardo):** so comprar empresa boa (filtro qualitativo primeiro, sem olhar numero), so quando o preco entrega retorno real muito acima da NTN-B, e vender quando o preco chega no valor justo; 14 papeis no maximo; zero macro.
- **Keleti (Alpha Key):** ser seletivo e defensivo (caixa de 20% a 25% em marco/2026, short contra balanco fragil), usar o macro para escolher o TIPO de empresa (receita em dolar, pouca divida) e para saber se o fluxo e o juro estao a favor.
- **Buffett:** pagar preco razoavel por negocio excelente dentro do que se entende, calcular pelo lucro que sobra para o dono, exigir margem de seguranca, e nunca perder o sono nem o caixa; opcoes so quando a contraparte paga adiantado e o prazo e de 15 a 20 anos.

**As 3 traducoes mais importantes para a bolsa brasileira:**
1. **O concorrente de toda acao e o CDI e a NTN-B.** Selic em 13,75% (Copom de 16/09/2026) e Octavio chama a NTN-B de IPCA+8%. Qualidade a preco justo aqui se mede como PREMIO SOBRE A NTN-B; e caixa nao e custo de oportunidade, e posicao que paga uns 8% a 9% reais. Isso apoia o caixa residual de Buffett e Keleti e contradiz a postura de Octavio de nunca migrar para a renda fixa, que vale para o fundo dele (long only), nao para um livro multimercado.
2. **Mercado pequeno e concentrado:** 76 acoes no Ibovespa, as 10 maiores pesam 54%, Vale + Petrobras mais de 24%, bancos 18,7% [S43]; Keleti conta uns 200 papeis investiveis [S28]. Concentracao a la Octavio vale; diversificacao a la gestor americano nao existe; e opcao liquida so em poucos nomes (a pesquisa do projeto usou 25 ativos).
3. **Atrito:** IR de 15% a cada venda com ganho (sem isencao em opcoes; day trade 20%), 10% de retencao em dividendos acima de R$ 50 mil por mes por pagadora desde 2026, e aluguel de acao caro justamente nos papeis de balanco fragil. A rotacao de Octavio (chegou no preco justo, vende) e o short de fragilidade de Keleti custam mais aqui; viram regra com barreira de troca (G6) e teste de short ANTES do custo (G10).

**Regras testaveis (so os titulos):** G1 razao edge/custo / G2 aposentadoria de sinal por decaimento / G3 largura lenta (tendencia em dolar, juros e indice) / G4 TIR real mecanica (a regua) / G5 entrada por premio sobre a NTN-B / G6 saida no preco justo e barreira de troca / G7 concentracao e tamanho / G8 juro cai, small e iliquidas andam / G9 fluxo estrangeiro nas grandes / G10 short de fragilidade, testado antes do aluguel / G11 tamanho por fragilidade e por unanimidade / G12 filtro de qualidade do dono / G13 circulo de competencia (universo congelado) / G14 put vendida como forma de entrar / G15 caixa como residuo / G16 benchmark nulo por modulo e prova viva / G17 tamanho por risco / G18 quando diminuir e aumentar a mao.

**Adendo Kinea (11/10/2026), regras novas:** G19 cartao de cenario com placar de calibracao / G20 termometro global-Brasil / G21 assimetria minima no swing / G22 opcao comprada em evento binario / G23 escada de dose de risco / G24 hedge por correlacao em estresse / G25 corte e reentrada do swing / G26 premio de risco da bolsa / G27 mini-dolar de 10 pregoes no sentido do carrego. Atencao: o terminal mostra a NTN-B 2035 a 6,81% em 09/10/2026 (era 8,31% em 23/07); o "IPCA+8%" desta pagina esta defasado (ver 5A.4).

**A esfera de cada um (o ponto que o Douglas pediu para distinguir):**

| Gestor | Onde vive | O que o ambiente dava de graca | O que falta aqui |
|---|---|---|---|
| Simons | Futuros e acoes dos EUA e de fora; fundo fechado, uns US$ 10 bi | Mercado profundo, custo baixo, alavancagem barata, equipe de cientistas | CDI de 13,65%, 200 ms de atraso, R$ 100 mil, aluguel caro |
| Buffett | EUA; capital permanente de seguradora (float); juro bem menor que o nosso | Dinheiro sem prazo de resgate, contraparte que paga o premio adiantado por 15 a 20 anos, imposto diferido | Sem float, sem prazo longo; o CDI e o concorrente |
| Octavio | Brasil, so comprado, sem macro, R$ 3 a 6 bi | Acesso a gestao das empresas, escala para ler empresa por empresa | Equipe qualitativa; o robo nao le governanca. Vantagem: R$ 100 mil entra onde ele nao consegue |
| Keleti | Brasil, comprado com protecao, ~R$ 1 bi, macro como filtro | Caixa, short e hedge dentro do mesmo fundo; comite diario | Aluguel caro nos papeis frageis; leitura de fluxo e juro e humana |

**Honestidade de partida:** o teste longo da carteira (2016 a 2026) nao achou alfa na selecao por fatores; o retorno veio de estar comprado em bolsa. As pesquisas de day trade nao acharam vantagem acima do custo (so a reversao do dado americano no mini-dolar, fraca). Nenhum dos quatro gestores muda isso por decreto. O que eles dao e DISCIPLINA (preco contra NTN-B, tamanho, caixa, aposentadoria de sinal, custo real), nao um atalho para alfa. E por causa do lacre do teste, TODA regra nova de carteira so se prova em dado novo (prova viva), o que leva anos (secao 1).

---

## 1. Como provar qualquer coisa aqui (vale para todas as G)

Lido de `quant/estudos/LEIA.md`, `quant/README.md`, `quant/pesquisa/METODO.md` e `quant/saida/pesquisa_carteira/RESULTADO_HOLDOUT.md`.

1. **Janela lacrada da carteira de acoes.** 2016-01 a 2026-06 foi aberta UMA vez em 10/10/2026 e nao reabre; ideia nova (tirar portoes, exposicao por volatilidade, piso de protecao) "so com dado novo ou paper trading". O desenvolvimento e 2012-03 a 2015-12 (mercado em queda, excesso do S0 de -8%/ano) e os fundamentos PIT (por data de entrega na CVM) comecam em 2011. Consequencia: **a janela de desenvolvimento serve para montar o cano e conferir sinal, nao para decidir.**
2. **Regra de historico longo nao tem como ser provada no desenvolvimento.** Filtro de "10 anos de ROIC" (Buffett) ou retorno de 3 a 5 anos (Octavio) precisa de fundamento de 10 anos e de retorno a frente de 3 a 5 anos. O primeiro dia com 5 anos de balanco publico e 2016 (lacrado). So a prova viva tira isso do papel. Proposta minha [MINHA]: prova viva de no minimo 36 meses e 30 posicoes encerradas, criterios de morte escritos antes.
3. **Regras de preco puro** (NEFIN desde 2001, DI x pre desde 2002 pelo arquivo TS da B3, PTAX, cotacoes desde 2005) podem usar 2002-2015 sem tocar no lacre da carteira. Aviso honesto: quem desenha a regra (eu, o Douglas) ja conhece a historia de 2008 e de 2013; isso contamina de leve qualquer teste nessa janela. So a prova viva limpa de verdade.
4. **Opcoes** seguem o corredor do proprio modulo: descoberta ate 2019, validacao 2020-2023, prova 2024-2026 uma vez. **Day trade:** descoberta 10/2021-12/2024, validacao 2025, prova 2026 (ja aberta para quem passou).
5. **Todo teste entra no `livro_tentativas.jsonl` ANTES de rodar** (muda o N do Sharpe deflacionado). Criterio de aprovacao do METODO.md: Sharpe deflacionado maior que 0,95, Sharpe anual maior que 1, no minimo 100 operacoes fora da amostra, custo real.
6. **Dado que falta no projeto** para estas regras: serie historica de NTN-B (taxa) e de IPCA esperado (Focus). Fonte provavel: Tesouro Transparente (CSV de preco e taxa do Tesouro Direto; um guia de terceiros diz que a serie diaria comeca em 2005, [NC] se a oficial comeca antes) ou IMA-B da Anbima. Alternativa de partida: curva DI x pre (ja ha rota, memoria `b3-curva-di-historica`) menos IPCA esperado do BCB (Expectativas, API Olinda). Nao testei nenhuma dessas rotas. Atualizacao de 11/10/2026: o terminal ja tem a taxa diaria dos Tesouro IPCA+ desde 27/09/2021 (`hist/TD-IPCA-*.json`, Tesouro Transparente) e a curva indicativa da Anbima (`rf.json`, real); no projeto `quant` a serie continua faltando.

---

## 2. Jim Simons (Renaissance Technologies)

**Esfera onde vive:** futuros e acoes dos EUA e de outros paises, fundo fechado a terceiros, perto de US$ 10 bilhoes, alavancagem barata e abundante (Zuckerman, segundo [S3]).

### 2.1 O que fazia de fato

| Ponto | O que as fontes dizem | Rotulo |
|---|---|---|
| Quem contratava | Matematicos e cientistas, nao veteranos de Wall Street; cultura aberta (todos sabiam o que os outros faziam); uns 300 funcionarios | [CONF] [S1] |
| Modelo unico | Todos os sinais e restricoes de carteira num modelo so; por isso testar um sinal novo e saber se o ganho paga o custo era rapido (resumo do livro de Zuckerman) | [SEC] [S5] |
| Muitos sinais pequenos | Acha padroes individuais e explora cada um so o bastante; a soma gera o retorno. Em 1997 mais da metade dos sinais achados era nao intuitiva; importava funcionar, nao o porque | [SEC] [S5] [S7] |
| Taxa de acerto | Em torno de 51% das operacoes (resumo do livro); 50,75% aparece citado do artigo de Cornell | [SEC] [S5] [S3] |
| Humildade com o modelo | A casa nunca achou que o modelo fosse a realidade, so um pedaco dela (essa e a frase curta que uso: "just some aspects of reality") | [SEC] [S5] |
| Horizonte | Curto: posicoes de um a dois dias, as vezes semanas, frequencia media; nao e alta frequencia pura. Sem numero de fonte primaria | [SEC] [NC] |
| Alavancagem | Media perto de 12,5 vezes, picos de 20 vezes; dimensionamento por criterio de Kelly. So fonte secundaria. Zuckerman, citado por [S3], descreve a alavancagem como ampla, barata e pouco notada | [SEC] [S6] [S3] |
| Neutralidade | Correlacao parcial negativa com o mercado (perto de -0,41), perdeu dinheiro liquido em um unico ano desde 1989. So fonte secundaria | [SEC] [S7] |
| Capacidade | Fechado a clientes de fora em 1993, so funcionarios desde 2005; devolve lucros todo ano; teto perto de US$ 10 bilhoes (outra fonte diz US$ 15 bi) | [CONF] [S1] [SEC] [S6] |
| Custo | Cobrava 5% ao ano mais 44% do lucro | [CONF] [S1] |
| Custo de transacao e limpeza de dado | Nao achei fonte acessivel que descreva como modelavam custo de transacao ou limpavam dado | [NC] |

### 2.2 Resultados (com ressalva)

- Medallion 1988-2018: uns 66% ao ano antes de taxas e 39% depois (Cornell, 2019; livro de Zuckerman) [CONF no relato, [S3]]. **Contestado:** artigo de 2024 de Guo e Liu diz que compor direto os retornos anuais divulgados e incorreto e estima o retorno composto bruto abaixo de 35% ao ano [CONF] [S4]. O numero liquido de uns 40% ao ano de 1988 a 2023 e o mais citado [S1].
- Em 2020 o Medallion fez +76%, enquanto os fundos abertos a terceiros perderam (RIEF -22,62%, RIDA -33,58%); o RIEF rendeu 8,05% ao ano desde 2005, contra 9,6% do S&P 500, com queda de 35,73% de maio/2007 a abril/2009 [CONF] [S2]. Leitura: a MESMA casa, quando abre capacidade e prazo, nao entrega o mesmo. O que vale e a versao pequena, curta e fechada.

### 2.3 O que NAO se copia com R$ 100 mil e 200 ms de atraso

| Ingrediente | Por que nao cabe | Numero do projeto |
|---|---|---|
| Prazo curto e muito giro | Custo de ida e volta em acoes e uns 0,11% do valor; WIN uns 0,01%; WDO uns 0,02% | O sinal intradiario de acoes e real (t 6,8) e 5 a 10 vezes menor que o custo [LEIA.md, 09/10] |
| Alavancagem barata | Aqui financiar custa o CDI (efetivo de 13,65% pelas fontes de setembro) e o robo tem limite de perda de 1% ao dia | Meta de 0,5% ao dia pede oscilar uns 4% ao dia [LEIA.md, 09/10] |
| Execucao e infraestrutura | Atraso de 200 ms, sem acesso a livro profundo nem a corretora de cada lado | Historico da B3 de negocios so 20 pregoes com corretora; sem agressor longo [LEIA.md, 10/10] |
| Escala de dado e de gente | Dezenas de cientistas, dado de tudo | Fontes gratuitas (B3, CVM, NEFIN, BCB) |
| Venda a descoberto em escala | Aluguel de acao e caro e limitado (secao 6) | n/a |

### 2.4 O que se aproveita

Disciplina estatistica (hipotese antes do codigo, registro de tentativas, Sharpe deflacionado: ja em vigor em `METODO.md`), custo real dentro de toda conta, saber que o sinal morre (decaimento) e a humildade de tratar o modelo como um pedaco da realidade.

### 2.5 Veredito por ensinamento

| Ensinamento | Vale aqui? | Por que |
|---|---|---|
| Muitos sinais pequenos num modelo so | Com adaptacao | O projeto ja fez (quarta rodada): a soma de efeitos pequenos nao paga o custo em nenhum dos tres mercados. Vale como metodo (combinar e medir custo), nao como fonte de retorno |
| Prazo curto, giro alto | Nao vale | Custo 3 a 20 vezes maior que o efeito em acoes |
| Alavancagem | Nao vale | CDI de 13,65% e limite de perda do robo |
| Neutralidade ao mercado | Com adaptacao | Hedge com mini-indice ja existe (`protecao.py`); no teste de 2016-2026 ele nao agregou (principal 10,8% a.a. contra 14,2% sem protecao). A base do futuro (CDI menos dividendos) nao foi medida |
| Capacidade limitada | Vale como esta | Com R$ 100 mil capacidade nao e problema |
| Registro de tentativas, custo como ciencia | Vale como esta | Ja e regra |
| Sinal morre | Vale como esta | O fim do pregao no WIN teve Sharpe 3,68, depois -0,91 e -3,65 (2021-24, 2025, 2026) |

### 2.6 Regras para o robo

**G1. Razao edge/custo como triagem (regra de pesquisa).**
- Mede: ganho medio bruto por operacao dividido pelo custo de ida e volta (`custos.py`, `lab.ESPEC`, e o slippage MEDIDO pelo `execucao/paper.py`).
- Regra: sinal so entra na fila de teste se a razao for 3 ou mais na descoberta. Custo usado e o medido; stress com o dobro.
- Teste: conta antes de qualquer Sharpe; cada sinal triado entra no livro de tentativas. Barato e evita gastar N do Sharpe deflacionado.
- Prior: filtra, nao gera retorno. Em acoes intradiarias a razao hoje e de 0,1 a 0,2.

**G2. Aposentadoria de sinal por decaimento.**
- Mede: media e t do resultado liquido dos ultimos 60 pregoes de cada modulo ou setup contra o que a descoberta esperava.
- Regra [MINHA, parametros fixos antes]: se a media de 60 pregoes e negativa e o t de 60 e negativo, o lote cai a zero e o setup continua em sombra (so mede). Volta quando 40 pregoes de sombra tem media positiva e t acima de 1. Se a media de 60 pregoes e menos de metade da esperada, lote pela metade.
- Teste: aplicar retroativamente ao fim do pregao no WIN e a reversao do dado no WDO (barras de 1 minuto desde 2021); medir perda evitada e lucro cortado contra o lote fixo; descoberta 10/2021-12/2024, validacao 2025, prova 2026 uma vez. Atencao: a variante "filtro de 60 pregoes" do fim do pregao JA foi reprovada em 2026; esta regra e disjuntor de lote (risco), nao filtro de entrada, e o que se mede e a perda evitada.
- Prior: protege, nao cria alfa. Risco de cortar na hora errada (whipsaw).

**G3. Largura lenta: tendencia de 12 meses em dolar, juros e indice, risco igualado.**
- Ideia herdada: largura (muitos mercados) sobe o retorno por unidade de risco; aqui so ha poucos mercados.
- Mede: retorno de 12 meses (pulando o ultimo mes) de PTAX, taxa DI de 2 anos (arquivos TS da B3) e Ibovespa; posicao long/short por sinal, tamanho por 1/vol de 60 dias, execucao mensal em WDO, DI1 (ou so sinal em sombra) e WIN.
- Teste: desenvolvimento 2005-2015, validacao 2016-2020, prova 2021-2026 aberta uma vez [MINHA]; custo medido; 5 parametros no maximo; comparar contra o Ibovespa com o mesmo beta.
- Prior: baixo para a bolsa (a leitura de regime da propria carteira, media de 200 dias e retorno de 12 meses, falhou em 2020); dolar e juros nao foram testados. Nao confirmei evidencia brasileira publicada [NC].

---

## 3. Octavio Magalhaes (Guepardo Investimentos)

**Esfera onde vive:** acoes brasileiras, long only (nenhuma venda a descoberto: acertar a compra ja e dificil, segundo trecho do livro Fora da Nova Curva [S19]), fundo de R$ 3 a 6 bilhoes (R$ 6,82 bi no total da gestora em set/2026, [S18]), sem macro.

**Frase (uma):** "Bateu o preco-justo, tchau." [S11].

### 3.1 Processo

| Ponto | O que as fontes dizem | Rotulo |
|---|---|---|
| Ordem das etapas | 1) filtro qualitativo (governanca, gestao, estrategia, cultura, setor, liquidez) SEM olhar numero; 2) so depois o valuation. De uns 500 papeis listados passam uns 70; destes a carteira tem no maximo 14. Questionarios com perguntas eliminatorias | [CONF] [S11] [S12] [S19] |
| Por que qualitativo primeiro | Todos os erros passados foram qualitativos (empresa barata por problema de fundo, a armadilha de valor); governanca, pessoas e estrategia pesam mais que erro de PIB ou cambio | [CONF] [S16] [S19] |
| Macro | Nao acompanha; relatorios macro e de terceiros evitados; cambio ou PIB mudam pouco o fluxo de caixa perto do tamanho do desconto | [CONF] [S11] [S12] |
| Valuation | Projeta receita e fluxo de caixa e faz fluxo de caixa descontado; compra so o que esta barato; descarta ate boa tese se cara | [CONF] [S11] [S15] |
| Quando compra | Quando o mercado rejeita uma lider (reacao exagerada); quando a bolsa cai, aumenta | [CONF] [S15] [S16] |
| Quando vende | (1) quando prefere a renda fixa para esperar a proxima; (2) quando esta 100% investido e troca por papel mais barato; (3) quando erra a tese qualitativa, e o papel sai da lista para sempre. Ao chegar no preco justo zera. Um papel ficou sete anos | [CONF] [S11] [S20] |
| Rotatividade | Para ele o segredo e a rotatividade da carteira: segurar barato por muito tempo reduz retorno e impede trocar por oportunidade melhor | [CONF] [S19] |
| Concentracao e tamanho | Ate 14 papeis (12 em 2025; ja teve 5). Maior posicao 17% (Klabin, 2024). Depois do caso BRF (chegou a 35%; fundo caiu 36% em 2015) o teto passou a 25%. Para ele muita posicao e diluicao, nao diversificacao. Tamanho varia com conviccao e perfil da empresa | [CONF] [S12] [S11] [S20] |
| Liquidez | Com R$ 3 bi, 1% do fundo e R$ 30 milhoes; pequenas ficam fora. Tentou alocar R$ 1 bi em Copasa (cerca de 2% do fundo) e nao conseguiu | [CONF] [S15] [S10] |
| Caixa | Quase nunca (diz que nunca migra para a renda fixa); se faz, e reserva curta em LFT; alerta contra ter acoes e NTN-B juntas porque caem juntas | [CONF] [S13] [S14] |
| Ativismo | Em 2012, a gestora disse que os representantes dela em conselhos eram em muitos casos figuras decorativas e que se envolvia com a gestao (caso Bematech). Nada recente confirmado | [SEC] [S49] [NC atual] |
| Derivativos | Nao confirmei uso em fonte aberta; ha um fundo Long Bias na casa, sem descricao do hedge | [NC] [S18] |

### 3.2 Resultados (com ressalva)

- Guepardo C (o mais antigo, de maio/2001): +8.810% ate 07/2024 [S11, nao verificado]; 21,1% ao ano liquido por 25 anos, segundo a carta trimestral de maio/2026 [S21]; 22 anos a 22% ao ano contra CDI de 11,7% e Ibovespa de 9,8% [S15, numeros da reportagem, nao dele].
- Queda de 36% em 2015 (BRF) e alta de 51% em 2016; 2019 +109% contra 32% do Ibovespa [S12].
- **Ressalva grande:** em 08/10/2026 o Institucional estava com +28,21% em 12 meses (Ibovespa +27,42%), mas **+56,26% em 36 meses contra +59,86% do Ibovespa**; no ano +36,37% contra +27,99% [S18]. O melhor historico de valor da B3 nao ganhou do indice em 3 anos.
- A gestora diz que a maioria dos cotistas que resgatou ficou menos de um ano [S15, S16]: o resultado depende de aguentar o caminho.

### 3.3 Como a TIR e montada: o que ele disse e o que nao disse

Outra frente esta construindo a tela de TIR real implicita no terminal. Este e o resumo do que se pode afirmar com fonte, para a tela nao atribuir a ele o que ele nao publicou.

| Item da tela | O que ele disse em publico | O que NAO confirmei | Para a tela |
|---|---|---|---|
| Nome | Fala em IPCA mais X%, em yield e em preco justo ou preco-alvo. Nao achei a expressao TIR real implicita em fala dele | Que ele chame assim | Rotular como TIR real implicita (metodo proprio, inspirado em falas publicas). Nao rotular como TIR da Guepardo |
| Fluxo projetado | Projeta receita e fluxo de caixa futuro da empresa, busca errar o minimo possivel nas projecoes de dez anos; faz fluxo de caixa descontado [S15] [S11] | Qual fluxo (para a firma, para o acionista, dividendos); se inclui recompra; como trata capex de crescimento | Mostrar qual fluxo foi usado e as premissas (receita, margem normalizada, capex) |
| Prazo | Menciona dez anos, tanto como horizonte do investidor quanto das projecoes [S15] | Se e janela explicita de 10 anos mais valor terminal | Janela de 10 anos explicita, mostrada |
| Valor terminal | Nada em fonte publica | Metodo (perpetuidade, multiplo de saida), crescimento terminal | Perpetuidade com crescimento real de 0% (base) e 2% (sensibilidade); mostrar o peso do terminal no valor |
| Real contra nominal | Sempre fala em retorno REAL, como spread sobre o IPCA: IPCA+14% para lideres amassadas (jul/2026) e IPCA+11% a 12% (jul/2024) [S9] [S10] [S13] | Qual trajetoria de IPCA usa (Focus?) | TIR em termos reais; deixar claro que trajetoria de IPCA entrou |
| Com que compara | NTN-B / Tesouro IPCA+: jul/2026 IPCA+8%; jul/2024 renda fixa a IPCA+6,5% a 7%. Nao considera a NTN-B livre de risco (risco do governo) [S9] [S10] [S13] | Prazo da NTN-B de comparacao | NTN-B de duracao parecida (a de 2035 e a de 2045); mostrar a data e a taxa usada |
| Premio exigido | Nas falas citadas: bolsa a IPCA+11% a 12% contra renda fixa a +6,5% a 7% (2024) = cerca de 4,5 a 5 pp; IPCA+14% a 15% contra +8% (2026) = cerca de 6 a 7 pp. Sao retornos que ele ve na bolsa em geral e em lideres amassadas, NAO a TIR da carteira dele | O premio minimo que ele exige para comprar | Mostrar o PREMIO (TIR menos NTN-B) como numero principal; sugestao [MINHA]: 4 pp de entrada (G5) |
| Saida | Vende quando chega no preco justo [S11] [S20] | A definicao numerica de preco justo | Preco justo = preco em que o premio sobre a NTN-B cai para uns 1 pp [MINHA] (G6) |
| Margem de seguranca | Elevada margem de seguranca, investir abaixo do valor intrinseco, sem percentual [S17] [S18] | O percentual | Nao inventar; mostrar o premio |
| Benchmark do fundo | O fundo usa como referencia IPCA + X% a.a., onde X e a media de tres meses das taxas do IMA-B 5+, fixada a cada semestre [S18] | n/a | Nao confundir com a TIR esperada: e um benchmark de mercado |
| Atencao tecnica (minha) | n/a | n/a | Juros pagos entram em FCO em algumas empresas e em financiamento em outras (CPC 03): o fluxo livre precisa ser conferido empresa a empresa |

### 3.4 Veredito por ensinamento

| Ensinamento | Vale aqui? | Por que |
|---|---|---|
| Qualitativo antes do numero | Vale como esta, mas e humano | Nao vira regra completa; so proxies (G12, G13) |
| Concentrar em ate 14 | Vale | Com R$ 100 mil e melhor ainda; depende de G7 |
| Acompanhar pelo retorno real contra a NTN-B | Vale com adaptacao | A mesma conta serve, mas o projeto so tem a versao mecanica (G4) |
| Vender no preco justo e rodar | Com adaptacao | IR de 15% por venda e custo de 0,11% pedem barreira de troca (G6) |
| Zero macro | Vale para a carteira dele, nao para o livro | Em livro multimercado macro e a camada tatica; Keleti mostra o oposto |
| Nunca ter caixa | Nao vale no livro | CDI paga uns 8% reais; caixa e posicao (G15) |
| Ativismo | Nao vale | R$ 100 mil nao tem voz |
| Liquidez como limite | Vantagem de ser pequeno | Ele nao consegue a Copasa; R$ 100 mil consegue |

### 3.5 Regras para o robo

**G4. TIR real mecanica: a regua unica da carteira.** [Octavio e Buffett]
- Hipotese: o preco paga, ou nao, o retorno real que o negocio entrega ao dono; comparar com a NTN-B resolve o custo de oportunidade brasileiro.
- Definicao [MINHA]: TIR_real(i,t) = FCFE_norm(i,t) / ValorDeMercado(i,t) + g_real. FCFE_norm = mediana dos 5 ultimos exercicios anuais (DFP, so o que ja tinha sido entregue em t) de FCO + capex (campos `fco`, `capex`, `fcf` de `cvm_fundamentos.ttm`/`metricas`), para tirar pico de ciclo. g_real = 0% na base, 2% de sensibilidade, nunca acima de ROIC x reinvestimento. Financeiras: lucro liquido normalizado x (1 - g/ROE). Valor de mercado: `painel_fundamentos.valor_de_mercado`. Premio = TIR_real menos a taxa real da NTN-B de ~8 a 10 anos na mesma data.
- Cuidados: LPA zero, acoes em tesouraria no FRE, juros em FCO ou financiamento (CPC 03), eventos extraordinarios.
- Teste: primeiro CALIBRACAO, nao retorno (a TIR em t explica o retorno real realizado em 3 a 5 anos?). Isso exige dado a frente que so existe no periodo lacrado, entao a calibracao e prova viva. No desenvolvimento 2012-2015 so se confere o cano e o retorno de 12 meses (baixo poder).
- Prior: baixo a moderado. Value ja esta no score (25%) e o HML da carteira foi -0,13 no teste longo. A versao mecanica e uma sombra da projecao do gestor.

**G5. Entrada por premio sobre a NTN-B.**
- Regra: compra se (a) esta no universo da G13, (b) passa a G12 e (c) premio da G4 e 4 pp ou mais [MINHA; as falas de Octavio dao 4,5 a 7 pp]. Sensibilidade a 3 e a 5 pp (3 tentativas no livro).
- Tamanho: G7. Se nenhum nome passa, o dinheiro fica em CDI (G15).
- Teste: prova viva desde 10/2026, 36 meses; no desenvolvimento, so cano.
- Mata a regra: premio medio realizado nos 36 meses menor que 0 contra a carteira nula beta-equivalente (G16).

**G6. Saida no preco justo e barreira de troca.**
- Sai se o premio cai a 1 pp ou menos, ou se um alarme mecanico de tese quebrada dispara [MINHA]: ROIC de 12 meses abaixo de 50% da mediana de 5 anos por 2 trimestres, dl_ebitda acima de 4, FCF negativo em 4 trimestres, corte de dividendo acima de 50%.
- Troca de A por B so se premio_B menos premio_A for 3 pp ou mais, mais o IR de 15% sobre o ganho de A diluido em 3 anos. Na conta: barreira = 3 pp + 0,15 x ganho_A / 3.
- Evidencia de que rodar compensa: Octavio vendeu Klabin depois de +80% em 2019 e recomprou por volta de R$ 16, em posicao maior [S12]. Contra: imposto.
- Teste: prova viva; contar giro e imposto reais.

**G7. Concentracao e tamanho.**
- 8 a 12 nomes (ele: no maximo 14; Keleti recomenda 15 a 20 numa carteira equilibrada, o que e outra escola [S24]). Teto de 17% por nome (maior posicao dele em 2024), duro de 25% (depois da BRF); alavancados (dl_ebitda acima de 3) ficam em G11; teto de 25% por macrossetor (ja no projeto).
- Peso base 1/N, escalado entre 0,5x e 1,5x pelo premio acima do minimo [MINHA].
- Teste: simular so o risco (queda maxima e volatilidade contra 1/N); nao e fonte de retorno.

---

## 4. Christian Keleti (Alpha Key Capital)

**Esfera onde vive:** acoes brasileiras, estrategias long biased (comprado com protecao) e long short, gestora de ~R$ 0,8 a 1 bilhao [S33], fundada em 2018 por Keleti, Bruno Rignel e Mauricio Justo [S32]; Keleti vem de mesa de acoes (Hedging-Griffo e Credit Suisse) [S32]. Macro entra como FILTRO para escolher o tipo de empresa e para ler fluxo e juro, nao como previsao de indice.

**Frase (uma):** "uma assimetria muito grande ainda para as acoes domesticas" (Stock Pickers, InfoMoney 10/10/2026) [S31].

### 4.1 Processo

| Ponto | O que as fontes dizem | Rotulo |
|---|---|---|
| Comite | Comite de investimento diario (gestor, Keleti como co-gestor e analistas). Posicoes mais relevantes podem chegar a 15% da carteira; decisao nao unanime em um papel pode ir ate 5%; a decisao final e do Diretor de Gestao. Dados de 31/12/2020 | [CONF] [S23] |
| Macro como filtro de empresa | Kit Brasil 2.0: o kit antigo (bolsa sobe, dolar cai, juro cai) hoje seria o inverso; por isso receita em dolar e despesa em real, evitar pouco poder de repasse e muita divida, preferir bons pagadores de dividendo, boa governanca e estrutura de capital adequada. Energia como protecao contra inflacao; shoppings e construtoras | [CONF] [S26] |
| Balanco e juro alto | Prefere lideres com balanco capaz de atravessar cenario incerto e evita muito endividadas, porque com juro alto a divida ameaca a geracao de caixa. Nao compra so por desconto: barata hoje pode ficar mais barata amanha. Em ago/2026 deixou Simpar, Magazine Luiza e Rumo em observacao: ele pode comprar se a tese se confirmar, mas nao agora | [CONF] [S30] |
| Numero de acoes e alavancadas | Em artigo escrito por ele: pelo menos 15 a 20 acoes numa carteira equilibrada, 5 a 6 domesticas baratas, dominantes e pouco endividadas; para alavancadas, stop curto e no maximo 1% a 2% da carteira; avisa que na bolsa nem tudo volta e ha perda permanente de capital | [CONF] [S24] |
| Small caps | Posicoes menores nos fundos liquidos por falta de liquidez; ativo concentrado vai para fundo exclusivo de socios e clientes grandes, sem data de saida; compra abaixo do caixa da empresa em um caso; usa EV/EBITDA (~3x em Priner) e P/L (~8x em Porto Seguro) | [CONF] [S25] [S26] |
| Caixa e defesa | Em 18/03/2026: caixa de 20% a 25% do fundo rendendo Selic, postura defensiva; usa venda a descoberto contra empresas com balanco desequilibrado ou gestao duvidosa. Nao confirmei o instrumento do hedge (acao alugada, futuro, opcao) | [CONF] [S29] [NC instrumento] |
| Fluxo estrangeiro | Citando o ditado americano de nao lutar contra o fluxo: entrada de mais de R$ 12 bi em janeiro/2026 (quase metade de 2025), puxada por Vale, Petrobras e grandes bancos; perde-se a referencia de valuation; a defesa possivel e um hedge | [CONF] [S28] |
| Escassez de papel | ~200 acoes investiveis; ~218 empresas acima de R$ 300 milhoes de valor de mercado; recompras de R$ 55 bi desde 2022 reduzindo o free float | [CONF] [S27] [S28] |
| Juro e ciclo (hoje) | Ve espaco para Selic de 11% a 11,5% (palavras da reportagem), juros menores mudam os modelos e ampliam o ganho, e que as acoes fora do indice e as small caps vao comecar a andar; alavancagem critica das empresas por causa da Selic alta | [CONF parcial: parte e parafrase do jornalista] [S31] |
| Short em acoes | Aparece como topico do podcast Market Makers #70 (os shorts da carteira); o conteudo nao foi lido | [NC] [S32] |

### 4.2 Resultados (com ressalva)

- Fundo principal (declarado na entrevista): +33% no ultimo ano e +12,6% no ano ate nov/2024 [S25, autodeclarado].
- Alpha Key Acoes (long biased), site da gestora em 08/10/2026: +23,59% no ano contra +27,99% do Ibovespa; +124,51% em 36 meses; +172,46% desde 12/11/2018; taxa de 2% mais 20% sobre IPCA + IMA-B [S33]. Ou seja, **atras do indice no ano**, o preco de ser defensivo em ano de alta.
- Benchmark do fundo: CDI ate 2020; IPCA + IMA-B desde 2021 [S33] (a mesma cultura de retorno real de Octavio).

### 4.3 Veredito por ensinamento

| Ensinamento | Vale aqui? | Por que |
|---|---|---|
| Macro para escolher tipo de empresa (dolar, divida, repasse) | Vale com adaptacao | Octavio diz o contrario; so testando. Receita em dolar e divida em juro alto sao verificaveis no balanco (G8, G11) |
| Caixa 20% a 25% | Vale | CDI paga bem; vira G15 |
| Short contra balanco fragil | Com adaptacao | Aluguel caro justo onde a tese e melhor; testar ANTES do custo (G10) |
| Fluxo estrangeiro | Vale se houver dado | A B3 divulga participacao por tipo de investidor; nao confirmei se ha historico diario gratuito [NC] (G9) |
| Alavancadas pequenas com stop curto | Vale | Cabe no sizing (G11) |
| Small caps com posicao pequena | Vale | R$ 100 mil e pequeno de sobra, mas spread pesa |
| 15 a 20 acoes | Outra escola | Conflita com Octavio; com R$ 100 mil a conta de custo manda (G7) |

### 4.4 Regras para o robo

**G8. Juro cai, small e iliquidas andam (retro-teste barato).**
- Hipotese: custo de capital e alavancagem; quando o DI cai, quem deve mais e mais sensivel ao credito sobe mais. Do outro lado: quem ainda nao comprou small porque o juro acabou de cair e quem esta ancorado em bluechip.
- Mede: retorno mensal dos fatores NEFIN de tamanho (SMB) e iliquidez (IML) em funcao da variacao da taxa DI de 2 anos nos ultimos 63 pregoes (arquivos TS da B3), 2002-2015. Depois, com fundamentos, o par alavancadas (dl_ebitda de 3 a 6) menos baixa alavancagem em 2012-2015.
- Regra se passar: satelite de ate 15% do livro de acoes inclina para alavancadas e small quando a queda da DI de 2 anos nos ultimos 63 pregoes passa de 100 pontos-base; zera quando a DI sobe mais de 100.
- Teste: regressao e tercis em 2002-2015 (nao toca no lacre); depois prova viva. Poucos regimes: cerca de 6 ciclos de juro desde 2005, entao NAO ha como provar, so ver se o sinal tem o sinal certo [MINHA].
- Prior: baixo a moderado; o detector de regime anterior do projeto falhou.

**G9. Fluxo estrangeiro manda nas grandes.**
- Mede: compra liquida semanal de estrangeiros (B3, participacao por tipo de investidor) e o excesso do Ibovespa sobre o proprio mercado no mesmo periodo; testar se o fluxo da semana explica a proxima (continuidade).
- Regra se passar: sobrepeso de Vale, Itau, Petrobras (as maiores) quando o fluxo de 4 semanas esta no quartil superior; redutor quando no inferior; no maximo +-10% de peso.
- Dado: serie historica de fluxo por tipo de investidor da B3 [NC acesso gratuito e historico]. Sem o dado, a regra fica como visao da mesa. Proxy gratuito: EWZ contra Ibovespa convertido em dolar [MINHA].
- Prior: desconhecido; efeito de fluxo e real no curto prazo em mercados emergentes, mas nao confirmei estudo brasileiro [NC].

**G10. Short de fragilidade: testar antes do custo, depois com o aluguel.**
- Hipotese: empresas com balanco fragil (dl_ebitda acima de 4, FCF negativo, cobertura de juros baixa) rendem menos que o mercado em juro alto.
- Teste 1 (sem custo): carteira de fragilidade menos mercado, mensal, 2012-2015 e, antes do lacre, nada mais; se nao for negativa ANTES do custo, a regra morre.
- Teste 2 (com custo): so se passar o 1. Aluguel por papel: o NEFIN tem `aluguel_taxa`; a retencao publica da B3 e de ~21 pregoes [sinais.py]; faixa citada: 0,03% a 5% ao ano para liquidos e mais de 20% para pouco liquidos [S48]; em fev/2026 os maiores eram Raizen 38,1%, Cruzeiro do Sul 26,6%, Casas Bahia 25,4% [S48]. A alternativa e hedge com mini-indice (custo e a base do futuro, nao medida).
- Prior: baixo; Octavio nao faz short por principio.

**G11. Tamanho por fragilidade e por unanimidade.**
- Peso maximo por nome [MINHA, com base nos numeros de Keleti]: 15% se passa todos os portoes com folga de 2 pp; 5% se passa raspando (equivalente a decisao nao unanime no comite deles); 2% para alavancadas (dl_ebitda acima de 3), com stop de 15% abaixo do preco de entrada ou da maxima de 63 pregoes (a fonte diz stop curto sem numero; o 15% e meu); soma de alavancadas ate 8%.
- Teste: simulacao de risco (queda maxima, caudas) sobre a carteira S0; nao e fonte de retorno.

---

## 5. Warren Buffett (Berkshire Hathaway)

**Esfera onde vive:** EUA, capital permanente (seguradoras e float), juro historicamente muito menor que o brasileiro (nao busquei o numero de hoje), imposto diferido pela posse longa.

**Frase (uma):** "It's far better to buy a wonderful company at a fair price" (carta de 1989) [S36].

### 5.1 Processo

| Ponto | O que a fonte diz | Rotulo |
|---|---|---|
| Valor | Valor de um negocio e o valor presente dos fluxos de caixa que ele ainda vai gerar; crescimento so cria valor se cada real reinvestido gera mais de um real de valor de mercado; so compra se o valor calculado estiver bem acima do preco (margem de seguranca, de Graham) | [CONF] [S35] |
| Lucro do dono | Lucro contabil, mais depreciacao e itens nao caixa, menos o investimento medio anual necessario para manter posicao competitiva e volume (e capital de giro, quando preciso). Preferivel estimar a grosso modo a ser preciso e errado | [CONF] [S38] |
| Qualidade a preco justo | Melhor comprar uma empresa maravilhosa a preco justo do que uma mediana a preco maravilhoso; admite que demorou a aprender (Berkshire Hathaway e Hochschild Kohn foram erros) | [CONF] [S36] |
| Circulo de competencia | Nao precisa conhecer muitas empresas, basta avaliar bem as dentro do circulo e conhecer os limites. Quem segue a linha de comprar bom e segurar acaba concentrado e nao deve vender o craque so porque virou grande demais | [CONF] [S37] [S39] |
| Para quem nao e profissional | Fundo de indice de custo minimo; instrucao ao fiduciario do testamento dele: 90% em fundo S&P 500 barato e 10% em titulos curtos do governo | [CONF] [S39] |
| Caixa | Promessa de rodar a Berkshire com caixa de sobra, sem depender da boa vontade de estranhos; entre dormir bem e lucro extra, dormir. Mas, em 2008, escreveu que ficar em caixa ou titulo longo aos juros de entao seria quase certamente uma politica pessima se mantida por muito tempo | [CONF] [S34] |
| Humildade | Em 2008 listou erros que chamou de nao forcados: ConocoPhillips comprada perto do topo e dois bancos irlandeses (perda de 89%) | [CONF] [S34] |
| Opcoes que vendeu (2004-2008) | Puts europeias de indices (S&P 500, FTSE 100, Euro Stoxx 50, Nikkei 225), prazos de 15 a 20 anos, premio recebido adiantado (US$ 4,9 bi em 2008 sobre US$ 37,1 bi de nocional), sem margem na maioria. Ele acreditava que cada contrato estava mal precificado; o float dos derivativos (pagamentos recebidos menos perdas pagas) era de US$ 8,1 bi no fim de 2008. Critica o Black-Scholes para prazos longos (volatilidade historica e irrelevante a 100 anos) | [CONF] [S34] |
| Resultado das puts | As opcoes adicionaram US$ 2,4 bi ao lucro de 2008 a 2017, segundo relato de 2018; em 2011 a Berkshire registrou ganho de US$ 222 milhoes quando a contraparte pediu para encerrar oito contratos. A conta final nao confirmei | [SEC] [S41] [S42] [NC final] |
| Put em acao (1993) | Vendeu puts de Coca-Cola (strike US$ 35, premio de US$ 1,50, cerca de US$ 7,5 milhoes) para comprar mais barato; em 1994 disse que raramente faz isso | [SEC] [S40] [NC fonte primaria] |

### 5.2 Resultados

- Valor patrimonial por acao da Berkshire: +20,3% ao ano de 1965 a 2008 contra +8,9% do S&P 500 com dividendos [CONF] [S34]. Nota: e valor patrimonial, nao cotacao; e a empresa de hoje ficou grande demais para o mesmo ritmo.
- Nenhum desses resultados foi reproduzido na base do projeto; o que vem dele aqui e metodo, nao numero [MINHA].

### 5.3 Veredito por ensinamento

| Ensinamento | Vale aqui? | Por que |
|---|---|---|
| Qualidade a preco justo | Com adaptacao | Preco justo aqui e premio sobre a NTN-B (G5), nao P/L absoluto |
| Lucro do dono | Vale com adaptacao | Vira FCFE normalizado (G4); capex de manutencao nao vem separado na CVM |
| Margem de seguranca | Vale | E o premio exigido (G5) |
| Circulo de competencia | Vale, e e humano | Proxy: universo congelado (G13) |
| Caixa como opcao | Vale muito | CDI paga ~8% a 9% reais; G15 |
| Fundo de indice para o pequeno | Vale como benchmark nulo | Todo modulo tem de bater o indice com mesmo beta (G16) |
| Puts longas de indice, premio adiantado | Nao vale | Sem float, sem contraparte que pague adiantado por 15 a 20 anos; opcoes da B3 vencem em meses |
| Put em acao para comprar mais barato | Com adaptacao | Pesquisa do projeto: venda de put como RENDA nao paga (delta 0,25 recebeu 1,88% do strike por mes e pagou 1,90%; 40 configuracoes, nenhuma passou). Como forma de ENTRADA em nome que ja passou nos portoes, nao testado (G14) |
| Nunca vender o que cresceu | Com adaptacao | Em conflito com G6; so em nome que continua passando |

### 5.4 Regras para o robo

**G12. Filtro de qualidade do dono.**
- Mede (campos de `metricas`): ROIC, margem EBIT, dl_ebitda, FCF, nos ultimos 5 exercicios anuais (7 de 10 quando houver 10).
- Regra [MINHA]: ROIC maior que a NTN-B real mais 2 pp em 4 de 5 exercicios; desvio-padrao da margem EBIT de ate 5 pp; dl_ebitda ate 2,5; FCF positivo em 4 de 5. Financeiras: ROE maior que NTN-B real mais 3 pp em 4 de 5.
- Teste: nao ha janela de desenvolvimento com 5 anos de historico (primeira data viavel e 2016, lacrada). Prova viva desde 10/2026 com parametros congelados; nesse meio tempo, rodar em SOMBRA e comparar com a carteira de portoes atual (que nao agregou alfa: sem portoes, +4,1% ao ano sobre o CDI, Sharpe 0,39; com portoes, +1,2%, Sharpe 0,12) [RESULTADO_HOLDOUT].
- Prior: baixo (os portoes de qualidade atuais nao agregaram). O que muda e a estabilidade em vez do nivel; ainda assim hipotese.

**G13. Circulo de competencia: universo congelado.**
- Regra: lista congelada em 1 de janeiro e 1 de julho. Entra quem tem 5 exercicios anuais publicados (exclui IPO recente, em linha com Octavio, que raramente participa de IPO [S16]), PL positivo, prejuizo em no maximo 1 dos 5 anos, ADTV no piso do projeto, e fora de setores sem modelo estavel (Octavio cita evitar aereas [S16]). Segmento de listagem (Novo Mercado) como proxy de governanca: [NC] se o projeto tem o campo.
- Teste: cano em 2012-2015 (efeito na lista, nao no retorno); depois prova viva. Custo: reduz o universo; medir quantos nomes sobram.
- Prior: e filtro de risco mais que de retorno.

**G14. Put vendida como forma de entrar, nao como renda.**
- Hipotese: se o nome ja passou nos portoes e voce comprava de qualquer forma, vender a put no preco em que a G5 entraria troca esperar por ser pago para esperar.
- Regra: so em nome com opcao liquida (30+ negocios, spread ate 30% como na pesquisa) que passou G12 e G5; strike = preco em que o premio sobre a NTN-B seria 6 pp (um colchao acima de G5); vencimento de 14 a 30 pregoes; caixa integral (sem margem); delta de 0,15 a 0,25. Se exercido, entra na carteira ao preco que queria; se nao, fica o premio.
- Teste: corredor das opcoes (descoberta ate 2019, validacao 2020-2023, prova 2024-2026 uma vez); compara com comprar o papel no mesmo dia e com a mesma put em qualquer dia. Ja morreu: a mesma put sem condicao fundamental (40 configuracoes), com condicao tecnica (queda forte, vol implicita alta ou baixa, resultado do trimestre: nenhuma passou nas duas fases).
- Prior: baixo e com amostra minima, porque poucos nomes de qualidade tem opcao liquida (os preferidos de Octavio, como Ultra, Klabin, Allos, Vulcabras e Fleury, provavelmente tem pouca opcao liquida; nao verifiquei na base). Nao e fonte de retorno; e metodo de entrada.

**G15. Caixa como residuo, nao como previsao.**
- Regra: exposicao a acoes = soma dos pesos dos nomes que passam G5 e G12 (cada um respeitando G7). O resto fica em CDI. Nao ha chamada de mercado.
- Contraste a testar em sombra: sempre investido (Octavio) contra caixa residual (Buffett, Keleti: 20% a 25% em mar/2026).
- Teste: prova viva em sombra; dois livros paralelos.
- Prior: mecanica de G5; efeito depende de quantos nomes passam.

---

## 5A. Kinea: Marco Freire e Ruy Alves como referencia de pensamento macro (adendo de 11/10/2026)

Pedido do Douglas em 11/10/2026: colocar Marco Freire e Ruy Alves, da Kinea, como referencias de pensamento macro. Contexto dele: o modulo de acoes virou um livro de swing curto (posicao de no maximo 10 pregoes) e ele quer que o robo "pense como gestor de fundo, macro primeiro". Este adendo usa como fonte primaria o que a propria Kinea publica (cartas do gestor, apresentacoes das lives, Kinea Insights, site), lido pelo `mesa.py kinea` e pelo branch `dados`; entrevistas e materias entram como contexto rotulado. A lente para a mesa esta em `quant/saida/mesa/lente_kinea.md` e `lente_kinea.json`.

Rotulos como no resto do estudo: [CONF] confirmado em fonte que abri; [SEC] fonte secundaria; [NC] nao confirmei; [MINHA] desenho meu.

### 5A.1 Quem sao (fonte da propria Kinea, consultada em 11/10/2026)

| | Marco Aurelio Freire | Ruy Alves |
|---|---|---|
| Cargo no site | Partner and Liquid Funds Manager (pagina em ingles); socio e gestor dos fundos liquidos (pagina "Quem somos"). A apresentacao da Kinea de 24/09/2026 o apresenta como CIO e lider da gestao [S61] [S62] [S63] | Partner and Senior Manager of Open-Ended Funds; socio e co-gestor dos fundos multimercados desde fevereiro de 2020 [S61] [S62] |
| O que gere | Entrou em janeiro de 2015 como gestor de Hedge Fund Macro; o site nao detalha as carteiras de hoje [NC] | Estrategias de acoes e commodities dentro dos multimercados |
| Antes | CIO de renda fixa local e multiestrategia na Franklin Templeton Brasil (2008 a 2014); renda fixa e multimercados desde 2004 | Mais de duas decadas; estrategias globais de acoes na ADAM Capital, na JGP e na Aviva Investors (Londres) |
| Formacao | Economia (graduacao e mestrado), PUC-Rio | Mestrado em financas na London Business School; MBA no IBMEC; administracao na UERJ |

**Voz das cartas.** As cartas do gestor e as apresentacoes das lives mensais nao sao assinadas por pessoa [CONF]. Chronos, Atlas e Apolo usam o mesmo texto de carta e diferem na dose: objetivo de superar o CDI com volatilidade de 3% a 5% ao ano (Chronos), 5% a 7% (Atlas) e 1% a 2% (Apolo) [CONF, carta de setembro de 2026, p. 22 e fichas]. Por isso quase tudo abaixo e "pensamento da Kinea Multimercados"; atribuir cada frase a Marco ou a Ruy nao e possivel com o que li [NC]. Atribuir por classe de ativo (acoes e commodities a Ruy) e inferencia minha [MINHA].

**Como a casa decide.** Estrutura multigestor sobre um produto-base; Marco destacou a meritocracia de ideias como pilar (InfoMoney, 17/04/2022) [SEC] [S66]. O site diz que cada especialista tem autonomia e responsabilidade sobre as proprias decisoes e que a decisao e coletiva [CONF] [S62]; fala em alocacoes dinamicas baseadas em analises macro e microeconomicas, em posicoes direcionais e relativas, e em uma Pontuacao de Risco Kinea de mercado, credito e liquidez [CONF] [S64]. O site nao descreve como os cenarios sao construidos, nem orcamento de risco, limites ou stop [NC]. A apresentacao da Kinea de setembro/2026 diz que decisoes de investimento de alguns fundos passam por comite com o CIO dos multimercados [CONF] [S63].

### 5A.2 O que cada um diz em publico (contexto rotulado; nao e fonte de numero)

**Marco Freire**
- Seu Dinheiro, 23/08/2021: num cenario de crescimento fraco e incerteza politica, preferia empresas cujo crescimento depende menos da economia; a frase que uso dele: "um carro resistente e com bom piloto". O cambio era o ativo mais descontado; com Selic de 5,25% e juro de 10 anos perto de 11%, a bolsa precisaria render perto de 15% para valer o risco [SEC] [S67].
- InfoMoney, 17/04/2022: riscos de nova guerra fria, desglobalizacao, fiscal e transicao verde; neutro em acoes globais pela incerteza sobre o Fed; o retorno do primeiro trimestre veio de commodities, juros americanos e visao construtiva para o Brasil [SEC] [S66].
- Brazil Journal, 28/04/2023 (na epoca identificado como CIO): descreveu a ofensiva dos bancos centrais contra a inflacao como uma pesca predatoria que expoe primeiro os ativos frageis (SVB, Americanas); a Kinea estava vendida em bolsa americana e em moedas de paises endividados, e comprada em petroleo, moedas fortes e renda fixa brasileira [SEC] [S68].
- Seu Dinheiro, 25/02/2026 (BTG Summit): IA nao e bolha nem o fim dos empregos, e o grande tema do ano; atribui o enfraquecimento do dolar ao crescimento europeu e ao gasto fiscal alemao, nao a perda de credibilidade institucional dos EUA [SEC] [S69].

**Ruy Alves**
- Seu Dinheiro, 19/05/2023 (Market Makers #45): o mundo com um resfriado e a China com pneumonia, por causa da transicao para o consumo; nao acredita em previsao de longo prazo; energia mais cara e demografia desfavoravel [SEC] [S70].
- InfoMoney, 01/09/2023: o Brasil nao tem ativos suficientes para uma carteira eficiente, entao olhar para fora; tecnologia, bancos e energia nos EUA; China concentrada na BYD [SEC] [S71].
- Brazil Journal, 17/12/2024: carta de 2025 pelas quatro estacoes do ano (EUA primavera e verao, Brasil outono, China e Europa inverno); cerca de 80% do risco da carteira fora do Brasil; vendido em moedas europeias e no renminbi; a bolsa depende mais de crescimento do que de juro baixo [SEC] [S72].
- InfoMoney, 12/12/2025 (Stock Pickers, Onde Investir 2026): "Nunca investi em acoes de emergentes sem investir na moeda local"; o EWZ da exposicao ao Brasil a custo razoavel; ambiente favoravel a opcionalidades em bolsa e moeda; a rejeicao dos candidatos e a chave da eleicao [SEC] [S73].

Nao li o que os dois disseram nas lives do canal: as legendas do YouTube nao foram coletadas (0 de 40 videos com legenda, coleta de 06/10/2026) [NC].

### 5A.3 Resultado, com ressalva (carta de setembro de 2026, p. 22 [S50])

| Chronos Geral Sub I | 2022 | 2023 | 2024 | 2025 | 2026 ate set | Desde 08/06/2015 |
|---|---|---|---|---|---|---|
| Fundo | 13,67% | 12,40% | 9,80% | 14,03% | 8,52% | 230,81% |
| CDI | 12,37% | 13,05% | 10,87% | 14,31% | 10,51% | 190,83% |
| % do CDI | 110,51% | 95,05% | 90,12% | 98,01% | 81,03% | 120,95% |

Rentabilidade divulgada pela Kinea, nao liquida de impostos. Em 12 meses ate setembro/2026 o Chronos rendeu 12,89% contra 14,48% do CDI; por estrategia: moedas +1,81 pp, juros -1,30 pp, acoes +0,60 pp, commodities +0,12 pp, despesas -2,64 pp. O Atlas (dose maior) esta em 8,03% no ano (76,41% do CDI) e o Apolo (dose menor) em 9,82% (93,39%). **Leitura honesta:** desde 2023 a Kinea Multimercados nao entregou mais que o CDI depois das despesas; pensar como ela nao e promessa de alfa.

### 5A.4 Atualizacao que muda numeros do resto do estudo

O terminal (`hist/TD-IPCA-2035.json`, Tesouro Transparente, taxa de venda) mostra o Tesouro IPCA+ 2035 a 8,31% em 23/07/2026, 7,82% em 03/09, 7,67% em 02/10 e 6,81% em 09/10/2026; a curva indicativa da Anbima de 09/10 traz a NTN-B 2035 a 6,69% (`rf.json`, real). Os "IPCA+8%" de Octavio (julho) e da Kinea (setembro) estao defasados em cerca de 1,2 a 1,3 ponto. A semana de 02/10 a 09/10 inclui o 1o turno (04/10); nao afirmo causa. Consequencia para G4 e G5: o premio exigido tem de ser medido contra a NTN-B do dia, nunca contra "8%". Consequencia para G1 a G18: a serie historica de NTN-B que eu dava como faltando no projeto existe no terminal (desde 27/09/2021); no projeto `quant` continua faltando.

## 5B. Os 12 principios macro da Kinea e o que viram no robo

Fonte: material da propria Kinea (cartas do gestor Chronos, Atlas e Apolo; apresentacoes das lives; Kinea Insights), voz institucional. Nenhum numero sem fonte e data. "No robo" diz a regra (G19 em diante, secao 5C) e o modulo, ou "pergunta da mesa" quando nao da para automatizar. Lembrete: o horizonte do swing e de 10 pregoes; a Kinea pensa em semanas e meses.

| # | Principio (parafraseado) | Fonte e data | No robo |
|---|---|---|---|
| 1 | Comeca por cenario com probabilidade e com preco de referencia por cenario. O cenario-base e o de maior massa de probabilidade; os de cauda viram hedge | Carta de set/2026 [S50]: base de PIB 1,0%, inflacao 4,7% e Selic 12,5% ao fim de 2027, com ajuste fiscal anunciado de cerca de 1,5% do PIB; carta de mar/2026 [S52]: tres cenarios para o Estreito de Ormuz com petroleo, Treasury de 10 anos e juro do Fed por cenario | G19 (o robo so mede os gatilhos); a narrativa e pergunta da mesa |
| 2 | Do global para o Brasil: Fed, curva americana e petroleo mandam no juro global; o Brasil entra pela curva de juros e pelo cambio | Carta de set/2026: Treasury de 10 anos acima de 5%, pressao nas curvas longas de todos os paises; live de 03/09/2026 [S55]: petroleo como chave dos juros globais, eleicao navegada principalmente via juros | G20 (termometro), swing e mini-dolar |
| 3 | A aritmetica fiscal manda no juro real brasileiro: primario perto de 2% do PIB para estabilizar a divida; indicador proprio coloca o Brasil como o emergente mais vulneravel | Carta de set/2026, p. 4; live de 03/09/2026, p. 24 a 26 | Pergunta da mesa (variavel lenta); entra em G26 so como premio |
| 4 | A eleicao se le por rejeicao, abstencao e agregador proprio de pesquisas, nao so por intencao de voto; para o mercado ela termina quando o vencedor disser com numeros como fecha a conta | Carta de ago/2026 [S51] e de set/2026; Ruy, InfoMoney, 12/12/2025 [S73] | Pergunta da mesa; o evento entra em G22 e G23 so no tamanho |
| 5 | Assimetria antes de direcao: nao basta estar barato, e preciso carrego, crescimento visivel, protecao ou catalisador; em vez de escolher lado, simplificar, proteger e manter convexidade; o que se administra e a exposicao, nao a previsao | Cartas de mai/2026 [S53], jan/2026 [S54] e set/2026 | G21 (swing) |
| 6 | Opcao comprada para ter convexidade com perda conhecida (calls de EWZ no pre-eleicao; opcoes de Nasdaq e, depois, de S&P 500) | Cartas de jan, mai, ago e set/2026; Ruy, 12/12/2025 (opcionalidades) | G22 (opcoes) |
| 7 | Mesmo portfolio em doses diferentes (volatilidade alvo de 1% a 2%, 3% a 5% e 5% a 7% ao ano); reduzir o numero de posicoes e hedgear antes do evento; exposicao neutra ao pais ate o fim do periodo eleitoral | Carta de set/2026 (fichas dos fundos); jan/2026; ago/2026 | G23 (escada de dose) |
| 8 | Hedge entre classes: petroleo e commodities como protecao parcial dos juros aplicados e da bolsa comprada | Cartas de abr, ago e set/2026 | G24 |
| 9 | Valor relativo entre mercados e vertices (aplicado onde a ociosidade vai impor juro menor; comprado em dolar e won contra euro; vender produtores de petroleo contra petroleo longo); em emergente, a moeda faz parte da tese | Carta de set/2026; carta de jun/2026; Ruy, 12/12/2025 | Em acoes da B3 nao ha o que automatizar; a parte de carrego do real vira G27; o resto e pergunta da mesa |
| 10 | Quando corta: a especulacao descola o preco dos fundamentos; a volatilidade sobe; a causa que sustentava o premio diminui (Ormuz); depois de valorizacao acumulada; reentra quando o posicionamento ficou limpo | Cartas de jan e fev/2026 (saida de ouro e metais), ago/2026 (volta ao ouro com o mercado mais limpo), set/2026 (reducao de petroleo, won, iene e financeiras) | G25 |
| 11 | Posicionamento e fluxo como termometro: fluxo estrangeiro na B3 em 12 meses, posicionamento especulativo em commodities, fluxo de ETFs de ouro | Live de 03/09/2026, p. 50; cartas de ago e set/2026 | G9 (atualizada); G20 |
| 12 | O premio de risco da bolsa e o earnings yield menos o juro real: o desconto esta nos juros, nao nas acoes (11,8% menos 7,8% = 4,0%, contra media de 5,0%, em 03/09/2026). Montar carteira que funcione nos dois desfechos, uma cesta que paga para esperar (utilities com TIR real implicita de 12,2% contra NTN-B 2045 a 7,5%) e outra que captura a queda de juros (bancos, varejo) | Live de 03/09/2026, p. 51; Kinea Insights de 16/09/2026 [S56] | G26 e G4/G5 |

**Nota para a tela de TIR do terminal.** O Kinea Insights de 16/09/2026 (p. 12 e 13) usa a expressao "TIR real implicita" para o setor de utilities (amostra fixa de 13 empresas; fontes citadas: Kinea, FactSet, Anbima e consenso sell-side) e a compara com a NTN-B 2045; e mostra tambem o crescimento anual composto do LPA mais o yield de dividendos de 2026 a 2028. E o unico lugar publico que achei em que uma casa nomeia a TIR assim. O metodo alem disso nao esta no documento [NC]. O Insights nao e assinado por pessoa.

## 5C. Regras G19 a G27 para o robo (livro de swing de ate 10 pregoes, alocacao, opcoes e mini-dolar)

Todas tem parametros fixos antes do teste e entram no `livro_tentativas.jsonl` ANTES de rodar.

**O livro de swing ja existe e tem pre-registro e corredor proprios** (lido em 11/10/2026 em `quant/swing/` e `quant/saida/pesquisa_swing/PRE_REGISTRO.md`): 39 variantes de 2 a 10 pregoes (familias de pullback, reversao, rompimento, deriva pos-resultado, forca relativa, gap e virada de mes), sobreposicoes S0 (nenhuma), S1 (metade de cima do ranking multifatorial) e S2 (Ibovespa acima da media de 200 pregoes), risco de 0,5% do capital por operacao, teto de 12% por nome e no maximo 10 posicoes. Corredor: descoberta 2010 a 2017, validacao 2018 a 2021, prova 2022 a 2026 aberta UMA vez e so para finalistas. **Em 11/10/2026 as 39 variantes rodaram em descoberta e validacao e nenhuma passou; a prova continua fechada** (`resultados_prova.json`); a melhor, deriva pos-resultado com metade de cima do ranking (D1.S1), teve excesso de 0,6 pp ao ano sobre o CDI e Sharpe de 0,28 na descoberta. Consequencias para G19 a G27: (1) G20, G23, G24 e G25 sao sobreposicoes de RISCO sobre uma base que ainda nao tem retorno liquido provado; so podem ser medidas em descoberta e validacao (2010 a 2021) e em prova viva, e NAO abrem a prova de 2022 a 2026; (2) cada uma entra no livro de tentativas como escopo novo, com o proprio N, sem mexer no N das 39; (3) sem finalista, elas rodam so medidas. A visao da mesa entra hoje no swing por `quant/mesa.py` (veto com conviccao -2, peso por conviccao e por inclinacao do setor, visao vencida nao muda nada, sem teste historico); G19 propoe um campo novo para ela. As series macro do terminal tem cerca de 1.250 pregoes (desde 08/10/2021); para ir mais longe, FRED, Yahoo e a curva DI da B3 (desde 2002). Limiares abaixo sao meus [MINHA], com sensibilidade de mais ou menos 20%.

**G19. Cartao de cenario com gatilhos e placar de calibracao.** Modulo: alocacao entre classes e porta do swing.
- Mede: toda segunda a mesa registra, antes da semana, um cenario-base e dois alternativos (probabilidades somando 100%) e, para cada um, tres gatilhos mensuraveis com dado do terminal (exemplo: Treasury de 10 anos acima de X; NTN-B 2035 abaixo de Y; Brent acima de Z), com verificacao em 5 e 10 pregoes.
- Regra: o robo le o cartao; so gatilho que disparou muda dose (G23) ou alerta (G20). A probabilidade escrita nao entra em conta de tamanho. Campo novo sugerido [MINHA] em `quant/saida/mesa/visao_mesa.json`: `cartao_cenario` com `base`, `alternativos`, `probabilidades` e `gatilhos` (variavel do terminal, limiar, data de verificacao); o `quant/mesa.py` nao o consome, so registra; o placar e um script a parte.
- Teste: placar de Brier de cada cenario e taxa de acerto do cenario-base por semana, contra um cartao ingenuo (probabilidades iguais) e contra a persistencia (repetir o cenario da semana anterior); no minimo 26 semanas.
- Prior: e medicao, nao retorno. Diz se a visao da mesa tem informacao.

**G20. Termometro global-Brasil.** Modulo: swing e mini-dolar.
- Mede: 7 variaveis diarias, cada uma 0 ou 1: Treasury de 10 anos sobe 25 pontos-base ou mais em 10 pregoes; dolar amplo (DXY) sobe 2% ou mais; Brent sobe 10% ou mais; VIX acima de 20 ou sobe 30%; spread de high yield dos EUA sobe 40 pontos-base; DI de 2 anos sobe 30 pontos-base; dolar/real sobe 3% ou mais (todas em 10 pregoes). Estado: 0 a 1 calmo; 2 a 3 alerta; 4 ou mais estresse.
- Regra: calmo, dose cheia; alerta, dose de 50% e sem novas entradas em setor sensivel a juro; estresse, sem novas entradas e saida parcial.
- Teste: como sobreposicao S3 (termometro em calmo) ao lado de S0, S1 e S2 do pre-registro do swing, sobre as variantes de melhor descoberta (D1, F2, A2), em descoberta e validacao (2010 a 2021), nunca na prova de 2022 a 2026; como o terminal so tem 5 anos de macro, as 7 variaveis precisam ser reconstruidas de FRED, Yahoo e curva DI ate 2010. Aprova se reduz a queda maxima em 20% ou mais, perdendo menos de 10% do retorno liquido, e nao piora em 2 dos 3 periodos; Sharpe deflacionado contra o numero de tentativas; no maximo 3 limiares livres.
- Prior: baixa a moderada. Reduz risco; pode cortar a recuperacao em V (a leitura de regime lenta da carteira falhou em 2020; aqui as variaveis sao rapidas, mas a regra continua defasada em alguns dias).

**G21. Assimetria minima na entrada do swing.** Modulo: swing.
- Regra: entra so se (alvo menos entrada) dividido por (entrada menos stop) for 2 ou mais, com stop de 1,5 x ATR de 14 pregoes e alvo igual ao maior entre 3 x ATR e a maxima de 20 pregoes; sem catalisador datado dentro da janela (resultado, Copom, dado), exige 3 ou mais.
- Mede: o resultado em multiplos de risco por faixa da razao ex-ante. No pre-registro, as razoes alvo/stop das 39 variantes ja vao de 1,25 (B1) a 2,0 (C2, D1 e D2); a G21 nao pede variante nova: e a analise por faixa sobre as 39 ja rodadas (`resultados_dv.json`), mais a separacao das familias com catalisador datado (resultado e gap).
- Teste: a faixa alta ganha da baixa com t de 2 ou mais na descoberta e mesmo sinal na validacao.
- Prior: baixa. A razao ex-ante e mecanicamente ligada ao stop; o que a Kinea chama de assimetria inclui carrego e catalisador, que em 10 pregoes sao quase zero.

**G22. Opcao comprada como expressao de evento binario.** Modulo: opcoes (e swing).
- Regra: quando o cartao (G19) marcar um evento binario com data (exemplo: 2o turno de 25/10/2026; Copom; payroll) e o termometro nao estiver em estresse, trocar ate 50% do beta direcional do swing por call ou put de BOVA11 com vencimento logo depois do evento; perda maxima igual ao premio, premio total de ate 0,5% do capital por evento; nada de venda de premio.
- Teste: eleicoes de 2014, 2018 e 2022 e os Copom e payroll recorrentes no corredor do modulo de opcoes, contra manter o beta direto; custo real.
- Prior: baixa, amostra minima (3 eleicoes). O piso e o que o projeto ja mediu: capital protegido, +1,0 pp acima do CDI, Sharpe deflacionado 0,47.

**G23. Escada de dose de risco em tres degraus.** Modulo: swing e mini-dolar.
- Regra: tres degraus fixos de volatilidade alvo do livro, na razao 1 para 2,5 para 4 (os pontos medios das fichas de Apolo, Chronos e Atlas, de 1,5%, 4% e 6% ao ano, em escala do modulo). Degrau medio no estado calmo sem evento; baixo em alerta ou a ate 5 pregoes de evento binario; zero em estresse; o degrau alto so existe depois de 36 meses de prova viva (G16). Nunca acima do teto de perda (G17).
- Teste: simulacao do swing com a escada contra dose fixa; Sharpe e queda maxima; sem otimizar os degraus. A escada estende a mao do dia de `config_carteira.exposicao_acoes(hoje)`, que continua sendo o teto de exposicao do swing; nao a substitui.
- Prior: moderada como controle de risco; extensao de G17 e G18.

**G24. Hedge por correlacao medida em estresse.** Modulo: swing e alocacao.
- Regra: so hedgeia com o termometro em alerta ou estresse. Candidatos: venda de mini-indice (WIN), compra de mini-dolar (WDO), ouro (OURO11) e uma cesta de petroleiras (a B3 nao tem Brent; PETR4 e PRIO3 como substituto imperfeito). Escolhe o de menor correlacao e menor custo medido nos 20% piores dias do livro nos ultimos 250 pregoes; tamanho igual ao beta do livro x exposicao x 50%.
- Teste: reducao da queda maxima menos custo e base, contra nao hedgear; 2021 a 2026 no terminal.
- Prior: baixa a moderada. A protecao com mini-indice nao agregou no teste longo da carteira (principal 10,8% ao ano contra 14,2% sem protecao); o petroleo da Kinea nao tem instrumento direto aqui.

**G25. Corte parcial por esticamento, corte por causa invalidada, reentrada apos limpeza.** Modulo: swing.
- Regra: (i) sai de 50% quando o ganho passa de 2 x ATR em ate 5 pregoes e o estado do termometro piorou; (ii) sai de tudo quando o gatilho do cartao que justificou a entrada foi invalidado; (iii) tempo maximo de 10 pregoes (ja existe); (iv) so reentra no mesmo ativo ou setor depois de volatilidade realizada de 5 pregoes abaixo da mediana de 60 e volume abaixo da media de 20 (proxy de posicionamento limpo).
- Teste: resultado em multiplos de risco e queda maxima contra sair so por stop e tempo; 3 parametros fixos.
- Prior: baixa. Saida e onde mais se sobreajusta.

**G26. Premio de risco da bolsa como teto de exposicao e calibrador do premio de G5.** Modulo: alocacao entre classes (nucleo).
- Mede: ERP = earnings yield agregado do universo (trailing, PIT; ou consenso de 12 meses do terminal) menos a NTN-B 2035 do dia. A Kinea mediu 11,8% menos 7,8% = 4,0% em 03/09/2026, contra media historica de 5,0%; com a NTN-B a 6,81% (09/10) tem de ser recalculado.
- Regra: ERP abaixo do percentil 30 de 5 anos (10, quando houver serie longa): teto de 50% na exposicao do nucleo (G15); acima do 70: sem teto; o premio minimo de G5 passa a ser o maior entre 4 pp e o ERP mediano do periodo.
- Teste: prova viva (variavel lenta; a janela lacrada impede o teste historico); descritivo: o ERP explica o retorno de 12 meses?
- Prior: baixa; e calibrador, nao gatilho de swing.

**G27. Mini-dolar de 10 pregoes no sentido do carrego, so em regime calmo.** Modulo: mini-dolar.
- Regra: com o termometro em calmo e a DI de 2 anos sem subir, vendido em mini-dolar (comprado em real) por ate 10 pregoes, com stop de 1,5 x ATR; zerado em alerta; comprado em dolar so em estresse E com rompimento da maxima de 20 pregoes.
- Racional: a Kinea declarou posicao comprada em real e aplicada em juros em marco/2026 [S52] e carrego via real em dez/2025 [SEC]. Conta minha: com CDI de 13,65% ao ano o carrego de 10 pregoes e perto de 0,5%; o dolar/real no terminal (`hist/USDBRL.json`, 11/10/2021 a 10/10/2026) teve volatilidade de 14,0% ao ano (12,0% nos ultimos 250 pregoes) e desvio-padrao de 2,37% em 10 pregoes (1,74% nos ultimos 250). O carrego e uma fracao pequena do risco.
- Teste: dolar futuro continuo diario (2005 em diante, se conseguir) e barras de 1 minuto desde 2021; custo real; corredor do day trade ou do modulo de opcoes, a definir.
- Prior: baixa; carry trade tem cauda (queda do real em estresse), e em 5 anos de pesquisa no mini-dolar so a reversao do dado americano passou, e fraca.

**G9 (atualizada em 11/10/2026).** O terminal tem o saldo diario do estrangeiro por tipo de investidor (`b3.json`, bloco `fluxo`, serie diaria desde 28/08/2026 direto da B3 e, antes disso, saldos arredondados do historico do boletim; profundidade nao verificada). A regra continua a mesma (fluxo de 4 semanas inclina para as maiores); o teste passa a depender de acumular historia: 12 meses de serie no minimo.

**O que NAO da para automatizar e vira pergunta da visao semanal da mesa:** a narrativa do cenario e as probabilidades (principio 1); a aritmetica fiscal e a leitura de rejeicao, abstencao e calendario politico depois de 25/10 (principios 3 e 4); o valor relativo entre mercados globais (principio 9); o caminho da receita de IA (carta de set/2026, p. 14 e 15: receita dos laboratorios de cerca de US$ 150 bi anualizados para cerca de US$ 450 bi no fim de 2027).

**O que nao confirmei sobre a Kinea:** o que Marco e Ruy disseram nas lives (legendas nao coletadas); a apresentacao da live de 02/10/2026; a data exata de publicacao da carta de setembro de 2026 (esta na pasta de outubro do site); a atribuicao de cada frase das cartas a um dos dois; a probabilidade de cada cenario da carta de marco/2026 (o texto extraido mostra 40%, 20% e 40% sem dizer qual e qual); como a Kinea monta a TIR real implicita alem do que aparece nos graficos do Insights; o orcamento de risco e os limites dos multimercados (o site nao os descreve).

---

## 6. O que muda na bolsa brasileira (com numero e fonte)

| Fator | Numero e fonte | Efeito nas regras |
|---|---|---|
| Juro real alto e CDI como concorrente | Selic 13,75% em 16/09/2026, 5o corte seguido; Selic efetiva 13,65%; juro real ex-ante de uns 8,4% a 9,1% (conta minha com IPCA do Focus de 4,9% em 2026 e 4,3% em 2027, [S45], fontes agregadoras; conferir no BCB). Octavio compara com NTN-B a IPCA+8% [S10]. Atualizacao de 11/10/2026: pelo terminal o Tesouro IPCA+ 2035 foi de 8,31% (23/07) para 7,67% (02/10) e 6,81% (09/10); Selic meta de 13,75% e efetiva de 13,65% confirmadas em `macro.json` (BCB SGS 432 e 1178) | Todo preco se mede contra NTN-B (G4 a G6); caixa e posicao (G15); venda de premio precisa pagar mais que o CDI (nao pagou: G14) |
| Poucas empresas liquidas | Ibovespa com 76 papeis, 10 maiores = 54% (S&P 500: 39%); ~200 investaveis (Keleti) [S43] [S28] | Concentracao permitida; diversificacao real exige limites por setor |
| Commodities e bancos | Previa de set-dez/2026: Vale 11,665%, Itau PN 8,809%, Petrobras PN 7,485%; commodities acima de 24% (Vale + Petrobras), financeiro 18,7% [S43] [S44] | Stock picking muitas vezes e aposta em 3 nomes; limites por setor (25%) e por nome (G7) |
| Estatais e risco politico | Octavio: a NTN-B carrega risco de governo [S9]; outro gestor (Encore) diz que cerca de 65% de Lula ja esta no preco [S10]. Axia (ex-Eletrobras), Petrobras e bancos com peso grande no indice | Eventos binarios sao visao da mesa; risco politico entra no tamanho (G18) |
| Ciclo eleitoral | Estudo do proprio Douglas (01/10/2026): pico de volatilidade da bolsa no mes seguinte ao 1o turno em 2002, 2014, 2018 e 2022; dia seguinte ao 1o turno +4,7% (2014), +4,6% (2018), +5,5% (2022), -4,3% (2002); 2o turno em 25/10/2026 | Nao vira regra automatica (poucos eventos); entra em G18 como gatilho de reducao |
| Cambio | Keleti: receita em dolar e despesa em real [S26]; Octavio: cambio muda pouco o fluxo perto do desconto [S11] | Dois gestores se contradizem; testar (G8, G11). O dolar anda NA FRENTE de outros mercados no intradia (LEIA.md, 08/10) |
| Fluxo estrangeiro | Mais de R$ 12 bi em jan/2026; R$ 45 bi de estrangeiro e R$ 35 bi de saida de fundos locais nos dois primeiros meses de 2026 [S28] [S29] | G9 (se houver dado) |
| Liquidez de opcoes | A pesquisa do projeto usa os 25 ativos de maior volume; validacao e prova com seis (PETR4, VALE, BOVA11, ITUB4, BBDC4, BBAS3) | Put condicional (G14) quase sem amostra |
| Tributacao | Swing de acoes 15%, day trade 20%; isencao de R$ 20 mil/mes so para venda de acoes a vista em swing; opcoes 15% swing e 20% day trade, sem isencao; prejuizo compensa por modalidade; dividendos: retencao de 10% sobre o total do mes quando uma empresa paga mais de R$ 50 mil a uma pessoa fisica, desde 01/01/2026 (Lei 15.270/2025); imposto minimo para renda anual acima de R$ 600 mil [S46] [S47] | Barreira de troca (G6); dividendo pesa em carteira grande; conferir com contador |
| Aluguel e venda a descoberto | 0,03% a 5% ao ano em liquidos, acima de 20% em pouco liquidos [S48]; fev/2026: Raizen 38,1%, Cruzeiro do Sul 26,6%, Casas Bahia 25,4% [S48]; short interest mediano do Ibovespa 7,1% | G10 (testar antes do custo) |
| Escala | Guepardo nao consegue R$ 1 bi em Copasa [S10]; R$ 100 mil consegue | Vantagem de ser pequeno; spread de small pesa |

---

## 7. Regras testaveis (resumo em tabela)

Detalhes de cada uma nas secoes 2 a 5. A coluna Teste resume a janela e o criterio; todas passam pelo livro de tentativas e pelo METODO.md.

| ID | Regra | Dados do projeto | Teste |
|---|---|---|---|
| G1 | Edge bruto / custo de ida e volta >= 3 como triagem | custos.py, paper.py, lab.ESPEC | Descoberta, custo medido, stress 2x |
| G2 | Lote zero se media e t de 60 pregoes < 0; volta com 40 pregoes de sombra positivos | barras de 1 min WIN/WDO | Retroativo no fim do pregao e no dado americano |
| G3 | Tendencia de 12 meses em dolar, juros e indice com risco igualado | PTAX, DI (TS da B3), Ibovespa | Dev 2005-2015, validacao 2016-2020, prova 2021-2026 |
| G4 | TIR real = FCFE normalizado / valor de mercado + g real | DFP/ITR PIT, FRE, cotacoes | Calibracao so em prova viva |
| G5 | Compra se premio sobre NTN-B >= 4 pp e passa G12/G13 | G4, NTN-B | Prova viva 36 meses |
| G6 | Vende com premio <= 1 pp; troca com barreira de 3 pp + IR | G4 | Prova viva, medir giro e imposto |
| G7 | 8 a 12 nomes; teto 17% (duro 25%); escala 0,5x a 1,5x | carteira.py | Simulacao de risco |
| G8 | Juro cai (DI 2 anos), small e iliquidas sobem | NEFIN SMB/IML, DI, dl_ebitda | Regressao 2002-2015, depois prova viva |
| G9 | Fluxo estrangeiro de 4 semanas inclina para as grandes | fluxo B3 (a achar) | Se houver dado, 2005-2015 |
| G10 | Carteira fragil menos mercado negativa ANTES do custo | dl_ebitda, fcf, aluguel | 2012-2015, depois custo |
| G11 | Tetos 15%, 5% e 2%; stop de 15% nas alavancadas | metricas | Simulacao de risco |
| G12 | ROIC > NTN-B + 2 pp em 4 de 5 exercicios, margem estavel, divida baixa | metricas anuais | Sombra e prova viva |
| G13 | Universo congelado, sem IPO recente nem setor sem modelo | identidade, setores | Cano, tamanho da lista |
| G14 | Put vendida (caixa integral) so em nome que passou G5/G12 | cadeia de opcoes B3 | Corredor das opcoes |
| G15 | Exposicao = soma dos nomes aprovados; resto no CDI | G5/G12 | Dois livros em sombra |
| G16 | Cada modulo contra benchmark de mesmo beta; 36 meses de prova viva | NEFIN, indice | Alfa e t |
| G17 | Tamanho por risco: alvo de vol por modulo, meio Kelly como teto | risco_robo.json | Simulacao de limites |
| G18 | Gatilhos para diminuir e aumentar a mao (secao 9) | todos | Prova viva; nao otimizar |
| G19 | Cartao semanal de cenario com gatilhos e placar de Brier | terminal (macro, rf, hist) | 26 semanas contra cartao ingenuo e persistencia |
| G20 | Termometro de 7 variaveis (calmo, alerta, estresse) para dose e entradas do swing | hist, macro, rf | Corredor proprio do swing; queda maxima -20% com perda de retorno < 10% |
| G21 | Assimetria minima 2 para 1 (3 para 1 sem catalisador) na entrada do swing | ATR, calendario | Retorno em multiplos de risco por faixa da razao |
| G22 | Call ou put de BOVA11 no evento binario, premio ate 0,5% do capital | cadeia de opcoes B3 | Corredor das opcoes (3 eleicoes) |
| G23 | Escada de 3 degraus de dose (1 : 2,5 : 4) amarrada ao termometro | G20, risco_robo.json | Simulacao contra dose fixa |
| G24 | Hedge escolhido por correlacao nos 20% piores dias do livro | WIN, WDO, OURO11, petroleiras | Queda maxima evitada menos custo |
| G25 | Corte parcial por esticamento, por causa invalidada e reentrada apos limpeza | historico do swing | R medio e queda maxima contra stop e tempo |
| G26 | ERP (earnings yield menos NTN-B) como teto do nucleo e calibrador do premio de G5 | multiplos.json, consenso, NTN-B | Prova viva |
| G27 | Mini-dolar de 10 pregoes no sentido do carrego so em regime calmo | WDO, PTAX, termometro | Dolar futuro diario e barras de 1 minuto |

**G16, G17 e G18 em detalhe:**

**G16. Benchmark nulo por modulo.** O teste longo mostrou que o excesso sobre o CDI era quase todo beta (S0: +4,6% ao ano sobre o CDI, alfa -0,8%, t -0,5). Regra: cada modulo e medido contra a carteira nula de MESMO beta (fundo de indice mais CDI, a ideia de Buffett para o nao profissional [S39]), nao contra o CDI. Alfa e t pelo NEFIN. Prova viva de no minimo 36 meses.

**G17. Tamanho por risco.** Alvo de volatilidade por modulo (nao por valor), com meio Kelly como TETO e nunca como alvo (o Sharpe fora da amostra e 0,72, entao quem manda e o limite de perda; `METODO.md` item 8). Limites ja vigentes no robo de day trade: perda do dia R$ 1.000, da semana R$ 2.000, queda maxima R$ 10.000 sobre R$ 100 mil. Extensao [MINHA]: o livro inteiro precisa de um orcamento de queda maxima proprio (secao 9).

**G18. A mao dinamica.** Gatilhos na secao 9; todos fixos antes e sem otimizar.

---

## 8. O que NAO vira regra: fica como visao da mesa

- **Filtro qualitativo** (governanca, honestidade e competencia da gestao, dono competente, cultura, vantagem competitiva): e a primeira etapa de Octavio e o centro de Buffett. So viram proxies fracos (G12, G13).
- **Projecao de dez anos** (receita, margem, capex) e valor terminal: e julgamento; a versao mecanica (G4) e sombra.
- **Tese quebrada** (erro qualitativo): Octavio tira o papel da lista para sempre; o robo so enxerga os numeros que ela deixa.
- **Eventos binarios** (eleicao de 25/10/2026, decisao fiscal, guerra): quanto de reducao antes do evento e visao do Douglas.
- **Macro do juro**: se a Selic chega a 11% a 11,5% (palavras de reportagem sobre Keleti) e leitura; G8 so mede a reacao.
- **Contrarian de verdade** (comprar quando todos rejeitam): depende de saber quem esta do outro lado.
- **Short especifico** (qual empresa, quando): fora do alcance do robo.
- **Ativismo e conselho**: nao existe com R$ 100 mil.
- **Kinea (adendo de 11/10/2026):** a narrativa do cenario e as probabilidades; a aritmetica fiscal e a leitura de rejeicao, abstencao e calendario politico depois de 25/10; o valor relativo entre mercados globais; o caminho da receita de IA (secao 5C).

---

## 9. O quadro do gestor multimercado: como as quatro escolas cabem num livro so

**Ressalva antes de tudo:** isto e desenho, nao resultado. O teste longo da carteira de acoes mostrou que o retorno veio de estar comprado em bolsa; nenhuma das camadas abaixo tem alfa provado neste projeto. Quem decide os orcamentos e o Douglas.

### 9.1 As camadas

| Camada | Funcao e escola | Instrumento | Orcamento de risco (proposta) |
|---|---|---|---|
| 0. Caixa em CDI | Base; paga uns 8% a 9% reais; e a posicao de espera (Buffett, Keleti) | CDI, LFT | Residuo (G15); sem orcamento de perda |
| 1. Nucleo | Carteira concentrada por premio sobre a NTN-B e qualidade (Octavio e Buffett) | 8 a 12 acoes | 60% do orcamento de queda do livro; queda historica de 23% a 35% por unidade de exposicao, e a camada que domina o risco |
| 2. Tatico | Inclinar tipo de empresa pelo juro, fluxo e cambio (Keleti) | Satelite de alavancadas/small, tilt em grandes | 15% do orcamento; desligavel (G8, G9, G11) |
| 3. Protecao | Seguro com custo conhecido (Keleti: hedge; Buffett: sono) | Venda de mini-indice acompanhando as acoes (`protecao.py`); opcoes de BOVA11 como seguro; capital protegido (CDI + 0,5% do capital por mes em call no dinheiro) | Nao consome orcamento de perda; tem custo anual declarado (limite de 2% a 3% do capital por ano, proposta) |
| 4. Estatistico | Sinais pequenos com aposentadoria automatica (Simons) | Reversao do dado americano no WDO (unica regra aprovada); outros em sombra | 10% do orcamento; lote por G2 |
| 5. Opcoes para especular | Convexidade comprada, perda conhecida (nao premio vendido) | Straddle onde a vol realizada de 252 dias supera a implicita; risco ate R$ 500 por estrutura | 5% do orcamento (teto de R$ 3 mil em risco, ja no modulo); reserva de 10% fica sem uso |

O que a pesquisa de opcoes do projeto diz (nao mudou): vender put, call coberta, trava de credito e pozinho nao pagaram o risco contra o CDI; a protecao com BOVA11 funciona como seguro mas custa de 7% a 15% da carteira por ano e nao e fonte de retorno; o capital protegido deu 10,9% ao ano contra CDI de 10,0%, pior mes -0,33% e pior ano +2,9% (Sharpe deflacionado 0,47, fraco); o straddle barato deu +20% por operacao (t 2,24, deflacionado 0,20, perde em metade dos meses). Fonte: `RESULTADO.md` e `RESULTADO_ASSIMETRIAS.md`.

### 9.2 A conta que precisa ser olhada de frente

O limite de queda maxima de R$ 10 mil (10%) vale para o day trade. Se o livro inteiro herdar esse numero, a conta da carteira diz o seguinte [MINHA, ordem de grandeza, nao e teste]:
- Sem protecao (S0), com 70% em acoes, a queda maxima foi 35,5%: cerca de 0,51 de queda por unidade de exposicao. Para cair no maximo 10%, a exposicao seria de uns 20% do capital.
- Com protecao fixa de 50% (S2), 23,3% com 70%: cerca de 0,33 por unidade. Para 10%, uns 30% do capital.
Ou seja, um limite de 10% e incompativel com um nucleo de acoes relevante. Decisao do Douglas: orcamento de queda maxima separado para o nucleo (por exemplo 20% a 25%) ou exposicao baixa.

**Conflito a resolver:** os percentuais da tabela 9.1 sao fatias de um orcamento de queda maxima do livro (D), que o Douglas ainda nao fixou. O day trade hoje tem o proprio limite de 10% do capital (R$ 10 mil). Se o livro tiver D = 20%, a fatia de 10% do estatistico e de 2% do capital (R$ 2 mil), e o limite de R$ 10 mil do day trade teria de cair para isso. Se D for 10%, o nucleo cabe em uns 6% do capital em perda, ou seja, uns 12% do capital em acoes sem protecao. Fixar D vem antes de qualquer lote.

### 9.3 Quando diminuir a mao (G18) [propostas minhas, fixar antes]

1. Queda do livro desde o pico em 50% do orcamento: tamanho do tatico e do estatistico cai pela metade; em 80%, zera e fica so o seguro (limites do robo no `risco_robo.json`).
2. Menos nomes aprovados em G5/G12: o nucleo diminui sozinho (G15); nunca baixar o premio exigido para ficar investido.
3. Modulo com decaimento (G2): lote a zero.
4. Volatilidade realizada de 20 dias do indice acima de duas vezes a de 252: tatico pela metade. Exposicao por volatilidade esta no lacre da carteira de acoes ("so com dado novo").
5. Evento binario em ate 5 pregoes: reduzir satelites e alavancadas; tamanho e visao do Douglas.

### 9.4 Quando aumentar

1. Mais nomes passando o portao de premio (G5) e queda maxima do nucleo abaixo de 50% do orcamento: Octavio aumenta quando cai; aqui so se o premio cruza o piso, nao pelo preco.
2. Modulo com 36 meses de prova viva e alfa t acima de 2 contra o benchmark de mesmo beta (G16): lote sobe um degrau por vez.
3. Opcoes: seguro mais barato nao e sinal confiavel (proteger BOVA11 so com vol implicita baixa foi reprovado: nao teria protegido marco de 2020).

---

## 10. O que nao consegui confirmar

- **Como a Guepardo monta a TIR:** valor terminal, taxa de desconto, tipo de fluxo, trajetoria de IPCA, premio minimo exigido. Nada em fonte publica que li (secao 3.3).
- **Que Octavio use a expressao "TIR real implicita":** as falas publicas usam IPCA mais X%, yield e preco justo.
- **Ativismo atual de Octavio** e uso de derivativos pela Guepardo.
- **Stock Pickers #142 (Octavio), Market Makers #115 e #70, Skin in the Game #47, Os Economistas:** li so a pagina de descricao; nao ouvi nem li transcricao. Pode haver detalhe de processo nesses audios.
- **Alpha Key:** o instrumento do hedge (acao alugada, futuro ou opcao); numero de acoes e exposicao liquida alvo; stops e dimensionamento alem do Formulario de 2020 e do artigo de jan/2025.
- **Simons:** custo de transacao e limpeza de dado; numero de sinais; horizonte medio (so relatos de leitor); alavancagem e Kelly (so fonte secundaria). Li resumos do livro de Zuckerman, nao o livro. A palestra de Simons no MIT (2010) nao tem transcricao acessivel.
- **Buffett:** resultado final das puts de indice (so ate 2017, por relato); fonte primaria das puts de Coca-Cola de 1993 (abri so relatos).
- **Kinea (adendo de 11/10/2026):** o que Marco Freire e Ruy Alves disseram nas lives (legendas do YouTube nao coletadas); a apresentacao da live de 02/10/2026; a data exata da carta de setembro de 2026; a atribuicao de cada frase das cartas a um dos dois; a probabilidade de cada cenario da carta de marco/2026; o metodo da TIR real implicita da Kinea; orcamento de risco e limites dos multimercados (secao 5C).
- **Retorno do Medallion:** o numero bruto e contestado (secao 2.2).
- **Selic de 13,75% e juro real ex-ante:** fontes agregadoras; conferir no BCB. NTN-B de hoje: nao busquei a taxa.
- **Fluxo estrangeiro diario da B3 e segmento de listagem no projeto:** nao verifiquei se ha dado.
- **Evidencia brasileira publicada** de qualidade, tendencia em macro e fluxo: nao busquei.

---

## 11. Fontes

Dados do projeto: `quant/estudos/LEIA.md`, `quant/README.md`, `quant/pesquisa/METODO.md`, `quant/pesquisa/FILA.md`, `quant/saida/pesquisa_carteira/RESULTADO_HOLDOUT.md`, `quant/saida/pesquisa5/opcoes/RESULTADO.md` e `RESULTADO_ASSIMETRIAS.md`, `quant/sinais.py`. O estudo de eleicoes de 01/10/2026 vem de relatorio do proprio Douglas.

**Simons**
- [S1] Bloomberg/Fortune, obituario, 10/05/2024: https://fortune.com/2024/05/10/jim-simons-obituary-renaissance-technologies-quant-king
- [S2] Institutional Investor, 13/01/2021 (Medallion, RIEF, RIDA): https://www.institutionalinvestor.com/article/2bswms7wco7as686o8ikg/portfolio/renaissances-medallion-fund-surged-76-in-2020-but-funds-open-to-outsiders-tanked
- [S3] Institutional Investor, jan/2020 (artigo de B. Cornell, "Medallion Fund: The Ultimate Counterexample?", dez/2019): https://www.institutionalinvestor.com/index.php/article/2bswymr8cih3jeaslxc00/portfolio/famed-medallion-fund-stretches-explanation-to-the-limit-professor-claims
- [S4] Guo e Liu, arXiv 2405.10917, 17/05/2024 (v2 10/11/2024): https://arxiv.org/abs/2405.10917
- [S5] A Wealth of Common Sense (Ben Carlson), resumo do livro de Zuckerman: https://awealthofcommonsense.com/?p=28151
- [S6] Quartr, Renaissance e Medallion (secundario): https://quartr.com/insights/company-research/renaissance-technologies-and-the-medallion-fund
- [S7] Marcellus (secundario): https://marcellus.in/story/why-the-medallion-fund-is-the-greatest-money-making-machine-of-all-time/
- [S8] Livro: G. Zuckerman, The Man Who Solved the Market (Portfolio/Penguin, 2019) - nao lido, so por resumos.

**Octavio Magalhaes / Guepardo**
- [S9] InfoMoney, 23/07/2026 (Expert XP): https://www.infomoney.com.br/onde-investir/prefiro-ganhar-ipca-15-em-acoes-ao-tesouro-ipca-diz-magalhaes-da-guepardo/
- [S10] Seu Dinheiro, 23/07/2026: https://www.seudinheiro.com/2026/bolsa-dolar/ipca-8-e-pouco-gestores-revelam-qual-outro-investimento-pode-render-ipca-14-e-quase-ninguem-esta-percebendo-bdap/
- [S11] Money Times, 04/07/2024: https://www.moneytimes.com.br/se-bater-preco-alvo-frita-e-se-tiver-barato-compra-as-licoes-de-gestor-que-bate-ibovespa-no-ano-rnda/
- [S12] NeoFeed, 04/07/2024: https://neofeed.com.br/wealth-management/os-segredos-por-tras-do-salto-de-oito-vezes-da-guepardo-sobre-o-ibovespa/
- [S13] Empiricus/Market Makers (Stock Picking Day), 08/07/2024: https://www.empiricus.com.br/artigos/investimentos/eu-nunca-migro-para-a-renda-fixa-diz-octavio-magalhaes-da-guepardo-veja-as-3-principais-acoes-do-fundo-lbrd5mp018/
- [S14] Seu Dinheiro, 05/07/2024: https://www.seudinheiro.com/2024/select/stock-picking-day-octavio-magalhaes-revela-as-tres-principais-apostas-da-guepardo-na-bolsa-lbrd5mp018/
- [S15] Bora Investir (B3), 08/09/2023: https://borainvestir.b3.com.br/objetivos-financeiros/investir-melhor/girar-rapido-em-fundos-prejudica-o-bolso-diz-octavio-magalhaes-da-guepardo/
- [S16] InfoMoney, 23/10/2022: https://www.infomoney.com.br/?p=1962522
- [S17] Guepardo, Carta aos Investidores n. 105 (1T23): https://www.guepardoinvest.com.br/wp-content/uploads/Carta_105_-_Carta_aos_Investidores_(1T23).pdf
- [S18] Site da Guepardo, consultado em 10/10/2026 (dados ate 08/10/2026): https://www.guepardoinvest.com.br/
- [S19] Curioso Mercado, 05/11/2025 (trecho de "Fora da Nova Curva"): https://curiosomercado.substack.com/p/octavio-magalhaes-so-comprar-barato
- [S20] NeoFeed, 08/05/2025: https://neofeed.com.br/videos/cafe-investidor/por-que-a-guepardo-esta-comprada-em-ultra-klabin-e-allos
- [S21] InfoMoney, 12/05/2026 (carta trimestral): https://www.infomoney.com.br/?p=3326756
- [S22] Nord, Skin in the Game #47, 28/11/2023 (so a descricao): https://www.nordinvestimentos.com.br/blog/videos/as-estrategias-do-fundo-que-rende-22-ao-ano-desde-2001-skin-in-the-game-47-com-octavio-magalhaes/
- [S49] Capital Aberto, jul/2012 (Bematech e conselhos; so o resumo de busca): https://capitalaberto.com.br/empresas/2012/07/ajeitando-a-casa

**Christian Keleti / Alpha Key**
- [S23] Formulario de Referencia da Alpha Key (base 31/12/2020): https://alphakey.com.br/wp-content/uploads/2021/08/Formulario-de-Referencia-Alpha-Key-31_12_2020-vf.pdf
- [S24] Suricato Investidor, 09/01/2025 (artigo escrito por Keleti): https://suricatoinvestidoridor.substack.com/p/o-portfolio-da-travessia
- [S25] Exame, 18/11/2024: https://exame.com/invest/mercados/essa-small-cap-nao-vale-nada-e-pode-triplicar-de-preco-na-bolsa-diz-christian-keleti/
- [S26] NeoFeed, 12/12/2024 (Cafe com Investidor): https://neofeed.com.br/videos/cafe-investidor/o-kit-brasil-2-0-da-alphakey-para-enfrentar-os-solavancos-da-bolsa-brasileira/
- [S27] The Investor, 06/01/2025: https://theinvestor.com.br/mercados/2025/01/06/quando-o-mercado-virar-vai-faltar-acao-diz-gestor-da-alpha-key/
- [S28] Bloomberg Linea, 28/01/2026: https://www.bloomberglinea.com.br/2026/01/28/dont-fight-the-flow-ceo-da-alpha-key-ve-desafio-de-valuation-com-rali-na-bolsa/
- [S29] Seu Dinheiro, 18/03/2026: https://www.seudinheiro.com/2026/bolsa-dolar/o-rali-mais-odiado-e-a-escassez-de-acoes-o-que-esperar-do-ibovespa-mlim/
- [S30] Seu Dinheiro, 18/08/2026: https://www.seudinheiro.com/2026/bolsa-dolar/nao-e-agora-gestor-da-alphakey-manda-recado-sobre-magazine-luiza-mglu3-e-revela-o-que-procura-na-bolsa-miql/
- [S31] InfoMoney (Stock Pickers), 10/10/2026: https://infomoney.com.br/mercados/queda-da-selic-e-preco-atrativo-das-acoes-criam-momento-raro-na-bolsa-diz-gestor
- [S32] Market Makers #70, 10/11/2023 (so a descricao): https://mmakers.com.br/podcast/de-trader-a-gestor-a-inspiradora-jornada-de-christian-keleti-ceo-da-alpha-key/
- [S33] Site da Alpha Key, fundo Long Biased, consultado em 10/10/2026: https://alphakey.com.br/fundos/alpha-key-lb-i-fic-fim/

**Buffett**
- [S34] Carta aos acionistas de 2008: https://www.berkshirehathaway.com/letters/2008ltr.pdf
- [S35] Carta de 1992: https://www.berkshirehathaway.com/letters/1992.html
- [S36] Carta de 1989: https://www.berkshirehathaway.com/letters/1989.html
- [S37] Carta de 1996: https://www.berkshirehathaway.com/letters/1996.html
- [S38] Carta de 1986 (lucro do dono): https://www.berkshirehathaway.com/letters/1986.html
- [S39] Carta de 2013: https://www.berkshirehathaway.com/letters/2013ltr.pdf
- [S40] Puts de Coca-Cola (1993): relatos secundarios, ex.: https://www.nasdaq.com/articles/how-buffett-used-this-simple-strategy-to-boost-returns-2019-11-06 (nao consegui abrir; o resumo de busca cita a reuniao de 1994)
- [S41] Business Standard/Bloomberg, 09/07/2018 (puts de indice): https://www.business-standard.com/amp/article/international/warren-buffett-starts-to-say-goodbye-to-a-pile-of-equity-index-options-118070900604_1.html (so o resumo de busca)
- [S42] Fortune, 26/02/2011 (Buffett e as puts): https://fortune.com/2011/02/26/buffett-cleans-up-on-derivatives-bet (so o resumo de busca)

**Brasil**
- [S43] InvestNews, 08/10/2026 (concentracao do Ibovespa): https://investnews.com.br/investimentos/concentracao-ibovespa-riscos/
- [S44] Tribuna do Sertao, 03/08/2026 (1a previa do Ibovespa set-dez/2026): https://tribunadosertao.com.br/geral/2026/08/03/951999-b3-divulga-1a-previa-do-ibovespa-com-novos-ativos
- [S45] Copom de 16/09/2026 (agregadores): https://atlaspublico.com.br/bcb/noticias/copom-reduz-selic-para-13-75pct-ao-ano-em-decisao-unanime-87748 e https://economicnewsbrasil.com.br/2026/09/16/nova-taxa-selic-projecao-dezembro-2026/
- [S46] Lei 15.270/2025: https://jornalcontabil.com.br/noticia/lei-15-270-define-regras-para-taxacao-de-lucros-e-dividendos-a-partir-de-2026/ e https://renovainvest.com.br/blog/tributacao-de-dividendos/
- [S47] IR em acoes e opcoes: https://www.nordinvestimentos.com.br/blog/imposto-renda-venda-de-acoes/
- [S48] Aluguel: InfoMoney, 09/02/2026 (monitor de short selling da XP): https://www.infomoney.com.br/?p=3205540 / Forbes Brasil, 2022: https://forbes.com.br/forbes-money/2022/03/aluguel-de-acoes-entenda-o-que-e-e-como-funciona/ / Renova Invest: https://renovainvest.com.br/?p=14130

**Kinea, Marco Freire e Ruy Alves (adendo de 11/10/2026)**
- [S50] Kinea, Carta do Gestor Chronos Geral Sub I, setembro/2026 (publicada em outubro/2026): https://www.kinea.com.br/wp-content/uploads/2026/10/Carta-do-Gestor-Chronos-Geral-Sub-I-2026-09.pdf
- [S51] Kinea, Carta do Gestor Chronos Geral Sub I, agosto/2026: https://www.kinea.com.br/wp-content/uploads/2026/09/Carta-do-Gestor-Chronos-Geral-Sub-I-2026-08.pdf
- [S52] Kinea, Carta do Gestor Atlas II Itau Sub III, marco/2026: https://www.kinea.com.br/wp-content/uploads/2026/04/Carta-do-Gestor-Atlas-II-Itau-Sub-III-2026-03.pdf
- [S53] Kinea, Carta do Gestor Atlas II Itau Sub III, maio/2026: https://www.kinea.com.br/wp-content/uploads/2026/06/Carta-do-Gestor-Atlas-II-Itau-Sub-III-2026-05.pdf
- [S54] Kinea, Carta do Gestor Atlas II Itau Sub III, janeiro/2026: https://www.kinea.com.br/wp-content/uploads/2026/02/Carta-do-Gestor-Atlas-II-Itau-Sub-III-2026-01.pdf
- [S55] Kinea, Apresentacao da Live Mensal, 03/09/2026: https://www.kinea.com.br/wp-content/uploads/2026/09/Apresentacao-Live-Mensal.pdf
- [S56] Kinea Insights, "O Guia do Mochileiro das Galaxias", 16/09/2026: https://www.kinea.com.br/wp-content/uploads/2026/09/Kinea-Insights_O-Guia-do-Mochileiro-das-Galaxias.pdf
- [S57] Kinea, Apresentacao da Live Mensal, 05/03/2026: https://www.kinea.com.br/wp-content/uploads/2026/03/Apresentacao-Live-Mensal.pdf
- [S58] InfoMoney, 03/12/2025 (apresentacao do evento com Ruy Alves; sem falas dele): https://www.infomoney.com.br/onde-investir/ruy-alves-da-kinea-desvenda-os-caminhos-do-ouro-e-do-dolar-no-onde-investir-2026/
- [S59] Kinea, Cartas do Gestor Atlas e Apolo, setembro/2026 (mesmo texto da Chronos; fichas de volatilidade): https://www.kinea.com.br/wp-content/uploads/2026/10/Carta-do-Gestor-Atlas-Geral-Sub-I-2026-09.pdf e https://www.kinea.com.br/wp-content/uploads/2026/10/Carta-do-Gestor-Apolo-Geral-Sub-I-2026-09.pdf
- [S60] Kinea, Cartas do Gestor Atlas II Itau Sub III de fevereiro, abril e junho/2026: https://www.kinea.com.br/wp-content/uploads/2026/03/Carta-do-Gestor-Atlas-II-Itau-Sub-III-2026-02.pdf , https://www.kinea.com.br/wp-content/uploads/2026/05/Carta-do-Gestor-Atlas-II-Itau-Sub-III-2026-04.pdf e https://www.kinea.com.br/wp-content/uploads/2026/07/Carta-do-Gestor-Atlas-II-Itau-Sub-III-2026-06.pdf
- [S61] Kinea, equipe (ingles), consultado em 11/10/2026: https://www.kinea.com.br/en/our-team/
- [S62] Kinea, Quem somos, consultado em 11/10/2026: https://www.kinea.com.br/somos/
- [S63] Kinea, Apresentacao Live Prev PJ, 24/09/2026 (p. 14 e 17: CIO e lider da gestao): https://www.kinea.com.br/wp-content/uploads/2026/09/Live-Prev-PJ.pdf
- [S64] Kinea, Multimercados, consultado em 11/10/2026: https://www.kinea.com.br/multimercados/
- [S65] Kinea, lista de documentos e cartas coletada pelo `mesa.py kinea` (branch `dados`, pasta kinea/, coleta de 06/10/2026)
- [S66] InfoMoney, 17/04/2022 (Marco Freire e Ruy Alves): https://www.infomoney.com.br/onde-investir/comprados-em-ativos-reais-e-mercados-emergentes-conheca-a-estrategia-e-as-principais-apostas-da-kinea/
- [S67] Seu Dinheiro, 23/08/2021 (Marco Freire): https://www.seudinheiro.com/2021/bolsa-dolar/bolsa-dolar-juros-kinea-entrevista-marco-freire/
- [S68] Brazil Journal, 28/04/2023 (Marco Freire): https://braziljournal.com/play/kinea-juro-e-pesca-com-dinamite-e-novas-baleias-devem-boiar/
- [S69] Seu Dinheiro, 25/02/2026 (Marco Freire, BTG Summit): https://www.seudinheiro.com/2026/economia/nem-bolha-nem-catastrofe-para-os-empregos-gestor-da-kinea-explica-o-que-o-mercado-ainda-nao-entendeu-sobre-a-inteligencia-artificial-lvgb/
- [S70] Seu Dinheiro, 19/05/2023 (Ruy Alves, Market Makers #45): https://www.seudinheiro.com/2023/economia/economia-da-china-em-apuros-ruy-alves-kinea-miql/
- [S71] InfoMoney, 01/09/2023 (Ruy Alves): https://www.infomoney.com.br/onde-investir/brasil-nao-tem-ativos-suficientes-para-uma-carteira-eficiente-diz-ruy-alves-da-kinea/
- [S72] Brazil Journal, 17/12/2024 (Ruy Alves): https://braziljournal.com/para-a-kinea-so-da-para-ficar-comprado-nos-eua/
- [S73] InfoMoney, 12/12/2025 (Ruy Alves, Stock Pickers): https://www.infomoney.com.br/advisor/kinea-ve-eleicoes-e-cenario-global-como-motores-das-oportunidades-para-2026/
- [S74] InfoMoney, 01/12/2025 (resumo da carta da Kinea, sem assinatura por pessoa): https://www.infomoney.com.br/?p=3124544
- Terminal do Douglas (11/10/2026): `~/Desktop/terminal-artefato/cache/out/` (`macro.json`, `rf.json`, `b3.json`, `hist/`, `pagina/wirp.json`, `consenso_estado.json`).

Material de estudo. Nao e recomendacao de investimento nos termos da CVM e nao promete resultado. Dado de mercado deve ser conferido na fonte oficial antes de qualquer decisao.
