"""
Macrossetor por empresa (M7): CNPJ -> um bucket da taxonomia fechada SETORES.

Por que existe: o limite "no maximo 25% da carteira em um setor" so e restricao se o setor
for economicamente real. A CVM da um campo unico e grosseiro (SETOR_ATIV do
cad_cia_aberta.csv) e, pior, com um balde de escape - "Emp. Adm. Part. - Sem Setor
Principal" - onde moram justamente as holdings (Itausa, Bradespar, Ultrapar, Simpar...).
Um teto de 25% cumprido por um balde de holdings sem relacao entre si NAO e restricao
nenhuma: Itausa e risco de banco, Bradespar e risco de minerio, Ultrapar e risco de
combustivel. Por isso este modulo faz duas coisas: (a) projeta o SETOR_ATIV numa taxonomia
fechada e curta (SETORES) e (b) aceita uma sobrescrita curada por CNPJ
(setores_curados.csv) - que existe EXATAMENTE por causa do "outros".

Fontes:
  (a) cad_cia_aberta.csv da CVM (campo SETOR_ATIV), lido por identidade.ler_cadastro e ja
      carregado na tabela `identidade` (coluna `setor`, texto cru). Chave: CNPJ.
  (b) quant/dados/setores_curados.csv: curadoria manual, chave CNPJ (ou CD_CVM quando o
      CNPJ nao foi anotado). Tem prioridade sobre a CVM.
  (c) NAO se usa aqui o segmento das carteiras de indice da B3 (arquivar_b3.py): ele so
      cobre quem esta no indice hoje e nao e point-in-time - entraria com sobrevivencia.

Suposicoes (as regras foram escritas de memoria sobre a lista de SETOR_ATIV da CVM e
precisam ser conferidas contra o cad_cia_aberta.csv real):
  - o SETOR_ATIV vem de uma lista fechada da CVM, mas a grafia ja mudou ao longo do tempo;
    por isso a comparacao e por SUBSTRING sem acento e em minusculas
    (contas_cvm.normalizar_texto), nunca por igualdade;
  - a ORDEM de REGRAS importa (a primeira que casa vence) porque os textos se sobrepoem:
    "Petroquimicos e Borracha" contem "petro" e nao e petroleo; "Saneamento, Serv. Agua e
    Gas" contem "gas" e nao e petroleo; "Farmaceutico e Higiene" contem "higiene" e e saude;
  - "Emp. Adm. Part. - X" segue o X (a holding de alimentos e consumo), porque o sufixo cai
    nas mesmas regras. So a variante "Sem Setor Principal" (CATCH_ALL_CVM) cai em "outros";
  - a taxonomia e curta de proposito (13 baldes): com ~150 empresas liquidas no universo, um
    setor de tres nomes nao restringe nada. Telecomunicacoes entra em "tecnologia",
    transporte/logistica em "industria", "energia" e energia eletrica e "utilidades" e
    saneamento/agua/gas encanado;
  - o SETOR_ATIV NAO e point-in-time: o cadastro traz a classificacao de hoje, sem historico.
    A empresa que mudou de ramo fica com o setor atual em todo o backtest. E vies conhecido e
    aceito porque setor aqui e restricao de concentracao, nao sinal - mas nao use este mapa
    para nada que dependa da data;
  - setor vazio (CNPJ sem cadastro) NAO vira "outros": fica FORA do mapa, e universo.setores
    devolve None. "outros" quer dizer "a CVM classificou e a classificacao e inutil";
    ausencia quer dizer "nao sabemos". Sao coisas diferentes na hora de conferir a carteira.

A validar com dados reais (nada disto foi rodado contra a CVM ainda):
  - quantas empresas do universo caem em "outros" (passando de ~10%, a curadoria esta curta);
  - se algum SETOR_ATIV real nao casa com nenhuma regra - rodar `main` e olhar "outros";
  - se os CNPJs de setores_curados.csv existem mesmo no cadastro: foram anotados de memoria e
    um CNPJ errado nao quebra nada, apenas nao sobrescreve nada (silencioso, entao confira);
  - se financeiras() cobre o mesmo conjunto de contas_cvm.eh_financeira MAIS os casos que ela
    nao ve (intermediacao financeira, arrendamento mercantil, bolsa, securitizadora).

Uso: python -m quant.dados.setores [--identidade quant/banco/identidade.parquet]
"""
import argparse
import io
import os
import sys

import pandas as pd

from quant.dados.contas_cvm import normalizar_texto
from quant.dados.identidade import ARQ_PARQUET as ARQ_IDENTIDADE
from quant.dados.identidade import carregar_identidade, cnpj_limpo

# Taxonomia fechada. Tudo que nao casa com REGRAS vira SETOR_PADRAO.
SETORES = ("bancos", "seguros", "energia", "utilidades", "petroleo", "materiais", "industria",
           "consumo", "varejo", "saude", "imobiliario", "tecnologia", "outros")
SETOR_PADRAO = "outros"
MACROSSETORES_FINANCEIROS = ("bancos", "seguros")   # os que usam ROE no lugar de ROIC

# O balde de escape da CVM: as holdings vao todas para ca. E a razao de existir ARQ_CURADOS.
CATCH_ALL_CVM = "Emp. Adm. Part. - Sem Setor Principal"

ARQ_CURADOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "setores_curados.csv")
COLUNAS_CURADOS = ["cnpj", "cd_cvm", "setor", "fonte", "obs"]

# (bucket, substrings do SETOR_ATIV sem acento e em minusculas). A PRIMEIRA regra que casa
# vence - a ordem resolve as sobreposicoes de texto listadas no docstring.
REGRAS = (
    ("bancos", ("banc", "intermediacao financeira", "arrendamento mercantil", "credito",
                "bolsas de valores", "securitiz", "financeira")),
    ("seguros", ("segur", "resseg", "previdencia", "capitaliza")),
    ("energia", ("energia",)),
    ("utilidades", ("saneamento", "agua e gas", "gas encanado", "servicos de agua")),
    ("petroleo", ("petroleo", "gas natural")),
    ("materiais", ("petroquim", "quimic", "celulose", "metalurgia", "siderurgia", "minera",
                   "minerio", "extracao mineral", "papel", "embalagens", "madeira",
                   "reflorestamento", "borracha", "cimento", "fertilizante")),
    ("saude", ("saude", "farmac", "hospital", "medic", "odonto")),
    ("varejo", ("comercio", "varejo", "atacado")),
    ("consumo", ("alimentos", "bebidas", "fumo", "textil", "vestuario", "calcado", "couro",
                 "agricultura", "acucar", "alcool", "brinquedos", "lazer", "hospedagem",
                 "turismo", "educacao", "higiene", "pesca", "carnes")),
    ("imobiliario", ("construcao", "imobili", "incorporac", "shopping", "decoracao")),
    ("tecnologia", ("informatica", "software", "tecnologia", "telecom", "comunicacao",
                    "internet", "programas de computador")),
    ("industria", ("maquinas", "equipamentos", "veiculos", "pecas", "transporte", "logistica",
                   "aeronaut", "naval", "eletrodomestic", "eletroeletronic", "industria",
                   "locacao", "aluguel")),
)


# ─────────────────────────────────────────────────────────────
# Classificacao e montagem do mapa (puras)
# ─────────────────────────────────────────────────────────────
def normalizar_setor(setor_ativ):
    """SETOR_ATIV cru do cadastro CVM -> um bucket de SETORES (primeira regra de REGRAS que casa).

    Insensivel a acento e a caixa: o mesmo SETOR_ATIV, escrito de qualquer jeito, cai no
    mesmo bucket. Texto vazio, desconhecido ou o balde de escape da CVM (CATCH_ALL_CVM,
    'Emp. Adm. Part. - Sem Setor Principal') viram SETOR_PADRAO ('outros') - e e por isso que
    setores_curados.csv existe: 25% da carteira num balde de holdings sem relacao entre si
    nao e restricao de concentracao nenhuma.
    """
    t = normalizar_texto(setor_ativ)
    if not t or t in ("nan", "nat", "none", "-"):
        return SETOR_PADRAO
    for setor, termos in REGRAS:
        if any(termo in t for termo in termos):
            return setor
    return SETOR_PADRAO


def _bucket(texto):
    """Texto de uma linha curada -> bucket: aceita o nome do bucket ('bancos') e, se nao for
    um deles, cai nas mesmas REGRAS ('Energia Eletrica' -> energia; lixo -> outros)."""
    t = normalizar_texto(texto)
    return t if t in SETORES else normalizar_setor(t)


def _para_cd(v):
    """CD_CVM de qualquer origem (int, str, <NA>) -> int ou None. Nunca levanta."""
    try:
        if v is None or (not isinstance(v, str) and pd.isna(v)):
            return None
        s = str(v).strip()
        return int(float(s)) if s else None
    except (TypeError, ValueError):
        return None


def _mapa_cvm(df):
    """{cnpj -> bucket} das colunas (cnpj, setor) de uma identidade ou de um cadastro.
    Linhas sem CNPJ ou sem texto de setor sao ignoradas (ausencia != 'outros')."""
    if df is None or len(df) == 0 or "cnpj" not in df.columns or "setor" not in df.columns:
        return {}
    out = {}
    for cnpj, setor in zip(df["cnpj"], df["setor"]):
        chave = cnpj_limpo(cnpj)
        texto = normalizar_texto(setor)
        if not chave or not texto or texto in ("nan", "none"):
            continue
        out[chave] = normalizar_setor(texto)
    return out


def _indice_cd_cvm(*dfs):
    """{cd_cvm -> cnpj} para resolver linhas curadas que so trazem o codigo CVM."""
    idx = {}
    for df in dfs:
        if df is None or len(df) == 0 or "cnpj" not in df.columns or "cd_cvm" not in df.columns:
            continue
        for cd, cnpj in zip(df["cd_cvm"], df["cnpj"]):
            codigo, chave = _para_cd(cd), cnpj_limpo(cnpj)
            if codigo is not None and chave:
                idx[codigo] = chave
    return idx


def _mapa_curados(curados, *dfs_cnpj):
    """{cnpj -> bucket} das linhas curadas. Linha sem CNPJ usa o cd_cvm, se ele for resolvivel
    em `dfs_cnpj`; sem nenhum dos dois a linha e ignorada (nao ha em quem aplicar)."""
    if curados is None or len(curados) == 0 or "setor" not in curados.columns:
        return {}
    idx = _indice_cd_cvm(*dfs_cnpj)
    out = {}
    for r in curados.to_dict("records"):
        chave = cnpj_limpo(r.get("cnpj"))
        if not chave:
            chave = idx.get(_para_cd(r.get("cd_cvm")), "")
        if not chave:
            continue
        out[chave] = _bucket(r.get("setor"))
    return out


def mapa_setores(identidade=None, cadastro=None, curados=None):
    """{cnpj de 14 digitos -> setor de SETORES}. Prioridade: curados > CVM.

    identidade: tabela de identidade.py (colunas cnpj, cd_cvm, setor - `setor` e o SETOR_ATIV
    cru); cadastro: saida de identidade.ler_cadastro (mesmas colunas); curados: saida de
    carregar_curados(). `curados=None` LE ARQ_CURADOS (unico toque em disco desta funcao) -
    passe um DataFrame vazio para desligar a curadoria.

    Entradas vazias devolvem {} e CNPJ sem setor no cadastro fica fora do mapa: quem consulta
    (universo.setores) recebe None, que e diferente de 'outros'.
    """
    mapa = {}
    for df in (identidade, cadastro):
        mapa.update(_mapa_cvm(df))
    cur = carregar_curados() if curados is None else curados
    mapa.update(_mapa_curados(cur, identidade, cadastro))
    return mapa


def financeiras(mapa, identidade):
    """Conjunto dos CD_CVM cujo macrossetor e bancos ou seguros.

    Alimenta cvm_fundamentos.metricas(financeira=True) - ROE no lugar de ROIC, sem
    divida liquida/EBITDA - e e (de proposito) mais largo que contas_cvm.eh_financeira, que
    so enxerga 'banc'/'segur' no texto cru e perde intermediacao financeira, arrendamento
    mercantil, bolsa e securitizadora. Sem mapa ou sem identidade devolve conjunto vazio.
    """
    if not mapa or identidade is None or len(identidade) == 0:
        return set()
    if "cnpj" not in identidade.columns or "cd_cvm" not in identidade.columns:
        return set()
    out = set()
    for cnpj, cd in zip(identidade["cnpj"], identidade["cd_cvm"]):
        codigo = _para_cd(cd)
        if codigo is not None and mapa.get(cnpj_limpo(cnpj)) in MACROSSETORES_FINANCEIROS:
            out.add(codigo)
    return out


def contagem(mapa):
    """{setor -> numero de empresas}, na ordem de SETORES e com os baldes vazios em zero."""
    cont = {s: 0 for s in SETORES}
    for setor in (mapa or {}).values():
        cont[setor] = cont.get(setor, 0) + 1
    return cont


# ─────────────────────────────────────────────────────────────
# Disco
# ─────────────────────────────────────────────────────────────
def _curados_vazio():
    df = pd.DataFrame(columns=COLUNAS_CURADOS)
    df["cd_cvm"] = df["cd_cvm"].astype("Int64")
    return df


def carregar_curados(caminho=ARQ_CURADOS):
    """setores_curados.csv (';', linhas iniciadas por '#' sao comentario - nao use '#' dentro
    de obs) -> DataFrame(cnpj, cd_cvm, setor, fonte, obs).

    cnpj sai com 14 digitos; cd_cvm e Int64 (<NA> quando vazio) e so serve para achar a
    empresa quando o CNPJ nao foi anotado; setor e projetado em SETORES. Arquivo ausente,
    vazio ou so com comentarios devolve a tabela vazia com o esquema - nunca levanta.
    """
    if not os.path.exists(caminho):
        return _curados_vazio()
    with open(caminho, encoding="utf-8") as f:
        texto = "\n".join(l for l in f.read().splitlines() if l.strip() and not l.lstrip().startswith("#"))
    if not texto.strip():
        return _curados_vazio()
    df = pd.read_csv(io.StringIO(texto), sep=";", dtype=str, keep_default_na=False)
    if df.empty:
        return _curados_vazio()
    linhas = [{"cnpj": cnpj_limpo(r.get("cnpj")), "cd_cvm": _para_cd(r.get("cd_cvm")),
               "setor": _bucket(r.get("setor")), "fonte": (r.get("fonte") or "curadoria").strip(),
               "obs": (r.get("obs") or "").strip()} for r in df.to_dict("records")]
    out = pd.DataFrame(linhas, columns=COLUNAS_CURADOS)
    out["cd_cvm"] = pd.array(list(out["cd_cvm"]), dtype="Int64")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Conta as empresas por macrossetor (cadastro CVM + curadoria)")
    ap.add_argument("--identidade", default=ARQ_IDENTIDADE, help="parquet gerado por quant.dados.identidade")
    ap.add_argument("--curados", default=ARQ_CURADOS)
    args = ap.parse_args(argv)
    ident = carregar_identidade(args.identidade)
    if ident is None:
        print(f"sem identidade em {args.identidade}: rode python -m quant.dados.identidade")
    curados = carregar_curados(args.curados)
    mapa = mapa_setores(identidade=ident, curados=curados)
    cont = contagem(mapa)
    for setor in SETORES:
        print(f"{setor:12s} {cont.get(setor, 0):6d}")
    print(f"{'TOTAL':12s} {len(mapa):6d}   ({len(curados)} linha(s) de curadoria)")
    return 0 if mapa else 1


if __name__ == "__main__":
    sys.exit(main())
