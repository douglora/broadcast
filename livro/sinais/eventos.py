"""Regras de evento: E03 fato relevante/comunicado da CVM, E04 8-K/6-K da SEC,
E05 noticia material. Elas nao interpretam: transformam o que as fontes trouxeram
(ctx.eventos) em Alertas com o corpo pronto (veiculo, hora, resumo fiel do texto,
link) para a sessao narrar. O id e o do item da fonte, entao a fila deduplica."""

from __future__ import annotations

from datetime import datetime, timezone

from livro import relogios
from livro.sinais.base import Alerta, Contexto, Estado, Regra

MAX_MANCHETE = 150
MAX_RESUMO = 6
POR_QUE_CVM = {
    "Fato Relevante": "fato relevante e o que a propria companhia julga capaz de mover o preco; ler o documento inteiro antes de comentar",
    "Comunicado ao Mercado": "comunicado ao mercado costuma responder a noticia ou a oficio; confirma ou nega o que circula",
    "Aviso aos Acionistas": "aviso aos acionistas traz provento, data-com ou evento societario que muda o fluxo ao acionista",
}
POR_QUE_SEC = {
    "2.02": "resultado do trimestre reprecifica lucro, guidance e multiplo; comparar com o consenso",
    "1.01": "acordo material muda receita, alavancagem ou estrategia; olhar contraparte e valor",
    "2.01": "aquisicao ou venda concluida muda o mix e a alavancagem",
    "2.05": "reestruturacao antecipa custo e sinaliza demanda fraca",
    "2.06": "impairment reconhece que um ativo vale menos; olhar tamanho vs patrimonio",
    "4.02": "balanco anterior nao e mais confiavel: risco de governanca",
    "5.02": "troca de diretor ou conselheiro reabre a discussao de estrategia",
    "5.01": "mudanca de controle reprecifica a companhia inteira",
    "3.01": "aviso de deslistagem e risco de liquidez",
}


def _hora_brt(iso: str | None) -> str:
    if not iso:
        return "-"
    try:
        s = iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return relogios.fmt_brt(dt, com_data=True)
    except ValueError:
        return iso[:16]


def _nome_curto(ctx: Contexto, ativo: str, alternativa: str | None = None) -> str:
    a = ctx.ativo(ativo)
    nome = a.nome if a else (alternativa or ativo)
    import re
    nome = re.sub(r"\s+(ON|PN|PNA|PNB|UNT|UNIT)(\b.*)?$", "", nome)
    return _corta(nome, 40)


def _corta(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _resumo(linhas: list[str], rotulo: str) -> list[str]:
    if not linhas:
        return []
    return [f"{rotulo}:"] + [f"  – {_corta(l, 220)}" for l in linhas[:MAX_RESUMO]]


class E05Noticia(Regra):
    id = "E05"

    def avaliar(self, ctx: Contexto, estado: Estado) -> list[Alerta]:
        cfg = (ctx.eventos or {}).get("config") or {}
        por_que_cfg = cfg.get("por_que") or {}
        saida = []
        for it in (ctx.eventos or {}).get("noticias") or []:
            ativos = [a for a in it.get("ativos") or [] if a]
            if not ativos:
                continue
            principal = ativos[0]
            manchete = _corta(it.get("titulo", ""), MAX_MANCHETE)
            veic = it.get("veiculo") or "veículo"
            extras = it.get("fontes_extras") or []
            segunda = ("+ " + ", ".join(extras[:2])) if extras else "fonte única"
            lic = it.get("licenca", "manchete")
            corpo = [f"{veic} · {_hora_brt(it.get('publicado'))} · {segunda} · licença: {lic}"]
            if it.get("texto"):
                corpo += _resumo(it.get("resumo") or [], "Do texto")
            elif lic == "resumo" and it.get("trechos"):
                corpo += _resumo(it.get("trechos") or [], "Trechos (licença resumo: reescrever, não colar)")
            url = it.get("url") or it.get("url_google") or ""
            if url:
                corpo.append(f"Link: {url}")
            gat = it.get("gatilho") or "padrao"
            pq = por_que_cfg.get(gat) or por_que_cfg.get("padrao") or ""
            saida.append(Alerta(
                regra=self.id, ativo=principal, severidade=it.get("severidade", "info"), familia="noticia",
                titulo=f"{ctx.rotulo(principal)} · {manchete}", tag=it.get("hash", "x"),
                data=(it.get("publicado") or ctx.agora_iso or "")[:10], corpo=corpo, por_que=pq,
                ativos_afetados=" · ".join(ativos), como_falar=f"saiu no {veic}: {_corta(manchete, 90)}; confirmar o número no texto antes de repassar",
                fonte=f"{veic} {_hora_brt(it.get('publicado'))}",
                dados={"id_item": it.get("id"), "url": url, "url_google": it.get("url_google"), "licenca": lic,
                       "veiculo": veic, "texto_disponivel": bool(it.get("texto")), "gatilho": gat,
                       "manchete": manchete, "fontes_extras": extras, "ativos": ativos},
            ))
        return saida


class E03CVM(Regra):
    id = "E03"

    def avaliar(self, ctx: Contexto, estado: Estado) -> list[Alerta]:
        saida = []
        for d in (ctx.eventos or {}).get("cvm") or []:
            ativo = d.get("ativo")
            if not ativo:
                continue
            cat = d.get("categoria", "Documento")
            assunto = _corta(d.get("assunto") or d.get("tipo") or "", MAX_MANCHETE)
            corpo = [f"CVM IPE · entregue {d.get('entregue_em') or d.get('data')} · {d.get('tipo') or ''}"
                     + (f" / {d['especie']}" if d.get("especie") else "")]
            if d.get("texto"):
                from livro.fontes.noticias import resumo_fiel
                corpo += _resumo(resumo_fiel("", d["texto"], MAX_RESUMO), "Do documento")
            if d.get("link"):
                corpo.append(f"Link: {d['link']}")
            saida.append(Alerta(
                regra=self.id, ativo=ativo, severidade=d.get("severidade", "info"), familia="evento",
                titulo=f"{ctx.rotulo(ativo)} · {cat}: {assunto}", tag=str(d.get("protocolo") or "x"),
                data=d.get("data", ""), corpo=corpo, por_que=POR_QUE_CVM.get(cat, "documento da companhia na CVM"),
                como_falar=f"a {_nome_curto(ctx, ativo, d.get('empresa'))} publicou {cat.lower()} sobre {_corta(assunto, 70)}",
                fonte=f"CVM IPE {d.get('data', '')}", ativos_afetados=ativo,
                dados={"id_item": d.get("id"), "url": d.get("link"), "licenca": "integral", "veiculo": "CVM",
                       "texto_disponivel": bool(d.get("texto")), "categoria": cat, "manchete": f"{cat}: {assunto}", "ativos": [ativo],
                       "atualizado": bool(d.get("atualizado"))},
            ))
        return saida


class E04SEC(Regra):
    id = "E04"

    def avaliar(self, ctx: Contexto, estado: Estado) -> list[Alerta]:
        saida = []
        for f in (ctx.eventos or {}).get("sec") or []:
            ativo = f.get("ativo")
            if not ativo:
                continue
            form = f.get("form", "")
            rot = ", ".join(f.get("itens_rotulo") or []) or (f.get("descricao") or form)
            titulo = f"{ctx.rotulo(ativo)} · {form}: {_corta(rot, MAX_MANCHETE)}"
            corpo = [f"SEC EDGAR · aceito {_hora_brt(f.get('aceito_em'))} · {f.get('descricao') or form}"]
            if f.get("texto"):
                from livro.fontes.noticias import resumo_fiel
                corpo += _resumo(resumo_fiel("", f["texto"], MAX_RESUMO), "Do documento")
            if f.get("url"):
                corpo.append(f"Link: {f['url']}")
            pq = next((POR_QUE_SEC[i] for i in (f.get("itens") or []) if i in POR_QUE_SEC), "")
            if not pq:
                pq = {"6-K": "6-K e o relatorio de emissor estrangeiro: resultado, provento ou fato relevante do pais de origem",
                      "10-Q": "10-Q e o balanco trimestral completo", "10-K": "10-K e o balanco anual completo"}.get(form, "documento da companhia na SEC")
            saida.append(Alerta(
                regra=self.id, ativo=ativo, severidade=f.get("severidade", "info"), familia="evento",
                titulo=titulo, tag=str(f.get("acc_sem_traco", "x"))[-8:], data=f.get("data", ""), corpo=corpo, por_que=pq,
                como_falar=f"a {f.get('ticker') or ativo} protocolou {form} na SEC ({_corta(rot, 60)})",
                fonte=f"SEC EDGAR {f.get('data', '')}", ativos_afetados=ativo,
                dados={"id_item": f.get("id"), "url": f.get("url"), "licenca": "integral", "veiculo": "SEC",
                       "texto_disponivel": bool(f.get("texto")), "form": form, "itens": f.get("itens"),
                       "manchete": f"{form}: {rot}", "ativos": [ativo]},
            ))
        return saida


REGRAS = [E03CVM(), E04SEC(), E05Noticia()]
