# Sistema quant long/short de ações na B3 — diagnóstico honesto e plano

## Contexto

Douglas quer construir do zero um sistema quantitativo de ações na B3, restrito a long/short (podendo ficar só long ou só short), para lucrar com alguma assimetria da bolsa brasileira. Pediu (a) resposta honesta sobre viabilidade, riscos e assimetrias, (b) extrair tudo do episódio do Stock Pickers com o gestor da Bayes Capital e triangular com ideias próprias, (c) dizer se dá para montar banco de dados e entrar no mundo quant.

Respostas dele nesta sessão: capital inicial R$50–200 mil; corretora ainda não decidida; objetivo conta própria com automação máxima; poucas horas por semana, o assistente constrói todo o código dentro deste repositório, em pasta separada (`quant/`).

### O que foi feito
- Episódio identificado: **Stock Pickers (InfoMoney), "Por que máquinas são melhores que humanos para investir?"**, apresentador Lucas Collazo, convidado único **Marcello Paixão** (Bayes Capital Management, hub quantitativo da AZ Quest; fundos AZ Quest Bayes Long Short Sistemático, Long Biased Sistemático e Sistemático Ações FIA). Douglas colou a transcrição; ela foi dissecada por 4 analistas independentes, fundida e checada linha a linha (85 citações confirmadas contra o texto).
- 8 pesquisadores em paralelo: gestor/Bayes; episódio; evidência acadêmica com estatísticas calculadas nos dados oficiais do NEFIN-USP (2001–jul/2026); arbitragens estruturais da B3; inventário de dados; execução/custos/impostos 2026; base rates; caça a assimetrias para player pequeno.
- Painel: 3 desenhos de estratégia independentes (fatores com hedge; arbitragem de classes ON/PN/units; eventos e small caps), 2 juízes por desenho, síntese. Ranking: fatores 22,5/40, eventos 20, arbitragem de classes 18,5. As correções dos juízes estão incorporadas abaixo.
- Limitações: YouTube, InfoMoney, B3, CVM, SSRN e quase todo domínio estão bloqueados pelo proxy da sessão; a cota de WebSearch (200 buscas) esgotou após os 2 primeiros pesquisadores. Os outros 6 usaram apenas GitHub (código, papers espelhados, cartas de gestores, dados NEFIN) e conhecimento prévio marcado como inferência. Tarifas, APIs de corretoras e regras de aluguel vêm de fontes comunitárias de 2026 e precisam de confirmação oficial antes de operar. Nenhum backtest foi rodado: os números abaixo são estimativas ancoradas em evidência, não resultados.

Convenção: **FATO** = verificado nas fontes; **ESTIMATIVA** = inferência ou conta própria. `[mm:ss]` = transcrição do podcast.

---

## 1. Veredito honesto

**Viável tecnicamente: sim. Fonte de retorno relevante com R$100 mil: não, ou quase não. Laboratório, infraestrutura e track record que escalam para R$200–300 mil e uso profissional: sim, com critérios de kill escritos.**

| Item (R$100 mil, desenho recomendado) | Estimativa honesta |
|---|---|
| Retorno acima do CDI, cenário base, antes de IR | −0,5 a +1,0 p.p. a.a. (ponto +0,3) |
| Líquido de IR vs Tesouro Selic líquido (11,5–11,9%) | +0,3 a +0,7 p.p. = R$300–700/ano (+~1 p.p. se a isenção de R$20 mil valer na maioria dos meses) |
| Sharpe do excesso após custos | 0,05–0,15 (base); ~0,4 (otimista) |
| Ano ruim (1 em ~5) | CDI −20 p.p.; perda de R$15–25 mil incluindo drawdown intra-ano |
| Drawdown esperado em algum momento | 20–30% |
| Custos totais antes de IR | 1,1–1,6% a.a. semi-manual; 2,1–3,8% com VPS Windows |
| Em R$200 mil | base CDI +0,5 a +2,0 p.p. (fixos diluídos, hedge com 2 contratos) |
| Em R$50 mil | base CDI −1,5 a +0,5 p.p. (fracionário, 1 contrato = hedge de ~70%) |

**Por quê (FATOS):**
- O CDI (~14% a.a.) é o adversário. O prêmio de mercado NEFIN (Rm–Rf) foi **−2,8% a.a. nos últimos 5 anos** e 3,8% a.a. em 25 anos.
- O único fator com estatística forte na B3 é **momentum 12–2**: WML NEFIN 2001–jul/2026 = 15,4% a.a. bruto, vol 16,8%, Sharpe 0,92, t = 4,6, positivo em todos os subperíodos (2024–jul/26: +12,6% a.a.), mas com anos de −32% (2016) e −36% (2009) e meses de −22%. Valor (HML): 8,2% a.a., Sharpe 0,56, 25% das janelas de 3 anos negativas. Size e iliquidez: prêmio zero (SMB −0,8% a.a.; small caps abaixo do CDI desde 2013). Qualidade: evidência local só em carta de gestor (V8: GPOA/ROIC +5,2%/+9,5% a.a. beta-hedged no IBrX-100 2007–22).
- Um terço do prêmio de momentum vem da perna short (losers: −4,6% a.a. abaixo do CDI; −9,5% em 2013–23), que para PF custa aluguel de 2–8% a.a. em papéis líquidos, dois dígitos ou indisponível em small caps (os losers têm patrimônio médio negativo).
- O teto institucional: o L/S beta-neutro da Bayes (200 posições, 20 anos de biblioteca, 4 PhDs/MSc) fez 2023 +16,5% vs CDI 13,0%; **2024 +2,97% vs CDI 10,9%**; 2025 +14,4% vs CDI ~14,9%; PL de R$19–52 mi. A mediana dos fundos L/S Neutro orbita o CDI desde 2022. O FIA long-only da Bayes fez Ibov +3,6 p.p. a.a. em 5 anos.
- Base rates: 97% das PFs que persistiram em day trade na B3 perderam (FGV); equipes do desafio quant do Itaú 2026 acharam sinal e P&L, e **zero alfa após custos** (custos comeram 12,6 p.p.); ML colapsou de Sharpe 0,48 para 0,05 em walk-forward; estratégias publicadas entregam ~50% do Sharpe do backtest ao vivo; 45 tentativas em 5 anos produzem Sharpe 1,0 espúrio. Nenhum quant solo brasileiro lucrativo foi documentado.

**O que NÃO vai funcionar (e não vamos construir):**
1. L/S beta-neutro "à la Bayes" com short em ações nesta escala: aluguel com piso institucional de 5% + 1%, PF paga mais que institucional pelo mesmo papel, nenhuma corretora documenta short automatizado com BTC automático via API para PF. Expectativa líquida ≤ CDI.
2. Arbitragem ON/PN, units e holdings como sistema: o único backtest pós-2012 no universo relevante (PETR3/4, GGBR3/4, ITSA4/ITUB4, BRAP4/VALE3) deu +0,92% a.a., Sharpe 0,24, 41,5% das saídas por quebra de relação; o robô retail ITSA3/ITSA4 caiu de 60–70% de acerto no backtest para 27% ao vivo (z-score no mid, execução a mercado). Corrigidas as contas, valor esperado ≤ 0 em R$100 mil.
3. Tudo que depende de latência, leilão de fechamento, gap de ADR, pin de opções: terreno de HFT; o imbalance do leilão só existe no feed UMDF/Profit. Paixão: "os caras estão em outra liga" `[10:13]`; a Principia largou HFT em 2010 mesmo com colocation `[10:43–11:02]`.
4. Comprar o que caiu 15% em small cap ("venda forçada"): vai contra o único fator robusto; reversão curta não funcionou na B3; "gap reversal" em microcaps é artefato de bid-ask.
5. Day trade e mini-índice direcional: 20% de IR sem isenção e base rate desastrosa.

**Onde existe assimetria plausível para capital pequeno:** exatamente onde Paixão localiza a vantagem do pequeno `[13:16–13:37]`, `[14:01–14:14]`: universo small/mid/large com ADTV ≥ R$1,5 mi, seleção por **interseção de fatores** (momentum como principal, qualidade como portão, valor como desempate), **hedge parcial de beta em mini-índice** (sem aluguel, sem recall) em vez de shorts individuais, **aluguel como filtro negativo**, insiders como desempate, seletor de classe na entrada, rebalanceamento incremental por custo, e a **isenção de R$20 mil/mês de vendas** como vantagem estrutural certa da PF. É um edge pequeno, lento e barato, e é o único com evidência.

---

## 2. O que Marcello Paixão faz, o que copiar e o que ele diria

**Trajetória** `[38:36–43:42]`: Columbia; grupo quant do Santander (egressos da AIG Financial Products), Merrill Lynch, Deutsche; Principia em 2004 com R$5 mi ("vamos usar dado, já que a gente não é um dealer" `[41:05]`), um dos primeiros a fazer HFT/arbitragem estatística no Brasil com colocation e parceria com a XP (ON×PN, opções do mesmo ativo contra fluxo de fundos, hedge de gregas, saída em poucos dias); de 5 para centenas de milhões, entre os melhores em 2008; abandonou HFT em 2010–12 ("se a gente não operar global e não tiver muita grana sob gestão, esquece" `[10:50]`); migrou para fatores em 2012; AZ Quest em 2022.

**Processo em 4 fases** `[18:54–19:06]`: dado → sinal → construção do portfólio → execução; discricionário e sistemático convergem nas duas primeiras.
- **Dados** `[21:42–22:03]`: preço, book, histórico e balanço → texto organizado → qualquer texto → em breve imagem e som. 20.000 transcrições de calls → embeddings → modelos estatísticos testando se explicam retorno e risco `[15:58–16:26]`; experiência em hiperparâmetros conta `[16:26–16:46]`.
- **Sinais**: 200 indicadores; ~200 ações no Brasil, 3.000 nos EUA `[22:37–22:50]`. Cinco famílias: "valor, crescimento, qualidade, momento e baixo risco" `[37:30]`. "A ideia é combinar e não é combinar na somatória. A interseção" `[30:30–30:44]`. Anti data-mining: "se funciona aqui, tem que testar para ver se não é data mine e funciona em vários mercados. E se funciona em vários períodos" `[25:04]`.
- **O que funciona hoje no Brasil** `[28:54–31:42]`: valor difícil com juro alto; momentum funciona nas duas pontas; qualidade e dividendos; empresa que gera caixa, ROI alto, cresce acima de 2–3% a.a., sem dívida; "a parte vendida tem sido mais poderosa ainda" com juro estratosférico e empresas em RJ (shorts em Braskem e Oncoclínicas `[36:54–37:07]`). Valor é o fator mais descontado em anos `[37:24–38:12]`.
- **Construção e execução**: ranqueia tudo contra tudo com limites setoriais `[34:52–35:03]`; saiu de rebalanceamento por calendário para **atualização diária incremental, 100% eletrônica, "só para aquelas ações que distorceram tanto que a gente sabe que pós custo transacional vale a pena executar"** `[26:51–27:10]`; long biased com net 60–100%, hoje 70% `[37:07–37:19]`; modelo comprou construção civil com Selic a 14% no fim de 2024 ("se eu fosse discricionário, eu não deixaria" `[33:14]`).
- **Metas** `[44:13–44:48]`: L/S 8% de vol para ~150% do CDI; long biased 12% de vol para >20% nominal; FIA +5–8% sobre o Ibov. Mirar 20% nominal e não %CDI por causa do câmbio `[42:59–43:55]`. "You are as good as your last trade" `[27:42]`.
- **Sobre o pequeno**: "eu tô operando small, mid, large. Então eu acho que eu consigo ganhar mais dinheiro que ele, embora ele tenha 50 PhDs" `[13:23]`; "testando uma tecnologia com um ano de atraso em mercados que essa galera não tá operando" `[14:08]`; "se a gente tiver um ano atrás do que estão fazendo nos EUA, em geral a gente vai estar melhor que a maioria" `[23:41]`; arbitragem estatística de minutos a dias "dá para ser competitivo", mas "no Brasil tem pouca escalabilidade" `[11:49–12:13]`; sistemático é para quem não é gigante `[22:50–23:16]`; a barreira de entrada caiu com IA `[15:15–15:20]`.

**Copiável por PF:** interseção de fatores; filtro de qualidade explícito; momentum nas duas pontas (a ponta short via hedge de índice, não short individual); ranking agnóstico com limite setorial; rebalanceamento incremental com regra de custo; validação em vários períodos e num universo-espelho; universo small/mid; meta nominal; 4 camadas separadas; texto/LLM em escala de ~200 empresas só depois da v1 validada.
**Não copiável:** HFT/colocation; 20 mil transcrições; 200 indicadores em 3.000 ações; execução institucional; ponta short de fundo com BTC em escala; 150–200 posições; opções globais; trend following em 50 futuros; a distorção de rebalanceamento trimestral de fundos de pensão (ele fala de mercados desenvolvidos).

**O que ele diria do plano:** concordaria com o universo, a interseção, o filtro de qualidade, a regra de custo, os limites setoriais e a validação. Alertaria que 22 posições é pouco (ele defende "portfólio super diversificado"), que estamos deixando "a metade mais poderosa" (o short em distressed) na mesa, e que a meta é modesta perto dos "20% ao ano" dele. A resposta do plano: a concentração é o preço do lote de 100 e do capital; o short em distressed é inacessível a PF (aluguel e recall); e a própria Bayes entregou entre CDI −8 e CDI +3,5 no L/S em 2023–25.

---

## 3. Assimetrias da B3: real vs mito (para PF com R$50–200 mil)

| # | Tese | Evidência | Edge após custos | Veredito / uso |
|---|---|---|---|---|
| 1 | Momentum 12–2 + portão de qualidade, long-only, hedge parcial em WIN | WML t=4,6; Winners VW +10,45% sobre CDI (Sharpe 0,42, beta ~1); momentum 2x mais forte em small caps (14,5% vs 7,1% a.a.); sem decaimento pós-publicação fora dos EUA (Jacobs-Müller); Bayes FIA +3,6 p.p. | CDI −0,5 a +1,5 p.p. base; −20 em ano ruim | **Real, pequeno; espinha dorsal** |
| 2 | Aluguel (BTC) como filtro negativo no long | dados diários públicos (BDI); literatura de short interest | +0 a +1 p.p. como filtro; sem histórico > 21 dias | **Real como filtro; só forward** |
| 3 | Insiders (CVM 44 / VLMO) em small caps | dataset mensal, agregado por grupo, 10–40 dias de atraso; evidência brasileira não acessada | +0 a +2 p.p. como desempate | **Plausível; overlay** |
| 4 | Seletor de classe (comprar a classe/unit mais barata do mesmo emissor NA ENTRADA) | spreads ON/PN 0,5–3% observados; unit vs cesta ~−0,5% | +0,2 a +0,5 p.p., sem risco próprio | **Real como tática de execução; nunca girar entre classes** (realiza ganho e consome a isenção por CPF) |
| 5 | Exclusões de SMLL/IDIV (comprar o excluído 1–3 dias após a vigência) | prévias públicas; nenhum estudo brasileiro; composição histórica gratuita inexistente | desconhecido | **Hipótese; arquivar dados hoje** |
| 6 | Direitos de subscrição e sobras | nenhuma evidência quantitativa | evento a evento, manual | **Oportunista** |
| 7 | Reversão pós-venda forçada em small cap | losers −9,5% a.a.; reversão curta não funcionou; resgates citados são de multimercados, não de FIAs | ≤ 0 | **Mito na forma simples** |
| 8 | Pairs ON/PN, units, holdings como book L/S | Grupo4 Sharpe 0,24; robô retail 27% ao vivo; holdings não convergem; Caldas 1996–2012 Sharpe 2,1 não replicou | ≤ 0 em R$100 mil; piso R$300 mil | **Mito para PF nesta escala** |
| 9 | Fatos relevantes noturnos em small caps | em líquidas: reversão D+1→D+6 (−2,30%, t=−2,4) em 2024, nada em 2023; IPE sem hora | não provado | **Pesquisa futura** |
| 10 | Gap ADR/EWZ, leilão, pin de opções, calendário | HFT/institucional; calendário +0,15–0,28%/trade | ≈ 0 | **Mito para PF** |
| 11 | Short direcional em distressed (a "ponta vendida" de Paixão) | prêmio existe (losers −4,6 a −9,5% a.a. abaixo do CDI), mas aluguel 5–30% a.a., indisponibilidade, recall em 2–3 pregões | ≈ 0 líquido para PF | **Real para fundo, inacessível para PF; capturar indiretamente: não carregar losers + hedge de índice** |

---

## 4. Custos e impostos (PF, 2026, R$100 mil, desenho recomendado)

Premissa de giro: ~18%/mês one-way sobre ~R$70 mil investidos ≈ R$150 mil negociados/ano.

| Item | Base | R$/ano | % a.a. |
|---|---|---|---|
| Emolumentos + liquidação B3 | FATO: ~0,030%/lado swing (0,032% no leilão de fechamento; day trade ~0,023%) | ~45 | 0,05 |
| Corretagem | FATO: R$0 em Clear/Genial/Rico/Inter (com RLP); XP R$0–2,50; BTG R$0–5 | 0 | 0 |
| Meio-spread + slippage (custo dominante) | ESTIMATIVA corrigida pelos juízes: 25/40/80 bps por lado (ADTV > R$20 mi / R$5–20 mi / < R$5 mi); small caps ilíquidas têm spread cheio de 0,5–2%; slippage medido +8/+12 bps mesmo em ITSA3 | ~720 | 0,72 |
| Fracionário (~30% das ordens) | ESTIMATIVA: +20 bps (livro separado) | ~90 | 0,09 |
| Hedge WIN (1–2 contratos, 6 rolagens) | FATO: R$0,25–0,42/contrato/lado; 1 tick de slippage | ~35 | 0,03 |
| Margem WIN | FATO: overnight ~R$3–7 mil/contrato; Tesouro aceito pela Câmara "sob critérios", haircut não obtido; corretora pode exigir mais | 0 (rende Selic) | 0 |
| JCP líquido de 15% vs backtest bruto | FATO: JCP 15% na fonte; NEFIN e StatusInvest usam bruto | 200–400 | 0,2–0,4 |
| Aluguel | R$0 no MVP-1 (sem short em ações) | 0 | 0 |
| Dados | FATO: R$0 (COTAHIST, CVM, B3, NEFIN, BCB, brapi free) | 0 | 0 |
| Infra estágio A (semi-manual, PC/GitHub Actions) | ESTIMATIVA | 0–300 | 0–0,3 |
| Infra estágio B (VPS Windows para MT5) | FATO: R$80–180/mês | 1.000–2.200 | 1,0–2,2 |
| **Total antes de IR** | | **1.100–1.600 (A) / 2.100–3.800 (B)** | **1,1–1,6 / 2,1–3,8** |

Sensibilidade: com R$50 mil os fixos dobram e o fracionário sobe (2,5–5% a.a.); com R$200 mil, 0,8–1,2% (A) / 1,3–2,3% (B). Teste obrigatório no backtest: sobreviver a 2x os custos.

**Impostos (FATO):** 15% sobre ganho líquido mensal em ações (swing) e em WIN comum; 20% day trade; isenção quando o **total de vendas de ações à vista do CPF no mês ≤ R$20 mil** (só ações; não vale para ETF, BDR, WIN, day trade; se ultrapassar, tributa todo o lucro do mês); IRRF 0,005% sobre vendas (abatível) e 1% do lucro em day trade; DARF 6015 até o último dia útil do mês seguinte, mínimo R$10; prejuízo compensa sem prazo dentro do compartimento (comum × comum, day trade × day trade; **futuros em swing entram na base comum**); ReVar (RFB/B3) integrado ao IRPF 2026 cruza tudo, inclusive shorts e aluguel; JCP 15% na fonte; dividendos > R$50 mil/mês do mesmo pagador têm IRRF 10% desde 01/01/2026 (Lei 15.270/2025); nada mudou em 15%/20%/R$20 mil. Comparação justa é líquida de IR nos dois lados: Tesouro Selic paga 15–22,5% só sobre o rendimento (≈ 11,5–11,9% líquido). Tomador de aluguel incorpora a despesa ao custo; doador é tributado como renda fixa. Isenção é por CPF: qualquer outra venda de ação do Douglas no mês a consome; prejuízos em meses isentos exigem parecer de contador.

---

## 5. Execução e corretora (PF, 2026)

**FATO (fontes comunitárias de 2026, confirmar):** MetaTrader 5 em Clear, XP, Genial, Modal/BTG, Nova Futura (Rico/Toro/Inter "a confirmar"); Clear e Genial "não exigem plano" de automação; XP Pro R$0–90/mês e BTG Trader R$0–150/mês "a confirmar"; risco documentado: "conta MT5 da corretora brasileira não permite EA; algumas exigem plano". O pacote Python `MetaTrader5` só roda em Windows. ProfitDLL exige Windows + Profit Pro R$200–380/mês + licença sob consulta (desproporcional para 15–25 ordens/mês). BTG só via terceiros; API comunitária é read-only. Nenhuma fonte documenta venda a descoberto automatizada com BTC automático via API para PF. Horários: pré-abertura 09:45–10:00, contínuo 10:00–16:55, fechamento 16:55–17:00; liquidação D+2 (D+1 em fev/2028); lote 100 / fracionário sufixo F (spread maior; short no fracionário raro).

> **DECISÃO TOMADA (set/2026): a corretora será o Safra.** Isso muda a aritmética desta
> seção e da seção 4, e a mudança é grande o bastante para ser eliminatória. Toda a tabela
> de custos assume **corretagem zero** (Clear/Genial/Rico/Inter); banco costuma cobrar por
> ordem, e a estratégia gera ~195 ordens por ano com ordem média de R$ 3,3 mil (medido no
> ensaio da Fase 4). No cenário base, o excesso de 0,3 p.p. sobre R$ 100 mil dá um teto de
> **R$ 1,54 por ordem**; uma tabela de R$ 15–25 custa 2,9–4,9% a.a. e come o ganho esperado
> várias vezes. O Safra também **não estava** na lista de corretoras com MetaTrader 5, o que
> provavelmente elimina o estágio B (automação) e deixa a operação semi-manual
> indefinidamente. O passo a passo, com as perguntas a fazer por escrito e a conta para
> rodar com o número real, está em [`comecar-a-rodar.md`](comecar-a-rodar.md); a conta sai
> de `python3 -m quant.custos --corretagem <valor>`.

**Recomendação original (ESTIMATIVA), mantida como registro:** abrir conta-teste com R$5 mil na **Clear** (MT5 sem plano, corretagem e custódia zero) ou **Genial**, e confirmar por escrito em 2 semanas: (1) EA/ordens via MT5 em conta PF sem plano pago, incluindo roteamento de **ações à vista e fracionário** (só WIN/WDO foi verificado); (2) Tesouro Selic aceito como margem de WIN e com qual haircut; (3) se um dia houver short em ação: BTC automático overnight, taxa/spread (no BTG o doador fica com 70%; "em outras o inverso") e custo mínimo por contrato; (4) recall e prazo de devolução (2–3 pregões). Se (1) falhar, XP ou BTG com plano viram alternativa. **Antes disso: verificar a política da intermediária a que Douglas é vinculado como assessor e a Resolução CVM 178 sobre negociação em conta própria** (fora do corpus; item obrigatório).

**Modelo de automação:** Estágio A (paper + primeiros 6 meses reais) = **semi-manual**: o sistema gera à noite a "boleta do dia" (CSV + painel no BROADCAST); Douglas executa em 10–15 min pela manhã (na prática 20–40 min em dias de fatiamento ou roll). Estágio B = MT5 via Python em Windows (PC do Douglas ou VPS), lendo as mesmas boletas, só após 6 meses ao vivo. Ordens sempre limitadas ao mid, enviadas ~10:20, reprecificadas em +0,2% a cada 2 h; nomes com ADTV < R$5 mi fatiados em 2–3 dias (≤ 1% do ADTV); nunca ordem a mercado em small cap; leilão de fechamento só para WIN e nomes > R$20 mi/dia; compras só com caixa disponível em D+2. Coleta pública pode rodar no GitHub Actions; **execução nunca** (sem credenciais no CI).

---

## 6. Dados: banco mínimo, fontes exatas, armadilhas

| Dado | Fonte (gratuita) | Observações |
|---|---|---|
| Preços diários desde 1986, com deslistadas | `https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{ano}.ZIP` (anual) e `COTAHIST_D{ddmmaaaa}.ZIP` (~20:31 BRT); 245 bytes/registro, latin-1, preços /100; universo com `CODBDI='02'` e `TPMERC='010'`; campos PREOFC/PREOFV (bid/ask de fechamento), CODISI (ISIN) | NÃO ajusta proventos; **seguir a série pelo ISIN por todos os CODBDI** até o último pregão (senão as piores perdas somem); excluir fracionário (TPMERC 020 / CODBDI 96) |
| Negócio a negócio | `https://arquivos.b3.com.br/apinegocios/tickercsv/{AAAA-MM-DD}` (+ `/apinegocios/dates`) | retenção ~20 pregões: **arquivar diariamente** (filtrado ao universo) |
| Aluguel (BTC) | `POST https://arquivos.b3.com.br/bdi/table/export/csv?lang=pt-BR` com `{"Name":"BTBLoanBalance"|"BTBLendingOpenPosition"|"BTBTrade","Date":..,"FinalDate":..,"ClientId":"","Filters":{}}` | retenção pública ≤ 21 dias (sondagem de jul/2026 só devolveu o último pregão); B3 repete taxa sem negócio: exigir contratos > 0 e quantidade > 0; publicado em D+1 |
| Fluxo por investidor | BDI `SharesInvesVolum` / PDF `BDI_02_{aaaammdd}.pdf` | defasagem ~2 pregões; só regime |
| Índices e prévias | `https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/{GetPortfolioDay|GetTheoricalPortfolio|GetQuartelyPreview}/{base64({"pageNumber":1,"pageSize":120,"language":"pt-br","index":"SMLL","segment":"1"})}` | composição histórica em bulk não existe grátis: snapshot diário; IBOV 2003–2022 no repo `igor17400/IBOV-HCI` |
| Proventos e eventos | `.../listedCompaniesProxy/CompanyCall/GetListedCashDividends/{base64}` e `GetListedSupplementCompany/{base64}` + `https://statusinvest.com.br/acao/companytickerprovents?ticker=X&chartProventsType=2` (User-Agent + Referer; cobre deslistadas) | B3 trunca (bonificação SLC 05/2023 ausente; KLBN repetida em ON/PN/UNIT; só empresas vivas); JCP bruto; ajustar como retorno total forward a partir da data-ex com fatores oficiais, nunca restatement |
| Fundamentos point-in-time | `https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{DFP|ITR}/DADOS/{dfp|itr}_cia_aberta_{ano}.zip` (BPA/BPP/DRE/DFC_MD `_con`); FCA `fca_cia_aberta_valor_mobiliario_{ano}.csv` (ticker/ISIN ↔ CD_CVM, cobre deslistadas); `CAD/DADOS/cad_cia_aberta.csv` | DFP desde 2010, ITR ~2011 → **backtest com fundamentos só a partir de 2011**; `DT_RECEB` como data de disponibilidade, maior `VERSAO` ≤ t, `ESCALA_MOEDA`; reapresentações frequentes |
| Insiders | `.../VLMO/DADOS/vlmo_cia_aberta_{ano}.zip` (`_con`) | 2017+ ou "últimos 5 anos" (divergência não resolvida); agregado por grupo; sem nomes |
| Fatos relevantes | CVM IPE (já coletado por `refresh_cvm` no app.py) | sem hora de entrega: gravar `capturado_em` |
| Fatores de referência | `https://raw.githubusercontent.com/nefin/nefin.github.io/{SHA}/static/resources/risk_factors/nefin_factors.csv` (+ portfolios e `stock_loans/average_loan_fee.csv`) | **fixar por SHA**: HML mudou > 1 bp em 3.889 datas entre snapshots de jun/2026 |
| Cotas/resgates de fundos | CVM INF_DIARIO e CDA | CDA com até 90 dias de atraso |
| CDI/Selic | BCB SGS série 12 via `sgs_fetch` (já existe) | |
| Cross-check | Yahoo `.SA` (já em app.py), brapi free (15 mil req/mês, 1 ticker/req, só 1d) | Yahoo apaga deslistados e tem abertura/volume ruins: nunca para universo, gaps ou leilões |

**Armadilhas (FATO):** survivorship (7–8 de 57 tickers líquidos sumiram em 2 anos); CSV `;` latin-1 vírgula decimal; JSON entre aspas; feriado → HTTP 400 / ZIP vazio (usar `bizdays` B3); mudança de ticker/ISIN (BRFS3/MRFG3 → MBRF3); aluguel sem histórico antes de set/2023 (no backtest o filtro é proxy NEFIN e fica marcado "não testado"); COTAHIST não tem book: slippage é modelo declarado; nenhuma calculadora aberta de IR trata short + aluguel + futuros.

**Banco mínimo** (parquet em `quant/dados/`, gitignored; DuckDB/SQLite opcional): `cotacoes_diarias(isin,ticker,data,abe,max,min,fec,bid,ask,vol_fin,qtd,negocios,codbdi)`, `identidade(isin,ticker,cd_cvm,cnpj,vigencia_ini,vigencia_fim)`, `eventos(isin,tipo,data_ex,fator,valor,fonte,versao)`, `retorno_total(isin,data,ret)`, `fundamentos_pit(cd_cvm,dt_refer,dt_receb,versao,conta,valor)`, `universo_pit(data,isin,adtv21,presenca)`, `aluguel_diario(data,ticker,taxa_doador,taxa_tomador,contratos,qtd,pos_aberta)`, `indices_carteira(data,indice,ticker,peso,tipo)`, `negocios_intraday` (particionado por dia), `insiders_vlmo`, `fatores_nefin(sha,data,...)`, `sinais`, `carteira_alvo`, `ordens`, `fiscal_mensal`, `livro_tentativas`.

Bibliotecas de referência para copiar parsers (não como dependência): `PythonicCafe/mercados`, `nickmaglowsch/b3-pipeline-data-and-backtest-framework`, `out-of-sample/Quant-AI-Itau-2026`, `ropensci/rb3`. Stack: pandas, numpy, pyarrow, requests (já existe), bizdays, statsmodels; sem sklearn/xgboost na v1.

---

## 7. Estratégia recomendada: "INTERSEÇÃO-PF" (fatores com hedge, corrigida pelos juízes)

**Universo (point-in-time, recalculado no último pregão de cada mês):** uma classe por empresa (a mais negociada; units contam); ADTV21 ≥ R$1,5 mi; presença ≥ 80% dos pregões em 12 meses; preço ≥ R$2; sem RJ/intervenção (CODBDI 05–11), BDR, ETF, FII; sem piso de valor de mercado. Tamanho esperado: ~120–170 nomes hoje; 60–90 em 2008–2012 (nos anos iniciais "top 22" será "tudo que passou"). Nota honesta: esse universo se sobrepõe ao da Bayes e de outras sistemáticas pequenas; a assimetria é "pouco capital de arbitragem", não "nenhum".

**Sinais mensais (dados disponíveis até t; fundamentos por `DT_RECEB`):**
1. **Momentum** (principal): MOM12 = retorno total t-12 a t-2 (definição NEFIN); MOM6 = t-6 a t-2; score = média dos percentis. Portão: percentil ≥ 50.
2. **Qualidade** `[29:44–30:25]`: FCO 12m > 0 e FCF 12m > 0 (obrigatório); dívida líquida/EBITDA ≤ 3 (obrigatório, ex-financeiras); ROIC (ou ROE em financeiras) ≥ mediana **ou** GPOA percentil ≥ 40.
3. **Crescimento**: excluir só o quartil inferior de crescimento de receita TTM; LPA TTM > 0.
4. **Valor** (B/M, EV/EBIT, FCF yield): não é portão; desempate com peso 25% e exclusão do decil mais caro.
5. **Baixo risco**: excluir o decil de maior vol 252d; peso 1/vol dentro do cap.
6. **Aluguel** (só ao vivo): excluir do long nomes com taxa tomador > 5% a.a. e posição em aberto subindo > 50% em 60 dias.
7. **Insiders** (VLMO): compras líquidas ≥ 0,3% do free float por controlador/diretoria em 1–3 meses = +10 pontos percentuais no ranking (hipótese pré-registrada, não portão).
8. **Seletor de classe**: ao comprar emissor com ON/PN/unit, comprar a classe cujo **ask** está mais barato em relação à mediana de 60 pregões ajustada por dividendo diferencial; nunca trocar de classe só por spread.

**Combinação (interseção, `[30:30]`):** sobreviventes dos portões 1–2–3 e das exclusões 4–5–6 (~30–45 nomes) ranqueados por 0,50 × momentum + 0,25 × qualidade + 0,25 × valor; top 22 (banda 18–25). **Histerese:** sai só abaixo do rank 40 ou por falha de portão obrigatório, com **teto de holding de 12 meses** (não estender até a zona de reversão do momentum). **Percentis fixados a priori (50/40/25/10), sem busca em grade** (janela in-sample real com fundamentos é 2011–2015; 12 parâmetros livres em 5 anos é receita de overfit).

**Testes pré-registrados obrigatórios no backtest:** (a) interseção (portões) vs soma de z-scores; (b) "só momentum + exclusão de vol" vs "com portões fundamentalistas" (se os portões não adicionarem alfa NEFIN com t ≥ 1,5, removê-los: 3 dos 5 não têm evidência local); (c) t-stat do alfa de Winners-hedgeado com 22 nomes (a estatística que importa e que ninguém calculou).

**Carteira e hedge (corrigidos):**
- Long ≈ 65–70% do capital (22 nomes × ~R$3–3,2 mil em R$100 mil; lote de 100 até ~R$30, fracionário acima); **caixa/margem ≥ 25–30% em Tesouro Selic** (margem de WIN R$3–7 mil/contrato + ajuste diário num rali de 10–15% + compras em D+2 não cabem em 8–10%).
- Hedge: **1 WIN** (~R$35 mil de nocional com Ibov ~175 mil) até R$200 mil de capital; 2 WIN acima. Com beta realizado de small/mid ~0,8, 1 WIN sobre R$70 mil long ≈ net beta 0,3–0,4. Aceitar o hedge grosseiro; não perseguir banda contínua. BOVA11 emprestado só se capital < R$70 mil (aluguel 0,3–2% a.a. é inferência; recall em 2–3 pregões; caixa da venda pode não render CDI).
- Cap por nome 6%, piso 3%; setor ≤ 25%; ≤ 40% em nomes com ADTV < R$5 mi.
- **Rebalanceamento incremental** `[26:51–27:10]`: ranking mensal, execução avaliada diariamente; trade só quando |peso alvo − atual| × capital > 3 × custo estimado (B3 + meio-spread por tier + fracionário); ajustes de peso só com desvio > 1,5 p.p.; hedge só no roll ou se beta 60d sair de [0,15; 0,55]. Giro alvo ≤ 20%/mês (a calibrar; o giro real do NEFIN não é publicado).
- Vol esperada: **14–15%** (0,35 × 24% de mercado + ~9% idiossincrático com 22 nomes + ~8–9% de base SMB/IML que o WIN não cobre).
- Fiscal: preferir concentrar vendas de ações em meses com total ≤ R$20 mil (por CPF).

**MVP-2 (só com ≥ R$200 mil e 12 meses ao vivo):** substituir até 30% do hedge por 6–8 shorts em ações líquidas (MOM12 ≤ p25 e FCF < 0 ou DL/EBITDA > 4 ou LPA < 0; ADTV ≥ R$10 mi; aluguel verificado ≤ 2% a.a. com contratos > 0 nos 5 pregões). Expectativa líquida ≈ 0; só como pesquisa.

**Módulos descartados após o julgamento:** book L/S de pares ON/PN/units (valor esperado ≤ 0 com as contas corrigidas; sobra só o seletor de classe na entrada); gatilho de "venda forçada" −15% em small cap; fatos relevantes noturnos (fica como pesquisa futura com o IPE timestampado).

---

## 8. Números esperados (ESTIMATIVA, R$100 mil, estágio A semi-manual)

| Cenário | Prob. subjetiva | Sobre o CDI antes de IR | Nominal (CDI ~14%) | Líquido de IR vs Selic líquida | Sharpe do excesso | Drawdown | Base |
|---|---|---|---|---|---|---|---|
| Pessimista (crash de momentum + reversão + base small×large contra) | ~20% | −15 a −25 p.p. | ≈ −6% | −12 a −17 p.p. (R$15–25 mil) | −0,8 a −1,5 | 20–30% | WML 2009/2016; 1S2023 (Mom −19%, Qualidade −29%) |
| Base (alfa bruto 4–7 p.p. com haircut de 50%, beta 0,35, base neutra) | ~55% | −0,5 a +1,0 p.p. | ≈ 14,3% | +0,3 a +0,7 p.p. (R$300–700) | 0,05–0,15 | 12–18% | Winners VW; Bayes FIA +3,6; Falck-Rej-Thesmar |
| Otimista (sem decaimento, mercado bom, small caps recuperando) | ~25% | +4 a +6 p.p. | ≈ 19–20% | +4 a +5 p.p. (R$4–5 mil) | 0,35–0,45 | 10–15% | meta Bayes FIA; W-L small 14,5% |
| Limiar de rejeição | | backtest com Sharpe > 1,0 após custos = procurar bug; > 1,5 = rejeitar | | | | | |

Conta do cenário base (p.p. sobre o CDI): alfa bruto 4–7 × haircut 50% × exposição 0,7 = +1,4 a +2,5; beta residual 0,35 × prêmio (+3,8% em 25 anos / −2,8% em 5 anos) ≈ +0,3; base SMB/IML esperança 0; custos −1,1 a −1,6; JCP líquido −0,2 a −0,4; parcela hedgeada ≈ CDI. Resultado −0,5 a +1,0.

---

## 9. Riscos
1. Crash de momentum (meses de −22%, anos de −32/−36%; correlação −0,34 com o mercado): o pior ano é "mercado sobe 30% e a carteira fica flat/negativa".
2. Rotação violenta de fatores no Brasil (1S2023; março/2025).
3. Base small × large não hedgeada (SMLL descolou do Ibov por anos; "duas bolsas" em 2026; SMB vol 17,6%, MDD −76%).
4. Concentração: um nome em RJ/fraude custa 3–6% do capital; SERIEMA teve 67% do P&L em uma ação.
5. Custos subestimados: sem book no backtest; spreads 0,5–2% em small caps.
6. Hedge imperfeito e margem: granularidade do WIN, beta instável, ajuste diário, roll bimestral, margem elevada em crise.
7. Dados: proventos truncados, NEFIN revisado, reapresentações, Yahoo com sobrevivência; cada erro vira alfa falso.
8. Overfitting: in-sample real 2011–2015; prêmios brasileiros exigiriam > 40 anos para robustez ex-ante; com ~10 anos o backtest não tem poder para validar Sharpe 0,3: ir ao vivo é aposta informada, não inferência.
9. Tributação: 15% sobre nominal inclusive o "CDI" do carrego; assimetria do hedge (ganho no WIN tributado no mês, perda no long não realizada); isenção por CPF; ReVar.
10. Execução/corretora: MT5 só Windows; EA pode exigir plano; short automatizado não documentado; tempo diário no estágio A é 20–40 min, não 5.
11. Comportamental: sobrepor julgamento ao sistema `[33:14]`; interferência impulsiva quebra a lógica.
12. Escala econômica: em R$100 mil o ganho esperado é menor que o valor do tempo do Douglas; o kill de 24 meses pode disparar mesmo com edge real (2 anos com Sharpe 0,1 é ruído).
13. Regulatório: assessor de investimentos negociando em conta própria (política da intermediária, Res. CVM 178) — verificar.
14. Regime: 5 anos de prêmio de mercado negativo com CDI 14–15%; se a Selic cair, muda a composição do retorno.

---

## 10. Plano de implementação (pasta `quant/` neste repositório)

Convenções: Python 3.11, nomes em português como no `app.py`, dependências mínimas (`pandas`, `pyarrow`, `requests`, `bizdays`, `statsmodels`; DuckDB opcional). Reaproveitar de `app.py`: `http_get` (GET tolerante), `Cache`, `log`, `load_json_file`/`save_json_file` (escrita atômica), `sgs_fetch` (CDI/Selic), `refresh_cvm` (IPE; estender com `capturado_em`) e o padrão `JOBS` / `run_job` / `scheduler_loop` (app.py:1480–1501) para as rotinas diárias. Dados brutos em `quant/dados_brutos/` e banco em `quant/dados/` (gitignored). Coleta pública diária via GitHub Actions (`.github/workflows/coletar-quant.yml`, cron após 21:00 BRT = `0 0 * * 2-6` UTC, pois COTAHIST_D sai ~20:31 BRT e BDI é D+1), gravando em branch de dados ou Release (não no `main`); execução nunca no CI. Esforço realista (corrigido pelos juízes): 250–400 h de código nas fases 1–3, concentradas no PIT da CVM e na curadoria de eventos; Douglas 1–2 h/semana de supervisão.

### Módulos, em ordem, com critério de pronto
- **M0 `quant/dados/arquivar_b3.py`** (rodar hoje): BDI BTBLoanBalance + BTBLendingOpenPosition (D-1; contratos > 0), tickercsv filtrado ao universo, GetPortfolioDay/GetQuartelyPreview de IBOV/SMLL/IDIV/IBRA, IPE com `capturado_em`. Pronto: 5 pregões consecutivos sem falha; feriados tratados; armazenamento fora do `main`.
- **M1 `quant/dados/calendario.py`**: calendário B3 (bizdays/ANBIMA), último pregão do mês. Pronto: feriados 2005–2027 batem com dias sem COTAHIST_D.
- **M2 `quant/dados/cotahist.py`**: download/parse anual 2005–2026 + diário (245 bytes, latin-1, preços /100, PREOFC/PREOFV, ISIN) → parquet particionado por ano, série por ISIN atravessando todos os CODBDI. Pronto: offsets conferidos contra PETR4 35,66 / SLCE3 17,68 / JBSS3 36,21 em 27/12/2024; JBSS3/BRFS3/STBP3 presentes até o último pregão.
- **M3 `quant/dados/identidade.py`**: mapa point-in-time ISIN ↔ ticker ↔ CD_CVM/CNPJ via FCA e cadastro, com vigências e eventos terminais. Pronto: 100% dos ISINs do universo com CD_CVM; BRFS3/MRFG3 → MBRF3, JBSS3, STBP3 resolvidos e documentados.
- **M4 `quant/dados/eventos.py`**: B3 GetListedCashDividends/GetListedSupplementCompany cruzados com StatusInvest; tabela `eventos` com fonte/versão; curadoria manual (SLC 05/2023, KLBN); `retorno_total` forward a partir da data-ex; JCP marcado bruto. Pronto: teste de que retornos até t não mudam ao adicionar evento após t; reconciliação com Yahoo adj close < 0,5% em 95% dos meses em 30 tickers.
- **M5 `quant/dados/cvm_fundamentos.py`**: DFP/ITR 2010–2026 → `fundamentos_pit` por filing (`DT_RECEB`, maior `VERSAO` ≤ t, `ESCALA_MOEDA`); TTM de receita, EBITDA, LPA, FCO, capex, dívida líquida, PL, lucro bruto, ativo; mapa de CD_CONTA com exceções. Pronto: 30 empresas conferidas à mão; ROIC/GPOA/DL-EBITDA para ≥ 90% do universo desde 2011.
- **M6 `quant/dados/nefin.py` + `cdi.py`**: fatores e portfólios NEFIN fixados por SHA (avail_date = snapshot); CDI via `sgs_fetch`. Pronto: série 2001–2026 carregada; SHA no README.
- **M7 `quant/universo.py`**: universo PIT mensal (regras da seção 7) + setor. Pronto (**bloqueio duro da fase 1**): réplica dos fatores WML e HML mensais do NEFIN com metodologia de terciles, correlação ≥ 0,90 e média anual dentro de ±3 p.p. em 2008–2026.
- **M8 `quant/sinais.py`**: sinais 1–8 da seção 7 com percentis fixos; filtro de aluguel marcado "não testado" no backtest. Pronto: teste unitário de look-ahead por sinal (nenhum dado com `DT_RECEB` > t); distribuição mensal inspecionada.
- **M9 `quant/custos.py`**: 0,030% B3; meio-spread 25/40/80 bps por tier de ADTV; +20 bps fracionário; impacto 10·√(p/1%) bps; WIN R$0,35/contrato/lado + 1 tick; aluguel (MVP-2) = max(taxa, piso) × markup 1,4–3 + tarifa; JCP líquido de 15%; modo "2x custos". Pronto: custo realizado no paper trading (contra tickercsv) dentro de 1,5x do modelado.
- **M10 `quant/carteira.py`**: portões + ranking, top 22 (banda 18–25), peso 1/vol com cap 6%/piso 3%, setor ≤ 25%, ≤ 40% em ADTV < R$5 mi, histerese com teto de 12 meses, lotes vs fracionário, caixa ≥ 25–30%, 1 WIN (< R$200 mil) com roll 5 pregões antes do vencimento, regra incremental (> 3× custo; peso > 1,5 p.p.; hedge só no roll ou beta fora de [0,15; 0,55]). Pronto: carteira-alvo mensal reproduzível; erro de lote reportado por nome.
- **M11 `quant/backtest.py`**: walk-forward mensal **2011–jun/2026** (2008–2010 só preço/momentum, à parte); holdout 2016–2026 aberto uma vez; subperíodos 2011–15 / 2016–19 / 2020–22 / 2023–26; hedge WIN sintético (Ibov total return − CDI); custos M9 e 2x; atribuição contra NEFIN (alfa, t, betas); deflated Sharpe com `livro_tentativas`; comparações pré-registradas (a)(b)(c) da seção 7; concentração de P&L por nome e ano. Pronto: relatório escrito com decisão go/no-go.
- **M12 `quant/fiscal.py`**: apuração mensal por modalidade (futuros na base comum), 15%, isenção por CPF (com campo para vendas externas), IRRF, prejuízos por compartimento, aluguel no custo (MVP-2), JCP na fonte, DARF 6015, exportação para ReVar. Pronto: 12 meses simulados batem com planilha manual e parecer de contador.
- **M13 `quant/execucao/boleta.py` + `/api/quant/*` em `app.py` + painel no `index.html`**: boleta noturna (ticker, lado, quantidade, limite ao mid, validade, motivo, custo, fatiamento, roll, seletor de classe) em `quant/saida/boletas_AAAAMMDD.json`; registro de fills; painel (carteira alvo vs atual, boleta, custos, fiscal, frescor dos dados); "modo seguro" (sem boleta se faltar COTAHIST_D ou BDI do dia). Pronto: 40 pregões de paper com fills simulados contra tickercsv; slippage ≤ 1,5x; execução ≥ 60%; zero boletas com dado velho.
- **M14 `quant/relatorio.py` + `quant/rodar_diario.py`**: orquestração diária (coleta → universo → sinais → carteira → custos → boleta → fiscal), relatório semanal/mensal (retorno vs CDI, Ibov e Selic líquida; atribuição NEFIN; giro; custos e slippage realizados; status dos kill criteria), changelog de versões (máximo 2 mudanças/ano, cada uma com backtest comparado e 3 meses de paper em paralelo). Pronto: 2 meses de relatórios sem intervenção manual.
- **M15 (opcional, estágio B) `quant/execucao/mt5_ponte.py`**: ponte Python ↔ MetaTrader 5 em Windows lendo as mesmas boletas; ordens limitadas, reprecificação a cada 2 h, cancelamento ao fim do dia, reconciliação. Pronto: conta-teste confirmou EA sem plano, roteamento de ações e fracionário, Tesouro como margem; 20 pregões sem divergência.

### Fases, critérios de passagem e kill
- **Fase 0 (hoje, 1 dia):** M0 + M1; conta-teste na corretora com as 4 checagens da seção 5; verificação regulatória (Res. CVM 178 / política da intermediária). Passagem: 5 pregões arquivados.
- **Fase 1 (semanas 1–4):** M2–M7. Passagem (bloqueio duro): replicar WML/HML do NEFIN (corr ≥ 0,90, ±3 p.p.); reconciliação de retorno total; deslistadas presentes. Se não replicar, o dado está errado: não seguir.
- **Fase 2 (semanas 5–9):** M8–M11. Passagem para o papel: excesso líquido sobre CDI > 0 no holdout e em ≥ 3 dos 4 subperíodos; Sharpe do excesso entre 0,2 e 0,8 (> 1,0 = procurar bug; > 1,5 = rejeitar); giro ≤ 25%/mês; MDD ≤ 35%; alfa NEFIN t ≥ 1,5; sobrevive a 2x custos com excesso ≥ 0; nenhum nome > 15% e nenhum ano > 60% do P&L. Kill: falhar qualquer item; deflated Sharpe < 0,5; resultado dependente de ADTV < R$1,5 mi ou de anos pré-2011. Se morrer aqui, o pipeline sobrevive como infraestrutura do BROADCAST (universo, eventos, fundamentos PIT, aluguel, painel).
- **Fase 3 (semanas 10–12):** M12–M14 (produção simulada).
- **Fase 4 (3–6 meses de paper trading, cobrindo ≥ 1 roll de WIN e 1 rebalanceamento de índice):** fills simulados contra tickercsv; Douglas executa a rotina como se fosse real. Passagem: slippage ≤ 1,5x; execução ≥ 60%; zero erros operacionais em 2 meses; paper reproduz o ranking do backtest; nenhum parâmetro alterado.
- **Fase 5 (mês 7+):** R$50 mil por 6 meses (12–15 nomes, 1 WIN, restante em Tesouro Selic); escalar para R$100–200 mil após 6 meses sem kill; MVP-2 só após 12 meses ao vivo e ≥ R$200 mil; M15 só se o P&L anualizado superar 3x o custo do VPS; avaliação formal em 12 e 24 meses contra a seção 8.
- **Kill ao vivo (por escrito antes do primeiro trade):** (1) drawdown 20% do pico → gross a 50% e revisão; 30% → encerrar; (2) excesso sobre CDI em 12 meses < −10 p.p. **e** alfa NEFIN 12m negativo → parar; (3) slippage > 2x por 3 meses ou giro > 35%/mês por 3 meses → suspender; (4) 24 meses com excesso líquido de IR sobre a Selic ≤ 0 → encerrar (decisão econômica, não estatística); (5) 2+ execuções erradas num mês ou margem chamada sem caixa → suspender; (6) fim da isenção de R$20 mil, +2 p.p. de custo fiscal, corretora remover MT5 elevando fixos > 3% a.a., universo < 100 nomes; (7) máximo 2 mudanças de parâmetro por ano, cada uma com nova versão e 3 meses de paper em paralelo.

---

## 11. Verificação
- Testes unitários dos parsers (COTAHIST, CVM, BDI, índices, proventos) com fixtures reais e os valores de referência de 27/12/2024.
- Teste de vazamento point-in-time em todos os sinais e no universo.
- Reconciliação de retorno total vs Yahoo adj close; réplica dos fatores WML/HML do NEFIN (o gate da fase 1).
- Backtest reproduzível (seed, SHA do NEFIN, versão dos dados) com `livro_tentativas` e deflated Sharpe; teste com 2x custos.
- Paper trading com log de todas as boletas e fills simulados contra tickercsv; slippage medido.
- Conferência da apuração fiscal com planilha manual e ReVar; parecer de contador.
- Painel no terminal e relatório mensal rodando 2 meses sem intervenção; "modo seguro" testado com dado ausente.

---

## 12. Decisões que só o Douglas pode tomar
1. **Objetivo:** fonte de retorno (não vale em R$100 mil) **ou** laboratório/infraestrutura/track record para escalar e uso profissional (vale, com kill criteria).
2. **Capital e cronograma:** R$50 mil real após o paper e escalar, ou esperar R$200 mil para o primeiro trade real.
3. **Corretora: decidida — Safra** (set/2026). Falta a tabela de corretagem por escrito e a verificação regulatória como assessor; as duas podem encerrar o projeto antes de começar. Ver seção 5 e `comecar-a-rodar.md`.
4. **Estágio A semi-manual por quanto tempo:** 20–40 min/dia por 6–9 meses, ou VPS Windows desde o início (1–2% a.a. em R$100 mil).
5. **Hedge:** 1 WIN grosseiro (recomendado) vs BOVA11 emprestado.
6. **Isenção de R$20 mil como restrição de desenho** (por CPF, inclui qualquer outra carteira) e parecer de contador.
7. **Portões fundamentalistas:** manter os 3 sem evidência local como hipótese pré-registrada, ou começar só com momentum + exclusão de vol.
8. **Perna short em ações (MVP-2):** desistir de vez até R$200 mil (recomendado) ou manter como pesquisa após 12 meses.
9. **Camada de texto/LLM** (releases e transcrições de ~200 empresas): só após a v1 validada.
10. **Disciplina:** compromisso escrito de não alterar parâmetros fora das regras — "se eu fosse discricionário, eu não deixaria" `[33:14]` é exatamente a tentação que mata o sistema.
