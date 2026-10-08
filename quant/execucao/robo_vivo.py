"""
O robo ao vivo (estagio 1, SIMULACAO): le as cotacoes do motor do Autopilot Terminal, casa a
boleta do dia contra elas com a mesma regra do paper trading e grava, a cada ciclo, o estado
que a area QUANT do terminal desenha.

O QUE ELE FAZ, EM ORDEM:
  1. le `quant/saida/painel.json` (a rodada da manha: boleta, carteira, gate, frescor);
  2. a cada `INTERVALO` segundos pede ao motor o retrato das cotacoes
     (GET /vivo/retrato) e transforma a VARIACAO DO VOLUME ACUMULADO de cada papel da
     boleta num "negocio" (quantidade = volume novo; preco = financeiro novo / volume novo,
     ou o ultimo preco quando o financeiro nao vem);
  3. entrega esses negocios a `paper_vivo.Sessao`, que recasa a boleta inteira com
     `paper.simular` - a regra de casamento e UMA so, a mesma da medicao de fechamento;
  4. grava o estado (ordens, execucoes, carteira, protecao, diario) nos arquivos de saida,
     de forma atomica. Quem desenha e o terminal; aqui nao ha HTML.

O QUE ELE NAO FAZ: nao manda ordem a corretora nenhuma (nao ha codigo de envio aqui, nem
credencial), nao inventa preco (papel sem negocio fica sem marcacao) e nao substitui a
medicao oficial: a fita derivada do volume acumulado junta os negocios de cada ciclo num
so, no preco medio do ciclo. Depois do fechamento, `campanha --sessao` casa a mesma boleta
contra o negocio a negocio da B3 e e ESSE resultado que entra no livro e no placar da fase 4.

REINICIO NO MEIO DO PREGAO. A fita vista e gravada em `saida/vivo/<data>/fita.csv` e o
ultimo volume de cada papel em `estado.json`: um processo que cai e volta recarrega a fita
e trata o volume negociado na ausencia como um negocio so, no preco medio do intervalo.

Uso:
    python -m quant.execucao.robo_vivo                # roda ate o fim do pregao
    python -m quant.execucao.robo_vivo --uma-vez      # grava o estado uma vez e sai
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta

import pandas as pd

from quant.comum import DIR_SAIDA, agora_brt, garantir_dir, gravar_atomico, ler_json, log
from quant.execucao import paper, paper_vivo

MOTOR = os.environ.get("QUANT_MOTOR", "http://127.0.0.1:8930")
INTERVALO = 2.0
ARQ_PAINEL = os.path.join(DIR_SAIDA, "painel.json")
DIR_VIVO = os.path.join(DIR_SAIDA, "vivo")
ARQ_SERIE = os.path.join(DIR_VIVO, "serie.json")
# Onde a area QUANT do terminal le o estado. Dois caminhos porque o montador do terminal copia
# cache/out/pagina/ para web/d/x/ a cada rodada: gravando nos dois, nenhum fica velho.
SAIDAS_PADRAO = [os.path.expanduser(p) for p in os.environ.get(
    "QUANT_SAIDA",
    "~/Desktop/terminal-artefato/web/d/x/quant.json:~/Desktop/terminal-artefato/cache/out/pagina/quant.json"
).split(":") if p]

# Posicoes do vetor de cotacao do motor (coletor/vivo.py do terminal):
# [ultimo, var%, abertura, max, min, volume, fech. anterior, hora, compra, venda, sessao,
#  negocios, financeiro, medio, aberto, fech. oficial, ultimo pos-fechamento]
I_ULT, I_VOL, I_ANT, I_HORA, I_NEG, I_FIN, I_MEDIO = 0, 5, 6, 7, 11, 12, 13

# Pregao regular da B3: negociacao continua das 10h00 as 16h55 e leilao de fechamento ate as 17h00.
# O after-market (ate as 18h) NAO conta para casar ordem: ordem com validade "dia" nao participa dele.
# O processo segue ate FIM_PROCESSO para a tela fechar com o preco oficial do dia.
ABERTURA, FECHAMENTO, FIM_PROCESSO = "10:00", "17:00", "18:30"
ATIVO_HEDGE = "WINFUT"
MULTIPLICADOR_WIN = 0.20          # R$ por ponto do mini-indice
DIARIO_MAX = 200
NOTA_HEDGE = ("Proteção parcial: mini-índice vendido. Entrada simulada no primeiro preço do contrato "
              "depois do envio da boleta; sem custo de rolagem ainda.")
TOLERANCIA_PRECO_MEDIO = 0.02     # preco medio do ciclo a mais de 2% do ultimo: usa o ultimo


# ─────────────────────────────────────────────────────────────
# Utilitarios
# ─────────────────────────────────────────────────────────────
def _num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _limpo(obj):
    """Tipos JSON nativos, sem NaN (o front quebra com NaN)."""
    from quant.rodar_diario import limpar
    return limpar(obj)


def gravar_estado(obj, caminhos):
    texto = json.dumps(_limpo(obj), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    feitos = 0
    for c in caminhos:
        try:
            garantir_dir(os.path.dirname(c))
            gravar_atomico(c, texto)
            feitos += 1
        except OSError as e:
            log(f"nao gravei {c}: {type(e).__name__}: {e}")
    return feitos


def ler_motor(caminho, motor=MOTOR, timeout=4.0):
    """GET no motor do terminal. Devolve o JSON ou None (o robo nunca cai por causa do motor)."""
    try:
        with urllib.request.urlopen(motor + caminho, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def fase_do_relogio(agora, hora_envio):
    hm = agora.strftime("%H:%M")
    if agora.weekday() >= 5:
        return "encerrado"
    if hm < ABERTURA:
        return "aguardando_abertura"
    if hm < hora_envio:
        return "aguardando_envio"
    if hm < FECHAMENTO:
        return "operando"
    return "encerrado"


# ─────────────────────────────────────────────────────────────
# Fita derivada do volume acumulado
# ─────────────────────────────────────────────────────────────
class Leitor:
    """Transforma retratos sucessivos do motor em negocios (ticker, hora, preco, quantidade).

    O volume do dia que o MetaTrader informa so cresce; a diferenca entre dois retratos e o
    que negociou no intervalo. Papel visto SEM volume hoje (antes do primeiro negocio) parte
    de zero, para o primeiro negocio de um papel pouco liquido nao se perder como linha de
    base; papel visto pela primeira vez JA com volume (robo ligado no meio do pregao, sem
    estado salvo) usa o volume atual como base e so conta dali em diante.
    """

    def __init__(self, tickers, ultimo=None):
        self.tickers = sorted({str(t).upper() for t in tickers})
        self.ultimo = dict(ultimo or {})          # ticker -> {"v": volume, "fin": financeiro}
        self.precos = {}                          # ticker -> ultimo preco de HOJE
        self.sem_volume = set()

    def negocios(self, retrato, agora):
        q = (retrato or {}).get("q") or {}
        hoje = agora.strftime("%Y-%m-%d")
        hora = agora.strftime("%H:%M:%S")
        fora = []
        for t in self.tickers:
            c = q.get(t)
            if not isinstance(c, list) or len(c) <= I_HORA:
                continue
            ts = _num(c[I_HORA])
            de_hoje = ts is not None and datetime.fromtimestamp(ts, agora.tzinfo).strftime("%Y-%m-%d") == hoje
            vol = _num(c[I_VOL]) if len(c) > I_VOL else None
            if not de_hoje or vol is None:
                self.sem_volume.add(t)
                continue
            preco = _num(c[I_ULT])
            if preco is None or preco <= 0:
                continue
            self.precos[t] = preco
            fin = _num(c[I_FIN]) if len(c) > I_FIN else None
            if fin is None and len(c) > I_MEDIO and _num(c[I_MEDIO]):
                # a corretora nem sempre manda o financeiro; o preco medio do dia vezes o volume da o mesmo
                # acumulado, e a diferenca entre dois retratos continua sendo o financeiro do intervalo
                fin = _num(c[I_MEDIO]) * vol
            ant = self.ultimo.get(t)
            if ant is None:
                ant = {"v": 0.0, "fin": 0.0} if t in self.sem_volume else {"v": vol, "fin": fin}
            self.ultimo[t] = {"v": vol, "fin": fin}
            dv = vol - (_num(ant.get("v")) or 0.0)
            if dv <= 0:
                continue                           # nada novo (ou a sessao recomecou: nova base)
            p = preco
            fa = _num(ant.get("fin"))
            if fin is not None and fa is not None and fin > fa:
                medio = (fin - fa) / dv
                if medio > 0 and abs(medio / preco - 1.0) <= TOLERANCIA_PRECO_MEDIO:
                    p = medio
            fora.append({"ticker": t, "hora": hora, "preco": round(float(p), 6), "quantidade": float(dv)})
        return fora


# ─────────────────────────────────────────────────────────────
# O robo
# ─────────────────────────────────────────────────────────────
class Robo:
    def __init__(self, painel, hoje, saidas=None, motor=MOTOR):
        self.painel = painel if isinstance(painel, dict) else {}
        self.hoje = str(hoje)
        self.saidas = list(saidas or SAIDAS_PADRAO)
        self.motor = motor
        self.pasta = os.path.join(DIR_VIVO, self.hoje)
        garantir_dir(self.pasta)
        self.arq_fita = os.path.join(self.pasta, "fita.csv")
        self.arq_estado = os.path.join(self.pasta, "estado.json")
        boleta = self.painel.get("boleta") or {}
        self.boleta_do_dia = boleta if str(boleta.get("data")) == self.hoje else {}
        self.sessao = paper_vivo.Sessao(self.boleta_do_dia, reprecificar=True)
        if self.boleta_do_dia.get("emitida"):
            # a copia do dia: a medicao da noite (quant.robo fechar) mede ESTA boleta, nao outra
            gravar_atomico(os.path.join(self.pasta, "boleta.json"),
                           json.dumps(self.boleta_do_dia, ensure_ascii=False, indent=1))
        salvo = ler_json(self.arq_estado, padrao=None) or {}
        tickers = [o.get("ticker") for o in (self.boleta_do_dia.get("ordens") or [])]
        tickers += list(((self.painel.get("carteira") or {}).get("posicoes") and
                         [p.get("ticker") for p in self.painel["carteira"]["posicoes"]]) or [])
        self.leitor = Leitor([t for t in tickers if t], salvo.get("ultimo"))
        self.diario = list(salvo.get("diario") or [])
        self.hedge = salvo.get("hedge")
        self.executado_ant = dict(salvo.get("executado") or {})
        self.marcos = set(salvo.get("marcos") or [])
        self.desde = salvo.get("desde") or agora_brt().isoformat(timespec="seconds")
        self.sinais = None
        self.ponte = None
        self.ponte_em = 0.0
        self._recarregar_fita()

    # ── persistencia ─────────────────────────────────────────
    def _recarregar_fita(self):
        if not os.path.exists(self.arq_fita):
            return
        try:
            d = pd.read_csv(self.arq_fita, sep=";", dtype={"ticker": str, "hora": str})
            if len(d):
                self.sessao.aplicar(d)
                log(f"fita do dia recarregada: {len(d)} negocios")
        except Exception as e:
            log(f"fita do dia ilegivel ({type(e).__name__}: {e}); comeco de novo")

    def _anexar_fita(self, novos):
        novo_arquivo = not os.path.exists(self.arq_fita)
        with open(self.arq_fita, "a", encoding="utf-8") as f:
            if novo_arquivo:
                f.write("ticker;hora;preco;quantidade\n")
            for n in novos:
                f.write(f"{n['ticker']};{n['hora']};{n['preco']};{n['quantidade']}\n")

    def _salvar(self):
        gravar_atomico(self.arq_estado, json.dumps({
            "desde": self.desde, "ultimo": self.leitor.ultimo, "diario": self.diario[-DIARIO_MAX:],
            "hedge": self.hedge, "executado": self.executado_ant, "marcos": sorted(self.marcos),
        }, ensure_ascii=False))

    def anotar(self, tipo, texto, agora=None):
        hora = (agora or agora_brt()).strftime("%H:%M:%S")
        self.diario.append({"hora": hora, "tipo": tipo, "texto": texto})
        self.diario = self.diario[-DIARIO_MAX:]
        log(f"[{tipo}] {texto}")

    def marco(self, chave, tipo, texto, agora=None):
        """Anota uma vez por dia (envio da boleta, cada reprecificacao, fechamento)."""
        if chave in self.marcos:
            return False
        self.marcos.add(chave)
        self.anotar(tipo, texto, agora)
        return True

    # ── um ciclo ─────────────────────────────────────────────
    def ciclo(self, agora=None, retrato=None):
        agora = agora or agora_brt()
        b = self.boleta_do_dia
        hora_envio = str(b.get("hora_envio") or paper.HORA_ENVIO)[:5]
        fase = fase_do_relogio(agora, hora_envio)
        if retrato is None:
            retrato = ler_motor("/vivo/retrato", self.motor)
        emitida = bool(b.get("emitida"))
        if retrato is not None and emitida:
            novos = self.leitor.negocios(retrato, agora)
            if agora.strftime("%H:%M") >= FECHAMENTO:
                novos = []                          # after-market: atualiza preco e volume, nao casa ordem
            if novos:
                self._anexar_fita(novos)
                self.sessao.aplicar(novos)
        if emitida:
            self._marcos_do_dia(agora, fase, hora_envio)
            self._hedge(retrato, agora, fase)
            self._anotar_execucoes(agora)
        estado = self.estado(agora, fase, retrato)
        gravar_estado(estado, self.saidas)
        self._salvar()
        return estado

    def _marcos_do_dia(self, agora, fase, hora_envio):
        b = self.boleta_do_dia
        ordens = b.get("ordens") or []
        hm = agora.strftime("%H:%M")
        if hm >= hora_envio and fase in ("operando", "encerrado"):
            compras = [o for o in ordens if o.get("lado") == "C"]
            vendas = [o for o in ordens if o.get("lado") != "C"]
            fin = sum((_num(o.get("financeiro")) or 0.0) for o in ordens)
            reais = f"{fin:,.0f}".replace(",", ".")
            self.marco("envio", "envio",
                       f"Boleta {b.get('id')} em vigor desde {hora_envio}: {len(compras)} compra(s) e "
                       f"{len(vendas)} venda(s), R$ {reais} no limite", agora)
        for h in ((b.get("reprecificacao") or {}).get("horarios") or []):
            if hm >= str(h)[:5] and fase == "operando":
                falta = sum(1 for o in self.sessao.estado()["ordens"] if o["falta"] > 0)
                passo = f"{(_num((b.get('reprecificacao') or {}).get('passo')) or 0) * 100:.1f}".replace(".", ",")
                self.marco(f"rep{h}", "reprecificacao",
                           f"Reprecificação das {h}: limite das {falta} ordem(ns) em aberto anda "
                           f"{passo}% na direção que executa", agora)
        if fase == "encerrado" and hm >= FECHAMENTO:
            t = self.sessao.estado()["totais"]
            taxa = t.get("taxa_execucao")
            self.marco("fechamento", "fechamento",
                       f"Pregão encerrado: {t['qtd_executada']} de {t['qtd_pedida']} ações executadas"
                       + (f" ({taxa * 100:.0f}%)" if taxa is not None else "")
                       + " (até o leilão de fechamento; o after-market não conta)."
                       + " A medição oficial sai com a fita da B3, depois das 20h.", agora)

    def _hedge(self, retrato, agora, fase):
        h = self.boleta_do_dia.get("hedge")
        if not isinstance(h, dict) or not h.get("contratos"):
            return
        c = ((retrato or {}).get("q") or {}).get(ATIVO_HEDGE)
        preco = _num(c[I_ULT]) if isinstance(c, list) and c else None
        ts = _num(c[I_HORA]) if isinstance(c, list) and len(c) > I_HORA else None
        de_hoje = ts is not None and datetime.fromtimestamp(ts, agora.tzinfo).strftime("%Y-%m-%d") == self.hoje
        if self.hedge is None:
            self.hedge = {"ativo": ATIVO_HEDGE, "contratos": int(h.get("contratos") or 0), "lado": "V",
                          "motivo": h.get("motivo"), "vencimento": h.get("vencimento"),
                          "preco_entrada": None, "hora": None, "preco_mercado": None, "aberto": None,
                          "multiplicador": MULTIPLICADOR_WIN,
                          "nota": NOTA_HEDGE}
        self.hedge["nota"] = NOTA_HEDGE            # o texto e do codigo, nao do estado salvo
        if preco is None or not de_hoje:
            return
        if self.hedge["preco_entrada"] is None and fase == "operando":
            self.hedge["preco_entrada"] = preco
            self.hedge["hora"] = agora.strftime("%H:%M:%S")
            pontos = f"{preco:,.0f}".replace(",", ".")
            self.anotar("fill", f"Proteção: {self.hedge['contratos']} contrato(s) de mini-índice vendido(s) a "
                                f"{pontos} pontos", agora)
        self.hedge["preco_mercado"] = preco
        if self.hedge["preco_entrada"] is not None:
            self.hedge["aberto"] = round((self.hedge["preco_entrada"] - preco) * MULTIPLICADOR_WIN
                                         * self.hedge["contratos"], 2)

    def _anotar_execucoes(self, agora):
        for o in self.sessao.estado()["ordens"]:
            ant = int(self.executado_ant.get(o["ticker"], 0))
            if o["executado"] > ant:
                self.executado_ant[o["ticker"]] = o["executado"]
                verbo = "comprou" if o["lado"] == "C" else "vendeu"
                pm = o.get("preco_medio")
                self.anotar("fill", f"{o['ticker']}: {verbo} {o['executado']} de {o['alvo']}"
                                    + (f" a R$ {pm:.2f}".replace(".", ",") if pm is not None else "")
                                    + (" (completa)" if o["falta"] == 0 else ""), agora)

    # ── o estado que a tela le ───────────────────────────────
    def _ponte(self):
        """Banco, gate e bloqueios. Caro (le o banco): refaz no maximo a cada 5 minutos."""
        if self.ponte is None or time.time() - self.ponte_em > 300:
            try:
                from quant import ponte_terminal
                self.ponte = ponte_terminal.payload()
            except Exception as e:
                self.ponte = {"pronto": False, "bloqueios": [{"chave": "ponte", "titulo": "A ponte falhou",
                                                              "detalhe": f"{type(e).__name__}: {e}", "comando": None}],
                              "gate": {}, "banco": {}}
            self.ponte_em = time.time()
        return self.ponte

    def _sinais(self):
        if self.sinais is not None:
            return self.sinais
        fora = {"data": None, "n_universo": None, "n_elegivel": None, "cortes": {}, "ranking": [], "lacunas": []}
        try:
            from quant import sinais as sg
            s = sg.carregar()
            if s is not None and len(s):
                ult = pd.to_datetime(s["data"]).max()
                u = s[pd.to_datetime(s["data"]) == ult]
                na_boleta = {o.get("ticker") for o in (self.boleta_do_dia.get("ordens") or [])}
                fora["data"] = str(ult.date())
                fora["n_universo"] = int(len(u))
                fora["n_elegivel"] = int(u["elegivel"].sum())
                fora["cortes"] = {str(k): int(v) for k, v in u["motivo"].value_counts().items() if str(k)}
                e = u[u["elegivel"]].sort_values("rank").head(40)
                for _, r in e.iterrows():
                    fora["ranking"].append({
                        "ticker": r["ticker"], "setor": r.get("setor"), "rank": _num(r.get("rank")),
                        "score": _num(r.get("score")), "pct_momentum": _num(r.get("pct_momentum")),
                        "pct_qualidade": _num(r.get("pct_qualidade")), "pct_valor": _num(r.get("pct_valor")),
                        "mom12": _num(r.get("mom12")), "mom6": _num(r.get("mom6")),
                        "vol252": _num(r.get("vol252")), "adtv21": _num(r.get("adtv21")),
                        "na_boleta": r["ticker"] in na_boleta})
                if u["pct_valor"].notna().sum() == 0:
                    fora["lacunas"].append("Sinal de valor sem dado: a carga ainda não tem o número de ações "
                                           "(capital social) para calcular valor de mercado; a nota de hoje usa "
                                           "só momentum e qualidade.")
                if u["taxa_aluguel"].notna().sum() == 0:
                    fora["lacunas"].append("Filtro de aluguel sem dado: o NEFIN deixou de publicar a taxa por papel.")
                fora["lacunas"].append("Bônus de compras de administradores (insiders) ainda não ligado.")
        except Exception as e:
            fora["lacunas"].append(f"Sinais ilegíveis: {type(e).__name__}: {e}")
        self.sinais = fora
        return fora

    def estado(self, agora, fase, retrato):
        p, b = self.painel, self.boleta_do_dia
        ponte = self._ponte()
        s = self.sessao.estado()
        q = (retrato or {}).get("q") or {}
        ordens_boleta = {str(o.get("ticker")): o for o in (b.get("ordens") or [])}
        ranking = {r["ticker"]: r for r in self._sinais()["ranking"]}
        hm = agora.strftime("%H:%M")

        ordens, n_exec, n_parc, n_sem, com_cotacao = [], 0, 0, 0, 0
        fin_alvo = fin_exec = aberto_total = 0.0
        for o in s["ordens"]:
            ob = ordens_boleta.get(o["ticker"], {})
            mercado = self.leitor.precos.get(o["ticker"])
            if mercado is not None:
                com_cotacao += 1
            limite = _num(ob.get("preco_limite"))
            atual = limite
            for d in (ob.get("limite_reprecificado") or []):
                if hm >= str(d.get("hora"))[:5] and _num(d.get("preco")):
                    atual = _num(d.get("preco"))
            pm = o.get("preco_medio")
            sinal = 1.0 if o["lado"] == "C" else -1.0
            aberto = ((mercado - pm) * o["executado"] * sinal
                      if (mercado is not None and pm is not None and o["executado"] > 0) else None)
            if o["executado"] >= o["alvo"] > 0:
                estado, n_exec = "executada", n_exec + 1
            elif o["executado"] > 0:
                estado, n_parc = "parcial", n_parc + 1
            else:
                n_sem += 1
                if fase in ("aguardando_abertura", "aguardando_envio"):
                    estado = "aguardando"
                elif mercado is None:
                    estado = "sem_negocio"
                elif atual is not None and ((o["lado"] == "C" and mercado > atual) or
                                            (o["lado"] != "C" and mercado < atual)):
                    estado = "fora_do_limite"
                else:
                    estado = "aguardando"
            alvo_fin = (limite or 0.0) * o["alvo"]
            exec_fin = (pm or 0.0) * o["executado"]
            fin_alvo += alvo_fin
            fin_exec += exec_fin
            aberto_total += aberto or 0.0
            r = ranking.get(o["ticker"], {})
            ordens.append({
                "ticker": o["ticker"], "setor": r.get("setor"), "lado": o["lado"], "motivo": ob.get("motivo"),
                "alvo": o["alvo"], "executado": o["executado"], "falta": o["falta"],
                "taxa_execucao": o["taxa_execucao"], "preco_limite": limite, "limite_atual": atual,
                "preco_medio": pm, "preco_mercado": mercado, "aberto": aberto,
                "financeiro_alvo": alvo_fin, "financeiro_executado": exec_fin,
                "hora_ultimo_fill": o.get("hora_ultimo_fill"), "rank": r.get("rank"), "score": r.get("score"),
                "fracionario": bool(ob.get("fracionario")), "iliquido": bool(ob.get("iliquido")),
                "reprecificacoes": ob.get("limite_reprecificado") or [], "estado": estado})
        pedida = sum(o["alvo"] for o in ordens)
        feita = sum(o["executado"] for o in ordens)

        # carteira: o que havia de manha mais o que executou hoje
        cart = dict(p.get("carteira") or {})
        patrimonio_ini = _num(cart.get("patrimonio")) or _num(p.get("capital")) or 0.0
        caixa = _num(cart.get("caixa")) or 0.0
        posicoes = {}
        for x in (cart.get("posicoes") or []):
            qtd = int(_num(x.get("qtd")) or 0)
            if qtd > 0:
                posicoes[x["ticker"]] = {"ticker": x["ticker"], "setor": x.get("setor"), "qtd": qtd,
                                         "custo": (_num(x.get("preco_medio")) or 0.0) * qtd,
                                         "peso_alvo": x.get("peso_alvo"), "origem": "anterior"}
        custos = 0.0
        fills = self.sessao.fills
        if len(fills):
            custos = float(pd.to_numeric(fills["emolumentos"], errors="coerce").fillna(0).sum()
                           + pd.to_numeric(fills["corretagem"], errors="coerce").fillna(0).sum())
        for o in ordens:
            if o["executado"] <= 0 or o["preco_medio"] is None:
                continue
            fin = o["preco_medio"] * o["executado"]
            pos = posicoes.setdefault(o["ticker"], {"ticker": o["ticker"], "setor": o["setor"], "qtd": 0,
                                                    "custo": 0.0, "peso_alvo": None, "origem": "hoje"})
            if o["lado"] == "C":
                pos["qtd"] += o["executado"]
                pos["custo"] += fin
                caixa -= fin
            else:
                medio = pos["custo"] / pos["qtd"] if pos["qtd"] else 0.0
                pos["qtd"] -= o["executado"]
                pos["custo"] -= medio * o["executado"]
                caixa += fin
        caixa -= custos
        linhas, valor_pos = [], 0.0
        for t, pos in sorted(posicoes.items()):
            if pos["qtd"] <= 0:
                continue
            preco = self.leitor.precos.get(t)
            if preco is None:
                c = q.get(t)
                preco = _num(c[I_ULT]) if isinstance(c, list) and c else None
            medio = pos["custo"] / pos["qtd"]
            valor = (preco if preco is not None else medio) * pos["qtd"]
            valor_pos += valor
            linhas.append({"ticker": t, "setor": pos["setor"], "qtd": pos["qtd"], "preco_medio": medio,
                           "preco": preco, "valor": valor, "peso": None, "peso_alvo": pos["peso_alvo"],
                           "pnl": (preco - medio) * pos["qtd"] if preco is not None else None,
                           "pnl_pct": (preco / medio - 1.0) if (preco is not None and medio) else None,
                           "origem": pos["origem"]})
        hedge_aberto = _num((self.hedge or {}).get("aberto")) or 0.0
        patrimonio = caixa + valor_pos + hedge_aberto
        for x in linhas:
            x["peso"] = x["valor"] / patrimonio if patrimonio else None
        carteira = {"patrimonio": patrimonio, "caixa": caixa, "valor_posicoes": valor_pos,
                    "n_posicoes": len(linhas), "exposicao": valor_pos / patrimonio if patrimonio else None,
                    "caixa_minimo": cart.get("caixa_minimo"), "resultado_dia": patrimonio - patrimonio_ini,
                    "custos_dia": custos, "posicoes": linhas}

        serie = self._serie(patrimonio, fase)
        motor = ler_motor("/vivo/estado", self.motor, timeout=2.0) if retrato is not None else None
        gate = dict(ponte.get("gate") or {})
        avisos = ["Simulação: nenhuma ordem é enviada à corretora.",
                  "Execução ao vivo estimada pela variação do volume acumulado do MetaTrader a cada "
                  f"{INTERVALO:.0f} s (não é o negócio a negócio oficial). A medição oficial sai depois do "
                  "fechamento, com a fita da B3."]
        lim = gate.get("limpeza") or {}
        if lim.get("saltos"):
            avisos.append(f"Validação aprovada com filtro de dado suspeito: {lim['saltos']} de "
                          f"{lim.get('observacoes')} retornos diários retirados ({lim.get('criterio')}).")
        avisos += self._sinais()["lacunas"]
        avisos += list(b.get("avisos") or [])[:0]          # avisos por ordem ficam no bloco da boleta
        if retrato is None:
            avisos.insert(0, "Motor do terminal sem resposta: cotações paradas até ele voltar.")

        textos = {
            "aguardando_abertura": "Boleta pronta; aguardando a abertura do pregão (10h00).",
            "aguardando_envio": f"Pregão aberto; a boleta entra em vigor às {b.get('hora_envio') or paper.HORA_ENVIO}.",
            "operando": f"Operando em simulação: {n_exec} ordem(ns) completa(s), {n_parc} parcial(is), "
                        f"{n_sem} sem execução.",
            "encerrado": "Pregão encerrado. Medição oficial depois das 20h, com a fita da B3.",
        }
        bloqueios = list(ponte.get("bloqueios") or [])
        pronto = bool(b.get("emitida")) and not bloqueios
        if not b:
            fase, texto = "bloqueado", "A rodada de hoje ainda não foi gerada."
        elif not b.get("emitida"):
            fase, texto = "bloqueado", "Boleta de hoje bloqueada: " + "; ".join(b.get("motivo_bloqueio") or ["modo seguro"])
        else:
            texto = textos.get(fase, fase)

        return {
            "v": 1,
            "gerado": agora.isoformat(timespec="seconds"),
            "vivo": {"ligado": True, "fase": fase, "fase_texto": texto, "desde": self.desde,
                     "batida": agora.isoformat(timespec="seconds"), "intervalo_s": INTERVALO,
                     "motor": {"ok": retrato is not None,
                               "idade_s": (retrato or {}).get("mt5_idade_s"),
                               "mt5": (motor or {}).get("mt5") or (retrato or {}).get("mt5")},
                     "negocios_vistos": s["negocios_vistos"], "com_cotacao": com_cotacao, "de": len(ordens)},
            "modo": p.get("modo") or "paper", "origem": p.get("origem"), "capital": p.get("capital"),
            "pronto": pronto, "bloqueios": bloqueios, "avisos": avisos,
            "gate": gate, "frescor": p.get("frescor") or {},
            "boleta": {k: b.get(k) for k in ("data", "id", "emitida", "hora_envio", "validade", "custo_total",
                                             "motivo_bloqueio", "reprecificacao", "liquidacao", "caixa", "avisos")},
            "ordens": ordens,
            "totais": {"ordens": len(ordens), "qtd_pedida": pedida, "qtd_executada": feita,
                       "taxa_execucao": (feita / pedida) if pedida else None,
                       "financeiro_alvo": fin_alvo, "financeiro_executado": fin_exec, "aberto": aberto_total,
                       "executadas": n_exec, "parciais": n_parc, "sem_execucao": n_sem},
            "hedge": self.hedge,
            "carteira": carteira,
            "sinais": self._sinais(),
            "paper": p.get("paper") or {}, "kill": p.get("kill") or [], "versao": p.get("versao") or {},
            "fiscal": p.get("fiscal") or {}, "desempenho": p.get("desempenho") or {},
            "serie": serie,
            "diario": list(reversed(self.diario[-DIARIO_MAX:])),
            "fontes": {"cotacoes": "motor do Autopilot Terminal (MetaTrader: último preço e volume acumulado da sessão)",
                       "sinais": "B3 (COTAHIST e proventos), CVM (ITR/DFP)",
                       "validacao": "NEFIN-USP (fator de momentum WML)",
                       "painel_da_manha": p.get("gerado_em")},
        }

    def _serie(self, patrimonio, fase):
        """Uma linha por pregao com o patrimonio simulado (a de hoje e regravada a cada ciclo)."""
        serie = ler_json(ARQ_SERIE, padrao=None)
        serie = serie if isinstance(serie, list) else []
        serie = [x for x in serie if isinstance(x, dict) and x.get("data") != self.hoje]
        if self.boleta_do_dia.get("emitida") and fase in ("operando", "encerrado"):
            serie.append({"data": self.hoje, "patrimonio": round(float(patrimonio), 2)})
            try:
                garantir_dir(DIR_VIVO)
                gravar_atomico(ARQ_SERIE, json.dumps(serie, ensure_ascii=False))
            except OSError:
                pass
        return serie[-400:]


def rodar(uma_vez=False, saidas=None, motor=MOTOR, intervalo=INTERVALO, ate=None):
    """Laco do dia. `ate` (HH:MM) encerra o processo; padrao: 40 minutos depois do fechamento."""
    agora = agora_brt()
    hoje = agora.strftime("%Y-%m-%d")
    fim = ate or FIM_PROCESSO
    trava = None
    if not uma_vez:
        # Um robo so por maquina: dois processos anexariam os mesmos negocios a mesma fita e a
        # boleta "executaria" em dobro. A trava some sozinha quando o processo morre.
        import fcntl
        garantir_dir(DIR_VIVO)
        trava = open(os.path.join(DIR_VIVO, "robo.trava"), "w")
        try:
            fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log("ja existe um robo ao vivo nesta maquina; este processo sai sem fazer nada")
            return 3
        trava.write(str(os.getpid()))
        trava.flush()
    robo, lido_em = None, 0.0
    while True:
        agora = agora_brt()
        # a rodada da manha pode chegar (ou ser refeita) com o robo ja no ar: rele o painel quando ele muda
        try:
            mudou = os.path.getmtime(ARQ_PAINEL)
        except OSError:
            mudou = 0.0
        if robo is None or mudou > lido_em:
            painel = ler_json(ARQ_PAINEL, padrao=None) or {}
            antes = robo
            robo = Robo(painel, hoje, saidas=saidas, motor=motor)
            lido_em = mudou or time.time()
            if antes is None or (antes.boleta_do_dia.get("id") != robo.boleta_do_dia.get("id")
                                 or bool(antes.boleta_do_dia.get("emitida")) != bool(robo.boleta_do_dia.get("emitida"))):
                b = robo.boleta_do_dia
                robo.marco("preparo", "preparo",
                           (f"Rodada da manhã lida: boleta {b.get('id')} com {len(b.get('ordens') or [])} ordem(ns)"
                            if b.get("emitida") else "Rodada da manhã lida: sem boleta emitida para hoje"), agora)
        try:
            robo.ciclo(agora)
        except Exception as e:                      # um ciclo ruim nao derruba o dia
            log(f"ciclo falhou: {type(e).__name__}: {e}")
        if uma_vez or agora.strftime("%H:%M") >= fim or agora.strftime("%Y-%m-%d") != hoje:
            return 0
        fase = fase_do_relogio(agora, "10:20")
        time.sleep(intervalo if fase in ("aguardando_envio", "operando") else min(15.0, intervalo * 5))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Robo ao vivo (simulacao) para a area QUANT do terminal")
    ap.add_argument("--uma-vez", action="store_true", help="grava o estado uma vez e sai")
    ap.add_argument("--saida", action="append", help="arquivo de estado (pode repetir)")
    ap.add_argument("--motor", default=MOTOR)
    ap.add_argument("--intervalo", type=float, default=INTERVALO)
    ap.add_argument("--ate", default=None, help="HH:MM em que o processo encerra")
    args = ap.parse_args(argv)
    return rodar(uma_vez=args.uma_vez, saidas=args.saida, motor=args.motor,
                 intervalo=args.intervalo, ate=args.ate)


if __name__ == "__main__":
    sys.exit(main())
