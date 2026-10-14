"""
Estudo 14/10/2026. Pedido do Douglas: "mais um pregao que o robo toma prejuizo com mini-dolar, ajuste a estrategia... Se esforce".
O pregao de 14/10 NAO entra em conta nenhuma (um dia de perda dentro da distribuicao nao e erro da regra). Tres perguntas, com a
hipotese escrita antes; descoberta = 10/2021-12/2024; so candidata abre 2025 (uma vez); 2026 nao escolhe parametro.

A. LIMIAR DO DADO RELATIVO A VOLATILIDADE (FILA item 16, nunca testado). Hipotese: 3 pontos fixos sao ruido num dia agitado e
   reacao de verdade num dia calmo; medir a reacao em unidades da amplitude tipica do dolar (mediana da amplitude diaria dos 20
   pregoes anteriores, conhecida na abertura) separaria melhor o exagero. O multiplicador k NAO e escolhido pelo resultado: e o
   que da o mesmo numero de sinais que os 3 pontos na descoberta (casamento de contagem); vizinhos 0,8k e 1,25k so para ver se e
   plato. Candidata: lab.candidata E resultado por pregao acima da regra que opera.
B. CONFLITO ENTRE AS REGRAS. De 02/11/2026 a 08/03/2027 (sem horario de verao nos EUA) o dado sai as 10h30 de Brasilia e a
   entrada e as 10h32. O nivel e reacao opera desde as 9h15 (o climax tambem). Se uma delas estiver posicionada as 10h32 ou ja
   tiver gasto as 3 perdas do dia (a trava vale para o dia inteiro), a unica regra aprovada nao entra. Quanto isso custa nos
   dias de inverno americano de 2021-2025 (descricao, nao escolha de parametro)?
C. CUSTO DE MANTER AS REGRAS REPROVADAS OPERANDO, com as travas do dia (3 perdas, R$ 1.000): resultado por pregao do nivel e
   reacao e do climax, 2021-2025.
Saida: quant/saida/pesquisa5/montecarlo/ajuste_2026-10-14.json
"""
import importlib.util
import json
import os
import sys

import numpy as np
import pandas as pd

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)
from quant.daytrade import estrategias_hist as eh  # noqa: E402
from quant.daytrade import historico as h  # noqa: E402
from quant.daytrade import robo_fluxo as rf  # noqa: E402
from quant.pesquisa import lab  # noqa: E402
from quant.saida.pesquisa5.calendario import regras  # noqa: E402

FAMILIA = "dado_limiar_relativo"
SAIDA = dict(stop=40.0, alvo=None, tempo=120)
PASTA = os.path.join(lab.PASTA, "montecarlo")


def amplitude_tipica(m, janela=20):
    """Por barra: mediana da amplitude diaria (maxima - minima) dos `janela` pregoes ANTERIORES (conhecida na abertura)."""
    d = lab.dia(m)
    amp = m.groupby(d).agg(h=("h", "max"), l=("l", "min"))
    tip = (amp.h - amp.l).rolling(janela, min_periods=10).median().shift(1)
    return pd.Series(d).map(tip).to_numpy(dtype=float)


def limiar_relativo(m, k):
    """A regra congelada (2 minutos, contra a reacao), com gatilho |reacao| > k x amplitude tipica em vez de 3 pontos."""
    verao = regras._verao_eua(m)
    hm = lab.hm(m)
    alvo = np.where(verao, "09:31", "10:31")
    mv = regras._mov(m, 2)
    rel = np.abs(mv) / amplitude_tipica(m)
    return np.nan_to_num(np.where((hm == alvo) & (rel > k), -np.sign(mv), 0.0)), rel, (hm == alvo)


def k_por_contagem(m):
    """O k que da, na descoberta, o mesmo numero de sinais que o gatilho de 3 pontos (nao olha resultado)."""
    s3 = regras.reverte_dado_ny(m, r=2, thr=3.0)
    _s, rel, decide = limiar_relativo(m, 0.0)
    n3 = int((s3 != 0).sum())
    vals = np.sort(rel[decide & ~np.isnan(rel)])[::-1]
    return float(vals[n3]) if n3 < len(vals) else float(vals[-1]), n3


def pergunta_a():
    m = lab.carregar("WDO", "descoberta")
    pregoes = len(set(lab.dia(m)))
    base = lab.avaliar(m, regras.reverte_dado_ny(m, r=2, thr=3.0), nome="dado gatilho 3 (a regra que opera) [descoberta]", familia=FAMILIA,
                       registrar=False, **SAIDA)
    k0, n3 = k_por_contagem(m)
    out = {"k_por_contagem": round(k0, 4), "sinais_do_gatilho_3": n3,
           "base": {k: base.get(k) for k in ("n", "acerto", "rs_por_negocio", "t", "total", "semestres_positivos")}}
    out["base"]["rs_por_pregao"] = round(base["total"] / pregoes, 1)
    print(f"A. base (3 pts): n {base['n']} R$/neg {base['rs_por_negocio']:+.1f} t {base['t']:.2f} R$/pregao {out['base']['rs_por_pregao']:+.1f} sem {base['semestres_positivos']}")
    print(f"   k por contagem = {k0:.4f} (reacao > {k0:.3f} x amplitude tipica)")
    cands = []
    for nome, k in (("k", k0), ("0,8k", 0.8 * k0), ("1,25k", 1.25 * k0)):
        s, _rel, _d = limiar_relativo(m, k)
        r = lab.avaliar(m, s, nome=f"dado limiar relativo {nome} ({k:.4f}) [descoberta]", familia=FAMILIA, **SAIDA)
        x = {k_: r.get(k_) for k_ in ("n", "acerto", "rs_por_negocio", "t", "total", "semestres_positivos", "por_ano")}
        x["rs_por_pregao"] = round(r["total"] / pregoes, 1) if r.get("n") else 0.0
        x["candidata"] = bool(r.get("n") and lab.candidata(r) and x["rs_por_pregao"] > out["base"]["rs_por_pregao"])
        out[nome] = x
        print(f"   {nome:6s} n {r['n']} R$/neg {r['rs_por_negocio']:+.1f} t {r['t']:.2f} R$/pregao {x['rs_por_pregao']:+.1f} sem {r['semestres_positivos']} candidata {x['candidata']}")
        if x["candidata"] and nome == "k":
            cands.append((nome, k))
    if cands:
        v = lab.carregar("WDO", "validacao")
        pv = len(set(lab.dia(v)))
        b25 = lab.avaliar(v, regras.reverte_dado_ny(v, r=2, thr=3.0), nome="dado gatilho 3 [validacao]", familia=FAMILIA, registrar=False, **SAIDA)
        for nome, k in cands:
            s, _rel, _d = limiar_relativo(v, k)
            r = lab.avaliar(v, s, nome=f"dado limiar relativo {nome} ({k:.4f}) [validacao]", familia=FAMILIA, **SAIDA)
            out["validacao_2025"] = {"base_rs_por_pregao": round(b25["total"] / pv, 1), "base_rs_por_negocio": b25["rs_por_negocio"], "base_n": b25["n"],
                                     "rs_por_pregao": round(r["total"] / pv, 1) if r.get("n") else 0.0, "rs_por_negocio": r.get("rs_por_negocio"), "n": r.get("n"),
                                     "t": r.get("t")}
            print(f"   VALIDACAO 2025 {nome}: {out['validacao_2025']}")
    return out


def _sem_ajuste(m):
    x = m.copy()
    desl = (x["nivel"] - x["c"]).to_numpy()
    for k in ("o", "h", "l", "c"):
        x[k] = x[k].to_numpy() + desl
    return x[["o", "h", "l", "c", "n", "v"]]


def _climax(m):
    spec = importlib.util.spec_from_file_location("cal", os.path.join(RAIZ, "quant", "estudos", "2026-10-08_calibrar_climax.py"))
    cal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cal)
    cal.m1 = m
    cal.o, cal.hi, cal.lo, cal.c, cal.v = (m[k].to_numpy() for k in ("o", "h", "l", "c", "v"))
    cal.hm = np.array(m.index.strftime("%H:%M"))
    cal.dia = np.array(m.index.date)
    cal.vrel = (m.v / m.groupby(cal.dia).v.transform(lambda s: s.shift(1).rolling(30, min_periods=3).mean())).to_numpy()
    cal.dias = sorted(set(cal.dia))
    cal.fim_do_dia = np.r_[cal.dia[1:] != cal.dia[:-1], True]
    c = rf.CLIMAX
    return cal.medir(cal.negocios(c["tranco"], c["vol"], c["alvo_devolve"], c["stop_fixo"], c["tempo_max"], ini="09:15", ult="18:10", zerar="18:24"))


def perguntas_b_c():
    m = pd.concat([lab.carregar("WDO", "descoberta"), lab.carregar("WDO", "validacao")])
    m = m[~m.index.duplicated()].sort_index()
    pregoes = sorted(set(lab.dia(m)))
    # o dado (a regra que opera), por dia
    t = lab.medir(lab.negocios(m, regras.reverte_dado_ny(m, r=2, thr=3.0), 40.0, None, 120))
    dado = {pd.Timestamp(d).date(): (hh, r) for d, hh, r in zip(t.dia, t.hora, t.res)}
    # nivel e reacao com as travas do dia do robo
    reg = h.RegrasDoDia(inicio="09:15", ultima_entrada="18:10", zerar="18:24", contratos=2, meta_rs=1000.0, perda_maxima_rs=1000.0,
                        perdas_para_parar=3, max_operacoes=12, espera_min=2)
    neg = h.simular(_sem_ajuste(m), eh.NivelReacao(**rf.NIVEIS), reg, h.Custos())
    niv = pd.DataFrame([{"dia": x.dia, "ent": pd.Timestamp(x.entrada_hora).strftime("%H:%M"), "sai": pd.Timestamp(x.saida_hora).strftime("%H:%M"),
                         "res": x.resultado} for x in neg])
    clx = _climax(m)
    clx["ent"] = clx.hora
    clx["sai"] = [(pd.Timestamp(f"2000-01-01 {x}") + pd.Timedelta(minutes=21)).strftime("%H:%M") for x in clx.hora]
    # C. custo por pregao
    por_dia_niv = niv.groupby("dia").res.sum().reindex(pregoes, fill_value=0.0)
    perdas_dia = niv[niv.res < 0].groupby("dia").size().reindex(pregoes, fill_value=0)
    c = {"nivel": {"rs_por_pregao": round(float(por_dia_niv.mean()), 1), "negocios_por_pregao": round(len(niv) / len(pregoes), 2),
                   "rs_por_negocio": round(float(niv.res.mean()), 1), "dias_com_3_perdas_pct": round(float((perdas_dia >= 3).mean() * 100), 1),
                   "pregoes_positivos_pct": round(float((por_dia_niv > 0).mean() * 100), 1), "pregoes": len(pregoes)},
         "climax": {"rs_por_pregao": round(float(clx.res.sum() / len(pregoes)), 1), "negocios_por_pregao": round(len(clx) / len(pregoes), 2),
                    "rs_por_negocio": round(float(clx.res.mean()), 1)},
         "dado": {"rs_por_pregao": round(float(t.res.sum() / len(pregoes)), 1), "rs_por_negocio": round(float(t.res.mean()), 1), "n": int(len(t))}}
    print(f"C. por pregao (2021-2025, {len(pregoes)} pregoes): nivel R$ {c['nivel']['rs_por_pregao']:+.1f} ({c['nivel']['negocios_por_pregao']} neg, "
          f"{c['nivel']['dias_com_3_perdas_pct']}% dos dias para nas 3 perdas, {c['nivel']['pregoes_positivos_pct']}% positivos); "
          f"climax R$ {c['climax']['rs_por_pregao']:+.1f}; dado R$ {c['dado']['rs_por_pregao']:+.1f}")
    # B. conflito nos dias de inverno americano (dado as 10h30; entrada 10h32); reserva de 22 minutos antes do dado (10h08)
    verao = {d: v for d, v in zip(lab.dia(m), regras._verao_eua(m))}
    inverno = [d for d in pregoes if not verao[d]]
    bloqueados, motivos = [], {"posicao do nivel": 0, "posicao do climax": 0, "trava de 3 perdas ou R$ 1.000": 0}
    for d in inverno:
        if d not in dado:
            continue
        n_d, c_d = niv[niv.dia == d], clx[clx.dia == d]
        antes = pd.concat([n_d[n_d.sai < "10:32"][["res"]], c_d[c_d.sai < "10:32"][["res"]]])
        motivo = None
        if len(antes) and ((antes.res < 0).sum() >= 3 or antes.res.sum() <= -1000):
            motivo = "trava de 3 perdas ou R$ 1.000"
        elif ((n_d.ent < "10:08") & (n_d.sai >= "10:32")).any():
            motivo = "posicao do nivel"
        elif ((c_d.ent < "10:08") & (c_d.sai >= "10:32")).any():
            motivo = "posicao do climax"
        if motivo:
            motivos[motivo] += 1
            bloqueados.append(dado[d][1])
    dias_dado_inverno = sum(1 for d in inverno if d in dado)
    b = {"dias_de_inverno": len(inverno), "dias_com_sinal_do_dado": dias_dado_inverno, "bloqueados": len(bloqueados), "motivos": motivos,
         "resultado_perdido_rs": round(float(np.sum(bloqueados)), 0), "media_do_bloqueado": round(float(np.mean(bloqueados)), 1) if bloqueados else None,
         "rs_por_pregao_de_inverno": round(float(np.sum(bloqueados)) / max(len(inverno), 1), 1)}
    print(f"B. inverno americano: {dias_dado_inverno} sinais do dado em {len(inverno)} pregoes; {len(bloqueados)} bloqueados pelas outras regras "
          f"({motivos}); o dado deixaria de ganhar R$ {b['resultado_perdido_rs']:+.0f} (media {b['media_do_bloqueado']})")
    return b, c


def main():
    os.makedirs(PASTA, exist_ok=True)
    a = pergunta_a()
    b, c = perguntas_b_c()
    out = {"gerado": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), "A_limiar_relativo": a, "B_conflito_inverno": b, "C_custo_reprovadas": c}
    with open(os.path.join(PASTA, "ajuste_2026-10-14.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    print("gravado", os.path.join(PASTA, "ajuste_2026-10-14.json"))


if __name__ == "__main__":
    main()
