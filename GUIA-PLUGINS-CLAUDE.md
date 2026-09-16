# Plugins financeiros do Claude — guia de uso

Este repositorio ja vem com os plugins de **Financial Services** da Anthropic
(analise de empresas, valuation, research) e com o **Claude for Financial
Advisors** (rotina de assessor) configurados para o Claude Code. Este guia diz
o que esta instalado, como ativar em cada lugar e como usar com empresas da B3.

Nada aqui e recomendacao de investimento. Os plugins geram rascunhos de
trabalho de analista; a leitura, a recomendacao e a responsabilidade
regulatoria continuam suas.

---

## O que esta instalado

| Plugin                          | O que traz                                                                                             | Contexto por sessao |
|---------------------------------|--------------------------------------------------------------------------------------------------------|---------------------|
| `financial-analysis` (nucleo)   | `/comps`, `/dcf`, `/lbo`, `/3-statement-model`, `/competitive-analysis`, `/debug-model`; Excel e PPT   | ~2,0k tokens        |
| `equity-research`               | `/earnings`, `/earnings-preview`, `/initiate`, `/model-update`, `/thesis`, `/catalysts`, `/screen`, `/sector`, `/morning-note` | ~1,5k |
| `market-researcher` (agente)    | Setor ou tema: panorama, concorrencia, comps de pares e lista de ideias                                | ~0,9k               |
| `earnings-reviewer` (agente)    | Resultado trimestral: atualiza o modelo, tabela de variacao e rascunho da nota                        | ~0,9k               |
| `model-builder` (agente)        | DCF, comps e 3 demonstracoes em Excel com formulas vivas                                               | ~1,0k               |
| `meeting-prep-agent` (agente)   | Briefing antes da reuniao: `client-review`, `client-report`, `investment-proposal`                     | ~0,5k               |
| `claude-for-financial-advisors` | `pre-meeting`, `post-meeting`, `compliance`, `prospect-intake`, `portfolio-rebalance-review`, `alts-brief`, `estate-and-tax-brief`, `onboarding` | ~3,1k |

Somados, ficam em torno de 10 mil tokens fixos por sessao. E um custo
pequeno para o plano Max. Se quiser enxugar, veja "Manutencao" no fim.

Os plugins sao instrucoes (Markdown), nao dados. Quem traz dados e voce:
arquivos anexados, o terminal BROADCAST ou um conector MCP (secao 4).

---

## Onde funciona e como ativar

### 1. Claude Code na web (claude.ai/code), neste repositorio

O arquivo `.claude/settings.json` declara os dois marketplaces da Anthropic e
os sete plugins. E o mecanismo que a documentacao do Claude Code indica para
sessoes na nuvem, e tambem o que faz o Claude Code de qualquer computador
reconhecer os plugins ao confiar nesta pasta.

Se ao abrir uma sessao os comandos `/financial-analysis:...` nao aparecerem,
peca ao Claude: "rode `bash INSTALAR-PLUGINS-CLAUDE.command --quiet`". Leva
uns 30 segundos e imprime um resumo. Plugins instalados com a sessao ja
aberta passam a valer na sessao seguinte, ou na mesma se voce digitar
`/reload-plugins`.

Quer que isso aconteca sozinho? Veja "Opcional: instalar sozinho ao abrir a
sessao", no fim deste guia.

### 2. Claude Code no seu computador (Mac ou Windows)

Clique duas vezes em:

| Sistema | Arquivo                          |
|---------|----------------------------------|
| macOS   | `INSTALAR-PLUGINS-CLAUDE.command`|
| Windows | `INSTALAR-PLUGINS-CLAUDE.bat`    |

Ele instala no escopo de usuario, entao os plugins valem em **qualquer
pasta** do computador, nao so nesta. Precisa do Claude Code instalado
(https://code.claude.com/docs/en/setup). Alternativa: numa sessao do Claude
Code aberta nesta pasta, peca "rode `bash INSTALAR-PLUGINS-CLAUDE.command --quiet`".

### 3. Cowork (app do Claude para desktop)

O Cowork nao le a configuracao deste repositorio. Instale pelo app:

1. **Settings > Plugins > Add plugin**.
2. Cole `https://github.com/anthropics/financial-services` e escolha na
   lista: Financial Analysis, Equity Research, Market Researcher,
   Earnings Reviewer, Model Builder e Meeting Prep Agent.
3. Para o Claude for Financial Advisors, cole
   `https://github.com/anthropics/claude-for-financial-advisors`, ou
   instale pelo catalogo da Anthropic dentro do proprio Cowork, onde ele
   ja aparece.

No Cowork as skills disparam sozinhas pelo contexto do pedido, e os
comandos `/plugin:comando` tambem funcionam.

### 4. Dados de mercado (opcional)

Os conectores que vem nos plugins (Morningstar, S&P Capital IQ, FactSet,
Daloopa, Moody's, LSEG, PitchBook) exigem assinatura propria do provedor.
Para B3, as opcoes praticas sao:

| Fonte                    | Como ligar                                                                   | Custo                    |
|--------------------------|------------------------------------------------------------------------------|--------------------------|
| Arquivos de RI e CVM     | Anexe release, ITR/DFP e apresentacao. Funciona sem nada instalar.           | Gratis                   |
| Terminal BROADCAST       | Com o terminal rodando, peca para usar `http://localhost:5051/api/...`       | Gratis                   |
| bolsai MCP               | Settings > Connectors > Add custom connector; URL em https://usebolsai.com/mcp | Gratis limitado; Pro pago |
| brapi MCP                | `claude mcp add --transport http brapi https://brapi.dev/api/mcp/mcp`        | So planos pagos          |

Endpoints do terminal que mais ajudam: `/api/quotes` (cotacoes),
`/api/tesouro` (curva NTN-B, taxa livre de risco real para o DCF),
`/api/di` (curva DI), `/api/tir/all` (seu modelo de TIR real),
`/api/cvm` (fatos relevantes e proventos) e `/api/indicators` (macro).

---

## Comandos, na ponta da lingua

No Claude Code, digite exatamente assim, sempre com o nome do plugin antes
dos dois pontos. Anexe os arquivos junto com o pedido.

**Analise e valuation** (`financial-analysis`)

| Comando                                        | Para que serve                                                   |
|------------------------------------------------|------------------------------------------------------------------|
| `/financial-analysis:dcf VALE3`                | DCF em Excel com WACC e sensibilidade; confirma cada premissa com voce |
| `/financial-analysis:comps ITUB4 BBDC4 BBAS3 SANB11 BPAC11` | Tabela de multiplos de pares                          |
| `/financial-analysis:3-statement-model`        | Projecao de DRE, balanco e caixa                                 |
| `/financial-analysis:competitive-analysis`     | Posicionamento competitivo e cenario do setor                    |
| `/financial-analysis:debug-model modelo.xlsx`  | Auditoria de planilha: formulas quebradas, numeros chumbados     |
| `/financial-analysis:ppt-template`             | Ensina o Claude o seu template de PowerPoint                     |

**Research** (`equity-research`)

| Comando                                   | Para que serve                                                   |
|-------------------------------------------|------------------------------------------------------------------|
| `/equity-research:earnings PETR4 2T26`    | Nota de resultado trimestral (anexe release e ITR)               |
| `/equity-research:earnings-preview`       | Previa com cenarios antes do resultado                           |
| `/equity-research:initiate`               | Inicio de cobertura em 5 etapas, uma por vez                     |
| `/equity-research:model-update`           | Atualiza o modelo com dados novos                                |
| `/equity-research:thesis`                 | Cria e mantem a tese de investimento por empresa                 |
| `/equity-research:catalysts`              | Calendario de catalisadores da cobertura                         |
| `/equity-research:screen`                 | Ideias por filtro de multiplos e dividendos                      |
| `/equity-research:sector`                 | Panorama setorial                                                |
| `/equity-research:morning-note`           | Nota matinal com destaques e ideias                              |

**Reuniao e rotina de assessor** (`meeting-prep-agent` e `claude-for-financial-advisors`)

| Comando                                                  | Para que serve                                            |
|----------------------------------------------------------|-----------------------------------------------------------|
| `/meeting-prep-agent:client-review`                      | Preparo de reuniao de revisao de carteira                 |
| `/meeting-prep-agent:client-report`                      | Relatorio de performance para o cliente                   |
| `/meeting-prep-agent:investment-proposal`                | Proposta para prospect                                    |
| `/claude-for-financial-advisors:pre-meeting`             | Briefing com Google Calendar, Gmail e Drive               |
| `/claude-for-financial-advisors:post-meeting`            | Nota de CRM e follow-ups a partir da reuniao              |
| `/claude-for-financial-advisors:prospect-intake`         | Organiza extratos de um prospect                          |
| `/claude-for-financial-advisors:portfolio-rebalance-review` | Drift versus alvo e cenarios de rebalanceamento        |
| `/claude-for-financial-advisors:compliance`              | Pre-check de material ao cliente (regras da SEC; peca para adaptar a CVM 178) |
| `/claude-for-financial-advisors:onboarding`              | Tour guiado do plugin                                     |

**Agentes.** Peca em linguagem natural: "use o agente market-researcher para
um panorama de saneamento com SBSP3, CSMG3 e SAPR11", ou mencione
`@market-researcher:market-researcher`. Vale o mesmo para
`earnings-reviewer`, `model-builder` e `meeting-prep-agent`.

**Skills automaticas.** Alem dos comandos, as skills disparam sozinhas quando
o pedido combina: "monta um DCF da WEG" aciona a skill de DCF sem comando.

---

## Contexto Brasil: cole isto no comeco do pedido

As skills foram escritas para o mercado americano (10-Q, EDGAR, consenso
Bloomberg, ingles). A metodologia serve igual; so precisa dizer o contexto:

```
Contexto: sou assessor de investimentos no Brasil. A empresa e listada na B3.
Fontes primarias: o release de resultados e o ITR/DFP anexados, o site de RI
e os dados abertos da CVM. Nao use EDGAR nem 10-Q. Moeda em R$, numeros no
formato brasileiro, texto em portugues. Se faltar consenso de mercado, use as
estimativas que eu colar e marque como [ESTIMATIVA DO ASSESSOR]. Para a taxa
livre de risco real, use a NTN-B do terminal em http://localhost:5051/api/tesouro.
```

---

## Fluxos que combinam com as suas ferramentas

- **Temporada de resultados.** `/equity-research:earnings VALE3 2T26` com o
  release e o ITR anexados. Depois, "faz um post" para a skill post-studio
  virar arte ou texto para o grupo.
- **Teses das empresas do modelo de TIR.** `/equity-research:thesis` por
  empresa e `/equity-research:catalysts` para o calendario. Quando o research
  mudar o LPA, a skill research-updater-tir atualiza `tir_real_servidor.py` e
  voce atualiza a tese no mesmo passo.
- **Comparaveis.** `/financial-analysis:comps` com o set de pares. A skill
  recusa web search como fonte primaria: cole a tabela do terminal ou do
  StatusInvest, ou ligue o bolsai.
- **Valuation cruzado.** `/financial-analysis:dcf` na empresa que quer
  aprofundar e compare com a TIR real do DDM em `/api/tir`. Divergencia
  grande e pauta boa para cliente.
- **Screening.** `/equity-research:screen` com filtros de multiplo e DY,
  de preferencia com o bolsai ligado.
- **Reuniao.** `/claude-for-financial-advisors:pre-meeting` usando Calendar,
  Gmail e Drive. O conector do HubSpot esta instalado na sua conta mas
  desligado por padrao no chat; ative-o na conversa para o CRM entrar.

---

## Manutencao

| Tarefa                          | Como                                                                              |
|---------------------------------|-----------------------------------------------------------------------------------|
| Ver instalados, erros, custo    | `/plugin` dentro do Claude Code (abas Installed, Marketplaces, Errors)            |
| Atualizar para a versao nova    | `claude plugin marketplace update`                                                |
| Desligar um plugin              | `claude plugin disable meeting-prep-agent@claude-for-financial-services`          |
| Ver o custo de um plugin        | `claude plugin details financial-analysis@claude-for-financial-services`          |
| Reinstalar ou conferir          | Duplo clique em `INSTALAR-PLUGINS-CLAUDE`, ou `bash INSTALAR-PLUGINS-CLAUDE.command --quiet` |

Ficaram de fora de proposito, por serem de banco de investimento, private
equity ou back-office: `investment-banking` (so o `/one-pager` seria util),
`private-equity`, `fund-admin`, `operations`, `pitch-agent`, `gl-reconciler`,
`kyc-screener`, `valuation-reviewer`, `month-end-closer`, `statement-auditor`.
Os parceiros `lseg` e `sp-global` exigem licenca. Para adicionar qualquer um:

```bash
claude plugin install investment-banking@claude-for-financial-services --scope user
```

Se quiser que valha tambem na web, inclua o nome em `enabledPlugins` no
`.claude/settings.json` e na lista `PLUGINS` de `INSTALAR-PLUGINS-CLAUDE.command`
(e no `.bat`).

---

## Opcional: instalar sozinho ao abrir a sessao

O Claude Code aceita um hook `SessionStart`: um comando que roda toda vez que
uma sessao abre nesta pasta, na web ou no computador. Com ele, o instalador
roda em silencio no inicio de cada sessao e instala o que faltar. Por ser um
comando que executa sozinho em todas as sessoes futuras, ele nao vem ligado;
a decisao e sua. Para ligar, acrescente este bloco ao `.claude/settings.json`,
ao lado de `enabledPlugins`:

```json
"hooks": {
  "SessionStart": [
    {
      "matcher": "startup",
      "hooks": [
        {
          "type": "command",
          "command": "bash \"$CLAUDE_PROJECT_DIR/INSTALAR-PLUGINS-CLAUDE.command\" --quiet",
          "timeout": 300
        }
      ]
    }
  ]
}
```

Quando ja esta tudo instalado o hook leva menos de um segundo. Quando
instala algo, os plugins carregam na sessao seguinte, e o resumo que ele
imprime entra no contexto do Claude, que avisa voce.

---

## Avisos

- As skills nascem em ingles e no padrao dos EUA. Use o bloco de contexto
  acima e revise moeda, fonte e formato antes de enviar a alguem.
- A skill `compliance` checa regras da SEC (Marketing Rule, Reg BI). Para o
  seu caso ela e um checklist inicial; peca para adaptar a Resolucao CVM 178.
- Os conectores do Claude for Financial Advisors (Schwab, BlackRock, Addepar,
  Orion, Wealthbox...) sao plataformas americanas e nao funcionam aqui. As
  skills seguem funcionando com Gmail, Calendar e Drive e pedem para colar o
  que faltar.
- Todo numero deve ter fonte. Quando a skill nao acha, ela marca
  `[UNSOURCED]`; nao remova a marca, resolva a fonte.
