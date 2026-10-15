"""
Revisao do pregao: onde o robo errou e o que muda amanha. Pedido do Douglas em 14/10/2026, 20h: "Todo pregao ele tem que
rever a estrategia e ver onde ele errou para nao cometer o mesmo erro e no dia seguinte comecar de novo para tentar vencer."

Roda na rotina da noite (quant/pesquisa/noite.py), ANTES do protocolo. Para cada negocio feito e cada sinal so medido (ou
barrado) do dia, diz o que aconteceu e em que categoria cai:

  (a) REGRA SEGUIDA, RESULTADO DENTRO DO ESPERADO: o resultado e comparado com a distribuicao historica da propria regra
      (quant/pesquisa/distribuicoes.json, 2021-2025, com os parametros vivos): percentil do resultado, se a sequencia de
      perdas e normal e se a media ao vivo destoa do historico. Perda dentro da distribuicao NAO e erro da regra.
  (b) FALHA DE EXECUCAO OU DE DADO: MetaTrader reaberto ou caido, robo sem cotacao (cego), barra faltando, sinal que devia
      entrar e nao entrou, saida fora do preco da barra, prova viva sem o pregao. Vira conserto no codigo, com teste, no
      mesmo dia: quem conserta e a rotina da noite, que registra o conserto em quant/saida/revisao/consertos.jsonl.
  (c) FORA DO CONTEXTO: a regra disparou num contexto (tamanho da reacao, tipo do dia, lado, horario, deriva antes do dado)
      em que ela nao tem vantagem no historico. Vira HIPOTESE, nunca filtro direto.
  (d) A SAIDA CUSTOU CARO: as saidas ja testadas (alvo, stop movel, tempo, stop) rodadas no negocio do dia, contra o
      ranking delas no historico (quant/saida/pesquisa5/montecarlo/dado_saida.json).

Tudo vai para o CADERNO DE ERROS (quant/saida/revisao/caderno_de_erros.jsonl, so acumula; caderno_de_erros.md e a leitura).
Quando um padrao de (a), (c) ou (d) aparece em um SEGUNDO pregao, a revisao abre um item em quant/pesquisa/FILA.md, para ser
testado nos 5 anos de barras de 1 minuto com descoberta, validacao e prova (METODO.md, lab.py). Regra so muda se passar.
Falha (b) repetida vira a primeira linha da mensagem: conserto que nao resolveu.

Saidas: quant/saida/revisao/<dia>.json e .md; o bloco "revisao" do quant.json da area QUANT (card "Revisao do pregao: onde
errou e o que muda amanha"); o robo publica a ultima revisao no quant.json enquanto roda.

Uso: python -m quant.pesquisa.revisao [--dia AAAA-MM-DD] [--sem-metatrader] [--ensaio]
"""
import argparse
import glob
import json
import os
import re
import subprocess

import numpy as np
import pandas as pd

from quant.comum import agora_brt, garantir_dir, gravar_atomico, ler_json
from quant.daytrade import barras as br
from quant.daytrade import medir
from quant.daytrade.robo import DIR_DT

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIR_REV = os.path.join(os.path.dirname(DIR_DT), "revisao")
ARQ_CADERNO = os.path.join(DIR_REV, "caderno_de_erros.jsonl")
ARQ_CONSERTOS = os.path.join(DIR_REV, "consertos.jsonl")
ARQ_DIST = os.path.join(RAIZ, "quant", "pesquisa", "distribuicoes.json")
ARQ_FILA = os.path.join(RAIZ, "quant", "pesquisa", "FILA.md")
ARQ_SAIDAS_DADO = os.path.join(os.path.dirname(DIR_DT), "pesquisa5", "montecarlo", "dado_saida.json")
TELAS = [os.path.expanduser(x) for x in os.environ.get(
    "QUANT_SAIDA_TELA", "~/Desktop/terminal-artefato/web/d/x/quant.json:~/Desktop/terminal-artefato/cache/out/pagina/quant.json").split(":") if x]

CATEGORIAS = {"a": "dentro do esperado", "b": "falha de execução ou de dado", "c": "fora do contexto", "d": "a saída custou caro"}
DADO = "reversão do dado"
VALOR_PONTO, TICK, CUSTO_LADO = 10.0, 0.5, 1.20
INICIO, ULTIMA = "09:15", "18:10"       # a janela do robo (estrategia_fluxo/modo_robo.json); a pausa do dado e a do dia (pausa_do_dia)
PREGAO = ("09:00", "18:20")
CEGO_MIN = 5                     # minutos seguidos sem barra do robo, com o servidor negociando, para contar como "cego"
SAIDAS_TESTADAS = {              # as saidas ja testadas na descoberta (estudo de 12/10/2026, familia dado_saida)
    "alvo 10": dict(alvo=10.0), "alvo 15": dict(alvo=15.0), "alvo 20": dict(alvo=20.0), "alvo 30": dict(alvo=30.0),
    "arrasto 15": dict(arrasto=15.0), "arrasto 25": dict(arrasto=25.0), "tempo 60": dict(tempo=60), "tempo 90": dict(tempo=90),
    "stop 30": dict(stop=30.0)}
SAIDA_CARA_RS = 100.0            # a saida "custou caro" quando uma alternativa testada daria pelo menos isto a mais no dia


# ── leitura do dia ───────────────────────────────────────────
def _jsonl(caminho):
    try:
        with open(caminho, encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]
    except (OSError, ValueError):
        return []


def ler_dia(dia, pasta=DIR_DT, setup="niveis"):
    est = ler_json(os.path.join(pasta, dia, f"estado_{setup}.json"), padrao=None) or {}
    return est, _jsonl(os.path.join(pasta, dia, f"sinais_{setup}.jsonl"))


def negocios_do_dia(est):
    """Parciais e saida somadas por negocio (ativo + hora da entrada)."""
    fora = {}
    for o in est.get("operacoes") or []:
        k = (o.get("ativo"), o.get("hora_entrada"))
        n = fora.setdefault(k, {"ativo": o.get("ativo"), "tecnica": o.get("tecnica"), "lado": o.get("lado"), "entrada": o.get("entrada"),
                                "hora_entrada": o.get("hora_entrada"), "contratos": 0, "resultado": 0.0, "pernas": []})
        n["contratos"] += int(o.get("contratos") or 0)
        n["resultado"] += float(o.get("resultado") or 0.0)
        n["pernas"].append(o)
        if o.get("tipo") == "saida":
            n.update(saida=o.get("saida"), hora_saida=o.get("hora_saida"), motivo=o.get("motivo"), nome_nivel=o.get("nome_nivel"))
    return [dict(n, resultado=round(n["resultado"], 2)) for n in fora.values() if n.get("motivo")]


def historico_ao_vivo(tecnica, ate_dia, pasta=DIR_DT, setup="niveis"):
    """Resultados dos negocios FEITOS pela tecnica, em ordem, de todos os pregoes ate `ate_dia` (inclusive)."""
    fora = []
    for d in sorted(glob.glob(os.path.join(pasta, "20??-??-??"))):
        dia = os.path.basename(d)
        if dia > ate_dia:
            continue
        est, _ = ler_dia(dia, pasta, setup)
        fora += [(dia, n["resultado"]) for n in negocios_do_dia(est) if n["tecnica"] == tecnica]
    return fora


def _num(v, casas):
    return f"{abs(float(v)):,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _rs(v, casas=2):
    """R$ no formato brasileiro, com o sinal na frente: -R$ 154,80; +R$ 100."""
    return ("-" if v < 0 else "+" if v > 0 else "") + "R$ " + _num(v, casas)


def _pt(v, casas=1):
    """Preco ou pontos no formato brasileiro: 5.054,0."""
    return "-" if v is None else ("-" if float(v) < 0 else "") + _num(v, casas)


def _hm(x):
    return str(x or "")[:5]


def _seg(h):
    p = str(h).split(":")
    return int(p[0]) * 3600 + int(p[1]) * 60 + (int(p[2]) if len(p) > 2 else 0)


def pausa_do_dia(dia):
    """A pausa do dado do pregao revisado: 9h28-9h40 no horario de verao dos EUA, 10h28-10h40 fora (15/10/2026, achado 81)."""
    return br.pausa_do_dado(pd.Timestamp(dia).date())


# ── o Mac dormindo ───────────────────────────────────────────
RX_PMSET = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) [+-]\d{4} (Sleep|Wake|DarkWake)\s{2,}")


def sono_do_mac(dia, texto=None):
    """Os trechos do dia em que o Mac dormiu, pelo registro de energia do macOS (`pmset -g log`): de cada "Sleep" ate o proximo "Wake"
    de verdade. O "DarkWake" (2 a 5 s de manutencao, com a tampa fechada) nao conta como acordado. [(inicio, fim)] em "HH:MM".
    Em 15/10/2026 o Mac dormiu na bateria das 8h00 as 9h24 e a revisao contaria o trecho como falha do MetaTrader (achado 42)."""
    if texto is None:
        try:
            texto = subprocess.run(["pmset", "-g", "log"], capture_output=True, text=True, timeout=60).stdout
        except Exception:                                        # sem o registro, a revisao segue sem saber do sono
            return []
    trechos, desde = [], None
    for ln in (texto or "").splitlines():
        m = RX_PMSET.match(ln)
        if not m:
            continue
        t, tipo = pd.Timestamp(m.group(1)), m.group(2)
        if tipo == "Sleep" and desde is None:
            desde = t
        elif tipo == "Wake" and desde is not None:
            trechos.append((desde, t))
            desde = None
    d0 = pd.Timestamp(dia)
    d1 = d0 + pd.Timedelta(days=1)
    if desde is not None:
        trechos.append((desde, d1))
    return [(max(a, d0).strftime("%H:%M"), (min(b, d1 - pd.Timedelta(minutes=1))).strftime("%H:%M")) for a, b in trechos if a < d1 and b > d0]


def fracao_dormindo(inicio, fim, sono):
    """Que fracao do intervalo [inicio, fim] ("HH:MM") o Mac passou dormindo."""
    a, b = _seg(inicio) / 60, _seg(fim) / 60
    if b <= a:
        b = a + 1
    dormido = sum(max(0.0, min(b, _seg(y) / 60) - max(a, _seg(x) / 60)) for x, y in sono)
    return dormido / (b - a)


# ── barras ───────────────────────────────────────────────────
def barras_do_servidor(dia, simbolo="WDO$N", quantas=3000, pasta_mt5=None, espera_s=120):
    """Barras de 1 minuto do pregao pelo historico do MetaTrader (o servidor guarda o dia inteiro, inclusive as horas em que o
    robo ficou cego). O rotulo leva a data e a hora do pedido: um pedido feito com o pregao aberto nunca e reaproveitado de noite."""
    from quant.daytrade import fluxo as fx
    from quant.pesquisa import prova_viva as pv
    agora = agora_brt()
    base = 900 if simbolo.startswith("WDO") else 800
    rotulo = int(pd.Timestamp(dia).strftime("%y%m%d")) * 1000 + base + agora.hour
    b = pv.pedir_barras(simbolo, quantas, pasta_mt5 or fx.PASTA_MT5, espera_s=espera_s, rotulo=rotulo)
    return b


def barras_do_robo(dia, pasta=DIR_DT, ativo="WDOFUT"):
    """Os minutos que o proprio robo montou da fita naquele dia (m1_<ativo>.csv): onde falta minuto, o robo estava cego."""
    arq = os.path.join(pasta, f"m1_{ativo}.csv")
    try:
        p = pd.read_csv(arq, sep=";", names=["hora", "a", "b", "c", "d", "e"], parse_dates=["hora"])
    except (OSError, ValueError):
        return pd.DataFrame()
    p = p[p.hora.dt.strftime("%Y-%m-%d") == dia].dropna(subset=["a"]).drop_duplicates("hora", keep="last").set_index("hora").sort_index()
    inteira = p["d"].notna()
    return pd.DataFrame({"o": p["a"], "h": p["b"].where(inteira, p["a"]), "l": p["c"].where(inteira, p["a"]), "c": p["d"].where(inteira, p["a"])})


def intervalos_cegos(servidor, robo, minimo=CEGO_MIN, janela=PREGAO):
    """[(inicio, fim, minutos)] em que o servidor negociou e o robo nao montou barra (minutos seguidos >= `minimo`)."""
    if servidor is None or not len(servidor):
        return []
    s = servidor[(servidor.index.strftime("%H:%M") >= janela[0]) & (servidor.index.strftime("%H:%M") < janela[1])]
    falta = ~s.index.isin(robo.index) if len(robo) else np.ones(len(s), dtype=bool)
    fora, ini, ant = [], None, None
    for t, f in zip(s.index, falta):
        if f and ini is None:
            ini = t
        if not f and ini is not None:
            fora.append((ini, ant))
            ini = None
        ant = t
    if ini is not None:
        fora.append((ini, ant))
    return [(a.strftime("%H:%M"), b.strftime("%H:%M"), int((b - a).total_seconds() // 60) + 1) for a, b in fora
            if (b - a).total_seconds() // 60 + 1 >= minimo]


# ── a regua historica ────────────────────────────────────────
def distribuicoes(arq=ARQ_DIST):
    return (ler_json(arq, padrao=None) or {}).get("regras") or {}


def percentil(valor, regra):
    """Percentil do resultado na distribuicao historica (0 a 100). Com a lista inteira, exato; senao, pelos quantis."""
    lista = regra.get("lista")
    if lista:
        return round(float(np.mean(np.asarray(lista) <= valor + 1e-9) * 100), 0)
    q = regra.get("quantis") or {}
    if not q:
        return None
    ps = sorted((float(k), float(v)) for k, v in q.items())
    xs, ys = [v for _k, v in ps], [k for k, _v in ps]
    return round(float(np.interp(valor, xs, ys, left=0.0, right=100.0)), 0)


def sequencia_final(resultados):
    """Quantas perdas seguidas no fim da lista."""
    k = 0
    for r in reversed(list(resultados)):
        if r > 0:
            break
        k += 1
    return k


def julgar_sequencia(k, regra):
    if k <= 0:
        return None
    seq = regra.get("sequencias") or {}
    freq = (seq.get("freq_k") or {}).get(str(min(k, 10)))
    maior = seq.get("maior")
    normal = maior is None or k <= maior
    return {"perdas_seguidas": k, "freq": freq, "maior_historica": maior, "normal": bool(normal)}


def julgar_ao_vivo(resultados, regra, n_min=10):
    """Media ao vivo contra a historica: z = (media ao vivo - media historica) / (desvio historico / raiz de n)."""
    r = np.asarray(resultados, dtype=float)
    if len(r) < n_min or not regra.get("desvio"):
        return None
    z = (r.mean() - regra["media"]) / (regra["desvio"] / np.sqrt(len(r)))
    return {"n": int(len(r)), "media": round(float(r.mean()), 2), "media_historica": regra["media"], "z": round(float(z), 2), "pior": bool(z <= -2.0)}


# ── (d) saidas alternativas no negocio do dia ────────────────
def simular_saida(barras, t0, entrada, lado, stop=40.0, alvo=None, tempo=120, arrasto=None, contratos=2):
    """O negocio do dia com outra saida, com as contas do laboratorio: stop primeiro na barra (sai 1 tick pior), alvo so se
    passar 1 tick, tempo sai na abertura da barra (1 tick pior), arrasto vale da barra seguinte. Comeca na barra da entrada."""
    s = 1.0 if lado == "C" else -1.0
    d = barras[(barras.index >= t0) & (barras.index.date == t0.date())]
    if not len(d):
        return None
    stp, alv, melhor = entrada - s * stop, (None if alvo is None else entrada + s * alvo), entrada
    limite = None if tempo is None else t0 + pd.Timedelta(minutes=int(tempo))
    pts, motivo = None, None
    for t, o, h, l, c in zip(d.index, d.o.to_numpy(), d.h.to_numpy(), d.l.to_numpy(), d.c.to_numpy()):
        if limite is not None and t >= limite:
            pts, motivo = s * ((o - s * TICK) - entrada), "tempo"
            break
        pior, bom = (l, h) if s > 0 else (h, l)
        if (pior <= stp) if s > 0 else (pior >= stp):
            base = min(o, stp) if s > 0 else max(o, stp)
            pts, motivo = s * ((base - s * TICK) - entrada), "stop"
            break
        if alv is not None and ((bom >= alv + TICK) if s > 0 else (bom <= alv - TICK)):
            pts, motivo = s * (alv - entrada), "alvo"
            break
        melhor = max(melhor, bom) if s > 0 else min(melhor, bom)
        if arrasto is not None:
            mv = melhor - s * arrasto
            stp = max(stp, mv) if s > 0 else min(stp, mv)
    if pts is None:
        c = float(d.c.iloc[-1])
        pts, motivo = s * ((c - s * TICK) - entrada), "fim do dia"
    return {"pontos": round(float(pts), 2), "resultado": round(float(pts) * VALOR_PONTO * contratos - 2 * CUSTO_LADO * contratos, 2), "motivo": motivo}


def caminho(barras, t0, t1, entrada, lado):
    """Melhor e pior ponto a favor enquanto a posicao esteve aberta."""
    d = barras[(barras.index >= t0) & (barras.index < t1)]
    if not len(d):
        return None, None
    s = 1.0 if lado == "C" else -1.0
    fav = (d.h.max() - entrada) if s > 0 else (entrada - d.l.min())
    con = (d.l.min() - entrada) if s > 0 else (entrada - d.h.max())
    return round(float(fav), 1), round(float(con), 1)


def saidas_do_dia(barras, n, dia):
    """{nome: resultado} da saida congelada ("base") e de cada saida testada, a partir da entrada real do negocio."""
    t0 = pd.Timestamp(f"{dia} {n['hora_entrada']}").floor("min")
    base = dict(stop=40.0, alvo=None, tempo=120, arrasto=None)
    fora = {}
    for nome, kw in dict(base={}, **SAIDAS_TESTADAS).items():
        r = simular_saida(barras, t0, float(n["entrada"]), n["lado"], contratos=int(n["contratos"] or 2), **dict(base, **kw))
        if r:
            fora[nome] = r
    return fora


def ranking_historico_das_saidas(arq=ARQ_SAIDAS_DADO):
    d = (ler_json(arq, padrao=None) or {}).get("descoberta") or {}
    return {k.split(" (")[0]: v.get("rs_por_negocio") for k, v in d.items()}


# ── (c) contexto ─────────────────────────────────────────────
def _faixa(valor, cortes, rotulos):
    for (a, b), r in zip(zip(cortes[:-1], cortes[1:]), rotulos):
        if a < valor <= b:
            return r
    return None


def contexto_do_dado(medidas, regra):
    """Os rotulos do sinal do dado contra o historico de cada faixa (descoberta e 2025). Devolve [(campo, faixa, desc, val, fora)]."""
    cd, c25 = regra.get("contexto_descoberta") or {}, regra.get("contexto_2025") or {}
    mv = abs(float(medidas.get("movimento") or 0.0))
    hora = "09:31" if str(medidas.get("hora_dado") or "").startswith("09") else "10:31"
    deriva = medidas.get("deriva_pre_dado")
    campos = [("reacao", _faixa(mv, [3, 6, 10, 999], ["3-6", "6-10", ">10"])), ("tipo_do_dia", medidas.get("tipo_do_dia")),
              ("lado", medidas.get("lado")), ("hora", hora),
              ("deriva_pre_dado", None if deriva is None else _faixa(float(deriva), [-999, -10, -3, 3, 10, 999], ["< -10", "-10 a -3", "-3 a 3", "3 a 10", "> 10"]))]
    fora = []
    for campo, faixa in campos:
        if faixa is None:
            continue
        a, b = (cd.get(campo) or {}).get(faixa), (c25.get(campo) or {}).get(faixa)
        if not a:
            continue
        sem_vantagem = a["media"] <= 0 or ((a.get("t") or 0) < 1.0 and b is not None and b.get("n", 0) >= 5 and b["media"] < 0)
        fora.append({"campo": campo, "faixa": faixa, "descoberta": a, "ano_2025": b, "fora": bool(sem_vantagem)})
    return fora


# ── sinais que nao entraram ──────────────────────────────────
def motivo_sem_entrada(sinal, entradas, negocios, est, dia):
    """Por que um sinal da regra que opera nao virou entrada (as mesmas portas de estrategia_fluxo.passo)."""
    h = sinal.get("hora") or ""
    hm, seg = _hm(h), _seg(h)
    for e in entradas:
        if e.get("tecnica") == sinal.get("tecnica") and e.get("ativo", sinal.get("ativo")) == sinal.get("ativo") \
                and abs(_seg(e.get("hora") or "00:00:00") - seg) <= 15:
            return "entrou", None
    # o robo anota o motivo desde 15/10/2026, inclusive no sinal da regra que opera e caiu na reserva do dado (gravado com
    # opera=False): antes ele era contado como "so medido" e a revisao dizia que a regra estava desligada (achado 44)
    if sinal.get("bloqueio"):
        return str(sinal["bloqueio"]).split(" (")[0], None
    if not sinal.get("opera"):
        return "só medido", None
    if hm < INICIO:
        return "antes da janela", f"sinal das {hm} marcado como 'opera', mas a janela de entradas só abre às {INICIO}"
    if hm >= ULTIMA:
        return "depois da última entrada", None
    for n in negocios:
        if _seg(n["hora_entrada"]) <= seg < _seg(n.get("hora_saida") or "23:59:59"):
            return "posição aberta", None                        # uma posicao por vez: e a regra, nao falha
    pausa = pausa_do_dia(dia)
    if pausa[0] <= hm < pausa[1] and sinal.get("tecnica") != DADO:
        return "pausa do dado", None
    for x in est.get("diario") or []:
        if x.get("tipo") == "trava" and _seg(x.get("hora") or "23:59") <= seg:
            return "trava do dia", None
    for n in negocios:
        fim = _seg(n.get("hora_saida") or "00:00:00")
        if 0 <= seg - fim < (180 if n["resultado"] <= 0 else 120):
            return "espera depois da saída", None
    return "sem motivo conhecido", f"sinal das {hm} ({sinal.get('tecnica')}) devia entrar e não entrou (spread aberto ou cotação velha?)"


# ── o caderno de erros ───────────────────────────────────────
def ler_caderno(arq=ARQ_CADERNO):
    return _jsonl(arq)


def dias_da_chave(caderno, chave):
    return sorted({x["dia"] for x in caderno if x.get("chave") == chave})


def _numero_novo(texto):
    nums = [int(x) for x in re.findall(r"(?m)^(\d+)\. ", texto)]
    return (max(nums) + 1) if nums else 1


def abrir_na_fila(item, dias, arq=ARQ_FILA):
    """Abre um item em "A testar" (antes de "## Testadas") para o padrao repetido. Nao duplica: se a chave ja esta na fila,
    devolve o numero que ja existe."""
    try:
        with open(arq, encoding="utf-8") as f:
            texto = f.read()
    except OSError:
        return None
    marca = f"[revisao: {item['chave']}]"
    achado = re.search(r"(?m)^(\d+)\. .*" + re.escape(marca), texto)
    if achado:
        return int(achado.group(1))
    n = _numero_novo(texto)
    linha = (f"{n}. {marca} {item['hipotese']} Apareceu em {len(dias)} pregoes ({', '.join(dias)}). Teste: lab.avaliar na descoberta "
             f"(10/2021-12/2024) com a regra congelada e o filtro/saida da hipotese; candidata (t >= 3, n >= 200, 5 de 7 semestres) vai a "
             f"validacao (2025); 2026 nao escolhe parametro. So muda a regra se passar e com o 'pode' do Douglas.\n\n")
    pos = texto.find("## Testadas")
    texto = (texto[:pos] + linha + texto[pos:]) if pos >= 0 else (texto + "\n" + linha)
    gravar_atomico(arq, texto)
    return n


def caderno_md(caderno, consertos):
    linhas = ["# Caderno de erros do robo de day trade (simulacao)", "",
              "Escrito pela revisao do pregao (quant/pesquisa/revisao.py) toda noite. So acumula. Categorias: (a) dentro do esperado, "
              "(b) falha de execucao ou de dado, (c) fora do contexto, (d) a saida custou caro.", "",
              "| Dia | Cat. | Regra | O que foi | Acao |", "|---|---|---|---|---|"]
    for x in caderno[-200:]:
        linhas.append(f"| {x['dia']} | {x['categoria']} | {x.get('tecnica') or '-'} | {x['texto']} | {x.get('acao') or '-'} |")
    rep = {}
    for x in caderno:
        rep.setdefault(x["chave"], set()).add(x["dia"])
    repetidos = {k: sorted(v) for k, v in rep.items() if len(v) >= 2}
    linhas += ["", "## Padroes que se repetiram", ""]
    linhas += [f"- `{k}`: {len(v)} pregoes ({', '.join(v)})" for k, v in sorted(repetidos.items())] or ["Nenhum ainda."]
    linhas += ["", "## Consertos registrados", ""]
    linhas += [f"- {c.get('quando', '')[:16]} `{c.get('chave')}`: {c.get('texto')} (teste: {c.get('teste') or '-'}; commit {c.get('commit') or '-'})"
               for c in consertos] or ["Nenhum ainda."]
    return "\n".join(linhas) + "\n"


# ── a revisao ────────────────────────────────────────────────
def _item(dia, cat, chave, tecnica, texto, acao=None, valor=None, **extra):
    return dict(dia=dia, categoria=cat, rotulo=CATEGORIAS[cat], chave=chave, tecnica=tecnica, texto=texto, acao=acao,
                valor_rs=None if valor is None else round(float(valor), 2), **extra)


def revisar(dia=None, pasta=DIR_DT, setup="niveis", servidor=None, pedir_servidor=True, dist=None, consertos=None, sono=None,
            registro=None, ativos_robo=None):
    """Monta a revisao de um pregao. `servidor`: barras de 1 minuto do dia (se None e `pedir_servidor`, pede ao MetaTrader;
    sem elas, usa as do robo). `sono`: os trechos em que o Mac dormiu (None: le o `pmset -g log`). `registro`: as regras do
    laboratorio (None: quant/pesquisa/setups.json). `ativos_robo`: os contratos que o robo percorria (None: ativos_robo.json).
    Nao grava nada (ver `gravar`)."""
    dia = dia or agora_brt().strftime("%Y-%m-%d")
    dist = distribuicoes() if dist is None else dist
    consertos = _jsonl(ARQ_CONSERTOS) if consertos is None else consertos
    sono = sono_do_mac(dia) if sono is None else sono
    est, linhas = ler_dia(dia, pasta, setup)
    negocios = negocios_do_dia(est)
    entradas = [x for x in linhas if x.get("tipo") == "entrada"]
    sinais = [x for x in linhas if x.get("tipo") == "sinal"]
    itens, lacunas, por_regra = [], [], {}
    robo = barras_do_robo(dia, pasta)
    if servidor is None and pedir_servidor:
        try:
            todas = barras_do_servidor(dia)
            servidor = None if todas is None else todas[todas.index.strftime("%Y-%m-%d") == dia]
        except Exception as e:
            lacunas.append(f"barras do servidor do MetaTrader indisponíveis ({type(e).__name__}: {e})")
    if servidor is None or not len(servidor):
        if pedir_servidor:
            lacunas.append("sem as barras do servidor: a revisão usou só os minutos que o robô montou (as horas cegas ficam sem conta)")
        servidor = robo
    barras = servidor
    # cada contrato com as suas barras: o mini-indice (regra do laboratorio, achado 10) nas que o robo montou dele
    por_ativo = {"WDOFUT": barras}

    def barras_de(ativo):
        if (ativo or "WDOFUT") not in por_ativo:
            por_ativo[ativo] = barras_do_robo(dia, pasta, ativo)
        return por_ativo[ativo or "WDOFUT"]

    # (b) o robo ficou cego? o MetaTrader foi reaberto?
    reab = [x for x in est.get("diario") or [] if x.get("tipo") == "feed" and "Reabrindo" in (x.get("texto") or "")]
    if len(reab) >= 3:
        itens.append(_item(dia, "b", "b:metatrader:reaberturas", None,
                           f"o MetaTrader foi fechado e reaberto {len(reab)} vezes por cotação em rajadas ({', '.join(_hm(x['hora']) for x in reab)})",
                           "conferir a conexão da XP; cada reabertura deixa o robô uns 40 s sem preço"))
    cegos = [(a, b, m, None) for a, b, m in intervalos_cegos(servidor, robo)] if servidor is not robo else []
    if not len(robo) and len(est.get("curva") or []):
        lacunas.append("o robô não gravou barra nenhuma da fita hoje")
    for x in est.get("cegueira") or []:                          # o proprio robo anota (desde 15/10/2026): [ini, fim, min(, motivo)]
        if not isinstance(x, (list, tuple)) or len(x) < 3:
            continue
        motivo = x[3] if len(x) > 3 else None
        k = next((i for i, c in enumerate(cegos) if c[0] == x[0]), None)
        if k is None:
            cegos.append((x[0], x[1], int(x[2]), motivo))
        elif motivo:
            cegos[k] = cegos[k][:3] + (motivo,)
    # o Mac dormindo nao e falha do MetaTrader: o robo nao roda enquanto ele dorme (15/10/2026, achado 42)
    cegos = [(a, b, m, "mac_dormindo" if mot == "mac_dormindo" or fracao_dormindo(a, b, sono) >= 0.5 else mot) for a, b, m, mot in cegos]
    for a, b, mins, motivo in cegos:
        if motivo == "mac_dormindo":
            itens.append(_item(dia, "b", "b:mac:dormiu", None,
                               f"o Mac estava dormindo de {a} a {b} ({mins} minutos; tampa fechada ou na bateria): o robô não roda enquanto ele "
                               "dorme e não leu sinal nenhum nesse tempo. Não foi o MetaTrader",
                               "no pregão, deixar o Mac na tomada e com a tampa aberta", inicio=a, fim=b, minutos=mins))
            continue
        itens.append(_item(dia, "b", "b:metatrader:cego", None, f"o robô ficou sem cotação de {a} a {b} ({mins} minutos): não leu sinal nenhum nesse tempo",
                           "conserto: o robô volta a tentar abrir o MetaTrader quando foi ele que fechou e a XP não voltou (14/10/2026)",
                           inicio=a, fim=b, minutos=mins))

    # (a), (c), (d) por negocio feito
    for n in negocios:
        tec = n["tecnica"]
        regra = dist.get(tec) or {}
        pr = por_regra.setdefault(tec, {"tecnica": tec, "operados": 0, "resultado": 0.0, "sinais": 0, "soma_sinais": 0.0, "negocios": []})
        pr["operados"] += 1
        pr["resultado"] = round(pr["resultado"] + n["resultado"], 2)
        p = percentil(n["resultado"], regra) if regra.get("n") else None
        t0 = pd.Timestamp(f"{dia} {n['hora_entrada']}").floor("min")
        t1 = pd.Timestamp(f"{dia} {n.get('hora_saida') or n['hora_entrada']}").floor("min") + pd.Timedelta(seconds=60)
        bn = barras_de(n.get("ativo"))
        melhor, pior = caminho(bn, t0, t1, float(n["entrada"]), n["lado"]) if len(bn) else (None, None)
        resumo = (f"{tec}: {'vendeu' if n['lado'] == 'V' else 'comprou'} {n['contratos']} a {_pt(n['entrada'])} às {n['hora_entrada'][:5]}, saiu por "
                  f"{n['motivo']} às {_hm(n.get('hora_saida'))} a {_pt(n.get('saida'))}: {_rs(n['resultado'])}"
                  + ("" if melhor is None else f" (andou até {_pt(melhor)} pontos a favor e {_pt(abs(pior))} contra)"))
        neg = {"hora": n["hora_entrada"][:5], "lado": n["lado"], "resultado": n["resultado"], "motivo": n["motivo"], "percentil": p,
               "melhor_pts": melhor, "pior_pts": pior, "texto": resumo}
        pr["negocios"].append(neg)
        if regra.get("n"):
            esperado = f"média histórica {_rs(regra['media'], 0)} por negócio, acerto {regra['acerto']:.0f}% ({regra['n']} negócios, 2021-2025)"
            if n["resultado"] <= 0:
                txt = (f"{resumo}. Perda no percentil {p:.0f} da regra ({esperado}): "
                       + ("dentro do esperado, não é erro da regra." if p is not None and p >= 5 else "na cauda da distribuição (pior que 95% dos negócios)."))
            else:
                txt = f"{resumo}. Ganho no percentil {p:.0f} ({esperado})."
            if regra.get("media", 0) < 0:
                txt += f" A regra é reprovada no histórico: perder é o esperado dela ({_rs(regra['media'], 0)} por negócio)."
            itens.append(_item(dia, "a", f"a:{tec}:resultado", tec, txt, "nada muda: um dia dentro da distribuição não é erro da regra",
                               n["resultado"], percentil=p))
            ao_vivo = historico_ao_vivo(tec, dia, pasta, setup)
            seq = julgar_sequencia(sequencia_final([r for _d, r in ao_vivo]), regra)
            if seq:
                pr["sequencia"] = seq
                if not seq["normal"]:
                    itens.append(_item(dia, "a", f"a:{tec}:sequencia_anormal", tec,
                                       f"{seq['perdas_seguidas']} perdas seguidas ao vivo: mais que a maior sequência do histórico ({seq['maior_historica']})",
                                       "alerta: a regra pode ter quebrado; vai para a fila de estudo"))
            jv = julgar_ao_vivo([r for _d, r in ao_vivo], regra)
            if jv:
                pr["ao_vivo"] = jv
                if jv["pior"]:
                    itens.append(_item(dia, "a", f"a:{tec}:pior_que_historico", tec,
                                       f"ao vivo, {jv['n']} negócios com média {_rs(jv['media'], 0)}, contra {_rs(jv['media_historica'], 0)} no histórico (z {jv['z']:+.1f})",
                                       "alerta: ao vivo pior que o histórico; vai para a fila de estudo"))
        else:
            lacunas.append(f"sem distribuição histórica para {tec}: o resultado não foi comparado")
        # execucao: a saida bate com a barra?
        if len(bn) and n.get("hora_saida") and n.get("saida") is not None:
            ts = pd.Timestamp(f"{dia} {n['hora_saida']}").floor("min")
            if ts in bn.index:
                bx = bn.loc[ts]
                folga = 1.0 if (n.get("ativo") or "WDOFUT") == "WDOFUT" else 50.0
                if not (bx.l - folga <= float(n["saida"]) <= bx.h + folga):
                    itens.append(_item(dia, "b", "b:execucao:saida_fora_da_barra", tec,
                                       f"a saída a {_pt(n['saida'])} às {_hm(n['hora_saida'])} ficou fora da barra do servidor ({_pt(bx.l)} a {_pt(bx.h)})",
                                       "conferir a cotação que o robô usou (cotação velha?)"))
        # contexto e saidas (so a regra aprovada tem contexto com vantagem e saidas testadas)
        if tec == DADO:
            ent = next((e for e in entradas if e.get("tecnica") == DADO and _hm(e.get("hora")) == n["hora_entrada"][:5]), {})
            ctx = contexto_do_dado(dict(ent.get("medidas") or {}, lado=n["lado"]), regra)
            neg["contexto"] = ctx
            fora = [x for x in ctx if x["fora"]]
            if fora:
                for x in fora:
                    itens.append(_item(dia, "c", f"c:{DADO}:{x['campo']}={x['faixa']}", DADO,
                                       f"disparou com {x['campo']} = {x['faixa']}, faixa sem vantagem no histórico (descoberta {_rs(x['descoberta']['media'], 0)} "
                                       f"por negócio, n {x['descoberta']['n']})", "hipótese: filtrar essa faixa (só depois do teste de 5 anos)", n["resultado"]))
            else:
                neg["contexto_texto"] = "contexto a favor da regra em todos os rótulos (" + "; ".join(
                    f"{x['campo']} {x['faixa']}: {_rs(x['descoberta']['media'], 0)}" for x in ctx) + ")"
            if len(barras):
                alt = saidas_do_dia(barras, n, dia)
                hist = ranking_historico_das_saidas()
                neg["saidas"] = alt
                if alt and "base" in alt:
                    if abs(alt["base"]["resultado"] - n["resultado"]) > 40.0:
                        itens.append(_item(dia, "b", f"b:execucao:diferente_da_simulacao", tec,
                                           f"o negócio real deu {_rs(n['resultado'], 0)} e a mesma regra nas barras do servidor daria {_rs(alt['base']['resultado'], 0)}",
                                           "conferir entrada e saída contra a barra (cotação velha ou rajada?)", n["resultado"] - alt["base"]["resultado"]))
                    outras = {k: v for k, v in alt.items() if k != "base"}
                    melhor_nome = max(outras, key=lambda k: outras[k]["resultado"])
                    ganho = outras[melhor_nome]["resultado"] - alt["base"]["resultado"]
                    if ganho >= SAIDA_CARA_RS:
                        base_h, alt_h = hist.get("base"), hist.get(melhor_nome)
                        comp = "" if base_h is None or alt_h is None else (f" No histórico (descoberta) a saída congelada rende {_rs(base_h, 0)} por negócio e "
                                                                          f"'{melhor_nome}' {_rs(alt_h, 0)}.")
                        itens.append(_item(dia, "d", f"d:{DADO}:{melhor_nome}", DADO,
                                           f"com '{melhor_nome}' o negócio teria dado {_rs(alt[melhor_nome]['resultado'], 0)} ({_rs(ganho, 0)} a mais)." + comp,
                                           "nada muda: saída escolhida no histórico, não no dia" if (alt_h is not None and base_h is not None and alt_h < base_h)
                                           else "hipótese de saída para a fila", ganho))

    # sinais do dia: o que cada um teria dado e por que nao entrou
    grupos = {}
    for s in sinais:
        tec = s.get("tecnica") or "?"
        pr = por_regra.setdefault(tec, {"tecnica": tec, "operados": 0, "resultado": 0.0, "sinais": 0, "soma_sinais": 0.0, "negocios": []})
        motivo, falha = motivo_sem_entrada(s, entradas, negocios, est, dia)
        bs = barras_de(s.get("ativo"))
        r = (medir.hipotetico(s, bs, fim=medir.fim_do_robo(), **medir.do_contrato(s))
             if len(bs) and s.get("entrada") is not None else None)
        pr["sinais"] += 1
        if r is not None:
            pr["soma_sinais"] = round(pr["soma_sinais"] + r["resultado"], 2)
            pr.setdefault("medidos", 0)
            pr["medidos"] += 1
        pr.setdefault("por_motivo", {})
        pr["por_motivo"][motivo] = pr["por_motivo"].get(motivo, 0) + 1
        if falha:
            grupos.setdefault((tec, motivo), []).append((_hm(s.get("hora")), None if r is None else r["resultado"]))
    for (tec, motivo), lista in grupos.items():                  # um item por regra e motivo, com as horas
        horas = ", ".join(h for h, _r in lista)
        soma = sum(x for _h, x in lista if x is not None) if any(x is not None for _h, x in lista) else None
        o_que = (f"marcados 'opera' antes da janela de entradas das {INICIO}: não podiam entrar e o placar da noite os contava como operados"
                 if motivo == "antes da janela" else "deviam entrar e não entraram (spread aberto ou cotação velha?)")
        itens.append(_item(dia, "b", f"b:sinal:{motivo}", tec, f"{len(lista)} sinal(is) de {tec} ({horas}) {o_que}",
                           "conserto: o sinal guarda por que não entrou e o placar conta só o que entrou", soma))
    # regra do laboratorio que opera e nao rodou: contrato fora do robo (o mini-indice ate 15/10/2026, achado 10) ou robo cego
    reg = regras_lab_ler() if registro is None else registro
    rodaram = regras_que_rodaram(est, reg, ativos_robo)
    com_sinal = {s.get("tecnica") for s in sinais} | {e.get("tecnica") for e in entradas}
    itens += fora_do_robo(dia, reg, rodaram)
    if cegos:
        itens += perdidas_por_cegueira(dia, cegos, reg, rodaram=rodaram, com_sinal=com_sinal)
    return {"dia": dia, "gerado": agora_brt().isoformat(timespec="seconds"), "itens": itens, "por_regra": list(por_regra.values()),
            "lacunas": lacunas, "fonte_barras": "servidor do MetaTrader" if barras is not robo else "minutos do robô"}


def regras_lab_ler():
    from quant.daytrade import regras_lab
    return regras_lab.ler_registro()


def regras_que_rodaram(est, registro, ativos_robo=None):
    """Os nomes das regras do laboratorio que o robo rodou no dia. Desde 15/10/2026 o robo grava a lista no estado ("labs_rodando");
    no estado antigo, rodava so a regra cujo contrato estava em ativos_robo.json (o laco do robo so passava por eles: achado 10)."""
    if isinstance(est.get("labs_rodando"), dict):
        return set(est["labs_rodando"])
    if ativos_robo is None:
        from quant.daytrade import chave
        from quant.daytrade.robo import TODOS_OS_ATIVOS
        ativos_robo = chave.ativos_ligados(TODOS_OS_ATIVOS)
    return {r["nome"] for r in registro if str(r.get("ativo") or "WDOFUT").upper() in set(ativos_robo)}


def refazer_regra(dia, r, barras_por_ativo=None):
    """A regra do laboratorio refeita nas barras do servidor do dia: o primeiro negocio do dia (lado, hora, resultado) ou None."""
    from quant.pesquisa import lab
    import importlib.util
    simb = "WIN$N" if (r.get("ativo") or "").startswith("WIN") else "WDO$N"
    b = (barras_por_ativo or {}).get(simb)
    if b is None:
        b = barras_do_servidor(dia, simb, quantas=int(r.get("barras") or 60000))
    arq = r["arquivo"] if os.path.isabs(r["arquivo"]) else os.path.join(RAIZ, r["arquivo"])
    spec = importlib.util.spec_from_file_location("regra_rev_" + r["nome"], arq)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    s = getattr(mod, r.get("funcao") or "regra")(b)
    sd = r.get("saida") or {}
    ja, jb = r["janela"]
    ativo = "WIN" if simb.startswith("WIN") else "WDO"
    t = lab.negocios(b, s, sd.get("stop"), sd.get("alvo"), sd.get("tempo"), ini=ja, ult=jb, zerar="18:30", tick=lab.ESPEC[ativo]["tick"])
    t = lab.medir(t, contratos=int(r.get("contratos") or 1), espec=lab.ESPEC[ativo])
    t = t[t.dia.astype(str) == dia]
    return t.iloc[0] if len(t) else None


def fora_do_robo(dia, registro, rodaram, barras_por_ativo=None):
    """A regra que opera e o robo nao rodou porque nao percorria o contrato dela (o mini-indice ate 15/10/2026: o laco do robo so
    passava pelos contratos de ativos_robo.json). Antes isso aparecia como 'robo cego', com o conserto errado (achado 10)."""
    fora = []
    for r in registro:
        if r.get("estado") != "opera" or not r.get("janela") or r["nome"] in rodaram:
            continue
        nome, titulo = r["nome"], r.get("titulo") or r["nome"]
        base = f"{titulo} não rodou: o robô só percorria os contratos ligados em ativos_robo.json e a regra é do {r.get('ativo') or 'WDOFUT'}"
        acao = "conserto de 15/10/2026: o robô passa a rodar as regras do laboratório de qualquer contrato (vale depois de o robô ser religado)"
        try:
            x = refazer_regra(dia, r, barras_por_ativo)
            txt = base + (f"; teria {'comprado' if x.lado == 'C' else 'vendido'} às {x.hora} e dado {_rs(x.res)}" if x is not None
                          else "; hoje ela não teria dado sinal")
            fora.append(_item(dia, "b", f"b:lab:fora_do_robo:{nome}", titulo, txt, acao, None if x is None else float(x.res)))
        except Exception as e:
            fora.append(_item(dia, "b", f"b:lab:fora_do_robo:{nome}", titulo, base + f" (não deu para refazer: {type(e).__name__})", acao, None))
    return fora


def perdidas_por_cegueira(dia, cegos, registro=None, barras_por_ativo=None, rodaram=None, com_sinal=()):
    """As regras de laboratorio que operam e cuja janela caiu num intervalo cego: o que teriam dado (barras do servidor). Fica de fora a
    regra que o robo nem rodava (vai em `fora_do_robo`) e a que deu sinal no dia (rodou). `cegos`: (ini, fim, min[, motivo])."""
    fora = []
    reg = registro if registro is not None else regras_lab_ler()
    for r in reg:
        if r.get("estado") != "opera" or not r.get("janela"):
            continue
        if (rodaram is not None and r["nome"] not in rodaram) or (r.get("titulo") or r["nome"]) in com_sinal:
            continue
        ja, jb = r["janela"]
        bate = [c for c in cegos if c[0] <= jb and ja <= c[1]]
        if not bate:
            continue
        dormiu = all(len(c) > 3 and c[3] == "mac_dormindo" for c in bate)
        por_que = "o Mac estava dormindo" if dormiu else "o robô estava cego"
        acao = "no pregão, deixar o Mac na tomada e com a tampa aberta" if dormiu else "o conserto da reabertura do MetaTrader cobre"
        titulo = r.get("titulo") or r["nome"]
        try:
            x = refazer_regra(dia, r, barras_por_ativo)
            if x is not None:
                fora.append(_item(dia, "b", f"b:cego:{r['nome']}", titulo,
                                  f"{titulo} não rodou porque {por_que}; teria {'comprado' if x.lado == 'C' else 'vendido'} às {x.hora} "
                                  f"e dado {_rs(x.res)}", acao, float(x.res)))
            else:
                fora.append(_item(dia, "b", f"b:cego:{r['nome']}", titulo, f"{titulo} caiu na janela cega, mas não teria dado sinal hoje", None))
        except Exception as e:
            fora.append(_item(dia, "b", f"b:cego:{r['nome']}", titulo, f"{titulo} caiu na janela cega e não deu para refazer ({type(e).__name__})", None))
    return fora


# ── o que muda amanha, texto e gravacao ──────────────────────
HIPOTESES = {
    "c": "A reversao do dado perde quando dispara com {sufixo}: testar o filtro na descoberta.",
    "d": "A saida '{sufixo}' rende mais que a congelada na reversao do dado: repetir o teste das saidas com os pregoes novos.",
    "a": "A regra {tecnica} esta ao vivo fora do historico ({sufixo}): conferir se o mecanismo mudou (prova viva e 2025).",
}


def repetidos(rev, caderno):
    """Itens de hoje cuja chave ja apareceu em OUTRO pregao do caderno."""
    fora = []
    for x in rev["itens"]:
        dias = sorted(set(dias_da_chave(caderno, x["chave"])) | {rev["dia"]})
        if len(dias) >= 2:
            fora.append((x, dias))
    return fora


def muda_amanha(rev, consertos, abertos):
    fora = []
    dia = rev["dia"]
    for c in consertos:
        if str(c.get("dia") or c.get("quando", ""))[:10] >= dia:
            fora.append(f"Conserto: {c.get('texto')}" + (" (com teste automático)" if c.get("teste") else ""))   # o nome do teste fica no caderno
    for n, x in abertos:
        fora.append(f"Hipótese nova na fila (item {n}): {x['texto']} — só muda a regra se passar no teste de 5 anos.")
    for pr in rev["por_regra"]:
        if pr["operados"]:
            fora.append(f"{pr['tecnica']}: nada muda na regra" + (" (perda dentro da distribuição histórica)" if pr["resultado"] <= 0 else "") + ".")
    return fora or ["Nada muda: o dia não mostrou erro de regra nem falha."]


def manchete(rev):
    falhas = [x for x in rev["itens"] if x["categoria"] == "b"]
    oper = [n for pr in rev["por_regra"] for n in pr["negocios"]]
    total = sum(pr["resultado"] for pr in rev["por_regra"])
    partes = []
    if oper:
        partes.append(f"{len(oper)} negócio(s), {_rs(total)}")
        perc = [n["percentil"] for n in oper if n.get("percentil") is not None]
        if perc and total <= 0:
            partes.append(f"perda dentro da distribuição histórica (percentil {min(perc):.0f})" if min(perc) >= 5 else "perda na cauda da distribuição")
    else:
        partes.append("nenhum negócio")
    if falhas:
        cego = [x for x in falhas if x["chave"] == "b:metatrader:cego"]
        dormiu = [x for x in falhas if x["chave"] == "b:mac:dormiu"]
        partes.append(f"{len(falhas)} falha(s) de execução ou de dado" + (f", com o robô cego {sum(x.get('minutos', 0) for x in cego)} minutos" if cego else "")
                      + (f", com o Mac dormindo {sum(x.get('minutos', 0) for x in dormiu)} minutos" if dormiu else ""))
    return "; ".join(partes) + "."


def texto(rev):
    L = [f"# Revisão do pregão de {pd.Timestamp(rev['dia']).strftime('%d/%m/%Y')}: onde errou e o que muda amanhã", "", f"Em uma frase: {rev['manchete']}", ""]
    for cat in ("b", "a", "c", "d"):
        xs = [x for x in rev["itens"] if x["categoria"] == cat]
        if not xs:
            continue
        L.append(f"## ({cat}) {CATEGORIAS[cat]}")
        for x in xs:
            L.append(f"- {x['texto']}" + (f" Ação: {x['acao']}." if x.get("acao") else "") + (" [REPETIU]" if x.get("repetiu") else ""))
        L.append("")
    L += ["## Por regra", "", "| Regra | Feitos (R$) | Sinais (teria dado) | Por que não entrou |", "|---|---|---|---|"]
    for pr in rev["por_regra"]:
        mot = ", ".join(f"{k} {v}" for k, v in (pr.get("por_motivo") or {}).items())
        L.append(f"| {pr['tecnica']} | {pr['operados']} ({_rs(pr['resultado'], 0)}) | {pr['sinais']} ({_rs(pr['soma_sinais'], 0)}) | {mot or '-'} |")
    L += ["", "## O que muda amanhã"] + [f"- {x}" for x in rev["muda_amanha"]]
    if rev.get("lacunas"):
        L += ["", "## Lacunas"] + [f"- {x}" for x in rev["lacunas"]]
    return "\n".join(L) + "\n"


def bloco_tela(rev):
    return {"dia": rev["dia"], "gerado": rev["gerado"], "manchete": rev["manchete"],
            "titulo": "Revisão do pregão: onde errou e o que muda amanhã",
            "itens": [{k: x.get(k) for k in ("categoria", "rotulo", "tecnica", "texto", "acao", "valor_rs", "repetiu")} for x in rev["itens"]],
            "por_regra": [{k: pr.get(k) for k in ("tecnica", "operados", "resultado", "sinais", "soma_sinais", "por_motivo")} for pr in rev["por_regra"]],
            "muda_amanha": rev["muda_amanha"], "lacunas": rev.get("lacunas") or [], "caderno": rev.get("caderno"),
            "termos": [{"termo": "Percentil", "explicacao": "onde o resultado cai entre os negócios da regra de 2021 a 2025: percentil 30 = 30% foram piores"},
                       {"termo": "Distribuição histórica", "explicacao": "todos os resultados que a regra, com os parâmetros de hoje, teria dado em 5 anos de barras de 1 minuto"},
                       {"termo": "Caderno de erros", "explicacao": "lista que acumula cada erro com data, categoria e ação; o que se repete vira teste na fila de pesquisa"}]}


def publicar_na_tela(rev, telas=None):
    """Poe o bloco "revisao" no quant.json da area QUANT (o robo republica a ultima revisao enquanto roda)."""
    for caminho in (TELAS if telas is None else telas):
        q = ler_json(caminho, padrao=None)
        if not isinstance(q, dict):
            continue
        q["revisao"] = bloco_tela(rev)
        try:
            gravar_atomico(caminho, json.dumps(q, ensure_ascii=False))
        except OSError:
            pass


def ultima_revisao(dir_rev=DIR_REV):
    """A revisao mais recente gravada (para o robo publicar no quant.json)."""
    arqs = sorted(glob.glob(os.path.join(dir_rev, "20??-??-??.json")))
    return ler_json(arqs[-1], padrao=None) if arqs else None


def gravar(rev, ensaio=False, arq_caderno=ARQ_CADERNO, arq_fila=ARQ_FILA, dir_rev=DIR_REV, telas=None, consertos=None):
    """Caderno, fila, arquivos do dia e tela. Devolve a revisao com `muda_amanha`, `manchete` e `caderno`."""
    caderno = ler_caderno(arq_caderno)
    consertos = _jsonl(os.path.join(dir_rev, "consertos.jsonl")) if consertos is None else consertos
    ja = {(x["dia"], x["chave"]) for x in caderno}
    abertos = []
    for x, dias in repetidos(rev, caderno):
        if x["chave"].endswith(":resultado"):
            continue                                             # um resultado da regra em dia diferente nao e "erro repetido"
        x["repetiu"] = dias
        cat = x["categoria"]
        if cat in ("a", "c", "d"):
            sufixo = x["chave"].split(":", 2)[-1]
            hip = dict(x, hipotese=HIPOTESES[cat].format(sufixo=sufixo, tecnica=x.get("tecnica")))
            n = None if ensaio else abrir_na_fila(hip, dias, arq_fila)
            x["fila"] = n
            abertos.append((n, x))
    rev["muda_amanha"] = muda_amanha(rev, consertos, abertos)
    rev["manchete"] = manchete(rev)
    # no caderno vai o que e erro ou alerta: falhas, contexto, saida, alertas e as perdas (o ganho da regra nao e erro)
    novos = [x for x in rev["itens"] if (x["dia"], x["chave"]) not in ja
             and not (x["chave"].endswith(":resultado") and (x.get("valor_rs") or 0) > 0)]
    # o Mac dormindo de novo nao e "conserto que nao resolveu": nao ha conserto de codigo para isso (15/10/2026, achado 42)
    rep_b = [x for x in rev["itens"] if x["categoria"] == "b" and x.get("repetiu") and not x["chave"].startswith("b:mac:")]
    total = len(caderno) + len(novos)
    rev["caderno"] = {"total": total, "novos_hoje": len(novos), "falhas_repetidas": [x["chave"] for x in rep_b],
                      "abertos_na_fila": [n for n, _x in abertos if n]}
    if rep_b:
        rev["manchete"] = f"FALHA REPETIDA ({', '.join(sorted({x['chave'] for x in rep_b}))}): o conserto anterior não resolveu. " + rev["manchete"]
    if ensaio:
        return rev
    garantir_dir(dir_rev)
    with open(arq_caderno, "a", encoding="utf-8") as f:
        for x in novos:
            f.write(json.dumps({k: x.get(k) for k in ("dia", "categoria", "rotulo", "chave", "tecnica", "texto", "acao", "valor_rs")}, ensure_ascii=False) + "\n")
    gravar_atomico(os.path.join(dir_rev, "caderno_de_erros.md"), caderno_md(caderno + novos, consertos))
    gravar_atomico(os.path.join(dir_rev, f"{rev['dia']}.json"), json.dumps(rev, ensure_ascii=False, default=str))
    gravar_atomico(os.path.join(dir_rev, f"{rev['dia']}.md"), texto(rev))
    publicar_na_tela(rev, telas)
    return rev


def registrar_conserto(chave, texto_, teste=None, commit=None, dia=None, arq=ARQ_CONSERTOS):
    """A rotina da noite chama isto depois de consertar uma falha (b) no codigo, com teste."""
    garantir_dir(os.path.dirname(arq))
    linha = {"quando": agora_brt().isoformat(timespec="seconds"), "dia": dia or agora_brt().strftime("%Y-%m-%d"), "chave": chave,
             "texto": texto_, "teste": teste, "commit": commit}
    with open(arq, "a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")
    return linha


def rodar(dia=None, ensaio=False, pedir_servidor=True, pasta=DIR_DT):
    rev = revisar(dia, pasta=pasta, pedir_servidor=pedir_servidor)
    return gravar(rev, ensaio=ensaio)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Revisao do pregao do robo de day trade (simulacao)")
    ap.add_argument("--dia", default=None)
    ap.add_argument("--sem-metatrader", action="store_true", help="nao pede barras ao MetaTrader (usa os minutos do robo)")
    ap.add_argument("--ensaio", action="store_true", help="mostra a revisao sem gravar caderno, fila nem tela")
    a = ap.parse_args()
    print(texto(rodar(a.dia, ensaio=a.ensaio, pedir_servidor=not a.sem_metatrader)))
