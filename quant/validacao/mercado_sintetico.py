"""
Mercado artificial completo (fase 0): um "B3 de laboratorio" nos ESQUEMAS DE DISCO reais.

Por que existe: esta maquina nao tem rede para a B3, a CVM nem o BCB, entao quant/banco/
esta vazio e nenhum backtest pode ser rodado com dado de verdade. Este modulo fabrica um
mercado inteiro - cotacoes COTAHIST, proventos, DFP/ITR da CVM, identidade/cadastro,
fatores NEFIN e CDI - com os MESMOS nomes de coluna, tipos e convencoes das fontes reais,
para que o pipeline inteiro rode aqui sem uma linha alterada:

    cotahist.carregar -> universo.universo_pit -> eventos.retorno_total
                      -> painel_fundamentos.painel_ttm -> sinais -> carteira -> backtest

Como a fabrica planta uma estrutura de fatores CONHECIDA, o backtest pode ser cobrado de
duas coisas que nenhum teste unitario prova: que ele recupera um premio plantado e que
ele NAO acha nada quando nao ha nada para achar.

LIMITE HONESTO (leia antes de comemorar qualquer resultado):
  - o modelo gerador e o MESMO modelo que os sinais assumem (retorno linear em momento
    12-2, qualidade e valor, com ruido gaussiano homocedastico). Recuperar aqui o premio
    plantado prova MECANICA (alinhamento de datas, ajuste por proventos, point-in-time,
    contas, custos), nao prova EDGE: nao ha nada nestes dados que nao tenhamos colocado;
  - o teste que carrega informacao de verdade e o CONTROLE NULO: com lambda_mom =
    lambda_qual = lambda_valor = 0 nao existe premio nenhum, entao qualquer alfa POSITIVO
    que o backtest reporte nessas series e bug (look-ahead, sobreposicao de datas, ajuste
    de proventos errado, sobrevivencia, custo esquecido) - nunca "descoberta". Alfa
    NEGATIVO e o esperado assim que o backtest cobra custo de negociacao e IR de JCP: o
    motor esta pagando spread e corretagem para negociar ruido. O substrato em si e limpo -
    a carteira igualmente ponderada de tudo que existe tem alfa zero (|t| < 1) contra os
    fatores gerados, e e isso que test_mercado_sintetico cobra; um controle nulo com custo
    deve exigir "sem alfa positivo", nao "alfa igual a zero";
  - o segundo teste util e o vazamento plantado (vazar=True): publicando o balanco no
    proprio dt_refer, um backtest correto NAO deve melhorar muito; se melhorar muito, o
    codigo esta lendo o futuro em algum lugar.

Estrutura plantada (retorno DIARIO, em excesso do CDI):
    r_it - rf_t = beta_i*(Rm - Rf)_t + lam_mom*mom_{i,t-1} + lam_qual*q_i
                  + lam_valor*v_i + sigma_i*eps_it
  mom_{i,t-1}  retorno 12-2 (252 a 42 pregoes atras) padronizado na secao transversal das
               empresas vivas, fixado no primeiro pregao de cada mes e constante no mes;
  q_i, v_i     qualidade e valor da empresa, padronizados, CONSTANTES no tempo (e os mesmos
               numeros que geram margem/ROE e o earnings yield dos documentos da CVM);
  lam_*        premio DIARIO por 1 desvio-padrao da caracteristica (0,0004 ~ 10% ao ano).

Suposicoes e simplificacoes (o que este mercado NAO reproduz):
  - retornos gaussianos i.i.d. no residuo: sem caudas gordas, sem clusters de volatilidade,
    sem contagio setorial, sem correlacao entre as caracteristicas;
  - dt_receb = dt_refer + atraso_receb_dias para TODO documento; no mundo real a ITR sai em
    ~45 dias e a DFP em ~90, e o atraso varia por empresa e por ano. Os documentos comecam
    no exercicio anterior a `ini` (para haver TTM no comeco da amostra) e param no ultimo
    trimestre FECHADO ate `fim` - o dt_receb dos ultimos pode cair depois de `fim`, como na
    vida real (o documento existe mas ninguem o conhecia dentro da amostra);
  - o plano de contas e o minimo necessario (BPA/BPP/DRE/DFC_MI); nao ha DMPL/DVA, nem
    conta fora do padrao, nem empresa que muda de escopo (con/ind) no meio da amostra;
  - so DESDOBRAMENTO, BONIFICACAO, DIVIDENDO e JCP; nao ha grupamento, subscricao, cisao,
    incorporacao, mudanca de ticker nem troca de classe; o provento e uma fracao do
    fechamento do pregao anterior a data-ex, mesmo que o papel nao tenha negociado nele
    (num papel esporadico isso deixa o retorno reconstruido um pouco fora do gerado);
  - o retorno diario e truncado em (-90%, +100%) e o preco em [R$ 0,05, R$ 1 milhao]: com
    lambdas na ordem certa (0,0004 ~ 10% ao ano) nada chega perto disso, mas um lambda
    absurdo geraria preco infinito - a serie tem de continuar sendo um COTAHIST possivel.
    Quando o truncamento passa a valer o gerador AVISA no log: dali em diante a estrutura
    plantada nao vale mais como gabarito;
  - liquidez estacionaria por papel (ADTV sorteado uma vez), sem crise de liquidez;
  - a "morte" de uma empresa e o fim das cotacoes (com passagem opcional por CODBDI 08);
    nao ha OPA, resgate, nem sucessor - o que basta para cobrar sobrevivencia do backtest;
  - o CDI e uma caminhada suave entre 4% e 14% ao ano, sem reuniao de Copom nem degraus;
  - SMB e IML dos fatores sao RUIDO (nao ha tamanho nem iliquidez plantados); WML e HML sao
    construidos a partir das caracteristicas plantadas para que a atribuicao do backtest
    tenha um alvo verificavel.

Uso:
    python -m quant.validacao.mercado_sintetico --dir quant/banco_sintetico --seed 7
    python -m quant.validacao.mercado_sintetico --lambda-mom 0.0006 --n-empresas 60
    python -m quant.validacao.mercado_sintetico --vazar        # look-ahead plantado

Em teste, use instalar(monkeypatch, dados) para apontar os carregadores reais para os
dados em memoria, sem tocar em disco.
"""
import argparse
import json
import os
import sys
from contextlib import contextmanager
from datetime import date

import numpy as np
import pandas as pd

from quant.comum import DIR_QUANT, garantir_dir, log
from quant.dados import calendario, cotahist, eventos, identidade, nefin
from quant.dados import cvm_fundamentos as cf

DIR_PADRAO = os.path.join(DIR_QUANT, "banco_sintetico")   # NUNCA o banco real: dado falso nao mistura

DIAS_UTEIS_ANO = 252
CARIMBO = "1970-01-01T00:00:00-03:00"      # fixo: carimbo de captura variavel quebraria a reprodutibilidade
FONTE = "sintetico"

# ── mercado e macro ──
VOL_MERCADO_ANO = 0.24
PREMIO_MERCADO_ANO = 0.05
CDI_FAIXA = (0.04, 0.14)          # a taxa anual passeia devagar dentro desta faixa
CDI_MEIA_VIDA = 500               # pregoes: velocidade do passeio da taxa

# ── empresas ──
BETA_MEDIO, BETA_DESVIO = 1.0, 0.30
BETA_LIMITES = (0.30, 2.00)
VOL_IDIO_ANO = (0.18, 0.45)
PRECO_INICIAL = (8.0, 60.0)
PRECO_PISO = 0.05                  # preco nunca zera: preco zero significa "sem pregao" em eventos.py
# faixas de ADTV (peso, minimo, maximo) - cobrem as tres faixas de custo de custos.FAIXAS_SPREAD
FAIXAS_ADTV = ((0.25, 20e6, 250e6), (0.40, 5e6, 20e6), (0.35, 0.8e6, 5e6))
FALTA_POR_FAIXA = (0.0, 0.01, 0.05)    # probabilidade de um dia sem negocio, por faixa
FRACAO_ESPORADICA = 0.08           # empresas que negociam em ~60% dos pregoes (testam `presenca`)
FALTA_ESPORADICA = 0.40
FRACAO_ATRASADAS = 0.08            # empresas que so listam no meio da amostra (IPO)
VIDA_ATRASADAS = (0.10, 0.45)      # em que trecho da amostra a atrasada estreia
VIDA_MORTAS = (0.30, 0.88)         # em que trecho a morta para de cotar (nunca colada no fim)
PREGOES_RJ = 84                    # ~4 meses em CODBDI 08 antes do ultimo pregao
FRACAO_MORTAS_EM_RJ = 0.35         # parte das mortas que passa pela recuperacao judicial

RETORNO_LIMITES = (-0.90, 1.00)    # acao de resp. limitada nao cai mais que 100% num dia
PRECO_TETO = 1e6                   # teto de sanidade do preco (a serie tem de ser sempre finita)
JANELA_MOM = (252, 42)             # momento 12-2, em pregoes
LIMITE_Z = 3.0                     # winsorizacao das caracteristicas padronizadas

SETORES = ("Energia Eletrica", "Petroleo e Gas", "Mineracao", "Comercio Varejista",
           "Alimentos e Bebidas", "Construcao Civil", "Saude", "Papel e Celulose",
           "Transporte e Logistica", "Telecomunicacoes")
SETOR_FINANCEIRO = "Bancos"        # contas_cvm.eh_financeira casa com 'banc'
ESCALAS = ("MIL", "MIL", "MIL", "UNIDADE", "MILHAO")    # mistura, com MIL dominante

# ── proventos ──
FRACAO_PAGADORAS = 0.75
MESES_PROVENTO = (2, 5, 8, 11)     # um provento por trimestre civil
DIA_PROVENTO = 12
YIELD_TRIMESTRAL = (0.002, 0.020)
FRACAO_JCP = 0.35                  # parte das pagadoras que usa JCP em metade dos trimestres
FATOR_DESDOBRAMENTO = 2.0
FATOR_BONIFICACAO = 1.10

# ── fundamentos ──
PESOS_TRIMESTRE = (0.22, 0.24, 0.26, 0.28)     # sazonalidade: o 4T e o maior
CRESCIMENTO_RECEITA = (-0.02, 0.18)
GIRO_DIARIO = 0.004                            # ADTV / valor de mercado (ancora o tamanho da empresa)
RECEITA_SOBRE_VALOR = (0.4, 2.5)               # receita anual / valor de mercado inicial
MARGEM_BRUTA = (0.28, 0.12)                    # media, sensibilidade a q_i
MARGEM_EBIT = (0.13, 0.07)
ROE_ALVO = (0.12, 0.07)
EARNINGS_YIELD = (0.07, 0.45)                  # base e sensibilidade (exponencial) a v_i
DEPRECIACAO_SOBRE_RECEITA = 0.05
CAPEX_SOBRE_RECEITA = 0.07
ALIQUOTA = 0.34
ATRASO_RESTATEMENT_DIAS = 180                  # quando a VERSAO 2 chega depois da VERSAO 1
CORTE_RESTATEMENT = 0.25                       # a reapresentacao deixa 25% do lucro original
FRACAO_RESTATEMENT = 0.08                      # empresas que reapresentam uma DFP

# ── fatores ──
VOL_FATOR_RUIDO = 0.004                        # ruido diario de SMB/HML/WML/IML


# ─────────────────────────────────────────────────────────────
# Utilitarios puros
# ─────────────────────────────────────────────────────────────
def _rng(seed, etapa):
    """Gerador independente por etapa: mexer no codigo de uma nao desloca os sorteios da outra."""
    return np.random.default_rng([int(seed), int(etapa)])


def _padronizar(x, limite=LIMITE_Z):
    """z-score na secao transversal, winsorizado; desvio nulo devolve zeros."""
    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return x
    dp = float(np.nanstd(x))
    if not np.isfinite(dp) or dp <= 0:
        return np.zeros_like(x)
    return np.clip((x - float(np.nanmean(x))) / dp, -limite, limite)


def _log_uniforme(rng, a, b, n):
    return np.exp(rng.uniform(np.log(a), np.log(b), n))


def _codigo(i):
    """Indice -> codigo de 4 letras estavel (SAAA, SAAB, ...): e a chave de empresa do universo."""
    letras = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return "S" + letras[(i // 676) % 26] + letras[(i // 26) % 26] + letras[i % 26]


def _cnpj(i):
    """CNPJ ficticio de 14 digitos, formatado como a CVM publica."""
    d = f"{(11000000 + i * 137) % 100000000:08d}0001{(i % 90) + 10:02d}"
    return f"{d[0:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}"


def _blocos_mensais(datas):
    """[(inicio, fim_exclusivo)] dos indices de cada mes civil do calendario."""
    chave = datas.year * 100 + datas.month
    corte = np.flatnonzero(np.diff(chave)) + 1
    inicios = np.concatenate(([0], corte))
    fins = np.concatenate((corte, [len(datas)]))
    return list(zip(inicios.tolist(), fins.tolist()))


def _indice_do_dia(datas, alvo):
    """Posicao do primeiro pregao >= alvo (ou None se nao houver)."""
    pos = int(np.searchsorted(datas.values, np.datetime64(pd.Timestamp(alvo)), side="left"))
    return pos if pos < len(datas) else None


# ─────────────────────────────────────────────────────────────
# Empresas, papeis, identidade e cadastro
# ─────────────────────────────────────────────────────────────
def _empresas(n_empresas, seed, fracao_mortas, fracao_financeiras, datas,
              lambda_qual, lambda_valor):
    """Uma linha por empresa com toda a verdade: cargas, liquidez, setor, vida e escopo."""
    rng = _rng(seed, 1)
    n = int(n_empresas)
    n_d = len(datas)
    idx = np.arange(n)

    beta = np.clip(rng.normal(BETA_MEDIO, BETA_DESVIO, n), *BETA_LIMITES)
    q = _padronizar(rng.normal(0.0, 1.0, n))
    v = _padronizar(rng.normal(0.0, 1.0, n))
    sigma = rng.uniform(*VOL_IDIO_ANO, n) / np.sqrt(DIAS_UTEIS_ANO)
    preco0 = rng.uniform(*PRECO_INICIAL, n)

    faixa = rng.choice(len(FAIXAS_ADTV), size=n, p=[f[0] for f in FAIXAS_ADTV])
    adtv = np.array([_log_uniforme(rng, FAIXAS_ADTV[k][1], FAIXAS_ADTV[k][2], 1)[0] for k in faixa])
    falta = np.array([FALTA_POR_FAIXA[k] for k in faixa])
    esporadicas = rng.choice(n, size=int(round(FRACAO_ESPORADICA * n)), replace=False)
    falta[esporadicas] = FALTA_ESPORADICA

    financeira = np.zeros(n, dtype=bool)
    financeira[rng.choice(n, size=int(round(fracao_financeiras * n)), replace=False)] = True
    setor = np.array([SETOR_FINANCEIRO if financeira[i] else SETORES[i % len(SETORES)] for i in idx])

    # vida: algumas listam depois do inicio (IPO) e uma fracao para de cotar no meio
    i_ini = np.zeros(n, dtype=int)
    atrasadas = rng.choice(n, size=int(round(FRACAO_ATRASADAS * n)), replace=False)
    i_ini[atrasadas] = rng.integers(int(VIDA_ATRASADAS[0] * n_d), int(VIDA_ATRASADAS[1] * n_d),
                                    size=len(atrasadas))
    i_fim = np.full(n, n_d - 1, dtype=int)
    mortas = rng.choice(n, size=int(round(fracao_mortas * n)), replace=False)
    i_fim[mortas] = rng.integers(int(VIDA_MORTAS[0] * n_d), int(VIDA_MORTAS[1] * n_d), size=len(mortas))
    i_fim = np.maximum(i_fim, i_ini + PREGOES_RJ + 21)
    i_fim = np.minimum(i_fim, n_d - 1)
    em_rj = np.zeros(n, dtype=bool)
    if len(mortas):
        n_rj = max(1, int(round(FRACAO_MORTAS_EM_RJ * len(mortas))))
        em_rj[np.sort(mortas)[:n_rj]] = True

    escopo = np.where(rng.random(n) < 0.80, "con", "ind")
    escala = np.array([ESCALAS[i % len(ESCALAS)] for i in idx])

    # "vencedora": empresa no tercil alto da carga constante plantada (vazia se nao ha premio)
    carga = lambda_qual * q + lambda_valor * v
    if np.allclose(carga, 0.0):
        vencedora = np.zeros(n, dtype=bool)
    else:
        vencedora = carga >= np.quantile(carga, 2.0 / 3.0)

    emp = pd.DataFrame({
        "empresa": [_codigo(i) for i in idx],
        "cnpj": [_cnpj(i) for i in idx],                       # formatado, como a CVM publica
        "cnpj_num": [identidade.cnpj_limpo(_cnpj(i)) for i in idx],   # so digitos, como a identidade
        "cd_cvm": 10000 + 3 * idx,
        "denominacao": [f"SINTETICA {_codigo(i)} S.A." for i in idx],
        "setor": setor, "financeira": financeira, "escopo": escopo, "escala": escala,
        "beta": beta, "q": q, "v": v, "sigma": sigma, "preco0": preco0,
        "adtv": adtv, "faixa_adtv": faixa, "prob_falta": falta,
        "i_ini": i_ini, "i_fim": i_fim, "em_rj": em_rj, "vencedora": vencedora,
    })
    emp["data_ini"] = [datas[i] for i in emp["i_ini"]]
    emp["data_fim"] = [datas[i] if i < n_d - 1 else pd.NaT for i in emp["i_fim"]]
    return emp


def _papeis(emp, fracao_pares_on_pn, seed):
    """Uma linha por TICKER. fracao_pares_on_pn das empresas ganham ON (3) e PN (4) com o
    mesmo CNPJ: e o que cobra a regra 'uma classe por empresa' do universo."""
    rng = _rng(seed, 2)
    n = len(emp)
    com_pn = np.zeros(n, dtype=bool)
    com_pn[rng.choice(n, size=int(round(fracao_pares_on_pn * n)), replace=False)] = True
    linhas = []
    for i, e in emp.reset_index(drop=True).iterrows():
        for classe, sufixo, trecho in (("ON", "3", "ACNOR"), ("PN", "4", "ACNPR")):
            if classe == "PN" and not com_pn[i]:
                continue
            fator_liq = 1.0 if classe == "ON" else float(rng.uniform(0.15, 0.60))
            linhas.append({
                "ticker": f"{e['empresa']}{sufixo}", "empresa": e["empresa"], "classe": classe,
                "isin": f"BR{e['empresa']}{trecho}{i % 10}", "cnpj": e["cnpj"],
                "cnpj_num": e["cnpj_num"], "cd_cvm": e["cd_cvm"],
                "nome": e["empresa"][:12], "especi": f"{classe:<8}NM"[:10],
                "beta": e["beta"], "q": e["q"], "v": e["v"],
                "sigma": e["sigma"] * (1.0 if classe == "ON" else float(rng.uniform(1.0, 1.4))),
                "preco0": e["preco0"] * (1.0 if classe == "ON" else float(rng.uniform(0.7, 1.1))),
                "adtv": e["adtv"] * fator_liq, "prob_falta": e["prob_falta"],
                "i_ini": e["i_ini"], "i_fim": e["i_fim"], "em_rj": e["em_rj"],
                "financeira": e["financeira"], "setor": e["setor"], "vencedora": e["vencedora"],
                "data_ini": e["data_ini"], "data_fim": e["data_fim"],
            })
    pap = pd.DataFrame(linhas).sort_values("ticker").reset_index(drop=True)
    emp = emp.copy()
    emp["ticker_on"] = emp["empresa"] + "3"
    emp["ticker_pn"] = np.where(com_pn, emp["empresa"] + "4", None)
    return emp, pap


def _identidade(emp, pap):
    """Tabela identidade.COLUNAS (uma vigencia por ticker) e cadastro no formato ler_cadastro."""
    ident = pd.DataFrame({
        "ticker": pap["ticker"], "isin": pap["isin"], "cnpj": pap["cnpj"].map(identidade.cnpj_limpo),
        "cd_cvm": pd.array(pap["cd_cvm"], dtype="Int64"),
        "denominacao": [f"SINTETICA {e} S.A." for e in pap["empresa"]],
        "setor": pap["setor"], "mercado": "Bolsa",
        "data_ini": pd.to_datetime(pap["data_ini"]), "data_fim": pd.to_datetime(pap["data_fim"]),
        "fonte": FONTE,
    })[identidade.COLUNAS].reset_index(drop=True)
    cadastro = pd.DataFrame({
        "cnpj": emp["cnpj"].map(identidade.cnpj_limpo),
        "cd_cvm": pd.array(emp["cd_cvm"], dtype="Int64"),
        "denominacao": emp["denominacao"],
        "situacao": np.where(emp["data_fim"].isna(), "ATIVO", "CANCELADA"),
        "setor": emp["setor"],
        "data_reg": pd.to_datetime(emp["data_ini"]),
        "data_cancel": pd.to_datetime(emp["data_fim"]),
    }).reset_index(drop=True)
    return ident, cadastro


# ─────────────────────────────────────────────────────────────
# Macro, retornos e caracteristicas
# ─────────────────────────────────────────────────────────────
def _macro(n_d, seed):
    """(rf, rm): CDI diario (taxa anual em passeio suave) e excesso de mercado diario."""
    rng = _rng(seed, 3)
    z = rng.normal(0.0, 1.0, n_d)
    passeio = np.zeros(n_d)
    alfa = 1.0 / CDI_MEIA_VIDA
    for t in range(1, n_d):
        passeio[t] = (1 - alfa) * passeio[t - 1] + np.sqrt(alfa) * z[t]
    meio = 0.5 * (CDI_FAIXA[0] + CDI_FAIXA[1])
    amplitude = 0.5 * (CDI_FAIXA[1] - CDI_FAIXA[0])
    taxa_ano = meio + amplitude * np.tanh(passeio)
    rf = (1.0 + taxa_ano) ** (1.0 / DIAS_UTEIS_ANO) - 1.0
    vol = VOL_MERCADO_ANO / np.sqrt(DIAS_UTEIS_ANO)
    rm = PREMIO_MERCADO_ANO / DIAS_UTEIS_ANO + vol * rng.normal(0.0, 1.0, n_d)
    return rf, rm


def _retornos(pap, datas, rf, rm, lambda_mom, lambda_qual, lambda_valor, seed):
    """Matriz (pregao x papel) de retornos totais diarios com a estrutura plantada.

    O momento e recursivo (o retorno de hoje depende do retorno acumulado de 12 a 2 meses
    atras), entao a geracao anda mes a mes: no primeiro pregao do mes calcula-se o 12-2
    padronizado entre os papeis VIVOS e ele fica fixo ate o fim do mes.
    """
    rng = _rng(seed, 4)
    n_d, n_t = len(datas), len(pap)
    beta = pap["beta"].to_numpy(float)
    q = pap["q"].to_numpy(float)
    v = pap["v"].to_numpy(float)
    sigma = pap["sigma"].to_numpy(float)
    i_ini = pap["i_ini"].to_numpy(int)
    i_fim = pap["i_fim"].to_numpy(int)

    eps = rng.normal(0.0, 1.0, size=(n_d, n_t))
    R = np.zeros((n_d, n_t))
    mom = np.zeros((n_d, n_t))
    logacum = np.zeros((n_d + 1, n_t))
    janela_longa, janela_curta = JANELA_MOM
    linhas_carac = []
    truncados = 0
    for s, e in _blocos_mensais(datas):
        vivos = (i_ini <= s) & (i_fim >= s)
        z = np.zeros(n_t)
        if s >= janela_longa:
            bruto = logacum[s - janela_curta] - logacum[s - janela_longa]
            vivos_antes = vivos & (i_ini <= s - janela_longa)
            if vivos_antes.sum() >= 3:
                z[vivos_antes] = _padronizar(bruto[vivos_antes])
        mom[s:e, :] = z
        bloco = (rf[s:e, None] + beta[None, :] * rm[s:e, None]
                 + lambda_mom * z[None, :] + lambda_qual * q[None, :] + lambda_valor * v[None, :]
                 + sigma[None, :] * eps[s:e, :])
        # o retorno de uma acao vive em (-100%, +inf): sem este limite um lambda absurdo
        # geraria preco negativo/infinito e a serie deixaria de ser um COTAHIST possivel
        truncados += int(((bloco < RETORNO_LIMITES[0]) | (bloco > RETORNO_LIMITES[1])).sum())
        bloco = np.clip(bloco, *RETORNO_LIMITES)
        R[s:e, :] = bloco
        logacum[s + 1:e + 1] = logacum[s] + np.cumsum(np.log1p(bloco), axis=0)
        linhas_carac.append(pd.DataFrame({
            "data": datas[s], "ano_mes": int(datas[s].year * 100 + datas[s].month),
            "ticker": pap["ticker"].to_numpy(), "mom": z, "q": q, "v": v, "vivo": vivos,
        }))
    if truncados > 0.001 * n_d * n_t:
        log(f"mercado sintetico: {truncados} retornos diarios truncados em {RETORNO_LIMITES} - "
            f"os lambdas sao premios DIARIOS por desvio-padrao (0,0004 ~ 10% ao ano) e a "
            f"estrutura plantada ja nao vale como gabarito neste tamanho")
    carac = pd.concat(linhas_carac, ignore_index=True)
    return R, mom, carac


# ─────────────────────────────────────────────────────────────
# Eventos corporativos e precos NAO ajustados
# ─────────────────────────────────────────────────────────────
def _agenda_eventos(pap, datas, seed):
    """Matrizes Y (yield na data-ex) e F (fator de quantidade) e a agenda dos eventos.

    Os proventos entram como fracao do preco do dia anterior, o que permite gerar o preco
    fechado em forma vetorial: P_t = P_{t-1} * (1 + r_t - y_t) / f_t. Isso faz a tabela de
    eventos e a serie de precos concordarem por construcao - retorno_total devolve
    exatamente o retorno gerado, e um fator errado aparece na hora.
    """
    rng = _rng(seed, 5)
    n_d, n_t = len(datas), len(pap)
    Y = np.zeros((n_d, n_t))
    F = np.ones((n_d, n_t))
    agenda = []
    i_ini = pap["i_ini"].to_numpy(int)
    i_fim = pap["i_fim"].to_numpy(int)
    paga = rng.random(n_t) < FRACAO_PAGADORAS
    usa_jcp = rng.random(n_t) < FRACAO_JCP
    anos = sorted({int(a) for a in datas.year})
    for j in range(n_t):
        if not paga[j]:
            continue
        for ano in anos:
            for k, mes in enumerate(MESES_PROVENTO):
                pos = _indice_do_dia(datas, date(ano, mes, DIA_PROVENTO))
                if pos is None or pos <= i_ini[j] or pos > i_fim[j]:
                    continue
                y = float(_log_uniforme(rng, *YIELD_TRIMESTRAL, 1)[0])
                tipo = "JCP" if (usa_jcp[j] and k % 2 == 1) else "DIVIDENDO"
                Y[pos, j] += y
                agenda.append({"j": j, "pos": pos, "tipo": tipo, "yield": y, "fator": float("nan")})
    # um desdobramento 1:2 e uma bonificacao de 10%, em papeis liquidos e vivos no meio da amostra
    meio = n_d // 2
    liquidos = [j for j in range(n_t)
                if pap["classe"].iloc[j] == "ON" and pap["prob_falta"].iloc[j] == 0.0
                and i_ini[j] < meio - 260 and i_fim[j] > meio + 260]
    if len(liquidos) < 2:
        liquidos = [j for j in range(n_t) if i_ini[j] < meio and i_fim[j] > meio][:2]
    especiais = {}
    for nome, (tipo, fator, desloc) in {
        "desdobramento": ("DESDOBRAMENTO", FATOR_DESDOBRAMENTO, 0),
        "bonificacao": ("BONIFICACAO", FATOR_BONIFICACAO, 63),
    }.items():
        if not liquidos:
            continue
        j = liquidos[0] if nome == "desdobramento" else liquidos[min(1, len(liquidos) - 1)]
        pos = min(meio + desloc, i_fim[j])
        F[pos, j] *= fator
        agenda.append({"j": j, "pos": pos, "tipo": tipo, "yield": 0.0, "fator": fator})
        especiais[nome] = {"ticker": pap["ticker"].iloc[j], "data_ex": datas[pos], "fator": fator}
    return Y, F, agenda, especiais


def _precos(pap, R, Y, F, seed):
    """(fec, negociou): matriz de fechamentos NAO ajustados e mascara de dias com negocio."""
    rng = _rng(seed, 6)
    n_d, n_t = R.shape
    i_ini = pap["i_ini"].to_numpy(int)
    i_fim = pap["i_fim"].to_numpy(int)
    # acumulacao em LOG: 17 anos de cumprod estouram para inf com premios grandes, e um
    # preco inf/NaN nao e um preco - a serie precisa continuar sendo um COTAHIST possivel
    log_fator = np.log(np.maximum(1.0 + R - Y, 1e-6)) - np.log(F)
    log_acum = np.cumsum(log_fator, axis=0)
    base = log_acum[i_ini, np.arange(n_t)]
    log_preco = np.log(pap["preco0"].to_numpy(float))[None, :] + log_acum - base[None, :]
    fec = np.round(np.exp(np.clip(log_preco, np.log(PRECO_PISO), np.log(PRECO_TETO))), 2)
    fec = np.clip(fec, PRECO_PISO, PRECO_TETO)
    vivo = (np.arange(n_d)[:, None] >= i_ini[None, :]) & (np.arange(n_d)[:, None] <= i_fim[None, :])
    negociou = vivo & (rng.random((n_d, n_t)) >= pap["prob_falta"].to_numpy(float)[None, :])
    negociou[i_ini, np.arange(n_t)] = True          # o primeiro e o ultimo pregao existem sempre
    negociou[i_fim, np.arange(n_t)] = True
    return fec, negociou


def _cotacoes(pap, datas, fec, negociou, seed):
    """Painel no formato exato de cotahist.parse (mesmas colunas, mesmos tipos)."""
    rng = _rng(seed, 7)
    n_d, n_t = fec.shape
    codbdi = np.full((n_d, n_t), "02", dtype=object)
    i_fim = pap["i_fim"].to_numpy(int)
    for j in np.flatnonzero(pap["em_rj"].to_numpy(bool)):
        codbdi[max(0, i_fim[j] - PREGOES_RJ):i_fim[j] + 1, j] = "08"
    td, tj = np.nonzero(negociou)
    n = len(td)
    f = fec[td, tj]
    amplitude = np.abs(rng.normal(0.0, 0.012, n))
    maximo = np.round(f * (1 + amplitude), 2)
    minimo = np.round(np.maximum(f * (1 - amplitude), PRECO_PISO), 2)
    abertura = np.round((maximo + minimo) / 2.0, 2)
    volume = np.round(pap["adtv"].to_numpy(float)[tj] * np.exp(rng.normal(-0.18, 0.60, n)), 2)
    datas_dia = np.array([d.date() for d in datas], dtype=object)
    out = pd.DataFrame({
        "data": datas_dia[td],
        "codbdi": codbdi[td, tj],
        "ticker": pap["ticker"].to_numpy()[tj],
        "tpmerc": "010",
        "nome": pap["nome"].to_numpy()[tj],
        "especi": pap["especi"].to_numpy()[tj],
        "prazot": "",
        "moeda": "R$",
        "abe": abertura, "max": maximo, "min": minimo,
        "med": np.round((maximo + minimo) / 2.0, 2), "fec": f,
        "bid": np.round(np.maximum(f - 0.01, PRECO_PISO), 2), "ask": np.round(f + 0.01, 2),
        "negocios": pd.array(np.maximum(1, (volume / 45000.0).astype(np.int64)), dtype="Int64"),
        "qtd": pd.array((volume / np.maximum(f, PRECO_PISO)).astype(np.int64), dtype="Int64"),
        "volume": volume,
        "preexe": 0.0, "indopc": "0",
        "datven": pd.Series(pd.NaT, index=range(n), dtype="datetime64[ns]"),
        "fatcot": pd.array(np.ones(n, dtype=np.int64), dtype="Int64"),
        "ptoexe": 0.0,
        "isin": pap["isin"].to_numpy()[tj],
        "dismes": pd.array(np.zeros(n, dtype=np.int64), dtype="Int64"),
    })
    return out.sort_values(["data", "ticker"]).reset_index(drop=True)


def _tabela_eventos(agenda, pap, datas, fec):
    """Agenda -> tabela eventos.COLUNAS, com o provento em reais por acao (base pre-evento)."""
    linhas = []
    for a in agenda:
        j, pos = a["j"], a["pos"]
        anterior = max(pos - 1, 0)
        valor = a["yield"] * float(fec[anterior, j]) if a["yield"] else float("nan")
        linhas.append({
            "ticker": pap["ticker"].iloc[j], "tipo": a["tipo"],
            "data_com": datas[anterior], "data_ex": datas[pos],
            "valor": valor, "fator": a["fator"],
            "data_aprov": datas[anterior] - pd.Timedelta(days=20),
            "fonte": FONTE, "carimbo": CARIMBO, "obs": "mercado sintetico",
        })
    if not linhas:
        return pd.DataFrame(columns=eventos.COLUNAS)
    df = pd.DataFrame(linhas, columns=eventos.COLUNAS)
    for c in ("data_com", "data_ex", "data_aprov"):
        df[c] = pd.to_datetime(df[c])
    df["valor"] = pd.to_numeric(df["valor"])
    df["fator"] = pd.to_numeric(df["fator"])
    return df.sort_values(["ticker", "data_ex", "tipo"]).reset_index(drop=True)


# ─────────────────────────────────────────────────────────────
# Fundamentos CVM (DFP anual + ITR trimestral, no layout dos dados abertos)
# ─────────────────────────────────────────────────────────────
FIM_TRI = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
INI_TRI = {1: "01-01", 2: "04-01", 3: "07-01", 4: "10-01"}


def _serie_anual(e, ano, ano0):
    """Numeros ANUAIS da empresa no exercicio `ano`, coerentes com q_i (qualidade) e v_i (valor)."""
    g = float(np.clip(CRESCIMENTO_RECEITA[0] + (CRESCIMENTO_RECEITA[1] - CRESCIMENTO_RECEITA[0])
                      * (0.5 + 0.25 * e["q"]), -0.05, 0.25))
    receita = float(e["_receita0"]) * (1.0 + g) ** (ano - ano0)
    mb = float(np.clip(MARGEM_BRUTA[0] + MARGEM_BRUTA[1] * e["q"], 0.06, 0.65))
    me = float(np.clip(MARGEM_EBIT[0] + MARGEM_EBIT[1] * e["q"], 0.02, 0.40))
    lucro_bruto = receita * mb
    ebit = receita * me
    financeiro = -0.02 * receita
    lucro = (ebit + financeiro) * (1 - ALIQUOTA)
    dep = receita * DEPRECIACAO_SOBRE_RECEITA
    fco = ebit * 0.85 + dep
    capex = -receita * CAPEX_SOBRE_RECEITA
    roe = float(np.clip(ROE_ALVO[0] + ROE_ALVO[1] * e["q"], 0.02, 0.40))
    pl = max(lucro, 1.0) / roe
    return {"receita": receita, "lucro_bruto": lucro_bruto, "ebit": ebit, "financeiro": financeiro,
            "lucro": lucro, "dep": dep, "fco": fco, "capex": capex, "pl": pl,
            "ativo": pl * float(e["_ativo_mult"]), "caixa": pl * 0.10, "aplicacoes": pl * 0.05,
            "cp": pl * 0.20, "lp": pl * 0.55}


def _linhas_documento(e, ano, tri, versao, dt_receb, anual, corte):
    """Um documento (ITR se tri<4, DFP se tri==4): indice + DRE/DFC acumulados + balanco.

    Os textos de DS_CONTA carregam acento de proposito: e assim que a CVM publica (latin-1).
    """
    tipo = "DFP" if tri == 4 else "ITR"
    escopo = str(e["escopo"])
    escala = str(e["escala"])
    fator_escala = cf.ESCALAS[escala]
    dt_refer = f"{ano}-{FIM_TRI[tri]}"
    pesos = np.cumsum(PESOS_TRIMESTRE)
    fatia = float(pesos[tri - 1])
    base = dict(CNPJ_CIA=e["cnpj"], DT_REFER=dt_refer, VERSAO=versao, DENOM_CIA=e["denominacao"],
                CD_CVM=int(e["cd_cvm"]), MOEDA="REAL", ESCALA_MOEDA=escala, ORDEM_EXERC="ÚLTIMO",
                DT_INI_EXERC=f"{ano}-01-01", DT_FIM_EXERC=dt_refer, ST_CONTA_FIXA="S")
    indice = [dict(CNPJ_CIA=e["cnpj"], DT_REFER=dt_refer, VERSAO=versao, DENOM_CIA=e["denominacao"],
                   CD_CVM=int(e["cd_cvm"]), CATEG_DOC=tipo, ID_DOC=f"{int(e['cd_cvm'])}{ano}{tri}{versao}",
                   DT_RECEB=dt_receb, LINK_DOC="http://sintetico")]

    def linha(cod, desc, valor_reais, grupo, **kw):
        div = 1.0 if cod.startswith("3.99") else fator_escala
        d = dict(base, GRUPO_DFP=grupo, CD_CONTA=cod, DS_CONTA=desc, VL_CONTA=f"{valor_reais / div:.2f}")
        d.update(kw)
        return d

    def dre_dfc(acumulado, ini_exerc, fim_exerc, corte_lucro):
        """Bloco DRE+DFC de um periodo (acumulado do exercicio ou trimestre isolado)."""
        receita = anual["receita"] * acumulado
        lucro = anual["lucro"] * acumulado * corte_lucro
        ebit = anual["ebit"] * acumulado * corte_lucro
        extra = dict(DT_INI_EXERC=ini_exerc, DT_FIM_EXERC=fim_exerc)
        dre = [linha("3.01", "Receita de Venda de Bens e/ou Serviços", receita, "DRE", **extra)]
        if not bool(e["financeira"]):        # banco nao tem 3.03: o resultado bruto nao existe
            dre.append(linha("3.03", "Resultado Bruto", anual["lucro_bruto"] * acumulado, "DRE", **extra))
        dre += [
            linha("3.05", "Resultado Antes do Resultado Financeiro e dos Tributos", ebit, "DRE", **extra),
            linha("3.06", "Resultado Financeiro", anual["financeiro"] * acumulado, "DRE", **extra),
            linha("3.11" if escopo == "con" else "3.09",
                  "Lucro/Prejuízo Consolidado do Período" if escopo == "con" else "Lucro/Prejuízo do Período",
                  lucro, "DRE", **extra),
            linha("3.99", "Lucro por Ação - (Reais / Ação)", 0.0, "DRE", **extra),
            linha("3.99.01", "Lucro Básico por Ação", 0.0, "DRE", **extra),
            linha("3.99.01.01", "ON", lucro / float(e["n_acoes"]), "DRE", **extra),
        ]
        dfc = [
            linha("6.01", "Caixa Líquido Atividades Operacionais", anual["fco"] * acumulado, "DFC", **extra),
            linha("6.01.01", "Caixa Gerado nas Operações", anual["fco"] * acumulado * 1.05, "DFC", **extra),
            linha("6.01.01.01", "Lucro Líquido do Período", lucro, "DFC", **extra),
            linha("6.01.01.02", "Depreciação e Amortização", anual["dep"] * acumulado, "DFC", **extra),
            linha("6.02", "Caixa Líquido Atividades de Investimento", anual["capex"] * acumulado * 1.15,
                  "DFC", **extra),
            linha("6.02.01", "Aquisição de Imobilizado", anual["capex"] * acumulado, "DFC", **extra),
            linha("6.02.02", "Aplicações Financeiras", anual["capex"] * acumulado * 0.15, "DFC", **extra),
        ]
        return dre, dfc

    dre, dfc = dre_dfc(fatia, f"{ano}-01-01", dt_refer, corte)
    if tri in (2, 3):
        # o ITR real traz TAMBEM o trimestre isolado; trimestralizar() precisa ignora-lo
        iso = float(PESOS_TRIMESTRE[tri - 1])
        d2, f2 = dre_dfc(iso, f"{ano}-{INI_TRI[tri]}", dt_refer, corte)
        dre, dfc = dre + d2, dfc + f2
    bpa = [linha("1", "Ativo Total", anual["ativo"], "BPA"),
           linha("1.01", "Ativo Circulante", anual["ativo"] * 0.45, "BPA"),
           linha("1.01.01", "Caixa e Equivalentes de Caixa", anual["caixa"], "BPA"),
           linha("1.01.02", "Aplicações Financeiras", anual["aplicacoes"], "BPA"),
           linha("1", "Ativo Total", anual["ativo"] * 0.9, "BPA",
                 ORDEM_EXERC="PENÚLTIMO", DT_FIM_EXERC=f"{ano - 1}-12-31")]
    bpp = [linha("2.01", "Passivo Circulante", anual["cp"] * 2.0, "BPP"),
           linha("2.01.04", "Empréstimos e Financiamentos", anual["cp"], "BPP"),
           linha("2.02.01", "Empréstimos e Financiamentos", anual["lp"], "BPP"),
           linha("2.03", "Patrimônio Líquido Consolidado", anual["pl"], "BPP")]
    for l in bpa + bpp:
        l.pop("DT_INI_EXERC", None)
    demos = {("DRE", escopo): dre, ("DFC_MI", escopo): dfc, ("BPA", escopo): bpa, ("BPP", escopo): bpp}
    return tipo, ano, indice, demos


def _fundamentos(emp, datas, atraso_receb_dias, vazar, restatement, seed):
    """DFP/ITR de todas as empresas -> zips no layout da CVM -> cf.parse_zip (esquema garantido)."""
    rng = _rng(seed, 8)
    ano_ini = int(datas[0].year) - 1
    ano_fim = int(datas[-1].year)
    ultimo_pregao = pd.Timestamp(datas[-1])
    emp = emp.copy()
    # tamanho: receita anual ancorada no valor de mercado inicial; o numero de acoes fixa o LPA
    # e o earnings yield - e por ele que v_i (valor) entra nos documentos da CVM
    emp["_valor0"] = emp["adtv"] / GIRO_DIARIO                      # ADTV ~ 0,4% do valor de mercado
    emp["_receita0"] = emp["_valor0"] * _log_uniforme(rng, *RECEITA_SOBRE_VALOR, len(emp))
    emp["_ativo_mult"] = rng.uniform(1.8, 3.2, len(emp))
    ey = EARNINGS_YIELD[0] * np.exp(EARNINGS_YIELD[1] * emp["v"].to_numpy(float))
    lucro0 = np.array([_serie_anual(e, ano_ini, ano_ini)["lucro"] for _, e in emp.iterrows()])
    emp["n_acoes"] = np.maximum(lucro0 / (ey * emp["preco0"].to_numpy(float)), 1.0)
    n_rest = max(1, int(round(FRACAO_RESTATEMENT * len(emp)))) if restatement else 0
    candidatas = emp.index[~emp["financeira"].to_numpy(bool)]
    reapresentam = set(candidatas[:n_rest]) if n_rest else set()
    ano_rest = ano_ini + max(1, (ano_fim - ano_ini) // 2)
    docs, restatements = [], []
    for i, e in emp.iterrows():
        primeiro = int(pd.Timestamp(e["data_ini"]).year) - 1
        ultimo = ano_fim if pd.isna(e["data_fim"]) else int(pd.Timestamp(e["data_fim"]).year)
        for ano in range(max(ano_ini, primeiro), min(ano_fim, ultimo) + 1):
            anual = _serie_anual(e, ano, ano_ini)
            for tri in (1, 2, 3, 4):
                dt_refer = pd.Timestamp(f"{ano}-{FIM_TRI[tri]}")
                if dt_refer > ultimo_pregao:     # exercicio que ainda nao fechou quando a amostra acaba
                    continue
                receb = dt_refer if vazar else dt_refer + pd.Timedelta(days=int(atraso_receb_dias))
                docs.append(_linhas_documento(e, ano, tri, 1, receb.date().isoformat(), anual, 1.0))
            if i in reapresentam and ano == ano_rest and pd.Timestamp(f"{ano}-12-31") <= ultimo_pregao:
                dt_refer = pd.Timestamp(f"{ano}-12-31")
                r1 = dt_refer if vazar else dt_refer + pd.Timedelta(days=int(atraso_receb_dias))
                r2 = r1 if vazar else r1 + pd.Timedelta(days=ATRASO_RESTATEMENT_DIAS)
                docs.append(_linhas_documento(e, ano, 4, 2, r2.date().isoformat(), anual,
                                              CORTE_RESTATEMENT))
                restatements.append({"cd_cvm": int(e["cd_cvm"]), "empresa": e["empresa"],
                                     "dt_refer": dt_refer, "dt_receb_v1": r1, "dt_receb_v2": r2,
                                     "lucro_ttm_v1": anual["lucro"],
                                     "lucro_ttm_v2": anual["lucro"] * CORTE_RESTATEMENT,
                                     "roe_v1": anual["lucro"] / anual["pl"],
                                     "roe_v2": anual["lucro"] * CORTE_RESTATEMENT / anual["pl"]})
    grupos = {}
    for tipo, ano, indice, demos in docs:
        g = grupos.setdefault((tipo, ano), {"indice": [], "demos": {}})
        g["indice"] += indice
        for k, linhas in demos.items():
            g["demos"].setdefault(k, []).extend(linhas)
    partes = [cf.parse_zip(cf.montar_zip(tipo, ano, g["indice"], g["demos"]), tipo)
              for (tipo, ano), g in sorted(grupos.items())]
    fund = pd.concat(partes, ignore_index=True) if partes else cf._vazio()
    rest = pd.DataFrame(restatements) if restatements else pd.DataFrame(
        columns=["cd_cvm", "empresa", "dt_refer", "dt_receb_v1", "dt_receb_v2",
                 "lucro_ttm_v1", "lucro_ttm_v2", "roe_v1", "roe_v2"])
    return fund[cf.COLUNAS].reset_index(drop=True), emp, rest


# ─────────────────────────────────────────────────────────────
# Fatores NEFIN e CDI
# ─────────────────────────────────────────────────────────────
def _espalhamento(carac_dia, vivos):
    """Media do tercil alto menos a do tercil baixo de uma caracteristica (long-short)."""
    x = carac_dia[vivos]
    if x.size < 6:
        return 0.0
    alto, baixo = np.quantile(x, 2.0 / 3.0), np.quantile(x, 1.0 / 3.0)
    if not (x >= alto).any() or not (x <= baixo).any():
        return 0.0
    return float(x[x >= alto].mean() - x[x <= baixo].mean())


def _fatores(datas, rf, rm, mom, pap, lambda_mom, lambda_valor, seed):
    """DataFrame com EXATAMENTE nefin.FATORES, indexado por Date.

    Rm_minus_Rf E o excesso de mercado gerado e Risk_Free E o CDI gerado: a regressao de
    atribuicao do backtest tem gabarito. WML e HML sao o premio plantado vezes o
    espalhamento da caracteristica; SMB e IML sao ruido (nao ha tamanho nem iliquidez
    plantados) e existem so para o esquema ficar completo.
    """
    rng = _rng(seed, 9)
    n_d, n_t = mom.shape
    i_ini = pap["i_ini"].to_numpy(int)
    i_fim = pap["i_fim"].to_numpy(int)
    v = pap["v"].to_numpy(float)
    wml = np.zeros(n_d)
    hml = np.zeros(n_d)
    for s, e in _blocos_mensais(datas):
        vivos = (i_ini <= s) & (i_fim >= s)
        wml[s:e] = lambda_mom * _espalhamento(mom[s], vivos)
        hml[s:e] = lambda_valor * _espalhamento(v, vivos)
    ruido = lambda: VOL_FATOR_RUIDO * rng.normal(0.0, 1.0, n_d)
    df = pd.DataFrame({
        "Rm_minus_Rf": rm, "SMB": ruido(), "HML": hml + ruido(),
        "WML": wml + ruido(), "IML": ruido(), "Risk_Free": rf,
    }, index=pd.DatetimeIndex(datas, name="Date"))
    return df[nefin.FATORES].astype(float)


# ─────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────
def gerar(ini="2009-01-01", fim="2026-06-30", n_empresas=120, seed=7,
          lambda_mom=0.0, lambda_qual=0.0, lambda_valor=0.0,
          fracao_mortas=0.20, fracao_financeiras=0.10, fracao_pares_on_pn=0.15,
          atraso_receb_dias=45, vazar=False, restatement=True):
    """Mercado artificial completo. Devolve um dict com as tabelas nos esquemas reais.

    Chaves: cotacoes (cotahist.parse), eventos (eventos.COLUNAS), fundamentos
    (cvm_fundamentos.COLUNAS), identidade (identidade.COLUNAS), cadastro (formato de
    identidade.ler_cadastro), fatores (nefin.FATORES), cdi (Series 'cdi' por 'data') e
    gabarito (verdade plantada: empresas, papeis, caracteristicas, retornos, eventos
    especiais, reapresentacoes e os parametros da chamada).

    lambda_mom/lambda_qual/lambda_valor sao premios DIARIOS por desvio-padrao da
    caracteristica (0,0004 ~ 10% ao ano). Todos zero = CONTROLE NULO: nao ha premio
    nenhum e qualquer alfa medido pelo backtest e bug.
    vazar=True publica os documentos com dt_receb = dt_refer (look-ahead plantado).
    """
    pregoes = calendario.pregoes(ini, fim)
    if len(pregoes) < JANELA_MOM[0] + 21:
        raise ValueError(f"janela curta demais: {len(pregoes)} pregoes entre {ini} e {fim}")
    datas = pd.DatetimeIndex(pd.to_datetime(pregoes), name="data")

    emp = _empresas(n_empresas, seed, fracao_mortas, fracao_financeiras, datas,
                    lambda_qual, lambda_valor)
    emp, pap = _papeis(emp, fracao_pares_on_pn, seed)
    rf, rm = _macro(len(datas), seed)
    R, mom, carac = _retornos(pap, datas, rf, rm, lambda_mom, lambda_qual, lambda_valor, seed)
    Y, F, agenda, especiais = _agenda_eventos(pap, datas, seed)
    fec, negociou = _precos(pap, R, Y, F, seed)
    cotacoes = _cotacoes(pap, datas, fec, negociou, seed)
    tabela_eventos = _tabela_eventos(agenda, pap, datas, fec)
    fundamentos, emp, restatements = _fundamentos(emp, datas, atraso_receb_dias, vazar,
                                                  restatement, seed)
    ident, cadastro = _identidade(emp, pap)
    fatores = _fatores(datas, rf, rm, mom, pap, lambda_mom, lambda_valor, seed)
    cdi = pd.Series(rf, index=pd.DatetimeIndex(datas, name="data"), name="cdi")

    retornos = pd.DataFrame(R, index=pd.DatetimeIndex(datas, name="data"), columns=pap["ticker"])
    colunas_emp = ["empresa", "ticker_on", "ticker_pn", "cnpj", "cnpj_num", "cd_cvm", "denominacao", "setor",
                   "financeira", "escopo", "escala", "beta", "q", "v", "sigma", "preco0", "adtv",
                   "faixa_adtv", "prob_falta", "n_acoes", "em_rj", "vencedora", "data_ini", "data_fim"]
    colunas_pap = ["ticker", "empresa", "classe", "isin", "cnpj", "cnpj_num", "cd_cvm", "beta", "q", "v", "sigma",
                   "preco0", "adtv", "prob_falta", "financeira", "setor", "vencedora",
                   "data_ini", "data_fim"]
    gabarito = {
        "empresas": emp[colunas_emp].reset_index(drop=True),
        "papeis": pap[colunas_pap].reset_index(drop=True),
        "caracteristicas": carac,
        "retornos": retornos,
        "eventos_especiais": especiais,
        "restatements": restatements,
        "parametros": {"ini": str(ini), "fim": str(fim), "n_empresas": int(n_empresas),
                       "seed": int(seed), "lambda_mom": float(lambda_mom),
                       "lambda_qual": float(lambda_qual), "lambda_valor": float(lambda_valor),
                       "fracao_mortas": float(fracao_mortas),
                       "fracao_financeiras": float(fracao_financeiras),
                       "fracao_pares_on_pn": float(fracao_pares_on_pn),
                       "atraso_receb_dias": int(atraso_receb_dias), "vazar": bool(vazar),
                       "restatement": bool(restatement), "n_pregoes": len(datas)},
    }
    return {"cotacoes": cotacoes, "eventos": tabela_eventos, "fundamentos": fundamentos,
            "identidade": ident, "cadastro": cadastro, "fatores": fatores, "cdi": cdi,
            "gabarito": gabarito}


@contextmanager
def banco_em(dir_banco):
    """Aponta os caminhos de banco de cotahist/cvm_fundamentos para `dir_banco` enquanto durar.

    Os leitores reais (cotahist.carregar, cvm_fundamentos.carregar) montam o caminho a
    partir das constantes do modulo; este contexto e o unico jeito de escrever e ler o
    banco sintetico com o codigo de producao, sem copia paralela do layout.
    """
    banco_cot, banco_cvm = cotahist.DIR_BANCO, cf.DIR_PARQUET
    cotahist.DIR_BANCO = str(dir_banco)
    cf.DIR_PARQUET = os.path.join(str(dir_banco), "fundamentos_pit")
    try:
        yield str(dir_banco)
    finally:
        cotahist.DIR_BANCO = banco_cot
        cf.DIR_PARQUET = banco_cvm


def gravar_banco(dados, dir_banco):
    """Escreve o banco sintetico no layout real e devolve {arquivo/particao: linhas}."""
    dir_banco = str(dir_banco)
    garantir_dir(dir_banco)
    contagem = {}
    cot = dados["cotacoes"]
    anos_cot = pd.to_datetime(cot["data"]).dt.year
    fund = dados["fundamentos"]
    anos_fund = fund["dt_refer"].dt.year
    with banco_em(dir_banco):
        for ano, parte in cot.groupby(anos_cot, sort=True):
            contagem[f"cotacoes_diarias/ano={ano}"] = cotahist.gravar_ano(parte, int(ano))
        for ano, parte in fund.groupby(anos_fund, sort=True):
            contagem[f"fundamentos_pit/ano={ano}"] = cf.gravar_ano(parte, int(ano))
    eventos.gravar_eventos(dados["eventos"], os.path.join(dir_banco, "eventos.parquet"))
    contagem["eventos.parquet"] = int(len(dados["eventos"]))
    identidade.gravar_identidade(dados["identidade"], os.path.join(dir_banco, "identidade.parquet"))
    contagem["identidade.parquet"] = int(len(dados["identidade"]))
    return contagem


def instalar(monkeypatch, dados):
    """Aponta os carregadores reais para os dados em memoria (uso: testes, sem disco).

    Substitui cotahist.carregar, cvm_fundamentos.carregar, identidade.carregar_identidade e
    eventos.carregar_eventos, respeitando as assinaturas (filtros de ano/ticker/cd_cvm/colunas).
    """
    cot = dados["cotacoes"]
    anos_cot = pd.to_datetime(cot["data"]).dt.year.to_numpy()
    fund = dados["fundamentos"]
    anos_fund = fund["dt_refer"].dt.year.to_numpy()

    def carregar_cotacoes(ano_ini, ano_fim, tickers=None, colunas=None):
        d = cot[(anos_cot >= int(ano_ini)) & (anos_cot <= int(ano_fim))]
        if tickers is not None:
            d = d[d["ticker"].isin(set(tickers))]
        if colunas is not None:
            d = d[list(colunas)]
        return d.reset_index(drop=True)

    def carregar_fundamentos(anos, cd_cvm=None, colunas=None):
        d = fund[np.isin(anos_fund, [int(a) for a in anos])]
        if cd_cvm is not None:
            cods = {int(cd_cvm)} if np.isscalar(cd_cvm) else {int(c) for c in cd_cvm}
            d = d[d["cd_cvm"].isin(cods)]
        if colunas is not None:
            d = d[list(colunas)]
        return d.reset_index(drop=True)

    monkeypatch.setattr(cotahist, "carregar", carregar_cotacoes)
    monkeypatch.setattr(cf, "carregar", carregar_fundamentos)
    monkeypatch.setattr(identidade, "carregar_identidade",
                        lambda caminho=None: dados["identidade"].copy())
    monkeypatch.setattr(eventos, "carregar_eventos", lambda caminho=None: dados["eventos"].copy())
    return dados


# ─────────────────────────────────────────────────────────────
# Linha de comando
# ─────────────────────────────────────────────────────────────
def _resumo(dados, contagem=None):
    g = dados["gabarito"]
    cot = dados["cotacoes"]
    out = {
        "parametros": g["parametros"],
        "papeis": int(len(g["papeis"])),
        "empresas": int(len(g["empresas"])),
        "pregoes": int(cot["data"].nunique()),
        "linhas_cotacoes": int(len(cot)),
        "linhas_eventos": int(len(dados["eventos"])),
        "linhas_fundamentos": int(len(dados["fundamentos"])),
        "deslistadas": int(g["empresas"]["data_fim"].notna().sum()),
        "financeiras": int(g["empresas"]["financeira"].sum()),
        "reapresentacoes": int(len(g["restatements"])),
        # contagem por faixa de custo (os cortes sao os de custos.FAIXAS_SPREAD)
        "faixas_adtv": {str(k): int(v) for k, v in g["papeis"]["adtv"]
                        .apply(lambda a: 0 if a >= 20e6 else (1 if a >= 5e6 else 2))
                        .value_counts().sort_index().items()},
        "eventos_especiais": {k: {"ticker": v["ticker"], "data_ex": str(pd.Timestamp(v["data_ex"]).date()),
                                  "fator": v["fator"]} for k, v in g["eventos_especiais"].items()},
    }
    if contagem is not None:
        out["gravado"] = contagem
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Gera um mercado sintetico completo nos esquemas do banco real")
    ap.add_argument("--dir", default=DIR_PADRAO, help="destino do banco sintetico (nunca quant/banco)")
    ap.add_argument("--ini", default="2009-01-01")
    ap.add_argument("--fim", default="2026-06-30")
    ap.add_argument("--n-empresas", type=int, default=120)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--lambda-mom", type=float, default=0.0, help="premio diario por 1 dp de momento")
    ap.add_argument("--lambda-qual", type=float, default=0.0)
    ap.add_argument("--lambda-valor", type=float, default=0.0)
    ap.add_argument("--fracao-mortas", type=float, default=0.20)
    ap.add_argument("--fracao-financeiras", type=float, default=0.10)
    ap.add_argument("--fracao-pares-on-pn", type=float, default=0.15)
    ap.add_argument("--atraso-receb-dias", type=int, default=45)
    ap.add_argument("--vazar", action="store_true", help="publica com dt_receb = dt_refer (look-ahead)")
    ap.add_argument("--sem-restatement", action="store_true")
    ap.add_argument("--nao-gravar", action="store_true", help="so gera e resume, sem escrever em disco")
    args = ap.parse_args(argv)
    if os.path.abspath(args.dir) == os.path.abspath(os.path.join(DIR_QUANT, "banco")):
        print("recusado: --dir nao pode ser o banco real (quant/banco); use quant/banco_sintetico")
        return 2
    dados = gerar(ini=args.ini, fim=args.fim, n_empresas=args.n_empresas, seed=args.seed,
                  lambda_mom=args.lambda_mom, lambda_qual=args.lambda_qual,
                  lambda_valor=args.lambda_valor, fracao_mortas=args.fracao_mortas,
                  fracao_financeiras=args.fracao_financeiras,
                  fracao_pares_on_pn=args.fracao_pares_on_pn,
                  atraso_receb_dias=args.atraso_receb_dias, vazar=args.vazar,
                  restatement=not args.sem_restatement)
    contagem = None if args.nao_gravar else gravar_banco(dados, args.dir)
    if contagem is not None:
        log(f"mercado sintetico gravado em {args.dir}")
    print(json.dumps(_resumo(dados, contagem), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
