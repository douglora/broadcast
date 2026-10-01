"""O que se busca de cada pregao do Boletim Diario do Mercado e o que fica gravado.

Gravado no branch `dados` (so texto e JSON; PDF nunca, o completo passa de 50 MB):

  boletim_b3/<AAAA-MM-DD>/status.json   cadernos: situacao, hora e link do PDF
  boletim_b3/<AAAA-MM-DD>/index.json    tabelas e arquivos: situacao, hora, linhas, falhas
  boletim_b3/tabelas/<Nome>.json        tabelas pequenas, inteiras, do ultimo pregao coletado
                                        (cada arquivo diz de que pregao e; uma linha por registro)

As tabelas grandes (negocios, cadastro, posicoes em aberto, aluguel, carteiras de indice)
sao lidas em memoria e so o recorte do livro vai para o resumo: boletim/resumo.py.
"""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from livro.http import Cliente, HttpError

from boletim import b3, renda_fixa

# (nome, paginas no maximo). Guardadas inteiras em tabelas/<Nome>.json.
INTEIRAS = (
    # renda variavel: indicadores
    ("SharesInvesVolum", 1), ("SharesInvesVolumMonthly", 1), ("EconomicIndicators", 2),
    ("HistoricalExchange", 1), ("INDEXES", 1),
    # renda variavel: resumo de acoes
    ("DailyAverageStocks", 1), ("StocksOperationSummary", 1), ("AverageChart", 1), ("IOPV", 1),
    ("ForwardMarket", 1), ("NegotiStrategi", 1),
    # renda variavel: maiores oscilacoes e mais negociadas
    ("IbovespaStockBiggestHighs", 1), ("IbovespaStockBiggestLow", 1), ("InCashMarketBiggestHighs", 1),
    ("InCashMarketBiggestLow", 1), ("InCash", 1), ("Forward", 1), ("OptionsPurshase", 1), ("OptionsSelling", 1),
    # derivativos
    ("DailyAverageDerivatives2", 1), ("DerivativesOperation2", 1), ("DerivativesMtM", 1), ("AnalyticalFramework2", 1),
    ("SwapFlex", 1), ("EletronicTerm", 1), ("OTCRegistrationWCCP", 1), ("OTCRegistrationCCP", 1),
    ("OTCInventoryWCCP", 1), ("OTCInventoryCCP", 1),
    # clearing, depositaria e COE
    ("ProventionCreditVariable", 1), ("Custody", 1), ("FugibleCustody", 1), ("DeadlineDepositSecurities", 1),
    ("COERegistration", 1), ("COEInventory", 1),
    # renda fixa
    ("DebenturesBusiness", 1), ("SaleOff", 1), ("Stock", 1), ("Register", 1), ("RepurchaseDealings", 1), ("DIover", 1),
)

# Lidas em memoria; so o recorte vai para o resumo. `Trade` e o negocio a negocio de renda fixa de
# balcao (debentures, CRI, CRA, com a taxa); `BTBTrade` e o aluguel negocio a negocio, com corretora.
SO_RESUMO = (("BTBLendingOpenPosition", 8), ("BTBLoanBalance", 12), ("PreviaQuadrimestral", 1), ("Previa", 1),
             ("Trade", 120), ("BTBTrade", 200))

# CSV da API de download: negocios do pregao e do after, cadastro (strike, vencimento,
# empresa, cotas) e posicoes em aberto (opcoes por serie, futuros por vencimento).
ARQUIVOS = ("TradeInformationConsolidated", "TradeInformationConsolidatedAfterHours",
            "InstrumentsConsolidated", "DerivativesOpenPosition")

# Fora da coleta, de proposito: negocio a negocio de bolsa (TickByTick*), renovacoes de aluguel,
# o cadastro inteiro e a negociacao consolidada de renda fixa de balcao (milhares de paginas; o
# cadastro e consultado papel a papel), cenarios de margem e as tabelas de cafe.


def gravar(caminho: str, conteudo, binario: bool = False) -> None:
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    if binario:
        with open(caminho, "wb") as f:
            f.write(conteudo)
        return
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(conteudo if isinstance(conteudo, str) else json.dumps(conteudo, ensure_ascii=False, indent=1))


def texto_tabela(tab: dict) -> str:
    """JSON com uma linha por registro: diff legivel no git e arquivo pequeno."""
    def bloco(t: dict, recuo: str) -> str:
        cab = {k: v for k, v in t.items() if k not in ("linhas", "filhos")}
        partes = [f"{recuo} {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in cab.items()]
        linhas = (",\n".join(f"{recuo}  {json.dumps(l, ensure_ascii=False)}" for l in t.get("linhas") or []))
        partes.append(f'{recuo} "linhas": [\n{linhas}\n{recuo} ]' if linhas else f'{recuo} "linhas": []')
        if t.get("filhos"):
            filhos = ",\n".join(bloco(f, recuo + "  ") for f in t["filhos"])
            partes.append(f'{recuo} "filhos": [\n{filhos}\n{recuo} ]')
        return recuo + "{\n" + ",\n".join(partes) + "\n" + recuo + "}"
    return bloco(tab, "") + "\n"


def texto_resumo(resumo: dict) -> str:
    """resumo.json com um bloco por linha: metade do tamanho do JSON recuado e diff por bloco."""
    partes = [f" {json.dumps(k)}: {json.dumps(v, ensure_ascii=False, separators=(',', ':'))}" for k, v in resumo.items()]
    return "{\n" + ",\n".join(partes) + "\n}\n"


def _linhas(tab: dict) -> int:
    return sum(len(t["linhas"]) for t in b3.folhas(tab))


def cadastros_rf(d: date, trade: dict, cache: dict, maximo: int = 2500, fios: int = 6, validade_dias: int = 10) -> dict:
    """Completa o cadastro (incentivada, indexador, vencimento) dos papeis negociados no dia.

    So consulta o que ainda nao esta no cache, do maior volume para o menor, ate `maximo` por
    rodada. Papel sem resposta fica marcado e e tentado de novo depois de `validade_dias`.
    """
    por = renda_fixa.agregar(b3.registros(trade))
    hoje = d.isoformat()

    def falta(cod: str) -> bool:
        c = cache.get(cod)
        if c is None:
            return True
        return bool(c.get("sem_cadastro")) and (d - date.fromisoformat(c["visto_em"])).days >= validade_dias

    fila = [c for c in sorted(por, key=lambda c: -por[c]["volume_rs"]) if falta(c)]
    local = threading.local()

    def busca(cod: str):
        if not hasattr(local, "cli"):
            local.cli = Cliente()
        try:
            return cod, b3.cadastro_balcao(local.cli, cod, d), None
        except (b3.B3Erro, HttpError) as e:
            return cod, None, str(e)[:80]

    achados = vazios = erros = 0
    if fila:
        with ThreadPoolExecutor(fios) as pool:
            for cod, cad, erro in pool.map(busca, fila[:maximo]):
                if erro:
                    erros += 1                       # falha de rede nao vira "sem cadastro": tenta na proxima rodada
                elif cad:
                    cache[cod] = dict(cad, visto_em=hoje)
                    achados += 1
                else:
                    cache[cod] = {"sem_cadastro": True, "tipo": por[cod]["tipo"], "visto_em": hoje}
                    vazios += 1
    return {"papeis_no_dia": len(por), "consultados": min(len(fila), maximo), "achados": achados,
            "sem_cadastro": vazios, "erros": erros, "ficaram_para_depois": max(0, len(fila) - maximo), "no_cache": len(cache)}


def texto_cadastro(cache: dict) -> str:
    """Um papel por linha: o arquivo cresce por acrescimo e o diff do git fica pequeno."""
    linhas = [f" {json.dumps(k)}: {json.dumps(cache[k], ensure_ascii=False, sort_keys=True)}" for k in sorted(cache)]
    return "{\n" + ",\n".join(linhas) + "\n}\n"


def coletar_pregao(cli: Cliente, d: date, pasta: str | None, pausa: float = 0.12, log=print,
                   rf_cadastro: dict | None = None, max_cadastros: int = 2500, pasta_tabelas: str | None = None) -> dict:
    """Busca tudo de um pregao. Devolve o bruto em memoria e grava status, index e tabelas.

    bruto = {pregao, status, tabelas{nome: tab}, arquivos{nome: [registros]}, informativos[],
             rf_cadastro{codigo: cadastro}, index{tabelas{}, arquivos{}, falhas{}}}
    `rf_cadastro` e o cache de cadastro de renda fixa; e completado aqui e devolvido no bruto.
    """
    bruto: dict = {"pregao": d.isoformat(), "status": None, "tabelas": {}, "arquivos": {}, "informativos": []}
    index: dict = {"pregao": d.isoformat(), "coletado_em": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "tabelas": {}, "arquivos": {}, "falhas": {}}

    try:
        bruto["status"] = b3.situacao_cadernos(cli, d)
    except (b3.B3Erro, HttpError) as e:
        index["falhas"]["status"] = str(e)[:160]

    for nome, paginas in INTEIRAS + SO_RESUMO:
        try:
            tab = b3.tabela(cli, nome, d, max_paginas=paginas)
        except (b3.B3Erro, HttpError) as e:
            index["falhas"][nome] = str(e)[:160]
            continue
        finally:
            time.sleep(pausa)
        n = _linhas(tab)
        index["tabelas"][nome] = {"titulo": tab["titulo"], "situacao": tab["situacao"], "atualizado_em": tab["atualizado_em"],
                                  "sla": tab["sla"], "linhas": n, "truncada": tab["truncada"]}
        bruto["tabelas"][nome] = tab
        # so com a tabela ja publicada: uma rodada cedo demais nao troca o dado bom de ontem por um vazio de hoje
        if pasta_tabelas and n and (nome, paginas) in INTEIRAS:
            gravar(os.path.join(pasta_tabelas, f"{nome}.json"), texto_tabela(dict({"pregao": d.isoformat()}, **tab)))

    for nome in ARQUIVOS:
        try:
            texto, meta = b3.arquivo(cli, nome, d)
            antes, regs = b3.ler_csv(texto)
        except (b3.B3Erro, HttpError) as e:
            index["falhas"][nome] = str(e)[:160]
            continue
        finally:
            time.sleep(pausa)
        datas = {r.get("RptDt") for r in regs[:200]}
        if datas - {d.isoformat()}:
            index["falhas"][nome] = f"arquivo de outra data: {sorted(datas)[:3]}"
            continue
        meta.update(linhas=len(regs), estado=" ".join(antes).replace("Status do Arquivo:", "").strip() or None)
        index["arquivos"][nome] = meta
        bruto["arquivos"][nome] = regs

    try:
        for cap in b3.capitulos(cli):
            for info in b3.informativos(cli, cap["id"], d):
                info["capitulo"] = cap["nome"]
                bruto["informativos"].append(info)
            time.sleep(pausa / 2)
    except (b3.B3Erro, HttpError) as e:
        index["falhas"]["informativos"] = str(e)[:160]

    bruto["rf_cadastro"] = rf_cadastro if rf_cadastro is not None else {}
    negocios_rf = bruto["tabelas"].get("Trade")
    if negocios_rf and negocios_rf["linhas"]:
        try:
            index["rf_cadastro"] = cadastros_rf(d, negocios_rf, bruto["rf_cadastro"], max_cadastros)
        except Exception as e:      # o cadastro e enriquecimento: sem ele a renda fixa sai sem classe, mas sai
            index["falhas"]["rf_cadastro"] = f"{type(e).__name__}: {e}"[:160]

    bruto["index"] = index
    if pasta:
        if bruto["status"]:
            gravar(os.path.join(pasta, "status.json"), bruto["status"])
        gravar(os.path.join(pasta, "index.json"), index)
    log(f"{d}: {len(index['tabelas'])} tabelas, {len(index['arquivos'])} arquivos, {len(index['falhas'])} falhas")
    return bruto
