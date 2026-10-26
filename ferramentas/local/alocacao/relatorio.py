"""Relatorio de asset allocation: HTML em A4 convertido em PDF pelo Chrome (sem cabecalho nem rodape do navegador).

Visual de relatorio institucional claro (fundo branco, tinta azul-marinho, serifa nos titulos, rotulos em caixa alta
espacada, cartoes de numeros e filetes finos), com capa azul-marinho e filete dourado. Dado de cliente fica na pasta
do cliente (LGPD): o PDF e o HTML sao gravados em `<cliente>/saida/` e nunca vao para Artifact nem para o git.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from datetime import date
from html import escape
from pathlib import Path

import numpy as np

from . import alinha as A
from . import cenarios as K
from . import cliente as CL
from . import config as C
from . import contexto as X
from . import graficos as G
from . import implementacao as I
from . import otimiza as O
from .formato import brl, mi, num, pct, pcts, pp, prob

CHROME = Path(os.environ.get("ALOCACAO_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
ASSESSOR = os.environ.get("ALOCACAO_ASSESSOR", "Douglas Lora")
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]
CONFIANCA = {"alta": "alta", "media": "média", "baixa": "baixa"}
GRUPOS = ["Liquidez", "Renda fixa isenta", "Renda fixa tributável", "Multimercado e previdência", "Renda variável",
          "Alternativos"]

CSS = """
@page { size: A4; margin: 0; }
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { background: #fff; }
body { font-family: 'Avenir Next','Helvetica Neue',Arial,sans-serif; color: #0d1b3e; font-size: 9.2pt; line-height: 1.45;
  -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.pg { width: 210mm; height: 297mm; padding: 16mm 17mm 18mm; position: relative; overflow: hidden;
  page-break-after: always; break-after: page; background: #fff; }
.pg:last-child { page-break-after: auto; break-after: auto; }
.cab { display: flex; justify-content: space-between; font: 600 6.4pt Menlo, monospace; letter-spacing: .16em;
  color: #6b7893; text-transform: uppercase; border-bottom: .6pt solid #d9e0ec; padding-bottom: 3mm; margin-bottom: 7mm; }
.rod { position: absolute; left: 17mm; right: 17mm; bottom: 8mm; display: flex; justify-content: space-between;
  font: 400 6pt Menlo, monospace; color: #8a96ad; border-top: .6pt solid #d9e0ec; padding-top: 2.4mm; }
h1 { font: 600 21pt/1.15 Charter, 'Iowan Old Style', Georgia, serif; letter-spacing: -.01em; margin-bottom: 1.5mm; }
.sub { font-size: 9.6pt; color: #5c6b8a; margin-bottom: 5mm; max-width: 150mm; }
h2 { font: 600 6.6pt Menlo, monospace; letter-spacing: .18em; color: #1f4e9c; text-transform: uppercase; margin: 6mm 0 2.4mm; }
p { margin-bottom: 2.2mm; }
.frase { font: 400 13.4pt/1.42 Charter, 'Iowan Old Style', Georgia, serif; color: #0d1b3e; margin: 1mm 0 5mm; }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 3mm; margin: 3mm 0 4mm; }
.kpi { border: .6pt solid #d9e0ec; padding: 3.4mm 3.4mm 3mm; border-radius: 1.4mm; }
.kpi.d { background: #eaf0fa; border-color: #b4c9e8; }
.kpi .l { font: 600 5.8pt Menlo, monospace; letter-spacing: .14em; color: #6b7893; text-transform: uppercase; }
.kpi .v { font: 600 17pt/1.1 Charter, Georgia, serif; margin-top: 1.6mm; }
.kpi .s { font-size: 7.2pt; color: #6b7893; margin-top: 1mm; line-height: 1.3; }
table { width: 100%; border-collapse: collapse; font-size: 8.2pt; margin: 1mm 0 3mm; }
th { font: 600 5.9pt Menlo, monospace; letter-spacing: .12em; text-transform: uppercase; color: #6b7893; text-align: left;
  border-bottom: .8pt solid #0d1b3e; padding: 1.5mm 1.5mm; }
td { padding: 1.6mm 1.5mm; border-bottom: .5pt solid #e6ebf3; vertical-align: top; }
td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
td.m { font-size: 7.4pt; color: #5c6b8a; }
tr.tot td { border-top: .8pt solid #0d1b3e; font-weight: 600; border-bottom: none; }
.chip { display: inline-block; font: 600 5.8pt Menlo, monospace; letter-spacing: .1em; text-transform: uppercase;
  padding: .5mm 1.8mm; border-radius: 2mm; white-space: nowrap; }
.chip.ok { background: #dff1ea; color: #1f7a5a; } .chip.atencao { background: #fbf0d5; color: #8a6a12; }
.chip.fora { background: #f7dcd5; color: #b3402a; } .chip.info { background: #e6ebf3; color: #5c6b8a; }
.nota { border-left: 1.1mm solid #1f4e9c; background: #f4f7fc; padding: 2.6mm 3.4mm; font-size: 8.2pt; margin: 3mm 0; }
.nota.aviso { border-left-color: #b39b6b; background: #fbf7ee; }
.nota.fora { border-left-color: #b3402a; background: #fcf1ee; }
.duas { display: grid; grid-template-columns: 1fr 1fr; gap: 7mm; }
.duas.estreita { grid-template-columns: 50mm 1fr; align-items: start; gap: 8mm; }
.leg { font-size: 7.6pt; } .leg div { display: flex; align-items: center; gap: 2mm; padding: .7mm 0; }
.leg i { width: 2.4mm; height: 2.4mm; border-radius: .5mm; display: inline-block; flex: none; }
.leg b { margin-left: auto; font-variant-numeric: tabular-nums; font-weight: 600; }
.par { display: grid; grid-template-columns: 44mm 1fr; font-size: 8.2pt; border-bottom: .5pt solid #e6ebf3; padding: 1.5mm 0; }
.par span { color: #6b7893; } .par b { font-weight: 500; }
ul.l { list-style: none; font-size: 8.2pt; } ul.l li { padding: 1.3mm 0 1.3mm 4mm; position: relative; border-bottom: .5pt solid #eef1f7; }
ul.l li::before { content: ''; position: absolute; left: 0; top: 2.9mm; width: 1.5mm; height: 1.5mm; background: #b39b6b; border-radius: 50%; }
.gl { display: grid; grid-template-columns: 1fr 1fr; gap: 0 7mm; font-size: 7.8pt; }
.gl div { padding: 1.3mm 0; border-bottom: .5pt solid #eef1f7; } .gl b { color: #1f4e9c; font-weight: 600; }
.peq { font-size: 7.4pt; color: #6b7893; }
.fonte { font: 400 6.2pt Menlo, monospace; color: #8a96ad; margin-top: 1mm; }
table.c { margin: .6mm 0 2mm; } table.c td { padding: 1.05mm 1.5mm; font-size: 7.7pt; } table.c th { padding: 1.1mm 1.5mm; }
.sw { display: inline-block; width: 2.3mm; height: 2.3mm; border-radius: .5mm; margin-right: 1.8mm; vertical-align: -.25mm; }
/* capa */
.capa { background: #0d1b3e; color: #fff; padding: 0; }
.capa::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 7mm; background: #b39b6b; }
.capa .in { position: absolute; left: 26mm; right: 20mm; top: 50mm; }
.capa .rot { font: 600 7pt Menlo, monospace; letter-spacing: .26em; color: #b39b6b; text-transform: uppercase; }
.capa h1 { font: 700 38pt/1.08 Charter, 'Iowan Old Style', Georgia, serif; color: #fff; margin: 9mm 0 4mm; letter-spacing: -.012em; }
.capa .it { font: italic 400 15pt/1.35 Charter, Georgia, serif; color: #c7d3ea; max-width: 140mm; }
.capa .fio { width: 34mm; height: .9mm; background: #b39b6b; margin: 11mm 0 9mm; }
.capa .cli { font: 600 20pt Charter, Georgia, serif; margin-bottom: 8mm; }
.capa .attr { display: grid; grid-template-columns: repeat(4, 1fr); gap: 5mm; }
.capa .attr div span { display: block; font: 600 5.8pt Menlo, monospace; letter-spacing: .18em; color: #b39b6b; text-transform: uppercase; margin-bottom: 1.4mm; }
.capa .attr div b { font: 500 10.4pt/1.3 'Avenir Next', Helvetica, sans-serif; color: #fff; }
.capa .pe { position: absolute; left: 26mm; right: 20mm; bottom: 14mm; display: flex; justify-content: space-between; font: 400 6.6pt Menlo, monospace; color: #8fa3c8; letter-spacing: .08em; }
"""


# ------------------------------------------------------------------------------------------------------
# blocos de HTML
def e(x) -> str:
    return escape(str(x if x is not None else ""))


def dmy(s) -> str:
    """AAAA-MM-DD (ou AAAA-MM-DDTHH:MM) -> dd/mm/aaaa; texto livre passa direto."""
    s = str(s or "")
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}:\d{2}))?", s)
    if not m:
        return s
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" + (f" {m.group(4)}" if m.group(4) else "")


def virg(s) -> str:
    """Decimal brasileiro em texto herdado das premissas (3.78% -> 3,78%)."""
    return re.sub(r"(?<=\d)\.(?=\d)", ",", str(s or ""))


def sw(cid: str) -> str:
    return f'<i class="sw" style="background:{C.POR_ID[cid].cor}"></i>'


def cel_classe(c) -> str:
    return sw(c.id) + e(c.curto)


def meses(x) -> str:
    if not x:
        return "—"
    k = int(round(float(x)))
    return "1 mês" if k == 1 else f"{k} meses"


def data_extensa(d: date) -> str:
    return f"{d.day} de {MESES[d.month-1]} de {d.year}"


def _v(x, fmt=lambda z: str(z), vazio="não informado") -> str:
    return vazio if x in (None, "", []) else fmt(x)


def chip(status: str, texto: str | None = None) -> str:
    return f'<span class="chip {status}">{e(texto or A.ROTULO.get(status, status))}</span>'


def kpi(rotulo: str, valor: str, sub: str = "", destaque: bool = False) -> str:
    return f'<div class="kpi{" d" if destaque else ""}"><div class="l">{e(rotulo)}</div><div class="v">{e(valor)}</div><div class="s">{e(sub)}</div></div>'


def tabela(cab: list, linhas: list, num_cols: tuple = (), total: bool = False, compacta: bool = False) -> str:
    h = "".join(f'<th class="{"n" if i in num_cols else ""}">{e(c)}</th>' for i, c in enumerate(cab))
    corpo = []
    for k, ln in enumerate(linhas):
        cls = ' class="tot"' if total and k == len(linhas) - 1 else ""
        cel = "".join(f'<td class="{"n" if i in num_cols else ""}">{c if str(c).startswith("<") else e(c)}</td>' for i, c in enumerate(ln))
        corpo.append(f"<tr{cls}>{cel}</tr>")
    return f"<table{' class=\"c\"' if compacta else ''}><thead><tr>{h}</tr></thead><tbody>{''.join(corpo)}</tbody></table>"


def nota(texto: str, tipo: str = "") -> str:
    return f'<div class="nota {tipo}">{texto}</div>'


def legenda(pesos: dict, minimo: float = 0.004) -> str:
    itens = [(c, pesos.get(c.id, 0.0)) for c in C.CLASSES if pesos.get(c.id, 0.0) > minimo]
    return '<div class="leg">' + "".join(f'<div><i style="background:{c.cor}"></i>{e(c.curto)}<b>{pct(p,1)}</b></div>' for c, p in itens) + "</div>"


def pagina(n: int, secao: str, ctx: X.Contexto, corpo: str, titulo: str = "", sub: str = "") -> str:
    cab = (f'<div class="cab"><span>{n:02d} · {e(secao)}</span><span>Alocação de ativos · {e(ctx.ficha["nome"])}</span></div>')
    t = f"<h1>{e(titulo)}</h1>" if titulo else ""
    s = f'<div class="sub">{e(sub)}</div>' if sub else ""
    rod = (f'<div class="rod"><span>Material de trabalho do assessor · não constitui recomendação de investimento · '
           f'rentabilidade esperada não é garantia</span><span>{n}</span></div>')
    return f'<section class="pg">{cab}{t}{s}{corpo}{rod}</section>'


def _rotulo_status(st: str) -> str:
    return {"ok": "alinhado", "atencao": "atenção", "fora": "fora", "info": "informativo"}[st]


# ------------------------------------------------------------------------------------------------------
# dados
def montar_dados(nome: str, curva: str = "viva", n_sim: int = 10000) -> dict:
    ctx = X.montar(nome, curva=curva, n_sim=n_sim)
    prop = CL.ler_proposta(nome)
    if not prop:
        raise FileNotFoundError(f"{nome}: ainda nao ha proposta gravada (rode `alocar.py proposta` ou `sugerir`)")
    w = X.vetor(prop["pesos"])
    w = w / w.sum()
    a = X.avaliar(ctx, w, "proposta")
    atual_w = atual_a = None
    if ctx.atual and ctx.atual.get("pesos"):
        atual_w = X.vetor(ctx.atual["pesos"])
        atual_w = atual_w / atual_w.sum()
        atual_a = X.avaliar(ctx, atual_w, "atual")
    modelo_a = X.avaliar(ctx, ctx.w_modelo, "modelo")
    checks = A.checar(ctx, a)
    ver = A.veredito(checks)
    checks_atual = A.checar(ctx, atual_a) if atual_a else None
    cs = O.candidatos(ctx.mu, ctx.cov, ctx.restr)
    fr = O.fronteira(ctx.mu, ctx.cov, ctx.restr, pontos=12)
    pl = ctx.plano.pl
    trans = I.transicao(w, atual_w, pl, ctx.mercado.em_choque)
    regras = I.regras_acompanhamento(w)
    ev = ctx.plano.eventos
    esteira = I.esteira_de_liquidez(ev, pl, ctx.ipca)
    anos = max(int(round(ctx.horizonte)), 1)
    trilha = I.trilha(w, pl, ctx.plano.aporte_mensal, a["ret"], anos, ctx.ipca, ev)
    return dict(ctx=ctx, prop=prop, w=w, a=a, atual_w=atual_w, atual_a=atual_a, modelo_a=modelo_a, checks=checks, ver=ver,
                checks_atual=checks_atual, cands=cs, fronteira=fr, trans=trans, regras=regras, esteira=esteira, trilha=trilha,
                hoje=date.today())


# ------------------------------------------------------------------------------------------------------
# paginas
def p_capa(d: dict) -> str:
    ctx, f = d["ctx"], d["ctx"].ficha
    obj = f["objetivo"].get("descricao") or "Estratégia de longo prazo"
    meta = f["objetivo"].get("meta_patrimonio")
    return f'''<section class="pg capa"><div class="in">
      <div class="rot">Asset allocation estratégica</div>
      <h1>Estratégia de Alocação<br>de Ativos</h1>
      <div class="it">Construção de portfólio sob medida: premissas de mercado, risco, projeção e plano de implementação.</div>
      <div class="fio"></div>
      <div class="cli">{e(f["nome"])}</div>
      <div class="attr">
        <div><span>Perfil</span><b>{e(C.ROTULOS_PERFIL[ctx.perfil])}</b></div>
        <div><span>Patrimônio sob análise</span><b>{e(mi(ctx.plano.pl))}</b></div>
        <div><span>Horizonte</span><b>{e(num(ctx.horizonte,0))} anos</b></div>
        <div><span>Objetivo</span><b>{e(obj[:70])}{(" · meta " + mi(meta)) if meta else ""}</b></div>
      </div></div>
      <div class="pe"><span>{e(ASSESSOR.upper())} · ASSESSOR DE INVESTIMENTOS</span><span>{e(data_extensa(d["hoje"]).upper())}</span></div></section>'''


def _frase(d: dict) -> str:
    ctx, a, w = d["ctx"], d["a"], d["w"]
    f = ctx.ficha
    iso = sum(w[C.IDS.index(c)] for c in ("pos_isenta", "ipca_isenta", "pre_isenta"))
    rf = sum(w[C.IDS.index(c)] for c in C.IDS if C.POR_ID[c].grupo in ("Liquidez", "Renda fixa isenta", "Renda fixa tributável"))
    meta = f["objetivo"].get("meta_patrimonio")
    sim = a["sim"]
    s = (f"A proposta põe {pct(rf,0)} em renda fixa ({pct(iso,0)} isenta de imposto) e {pct(a['rv'],0)} em renda variável, e rende "
         f"{pct(a['ret'])} ao ano líquido de imposto ({pct(a['ret_real'])} acima da inflação)")
    if meta and sim["p_meta"] is not None:
        s += f", com {prob(sim['p_meta'],0)} de chance de chegar a {mi(meta)} (em reais de hoje) em {num(ctx.horizonte,0)} anos"
    cont = d["ver"]["contagem"]
    if d["ver"]["status"] == "ok":
        s += "; está alinhada ao cliente."
    elif d["ver"]["status"] == "atencao":
        s += f"; está alinhada, com {cont['atencao']} ponto{'s' if cont['atencao']!=1 else ''} de atenção."
    else:
        s += f"; está fora do alinhamento em {cont['fora']} ponto{'s' if cont['fora']!=1 else ''}."
    return s


def p_resumo(d: dict, n: int) -> str:
    ctx, a, w, ver = d["ctx"], d["a"], d["w"], d["ver"]
    sim = a["sim"]
    pior = a["estresse"]["pior"]
    ks = "".join([
        kpi("Retorno líquido esperado", pct(a["ret"]) + " a.a.", f"{pct(a['ret_real'])} acima da inflação · 100% CDI líquido: {pct(ctx.bench)}", True),
        kpi("Volatilidade", pct(a["vol"]), f"orçamento do perfil: {pct(ctx.restr.vol_max or 0)}"),
        kpi("Chance de atingir a meta", prob(sim["p_meta"], 0).replace("mais de ", ">").replace("menos de ", "<") if sim["p_meta"] is not None else "—",
            f"meta {mi(ctx.plano.meta)} em reais de hoje" if ctx.plano.meta else "sem meta na ficha"),
        kpi("Pior cenário testado", pct(pior["total"], 1) if pior else "—", pior["nome"] if pior else ""),
    ])
    ref = d["atual_w"] if d["atual_w"] is not None else None
    linhas = []
    for i, c in enumerate(C.CLASSES):
        if w[i] < 0.003 and (ref is None or ref[i] < 0.003):
            continue
        base = ref[i] if ref is not None else ctx.w_modelo[i]
        linhas.append([cel_classe(c), pct(base, 1), pct(w[i], 1), pp(w[i] - base, 1)])
    base_nome = "Hoje" if ref is not None else "Modelo"
    cont = ver["contagem"]
    pontos = [c for c in d["checks"] if c["status"] in ("fora", "atencao")][:4]
    lista = "".join(f'<li>{chip(c["status"])} <b>{e(c["titulo"])}</b>: {e(c["leitura"])}</li>' for c in pontos) or "<li>Nenhum ponto de atenção.</li>"
    corpo = (f'<div class="frase">{e(_frase(d))}</div><div class="kpis">{ks}</div>'
             f'<div class="duas estreita"><div>{G.donut({cid: float(w[i]) for i, cid in enumerate(C.IDS)}, "100%", "carteira alvo", 230)}</div>'
             f'<div>{tabela(["Classe", base_nome, "Proposta", "Δ"], linhas, (1, 2, 3), compacta=True)}</div></div>'
             f'<h2>Alinhamento com o cliente</h2><p>{chip(ver["status"], ver["veredito"])} &nbsp;'
             f'<span class="peq">{cont["ok"]} alinhados · {cont["atencao"]} de atenção · {cont["fora"]} fora</span></p>'
             f'<ul class="l">{lista}</ul>')
    return pagina(n, "Resumo executivo", ctx, corpo, "Resumo executivo", "A estratégia em uma página: o que se propõe, o que se espera e se cabe no cliente.")


def p_ficha(d: dict, n: int) -> str:
    ctx = d["ctx"]
    f = ctx.ficha
    ps, pa, fl, ob, rk, lq, rs, mo, fi, su = (f[k] for k in ("pessoa", "patrimonio", "fluxo", "objetivo", "risco", "liquidez", "restricoes", "moeda", "fiscal", "sucessao"))
    par = lambda r, v: f'<div class="par"><span>{e(r)}</span><b>{e(v)}</b></div>'
    sim_nao = lambda x: "sim" if x else "não"
    quem = "".join([
        par("Idade", _v(ps.get("idade"), lambda x: f"{x} anos")), par("Estado civil", _v(ps.get("estado_civil"))),
        par("Dependentes", _v(ps.get("dependentes"))), par("Profissão", _v(ps.get("profissao"))),
        par("Estabilidade da renda", _v(ps.get("estabilidade_renda"))),
        par("Patrimônio financeiro", _v(pa.get("financeiro"), brl)), par("Imóveis", _v(pa.get("imoveis"), brl)),
        par("Empresa e participações", _v(pa.get("empresa_participacoes"), brl)), par("Dívidas", _v(pa.get("dividas"), brl)),
        par("Renda mensal", _v(fl.get("renda_mensal"), brl)), par("Despesa mensal", _v(fl.get("despesa_mensal"), brl)),
        par("Aporte mensal", _v(fl.get("aporte_mensal") or None, brl, "nenhum")),
        par("Renda anual (IRPFM)", _v(fl.get("renda_anual_para_irpfm"), brl)),
    ])
    queda = rk.get("queda_maxima_tolerada")
    quer = "".join([
        par("Objetivo", _v(ob.get("descricao"))), par("Meta de patrimônio", _v(ob.get("meta_patrimonio"), mi)),
        par("Prazo", _v(ob.get("prazo_anos"), lambda x: f"{x} anos")),
        par("Perfil (suitability)", C.ROTULOS_PERFIL[ctx.perfil]),
        par("Queda máxima tolerada", _v(queda, lambda x: f"{num(x,0)}% (pico ao vale)") if queda else f"padrão do perfil: {pct(ctx.queda_limite,0)}"),
        par("Reação a queda de 20%", _v(rk.get("reacao_a_queda_20pct"))),
        par("Reserva de liquidez", f"{lq.get('reserva_meses') or 0} meses de despesa" + (f" + {brl(lq['obrigacoes_12m'])} em 12 meses" if lq.get("obrigacoes_12m") else "")),
        par("Classes vetadas", ", ".join(C.POR_ID[c].curto for c in rs.get("classes_vetadas", []) if c in C.POR_ID) or "nenhuma"),
        par("Despesas em dólar", _v(mo.get("despesas_em_dolar_pct"), lambda x: f"{num(x,0)}% das despesas") if mo.get("despesas_em_dolar_pct") else "nenhuma informada"),
        par("Declaração / PGBL", f"{_v(fi.get('declaracao_completa'), sim_nao)} / {_v(fi.get('usa_pgbl'), sim_nao)}"),
        par("Sucessão", "; ".join(f"{k.replace('_', ' ')}: {sim_nao(v)}" for k, v in su.items() if v is not None) or "não informada"),
    ])
    lac = CL.lacunas(f)[:6]
    falta = ("".join(f'<li>{e(x["pergunta"])}</li>' for x in lac)) or "<li>Ficha completa.</li>"
    ev = fl.get("eventos") or []
    evt = tabela(["Quando", "Evento", "Valor (R$ de hoje)"], [[f"mês {x.get('mes')}", x.get("desc") or x.get("descricao") or "—", ("entrada de " if x.get("valor", 0) > 0 else "saída de ") + brl(abs(x.get("valor", 0)))] for x in ev], (2,), compacta=True) if ev else ""
    obs = "".join(f"<li>{e(o)}</li>" for o in f.get("observacoes", []))
    corpo = (f'<div class="duas"><div><h2>Quem é o cliente</h2>{quem}</div><div><h2>O que ele quer e aguenta</h2>{quer}</div></div>'
             + (f"<h2>Entradas e saídas previstas</h2>{evt}" if evt else "")
             + f'<h2>A confirmar com o cliente</h2><ul class="l">{falta}</ul>'
             + (f'<h2>Observações do assessor</h2><ul class="l">{obs}</ul>' if obs else ""))
    return pagina(n, "Ficha e mandato", ctx, corpo, "O cliente e o mandato", "Tudo que muda a carteira: o que ele tem, o que quer, o que aguenta e o que não aceita.")


def p_cenario(d: dict, n: int) -> str:
    ctx = d["ctx"]
    m = ctx.mercado
    H = ctx.horizonte
    est = " (estim.)" if m.em_choque else ""
    fonte_bcb = f"BCB · {dmy(m.fontes[0][1])}"
    fonte_di = f"B3 · hoje {m.di_vivo_hora}" if m.di_vivo else f"B3 · ajuste de {dmy(m.di_data)}"
    linhas = [
        ["Selic meta", f"{num(m.selic_meta,2)}% a.a.", fonte_bcb],
        ["CDI", f"{num(m.cdi,2)}% a.a.", fonte_bcb],
        ["IPCA em 12 meses", f"{num(m.ipca_12m,2)}%", fonte_bcb],
        [f"IPCA esperado ({num(H,0)} anos)", f"{num(m.ipca_esperado(H),2)}% a.a.", f"Focus · {dmy(m.focus_data)}"],
        ["DI x pré, 1 ano", f"{num(m.di_aa(1),2)}% a.a.", fonte_di],
        ["DI x pré, 3 anos", f"{num(m.di_aa(3),2)}% a.a.", "B3"], ["DI x pré, 5 anos", f"{num(m.di_aa(5),2)}% a.a.", "B3"],
        [f"Juro real (NTN-B), {num(H,0)} anos", f"{num(m.real_aa(H),2)}% a.a.{est}", f"ANBIMA · {dmy(m.ntnb_data)}"],
        [f"Pré-fixado, {num(H,0)} anos", f"{num(m.pre_aa(H),2)}% a.a.{est}", "ANBIMA + DI"],
        ["Treasury de 10 anos", f"{num(m.ust10,2)}% a.a.", f"EUA · {dmy(m.ust_data)}"],
        ["Dólar PTAX", f"R$ {num(m.ptax,4)}", f"BCB · {dmy(m.ptax_data)}"],
    ]
    aviso = ""
    if m.em_choque:
        sentido = "acima" if m.choque_bps > 0 else "abaixo"
        como = (f"deslocamento de {num(m.ajustes['real_bps'],0)} pontos-base informado pelo assessor" if "real_bps" in m.ajustes
                else "estimados a partir da ANBIMA da véspera mais metade do deslocamento do DI")
        aviso = nota(f"<b>Mercado em choque hoje.</b> O DI de 3 anos negocia {num(abs(m.choque_bps),0)} pontos-base {sentido} do ajuste de {dmy(m.di_data)}. "
                     f"A NTN-B da ANBIMA ({dmy(m.ntnb_data)}) ainda não reflete o movimento: os juros reais e pré-fixados marcados “estim.” foram {como}. "
                     "Confirme as taxas no balcão antes de levar números ao cliente.", "aviso")
    elif m.veredito != "ATUAL":
        velhos = [x.replace("dado velho: ", "") for x in m.avisos if x.startswith("dado velho")]
        aviso = nota("<b>Dado de mercado defasado.</b> " + e("; ".join(velhos)) + ". Os números podem não refletir o pregão de hoje.", "aviso")
    visoes = "".join(f'<li><b>{e(("CDI" if v["classe"]=="_cdi" else "IPCA" if v["classe"]=="_ipca" else C.POR_ID[v["classe"]].curto))}</b> {pp(v["delta_pp"]/100.0,1)} ao ano: {e(v["tese"])}</li>' for v in ctx.visoes)
    curva = G.curva_di(m.di_vivo, m.di_ajuste, m.ntnb, altura=225)
    corpo = (aviso + f'<h2>Curva de juros</h2>{curva}<div class="fonte">DI x pré (B3) e juro real da NTN-B (ANBIMA), por prazo.</div>'
             + "<h2>Indicadores e fontes</h2>" + tabela(["Indicador", "Valor", "Fonte"], linhas, (1,), compacta=True)
             + (f'<h2>Visões do assessor que mudam as premissas</h2><ul class="l">{visoes}</ul>' if visoes else
                '<h2>Visões do assessor</h2><p class="peq">Nenhuma: as premissas seguem o mercado puro. Cada opinião do assessor entra aqui como deslocamento em pontos percentuais ao ano, sempre visível.</p>'))
    return pagina(n, "Cenário de mercado", ctx, corpo, "O que o mercado paga hoje",
                  f"Curva, inflação esperada e juro real são a base das premissas; tudo com fonte e data. Retrato de {dmy(m.consulta)}: "
                  f"{'dados atuais' if m.veredito == 'ATUAL' else 'dados com defasagem'}.")


def p_premissas(d: dict, n: int) -> str:
    ctx = d["ctx"]
    ids = [c for c in C.IDS if ctx.restr.hi[C.IDS.index(c)] > 0]
    prem = [{"classe": C.POR_ID[c].curto, "bruto": ctx.prem[c].bruto_total, "liquido": ctx.prem[c].liquido} for c in ids]
    graf = G.barras_retorno(prem, ctx.bench, linha=21)
    linhas = [[cel_classe(C.POR_ID[c]), pct(ctx.prem[c].liquido, 1), CONFIANCA.get(ctx.prem[c].confianca, ctx.prem[c].confianca), f"<span class='peq'>{e(virg(ctx.prem[c].metodo))}</span>"] for c in ids]
    corpo = (graf + '<div class="fonte">Retorno esperado ao ano, em média no horizonte; "líquido" já desconta imposto no horizonte e custos.</div>'
             + "<h2>Como cada número foi construído</h2>"
             + tabela(["Classe", "Líquido", "Confiança", "Método"], linhas, (1,), compacta=True)
             + nota("<b>Leitura.</b> Com o CDI alto, renda variável paga pouco acima da renda fixa isenta: ela entra na carteira por diversificação, "
                    "proteção cambial e opção de crescimento, não por prêmio. Confiança <i>baixa</i> significa que o número é ordem de grandeza, não previsão."))
    return pagina(n, "Premissas", ctx, corpo, "Retorno esperado por classe", "Cada classe tem método, fonte e grau de confiança declarados. Nada é palpite sem rótulo.")


def p_diagnostico(d: dict, n: int) -> str:
    ctx, w = d["ctx"], d["w"]
    if d["atual_w"] is not None:
        aw, aa, at = d["atual_w"], d["atual_a"], ctx.atual
        ks = "".join([kpi("Patrimônio na carteira atual", mi(at["total"]), f"{len(at['posicoes'])} posições", True),
                      kpi("Retorno esperado hoje", pct(aa["ret"]), f"proposta: {pct(d['a']['ret'])}"),
                      kpi("Volatilidade hoje", pct(aa["vol"]), f"proposta: {pct(d['a']['vol'])}"),
                      kpi("Emissores bancários", str(len(at.get("emissores", {}))), "concentração e FGC abaixo")])
        linhas = []
        for i, c in enumerate(C.CLASSES):
            if aw[i] < 0.003 and w[i] < 0.003:
                continue
            lo, hi = ctx.restr.lo[i], ctx.restr.hi[i]
            st = "ok" if lo - 0.0026 <= aw[i] <= hi + 0.0026 else "fora"
            txt = "dentro da banda" if st == "ok" else ("acima da banda" if aw[i] > hi else "abaixo da banda")
            linhas.append([cel_classe(c), pct(aw[i], 1), f"{pct(lo,0)} a {pct(hi,0)}", chip(st, txt)])
        pontos = [c for c in (d["checks_atual"] or []) if c["status"] in ("fora", "atencao")][:4]
        lista = "".join(f'<li>{chip(c["status"])} <b>{e(c["titulo"])}</b>: {e(c["leitura"])}</li>' for c in pontos) or "<li>Sem pontos de atenção relevantes.</li>"
        emis = sorted(at.get("emissores", {}).items(), key=lambda kv: -kv[1])[:3]
        t_emis = tabela(["Emissor", "Valor", "Cobertura do FGC (R$ 250 mil)"], [[k, brl(v), "acima do limite" if v > 250_000 else "dentro"] for k, v in emis], (1,), compacta=True) if emis else ""
        conf = "".join(f"<li>{e(x)}</li>" for x in at.get("a_conferir", [])[:2])
        corpo = (f'<div class="kpis">{ks}</div><div class="duas estreita"><div>{G.donut({cid: float(aw[i]) for i, cid in enumerate(C.IDS)}, "hoje", "carteira atual", 200)}</div>'
                 f'<div>{tabela(["Classe", "Hoje", "Banda do perfil", "Situação"], linhas, (1,), compacta=True)}</div></div>'
                 f'<h2>O que chama atenção hoje</h2><ul class="l">{lista}</ul>'
                 + (f"<h2>Concentração por emissor</h2>{t_emis}" if t_emis else "")
                 + (f'<h2>Posições a conferir</h2><ul class="l">{conf}</ul>' if conf else ""))
        return pagina(n, "Diagnóstico", ctx, corpo, "Diagnóstico da carteira atual", "Onde o cliente está hoje, contra as bandas do perfil e as checagens de risco.")
    mo = d["modelo_a"]
    ks = "".join([kpi("Ponto de partida", "Carteira modelo", f"perfil {C.ROTULOS_PERFIL[ctx.perfil].lower()}", True),
                  kpi("Retorno do modelo", pct(mo["ret"]), f"proposta: {pct(d['a']['ret'])}"),
                  kpi("Volatilidade do modelo", pct(mo["vol"]), f"proposta: {pct(d['a']['vol'])}"),
                  kpi("Classes", str(sum(1 for x in ctx.w_modelo if x > 0)), "no modelo do perfil")])
    linhas = [[cel_classe(c), pct(ctx.w_modelo[i], 1), pct(w[i], 1), pp(w[i] - ctx.w_modelo[i], 1)] for i, c in enumerate(C.CLASSES)
              if ctx.w_modelo[i] > 0.003 or w[i] > 0.003]
    corpo = (f'<div class="kpis">{ks}</div>'
             + nota("Sem carteira atual cadastrada: o diagnóstico parte da <b>carteira modelo do perfil</b> (a mesma que ancora o otimizador). "
                    "Quando o extrato do cliente for importado, esta página passa a mostrar as posições reais, a concentração por emissor e o FGC.")
             + tabela(["Classe", "Modelo do perfil", "Proposta", "Δ"], linhas, (1, 2, 3), compacta=True))
    return pagina(n, "Diagnóstico", ctx, corpo, "Ponto de partida", "Sem carteira atual no sistema, a referência é o modelo do perfil.")


def p_proposta(d: dict, n: int) -> str:
    ctx, w, a = d["ctx"], d["w"], d["a"]
    linhas = []
    for i, c in enumerate(C.CLASSES):
        if w[i] < 0.0005 and ctx.restr.hi[i] <= 0:
            continue
        linhas.append([f"{sw(c.id)}<b>{e(c.curto)}</b><br><span class='peq'>{e(c.papel)}</span>", f"{pct(ctx.restr.lo[i],0)} a {pct(ctx.restr.hi[i],0)}", pct(w[i], 1), brl(w[i] * ctx.plano.pl)])
    linhas.append(["Total", "", "100,0%", brl(ctx.plano.pl)])
    grupos = {g: sum(w[i] for i, c in enumerate(C.CLASSES) if c.grupo == g) for g in GRUPOS}
    glinhas = [[g, pct(v, 1)] for g, v in grupos.items() if v > 0.0005]
    corpo = (f'<div class="duas estreita"><div>{G.donut({cid: float(w[i]) for i, cid in enumerate(C.IDS)}, "100%", "carteira alvo", 230)}</div>'
             f'<div>{tabela(["Grupo", "Peso"], glinhas, (1,), compacta=True)}</div></div>'
             + tabela(["Classe e papel na carteira", "Banda", "Alvo", "Valor"], linhas, (1, 2, 3), total=True, compacta=True)
             + nota(f"<b>Proposta v{d['prop']['versao']}</b> ({e(d['prop'].get('origem',''))}). {e(d['prop'].get('nota',''))} "
                    f"Retorno líquido de {pct(a['ret'])} ao ano, volatilidade de {pct(a['vol'])}, custo médio de {pct(a['custo'],2)} ao ano."))
    return pagina(n, "Proposta", ctx, corpo, "Alocação estratégica proposta", "Os pesos-alvo de longo prazo, as bandas que o perfil e o cliente permitem e o papel de cada classe.")


def p_movimentos(d: dict, n: int) -> str:
    ctx, w = d["ctx"], d["w"]
    ref = d["atual_w"] if d["atual_w"] is not None else ctx.w_modelo
    nome_ref = "carteira atual" if d["atual_w"] is not None else "modelo do perfil"
    delta = {cid: float((w[i] - ref[i]) * 100.0) for i, cid in enumerate(C.IDS)}
    graf = G.barras_pp(delta, altura_linha=20)
    passos = d["trans"]["passos"]
    linhas = [[p["janela"], sw(p["classe"]) + e(p["curto"]), f"{p['acao']} {num(abs(p['pp']),1)} p.p. · {brl(p['reais'])}", f"{p['parcelas']}x de {brl(p['por_parcela'])}" if p["parcelas"] > 1 else "à vista"] for p in passos]
    como = []
    for p in passos:
        if p["nota"] not in como:
            como.append(p["nota"])
    corpo = (f'<h2>Variação em pontos percentuais contra a {nome_ref}</h2>{graf}'
             f'<h2>Plano de transição · giro de {pct(d["trans"]["giro"],0)} da carteira</h2>'
             + tabela(["Quando", "Classe", "Movimento", "Execução"], linhas, (), compacta=True)
             + "<h2>Como executar</h2><ul class='l'>" + "".join(f"<li>{e(c)}</li>" for c in como[:4]) + "</ul>"
             + (nota("Dia de choque nos juros: as parcelas de renda fixa travada em taxa esperam o balcão assentar.", "aviso") if ctx.mercado.em_choque else ""))
    return pagina(n, "Movimentos", ctx, corpo, "Da carteira de hoje à carteira alvo", "O que aumentar, o que reduzir e em que ritmo. Aumentar e reduzir são movimentos de carteira; a decisão final é do assessor.")


def p_risco(d: dict, n: int) -> str:
    ctx, w, a = d["ctx"], d["w"], d["a"]
    curva = sorted((x["vol"], x["ret"]) for x in d["fronteira"])
    pts = [{"nome": "Proposta", "vol": a["vol"], "ret": a["ret"], "cor": G.INK, "destaque": True, "dx": 10, "dy": -9},
           {"nome": "Modelo do perfil", "vol": d["modelo_a"]["vol"], "ret": d["modelo_a"]["ret"], "cor": G.CINZA, "dx": 10, "dy": 14},
           {"nome": "100% CDI líquido", "vol": 0.003, "ret": ctx.bench, "cor": G.OURO, "dx": 10, "dy": -8}]
    if d["atual_a"]:
        pts.append({"nome": "Carteira atual", "vol": d["atual_a"]["vol"], "ret": d["atual_a"]["ret"], "cor": G.VERMELHO, "dx": -10, "dy": 14})
    graf = G.fronteira(curva, pts, altura=235)
    idx = [i for i in range(len(C.IDS)) if w[i] > 0.005]
    rot = [C.CLASSES[i].curto for i in idx]
    cands = [[f"{c['cod']} · {c['nome']}", pct(c["ret"], 1), pct(c["vol"], 1)] for c in d["cands"] if c.get("w") is not None]
    cands.append(["Proposta adotada", pct(a["ret"], 1), pct(a["vol"], 1)])
    corpo = (f'<h2>Retorno contra risco</h2>{graf}'
             f'<h2>De onde vem o risco</h2>{G.barras_duplas(rot, [float(w[i]) for i in idx], [float(a["rc"][i]) for i in idx], "peso na carteira", "parte do risco", linha=21)}'
             f'<div class="peq">Número efetivo de apostas independentes: <b>{num(a["enb"],1)}</b>. Quanto mais perto do número de classes, mais diversificado.</div>'
             f'<h2>Alternativas consideradas</h2>{tabela(["Carteira", "Retorno líquido", "Volatilidade"], cands, (1, 2), compacta=True)}')
    return pagina(n, "Risco e retorno", ctx, corpo, "O que se paga de risco por cada ponto de retorno",
                  f"Fronteira eficiente dentro das bandas do cliente. Volatilidade pelo histórico de 5 anos de proxies de cada classe, com nível de juros e cauda gorda tratados à parte.")


def p_projecao(d: dict, n: int) -> str:
    ctx, a = d["ctx"], d["a"]
    sim = a["sim"]
    graf = G.fan(sim, ctx.plano.meta, altura=290, pl=ctx.plano.pl)
    fr = sim["final_real"]
    fr_t = sim["faixa_real"]
    linhas = [["Pessimista (1 em 20 abaixo)", mi(fr[5]), "P5"], ["Abaixo do usual", mi(fr[25]), "P25"], ["Mediana", mi(fr[50]), "P50"],
              ["Acima do usual", mi(fr[75]), "P75"], ["Otimista (1 em 20 acima)", mi(fr[95]), "P95"]]
    probs = [["Chance de atingir a meta", prob(sim["p_meta"], 0) if sim["p_meta"] is not None else "sem meta"],
            ["Chance de perder poder de compra no horizonte", prob(sim["p_perde_poder_compra"], 1)],
            ["Janelas de 12 meses com retorno negativo", prob(sim["p_neg_12m"], 1)],
            ["Janelas de 12 meses abaixo da inflação", prob(sim["p_abaixo_ipca_12m"], 1)],
            ["Pior janela de 12 meses (1 em 20)", pct(sim["var95_12m"], 1)],
            ["Maior queda de pico a vale (1 em 20)", pct(sim["mdd_p95"], 1)]]
    anos = int(sim["anos"])
    marcos = sorted({y for y in (1, 2, 3, 5, 7, 10, anos) if 1 <= y <= anos})
    caminho = [[f"{y} ano{'s' if y > 1 else ''}", mi(fr_t[5][12 * y]), mi(fr_t[50][12 * y]), mi(fr_t[95][12 * y])] for y in marcos]
    fluxo = ""
    if ctx.plano.aporte_mensal:
        fluxo = f" Aportes de {brl(ctx.plano.aporte_mensal)} por mês (corrigidos pela inflação)."
    corpo = (f'<h2>Patrimônio em reais de hoje, {num(sim["n"],0)} trajetórias</h2>{graf}'
             f'<div class="fonte">Faixas: 5% a 95% (claro) e 25% a 75% (médio); linha escura = mediana. Retorno mensal com cauda gorda (t de Student), correlações do histórico, juros reinvestidos com risco de nível.{e(fluxo)}</div>'
             f'<div class="duas"><div><h2>Patrimônio final (R$ de hoje)</h2>{tabela(["Cenário", "Valor", "Faixa"], linhas, (1,), compacta=True)}</div>'
             f'<div><h2>Probabilidades</h2>{tabela(["Medida", "Valor"], probs, (1,), compacta=True)}</div></div>'
             + "<h2>Patrimônio ao longo do tempo (R$ de hoje)</h2>" + tabela(["Prazo", "Pessimista (P5)", "Mediana", "Otimista (P95)"], caminho, (1, 2, 3), compacta=True)
             + nota(f"<b>Retorno anual composto mediano:</b> {pct(sim['cagr_mediano'])} nominal ({pct(sim['cagr_real_mediano'])} acima da inflação); faixa de 5% a 95%: {pct(sim['cagr_p5'])} a {pct(sim['cagr_p95'])}. "
                    f"Para chegar à meta o plano exige {pct(a['retorno_necessario'])} ao ano." if a["retorno_necessario"] is not None else
                    f"<b>Retorno anual composto mediano:</b> {pct(sim['cagr_mediano'])} nominal ({pct(sim['cagr_real_mediano'])} acima da inflação)."))
    return pagina(n, "Projeção", ctx, corpo, "Para onde o patrimônio pode ir", "Simulação de Monte Carlo com semente fixa: mesma entrada, mesmo resultado. É faixa de possibilidades, não previsão.")


def p_estresse(d: dict, n: int) -> str:
    ctx, a = d["ctx"], d["a"]
    est = a["estresse"]
    por_id = {c.id: c for c in K.todos(ctx.cenario_hoje)}
    linhas = []
    for r in est["cenarios"]:
        c = por_id.get(r["id"])
        linhas.append([f"<b>{e(r['nome'])}</b><br><span class='peq'>{e(r['historia'])}</span>", _resumo_choque(c) if c else "", pcts(r["total"], 1), meses(r["meses_para_recuperar"])])
    lim = ctx.queda_limite
    pior = est["pior"]
    texto = ""
    if pior:
        st = "ok" if abs(pior["total"]) <= lim else "fora"
        texto = nota(f"<b>Pior cenário adverso: {e(pior['nome'])}, {pct(pior['total'],1)}.</b> O limite de queda do cliente é {pct(lim,0)}; "
                     f"{'cabe' if st=='ok' else 'NÃO cabe'}. O carrego da carteira repõe a perda em cerca de {meses(pior['meses_para_recuperar'])}.", "" if st == "ok" else "fora")
    corpo = (f"{G.barras_estresse([{'nome': r['nome'], 'total': r['total']} for r in est['cenarios']])}{texto}"
             + tabela(["Cenário", "Choque aplicado", "Impacto", "Recupera em"], linhas, (2, 3), compacta=True)
             + '<div class="fonte">Choques são hipóteses da mesa (instantâneos, a mercado), calibrados na ordem de grandeza de crises recentes; não são previsões.</div>')
    return pagina(n, "Estresse", ctx, corpo, "E se o pior acontecer?", "Quanto a carteira perde, de uma vez, em cada cenário adverso, e quanto tempo o carrego leva para repor.")


def _resumo_choque(c) -> str:
    p = []
    if c.d_pre: p.append(f"pré {c.d_pre:+.0f} bps")
    if c.d_real: p.append(f"juro real {c.d_real:+.0f} bps")
    if c.d_spread: p.append(f"spread {c.d_spread:+.0f} bps")
    if c.usd: p.append(f"dólar {c.usd:+.0f}%")
    if c.ibov: p.append(f"bolsa BR {c.ibov:+.0f}%")
    if c.ifix: p.append(f"FIIs {c.ifix:+.0f}%")
    if c.spx: p.append(f"bolsa EUA {c.spx:+.0f}%")
    if c.ouro: p.append(f"ouro {c.ouro:+.0f}%")
    if c.cripto: p.append(f"cripto {c.cripto:+.0f}%")
    return ", ".join(p).replace(".", ",")


def p_alinhamento(d: dict, n: int) -> str:
    ctx, ver = d["ctx"], d["ver"]
    linhas = []
    for c in d["checks"]:
        if c["id"] == "mercado" and c["status"] == "ok":
            continue
        if c["status"] == "ok":
            texto = f'<b>{e(c["titulo"])}</b>'
        else:
            texto = f'<b>{e(c["titulo"])}</b><br><span class="peq">{e(c["leitura"])}</span>'
            if c["acao"] and c["status"] in ("fora", "atencao"):
                texto += f'<br><span class="peq">→ <b>{e(c["acao"])}</b></span>'
        linhas.append([chip(c["status"]), texto, c["valor"], c["limite"]])
    cont = ver["contagem"]
    corpo = (f'<p>{chip(ver["status"], ver["veredito"])} &nbsp;<span class="peq">{cont["ok"]} alinhados · {cont["atencao"]} de atenção · {cont["fora"]} fora · {cont["info"]} informativos</span></p>'
             + tabela(["Status", "Checagem, leitura e ação", "Valor", "Limite"], linhas, (), compacta=True))
    return pagina(n, "Alinhamento", ctx, corpo, "A estratégia está alinhada ao cliente?", "A régua da mesa: cada checagem contra o que o cliente declarou e o que o perfil permite.")


def p_fiscal_liquidez(d: dict, n: int) -> str:
    ctx, w, a = d["ctx"], d["w"], d["a"]
    tr = {"caixa": "IR regressivo (15% a 22,5%)", "isento": "isento (pessoa física)", "regressivo": "IR regressivo (22,5% a 15%)", "fundo_cota": "come-cotas 15% e IR no resgate",
          "previdencia": "tabela da previdência (10% a 35%)", "ganho_15": "15% sobre o ganho", "fii": "rendimento isento; 20% sobre o ganho"}
    bl = {"excluido": "fora da base", "diferido": "diferido", "neutralizado": "neutralizado pela retenção", "exposto": "entra na base"}
    linhas = [[c.curto, pct(w[i], 1), tr.get(c.tributo, c.tributo), bl[c.blindagem]] for i, c in enumerate(C.CLASSES) if w[i] > 0.003]
    mp = a["irpfm"]
    ks = "".join([kpi("Protegido do IRPFM", pct(mp["protegido"], 0), "isentos, previdência e retenção", True), kpi("Fora da base", pct(mp["excluido"], 0), "LCA, LCI, CRA, CRI, incentivadas"),
                  kpi("Diferido", pct(mp["diferido"], 0), "previdência"), kpi("Exposto", pct(mp["exposto"], 0), "renda variável, FIIs, exterior")])
    liq = G.escada_liquidez(a["liq"])
    ev = "".join(f'<li><b>{e(x["descricao"])}</b> · {brl(x["valor_futuro"])} no mês {x["mes"]}: ' + "; ".join(f'{e(m["quando"])} {e(m["onde"])}' for m in x["marcos"]) + "</li>" for x in d["esteira"])
    reserva = CL.reserva_necessaria(ctx.ficha)
    corpo = (f'<h2>Mapa fiscal e IRPFM (Lei 15.270/2025)</h2><div class="kpis">{ks}</div>'
             + tabela(["Classe", "Peso", "Imposto", "IRPFM"], linhas, (1,))
             + f'<div class="fonte">Alíquotas simplificadas; confirmar com o tributarista. O retorno líquido das premissas já desconta o imposto no horizonte.</div>'
             + f'<h2>Escada de liquidez</h2>{liq}<div class="fonte">Quanto da carteira vira dinheiro em D+1, até D+5, D+30, D+90 e acima.</div>'
             + (f"<p style='margin-top:2.5mm'>Reserva de liquidez do cliente: <b>{brl(reserva)}</b>; caixa na proposta: <b>{brl(w[C.IDS.index('caixa')] * ctx.plano.pl)}</b>.</p>" if reserva else "")
             + (f"<h2>Saídas grandes previstas</h2><ul class='l'>{ev}</ul>" if ev else ""))
    return pagina(n, "Fiscal e liquidez", ctx, corpo, "Imposto e liquidez", "O que fica para o cliente depois do imposto e como o dinheiro vira caixa quando precisar.")


def p_implementacao(d: dict, n: int) -> str:
    ctx = d["ctx"]
    tr = d["trilha"]
    graf = G.empilhado(tr)
    linhas = [[b["curto"], pct(b["alvo"], 1), pct(b["min"], 1), pct(b["max"], 1)] for b in d["regras"]["bandas"]]
    gat = "".join(f"<li>{e(g)}</li>" for g in d["regras"]["gatilhos"])
    riq = tr["riqueza"]
    corpo = (f'<h2>Composição esperada ao longo dos anos</h2>{graf}'
             f'<div class="fonte">Alvo mantido; antes de cada saída grande o dinheiro vai para o caixa. Patrimônio esperado (nominal): {mi(riq[0])} hoje, {mi(riq[len(riq)//2])} no meio do prazo e {mi(riq[-1])} no fim.</div>'
             f'<div class="duas"><div><h2>Faixas de rebalanceamento</h2>{tabela(["Classe", "Alvo", "De", "Até"], linhas, (1, 2, 3))}</div>'
             f'<div><h2>Quando revisar</h2><ul class="l">{gat}</ul></div></div>')
    return pagina(n, "Implementação", ctx, corpo, "Como manter a estratégia viva", "Uma alocação não termina na entrega: ela é acompanhada por faixas e gatilhos definidos de antemão.")


def p_riscos(d: dict, n: int) -> str:
    ctx, w, a = d["ctx"], d["w"], d["a"]
    g = lambda *ids: sum(w[C.IDS.index(i)] for i in ids)
    riscos = []
    if a["cdi_dep"] > 0.3:
        riscos.append(["Queda do CDI mais rápida que a curva", f"{pct(a['cdi_dep'],0)} da carteira rende CDI e reaplica a taxas menores.", "Travar parte em IPCA+ enquanto a taxa está alta."])
    if g("pos_isenta", "ipca_isenta", "pre_isenta", "pos_trib") > 0.2:
        riscos.append(["Crédito privado e FGC", f"Cerca de {a['emissores_fgc']} emissores para ficar sob o FGC; calote em um emissor perde o que passa do limite.", "Diversificar emissores, limitar cada um, acompanhar rating."])
    if a["travado"] > 0.1:
        riscos.append(["Marcação a mercado da taxa travada", "Se os juros abrirem, o papel longo perde valor no curto prazo; no vencimento o carrego se mantém.", "Casar vencimentos com os usos do dinheiro."])
    if a["usd"] > 0.03:
        riscos.append(["Câmbio", f"{pct(a['usd'],0)} em ativos dólar: o dólar pode cair e tirar retorno em reais.", "Dimensionar pelo gasto futuro em dólar, não pela aposta."])
    if a["rv"] > 0.05:
        riscos.append(["Bolsa e FIIs", "Retorno esperado de baixa confiança e quedas de dois dígitos no caminho.", "Entrada escalonada e rebalanceamento por faixas."])
    if g("mm", "vgbl") > 0.03:
        riscos.append(["Escolha de gestor", "A diferença entre gestores é maior que a diferença entre classes.", "Seleção com histórico longo, taxa e consistência."])
    riscos.append(["Premissas de mercado", "Taxas, inflação e prêmios mudam; o retorno esperado é ordem de grandeza.", "Revisar a cada semestre e em choques."])
    riscos.append(["Mudança tributária", "O imposto mínimo e outras regras podem mudar o líquido.", "Confirmar com o tributarista; revisar o mapa fiscal."])
    gloss = [
        ("CDI", "taxa de juro de referência do mercado; renda fixa pós-fixada paga uma porcentagem dela."), ("IPCA", "inflação oficial; IPCA+ é inflação mais um juro fixo."),
        ("Pré-fixado", "taxa de juro combinada na compra."), ("LCA/LCI/CRA/CRI", "títulos de crédito agro ou imobiliário, isentos de IR para pessoa física."),
        ("Debênture incentivada", "título de empresa para infraestrutura, isento de IR para pessoa física."), ("FGC", "fundo garantidor: cobre até R$ 250 mil por CPF e por instituição."),
        ("Volatilidade", "quanto o retorno oscila ao ano; é a medida de risco usada aqui."), ("Monte Carlo", "milhares de trajetórias simuladas para ver a faixa de resultados."),
        ("P5 / P50 / P95", "pior 5%, mediana e melhor 5% dos resultados simulados."), ("Queda máxima", "maior perda do pico ao vale."),
        ("Come-cotas", "IR de 15% ou 20% que o fundo recolhe duas vezes ao ano."), ("IRPFM", "imposto mínimo da Lei 15.270/2025 para rendas altas."),
        ("Rebalancear", "voltar os pesos ao alvo quando saem das faixas."), ("Duration", "prazo médio de um título; mede a sensibilidade a juros."),
        ("UCITS", "fundos europeus, usados para exposição a bolsas do mundo."), ("p.p. e bps", "ponto percentual; 100 pontos-base (bps) = 1 p.p."),
    ]
    corpo = ("<h2>Riscos da proposta e como acompanhar</h2>" + tabela(["Risco", "O que acontece", "Como mitigar"], riscos, ())
             + "<h2>Termos deste relatório</h2><div class='gl'>" + "".join(f"<div><b>{e(t)}</b>: {e(x)}</div>" for t, x in gloss) + "</div>")
    return pagina(n, "Riscos e termos", ctx, corpo, "Riscos, gatilhos e glossário", "O que pode dar errado, o que fazer se der e o significado de cada termo.")


def p_metodologia(d: dict, n: int) -> str:
    ctx = d["ctx"]
    m = ctx.mercado
    fontes = tabela(["Fonte", "Data"], [[r, dmy(dt_) or "—"] for r, dt_ in m.fontes], ())
    corpo = (f'<div class="duas"><div><h2>Como foi calculado</h2>'
             "<p><b>Premissas.</b> Renda fixa sai da curva DI, da NTN-B e dos spreads de debêntures; bolsa, do juro real mais prêmio e da TIR mediana; ouro e cripto são convenção declarada. As visões do assessor entram como deslocamento visível.</p>"
             "<p><b>Imposto.</b> Cada classe usa a tabela do seu veículo (regressiva, come-cotas, previdência, 15% sobre ganho, FIIs). O retorno é líquido no horizonte.</p>"
             "<p><b>Risco.</b> Histórico semanal de 5 anos de proxies por classe, correlação encolhida, mais risco de nível do CDI e cauda gorda.</p>"
             "<p><b>Otimização.</b> Média-variância convexa, dentro das bandas do perfil e do cliente, ancorada no modelo do perfil para evitar soluções extremas.</p>"
             "<p><b>Projeção.</b> Monte Carlo de 10 mil trajetórias mensais com semente fixa; fluxos corrigidos pelo IPCA; rebalanceamento anual.</p>"
             "<p><b>Estresse.</b> Choques instantâneos hipotéticos aplicados por duration e sensibilidade de cada classe.</p></div>"
             f"<div><h2>Fontes e datas</h2>{fontes}</div></div>"
             + nota("<b>Limitações.</b> Previsões erram. Os números são estimativas condicionadas às premissas e ao histórico recente; não há garantia de resultado. "
                    "Taxas de renda fixa de balcão variam por emissor e prazo: confirme antes de executar. O cálculo não considera custos de corretagem e custódia além dos custos médios por classe.", "aviso")
             + nota("<b>Aviso.</b> Material de trabalho do assessor de investimentos para apoiar a conversa com o cliente. Não é oferta nem recomendação de investimento. "
                    "A adequação ao perfil do investidor (Resolução CVM 30) e a recomendação final são responsabilidade do assessor e da instituição (Resolução CVM 178). "
                    "Rentabilidade passada ou esperada não é garantia de rentabilidade futura. Premissas fiscais devem ser confirmadas com o tributarista. "
                    "Documento contém dados pessoais do cliente: guardar conforme a LGPD."))
    return pagina(n, "Metodologia", ctx, corpo, "Metodologia, fontes e avisos", "Como cada número foi produzido, de onde vem e o que o relatório não promete.")


# ------------------------------------------------------------------------------------------------------
def html_do_relatorio(d: dict) -> str:
    ctx = d["ctx"]
    paginas = [p_capa(d)]
    for fn in (p_resumo, p_ficha, p_cenario, p_premissas, p_diagnostico, p_proposta, p_movimentos, p_risco, p_projecao,
               p_estresse, p_alinhamento, p_fiscal_liquidez, p_implementacao, p_riscos, p_metodologia):
        paginas.append(fn(d, len(paginas) + 1))
    titulo = f"Alocação de ativos · {ctx.ficha['nome']}"
    return f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>{e(titulo)}</title><style>{CSS}</style></head><body>{"".join(paginas)}</body></html>'


def gerar(nome: str, curva: str = "viva", n_sim: int = 10000, pdf: bool = True) -> dict:
    d = montar_dados(nome, curva=curva, n_sim=n_sim)
    html = html_do_relatorio(d)
    pasta = CL.pasta(nome) / "saida"
    pasta.mkdir(parents=True, exist_ok=True)
    base = f"{d['hoje']:%Y-%m-%d}_{CL.slug(nome)}_asset-allocation_v{d['prop']['versao']}"
    arq_html = pasta / f"{base}.html"
    arq_html.write_text(html, encoding="utf-8")
    out = {"html": arq_html, "pdf": None, "veredito": d["ver"]["veredito"]}
    if pdf:
        arq_pdf = pasta / f"{base}.pdf"
        if not CHROME.exists():
            raise FileNotFoundError(f"Chrome nao encontrado em {CHROME}: o PDF precisa dele (o HTML foi gravado em {arq_html})")
        with tempfile.TemporaryDirectory() as perfil:
            cmd = [str(CHROME), "--headless=new", "--disable-gpu", "--no-sandbox", f"--user-data-dir={perfil}", "--no-pdf-header-footer",
                   "--run-all-compositor-stages-before-draw", f"--print-to-pdf={arq_pdf}", arq_html.as_uri()]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if not arq_pdf.exists() or arq_pdf.stat().st_size < 5_000:
            raise RuntimeError(f"o Chrome nao gerou o PDF: {r.stderr[-400:]}")
        out["pdf"] = arq_pdf
    return out
