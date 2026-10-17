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

from quant.comum import agora_brt, gravar_atomico
from quant.daytrade import fluxo as fx
from quant.daytrade import historico as h
from quant.pesquisa import lab

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ARQ = os.path.join(RAIZ, "quant", "pesquisa", "provas_vivas.json")
SAIDA = os.path.join(lab.PASTA, "prova_viva.jsonl")
# O modulo MINI-INDICE da area QUANT do terminal le este arquivo (dois caminhos, como o quant.json dos robos).
SAIDAS_INDICE = [os.path.expanduser(x) for x in os.environ.get(
    "QUANT_SAIDA_INDICE",
    "~/Desktop/terminal-artefato/web/d/x/quant_indice.json:~/Desktop/terminal-artefato/cache/out/pagina/quant_indice.json"
).split(":") if x]
NEGOCIOS_PARA_ESTUDO = 60


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


def rotulo_do_pedido(agora, indice):
    """O rotulo do arquivo de barras. O leitor do MetaTrader nao regrava arquivo que ja existe: em 14/10/2026 a medicao da noite
    (19h34) releu as barras pedidas de manha (08h13) e o pregao do dia ficou de fora. Antes das 9h o rotulo e o da manha; dali em
    diante leva a hora (17/10/2026: a rotina da noite passa a rodar as 12h55, quando o Mac ainda esta ligado)."""
    base = int(agora.strftime("%y%m%d"))
    return base * 10 + indice if agora.hour < 9 else base * 1000 + agora.hour * 10 + indice


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
            "pedir_estudo": bool(n >= NEGOCIOS_PARA_ESTUDO and t.res.mean() > 0 and lab._t(t.res) >= 2.0),
            "lista": [{"dia": str(x.dia), "hora": str(x.hora), "lado": str(x.lado), "entrada": float(x.entrada), "pts": round(float(x.pts), 2),
                       "motivo": str(x.saida), "minutos": int(x.minutos), "res": round(float(x.res), 2)} for x in t.tail(80).itertuples()]}


def rodar(arq=ARQ, pasta=fx.PASTA_MT5, gravar=True):
    with open(arq, encoding="utf-8") as f:
        regras = [r for r in json.load(f).get("regras") or [] if r.get("nome")]
    hoje, fora = agora_brt(), []
    for r in regras:
        dias = max(1, int(np.busday_count(pd.Timestamp(r["desde"]).date(), hoje.date()))) + 4      # desde a vespera, com folga
        # "barras_extras": historia a mais para a regra que precisa de memoria (por exemplo, os 60 pregoes anteriores)
        barras = pedir_barras(r.get("simbolo") or r.get("ativo"), min(900_000, dias * 620 + int(r.get("barras_extras") or 0)), pasta,
                              rotulo=rotulo_do_pedido(hoje, regras.index(r)))
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
        painel(fora, regras, quando=hoje)
    return fora


def painel(fora=None, regras=None, quando=None, saidas=None, arq=ARQ):
    """Grava o arquivo do modulo MINI-INDICE da area QUANT. Sem `fora`, usa a ultima medicao gravada; sem medicao nenhuma,
    mostra as regras com zero negocio. Nada aqui opera: sao regras em prova viva, medidas so com pregoes novos."""
    if regras is None:
        with open(arq, encoding="utf-8") as f:
            regras = [r for r in json.load(f).get("regras") or [] if r.get("nome")]
    medido_em = quando.isoformat(timespec="seconds") if quando is not None else None
    if fora is None:
        fora = []
        try:
            with open(SAIDA, encoding="utf-8") as f:
                linhas = [ln for ln in f.read().splitlines() if ln.strip()]
            if linhas:
                ult = json.loads(linhas[-1])
                fora, medido_em = ult.get("regras") or [], ult.get("quando")
        except (OSError, ValueError):
            fora = []
    por_nome = {x.get("nome"): x for x in fora}
    linhas_regra, negocios, avisos = [], [], []
    for r in regras:
        x = por_nome.get(r["nome"]) or {}
        n = int(x.get("negocios") or 0)
        if x.get("erro"):
            avisos.append(f"{(r.get('na_tela') or {}).get('titulo') or r.get('titulo') or r['nome']}: {x['erro']}")
        if x.get("pedir_estudo"):
            falta = "PEDIDO DE ESTUDO: passou de 60 negócios com média positiva e t de 2 ou mais"
        elif n >= NEGOCIOS_PARA_ESTUDO:
            falta = "já tem 60 negócios; falta média positiva com t de 2 ou mais"
        else:
            falta = f"faltam {NEGOCIOS_PARA_ESTUDO - n} negócios (e média positiva com t de 2 ou mais) para virar pedido de estudo"
        tela = r.get("na_tela") or {}                # textos com acento para a tela (os arquivos do repositorio nao levam acento)
        titulo = tela.get("titulo") or r.get("titulo") or r["nome"]
        linhas_regra.append({"nome": r["nome"], "titulo": titulo, "explicacao": tela.get("explicacao") or r.get("explicacao"),
                             "estado": "medindo", "desde": r.get("desde"), "negocios": n, "media_rs": x.get("media"),
                             "total_rs": x.get("soma") if n else None, "acerto_pct": x.get("acerto"), "t": x.get("t"),
                             "falta_para_estudo": falta, "historico": r.get("historico")})
        for g in x.get("lista") or []:
            negocios.append({"dia": g.get("dia"), "regra": titulo, "lado": g.get("lado"), "entrada": g.get("entrada"),
                             "hora_entrada": g.get("hora"), "pontos": g.get("pts"), "resultado_rs": g.get("res"), "motivo": g.get("motivo"),
                             "minutos": g.get("minutos")})
    negocios.sort(key=lambda g: (str(g.get("dia")), str(g.get("hora_entrada"))), reverse=True)
    por_dia = {}
    for g in negocios:
        por_dia[g["dia"]] = por_dia.get(g["dia"], 0.0) + float(g.get("resultado_rs") or 0.0)
    serie, ac = [], 0.0
    for d in sorted(por_dia):
        ac += por_dia[d]
        serie.append({"dia": d, "resultado_rs": round(por_dia[d], 2), "acumulado_rs": round(ac, 2)})
    if medido_em is None:
        avisos.append("Ainda não houve medição: ela roda na rotina da noite, com o MetaTrader aberto.")
    agora = agora_brt()
    obj = {"v": 1, "tipo": "indice", "gerado": agora.isoformat(timespec="seconds"), "modo": "simulacao", "estado": "medindo",
           "medido_em": medido_em,
           "texto": "Nenhuma regra do mini-índice passou no histórico. As regras abaixo estão em prova viva: são medidas só com "
                    "pregões novos, com os parâmetros congelados, e nada opera.",
           "regras": linhas_regra, "negocios": negocios[:120], "serie": serie, "avisos": avisos,
           "termos": [{"termo": "Prova viva", "explicacao": "acompanhar a regra só com pregões que ainda não existiam quando ela foi desenhada; é o único teste que não dá para ajustar depois"},
                      {"termo": "t", "explicacao": "quantas vezes a média é maior que o erro dela; abaixo de 2 pode ser acaso"},
                      {"termo": "Pedido de estudo", "explicacao": "60 negócios ou mais com média positiva e t de 2 ou mais: a regra volta para a mesa de pesquisa, não entra operando sozinha"},
                      {"termo": "Mini-índice", "explicacao": "contrato futuro pequeno do Ibovespa (WIN); cada ponto vale R$ 0,20"}]}
    for caminho in (SAIDAS_INDICE if saidas is None else saidas):
        try:
            gravar_atomico(caminho, json.dumps(obj, ensure_ascii=False))
        except OSError:
            pass
    return obj


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
    import sys
    if "--painel" in sys.argv:                     # so regrava o arquivo da tela com a ultima medicao (nao precisa do MetaTrader)
        o = painel()
        print(f"quant_indice.json gravado: {len(o['regras'])} regras, {len(o['negocios'])} negocios, medido em {o['medido_em']}")
    else:
        print(texto(rodar()))
