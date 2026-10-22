#!/usr/bin/env python3
"""Por que mexeu: a investigacao que a mesa faz quando o livro diz "sem causa no dado".

So roda com internet aberta (computador do Douglas). Junta, numa ficha so, o que o
dado sustenta sobre um movimento de um ativo num pregao:

  1. a fita intradia do ativo contra os pares do grupo (pares.py) e o Ibovespa,
     com a mediana hora a hora dos PARES PROXIMOS (os 3 do grupo que mais andam
     junto com o ativo no dia a dia: na construcao, a Cury se compara com a baixa
     renda, nao com Cyrela e EZTec) e a mediana do grupo inteiro;
  2. quanto do movimento e do setor e quanto e so do ativo, e a HORA em que a
     divergencia abriu (abertura, meio do pregao ou leilao de fechamento);
  3. volume contra a media de 20 pregoes e onde o preco fechou na faixa do dia;
  4. documentos na CVM no dia e nos dias em volta (do JSON do ativo);
  5. os outros dias recentes em que o ativo destoou dos pares, e o dia seguinte;
  6. o que falta conferir na web (noticia do horario, setor, eleicao), para a
     sessao buscar e citar ROTULADO como busca web.

    python3 ferramentas/local/porque.py CURY3                       # ultimo pregao
    python3 ferramentas/local/porque.py CURY3 --dia 2026-09-30
    python3 ferramentas/local/porque.py CURY3 --pares DIRR3,TEND3   # pares escolhidos a mao
    python3 ferramentas/local/porque.py PETR4 --intervalo 60m

O caso de teste e a CURY3 de 30/09/2026: a ficha tem de separar a parte setorial
da manha da parte so da Cury a tarde. Nada aqui e opiniao nem regra do livro; a
ficha nao inventa causa. Se o dado nao traz o motivo, a ultima secao diz isso.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from datetime import date, datetime, timedelta, timezone

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(AQUI))
for p in (AQUI, RAIZ):
    if p not in sys.path:
        sys.path.insert(0, p)

import fita as F  # noqa: E402
from livro.http import Cliente  # noqa: E402

LIMIAR = 1.0        # pontos percentuais para chamar de divergencia
DESTOA = 2.5        # pp contra a mediana dos pares para entrar em "dias parecidos"
PROXIMOS = 3        # quantos pares do grupo entram na comparacao fina
CORR_MIN = 0.5      # correlacao minima dos retornos diarios para ser "par proximo"


def correlacao(a: dict, b: dict, n: int = 120) -> float | None:
    comuns = sorted(set(a) & set(b))[-n:]
    if len(comuns) < 30:
        return None
    try:
        return statistics.correlation([a[d] for d in comuns], [b[d] for d in comuns])
    except Exception:
        return None


def pp(x: float | None) -> str:
    return F.pct(x).replace("%", " pp")


def pares_do_grupo(tk: str) -> tuple[list[str], str]:
    try:
        import pares
        lista = [t for t in (pares.pares_de(tk) or []) if t.upper() != tk.upper()]
        g = pares.grupo_de(tk)
        nome = g if isinstance(g, str) else (g or {}).get("nome") if isinstance(g, dict) else ""
        return lista, str(nome or "")
    except Exception:
        return [], ""


def diarios(cli: Cliente, nome: str, ate: date, dias: int = 270) -> dict[date, float]:
    """Variacao diaria (%) por data, pelo fechamento, para os ~6 meses antes de `ate`."""
    s = F.simbolo_yahoo(nome)
    fim = datetime(ate.year, ate.month, ate.day, tzinfo=F.BRT) + timedelta(hours=30)
    res = F.baixar(cli, s, fim - timedelta(days=dias), fim, "1d")
    bs = F.barras(res)
    out: dict[date, float] = {}
    for a, b in zip(bs, bs[1:]):
        if a["fech"]:
            out[b["t"].astimezone(F.BRT).date()] = (b["fech"] / a["fech"] - 1) * 100
    return out


def documentos_cvm(tk: str, dia: date) -> tuple[list[dict], str | None]:
    """Fatos relevantes e comunicados do JSON do ativo entre D-5 e D+1."""
    try:
        import mesa
        d = mesa.baixar(f"ativos/{tk}.json", ttl=0)
    except Exception:
        d = None
    if not d:
        return [], None
    cvm = d.get("cvm") or {}
    docs = []
    for chave, rotulo in (("fatos_relevantes", "FATO RELEVANTE"), ("outros_documentos", "documento")):
        for x in cvm.get(chave) or []:
            try:
                dd = date.fromisoformat(str(x.get("data"))[:10])
            except Exception:
                continue
            if dia - timedelta(days=5) <= dd <= dia + timedelta(days=1):
                docs.append({"data": dd, "rotulo": rotulo, "categoria": x.get("categoria") or "",
                             "tipo": x.get("tipo") or "", "assunto": x.get("assunto") or "", "link": x.get("link") or ""})
    docs.sort(key=lambda z: z["data"], reverse=True)
    return docs, d.get("gerado_em")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ticker")
    ap.add_argument("--dia", help="AAAA-MM-DD (padrao: ultimo pregao)")
    ap.add_argument("--pares", default="", help="lista separada por virgula (padrao: grupo do pares.py)")
    ap.add_argument("--intervalo", default="30m", choices=F.INTERVALOS)
    a = ap.parse_args(argv[1:])
    tk = a.ticker.strip().upper()
    dia = date.fromisoformat(a.dia) if a.dia else None
    if a.pares:
        lista, grupo = [t.strip().upper() for t in a.pares.split(",") if t.strip()], "escolhidos a mao"
    else:
        lista, grupo = pares_do_grupo(tk)
    cli = Cliente()

    # barras de 30m so existem para os ultimos 60 dias: fora disso, cai para 60m e avisa
    intervalo = a.intervalo
    if dia and intervalo != "60m" and (date.today() - dia).days > 55:
        intervalo = "60m"
        print(f"Nota: {dia.isoformat()} esta fora do limite de 60 dias do Yahoo para {a.intervalo}; uso barras de 60m.")
    try:
        ref = F.coletar(cli, tk, dia, intervalo)
    except Exception as e:
        print(f"LACUNA: sem fita de {tk}: {e}")
        return 1
    dia = ref["dia"]
    fitas, lacunas = [], []
    for p in lista:
        try:
            f = F.coletar(cli, p, dia, intervalo)
            if f["dia"] == dia:
                fitas.append(f)
        except Exception as e:
            lacunas.append(f"{p}: {e}")
    try:
        ibov = F.coletar(cli, "IBOV", dia, intervalo)
    except Exception:
        ibov = None

    # series diarias: servem para achar os pares proximos e os dias parecidos
    try:
        d_ref = diarios(cli, tk, dia)
    except Exception:
        d_ref = {}
    d_par: dict[str, dict] = {}
    for f in fitas:
        try:
            d_par[f["nome"]] = diarios(cli, f["nome"], dia)
        except Exception:
            d_par[f["nome"]] = {}
    corr = {n: correlacao(d_ref, m) for n, m in d_par.items()}
    if a.pares:
        proximos = list(fitas)
    else:
        ordem = sorted((f for f in fitas if corr.get(f["nome"]) is not None), key=lambda f: corr[f["nome"]], reverse=True)
        proximos = [f for f in ordem if corr[f["nome"]] >= CORR_MIN][:PROXIMOS] or ordem[:2] or list(fitas)
    nomes_prox = {f["nome"] for f in proximos}

    print(f"POR QUE MEXEU · {tk} · {F.DIAS[dia.weekday()]} {dia.strftime('%d/%m/%Y')}"
          + (" · PREGAO EM ANDAMENTO (parcial)" if ref["em_andamento"] else ""))
    print(f"Fonte da fita: Yahoo Finance, barras de {intervalo}, B3 com atraso de ~15 min. Hora de Brasilia = inicio da barra.")
    for l in lacunas:
        print(f"LACUNA: {l}")
    print()

    # 1. O dia
    print("1. O DIA")
    lin = [[tk, F.pct(ref["var_dia"]), F.num(ref["fechamento"]),
            "-" if ref["posicao_na_faixa"] is None else f"{ref['posicao_na_faixa']:.0f}%",
            "-" if ref["volume_sobre_media20"] is None else F.num(ref["volume_sobre_media20"], 1) + "x"]]
    for f in fitas:
        lin.append([f["nome"] + (" *" if f["nome"] in nomes_prox and not a.pares else ""), F.pct(f["var_dia"]), F.num(f["fechamento"]),
                    "-" if f["posicao_na_faixa"] is None else f"{f['posicao_na_faixa']:.0f}%",
                    "-" if f["volume_sobre_media20"] is None else F.num(f["volume_sobre_media20"], 1) + "x"])
    med_grupo = statistics.median([f["var_dia"] for f in fitas]) if fitas else None
    med_dia = statistics.median([f["var_dia"] for f in proximos]) if proximos else None
    if med_dia is not None and not a.pares and len(proximos) < len(fitas):
        lin.append([f"mediana dos {len(proximos)} pares proximos *", F.pct(med_dia), "", "", ""])
    if med_grupo is not None:
        lin.append([f"mediana dos {len(fitas)} pares", F.pct(med_grupo), "", "", ""])
    if ibov:
        lin.append(["IBOV", F.pct(ibov["var_dia"]), F.num(ibov["fechamento"], 0), "", ""])
    print(F.tabela(["ativo", "dia", "ultimo", "faixa", "vol/media"], lin))
    print("faixa: 0% = fechou na minima do dia, 100% = na maxima. vol/media: volume do dia sobre a media de 20 pregoes.")
    if a.pares:
        print("Pares escolhidos a mao.")
    elif fitas:
        print(f"Pares: grupo {grupo} do pares.py. * = pares proximos, os que mais andam junto com {tk} "
              "(correlacao dos retornos diarios em 6 meses: "
              + ", ".join(f"{f['nome']} {F.num(corr[f['nome']], 2)}" for f in proximos if corr.get(f["nome"]) is not None) + ").")
    print()

    # 2. Setor ou ativo, e a hora
    horas = [b["hora"] for b in ref["fita"]]
    m_ref = {b["hora"]: b["var"] for b in ref["fita"]}
    difs: list[tuple[str, float, float]] = []
    if fitas:
        mapas = [{b["hora"]: b["var"] for b in f["fita"]} for f in proximos]
        mapas_g = [{b["hora"]: b["var"] for b in f["fita"]} for f in fitas]
        grupo_h = {}
        for h in horas:
            vs = [m[h] for m in mapas if h in m]
            vg = [m[h] for m in mapas_g if h in m]
            if vg:
                grupo_h[h] = statistics.median(vg)
            if vs:
                med = statistics.median(vs)
                difs.append((h, med, m_ref[h] - med))
        rot_prox = "pares" if a.pares or len(proximos) == len(fitas) else "pares proximos"
        print(f"2. SETOR OU ATIVO, HORA A HORA (diferenca = {tk} menos a mediana dos {rot_prox})")
        ab_p = [f["var_abertura"] for f in proximos if f["var_abertura"] is not None]
        ab_g = [f["var_abertura"] for f in fitas if f["var_abertura"] is not None]
        print(F.tabela(["hora", tk, rot_prox, "diferenca", "grupo todo"],
                       [["abertura", F.pct(ref["var_abertura"]), F.pct(statistics.median(ab_p)) if ab_p else "-", "",
                         F.pct(statistics.median(ab_g)) if ab_g else "-"]]
                       + [[h, F.pct(m_ref[h]), F.pct(med), pp(d), F.pct(grupo_h.get(h))] for h, med, d in difs]
                       + [["fecham." if not ref["em_andamento"] else "parcial", F.pct(ref["var_dia"]), F.pct(med_dia),
                           pp(ref["var_dia"] - med_dia), F.pct(med_grupo)]]))
        print()

    # 3. CVM
    docs, coletado = documentos_cvm(tk, dia)
    print("3. DOCUMENTOS NA CVM (D-5 a D+1)")
    if coletado is None:
        print(f"LACUNA: {tk} nao esta no branch dados nem em dados_local/. Rode: python3 ferramentas/local/coletar.py {tk}")
    else:
        print(f"JSON do ativo coletado em {coletado}. Documento protocolado depois disso nao aparece aqui"
              f" (para atualizar: python3 ferramentas/local/coletar.py {tk}).")
        if not docs:
            print("Nenhum documento da companhia na CVM entre D-5 e D+1.")
        for x in docs:
            marca = "NO DIA" if x["data"] == dia else x["data"].strftime("%d/%m")
            desc = " | ".join(t for t in (x["categoria"], x["tipo"], x["assunto"]) if t)
            print(f"- [{marca}] {x['rotulo']}: {desc[:170]}")
            if x["data"] == dia and x["link"]:
                print(f"  {x['link']}")
    print()

    # 4. Dias parecidos
    lim_txt = f"{DESTOA:.1f}".replace(".", ",")
    print(f"4. OUTROS DIAS EM QUE {tk} DESTOOU DOS PARES" + ("" if a.pares or len(proximos) == len(fitas) else " PROXIMOS")
          + f" (6 meses, {lim_txt} pp ou mais contra a mediana)")
    try:
        series_p = [d_par[f["nome"]] for f in proximos]
        if not d_ref or not series_p:
            raise RuntimeError("serie diaria indisponivel")
        datas = sorted(d_ref)
        linhas = []
        for i, dt_ in enumerate(datas):
            vs = [m[dt_] for m in series_p if dt_ in m]
            if len(vs) < max(1, len(series_p) // 2) or dt_ == dia:
                continue
            dif = d_ref[dt_] - statistics.median(vs)
            if abs(dif) >= DESTOA:
                seg = datas[i + 1] if i + 1 < len(datas) else None
                vs2 = [m[seg] for m in series_p if seg and seg in m]
                dif2 = (d_ref[seg] - statistics.median(vs2)) if seg and vs2 else None
                linhas.append([dt_.strftime("%d/%m/%Y"), F.pct(d_ref[dt_]), F.pct(statistics.median(vs)), pp(dif),
                               "-" if dif2 is None else pp(dif2)])
        if linhas:
            print(F.tabela(["data", tk, "mediana pares", "diferenca", "dif. no dia seguinte"], linhas[-8:]))
        else:
            print("Nenhum outro dia assim na janela.")
    except Exception as e:
        print(f"LACUNA: sem serie diaria para comparar ({e})")
    print()

    # 5. O que o dado sustenta
    print("5. O QUE O DADO SUSTENTA (e so isto)")
    if med_dia is None:
        print(f"- Sem pares com fita no dia: nao da para separar setor de ativo. {tk} {F.pct(ref['var_dia'])}.")
    else:
        final = ref["var_dia"] - med_dia
        quem = "dos pares" if a.pares or len(proximos) == len(fitas) else "dos pares proximos (" + ", ".join(f["nome"] for f in proximos) + ")"
        print(f"- Parte do setor: a mediana {quem} fez {F.pct(med_dia)}. Parte so de {tk}: {pp(final)} (dia {F.pct(ref['var_dia'])}).")
        if med_grupo is not None and abs(med_grupo - med_dia) >= LIMIAR:
            print(f"- O grupo inteiro fez {F.pct(med_grupo)}: o setor nao andou junto no dia, entao a comparacao que vale e com os pares proximos.")
        if abs(final) < LIMIAR:
            print(f"- {tk} andou com os pares: o movimento e do setor, nao da companhia.")
        else:
            abre = None
            for h, _med, d in reversed(difs):
                if abs(d) >= LIMIAR and (d > 0) == (final > 0):
                    abre = h
                else:
                    break
            juntos = [h for h, _m, d in difs if abs(d) < LIMIAR]
            if abre is None:
                print("- A diferenca so aparece no fechamento (leilao): ate a ultima barra o ativo andava com os pares.")
            elif difs and abre == difs[0][0]:
                print("- A diferenca vem desde a primeira barra do pregao: procure o que saiu ANTES da abertura ou na vespera a noite.")
            else:
                pior = min((m for _h, m, _d in difs if _h < abre), default=None) if final < 0 else max((m for _h, m, _d in difs if _h < abre), default=None)
                print(f"- Antes das {abre} o ativo andou com os pares (diferenca menor que {LIMIAR:.0f} pp"
                      + (f"; os pares chegaram a {F.pct(pior)}" if pior is not None else "") + "): essa parte e do setor.")
                print(f"- A partir das {abre} a diferenca abriu e nao fechou mais: essa parte e so de {tk}.")
                print(f"  Procure o que saiu por volta das {abre}: e a hora que a noticia, se existir, tem de ter.")
    if ref["volume_sobre_media20"] is not None:
        v = ref["volume_sobre_media20"]
        rot = "acima do normal" if v >= 1.5 else "normal" if v >= 0.7 else "fraco"
        print(f"- Volume {F.num(v, 1)}x a media de 20 pregoes ({rot})."
              + (" Movimento com volume fraco pesa menos." if v < 0.7 else ""))
    if ref["posicao_na_faixa"] is not None and not ref["em_andamento"]:
        q = ref["posicao_na_faixa"]
        if q <= 15:
            print(f"- Fechou a {q:.0f}% da faixa do dia, colado na minima: a venda foi ate o fim, sem recompra.")
        elif q >= 85:
            print(f"- Fechou a {q:.0f}% da faixa do dia, colado na maxima.")
    no_dia = [x for x in docs if x["data"] == dia]
    if coletado is not None:
        if no_dia:
            print(f"- Ha {len(no_dia)} documento(s) da companhia na CVM no dia (secao 3): leia antes de ligar ao preco, e diga o que o documento e.")
        else:
            print("- Sem documento da companhia na CVM no dia: a causa, se houver, nao e fato da empresa registrado.")
    print()
    print("6. A CONFERIR NA WEB (citar com veiculo, data e HORA; rotular \"busca web\")")
    print(f"- Noticia de {tk} ou do setor no horario em que a divergencia abriu.")
    print("- Relatorio de casa (rebaixamento, mudanca de preco-alvo) e bloco/leilao no dia.")
    print("- Evento do dia no calendario do livro (config/calendario.yaml): macro, eleicao, FGTS/Caixa, previa operacional.")
    print("- Em periodo eleitoral: pesquisa divulgada no dia, com a hora da divulgacao.")
    print("Se a busca nao achar nada datado do dia, a resposta e \"sem causa identificada\", com o que o dado mostra acima.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
