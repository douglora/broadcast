#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Roteiro por setor: o que um analista especialista olha em cada tipo de empresa, qual metodo
de avaliacao serve, se o caixa e previsivel (o ponto forte da mesa: TIR real contra a NTN-B),
as armadilhas contabeis do setor e o que procurar nos releases.

Nada aqui e numero: e o roteiro. Os numeros vem do balanco integral (CVM) e do release do RI.
"""

from __future__ import annotations

import re
import sqlite3

from . import base as B

# previsivel: True = receita regulada ou contratada (TIR real e o metodo central)
#             None = parcialmente previsivel (TIR real com ressalva)
#             False = ciclico (TIR por caixa normalizado e so referencia)
SETORES = {
    "eletrica_transmissao": {
        "nome": "Energia elétrica: transmissão", "previsivel": True, "damodaran": "Power",
        "metodo": "TIR real do fluxo até o FIM de cada concessão (sem perpetuidade), contra a NTN-B de prazo parecido",
        "indicadores": [
            ("RAP (receita anual permitida) do ciclo", "é a receita em caixa, corrigida por IPCA ou IGP-M; é ela, não a receita contábil, que paga o dividendo"),
            ("EBITDA regulatório x EBITDA IFRS", "o IFRS reconhece ativo de contrato (receita de construção e correção que não é caixa); o regulatório é o caixa"),
            ("Prazo médio até o fim das concessões", "depois do fim o fluxo acaba ou cai: define o valor terminal"),
            ("Degrau de RAP (concessões de categoria 2)", "em contratos antigos a RAP cai 50% a partir do 16o ano"),
            ("Dívida líquida / EBITDA regulatório", "alavancagem em cima do caixa de verdade"),
            ("Custo da dívida e indexador", "dívida em IPCA casa com a receita; em CDI vira risco de juro"),
            ("Projetos em construção: capex e RAP a entrar", "é o crescimento contratado; atraso de obra é o risco"),
            ("Payout sobre o lucro regulatório", "dividendo acima do caixa gerado é pago com dívida nova"),
        ],
        "termos": r"RAP|receita anual permitida|regulat[oó]ri|ativo de contrato|ciclo 20\d\d|revis[aã]o tarif|refor[cç]os|leil[aã]o|concess[aã]o.*(vencimento|t[eé]rmino)",
        "armadilhas": ["Lucro e EBITDA IFRS inflados por correção do ativo de contrato: não são caixa.",
                       "Depreciação quase zero (o ativo não é imobilizado): 'investimento = depreciação' não vale; o investimento passa pelo caixa operacional.",
                       "Perpetuidade superestima: concessão acaba. Informe 'fim' e 'residual' no caso da mesa."],
        "perguntas": ["Quanto da RAP atual termina ou cai pela metade nos próximos 10 anos?",
                      "O dividendo cabe no caixa regulatório ou depende de dívida nova?"],
    },
    "eletrica_distribuicao": {
        "nome": "Energia elétrica: distribuição", "previsivel": True, "damodaran": "Power",
        "metodo": "TIR real do caixa do dono; o valor vem da base de remuneração vezes o WACC regulatório (o retorno que a ANEEL autoriza) mais a eficiência sobre o regulador",
        "indicadores": [
            ("Base de remuneração líquida e data da próxima revisão tarifária", "é o capital que a ANEEL remunera; a revisão (a cada 4 ou 5 anos) reconhece o investimento feito"),
            ("WACC regulatório real", "retorno que a tarifa paga sobre a base de remuneração; compare com a NTN-B e com o custo da dívida"),
            ("EBITDA / EBITDA regulatório", "acima de 1 a empresa bate o regulador (custo e perda menores que os da tarifa)"),
            ("Perdas não técnicas x limite regulatório", "perda acima do limite não entra na tarifa: sai do lucro"),
            ("PMSO por consumidor x PMSO regulatório", "eficiência de custo"),
            ("Inadimplência (PDD / receita bruta)", "provisão acima da regulatória come margem"),
            ("DEC e FEC", "qualidade: fora do limite gera multa e compensação"),
            ("CVA e ativos setoriais", "dinheiro que a empresa adiantou e recebe na tarifa seguinte: distorce o caixa operacional do ano"),
            ("Crescimento do mercado faturado (GWh)", "volume; a parcela B cresce com ele entre revisões"),
            ("Vencimento da concessão e condições de renovação", "30 anos; renovação recente exigiu investimento e qualidade"),
        ],
        "termos": r"base de remunera|BRL|revis[aã]o tarif|reajuste tarif|parcela B|perdas|PMSO|DEC|FEC|CVA|inadimpl|PDD|WACC regulat|renova[cç][aã]o da concess",
        "armadilhas": ["Caixa operacional de um ano só engana por causa da CVA: use a mediana de vários anos.",
                       "Investimento acima da depreciação não é 'manutenção': vira base de remuneração e receita na próxima revisão.",
                       "Holding com minoritários nas distribuidoras: o EBITDA consolidado não é todo do acionista."],
        "perguntas": ["Quanto a base de remuneração sobe na próxima revisão e quando?", "A empresa ganha ou perde do regulador em perdas e PMSO?"],
    },
    "eletrica_geracao": {
        "nome": "Energia elétrica: geração", "previsivel": None, "damodaran": "Power",
        "metodo": "TIR real até o fim das concessões e contratos; a parte descontratada depende do preço de energia (cenários)",
        "indicadores": [
            ("Balanço energético: % contratado por ano e preço médio", "o contratado é previsível; o descontratado fica com o preço de mercado"),
            ("Preço de energia de longo prazo (curva e PLD)", "premissa mais sensível da parte descontratada"),
            ("GSF (risco hidrológico) e exposição", "em ano seco a hidrelétrica compra energia cara"),
            ("Prazo das concessões e dos PPAs", "fim de concessão = fim do fluxo (ou renovação com outorga)"),
            ("Curtailment (corte de geração) em eólica e solar", "energia que não pode ser entregue: corta receita sem cortar custo"),
            ("Fator de capacidade e disponibilidade", "eficiência operacional do parque"),
            ("Dívida líquida / EBITDA e custo da dívida", "projeto novo alavanca; conferir covenants"),
        ],
        "termos": r"contratad|descontratad|balan[cç]o energ[eé]tico|PLD|GSF|curtailment|pre[cç]o m[eé]dio|concess[aã]o|outorga|garantia f[ií]sica",
        "armadilhas": ["EBITDA de um ano bom de preço não é o normal: olhe o % contratado dos anos seguintes.",
                       "Renovação de concessão custa outorga: não é de graça."],
        "perguntas": ["Qual preço de energia o valor de mercado embute?", "Quanto do EBITDA acaba com as concessões até 2040?"],
    },
    "eletrica_integrada": {
        "nome": "Energia elétrica: integrada (geração, transmissão e distribuição)", "previsivel": True, "damodaran": "Power",
        "metodo": "TIR real do caixa do dono, com soma das partes: distribuição pela base de remuneração, transmissão pela receita anual permitida (RAP), geração pela energia contratada",
        "indicadores": [
            ("EBITDA por segmento (distribuição, geração, transmissão)", "cada parte tem risco e prazo diferentes"),
            ("Base de remuneração da distribuidora e data da revisão", "degrau de receita contratado"),
            ("% de energia contratada e preço médio", "previsibilidade da geração"),
            ("Prazo das concessões de geração", "o fluxo encolhe no fim (o Safra modela crescimento negativo no longo prazo)"),
            ("PMSO e programa de eficiência (PDV)", "após privatização, corte de custo é a alavanca principal"),
            ("Dívida líquida / EBITDA e política de dividendos", "espaço para pagar mais ou necessidade de reter"),
            ("Investimento x depreciação", "acima de 1 a empresa está crescendo a base, não só mantendo"),
        ],
        "termos": r"base de remunera|revis[aã]o tarif|contratad|PMSO|PDV|efici[eê]ncia|concess[aã]o|pol[ií]tica de dividendos|payout|capex|investimento",
        "armadilhas": ["Itens não recorrentes (provisões, ganhos de repactuação, venda de ativos) dentro do EBITDA publicado.",
                       "Imposto pago abaixo do lucro por crédito fiscal: o caixa de hoje não é o de sempre."],
        "perguntas": ["Qual EBITDA recorrente depois da última revisão tarifária?", "Quanto do investimento vira base remunerada?"],
    },
    "saneamento": {
        "nome": "Saneamento", "previsivel": True, "damodaran": "Utility (Water)",
        "metodo": "TIR real do caixa do dono; valor = base de ativos regulatória x WACC regulatório, com o plano de universalização até 2033",
        "indicadores": [
            ("Base de ativos regulatória (BAR ou RAB) e WACC regulatório", "capital remunerado pela tarifa"),
            ("Plano de investimento da universalização (2029 ou 2033)", "capex muito acima da depreciação: caixa livre negativo por anos, de propósito"),
            ("Reajuste e revisão tarifária (data e índice)", "repasse de inflação e do investimento"),
            ("Volume faturado de água e esgoto, e novas ligações", "crescimento físico"),
            ("Perdas de água (IPDT, perdas por ligação)", "eficiência; a tarifa reconhece só até o limite"),
            ("Inadimplência e PDD", "peso de órgãos públicos e baixa renda"),
            ("Dívida líquida / EBITDA e indexador da dívida", "plano de capex alavanca; dívida em CDI ou câmbio é risco"),
            ("Margem EBITDA ajustada (sem receita de construção)", "a receita de construção tem margem zero e incha a receita"),
        ],
        "termos": r"base de ativos|BAR|RAB|WACC|universaliza|reajuste tarif|revis[aã]o tarif|perdas|IPDT|liga[cç][oõ]es|volume faturado|capex|investimento",
        "armadilhas": ["Receita e custo de construção (ICPC 01) inflam a receita sem margem: use a receita operacional.",
                       "Ativo financeiro e ativo de contrato: parte do investimento não passa pela depreciação.",
                       "Caixa livre negativo no ciclo de universalização não é problema se o investimento entra na base remunerada."],
        "perguntas": ["O investimento está entrando na base a tempo de ser remunerado?", "A alavancagem aguenta o plano até 2033 sem aumento de capital?"],
    },
    "concessoes": {
        "nome": "Concessões de infraestrutura (rodovias, aeroportos, gás)", "previsivel": None, "damodaran": "Transportation",
        "metodo": "TIR real até o fim de cada concessão, com tráfego ligado ao PIB",
        "indicadores": [("Tráfego (veículos equivalentes) e tarifa média", "receita = volume x tarifa corrigida por contrato"),
                        ("Prazo remanescente por concessão", "valor terminal é zero no fim"),
                        ("Capex contratual a executar", "obrigação: sai do caixa do dono"),
                        ("Margem EBITDA ajustada (sem construção)", "eficiência"),
                        ("Dívida líquida / EBITDA e custo", "setor alavancado; juro alto pesa"),
                        ("Reequilibrios e aditivos", "mudam prazo e tarifa")],
        "termos": r"tr[aá]fego|ve[ií]culos equivalentes|tarifa|reequil[ií]brio|aditivo|prazo|capex|outorga",
        "armadilhas": ["Receita de construção sem margem.", "Tráfego cai em recessão: não é receita garantida."],
        "perguntas": ["Quanto do valor está em concessões que vencem em menos de 10 anos?"],
    },
    "telecom": {
        "nome": "Telecomunicacoes", "previsivel": None, "damodaran": "Telecom. Services",
        "metodo": "TIR real pelo caixa livre (EBITDA menos capex menos arrendamentos); Damodaran como segunda leitura",
        "indicadores": [("ARPU e base de clientes (pós, pré, fibra)", "receita = clientes x gasto médio"), ("Churn", "perda de clientes"),
                        ("Capex / receita", "intensidade de investimento"), ("EBITDA-AL (depois de arrendamentos)", "o IFRS 16 tira o aluguel de torres do EBITDA"),
                        ("Caixa livre e payout", "setor de retorno ao acionista"), ("Dívida líquida com arrendamentos / EBITDA", "alavancagem real")],
        "termos": r"ARPU|churn|fibra|FTTH|p[oó]s.pago|capex|arrendament|EBITDA.AL|remunera[cç][aã]o aos acionistas",
        "armadilhas": ["EBITDA sem descontar arrendamento (IFRS 16) superestima o caixa."], "perguntas": ["O capex/receita cai de forma sustentável?"],
    },
    "bancos": {
        "nome": "Bancos", "previsivel": None, "damodaran": "Bank (Money Center)",
        "metodo": "Retorno em excesso sobre o patrimônio (Damodaran): valor = patrimônio + valor presente de (ROE - custo do capital). Não existe EBITDA nem dívida líquida",
        "indicadores": [("ROE recorrente x custo do capital próprio", "só há valor acima do patrimônio se o ROE supera o custo"),
                        ("P/VP x ROE", "múltiplo justo = (ROE - g) / (Ke - g)"), ("Margem financeira (NIM) com clientes e com o mercado", "spread e tesouraria"),
                        ("Inadimplência acima de 90 dias e formação de NPL", "qualidade da carteira"), ("Custo do crédito (PDD / carteira) e cobertura", "provisão"),
                        ("Índice de eficiência", "custo / receita"), ("Índice de Basileia e capital principal (CET1)", "espaço para crescer e pagar dividendo"),
                        ("Crescimento e mix da carteira", "linhas de risco maior pagam mais e perdem mais"), ("Payout e JCP", "retorno ao acionista")],
        "termos": r"ROE|ROAE|margem financeira|NIM|inadimpl|NPL|custo do cr[eé]dito|PDD|[ií]ndice de efici|Basileia|CET1|carteira de cr[eé]dito|guidance|JCP|payout",
        "armadilhas": ["Lucro de um trimestre com reversão de provisão ou ganho de tesouraria não é recorrente.",
                       "Resolução 4.966 mudou a provisão em 2025: séries antes e depois não são comparáveis sem ajuste."],
        "perguntas": ["O ROE de hoje é sustentável no ciclo de crédito?", "O preço embute ROE acima ou abaixo do guidance?"],
    },
    "seguros": {
        "nome": "Seguros e previdência", "previsivel": None, "damodaran": "Insurance (General)",
        "metodo": "Retorno em excesso sobre o patrimônio; dividendos descontados quando o payout é alto e estável",
        "indicadores": [("Sinistralidade e índice combinado", "abaixo de 100% a operação da lucro antes do financeiro"), ("Resultado financeiro e sensibilidade a Selic", "boa parte do lucro vem do float"),
                        ("Prêmios emitidos e ganhos", "crescimento"), ("ROE e payout", "setor leve de capital"), ("Índice de solvência", "capital regulatório")],
        "termos": r"sinistralidade|[ií]ndice combinado|pr[eê]mios|resultado financeiro|solv[eê]ncia|payout|guidance", "armadilhas": ["Selic alta infla o resultado financeiro: normalize."],
        "perguntas": ["Quanto do lucro some se a Selic cair 3 pontos?"],
    },
    "varejo": {
        "nome": "Varejo e consumo", "previsivel": False, "damodaran": "Retail (General)",
        "metodo": "Damodaran (FCFF) com margem normalizada; TIR por caixa é só referência. Juro alto pesa duas vezes: na dívida e no consumo",
        "indicadores": [("Vendas mesmas lojas (SSS)", "crescimento orgânico"), ("Margem bruta e margem EBITDA sem IFRS 16", "o aluguel sai do EBITDA no IFRS 16"),
                        ("Capital de giro: prazos de estoque, fornecedor e recebimento", "varejo vive de giro; antecipação de recebíveis é dívida disfarçada"),
                        ("Dívida líquida com arrendamento e recebíveis antecipados / EBITDA", "alavancagem real"), ("Despesa financeira / EBIT", "quanto do operacional o juro come"),
                        ("ROIC x custo de capital", "expansão só cria valor acima do custo"), ("Inadimplência do braço financeiro", "risco de crédito próprio")],
        "termos": r"mesmas lojas|SSS|margem bruta|capital de giro|estoque|fornecedor|antecipa[cç][aã]o|receb[ií]veis|arrendament|inaugura|GMV",
        "armadilhas": ["Recebíveis antecipados e risco sacado fora da dívida.", "EBITDA com IFRS 16 esconde o aluguel."], "perguntas": ["A margem aguenta o custo do dinheiro de hoje?"],
    },
    "construtoras": {
        "nome": "Construção civil e incorporação", "previsivel": False, "damodaran": "Homebuilding",
        "metodo": "P/VP x ROE e margem a apropriar; fluxo de caixa por safra de lançamentos. TIR por EBITDA não se aplica bem",
        "indicadores": [("Lançamentos e vendas líquidas (VGV, % da empresa)", "o resultado de amanhã"), ("VSO (velocidade de vendas)", "demanda"),
                        ("Margem bruta ajustada e margem REF (a apropriar)", "rentabilidade já vendida que ainda vai para a DRE"), ("Geração (queima) de caixa", "o lucro contábil (POC) não é caixa"),
                        ("Dívida líquida / patrimônio", "régua de alavancagem do setor"), ("Estoque pronto e distratos", "risco de ciclo"),
                        ("Banco de terrenos (landbank) e permuta", "anos de lançamento garantidos"), ("ROE", "comparável entre pares"), ("Exposição ao MCMV e ao teto do programa", "segmento de baixa renda depende do FGTS")],
        "termos": r"lan[cç]amentos|vendas l[ií]quidas|VSO|VGV|margem (bruta|REF)|resultado a apropriar|gera[cç][aã]o de caixa|queima de caixa|distratos|landbank|MCMV|repasse",
        "armadilhas": ["Lucro pelo POC antecipa receita de obra não entregue.", "Cessão de recebíveis melhora o caixa de um trimestre so."], "perguntas": ["A geração de caixa acompanha o lucro?"],
    },
    "commodities": {
        "nome": "Commodities (mineração, siderurgia, petróleo, celulose, proteínas)", "previsivel": False, "damodaran": "Metals & Mining",
        "metodo": "Damodaran com preço de commodity NORMALIZADO (média do ciclo) e cenários; múltiplo no meio do ciclo. TIR sobre o lucro do pico engana",
        "indicadores": [("Custo caixa por unidade (C1, lifting cost, custo por tonelada)", "posição na curva de custo: quem sobrevive no fundo do ciclo"),
                        ("Preço realizado x preço de referência", "prêmio ou desconto de qualidade"), ("Volume de produção e guidance", "crescimento físico"),
                        ("Capex de manutenção x de expansão", "caixa livre de verdade"), ("Dívida líquida / EBITDA no meio do ciclo", "alavancagem com preço normal"),
                        ("Câmbio", "receita em dólar, custo em real"), ("Vida útil das reservas", "valor terminal finito")],
        "termos": r"custo caixa|C1|lifting|pre[cç]o realizado|guidance|produ[cç][aã]o|capex de manuten|break.?even|reservas",
        "armadilhas": ["Margem de pico tratada como normal.", "Dividendo extraordinário de ano bom projetado para sempre."], "perguntas": ["Qual preço da commodity o valor de mercado embute?"],
    },
    "shoppings": {
        "nome": "Shoppings e propriedades", "previsivel": None, "damodaran": "R.E.I.T.",
        "metodo": "TIR real pelo FFO (lucro caixa) e cap rate implícito contra a NTN-B",
        "indicadores": [("NOI e margem NOI", "resultado operacional dos imóveis"), ("FFO e FFO por ação", "lucro caixa"), ("Vendas e aluguel mesmas lojas (SSS, SSR)", "o aluguel segue a venda do lojista com defasagem"),
                        ("Taxa de ocupação e inadimplência", "saúde do portfólio"), ("Custo de ocupação", "quanto o lojista aguenta de aluguel"), ("Cap rate implícito", "NOI / valor da firma, contra a NTN-B"),
                        ("Dívida líquida / EBITDA", "alavancagem")],
        "termos": r"NOI|FFO|SSS|SSR|ocupa[cç][aã]o|inadimpl|custo de ocupa|cap rate|ABL", "armadilhas": ["Linearização de aluguel e ganho de valor justo não são caixa."], "perguntas": ["O cap rate implícito paga prêmio sobre a NTN-B?"],
    },
    "geral": {
        "nome": "Empresa operacional (sem roteiro de setor próprio)", "previsivel": False, "damodaran": "Total Market (without financials)",
        "metodo": "Damodaran (FCFF) como leitura central; TIR por caixa como referência",
        "indicadores": [("Crescimento de receita orgânico", "volume x preço"), ("Margens bruta, EBITDA e líquida, e a trajetória", "poder de preço e eficiência"),
                        ("ROIC x custo de capital", "criação de valor"), ("Conversão de caixa (caixa operacional / EBITDA)", "qualidade do lucro"),
                        ("Dívida líquida / EBITDA, custo e moeda da dívida", "o custo do dinheiro no Brasil"), ("Capital de giro", "quanto o crescimento consome")],
        "termos": r"guidance|margem|capex|capital de giro|d[ií]vida|alavancagem|investimento", "armadilhas": ["EBITDA 'ajustado' que tira despesa recorrente."], "perguntas": ["O retorno sobre o capital paga o custo do dinheiro?"],
    },
}

# raiz do ticker -> setor (o que a mesa mais acompanha; o resto cai na classificacao da B3)
RAIZES = {
    "eletrica_transmissao": "TAEE ISAE TRPL ALUP",
    "eletrica_distribuicao": "EQTL ENGI LIGT COCE CEEB ENMT EKTR REDE CEBR",
    "eletrica_geracao": "EGIE AURE ENEV AESB SRNA RNEW EMAE GEPA CESP",
    "eletrica_integrada": "CPLE CMIG AXIA ELET NEOE CPFE CLSC",
    "saneamento": "SBSP SAPR CSMG ORVR AMBP CASN",
    "concessoes": "MOTV CCRO ECOR TPIS CGAS RAIL PORT STBP",
    "telecom": "VIVT TIMS OIBR FIQE BRST DESK",
    "bancos": "ITUB BBDC BBAS SANB BPAC ABCB BMGB BRSR BPAN INBR ROXO NUBR BMEB PINE BAZA BNBR",
    "seguros": "BBSE CXSE PSSA IRBR WIZC",
    "varejo": "MGLU LREN ASAI CRFB PCAR AMER BHIA PETZ SOMA AZZA ARZZ CEAB GUAR VIVA NATU NTCO RADL PGMN SBFG GMAT SMFT VULC ALPA GRND",
    "construtoras": "CYRE CURY DIRR MRVE TEND EZTC EVEN PLPL JHSF MDNE LAVV TRIS HBOR GFSA MELK MTRE",
    "commodities": "VALE GGBR GOAU CSNA USIM CMIN PETR PRIO BRAV RECV SUZB KLBN JBSS BEEF MRFG BRFS SLCE CBAV UNIP BRKM",
    "shoppings": "MULT IGTI ALOS SYNE LOGG HBRE",
}
_POR_RAIZ = {r: s for s, rs in RAIZES.items() for r in rs.split()}

_B3 = (  # (regex sobre "setor | subsetor" da B3, setor do roteiro)
    (r"transmiss", "eletrica_transmissao"), (r"energia el[eé]trica", "eletrica_integrada"), (r"saneamento|[aá]gua", "saneamento"),
    (r"rodovia|aeroport|g[aá]s|ferrovi|portu", "concessoes"), (r"telecom", "telecom"), (r"banco|intermedi[aá]rios financeiros", "bancos"),
    (r"segur|previd", "seguros"), (r"com[eé]rcio|varej|tecidos|vestu[aá]rio|consumo", "varejo"), (r"constru[cç][aã]o civil|incorpora", "construtoras"),
    (r"minera|siderur|petr[oó]leo|papel|celulose|qu[ií]mic|agropecu|carnes", "commodities"), (r"explora[cç][aã]o de im[oó]veis|shopping", "shoppings"),
)


def classificacao_b3(ticker):
    """(setor, subsetor) da B3 pelo banco do terminal, somente leitura. None se nao houver."""
    try:
        con = sqlite3.connect(f"file:{B.TERMINAL.parent / 'banco' / 'terminal.sqlite'}?mode=ro", uri=True)
        r = con.execute("select setor, subsetor from tir where ticker = ? order by data desc limit 1", (ticker.upper(),)).fetchone()
        con.close()
        return r
    except sqlite3.Error:
        return None


def identificar(ticker, d=None):
    """Roteiro do setor para o ticker: {'id', 'de_onde', + campos do setor}."""
    tk = ticker.upper().replace(".SA", "")
    raiz = tk[:4]
    sid, de = _POR_RAIZ.get(raiz), "lista da mesa"
    if not sid:
        b3 = classificacao_b3(tk)
        txt = " | ".join(x for x in (b3 or ()) if x)
        if not txt and d:
            info = (d.get("yahoo") or {}).get("info") or {}
            txt = " | ".join(str(info.get(k) or "") for k in ("sector", "industry"))
        if d and (d.get("cvm_demonstracoes") or {}).get("plano_de_contas") == "instituicao_financeira":
            sid, de = "bancos", "plano de contas de instituição financeira (CVM)"
        for rx, s in _B3:
            if sid:
                break
            if txt and re.search(rx, txt, re.I):
                sid, de = s, f"classificação da B3 ({txt})"
        if not sid:
            sid, de = "geral", "sem roteiro próprio" + (f" ({txt})" if txt else "")
    return dict(SETORES[sid], id=sid, de_onde=de)


def texto(s):
    L = [f"ROTEIRO DO SETOR  {s['nome']}  ({s['de_onde']})",
         "  Caixa previsível: " + {True: "SIM (ponto forte da mesa: TIR real contra a NTN-B)", None: "EM PARTE (TIR real com ressalva)",
                                   False: "NÃO (cíclico: TIR por caixa é só referência)"}[s["previsivel"]],
         f"  Método: {s['metodo']}", "  O que o especialista olha:"]
    L += [f"   {i + 1}. {n}: {p}" for i, (n, p) in enumerate(s["indicadores"])]
    L += ["  Armadilhas:"] + [f"   - {a}" for a in s["armadilhas"]]
    L += ["  Perguntas que a análise tem de responder:"] + [f"   - {a}" for a in s["perguntas"]]
    L.append(f"  Procurar nos releases (mesa.py linha TICKER \"...\"): {s['termos']}")
    return "\n".join(L)
