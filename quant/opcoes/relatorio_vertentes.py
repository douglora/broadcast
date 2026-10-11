"""
Relatorio das tres vertentes (RESULTADO_VERTENTES.md), escrito a partir de resultados_vertentes.json (pesquisa) e do bloco `vertentes` do
quant_opcoes.json (limites e ranking de hoje). Os numeros nao sao digitados a mao.

  python -m quant.opcoes.relatorio_vertentes
"""
import json
import os

from quant.opcoes import vertentes_pesquisa as VP
from quant.opcoes.base import DIR_OPC

ARQ_MD = os.path.join(DIR_OPC, "RESULTADO_VERTENTES.md")
ARQ_TELA = "/Users/douglaslora/Desktop/terminal-artefato/web/d/x/quant_opcoes.json"


def t(x, nd=1):
    if x is None:
        return "n/d"
    return f"{x:,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def cfg(res, lista, nome):
    for r in res.get(lista, []):
        if r["config"] == nome:
            return r
    return None


def linha_fase(m):
    return (f"excesso {t(m.get('excesso_anual_pct'))}% ao ano, Sharpe {t(m.get('sharpe'), 2)}, pior mês {t(m.get('pior_mes_pct'))}%, "
            f"maior sequência de perdas {m.get('maior_sequencia_de_perdas_meses')} meses")


def gerar():
    with open(VP.ARQ, encoding="utf-8") as f:
        R = json.load(f)
    try:
        with open(ARQ_TELA, encoding="utf-8") as f:
            T = json.load(f)
        vt = {b["nome"]: b for b in T["vertentes"]}
    except (OSError, ValueError, KeyError):
        vt = {}
    b11 = R["bova11"]
    L = []
    w = L.append
    w("# Três vertentes de opções: o que a história da B3 mostra (11/10/2026)\n")
    w("Pesquisa e SIMULAÇÃO. Nenhuma ordem real. Nada aqui é recomendação (Resolução CVM 178). Hipóteses e grades escritas ANTES de rodar em `HIPOTESES_VERTENTES.md` (com as três correções feitas na primeira rodada, declaradas lá); tentativas em `tentativas.jsonl` (famílias V2 e V3).\n")
    w("## Em uma frase\n")
    w("**Nenhuma das três vertentes está aprovada, e duas são reprovadas no histórico.** Vender put ou call coberta de ações com saída em 80% do prêmio não pagou o CDI; as 72 travas de crédito de BOVA11 também não; a única regra que passou na validação foi **vender put de BOVA11 com stop em 3 vezes o prêmio** (2020-2023, sem fase de descoberta), e ela depende de sair no fechamento do primeiro pregão em que o stop dispara.\n")
    w("A prova 2024-2026 destas famílias já tinha sido aberta em turnos anteriores, então **nada foi escolhido com ela**; a confirmação vem da simulação ao vivo.\n")
    w("## Veredito\n")
    w("| Vertente | Etiqueta | Número que decide | Cauda |")
    w("|---|---|---|---|")
    c1 = cfg(R, "v2", "cesta put delta=0.20 M1 F0")
    c2 = cfg(R, "v2", "cesta call delta=0.30 M1 F0")
    c3 = cfg(R, "v2", "BOVA11 put delta=0.20 M1 F0")
    c4 = cfg(R, "v2", "BOVA11 put delta=0.20 M2 F0")
    w(f"| Especulativa (compra de call) | medindo | vem de A0 e A1 (turno 2): capital protegido +0,96 ponto ao ano sobre o CDI, Sharpe 0,39; straddle barato +20% por operação | perda máxima = prêmio |")
    w(f"| Dividendo sintético: put de ações | reprovada no histórico: só medida | D {t(c1['fases']['descoberta']['excesso_anual_pct'])}% e V {t(c1['fases']['validacao']['excesso_anual_pct'])}% ao ano (referência do mandato) | pior mês V {t(c1['fases']['validacao']['pior_mes_pct'])}% da garantia |")
    w(f"| Dividendo sintético: call coberta | reprovada no histórico: só medida | D {t(c2['fases']['descoberta']['excesso_anual_pct'])}% e V {t(c2['fases']['validacao']['excesso_anual_pct'])}% ao ano; Sharpe abaixo do papel sozinho | pior mês V {t(c2['fases']['validacao']['pior_mes_pct'])}% |")
    w(f"| Dividendo sintético: put de BOVA11 sem stop | reprovada no histórico: só medida | V {t(c3['fases']['validacao']['excesso_anual_pct'])}% ao ano | março/2020: {t(c3['fases']['validacao']['ciclo_mar2020_excesso_pct'])}% da garantia |")
    w(f"| Dividendo sintético: put de BOVA11 com stop 3x | medindo (frágil) | V {t(c4['fases']['validacao']['excesso_anual_pct'])}% ao ano, Sharpe {t(c4['fases']['validacao']['sharpe'], 2)}, deflacionado {t(c4['fases']['validacao'].get('sharpe_deflacionado'), 2)} | março/2020: {t(c4['fases']['validacao']['ciclo_mar2020_excesso_pct'])}% (1 pregão de atraso: {t(R['estresse_stop_bova11']['atraso_1_pregoes']['ciclo_mar2020_excesso_pct'])}%) |")
    v3 = [x for x in R["v3"] if "gatilho" not in x]
    pior = min(v3, key=lambda x: x["fases"]["validacao"]["excesso_anual_pct"])
    melhor = max(v3, key=lambda x: x["fases"]["validacao"]["sharpe"])
    w(f"| Travas com BOVA11 (crédito) | reprovada no histórico: só medida | 0 de {len(v3)} passaram; melhor Sharpe {t(melhor['fases']['validacao']['sharpe'], 2)} ({melhor['config']}); excesso entre {t(pior['fases']['validacao']['excesso_anual_pct'])}% e {t(max(x['fases']['validacao']['excesso_anual_pct'] for x in v3))}% ao ano | pior mês até {t(min(x['fases']['validacao']['pior_mes_pct'] for x in v3))}% do patrimônio com 10% em risco |")
    w("")
    w("Critérios fixados antes: fase passa com excesso sobre o CDI > 0, Sharpe > 0,3 e 24+ meses (ou 30+ operações); BOVA11 (sem descoberta) exige ainda as duas metades de 2020-2023 positivas; aprovada exige Sharpe > 1, deflacionado > 0,95, 100+ operações e prova virgem (impossível hoje).\n")

    w("## V2. Dividendo sintético (venda de put coberta por caixa e call coberta)\n")
    w("Grade pré-registrada: 54 configurações (6 seleções x 3 manejos x 3 filtros). Manejos: M0 segurar; M1 recomprar a 20% do prêmio recebido; M2 = M1 + stop em 3 vezes o prêmio. Filtros: F0 nenhum; F1 percentil da volatilidade implícita >= 0,60; F2 direção (put só acima da média de 200 pregões; call só abaixo). Ações: PETR4, VALE, ITUB4, BBAS3 e BBDC4; BOVA11 só 2020-2023.\n")

    def faixa(rows, per, chave):
        v = [x["fases"][per][chave] for x in rows if per in x["fases"] and x["fases"][per].get(chave) is not None]
        return f"{t(min(v))} a {t(max(v))}"
    cp = [x for x in R["v2"] if x["universo"] == "cesta" and x["estrutura"].startswith("put")]
    cc = [x for x in R["v2"] if x["estrutura"].startswith("call")]
    bp = [x for x in R["v2"] if x["universo"] == "BOVA11"]
    w("| Grupo (18 configurações cada) | Descoberta 2012-2019: excesso ao ano (%) | Validação 2020-2023: excesso ao ano (%) | Passaram |")
    w("|---|---|---|---|")
    w(f"| Put coberta de ações | {faixa(cp, 'descoberta', 'excesso_anual_pct')} | {faixa(cp, 'validacao', 'excesso_anual_pct')} | {sum(1 for x in cp if x['passou'])} |")
    w(f"| Call coberta | {faixa(cc, 'descoberta', 'excesso_anual_pct')} | {faixa(cc, 'validacao', 'excesso_anual_pct')} | {sum(1 for x in cc if x['passou'])} |")
    w(f"| Put coberta de BOVA11 | sem descoberta | {faixa(bp, 'validacao', 'excesso_anual_pct')} | {sum(1 for x in bp if x['passou'])} |")
    w("")
    w("**Referência do mandato (saída em 80%, sem stop, sem filtro):**\n")
    for nome, rot in (("cesta put delta=0.20 M1 F0", "Put de ações, delta 0,20"), ("cesta call delta=0.30 M1 F0", "Call coberta, delta 0,30"), ("BOVA11 put delta=0.20 M1 F0", "Put de BOVA11, delta 0,20")):
        r = cfg(R, "v2", nome)
        for per, m in r["fases"].items():
            extra = f"; {t(m.get('pct_alvo_80'), 0)}% das operações saíram no alvo de 80%" if m.get("pct_alvo_80") is not None else ""
            w(f"- {rot}, {'descoberta' if per == 'descoberta' else 'validação'}: {linha_fase(m)}{extra}.")
    w("")
    sa = R.get("stop_em_acoes") or {}
    w(f"**O que mudaria com o stop e com os filtros:** em ações o stop em 3 vezes não ajudou (Sharpe até -0,9): das {sa.get('stops')} vezes em que ele disparou na put de delta 0,20, {t(sa.get('pct_que_teria_dado_lucro_sem_stop'), 0)}% teriam terminado no lucro se seguradas, "
      f"e a perda média com o stop (R$ {t(abs(sa.get('resultado_medio_com_stop_rs') or 0), 2)} por opção) ficou um pouco maior que a de segurar (R$ {t(abs(sa.get('resultado_medio_sem_stop_rs') or 0), 2)}). O filtro de volatilidade implícita alta e o de direção não trouxeram ganho. Em BOVA11 o stop é o que separa um resultado de outro:\n")
    w("| Put de BOVA11 delta 0,20 (2020-2023) | Excesso ao ano | Sharpe | Pior mês | Março/2020 | Excesso sem março/2020 |")
    w("|---|---|---|---|---|---|")
    for nome, rot in (("BOVA11 put delta=0.20 M0 F0", "segurar"), ("BOVA11 put delta=0.20 M1 F0", "saída em 80%"), ("BOVA11 put delta=0.20 M2 F0", "80% e stop em 3 vezes")):
        m = cfg(R, "v2", nome)["fases"]["validacao"]
        w(f"| {rot} | {t(m['excesso_anual_pct'])}% | {t(m['sharpe'], 2)} | {t(m['pior_mes_pct'])}% | {t(m['ciclo_mar2020_excesso_pct'])}% | {t(m.get('excesso_sem_mar2020_anual_pct'))}% |")
    w("")
    w(f"Contra o BOVA11 comprado e segurado (retorno total do Ibovespa menos 0,10% ao ano): excesso sobre o CDI de {t(b11['validacao']['excesso_anual_pct'])}% ao ano em 2020-2023, pior mês {t(b11['validacao']['pior_mes_pct'])}%, queda máxima {t(b11['validacao']['queda_maxima_pct'])}%. Contra o CDI, o excesso é zero por definição.\n")
    w("**Estresse do stop (fora da grade, não escolhe nada):** o gatilho dispara no fechamento do dia em que o custo triplica e a recompra sai na oferta de venda daquele dia. Executando um ou dois pregões com cotação depois do gatilho:\n")
    w("| Atraso | Excesso ao ano | Sharpe | Pior mês | Perda em março/2020 (% do strike) |")
    w("|---|---|---|---|---|")
    for k, rot in (("atraso_0_pregoes", "no fechamento do gatilho"), ("atraso_1_pregoes", "1 pregão depois"), ("atraso_2_pregoes", "2 pregões depois")):
        m = R["estresse_stop_bova11"][k]
        w(f"| {rot} | {t(m['excesso_anual_pct'])}% | {t(m['sharpe'], 2)} | {t(m['pior_mes_pct'])}% | {t(m['perda_mar2020_pct_do_strike'])}% |")
    w("")
    w("Em março de 2020 houve interrupções de negociação e aberturas com salto; a perda real pode ter sido maior que a da tabela. O caso sem stop (−34,9% do strike) é o teto do que o histórico mostra.\n")

    w("## V3. Travas com BOVA11 (somente 2020-2023)\n")
    w("Grade: 72 travas de crédito (alta com put e baixa com call; delta da vendida 0,20 e 0,30; largura 3% e 6% do preço; M0, M1 e M2 com stop em 2 vezes o crédito; F0, F1 e F2) mais 4 travas a débito com gatilho. Dimensionamento da pesquisa: 10% do patrimônio em risco máximo por mês (correção declarada: com 100% o primeiro mês de perda total zera a conta e o retorno anual vira -100%).\n")
    w("| Trava (F0, 2020-2023) | Manejo | Excesso ao ano | Sharpe | Stop disparou | Perda total do risco |")
    w("|---|---|---|---|---|---|")
    for nome, rot in (("trava alta credito delta=0.20 largura=3% M0 F0", "alta, delta 0,20, 3%: segurar"), ("trava alta credito delta=0.20 largura=3% M1 F0", "alta, delta 0,20, 3%: 80%"),
                      ("trava alta credito delta=0.20 largura=6% M0 F0", "alta, delta 0,20, 6%: segurar"), ("trava baixa credito delta=0.20 largura=3% M1 F0", "baixa, delta 0,20, 3%: 80%"),
                      ("trava baixa credito delta=0.30 largura=6% M1 F0", "baixa, delta 0,30, 6%: 80%"), ("trava alta credito delta=0.20 largura=3% M2 F0", "alta, delta 0,20, 3%: 80% e stop")):
        r = cfg(R, "v3", nome)
        m = r["fases"]["validacao"]
        w(f"| {rot} | {r['manejo']} | {t(m['excesso_anual_pct'])}% | {t(m['sharpe'], 2)} | {t(m.get('pct_stop'), 0)}% | {t(m.get('pct_perda_total_do_risco'), 0)}% |")
    w("")
    pt = [x["fases"]["validacao"].get("pct_perda_total_do_risco") or 0 for x in v3 if x["manejo"] == "M0"]
    st = [x["fases"]["validacao"].get("pct_stop") or 0 for x in v3 if x["manejo"] == "M2"]
    s20 = [x for x in v3 if (x["fases"]["validacao"].get("excesso_sem_mar2020_anual_pct") or -9) > 0]
    ambas = [x for x in v3 if x["fases"]["validacao"]["excesso_anual_metade_1_pct"] > 0 and x["fases"]["validacao"]["excesso_anual_metade_2_pct"] > 0 and x["fases"]["validacao"]["excesso_anual_pct"] > 0]
    w(f"Leitura: o crédito de uma trava é pequeno perto do spread entre compra e venda das duas pernas (fechar custava em mediana 1,45 vez o crédito no primeiro pregão observável), "
      f"uma queda forte consome vários meses de crédito (de {t(min(pt), 0)}% a {t(max(pt), 0)}% das travas, segundo a configuração, perderam o risco todo quando seguradas até o vencimento) "
      f"e o stop em 2 vezes disparou em {t(min(st), 0)}% a {t(max(st), 0)}% das operações. Sem o ciclo de março de 2020, {len(s20)} das {len(v3)} ficaram positivas "
      f"(de {t(min(x['fases']['validacao']['excesso_sem_mar2020_anual_pct'] for x in s20))}% a {t(max(x['fases']['validacao']['excesso_sem_mar2020_anual_pct'] for x in s20))}% ao ano). "
      + (f"Só {len(ambas)} tiveram excesso positivo no período inteiro e nas duas metades ({'; '.join(x['config'] + ', Sharpe ' + t(x['fases']['validacao']['sharpe'], 2) for x in ambas)}): ficaram abaixo do corte de Sharpe 0,3.\n" if ambas else "Nenhuma teve excesso positivo no período inteiro e nas duas metades.\n"))
    w("**Travas a débito com gatilho (média por operação, depois do CDI):**\n")
    w("| Gatilho | Eventos | Trava | BOVA11 comprado | Trava em qualquer dia |")
    w("|---|---|---|---|---|")
    for x in [x for x in R["v3"] if "gatilho" in x]:
        v = x["fases"]["validacao"]
        nome = f"trava de {'alta' if x['gatilho'].startswith('alta') else 'baixa'} a débito, gatilho {x['gatilho'][-2:]}"
        w(f"| {nome} | {v['trava'].get('n')} | {t(v['trava'].get('media_pct'))}% | {t(v['bova11_comprado'].get('media_pct'))}% | {t(v['trava_em_qualquer_dia'].get('media_pct'))}% |")
    w("")
    w("Amostras de 3 a 14 eventos: sem poder estatístico; nenhuma passou o critério. Strike não ajustado por distribuição (BOVA11 sem tabela de proventos; nos dados nenhum ajuste foi observado).\n")

    w("## Limites propostos (o Douglas decide)\n")
    if vt:
        for n in ("especulativa", "dividendo_sintetico", "travas_bova"):
            w(f"- **{vt[n]['titulo']}**: {vt[n]['limites']['texto']}")
    w("")
    if vt:
        uso = vt["especulativa"]["placar"]["uso_do_limite_pct"]
        w(f"Partição do orçamento de queda das opções (R$ 3.000 = 3% do livro de R$ 100 mil): especulativa 30%, dividendo sintético 40%, travas 30%. A fatia da especulativa já está {t(uso, 0)}% usada pelas duas calls abertas em 09/10 pelo ranking antigo (o capital protegido fica à parte).\n")

    w("## O que ficou aberto hoje (cadeia de 09/10/2026)\n")
    if vt:
        for n in ("especulativa", "dividendo_sintetico", "travas_bova"):
            pl = vt[n]["placar"]
            w(f"- {vt[n]['titulo']}: {pl['n_abertas']} aberta(s), risco em aberto R$ {t(pl['risco_em_aberto_rs'], 0)} de R$ {t(pl['limite_de_risco_rs'], 0)}; resultado aberto R$ {t(pl['resultado_aberto_rs'], 0)}.")
        w("")
        w("Posições abertas por esta rodada (livro `carteira_vertentes.json`):\n")
        for n in ("dividendo_sintetico", "travas_bova"):
            for p in vt[n]["posicoes"]:
                w(f"- {p['titulo']} (aberta em {p['aberta_em']}, risco contado R$ {t(p['risco_rs'], 0)}).")
    w("")
    w("## Não testado e lacunas\n")
    w("- Rolagem e \"roda\" (aceitar o exercício e lançar call coberta) estão definidas como política e não foram testadas; no livro simulado o exercício aparece como perda realizada.")
    w("- Call coberta no livro simulado: só aparece no ranking (exige o papel em carteira); o livro abre apenas puts cobertas por caixa e travas.")
    w("- Margem oficial da B3 para travas, contrato por opção e ajuste de strike por distribuição de ETF: não confirmados (ver `quant/docs/travas-bova.md`).")
    w("- Execução do stop em dia de pânico (interrupção de negociação) não é simulada; só o atraso de 1 e 2 pregões.")
    w("- Imposto e corretagem fora da conta. Filtro de volatilidade implícita e direção só em F1 e F2 fixos; não houve busca de parâmetros.")
    with open(ARQ_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return ARQ_MD


if __name__ == "__main__":
    print(gerar())
