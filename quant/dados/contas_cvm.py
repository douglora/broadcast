"""
Mapa do plano de contas padrao da CVM (DFP/ITR) para os nomes usados no sistema (M5).

Por que existe: as demonstracoes da CVM vem como linhas (CD_CONTA, DS_CONTA, VL_CONTA)
e o codigo e a unica chave estavel entre empresas e anos - a descricao muda de texto
("Receita de Venda de Bens e/ou Servicos" vs "Receita Liquida"). Concentrar aqui o
"qual codigo e o que" evita que cada calculo repita a regra e permite corrigir uma
empresa fora do padrao num lugar so (EXCECOES).

Armadilhas conhecidas:
  - Lucro liquido: '3.11' no consolidado (depois de participacao de minoritarios) e
    '3.09' no individual. Procuramos os dois, nessa ordem.
  - Depreciacao/amortizacao e capex NAO tem codigo fixo: sao linhas livres sob
    '6.01.01' (caixa gerado nas operacoes) e '6.02' (investimento); identificamos
    pela DS_CONTA sem acento/caixa. Capex e a soma das linhas com 'imobilizado' ou
    'intangivel' - inclui recebimentos por venda (capex liquido); sinal negativo = saida.
  - Acoes em circulacao nao vem na DFP. O LPA vem de '3.99' (Lucro por Acao); usamos
    o basico por ON ('3.99.01.01') quando existir, senao o total.
  - Bancos e seguradoras usam '3.01' com outro sentido (receitas da intermediacao
    financeira / premios), nao tem '3.03' e a divida nao e divida. Marque financeiras
    pelo SETOR_ATIV do cadastro ('Banc', 'Segur') e use ROE em vez de ROIC.
  - Na DFC, D&A e um ajuste positivo (add-back) e capex e negativo: EBITDA = EBIT + D&A
    e FCF = FCO + capex (soma, nao subtracao).
  - Uma conta pode aparecer tanto como pai quanto como filho quando a empresa detalha;
    ao somar por descricao descartamos as linhas cujo ancestral tambem casou.
"""
import unicodedata

import numpy as np

# Cada entrada: demo ('BPA', 'BPP', 'DRE' ou 'DFC' = DFC_MI ou DFC_MD), e uma de duas regras:
#   codigos   lista de CD_CONTA exatos; 'agregar' = 'primeiro' (primeiro codigo que existir)
#             ou 'soma' (soma dos que existirem);
#   prefixo + descricao_contem   soma das linhas descendentes de `prefixo` cuja DS_CONTA
#             (sem acento, minuscula) contem algum dos termos.
MAPA_CONTAS = {
    # estoques (balanco)
    "ativo": {"demo": "BPA", "codigos": ["1"], "agregar": "primeiro"},
    "ativo_circulante": {"demo": "BPA", "codigos": ["1.01"], "agregar": "primeiro"},
    "caixa": {"demo": "BPA", "codigos": ["1.01.01", "1.01.02"], "agregar": "soma"},   # caixa + aplicacoes
    "passivo_circulante": {"demo": "BPP", "codigos": ["2.01"], "agregar": "primeiro"},
    "emprestimos_cp": {"demo": "BPP", "codigos": ["2.01.04"], "agregar": "primeiro"},
    "emprestimos_lp": {"demo": "BPP", "codigos": ["2.02.01"], "agregar": "primeiro"},
    "pl": {"demo": "BPP", "codigos": ["2.03"], "agregar": "primeiro"},
    # fluxos (DRE)
    "receita": {"demo": "DRE", "codigos": ["3.01"], "agregar": "primeiro"},
    "lucro_bruto": {"demo": "DRE", "codigos": ["3.03"], "agregar": "primeiro"},
    "ebit": {"demo": "DRE", "codigos": ["3.05"], "agregar": "primeiro"},
    "resultado_financeiro": {"demo": "DRE", "codigos": ["3.06"], "agregar": "primeiro"},
    "lucro_liquido": {"demo": "DRE", "codigos": ["3.11", "3.09"], "agregar": "primeiro"},
    "lpa": {"demo": "DRE", "codigos": ["3.99.01.01", "3.99.01", "3.99"], "agregar": "primeiro"},
    # fluxos (DFC)
    "fco": {"demo": "DFC", "codigos": ["6.01"], "agregar": "primeiro"},
    "fci": {"demo": "DFC", "codigos": ["6.02"], "agregar": "primeiro"},
    "depreciacao": {"demo": "DFC", "prefixo": "6.01.01", "descricao_contem": ["deprecia", "amortiza"]},
    "capex": {"demo": "DFC", "prefixo": "6.02", "descricao_contem": ["imobilizado", "intangivel"]},
}

# Empresas cujo plano de contas foge do padrao. Formato:
#   EXCECOES[cd_cvm] = {nome_em_MAPA_CONTAS: {chaves a sobrescrever na regra}}
# Ex.: {1023: {"receita": {"demo": "DRE", "codigos": ["3.01"], "agregar": "primeiro"},
#              "capex": {"demo": "DFC", "prefixo": "6.02", "descricao_contem": ["ativo fixo"]}}}
# A sobrescrita e por chave (dict.update sobre a regra padrao). Vazia por enquanto.
EXCECOES = {}

# Substrings (sem acento, minusculas) do SETOR_ATIV do cadastro que marcam financeiras.
SETORES_FINANCEIROS = ("banc", "segur")

ALIQUOTA_IR = 0.34   # IR + CSLL padrao usado no ROIC (NOPAT = EBIT * (1 - 0.34))


def normalizar_texto(s):
    """Remove acentos e poe em minusculas: 'Depreciação' -> 'depreciacao'."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def eh_financeira(setor_ativ):
    """True se o SETOR_ATIV do cadastro CVM indica banco ou seguradora."""
    t = normalizar_texto(setor_ativ)
    return any(k in t for k in SETORES_FINANCEIROS)


def regra(nome, cd_cvm=None):
    """Regra efetiva para `nome`: padrao de MAPA_CONTAS com as sobrescritas de EXCECOES."""
    base = dict(MAPA_CONTAS[nome])
    extra = EXCECOES.get(cd_cvm, {}).get(nome) if cd_cvm is not None else None
    if extra:
        base.update(extra)
    return base


def _linhas_da_demo(linhas, demo):
    if demo == "DFC":
        m = linhas["demo"].isin(("DFC_MI", "DFC_MD"))
        sel = linhas[m]
        if (sel["demo"] == "DFC_MI").any():       # se a empresa entrega os dois, fica o indireto
            sel = sel[sel["demo"] == "DFC_MI"]
        return sel
    return linhas[linhas["demo"] == demo]


def _sem_descendentes(sel):
    """Descarta linhas cujo ancestral (por prefixo do CD_CONTA) tambem esta em `sel`."""
    contas = list(sel["conta"])
    manter = [not any(c != o and c.startswith(o + ".") for o in contas) for c in contas]
    return sel[np.array(manter, dtype=bool)]


def extrair(linhas, nome, cd_cvm=None):
    """Valor (em reais) de `nome` a partir das linhas de UM periodo/documento/escopo.

    `linhas` precisa das colunas demo, conta, descricao, valor_reais. Devolve NaN
    quando nenhuma linha casa. Nao soma pai com filho.
    """
    r = regra(nome, cd_cvm)
    sel = _linhas_da_demo(linhas, r["demo"])
    if sel.empty:
        return float("nan")
    if "codigos" in r:
        achados = []
        for cod in r["codigos"]:
            v = sel.loc[sel["conta"] == cod, "valor_reais"]
            v = v[v.notna()]
            if not v.empty:
                achados.append(float(v.iloc[0]))
                if r.get("agregar", "primeiro") == "primeiro":
                    break
        if not achados:
            return float("nan")
        return float(sum(achados))
    prefixo = r["prefixo"] + "."
    termos = [normalizar_texto(t) for t in r["descricao_contem"]]
    desc = sel["descricao"].map(normalizar_texto)
    m = sel["conta"].str.startswith(prefixo) & desc.map(lambda d: any(t in d for t in termos))
    m = m & sel["valor_reais"].notna()
    sel = sel[m]
    if sel.empty:
        return float("nan")
    return float(_sem_descendentes(sel)["valor_reais"].sum())
