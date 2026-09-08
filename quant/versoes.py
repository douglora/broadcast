"""
Changelog de versoes do sistema: o criterio de kill numero 7, escrito em codigo.

O plano diz, na secao 10: "maximo 2 mudancas de parametro por ano, cada uma com nova
versao e 3 meses de paper em paralelo". Enquanto isso e so uma frase num documento, e uma
frase que se descumpre sozinha — mexer num percentil depois de um mes ruim custa trinta
segundos e nao deixa rastro. Este modulo faz a regra ter dentes:

  1. `registrar()` RECUSA a terceira mudanca do ano e diz quando a proxima janela abre;
  2. RECUSA versao que nao muda parametro nenhum (o diff sai vazio) e versao sem backtest
     comparado;
  3. toda MUDANCA nasce `em_paralelo` e so vira `vigente` depois de MESES_PARALELO meses.
     Uma versao nova nao passa a valer no dia em que foi pensada; enquanto ela roda em
     paralelo, quem manda continua sendo a anterior. (A primeira versao e a linha de base:
     vale desde ja e nao consome orcamento, porque nao muda nada.);
  4. o diff contra a versao anterior e calculado, nao declarado: "eu so mexi num percentil"
     vira uma lista de campos que da para conferir.

POR QUE A REGRA EXISTE. Com ~10 anos de dado utilizavel e um prêmio esperado da ordem de
1 p.p. ao ano, nenhum backtest tem poder para distinguir "o parametro estava errado" de
"o ano foi ruim". Trocar parametro depois de um drawdown e, quase sempre, ajustar o
sistema ao ruido do passado recente — e cada ajuste desses queima uma tentativa no
`livro.py`, que e o que o Sharpe deflacionado desconta. Duas mudancas por ano nao e um
numero magico: e um orcamento pequeno o bastante para doer na hora de gastar.

O QUE ESTE MODULO NAO FAZ. Ele nao impede voce de editar `sinais.py` e rodar. Nada impede.
O que ele faz e deixar o rastro: a versao vigente carrega o hash da configuracao, e
`conferir()` compara esse hash com o do codigo de agora. Divergiu, o painel mostra
MUDANCA NAO REGISTRADA em vermelho, e a campanha de paper trading (fase 4) reprova o
criterio de parametros estaveis. A disciplina continua sendo sua; o que muda e que a
falta dela para de ser invisivel.

Arquivo: `quant/versoes.jsonl`, encadeado por hash como o livro de tentativas, e
VERSIONADO NO GIT de proposito — apagar uma versao para reescrever a historia deixa um
diff. Nao e dado pessoal: e o registro de governanca do proprio sistema.
"""
import argparse
import json
import os
import sys
from datetime import date

import pandas as pd

from quant.comum import DIR_QUANT, agora_iso, gravar_atomico, log
from quant.livro import _hash_linha, _linhas_cruas, canonizar, hash_config, versao_codigo

ARQ_VERSOES = os.path.join(DIR_QUANT, "versoes.jsonl")

LIMITE_MUDANCAS_ANO = 2      # secao 10, criterio de kill 7
MESES_PARALELO = 3           # paper em paralelo antes de a versao valer
ESTADOS = ("em_paralelo", "vigente", "descartada")
COLUNAS = ["id", "carimbo", "estado", "linha_de_base", "descricao", "motivo",
           "hash_config", "config", "diff", "backtest", "vigente_a_partir_de",
           "versao_codigo", "hash_anterior", "hash"]
CAMPOS_HASH = ("hash_anterior", "hash")


# ─────────────────────────────────────────────────────────────
# Leitura
# ─────────────────────────────────────────────────────────────
def historico(caminho=ARQ_VERSOES):
    """Lista de versoes, da mais antiga para a mais nova. Arquivo ausente: lista vazia."""
    saida = []
    for i, bruto in enumerate(_linhas_cruas(caminho)):
        try:
            r = json.loads(bruto)
        except Exception:
            log(f"versoes: linha {i} ilegivel; ignorada na leitura")
            continue
        if isinstance(r, dict):
            saida.append(r)
    return saida


def verificar_cadeia(caminho=ARQ_VERSOES):
    """(ok, indice da primeira quebra), mesmo contrato de `livro.verificar_cadeia`."""
    anterior = ""
    for i, bruto in enumerate(_linhas_cruas(caminho)):
        try:
            linha = json.loads(bruto)
        except Exception:
            return False, i
        if not isinstance(linha, dict):
            return False, i
        if linha.get("hash_anterior") != anterior:
            return False, i
        if linha.get("hash") != _hash_linha(linha, anterior):
            return False, i
        anterior = linha["hash"]
    return True, None


def vigente(caminho=ARQ_VERSOES, hoje=None):
    """A versao que manda hoje: a mais recente que ja cumpriu o paper em paralelo.

    Enquanto a versao nova roda em paralelo, quem manda continua sendo a ANTERIOR — e esse
    e o ponto da regra. Sem nenhuma versao promovida, devolve None.
    """
    hoje = pd.Timestamp(hoje or date.today())
    promovidas = [v for v in historico(caminho)
                  if v.get("estado") == "vigente"
                  or (v.get("estado") == "em_paralelo"
                      and _venceu_o_paralelo(v, hoje))]
    return promovidas[-1] if promovidas else None


def em_paralelo(caminho=ARQ_VERSOES, hoje=None):
    """Versoes ainda cumprindo os 3 meses de paper. Lista (normalmente com zero ou um)."""
    hoje = pd.Timestamp(hoje or date.today())
    return [v for v in historico(caminho)
            if v.get("estado") == "em_paralelo" and not _venceu_o_paralelo(v, hoje)]


def _venceu_o_paralelo(v, hoje):
    quando = v.get("vigente_a_partir_de")
    if not quando:
        return False
    try:
        return pd.Timestamp(hoje) >= pd.Timestamp(quando)
    except Exception:
        return False


def mudancas_no_ano(ano=None, caminho=ARQ_VERSOES):
    """Quantas MUDANCAS foram registradas no ano.

    A linha de base nao conta: ela nao muda nada, e o ponto de partida. Versao descartada
    tambem nao conta — nao chegou a valer.
    """
    ano = int(ano or date.today().year)
    return sum(1 for v in historico(caminho)
               if v.get("estado") != "descartada"
               and not v.get("linha_de_base")
               and str(v.get("carimbo", ""))[:4] == str(ano))


def pode_mudar(quando=None, caminho=ARQ_VERSOES, limite=LIMITE_MUDANCAS_ANO):
    """(pode, motivo). Motivo vazio quando pode; quando nao pode, diz quando abre a janela."""
    quando = pd.Timestamp(quando or date.today())
    usadas = mudancas_no_ano(quando.year, caminho)
    if usadas < int(limite):
        return True, ""
    return False, (f"o orcamento de {limite} mudancas de {quando.year} acabou "
                   f"({usadas} usadas). A proxima janela abre em 01/01/{quando.year + 1}. "
                   "Esperar e o comportamento desejado: a regra existe justamente para "
                   "impedir o ajuste que parece obvio depois de um mes ruim.")


# ─────────────────────────────────────────────────────────────
# Diff entre configuracoes
# ─────────────────────────────────────────────────────────────
def diff_config(antes, depois, prefixo=""):
    """Lista de {campo, de, para} entre duas configuracoes aninhadas.

    Percorre dicionarios recursivamente; qualquer outra coisa (lista, numero, texto) e
    comparada inteira. Campo que so existe de um lado aparece com o outro lado None.
    """
    antes = antes if isinstance(antes, dict) else {}
    depois = depois if isinstance(depois, dict) else {}
    saida = []
    for chave in sorted(set(antes) | set(depois)):
        a, b = antes.get(chave), depois.get(chave)
        campo = f"{prefixo}{chave}"
        if isinstance(a, dict) or isinstance(b, dict):
            saida.extend(diff_config(a, b, prefixo=f"{campo}."))
            continue
        if canonizar(a) != canonizar(b):
            saida.append({"campo": campo, "de": a, "para": b})
    return saida


# ─────────────────────────────────────────────────────────────
# Registro
# ─────────────────────────────────────────────────────────────
def registrar(descricao, motivo, backtest, config=None, caminho=ARQ_VERSOES,
              quando=None, meses_paralelo=MESES_PARALELO, forcar=False):
    """Anexa uma versao ao changelog e devolve o dict gravado.

    `descricao`: o que mudou, em uma linha. `motivo`: POR QUE mudou — o campo que vai ser
    lido daqui a um ano para julgar se a mudanca foi pesquisa ou panico.
    `backtest`: dict comparando a versao nova com a atual (o plano exige backtest comparado;
    sem ele a funcao recusa). `config`: por padrao, a configuracao viva do codigo.

    A PRIMEIRA versao e a linha de base: vale desde ja, nao consome o orcamento anual e
    nao exige diff, porque nao muda nada — e o ponto de partida contra o qual as proximas
    serao comparadas. Da segunda em diante valem as tres regras.

    Levanta RuntimeError quando o orcamento anual acabou, quando nada mudou, ou quando
    falta backtest. `forcar=True` so passa por cima do orcamento anual, e grava a excecao
    dentro da propria versao — quem for ler o changelog vai ver que a regra foi quebrada
    e em que dia.
    """
    quando = pd.Timestamp(quando or date.today())
    if config is None:
        from quant.execucao import campanha as cp
        config = cp.config_da_estrategia()

    linhas = _linhas_cruas(caminho)
    anteriores = historico(caminho)
    base = not anteriores                      # a primeira versao e a linha de base

    pode, porque = pode_mudar(quando, caminho)
    if not base and not pode and not forcar:
        raise RuntimeError(porque)
    if not backtest:
        raise RuntimeError(
            "versao sem backtest. Numa mudanca o plano cobra a comparacao contra a versao "
            "atual; na linha de base, o resultado da fase 2. Registrar sem isso transforma "
            "o changelog num diario de opinioes.")

    config_anterior = anteriores[-1]["config"] if anteriores else {}
    diff = diff_config(config_anterior, config)
    if anteriores and not diff:
        raise RuntimeError(
            "nenhum parametro mudou em relacao a versao anterior: nao existe versao nova. "
            "Se a mudanca foi no codigo e nao em parametro, o hash nao a enxerga — "
            "descreva no commit e no changelog do repositorio.")

    linha = {
        "id": f"v{len(anteriores) + 1}",
        "carimbo": agora_iso(),
        # A linha de base vale desde ja: ela nao muda nada, e o ponto de partida. Os 3
        # meses de paper em paralelo sao o preco de uma MUDANCA, nao do primeiro registro.
        "estado": "vigente" if base else "em_paralelo",
        "linha_de_base": bool(base),
        "descricao": str(descricao),
        "motivo": str(motivo),
        "hash_config": hash_config(config),
        "config": config,
        "diff": diff,
        "backtest": backtest,
        "vigente_a_partir_de": str(quando.date() if base else
                                   (quando + pd.DateOffset(months=int(meses_paralelo))).date()),
        "versao_codigo": versao_codigo(),
    }
    if not base and not pode:
        linha["excecao"] = {"regra": "orcamento anual de mudancas", "motivo": porque}
    anterior = json.loads(linhas[-1]).get("hash", "") if linhas else ""
    linha["hash_anterior"] = anterior or ""
    linha["hash"] = _hash_linha(linha, linha["hash_anterior"])
    conteudo = "".join(x + "\n" for x in linhas) + json.dumps(linha, ensure_ascii=False) + "\n"
    gravar_atomico(caminho, conteudo)
    log(f"versoes: {linha['id']} ({descricao}) — {len(diff)} parametro(s), "
        f"vale a partir de {linha['vigente_a_partir_de']}")
    return linha


def conferir(config=None, caminho=ARQ_VERSOES, hoje=None):
    """A configuracao viva bate com a versao que manda hoje?

    Devolve {"ok", "versao", "hash_esperado", "hash_atual", "diff", "motivo"}. `ok=False`
    com `versao=None` significa "nunca houve versao registrada", que e o estado normal
    antes da primeira: nao e alarme, e ausencia de linha de base.
    """
    if config is None:
        try:
            from quant.execucao import campanha as cp
            config = cp.config_da_estrategia()
        except Exception as e:                     # o painel nunca cai por causa disto
            return {"ok": False, "versao": None, "hash_esperado": None, "hash_atual": None,
                    "diff": [], "motivo": f"configuracao ilegivel ({type(e).__name__})"}
    atual = hash_config(config)
    v = vigente(caminho, hoje)
    if v is None:
        return {"ok": False, "versao": None, "hash_esperado": None, "hash_atual": atual,
                "diff": [], "motivo": "nenhuma versao registrada ainda"}
    diff = diff_config(v.get("config"), config)
    ok = (v.get("hash_config") == atual)
    return {"ok": bool(ok), "versao": v.get("id"), "hash_esperado": v.get("hash_config"),
            "hash_atual": atual, "diff": diff,
            "motivo": "" if ok else
                      f"a configuracao viva difere da versao {v.get('id')} em "
                      f"{len(diff)} parametro(s), sem versao registrada"}


def resumo(caminho=ARQ_VERSOES, hoje=None, config=None):
    """Bloco `versao` do painel (ver docs/painel-contrato.md), em tipos JSON nativos."""
    hoje = pd.Timestamp(hoje or date.today())
    v = vigente(caminho, hoje)
    paralelo = em_paralelo(caminho, hoje)
    c = conferir(config, caminho, hoje)
    pode, porque = pode_mudar(hoje, caminho)
    cadeia_ok, quebra = verificar_cadeia(caminho)
    return {
        "vigente": v.get("id") if v else None,
        "descricao": v.get("descricao") if v else None,
        "desde": v.get("vigente_a_partir_de") if v else None,
        "em_paralelo": [{"id": x.get("id"), "descricao": x.get("descricao"),
                         "vale_a_partir_de": x.get("vigente_a_partir_de")}
                        for x in paralelo],
        "mudancas_no_ano": int(mudancas_no_ano(hoje.year, caminho)),
        "limite_ano": int(LIMITE_MUDANCAS_ANO),
        "pode_mudar": bool(pode),
        "motivo_bloqueio": porque or None,
        "config_confere": bool(c["ok"]),
        "divergencia": [d["campo"] for d in c["diff"]][:20],
        "aviso": c["motivo"] or None,
        "cadeia_ok": bool(cadeia_ok),
        "cadeia_quebra": quebra,
    }


def texto(caminho=ARQ_VERSOES, hoje=None):
    """O changelog legivel, para colar no relatorio mensal."""
    linhas = ["# Changelog de versoes", ""]
    hist = historico(caminho)
    if not hist:
        linhas.append("Nenhuma versao registrada. A configuracao de hoje e a linha de base;")
        linhas.append("registre a v1 antes da primeira mudanca, senao nao ha contra o que comparar.")
        return "\n".join(linhas)
    v = vigente(caminho, hoje)
    for x in hist:
        marca = " (VIGENTE)" if v and x.get("id") == v.get("id") else ""
        linhas.append(f"## {x.get('id')}{marca} — {x.get('descricao')}")
        linhas.append(f"- registrada em {str(x.get('carimbo'))[:10]}, "
                      f"vale a partir de {x.get('vigente_a_partir_de')}")
        linhas.append(f"- motivo: {x.get('motivo')}")
        for d in x.get("diff") or []:
            linhas.append(f"  - `{d['campo']}`: {d['de']} -> {d['para']}")
        if x.get("excecao"):
            linhas.append(f"- **EXCECAO A REGRA**: {x['excecao'].get('regra')}")
        linhas.append("")
    return "\n".join(linhas)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Changelog de versoes do sistema (kill 7)")
    ap.add_argument("--registrar", nargs=2, metavar=("DESCRICAO", "MOTIVO"),
                    help="registra uma versao nova a partir da configuracao viva")
    ap.add_argument("--backtest", help="JSON com a comparacao contra a versao atual")
    ap.add_argument("--forcar", action="store_true",
                    help="registra mesmo com o orcamento anual esgotado (fica gravado)")
    ap.add_argument("--conferir", action="store_true",
                    help="a configuracao viva bate com a versao vigente?")
    ap.add_argument("--texto", action="store_true", help="imprime o changelog legivel")
    args = ap.parse_args(argv)

    if args.registrar:
        try:
            bt = json.loads(args.backtest) if args.backtest else None
        except Exception:
            print("--backtest precisa ser um JSON valido")
            return 2
        try:
            linha = registrar(args.registrar[0], args.registrar[1], bt, forcar=args.forcar)
        except RuntimeError as e:
            print(f"recusado: {e}")
            return 1
        print(json.dumps({k: v for k, v in linha.items() if k != "config"},
                         indent=2, ensure_ascii=False))
        return 0
    if args.conferir:
        c = conferir()
        print(json.dumps(c, indent=2, ensure_ascii=False))
        return 0 if c["ok"] else 1
    print(texto())
    return 0


if __name__ == "__main__":
    sys.exit(main())
