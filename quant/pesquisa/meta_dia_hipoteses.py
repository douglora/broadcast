"""Hipoteses 16 e 17 da FILA (pre-registradas em 11/10/2026 ANTES de rodar). SO a descoberta (10/2021 a 12/2024, 805 pregoes). Nada aqui opera.
Cada configuracao rodada vai para `quant/pesquisa/meta_dia/tentativas.jsonl`.
Uso: PYTHONPATH=. .venv/bin/python -W ignore -m quant.pesquisa.meta_dia_hipoteses"""
import json
import os
import time

from quant.daytrade.historico import Custos, RegrasDoDia
from quant.pesquisa import lab
from quant.pesquisa import meta_dia as md

TENTATIVAS = os.path.join(md.PASTA_SAIDA, "tentativas.jsonl")


def registrar(linha):
    os.makedirs(md.PASTA_SAIDA, exist_ok=True)
    with open(TENTATIVAS, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(linha, quando=time.strftime("%Y-%m-%d %H:%M:%S")), ensure_ascii=False) + "\n")


def principal(parte="descoberta"):
    m1 = lab.carregar("WDO", parte)
    dias = sorted(set(m1.index.date))
    configs = [("referencia: dado sem teto", dict(stop=40.0, meta=None, lock=None)),
               ("referencia: dado com teto de R$ 100 (stop 40)", dict(stop=40.0, meta=100.0, lock=None)),
               ("H16: meta 100 como trava de entrada, stop da posicao em +R$ 90 liquidos", dict(stop=40.0, meta=100.0, lock=90.0)),
               ("H17: teto de R$ 100 com stop de 10 pontos", dict(stop=10.0, meta=100.0, lock=None)),
               ("H17: teto de R$ 100 com stop de 15 pontos", dict(stop=15.0, meta=100.0, lock=None)),
               ("H17: teto de R$ 100 com stop de 20 pontos", dict(stop=20.0, meta=100.0, lock=None))]
    out = []
    for nome, c in configs:
        est = md.DadoNY(stop=c["stop"])
        negs, bateu = md.simular(m1, est, RegrasDoDia(contratos=2), Custos(), meta=c["meta"], lock=c["lock"])
        t = md.tabela_de(nome, negs, bateu, dias, meta=c["meta"] or 100.0)
        t.update(parte=parte, config=c)
        registrar(t)
        out.append(t)
        print(f"{nome:<76} neg {t['negocios']:>3} | acerto {t['acerto_pct']:>5}% | ganho {t['ganho_medio']:>6} perda {t['perda_media']:>7} | R$/neg {t['rs_por_negocio']:>7} | "
              f"por pregao {t['media_por_pregao']:>+6.1f} (t {t['t_da_media_diaria']}) | tocaram {t['pct_dias_tocaram']:>5}% | fecham>=100 {t['pct_dias_fecham_ge_meta']:>5}% | "
              f"pior dia {t['pior_dia']:>6} | queda {t['queda_maxima']:>6}")
    return out


if __name__ == "__main__":
    principal()
