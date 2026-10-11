"""
Escreve quant/saida/pesquisa5/opcoes/RESULTADO_TESES.md a partir de resultados_teses.json, resultados_assimetrias.json e do quant_opcoes.json do terminal.

  PYTHONPATH=. .venv/bin/python -W ignore -m quant.opcoes.relatorio_teses
"""
import json
import os
import re

from quant.opcoes.base import DIR_OPC
from quant.opcoes.relatorio import br, pct, tabela

SAIDA = "/Users/douglaslora/Desktop/terminal-artefato/web/d/x/quant_opcoes.json"


def n(x, c=0, sinal=False):
    return br(x, c, sinal)


def gerar():
    RT = json.load(open(os.path.join(DIR_OPC, "resultados_teses.json"), encoding="utf-8"))
    RA = json.load(open(os.path.join(DIR_OPC, "resultados_assimetrias.json"), encoding="utf-8"))
    P = json.load(open(SAIDA, encoding="utf-8"))
    q, el, rq, gt = RT["queda_forte"], RT["eleicoes"], RT["resultado_trimestral"], RT["gatilho_tecnico"]
    L = []
    w = L.append
    h1 = RA["A0"]["historico_completo"]["call_atm_1m orcamento=1.0%"]
    h5 = RA["A0"]["historico_completo"]["call_atm_1m orcamento=0.5%"]
    pr1 = RA["A0"]["prova"]["call_atm_1m orcamento=1.0%"]
    tese = P["teses"][0]
    cob = q["cobertura"]
    A_ = q["A"]

    w("# Terceira etapa: orçamento de 1%, as duas regras do Douglas, as eleições e o livro de teses (10/10/2026, noite)\n")
    w("Pesquisa e SIMULAÇÃO. Nenhuma ordem real. Nada aqui é recomendação (Resolução CVM 178). Hipóteses escritas antes de rodar em `HIPOTESES_TESES.md`; tentativas em `tentativas.jsonl` (famílias T2, T3, T5); "
      "descoberta até 2019, validação 2020-2023, prova 2024-2026 fechada salvo para quem passou nas duas fases.\n")

    # ------------------------------------------------------------------------------------------------ em uma frase
    w("## Em uma frase\n")
    w(f"**A regra nº 1 (vender put depois de queda forte) NÃO melhora a venda de put: a média por operação ficou em {n(A_['descoberta']['put_vendida']['media_pct'], 2, True)}% e {n(A_['validacao']['put_vendida']['media_pct'], 2, True)}% (descoberta e validação), "
      f"contra {n(A_['descoberta']['put_vendida_todos_os_dias']['media_pct'], 2, True)}% e {n(A_['validacao']['put_vendida_todos_os_dias']['media_pct'], 2, True)}% vendendo em qualquer dia, e só {n(cob['pct_com_put_executavel'], 0)}% das quedas fortes tinham put que desse para vender.** "
      f"**A regra nº 2 (opção no lugar do papel antes de um evento binário) é mais cara do que parece:** nas seis eleições de 2014, 2018 e 2022 a volatilidade implícita despencou {n(abs(el['esmagamento_vol_pct']['mediana']), 0)}% (mediana) depois do evento "
      f"e a call no dinheiro perdeu em média {n(abs(next(x for x in el['medias_por_entrada_saida'] if x['entrada_pregoes_antes'] == 5 and x['saida_pregoes_depois'] == 5)['call'][0]), 0)}% entrando 5 pregões antes e saindo 5 depois, "
      f"enquanto o papel ganhou {n(next(x for x in el['medias_por_entrada_saida'] if x['entrada_pregoes_antes'] == 5 and x['saida_pregoes_depois'] == 5)['papel'][0], 1, True)}% em média. "
      "São **seis eventos**: serve para entender o mecanismo, não para tirar regra. No caso trabalhado do Douglas (BBAS3 e o 2º turno), a call no dinheiro de hoje só empata se o BBAS3 subir " + n(next(e for e in tese['expressoes'] if e['nome'] == 'call_no_dinheiro')['movimento_de_empate_pct'], 1) + "% até 30/10 (já com o esmagamento da volatilidade): com movimentos de ±" + n(tese['movimento_base_pct'], 1) + "%, o preço pede " + n(next(e for e in tese['expressoes'] if e['nome'] == 'call_no_dinheiro')['probabilidade_que_o_preco_exige_pct'], 0) + "% de chance de alta.\n")

    # ------------------------------------------------------------------------------------------------ item 1
    w("## 1. Orçamento do capital protegido em 1% do capital por mês (R$ 1.000)\n")
    w("Aprovado pelo Douglas em 10/10/2026. Os números do quadro passam a ser os medidos com 1,0% (a pesquisa A0 já tinha os três orçamentos, com a prova 2024-2026 aberta uma vez para eles):\n")
    w(tabela(["Medida (call no dinheiro de ~1 mês, 6 ativos, 2012-2026)", "0,5% (antes)", "**1,0% (agora)**", "Referência"], [
        ["Retorno ao ano", pct(h5["retorno_anual_pct"]), f"**{pct(h1['retorno_anual_pct'])}**", f"CDI {pct(h1['cdi_anual_pct'])} · ações {pct(h1['ref_ativo_aa_pct'])} · 70/30 {pct(h1['ref_70_30_aa_pct'])}"],
        ["Excesso sobre o CDI · Sharpe", f"{n(h5['excesso_anual_pct'], 2, True)} p.p. · {n(h5['sharpe'], 2)}", f"**{n(h1['excesso_anual_pct'], 2, True)} p.p. · {n(h1['sharpe'], 2)}**", f"prova 2024-2026: {n(pr1['excesso_anual_pct'], 2, True)} p.p. · Sharpe {n(pr1['sharpe'], 2)}"],
        ["Pior mês do patrimônio", pct(h5["pior_mes_pct"], 2), f"**{pct(h1['pior_mes_pct'], 2)}**", "o orçamento do mês é 1,0%"],
        ["Pior ano · queda máxima", f"{pct(h5['pior_ano_pct'])} · {pct(h5['queda_maxima_pct'], 2)}", f"**{pct(h1['pior_ano_pct'])} · {pct(h1['queda_maxima_pct'], 2)}**", f"ações: pior ano {pct(h1['pior_ano_do_ativo_pct'])}, queda {pct(h1['ref_ativo_queda_maxima_pct'])}"],
        ["Participação na alta · anos parados", f"{pct(h5['captura_da_alta_pct'], 0)} · {n(h5['excesso_medio_ano_parado_pct'], 2, True)} p.p.", f"**{pct(h1['captura_da_alta_pct'], 0)} · {n(h1['excesso_medio_ano_parado_pct'], 2, True)} p.p.**", f"acima do CDI em {pct(h1['anos_acima_do_cdi_pct'], 0)} dos anos"]]))
    w("")
    cp = [p for p in P["posicoes"] if p.get("permanente")]
    if cp:
        c = cp[0]
        w(f"**Carteira simulada:** a tranche do mês (vencimento {c['vencimento']}) foi aberta com R$ 500 e **completada com os R$ 500 que faltavam** na cadeia de 09/10/2026 (agora R$ {n(c['custo'], 2)}; "
          f"marcada pela oferta de compra, o resultado de abertura é {n(c['resultado_rs'], 2, True)}, que é o spread de entrada nas seis calls). Rodar de novo não completa de novo: o estado guarda `orcamento_rs` e só completa quando ele está abaixo do orçamento. "
          "A pesquisa anterior continua valendo: 1% captura ~14% da alta, o pior mês foi -0,83% e o Sharpe deflacionado (0,47) não chega a 0,95: segue \"medindo\".\n")

    # ------------------------------------------------------------------------------------------------ item 2
    w("## 2. Regra nº 1 do Douglas: vender put depois de queda forte\n")
    w(f"**Hipótese (do Douglas):** papel líquido que caiu demais em poucos pregões e perdeu as médias tem volatilidade implícita alta; quem vende put recebe mais para comprar mais barato. "
      f"**Definição fixa antes de rodar:** retorno de 5 pregões ≤ -8% **ou** ≤ -2 desvios dos 252 pregões anteriores, **e** fechamento abaixo das médias de 21 e 50 pregões (versão A; a B exige também abaixo da de 200). "
      f"Put vendida coberta por caixa (delta 0,25, ~21 pregões, 30+ negócios, spread até 30%), trava de alta de crédito com puts (compra a ~5% abaixo), comparadas com **comprar o papel no mesmo dia e segurar até a mesma data** e com **a mesma put vendida em qualquer dia** (a cada 5 pregões).\n")
    linhas = []
    for per, rot in (("descoberta", "Descoberta 2012-2019"), ("validacao", "Validação 2020-2023")):
        b = A_[per]
        linhas.append([f"{rot}: put vendida", f"{n(b['put_vendida']['media_pct'], 2, True)}% (n {b['put_vendida']['n']}, t {n(b['put_vendida']['t'], 2)})", f"{n(b['put_vendida_todos_os_dias']['media_pct'], 2, True)}% (n {b['put_vendida_todos_os_dias']['n']})",
                       f"{n(b['dif_put_sinal_menos_todos_pp']['dif'], 2, True)} p.p. (t {n(b['dif_put_sinal_menos_todos_pp']['t'], 2)})"])
        linhas.append([f"{rot}: trava de crédito", f"{n(b['trava_credito']['media_pct'], 1, True)}% (n {b['trava_credito']['n']}; pior {n(b['trava_credito']['pior_pct'], 0)}%)", f"{n(b['trava_todos_os_dias']['media_pct'], 1, True)}% (n {b['trava_todos_os_dias']['n']})",
                       f"{n(b['dif_trava_sinal_menos_todos_pp']['dif'], 1, True)} p.p. (t {n(b['dif_trava_sinal_menos_todos_pp']['t'], 2)})"])
        linhas.append([f"{rot}: comprar o papel", f"{n(b['papel']['media_pct'], 2, True)}% (n {b['papel']['n']}, pior {n(b['papel']['pior_pct'], 0)}%)", f"{n(b['papel_todos_os_dias']['media_pct'], 2, True)}% (n {b['papel_todos_os_dias']['n']})", "—"])
    w("**Versão A, resultado médio por operação (put e papel: excesso sobre o CDI sobre o capital; trava: sobre o risco máximo):**\n")
    w(tabela(["Fase e estrutura", "Depois de queda forte", "Em qualquer dia", "Diferença (sinal menos qualquer dia)"], linhas))
    w("")
    vb = q["B"]
    w(f"**Versão B (também abaixo da média de 200):** put vendida {n(vb['descoberta']['put_vendida']['media_pct'], 2, True)}% (n {vb['descoberta']['put_vendida']['n']}) na descoberta e {n(vb['validacao']['put_vendida']['media_pct'], 2, True)}% (n {vb['validacao']['put_vendida']['n']}) na validação; "
      f"diferença para qualquer dia {n(vb['descoberta']['dif_put_sinal_menos_todos_pp']['dif'], 2, True)} e {n(vb['validacao']['dif_put_sinal_menos_todos_pp']['dif'], 2, True)} p.p.; a trava teve {vb['descoberta']['trava_credito']['n']} operações na descoberta (sem amostra).\n")
    w(f"**Cobertura (o ponto que mais pesa):** dos {n(cob['sinais_A'])} sinais da versão A (2012-2023), **só {n(cob['com_put_executavel'])} ({n(cob['pct_com_put_executavel'], 1)}%)** tinham uma put de delta ~0,25 com 30+ negócios e spread de até 30% para vender. "
      f"Depois de quedas fortes o spread abre e a liquidez some. Em **março de 2020** foram {cob['marco_2020']['sinais']} sinais e **só {cob['marco_2020']['com_put_executavel']}** com put executável; "
      f"os sinais sem put teriam rendido {n(cob['marco_2020']['retorno_medio_21_pregoes_dos_sinais_pct'], 1)}% em média nos 21 pregões seguintes. Nos sinais que tinham put, a queda continuou em {n(q['quedas_que_continuaram']['pct_eventos_A_com_queda_adicional_acima_de_10pct'], 0)}% dos casos (mais de 10% adicionais até o vencimento) "
      f"e a put foi exercida em {n(q['quedas_que_continuaram']['pct_eventos_A_exercidos'], 0)}% (em qualquer dia: {n(q['quedas_que_continuaram']['pct_todos_os_dias_exercidos'], 0)}%).\n")
    linhas = [[x["dia"], f"{n(x['preco_entrada'], 2)} → {n(x['preco_vencimento'], 2)} (exercício {n(x['exercicio'], 2)})", f"{n(x['resultado_put_pct_do_exercicio'], 1, True)}%", f"{n(x['resultado_papel_pct'], 1, True)}%"] for x in cob["petr4_2014_2015"]]
    w("**A cauda, PETR4 2014-2015 (cada linha é um sinal que tinha put executável):**\n")
    w(tabela(["Dia do sinal", "Preço do ativo: entrada → vencimento", "Resultado da put vendida (% do exercício)", "Comprar o papel"], linhas))
    w("")
    pior = q["cauda"][:6]
    am = q["amer3"]
    w("**Piores casos de put vendida depois de queda forte (2012-2023):** " + "; ".join(f"{x['ativo']} {x['dia']} (perda de {n(x['perda_pct_do_exercicio'], 0)}% do exercício; de {n(x['preco_na_entrada'], 2)} a {n(x['preco_no_vencimento'], 2)})" for x in q["cauda"][:6]) +
      ". **Março de 2020:** " + ("; ".join(f"{x['ativo']} {x['dia']} ({n(x['perda_pct_do_exercicio'], 1)}% do exercício)" for x in cob["marco_2020"]["casos_com_put"]) or "nenhuma put executável") +
      f" — dos {cob['marco_2020']['sinais']} sinais de 20/02 a 10/04, só estes tinham put que desse para vender; nos dias de pânico o spread passa de 30% e a regra fica sem como ser executada. "
      f"**Americanas (AMER3, 12/01/2023, {n(am['queda_do_dia_pct'], 0)}% num dia, de R$ {n(am['preco_11_01'], 2)} a R$ {n(am['preco_12_01'], 2)}):** o sinal do robô NÃO dispara, porque a série de retorno total do projeto descarta queda diária acima de 50% (limpeza de desdobramento); "
      f"marcado à mão: no dia seguinte (13/01) havia a put {am['put']} (delta {n(am['delta'], 2)}, exercício R$ {n(am['exercicio'], 2)}) com oferta de compra de R$ {n(am['bid'], 2)}; o papel fechou a R$ {n(am['ultimo_preco_disponivel'], 2)} em {am['ultima_data']} "
      f"(último preço disponível na base), o que daria uma perda de ~{n(am['perda_marcada_pct_do_exercicio'], 0)}% do exercício marcada a esse preço. É o tipo de caso em que a venda de put depois de uma queda forte perde muito, e a regra não o enxerga.\n")
    w(f"**Veredito da regra nº 1: NÃO MELHORA, e o que parece melhorar é a trava de crédito com amostra minúscula.** A condição \"depois de queda forte\" deixa a put vendida igual ou um pouco pior que vender em qualquer dia ({n(A_['descoberta']['dif_put_sinal_menos_todos_pp']['dif'], 1, True)} e {n(A_['validacao']['dif_put_sinal_menos_todos_pp']['dif'], 1, True)} p.p., sem significância), "
      f"e comprar o papel depois da queda também não pagou ({n(A_['descoberta']['papel']['media_pct'], 1, True)}% e {n(A_['validacao']['papel']['media_pct'], 1, True)}%). A trava de crédito aparece melhor que em qualquer dia "
      f"({n(A_['descoberta']['dif_trava_sinal_menos_todos_pp']['dif'], 0, True)} e {n(A_['validacao']['dif_trava_sinal_menos_todos_pp']['dif'], 0, True)} p.p.), mas com {A_['descoberta']['trava_credito']['n']} e {A_['validacao']['trava_credito']['n']} operações, desvio de ~40% do risco e perda de 100% do risco em algumas: "
      "t de 1,1 na descoberta, abaixo do exigido (2,0). **Critério fixo: \"sem diferença comprovada\"; a prova 2024-2026 não foi aberta.** O mecanismo dele (volatilidade alta paga mais) é real no preço, mas é o preço de um risco que se concretiza: "
      f"a ação continua caindo em {n(q['quedas_que_continuaram']['pct_eventos_A_com_queda_adicional_acima_de_10pct'], 0)}% dos casos e a liquidez desaparece justamente nas piores quedas, o que impede de executar. "
      "A regra não vira tese automática do robô.\n")

    # ------------------------------------------------------------------------------------------------ item 3
    w("## 3. Regra nº 2 do Douglas: evento binário, opção no lugar do papel\n")
    w("**Descritivo, sem regra.** Eleições (domingo; pregão de reação = segunda): 2014 (05/10 e 26/10), 2018 (07/10 e 28/10), 2022 (02/10 e 30/10). Ativos com opção: BBAS3, PETR4, ELET3, CMIG4, SBSP3 e o Ibovespa (opções de índice). "
      "Entrada no fechamento 10, 5 e 1 pregão antes do pregão de reação; saída no próprio pregão de reação (1 depois) e quatro pregões depois (5 depois). "
      f"**Atenção: são seis eventos, de cinco a seis ativos, com janelas que se sobrepõem. {n(el['linhas_estimadas_pct'], 0)}% das linhas usam o último negócio com 5% contra no lugar de oferta (as opções de 2014 e 2018 quase não têm oferta no fechamento). Não se tira regra de seis observações.**\n")
    medias = {(x["entrada_pregoes_antes"], x["saida_pregoes_depois"]): x for x in el["medias_por_entrada_saida"]}
    linhas = []
    for k in (10, 5, 1):
        for j in (1, 5):
            x = medias[(k, j)]
            linhas.append([f"Entra {k} antes, sai {j} depois", f"{n(x['papel'][0], 1, True)}% (n {x['papel'][1]})", f"{n(x['call'][0], 1, True)}% (n {x['call'][1]})", f"{n(x['straddle'][0], 1, True)}% (n {x['straddle'][1]})"])
    w("**Resultado médio por estrutura (todos os ativos e eventos com preço de entrada e de saída):**\n")
    w(tabela(["Janela", "Papel", "Call no dinheiro", "Straddle"], linhas))
    linhas = []
    for k in (10, 5, 1):
        for j in (1, 5):
            x = medias[(k, j)]
            linhas.append([f"Entra {k} antes, sai {j} depois", f"{n(x['trava_alta'][0], 1, True)}% (n {x['trava_alta'][1]})", f"{n(x['put'][0], 1, True)}% (n {x['put'][1]})"])
    w("\n" + tabela(["Janela", "Trava de alta (no dinheiro / +10%)", "Put no dinheiro"], linhas))
    w("")
    linhas = []
    def pc_(x, c=0, sinal=False, suf="%"):
        return "n/d" if x is None else n(x, c, sinal) + suf
    for x in el["bbas3_k5_j5"]:
        linhas.append([x["evento"], f"papel {pc_(x['papel'], 1, True)} · call {pc_(x['call'], 0, True) if x['call'] is not None else 'sem preço'}", f"{pc_(x['iv_in'])} → {pc_(x['iv_out'])} (esmagamento {pc_(x['esmagamento_pct'], 0, True)})",
                       f"exigia {pc_(x['exigido_call_pct'], 1, True)} · veio {pc_(x['veio_pct'], 1, True)}"])
    w("**BBAS3, entrando 5 pregões antes e saindo 5 depois (volatilidade implícita na entrada → saída; movimento que a call exigia para empatar na saída contra o que veio):**\n")
    w(tabela(["Evento", "Resultado", "Volatilidade implícita (esmagamento)", "O preço exigia · o ativo fez"], linhas))
    bm = el["bbas3_movimentos"]
    w("\nMovimento do BBAS3 (papel, 5 antes a 5 depois) nos seis turnos: " + "; ".join(f"{x['evento']} {n(x['movimento_pct'], 1, True)}%" for x in bm) +
      f". Esmagamento da volatilidade na saída de 1 pregão, todos os ativos: mediana **{n(el['esmagamento_vol_pct']['mediana'], 0)}%** (intervalo interquartil {n(el['esmagamento_vol_pct']['p25'], 0)}% a {n(el['esmagamento_vol_pct']['p75'], 0)}%, n {el['esmagamento_vol_pct']['n']}); "
      f"a call no dinheiro exigia, para empatar na saída, um movimento mediano de **{n(el['call_exigia_empatar_mediano_pct'], 1, True)}%** e o ativo fez, em módulo, **{n(el['movimento_absoluto_que_veio_mediano_pct'], 1)}%** (mediana); "
      f"só {n(el['calls_que_empataram_na_saida_pct'], 0)}% das calls empataram na saída.\n")
    ct = rq["call_contra_papel"]
    linhas = []
    for per, rot in (("descoberta", "Descoberta"), ("validacao", "Validação")):
        for lado, chave, nome in (("subiu", "papel_subiu", "papel subiu"), ("caiu", "papel_caiu", "papel caiu")):
            b = ct[per][chave]
            linhas.append([f"{rot}: {nome} (n {b['n']})", f"papel {n(b['papel_medio_pct'], 1, True)}% · opção {n(b['opcao_media_pct'], 0, True)}%", f"{n(b['opcao_melhor_que_o_papel_pct_dos_eventos'], 0)}% dos eventos", f"movimento mediano {n(b['mov_papel_mediano_pct'], 1)}%"])
    w("**Série maior: resultado trimestral (protocolo na CVM), call (ou put) no dinheiro contra o papel no MESMO lado, entrada 5 pregões antes, saída no dia seguinte:**\n")
    w(tabela(["Fase e lado", "Retorno médio", "Opção melhor que o papel em", "Tamanho do movimento"], linhas))
    g = {per: ct[per]["movimento_de_5pct_ou_mais"] for per in ("descoberta", "validacao")}
    w(f"\nA call foi melhor que o papel quando o papel subiu forte (movimento de 5% ou mais: call {n(g['descoberta']['call_media_pct_quando_subiu'], 0, True)}% na descoberta e {n(g['validacao']['call_media_pct_quando_subiu'], 0, True)}% na validação) e pior nos movimentos pequenos, "
      f"em que o spread e o desgaste do tempo comem tudo (opção melhor que o papel em só ~1/3 dos eventos na validação). O esmagamento da volatilidade de 30 dias em resultado trimestral é pequeno: mediana {n(rq['esmagamento_vol']['mediana_pct'], 1)}% (n {rq['esmagamento_vol']['n']}), "
      "contra -28% nas eleições: quem compra opção antes de eleição paga um prêmio de evento muito maior.\n")
    w("**Veredito da regra nº 2: o mecanismo dele está certo no sentido (a call limita a perda ao prêmio), mas o PREÇO do evento é alto.** Antes das eleições a volatilidade implícita do BBAS3 foi de 52% a 70% ao ano e caiu ~45% a 50% no 1º e 2º turnos de 2022; "
      "a call precisava de +7% a +10% na saída e o ativo fez +4,7% e -5,7%. Em 2018 (2º turno) o ativo subiu 8,9% e a call ainda perdeu (preços estimados; sem esmagamento medido). "
      "A opção só bate o papel quando o movimento passa do que o preço exige; com seis eventos não há regra para dizer quando.\n")

    # ------------------------------------------------------------------------------------------------ item 4: caso BBAS3
    w("## 4. Livro de teses e o caso BBAS3 (2º turno em 25/10/2026, cadeia de 09/10/2026)\n")
    w("**Tese do Douglas:** BBAS3, alta, evento no 2º turno (domingo 25/10; reação na segunda 26/10), horizonte de 14 pregões, vencimento de 19/11 (27 pregões). "
      f"BBAS3 fechou a R$ {n(tese['preco_do_ativo'], 2)}; a volatilidade implícita de 30 dias está em {n(next(x['vol_implicita_30d'] for x in P['assimetrias']['por_ativo'] if x['ativo'] == 'BBAS3') * 100, 0)}% ao ano, no {n(next(x['percentil_vol_implicita_1a'] for x in P['assimetrias']['por_ativo'] if x['ativo'] == 'BBAS3'), 0)}º percentil do último ano. "
      f"**A probabilidade do cenário político é DELE: o robô não preencheu.** Cenários: \"direita na frente\" +{n(tese['movimento_base_pct'], 1)}% ou \"outro resultado\" -{n(tese['movimento_base_pct'], 1)}% (mediana do módulo do movimento do BBAS3 nos seis turnos de 2014 a 2022); "
      f"na saída, a volatilidade implícita cai {n(abs(tese['esmagamento_considerado_pct']), 0)}% (esmagamento mediano das eleições). Tudo em R$ por lote de 100.\n")
    linhas = []
    nomes = {"papel": "Papel (100 ações)", "call_no_dinheiro": "Call no dinheiro", "call_fora_do_dinheiro": "Call fora do dinheiro (delta ~0,25)", "trava_de_alta": "Trava de alta (compra no dinheiro, vende delta ~0,25)",
             "put_vendida_coberta": "Put vendida coberta por caixa", "trava_de_alta_com_puts": "Trava de alta de crédito com puts"}
    for e in tese["expressoes"]:
        exige = []
        if e["movimento_de_empate_pct"] is not None and e["nome"] != "papel":
            exige.append(f"empate com o ativo {n(e['movimento_de_empate_pct'], 1, True)}% no horizonte")
        if e["probabilidade_que_o_preco_exige_pct"] is not None and e["nome"] != "papel":
            exige.append(f"{n(e['probabilidade_que_o_preco_exige_pct'], 0)}% de chance de alta")
        if e.get("prob_implicita_de_exercicio_pct") is not None:
            exige.append(f"o preço embute {n(e['prob_implicita_de_exercicio_pct'], 0)}% de terminar no dinheiro")
        if e["nome"] == "papel":
            exige.append("50% de chance de alta (cenários simétricos)")
        custo = f"R$ {n(abs(e['custo']), 0)}" + (" de crédito" if e["custo"] < 0 else "")
        perda = f"R$ {n(e['perda_maxima'], 0)}" + ("" if e["cabe_no_teto"] else " (passa do teto de R$ 500)")
        linhas.append([nomes[e["nome"]], custo, perda, "; ".join(exige)])
    w("**BBAS3: o que cada expressão custa e o que o preço exige (cenários ±" + n(tese["movimento_base_pct"], 1) + "%):**\n")
    w(tabela(["Expressão", "Custo (ou crédito)", "Perda máxima", "O que o preço exige"], linhas))
    w("")
    sp = tese["sensibilidade_probabilidade"]
    linhas = []
    for e in tese["expressoes"]:
        linhas.append([nomes[e["nome"]]] + [f"{n(sp[k]['valor_esperado_rs'][e['nome']], 0, True)}" for k in ("40%", "50%", "60%")])
    w(f"**Valor esperado em R$ por lote, conforme a chance que o Douglas der ao cenário de alta (movimento de ±{n(tese['movimento_base_pct'], 1)}%):**\n")
    w(tabela(["Expressão", "Se a chance for 40%", "Se for 50%", "Se for 60%"], linhas))
    w("")
    sm = tese["sensibilidade_movimento"]
    linhas = []
    for mv, bl in sm.items():
        for k in ("40%", "50%", "60%"):
            b = bl[k]["valor_esperado_rs"]
            linhas.append([f"Movimento {mv.replace('.', ',')} · chance de alta {k}", f"call {n(b['call_no_dinheiro'], 0, True)} · fora {n(b['call_fora_do_dinheiro'], 0, True)}", f"trava {n(b['trava_de_alta'], 0, True)} · crédito puts {n(b['trava_de_alta_com_puts'], 0, True)}", bl[k]["escolhida"] or "nenhuma"])
    w("**E se o movimento for maior? Valor esperado (R$ por lote) por tamanho de movimento e chance de alta:**\n")
    w(tabela(["Cenário", "Calls", "Travas", "Escolhida pela regra"], linhas))
    w("")
    call = next(e for e in tese["expressoes"] if e["nome"] == "call_no_dinheiro")
    trava = next(e for e in tese["expressoes"] if e["nome"] == "trava_de_alta")
    w(f"**O que o preço das calls exige:** a call no dinheiro (R$ {n(call['custo'], 0)} por lote, volatilidade implícita de {n(call['pernas'][0]['vol_implicita'] * 100, 0)}%) só empata na saída se o BBAS3 subir **{n(call['movimento_de_empate_pct'], 1)}%** até 30/10, já descontado o esmagamento; "
      f"com cenários de ±{n(tese['movimento_base_pct'], 1)}%, isso pede **{n(call['probabilidade_que_o_preco_exige_pct'], 0)}% de chance** do cenário de alta; com cenários de ±15%, {n(tese['sensibilidade_movimento']['±15%']['50%']['prob_exigida_pct']['call_no_dinheiro'], 0)}%. A trava de alta custa {n((1 - trava['custo'] / call['custo']) * 100, 0)}% menos e exige {n(trava['probabilidade_que_o_preco_exige_pct'], 0)}%. "
      f"A única expressão com valor esperado positivo em todas as colunas dos cenários de ±{n(tese['movimento_base_pct'], 1)}% é a **put vendida coberta**, mas ela empenha R$ {n(next(e for e in tese['expressoes'] if e['nome'] == 'put_vendida_coberta')['caixa_empenhado'], 0)} por lote (passa do teto de R$ 500) e ganha só o prêmio. "
      "**Escolha da regra: nenhuma expressão cabe no teto com valor esperado positivo nesses cenários** — a carteira simulada não abre nada com a tese dele (a probabilidade é do Douglas e está marcada como pendente). "
      f"**Esmagamento depois do evento:** pela história das seis eleições, a volatilidade implícita cai ~28% (mediana); no BBAS3, 50% no 1º turno de 2022 e 45% no 2º. Isso tira R$ {n(abs(call['efeito_do_esmagamento_rs']), 0)} do valor esperado da call por lote (campo `efeito_do_esmagamento_rs` do JSON).\n")

    w("**Regra de escolha do livro de teses (explícita):** entre as expressões que cabem no teto de R$ 500 de perda máxima por estrutura (um lote de 100) e têm valor esperado positivo, a de MAIOR valor esperado por R$ de perda máxima. "
      "Papel puro entra com perda máxima igual ao preço inteiro e quase nunca cabe; aparece na tabela com o pior cenário. Tese sem cenários usa a distribuição histórica do ativo no prazo (cinco faixas de peso igual). "
      "O livro lê `quant/saida/mesa/teses.json` e os eventos binários de `quant/saida/mesa/visao_mesa.json`; **nenhum dos dois existe ainda**, então hoje o bloco `teses` traz só o caso do Douglas. "
      "Teses automáticas do robô pela \"queda forte\" não foram criadas porque a regra 1 não melhorou a venda de put.\n")
    abertas = [p for p in P["posicoes"] if p.get("tese_id")]
    w(f"**O que o livro de teses abriu na carteira simulada hoje:** {'nada' if not abertas else ', '.join(p['titulo'] for p in abertas)}. "
      "Motivos: a tese do Douglas está com a probabilidade pendente (não abre sozinha) e a regra não achou expressão que caiba; as teses da mesa e as automáticas ainda não existem. "
      "O caminho está testado: uma tese de origem `mesa` ou `robo` com cenários definidos abre a expressão escolhida (marcando `origem` e `tese_id`) dentro do mesmo teto de R$ 500, 6 abertas e R$ 3.000.\n")

    # ------------------------------------------------------------------------------------------------ item 5
    w("## 5. Gatilho técnico de alta: papel contra call no dinheiro contra trava de alta (21 pregões)\n")
    w("**Gatilhos fixos:** T1 = fechamento acima da máxima dos 55 fechamentos anteriores; T2 = volta acima da média de 200 (ontem abaixo) com a média de 50 virando para cima. "
      "Retorno por R$ 1 empenhado menos o CDI do prazo (papel sobre o preço; call e trava sobre o prêmio). Critério fixo: média da opção positiva e média/desvio maior que a do papel nas duas fases.\n")
    linhas = []
    for trg, rot in (("T1", "T1 rompimento de 55"), ("T2", "T2 retomada da média de 200")):
        for per, pl in (("descoberta", "D"), ("validacao", "V")):
            b = gt[trg][per]
            linhas.append([f"{rot} ({pl}, n {b['papel']['n']})", f"papel {n(b['papel']['media_pct'], 1, True)}% (média/desvio {n(b['papel']['media_sobre_desvio'], 2)})", f"call {n(b['call_no_dinheiro']['media_pct'], 1, True)}% ({n(b['call_no_dinheiro']['media_sobre_desvio'], 2)}) · pior {n(b['call_no_dinheiro']['pior_pct'], 0)}%",
                           f"trava {n(b['trava_alta']['media_pct'], 1, True)}% ({n(b['trava_alta']['media_sobre_desvio'], 2)}; n {b['trava_alta']['n']})"])
    w(tabela(["Gatilho e fase", "Papel", "Call no dinheiro", "Trava de alta"], linhas))
    w("")
    base = gt["T1"]["descoberta"]
    w(f"**Qualquer dia (comparador):** papel {n(base['qualquer_dia_papel']['media_pct'], 1, True)}% e call {n(base['qualquer_dia_call']['media_pct'], 1, True)}% na descoberta; papel {n(gt['T1']['validacao']['qualquer_dia_papel']['media_pct'], 1, True)}%, call {n(gt['T1']['validacao']['qualquer_dia_call']['media_pct'], 1, True)}% e trava {n(gt['T1']['validacao']['qualquer_dia_trava']['media_pct'], 1, True)}% na validação.")
    if gt["prova"]:
        for k, v in gt["prova"].items():
            op = [c for c in v if c != "papel"][0]
            w(f"- **{k} passou na descoberta e na validação pelo critério fixo, e a PROVA 2024-2026 foi aberta uma vez:** {op.replace('_', ' ')} {n(v[op]['media_pct'], 1, True)}% (n {v[op]['n']}, média/desvio {n(v[op]['media_sobre_desvio'], 2)}, pior {n(v[op]['pior_pct'], 0)}%) contra papel {n(v['papel']['media_pct'], 1, True)}%: **não se sustentou**.")
    w("\n**Resposta:** o rompimento de 55 pregões não deu ao papel um retorno ajustado ao risco melhor que o de qualquer dia (média perto de zero), e a opção dependeu da fase: a call foi negativa na descoberta e positiva na validação; a trava passou as duas primeiras fases e perdeu na prova. "
      "A retomada da média de 200 (T2) só funcionou na descoberta, com poucos eventos. **Veredito: a opção NÃO melhora de forma comprovada o retorno ajustado ao risco dado o gatilho técnico.**\n")

    # ------------------------------------------------------------------------------------------------ limites
    w("## Limites e divulgações\n")
    w("- **Item 2:** a put executável (delta 0,25, 30+ negócios, spread até 30%) existe em só " + n(cob["pct_com_put_executavel"], 1) + "% dos sinais, então o resultado vale para as quedas em que ainda há mercado de opção; o viés é contra a regra nas quedas piores. "
      "O exercício na data do vencimento sai dos proventos da tabela de eventos (confere com o exercício corrigido do ciclo mensal: mediana de 0,4 centavo nos ciclos com provento); operações com desdobramento, grupamento, bonificação ou subscrição na janela foram descartadas. "
      "Retorno da put e do papel sobre o capital; da trava, sobre o risco máximo. Amostra de \"qualquer dia\": a cada 5 pregões por ativo, com erro-padrão por mês.")
    w("- **Item 3:** seis eventos; preços de 2014 e 2018 sem oferta no fechamento na maior parte (último negócio com 5% contra), então os retornos das opções desses anos são aproximados; o empate recalculado usa Black-Scholes europeu com a volatilidade da saída. "
      "Ibovespa por opções de índice (preço estimado). ELET3, CMIG4 e SBSP3 quase não tinham opção em 2014.")
    w("- **Item 4:** a reavaliação no horizonte é Black-Scholes com a volatilidade de hoje (sem inclinação, sem efeito do evento além do esmagamento mediano) e saída pela metade do spread de entrada; os cenários de ±" + n(tese['movimento_base_pct'], 1) + "% são ilustrativos (mediana dos movimentos do BBAS3), a probabilidade é do Douglas. "
      "Capital protegido completado em fração de ação (a pesquisa não arredonda lote).")
    w("- **Item 5:** retornos por R$ de prêmio são grandes e muito dispersos (perda de ~100% em boa parte das operações): olhe a média sobre o desvio e o pior caso. Prova aberta uma vez, só para T1 trava de alta.")
    w("- **Prova 2024-2026:** aberta apenas no item 5 (T1 trava de alta) e já aberta antes para A0 e A1; nos itens 2 e 3 não foi aberta.\n")

    w("## Arquivos criados\n")
    w("- `quant/opcoes/`: `diario.py` (tabela diária de opções líquidas e ajuste de proventos), `queda_forte.py` (item 2), `eleicoes.py` (item 3), `gatilho_tecnico.py` (item 5), `teses.py` (livro de teses), `teses_pesquisa.py`, `relatorio_teses.py`; alterados `carteira_simulada.py` (orçamento de 1%, completar a tranche, abrir teses), `painel.py` (bloco `teses`, quadro com 1%) e `assimetrias.py`.")
    w("- `quant/testes/test_opcoes_teses.py` (12 testes). Os três arquivos de teste de opções: 36 passam.")
    w("- `quant/saida/pesquisa5/opcoes/`: `HIPOTESES_TESES.md`, `RESULTADO_TESES.md`, `resultados_teses.json`, `dados/opcoes_diarias.parquet`, `tentativas.jsonl` (T2, T3, T5); estado da carteira em `quant/saida/opcoes/carteira_simulada.json`; no terminal, só os dois `quant_opcoes.json`.")
    return "\n".join(L) + "\n"


def main():
    txt = gerar()
    txt = re.sub(r"(?<![\w.])(t|IC) (-?\d+)\.(\d+)", r"\1 \2,\3", txt)
    caminho = os.path.join(DIR_OPC, "RESULTADO_TESES.md")
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(txt)
    os.replace(tmp, caminho)
    print("gravado", caminho, len(txt))


if __name__ == "__main__":
    main()
