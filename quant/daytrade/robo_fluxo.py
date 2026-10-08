"""
Robo de day trade pela LEITURA DE FLUXO (regra versao 1), em SIMULACAO.

E o mesmo desenho de robo.py (le o motor do terminal uma vez por segundo, simula, grava o
estado para a area QUANT), com duas diferencas:
  - alem do preco, le a FITA (negocios com o lado agressor) que o AutopilotFeed 1.3 grava na
    pasta do MetaTrader, e o ajuste de ontem na foto do mesmo robo;
  - a regra e a de estrategia_fluxo.py: defesa e perda de nivel confirmadas pelo fluxo,
    parcial, zero a zero, stop movel, escada de lote, parada apos 3 perdas.

SEM FITA NAO OPERA. Se o arquivo da fita nao existe ou parou (robo 1.3 desligado, MetaTrader
fechado), o robo fica parado e diz isso na tela: leitura de fluxo sem fluxo seria a regra
antiga com outro nome.

Nada aqui manda ordem. Uso: python -m quant.daytrade.robo_fluxo [--uma-vez]
"""
import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime

from quant.comum import agora_brt, garantir_dir, gravar_atomico, ler_json, log
from quant.daytrade import estrategia as es
from quant.daytrade import estrategia_fluxo as ef
from quant.daytrade import fluxo as fx
from quant.daytrade.robo import (ABERTURA, ATIVOS, DIARIO_MAX, DIR_DT, FIM_PROCESSO, I_ABE, I_ANT, I_HORA, I_MAX,
                                 I_MEDIO, I_MIN, I_ULT, I_VAR, INTERVALO, MOTOR, SAIDAS_PADRAO, _num, _pontos, _reais,
                                 ler_motor)

ARQ_SERIE = os.path.join(DIR_DT, "serie_fluxo.json")
FITA_PARADA_S = 30.0


class RoboFluxo:
    def __init__(self, hoje, saidas=None, motor=MOTOR, pasta_mt5=fx.PASTA_MT5):
        self.hoje = str(hoje)
        self.saidas = list(saidas or SAIDAS_PADRAO)
        self.motor = motor
        self.p = ef.ParamFluxo()
        self.pasta = os.path.join(DIR_DT, self.hoje)
        garantir_dir(self.pasta)
        self.arq_estado = os.path.join(self.pasta, "estado_fluxo.json")
        salvo = ler_json(self.arq_estado, padrao=None) or {}
        self.estados = {}
        for a in ATIVOS:
            e = ef.EstadoF(a)
            s = (salvo.get("estados") or {}).get(a) or {}
            e.operacoes = int(s.get("operacoes") or 0)
            e.ultima_saida_ts = float(s.get("ultima_saida_ts") or 0.0)
            e.lado_dos_niveis = dict(s.get("lado_dos_niveis") or {})
            if isinstance(s.get("posicao"), dict):
                e.posicao = ef.PosicaoF(**s["posicao"])
            self.estados[a] = e
        self.operacoes = list(salvo.get("operacoes") or [])      # parciais e saidas, na ordem
        self.diario = list(salvo.get("diario") or [])
        self.curva = list(salvo.get("curva") or [])
        self.trava = salvo.get("trava")                          # None | "meta" | "perda" | "tres_perdas"
        self.perdas = int(salvo.get("perdas") or 0)              # negocios (entrada ate a saida final) que perderam
        self.negocio = dict(salvo.get("negocio") or {})          # ativo -> resultado acumulado do negocio aberto
        self.pico, self.vale = float(salvo.get("pico") or 0.0), float(salvo.get("vale") or 0.0)
        self.desde = salvo.get("desde") or agora_brt().isoformat(timespec="seconds")
        self.marcos = set(salvo.get("marcos") or [])
        self.codigos = dict(salvo.get("codigos") or {})          # WINFUT -> WINV26
        self.ajustes = dict(salvo.get("ajustes") or {})
        self.leitor = fx.Leitor(pasta=pasta_mt5, dia=self.hoje.replace("-", ""))
        self.fitas = {a: fx.Fita(a, es.CONTRATOS[a]["tick"]) for a in ATIVOS}
        self.ultima_fita = 0.0                                   # relogio da ultima linha de fita recebida
        self.cot, self.feed, self.feed_em, self.livro = {}, {}, 0.0, {}
        self.acumulado_antes = self._acumulado_antes()

    # ── persistencia ─────────────────────────────────────────
    def _acumulado_antes(self):
        serie = ler_json(ARQ_SERIE, padrao=None)
        return sum(float(x.get("resultado") or 0.0) for x in (serie if isinstance(serie, list) else [])
                   if isinstance(x, dict) and x.get("data") != self.hoje)

    def _salvar(self):
        est = {a: {"operacoes": e.operacoes, "ultima_saida_ts": e.ultima_saida_ts, "lado_dos_niveis": e.lado_dos_niveis,
                   "posicao": asdict(e.posicao) if e.posicao else None} for a, e in self.estados.items()}
        gravar_atomico(self.arq_estado, json.dumps({
            "desde": self.desde, "estados": est, "operacoes": self.operacoes, "diario": self.diario[-DIARIO_MAX:],
            "curva": self.curva[-700:], "trava": self.trava, "perdas": self.perdas, "negocio": self.negocio,
            "pico": self.pico, "vale": self.vale, "marcos": sorted(self.marcos), "codigos": self.codigos,
            "ajustes": self.ajustes}, ensure_ascii=False))

    def anotar(self, tipo, texto, agora=None):
        self.diario.append({"hora": (agora or agora_brt()).strftime("%H:%M:%S"), "tipo": tipo, "texto": texto})
        self.diario = self.diario[-DIARIO_MAX:]
        log(f"[{tipo}] {texto}")

    def marco(self, chave, tipo, texto, agora=None):
        if chave in self.marcos:
            return False
        self.marcos.add(chave)
        self.anotar(tipo, texto, agora)
        return True

    # ── fita, contratos e ajuste ─────────────────────────────
    def preparar(self):
        """Descobre o contrato vigente de cada futuro, pede a fita dele e le o ajuste de ontem."""
        for a in ATIVOS:
            if a not in self.codigos:
                s = ler_motor(f"/vivo/intradia?s={a}&dias=1", self.motor, timeout=8.0) or {}
                if s.get("codigo"):
                    self.codigos[a] = str(s["codigo"])
        if len(self.codigos) == len(ATIVOS):
            try:
                self.leitor.pedir(list(self.codigos.values()))
            except OSError as e:
                log(f"nao consegui pedir a fita ao MetaTrader: {e}")
        try:                                             # ajuste de ontem: coluna 12 da foto do robo do MetaTrader
            with open(os.path.join(self.leitor.pasta, "autopilot_feed.csv"), "r", encoding="latin-1", errors="ignore") as f:
                for ln in f:
                    c = ln.strip().split(";")
                    for a, cod in self.codigos.items():
                        if c and c[0] == cod and len(c) > 12 and (_num(c[12]) or 0) > 0:
                            self.ajustes[a] = _num(c[12])
        except OSError:
            pass

    def ler_fita(self):
        de = {cod: a for a, cod in self.codigos.items()}
        n = 0
        for ln in self.leitor.novas_linhas():
            a = de.get(ln["simbolo"])
            if a:
                self.fitas[a].tick = es.CONTRATOS[a]["tick"]
                ln = dict(ln, simbolo=a)
                self.fitas[a].acrescentar(ln)
                n += 1
        if n:
            self.ultima_fita = time.time()
        return n

    # ── contas ───────────────────────────────────────────────
    def resultado(self):
        realizado = sum(float(o["resultado"]) for o in self.operacoes)
        custos = sum(float(o["custos"]) for o in self.operacoes)
        aberto = 0.0
        for a, e in self.estados.items():
            c = self.cot.get(a)
            if e.posicao is not None and c:
                k = es.CONTRATOS[a]
                pts = ef._pontos(e.posicao, c["preco"])
                cst = 2 * k["custo"] * e.posicao.contratos
                aberto += pts * k["valor_ponto"] * e.posicao.contratos - cst
                custos += cst
        return realizado, aberto, custos

    def _frescor(self):
        if time.time() - self.feed_em < 6.0:
            return
        self.feed_em = time.time()
        s = ler_motor("/vivo/saude", self.motor, timeout=2.0)
        mt5 = next((f for f in ((s or {}).get("fontes") or []) if f.get("id") == "mt5"), None)
        self.feed = {} if not mt5 else {
            "sem_tique_s": _num((mt5.get("idade_s") or {}).get("menor")),
            "atraso_ms": _num((mt5.get("atraso_tique_acima_do_melhor_ms") or {}).get("p50")), "mt5": mt5.get("estado")}

    def _registrar(self, ev, agora):
        a, nome = ev["ativo"], es.CONTRATOS[ev["ativo"]]["nome"]
        if ev["tipo"] == "entrada":
            self.negocio[a] = 0.0
            m = ev.get("medidas") or {}
            self.anotar("entrada", f"{nome}: {'COMPROU' if ev['lado'] == 'C' else 'VENDEU'} {ev['contratos']} a {_pontos(ev['entrada'], a)} "
                        f"por {ev['tecnica']} em {ev['nome_nivel']} ({_pontos(ev['nivel'], a)}); stop {_pontos(ev['stop'], a)}; "
                        f"{(m.get('fracao_a_favor') or 0) * 100:.0f}% da agressão a favor", agora)
            return
        ev = dict(ev, n=len(self.operacoes) + 1)
        self.operacoes.append(ev)
        self.negocio[a] = float(self.negocio.get(a) or 0.0) + float(ev["resultado"])
        sinal = "+" if ev["pontos"] >= 0 else ""
        if ev["tipo"] == "parcial":
            self.anotar("parcial", f"{nome}: parcial de {ev['contratos']} a {_pontos(ev['saida'], a)} ({sinal}{_pontos(ev['pontos'], a)} pontos, "
                        f"{_reais(ev['resultado'])}); stop no preço de entrada.", agora)
            return
        total = self.negocio.pop(a, 0.0)
        if total < 0:
            self.perdas += 1
        self.anotar("saida", f"{nome}: saiu por {ev['motivo'].replace('_', ' ')} a {_pontos(ev['saida'], a)} ({sinal}{_pontos(ev['pontos'], a)} pontos); "
                    f"negócio fechou em {_reais(total)}.", agora)

    # ── um ciclo ─────────────────────────────────────────────
    def ciclo(self, agora=None, retrato=None):
        agora = agora or agora_brt()
        hora, ts = agora.strftime("%H:%M:%S"), agora.timestamp()
        if retrato is None:
            retrato = ler_motor("/vivo/retrato", self.motor)
        self._frescor()
        pregao = agora.weekday() < 5 and ABERTURA <= hora[:5]
        if pregao and (len(self.codigos) < len(ATIVOS) or int(ts) % 60 == 0):
            self.preparar()
        self.ler_fita()
        fita_ok = (time.time() - self.ultima_fita) <= FITA_PARADA_S if self.ultima_fita else False
        q = (retrato or {}).get("q") or {}
        lote = ef.lote_do_dia(self.acumulado_antes, self.p)
        for a in ATIVOS:
            c = q.get(a)
            if not isinstance(c, list) or len(c) <= I_HORA:
                continue
            preco, ts_tique = _num(c[I_ULT]), _num(c[I_HORA])
            de_hoje = ts_tique is not None and datetime.fromtimestamp(ts_tique, agora.tzinfo).strftime("%Y-%m-%d") == self.hoje
            if preco is None or preco <= 0 or not de_hoje or not pregao:
                continue
            idade = ts - ts_tique
            self.cot[a] = {"preco": preco, "medio": _num(c[I_MEDIO]) if len(c) > I_MEDIO else None, "maxima": _num(c[I_MAX]),
                           "minima": _num(c[I_MIN]), "abertura": _num(c[I_ABE]), "anterior": _num(c[I_ANT]),
                           "var": _num(c[I_VAR]), "idade_s": idade, "ajuste": self.ajustes.get(a)}
            if idade > 15.0:
                continue                                   # preco velho nao dispara nada
            for ev in ef.passo(self.estados[a], ts, hora, preco, self.fitas[a], ef.niveis_do_dia(self.cot[a]), self.p, lote,
                               pode_entrar=self.trava is None and fita_ok, feed_ok=True):
                self._registrar(ev, agora)
        realizado, aberto, _c = self.resultado()
        total = realizado + aberto
        motivo = None
        if self.trava is None:
            if total <= -self.p.capital * self.p.perda_maxima_dia:
                self.trava, motivo = "perda", "perda_maxima"
            elif total >= self.p.capital * self.p.meta_dia:
                self.trava, motivo = "meta", "meta"
            elif self.perdas >= self.p.perdas_para_parar and all(e.posicao is None for e in self.estados.values()):
                self.trava = "tres_perdas"
                self.anotar("trava", f"{self.perdas} negócios perdedores no dia: o robô não entra mais hoje.", agora)
        if motivo:
            for a in ATIVOS:
                c = self.cot.get(a)
                ev = ef.zerar(self.estados[a], ts, hora, c["preco"], motivo) if c else None
                if ev:
                    self._registrar(ev, agora)
            realizado, aberto, _c = self.resultado()
            total = realizado + aberto
            self.anotar("trava", ("Perda máxima do dia atingida" if self.trava == "perda" else "Meta do dia atingida")
                        + f": {_reais(total)}. Tudo zerado; o robô não entra mais hoje.", agora)
        self.pico, self.vale = max(self.pico, total), min(self.vale, total)
        if pregao:
            if self.curva and self.curva[-1][0] == hora[:5]:
                self.curva[-1][1] = round(total, 2)
            else:
                self.curva.append([hora[:5], round(total, 2)])
        estado = self.estado(agora, retrato, realizado, aberto, fita_ok, lote, pregao)
        self._gravar(estado)
        self._salvar()
        return estado

    # ── o estado que a tela le ───────────────────────────────
    def estado(self, agora, retrato, realizado, aberto, fita_ok, lote, pregao):
        p, hm = self.p, agora.strftime("%H:%M")
        total = realizado + aberto
        _r, _a, custos = self.resultado()
        parado, atraso = _num(self.feed.get("sem_tique_s")), _num(self.feed.get("atraso_ms"))
        em_hora = pregao and hm < p.hora_zerar
        feed_ruim = em_hora and ((parado is not None and parado > 15) or (atraso is not None and atraso > 5000))
        abertas = sum(1 for e in self.estados.values() if e.posicao is not None)
        if agora.weekday() >= 5 or hm < ABERTURA:
            fase, texto = "aguardando_abertura", "Aguardando a abertura dos futuros (9h00)."
        elif self.trava == "meta":
            fase, texto = "meta_batida", f"Meta do dia atingida ({_reais(total)}). Parado até amanhã."
        elif self.trava in ("perda", "tres_perdas"):
            fase = "perda_maxima"
            texto = (f"Perda máxima do dia atingida ({_reais(total)}). Parado até amanhã." if self.trava == "perda"
                     else f"{self.perdas} negócios perdedores no dia ({_reais(total)}). Parado até amanhã.")
        elif hm < p.hora_inicio:
            fase, texto = "formando_faixa", f"Lendo o fluxo da abertura; entradas a partir das {p.hora_inicio}."
        elif hm >= p.hora_zerar:
            fase, texto = "encerrado", f"Operações encerradas ({p.hora_zerar}). Resultado do dia: {_reais(total)}."
        elif hm >= p.hora_ultima_entrada:
            fase, texto = "encerrando", f"Sem novas entradas desde as {p.hora_ultima_entrada}; {abertas} posição(ões) aberta(s) até as {p.hora_zerar}."
        else:
            fase = "operando"
            texto = (f"Lendo o fluxo: {abertas} posição(ões) aberta(s), {len(self.operacoes)} saída(s) e parcial(is), "
                     f"resultado do dia {_reais(total)}.")
        avisos = ["Simulação: nenhuma ordem é enviada à corretora.",
                  "Regra inspirada no que Alison Correia mostra no canal dele, sem a parte que depende de saber qual corretora está "
                  "de cada lado (o MetaTrader não informa). Os limiares de \"muita agressão\" são nossos, ainda sem teste histórico.",
                  "Os números do mini-índice são os do mini-dólar levados na proporção do preço: ele quase não mostra índice.",
                  "Custos da B3 estimados e 1 tick contra nas ordens a mercado; imposto de day trade (20%) não descontado."]
        if em_hora and not fita_ok:
            alerta = ("ATENÇÃO: sem a fita de negócios do MetaTrader (robô 1.3 desligado ou parado). "
                      "Sem fluxo o robô não entra; posição aberta segue com o stop.")
            avisos.insert(0, alerta)
            texto = alerta + " " + texto
        elif feed_ruim:
            alerta = "ATENÇÃO: cotações da B3 atrasadas ou paradas (MetaTrader). Com preço velho o robô não entra nem sai."
            avisos.insert(0, alerta)
            texto = alerta + " " + texto
        instrumentos, ops = [], [dict(o, aberta=False) for o in self.operacoes]
        for a in ATIVOS:
            e, c, k, f = self.estados[a], self.cot.get(a) or {}, es.CONTRATOS[a], self.fitas[a]
            pr = c.get("preco")
            pos = None
            if e.posicao is not None:
                pts = ef._pontos(e.posicao, pr) if pr is not None else None
                ab = (pts * k["valor_ponto"] * e.posicao.contratos - 2 * k["custo"] * e.posicao.contratos) if pts is not None else None
                pos = dict(asdict(e.posicao), pontos=pts, aberto=ab, alvo=None, risco_pts=abs(e.posicao.entrada - e.posicao.stop),
                           protegido=e.posicao.parcial_feita)
                ops.append({"n": len(ops) + 1, "ativo": a, "lado": e.posicao.lado, "contratos": e.posicao.contratos,
                            "entrada": e.posicao.entrada, "hora_entrada": e.posicao.hora, "saida": None, "hora_saida": None,
                            "motivo": None, "stop": e.posicao.stop, "alvo": None, "pontos": pts,
                            "custos": 2 * k["custo"] * e.posicao.contratos, "resultado": ab, "aberta": True,
                            "tecnica": e.posicao.tecnica, "nome_nivel": e.posicao.nome_nivel})
            a15, a60 = f.agressao(15), f.agressao(60)
            niveis = [{"nome": n, "preco": v, "distancia_pts": (pr - v) if pr is not None else None}
                      for n, v in ef.niveis_do_dia(c)]
            livro = (self.livro or {}).get(self.codigos.get(a) or "", {})
            fechadas = [o for o in self.operacoes if o["ativo"] == a]
            instrumentos.append({
                "ativo": a, "nome": k["nome"], "contrato": self.codigos.get(a), "valor_ponto": k["valor_ponto"], "tick": k["tick"],
                "ultimo": pr, "variacao_pct": c.get("var"), "medio_dia": c.get("medio"), "maxima": c.get("maxima"),
                "minima": c.get("minima"), "abertura": c.get("abertura"), "anterior": c.get("anterior"), "ajuste": c.get("ajuste"),
                "idade_s": c.get("idade_s"),
                "lado_do_medio": (None if pr is None or not c.get("medio") else ("acima" if pr > c["medio"] else "abaixo")),
                "faixa_abertura": None, "gatilho_compra": None, "gatilho_venda": None,
                "risco_pts_agora": ef.ATIVOS[a].stop_pts,
                "niveis": niveis,
                "fluxo": {"agressao_15s": a15, "agressao_60s": a60, "tipico_30s": f.volume_tipico(p.janela_tipico_s),
                          "linhas": len(f.linhas),
                          "livro_compra": (livro.get("compra") or [])[:5], "livro_venda": (livro.get("venda") or [])[:5]},
                "posicao": pos, "operacoes_hoje": e.operacoes, "restam": max(p.max_operacoes - e.operacoes, 0),
                "resultado": sum(float(o["resultado"]) for o in fechadas) + ((pos or {}).get("aberto") or 0.0)})
        finais = [o for o in self.operacoes if o["tipo"] == "saida"]
        ganhos = [o for o in self.operacoes if o["resultado"] > 0]
        perdas = [o for o in self.operacoes if o["resultado"] <= 0]
        serie = self._serie(total, len(finais), pregao)
        acumulado = sum(float(x.get("resultado") or 0.0) for x in serie)
        return {
            "v": 2, "tipo": "daytrade", "regra": "fluxo", "gerado": agora.isoformat(timespec="seconds"),
            "vivo": {"ligado": True, "fase": fase, "fase_texto": texto, "desde": self.desde,
                     "batida": agora.isoformat(timespec="seconds"), "intervalo_s": INTERVALO,
                     "motor": {"ok": retrato is not None and not feed_ruim and (fita_ok or not em_hora),
                               "b3_sem_tique_s": parado, "b3_atraso_ms": atraso, "mt5": self.feed.get("mt5"),
                               "fita_ok": fita_ok}},
            "modo": "paper", "origem": "real", "capital": p.capital, "pronto": True, "bloqueios": [], "avisos": avisos,
            "regras": {"nome": "Leitura de fluxo: defesa e perda de nível, conduzidas como Alison Correia mostra (versão 1)",
                       "itens": ef.regras_em_texto(p), "parametros": dict(asdict(p), lote_hoje=lote)},
            "resultado": {"dia": total, "dia_pct": total / p.capital if p.capital else None, "realizado": realizado,
                          "aberto": aberto, "custos": custos, "operacoes": len(finais), "abertas": abertas,
                          "ganhadoras": len(ganhos), "perdedoras": len(perdas),
                          "taxa_acerto": (len(ganhos) / len(self.operacoes)) if self.operacoes else None,
                          "maior_ganho": max((o["resultado"] for o in ganhos), default=None),
                          "maior_perda": min((o["resultado"] for o in perdas), default=None),
                          "meta": p.capital * p.meta_dia, "perda_maxima": -p.capital * p.perda_maxima_dia,
                          "pico": self.pico, "vale": self.vale, "trava": ("perda" if self.trava == "tres_perdas" else self.trava),
                          "negocios_perdedores": self.perdas, "lote_hoje": lote,
                          "patrimonio": p.capital + acumulado, "acumulado": acumulado, "dias": len(serie)},
            "instrumentos": instrumentos, "operacoes": list(reversed(ops)),
            "curva": [{"hora": h, "resultado": v} for h, v in self.curva], "serie": serie,
            "diario": list(reversed(self.diario[-DIARIO_MAX:])),
            "fontes": {"cotacoes": "motor do Autopilot Terminal (MetaTrader)",
                       "fluxo": "AutopilotFeed 1.3: negócios por segundo com o lado agressor e livro de ofertas",
                       "regra": "quant/daytrade/estrategia_fluxo.py", "metodo": "quant/docs/metodo-alison-correia.md"}}

    def _serie(self, total, n_ops, pregao):
        serie = ler_json(ARQ_SERIE, padrao=None)
        serie = [x for x in (serie if isinstance(serie, list) else []) if isinstance(x, dict) and x.get("data") != self.hoje]
        if pregao and (self.ultima_fita or self.operacoes):
            serie.append({"data": self.hoje, "resultado": round(float(total), 2), "operacoes": int(n_ops)})
            try:
                garantir_dir(DIR_DT)
                gravar_atomico(ARQ_SERIE, json.dumps(serie, ensure_ascii=False))
            except OSError:
                pass
        acum = 0.0
        for x in serie:
            acum += float(x.get("resultado") or 0.0)
            x["patrimonio"] = round(self.p.capital + acum, 2)
        return serie[-400:]

    def _gravar(self, estado):
        from quant.rodar_diario import limpar
        texto = json.dumps(limpar(estado), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        for c in self.saidas:
            try:
                garantir_dir(os.path.dirname(c))
                gravar_atomico(c, texto)
            except OSError as e:
                log(f"nao gravei {c}: {type(e).__name__}: {e}")


def rodar(uma_vez=False, saidas=None, motor=MOTOR, intervalo=INTERVALO, ate=FIM_PROCESSO):
    agora = agora_brt()
    hoje = agora.strftime("%Y-%m-%d")
    if not uma_vez:
        import fcntl
        garantir_dir(DIR_DT)
        trava = open(os.path.join(DIR_DT, "robo.trava"), "w")       # a mesma trava do robo antigo: um so por maquina
        try:
            fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log("ja existe um robo de day trade nesta maquina; este processo sai sem fazer nada")
            return 3
    robo = RoboFluxo(hoje, saidas=saidas, motor=motor)
    robo.marco("ligado_fluxo", "preparo", "Robô de day trade por leitura de fluxo ligado (simulação), regra versão 1.", agora)
    n = 0
    while True:
        agora = agora_brt()
        try:
            if n % 5 == 0:
                robo.livro = robo.leitor.livro()
            robo.ciclo(agora)
        except Exception as e:
            log(f"ciclo falhou: {type(e).__name__}: {e}")
        n += 1
        hm = agora.strftime("%H:%M")
        if uma_vez or hm >= ate or agora.strftime("%Y-%m-%d") != hoje:
            return 0
        time.sleep(intervalo if ABERTURA <= hm < "17:25" else 10.0)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Robo de day trade por leitura de fluxo (simulacao)")
    ap.add_argument("--uma-vez", action="store_true")
    ap.add_argument("--saida", action="append")
    args = ap.parse_args(argv)
    return rodar(uma_vez=args.uma_vez, saidas=args.saida)


if __name__ == "__main__":
    sys.exit(main())
