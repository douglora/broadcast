# Começar a rodar — passo a passo (corretora: Safra)

Este documento é a lista do que **só você** pode fazer. O código está pronto até a Fase 4;
o que falta não é programação, é (a) uma decisão sobre custo, (b) uma verificação
regulatória e (c) uma primeira carga de dados com rede.

Leia os passos 0 e 1 antes de qualquer outra coisa. Os dois podem matar o projeto, e é
melhor que matem agora do que depois de seis meses de trabalho.

---

## Passo 0 — A tabela de corretagem do Safra (antes de tudo)

**Por que este passo vem primeiro.** O modelo de custos foi construído assumindo corretagem
**zero** (Clear, Genial, Rico, Inter). O Safra é banco, e banco costuma cobrar por ordem.
Isso não é um ajuste de premissa: muda o sinal do resultado.

A estratégia gera **~195 ordens por ano** com R$ 100 mil (medido no ensaio de 110 pregões da
Fase 4), com ordem média de **R$ 3,3 mil**. Ordem pequena é onde a tarifa fixa mais dói:

| Corretagem por ordem | Custo por ano | Sobre R$ 100 mil |
|---|---|---|
| R$ 0 | R$ 0 | 0,00% a.a. |
| R$ 2,50 | R$ 488 | 0,49% a.a. |
| R$ 5,00 | R$ 975 | 0,97% a.a. |
| R$ 15,00 | R$ 2.925 | **2,93% a.a.** |
| R$ 25,00 | R$ 4.875 | **4,88% a.a.** |

E o outro lado da conta, o que importa: no **cenário base** do plano o excesso líquido sobre
o CDI é de ~0,3 p.p. ao ano — R$ 300 sobre R$ 100 mil. Divididos por 195 ordens, isso dá um
teto de **R$ 1,54 por ordem**. Acima disso, a estratégia trabalha para a corretora.

Rode a conta com o número que o Safra te passar:

```bash
python3 -m quant.custos --corretagem 15.00        # troque pelo valor real
python3 -m quant.custos --corretagem 15.00 --capital 200000
```

**O que pedir ao Safra, por escrito** (e-mail do assessor serve; print de tela não):

1. Corretagem por ordem em **ações à vista**, lote padrão e **fracionário** — são tabelas
   diferentes em muitas casas.
2. Se há **corretagem mínima por nota** ou por ordem, e se ordens do mesmo papel no mesmo
   dia contam como uma nota ou várias. Com fatiamento em 2–3 dias isso muda a conta.
3. **Custódia** mensal e taxa de manutenção.
4. Tarifa por contrato de **mini-índice (WIN)**, por lado, e se há tarifa de rolagem.
5. Se existe **tabela para volume** ou pacote negociável — e, sendo você assessor, se há
   condição de funcionário/parceiro.

**Se a tarifa não couber**: as opções honestas são (a) negociar a tabela, (b) abrir uma conta
separada numa corretora de corretagem zero só para esta estratégia — respeitando o passo 1 —,
ou (c) desistir da parte de execução e manter o projeto como laboratório e infraestrutura, que
continua valendo. O que **não** é opção é reduzir o giro para caber na tarifa: isso muda a
estratégia para acomodar um custo, e é exatamente o tipo de ajuste que o `versoes.py` existe
para impedir.

---

## Passo 1 — A verificação regulatória (você é assessor)

Este passo é independente do passo 0 e igualmente eliminatório. Como profissional vinculado
a uma intermediária, sua negociação em conta própria não é livre.

**O que verificar, por escrito, com o compliance da intermediária a que você é vinculado:**

1. A **Resolução CVM 178** e o que ela exige de quem atua como assessor de investimentos ao
   negociar em conta própria.
2. A **política interna** da intermediária: costuma haver pré-aprovação de ordens, período
   mínimo de permanência (*holding period*), lista restrita de ativos, e obrigação de operar
   pela própria casa.
3. Se existe **holding period mínimo**, ele pode ser incompatível com o desenho: a estratégia
   tem histerese e teto de 12 meses, mas o rebalanceamento incremental gera ajustes de peso a
   qualquer momento. Um período mínimo de 30 dias, por exemplo, exigiria mudar a regra — e
   mudar a regra é uma versão nova no `versoes.py`, não um remendo.
4. Se há **obrigação de operar pela casa**, o passo 0 deixa de ter a saída (b).

Guarde a resposta. Ela é o documento que te protege, e o `quant/versoes.jsonl` é onde a
restrição, se existir, deve virar parâmetro registrado.

---

## Passo 2 — A conta e as quatro checagens operacionais

Só depois dos passos 0 e 1. Abra (ou confirme) a conta no Safra e confirme **por escrito**:

1. **Roteamento de ações à vista e fracionário** pelo canal que você vai usar. O estágio A é
   semi-manual: você digita as ordens olhando a boleta. Isso funciona em qualquer home
   broker, então aqui a pergunta é só sobre custo e horário.
2. **Tesouro Selic aceito como margem** de WIN, e com qual *haircut*. O desenho mantém 25–30%
   do capital em caixa justamente para a margem; se o Safra não aceitar título como margem, o
   caixa fica ocioso e o retorno cai.
3. **Automação (estágio B), se um dia existir.** O MetaTrader 5 é o caminho documentado para
   PF, e o Safra **não estava** na lista de corretoras com MT5 que levantei — confirme se
   existe, se exige plano pago e se permite *Expert Advisor* em conta PF. Se não existir, o
   estágio B some e você fica em semi-manual indefinidamente. Isso é aceitável: o plano prevê
   6 a 9 meses de estágio A de qualquer forma, e a automação só se paga se o P&L anualizado
   superar 3× o custo da infraestrutura.
4. **Aluguel de ações (BTC)** — só relevante no MVP-2, que exige R$ 200 mil e 12 meses ao
   vivo. Pergunte assim mesmo, para não ter surpresa depois: taxa de tomador, se há BTC
   automático, e o prazo de devolução em caso de *recall*.

---

## Passo 3 — A primeira carga de dados (com rede)

Aqui volta a ser trabalho de máquina. Rode **nesta ordem** — cada passo depende do anterior:

```bash
pip install -r quant/requirements.txt

python3 -m quant.dados.cotahist --anos 2005-2026            # ~20 anos de preços
python3 -c "from quant.dados import nefin; nefin.baixar('fatores'); nefin.baixar('aluguel_taxa')"
python3 -m quant.dados.identidade                            # FCA + cadastro CVM
python3 -m quant.dados.eventos                               # proventos e desdobramentos
python3 -m quant.dados.cvm_fundamentos --anos 2010-2026      # DFP/ITR point-in-time
python3 -m quant.dados.cdi                                   # CDI diário (BCB)
python3 -m quant.dados.setores                               # macrossetor por CNPJ
python3 -m quant.dados.capital_social --anos 2010-2026
python3 -m quant.dados.painel_fundamentos --anos 2010-2026
```

É demorado (algumas horas na primeira vez, a maior parte no COTAHIST e na CVM) e pode falhar
por rede. Todos os coletores são idempotentes: rodar de novo continua de onde parou.

**Confira o que chegou** antes de seguir — os valores de referência estão em
`quant/docs/validar-com-fonte-real.md`, e o principal é: PETR4 a 35,66, SLCE3 a 17,68 e
JBSS3 a 36,21 no pregão de 27/12/2024, e JBSS3/BRFS3/STBP3 presentes até o último pregão em
que existiram (se sumiram antes, o parser está perdendo empresa deslistada, e todo o backtest
fica enviesado para cima).

---

## Passo 4 — O gate da Fase 1 (o bloqueio duro)

```bash
python3 -m quant.validacao.replica_nefin --ini 2008 --fim 2026
```

Ele reconstrói os fatores WML e HML a partir dos **seus** dados e compara com os do NEFIN.
Passa com correlação ≥ 0,90 e diferença de média anual dentro de ±3 p.p.

**Se falhar, pare.** Não é o gate que está apertado: é o seu banco de dados que está errado, e
seguir em frente significa construir uma estratégia sobre números que não descrevem a bolsa.
As causas prováveis, em ordem: empresa deslistada faltando, provento não ajustado, ou data de
disponibilidade errada nos fundamentos.

Se passar, registre a linha de base do changelog — a partir daí toda mudança de parâmetro
entra no orçamento de duas por ano:

```bash
python3 -m quant.backtest --janela treino                 # 2011-2015, quantas vezes quiser
python3 -m quant.versoes --registrar "linha de base" "fase 1 aprovada" --backtest '{"sharpe":0.3}'
```

---

## Passo 5 — Fase 2: o backtest e o veredito go/no-go

```bash
python3 -m quant.backtest --janela treino                 # explore aqui
python3 -m quant.backtest --janela holdout --abrir-holdout   # UMA vez, e lacra
python3 -m quant.livro --verificar
```

O holdout abre **uma vez**. Depois de aberto, o livro de tentativas lacra e qualquer nova
passada fica registrada como o que é: reuso de dado já visto.

Critérios de passagem (seção 10 do plano): excesso líquido sobre o CDI > 0 no holdout e em
≥ 3 dos 4 subperíodos; Sharpe do excesso entre 0,2 e 0,8 (**acima de 1,0 procure o bug, acima
de 1,5 rejeite**); giro ≤ 25%/mês; MDD ≤ 35%; alfa NEFIN com t ≥ 1,5; sobrevive a 2× custos.

Se morrer aqui, morreu com dignidade: o pipeline continua valendo como infraestrutura do
BROADCAST (universo, eventos, fundamentos PIT, aluguel, painel).

---

## Passo 6 — Fase 4: a rotina diária de paper trading

Detalhada em [`rotina-paper-trading.md`](rotina-paper-trading.md). Em uma linha por momento:

```bash
# de manha, antes das 10:20
python3 -m quant.rodar_diario --paper
python3 app.py                                  # painel em http://localhost:5051/quant

# depois do fechamento
python3 -m quant.dados.arquivar_b3
python3 -m quant.execucao.campanha --sessao

# quando errar, no mesmo dia
python3 -m quant.execucao.campanha --erro 2026-09-08 ordem_esquecida "esqueci a venda de ABCD3"

# fim de mes
python3 -m quant.execucao.campanha --conferir 2026-09
python3 -m quant.relatorio --periodo mensal
python3 -m quant.fiscal --ano 2026
```

São 3 a 6 meses de **calendário**, cobrindo pelo menos um roll do mini-índice e um
rebalanceamento de índice. Não dá para comprimir.

---

## Passo 7 — Dinheiro real, e só então

R$ 50 mil por 6 meses (12–15 nomes, 1 WIN, o resto em Tesouro Selic). Escalar para
R$ 100–200 mil após 6 meses sem kill. O MVP-2 (perna short em ações) só depois de 12 meses ao
vivo e ≥ R$ 200 mil.

Antes do primeiro DARF, leve ao contador a memória de cálculo (`quant/saida/fiscal_memoria.csv`)
e a divergência sobre prejuízo em mês isento. O módulo fiscal calcula; quem declara é você.

---

## Resumo do que depende de você

| # | O que | Bloqueia | Quanto tempo |
|---|---|---|---|
| 0 | Tabela de corretagem do Safra, por escrito | tudo | dias |
| 1 | CVM 178 + política da intermediária | tudo | dias a semanas |
| 2 | As quatro checagens operacionais | Fase 5 | dias |
| 3 | Primeira carga com rede | Fase 1 | horas de máquina |
| 4 | Rodar o gate WML/HML | Fases 2–5 | minutos |
| 5 | Abrir o holdout (uma vez) | Fase 3+ | minutos |
| 6 | A rotina diária, 3 a 6 meses | Fase 5 | **calendário** |

Os passos 0 e 1 são os únicos que podem encerrar o projeto antes de começar. Faça os dois
esta semana.
