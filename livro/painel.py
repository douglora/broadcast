"""Painel HTML do livro: a mesma coleta do Fechamento virada pagina.

Gera saida/painel.html, que a sessao publica como Artifact para o Douglas abrir
no PC ou fixar no celular. O runner escreve todos os numeros; a sessao so troca
o marcador da Leitura da Mesa pelo texto dela. Nada e calculado aqui: tudo vem
de janelas/series_info/insumos, os mesmos que alimentam o BLOCO A e o BLOCO B.
"""

from __future__ import annotations

import html
import re
from datetime import date

from livro import fmt
from livro import qualidade as qa
from livro import atribuicao

MARCADOR_LEITURA = "[[LEITURA_DA_MESA]]"

# escala do termometro da coluna 'dia': 4% de variacao enche a barra
ESCALA_DIA = 0.04

TITULOS_CURVA = {"di": "DI futuro (B3)", "tesouro": "Tesouro Direto", "ust": "Treasury (EUA)"}

FONTES_GOOGLE = ("https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600"
                 "&family=IBM+Plex+Sans:wght@400;500;600&family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600"
                 "&display=swap")

# Tema claro unico e proposital: o Douglas le o chat no escuro e quer o painel
# branco do lado. A pagina nao herda o tema de quem abre; ela pinta tudo.
CSS = """
:root{
  color-scheme: light;
  --papel:#F2F1ED; --carta:#FFFFFF; --tinta:#14151A; --meio:#4A4D57; --fraco:#7A7D87;
  --linha:#E7E5DF; --linha-forte:#D6D3CA; --leve:#F8F7F4;
  --alta:#0A6B45; --baixa:#A5190F; --atencao:#8A5200; --mesa:#16324F;
  --sans:"IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  --serif:Newsreader,Georgia,"Times New Roman",serif;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
body{background:var(--papel);color:var(--tinta);font-family:var(--sans);font-size:15px;line-height:1.5;
  padding-inline:18px;padding-block:24px 48px;-webkit-text-size-adjust:100%;
  -webkit-font-smoothing:antialiased;}
main{max-width:1200px;margin:0 auto;display:flex;flex-direction:column;gap:16px;}
h1,h2,h3{margin:0;text-wrap:balance;}
p{margin:0;}
a{color:var(--mesa);text-underline-offset:2px;}
a:focus-visible{outline:2px solid var(--mesa);outline-offset:2px;}

/* ---------- cabecalho ---------- */
.topo{padding-bottom:14px;border-bottom:2px solid var(--tinta);}
.topo .faixa{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 14px;font-family:var(--mono);
  font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--fraco);}
.topo .marca{color:var(--mesa);font-weight:600;}
.topo .hora{text-transform:none;letter-spacing:.02em;margin-left:auto;}
.topo .parcial{color:var(--atencao);border:1px solid currentColor;border-radius:2px;
  padding:1px 6px;letter-spacing:.06em;}
.topo h1{font-family:var(--serif);font-size:clamp(28px,7vw,42px);font-weight:500;
  letter-spacing:-.02em;line-height:1.05;margin-top:10px;}

/* ---------- cartoes ---------- */
.cartao{background:var(--carta);border:1px solid var(--linha);border-radius:3px;padding:18px 20px;
  min-width:0;}   /* item de grid nao pode crescer com a tabela e empurrar a pagina */
.cartao h2{font-family:var(--sans);font-size:11.5px;font-weight:600;letter-spacing:.11em;
  text-transform:uppercase;color:var(--mesa);display:flex;flex-wrap:wrap;align-items:baseline;
  gap:6px 12px;padding-bottom:11px;border-bottom:1px solid var(--linha-forte);margin-bottom:14px;}
.cartao h2 .conta{margin-left:auto;font-family:var(--mono);font-size:11px;letter-spacing:.02em;
  text-transform:none;color:var(--fraco);font-weight:400;font-variant-numeric:tabular-nums;}
.cartao h2 .conta b{font-weight:600;}
.nota{font-size:13px;color:var(--meio);margin-top:9px;}
.nota b{color:var(--tinta);font-weight:600;}
.vazio{font-size:14px;color:var(--fraco);}

/* ---------- leitura da mesa ---------- */
.leitura{padding:22px 24px;}
.texto-leitura{font-family:var(--serif);font-size:17.5px;line-height:1.62;max-width:64ch;color:var(--tinta);}
.texto-leitura p{margin-bottom:12px;}
.texto-leitura p:last-child{margin-bottom:0;}
.texto-leitura strong{font-weight:600;}

/* ---------- fita de destaques ---------- */
.movers{display:flex;flex-wrap:wrap;gap:18px 32px;padding:14px 20px;}
.movers .lado{flex:1 1 260px;display:flex;flex-wrap:wrap;align-items:baseline;gap:8px;}
.movers h3{font-size:10.5px;font-weight:600;letter-spacing:.11em;text-transform:uppercase;
  color:var(--fraco);width:100%;margin-bottom:2px;}
.mvs{display:flex;flex-wrap:wrap;gap:7px 16px;width:100%;}
.mv{font-family:var(--mono);font-size:13px;font-variant-numeric:tabular-nums;white-space:nowrap;}
.mv b{font-weight:600;margin-right:6px;color:var(--tinta);}

/* ---------- tabelas por bloco ---------- */
/* um cartao por linha: a tabela tem 10 colunas e em grade de 3 elas se espremem
   ate o numero colar no vizinho */
.grade{display:flex;flex-direction:column;gap:16px;min-width:0;}
.rolagem{overflow-x:auto;max-width:100%;}
table{width:100%;border-collapse:collapse;font-size:13.5px;}
thead th{font-family:var(--mono);font-size:10px;font-weight:500;letter-spacing:.06em;
  text-transform:uppercase;color:var(--fraco);text-align:right;padding:0 10px 9px;white-space:nowrap;}
thead th:first-child{text-align:left;padding-left:0;}
/* regua vertical entre as colunas: sem ela o olho perde a janela a que o numero
   pertence, e YTD e 5 anos parecem um numero so */
thead th+th,tbody td{border-left:1px solid var(--linha);}
thead th:nth-child(2),tbody td:first-of-type{border-left:1px solid var(--linha-forte);}
thead tr{border-bottom:1px solid var(--linha-forte);}
tbody th{text-align:left;font-weight:600;padding:7px 12px 7px 0;vertical-align:baseline;}
tbody tr+tr th,tbody tr+tr td{border-top:1px solid var(--linha);}
tbody tr:hover th,tbody tr:hover td{background:var(--leve);}
.tk{font-family:var(--mono);font-size:12.5px;font-weight:600;letter-spacing:.01em;}
.nm{display:block;font-weight:400;font-size:11.5px;color:var(--fraco);line-height:1.35;max-width:30ch;}
.atraso{display:inline-block;font-size:9.5px;color:var(--atencao);border:1px solid currentColor;
  border-radius:2px;padding:0 4px;margin-top:4px;letter-spacing:.04em;text-transform:uppercase;}
td.n{font-family:var(--mono);font-size:13px;font-variant-numeric:tabular-nums;text-align:right;
  padding:7px 10px;white-space:nowrap;color:var(--meio);min-width:54px;}
td.ult{color:var(--tinta);font-weight:500;}
td.dia{position:relative;font-weight:600;}
td.dia .barra{position:absolute;right:0;top:50%;transform:translateY(-50%);height:1.7em;
  width:var(--w);background:currentColor;opacity:.10;border-radius:2px;}
td.dia .v{position:relative;}
.alta{color:var(--alta);}
.baixa{color:var(--baixa);}
.zero,.nulo{color:var(--fraco);}

/* ---------- curvas ---------- */
.curvas{display:flex;flex-direction:column;gap:20px;}
.curva h3{font-size:10.5px;font-weight:600;letter-spacing:.11em;text-transform:uppercase;
  color:var(--fraco);margin-bottom:10px;display:flex;gap:8px;align-items:baseline;}
.curva h3 .quando{font-family:var(--mono);font-size:10px;letter-spacing:.02em;text-transform:none;}
.chips{display:flex;flex-wrap:wrap;gap:8px;}
.chip{display:flex;flex-direction:column;gap:2px;min-width:92px;padding:8px 11px;background:var(--leve);
  border:1px solid var(--linha);border-radius:3px;font-variant-numeric:tabular-nums;}
.chip .cr{font-family:var(--mono);font-size:9.5px;letter-spacing:.08em;color:var(--fraco);text-transform:uppercase;}
.chip .ct{font-family:var(--mono);font-size:17px;font-weight:600;line-height:1.1;letter-spacing:-.01em;}
.chip .cd{font-family:var(--mono);font-size:10.5px;color:var(--fraco);}
.chip .cd.forte{color:var(--mesa);font-weight:600;}
.verbo{color:var(--mesa);letter-spacing:.08em;font-weight:600;}

/* ---------- alertas ---------- */
.alerta{border-left:3px solid var(--baixa);background:var(--leve);padding:13px 16px;
  border-radius:0 3px 3px 0;margin-bottom:12px;}
.alerta .cab,.noticia .cab{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-bottom:6px;}
.sev{font-family:var(--mono);font-size:9.5px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;
  color:#fff;background:var(--baixa);padding:2px 7px;border-radius:2px;}
.sev.at{background:var(--atencao);}
.regra{font-family:var(--mono);font-size:10.5px;color:var(--fraco);letter-spacing:.04em;}
.ativo{font-family:var(--mono);font-size:12px;font-weight:600;}
.alerta .tit,.noticia .tit{font-size:15px;font-weight:600;line-height:1.4;max-width:68ch;letter-spacing:-.005em;}
.corpo{margin:9px 0 0;padding-left:17px;font-size:12.5px;color:var(--meio);}
.corpo li{margin-bottom:3px;}
.porque{font-size:12.5px;color:var(--meio);margin-top:9px;max-width:68ch;}
.porque::before{content:"Por que importa ";color:var(--mesa);font-weight:600;
  font-size:10px;letter-spacing:.09em;text-transform:uppercase;}
.revisto{font-size:12.5px;color:var(--atencao);margin-top:9px;max-width:68ch;font-style:italic;}
.fonte{font-family:var(--mono);font-size:10.5px;color:var(--fraco);margin-top:8px;}
.lista-alertas{list-style:none;margin:0;padding:0;}
.lista-alertas li{display:flex;flex-wrap:wrap;align-items:baseline;gap:9px;padding:9px 0;
  border-top:1px solid var(--linha);}
.lista-alertas .txt{flex:1 1 220px;font-size:13.5px;line-height:1.45;}

/* ---------- noticias e agenda ---------- */
.noticia{padding:13px 0;border-top:1px solid var(--linha);}
.noticia:first-of-type{border-top:0;padding-top:0;}
.veiculo{font-size:10.5px;font-weight:600;color:var(--mesa);background:var(--leve);
  border:1px solid var(--linha);border-radius:2px;padding:2px 7px;letter-spacing:.02em;}
.noticia .quando,.lic{font-family:var(--mono);font-size:10px;color:var(--fraco);letter-spacing:.03em;}
.link{display:inline-block;margin-top:8px;font-size:12.5px;font-weight:500;}
.lista-agenda{list-style:none;margin:0;padding:0;}
.lista-agenda li{display:flex;flex-wrap:wrap;align-items:baseline;gap:12px;padding:8px 0;
  border-top:1px solid var(--linha);}
.lista-agenda li:first-child{border-top:0;}
.lista-agenda .quando{font-family:var(--mono);font-size:12px;font-weight:600;min-width:70px;
  font-variant-numeric:tabular-nums;}
.lista-agenda .hora{font-family:var(--mono);font-size:12px;color:var(--fraco);font-variant-numeric:tabular-nums;}
.lista-agenda .txt{flex:1 1 200px;font-size:13.5px;}

/* ---------- rodape ---------- */
.rodape{background:transparent;border:0;border-top:1px solid var(--linha-forte);border-radius:0;
  padding:18px 2px 0;}
.rodape h2{color:var(--fraco);border-bottom:0;padding-bottom:0;margin-bottom:8px;}
.rodape .nota{margin-top:8px;font-size:12.5px;}
.legenda{font-size:11.5px;line-height:1.5;border-top:1px solid var(--linha);padding-top:10px;}
.rodape .lacuna b{color:var(--atencao);}
.alerta-nota{border-left:2px solid var(--atencao);padding-left:10px;}
.aviso{font-size:11.5px;font-style:italic;color:var(--fraco);margin-top:14px;}
.atraso.evento{color:var(--mesa);margin-left:4px;}
.correcao{background:#8C1C13;color:#fff;padding:14px 18px;border-radius:6px;font-weight:600;line-height:1.45}
.correcao span{display:block;font-weight:400;opacity:.93;margin-top:4px;font-size:.93em}
.errado{display:inline-block;font-size:9.5px;color:#fff;background:var(--baixa);border-radius:2px;padding:1px 5px;margin-top:4px;letter-spacing:.04em;text-transform:uppercase}
.mv .ctx{display:block;font-size:10.5px;font-weight:400;color:var(--fraco);white-space:normal;}
td.txt{font-size:13px;color:var(--meio);text-align:left;white-space:normal;padding:7px 10px;min-width:18ch;}
td.grau{font-family:var(--mono);font-size:11px;min-width:9ch;}

@media (max-width:620px){
  body{padding-inline:14px;padding-block:18px 36px;}
  /* nada de esconder coluna nem comprimir: o Douglas le no painel estreito e quer
     6 m, 1 ano e 5 anos legiveis. A tabela rola dentro do cartao, com a coluna do
     ativo fixa para nao se perder a linha; a pagina nao rola de lado. */
  tbody th{position:sticky;left:0;background:var(--carta);z-index:1;}
  tbody tr:hover th{background:var(--leve);}
  .nm{max-width:16ch;}
  .nm{max-width:20ch;}
  .cartao{padding:15px 16px;}
  .leitura{padding:18px 17px;}
  .texto-leitura{font-size:16.5px;}
  .topo .hora{margin-left:0;}
}
"""


def _e(x) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def _sinal(v) -> str:
    """Segue o numero que aparece na tela: o que arredonda para 0,0% e neutro."""
    if v is None:
        return "nulo"
    if abs(round(v * 100, 1)) < 0.05:
        return "zero"
    return "alta" if v > 0 else "baixa"


def _larg(v) -> int:
    """Termometro da coluna 'dia'; abaixo de 0,5% nao vale a tinta."""
    if v is None or abs(v) < 0.005:
        return 0
    return max(10, min(100, round(abs(v) / ESCALA_DIA * 100)))


def _cel(v, classe: str = "") -> str:
    return f'<td class="n {classe} {_sinal(v)}">{_e(fmt.pct(v))}</td>'


def nome_curto(a) -> str:
    """Mesmo corte dos cards: tira o jargao do involucro e o parentese, que sao o
    que faz a celula do nome virar um paragrafo de seis linhas."""
    n = a.nome or a.apelido or a.id
    return n.split(" UCITS")[0].split(" (")[0].strip()


def _linha_ativo(a, j: dict, info: dict) -> str:
    # mesmo vocabulario do card (livro/qualidade.py): "dia dd/mm", "2 pregões",
    # "parcial", "D-1", ou "dado a confirmar" sem numero
    rot, ocultar = qa.marcador(j, info)
    dia = None if ocultar else j.get("dia")
    atraso = ""
    if rot:
        motivos = "; ".join(((info.get("qualidade") or {}).get("motivos") or [])[:2])
        titulo = motivos or ("minério CME liquida com um pregão de atraso" if rot.startswith("D-1")
                             else f"sem barra de {fmt.data_br(info.get('esperado'))} — ultima {fmt.data_br(j.get('data'))}")
        atraso = f'<span class="atraso" title="{_e(titulo)}">{_e(rot)}</span>'
    nome = f'<span class="nm">{_e(nome_curto(a))}</span>' if a.nome and a.nome != a.apelido else ""
    for x in (j.get("extremo_52s"), j.get("proximo_evento")):
        if x:
            atraso += f'<span class="atraso evento">{_e(x)}</span>'
    return (
        "<tr>"
        f'<th scope="row"><span class="tk">{_e(a.id)}</span>{nome}{atraso}</th>'
        f'<td class="n ult">{"a confirmar" if ocultar else _e(fmt.preco(j.get("ultimo"), a.decimais))}</td>'
        f'<td class="n dia {_sinal(dia)}"><span class="barra" style="--w:{_larg(dia)}%"></span>'
        f'<span class="v">{"a confirmar" if ocultar else _e(fmt.pct(dia))}</span></td>'
        + "".join(_cel(None if ocultar else j.get(k)) for k in ("1s", "1m", "3m", "6m", "1a", "ytd", "5a")) +
        "</tr>"
    )


def _cartao_bloco(universo, bloco: dict, janelas: dict, series_info: dict) -> str:
    ativos = [a for a in universo.por_bloco(bloco["id"]) if a.id in janelas]
    if not ativos:
        return ""
    linhas = "".join(_linha_ativo(a, janelas[a.id], series_info.get(a.id) or {}) for a in ativos)
    # como o bloco andou: a mediana resiste ao ativo que disparou sozinho, que e o
    # que se quer saber antes de descer linha a linha
    dias = sorted(j for j in (janelas[a.id].get("dia") for a in ativos
                              if janelas[a.id].get("dia_confirmado", True)) if j is not None)
    if dias:
        meio = len(dias) // 2
        m = dias[meio] if len(dias) % 2 else (dias[meio - 1] + dias[meio]) / 2
        resumo = (f'<span class="conta">{len(ativos)} ativos · mediana do dia '
                  f'<b class="{_sinal(m)}">{_e(fmt.pct(m))}</b> · '
                  f'{sum(1 for d in dias if d > 0)} em alta</span>')
    else:
        resumo = f'<span class="conta">{len(ativos)} ativos</span>'
    return (
        f'<section class="cartao bloco">'
        f'<h2>{_e(bloco["titulo"])}{resumo}</h2>'
        f'<div class="rolagem"><table>'
        '<thead><tr><th scope="col">Ativo</th><th scope="col">últ</th><th scope="col">dia</th>'
        '<th scope="col">1 sem</th><th scope="col">1 mês</th><th scope="col">3 m</th>'
        '<th scope="col">6 m</th><th scope="col">1 ano</th><th scope="col">YTD</th>'
        '<th scope="col">5 anos</th></tr></thead>'
        f"<tbody>{linhas}</tbody></table></div>{_legenda_ucits(ativos)}</section>"
    )


def _legenda_ucits(ativos: list) -> str:
    """Regra do Douglas: UCITS sempre por extenso. Na celula vai o nome curto; o
    nome oficial fica aqui embaixo, em qualquer bloco que tenha um."""
    ucits = [a for a in ativos if "UCITS" in (a.nome or "")]
    if not ucits:
        return ""
    return ('<p class="nota legenda">Nomes completos: '
            + " · ".join(f"<b>{_e(a.id)}</b> {_e(a.nome)}" for a in ucits) + ".</p>")


def _chip_taxa(rotulo: str, taxa, delta, sufixo: str = "") -> str:
    # delta de taxa nao ganha verde/vermelho (em juro, subir nao e 'bom'); o que
    # o olho precisa achar e o vertice que andou, entao o destaque e por tamanho
    forte = " forte" if delta is not None and abs(delta) >= 10 else ""
    return (
        f'<div class="chip"><span class="cr">{_e(rotulo)}</span>'
        f'<span class="ct">{_e(fmt.taxa(taxa))}{_e(sufixo)}</span>'
        f'<span class="cd{forte}">{_e(fmt.bps(delta))} bps</span></div>'
    )


def _cartao_commodities(em_dolar: dict | None) -> str:
    if not em_dolar:
        return ""
    ordem = ("CELULOSE_CURTA", "CELULOSE_LONGA", "MINERIO_DALIAN")
    itens = [(k, em_dolar[k]) for k in ordem if k in em_dolar]
    if not itens:
        return ""
    linhas = []
    for _, v in itens:
        j = v.get("janelas") or {}
        var = v.get("variacao") if v.get("semanal") else j.get("dia")
        linhas.append(
            f'<tr><th scope="row"><span class="tk">{_e(v.get("nome"))}</span>'
            f'<span class="nm">{_e(v.get("rotulo"))}</span></th>'
            f'<td class="n ult">{_e(fmt.num(v.get("usd"), 0))}</td>'
            f'<td class="n {_sinal(var)}">{_e(fmt.pct(var))}</td>'
            f'<td class="n">{_e(fmt.data_br(v.get("data")) if v.get("data") else "-")}</td></tr>')
    return (f'<section class="cartao largo"><h2>Commodities em dólar<span class="conta">US$/t</span></h2>'
            f'<div class="rolagem"><table><thead><tr><th scope="col">Referência</th>'
            f'<th scope="col">US$/t</th><th scope="col">variação</th><th scope="col">data</th>'
            f'</tr></thead><tbody>{"".join(linhas)}</tbody></table></div></section>')


def _cartao_curvas(ins: dict) -> str:
    if not ins:
        return ""
    partes = []
    di = ins.get("di") or {}
    if di.get("taxas"):
        chips = "".join(_chip_taxa(c[3:], t, (di.get("deltas") or {}).get(c))
                        for c, t in di["taxas"].items())
        incl = di.get("inclinacao")
        d_incl = di.get("inclinacao_delta")
        nota = (f'<p class="nota"><strong class="verbo">{_e(di.get("verbo", ""))}</strong> · '
                f'inclinação F35-F28 {_e(fmt.bps(incl))} bps'
                + (f' ({_e(fmt.bps(d_incl))} no dia)' if d_incl is not None else "") + "</p>")
        partes.append(f'<div class="curva"><h3>DI futuro (B3) <span class="quando">'
                      f'{_e(di.get("rotulo", ""))}</span></h3><div class="chips">{chips}</div>{nota}</div>')
    tes = ins.get("tesouro") or {}
    if tes:
        pre = [(v.get("apelido", k), v) for k, v in tes.items() if "prefixado" in (v.get("tipo") or "").lower()]
        ipca = [(v.get("apelido", k), v) for k, v in tes.items() if (k, v) and "prefixado" not in (v.get("tipo") or "").lower()]
        chips = "".join(_chip_taxa(r, v.get("taxa"), v.get("delta"), "%") for r, v in pre + ipca)
        be = ins.get("breakeven") or {}
        foc = ins.get("focus_ipca") or {}
        nota = ""
        if be:
            txt = "Inflação implícita " + " · ".join(f"{r} {fmt.taxa(v)}%" for r, v in be.items())
            if foc.get("mediana"):
                txt += f" · Focus IPCA {foc.get('ano')} {fmt.taxa(foc['mediana'])}%"
            nota = f'<p class="nota">{_e(txt)}</p>'
        base = fmt.data_br(ins.get("tesouro_base")) if ins.get("tesouro_base") else ""
        ant = fmt.data_br(ins.get("tesouro_base_anterior")) if ins.get("tesouro_base_anterior") else ""
        quando = f"base {base}" + (f" · Δ desde {ant}" if ant else "")
        partes.append(f'<div class="curva"><h3>Tesouro Direto <span class="quando">{_e(quando)}</span></h3>'
                      f'<div class="chips">{chips}</div>{nota}</div>')
    ust = ins.get("ust") or {}
    if ust.get("10y") is not None:
        d = ust.get("deltas") or {}
        chips = "".join(_chip_taxa(p, ust.get(p), d.get(p)) for p in ("2y", "10y", "30y"))
        nota = ""
        if ust.get("2s10s") is not None:
            nota = (f'<p class="nota">2s10s {_e(fmt.bps(ust["2s10s"]))} bps'
                    + (f' ({_e(fmt.bps(ust.get("d2s10s")))} no dia)' if ust.get("d2s10s") is not None else "") + "</p>")
        partes.append(f'<div class="curva"><h3>Treasury (EUA) <span class="quando">{_e(ust.get("rotulo", ""))}'
                      f'</span></h3><div class="chips">{chips}</div>{nota}</div>')
    reg = ins.get("regime") or {}
    if reg:
        vix = reg.get("vix")
        itens = []
        if vix is not None:
            itens.append(f'VIX {fmt.num(vix, 1)} ({fmt.pct(reg.get("vix_var"))})')
        itens.append(f'score de risco {reg.get("score", 0)} de {reg.get("avaliados", 6)}')
        if reg.get("regime_vol"):
            itens.append("regime de vol LIGADO")
        partes.append(f'<div class="curva regime"><h3>Regime</h3><p class="nota">{_e(" · ".join(itens))}</p></div>')
    if not partes:
        return ""
    return f'<section class="cartao largo curvas"><h2>Curvas de juro</h2>{"".join(partes)}</section>'


def _corpo_alerta(a: dict) -> str:
    linhas = [l for l in (a.get("corpo") or []) if l and not l.startswith("Link:")]
    if not linhas:
        return ""
    return '<ul class="corpo">' + "".join(f"<li>{_e(l.lstrip(' –'))}</li>" for l in linhas[:5]) + "</ul>"


def _link_de(a: dict) -> str:
    d = a.get("dados") or {}
    url = d.get("link") or d.get("url") or ""
    if not url:
        for l in (a.get("corpo") or []):
            if l.startswith("Link: "):
                url = l[6:].strip()
    if not url.startswith("http"):
        return ""
    return f'<a class="link" href="{_e(url)}" target="_blank" rel="noopener">abrir a fonte</a>'


def _cartao_alertas(do_dia: list[dict]) -> str:
    msg = [a for a in do_dia if a.get("canal") == "mensagem" and a.get("familia") not in ("noticia", "evento")]
    crit = [a for a in msg if a.get("severidade") == "critico"]
    aten = [a for a in msg if a.get("severidade") == "atencao"]
    info = [a for a in do_dia if a.get("canal") != "mensagem" and a.get("familia") not in ("noticia", "evento")]
    if not msg and not info:
        return ('<section class="cartao largo alertas"><h2>Alertas do dia</h2>'
                '<p class="vazio">Nenhuma regra disparou hoje.</p></section>')
    out = [f'<section class="cartao largo alertas"><h2>Alertas do dia'
           f'<span class="conta">{len(msg)} para ler · {len(crit)} crítico{"s" if len(crit) != 1 else ""}</span></h2>']
    for a in crit:
        out.append(
            f'<article class="alerta critico"><p class="cab"><span class="sev">crítico</span>'
            f'<span class="regra">{_e(a.get("regra"))}</span><span class="ativo">{_e(a.get("ativo"))}</span></p>'
            f'<p class="tit">{_e(a.get("titulo"))}</p>{_corpo_alerta(a)}'
            + (f'<p class="revisto">Número revisto depois do disparo; o alerta saiu como: '
               f'{_e(a["titulo_inicial"])}</p>' if a.get("titulo_inicial") else "")
            + (f'<p class="porque">{_e(a.get("por_que"))}</p>' if a.get("por_que") else "")
            + (f'<p class="fonte">{_e(a.get("fonte"))}</p>' if a.get("fonte") else "")
            + "</article>")
    if aten:
        itens = "".join(
            f'<li><span class="sev at">atenção</span><span class="regra">{_e(a.get("regra"))}</span>'
            f'<span class="txt">{_e(a.get("titulo"))}</span></li>' for a in aten)
        out.append(f'<ul class="lista-alertas">{itens}</ul>')
    if info:
        out.append(f'<p class="nota">Mais {len(info)} sinais de baixa prioridade ficaram em alertas.md.</p>')
    out.append("</section>")
    return "".join(out)


def _cartao_noticias(do_dia: list[dict]) -> str:
    itens = [a for a in do_dia if a.get("familia") in ("noticia", "evento") and a.get("canal") == "mensagem"]
    se_manchete = [a for a in do_dia if a.get("familia") in ("noticia", "evento") and a.get("canal") != "mensagem"]
    if not itens:
        return ""
    out = [f'<section class="cartao largo noticias"><h2>Notícias e fatos'
           f'<span class="conta">{len(itens)} com materialidade</span></h2>']
    for a in itens:
        d = a.get("dados") or {}
        marca = d.get("veiculo") or ("SEC" if a.get("regra") == "E04" else "CVM" if a.get("regra") == "E03" else "")
        quando = d.get("hora") or fmt.data_br(a.get("data"))
        lic = d.get("licenca")
        out.append(
            f'<article class="noticia"><p class="cab"><span class="ativo">{_e(a.get("ativo"))}</span>'
            + (f'<span class="veiculo">{_e(marca)}</span>' if marca else "")
            + (f'<span class="quando">{_e(quando)}</span>' if quando else "")
            + (f'<span class="lic">licença: {_e(lic)}</span>' if lic and lic != "integral" else "")
            + f'</p><p class="tit">{_e(d.get("manchete") or a.get("titulo"))}</p>{_corpo_alerta(a)}'
            + (f'<p class="porque">{_e(a.get("por_que"))}</p>' if a.get("por_que") else "")
            + _link_de(a) + "</article>")
    if se_manchete:
        out.append(f'<p class="nota">Outras {len(se_manchete)} manchetes citaram o livro sem número '
                   f'ou decisão nova; a lista completa está em noticias.md.</p>')
    out.append("</section>")
    return "".join(out)


def _cartao_agenda(agenda_l: list[str]) -> str:
    if not agenda_l:
        return ""
    linhas: list[str] = []
    for l in agenda_l:
        if l.startswith("    ") and linhas:
            linhas[-1] = linhas[-1] + " " + l.strip()
        else:
            linhas.append(l.strip())
    itens = []
    for l in linhas:
        m = re.match(r"^(\w{3} \d{2}/\d{2})(?: (\d{2}:\d{2}))? (.*)$", l)
        if m:
            hora = f'<span class="hora">{_e(m.group(2))}</span>' if m.group(2) else ""
            itens.append(f'<li><span class="quando">{_e(m.group(1))}</span>{hora}'
                         f'<span class="txt">{_e(m.group(3))}</span></li>')
        else:
            itens.append(f'<li><span class="txt">{_e(l)}</span></li>')
    return (f'<section class="cartao agenda"><h2>Agenda</h2>'
            f'<ul class="lista-agenda">{"".join(itens)}</ul></section>')


def _cartao_movers(movers: dict, janelas: dict | None = None) -> str:
    janelas = janelas or {}

    def lado(chave: str, titulo: str) -> str:
        itens = movers.get(chave) or []
        if not itens:
            return ""
        def chip(i, v):
            ctx = atribuicao.contexto_curto(janelas.get(i) or {})
            return (f'<span class="mv {_sinal(v)}"><b>{_e(i)}</b>{_e(fmt.pct(v))}'
                    + (f'<small class="ctx">{_e(ctx)}</small>' if ctx else "") + "</span>")
        chips = "".join(chip(i, v) for i, v in itens)
        return f'<div class="lado"><h3>{_e(titulo)}</h3><div class="mvs">{chips}</div></div>'
    corpo = lado("altas", "Maiores altas") + lado("baixas", "Maiores baixas")
    return f'<section class="cartao largo movers">{corpo}</section>' if corpo else ""


def _cartao_por_que(ins: dict) -> str:
    itens = ins.get("por_que_mexeu") or []
    if not itens:
        return ""
    linhas = "".join(
        f'<tr><th scope="row"><span class="tk">{_e(x["id"])}</span></th>'
        f'<td class="n dia {_sinal(x["dia"])}"><span class="v">{_e(fmt.pct(x["dia"]))}</span></td>'
        f'<td class="txt">{_e(x["explicacao"])}</td><td class="txt grau">{_e(x["grau"])}</td></tr>' for x in itens)
    return ('<section class="cartao largo porque-mexeu"><h2>Por que mexeu<span class="conta">camadas que o dado sustenta, '
            'sem somar efeitos</span></h2><div class="rolagem"><table><thead><tr><th scope="col">Ativo</th>'
            '<th scope="col">dia</th><th scope="col">explicação</th><th scope="col">grau</th></tr></thead>'
            f'<tbody>{linhas}</tbody></table></div></section>')


def _cartao_setores(ins: dict) -> str:
    setores = ins.get("setores") or []
    if not setores:
        return ""
    def destoou(c):
        d = c["destoou"]
        return f"destoou: {d['id']} {fmt.pct(d['dia'])}" if d else "ninguém destoou"
    # 3 colunas: quem destoou vai dentro da celula do setor (no celular nao rola de lado)
    linhas = "".join(
        f'<tr><th scope="row">{_e(c["titulo"])}<span class="nm">{_e(" · ".join(x for x in (c.get("fator"), destoou(c)) if x))}</span></th>'
        f'<td class="n dia {_sinal(c["mediana"])}"><span class="v">{_e(fmt.pct(c["mediana"]))}</span></td>'
        f'<td class="n">{c["subiram"]}/{c["cairam"]}</td></tr>'
        for c in setores)
    return ('<section class="cartao largo setores"><h2>Setores do dia<span class="conta">o setor todo andou ou só o papel?</span></h2>'
            '<div class="rolagem"><table><thead><tr><th scope="col">Setor</th><th scope="col">mediana</th>'
            '<th scope="col">subiram/caíram</th></tr></thead>'
            f'<tbody>{linhas}</tbody></table></div></section>')


def _faixa_correcoes(ins: dict) -> str:
    itens = ins.get("correcoes") or []
    if not itens:
        return ""
    linhas = "".join(f"<span>{_e(c['texto'])}</span>" for c in itens)
    return f'<div class="correcao">Correção de alertas já enviados{linhas}</div>'


def _nota_brent_reais(ins: dict) -> str:
    b = ins.get("brent_reais") or {}
    if not b:
        return ""
    if b.get("a_confirmar"):
        return f'<p class="nota"><b>Brent em reais:</b> a confirmar ({_e(b["a_confirmar"])} sem fechamento confirmado).</p>'
    partes = [f"R$ {fmt.num(b['valor'], 2)} por barril"]
    for k, rot in (("dia", "dia"), ("1m", "1 mês"), ("ytd", "no ano")):
        if b.get(k) is not None:
            partes.append(f"{rot} {fmt.pct(b[k])}")
    return f'<p class="nota"><b>Brent em reais:</b> {_e(" · ".join(partes))} (1º vencimento × dólar).</p>'


def _rodape(universo, relogios_txt: str, lacunas: list[str], notas: list[str], fontes: list[str]) -> str:
    ucits = " · ".join(f"<b>{_e(a.id)}</b> {_e(a.nome)}" for a in universo.ucits())
    hip = universo.por_bloco("hipotese")
    nota_iuaa = next((a.nota for a in universo.ucits() if a.nota and "NAO" in (a.nota or "").upper()), "")
    partes = [f'<section class="cartao largo rodape"><h2>Como ler esta página</h2>']
    partes.append(f'<p class="nota"><b>Relógios:</b> {_e(relogios_txt)}</p>')
    if lacunas:
        partes.append('<p class="nota lacuna"><b>Lacunas:</b> ' + _e("; ".join(lacunas)) + ".</p>")
    else:
        partes.append('<p class="nota"><b>Lacunas:</b> nenhuma perna falhou.</p>')
    partes.append(f'<p class="nota"><b>UCITS por extenso:</b> {ucits}.</p>')
    if nota_iuaa:
        partes.append(f'<p class="nota alerta-nota">{_e(nota_iuaa)}</p>')
    if hip:
        partes.append('<p class="nota"><b>Hipótese:</b> ' + " · ".join(f"<b>{_e(a.id)}</b> {_e(a.nome)}" for a in hip)
                      + " — ETFs dos EUA, a confirmar.</p>")
    for n in notas:
        partes.append(f'<p class="nota">{_e(n)}</p>')
    partes.append(f'<p class="nota fontes"><b>Fontes:</b> {_e(" · ".join(fontes))}.</p>')
    partes.append('<p class="nota aviso">Uso interno da mesa. Organização e comparação de dados públicos, '
                  'não é recomendação de investimento (Resolução CVM 178).</p>')
    partes.append("</section>")
    return "".join(partes)


def pagina(universo, hoje: date, slot: str, hora_txt: str, relogios_txt: str, janelas: dict,
           series_info: dict, do_dia: list[dict], ins: dict, movers: dict, agenda_l: list[str],
           lacunas: list[str], notas: list[str], fontes: list[str], parcial: bool = False,
           em_dolar: dict | None = None) -> str:
    """HTML completo do painel. O marcador da Leitura da Mesa fica para a sessao."""
    rotulo = {"manha": "Manhã do livro", "intradia": "O livro agora"}.get(slot, "Fechamento do livro")
    cartoes = ""
    for b in universo.blocos:
        c = _cartao_bloco(universo, b, janelas, series_info)
        if c and b["id"] == "macro" and _nota_brent_reais(ins):
            c = c.replace("</section>", _nota_brent_reais(ins) + "</section>", 1) if c.endswith("</section>") else c + _nota_brent_reais(ins)
        cartoes += c
    corpo = (
        _faixa_correcoes(ins) +
        f'<header class="topo"><div class="faixa">'
        f'<span class="marca">Livro monitorado</span>'
        f'<span class="quando">{_e(fmt.dia_semana(hoje))} {_e(fmt.data_br(hoje.isoformat(), True))}</span>'
        + ('<span class="parcial">parcial</span>' if parcial else "")
        + f'<span class="hora">{_e(hora_txt)} BRT</span></div>'
        f'<h1>{_e(rotulo)}</h1></header>'
        f'<section class="cartao largo leitura"><h2>Leitura da mesa</h2>'
        f'<div class="texto-leitura">{MARCADOR_LEITURA}</div></section>'
        + _cartao_movers(movers, janelas)
        + _cartao_por_que(ins)
        + _cartao_alertas(do_dia)
        + _cartao_setores(ins)
        + f'<div class="grade">{cartoes}</div>'
        + _cartao_commodities(em_dolar)
        + _cartao_curvas(ins)
        + _cartao_noticias(do_dia)
        + _cartao_agenda(agenda_l)
        + _rodape(universo, relogios_txt, lacunas, notas, fontes)
    )
    # Titulo da aba estavel: o painel e um Artifact fixado; o nome do slot fica no <h1>.
    return ('<title>Livro monitorado</title>\n'
            f'<link rel="stylesheet" href="{FONTES_GOOGLE}">\n'
            f"<style>{CSS}</style>\n<main>{corpo}</main>\n")
