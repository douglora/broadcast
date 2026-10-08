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
