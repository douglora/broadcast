# Handoff: a mesa BROADCAST sai da nuvem e passa a rodar no computador do Douglas

Escrito em 01/10/2026 pela sessao Claude Code na web "Ferramentas para assessoria de
investimentos" (`session_015YuN1wiZ8G2GovL7vnA4QN`, repo douglora/broadcast, branch de trabalho
`claude/investment-advisory-tools-3eln16`). Quem ler isto e o agente local. O Douglas pediu que a
mesa rode no computador dele daqui em diante, e que este arquivo ja traga as melhorias pedidas
como se o agente fosse local.

Leia junto: `CLAUDE.md` (como a mesa se comporta), `.claude/skills/` (analise-ativo, deep-search,
dados-completos, livro), `README.md` (terminal), `ferramentas/etf/README.md` (analise de ETFs).

## 1. O que muda rodando local

Ganha:
- Internet aberta. Yahoo, CVM, B3, FRED, Tesouro, justETF, sites de RI e de noticias respondem
  direto. Na nuvem o proxy bloqueava esses sites, e toda coleta passava pelo GitHub Actions
  (3 a 8 minutos por ativo). WebFetch tambem funciona local (na nuvem so havia WebSearch).
- Arquivos do PC: PDFs e planilhas do Douglas (por exemplo o "Selecao UCITS" da Avenue, que
  nunca chegou na nuvem) e as pastas `Desktop\Assessoria Safra` e `Desktop\BROADCAST`.
- O terminal `app.py` (porta 5051) roda na mesma maquina.
- Os conectores de dados do plugin claude-for-financial-advisors (FactSet, Morningstar, S&P,
  Daloopa, Addepar e outros) falharam na nuvem por proxy. Local, eles tentam conectar de verdade;
  cada um depende de assinatura do Douglas.

Nao muda:
- O branch `dados` continua sendo o armazem compartilhado (celular, Actions, artifacts). A sessao
  nunca da push no `dados` (regra do CLAUDE.md e `deny` no `.claude/settings.json`).
- O GitHub Actions continua coletando sozinho, mesmo com o PC desligado: `livro.yml` as 08h20 e
  18h05 de Brasilia; `coletar-dados.yml`, `etfs.yml` e `kinea.yml` sob demanda.
- Tudo o que esta em "Regras que nao mudam" (secao 6).

Atencao: rotina local so roda com o PC ligado e o app aberto. Em 29/09 duas rotinas locais foram
suspensas por "device_absent" (PC desligado). Por isso a coleta fica no Actions e o local cuida
da analise e da narracao.

## 2. Instalacao no Windows (checklist)

1. Git for Windows. Ele da o Bash ao Claude Code, e o hook de inicio do projeto chama `bash`.
2. Python 3.11 ou mais novo, com "Add Python to PATH". No Windows o comando e `py` (ou
   `python`); os skills e o CLAUDE.md escrevem `python3`.
3. Claude Code pelo instalador do PowerShell (https://code.claude.com/docs/en/setup), com login
   na mesma conta claude.ai.
4. Clonar numa pasta nova, sem mexer na `C:\Users\Douglas\Desktop\BROADCAST` antiga ate validar:
   `git clone https://github.com/douglora/broadcast C:\Users\Douglas\broadcast` e, dentro dela,
   `git fetch origin dados`.
5. Dependencias: `py -m pip install -r requirements.txt -r requirements-livro.txt`.
6. GitHub CLI: `winget install GitHub.cli` e `gh auth login` na conta douglora. Na nuvem, os
   skills disparavam os workflows pela ferramenta MCP do GitHub (`mcp__github__actions_run_trigger`),
   que vinha pronta. Local, ela so existe se o servidor MCP do GitHub for configurado; sem ele,
   use `gh workflow run livro.yml --ref main -f modo=fechamento -f ids_entregues=...` e
   `gh run list --workflow livro.yml` (item 4 do P1).
7. Validar: `py mesa.py skills` (tem de dizer TUDO OPERANDO), `py mesa.py frescor CURY3`,
   `py -m pytest -q`. Se o console estragar acentos: `set PYTHONIOENCODING=utf-8`.
8. Abrir a sessao na pasta com `claude remote-control`. Ela aparece no app Claude do celular e em
   claude.ai/code, com o codigo rodando no PC (https://code.claude.com/docs/en/remote-control).
   O Claude Desktop tambem serve.
9. Opcional, para trazer o historico da sessao da nuvem: `claude --teleport` na pasta clonada
   (escolha a sessao "Ferramentas para assessoria de investimentos"). Exige o branch no remoto,
   arvore limpa e a mesma conta. O historico e longo (cerca de 630 mil tokens, ja compactado);
   comecar uma sessao nova com este arquivo e mais limpo.

## 3. Rotinas: o que existe e como fica

Rotina da nuvem nao dispara em sessao local. As do livro precisam ser recriadas como tarefas
agendadas do Claude Desktop (https://code.claude.com/docs/en/desktop-scheduled-tasks), ou com
`/loop` numa sessao que fique aberta. Horarios em Brasilia; os prompts estao no anexo A.

| Rotina | Horario | Onde roda hoje | O que fazer |
|---|---|---|---|
| livro-manha-0830 (`trig_01UBj3483wSv265TujrMCg5j`) | 08h31, seg-sex | nuvem, sessao `session_01Vb67yBerNLC3nNQKotGsZi` | recriar local; desligar a da nuvem so depois de um dia de teste |
| livro-intradia (`trig_0167TwyUn1bg2kwABzh8KqmY`) | 10h20 a 17h20, de hora em hora | nuvem, mesma sessao | idem |
| livro-fechamento-1800 (`trig_01TCY9j5uTYswEXKzFb8N6Qz`) | 18h11, seg-sex | nuvem, mesma sessao | idem |
| Resumo semanal mercado (`trig_012FVbKSk3UD7j1yysYUFyrg`) | seg 07h30 | ja local (Desktop) | manter |
| Tir digest semanal (`trig_01Y9t5HGUDCpFDMsZ3MAJs6j`) | seg 09h00 | ja local (Desktop) | manter |
| Broadcast daily fund update (`trig_01DKUN54hT8NCnx8CciQGFfT`) | 07h00, seg-sex | local, DESLIGADA em 29/09 (device_absent) | aponta para `daily_update.py` e porta 5050, que nao existem neste repo (o terminal atual e `app.py` na 5051): perguntar ao Douglas se religa, corrige ou apaga |
| Cvm fatos relevantes daily (`trig_01TGDQMHGxYL2BcV8aYdYttp`) | 07h00, seg-sex | local, DESLIGADA em 29/09 (device_absent) | idem; o coletor do repo ja traz os fatos da CVM por ativo |

Desligar uma rotina da nuvem e reversivel, mas e decisao do Douglas: confirme com ele antes.

## 4. Estado do trabalho em 01/10/2026

Artifacts publicados:
- Painel do livro: https://claude.ai/artifact/EnPzCWSa78Rst1GcZsSwu7 (republicado pelas rotinas)
- Carteira modelo UCITS: https://claude.ai/artifact/MbzW2Y3yzKCGDHf3fE6s6d
- Entrada nos UCITS (29/09): https://claude.ai/artifact/BHUnMzteyivcHye62LFaMv
- MCMV a prova: https://claude.ai/artifact/XovhG33G7Sg18oE6oVfw3v
- Margem por faixa: https://claude.ai/artifact/HjMge9hso5a51tbKbU4nLB
- Cury contra Direcional: https://claude.ai/artifact/BvdN5eDzViyY6553hs6rmK
- O Preco da Direcional: https://claude.ai/artifact/P7accDiT6tUUqEgyZAJaG8
- MCMV sob Aperto: https://claude.ai/artifact/4sy2AfX7SN2qEeyR2MMfnX

Pendencias abertas com o Douglas:
1. CURY3. A queda de 30/09 (-3,4%, contra -0,5% da DIRR3) nao tem documento nem noticia. Ate
   13h as tres de baixa renda (CURY3, DIRR3, TEND3) cairam juntas, no dia da rotacao eleitoral e
   do fim da greve da Caixa (TST em 29/09). A tarde so a Cury nao voltou. Em aberto: o que
   houve em 17/09 (CURY3 -5,2% com a DIRR3 estavel); a previa operacional do 3T26, na primeira
   quinzena de outubro (a do 2T26 saiu em 07/07 e a acao caiu 7,9% em 08/07).
2. VALE3, venda de puts. Os premios foram estimados por Black-Scholes (vol 30%, CDI 13,65%)
   porque a cadeia de opcoes nao era acessivel da nuvem. Refazer com a cadeia real.
3. UCITS. Conferir as conclusoes de 5 anos com o PDF "Selecao UCITS" da Avenue.
4. Calendario. 1o turno em 04/10 e 2o turno em 25/10. O Conselho Curador do FGTS vota o
   orcamento de 2027 a 2029 no fim de outubro.

Codigo novo desta sessao: `etfs.py` e `.github/workflows/etfs.yml` (coletor de ETFs, ja na
main) e `ferramentas/etf/` (analise de ETFs, com README).

## 5. Melhorias pedidas ao agente local (em ordem)

### P1. Funcionar local (primeiro dia)
1. Hook de inicio por sistema operacional. Hoje o `SessionStart` roda
   `bash "$CLAUDE_PROJECT_DIR/INSTALAR-PLUGINS-CLAUDE.command"`; no Windows sem Git Bash ele
   falha. Rodar o `.bat` no Windows e o `.command` nos demais.
2. Permissoes. Duplicar no `.claude/settings.json` as regras de `python3` para `py` e
   `python`. Nos skills, uma linha: "no Windows, `py` no lugar de `python3`". A espera com
   `python3 -c "import time; time.sleep(N)"` existia porque `sleep` era bloqueado na nuvem.
3. Validar `mesa.py`, `livro` e `ferramentas/etf` no Windows: encoding UTF-8, caminhos e
   `git show origin/dados:...`.
4. Disparo de workflow sem a ferramenta MCP do GitHub. Os skills `livro`, `analise-ativo`,
   `deep-search` e `dados-completos` mandam disparar com `mcp__github__actions_run_trigger` e
   conferir com `mcp__github__actions_list`. Acrescentar a alternativa com `gh workflow run` e
   `gh run watch`, ou configurar o servidor MCP do GitHub com token de acesso (sem commitar o
   token). Conferir tambem se o `PushNotification` funciona local; se nao, a resposta no app basta.
5. Recriar as tres rotinas do livro como tarefas agendadas locais. Rodar um dia inteiro e so
   entao pedir ao Douglas para desligar as da nuvem.

### P2. Aproveitar a internet aberta
6. Coleta local rapida: `py mesa.py coletar TICKER --local` rodando `coletar_dados.py` direto,
   sem esperar o Actions. Grava num cache local ignorado pelo git (por exemplo `dados_local/`),
   que o `mesa.py` le antes do branch. O branch `dados` continua sendo escrito so pelo Actions.
7. Fita intradia. A cada rodada do livro, gravar um arquivo por dia com preco, variacao e volume
   de cada ativo. Em 30/09 o caminho hora a hora da CURY3 so saiu reconstruindo o historico do
   git das series.
8. "Por que mexeu" com investigacao automatica quando o livro diz "sem causa no dado":
   - documentos da CVM do dia para o ativo;
   - a hora em que a divergencia comecou (abertura, meio do pregao, leilao);
   - volume contra a media e fechamento na minima;
   - noticias do horario;
   - no periodo eleitoral, as pesquisas com horario de divulgacao.

   O caso CURY3 de 30/09 e o teste: a resposta tem de separar a parte setorial da manha da
   parte so da Cury a tarde.
9. Opcoes da B3: `py mesa.py opcoes VALE3`, com cadeia, volatilidade implicita, delta e premio
   real. Escolher a fonte e conferir a licenca antes.
10. Calendario de catalisadores: previas operacionais, resultados, Copom e Fed, eleicao e FGTS,
   marcando data confirmada e data estimada.

### P3. Consolidar o que ficou na nuvem
11. Transformar `ferramentas/etf/` em comandos do `mesa.py`: `etf tecnica`, `etf ranking`,
    `etf sensibilidade`, `etf relatorio`.
12. `etfs.py`:
    - `cotacoes.json` e sobrescrito por coleta parcial; mesclar com o anterior;
    - na LSE, inserir no proprio coletor o pregao anterior que o Yahoo omite com o pregao
      aberto. Hoje isso e feito na analise.
13. Ler o PDF "Selecao UCITS" local e conferir as conclusoes de 5 anos (pendencia 3).
14. Testar os conectores do plugin claude-for-financial-advisors e os de dados. Se houver
    assinatura, usar como fonte de consenso e de P/L historico; faltou o P/L historico dos ETFs
    no relatorio de 29/09.
15. Atualizar o `CLAUDE.md`:
    - uma secao "modo local", com caminhos, comandos `py` e rotinas locais;
    - corrigir a frase "Routines disparam turnos NESTA sessao".

## 6. Regras que nao mudam

- Respostas ao Douglas em portugues do Brasil, com acentos. Arquivos do repositorio sem
  acentos. Commits em portugues, no imperativo curto.
- Toda pesquisa comeca por `mesa.py skills` e abre com a linha de skills e comandos usados.
- Frescor e cobertura antes de escrever. Dado velho ou lacuna vira a primeira frase.
- Nunca "compre" ou "venda" (Resolucao CVM 178) e sem preco-alvo proprio. A recomendacao e do
  Douglas.
- Dado de mercado so no branch `dados`. A sessao nunca da push no `dados`.
- Formato para celular:
  - abrir com "Em uma frase";
  - tabelas de ate 4 colunas;
  - siglas explicadas na primeira vez;
  - fechar com "Termos desta nota" e "Quer aprofundar?".
- Busca web marcada como tal. Nunca reproduzir integra de materia com licenca de resumo ou
  manchete.

## 7. Primeira mensagem para a sessao local

> Leia HANDOFF-LOCAL.md e CLAUDE.md. Voce agora roda local, no Windows do Douglas, com
> internet aberta. Faca o checklist da secao 2 e me diga o que passou e o que falhou. Depois
> execute o P1 da secao 5 (itens 1 a 5). Nao desligue nenhuma rotina da nuvem sem eu confirmar.

## Anexo A. Prompts das rotinas do livro (copiar como estao)

No Windows, troque `python3` por `py`.

### livro-manha-0830 (08h31 de Brasilia, seg-sex)

```
Turno de rotina do livro monitorado, slot MANHA (08h31 BRT). Siga a skill `livro` (.claude/skills/livro/SKILL.md).

COMO ESTE TURNO FUNCIONA: o workflow `livro.yml` ja roda sozinho no Actions as 08h20 BRT (cron `20 11 * * 1-5`). Quando voce acorda, na maioria dos dias o dado da manha JA ESTA no branch `dados` e voce so le e narra - nao dispare por reflexo.

1. DEAD-MAN PRIMEIRO: confira se o FECHAMENTO do pregao anterior saiu (`saida/fechamento.json` com `gerado_em` posterior as 18h00 daquele dia). Se nao saiu, isso e a PRIMEIRA linha da resposta, com o motivo apurado (run do Actions, anotacao, lacuna), nunca silencio.
2. FRESCOR: `git fetch origin dados` e leia `livro/saida/manifest.json`. SO SE o slot `manha` de hoje nao estiver la, dispare `livro.yml` no ref `main` com modo=manha e ids_entregues (os ids narrados no turno anterior) e espere em laco de segundo plano, ate 8 min.
3. PORTAO DE QUALIDADE (skill, passo 3b, R0 a R10): rode `python3 -m livro.portao` e leia `drivers` e `qualidade` do `saida/fechamento.json`. O runner ja usa o contrato explicito do Brent (BZX26.NYM ate 30/09, depois BZZ26) e o dolar das 17h; serie que nao sai "ok" nao entra em frase causal, tese nem push, e so ela pede WebSearch rotulado (R4). Nenhuma narrativa de "divergencia" (acao contra o driver, real firme com dolar forte) com uma perna fora de ok.
4. CORRECAO: se `leitura_insumos.correcoes` nao estiver vazio (CORRECAO de numero ou RETIRADO de alerta ja enviado), o card de correcao abre a resposta e o push e OBRIGATORIO com o `push_sugerido`, que ja abre com ela.
5. Cole `saida/manha_cards.md` inteiro, com a sua Leitura da Mesa no lugar de [[LEITURA_DA_MESA]], deixando claro que os precos sao o fechamento do pregao anterior (a B3 abre as 10h) e que as curvas de DI, Tesouro e Treasury sao as oficiais de D-1. Use o card "Por que mexeu" e "Setores do dia" como base causal; "sem causa no dado" nao vira causa inventada. Inclua o card de commodities em dolar. De o numero da CURY3.
6. Republique OBRIGATORIAMENTE o painel no Artifact https://claude.ai/artifact/EnPzCWSa78Rst1GcZsSwu7 (leia o Artifact antes, troque SO o [[LEITURA_DA_MESA]] do painel pelo mesmo texto; a faixa de correcao ja vem do runner) e feche a resposta com o link. Se a republicacao falhar, diga a falha em uma linha e siga.
7. Push: correcao (passo 4), alerta critico ou de atencao. Nunca para info.

SE ALGO QUEBRAR, a falha vira a primeira linha: `git fetch` com 503 -> leia pelo CDN `https://raw.githubusercontent.com/douglora/broadcast/dados/livro/saida/<arquivo>?nocache=$(date +%s)$RANDOM`; sem a ferramenta do GitHub voce nao dispara o workflow, entao entregue o ultimo dado com o horario em destaque e a lacuna declarada; workflow com `startup_failure` -> leia a anotacao do run e diga a causa em portugues.
```

Observacao: o Brent de novembro (BZX26) venceu em 30/09; a partir de outubro o contrato e o de
dezembro (BZZ26).

### livro-intradia (10h20 a 17h20 de Brasilia, de hora em hora, seg-sex)

```
Turno de rotina do livro monitorado, slot INTRADIA. Siga a skill `livro` (.claude/skills/livro/SKILL.md): frescor (20 min) -> disparo modo=intradia com ids_entregues -> espera (laco em segundo plano) -> se intradia.md e a linha 'sem alerta novo', responda so essa linha; senao cole os alertas e faca o push agrupado.
```

### livro-fechamento-1800 (18h11 de Brasilia, seg-sex)

```
Turno de rotina do livro monitorado, slot FECHAMENTO (18h11 BRT). Siga a skill `livro` (.claude/skills/livro/SKILL.md).

COMO ESTE TURNO FUNCIONA: o workflow `livro.yml` ja roda sozinho no Actions as 18h05 BRT (cron `5 21 * * 1-5`). Quando voce acorda, na maioria dos dias o dado do fechamento JA ESTA no branch `dados` e voce so le e narra - nao dispare por reflexo.

1. FRESCOR: `git fetch origin dados` e leia `livro/saida/manifest.json`. O dado so serve se `slot` for `fechamento` E `gerado_em_brt` for POSTERIOR as 18h00 do dia de hoje (hora em que a B3 fecha). Dado das 17h5x e intradiario e NAO pode ser apresentado como fechamento.
2. SO SE nao estiver fresco: dispare `livro.yml` no ref `main` com modo=fechamento e ids_entregues (os ids que voce narrou no turno anterior) e espere em laco de segundo plano, ate 8 min. Se o cron das 18h05 estiver apenas atrasado, o seu disparo resolve do mesmo jeito.
3. PORTAO DE QUALIDADE (skill, passo 3b, R0 a R10): rode `python3 -m livro.portao` e leia `drivers` e `qualidade` do `saida/fechamento.json`. O runner ja usa o contrato explicito do Brent e o dolar das 17h; serie que nao sai "ok" (dia de dois pregoes, barra descartada, velha) nao entra em frase causal, tese nem push, e so ela pede WebSearch rotulado (R4). Nenhuma narrativa de "divergencia" (acao contra o driver, real firme com dolar forte la fora) com uma perna fora de ok.
4. CORRECAO: se `leitura_insumos.correcoes` nao estiver vazio (CORRECAO de numero ou RETIRADO de alerta ja enviado), o card de correcao abre a resposta e o push leva o `push_sugerido`, que ja abre com ela. Nao cite na Leitura alerta retirado.
5. Cole `saida/fechamento_cards.md` inteiro, com a sua Leitura da Mesa (3 a 6 paragrafos, opinativa com evidencia, sem compre/venda) no lugar de [[LEITURA_DA_MESA]]. Use "Por que mexeu" e "Setores do dia" como base causal; "sem causa no dado" nao vira causa inventada; noticia "a conferir" se cita como manchete, nao como causa. Nada de BLOCO A/BLOCO B por padrao: so se ele pedir "tabela" ou "completo".
6. Republique OBRIGATORIAMENTE o painel no Artifact https://claude.ai/artifact/EnPzCWSa78Rst1GcZsSwu7 (leia o Artifact antes, troque SO o [[LEITURA_DA_MESA]] do painel pelo mesmo texto; a faixa de correcao ja vem do runner) e feche a resposta com o link. Se a republicacao falhar, diga a falha em uma linha e siga.
7. PushNotification com o push_sugerido de `saida/fechamento.json` (< 200 caracteres).
8. Sexta: linha SEMANA.

SE ALGO QUEBRAR, a falha vira a PRIMEIRA linha da resposta, nunca silencio: `git fetch` com 503 -> leia pelo CDN `https://raw.githubusercontent.com/douglora/broadcast/dados/livro/saida/<arquivo>?nocache=$(date +%s)$RANDOM`; sem a ferramenta do GitHub voce nao dispara o workflow, entao entregue o ultimo dado com o horario em destaque e a lacuna declarada; workflow com `startup_failure` -> leia a anotacao do run e diga a causa em portugues.
```
