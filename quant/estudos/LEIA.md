# Estudos do robo de day trade

Scripts que sustentam uma decisao de regra. Rodam com `PYTHONPATH=. .venv/bin/python quant/estudos/<arquivo>.py`
e leem as barras que o MetaTrader exporta (`quant/daytrade/historico.py`). Todos separam os pregoes em duas
metades (60% para achar, 40% para confirmar) e contam o resultado depois de custo e de 1 tick de deslize.

## 08/10/2026: "prejuizo forte hoje, precisa rever e ver onde errou"

| Arquivo | Pergunta | Resposta |
|---|---|---|
| `2026-10-08_estudo_niveis.py` | Algum filtro separa ganho de perda no teste de nivel? (6.311 negocios, 888 pregoes) | Nao. Todas as faixas de todos os filtros ficam entre -R$ 17 e -R$ 30 por negocio nas duas metades. |
| `2026-10-08_estudo_estrutura.py` | Mudar stop, alvo e parcial muda o resultado? | Muda a taxa de acerto (de 23% a 45%), nao o resultado: sempre perto de -R$ 23. |
| `2026-10-08_estudo_eventos.py` | Algo medido em hora fixa antecipa a direcao ate as 13h? (321 regras) | Nenhuma passa com t maior que 2 nas duas metades. |
| `2026-10-08_estudo_lider.py` | O mini-indice anda na frente do mini-dolar? | Nao: correlacao com o minuto seguinte abaixo de 0,04. |
| `2026-10-08_estudo_tranco.py`, `..._estudo_climax.py` | O preco devolve depois de um tranco? | So quando o volume do minuto e 3 vezes a media ou mais: +1 a +2 pontos em 3 a 20 minutos (1 min, 2026). Em 5 min, 3 de 4 anos. |
| `2026-10-08_estudo_climax_sim.py` | O climax paga o custo? | Empata menos o custo: de -R$ 14 a +R$ 7 por negocio, acerto de 66% a 75% com alvo curto. Sem significancia. |
| `2026-10-08_conferir_fita_barras.py` | A fita gravada bate com as barras do MetaTrader? | Sim: volume igual em 200 de 202 minutos, maxima e minima em 201. |

Consequencia no codigo (`quant/daytrade/robo_fluxo.py`): dentro do setup `niveis`, quem opera e o climax de volume
(`CLIMAX`); o teste de nivel fica so medido; todo sinal e guardado com a leitura da fita e `python -m quant.daytrade.medir`
calcula o que cada um teria dado.

## 08/10/2026, 17h30: "ajuste para acertar 2 em 3, objetivo de 1% por dia"

`2026-10-08_calibrar_climax.py`: 1.200 configuracoes do climax (tranco 3 a 6 pontos, volume 2,5 a 5 vezes, alvo devolvendo
40% a 100% do tranco, stop de 6 a 15 pontos, tempo de 10 a 30 minutos), escolhidas na metade 1 de 2026 e conferidas na
metade 2. O calibrador rapido foi conferido contra o simulador oficial: os negocios em comum tem os mesmos pontos.

| O que | Resultado (manha, 2 contratos, depois de custo) |
|---|---|
| Tranco maior | Melhora nas duas metades: 3 pts +3 / -4; 4 pts +8 / +1; 5 pts +10 / +14; 6 pts +17 / +20 (R$ por negocio, media da grade) |
| Volume maior | Idem: 2,5x +1 / -3; 3x +7 / 0; 4x +12 / +19; 5x +18 / +14 |
| Escolhida: tranco 5, volume 3x, alvo 80%, stop 10, 20 min | 164 negocios em 177 manhas (0,93 por manha), acerto 67%, +R$ 15,60 por negocio (t 1,5); metades +17,50 e +11,90 |
| Anterior: tranco 4, alvo 60% | 249 negocios, acerto 69%, -R$ 4,30 por negocio |
| Sem os sinais de 9h27 a 9h39 (a pausa do dado, que o robo ja faz) | 143 negocios, acerto 69%, +R$ 22,40 (t 2,1) |
| Por mes (escolhida) | jan -210, fev +226, mar +1.374, abr +452, mai -49, jun +94, jul +685, ago +36, set -44, out -9 |
| Tarde (13h a 16h30), mesma leitura | Tambem positiva com tranco 5 ou 6 (+14 a +28 por negocio, acerto 61% a 65%) |

O dia com as regras do Douglas (meta de R$ 1.000, perda de R$ 1.000, 3 perdas), 177 pregoes:

| Lote | Media por pregao | Melhor dia | Pior dia | Dias com a meta |
|---|---|---|---|---|
| 2 contratos | +R$ 13 (0,013%) | +R$ 613 | -R$ 346 | 0 |
| 4 contratos | +R$ 27 (0,027%) | +R$ 1.226 | -R$ 693 | 1 |
| 8 contratos | +R$ 49 (0,049%) | +R$ 1.638 | -R$ 1.386 | 5 |

74 dos 177 pregoes nao tem nenhum sinal de manha. Ressalvas: 9 meses de dado (o MetaTrader so entrega 100 mil barras de
1 minuto), metade do ganho em marco, t perto de 2 depois de olhar 1.200 configuracoes. A meta de 1% ao dia nao sai desta regra.

## 08/10/2026, 18h32: prova fora da amostra (a calibracao NAO se confirmou)

O MetaTrader so entregava 100 mil barras de 1 minuto (2026). Com o limite de barras subido para 1 milhao
(`quant/saida/historia_longa.py`; `MaxBars` em `config/common.ini`, copia `common.ini.antes_do_historico_longo`) a serie
WDO$D veio desde 08/10/2021: 699.276 barras, 1.248 pregoes, em `autopilot_historia_WDOSD_M2.csv` (o rotulo M2 e so o nome
do arquivo; as barras sao de 1 minuto). `2026-10-08_climax_fora_da_amostra.py` roda a configuracao escolhida nos 1.071
pregoes de antes de 26/01/2026, que a calibracao nunca viu.

| Periodo | Negocios | Acerto | R$ por negocio (2 contratos) |
|---|---|---|---|
| 2021 (out a dez) | 89 | 49% | -45,50 |
| 2022 | 316 | 60% | -4,70 |
| 2023 | 301 | 55% | -18,20 |
| 2024 | 239 | 56% | -11,50 |
| 2025 | 257 | 51% | -29,20 |
| **2021 a jan/2026 (fora da amostra)** | **1.221** | **56%** | **-16,50 (t -3,6)** |
| 2026 (a amostra da calibracao) | 183 | 68% | +20,30 |

Das 108 configuracoes de uma grade reduzida (tranco 4 a 8, volume 3 a 5 vezes, alvo 50% a 100%, stop 8 a 15), 107 ganham
em 2026 e NENHUMA ganha no conjunto 2021-2025, nem em 3 dos 5 anos. Volume maior, que em 2026 melhorava, piora nos outros
anos. Com as regras do dia e lote 4: -R$ 34,70 por pregao, pior dia -R$ 1.289. A tarde tambem perde (-R$ 24,70 por negocio).

Conclusao: o efeito do climax em 2026 nao e uma vantagem; foi o ano. Nenhuma regra testada ate aqui ganha depois de
custo. Licao de processo: prova em historico longo ANTES de apresentar calibracao ou mexer no lote.

## 08/10/2026, 22h: busca ampla em 5 anos e o setup proprio ("pense fora da caixa")

Laboratorio: `quant/pesquisa/lab.py` (contas conservadoras, detector de regra que olha o futuro, registro de tudo o que
foi olhado) e `quant/pesquisa/preparar_base.py` (WDO, DOL, WIN, DI27, DI29, DI1, WSP, PETR4, VALE3; 1.248 pregoes).
Tres partes: DESCOBERTA 10/2021 a 12/2024 (805 pregoes), VALIDACAO 2025 (250), PROVA 2026 (193). Sete frentes rodaram
so na descoberta; notas e scripts de cada uma em `quant/saida/pesquisa5/<frente>/RESULTADO.md` (fora do git).

| Frente | O que olhou (aprox.) | Resultado |
|---|---|---|
| microestrutura (tamanho do negocio, dolar cheio x mini) | 330 medicoes, 56 simulacoes | nenhuma candidata; 1 pista, morta em 2025 (-R$ 134 por negocio) |
| calendario e relogio (PTAX, fim de mes, dado americano) | 7.600 medicoes, 130 simulacoes | 1 CANDIDATA: reversao do dado americano |
| intermercado (juros, bolsa, S&P, acoes) | 480 medicoes, 30 simulacoes | nenhuma; o dolar anda NA FRENTE dos outros |
| regime do dia (gap, abertura, VWAP, tendencia) | 1.700 medicoes, 17 simulacoes | nenhuma; 2 pistas: uma morta em 2025, outra morta em 2026 |
| armadilhas (rompimento falso, varredura de stop) | 415 variantes | nenhuma |
| execucao (ordem parada, cerco, escada, formato) | 1.050 simulacoes | nenhuma; ordem parada economiza so 0,26 ponto |
| maquina (78 caracteristicas, arvores e linear) | 355 ajustes | nenhuma; correlacao previsao x retorno de 0,01 a 0,02 |

### O setup que sobrou: reversao da reacao ao dado americano

Regra (parametros CONGELADOS): no horario do dado das 8h30 de Nova York (9h30 de Brasilia no horario de verao dos EUA,
10h30 fora), mede o movimento do mini-dolar do fechamento do minuto anterior ao fechamento do 2o minuto depois. Passou
de 4 pontos: entra CONTRA na abertura do minuto seguinte. Sem alvo e sem parcial; sai em 120 minutos ou no stop de 40
pontos. Codigo de pesquisa: `quant/saida/pesquisa5/calendario/regras.py::reverte_dado_ny(m, r=2, thr=4.0)`; ao vivo:
`quant/daytrade/barras.py::SinalDado` (confere com a regra de pesquisa nos 1.248 pregoes: 339 sinais, 0 diferencas).

| Parte | Negocios | Acerto | R$ por negocio (2 contratos) | t |
|---|---|---|---|---|
| Descoberta 2021-2024 | 262 | 59% | +115,90 | +3,2 |
| Validacao 2025 | 45 | 53% | +19,40 | +0,3 |
| Prova 2026 | 32 | 66% | +90,50 | +1,1 |
| Fora da descoberta (2025+2026) | 77 | 58% | +49,00 | +0,9 |
| Os 5 anos | 339 | 59% | +100,70 | +3,3 |

Por ano: 2021 +99,50; 2022 +109,50; 2023 +62,30; 2024 +184,50; 2025 +19,40; 2026 +90,50. Fora da descoberta, por
semestre: +27,60; +9,20; -52,20; +299,00. Ganho medio +R$ 464, perda media -R$ 415, stop cheio -R$ 815 (34 de 339),
maior sequencia de perdas 6, pior queda do acumulado -R$ 3.482. Media por pregao: R$ 27 nos 5 anos, R$ 8,50 fora da
descoberta. Da 1 entrada a cada 3 a 6 pregoes.

Leitura honesta: e a unica regra que atravessou descoberta, validacao e prova com sinal positivo, e tem mecanismo
(reacao exagerada ao dado e devolvida). Mas fora da descoberta o resultado ainda nao se distingue do acaso (t 0,9), e
a busca olhou mais de 12 mil medicoes. O tamanho real do efeito deve estar mais perto de R$ 50 do que de R$ 116.

## 09/10/2026: rotina da noite, dados da B3 sobre o dolar e segunda rodada de busca

- Rotina da noite: `quant/pesquisa/noite.py` (placar de todo sinal guardado e protocolo que decide quem opera e quem so
  mede; o texto de abertura do arquivo e o protocolo), `quant/daytrade/regras_lab.py` + `quant/pesquisa/setups.json`
  (o robo roda ao vivo, sem traducao, regras no formato do laboratorio), `quant/pesquisa/FILA.md` (hipoteses a testar e
  testadas). Tarefa agendada `quant-rotina-da-noite`, dias uteis as 19h15.
- Dados novos em `quant/saida/pesquisa5/b3_dolar/` (LEIA.md la dentro): negocio a negocio de WDO e DOL com a corretora de
  cada lado (20 pregoes, cresce com a rotina), PTAX das 4 janelas desde 2021, contratos em aberto, ajuste e rolagem por
  contrato em 5 anos, dolar a vista B3, cupom cambial, swap e leiloes do BC, opcoes de dolar por strike. Nao achamos rota
  gratuita para posicao por tipo de participante (a pagina antiga saiu do ar; nao se sabe se virou pago).
- Segunda rodada (tres frentes, ~3.500 medicoes; `quant/saida/pesquisa5/BRIEF_B3.md`): NENHUMA candidata. O resumo de cada
  frente esta em `quant/pesquisa/FILA.md`, secao "Testadas". A pista do penultimo dia util foi a prova com parametros
  congelados e foi reprovada (2025 -R$ 85, 2026 +R$ 193 por negocio). O que ficou de conhecimento: banco local compra com o
  preco; XP, formadores e BTG compram contra; o ajuste nao e ima; leilao agendado do BC nao tem hora nas barras.
- Continua valendo: a unica regra aprovada e a reversao da reacao ao dado americano.

## 09/10/2026, 17h45: estudo do gatilho do setup proprio ("estude melhor esse gatilho")

So com a descoberta (2021-2024), por faixa de reacao aos 2 primeiros minutos do dado (saida igual: 120 min, stop 40):

| Reacao | Negocios | Acerto | R$ por negocio |
|---|---|---|---|
| ate 1 ponto | 171 | 52% | -14,70 |
| 1 a 2 | 136 | 43% | -78,10 |
| 2 a 3 | 120 | 47% | -71,00 |
| 3 a 4 | 76 | 54% | +46,50 |
| 4 a 6 | 107 | 53% | +56,10 |
| 6 a 10 | 82 | 63% | +148,40 |
| mais de 10 | 73 | 62% | +167,00 |

Reacao pequena nao devolve; a vantagem cresce com o tamanho da reacao. Gatilho acumulado: 3 pontos da o maior resultado
por pregao (338 negocios, +R$ 100,30, t 3,3, 7 de 7 semestres, R$ 42 por pregao); 4 pontos, R$ 38; 2 pontos, R$ 31.
Gatilho de 3 levado a validacao e a prova com a saida congelada: 2025 +R$ 26,50 (62 negocios), 2026 +R$ 56,10 (54);
fora da descoberta 116 negocios, +R$ 40,30 (t 1,0), R$ 10,50 por pregao (com 4 pontos: 77 negocios, +R$ 49,00, R$ 8,50
por pregao). O gatilho ao vivo passou de 4 para 3 (`robo_fluxo.DADO`). Medir em 1, 3 ou 5 minutos em vez de 2 e pior
(t 1,5, 2,5 e 1,6).

O que isso NAO muda: o setup rende, com 2 contratos, de R$ 10 a R$ 40 por pregao (0,01% a 0,04% do capital). A meta de
1% ao dia fica 25 a 100 vezes acima, e nenhum gatilho opera todo dia: abaixo de 3 pontos a reversao perde.

## 09/10/2026, noite: terceira rodada (mini-indice e acoes) e a meta de 0,5% ao dia

O Douglas baixou a meta para 0,5% ao dia e liberou mini-indice e acoes. `lab.ESPEC` / `lab.avaliar(ativo=...)` passaram a
ter as contas de cada mercado (custo de ida e volta: WIN ~0,01% do preco, WDO ~0,02%, acao ~0,11%); a base ganhou 13 acoes
e o BOVA11. Quatro frentes (~15 mil medicoes): NENHUMA regra aprovada. O detalhe esta em `quant/pesquisa/FILA.md`.
- A unica candidata (WIN: a tendencia do dia continua nos ultimos 30 minutos; descoberta t 6,6) foi reprovada na validacao
  de 2025 (-R$ 4,47 por negocio, acerto de 40%). Reimplementada de forma independente em
  `quant/pesquisa/regras/win_fim_do_dia.py` (800 de 801 sinais iguais aos da frente). Fica para a prova viva.
- Em acoes o custo (0,11%) e 3 a 20 vezes maior que qualquer efeito intradiario encontrado.
- Conta que foi dita ao Douglas: com perda maxima de 1% ao dia, um sistema excelente rende cerca de 0,1% ao dia; 0,5% pede
  oscilar uns 4% ao dia. Somando as tres rodadas: mais de 30 mil medicoes em 5 anos, tres mercados, UMA regra aprovada
  (reversao do dado americano no mini-dolar), que rende 0,01% a 0,04% ao dia com 2 contratos.

## 09/10/2026, 22h: quarta rodada, modelo multifator

Pedido do Douglas: "continue so no day trade, mas multifatores agora... achar alguma assimetria com os dados e entrar, e ai
vamos refinando". Desenho em `quant/saida/pesquisa5/BRIEF_4.md`; resultado de cada mercado em `quant/pesquisa/FILA.md`
(secao "Testadas"). Nenhuma candidata: a soma dos efeitos pequenos nao paga o custo em nenhum dos tres mercados. No
mini-indice a soma so reencontra o fim do pregao; no mini-dolar, o dado americano (ja aprovado) e o fim do pregao; nas
acoes o sinal e real (t 6,8) e 5 a 10 vezes menor que o custo. Os modelos ficaram com `modelo.py::sinais(parte)` prontos
para rodar em dado novo.

## 10/10/2026: o metodo Chan + Lopez de Prado e a prova final do fim do pregao

O Douglas trouxe um metodo (ideia de Ernest Chan, rigor de Marcos Lopez de Prado) e pediu para introduzi-lo e dizer, com
honestidade, se ha estrategia vencedora. O metodo virou `quant/pesquisa/METODO.md` e as ferramentas `quant/pesquisa/ldp.py`
(Sharpe deflacionado pelo numero de tentativas, validacao combinatoria com purga, barras de volume, queda maxima).

| Regra | Onde | Sharpe anual liquido | Veredito pelo metodo |
|---|---|---|---|
| Reversao do dado (WDO, gatilho 3) | 2021-24 / 2025 / 2026 | 1,82 / 0,45 / 1,06 | positiva nos 6 anos, mas fraca: 0,72 fora da descoberta (pede > 1) e deflacionado de 0,43 com 2.500 tentativas (pede > 0,95) |
| Fim do pregao (WIN), sempre | 2021-24 / 2025 / 2026 | 3,68 / -0,91 / -3,65 | foi real e inverteu |
| Fim do pregao com filtro de 60 pregoes | 10/2021-12/2025 / 2026 | 2,88 / -1,17 | passou em tudo ate 2025 (deflacionado 0,96 com 35.000 tentativas) e foi REPROVADA na prova final de 2026 |

Leitura: nenhuma estrategia passa hoje nos criterios do metodo. O metodo cumpriu o papel dele: uma regra com tres anos de
Sharpe 3,7 teria ido para o robo e perdido dinheiro em 2026. A vantagem do fim do pregao existiu, decaiu em 2025 e virou do
avesso em 2026 (provavel excesso de gente explorando o mesmo empurrao). A variante adaptativa e a regra original ficam na
prova viva (`quant/pesquisa/provas_vivas.json`), medidas so com pregoes novos.

Na tarde de 10/10 rodou o resto do metodo (detalhe em `quant/pesquisa/FILA.md`): a meta-rotulagem do setup do dado nao
melhora a regra simples (0 de 66 configuracoes; so o tamanho da reacao informa) e as barras de volume nao mudam o quadro no
indice nem no dolar. Os limites de risco do metodo entraram no robo: perda da semana de R$ 2.000, queda maxima de R$ 10.000
e lote cortado para o stop cheio nao passar da perda do dia (`quant/saida/risco_robo.json`, `chave.risco()`).
Aritmetica que fecha a questao do historico: com cerca de 1.050 pregoes, um Sharpe deflacionado de 0,95 so sai com Sharpe
anual acima de 2; regra de Sharpe 1 so se prova com dado novo.

## 10/10/2026, fim da tarde: dolar global, historico de negocios e agressor ("verifique a viabilidade para o daytrade")

O Douglas pediu para verificar duas ideias para o day trade: (1) o dolar la fora andar na frente do nosso e (2) historico
de negocio a negocio com agressor. Detalhe em `quant/saida/pesquisa5/global_lidera/RESULTADO.md` e
`quant/saida/pesquisa5/fluxo_mt5/RESULTADO.md`.

- Ferramenta nova: `~/Desktop/terminal-artefato/ferramentas/mt5/AutopilotSonda.mq5`, um script so de leitura que roda uma
  vez no MetaTrader (partida por `/config:` com `[StartUp] Script=`), sem tocar no AutopilotFeed. Tira barras de 1 minuto
  de qualquer simbolo, conta negocios e agressor de um dia e grava o fluxo por minuto de um periodo.
- Dolar global: em barra de 1 minuto o ajuste termina dentro do proprio minuto. Nao ha o que operar (14 simulacoes, todas
  negativas depois do custo).
- Historico da XP: negocio a negocio do mini-dolar e do mini-indice continuos desde 07/2025 (com dias faltando), SEM o
  agressor da bolsa. O agressor so existe no contrato vigente (o vencido some do servidor) e em acoes (2 meses). Nao ha
  corretora em lugar nenhum do MetaTrader. Gravado por minuto: WINV26 (42 pregoes), WDOX26 (28), DOLX26 (19) com agressor
  real; WDO$N (290), WIN$N (313) e DOL$N (186) com agressor inferido.
- Agressor inferido pelo preco contra a compra e a venda: 99,8% de acerto no contrato; na serie continua so resta a regra
  do tique (correlacao de 0,95 por minuto com o saldo real).
- Triagem do saldo de agressao por minuto (119 pregoes de descoberta): sem continuacao; devolucao pequena, abaixo do custo.
- B3 (sessao "Boletim B3 handoff"): 20 pregoes de negocio a negocio com corretora, sem agressor e sem livro; nada mais
  longo de graca; UP2DATA pago e so fim de dia.
- Armadilha da B3: o arquivo de negocios do ultimo pregao pode ser servido pela metade (o de 09/10, no sabado as 15h18,
  tinha so o cabecalho no mini-dolar e so o fim da tarde no mini-indice). Os 51 arquivos ja guardados foram conferidos em
  10/10 e estao inteiros (abertura ao fechamento). `b3_dolar/scripts/baixa_ticks.py` agora baixa de novo os dois ultimos
  pregoes a cada rodada e so troca se vier com MAIS linhas (o antigo fica ao lado com o final `.parcial`; no registro sai
  a palavra COMPLETADO). Se isso acontecer, o cache das corretoras daquele dia (`corretoras/cache/tk_*`) fica velho.

## 10/10/2026, noite: carteira liberada, quatro modulos, opcoes e mais duas frentes no dolar

O Douglas liberou a carteira de acoes ("vamos entao para a carteira de acoes"), pediu a tela com quatro modulos
(multifatorial, mini-dolar, mini-indice, opcoes), cobrou a protecao em mini-indice de 08/10 e disse do dolar: "ainda nao
desisti". Detalhe de cada frente no RESULTADO.md da pasta indicada.

- Protecao em mini-indice (`quant/execucao/protecao.py`, testes em `test_protecao.py`): o defeito de 08/10 era de tamanho
  (venda executada antes das compras: livro vendido no liquido). Agora a venda acompanha as acoes carregadas, nunca passa
  do valor delas, e carregada entre pregoes e nao abre em contrato perto do vencimento.
- Protecao por regime (`quant/regime.py`, `quant/saida/pesquisa_carteira/`): cinco variantes pre-registradas, todas piores
  que a protecao fixa na janela de desenvolvimento (2012-03 a 2015-12). A leitura de regime fica na tela so como informacao.
- Dolar em segundos, mini contra cheio, rolagem e dolar com prazo de dias: nada passa (ver FILA.md, "Testadas").
- Opcoes (`quant/opcoes/`, `quant/saida/pesquisa5/opcoes/`): venda de put, call coberta, trava de credito e pozinho
  reprovados contra o CDI (97 configuracoes); protecao com opcoes de BOVA11 fica em medicao, como seguro.
- Modulos: `modo_robo.json` ganhou a chave `modulos`; a carteira grava `quant_fatores.json`, o day trade `quant.json`, a
  prova viva do indice `quant_indice.json` e `quant/opcoes/painel.py` grava `quant_opcoes.json`.

- TESTE LONGO DA CARTEIRA (periodo final 2016-01 a 2026-06, aberto UMA vez em 10/10/2026; `quant/holdout.json`,
  `quant/saida/pesquisa_carteira/RESULTADO_HOLDOUT.md`): NAO PASSOU nos criterios escritos antes (4 de 9 reprovados).
  Principal (acoes 70%, venda de indice de 50% do valor das acoes): 10,8% a.a. contra CDI de 9,6% (R$ 228 por mes a mais
  com R$ 100 mil), Sharpe do excesso 0,12, queda maxima 23,3%, alfa contra o NEFIN -2,6% a.a. (t -1,5), Sharpe
  deflacionado 0,08, 1 de 4 subperiodos positivo. Sem protecao: +4,6% a.a. sobre o CDI, queda de 35,5%. 1 contrato fixo:
  +4,5%, queda de 29,3%. As cinco variantes de protecao por regime ficaram atras de todas (2020: -21% a -27%; alfa -7% a
  -8% a.a., t -2,4 a -2,7). Os portoes fundamentalistas nao agregaram (sem eles: +4,1% a.a., Sharpe 0,39). O retorno veio de
  ficar comprado em bolsa, nao da selecao. Antes de abrir: numero de acoes desde 2010 pelo FRE da CVM
  (`quant/dados_brutos/cvm_fre`), escala corrigida linha a linha, `capital_social` passa a mesclar em vez de substituir.
  O periodo NAO pode ser reaberto: ideia nova (tirar os portoes, exposicao por volatilidade, piso de protecao) so com
  dado novo.
- ASSIMETRIAS EM OPCOES (10/10/2026, noite; pedido do Douglas: "ele tem que ver a melhor entrada nas opcoes", "ME DE A
  SOLUCAO"; `quant/saida/pesquisa5/opcoes/RESULTADO_ASSIMETRIAS.md`, hipoteses A0 a A6 escritas antes): duas passaram nas
  tres fases, nenhuma aprovada pelo Sharpe deflacionado. A0 capital protegido (caixa no CDI e 0,5% do capital por mes em
  call no dinheiro de 1 mes): 10,9% a.a. contra CDI de 10,0% em 174 meses, pior mes -0,33%, pior ano +2,9%, captura ~7% da
  alta acima do CDI, Sharpe 0,39/0,36/0,47 (deflacionado 0,47). A1 straddle onde a volatilidade realizada de 252 dias
  supera a implicita: +20% por operacao (n 428, t 2,24; deflacionado 0,20; perde em metade dos meses). Reprovadas: proteger
  BOVA11 so com volatilidade implicita baixa (nao teria protegido marco/2020), inclinacao, paridade, straddle antes do
  resultado (-31% a -35% por operacao). Arbitragem no fechamento: 6,6 por dia, centavos, cotacao velha.
  O modulo ganhou `quant/opcoes/assimetrias.py` (ranking diario das entradas pela vantagem contra 10 anos de historia do
  ativo, com o veredito da familia em cada linha) e `quant/opcoes/carteira_simulada.py` (risco definido de ate R$ 500 por
  estrutura, 6 abertas, R$ 3 mil em risco; capital protegido como posicao permanente; estado em `quant/saida/opcoes/`).
  Em 09/10/2026 as opcoes estavam caras (percentil da volatilidade implicita do BOVA11 em 88) e so 3 de 15 estruturas
  tinham vantagem positiva.
- PUBLICACAO DA TELA (terminal): o Douglas disse "sim" em 10/10. As 64 fatias antigas `d/a/140` a `203` ja sairam do
  artefato (versao 607). Os comandos `python -m coletor.montar --tirados` e `--liberar` sao barrados para o assistente
  pela protecao do aplicativo: quem roda e o Douglas, no Terminal. Ate la a pagina oficial segue com a tela antiga.

## 10 para 11/10/2026: a rodada do "gestor multimercado"

Pedido do Douglas: protecao em 1/4, stock picking com macro e bottom-up, opcoes junto, referencias de gestores e a TIR
real no terminal. Onde esta cada coisa:

- Decisoes dele: `quant/saida/carteira_config.json` (lido por `quant/config_carteira.py` e `quant/execucao/protecao.py`).
- Visao da mesa (macro, setores, bottom-up): `quant/saida/mesa/visao_mesa.json`, aplicada por `quant/mesa.py` (veto com
  conviccao -2, ajuste pequeno de peso; sem teste historico, medida daqui para a frente).
- Gestores: `quant/docs/gestores-referencia.md` (regras G1 a G18) e o relatorio em `quant/saida/relatorios/`.
- Opcoes: `quant/saida/pesquisa5/opcoes/RESULTADO_TESES.md`. Put depois de queda forte nao melhora a venda de put; nas
  eleicoes de 2014, 2018 e 2022 o papel bateu a call em media; gatilho tecnico com trava falhou na prova. O livro de
  teses (`quant/opcoes/teses.py`) compara papel, call, trava e put por tese e mostra o que o preco exige.
- Tamanho da mao e alocacao: `quant/saida/pesquisa_carteira/RESULTADO_MAO_E_ALOCACAO.md` e `quant/risco/` (nao ligado ao
  robo). Mao por volatilidade corta a cauda sem melhorar o Sharpe; corte por queda reprovado.
- TIR real implicita: modulo `tir` do terminal (`~/Desktop/terminal-artefato/coletor/tir.py`, `src/mod/tir/`).


## 11/10/2026: o livro por classes e o orcamento de queda

Respostas do Douglas: "entra cheia e pode rotacionar"; BBAS3 "foi so um exemplo pra voce entender uma forma de pensamento";
pesos e regra de volatilidade "pode ser"; orcamento de queda "corrija entao". O que mudou:

- Decisao em arquivo: `quant/saida/risco_livro.json` (lido por `quant/risco/livro.py`). Pesos 60% acoes, 30% opcoes, 10%
  dolar; mao por volatilidade ligada; corte por queda desligado; orcamento de queda do livro 25% (17% acoes, 3% opcoes,
  5% day trade). `"ligado": false` volta ao comportamento anterior (carteira em 70%, opcoes com o capital inteiro).
- Carteira: exposicao = peso da classe x mao do dia (`quant/config_carteira.py`). "Cheia" e 60% do capital, nao 70%.
  Uma `exposicao_acoes` escrita em `carteira_config.json` continua mandando por cima (ordem direta).
- Rotina da manha: dois passos novos antes da boleta, `risco` (`python -m quant.risco.orcamento`) e `livro`
  (`python -m quant.risco.livro`). Sao auxiliares: se falharem, a boleta sai com mao cheia e o log avisa.
- Opcoes: o capital protegido passou a 1% do capital DA CLASSE por mes (R$ 300), nao do livro inteiro (R$ 1.000). Erro
  do assistente em 10/10: R$ 1.000 por mes contra uns R$ 300 de rendimento do caixa da classe nao protegia o principal.
  A tranche de outubro, aberta com R$ 1.000, fica como esta. Com o orcamento de queda estourado, nada tatico novo abre.
- Day trade: `queda_maxima_rs` baixou de R$ 10.000 para R$ 5.000 em `quant/saida/risco_robo.json` (a fatia dele no
  orcamento). Para voltar, escrever 10000 no arquivo. Semana (R$ 2.000) e dia (R$ 1.000) nao mudaram.
- Caso BBAS3: marcado `exemplo` em `quant/opcoes/teses.py`; nunca abre.
- Tela: bloco `livro` em `quant_fatores.json` (pesos, mao, queda de cada modulo contra o orcamento).
- Testes: `quant/testes/conftest.py` isola a suite dos arquivos de decisao em `quant/saida`.

## 11/10/2026 (fim da manha em diante): o mandato novo

Palavras do Douglas: carteira de acoes "de operacoes de curto prazo, swing trades curtos, de no max 2 semanas"; day trade
"pode voltar para os R$10.000,00"; opcoes em tres vertentes (especulativa, dividendo sintetico com saida perto de 80% do
premio, travas de BOVA11: "fique especialista nisso"); mini-dolar com "objetivo de fazer 0,10% ao dia liquido"; Ruy Alves e
Marco Freire (Kinea) como referencia macro; o robo com "acesso a todas ferramentas do terminal" e usando "o banco de dados
do terminal". O que existe por causa disso:

- `quant/saida/modo_robo.json`: `"modulos": ["swing", "daytrade"]`. A carteira de fatores nao roda (o modulo continua no
  codigo; para voltar, `["fatores", "daytrade"]`).
- Swing: `quant/swing/` (pesquisa, livro, boleta, gestor, vivo), contrato da tela em `quant/docs/tela_swing.md`, pre-registro
  e resultados em `quant/saida/pesquisa_swing/`. 39 variantes, nenhuma passou descoberta (2010-2017) e validacao (2018-2021);
  a prova 2022-2026 esta FECHADA. Roda so medido; capital so por evidencia ou por `"liberar"` em `quant/saida/swing_config.json`.
  M1 e M2 medem a conviccao e o veto da mesa (sem teste historico).
- Opcoes: `quant/opcoes/vertentes.py`, `manejo.py`, `vertentes_pesquisa.py`; manual em `quant/docs/travas-bova.md`; resultado
  em `quant/saida/pesquisa5/opcoes/RESULTADO_VERTENTES.md`. Limites de risco 900 / 1.200 / 900 (somam os R$ 3.000 da classe).
- Mini-dolar: `objetivo_dia_rs` (placar) e `meta_dia_rs` (teto que zera) em `quant/saida/risco_robo.json`; medicao em
  `quant/pesquisa/META_DIA.md` (parar em R$ 100 baixa a media do dado americano de R$ 34 para R$ 2 por pregao).
- Livro: `quant/saida/risco_livro.json` com orcamento de queda de 30% (17 acoes, 3 opcoes, 10 day trade); o resultado do
  swing entra em `quant/risco/livro.py::resultado_acoes`.
- Mesa: visao refeita para 10 pregoes; procedimento em `quant/docs/visao_mesa_procedimento.md`; lente Kinea em
  `quant/saida/mesa/lente_kinea.json`; tarefa agendada `quant-visao-da-mesa-semanal` (domingo 8h40, Sonnet).
- Terminal: `quant/terminal/` le o banco de dados do terminal (ficha, tabela, eventos, historico); inventario e lacunas em
  `quant/docs/terminal-para-o-robo.md`. No terminal, `coletor/banco.py` guarda a historia diaria em SQLite.
- Pendente do Douglas: liberar ou nao o setup D1.S1 (reacao ao resultado) com capital; parar ou nao o mini-dolar em R$ 100;
  fonte para a expectativa dos dados americanos (`cache/manual/consenso_eua.csv` no terminal).

## 11/10/2026 (noite): bonificacoes que faltavam na tabela de eventos (defeito de dado, achado pela auditoria da TIR)

O que era: o indice de retorno total (`eventos.retorno_total_limpo`, que alimenta TODO backtest, os sinais de momentum, o gate e o swing) subia menos que o preco
ajustado do terminal em 41 meses de 15 papeis (ITUB4, BBDC4, WEGE3, ITSA4, LREN3, CMIG4, SLCE3, ...). Retorno total nunca sobe menos que o preco; quando sobe,
falta bonificacao ou desdobramento na tabela `banco/eventos.parquet` e o indice "cai" na data-ex (bonificacao de 10% = -9,1%; desdobramento 1:2 = -50%).

Tres causas, em ordem de tamanho (`quant/dados/eventos_cvm.py`, docstring completa):
1. **A lista da B3 tem buracos** (`GetListedSupplementCompany` nao devolve toda bonificacao antiga: Itau so 4 das ~10 desde 2007, Bradesco nada entre 2010 e 2021, WEG
   nao tem 2014 nem 2015). Nao e truncamento por tamanho. Agora a segunda fonte e a CVM: FRE item 17.3 (`dados_brutos/cvm_fre`, quantidade de acoes antes e depois, ate o FRE
   de 2023) e, de 2024 em diante (o FRE novo nao tem mais o item), o salto exato do numero de acoes entre dois trimestres (`capital_social.parquet`: proporcao redonda, igual
   nas classes). A CVM da o fator e a assembleia, nao a data-ex: a data-ex vem do PRECO (o dia da janela em que `preco x fator + provento` fica mais perto do preco anterior,
   menos a mediana do mercado). Contra os eventos de 7% ou mais que a B3 ja traz (129), acerta o dia (a 3 dias) 89% das vezes (115). Fonte gravada: `cvm_fre` / `cvm_capital`; `obs` leva o escore e a
   margem (22 de 315 com `DATA INCERTA`: o retorno acumulado esta certo, o dia pode estar algumas semanas fora).
2. **O leitor da B3 descartava o evento de quem recebe**: na bonificacao `assetIssued` e a classe das acoes NOVAS e `isinCode` a do titular. CYRE3 (18,96%, 2025), AXIA3
   (26,3%), RENT3, BPAC11, SANB3 saiam. Conserto em `eventos._casa_evento_de_quantidade`; unit recebe o evento das classes que a compoem.
3. O COTAHIST nao ajuda: `fatcot` e fator de lote, nao de bonificacao.

Dos 41 casos: 35 tinham o evento faltando e agora estao na tabela (30 FRE, 2 leitor da B3 corrigido, 2 salto do numero de acoes, 1 ja era da B3); 6 sao o terminal que datou o evento
na assembleia e nao no ex (BBDC4 2017-03 e 2018-03, ITSA4 2016-04, CMIG4 2013-04, EZTC3 2015-04: o evento esta na tabela 1 a 2 meses depois, na data do preco; CMIG4 2014-09,
queda de 22% sem evento).
Entraram **315 eventos de quantidade em 161 papeis** (257 FRE, 26 salto de acoes, 32 leitor da B3; 208 bonificacoes, 58 desdobramentos, 49 grupamentos).

Limites declarados: evento abaixo de 5% nao entra (some no ruido do dia; vies < 5% por evento); reducao de acoes que nao e grupamento redondo nao entra (cancelamento de
tesouraria: Ambev 2013, Assai 2020); direito de subscricao continua fora do retorno (o Yahoo ajusta como desdobramento).

Como refazer: a rotina diaria (`python -m quant.dados.eventos`) ja faz sozinha. Sem rede, a partir dos brutos que estao no disco:
`python -m quant.dados.eventos --do-bruto --sem-statusinvest` (guarda `banco/eventos_antes_do_bruto_AAAAMMDD.parquet`, o parquet COMO ESTAVA; nunca sobrescreve a copia).
So a parte da CVM sobre um parquet existente: `python -m quant.dados.eventos_cvm --gravar`.

Teste (`test_retorno_total_universo.py`, dado real; pula sem ele): compara, mes a mes, o indice com o preco ajustado do terminal (`cache/out/longo`, Yahoo) em TODO o
universo liquido (giro >= R$ 5 mi, 2010 em diante) e reprova mes novo fora de `CONHECIDOS` (33 meses, 24 em que o Yahoo ajusta 5% a 19% sem evento na B3 nem na CVM, provavel direito
de subscricao; 9 com erro do Yahoo). Universo liquido 2010+: 95 meses em 43 papeis ANTES (47 nos 15 da auditoria, 48 em 30 outros papeis) para 43 meses em 29 papeis DEPOIS
(33 sem explicacao, 8 serie do Yahoo parada, 2 subscricao). Universo inteiro (441 papeis com serie): 498 meses em 180 papeis para 385 em 162. A lista de 41 da auditoria: 0 reprovam.

Efeito, so descritivo e sem reabrir nada (`pesquisa_carteira/90_efeito_eventos_corrigidos.py` e `pesquisa_swing/95_efeito_eventos_corrigidos.py`; o numero publicado foi refeito
primeiro com a tabela de antes e bate com `holdout.json` a 1e-9):
- Carteira de fatores, holdout 2016-2026 (S2, a principal): 10,77% -> 9,92% ao ano (o publicado estava 0,85 ponto ACIMA do corrigido); excesso sobre o CDI +1,17 -> +0,33 ponto;
  Sharpe do excesso 0,12 -> 0,03; queda maxima 23,3% -> 26,2%. S0: 14,17% -> 14,66% (+0,49); S1: 14,13% -> 14,30% (+0,18). Desenvolvimento 2012-03 a 2015-12: S2 6,59% -> 8,26%,
  S0 2,06% -> 4,45%, S1 3,22% -> 5,33% (publicado 1,7 a 2,4 pontos abaixo). Nenhuma conclusao muda: o S2 continua reprovado (e piora).
- Swing, descoberta e validacao 2010-2021 (39 variantes): nenhuma variante muda de lado; finalistas 0 -> 0; a prova 2022-2026 segue FECHADA. D1.S1 (a quase-aprovada) vai de
  Sharpe 0,28 para 0,25 na descoberta.
- Livro de tentativas: duas linhas com escopo `correcao_de_dado` (t0079 carteira, t0080 swing), fora do N de todas as familias (n_tentativas segue 37; swing 39). Nao e
  tentativa nova: mesma regra, mesmos parametros, outro dado.
- Painel de sinais refeito com a tabela corrigida: `pesquisa_carteira/sinais_2011_2026_eventos_corrigidos.parquet` (so mudam as colunas derivadas de retorno: momentum e
  volatilidade). O original continua ao lado.


## 12/10/2026: estudo completo da estrategia (auditoria, dados, literatura, testes, camada de observacao)

Pedido do Douglas: "estudo completo da estrategia do robo, backtesting, Monte Carlo e outras formas... reveja a estrategia, ache os furos...
pesquise estrategias vencedoras... deixe o modelo mais assertivo". Relatorio: `quant/saida/relatorios/2026-10-12_estudo_completo_robo.html`.
Scripts em `quant/estudos/2026-10-12_*.py`; saidas em `quant/saida/pesquisa5/montecarlo/`; tentativas no `registro.jsonl` (11 novas).

| O que | Resultado | Veredito |
|---|---|---|
| Reversao do dado (congelada), 2021-2025, Monte Carlo | 400 negocios, +R$ 88,85/neg, Sharpe 1,57, DSR 0,48 (N 1.000) e 0,16 (N 35 mil); bootstrap: ano medio +R$ 8,4 mil, P(ano negativo) 4-6%, P(queda > 10 mil) < 0,2%; permutacao z 4,3 (p < 0,0025); so 2025: +R$ 26/neg | continua a unica regra com capital; fraca fora da descoberta |
| Reversao do dado por tipo de dia (calendario do BLS) | payroll +R$ 223 e PPI +189/neg na descoberta; dias sem dado conhecido +57 (2025: -21); V1 so dia com dado: +R$ 137/neg, t 3,2, 7/7, mas R$ 31/pregao (base 42) | "nao agrega" pelo pre-registro; rotulo `tipo_do_dia` so medido em cada sinal |
| Overnight BOVA11 (Lou-Polk-Skouras) | +5 pb/dia (t 2,0); regra liquida -2,8 pb | reprovada |
| Dia de anuncio (Savor-Wilson) e pre-FOMC (Lucca-Moench) no BOVA11 | -1,5 pb de diferenca; pre-FOMC +12 pb (n 24, t 0,6) | nada / inconclusivo |
| Tendencia de meses no indice (NEFIN) | Sharpe 0,10 e 0,08 (12-1) | reprovada |
| Tendencia em juros (DI 2 anos, Kadima) | Sharpe 0,33 e -0,58 (N 126) | reprovada |
| Mecanismo da surpresa (payroll/CPI) | reacao contra o sentido da surpresa devolve 11,3 pts contra 6,3 | pista para a prova viva com consenso |
| Caminhos do livro 60/30/10 | queda p95 14%, p99 18%; acoes estouram 17% em 3% dos caminhos | orcamento de 30% cabe |

Furos (tabela completa no relatorio): o setup do dado dispara todo dia (A1); pausa do dado fixa em 9h28 nao segue o horario de verao dos EUA (A2);
cotacao velha > 15 s nao executa o stop (A8); protocolo da noite promove com t >= 1 e n 20 (A11); placar do "so medido" ate 17h30 contra operado
ate 13h (A12); N do Sharpe deflacionado varia por familia (A17); IR fora das opcoes e do swing (A18, A21); validacao/prova reabertas em varias
regras (digest do agente: 168 aberturas da validacao, 16 da prova); custo de 1,24 ponto no codigo contra 1,05 nos briefs.

Camada de observacao (`quant/observacao/`, so medida): 17 sinais (macro, micro, grafico, fundamento) lidos do terminal, termometro G20,
dose G23 e placar G19/G2; passo auxiliar `observacao` na rotina da manha; primeira leitura em 12/10/2026. Dado novo: calendario das
divulgacoes americanas (`quant/dados/calendario_eua.py`: BLS 2021-2026, pedidos de auxilio, efetivos pela API do BLS, consenso semanal
do ForexFactory arquivado). Pendente do Douglas: compilar e rodar o script do calendario do MetaTrader (consenso historico).
Nenhuma regra com capital mudou.
