"""Orquestra a coleta por modo (intradia | fechamento | manha | sonda | backfill |
ack), cada perna falhando sozinha, roda o motor de sinais, aplica a politica,
renderiza as saidas e grava livro/saida/manifest.json.

Layout no branch dados (raiz = dados_branch/livro):
  series/<SIMBOLO_SAFE>.json   curvas/{di,tesouro,ust}.json   macro/{bcb,focus,proxies,regime}.json
  estado/{regras_estado.json,alertas.json,historico_alertas.jsonl}
  saida/{manifest.json,fechamento.md,fechamento.json,fechamento_cards.md,manha_cards.md,painel.html,alertas.md,intradia.md,manha.md,noticias.md,eventos.md}
  eventos/{noticias,cvm,sec}.json   noticias/vistos.json   noticias/corpo/<id>.json
  sonda/cobertura.json   universo.json"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from livro import atribuicao, cards, fmt, insumos, painel, politica, reconferir, relogios, render
from livro import indicadores as ind
from livro import qualidade as qa
from livro import universo as uni
from livro.estado import Repositorio
from livro.fontes import agenda as f_agenda
from livro.fontes import b3_di, bcb, cvm, futuros, noticias, sec, sina, tesouro, ust, yahoo
from livro.http import Cliente
from livro.sinais import curvas as r_curvas
from livro.sinais import eventos as r_ev
from livro.sinais import eventos_macro as r_evm
from livro.sinais import tecnicas2 as r_tec2
from livro.sinais import fx_commod as r_fx
from livro.sinais import sistema as r_sis
from livro.sinais import tecnicas as r_tec
from livro.sinais.base import Contexto
from livro.universo import gravar_json, ler_json

SLOT_ROTULO = {"intradia": "intradia", "fechamento": "Fechamento 18h", "manha": "Manhã 08h30",
               "fimdesemana": "Domingo", "sonda": "sonda", "backfill": "backfill", "ack": "ack", "eventos": "eventos"}
MODOS_COM_EVENTOS = ("intradia", "fechamento", "manha", "eventos")


def _p(obj, chave: str, padrao=None):
    """Parametro do ativo do universo; benchmark nao tem parametros."""
    f = getattr(obj, "param", None)
    return f(chave, padrao) if f else padrao


def _log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}Z] {msg}", flush=True)


class Coleta:
    def __init__(self, saida: str, modo: str, agora: datetime | None = None, offline: str | None = None,
                 run_id: str = "", dias_backfill: int = 10, simbolos_extra: list[str] | None = None):
        self.saida = saida
        self.modo = modo
        self.agora = agora or datetime.now(timezone.utc)
        self.offline = offline
        self.run_id = run_id
        self.dias_backfill = dias_backfill
        self.simbolos_extra = simbolos_extra or []
        self.u = uni.carregar()
        self.limiares = uni.carregar_yaml("limiares.yaml")
        self.calendario = uni.carregar_yaml("calendario.yaml")
        self.hoje = relogios.data_pregao_b3(self.agora)
        self.pernas: dict = {}
        self.falhas: dict = {}
        self.series: dict = {}
        self.series_longo: dict = {}   # semanal de 6 anos, so para a janela de 5 anos
        self.series_info: dict = {}
        self.curvas: dict = {}
        self.macro: dict = {}
        self.eventos: dict = {}
        self.correcoes: list = []
        self.inicio = time.time()
        for sub in ("series", "series_longo", "curvas", "macro", "estado", "saida", "sonda", "eventos", "noticias/corpo"):
            os.makedirs(os.path.join(saida, sub), exist_ok=True)
        gravar_json(os.path.join(saida, "universo.json"), self.u.para_json())

    # ------------------------------------------------------------ series
    def _carregar_serie_local(self, simbolo: str) -> dict | None:
        return ler_json(os.path.join(self.saida, "series", f"{uni.nome_seguro(simbolo)}.json"))

    def _contratos_brent(self) -> list[str]:
        """Simbolos do Brent por vencimento (vigente e seguinte), se o BRENT do livro
        estiver marcado com `contrato_explicito: brent`."""
        a = self.u.por_id("BRENT")
        if a is None or _p(a, "contrato_explicito") != "brent":
            return []
        return futuros.simbolos_para(relogios.brt(self.agora).date())

    def coletar_series(self) -> None:
        simbolos = self.u.simbolos_yahoo() + self.simbolos_extra
        if self.offline:
            self._series_offline(simbolos)
            return
        contratos = [c for c in self._contratos_brent() if c not in simbolos]
        rng = "5d" if self.modo == "intradia" else "2y"
        novas, falhas = yahoo.coletar(simbolos + contratos, rng)
        ok, recuperados, reprecificadas, rejeitadas = 0, [], [], []
        for s in simbolos + contratos:
            # mesclar une por data (intradia com range=5d e fechamento com 2y): nada se perde,
            # salvo quando a serie inteira foi reprecificada (rolagem de futuro, split)
            antiga = self._carregar_serie_local(s)
            final = yahoo.mesclar(antiga, novas.get(s))
            if final and antiga and antiga.get("fechamentos_17h") and not final.get("fechamentos_17h"):
                final["fechamentos_17h"] = antiga["fechamentos_17h"]
            if final and final.get("revisoes_rejeitadas") and novas.get(s):
                rejeitadas.append(f"{s} {', '.join(final['revisoes_rejeitadas'][-3:])}")
            if s in contratos:
                if final:
                    gravar_json(os.path.join(self.saida, "series", f"{uni.nome_seguro(s)}.json"), final)
                continue
            if final:
                gravar_json(os.path.join(self.saida, "series", f"{uni.nome_seguro(s)}.json"), final)
                if novas.get(s):
                    ok += 1
                if final.get("barras_recuperadas"):
                    recuperados.append(s)
                if final.get("reprecificada"):
                    obj = self.u.por_yahoo(s)
                    reprecificadas.append(f"{getattr(obj, 'id', s)} {fmt.pct(final['reprecificada'], 1, False)}")
        self.pernas["yahoo"] = (f"ok {ok}/{len(simbolos)}"
                                + (f"; {len(recuperados)} séries com barra do Yahoo faltando (recuperada do histórico)" if recuperados else "")
                                + (f"; série reprecificada (rolagem/split): {', '.join(reprecificadas)}" if reprecificadas else "")
                                + (f"; falhas: {', '.join(f'{k} {v}' for k, v in list(falhas.items())[:6])}" if falhas else ""))
        if reprecificadas:
            self.falhas["series_reprecificadas"] = ("histórico refeito pelo Yahoo em " + ", ".join(reprecificadas)
                                                    + " (rolagem de contrato ou split): comparações com dias anteriores mudam de base")
        falhas_livro = {k: v for k, v in falhas.items() if k in simbolos}
        if falhas_livro:
            self.falhas["yahoo"] = f"{len(falhas_livro)} símbolos falharam ({', '.join(list(falhas_livro.values())[:3])})"
        if contratos:
            vig = [c for c in contratos if novas.get(c)]
            self.pernas["brent_contratos"] = (f"ok {', '.join(vig)}" if vig else
                                              f"falha: {', '.join(f'{k} {v}' for k, v in falhas.items() if k in contratos)}")
        if rejeitadas:
            self.pernas["yahoo"] += f"; barras podres recusadas (ficou a guardada): {'; '.join(rejeitadas[:4])}"
        self._fechar_cambio()
        self._refazer_buracos(simbolos)
        self._montar_dataframes(simbolos, falhas)
        self.coletar_series_longas(simbolos)

    def _fechar_cambio(self) -> None:
        """Dolar pelo ultimo negocio ate as 17h (grafico de 15 minutos). A barra diaria
        do Yahoo guardava o fechamento da vespera (23/09: 5,0999 com o dolar a 5,16).
        Os fechamentos das 17h ficam guardados na propria serie (`fechamentos_17h`) e
        valem por cima da barra diaria em `_montar_dataframes`."""
        alvos = [a for a in self.u.ativos if _p(a, "fechamento_intradia")]
        if not alvos or self.offline:
            return
        agora_brt = relogios.brt(self.agora)
        try:
            cli = Cliente()
            crumb = yahoo.preparar_sessao(cli)
        except Exception as e:
            self.pernas["cambio_17h"] = f"falha na sessão: {type(e).__name__}"
            return
        rel = []
        for a in alvos:
            hora = str(_p(a, "fechamento_intradia"))
            hh, mm = (int(x) for x in hora.split(":"))
            try:
                fech = yahoo.fechamentos_intradia(cli, a.yahoo, hora, crumb=crumb)
            except Exception as e:
                rel.append(f"{a.id} falha {type(e).__name__}: {str(e)[:60]}")
                continue
            d = self._carregar_serie_local(a.yahoo)
            if not d:
                continue
            guard = dict(d.get("fechamentos_17h") or {})
            novos = 0
            for data, (preco, hhmm) in sorted(fech.items()):
                if data == agora_brt.date().isoformat() and (agora_brt.hour, agora_brt.minute) < (hh, mm):
                    continue                       # o corte de hoje ainda nao chegou
                if data > agora_brt.date().isoformat():
                    continue
                guard[data] = [round(float(preco), 6), hhmm]
                novos += 1
            d["fechamentos_17h"] = dict(sorted(guard.items())[-400:])
            gravar_json(os.path.join(self.saida, "series", f"{uni.nome_seguro(a.yahoo)}.json"), d)
            ult = max(guard) if guard else None
            rel.append(f"{a.id} {novos} dias" + (f", último {fmt.data_br(ult)} {guard[ult][1]}" if ult else ""))
        self.pernas["cambio_17h"] = "ok " + "; ".join(rel) if rel else "sem alvo"

    def _refazer_buracos(self, simbolos: list[str]) -> None:
        """Pregao faltando nas ultimas 15 barras (MMM, GFS, IBOV e mais 17 sem 22/09 em
        23/09): segunda chamada com 1 mes, que o Yahoo costuma devolver completa."""
        com_buraco = {}
        for s in simbolos:
            obj = self.u.por_yahoo(s)
            if obj is None or obj.mercado == "CRIPTO" or _p(obj, "sem_pregao_diario", False):
                continue
            d = self._carregar_serie_local(s)
            barras = qa.limpar_fim_de_semana((d or {}).get("barras") or [], obj.mercado)[-15:]
            faltam = []
            for b0, b1 in zip(barras, barras[1:]):
                faltam += qa.dias_sem_barra(obj.mercado, b0[0], b1[0])
            if faltam:
                com_buraco[s] = faltam
        if not com_buraco:
            return
        try:
            novas, _ = yahoo.coletar(list(com_buraco), "1mo")
        except Exception as e:
            self.pernas["buracos"] = f"{len(com_buraco)} séries com pregão faltando; nova chamada falhou ({type(e).__name__})"
            return
        refeitas = 0
        for s, faltam in com_buraco.items():
            if not novas.get(s):
                continue
            final = yahoo.mesclar(self._carregar_serie_local(s), novas[s])
            datas = {b[0] for b in (final or {}).get("barras") or []}
            if final and any(f in datas for f in faltam):
                antiga = self._carregar_serie_local(s) or {}
                if antiga.get("fechamentos_17h"):
                    final["fechamentos_17h"] = antiga["fechamentos_17h"]
                gravar_json(os.path.join(self.saida, "series", f"{uni.nome_seguro(s)}.json"), final)
                refeitas += 1
        self.pernas["buracos"] = f"{len(com_buraco)} séries com pregão faltando; {refeitas} completadas numa 2ª chamada"

    def coletar_series_longas(self, simbolos: list[str]) -> None:
        """Serie SEMANAL de 6 anos, so para a janela de 5 anos.

        A serie diaria e de 2 anos de proposito (arquivo pequeno, commit leve). Para
        5 anos basta o fechamento semanal: ~310 pontos por simbolo em vez de ~1.260.
        Roda uma vez por dia, no fechamento e na manha. No intradia nao se coleta de
        novo (a barra semanal nao mudou), mas a serie guardada e RELIDA do disco: sem
        isso a coluna "5 anos" do painel intradiario saia vazia."""
        if self.modo not in ("fechamento", "manha") or self.offline:
            if not self.offline:
                self._carregar_series_longas(simbolos)
            return
        try:
            novas, falhas = yahoo.coletar(simbolos, "6y", intervalo="1wk")
        except Exception as e:
            self.pernas["yahoo_longo"] = f"falha: {type(e).__name__}: {str(e)[:60]}"
            return
        ok = 0
        for simbolo in simbolos:
            d = novas.get(simbolo)
            if not d or not d.get("barras"):
                continue
            gravar_json(os.path.join(self.saida, "series_longo", f"{uni.nome_seguro(simbolo)}.json"), d)
            obj = self.u.por_yahoo(simbolo)
            if obj is not None:
                df = ind.para_df(d["barras"])
                if len(df):
                    self.series_longo[obj.id] = df
                    ok += 1
        self.pernas["yahoo_longo"] = f"ok {ok}/{len(simbolos)} (semanal 6 anos)" + (
            f"; falhas: {len(falhas)}" if falhas else "")

    def _carregar_series_longas(self, simbolos: list[str]) -> None:
        """Le do disco a serie semanal ja coletada hoje de manha (ou no fechamento
        anterior). Nao vai a rede: e so para a janela de 5 anos nao ficar vazia."""
        ok = 0
        for simbolo in simbolos:
            d = ler_json(os.path.join(self.saida, "series_longo", f"{uni.nome_seguro(simbolo)}.json"), {})
            if not d or not d.get("barras"):
                continue
            obj = self.u.por_yahoo(simbolo)
            if obj is not None:
                df = ind.para_df(d["barras"])
                if len(df):
                    self.series_longo[obj.id] = df
                    ok += 1
        self.pernas["yahoo_longo"] = f"reaproveitado {ok}/{len(simbolos)} (semanal do disco)"

    def _series_offline(self, simbolos: list[str]) -> None:
        import glob
        n = 0
        for arq in glob.glob(os.path.join(self.offline, "series", "*.json")):
            d = ler_json(arq)
            if not d:
                continue
            simbolo = d.get("ticker") or d.get("simbolo")
            if d.get("barras"):
                gravar_json(os.path.join(self.saida, "series", f"{uni.nome_seguro(simbolo)}.json"), d)
            else:
                barras = [[dt, p, p, p, p, p, 0] for dt, p in zip(d["dates"], d["prices"])]
                gravar_json(os.path.join(self.saida, "series", f"{uni.nome_seguro(simbolo)}.json"),
                            {"simbolo": simbolo, "moeda": None, "tz": None, "meta": {}, "barras": barras,
                             "eventos": {}, "coletado_em": "fixture"})
            n += 1
        self.pernas["yahoo"] = f"offline {n} fixtures"
        self._montar_dataframes(simbolos, {})

    def _mercado(self, obj) -> str:
        return obj.mercado if obj.mercado in self.calendario["mercados"] else "NYSE"

    def ate(self, id_: str):
        """Ultima data que entra nas contas deste ativo. Na manha e no fechamento, o
        ultimo pregao ENCERRADO do mercado dele (a barra viva de cripto, futuro e
        cambio fica de fora); no intradia, hoje."""
        if self.modo in ("manha", "fechamento"):
            obj = self.u.por_id(id_) or self.u.bench(id_)
            if obj is not None:
                return relogios.data_referencia(self._mercado(obj), self.agora)
            return self.hoje
        return relogios.brt(self.agora).date()

    def _barras_brent(self, d: dict, obj) -> tuple[list, dict]:
        """BZ=F ate pouco antes do contrato vigente virar o 1o vencimento; o contrato
        explicito dali em diante (futuros.emendar). Sem contrato bom, o continuo."""
        barras = d.get("barras") or []
        if obj.id != "BRENT" or _p(obj, "contrato_explicito") != "brent":
            return barras, {}
        cod = futuros.contrato_vigente(relogios.brt(self.agora).date())
        simb = futuros.simbolo_brent(cod)
        c = self._carregar_serie_local(simb) or {}
        bc = c.get("barras") or []
        if len(bc) < 5:
            return barras, {"contrato": f"{simb} indisponível; série contínua BZ=F (a conferir)"}
        # trava: contrato e continuo tem de estar na mesma ordem de grandeza
        comuns = {b[0]: b[4] for b in barras[-30:]}
        difs = [abs(b[4] / comuns[b[0]] - 1) for b in bc[-30:] if b[0] in comuns and comuns[b[0]]]
        if difs and sorted(difs)[len(difs) // 2] > 0.15:
            return barras, {"contrato": f"{simb} fora da faixa do contínuo; série contínua BZ=F (a conferir)"}
        emendadas, corte = futuros.emendar(barras, bc, cod)
        return emendadas, {"contrato": f"{futuros.rotulo(cod)} ({simb}) desde {fmt.data_br(corte)}",
                           "_dados_contrato": c}

    def _montar_dataframes(self, simbolos: list[str], falhas: dict) -> None:
        for s in simbolos:
            obj = self.u.por_yahoo(s)
            if obj is None:
                continue
            d = self._carregar_serie_local(s)
            if not d or not d.get("barras"):
                self.series_info[obj.id] = {"ausente": True, "esperado_hoje": True}
                continue
            mercado = self._mercado(obj)
            barras, extra = self._barras_brent(d, obj)
            dados_q = extra.pop("_dados_contrato", None) or d
            # cambio: o fechamento das 17h (15 minutos) vale por cima da barra diaria
            f17 = d.get("fechamentos_17h") or {}
            if f17:
                por_data = {b[0]: list(b) for b in barras}
                for data, (preco, _hora) in f17.items():
                    b = por_data.get(data)
                    if b is None:
                        por_data[data] = [data, preco, preco, preco, preco, preco, 0]
                    else:
                        b[4] = b[5] = preco
                        if b[2] is not None:
                            b[2] = max(b[2], preco)
                        if b[3] is not None:
                            b[3] = min(b[3], preco)
                barras = [por_data[k] for k in sorted(por_data)]
            barras = qa.limpar_fim_de_semana(barras, mercado)
            ate = self.ate(obj.id)
            classe = getattr(obj, "classe", "") or ""
            simb_q = (extra.get("contrato", "").split("(")[-1].split(")")[0]
                      if extra.get("contrato", "").startswith(tuple(futuros.MESES_PT)) else s)
            v = qa.avaliar({**dados_q, "barras": barras}, simb_q, mercado, classe, self.agora, ate,
                           confirmadas={k: x[1] for k, x in f17.items()})
            if v.descartar_ultima:
                barras = [b for b in barras if b[0] != v.data_barra]
            df = ind.para_df(barras)
            if len(df) == 0:
                self.series_info[obj.id] = {"ausente": True, "esperado_hoje": True}
                continue
            self.series[obj.id] = df
            esperado = relogios.data_referencia(mercado, self.agora)
            defasado = int(_p(obj, "defasagem_pregoes", 0) or 0) > 0
            if defasado:
                # minerio CME: liquida com um pregao de atraso; D-1 e o esperado, nao falha
                esperado = relogios.dia_util_anterior(mercado, esperado)
            vistos = df.loc[:ind.pd.Timestamp(ate)] if self.modo in ("manha", "fechamento") else df
            ultima = (vistos.index[-1] if len(vistos) else df.index[-1]).date()
            self.series_info[obj.id] = {
                "ultima": ultima.isoformat(), "esperado": esperado.isoformat(),
                "esperado_hoje": esperado == self.agora.astimezone(relogios.BRT).date(),
                "fresco": ultima >= esperado, "reaproveitada": bool(d.get("reaproveitada")),
                "falha": falhas.get(s), "barras": int(len(df)), "moeda": d.get("moeda"),
                # ativo que nao negocia todo pregao (ETF pouco liquido) ou que chega com
                # um pregao de atraso por natureza (minerio CME, D-1): dia sem barra e
                # normal e nao pode contar como falha de coleta
                "tolera_falta": bool(_p(obj, "sem_pregao_diario", False)) or defasado,
                "defasado": defasado,
                "qualidade": v.para_json(),
                **({"fechamento_17h": f17.get(ultima.isoformat(), [None, None])[1]} if f17.get(ultima.isoformat()) else {}),
                **extra,
            }

    # ------------------------------------------------------------ curvas e macro
    def coletar_curvas(self) -> None:
        cfg = self.u.curvas
        codigos = [v["codigo"] for v in cfg.get("di", {}).get("vertices", [])]
        caminho_di = os.path.join(self.saida, "curvas", "di.json")
        antigo = ler_json(caminho_di, {}) or {}
        if self.offline:
            self.curvas["di"] = antigo or self._offline_json("di.json") or {}
            self.curvas["tesouro"] = self._offline_json("tesouro.json") or ler_json(os.path.join(self.saida, "curvas", "tesouro.json"), {}) or {}
            self.curvas["ust"] = self._offline_json("ust.json") or ler_json(os.path.join(self.saida, "curvas", "ust.json"), {}) or {}
            self.macro["bcb"] = self._offline_json("bcb.json") or {}
            self.macro["focus"] = self._offline_json("focus.json") or {}
            self.macro["proxies"] = self._offline_json("proxies.json") or {}
            for k in ("di", "tesouro", "ust"):
                self.pernas[k] = "offline" if self.curvas.get(k) else "ausente"
            return
        # DI
        try:
            dias = self.dias_backfill if self.modo == "backfill" else (3 if self.modo in ("fechamento", "manha") else 1)
            di = b3_di.coletar(antigo.get("historico"), codigos, hoje=self.hoje, dias_backfill=dias,
                               max_tentativas=max(40, dias + 10))
            gravar_json(caminho_di, di)
            self.curvas["di"] = di
            self.pernas["di"] = f"ok até {di.get('ultimo_pregao')} ({', '.join(f'{k} {v}' for k, v in di['cobertura'].items())})"
            esperado_di = self.hoje if self.modo == "fechamento" else relogios.dia_util_anterior("B3", self.hoje)
            if str(di.get("ultimo_pregao") or "") < esperado_di.isoformat():
                self.falhas["di"] = f"ajuste B3 de {esperado_di.isoformat()} não publicado (último {di.get('ultimo_pregao')})"
        except Exception as e:
            self.curvas["di"] = antigo
            self.pernas["di"] = f"falha: {type(e).__name__}: {str(e)[:80]}"
            self.falhas["di"] = self.pernas["di"]
        # Tesouro (nao no intradia)
        caminho_tes = os.path.join(self.saida, "curvas", "tesouro.json")
        if self.modo in ("fechamento", "manha", "backfill"):
            try:
                titulos = list(cfg.get("tesouro", {}).get("titulos", [])) + list(cfg.get("tesouro", {}).get("controles", []))
                tes = tesouro.coletar(titulos)
                antigo_tes = ler_json(caminho_tes, {}) or {}
                if antigo_tes.get("data_base") and str(tes.get("data_base") or "") < str(antigo_tes["data_base"]):
                    # o CSV voltou mais velho que o guardado (cache do CKAN): nao regride
                    tes = antigo_tes
                else:
                    gravar_json(caminho_tes, tes)
                self.curvas["tesouro"] = tes
                self.pernas["tesouro"] = f"ok base {tes.get('data_base')}"
                # a base esperada e D-1 (o Tesouro Transparente publica o dia anterior).
                # Em 23/09 a base era 18/09 e o manifest dizia "ok": dois pregoes de
                # atraso sem lacuna nem alerta (auditoria de 23/09)
                if tes.get("data_base"):
                    esperado = relogios.dia_util_anterior("B3", self.hoje)
                    faltam = []
                    d = relogios._d(tes["data_base"])
                    while d < esperado:
                        d = relogios.proximo_dia_util("B3", d)
                        if d <= esperado:
                            faltam.append(d.isoformat())
                    if faltam:
                        self.pernas["tesouro"] += f" (atrasada: faltam {', '.join(fmt.data_br(x) for x in faltam)})"
                        self.falhas["tesouro"] = (f"Tesouro Transparente com data-base {fmt.data_br(tes['data_base'])}; "
                                                  f"faltam {', '.join(fmt.data_br(x) for x in faltam)} (taxas não são as de hoje)")
            except Exception as e:
                self.curvas["tesouro"] = ler_json(caminho_tes, {}) or {}
                self.pernas["tesouro"] = f"falha: {type(e).__name__}: {str(e)[:80]}"
                self.falhas["tesouro"] = self.pernas["tesouro"]
        else:
            self.curvas["tesouro"] = ler_json(caminho_tes, {}) or {}
            self.pernas["tesouro"] = "reaproveitado (intradia)"
        # UST
        caminho_ust = os.path.join(self.saida, "curvas", "ust.json")
        antigo_ust = ler_json(caminho_ust, {}) or {}
        try:
            meses = 24 if (self.modo == "backfill" or not antigo_ust.get("historico")) else 2
            u = ust.coletar(antigo_ust.get("historico"), meses=meses, hoje=self.agora.astimezone(relogios.BRT).date())
            gravar_json(caminho_ust, u)
            self.curvas["ust"] = u
            self.pernas["ust"] = f"ok até {u.get('ultima_data')} ({u.get('fonte')})"
        except Exception as e:
            self.curvas["ust"] = antigo_ust
            self.pernas["ust"] = f"falha: {type(e).__name__}: {str(e)[:80]}"
            self.falhas["ust"] = self.pernas["ust"]
        # BCB, Focus, proxies
        try:
            b = bcb.coletar_sgs()
            faltando = [k for k in bcb.SERIES if k not in (b.get("series") or {})]
            if b.get("series"):
                gravar_json(os.path.join(self.saida, "macro", "bcb.json"), b)
                self.macro["bcb"] = b
            else:
                self.macro["bcb"] = ler_json(os.path.join(self.saida, "macro", "bcb.json"), {}) or {}
            n, total = len(b.get("series") or {}), len(bcb.SERIES)
            self.pernas["bcb"] = f"ok {n}/{total} séries" + (f"; faltaram {', '.join(faltando)}" if faltando else "")
            if faltando:
                self.falhas["bcb"] = f"BCB devolveu {n} de {total} séries (faltaram {', '.join(faltando)})"
        except Exception as e:
            self.macro["bcb"] = ler_json(os.path.join(self.saida, "macro", "bcb.json"), {}) or {}
            self.pernas["bcb"] = f"falha: {e}"
            self.falhas["bcb"] = self.pernas["bcb"]
        if self.modo in ("manha", "fechamento", "backfill"):
            try:
                f = bcb.coletar_focus()
                exp = [k for k, v in (f.get("expectativas") or {}).items() if (v or {}).get("por_ano")]
                if exp:
                    gravar_json(os.path.join(self.saida, "macro", "focus.json"), f)
                    self.macro["focus"] = f
                    self.pernas["focus"] = f"ok {exp}"
                else:
                    # resposta vazia nao sobrescreve a pesquisa boa que ja esta no disco
                    antigo_f = ler_json(os.path.join(self.saida, "macro", "focus.json"), {}) or {}
                    self.macro["focus"] = antigo_f
                    reusa = [k for k, v in (antigo_f.get("expectativas") or {}).items() if (v or {}).get("por_ano")]
                    self.pernas["focus"] = "vazio" + (f"; reaproveitada a coleta de {str(antigo_f.get('coletado_em'))[:10]}" if reusa else "")
                    self.falhas["focus"] = ("Focus voltou sem expectativas" + (f"; usada a pesquisa anterior ({str(antigo_f.get('coletado_em'))[:10]})" if reusa
                                                                               else "; sem pesquisa anterior no disco"))
            except Exception as e:
                self.macro["focus"] = ler_json(os.path.join(self.saida, "macro", "focus.json"), {}) or {}
                self.pernas["focus"] = f"falha: {e}"
                self.falhas["focus"] = self.pernas["focus"]
            try:
                p = sina.coletar()
                antigo_p = ler_json(os.path.join(self.saida, "macro", "proxies.json"), {}) or {}
                p["bhkp_semanal"] = antigo_p.get("bhkp_semanal")
                p["bhkp_anterior"] = antigo_p.get("bhkp_anterior")
                # historico diario dos proxies (um ponto por data), para variacao semanal
                hist = antigo_p.get("historico") or {}
                for chave, v in (p.get("proxies") or {}).items():
                    if v.get("preco") and v.get("data"):
                        serie = [x for x in (hist.get(chave) or []) if x[0] != v["data"]]
                        serie.append([v["data"], v["preco"]])
                        hist[chave] = sorted(serie)[-90:]
                p["historico"] = hist
                # celulose e minerio em US$ (pedido do Douglas): converte pelo CNY=X do dia
                p["em_dolar"] = sina.em_dolar(p, self.series.get("CNY"), self.hoje)
                gravar_json(os.path.join(self.saida, "macro", "proxies.json"), p)
                self.macro["proxies"] = p
                self.pernas["proxies"] = f"ok {list((p.get('proxies') or {}).keys())}" + (f"; {p['falhas']}" if p.get("falhas") else "")
            except Exception as e:
                self.macro["proxies"] = ler_json(os.path.join(self.saida, "macro", "proxies.json"), {}) or {}
                self.pernas["proxies"] = f"falha: {e}"
        else:
            self.macro["focus"] = ler_json(os.path.join(self.saida, "macro", "focus.json"), {}) or {}
            self.macro["proxies"] = ler_json(os.path.join(self.saida, "macro", "proxies.json"), {}) or {}

    def _offline_json(self, nome: str):
        return ler_json(os.path.join(self.offline, "raw", nome)) if self.offline else None

    # ------------------------------------------------------------ eventos (noticias, CVM, SEC)
    def coletar_eventos(self) -> None:
        """Noticias em todo slot; CVM (IPE atualiza uma vez ao dia) na manha, no
        fechamento, no modo eventos e no intradia das 12h e 15h BRT; SEC em todo slot
        (leve), declarada indisponivel sem o secret. Cada perna falha sozinha."""
        cfg = uni.carregar_yaml("fontes_noticias.yaml")
        self.eventos = {"config": cfg, "noticias": [], "cvm": [], "sec": [], "calendario": self.calendario, "agenda": {}}
        hoje_brt = relogios.brt(self.agora).date()
        if self.offline:
            for perna in ("noticias", "cvm", "sec"):
                d = ler_json(os.path.join(self.offline, "eventos", f"{perna}.json"), {}) or {}
                self.eventos[perna] = d.get("itens") or d.get("docs") or d.get("filings") or []
                self.pernas[perna] = f"offline {len(self.eventos[perna])}"
            ag = ler_json(os.path.join(self.offline, "eventos", "agenda_yahoo.json"), {}) or {}
            self.eventos["agenda"] = f_agenda.consolidar(self.calendario, ag.get("por_ativo") or {}, hoje_brt, self.u)
            self.pernas["agenda"] = f"offline {len(self.eventos['agenda'].get('resultados', []))} resultados"
            return
        # agenda corporativa (Yahoo calendarEvents + calendario.yaml): manha e fechamento
        if self.modo in ("manha", "fechamento"):
            try:
                ag = f_agenda.coletar(self.u)
                gravar_json(os.path.join(self.saida, "eventos", "agenda_yahoo.json"), ag)
                self.eventos["agenda"] = f_agenda.consolidar(self.calendario, ag.get("por_ativo") or {}, hoje_brt, self.u)
                gravar_json(os.path.join(self.saida, "eventos", "agenda.json"), self.eventos["agenda"])
                self.pernas["agenda"] = (f"ok {len(self.eventos['agenda'].get('resultados', []))} resultados, "
                                         f"{len(self.eventos['agenda'].get('ex_dividendos', []))} ex-dividendos"
                                         + (f"; {len(ag['falhas'])} ativos sem resposta" if ag.get("falhas") else ""))
            except Exception as e:
                self.falhas["agenda"] = f"{type(e).__name__}: {str(e)[:80]}"
                self.pernas["agenda"] = "falhou"
                self.eventos["agenda"] = ler_json(os.path.join(self.saida, "eventos", "agenda.json"), {}) or f_agenda.consolidar(self.calendario, {}, hoje_brt, self.u)
        else:
            self.eventos["agenda"] = ler_json(os.path.join(self.saida, "eventos", "agenda.json"), {}) or f_agenda.consolidar(self.calendario, {}, hoje_brt, self.u)
        caminho_vistos = os.path.join(self.saida, "noticias", "vistos.json")
        vistos = ler_json(caminho_vistos, {}) or {}
        hora_brt = relogios.brt(self.agora).hour
        lim = self.limiares
        # noticias
        try:
            n = noticias.coletar(cfg, vistos.get("noticias"), agora=self.agora)
            self.eventos["noticias"] = n["itens"]
            vistos["noticias"] = n["vistos"]
            gravar_json(os.path.join(self.saida, "eventos", "noticias.json"),
                        {k: v for k, v in n.items() if k != "vistos"})
            desc = n.get("descartados") or {}
            self.pernas["noticias"] = (f"ok {len(n['itens'])} novas ({n['consultas']} consultas; descartadas: "
                                       f"{desc.get('veiculo_desconhecido', 0)} veículo fora da lista, {desc.get('sem_ativo', 0)} sem ativo, "
                                       f"{desc.get('teto', 0)} teto)" + (f"; {len(n['falhas'])} falhas" if n["falhas"] else ""))
            for it in n["itens"]:
                if it.get("texto"):
                    gravar_json(os.path.join(self.saida, "noticias", "corpo", f"{it['id']}.json"),
                                {k: it.get(k) for k in ("id", "titulo", "veiculo", "url", "licenca", "publicado", "ativos", "texto")})
        except Exception as e:
            self.falhas["noticias"] = f"{type(e).__name__}: {str(e)[:80]}"
            self.pernas["noticias"] = "falhou"
        # CVM
        c_cfg = lim.get("E03_CVM") or {}
        roda_cvm = self.modo in (c_cfg.get("slots") or ["manha", "fechamento", "eventos", "intradia"])
        if roda_cvm:
            try:
                c = cvm.coletar(cfg.get("cvm") or {}, hoje=hoje_brt, dias=int(c_cfg.get("dias", 3)),
                                categorias=cfg.get("cvm_categorias"), vistos=vistos.get("cvm"),
                                max_pdf=int(c_cfg.get("max_pdf_por_run", 8)),
                                com_ipe=self.modo in (c_cfg.get("ipe_slots") or ["manha"]))
                self.eventos["cvm"] = c["docs"]
                vistos["cvm"] = c["vistos"]
                gravar_json(os.path.join(self.saida, "eventos", "cvm.json"), {k: v for k, v in c.items() if k != "vistos"})
                self.pernas["cvm"] = (f"ok {len(c['docs']) - c.get('atualizados', 0)} novos de {c['todos']} ({len(c['empresas_casadas'])} cias casadas)"
                                      + (f"; {c['atualizados']} PDF lido em nova tentativa" if c.get("atualizados") else "")
                                      + (f"; falhas {list(c['falhas'])}" if c["falhas"] else ""))
                for d in c["docs"]:
                    if d.get("texto"):
                        gravar_json(os.path.join(self.saida, "noticias", "corpo", f"{d['id']}.json"),
                                    {"id": d["id"], "titulo": f"{d['categoria']}: {d['assunto']}", "veiculo": "CVM", "url": d["link"],
                                     "licenca": "integral", "publicado": d["entregue_em"], "ativos": [d["ativo"]], "texto": d["texto"]})
            except Exception as e:
                self.falhas["cvm"] = f"{type(e).__name__}: {str(e)[:80]}"
                self.pernas["cvm"] = "falhou"
        else:
            self.pernas["cvm"] = "fora do slot"
        # SEC
        s_cfg = lim.get("E04_SEC") or {}
        try:
            s = sec.coletar(cfg.get("sec") or {}, hoje=hoje_brt, dias=int(s_cfg.get("dias", 3)),
                            formularios=cfg.get("sec_formularios"), vistos=vistos.get("sec"),
                            max_docs=int(s_cfg.get("max_docs_por_run", 6)),
                            dias_primeira_vez=int(s_cfg.get("dias_primeira_vez", 15)))
            if not s.get("disponivel"):
                self.pernas["sec"] = f"indisponível ({s.get('motivo')})"
            else:
                self.eventos["sec"] = s["filings"]
                vistos["sec"] = s["vistos"]
                gravar_json(os.path.join(self.saida, "eventos", "sec.json"), {k: v for k, v in s.items() if k != "vistos"})
                contato = str(s.get("ua_usado") or "")
                self.pernas["sec"] = (f"ok {len(s['filings'])} novos em {s.get('janela_dias', '?')} dias"
                                      + (" (primeira coleta)" if s.get("primeira_coleta") else "")
                                      + (f"; falhas {list(s['falhas'])}" if s["falhas"] else ""))
                if s.get("falhas"):
                    self.falhas["sec"] = "; ".join(f"{k}: {v}" for k, v in s["falhas"].items())[:300]
                for f in s["filings"]:
                    if f.get("texto"):
                        gravar_json(os.path.join(self.saida, "noticias", "corpo", f"{f['id']}.json"),
                                    {"id": f["id"], "titulo": f"{f['form']}: {', '.join(f.get('itens_rotulo') or [])}", "veiculo": "SEC",
                                     "url": f["url"], "licenca": "integral", "publicado": f["aceito_em"], "ativos": [f["ativo"]], "texto": f["texto"]})
        except Exception as e:
            self.falhas["sec"] = f"{type(e).__name__}: {str(e)[:80]}"
            self.pernas["sec"] = "falhou"
        gravar_json(caminho_vistos, vistos)

    # ------------------------------------------------------------ sinais
    def rodar_sinais(self, repo: Repositorio) -> tuple[list, Contexto]:
        # No fechamento e na manha a regra tem de enxergar o MESMO pregao que a tabela.
        # Sem isso, um ativo de mercado continuo (cripto) dispara com a barra do dia
        # ainda se formando e o alerta fica com o numero intradiario para sempre,
        # enquanto a tabela mostra o fechamento.
        series_ctx = self.series
        if self.modo in ("fechamento", "manha"):
            series_ctx = {k: df.loc[:ind.pd.Timestamp(self.ate(k))] for k, df in self.series.items()
                          if len(df.loc[:ind.pd.Timestamp(self.ate(k))])}
        ctx = Contexto(universo=self.u, limiares=self.limiares, hoje=self.hoje, slot=self.modo,
                       series=series_ctx, series_info=self.series_info, curvas=self.curvas,
                       macro=self.macro, falhas=self.falhas, agora_iso=self.agora.strftime("%Y-%m-%dT%H:%M:%SZ"),
                       eventos=self.eventos)
        ordem = ([r_curvas.C01DIMovimento(), r_curvas.C04TesouroJuroReal(), r_curvas.C05TesouroVariacaoPU(), r_curvas.C07UST()]
                 + r_curvas.REGRAS_V11
                 + [r_tec.T13Regime(), r_tec.T01MM200(), r_tec.T03GoldenDeath(), r_tec.T04MaxMin(), r_tec.T05Zscore(), r_tec.T08Drawdown()]
                 + r_tec2.REGRAS
                 + [r_fx.F01USDBRL(), r_fx.F03Brent(), r_fx.F06Cripto()] + r_fx.REGRAS_V11
                 + r_evm.REGRAS + r_ev.REGRAS + [r_sis.S01FalhaDados()])
        if self.modo == "intradia":
            # intradia: so o que e seguro sem fechamento consolidado
            ordem = ([r_tec.T13Regime(), r_fx.F01USDBRL(), r_fx.F03Brent(), r_fx.F06Cripto(), r_fx.F02DXY()]
                     + r_evm.REGRAS + r_ev.REGRAS + [r_sis.S01FalhaDados()])
        elif self.modo == "eventos":
            ordem = list(r_ev.REGRAS)
        alertas = []
        for regra in ordem:
            try:
                alertas += regra.avaliar(ctx, repo.regras)
            except Exception as e:
                _log(f"regra {regra.id} falhou: {type(e).__name__}: {e}")
                self.falhas[f"regra_{regra.id}"] = f"{type(e).__name__}: {str(e)[:80]}"
        alertas = self._portao_alertas(alertas)
        if self.modo == "intradia":
            # no intradia, movimentos sao 'parciais': so critico passa como alerta proprio
            for a in alertas:
                if a.familia in ("cambio", "commodity", "cripto") and a.severidade != "critico":
                    a.severidade = "info"
                if a.familia in ("cambio", "commodity", "cripto"):
                    a.titulo = a.titulo + " (parcial, intradia)"
        return alertas, ctx

    # regras que leem a variacao do DIA: nao podem rodar sobre dois pregoes nem sobre
    # barra parcial (MMM +3,2% "no dia" em 23/09 eram dois pregoes; o T05 disparou)
    REGRAS_DO_DIA = {"T05", "T06", "T09", "F01", "F02", "F03", "F04", "F06"}

    def _portao_alertas(self, alertas: list) -> list:
        """Nenhum alerta sai de serie nao confirmada. Serie suspeita rebaixa um degrau
        e avisa no titulo. Regra do dia nao roda sobre buraco nem barra parcial."""
        passam, segurados = [], []
        for a in alertas:
            if a.familia in ("evento", "noticia", "sistema", "curva"):
                passam.append(a)           # noticia, fato relevante e curva nao dependem da barra do Yahoo
                continue
            ids = [a.ativo] + [x for x in ((a.dados or {}).get("par") or []) if isinstance(x, str)]
            motivo, suspeita = None, None
            for i in ids:
                info = self.series_info.get(i)
                if not info:
                    continue
                q = info.get("qualidade") or {}
                if q.get("status") == qa.NAO_CONFIRMADO and not q.get("descartar_ultima"):
                    motivo = f"{i}: {(q.get('motivos') or ['dado não confirmado'])[0]}"
                elif a.regra in self.REGRAS_DO_DIA and q.get("dia_pregoes", 1) > 1:
                    motivo = f"{i}: variação de {q['dia_pregoes']} pregões (sem {', '.join(fmt.data_br(x) for x in q.get('sem_barra', []))})"
                elif a.regra in self.REGRAS_DO_DIA and q.get("parcial") and a.familia != "cripto":
                    motivo = f"{i}: barra parcial"
                elif q.get("status") == qa.SUSPEITO:
                    suspeita = (q.get("motivos") or ["dado a confirmar"])[0]
                if motivo:
                    break
            if motivo:
                segurados.append(f"{a.regra} {a.ativo} ({motivo})")
                continue
            if suspeita and a.familia not in ("evento", "noticia", "sistema"):
                a.severidade = {"critico": "atencao", "atencao": "info"}.get(a.severidade, a.severidade)
                a.titulo += " (dado a confirmar)"
                a.corpo = list(a.corpo) + [f"Dado a confirmar: {suspeita}"]
            passam.append(a)
        if segurados:
            self.falhas["alertas_segurados"] = ("alertas não emitidos por dado não confirmado: "
                                                + "; ".join(segurados[:8]))
        return passam

    # ------------------------------------------------------------ render
    def renderizar(self, ctx: Contexto, resultado: dict, repo: Repositorio) -> dict:
        saida = os.path.join(self.saida, "saida")
        janelas = {}
        for a in self.u.ativos:
            if a.id in self.series:
                # corte por mercado: na manha e no fechamento, o ultimo pregao encerrado
                # do mercado do ativo (a barra viva de cripto, futuro e cambio fica fora)
                ate_a = self.ate(a.id)
                j = ind.janelas(self.series[a.id], ate=ate_a)
                # 5 anos: numerador = ultima barra DIARIA (a semanal da semana corrente
                # pode ser um toco: em 23/09 a semanal do Brent era 97,83)
                j["5a"] = ind.retorno_longo(self.series_longo.get(a.id), self.series[a.id], 1826, ate=ate_a)
                info = self.series_info.get(a.id) or {}
                q = info.get("qualidade") or {}
                j["qualidade"] = q.get("status", qa.OK)
                j["dia_pregoes"] = q.get("dia_pregoes", 1)
                j["sem_barra"] = q.get("sem_barra", [])
                j["parcial"] = bool(q.get("parcial"))
                j["dia_confirmado"] = qa.dia_valido(info)
                # contexto do movimento: volume contra a media, onde fechou na amplitude,
                # extremo de 52 semanas (so com barra completa e dia confirmado)
                if j["dia_confirmado"] and a.classe in ("acao", "etf", "bdr"):
                    j.update(atribuicao.qualidade_dia(self.series[a.id], ate_a))
                if j["dia_confirmado"]:
                    ext = atribuicao.extremo_52s(self.series[a.id], ate_a)
                    if ext:
                        j["extremo_52s"] = ext
                janelas[a.id] = j
        # referencias das cestas setoriais (benchmarks), com o mesmo portao
        janelas_ref = {}
        for c in getattr(self.u, "cestas", []) or []:
            for m in list(c.get("membros", [])) + ([c["fator"]] if c.get("fator") and not str(c["fator"]).startswith("DI1F") else []):
                if m in janelas or m in janelas_ref or m not in self.series:
                    continue
                jr = ind.janelas(self.series[m], ate=self.ate(m))
                jr["dia_confirmado"] = qa.dia_valido(self.series_info.get(m))
                janelas_ref[m] = jr
        eventos_prox = self._proximos_eventos()
        for id_, ev in eventos_prox.items():
            if id_ in janelas:
                janelas[id_]["proximo_evento"] = ev
        do_dia = repo.do_dia(self.hoje.isoformat(), relogios.brt(self.agora).date().isoformat())
        rot = SLOT_ROTULO.get(self.modo, self.modo)
        alertas_txt = render.alertas_md(resultado, do_dia, rot)
        with open(os.path.join(saida, "alertas.md"), "w", encoding="utf-8") as f:
            f.write(alertas_txt)
        hora = fmt.data_br(self.agora.astimezone(relogios.BRT).date().isoformat()) + " " + relogios.fmt_brt(self.agora)
        with open(os.path.join(saida, "noticias.md"), "w", encoding="utf-8") as f:
            f.write(render.noticias_md(do_dia, hora, self.pernas))
        out = {"alertas": len(resultado["mensagens"]), "criticos": sum(1 for m in resultado["mensagens"] if m["severidade"] == "critico"),
               "noticias": sum(1 for a in do_dia if a.get("familia") in ("noticia", "evento"))}
        if self.modo == "eventos":
            with open(os.path.join(saida, "eventos.md"), "w", encoding="utf-8") as f:
                f.write((alertas_txt if resultado["mensagens"] else f"{relogios.fmt_brt(self.agora)} · sem noticia ou fato novo atribuido ao livro\n") + "\n")
            return out
        if self.modo == "intradia":
            ucits = [f"{a.id} {fmt.pct(janelas[a.id].get('dia'))}" for a in self.u.ucits()[:4] if a.id in janelas and self.series_info.get(a.id, {}).get("fresco")]
            obs = ("UCITS fecharam: " + ", ".join(ucits)) if ucits and relogios.fechou("LSE", self.agora) else ""
            txt = render.linha_sem_novidade(relogios.fmt_brt(self.agora), relogios.fmt_brt(self.agora), obs, "") if not resultado["mensagens"] else alertas_txt
            with open(os.path.join(saida, "intradia.md"), "w", encoding="utf-8") as f:
                f.write(txt + "\n")
            # NAO retorna aqui: o painel e republicado em todo slot (pedido do Douglas
            # em 21/09), entao o intradia tambem regenera painel.html. O que continua
            # so na manha e no fechamento sao os .md longos, o celular, os cards e o
            # fechamento.json - o intradia nao tem Tesouro novo nem ajuste do dia.
        curvas_l, lacunas_c, ins = render.curvas_linhas(self.curvas, self.u, self.macro, ctx.regime, self.hoje)
        # material de analise para a Leitura da Mesa: amplitude, extremos, pares
        # descolados, drawdowns e vol abrindo. A sessao narra; quem calcula e o runner.
        try:
            ins["mesa"] = insumos.montar(self.u, self.series, janelas, self.hoje)
        except Exception as e:
            self.falhas["insumos_mesa"] = f"{type(e).__name__}: {str(e)[:80]}"
        try:
            ins["setores"] = atribuicao.cestas(self.u, {**janelas, **janelas_ref}, ins)
            ins["por_que_mexeu"] = atribuicao.por_que_mexeu(self.u, janelas, ins["setores"], self.eventos,
                                                            do_dia, self.hoje.isoformat())
            ins["brent_reais"] = atribuicao.brent_reais(janelas)
            ins["correcoes"] = self.correcoes
        except Exception as e:
            self.falhas["insumos_setores"] = f"{type(e).__name__}: {str(e)[:80]}"
        b_txt, lacunas_b = render.bloco_b(self.u, janelas, self.series_info, "completo")
        b_cel, _ = render.bloco_b(self.u, janelas, self.series_info, "celular")
        lacunas = (lacunas_c + lacunas_b + self._lacunas_qualidade()
                   + [f"{k}: {v}" for k, v in self.falhas.items() if not k.startswith("regra_")])
        mov = render.movers(janelas, self.u)
        relogios_txt = self._relogios_txt()
        fontes = ["Yahoo Finance", "B3 Boletim Diário", "Tesouro Transparente", "Treasury.gov CMT", "BCB"]
        # "parcial" = pregao dos EUA ainda aberto; vale para todos os blocos de la
        eua = [a for b in ("etf_eua", "eua_semis", "eua_tech", "eua_banco", "eua_outros")
               for a in self.u.por_bloco(b)]
        parcial = any(not (self.series_info.get(a.id) or {}).get("fresco", True) for a in eua)
        coleta_dia = relogios.brt(self.agora).date()
        hora_txt = relogios.fmt_brt(self.agora) + ("" if coleta_dia == self.hoje else f" de {fmt.data_br(coleta_dia.isoformat())}")
        agenda_l = render.agenda(self.calendario, self.hoje, extras=render.agenda_extras(self.eventos.get("agenda") or {}, self.calendario))
        a_txt = ("" if self.modo == "intradia" else
                 render.bloco_a(self.hoje, relogios_txt, do_dia, [], mov, curvas_l, agenda_l,
                                lacunas, fontes, parcial=parcial, slot=self.modo, hora=hora_txt))
        legenda = render.legenda_ucits(self.u)
        notas = []
        prox = (self.macro.get("proxies") or {}).get("proxies") or {}
        if "DCE_I0" in prox and prox["DCE_I0"].get("preco"):
            notas.append(f"Minério: proxy Dalian {fmt.num(prox['DCE_I0']['preco'], 0)} CNY/t ({prox['DCE_I0'].get('data')}).")
        if "SHFE_SP" in prox and prox["SHFE_SP"].get("preco"):
            notas.append(f"Celulose: proxy SHFE SP (fibra longa) {fmt.num(prox['SHFE_SP']['preco'], 0)} CNY/t; BHKP sem série diária.")
        bh = (self.macro.get("proxies") or {}).get("bhkp_semanal")
        if bh:
            notas.append(f"BHKP semanal: US$ {fmt.num(bh.get('valor'), 0)}/t ({bh.get('fonte')}, {bh.get('data')}).")
        if self.modo != "intradia":
            md = render.fechamento_md(a_txt, b_txt, legenda, notas)
            nome = "manha.md" if self.modo == "manha" else "fechamento.md"
            with open(os.path.join(saida, nome), "w", encoding="utf-8") as f:
                f.write(md)
        if self.modo not in ("manha", "intradia"):
            with open(os.path.join(saida, "fechamento_celular.md"), "w", encoding="utf-8") as f:
                f.write("```\n" + b_cel + "\n```\n" + legenda + "\n")
        if self.modo != "intradia":
            gravar_json(os.path.join(saida, "fechamento.json"), {
                "data": self.hoje.isoformat(), "slot": self.modo, "gerado_em": self.agora.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "janelas": janelas, "series_info": self.series_info, "movers": mov, "leitura_insumos": ins,
                "alertas_do_dia": do_dia, "lacunas": lacunas, "relogios": relogios_txt,
                "push_sugerido": self._push_fechamento(do_dia, mov, ins),
                "qualidade": qa.resumo(self.series_info), "drivers": qa.drivers(self.series_info, janelas),
            })
            # cards em markdown: o que a sessao cola no chat as 18h40 (escolha do Douglas)
            nome_cards = "manha_cards.md" if self.modo == "manha" else "fechamento_cards.md"
            with open(os.path.join(saida, nome_cards), "w", encoding="utf-8") as f:
                f.write(cards.cards_md(self.u, self.hoje, self.modo, hora_txt, relogios_txt, janelas,
                                       self.series_info, do_dia, ins, mov, agenda_l, lacunas, notas,
                                       fontes, parcial=parcial, em_dolar=(self.macro.get("proxies") or {}).get("em_dolar")))
        # painel HTML: a mesma coleta virada pagina; a sessao so troca o marcador da
        # leitura e publica como Artifact
        with open(os.path.join(saida, "painel.html"), "w", encoding="utf-8") as f:
            f.write(painel.pagina(self.u, self.hoje, self.modo, hora_txt, relogios_txt, janelas,
                                  self.series_info, do_dia, ins, mov, agenda_l, lacunas, notas,
                                  fontes, parcial=parcial, em_dolar=(self.macro.get("proxies") or {}).get("em_dolar")))
        out.update({"lacunas": len(lacunas), "tamanho_a": len(a_txt), "tamanho_b": len(b_txt)})
        return out

    def _proximos_eventos(self, dias: int = 14) -> dict:
        """{ativo: 'resultado 30/09' | 'data-com 01/10' | 'ex-dividendo hoje'} nos proximos
        ~10 pregoes, para o sufixo da linha da tabela."""
        ag = self.eventos.get("agenda") or {}
        hoje = self.hoje
        out: dict = {}
        for r in ag.get("resultados") or []:
            d = relogios._d(r["data"])
            if hoje <= d <= hoje + relogios.timedelta(days=dias) and self.u.por_id(r["ticker"]):
                out.setdefault(r["ticker"], f"resultado {fmt.data_br(d.isoformat())}" + ("" if r.get("confirmado") else " (estimado)"))
        for e in ag.get("ex_dividendos") or []:
            d = relogios._d(e["data"])
            if not self.u.por_id(e["ticker"]):
                continue
            if d == hoje:
                out[e["ticker"]] = "ex-dividendo hoje" + (f" ({e.get('moeda', '')} {fmt.num(e['valor'], 2)})".replace("( ", "(") if e.get("valor") else "")
            elif hoje < d <= hoje + relogios.timedelta(days=dias):
                out.setdefault(e["ticker"], f"data-com {fmt.data_br(d.isoformat())}")
        return out

    def _lacunas_qualidade(self) -> list[str]:
        """O que o portao segurou, em portugues, para o rodape e para a sessao."""
        out, buracos = [], {}
        for id_, info in self.series_info.items():
            if not self.u.por_id(id_):
                continue
            q = info.get("qualidade") or {}
            if q.get("descartar_ultima"):
                out.append(f"{id_}: {q['motivos'][0]}; barra descartada, fica a de {fmt.data_br(info.get('ultima'))}")
            elif q.get("status") == qa.NAO_CONFIRMADO:
                out.append(f"{id_}: {q['motivos'][0]}; variação do dia a confirmar")
            elif q.get("dia_pregoes", 1) > 1:
                chave = ", ".join(fmt.data_br(x) for x in q.get("sem_barra", []))
                buracos.setdefault(chave, []).append(id_)
            if info.get("contrato") and "a conferir" in str(info.get("contrato")):
                out.append(f"{id_}: {info['contrato']}")
        for datas, ids in buracos.items():
            n = datas.count(",") + 2
            out.append(f"sem barra de {datas} no Yahoo, variação do dia cobre {n} pregões: {', '.join(ids)}")
        return out

    def _relogios_txt(self) -> str:
        partes = []
        y = [i for i in self.series_info.values() if i.get("ultima")]
        if y:
            partes.append(f"Yahoo {relogios.fmt_brt(self.agora)}")
        di = self.curvas.get("di") or {}
        if di.get("ultimo_pregao"):
            partes.append("DI ajuste " + ("D0" if di["ultimo_pregao"] == self.hoje.isoformat() else fmt.data_br(di["ultimo_pregao"])))
        tes = self.curvas.get("tesouro") or {}
        if tes.get("data_base"):
            partes.append(f"Tesouro base {fmt.data_br(tes['data_base'])}")
        u = self.curvas.get("ust") or {}
        if u.get("ultima_data"):
            partes.append("UST CMT " + ("D0" if u["ultima_data"] == self.hoje.isoformat() else fmt.data_br(u["ultima_data"])))
        ptax = ((self.macro.get("bcb") or {}).get("series") or {}).get("ptax_venda")
        if ptax:
            partes.append(f"PTAX {fmt.data_br(ptax.get('data'))}")
        return " · ".join(partes)

    def _push_fechamento(self, do_dia: list[dict], mov: dict, ins: dict) -> str:
        """Texto do push (< 200 caracteres): curva, criticos, movers, contagem. Encurta por
        partes inteiras, nunca no meio de uma palavra."""
        # na manha o push nao se chama "Fechamento": os precos sao do pregao anterior
        corr = [f"CORREÇÃO {c['ativo']} {fmt.data_br(c['data'])} {fmt.pct(c['var_certa'])}, não {fmt.pct(c['var_entregue'])}"
                for c in (ins.get("correcoes") or [])][:2]
        cab = (f"Manhã {fmt.data_br(self.hoje.isoformat())} (pregão de "
               f"{fmt.data_br(relogios.dia_util_anterior('B3', self.hoje).isoformat())}):"
               if self.modo == "manha" else f"Fechamento {fmt.data_br(self.hoje.isoformat())}:")
        partes = []
        di = ins.get("di")
        if di:
            f28, f35 = di["deltas"].get("DI1F28"), di["deltas"].get("DI1F35")
            det = f" (F28 {fmt.bps(f28)}, F35 {fmt.bps(f35)} bps)" if f28 is not None and f35 is not None else ""
            partes.append(f"curva {di['verbo']}{det}")
        for a in [a for a in do_dia if a.get("severidade") == "critico"][:2]:
            t = str(a.get("titulo", "")).split(":")[0].strip()
            alnum = lambda s: "".join(ch for ch in s.lower() if ch.isalnum())
            if not alnum(t).startswith(alnum(str(a.get("ativo", "")))):
                t = f"{a.get('ativo')} {t}"
            partes.append(t)
        extras = []
        if mov.get("altas"):
            extras.append("alta " + ", ".join(f"{i} {fmt.pct(v)}" for i, v in mov["altas"][:2]))
        if mov.get("baixas"):
            extras.append("queda " + ", ".join(f"{i} {fmt.pct(v)}" for i, v in mov["baixas"][:2]))
        # conta o que o Douglas vai de fato ler, nao a fila inteira do runner
        lidos = [x for x in do_dia if x.get("canal") == "mensagem"]
        fim = f"{len(lidos)} alertas. Leitura na sessão."

        def montar(ps: list[str]) -> str:
            return (cab + " " + "; ".join(ps) + ". " + fim) if ps else (cab + " " + fim)

        partes = corr + partes
        txt = montar(partes + extras)
        if len(txt) > 195:
            txt = montar(partes)
        if len(txt) > 195:
            txt = montar([p if len(p) <= 60 else p[:60].rsplit(" ", 1)[0] for p in partes])
        if len(txt) > 195:
            txt = montar(partes[:1])
        return txt[:195]

    # ------------------------------------------------------------ manifest
    def manifest(self, extra: dict) -> dict:
        m = {
            "slot": self.modo, "run_id": self.run_id, "gerado_em": self.agora.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "gerado_em_brt": relogios.fmt_brt(self.agora, com_data=True), "data_pregao": self.hoje.isoformat(),
            "mercados": {m: {"fechou": relogios.fechou(m, self.agora), "referencia": relogios.data_referencia(m, self.agora).isoformat()}
                         for m in ("B3", "NYSE", "LSE", "AMS")},
            "pernas": self.pernas, "falhas": self.falhas,
            "qualidade": qa.resumo(self.series_info),
            "series": {"total": len(self.series), "frescas": sum(1 for i in self.series_info.values() if i.get("fresco")),
                       "velhas": [k for k, i in self.series_info.items() if i.get("esperado_hoje") and not i.get("fresco", True)],
                       "ausentes": [k for k, i in self.series_info.items() if i.get("ausente")]},
            "duracao_s": round(time.time() - self.inicio, 1),
            **extra,
        }
        gravar_json(os.path.join(self.saida, "saida", "manifest.json"), m)
        return m


def executar(modo: str, saida: str, ids_entregues: str = "", run_id: str = "", dias_backfill: int = 10,
             offline: str | None = None, agora: datetime | None = None, simbolos_extra: list[str] | None = None) -> dict:
    c = Coleta(saida, modo, agora=agora, offline=offline, run_id=run_id, dias_backfill=dias_backfill, simbolos_extra=simbolos_extra)
    repo = Repositorio(saida)
    ids = [i for i in (ids_entregues or "").replace("\n", ",").split(",") if i.strip()]
    n_ack = repo.marcar_entregues(ids) if ids else 0
    if modo == "ack":
        repo.salvar()
        return c.manifest({"ack": n_ack, "alertas": {"pendentes": len(repo.pendentes())}})
    if modo == "sonda":
        cob = yahoo.sonda(c.u.simbolos_yahoo() + c.simbolos_extra)
        gravar_json(os.path.join(saida, "sonda", "cobertura.json"), {**cob, "gerado_em": c.agora.strftime("%Y-%m-%dT%H:%M:%SZ")})
        ok = sum(1 for v in cob["simbolos"].values() if v.get("status") == "ok")
        c.pernas["sonda"] = f"{ok}/{len(cob['simbolos'])} ok"
        return c.manifest({"sonda": {"ok": ok, "total": len(cob["simbolos"]), "cliente": cob["cliente"]}})
    _log(f"modo {modo} · pregão {c.hoje} · ack {n_ack}")
    if modo != "eventos":
        c.coletar_series()
        _log(f"séries: {c.pernas.get('yahoo')}")
        c.coletar_curvas()
        _log(f"curvas: DI {c.pernas.get('di')} · TD {c.pernas.get('tesouro')} · UST {c.pernas.get('ust')}")
    if modo in MODOS_COM_EVENTOS:
        c.coletar_eventos()
        _log(f"eventos: notícias {c.pernas.get('noticias')} · CVM {c.pernas.get('cvm')} · SEC {c.pernas.get('sec')}")
    if modo == "backfill":
        # operacao de dados: nao avalia regra, nao registra alerta, nao renderiza
        return c.manifest({"backfill": {"dias": c.dias_backfill}})
    alertas, ctx = c.rodar_sinais(repo)
    novos = repo.registrar(alertas, modo)
    ids_novos = {a.id for a in novos}
    # texto que chegou depois (PDF lido numa nova tentativa): atualiza o alerta ja registrado, sem mudar status
    for a in alertas:
        e = repo.fila.get(a.id)
        if e and a.id not in ids_novos and (a.dados or {}).get("atualizado") and not (e.get("dados") or {}).get("texto_disponivel"):
            e.update({"titulo": a.titulo, "corpo": a.corpo, "como_falar": a.como_falar, "texto": a.texto(), "dados": a.dados})
            e["enriquecido_em"] = c.agora.strftime("%Y-%m-%dT%H:%M:%SZ")
    # reapresenta so o que ja saiu como mensagem (o que virou linha nao volta a disputar o teto)
    pendentes = [p for p in repo.pendentes() if p["id"] not in ids_novos and p.get("canal", "mensagem") == "mensagem"]
    for p in pendentes:
        p["reapresentado"] = p.get("reapresentado", 0) + 1
    # teto diario conta mensagens ja emitidas hoje (uma por grupo), nao alertas registrados
    ja = {"critico": 0, "atencao": 0}
    vistas = set()
    for a in repo.do_dia(c.hoje.isoformat()):
        if a["id"] in ids_novos or a.get("canal") != "mensagem":
            continue
        chave = a.get("mensagem") or a["id"]
        sev = a.get("mensagem_sev") or a.get("severidade")
        if chave not in vistas and sev in ja:
            vistas.add(chave)
            ja[sev] += 1
    resultado = politica.aplicar([a.para_json() for a in novos], pendentes, c.limiares, modo, SLOT_ROTULO.get(modo, modo), ja)
    for m in resultado["mensagens"]:
        chave = f"{c.hoje.isoformat()}:{modo}:{m['grupo']}"
        for i in m["ids"]:
            if i in repo.fila:
                e = repo.fila[i]
                e["canal"] = "mensagem"
                e.setdefault("mensagem", chave)
                e.setdefault("mensagem_sev", m["severidade"])
    for a in resultado["linhas_info"]:
        e = repo.fila.get(a["id"])
        if e and e.get("canal") != "mensagem":
            e["canal"] = "info"
            e["status"] = "linha"
    if modo in ("manha", "fechamento"):
        # alerta ja entregue que a serie corrigida desmente vira CORRECAO, uma vez so
        try:
            feitas = dict(repo.regras.get("correcoes_feitas") or {})
            c.correcoes = reconferir.reconferir(repo.fila, c.series, c.series_info, c.u, c.hoje, feitas)
            for x in c.correcoes:
                feitas[x["original"]] = c.hoje.isoformat()
            corte = (c.hoje - relogios.timedelta(days=30)).isoformat()
            repo.regras.set("correcoes_feitas", {k: v for k, v in feitas.items() if v >= corte})
        except Exception as e:
            c.falhas["reconferir"] = f"{type(e).__name__}: {str(e)[:80]}"
    repo.expirar()
    repo.podar()
    repo.salvar()
    if modo != "manha" or True:
        info = c.renderizar(ctx, resultado, repo)
    _log(f"alertas novos {len(novos)} · mensagens {len(resultado['mensagens'])} · info {len(resultado['linhas_info'])}")
    ids_msgs = [i for m in resultado["mensagens"] for i in m["ids"]]
    return c.manifest({"alertas": {"novos": len(novos), "mensagens": len(resultado["mensagens"]),
                                   "criticos": sum(1 for m in resultado["mensagens"] if m["severidade"] == "critico"),
                                   "ids": ids_msgs, "pendentes": len(repo.pendentes()), "suprimidos": len(resultado["suprimidos"])},
                       "render": info, "regime": ctx.regime, "ack": n_ack,
                       "correcoes": [x["id"] for x in c.correcoes],
                       "push": [m["push"] for m in resultado["mensagens"] if m.get("push")]})
