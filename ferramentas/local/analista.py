#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Analista de acoes da mesa do Douglas: momento economico, balanco integral da CVM, roteiro do setor,
TIR real implicita (regua NTN-B 2035), preco justo no metodo de Damodaran, ponte com o Safra e o
relatorio no padrao visual aprovado (azul-marinho, Montserrat, "Figura N."), resumido ou profundo.

O motor vive em ferramentas/local/analista/. A conversa segue a skill `analise-ativo`. Antes de usar,
o ativo tem de estar coletado (python3 ferramentas/local/coletar.py TICKER --pares auto) e o veredito
de `mesa.py frescor` e `mesa.py cobertura` tem de estar na resposta.

    python3 ferramentas/local/analista.py macro                      # terreno para a bolsa: Focus, NTN-B, regime, premio exigido
    python3 ferramentas/local/analista.py setor CPLE3                # como o especialista do setor olha, armadilhas e perguntas
    python3 ferramentas/local/analista.py balanco CPLE3 --dem DFC    # demonstracao inteira da CVM (DRE, BPA, BPP, DFC, DVA)
    python3 ferramentas/local/analista.py rapido CPLE3               # a resposta curta: 12 linhas com o que decide
    python3 ferramentas/local/analista.py completo CPLE3             # tudo em texto: macro, setor, TIR, Damodaran e a ponte
    python3 ferramentas/local/analista.py tir CPLE3                  # TIR real, estresse, conta reversa, livro de premissas
    python3 ferramentas/local/analista.py damodaran CPLE3            # preco justo, sensibilidade e o que o preco embute
    python3 ferramentas/local/analista.py safra CPLE3                # ponte: Safra x mesa x Damodaran x consenso
    python3 ferramentas/local/analista.py safra CPLE3 --alvo 19,50 --tir 11,3 --data 2026-11-10 --rec compra
    python3 ferramentas/local/analista.py premissa TAEE11 fim 2042 --fonte "Formulario de Referencia 2026, item 1.4" --tipo OFICIAL
    python3 ferramentas/local/analista.py premissa TAEE11            # lista o caso da mesa
    python3 ferramentas/local/analista.py texto CPLE3                # cria o texto.json do analista (tese, gestao, riscos)
    python3 ferramentas/local/analista.py relatorio CPLE3 --resumido --pdf
    python3 ferramentas/local/analista.py relatorio CPLE3 --profundo --pdf --artifact   # + pagina para publicar, com botao de PDF

Regras: nenhum numero sem fonte e data; premissa sem documento nao entra (a conta para e diz o que
falta); nunca "compre/venda" (a recomendacao e do assessor, Resolucao CVM 178).
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analista import base as B  # noqa: E402
from analista import cvm_integral as C  # noqa: E402
from analista import damodaran as D  # noqa: E402
from analista import macro as MAC  # noqa: E402
from analista import relatorio as R  # noqa: E402
from analista import safra as F  # noqa: E402
from analista import setores as S  # noqa: E402
from analista import tir_real as T  # noqa: E402


def _num(txt):
    """'19,50' ou '19.50' -> 19.5 (formato brasileiro aceito)."""
    if txt is None:
        return None
    s = str(txt).strip().replace("%", "").replace("R$", "").strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    return float(s)


def _ipca(v, casas=1):
    return "não fecha" if v is None else f"IPCA + {B.br(v * 100, casas)}%"


def cmd_macro(a):
    print(MAC.texto(MAC.carregar()))


def cmd_setor(a):
    print(S.texto(S.identificar(a.ticker, B.ativo(a.ticker))))


def cmd_balanco(a):
    d = B.ativo(a.ticker)
    cvm = d.get("cvm_demonstracoes") or {}
    if not cvm.get("cd_cvm"):
        raise B.SemDado(f"{a.ticker.upper()}: sem código CVM no JSON do ativo (BDR ou empresa estrangeira).")
    integral = C.carregar(cvm["cd_cvm"])
    dems = ("DRE", "BPA", "BPP", "DFC", "DVA") if a.dem == "tudo" else (a.dem,)
    for dem in dems:
        C.imprimir(integral, dem, a.anos, a.nivel)
        print()
    print("Fonte: CVM, DFP consolidada (dados abertos), exercícios completos. Trimestres: ITR, no JSON do ativo.")


def cmd_tir(a):
    c = R.coletar(a.ticker, preco=_num(a.preco))
    if not c["tir"]:
        raise B.SemDado(f"{c['ticker']}: {'banco e seguradora não têm TIR por caixa; use damodaran e safra' if c['financeira'] else '; '.join(c['lacunas'])}")
    print(T.texto(c["tir"]))


def cmd_damodaran(a):
    c = R.coletar(a.ticker, preco=_num(a.preco))
    if not c["dam"]:
        raise B.SemDado("; ".join(c["lacunas"]))
    print(D.texto(c["dam"]))


def cmd_safra(a):
    if a.alvo is not None or a.tir is not None:
        tir = _num(a.tir)
        item = F.informar(a.ticker, alvo=_num(a.alvo), tir=None if tir is None else tir / 100.0, data=a.data, preco=_num(a.preco_data), rec=a.rec, fonte=a.fonte)
        print(f"Guardado ({a.ticker.upper()}): {item}\n")
    c = R.coletar(a.ticker)
    print(F.texto(c["ponte"]))


def cmd_premissa(a):
    tk = a.ticker.upper()
    arq = T.PREMISSAS / f"{tk}.json"
    d = B.ler_json(arq) or {"ticker": tk, "resumo": "", "itens": {}}
    if a.chave is None:
        if not d["itens"]:
            print(f"{tk}: sem caso da mesa. Chaves aceitas: {', '.join(T.CHAVES)}.")
            return
        print(f"CASO DA MESA  {tk}  ({arq})")
        for k, x in d["itens"].items():
            print(f"  {k:<18} {x['valor']!s:<14} [{x.get('tipo', B.GUIDANCE)}] {x['fonte']}" + (f", {B.data_br(x['data'])}" if x.get("data") else ""))
        return
    if a.chave not in T.CHAVES:
        raise B.SemDado(f"premissa desconhecida '{a.chave}'. Aceitas: {', '.join(T.CHAVES)}")
    if a.valor is None or not (a.fonte or "").strip():
        raise B.SemDado("premissa precisa de valor e de --fonte (documento, página). Sem documento não entra na conta.")
    v = [_num(x) for x in a.valor.split(";")] if ";" in a.valor else _num(a.valor)
    if a.chave in ("g", "g_t", "custo_real_divida"):                 # taxas entram em % na linha de comando
        v = [x / 100.0 for x in v] if isinstance(v, list) else v / 100.0
    if a.chave == "fim":
        v = int(v)
    d["itens"][a.chave] = {"valor": v, "fonte": a.fonte.strip(), "data": a.data or dt.date.today().isoformat(), "tipo": a.tipo}
    if a.resumo:
        d["resumo"] = a.resumo
    B.gravar_json(arq, d)
    print(f"Guardado em {arq}: {a.chave} = {v} [{a.tipo}] {a.fonte}")


def _rapido(c):
    """A resposta curta: so o que decide, em linhas que cabem no celular."""
    tk, o, dm, sf, po, m = c["ticker"], c["tir"], c["dam"], c["safra"], c["ponte"], c["mac"]
    L = [f"{tk}  {c['nome']}  |  {c['setor']['nome']}  |  preço {B.reais(c['preco'])} ({B.data_br(c['data_preco'])})",
         f"Em uma frase: {R.frase(c)}", "",
         f"Terreno: {m['regime']['nome'].upper()}; NTN-B 2035 a {_ipca(m['ntnb_2035'], 2)}; prêmio exigido {B.br(m['regime']['premio_exigido'] * 100, 1)} pp."]
    if o:
        for x in o["cenarios"]:
            L.append(f"TIR real, {x['nome'].lower()}: {_ipca(x['tir'])}" + (f" ({B.br(abs(x['premio']) * 100, 1)} pp {'acima' if x['premio'] >= 0 else 'abaixo'} da NTN-B)" if x["premio"] is not None else ""))
        r = o["reversa"][0]
        L.append(f"O preço exige: caixa do dono crescendo {B.pct(r['crescimento']) if r['crescimento'] is not None else 'n/d'} a.a. real por 10 anos"
                 + (f", ou preço de {B.reais(r['preco'])}" if r.get("preco") else "") + f" para render {_ipca(r['taxa'])}.")
        L.append(f"Previsibilidade: {o['previsibilidade']['frase']}")
    else:
        for n, v, nota in po["retornos"]:
            L.append(f"{n}: {_ipca(v)} ({nota})")
    if dm:
        L.append(f"Damodaran: preço justo {B.reais(dm['preco_justo'])} ({B.pct(dm['potencial'], 0, True)}); Ke {B.pct(dm['custo']['ke_real'])} real = {B.pct(dm['custo']['ke_nominal'])} nominal.")
    if sf.get("tir"):
        L.append(f"Safra: TIR real {B.pct(sf['tir']['ref'])} em {B.data_br(sf['tir']['data'])} = {_ipca(sf['tir']['hoje'])} ao preço de hoje" + (" (VELHA)" if sf["tir"]["velha"] else "") + ".")
    if sf.get("alvo"):
        L.append(f"Safra: preço-alvo {B.reais(sf['alvo']['alvo'])} de {B.data_br(sf['alvo']['data'])}" + (" (VELHO)" if sf["alvo"]["velho"] else "") + (f", {sf['alvo']['rec']}" if sf["alvo"].get("rec") else "") + ".")
    if sf.get("consenso"):
        L.append(f"Consenso: alvo mediano {B.reais(sf['consenso']['alvo'])} ({sf['consenso'].get('casas') or '?'} casas).")
    L += ["Ponte:"] + [f"  - {x}" for x in po["leitura"][:3]]
    avisos = []
    for x in (o, dm):
        if x:
            avisos += [v for v in x["livro"].avisos if v not in avisos and not (o and v in (o["previsibilidade"].get("frase"), o["previsibilidade"].get("aviso")))]
    if avisos:
        L += ["Ressalvas da conta:"] + [f"  - {x}" for x in avisos[:3]]
    L += [f"LACUNA: {x}" for x in c["lacunas"]] + [f"AVISO: {x}" for x in sf["avisos"]]
    return "\n".join(L)


def cmd_rapido(a):
    print(_rapido(R.coletar(a.ticker, preco=_num(a.preco))))


def cmd_completo(a):
    c = R.coletar(a.ticker, preco=_num(a.preco))
    blocos = [MAC.texto(c["mac"]), S.texto(c["setor"])]
    if c["tir"]:
        blocos.append(T.texto(c["tir"]))
    if c["dam"]:
        blocos.append(D.texto(c["dam"]))
    blocos.append(F.texto(c["ponte"]))
    for x in c["lacunas"]:
        blocos.append(f"LACUNA: {x}")
    print(("\n\n" + "=" * 100 + "\n\n").join(blocos))


def cmd_texto(a):
    arq = R.modelo_texto(a.ticker)
    print(f"Texto do analista: {arq}\nPreencha com o que saiu da leitura dos releases (mesa.py releases/release/linha) e do balanço; "
          "item de gestão, setor e notícia sem fonte derruba a montagem.")


def cmd_relatorio(a):
    modos = [m for m, on in (("resumido", a.resumido), ("profundo", a.profundo)) if on]
    if not modos:
        raise B.SemDado("escolha --resumido, --profundo ou os dois.")
    c = R.coletar(a.ticker, preco=_num(a.preco))
    tx = {} if a.sem_texto else R.ler_texto(c["ticker"], a.texto)
    if not tx and not a.sem_texto:
        print("AVISO: sem texto.json do analista; o relatório sai só com as contas (use `texto TICKER` para criar o modelo).")
    for modo in modos:
        o = R.gravar(c["ticker"], modo, texto=tx, contexto=c, pdf=a.pdf)
        print(f"{modo}: {o['html']}  ({o['figuras']} figuras)" + (f"\n          {o['pdf']}" if o.get("pdf") else ("\n          PDF não gerado (Chrome não respondeu)" if a.pdf else "")))
        if o.get("pdf"):
            pgs = R.paginas(o["pdf"])
            if pgs:
                print(f"          {len(pgs)} páginas para conferir: {pgs[0].parent}/{pgs[0].name.rsplit('-p', 1)[0]}-pN.png"
                      + ("  (modo compacto: passava da meta)" if o.get("compacta") else ""))
                if modo == "resumido" and len(pgs) > R.META_RESUMIDO:
                    print(f"ATENCAO: o resumido saiu com {len(pgs)} páginas (meta: {R.META_RESUMIDO}). Encurte o texto.json antes de mandar.")
        if a.artifact:
            pag, pdf = R.para_artifact(o["html"])
            print(f"          artifact: {pag}" + (f'\n          publicar com files={{"relatorio.pdf": "{pdf}"}} e capabilities={{"downloads": true}}' if pdf else
                                                 "  (sem PDF ao lado: sem botão de download)"))
    for x in c["lacunas"]:
        print(f"LACUNA: {x}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Analista de ações da mesa (TIR real, Damodaran, ponte com o Safra, relatório).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("macro").set_defaults(f=cmd_macro)
    for nome, f in (("setor", cmd_setor), ("texto", cmd_texto)):
        p = sub.add_parser(nome); p.add_argument("ticker"); p.set_defaults(f=f)
    p = sub.add_parser("balanco"); p.add_argument("ticker"); p.add_argument("--dem", default="DRE", choices=("DRE", "BPA", "BPP", "DFC", "DVA", "tudo"))
    p.add_argument("--anos", type=int, default=5); p.add_argument("--nivel", type=int, default=3); p.set_defaults(f=cmd_balanco)
    for nome, f in (("tir", cmd_tir), ("damodaran", cmd_damodaran), ("rapido", cmd_rapido), ("completo", cmd_completo)):
        p = sub.add_parser(nome); p.add_argument("ticker"); p.add_argument("--preco"); p.set_defaults(f=f)
    p = sub.add_parser("safra"); p.add_argument("ticker"); p.add_argument("--alvo"); p.add_argument("--tir"); p.add_argument("--data")
    p.add_argument("--preco-data", dest="preco_data"); p.add_argument("--rec"); p.add_argument("--fonte"); p.set_defaults(f=cmd_safra)
    p = sub.add_parser("premissa"); p.add_argument("ticker"); p.add_argument("chave", nargs="?"); p.add_argument("valor", nargs="?")
    p.add_argument("--fonte"); p.add_argument("--data"); p.add_argument("--tipo", default=B.GUIDANCE, choices=(B.OFICIAL, B.GUIDANCE, B.CONSENSO, B.MESA))
    p.add_argument("--resumo"); p.set_defaults(f=cmd_premissa)
    p = sub.add_parser("relatorio"); p.add_argument("ticker"); p.add_argument("--resumido", action="store_true"); p.add_argument("--profundo", action="store_true")
    p.add_argument("--pdf", action="store_true"); p.add_argument("--artifact", action="store_true"); p.add_argument("--texto")
    p.add_argument("--sem-texto", dest="sem_texto", action="store_true")
    p.add_argument("--preco"); p.set_defaults(f=cmd_relatorio)
    a = ap.parse_args(argv)
    try:
        a.f(a)
    except B.SemDado as e:
        print(f"SEM DADO: {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
