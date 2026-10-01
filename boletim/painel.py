"""Painel HTML do boletim: a leitura do pregao em uma pagina, que a sessao publica como Artifact.

Segue o formato branco e azul do Douglas (pagina clara, cards brancos, azul institucional,
verde e vermelho so para sinal) e e deliberadamente claro: nao ha versao escura. Tudo e
gerado aqui, sem biblioteca externa: graficos em SVG, barras em CSS, um script curto para a
dica de valor e para as abas. A sessao so troca `[[LEITURA_DA_MESA]]` pela leitura dela.

Nada e calculado aqui. Os numeros vem do resumo do pregao (boletim/resumo.py) e do historico
compacto; quando um bloco do pregao ainda nao saiu na B3 (aluguel e posicoes em aberto saem de
madrugada), a pagina mostra o do pregao anterior com a data dele escrita no card.

Cores dos graficos (validadas com o validador de paleta para daltonismo, superficie branca):
  serie principal e calls  #1c5c99   (um passo mais claro do azul institucional, dentro da faixa)
  segunda serie e puts     #c2702a
  positivo e negativo      #0a7d4f / #b3372f, sempre com o sinal escrito ao lado
"""

from __future__ import annotations

import html
import math
from datetime import date

MARCADOR_LEITURA = "[[LEITURA_DA_MESA]]"
DIAS = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo")
MESES = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
LETRAS = "FGHJKMNQUVXZ"

ROTULO_INVESTIDOR = {"estrangeiro": "Estrangeiro", "institucional": "Institucional (fundos)",
                     "pessoa_fisica": "Pessoa física", "inst_financeira": "Bancos e corretoras", "outros": "Outros"}
ROTULO_SINAL = {
    "volume_anormal": "Volume", "aluguel_variacao": "Aluguel", "pressao_vendida": "Pressão vendida",
    "zeragem_de_vendidos": "Vendidos zerando", "aluguel_alto": "Aluguel alto", "aluguel_caro": "Aluguel caro",
    "opcoes_parede": "Parede de opções", "opcoes_posicao": "Posição em opções", "etf_premio": "ETF x cota",
    "etf_cotas": "Cotas de ETF", "provento": "Provento", "subscricao": "Subscrição", "lista_do_dia": "Listas do dia",
    "fluxo_estrangeiro": "Fluxo", "posicao_em_aberto": "Posição em aberto", "juros": "Juros",
    "previa_indice": "Prévia de índice", "informativo": "Comunicado", "after_market": "After market",
    "paridade": "Paridade", "rf_abertura": "Crédito: taxa abriu", "rf_premio_alto": "Crédito: prêmio alto",
    "rf_giro": "Crédito: giro",
}
NOME_INDICE = {"IBOVESPA": "Ibovespa", "SMALL CAP": "Small caps", "IFINANCEIRO": "Financeiro",
               "UTILITIES": "Utilidade pública", "IMOBILIARIO": "Imobiliário", "I DIVIDENDOS": "Dividendos",
               "IEE": "Energia elétrica", "IMATBASICOS": "Materiais básicos", "IFIX": "Fundos imobiliários", "BDRX": "BDRs"}
NOME_GRUPO = {"construtoras": "Construtoras", "utilities": "Utilities", "bancos": "Bancos", "commodities": "Commodities",
              "consumo_e_distribuicao": "Consumo e distribuição", "etfs": "ETFs"}
NOME_PENDENTE = {
    "TradeInformationConsolidated": "negócios do pregão", "TradeInformationConsolidatedAfterHours": "after market",
    "InstrumentsConsolidated": "cadastro de instrumentos", "DerivativesOpenPosition": "posições em aberto",
    "BTBLendingOpenPosition": "saldo de aluguel", "BTBLoanBalance": "empréstimos do dia", "BTBTrade": "aluguel por corretora",
    "AnalyticalFramework2": "quadro de posições em aberto", "SharesInvesVolum": "fluxo por investidor",
    "Trade": "negócios de renda fixa",
}
ROTULO_RF = {"deb_incentivada": "Debêntures incentivadas", "cri": "CRI", "cra": "CRA"}

CSS = """
/* Painel do boletim: resumo no topo, detalhe por secao; uma coluna no celular, duas no computador */
:root{
  color-scheme: light;
  --bg:#f7f8fa; --card:#fff; --ink:#1a2233; --mut:#5b6474; --line:#e3e7ee; --linha2:#eef1f6;
  --acc:#0f4c81; --pos:#0a7d4f; --neg:#b3372f; --hl:#fff8e6; --ouro:#b8860b;
  --s1:#1c5c99; --s2:#c2702a; --de:#c3cad5; --trilho:#e6edf5; --grade:#edf0f4; --info:#f5f8fc;
  --sans:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;
  --mono:Consolas,'SF Mono',Menlo,monospace;
}
*{box-sizing:border-box}
body{font:15px/1.55 var(--sans);color:var(--ink);background:var(--bg);margin:0;padding-inline:18px;
  padding-block:22px 48px;-webkit-text-size-adjust:100%}
.wrap{max-width:1180px;margin:0 auto;display:flex;flex-direction:column;gap:14px}
h1,h2,h3,h4,p{margin:0}
h1{font-size:25px;line-height:1.2;letter-spacing:-.01em;text-wrap:balance}
h1 small{font-size:15px;font-weight:400;color:var(--mut);margin-left:6px;white-space:nowrap}
h2{font-size:18px;color:var(--acc);text-wrap:balance}
h3{font-size:15px}
h4{font-size:12px;text-transform:uppercase;letter-spacing:.5px;color:var(--mut);font-weight:600}
a{color:var(--acc);text-underline-offset:2px}
a:focus-visible,button:focus-visible,summary:focus-visible,[tabindex]:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
.sub{color:var(--mut);font-size:14px;margin-top:4px}
.marca{font-size:12px;letter-spacing:.6px;text-transform:uppercase;color:var(--acc);font-weight:700;margin-bottom:4px}
.selo{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.5px;color:#fff;background:var(--acc);
  border-radius:4px;padding:2px 8px;margin-right:6px;vertical-align:1px}
.selo.parcial{background:var(--ouro)}
.code{font-family:var(--mono);font-weight:700;color:var(--acc);white-space:nowrap}
.pos{color:var(--pos)} .neg{color:var(--neg)} .mut{color:var(--mut)}
.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}

/* indicadores do topo */
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
@media (max-width:760px){.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:11px 13px;min-width:0}
.kpi .rot{font-size:11.5px;color:var(--mut);letter-spacing:.2px}
.kpi .val{font-size:21px;font-weight:650;line-height:1.25;letter-spacing:-.01em}
.kpi .val small{font-size:12px;font-weight:500;color:var(--mut);margin-left:2px}
.kpi .dl{font-size:13px;font-weight:600}
.kpi .pe{font-size:11.5px;color:var(--mut)}

/* indice das secoes */
.indice{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--bg);padding-block:8px;
  display:flex;gap:6px;overflow-x:auto;scrollbar-width:none;border-bottom:1px solid var(--line)}
.indice::-webkit-scrollbar{display:none}
.indice a{flex:none;font-size:13px;text-decoration:none;color:var(--mut);background:var(--card);border:1px solid var(--line);
  border-radius:999px;padding:4px 12px}
.indice a:hover{color:var(--acc);border-color:var(--acc)}

/* cards e grades */
section{display:flex;flex-direction:column;gap:10px;scroll-margin-top:56px}
section>h2{margin-top:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;min-width:0}
.card-destaque{border:2px solid var(--acc);background:linear-gradient(#fff,#fbfdff)}
.card>h3{margin-bottom:2px}
.card>h3+.desc{margin-bottom:10px}
.desc{color:var(--mut);font-size:13px}
.g2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,430px),1fr));gap:14px;align-items:start}
.g3{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,270px),1fr));gap:14px}
.g2>:last-child:nth-child(odd){grid-column:1/-1}
.duo{display:grid;grid-template-columns:minmax(0,1.85fr) minmax(0,1fr);gap:18px;align-items:start}
.col{display:flex;flex-direction:column;gap:14px;min-width:0}
@media (max-width:900px){.duo{grid-template-columns:minmax(0,1fr)}}
.explicacao{background:var(--info);border-left:3px solid var(--acc);border-radius:4px;padding:8px 12px;font-size:13.5px;margin-top:10px}
.ref{color:var(--mut);font-size:12px}
.tag{display:inline-block;font-size:11px;font-weight:600;color:var(--acc);background:var(--info);border:1px solid #d5e2f1;
  border-radius:4px;padding:0 6px;white-space:nowrap}
.tag.velho{color:#7a5a00;background:var(--hl);border-color:#ecd9a0}
.leitura{font-size:16px;line-height:1.6;max-width:76ch}
.leitura p+p{margin-top:10px}
.leitura ul{margin:8px 0 0;padding-left:20px}
.vazio{color:var(--mut);font-size:14px}

/* tabelas */
.overx{overflow-x:auto;margin-top:6px}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{border-bottom:1px solid var(--linha2);padding:6px 8px;text-align:left;vertical-align:middle}
th{font-size:11.5px;font-weight:600;color:var(--mut);letter-spacing:.2px;border-bottom:1px solid var(--line);
  white-space:nowrap;background:transparent}
td,th{font-variant-numeric:tabular-nums}
tbody tr:last-child td{border-bottom:0}
.overx th:first-child,.overx td:first-child{position:sticky;left:0;background:var(--card);z-index:1}
.overx tr.grupo td:first-child{background:var(--info)}
tr.grupo td{background:var(--info);font-size:11.5px;font-weight:700;color:var(--acc);letter-spacing:.4px;text-transform:uppercase;
  padding-block:4px}
td.txt{white-space:normal;min-width:150px}
td .peq{display:block;font-size:11.5px;color:var(--mut);font-weight:400}

/* barras em celula */
.dv{display:inline-grid;grid-template-columns:1fr 1fr;width:60px;height:8px;vertical-align:middle;margin-right:8px;
  background:linear-gradient(var(--de),var(--de)) center/1px 100% no-repeat}
.dv i{display:block;height:8px}
.dv .e{justify-self:end;background:var(--neg);border-radius:3px 0 0 3px}
.dv .d{justify-self:start;background:var(--pos);border-radius:0 3px 3px 0}
.mt{display:inline-block;width:64px;height:8px;border-radius:4px;background:var(--trilho);vertical-align:middle;
  margin-right:8px;position:relative;overflow:hidden}
.mt i{display:block;height:8px;background:var(--s1);border-radius:4px}
.mt.dois i{background:var(--s2)}
.bh{display:grid;grid-template-columns:minmax(64px,auto) minmax(0,1fr) auto;gap:4px 10px;align-items:center;font-size:13.5px}
.bh .tr{height:10px;border-radius:5px;background:var(--trilho);overflow:hidden}
.bh .tr i{display:block;height:10px;background:var(--s1);border-radius:5px}
.bh .tr.dois i{background:var(--s2)}
.bh .v{font-variant-numeric:tabular-nums;white-space:nowrap;text-align:right}
.bh .v small{color:var(--mut);font-size:11.5px;margin-left:4px}
.pilha{display:flex;height:10px;border-radius:5px;overflow:hidden;gap:2px;background:var(--card)}
.pilha i{display:block;height:10px}

/* sinais */
.sinais{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}
.sinais li{display:grid;grid-template-columns:128px minmax(0,1fr);gap:4px 12px;font-size:14px;align-items:baseline}
.sinais .tp{font-size:11.5px;font-weight:700;color:var(--acc);letter-spacing:.2px}
.sinais .ref{display:block}
@media (max-width:560px){.sinais li{grid-template-columns:minmax(0,1fr)}}
details>summary{cursor:pointer;color:var(--acc);font-size:13.5px;font-weight:600;margin-top:10px}
details[open]>summary{margin-bottom:8px}

/* graficos */
figure{margin:0;overflow-x:auto}
svg.graf{min-width:500px}
figcaption{font-size:12px;color:var(--mut);margin-top:6px}
svg{display:block;width:100%;height:auto;overflow:visible}
svg text{font-family:var(--sans);font-size:11px;fill:var(--mut)}
svg .eixo{stroke:var(--de);stroke-width:1}
svg .gr{stroke:var(--grade);stroke-width:1}
svg .rot{fill:var(--ink);font-weight:600}
svg [data-tip]{cursor:default}
svg [data-tip]:hover,svg [data-tip]:focus{opacity:.78;outline:none}
.legenda{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:12.5px;color:var(--mut);margin-bottom:6px}
.legenda i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.legenda i.l{height:2px;width:14px;border-radius:0;vertical-align:3px}
#dica{position:fixed;z-index:20;pointer-events:none;background:#16202f;color:#fff;font-size:12.5px;line-height:1.45;
  padding:7px 10px;border-radius:6px;max-width:260px;box-shadow:0 4px 14px rgba(20,30,50,.18)}
#dica b{display:block;font-size:13px}

/* abas */
.abas{display:flex;gap:6px;overflow-x:auto;padding-bottom:2px;scrollbar-width:none}
.abas::-webkit-scrollbar{display:none}
.abas button{flex:none;font:600 13px var(--sans);color:var(--mut);background:var(--card);border:1px solid var(--line);
  border-radius:6px;padding:5px 11px;cursor:pointer}
.abas button[aria-selected="true"]{color:#fff;background:var(--acc);border-color:var(--acc)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin-bottom:12px}
.tile{border:1px solid var(--line);border-radius:8px;padding:8px 10px;min-width:0}
.tile .rot{font-size:11.5px;color:var(--mut)}
.tile .val{font-size:17px;font-weight:650}
.tile .pe{font-size:11.5px;color:var(--mut)}
.listas{display:flex;flex-direction:column;gap:4px;font-size:13.5px}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{font-size:12.5px;border:1px solid var(--line);border-radius:999px;padding:2px 10px;background:var(--card);white-space:nowrap}
.disclaimer{padding:12px 14px;background:#f2f2f2;border-radius:6px;font-style:italic;color:var(--mut);font-size:13px}
.rodape{font-size:13px;color:var(--mut)}
.rodape ul{margin:6px 0;padding-left:20px}
"""

JS = """
(function(){
  var dica=document.createElement('div');dica.id='dica';dica.hidden=true;document.body.appendChild(dica);
  function mostra(el,x,y){
    var partes=(el.getAttribute('data-tip')||'').split('|');
    dica.textContent='';
    partes.forEach(function(t,i){var n=document.createElement(i===0?'b':'div');n.textContent=t;dica.appendChild(n);});
    dica.hidden=false;
    var w=dica.offsetWidth,h=dica.offsetHeight,vw=document.documentElement.clientWidth;
    dica.style.left=Math.max(8,Math.min(x+14,vw-w-8))+'px';
    dica.style.top=(y-h-12<8?y+18:y-h-12)+'px';
  }
  function some(){dica.hidden=true;}
  document.addEventListener('pointermove',function(e){
    var el=e.target.closest?e.target.closest('[data-tip]'):null;
    if(el){mostra(el,e.clientX,e.clientY);}else{some();}
  });
  document.addEventListener('pointerdown',function(e){
    var el=e.target.closest?e.target.closest('[data-tip]'):null;
    if(el){mostra(el,e.clientX,e.clientY);}else{some();}
  });
  document.addEventListener('focusin',function(e){
    var el=e.target;if(el&&el.getAttribute&&el.getAttribute('data-tip')){var r=el.getBoundingClientRect();mostra(el,r.left+r.width/2,r.top);}
  });
  document.addEventListener('focusout',some);
  document.addEventListener('scroll',some,true);
  Array.prototype.forEach.call(document.querySelectorAll('[data-abas]'),function(grupo){
    var botoes=grupo.querySelectorAll('button[data-aba]');
    var paineis=document.querySelectorAll('[data-painel="'+grupo.getAttribute('data-abas')+'"]');
    function escolhe(id){
      Array.prototype.forEach.call(botoes,function(b){b.setAttribute('aria-selected',b.getAttribute('data-aba')===id?'true':'false');});
      Array.prototype.forEach.call(paineis,function(p){p.hidden=p.getAttribute('data-id')!==id;});
    }
    Array.prototype.forEach.call(botoes,function(b){b.addEventListener('click',function(){escolhe(b.getAttribute('data-aba'));});});
    if(botoes.length){escolhe(botoes[0].getAttribute('data-aba'));}
  });
})();
"""


# ------------------------------------------------------------------ formatos

def e(x) -> str:
    return html.escape(str(x), quote=True)


def n(v, casas: int = 2, sinal: bool = False) -> str:
    if v is None:
        return "–"
    s = f"{v:+,.{casas}f}" if sinal else f"{v:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".").replace("-", "−")


def cls(v) -> str:
    return "" if not v else ("pos" if v > 0 else "neg")


def pc(v, casas: int = 2, cor: bool = True) -> str:
    if v is None:
        return '<span class="mut">–</span>'
    return f'<span class="{cls(v) if cor else ""}">{n(v, casas, True)}%</span>'


def pb(v) -> str:
    if v is None:
        return '<span class="mut">–</span>'
    return f"{n(v, 1 if abs(v) < 10 and v != int(v) else 0, True)} pb"


def dm(iso) -> str:
    return "–" if not iso else f"{str(iso)[8:10]}/{str(iso)[5:7]}"


def compacto(v, casas: int = 1) -> str:
    """1.250.000 -> '1,3 mi'; 2.400 -> '2,4 mil'; 3.2e9 -> '3,2 bi'."""
    if v is None:
        return "–"
    a = abs(v)
    for limite, sufixo in ((1e9, " bi"), (1e6, " mi"), (1e3, " mil")):
        if a >= limite:
            return n(v / limite, casas if a / limite < 100 else 0) + sufixo
    return n(v, 0)


def nome_curto(s: str, limite: int = 34) -> str:
    s = " ".join(str(s or "").replace(" S.A.", "").replace(" S/A", "").replace(" S.A", "").split()).title()
    for a, b in ((" De ", " de "), (" Do ", " do "), (" Da ", " da "), (" E ", " e "), (" Dos ", " dos "), (" Das ", " das ")):
        s = s.replace(a, b)
    return s if len(s) <= limite else s[:limite - 1].rstrip() + "…"


def venc_futuro(tk: str):
    """DI1F29 -> date(2029, 1, 1). So para posicionar no eixo do tempo."""
    try:
        return date(2000 + int(tk[4:6]), LETRAS.index(tk[3]) + 1, 1)
    except (ValueError, IndexError):
        return None


def rotulo_futuro(tk: str) -> str:
    v = venc_futuro(tk)
    return f"{MESES[v.month - 1]}/{str(v.year)[2:]}" if v else tk


def tabela(cab: list, linhas: list, classes: list | None = None) -> str:
    """cab e linhas ja em HTML; classes por coluna ('n' alinha a direita)."""
    if not linhas:
        return '<p class="vazio">Sem dado neste pregão.</p>'
    classes = classes or [""] * len(cab)
    th = "".join(f'<th class="{c}">{h}</th>' for h, c in zip(cab, classes))
    corpo = []
    for l in linhas:
        if isinstance(l, str):
            corpo.append(l)
        else:
            corpo.append("<tr>" + "".join(f'<td class="{c}">{v}</td>' for v, c in zip(l, classes)) + "</tr>")
    return f'<div class="overx"><table><thead><tr>{th}</tr></thead><tbody>{"".join(corpo)}</tbody></table></div>'


def barra_div(v, escala: float) -> str:
    """Barra de sinal: negativa cresce para a esquerda do eixo, positiva para a direita."""
    if v is None or not escala:
        return '<span class="dv"><i class="e" style="width:0"></i><i class="d" style="width:0"></i></span>'
    w = min(100.0, abs(v) / escala * 100.0)
    esq, dire = (w, 0) if v < 0 else (0, w)
    return f'<span class="dv"><i class="e" style="width:{esq:.0f}%"></i><i class="d" style="width:{dire:.0f}%"></i></span>'


def medidor(v, teto: float, dois: bool = False) -> str:
    w = 0 if v is None or not teto else min(100.0, max(0.0, v / teto * 100.0))
    return f'<span class="mt{" dois" if dois else ""}"><i style="width:{w:.0f}%"></i></span>'


def tag_data(iso, pregao) -> str:
    """Etiqueta de data do bloco; amarela quando o dado e de outro pregao."""
    if not iso:
        return ""
    return f'<span class="tag{" velho" if iso != pregao else ""}">dados de {dm(iso)}</span>'


# ------------------------------------------------------------------ SVG

def _escala(vmin: float, vmax: float, alvo: int = 4) -> list:
    """Marcas redondas entre vmin e vmax."""
    if vmax <= vmin:
        vmax = vmin + 1.0
    bruto = (vmax - vmin) / alvo
    mag = 10 ** math.floor(math.log10(bruto))
    passo = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= bruto)
    ini = math.floor(vmin / passo) * passo
    marcas, x = [], ini
    while x <= vmax + passo * 0.501:
        marcas.append(round(x, 10))
        x += passo
    return marcas


def spark(vals: list, w: int = 76, h: int = 22) -> str:
    """Linha de tendencia sem eixo: cinza, com o ultimo ponto no azul."""
    xs = [v for v in vals if v is not None]
    if len(xs) < 3:
        return ""
    lo, hi = min(xs), max(xs)
    amp = (hi - lo) or 1.0
    pts = []
    for i, v in enumerate(vals):
        if v is None:
            continue
        pts.append((2 + i * (w - 6) / (len(vals) - 1), h - 3 - (v - lo) / amp * (h - 6)))
    d = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts))
    return (f'<svg viewBox="0 0 {w} {h}" style="width:{w}px;display:inline-block;vertical-align:middle" aria-hidden="true">'
            f'<path d="{d}" fill="none" stroke="#9aa5b5" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>'
            f'<circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="2.6" fill="#1c5c99"/></svg>')


def svg_colunas_sinal(pontos: list, unidade: str = "R$ mi") -> str:
    """Colunas positivas e negativas sobre uma linha de base. pontos = [(rotulo, valor, dica)]."""
    if not pontos:
        return ""
    W, H, ml, mr, mt, mb = 640, 230, 46, 10, 14, 26
    vals = [v for _, v, _ in pontos]
    marcas = _escala(min(0.0, min(vals)), max(0.0, max(vals)))
    lo, hi = marcas[0], marcas[-1]
    y = lambda v: mt + (hi - v) / (hi - lo) * (H - mt - mb)
    passo = (W - ml - mr) / len(pontos)
    larg = min(24.0, passo * 0.62)
    o = [f'<svg class="graf" viewBox="0 0 {W} {H}" role="img" aria-label="Saldo diário do investidor estrangeiro">']
    for m in marcas:
        o.append(f'<line class="gr" x1="{ml}" x2="{W - mr}" y1="{y(m):.1f}" y2="{y(m):.1f}"/>')
        o.append(f'<text x="{ml - 6}" y="{y(m) + 3.5:.1f}" text-anchor="end">{n(m, 0)}</text>')
    o.append(f'<line class="eixo" x1="{ml}" x2="{W - mr}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>')
    pula = max(1, round(len(pontos) / 9))
    extremos = {vals.index(max(vals)), vals.index(min(vals)), len(vals) - 1}
    for i, (rot, v, dica) in enumerate(pontos):
        x = ml + passo * i + (passo - larg) / 2
        y0, y1 = y(0), y(v)
        topo, alt = (y1, y0 - y1) if v >= 0 else (y0, y1 - y0)
        r = min(4.0, alt / 2, larg / 2)
        if v >= 0:
            d = (f"M{x:.1f},{y0:.1f} V{topo + r:.1f} Q{x:.1f},{topo:.1f} {x + r:.1f},{topo:.1f} H{x + larg - r:.1f} "
                 f"Q{x + larg:.1f},{topo:.1f} {x + larg:.1f},{topo + r:.1f} V{y0:.1f} Z")
        else:
            b = topo + alt
            d = (f"M{x:.1f},{y0:.1f} V{b - r:.1f} Q{x:.1f},{b:.1f} {x + r:.1f},{b:.1f} H{x + larg - r:.1f} "
                 f"Q{x + larg:.1f},{b:.1f} {x + larg:.1f},{b - r:.1f} V{y0:.1f} Z")
        cor = "#0a7d4f" if v >= 0 else "#b3372f"
        o.append(f'<path d="{d}" fill="{cor}" data-tip="{e(dica)}" tabindex="0"/>')
        if i in extremos:
            ty = y1 - 5 if v >= 0 else y1 + 13
            o.append(f'<text class="rot" x="{x + larg / 2:.1f}" y="{ty:.1f}" text-anchor="middle">{n(v, 0, True)}</text>')
        ultimo = len(pontos) - 1
        if i == ultimo or (i % pula == 0 and ultimo - i >= pula):
            o.append(f'<text x="{x + larg / 2:.1f}" y="{H - 8}" text-anchor="middle">{e(rot)}</text>')
    o.append(f'<text x="{ml}" y="{mt - 3}">{e(unidade)}</text></svg>')
    return "".join(o)


def svg_curva(series: list) -> str:
    """Curva de juros por vencimento. series = [(rotulo, cor, espessura, [(anos, taxa, rotulo_x, dica)])],
    a primeira e a de hoje (destacada); as demais sao contexto em cinza."""
    series = [s for s in series if len(s[3]) >= 2]
    if not series:
        return ""
    W, H, ml, mr, mt, mb = 640, 250, 44, 58, 14, 28
    xs = [p[0] for s in series for p in s[3]]
    ys = [p[1] for s in series for p in s[3]]
    marcas = _escala(min(ys) - 0.02, max(ys) + 0.02)
    lo, hi, x0, x1 = marcas[0], marcas[-1], min(xs), max(xs)
    X = lambda a: ml + (a - x0) / ((x1 - x0) or 1.0) * (W - ml - mr)
    Y = lambda v: mt + (hi - v) / (hi - lo) * (H - mt - mb)
    o = [f'<svg class="graf" viewBox="0 0 {W} {H}" role="img" aria-label="Curva de juros do DI futuro">']
    for m in marcas:
        o.append(f'<line class="gr" x1="{ml}" x2="{W - mr}" y1="{Y(m):.1f}" y2="{Y(m):.1f}"/>')
        o.append(f'<text x="{ml - 6}" y="{Y(m) + 3.5:.1f}" text-anchor="end">{n(m, 2)}</text>')
    usados = []
    for rot, cor, esp, pts in reversed(series):
        d = " ".join(f"{'M' if i == 0 else 'L'}{X(a):.1f},{Y(v):.1f}" for i, (a, v, _, _) in enumerate(pts))
        o.append(f'<path d="{d}" fill="none" stroke="{cor}" stroke-width="{esp}" stroke-linejoin="round" stroke-linecap="round"/>')
        ly = Y(pts[-1][1]) + 4
        while any(abs(ly - u) < 12 for u in usados):
            ly += 12
        usados.append(ly)
        o.append(f'<text x="{X(pts[-1][0]) + 8:.1f}" y="{ly:.1f}" class="{"rot" if esp >= 2 else ""}">{e(rot)}</text>')
    hoje = series[0]
    ultimo_x = None
    for a, v, rx, dica in reversed(hoje[3]):
        o.append(f'<circle cx="{X(a):.1f}" cy="{Y(v):.1f}" r="5" fill="{hoje[1]}" stroke="#fff" stroke-width="2" data-tip="{e(dica)}" tabindex="0"/>')
        if ultimo_x is None or ultimo_x - X(a) >= 50:
            o.append(f'<text x="{X(a):.1f}" y="{H - 9}" text-anchor="middle">{e(rx)}</text>')
            ultimo_x = X(a)
    o.append(f'<text x="{ml}" y="{mt - 3}">% ao ano</text></svg>')
    return "".join(o)


def svg_strikes(grade: list, preco, parede_call=None, parede_put=None, dor=None, unidade: str = "") -> str:
    """Posicao em aberto por strike: calls para cima, puts para baixo, o preco como linha vertical."""
    if not grade or len(grade) < 3:
        return ""
    W, H, ml, mr, mt, mb = 720, 312, 46, 12, 22, 46
    meio = mt + (H - mt - mb) / 2
    teto = max(max(c, p) for _, c, p in grade) or 1.0
    marcas = [m for m in _escala(0, teto, 2) if m > 0]
    teto = marcas[-1]
    passo = (W - ml - mr) / len(grade)
    larg = min(22.0, passo * 0.62)
    esc = (H - mt - mb) / 2 / teto
    strikes = [k for k, _, _ in grade]

    def x_de(k: float) -> float:
        """Posicao de um preco entre as colunas (os strikes nao sao equidistantes)."""
        if k <= strikes[0]:
            return ml + passo / 2
        if k >= strikes[-1]:
            return ml + passo * (len(strikes) - 0.5)
        for i in range(len(strikes) - 1):
            if strikes[i] <= k <= strikes[i + 1]:
                f = (k - strikes[i]) / ((strikes[i + 1] - strikes[i]) or 1.0)
                return ml + passo * (i + 0.5 + f)
        return ml

    o = [f'<svg class="graf" viewBox="0 0 {W} {H}" role="img" aria-label="Posição em aberto por preço de exercício">']
    for m in marcas:
        for sinal in (-1, 1):
            yy = meio - sinal * m * esc
            o.append(f'<line class="gr" x1="{ml}" x2="{W - mr}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
            o.append(f'<text x="{ml - 6}" y="{yy + 3.5:.1f}" text-anchor="end">{compacto(m, 0 if m >= 1e6 or m < 1e3 else 0)}</text>')
    o.append(f'<line class="eixo" x1="{ml}" x2="{W - mr}" y1="{meio:.1f}" y2="{meio:.1f}"/>')
    pula = max(1, math.ceil(len(grade) / 13))
    for i, (k, c, p) in enumerate(grade):
        x = ml + passo * i + (passo - larg) / 2
        for v, cima, cor, nome in ((c, True, "#1c5c99", "call"), (p, False, "#c2702a", "put")):
            if not v:
                continue
            alt = max(1.5, v * esc)
            r = min(4.0, alt / 2, larg / 2)
            if cima:
                t = meio - 1 - alt
                d = (f"M{x:.1f},{meio - 1:.1f} V{t + r:.1f} Q{x:.1f},{t:.1f} {x + r:.1f},{t:.1f} H{x + larg - r:.1f} "
                     f"Q{x + larg:.1f},{t:.1f} {x + larg:.1f},{t + r:.1f} V{meio - 1:.1f} Z")
            else:
                b = meio + 1 + alt
                d = (f"M{x:.1f},{meio + 1:.1f} V{b - r:.1f} Q{x:.1f},{b:.1f} {x + r:.1f},{b:.1f} H{x + larg - r:.1f} "
                     f"Q{x + larg:.1f},{b:.1f} {x + larg:.1f},{b - r:.1f} V{meio + 1:.1f} Z")
            dica = f"Strike {n(k, 2)}|{nome}: {n(v, 0)} opções em aberto"
            o.append(f'<path d="{d}" fill="{cor}" data-tip="{e(dica)}" tabindex="0"/>')
        if i % pula == 0:
            o.append(f'<text x="{x + larg / 2:.1f}" y="{H - 18}" text-anchor="middle">{n(k, 2 if k < 1000 else 0)}</text>')
    for par, cima, nome in ((parede_call, True, "teto"), (parede_put, False, "piso")):
        if par and par.get("strike") in strikes:
            i = strikes.index(par["strike"])
            x = ml + passo * i + passo / 2
            v = grade[i][1] if cima else grade[i][2]
            yy = (meio - 1 - v * esc - 6) if cima else (meio + 1 + v * esc + 14)
            o.append(f'<text class="rot" x="{x:.1f}" y="{yy:.1f}" text-anchor="middle">{nome}</text>')
    if preco:
        xp = x_de(preco)
        o.append(f'<line x1="{xp:.1f}" x2="{xp:.1f}" y1="{mt - 4}" y2="{H - mb + 4}" stroke="#1a2233" stroke-width="1.5"/>')
        anc = "start" if xp < W - 120 else "end"
        o.append(f'<text class="rot" x="{xp + (6 if anc == "start" else -6):.1f}" y="{mt + 4}" text-anchor="{anc}">preço {n(preco, 2 if preco < 1000 else 0)}</text>')
    if dor and strikes[0] <= dor <= strikes[-1]:
        xd = x_de(dor)
        o.append(f'<path d="M{xd - 5:.1f},{H - mb + 13} L{xd + 5:.1f},{H - mb + 13} L{xd:.1f},{H - mb + 4} Z" fill="#5b6474" '
                 f'data-tip="Dor máxima|{n(dor, 2 if dor < 1000 else 0)}"/>')
    o.append(f'<text x="{ml}" y="{mt - 8}">calls (para cima) e puts (para baixo), em opções{e(unidade)}</text>')
    o.append(f'<text x="{W - mr}" y="{H - 3}" text-anchor="end">preço de exercício (strike)</text></svg>')
    return "".join(o)


def svg_dispersao(pontos: list, curva: list) -> tuple[str, int]:
    """Taxa x prazo das debentures incentivadas negociadas, com a curva do juro real (DAP).
    Devolve (svg, quantos pontos ficaram acima da escala)."""
    pontos = [p for p in pontos if p.get("anos") and p.get("taxa") is not None]
    if len(pontos) < 4:
        return "", 0
    W, H, ml, mr, mt, mb = 720, 320, 44, 14, 18, 34
    taxas = sorted(p["taxa"] for p in pontos)
    corte = taxas[min(len(taxas) - 1, int(len(taxas) * 0.94))]
    ref = [c[1] for c in curva] or taxas
    marcas = _escala(min(min(taxas), min(ref)) - 0.1, max(corte, max(ref)) + 0.2)
    lo, hi = marcas[0], marcas[-1]
    xmax = max(p["anos"] for p in pontos) * 1.04
    curva = [c for c in curva if c[0] <= xmax] + ([c for c in curva if c[0] > xmax][:1])
    X = lambda a: ml + a / xmax * (W - ml - mr)
    Y = lambda v: mt + (hi - min(v, hi)) / (hi - lo) * (H - mt - mb)
    vmax = max(p["volume_rs"] for p in pontos) or 1.0
    o = [f'<svg class="graf" viewBox="0 0 {W} {H}" role="img" aria-label="Taxa por prazo das debêntures incentivadas negociadas">']
    for m in marcas:
        o.append(f'<line class="gr" x1="{ml}" x2="{W - mr}" y1="{Y(m):.1f}" y2="{Y(m):.1f}"/>')
        o.append(f'<text x="{ml - 6}" y="{Y(m) + 3.5:.1f}" text-anchor="end">{n(m, 1)}</text>')
    for a in _escala(0, xmax, 6):
        if 0 < a <= xmax:
            o.append(f'<text x="{X(a):.1f}" y="{H - mb + 16}" text-anchor="middle">{n(a, 0)}</text>')
    o.append(f'<line class="eixo" x1="{ml}" x2="{W - mr}" y1="{H - mb}" y2="{H - mb}"/>')
    if len(curva) >= 2:
        pts = [(c[0], c[1]) for c in curva]
        if pts[-1][0] > xmax:                      # corta a linha na borda do grafico
            (x0, y0), (x1, y1) = pts[-2], pts[-1]
            pts[-1] = (xmax, y0 + (y1 - y0) * (xmax - x0) / (x1 - x0))
        d = " ".join(f"{'M' if i == 0 else 'L'}{X(a):.1f},{Y(v):.1f}" for i, (a, v) in enumerate(pts))
        o.append(f'<path d="{d}" fill="none" stroke="#1a2233" stroke-width="2" stroke-linejoin="round"/>')
        o.append(f'<text class="rot" x="{W - mr - 2:.1f}" y="{Y(pts[-1][1]) + 15:.1f}" text-anchor="end">juro real de mercado (DAP)</text>')
    fora = 0
    for p in sorted(pontos, key=lambda p: -p["volume_rs"]):
        r = 3.5 + 7.5 * math.sqrt(p["volume_rs"] / vmax)
        dica = (f"{p['codigo']} · {nome_curto(p['emissor'], 30)}|IPCA + {n(p['taxa'], 2)}% · {n(p['anos'], 1)} anos|"
                f"R$ {compacto(p['volume_rs'])} no dia"
                + (f"|{n(p['premio_dap_pb'], 0, True)} pb sobre o DAP" if p.get("premio_dap_pb") is not None else ""))
        if p["taxa"] > hi:
            fora += 1
            x = X(p["anos"])
            o.append(f'<path d="M{x - 5:.1f},{mt + 9} L{x + 5:.1f},{mt + 9} L{x:.1f},{mt} Z" fill="#b3372f" '
                     f'stroke="#fff" stroke-width="1.5" data-tip="{e(dica)}"/>')
            continue
        o.append(f'<circle cx="{X(p["anos"]):.1f}" cy="{Y(p["taxa"]):.1f}" r="{r:.1f}" fill="#1c5c99" fill-opacity=".62" '
                 f'stroke="#fff" stroke-width="1.5" data-tip="{e(dica)}"/>')
    o.append(f'<text x="{ml}" y="{mt - 6}">IPCA + % ao ano</text>')
    o.append(f'<text x="{W - mr}" y="{H - 2}" text-anchor="end">anos até o vencimento</text></svg>')
    return "".join(o), fora


# ------------------------------------------------------------------ dados com data

def _bloco(atual: dict, anterior: dict | None, chave: str, teste=None):
    """(valor, pregao a que se refere). Usa o pregao anterior quando o atual ainda nao tem o bloco."""
    v = (atual or {}).get(chave)
    if v and (teste is None or teste(v)):
        return v, atual["pregao"]
    w = (anterior or {}).get(chave)
    if w and (teste is None or teste(w)):
        return w, anterior["pregao"]
    return v or {}, (atual or {}).get("pregao")


def _serie_hist(hist: dict, ate: str, *chaves, n_max: int = 20) -> list:
    out = []
    for d in sorted(k for k in (hist.get("pregoes") or {}) if k <= ate)[-n_max:]:
        x = hist["pregoes"][d]
        for c in chaves:
            x = x.get(c) if isinstance(x, dict) else None
            if x is None:
                break
        out.append(x)
    return out


def fluxo_diario(hist: dict, ate_pregao: str) -> list:
    """[(data, saldo do estrangeiro no dia em R$ mi)] a partir dos acumulados guardados."""
    acum = {}
    for d in sorted(k for k in (hist.get("pregoes") or {}) if k <= ate_pregao):
        f = hist["pregoes"][d].get("fluxo") or {}
        if f.get("ate") and (f.get("saldo") or {}).get("estrangeiro") is not None:
            acum[f["ate"]] = f["saldo"]["estrangeiro"]
    datas, out = sorted(acum), []
    for i, d in enumerate(datas):
        if i == 0:
            continue
        ant = datas[i - 1]
        out.append((d, acum[d] - acum[ant] if ant[:7] == d[:7] else acum[d]))
    return out[-18:]


# ------------------------------------------------------------------ secoes

def _cabecalho(r: dict, ant: dict | None) -> str:
    d = date.fromisoformat(r["pregao"])
    sit = r["situacao"]
    if sit["completo"]:
        estado = '<span class="selo">COMPLETO</span>Todos os blocos do pregão já publicados pela B3.'
    else:
        falta = ", ".join(NOME_PENDENTE.get(x, x) for x in sit["faltam"])
        emprest = f" Esses cards mostram a posição de {dm(ant['pregao'])}." if ant else ""
        estado = (f'<span class="selo parcial">PARCIAL</span>Ainda sem {e(falta)}: a B3 publica esses blocos na madrugada '
                  f'seguinte ao pregão.{emprest}')
    return (f'<header><div class="marca">Boletim diário do mercado · B3</div>'
            f'<h1>📊 Pregão de {d.strftime("%d/%m/%Y")}<small>{DIAS[d.weekday()]}</small></h1>'
            f'<p class="sub">{estado}</p></header>')


def _kpis(r: dict, ant: dict | None) -> str:
    ind, der, mer = r.get("indices") or {}, r.get("derivativos") or {}, r.get("mercado") or {}
    fut = der.get("futuros") or {}
    tiles = []

    def tile(rot, val, delta="", pe=""):
        tiles.append(f'<div class="kpi"><div class="rot">{rot}</div><div class="val">{val}</div>'
                     f'<div class="dl">{delta}</div><div class="pe">{pe}</div></div>')

    ib = ind.get("IBOVESPA")
    if ib:
        tile("Ibovespa", n(ib.get("fechamento"), 0), pc(ib.get("dia_pct")), f"no mês {n(ib.get('mes_pct'), 2, True)}%")
    dol = next(iter((fut.get("DOL") or {}).items()), None)
    if dol:
        tile(f"Dólar futuro ({rotulo_futuro(dol[0])})", n((dol[1].get("ajuste") or 0) / 1000.0, 4), pc(dol[1].get("var_pct")), "ajuste em R$")
    di = fut.get("DI1") or {}
    for alvo in ("DI1F29", "DI1F28", "DI1F27"):
        if alvo in di:
            v = di[alvo]
            delta = (f'<span class="{cls(-(v.get("var_bps") or 0))}">{pb(v.get("var_bps"))}</span>') if v.get("var_bps") is not None else ""
            tile(f"Juros: DI {rotulo_futuro(alvo)}", n(v.get("taxa"), 2) + "<small>%</small>", delta, "taxa de ajuste")
            break
    base = date.fromisoformat(r["pregao"])
    longos = [(tk, v) for tk, v in (fut.get("DAP") or {}).items() if venc_futuro(tk) and (venc_futuro(tk) - base).days >= 540]
    dap = sorted(longos, key=lambda kv: -(kv[1].get("contratos") or 0))[:1]
    for tk, v in dap:
        delta = (f'<span class="{cls(-(v.get("var_bps") or 0))}">{pb(v.get("var_bps"))}</span>') if v.get("var_bps") is not None else ""
        tile(f"Juro real: DAP {rotulo_futuro(tk)}", n(v.get("taxa"), 2) + "<small>%</small>", delta, "cupom de IPCA")
    if mer.get("dia"):
        x = mer.get("volume_x_media_mes")
        tile("Giro à vista", n((mer["dia"].get("volume_mi") or 0) / 1000.0, 1) + "<small>R$ bi</small>",
             f"{n(x, 2)}x a média do mês" if x else "", f"{n((mer['dia'].get('negocios') or 0) / 1e6, 2)} mi de negócios")
    f = r.get("fluxo") or {}
    est = (f.get("acumulado_no_mes") or {}).get("estrangeiro")
    if est:
        per = (f.get("periodo") or {}).get("saldo_mi", {}).get("estrangeiro")
        tile("Estrangeiro no mês", f'<span class="{cls(est["saldo_mi"])}">{n(est["saldo_mi"] / 1000.0, 2, True)}</span><small>R$ bi</small>',
             (f'<span class="{cls(per)}">{n(per, 0, True)} mi</span> em {dm(f.get("ate"))}') if per is not None else "",
             f"acumulado até {dm(f.get('ate'))}")
    rad, d_rad = _bloco(r, ant, "radar", lambda v: v.get("aluguel_total_rs"))
    if rad.get("aluguel_total_rs"):
        tile("Aluguel de ações", n(rad["aluguel_total_rs"] / 1e9, 1) + "<small>R$ bi</small>",
             pc(rad.get("aluguel_total_var_pct")) if rad.get("aluguel_total_var_pct") is not None else "",
             f"saldo do mercado em {dm(d_rad)}")
    rf = (r.get("renda_fixa") or {}).get("resumo") or {}
    if rf:
        total = sum((rf.get(c) or {}).get("volume_rs") or 0 for c in ROTULO_RF)
        inc = rf.get("deb_incentivada") or {}
        tile("Crédito isento", n(total / 1e9, 2) + "<small>R$ bi</small>",
             f"incentivadas a IPCA+{n(inc.get('taxa_ipca_media'), 2)}%" if inc.get("taxa_ipca_media") else "",
             "debêntures incentivadas, CRI e CRA")
    return f'<div class="kpis">{"".join(tiles)}</div>'


def _sinais(r: dict) -> str:
    def item(s):
        seg = f" · {s['pregoes_seguidos']}º pregão seguido" if s.get("pregoes_seguidos", 1) > 1 else ""
        return (f'<li><span class="tp">{e(ROTULO_SINAL.get(s["tipo"], s["tipo"]))}</span><span>{e(s["texto"])}'
                f'<span class="ref">B3 · {e(s["fonte"])} · {dm(s["data"])}{seg}</span></span></li>')
    novos = [s for s in r["sinais"] if s.get("pregoes_seguidos", 1) == 1]
    velhos = [s for s in r["sinais"] if s.get("pregoes_seguidos", 1) > 1]
    o = ['<section id="sinais"><h2>Sinais do dia</h2><div class="card">']
    if not r["sinais"]:
        o.append('<p class="vazio">Nenhum sinal passou dos limiares hoje.</p>')
    if novos:
        o.append(f'<h4>Novos hoje · {len(novos)}</h4><ul class="sinais" style="margin-top:8px">{"".join(item(s) for s in novos)}</ul>')
    if velhos:
        o.append(f'<details{" open" if not novos else ""}><summary>Já vinham de pregões anteriores · {len(velhos)}</summary>'
                 f'<ul class="sinais">{"".join(item(s) for s in velhos)}</ul></details>')
    o.append('<p class="explicacao"><b>Sinal</b> é um fato do boletim que passou de um limiar fixo (volume acima de 2x a média, '
             'aluguel acima de 5% das ações em circulação, taxa de crédito abrindo 30 pontos-base). Não é recomendação.</p>')
    o.append("</div></section>")
    return "".join(o)


def _mercado(r: dict) -> str:
    ind, mer, dest = r.get("indices") or {}, r.get("mercado") or {}, r.get("destaques") or {}
    escala = max([abs(v.get("dia_pct") or 0) for v in ind.values()] + [1.0])
    linhas = [[e(NOME_INDICE.get(k, k)), n(v.get("fechamento"), 0), barra_div(v.get("dia_pct"), escala) + pc(v.get("dia_pct")),
               pc(v.get("mes_pct")), pc(v.get("ano_pct"))] for k, v in ind.items()]
    o = ['<section id="mercado"><h2>Mercado</h2><div class="g2">']
    o.append('<div class="card"><h3>Índices da B3</h3><p class="desc">Fechamento e variação no dia, no mês e no ano.</p>'
             + tabela(["Índice", "Fechamento", "Dia", "Mês", "Ano"], linhas, ["", "n", "n", "n", "n"]) + "</div>")
    o.append('<div class="card"><h3>Giro e amplitude</h3><p class="desc">Quanto girou e quantas ações subiram.</p>')
    ib = ind.get("IBOVESPA") or {}
    if ib.get("altas") is not None:
        a, b = ib.get("altas") or 0, ib.get("baixas") or 0
        tot = (a + b) or 1
        o.append(f'<div class="pilha" style="margin-block:6px 4px"><i style="width:{a / tot * 100:.0f}%;background:var(--pos)"></i>'
                 f'<i style="width:{b / tot * 100:.0f}%;background:var(--neg)"></i></div>'
                 f'<p class="desc">Ibovespa: <b class="pos">{a} em alta</b> e <b class="neg">{b} em baixa</b>.</p>')
    seg = mer.get("segmentos") or {}
    linhas = []
    if mer.get("dia"):
        linhas.append(["Mercado à vista (dia)", n(mer["dia"].get("volume_mi"), 0), n((mer["dia"].get("negocios") or 0) / 1e3, 0)])
        if mer.get("media_mes"):
            linhas.append(["Média do mês", n(mer["media_mes"].get("volume_mi"), 0), n((mer["media_mes"].get("negocios") or 0) / 1e3, 0)])
    for chave, rot in (("opcoes", "Opções"), ("termo", "Termo"), ("after_market", "After market")):
        if seg.get(chave):
            linhas.append([rot, n(seg[chave].get("volume_mi"), 0), n((seg[chave].get("negocios") or 0) / 1e3, 0)])
    o.append(tabela(["Segmento", "Volume (R$ mi)", "Negócios (mil)"], linhas, ["", "n", "n"]))
    for chave, rot in (("maiores_altas_ibov", "Maiores altas do Ibovespa"), ("maiores_baixas_ibov", "Maiores baixas do Ibovespa")):
        if dest.get(chave):
            chips = "".join(f'<span class="chip"><span class="code">{e(c)}</span> {pc(v)}</span>' for c, v in dest[chave][:6])
            o.append(f'<h4 style="margin-top:12px">{rot}</h4><div class="chips" style="margin-top:6px">{chips}</div>')
    o.append("</div></div></section>")
    return "".join(o)


def _fluxo(r: dict, hist: dict) -> str:
    f = r.get("fluxo") or {}
    if not f.get("acumulado_no_mes"):
        return ""
    per = f.get("periodo") or {}
    diario = fluxo_diario(hist, r["pregao"])
    o = [f'<section id="fluxo"><h2>Fluxo por tipo de investidor</h2><div class="g2">']
    o.append(f'<div class="card"><h3>Estrangeiro: saldo dia a dia</h3><p class="desc">Compras menos vendas, em R$ milhões. '
             f'Último dia divulgado: {dm(f.get("ate"))} {tag_data(f.get("ate"), r["pregao"])}</p>')
    if len(diario) >= 2:
        ibov = {d: (x.get("indices") or {}).get("IBOVESPA") for d, x in (hist.get("pregoes") or {}).items()}
        pontos = [(dm(d), v, f"{dm(d)}|Estrangeiro: {n(v, 0, True)} R$ mi"
                   + (f"|Ibovespa no dia: {n(ibov[d][1], 2, True)}%" if ibov.get(d) and ibov[d][1] is not None else "")) for d, v in diario]
        contra = [d for d, v in diario if ibov.get(d) and ibov[d][1] is not None and v * ibov[d][1] < 0]
        o.append(f"<figure>{svg_colunas_sinal(pontos)}</figure>")
        if contra:
            o.append(f'<p class="desc">Em {len(contra)} de {len(diario)} dias o estrangeiro foi na direção contrária à do Ibovespa '
                     f'(último: {dm(contra[-1])}). Passe o dedo ou o mouse nas colunas para ver o índice do dia.</p>')
    else:
        o.append('<p class="vazio">O gráfico aparece quando houver dois acumulados no histórico.</p>')
    o.append("</div>")
    escala = max([abs(v["saldo_mi"]) for v in f["acumulado_no_mes"].values()] + [1.0])
    linhas = []
    for k, v in sorted(f["acumulado_no_mes"].items(), key=lambda kv: -abs(kv[1]["saldo_mi"])):
        p = (per.get("saldo_mi") or {}).get(k)
        linhas.append([e(ROTULO_INVESTIDOR.get(k, k)),
                       barra_div(v["saldo_mi"], escala) + f'<span class="{cls(v["saldo_mi"])}">{n(v["saldo_mi"], 0, True)}</span>',
                       f'<span class="{cls(p)}">{n(p, 0, True)}</span>' if p is not None else "–",
                       n(v.get("part_compras_pct"), 1) + "%"])
    cab = "No dia" if per.get("de") == per.get("ate") else f"De {dm(per.get('de'))} a {dm(per.get('ate'))}"
    o.append(f'<div class="card"><h3>Quem comprou e quem vendeu</h3><p class="desc">Acumulado do mês até {dm(f.get("ate"))}, em R$ milhões.</p>'
             + tabela(["Investidor", "Saldo no mês", cab if per else "No dia", "Fatia das compras"], linhas, ["", "n", "n", "n"])
             + '<p class="explicacao"><b>Como ler:</b> a B3 divulga compras e vendas acumuladas no mês, somando todos os mercados, '
               'com dois pregões de atraso. O saldo de um dia é a diferença entre dois acumulados seguidos.</p></div>')
    o.append("</div></section>")
    return "".join(o)


def _juros(r: dict, ant: dict | None, hist: dict) -> str:
    der = r.get("derivativos") or {}
    fut = der.get("futuros") or {}
    di = fut.get("DI1") or {}
    if not fut:
        return ""
    base = date.fromisoformat(r["pregao"])
    anos = lambda tk: (venc_futuro(tk) - base).days / 365.25
    hoje = [(anos(tk), v["taxa"], rotulo_futuro(tk),
             f"DI {rotulo_futuro(tk)}|{n(v['taxa'], 3)}% ao ano" + (f"|{pb(v.get('var_bps'))} no dia" if v.get("var_bps") is not None else ""))
            for tk, v in di.items() if v.get("taxa") is not None and venc_futuro(tk)]
    series = [("hoje", "#1c5c99", 2.5, sorted(hoje))]
    datas = sorted(k for k in (hist.get("pregoes") or {}) if k < r["pregao"])
    for recuo, cor in ((1, "#8b97a8"), (5, "#c3cad5")):
        if len(datas) >= recuo:
            d = datas[-recuo]
            pts = sorted((anos(tk), v["taxa"], "", "") for tk, v in (hist["pregoes"][d].get("futuros") or {}).items()
                         if tk in di and v.get("taxa") is not None)
            if len(pts) >= 2:
                series.append((dm(d), cor, 1.5, pts))
    g = svg_curva(series)
    esquerda = ['<div class="card"><h3>Curva do DI futuro</h3><p class="desc">Taxa de ajuste por vencimento: hoje contra o pregão '
                'anterior e contra cinco pregões atrás.</p>',
                f"<figure>{g}</figure>" if g else '<p class="vazio">Sem vértices suficientes para a curva.</p>',
                '<p class="explicacao"><b>DI futuro</b> é a taxa prefixada que o mercado negocia para cada prazo. Curva subindo = '
                'juro mais alto à frente; pesa em construtoras e utilities.</p></div>']
    quadro, d_q = der.get("quadro") or {}, r["pregao"]
    if not quadro and ant:
        quadro, d_q = (ant.get("derivativos") or {}).get("quadro") or {}, ant["pregao"]
    if quadro:
        nomes = {"DOL": "Dólar cheio", "WDO": "Minidólar", "DI1": "DI futuro", "DAP": "Cupom de IPCA", "IND": "Ibovespa cheio",
                 "WIN": "Mini-índice", "DDI": "Cupom cambial", "FRC": "FRA de cupom"}
        linhas = [[f'{e(nomes.get(a, a))} <span class="code">{e(a)}</span>', n(v.get("contratos"), 0), pc(v.get("var_contratos_pct")),
                   n((v.get("referencial_mi") or 0) / 1000.0, 1)] for a, v in quadro.items()]
        qo = (der.get("quadro_opcoes") or ((ant or {}).get("derivativos") or {}).get("quadro_opcoes") or {}).get("DOL")
        extra = ""
        if qo and qo.get("call"):
            extra = (f'<p class="explicacao"><b>Opções de dólar:</b> {n(qo["call"], 0)} contratos de call em aberto contra '
                     f'{n(qo.get("put"), 0)} de put (put/call de {n(qo.get("put_call"), 2)}). Call de dólar é proteção contra a alta '
                     f'da moeda.</p>')
        esquerda.append(f'<div class="card"><h3>Posições em aberto por mercado {tag_data(d_q, r["pregao"])}</h3>'
                        '<p class="desc">Contratos em aberto nos futuros. Contratos subindo com preço andando é posição nova, não zeragem.</p>'
                        + tabela(["Mercado", "Contratos", "No pregão", "Referencial (R$ bi)"], linhas, ["", "n", "n", "n"]) + extra + "</div>")
    linhas = []
    for a, rot in (("DI1", "DI futuro"), ("DAP", "Cupom de IPCA (juro real)"), ("DOL", "Dólar futuro"), ("IND", "Ibovespa futuro")):
        itens = fut.get(a) or {}
        if not itens:
            continue
        linhas.append(f'<tr class="grupo"><td colspan="4">{rot}</td></tr>')
        ordem = list(itens)
        if a == "DAP":
            fica = sorted(itens, key=lambda k: -(itens[k].get("contratos") or 0))[:4]
            ordem = [k for k in itens if k in fica]
        elif a in ("DOL", "IND"):
            ordem = ordem[:2]
        for tk in ordem:
            v = itens[tk]
            if v.get("taxa") is not None:
                nivel = n(v["taxa"], 3) + "%"
                var = (f'<span class="{cls(-(v.get("var_bps") or 0))}">{pb(v.get("var_bps"))}</span>') if v.get("var_bps") is not None else "–"
            else:
                nivel, var = n(v.get("ajuste"), 2), pc(v.get("var_pct"))
            linhas.append([f'<span class="code">{e(tk)}</span> <span class="mut">{rotulo_futuro(tk)}</span>', nivel, var,
                           n(v.get("em_aberto"), 0)])
    direita = ('<div class="card"><h3>Ajustes do dia</h3><p class="desc">Taxa ou preço de ajuste, variação e contratos em aberto. '
               'Em juros, queda de taxa aparece em verde.</p>'
               + tabela(["Contrato", "Ajuste", "Variação", "Em aberto"], linhas, ["", "n", "n", "n"]) + "</div>")
    return ('<section id="juros"><h2>Juros, dólar e índice futuro</h2><div class="g2">'
            f'<div class="col">{"".join(esquerda)}</div>{direita}</div></section>')


def _livro(r: dict, ant: dict | None, hist: dict) -> str:
    at, grupos = r.get("ativos") or {}, r.get("grupos") or {}
    ant_at = (ant or {}).get("ativos") or {}
    esc_dia = max([abs((a.get("negocios") or {}).get("oscilacao_pct") or 0) for a in at.values()] + [1.0])
    sinais = {}
    for s in r.get("sinais") or []:
        if s.get("ativo"):
            sinais.setdefault(s["ativo"], []).append(ROTULO_SINAL.get(s["tipo"], s["tipo"]))
    linhas, vistos = [], set()
    emprestado = False
    tri = (r.get("triangulacao") or {}).get("grupos") or {}
    for g, tks in list(grupos.items()) + [("outros", [tk for tk in at if not any(tk in v for v in grupos.values())])]:
        tks = [tk for tk in tks if tk in at and tk not in vistos]
        if not tks:
            continue
        media = (tri.get(g) or {}).get("media_pct")
        linhas.append(f'<tr class="grupo"><td colspan="8">{e(NOME_GRUPO.get(g, g.title()))}'
                      + (f' <span style="font-weight:400;text-transform:none;letter-spacing:0">· média do dia {n(media, 2, True)}%</span>' if media is not None else "")
                      + "</td></tr>")
        for tk in tks:
            vistos.add(tk)
            a = at[tk]
            g_ = a.get("negocios") or {}
            al = a.get("aluguel") or {}
            op = a.get("opcoes") or {}
            if not al.get("saldo_qtd") and (ant_at.get(tk) or {}).get("aluguel"):
                al, emprestado = ant_at[tk]["aluguel"], True
            if op.get("put_call") is None and (ant_at.get(tk) or {}).get("opcoes"):
                op = ant_at[tk]["opcoes"]
            x = g_.get("volume_x_media")
            mi = (g_.get("volume_rs") or 0) / 1e6
            sp = spark(_serie_hist(hist, r["pregao"], "ativos", tk, "fech", n_max=20))
            marcas = "".join(f'<span class="tag" style="margin-right:3px">{e(t)}</span>' for t in dict.fromkeys(sinais.get(tk, [])))
            linhas.append([
                f'<span class="code">{e(tk)}</span>', n(g_.get("fechamento")),
                barra_div(g_.get("oscilacao_pct"), esc_dia) + pc(g_.get("oscilacao_pct")),
                sp or '<span class="mut">–</span>',
                (medidor(x, 3.0) + f"{n(x, 1)}x" if x else "") + f'<span class="peq">R$ {n(mi, 0 if mi >= 10 else 1)} mi</span>',
                (n(al.get("pct_free_float"), 1) + "%" if al.get("pct_free_float") is not None else "–")
                + (f'<span class="peq">taxa {n(al.get("taxa_tomador_media"), 2)}%</span>' if al.get("taxa_tomador_media") is not None else ""),
                n(op.get("put_call"), 2) if op.get("put_call") is not None else "–",
                marcas or '<span class="mut">–</span>'])
    if not linhas:
        return ""
    nota = (f' <span class="tag velho">aluguel e put/call de {dm(ant["pregao"])}</span>' if emprestado and ant else "")
    return ('<section id="livro"><h2>O livro na B3</h2><div class="card"><h3>Os ativos monitorados, lado a lado' + nota + '</h3>'
            '<p class="desc">Preço e volume do pregão; aluguel como parcela das ações em circulação; put/call da posição em aberto.</p>'
            + tabela(["Ativo", "Fech. (R$)", "Dia", "20 pregões", "Volume x média", "Alugado", "Put/call", "Sinais"],
                     linhas, ["", "n", "n", "", "n", "n", "n", "txt"])
            + '<p class="explicacao"><b>Volume x média:</b> volume do dia dividido pela média dos pregões anteriores (até 20). '
              '<b>Alugado:</b> ações alugadas (quase sempre para venda a descoberto) como parcela da quantidade teórica do índice, '
              'que aproxima as ações em circulação. <b>Put/call:</b> opções de venda em aberto divididas pelas de compra; acima de 1 '
              'há mais proteção ou aposta de queda do que de alta.</p></div></section>')


def _linhas_radar(itens: list, colunas: list) -> list:
    out = []
    for l in itens:
        linha = [f'<span class="code">{e(l["ativo"])}</span>' + (' <span class="tag">livro</span>' if l.get("do_livro") else "")]
        for chave, fmt in colunas:
            linha.append(fmt(l.get(chave)))
        out.append(linha)
    return out


def _aluguel(r: dict, ant: dict | None, hist: dict) -> str:
    at = r.get("ativos") or {}
    d_al = r["pregao"]
    com = {tk: a["aluguel"] for tk, a in at.items() if (a.get("aluguel") or {}).get("saldo_qtd")}
    if not com and ant:
        com = {tk: a["aluguel"] for tk, a in (ant.get("ativos") or {}).items() if (a.get("aluguel") or {}).get("saldo_qtd")}
        d_al = ant["pregao"]
    rad, d_rad = _bloco(r, ant, "radar", lambda v: v.get("aluguel_float"))
    corr, d_corr = _bloco(r, ant, "aluguel_corretoras", lambda v: v.get("tomadoras"))
    if not com and not rad.get("aluguel_float"):
        return ""
    o = ['<section id="aluguel"><h2>Aluguel de ações</h2>']
    if com:
        ordem = sorted(com.items(), key=lambda kv: -(kv[1].get("pct_free_float") or 0))
        teto = max([v.get("pct_free_float") or 0 for _, v in ordem] + [1.0])
        barras = []
        for tk, v in ordem:
            ff = v.get("pct_free_float")
            if ff is None:
                continue
            var = v.get("var_dia_pct")
            barras.append(f'<span class="code">{e(tk)}</span><span class="tr" data-tip="{e(tk)}|{n(ff, 1)}% das ações em circulação alugadas|'
                          f'{n((v.get("saldo_qtd") or 0) / 1e6, 1)} mi de ações · R$ {compacto(v.get("saldo_rs"))}|'
                          f'taxa do tomador {n(v.get("taxa_tomador_media"), 2)}% ao ano"><i style="width:{ff / teto * 100:.0f}%"></i></span>'
                          f'<span class="v">{n(ff, 1)}%<small>{("taxa " + n(v.get("taxa_tomador_media"), 2) + "%") if v.get("taxa_tomador_media") is not None else ""}'
                          f'{(" · dia " + n(var, 1, True) + "%") if var is not None else ""}</small></span>')
        esq = [f'<div class="card"><h3>O livro: quanto está alugado {tag_data(d_al, r["pregao"])}</h3>'
               '<p class="desc">Ações alugadas como parcela das ações em circulação, com a taxa que o tomador paga ao ano e a variação do saldo no pregão.</p>'
               f'<div class="bh">{"".join(barras)}</div>']
        sem = [f'<span class="chip"><span class="code">{e(tk)}</span> {n((v.get("saldo_qtd") or 0) / 1e6, 2)} mi</span>'
               for tk, v in ordem if v.get("pct_free_float") is None]
        if sem:
            esq.append('<h4 style="margin-top:14px">Fora do índice (saldo em ações, sem base de ações em circulação)</h4>'
                       f'<div class="chips" style="margin-top:6px">{"".join(sem)}</div>')
        esq.append('<p class="explicacao"><b>Aluguel (BTC):</b> quem aluga a ação normalmente a vende esperando recomprar mais barato. Saldo alto com '
                   'taxa alta mostra aposta de queda cara de manter; se o preço sobe, esse vendido tende a recomprar.</p></div>')
        dire = ['<div class="card"><h3>Quem intermediou o aluguel do dia ' + tag_data(d_corr, r["pregao"]) + '</h3>']
        if corr.get("tomadoras"):
            teto_c = max(x[2] for x in corr["tomadoras"][:6] + corr["doadoras"][:6])

            def lista(itens, dois):
                return "".join(f'<span>{e(nome)}</span><span class="tr{" dois" if dois else ""}"><i style="width:{p_ / teto_c * 100:.0f}%"></i></span>'
                               f'<span class="v">{n(p_, 1)}%<small>R$ {compacto(rs)}</small></span>' for nome, rs, p_ in itens[:6])
            dire.append(f'<p class="desc">{n(corr.get("negocios"), 0)} empréstimos novos, R$ {compacto(corr.get("volume_rs"))}. '
                        'Corretora é o intermediário, não o investidor final.</p>'
                        f'<h4 style="margin-top:6px">Lado tomador (quem pegou a ação)</h4><div class="bh" style="margin-top:6px">{lista(corr["tomadoras"], False)}</div>'
                        f'<h4 style="margin-top:12px">Lado doador (quem emprestou)</h4><div class="bh" style="margin-top:6px">{lista(corr["doadoras"], True)}</div>')
            do_livro = [(tk, v) for tk, v in (corr.get("ativos") or {}).items() if tk in com and v.get("tomadoras")]
            do_livro = sorted(do_livro, key=lambda kv: -((com.get(kv[0]) or {}).get("pct_free_float") or 0))[:5]
            if do_livro:
                linhas = [[f'<span class="code">{e(tk)}</span>', n((v.get("quantidade") or 0) / 1e6, 2),
                           ", ".join(f"{e(nm)} {n(p_, 0)}%" for nm, p_ in v["tomadoras"])] for tk, v in do_livro]
                dire.append('<h4 style="margin-top:14px">No livro: por onde passou o lado tomador</h4>'
                            + tabela(["Ativo", "Ações no dia (mi)", "Principais corretoras"], linhas, ["", "n", "txt"]))
        else:
            dire.append('<p class="vazio">A B3 ainda não publicou o aluguel negócio a negócio deste pregão.</p>')
        dire.append("</div>")
        o.append(f'<div class="g2">{"".join(esq)}{"".join(dire)}</div>')
    if rad.get("aluguel_float"):
        f1 = lambda v: n(v, 1) + "%" if v is not None else "–"
        f2 = lambda v: n(v, 2) + "%" if v is not None else "–"
        rs = lambda v: compacto(v) if v is not None else "–"
        o.append(f'<div class="card"><h3>Radar do mercado: aluguel {tag_data(d_rad, r["pregao"])}</h3>'
                 f'<p class="desc">As ações do IBrA ({rad.get("universo")} papéis com liquidez) mais o livro. '
                 f'Saldo total do mercado: R$ {compacto(rad.get("aluguel_total_rs"))} em {n(rad.get("papeis_com_aluguel"), 0)} papéis.</p><div class="g2">')
        o.append("<div><h4>Mais alugadas (parcela das ações em circulação)</h4>"
                 + tabela(["Ativo", "Alugado", "Taxa", "Preço em 5 pregões"],
                          _linhas_radar(rad["aluguel_float"][:10], [("pct_free_float", f1), ("taxa", f2), ("preco_5d_pct", pc)]),
                          ["", "n", "n", "n"]) + "</div>")
        o.append("<div><h4>Aluguel mais caro (taxa do tomador ao ano)</h4>"
                 + tabela(["Ativo", "Taxa", "Alugado", "Saldo (R$)"],
                          _linhas_radar(rad.get("aluguel_taxa", [])[:10], [("taxa", f2), ("pct_free_float", f1), ("saldo_rs", rs)]),
                          ["", "n", "n", "n"]) + "</div>")
        if rad.get("aluguel_alta"):
            o.append("<div><h4>Saldo alugado que mais subiu no pregão</h4>"
                     + tabela(["Ativo", "Saldo", "Preço no dia", "Saldo (R$)"],
                              _linhas_radar(rad["aluguel_alta"][:8], [("aluguel_var_dia_pct", pc), ("oscilacao_pct", pc), ("saldo_rs", rs)]),
                              ["", "n", "n", "n"]) + "</div>")
        if rad.get("aluguel_queda"):
            o.append("<div><h4>Saldo alugado que mais caiu no pregão</h4>"
                     + tabela(["Ativo", "Saldo", "Preço no dia", "Saldo (R$)"],
                              _linhas_radar(rad["aluguel_queda"][:8], [("aluguel_var_dia_pct", pc), ("oscilacao_pct", pc), ("saldo_rs", rs)]),
                              ["", "n", "n", "n"]) + "</div>")
        o.append("</div>")
        for chave, titulo, texto in (
                ("vendidos_pressionados", "Vendidos sob pressão", "muito alugadas e com o preço subindo em 5 pregões"),
                ("aposta_vendida_crescendo", "Aposta vendida crescendo", "saldo alugado subindo forte com o preço caindo em 5 pregões")):
            if rad.get(chave):
                chips = "".join(f'<span class="chip"><span class="code">{e(l["ativo"])}</span> alugado {n(l.get("pct_free_float"), 1)}% · '
                                f'saldo em 5 pregões {n(l.get("aluguel_var_5d_pct"), 0, True)}% · preço {n(l.get("preco_5d_pct"), 1, True)}%</span>' for l in rad[chave])
                o.append(f'<h4 style="margin-top:14px">{titulo}: {texto}</h4><div class="chips" style="margin-top:6px">{chips}</div>')
        o.append("</div>")
    o.append("</section>")
    return "".join(o)


def _radar_volume(r: dict) -> str:
    rad = r.get("radar") or {}
    if not rad.get("volume"):
        return ""
    linhas = _linhas_radar(rad["volume"][:10], [("volume_x_media", lambda v: medidor(v, 5.0) + n(v, 1) + "x"),
                                                ("oscilacao_pct", pc), ("volume_rs", lambda v: compacto(v))])
    return ('<div class="card"><h3>Radar do mercado: volume fora do padrão</h3>'
            '<p class="desc">Ações do IBrA e do livro que giraram pelo menos 2x a própria média de 20 pregões.</p>'
            + tabela(["Ativo", "Volume x média", "Preço no dia", "Volume (R$)"], linhas, ["", "n", "n", "n"]) + "</div>")


def _painel_opcao(tk: str, o_: dict, hist: dict, pregao: str, data_pos: str, do_livro: bool) -> str:
    preco = o_.get("preco")
    venc = (o_.get("vencimentos") or [None])[0]
    pcs = [x[1] / x[0] if isinstance(x, list) and x[0] else None
           for x in _serie_hist(hist, pregao, *(("ativos", tk, "opc") if do_livro else ("opcoes_extras", tk)), n_max=20)]
    casas = 2 if (preco or 0) < 1000 else 0
    tiles = []

    def tile(rot, val, pe=""):
        tiles.append(f'<div class="tile"><div class="rot">{rot}</div><div class="val">{val}</div><div class="pe">{pe}</div></div>')

    tile("Preço do ativo", n(preco, casas), "fechamento")
    if o_.get("put_call") is not None:
        ant = o_.get("put_call_anterior")
        tile("Put/call (posição)", n(o_["put_call"], 2), (f"era {n(ant, 2)} no pregão anterior" if ant is not None else "puts ÷ calls em aberto"))
    if o_.get("posicao_call") is not None:
        tile("Calls em aberto", compacto(o_["posicao_call"]), f"dia {n(o_.get('var_posicao_call_pct'), 1, True)}%" if o_.get("var_posicao_call_pct") is not None else "opções")
        tile("Puts em aberto", compacto(o_.get("posicao_put")), f"dia {n(o_.get('var_posicao_put_pct'), 1, True)}%" if o_.get("var_posicao_put_pct") is not None else "opções")
    vc, vp = o_.get("volume_call_rs") or 0, o_.get("volume_put_rs") or 0
    tile("Volume do dia", "R$ " + compacto(vc + vp), f"calls {compacto(vc)} · puts {compacto(vp)}")
    if venc and venc.get("dor_maxima"):
        tile("Dor máxima", n(venc["dor_maxima"], casas),
             f"{n(venc.get('dor_maxima_dist_pct'), 1, True)}% do preço · venc. {dm(venc['vencimento'])}")
    s = [f'<div data-painel="opcoes" data-id="{e(tk)}"><div class="tiles">{"".join(tiles)}</div><div class="duo">']
    # ---- esquerda: o grafico
    s.append("<div>")
    if venc and venc.get("grade"):
        g = svg_strikes(venc["grade"], preco, venc.get("parede_call"), venc.get("parede_put"), venc.get("dor_maxima"))
        s.append(f'<h4>Posição em aberto por strike · vencimento de {dm(venc["vencimento"])} ({venc["dias_uteis"]} dias úteis) '
                 f'{tag_data(data_pos, pregao)}</h4>'
                 '<div class="legenda" style="margin-top:6px"><span><i style="background:#1c5c99"></i>calls (opções de compra)</span>'
                 '<span><i style="background:#c2702a"></i>puts (opções de venda)</span>'
                 '<span><i class="l" style="background:#1a2233"></i>preço do ativo</span><span>▲ dor máxima</span></div>'
                 f"<figure>{g}</figure>")
    else:
        s.append('<p class="vazio">Sem posição em aberto suficiente para o gráfico por strike.</p>')
    s.append("</div>")
    # ---- direita: paredes, put/call e series
    s.append('<div class="col">')
    linhas = []
    for v in o_.get("vencimentos") or []:
        pcall, pput = v.get("parede_call") or {}, v.get("parede_put") or {}
        linhas.append([f'{dm(v["vencimento"])}<span class="peq">{v["dias_uteis"]} dias úteis</span>',
                       (f'{n(pcall.get("strike"), casas)}<span class="peq">{n(pcall.get("distancia_pct"), 1, True)}%</span>') if pcall else "–",
                       (f'{n(pput.get("strike"), casas)}<span class="peq">{n(pput.get("distancia_pct"), 1, True)}%</span>') if pput else "–"])
    s.append("<div><h4>Paredes por vencimento</h4>"
             + tabela(["Vencimento", "Teto (call)", "Piso (put)"], linhas, ["", "n", "n"]))
    extras = []
    if len([x for x in pcs if x is not None]) >= 3:
        extras.append(f"Put/call nos últimos pregões: {spark(pcs, 110, 24)}")
    if o_.get("descoberta_call_pct") is not None:
        extras.append(f'Lançadas a descoberto: {n(o_["descoberta_call_pct"], 0)}% das calls e {n(o_.get("descoberta_put_pct"), 0)}% das puts.')
    if extras:
        s.append('<p class="desc" style="margin-top:8px">' + "<br>".join(extras) + "</p>")
    s.append("</div>")
    mud = (o_.get("maiores_altas") or [])[:3] + (o_.get("maiores_quedas") or [])[:2]
    if mud:
        linhas = [[f'<span class="code">{e(m["codigo"])}</span><span class="peq">{e(m["tipo"])} · strike {n(m.get("strike"), casas)} · {dm(m.get("vencimento"))}</span>',
                   f'<span class="{cls(m["variacao"])}">{compacto(m["variacao"]) if abs(m["variacao"]) >= 1000 else n(m["variacao"], 0)}</span>'
                   if m["variacao"] < 0 else f'<span class="pos">+{compacto(m["variacao"])}</span>', compacto(m.get("posicao"))] for m in mud]
        s.append("<div><h4>Séries que mais mudaram de posição</h4>"
                 + tabela(["Série", "No dia", "Em aberto"], linhas, ["", "n", "n"]) + "</div>")
    else:
        linhas = [[f'<span class="code">{e(m["codigo"])}</span><span class="peq">{e(m["tipo"])} · strike {n(m.get("strike"), casas)} · {dm(m.get("vencimento"))}</span>',
                   n(m.get("ultimo"), 2), "R$ " + compacto(m.get("volume_rs"))] for m in (o_.get("mais_negociadas") or [])[:5]]
        s.append("<div><h4>Séries mais negociadas no dia</h4>"
                 + tabela(["Série", "Último", "Volume"], linhas, ["", "n", "n"]) + "</div>")
    s.append("</div></div></div>")
    return "".join(s)


def _opcoes(r: dict, ant: dict | None, hist: dict) -> str:
    def junta(res):
        if not res:
            return {}
        d = {tk: (a["opcoes"], True) for tk, a in (res.get("ativos") or {}).items() if (a.get("opcoes") or {}).get("vencimentos")}
        d.update({tk: (o_, False) for tk, o_ in (res.get("opcoes_extras") or {}).items() if o_.get("vencimentos")})
        return d
    todos, data_pos = junta(r), r["pregao"]
    if not todos and ant:
        todos, data_pos = junta(ant), ant["pregao"]
    om, d_om = _bloco(r, ant, "opcoes_mercado", lambda v: v.get("por_ativo"))
    if not todos and not om.get("por_ativo"):
        return ""
    o = ['<section id="opcoes"><h2>Opções</h2>']
    if todos:
        ordem = sorted(todos, key=lambda tk: (todos[tk][1], -((todos[tk][0].get("posicao_call") or 0) + (todos[tk][0].get("posicao_put") or 0))))
        botoes = "".join(f'<button type="button" data-aba="{e(tk)}">{e("Ibovespa" if tk.startswith("IBOV") else tk)}</button>' for tk in ordem)
        o.append(f'<div class="card"><h3>Posição em aberto por ativo</h3><p class="desc">Índice e ETF do Ibovespa primeiro, depois os ativos do livro '
                 'pela ordem de tamanho da posição. Escolha o ativo.</p>'
                 f'<div class="abas" data-abas="opcoes" role="tablist" style="margin-bottom:12px">{botoes}</div>')
        for tk in ordem:
            o.append(_painel_opcao(tk, todos[tk][0], hist, r["pregao"], data_pos, todos[tk][1]))
        o.append('<p class="explicacao"><b>Parede:</b> strike com a maior posição em aberto fora do dinheiro. Call acima do preço funciona como teto, '
                 'put abaixo como piso; perto do vencimento o preço costuma ser atraído ou travado por elas. <b>Dor máxima:</b> preço em que os '
                 'compradores de opções, somados, recebem menos no vencimento. <b>A descoberto:</b> opção lançada sem o ativo em garantia.</p></div>')
    if om.get("por_ativo"):
        o.append('<div class="g2">')
        teto = max((a["call"] + a["put"]) for a in om["por_ativo"])
        linhas = [[f'<span class="code">{e(a["ativo"])}</span>' + (' <span class="tag">livro</span>' if a.get("do_livro") else ""),
                   medidor(a["call"], teto) + compacto(a["call"]), medidor(a["put"], teto, True) + compacto(a["put"]), n(a.get("put_call"), 2)]
                  for a in om["por_ativo"]]
        o.append(f'<div class="card"><h3>Onde está a posição do mercado {tag_data(d_om, r["pregao"])}</h3>'
                 f'<p class="desc">Os 12 ativos com mais opções em aberto. Mercado inteiro: {compacto(om.get("posicao_call"))} de calls e '
                 f'{compacto(om.get("posicao_put"))} de puts (put/call de {n(om.get("put_call"), 2)}); no volume do dia, put/call de '
                 f'{n(om.get("put_call_volume"), 2)}.</p>'
                 + tabela(["Ativo", "Calls", "Puts", "Put/call"], linhas, ["", "n", "n", "n"]))
        if om.get("por_vencimento"):
            base = date.fromisoformat(r["pregao"])
            teto_v = max(c + p_ for _, c, p_ in om["por_vencimento"]) or 1.0
            cal = "".join(f'<span>{dm(v)}<small class="mut" style="margin-left:4px">{(date.fromisoformat(v) - base).days} {"dia" if (date.fromisoformat(v) - base).days == 1 else "dias"}</small></span>'
                          f'<span class="pilha" data-tip="Vencimento de {dm(v)}|calls: {compacto(c)}|puts: {compacto(p_)}">'
                          f'<i style="width:{c / teto_v * 100:.1f}%;background:var(--s1)"></i><i style="width:{p_ / teto_v * 100:.1f}%;background:var(--s2)"></i></span>'
                          f'<span class="v">{compacto(c + p_)}</span>' for v, c, p_ in om["por_vencimento"][:6])
            o.append('<h4 style="margin-top:14px">Calendário: quanto vence em cada data</h4>'
                     '<div class="legenda" style="margin-top:6px"><span><i style="background:#1c5c99"></i>calls</span>'
                     f'<span><i style="background:#c2702a"></i>puts</span></div><div class="bh">{cal}</div>')
        o.append("</div>")
        if om.get("maiores_altas"):
            def linhas_de(itens):
                return [[f'<span class="code">{e(m["codigo"])}</span><span class="peq">{e(m["ativo"])} · {e(m["tipo"])} · strike {n(m.get("strike"), 2)} · {dm(m.get("vencimento"))}</span>',
                         f'<span class="{cls(m["variacao"])}">{n(m["variacao"] / 1e6, 2, True)} mi</span>', compacto(m.get("posicao"))] for m in itens[:7]]
            o.append(f'<div class="card"><h3>Maiores mudanças de posição no dia {tag_data(d_om, r["pregao"])}</h3>'
                     f'<p class="desc">Séries que mais ganharam e mais perderam opções em aberto contra {dm(om.get("comparado_com"))}. '
                     'Mesmo strike em call e put ao mesmo tempo costuma ser operação estruturada.</p>'
                     '<h4>Ganharam posição</h4>' + tabela(["Série", "Variação", "Em aberto"], linhas_de(om["maiores_altas"]), ["", "n", "n"])
                     + '<h4 style="margin-top:12px">Perderam posição</h4>'
                     + tabela(["Série", "Variação", "Em aberto"], linhas_de(om.get("maiores_quedas") or []), ["", "n", "n"]) + "</div>")
        o.append("</div>")
    o.append("</section>")
    return "".join(o)


def _taxa_rf(l: dict) -> str:
    t, c = l.get("taxa_media"), l.get("convencao")
    if t is None:
        return '<span class="mut">sem taxa</span>'
    if c == "% do CDI":
        return f"{n(t, 1)}% do CDI"
    if c == "Pré":
        return f"{n(t, 2)}% pré"
    return f"{e(c or '')} {n(t, 2)}%"


def _renda_fixa(r: dict) -> str:
    rf = r.get("renda_fixa") or {}
    if not rf.get("resumo"):
        return ""
    res = rf["resumo"]
    o = ['<section id="renda-fixa"><h2>Renda fixa: debêntures incentivadas, CRI e CRA</h2>']
    tiles = []
    for cl in ("deb_incentivada", "cri", "cra"):
        v = res.get(cl)
        if not v:
            continue
        extras = []
        if v.get("taxa_ipca_media") is not None:
            extras.append(f"IPCA+ médio {n(v['taxa_ipca_media'], 2)}%")
        if v.get("premio_dap_medio_pb") is not None:
            extras.append(f"{n(v['premio_dap_medio_pb'], 0, True)} pb sobre o juro real")
        if v.get("premio_cdi_medio") is not None:
            extras.append(f"CDI+ médio {n(v['premio_cdi_medio'], 2)}%")
        x = v.get("volume_x_media")
        tiles.append(f'<div class="card"><h4>{e(ROTULO_RF[cl])}</h4>'
                     f'<div style="font-size:22px;font-weight:650;margin-top:2px">R$ {compacto(v.get("volume_rs"), 2)}</div>'
                     f'<p class="desc">{n(v.get("negocios"), 0)} negócios em {n(v.get("papeis"), 0)} papéis'
                     + (f" · {n(x, 1)}x a média" if x else "") + "</p>"
                     + (f'<p style="font-size:13.5px;margin-top:6px">{" · ".join(extras)}</p>' if extras else "")
                     + (f'<p class="desc" style="margin-top:4px">Por indexador: '
                        + ", ".join(f"{e(k)} {n(p_, 0)}%" for k, p_ in list((v.get("por_indexador_pct") or {}).items())[:3]) + "</p>") + "</div>")
    o.append(f'<div class="g3">{"".join(tiles)}</div>')
    g, fora = svg_dispersao(rf.get("curva") or [], rf.get("dap") or [])
    if g:
        inc = res.get("deb_incentivada") or {}
        lado = []
        if inc.get("taxa_ipca_media") is not None:
            lado.append(f'<div class="tile"><div class="rot">Taxa média do dia</div><div class="val">IPCA + {n(inc["taxa_ipca_media"], 2)}%</div>'
                        '<div class="pe">ponderada pelo volume</div></div>')
        if inc.get("premio_dap_medio_pb") is not None:
            lado.append(f'<div class="tile"><div class="rot">Prêmio médio sobre o juro real</div><div class="val">{n(inc["premio_dap_medio_pb"], 0, True)} pb</div>'
                        '<div class="pe">contra o DAP de prazo equivalente</div></div>')
        lado.append(f'<div class="tile"><div class="rot">Papéis no gráfico</div><div class="val">{len(rf.get("curva") or [])}</div>'
                    '<div class="pe">indexados ao IPCA, acima do volume mínimo</div></div>')
        o.append('<div class="card"><h3>Curva de crédito das debêntures incentivadas</h3>'
                 '<p class="desc">Cada círculo é uma debênture incentivada indexada ao IPCA negociada no dia: prazo até o vencimento na horizontal, '
                 'taxa média do dia na vertical, tamanho pelo volume. A linha é o juro real de mercado (DAP). Passe o dedo ou o mouse para ver o papel.</p>'
                 f'<div class="duo"><div><figure>{g}</figure>'
                 + (f'<p class="desc">▲ {fora} {"papel ficou" if fora == 1 else "papéis ficaram"} acima da escala; estão na tabela de prêmios altos.</p>' if fora else "")
                 + f'</div><div class="col" style="gap:8px">{"".join(lado)}'
                 + '<p class="explicacao" style="margin-top:2px"><b>Como ler:</b> a distância vertical entre o círculo e a linha é o prêmio de crédito. '
                   'Papel muito acima da linha é o mercado pedindo mais para carregar aquele risco. A comparação é por vencimento, não por duration: '
                   'papel que amortiza tem prazo médio menor que o vencimento, então é aproximação.</p></div></div></div>')

    def tab_papeis(itens, n_max=12):
        linhas = []
        for l in itens[:n_max]:
            var = l.get("var_taxa_pb")
            linhas.append([f'<span class="code">{e(l["codigo"])}</span><span class="peq">{e(nome_curto(l["emissor"]))}</span>',
                           _taxa_rf(l) + (f'<span class="peq">emissão {n(l.get("taxa_emissao"), 2)}%</span>' if l.get("taxa_emissao") is not None else ""),
                           (f'<span class="{cls(-(l["premio_dap_pb"]))}">{n(l["premio_dap_pb"], 0, True)} pb</span>' if l.get("premio_dap_pb") is not None else "–")
                           + (f'<span class="peq">taxa {n(var, 0, True)} pb vs {dm(l.get("comparado_com"))}</span>' if var is not None else ""),
                           (l.get("vencimento") or "–")[:4] + (f'<span class="peq">{n(l.get("prazo_anos"), 1)} anos</span>' if l.get("prazo_anos") else ""),
                           "R$ " + compacto(l.get("volume_rs")) + f'<span class="peq">{n(l.get("negocios"), 0)} negócios</span>'])
        return tabela(["Papel e emissor", "Taxa do dia", "Sobre o juro real", "Vencimento", "Volume"], linhas, ["", "n", "n", "n", "n"])

    abas = [(cl, ROTULO_RF[cl]) for cl in ("deb_incentivada", "cri", "cra") if (rf.get("papeis") or {}).get(cl)]
    if abas:
        botoes = "".join(f'<button type="button" data-aba="{cl}">{e(rot)}</button>' for cl, rot in abas)
        o.append('<div class="card"><h3>Mais negociados do dia</h3><p class="desc">Taxa média ponderada pelo volume; ao lado, a taxa da emissão. '
                 'Em CRI e CRA o emissor que a B3 informa é a securitizadora.</p>'
                 f'<div class="abas" data-abas="rf" role="tablist" style="margin-bottom:8px">{botoes}</div>')
        for cl, _ in abas:
            o.append(f'<div data-painel="rf" data-id="{cl}">{tab_papeis(rf["papeis"][cl])}</div>')
        o.append("</div>")
    o.append('<div class="g2">')
    if rf.get("aberturas") or rf.get("fechamentos"):
        def mov(itens):
            return [[f'<span class="code">{e(l["codigo"])}</span><span class="peq">{e(nome_curto(l["emissor"], 26))} · {e(ROTULO_RF.get(l["classe"], ""))}</span>',
                     f'<span class="{cls(-l["var_taxa_pb"])}">{n(l["var_taxa_pb"], 0, True)} pb</span><span class="peq">vs {dm(l.get("comparado_com"))}</span>',
                     _taxa_rf(l), "R$ " + compacto(l.get("volume_rs"))] for l in itens[:6]]
        o.append('<div class="card"><h3>Quem abriu e quem fechou taxa</h3><p class="desc">Taxa média do dia contra o último pregão em que o papel '
                 'negociou acima do volume mínimo. Taxa abrindo é preço caindo.</p><h4>Abriram</h4>'
                 + tabela(["Papel", "Variação", "Taxa do dia", "Volume"], mov(rf.get("aberturas") or []), ["", "n", "n", "n"])
                 + '<h4 style="margin-top:12px">Fecharam</h4>'
                 + tabela(["Papel", "Variação", "Taxa do dia", "Volume"], mov(rf.get("fechamentos") or []), ["", "n", "n", "n"]) + "</div>")
    if rf.get("premios_altos"):
        linhas = [[f'<span class="code">{e(l["codigo"])}</span><span class="peq">{e(nome_curto(l["emissor"], 26))} · {e(ROTULO_RF.get(l["classe"], ""))}</span>',
                   _taxa_rf(l), (n(l["premio_dap_pb"], 0, True) + " pb") if l.get("premio_dap_pb") is not None else "–",
                   "R$ " + compacto(l.get("volume_rs"))] for l in rf["premios_altos"][:8]]
        o.append('<div class="card"><h3>Onde o mercado pede prêmio alto</h3><p class="desc">Papéis negociados com prêmio de 300 pontos-base ou mais '
                 'sobre o juro real, ou CDI + 5% ou mais. Em volume pequeno o preço pode ser de um negócio isolado.</p>'
                 + tabela(["Papel", "Taxa do dia", "Sobre o juro real", "Volume"], linhas, ["", "n", "n", "n"]) + "</div>")
    if rf.get("emissores_incentivadas"):
        linhas = [[e(nome_curto(x["emissor"], 36)) + f'<span class="peq">{n(x["papeis"], 0)} {"papel" if x["papeis"] == 1 else "papéis"} · {n(x["negocios"], 0)} negócios</span>',
                   (f'IPCA+ {n(x["taxa_ipca_media"], 2)}%') if x.get("taxa_ipca_media") is not None else "–",
                   (n(x["premio_dap_medio_pb"], 0, True) + " pb") if x.get("premio_dap_medio_pb") is not None else "–",
                   "R$ " + compacto(x.get("volume_rs"))] for x in rf["emissores_incentivadas"][:8]]
        o.append('<div class="card"><h3>Emissores de incentivadas mais negociados</h3><p class="desc">Todas as séries do emissor somadas; '
                 'taxa média ponderada pelo volume das séries indexadas ao IPCA.</p>'
                 + tabela(["Emissor", "Taxa média", "Sobre o juro real", "Volume"], linhas, ["", "n", "n", "n"]) + "</div>")
    if rf.get("maiores_negocios"):
        linhas = [[f'<span class="code">{e(m["codigo"])}</span><span class="peq">{e(nome_curto(m["emissor"], 26))} · {e(ROTULO_RF.get(m["classe"], "debênture"))}</span>',
                   (_taxa_rf({"taxa_media": m.get("taxa"), "convencao": m.get("convencao")})), e(str(m.get("hora") or "–")[:5]),
                   "R$ " + compacto(m.get("volume_rs"))] for m in rf["maiores_negocios"][:8]]
        o.append('<div class="card"><h3>Maiores negócios do dia</h3><p class="desc">Os maiores lotes fechados em debêntures, CRI e CRA. '
                 'Negócio grande sem taxa costuma ser registro de oferta ou transferência.</p>'
                 + tabela(["Papel", "Taxa", "Hora", "Volume"], linhas, ["", "n", "n", "n"]) + "</div>")
    est, comp = rf.get("estoque") or {}, rf.get("compromissadas") or {}
    if est:
        nomes = {"DEB": "Debêntures (todas)", "CRI": "CRI", "CRA": "CRA"}
        linhas = [[nomes.get(k, k), "R$ " + compacto(v.get("volume_em_mercado_rs")), n(v.get("instrumentos"), 0),
                   ("R$ " + compacto((comp.get(k) or {}).get("volume_rs"))) if comp.get(k) else "–"] for k, v in est.items()]
        o.append('<div class="card"><h3>Tamanho do mercado</h3><p class="desc">Estoque em mercado e compromissadas do dia com lastro em cada instrumento, '
                 f'segundo a B3. Cadastro lido para {n(rf.get("cobertura_cadastro_pct"), 0)}% do volume negociado.</p>'
                 + tabela(["Instrumento", "Estoque em mercado", "Papéis", "Compromissadas no dia"], linhas, ["", "n", "n", "n"]) + "</div>")
    o.append("</div></section>")
    return "".join(o)


def _eventos(r: dict, ant: dict | None) -> str:
    at = r.get("ativos") or {}
    o = []
    etfs = [(tk, a["etf"]) for tk, a in at.items() if a.get("etf")]
    if etfs:
        linhas = [[f'<span class="code">{e(tk)}</span>', n(x.get("iopv")), pc(x.get("premio_pct")), compacto(x.get("cotas")),
                   ("0" if not x.get("var_cotas") else n(x["var_cotas"], 0, True)) if x.get("var_cotas") is not None else "–"] for tk, x in etfs]
        par = "".join(f'<p class="desc" style="margin-top:8px"><b>Paridade:</b> {e(x["ativo"])} fez {n(x["oscilacao_pct"], 2, True)}% contra '
                      f'{n(x["referencia_em_reais_pct"], 2, True)}% de {e(x["referencia"])} em reais (lá fora {n(x["referencia_pct"], 2, True)}%, câmbio '
                      f'{n(x["cambio_pct"], 2, True)}%). Desvio de {n(x["desvio_pct"], 2, True)} ponto; fechamentos em horários diferentes.</p>'
                      for x in r.get("paridades") or [])
        o.append('<div class="card"><h3>ETFs do livro</h3><p class="desc">Fechamento contra o valor de referência da cota (IOPV) e cotas emitidas.</p>'
                 + tabela(["ETF", "Cota (IOPV)", "Prêmio", "Cotas", "Criadas no dia"], linhas, ["", "n", "n", "n", "n"]) + par + "</div>")
    adr = [(tk, a["adr"]) for tk, a in at.items() if a.get("adr") and (a["adr"].get("pct_da_classe") or 0) >= 0.5]
    d_adr = r["pregao"]
    if not adr and ant:
        adr = [(tk, a["adr"]) for tk, a in (ant.get("ativos") or {}).items() if a.get("adr") and (a["adr"].get("pct_da_classe") or 0) >= 0.5]
        d_adr = ant["pregao"]
    if adr:
        linhas = [[f'<span class="code">{e(tk)}</span>', n(x["acoes_em_adr"] / 1e6, 1), n(x.get("pct_da_classe"), 1) + "%",
                   (f'<span class="{cls(x["var"])}">{n(x["var"] / 1e6, 2, True)}</span>' if x.get("var") else "0") if x.get("var") is not None else "–"]
                  for tk, x in adr]
        o.append(f'<div class="card"><h3>Ações do livro em Nova York (ADR) {tag_data(d_adr, r["pregao"])}</h3>'
                 '<p class="desc">Ações custodiadas no programa de recibos. Entrada de ações no programa indica compra lá fora; saída, venda.</p>'
                 + tabela(["Ativo", "Em ADR (mi)", "Da classe", "No pregão (mi)"], linhas, ["", "n", "n", "n"]) + "</div>")
    ev = r.get("eventos") or {}
    itens = [f'<li><span class="code">{e(x["ativo"])}</span>: {e((x.get("tipo") or "provento").lower())}'
             + (f' de R$ {n(x["valor"], 4)}, crédito em {dm(x.get("credito_em"))}' if x.get("valor") is not None else f', prazo em {dm(x.get("prazo_deposito"))}') + "</li>"
             for x in ev.get("proventos") or []]
    itens += [f'<li><span class="code">{e(x["ativo"])}</span>: subscrição, prazo final em {dm(x.get("prazo_subscricao"))}</li>' for x in ev.get("subscricoes") or []]
    if r.get("previa_indice"):
        pv = r["previa_indice"]
        itens.append(f'<li>{pv["previa"]}ª prévia do Ibovespa: entram {e(", ".join(pv["entram"]) or "ninguém")}; saem {e(", ".join(pv["saem"]) or "ninguém")}</li>')
    for x in r.get("informativos") or []:
        marca = (" <b>[" + e(", ".join(x["ativos_do_livro"])) + "]</b>") if x.get("ativos_do_livro") else ""
        link = f' <a href="{e(x["link"])}" target="_blank" rel="noopener">abrir</a>' if x.get("link") else ""
        itens.append(f'<li>Comunicado de {dm(x.get("data"))}: {e(x["titulo"])}{marca}{link}</li>')
    if itens:
        o.append(f'<div class="card"><h3>Proventos, índices e comunicados</h3><ul style="margin:6px 0 0;padding-left:20px;font-size:14px">{"".join(itens)}</ul></div>')
    if not o:
        return ""
    return f'<section id="eventos"><h2>ETFs, ADR e eventos</h2><div class="g2">{"".join(o)}</div></section>'


def _rodape(r: dict) -> str:
    sit = r["situacao"]
    itens = [f"<li>{e(NOME_PENDENTE.get(k, k))}: {e(v)}</li>" for k, v in (sit.get("pendentes") or {}).items()]
    if sit.get("publicadas_com_atraso"):
        itens.append("<li>Publicadas pela B3 depois do prazo, mas com dado: " + e(", ".join(sit["publicadas_com_atraso"])) + "</li>")
    itens += [f"<li>{e(x)}</li>" for x in r.get("lacunas") or []]
    pdf = sit.get("boletim_completo_pdf")
    return ('<section id="fontes"><h2>Lacunas, fontes e termos</h2><div class="card rodape">'
            f'<h4>Lacunas e pendências deste pregão</h4><ul>{"".join(itens)}</ul>'
            f'<h4 style="margin-top:10px">Fonte</h4><p>{e(r["fonte"])}. Coleta de {e(r["gerado_em"])} (UTC). '
            + (f'Boletim completo em PDF na B3: <a href="{e(pdf)}" target="_blank" rel="noopener">abrir</a>. ' if pdf else "")
            + 'Cada card traz a data do dado quando ela não é a do pregão.</p>'
            '<details><summary>Termos desta página</summary><ul>'
            '<li><b>Aluguel de ações (BTC):</b> empréstimo de ações registrado na B3; o tomador paga uma taxa ao ano e quase sempre vende a ação.</li>'
            '<li><b>Ações em circulação:</b> aqui, a quantidade teórica da carteira de índice da B3, que exclui o controlador.</li>'
            '<li><b>Posição em aberto:</b> contratos ou opções que ainda não foram encerrados nem venceram.</li>'
            '<li><b>Call e put:</b> opção de compra e opção de venda. <b>Strike:</b> preço de exercício.</li>'
            '<li><b>DI futuro e DAP:</b> contratos da B3 que mostram a taxa prefixada e o juro real (acima do IPCA) esperados para cada prazo.</li>'
            '<li><b>pb:</b> ponto-base, 0,01 ponto percentual.</li>'
            '<li><b>Debênture incentivada:</b> emitida pela Lei 12.431 para infraestrutura; rendimento isento de IR para pessoa física.</li>'
            '<li><b>CRI e CRA:</b> certificados de recebíveis imobiliários e do agronegócio; também isentos para pessoa física.</li>'
            '<li><b>IOPV:</b> valor de referência da cota do ETF calculado pela B3 a partir da carteira.</li>'
            '<li><b>ADR:</b> recibo de ação brasileira negociado em Nova York.</li></ul></details></div>'
            '<div class="disclaimer">Material de análise e estudo, produzido para uso pessoal a partir de dados públicos da B3. Não constitui recomendação '
            'de investimento nos termos da regulamentação da CVM. Preços, taxas e códigos devem ser confirmados na corretora antes de qualquer ordem; '
            'o dado gratuito da B3 é o do negócio realizado, sem oferta de compra e venda. Opções podem perder 100% do valor investido. Decisão e '
            'execução são de responsabilidade do leitor.</div></section>')


def pagina(r: dict, hist: dict, anterior: dict | None = None) -> str:
    """HTML do painel do pregao `r`. `anterior` e o resumo do pregao de antes, usado so nos blocos
    que a B3 ainda nao publicou para `r` (e sempre com a data escrita no card)."""
    hist = hist or {}
    if anterior and anterior.get("pregao", "") >= r["pregao"]:
        anterior = None
    usa_ant = anterior if not r["situacao"]["completo"] else None
    corpo = [_cabecalho(r, usa_ant), _kpis(r, usa_ant)]
    secoes = [("leitura", "Leitura", '<section id="leitura"><h2>Leitura da mesa</h2><div class="card card-destaque"><div class="leitura">'
               + MARCADOR_LEITURA + "</div></div></section>"),
              ("sinais", "Sinais", _sinais(r)), ("mercado", "Mercado", _mercado(r)), ("fluxo", "Fluxo", _fluxo(r, hist)),
              ("juros", "Juros e dólar", _juros(r, usa_ant, hist)), ("livro", "Livro", _livro(r, usa_ant, hist)),
              ("aluguel", "Aluguel", _aluguel(r, usa_ant, hist)), ("opcoes", "Opções", _opcoes(r, usa_ant, hist)),
              ("renda-fixa", "Renda fixa", _renda_fixa(r)), ("eventos", "Eventos", _eventos(r, usa_ant)),
              ("fontes", "Fontes", _rodape(r))]
    volume = _radar_volume(r)
    nav = "".join(f'<a href="#{i}">{e(t)}</a>' for i, t, h in secoes if h)
    corpo.append(f'<nav class="indice" aria-label="Seções">{nav}</nav>')
    for i, _, h in secoes:
        if i == "livro" and h and volume:
            h = h.replace("</section>", volume + "</section>")
        corpo.append(h)
    d = date.fromisoformat(r["pregao"])
    return (f"<title>Boletim B3</title>\n<style>{CSS}</style>\n"
            f'<div class="wrap" data-pregao="{e(r["pregao"])}">{"".join(corpo)}</div>\n<script>{JS}</script>\n'
            f"<!-- pregao {d.isoformat()} -->\n")
