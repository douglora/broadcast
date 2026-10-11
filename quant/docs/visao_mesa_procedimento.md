# Procedimento: refazer a visão da mesa toda semana (livro de swing de 10 pregões)

Para quem executa: uma rotina noturna em Sonnet, sem acesso à conversa em que este procedimento nasceu (11/10/2026). Tudo o que precisa está aqui, nos arquivos
de `quant/saida/mesa/ferramentas/` e nos modelos desta pasta. Tempo esperado: 60 a 90 minutos de relógio com subagentes em paralelo; cerca de 3 horas em sequência.

## 0. O que sai, para quem, e o que não é

- **Saída:** `quant/saida/mesa/visao_mesa.json` (lido por `quant/mesa.py`) e `quant/saida/mesa/visao_mesa.md` (leitura no celular do Douglas, assessor de investimentos).
- **Quem lê o JSON:** `quant/mesa.py` (`ler`, `vetar`, `fatores_de_peso`). Ele usa só: `gerado`, `validade_dias`, `macro`, `setores[].setor` e `.inclinacao`, `acoes[].ticker`, `.conviccao`, `.tese`, `.risco`,
  `.o_que_o_preco_exige`, `.margem`, `.evento_binario`, `sem_analise`, `avisos`. Os campos de swing (abaixo) são extras e não quebram nada.
- **O efeito no robô:** conviccao **-2 = VETO** (o papel sai da seleção); cada ponto de convicção mexe 15% no peso e cada ponto de inclinação do setor 5%. Visão mais velha que `validade_dias` não muda nada.
  Por isso: **-2 e +2 são raros, caros e só com análise a fundo.**
- **O que NÃO é:** recomendação. Nunca escreva "compre" ou "venda". A convicção é leitura interna para a simulação (Resolução CVM 178: a recomendação é do Douglas).
- **Mandato de 11/10/2026:** o módulo de ações virou livro de swing curto (posição de no máximo 10 pregões) e o robô tem de "pensar como gestor de fundo": **macro primeiro**, depois o papel;
  referência de pensamento macro: a Kinea (Ruy Alves e Marco Freire).

## 1. Convenções e pastas

```
MESA   = "/Users/douglaslora/agene analista "          # repositório da mesa. ATENÇÃO: o nome tem um ESPAÇO NO FIM; use sempre aspas
QUANT  = /Users/douglaslora/Desktop/quant-b3/quant
SAIDA  = $QUANT/saida/mesa
FERR   = $SAIDA/ferramentas                             # scripts desta rotina
PARTES = $SAIDA/partes                                  # insumos e lotes intermediários
```

- Python: `python3` dentro de `$MESA` é o do `.venv` (3.12). Para ler `quant/banco/*.parquet` use `/Users/douglaslora/Desktop/quant-b3/.venv/bin/python3` (tem pyarrow).
- Internet aberta (modo local). Coleta de dados SEMPRE com `--so-local` (não dispara workflow no GitHub; a regra do Douglas é não mexer na `main` nem no branch `dados`).
- **Proibido:** apagar arquivo (há trava contra `rm`), `git commit/push/reset`, disparar workflow, editar código de `quant/` ou da mesa. Escreva só em `$SAIDA` (e `$MESA/dados_local/`, onde o coletor grava) e neste doc.
- `sleep` do shell é bloqueado: espere com `python3 -c "import time; time.sleep(45)"`.
- Antes de sobrescrever `visao_mesa.json`, **arquive** a anterior: `cp -n $SAIDA/visao_mesa.json $SAIDA/arquivo/visao_mesa_AAAA-MM-DD.json` (e o `.md`). Nada é apagado.

## 2. Regras de ferro da mesa (valem para todo número)

1. `cd $MESA && python3 mesa.py skills` primeiro; tem de terminar com **TUDO OPERANDO**. Skill faltando ou inválida vira a primeira linha de `avisos`.
2. Fonte oficial (CVM, RI, B3, BCB) vence agregador (Yahoo, Fundamentus). Busca na web é **contexto rotulado** (veículo e data), nunca a base de um número que existe em fonte oficial.
3. Número só com fonte e data. Lacuna é declarada, nunca preenchida com palpite: o trimestre que falta vai **pelo nome** no campo `cobertura`.
4. Frescor **e** cobertura antes de escrever (`mesa.py frescor T`, `mesa.py cobertura T`). Só `frescor` ATUAL **e** `cobertura` COMPLETA autorizam número sem ressalva.
5. Se o Douglas (ou o coordenador) apontou um erro, conserte a causa na ferramenta ou neste procedimento, não só o ticker da vez.
6. Português do Brasil, acentuação normal, números no formato brasileiro nos textos (vírgula decimal), R$ milhões salvo aviso, sigla explicada na primeira vez.

## 3. Passo a passo

### 3.1 Janela dos 10 pregões
```
python3 $FERR/janela.py                       # começa no próximo pregão depois de hoje, pula fins de semana e feriados da B3 (config/calendario.yaml do MESA)
python3 $FERR/janela.py --de AAAA-MM-DD --json
```
Anote `inicio` e `fim`. Em 11/10/2026: 13/10 a 26/10 (12/10 é feriado). O **10º pregão é o dia seguinte ao evento de fim de janela** (2º turno de domingo 25/10 → reação em 26/10).
Posição aberta antes do evento o atravessa: isso é decisão do macro, não do papel.

### 3.2 Universo
```
cp -n $SAIDA/visao_mesa.json $SAIDA/arquivo/visao_mesa_$(date +%F).json
python3 $FERR/universo_swing.py --n 50 --anterior $SAIDA/arquivo/visao_mesa_AAAA-MM-DD.json
```
Resultado em `$PARTES/universo_swing.json`: `top50` (os 50 papéis mais líquidos do Ibovespa, uma classe por empresa; PETR3/BBDC3 descartadas), `prev_fora` (papéis da visão anterior fora do top-50, que continuam cobertos por serem do ranking/boleta do robô)
e `ibov_resto` (o resto do Ibovespa, que vai para `sem_analise`). Papel novo no top-50 entra na triagem; papel que sai do top-50 mas estava na visão anterior vira `prev_fora` (continua coberto).
Bucket de setor do robô de cada papel (necessário para a seção 3.8):
```
/Users/douglaslora/Desktop/quant-b3/.venv/bin/python3 $FERR/bucket_setor.py        # grava $PARTES/bucket_setor_robo.json
```

### 3.3 Dados: frescor, cobertura e coleta
```
python3 $FERR/checar_dados.py                  # confere todos; grava $PARTES/frescor_cobertura.json
python3 $FERR/checar_dados.py --coletar --lotes 3     # dispara coletas locais em segundo plano para quem está sem dado ou com COLETA VELHA
```
Cada coleta leva 1 a 3 minutos por papel (o coletor às vezes trava num papel; se um log não andar por 8 minutos, mate **o seu** processo `coletar_dados.py` e refaça o lote com os tickers que faltam).
Repita `checar_dados.py` até o `frescor` ficar ATUAL. O que não fechar (RI bloqueado, release vazio, ticker novo sem mapa em `ri_fontes.py`) vira lacuna nomeada:
- `EUCA4`, `GMAT3`, `UGPA3`, `VBBR3` etc. aparecem com "site de RI NAO MAPEADO": o coletor só acha release novo pela CVM; declare, não insista.
- `cobertura` do `mesa.py` **conta documentos, não conteúdo**: release de 26 caracteres ou "informativo de RI" de 4 mil caracteres passa como `ok`. Leia o tamanho (`chars`) antes de confiar.
- Ticker que mudou de nome: `ELET3` virou `AXIA3` (Axia Energia); `MOTV3` é a ex-CCR; `PNVL3` é a **Panvel** (Grupo Dimed), não a Pague Menos (PGMN3).

### 3.4 Mercado de curto prazo
```
python3 $FERR/mercado_swing.py --ref AAAA-MM-DD --janela-inicio AAAA-MM-DD --janela-fim AAAA-MM-DD
```
`--ref` = fechamento de referência para a conta de reversão (em 11/10/2026: 2026-10-02, o último fechamento antes do 1º turno; sem `--ref` usa 5 pregões antes do último).
Grava `$PARTES/mercado_swing.json`: último fechamento, retorno desde a referência, retorno em 10 pregões, volatilidade realizada, RSI14, distância da média de 200 dias, liquidez diária, P/L, P/VP, DY, ROE, valor de mercado,
`proximo_resultado` (data e status confirmada/estimada, do calendário da CVM) e `resultado_na_janela`. **Data de resultado "estimada" nunca entra no texto como data**: cite só o trimestre.

### 3.5 Macro: insumos numéricos
```
python3 $FERR/macro_insumos.py --janela-inicio AAAA-MM-DD --janela-fim AAAA-MM-DD    # grava $PARTES/macro_insumos.json
```
Traz (cada bloco falha sozinho e vai para `lacunas`): BCB (Selic e mudanças, CDI, IPCA mês e 12m, dívida bruta/líquida, primário, PTAX, reservas, desemprego, PIB, inadimplência, juro do crédito), Focus (IPCA, Selic, câmbio, PIB),
terminal (Copom e Fed embutidos nas curvas, **vértices do DI hoje, há uma semana e há um mês**, indicadores dos EUA do FRED), agenda macro e resultados BR da janela, Yahoo (Ibovespa, dólar, Brent, Treasury 10 anos, VIX, EWZ, S&P) e opções de BOVA11 (volatilidade implícita).
Complete com **busca na web rotulada** (veículo e data) o que o terminal não tem: pesquisas do 2º turno (Datafolha, Quaest, AtlasIntel), mercados de previsão (Polymarket/Kalshi), debates, fluxo estrangeiro (B3), China (PMI), minério e celulose.
Se um insumo não existir, escreva a lacuna em `avisos`.

### 3.6 Lente da Kinea (macro primeiro)
1. Leia `$SAIDA/lente_kinea.json` (e `.md`). Se existir e for de até 7 dias, **use**; senão leia direto: `cd $MESA && python3 mesa.py kinea cartas --grep "eleiç|fiscal|Selic|juros"`, `python3 mesa.py kinea carta AAAA-MM "Atlas Geral"`
   (a carta do gestor do Atlas é a mais macro), `python3 mesa.py kinea docs --grep "..."` e `mesa.py kinea videos` (as lives têm só título: nenhuma legenda foi coletada).
2. Responda **as 14 perguntas** de `lente_kinea.json -> perguntas_visao_semanal` (cenário-base e probabilidade; juro americano; petróleo e diesel; dólar; China; juro real do Brasil; eleição; fiscal; crédito; posicionamento; prêmio da bolsa; IA;
   dose e hedge; o que mudaria de ideia), cada uma com dado, data e fonte. Modelo: `macro_swing_modelo_11-10-2026.py` (bloco `lente_kinea`).
3. Diga no campo `macro.lente_kinea.fonte` **qual das duas coisas foi feita** (usou o `lente_kinea.json` do outro agente, ou leu a carta e a live direto) e o que não foi lido.
   As cartas da Kinea não são assinadas por pessoa; os textos guardados não nomeiam Ruy Alves nem Marco Freire: atribua à Kinea.
4. Termômetro de regime (regra G20 do estudo de gestores): **calmo / em alerta / em estresse**, em `macro.regime_de_risco`. Regras G19 a G27 (cenário com placar, assimetria mínima 2 para 1 na entrada do swing, opção comprada em evento binário, escada de dose, hedge por correlação) estão em `lente_kinea.json -> regras_relacionadas`.

### 3.7 Escrever o macro (`$PARTES/macro_swing.json`)
Copie `ferramentas/macro_swing_modelo_11-10-2026.py` para o scratchpad, troque os textos e números pelos de `macro_insumos.json` e rode: ele grava `$PARTES/macro_swing.json`. Campos (todos obrigatórios, exceto onde marcado):

| Campo | Conteúdo |
|---|---|
| `regime` | uma frase: em que regime estamos |
| `regime_de_risco` | calmo / em alerta / em estresse, com a razão |
| `texto` | até 8 linhas; **fato** e **leitura de mercado** rotulados; evento dominante e o que o preço já embute |
| `indicadores[]` | `{nome, valor, data, fonte}`; web e imprensa rotuladas na `fonte` |
| `eventos[]` e `_eventos_10_pregoes[]` | `{data, hora?, evento, pais, relevancia, leitura, fonte, na_janela}`; o segundo é copiado para o topo do JSON como `eventos_10_pregoes` |
| `favorece[]`, `pune[]` | o que o regime favorece/pune **nos 10 pregões** |
| `cenarios_25_10[]` (ou o evento da semana) | cenário, probabilidade implícita (mercado de previsão e pesquisas, rotuladas), reação esperada (âncoras de imprensa), âncora aritmética de reversão |
| `valor_esperado_ilustrativo` | conta da mesa com as entradas à vista; o sinal depende de quem acerta a probabilidade |
| `lente_kinea` | `fonte`, `o_que_olham[]`, `perguntas[]` (14), `limites` |

Eventos da janela: calendário em `macro_insumos.json -> agenda_janela` (IBGE, BCB, FRED, FOMC, resultados BR da CVM, vencimento de opções), mais busca na web para debates e pesquisas. Vencimentos: opções sobre ações = série mensal do cadastro da B3 (3ª sexta, em out/26: 16/10);
opções sobre índice e futuro de Ibovespa = quarta-feira mais próxima do dia 15 (14/10/2026). **Conferir sempre com `fut.json`/`eventos.json`.**

### 3.8 Setores (`$PARTES/setores_swing.json`) — ATENÇÃO ao nome
Modelo pronto: `ferramentas/setores_swing_modelo_11-10-2026.py` (troque o dicionário `TEXTOS` e rode; ele imprime a média ponderada das convicções por balde e grava `setores_swing.json`).
`quant/mesa.py` só aplica a inclinação se o campo `setor` casar com o bucket do robô (`bancos`, `seguros`, `energia`, `utilidades`, `petroleo`, `materiais`, `industria`, `consumo`, `varejo`, `saude`, `imobiliario`, `tecnologia`, `outros`),
em minúsculas e **sem acento**. A visão de 10/10/2026 usou nomes como "Petróleo e gás" e "Elétricas": só `bancos`, `seguros`, `varejo` e `tecnologia` casaram; energia, utilidades, petróleo, materiais, indústria, consumo, saúde e imobiliário ficaram em zero.
Corrija assim: **uma entrada por bucket, com `setor` igual ao bucket**, e os subsetores (educação, transporte, celulose, distribuição de combustíveis etc.) em `subsetores`:
```
{"setor": "petroleo", "inclinacao": -1, "porque": "...", "juro": "neutro com juro em queda", "cambio": "ganha com dolar em alta", "fontes": ["..."],
 "subsetores": [{"nome": "Petróleo e gás (produtoras)", "inclinacao": 0, "porque": "..."}, {"nome": "Distribuição de combustíveis", "inclinacao": -1, "porque": "..."}],
 "papeis_do_bucket": ["PETR4","PRIO3","UGPA3","CSAN3"]}
```
- `juro`: `ganha|perde|neutro com juro em queda`. `cambio`: `ganha|perde|neutro com dolar em alta` (efeito de dólar SUBINDO). Detalhe em `juro_detalhe`/`cambio_detalhe`.
- A inclinação do bucket **resume** as convicções dos papéis dele (média ponderada pela liquidez, arredondada) e o tipo de exposição ao evento; use -1..+1, e ±2 só com os papéis do bucket todos em direção única e análise a fundo.
- Conferir o casamento: `cd /Users/douglaslora/Desktop/quant-b3 && .venv/bin/python3 -c "import json; from quant import mesa; v=json.load(open('quant/saida/mesa/visao_mesa.json')); i=mesa.inclinacoes(v); print({b: mesa._setor_da_mesa(b,i) for b in ['bancos','seguros','energia','utilidades','petroleo','materiais','industria','consumo','varejo','saude','imobiliario','tecnologia']})"`.
  Todos os buckets com papel na visão têm de aparecer com o valor escrito.

### 3.9 Ações: lotes por setor, profundidade e convicção
Divida o universo em lotes de 8 a 13 papéis do mesmo bloco setorial (7 lotes em 11/10/2026: bancos_seguros, commodities_energia, utilities, industria_transporte_tech, construcao_shoppings, varejo_consumo, saude_educacao).
Cada lote vira um subagente **Sonnet** (ou, sem subagentes, é processado em sequência). Modelos: `ferramentas/modelo_contexto_swing.md` (copie para `$PARTES/CONTEXTO_SWING.md` depois de atualizar a janela e o evento)
e `ferramentas/modelo_prompt_lote.md`. Cada lote grava `$PARTES/swing_<grupo>.json`.

**Profundidade:**
- `"a fundo"`: ficha, frescor, cobertura, decomposição de margem, release (grep) e dívida/custo lidos pelo `mesa.py` (mesmo método da skill `analise-ativo`, seções 2 e 4). Papel já lido a fundo na semana anterior continua a fundo se nada material mudou (reconfira frescor).
- `"triagem"`: `frescor` + `cobertura` + primeira tela da ficha + margem de 4 a 8 trimestres + um grep no release mais novo + uma busca de notícia dos últimos 15 dias (rotulada). 4 a 6 minutos por papel.
- **Regra de ouro:** convicção sem análise a fundo fica em **0 ou ±1, nunca ±2.** `mesclar_swing.py` rebaixa automaticamente e avisa.

**Convicção de swing (-2..+2)** = assimetria do papel nos próximos 10 pregões, combinando (1) exposição ao evento dominante e quanto já está no preço (retorno da semana, RSI14, distância da média de 200 dias, `reversao_total_a_ref_pct`),
(2) gatilhos de curto prazo (resultado na janela, vencimento de opções, decisão regulatória, OPA/M&A, dividendo) e (3) qualidade de balanço como proteção (dívida, caixa, margem, lucro não recorrente).
+2 = gatilho concreto na janela (ou proteção clara ao evento) + preço que não embute + balanço que aguenta o cenário ruim. -2 = problema concreto que o filtro quantitativo não vê + esticado/sem proteção; **vira veto**.

**Campos por ação (obrigatórios):** `ticker`, `setor`, `conviccao`, `profundidade`, `tese`, `divida_e_custo`, `margem`, `o_que_o_preco_exige`, `risco`, `gatilho_curto_prazo`, `sensibilidade_eleicao` (alta|media|baixa), `lado_eleicao`
(favorece_flavio|favorece_lula|protege|neutro — adapte ao evento da semana), `evento_binario` ({data, descricao, se_sim, se_nao} ou null), `fontes` ([{documento, data}]), `frescor` (ATUAL|DESATUALIZADO),
`cobertura` (COMPLETA ou "INCOMPLETA: trimestres que faltam, pelo nome"). **Preenchidos pelo merge:** `horizonte` = "10 pregoes", `proximo_resultado`, `mercado`, `no_top50_ibovespa`.
Textos curtos (tese até 400 caracteres; os demais até 300): o arquivo tem ~70 papéis e o Douglas lê no celular.

### 3.10 Juntar, validar e gerar o markdown
```
python3 $FERR/mesclar_swing.py --janela-inicio AAAA-MM-DD --janela-fim AAAA-MM-DD         # grava $SAIDA/visao_mesa.json e imprime os ALERTAS
python3 $FERR/gerar_md_swing.py                                                             # grava $SAIDA/visao_mesa.md e visao_mesa_cartoes_completos.md
```
Cada ALERTA do merge precisa de resposta (corrigir o lote ou registrar em `avisos`). Antes de entregar:
1. JSON estrito (o merge usa `allow_nan=False`) e `python3 -c "import json;json.load(open('$SAIDA/visao_mesa.json'))"`.
2. O robô lê: `cd /Users/douglaslora/Desktop/quant-b3 && .venv/bin/python3 -c "from quant import mesa; v,m=mesa.ler(); print(m, len(v['acoes']), mesa.vetar(None, v)); b=mesa.bloco(v, m); print(b['ativa'])"`.
3. Todo papel da boleta do dia (`quant/saida/painel.json -> boleta.ordens`) e do ranking (`terminal-artefato/web/d/x/quant_fatores.json -> sinais.ranking`) está em `acoes` ou em `sem_analise` com motivo.
4. Nenhum ±2 com `profundidade` "triagem"; nenhum "compre/venda/recomendo" no texto (`grep -i -E "compre |venda agora|recomend" visao_mesa.json`).
5. `gerado` em ISO com fuso -03:00; `validade_dias` 7 (a rotina semanal renova antes); `eventos_10_pregoes` com data e fonte; `macro.lente_kinea.fonte` preenchido.
6. Primeira linha de `avisos`: o que é a visão (leitura interna) e a janela. Resumo para o Douglas: regime em duas linhas, setores, convicções ±2 com o motivo em uma linha, eventos, o que ficou sem análise e por quê.

## 4. Quando falta dado (tabela de decisão)

| Situação | O que fazer |
|---|---|
| `frescor` COLETA VELHA | `checar_dados.py --coletar`; se não resolver em 2 tentativas, `frescor` = DESATUALIZADO no papel e aviso |
| `cobertura` com trimestre AUSENTE/CURTO/FRACO | nunca citar número do trimestre; nomear no campo `cobertura`; conclusão por ausência (“a gestão nunca falou disso”) só com a janela cheia |
| Ticker novo sem coleta | `coletar.py T --so-local`; sem sucesso → `sem_analise` com motivo; nunca inventar |
| Release de 26 caracteres | RI bloqueia o coletor; use CVM (ITR/DFP) e rotule web |
| Data de resultado “estimada” | só o trimestre no texto; `proximo_resultado.status = "estimada"` |
| Sem cotação de minério, celulose ou China | declarar no `avisos` e usar preço realizado dos releases |
| Mercado de previsão/pesquisa discordam | mostrar os dois, com a probabilidade que cada um implica, e o sinal do valor esperado em cada caso |
| Lente da Kinea desatualizada | ler a carta do mês direto; declarar que `lente_kinea.json` não foi usado |
| Subagente devolve ±2 sem “a fundo” | o merge rebaixa; se a tese é forte, mande aprofundar |
| Cadeia de opções sem negócio | citar só a data de vencimento |

## 5. Armadilhas já encontradas (não repetir)

- **Setor da visão ≠ bucket do robô** (acento e nome): ver 3.8. Descoberto em 11/10/2026; a visão de 10/10 teve 12 de 16 setores sem efeito.
- **Veto é -2:** o robô tira o papel da seleção; use só com análise a fundo e motivo escrito em `risco` (o `quant/mesa.py` mostra o `risco` como razão do veto).
- **Ibovespa só na B3 até as 17h:** o último fechamento conhecido num domingo é o de sexta; a segunda 12/10 foi feriado. Confirme feriados em `config/calendario.yaml`.
- **`coletar.py` sem `--so-local` dispara workflow** no GitHub: proibido nesta rotina.
- **Dois processos de coleta no mesmo ticker** dão arquivos incoerentes: dê a cada processo uma lista própria.
- **PSSA3, BRSR6, YDUQ3, EUCA4** tiveram janela incompleta em 10/10/2026 (orçamento de tempo do coletor, RI bloqueado, ticker sem mapa em `ri_fontes.py`).
- **Preço de referência da boleta** é o fechamento do dia anterior: depois de uma alta forte, o robô compra em cima do movimento; diga isso em `avisos`.
- **Nomes de campo** do `mercado_swing.json`: `ret_desde_ref_pct`, `ret_1o_pregao_pos_ref_pct`, `reversao_total_a_ref_pct`, `fechamento_ref`, `data_ref` (a primeira versão de 11/10/2026 usou nomes datados, como `ret_semana_02a09_10_pct`; os lotes dessa rodada leram essa versão e o arquivo final foi regerado com os nomes genéricos). O merge e o gerador de markdown só leem os genéricos.

## 6. Depois do evento (o que muda na semana de 25/10)

- Se o 2º turno já passou, o evento dominante deixa de ser a eleição: passa a ser a **proposta fiscal do vencedor** (Kinea: “a eleição só termina quando o vencedor disser, com números, como fecha a conta”), o Copom de 04/11, a ata de 10/11, o FOMC de 28/10 e a safra de resultados do 3T26.
  Reescreva `cenarios_*`, `favorece/pune`, a tipologia de papéis (`lado_eleicao` → `lado_fiscal`: quem ganha com ajuste fiscal e com juro longo em queda) e a lista de eventos.
- Registre o placar do cenário da semana anterior (G19): o que a mesa disse, o que aconteceu, o erro. Em 04/10 a faixa para “Flávio na frente” era +2% a +5,5% e o Ibovespa fez +7,7% no dia seguinte: o erro entra na primeira pergunta da lente.
- Mantenha o histórico: `arquivo/visao_mesa_AAAA-MM-DD.json`.

## 7. Arquivos desta pasta (ferramentas)

| Arquivo | Função |
|---|---|
| `janela.py` | 10 pregões a partir de uma data, com feriados da B3 |
| `universo_swing.py` | top-N líquidos do Ibovespa + papéis carregados da visão anterior |
| `bucket_setor.py` | bucket de setor do robô de cada papel (precisa do python do quant) |
| `checar_dados.py` | frescor e cobertura de todos + coleta local em segundo plano |
| `mercado_swing.py` | preço, retornos, RSI, liquidez, próxima data de resultado |
| `macro_insumos.py` | números do macro (BCB, Focus, DI, FRED, Yahoo, opções de BOVA11, agenda) |
| `macro_swing_modelo_11-10-2026.py` | modelo do macro e da lente Kinea da rodada de 11/10/2026 (troque textos e números) |
| `setores_swing_modelo_11-10-2026.py` | modelo dos 12 baldes de setor (texto, inclinação, subsetores) da rodada de 11/10/2026; calcula a média ponderada das convicções por balde |
| `modelo_contexto_swing.md` / `modelo_prompt_lote.md` | contexto e prompt dos lotes de ações |
| `mesclar_swing.py` | junta as partes, valida (±2 só “a fundo”), grava `visao_mesa.json` |
| `gerar_md_swing.py` | gera `visao_mesa.md` (celular) e os cartões completos |
