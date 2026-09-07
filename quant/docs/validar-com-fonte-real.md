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
