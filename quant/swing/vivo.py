"""
O robo de swing ao vivo (SIMULACAO): le as cotacoes do motor do Autopilot Terminal, entra nas operacoes COM CAPITAL da boleta do dia na abertura,
vigia stop, alvo e prazo de todas as posicoes com capital durante o pregao e grava a tela a cada poucos segundos.

    python -m quant.swing.vivo                  # roda o dia (e o que `python -m quant.robo dia --modulo swing` chama)
    python -m quant.swing.vivo --uma-vez        # grava a tela uma vez e sai

O QUE ELE FAZ:
  1. ENTRADA. As ordens com capital da boleta (`swing/boleta/<hoje>.json`) entram no preco de ABERTURA do dia, com a quantidade recalculada pelo
     risco no preco real da abertura. Sem cotacao de hoje ate as 11h, a entrada e cancelada e anotada. Hoje nenhum setup tem capital: a lista vem vazia.
     Ordem que so passou a existir DEPOIS da abertura (boleta refeita ou liberada a tarde, 13/10/2026) nao entra no preco da abertura, que a essa hora
     ja nao existe: entra no ultimo preco do ciclo em que apareceu, com quantidade, stop e alvo a partir dele, e o diario anota "fora da abertura".
     A hora em que a ordem passou a existir e a que a boleta grava na candidata (`capital_desde`), nao a da gravacao do arquivo.
  2. SAIDA. A cada ciclo confere stop, alvo e prazo (`posicao.decidir_saida`): stop e ordem a mercado simulada (no ultimo preco visto; se a abertura ja
     esta abaixo do stop, na abertura, PIOR que o stop); alvo e ordem limitada; no ultimo pregao do prazo (10o, no maximo) sai no leilao de fechamento.
  3. AS OPERACOES SO MEDIDAS NAO SAEM AQUI. Elas sao resolvidas na manha seguinte pelas barras oficiais (`estado.conciliar`), com a regra exata da
     pesquisa; aqui so recebem preco para a tela.
  4. TELA. Reescreve `quant_fatores.json` (mesmo arquivo da carteira de fatores) com o bloco `swing`: contrato em `quant/docs/tela_swing.md`.

O QUE NAO FAZ: nao manda ordem a corretora (nao ha codigo de envio nem credencial aqui) e nao inventa preco: papel sem cotacao de hoje fica sem marcacao
e vira aviso. Uma trava de instancia unica impede dois robos de swing na mesma maquina.
"""
import argparse
import fcntl
import json
import os
import sys
import time
from datetime import datetime

from quant import mesa as mesa_mod
from quant.comum import agora_brt, garantir_dir, gravar_atomico, ler_json, log
from quant.execucao.robo_vivo import (ABERTURA, FECHAMENTO, FIM_PROCESSO, I_ANT, I_HORA, I_ULT, MOTOR, _num, fase_do_relogio,
                                      gravar_estado, ler_motor)
from quant.swing import boleta as bol_mod
from quant.swing import estado as est
from quant.swing import evidencia, painel, posicao, tamanho
from quant.swing.texto import brl

INTERVALO = 3.0
TELA_CADA_S = 10.0
SALVAR_CADA_S = 60.0
LIMITE_ENTRADA = "11:00"          # sem cotacao de hoje ate esta hora, a entrada do dia e cancelada
ESPERA_FORA_MIN = 60              # ordem que chegou depois da abertura: sem cotacao de hoje em 1 hora, a entrada e cancelada
I_ABERTURA = 2


def _br_data(iso):
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}"


def cotacao(c, agora):
    """Vetor do motor -> {ultimo, abertura, anterior, de_hoje} ou None."""
    if not isinstance(c, list) or len(c) <= I_HORA:
        return None
    ts = _num(c[I_HORA])
    de_hoje = ts is not None and datetime.fromtimestamp(ts, agora.tzinfo).strftime("%Y-%m-%d") == agora.strftime("%Y-%m-%d")
    ab = _num(c[I_ABERTURA]) if len(c) > I_ABERTURA else None
    return {"ultimo": _num(c[I_ULT]), "abertura": ab if ab and ab > 0 else None, "anterior": _num(c[I_ANT]) if len(c) > I_ANT else None, "de_hoje": bool(de_hoje)}


class RoboSwing:
    def __init__(self, hoje, saidas=None, motor=MOTOR, relogio=agora_brt):
        self.hoje = str(hoje)
        self.motor = motor
        self.relogio = relogio
        self.saidas = list(saidas) if saidas else bol_mod.saidas_da_tela()
        self.estado = est.carregar()
        self.cfg = evidencia.config()
        self.variantes = evidencia.por_variante(cfg=self.cfg)
        self.boleta = None
        self.boleta_lida_em = 0.0
        self.desde = relogio().isoformat(timespec="seconds")
        self.ultima_tela = 0.0
        self.ultimo_salvar = 0.0
        self.precos = {}
        self.avisos = []
        self.sem_cotacao = set()
        self.disponivel = {}             # id da ordem com capital -> quando ela passou a existir na boleta (decide abertura ou ultimo preco)
        self.arq_serie = est.arq("serie.json")
        self.exposicao = bol_mod.exposicao_do_dia(self.hoje)
        self.visao, self.motivo_visao = mesa_mod.ler(arq=mesa_mod.ARQ_VISAO, hoje=None)
        self.ultimo_retrato, self.ultimo_cot = None, {}

    # ── boleta ───────────────────────────────────────────────
    def _ler_boleta(self):
        caminho = bol_mod.arq_boleta(self.hoje)
        try:
            mt = os.path.getmtime(caminho)
        except OSError:
            self.boleta = None
            return
        if mt > self.boleta_lida_em:
            self.boleta = bol_mod.ler_boleta(self.hoje)
            self.boleta_lida_em = mt

    def _bloqueios(self):
        if self.boleta is None:
            return [{"chave": "boleta", "titulo": "Sem boleta de swing para hoje",
                     "detalhe": "A rodada da manhã (conciliação, sinais e boleta) ainda não gerou a boleta de hoje. As posições abertas continuam vigiadas; "
                                "não entra operação nova.", "comando": "python -m quant.swing.boleta"}]
        return list(self.boleta.get("bloqueios") or [])

    # ── entradas ─────────────────────────────────────────────
    def _desde_da_ordem(self, c, agora):
        """Quando a ordem com capital passou a existir: o `capital_desde` que a boleta grava na propria candidata (gerar, --refazer e --so-mesa
        o mantem). A hora da gravacao do arquivo nao serve: o --so-mesa regrava a boleta da manha no meio do dia (revisao de 15/10/2026).
        Boleta antiga, sem o campo: a hora em que ela foi gerada e, sem ela, a da gravacao do arquivo. Nunca depois de agora."""
        for v in (c.get("capital_desde"), (self.boleta or {}).get("gerado")):
            try:
                d = datetime.fromisoformat(str(v)) if v else None
            except ValueError:
                d = None
            if d is not None:
                return min(d if d.tzinfo else d.replace(tzinfo=agora.tzinfo), agora)
        if self.boleta_lida_em:
            return min(datetime.fromtimestamp(self.boleta_lida_em, agora.tzinfo), agora)
        return agora

    def _marcar_disponiveis(self, agora):
        """Anota quando cada ordem com capital passou a existir. A boleta da manha entra na abertura mesmo com o robo religado no meio do dia
        (e mesmo que o --so-mesa tenha regravado o arquivo depois do sino); a ordem liberada a tarde entra no ultimo preco."""
        for c in self.boleta.get("candidatas") or []:
            if c.get("destino") != "capital":
                continue
            pid = f"{self.hoje}|{c['setup']}|{c['ticker']}|capital"
            if pid not in self.disponivel:
                self.disponivel[pid] = self._desde_da_ordem(c, agora)

    def _abertura_de_hoje(self, agora):
        h, m = (int(x) for x in ABERTURA.split(":"))
        return agora.replace(hour=h, minute=m, second=0, microsecond=0)

    def _entradas(self, cot, agora):
        if self.boleta is None or not self.boleta.get("emitida"):
            return
        self._marcar_disponiveis(agora)
        hm = agora.strftime("%H:%M")
        if hm < ABERTURA:
            return
        ja = {p["id"] for p in self.estado["posicoes"]} | {f["id"] for f in est.fechadas()} | set(self.estado.get("entradas_canceladas") or [])
        abertura = self._abertura_de_hoje(agora)
        for c in self.boleta.get("candidatas") or []:
            if c.get("destino") != "capital":
                continue
            pid = f"{self.hoje}|{c['setup']}|{c['ticker']}|capital"
            if pid in ja:
                continue
            if self.cfg.get("sair_antes_de") and self.hoje >= str(self.cfg["sair_antes_de"]):      # evento binario a frente: so sai, nao entra
                self._cancelar(pid, c, f"evento binário à frente ({self.cfg['sair_antes_de']}): sem entrada nova até passar (decisão do Douglas)", agora)
                continue
            desde = self.disponivel.get(pid, agora)
            na_abertura = desde <= abertura                   # a ordem existia antes do sino: entra no preco da abertura
            q = cot.get(c["ticker"])
            preco = (q or {}).get("abertura") if na_abertura else (q or {}).get("ultimo")
            if not na_abertura and desde.strftime("%H:%M") >= FECHAMENTO:
                self._cancelar(pid, c, f"a ordem só passou a existir às {desde.strftime('%Hh%M')}, depois do fechamento do pregão", agora)
                continue
            if not q or not q["de_hoje"] or not preco:
                if na_abertura and hm >= LIMITE_ENTRADA:
                    self._cancelar(pid, c, "sem cotação de hoje até as 11h", agora)
                elif not na_abertura and (agora - desde).total_seconds() >= ESPERA_FORA_MIN * 60:
                    self._cancelar(pid, c, f"sem cotação de hoje na hora seguinte à liberação ({desde.strftime('%Hh%M')})", agora)
                continue
            lv = painel.livro_capital(self.estado, est.fechadas(), self.cfg, self.precos, self.hoje)
            abertas = [p for p in self.estado["posicoes"] if p.get("modo") == "capital" and p.get("status") == "aberta"]
            qtd, valor = tamanho.quantidade(lv["patrimonio"], preco, c["stop_dist"], self.cfg["risco"], self.cfg["teto_nome"])
            teto = min(self.exposicao["teto_rs"], lv["patrimonio"] * tamanho.EXPO_MAX)
            if qtd <= 0:
                self._cancelar(pid, c, f"no preço {'da abertura' if na_abertura else 'de agora'} não cabe um lote dentro do risco e do teto por papel", agora)
                continue
            if not tamanho.cabe(valor, sum(p["valor"] for p in abertas), teto, len(abertas), lv["caixa"], 1.0, self.cfg["max_posicoes"]):
                self._cancelar(pid, c, "sem espaço no livro (posições, exposição ou caixa)", agora)
                continue
            extras = {"variante": c.get("variante"), "conviccao_mesa": (c.get("mesa") or {}).get("conviccao")}
            if not na_abertura:
                extras.update({"entrada_fora_da_abertura": True, "hora_entrada": agora.strftime("%H:%M"), "abertura_do_dia": q.get("abertura")})
            pos = est.nova_posicao(c["setup"], c["ticker"], c["sinal_em"], preco, c["stop_dist"], c["alvo_dist"], c["prazo"], qtd, self.hoje, c["adtv"],
                                   modo="capital", porque=c["porque"], overlays={"top": c["top"], "ibov_ok": c["ibov_ok"]}, ficha=c.get("ficha"),
                                   preco_ref=c["preco_ref"], origem="vivo", extras=extras)
            est.adicionar(self.estado, pos)
            fora = "" if na_abertura else (f" Entrada fora da abertura ({agora.strftime('%Hh%M')}): a ordem só existiu às {desde.strftime('%Hh%M')}, "
                                           f"então entrou no último preço, não na abertura ({brl(q['abertura']) if q.get('abertura') else '-'}).")
            est.anotar(self.estado, "entrada", f"Entrou em {c['ticker']} ({c['setup']}): {qtd} a {brl(preco)}, stop {brl(pos['stop'])}, "
                                               f"alvo {brl(pos['alvo']) if pos['alvo'] else '-'}, até {_br_data(pos['prazo_ate'])}.{fora} {c['porque']}", agora)
            self._salvar(True)

    def _cancelar(self, pid, c, motivo, agora):
        self.estado.setdefault("entradas_canceladas", []).append(pid)
        est.anotar(self.estado, "cancelada", f"Entrada em {c['ticker']} ({c['setup']}) cancelada: {motivo}", agora)
        self._salvar(True)

    # ── saidas ───────────────────────────────────────────────
    def _saidas(self, cot, agora):
        hm = agora.strftime("%H:%M")
        if hm < ABERTURA:
            return
        for pos in [p for p in self.estado["posicoes"] if p.get("modo") == "capital" and p.get("status") == "aberta"]:
            q = cot.get(pos["ticker"])
            if not q or not q["de_hoje"] or q["ultimo"] is None:
                self.sem_cotacao.add(pos["ticker"])           # o aviso sai do conjunto em tela(): some quando a cotacao volta
                continue
            self.sem_cotacao.discard(pos["ticker"])
            r = posicao.decidir_saida(pos, q["ultimo"], q["abertura"], self.hoje, hm, sair_em=self.cfg.get("sair_antes_de"))
            if r is None:
                continue
            preco, motivo = r
            f = est.fechar(pos, preco, motivo, self.hoje, origem="vivo")
            self.estado["posicoes"] = [p for p in self.estado["posicoes"] if p["id"] != pos["id"]]
            est.anexar_fechada(f)
            est.anotar(self.estado, "saida", f"Saiu de {pos['ticker']} ({pos['setup']}): {f['texto_saida']} a {brl(preco)}, resultado {brl(f['resultado_rs'])} "
                                             f"({f['pregoes']} pregão(ões))", agora)
            self._salvar(True)

    # ── persistencia e tela ──────────────────────────────────
    def _salvar(self, forcar=False):
        agora_s = time.time()
        if forcar or agora_s - self.ultimo_salvar >= SALVAR_CADA_S:
            est.salvar(self.estado)
            self.ultimo_salvar = agora_s

    def _serie(self, patrimonio, fase):
        serie = ler_json(self.arq_serie, padrao=None)
        serie = [x for x in (serie if isinstance(serie, list) else []) if isinstance(x, dict) and x.get("data") != self.hoje]
        if fase in ("operando", "encerrado"):
            serie.append({"data": self.hoje, "patrimonio": round(float(patrimonio), 2)})
            try:
                gravar_atomico(self.arq_serie, json.dumps(serie, ensure_ascii=False))
            except OSError:
                pass
        return serie[-400:]

    def tela(self, agora, retrato, cot, fase, forcar=False):
        if not forcar and time.time() - self.ultima_tela < TELA_CADA_S:
            return
        textos = {"aguardando_abertura": "Aguardando a abertura do pregão (10h).", "operando": "Vigiando as posições de swing; entradas na abertura.",
                  "encerrado": "Pregão encerrado: as medidas serão resolvidas pelas barras oficiais na manhã seguinte."}
        lv = painel.livro_capital(self.estado, est.fechadas(), self.cfg, self.precos, self.hoje)
        pos_tickers = {p["ticker"] for p in self.estado["posicoes"]}
        com_cot = sum(1 for t in pos_tickers if (cot.get(t) or {}).get("de_hoje"))
        vivo = {"ligado": True, "fase": fase, "fase_texto": textos.get(fase, fase), "desde": self.desde, "batida": agora.isoformat(timespec="seconds"),
                "intervalo_s": INTERVALO, "motor": {"ok": retrato is not None, "idade_s": (retrato or {}).get("mt5_idade_s"), "mt5": (retrato or {}).get("mt5")},
                "negocios_vistos": 0, "com_cotacao": com_cot, "de": len(pos_tickers)}
        avisos = list(self.avisos)
        abertas = {p["ticker"] for p in self.estado["posicoes"] if p.get("modo") == "capital" and p.get("status") == "aberta"}
        sem = sorted(self.sem_cotacao & abertas)
        if sem:
            avisos.append(f"{', '.join(sem)}: sem cotação de hoje no motor; o stop não está sendo vigiado até a cotação voltar.")
        if retrato is None:
            avisos.append("O motor de cotações do terminal não respondeu: sem preço ao vivo, o stop não está sendo vigiado.")
        obj = painel.tela(self.estado, est.fechadas(), self.boleta, self.variantes, self.cfg, self.hoje, self.precos, self.exposicao, visao=self.visao,
                          motivo_visao=self.motivo_visao, vivo=vivo, serie=self._serie(lv["patrimonio"], fase), avisos=avisos, bloqueios=self._bloqueios())
        gravar_estado(obj, self.saidas)
        self.ultima_tela = time.time()

    # ── o ciclo ──────────────────────────────────────────────
    def ciclo(self, agora, forcar_tela=False):
        self._ler_boleta()
        retrato = ler_motor("/vivo/retrato", self.motor)
        q = (retrato or {}).get("q") or {}
        cot = {}
        for t in {p["ticker"] for p in self.estado["posicoes"]} | {c["ticker"] for c in ((self.boleta or {}).get("candidatas") or []) if c.get("destino") == "capital"}:
            v = cotacao(q.get(t), agora)
            if v:
                cot[t] = v
                if v["de_hoje"] and v["ultimo"]:
                    self.precos[t] = v["ultimo"]
        self._entradas(cot, agora)
        self._saidas(cot, agora)
        self.ultimo_retrato, self.ultimo_cot = retrato, cot
        self.tela(agora, retrato, cot, fase_do_relogio(agora, ABERTURA), forcar=forcar_tela)
        self._salvar()


def rodar(uma_vez=False, saidas=None, motor=MOTOR, intervalo=INTERVALO, ate=None, relogio=agora_brt, dormir=time.sleep):
    """Laco do dia. `ate` (HH:MM) encerra o processo; padrao: 18h30. `relogio` e `dormir` existem para o ensaio rodar um dia inteiro em segundos."""
    hoje = relogio().strftime("%Y-%m-%d")
    fim = ate or FIM_PROCESSO
    trava = None
    if not uma_vez:
        garantir_dir(est.arq("."))
        trava = open(est.arq("robo.trava"), "w")
        try:
            fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log("já existe um robô de swing nesta máquina; este processo sai sem fazer nada")
            return 3
        trava.write(str(os.getpid()))
        trava.flush()
    robo = RoboSwing(hoje, saidas=saidas, motor=motor, relogio=relogio)
    log(f"swing ao vivo: {robo.hoje}, {len([p for p in robo.estado['posicoes'] if p.get('modo') == 'capital'])} posição(ões) com capital em carteira")
    primeira = True
    while True:
        agora = relogio()
        try:
            robo.ciclo(agora, forcar_tela=primeira)
        except Exception as e:                     # um ciclo ruim nao derruba o dia
            log(f"swing: ciclo falhou: {type(e).__name__}: {e}")
        primeira = False
        if uma_vez or agora.strftime("%H:%M") >= fim or agora.strftime("%Y-%m-%d") != hoje:
            try:
                robo.tela(agora, robo.ultimo_retrato, robo.ultimo_cot, fase_do_relogio(agora, ABERTURA), forcar=True)
                robo._salvar(True)
            except Exception as e:
                log(f"swing: tela final falhou: {type(e).__name__}: {e}")
            return 0
        fase = fase_do_relogio(agora, ABERTURA)
        dormir(intervalo if fase in ("aguardando_envio", "operando") else min(15.0, intervalo * 5))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Robo de swing ao vivo (simulacao)")
    ap.add_argument("--uma-vez", action="store_true")
    ap.add_argument("--saida", action="append")
    ap.add_argument("--motor", default=MOTOR)
    ap.add_argument("--intervalo", type=float, default=INTERVALO)
    ap.add_argument("--ate", default=None, help="HH:MM em que o processo encerra")
    a = ap.parse_args(argv)
    return rodar(uma_vez=a.uma_vez, saidas=a.saida, motor=a.motor, intervalo=a.intervalo, ate=a.ate)


if __name__ == "__main__":
    sys.exit(main())
