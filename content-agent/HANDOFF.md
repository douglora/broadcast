# HANDOFF — projeto de conteúdo (LinkedIn)

Estado do projeto para continuar em qualquer sessão (web ou terminal local).

## O que é
Sistema/agente para o autor publicar conteúdo de mercado no LinkedIn: relatórios
de macro/mercado em **texto corrido** (não carrossel), 3x/semana, com imagem, em
tom de **educação/comentário** (sem recomendação — o autor não é CNPI).

## Decisões travadas
- **Tom:** educação/comentário. Proibido "compre/venda", preço-alvo, promessa de retorno.
- **Formato:** texto corrido; gancho nas 2 primeiras linhas; parágrafos curtos;
  ~1.800–2.900 caracteres (limite 3.000 do LinkedIn); termina com pergunta.
- **Voz:** registro inspirado no Dan Kawa — macro global→local, didático,
  probabilístico, abre com "cenário", fecha com "o que mudaria a tese".
  Inspiração de estilo apenas; a voz e as ideias são do autor (não copiar ninguém).
- **Imagem:** estética editorial "The Invest Post" (marfim/carvão/dourado), sem texto na imagem.

## Os 5 ajustes de voz a aplicar em todo post
1. Abrir declarando o cenário, não o fato.
2. Fechar o arco global → Brasil.
3. Deixar claro o gatilho que mudaria a tese.
4. Linguagem probabilística ("a balança pende para").
5. Manter a trava de compliance (comentário, nunca recomendação).

## Mapa do código
- `content-agent/` — coletor + propositor de pautas + redator (ver `README.md`).
- `content-agent/voice/voice-guide.md` — regras de voz/compliance/formato (o "cérebro" do prompt).
- `content-agent/voice/samples.md` — COLAR aqui 3–5 posts do autor (calibra o estilo, peça mais importante).
- `content-agent/BLUEPRINT.md` — arquitetura e estratégia.

## Vantagens de rodar no terminal local (vs. ambiente web)
Na máquina do autor não existe a allowlist de rede do ambiente web. Então:
- Geração de imagem via **OpenAI funciona** (gpt-image-1 / dall-e-3). No web estava bloqueada.
- **Salvar arquivos em pastas locais** (ex.: Área de Trabalho) funciona.
- **Download de exports** (Canva etc.) funciona.

## Estratégia de engajamento no LinkedIn (resumo)
Maior alavanca não é "mais conteúdo". É:
1. **Comentar todo dia** (40–120 palavras) em 10–15 perfis maiores de macro/mercado, antes de postar. Comentário pesa ~15x mais que like; comentar uma vez ≈ 80% de chance de ver o próximo post da pessoa.
2. **Newsletter no LinkedIn** com o "Cenário" — fura o algoritmo (vai pra inbox), assinante é permanente.
3. **Enquete semanal** (alto engajamento) + **post de reação** no mesmo dia usando dado exclusivo do BROADCAST.
- Formatos a somar 1 por vez (rodar 30 dias antes do próximo): poll, reação, gráfico avulso, PDF educacional, vídeo nativo 30–90s, take contrarian.
- Mecânica: gancho nos primeiros ~210 caracteres; link no 1º comentário; responder comentários nos primeiros 60–90 min.

## Próximos passos em aberto
1. Preencher `voice/samples.md` com posts reais do autor.
2. Lançar a newsletter.
3. Implantar a rotina diária de comentários.
4. Montar calendário de 30 dias.
5. Estender o `content-agent` para propor enquete + post de reação + repurpose de um relatório nas outras superfícies.

## Post de referência (voz + formato aprovados) — "Dilema do BC / dominância fiscal"
> O sonho de ver o juro brasileiro voltar para a casa dos 11,50% virou história. Meses atrás o mercado precificava esse alívio. Hoje, ele parece cada vez mais distante.
>
> Pense no Banco Central como um homem no meio do oceano, dentro de um barco furado. O furo é a desancoragem fiscal. Ele tem um único balde, o juro alto, para tirar a água que não para de entrar: uma inflação que resiste, principalmente nos serviços, numa economia que veio mais forte do que se esperava. O problema é o que acontece a cada balde que ele joga para fora. O governo enche o mesmo balde com água do oceano e devolve para dentro do barco. É a política fiscal desfazendo o esforço da monetária.
>
> (post completo no histórico; usar como molde de voz, gancho e fecho com pergunta.)
