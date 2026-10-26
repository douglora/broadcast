#!/usr/bin/env python3
"""Mesa de asset allocation do Douglas: ficha do prospect, proposta, alinhamento e relatorio.

O motor vive em ferramentas/local/alocacao/ (mercado -> premissas -> risco -> otimizacao -> simulacao ->
estresse -> alinhamento -> relatorio). Dado de cliente fica em ~/Documents/Asset Allocation/<cliente>/
(LGPD: nunca no git, nunca em Artifact). A conversa com o prospect segue a skill `asset-allocation`.

    python3 ferramentas/local/alocar.py mercado                       # o que o mercado paga hoje, com frescor
    python3 ferramentas/local/alocar.py novo "Carlos Silva" --set pessoa.idade=52 --set patrimonio.financeiro=8000000
    python3 ferramentas/local/alocar.py ficha "Carlos Silva" --set risco.perfil=moderado
    python3 ferramentas/local/alocar.py sugerir "Carlos Silva"         # carteiras A, B e C para a conversa
    python3 ferramentas/local/alocar.py proposta "Carlos Silva" --candidato A
    python3 ferramentas/local/alocar.py proposta "Carlos Silva" --mover caixa:-2,fii:+2
    python3 ferramentas/local/alocar.py visao "Carlos Silva" fii 1.0 "FIIs de papel pagam mais que a NTN-B"
    python3 ferramentas/local/alocar.py alinhar "Carlos Silva"         # a proposta esta alinhada ao cliente?
    python3 ferramentas/local/alocar.py relatorio "Carlos Silva"       # PDF em <cliente>/saida/

Palavras: "aumentar" e "reduzir", nunca "compre/venda" (a recomendacao e do assessor, CVM 178).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(AQUI))
for p in (AQUI, RAIZ):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np  # noqa: E402

from alocacao import alinha as A  # noqa: E402
from alocacao import atual as AT  # noqa: E402
from alocacao import cliente as CL  # noqa: E402
from alocacao import config as C  # noqa: E402
from alocacao import contexto as X  # noqa: E402
from alocacao import implementacao as I  # noqa: E402
from alocacao import mercado as M  # noqa: E402
from alocacao import otimiza as O  # noqa: E402
from alocacao import relatorio as R  # noqa: E402
from alocacao.formato import brl, mi, num, pct, pp, prob  # noqa: E402


# ------------------------------------------------------------------------------------------------------
def _valor(txt: str):
    """Valor de --set: JSON quando der (52, 8000000, true, [..]), senao o proprio texto."""
    try:
        return json.loads(txt)
    except ValueError:
        return txt


def _campos(sets: list[str] | None) -> dict:
    out = {}
    for s in sets or []:
        if "=" not in s:
            raise ValueError(f"--set espera campo=valor, recebi {s!r}")
        k, v = s.split("=", 1)
        out[k.strip()] = _valor(v.strip())
    return out


def _classe(txt: str) -> str:
    t = txt.strip().lower()
    if t in C.POR_ID:
        return t
    for c in C.CLASSES:
        if t in (c.curto.lower(), c.nome.lower()):
            return c.id
    raise ValueError(f"classe desconhecida {txt!r}. Use: {', '.join(C.IDS)}")


def _tabela_pesos(colunas: dict[str, np.ndarray], minimo: float = 0.0005) -> str:
    nomes = list(colunas)
    larg = max(len(c.curto) for c in C.CLASSES) + 1
    linhas = [f"{'classe':<{larg}} " + " ".join(f"{n:>9}" for n in nomes)]
    for i, c in enumerate(C.CLASSES):
        if all(abs(v[i]) < minimo for v in colunas.values()):
            continue
        linhas.append(f"{c.curto:<{larg}} " + " ".join(f"{pct(v[i], 1):>9}" for v in colunas.values()))
    return "\n".join(linhas)


def _proposta_pesos(nome: str) -> np.ndarray:
    prop = CL.ler_proposta(nome)
    if not prop:
        raise FileNotFoundError(f"{nome}: ainda nao ha proposta (use `alocar.py sugerir` e depois `proposta --candidato A`)")
    w = X.vetor(prop["pesos"])
    return w / w.sum()


def _cabecalho_mercado(m: M.Mercado) -> str:
    sel = f"{m.veredito}" + (f" · em choque ({m.choque_bps:+.0f} bps no DI de 3 anos)" if m.em_choque else "")
    return f"MERCADO {sel} · leitura de {m.consulta}"


# ------------------------------------------------------------------------------------------------------
def cmd_mercado(a) -> None:
    m = M.carregar(curva=a.curva)
    print(_cabecalho_mercado(m))
    print(f"Selic {num(m.selic_meta,2)}% · CDI {num(m.cdi,2)}% · IPCA 12m {num(m.ipca_12m,2)}% · IPCA esperado 10a {num(m.ipca_esperado(10),2)}% (Focus {m.focus_data})")
    est = " (ESTIMATIVA: choque do dia)" if m.em_choque else ""
    print(f"DI x pré: 1a {num(m.di_aa(1),2)}% · 3a {num(m.di_aa(3),2)}% · 5a {num(m.di_aa(5),2)}% · 10a {num(m.di_aa(10),2)}% ({'hoje ' + m.di_vivo_hora if m.di_vivo else 'ajuste ' + m.di_data})")
    print(f"NTN-B 10a {num(m.real_aa(10),2)}%{est} (ANBIMA {m.ntnb_data}) · pré 10a {num(m.pre_aa(10),2)}%{est}")
    if m.em_choque:
        print(f"Curva de ontem (ajuste {m.di_data}): DI 3a {num(m.di_ajuste_aa(3),2)}%. Rode também com --curva ontem para ver a leitura sem o ruído do dia.")
    print(f"Treasury 10a {num(m.ust10,2)}% ({m.ust_data}) · PTAX R$ {num(m.ptax,4)} ({m.ptax_data}) · TIR mediana da bolsa {pct(m.tir_mediana_real or 0, 1)} real ({m.tir_data})")
    for av in m.avisos:
        print(f"AVISO: {av}")
    if m.ajustes:
        print(f"Ajustes manuais em vigor: {json.dumps(m.ajustes, ensure_ascii=False)}")


def cmd_listar(a) -> None:
    nomes = CL.listar()
    if not nomes:
        print(f"Nenhum cliente em {C.CLIENTES}. Crie com: alocar.py novo \"Nome\"")
        return
    for n in nomes:
        f = CL.ler_ficha(n)
        prop = CL.ler_proposta(n)
        print(f"- {f['nome']} ({n}) · {f.get('tipo')} · perfil {f['risco'].get('perfil') or '?'} · proposta {'v' + str(prop['versao']) if prop else 'não há'}")


def cmd_novo(a) -> None:
    f = CL.novo(a.nome, **_campos(a.set))
    print(f"Ficha criada em {CL.pasta(a.nome)}")
    _mostrar_ficha(f)


def _mostrar_ficha(f: dict) -> None:
    for sec in ("pessoa", "patrimonio", "fluxo", "objetivo", "risco", "liquidez", "restricoes", "moeda", "fiscal", "sucessao"):
        itens = {k: v for k, v in f[sec].items() if v not in (None, "", [], {})}
        print(f"[{sec}] " + (json.dumps(itens, ensure_ascii=False) if itens else "—"))
    if f.get("observacoes"):
        print("[observacoes] " + " | ".join(f["observacoes"]))
    ok, falta = CL.pronta_para_proposta(f)
    print("PRONTA PARA PROPOSTA" if ok else "NÃO está pronta para proposta; falta (peso 1): " + " / ".join(falta))
    lac = CL.lacunas(f)
    if lac:
        print("Ainda a perguntar (do mais importante ao menos):")
        for x in lac[:8]:
            print(f"  [{x['peso']}] {x['pergunta']}")


def cmd_ficha(a) -> None:
    if a.set:
        CL.atualizar(a.nome, _campos(a.set))
        CL.anotar(a.nome, "Ficha atualizada: " + ", ".join(f"{k}={v}" for k, v in _campos(a.set).items()))
    if a.observacao:
        f = CL.ler_ficha(a.nome)
        CL.atualizar(a.nome, {"observacoes": f.get("observacoes", []) + [a.observacao]})
    _mostrar_ficha(CL.ler_ficha(a.nome))


def cmd_visao(a) -> None:
    if a.listar or (a.classe is None and a.desativar is None):
        for v in CL.ler_visoes(a.nome):
            print(f"#{v['id']} {'ativa' if v.get('ativa', True) else 'desativada'} · {v['classe']} {v['delta_pp']:+.1f} p.p./ano · {v['tese']}")
        return
    if a.desativar is not None:
        CL.desativar_visao(a.nome, a.desativar)
        print(f"Visão #{a.desativar} desativada.")
        return
    cid = a.classe if a.classe in ("_cdi", "_ipca") else _classe(a.classe)
    v = CL.gravar_visao(a.nome, cid, a.delta_pp, a.tese or "", direcao=a.direcao)
    print(f"Visão #{v['id']} gravada: {cid} {a.delta_pp:+.1f} p.p./ano. Rode `alinhar` para ver o efeito.")


def cmd_sugerir(a) -> None:
    ctx = X.montar(a.nome, curva=a.curva, n_sim=2000)
    print(_cabecalho_mercado(ctx.mercado))
    inv = O.viabilidade(ctx.restr)
    if inv:
        print(f"INVIÁVEL: {inv}")
        return
    cs = O.candidatos(ctx.mu, ctx.cov, ctx.restr)
    cols = {"Modelo": ctx.w_modelo}
    for c in cs:
        if c.get("w") is not None:
            cols[c["cod"]] = c["w"]
    print(f"Perfil {C.ROTULOS_PERFIL[ctx.perfil]} · horizonte {num(ctx.horizonte,0)} anos · PL {mi(ctx.plano.pl)} · queda máx. {pct(ctx.queda_limite,0)} · 100% CDI líquido {pct(ctx.bench,1)}")
    print(_tabela_pesos(cols))
    modelo = X.avaliar(ctx, ctx.w_modelo)
    print(f"Modelo: retorno {pct(modelo['ret'],1)} · vol {pct(modelo['vol'],1)}")
    for c in cs:
        if c.get("w") is None:
            print(f"{c['cod']} · {c['nome']}: não resolveu ({'; '.join(c.get('avisos') or [])})")
            continue
        print(f"{c['cod']} · {c['nome']}: retorno {pct(c['ret'],1)} · vol {pct(c['vol'],1)}" + (f" · {'; '.join(c['avisos'])}" if c.get("avisos") else ""))
    print("Grave uma delas com: alocar.py proposta NOME --candidato A")


def cmd_proposta(a) -> None:
    ctx = X.montar(a.nome, curva=a.curva, n_sim=2000)
    if a.candidato:
        cs = {c["cod"]: c for c in O.candidatos(ctx.mu, ctx.cov, ctx.restr)}
        c = cs.get(a.candidato.upper())
        if not c or c.get("w") is None:
            raise ValueError(f"candidato {a.candidato!r} indisponível")
        pesos, origem, nota = O.para_dict(c["w"]), f"otimizador {c['cod']}", a.nota or c["nome"] + "."
    elif a.pesos:
        raw = {}
        for par in a.pesos.split(","):
            k, v = par.split("=")
            raw[_classe(k)] = float(v) / 100.0
        s = sum(raw.values())
        if abs(s - 1.0) > 0.0051:
            raise ValueError(f"os pesos somam {s*100:.1f}%, tem de somar 100%")
        pesos, origem, nota = {k: v / s for k, v in raw.items()}, "manual do assessor", a.nota or ""
    elif a.mover:
        base = _proposta_pesos(a.nome)
        w = base.copy()
        delta = {}
        for par in a.mover.split(","):
            k, v = par.split(":")
            delta[_classe(k)] = float(v) / 100.0
        for cid, d in delta.items():
            w[C.IDS.index(cid)] += d
        if abs(sum(delta.values())) > 0.0051:
            raise ValueError(f"os movimentos somam {sum(delta.values())*100:+.1f} p.p.; o que sai tem de entrar (some 0)")
        if (w < -1e-9).any():
            raise ValueError("o movimento deixaria uma classe negativa")
        pesos = O.para_dict(w / w.sum())
        origem = "ajuste do assessor"
        nota = a.nota or "Movimentos sobre a versão anterior: " + ", ".join(f"{C.POR_ID[k].curto} {v*100:+.1f} p.p." for k, v in delta.items()) + "."
    else:
        raise ValueError("diga a proposta: --candidato A|B|C, --pesos \"caixa=9,pos_isenta=23,...\" (em %) ou --mover caixa:-2,fii:+2")
    prop = CL.gravar_proposta(a.nome, pesos, origem, nota)
    print(f"Proposta v{prop['versao']} gravada ({origem}).")
    if not a.quieto:
        _alinhar(a.nome, a.curva, n_sim=a.sims)


def _avaliar_txt(nome: str, rotulo: str, ctx: X.Contexto, w: np.ndarray) -> dict:
    ev = X.avaliar(ctx, w, rotulo)
    sim = ev["sim"]
    pior = ev["estresse"]["pior"]
    print(f"{rotulo}: retorno {pct(ev['ret'],1)} líquido ({pct(ev['ret_real'],1)} real) · vol {pct(ev['vol'],1)} · excesso sobre 100% CDI líquido {pp(ev['excesso'],2)} · RV {pct(ev['rv'],0)} · dólar {pct(ev['usd'],0)}"
          + (f" · chance da meta {prob(sim['p_meta'],0)}" if sim["p_meta"] is not None else "")
          + (f" · pior cenário {pior['nome']} {pct(pior['total'],1)}" if pior else ""))
    return ev


def _alinhar(nome: str, curva: str, n_sim: int = 10000) -> None:
    ctx = X.montar(nome, curva=curva, n_sim=n_sim)
    print(_cabecalho_mercado(ctx.mercado))
    w = _proposta_pesos(nome)
    ev = _avaliar_txt(nome, "Proposta", ctx, w)
    checks = A.checar(ctx, ev)
    ver = A.veredito(checks)
    print(A.resumo_texto(checks, ver))
    if ctx.atual and ctx.atual.get("pesos"):
        wa = X.vetor(ctx.atual["pesos"])
        wa = wa / wa.sum()
        eva = _avaliar_txt(nome, "Carteira atual", ctx, wa)
        va = A.veredito(A.checar(ctx, eva))
        print(f"Carteira atual: {va['veredito']} ({va['contagem']['ok']} ✅ · {va['contagem']['atencao']} 🟡 · {va['contagem']['fora']} 🔴)")


def cmd_alinhar(a) -> None:
    _alinhar(a.nome, a.curva, n_sim=a.sims)


def cmd_avaliar(a) -> None:
    ctx = X.montar(a.nome, curva=a.curva, n_sim=a.sims)
    print(_cabecalho_mercado(ctx.mercado))
    w = _proposta_pesos(a.nome)
    cols = {"Modelo": ctx.w_modelo, "Proposta": w}
    if ctx.atual and ctx.atual.get("pesos"):
        wa = X.vetor(ctx.atual["pesos"])
        cols = {"Atual": wa / wa.sum(), **cols}
    print(_tabela_pesos(cols))
    _avaliar_txt(a.nome, "Modelo do perfil", ctx, ctx.w_modelo)
    _avaliar_txt(a.nome, "Proposta", ctx, w)
    if "Atual" in cols:
        _avaliar_txt(a.nome, "Carteira atual", ctx, cols["Atual"])
    ev = X.avaliar(ctx, w, "proposta")
    rc = ev["rc"]
    topo = sorted(((rc[i], C.CLASSES[i].curto) for i in range(len(C.IDS)) if rc[i] > 0.02), reverse=True)[:4]
    print("Risco por classe: " + " · ".join(f"{n} {pct(v,0)}" for v, n in topo) + f" · apostas independentes {num(ev['enb'],1)}")
    print(f"Imposto: {pct(ev['irpfm']['protegido'],0)} protegido do IRPFM · custo {pct(ev['custo'],2)} a.a. · liquidez D+1 {pct(ev['liq']['d1'],0)}, até D+30 {pct(ev['liq']['d1']+ev['liq']['d5']+ev['liq']['d30'],0)}")


def cmd_simular(a) -> None:
    ctx = X.montar(a.nome, curva=a.curva, n_sim=a.sims)
    ev = X.avaliar(ctx, _proposta_pesos(a.nome), "proposta")
    s = ev["sim"]
    print(_cabecalho_mercado(ctx.mercado))
    print(f"{num(s['n'],0)} trajetórias, {num(s['anos'],0)} anos, semente {s['semente']}. Valores em R$ de hoje.")
    fr = s["final_real"]
    print("Patrimônio final: P5 " + mi(fr[5]) + " · P25 " + mi(fr[25]) + " · mediana " + mi(fr[50]) + " · P75 " + mi(fr[75]) + " · P95 " + mi(fr[95]))
    if s["p_meta"] is not None:
        print(f"Chance de atingir {mi(ctx.plano.meta)}: {prob(s['p_meta'],0)} (o plano exige {pct(ev['retorno_necessario'],1)} ao ano)" if ev["retorno_necessario"] is not None else f"Chance de atingir a meta: {prob(s['p_meta'],0)}")
    print(f"CAGR mediano {pct(s['cagr_mediano'],1)} ({pct(s['cagr_real_mediano'],1)} real) · faixa 5%-95%: {pct(s['cagr_p5'],1)} a {pct(s['cagr_p95'],1)}")
    print(f"Perder poder de compra: {prob(s['p_perde_poder_compra'],1)} · janela de 12m negativa: {prob(s['p_neg_12m'],1)} · pior janela 12m (1 em 20): {pct(s['var95_12m'],1)} · maior queda (1 em 20): {pct(s['mdd_p95'],1)}")


def cmd_stress(a) -> None:
    ctx = X.montar(a.nome, curva=a.curva, n_sim=500)
    ev = X.avaliar(ctx, _proposta_pesos(a.nome), "proposta")
    est = ev["estresse"]
    print(_cabecalho_mercado(ctx.mercado))
    print(f"Limite de queda do cliente: {pct(ctx.queda_limite,0)}. Choques são hipóteses da mesa, instantâneos e a mercado.")
    for r in est["cenarios"]:
        print(f"- {r['nome']}: {pct(r['total'],1)}" + (f" · recupera em ~{int(r['meses_para_recuperar'])} meses" if r["meses_para_recuperar"] else ""))


def cmd_movimentos(a) -> None:
    ctx = X.montar(a.nome, curva=a.curva, n_sim=500)
    w = _proposta_pesos(a.nome)
    wa = None
    if ctx.atual and ctx.atual.get("pesos"):
        wa = X.vetor(ctx.atual["pesos"])
        wa = wa / wa.sum()
    tr = I.transicao(w, wa, ctx.plano.pl, ctx.mercado.em_choque)
    print(f"Giro de {pct(tr['giro'],0)} da carteira · base: {'carteira atual' if wa is not None else 'tudo em caixa (dinheiro novo)'}")
    for p in tr["passos"]:
        print(f"- {p['janela']}: {p['acao']} {C.POR_ID[p['classe']].curto} {num(abs(p['pp']),1)} p.p. ({brl(p['reais'])})" + (f" em {p['parcelas']}x de {brl(p['por_parcela'])}" if p["parcelas"] > 1 else ""))


def cmd_relatorio(a) -> None:
    r = R.gerar(a.nome, curva=a.curva, n_sim=a.sims, pdf=not a.sem_pdf)
    CL.anotar(a.nome, f"Relatório gerado ({r['veredito']}): {r['pdf'] or r['html']}")
    print(f"Veredito: {r['veredito']}")
    print(f"HTML: {r['html']}")
    if r["pdf"]:
        print(f"PDF:  {r['pdf']}")
    print("Dado de cliente: fica nesta pasta do Mac (LGPD); não vai ao git nem a Artifact.")


def cmd_importar(a) -> None:
    dado = AT.importar(Path(a.arquivo).expanduser(), CL.pasta(a.nome))
    CL.gravar_atual(a.nome, dado)
    CL.anotar(a.nome, f"Carteira atual importada de {Path(a.arquivo).name}: {brl(dado['total'])} em {len(dado['posicoes'])} posições.")
    print(f"Importado: {brl(dado['total'])} em {len(dado['posicoes'])} posições.")
    for cid, v in sorted(dado["pesos"].items(), key=lambda kv: -kv[1]):
        if v > 0.0005:
            print(f"- {C.POR_ID[cid].curto}: {pct(v,1)}")
    for x in dado["a_conferir"][:10]:
        print(f"CONFERIR: {x}")


def cmd_diario(a) -> None:
    if a.anotar:
        CL.anotar(a.nome, a.anotar)
    print(CL.ler_diario(a.nome) or "(diário vazio)")


def cmd_ajuste(a) -> None:
    arq = C.CACHE / "ajustes.json"
    try:
        d = json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    if a.chave == "mostrar":
        print(json.dumps(d, ensure_ascii=False, indent=2) if d else "Sem ajustes manuais.")
        return
    if a.chave not in ("real_bps", "cenario_hoje"):
        raise ValueError("chaves aceitas: real_bps, cenario_hoje, mostrar")
    if a.valor is None or a.valor.lower() == "limpar":
        d.pop(a.chave, None)
    else:
        d[a.chave] = _valor(a.valor)
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ajustes.json: {json.dumps(d, ensure_ascii=False)}")


# ------------------------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def com_cliente(nome, ajuda, func, curva=True, sims=False):
        sp = sub.add_parser(nome, help=ajuda)
        sp.add_argument("nome", help="nome do cliente ou prospect")
        if curva:
            sp.add_argument("--curva", choices=("viva", "ontem"), default="viva", help="DI de agora (viva) ou o ajuste de ontem")
        if sims:
            sp.add_argument("--sims", type=int, default=10000, help="trajetórias do Monte Carlo (padrão 10000)")
        sp.set_defaults(func=func)
        return sp

    sp = sub.add_parser("mercado", help="o que o mercado paga hoje, com frescor")
    sp.add_argument("--curva", choices=("viva", "ontem"), default="viva")
    sp.set_defaults(func=cmd_mercado)

    sp = sub.add_parser("listar", help="clientes e prospects")
    sp.set_defaults(func=cmd_listar)

    sp = com_cliente("novo", "cria a ficha", cmd_novo, curva=False)
    sp.add_argument("--set", action="append", help="campo=valor (ex.: pessoa.idade=52); repita")

    sp = com_cliente("ficha", "mostra ou atualiza a ficha", cmd_ficha, curva=False)
    sp.add_argument("--set", action="append", help="campo=valor; repita")
    sp.add_argument("--observacao", help="anota uma observação do assessor na ficha")

    sp = com_cliente("visao", "registra a opinião do Douglas como deslocamento visível das premissas", cmd_visao, curva=False)
    sp.add_argument("classe", nargs="?", help="classe (ex.: fii, rv_br) ou _cdi / _ipca")
    sp.add_argument("delta_pp", nargs="?", type=float, help="deslocamento do retorno em p.p. ao ano (+1,0 = mais otimista)")
    sp.add_argument("tese", nargs="?", help="a tese em uma frase")
    sp.add_argument("--direcao", type=int, default=0, help="+1 quer mais da classe, -1 quer menos (o alinhamento confere)")
    sp.add_argument("--desativar", type=int, help="desativa a visão de número N")
    sp.add_argument("--listar", action="store_true")

    com_cliente("sugerir", "carteiras A (modelo), B (eficiente) e C (defensiva)", cmd_sugerir)

    sp = com_cliente("proposta", "grava a proposta vigente (e mostra o alinhamento)", cmd_proposta, sims=True)
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--candidato", help="A, B ou C do `sugerir`")
    g.add_argument("--pesos", help='pesos em %% por classe: "caixa=9,pos_isenta=23,..."')
    g.add_argument("--mover", help='movimentos em p.p. sobre a versão anterior: "caixa:-2,fii:+2" (tem de somar zero)')
    sp.add_argument("--nota", help="comentário que acompanha a versão")
    sp.add_argument("--quieto", action="store_true", help="não roda o alinhamento depois de gravar")

    com_cliente("alinhar", "a proposta está alinhada ao cliente?", cmd_alinhar, sims=True)
    com_cliente("avaliar", "números da proposta ao lado do modelo e da carteira atual", cmd_avaliar, sims=True)
    com_cliente("simular", "Monte Carlo da proposta", cmd_simular, sims=True)
    com_cliente("stress", "cenários adversos", cmd_stress)
    com_cliente("movimentos", "plano de transição: o que aumentar e reduzir, em que ritmo", cmd_movimentos)

    sp = com_cliente("relatorio", "gera o relatório em PDF (e HTML) em <cliente>/saida/", cmd_relatorio, sims=True)
    sp.add_argument("--sem-pdf", action="store_true")

    sp = com_cliente("importar", "lê o extrato do cliente (PDF/planilha) e grava a carteira atual", cmd_importar, curva=False)
    sp.add_argument("arquivo")

    sp = com_cliente("diario", "mostra ou anota o diário da conversa", cmd_diario, curva=False)
    sp.add_argument("--anotar", help="acrescenta uma linha ao diário")

    sp = sub.add_parser("ajuste", help="ajuste manual de mercado em dia de choque (real_bps, cenario_hoje)")
    sp.add_argument("chave", help="real_bps | cenario_hoje | mostrar")
    sp.add_argument("valor", nargs="?", help="número (bps) ou JSON; 'limpar' remove")
    sp.set_defaults(func=cmd_ajuste)

    a = ap.parse_args(argv)
    try:
        a.func(a)
    except (FileNotFoundError, FileExistsError, ValueError, KeyError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
