---
name: deep-search
description: Investigacao a fundo de UMA pergunta sobre um ativo, ate a resposta ter numero, fonte e data. Dispara quando o Douglas pergunta por que, como, de onde vem, o que precisa acontecer, ou desconfia de um numero: "por que a margem caiu", "quais os gatilhos para melhorar a margem EBIT", "se eles nao tem guidance por que eu compraria", "isso e sustentavel", "de onde vem esse lucro", "o que o preco exige", "eles entregaram o que prometeram", "a divida preocupa". Sete passos obrigatorios: fixa a pergunta, inventaria o dado, decompoe a DRE linha a linha, varre os 8 releases atras do discurso da gestao, faz a conta reversa do preco, testa contra os pares e fecha com veredito e o que mudaria de ideia. Nao recomenda; investiga e apresenta.
---

# Deep search (investigacao da mesa)

A skill `analise-ativo` responde "o que e este ativo". Esta responde **uma
pergunta so, ate o fundo**. A diferenca de postura: a nota cobre o ativo em
largura; o deep search escolhe uma duvida e nao larga enquanto ela nao tiver
numero oficial, data e a frase da gestao ao lado.

Quem le: o Douglas, no celular, entre um cliente e outro. Vale a secao 6 da
skill `analise-ativo` (texto para celular e termos) sem excecao: "Em uma
frase" na abertura, tabela de ate 4 colunas, sigla explicada em portugues na
primeira vez, "Termos desta nota" no fim, menu "Quer aprofundar?".

Regra que nao se negocia: **nenhuma frase de conclusao sem um numero oficial
por tras**. Se a resposta depender de um dado que nao existe no branch
`dados`, a lacuna e declarada e vira a primeira linha do veredito.

## Passo 0. Fixe a pergunta antes de abrir qualquer dado

Reescreva o pedido do Douglas como uma pergunta falseavel, com metrica,
periodo e o que contaria como resposta "sim" e como "nao". Sem isso a
investigacao vira passeio.

| Ele pergunta                          | Pergunta fixada                                                                 |
|---------------------------------------|---------------------------------------------------------------------------------|
| "por que a margem caiu"               | Qual linha da DRE, em % da receita, explica a queda da margem EBIT entre X e Y?  |
| "quais os gatilhos para melhorar"     | Que linha teria de ceder, em quantos pp, e a gestao tem plano com data para ela? |
| "se nao tem guidance, por que comprar"| Que lucro/margem/crescimento o preco de hoje exige, e a empresa ja entregou isso?|
| "isso e sustentavel"                  | O resultado vem de linha recorrente ou de item que apareceu 1 a 2 vezes em 8T?   |
| "a divida preocupa"                   | Quanto do EBIT o juro consome, a que custo, com que vencimento e contra o CDI?   |
| "eles entregaram o que prometeram"    | O que a gestao prometeu em 4 releases atras, com numero, e o que saiu?           |

Escreva a pergunta fixada na primeira linha do rascunho. Ela e o criterio de
"pronto": a investigacao acaba quando ela esta respondida, nao antes.

## Passo 1. Inventario: o que existe, o que falta

```bash
python3 mesa.py skills       # as skills da mesa estao instaladas e validas?
python3 mesa.py ficha TICKER
python3 mesa.py frescor TICKER    # TRAVA 1, a ponta: o trimestre mais novo e o de hoje?
python3 mesa.py cobertura TICKER  # TRAVA 2, o corpo: os 8 da janela estao la, um a um?
```

A resposta abre confirmando o que operou: quais skills e quais comandos. O
Douglas pediu essa confirmacao em toda pesquisa.

A ficha diz em uma tela se ha demonstracao oficial, quantos releases estao
guardados, qual o grupo de pares e quais fontes falharam.

### As duas travas (obrigatorias, logo depois da ficha)

Sao duas perguntas diferentes e nenhuma cobre a outra. **Frescor olha a
ponta**: o release mais novo esta no trimestre que o ITR e o calendario ja
cobram? **Cobertura olha o corpo**: os 8 trimestres da janela estao no branch,
um a um, com texto que serve de fonte? Indice com oito linhas passa no frescor
e reprova na cobertura quando duas delas sao de trimestres velhos ou estao
ocupadas por documento que nao e release. Foi assim que o deep search da DIRR3
saiu sem 1T26 e sem 4T25: a trava olhava so a ponta.

`python3 mesa.py cobertura TICKER` monta a janela pelo mesmo calendario do
frescor (o trimestre vencido e os 7 anteriores), confere cada um contra
`releases/<TICKER>/index.json` e fecha com `VEREDITO: COMPLETA` (saida 0) ou
`COBERTURA 6/8, faltam 1T26, 4T25` (saida 1). Trimestre `CURTO` e o que tem
arquivo abaixo de 4 mil caracteres, ou documento que nao e release de
resultado (aviso de assembleia, dividendo, recompra): conta como lacuna, nao
como dado. **Deep search quer dizer a janela inteira.** Sem saida 0, dispare a
coleta, espere e repita ANTES de escrever qualquer numero.

Antes de comparar contra os pares (Passo 5), rode
`python3 mesa.py cobertura TICKER --pares`: mediana de grupo com par furado e
mediana errada.

### Trava de frescor (o detalhe da ponta)

`python3 mesa.py frescor TICKER` e o criterio, nao a intuicao. Ele imprime o
trimestre do ITR mais novo, o trimestre do release mais novo, a defasagem
entre os dois e a idade da coleta, e fecha com um VEREDITO: `ATUAL` (saida 0)
ou `RELEASE VELHO (N trimestres atras do ITR)` / `COLETA VELHA (Nh)` (saida
1). Release mais novo que o ITR e normal logo apos a divulgacao e conta como
ATUAL.

- `RELEASE VELHO` ou `COLETA VELHA`: dispare a coleta (abaixo; o coletor
  agora busca o release tambem no site de RI da companhia, `ri_fontes.py`,
  quando a CVM nao tem o trimestre do ITR), espere o run terminar e repita
  `python3 mesa.py frescor TICKER`. Com ATUAL, siga ao passo 2; se continuar
  RELEASE VELHO, siga ao passo 2 com as regras (a)-(e) abaixo.
- Se depois da coleta continuar `RELEASE VELHO`:
  (a) a resposta ABRE com a lacuna em uma frase, com o trimestre do ITR e o
      do release lado a lado ("Numeros oficiais ate o 2T26; ultimo release
      lido e do 3T25, tres trimestres atras"), antes do "Em uma frase";
  (b) tudo que vier de release carrega o trimestre entre parenteses:
      "margem bruta de 36,1% (release 3T25)";
  (c) o passo 3 (discurso contra entrega) declara que a fala da gestao esta
      N trimestres atras dos numeros e cobra o que der com essa ressalva;
  (d) a mesa procura o release do trimestre que falta pelo buscador web
      (WebSearch: "<empresa> resultado 2T26 release") para ao menos citar
      manchete, data e os numeros divulgados, sempre marcados como "busca
      web, nao e fonte primaria";
  (e) nunca apresentar KPI de release velho como se fosse do trimestre
      atual: sem o trimestre ao lado, o numero nao entra.

**Dado velho nao e motivo para nao responder; e motivo para dizer a idade do
dado na primeira linha.**

Tres avisos do `frescor` mudam o que fazer ANTES de disparar a coleta:

- `AVISO: site de RI: NAO MAPEADO em ri_fontes.py`: com a CVM sem o indice do
  ano, a coleta nao vai achar release novo. Ache a central de resultados da
  companhia pelo buscador (WebSearch: "<empresa> RI central de resultados"),
  inclua a entrada em `ri_fontes.py` (esquema no proprio arquivo; `mz_id` so
  quando visto em URL real de documento), commite e leve a `main`, e so entao
  dispare. `python3 mesa.py skills` valida o mapa.
- `RELEASE VELHO (calendario: ...)` ou `ITR VELHO (calendario: ...)`: o prazo
  legal do trimestre venceu (45 dias no 1T a 3T, 90 no 4T) e nem o ITR nem o
  release chegaram. E a mesma classe de falha do IPE: a fonte de referencia
  sumiu. Dispare a coleta; se continuar, a lacuna vai para a primeira frase.
- `RELEASE ADIANTADO`: release dois ou mais trimestres a frente do ITR e
  trimestre suspeito; abra o release e confira o cabecalho antes de usar.

Todo leitor (`ficha`, `serie`, `releases`, `release`, `linha`, `decompor`)
imprime o veredito de frescor na primeira linha: nao ha como pular a trava.

Dispare a coleta tambem quando a ficha imprimir "nao esta no branch" ou
"demonstracao oficial: AUSENTE", e sempre que `cobertura` nao devolver saida 0
(o `frescor` ja cobre `gerado_em` velho). O coletor vai atras do trimestre que
falta mesmo quando ele e mais antigo que o release mais novo. Ferramenta `mcp__github__actions_run_trigger`,
`method: run_workflow`, `owner: douglora`, `repo: broadcast`,
`workflow_id: coletar-dados.yml`, `ref: main`,
`inputs: {"tickers": "TICKER", "pares": "auto"}`. Leva de 3 a 8 minutos;
espere com `python3 -c "import time; time.sleep(45)"` (o comando `sleep` e
bloqueado aqui) e confirme por `mcp__github__actions_list`. O detalhe completo
de espera e cache do CDN esta na secao 2b da skill `analise-ativo`.

Uma pergunta sobre trajetoria (margem, custo, entrega) exige a janela
inteira: 8 trimestres de release e 8 de demonstracao oficial. Abaixo disso a
investigacao continua, mas a primeira linha diz quantos dos 8 foram lidos e
quais faltam, pelo nome do trimestre.

## Passo 2. Decomponha a DRE: ache a linha que se mexeu

```bash
python3 mesa.py decompor TICKER
```

Imprime cada conta de resultado como % da receita, trimestre a trimestre, e
ordena as linhas pela variacao em pontos percentuais entre a ponta antiga e a
nova. **A linha do topo dessa lista e a resposta mecanica da pergunta "por que
a margem mudou".** Narrativa nenhuma sobrevive a essa tabela.

Como ler:

- Custo subindo em % da receita e problema de preco, mix ou insumo. Despesa
  operacional caindo em % da receita e alavancagem operacional funcionando.
- Linha que sobe e desce em trimestres alternados e sazonalidade ou item nao
  recorrente, nao tendencia: confira a coluna `D` (trimestre derivado do
  anual) antes de chamar de virada.
- Em banco (`plano_de_contas: instituicao_financeira`) a base e a receita da
  intermediacao financeira, nao existe EBIT. A linha "despesas da
  intermediacao" e o custo de captacao: e ela que o CDI move.
- Cruze com `python3 mesa.py serie TICKER` (12 trimestres em valor absoluto)
  quando a duvida for de escala, nao de margem.

Balanco e caixa entram aqui quando a pergunta e de divida ou de conversao:
`serie` traz caixa operacional, divida e patrimonio; a secao 4.2 e 4.3 da
skill `analise-ativo` tem as contas prontas.

## Passo 3. Interrogue os 8 releases: discurso contra entrega

```bash
python3 mesa.py linha TICKER "meta|guidance|ROE de|margem|plano"
```

Busca o mesmo termo nos 8 releases guardados, do mais antigo ao mais novo, e
imprime o que a gestao disse em cada trimestre. **A leitura esta tanto no que
aparece quanto no que some.** Quatro achados valem manchete:

1. **Promessa com numero e data** que nao foi cumprida no prazo, ou cujo ritmo
   nao fecha com o prazo (calcule: % da meta atingido contra % do prazo
   decorrido).
2. **Meta datada trocada por meta sem data.** E rebaixamento de compromisso,
   mesmo quando a empresa apresenta como evolucao.
3. **Troca de metrica ou de definicao de "ajustado"** justo depois de a
   metrica antiga piorar.
4. **"Extraordinario" que aparece em 4 dos 8 trimestres**: e recorrente.

Depois de achar o termo, abra o release inteiro do trimestre que interessa
(`python3 mesa.py release TICKER 2T26`) para ler a frase no contexto e citar
com trimestre e data. Nunca cite uma frase so pelo trecho do grep.

Se nenhum release fala do assunto, isso e um achado, nao um vazio: "a gestao
nunca tratou disso em 8 trimestres" responde a pergunta. **So vale com a
cobertura COMPLETA.** Com trimestre faltando, a frase vira "nao fala disso nos
6 trimestres lidos; 1T26 e 4T25 nao estao no branch": ausencia em janela
furada nao e silencio da gestao, e falha de coleta, e as duas conclusoes sao
opostas.

## Passo 4. Conta reversa: o que o preco de hoje exige

O passo que transforma investigacao em decisao. Em vez de projetar o que a
empresa vai fazer, inverta: **que resultado o preco ja esta cobrando?** Sempre
com os insumos declarados linha a linha.

**Empresa operacional.** Do `mesa.py ficha`: valor de mercado e lucro LTM
(ultimos 12 meses) oficial. Escolha um multiplo de saida defensavel (mediana
de P/L do grupo, do `mesa.py pares`) e um horizonte (3 ou 5 anos). Entao:

```
lucro exigido no ano N = valor de mercado de hoje / multiplo de saida
crescimento de lucro exigido = (lucro exigido / lucro LTM) ** (1/N) - 1
```

Desdobre em receita e margem: com a margem de hoje, que crescimento de receita
fecha a conta? Com o crescimento de receita de hoje, que margem fecha? As duas
respostas juntas dizem se o preco pede o que a empresa ja faz ou algo que ela
nunca fez. Compare o crescimento exigido com o realizado nos 8 trimestres do
passo 2.

**Banco ou financeira.** O preco esta em P/VP (preco sobre patrimonio):

```
P/VP justo = (ROE - g) / (Ke - g)
ROE exigido pelo preco = P/VP negociado * (Ke - g) + g
```

`Ke` (custo do capital proprio, o retorno que o acionista exige) monte assim,
declarando cada parcela: juro real longo da NTN-B (`snapshot/tesouro.json`)
+ IPCA de 12 meses (bloco `macro`) + premio de risco de acoes de 5 pp. `g` e
o crescimento nominal perpetuo: use IPCA + 2 a 3 pp e diga qual usou. Compare
o ROE exigido com o ROE entregue no ultimo trimestre e com a meta da gestao
achada no passo 3. **Em banco, a primeira comparacao e sempre ROE contra o
CDI**: retorno de acao proximo do CDI e risco de acao com retorno de renda
fixa.

Sensibilidade obrigatoria: refaca a conta com Ke 2 pp acima e 2 pp abaixo, e
diga em uma linha quanto a conclusao muda. Conta reversa com um numero so e
falsa precisao.

## Passo 5. Controle: e a empresa ou e o setor?

```bash
python3 mesa.py pares TICKER
```

A mesma metrica que se mexeu no passo 2, na mesma janela, nos pares do grupo.
Sem esse passo nao da para saber se o achado e da empresa ou do ambiente.

- Metrica piorou no ativo e na mediana do grupo: e macro ou setor. O que
  importa passa a ser quem perdeu menos.
- Piorou so no ativo: e execucao ou modelo. Aqui mora a manchete.
- Melhorou so no ativo: ou e vantagem real, ou e contabilidade diferente.
  Confira o plano de contas e a moeda antes de comemorar.
- Grupo `financeiro`: P/L, P/VP, ROE, DY e lucro oficial. Grupo
  `operacional`: EV/EBITDA, margens LTM oficiais, crescimento de receita,
  divida liquida/EBITDA, resultado financeiro sobre EBIT.
- Par com prejuizo tem P/L sem sentido; par em recuperacao judicial entra
  como referencia do que acontece quando a tese quebra, nao como comparavel.
- Olhe o `gerado_em` de cada linha: par com dado mais velho que o ativo vira
  ressalva escrita, nao numero silencioso.

## Passo 6. Veredito e o que mudaria de ideia

Fecha com quatro blocos, nesta ordem, e nada mais:

1. **A resposta**, em uma frase, com o numero principal e a data.
2. **Como se chegou nela**: a linha da DRE que se mexeu, a frase da gestao e
   a conta reversa. Tres a cinco frases, uma evidencia cada.
3. **O que mudaria de ideia**: o dado especifico, com o numero-limite e o
   trimestre em que ele aparece ("se a despesa de captacao voltar abaixo de
   45% da receita no 3T26, a leitura muda"). Sem isso a investigacao nao e
   falseavel.
4. **O que vigiar, com data**: proximo resultado, fato relevante esperado,
   vencimento de divida, reuniao do Copom.

Nunca escreva "compre" ou "venda". A recomendacao e a responsabilidade
regulatoria sao do Douglas (Resolucao CVM 178). O deep search apresenta a
evidencia e o veredito analitico; a decisao e dele.

## Forma da resposta

Vale a secao 6 da skill `analise-ativo`, resumida aqui porque quase toda
resposta desta skill e lida no celular:

- Abra com **Em uma frase:** e a resposta inteira em ate 30 palavras.
- 400 a 700 palavras. Deep search e mais fundo, nao mais longo.
- Tabela com no maximo 4 colunas. Serie de 8 trimestres vai em duas colunas
  ou em prosa ("de 57,6% no 3T24 para 53,0% no 2T26, caindo em cinco dos oito").
- Um numero por frase, com fonte e data. Negrito so no achado e no risco.
- Data de release marcada `(estimada)` pelo `mesa.py` (campo `data_estimada`
  no JSON; `release_data_estimada` no bloco frescor) e inferencia do coletor
  (fim do trimestre + 40 dias), nao data de divulgacao: nunca entra na
  resposta como data; cite so o trimestre ("release do 2T26").
- Toda sigla explicada em portugues na primeira vez, em ate 12 palavras
  (`python3 mesa.py termos ROE NIM` imprime a linha pronta de GLOSSARIO.md).
- Feche com **Termos desta nota** e **Quer aprofundar?** com 3 a 5 opcoes,
  cada uma um tema que renda uma investigacao propria.
- Uma linha no fim: "Analise para uso interno do assessor; nao constitui
  recomendacao de investimento."

## Como nao se enganar

- **Licao de 20/09/2026: o frescor e verificado por comando, nao suposto.**
  A CVM sumiu com o indice IPE de 2026 (HTTP 404), o coletor so achava
  release por esse indice, e a mesa entregou nota de DIRR3 com release do
  3T25 contra ITR do 2T26, tres trimestres atras, sem dizer isso na primeira
  linha; o Douglas apontou. Desde entao `mesa.py frescor` roda antes de
  qualquer texto e a defasagem, quando existe, abre a resposta.
- **Nao confunda a conta da empresa com a da gestao.** O release apresenta
  "ajustado"; a DRE oficial nao ajusta nada. Quando divergem, a oficial e o
  numero e a diferenca e o assunto.
- **Numero de agregador nunca responde pergunta de deep search.** Yahoo e
  Fundamentus servem para preco, consenso e conferencia. Se o numero existe
  na CVM ou na SEC, e de la que ele sai.
- **Trimestre marcado `D` e derivado** (4T calculado pelo anual menos o 9M).
  Serve para tendencia, nao para precisao de uma casa decimal.
- **Moeda e plano de contas antes de comparar.** XP, Stone e PagBank arquivam
  20-F em reais; MELI e Nubank em dolares. Banco nao tem EBIT: a chave `ebit`
  em `plano_de_contas: instituicao_financeira` nao e EBIT.
- **Divida na SEC**: `divida_total` (tag LongTermDebt) ja e o total e nunca se
  soma a `divida_curto_prazo` e `divida_longo_prazo`.
- **Uma correlacao em 8 trimestres nao e causa.** Se a margem cai junto com o
  CDI subindo, mostre a linha de despesa financeira, nao so as duas series.
- **Se a evidencia contraria a tese inicial, a tese muda.** O deep search
  existe para descobrir, nao para confirmar. Diga quando o dado contrariou o
  que voce esperava: essa frase vale mais do que a conclusao.

## Dois exemplos que a mesa ja rodou

**MELI34, "quais os gatilhos para a margem EBIT e eles estao fazendo algo?"**
O passo 2 respondeu sozinho: em 8 trimestres a margem bruta caiu 5,0 pp e a
provisao para devedores duvidosos subiu 3,0 pp da receita, enquanto pesquisa
e desenvolvimento caiu 2,3 pp e a despesa geral 2,4 pp. Ou seja: a empresa ja
esta cortando estrutura; quem come a margem e o credito, que na Mercado Libre
passa dentro do EBIT (no Magazine Luiza o custo financeiro fica abaixo dele,
por isso os multiplos nao se comparam direto). O passo 4 mostrou que o preco
nao exigia margem maior, exigia margem estavel com receita crescendo ~25% ao
ano. Sem o passo 4 a conclusao teria sido "margem caindo, evite", que era a
leitura errada.

**INBR32, "se nao tem guidance de margem, por que eu compraria?"**
O passo 3 achou o que nenhuma tabela mostra: o plano 60/30/30 (60 milhoes de
clientes, indice de eficiencia de 30%, ROE de 30% ate 2027) aparece nos
releases do 4T24 e do 1T25 e some por cinco trimestres seguidos; no 2T26 a
gestao abre a apresentacao com a "Regra do 50", uma metrica unica que soma
crescimento de receita e ROE. Trocar tres metas por uma soma deixa o
crescimento de receita substituir a perna de rentabilidade: a Regra do 50
marca 48 de ~50, quase pronta, enquanto o ROE esta em 16,3% de 30%.
O passo 2 mostrou o outro lado: a despesa de captacao subiu 4,6 pp da
receita, mas a despesa operacional caiu 2,9 pp, e o lucro so perdeu 1,4 pp de
margem com a receita quase dobrando. A execucao aparece; o painel publico e
que ficou mais facil de acertar.

Este exemplo tem uma segunda licao. Na primeira passagem a mesa escreveu que
a Regra do 50 vinha "sem data e declarada como nao sendo guidance". A
varredura com `mesa.py linha` derrubou as duas afirmacoes: a palavra
"guidance" nao aparece em nenhum dos quatro releases mais recentes, e o
grafico da Regra do 50 tem eixo ate 2029E. A frase foi corrigida. **Achado que
nao sobrevive ao grep nao vai para a nota**, e quando o dado derruba o que a
mesa disse antes, a correcao e explicita.
