# KLBN11 — Notas de verificação (revisão adversarial)

Análise verificada por 3 revisores independentes (quant / estratégia / mercado‑BR) + síntese sênior.
Todos reimplementaram Black‑Scholes do zero. **Núcleo numérico confirmado** (IV 21,6%, gregas,
fair values, breakeven, probabilidades, créditos das estruturas; datas 17/07/2026 = 3ª sexta,
12 dias úteis com feriado de 09/07‑SP excluído; base 252). Conclusão de fundo sustentada.

## Correções incorporadas
1. **PUTs na B3 são europeias** → a put vendida **não** tem risco de exercício antecipado. Esse risco
   só existe nas **calls** vendidas (americanas), tipicamente perto de ex‑dividendo. KLBN não tem
   ex‑div até o vencimento.
2. **IR sobre opções: sem isenção** de R$20 mil/mês (essa é só para ações à vista). Ganho em opção
   = 15%, DARF auto‑apurado (recolhe se imposto do mês > R$10). Líquido de 0,07 ≈ 0,0595/ação.
3. **Prêmios das estruturas multi‑perna são teóricos** (IV plana 21,6%), não cotações executáveis.
4. **Probabilidades são risk‑neutral** (P(ITM)=17,5%); no mundo real (drift 0) ~21%.
5. **Theta** reportado em base dia‑corrido (~0,007/dia); em base 252 seria ~0,0096/dia‑útil.

## Ressalvas materiais de mercado
- **Liquidez:** opções de KLBN11 são líquidas quase só no ATM e majoritariamente em **calls**.
  Pontas do Iron Condor (15,66/18,00) e até a própria PUT 16,16@0,07 podem não ter book —
  **checar volume/spread de cada série no home broker antes de operar.**
- **Custo por boleta** inviabiliza centavos em lote pequeno (Iron Condor = 4 boletas).
- **Carrego:** forward ≈ 16,91 > spot 16,80 (SELIC 14,25%) → puts OTM estruturalmente **baratas**,
  calls estruturalmente **ricas**. Call equidistante vale ~+77% vs a put. Vender o lado da **call**
  capta mais valor, e alinha melhor à leitura **neutra‑a‑baixista** (suporte 16,97 perdido, fundo do range).
- **Skew não testado:** comparei IV com vol histórica, não com a IV ATM/calls. Conferir a curva de
  skew na tela pode inverter qual lado vender.
- **Benchmark caixa:** SELIC rende ~0,6% em 12 d.u., **acima** dos 0,43% da venda da put — sem risco.

## Veredito
- **Vender a PUT 16,16 @0,07: não compensa** (prêmio justo, absoluto minúsculo, assimetria péssima,
  downside no fundo do range; caixa na SELIC rende mais sem risco).
- **Melhor operação (se houver liquidez no book):** Covered Call ~17,50 se já possui as units; ou
  **bear call spread** (vende o lado rico/call, risco definido, alinhado ao viés neutro‑baixista).
- Calendar descartado (12 d.u., série seguinte ilíquida).
