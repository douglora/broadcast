---
name: boletim-b3
description: Leitura do Boletim Diario do Mercado da B3 (BDI) cruzada com o livro do Douglas, entregue em painel (Artifact). Dispara na Routine do boletim (noite, depois da rodada das 21h40 BRT, e manha, depois da rodada das 08h35) e quando ele escrever "boletim", "boletim da B3", "BDI", "painel do boletim", "fluxo estrangeiro", "fluxo por investidor", "quem comprou", "aluguel de PETR4", "aluguel de acoes", "BTC", "vendidos", "short", "corretoras no aluguel", "posicao em aberto", "parede de opcoes", "strikes", "put/call", "dor maxima", "opcoes de PETR4", "IOPV", "ADR", "previa do Ibovespa", "debentures incentivadas", "CRI", "CRA", "credito privado no balcao", "taxa da debenture X", "quem abriu taxa" ou pedir o que a B3 publicou no fechamento. Le o que o GitHub Actions gravou em boletim_b3/ no branch `dados` (python3 mesa.py boletim), confere frescor e completude, dispara o workflow boletim-b3.yml quando o dado esta velho, escreve a Leitura da Mesa em cima dos sinais que o runner calculou e republica o painel no Artifact, sem calcular regra, sem inventar numero e sem "compre/venda".
---

# Boletim Diario do Mercado da B3 (leitura da mesa)

O boletim e o que a propria B3 publica depois de cada pregao: quem comprou e quem
vendeu, quanto de cada acao esta alugado para venda a descoberto e por qual corretora
passou, onde esta a posicao em aberto das opcoes e dos futuros, a taxa de cada negocio de
debenture, CRI e CRA no balcao, o valor de referencia da cota dos ETFs, proventos,
previas de indice e comunicados. E fonte primaria, sem cadastro.

O runner do GitHub Actions (`boletim_b3.py`, pacote `boletim/`) ja coletou, cruzou com
o livro (config/livro.yaml, ativos com mercado B3) e calculou os sinais com os limiares
de config/boletim.yaml. O trabalho desta skill e (1) garantir que o dado e do pregao
certo e dizer se esta completo, (2) escrever a Leitura da Mesa: opinativa, com
evidencia, em portugues do Brasil, e (3) republicar o painel no Artifact.

## Regras que nao se negociam

- A sessao NUNCA calcula regra, NUNCA inventa numero e NUNCA faz push no branch `dados`.
  Todo numero vem de `boletim_b3/<pregao>/resumo.json` (ou de `tabelas/`); se nao esta
  la, e lacuna e vai escrita como lacuna.
- Nenhum numero sem fonte e data. A data nem sempre e a do pregao: o fluxo por
  investidor sai com dois pregoes de atraso (o resumo traz `fluxo.ate`); a carteira de
  indice vale pelo quadrimestre; de noite o painel mostra aluguel e posicoes em aberto
  do pregao anterior, com a etiqueta "dados de DD/MM" no card. Escreva a data que esta la.
- Nunca "compre" ou "venda" (Resolucao CVM 178). Sinal e fato com numero: "o saldo
  alugado de X subiu 30% em 5 pregoes enquanto o preco caiu 6%". A recomendacao e do
  Douglas.
- Dia sem novidade e uma linha. Sinal com `pregoes_seguidos` maior que 1 e estado, nao
  noticia: entra so se mudou de tamanho ou se sustenta a tese do dia.
- PARCIAL nao e erro: a rodada da noite nao tem aluguel nem posicoes em aberto, que a
  B3 publica de madrugada. Diga "parcial, falta X" na primeira linha. Nunca escreva o
  aluguel de D-1 como se fosse de D. Na rodada parcial, `mesa.py boletim TICKER`,
  `boletim opcoes TICKER` e `boletim radar` mostram a posicao do pregao anterior com a
  marca `[POSICAO DO PREGAO ANTERIOR ...]` e a data: cite com essa data.
- Renda fixa do pregao corrente e PRELIMINAR ate a B3 ajustar o balcao (perto do meio-dia
  de D+1): o resumo traz `renda_fixa.preliminar` e a fonte dos sinais diz "(preliminar)".
  Diga isso sempre que citar taxa ou volume do dia. Taxa de papel com volume pequeno pode
  ser um negocio isolado de pessoa fisica; cite o volume ao lado da taxa. Em CRI e CRA o emissor que a B3 informa e a
  securitizadora, nao o devedor. O premio sobre o juro real compara por vencimento, nao
  por duration: e aproximacao e vai dito como tal.
- Corretora no aluguel e intermediario, nao investidor final. Nunca escreva "o banco X
  esta vendido em Y"; escreva "o lado tomador de Y passou X% pela corretora Z".

## Onde estao as coisas (branch `dados`, pasta `boletim_b3/`)

| Caminho | O que e |
|---|---|
| `manifest.json` | ultima rodada: `ultimo_pregao`, completo ou parcial por pregao, falhas, `catalogo_mudou` |
| `painel.html` | a pagina do ULTIMO pregao coletado, que a sessao publica como Artifact, com o marcador `[[LEITURA_DA_MESA]]`; a ultima linha do arquivo diz de que pregao e |
| `tabelas/<Nome>.json` | tabelas pequenas do ultimo pregao, inteiras, como a B3 publicou (cada uma traz o campo `pregao`) |
| `<pregao>/resumo.md` | a mesma leitura em cards de texto, para colar na sessao |
| `<pregao>/resumo.json` | os numeros, com fonte e data por bloco, e a lista `sinais` |
| `<pregao>/status.json` | cadernos em PDF: situacao, hora e link na B3 (o PDF nao e gravado: o completo passa de 50 MB) |
| `<pregao>/index.json` | cada tabela e arquivo: situacao na B3, hora, linhas, falhas |
| `historico.json` | serie compacta do livro nos ultimos 70 pregoes (media de volume, aluguel, futuros, fluxo, put/call) |
| `mercado.json` | fechamento, volume e saldo alugado do IBrA nos ultimos 26 pregoes (radar) |
| `rf_cadastro.json`, `rf_estado.json` | cadastro dos papeis de renda fixa ja vistos e as ultimas taxas por papel |

Leitura canonica:

```bash
python3 mesa.py boletim                 # veredito + resumo.md do ultimo pregao
python3 mesa.py boletim PETR4           # o ativo no boletim e os ultimos 12 pregoes
python3 mesa.py boletim sinais          # so os sinais
python3 mesa.py boletim rf              # debentures incentivadas, CRI e CRA: taxa do dia, premio, quem abriu e fechou
python3 mesa.py boletim opcoes PETR4    # vencimentos, posicao por strike, paredes, dor maxima, series que mudaram
python3 mesa.py boletim radar           # mercado inteiro: aluguel, volume, opcoes, corretoras
python3 mesa.py boletim status          # cadernos, pendencias e falhas
python3 mesa.py boletim tabela IOPV     # uma tabela bruta
python3 mesa.py boletim json radar      # um bloco do resumo em JSON, para outro agente
python3 mesa.py boletim 2026-09-29      # um pregao guardado
```

Sem cache de CDN: `git fetch origin dados` e `git show origin/dados:boletim_b3/<pregao>/resumo.md`.

## Procedimento do turno

1. **Skills.** `python3 mesa.py skills` (regra da casa: abre a resposta dizendo quais
   skills e comandos operaram).
2. **Frescor e completude.** `python3 mesa.py boletim` imprime na primeira linha
   `BOLETIM B3: pregao AAAA-MM-DD | ATUAL ou VELHO | COMPLETO ou PARCIAL | N sinais`.
   - VELHO ou AUSENTE: dispare o workflow (passo 3) antes de escrever.
   - PARCIAL de noite: normal. PARCIAL depois das 09h00 do dia seguinte: dispare de
     novo; se continuar parcial, olhe `boletim status` e diga qual tabela a B3 nao
     publicou (ela informa `aguardando`, `publicando` ou `atrasado`).
3. **Disparo.** `mcp__github__actions_run_trigger`, `method: run_workflow`,
   `owner: douglora`, `repo: broadcast`, `workflow_id: boletim-b3.yml`, `ref: main`,
   `inputs: {"data": "", "dias": "auto"}` (`auto` = os 2 ultimos pregoes; 21 se o historico
   estiver curto). A rodada leva de 2 a 3 minutos. Espere com o
   laco em segundo plano (o mesmo da skill `livro`):

   ```bash
   for i in $(seq 1 20); do git fetch -q origin dados 2>/dev/null; g=$(git show origin/dados:boletim_b3/manifest.json 2>/dev/null | grep -o '"gerado_em": *"[^"]*"' | head -1); if [ "$g" \> "\"gerado_em\": \"<HORA_UTC_DO_DISPARO>\"" ]; then echo "boletim gravado: $g (tentativa $i)"; exit 0; fi; sleep 30; done; echo "boletim nao apareceu em 10 min"; exit 1
   ```

   Se o run falhar: "coleta do boletim falhou as HHhMM" + link do run, e narre o ultimo
   pregao disponivel dizendo a data dele em destaque.
4. **Leitura.** `resumo.md` do pregao. Para aprofundar: `mesa.py boletim TICKER`,
   `boletim rf`, `boletim opcoes TICKER`, `boletim radar`.
5. **Triangulacao.** O runner ja entrega os cruzamentos de dentro da B3 (bloco
   `triangulacao`, sinais, `radar` e `paridades`). Driver de fora (Brent, minerio, MELI na
   Nasdaq, REMX, S&P) so entra pelo livro: `git show origin/dados:livro/saida/fechamento.json`,
   com o portao da skill `livro` (R0 a R10). Sem o driver confirmado, a frase causal nao
   se escreve.
6. **Escrever** a Leitura da Mesa (formato abaixo) e **republicar o painel** (secao Painel).

## O que sai do boletim e como ler (validado em 30/09/2026)

| Bloco (tabela da B3) | O que diz | Como cruzar |
|---|---|---|
| Fluxo por investidor (`SharesInvesVolum`) | Compras e vendas do mes por estrangeiro, institucional, pessoa fisica e bancos; o runner tira o saldo do ultimo dia divulgado | Estrangeiro comprando com Ibovespa caindo (ou o contrario) e a divergencia que interessa; ler com o indice do mesmo dia de `fluxo.ate`, nao com o de hoje |
| Aluguel (`BTBLendingOpenPosition`, `BTBLoanBalance`) | Saldo alugado por acao, % da quantidade teorica do indice, pregoes de giro e taxa media do tomador | Saldo subindo com preco caindo = aposta vendida crescendo. Saldo alto e taxa alta com preco subindo = vendido pressionado a recomprar. Saldo caindo com preco subindo = vendidos ja zerando |
| Aluguel por corretora (`BTBTrade`) | Cada emprestimo do dia, com corretora doadora e tomadora | Concentracao do lado tomador em poucas corretoras diz por onde a venda esta passando; nao diz quem e o investidor |
| Radar (`mercado.json`) | No IBrA inteiro: mais alugadas, aluguel mais caro, saldo que mais mexeu, volume acima de 2x a media, vendidos sob pressao | Ideia fora do livro e contexto setorial para o que esta dentro |
| Negocios (`TradeInformationConsolidated`) | Fechamento, oscilacao, volume e numero de negocios de cada ativo | Volume acima de 2x a media de 20 pregoes sem noticia e o sinal; com noticia, e a confirmacao |
| Opcoes (`DerivativesOpenPosition` + cadastro) | Posicao em aberto por strike e vencimento, put/call, parcela a descoberto, dor maxima, series que mais ganharam e perderam posicao | Parede = strike de maior posicao fora do dinheiro (call acima do preco e teto, put abaixo e piso); perto do vencimento o preco costuma ser atraido ou travado por ela. Serie bem dentro do dinheiro ganhando posicao, ou call e put no mesmo strike, e operacao estruturada, nao aposta de direcao |
| Futuros e quadro (`AnalyticalFramework2`) | Ajuste e taxa do DI, DAP, dolar e indice; contratos em aberto por mercado; calls e puts de dolar | DI abrindo com construtoras (CURY3, DIRR3, MRVE3) e utilities caindo e o cruzamento classico; contratos em aberto subindo com preco andando = posicao nova, nao zeragem |
| Renda fixa (`Trade` + `InstrumentRegistration`) | Debentures incentivadas, CRI e CRA: taxa de cada negocio, taxa media do papel, premio sobre o DAP, quem abriu e quem fechou taxa, emissores | Curva de credito incentivado do dia (taxa x prazo contra o juro real); papel abrindo taxa com volume e o mercado repricando o risco; premio acima de 300 pb e estresse |
| ETFs (`IOPV` + cadastro) | Valor de referencia da cota e numero de cotas emitidas | Premio ou desconto do SMAL11 sobre a cota; criacao de cotas = dinheiro novo entrando. RARA11 nao tem IOPV no boletim: a paridade sai contra o REMX x cambio |
| ADR (`Custody`) | Acoes de cada empresa custodiadas no programa de ADR | Variacao do saldo = fluxo pelo recibo em Nova York |
| Carteiras e previas (`PreviaQuadrimestral`, `Previa`) | Peso de cada acao no Ibovespa e nos setoriais; previas da proxima carteira | Entrada, saida ou mudanca de peso de ativo do livro vira alerta: fundo passivo compra e vende na virada |
| Proventos, subscricao e comunicados | Credito de dividendo e JCP, prazos, editais de leilao e de OPA | Evento em ativo do livro vira linha no card de eventos |

O que o boletim NAO tem (lacuna fixa, nao procure de novo): posicao em aberto de
derivativos por tipo de investidor. O "estrangeiro comprado em dolar futuro" nao sai
daqui; o que ha e o total de contratos por mercado.

## Formato da resposta na sessao

Regras do CLAUDE.md valem inteiras: o Douglas le no celular e nao decora sigla.

1. Linha de operacao: skills e comandos usados, e o veredito do boletim.
2. **Em uma frase**: o fato do dia, com o numero. Se parcial ou velho, isso vem antes.
3. Sinais novos, um por linha, com fonte e data. Sinais repetidos so se mudaram.
4. Os cards do `resumo.md` que tem noticia (tabelas de ate 4 colunas, como o runner gera).
5. **O que eu olharia amanha**: de 1 a 3 verificacoes objetivas (ex.: "se o saldo alugado
   de MRVE3 cair com o preco subindo, os vendidos estao zerando").
6. Lacunas do dia, sem maquiagem.
7. O link do painel, "Termos desta nota" e o menu "Quer aprofundar?" (`boletim TICKER`,
   `boletim rf`, `boletim opcoes TICKER`, `analise-ativo`, `deep-search`).

## Painel (sempre que houver leitura nova)

O painel e uma pagina so, no formato branco e azul do Douglas, gerada pelo runner
(`boletim/painel.py`). E um Artifact, uma URL; republique sempre no MESMO:

**https://claude.ai/artifact/LdEMW5YS5WXpqF72qkx3Kc**

```bash
mkdir -p /tmp/boletim && git show origin/dados:boletim_b3/painel.html > /tmp/boletim/painel.html
tail -1 /tmp/boletim/painel.html      # <!-- pregao AAAA-MM-DD -->: tem de ser o pregao que voce leu no passo 2
# escrever a leitura em /tmp/boletim/leitura.html: 3 a 5 paragrafos <p>...</p>, o primeiro comecando por <b>Em uma frase:</b>
# (cada paragrafo abre com o assunto em negrito: O livro, Posicoes e fluxo, Credito, O que conferir)
python3 - <<'PY'
import io
h = io.open("/tmp/boletim/painel.html", encoding="utf-8").read()
l = io.open("/tmp/boletim/leitura.html", encoding="utf-8").read().strip()
assert "[[LEITURA_DA_MESA]]" in h
io.open("/tmp/boletim/painel_pub.html", "w", encoding="utf-8").write(h.replace("[[LEITURA_DA_MESA]]", l))
PY
```

Publicar com a ferramenta `Artifact` em dois passos: primeiro `action: read` com a `url`
de cima (a ferramenta recusa atualizar um artefato que a conversa ainda nao leu nem
publicou), depois publicar passando a mesma `url` e
`file_path: /tmp/boletim/painel_pub.html`; sem `icon` (o Artifact ja tem o dele). Nao
edite o painel a mao alem da troca do marcador: numero errado se corrige no runner.
A Leitura da Mesa do painel e a mesma da resposta: sem "compre/venda", com a data de
cada numero que nao for do pregao, e dizendo "parcial" quando for.

## Routine (ligada em 01/10/2026, com o ok do Douglas)

Dois turnos por pregao, dez a quinze minutos depois dos crons do workflow
(`boletim-b3.yml`). Cada turno e uma sessao nova na nuvem, clonada da `main`: a skill e o
`mesa.py` valem sempre na versao mais recente, e a sessao nao guarda memoria do turno
anterior (o que ficou para conferir esta na Leitura da Mesa do painel publicado).

| Routine | Quando (BRT) | Cron | O que encontra |
|---|---|---|---|
| `boletim-b3-noite` | 21h50, segunda a sexta | `CRON_TZ=America/Sao_Paulo 50 21 * * 1-5` | rodada das 21h40: pregao de hoje, PARCIAL |
| `boletim-b3-manha` | 08h50, terca a sabado | `CRON_TZ=America/Sao_Paulo 50 8 * * 2-6` | rodada das 08h35: pregao de ontem, COMPLETO |

O cron do Actions e o caminho principal: grava no branch `dados` sem depender de sessao.
A Routine acorda depois, confere e, na maioria dos dias, so le. **Disparar o workflow e o
plano B**, para quando o cron do GitHub atrasar ou falhar.

### Turno da noite (21h50 BRT)

1. `python3 mesa.py skills` e `python3 mesa.py boletim`. A primeira linha tem de dizer o
   pregao de HOJE e ATUAL. PARCIAL e o normal: aluguel, posicoes em aberto e opcoes saem
   de madrugada.
2. VELHO ou AUSENTE: disparo (passo 3 do procedimento) e espera. Hoje nao teve pregao
   (feriado da B3): uma linha dizendo isso, sem republicar.
3. `mesa.py boletim sinais`, `boletim rf`, `boletim radar`; para o que foi noticia,
   `boletim TICKER` e `boletim opcoes TICKER`. Aluguel e opcoes vem do pregao anterior,
   marcados `[POSICAO DO PREGAO ANTERIOR ...]`: cite com essa data.
4. Leitura da Mesa em 5 paragrafos: **Em uma frase**; **O livro**; **Posicoes de DD/MM e
   fluxo**; **Credito (preliminar)**; **O que conferir na edicao da manha**. Republique o
   painel.

### Turno da manha (08h50 BRT)

1. `python3 mesa.py skills` e `python3 mesa.py boletim`. A primeira linha tem de dizer o
   ULTIMO pregao e COMPLETO.
2. PARCIAL depois das 09h00: disparo e espera; se continuar, `boletim status` e diga qual
   tabela a B3 nao publicou. Ontem nao teve pregao: uma linha, sem republicar.
3. Leia no painel publicado (`Artifact`, `action: read`) o paragrafo "O que conferir na
   edicao da manha" da noite anterior e responda a cada item com o dado de hoje
   (`boletim TICKER`, `boletim opcoes TICKER`, `boletim radar`, `boletim fluxo`).
4. Leitura da Mesa em 5 paragrafos: **Em uma frase**; **Aluguel**; **Opcoes e futuros**;
   **Credito** (o pregao de ontem segue preliminar ate perto do meio-dia; os papeis da
   lista `renda_fixa.papeis` entram aqui); **O que conferir na edicao desta noite**.
   Republique o painel.

### Em todo turno

- Resposta no formato desta skill (linha de operacao, Em uma frase, sinais novos, o que
  conferir, lacunas, link do painel). Dia sem sinal novo e uma linha, mas o painel e
  republicado mesmo assim.
- Falha nunca vira silencio: sem dado novo, diga a hora e o link do run, e narre o
  ultimo pregao disponivel com a data em destaque.
- `PushNotification` so com sinal novo em ativo do livro, em papel acompanhado de renda
  fixa ou falha da coleta: uma linha com o fato e o numero.

### Recriar as Routines

`RemoteTrigger` (`action: create`), uma por turno: `cron_expression` da tabela, ambiente
da nuvem do Douglas, `sources` com `https://github.com/douglora/broadcast` e o prompt
"Turno de rotina do Boletim da B3, slot NOITE (ou MANHA). Siga a skill `boletim-b3`
(.claude/skills/boletim-b3/SKILL.md), secao Routine, turno da noite (ou da manha), e
republique o painel no Artifact do boletim." Pausar: `action: update` com `enabled: false`.
Nao mude o horario sem o Douglas pedir.
