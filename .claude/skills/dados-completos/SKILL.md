---
name: dados-completos
description: Garante que a mesa so escreva com a janela de trimestres inteira. Dispara antes de qualquer nota ou deep search (as skills analise-ativo e deep-search chamam esta) e quando o Douglas reclamar de dado faltando ou vazio - "faltou o 1T26", "isso ficou vazio", "nao pegou o balanco", "esta desatualizado", "voce nao acessou todos os releases", "cobertura", "atualiza esse ativo", "verifica se tem tudo". Monta a janela obrigatoria pelo calendario (os 8 trimestres cujo prazo legal de divulgacao ja venceu), confere trimestre a trimestre com mesa.py frescor e mesa.py cobertura, dispara a coleta no GitHub Actions ate fechar a janela, e quando nao fecha obriga a lacuna a virar a primeira frase da resposta, com o trimestre pelo nome. Vale para todo ativo: acao da B3, BDR e ADR.
---

# Dados completos (a trava antes de escrever)

Esta skill existe por causa de um erro concreto: em 21/09/2026 um deep search
da DIRR3 foi escrito sem os releases de 1T26 e de 4T25. O veredito de frescor
dizia `ATUAL`, o indice tinha oito linhas, e mesmo assim dois trimestres da
janela nao estavam la. A analise saiu com buraco.

A regra que sai dai vale para **todo ativo**, nao para aquele caso:

> **Deep search quer dizer a janela inteira.** Nenhum numero e escrito antes
> de a janela obrigatoria de trimestres estar fechada, ou de a lacuna estar
> declarada na primeira frase, com o trimestre pelo nome.

## 1. A janela obrigatoria

A janela vem do **calendario**, nunca do que o coletor conseguiu achar. Sao os
8 trimestres a partir do ultimo cujo prazo legal de divulgacao ja venceu (45
dias corridos apos o fim do 1T, 2T e 3T; 90 dias apos o 4T), ou do ITR mais
novo, o que for mais recente.

Em 21/09/2026 a janela e: `2T26 1T26 4T25 3T25 2T25 1T25 4T24 3T24`.

Ela e igual para DIRR3, para PETR4 e para MELI34. Um ativo que nao tem um
desses trimestres esta incompleto, e ponto - a razao (coletor, fonte, empresa
que nao divulgou) entra na resposta, mas nao muda o veredito.

Cinco estados por trimestre, e so o primeiro conta como dado:

| Estado     | O que e                                                            |
|------------|--------------------------------------------------------------------|
| `ok`       | release guardado, com texto que sustenta analise                    |
| `CURTO`    | abaixo de 4 mil caracteres, ou muito abaixo da mediana do ticker    |
| `FRACO`    | documento que nao e release de resultado                            |
| `SUSPEITO` | documento da SEC gravado antes do classificador; nao conferido      |
| `AUSENTE`  | nao existe no branch                                                |
| `n/a`      | anterior a primeira demonstracao oficial: nao existe release dele   |

`CURTO` e `FRACO` sao a armadilha silenciosa: ata de assembleia, dividendo
extraordinario, recompra, venda de ativo e ate as demonstracoes auditadas
inteiras (184 mil caracteres, no caso do XP) entram no lugar do release e a
contagem de "8 releases" fica certa. Linha no indice nao e dado. Tamanho
tambem nao resolve sozinho: o 4T24 do Itau tinha 6 mil caracteres contra 92 mil
dos trimestres irmaos, e o piso relativo e que o pegou.

`n/a` existe para a trava nao travar o que nao tem como existir: companhia
aberta ha um ano nao tem release de dois anos atras. O limite vem da propria
serie de demonstracoes oficiais, e so vale quando ela tem 4 trimestres ou
mais - serie curta e coleta truncada, nao companhia nova.

## 2. As duas travas, nesta ordem

```bash
python3 mesa.py skills            # as skills da mesa estao instaladas e validas?
python3 mesa.py ficha TICKER
python3 mesa.py frescor TICKER    # TRAVA 1, a ponta: o trimestre mais novo e o de hoje?
python3 mesa.py cobertura TICKER  # TRAVA 2, o corpo: os 8 da janela estao la, um a um?
```

Nenhuma cobre a outra. Frescor compara o release mais novo com o ITR e com o
calendario; cobertura percorre a janela trimestre a trimestre. **Indice com 8
linhas e buraco no meio passa no frescor.**

Os dois vereditos aparecem na primeira linha de todo leitor (`ficha`, `serie`,
`releases`, `release`, `linha`, `decompor`), entao nao ha como pular a trava
sem querer:

```
FRESCOR TEND3: ATUAL | COBERTURA 7/8, falta 4T25
```

So `frescor` com saida 0 **e** `cobertura` com saida 0 autorizam escrever
numero. O `cobertura` tem tres saidas:

| Saida | Significado                                  | O que fazer                         |
|-------|----------------------------------------------|-------------------------------------|
| 0     | janela inteira, com texto util                | pode escrever                       |
| 1     | falta trimestre ou o documento nao serve      | dispare a coleta e repita (secao 3) |
| 2     | a coleta de hoje ja relatou a mesma lacuna    | pare de insistir, declare (secao 4) |

Saida 2 quer dizer que o coletor com a regra de janela ja rodou neste ativo nas
ultimas 24 horas e mesmo assim nao achou: ou a companhia nao publicou aquele
trimestre, ou o site de RI bloqueia o coletor (403/WAF, como a PRIO). Repetir a
coleta nao muda nada; o que muda e declarar.

Antes de comparar contra a mediana do grupo, rode
`python3 mesa.py cobertura TICKER --pares`: par com janela furada produz
mediana errada, e a comparacao e o passo 5 do deep search.

## 3. Quando falta: feche a janela

1. Ticker da B3 **NAO MAPEADO** em `ri_fontes.py` (o `frescor` avisa): mapeie a
   central de resultados antes de disparar (WebSearch, entrada em
   `ri_fontes.py`, commit, merge na `main`). Com o indice da CVM fora do ar, o
   site de RI e a unica fonte de release.
2. Dispare a coleta: ferramenta `mcp__github__actions_run_trigger`,
   `method: run_workflow`, `owner: douglora`, `repo: broadcast`,
   `workflow_id: coletar-dados.yml`, `ref: main`,
   `inputs: {"tickers": "TICKER", "pares": "auto"}`.
3. Espere de 3 a 8 minutos com `python3 -c "import time; time.sleep(60)"` (o
   `sleep` do shell e bloqueado aqui) e confirme o fim por
   `mcp__github__actions_list`.
4. Leia o dado fresco por `git fetch origin dados && git show
   origin/dados:ativos/TICKER.json` - o CDN do raw.githubusercontent guarda 5
   minutos e devolveria o JSON velho.
5. **Repita** `python3 mesa.py cobertura TICKER`. Uma coleta pode nao fechar
   tudo: o coletor tem orcamento de tempo por ativo e completa na seguinte.
   Saida 2, ou duas rodadas sem avanco, significam que o documento nao esta na
   fonte - va para o passo 4 desta skill.
6. Ticker que nunca foi coletado nao precisa de mapa: o coletor descobre a
   central de resultados sozinho pelo dominio da companhia e guarda o que achou
   em `ri_descobertos.json`, no branch. Quando o log disser que o site existe
   mas bloqueia o coletor, a fonte nao e o problema: e o robo que nao passa, e
   isso se declara como lacuna em vez de insistir.

O coletor persegue a janela, nao a ponta: ele vai atras do trimestre que falta
mesmo quando ele e **mais antigo** que o release mais novo, consulta o site de
RI quando ha buraco no meio, e nunca apaga do branch o texto que ja tinha.

## 4. Quando nao fecha: a lacuna vira a primeira frase

Dado velho ou faltando nao e motivo para nao responder; e motivo para dizer a
idade e o tamanho do buraco antes de qualquer numero.

- A resposta **abre** com a lacuna, em uma frase, antes do "Em uma frase":
  "Faltam no branch os releases de 1T26 e 4T25; o que segue usa os 6
  trimestres restantes e as demonstracoes oficiais ate o 2T26."
- Todo numero que vier de um trimestre lido leva o trimestre ao lado.
- Nenhum numero e citado de trimestre `AUSENTE` ou `CURTO`. Nunca preencha com
  estimativa propria, com agregador, nem com "provavelmente".
- Conclusao por ausencia so com a janela cheia. Com buraco, "a gestao nunca
  falou disso em 8 trimestres" vira "nao aparece nos 6 trimestres lidos; 1T26 e
  4T25 nao estao no branch". Sao conclusoes opostas.
- WebSearch serve de contexto para a manchete do trimestre que falta, sempre
  marcado como "busca web, nao e fonte primaria", e nunca substitui o release
  na tabela de numeros.
- A secao de fontes fecha repetindo o que faltou e por que.

## 5. Antes de entregar, confira

- [ ] `python3 mesa.py skills` diz TUDO OPERANDO e a resposta abre dizendo
      quais skills e quais comandos operaram (o Douglas pediu isso em toda
      pesquisa, 20/09).
- [ ] `python3 mesa.py frescor TICKER` deu saida 0, ou a idade esta na
      primeira frase.
- [ ] `python3 mesa.py cobertura TICKER` deu saida 0, ou os trimestres que
      faltam estao nomeados na primeira frase.
- [ ] Nos comparativos, `cobertura --pares` conferido; par furado declarado.
- [ ] Nenhum numero de trimestre `AUSENTE` ou `CURTO` na nota.

## 6. Por que o buraco acontecia (para reconhecer a recaida)

Cada um destes ja causou uma nota com informacao vazia. Se voltar a aparecer,
o problema e de coletor, e a correcao e no codigo, nao na nota:

- o coletor so perseguia a **ponta**: com a cabeca em dia, o site de RI nunca
  mais era aberto, e o corte `ate_periodo` descartava todo trimestre mais
  antigo antes do download;
- documento de trimestre ja coberto ia para `descartados` e o descarte se
  auto-renovava a cada 90 dias, escondendo para sempre o arquivo que fecharia
  o buraco;
- o historico era remontado do zero a cada coleta e a poda apagava do branch o
  texto que a coleta do dia nao redescobrisse;
- na rota da SEC (BDR e ADR), comunicado societario entrava como release
  porque o classificador pontuava o rodape juridico e o nome do arquivo;
- a execucao agendada resolvia para **zero ativos**, entao ativos da lista
  padrao ficavam meses sem coleta.

`teste_cobertura.py` cobre a janela, a mescla, a poda e o gatilho sem rede.
Rode antes de mexer no coletor.
