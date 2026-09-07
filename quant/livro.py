"""
Livro de tentativas (registro anti-overfitting) e trava do holdout.

Por que existe: um backtest que pode ser re-rodado com outros parametros ate ficar bonito
nao e evidencia, e uma busca. O Sharpe deflacionado (Bailey & Lopez de Prado, 2014) corrige
o Sharpe medido pelo numero de tentativas, entao o numero de tentativas precisa ser
registrado com honestidade e fora do alcance de um `rm` distraido. Como quant/saida/ e
gitignored, os dois arquivos deste modulo ficam na RAIZ DO PACOTE e sao commitados:

  quant/livro_tentativas.jsonl   uma tentativa por linha, encadeada por hash;
  quant/holdout.json             a trava do periodo reservado (abre uma vez so).

O encadeamento e a primeira camada: hash = sha256(hash_anterior + canonizar(linha sem os
campos de hash)), entao apagar uma linha, editar um numero de uma linha antiga ou trocar
duas linhas de lugar quebra a verificacao e verificar_cadeia() aponta a primeira quebra.
O git e a segunda camada: os dois arquivos sao versionados, e qualquer reescrita aparece
no diff da revisao. Nenhuma das duas impede a fraude deliberada (quem reescreve a cadeia
inteira e faz force-push passa); as duas juntas impedem o auto-engano, que e o problema real.

Como usar (fase 2, no backtest):
    from quant import livro
    linha = livro.registrar(config, ("2008-01-01", "2015-12-31"), resultados,
                            "grid de momentum 12-2, tercil alto", escopo="pesquisa",
                            extras={"dados": [caminho_cotahist], "estresse": {"custos_x2": ...}})
    n = livro.n_tentativas()                       # configs DISTINTAS ja tentadas
    v = livro.variancia_sharpes()                  # V[SR] entre elas
    dsr = livro.sharpe_deflacionado(sr_mensal, n_meses, n, v, assimetria, curtose)
    # e, uma unica vez na vida do projeto, com a config congelada:
    livro.abrir_holdout(config, "estrategia pre-registrada em docs/pre-registro.md")
    livro.registrar_holdout(resultados_do_holdout)

Linha do livro (JSON, uma por linha, na ordem):
    id, carimbo, escopo, motivo, versao_codigo, hash_config, config, pin_nefin,
    impressao_dados, periodo, estresse, resultados, hash_anterior, hash

Escopos:
    teste           fixtures, CI, exemplos: NAO conta como tentativa;
    pesquisa        exploracao livre no desenvolvimento: conta;
    pre_registrado  config congelada e escrita antes de ver o resultado: conta;
    holdout         a unica passada no periodo trancado.

Suposicoes (o que este modulo assume e que o leitor precisa saber):
  - uma "tentativa" e uma CONFIG distinta: n_tentativas conta hash_config unicos, entao
    re-rodar a mesma config (crash, CI, reproducao) nao infla o N, mas mexer em UM
    parametro sim. Isso subestima o N verdadeiro se a busca acontecer fora do codigo
    (olhar o grafico e decidir na mao tambem e tentativa: registre com escopo pesquisa);
  - o SR usado em variancia_sharpes e em sharpe_deflacionado e o SR POR PERIODO (mensal),
    nunca o anualizado; misturar os dois e o erro classico e infla o DSR para perto de 1;
  - variancia_sharpes usa variancia amostral (ddof=1) sobre UM SR por config (o ultimo
    registro daquela config) e le resultados["sharpe"] (ou "sharpe_mensal");
  - carimbo em UTC (ISO, segundos). Relogio errado da carimbo errado: o que garante a
    ordem e o encadeamento, nao a hora;
  - o append reescreve o arquivo inteiro com gravar_atomico (nunca deixa linha pela
    metade). Nao ha trava entre processos: rode um backtest por vez, ou duas gravacoes
    simultaneas perdem uma linha (a ultima a gravar vence e a cadeia continua valida);
  - versao_codigo() depende do git no PATH e do repositorio presente; sem isso devolve
    commit None e sujo True (pessimista: codigo nao identificado e codigo suspeito);
  - impressao_dados() indexa pelo caminho relativo a RAIZ quando o arquivo esta no
    repositorio; arquivo ausente entra com sha256/bytes/mtime None em vez de sumir;
  - pin_nefin e preenchido sozinho com nefin.pin_ultimo("fatores") (None se nao houver
    snapshot); passe extras={"pin_nefin": ...} para fixar outro;
  - nenhuma funcao levanta por arquivo ausente: ler() devolve o DataFrame vazio com as
    COLUNAS, verificar_cadeia() devolve (True, None) e holdout_estado() devolve o estado
    inicial. Levantam so quando ha decisao errada do usuario (escopo invalido, cadeia
    quebrada, holdout ja aberto com outra config);
  - o holdout (HOLDOUT) fica fechado ate a estrategia estar pre-registrada. abrir_holdout
    registra a tentativa no livro ANTES de destravar, entao a abertura fica nas duas
    trilhas; reabrir com config diferente exige editar holdout.json a mao (e o diff fica
    no git, que e exatamente o ponto).

Linha de comando:
    python3 -m quant.livro --verificar        # 0 se a cadeia esta intacta, 1 se nao
    python3 -m quant.livro --listar
    python3 -m quant.livro --estado-holdout
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy.stats import norm

from quant.comum import DIR_QUANT, RAIZ, gravar_atomico, gravar_json, ler_json, log

ARQ_LIVRO = os.path.join(DIR_QUANT, "livro_tentativas.jsonl")
ARQ_HOLDOUT = os.path.join(DIR_QUANT, "holdout.json")
HOLDOUT = ("2016-01-01", "2026-06-30")          # periodo reservado: uma unica passada
ESCOPOS = ("teste", "pesquisa", "pre_registrado", "holdout")
ESCOPOS_QUE_CONTAM = ("pesquisa", "pre_registrado")
GAMA_EULER = 0.5772156649015329                 # constante de Euler-Mascheroni
COLUNAS = ["id", "carimbo", "escopo", "motivo", "versao_codigo", "hash_config", "config",
           "pin_nefin", "impressao_dados", "periodo", "estresse", "resultados",
           "hash_anterior", "hash"]
CAMPOS_HASH = ("hash_anterior", "hash")         # ficam FORA do corpo que e hasheado
CHAVES_SHARPE = ("sharpe", "sharpe_mensal")     # de onde sai o SR de cada tentativa
NOTA_HOLDOUT = "Abrir UMA vez. Reabrir exige editar este arquivo a mao, e o diff fica no git."
TIMEOUT_GIT = 10


# ─────────────────────────────────────────────────────────────
# Funcoes puras
# ─────────────────────────────────────────────────────────────
def canonizar(config):
    """dict -> JSON canonico: chaves ordenadas, separadores fixos, sem espacos.

    E a forma unica de um objeto: {"a": 1, "b": 2} e {"b": 2, "a": 1} dao o mesmo texto,
    entao o mesmo hash. Valores que o json nao serializa viram str() em vez de levantar.
    """
    return json.dumps(config, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def hash_config(config):
    """sha256 hex de canonizar(config): a identidade de uma tentativa."""
    return hashlib.sha256(canonizar(config).encode("utf-8")).hexdigest()


def _git(*args):
    """Saida do git (str, sem espacos nas pontas) ou None em qualquer falha."""
    try:
        r = subprocess.run(["git", *args], cwd=RAIZ, capture_output=True,
                           text=True, timeout=TIMEOUT_GIT)
    except Exception:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def versao_codigo():
    """{"commit": sha ou None, "sujo": bool} do repositorio. Nunca levanta.

    sujo=True quando ha mudanca nao commitada (o resultado nao e reproduzivel pelo sha)
    e tambem quando o git nao respondeu: codigo nao identificado conta como suspeito.
    """
    commit = _git("rev-parse", "HEAD")
    if commit is None:
        return {"commit": None, "sujo": True}
    pendente = _git("status", "--porcelain")
    return {"commit": commit, "sujo": True if pendente is None else bool(pendente)}


def _rotulo(caminho):
    """Caminho relativo a RAIZ quando dentro do repositorio; absoluto caso contrario."""
    inteiro = os.path.abspath(str(caminho))
    if inteiro.startswith(RAIZ + os.sep):
        return os.path.relpath(inteiro, RAIZ).replace(os.sep, "/")
    return str(caminho)


def impressao_dados(caminhos):
    """{arquivo: {"sha256", "bytes", "mtime"}} para os arquivos de entrada da tentativa.

    Aceita um caminho ou uma lista. Arquivo ausente ou ilegivel entra com os tres campos
    None: a ausencia tambem e informacao (e o hash da linha registra que estava ausente).
    mtime em UTC ISO. Ler o arquivo inteiro so acontece aqui, nao no resto do modulo.
    """
    if caminhos is None:
        return {}
    if isinstance(caminhos, (str, bytes, os.PathLike)):
        caminhos = [caminhos]
    out = {}
    for c in caminhos:
        rotulo = _rotulo(c)
        try:
            h = hashlib.sha256()
            with open(str(c), "rb") as f:
                for bloco in iter(lambda: f.read(1 << 20), b""):
                    h.update(bloco)
            st = os.stat(str(c))
            out[rotulo] = {
                "sha256": h.hexdigest(),
                "bytes": int(st.st_size),
                "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="seconds"),
            }
        except Exception:
            out[rotulo] = {"sha256": None, "bytes": None, "mtime": None}
    return out


def _hash_linha(linha, hash_anterior):
    """sha256(hash_anterior + canonizar(linha sem os campos de hash))."""
    corpo = {k: v for k, v in linha.items() if k not in CAMPOS_HASH}
    return hashlib.sha256((hash_anterior + canonizar(corpo)).encode("utf-8")).hexdigest()


def _periodo(periodo):
    """(ini, fim) -> ["AAAA-MM-DD", "AAAA-MM-DD"]; qualquer outra coisa passa como veio."""
    if isinstance(periodo, (tuple, list)) and len(periodo) == 2:
        return [str(periodo[0])[:10], str(periodo[1])[:10]]
    return periodo


def _sharpe_do_resultado(resultados):
    """SR mensal de um dict de resultados (CHAVES_SHARPE, a primeira presente). NaN se nao houver."""
    if not isinstance(resultados, dict):
        return float("nan")
    for k in CHAVES_SHARPE:
        if k in resultados:
            try:
                return float(resultados[k])
            except (TypeError, ValueError):
                return float("nan")
    return float("nan")


def sharpe_deflacionado(sharpe, n_periodos, n_tentativas, var_sharpes,
                        assimetria=0.0, curtose=3.0):
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014): P(SR verdadeiro > 0).

        SR0 = sqrt(V[SR]) * ((1 - g) * Phi_inv(1 - 1/N) + g * Phi_inv(1 - 1/(N*e)))
        DSR = Phi[ (SR - SR0) * sqrt(T - 1) / sqrt(1 - a*SR + ((k - 1)/4) * SR^2) ]

    g = GAMA_EULER, N = n_tentativas, T = n_periodos, a = assimetria, k = curtose (3 = normal).
    SR0 e o Sharpe que a MELHOR de N tentativas independentes atinge por sorte; DSR e a
    probabilidade de o Sharpe observado superar isso depois de corrigir por N, pelo tamanho
    da amostra e pelos momentos altos dos retornos.

    ATENCAO: `sharpe` e o SR POR PERIODO (mensal, se T conta meses), NAO o anualizado -
    passar o anualizado com T em meses e o erro classico e devolve DSR ~ 1 sempre.

    Devolve NaN, sem levantar, nos casos degenerados:
      - algum argumento nao numerico ou nao finito;
      - N <= 1 (com uma tentativa nao ha selecao a corrigir: use o Sharpe normal);
      - V[SR] <= 0 ou NaN (menos de duas tentativas registradas, ou todas com o mesmo SR);
      - T <= 1 (sem graus de liberdade);
      - radicando 1 - a*SR + ((k - 1)/4)*SR^2 <= 0 (momentos incoerentes);
      - N tao grande que Phi_inv(1 - 1/(N*e)) satura em infinito.
    """
    try:
        sr, t, n = float(sharpe), float(n_periodos), float(n_tentativas)
        v, a, k = float(var_sharpes), float(assimetria), float(curtose)
    except (TypeError, ValueError):
        return float("nan")
    if not np.isfinite([sr, t, n, v, a, k]).all():
        return float("nan")
    if n <= 1 or v <= 0 or t <= 1:
        return float("nan")
    sr0 = np.sqrt(v) * ((1.0 - GAMA_EULER) * norm.ppf(1.0 - 1.0 / n)
                        + GAMA_EULER * norm.ppf(1.0 - 1.0 / (n * np.e)))
    radicando = 1.0 - a * sr + ((k - 1.0) / 4.0) * sr * sr
    if not np.isfinite(sr0) or not np.isfinite(radicando) or radicando <= 0:
        return float("nan")
    z = (sr - sr0) * np.sqrt(t - 1.0) / np.sqrt(radicando)
    return float(norm.cdf(z))


# ─────────────────────────────────────────────────────────────
# Disco: o livro (JSONL encadeado)
# ─────────────────────────────────────────────────────────────
def _linhas_cruas(caminho):
    """Linhas nao vazias do JSONL, como texto. [] se o arquivo nao existir ou nao abrir."""
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return [linha.strip() for linha in f if linha.strip()]
    except Exception:
        return []


def verificar_cadeia(caminho=ARQ_LIVRO):
    """(ok, indice da primeira quebra). Arquivo ausente ou vazio: (True, None).

    Quebra = linha ilegivel, hash_anterior que nao aponta para o hash da linha de cima
    (linha apagada, linhas trocadas de lugar) ou hash que nao bate com o conteudo (linha
    editada). O indice e a posicao no arquivo, base 0.
    """
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


def registrar(config, periodo, resultados, motivo, escopo="pesquisa", caminho=ARQ_LIVRO,
              extras=None):
    """Anexa uma tentativa ao livro e devolve o dict gravado.

    config: os parametros da rodada (qualquer dict serializavel); e o que define a
    identidade da tentativa via hash_config. periodo: par (ini, fim) de datas ISO.
    resultados: dict com as metricas medidas - inclua "sharpe" MENSAL para o DSR.
    motivo: por que esta rodada existe, em uma frase (o campo mais importante para quem
    for ler o livro depois). escopo: um de ESCOPOS.

    extras (opcional) preenche os campos que o backtest conhece e este modulo nao:
      "dados": lista de caminhos -> vira impressao_dados; "impressao_dados": pronto;
      "pin_nefin": pin do snapshot NEFIN (default: nefin.pin_ultimo); "estresse": dict
      com as variacoes de estresse rodadas. Chaves desconhecidas entram como campos extras
      da linha (e entram no hash).

    Levanta ValueError se o escopo for invalido ou se a cadeia ja estiver quebrada -
    registrar em cima de um livro adulterado esconderia a adulteracao.
    """
    if escopo not in ESCOPOS:
        raise ValueError(f"escopo invalido: {escopo!r}; use um de {ESCOPOS}")
    ok, i = verificar_cadeia(caminho)
    if not ok:
        raise ValueError(f"cadeia quebrada na linha {i} de {caminho}: restaure o arquivo "
                         "pelo git (git checkout) antes de registrar qualquer tentativa")
    extras = dict(extras or {})
    impressao = extras.pop("impressao_dados", None)
    dados = extras.pop("dados", None)
    if impressao is None:
        impressao = impressao_dados(dados)
    pin = extras.pop("pin_nefin", None)
    if pin is None:
        pin = _pin_nefin()
    estresse = extras.pop("estresse", None)
    linhas = _linhas_cruas(caminho)
    anterior = json.loads(linhas[-1])["hash"] if linhas else ""
    linha = {
        "id": f"t{len(linhas) + 1:04d}-{uuid.uuid4().hex[:8]}",
        "carimbo": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "escopo": escopo,
        "motivo": str(motivo),
        "versao_codigo": versao_codigo(),
        "hash_config": hash_config(config),
        "config": config,
        "pin_nefin": pin,
        "impressao_dados": impressao,
        "periodo": _periodo(periodo),
        "estresse": estresse,
        "resultados": resultados,
    }
    for k, v in extras.items():
        if k not in linha and k not in CAMPOS_HASH:
            linha[k] = v
    linha["hash_anterior"] = anterior
    linha["hash"] = _hash_linha(linha, anterior)
    conteudo = "".join(x + "\n" for x in linhas) + json.dumps(linha, ensure_ascii=False) + "\n"
    gravar_atomico(caminho, conteudo)
    log(f"livro: {linha['id']} escopo={escopo} config={linha['hash_config'][:12]} ({motivo})")
    return linha


def ler(caminho=ARQ_LIVRO):
    """DataFrame com uma linha por tentativa. Arquivo ausente: DataFrame vazio com COLUNAS.

    Linhas ilegiveis sao puladas (verificar_cadeia e quem acusa a quebra). Campos extras
    gravados por extras= aparecem depois das COLUNAS.
    """
    registros = []
    for i, bruto in enumerate(_linhas_cruas(caminho)):
        try:
            r = json.loads(bruto)
        except Exception:
            log(f"livro: linha {i} ilegivel; ignorada na leitura")
            continue
        if isinstance(r, dict):
            registros.append(r)
    if not registros:
        return pd.DataFrame(columns=COLUNAS)
    df = pd.DataFrame(registros)
    for c in COLUNAS:
        if c not in df.columns:
            df[c] = None
    return df[COLUNAS + [c for c in df.columns if c not in COLUNAS]]


def _filtrar(df, escopos):
    """Recorte por escopo; escopos=None nao filtra."""
    if len(df) == 0 or escopos is None:
        return df
    return df[df["escopo"].isin(list(escopos))]


def n_tentativas(escopos=ESCOPOS_QUE_CONTAM, caminho=ARQ_LIVRO):
    """Quantas CONFIGS DISTINTAS ja foram tentadas nos escopos dados (o N do DSR).

    Re-rodar a mesma config nao conta de novo; escopo "teste" fica de fora do default.
    """
    df = _filtrar(ler(caminho), escopos)
    if len(df) == 0:
        return 0
    return int(df["hash_config"].dropna().nunique())


def variancia_sharpes(escopos=ESCOPOS_QUE_CONTAM, caminho=ARQ_LIVRO):
    """V[SR] entre as tentativas (variancia amostral, ddof=1). NaN com menos de duas.

    Um SR por config (o ultimo registro dela), lido de resultados["sharpe"], MENSAL.
    """
    df = _filtrar(ler(caminho), escopos)
    if len(df) == 0:
        return float("nan")
    df = df.assign(_sr=[_sharpe_do_resultado(r) for r in df["resultados"]])
    df = df[df["_sr"].notna()].drop_duplicates("hash_config", keep="last")
    if len(df) < 2:
        return float("nan")
    return float(np.var(df["_sr"].to_numpy(dtype=float), ddof=1))


def _pin_nefin():
    """pin do ultimo snapshot NEFIN, ou None (sem snapshot, sem rede, sem o modulo)."""
    try:
        from quant.dados import nefin
        return nefin.pin_ultimo("fatores")
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# Disco: a trava do holdout
# ─────────────────────────────────────────────────────────────
def _estado_inicial():
    return {"periodo": list(HOLDOUT), "aberto_em": None, "aberto_por": None,
            "id_tentativa": None, "hash_config": None, "resultados": None,
            "nota": NOTA_HOLDOUT}


def holdout_estado(caminho=ARQ_HOLDOUT):
    """Estado da trava. Arquivo ausente ou ilegivel: o estado inicial (fechado)."""
    estado = ler_json(caminho, None)
    if not isinstance(estado, dict):
        return _estado_inicial()
    base = _estado_inicial()
    base.update(estado)
    return base


def abrir_holdout(config, motivo, caminho=ARQ_HOLDOUT):
    """Destrava o holdout para UMA configuracao. Devolve o estado.

    Registra a tentativa no livro (escopo "holdout", com a config inteira) ANTES de gravar
    a trava: a abertura fica nas duas trilhas e o id_tentativa liga uma a outra.

    Reabrir com a MESMA config e no-op e devolve o estado guardado - assim uma rodada que
    caiu no meio pode ser retomada. Com config diferente levanta RuntimeError nomeando a
    primeira configuracao: o holdout so tem um uso, e gastar o segundo exige editar o
    arquivo a mao (o diff fica no git).
    """
    estado = holdout_estado(caminho)
    h = hash_config(config)
    if estado.get("aberto_em"):
        if estado.get("hash_config") == h:
            log(f"livro: holdout ja aberto em {estado['aberto_em']} para esta mesma config; nada a fazer")
            return estado
        raise RuntimeError(
            f"holdout JA FOI ABERTO em {estado['aberto_em']} para a configuracao "
            f"{estado.get('hash_config')} (tentativa {estado.get('id_tentativa')}, "
            f"por {estado.get('aberto_por')}); esta config e {h}. O periodo "
            f"{estado.get('periodo')} tem um unico uso: rodar de novo com outra config "
            f"transforma o holdout em mais uma amostra de pesquisa. Para insistir, edite "
            f"{caminho} a mao e explique no commit.")
    linha = registrar(config, HOLDOUT, None, motivo, escopo="holdout", caminho=ARQ_LIVRO)
    estado.update({
        "aberto_em": linha["carimbo"],
        "aberto_por": dict(linha["versao_codigo"], motivo=str(motivo)),
        "id_tentativa": linha["id"],
        "hash_config": h,
        "resultados": None,
    })
    gravar_json(caminho, estado)
    log(f"livro: HOLDOUT ABERTO {estado['periodo']} para a config {h[:12]} ({motivo})")
    return estado


def registrar_holdout(resultados, caminho=ARQ_HOLDOUT):
    """Grava o resultado da passada no holdout. Devolve o estado.

    Levanta RuntimeError se o holdout nunca foi aberto (o resultado nao teria config).
    Reescrever um resultado ja existente e permitido (rodada retomada) mas fica no log e
    no diff do git.
    """
    estado = holdout_estado(caminho)
    if not estado.get("aberto_em"):
        raise RuntimeError(f"holdout fechado em {caminho}: chame abrir_holdout(config, motivo) "
                           "antes de rodar o periodo reservado")
    if estado.get("resultados") is not None:
        log("livro: ATENCAO, substituindo um resultado de holdout ja gravado")
    estado["resultados"] = resultados
    gravar_json(caminho, estado)
    log(f"livro: resultado do holdout gravado (tentativa {estado.get('id_tentativa')})")
    return estado


# ─────────────────────────────────────────────────────────────
# Linha de comando
# ─────────────────────────────────────────────────────────────
def _resumo(caminho):
    df = ler(caminho)
    if len(df) == 0:
        return "livro vazio"
    linhas = []
    for _, r in df.iterrows():
        hc = str(r["hash_config"] or "")[:12]
        linhas.append(f"{r['id']}  {r['carimbo']}  {str(r['escopo']):14s}  {hc}  {r['motivo']}")
    return "\n".join(linhas)


def main(argv=None):
    """CLI do livro. Sai com 1 se a cadeia estiver quebrada, qualquer que seja o subcomando
    (um livro adulterado invalida tambem a listagem e o estado do holdout)."""
    ap = argparse.ArgumentParser(description="Livro de tentativas: verificacao, listagem e holdout")
    ap.add_argument("--verificar", action="store_true", help="confere o encadeamento por hash")
    ap.add_argument("--listar", action="store_true", help="lista as tentativas registradas")
    ap.add_argument("--estado-holdout", action="store_true", help="mostra a trava do holdout")
    args = ap.parse_args(argv)
    if args.listar:
        print(_resumo(ARQ_LIVRO))
    if args.estado_holdout:
        print(json.dumps(holdout_estado(ARQ_HOLDOUT), ensure_ascii=False, indent=2))
    ok, i = verificar_cadeia(ARQ_LIVRO)
    if args.verificar or not (args.listar or args.estado_holdout):
        n = n_tentativas(caminho=ARQ_LIVRO)
        v = variancia_sharpes(caminho=ARQ_LIVRO)
        estado = "ok" if ok else f"QUEBRADA na linha {i}"
        print(f"cadeia: {estado} | tentativas distintas: {n} | V[SR]: {v:.6f}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
