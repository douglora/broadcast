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
    python3 mesa.py pares INBR32                 # comparativo do grupo com medianas
    python3 mesa.py termos ROE NIM P/VP          # glossario em portugues claro

Nada aqui e opiniao: e leitura do que o coletor gravou. Valores sem fonte no
JSON aparecem como "-", nunca preenchidos.
"""

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


def ficha(tk):
    d = baixar(f"ativos/{tk}.json")
    if not d:
        print(f"{tk}: nao esta no branch dados. Dispare a coleta (pares: auto)."); return
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
        print(f"  {r.get('periodo') or '?':5} {r.get('data')}  {str(r.get('assunto') or r.get('arquivo_sec') or r.get('formulario'))[:50]:52} {r.get('caracteres_total') or 0:>7} chars")
    rel = d.get("release_ri") or {}
    print(f"  mais novo: {rel.get('periodo')} de {rel.get('data')} | {rel.get('fonte')}")
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
        imprimir_serie(d, 12)


def releases(tk):
    idx = baixar(f"releases/{tk}/index.json")
    if not idx:
        return
    print(f"{tk}: {len(idx.get('releases', []))} releases, atualizado em {idx.get('atualizado_em')}")
    for r in idx.get("releases", []):
        print(f"  {r.get('periodo') or '?':5} {r.get('data')}  {str(r.get('assunto') or r.get('arquivo_sec') or r.get('formulario'))[:60]:62} {r.get('caracteres_total') or 0:>7} chars  {r.get('arquivo')}")


def release(tk, periodo, grep=None, contexto=260):
    idx = baixar(f"releases/{tk}/index.json")
    if not idx:
        return
    alvo = next((r for r in idx.get("releases", []) if (r.get("periodo") or "").upper() == periodo.upper()), None)
    if not alvo:
        print(f"{tk}: nao ha release {periodo}. Existem: {[r.get('periodo') for r in idx.get('releases', [])]}")
        return
    texto = baixar(alvo["arquivo"], texto=True)
    if texto is None:
        return
    print(f"== {tk} {alvo.get('periodo')} | {alvo.get('data')} | {alvo.get('assunto') or alvo.get('arquivo_sec')} | {alvo.get('link')}")
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
    elif cmd == "pares" and args:
        pares(args[0].upper())
    elif cmd == "termos":
        termos(args)
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
