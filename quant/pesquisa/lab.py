"""
Laboratorio de pesquisa de setups de day trade no mini-dolar, sobre 5 anos de barras de 1 minuto.

Por que existe: em 08/10/2026 uma calibracao escolhida e "provada" dentro de 2026 perdeu dinheiro em todos os outros
anos. A disciplina daqui e o remedio:

    DESCOBERTA   08/10/2021 a 31/12/2024   aqui se procura (e o unico pedaco que quem pesquisa recebe)
    VALIDACAO    2025                      so para as candidatas que passaram na descoberta
    PROVA        2026                      aberta uma vez, no fim

Tudo o que e avaliado fica em quant/saida/pesquisa5/registro.jsonl: o numero de hipoteses olhadas faz parte do
resultado (quem olha 500 ideias acha 25 "boas" por acaso).

Contas, sempre as mesmas (conservadoras):
  - a decisao e tomada no FECHAMENTO da barra i; a entrada a mercado sai na ABERTURA da barra i+1, 1 tick contra;
  - ordem parada (entrada com limite, alvo) so conta como executada se o preco PASSA do limite por 1 tick;
  - o stop vem primeiro dentro da barra; stop e saida por tempo saem a mercado, 1 tick contra; abriu alem do stop,
    sai na abertura;
  - custo de R$ 1,20 por contrato e por lado; mini-dolar: tick de 0,5 ponto, R$ 10 por ponto e por contrato;
  - uma posicao por vez; zera no fim da janela.

Uso tipico:
    from quant.pesquisa import lab
    m = lab.carregar("WDO")                       # descoberta
    s = minha_regra(m)                            # vetor do tamanho de m: +1 compra, -1 vende, 0 nada
    lab.sem_futuro(minha_regra, m)                # prova que a regra nao olha barra do futuro
    r = lab.avaliar(m, s, nome="...", familia="...", stop=8, alvo=6, tempo=20)
    print(lab.texto(r))
"""
import json
import os
import time

import numpy as np
import pandas as pd

TICK, VALOR_PONTO, TAXA = 0.5, 10.0, 1.20
PASTA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "saida", "pesquisa5")
REGISTRO = os.path.join(PASTA, "registro.jsonl")
PARTES = {"descoberta": ("2021-10-01", "2024-12-31"), "validacao": ("2025-01-01", "2025-12-31"), "prova": ("2026-01-01", "2026-12-31")}


def carregar(ativo="WDO", parte="descoberta"):
    """Barras de 1 minuto (o, h, l, c, n = numero de negocios, v = contratos), hora de Brasilia, indice sem fuso.
    No WDO ha tambem `nivel`: o fechamento da serie SEM ajuste (o preco de tela daquele dia); o, h, l, c vem da serie
    ajustada por diferenca, em que os PONTOS dentro do dia sao os verdadeiros mas o nivel antigo esta deslocado."""
    arq = os.path.join(PASTA, parte, f"{ativo}.pkl")
    if parte != "descoberta":
        with open(os.path.join(PASTA, "acessos_reserva.log"), "a", encoding="utf-8") as f:   # cada olhada fora da descoberta fica anotada
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {parte} {ativo}\n")
    return pd.read_pickle(arq)


def ativos(parte="descoberta"):
    return sorted(x[:-4] for x in os.listdir(os.path.join(PASTA, parte)) if x.endswith(".pkl"))


def dia(m):
    return np.array(m.index.date)


def hm(m):
    return np.array(m.index.strftime("%H:%M"))


def volume_relativo(m, janela=30, minimo=5, coluna="v"):
    """Volume da barra dividido pela media das `janela` barras ANTERIORES do mesmo dia."""
    base = m.groupby(dia(m))[coluna].transform(lambda s: s.shift(1).rolling(janela, min_periods=minimo).mean())
    return (m[coluna] / base).to_numpy()


def alinhar(base, outro, colunas=("o", "h", "l", "c", "v"), prefixo="x_", tolerancia_min=3):
    """As colunas de `outro` no minuto de `base` (ultimo valor ja conhecido do mesmo dia, ate `tolerancia_min` atras)."""
    o = outro[list(colunas)].copy()
    o.columns = [prefixo + c for c in colunas]
    j = pd.merge_asof(base[[]].reset_index(), o.reset_index(), on=base.index.name or "hora", direction="backward",
                      tolerance=pd.Timedelta(minutes=tolerancia_min))
    j = j.set_index(base.index.name or "hora")
    return j


def sem_futuro(regra, m, cortes=4, semente=7, folga=0):
    """Prova de que `regra(m)` nao olha o futuro: roda a regra na serie cortada em pontos sorteados e confere se os
    sinais ANTES do corte sao os mesmos da serie inteira. Devolve True ou levanta AssertionError dizendo onde difere."""
    inteiro = np.asarray(regra(m), dtype=float)
    assert len(inteiro) == len(m), "a regra tem de devolver um valor por barra"
    rng = np.random.default_rng(semente)
    for k in sorted(rng.integers(len(m) // 3, len(m) - 1, size=cortes)):
        parte = np.asarray(regra(m.iloc[:k]), dtype=float)
        a, b = np.nan_to_num(inteiro[:k - folga]), np.nan_to_num(parte[:k - folga])
        dif = np.where(a != b)[0]
        assert len(dif) == 0, f"a regra olha o futuro: cortando em {m.index[k]}, o sinal de {m.index[dif[0]]} muda ({len(dif)} barras diferentes)"
    return True


def _vetor(x, n):
    if x is None:
        return None
    if np.isscalar(x):
        return np.full(n, float(x))
    v = np.asarray(x, dtype=float)
    assert len(v) == n, "vetor de parametro com tamanho diferente do numero de barras"
    return v


def negocios(m, sinais, stop, alvo=None, tempo=None, arrasto=None, ini="09:15", ult="12:50", zerar="13:00", limite=None,
             validade=5, alvo_no_toque=False):
    """Simula. `sinais`: um valor por barra (+1, -1, 0), decidido no fechamento da barra. `stop`, `alvo`, `arrasto` em
    pontos e `tempo` em minutos: numero ou vetor por barra (vale o da barra do sinal). `limite`: vetor com o preco da
    ordem parada de entrada (NaN = a mercado), valida por `validade` minutos. Devolve um DataFrame de negocios."""
    n = len(m)
    o, h, l, c = (m[k].to_numpy(dtype=float) for k in ("o", "h", "l", "c"))
    horas, d = hm(m), dia(m)
    s = np.nan_to_num(np.asarray(sinais, dtype=float))
    assert len(s) == n
    stop, alvo, tempo, arrasto, limite = _vetor(stop, n), _vetor(alvo, n), _vetor(tempo, n), _vetor(arrasto, n), _vetor(limite, n)
    ultimo_do_dia = np.r_[d[1:] != d[:-1], True]
    cand = np.where((s != 0) & (horas >= ini) & (horas < ult) & ~ultimo_do_dia)[0]
    fora, livre = [], -1
    for i in cand:
        if i <= livre:
            continue
        lado = 1.0 if s[i] > 0 else -1.0
        j = i + 1
        if limite is not None and not np.isnan(limite[i]):               # entrada com ordem parada
            ent, pegou = float(limite[i]), False
            while j < n and d[j] == d[i] and j - i <= validade and horas[j] < ult:
                if (l[j] <= ent - TICK) if lado > 0 else (h[j] >= ent + TICK):
                    pegou = True
                    break
                j += 1
            if not pegou:
                livre = max(livre, j - 1)
                continue
            mesma_barra = True                                            # na barra da execucao so vale o que vem DEPOIS: stop conta, alvo nao
        else:
            ent, mesma_barra = o[j] + lado * TICK, False
        stp = ent - lado * stop[i]
        alv = None if alvo is None or np.isnan(alvo[i]) else ent + lado * alvo[i]
        tmp = None if tempo is None or np.isnan(tempo[i]) else int(tempo[i])
        arr = None if arrasto is None or np.isnan(arrasto[i]) else arrasto[i]
        aberta, melhor, pts, saida = j, ent, None, None
        while True:
            if j >= n or d[j] != d[i]:
                pts, saida = lado * (c[j - 1] - lado * TICK - ent), "fim do dia"
                j -= 1
                break
            if horas[j] >= zerar and j > aberta:
                pts, saida = lado * (o[j] - lado * TICK - ent), "fim da janela"
                break
            if tmp is not None and j - aberta >= tmp:
                pts, saida = lado * (o[j] - lado * TICK - ent), "tempo"
                break
            pior, bom = (l[j], h[j]) if lado > 0 else (h[j], l[j])
            if (pior <= stp) if lado > 0 else (pior >= stp):
                base = stp if (mesma_barra and j == aberta) else (min(o[j], stp) if lado > 0 else max(o[j], stp))
                pts, saida = lado * (base - lado * TICK - ent), ("stop" if arr is None or abs(stp - (ent - lado * stop[i])) < 1e-9 else "stop movel")
                break
            if alv is not None and not (mesma_barra and j == aberta):
                passou = (bom >= alv + (0 if alvo_no_toque else TICK)) if lado > 0 else (bom <= alv - (0 if alvo_no_toque else TICK))
                if passou:
                    pts, saida = lado * (alv - ent), "alvo"
                    break
            melhor = max(melhor, bom) if lado > 0 else min(melhor, bom)
            if arr is not None:
                movel = melhor - lado * arr
                if (movel > stp) if lado > 0 else (movel < stp):
                    stp = movel                                           # vale a partir da barra seguinte
            j += 1
        fora.append((d[i], horas[i], "C" if lado > 0 else "V", ent, pts, saida, j - aberta))
        livre = j
    t = pd.DataFrame(fora, columns=["dia", "hora", "lado", "entrada", "pts", "saida", "minutos"])
    return t


def medir(t, contratos=2):
    t = t.copy()
    t["res"] = t.pts * VALOR_PONTO * contratos - 2 * TAXA * contratos
    return t


def _t(x):
    x = np.asarray(x, dtype=float)
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 3 and x.std(ddof=1) > 0 else float("nan")


def resumir(t, pregoes, contratos=2):
    """Numeros de um conjunto de negocios (DataFrame de `negocios`)."""
    t = medir(t, contratos)
    if not len(t):
        return {"n": 0}
    dt = pd.to_datetime(t.dia)
    sem = dt.dt.year.astype(str) + "S" + ((dt.dt.month > 6) + 1).astype(str)
    por_sem = t.groupby(sem.values).res.agg(["count", "mean"])
    por_ano = t.groupby(dt.dt.year.values).res.agg(["count", "mean", lambda v: (v > 0).mean() * 100])
    return {"n": int(len(t)), "por_pregao": round(len(t) / max(pregoes, 1), 2), "acerto": round(float((t.res > 0).mean() * 100), 1),
            "rs_por_negocio": round(float(t.res.mean()), 2), "t": round(_t(t.res), 2), "pts_brutos": round(float(t.pts.mean()), 3),
            "ganho_medio": round(float(t.res[t.res > 0].mean()), 1) if (t.res > 0).any() else None,
            "perda_media": round(float(t.res[t.res <= 0].mean()), 1) if (t.res <= 0).any() else None,
            "total": round(float(t.res.sum()), 0), "minutos": round(float(t.minutos.mean()), 1),
            "semestres_positivos": f"{int((por_sem['mean'] > 0).sum())} de {len(por_sem)}",
            "por_semestre": {k: [int(a), round(float(b), 1)] for k, (a, b) in por_sem.iterrows()},
            "por_ano": {int(k): [int(a), round(float(b), 1), round(float(c_), 0)] for k, (a, b, c_) in por_ano.iterrows()},
            "por_lado": {k: [int(len(g)), round(float(g.res.mean()), 1)] for k, g in t.groupby("lado")},
            "saidas": t.saida.value_counts().to_dict()}


def avaliar(m, sinais, nome, familia="", stop=8.0, alvo=None, tempo=None, arrasto=None, ini="09:15", ult="12:50", zerar="13:00",
            limite=None, validade=5, alvo_no_toque=False, contratos=2, registrar=True, extra=None):
    """Simula e resume. Grava uma linha no registro (toda hipotese olhada conta). Devolve o resumo, com `negocios`."""
    t = negocios(m, sinais, stop, alvo, tempo, arrasto, ini, ult, zerar, limite, validade, alvo_no_toque)
    pregoes = len(set(dia(m)))
    r = resumir(t, pregoes, contratos)
    r.update(nome=nome, familia=familia, janela=f"{ini}-{ult}", pregoes=pregoes, de=str(m.index[0].date()), ate=str(m.index[-1].date()))
    if registrar:
        os.makedirs(PASTA, exist_ok=True)
        linha = {k: v for k, v in r.items()}
        linha.update(quando=time.strftime("%Y-%m-%d %H:%M:%S"), extra=extra,
                     saida={"stop": None if stop is None or not np.isscalar(stop) else stop, "alvo": alvo if np.isscalar(alvo) or alvo is None else "vetor",
                            "tempo": tempo if np.isscalar(tempo) or tempo is None else "vetor", "arrasto": arrasto if np.isscalar(arrasto) or arrasto is None else "vetor"})
        with open(REGISTRO, "a", encoding="utf-8") as f:
            f.write(json.dumps(linha, ensure_ascii=False, default=str) + "\n")
    r["negocios"] = t
    return r


def evento(m, mascara, lado, horizontes=(1, 3, 5, 10, 20, 30, 60), nome="", familia="", ini="09:15", ult="12:50", registrar=True):
    """Estudo de evento, SEM custo: para cada barra marcada, o retorno em pontos por contrato da abertura da barra
    seguinte ate o fechamento k minutos depois (dentro do mesmo dia), no sentido de `lado` (+1/-1, numero ou vetor).
    Devolve uma tabela: horizonte x (n, media, t, % positivo) e a media por ano."""
    n = len(m)
    o, c = m["o"].to_numpy(dtype=float), m["c"].to_numpy(dtype=float)
    d, horas = dia(m), hm(m)
    lado = _vetor(lado, n)
    idx = np.where(np.asarray(mascara, dtype=bool) & (horas >= ini) & (horas < ult))[0]
    idx = idx[idx + 1 < n]
    idx = idx[d[idx + 1] == d[idx]]
    linhas = []
    anos = pd.to_datetime(pd.Series(d[idx])).dt.year.to_numpy() if len(idx) else np.array([])
    for k in horizontes:
        fim = np.minimum(idx + k, n - 1)
        ok = d[fim] == d[idx]
        r = lado[idx[ok]] * (c[fim[ok]] - o[idx[ok] + 1])
        linha = {"min": k, "n": int(len(r)), "media_pts": round(float(r.mean()), 3) if len(r) else np.nan, "t": round(_t(r), 2),
                 "positivo_%": round(float((r > 0).mean() * 100), 1) if len(r) else np.nan}
        for a in sorted(set(anos)):
            x = r[anos[ok] == a]
            linha[str(a)] = round(float(x.mean()), 2) if len(x) else np.nan
        linhas.append(linha)
    tab = pd.DataFrame(linhas)
    if registrar and nome:
        os.makedirs(PASTA, exist_ok=True)
        with open(REGISTRO, "a", encoding="utf-8") as f:
            f.write(json.dumps({"tipo": "evento", "nome": nome, "familia": familia, "quando": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "tabela": tab.to_dict("records")}, ensure_ascii=False, default=str) + "\n")
    return tab


def texto(r):
    """O resumo em uma linha, mais os semestres."""
    if not r.get("n"):
        return f"{r.get('nome', '')}: sem negocios"
    return (f"{r['nome']}: n {r['n']} ({r['por_pregao']}/pregao) acerto {r['acerto']}% R$/neg {r['rs_por_negocio']:+.2f} (t {r['t']:+.1f}) "
            f"pts brutos {r['pts_brutos']:+.2f} ganho {r['ganho_medio']} perda {r['perda_media']} total {r['total']:+.0f} | "
            f"semestres positivos {r['semestres_positivos']} | por ano {r['por_ano']} | lado {r['por_lado']} | saidas {r['saidas']}")


def candidata(r, n_min=200, t_min=3.0, semestres_min=5):
    """O criterio da descoberta: resultado positivo depois de custo com t >= 3 (ha muitas hipoteses na mesa), pelo
    menos 200 negocios e 5 dos 7 semestres positivos."""
    if not r.get("n") or r["n"] < n_min:
        return False
    pos = int(str(r["semestres_positivos"]).split(" de ")[0])
    return bool(r["rs_por_negocio"] > 0 and r["t"] >= t_min and pos >= semestres_min)
