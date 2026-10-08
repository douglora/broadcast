"""
Robo de day trade em mini-indice (WIN) e mini-dolar (WDO), em SIMULACAO.

Le as cotacoes ao vivo do motor do Autopilot Terminal (GET /vivo/retrato, uma vez por
segundo), aplica a regra de `estrategia.py` e grava o estado que a area QUANT do terminal
desenha. Compra e vende, zera tudo antes do fim do pregao e nao dorme posicionado.

NADA AQUI MANDA ORDEM. Nao ha codigo de envio nem credencial: cada "execucao" e uma conta
feita sobre o preco que o MetaTrader mostrou, com 1 tick contra nas ordens a mercado e os
custos da B3 estimados. O resultado e de simulacao.

REINICIO NO MEIO DO DIA. O estado (posicoes, operacoes, barras de 1 minuto, diario) fica em
`quant/saida/daytrade/<data>/estado.json`; quem cai e volta continua de onde parou. Na
primeira subida do dia as barras vem da serie de minutos do motor (GET /vivo/intradia) e a
maxima e a minima do dia vem do proprio MetaTrader.

Uso:
    python -m quant.daytrade.robo            # roda ate o fim do pregao
    python -m quant.daytrade.robo --uma-vez  # grava o estado uma vez e sai
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from dataclasses import asdict
from datetime import datetime

from quant.comum import DIR_SAIDA, agora_brt, garantir_dir, gravar_atomico, ler_json, log
from quant.daytrade import chave
from quant.daytrade import estrategia as es

MOTOR = os.environ.get("QUANT_MOTOR", "http://127.0.0.1:8930")
INTERVALO = 1.0
DIR_DT = os.path.join(DIR_SAIDA, "daytrade")
ARQ_SERIE = os.path.join(DIR_DT, "serie.json")
SAIDAS_PADRAO = [os.path.expanduser(p) for p in os.environ.get(
    "QUANT_SAIDA",
    "~/Desktop/terminal-artefato/web/d/x/quant.json:~/Desktop/terminal-artefato/cache/out/pagina/quant.json"
).split(":") if p]
ATIVOS = ("WINFUT", "WDOFUT")
ABERTURA, FIM_PROCESSO = "09:00", "18:30"
DIARIO_MAX = 300
# posicoes do vetor de cotacao do motor: ultimo, var%, abertura, maxima, minima, volume,
# fechamento anterior, hora do tique, ..., preco medio do dia (13)
I_ULT, I_VAR, I_ABE, I_MAX, I_MIN, I_VOL, I_ANT, I_HORA, I_MEDIO = 0, 1, 2, 3, 4, 5, 6, 7, 13


def _num(x):
    try:
        v = float(x)
        return v if v == v and abs(v) != float("inf") else None
    except (TypeError, ValueError):
        return None


def ler_motor(caminho, motor=MOTOR, timeout=4.0):
    try:
        with urllib.request.urlopen(motor + caminho, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _reais(v):
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if v < 0 else "") + "R$ " + s


def _pontos(v, ativo):
    casas = 1 if es.CONTRATOS[ativo]["tick"] < 1 else 0
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


class Robo:
    def __init__(self, hoje, saidas=None, motor=MOTOR, parametros=None):
        self.hoje = str(hoje)
        self.saidas = list(saidas or SAIDAS_PADRAO)
        self.motor = motor
        self.p = parametros or es.Parametros()
        self.janela = chave.janela(self.hoje)                   # a janela do dia e do Douglas (pode ter excecao por data)
        if parametros is None:
            self.p.hora_inicio, self.p.hora_ultima_entrada, self.p.hora_zerar = (
                self.janela["inicio"], self.janela["ultima_entrada"], self.janela["zerar"])
        self.pasta = os.path.join(DIR_DT, self.hoje)
        garantir_dir(self.pasta)
        self.arq_estado = os.path.join(self.pasta, "estado.json")
        salvo = ler_json(self.arq_estado, padrao=None) or {}
        self.estados = {}
        for a in ATIVOS:
            e = es.EstadoAtivo(ativo=a)
            s = (salvo.get("estados") or {}).get(a) or {}
            e.operacoes = int(s.get("operacoes") or 0)
            e.ultima_saida_ts = float(s.get("ultima_saida_ts") or 0.0)
            e.barras = [list(x) for x in (s.get("barras") or [])]
            e.semente_max, e.semente_min = _num(s.get("semente_max")), _num(s.get("semente_min"))
            if isinstance(s.get("posicao"), dict):
                e.posicao = es.Posicao(**s["posicao"])
            self.estados[a] = e
        self.operacoes = list(salvo.get("operacoes") or [])      # fechadas, na ordem
        self.diario = list(salvo.get("diario") or [])
        self.curva = list(salvo.get("curva") or [])              # [[HH:MM, resultado do dia]]
        self.trava = salvo.get("trava")                          # None | "meta" | "perda"
        self.pico = float(salvo.get("pico") or 0.0)
        self.vale = float(salvo.get("vale") or 0.0)
        self.desde = salvo.get("desde") or agora_brt().isoformat(timespec="seconds")
        self.marcos = set(salvo.get("marcos") or [])
        self.aquecido = bool(salvo.get("aquecido"))
        self.cot = {}                                            # ativo -> ultimo vetor visto
        self.chave = chave.ler()                                 # liga/desliga do Douglas
        self.feed = {}
        self.feed_em = 0.0

    # ── persistencia ─────────────────────────────────────────
    def _salvar(self):
        est = {}
        for a, e in self.estados.items():
            est[a] = {"operacoes": e.operacoes, "ultima_saida_ts": e.ultima_saida_ts, "barras": e.barras,
                      "semente_max": e.semente_max, "semente_min": e.semente_min,
                      "posicao": asdict(e.posicao) if e.posicao else None}
        gravar_atomico(self.arq_estado, json.dumps({
            "desde": self.desde, "estados": est, "operacoes": self.operacoes,
            "diario": self.diario[-DIARIO_MAX:], "curva": self.curva[-700:], "trava": self.trava,
            "pico": self.pico, "vale": self.vale, "marcos": sorted(self.marcos), "aquecido": self.aquecido,
        }, ensure_ascii=False))

    def anotar(self, tipo, texto, agora=None):
        hora = (agora or agora_brt()).strftime("%H:%M:%S")
        self.diario.append({"hora": hora, "tipo": tipo, "texto": texto})
        self.diario = self.diario[-DIARIO_MAX:]
        log(f"[{tipo}] {texto}")

    def marco(self, chave, tipo, texto, agora=None):
        if chave in self.marcos:
            return False
        self.marcos.add(chave)
        self.anotar(tipo, texto, agora)
        return True

    # ── aquecimento: barras do dia que o robo nao viu ────────
    def aquecer(self, agora, retrato):
        """Preenche as barras de hoje com a serie de minutos do motor e a maxima/minima do MetaTrader."""
        if self.aquecido:
            return
        q = (retrato or {}).get("q") or {}
        hoje0 = agora.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        minuto_atual = int(agora.timestamp() // 60) * 60
        for a in ATIVOS:
            e = self.estados[a]
            serie = ler_motor(f"/vivo/intradia?s={a}&dias=1", self.motor, timeout=8.0) or {}
            barras = {}
            for t, pr in zip(serie.get("t") or [], serie.get("p") or []):
                t, pr = _num(t), _num(pr)
                if t is None or pr is None or t < hoje0 or t >= minuto_atual:
                    continue
                m = int(t // 60) * 60
                b = barras.setdefault(m, [m, pr, pr, pr])
                b[1], b[2], b[3] = max(b[1], pr), min(b[2], pr), pr
            lista = [barras[k] for k in sorted(barras)]
            c = q.get(a)
            if isinstance(c, list) and len(c) > I_MIN:
                # a serie de minutos guarda so o ultimo preco de cada minuto: a maxima e a minima de
                # verdade do dia vem da sessao do MetaTrader e ficam como semente da referencia
                e.semente_max, e.semente_min = _num(c[I_MAX]), _num(c[I_MIN])
            if lista and not e.barras:
                e.barras = lista
        self.aquecido = True
        n = {a: len(self.estados[a].barras) for a in ATIVOS}
        self.anotar("preparo", f"Barras de 1 minuto de hoje carregadas: mini-índice {n['WINFUT']}, mini-dólar {n['WDOFUT']}.", agora)

    # ── contas do dia ────────────────────────────────────────
    def resultado(self):
        realizado = sum(float(o["resultado"]) for o in self.operacoes)
        custos = sum(float(o["custos"]) for o in self.operacoes)
        aberto = 0.0
        for a, e in self.estados.items():
            c = self.cot.get(a)
            if e.posicao is not None and c:
                aberto += es.resultado_reais(a, e.posicao, c["preco"], com_custos=True)
                custos += 2 * es.CONTRATOS[a]["custo"] * e.posicao.contratos
        return realizado, aberto, custos

    def _frescor(self):
        if time.time() - self.feed_em < 6.0:
            return
        self.feed_em = time.time()
        s = ler_motor("/vivo/saude", self.motor, timeout=2.0)
        mt5 = next((f for f in ((s or {}).get("fontes") or []) if f.get("id") == "mt5"), None)
        self.feed = {} if not mt5 else {
            "sem_tique_s": _num((mt5.get("idade_s") or {}).get("menor")),
            "atraso_ms": _num((mt5.get("atraso_tique_acima_do_melhor_ms") or {}).get("p50")),
            "mt5": mt5.get("estado")}

    # ── um ciclo ─────────────────────────────────────────────
    def ciclo(self, agora=None, retrato=None):
        agora = agora or agora_brt()
        hora = agora.strftime("%H:%M:%S")
        ts = agora.timestamp()
        if retrato is None:
            retrato = ler_motor("/vivo/retrato", self.motor)
        self._frescor()
        q = (retrato or {}).get("q") or {}
        pregao = agora.weekday() < 5 and ABERTURA <= hora[:5]
        if pregao and retrato is not None:
            self.aquecer(agora, retrato)
        realizado, aberto, _c = self.resultado()
        total = realizado + aberto
        limite_perda = -self.p.capital * self.p.perda_maxima_dia
        meta = self.p.capital * self.p.meta_dia
        self.chave = chave.ler()
        if not self.chave["ligado"]:                       # o Douglas desligou: zera o que houver e nao entra
            for a in ATIVOS:
                c = self.cot.get(a)
                ev = es.zerar(self.estados[a], ts, hora, c["preco"], "desligado") if c else None
                if ev:
                    self._registrar(ev, agora)
        for a in ATIVOS:
            c = q.get(a)
            if not isinstance(c, list) or len(c) <= I_HORA:
                continue
            preco, ts_tique = _num(c[I_ULT]), _num(c[I_HORA])
            de_hoje = ts_tique is not None and datetime.fromtimestamp(ts_tique, agora.tzinfo).strftime("%Y-%m-%d") == self.hoje
            if preco is None or preco <= 0 or not de_hoje or not pregao:
                continue
            medio = _num(c[I_MEDIO]) if len(c) > I_MEDIO else None
            idade = ts - ts_tique
            self.cot[a] = {"preco": preco, "medio": medio, "maxima": _num(c[I_MAX]), "minima": _num(c[I_MIN]),
                           "abertura": _num(c[I_ABE]), "anterior": _num(c[I_ANT]), "var": _num(c[I_VAR]),
                           "idade_s": idade}
            feed_ok = idade <= self.p.feed_parado_s
            if not feed_ok:
                continue                               # preco velho nao dispara stop nem entrada: espera o tique
            e = self.estados[a]
            eventos = es.passo(e, ts, hora, preco, medio, self.p, pode_entrar=self.trava is None and self.chave["ligado"],
                               feed_ok=feed_ok)
            for ev in eventos:
                self._registrar(ev, agora)
        # travas do dia: olhadas depois dos tiques, com o resultado ja atualizado
        realizado, aberto, _c = self.resultado()
        total = realizado + aberto
        if self.trava is None and (total <= limite_perda or total >= meta):
            self.trava = "perda" if total <= limite_perda else "meta"
            for a in ATIVOS:
                c = self.cot.get(a)
                if c:
                    ev = es.zerar(self.estados[a], ts, hora, c["preco"], "perda_maxima" if self.trava == "perda" else "meta")
                    if ev:
                        self._registrar(ev, agora)
            realizado, aberto, _c = self.resultado()
            total = realizado + aberto
            self.anotar("trava", ("Perda máxima do dia atingida" if self.trava == "perda" else "Meta do dia atingida")
                        + f": {_reais(total)}. Tudo zerado; o robô não entra mais hoje.", agora)
        self.pico, self.vale = max(self.pico, total), min(self.vale, total)
        if pregao and hora[:5] >= "09:00":
            hm = hora[:5]
            if self.curva and self.curva[-1][0] == hm:
                self.curva[-1][1] = round(total, 2)
            else:
                self.curva.append([hm, round(total, 2)])
        if hora[:5] >= self.p.hora_zerar and pregao:
            self.marco("zerado", "fechamento", f"Fim das operações do dia ({self.p.hora_zerar}): nenhuma posição aberta. "
                       f"Resultado do dia: {_reais(total)} em {len(self.operacoes)} operação(ões).", agora)
        estado = self.estado(agora, retrato, realizado, aberto)
        self._gravar(estado)
        self._salvar()
        return estado

    def _registrar(self, ev, agora):
        a = ev["ativo"]
        nome = es.CONTRATOS[a]["nome"]
        if ev["tipo"] == "entrada":
            verbo = "COMPROU" if ev["lado"] == "C" else "VENDEU"
            self.anotar("entrada", f"{nome}: {verbo} {ev['contratos']} contrato(s) a {_pontos(ev['entrada'], a)} "
                        f"(rompeu {_pontos(ev['rompeu'], a)}; stop {_pontos(ev['stop'], a)}, alvo {_pontos(ev['alvo'], a)})", agora)
        elif ev["tipo"] == "protecao":
            self.anotar("protecao", f"{nome}: stop levado para a entrada ({_pontos(ev['stop'], a)}).", agora)
        elif ev["tipo"] == "saida":
            ev = dict(ev, n=len(self.operacoes) + 1)
            self.operacoes.append(ev)
            motivos = {"stop": "stop", "alvo": "alvo", "protecao": "stop na entrada", "fim_do_dia": "fim do dia",
                       "meta": "meta do dia", "perda_maxima": "perda máxima do dia"}
            self.anotar("saida", f"{nome}: saiu por {motivos.get(ev['motivo'], ev['motivo'])} a {_pontos(ev['saida'], a)} "
                        f"({'+' if ev['pontos'] >= 0 else ''}{_pontos(ev['pontos'], a)} pontos, {_reais(ev['resultado'])})", agora)

    # ── o estado que a tela le ───────────────────────────────
    def estado(self, agora, retrato, realizado, aberto):
        p = self.p
        hora = agora.strftime("%H:%M:%S")
        hm = hora[:5]
        total = realizado + aberto
        _r, _a, custos = self.resultado()
        parado, atraso = _num(self.feed.get("sem_tique_s")), _num(self.feed.get("atraso_ms"))
        pregao = agora.weekday() < 5 and ABERTURA <= hm < FIM_PROCESSO
        feed_ruim = pregao and hm < p.hora_zerar and ((parado is not None and parado > p.feed_parado_s)
                                                      or (atraso is not None and atraso > 5000))
        abertas = sum(1 for e in self.estados.values() if e.posicao is not None)
        if agora.weekday() >= 5 or hm < ABERTURA:
            fase, texto = "aguardando_abertura", "Aguardando a abertura dos futuros (9h00)."
        elif not self.chave["ligado"]:
            fase = "desligado"
            texto = (f"Robô DESLIGADO por você às {chave.hora_de(self.chave)}. Nada aberto, nenhuma entrada. "
                     f"Resultado do dia: {_reais(total)}. Para religar: ícone \"Robô - ligar\" na Mesa, ou peça \"ligue o robô\".")
        elif self.trava == "meta":
            fase, texto = "meta_batida", f"Meta do dia atingida ({_reais(total)}). Parado até amanhã."
        elif self.trava == "perda":
            fase, texto = "perda_maxima", f"Perda máxima do dia atingida ({_reais(total)}). Parado até amanhã."
        elif hm < p.hora_inicio:
            fase, texto = "formando_faixa", f"Formando a faixa de abertura; entradas a partir das {p.hora_inicio}."
        elif hm >= p.hora_zerar:
            fase, texto = "encerrado", f"Operações encerradas ({p.hora_zerar}). Resultado do dia: {_reais(total)}."
        elif hm >= p.hora_ultima_entrada:
            fase, texto = "encerrando", (f"Sem novas entradas desde as {p.hora_ultima_entrada}; "
                                         f"{abertas} posição(ões) aberta(s) até as {p.hora_zerar}.")
        else:
            fase = "operando"
            texto = (f"Operando: {abertas} posição(ões) aberta(s), {len(self.operacoes)} operação(ões) fechada(s), "
                     f"resultado do dia {_reais(total)}.")
        avisos = ["Simulação: nenhuma ordem é enviada à corretora.",
                  "Regra na versão 0, ainda SEM teste histórico: o que aparece aqui é observação, não evidência de que a regra ganha.",
                  "Custos da B3 estimados (mini-índice R$ 0,30 e mini-dólar R$ 1,20 por contrato e por lado) e 1 tick contra "
                  "nas ordens a mercado. Imposto de day trade (20% sobre o ganho líquido do mês) não descontado."]
        if feed_ruim:
            quanto = (f"sem negócio novo há {parado:.0f} s" if (parado or 0) > p.feed_parado_s
                      else f"chegando com {(atraso or 0) / 1000:.0f} s de atraso")
            alerta = f"ATENÇÃO: cotações da B3 {quanto} (MetaTrader). Com preço velho o robô não entra nem sai."
            avisos.insert(0, alerta)
            texto = alerta + " " + texto
        if retrato is None:
            avisos.insert(0, "Motor do terminal sem resposta: cotações paradas até ele voltar.")

        instrumentos = []
        for a in ATIVOS:
            e, c, k = self.estados[a], self.cot.get(a) or {}, es.CONTRATOS[a]
            ref = es.referencias(e, agora.timestamp(), p)
            pos = None
            if e.posicao is not None:
                pr = c.get("preco")
                pos = dict(asdict(e.posicao),
                           pontos=es.resultado_pontos(e.posicao, pr) if pr is not None else None,
                           aberto=es.resultado_reais(a, e.posicao, pr, com_custos=True) if pr is not None else None)
            fechadas = [o for o in self.operacoes if o["ativo"] == a]
            abertura = [x for x in e.barras if datetime.fromtimestamp(x[0], agora.tzinfo).strftime("%H:%M") < p.hora_inicio]
            instrumentos.append({
                "ativo": a, "nome": k["nome"], "valor_ponto": k["valor_ponto"], "tick": k["tick"],
                "ultimo": c.get("preco"), "variacao_pct": c.get("var"), "medio_dia": c.get("medio"),
                "maxima": c.get("maxima"), "minima": c.get("minima"), "abertura": c.get("abertura"),
                "anterior": c.get("anterior"), "idade_s": c.get("idade_s"),
                "lado_do_medio": (None if c.get("preco") is None or not c.get("medio") else
                                  ("acima" if c["preco"] > c["medio"] else "abaixo")),
                "faixa_abertura": ([min(x[2] for x in abertura), max(x[1] for x in abertura)] if abertura else None),
                "gatilho_compra": (ref[0] + k["tick"]) if ref else None,
                "gatilho_venda": (ref[1] - k["tick"]) if ref else None,
                "risco_pts_agora": es.risco_em_pontos(a, ref[2]) if ref else None,
                "posicao": pos, "operacoes_hoje": e.operacoes, "restam": max(p.max_operacoes - e.operacoes, 0),
                "resultado": sum(float(o["resultado"]) for o in fechadas) + ((pos or {}).get("aberto") or 0.0),
            })
        ops = []
        for o in self.operacoes:
            ops.append(dict(o, aberta=False))
        for a in ATIVOS:
            e = self.estados[a]
            if e.posicao is not None:
                pr = (self.cot.get(a) or {}).get("preco")
                ops.append({"n": len(ops) + 1, "ativo": a, "lado": e.posicao.lado, "contratos": e.posicao.contratos,
                            "entrada": e.posicao.entrada, "hora_entrada": e.posicao.hora, "saida": None,
                            "hora_saida": None, "motivo": None, "stop": e.posicao.stop, "alvo": e.posicao.alvo,
                            "pontos": es.resultado_pontos(e.posicao, pr) if pr is not None else None,
                            "custos": 2 * es.CONTRATOS[a]["custo"] * e.posicao.contratos,
                            "resultado": es.resultado_reais(a, e.posicao, pr, com_custos=True) if pr is not None else None,
                            "aberta": True})
        ganhos = [o for o in self.operacoes if o["resultado"] > 0]
        perdas = [o for o in self.operacoes if o["resultado"] <= 0]
        serie = self._serie(total, len(self.operacoes), pregao)
        acumulado = sum(float(x.get("resultado") or 0.0) for x in serie)
        return {
            "v": 2, "tipo": "daytrade",
            "gerado": agora.isoformat(timespec="seconds"),
            "vivo": {"ligado": True, "fase": fase, "fase_texto": texto, "desde": self.desde,
                     "batida": agora.isoformat(timespec="seconds"), "intervalo_s": INTERVALO,
                     "motor": {"ok": retrato is not None and not feed_ruim, "b3_sem_tique_s": parado,
                               "b3_atraso_ms": atraso, "mt5": self.feed.get("mt5")}},
            "modo": "paper", "origem": "real", "capital": p.capital,
            "pronto": True, "bloqueios": [], "avisos": avisos,
            "regras": {"nome": "Rompimento da máxima ou da mínima do dia, a favor do preço médio (versão 0)",
                       "itens": es.regras_em_texto(p), "parametros": asdict(p)},
            "resultado": {"dia": total, "dia_pct": total / p.capital if p.capital else None,
                          "realizado": realizado, "aberto": aberto, "custos": custos,
                          "operacoes": len(self.operacoes), "abertas": abertas,
                          "ganhadoras": len(ganhos), "perdedoras": len(perdas),
                          "taxa_acerto": (len(ganhos) / len(self.operacoes)) if self.operacoes else None,
                          "maior_ganho": max((o["resultado"] for o in ganhos), default=None),
                          "maior_perda": min((o["resultado"] for o in perdas), default=None),
                          "meta": p.capital * p.meta_dia, "perda_maxima": -p.capital * p.perda_maxima_dia,
                          "pico": self.pico, "vale": self.vale, "trava": self.trava,
                          "patrimonio": p.capital + acumulado, "acumulado": acumulado, "dias": len(serie)},
            "instrumentos": instrumentos,
            "operacoes": list(reversed(ops)),
            "curva": [{"hora": h, "resultado": v} for h, v in self.curva],
            "serie": serie,
            "diario": list(reversed(self.diario[-DIARIO_MAX:])),
            "fontes": {"cotacoes": "motor do Autopilot Terminal (MetaTrader: último preço, máxima, mínima e preço médio da sessão)",
                       "regra": "quant/daytrade/estrategia.py"},
        }

    def _serie(self, total, n_ops, pregao):
        serie = ler_json(ARQ_SERIE, padrao=None)
        serie = [x for x in (serie if isinstance(serie, list) else []) if isinstance(x, dict) and x.get("data") != self.hoje]
        if pregao and self.aquecido:
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
    trava = None
    if not uma_vez:
        import fcntl
        garantir_dir(DIR_DT)
        trava = open(os.path.join(DIR_DT, "robo.trava"), "w")
        try:
            fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log("ja existe um robo de day trade nesta maquina; este processo sai sem fazer nada")
            return 3
    robo = Robo(hoje, saidas=saidas, motor=motor)
    robo.marco("ligado", "preparo", "Robô de day trade ligado (simulação): mini-índice e mini-dólar, "
               "comprado e vendido, zerando tudo às " + robo.p.hora_zerar + ".", agora)
    while True:
        agora = agora_brt()
        try:
            robo.ciclo(agora)
        except Exception as e:                      # um ciclo ruim nao derruba o dia
            log(f"ciclo falhou: {type(e).__name__}: {e}")
        hm = agora.strftime("%H:%M")
        if uma_vez or hm >= ate or agora.strftime("%Y-%m-%d") != hoje:
            return 0
        time.sleep(intervalo if ABERTURA <= hm < "17:25" else 10.0)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Robo de day trade (simulacao) em mini-indice e mini-dolar")
    ap.add_argument("--uma-vez", action="store_true")
    ap.add_argument("--saida", action="append")
    ap.add_argument("--motor", default=MOTOR)
    ap.add_argument("--ate", default=FIM_PROCESSO)
    args = ap.parse_args(argv)
    return rodar(uma_vez=args.uma_vez, saidas=args.saida, motor=args.motor, ate=args.ate)


if __name__ == "__main__":
    sys.exit(main())
