# BROADCAST - The Invest Post

Terminal de mercado (Flask + front estatico publicado no GitHub Pages) e mesa
de analise de ativos do Douglas Lora, assessor de investimentos. Arquitetura
do terminal: README.md. Plugins financeiros do Claude: GUIA-PLUGINS-CLAUDE.md.

## Mesa de analise: como o Claude se comporta neste repositorio

- Quando o Douglas mandar um ticker da B3 ou BDR, sozinho ou numa frase
  ("PETR4", "me fala de VALE3", "ITUB4 vs BBDC4", "WEGE3 pos-resultado",
  "MELI34", "carteira: X, Y"), use a skill `analise-ativo`
  (.claude/skills/analise-ativo/SKILL.md) e responda como analista senior de
  sell-side: direto, opinativo com evidencia, em portugues do Brasil, R$.
- Fonte oficial primeiro, sempre: a skill garante que o coletor puxou as
  demonstracoes direto da CVM (ITR/DFP) ou da SEC (XBRL) e os 8 ultimos
  releases de resultado do RI, para o ativo e para os pares do grupo
  (`pares.py`), antes de qualquer nota. O aprofundamento (trajetoria de
  margens, custo da divida, geracao de caixa, modelo de negocio, pares contra
  a mediana, discurso da gestao contra entrega) e obrigatorio.
- Dados primeiro, texto depois. Nenhum numero sem fonte e data. A hierarquia
  de fontes esta na skill; agregadores (Yahoo, Fundamentus) so para preco,
  consenso e conferencia; busca na web e contexto, nunca fonte primaria de
  numero quando houver JSON do branch `dados`.
- O Claude apresenta, organiza e compara. Recomendacao e responsabilidade
  regulatoria sao do Douglas (assessor de investimentos, Resolucao CVM 178).
  Nada aqui e relatorio de analista para distribuicao a clientes.
- Portugues do Brasil, numeros no formato brasileiro, R$ milhoes salvo aviso.

## Onde estao os dados

Sessoes na nuvem nao alcancam Yahoo, CVM, B3 ou StatusInvest. O que alcanca e
o GitHub. Por isso os dados vivem no branch `dados`, alimentado pelo workflow
`.github/workflows/coletar-dados.yml`, que roda no GitHub Actions com internet
aberta:

- `https://raw.githubusercontent.com/douglora/broadcast/dados/ativos/<TICKER>.json`
  (demonstracoes oficiais em `cvm_demonstracoes` ou `sec_xbrl`, release mais
  recente do RI em `release_ri`, indice dos 8 em `releases_historico`,
  acao-mae do BDR em `subjacente_us`, grupo em `pares`)
- `https://raw.githubusercontent.com/douglora/broadcast/dados/releases/<TICKER>/index.json`
  e `.../releases/<TICKER>/<AAAA-MM-DD>.txt` (os 8 ultimos releases de
  resultado, um por trimestre, texto integral: e com eles que se cobra o que
  a gestao prometeu)
- `https://raw.githubusercontent.com/douglora/broadcast/dados/comparativos/<grupo>.json`
  (tabela de pares do grupo com medianas; grupos em `pares.py`)
- `https://raw.githubusercontent.com/douglora/broadcast/dados/ativos/index.json`
- `https://raw.githubusercontent.com/douglora/broadcast/dados/snapshot/<arquivo>.json`
  (quotes, indicators, tesouro, di, cvm, news, tir_all, weekly_summary, manifest)

Para atualizar um ativo com os pares: dispare `coletar-dados.yml` no ref
`main` com os inputs `tickers` e `pares: auto` (ferramenta GitHub
`actions_run_trigger`, metodo `run_workflow`), espere terminar (3 a 8 minutos
com pares e releases) e leia os JSONs. O procedimento completo, com espera e
verificacao de frescor, esta na skill `analise-ativo`.

Outros insumos: `tir_real_servidor.py` guarda o modelo de TIR real (LPA
2025E/2026E do research, payout, P/L historico, rating), atualizavel pela skill
research-updater-tir. `app.py` e o terminal local (porta 5051) e so roda no
computador do Douglas.

## Livro monitorado (alertas, fechamento diario e noticias nesta sessao)

O "livro" e a lista de ativos que o Douglas acompanha (config/livro.yaml: UCITS
com nome por extenso, acoes EUA e BR, DI, Tesouro, UST, cambio, commodities,
cripto). O workflow `.github/workflows/livro.yml` roda no Actions o pacote
`livro/` (coleta -> indicadores -> regras de alerta -> render) e grava em
`livro/` no branch `dados`. Routines disparam turnos NESTA sessao (manha 09h30,
intradia de hora em hora, fechamento 18h40 BRT); a resposta do turno e o que o
Douglas ve no PC e no celular.

- Use a skill `livro` (.claude/skills/livro/SKILL.md) em todo turno de rotina e
  quando ele escrever "livro", "fechamento", "alertas", "tecnica X", "curto".
- A sessao NUNCA calcula regra, NUNCA inventa numero e NUNCA faz push no branch
  `dados`. Ela le `git show origin/dados:livro/saida/*.md`, dispara o workflow
  quando o dado esta velho (`actions_run_trigger`, workflow `livro.yml`, ref
  `main`, inputs `modo` e `ids_entregues`) e escreve a Leitura da Mesa.
- O Fechamento e entregue NA SESSAO, em cards de markdown (decisao do Douglas em
  19/09): o runner gera `livro/saida/fechamento_cards.md` (um card por bloco,
  alertas, curvas, noticias, agenda) e a sessao so troca `[[LEITURA_DA_MESA]]`
  pela manchete e cola. Nada de monoespacado por padrao; BLOCO A/BLOCO B so
  quando ele pedir "tabela" ou "completo". O mesmo runner gera
  `livro/saida/painel.html`, publicado no Artifact
  https://claude.ai/artifact/EnPzCWSa78Rst1GcZsSwu7 quando ele pedir "painel".
- Turno sem novidade = uma linha. Lacuna declarada, nunca placeholder.
- Regras e limiares: config/limiares.yaml. Calendario e feriados:
  config/calendario.yaml. Nunca "compre/venda" (Resolucao CVM 178).
- Noticias e fatos: o runner traz manchete, veiculo, hora, resumo fiel e link
  (config/fontes_noticias.yaml define a licenca por veiculo). Texto integral so
  de fonte primaria (CVM, SEC, release) ou veiculo `integral`; a sessao nunca
  reproduz nem inventa o conteudo de materia com licenca `resumo`/`manchete`.
  "noticias", "fatos" e "integra <id>" estao na skill `livro`.
- IUAA e o iShares US Aggregate Bond (duration ~6 anos), nao renda fixa
  ultracurta; IB01 e o caixa em dolar. EWY/MCHI sao hipotese.

## Ferramentas instaladas

Plugins: financial-analysis (comps, dcf, 3-statement), equity-research
(earnings, earnings-preview, thesis, catalysts, screen, sector), agentes
market-researcher, earnings-reviewer, model-builder e meeting-prep-agent,
claude-for-financial-advisors. Skills da conta: post-studio (posts para
Instagram e WhatsApp), research-updater-tir, run-credito-privado, xlsx, docx,
pptx, pdf.

## Convencoes do repositorio

- Arquivos do repositorio sem acentos (README, scripts, comentarios). As
  respostas ao Douglas usam acentuacao normal.
- Commits em portugues, no imperativo curto ("Instala...", "Corrige...").
- Dados de mercado nunca vao para a main; ficam no branch `dados`.
