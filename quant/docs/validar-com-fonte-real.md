# O que validar na primeira rodada com rede (fontes reais)

Os módulos da fase 1 foram escritos e testados com fixtures construídas a partir do layout documentado,
porque B3, CVM, StatusInvest e BCB estão bloqueados no ambiente onde o código foi escrito.
Cada item abaixo é uma suposição sobre a fonte real. Rode os comandos indicados no README e confira.


## identidade_eventos  (nota do revisor: 7/10)

### Suposições do implementador
- FCA valor_mobiliario: colunas CNPJ_Companhia, Data_Referencia, Versao, Valor_Mobiliario, Codigo_Negociacao, Mercado, Data_Inicio_Negociacao, Data_Fim_Negociacao; datas AAAA-MM-DD; ';' latin-1. O parser acha colunas por nome aproximado, mas o nome do CSV dentro do zip (fca_cia_aberta_valor_mobiliario_{ano}.csv) e o significado de Data_Fim_Negociacao vazia (= vigente) precisam ser conferidos.
- cad_cia_aberta.csv: colunas CNPJ_CIA, CD_CVM, DENOM_SOCIAL, SIT, DT_INI_SIT, SETOR_ATIV, DT_REG, DT_CANCEL; um CNPJ pode aparecer em mais de uma linha (fica ATIVO / DT_INI_SIT mais recente).
- B3 GetListedCashDividends: resposta {page:{totalPages}, results:[{typeStock, valueCash '1.234,56', dateApproval, lastDatePriorEx, paymentDate, relatedTo, label}]} em dd/mm/yyyy; typeStock 'ON'/'PN'/'UNIT' (casado com o sufixo do ticker: 3=ON, 4=PN, 5=PNA, 6=PNB, 11=UNT). Se typeStock vier vazio a linha e aceita para qualquer classe.
- B3 GetListedSupplementCompany: lista com um dict contendo stockDividends[{assetIssued=ISIN, factor, approvedOn, label, lastDatePrior}], cashDividends[{rate,...}] e subscriptions[{priceUnit, percentage, tradingPeriod,...}]. O filtro por classe usa o trecho do ISIN (ACNOR=ON, ACNPR=PN, ACNPA/ACNPB, CDAM=UNIT).
- MAIOR SUPOSICAO: campo `factor` do suplemento como PERCENTUAL sobre a posicao (DESDOBRAMENTO 100 -> 2.0, MGLU3 2019 700 -> 8.0; BONIFICACAO 10 -> 1.10). Para GRUPAMENTO: f<1 = multiplicador pronto, 1<=f<100 = percentual retirado (90 -> 0.10), f>=100 = razao N:1. Validar contra o salto de preco no COTAHIST na data-ex (ex.: IRBR3 30:1 em 2023, OIBR3, AMER3).
- StatusInvest: {assetEarningsModels:[{ed dd/mm/yyyy (data-com), pd, et 'Dividendo'|'JCP'|'Rendimento', etd, v numerico, sv texto, adj bool, sov}]}; usa sov (nominal original) quando adj=True; JCP tratado como bruto. Headers User-Agent + Referer https://statusinvest.com.br/ (pode devolver HTML/captcha -> None).
- ISIN de units na B3 e 'CDAM' (BRSANBCDAM13), nao 'ACN' como dizia a especificacao; classificar_papel aceita ambos como unit. ETF x FII com ISIN 'CTF': decide pelo CODBDI (12 = FII; 02/None = ETF).
- OVERRIDES anotados de memoria (validado=False): BRFS3 e MRFG3 ultimo pregao 2025-09-22 e MBRF3 a partir de 2025-09-23 (data da troca de codigo a conferir no COTAHIST); JBSS3 ultimo pregao 2025-06-06 (BDR JBSS32 depois); STBP3 resgate 2025-10-03.
- mapa_isin considera o ultimo trecho de um ticker 'aberto' (data_fim NaT) se a ultima cotacao esta a <= 45 dias do fim da amostra do COTAHIST (DIAS_ABERTO); do contrario data_fim = ultima cotacao.
- retorno_total: provento reinvestido no fechamento da data-ex; se a data-ex nao tem preco do papel, o evento cai no primeiro pregao com preco depois dela; SUBSCRICAO e OUTRO nao entram no retorno (ficam registrados); fator_acum tem base 1.0 no primeiro pregao da serie.

### Riscos que restaram após a revisão
- Convencao do campo `factor` do GetListedSupplementCompany (sobretudo GRUPAMENTO: percentual retirado x razao N:1) e a maior suposicao nao validada; conferir contra o salto de preco do COTAHIST na data-ex (IRBR3 2023, OIBR3, AMER3, MGLU3 2019) e ajustar fator_de. Sugestao: helper que compara fec_{t-1}/fec_t com o fator e marca divergencias > 25%.
- Formato real de typeStock ('ON'/'PN'/'UNT' com ou sem segmento, 'PNA'/'PNB'?) e da paginacao (page.totalPages) do GetListedCashDividends; o suplemento vir como lista com um dict; o significado de Data_Fim_Negociacao vazia no FCA e os nomes reais das colunas do FCA/cad_cia_aberta (parser tolerante, mas sem trecho real de CSV nos testes).
- StatusInvest: suposicao de que `ed` e a DATA-COM (nao a data-ex) e de que JCP vem bruto; se `ed` for data-ex, todos os eventos dessa fonte ficam um pregao atrasados (data_ex_de empurra mais um dia) e a dedupe com a B3 falha (data_ex diferente -> provento em dobro). Validar com um ticker conhecido antes de consolidar.
- Dedupe entre fontes depende de `tipo` identico; divergencia de rotulo (DIVIDENDO x JCP) entre B3 e StatusInvest duplica o provento. Considerar segunda passada por (ticker, data_ex, valor~) ignorando tipo dentro de TIPOS_DINHEIRO.
- OVERRIDES (BRFS3/MRFG3 -> MBRF3 2025-09-22, JBSS3 2025-06-06, STBP3 2025-10-03) anotados de memoria, validado=False; conferir no COTAHIST real. Tambem nao ha regra automatica para a troca de ISIN quando o codigo muda (MRFG3 -> MBRF3 provavelmente ganha ISIN novo) - o mapa_isin trata como papel novo sem CNPJ ate o FCA seguinte.
- Juncao FCA x COTAHIST e so por ticker + datas: ticker reutilizado por outra empresa DENTRO do mesmo intervalo que o FCA antigo declara aberto e sem DT_CANCEL e sem outro CNPJ no FCA (empresa deslistada que nunca entregou FCA) ainda pode herdar o CNPJ errado; cruzar pelo emissor do ISIN (Composicao/ISIN no FCA, se existir) fecharia essa brecha.
- Codigo_Negociacao do FCA pode trazer mais de um codigo por celula ou codigos de balcao/BDR; o filtro regex aceita qualquer coisa que pareca ticker. Verificar com o arquivo real.
- SUBSCRICAO nao entra no retorno total (documentado); para papeis com subscricoes relevantes e desconto grande (bancos, OIBR) o retorno total fica subestimado.
- carregar_curados descarta qualquer linha iniciada por '#' e nao suporta '#' dentro de obs; formato do CSV e responsabilidade do curador (sem validacao de tipo/fator > 0).
- Testes de rede (baixar_*) nao sao executados nesta maquina (dominios bloqueados); o tratamento de None foi lido, nao exercitado.

### Pendências
- Validar com rede o significado do `factor` do GetListedSupplementCompany para GRUPAMENTO (e confirmar DESDOBRAMENTO/BONIFICACAO como percentual) comparando com o salto de preco no COTAHIST; ajustar eventos.fator_de se necessario.
- Conferir as datas dos OVERRIDES (BRFS3/MRFG3 -> MBRF3, JBSS3, STBP3) no COTAHIST real e marcar validado=True.
- Confirmar nomes reais das colunas do FCA e do cad_cia_aberta (o parser e tolerante, mas um teste com um trecho real do CSV deve ser adicionado quando houver rede).
- Confirmar formato de typeStock ('ON'/'PN'/'UNIT'?) e paginacao (page.totalPages) do GetListedCashDividends; confirmar que o suplemento vem como lista com um dict.
- StatusInvest pode bloquear por User-Agent/captcha: baixar_statusinvest devolve None nesse caso; avaliar cache do bruto em dados_brutos/statusinvest para nao rebaixar.
- eventos_curados.csv tem so o registro da SLCE3 (bonificacao 10%, data-ex 2023-05-09); outros truncamentos conhecidos da B3 devem ser adicionados a mao.
- Retorno de SUBSCRICAO (direito de preferencia) nao e incorporado ao ret_total; se for relevante, exigira o preco do direito ou a formula max(P - preco_subscricao, 0) x percentual.
- Tickers em situacao especial (CODBDI 05-11) e fracionario nao sao tratados em identidade alem do classificar_papel; a juncao FCA x COTAHIST usa apenas ticker + datas (nao usa nome/ISIN emissor para cruzar CNPJ quando o FCA nao tem o ticker).
- Nao foi feito git commit (conforme instrucao).

## cvm_fundamentos  (nota do revisor: 7/10)

### Suposições do implementador
- Nomes dentro do zip: {dfp|itr}_cia_aberta_{ano}.csv (indice) e {dfp|itr}_cia_aberta_{DEMO}_{con|ind}_{ano}.csv; regex tolerante a caixa e a subpastas. DMPL/DVA (layout com COLUNA_DF) sao ignorados por padrao.
- Datas (DT_REFER, DT_RECEB, DT_INI_EXERC, DT_FIM_EXERC) em ISO aaaa-mm-dd nos dados abertos; ha fallback para dd/mm/aaaa. DT_RECEB assumido como data (sem hora) e disponivel para TODAS as versoes no indice; documento sem linha no indice fica com dt_receb NaT e nunca entra na visao.
- VL_CONTA com ponto decimal e sem separador de milhar ('2081947580.00'); '1.234' e tratado como 1,234 (LPA), NAO como 1234 - por isso _valor so chama numero_br quando ha virgula. Validar contra um CSV real.
- ORDEM_EXERC vem como 'ÚLTIMO'/'PENÚLTIMO' (acento em latin-1); normalizamos sem acento. ESCALA_MOEDA: MIL=1000, UNIDADE=1 (MILHAO previsto); escala desconhecida assume 1 e loga.
- DRE/DFC do ITR: usamos APENAS as linhas acumuladas (dt_ini = inicio do exercicio, meses 3/6/9) e derivamos o trimestre por diferenca. Se o ITR real tambem trouxer a linha do trimestre isolado (DT_INI=01/04, meses=3, ORDEM ULTIMO), ela e descartada pelo filtro meses in (3,6,9,12) so quando meses != 3; uma linha isolada 01/04-30/06 tem meses=3 e poderia colidir com o acumulado - o drop_duplicates por (chave, meses) com dt_ini na chave separa os dois porque dt_ini difere, mas ela geraria um 'Q1' espurio com dt_refer 30/06. VALIDAR com ITR real e, se existir, filtrar dt_ini == inicio do exercicio.
- DFP sem DT_INI_EXERC: assumido exercicio de 12 meses terminando em DT_FIM_EXERC (dt_ini = dt_fim - 1 ano + 1 dia). Exercicios sociais nao-dezembro funcionam porque o agrupamento e por dt_ini, nao por ano civil.
- Zip anual de referencia X contem todas as versoes (inclusive reapresentacoes recebidas em X+1/X+2); por isso o parquet e particionado por ano de dt_refer e baixar() rebaixa os 2 ultimos anos. Confirmar se reapresentacoes antigas entram no zip do ano de referencia ou no do ano de entrega.
- Lucro por acao: preferencia 3.99.01.01 (basico ON) > 3.99.01 > 3.99; a escala MIL e aplicada tambem ao LPA (na fixture 5,00 vira 5000) - conferir se a CVM publica 3.99 com ESCALA_MOEDA=UNIDADE ou se e preciso isentar 3.99 da escala.
- Capex = soma liquida das linhas sob 6.02 com 'imobilizado'/'intangivel' (inclui recebimentos por venda); D&A = linhas sob 6.01.01 com 'deprecia'/'amortiza'. Descricoes reais podem variar ('Adicoes ao ativo imobilizado', 'Depreciacao, amortizacao e exaustao') - a busca e por substring sem acento, mas vale amostrar.
- Escopo: 'con' se a empresa tem qualquer linha consolidada na visao, senao 'ind' (nao mistura escopos entre trimestres). Balanco usado no ttm = ultimo dt_refer disponivel em t (pode ser mais recente que o ultimo trimestre de fluxo completo).
- Financeiras: marcadas fora deste modulo via SETOR_ATIV do cadastro (contas_cvm.eh_financeira); metricas(financeira=True) zera ROIC e dl_ebitda. O download do cadastro (cad_cia_aberta.csv) nao foi implementado aqui.

### Riscos que restaram após a revisão
- Layout real nunca visto nesta maquina (dados.cvm.gov.br bloqueado): nomes dos CSVs no zip, datas ISO, VL_CONTA com ponto decimal, ORDEM_EXERC 'ÚLTIMO'/'PENÚLTIMO', DT_RECEB sem hora. Validar com um dfp/itr_cia_aberta_2023.zip real e rodar parse_zip + trimestralizar; conferir que a linha isolada do ITR tem mesmo DT_FIM e ORDEM ULTIMO (premissa da correcao).
- LPA assumido em reais por acao SEM escala (CONTAS_SEM_ESCALA). Se em algum ano a CVM publicar 3.99 ja escalado, o LPA sai 1000x menor. Amostrar PETR/VALE em 2 anos.
- dt_receb <= t e inclusivo; a hora de recepcao nao esta nos dados abertos. O universo (M7) precisa chamar visao_em/ttm com t = pregao anterior a decisao, senao ha look-ahead intradiario.
- Suposicao de que o zip do ano X contem todas as versoes de documentos com DT_REFER em X (inclusive reapresentacoes recebidas em X+1/X+2). Se reapresentacoes forem para o zip do ano de ENTREGA, gravar_ano agora loga as descartadas - mas elas ainda seriam perdidas; teria de gravar por ano de dt_refer cruzando zips.
- Trimestralizacao por diferenca assume dt_ini estavel dentro do exercicio; mudanca de exercicio social ou ITR com DT_INI_EXERC inconsistente produz NaN/None (conservador) mas sem teste de exercicio nao-dezembro.
- escopo_padrao e global por empresa na visao: quem passou a consolidar num ano perde o TTM dos anos so-individual (devolve None em vez de cair para 'ind').
- capex/D&A por substring ('imobilizado','intangivel','deprecia','amortiza' sob 6.02/6.01.01): descricoes reais como 'Amortizacao de custos de captacao' ou 'Recebimento por venda de imobilizado' entram na soma; impairment nao entra. EXCECOES esta vazia; financeiras dependem do cadastro (SETOR_ATIV) ainda nao integrado - hoje nenhum banco e marcado.
- extrair() com agregar='primeiro' pega iloc[0] silenciosamente se houver mais de uma linha para o mesmo codigo no periodo; nao ha log de duplicidade.
- Balanco no ttm = ultimo dt_refer disponivel, que pode ser mais recente que o ultimo trimestre de fluxo completo (dl_ebitda mistura datas). Documentado, nao tratado.
- baixar() rebaixa integralmente os zips dos 2 ultimos anos a cada rodada (~50-100 MB cada), sem If-Modified-Since; gravar_atomico pode levantar em erro de disco (nao e rede, mas 'nunca levanta' vale so para HTTP).
- Apareceu quant/banco/fundamentos_pit/ano=2023/parte.parquet (9,6 KB, gitignored) durante a sessao; os testes deste modulo usam tmp_path e nao o recriam - provavelmente smoke de outro agente. Verificar antes de confiar no banco.
- Nao ha teste de que DMPL/DVA no zip sao ignorados sem quebrar (regex tolera, mas nao testado com esses nomes).

### Pendências
- Validar com rede: baixar um dfp_cia_aberta_2023.zip e um itr_cia_aberta_2023.zip reais e rodar parse_zip para conferir nomes de arquivos, formato de datas, VL_CONTA e ORDEM_EXERC (suposicoes acima).
- Confirmar se o ITR real traz linha do trimestre isolado alem do acumulado na DRE; se sim, filtrar em trimestralizar por dt_ini == inicio do exercicio.
- Conferir escala do 3.99 (LPA) na fonte real; possivelmente isentar 3.99* da multiplicacao por ESCALA_MOEDA.
- Popular contas_cvm.EXCECOES com empresas de plano fora do padrao (bancos, seguradoras, holdings) apos amostragem dos dados reais.
- Integrar com o cadastro CVM (SETOR_ATIV) para marcar financeiras e com M3 (identidade ISIN/CD_CVM) para ligar ttm a tickers; fcf_yield depende de valor de mercado vindo de cotahist + acoes em circulacao (fonte externa a DFP).
- quant/README.md nao existe ainda; documentar M5 la quando for criado.

## cdi_universo_replica  (nota do revisor: 7/10)

### Suposições do implementador
- SGS 12: assumido JSON [{'data':'dd/mm/aaaa','valor':'0.056978'}] com valor em % ao dia e limite de ~10 anos por chamada (blocos de 9 anos); nao foi possivel validar contra a API (403 no proxy). O parse aceita virgula decimal e datas repetidas por precaucao.
- CDI: o fallback usa Risk_Free do NEFIN como equivalente ao CDI diario (o NEFIN documenta Risk_Free = CDI); a diferenca, se houver, e de arredondamento. A serie de fallback nao e gravada no cache do BCB.
- Universo: 'ultimo pregao de cada mes' = ultima data presente nas cotacoes de cada mes (nao o calendario B3), para que o universo de um mes so exista quando os dados daquele mes existem; presenca e medida sobre os pregoes do MERCADO presentes nos dados (ate 252), e min_pregoes=21 evita universo com 1 dia de historico.
- Universo: classificacao interna por sufixo/ISIN/CODBDI (BDR = sufixo 31..39 ou 'BDR' no ISIN; ETF = sufixo 11 + 'CTF'; FII = sufixo 11 + CODBDI 12; unit = sufixo 11 com ISIN de acao; direito = CODBDI 10 ou sufixo 1/2/9/10); a espec pedia 31..35, ampliei para 31..39 (36..39 tambem sao BDR/ETF-BDR). Chave de empresa sem identidade = ticker[:4], que falha para holdings com prefixo diferente (por isso identidade.py com CNPJ e o caminho certo). identidade.classificar_papel pode ser passado em `classificar=` (mesma assinatura).
- Universo: preco e o ultimo fechamento conhecido (ffill) e codbdi/isin idem, porque o papel pode nao negociar justamente no ultimo pregao; codbdi nao passa por 'apenas_lote_padrao' do cotahist (o filtro e feito aqui pelo parametro codbdi).
- Replica NEFIN: 'negociada em >80% dos dias com volume > R$500 mil/dia' foi lida como um unico criterio (fracao dos pregoes de t-1 com volume > 500 mil > 80%); a leitura alternativa (presenca > 80% E volume medio > 500 mil) esta disponivel em criterio='separado'. Elegibilidade e anual (ano t usa so t-1) e 'listada antes de dezembro de t-1' = primeira cotacao nos dados < 1/dez/t-1.
- Replica NEFIN: carteiras equal-weighted lidas como media simples dos retornos diarios dos membros (rebalance diario dentro do mes), nao buy-and-hold; momentum = composto dos retornos MENSAIS de t-12 a t-2 (11 meses), exigindo os 11 meses sem NaN; terciles por np.array_split (resto vai para os extremos); serie mensal = composto dos diarios (igual a nefin.mensal); medias anuais em comparar() = media mensal aritmetica x 12.
- Replica HML: segue o NEFIN e NAO e point-in-time de proposito (PL de dezembro de t-1 usado em janeiro de t); book_equity precisa de bm ou valor_mercado ou qtd_acoes (o COTAHIST nao traz acoes em circulacao); PL <= 0 excluido (suposicao sobre o NEFIN).
- O gate real (corr >= 0,90 e |dif| <= 3 p.p. em 2008-2026) NAO foi rodado: exige o COTAHIST (bvmf.bmfbovespa.com.br bloqueado) e, idealmente, retornos totais de eventos.retorno_total em vez de retornos_de_cotacoes (fechamento cru, sem proventos) - com fechamento cru espera-se WML um pouco distorcido e HML mais ainda (value paga mais dividendo).

### Riscos que restaram após a revisão
- SGS 12 (BCB) nao validado ao vivo (403 no proxy): formato JSON, valor em % ao dia, limite de ~10 anos por chamada e possivel exigencia de header Accept/User-Agent (a API do BCB e conhecida por 406/403 com alguns UAs). Ao ter rede: conferir sgs12.csv.gz contra o Risk_Free do NEFIN (esperado identico ao arredondamento) e o primeiro dia (02/01/2001).
- O gate real (corr >= 0,90, |dif| <= 3 p.p., 2008-2026) NAO rodou: exige COTAHIST (bvmf bloqueado). Com fechamento cru (sem proventos) espera-se WML um pouco abaixo e HML bem distorcido; passar retornos=eventos.retorno_total pivotado em rodar_gate.
- Leituras da metodologia NEFIN ainda sao suposicoes: criterio de volume 'conjunto' (fracao de dias com volume > 500 mil > 80%) vs 'separado'; EW rebalanceado diariamente vs buy-and-hold no mes; terciles por contagem (agora simetricos) vs pontos de corte 33/66%; exclusao de PL <= 0 no HML; units incluidas como 'acao mais negociada'. Ajustar se a correlacao ficar abaixo de 0,90.
- Chave de empresa sem identidade = ticker[:4] falha para holdings com prefixo diferente e para tickers reaproveitados; no uso real passar identidade (CNPJ) em universo_pit e empresa_de=identidade.empresa_de na replica.
- Classificacao interna por sufixo/ISIN/CODBDI e heuristica: FII exige CODBDI 12 (ETF com CODBDI 02 + 'CTF'); FIAGRO/FI-Infra/BDR de ETF (36..39) e sufixos 12/13 caem em 'outro' ou 'bdr' sem validacao contra o cadastro real.
- retornos_de_cotacoes com ffill: papel deslistado fica NaN (correto), mas um papel com longa suspensao acumula todo o movimento num unico dia - e o comportamento desejado para EW diario, porem infla a vol daquele dia.
- HML: precisa de book_equity (PL de dezembro) e acoes em circulacao vindos de cvm_fundamentos.py/FCA; sem isso replicar_hml devolve None e o gate so avalia WML.
- universo.setores() continua placeholder (so aplica um mapa); universo_em(data) devolve o universo calculado no fechamento de `data` quando data e a propria data de calculo - usar para negociar no fechamento do dia seguinte.
- README nao foi atualizado (fora dos arquivos atribuidos): as tres linhas ainda dizem 'em construcao'.

### Pendências
- Rodar o gate de verdade quando houver rede: python -m quant.dados.cotahist --anos 2006-2026 && python -m quant.validacao.replica_nefin --ini 2008 --fim 2026; se reprovar com fechamento cru, passar retornos=eventos.retorno_total(...) pivotado (data x ticker de ret_total) em rodar_gate.
- Validar o formato real da API SGS 12 (JSON, limite de janela, virgula decimal) e conferir o cache gravado em quant/dados_brutos/bcb/sgs12.csv.gz contra o Risk_Free do NEFIN (esperado: identicos ao arredondamento).
- Conferir as leituras da metodologia NEFIN (criterio de volume 'conjunto' vs 'separado', EW diario vs buy-and-hold, exclusao de PL negativo no HML) contra a pagina 'Methodology' do NEFIN e ajustar se a correlacao ficar abaixo de 0,90.
- HML: precisa de book_equity (PL de dezembro por ticker) vindo de cvm_fundamentos.py (M5) e de acoes em circulacao (FCA/DFP) para o valor de mercado; ainda nao existe integracao - replicar_hml devolve None sem esses dados.
- universo.setores() e placeholder: ligar ao SETOR_ATIV do cadastro CVM (identidade.py) ou ao segmento das carteiras B3 (arquivar_b3.py) quando M3 estiver pronto; e trocar a chave ticker[:4] por identidade.empresa_de (CNPJ) no uso real.
- README: atualizar as linhas de cdi.py, universo.py e validacao/replica_nefin.py de 'em construcao' para 'pronto; testado com fixtures; gate pendente de COTAHIST' (nao editei o README por estar fora dos meus arquivos).

---

## Fase 2 — sinais, custos, carteira e backtest (M8–M11)

Escrita inteira sem acesso a B3, CVM, StatusInvest, BCB ou Yahoo. Todo número produzido
nesta fase saiu do mercado sintético de `validacao/mercado_sintetico.py`, cuja estrutura de
fatores é o **mesmo modelo** que os sinais assumem: recuperar o que foi plantado prova
encanamento, não vantagem. **Nenhum número da Fase 2 é resultado de estratégia.**

### Suposições do implementador

- **`capital_social.py` é a suposição maior desta fase.** O nome do CSV dentro do zip do FCA
  (`fca_cia_aberta_capital_social_{ano}.csv`) e suas colunas foram escritos a partir da
  documentação, sem ver o arquivo. Se divergirem, o módulo devolve vazio e o sinal de valor
  se desliga sozinho, o que é o comportamento seguro, mas significa perder 25% do score.
- O capital usado é o **integralizado**, com subscrito e emitido como alternativas nessa
  ordem. O autorizado nunca entra (é teto estatutário, não ação emitida).
- `DIAS_ATRASO = 150` sobre a data de referência é o carimbo point-in-time estimado do FCA.
  É conservador, mas se for curto demais há look-ahead no sinal de valor.
- Valor de mercado = quantidade **total** de ações × preço da **única** classe que o
  universo manteve. Quando ON e PN divergem de preço, isso erra por essa diferença.
- `setores_curados.csv` tem cinco CNPJs escritos de memória. CNPJ errado falha em silêncio
  (o override simplesmente nunca casa).
- O `SETOR_ATIV` do cadastro da CVM **não é point-in-time**: é um retrato de hoje aplicado a
  todo o histórico. Aceitável para um teto de concentração; proibido se setor entrar no
  ranking algum dia.
- `mercado.NIVEL_ANCORA` (fechamento do Ibovespa em 30/12/2021) foi escrito de memória. Ele
  escala o nocional inteiro do hedge: errar é viés sistemático, não ruído.
- O nível do índice composto a partir do fator de mercado do NEFIN **não** segue a trajetória
  do Ibovespa (a carteira teórica é outra). Para o nocional, o certo é usar fechamentos reais
  do índice.
- `calendario.vencimento_indice` assume "quarta-feira mais próxima do dia 15 dos meses
  pares", recuando para o pregão anterior em feriado.
- As faixas de meio-spread (25/40/80 bps) e o modelo de impacto são **estimativa**, e o
  custo tem a mesma ordem de grandeza do alfa esperado. O modo 2× é um chute sobre um chute.

### Achados que mudaram o desenho aprovado

1. **A regra de "3× custo" da seção 7 é matematicamente vazia.** O custo é uma fração do
   valor negociado, então `valor > 3 × custo` equivale a `1 > 3c`, sempre verdadeiro. Ficou
   implementada como escrita, com teste que prova a vacuidade, e foi acrescentado um piso
   absoluto de R$500 por ordem — que **não** estava no plano.
2. **O teto de 12 meses de holding não pode forçar venda.** A leitura literal esvazia a
   carteira inteira no mês em que vários nomes completam 12 meses e recompra tudo no mês
   seguinte. Passou a **revogar a histerese**: o nome volta a disputar vaga por rank e, se
   continua no topo, não há trade nenhum.
3. **O holdout não pode ser avaliado sem ser aberto**, porque três dos quatro subperíodos
   estão dentro dele. "Abrir uma vez" virou uma chamada atômica que calcula tudo e lacra.
4. **O piso de 3% por nome quase anula o peso 1/vol.** Com 22 nomes e exposição de 70%,
   sobram 4 pontos percentuais para distribuir; `carteira.diagnostico` mede a fração presa
   no piso para o relatório poder dizer se o sinal de baixo risco faz algo.
5. **Um controle nulo de duas caudas sobre a série líquida reprova um motor que funciona.**
   Custo é dreno determinístico: cobrar 2,5% ao ano para negociar ruído produz alfa negativo
   com t grande, e isso é o resultado certo. O controle nulo passou a ser feito no bruto.

### Riscos que restaram

- Sem número de ações, o componente de valor se auto-desliga e o score vira 2/3 momento e
  1/3 qualidade. `painel_fundamentos.cobertura` diz em que fração isso aconteceu; esse
  número tem de aparecer no relatório antes de qualquer veredito.
- O universo pode não ter 18 nomes depois dos portões em 2011–2013. O motor reporta
  `n_efetivo` mês a mês; um backtest que segurou 11 nomes em 2012 não é a estratégia que se
  pretende testar.
- Aluguel (sinal 6) tem cobertura **zero** no backtest: a B3 guarda 21 pregões e o
  arquivamento deste repositório começou agora. Não é "não testado", é **não testável**.
- Insiders (sinal 7) é interface vazia: o VLMO começa em 2017 e o bônus exige free float,
  que exige número de ações.
- O provento entra reinvestido no próprio papel, quando na realidade cai no caixa e só é
  reinvestido no rebalanceamento seguinte.
- O backtest **nunca rodou com dado real** e o gate da Fase 1 continua sem rodar.

### Pendências

- Baixar o COTAHIST e rodar o gate da Fase 1 **antes** de olhar qualquer número da Fase 2.
- Conferir o nome e as colunas do CSV de capital social dentro do zip do FCA; medir a
  cobertura de ações no universo real e decidir se o sinal de valor entra.
- Conferir a data de entrega real do FCA e calibrar `DIAS_ATRASO`.
- Trocar `NIVEL_ANCORA` por uma série real de fechamentos do Ibovespa.
- Conferir o calendário de vencimentos do índice contra a B3.
- Medir slippage realizado no paper trading e comparar com as faixas de 25/40/80 bps; o
  critério de pronto do M9 é ficar dentro de 1,5× do modelado.
- Rodar `python -m quant.dados.setores` contra a identidade real e olhar o tamanho do balde
  "outros"; cada holding relevante lá dentro é um teto de setor que não existe.

---

## Fase 3 — fiscal, boleta e painel (M12–M14)

A fase que encosta em dinheiro de verdade. Aqui um erro não produz um backtest otimista:
produz um DARF errado, uma ordem no papel errado ou um painel que mente. Por isso a
postura muda — quase tudo bloqueia por padrão em vez de seguir em frente.

### Suposições do implementador

- **Toda a tabela tributária veio da seção 4 do plano**, montada em 2026 de fontes
  comunitárias, sem acesso à Receita nem à B3. Cada alíquota e cada limite é uma constante
  nomeada no topo de `fiscal.py`, com a fonte no comentário, para poder ser corrigida num
  lugar só: 15% comum, 20% day trade, teto de R$20 mil, IRRF de 0,005% e 1%, DARF mínimo
  de R$10, código 6015, 15% sobre JCP na fonte e o IRRF de 10% sobre dividendo acima de
  R$50 mil por pagador.
- **O vencimento do DARF usa o último pregão do mês seguinte** como aproximação do último
  dia útil bancário. Nos meses em que os dois diferem, a data sai deslocada de um dia.
- **A isenção é calculada só com o que passou por aqui.** Sem `vendas_externas`
  preenchido, o teto de R$20 mil sai subestimado e o imposto calculado fica **menor** que
  o devido — que é o erro caro.
- **Day trade é inferido da movimentação**, casando compra e venda do mesmo papel no mesmo
  pregão pelos preços médios do dia. É a leitura padrão, mas não foi conferida contra uma
  nota de corretagem real.
- **Prejuízo em mês isento**: a Receita já sustentou as duas leituras. O padrão é o
  conservador (não compensa) e a diferença em reais sai em
  `apurar(...)["divergencia_prejuizo_isento"]`. Esse número é a pergunta a levar ao
  contador — não uma dúvida vaga.
- **O fill simulado é otimista.** Casar contra o negócio a negócio supõe que a ordem teria
  sido executada sem mover o preço. O slippage medido no paper é piso, não estimativa.
- **O horário de envio, a reprecificação e o teto de participação** (10:20, 0,2% a cada
  2 horas, 1% do ADTV por fatia) vieram da seção 5 do plano e nunca foram exercidos numa
  corretora.

### Decisões que valem a pena conhecer

1. **O terminal não ganhou pandas.** `app.py` continua dependendo só de flask, flask-cors,
   requests e feedparser; o painel lê um JSON pronto. Foi decisão explícita: o
   `INICIAR-TERMINAL.bat` tem de continuar funcionando numa instalação limpa.
2. **O painel nunca sai da máquina.** Nenhuma rota de quant entra no mapa do modo estático
   e o `gerar_dados.py` não foi tocado. Carteira, resultado e apuração de imposto não
   chegam ao GitHub Pages.
3. **Modo seguro bloqueia por padrão.** Sem gate da Fase 1 aprovado, ou com qualquer fonte
   atrasada, não sai boleta — e `gate_passou=None` (desconhecido) também bloqueia.
4. **`NaT` é um `datetime`.** A primeira versão do `limpar()` testava `datetime` antes de
   `NaT` e teria quebrado a geração do painel na primeira data ausente. O teste que pegou
   isso continua lá.

### Riscos que restaram

- A apuração nunca foi conferida contra uma nota de corretagem nem contra o ReVar. O que
  existe é uma memória de cálculo linha a linha para ser conferida — use-a.
- Não há tratamento de aluguel de ações no custo (o MVP-1 não tem ponta vendida) nem de
  opções.
- O ajuste diário de futuros entra pela mão: enquanto não houver corretora, ninguém
  alimenta `ajustes_futuros` automaticamente.
- O livro de ordens vive em `quant/saida/`, que é ignorado pelo git por ser dado pessoal.
  **Perder esse arquivo é perder a base de cálculo do imposto.** Faça backup.
- O `index.html` tem mais de 2.200 linhas e nenhum teste automatizado: a mudança do painel
  foi conferida a olho.

### Pendências

- Conferir a tabela tributária inteira com contador antes do primeiro DARF, e conferir o
  vencimento do DARF contra o calendário bancário.
- Preencher `vendas_externas` com as vendas de ações feitas fora deste sistema, todo mês.
- Levar ao contador a divergência calculada sobre prejuízo em mês isento.
- Conferir o formato da nota de corretagem quando a corretora for escolhida, e decidir se
  vale escrever um importador.
- Rodar 40 pregões de paper e comparar o slippage medido com as faixas de 25/40/80 bps do
  modelo de custos; o critério de pronto do M13 é ficar dentro de 1,5 vez.
- Conferir a posição do livro contra o extrato da corretora todo mês (`livro_ordens.conferir`).

## Fase 4 — campanha de paper trading (`execucao/campanha.py`)

A rotina do dia a dia está em `quant/docs/rotina-paper-trading.md`. O que segue é o que
**não** foi validado com dado real, e por quê.

### O que rodou de verdade

Um **ensaio** de 110 pregões (abr–set/2026) sobre o mercado sintético, com 60 empresas.
O laço fechou de ponta a ponta: boleta → fills → posição → boleta do dia seguinte, com 3
rolls do mini-índice e 2 rebalanceamentos de índice na janela. Oito dos nove critérios
ficaram verdes; `meses_sem_erro` ficou vermelho porque nenhum mês foi assinado — que é o
comportamento correto.

**Isso não é a Fase 4 e não pode ser lido como se fosse.** `avaliar()` só devolve
`passou=True` com `origem="real"`, por construção. O ensaio prova que a máquina roda, e
mais nada.

### Dois achados do ensaio (já corrigidos)

1. **A ordem saía com preço do mês anterior.** O painel de sinais é mensal, e a boleta
   estava sendo precificada pelo `preco` dele. No dia 5 saiu uma compra com limite de
   R$ 15,76 num papel que negociou o dia inteiro entre R$ 16,43 e R$ 16,49 — reemitida
   todo pregão, nunca executada. Corrigido com `rodar_diario.precos_do_dia()`, que usa o
   último fechamento disponível; ranking, vol, ADTV e setor continuam vindo do painel
   mensal. **Isso afetava também o `rodar_diario` da Fase 3**, não só a campanha.
2. **O roll se repetia.** O hedge só era gravado no estado quando havia fill de ação, então
   um roll num dia sem ordem reaparecia no pregão seguinte, e no seguinte: três rolls
   registrados onde houve um. O hedge passou a ser gravado sempre que a boleta sai, e a
   contagem passou a ser por bloco contíguo.

### O que precisa de dado real para ser validado

- **O slippage do ensaio é ficção, e sai favorável** (−60 bps contra o VWAP). A fita
  sintética passeia uniformemente dentro da faixa do dia e o simulador só casa negócio
  dentro do limite, então o preço obtido tende a ficar melhor que o VWAP. O número real só
  aparece com o negócio-a-negócio do `arquivar_b3`, e a comparação que importa é contra as
  faixas de 25/40/80 bps do modelo de custos.
- **A taxa de execução de 100% do ensaio é irreal** pelo mesmo motivo: no mercado de
  verdade a ordem limitada disputa fila, e papel ilíquido passa dias sem tocar o limite.
- **A licença do BDI.** No ensaio, o mercado sintético carimba todas as fontes, inclusive
  o BDI, que não existe sintético — sem isso a boleta bloquearia todo pregão e o ensaio
  não provaria nada. Com `origem="real"` a ausência de BDI volta a bloquear, e há teste
  para isso. Confira no primeiro dia real que o bloqueio acontece mesmo.
- **`--sessao` nunca rodou contra a fita real**, porque a fita real não existe neste
  ambiente. Ele recusa e explica quando falta o negócio-a-negócio; o caminho feliz é o que
  falta ver.
- **A reconstrução do estado vem do livro de ordens** (`rd._estado_atual`), que ainda não
  foi conferido contra extrato de corretora nenhum.

### Riscos que restam

- O ensaio carregou 8 posições com 30–60 empresas sintéticas, bem abaixo dos 22 nomes que
  a estratégia pressupõe. Com universo real (~120–170 nomes) o comportamento de
  concentração, giro e custo pode ser bem diferente.
- A contagem de rebalanceamentos de índice usa jan/mai/set como meses de vigência. Se a B3
  mudar o calendário, a constante `MESES_REBALANCE_INDICE` tem de mudar junto.
- `abrir_campanha` prova que a configuração não mudou, mas só cobre o que está em
  `config_da_estrategia()`. Mudança em código que não seja parâmetro nomeado passa
  despercebida — o hash não é um substituto para o changelog de versões.
- **O caixa da campanha é creditado no ato da venda, não em D+2.** Uma venda de hoje pode
  financiar uma compra de hoje, o que a B3 não permite. No ensaio quase não aparece porque
  as ordens são pequenas perto do caixa, mas num rebalanceamento grande a campanha
  compraria mais do que a corretora deixaria — a taxa de execução medida é otimista por
  esse lado. Corrigir exige carregar a fila de liquidação no estado.


## Changelog de versões (`versoes.py`)

O critério de kill 7 do plano — "máximo 2 mudanças de parâmetro por ano, cada uma com nova
versão e 3 meses de paper em paralelo" — deixou de ser uma frase num documento e virou
código que recusa. Não há nada aqui que dependa de dado real, mas há duas coisas que
dependem de **você**:

- **O changelog começa vazio, e isso está certo.** A linha de base (v1) só deve ser
  registrada quando a Fase 2 tiver rodado com dado real e produzido um resultado — sem
  isso, `--registrar` gravaria uma "aprovação" que nunca aconteceu. Enquanto não houver
  v1, o painel diz "nenhuma versão registrada" em cinza, não em vermelho.
- **O módulo não impede ninguém de editar `sinais.py` e rodar.** Nada impede. O que ele faz
  é comparar o hash da configuração viva com o da versão vigente: divergiu, o painel mostra
  MUDANÇA NÃO REGISTRADA com a lista de campos, e o relatório mensal repete. A disciplina
  continua sendo sua; o que muda é que a falta dela deixa de ser invisível.

### Limites conhecidos

- **O hash só enxerga parâmetro nomeado** (o que está em `campanha.config_da_estrategia()`).
  Mudança na lógica de `sinais.py` que não passe por uma constante não aparece no diff — o
  changelog não substitui a disciplina de commit.
- `quant/versoes.jsonl` é versionado no git de propósito: apagar uma versão para reescrever
  a história deixa um diff. A cadeia de hash acusa linha editada ou removida, mas quem
  reescrever o arquivo inteiro e recalcular a cadeia passa — o git é a segunda barreira.
- O orçamento é por **ano-calendário**. Duas mudanças em dezembro e mais duas em janeiro
  são quatro em dois meses, e a regra não vê isso. É uma folga conhecida; apertar exigiria
  janela móvel de 12 meses, ao custo de o usuário nunca saber quando a próxima abre.
