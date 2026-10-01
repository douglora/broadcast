#!/usr/bin/env python3
"""Coletor do Boletim Diario do Mercado da B3 (BDI).

Roda no GitHub Actions (internet aberta; a sessao do Claude na nuvem nao alcanca a B3) e
grava em boletim_b3/ no branch dados:

  boletim_b3/manifest.json                     ultima rodada: pregoes, situacao, falhas
  boletim_b3/historico.json                    serie compacta dos ultimos pregoes do livro (medias e variacoes)
  boletim_b3/mercado.json                      fechamento, volume e saldo alugado do IBrA nos ultimos pregoes (radar)
  boletim_b3/rf_cadastro.json                  cadastro dos papeis de renda fixa ja vistos (incentivada, indexador, vencimento)
  boletim_b3/rf_estado.json                    ultimas taxas negociadas por papel (abertura e fechamento de taxa)
  boletim_b3/catalogo.json                     tabelas que o BDI expoe hoje (acusa tabela nova ou removida)
  boletim_b3/painel.html                       o ultimo pregao em pagina; e o que a sessao publica como Artifact
  boletim_b3/tabelas/<Nome>.json               tabelas pequenas do ultimo pregao, inteiras
  boletim_b3/<AAAA-MM-DD>/resumo.json          numeros com fonte e data, cruzados com o livro, e os sinais
  boletim_b3/<AAAA-MM-DD>/resumo.md            a mesma leitura em texto, pronta para a sessao
  boletim_b3/<AAAA-MM-DD>/status.json          cadernos em PDF: situacao, hora e link (o PDF nao e gravado)
  boletim_b3/<AAAA-MM-DD>/index.json           tabelas e arquivos: situacao, hora, linhas, falhas

Por pregao fica so o resumo (cerca de 230 KB); painel e tabelas sao um arquivo so, sempre do
ultimo pregao, para o branch nao crescer 1 MB por dia.

Duas rodadas por pregao, as duas idempotentes: a da noite pega negocios, fluxo e indices; a da
manha seguinte completa com aluguel, posicoes em aberto e derivativos, que a B3 publica de
madrugada. Rotas e formatos: boletim/b3.py. Leitura na sessao: `python3 mesa.py boletim`.

Uso: python boletim_b3.py --saida dados_branch/boletim_b3 [--data AAAA-MM-DD] [--dias 1]
                          [--series dados_branch/livro/series] [--pdf pasta]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta

from livro import relogios, universo
from livro.http import Cliente, HttpError

from boletim import b3, coleta, mercado, painel, render, renda_fixa, resumo


def pregoes(fim: date, n: int) -> list[date]:
    """n pregoes B3 terminando em `fim` (ou no dia util anterior), do mais velho ao mais novo."""
    out, d = [], relogios.ultimo_dia_util("B3", fim)
    while len(out) < n:
        out.append(d)
        d = relogios.dia_util_anterior("B3", d)
    return out[::-1]


def pregao_padrao(agora=None) -> date:
    """Pregao que a B3 ja fechou: hoje a partir das 18h30 de Brasilia, senao o dia util anterior.
    A rodada da manha seguinte cai no pregao de ontem, que e o que ela vem completar."""
    local = (agora or relogios.agora_utc()).astimezone(relogios.BRT)
    hoje = local.date()
    if relogios.eh_dia_util("B3", hoje) and (local.hour, local.minute) >= (18, 30):
        return hoje
    return relogios.ultimo_dia_util("B3", hoje - timedelta(days=1))


def livro_b3() -> list[dict]:
    """Ativos do livro negociados na B3 (config/livro.yaml)."""
    return [{"id": a.id, "nome": a.nome, "classe": a.classe} for a in universo.carregar().ativos
            if a.mercado == "B3" and a.ativo]


def ler_json(caminho: str, padrao):
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return padrao


def baixar_pdfs(cli: Cliente, status: dict, pasta: str) -> list[str]:
    """Cadernos em PDF para o artefato da rodada (nunca para o branch dados)."""
    baixados = []
    for c in [status.get("completo") or {}] + (status.get("cadernos") or []):
        if not c.get("pdf"):
            continue
        try:
            r = cli.get(c["pdf"], headers={"Accept": "application/pdf,*/*"}, timeout=300)
        except HttpError:
            continue
        if r.status == 200 and r.content.startswith(b"%PDF"):
            coleta.gravar(os.path.join(pasta, c["arquivo"]), r.content, binario=True)
            baixados.append(c["arquivo"])
    return baixados


def refazer_paineis(saida: str, fim: date | None, n: int) -> int:
    """Refaz resumo.md dos ultimos `n` pregoes guardados e o painel.html do ultimo deles (ou de `fim`).
    Nao vai a B3."""
    hist = ler_json(os.path.join(saida, "historico.json"), {})
    dias = sorted(d for d in os.listdir(saida) if len(d) == 10 and os.path.exists(os.path.join(saida, d, "resumo.json"))
                  and (fim is None or d <= fim.isoformat()))
    for i, d in enumerate(dias):
        if d not in dias[-n:]:
            continue
        res = ler_json(os.path.join(saida, d, "resumo.json"), None)
        anterior = ler_json(os.path.join(saida, dias[i - 1], "resumo.json"), None) if i else None
        coleta.gravar(os.path.join(saida, d, "resumo.md"), render.markdown(res))
        if d == dias[-1]:
            coleta.gravar(os.path.join(saida, "painel.html"), painel.pagina(res, hist, anterior))
        print(f"{d}: resumo.md refeito" + (" e painel.html" if d == dias[-1] else ""))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--saida", default="boletim_b3")
    ap.add_argument("--data", default="", help="AAAA-MM-DD (vazio = ultimo pregao fechado)")
    ap.add_argument("--dias", default="1",
                    help="quantos pregoes, terminando na data (ate 21: e o que a B3 guarda); `auto` = 2, ou 21 enquanto o "
                         "historico tiver menos de 15 pregoes da versao atual")
    ap.add_argument("--series", default="", help="pasta livro/series do branch dados, para a paridade com a referencia la fora")
    ap.add_argument("--pdf", default="", help="pasta para baixar os cadernos em PDF do ultimo pregao (artefato; fora do git)")
    ap.add_argument("--so-painel", action="store_true",
                    help="sem rede: refaz resumo.md dos ultimos --dias pregoes guardados e o painel.html do ultimo (ou de --data)")
    a = ap.parse_args(argv)
    if a.so_painel:
        return refazer_paineis(a.saida, date.fromisoformat(a.data) if a.data else None,
                               max(1, int(a.dias) if a.dias.isdigit() else 1))

    cli = Cliente()
    cfg = universo.carregar_yaml("boletim.yaml")
    livro = livro_b3()
    fim = date.fromisoformat(a.data) if a.data else pregao_padrao()
    hist = ler_json(os.path.join(a.saida, "historico.json"), {})
    merc = ler_json(os.path.join(a.saida, "mercado.json"), {})
    rf_cadastro = ler_json(os.path.join(a.saida, "rf_cadastro.json"), {})
    rf_estado = ler_json(os.path.join(a.saida, "rf_estado.json"), {})
    cfg_rf = cfg.get("renda_fixa") or {}
    if hist and hist.get("versao") != resumo.VERSAO:
        # historico gravado por uma versao anterior do coletor: os numeros nao sao comparaveis
        manifest_nota = f"historico da versao {hist.get('versao')} descartado; refeito na versao {resumo.VERSAO}"
        hist, merc, rf_estado = {}, {}, {}
    else:
        manifest_nota = ""
    n_dias = (2 if len(hist.get("pregoes") or {}) >= 15 else 21) if a.dias == "auto" else int(a.dias)
    manifest: dict = {"gerado_em": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "cliente_http": cli.tipo,
                      "livro": [x["id"] for x in livro], "pregoes": {}, "falhas": [], "versao": resumo.VERSAO}
    if manifest_nota:
        manifest["nota"] = manifest_nota

    try:
        cat = b3.catalogo(cli)
        antigo = {x["tabela"] for x in ler_json(os.path.join(a.saida, "catalogo.json"), [])}
        agora = {x["tabela"] for x in cat}
        if antigo and antigo != agora:
            manifest["catalogo_mudou"] = {"novas": sorted(agora - antigo), "removidas": sorted(antigo - agora)}
        coleta.gravar(os.path.join(a.saida, "catalogo.json"), cat)
    except (b3.B3Erro, HttpError) as e:
        manifest["falhas"].append(f"catalogo: {e}")

    ultimo = None
    dias = pregoes(fim, max(1, min(n_dias, 21)))
    # posicoes em aberto do pregao anterior ao primeiro: base das maiores mudancas de posicao do dia
    pos_ant, data_ant = None, relogios.dia_util_anterior("B3", dias[0])
    try:
        pos_ant = b3.ler_csv(b3.arquivo(cli, "DerivativesOpenPosition", data_ant)[0])[1]
    except (b3.B3Erro, HttpError) as e:
        manifest["falhas"].append(f"posicoes em aberto de {data_ant}: {e}")
    for d in dias:
        pasta = os.path.join(a.saida, d.isoformat())
        t0 = time.time()
        try:
            bruto = coleta.coletar_pregao(cli, d, pasta, rf_cadastro=rf_cadastro,
                                          max_cadastros=cfg_rf.get("cadastros_por_rodada", 2500),
                                          pasta_tabelas=os.path.join(a.saida, "tabelas") if d == dias[-1] else None)
            # o cadastro custa centenas de consultas: grava logo, antes de qualquer coisa poder quebrar
            coleta.gravar(os.path.join(a.saida, "rf_cadastro.json"), coleta.texto_cadastro(rf_cadastro))
            bruto["pos_anterior"], bruto["pos_anterior_data"] = pos_ant, data_ant.isoformat()
            res = resumo.montar(bruto, cfg, livro, hist, a.series or None, merc, rf_estado)
        except Exception as e:      # um pregao que quebra nao derruba os outros
            manifest["falhas"].append(f"{d}: {type(e).__name__}: {e}")
            continue
        if bruto["arquivos"].get("DerivativesOpenPosition"):
            pos_ant, data_ant = bruto["arquivos"]["DerivativesOpenPosition"], d
        sem_dado = not bruto["arquivos"] and not any(t["linhas"] for t in bruto["index"]["tabelas"].values())
        if sem_dado:
            manifest["falhas"].append(f"{d}: a B3 nao devolveu nada (feriado, pregao futuro ou fora da janela de 21 dias)")
            continue
        apoio = res.pop("_apoio")
        hist = resumo.atualizar_historico(hist, res, cfg.get("historico_pregoes", 70))
        merc = mercado.atualizar(merc, d.isoformat(), apoio["mercado_hoje"], apoio["teorica"], cfg.get("mercado_pregoes", 26))
        rf_estado = renda_fixa.atualizar_estado(rf_estado, {"_linhas": apoio["rf_linhas"]}, d.isoformat(),
                                                cfg_rf.get("estado_volume_minimo_rs", 1000000))
        coleta.gravar(os.path.join(pasta, "resumo.json"), coleta.texto_resumo(res))
        coleta.gravar(os.path.join(pasta, "resumo.md"), render.markdown(res))
        anterior = ler_json(os.path.join(a.saida, relogios.dia_util_anterior("B3", d).isoformat(), "resumo.json"), None)
        coleta.gravar(os.path.join(a.saida, "painel.html"), painel.pagina(res, hist, anterior))
        manifest["pregoes"][d.isoformat()] = {
            "completo": res["situacao"]["completo"], "faltam": res["situacao"]["faltam"],
            "boletim": res["situacao"]["boletim"], "sinais": len(res["sinais"]),
            "tabelas": len(bruto["index"]["tabelas"]), "arquivos": sorted(bruto["index"]["arquivos"]),
            "rf_cadastro": bruto["index"].get("rf_cadastro"),
            "falhas": bruto["index"]["falhas"], "segundos": round(time.time() - t0)}
        ultimo = (d, bruto)
        # grava a cada pregao: rodada longa interrompida nao perde o que ja veio
        compacto = {"ensure_ascii": False, "separators": (",", ":")}
        coleta.gravar(os.path.join(a.saida, "historico.json"), json.dumps(hist, **compacto))
        coleta.gravar(os.path.join(a.saida, "mercado.json"), json.dumps(merc, **compacto))
        coleta.gravar(os.path.join(a.saida, "rf_estado.json"), json.dumps(rf_estado, **compacto))

    if ultimo:
        manifest["ultimo_pregao"] = ultimo[0].isoformat()
        if a.pdf and ultimo[1].get("status"):
            manifest["pdf_no_artefato"] = baixar_pdfs(cli, ultimo[1]["status"], a.pdf)
    coleta.gravar(os.path.join(a.saida, "manifest.json"), manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=1)[:6000])
    return 0 if manifest["pregoes"] else 1


if __name__ == "__main__":
    sys.exit(main())
