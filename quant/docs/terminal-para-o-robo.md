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
f["proximo_resultado"]["proximo"]["antes_da_abertura"] # True | False | None: o resultado sai antes da abertura? (estimativa, com confianca)
f["motivos"]                                           # por que cada pedaco ausente esta ausente
df = terminal.tabela(["PETR4", "VALE3"])               # DataFrame, 1 linha por ticker, 68 colunas estaveis
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

## 2. O que a `ficha` e a `tabela` devolvem hoje (12/10/2026, 369 acoes da B3)

`ficha`: doze pedacos. Para PETR4 e DIRR3, todos os 12 tem dado; para BBAS3, 11 (banco nao tem painel de divida: o motivo vem dito).

| Pedaco | O que traz | Fonte | Dado de |
|---|---|---|---|
| `tir` | TIR de hoje, normalizada e prudente; premio sobre a NTN-B; `ciclo_do_lucro` (pico, fundo, criterios e razoes); base (consenso ou historico) e no de casas; premissas; segunda leitura por caixa | modulo `tir` | preco de 09/10 |
| `consenso` | alvo (medio, mediano, faixa, no de analistas, potencial); recomendacao (nota 1 a 5, % compra e ha 3 meses); LPA do trimestre, do ano e do ano seguinte com revisao em 7/30/60/90 dias e quem subiu e cortou; evolucao do alvo desde o primeiro retrato | Yahoo (agregador) | coleta de 10/10 |
| `insiders` | saldo de compras menos vendas em reais na janela de 90 dias, por orgao (controlador, conselho, diretoria...); saldo so de administradores; no de negocios; mes do formulario | CVM (Res. 44, art. 11) | formulario de agosto/2026 (entregue em 10/09) |
| `aluguel` | taxa do tomador (media, minima, maxima), saldo em quantidade e em reais, variacao em 1/5/20 dias, % do float, dias para cobrir, saldo contra a media de 21 pregoes | B3 BDI | pregao de 09/10 |
| `noticias` | manchetes dos ultimos 7 dias: contagem, soma e maior nota 0-3 de "faz preco", as 5 principais com fonte e hora | veiculos + agente | 11/10 |
| `proximo_resultado` | data, periodo, confirmado ou estimado, dias ate; **momento estimado (antes da abertura, durante, apos o fechamento), confianca e `antes_da_abertura`**; teleconferencia; reacao media historica do papel no pregao apos o resultado; outros eventos do papel (data ex, assembleia) | CVM, RAD, Yahoo | 11/10 |
| `multiplos` | preco, valor de mercado, liquidez de 21 dias, P/L, P/VP, EV/EBITDA, DL/EBITDA, DY, ROE, ROIC, margens, crescimento, cobertura de juros, custo da divida, idade do balanco | B3 + CVM ITR/DFP | pregao de 09/10 |
| `valuation` | percentil e z-score do P/L, P/VP, EV/EBITDA e DY de hoje contra 5 e 10 anos do proprio papel; premio ou desconto contra a mediana do subsetor | modulo `valuation` | 09/10 |
| `divida` | divida bruta, caixa, liquida, curto prazo, DL/EBITDA, cobertura de juros, custo, % em moeda estrangeira (quando a companhia abre), contra os pares | CVM ITR/DFP | 2T26 |
| `opcoes` | IV no dinheiro (a ultima com data, percentil e media na historia de ate 60 pregoes), posicao em aberto, put/call, dor maxima e paredes do vencimento de referencia, sorriso (IV no dinheiro e ~10% abaixo e acima, skew), liquidez da cadeia, e qual pregao e o ultimo COMPLETO (e o incompleto mais recente, se houver) | B3 (boletim) | pregao completo de 08/10 (o de 09/10 veio incompleto da B3) |
| `fundos` | % das acoes da classe e do free float nos fundos, no de fundos, movimento do mes | CVM (CDA) | carteira de 03/2026 |
| `pares` | pares proximos por correlacao de 126 pregoes, retorno de 12 pregoes do papel contra a media dos pares | historico do terminal | 09/10 |

`tabela()`: uma linha por ticker, 68 colunas (4 de texto e 64 numericas), as mesmas contas da `ficha`. As 4 ultimas colunas (momento do resultado, sorriso e pregao incompleto) entraram em 12/10/2026, sempre no fim: a ordem das anteriores nao muda. Cobertura medida em 12/10/2026:

| Grupo | Colunas (no de tickers com dado, de 369) |
|---|---|
| Preco e liquidez | `preco` 362, `mcap_rs` 362, `liq_21d_rs` 362 |
| TIR | `tir_pct` 92, `tir_prudente_pct` 92, `tir_premio_pp` 92, `tir_premio_hoje_pp` 92, `ciclo_lucro` 83, `ciclo_razao` 87, `tir_caixa_g0_pct` 71, `tir_caixa_diverge` 91, `tir_casas` 90 |
| Consenso | `consenso_upside_pct` 182, `consenso_alvo_n` 182, `consenso_nota` 124, `consenso_pct_compra` 179, `consenso_lpa_rev_30d_pct` 166, `consenso_lpa_rev_90d_pct` 166, `consenso_lpa_subiram_30d` 171, `consenso_lpa_cortaram_30d` 171, `consenso_pl_proj` 157 |
| Insiders | `insiders_saldo_90d_rs` 351, `insiders_saldo_gestao_90d_rs` 351, `insiders_negocios_90d` 351, `insiders_idade_dias` 351 |
| Aluguel | `aluguel_taxa_aa` 328, `aluguel_pct_float` 219, `aluguel_var_20d_pct` 324, `aluguel_dias_para_cobrir` 328, `aluguel_saldo_rs` 328 |
| Noticias | `noticia_n_7d` 369, `noticia_score_7d` 192, `noticia_max_7d` 192 |
| Calendario | `dias_ate_resultado` 360, `dias_ate_provento_ex` 0, `reacao_resultado_media_abs_pct` 369, `resultado_antes_da_abertura` 347, `resultado_momento_confianca` 357 |
| Multiplos e balanco | `pl` 267, `pvp` 325, `ev_ebitda` 281, `div_liq_ebitda` 281, `dy_12m_pct` 362, `roe_pct` 328, `mg_liq_12m_pct` 354, `cresc_lucro_12m_pct` 273, `balanco_idade_dias` 362 |
| Valuation | `pl_pct_5a` 261, `pl_z_5a` 261, `pvp_pct_5a` 319, `ev_ebitda_pct_5a` 274 |
| Divida | `div_cp_pct` 307, `div_cobertura_juros` 228, `div_custo_pct` 222, `div_moeda_estrangeira_pct` 210 |
| Opcoes | `iv_atm_pct` 138, `iv_pctil` 138, `iv_skew_10_pp` 76, `opcoes_pc_oi` 164, `opcoes_dor_maxima_dist_pct` 150, `opcoes_pregao_incompleto` 165 |
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
  em modulo. **Desde 12/10/2026** cada resultado futuro traz `momento_estimado` (antes da abertura, durante o pregao, apos o fechamento),
  `momento_confianca` (iguais / entregas com hora entre as ultimas 8) e `momento_origem`: e ESTIMATIVA pelas 2.582 entregas passadas com hora
  (ou o que a companhia informou em comunicado, confianca 1). Conferido fora da amostra: a regra sem a entrega mais recente acerta o momento
  dela em 268 de 288 companhias (93%). Cobertura: 280 dos 281 resultados BR futuros (antes: 224 com `costuma` ou `quando`). No robo:
  `proximo_resultado.proximo.antes_da_abertura` (True/False; None com confianca abaixo de 0,6) e a coluna `resultado_antes_da_abertura`.
  **Data ex futura**: a fonte e que nao tem (a B3 so lista o provento depois da aprovacao; a aprovacao mais recente no cadastro e de 30/09 e a data
  com mais recente, 08/10; o coletor nao filtra nada): `terminal.eventos().avisos` repete a nota.
- `agenda.json`: agenda economica (103 eventos entre 27/09 e 25/11): IBGE, BCB, Tesouro, FRED, BEA, Fed; relevancia 1 a 3; efetivo,
  anterior, expectativa so onde existe (Focus; **EUA: so se o Douglas digitar o consenso em `cache/manual/consenso_eua.csv`, formato no proprio
  arquivo; vem rotulado `manual`**); com expectativa e efetivo, o evento ganha `surpresa` (efetivo menos expectativa); eleicoes 2o turno em
  25/10; FOMC em 28/10, 15h.
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
  historico de 60 pregoes do resumo e das series mais negociadas. B3. **Pregao incompleto (12/10/2026)**: quando a B3 serve o arquivo de negocios
  pela metade (o de 09/10 veio com 41% das linhas de opcao), o coletor nao o promove: o resumo e os arquivos por ativo ficam com o ultimo pregao
  COMPLETO (hoje 08/10) e o resumo ganha `incompleto` {data, motivo, tentativas}; a cada 25 minutos o arquivo e pedido de novo (ate 16 vezes). A
  ficha mostra `pregao_completo` e `pregao_incompleto_mais_recente`, e a cadeia ganhou o **sorriso**: `sorriso_do_vencimento_de_referencia` (IV no
  dinheiro e a ~10% abaixo e acima do preco, com o skew), so com strike observado perto.
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
(`python -m coletor.banco --gravar`, uma vez por dia; documentacao em `~/Desktop/terminal-artefato/BANCO.md`). 18 tabelas:

| Tabela | O que guarda | `data` e | Passado ja aproveitado |
|---|---|---|---|
| `tir`, `tir_geral` | TIR por empresa e premissas do dia | dia do retrato (e fim de mes na reconstrucao) | **reconstruida mes a mes (principal, normalizada e por caixa), 92 papeis, 2013-01 a 2026-10, `origem = 'reconstruida'`**; o retrato com consenso comeca em 11/10/2026; colunas canonicas `tir_principal_*` (v3) |
| `consenso` | alvo, recomendacao, LPA e revisoes por papel | dia do retrato | desde 18/09/2026 (alvo, nota, % compra), LPA desde julho |
| `aluguel` | saldo, taxa, variacoes | pregao | 21 pregoes (so quantidade) |
| `multiplos` | multiplos do pregao | pregao | cerca de 27 pregoes |
| `valuation_mensal` | P/L, P/VP, EV/EBITDA, DY... de fim de mes | fim do mes | **desde 2011-01, 541 papeis (ponto no tempo)** |
| `opcoes_ativo`, `opcoes_venc` | IV no dinheiro, OI, put/call; por vencimento: dor maxima e paredes; `incompleto` marca pregao que a B3 serviu pela metade | pregao COMPLETO | 60 pregoes (IV, OI) |
| `opcoes_sorriso` | volatilidade implicita por faixa de distancia do strike ao preco, por ativo e vencimento (so strike observado) | pregao completo | nenhum (comeca em 12/10/2026) |
| `noticias_ativo` | manchetes e nota por ativo e dia | dia da noticia | ate 120 dias (contagem; nota so onde o agente pontuou) |
| `macro`, `macro_focus`, `curva`, `wirp` | indicadores, Focus, DI/NTN-B/UST, juro implicito | dia do retrato ou da curva | nenhum |
| `eventos`, `agenda_macro` | o calendario como o terminal o conhecia no dia (as datas mudam) | dia do retrato | nenhum |
| `robo_painel`, `robo_item` | resumo do dia e itens (operacoes, sinais, posicoes, ordens, decisoes) de cada modulo do robo | dia do retrato | resultado e patrimonio desde 08/10/2026 |

**TIR no banco (esquema v3, 12/10/2026): use as colunas canonicas.** O numero principal da tela passou a ser o terminal endogeno (a conta V5a da auditoria da TIR:
depois do ano 10 o lucro e capitalizado a propria taxa). Em `terminal.historico("tir", ...)` as colunas **canonicas** vem logo depois de `data` e `ticker`:

| Coluna | O que e |
|---|---|
| `tir_principal_pct` | TIR real de hoje (lucro corrente ou consenso), pelo terminal endogeno, em pontos |
| `tir_principal_norm_pct` | a mesma com o lucro normalizado |
| `tir_principal_prudente_pct`, `tir_principal_base` | a TIR prudente da tela (a menor entre a de hoje e a normalizada em pico ou virada) e qual das duas foi (`hoje` ou `normalizada`) |
| `premio_principal_pp` | prudente menos a NTN-B de ~10 anos, em pontos |
| `conta` | com qual definicao o `tir_prudente_pct` LEGADO da linha foi calculado: `endogena` ou `menor_das_duas` |

`tir_hoje_pct`, `tir_normalizada_pct`, `tir_pl_pct`, `tir_perp_pct`, `tir_prudente_pct`, `tir_prudente_base`, `premio_pp` e `premio_hoje_pp` sao **LEGADO**: a conta
antiga, a menor entre a saida por P/L e a por perpetuidade (NTN-B + 5 pontos), que subestimava (mediana 3,4 pontos ao ano na auditoria). Ficam na tabela e nao sao
apagadas, mas as 12.230 linhas `reconstruida` foram gravadas pela conta antiga (`conta = 'menor_das_duas'`) e a mediana do `tir_prudente_pct` antigo fica cerca de
5 pontos abaixo da canonica na mesma linha: **uma serie com `tir_prudente_pct` mistura definicoes quando cruza linhas de contas diferentes**. As colunas `tir_principal_*`
sao sempre a conta endogena (as linhas antigas ganharam as canonicas recalculadas ponto no tempo, sem consenso); e nelas que a serie nao mistura. `.attrs` do DataFrame traz
`canonicas`, `legado` e `nota`. Banco ainda no esquema anterior: `.attrs['motivo']` manda rodar `python -m coletor.banco --preencher --so tir` no terminal.
`terminal.tabela()` e a ficha nao mudam de nome: `tir_prudente_pct` ali e a da tela, ao vivo.

`terminal.historico("tir", "PETR4", desde="2013-01-01")` le qualquer uma. A coluna `origem` separa `retrato` (o que o terminal mostrava naquele
dia), `hist` (reconstruido depois de um historico que o terminal tinha) e `reconstruida` (so na `tir`). Para medir um sinal, **use `retrato` quando
houver**, porque `hist` pode ter sido refeito com dado de depois. A `reconstruida` e a excecao feita de proposito: ponto no tempo de verdade (balanco
so depois da entrega, IPCA publicado, preco do mes), testado contra olhar o futuro, mas SEM consenso: a TIR normalizada e a por caixa
(`caixa_tir_g0_pct`, `ciclo_nivel` e a TIR principal normalizada, `tir_principal_norm_pct`) sao as comparaveis com as de hoje; `tir_principal_pct` e
`tir_principal_prudente_pct` dessa origem usam o historico de lucro em vez da estimativa dos analistas e **nao se misturam** com as do `retrato`.
Conferencia com o modelo ao vivo no ultimo mes:
a leitura por caixa bate dentro de 0,3 ponto em 67 de 67 papeis; o nivel do ciclo do lucro, em 90 de 92. O periodo 2016-2026 da carteira continua fechado:
a TIR reconstruida serve a ideias novas medidas daqui para a frente ou na janela de desenvolvimento, nao para reabrir o teste longo.

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

## 7. O que falta no terminal para o robo decidir melhor (priorizado, estado de 12/10/2026)

O Douglas pediu: "o que voce sentir que falta, voce implementa ou pede para eu implementar". Em 11/10 saiu a lista abaixo; em 12/10 as lacunas 1, 2, 3 e
4 e a 11 foram atacadas. Estado de cada uma:

| # | Lacuna | Estado em 12/10/2026 | O que sobra |
|---|---|---|---|
| 1 | **Profundidade historica dos sinais.** TIR, eventos, macro e curva nunca foram guardados. | **Parcial.** Banco com retrato diario (linha no `atualizar.sh`) + **TIR normalizada e por caixa reconstruidas mes a mes** (92 papeis, 2013-01 a 2026-10, 12.230 linhas; ponto no tempo, sem consenso; conferida contra o modelo ao vivo). | O consenso, os eventos, o macro e a curva so tem historia daqui para a frente. A TIR com consenso nao se reconstroi: o consenso do passado nao foi guardado. |
| 2 | **Opcoes: pregao incompleto da B3 e sorriso.** Em 09/10 so 53 de 203 ativos com IV (155 a 161 nos dias vizinhos). | **Feito.** O pregao incompleto nao e promovido: vale o ultimo completo (hoje 08/10, 155 ativos com IV), com `incompleto` e o motivo no resumo; novo pedido a cada 25 minutos, ate 16. A ficha diz qual pregao e o completo e qual ficou de fora. Sorriso por faixa de distancia do strike guardado no banco (`opcoes_sorriso`, ~7 mil linhas por pregao, a partir de 12/10). | Sorriso sem passado. O arquivo de 09/10 continua curto na B3 (tentativa 1 devolveu o mesmo): a B3 pode nunca completa-lo. |
| 3 | **Mini-dolar: expectativa dos dados americanos.** | **Sem fonte limpa; caminho manual pronto.** Pesquisa de fontes publicas sem login: investing.com (robots 403), FXStreet (robots proibe o calendario), MarketWatch e Yahoo (Disallow /), Atlanta Fed (Disallow /; e modelo), Nasdaq (termos proibem), Finviz, Trading Economics, Forex Factory e Econoday (termos ilegiveis por robo ou consenso pago), Cleveland Fed (nowcast e modelo, nao consenso; sem arquivo de dados). Nada foi forcado. O terminal le `cache/manual/consenso_eua.csv` (formato no proprio arquivo, que ja esta la, vazio) e aplica a expectativa por (dia, indicador), rotulada `manual`; o evento ganha `surpresa`. | **Douglas**: alguem tem de digitar (ou colar de Bloomberg/Reuters) o consenso de CPI, nucleo, payroll, PIB, PCE, PPI e pedidos de seguro-desemprego. Vendas no varejo dos EUA nem estao na agenda do terminal (a agenda traz so o varejo do IBGE). |
| 4 | **Calendario de resultados sem hora.** | **Feito (estimativa).** `momento_estimado` e `momento_confianca` em 280 dos 281 resultados BR futuros (93% de acerto fora da amostra); `antes_da_abertura` na ficha e `resultado_antes_da_abertura` na tabela. | A hora exata continua desconhecida (so antes/durante/depois); as 47 datas estimadas ainda sao estimativa. |
| 5 | **Consenso do Brasil raso e sem mudanca por casa.** Alguma cobertura em 240 das 369 acoes (alvo em 182), alvo de 3 analistas ou mais em 160, 28 papeis com 3 ou mais mudancas de estimativa em 30 dias. | Nao atacada (precisa de fonte nova; o Safra saiu em 08/10). | Extrair das manchetes ja coletadas ("BTG eleva recomendacao") ou relatorios que o Douglas recebe. |

Outras lacunas, em ordem:

6. **Guidance e numeros do release estruturados.** `releases/` tem o texto de 8 trimestres, mas a comparacao "gestao prometeu x entregou" e manual.
7. **Beta, volatilidade e matriz de correlacao prontos** (o robo calcula do banco de precos; seria so para cruzar com `proximos.json`).
8. **Fluxo estrangeiro por papel** e **posicao por tipo de investidor em futuros de dolar e indice** (a B3 publica agregados; nao ha fonte gratuita por papel).
9. **Taxa de aluguel intradiaria e contratos novos por dia**: o terminal tem o fechamento do dia e 21 pregoes; o banco passa a acumular o resto.
10. **Cobertura da TIR**: 92 empresas; as 277 restantes ficam sem numero (muitas sem consenso e sem 3 anos de dividendos).
11. **Data ex de provento futura**: **era a fonte, nao o coletor.** Conferido direto no servico da B3 (GetListedSupplementCompany e GetListedCashDividends) para Itau, BB, Vale, ISA e
    Petrobras: a B3 so lista o provento depois da aprovacao pela companhia; a aprovacao mais recente em todo o cadastro e de 30/09/2026 e a data com mais recente, 08/10.
    Parcela mensal ja aprovada de uma vez (JCP mensal do Itau, aprovado em 09/12/2025) so aparece quando a B3 a lista (a B3 mostra ate a de 30/09). O arquivo de eventos
    traz a nota em `fontes.proventos.nota`, e `terminal.eventos().avisos` a repete. Nada a consertar.
12. **Estado normal da manha do cadastro de opcoes** (descoberto em 12/10): quando o resumo fica com `data` igual a `data_posicao` (o estado de toda manha depois das 8h), 3 series
    de PETR* (87 mil contratos) tem posicao em aberto no fechamento mas nao estao no cadastro do proprio dia (entram no do dia seguinte); o total do ativo as conta e a soma por
    vencimento nao. E anterior a esta rodada, aparece em `ferramentas/teste_opcoes.py` (23 conferencias de posicao) e nao muda o que o robo le (a ficha usa o total).
