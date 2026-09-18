"""Orquestra a coleta por modo (intradia | fechamento | manha | sonda | backfill |
ack), cada perna falhando sozinha, roda o motor de sinais, aplica a politica,
renderiza as saidas e grava livro/saida/manifest.json.

Layout no branch dados (raiz = dados_branch/livro):
  series/<SIMBOLO_SAFE>.json   curvas/{di,tesouro,ust}.json   macro/{bcb,focus,proxies,regime}.json
  estado/{regras_estado.json,alertas.json,historico_alertas.jsonl}
  saida/{manifest.json,fechamento.md,fechamento.json,alertas.md,intradia.md,manha.md,noticias.md,eventos.md}
  eventos/{noticias,cvm,sec}.json   noticias/vistos.json   noticias/corpo/<id>.json
  sonda/cobertura.json   universo.json"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from livro import fmt, politica, relogios, render
from livro import indicadores as ind
from livro import universo as uni
from livro.estado import Repositorio
from livro.fontes import b3_di, bcb, cvm, noticias, sec, sina, tesouro, ust, yahoo
from livro.sinais import curvas as r_curvas
from livro.sinais import eventos as r_ev
from livro.sinais import fx_commod as r_fx
from livro.sinais import sistema as r_sis
from livro.sinais import tecnicas as r_tec
from livro.sinais.base import Contexto
from livro.universo import gravar_json, ler_json

SLOT_ROTULO = {"intradia": "intradia", "fechamento": "Fechamento 18h40", "manha": "Manhã 07h20",
               "fimdesemana": "Domingo", "sonda": "sonda", "backfill": "backfill", "ack": "ack", "eventos": "eventos"}
MODOS_COM_EVENTOS = ("intradia", "fechamento", "manha", "eventos")


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
        self.series_info: dict = {}
        self.curvas: dict = {}
        self.macro: dict = {}
        self.eventos: dict = {}
        self.inicio = time.time()
        for sub in ("series", "curvas", "macro", "estado", "saida", "sonda", "eventos", "noticias/corpo"):
            os.makedirs(os.path.join(saida, sub), exist_ok=True)
        gravar_json(os.path.join(saida, "universo.json"), self.u.para_json())

    # ------------------------------------------------------------ series
    def _carregar_serie_local(self, simbolo: str) -> dict | None:
        return ler_json(os.path.join(self.saida, "series", f"{uni.nome_seguro(simbolo)}.json"))

    def coletar_series(self) -> None:
        simbolos = self.u.simbolos_yahoo() + self.simbolos_extra
        if self.offline:
            self._series_offline(simbolos)
            return
        rng = "5d" if self.modo == "intradia" else "2y"
        novas, falhas = yahoo.coletar(simbolos, rng)
        ok = 0
        for s in simbolos:
            antiga = self._carregar_serie_local(s)
            nova = novas.get(s)
            if nova and rng == "5d" and antiga and antiga.get("barras"):
                # intradia: mescla as barras novas no historico de 2 anos
                por_data = {b[0]: b for b in antiga["barras"]}
                for b in nova["barras"]:
                    por_data[b[0]] = b
                nova = {**antiga, "meta": nova["meta"], "coletado_em": nova["coletado_em"],
                        "barras": [por_data[k] for k in sorted(por_data)]}
            final = yahoo.mesclar(antiga, nova)
            if final:
                gravar_json(os.path.join(self.saida, "series", f"{uni.nome_seguro(s)}.json"), final)
                if nova:
                    ok += 1
        self.pernas["yahoo"] = f"ok {ok}/{len(simbolos)}" + (f"; falhas: {', '.join(f'{k} {v}' for k, v in list(falhas.items())[:6])}" if falhas else "")
        if falhas:
            self.falhas["yahoo"] = f"{len(falhas)} símbolos falharam ({', '.join(list(falhas.values())[:3])})"
        self._montar_dataframes(simbolos, falhas)

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

    def _montar_dataframes(self, simbolos: list[str], falhas: dict) -> None:
        for s in simbolos:
            obj = self.u.por_yahoo(s)
            if obj is None:
                continue
            d = self._carregar_serie_local(s)
            if not d or not d.get("barras"):
                self.series_info[obj.id] = {"ausente": True, "esperado_hoje": True}
                continue
            df = ind.para_df(d["barras"])
            if len(df) == 0:
                self.series_info[obj.id] = {"ausente": True, "esperado_hoje": True}
                continue
            self.series[obj.id] = df
            mercado = obj.mercado if obj.mercado in self.calendario["mercados"] else "NYSE"
            esperado = relogios.data_referencia(mercado, self.agora)
            ultima = df.index[-1].date()
            self.series_info[obj.id] = {
                "ultima": ultima.isoformat(), "esperado": esperado.isoformat(),
                "esperado_hoje": esperado == self.agora.astimezone(relogios.BRT).date(),
                "fresco": ultima >= esperado, "reaproveitada": bool(d.get("reaproveitada")),
                "falha": falhas.get(s), "barras": int(len(df)), "moeda": d.get("moeda"),
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
            if di.get("ultimo_pregao") != self.hoje.isoformat():
                self.falhas["di"] = f"ajuste B3 de {self.hoje.isoformat()} não publicado (último {di.get('ultimo_pregao')})"
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
                gravar_json(caminho_tes, tes)
                self.curvas["tesouro"] = tes
                self.pernas["tesouro"] = f"ok base {tes.get('data_base')}"
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
            gravar_json(os.path.join(self.saida, "macro", "bcb.json"), b)
            self.macro["bcb"] = b
            self.pernas["bcb"] = f"ok {len(b.get('series', {}))} séries"
        except Exception as e:
            self.macro["bcb"] = ler_json(os.path.join(self.saida, "macro", "bcb.json"), {}) or {}
            self.pernas["bcb"] = f"falha: {e}"
        if self.modo in ("manha", "fechamento", "backfill"):
            try:
                f = bcb.coletar_focus()
                gravar_json(os.path.join(self.saida, "macro", "focus.json"), f)
                self.macro["focus"] = f
                self.pernas["focus"] = f"ok {list((f.get('expectativas') or {}).keys())}"
            except Exception as e:
                self.macro["focus"] = ler_json(os.path.join(self.saida, "macro", "focus.json"), {}) or {}
                self.pernas["focus"] = f"falha: {e}"
            try:
                p = sina.coletar()
                antigo_p = ler_json(os.path.join(self.saida, "macro", "proxies.json"), {}) or {}
                p["bhkp_semanal"] = antigo_p.get("bhkp_semanal")
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
        self.eventos = {"config": cfg, "noticias": [], "cvm": [], "sec": []}
        if self.offline:
            for perna in ("noticias", "cvm", "sec"):
                d = ler_json(os.path.join(self.offline, "eventos", f"{perna}.json"), {}) or {}
                self.eventos[perna] = d.get("itens") or d.get("docs") or d.get("filings") or []
                self.pernas[perna] = f"offline {len(self.eventos[perna])}"
            return
        caminho_vistos = os.path.join(self.saida, "noticias", "vistos.json")
        vistos = ler_json(caminho_vistos, {}) or {}
        hoje_brt = relogios.brt(self.agora).date()
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
                self.pernas["cvm"] = f"ok {len(c['docs'])} novos de {c['todos']} ({len(c['empresas_casadas'])} cias casadas)" + \
                    (f"; falhas {list(c['falhas'])}" if c["falhas"] else "")
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
                            max_docs=int(s_cfg.get("max_docs_por_run", 6)))
            if not s.get("disponivel"):
                self.pernas["sec"] = f"indisponível ({s.get('motivo')})"
            else:
                self.eventos["sec"] = s["filings"]
                vistos["sec"] = s["vistos"]
                gravar_json(os.path.join(self.saida, "eventos", "sec.json"), {k: v for k, v in s.items() if k != "vistos"})
                self.pernas["sec"] = f"ok {len(s['filings'])} novos" + (f"; falhas {list(s['falhas'])}" if s["falhas"] else "")
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
        ctx = Contexto(universo=self.u, limiares=self.limiares, hoje=self.hoje, slot=self.modo,
                       series=self.series, series_info=self.series_info, curvas=self.curvas,
                       macro=self.macro, falhas=self.falhas, agora_iso=self.agora.strftime("%Y-%m-%dT%H:%M:%SZ"),
                       eventos=self.eventos)
        ordem = [r_curvas.C01DIMovimento(), r_curvas.C04TesouroJuroReal(), r_curvas.C05TesouroVariacaoPU(), r_curvas.C07UST(),
                 r_tec.T13Regime(), r_tec.T01MM200(), r_tec.T03GoldenDeath(), r_tec.T04MaxMin(), r_tec.T05Zscore(),
                 r_tec.T08Drawdown(), r_fx.F01USDBRL(), r_fx.F03Brent(), r_fx.F06Cripto()] + r_ev.REGRAS + [r_sis.S01FalhaDados()]
        if self.modo == "intradia":
            # intradia: so o que e seguro sem fechamento consolidado
            ordem = [r_tec.T13Regime(), r_fx.F01USDBRL(), r_fx.F03Brent(), r_fx.F06Cripto()] + r_ev.REGRAS + [r_sis.S01FalhaDados()]
        elif self.modo == "eventos":
            ordem = list(r_ev.REGRAS)
        alertas = []
        for regra in ordem:
            try:
                alertas += regra.avaliar(ctx, repo.regras)
            except Exception as e:
                _log(f"regra {regra.id} falhou: {type(e).__name__}: {e}")
                self.falhas[f"regra_{regra.id}"] = f"{type(e).__name__}: {str(e)[:80]}"
        if self.modo == "intradia":
            # no intradia, movimentos sao 'parciais': so critico passa como alerta proprio
            for a in alertas:
                if a.familia in ("cambio", "commodity", "cripto") and a.severidade != "critico":
                    a.severidade = "info"
                if a.familia in ("cambio", "commodity", "cripto"):
                    a.titulo = a.titulo + " (parcial, intradia)"
        return alertas, ctx

    # ------------------------------------------------------------ render
    def renderizar(self, ctx: Contexto, resultado: dict, repo: Repositorio) -> dict:
        saida = os.path.join(self.saida, "saida")
        janelas = {}
        for a in self.u.ativos:
            if a.id in self.series:
                janelas[a.id] = ind.janelas(self.series[a.id])
        do_dia = repo.do_dia(self.hoje.isoformat())
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
            return out
        curvas_l, lacunas_c, ins = render.curvas_linhas(self.curvas, self.u, self.macro, ctx.regime, self.hoje)
        b_txt, lacunas_b = render.bloco_b(self.u, janelas, self.series_info, "completo")
        b_cel, _ = render.bloco_b(self.u, janelas, self.series_info, "celular")
        lacunas = lacunas_c + lacunas_b + [f"{k}: {v}" for k, v in self.falhas.items() if not k.startswith("regra_")]
        mov = render.movers(janelas, self.u)
        relogios_txt = self._relogios_txt()
        fontes = ["Yahoo Finance", "B3 Boletim Diário", "Tesouro Transparente", "Treasury.gov CMT", "BCB"]
        parcial = any(not (self.series_info.get(a.id) or {}).get("fresco", True) for a in self.u.por_bloco("eua"))
        a_txt = render.bloco_a(self.hoje, relogios_txt, do_dia, [], mov, curvas_l, render.agenda(self.calendario, self.hoje),
                               lacunas, fontes, parcial=parcial, slot=self.modo, hora=relogios.fmt_brt(self.agora))
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
        md = render.fechamento_md(a_txt, b_txt, legenda, notas)
        nome = "manha.md" if self.modo == "manha" else "fechamento.md"
        with open(os.path.join(saida, nome), "w", encoding="utf-8") as f:
            f.write(md)
        if self.modo != "manha":
            with open(os.path.join(saida, "fechamento_celular.md"), "w", encoding="utf-8") as f:
                f.write("```\n" + b_cel + "\n```\n" + legenda + "\n")
        gravar_json(os.path.join(saida, "fechamento.json"), {
            "data": self.hoje.isoformat(), "slot": self.modo, "gerado_em": self.agora.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "janelas": janelas, "series_info": self.series_info, "movers": mov, "leitura_insumos": ins,
            "alertas_do_dia": do_dia, "lacunas": lacunas, "relogios": relogios_txt,
            "push_sugerido": self._push_fechamento(do_dia, mov, ins),
        })
        out.update({"lacunas": len(lacunas), "tamanho_a": len(a_txt), "tamanho_b": len(b_txt)})
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
        cab = f"Fechamento {fmt.data_br(self.hoje.isoformat())}:"
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
        fim = f"{len(do_dia)} alertas. Leitura na sessão."

        def montar(ps: list[str]) -> str:
            return (cab + " " + "; ".join(ps) + ". " + fim) if ps else (cab + " " + fim)

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
                       "push": [m["push"] for m in resultado["mensagens"] if m.get("push")]})
