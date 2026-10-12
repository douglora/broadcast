# Dados pedidos pela pesquisa do robo (12/10/2026) - formato: dado | para que | frequencia | fonte sugerida | prioridade

A sessao "Dados em tempo real para o robo e o terminal" le este arquivo. O que ja foi coletado em HISTORICO esta em
quant/dados/calendario_eua.py (BLS 2021-2026 pelo bls.gov/schedule, pedidos de auxilio por regra, efetivos pela API v1 do BLS sem chave,
consenso semanal do ForexFactory em dados_brutos/calendario_eua/ff/) e no script do calendario do MetaTrader (AutopilotCalendario.mq5,
na pasta Scripts do MetaTrader Global; precisa do "pode" do Douglas para compilar e rodar).

| dado | para que | frequencia | fonte sugerida | prioridade |
|---|---|---|---|---|
| Consenso (mediana) e efetivo dos dados americanos das 8h30 de NY (payroll, CPI, PPI, PCE, PIB, varejo, pedidos de auxilio, ISM) com hora da divulgacao | surpresa contra o consenso no setup do dado do mini-dolar (prova viva por tipo de dia e por sinal da surpresa) | no minuto da divulgacao (8h30 NY) e a semana a frente (agendados) | ForexFactory thisweek JSON (nfs.faireconomy.media, sem login, robots libera; so a semana corrente) ou calendario economico do MetaTrader (CalendarValueHistory, historico de anos) | alta |
| Calendario das divulgacoes do BEA e do Census (PIB, PCE, balanca, varejo, bens duraveis, construcao) | completar o `tipo_do_dia` (hoje so BLS + pedidos de auxilio: dias do BEA/Census caem em "nenhum conhecido") | semanal (agenda do mes) | bea.gov/news/schedule (HTML), census.gov/economic-indicators/calendar-listview.html (HTML) | alta |
| Fluxo do investidor estrangeiro na B3, serie diaria longa (2010 em diante) | sinal `fluxo_estrangeiro_5d` da camada de observacao e a regra G9; hoje so ha serie desde 28/08/2026 | diaria (D+2) | B3 BDI SharesInvesVolum (historico) ou boletim mensal da B3 | media |
| Spread real de compra e venda por acao e faixa de liquidez (medido no negocio a negocio) | trocar o meio-spread estimado (25/40/80 pb) do custo do swing por medida | diaria (20 pregoes de ticks da B3) | arquivos.b3.com.br rapinegocios tickercsv (ja coletado para WDO/DOL/WIN em pesquisa5/b3_dolar) | media |
| VIX, DXY, Treasury 10 anos, Brent, dolar/real e spread high yield intradiarios (a cada minuto) | termometro G20 em tempo real (hoje le o fechamento diario de hist/) | 1 minuto | MetaTrader Global (US500, DXY?, XAUUSD...), Yahoo (atraso 15 min), FRED (so diario) | baixa (diario basta para a dose) |
| Posicao em aberto no dolar futuro por tipo de participante | pista do dolar_dias e FILA 6/7 | diaria | NAO EXISTE de graca desde 04/2025 (B3 tirou a pagina); so UP2DATA pago | baixa |
| Ajuste oficial dos futuros (WDO, WIN) com hora | nivel do ajuste no robo sem depender de futuros.json com ate 5 dias | diaria, 18h | B3 TradeInformationConsolidated (rota /api, ja usada em b3_dolar) | media |
| Cartao de cenario da mesa no formato G19 (cenarios, probabilidades, gatilhos com serie, limiar, sentido, data de verificacao) | placar de Brier em quant/observacao/placar.py (quant/saida/mesa/cartao_cenario.json) | semanal (domingo, com a visao da mesa) | a propria rotina quant-visao-da-mesa-semanal | alta |
