#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relatorio do analista de ativos em HTML (e PDF), no padrao visual aprovado pelo Douglas em
11/11/2026: azul-marinho, Montserrat embutida, fundo branco, "Figura N." com a fonte embaixo,
caixa azul-clara com o numero. Duas versoes do MESMO calculo:

  resumido   o que decide: momento economico, quanto a acao entrega acima da inflacao, o que o
             preco exige, preco justo por lente e a ponte com o Safra. 4 paginas, 4 figuras.
  profundo   tudo o que sustenta: cascata do caixa, fluxo ano a ano, historia, estresse,
             sensibilidades, passo a passo de Damodaran, roteiro do setor e o livro de premissas.

Dinamico: cada secao so entra quando o dado existe e quando faz sentido para o setor (banco nao
tem TIR por caixa; ciclico leva o aviso de que a TIR e referencia). O texto do analista (tese, o
que a gestao disse e entregou, riscos) entra por um arquivo texto.json por ativo; sem ele, o
relatorio sai so com o que e conta, e diz que a leitura dos releases nao foi anexada.
"""

from __future__ import annotations

import base64
import datetime as dt
import html
import json
import re
import subprocess
from pathlib import Path

from . import base as B
from . import damodaran as D
from . import graficos as G
from . import macro as MAC
from . import safra as F
from . import setores as S
from . import tir_real as T

ESTILO = Path(__file__).resolve().parent / "estilo"
SAIDA = B.CACHE / "relatorios"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
E = lambda s: html.escape(str(s), quote=False)
FINANCEIRAS = ("bancos", "seguros")
CAMPOS_TEXTO = ("titulo", "em_uma_frase", "tese", "gestao", "setor", "noticias", "gatilhos", "riscos", "mudaria", "aprofundar")

TERMOS = {
    "TIR real": "Taxa interna de retorno acima da inflação: quanto o caixa que sobra para o acionista rende ao ano, a preço de hoje, em reais de hoje.",
    "NTN-B 2035": "Título do Tesouro que paga IPCA mais juro fixo até 2035. É a régua: o que se ganha sem risco de empresa.",
    "Prêmio": "Quanto a ação rende a mais que a NTN-B, em pontos percentuais (pp).",
    "EBITDA": "Lucro antes de juros, impostos, depreciação e amortização: o resultado da operação.",
    "Caixa do dono": "O que sobra para o acionista depois de operar, investir e pagar o custo real da dívida.",
    "Custo real da dívida": "Juro da dívida descontada a inflação. A parte do juro que só repõe a inflação é rolada, não é custo.",
    "Ke": "Custo do capital próprio: o retorno mínimo que o acionista exige.",
    "WACC": "Custo médio de capital: média do custo do capital próprio e da dívida, pelo peso de cada um.",
    "ROIC": "Retorno sobre o capital investido: lucro operacional depois do imposto dividido por dívida líquida mais patrimônio.",
    "ROE": "Retorno sobre o patrimônio: lucro dividido pelo patrimônio líquido.",
    "Beta": "Quanto a ação costuma oscilar em relação ao mercado. Damodaran publica o beta médio de cada setor.",
    "FCFF": "Fluxo de caixa da firma: o caixa da operação antes de pagar dívida e acionista.",
    "Focus": "Pesquisa semanal do Banco Central com as projeções de bancos e gestoras para inflação, Selic e PIB.",
    "P/VP": "Preço da ação dividido pelo patrimônio por ação.",
    "pp": "Ponto percentual: a diferença entre duas taxas (de 5% para 7% são 2 pp).",
    "RAP": "Receita anual permitida: o que a transmissora recebe por ano pela linha disponível, corrigida por inflação.",
    "PMSO": "Pessoal, material, serviços e outros: os custos que a gestão controla.",
    "CDI": "Taxa dos empréstimos de um dia entre bancos; anda junto com a Selic e corrige a maior parte da dívida das empresas.",
}


def _ipca(v, casas=1):
    return "não fecha" if v is None else f"IPCA + {B.br(v * 100, casas)}%"


def _p100(v):
    return B.br(v * 100, 1) + "%"


def pasta(ticker):
    p = SAIDA / ticker.upper()
    p.mkdir(parents=True, exist_ok=True)
    return p


def modelo_texto(ticker):
    """Cria (se nao existir) o texto.json que o analista preenche antes de montar o relatorio."""
    arq = pasta(ticker) / "texto.json"
    if not arq.exists():
        B.gravar_json(arq, {
            "_leia": "Texto do analista para o relatorio. Apague o que nao for usar. Todo item de 'gestao', 'setor' e 'noticias' "
                     "precisa de 'fonte' (documento, pagina, data): item sem fonte derruba a montagem.",
            "titulo": "", "em_uma_frase": "", "tese": [],
            "gestao": [{"tema": "", "disse": "", "entregou": "", "fonte": ""}],
            "setor": [{"indicador": "", "valor": "", "leitura": "", "fonte": ""}],
            "noticias": [{"data": "", "titulo": "", "leitura": "", "fonte": ""}],
            "gatilhos": [], "riscos": [], "mudaria": [], "aprofundar": []})
    return arq


def ler_texto(ticker, caminho=None):
    arq = Path(caminho) if caminho else pasta(ticker) / "texto.json"
    d = B.ler_json(arq)
    if not d:
        return {}
    out = {}
    for k in CAMPOS_TEXTO:
        v = d.get(k)
        if isinstance(v, list):
            v = [x for x in v if (x if isinstance(x, str) else any(str(y).strip() for y in x.values()))]
        if v:
            out[k] = v
    for k in ("gestao", "setor", "noticias"):
        for x in out.get(k, []):
            if not str(x.get("fonte") or "").strip():
                raise B.SemDado(f"{arq.name}: item de '{k}' sem fonte ({str(x)[:70]}). Nada entra no relatório sem documento e data.")
    return out


def coletar(ticker, preco=None):
    """Roda tudo uma vez e devolve o contexto do relatorio. Bloco que falha vira lacuna declarada."""
    tk = ticker.upper()
    d = B.ativo(tk)
    s = S.identificar(tk, d)
    c = {"ticker": tk, "nome": (d.get("identificacao") or {}).get("nome") or tk, "setor": s, "financeira": s["id"] in FINANCEIRAS,
         "lacunas": [], "tir": None, "dam": None, "ins": None, "mac": MAC.carregar()}
    if c["financeira"]:
        try:
            c["dam"] = D.calcular_financeira(tk, industria=s["damodaran"], preco=preco)
        except B.SemDado as e:
            c["lacunas"].append(f"Preço justo de Damodaran: {e}")
    else:
        try:
            c["ins"] = T.insumos(tk, preco=preco)
            c["tir"] = T.calcular(tk, ins=c["ins"], previsivel=s["previsivel"])
        except B.SemDado as e:
            c["lacunas"].append(f"TIR real: {e}")
        if c["ins"]:
            try:
                c["dam"] = D.calcular(tk, ins=c["ins"], industria=s["damodaran"])
            except B.SemDado as e:
                c["lacunas"].append(f"Preço justo de Damodaran: {e}")
    ref = c["tir"] or c["dam"]
    if not ref:
        raise B.SemDado(f"{tk}: nem a TIR real nem o preço justo fecharam. " + " | ".join(c["lacunas"]))
    c["preco"], c["data_preco"] = ref["preco"], ref["data_preco"]
    c["safra"] = F.carregar(tk, c["preco"], c["data_preco"], c["mac"]["ipca_longo"])
    c["ponte"] = F.ponte(c["safra"], c["tir"], c["dam"], s)
    return c


# ------------------------------------------------------------------ pecas de HTML
class _Fig:
    def __init__(self):
        self.n = 0

    def __call__(self, titulo, svg, fonte, leitura=""):
        self.n += 1
        return (f'<figure><figcaption>Figura {self.n}. {E(titulo)}</figcaption>{svg}</figure>'
                f'<div class="fonte">Fonte: {E(fonte)} · elaboração própria</div>' + (f'<p class="leitura">{leitura}</p>' if leitura else ""))


def _tab(cab, linhas, num=(), nota="", destaque=()):
    th = "".join(f'<th{" class=num" if i in num else ""}>{c}</th>' for i, c in enumerate(cab))
    trs = []
    for k, l in enumerate(linhas):
        tds = "".join(f'<td{" class=num" if i in num else ""}>{v}</td>' for i, v in enumerate(l))
        trs.append(f'<tr{" class=eu" if k in destaque else ""}>{tds}</tr>')
    # tabela pequena (ate 12 linhas de uma ou duas linhas de texto) nao se divide entre duas paginas
    curta = 0 < len(linhas) <= 12 and sum(len(re.sub(r"<[^>]+>", "", str(v))) for l in linhas for v in l) / len(linhas) < 110
    return (f'<div class="tab{" curta" if curta else ""}"><table><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table></div>'
            + (f'<div class="nota-tab">{nota}</div>' if nota else ""))


def _kpis(itens):
    return '<div class="kpis">' + "".join(f'<div class="kpi"><div class="r">{E(r)}</div><div class="v">{E(v)}</div><div class="n">{E(n)}</div></div>'
                                          for r, v, n in itens) + "</div>"


def _lista(itens):
    return "<ul>" + "".join(f"<li>{E(x)}</li>" for x in itens) + "</ul>" if itens else ""


def _contra(premio):
    """'2,1 pp abaixo' / '1,3 pp acima', com a cor do sinal."""
    return _sinal(premio, f"{B.br(abs(premio) * 100, 1)} pp {'acima' if premio >= 0 else 'abaixo'}")


def _valor_livro(i):
    """Valor de uma premissa do livro, com a unidade no lugar certo."""
    v, un = i.valor, (i.unidade or "").strip()
    if isinstance(v, (list, tuple)):
        return ", ".join(B.br(x, 0) if abs(x) > 5 else B.pct(x) for x in v) + (f" {un}" if un else "")
    if not isinstance(v, (int, float)):
        return f"{v} {un}".strip()
    if un.startswith("a.a."):
        return B.pct(v, 2) + " " + un
    if un.startswith("do "):
        return B.pct(v, 1) + " " + un
    if un == "x":
        return B.br(v, 2) + "x"
    if un.startswith("R$"):
        return "R$ " + B.br(v, 2 if abs(v) < 100 else 0) + un[2:]
    return (B.br(v, 2 if abs(v) < 100 else 0) + " " + un).strip()


def _sinal(v, txt):
    return f'<span class="{"pos" if v >= 0 else "neg"}">{txt}</span>'


def frase(c):
    """Em uma frase, so com a conta (o analista pode trocar pelo texto.json)."""
    tk, o, dm = c["ticker"], c["tir"], c["dam"]
    if o:
        base = o["central"]
        r = o["reversa"][0]
        if base["tir"] is None:
            return f"A {B.reais(o['preco'])}, o caixa do dono de {tk} não fecha uma TIR real positiva com o balanço de hoje: o preço depende de projeção, não do que já existe."
        exige = (f"crescer {B.pct(r['crescimento'])} ao ano acima da inflação por 10 anos" if r.get("crescimento") is not None else "um caixa que o balanço não mostra")
        lado = "acima" if base["premio"] >= 0 else "abaixo"
        return (f"A {B.reais(o['preco'])}, {tk} entrega {_ipca(base['tir'])} ao ano com o caixa de hoje ({base['nome'].lower()}), "
                f"{B.br(abs(base['premio']) * 100, 1)} pp {lado} da NTN-B 2035 ({_ipca(o['ntnb_2035'], 2)}); para pagar o prêmio de "
                f"{B.br(o['premio_exigido'] * 100, 1)} pp que a mesa exige neste terreno {o['regime']}, o caixa do dono precisa {exige}"
                + (f", ou o preço ser {B.reais(r['preco'])}." if r.get("preco") else "."))
    return (f"A {B.reais(dm['preco'])}, {tk} negocia a {B.br(dm['p_vp'], 2)}x o patrimônio com ROE de {B.pct(dm['roe'])}; o preço embute ROE de "
            f"{B.pct(dm['roe_implicito']) if dm.get('roe_implicito') is not None else 'n/d'} para sempre, contra custo do capital de {B.pct(dm['custo']['ke_nominal'])} "
            f"(método de Damodaran, que dá preço justo de {B.reais(dm['preco_justo'])} se o retorno em excesso sumir em 10 anos).")


# ------------------------------------------------------------------ secoes
def _sec_macro(c, fig, profundo):
    m, r = c["mac"], c["mac"]["regime"]
    prox = m["revisao_4s"]["ano"]
    H = ['<h2>Momento econômico: o terreno do valuation</h2>',
         f'<div class="frase">Terreno para a bolsa: <b>{E(r["nome"].upper())}</b>. Prêmio mínimo que a mesa exige sobre a NTN-B 2035 neste regime: '
         f'<b>{B.br(r["premio_exigido"] * 100, 1)} pp</b>.</div>']
    linhas = []
    for ind, rot, un in (("IPCA", "Inflação (IPCA)", "%"), ("Selic", "Selic no fim do ano", "% a.a."), ("PIB Total", "PIB", "%")):
        x = (m["focus"].get(ind) or {}).get(prox) or {}
        if x.get("mediana") is None:
            continue
        rv = None if x.get("ha_4_sem") is None else x["mediana"] - x["ha_4_sem"]
        linhas.append([f"{rot} {prox}", B.br(x["mediana"], 2) + un, "—" if x.get("ha_4_sem") is None else B.br(x["ha_4_sem"], 2) + un,
                       "—" if rv is None else B.br(rv, 2, True) + " pp"])
    # motivos do regime: a revisao do Focus ja esta na tabela logo abaixo, com mais detalhe; nao repete
    motivos = [x for x in r["motivos"] if not (linhas and x.startswith("Focus revisou"))]
    if motivos:
        H.append(_lista(motivos))
    if linhas:
        H.append(_tab(["Focus", "Hoje", "Há 4 semanas", "Revisão"], linhas, num=(1, 2, 3),
                      nota=f"Boletim Focus de {B.data_br(m['focus_data'])} (mediana do mercado). Selic hoje: {B.br(m['selic'], 2)}% · IPCA 12 meses: {B.br(m['ipca_12m'], 2)}%."))
    if m.get("ntnb_2035_hist"):
        refs = [(m["ntnb_2035_media"] * 100, "média", "mut")] if m.get("ntnb_2035_media") else []
        pc = f" Está no percentil {B.br(m['ntnb_2035_percentil'] * 100, 0)} da própria história desde {m['ntnb_2035_desde'][:4]}." if m.get("ntnb_2035_percentil") is not None else ""
        ult = m.get("ntnb_2035_hist_ult") or {}
        serie = (f" (no gráfico, a taxa de resgate do Tesouro Direto, alguns centésimos acima: {B.br(ult['taxa'] * 100, 2)}% em {B.data_br(ult['data'])})" if ult else "")
        H.append(fig("NTN-B 2035: o juro real que concorre com a ação (% ao ano acima do IPCA)",
                     G.linha_tempo(m["ntnb_2035_hist"], lambda v: B.br(v, 2 if abs(v) < 20 else 1) + "%", refs, "Taxa da NTN-B 2035 no tempo",
                                   fmt_eixo=lambda v: B.br(v, 1) + "%"),
                     f"Tesouro Direto ({m.get('ntnb_2035_hist_nome') or 'série'}) e ANBIMA (régua)",
                     f"A régua da conta é a taxa indicativa da ANBIMA: a NTN-B 2035 paga <b>{_ipca(m['ntnb_2035'], 2)}</b> em {B.data_br(m['ntnb_data'])}{serie}.{pc} "
                     "Quanto mais alto o juro real, maior o retorno que a ação precisa entregar e menor o preço justo de qualquer fluxo de caixa."))
    if profundo:
        H.append(_tab(["Indicador", "Valor", "O que diz"], [
            ["Juro real de 12 meses à frente", B.pct(m["juro_real_ex_ante"]), "Selic esperada menos inflação esperada: o custo de carregar dívida"],
            ["DI de 10 anos", B.pct(m["di_10a"], 2), "o juro nominal longo que o mercado negocia"],
            ["Inflação implícita de 10 anos", B.pct(m["implicita_10a"], 2), f"DI contra NTN-B; o Focus longo vê {B.pct(m['ipca_longo'], 2)}"],
            ["TIR real mediana da bolsa", B.pct(m["tir_bolsa_mediana"]) if m.get("tir_bolsa_mediana") else "n/d",
             "método do Safra replicado no terminal: o prêmio que a bolsa inteira oferece"]], num=(1,)))
    return "".join(H)


def _sec_tir(c, fig, profundo):
    o, ins, po = c["tir"], c["ins"], c["ponte"]
    ntnb, exige = o["ntnb_2035"], o["premio_exigido"]
    base = o["central"]
    H = ['<h2>Quanto a ação entrega acima da inflação</h2>',
         f'<p>TIR real implícita no preço: o caixa que sobra para o acionista em 10 anos, em reais de hoje, contra o valor de mercado de '
         f'{B.mi(o["valor_mercado"])}. Método da mesa, inspirado nas falas públicas de Octavio Magalhães: retorno real, régua na NTN-B, '
         f'nenhuma melhora que o balanço ainda não mostra. {E(o["previsibilidade"]["frase"])}</p>']
    cx = [f'<div><b>{E(x["nome"])}:</b> {_ipca(x["tir"])} ao ano' + (f' ({_contra(x["premio"])} da NTN-B 2035)' if x["premio"] is not None else "") + "</div>"
          for x in o["cenarios"]]
    cx.append(f'<div><b>Régua:</b> NTN-B 2035 a {_ipca(ntnb, 2)}; a mesa exige {B.br(exige * 100, 1)} pp de prêmio, ou seja, {_ipca(ntnb + exige)}.</div>')
    H.append('<div class="caixa">' + "".join(cx) + "</div>")
    itens = [{"rotulo": "Mesa: " + x["nome"].lower(), "valor": x["tir"], "cor": "acc", "forte": x is base} for x in o["cenarios"]]
    for nome, v, _ in po["retornos"]:
        if nome.startswith("Safra"):
            itens.append({"rotulo": "Safra: TIR real ao preço de hoje", "valor": v, "cor": "azul"})
        elif nome.startswith("Terminal: TIR pelo lucro (") :
            itens.append({"rotulo": "Terminal: pelo lucro projetado (método do Safra)", "valor": v, "cor": "claro"})
    itens.append({"rotulo": "O que a mesa exige: NTN-B + prêmio", "valor": ntnb + exige, "cor": "cinza"})
    H.append(fig("Retorno real ao preço de hoje, lente por lente (% ao ano acima do IPCA)",
                 G.barras_h(itens, _p100, ntnb, "NTN-B 2035", "Retorno real por lente contra a NTN-B 2035"),
                 "CVM (DFP e ITR), ANBIMA, Safra e terminal",
                 "A linha tracejada é o que o Tesouro paga sem risco de empresa. Barra à esquerda dela: a ação rende menos que o título."))
    l1 = base["fluxo"]["linhas"][0]
    passos = [{"rotulo": "EBITDA", "valor": l1["ebitda"], "total": True},
              {"rotulo": "Imposto, giro e itens sem caixa", "valor": l1["caixa_oper"] - l1["ebitda"]},
              {"rotulo": "Investimento", "valor": -l1["investimento"]},
              {"rotulo": "Custo real da dívida", "valor": -l1["custo_divida"]}]
    if abs(l1["divida_nova"]) > 0.005 * l1["ebitda"]:
        passos.append({"rotulo": "Dívida nova", "valor": l1["divida_nova"]})
    if l1["minoritarios"] > 0.005 * l1["ebitda"]:
        passos.append({"rotulo": "Sócios minoritários", "valor": -l1["minoritarios"]})
    passos.append({"rotulo": "Caixa do dono", "valor": l1["dono"], "total": True})
    H.append(fig(f"Do EBITDA ao caixa do dono em {l1['ano']} ({base['nome'].lower()}; R$ milhões de hoje)",
                 G.cascata(passos, lambda v: B.br(v, 0), "Cascata do EBITDA ao caixa do dono"), "CVM (DFP e ITR), contas da mesa",
                 f"De cada R$ 100 de EBITDA, R$ {B.br(100 * l1['dono'] / l1['ebitda'], 0)} chegam ao acionista. Conversão de caixa de {B.br(ins['conv'], 2)}x "
                 f"(mediana de 5 anos); dívida a {B.pct(ins['custo_nominal'])} nominal = {B.pct(ins['custo_real'])} real, convergindo para a NTN-B em 5 anos."))
    # o que o preco exige
    H.append("<h3>O que o preço exige</h3>")
    lin = []
    for r in o["reversa"]:
        lin.append([E(r["rotulo"]), _ipca(r["taxa"]), B.pct(r["crescimento"]) + " a.a." if r["crescimento"] is not None else "não fecha",
                    B.reais(r["preco"]) if r.get("preco") else "n/d"])
    if c["safra"].get("tir") and po["exige"].get("taxa"):
        x = po["exige"]
        lin.append(["TIR do Safra ao preço de hoje", _ipca(x["taxa"]), B.pct(x["crescimento"]) + " a.a." if x.get("crescimento") is not None else "não fecha",
                    B.reais(T.preco_para(o["cenarios"][0]["fluxo"], o["valor_mercado"], o["preco"], x["taxa"]) or 0)])
    H.append(_tab(["Para render", "Taxa real", "O caixa do dono cresce", "Ou o preço é"], lin, num=(1, 2, 3),
                  nota="Crescimento real por 10 anos, partindo do caixa parado. Preço: o que entrega a taxa sem crescimento nenhum."))
    if not profundo:
        pior = sorted((e for e in o["estresse"] if e["delta"] is not None and e["delta"] < -0.002), key=lambda e: e["delta"])[:2]
        if pior:
            H.append('<p class="leitura"><b>De qual premissa a conta mais depende:</b> ' + "; ".join(
                f'{E(e["nome"][0].lower() + e["nome"][1:])}: TIR de {_ipca(e["tir"])} ({B.pp(e["delta"])})' for e in pior) + ".</p>")
        return "".join(H)
    # ---------------- profundo
    fx = base["fluxo"]
    H.append(fig(f"Caixa do dono projetado ({base['nome'].lower()}; R$ milhões de hoje)",
                 G.colunas([str(l["ano"]) for l in fx["linhas"]], [{"nome": "Caixa do dono", "valores": [l["dono"] for l in fx["linhas"]], "cor": "acc"}],
                           lambda v: B.br(v, 0), descricao="Caixa do dono por ano"), "CVM (DFP e ITR), contas da mesa",
                 "Depois do ano 10: " + (f"fim da concessão em {fx['fim']}, com valor residual de {B.mi(fx['residual'])}." if fx["fim"] else
                                         f"perpetuidade sem crescimento real, com caixa do dono de {B.mi(fx['tipo']['dono'])} por ano.")))
    H.append(_tab(["Ano", "Caixa da operação", "Investimento e dívida", "Caixa do dono"],
                  [[l["ano"], B.br(l["caixa_oper"], 0), B.br(-l["investimento"] - l["custo_divida"] + l["divida_nova"] - l["minoritarios"], 0), B.br(l["dono"], 0)]
                   for l in fx["linhas"]], num=(1, 2, 3), nota="R$ milhões de hoje. Investimento e dívida: investimento, custo real da dívida, dívida nova e minoritários."))
    hs = [h for h in ins["hist_real"] if h.get("ebitda")][-8:]
    if len(hs) >= 3:
        H.append(fig("A história em reais de hoje: EBITDA, caixa da operação e investimento (R$ milhões)",
                     G.colunas([h["ano"] for h in hs], [{"nome": "EBITDA", "valores": [h["ebitda"] for h in hs], "cor": "acc"},
                                                        {"nome": "Caixa da operação", "valores": [h.get("fco_pre") for h in hs], "cor": "azul"},
                                                        {"nome": "Investimento", "valores": [h.get("capex") for h in hs], "cor": "cinza"}],
                               lambda v: B.br(v, 0), descricao="História de EBITDA, caixa e investimento", rotular=False),
                     "CVM (DFP), corrigido pelo IPCA", "Caixa da operação antes dos juros. Onde o investimento passa do caixa da operação, "
                     "a diferença foi coberta por dívida ou por aumento de capital."))
    H.append("<h3>Quanto a resposta muda quando uma premissa muda</h3>")
    H.append(_tab(["Se...", "TIR real", "Diferença"], [[E(e["nome"]), _ipca(e["tir"]), B.pp(e["delta"]) if e["delta"] is not None else "n/d"] for e in o["estresse"]],
                  num=(1, 2), nota="Sempre sobre o caixa parado. É aqui que se vê de qual premissa a tese depende."))
    sv = o["sensibilidade"]
    cols = [1, 2, 3]
    H.append(_tab(["Crescimento real do caixa do dono"] + [B.reais(sv["precos"][k]) for k in cols],
                  [[B.pct(h, 0, True) + " a.a."] + [_ipca(linha[k]) for k in cols] for h, linha in zip(sv["h"], sv["tir"])], num=(1, 2, 3),
                  nota="TIR real para cada preço (colunas) e cada crescimento por 10 anos (linhas).", destaque=(0,)))
    le, rot = o["lentes"], {"lucro_sobre_preco": "Lucro de 12 meses", "lucro_real_sobre_preco": "Lucro de 12 meses mais a correção monetária da dívida (lucro real)",
                            "dividendos_pagos_sobre_preco": "Dividendos e JCP pagos em 12 meses", "dividendos_mediana_5a_sobre_preco": "Dividendos pagos, mediana real de 5 anos",
                            "caixa_livre_5a_sobre_preco": "Caixa da operação menos investimento total, mediana de 5 anos"}
    H.append("<h3>Conferência: rendimentos simples sobre o valor de mercado</h3>")
    H.append(_tab(["Só com número publicado", "Sobre o valor de mercado"], [[rot[k], B.pct(le[k])] for k in rot if k in le], num=(1,),
                  nota="Não são TIR: servem para conferir se a conta acima está na ordem de grandeza certa."))
    return "".join(H)


def _sec_preco(c, fig, profundo):
    dm, po, sf = c["dam"], c["ponte"], c["safra"]
    H = ['<h2>Preço justo: Damodaran, Safra e consenso</h2>']
    if dm:
        cc = dm["custo"]
        cx = [f'<div><b>Preço justo pelo método de Damodaran:</b> {B.reais(dm["preco_justo"])} ({_sinal(dm["potencial"], B.pct(dm["potencial"], 0, True))} sobre o preço de tela)</div>',
              f'<div><b>Custo do capital próprio:</b> {B.pct(cc["ke_real"])} real = {B.pct(cc["ke_nominal"])} nominal (juro sem risco real {B.pct(cc["rf_real"], 2)} + beta {B.br(cc["beta"], 2)} × prêmio {B.pct(cc["premio"], 2)})</div>']
        if dm["tipo"] == "fcff":
            cx.append(f'<div><b>O preço de tela embute:</b> ' + (f'lucro operacional de {B.mi(dm["ebit_implicito"])} ({B.pct(dm["fator_implicito"] - 1, 0, True)} sobre os 12 meses)' if dm.get("fator_implicito") else "n/d")
                      + (f', ou retorno da firma de {B.pct(dm["wacc_implicito"])} real contra custo de capital de {B.pct(dm["wacc"])}' if dm.get("wacc_implicito") else "") + ".</div>")
        else:
            cx.append(f'<div><b>O preço de tela embute:</b> ROE de {B.pct(dm["roe_implicito"]) if dm.get("roe_implicito") is not None else "n/d"} para sempre '
                      f'(12 meses: {B.pct(dm["roe"])}); P/VP de tela {B.br(dm["p_vp"], 2)}x contra {B.br(dm["p_vp_justo"], 2)}x pelo método.</div>')
        H.append('<div class="caixa">' + "".join(cx) + "</div>")
    if po["precos"]:
        cor = lambda n: "azul" if n.startswith("Safra") else "claro" if n.startswith("Consenso") else "acc" if n.startswith("Damodaran") else "cinza"
        itens = [{"rotulo": n, "valor": v, "cor": cor(n), "forte": n.startswith("Damodaran")} for n, v, _ in po["precos"]]
        H.append(fig("Preço justo por lente contra o preço de tela (R$ por ação)", G.barras_h(itens, B.reais, c["preco"], "Preço de tela", "Preço justo por lente"),
                     "Safra, Yahoo (consenso), Aswath Damodaran (parâmetros) e CVM",
                     "Cada barra responde a uma pergunta diferente: o alvo do banco e o do consenso projetam o futuro; Damodaran usa o balanço e o "
                     "custo de capital de hoje" + ("; os preços da mesa dizem quanto pagar para ganhar a NTN-B ou a NTN-B mais o prêmio." if c["tir"] else ".")))
    if not c["tir"] and po["retornos"]:          # banco e seguradora: nao ha TIR por caixa, mas ha o retorno real pelo lucro
        m = c["mac"]
        itens = [{"rotulo": n.replace("Terminal: ", "").replace("TIR pelo lucro (", "Pelo lucro projetado (").replace("TIR pelo lucro de hoje", "Pelo lucro de hoje"),
                  "valor": v, "cor": "acc" if k == 0 else "claro", "forte": k == 0} for k, (n, v, _) in enumerate(po["retornos"])]
        itens.append({"rotulo": "O que a mesa exige: NTN-B + prêmio", "valor": m["ntnb_2035"] + m["regime"]["premio_exigido"], "cor": "cinza"})
        H.append(fig("Retorno real implícito no lucro, ao preço de hoje (% ao ano acima do IPCA)",
                     G.barras_h(itens, _p100, m["ntnb_2035"], "NTN-B 2035", "Retorno real pelo lucro contra a NTN-B 2035"),
                     "terminal (método do Safra replicado: lucro projetado, payout e crescimento de longo prazo), ANBIMA",
                     "Em banco não existe caixa do dono separado do lucro: a régua é o retorno real que o lucro entrega sobre o preço, "
                     "contra a NTN-B 2035 e contra o prêmio que a mesa exige neste regime."))
    if sf.get("rec"):
        H.append(f'<p>Recomendação do Safra: <b>{E(sf["rec"]["rec"])}</b> ({B.data_br(sf["rec"]["data"])}).</p>')
    if po["leitura"]:
        pts, resto = _corte(po["leitura"], "ponte", profundo)
        H.append("<h3>A ponte: de onde vem cada número</h3>" + _lista(pts) + (f'<div class="nota-tab">{resto}</div>' if resto else ""))
    if profundo and po["taxas"]:
        H.append(_tab(["Quem", "Taxa real exigida", "Como chega"], [[E(n), B.pct(v), E(nota)] for n, v, nota in po["taxas"]], num=(1,)))
    for a in sf["avisos"]:
        H.append(f'<p class="falta">{E(a)}</p>')
    hist = [h for h in sf.get("historia", []) if not h.get("repeticao")]
    if profundo and len(hist) >= 3:
        H.append(fig("TIR real que o Safra publicou para a ação, no tempo (% ao ano acima do IPCA)",
                     G.pontos([{"x": B.data_br(h["data"])[:5] + "/" + h["data"][2:4], "valor": h["tir"] * 100, "nota": B.reais(h["preco"])} for h in hist[-9:]],
                              lambda v: B.br(v, 1) + "%", [(sf["ke_real"] * 100, "Ke real do Safra", "neg")], "TIR do Safra no tempo"),
                     "Safra (relatórios e números informados ao assessor), terminal",
                     "Embaixo de cada data, o preço da ação naquele dia. A TIR do banco sobe quando o preço cai e desce quando o preço sobe; "
                     "quando muda sem o preço mudar, o banco mexeu no modelo."))
    if profundo and dm:
        H.append("<h3>Damodaran, passo a passo</h3>")
        sv = dm["sensibilidade"]
        if dm["tipo"] == "fcff":
            H.append(f'<p>Fluxo de caixa da firma em reais de hoje, 10 anos mais perpetuidade sem retorno em excesso. Valor da firma de {B.mi(dm["valor_firma"])} '
                     f'menos dívida líquida de {B.mi(dm["divida_liquida"])} = {B.mi(dm["valor_acionista"])} para o acionista. O valor depois do ano 10 pesa '
                     f'{B.pct(dm["terminal_peso"], 0)} do total.</p>')
            H.append(_tab(["Lucro operacional de partida"] + ["WACC " + B.pct(w) for w in sv["wacc"]],
                          [[B.pct(f - 1, 0, True) if f != 1 else "12 meses"] + [B.reais(x) if x is not None else "n/d" for x in linha] for f, linha in zip(sv["fator_ebit"], sv["preco"])],
                          num=(1, 2, 3), nota="Preço justo por ação para cada custo médio de capital (colunas) e cada nível de lucro operacional (linhas).", destaque=(1,)))
        else:
            H.append(f'<p>Retorno em excesso sobre o patrimônio: valor = patrimônio de {B.mi(dm["patrimonio"])} mais o valor presente de (ROE − custo do capital) × patrimônio. '
                     f'O ROE vai de {B.pct(dm["roe"])} ao custo do capital em 10 anos, salvo a parte que se supõe duradoura.</p>')
            H.append(_tab(["Quanto da diferença entre ROE e Ke dura para sempre"] + ["Ke " + B.pct(k) for k in sv["ke"]],
                          [[B.pct(x, 0)] + [B.reais(v) for v in linha] for x, linha in zip(sv["fracao"], sv["preco"])], num=(1, 2, 3), destaque=(0,)))
        par = dm["parametros"]
        H.append(f'<p class="nota-tab">Parâmetros de Aswath Damodaran (NYU Stern): prêmio de mercado maduro de {B.data_br(par["premio_maduro_data"])}; '
                 f'risco do Brasil e betas de {B.data_br(par["pais_data"])}. Beta do setor: {E(dm["custo"]["beta_setor"]["industria"])}, {E(dm["custo"]["beta_setor"]["base"])}.</p>')
    return "".join(H)


def _sec_setor(c, profundo, tx):
    s = c["setor"]
    H = [f'<h2>Como o analista do setor olha: {E(s["nome"].lower())}</h2>', f'<p><b>Método de avaliação do setor:</b> {E(s["metodo"])}.</p>']
    if tx.get("setor"):
        itens, resto = _corte(tx["setor"], "setor", profundo)
        H.append(_tab(["Indicador", "Valor", "Leitura"], [[E(x.get("indicador", "")), E(x.get("valor", "")), _com_fonte(x.get("leitura", ""), x["fonte"])] for x in itens],
                      nota=resto))
    # o roteiro generico do setor explica o porque de cada indicador: no resumido so entra quando o
    # analista nao trouxe os numeros (senao repete a tabela de cima e estica o relatorio)
    if profundo or not tx.get("setor"):
        ind = s["indicadores"] if profundo else s["indicadores"][:5]
        if tx.get("setor"):
            H.append("<h3>O roteiro do setor: o que o analista acompanha e por quê</h3>")
        H.append(_tab(["O que o analista do setor acompanha", "Por que importa"], [[E(a), E(b)] for a, b in ind]))
    if profundo or not tx.get("setor"):
        H.append("<h3>Armadilhas do setor</h3>" + _lista(s["armadilhas"] if profundo else s["armadilhas"][:3]))
    if profundo:
        H.append("<h3>Perguntas que a leitura do balanço e do release tem de responder</h3>" + _lista(s["perguntas"]))
    return "".join(H)


# Quantas linhas do texto do analista cabem no relatorio resumido (o profundo traz todas). O analista
# escreve em ordem de importancia: o resumido mostra as primeiras e avisa quantas ficaram de fora.
CORTE_RESUMIDO = {"gestao": 3, "setor": 4, "noticias": 3, "ponte": 4, "avisos": 2}


def _com_fonte(texto, fonte):
    """Celula com a fonte em letra pequena embaixo: a tabela fica com 3 colunas e cabe no celular."""
    return f"{E(texto)}<small>Fonte: {E(fonte)}</small>"


def _corte(itens, campo, profundo):
    """(itens que entram, nota sobre os que ficaram de fora)."""
    n = CORTE_RESUMIDO[campo]
    if profundo or len(itens) <= n:
        return itens, ""
    fora = len(itens) - n
    nome = {"ponte": ("ponto", "pontos"), "avisos": ("limite desta conta", "limites desta conta")}.get(campo, ("linha", "linhas"))
    return itens[:n], f"Mais {fora} {nome[0] if fora == 1 else nome[1]} no relatório profundo."


def _sec_texto(tx, profundo):
    H = []
    if tx.get("tese"):
        H.append("<h2>Leitura da mesa</h2>" + "".join(f"<p>{E(p)}</p>" for p in tx["tese"]))
    if tx.get("gestao"):
        itens, resto = _corte(tx["gestao"], "gestao", profundo)
        H.append("<h2>O que a gestão disse e o que entregou</h2>" +
                 _tab(["Tema", "Disse", "Entregou"], [[E(x.get("tema", "")), E(x.get("disse", "")), _com_fonte(x.get("entregou", ""), x["fonte"])] for x in itens],
                      nota=resto))
    elif profundo:
        H.append('<h2>O que a gestão disse e o que entregou</h2><p class="falta">Leitura dos 8 releases de resultado não anexada a este relatório '
                 "(sem o texto do analista). Os números acima vêm só das demonstrações da CVM.</p>")
    if tx.get("noticias"):
        itens, resto = _corte(tx["noticias"], "noticias", profundo)
        H.append("<h2>Notícias e revisões que mexem com a tese</h2>" +
                 _tab(["Data", "Fato", "O que muda"], [[E(x.get("data", "")), E(x.get("titulo", "")), _com_fonte(x.get("leitura", ""), x["fonte"])] for x in itens],
                      nota=resto))
    if tx.get("gatilhos"):
        H.append("<h2>Gatilhos</h2>" + _lista(tx["gatilhos"]))
    return "".join(H)


def _sec_riscos(c, tx, profundo=True):
    avisos = []
    for o in (c["tir"], c["dam"]):
        if o:
            avisos += [a for a in o["livro"].avisos if a not in avisos]
    H = ["<h2>Riscos da tese e limites desta conta</h2>"]
    if tx.get("riscos"):
        H.append(_lista(tx["riscos"]))
    if avisos:
        mostra, resto = _corte(avisos[:6], "avisos", profundo)
        H.append("".join(f'<div class="risco">{E(a)}</div>' for a in mostra) + (f'<div class="nota-tab">{resto}</div>' if resto else ""))
    if tx.get("mudaria"):
        H.append("<h3>O que faria a mesa mudar de ideia</h3>" + _lista(tx["mudaria"]))
    for l in c["lacunas"]:
        H.append(f'<p class="falta">Lacuna: {E(l)}</p>')
    return "".join(H) if len(H) > 1 else ""


def _sec_livro(c):
    H = ["<h2>Livro de premissas</h2><p>Todo número que entra na conta, com a origem. OFICIAL: demonstração ou documento da empresa. MERCADO: preço ou taxa "
         "negociada. CONSENSO: projeção de terceiros. GUIDANCE: o que a gestão prometeu. MESA: escolha da mesa, a única que pode ser discutida.</p>"]
    for tit, o in (("TIR real", c["tir"]), ("Preço justo de Damodaran", c["dam"])):
        if not o:
            continue
        lin = []
        for i in o["livro"].itens:
            lin.append([E(i.tipo), E(i.nome), E(_valor_livro(i)), E(i.fonte + (f", {B.data_br(i.data)}" if i.data else "") + (f". {i.nota}" if i.nota else ""))])
        H.append(f"<h3>{tit}</h3>" + _tab(["Tipo", "Premissa", "Valor", "Fonte"], lin))
    return "".join(H)


def termos_usados(corpo):
    """Termos do glossario que aparecem no texto do relatorio (sem as tags), na ordem do dicionario.
    Sigla confere maiuscula e minuscula; expressao por extenso nao."""
    texto = html.unescape(re.sub(r"<[^>]+>", " ", corpo))
    usa = []
    for k in TERMOS:
        sigla = k.isupper() or k in ("Ke", "pp") or "/" in k
        if re.search(r"(?<![\w-])" + re.escape(k) + r"(?![\w-])", texto, 0 if sigla else re.I):
            usa.append(k)
    return usa


def _termos(corpo):
    usa = termos_usados(corpo)
    if not usa:
        return ""
    return '<h2>Termos desta nota</h2><dl class="termos">' + "".join(f"<div><dt>{E(k)}</dt><dd>{E(TERMOS[k])}</dd></div>" for k in usa) + "</dl>"


def _estilo(rodape):
    css = (ESTILO / "estilo.css").read_text(encoding="utf-8")
    faces = []
    for arq, est in (("montserrat-latin.woff2", "normal"), ("montserrat-latin-italic.woff2", "italic")):
        f = ESTILO / arq
        if f.exists():
            b64 = base64.b64encode(f.read_bytes()).decode("ascii")
            faces.append("@font-face { font-family:'Montserrat'; font-style:%s; font-weight:400 800; font-display:swap; "
                         "src:url(data:font/woff2;base64,%s) format('woff2'); }" % (est, b64))
    return css.replace("%%FONTES%%", "\n".join(faces)).replace("%%RODAPE%%", rodape)


META_RESUMIDO = 6      # paginas: acima disso o resumido e refeito no modo compacto


def montar(ticker, modo="resumido", texto=None, contexto=None, preco=None, compacta=False):
    """Devolve (html, contexto). modo: 'resumido' ou 'profundo'. compacta: letra e respiro menores na impressao."""
    profundo = modo == "profundo"
    c = contexto or coletar(ticker, preco=preco)
    tx = texto if texto is not None else ler_texto(c["ticker"])
    tk, o, dm, sf = c["ticker"], c["tir"], c["dam"], c["safra"]
    fig = _Fig()
    hoje = dt.date.today()
    titulo = tx.get("titulo") or ("TIR real, preço justo e a ponte com o Safra" if not c["financeira"] else "Preço justo pelo retorno sobre o patrimônio e a ponte com o Safra")
    k = [("Preço", B.reais(c["preco"]), B.data_br(c["data_preco"]))]
    if o:
        b = o["central"]
        k += [("TIR real hoje", _ipca(b["tir"]), b["nome"].lower()),
              ("Prêmio sobre a NTN-B 2035", B.pp(b["premio"]) if b["premio"] is not None else "n/d", f"a mesa exige {B.br(o['premio_exigido'] * 100, 1)} pp")]
    elif dm:
        k += [("ROE de 12 meses", B.pct(dm["roe"]), f"custo do capital {B.pct(dm['custo']['ke_nominal'])}"), ("P/VP", B.br(dm["p_vp"], 2) + "x", f"justo pelo método: {B.br(dm['p_vp_justo'], 2)}x")]
    if dm:
        k.append(("Preço justo (Damodaran)", B.reais(dm["preco_justo"]), B.pct(dm["potencial"], 0, True) + " sobre a tela"))
    if sf.get("tir"):
        k.append(("TIR do Safra hoje", _ipca(sf["tir"]["hoje"]), f"{B.pct(sf['tir']['ref'])} em {B.data_br(sf['tir']['data'])}"))
    elif sf.get("alvo"):
        k.append(("Alvo do Safra", B.reais(sf["alvo"]["alvo"]), B.data_br(sf["alvo"]["data"]) + (" (velho)" if sf["alvo"]["velho"] else "")))
    elif sf.get("consenso"):
        k.append(("Alvo do consenso", B.reais(sf["consenso"]["alvo"]), f"{sf['consenso'].get('casas') or '?'} casas"))
    k.append(("Terreno para a bolsa", c["mac"]["regime"]["nome"].capitalize(), f"NTN-B 2035 a {_ipca(c['mac']['ntnb_2035'], 2)}"))
    corpo = [f'<div class="topo"><span>Mesa de análise · {E(c["setor"]["nome"])}</span><span>{hoje.strftime("%d/%m/%Y")} · relatório {modo}</span></div>',
             f'<div class="capa"><h1>{E(tk)} · {E(c["nome"])}</h1><p>{E(titulo)}</p></div>',
             f'<div class="frase"><b>Em uma frase.</b> {E(tx.get("em_uma_frase") or frase(c))}</div>', _kpis(k[:6]),
             _sec_macro(c, fig, profundo)]
    if o:
        corpo.append(_sec_tir(c, fig, profundo))
    corpo.append(_sec_preco(c, fig, profundo))
    corpo.append(_sec_texto(tx, profundo))
    corpo.append(_sec_setor(c, profundo, tx))
    corpo.append(_sec_riscos(c, tx, profundo))
    if profundo:
        corpo.append(_sec_livro(c))
    if tx.get("aprofundar"):
        corpo.append('<div class="junto"><h2>Quer aprofundar?</h2><ol>' + "".join(f"<li>{E(x)}</li>" for x in tx["aprofundar"]) + "</ol></div>")
    corpo.append(_termos("\n".join(x for x in corpo if x)))
    corpo.append('<div class="aviso">Material de estudo da mesa, para uso do assessor. Não é relatório de análise nem recomendação de investimento '
                 "(Resolução CVM 178): apresenta contas e comparações; a decisão e a recomendação são do assessor. Números das demonstrações oficiais "
                 "(CVM), de preços e taxas de mercado (B3, ANBIMA, Tesouro), do Boletim Focus (Banco Central), dos parâmetros publicados por Aswath Damodaran "
                 "e do que o Safra publicou ou informou, cada um com a data ao lado. Projeção não é promessa.</div>")
    rodape = f"{tk} · relatório {modo} · {hoje.strftime('%d/%m/%Y')}"
    pagina = ("<!doctype html>\n<html lang=\"pt-BR\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
              f"<title>{E(tk)} relatório {modo}</title>\n<style>\n{_estilo(rodape)}\n</style></head>\n<body><div class=\"folha{' compacta' if compacta else ''}\">\n" + "\n".join(x for x in corpo if x) +
              f'\n<div class="rodape"><span>{E(rodape)}</span><span>Mesa de análise</span></div>\n</div></body></html>\n')
    return pagina, c


def gravar(ticker, modo="resumido", texto=None, contexto=None, pdf=False, preco=None):
    pagina, c = montar(ticker, modo, texto, contexto, preco)
    arq = pasta(c["ticker"]) / f"{c['ticker']}_{modo}.html"
    arq.write_text(pagina, encoding="utf-8")
    out = {"html": arq, "contexto": c, "figuras": pagina.count("<figure>"), "compacta": False}
    if pdf:
        out["pdf"] = para_pdf(arq)
        n = conta_paginas(out["pdf"])
        if modo == "resumido" and n and n > META_RESUMIDO:
            pagina, _ = montar(ticker, modo, texto, c, preco, compacta=True)
            arq.write_text(pagina, encoding="utf-8")
            out["pdf"], out["compacta"] = para_pdf(arq), True
    return out


def conta_paginas(pdf):
    """Paginas do PDF, ou None sem o pymupdf ou sem o arquivo."""
    try:
        import pymupdf
        with pymupdf.open(pdf) as doc:
            return len(doc)
    except Exception:
        return None


def para_pdf(arq_html):
    """PDF pelo Chrome sem janela (o mesmo caminho do agente de FIIs). Devolve o caminho ou None."""
    if not Path(CHROME).exists():
        return None
    destino = Path(arq_html).with_suffix(".pdf")
    perfil = B.CACHE / "chrome-perfil"
    perfil.mkdir(parents=True, exist_ok=True)
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--no-pdf-header-footer", f"--user-data-dir={perfil}",
           f"--print-to-pdf={destino}", Path(arq_html).resolve().as_uri()]
    try:
        subprocess.run(cmd, capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return destino if destino.exists() and destino.stat().st_size > 5000 else None


BAIXAR = """<style>
.baixar { margin:0 0 14px; display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.baixar button { font:inherit; font-size:14px; font-weight:600; color:#fff; background:#101a5c;
  border:0; padding:9px 16px; cursor:pointer; }
.baixar button:disabled { opacity:.6; cursor:default; }
.baixar span { font-size:13px; color:#5d6577; }
</style>
<div class="baixar" id="baixar" hidden>
  <button type="button" id="baixar-btn">Baixar em PDF</button>
  <span id="baixar-msg" role="status"></span>
</div>
<script>
(function () {
  var caixa = document.getElementById('baixar'), btn = document.getElementById('baixar-btn'),
      msg = document.getElementById('baixar-msg');
  if (!window.claude || !window.claude.use) return;
  window.claude.use('downloads').then(function (dl) {
    if (!dl) return;
    caixa.hidden = false;
    btn.addEventListener('click', function () {
      btn.disabled = true;
      msg.textContent = 'Preparando o arquivo…';
      fetch('relatorio.pdf').then(function (r) {
        if (!r.ok) throw { code: 'arquivo' };
        return r.blob();
      }).then(function (b) {
        return dl.save({ filename: %%NOME%%, data: b });
      }).then(function () {
        msg.textContent = 'PDF salvo.';
      }).catch(function (e) {
        var c = e && e.code;
        msg.textContent = c === 'declined' ? ''
          : c === 'rate_limited' ? 'Aguarde um instante e toque de novo.'
          : 'Não foi possível baixar o PDF por aqui.';
      }).then(function () { btn.disabled = false; });
    });
  });
})();
</script>"""


def para_artifact(arq_html):
    """Pagina para publicar em Artifact: o mesmo relatorio, com o botao "Baixar em PDF" quando ha
    PDF ao lado. Devolve (pagina, pdf ou None). Publica-se com files={"relatorio.pdf": pdf} e
    capabilities={"downloads": true}."""
    src = Path(arq_html)
    pagina = src.read_text(encoding="utf-8")
    css = re.search(r"<style>(.*?)</style>", pagina, re.S)
    miolo = re.search(r"<body>(.*)</body>", pagina, re.S)
    titulo = re.search(r"<title>(.*?)</title>", pagina, re.S)
    if not (css and miolo and titulo):
        raise B.SemDado(f"{src.name} não saiu do comando relatorio.")
    corpo = miolo.group(1)
    pdf = src.with_suffix(".pdf")
    if pdf.exists():
        botao = BAIXAR.replace("%%NOME%%", json.dumps(html.unescape(titulo.group(1)) + ".pdf", ensure_ascii=False))
        corpo = corpo.replace('<div class="folha">', '<div class="folha">\n' + botao, 1)
    destino = src.with_name(src.stem + "_artifact.html")
    destino.write_text('<meta name="claude:viewport-fit-sides" content="cover">\n'
                       f"<title>{titulo.group(1)}</title>\n<style>{css.group(1)}</style>\n{corpo.strip()}\n", encoding="utf-8")
    return destino, (pdf if pdf.exists() else None)


def paginas(pdf, dpi=68):
    """Uma imagem por pagina do PDF, para conferir antes de entregar (figura cortada, pagina quase
    vazia, titulo sozinho no pe). Devolve a lista de PNGs; lista vazia se o pymupdf nao estiver instalado."""
    try:
        import pymupdf
    except ImportError:
        return []
    pdf = Path(pdf)
    dest = pdf.parent / "paginas"
    dest.mkdir(exist_ok=True)
    out = []
    with pymupdf.open(pdf) as doc:
        for i, pg in enumerate(doc, 1):
            arq = dest / f"{pdf.stem}-p{i}.png"
            pg.get_pixmap(dpi=dpi).save(arq)
            out.append(arq)
    return out
