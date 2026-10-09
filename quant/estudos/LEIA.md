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
  contrato em 5 anos, dolar a vista B3, cupom cambial, swap e leiloes do BC, opcoes de dolar por strike. Nao existe mais de
  graca: posicao por tipo de participante.
- Segunda rodada (tres frentes, ~3.500 medicoes; `quant/saida/pesquisa5/BRIEF_B3.md`): NENHUMA candidata. O resumo de cada
  frente esta em `quant/pesquisa/FILA.md`, secao "Testadas". A pista do penultimo dia util foi a prova com parametros
  congelados e foi reprovada (2025 -R$ 85, 2026 +R$ 193 por negocio). O que ficou de conhecimento: banco local compra com o
  preco; XP, formadores e BTG compram contra; o ajuste nao e ima; leilao agendado do BC nao tem hora nas barras.
- Continua valendo: a unica regra aprovada e a reversao da reacao ao dado americano.
