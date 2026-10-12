"""
Tres anomalias da literatura testadas com o que temos (barras de 1 minuto do BOVA11, 10/2021 em diante):

  A. OVERNIGHT x INTRADIA (Lou, Polk e Skouras, JFE 2019): o retorno do fechamento (16h54, antes do leilao) ate a abertura
     do dia seguinte (10h00) contra o retorno de dentro do pregao. Regra R1 pre-registrada: compra a mercado na barra das
     16h54 e vende na abertura seguinte; custo 0,025% por lado (emolumentos de day trade... nao: aqui dorme posicionado, entao
     0,030% por lado, swing) e 1 tick (R$ 0,01) contra em cada ponta; sem IR.
  B. DIAS DE ANUNCIO MACRO (Savor e Wilson, JFQA 2013): retorno do pregao (10h00 -> 16h54) do BOVA11 nos dias com dado
     americano das 8h30 (calendario_eua: payroll, CPI, PPI, outros do BLS, pedidos de auxilio) contra os demais dias.
  C. DERIVA PRE-FOMC (Lucca e Moench, JF 2015): retorno do BOVA11 do fechamento da vespera ate as 14h59 do dia do FOMC
     (a decisao sai as 15h no horario de verao dos EUA, 16h fora), contra o mesmo trecho nos outros dias; datas em
     quant/saida/pesquisa5/dolar_dias/dados/fomc_datas.csv.

PRE-REGISTRO (12/10/2026): descritivo na DESCOBERTA (10/2021-12/2024); a validacao (2025) so e aberta para a regra R1 se ela
passar `lab.candidata` na descoberta (t >= 3, 200+ negocios, 5 de 7 semestres). B e C sao estudos de evento (sem regra),
registrados como tal. 2026 nao e aberto. Cada bloco e UMA tentativa (3 no total) no registro.
Rodar: cd ~/Desktop/quant-b3 && PYTHONPATH=. .venv/bin/python -W ignore quant/estudos/2026-10-12_overnight_e_anuncios.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.getcwd())
from quant.dados import calendario_eua as ce  # noqa: E402
from quant.pesquisa import lab  # noqa: E402
from quant.saida.pesquisa5.calendario import regras  # noqa: E402

PASTA = os.path.join(lab.PASTA, "montecarlo")
TAXA_LADO = 0.00030           # swing (dorme posicionado): emolumentos + liquidacao por lado
TICK = 0.01
ARQ_FOMC = os.path.join(lab.PASTA, "dolar_dias", "dados", "fomc_datas.csv")


def _t(x):
    x = np.asarray(x, dtype=float)
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 3 and x.std(ddof=1) > 0 else float("nan")


def diario(m):
    """Por pregao: abertura (primeira barra >= 10:00), fechamento das 16:54 (ultima barra < 16:55), maxima/minima do dia."""
    h = lab.hm(m)
    d = pd.Series(lab.dia(m), index=m.index)
    x = m[(h >= "10:00") & (h < "16:55")]
    g = x.groupby(d.loc[x.index].values)
    f = pd.DataFrame({"abre": g["o"].first(), "fecha": g["c"].last(), "n": g.size(), "c1459": x[lab.hm(x) < "15:00"].groupby(d.loc[x[lab.hm(x) < "15:00"].index].values)["c"].last()})
    f.index = pd.to_datetime(f.index)
    f = f[f["n"] >= 300]                                   # pregao inteiro (sem meia sessao)
    f["overnight"] = f["abre"] / f["fecha"].shift(1) - 1.0
    f["intradia"] = f["fecha"] / f["abre"] - 1.0
    f["ate_1459"] = f["c1459"] / f["fecha"].shift(1) - 1.0
    return f


def bloco_a(f, registrar=True):
    on, it = f["overnight"].dropna(), f["intradia"].dropna()
    custo = 2 * TAXA_LADO + 2 * TICK / float(f["fecha"].median())
    liq = on - custo
    por_ano = {int(k): {"n": int(len(v)), "overnight_bps": round(float(v.mean() * 1e4), 2), "intradia_bps": round(float(f.loc[v.index, "intradia"].mean() * 1e4), 2)}
               for k, v in on.groupby(on.index.year)}
    sem = on.groupby(on.index.year.astype(str) + "S" + ((on.index.month > 6) + 1).astype(str)).mean()
    r = {"n": int(len(on)), "overnight_bps_media": round(float(on.mean() * 1e4), 2), "overnight_t": round(_t(on), 2),
         "intradia_bps_media": round(float(it.mean() * 1e4), 2), "intradia_t": round(_t(it), 2),
         "custo_ida_volta_bps": round(custo * 1e4, 2), "R1_liquido_bps": round(float(liq.mean() * 1e4), 2), "R1_t": round(_t(liq), 2),
         "R1_semestres_positivos": f"{int((sem - custo > 0).sum())} de {len(sem)}", "por_ano": por_ano,
         "R1_rs_por_negocio_com_20k": round(float(liq.mean() * 20_000), 2)}
    r["candidata"] = bool(liq.mean() > 0 and _t(liq) >= 3 and len(liq) >= 200 and int((sem - custo > 0).sum()) >= 5)
    if registrar:
        lab.evento.__globals__  # noqa (so para deixar claro que o registro e o do lab)
        with open(lab.REGISTRO, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"tipo": "simulacao", "nome": "R1 overnight BOVA11 (compra 16h54, vende abertura)", "familia": "anomalias_literatura",
                                 "n": r["n"], "rs_por_negocio": r["R1_rs_por_negocio_com_20k"], "t": r["R1_t"], "semestres_positivos": r["R1_semestres_positivos"],
                                 "de": str(on.index.min().date()), "ate": str(on.index.max().date()), "quando": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")},
                                ensure_ascii=False) + "\n")
    return r


def bloco_b(f, mapa, registrar=True):
    tipo = pd.Series([ce.tipo_do_dia(d.date(), mapa) for d in f.index], index=f.index)
    it = f["intradia"].dropna()
    fora = {}
    for k, g in it.groupby(tipo.loc[it.index]):
        fora[k] = {"n": int(len(g)), "media_bps": round(float(g.mean() * 1e4), 2), "t": round(_t(g), 2), "desvio_bps": round(float(g.std() * 1e4), 1)}
    com = it[tipo.loc[it.index] != "nenhum"]
    sem = it[tipo.loc[it.index] == "nenhum"]
    fora["com_dado_vs_sem"] = {"com_n": int(len(com)), "com_bps": round(float(com.mean() * 1e4), 2), "sem_n": int(len(sem)), "sem_bps": round(float(sem.mean() * 1e4), 2),
                               "diferenca_bps": round(float((com.mean() - sem.mean()) * 1e4), 2),
                               "t_diferenca": round(float((com.mean() - sem.mean()) / np.sqrt(com.var(ddof=1) / len(com) + sem.var(ddof=1) / len(sem))), 2)}
    if registrar:
        with open(lab.REGISTRO, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"tipo": "evento", "nome": "BOVA11 intradia em dia de dado americano 8h30 x demais", "familia": "anomalias_literatura",
                                 "tabela": fora["com_dado_vs_sem"], "quando": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False) + "\n")
    return fora


def bloco_c(f, registrar=True):
    try:
        fomc = pd.read_csv(ARQ_FOMC)
        col = next(c for c in fomc.columns if "dat" in c.lower() or "dia" in c.lower())
        datas = set(pd.to_datetime(fomc[col]).dt.normalize())
    except Exception as e:                                        # sem o arquivo nao ha bloco C
        return {"erro": f"{type(e).__name__}: {e}"}
    r = f["ate_1459"].dropna()
    e_fomc = pd.Series([d in datas for d in r.index], index=r.index)
    a, b = r[e_fomc], r[~e_fomc]
    fora = {"fomc_n": int(len(a)), "fomc_bps": round(float(a.mean() * 1e4), 2), "fomc_t": round(_t(a), 2),
            "outros_n": int(len(b)), "outros_bps": round(float(b.mean() * 1e4), 2),
            "diferenca_bps": round(float((a.mean() - b.mean()) * 1e4), 2) if len(a) else None,
            "fomc_positivos": f"{int((a > 0).sum())} de {len(a)}"}
    if registrar:
        with open(lab.REGISTRO, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"tipo": "evento", "nome": "BOVA11 deriva pre-FOMC (fech. vespera -> 14h59)", "familia": "anomalias_literatura",
                                 "tabela": fora, "quando": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False) + "\n")
    return fora


def main():
    os.makedirs(PASTA, exist_ok=True)
    mapa = ce.tipos_por_dia()
    m = lab.carregar("BOVA11", "descoberta")
    f = diario(m)
    fora = {"descoberta": {"pregoes": int(len(f)), "A_overnight": bloco_a(f), "B_anuncios": bloco_b(f, mapa), "C_pre_fomc": bloco_c(f)}}
    print(json.dumps(fora, ensure_ascii=False, indent=1))
    if fora["descoberta"]["A_overnight"]["candidata"]:
        mv = lab.carregar("BOVA11", "validacao")
        fv = diario(mv)
        fora["validacao"] = {"pregoes": int(len(fv)), "A_overnight": bloco_a(fv, registrar=False)}
        print("validacao:", json.dumps(fora["validacao"], ensure_ascii=False, indent=1))
    else:
        fora["validacao"] = "nao aberta: R1 nao foi candidata na descoberta"
    with open(os.path.join(PASTA, "overnight_e_anuncios.json"), "w", encoding="utf-8") as fh:
        json.dump(fora, fh, ensure_ascii=False, indent=1)
    print("gravado em", os.path.join(PASTA, "overnight_e_anuncios.json"))


if __name__ == "__main__":
    main()
