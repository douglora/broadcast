#!/usr/bin/env python3
"""
Leitura padronizada da mesa de analise: um comando, uma ficha.

Le o branch `dados` pelo raw.githubusercontent.com (com cache-busting, porque o
CDN guarda 5 minutos) e imprime o que a skill analise-ativo precisa, sempre no
mesmo formato. Substitui os scripts avulsos escritos a cada analise.

    python3 mesa.py ficha INBR32                 # cabecalho, valuation, series oficiais, releases, pares, lacunas
    python3 mesa.py serie INBR32                 # series oficiais completas, uma linha por trimestre
    python3 mesa.py releases INBR32              # os 8 releases guardados
    python3 mesa.py release INBR32 2T25          # texto integral de um release
    python3 mesa.py release INBR32 2T25 --grep "guidance|ROE|meta"   # so as frases que casam
    python3 mesa.py linha INBR32 "ROE|meta|guidance"  # a mesma busca nos 8 releases, em ordem: o que a gestao disse trimestre a trimestre
    python3 mesa.py decompor INBR32              # cada linha da DRE como % da receita, trimestre a trimestre, e quem explica a variacao
    python3 mesa.py pares INBR32                 # comparativo do grupo com medianas
    python3 mesa.py balanco DIRR3                # alavancagem e caixa do grupo, pelo balanco oficial da CVM
    python3 mesa.py frescor DIRR3                # idade da coleta e defasagem ITR x release; VEREDITO ATUAL (saida 0) ou velho (saida 1): a trava das skills
    python3 mesa.py termos ROE NIM P/VP          # glossario em portugues claro
    python3 mesa.py skills                       # confere se as skills da mesa estao instaladas e validas

Nada aqui e opiniao: e leitura do que o coletor gravou. Valores sem fonte no
JSON aparecem como "-", nunca preenchidos.
"""

import datetime
import json
import os
import re
import sys
import time
import urllib.request

BASE = "https://raw.githubusercontent.com/douglora/broadcast/dados/"
CACHE = os.path.join(os.environ.get("TMPDIR", "/tmp"), "mesa_cache")
AQUI = os.path.dirname(os.path.abspath(__file__))


def baixar(caminho, texto=False, ttl=120):
    """Baixa um arquivo do branch dados, com cache curto em disco e cache-busting no CDN."""
    os.makedirs(CACHE, exist_ok=True)
    local = os.path.join(CACHE, caminho.replace("/", "__"))
    if os.path.exists(local) and time.time() - os.path.getmtime(local) < ttl:
        with open(local, "rb") as f:
            dados = f.read()
    else:
        url = f"{BASE}{caminho}?v={int(time.time() * 1000)}"
        req = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "Pragma": "no-cache"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                dados = r.read()
        except Exception as e:
            print(f"!! {caminho}: {type(e).__name__}: {e}")
            return None
        with open(local, "wb") as f:
            f.write(dados)
    if texto:
        return dados.decode("utf-8", "replace")
    try:
        return json.loads(dados.decode("utf-8"))
    except Exception:
        print(f"!! {caminho}: JSON ilegivel")
        return None


def fmt(v, casas=1, pct=False, mil=False):
    if v is None:
        return "-"
    if isinstance(v, str):
        return v
    if pct:
        return f"{100 * v:.{casas}f}%".replace(".", ",")
    if mil:
        return f"{v / 1e6:,.0f} mi".replace(",", ".") if abs(v) >= 1e6 else f"{v:,.0f}".replace(",", ".")
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def ordem_periodo(p):
    """Aceita '2025T4' (series da CVM), '4T25' (releases) e 'CY2025Q4' (SEC) -> (ano, trimestre)."""
    p = p or ""
    m = re.fullmatch(r"(\d{4})T([1-4])", p)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    m = re.fullmatch(r"([1-4])T(\d{2})", p)
    if m:
        return (2000 + int(m.group(2)), int(m.group(1)))
    m = re.fullmatch(r"CY(\d{4})Q([1-4])", p)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def serie_oficial(d):
    """(fonte, unidade, series trimestrais, ltm, derivados, plano) do bloco oficial que existir."""
    cvm = d.get("cvm_demonstracoes") or {}
    sub = d.get("subjacente_us") or {}
    sec = sub.get("sec_xbrl") or d.get("sec_xbrl") or d.get("sec_xbrl_adr") or {}
    if cvm.get("serie_trimestral"):
        return ("CVM ITR/DFP", cvm.get("unidade", "R$ milhoes"), cvm["serie_trimestral"], cvm.get("ltm") or {},
                cvm.get("derivados") or {}, cvm.get("plano_de_contas", "geral"), cvm.get("descricao_contas") or {})
    if sec.get("trimestral"):
        tri = {k: {q: (v / 1e6 if isinstance(v, (int, float)) else v) for q, v in s.items()} for k, s in sec["trimestral"].items()}
        ltm = {k: {**v, "valor": v["valor"] / 1e6} for k, v in (sec.get("ltm") or {}).items()}
        return ("SEC XBRL", "US$ milhoes", tri, ltm, sec.get("derivados") or {}, "geral", sec.get("tags_usadas") or {})
    return (None, None, {}, {}, {}, None, {})


LINHAS_GERAL = [("receita_liquida", "receita"), ("ebit", "EBIT"), ("resultado_financeiro", "res. financeiro"),
                ("lucro_liquido_consolidado", "lucro"), ("patrimonio_liquido_consolidado", "patrimonio"),
                ("caixa_operacional", "caixa operacional")]
LINHAS_SEC = [("receita", "receita"), ("lucro_bruto", "lucro bruto"), ("ebit", "EBIT"), ("lucro_liquido", "lucro"),
              ("patrimonio_liquido", "patrimonio"), ("divida_total", "divida total"), ("caixa", "caixa")]
LINHAS_BANCO = [("receita_liquida", "rec. intermediacao"), ("resultado_bruto", "res. bruto interm."),
                ("resultado_antes_ir", "antes dos tributos"), ("lucro_liquido_consolidado", "lucro"),
                ("lucro_atribuido_controladores", "lucro controladores"), ("patrimonio_liquido_consolidado", "patrimonio"),
                ("carteira_credito", "carteira de credito"), ("depositos", "depositos"), ("ativo_total", "ativo total")]


def imprimir_serie(d, n=8):
    fonte, unidade, tri, ltm, der, plano, descr = serie_oficial(d)
    if not fonte:
        print("  demonstracao oficial: AUSENTE")
        return
    linhas = LINHAS_BANCO if plano == "instituicao_financeira" else (LINHAS_SEC if fonte == "SEC XBRL" else LINHAS_GERAL)
    linhas = [(k, r) for k, r in linhas if k in tri]
    periodos = sorted({q for k, _ in linhas for q in tri[k]}, key=ordem_periodo)[-n:]
    print(f"  fonte {fonte} | {unidade} | plano {plano} | D = trimestre derivado do anual")
    print("  " + f"{'trimestre':11}" + "".join(f"{r[:15]:>17}" for _, r in linhas))
    for q in periodos:
        marca = "D" if any(q in der.get(k, []) for k, _ in linhas) else " "
        print("  " + f"{q:10}{marca}" + "".join(f"{fmt(tri[k].get(q), 0):>17}" for k, _ in linhas))
    if ltm:
        print("  12 meses ate " + next(iter(ltm.values())).get("ate", "?") + ": " +
              " | ".join(f"{r} {fmt(ltm[k]['valor'], 0)}" for k, r in linhas if k in ltm))
    # margens e ROE quando fazem sentido
    rec_k = "receita_liquida" if "receita_liquida" in tri else "receita"
    luc_k = "lucro_liquido_consolidado" if "lucro_liquido_consolidado" in tri else "lucro_liquido"
    pl_k = "patrimonio_liquido_consolidado" if "patrimonio_liquido_consolidado" in tri else "patrimonio_liquido"
    ult = periodos[-1] if periodos else None
    if ult and tri.get(luc_k, {}).get(ult) and tri.get(pl_k, {}).get(ult):
        print(f"  ROE anualizado do ultimo trimestre: {fmt(4 * tri[luc_k][ult] / tri[pl_k][ult], 1, pct=True)}"
              f"  (lucro x4 / patrimonio de {ult})")
    if plano == "instituicao_financeira":
        print("  banco: nao existe EBIT nem margem operacional aqui; use lucro, ROE, carteira, depositos e o release")
    elif ult and tri.get(rec_k, {}).get(ult) and tri.get("ebit", {}).get(ult) is not None:
        serie = [(q, tri["ebit"][q] / tri[rec_k][q]) for q in periodos if tri[rec_k].get(q) and tri.get("ebit", {}).get(q) is not None]
        print("  margem EBIT por trimestre: " + "  ".join(f"{q} {fmt(m, 1, pct=True)}" for q, m in serie))
    if descr and plano == "instituicao_financeira":
        print("  contas usadas: " + "; ".join(f"{k}={v}" for k, v in descr.items() if k in dict(linhas))[:400])


def data_release(r):
    """Data do release como o coletor gravou; sufixo ' (estimada)' quando ele so inferiu
    (fim do trimestre + 40 dias, campo data_estimada). Data estimada nunca entra na nota como data de divulgacao."""
    r = r or {}
    d = r.get("data")
    return f"{d} (estimada)" if d and r.get("data_estimada") else d


def ficha(tk):
    d = baixar(f"ativos/{tk}.json")
    if not d:
        print(f"{tk}: nao esta no branch dados. Dispare a coleta (pares: auto)."); return
    print(veredito_frescor(tk, d))
    ident = d.get("identificacao") or {}
    sub = d.get("subjacente_us") or {}
    y = (sub.get("yahoo") if sub else d.get("yahoo")) or {}
    info, calc = y.get("info") or {}, y.get("multiplos_calculados") or {}
    ret = (d.get("yahoo") or {}).get("retornos") or {}
    fn = {re.sub(r"[^A-Z0-9 ]+", " ", k.upper()).strip(): v for k, v in (d.get("fundamentus") or {}).items() if isinstance(v, (int, float))}
    print(f"=== {tk} | {ident.get('nome')} | {ident.get('setor_yahoo')} / {ident.get('industria_yahoo')}")
    print(f"  coletado em {d.get('gerado_em')} | grupo {(d.get('pares') or {}).get('grupo')} ({(d.get('pares') or {}).get('tipo')})"
          f" | pares {', '.join((d.get('pares') or {}).get('tickers') or [])}")
    if sub:
        par = sub.get("paridade_implicita") or {}
        print(f"  BDR de {sub.get('simbolo')}: preco BDR R$ {fmt((d.get('yahoo') or {}).get('info', {}).get('currentPrice'), 2)}"
              f" | acao-mae {info.get('currency')} {fmt(info.get('currentPrice'), 2)} | paridade implicita {fmt(par.get('bdrs_por_acao'), 3)} BDR por acao")
    print("\n-- preco e multiplos (Yahoo, na data da coleta; Fundamentus quando houver)")
    print(f"  preco {info.get('currency')} {fmt(info.get('currentPrice'), 2)} | valor de mercado {fmt(info.get('marketCap'), mil=True)}"
          f" | EV {fmt(info.get('enterpriseValue'), mil=True)}")
    print(f"  P/L 12m {fmt(fn.get('P L') or info.get('trailingPE'), 1)}x | P/L projetado {fmt(info.get('forwardPE'), 1)}x"
          f" | P/VP {fmt(fn.get('P VP') or info.get('priceToBook'), 2)}x | EV/EBITDA {fmt(fn.get('EV EBITDA') or info.get('enterpriseToEbitda'), 1)}x")
    dy = calc.get("dy_12m") if calc.get("dy_12m") is not None else fn.get("DIV YIELD")
    print(f"  DY 12m {fmt(dy, 1, pct=True)} | ROE (agregador) {fmt(fn.get('ROE') or info.get('returnOnEquity'), 1, pct=True)}"
          f" | beta {fmt(info.get('beta'), 2)} | div. liquida/EBITDA {fmt(calc.get('divida_liquida_ebitda'), 2)}x")
    print(f"  retorno: 1m {fmt(ret.get('1m'), 1, pct=True)} | 3m {fmt(ret.get('3m'), 1, pct=True)} | 12m {fmt(ret.get('12m'), 1, pct=True)}"
          f" | no ano {fmt(ret.get('ytd'), 1, pct=True)} | max 52s {fmt(ret.get('max_52s'), 2)} | min 52s {fmt(ret.get('min_52s'), 2)}")
    alvo, preco = info.get("targetMeanPrice"), info.get("currentPrice")
    print(f"  consenso: {info.get('recommendationKey')} | {info.get('numberOfAnalystOpinions')} analistas | alvo medio {fmt(alvo, 2)}"
          f" ({fmt(alvo / preco - 1, 1, pct=True) if alvo and preco else '-'}) | min {fmt(info.get('targetLowPrice'), 2)} | max {fmt(info.get('targetHighPrice'), 2)}")
    print("\n-- demonstracoes oficiais (ultimos 8 trimestres)")
    imprimir_serie(d, 8)
    print("\n-- releases guardados (releases/%s/)" % tk)
    for r in d.get("releases_historico") or []:
        print(f"  {r.get('periodo') or '?':5} {data_release(r)}  {str(r.get('assunto') or r.get('arquivo_sec') or r.get('formulario'))[:50]:52} {r.get('caracteres_total') or 0:>7} chars")
    rel = d.get("release_ri") or {}
    print(f"  mais novo: {rel.get('periodo')} de {data_release(rel)} | {rel.get('fonte')}")
    mac = d.get("macro") or {}
    print("\n-- macro (BCB): " + " | ".join(f"{k} {v.get('value')}{'' if v.get('unidade','').startswith('R$') else '%'} ({v.get('date')})"
                                          for k, v in mac.items() if isinstance(v, dict)))
    tir = d.get("tir_modelo") or {}
    if tir.get("coberto"):
        print(f"  TIR real da casa: {json.dumps(tir.get('resultado'), ensure_ascii=False)[:200]}")
    else:
        print("  TIR real da casa: nao cobre este ativo")
    print("\n-- fontes com problema:")
    ruins = {k: v for k, v in (d.get("fontes") or {}).items() if not str(v).startswith("ok")}
    for k, v in ruins.items():
        print(f"  {k}: {v}")
    if not ruins:
        print("  nenhuma")
    fatos, vistos = [], set()
    for f in (d.get("cvm") or {}).get("fatos_relevantes") or []:
        chave = (f["data"], f["assunto"][:60])
        if chave not in vistos:
            vistos.add(chave)
            fatos.append(f)
    if fatos:
        print("\n-- fatos relevantes recentes (CVM):")
        for f in fatos[:5]:
            print(f"  {f['data']} {f['assunto'][:90]}")
    ev = (d.get("yahoo") or {}).get("eventos") or {}
    if ev.get("datas_de_resultado"):
        print(f"\n-- proximo resultado (Yahoo): {ev['datas_de_resultado'][0]}")


def serie(tk):
    d = baixar(f"ativos/{tk}.json")
    if d:
        print(veredito_frescor(tk, d))
        imprimir_serie(d, 12)


def releases(tk):
    idx = baixar(f"releases/{tk}/index.json")
    if not idx:
        return
    d = baixar(f"ativos/{tk}.json")
    if d:
        print(veredito_frescor(tk, d))
    print(f"{tk}: {len(idx.get('releases', []))} releases, atualizado em {idx.get('atualizado_em')}")
    for r in idx.get("releases", []):
        print(f"  {r.get('periodo') or '?':5} {data_release(r)}  {str(r.get('assunto') or r.get('arquivo_sec') or r.get('formulario'))[:60]:62} {r.get('caracteres_total') or 0:>7} chars  {r.get('arquivo')}")


def release(tk, periodo, grep=None, contexto=260):
    idx = baixar(f"releases/{tk}/index.json")
    if not idx:
        return
    d = baixar(f"ativos/{tk}.json")
    if d:
        print(veredito_frescor(tk, d))
    alvo = next((r for r in idx.get("releases", []) if (r.get("periodo") or "").upper() == periodo.upper()), None)
    if not alvo:
        print(f"{tk}: nao ha release {periodo}. Existem: {[r.get('periodo') for r in idx.get('releases', [])]}")
        return
    texto = baixar(alvo["arquivo"], texto=True)
    if texto is None:
        return
    print(f"== {tk} {alvo.get('periodo')} | {data_release(alvo)} | {alvo.get('assunto') or alvo.get('arquivo_sec')} | {alvo.get('link')}")
    if not grep:
        print(texto)
        return
    plano = re.sub(r"\s+", " ", texto)
    rx = re.compile(grep, re.I)
    vistos, n = set(), 0
    for m in rx.finditer(plano):
        ini = max(0, plano.rfind(". ", 0, max(0, m.start() - contexto)) + 2)
        fim = plano.find(". ", m.end() + contexto)
        trecho = plano[ini:(fim + 1 if fim > 0 else m.end() + contexto)].strip()
        chave = trecho[:60]
        if chave in vistos:
            continue
        vistos.add(chave)
        n += 1
        print(f"\n[{n}] ...{trecho[:900]}")
        if n >= 25:
            print("\n(25 trechos; refine o --grep)")
            break
    if not n:
        print("nenhum trecho casou")


def _trechos(texto, rx, contexto=200, max_por_release=4, largura=420):
    """Frases que casam com rx, sem repetir, ja normalizadas em uma linha."""
    plano = re.sub(r"\s+", " ", texto)
    saida, vistos = [], set()
    for m in rx.finditer(plano):
        ini = max(0, plano.rfind(". ", 0, max(0, m.start() - contexto)) + 2)
        fim = plano.find(". ", m.end() + contexto)
        trecho = plano[ini:(fim + 1 if fim > 0 else m.end() + contexto)].strip()
        chave = re.sub(r"[^a-z0-9]+", "", trecho.lower())[:70]
        if chave in vistos:
            continue
        vistos.add(chave)
        saida.append(trecho[:largura])
        if len(saida) >= max_por_release:
            break
    return saida


def linha(tk, padrao, max_por_release=4):
    """A mesma busca nos 8 releases, do mais antigo ao mais novo: discurso contra entrega em um comando."""
    idx = baixar(f"releases/{tk}/index.json")
    if not idx:
        print(f"{tk}: nenhum release guardado. Dispare a coleta.")
        return
    d = baixar(f"ativos/{tk}.json")
    if d:
        print(veredito_frescor(tk, d))
    rels = sorted(idx.get("releases", []), key=lambda r: ordem_periodo(r.get("periodo")))
    rx = re.compile(padrao, re.I)
    print(f"== {tk}: \"{padrao}\" em {len(rels)} releases, do mais antigo ao mais novo")
    achou_algum = False
    for r in rels:
        texto = baixar(r["arquivo"], texto=True)
        cab = f"\n-- {r.get('periodo') or '?'} ({data_release(r)}) {str(r.get('assunto') or r.get('arquivo_sec') or '')[:58]}"
        if texto is None:
            print(cab + "\n   (texto indisponivel)")
            continue
        achados = _trechos(texto, rx, max_por_release=max_por_release)
        print(cab)
        if not achados:
            print("   (nao fala nisso)")
            continue
        achou_algum = True
        for t in achados:
            print(f"   . {t}")
    if not achou_algum:
        print("\nnenhum release fala nisso. Ou o termo esta errado, ou a gestao nunca tocou no assunto: "
              "as duas leituras valem, diga qual e.")
    print(f"\n(ate {max_por_release} trechos por release; `mesa.py release {tk} <periodo>` traz o texto inteiro)")


ORDEM_DRE = ["receita_liquida", "receita", "custo", "custo_produtos_vendidos", "lucro_bruto", "resultado_bruto",
             "despesas_operacionais", "despesas_vendas", "despesas_administrativas", "despesas_gerais_administrativas",
             "despesa_pdd", "provisao_credito", "pesquisa_desenvolvimento", "ebit", "resultado_financeiro",
             "receita_financeira", "despesa_financeira", "receita_juros", "resultado_financeiro_outros",
             "resultado_antes_ir", "imposto_renda", "lucro_liquido_consolidado", "lucro_liquido",
             "lucro_atribuido_controladores"]
NAO_E_DRE = {"patrimonio_liquido", "patrimonio_liquido_consolidado", "ativo_total", "passivo_total", "caixa",
             "caixa_equivalentes", "aplicacoes_financeiras", "ativo_circulante", "ativo_nao_circulante",
             "passivo_circulante", "passivo_nao_circulante", "caixa_operacional", "caixa_investimento",
             "caixa_financiamento", "capex", "estoques", "contas_a_receber", "divida_total",
             "divida_curto_prazo", "divida_longo_prazo", "emprestimos_curto_prazo", "emprestimos_longo_prazo",
             "carteira_credito", "depositos", "dividendos_pagos", "recompra_acoes", "lpa_basico_on",
             "lpa_diluido_on", "lpa_basico", "lpa_diluido", "acoes_em_circulacao"}


def _e_conta_de_resultado(chave, descr):
    """Na CVM o codigo decide: grupo 3 e a DRE, 3.99 e lucro por acao, 1 e 2 sao balanco."""
    codigo = str((descr or {}).get(chave) or "").strip()
    if codigo[:1].isdigit():
        return codigo.startswith("3.") and not codigo.startswith("3.99")
    return chave not in NAO_E_DRE


def decompor(tk, n=8):
    """Cada linha da DRE como % da receita, trimestre a trimestre, e quem explica a variacao da margem."""
    d = baixar(f"ativos/{tk}.json")
    if not d:
        print(f"{tk}: nao esta no branch dados.")
        return
    print(veredito_frescor(tk, d))
    fonte, unidade, tri, ltm, der, plano, descr = serie_oficial(d)
    if not fonte:
        print("  demonstracao oficial: AUSENTE; sem decomposicao possivel")
        return
    base = "receita_liquida" if "receita_liquida" in tri else ("receita" if "receita" in tri else None)
    if not base:
        print("  sem linha de receita na serie oficial; use o release")
        return
    elegivel = [k for k in tri if k != base and _e_conta_de_resultado(k, descr)]
    chaves = [k for k in ORDEM_DRE if k in elegivel] + [k for k in sorted(elegivel) if k not in ORDEM_DRE]
    periodos = sorted([q for q in tri[base] if tri[base].get(q)], key=ordem_periodo)[-n:]
    if len(periodos) < 2:
        print("  menos de 2 trimestres com receita; sem decomposicao")
        return
    rotulo = "receitas da intermediacao" if plano == "instituicao_financeira" else "receita"
    print(f"== {tk}: DRE como % da {rotulo} | fonte {fonte} | {unidade} | D = trimestre derivado do anual")
    if plano == "instituicao_financeira":
        print("   (banco: a base e a receita da intermediacao financeira, nao ha margem EBIT)")
    print("   " + f"{'trimestre':11}" + f"{rotulo[:13]:>15}" + "".join(f"{k.replace('_', ' ')[:13]:>15}" for k in chaves))
    pcts = {}
    for q in periodos:
        rec = tri[base][q]
        marca = "D" if any(q in der.get(k, []) for k in [base] + chaves) else " "
        cels = []
        for k in chaves:
            v = tri[k].get(q)
            pct = None if v is None or not rec else v / rec
            pcts.setdefault(k, {})[q] = pct
            cels.append(fmt(pct, 1, pct=True) if pct is not None else "-")
        print("   " + f"{q:10}{marca}" + f"{fmt(rec, 0):>15}" + "".join(f"{c:>15}" for c in cels))
    ini, fim = periodos[0], periodos[-1]
    print(f"\n-- variacao de {ini} para {fim}, em pontos percentuais da {rotulo}")
    deltas = []
    for k in chaves:
        a, b = pcts[k].get(ini), pcts[k].get(fim)
        if a is None or b is None:
            continue
        deltas.append((abs(b - a), b - a, k, a, b))
    if not deltas:
        print("   serie incompleta nas pontas; compare os trimestres que existem na tabela acima")
    for _, delta, k, a, b in sorted(deltas, reverse=True):
        sinal = "+" if delta >= 0 else ""
        print(f"   {k.replace('_', ' ')[:30]:32} {fmt(a, 1, pct=True):>8} -> {fmt(b, 1, pct=True):>8}   {sinal}{fmt(100 * delta, 1)} pp")
    d_rec = tri[base][fim] / tri[base][ini] - 1
    print(f"   {'(a receita variou)':32} {' ':>8}    {' ':>8}   {'+' if d_rec >= 0 else ''}{fmt(100 * d_rec, 1)}% em {len(periodos) - 1} trimestres")
    if descr:
        usadas = {k: v for k, v in descr.items() if k in chaves or k == base}
        if usadas:
            print("\n-- conta oficial por linha: " + "; ".join(f"{k}={v}" for k, v in list(usadas.items())[:14]))
    print("\nLeia assim: a linha com mais pp de variacao e a que explica a margem. Depois pergunte ao release por que,\n"
          f"com `mesa.py linha {tk} \"<termo da linha>\"`.")


def pares(tk):
    d = baixar(f"ativos/{tk}.json")
    if not d:
        return
    arq = (d.get("pares") or {}).get("comparativo")
    if not arq:
        print(f"{tk} nao tem grupo em pares.py")
        return
    c = baixar(arq)
    if not c:
        return
    fin = c.get("tipo") == "financeiro"
    print(f"== {c.get('nome')} ({c.get('tipo')}) | gerado {c.get('gerado_em')}")
    cab = ["ticker", "P/L", "P/L proj", "P/VP", "ROE", "DY", "ret 12m"] + (["lucro ofic", "ROE ofic", "cresc ofic"] if fin
          else ["EV/EBITDA", "mgEBIT ofic", "cresc ofic", "fin/EBIT"])
    print("  " + " ".join(f"{h:>12}" for h in cab))
    for ln in c.get("linhas", []):
        o = ln.get("oficial") or {}
        # CVM ja vem em R$ milhoes; SEC vem em dolares inteiros
        escala = 1e6 if "SEC" in (o.get("fonte") or "") else 1.0
        moeda = {"USD": "US$", "BRL": "R$", "R$ milhoes": "R$"}.get(o.get("unidade") or "", o.get("unidade") or "")
        lucro = f"{fmt((o.get('lucro_ltm') or 0) / escala, 0)} {moeda}mi" if o.get("lucro_ltm") is not None else "-"
        base = [ln["ticker"], fmt(ln.get("pl_12m"), 1), fmt(ln.get("pl_projetado"), 1), fmt(ln.get("pvp"), 2),
                fmt(ln.get("roe"), 1, pct=True), fmt(ln.get("dy_12m"), 1, pct=True), fmt(ln.get("retorno_12m"), 1, pct=True)]
        extra = ([lucro, fmt(o.get("roe_ltm"), 1, pct=True), fmt(o.get("cresc_receita_ltm"), 1, pct=True)] if fin
                 else [fmt(ln.get("ev_ebitda"), 1), fmt(o.get("margem_ebit_ltm"), 1, pct=True), fmt(o.get("cresc_receita_ltm"), 1, pct=True),
                       fmt(o.get("resultado_financeiro_sobre_ebit"), 2)])
        print("  " + " ".join(f"{x:>12}" for x in base + extra) + f"   [{(o.get('fonte') or 'sem oficial')[:34]}; ate {o.get('ltm_ate') or '-'}; dado de {ln.get('gerado_em', '')[:10]}]")
    med = c.get("medianas") or {}
    print("  medianas: " + " | ".join(f"{k} {fmt(v['mediana'], 2) if 'pl' in k or 'pvp' in k or 'ev' in k else fmt(v['mediana'], 1, pct=True)}"
                                     for k, v in med.items() if k in ("pl_12m", "pl_projetado", "pvp", "ev_ebitda", "roe", "dy_12m", "retorno_12m", "oficial.roe_ltm", "oficial.margem_ebit_ltm", "oficial.cresc_receita_ltm")))


def termos(chaves):
    caminho = os.path.join(AQUI, ".claude", "skills", "analise-ativo", "GLOSSARIO.md")
    try:
        linhas = open(caminho, encoding="utf-8").read().split("\n")
    except FileNotFoundError:
        print("glossario nao encontrado:", caminho)
        return
    if not chaves:
        print("\n".join(l for l in linhas if l.startswith("- **")))
        return
    for chave in chaves:
        rx = re.compile(r"\*\*[^*]*\b" + re.escape(chave) + r"\b", re.I)
        achou = [l for l in linhas if l.startswith("- **") and rx.search(l)]
        print("\n".join(achou) if achou else f"- {chave}: nao esta no glossario; explique em uma frase e proponha incluir")


def _linha_balanco(tk):
    """Divida, caixa, patrimonio e geracao de caixa de um ticker, direto da demonstracao oficial."""
    d = baixar(f"ativos/{tk}.json")
    if not d:
        return None
    fonte, unidade, tri, ltm, der, plano, descr = serie_oficial(d)
    if not fonte:
        return {"ticker": tk, "erro": "sem demonstracao oficial"}
    def ult(chave):
        s = tri.get(chave) or {}
        qs = sorted([q for q in s if s[q] is not None], key=ordem_periodo)
        return (s[qs[-1]], qs[-1]) if qs else (None, None)
    def soma_ltm(chave):
        s = tri.get(chave) or {}
        qs = sorted([q for q in s if s[q] is not None], key=ordem_periodo)[-4:]
        return sum(s[q] for q in qs) if len(qs) == 4 else None
    cp, q = ult("emprestimos_curto_prazo" if "emprestimos_curto_prazo" in tri else "divida_curto_prazo")
    lp, _ = ult("emprestimos_longo_prazo" if "emprestimos_longo_prazo" in tri else "divida_longo_prazo")
    cx, _ = ult("caixa_equivalentes" if "caixa_equivalentes" in tri else "caixa")
    ap, _ = ult("aplicacoes_financeiras")
    pl, _ = ult("patrimonio_liquido_consolidado" if "patrimonio_liquido_consolidado" in tri else "patrimonio_liquido")
    est, _ = ult("estoques")
    at, _ = ult("ativo_total")
    bruta = (cp or 0) + (lp or 0) if (cp is not None or lp is not None) else None
    liquida = None if bruta is None else bruta - (cx or 0) - (ap or 0)
    return {"ticker": tk, "periodo": q, "fonte": fonte, "unidade": unidade, "plano": plano, "gerado_em": (d.get("gerado_em") or "")[:10],
            "divida_bruta": bruta, "caixa": (cx or 0) + (ap or 0), "divida_liquida": liquida,
            "patrimonio": pl, "estoques": est, "ativo_total": at,
            "dl_pl": None if not pl or liquida is None else liquida / pl,
            "ebit_ltm": soma_ltm("ebit"), "lucro_ltm": soma_ltm("lucro_liquido_consolidado") or soma_ltm("lucro_liquido"),
            "receita_ltm": soma_ltm("receita_liquida") or soma_ltm("receita"),
            "caixa_op_ltm": soma_ltm("caixa_operacional"),
            "roe": None if not pl else ((soma_ltm("lucro_liquido_consolidado") or soma_ltm("lucro_liquido") or 0) / pl) or None}


def balanco(tk):
    """Alavancagem do grupo inteiro pelo balanco oficial: o que o multiplo do agregador nao mostra."""
    d = baixar(f"ativos/{tk}.json")
    if not d:
        print(f"{tk}: nao esta no branch dados.")
        return
    grupo = (d.get("pares") or {})
    tickers = grupo.get("tickers") or [tk]
    print(f"== {grupo.get('nome') or tk}: alavancagem pelo balanco oficial (nao pelo agregador)")
    print("   Divida liquida = emprestimos de curto + longo prazo, menos caixa e aplicacoes financeiras.")
    print("   " + f"{'ticker':8}{'periodo':9}" + "".join(f"{h:>15}" for h in
          ("div. bruta", "caixa", "div. liquida", "patrimonio", "DL/PL", "EBIT 12m", "caixa op 12m", "ROE 12m")))
    linhas = []
    for t in tickers:
        ln = _linha_balanco(t)
        if not ln:
            print(f"   {t:8} nao esta no branch")
            continue
        if ln.get("erro"):
            print(f"   {t:8} {ln['erro']}")
            continue
        linhas.append(ln)
        if ln.get("plano") == "instituicao_financeira":
            print(f"   {t:8} banco: capta por deposito, nao por emprestimo. Alavancagem aqui e ativo/patrimonio"
                  f" ({fmt((ln['ativo_total'] or 0) / ln['patrimonio'], 1)}x) e capital principal, nao DL/PL.")
            continue
        print("   " + f"{t:8}{(ln['periodo'] or '-'):9}" +
              "".join(f"{v:>15}" for v in (fmt(ln["divida_bruta"], 0), fmt(ln["caixa"], 0), fmt(ln["divida_liquida"], 0),
                                           fmt(ln["patrimonio"], 0), fmt(ln["dl_pl"], 1, pct=True), fmt(ln["ebit_ltm"], 0),
                                           fmt(ln["caixa_op_ltm"], 0), fmt(ln["roe"], 1, pct=True))))
    linhas = [l for l in linhas if l.get("plano") != "instituicao_financeira"]
    if linhas:
        us = sorted({l["unidade"] for l in linhas})
        print(f"   valores em {' e '.join(us)}; DL/PL negativo = caixa liquido (mais caixa que divida)")
        if len(us) > 1:
            print("   ATENCAO: moedas diferentes na tabela; so DL/PL e ROE se comparam direto")
        dls = sorted([l for l in linhas if l["dl_pl"] is not None], key=lambda l: l["dl_pl"])
        if dls:
            print(f"   menos alavancada: {dls[0]['ticker']} ({fmt(dls[0]['dl_pl'], 1, pct=True)})"
                  f" | mais alavancada: {dls[-1]['ticker']} ({fmt(dls[-1]['dl_pl'], 1, pct=True)})")
        cxs = [l for l in linhas if l["caixa_op_ltm"] is not None]
        if cxs:
            queima = [l["ticker"] for l in cxs if l["caixa_op_ltm"] < 0]
            print(f"   queima caixa nos 12 meses: {', '.join(queima) if queima else 'nenhuma'}")
    print("   Divida de projeto (SFH) e divida corporativa somam aqui: o release separa as duas, o balanco nao.")


def _horas_desde(iso):
    """Horas entre um carimbo ISO em UTC (como o coletor grava gerado_em) e agora; None se ilegivel."""
    if not iso:
        return None
    try:
        t = datetime.datetime.strptime(str(iso)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None
    return (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds() / 3600


def _rotulo_curto(par):
    """(2026, 2) -> '2T26', o formato dos releases."""
    ano, t = par
    return f"{t}T{str(ano)[-2:]}" if ano else "?"


def _itr_mais_novo(tri):
    """Trimestre mais recente com receita na serie oficial (CVM ou SEC): (rotulo original, (ano, tri))."""
    for chave in ("receita_liquida", "receita"):
        s = tri.get(chave) or {}
        qs = sorted([q for q in s if s[q] is not None], key=ordem_periodo)
        if qs:
            return qs[-1], ordem_periodo(qs[-1])
    return None, (0, 0)


_PRAZO_DIAS = {1: 45, 2: 45, 3: 45, 4: 90}
_FIM_TRI = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}


def trimestre_vencido(hoje=None):
    """Ultimo trimestre fechado cujo prazo legal de divulgacao ja venceu (45 dias no 1T a 3T, 90 no 4T).

    E a segunda referencia de frescor: se o ITR atrasar ou o zip da CVM sumir, o release "em dia com o
    ITR" continua velho para o calendario. Devolve (ano, tri) e a data do vencimento."""
    h = hoje or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    tri, ano = (h.month - 1) // 3, h.year
    if tri == 0:
        tri, ano = 4, ano - 1
    for _ in range(6):
        fim = datetime.datetime.strptime(f"{ano}-{_FIM_TRI[tri]}", "%Y-%m-%d")
        venc = fim + datetime.timedelta(days=_PRAZO_DIAS[tri])
        if h >= venc:
            return (ano, tri), venc
        tri -= 1
        if tri == 0:
            tri, ano = 4, ano - 1
    return (0, 0), None


def _eh_b3_sem_bdr(tk):
    """Companhia da B3 que publica na CVM (nao BDR, nao ticker dos EUA): e o caso que precisa de mapa de RI."""
    if not re.fullmatch(r"[A-Z]{4}\d{1,2}", tk or ""):
        return False
    try:
        import pares as _p
        if tk in _p.BDR_SUBJACENTE:
            return False
    except Exception:
        pass
    return tk[4:] not in ("31", "32", "33", "34", "35", "39")


def _mapeado_no_ri(tk):
    try:
        import ri_fontes as _r
        return tk in _r.RI_FONTES
    except Exception:
        return False


def avaliar_frescor(tk, d):
    """(motivos, avisos, detalhes) do frescor de um JSON do branch. Motivo = bloqueia; aviso = so alerta."""
    gerado = d.get("gerado_em")
    idade = _horas_desde(gerado)
    agora_brt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)
    dia_util = agora_brt.weekday() < 5
    teto = 6 if dia_util else 24
    fonte, _, tri, _, _, _, _ = serie_oficial(d)
    itr_rotulo, itr = _itr_mais_novo(tri)
    rel = d.get("release_ri") or {}
    hist = d.get("releases_historico") or []
    primeiro = hist[0] if hist else {}
    rel_periodo = rel.get("periodo") or primeiro.get("periodo")
    rel_data = data_release(rel if rel.get("data") else primeiro)
    rel_fonte = rel.get("fonte") or primeiro.get("fonte")
    rel_ord = ordem_periodo(rel_periodo)
    vencido, venc_data = trimestre_vencido()
    defasagem = None
    if itr != (0, 0) and rel_ord != (0, 0):
        defasagem = (itr[0] * 4 + itr[1]) - (rel_ord[0] * 4 + rel_ord[1])
    atraso_cal = (vencido[0] * 4 + vencido[1]) - (rel_ord[0] * 4 + rel_ord[1]) if (vencido != (0, 0) and rel_ord != (0, 0)) else None
    itr_cal = (vencido[0] * 4 + vencido[1]) - (itr[0] * 4 + itr[1]) if (vencido != (0, 0) and itr != (0, 0)) else None
    detalhes = [f"coletado em {gerado or '-'} | idade {fmt(idade, 1) if idade is not None else '-'} h"
                f" | teto {teto} h ({'dia util' if dia_util else 'fim de semana'}, horario de Brasilia)",
                (f"ITR mais novo: {itr_rotulo} ({_rotulo_curto(itr)}) | {fonte}" if itr_rotulo
                 else "ITR mais novo: AUSENTE | sem demonstracao oficial no JSON"),
                f"release mais novo: {rel_periodo or 'AUSENTE'} | {rel_data or '-'} | {rel_fonte or '-'}",
                (f"calendario: ultimo trimestre com prazo vencido {_rotulo_curto(vencido)} (venceu em {venc_data:%d/%m/%Y})"
                 if vencido != (0, 0) else "calendario: nao calculado")]
    if defasagem is None:
        detalhes.append("defasagem: nao da para medir (falta ITR ou release)")
    elif defasagem == 0:
        detalhes.append("defasagem: 0 trimestre | release e ITR no mesmo trimestre")
    elif defasagem > 0:
        detalhes.append(f"defasagem: {defasagem} trimestre(s) | release ATRAS do ITR: a fala da gestao e mais velha que os numeros")
    else:
        detalhes.append(f"defasagem: {defasagem} trimestre(s) | release a frente do ITR"
                        + (" (normal logo apos a divulgacao)" if defasagem == -1 else " (confira o trimestre do release)"))
    bloco = d.get("frescor")
    detalhes.append("bloco frescor do coletor: " + (" | ".join(f"{k} {json.dumps(v, ensure_ascii=False)}" for k, v in bloco.items() if k != "nota")
                    if isinstance(bloco, dict) and bloco else "ausente (JSON gravado antes de o coletor medir frescor)"))
    motivos, avisos = [], []
    if defasagem is None:
        motivos.append("SEM DADO (falta ITR ou release)")
    elif defasagem > 0:
        motivos.append(f"RELEASE VELHO ({defasagem} trimestre{'s' if defasagem > 1 else ''} atras do ITR)")
    elif defasagem <= -2:
        motivos.append(f"RELEASE ADIANTADO ({-defasagem} trimestres a frente do ITR: trimestre do release suspeito)")
    if atraso_cal is not None and atraso_cal > 0 and not any(m.startswith("RELEASE VELHO") for m in motivos):
        motivos.append(f"RELEASE VELHO (calendario: {_rotulo_curto(vencido)} venceu em {venc_data:%d/%m}, release e {rel_periodo})")
    if itr_cal is not None and itr_cal > 0:
        motivos.append(f"ITR VELHO (calendario: {_rotulo_curto(vencido)} venceu em {venc_data:%d/%m}, ITR e {_rotulo_curto(itr)})")
    if idade is None:
        motivos.append("COLETA VELHA (gerado_em ilegivel)")
    elif idade > teto:
        motivos.append(f"COLETA VELHA ({idade:.0f}h)")
    if _eh_b3_sem_bdr(tk) and not _mapeado_no_ri(tk):
        avisos.append("site de RI: NAO MAPEADO em ri_fontes.py; com a CVM sem indice, a coleta nao vai achar release novo. "
                      "Mapeie a central de resultados (WebSearch) e leve a main ANTES de disparar")
    return motivos, avisos, detalhes


def veredito_frescor(tk, d):
    """Uma linha para o topo de qualquer leitor: 'FRESCOR DIRR3: ATUAL' ou os motivos."""
    motivos, avisos, _ = avaliar_frescor(tk, d)
    linha = f"FRESCOR {tk}: " + (" | ".join(motivos) if motivos else "ATUAL")
    if avisos:
        linha += " | AVISO: " + " | ".join(avisos)
    return linha


def frescor(tk):
    """Idade da coleta e defasagem entre ITR, calendario e release em um VEREDITO. E a trava das skills.

    Saida 0 = ATUAL (release no trimestre do ITR ou mais novo, ITR e release no trimestre que o calendario
    exige, e coleta dentro do teto de horas). Saida 1 = RELEASE VELHO, ITR VELHO, RELEASE ADIANTADO,
    COLETA VELHA ou SEM DADO: a skill dispara a coleta e repete o comando. Le sem cache local.
    """
    d = baixar(f"ativos/{tk}.json", ttl=0)
    if not d:
        print(f"{tk}: nao esta no branch dados. Dispare a coleta (pares: auto).")
        print("VEREDITO: SEM DADO (ativo fora do branch)")
        return 1
    motivos, avisos, detalhes = avaliar_frescor(tk, d)
    print(f"== {tk}: frescor do dado no branch dados")
    for l in detalhes:
        print("  " + l)
    for a in avisos:
        print("  AVISO: " + a)
    print("VEREDITO: " + (" | ".join(motivos) if motivos else "ATUAL"))
    return 1 if motivos else 0


COMANDOS = ("ficha", "serie", "releases", "release", "linha", "decompor", "pares", "balanco", "frescor", "termos", "skills")


def skills():
    """Confere se as skills da mesa estao no lugar e validas. Roda antes de toda pesquisa."""
    base = os.path.join(AQUI, ".claude", "skills")
    esperadas = {
        "analise-ativo": ["SKILL.md", "GLOSSARIO.md"],
        "deep-search": ["SKILL.md"],
        "livro": ["SKILL.md"],
    }
    ok = True
    print("== skills da mesa em .claude/skills/")
    for nome, arquivos in esperadas.items():
        for arq in arquivos:
            caminho = os.path.join(base, nome, arq)
            if not os.path.exists(caminho):
                print(f"  FALTA   {nome}/{arq}")
                ok = False
                continue
            texto = open(caminho, encoding="utf-8").read()
            if arq != "SKILL.md":
                n = sum(1 for l in texto.split("\n") if l.startswith("- **"))
                print(f"  ok      {nome}/{arq}  {n} termos")
                continue
            m = re.match(r"---\n(.*?)\n---\n", texto, re.S)
            if not m:
                print(f"  INVALIDA {nome}/{arq}: sem frontmatter")
                ok = False
                continue
            fm = m.group(1)
            tem_nome = re.search(r"^name:\s*(\S+)", fm, re.M)
            tem_desc = re.search(r"^description:\s*\S", fm, re.M)
            if not tem_nome or not tem_desc:
                print(f"  INVALIDA {nome}/{arq}: falta name ou description")
                ok = False
                continue
            if tem_nome.group(1) != nome:
                print(f"  INVALIDA {nome}/{arq}: name '{tem_nome.group(1)}' nao bate com a pasta")
                ok = False
                continue
            print(f"  ok      {nome}/{arq}  {len(texto.split(chr(10)))} linhas, {len(fm)} chars de gatilho")
    faltando = [c for c in COMANDOS if f'cmd == "{c}"' not in open(os.path.join(AQUI, "mesa.py"), encoding="utf-8").read()]
    print(f"  ok      mesa.py: {len(COMANDOS)} comandos" if not faltando else f"  FALTA   mesa.py: {faltando}")
    ok = ok and not faltando
    try:
        import pares as _p
        print(f"  ok      pares.py: {len(_p.PARES)} grupos, {len(_p.BDR_SUBJACENTE)} BDRs mapeados")
    except Exception as e:
        print(f"  FALTA   pares.py: {e}")
        ok = False
    try:
        import ri_fontes as _r
        chaves = {"empresa", "central", "alternativas", "plataforma", "mz_id", "observacao"}
        ruins = [t for t, v in _r.RI_FONTES.items() if set(v) != chaves or not v.get("central")]
        if ruins:
            print(f"  INVALIDA ri_fontes.py: entradas fora do esquema: {ruins}")
            ok = False
        else:
            print(f"  ok      ri_fontes.py: {len(_r.RI_FONTES)} companhias com central de resultados mapeada")
    except Exception as e:
        print(f"  FALTA   ri_fontes.py: {e}")
        ok = False
    print("\n" + ("TUDO OPERANDO" if ok else "HA PENDENCIA ACIMA"))
    return 0 if ok else 1


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd, args = argv[1], argv[2:]
    if cmd == "ficha" and args:
        ficha(args[0].upper())
    elif cmd == "serie" and args:
        serie(args[0].upper())
    elif cmd == "releases" and args:
        releases(args[0].upper())
    elif cmd == "release" and len(args) >= 2:
        grep = args[args.index("--grep") + 1] if "--grep" in args and args.index("--grep") + 1 < len(args) else None
        release(args[0].upper(), args[1], grep)
    elif cmd == "linha" and len(args) >= 2:
        linha(args[0].upper(), args[1])
    elif cmd == "decompor" and args:
        decompor(args[0].upper())
    elif cmd == "pares" and args:
        pares(args[0].upper())
    elif cmd == "balanco" and args:
        balanco(args[0].upper())
    elif cmd == "frescor" and args:
        return frescor(args[0].upper())
    elif cmd == "termos":
        termos(args)
    elif cmd == "skills":
        return skills()
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
