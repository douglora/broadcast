"""
O livro inteiro: pesos entre classes, mao por volatilidade e o orcamento de queda. Decisao do Douglas, fora do codigo:
`quant/saida/risco_livro.json`.

POR QUE EXISTE. Ate 10/10/2026 o unico limite de queda do projeto era o do day trade (R$ 10 mil, 10% do capital). O estudo
dos gestores mostrou a incoerencia: uma carteira de acoes sem protecao ja caiu 35% no teste longo, entao um limite de 10%
para o livro inteiro so comportaria 20% a 30% do capital em acoes. Em 11/10/2026 o Douglas respondeu: a carteira "entra
cheia", os pesos entre classes "pode ser" 60/30/10 com a regra de volatilidade, e "corrija entao" o orcamento de queda.

O QUE FICA DECIDIDO AQUI (padrao; ele muda no arquivo):
  - pesos: 60% acoes, 30% opcoes (capital protegido: o caixa fica no CDI), 10% dolar;
  - mao por volatilidade nas acoes: exposicao = peso x min(1, vol media / vol dos ultimos 63 pregoes). Corta a cauda; nao
    melhora o Sharpe (quant/saida/pesquisa_carteira/RESULTADO_MAO_E_ALOCACAO.md);
  - corte de mao por queda: DESLIGADO (no teste so realizou prejuizo no fundo);
  - orcamento de queda do livro: 25% do capital, repartido em 17% para as acoes (com 60% do capital e a regra de
    volatilidade a queda historica foi de uns 18%), 3% para as opcoes (o premio em risco) e 5% para o day trade;
  - ao estourar o orcamento, NAO vende no fundo: o livro de opcoes para de abrir tese nova (quant/opcoes/carteira_simulada.py),
    o day trade para pelo limite proprio (quant/saida/risco_robo.json, a fatia dele: R$ 5.000) e o aviso vai na primeira linha.

Funcoes puras mais a leitura do arquivo. Quem usa: quant/config_carteira.py (exposicao da carteira), quant/risco/orcamento.py
(pesos) e quant/opcoes/carteira_simulada.py (orcamento mensal do capital protegido sobre o capital da CLASSE).
"""
import json
import os
from datetime import datetime, timedelta

from quant.comum import DIR_SAIDA

ARQ = os.path.join(DIR_SAIDA, "risco_livro.json")
ARQ_ORCAMENTO = os.path.join(DIR_SAIDA, "risco", "orcamento.json")
PADRAO = {"ligado": False,
          "pesos": {"acoes": 0.60, "opcoes": 0.30, "dolar": 0.10},
          "mao_por_volatilidade": True, "corte_por_queda": False,
          "queda_maxima_livro_pct": 25.0,
          "orcamento_de_queda_pct": {"acoes": 17.0, "opcoes": 3.0, "daytrade": 5.0}}
VALIDADE_ORCAMENTO_DIAS = 4          # o orcamento de sexta vale ate a manha de terca depois de feriado


def config(arq=None):
    """A decisao do Douglas por cima do padrao. Arquivo ausente ou ilegivel: padrao, com `ligado` falso."""
    c = json.loads(json.dumps(PADRAO))
    try:
        with open(arq or ARQ, encoding="utf-8") as f:
            v = json.load(f)
    except (OSError, ValueError):
        return c
    if not isinstance(v, dict):
        return c
    c["ligado"] = bool(v.get("ligado"))
    pesos = v.get("pesos")
    if isinstance(pesos, dict):
        try:
            p = {k: float(pesos[k]) for k in ("acoes", "opcoes", "dolar")}
            if all(0.0 <= x <= 1.0 for x in p.values()) and abs(sum(p.values()) - 1.0) < 1e-6:
                c["pesos"] = p
        except (KeyError, TypeError, ValueError):
            pass
    for k in ("mao_por_volatilidade", "corte_por_queda"):
        if k in v:
            c[k] = bool(v[k])
    try:
        q = float(v.get("queda_maxima_livro_pct"))
        if 1.0 <= q <= 60.0:
            c["queda_maxima_livro_pct"] = q
    except (TypeError, ValueError):
        pass
    o = v.get("orcamento_de_queda_pct")
    if isinstance(o, dict):
        try:
            c["orcamento_de_queda_pct"] = {k: float(o[k]) for k in ("acoes", "opcoes", "daytrade")}
        except (KeyError, TypeError, ValueError):
            pass
    for k in ("desde", "motivo"):
        if v.get(k):
            c[k] = v[k]
    return c


def peso(classe, arq=None):
    """Peso da classe no livro; 1.0 quando o livro por classes esta desligado (cada modulo usa o capital inteiro)."""
    c = config(arq)
    return float(c["pesos"].get(classe, 0.0)) if c["ligado"] else 1.0


def mao_das_acoes(hoje=None, arq_orcamento=None):
    """A mao (0 a 1) que a regra de volatilidade deu para as acoes na ultima rodada do orcamento de risco, se ela for
    recente. Devolve (mao, texto). Sem orcamento recente: 1,0, dizendo por que."""
    try:
        with open(arq_orcamento or ARQ_ORCAMENTO, encoding="utf-8") as f:
            o = json.load(f)
        quando = datetime.fromisoformat(str(o.get("gerado_em")))
        x = float(((o.get("classes") or {}).get("acoes") or {}).get("exposicao"))
    except (OSError, ValueError, TypeError):
        return 1.0, "sem orçamento de risco recente: mão cheia"
    if hoje is None:
        agora = datetime.now()
    elif isinstance(hoje, datetime):
        agora = hoje
    else:                                                    # so a data: vale o fim do dia
        try:
            agora = datetime.fromisoformat(str(hoje)[:10] + "T23:59:00")
        except ValueError:
            agora = datetime.now()
    if agora.replace(tzinfo=None) - quando.replace(tzinfo=None) > timedelta(days=VALIDADE_ORCAMENTO_DIAS):
        return 1.0, f"orçamento de risco velho (de {quando.date()}): mão cheia"
    x = max(0.0, min(1.0, x))
    return x, (f"mão de {x:.2f}".replace(".", ",") + f" pela volatilidade (orçamento de {quando.strftime('%d/%m')})")


def exposicao_acoes(hoje=None, arq=None, arq_orcamento=None):
    """Fracao do capital em acoes pelo livro: peso da classe x mao por volatilidade. Devolve (valor, texto) ou (None, motivo)
    quando o livro por classes esta desligado."""
    c = config(arq)
    if not c["ligado"]:
        return None, "livro por classes desligado"
    p = float(c["pesos"]["acoes"])
    if not c["mao_por_volatilidade"]:
        return p, f"{p * 100:.0f}% do capital (peso da classe; regra de volatilidade desligada)"
    m, txt = mao_das_acoes(hoje, arq_orcamento)
    return p * m, f"{p * m * 100:.0f}% do capital: peso de {p * 100:.0f}% x {txt}"


def situacao(capital, modulos, arq=None):
    """Queda do livro contra o orcamento. `modulos`: {"acoes"|"opcoes"|"daytrade": {"pico_rs": x, "agora_rs": y}} com o
    resultado acumulado de cada modulo no pico e agora (em reais). Devolve um dict para a tela e para a rotina da noite."""
    c = config(arq)
    cap = float(capital)
    linhas, total = [], 0.0
    for nome in ("acoes", "opcoes", "daytrade"):
        m = modulos.get(nome) or {}
        queda = max(0.0, float(m.get("pico_rs") or 0.0) - float(m.get("agora_rs") or 0.0))
        total += queda
        limite = cap * float(c["orcamento_de_queda_pct"].get(nome, 0.0)) / 100.0
        linhas.append({"modulo": nome, "queda_rs": round(queda, 2), "orcamento_rs": round(limite, 2),
                       "usado_pct": round(queda / limite * 100.0, 1) if limite > 0 else None, "estourou": bool(limite > 0 and queda >= limite)})
    limite_livro = cap * float(c["queda_maxima_livro_pct"]) / 100.0
    estourou = total >= limite_livro
    return {"capital": cap, "queda_do_livro_rs": round(total, 2), "orcamento_do_livro_rs": round(limite_livro, 2),
            "usado_pct": round(total / limite_livro * 100.0, 1) if limite_livro else None, "estourou": bool(estourou),
            "modulos": linhas,
            "regra": ("Ao estourar o orçamento de queda o robô não vende ação no fundo: o livro de opções para de abrir tese nova, o day trade "
                      "para pelo limite dele (a fatia de day trade do orçamento) e o aviso vai na primeira linha.")}


# ─────────────────────────────────────────────────────────────
# Leitura dos modulos e gravacao (impuro: le disco). `python -m quant.risco.livro`
# ─────────────────────────────────────────────────────────────
ARQ_SAIDA = os.path.join(DIR_SAIDA, "risco", "livro.json")
ARQ_HISTORICO = os.path.join(DIR_SAIDA, "risco", "livro_historico.json")


def _json(caminho, padrao=None):
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return padrao


def _serie_de_resultado(arq, capital):
    """data -> resultado acumulado (patrimonio menos o capital inicial) de um livro que grava `serie.json`."""
    s = _json(arq, []) or []
    return {str(x["data"]): float(x["patrimonio"]) - float(capital) for x in s
            if isinstance(x, dict) and x.get("data") and x.get("patrimonio") is not None}


def resultado_acoes(capital, arq=None, arq_swing=None, capital_swing=None):
    """(agora, pico) do resultado acumulado do modulo de acoes: a carteira de fatores (quant/saida/vivo/serie.json) mais o livro de
    swing (quant/saida/swing/serie.json, so as operacoes COM capital). Cada livro leva adiante o ultimo valor nos dias em que nao gravou."""
    fat = _serie_de_resultado(arq or os.path.join(DIR_SAIDA, "vivo", "serie.json"), capital)
    if capital_swing is None:
        capital_swing = float(capital) * float(PADRAO["pesos"]["acoes"])
        try:
            from quant.swing import evidencia
            capital_swing = float(evidencia.config()["capital"])
        except Exception:
            pass
    swi = _serie_de_resultado(arq_swing or os.path.join(os.environ.get("QUANT_SWING_DIR") or os.path.join(DIR_SAIDA, "swing"), "serie.json"), capital_swing)
    v, a, b = [], 0.0, 0.0
    for d in sorted(set(fat) | set(swi)):
        a, b = fat.get(d, a), swi.get(d, b)
        v.append(a + b)
    return (v[-1], max([0.0] + v)) if v else (0.0, 0.0)


def resultado_daytrade(pasta=None):
    """(agora, pico) do acumulado do day trade, somando por pregao todas as regras que ja rodaram (serie*.json)."""
    pasta = pasta or os.path.join(DIR_SAIDA, "daytrade")
    por_dia = {}
    try:
        nomes = sorted(n for n in os.listdir(pasta) if n.startswith("serie") and n.endswith(".json"))
    except OSError:
        nomes = []
    for n in nomes:
        for x in _json(os.path.join(pasta, n), []) or []:
            if isinstance(x, dict) and x.get("data"):
                por_dia[str(x["data"])] = por_dia.get(str(x["data"]), 0.0) + float(x.get("resultado") or 0.0)
    acum = pico = 0.0
    for d in sorted(por_dia):
        acum += por_dia[d]
        pico = max(pico, acum)
    return acum, pico


def resultado_opcoes(arq=None):
    """Acumulado do livro de opcoes agora (aberto mais encerrado). O pico vem do historico deste modulo."""
    e = _json(arq or os.path.join(DIR_SAIDA, "opcoes", "carteira_simulada.json"), {}) or {}
    return sum(float(p.get("resultado_rs") or 0.0) for p in e.get("posicoes") or [])


def _texto(c, s, expo):
    def r(x):
        return f"R$ {x:,.0f}".replace(",", ".")
    o = c["orcamento_de_queda_pct"]
    linhas = [f"Pesos do livro: {c['pesos']['acoes'] * 100:.0f}% ações, {c['pesos']['opcoes'] * 100:.0f}% opções (capital protegido, com o caixa no CDI) e "
              f"{c['pesos']['dolar'] * 100:.0f}% dólar (margem e capital de risco do day trade; o que sobra fica no CDI).",
              (f"Ações hoje: {expo[1]}." if expo[0] is not None else "Livro por classes desligado: cada módulo usa a própria regra de tamanho."),
              f"Orçamento de queda: {c['queda_maxima_livro_pct']:.0f}% do capital ({r(s['orcamento_do_livro_rs'])}), repartido em {o['acoes']:.0f}% para as ações, "
              f"{o['opcoes']:.0f}% para as opções e {o['daytrade']:.0f}% para o day trade. Usado até agora: {r(s['queda_do_livro_rs'])} "
              f"({str(round(s['usado_pct'] or 0, 1)).replace('.', ',')}% do orçamento).",
              s["regra"],
              "Cortar a mão quando o livro cai continua desligado: no teste essa regra só realizou prejuízo no fundo."]
    return linhas


def montar(capital=100_000.0, hoje=None, arq=None, historico=None, gravar_historico=True):
    """O bloco do livro para a tela e para a rotina: decisao, exposicao das acoes e queda contra o orcamento."""
    c = config(arq)
    agora = datetime.now()
    dia = str(hoje or agora.date())
    ac, pico_ac = resultado_acoes(capital)
    dt, pico_dt = resultado_daytrade()
    op = resultado_opcoes()
    arq_h = historico or ARQ_HISTORICO
    h = [x for x in (_json(arq_h, []) or []) if isinstance(x, dict) and x.get("data")]
    h = [x for x in h if x["data"] != dia] + [{"data": dia, "acoes_rs": round(ac, 2), "opcoes_rs": round(op, 2), "daytrade_rs": round(dt, 2)}]
    h.sort(key=lambda x: x["data"])
    pico_op = max([0.0] + [float(x.get("opcoes_rs") or 0.0) for x in h])
    s = situacao(capital, {"acoes": {"pico_rs": pico_ac, "agora_rs": ac}, "opcoes": {"pico_rs": pico_op, "agora_rs": op},
                           "daytrade": {"pico_rs": pico_dt, "agora_rs": dt}}, arq)
    expo = exposicao_acoes(hoje, arq)
    bloco = {"gerado_em": agora.isoformat(timespec="seconds"), "ligado": c["ligado"], "desde": c.get("desde"), "motivo": c.get("motivo"),
             "pesos": c["pesos"], "mao_por_volatilidade": c["mao_por_volatilidade"], "corte_por_queda": c["corte_por_queda"],
             "exposicao_acoes": expo[0], "exposicao_acoes_texto": expo[1],
             "resultado_rs": {"acoes": round(ac, 2), "opcoes": round(op, 2), "daytrade": round(dt, 2), "livro": round(ac + op + dt, 2)},
             **s, "porque": _texto(c, s, expo)}
    if gravar_historico:
        os.makedirs(os.path.dirname(arq_h), exist_ok=True)
        tmp = arq_h + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(h, f, ensure_ascii=False)
        os.replace(tmp, arq_h)
    return bloco


def gravar(bloco, arq=None):
    arq = arq or ARQ_SAIDA
    os.makedirs(os.path.dirname(arq), exist_ok=True)
    tmp = arq + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(bloco, f, ensure_ascii=False, indent=1)
    os.replace(tmp, arq)
    return arq


def ler_bloco(arq=None):
    """O ultimo bloco gravado (para a tela), ou None."""
    return _json(arq or ARQ_SAIDA)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Livro inteiro: pesos, mao das acoes e queda contra o orcamento")
    ap.add_argument("--capital", type=float, default=100_000.0)
    a = ap.parse_args(argv)
    b = montar(a.capital)
    print(f"Livro ({b['gerado_em']}): {'LIGADO' if b['ligado'] else 'desligado'}")
    for linha in b["porque"]:
        print("-", linha)
    for m in b["modulos"]:
        print(f"  {m['modulo']:9s} queda R$ {m['queda_rs']:>9.2f} de R$ {m['orcamento_rs']:>9.2f}{'  ESTOUROU' if m['estourou'] else ''}")
    if b["estourou"]:
        print("AVISO: orcamento de queda do livro ESTOURADO: nada tatico novo abre")
    print("gravado em", gravar(b))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
