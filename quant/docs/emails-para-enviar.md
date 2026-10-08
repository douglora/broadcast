# Dois e-mails para enviar esta semana

Os dois passos que podem encerrar o projeto antes de começar dependem de resposta por
escrito. Estão prontos abaixo: copie, ajuste o nome do destinatário e envie.

Guarde as respostas. A do compliance é o documento que te protege; a do Safra é o número
que decide se o desenho fecha.

---

## E-mail 1 — Safra: tabela de custos

**Para:** seu assessor no Safra
**Assunto:** Tabela de custos para operação própria em ações — pedido por escrito

> Prezado [nome],
>
> Estou estruturando uma carteira própria de ações com rebalanceamento sistemático e
> preciso dimensionar o custo antes de começar. O perfil é de **ordens frequentes e
> pequenas**: estimo cerca de 200 ordens por ano, com valor médio em torno de R$ 3 mil,
> em ações à vista e no fracionário, mais 1 a 2 contratos de mini-índice para hedge.
>
> Poderia me enviar **por escrito** as seguintes informações?
>
> 1. Corretagem por ordem em **ações à vista**, lote padrão.
> 2. Corretagem por ordem no **fracionário** — se a tabela for diferente da anterior.
> 3. Se existe **corretagem mínima por nota ou por ordem**, e se ordens do mesmo papel
>    executadas no mesmo pregão são cobradas como uma nota ou como várias. (Pergunto
>    porque parte das ordens será fatiada em 2 ou 3 dias.)
> 4. **Custódia** mensal e qualquer taxa de manutenção de conta.
> 5. Tarifa por **contrato de mini-índice (WIN)**, por lado, e se há custo adicional na
>    rolagem de vencimento.
> 6. Se existe **tabela por volume**, pacote negociável, ou condição específica para
>    profissionais vinculados.
>
> Aproveito para confirmar dois pontos operacionais:
>
> 7. O Safra aceita **Tesouro Selic como margem** para posição em mini-índice? Se sim,
>    com qual deságio (*haircut*)?
> 8. Existe integração com **MetaTrader 5** em conta pessoa física, com envio de ordens
>    de ações à vista e fracionário? Se sim, exige plano pago e permite Expert Advisor?
>
> Obrigado,
> Douglas

**O que fazer com a resposta:** rode a conta e leia o veredito.

```bash
python3 -m quant.custos --corretagem <valor por ordem>
```

O teto no cenário base é **R$ 1,54 por ordem**. Acima disso a estratégia trabalha para a
corretora — e o comando diz isso com todas as letras.

---

## E-mail 2 — Compliance: negociação em conta própria

**Para:** compliance da intermediária a que você é vinculado
**Assunto:** Negociação em conta própria — consulta sobre política interna e Res. CVM 178

> Prezados,
>
> Na condição de assessor de investimentos vinculado, gostaria de confirmar por escrito as
> regras aplicáveis à minha **negociação em conta própria**, antes de iniciar qualquer
> operação.
>
> A operação que pretendo montar tem estas características, que podem ser relevantes para
> a análise:
>
> - carteira própria de ações listadas na B3, entre 15 e 25 nomes;
> - seleção **sistemática** por regras fixas, sem decisão discricionária caso a caso;
> - rebalanceamento incremental, com ajustes que podem ocorrer em qualquer pregão;
> - hedge parcial com contratos de mini-índice;
> - horizonte de permanência típico de meses, com teto de 12 meses por posição.
>
> Peço confirmação sobre:
>
> 1. As exigências da **Resolução CVM 178** aplicáveis ao meu caso.
> 2. A **política interna** da instituição quanto a operações em conta própria: há
>    necessidade de pré-aprovação de ordens? Comunicação prévia ou posterior?
> 3. Existe **período mínimo de permanência** (*holding period*) para ativos adquiridos em
>    conta própria? Em caso afirmativo, qual o prazo?
> 4. Existe **lista restrita** de ativos, ou vedação a ativos cobertos por research da
>    casa?
> 5. Há **obrigação de operar exclusivamente** por meio da instituição?
> 6. Alguma exigência específica quanto a **derivativos** (mini-índice) em conta própria?
>
> Fico à disposição para detalhar a estratégia caso seja necessário para a análise.
>
> Atenciosamente,
> Douglas

**O que fazer com a resposta:** se houver *holding period* mínimo ou restrição de ativos,
isso **muda o desenho da estratégia** — e mudar o desenho é registrar uma versão nova, não
remendar o código:

```bash
python3 -m quant.versoes --registrar "restricao de compliance" "holding period de N dias" \
  --backtest '{"observacao": "impacto a medir no backtest"}'
```

Se houver obrigação de operar exclusivamente pela casa, some a alternativa de abrir conta
numa corretora de corretagem zero, e o e-mail 1 passa a ser eliminatório sozinho.
