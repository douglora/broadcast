"""A tabela: uma linha por ticker, colunas numericas estaveis, montada com os MESMOS pedacos da ficha (uma so regra por numero)."""
from __future__ import annotations

from typing import Any, Callable, Iterable

import pandas as pd

from . import _ficha as F
from . import _leitor as L
from . import _secoes as S


def _g(f: dict | None, *ks: str) -> Any:
    for k in ks:
        if not isinstance(f, dict):
            return None
        f = f.get(k)
    return f


def _bin(v: Any) -> float | None:
    return None if v is None else float(bool(v))


def _ex(f: dict) -> float | None:
    """Dias ate a proxima data ex de provento."""
    for e in _g(f, "proximo_resultado", "outros_eventos") or []:
        if e.get("tipo") == "provento_ex":
            return float(e["dias_ate"])
    return None


# (nome, descricao, funcao(ficha) -> valor)
COLUNAS: list[tuple[str, str, Callable[[dict], Any]]] = [
    # identidade (texto)
    ("nome", "texto: nome do papel no terminal", lambda f: f.get("nome")),
    ("classe", "texto: classe do ativo (acao_br, bdr...)", lambda f: f.get("classe")),
    ("setor", "texto: setor do terminal", lambda f: f.get("setor")),
    ("subsetor", "texto: subsetor do terminal", lambda f: f.get("subsetor")),
    # preco e liquidez (multiplos.json, pregao)
    ("preco", "R$: fechamento B3 usado nos multiplos", lambda f: _g(f, "multiplos", "preco")),
    ("mcap_rs", "R$: valor de mercado", lambda f: _g(f, "multiplos", "mcap_rs")),
    ("liq_21d_rs", "R$: volume financeiro medio diario de 21 pregoes", lambda f: _g(f, "multiplos", "liq_media_21d_rs")),
    # TIR real implicita (modulo tir)
    ("tir_pct", "% a.a. real: TIR de hoje (terminal endogeno: o lucro do ano 11 capitalizado a propria taxa)", lambda f: _g(f, "tir", "tir_hoje_pct")),
    ("tir_prudente_pct", "% a.a. real: TIR prudente (a da tela; normalizada quando o lucro esta em pico)", lambda f: _g(f, "tir", "tir_prudente", "pct")),
    ("tir_premio_pp", "pp: TIR prudente menos a taxa da NTN-B de ~10 anos", lambda f: _g(f, "tir", "tir_prudente", "premio_pp")),
    ("tir_premio_hoje_pp", "pp: TIR de hoje menos a NTN-B", lambda f: _g(f, "tir", "premio_hoje_pp")),
    ("ciclo_lucro", "codigo: -1 fundo de lucro, 0 normal, 1 pico possivel, 2 pico provavel (vazio = sem dado)", lambda f: _g(f, "tir", "ciclo_do_lucro", "codigo")),
    ("ciclo_razao", "x: lucro de 12 meses sobre a media real de 5 anos", lambda f: _g(f, "tir", "ciclo_do_lucro", "razao_lucro_12m_sobre_media_5a")),
    ("tir_caixa_g0_pct", "% a.a. real: segunda leitura da TIR (caixa normalizado, sem crescimento)", lambda f: _g(f, "tir", "caixa", "tir_g0_pct")),
    ("tir_caixa_diverge", "0/1: as duas leituras da TIR divergem 10 pp ou mais", lambda f: _bin(_g(f, "tir", "caixa", "diverge"))),
    ("tir_casas", "n: analistas por tras do lucro esperado da TIR (1 = nao e consenso)", lambda f: _g(f, "tir", "base", "casas")),
    # consenso (agregador)
    ("consenso_upside_pct", "%: preco-alvo medio sobre o preco na coleta, menos 1", lambda f: _g(f, "consenso", "alvo", "potencial_pct")),
    ("consenso_alvo_n", "n: analistas no preco-alvo", lambda f: _g(f, "consenso", "alvo", "analistas")),
    ("consenso_nota", "1 (compra forte) a 5 (venda forte): nota media das recomendacoes", lambda f: _g(f, "consenso", "recomendacao", "nota_1_compra_forte_a_5_venda")),
    ("consenso_pct_compra", "%: analistas com compra ou compra forte", lambda f: _g(f, "consenso", "recomendacao", "pct_compra")),
    ("consenso_lpa_rev_30d_pct", "%: revisao do lucro por acao do ano corrente em 30 dias", lambda f: _g(f, "consenso", "lpa_ano_corrente", "revisao_30d_pct")),
    ("consenso_lpa_rev_90d_pct", "%: revisao do lucro por acao do ano corrente em 90 dias", lambda f: _g(f, "consenso", "lpa_ano_corrente", "revisao_90d_pct")),
    ("consenso_lpa_subiram_30d", "n: analistas que subiram a estimativa do ano corrente em 30 dias", lambda f: _g(f, "consenso", "lpa_ano_corrente", "subiram_30d")),
    ("consenso_lpa_cortaram_30d", "n: analistas que cortaram a estimativa do ano corrente em 30 dias", lambda f: _g(f, "consenso", "lpa_ano_corrente", "cortaram_30d")),
    ("consenso_pl_proj", "x: preco sobre o lucro por acao estimado do ano corrente", lambda f: _g(f, "consenso", "lpa_ano_corrente", "pl_projetado")),
    # insiders (CVM)
    ("insiders_saldo_90d_rs", "R$: compras menos vendas de insiders (controlador, conselho, diretoria...) em 90 dias", lambda f: _g(f, "insiders", "saldo_90d_rs")),
    ("insiders_saldo_gestao_90d_rs", "R$: o mesmo so de administradores (sem controlador nem a companhia)", lambda f: _g(f, "insiders", "saldo_gestao_90d_rs")),
    ("insiders_negocios_90d", "n: negocios de insiders na janela", lambda f: _g(f, "insiders", "negocios_90d")),
    ("insiders_idade_dias", "dias: desde o fim do mes do ultimo formulario entregue", lambda f: _g(f, "insiders", "idade_dias")),
    # aluguel (B3)
    ("aluguel_taxa_aa", "% a.a.: taxa media do aluguel de acoes (tomador)", lambda f: _g(f, "aluguel", "taxa_aa_pct")),
    ("aluguel_pct_float", "%: saldo alugado sobre a quantidade teorica do indice", lambda f: _g(f, "aluguel", "pct_float")),
    ("aluguel_var_20d_pct", "%: variacao do saldo alugado em 20 pregoes", lambda f: _g(f, "aluguel", "var_20d_pct")),
    ("aluguel_dias_para_cobrir", "dias de negociacao a vista para zerar o saldo alugado", lambda f: _g(f, "aluguel", "dias_para_cobrir")),
    ("aluguel_saldo_rs", "R$: saldo alugado", lambda f: _g(f, "aluguel", "saldo_rs")),
    # noticias
    ("noticia_n_7d", "n: manchetes dos ultimos 7 dias", lambda f: _g(f, "noticias", "n_7d")),
    ("noticia_score_7d", "soma das notas 0-3 de 'faz preco' das manchetes pontuadas em 7 dias", lambda f: _g(f, "noticias", "score_7d")),
    ("noticia_max_7d", "maior nota 0-3 em 7 dias", lambda f: _g(f, "noticias", "max_7d")),
    # calendario
    ("dias_ate_resultado", "dias: ate a proxima divulgacao de resultado no calendario", lambda f: _g(f, "proximo_resultado", "proximo", "dias_ate")),
    ("dias_ate_provento_ex", "dias: ate a proxima data ex de provento", _ex),
    ("reacao_resultado_media_abs_pct", "%: reacao media (em modulo) do papel no pregao apos o resultado, historico do terminal",
     lambda f: _g(f, "proximo_resultado", "reacao_historica", "media_absoluta_pct")),
    # multiplos e balanco
    ("pl", "x: preco sobre lucro de 12 meses", lambda f: _g(f, "multiplos", "pl")),
    ("pvp", "x: preco sobre valor patrimonial", lambda f: _g(f, "multiplos", "pvp")),
    ("ev_ebitda", "x: valor da firma sobre EBITDA de 12 meses (vazio em banco/seguradora)", lambda f: _g(f, "multiplos", "ev_ebitda")),
    ("div_liq_ebitda", "x: divida liquida sobre EBITDA", lambda f: _g(f, "multiplos", "dl_ebitda")),
    ("dy_12m_pct", "%: dividendos e JCP dos ultimos 12 meses sobre o preco", lambda f: _g(f, "multiplos", "dy_12m_pct")),
    ("roe_pct", "%: retorno sobre o patrimonio", lambda f: _g(f, "multiplos", "roe_pct")),
    ("mg_liq_12m_pct", "%: margem liquida de 12 meses", lambda f: _g(f, "multiplos", "mg_liq_12m_pct")),
    ("cresc_lucro_12m_pct", "%: crescimento do lucro de 12 meses", lambda f: _g(f, "multiplos", "cresc_lucro_12m_pct")),
    ("balanco_idade_dias", "dias: idade do balanco usado nos multiplos", lambda f: _g(f, "multiplos", "balanco", "idade_dias")),
    # valuation contra a propria historia
    ("pl_pct_5a", "percentil 0-100 do P/L de hoje na historia de 5 anos (100 = mais caro)", lambda f: _g(f, "valuation", "pl", "percentil_5a")),
    ("pl_z_5a", "desvios-padrao do P/L de hoje contra a media de 5 anos", lambda f: _g(f, "valuation", "pl", "z_5a")),
    ("pvp_pct_5a", "percentil 0-100 do P/VP de hoje na historia de 5 anos", lambda f: _g(f, "valuation", "pvp", "percentil_5a")),
    ("ev_ebitda_pct_5a", "percentil 0-100 do EV/EBITDA de hoje na historia de 5 anos", lambda f: _g(f, "valuation", "ev_ebitda", "percentil_5a")),
    # divida
    ("div_cp_pct", "%: parte da divida bruta que vence no curto prazo", lambda f: _g(f, "divida", "curto_prazo_pct_da_divida")),
    ("div_cobertura_juros", "x: EBIT (ou EBITDA) sobre juros pagos, como o modulo divida mede", lambda f: _g(f, "divida", "cobertura_juros")),
    ("div_custo_pct", "% a.a.: custo medio da divida", lambda f: _g(f, "divida", "custo_pct")),
    ("div_moeda_estrangeira_pct", "%: parte da divida em moeda estrangeira (vazio quando a companhia nao abre)", lambda f: _g(f, "divida", "moeda_estrangeira_pct")),
    # opcoes
    ("iv_atm_pct", "% a.a.: volatilidade implicita no dinheiro (a ultima com data valida)", lambda f: _g(f, "opcoes", "iv_no_dinheiro", "pct")),
    ("iv_pctil", "percentil 0-100 da IV de hoje na historia de ate 60 pregoes", lambda f: _g(f, "opcoes", "iv_no_dinheiro", "percentil_historico")),
    ("opcoes_pc_oi", "razao put/call da posicao em aberto", lambda f: _g(f, "opcoes", "posicao", "put_call_oi")),
    ("opcoes_dor_maxima_dist_pct", "%: distancia da dor maxima (vencimento de referencia) ao preco", lambda f: _g(f, "opcoes", "no_vencimento_de_referencia", "dor_maxima_dist_pct")),
    # pares e fundos
    ("retorno_12d_pct", "%: retorno acumulado nos ultimos 12 pregoes", lambda f: _g(f, "pares", "retorno_12d_pct")),
    ("retorno_12d_vs_pares_pp", "pp: retorno de 12 pregoes menos a media dos pares proximos", lambda f: _g(f, "pares", "retorno_12d_vs_pares_pp")),
    ("fundos_pct_classe", "%: parte das acoes da classe na carteira dos fundos (CVM, com atraso de meses)", lambda f: _g(f, "fundos", "pct_das_acoes_da_classe")),
    ("resultado_antes_da_abertura", "0/1: o proximo resultado sai ANTES da abertura (estimativa: moda das ultimas 8 entregas com hora, confianca de 60% ou mais; vazio = sem estimativa firme)",
     lambda f: _bin(_g(f, "proximo_resultado", "proximo", "antes_da_abertura"))),
    ("resultado_momento_confianca", "0 a 1: iguais / entregas com hora, na estimativa do momento do resultado", lambda f: _g(f, "proximo_resultado", "proximo", "momento_confianca")),
    ("iv_skew_10_pp", "pp: volatilidade implicita ~10% abaixo do preco (put) menos ~10% acima (call), no vencimento de referencia; so com strike observado perto",
     lambda f: _g(f, "opcoes", "sorriso_do_vencimento_de_referencia", "skew_10_pp")),
    ("opcoes_pregao_incompleto", "0/1: o pregao mais recente veio incompleto da B3 e os numeros de opcao sao do ultimo pregao COMPLETO",
     lambda f: None if f.get("opcoes") is None else float(bool(_g(f, "opcoes", "pregao_incompleto_mais_recente")))),
]
NOMES = [c[0] for c in COLUNAS]
TEXTO = ("nome", "classe", "setor", "subsetor")


def documentacao() -> str:
    linhas = ["Colunas (indice = ticker; percentual em pontos, dinheiro em reais, vazio = o terminal nao tem o dado ou ele passou do limite de idade):"]
    for n, d, _ in COLUNAS:
        linhas.append(f"    {n:<32} {d}")
    return "\n".join(linhas)


def universo_padrao(ctx: S.Ctx, classes: Iterable[str]) -> list[str]:
    cls = set(classes)
    tks = [s for s, it in ctx.universo().items() if it.get("c") in cls]
    if tks:
        return sorted(tks)
    chaves = set((L.ler("multiplos.json") or {}).get("a", {})) | set(((L.ler("pagina/tir.json") or {}).get("empresas") or {}))
    return sorted(chaves)


def montar(tickers: Iterable[str] | None, ctx: S.Ctx, classes: Iterable[str]) -> pd.DataFrame:
    lista = [t.strip().upper() for t in tickers] if tickers is not None else universo_padrao(ctx, classes)
    linhas = []
    for t in lista:
        f = F.montar(t, ctx)
        linhas.append({n: fn(f) for n, _, fn in COLUNAS})
    df = pd.DataFrame(linhas, index=pd.Index(lista, name="ticker"), columns=NOMES)
    for n in NOMES:
        if n not in TEXTO:
            df[n] = pd.to_numeric(df[n], errors="coerce").astype(float)
    df.attrs["hoje"] = ctx.hoje.isoformat()
    df.attrs["terminal"] = str(L.raiz())
    return df


def cobertura(df: pd.DataFrame) -> pd.Series:
    """Quantos tickers tem cada coluna preenchida."""
    return df[[c for c in df.columns if c not in TEXTO]].notna().sum()
