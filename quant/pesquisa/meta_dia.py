"""
A META DO DIA em reais, medida no passado (11/10/2026).

O Douglas fixou a meta do mini-dolar em R$ 100 LIQUIDOS por dia (0,10% de R$ 100 mil); batida a meta, o robo zera tudo e para
ate amanha. Aqui se mede, com as barras de 1 minuto do laboratorio e as REGRAS CONGELADAS que o robo roda (dado, climax e teste
de nivel, com os numeros de `quant/daytrade/robo_fluxo.py`), o que isso teria dado dia a dia:

  - em quantos pregoes o dia toca +R$ 100 e em quantos fecha em +R$ 100 ou mais;
  - resultado medio por pregao e por mes, pior dia, pior mes, queda do acumulado;
  - o efeito de PARAR em +R$ 100 (media com e sem o teto: parar cedo corta os dias grandes e deixa passar os dias ruins).

Nao e uma regra nova e nao muda nenhum parametro: e a regua do robo (a meta) passada sobre o que ja existe.

COMO SIMULA (sempre contra a regra; igual ao `historico.py` do robo, mais a meta e o limite de perda DENTRO do negocio):
  - entrada a mercado na abertura da barra seguinte ao sinal, 1 tick pior; saida a mercado 1 tick pior; parcial e alvo no preco;
    taxa de R$ 1,20 por contrato e por lado; 2 contratos (o lote do robo);
  - dentro de uma barra de 1 minuto nao se sabe a ordem dos precos: o lado ADVERSO vem primeiro (stop, depois o limite de
    perda do dia), o lado favoravel depois (parcial, a meta, o alvo, pela ordem de preco);
  - a META e comparada, como no robo (`robo_fluxo.py`, ciclo), com o resultado LIQUIDO do dia: o que ja fechou (depois de custo)
    mais o aberto ao ultimo preco menos o custo de ida e volta do que ainda esta aberto. Batida, zera a mercado (1 tick pior) e para;
    por isso o dia fecha perto de R$ 90 a R$ 100, nao exatamente em R$ 100;
  - as outras travas do dia valem: perda maxima de R$ 1.000 (tambem DENTRO do negocio), 3 negocios perdedores, 12 operacoes;
  - varias regras no mesmo dia: uma posicao por vez (a primeira que sinaliza fica); antes do dado americano a vaga e do setup do
    dado (reserva de 22 minutos, como no robo).

Periodos: DESCOBERTA (10/2021 a 12/2024) e VALIDACAO (2025). 2026 NAO e aberto: ja foi usado como prova das regras do dado e do climax
(quant/pesquisa/METODO.md) e a pergunta nao justifica outra abertura.

Uso: PYTHONPATH=. .venv/bin/python -W ignore -m quant.pesquisa.meta_dia
"""
import json
import math
import os
import sys
import time

import numpy as np
import pandas as pd

from quant.daytrade import estrategias_hist as eh
from quant.daytrade import historico as h
from quant.daytrade.historico import Custos, Estrategia, Negocio, Ordem, RegrasDoDia, _abrir
from quant.pesquisa import lab

PASTA_SAIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "meta_dia")
DU_POR_MES = 21


# ───────────────────────── as regras congeladas do robo, em forma de Estrategia ─────────────────────────
class DadoNY(Estrategia):
    """Reversao da reacao ao dado americano (robo_fluxo.DADO): mede do fechamento do minuto anterior ao dado ate o fechamento do
    `minutos`-esimo minuto depois; passou de `limiar` pontos, entra CONTRA no minuto seguinte. Sem alvo e sem parcial; sai em
    `tempo_max` minutos ou no stop. E a mesma conta de `calendario/regras.py::reverte_dado_ny` (800 de 801 sinais iguais ao robo)."""
    nome = "reversao do dado americano"

    def __init__(self, minutos=2, limiar=3.0, stop=40.0, tempo_max=120, **_):
        self.minutos, self.limiar, self.stop, self.tempo_max = minutos, limiar, stop, tempo_max

    def preparar(self, m1):
        from quant.saida.pesquisa5.calendario import regras as cal
        self.m1 = m1
        self.s = cal.reverte_dado_ny(m1, r=self.minutos, thr=self.limiar)
        self.verao = cal._verao_eua(m1)

    def decidir(self, i, dia, ctx):
        v = self.s[i]
        if v == 0:
            return None
        return Ordem("C" if v > 0 else "V", stop_pts=self.stop, tempo_max=self.tempo_max, motivo="reversao do dado",
                     info={"tecnica": "dado"})

    def perto_do_dado(self):
        """Por barra: True se a DECISAO do fechamento desta barra cai entre 22 minutos antes do dado e o minuto da entrada do dado."""
        hora = self.m1.index + pd.Timedelta(minutes=1)                       # a decisao e no fechamento da barra
        minuto = hora.hour * 60 + hora.minute
        dado = np.where(self.verao, 9 * 60 + 30, 10 * 60 + 30)
        return np.asarray((minuto >= dado - 22) & (minuto <= dado + self.minutos))


class Prioridade(Estrategia):
    """Varias regras no mesmo dia, uma posicao por vez: vale a primeira da lista que sinaliza. As que nao sao o dado ficam de fora da
    reserva antes do dado (a vaga e do setup proprio)."""

    def __init__(self, estrategias, nome=None):
        self.estrategias = list(estrategias)
        self.nome = nome or " + ".join(e.nome for e in self.estrategias)

    def preparar(self, m1):
        self.m1 = m1
        for e in self.estrategias:
            e.preparar(m1)
        dado = next((e for e in self.estrategias if isinstance(e, DadoNY)), None)
        self.reserva = dado.perto_do_dado() if dado is not None else np.zeros(len(m1), dtype=bool)

    def decidir(self, i, dia, ctx):
        for e in self.estrategias:
            if not isinstance(e, DadoNY) and self.reserva[i]:
                continue
            o = e.decidir(i, dia, ctx)
            if o is not None:
                return o
        return None


def regras_do_robo():
    """As regras como o robo as roda hoje, com os numeros do codigo (nao copiados: lidos de robo_fluxo)."""
    from quant.daytrade import robo_fluxo as rf
    c, n = rf.CLIMAX, rf.NIVEIS
    return {
        "dado": lambda: DadoNY(minutos=rf.DADO["minutos"], limiar=rf.DADO["limiar"], stop=rf.DADO["stop"], tempo_max=rf.DADO["tempo_max"]),
        "climax": lambda: eh.Climax(tranco=c["tranco"], vol=c["vol"], janela=c["janela"], stop_fixo=c["stop_fixo"],
                                    alvo_devolve=c["alvo_devolve"], tempo_max=c["tempo_max"], nome="climax de volume"),
        "climax_fraco": lambda: eh.Climax(tranco=c["medir_tranco"], vol=c["medir_vol"], janela=c["janela"], stop_fixo=c["stop_fixo"],
                                          alvo_devolve=c["alvo_devolve"], tempo_max=c["tempo_max"], nome="climax fraco (so medido)"),
        "nivel": lambda: eh.NivelReacao(**n, nome="teste de nivel (so medido)"),
    }


# ───────────────────────── o motor: o historico.py do robo + a meta e a perda DENTRO do negocio ─────────────────────────
def _arredonda(preco, tick, para_cima):
    return (math.ceil(preco / tick - 1e-9) if para_cima else math.floor(preco / tick + 1e-9)) * tick


def _conduzir_dia(pos, i, o, hi, lo, hm, regras, custos, desl, res_dia, meta, perda, lock=None):
    """Uma barra com posicao aberta, como `historico._conduzir`, mais: (1) a META do dia: o aberto, liquido do custo de ida e volta,
    leva o dia a `meta`; (2) o limite de PERDA do dia dentro do negocio. Devolve o motivo da saida final ou None.
    `lock` (hipotese 16 da FILA, pre-registrada): em vez de zerar na meta, leva o stop para o preco em que o dia ainda fecha em `lock` reais
    liquidos (depois do deslize da saida) e deixa a posicao correr; vale a partir da barra seguinte."""
    s, ent, vp, tick = pos["sinal"], pos["entrada"], custos.valor_ponto, custos.tick
    if i < pos["aberta_em"]:
        return None
    if hm[i] >= regras.zerar:
        pos["soma_pts"] += s * ((o[i] - s * desl) - ent) * pos["restam"]
        return "fim da janela"
    if pos.get("tempo_max") and i - pos["aberta_em"] >= pos["tempo_max"]:
        pos["soma_pts"] += s * ((o[i] - s * desl) - ent) * pos["restam"]
        return "tempo"
    pior, melhor = (lo[i], hi[i]) if s > 0 else (hi[i], lo[i])
    custo_total = 2 * custos.por_lado_rs * pos["inicial"]

    def preco_do_dia(total):
        """Preco em que o dia (liquido) chega a `total`, com a posicao no estado de agora."""
        return ent + s * (((total - res_dia + custo_total) / vp - pos["soma_pts"]) / pos["restam"])

    # lado adverso primeiro: o que estiver mais perto da entrada (o stop ou o limite de perda do dia)
    p_perda = preco_do_dia(-perda) if perda else None
    bateu_stop = (pior <= pos["stop"]) if s > 0 else (pior >= pos["stop"])
    bateu_perda = p_perda is not None and ((pior <= p_perda) if s > 0 else (pior >= p_perda))
    if bateu_stop and (not bateu_perda or ((pos["stop"] >= p_perda) if s > 0 else (pos["stop"] <= p_perda))):
        base = min(o[i], pos["stop"]) if s > 0 else max(o[i], pos["stop"])
        pos["soma_pts"] += s * ((base - s * desl) - ent) * pos["restam"]
        return "stop" if not pos["parcial_feita"] else ("zero a zero" if abs(pos["stop"] - ent) < 1e-9 else "stop móvel")
    if bateu_perda:
        base = min(o[i], p_perda) if s > 0 else max(o[i], p_perda)
        pos["soma_pts"] += s * ((base - s * desl) - ent) * pos["restam"]
        return "perda maxima do dia"
    # lado favoravel. Como no historico.py: o alvo vale para a posicao inteira (se o alvo e a parcial cabem na mesma barra, sai tudo no alvo);
    # a META entra pela ordem de preco: se esta mais perto da entrada que o alvo, fecha antes; se a parcial esta mais perto que a meta, sai antes.
    def chegou(preco):
        return (melhor >= preco) if s > 0 else (melhor <= preco)

    while True:
        p_meta = _arredonda(preco_do_dia(meta), tick, para_cima=s > 0) if (meta and not pos.get("meta_tocada")) else None
        meta_ok = p_meta is not None and chegou(p_meta)
        alvo_ok = pos["alvo"] is not None and chegou(pos["alvo"])
        if alvo_ok and (not meta_ok or s * pos["alvo"] <= s * p_meta):
            pos["soma_pts"] += s * (pos["alvo"] - ent) * pos["restam"]
            return "alvo"
        parcial_ok = pos["parcial"] is not None and not pos["parcial_feita"] and chegou(pos["parcial"])
        if meta_ok and not (parcial_ok and s * pos["parcial"] < s * p_meta):
            if lock is not None:                                                   # hipotese 16: protege em vez de zerar
                trava = preco_do_dia(lock) + s * desl                              # o stop dispara aqui e sai 1 tick pior: o dia fecha em `lock`
                pos["stop"] = max(pos["stop"], trava) if s > 0 else min(pos["stop"], trava)
                pos["meta_tocada"] = True
                break
            base = max(o[i], p_meta) if s > 0 else min(o[i], p_meta)           # abriu alem do gatilho: o robo ve no primeiro ciclo
            pos["soma_pts"] += s * ((base - s * desl) - ent) * pos["restam"]
            return "meta do dia"
        if not parcial_ok:
            break
        metade = pos["restam"] // 2
        pos["soma_pts"] += s * (pos["parcial"] - ent) * metade
        pos["restam"] -= metade
        pos["parcial_feita"] = True
        pos["stop"] = ent
        if not meta:
            break                                                                   # sem meta: igual ao historico (a parcial encerra a barra)
    pos["melhor"] = max(pos["melhor"], melhor) if s > 0 else min(pos["melhor"], melhor)
    if pos["arrasto"] is not None and (pos["parcial_feita"] or pos["parcial"] is None):
        movel = pos["melhor"] - s * pos["arrasto"]
        if (movel > pos["stop"]) if s > 0 else (movel < pos["stop"]):
            pos["stop"] = movel
    return None


def _um_dia(i0, i1, dia, o, hi, lo, c, horas, hm, est, regras, custos, desl, meta, perda_dentro=True, lock=None):
    fora, toques = [], False
    pos, res_dia, perdas, operacoes, livre_em, travado = None, 0.0, 0, 0, i0, False
    ctx = {"i0": i0}
    perda = regras.perda_maxima_rs if perda_dentro else None
    for i in range(i0, i1):
        if pos is not None:
            fechou = _conduzir_dia(pos, i, o, hi, lo, hm, regras, custos, desl, res_dia, meta, perda, lock)
            if lock is not None and pos is not None and pos.get("meta_tocada"):
                toques = True
            if fechou:
                pts = pos["soma_pts"] / pos["inicial"]
                res = pos["soma_pts"] * custos.valor_ponto - 2 * custos.por_lado_rs * pos["inicial"]
                fora.append(Negocio(dia, pos["hora"], horas[i], pos["lado"], pos["inicial"], pos["entrada"],
                                    pos["entrada"] + (pts if pos["lado"] == "C" else -pts), pts, res, pos["motivo"], fechou,
                                    pos.get("info") or {}, abs(pos["melhor"] - pos["entrada"])))
                res_dia += res
                perdas += 1 if res < 0 else 0
                tocada = bool(pos.get("meta_tocada"))
                pos, livre_em = None, i + regras.espera_min
                if fechou == "meta do dia" or (meta and res_dia >= meta) or (lock is not None and tocada):
                    toques, travado = True, True                    # meta batida: zerou (ou fechou a posicao protegida) e para ate amanha
                if (regras.perda_maxima_rs and res_dia <= -regras.perda_maxima_rs) or \
                        (regras.perdas_para_parar and perdas >= regras.perdas_para_parar):
                    travado = True
            continue
        if travado or i + 1 >= i1 or i < livre_em or operacoes >= regras.max_operacoes:
            continue
        if not (regras.inicio <= hm[i] < regras.ultima_entrada):
            continue
        ordem = est.decidir(i, dia, ctx)
        if ordem is None:
            continue
        assert ordem.limite is None, "ordem parada nao e usada pelas regras do robo"
        pos = _abrir(ordem, o[i + 1] + (desl if ordem.lado == "C" else -desl), horas[i + 1], i + 1, regras)
        operacoes += 1
    return fora, toques


def simular(m1, estrategia, regras=None, custos=None, meta=None, de=None, ate=None, perda_dentro=True, lock=None):
    """Roda dia a dia. Devolve (lista de Negocio, {dia: bateu_a_meta}). `meta=None`: sem teto (so as outras travas)."""
    regras, custos = regras or RegrasDoDia(meta_rs=None), custos or Custos()
    regras.meta_rs = meta
    estrategia.preparar(m1)
    o, hi, lo, c = (m1[k].to_numpy() for k in ("o", "h", "l", "c"))
    horas = m1.index
    hm = np.array([t.strftime("%H:%M") for t in horas])
    dias = np.array([t.date() for t in horas])
    desl = custos.deslize_ticks * custos.tick
    negocios, bateu = [], {}
    n, i = len(m1), 0
    while i < n:
        dia = dias[i]
        j = i
        while j < n and dias[j] == dia:
            j += 1
        if (de is None or dia >= de) and (ate is None or dia <= ate):
            ns, tocou = _um_dia(i, j, dia, o, hi, lo, c, horas, hm, estrategia, regras, custos, desl, meta, perda_dentro, lock)
            negocios.extend(ns)
            bateu[dia] = tocou
        else:
            bateu[dia] = False
        i = j
    return negocios, bateu


# ───────────────────────── numeros ─────────────────────────
def por_dia(negocios, dias):
    """Resultado liquido de cada pregao (zero onde nao houve negocio)."""
    s = pd.Series({d: 0.0 for d in dias})
    for x in negocios:
        s[x.dia] += x.resultado
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def tabela_de(nome, negocios, bateu, dias, meta=100.0):
    r = por_dia(negocios, dias)
    n_neg = len(negocios)
    operou = pd.Series({pd.Timestamp(d): False for d in dias})
    for x in negocios:
        operou[pd.Timestamp(x.dia)] = True
    mes = r.groupby(r.index.to_period("M")).sum()
    pregoes = len(r)
    ganhos = [x.resultado for x in negocios if x.resultado > 0]
    perdas = [x.resultado for x in negocios if x.resultado <= 0]
    acum = r.cumsum()
    toca = sum(1 for d in dias if bateu.get(d))
    return {
        "regra": nome, "pregoes": pregoes, "pregoes_com_negocio": int(operou.sum()), "negocios": n_neg,
        "acerto_pct": round(100 * len(ganhos) / n_neg, 1) if n_neg else None,
        "ganho_medio": round(float(np.mean(ganhos)), 1) if ganhos else None, "perda_media": round(float(np.mean(perdas)), 1) if perdas else None,
        "rs_por_negocio": round(float(np.mean([x.resultado for x in negocios])), 1) if n_neg else None,
        "dias_fecham_ge_meta": int((r >= meta).sum()), "pct_dias_fecham_ge_meta": round(100 * float((r >= meta).mean()), 1),
        "dias_que_tocaram_a_meta": int(toca), "pct_dias_tocaram": round(100 * toca / pregoes, 1),
        "dias_positivos_pct": round(100 * float((r > 0).mean()), 1), "dias_negativos_pct": round(100 * float((r < 0).mean()), 1),
        "media_por_pregao": round(float(r.mean()), 1), "media_por_dia_operado": round(float(r[operou.values].mean()), 1) if operou.any() else None,
        "media_por_mes": round(float(r.mean() * DU_POR_MES), 0), "meses": int(len(mes)), "meses_ge_2100": int((mes >= meta * DU_POR_MES).sum()),
        "pior_mes": round(float(mes.min()), 0), "melhor_mes": round(float(mes.max()), 0), "pior_dia": round(float(r.min()), 0),
        "melhor_dia": round(float(r.max()), 0), "dias_pior_que_menos_500": int((r <= -500).sum()),
        "queda_maxima": round(float((acum - acum.cummax()).min()), 0), "total": round(float(r.sum()), 0),
        "desvio_diario": round(float(r.std()), 1), "t_da_media_diaria": round(float(r.mean() / (r.std() / math.sqrt(len(r)))), 2) if r.std() > 0 else None,
    }


def carregar_partes(partes=("descoberta", "validacao")):
    out = {}
    for p in partes:
        out[p] = lab.carregar("WDO", p)
    return out


def rodar(meta=100.0, partes=("descoberta", "validacao"), regras_nomes=None, verboso=True):
    base = regras_do_robo()
    fabrica = {
        "A. DADO (opera)": ["dado"],
        "B. CLIMAX lote 2 (codigo liga; modo_robo.json: so medido)": ["climax"],
        "C. DADO + CLIMAX (dado primeiro)": ["dado", "climax"],
        "D. TESTE DE NIVEL (so medido)": ["nivel"],
        "E. CLIMAX FRACO 3 pts / 2,5x (so medido)": ["climax_fraco"],
        "F. TUDO JUNTO (dado, climax, nivel)": ["dado", "climax", "nivel"],
    }
    if regras_nomes:
        fabrica = {k: v for k, v in fabrica.items() if k[0] in regras_nomes}
    dados = carregar_partes(partes)
    saida, dia_a_dia = [], {}
    for parte, m1 in dados.items():
        dias = sorted(set(m1.index.date))
        for rotulo, nomes in fabrica.items():
            for com_meta in (False, True):
                est = Prioridade([base[n]() for n in nomes]) if len(nomes) > 1 else base[nomes[0]]()
                negocios, bateu = simular(m1, est, RegrasDoDia(contratos=2), Custos(), meta=meta if com_meta else None)
                t = tabela_de(rotulo, negocios, bateu, dias, meta=meta)
                t.update(parte=parte, com_teto=com_meta)
                saida.append(t)
                dia_a_dia[(parte, rotulo, com_meta)] = (por_dia(negocios, dias), negocios)
                if verboso:
                    print(f"{parte:<10} {'COM teto' if com_meta else 'sem teto'} {rotulo:<56} neg {t['negocios']:>4} | pregoes {t['pregoes']} | "
                          f"fecham >= {meta:.0f}: {t['pct_dias_fecham_ge_meta']:>5.1f}% | tocaram: {t['pct_dias_tocaram']:>5.1f}% | por pregao {t['media_por_pregao']:>+7.1f} | "
                          f"por mes {t['media_por_mes']:>+7.0f} | pior dia {t['pior_dia']:>+6.0f} | queda {t['queda_maxima']:>+7.0f}", flush=True)
    return pd.DataFrame(saida), dia_a_dia


def principal(meta=100.0):
    os.makedirs(PASTA_SAIDA, exist_ok=True)
    T, dd = rodar(meta=meta)
    T.to_csv(os.path.join(PASTA_SAIDA, "tabela_por_regra.csv"), index=False)
    linhas = []
    for (parte, rotulo, com), (serie, _neg) in dd.items():
        linhas.append(serie.rename(f"{parte}|{rotulo}|{'teto' if com else 'sem'}"))
    pd.concat(linhas, axis=1).to_csv(os.path.join(PASTA_SAIDA, "resultado_por_pregao.csv"))
    return T, dd




# ───────────────────────── relatorio completo (tabelas que vao para META_DIA.md) ─────────────────────────
def _juntar(dd, rotulo, com):
    """Serie por pregao e lista de negocios das duas partes juntas (descoberta + validacao)."""
    series = [dd[(p, rotulo, com)][0] for p in ("descoberta", "validacao") if (p, rotulo, com) in dd]
    negs = [x for p in ("descoberta", "validacao") if (p, rotulo, com) in dd for x in dd[(p, rotulo, com)][1]]
    return pd.concat(series).sort_index(), negs


def gravar_constantes(L, meta=100.0):
    """Os numeros que o texto do objetivo cita no robo (`estrategia_fluxo.objetivo_em_texto`): um JSON pequeno com a fonte e a data.
    Sai da mesma tabela deste relatorio (regra A, dado, 10/2021 a 12/2025), nunca digitado a mao."""
    a = L[L.regra.str.startswith("A.") & (L.periodo == "junto")]
    sem, com = a[~a.com_teto].iloc[0], a[a.com_teto].iloc[0]
    d = {"fonte": "quant/pesquisa/META_DIA.md (motor quant/pesquisa/meta_dia.py, relatorio)", "data": time.strftime("%Y-%m-%d"),
         "periodo": "10/2021 a 12/2025 (descoberta 805 + validacao 250 pregoes; 2026 nao aberto)", "regra": "reversao do dado americano (opera)",
         "pregoes": int(sem.pregoes), "teto_testado_rs": float(meta), "media_por_pregao_sem_teto_rs": float(sem.media_por_pregao),
         "media_por_pregao_com_teto_rs": float(com.media_por_pregao), "pior_dia_sem_teto_rs": float(sem.pior_dia),
         "pior_dia_com_teto_rs": float(com.pior_dia), "negocios": int(sem.negocios)}
    with open(os.path.join(PASTA_SAIDA, "constantes_medicao.json"), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    return d


def relatorio(meta=100.0):
    os.makedirs(PASTA_SAIDA, exist_ok=True)
    T, dd = rodar(meta=meta, verboso=False)
    rotulos = sorted(set(T.regra))
    saida = {}
    # 1. tabela por regra, por periodo e juntos
    linhas = []
    for rotulo in rotulos:
        for com in (False, True):
            for parte in ("descoberta", "validacao", "junto"):
                if parte == "junto":
                    r, negs = _juntar(dd, rotulo, com)
                else:
                    r, negs = dd[(parte, rotulo, com)]
                dias = [d.date() for d in r.index]
                toca = None
                if com:
                    toca = sum(1 for x in negs if x.motivo and x.saida == "meta do dia")
                n = len(negs)
                ganhos = [x.resultado for x in negs if x.resultado > 0]
                perdas = [x.resultado for x in negs if x.resultado <= 0]
                mes = r.groupby(r.index.to_period("M")).sum()
                acum = r.cumsum()
                linhas.append({
                    "regra": rotulo, "com_teto": com, "periodo": parte, "pregoes": len(r), "negocios": n,
                    "pct_pregoes_com_negocio": round(100 * float(len({x.dia for x in negs})) / len(r), 1),
                    "pct_pregoes_fecham_ge_meta": round(100 * float((r >= meta).mean()), 1) if not com else None,
                    "pct_pregoes_bateram_a_meta": round(100 * toca / len(r), 1) if com else None,
                    "acerto_pct": round(100 * len(ganhos) / n, 1) if n else None,
                    "ganho_medio": round(float(np.mean(ganhos)), 0) if ganhos else None, "perda_media": round(float(np.mean(perdas)), 0) if perdas else None,
                    "rs_por_negocio": round(float(np.mean([x.resultado for x in negs])), 1) if n else None,
                    "media_por_pregao": round(float(r.mean()), 1), "media_por_mes": round(float(r.mean() * DU_POR_MES), 0),
                    "t_media_diaria": round(float(r.mean() / (r.std() / math.sqrt(len(r)))), 2) if r.std() > 0 else None,
                    "pior_dia": round(float(r.min()), 0), "pior_mes": round(float(mes.min()), 0),
                    "meses_ge_2100": f"{int((mes >= meta * DU_POR_MES).sum())} de {len(mes)}",
                    "queda_maxima": round(float((acum - acum.cummax()).min()), 0), "total": round(float(r.sum()), 0)})
    L = pd.DataFrame(linhas)
    L.to_csv(os.path.join(PASTA_SAIDA, "tabela_final.csv"), index=False)
    gravar_constantes(L, meta)
    saida["tabela"] = L
    # 2. o dado com e sem teto: por saida, por ano
    detalhe = []
    for com in (False, True):
        r, negs = _juntar(dd, "A. DADO (opera)", com)
        df = pd.DataFrame([{"saida": x.saida, "res": x.resultado, "dia": pd.Timestamp(x.dia)} for x in negs])
        g = df.groupby("saida").res.agg(["count", "mean", "sum"]).round(1)
        g["com_teto"] = com
        detalhe.append(g.reset_index())
        por_ano = r.groupby(r.index.year).agg(["mean", "sum", "count"]).round(1)
        por_ano["com_teto"] = com
        saida[f"por_ano_dado_{'teto' if com else 'sem'}"] = por_ano
    saida["dado_por_saida"] = pd.concat(detalhe)
    # 3. sensibilidade da meta (dado), so descritiva
    sens = []
    est = regras_do_robo()["dado"]
    for parte in ("descoberta", "validacao"):
        m1 = lab.carregar("WDO", parte)
        dias = sorted(set(m1.index.date))
        for mt in (50, 100, 150, 200, 300, 500, 1000, None):
            negs, bateu = simular(m1, est(), RegrasDoDia(contratos=2), Custos(), meta=mt)
            t = tabela_de("dado", negs, bateu, dias, meta=mt or 100.0)
            sens.append({"parte": parte, "meta": mt if mt else "sem", "media_por_pregao": t["media_por_pregao"], "pct_pregoes_tocaram": t["pct_dias_tocaram"] if mt else None,
                         "pior_dia": t["pior_dia"], "rs_por_negocio": t["rs_por_negocio"], "negocios": t["negocios"]})
    saida["sensibilidade_meta_dado"] = pd.DataFrame(sens)
    return saida


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "relatorio":
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 200)
    for nome, df in relatorio().items():
        print("\n==", nome)
        print(df.to_string())


if __name__ == "__main__" and not (len(sys.argv) > 1 and sys.argv[1] == "relatorio"):
    principal(float(sys.argv[1]) if len(sys.argv) > 1 else 100.0)
