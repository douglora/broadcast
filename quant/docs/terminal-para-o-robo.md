# O terminal para o robo: o que ele tem, como o robo le e o que ainda falta

Pedido do Douglas (11/10/2026): "Esse robo precisa ter acesso a todas ferramentas do terminal, para tomar decisoes mais assertivas nos trades
[...] penso na questao dele usar o banco de dados do terminal, para que o terminal se torne indispensavel e ficarmos com um banco de dados
cada vez mais robusto e ficar cada vez melhor".
Este documento e o mapa. Tudo e SIMULACAO; nada aqui e recomendacao de compra ou venda.

Dois caminhos, que nao se confundem:

| Caminho | Quem escreve | Quem le | Onde |
|---|---|---|---|
| robo para a tela | `quant/ponte_terminal.py`, `quant/opcoes/painel.py` e os robos (`quant*.json`) | a aba QUANT do terminal | `web/d/x/quant*.json` |
| **terminal para o robo** (este documento) | os coletores do terminal | o robo, pelo pacote `quant/terminal/` | `~/Desktop/terminal-artefato/cache/out/` e o banco `cache/banco/terminal.sqlite` |

O robo so **le** o terminal. Nada do pacote `quant/terminal/` escreve no terminal.

## 1. Como o robo chama

Caminho do terminal: variavel de ambiente `AUTOPILOT_TERMINAL` (padrao `~/Desktop/terminal-artefato`).

```python
from quant import terminal

terminal.disponivel()                                  # bool: o terminal esta no disco?
f = terminal.ficha("PETR4")                            # dict: tudo o que o terminal sabe do papel
f["tir"]["tir_prudente"]["premio_pp"]                  # 11.68: TIR prudente menos a NTN-B de ~10 anos, em pontos
f["tir"]["ciclo_do_lucro"]["marca"]                    # None | "pico" | "fundo"
f["motivos"]                                           # por que cada pedaco ausente esta ausente
df = terminal.tabela(["PETR4", "VALE3"])               # DataFrame, 1 linha por ticker, 64 colunas estaveis
terminal.cobertura(df)                                 # quantos tickers tem cada coluna
terminal.eventos(dias=10, pais="BR")                   # resultados, proventos, assembleias, vencimentos e agenda macro
terminal.historico("tir", "PETR4", desde="2026-10-01") # lido do banco historico (tabelas na secao 5)
```

CLI (mesmos dados, para olhar no Terminal do Mac): `python -m quant.terminal ficha PETR4 [--json]`, `tabela [TICKER...] [--cobertura]`,
`eventos --dias 10`, `historico TABELA --ticker X`, `status`. Rode com `cd ~/Desktop/quant-b3 && PYTHONPATH=. .venv/bin/python -m quant.terminal ...`.

### Regras de leitura (valem para quem usa os numeros)

1. **Nunca inventar.** O que falta e `None` (na tabela, `NaN`), com o motivo em `ficha["motivos"]`. Nunca troque `None` por zero.
2. **Idade tem limite por tipo de dado.** Passou do limite, o pedaco vira `None` com o motivo (limites em `terminal.LIMITES_DIAS`):
   TIR 5 dias (do preco usado), consenso 4 (da coleta), aluguel 5, multiplos 5, valuation 7, opcoes 5 (a IV tem o mesmo teto contado do dia
   dela), noticias 2, calendario 3, pares 7, insiders 75 depois do fim do mes do formulario, divida 200 depois do fim do trimestre, fundos 210.
   Todo pedaco traz `fonte`, `data` (do dado, nao da leitura) e `idade_dias`.
3. **Unidades**: percentual em pontos (7.4 = 7,4%), dinheiro em reais (a divida, que o terminal guarda em R$ milhoes, sai convertida), datas
   ISO. Colunas `_pct` e `_pp` sao pontos percentuais.
4. **Leia `avisos`.** Consenso de uma casa so, alvo de 1 ou 2 analistas, empresa ciclica, taxa de aluguel repetida (sem negocio no dia),
   IV velha: o aviso vai dentro do pedaco e junto em `ficha["avisos"]`.
5. **Quem o terminal e.** O consenso e de agregador (Yahoo), nao dado oficial. A TIR e um modelo do proprio terminal, com premissas
   escritas no registro (`premissas`); o terminal apresenta, nao recomenda. As notas de noticia sao o julgamento do agente, nao fato.
6. **Nenhum campo do terminal foi testado como sinal de trade.** Antes de entrar numa decisao do robo, ele passa pelo mesmo caminho de
   qualquer ideia nova (hipotese escrita antes, desenvolvimento, validacao, prova viva). O banco historico existe para isso: ver a secao 6.

## 2. O que a `ficha` e a `tabela` devolvem hoje (11/10/2026, 369 acoes da B3)

`ficha`: doze pedacos. Para PETR4 e DIRR3, todos os 12 tem dado; para BBAS3, 11 (banco nao tem painel de divida: o motivo vem dito).

| Pedaco | O que traz | Fonte | Dado de |
|---|---|---|---|
| `tir` | TIR de hoje, normalizada e prudente; premio sobre a NTN-B; `ciclo_do_lucro` (pico, fundo, criterios e razoes); base (consenso ou historico) e no de casas; premissas; segunda leitura por caixa | modulo `tir` | preco de 09/10 |
| `consenso` | alvo (medio, mediano, faixa, no de analistas, potencial); recomendacao (nota 1 a 5, % compra e ha 3 meses); LPA do trimestre, do ano e do ano seguinte com revisao em 7/30/60/90 dias e quem subiu e cortou; evolucao do alvo desde o primeiro retrato | Yahoo (agregador) | coleta de 10/10 |
| `insiders` | saldo de compras menos vendas em reais na janela de 90 dias, por orgao (controlador, conselho, diretoria...); saldo so de administradores; no de negocios; mes do formulario | CVM (Res. 44, art. 11) | formulario de agosto/2026 (entregue em 10/09) |
| `aluguel` | taxa do tomador (media, minima, maxima), saldo em quantidade e em reais, variacao em 1/5/20 dias, % do float, dias para cobrir, saldo contra a media de 21 pregoes | B3 BDI | pregao de 09/10 |
| `noticias` | manchetes dos ultimos 7 dias: contagem, soma e maior nota 0-3 de "faz preco", as 5 principais com fonte e hora | veiculos + agente | 11/10 |
| `proximo_resultado` | data, periodo, confirmado ou estimado, dias ate; teleconferencia; reacao media historica do papel no pregao apos o resultado; outros eventos do papel (data ex, assembleia) | CVM, RAD, Yahoo | 11/10 |
| `multiplos` | preco, valor de mercado, liquidez de 21 dias, P/L, P/VP, EV/EBITDA, DL/EBITDA, DY, ROE, ROIC, margens, crescimento, cobertura de juros, custo da divida, idade do balanco | B3 + CVM ITR/DFP | pregao de 09/10 |
| `valuation` | percentil e z-score do P/L, P/VP, EV/EBITDA e DY de hoje contra 5 e 10 anos do proprio papel; premio ou desconto contra a mediana do subsetor | modulo `valuation` | 09/10 |
| `divida` | divida bruta, caixa, liquida, curto prazo, DL/EBITDA, cobertura de juros, custo, % em moeda estrangeira (quando a companhia abre), contra os pares | CVM ITR/DFP | 2T26 |
| `opcoes` | IV no dinheiro (a ultima com data, percentil e media na historia de ate 60 pregoes), posicao em aberto, put/call, dor maxima e paredes do vencimento de referencia, liquidez da cadeia | B3 (boletim) | pregao de 09/10 (IV de 08/10) |
| `fundos` | % das acoes da classe e do free float nos fundos, no de fundos, movimento do mes | CVM (CDA) | carteira de 03/2026 |
| `pares` | pares proximos por correlacao de 126 pregoes, retorno de 12 pregoes do papel contra a media dos pares | historico do terminal | 09/10 |

`tabela()`: uma linha por ticker, 64 colunas (4 de texto e 60 numericas), as mesmas contas da `ficha`. Cobertura medida em 11/10/2026:

| Grupo | Colunas (no de tickers com dado, de 369) |
|---|---|
| Preco e liquidez | `preco` 362, `mcap_rs` 362, `liq_21d_rs` 362 |
| TIR | `tir_pct` 92, `tir_prudente_pct` 92, `tir_premio_pp` 92, `tir_premio_hoje_pp` 92, `ciclo_lucro` 81, `ciclo_razao` 87, `tir_caixa_g0_pct` 71, `tir_caixa_diverge` 91, `tir_casas` 90 |
| Consenso | `consenso_upside_pct` 182, `consenso_alvo_n` 182, `consenso_nota` 124, `consenso_pct_compra` 179, `consenso_lpa_rev_30d_pct` 166, `consenso_lpa_rev_90d_pct` 166, `consenso_lpa_subiram_30d` 171, `consenso_lpa_cortaram_30d` 171, `consenso_pl_proj` 157 |
| Insiders | `insiders_saldo_90d_rs` 351, `insiders_saldo_gestao_90d_rs` 351, `insiders_negocios_90d` 351, `insiders_idade_dias` 351 |
| Aluguel | `aluguel_taxa_aa` 328, `aluguel_pct_float` 219, `aluguel_var_20d_pct` 324, `aluguel_dias_para_cobrir` 328, `aluguel_saldo_rs` 328 |
| Noticias | `noticia_n_7d` 369, `noticia_score_7d` 193, `noticia_max_7d` 193 |
| Calendario | `dias_ate_resultado` 360, `dias_ate_provento_ex` 0 (nenhuma data ex futura no calendario), `reacao_resultado_media_abs_pct` 369 |
| Multiplos e balanco | `pl` 267, `pvp` 325, `ev_ebitda` 281, `div_liq_ebitda` 281, `dy_12m_pct` 362, `roe_pct` 328, `mg_liq_12m_pct` 354, `cresc_lucro_12m_pct` 273, `balanco_idade_dias` 362 |
| Valuation | `pl_pct_5a` 261, `pl_z_5a` 261, `pvp_pct_5a` 319, `ev_ebitda_pct_5a` 274 |
| Divida | `div_cp_pct` 307, `div_cobertura_juros` 228, `div_custo_pct` 222, `div_moeda_estrangeira_pct` 210 |
| Opcoes | `iv_atm_pct` 141, `iv_pctil` 141, `opcoes_pc_oi` 164, `opcoes_dor_maxima_dist_pct` 135 |
| Pares e fundos | `retorno_12d_pct` 369, `retorno_12d_vs_pares_pp` 236, `fundos_pct_classe` 328 |

Leitura honesta da cobertura: a TIR cobre so 92 empresas (as que o modelo consegue projetar); o consenso tem alguma coisa em 182, e em
apenas 160 ha 3 analistas ou mais no alvo; so 28 papeis tem 3 ou mais mudancas de estimativa em 30 dias. Quem constroi regra em cima disso
precisa tratar `NaN` como "sem sinal", nao como neutro.

## 3. Inventario do terminal

Atualizacao: **rapida** = a cada 5 minutos no pregao (9h-19h), 15 minutos nas bordas, 30 minutos no fim de semana; **completa** = uma vez por
dia depois das 20h (e as 9h no fim de semana); **derivativos** = de hora em hora de manha e a noite, a cada 3 horas no resto; **empresa** =
uma vez por dia e de novo depois das 19h. Tudo roda so com o aplicativo do Claude aberto no Mac.

Em cada grupo: o que tem, de quando e, e como o robo pode usar no **swing** de acoes (livro de ate 10 pregoes), nas **opcoes** e no
**mini-dolar** (day trade). Caminhos relativos a `cache/out/`.

### 3.1 Preco e historico

| Arquivo | Campos | De quando | Atualiza |
|---|---|---|---|
| `cotacoes.json` | `q[ticker]`: p, chp, o, h, l, v, pc, hora, estado; 1.504 instrumentos | atraso de 15 min na B3, tempo real nos EUA, moedas, cripto | rapida |
| `hist/<S>.json` | barras diarias de 5 anos: o, h, l, c, `ac` (ajustado a proventos), v, dividendos, desdobramentos; 1.648 arquivos | desde 2021-10 | rapida (ultima barra) e completa |
| `longo/<S>.json` | barras mensais desde o inicio do papel; 1.479 arquivos | historico longo | completa |
| `intradia/<S>.json` | caminho do preco no pregao em passos de 60 s (atraso de 15 min); 393 papeis | pregao do dia | rapida |
| `fita/` e `pagina/fita.json` | hora a hora dos ultimos 20 pregoes (fechamento anterior, abertura, cada hora, fechamento oficial); 410 papeis | 20 pregoes | derivativos (uma vez por dia, depois das 18h30) |
| `pagina/auditoria.json` | confere a tela contra o arquivo oficial de negocios da B3 (652 papeis) | pregao anterior | a noite |

- **Swing**: o robo ja tem o COTAHIST e o MetaTrader; o valor aqui e a comparacao de cruzamento (a tela do terminal contra o arquivo oficial) e
  o historico de BDRs e papeis dos EUA, que o robo nao coleta.
- **Opcoes**: spot e variacao do ativo ao vivo para marcar a posicao simulada.
- **Mini-dolar**: `hist/USDBRL.json`, `hist/DXY...` e as moedas servem de contexto de regime (dolar global, VIX). Em 10/10 o robo testou o
  dolar global em barras de 1 minuto e nao achou o que operar; o uso aqui e so filtro de regime.

### 3.2 Fundamentos oficiais

| Arquivo | Campos | De quando | Atualiza |
|---|---|---|---|
| `contas/<RAIZ>.json` | ITR/DFP da CVM: trimestres, anos, 12 meses, balanco, indicadores, acoes, por acao; anual desde 2010, trimestral desde 2011; 289 empresas | ultimo ITR entregue (2T26) | empresa |
| `cadastro/<RAIZ>.json` | perfil, capital, acionistas, administracao, insiders, proventos, eventos | diario | empresa |
| `multiplos.json` | por ticker (468: 369 acoes e 99 FIIs), 100+ campos: preco do pregao, valor de mercado, EV, P/L, P/VP, EV/EBITDA, DY, margens, ROE/ROIC, divida, cobertura, crescimento, CAGR de 5 anos, retorno de 5 e 10 anos, pesos nos indices, aluguel | pregao de 09/10 | rapida |
| `../multiplos_hist/<T>.json` | P/L, P/VP, EV/EBITDA, DY e valor de mercado em cada fechamento recente (468) | cerca de 27 pregoes | rapida |
| `porativo/valuation/<T>.json` | P/L, P/VP, EV/EBITDA, DY, P/Receita e EV/Receita de fim de mes desde 2011 com o balanco que existia em cada data; percentil e z-score; premio contra o setor; qualidade (Piotroski, DuPont); 541 papeis | pregao de 09/10 | empresa |
| `porativo/divida/<RAIZ>.json` | divida bruta, caixa, liquida, curto prazo, custo, cobertura, composicao, cronograma de vencimentos, emissoes, pares; 289 empresas | 2T26 | empresa |
| `porativo/negocio/<RAIZ>.json`, `segbr/` | Formulario de Referencia: partes relacionadas, controladas, pessoal, auditor, governanca, remuneracao; receita por segmento e regiao, clientes e fornecedores | 2026 | empresa |
| `releases/<RAIZ>.json` | texto dos 8 ultimos releases de resultado (296) | ate 2T26 | empresa (retomavel) |
| `docs/<RAIZ>.json` | documentos da CVM com briefing de uma frase (fatos relevantes, comunicados); 1.104 | dia | rapida e empresa |
| `fund/<S>.json`, `fund_resumo.json` | Fundamentus e Yahoo: grupos, series, dividendos, perfil (1.432) | diario | completa |
| `fii/`, `fii_resumo.json`, `bancos/` | balanco mensal dos FIIs (99); capital e Basileia dos bancos (24) | mes corrente | empresa |

- **Swing**: portoes de qualidade e de divida (`divida_*`, `div_liq_ebitda`, `cobertura_juros`, `custo_divida`), o que o Douglas costuma pedir:
  "custo do dinheiro e moeda da divida", "trajetoria de margem". `liq_21d_rs` limita o tamanho da ordem. `valuation` da o multiplo de hoje
  contra a propria historia (ordenacao de entrada). O robo tem o seu painel point-in-time de fundamentos; o do terminal serve de
  **conferencia cruzada** (mesmo balanco, duas contas) e cobre o que o robo nao tem: FIIs, bancos (Basileia), BDRs.
- **Opcoes**: `lucro_12m`, `dl_ebitda` e `cobertura_juros` para escolher em quais papeis aceitar "ficar com a acao" ao vender put; `releases` para
  o discurso da gestao antes do resultado.
- **Mini-dolar**: nao se aplica diretamente.

### 3.3 TIR real implicita (`pagina/tir.json`)

Por empresa (92): preco, lucro por acao esperado (consenso ou historico), crescimento, payout, ROE, multiplo terminal, custo do capital real
(`k` = NTN-B de 10 anos + 5 pontos), fluxo de 10 anos, **TIR de hoje**, **TIR normalizada** (lucro normal: media real de 5 anos) e **TIR
prudente** (a normalizada quando o lucro esta em pico, nunca acima da de hoje), `ciclo_do_lucro` (nivel, criterios, razoes) e a segunda
leitura por caixa normalizado (`caixa`). Geral: NTN-B de ~10 anos (6,71% em 09/10), Focus, deflator. Recalculada a cada rodada com o preco
do dia. **Hoje: 81 com nivel de ciclo, 50 normais, 15 em pico provavel, 2 em pico possivel, 14 em fundo de lucro.**

- **Swing**: `tir_premio_pp` como filtro de valor com juros reais altos (o premio sobre a NTN-B e o custo de oportunidade); `ciclo_lucro` >= 1 como
  **veto de armadilha** (comprar commodity no pico de lucro); `tir_caixa_diverge` como aviso de modelo duvidoso. Ressalva importante: o
  teste longo da carteira (10/10) mostrou que os portoes fundamentalistas **nao agregaram** e que o retorno veio de estar comprado em bolsa; a TIR
  e uma ideia nova, que entra como informacao ate ter prova viva.
- **Opcoes**: quem vende put "com o objetivo de ficar com o premio" precisa querer a acao: TIR prudente alta, sem pico de lucro, sem
  resultado nos proximos dias e a lista de papeis em que o Douglas aceitaria o exercicio.
- **Mini-dolar**: nao se aplica.

### 3.4 Consenso (`porativo/consenso/<T>.json`)

1.000 registros (369 acoes, 566 EUA, 60 BDR), coleta diaria. Alvo (medio, mediano, minimo, maximo, no), recomendacao (nota, distribuicao
em 4 meses), estimativas de LPA e receita de 4 periodos com revisao e quem subiu e cortou, surpresas dos 4 ultimos resultados com o LPA oficial da
CVM ou da SEC ao lado, historia propria do alvo e do LPA (retratos diarios desde 07/10/2026, sementes desde 18/09), mudancas por casa (so EUA).
BDR aponta o papel la fora. Descartadas pelo terminal: Nasdaq, MarketBeat, Zacks, TradingView (termos). O modelo do Safra saiu em 08/10 por
decisao do Douglas.

- **Swing**: **revisao de lucro** (`consenso_lpa_rev_30d_pct`) e **assimetria** entre `consenso_upside_pct` e `tir_premio_pp`; so vale com 3
  analistas ou mais (o aviso diz). Surpresa de resultado (`sur`) como momento pos-resultado.
- **Opcoes**: tese direcional leve (call spread ou venda de put) quando alvo e revisao apontam para o mesmo lado; `consenso_pl_proj` para
  checar o que o preco ja embute.
- **Mini-dolar**: nao se aplica (para BDRs, ver o lastro).

### 3.5 Posicionamento e fluxo

| Arquivo | Campos | De quando | Atualiza |
|---|---|---|---|
| `porativo/insidersbr/<RAIZ>.json` | negocios de insiders por orgao (controlador, conselho, diretoria, fiscal), com quantidade, preco, intermediario; preco medio de 12 meses; derivativos; tesouraria (recompra e cancelamento); janela de 24 meses; 281 empresas | formulario de agosto/2026 (entregue ate o dia 10 do mes seguinte) | empresa |
| `b3_aluguel.json` | aluguel de acoes por ativo (1.058): saldo em quantidade e reais, taxa media/minima/maxima, contratos, variacoes, % do float, dias para cobrir, serie de 21 pregoes | pregao de 09/10 | derivativos |
| `b3.json` (`fluxo`) | compras, vendas e saldo por tipo de investidor (estrangeiro, institucional, pessoa fisica...) acumulado do mes no mercado de acoes; serie diaria | ate 07/10 (a B3 publica com 2 pregoes de atraso) | derivativos |
| `porativo/quemtem/<T>.json` | fundos que carregam o papel (CDA): no, valor, % da classe e do free float, entradas e saidas, concentracao por gestora; 792 papeis | carteira de 03/2026 (parcial ate 06/2026) | empresa |
| `porativo/secpos/<T>.json` | EUA e BDRs: insiders (Form 4), vendas planejadas (10b5-1), donos de 5% e instituicoes (13F); 627 | trimestre | empresa |
| (fora do terminal) `mesa.py kinea` | carteira mensal dos fundos da Kinea e cartas do gestor, no proprio repositorio do robo | mensal | outro caminho |

- **Swing**: `insiders_saldo_gestao_90d_rs` e exatamente o "bonus de compras de administradores" que o painel `quant_fatores.json` lista como
  "ainda nao ligado"; `aluguel_taxa_aa` e `aluguel_pct_float` sao o "filtro de aluguel" que o mesmo painel diz estar **sem dado desde que o NEFIN
  deixou de publicar a taxa por papel**. Os dois tem a ressalva de ainda nao terem prova. Aluguel alto e subindo e pressao vendida; `dias_para_cobrir`
  alto e risco de aperto; taxa acima de 5% a.a. ocorre em 87 das 328 acoes com saldo.
- **Opcoes**: taxa de aluguel e saldo para escolher call coberta (da para emprestar a acao que ficou na carteira?) e para ler o risco de
  aperto em venda de call descoberta; `fundos_*` para o tamanho do "dono forte" que sustenta o papel.
- **Mini-dolar**: o saldo de estrangeiros no mercado de acoes (`b3.json`) e proxy de apetite a risco, com 2 pregoes de atraso: contexto, nao gatilho.

### 3.6 Noticias (`noticias.json`, `noticias_ativos.json`, `../notas_agente.json`)

1.400 manchetes recentes (janela de 72 horas) com veiculo, hora, licenca, temas, tickers e **nota de "faz preco" de 0 a 3** (a do agente quando
existe, senao uma regra por peso); por ativo, ate 12 manchetes de 120 dias, sem nota. Documentos oficiais do dia (CVM) entram com a hora de
entrega. Atualizacao rapida; as notas do agente chegam por lote.

- **Swing**: `noticia_max_7d` = 3 como **alerta de risco de evento** (revisar a posicao, nao abrir nova); nota 3 de um papel ja na carteira. Sem
  texto integral de materia (licenca de veiculo): so titulo, veiculo, hora e link.
- **Opcoes**: manchete de nota 3 num ativo com venda de put aberta e motivo para revisar; o terminal nao diz o que fazer.
- **Mini-dolar**: manchetes com tema `cambio`, `juros` ou `exterior` e nota 3 (sao "flash"): marcam a hora em que o mercado parou para ler.

### 3.7 Calendario (`pagina/eventos.json`, `pagina/agenda.json`, `pagina/wirp.json`, `macro.json`)

- `eventos.json` (versao 3): 1.042 itens de 27/09 a 10/12: resultados (817), teleconferencias (171), assembleias (34), data ex de proventos
  (18), vencimento de opcoes (2); BR (289 empresas: 232 confirmadas, 47 estimadas, 10 sem data) e EUA (566); fonte da data e hora quando
  existe; `reacoes`: por empresa, a reacao do papel e do Ibovespa no pregao seguinte a cada um dos ultimos 8 resultados, com media e media
  em modulo.
- `agenda.json`: agenda economica (103 eventos entre 27/09 e 25/11): IBGE, BCB, Tesouro, FRED, BEA, Fed; relevancia 1 a 3; efetivo,
  anterior, expectativa so onde existe (Focus); eleicoes 2o turno em 25/10; FOMC em 28/10, 15h.
- `wirp.json`: juro implicito por reuniao do Copom (DI e opcoes de Copom) e do Fed (contratos ZQ): movimento esperado e probabilidade de cada passo.
- `macro.json` (33 indicadores com historico) e `rf.json` (curva de DI, NTN-B, Treasuries, Tesouro, debentures, spreads de credito dos EUA).

- **Swing**: `dias_ate_resultado` e `reacao_resultado_media_abs_pct` para **nao carregar posicao grande atraves do resultado** (a perda esperada
  do gap e a reacao media em modulo, 3,14% na Petrobras). Mes de eleicao: o calendario traz o 2o turno.
- **Opcoes**: nao vender put sobre o resultado sem querer o gap; vencimento mensal (16/10) e semanais ja marcados; `wirp` e DI para o juro do
  modelo de preco (o robo usa 13,65%).
- **Mini-dolar**: **o horario dos dados americanos** (CPI, payroll, PIB, FOMC) vem da `agenda`: e o gatilho do setup "reversao do dado americano".
  Cuidado com o horario de verao dos EUA: o robo troca 9h30 por 10h30, e a agenda do terminal ja traz a hora convertida para Brasilia
  (conferir uma vez por semana). `wirp` do Fed e DXY (`macro.json`, `dolar_amplo`) dao o regime.

### 3.8 Derivativos (`deriv/`)

- `deriv/opcoes/<ativo>.json` (204) e `opcoes_resumo.json`: por ativo e vencimento, **posicao em aberto** de cada serie (OI), variacao de OI, dor
  maxima, paredes de call e put, put/call, **IV no dinheiro**, movimento esperado, cadeia com IV e gregas (delta, gama, vega, theta) de 17 mil
  series (a partir do ultimo negocio ou do premio de referencia da B3, Black-Scholes europeu com o DI interpolado), bid e ask de fechamento,
  historico de 60 pregoes do resumo e das series mais negociadas. B3, pregao de 09/10.
- `deriv/futuros.json` (85 familias): WIN, WDO, DOL, IND, DI1, DAP, DDI, boi, milho, cafe, soja, ouro, S&P, bitcoin...; contratos com ajuste,
  abertura, ultimo, minimo, maximo, negocios, volume, OI e variacao de OI; curva do dia, de ontem, de uma semana e de um mes; estruturas
  (rolagem, FRA, EDS), **opcoes de dolar** (OI por strike), opcoes de IDI e o Copom embutido. `deriv/fut_hist/<RAIZ>.json`: historico por contrato.
- `b3_hoje` / `b3.json`: volume do mercado, negocios, segmentos, participacao de indices, destaques, sinais do boletim.

- **Swing**: OI e paredes dao **niveis de referencia** (imas do vencimento); `opcoes_pc_oi` extremo como leitura de posicionamento.
- **Opcoes**: e a base: `iv_pctil` para vender premio caro ou comprar vol barata (hipotese A1 do robo: vol realizada de 252 dias acima da
  implicita), paredes de put como referencia de strike para venda de put, `liquidez` (ofertas nos dois lados, spread) como portao. O robo ja
  monta a cadeia pelo COTAHIST (sem OI): o terminal **acrescenta OI, dor maxima, paredes e a historia de IV**.
- **Mini-dolar**: `WDO`/`DOL`: ajuste de ontem, maxima e minima de ontem (os niveis do setup de niveis), OI e variacao de OI, **rolagem** (o
  contrato principal e o proximo, com diferencial), cupom cambial (DDI), opcoes de dolar (strikes com muito OI no vencimento).

### 3.9 Pares e risco

`pagina/proximos.json`: pares proximos de cada ativo (correlacao de 126 pregoes, mesmo subsetor primeiro), os 12 ultimos pregoes de cada
ativo e as reacoes de mercado (Ibovespa, IFIX, S&P, VIX, dolar, Brent, ouro, DI e Treasury). 1.233 ativos.

- **Swing**: `retorno_12d_vs_pares_pp` (o papel destoou do grupo?) e o grupo de pares para **limitar concentracao** (o robo tem teto de 25% por
  macrossetor); `setor`/`subsetor` do universo para o mesmo fim.
- **Opcoes**: pares como alternativa quando o papel nao tem opcao liquida.
- **Mini-dolar**: as reacoes de mercado (dolar, VIX, DI, Treasury) em 12 pregoes sao o painel de regime do dia anterior.

### 3.10 Credito privado e cadeia (por completeza; fora do foco do robo)

`porativo/credito/` e `pacote/credito/` (debentures, CRI, CRA: taxas indicativas da ANBIMA e negocios da B3), `porativo/cadeia/` (clientes e
fornecedores pela SEC), `fundos` (informe diario dos fundos). Nao ha uso direto nos tres modulos hoje.

### 3.11 Saude do terminal e o que o robo grava

`pagina/saude.json` (motor ao vivo, fontes, erros), `*_estado.json` (por coletor: quando rodou, cobertura, fontes que falharam). Vale o robo
olhar `terminal.estado()` antes de confiar: se o `status` mostra arquivo ausente ou velho, a ficha ja devolve `None` com o motivo.
`pagina/quant.json`, `quant_fatores.json`, `quant_indice.json`, `quant_opcoes.json`: o que **o robo** escreve para a tela (caminho inverso).

## 4. Como o robo pode decidir melhor, modulo a modulo

Cada linha e uma **hipotese a testar**, nao uma regra pronta. Os campos existem hoje; nenhum foi medido como sinal.

| Modulo | Decisao | Campo do terminal | Pergunta que o dado responde |
|---|---|---|---|
| Swing | entrar | `tir_premio_pp`, `ciclo_lucro`, `pl_pct_5a`, `consenso_lpa_rev_30d_pct` | o papel paga mais que a NTN-B sem estar no pico de lucro e com as estimativas subindo? |
| Swing | vetar | `ciclo_lucro` >= 1, `dias_ate_resultado` <= 3, `noticia_max_7d` = 3, `div_cp_pct`, `div_cobertura_juros` | ha evento, armadilha de lucro ou aperto de divida? |
| Swing | tamanho | `liq_21d_rs`, `reacao_resultado_media_abs_pct`, `aluguel_dias_para_cobrir` | quanto o gap e a liquidez deixam carregar? |
| Swing | sair | `dias_ate_resultado`, `insiders_saldo_gestao_90d_rs` (virou), `aluguel_var_20d_pct` | o que mudou desde a entrada? |
| Opcoes | escolher o papel | `iv_pctil`, `tir_prudente_pct`, `ciclo_lucro`, `dias_ate_resultado` | quero ficar com a acao se for exercido, e o premio esta caro? |
| Opcoes | escolher o strike | `parede_put`, `dor_maxima`, `liquidez` | onde esta o suporte de posicao em aberto e a serie tem negocio? |
| Opcoes | custo | `aluguel_taxa_aa` | da para cobrir a call? |
| Mini-dolar | quando operar | `eventos(tipos=["macro"], pais="US")` (hora e relevancia), `wirp` | qual e a hora do dado e o que o Fed esta precificando? |
| Mini-dolar | regime | VIX, DXY, UST10Y (`macro.json`), reacoes de 12 pregoes (`proximos.json`) | o dia anterior foi de risco ou de calma? |
| Mini-dolar | niveis | `futuros.json` (WDO/DOL: ajuste, maxima e minima de ontem, OI) | onde estao os niveis e quando rola o contrato? |

## 5. O banco historico (para o robo aprender com o terminal)

Hoje os indicadores derivados sao sobrescritos a cada rodada. O terminal ganhou o banco `cache/banco/terminal.sqlite`
(`python -m coletor.banco --gravar`, uma vez por dia; documentacao em `~/Desktop/terminal-artefato/BANCO.md`). 17 tabelas:

| Tabela | O que guarda | `data` e | Passado ja aproveitado |
|---|---|---|---|
| `tir`, `tir_geral` | TIR por empresa e premissas do dia | dia do retrato | nenhum (comeca em 11/10/2026) |
| `consenso` | alvo, recomendacao, LPA e revisoes por papel | dia do retrato | desde 18/09/2026 (alvo, nota, % compra), LPA desde julho |
| `aluguel` | saldo, taxa, variacoes | pregao | 21 pregoes (so quantidade) |
| `multiplos` | multiplos do pregao | pregao | cerca de 27 pregoes |
| `valuation_mensal` | P/L, P/VP, EV/EBITDA, DY... de fim de mes | fim do mes | **desde 2011-01, 541 papeis (ponto no tempo)** |
| `opcoes_ativo`, `opcoes_venc` | IV no dinheiro, OI, put/call; por vencimento: dor maxima e paredes | pregao | 60 pregoes (IV, OI) |
| `noticias_ativo` | manchetes e nota por ativo e dia | dia da noticia | ate 120 dias (contagem; nota so onde o agente pontuou) |
| `macro`, `macro_focus`, `curva`, `wirp` | indicadores, Focus, DI/NTN-B/UST, juro implicito | dia do retrato ou da curva | nenhum |
| `eventos`, `agenda_macro` | o calendario como o terminal o conhecia no dia (as datas mudam) | dia do retrato | nenhum |
| `robo_painel`, `robo_item` | resumo do dia e itens (operacoes, sinais, posicoes, ordens, decisoes) de cada modulo do robo | dia do retrato | resultado e patrimonio desde 08/10/2026 |

`terminal.historico("tir", "PETR4", desde="2026-10-01")` le qualquer uma. A coluna `origem` separa `retrato` (o que o terminal mostrava naquele
dia) de `hist` (reconstruido depois): para medir um sinal, **use so `retrato`** quando houver, porque `hist` pode ter sido refeito com dado
de depois.

O que isso destrava: (a) o robo pode gravar o sinal de cada dia junto com a ficha daquele dia (`robo_item`) e **medir sem olhar o futuro**;
(b) a serie de revisoes de LPA e de TIR se forma com o tempo; (c) a agenda macro guarda o `efetivo` junto com o `anterior`, formando a serie de
surpresas.

## 6. Como fazer os campos virarem decisao sem se enganar

O metodo do robo (Chan e Lopez de Prado, `quant/pesquisa/METODO.md`) vale para o que vem do terminal:

1. escrever a hipotese **antes** (por exemplo, "papeis com `tir_premio_pp` acima de X e `ciclo_lucro` <= 0 tem retorno de 10 pregoes maior que o
   resto do livro"), com o criterio de aprovacao;
2. testar so com dado que o banco guardou com a data certa (`origem = 'retrato'`) ou com o que o terminal reconstroi ponto no tempo
   (`valuation_mensal`);
3. descontar o numero de tentativas (Sharpe deflacionado) e olhar o custo (0,11% por ordem em acoes);
4. o periodo 2016-2026 da carteira **nao pode ser reaberto**: o que vier do terminal entra pela prova viva (simulacao com pregoes novos);
5. enquanto nao passar, o campo entra na tela como **informacao** (a ficha), nao como gatilho.

Atalho util: gravar em `robo_item` (tipo `sinal`) o que cada hipotese teria feito no dia, e medir o resultado depois. O banco ja aceita.

## 7. O que falta no terminal para o robo decidir melhor (priorizado)

O Douglas pediu: "o que voce sentir que falta, voce implementa ou pede para eu implementar". Lista em ordem de valor para a decisao:

| # | Lacuna | Por que pesa | Evidencia (11/10/2026) | Quem faz | Esforco |
|---|---|---|---|---|---|
| 1 | **Profundidade historica dos sinais do terminal.** TIR, eventos, macro, curva e Selic implicita nunca foram guardados; o consenso proprio comeca em 07/10 (sementes de 18/09); o aluguel tem 21 pregoes; as notas de noticia, 6 dias. | sem passado nao ha teste: toda regra com dado do terminal so tem prova viva, que leva meses | `--status` do banco: tir/macro/curva/wirp/eventos com 1 dia | **ja resolvido para frente** (banco + linha no `atualizar.sh`); para tras, **reconstruir a TIR normalizada e a por caixa ponto no tempo** (contas da CVM + preco, desde 2012, como o modulo valuation fez com o P/L) so se o terminal pedir | rodar o banco: 1 linha; reconstrucao: medio |
| 2 | **Opcoes: IV do pregao incompleta quando o arquivo de negocios da B3 vem sem opcao, e sem sorriso guardado.** Em 09/10 so 53 de 203 ativos tem IV no dinheiro do dia (155 a 161 nos quatro dias anteriores) e 137 de 204 ficaram com volume de opcao zero (provavel arquivo da B3 servido incompleto, a armadilha ja registrada no day trade); a cadeia nao guarda o sorriso (inclinacao, estrutura a termo) por dia. | o robo vende put e compra vol com base em IV; sem ela cai para o premio de referencia | `deriv/opcoes/*.json`, `hist.iv_atm`; `resumo.vol_call = vol_put = 0` em 137 ativos em 09/10 | terminal | baixo: marcar o dia como incompleto e refazer o download quando o arquivo vier curto (o mesmo cuidado que ja existe no day trade); medio: guardar IV por strike ao longo dos dias |
| 3 | **Mini-dolar: sem a expectativa (consenso) dos dados americanos.** O setup aprovado reage ao movimento dos 2 primeiros minutos depois do dado; o terminal declara que nao existe fonte gratuita do consenso dos EUA, entao `expectativa` e vazia para CPI, payroll, PIB. | nao da para medir se a reversao e maior quando a **surpresa** e grande, que e a hipotese natural do setup | `agenda.json`, lista `lacunas` ("Consenso de mercado dos EUA") | **Douglas** (se tem acesso a uma tabela semanal de consenso, o terminal passa a ler de um arquivo seu) ou fonte permitida | baixo se vier por arquivo; indefinido se for coleta |
| 4 | **Calendario de resultados sem hora de divulgacao e com data estimada.** Das 289 empresas, 47 tem data so estimada e 10 sem data; **nenhum** dos 281 resultados BR futuros traz a hora (antes ou depois do pregao); nao ha data ex futura. | no swing de ate 10 pregoes, o gap e no mesmo dia ou na abertura seguinte? muda o risco e a hora de zerar | `eventos.json`: `hora` nula em 281 de 281 | terminal | baixo: o terminal ja tem 2.582 entregas passadas com hora (RAD): inferir o "momento tipico" de cada empresa (pre, durante, pos-pregao) e marcar |
| 5 | **Consenso do Brasil raso e sem mudanca por casa.** Alguma cobertura em 240 das 369 acoes (alvo em 182), alvo de 3 analistas ou mais em 160, e so 28 papeis com 3 ou mais mudancas de estimativa em 30 dias (PETR4 tem LPA de **uma** casa); "mudancas por casa" so existe nos EUA; o modelo do Safra saiu em 08/10. | a revisao de lucro e o sinal mais citado nos gestores de referencia e hoje e ruido no Brasil | `consenso_estado.json` (`mud` = 0 para `acao_br`) | terminal (extrair das manchetes que ja coleta: "BTG eleva recomendacao", preco-alvo e casa) ou Douglas (relatorios que ele recebe) | medio, com precisao moderada |

Outras lacunas, em ordem:

6. **Guidance e numeros do release estruturados.** `releases/` tem o texto de 8 trimestres, mas a comparacao "gestao prometeu x entregou" e manual.
7. **Beta, volatilidade e matriz de correlacao prontos** (o robo calcula do banco de precos; seria so para cruzar com `proximos.json`).
8. **Fluxo estrangeiro por papel** e **posicao por tipo de investidor em futuros de dolar e indice** (a B3 publica agregados; nao ha fonte gratuita por papel).
9. **Taxa de aluguel intradiaria e contratos novos por dia**: o terminal tem o fechamento do dia e 21 pregoes; o banco passa a acumular o resto.
10. **Cobertura da TIR**: 92 empresas; as 277 restantes ficam sem numero (muitas sem consenso e sem 3 anos de dividendos). Um modo "sem consenso" com a media historica de lucro cobriria mais.
11. **Data ex de provento futura**: nenhuma no calendario (as 18 do arquivo sao todas passadas). Vale conferir se a fonte (B3) so publica depois da aprovacao ou se o coletor esta filtrando.

Nada disso foi feito neste pedido alem das duas entregas (leitor no robo e banco no terminal); os itens 2 e 4 sao pequenos e podem ser a proxima
rodada no terminal. Os itens 1 e 3 dependem de decisao do Douglas.
