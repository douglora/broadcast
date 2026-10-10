"""
Prova viva: mede, so com pregoes NOVOS, as regras que nao foram aprovadas no historico mas merecem acompanhamento
(quant/pesquisa/provas_vivas.json). Nada aqui opera nem muda o robo.

As barras vem do historico do proprio MetaTrader (o servidor guarda as barras de 1 minuto; nao depende de o Mac estar
acordado na hora do pregao): o programa pede ao leitor do MetaTrader (arquivo autopilot_historia.txt) as barras desde a
vespera de `desde` e roda a regra com as contas do laboratorio. Cada pedido gera um arquivo pequeno na pasta do
MetaTrader, com a data no nome; nada e apagado.

Uso: python -m quant.pesquisa.prova_viva            (precisa do MetaTrader aberto)
"""
import importlib.util
import json
import os
import time

import numpy as np
import pandas as pd

from quant.comum import agora_brt
from quant.daytrade import fluxo as fx
from quant.daytrade import historico as h
from quant.pesquisa import lab

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ARQ = os.path.join(RAIZ, "quant", "pesquisa", "provas_vivas.json")
SAIDA = os.path.join(lab.PASTA, "prova_viva.jsonl")


def pedir_barras(simbolo, quantas, pasta=fx.PASTA_MT5, espera_s=150, rotulo=None):
    """Barras de 1 minuto mais recentes do simbolo, pelo leitor do MetaTrader. O rotulo (data) entra no nome do arquivo:
    o leitor trata qualquer numero diferente de 5, 15 e 60 como 1 minuto e nao regrava arquivo que ja existe."""
    rotulo = rotulo or int(agora_brt().strftime("%y%m%d"))
    nome = os.path.join(pasta, f"autopilot_historia_{simbolo.replace('$', 'S')}_M{rotulo}.csv")
    if not os.path.exists(nome):
        with open(os.path.join(pasta, "autopilot_historia.txt"), "w", encoding="ascii") as f:
            f.write(f"{simbolo};{rotulo};{int(quantas)}\n")
        fim = time.time() + espera_s
        while time.time() < fim and not os.path.exists(nome):
            time.sleep(3)
        if not os.path.exists(nome):
            return None
        time.sleep(2)
    return h.carregar(nome)


def medir_regra(r, barras):
    """Roda a regra nas barras e devolve o resumo so dos negocios de `desde` em diante."""
    arq = r["arquivo"] if os.path.isabs(r["arquivo"]) else os.path.join(RAIZ, r["arquivo"])
    spec = importlib.util.spec_from_file_location("regra_viva_" + r["nome"], arq)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    s = getattr(mod, r.get("funcao") or "regra")(barras)
    res = lab.avaliar(barras, s, nome=r["nome"], familia="prova_viva", ativo=r.get("ativo", "WDO"), registrar=False, **(r.get("kw") or {}))
    t = lab.medir(res["negocios"], espec=lab.espec_de(r.get("ativo", "WDO")))
    t = t[pd.to_datetime(t.dia) >= pd.Timestamp(r["desde"])]
    n = len(t)
    return {"nome": r["nome"], "titulo": r.get("titulo") or r["nome"], "desde": r["desde"], "negocios": n,
            "acerto": round(float((t.res > 0).mean() * 100), 1) if n else None, "media": round(float(t.res.mean()), 2) if n else None,
            "t": round(lab._t(t.res), 2) if n > 3 else None, "soma": round(float(t.res.sum()), 2) if n else 0.0,
            "ultimo": str(t.dia.max()) if n else None,
            "pedir_estudo": bool(n >= 60 and t.res.mean() > 0 and lab._t(t.res) >= 2.0)}


def rodar(arq=ARQ, pasta=fx.PASTA_MT5, gravar=True):
    with open(arq, encoding="utf-8") as f:
        regras = [r for r in json.load(f).get("regras") or [] if r.get("nome")]
    hoje, fora = agora_brt(), []
    for r in regras:
        dias = max(1, int(np.busday_count(pd.Timestamp(r["desde"]).date(), hoje.date()))) + 4      # desde a vespera, com folga
        # "barras_extras": historia a mais para a regra que precisa de memoria (por exemplo, os 60 pregoes anteriores)
        barras = pedir_barras(r.get("simbolo") or r.get("ativo"), min(900_000, dias * 620 + int(r.get("barras_extras") or 0)), pasta,
                              rotulo=int(agora_brt().strftime("%y%m%d")) * 10 + regras.index(r))
        if barras is None or not len(barras):
            fora.append({"nome": r["nome"], "titulo": r.get("titulo") or r["nome"], "erro": "o MetaTrader nao entregou as barras (esta aberto?)"})
            continue
        try:
            fora.append(medir_regra(r, barras))
        except Exception as e:
            fora.append({"nome": r["nome"], "titulo": r.get("titulo") or r["nome"], "erro": f"{type(e).__name__}: {e}"})
    if gravar:
        os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
        with open(SAIDA, "a", encoding="utf-8") as f:
            f.write(json.dumps({"quando": hoje.isoformat(timespec="seconds"), "regras": fora}, ensure_ascii=False) + "\n")
    return fora


def texto(fora):
    linhas = ["PROVA VIVA (so pregoes novos; nada aqui opera):"]
    for x in fora:
        if x.get("erro"):
            linhas.append(f"- {x['titulo']}: {x['erro']}")
        elif not x["negocios"]:
            linhas.append(f"- {x['titulo']}: ainda sem negocio desde {x['desde']}.")
        else:
            linhas.append(f"- {x['titulo']}: {x['negocios']} negocios desde {x['desde']}, acerto {x['acerto']}%, media R$ {x['media']:+.2f} por negocio"
                          + (f" (t {x['t']:+.1f})" if x["t"] is not None else "") + f", soma R$ {x['soma']:+.0f}"
                          + (". PEDIDO DE ESTUDO: passou de 60 negocios com media positiva e t >= 2." if x["pedir_estudo"] else "."))
    return "\n".join(linhas)


if __name__ == "__main__":
    print(texto(rodar()))
