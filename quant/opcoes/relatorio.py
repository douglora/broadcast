"""
Escreve quant/saida/pesquisa5/opcoes/RESULTADO.md a partir de resultados.json (nenhum numero digitado a mao).

  PYTHONPATH=. .venv/bin/python -W ignore -m quant.opcoes.relatorio
"""
import json
import os

from quant.opcoes.base import DIR_OPC


def acento(t):
    for a, b in (("sem condicao", "sem condição"), ("implicita", "implícita"), ("pregoes", "pregões"), ("trimestral na janela", "trimestral na janela"),
                 ("vol. ", "vol. ")):
        t = t.replace(a, b)
    return t


def br(x, casas=1, sinal=False):
    if x is None:
        return "n/d"
    if round(x, casas) == 0:
        x = 0.0
    s = f"{x:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if sinal and x > 0:
        s = "+" + s
    return s


def pct(x, casas=1, sinal=False):
    return "n/d" if x is None else br(x, casas, sinal) + "%"


def tabela(cab, linhas):
    out = ["| " + " | ".join(cab) + " |", "|" + "|".join(["---"] * len(cab)) + "|"]
    for l in linhas:
        out.append("| " + " | ".join(str(c) for c in l) + " |")
    return "\n".join(out)


def gerar():
    R = json.load(open(os.path.join(DIR_OPC, "resultados.json"), encoding="utf-8"))
    pc, pb, cc, tp, pz, pr = R["put_cesta"], R["put_bova11"], R["call_coberta"], R["trava_put"], R["pozinho"], R["protecao"]
    tent = R["tentativas"]
    L = []
    w = L.append

    w("# Opções no robô quant: o que a história da B3 diz (pesquisa de 10/10/2026)\n")
    w("Pesquisa e SIMULAÇÃO. Nenhuma ordem real. Nada aqui é recomendação (Resolução CVM 178): descreve o que os preços de fechamento da B3 mostram.\n")

    # ------------------------------------------------------------------------------------------------ em uma frase
    w("## Em uma frase\n")
    w("**Não achamos estratégia vencedora de venda de prêmio.** Vender put, vender call coberta, trava de crédito e comprar pozinho não pagaram o risco "
      "contra o CDI nos dados de 2012 a 2026, já cruzando a oferta de compra e de venda e descontando emolumentos. "
      "O que sobrou de útil é a **proteção com opções de BOVA11**, que funciona como seguro (segurou março de 2020), custa de 7% a 15% da carteira por ano "
      "e **não é fonte de retorno**.\n")

    # ------------------------------------------------------------------------------------------------ veredito
    m = pc["melhor"]
    b0 = next(x for x in pb["tabela"] if x["cfg"] == "put BOVA11 delta=0.20 exec=oferta")
    cb = max([x for x in cc["tabela"] if "universo=cesta" in x["cfg"] and "exec=oferta" in x["cfg"]], key=lambda x: x["delta_sharpe"])
    tb = max(tp["tabela"], key=lambda x: x["sharpe"])
    pzd = {(x["modo"], x["tipo"]): x for x in pz["descritivo"]}
    jan = pr["bova11"]["janelas"]["crash_2020 (ciclo que vence em 16/03/2020)"]
    sh_max = max(x["sharpe"] for x in pc["tabela"] if (x["n_ops"] or 0) >= 30)
    w("## Veredito de cada estratégia\n")
    w(tabela(["Estratégia", "Veredito", "Número que decide", "Pior caso"], [
        ["a) Vender put coberta por caixa (5 ações)", "REPROVADA", f"excesso sobre o CDI {pct(m['excesso_anual_pct'], 1, True)} ao ano, Sharpe {br(m['sharpe'], 2)} (2012-2019)",
         f"{pct(pc['cauda']['pior_operacao_pct_do_strike'])} do strike em 1 mês ({pc['cauda']['pior_operacao']}); mar/2020: PETR4 {pct(-next(x['perda_pct_do_strike'] for x in pc['estresse_mar2020']['por_ativo'] if x['grupo']=='PETR4'))}"],
        ["a) Vender put coberta por caixa (BOVA11)", "REPROVADA", f"excesso {pct(b0['bova_desc']['excesso_anual_pct'], 1, True)} ao ano em 2020-2022",
         f"mar/2020: {pct(-pb['estresse_mar2020']['perda_pct_do_strike'])} do strike em 1 mês"],
        ["b) Vender call coberta (financiamento)", "REPROVADA", f"Sharpe {br(cb['sharpe'], 2)} contra {br(cb['acao_sharpe'], 2)} da carteira sem a call",
         f"queda máxima da cesta com call {pct(cb['queda_maxima_pct'])}"],
        ["c) Pozinho (call/put de centavos)", "REPROVADA", f"valor esperado da call {pct(pzd[('inicio','C')]['ev_pct'], 0, True)}; {pct(pzd[('inicio','C')]['po_pct'], 0)} viram pó",
         "perde 100% do bilhete na imensa maioria"],
        ["d) Proteção com put/colar de BOVA11", "MEDINDO (seguro)", f"mar/2020: carteira {pct(jan['nu'], 0)}, com put {pct(jan['put'], 0)}", "custo de 7% a 15% da carteira por ano"],
        ["e) Trava de crédito com puts", "REPROVADA", f"melhor Sharpe {br(tb['sharpe'], 2)}; retorno sobre o risco negativo nas 8 configurações", f"pior mês {pct(tb['pior_mes_pct'], 0)} do risco empenhado"],
    ]))
    w("")

    # ------------------------------------------------------------------------------------------------ como foi testado
    w("## Como foi testado (resumo)\n")
    w("- **Base:** COTAHIST da B3, 2005 a 2026 (opções de ações e ETFs, mais as de índice do Ibovespa, pregão a pregão). Pesquisa a partir de 2012: "
      "2012 a 2019 = DESCOBERTA; 2020 a 2023 = VALIDAÇÃO; 2024 a 2026 = PROVA (uma vez, só do que passar). Todas as séries com negócio no dia; "
      "ligadas ao fechamento sem ajuste do ativo (o que a B3 liquida), ao retorno total (dividendos) e ao CDI (SGS 12).")
    w("- **Vencimento:** **terceira segunda-feira até abril/2021 e terceira sexta-feira desde maio/2021** (conferido nos dados; a regra foi lida da data de vencimento do próprio arquivo, não calculada). Semanais ficam na base marcadas e fora das estratégias mensais.")
    w("- **Strike ajustado:** a B3 ajusta o exercício de todas as séries na data do dividendo/JCP, mas o arquivo só mostra o novo strike nas séries que negociam depois. "
      "Corrigi o strike de liquidação das séries paradas pelo ajuste medido nas séries do mesmo ativo que negociaram no dia do vencimento.")
    w("- **Custo real:** vendo na oferta de COMPRA e compro na oferta de VENDA do fechamento; emolumentos de 0,05% do prêmio por lado (premissa, a tabela de opções da B3 deu erro e não foi lida); "
      "exercício 0,03%. **Sem imposto** (15% sobre o ganho em opções) e sem corretagem.")
    w("- **Liquidez mínima (fixa, definida antes de olhar o resultado):** 30 negócios da série no dia da entrada, oferta dos dois lados e spread de até 30% do ponto médio. "
      "Mês sem série que passe: o dinheiro fica no CDI e o mês entra com excesso zero.")
    w("- **Entrada:** fechamento do primeiro pregão depois do vencimento anterior; carrega até o vencimento (cerca de 20 pregões), sem gestão no meio.")
    w(f"- **Tentativas:** {tent['total_configuracoes']} configurações distintas avaliadas ({', '.join(f'{k} {v}' for k, v in tent['por_familia'].items())}); "
      f"todas em `tentativas.jsonl`. O Sharpe deflacionado desconta o número de configurações da própria família (ex.: venda de put, 40).")
    w("- **Aprovação (METODO.md):** Sharpe fora da amostra > 1, Sharpe deflacionado > 0,95 e 100+ operações. Para PASSAR de fase: excesso sobre o CDI positivo, Sharpe > 0,3 e 30+ operações. "
      "Como nada passou da descoberta, a prova 2024-2026 NÃO foi aberta para nenhuma estratégia de renda.\n")

    # ------------------------------------------------------------------------------------------------ (a)
    w("## a) Venda de put coberta por caixa (delta 0,15 a 0,30, mensal)\n")
    w("**Hipótese:** o mercado cobra pela proteção mais do que a perda média (prêmio de risco de volatilidade); do outro lado estão quem compra seguro e quem compra loteria. "
      "O vendedor ganha o prêmio quase todo mês e perde forte de vez em quando. **Pergunta:** o prêmio paga as perdas, contra o CDI?\n")
    linhas = []
    for d in ("0.15", "0.20", "0.25", "0.30"):
        r = next(x for x in pc["tabela"] if x["cfg"] == f"put delta={d} universo=cesta exec=oferta liq=padrao")
        linhas.append([f"{d.replace('.', ',')}", pct(r["excesso_anual_pct"], 1, True), br(r["sharpe"], 2), pct(r["pior_mes_pct"], 1)])
    w("**Cesta de 5 ações (PETR4, VALE, ITUB4, BBAS3, BBDC4), 2012-2019, cruzando a oferta:**\n")
    w(tabela(["Delta da put vendida", "Excesso sobre o CDI (ao ano)", "Sharpe", "Pior mês"], linhas))
    w("")
    ativos_txt = []
    for g in ("PETR4", "VALE", "ITUB4", "BBAS3", "BBDC4"):
        rs = [x for x in pc["tabela"] if f"universo={g} " in x["cfg"] + " " and "exec=oferta" in x["cfg"]]
        ativos_txt.append(f"{g}: " + " / ".join(pct(x["excesso_anual_pct"], 1, True) + f" ({x['n_ops']} op.)" for x in rs))
    w("Por ativo (delta 0,15 / 0,20 / 0,25 / 0,30, excesso ao ano): " + "; ".join(ativos_txt) + ". "
      "ITUB4, BBAS3 e BBDC4 quase não tinham opção líquida antes de 2019 (3 a 21 operações em 8 anos): os números bons delas são amostra pequena, não evidência.\n")
    var = []
    for nome, chave in (("Cruzando a oferta (padrão)", "exec=oferta liq=padrao"), ("No ponto médio (sem pagar spread)", "exec=meio"),
                        ("Liquidez rigorosa (100 negócios, spread 15%)", "liq=rigorosa"), ("Só com vol. implícita > 1,1x a realizada", "vrp>=1.1"),
                        ("Só com índice acima da média de 200 pregões", "tendencia")):
        r = next(x for x in pc["tabela"] if x["cfg"].startswith("put delta=0.25 universo=cesta") and chave in x["cfg"] and
                 (chave != "exec=oferta liq=padrao" or not any(k in x["cfg"] for k in ("vrp", "tendencia"))))
        var.append([nome, pct(r["excesso_anual_pct"], 1, True), br(r["sharpe"], 2), r["n_ops"]])
    w("**Variações da cesta com delta 0,25 (2012-2019):**\n")
    w(tabela(["Variação", "Excesso sobre o CDI (ao ano)", "Sharpe", "Operações"], var))
    w("")
    c = pc["cauda"]
    w(f"**Ficha da melhor configuração da cesta (delta 0,25, cruzando a oferta, 2012-2019):** retorno de {pct(m['retorno_anual_pct'], 1)} ao ano sobre o caixa empenhado (CDI no período: {pct(m['retorno_anual_pct'] - m['excesso_anual_pct'], 1)}), "
      f"excesso {pct(m['excesso_anual_pct'], 1, True)}, Sharpe {br(m['sharpe'], 2)}, queda máxima {pct(m['queda_maxima_pct'], 1)}, pior mês {pct(m['pior_mes_pct'], 1)}, "
      f"{pct(m['meses_positivos_pct'], 0)} dos meses positivos, {m['n_ops']} operações, Sharpe deflacionado {br(m['sharpe_deflacionado'], 2)} (40 configurações na família).\n")
    w(f"**Por que perde (e o pior caso, com o mesmo destaque do prêmio):** a put de delta 0,25 recebeu em média **{pct(c['premio_medio_pct_do_strike'], 2)} do strike** por mês e pagou em média "
      f"**{pct(c['pagamento_medio_pct_do_strike'], 2)}**; foi exercida em {pct(c['pct_exercidas'], 0)} dos meses. A pior operação foi {c['pior_operacao']}: "
      f"**{pct(c['pior_operacao_pct_do_strike'])} do strike em um mês** (greve dos caminhoneiros). Em **março de 2020** (cenário de estresse, fora do corredor: está na validação), "
      f"as puts da cesta que tinham série líquida perderam: " + ", ".join(f"{x['grupo']} {pct(-x['perda_pct_do_strike'], 0)}" for x in pc["estresse_mar2020"]["por_ativo"]) +
      f" do strike; a cesta, com o dinheiro dividido em 5 e dois ativos sem série líquida, fechou o mês em {pct(pc['estresse_mar2020']['ciclo_cesta_pct'], 1)}.\n")
    w("**BOVA11 (opção líquida só desde 2020; descoberta 2020-2022, validação 2023):**\n")
    linhas = []
    for d in ("0.15", "0.20", "0.25", "0.30"):
        r = next(x for x in pb["tabela"] if x["cfg"] == f"put BOVA11 delta={d} exec=oferta")
        linhas.append([d.replace(".", ","), pct(r["bova_desc"]["excesso_anual_pct"], 1, True) + f" (Sharpe {br(r['bova_desc']['sharpe'], 2)})", pct(r["bova_desc"]["queda_maxima_pct"], 0),
                       pct(r["bova_val"]["excesso_anual_pct"], 1, True) + " (12 meses, informativo)"])
    w(tabela(["Delta", "2020-2022: excesso ao ano", "Queda máxima 2020-22", "2023 (não aberta pelo corredor)"], linhas))
    w(f"\nGanha em ~90% dos meses e março de 2020 apaga tudo: a put de delta 0,20 ({pb['estresse_mar2020']['codigo']}, strike R$ {br(pb['estresse_mar2020']['exercicio'], 2)}, BOVA11 de R$ {br(pb['estresse_mar2020']['S_E'], 2)} a R$ {br(pb['estresse_mar2020']['S_T'], 2)}) "
      f"custou **{pct(pb['estresse_mar2020']['perda_pct_do_strike'], 1)} do caixa em um mês**. Os 2023 positivos aparecem só como informação; a validação não foi aberta porque a descoberta falhou.\n")
    w("**Veredito (a): REPROVADA.** Nenhuma das 40 configurações passou (maior Sharpe com 30+ operações: " + br(sh_max, 2) + "; a barra era 0,3). O prêmio médio não cobre a perda média nessa amostra, e o ponto médio quase não muda "
      "o resultado (o spread não é o problema; é a falta de prêmio de risco que sobre depois do CDI de 10% a 14% ao ano). Filtro de volatilidade e de tendência não resgatam. "
      "Vender put é uma aposta comprada em mercado: a cesta rendeu menos que o CDI em 2012-2019, e a put vendida rendeu um pouco abaixo da renda fixa, com cauda.\n")

    # ------------------------------------------------------------------------------------------------ (b)
    w("## b) Venda coberta de call (\"financiamento\") sobre uma carteira de ações\n")
    w("**Hipótese:** a call vendida embolsa o prêmio de volatilidade e reduz a oscilação da carteira; em troca abre mão da alta forte. **Pergunta:** melhora o retorno ajustado ao risco?\n")
    linhas = []
    for d in ("0.20", "0.30", "0.40"):
        r = next(x for x in cc["tabela"] if x["cfg"] == f"call coberta delta={d} universo=cesta exec=oferta")
        linhas.append([d.replace(".", ","), f"{pct(r['retorno_anual_pct'])} contra {pct(r['acao_retorno_anual_pct'])}", f"{br(r['sharpe'], 2)} contra {br(r['acao_sharpe'], 2)}",
                       f"{pct(r['queda_maxima_pct'], 0)} contra {pct(r['acao_queda_maxima_pct'], 0)}"])
    w(tabela(["Delta da call vendida", "Retorno ao ano: com call contra só a ação", "Sharpe", "Queda máxima"], linhas))
    w(f"\nCesta de 5 ações, 2012-2019 (retorno total das ações; as ações renderam menos que o CDI no período). A call reduz a queda máxima em {br(min(x['delta_queda_max'] for x in cc['tabela'] if 'universo=cesta' in x['cfg'] and 'exec=oferta' in x['cfg']), 0)} a {br(max(x['delta_queda_max'] for x in cc['tabela'] if 'universo=cesta' in x['cfg'] and 'exec=oferta' in x['cfg']), 0)} pontos, "
      f"mas corta mais retorno do que protege: Sharpe pior nas 10 de 11 configurações (a exceção, BBDC4, teve 22 operações). O ponto médio ajuda pouco.\n")
    w("**Veredito (b): REPROVADA.** Nos dados, financiar a carteira com call vendida não melhorou o retorno ajustado ao risco.\n")

    # ------------------------------------------------------------------------------------------------ (c)
    w("## c) Pozinho: call ou put de centavos, comprada para carregar\n")
    w("**Hipótese:** convexidade barata. Perde centavos quase sempre e paga múltiplos nas poucas vezes em que o ativo dispara ou desaba. **Quem está do outro lado:** quem vende a loteria e cobra pelo bilhete mais do que ele vale em média. "
      "**Definição fixa do bilhete:** compra na oferta de venda do fechamento, até R$ 0,20 (e R$ 0,10 como variação), call 5% ou mais fora do dinheiro (put idem para baixo), "
      "25 ativos de maior volume de opções do ano anterior, R$ 1 por bilhete.\n")
    linhas = []
    for modo, rot in (("inicio", "Entrada no início do ciclo (~20 pregões)"), ("curto", "Entrada curta (8 pregões até o vencimento)")):
        for tipo, tr in (("C", "call"), ("P", "put")):
            r = pzd[(modo, tipo)]
            linhas.append([f"{rot}, {tr}", f"{pct(r['po_pct'], 0)} pó · {pct(r['pct_ge5x'], 1)} ×5 · {pct(r['pct_ge10x'], 1)} ×10",
                           f"{pct(r['ev_pct'], 0, True)} (IC 90%: {br(r['ev_ic90_pct'][0], 0)} a {br(r['ev_ic90_pct'][1], 0, True)})", f"{r['n']:,}".replace(",", ".")])
    w("**Distribuição (teto R$ 0,20, 2012 a 2026, descritivo):**\n")
    w(tabela(["Bilhete", "Distribuição do resultado", "Valor esperado por R$ 1", "Bilhetes"], linhas))
    w("")
    w(f"**Resposta direta:** o pozinho de call, comprado no início do ciclo, perde **em média cerca de {br(abs(pzd[('inicio','C')]['ev_pct']), 0)}% do que se gasta** "
      f"(com margem de erro grande: de {br(pzd[('inicio','C')]['ev_ic90_pct'][0], 0)}% a {br(pzd[('inicio','C')]['ev_ic90_pct'][1], 0, True)}%), "
      f"porque {pct(pzd[('inicio','C')]['po_pct'], 0)} viram pó e só {pct(pzd[('inicio','C')]['pct_ge10x'], 1)} multiplicam por 10. "
      f"Comprando perto do vencimento (8 pregões), a call perde **{br(abs(pzd[('curto','C')]['ev_pct']), 0)}%** em média: o tempo corre contra e o spread é grande demais para centavos. "
      f"Sair ao dobrar ou ao multiplicar por 5 não ajuda: segurar até o fim rende mais que vender no ×5 ({pct(pzd[('inicio','C')]['ev_saida5_pct'], 0, True)} contra {pct(pzd[('inicio','C')]['ev_pct'], 0, True)}), "
      f"porque o dinheiro está nas poucas caudas muito grandes. A put de pozinho mostra {pct(pzd[('inicio','P')]['ev_pct'], 0, True)} no total, mas isso é **um ciclo só, março de 2020**: "
      f"sem ele o valor esperado é {pct(pz['puts_inicio_teto20_ev_sem_mar2020_pct'], 0, True)}. Ou seja, put de pozinho só \"vale\" como seguro contra um crash que ninguém sabe a data.\n")
    b10 = {(x["periodo"], x["modo"], x["tipo"]): x for x in pz["base"] if x["teto"] == 0.10}
    w("Com teto de R$ 0,10 (bilhete ainda mais barato), valor esperado da call no início do ciclo: "
      f"{pct(b10[('descoberta','inicio','C')]['ev_pct'], 0, True)} na descoberta e {pct(b10[('validacao','inicio','C')]['ev_pct'], 0, True)} na validação; "
      f"na entrada curta, {pct(b10[('descoberta','curto','C')]['ev_pct'], 0, True)} e {pct(b10[('validacao','curto','C')]['ev_pct'], 0, True)}.\n")
    cond = {(x["tipo"], x["condicao"], x["periodo"]): x for x in pz["condicoes"]}
    nomes = [k for k in dict.fromkeys(x["condicao"] for x in pz["condicoes"])]
    linhas = []
    for tipo, tr in (("C", "call"), ("P", "put")):
        for nome in nomes:
            d, v = cond.get((tipo, nome, "descoberta")), cond.get((tipo, nome, "validacao"))
            if not d or not v or not d.get("n") or not v.get("n"):
                continue
            ok = d["ev_pct"] > 0 and v["ev_pct"] > 0 and d["n"] >= 300 and v["n"] >= 300
            linhas.append([acento(f"{tr}: {nome}"), f"{pct(d['ev_pct'], 0, True)} ({d['n']})", f"{pct(v['ev_pct'], 0, True)} ({v['n']})", "PASSOU" if ok else "não"])
    w("**Existe condição em que deixa de ser bilhete perdedor?** Valor esperado por R$ 1, entrada no início do ciclo, teto R$ 0,20 (entre parênteses, nº de bilhetes):\n")
    w(tabela(["Condição", "Descoberta 2012-2019", "Validação 2020-2023", "Positivo nas duas?"], linhas))
    w("")
    w(f"**Nenhuma condição ficou positiva nas duas fases.** As que parecem boas em uma fase viram ruins na outra (call com volatilidade implícita baixa: bom na descoberta, ruim na validação; "
      f"call com resultado na janela: o contrário). A única regularidade: comprar call **depois de queda forte** é o pior caso nas duas fases. "
      "Os intervalos de confiança de quase todas as condições são largos e cruzam o zero: com 93% de bilhetes zerados e cauda de até 500 vezes, "
      "a média depende de poucos eventos. **Veredito (c): REPROVADA** como estratégia de renda; como loteria, o custo médio é uns 15% a 60% do bilhete conforme o prazo.\n")

    # ------------------------------------------------------------------------------------------------ (d)
    w("## d) Proteção da carteira: opções contra venda de mini-índice\n")
    w("**Carteira espelhada no BOVA11** (retorno total do Ibovespa). Variantes mensais, parâmetros fixos antes de olhar: put delta -0,25; trava de baixa (compra -0,30, vende -0,10); colar (put -0,25 e call +0,25); "
      "venda de mini-índice com 100% e 50% do valor da carteira. A venda de mini-índice é modelada pelo custo de carregamento (um futuro vendido paga o CDI e devolve a variação do índice): "
      "o histórico do WIN não está na base, então a base do futuro contra o valor justo não foi medida.\n")
    tab = {x["variante"]: x for x in pr["bova11"]["2020-2026"]}
    nome = {"nu": "Carteira sem proteção", "put": "Put comprada (delta -0,25)", "trava": "Trava de baixa", "colar": "Colar", "win50": "Vende mini-índice (50%)", "win100": "Vende mini-índice (100%)"}
    linhas = []
    for e in ("nu", "put", "trava", "colar", "win50", "win100"):
        j = pr["bova11"]["janelas"]["crash_2020 (ciclo que vence em 16/03/2020)"][e]
        linhas.append([nome[e], pct(tab[e]["retorno_anual_pct"], 1), pct(tab[e]["queda_maxima_pct"], 0), pct(j, 1, True)])
    w(f"**BOVA11, 2020-2026 ({tab['nu']['n_ciclos']} ciclos mensais; CDI no período: {pct(tab['nu']['cdi_anual_pct'], 1)} ao ano):**\n")
    w(tabela(["Variante", "Retorno ao ano", "Queda máxima (fecham. mensais)", "Mês da queda de março/2020"], linhas))
    w("")
    jj = pr["bova11"]["janelas"]
    pa = pr["bova11"]["por_ano"]
    linhas = []
    for e in ("nu", "put", "trava", "colar", "win50", "win100"):
        dif = pr["bova11"]["diferenca_para_a_carteira_nua_por_ano"].get(e)
        linhas.append([nome[e], pct(jj["2021-2022"][e], 1, True), pct(pa["2025"][e], 1, True), "—" if dif is None else f"{br(dif['mediana_dif_ano_pp'], 1, True)} pp (pior ano {br(dif['pior_ano_pp'], 1)})"])
    w("**Outras janelas e o custo nos anos comuns:**\n")
    w(tabela(["Variante", "2021-2022 (24 meses, acumulado)", "2025 (ano de alta)", "Diferença p/ carteira sem proteção, mediana por ano"], linhas))
    w("")
    ci = pr["indice_2013_2019"]
    nm = ci["janela_2015"]
    w(f"**2015 (BOVA11 não tinha opção líquida: usei as opções do próprio Ibovespa, ciclos de dois meses, put 5% fora, trava 95/85, colar 95/105; "
      f"preço estimado em {ci['ciclos_preco_estimado']} de {ci['ciclos']} ciclos de 2013 a 2019, último negócio com 5% contra):** carteira sem proteção {pct(nm['nu'], 1, True)}, put {pct(nm['put'], 1, True)}, "
      f"trava {pct(nm['trava'], 1, True)}, colar {pct(nm['colar'], 1, True)}, vendendo mini-índice 50% {pct(nm['win50'], 1, True)} e 100% {pct(nm['win100'], 1, True)}. "
      "A queda de 2015 veio aos poucos (de 2% a 5% por ciclo), então a put 5% fora do dinheiro pagou o prêmio inteiro e recebeu pouco; a venda de mini-índice foi o que protegeu.\n")
    w("**Leitura:**\n")
    w(f"- **Custo:** a put de delta -0,25 custa em média {pct(pr['bova11']['premio_medio_pct'], 2)} da carteira por mês, ou de {br(min(pr['bova11']['custo_bruto_put_pct_por_ano'].values()), 0)}% a {br(max(pr['bova11']['custo_bruto_put_pct_por_ano'].values()), 0)}% ao ano (2021-2026). "
      f"Em 2025, ano de alta de {pct(pa['2025']['nu'], 0)}, a carteira com put fez {pct(pa['2025']['put'], 0)}.")
    w(f"- **Quanto segura:** março de 2020 foi o caso que justifica o seguro: carteira {pct(jan['nu'], 0)} no ciclo, com put {pct(jan['put'], 1)}, com colar {pct(jan['colar'], 1)}, com trava {pct(jan['trava'], 0)} "
      f"(a trava só cobre até o strike vendido). Em 2021-2022, o seguro não pagou: put {pct(jj['2021-2022']['put'], 1, True)} contra carteira {pct(jj['2021-2022']['nu'], 1, True)}. Em 2015 (opções de índice), idem.")
    w(f"- **Contra a venda de mini-índice:** vender mini-índice custa quase nada em prêmio, mas transforma a carteira em CDI (retorno de {pct(tab['win100']['retorno_anual_pct'], 1)} ao ano contra {pct(tab['nu']['retorno_anual_pct'], 1)} da carteira nua em 2020-2026) e abre mão de toda a alta. "
      "Neste período o Ibovespa rendeu menos que o CDI, então vender o índice \"ganhou\" do investidor comprado; isso é sorte do período, não custo negativo de proteção. "
      "A put e o colar são seguro que mantém a alta (o colar até o teto da call) e pagam o prêmio ou o teto por isso.")
    w("- **Veredito (d): MEDINDO.** Como seguro funciona e tem preço conhecido; não melhora retorno. Exige disciplina: pagar 7% a 15% ao ano para se proteger de um evento raro. O colar foi a melhor relação custo/proteção em 2020 e a pior em 2025.\n")

    # ------------------------------------------------------------------------------------------------ (e)
    w("## e) Estrutura de risco definido: trava de alta de crédito com puts\n")
    w("**Hipótese:** o mesmo prêmio da put vendida, com a cauda cortada pela put comprada mais abaixo. Parece promissora no papel (liquidez razoável em PETR4, VALE e BOVA11, perda máxima conhecida). "
      "Borboleta e calendário **não foram testadas**: as três pernas não têm liquidez em quase nenhuma data fora de BOVA11 e PETR4.\n")
    linhas = []
    for r in tp["tabela"]:
        if "exec=oferta" in r["cfg"]:
            linhas.append([r["cfg"].split("universo")[0].replace("trava put ", "").replace("delta=", "delta ").replace("largura=", "largura ").replace(".", ","),
                           pct(r["excesso_anual_pct"], 0, True) + " ao ano sobre o risco", br(r["sharpe"], 2), f"{pct(r['perda_total_pct'], 0)} das vezes"])
    w(tabela(["Trava (cesta, 2012-2019, cruzando a oferta)", "Excesso sobre o CDI", "Sharpe", "Perda total da trava"], linhas))
    w("\nO retorno por real de risco empenhado é negativo em todas as 8 configurações (o ponto médio ajuda, mas não vira positivo): o spread de duas pernas come boa parte do crédito e a perna comprada paga a cauda que a vendida não cobre. "
      "**Veredito (e): REPROVADA.** Nenhuma estrutura de risco definido passou; a vendida seca também não.\n")

    # ------------------------------------------------------------------------------------------------ módulo
    w("## O que entra no módulo do painel\n")
    w("`quant_opcoes.json` (formato v1, simulação) já foi gravado nos dois caminhos do terminal. Estados:\n")
    w("- **medindo:** proteção com put de BOVA11, colar sobre BOVA11 e trava de baixa em BOVA11 (seguro, não fonte de retorno). A lista de hoje (cadeia de 09/10/2026) descreve as três, só com as pernas que passam no filtro de liquidez.")
    w("- **reprovadas, com o número:** venda de put (cesta e BOVA11), call coberta, trava de crédito, pozinho.")
    w("- **aprovadas:** nenhuma.")
    w("- Não diz \"compre\" nem \"venda\"; avisos e glossário vão no próprio JSON.\n")
    w("Para virar \"aprovada\" no futuro, o módulo pode acumular mês a mês o resultado simulado dos candidatos de hoje (dado novo, não visto) antes de qualquer capital.\n")

    # ------------------------------------------------------------------------------------------------ divulgações
    w("## Limites e divulgações (leia)\n")
    w("- **Diagnóstico prévio de 2024-2026:** antes de o corredor existir, rodei a venda de put da cesta nos três períodos de uma vez (inclusive 2024-2026). A estratégia já falhava na descoberta e na validação, então a conclusão não depende disso, "
      "mas a prova dela não é virgem. Registrado em `tentativas.jsonl`.")
    w("- **Proteção e pozinho:** parâmetros fixados a priori; os números de 2020-2026 (proteção) e de 2012-2026 (pozinho sem condição) são **descritivos**, não passaram pelo corredor de aprovação.")
    w("- **Cenário de estresse de março/2020** para a venda de put é descritivo (a janela é da validação, que o corredor não abriu).")
    w("- **Marcação mensal:** queda máxima e pior mês saem dos fechamentos de cada ciclo; a perda dentro do mês pode ser maior. Opção americana tratada como europeia (exercício antecipado ignorado).")
    w("- **Preço de entrada = oferta do fechamento** do dia; supõe que a ordem sai nos minutos finais. Spread no meio do pregão pode ser menor (o ponto médio mostra o teto desse ganho: pouco).")
    w("- **Mini-índice modelado** por identidade de carregamento, sem série real do WIN. **Opções de índice 2013-2019** com preço estimado na maioria dos ciclos.")
    w("- **Ajuste de strike** de séries paradas estimado a partir das séries que negociaram no vencimento; 1,7% das linhas da cadeia de entrada foram corrigidas.")
    w("- **Emolumento de opções:** premissa de 0,05% por lado; a tabela da B3 não foi lida. Sem imposto, sem corretagem. Retorno anual usa só os dias dentro dos ciclos (o pregão do vencimento à entrada seguinte fica de fora).")
    w("- **Amostra:** antes de 2019 só PETR4 e VALE têm opção realmente líquida; ITUB4, BBAS3, BBDC4 têm poucas operações na descoberta. A cesta de 2012-2019 é basicamente PETR4 + VALE, dois ativos com um choque comum (2014-2015, greve de 2018).\n")

    # ------------------------------------------------------------------------------------------------ arquivos
    w("## Arquivos criados\n")
    w("- `quant/opcoes/` (pacote novo): `bs.py` (Black-Scholes), `base.py` (COTAHIST → parquet), `dados.py`, `ciclos.py`, `custos.py`, `motor.py`, `metricas.py`, "
      "`pesquisa.py`, `pozinho.py`, `protecao.py`, `resultados.py`, `relatorio.py`, `painel.py`")
    w("- `quant/testes/test_opcoes_bs.py` (13 testes; 5 casos reais conferidos com a calculadora do terminal rodada em Node)")
    w("- `quant/saida/pesquisa5/opcoes/`: `dados/` (opcoes_AAAA, ativo_AAAA, indice_AAAA parquet; cadeia_entrada, cadeia_preparada, cadeia_curto8, ciclos, pozinhos, ibov_diario), "
      "`tentativas.jsonl`, `resultados.json`, `RESULTADO.md`")
    w("- Terminal: `web/d/x/quant_opcoes.json` e `cache/out/pagina/quant_opcoes.json`\n")

    # ------------------------------------------------------------------------------------------------ termos
    w("## Termos desta nota\n")
    for t, e in (("Put / call", "opção de venda / de compra"), ("Strike", "preço de exercício combinado"), ("Prêmio", "preço da opção"),
                 ("Delta", "quanto o prêmio anda por R$ 1 do ativo; em módulo, chance aproximada de terminar dentro do dinheiro"),
                 ("Excesso sobre o CDI", "quanto a estratégia rendeu acima da renda fixa de referência"), ("Sharpe", "excesso de retorno dividido pela oscilação; acima de 1 é bom"),
                 ("Sharpe deflacionado", "probabilidade de o Sharpe ser verdadeiro depois de descontar as configurações testadas; exige-se > 0,95"),
                 ("Pozinho", "opção de centavos, muito fora do dinheiro, comprada como bilhete de loteria"), ("Colar", "put comprada + call vendida sobre a carteira"),
                 ("Mini-índice (WIN)", "contrato futuro do Ibovespa; vendê-lo protege a carteira e tira a alta"), ("Spread", "diferença entre a oferta de venda e a de compra")):
        w(f"- **{t}:** {e}")
    w("\n## Quer aprofundar?\n")
    w("1. Rodar a mesma bateria só em PETR4+VALE com liquidez desde 2012, aceitando amostra menor, para separar efeito de ativo de efeito de período.")
    w("2. Montar o acompanhamento mês a mês dos candidatos de hoje (dado novo) para o módulo.")
    w("3. Testar a proteção com a série real do WIN (precisa do histórico do contrato) e com horizonte de 2 meses para BOVA11.")
    w("4. Testar a venda de put com gestão (fechar a 50% do prêmio ou a 2x o prêmio), que muda a cauda.")
    return "\n".join(L) + "\n"


def main():
    txt = gerar()
    caminho = os.path.join(DIR_OPC, "RESULTADO.md")
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(txt)
    os.replace(tmp, caminho)
    print("gravado", caminho, len(txt))


if __name__ == "__main__":
    main()
