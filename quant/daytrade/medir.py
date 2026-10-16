"""
Mede o que a fita dizia em cada entrada do robo e o resultado que a entrada teve.

Junta, de todos os pregoes em quant/saida/daytrade/<data>/, as entradas gravadas (sinais_<setup>.jsonl, com as
medidas da fita) e as saidas (estado_<setup>.json), pela hora da entrada, e compara:
  - entradas que a fita CONFIRMOU contra as que nao confirmou;
  - por nome do nivel; por hora do dia.
Com poucos negocios isso nao prova nada: a tabela mostra o numero de negocios de cada linha para lembrar disso.

Desde 08/10/2026 o robo guarda TODO sinal (linha "sinal" do mesmo arquivo), operando ou so medindo, o dia inteiro.
`sinais` calcula o que cada um teria dado, andando pelas barras de 1 minuto depois dele com as mesmas contas do
teste historico (stop primeiro, alvo, parcial com stop na entrada, saida por tempo), e o relatorio separa por
tecnica e pelo que a fita dizia. E assim que a amostra cresce sem o robo pagar para operar a regra que perde.

Uso: python -m quant.daytrade.medir [--setup niveis]
"""
import argparse
import glob
import json
import os

import pandas as pd

from quant.comum import ler_json
from quant.daytrade.robo import DIR_DT

FIM_DA_MEDIDA = "17:30"            # o sinal medido que nao saiu por stop, alvo ou tempo sai aqui, a mercado
ARQ_MODO = os.path.join(os.path.dirname(DIR_DT), "modo_robo.json")


def fim_do_robo(arq=None):
    """A hora em que o robo zera tudo (`hora_zerar` em modo_robo.json; desde 13/10/2026 vai ate 18h24). O sinal medido segue a mesma
    janela do robo: com o corte antigo (17h30) a regra do fim do pregao do mini-indice "saia" na propria barra da entrada. Sem a chave,
    FIM_DA_MEDIDA."""
    v = str((ler_json(arq or ARQ_MODO, padrao=None) or {}).get("hora_zerar") or "")
    return v if len(v) == 5 and v[2] == ":" and "09:00" <= v <= "18:29" else FIM_DA_MEDIDA


def do_contrato(ev):
    """Contratos, custo, valor do ponto e tick para o `hipotetico` de um sinal: os do contrato do sinal (mini-dolar ou mini-indice) e a dose
    da regra do laboratorio, quando ela traz uma; sem dose, 2 contratos (a medida de sempre)."""
    from quant.daytrade.estrategia import CONTRATOS
    k = CONTRATOS.get(ev.get("ativo") or "WDOFUT") or CONTRATOS["WDOFUT"]
    dose = (ev.get("medidas") or {}).get("dose")
    return {"contratos": int(dose) if dose else 2, "custo_lado": k["custo"], "valor_ponto": k["valor_ponto"], "tick": k["tick"]}


def entradas_do_dia(linhas):
    """[(ativo, tecnica, segundos)] das entradas gravadas no jsonl de sinais do dia."""
    return [(e.get("ativo"), e.get("tecnica"), _segundos(e.get("hora"))) for e in linhas if e.get("tipo") == "entrada"]


def entrou(ev, entradas, folga_s=15):
    """O sinal virou entrada? "opera" diz que a REGRA opera, nao que o sinal entrou (14/10/2026): operado e o sinal que tem a entrada
    da mesma tecnica, no mesmo contrato, ate `folga_s` segundos depois (ou antes) dele."""
    s = _segundos(ev.get("hora"))
    return s is not None and any(a == ev.get("ativo") and t == ev.get("tecnica") and x is not None and abs(x - s) <= folga_s
                                 for a, t, x in entradas)


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
            if ev.get("tipo") == "sinal":
                continue                                         # sinal medido: fica para `sinais`
            r = res.get((ev.get("ativo"), ev.get("hora")))
            if r is None or r["saida"] is None:
                continue                                         # entrada ainda aberta, ou de outro setup
            fita = (ev.get("medidas") or {}).get("fita") or {}
            fora.append({"dia": os.path.basename(dia), "hora": ev.get("hora"), "lado": ev.get("lado"), "nivel": ev.get("nome_nivel"),
                         "resultado": r["resultado"], "saida": r["saida"], "confirmou": fita.get("confirmou"),
                         "favor": fita.get("fracao_a_favor"), "testes": fita.get("testes_do_nivel")})
    return fora


def hipotetico(ev, df, contratos=2, custo_lado=1.20, valor_ponto=10.0, tick=0.5, fim=FIM_DA_MEDIDA):
    """O que o sinal teria dado, pelas barras de 1 minuto a partir do minuto em que nasceu. None sem barras depois dele."""
    try:
        t0 = pd.Timestamp(ev["quando"]).tz_localize(None).floor("min")
        entrada, s = float(ev["entrada"]), (1.0 if ev["lado"] == "C" else -1.0)
        stop = entrada - s * float(ev["stop_pts"])
    except (KeyError, TypeError, ValueError):
        return None
    alvo = None if not ev.get("alvo_pts") else entrada + s * float(ev["alvo_pts"])
    parcial = None if not ev.get("parcial_pts") or contratos < 2 else entrada + s * float(ev["parcial_pts"])
    limite = None if not ev.get("tempo_max_s") else t0 + pd.to_timedelta(float(ev["tempo_max_s"]), unit="s")
    d = df[(df.index >= t0) & (df.index.date == t0.date())]
    if not len(d):
        return None
    restam, soma, feita, saida = contratos, 0.0, False, None
    for t, o, h, l in zip(d.index, d["o"].to_numpy(), d["h"].to_numpy(), d["l"].to_numpy()):
        if t.strftime("%H:%M") >= fim or (limite is not None and t >= limite):
            soma += s * ((o - s * tick) - entrada) * restam
            saida = "tempo" if limite is not None and t >= limite else "fim do dia"
            break
        pior, melhor = (l, h) if s > 0 else (h, l)
        if (pior <= stop) if s > 0 else (pior >= stop):
            base = min(o, stop) if s > 0 else max(o, stop)
            soma += s * ((base - s * tick) - entrada) * restam
            saida = "stop" if not feita else "zero a zero"
            break
        if alvo is not None and ((melhor >= alvo) if s > 0 else (melhor <= alvo)):
            soma += s * (alvo - entrada) * restam
            saida = "alvo"
            break
        if parcial is not None and not feita and ((melhor >= parcial) if s > 0 else (melhor <= parcial)):
            metade = restam // 2
            soma += s * (parcial - entrada) * metade
            restam -= metade
            feita, stop = True, entrada
    if saida is None:
        return None                                              # o dia ainda nao acabou para este sinal
    return {"pontos": soma / contratos, "resultado": soma * valor_ponto - 2 * custo_lado * contratos, "saida": saida}


def _segundos(hora):
    try:
        p = str(hora).split(":")
        return int(p[0]) * 3600 + int(p[1]) * 60 + (int(p[2]) if len(p) > 2 else 0)
    except (ValueError, IndexError):
        return None


def sinais(setup="niveis", pasta=DIR_DT, pasta_mt5=None, ativo="WDOFUT"):
    """Todos os sinais guardados, com o resultado que teriam dado."""
    from quant.daytrade import barras as br
    df = br.Barras(ativo, pasta, pasta_mt5).df
    fora = []
    for dia in sorted(glob.glob(os.path.join(pasta, "20??-??-??"))):
        try:
            linhas = [json.loads(x) for x in open(os.path.join(dia, f"sinais_{setup}.jsonl"), encoding="utf-8") if x.strip()]
        except OSError:
            continue
        entradas = entradas_do_dia(linhas)
        for ev in linhas:
            if ev.get("tipo") != "sinal" or ev.get("ativo") != ativo or ev.get("entrada") is None:
                continue
            r = hipotetico(ev, df, fim=fim_do_robo(), **do_contrato(ev))
            if r is None:
                continue
            fita = (ev.get("medidas") or {}).get("fita") or {}
            # 14/10/2026: "opera" diz que a regra opera, nao que o sinal entrou (9h01 e 9h06 eram antes da janela; das 9h48 as 10h36
            # havia posicao aberta). Operado e o sinal que tem a entrada da mesma tecnica no mesmo instante (ate 15 s).
            fora.append({"dia": os.path.basename(dia), "hora": ev.get("hora"), "lado": ev.get("lado"), "tecnica": ev.get("tecnica"),
                         "nivel": ev.get("nome_nivel"), "opera": bool(ev.get("opera")), "entrou": entrou(ev, entradas), "bloqueio": ev.get("bloqueio"),
                         "resultado": r["resultado"], "saida": r["saida"],
                         "confirmou": fita.get("confirmou"), "favor": fita.get("fracao_a_favor"),
                         "na_janela": "09:15" <= (ev.get("hora") or "")[:5] < "12:50"})
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
    try:
        m = sinais(setup, pasta)
    except Exception as e:                                       # barras faltando nao derrubam o relatorio dos negocios feitos
        m = []
        linhas.append(f"(sinais medidos: não consegui calcular: {type(e).__name__}: {e})")
    if m:
        linhas.append("")
        linhas.append(f"SINAIS MEDIDOS (operando ou não, o que cada um teria dado com 2 contratos): {len(m)} em {len({x['dia'] for x in m})} pregão(ões).")
        for tec in sorted({x["tecnica"] or "?" for x in m}):
            t = [x for x in m if (x["tecnica"] or "?") == tec]
            linhas.append(_linha(tec + ": todos", t))
            linhas.append(_linha("   das 9h15 às 12h50", [x for x in t if x["na_janela"]]))
            linhas.append(_linha("   fita CONFIRMOU", [x for x in t if x["confirmou"] is True]))
            linhas.append(_linha("   fita NÃO confirmou", [x for x in t if x["confirmou"] is False]))
        if len(m) < 100:
            linhas.append("ATENÇÃO: com menos de 100 sinais estas diferenças ainda são acaso.")
    return "\n".join(linhas)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Resultado das entradas do robo contra a leitura da fita")
    ap.add_argument("--setup", default="niveis")
    print(relatorio(ap.parse_args().setup))
