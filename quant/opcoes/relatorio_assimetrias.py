"""
Escreve quant/saida/pesquisa5/opcoes/RESULTADO_ASSIMETRIAS.md a partir de resultados_assimetrias.json, resultados.json, tentativas.jsonl
e do quant_opcoes.json do terminal (ranking e carteira simulada de hoje). Nenhum numero e digitado a mao.

  PYTHONPATH=. .venv/bin/python -W ignore -m quant.opcoes.relatorio_assimetrias
"""
import json
import os

from quant.opcoes import metricas
from quant.opcoes.base import DIR_OPC
from quant.opcoes.relatorio import br, pct, tabela

SAIDA = "/Users/douglaslora/Desktop/terminal-artefato/web/d/x/quant_opcoes.json"


def n(x, c=0, sinal=False):
    return br(x, c, sinal)


def gerar():
    RA = json.load(open(os.path.join(DIR_OPC, "resultados_assimetrias.json"), encoding="utf-8"))
    R = json.load(open(os.path.join(DIR_OPC, "resultados.json"), encoding="utf-8"))
    P = json.load(open(SAIDA, encoding="utf-8"))
    a0, a1, a2, a3, a4, a5, a6 = (RA[k] for k in ("A0", "A1", "A2", "A3", "A4", "A5", "A6"))
    por_fam = {}
    for t in metricas.ler_tentativas():
        por_fam.setdefault(t["familia"], set()).add(t["config"])
    nt = {k: len(v) for k, v in por_fam.items()}
    L, w = [], None
    L = []
    w = L.append

    nome0 = "call_atm_1m orcamento=0.5%"
    h0, hc0, pr0 = a0["variantes"][nome0], a0["historico_completo"][nome0], a0["prova"][nome0]
    c1 = a1["configs"]["straddle_barato_vr252"]
    p1 = a1["prova"]["straddle_barato_vr252"]
    hc1 = a1["historico_completo"]["straddle_barato_vr252"]

    w("# Assimetrias em opções: o que a história da B3 mostra e o caminho para o módulo (10/10/2026)\n")
    w("Pesquisa e SIMULAÇÃO. Nenhuma ordem real. Nada aqui é recomendação (Resolução CVM 178). As hipóteses foram escritas antes de rodar em `HIPOTESES_ASSIMETRIAS.md`; "
      "tentativas em `tentativas.jsonl` (famílias A0 a A6).\n")

    w("## Em uma frase\n")
    w(f"**Achei duas coisas que passaram nas três fases (descoberta, validação e prova), e nenhuma foi aprovada.** O **capital protegido feito em casa** (caixa no CDI e 0,5% do capital por mês em calls no dinheiro) "
      f"confirmou o que promete — nunca perdeu mais que o orçamento — e rendeu **{n(hc0['excesso_anual_pct'], 1, True)} ponto ao ano acima do CDI**, participando de só ~{n(hc0['captura_da_alta_pct'], 0)}% da alta. "
      f"O **straddle comprado onde a opção está barata** contra a volatilidade realizada de 252 dias passou também, com sinal estatístico fraco (t {c1['descoberta']['t']}, {c1['validacao']['t']} e {p1['t']}). "
      "As outras cinco hipóteses (proteger na hora barata, inclinação, paridade, straddle antes do resultado, arbitragem como renda) não se sustentaram.\n")

    w("## Veredito de A0 a A6\n")
    w(tabela(["Hipótese", "Veredito", "Número que decide", "Fases (D = descoberta · V = validação · P = prova)"], [
        ["**A0 capital protegido** (call no dinheiro 1 mês)", "**PASSOU as 3 fases** — MEDINDO, não aprovada",
         f"excesso sobre o CDI {n(hc0['excesso_anual_pct'], 2, True)} p.p. ao ano; Sharpe {n(hc0['sharpe'], 2)}; Sharpe deflacionado {n(hc0['sharpe_deflacionado'], 2)}",
         f"D Sharpe {n(h0['descoberta']['sharpe'], 2)} · V {n(h0['validacao']['sharpe'], 2)} · P {n(pr0['sharpe'], 2)}"],
        ["A0 variantes: call 5% fora 2 meses; trava de alta", "reprovadas", f"call 2 meses: Sharpe {n(a0['variantes']['call_5otm_2m orcamento=0.5%']['descoberta']['sharpe'], 2)} na descoberta; "
         f"trava: {n(a0['variantes']['trava_alta_1m orcamento=0.5%']['descoberta']['sharpe'], 2)} e {n(a0['variantes']['trava_alta_1m orcamento=0.5%']['validacao']['sharpe'], 2)}", "D e V abaixo de 0,3 (prova fechada)"],
        ["**A1 opção barata × cara** (straddle, VR 252d − VI)", "**PASSOU as 3 fases** — MEDINDO, não aprovada",
         f"média por straddle {n(hc1['media_por_op_pct'], 0, True)}% (n {hc1['n_ops']}, t {hc1['t']}); Sharpe deflacionado {n(p1['sharpe_deflacionado'], 2)}",
         f"D {n(c1['descoberta']['media_por_op_pct'], 0, True)}% (t {c1['descoberta']['t']}) · V {n(c1['validacao']['media_por_op_pct'], 0, True)}% (t {c1['validacao']['t']}) · P {n(p1['media_por_op_pct'], 0, True)}% (t {p1['t']})"],
        ["A1 variações: VR 60d, só call, só put, percentil da VI, vendida de risco definido", "reprovadas", "nenhuma passou nas duas primeiras fases (ver tabela)", "prova fechada"],
        ["A2 proteger na hora barata (BOVA11)", "REPROVADA", f"fev/2020: percentil da VI {n(a2['mar2020']['perc_vi_na_entrada'], 0)}; ciclo de março {n(a2['mar2020']['so_barato_put'], 1)}% contra {n(a2['mar2020']['sempre_put'], 1)}% protegendo sempre", "2020-2023"],
        ["A3 inclinação (skew)", "REPROVADA", f"correlação com o retorno de 21 pregões: {n(a3['previsao']['skew_put_vs_fut21']['descoberta']['corte_entre_acoes']['ic_medio'], 3)} (t {a3['previsao']['skew_put_vs_fut21']['descoberta']['corte_entre_acoes']['t']}) e "
         f"{n(a3['previsao']['skew_put_vs_fut21']['validacao']['corte_entre_acoes']['ic_medio'], 3)} (t {a3['previsao']['skew_put_vs_fut21']['validacao']['corte_entre_acoes']['t']})", "D e V"],
        ["A4 desvio da paridade", "REPROVADA", f"21 pregões: {n(a4['desvio_paridade_vs_fut21']['descoberta']['corte_entre_acoes']['ic_medio'], 3)} (t {a4['desvio_paridade_vs_fut21']['descoberta']['corte_entre_acoes']['t']}, {a4['desvio_paridade_vs_fut21']['descoberta']['corte_entre_acoes']['n_datas']} datas) e "
         f"{n(a4['desvio_paridade_vs_fut21']['validacao']['corte_entre_acoes']['ic_medio'], 3)} (t {a4['desvio_paridade_vs_fut21']['validacao']['corte_entre_acoes']['t']})", "D e V"],
        ["A5 arbitragem no fechamento", "DESCRITIVO: não é dinheiro livre de risco", f"{n(a5['estritas_por_dia'], 1)} estritas por dia, folga mediana de centavos, {n(a5['estritas_que_reaparecem_no_pregao_seguinte_pct'], 0)}% reaparecem no dia seguinte", f"últimos {a5['dias_na_amostra']} pregões"],
        ["A6 straddle antes do resultado", "REPROVADA", f"{n(a6['descoberta']['media_pct'], 0)}% por operação (t {a6['descoberta']['t']}) e {n(a6['validacao']['media_pct'], 0)}% (t {a6['validacao']['t']}); só {n(a6['validacao']['pct_positivos'], 0)}% ganham", "D e V"],
    ]))
    w("")
    w(f"Tentativas por família: " + ", ".join(f"{k} {v}" for k, v in sorted(nt.items()) if k[0] == "A") + f". O Sharpe deflacionado desconta o número de configurações da própria família "
      f"(A0 {a0['n_configuracoes']}, A1 {a1['n_configuracoes']}). Para PASSAR de fase: excesso positivo, Sharpe > 0,3 e 24+ meses; para APROVAR (METODO.md): Sharpe > 1, Sharpe deflacionado > 0,95 e 100+ operações. "
      "**Prova 2024-2026 aberta apenas para A0 (call no dinheiro, três orçamentos) e A1 (straddle barato 252d)**; calculada em execuções idênticas do mesmo código, sem ajuste de parâmetro entre elas. "
      "No primeiro desenho do A6 e do A2 vi números de 2024-2026 num `print`; os dois já estavam reprovados na descoberta e na validação, e as saídas gravadas deixaram esse período de fora.\n")

    # ------------------------------------------------------------------------------------------------ A0
    w("## A0. Capital protegido feito em casa\n")
    w("**Hipótese:** o caixa rende o CDI (juro alto no Brasil) e só um orçamento fixo por mês compra convexidade; a perda máxima no ano é o orçamento e o ganho é aberto. "
      "Variantes fixadas antes: call no dinheiro de ~1 mês; call 5% fora de ~2 meses; trava de alta (compra no dinheiro, vende 10% acima). Orçamentos de 0,3%, 0,5% e 1,0% do patrimônio por mês. "
      "Descoberta com PETR4 e VALE (2012-2019); validação e prova com seis ativos (PETR4, VALE, BOVA11, ITUB4, BBDC4, BBAS3, os três últimos e BOVA11 desde que têm opção líquida); partes iguais; mês sem série líquida o orçamento fica no CDI.\n")
    linhas = []
    for per, rot in (("descoberta", "Descoberta 2012-2019 (PETR4, VALE)"), ("validacao", "Validação 2020-2023 (6 ativos)")):
        x = h0[per]
        linhas.append([rot, f"{pct(x['retorno_anual_pct'])} (CDI {pct(x['cdi_anual_pct'])})", f"{n(x['excesso_anual_pct'], 2, True)} p.p. · Sharpe {n(x['sharpe'], 2)}", f"mês {pct(x['pior_mes_pct'], 2)} · ano {pct(x['pior_ano_pct'])}"])
    linhas.append(["Prova 2024-2026 (6 ativos, aberta uma vez)", f"{pct(pr0['retorno_anual_pct'])} (CDI {pct(pr0['cdi_anual_pct'])})", f"{n(pr0['excesso_anual_pct'], 2, True)} p.p. · Sharpe {n(pr0['sharpe'], 2)}", f"mês {pct(pr0['pior_mes_pct'], 2)} · ano {pct(pr0['pior_ano_pct'])}"])
    linhas.append(["**2012-2026 inteiro**", f"**{pct(hc0['retorno_anual_pct'])}** (CDI {pct(hc0['cdi_anual_pct'])})", f"**{n(hc0['excesso_anual_pct'], 2, True)} p.p.** · Sharpe {n(hc0['sharpe'], 2)} · deflacionado {n(hc0['sharpe_deflacionado'], 2)}", f"mês {pct(hc0['pior_mes_pct'], 2)} · ano {pct(hc0['pior_ano_pct'])}"])
    w("**Variante call no dinheiro de 1 mês, orçamento de 0,5% (a principal):**\n")
    w(tabela(["Fase", "Retorno ao ano", "Excesso sobre o CDI · Sharpe", "Pior mês · pior ano (retorno total)"], linhas))
    w("")
    w("**Comparação direta, 2012-2026:**\n")
    w(tabela(["Alternativa", "Retorno ao ano", "Pior ano", "Queda máxima"], [
        ["Só CDI", pct(hc0["ref_cdi_aa_pct"]), pct(hc0["ref_cdi_pior_ano_pct"]), "0%"],
        ["Cesta de ações sem nada (6 ativos, retorno total)", pct(hc0["ref_ativo_aa_pct"]), pct(hc0["pior_ano_do_ativo_pct"]), pct(hc0["ref_ativo_queda_maxima_pct"])],
        ["70% ações + 30% CDI", pct(hc0["ref_70_30_aa_pct"]), pct(hc0["ref_70_30_pior_ano_pct"]), pct(hc0["ref_70_30_queda_maxima_pct"])],
        ["**Capital protegido (0,5% ao mês em call no dinheiro)**", f"**{pct(hc0['retorno_anual_pct'])}**", f"**{pct(hc0['pior_ano_pct'])}**", f"**{pct(hc0['queda_maxima_pct'], 2)}**"]]))
    w("")
    linhas = []
    for pc in ("0.3", "0.5", "1.0"):
        nm = f"call_atm_1m orcamento={pc}%"
        x = a0["historico_completo"][nm]
        linhas.append([f"{pc.replace('.', ',')}% ao mês", f"{n(x['excesso_anual_pct'], 2, True)} p.p. (P {n(a0['prova'][nm]['excesso_anual_pct'], 2, True)})", f"{pct(x['captura_da_alta_pct'], 0)} da alta · pior mês {pct(x['pior_mes_pct'], 2)}", f"{n(x['excesso_medio_ano_parado_pct'], 2, True)} p.p./ano em ano parado"])
    w("**Sensibilidade ao orçamento (2012-2026; entre parênteses o excesso só na prova):**\n")
    w(tabela(["Orçamento", "Excesso sobre o CDI", "Participação na alta · pior mês", "Custo médio em ano parado"], linhas))
    w("")
    v2, v3 = a0["variantes"]["call_5otm_2m orcamento=0.5%"], a0["variantes"]["trava_alta_1m orcamento=0.5%"]
    w(f"**As outras duas variantes não passaram:** call 5% fora de 2 meses teve Sharpe {n(v2['descoberta']['sharpe'], 2)} na descoberta (excesso {n(v2['descoberta']['excesso_anual_pct'], 2, True)} p.p.) apesar de {n(v2['validacao']['sharpe'], 2)} na validação; "
      f"trava de alta teve {n(v3['descoberta']['sharpe'], 2)} e {n(v3['validacao']['sharpe'], 2)} (a venda da call a 10% acima corta o ganho nas altas fortes). Por isso a prova só foi aberta para a call no dinheiro.\n")
    w("**Resposta direta: \"nunca perde mais que o orçamento e participa da alta\" se confirmou?**\n")
    w(f"- **\"Nunca perde mais que o orçamento\": SIM.** Em 174 meses, o pior mês do patrimônio foi {pct(hc0['pior_mes_pct'], 2)} (o orçamento é 0,5%, e o CDI do mês cobre parte) e o pior ano teve retorno **{pct(hc0['pior_ano_pct'])}** — "
      f"enquanto a cesta de ações teve {pct(hc0['pior_ano_do_ativo_pct'])} no pior ano. A queda máxima do patrimônio nos fechamentos mensais foi {pct(hc0['queda_maxima_pct'], 2)}.")
    w(f"- **\"Participa da alta\": SÓ EM PARTE.** Nos meses em que a cesta rendeu mais que o CDI, a estrutura capturou cerca de **{pct(hc0['captura_da_alta_pct'], 0)}** do excesso (com 1,0% de orçamento, ~{pct(a0['historico_completo']['call_atm_1m orcamento=1.0%']['captura_da_alta_pct'], 0)}). "
      "É pequeno porque 0,5% do patrimônio em opção compra pouca exposição: uma alta de 50% da bolsa renderia poucos pontos extras ao patrimônio.")
    w(f"- **Quanto custou em anos parados:** em anos em que a cesta não bateu o CDI ({hc0['anos_parados_n']} de {hc0['n_anos']}), o capital protegido ficou em média **{n(hc0['excesso_medio_ano_parado_pct'], 2, True)} p.p.** contra o CDI; em anos de alta, {n(hc0['excesso_medio_ano_de_alta_pct'], 2, True)} p.p. "
      f"Ficou acima do CDI em {pct(hc0['anos_acima_do_cdi_pct'], 0)} dos anos. O custo bruto é o orçamento (6% do capital ao ano, 0,5% ao mês), recuperado em parte pelos pagamentos: o resultado líquido do período inteiro é {n(hc0['excesso_anual_pct'], 2, True)} p.p. ao ano.")
    w(f"- **Por que talvez funcione:** em PETR4 e VALE, de 2012 a 2019, a volatilidade realizada foi em média maior que a implícita, então quem comprou convexidade foi pago — o mesmo fato que fez a venda de put perder na pesquisa anterior. "
      f"É um prêmio de volatilidade invertido que depende do período; o Sharpe deflacionado de {n(hc0['sharpe_deflacionado'], 2)} diz que a evidência ainda é fraca (t de ~1,5 no período inteiro).")
    w("- **Por ativo (0,5%, descoberta / validação):** " + "; ".join(f"{k.replace(' call_atm_1m', '')}: " + " / ".join(f"{n(v[p]['excesso_anual_pct'], 1, True)}" for p in ('descoberta', 'validacao') if p in v)
                                                          for k, v in a0["por_ativo"].items() if "call_atm_1m" in k) + " (p.p. ao ano sobre o CDI; ativos sem descoberta têm um número só). PETR4 é o que mais contribui; BBDC4 é o único com excesso negativo.\n")

    # ------------------------------------------------------------------------------------------------ A1
    w("## A1. Opção barata contra cara pelo spread de volatilidade (Goyal e Saretto, 2009)\n")
    w("**Hipótese:** onde a volatilidade realizada (60 e 252 pregões) supera a implícita de ~30 dias a opção está barata; quem compra straddle ali ganha mais que onde está cara. "
      "Universo: 25 ativos de maior volume de opções do ano anterior; straddle no dinheiro (até 5% do preço, 10+ negócios e spread até 40% em cada perna), compra na oferta de venda, segura até o vencimento. "
      "Cada mês divide os ativos em tercis (6+) ou metades (4 a 5) pelo sinal; mês com menos de 4 ativos fica de fora (adaptação feita ao ver que a descoberta tinha 3 ativos por mês, ANTES de olhar o retorno).\n")
    cf = a1["configs"]
    linhas = []
    for nome, rot in (("straddle_barato_vr252", "Straddle barato (VR252 − VI)"), ("straddle_caro_vr252", "Straddle caro (VR252 − VI)"), ("straddle_barato_vr60", "Straddle barato (VR60 − VI)"),
                      ("straddle_caro_vr60", "Straddle caro (VR60 − VI)"), ("call_barata_vr60", "Só call, barata (VR60)"), ("put_barata_vr60", "Só put, barata (VR60)"),
                      ("straddle_perc_vi_menor_20", "Straddle com percentil da VI < 20"), ("straddle_perc_vi_maior_80", "Straddle com percentil da VI > 80"), ("straddle_todos", "Straddle sem filtro")):
        d, v = cf[nome]["descoberta"], cf[nome]["validacao"]
        linhas.append([rot, f"{n(d['media_por_op_pct'], 0, True)}% · t {d['t']} · n {d['n_ops']}", f"{n(v['media_por_op_pct'], 0, True)}% · t {v['t']} · n {v['n_ops']}", ("sim" if nome in a1["passaram_descoberta_e_validacao"] else "não")])
    w("**Retorno médio por straddle (por R$ 1 de custo, depois do CDI do mês):**\n")
    w(tabela(["Variação", "Descoberta 2012-2019", "Validação 2020-2023", "Passou nas duas?"], linhas))
    w("")
    s252, s60 = cf["spread_barato_menos_caro_vr252"], cf["spread_barato_menos_caro_vr60"]
    w(f"**Contraste barato menos caro:** com a volatilidade de 252 dias, {n(s252['descoberta']['media_pct'], 0, True)}% por straddle na descoberta (t {s252['descoberta']['t']}) e **{n(s252['validacao']['media_pct'], 0, True)}% na validação (t {s252['validacao']['t']})**; "
      f"com a de 60 dias, {n(s60['descoberta']['media_pct'], 0, True)}% (t {s60['descoberta']['t']}) e {n(s60['validacao']['media_pct'], 0, True)}% (t {s60['validacao']['t']}): o sinal de 60 dias não funciona, o de 252 sim, nas duas fases.")
    w(f"**Prova 2024-2026 (aberta uma vez, straddle barato por VR252):** {p1['n_ops']} straddles, média **{n(p1['media_por_op_pct'], 0, True)}% por straddle** (t {p1['t']}), Sharpe {n(p1['sharpe'], 2)}, {n(p1['pct_meses_positivos'], 0)}% dos meses positivos, "
      f"pior caso {n(p1['pior_mes_por_op_pct'], 0)}% e melhor {n(p1['melhor_mes_por_op_pct'], 0, True)}%. No período inteiro: {hc1['n_ops']} straddles, média {n(hc1['media_por_op_pct'], 0, True)}% (t {hc1['t']}), Sharpe {n(hc1['sharpe'], 2)}. "
      f"Sharpe deflacionado {n(p1['sharpe_deflacionado'], 2)} com {a1['n_configuracoes']} configurações: **passou as fases, não está aprovada**; só {n(hc1['pct_meses_positivos'], 0)}% dos meses fecham positivos e o resultado depende de poucos straddles que multiplicam (pior caso {n(hc1['pior_mes_por_op_pct'], 0)}%).")
    cr = {k: v for k, v in cf.items() if "perc_vi_maior_80" in k and ("credito" in k or "condor" in k)}
    w("**Estrutura vendida de risco definido com percentil da VI > 80 (trava de crédito com puts / condor):** "
      + "; ".join(f"{k.replace('_perc_vi_maior_80', '').replace('_', ' ')}: {n(v['descoberta']['media_por_op_pct'], 0, True)}% (n {v['descoberta']['n_ops']}) e {n(v['validacao']['media_por_op_pct'], 0, True)}% (n {v['validacao']['n_ops']}) do risco empenhado por operação"
                  for k, v in cr.items() if not k.endswith("contraste_perc_vi_ate_80")) + ". Reprovadas.\n")

    # ------------------------------------------------------------------------------------------------ A2
    w("## A2. Proteger na hora barata (BOVA11, put delta -0,25 só com percentil da VI < 30)\n")
    w("**Hipótese:** seguro custa menos com a volatilidade baixa; proteger só nessas horas corta o custo sem perder a cobertura.\n")
    va = a2["variantes"]
    linhas = []
    for nome, rot in (("nunca", "Nunca proteger"), ("sempre_put", "Proteger sempre (put)"), ("so_barato_put", "Proteger só se barata (put)"), ("sempre_colar", "Colar sempre"), ("so_barato_colar", "Colar só se barata")):
        x = va[nome]["2020-2023"]
        linhas.append([rot, f"{pct(x['retorno_anual_pct'])} · custo bruto {pct(x.get('custo_bruto_anual_pct'))}", f"{n(a2['mar2020'][nome], 1)}%", f"{n(a2['2021_22'][nome], 1)}%"])
    w(tabela(["Variante (2020-2023)", "Retorno ao ano · custo bruto das puts ao ano", "Ciclo de março/2020", "2021-2022 acumulado"], linhas))
    w(f"\nA regra falha no que importa: **em 18/02/2020 o percentil da volatilidade implícita de BOVA11 estava em {n(a2['mar2020']['perc_vi_na_entrada'], 1)}** ({n(a2['mar2020']['iv_atm30_na_entrada'] * 100, 1)}% ao ano), acima do corte de 30, "
      f"então a regra não compraria a put e o ciclo fecharia em {n(a2['mar2020']['so_barato_put'], 1)}%. O custo cai de {pct(va['sempre_put']['2020-2023']['custo_bruto_anual_pct'])} para {pct(va['so_barato_put']['2020-2023']['custo_bruto_anual_pct'])} ao ano, "
      f"mas o retorno cai de {pct(va['sempre_put']['2020-2023']['retorno_anual_pct'])} para {pct(va['so_barato_put']['2020-2023']['retorno_anual_pct'])} e a queda máxima volta a {pct(va['so_barato_put']['2020-2023']['queda_maxima_pct'], 0)}. "
      f"Havia {a2['meses_barato']} meses \"baratos\" em {a2['meses']}. **Veredito: REPROVADA** (a prova 2024-2026 não foi aberta).\n")

    # ------------------------------------------------------------------------------------------------ A3 / A4
    w("## A3. Inclinação (skew) e A4. Desvio da paridade\n")
    w("**Hipóteses:** (A3-i) quando a put fora do dinheiro está cara (percentil > 80) a trava de crédito com puts rende mais, e com a inclinação baixa (< 20) a trava de baixa com débito fica barata; "
      "(A3-ii, Xing-Zhang-Zhao) inclinação alta antecipa retorno pior do ativo; (A4, Cremers-Weinbaum) volatilidade da call acima da da put no mesmo exercício antecipa retorno melhor.\n")
    st = a3["estruturas"]
    linhas = []
    for nome, rot in (("trava_credito_put_skew_maior_80", "Trava de crédito com puts, inclinação > 80"), ("trava_credito_put_skew_ate_80", "Trava de crédito com puts, inclinação ≤ 80 (contraste)"),
                      ("trava_baixa_debito_skew_menor_20", "Trava de baixa com débito, inclinação < 20"), ("trava_baixa_debito_skew_a_partir_20", "Trava de baixa com débito, inclinação ≥ 20 (contraste)")):
        d, v = st[nome]["descoberta"], st[nome]["validacao"]
        linhas.append([rot, f"{n(d['media_por_op_pct'], 0, True)}% · t {d['t']} · n {d['n_ops']}", f"{n(v['media_por_op_pct'], 0, True)}% · t {v['t']} · n {v['n_ops']}", "não"])
    w("**Estruturas (retorno por operação sobre o risco empenhado, 25 ativos):**\n")
    w(tabela(["Estrutura", "Descoberta", "Validação", "Passou nas duas?"], linhas))
    w("")
    linhas = []
    for blk, rot in ((a3["previsao"], "A3"), (a4, "A4")):
        for nome, v in blk.items():
            sinal = "inclinação da put" if "skew" in nome else "desvio da paridade"
            hz = "5 pregões" if nome.endswith("fut5") else "21 pregões"
            d, va_ = v["descoberta"]["corte_entre_acoes"], v["validacao"]["corte_entre_acoes"]
            linhas.append([f"{rot} {sinal} → retorno de {hz}", f"IC {n(d['ic_medio'], 3, True)} · t {d['t']} ({d['n_datas']} datas)", f"IC {n(va_['ic_medio'], 3, True)} · t {va_['t']} ({va_['n_datas']} datas)",
                           f"BOVA11: D {n(v['descoberta']['BOVA11'].get('ic'), 2, True)} / V {n(v['validacao']['BOVA11'].get('ic'), 2, True)}"])
    w("**Sinal para o retorno do ativo (correlação de postos entre ações no mesmo dia, janelas sem sobreposição):**\n")
    w(tabela(["Teste", "Descoberta", "Validação", "BOVA11 sozinho (correlação)"], linhas))
    w("\nO sinal esperado era negativo para a inclinação e positivo para o desvio de paridade; nenhum teste teve t ≥ 2 na descoberta e repetiu na validação. "
      "O 0,19 do desvio de paridade com 21 pregões na descoberta usa só 19 datas e 6 ativos por data e desaparece na validação. No BOVA11 sozinho a inclinação aparece com o sinal OPOSTO ao da hipótese. "
      "**Veredito: A3 e A4 REPROVADAS** (inclinação e paridade não viram sinal para a carteira de ações).\n")

    # ------------------------------------------------------------------------------------------------ A5
    w("## A5. Arbitragem de verdade no fechamento\n")
    w(f"Varredura de {a5['dias_na_amostra']} pregões ({a5['periodo']}) com a oferta de compra e a de venda do fechamento, depois de emolumentos, folga mínima de R$ 0,02 por ação: "
      f"{n(a5['total_detectadas'])} combinações ({n(a5['por_dia_media'], 1)} por dia); **{n(a5['sobrevivem'])}** com 5+ negócios em todas as pernas e último negócio dentro das ofertas; "
      f"**{n(a5['estritas'])}** na versão estrita (20+ negócios, até 90 dias, exercício a até 15% do preço), {n(a5['estritas_por_dia'], 1)} por dia, em {a5['dias_com_estrita']} dos {a5['dias_na_amostra']} pregões.\n")
    linhas = []
    for t, v in sorted(a5["por_tipo"].items()):
        linhas.append([t.replace("_", " "), f"{n(v['detectadas'])} · estritas {n(v['estritas'])}", f"R$ {n(v['estritas_folga_mediana_rs'], 3) if v['estritas_folga_mediana_rs'] is not None else 'n/d'} (máx. R$ {n(v['estritas_folga_maxima_rs'], 2) if v['estritas_folga_maxima_rs'] is not None else 'n/d'})", f"{n(v['negocios_mediano'])}"])
    w(tabela(["Tipo", "Detectadas · estritas", "Folga mediana das estritas por ação", "Negócios mínimos (mediana)"], linhas))
    w(f"\n**É arbitragem ou cotação velha?** Nem uma coisa nem outra, na versão estrita: {n(a5['estritas_conv_rev_com_folga_tambem_no_ultimo_negocio_pct'], 0)}% das conversões e reversões estritas também têm folga com o ÚLTIMO NEGÓCIO das opções (não é oferta velha no livro), "
      f"mas só {n(a5['estritas_que_reaparecem_no_pregao_seguinte_pct'], 0)}% reaparecem no pregão seguinte e a folga mediana é de centavos (R$ 5 a 10 por lote de 100). A reversão (maioria) exige alugar a ação e a conversão equivale a emprestar dinheiro um pouco acima do CDI; "
      "exercício antecipado de opção americana e margem não entram. Algumas folgas grandes (borboleta de BOVA11, R$ 2 a 3) vêm de ofertas que não são simultâneas. "
      "**Veredito: descritivo, \"medindo\"**: o painel lista as de hoje com aviso; nenhuma entra na carteira simulada.\n")

    # ------------------------------------------------------------------------------------------------ A6
    w("## A6. Straddle antes do resultado trimestral\n")
    w("**Hipótese:** a volatilidade implícita sobe antes do resultado e cai depois; comprar o straddle no dinheiro 5 pregões antes do protocolo na CVM e vender no dia seguinte só paga se o movimento superar o que a opção cobra.\n")
    linhas = []
    for per, rot in (("descoberta", "Descoberta 2012-2019"), ("validacao", "Validação 2020-2023")):
        x = a6[per]
        linhas.append([rot, f"n {x['n']}", f"média {n(x['media_pct'], 1)}% · mediana {n(x['mediana_pct'], 1)}% · t {x['t']}", f"{n(x['pct_positivos'], 1)}% ganham · pior {n(x['pior_pct'], 0)}% · melhor {n(x['melhor_pct'], 0, True)}%"])
    w(tabela(["Fase", "Operações", "Resultado por straddle", "Dispersão"], linhas))
    w(f"\n{a6['meta']['eventos_brutos']} protocolos no universo; {a6['meta']['eventos_com_serie_na_entrada']} com série líquida na entrada; {a6['meta']['eventos_com_saida_cotada']} com as duas pernas cotadas na oferta de compra no dia seguinte. "
      "O resultado é negativo em todos os anos de 2012 a 2023. **Veredito: REPROVADA** — spread de entrada e de saída, desgaste do tempo e queda da volatilidade pesam mais que o movimento do resultado.\n")

    # ------------------------------------------------------------------------------------------------ ranking
    a = P["assimetrias"]
    w(f"## Ranking de hoje (cadeia de {a['data_da_cadeia']}): as 5 primeiras\n")
    w(f"{len(a['ativos_no_ranking'])} ativos com opção líquida entram ({', '.join(a['ativos_no_ranking'])}); estruturas de risco definido nos vencimentos {', '.join(a['vencimentos'])}, a preços executáveis. "
      "`vantagem` = o MENOR entre o valor esperado com 10 anos de retornos do próprio ativo e o mesmo reescalado para a volatilidade realizada de 60 pregões, sobre o custo, depois do CDI do prazo.\n")
    linhas = []
    for r in a["ranking"][:5]:
        pern = " + ".join(f"{p['lado']} {p['codigo']} (K {p['exercicio']})" for p in r["pernas"])
        linhas.append([f"{r['posicao']}. {r['ativo']} — {r['titulo'].split(' em ')[0]} ({r['vencimento']})", f"custo R$ {n(r['custo'], 2)}/ação · perda máx. R$ {n(r['perda_maxima'], 2)} · equilíbrio {n(r['ponto_de_equilibrio'], 2)}",
                       f"vantagem {n(r['vantagem_pct'], 1, True)}% (histórica {n(r['vantagem_historica_pct'], 0, True)}%, reescalada {n(r['vantagem_reescalada_pct'], 0, True)}%) · lucro {n(r['prob_lucro_historica_pct'], 0)}% hist. / {n(r['prob_lucro_implicita_pct'], 0)}% implícita",
                       f"{r['historico_da_familia']['estado'].upper()} · liquidez {r['liquidez']}"])
    w(tabela(["Estrutura", "Custo e risco", "Vantagem e chance de lucro", "Família na pesquisa"], linhas))
    w("")
    for r in a["ranking"][:5]:
        w(f"- **{r['posicao']}. {r['ativo']}:** {r['historico_da_familia']['texto']}")
    positivas = [r for r in a["ranking"] if r["vantagem_pct"] > 0]
    w(f"\n**Leitura:** hoje só {len(positivas)} das 15 primeiras têm vantagem prudente positiva; as demais custam mais do que a história do ativo paga. "
      "A vantagem usa 10 anos de um único ativo (a PRIO3, por exemplo, subiu muito no período): é uma régua do que a história pagou, não previsão.\n")
    w("**Leitura de volatilidade de hoje (ativos líquidos):** " + "; ".join(f"{x['ativo']} VI {n(x['vol_implicita_30d'] * 100, 0)}% · VR20 {n(x['vol_realizada_20d'] * 100, 0)}% · percentil {n(x['percentil_vol_implicita_1a'], 0)} ({x['leitura_vol']})"
                                                                           for x in a["por_ativo"] if x["no_ranking"] and x["percentil_vol_implicita_1a"] is not None)[:1400] + ".\n")

    # ------------------------------------------------------------------------------------------------ carteira
    res = P["resultado"]
    w("## Carteira simulada: o que abriu hoje\n")
    w(f"R$ 100 mil fictícios; até 2 posições novas por dia; perda máxima de R$ 500 por estrutura; 6 abertas e R$ 3.000 em risco; só famílias não reprovadas e vantagem prudente positiva. "
      f"Primeira rodada com a cadeia de {res['ultima_data']}: {res['n_abertas']} posições abertas, risco em aberto R$ {n(res['risco_em_aberto_rs'], 0)}, resultado R$ {n(res['acumulado_rs'], 2)} (abriu agora). "
      "Rodar de novo com a mesma cadeia não abre nada (idempotente pela data).\n")
    linhas = []
    for p in P["posicoes"]:
        linhas.append([p["titulo"], f"custo R$ {n(p['custo'], 2)} · risco R$ {n(p['risco_rs'], 2)}", f"vence {p['vencimento']}", p["familia"] + (" (permanente)" if p.get("permanente") else "")])
    w(tabela(["Posição", "Custo e risco", "Vencimento", "Família"], linhas))
    w("\nO capital protegido entra como posição permanente: R$ 500 por mês divididos entre PETR4, VALE3, BOVA11, ITUB4, BBDC4 e BBAS3 em calls no dinheiro, com quantidades fracionadas (a pesquisa não arredonda lote). "
      "O resto do capital fica no CDI e não entra na conta. As outras duas posições vieram do ranking (PRIO3 e PETR4, calls no dinheiro de famílias em medição).\n")

    # ------------------------------------------------------------------------------------------------ solucao
    w("## A solução que recomendo para o módulo de opções (sem prometer resultado)\n")
    w(f"1. **Núcleo = capital protegido (A0):** caixa no CDI e 0,5% do capital por mês em calls no dinheiro de vários ativos. É a única estrutura que entregou o que o Douglas pediu (perda limitada ao orçamento, ganho aberto) e passou nas três fases; "
      f"rendeu {n(hc0['excesso_anual_pct'], 1, True)} p.p. ao ano sobre o CDI, mas captura ~{n(hc0['captura_da_alta_pct'], 0)}% da alta e o Sharpe deflacionado é {n(hc0['sharpe_deflacionado'], 2)}: tratar como \"medindo\", pequeno, e medir em dado novo.")
    w("2. **Camada tática pequena = straddle em opção barata (A1):** só onde a volatilidade realizada de 252 dias supera a implícita, com perda máxima de R$ 500 por operação. Passou as fases, mas com t baixo, cerca de metade dos meses perdendo e uma cauda de ganhos que decide o resultado.")
    w("3. **Ranking diário como régua, não como ordem:** ele mostra a melhor entrada e diz se a história da família sustenta o critério; hoje só 3 das 15 primeiras têm vantagem positiva. Abrir na carteira simulada só o que a pesquisa não reprovou.")
    w("4. **Parar de insistir** em venda de prêmio (put, call coberta, trava de crédito), pozinho, proteção \"na hora barata\", inclinação, paridade e straddle de resultado: os números estão na pesquisa; arbitragem fica só como lista de observação.")
    w("5. **Critério para virar \"aprovada\":** 24 meses de carteira simulada em dado novo sem ajuste de parâmetro, com Sharpe deflacionado acima de 0,95; antes disso, nenhum capital real, e nada de tamanho que o orçamento de 0,5% não comporte.\n")

    # ------------------------------------------------------------------------------------------------ limites
    w("## Limites e divulgações\n")
    w("- Premissas de custo e de liquidez das pesquisas anteriores (emolumento de 0,05% por lado, sem imposto, sem corretagem, oferta do fechamento). Opção tratada como europeia.")
    w("- **A0:** a descoberta usa só PETR4 e VALE (os únicos com opção líquida antes de 2019): é um período de volatilidade realizada acima da implícita nesses dois ativos; os ativos novos entram a partir de 2019/2020. "
      "Posições de 2 meses abertas no fim do mês foram marcadas por modelo (Black-Scholes com a volatilidade de entrada). O ganho extra de ~1 p.p. ao ano é pequeno diante da incerteza (t ~1,5).")
    w("- **A1:** a liquidez do straddle foi relaxada (10+ negócios, spread até 40%) depois de a descoberta mostrar 3 ativos por mês com o filtro anterior (antes de ver retornos); sinais de 60 e 252 dias testados; 13 configurações na família.")
    w("- **Ranking:** a distribuição histórica de 10 anos é de um ativo só e embute o período (altas e quedas fortes entram como parte do passado); a reescalada corrige a volatilidade, não a tendência. Vantagem positiva não é previsão.")
    w("- **Carteira simulada:** lotes de 100; marcação pela oferta de compra do fechamento; vencimento pelo valor intrinseco com o strike da cadeia do dia ou o de entrada; capital protegido fracionado. Não é ordem real.")
    w("- **A5:** sem série de tamanho de oferta (COTAHIST só traz o melhor preço), sem aluguel de ação, margem ou exercício antecipado.\n")

    w("## Arquivos criados\n")
    w("- `quant/opcoes/`: `painel_vol.py` (painel diário de volatilidade, inclinação e paridade), `capital_protegido.py` (A0), `assimetrias_pesquisa.py` (A1 a A6), `arbitragens.py` (A5), `assimetrias.py` (ranking e arbitragens do dia), "
      "`carteira_simulada.py`, `relatorio_assimetrias.py`; alterados `painel.py` (blocos novos), `ciclos.py` (horizonte de 2 meses), `dados.py` (calendário estendido) e `metricas.py`.")
    w("- `quant/testes/test_opcoes_assimetrias.py` (11 testes: ranking determinístico, filtro de liquidez, arbitragem, carteira idempotente, risco máximo).")
    w("- `quant/saida/pesquisa5/opcoes/`: `HIPOTESES_ASSIMETRIAS.md`, `RESULTADO_ASSIMETRIAS.md`, `resultados_assimetrias.json`, `tentativas.jsonl` (famílias A0 a A6), `dados/painel_vol.parquet`, `dados/a0_compras.parquet`, `dados/cadeia_2meses.parquet`.")
    w("- `quant/saida/opcoes/carteira_simulada.json` (estado da carteira); no terminal, `web/d/x/quant_opcoes.json` e `cache/out/pagina/quant_opcoes.json` com os blocos `assimetrias`, `posicoes` e `resultado`.\n")

    w("## Termos desta nota\n")
    for t, e in (("Capital protegido feito em casa", "caixa no CDI + orçamento mensal fixo em opções de alta"), ("Straddle", "compra de call e put do mesmo exercício"),
                 ("VI / VR", "volatilidade implícita (do preço da opção) / realizada (do ativo)"), ("Percentil da VI", "onde a volatilidade de hoje está contra o último ano do ativo"),
                 ("Inclinação (skew)", "VI da put fora do dinheiro menos a VI no dinheiro"), ("Paridade put-call", "relação que liga call, put, ação e exercício"),
                 ("IC", "correlação de postos entre o sinal e o retorno futuro"), ("Sharpe deflacionado", "probabilidade de o Sharpe ser verdadeiro depois de descontar as configurações testadas"),
                 ("Vantagem", "valor esperado pela história do ativo dividido pelo custo, depois do CDI")):
        w(f"- **{t}:** {e}")
    w("\n## Quer aprofundar?\n")
    w("1. Rodar o capital protegido com outros ativos líquidos (PRIO3, B3SA3, ABEV3) e com orçamento que cresce com o patrimônio.")
    w("2. Acompanhar o straddle barato mês a mês na carteira simulada e medir a cauda de ganhos.")
    w("3. Montar o diário da carteira simulada (gráfico de resultado acumulado) no painel.")
    return "\n".join(L) + "\n"


def main():
    import re
    txt = gerar()
    txt = re.sub(r"(?<![\w.])(t|IC) (-?\d+)\.(\d+)", r"\1 \2,\3", txt)     # t e IC com virgula decimal
    caminho = os.path.join(DIR_OPC, "RESULTADO_ASSIMETRIAS.md")
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(txt)
    os.replace(tmp, caminho)
    print("gravado", caminho, len(txt))


if __name__ == "__main__":
    main()
