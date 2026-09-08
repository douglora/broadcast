# A rotina da Fase 4 (paper trading)

De 3 a 6 meses executando o sistema **como se fosse dinheiro real**, sem dinheiro real.
É tempo de **calendário** e não pode ser comprimido: rodar 120 pregões sintéticos numa
tarde não substitui 120 manhãs de verdade, porque o que a Fase 4 mede é justamente o que
só aparece no calendário — o roll do mini-índice, o rebalanceamento das carteiras teóricas
da B3, o dia em que a fita não baixou, e o dia em que você esqueceu de enviar a venda.

A campanha só vale se testar **uma** versão do sistema. Mexer num percentil no meio dela
zera tudo, e é para zerar mesmo: senão o que está sendo medido não é nada em particular.

---

## Antes de começar

```bash
python3 -m quant.execucao.campanha --ensaio        # ensaio sintetico: prova que o laco fecha
```

O ensaio roda o pipeline inteiro sobre o mercado sintético e mostra o placar. Ele **nunca
passa** na Fase 4, por construção: `passou` só fica verdadeiro com `origem="real"`. E o
slippage do ensaio é ficção — a fita sintética passeia dentro da faixa do dia e o
simulador só casa negócio dentro do limite, então o preço obtido sai *melhor* que o VWAP.
Não leia aquele número como execução boa.

Depois, abra a campanha. Isso congela a configuração e é o que permite provar, no fim, que
nenhum parâmetro foi mexido:

```bash
python3 -c "from quant.execucao import campanha; print(campanha.abrir_campanha()['hash'])"
```

---

## Todo dia

**De manhã, antes das 10:20** — a boleta:

```bash
python3 -m quant.rodar_diario --paper
python3 app.py                       # terminal em http://localhost:5051
```

Abra o card SISTEMA QUANT (fim da coluna da direita) → aba **Boleta**. Execute as ordens
como se fossem reais: mesmo horário, mesmo preço limite, mesma reprecificação. Se a boleta
não saiu, **não invente ordem**: modo seguro ativo quer dizer que falta dado, e ordem sobre
dado velho é exatamente o erro que a Fase 4 existe para não deixar acontecer em dinheiro
real.

**Depois do fechamento** — a medição:

```bash
python3 -m quant.dados.arquivar_b3            # guarda a fita do dia (retencao ~20 pregoes)
python3 -m quant.execucao.campanha --sessao   # casa a boleta contra a fita e registra
```

O `--sessao` é o segundo momento porque o negócio-a-negócio só existe depois do pregão.
Sem a fita ele **recusa** e diz o que falta, em vez de inventar fill — fill imaginado entra
no placar da Fase 4 e contamina a decisão de pôr dinheiro.

**Quando errar**, anote no mesmo dia:

```bash
python3 -m quant.execucao.campanha --erro 2026-09-08 ordem_esquecida "esqueci a venda de ABCD3"
```

Tipos aceitos: `ordem_errada`, `ordem_esquecida`, `preco_errado`, `quantidade_errada`,
`margem_chamada`, `parametro_alterado`, `dado_velho`, `outro`. Anotar erro é o critério
mais fácil de sabotar e o mais caro de sabotar: o critério 3 pede **zero erros em 2 meses
seguidos**, e um diário que ninguém alimenta vira uma aprovação falsa.

---

## Todo fim de mês

```bash
python3 -m quant.execucao.campanha --conferir 2026-09   # assina: eu olhei e nao houve erro
python3 -m quant.relatorio --periodo mensal
python3 -m quant.fiscal --ano 2026
python3 -m quant.execucao.campanha --status             # o placar dos 9 criterios
```

A assinatura mensal existe porque **diário vazio não prova mês limpo** — pode ser mês em
que ninguém anotou. Enquanto nenhum mês estiver assinado, `meses_sem_erro` vem `null` e o
critério não passa. Só você sabe qual dos dois casos é o seu.

O mês corrente ainda em curso não precisa estar assinado para a sequência contar: em 15 de
junho, abril e maio assinados e limpos já valem 2. Mas um erro anotado em junho quebra a
sequência na hora — mês com erro nunca é pulado.

---

## Os critérios de passagem

O placar sai no `--status` e na aba Boleta do painel. São nove, e a Fase 4 passa quando
todos ficam verdes **com origem real**:

| Critério | Gatilho | Por que existe |
|---|---|---|
| Pregões rodados | ≥ 60 | ~3 meses de pregões |
| Meses de calendário | ≥ 3 | tempo não se comprime |
| Taxa de execução | ≥ 60% | ordem limitada que não executa é estratégia que não existe |
| Slippage vs modelado | ≤ 1,5x | contra o **VWAP**; se o custo real for maior, o backtest mentiu |
| Erros operacionais | 0 | erro operacional é risco que nenhum backtest mede |
| Meses seguidos sem erro | ≥ 2 | só conta mês assinado |
| Rolls do mini-índice | ≥ 1 | o roll é o momento em que o hedge quebra |
| Rebalanceamentos de índice | ≥ 1 | jan, mai e set mexem no universo |
| Parâmetros intocados | sim | verificado por hash da configuração |

O slippage é medido **contra o VWAP do dia inteiro**, inclusive o leilão de abertura, ao
qual uma ordem enviada às 10:20 nunca teve acesso. É uma referência dura de propósito: o
viés tem de ser contra a estratégia.

---

## Se der vontade de mexer num parâmetro

Não mexa em silêncio. O caminho é `python3 -m quant.versoes --registrar`, e ele recusa a
terceira mudança do ano, recusa versão sem backtest comparado, e faz a versão nova rodar
3 meses de paper em paralelo antes de valer — enquanto isso, quem manda é a anterior.

Mexer sem registrar não é bloqueado por ninguém, mas aparece: o painel mostra **MUDANÇA
NÃO REGISTRADA** com a lista de campos, o relatório mensal repete, e a campanha reprova o
critério de parâmetros intocados. Se a mudança valia a pena, registre; se não valia,
desfaça. As duas coisas são aceitáveis — deixar assim não é.

## O que a Fase 4 não é

Ela **não** testa se a estratégia ganha dinheiro. Isso é a Fase 2 (backtest), e continua
sem ter rodado com dado real. A Fase 4 testa se a *operação* funciona: se a boleta sai, se
as ordens executam, se o custo é o modelado, e se o humano na ponta consegue manter a
disciplina por três meses seguidos. Passar na Fase 4 com um backtest ruim significa que
você aprendeu a executar com precisão uma estratégia que perde dinheiro.
