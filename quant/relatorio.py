"""
Relatorio periodico e os criterios de encerramento (M14).

Por que existe: um sistema que roda sozinho vira invisivel, e o que fica invisivel deixa
de ser julgado. Este modulo produz, toda semana e todo mes, o documento que responde a
unica pergunta que importa - continua ou para? - com numeros, e nao com sensacao.

OS SETE CRITERIOS DE KILL da secao 10 do plano estao codificados aqui, em `CRITERIOS`, e
sao avaliados a cada relatorio. Foram escritos ANTES do primeiro trade de proposito: o
momento de decidir quando parar e o momento em que ainda nao ha dinheiro em jogo. Mudar um
gatilho depois de ele ser atingido e a forma mais comum de perder muito dinheiro devagar,
entao qualquer mudanca aqui deve virar uma linha no changelog do README com a data.

Tres coisas que o relatorio faz questao de dizer, mesmo quando esta tudo verde:
  - a origem dos dados (real ou sintetico) e se o gate da fase 1 passou;
  - a cobertura do sinal de aluguel, que e ZERO no backtest e continua zero ate haver
    historico proprio arquivado;
  - que a apuracao de imposto e calculo de apoio e precisa de contador.

O status de cada criterio e "ok", "atencao" (metade do caminho) ou "disparado". Um
criterio disparado nao para o sistema sozinho - quem para e o Douglas. O programa avisa.
"""
import argparse
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

from quant.comum import DIR_SAIDA, garantir_dir, log

# Gatilhos dos sete criterios (secao 10 do plano). Numero e o gatilho de PARADA;
# `atencao` e onde o relatorio comeca a avisar.
CRITERIOS = {
    "drawdown": {"rotulo": "Drawdown do pico", "gatilho": 0.30, "atencao": 0.20,
                 "formato": "pct",
                 "descricao": "20% reduz o gross pela metade e obriga revisao; 30% encerra"},
    "excesso_12m": {"rotulo": "Excesso sobre o CDI em 12 meses", "gatilho": -0.10,
                    "formato": "pct",
                    "atencao": -0.05, "sentido": "menor",
                    "descricao": "abaixo de -10 p.p. com alfa NEFIN negativo, para"},
    "slippage": {"rotulo": "Slippage contra o modelado", "gatilho": 2.0, "atencao": 1.5,
                 "formato": "x",
                 "descricao": "acima de 2x por 3 meses seguidos, suspende"},
    "giro": {"rotulo": "Giro mensal", "gatilho": 0.35, "atencao": 0.25,
             "formato": "pct",
             "descricao": "acima de 35% ao mes por 3 meses seguidos, suspende"},
    "excesso_24m": {"rotulo": "Excesso liquido de IR sobre a Selic em 24 meses",
                    "gatilho": 0.0, "atencao": 0.005, "sentido": "menor",
                    "formato": "pct",
                    "descricao": "24 meses sem ganhar da Selic liquida encerra; e decisao "
                                 "economica, nao estatistica"},
    "erros": {"rotulo": "Erros de execucao no mes", "gatilho": 2, "atencao": 1,
              "formato": "num",
              "descricao": "2 ou mais execucoes erradas no mes, ou margem chamada sem "
                           "caixa, suspende"},
    "universo": {"rotulo": "Tamanho do universo", "gatilho": 100, "atencao": 120,
                 "formato": "num",
                 "sentido": "menor",
                 "descricao": "universo abaixo de 100 nomes tira a premissa da estrategia"},
    "mudancas": {"rotulo": "Mudancas de parametro no ano", "gatilho": 2, "atencao": 2,
                 "formato": "num",
                 "descricao": "no maximo 2 por ano, cada uma com backtest comparado e 3 "
                              "meses de paper em paralelo"},
}
MESES_PERSISTENCIA = 3          # slippage e giro so disparam depois de 3 meses seguidos
ARQ_RELATORIO = os.path.join(DIR_SAIDA, "relatorio_{periodo}.md")


# ─────────────────────────────────────────────────────────────
# Criterios de kill
# ─────────────────────────────────────────────────────────────
def _status(valor, gatilho, atencao, sentido="maior"):
    """'ok' | 'atencao' | 'disparado'. `sentido='menor'` inverte a comparacao."""
    if valor is None or (isinstance(valor, float) and not np.isfinite(valor)):
        return "ok"
    if sentido == "menor":
        if valor <= gatilho:
            return "disparado"
        return "atencao" if valor <= atencao else "ok"
    if valor >= gatilho:
        return "disparado"
    return "atencao" if valor >= atencao else "ok"


def criterios_kill(medidas):
    """Avalia os sete criterios. `medidas` e um dict com as chaves de CRITERIOS.

    Devolve a lista no formato do bloco `kill` de docs/painel-contrato.md, com tipos JSON
    nativos. Criterio sem medida disponivel sai como 'ok' com valor None - nao existe
    "disparado por falta de dado", porque isso viraria alarme falso todo dia.
    """
    medidas = dict(medidas or {})
    saida = []
    for chave, c in CRITERIOS.items():
        valor = medidas.get(chave)
        persistente = medidas.get(chave + "_meses", 0)
        status = _status(valor, c["gatilho"], c["atencao"], c.get("sentido", "maior"))
        # slippage e giro so disparam com persistencia: um mes ruim nao para o sistema
        if chave in ("slippage", "giro") and status == "disparado" and persistente < MESES_PERSISTENCIA:
            status = "atencao"
        v = None
        if valor is not None and (not isinstance(valor, float) or np.isfinite(valor)):
            v = float(valor)
        saida.append({"criterio": chave, "rotulo": c["rotulo"], "valor": v,
                      "gatilho": float(c["gatilho"]), "status": status,
                      "formato": c.get("formato", "num"), "descricao": c["descricao"]})
    return saida


def formatar_kill(valor, formato="num"):
    """Nem todo criterio e percentual: universo e contagem de nomes, slippage e multiplo.

    Formatar tudo como porcentagem faz um universo de 33 nomes aparecer como "3.300%" -
    foi exatamente o que aconteceu na primeira versao do painel. `bool` existe porque
    "parametros intocados: 1" nao quer dizer nada para quem le a tela.
    """
    if valor is None or (isinstance(valor, float) and not np.isfinite(valor)):
        return "--"
    v = float(valor)
    if formato == "bool":
        return "sim" if v else "nao"
    if formato == "pct":
        return f"{100 * v:.1f}%"
    if formato == "x":
        return f"{v:.2f}x"
    return f"{v:.0f}" if abs(v - round(v)) < 1e-9 else f"{v:.4g}"


def algum_disparado(kill):
    return [k["criterio"] for k in (kill or []) if k["status"] == "disparado"]


# ─────────────────────────────────────────────────────────────
# Medidas de desempenho
# ─────────────────────────────────────────────────────────────
def desempenho(serie, cdi=None, ibov=None, desde=None):
    """Bloco `desempenho` do painel a partir da serie diaria de patrimonio.

    `serie`: DataFrame(data, patrimonio) ou a serie do backtest. `cdi` e `ibov`: Series
    diarias de retorno. Tudo em tipos JSON nativos, com `null` no lugar de NaN.
    """
    vazio = {"desde": None, "retorno": None, "cdi": None, "excesso": None, "ibov": None,
             "vol": None, "mdd": None, "giro_mensal": None, "custo_aa": None, "serie": []}
    if serie is None or len(serie) < 2:
        return vazio
    s = serie.copy()
    s["data"] = pd.to_datetime(s["data"])
    s = s.sort_values("data").reset_index(drop=True)
    if desde is not None:
        s = s[s["data"] >= pd.Timestamp(desde)]
    if len(s) < 2:
        return vazio
    ret = s["patrimonio"].iloc[-1] / s["patrimonio"].iloc[0] - 1.0
    # fill_method=None de proposito: o padrao propaga o ultimo valor por cima do
    # buraco e inventa um retorno zero onde na verdade nao se sabe.
    diario = s["patrimonio"].pct_change(fill_method=None).fillna(0.0)
    idx = s["data"]
    cdi_ac = _acumular(cdi, idx)
    ibov_ac = _acumular(ibov, idx)
    curva = (1 + diario).cumprod()
    mdd = float((1 - curva / curva.cummax()).max())
    linhas = []
    c_cum = (1 + _alinhar(cdi, idx)).cumprod() if cdi is not None else None
    i_cum = (1 + _alinhar(ibov, idx)).cumprod() if ibov is not None else None
    for n, d in enumerate(idx):
        linhas.append({"data": d.strftime("%Y-%m-%d"),
                       "carteira": _num(curva.iloc[n]),
                       "cdi": _num(c_cum.iloc[n]) if c_cum is not None else None,
                       "ibov": _num(i_cum.iloc[n]) if i_cum is not None else None})
    return {"desde": idx.iloc[0].strftime("%Y-%m-%d"), "retorno": _num(ret),
            "cdi": _num(cdi_ac), "excesso": _num(ret - cdi_ac) if cdi_ac is not None else None,
            "ibov": _num(ibov_ac), "vol": _num(diario.std(ddof=1) * np.sqrt(252)),
            "mdd": _num(mdd), "giro_mensal": None, "custo_aa": None, "serie": linhas}


def _alinhar(taxa, idx):
    if taxa is None:
        return pd.Series(0.0, index=range(len(idx)))
    t = pd.Series(taxa).copy()
    t.index = pd.to_datetime(t.index)
    return t.reindex(pd.DatetimeIndex(idx)).fillna(0.0).reset_index(drop=True)


def _acumular(taxa, idx):
    if taxa is None:
        return None
    return float((1 + _alinhar(taxa, idx)).prod() - 1.0)


def _num(x, casas=6):
    if x is None:
        return None
    v = float(x)
    return None if not np.isfinite(v) else round(v, casas)


# ─────────────────────────────────────────────────────────────
# Relatorio
# ─────────────────────────────────────────────────────────────
def _pct(x, casas=2):
    return "--" if x is None else f"{100 * float(x):.{casas}f}%"


def _brl(x):
    return "--" if x is None else f"R$ {float(x):,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


def montar(painel, periodo="mensal", medidas_kill=None):
    """Relatorio em Markdown a partir do `painel.json` (ver docs/painel-contrato.md)."""
    p = dict(painel or {})
    d = p.get("desempenho") or {}
    f = p.get("fiscal") or {}
    c = p.get("carteira") or {}
    kill = p.get("kill") or criterios_kill(medidas_kill)
    origem = p.get("origem", "desconhecida")
    gate = (p.get("gate_fase1") or {}).get("passou")

    L = [f"# Relatorio {periodo} — sistema quant B3", ""]
    L.append(f"- Gerado em: {p.get('gerado_em', '--')}")
    L.append(f"- Modo: **{p.get('modo', '--')}** | Origem dos dados: **{origem}**")
    L.append(f"- Gate da fase 1 (replica WML/HML do NEFIN): "
             f"**{'passou' if gate else 'NAO RODOU / NAO PASSOU'}**")
    if origem != "real" or not gate:
        L.append("")
        L.append("> **Nenhum numero deste relatorio e resultado de estrategia.** Os dados sao "
                 "sinteticos ou o gate da fase 1 nao foi aprovado; o que esta medido aqui e a "
                 "mecanica do sistema, nao a vantagem dele.")
    ms = p.get("modo_seguro") or {}
    if ms.get("ativo"):
        L.append("")
        L.append("> **Modo seguro ativo**: nao houve boleta. Motivos: "
                 + "; ".join(ms.get("motivos") or ["nao informado"]) + ".")

    L += ["", "## Desempenho", "", "| medida | valor |", "|---|---|"]
    L.append(f"| retorno no periodo | {_pct(d.get('retorno'))} |")
    L.append(f"| CDI | {_pct(d.get('cdi'))} |")
    L.append(f"| excesso sobre o CDI | {_pct(d.get('excesso'))} |")
    L.append(f"| Ibovespa | {_pct(d.get('ibov'))} |")
    L.append(f"| volatilidade anualizada | {_pct(d.get('vol'))} |")
    L.append(f"| drawdown maximo | {_pct(d.get('mdd'))} |")
    L.append(f"| giro mensal | {_pct(d.get('giro_mensal'))} |")
    L.append(f"| custo ao ano | {_pct(d.get('custo_aa'))} |")

    L += ["", "## Carteira", ""]
    L.append(f"- Patrimonio: {_brl(c.get('patrimonio'))} | Caixa: {_brl(c.get('caixa'))} "
             f"| Exposicao: {_pct(c.get('exposicao'))}")
    L.append(f"- Nomes: {c.get('n_posicoes', 0)} | Contratos de indice: {c.get('contratos_hedge', 0)}")
    if c.get("violacoes"):
        L.append(f"- **Restricoes violadas**: {'; '.join(c['violacoes'])}")

    L += ["", "## Fiscal", ""]
    L.append(f"- Mes {f.get('mes', '--')}: vendas de acoes {_brl(f.get('vendas_acoes_mes'))}, "
             f"folga na isencao {_brl(f.get('isencao_restante'))}")
    L.append(f"- Lucro comum {_brl(f.get('lucro_comum'))} | day trade {_brl(f.get('lucro_day_trade'))}")
    L.append(f"- Prejuizo acumulado: comum {_brl(f.get('prejuizo_acumulado_comum'))}, "
             f"day trade {_brl(f.get('prejuizo_acumulado_day_trade'))}")
    L.append(f"- **DARF {_brl(f.get('darf'))}**, vence em {f.get('darf_vence', '--')}")
    if f.get("aviso"):
        L.append(f"- {f['aviso']}")

    L += ["", "## Criterios de encerramento", "",
          "| criterio | valor | gatilho | status |", "|---|---|---|---|"]
    for k in kill:
        marca = {"ok": "ok", "atencao": "ATENCAO", "disparado": "**DISPARADO**"}[k["status"]]
        L.append(f"| {k['rotulo']} | {formatar_kill(k['valor'], k.get('formato'))} | "
                 f"{formatar_kill(k['gatilho'], k.get('formato'))} | {marca} |")
    disparados = algum_disparado(kill)
    if disparados:
        L += ["", f"> **{len(disparados)} criterio(s) disparado(s): {', '.join(disparados)}.** "
                  "A regra escrita antes do primeiro trade manda agir. Mudar o gatilho agora "
                  "e a forma mais comum de perder muito dinheiro devagar."]

    v = p.get("versao") or {}
    if v:
        L += ["", "## Versao do sistema", ""]
        if v.get("vigente"):
            L.append(f"- Vigente: **{v['vigente']}** ({v.get('descricao') or 'sem descricao'}), "
                     f"desde {v.get('desde') or '--'}")
        else:
            L.append("- **Nenhuma versao registrada.** Registre a linha de base antes da "
                     "primeira mudanca: sem ela nao ha contra o que comparar "
                     "(`python3 -m quant.versoes --registrar`).")
        for x in v.get("em_paralelo") or []:
            L.append(f"- Em paralelo: {x.get('id')} ({x.get('descricao')}), "
                     f"vale a partir de {x.get('vale_a_partir_de')} — ate la quem manda e a anterior")
        L.append(f"- Mudancas em {date.today().year}: {v.get('mudancas_no_ano', 0)} de "
                 f"{v.get('limite_ano', 2)} do orcamento anual")
        if v.get("vigente") and v.get("config_confere") is False:
            L.append(f"- **MUDANCA NAO REGISTRADA** em {len(v.get('divergencia') or [])} "
                     f"parametro(s): {', '.join((v.get('divergencia') or [])[:6]) or '--'}. "
                     "Ou registre a versao, ou desfaca a mudanca — as duas coisas sao "
                     "aceitaveis; deixar assim nao e.")
        if v.get("cadeia_ok") is False:
            L.append(f"- **A cadeia do changelog esta quebrada** na linha {v.get('cadeia_quebra')}.")

    L += ["", "## Limites conhecidos", "",
          "- Aluguel (sinal 6): **0 meses de cobertura**. A B3 guarda 21 pregoes e o "
          "arquivamento deste repositorio comecou agora; nao e 'nao testado', e nao testavel.",
          "- Insiders (sinal 7): desligado. O VLMO comeca em 2017 e o bonus exige free float.",
          "- A apuracao de imposto e calculo de apoio: confira a memoria de calculo em "
          "`quant/saida/fiscal_memoria.csv` e valide com contador antes de recolher.", ""]
    return "\n".join(L)


def gravar(texto, periodo, dir_saida=DIR_SAIDA):
    garantir_dir(dir_saida)
    caminho = os.path.join(dir_saida, f"relatorio_{periodo}.md")
    with open(caminho, "w", encoding="utf-8") as fh:
        fh.write(texto)
    return caminho


def main(argv=None):
    ap = argparse.ArgumentParser(description="Relatorio periodico e criterios de kill (M14)")
    ap.add_argument("--periodo", choices=["semanal", "mensal"], default="mensal")
    ap.add_argument("--mes", default=None, help="AAAA-MM (so rotula o arquivo)")
    args = ap.parse_args(argv)
    from quant.comum import ler_json
    painel = ler_json(os.path.join(DIR_SAIDA, "painel.json"))
    if not painel:
        print("sem painel.json; rode python -m quant.rodar_diario --paper")
        return 2
    texto = montar(painel, periodo=args.periodo)
    rotulo = args.mes or args.periodo
    caminho = gravar(texto, rotulo)
    print(texto)
    log(f"relatorio em {caminho}")
    return 1 if algum_disparado(painel.get("kill")) else 0


if __name__ == "__main__":
    sys.exit(main())
