"""
Conferencia do banco depois da primeira carga: os numeros de referencia, automatizados.

Por que existe: `validar-com-fonte-real.md` lista o que precisa ser conferido depois que
os dados reais chegam — precos de referencia num pregao conhecido, empresas deslistadas
presentes ate o ultimo dia em que existiram, os fatores do NEFIN batendo com o que o plano
afirma. Conferir isso a olho e o tipo de tarefa que se faz mal na primeira vez e nao se faz
mais nunca. Aqui cada item vira uma checagem com veredito.

  python3 -m quant.dados.conferir            # roda tudo o que der para rodar
  python3 -m quant.dados.conferir --json     # saida para script

Codigo de saida: 0 se nada FALHOU, 1 se alguma checagem falhou. Checagem que nao pode
rodar (dado ainda nao carregado) sai como "pulada" e NAO reprova — o objetivo e dizer o
que ja da para confiar, nao reclamar do que ainda nao chegou.

A CHECAGEM QUE MAIS IMPORTA e a das deslistadas. Se JBSS3, BRFS3 e STBP3 sumiram do banco,
o survivorship bias entrou: o backtest so vai ver quem sobreviveu, e o resultado sai alto
por um motivo que nao tem nada a ver com a estrategia. E o erro mais caro desta fase,
porque ele nao quebra nada — ele so faz o numero ficar bonito.
"""
import argparse
import json
import sys

import numpy as np
import pandas as pd

from quant.comum import log

# Precos de fechamento conferidos manualmente no COTAHIST (pregao de 27/12/2024).
# Fonte: `docs/validar-com-fonte-real.md`. Se o parser errar o offset dos campos de preco,
# e aqui que aparece — os tres valores saem errados juntos, e por um fator redondo.
PRECOS_REFERENCIA = {"PETR4": 35.66, "SLCE3": 17.68, "JBSS3": 36.21}
DATA_REFERENCIA = "2024-12-27"
TOLERANCIA_PRECO = 0.01

# Empresas que deixaram de negociar. Elas TEM de estar no banco ate o ultimo pregao em que
# existiram; se sumiram, o banco tem vies de sobrevivencia.
DESLISTADAS = ("JBSS3", "BRFS3", "STBP3")

# O que o plano afirma sobre os fatores do NEFIN (secao 1 do diagnostico), 2001-hoje.
# Tolerancia larga de proposito: o NEFIN revisa a serie, e o objetivo e pegar erro de
# leitura (coluna trocada, escala errada), nao divergencia de terceira casa.
FATORES_ESPERADOS = {
    "WML": {"media_aa": 0.154, "tol": 0.03, "t_min": 3.0},
    "HML": {"media_aa": 0.082, "tol": 0.03, "t_min": 1.5},
    "SMB": {"media_aa": -0.008, "tol": 0.03, "t_min": None},
    "Rm_minus_Rf": {"media_aa": 0.038, "tol": 0.03, "t_min": None},
}

OK, FALHOU, PULADA = "ok", "FALHOU", "pulada"


def _res(nome, estado, detalhe, esperado=None, obtido=None):
    return {"checagem": nome, "estado": estado, "detalhe": detalhe,
            "esperado": esperado, "obtido": obtido}


# ─────────────────────────────────────────────────────────────
# Checagens
# ─────────────────────────────────────────────────────────────
def checar_precos_de_referencia():
    """Tres fechamentos conferidos a mao. Pega erro de offset no parser de campo fixo."""
    from quant.dados import cotahist
    ano = int(DATA_REFERENCIA[:4])
    try:
        cot = cotahist.carregar(ano, ano, tickers=list(PRECOS_REFERENCIA))
    except Exception as e:
        return [_res("precos de referencia", PULADA,
                     f"COTAHIST de {ano} nao carregou ({type(e).__name__})")]
    if cot is None or len(cot) == 0:
        return [_res("precos de referencia", PULADA, f"sem COTAHIST de {ano} no banco")]
    d = cot[pd.to_datetime(cot["data"]) == pd.Timestamp(DATA_REFERENCIA)]
    saida = []
    for ticker, esperado in PRECOS_REFERENCIA.items():
        linha = d[d["ticker"] == ticker]
        if linha.empty:
            saida.append(_res(f"preco {ticker}", FALHOU,
                              f"sem cotacao de {ticker} em {DATA_REFERENCIA}", esperado, None))
            continue
        obtido = float(linha["fec"].iloc[0])
        bate = abs(obtido - esperado) <= TOLERANCIA_PRECO
        saida.append(_res(
            f"preco {ticker}", OK if bate else FALHOU,
            f"{DATA_REFERENCIA}: esperado {esperado:.2f}, obtido {obtido:.2f}"
            + ("" if bate else "  <- offset do parser ou preco nao dividido por 100"),
            esperado, obtido))
    return saida


def checar_deslistadas():
    """A checagem mais importante: empresa que morreu tem de estar no banco ate morrer."""
    from quant.dados import cotahist
    ano = pd.Timestamp.today().year
    try:
        cot = cotahist.carregar(ano - 3, ano, tickers=list(DESLISTADAS))
    except Exception as e:
        return [_res("deslistadas", PULADA, f"COTAHIST nao carregou ({type(e).__name__})")]
    if cot is None or len(cot) == 0:
        return [_res("deslistadas", PULADA, "sem COTAHIST no banco")]
    saida = []
    for ticker in DESLISTADAS:
        d = cot[cot["ticker"] == ticker]
        if d.empty:
            saida.append(_res(
                f"deslistada {ticker}", FALHOU,
                f"{ticker} nao existe no banco. VIES DE SOBREVIVENCIA: o backtest so vai "
                "ver quem sobreviveu e o resultado sai alto sem a estrategia ter merito",
                "presente", "ausente"))
            continue
        ultimo = pd.to_datetime(d["data"]).max().date()
        saida.append(_res(f"deslistada {ticker}", OK,
                          f"presente ate {ultimo} ({len(d)} pregoes na janela)",
                          "presente", str(ultimo)))
    return saida


def checar_fatores_nefin():
    """Os numeros que sustentam a tese: WML e HML tem de sair como o plano afirma."""
    from quant.dados import nefin
    try:
        f = nefin.carregar_fatores()
    except Exception as e:
        return [_res("fatores NEFIN", PULADA, f"snapshot ausente ({type(e).__name__})")]
    if f is None or len(f) == 0:
        return [_res("fatores NEFIN", PULADA, "snapshot vazio")]
    est = nefin.estatisticas(f)
    saida = []
    for fator, alvo in FATORES_ESPERADOS.items():
        e = est.get(fator)
        if not e:
            saida.append(_res(f"fator {fator}", FALHOU, "coluna ausente no snapshot"))
            continue
        media, t = float(e["media_aa"]), float(e["t"])
        perto = abs(media - alvo["media_aa"]) <= alvo["tol"]
        forte = alvo["t_min"] is None or t >= alvo["t_min"]
        estado = OK if (perto and forte) else FALHOU
        detalhe = (f"media {media:+.2%} a.a. (plano: {alvo['media_aa']:+.1%}), t = {t:.2f}")
        if not perto:
            detalhe += "  <- fora da tolerancia: coluna trocada ou escala errada?"
        elif not forte:
            detalhe += f"  <- t abaixo de {alvo['t_min']:.1f}"
        saida.append(_res(f"fator {fator}", estado, detalhe, alvo["media_aa"], media))
    periodo = est.get("_periodo", {})
    saida.append(_res("periodo NEFIN", OK,
                      f"{periodo.get('ini')} a {periodo.get('fim')} "
                      f"({periodo.get('dias')} pregoes)", None, periodo.get("fim")))
    return saida


def checar_identidade():
    """Todo papel do universo precisa de CD_CVM, senao nao ha fundamento para ele."""
    from quant.dados import identidade
    try:
        ident = identidade.carregar_identidade()
    except Exception as e:
        return [_res("identidade", PULADA, f"nao carregou ({type(e).__name__})")]
    if ident is None or len(ident) == 0:
        return [_res("identidade", PULADA, "tabela de identidade vazia")]
    com_cvm = ident["cd_cvm"].notna().mean() if "cd_cvm" in ident else 0.0
    estado = OK if com_cvm >= 0.90 else FALHOU
    return [_res("identidade com CD_CVM", estado,
                 f"{com_cvm:.1%} dos papeis tem CD_CVM (minimo 90%)", 0.90, float(com_cvm))]


def checar_eventos():
    """Sem evento nao ha retorno total, e sem retorno total o momentum e ficcao."""
    from quant.dados import eventos
    try:
        ev = eventos.carregar_eventos()
    except Exception as e:
        return [_res("eventos", PULADA, f"nao carregou ({type(e).__name__})")]
    if ev is None or len(ev) == 0:
        return [_res("eventos", PULADA, "tabela de eventos vazia")]
    tipos = ev["tipo"].value_counts().to_dict() if "tipo" in ev else {}
    return [_res("eventos carregados", OK,
                 f"{len(ev)} eventos; por tipo: " +
                 ", ".join(f"{k}={v}" for k, v in list(tipos.items())[:6]),
                 None, len(ev))]


def checar_cdi():
    """O adversario da estrategia. Sem ele nao ha excesso para medir."""
    from quant.dados import cdi
    try:
        serie = cdi.carregar(permitir_rede=False)
    except Exception as e:
        return [_res("CDI", PULADA, f"nao carregou ({type(e).__name__})")]
    if serie is None or len(serie) == 0:
        return [_res("CDI", PULADA, "serie de CDI vazia")]
    aa = float((1 + serie.tail(252)).prod() - 1) if len(serie) >= 252 else float("nan")
    fonte = serie.attrs.get("fonte", "desconhecida")
    plausivel = not np.isfinite(aa) or (0.02 <= aa <= 0.30)
    return [_res("CDI", OK if plausivel else FALHOU,
                 f"{len(serie)} dias, fonte {fonte}, ultimos 252 pregoes = {aa:.2%}"
                 + ("" if plausivel else "  <- fora de qualquer faixa plausivel; escala?"),
                 None, aa)]


CHECAGENS = (
    ("precos de referencia", checar_precos_de_referencia),
    ("deslistadas", checar_deslistadas),
    ("fatores NEFIN", checar_fatores_nefin),
    ("identidade", checar_identidade),
    ("eventos", checar_eventos),
    ("CDI", checar_cdi),
)


def rodar_tudo():
    """Roda todas as checagens. Nenhuma derruba as outras."""
    saida = []
    for nome, funcao in CHECAGENS:
        try:
            saida.extend(funcao() or [])
        except Exception as e:                     # checagem quebrada nao pode virar veredito
            saida.append(_res(nome, PULADA, f"a propria checagem falhou ({type(e).__name__}: {e})"))
    return saida


def imprimir(resultados):
    largura = max((len(r["checagem"]) for r in resultados), default=10) + 2
    print("=" * 76)
    print("CONFERENCIA DO BANCO")
    print("=" * 76)
    for r in resultados:
        print(f"  {r['checagem']:<{largura}} {r['estado']:<8} {r['detalhe']}")
    print("=" * 76)
    falhas = [r for r in resultados if r["estado"] == FALHOU]
    puladas = [r for r in resultados if r["estado"] == PULADA]
    print(f"{len(resultados) - len(falhas) - len(puladas)} ok, {len(falhas)} falharam, "
          f"{len(puladas)} puladas (dado ainda nao carregado)")
    if falhas:
        print()
        print("NAO SIGA com o gate enquanto houver falha aqui. O gate compara os SEUS")
        print("fatores com os do NEFIN; se o banco esta errado, o gate vai reprovar sem")
        print("dizer o motivo, e voce vai passar dias procurando no lugar errado.")
    elif puladas:
        print()
        print("Complete a carga e rode de novo:")
        print("  python3 -m quant.primeira_carga --continuar")
    else:
        print()
        print("Banco conferido. O proximo passo e o gate da fase 1:")
        print("  python3 -m quant.validacao.replica_nefin --ini 2008 --fim 2026")
    return 1 if falhas else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Confere o banco contra os valores de referencia")
    ap.add_argument("--json", action="store_true", help="saida em JSON, para script")
    args = ap.parse_args(argv)
    resultados = rodar_tudo()
    if args.json:
        print(json.dumps(resultados, ensure_ascii=False, indent=2, default=str))
        return 1 if any(r["estado"] == FALHOU for r in resultados) else 0
    return imprimir(resultados)


if __name__ == "__main__":
    sys.exit(main())
