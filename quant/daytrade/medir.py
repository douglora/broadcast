"""
Mede o que a fita dizia em cada entrada do robo e o resultado que a entrada teve.

Junta, de todos os pregoes em quant/saida/daytrade/<data>/, as entradas gravadas (sinais_<setup>.jsonl, com as
medidas da fita) e as saidas (estado_<setup>.json), pela hora da entrada, e compara:
  - entradas que a fita CONFIRMOU contra as que nao confirmou;
  - por nome do nivel; por hora do dia.
Com poucos negocios isso nao prova nada: a tabela mostra o numero de negocios de cada linha para lembrar disso.

Uso: python -m quant.daytrade.medir [--setup niveis]
"""
import argparse
import glob
import json
import os

from quant.comum import ler_json
from quant.daytrade.robo import DIR_DT


def negocios(setup="niveis", pasta=DIR_DT):
    fora = []
    for dia in sorted(glob.glob(os.path.join(pasta, "20??-??-??"))):
        est = ler_json(os.path.join(dia, f"estado_{setup}.json"), padrao=None) or {}
        res = {}
        for o in est.get("operacoes") or []:                    # parciais e saidas, somadas por negocio (hora da entrada)
            k = (o.get("ativo"), o.get("hora_entrada"))
            r = res.setdefault(k, {"resultado": 0.0, "saida": None})
            r["resultado"] += float(o.get("resultado") or 0.0)
            if o.get("tipo") == "saida":
                r["saida"] = o.get("motivo")
        arq = os.path.join(dia, "sinais.jsonl" if setup == "fluxo" else f"sinais_{setup}.jsonl")
        try:
            linhas = [json.loads(x) for x in open(arq, encoding="utf-8") if x.strip()]
        except OSError:
            linhas = []
        for ev in linhas:
            r = res.get((ev.get("ativo"), ev.get("hora")))
            if r is None or r["saida"] is None:
                continue                                         # entrada ainda aberta, ou de outro setup
            fita = (ev.get("medidas") or {}).get("fita") or {}
            fora.append({"dia": os.path.basename(dia), "hora": ev.get("hora"), "lado": ev.get("lado"), "nivel": ev.get("nome_nivel"),
                         "resultado": r["resultado"], "saida": r["saida"], "confirmou": fita.get("confirmou"),
                         "favor": fita.get("fracao_a_favor"), "testes": fita.get("testes_do_nivel")})
    return fora


def _linha(nome, lista):
    if not lista:
        return f"{nome:<34} sem negócios"
    r = [x["resultado"] for x in lista]
    ganhos = sum(1 for v in r if v > 0)
    return (f"{nome:<34} {len(r):>4} negócios | ganhou {ganhos:>3} ({ganhos / len(r) * 100:>3.0f}%) | por negócio R$ {sum(r) / len(r):>8.2f} "
            f"| total R$ {sum(r):>9.2f}")


def relatorio(setup="niveis", pasta=DIR_DT):
    n = negocios(setup, pasta)
    linhas = [f"Setup {setup}: {len(n)} negócios fechados em {len({x['dia'] for x in n})} pregão(ões).", _linha("todos", n),
              _linha("fita CONFIRMOU a entrada", [x for x in n if x["confirmou"] is True]),
              _linha("fita NÃO confirmou", [x for x in n if x["confirmou"] is False]),
              _linha("sem leitura da fita", [x for x in n if x["confirmou"] is None])]
    for nome in sorted({x["nivel"] or "?" for x in n}):
        linhas.append(_linha("nível: " + nome, [x for x in n if (x["nivel"] or "?") == nome]))
    for h in sorted({(x["hora"] or "??")[:2] for x in n}):
        linhas.append(_linha(f"entrada das {h}h", [x for x in n if (x["hora"] or "??")[:2] == h]))
    if len(n) < 100:
        linhas.append("ATENÇÃO: com menos de 100 negócios estas diferenças ainda são acaso.")
    return "\n".join(linhas)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Resultado das entradas do robo contra a leitura da fita")
    ap.add_argument("--setup", default="niveis")
    print(relatorio(ap.parse_args().setup))
