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
