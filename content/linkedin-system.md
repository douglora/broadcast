# Sistema de Conteúdo LinkedIn — BROADCAST

Pipeline que transforma os outputs do autopilot (morning call, fechamento,
masterbriefing) em posts de LinkedIn com POV, para construir autoridade em
assessoria de investimentos.

## Configuração travada
- **Perfil:** Assessor (CVM/ANCORD) → SEM recomendação individualizada. Conteúdo
  educacional/macro com enquadramento de ALOCAÇÃO, nunca stock pick.
- **Audiência:** Investidor qualificado → leitura não-óbvia, não didatismo básico.
- **Cadência:** 3x/semana, mínimo 6 meses.

## Calendário editorial
| Dia | Pilar | Fonte (autopilot) | Formato |
|-----|-------|-------------------|---------|
| Seg | Mapa da semana (vetores macro de alocação) | masterbriefing | Texto + imagem |
| Qua | Tese da semana (1 tema, chave de alocação) | resumos + notícias | Carrossel (ver templates/) |
| Sex | Fechamento + leitura (erro comum + opinião) | fechamento da semana | Texto + pergunta-CTA |

## Princípios (não-negociáveis)
1. Tese errável na abertura, não fato neutro. Primeira pessoa de assessor.
2. Primeiras 3 linhas forçam o "ver mais" (dwell time).
3. Toda peça passa por compliance-assessor.md antes de publicar.
4. Toda peça é escrita conforme voice-guide.md (sua voz).
5. Gate humano: você adiciona 1 frase de opinião genuína e aprova.

## Pipeline de agentes
1. CURADOR → escolhe o tema único de maior relevância da semana.
2. ÂNGULO/POV → tese + ganchos + leitura não-óbvia.
3. COMPLIANCE → aplica compliance-assessor.md.
4. WRITER → escreve na sua voz (voice-guide.md).
5. DESIGNER → gera carrossel (MCP de design).
6. EDITOR/QA → gancho, dwell time, pergunta-CTA, comprimento.
7. GATE HUMANO → push via ntfy pro celular → você aprova → agenda.

Roda 1x/semana em lote (gera as 3 peças do digest semanal).

## Pendências para ativar
- [ ] Backend do autopilot commitado no repo (formato dos outputs).
- [ ] voice-guide.md preenchido com 5-10 amostras suas.
- [ ] Conta/integração de agendamento do LinkedIn definida.
