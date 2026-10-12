"""python -m quant.observacao [--placar] [--hoje AAAA-MM-DD] [--sem-terminal]"""
import argparse
import json
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

from quant.comum import gravar_atomico
from quant.observacao import ARQ_HOJE, DIR_OBS, dose, placar, sinais, termometro


def _mao_atual():
    try:
        from quant.risco import livro
        v, _txt = livro.exposicao_acoes()
        return v
    except Exception:
        return None


def _vol_ibov(f):
    s = f["series"].get("IBOV")
    if s is None or len(s) < 21:
        return None
    r = np.log(s).diff().dropna()
    return float(r.iloc[-20:].std() * np.sqrt(252))


def rodar(hoje=None, com_tabela=True, gravar=True):
    hoje = pd.Timestamp(hoje or date.today()).date()
    f = sinais.montar_fontes(hoje, com_tabela=com_tabela)
    lidos, faltam = sinais.calcular(f)
    term = termometro.ler(f)
    rec = dose.recomendar(hoje, term, f.get("mapa_eua"), f.get("copom"), _vol_ibov(f), _mao_atual())
    obj = {"gerado": pd.Timestamp.now().isoformat(timespec="seconds"), "dia": str(hoje), "modo": "so medido", "sinais": lidos, "sem_dado": faltam,
           "termometro": term, "dose": rec,
           "nota": "Camada de observacao: tudo e so medido; nenhum sinal muda lote, exposicao ou chave. O placar (python -m quant.observacao --placar) diz, com 60+ leituras, quem tem informacao."}
    if gravar:
        n = placar.registrar(hoje, lidos, term, rec)
        os.makedirs(DIR_OBS, exist_ok=True)
        gravar_atomico(ARQ_HOJE, json.dumps(obj, ensure_ascii=False, indent=1))
        obj["leituras_gravadas"] = n
    return obj


def texto(obj):
    linhas = [f"OBSERVACAO de {obj['dia']} (so medido): {len(obj['sinais'])} sinais lidos, {len(obj['sem_dado'])} sem dado.", obj["termometro"]["texto"],
              f"Dose (G23): degrau {obj['dose']['degrau']} ({obj['dose']['vol_alvo_aa_pct']}% a.a.): {obj['dose']['motivo']}."]
    for s in obj["sinais"]:
        marca = {1: "+", -1: "-", 0: "o"}[s["leitura"]]
        linhas.append(f"  [{marca}] {s['grupo']:<10} {s['id']:<22} {s['texto']}")
    if obj["sem_dado"]:
        linhas.append("  sem dado: " + ", ".join(obj["sem_dado"]))
    return "\n".join(linhas)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Camada de observacao do robo (so medida)")
    ap.add_argument("--placar", action="store_true", help="imprime o placar dos sinais contra o que o mercado fez depois")
    ap.add_argument("--hoje", default=None)
    ap.add_argument("--sem-terminal", action="store_true", help="nao chama a tabela do terminal (mais rapido; sem consenso e TIR)")
    a = ap.parse_args(argv)
    if a.placar:
        cartao = None
        try:
            with open(os.path.join(os.path.dirname(DIR_OBS), "mesa", "cartao_cenario.json"), encoding="utf-8") as f:
                cartao = json.load(f)
        except (OSError, ValueError):
            cartao = None
        print(placar.texto(placar.montar(cartao=cartao)))
        return 0
    print(texto(rodar(a.hoje, com_tabela=not a.sem_terminal)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
