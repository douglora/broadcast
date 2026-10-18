"""
O robo le o Autopilot Terminal: tudo o que o terminal sabe de um papel, numa chamada.

Este pacote e o caminho terminal -> robo. O caminho inverso (robo -> tela) e `quant/ponte_terminal.py`; nao confundir.

API (os nomes sao combinados com os outros modulos do robo; nao mude)
    terminal.disponivel()                       -> bool
    terminal.ficha("PETR4")                     -> dict: TIR real e premio sobre a NTN-B, consenso e revisao, insiders, aluguel, noticias
                                                   (TIR: so a do metodo do Safra, tir_safra.json, recalculada pelo terminal antes de ler;
                                                   a antiga nao e lida desde 19/10/2026; regras em _tir.py)
                                                   pontuadas, proximo resultado, multiplos, valuation contra a propria historia, divida,
                                                   opcoes, fundos e pares. Cada pedaco tem `fonte`, `data` e `idade_dias`; dado mais velho que
                                                   o limite do seu tipo (`LIMITES_DIAS`) vira None, com o motivo em `ficha["motivos"]`.
    terminal.tabela(["PETR4", "VALE3"])         -> DataFrame, uma linha por ticker, colunas numericas estaveis (docstring de `tabela`)
    terminal.eventos(dias=10)                   -> lista de eventos (resultados, proventos, assembleias, vencimentos, agenda macro)
    terminal.historico("tir", "PETR4", desde)   -> DataFrame lido do banco historico (cache/banco/terminal.sqlite)
    terminal.tir_estado()                       -> a TIR do dia, conferida: ok, motivo da recusa, gerado, papeis sem TIR e por que

Onde fica o terminal: variavel de ambiente AUTOPILOT_TERMINAL (padrao ~/Desktop/terminal-artefato).

Regra que governa tudo aqui: NUNCA INVENTAR. O que falta e None com o motivo; o que passou do limite de idade tambem. Nenhuma funcao levanta
excecao por arquivo ausente ou em formato inesperado (o robo nao pode parar por causa da tela); `historico` levanta ValueError so para
nome de tabela errado, porque isso e erro de programacao.

CLI:  python -m quant.terminal ficha PETR4 | tabela | eventos | historico TABELA | status
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

import pandas as pd

from . import _eventos, _ficha, _historico, _leitor, _secoes, _tabela, _tir
from ._eventos import Eventos
from ._leitor import ENV_TERMINAL, LIMITES_DIAS, caminho_banco, raiz as caminho_terminal

__all__ = ["disponivel", "ficha", "tabela", "eventos", "historico", "cobertura", "estado", "tir_estado", "caminho_terminal", "caminho_banco",
           "limpar_cache", "LIMITES_DIAS", "ENV_TERMINAL", "COLUNAS_TABELA", "Eventos"]

COLUNAS_TABELA = _tabela.NOMES


def disponivel() -> bool:
    """True se o terminal existe no disco (AUTOPILOT_TERMINAL) e tem o cadastro de ativos para consultar."""
    return _ficha.disponivel()


def limpar_cache() -> None:
    """Zera o que o leitor guarda em memoria: os arquivos lidos e a conferencia da TIR (os testes chamam)."""
    _leitor.limpar_cache()
    _tir.limpar()


def tir_estado(*, agora: datetime | None = None) -> dict[str, Any]:
    """A TIR do dia, conferida como a ficha confere (roda o recalculo do terminal se a ultima conferencia do processo tem mais de 10 minutos):
    ok, motivo (por que foi recusada), gerado, ultimo_pregao, conferido_em, empresas (quantas o arquivo traz) e sem_tir ({papel: motivo}
    dos papeis que o arquivo conhece e que ficaram sem TIR)."""
    c = _secoes.Ctx(agora=agora)
    est = _tir.estado(c.agora)
    d = est.get("dados") or {}
    return {k: est.get(k) for k in ("ok", "motivo", "gerado", "ultimo_pregao", "conferido_em")} | {
        "empresas": len(d.get("empresas") or {}), "sem_tir": _tir.sem_tir(est, c.agora) if est["ok"] else {}}


def ficha(ticker: str, *, hoje: date | None = None, agora: datetime | None = None) -> dict[str, Any]:
    """Tudo o que o terminal sabe de `ticker`, com fonte, data e idade em cada pedaco.

    Chaves: ticker, nome, classe, setor, subsetor, indices, moeda, hoje, terminal, disponivel, e os pedacos
    tir, consenso, insiders, aluguel, noticias, proximo_resultado, multiplos, valuation, divida, opcoes, fundos, pares.
    Pedaco sem dado (ou velho demais) e None e a razao esta em `ficha["motivos"][pedaco]`; `ficha["avisos"]` junta os avisos
    dos pedacos (ex.: consenso de uma casa so); `ficha["cobertura"]` conta quantos dos pedacos tem dado.
    Percentual em pontos (7.4 = 7,4%), dinheiro em reais, datas ISO. `hoje` e `agora` servem para testar com outra data ou hora
    (so com `hoje`, a TIR e conferida como se fossem 9h daquele dia).
    """
    return _ficha.montar(ticker, _secoes.Ctx(hoje, agora))


def tabela(tickers: Iterable[str] | None = None, *, hoje: date | None = None, agora: datetime | None = None,
           classes: Iterable[str] = ("acao_br",)) -> pd.DataFrame:
    """DataFrame com uma linha por ticker (indice `ticker`) e as colunas abaixo. Sem `tickers`: todas as acoes do universo do terminal
    (`classes` muda isso). Tudo vem dos mesmos pedacos da `ficha`, com as mesmas regras de idade: dado velho demais ou inexistente e NaN.
    `terminal.cobertura(df)` conta quantos tickers tem cada coluna.

    @@COLUNAS@@
    """
    return _tabela.montar(tickers, _secoes.Ctx(hoje, agora), classes)


tabela.__doc__ = tabela.__doc__.replace("@@COLUNAS@@", _tabela.documentacao())


def cobertura(df: pd.DataFrame) -> pd.Series:
    """Para cada coluna numerica da tabela, quantos tickers tem o dado."""
    return _tabela.cobertura(df)


def eventos(dias: int = 10, *, hoje: date | None = None, tipos: Iterable[str] | None = None, pais: str | None = None,
            tickers: Iterable[str] | None = None) -> Eventos:
    """Eventos de hoje ate hoje + `dias`, do mais proximo para o mais distante.

    Cada evento: data, hora, dias_ate, tipo (resultado, teleconferencia, provento_ex, assembleia, vencimento_opcoes, macro), ticker, tickers,
    empresa, pais, titulo, periodo, confirmado, relevancia (1 a 3, so macro), expectativa/anterior/efetivo/unidade (so macro), indices,
    fonte, detalhe. Filtros: `tipos`, `pais` ("BR"/"US") e `tickers` (com `tickers` a agenda macro fica de fora). A lista devolvida tem `.avisos`
    com o que faltou (calendario ausente ou velho demais).
    """
    return _eventos.montar(dias, _secoes.Ctx(hoje), tipos=tipos, pais=pais, tickers=tickers)


def historico(tabela: str, ticker: str | None = None, desde: date | str | None = None) -> pd.DataFrame:
    """Linhas de `tabela` do banco historico do terminal (cache/banco/terminal.sqlite, gravado por `python -m coletor.banco --gravar`),
    da mais antiga para a mais nova. Tabelas: tir, tir_geral, consenso, aluguel, multiplos, valuation_mensal, opcoes_ativo, opcoes_venc,
    noticias_ativo, macro, macro_focus, curva, wirp, eventos, agenda_macro, robo_painel, robo_item. `ticker` filtra a coluna `ticker` (ou
    `ativo`); `desde` e uma data ISO. A coluna `origem` diz se a linha e 'retrato' (gravada no proprio dia) ou 'hist' (reconstruida de um
    historico que o terminal ja tinha) ou 'reconstruida' (so na `tir`). Banco ausente: DataFrame vazio com `.attrs['motivo']`. Tabela inexistente: ValueError.

    TABELA `tir`: so o modelo ANTIGO do terminal. O robo nao usa a TIR antiga em decisao nenhuma desde 19/10/2026 (a TIR do robo e a do
    metodo do Safra, que este banco nao guarda: o retrato diario dela fica em quant/saida/observacao/tir_diaria.jsonl).
    Nele o numero principal da TIR e o terminal endogeno. As colunas CANONICAS vem primeiro (`tir_principal_pct`, `tir_principal_norm_pct`,
    `tir_principal_prudente_pct`, `tir_principal_base`, `premio_principal_pp`) mais `conta`; `tir_hoje_pct`, `tir_normalizada_pct`, `tir_pl_pct`, `tir_perp_pct`,
    `tir_prudente_pct`, `tir_prudente_base`, `premio_pp` e `premio_hoje_pp` sao LEGADO (a menor entre P/L e perpetuidade). `conta` diz so com qual definicao o
    `tir_prudente_pct` (legado) da linha saiu ('endogena' ou 'menor_das_duas'); as colunas `tir_principal_*` sao sempre a conta endogena, em qualquer linha,
    e e nelas que a serie nao mistura definicoes. `.attrs` traz `canonicas`, `legado` e `nota`."""
    return _historico.ler(tabela, ticker, desde)


def estado() -> dict[str, Any]:
    """Diagnostico: o terminal esta no disco, que arquivos existem e de quando sao (para o CLI `status` e para quem investiga)."""
    from datetime import datetime
    arqs = ["universo.json", "pagina/tir_safra.json", "multiplos.json", "b3_aluguel.json", "noticias.json", "noticias_ativos.json",
            "pagina/eventos.json", "pagina/agenda.json", "pagina/proximos.json", "deriv/opcoes_resumo.json", "porativo/consenso/_pronto.json",
            "porativo/insidersbr/_pronto.json", "porativo/divida/_pronto.json", "porativo/valuation/_pronto.json", "macro.json", "rf.json"]
    out: dict[str, Any] = {}
    for a in arqs:
        p = _leitor.saida() / a
        out[a] = None if not p.is_file() else datetime.fromtimestamp(p.stat().st_mtime, _leitor.FUSO_BRT).isoformat(timespec="seconds")
    db = caminho_banco()
    return {"terminal": str(_leitor.raiz()), "disponivel": disponivel(), "hoje": _leitor.hoje().isoformat(), "arquivos": out,
            "banco": {"caminho": str(db), "existe": db.is_file(), "tabelas": _historico.tabelas_do_banco()}, "limites_dias": dict(LIMITES_DIAS)}
