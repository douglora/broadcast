"""Retorno esperado por classe, do dado de mercado e com a fonte de cada numero.

Principio: cada classe tem um metodo declarado, uma confianca (alta, media, baixa) e uma nota.
Renda fixa sai do mercado (curva DI, NTN-B, spreads), renda variavel sai de premio sobre juro
real (com a TIR da bolsa pelo metodo do Safra como segunda leitura), e o que nao tem ancora
(ouro, cripto) fica rotulado como convencao. As opinioes do Douglas entram como `visoes`:
deslocamento em pontos percentuais ao ano sobre o retorno bruto da classe, sempre visivel.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import config as C
from . import fiscal
from .mercado import Mercado

# Parametros de convencao (nao saem de dado). Mexer aqui muda todos os relatorios, de proposito.
PARAMS = {
    "pos_isenta_pct_cdi": 1.00,   # LCA/LCI/CRA CDI na prateleira: ~100% do CDI sem imposto (Tonial: LCA 102%)
    "pos_trib_pct_cdi": 1.04,     # CDB/LF de banco medio e fundos DI: ~104% do CDI, com IR
    "erp_br": 0.040,              # premio de risco da bolsa sobre a NTN-B de 10 anos
    "haircut_rv": 0.010,          # desconto de prudencia no retorno real de bolsa (erro de estimativa)
    "erp_us": 0.030,              # premio de risco da bolsa dos EUA sobre o Treasury de 10 anos
    "infl_eua": 0.025,            # inflacao americana de longo prazo (breakeven de 10 anos + folga)
    "fii_premio_real": 0.018,     # FIIs: premio sobre a NTN-B real (yield de carrego + crescimento)
    "mm_premio": 0.005,           # multimercado mediano: CDI + 0,5% bruto, depois das taxas
    "ouro_real_usd": 0.005,       # ouro: inflacao americana + 0,5%
    "cripto_premio": 0.030,       # sem ancora: CDI + 3% como convencao, dimensionado pelo risco
    "dy_fii": fiscal.DY_FII_PADRAO,
}


@dataclass
class Premissa:
    id: str
    bruto: float                 # fracao a.a., antes do imposto e da visao
    visao_pp: float = 0.0        # deslocamento do Douglas, em pontos percentuais a.a.
    liquido: float = 0.0         # fracao a.a., depois do imposto no horizonte
    metodo: str = ""
    fonte: str = ""
    confianca: str = "media"
    nota: str = ""

    @property
    def bruto_total(self) -> float:
        return self.bruto + self.visao_pp / 100.0


def horizonte_anos(h: float) -> float:
    return min(max(float(h), 1.0), 12.0)


def cdi_horizonte(m: Mercado, anos: float) -> float:
    """CDI medio esperado nos proximos `anos` (fracao a.a.): a propria curva DI viva."""
    return m.di_aa(anos) / 100.0


def benchmark_liquido(m: Mercado, anos: float, visoes: list[dict] | None = None) -> float:
    """O que o cliente ganharia em 100% do CDI tributado pela tabela regressiva (fracao a.a.),
    com o deslocamento de CDI que o Douglas tenha dado (visao `_cdi`)."""
    desl = sum(float(v.get("delta_pp", 0.0)) for v in (visoes or []) if v.get("classe") == "_cdi") / 100.0
    return fiscal.liquido(cdi_horizonte(m, anos) + desl, "regressivo", anos)


def montar(m: Mercado, horizonte: float, visoes: list[dict] | None = None) -> dict[str, Premissa]:
    H = horizonte_anos(horizonte)
    visoes = visoes or []
    # visoes de nivel (classe "_cdi" e "_ipca"): deslocam o CDI medio e o IPCA esperado do horizonte, em pontos
    # percentuais ao ano, e alcancam tudo que depende deles (o que esta travado em taxa nao muda).
    desl_cdi = sum(float(v.get("delta_pp", 0.0)) for v in visoes if v.get("classe") == "_cdi") / 100.0
    desl_ipca = sum(float(v.get("delta_pp", 0.0)) for v in visoes if v.get("classe") == "_ipca") / 100.0
    cdi = cdi_horizonte(m, H) + desl_cdi
    ipca = m.ipca_esperado(H) / 100.0 + desl_ipca
    real = m.real_aa(H) / 100.0
    real10 = m.real_aa(10.0) / 100.0
    pre = m.pre_aa(H) / 100.0
    sp_ipca = m.deb_ipca_spread_bps / 10000.0
    sp_pre = m.deb_pre_spread_bps / 10000.0
    P = PARAMS
    src_di = ("DI vivo " + m.di_vivo_hora + " (B3)") if m.di_vivo else f"DI {m.di_data} (B3)"
    out: dict[str, Premissa] = {}

    def add(cid: str, bruto: float, metodo: str, fonte: str, conf: str, nota: str = ""):
        out[cid] = Premissa(cid, bruto, metodo=metodo, fonte=fonte, confianca=conf, nota=nota)

    add("caixa", cdi, f"CDI médio do horizonte pela curva DI de {H:.0f} anos", src_di, "alta")
    add("pos_isenta", cdi * P["pos_isenta_pct_cdi"],
        f"{P['pos_isenta_pct_cdi']*100:.0f}% do CDI do horizonte, sem imposto", src_di + "; prateleira típica", "media",
        "Prateleira varia por emissor; confira a taxa real do papel.")
    add("pos_trib", cdi * P["pos_trib_pct_cdi"],
        f"{P['pos_trib_pct_cdi']*100:.0f}% do CDI do horizonte, com IR regressivo", src_di + "; prateleira típica", "media")
    add("ipca_trib", (1 + ipca) * (1 + real) - 1,
        f"IPCA do Focus ({ipca*100:.2f}% a.a.) + juro real da NTN-B de {H:.0f} anos ({real*100:.2f}%)",
        f"Focus {m.focus_data}; NTN-B ANBIMA {m.ntnb_data}", "media",
        "Se marcada a mercado antes do vencimento o resultado muda; no vencimento trava o carrego."
        + (" Juro real de ontem: hoje deve estar maior." if m.em_choque else ""))
    add("ipca_isenta", (1 + ipca) * (1 + real + sp_ipca) - 1,
        f"igual ao IPCA+ do Tesouro mais {m.deb_ipca_spread_bps:.0f} bps de spread mediano das debêntures",
        f"Focus {m.focus_data}; NTN-B e debêntures ANBIMA {m.ntnb_data}", "media",
        "Risco de crédito do emissor entra: o spread é o pagamento por ele.")
    add("pre_trib", pre, f"taxa pré do Tesouro no prazo de {H:.0f} anos", f"LTN/NTN-F ANBIMA + DI de hoje", "media",
        "Trava taxa nominal; perde se o CDI médio do período superar a taxa travada.")
    add("pre_isenta", pre + sp_pre,
        f"taxa pré do Tesouro mais {m.deb_pre_spread_bps:.0f} bps de spread mediano", "LTN/NTN-F e debêntures ANBIMA", "media")

    ntnb10 = real10 * 100.0
    tir_real = (m.tir_mediana_real * 100.0) if m.tir_mediana_real is not None else None
    anchor1 = ntnb10 / 100.0 + P["erp_br"]
    if tir_real is not None:
        real_rv = 0.5 * anchor1 + 0.5 * (tir_real / 100.0) - P["haircut_rv"]
        metodo_rv = (f"retorno real = 50% (NTN-B 10a {ntnb10:.2f}% + prêmio {P['erp_br']*100:.1f}%) + 50% (TIR mediana da "
                     f"bolsa {tir_real:.1f}%) - {P['haircut_rv']*100:.1f}% de prudência")
    else:
        real_rv = anchor1 - P["haircut_rv"]
        metodo_rv = f"retorno real = NTN-B 10a {ntnb10:.2f}% + prêmio {P['erp_br']*100:.1f}% - prudência"
    add("rv_br", (1 + ipca) * (1 + real_rv) - 1, metodo_rv, f"NTN-B ANBIMA; TIR {m.tir_data}; Focus", "baixa",
        "Previsão de bolsa erra muito (11 a 12 pontos ao ano em papel isolado, estudo do terminal): trate como ordem de grandeza.")
    add("fii", (1 + ipca) * (1 + real10 + P["fii_premio_real"]) - 1,
        f"IPCA + NTN-B 10a ({real10*100:.2f}%) + {P['fii_premio_real']*100:.1f}% de prêmio", "NTN-B ANBIMA; Focus", "media",
        "Parte do retorno sai como rendimento mensal isento (dy de convenção).")

    usd = m.ust10 / 100.0 + P["erp_us"]
    deriva = (1 + ipca) / (1 + P["infl_eua"]) - 1
    add("rv_int", (1 + usd) * (1 + deriva) - 1,
        f"Treasury 10a ({m.ust10:.2f}%) + prêmio {P['erp_us']*100:.1f}% em dólar, mais deriva cambial pela paridade de inflação ({deriva*100:.1f}% a.a.)",
        f"Treasury {m.ust_data}; Focus", "baixa",
        "Com CDI alto, renda variável no exterior rende menos que o carrego: entra por diversificação e proteção cambial, não por retorno.")
    ouro_usd = P["infl_eua"] + P["ouro_real_usd"]
    add("alt_ouro", (1 + ouro_usd) * (1 + deriva) - 1,
        f"inflação dos EUA + {P['ouro_real_usd']*100:.1f}% real, em dólar, mais deriva cambial", "convenção", "baixa",
        "Sem fluxo de caixa: o valor está no seguro, não no retorno.")
    add("cripto", cdi + P["cripto_premio"], f"CDI + {P['cripto_premio']*100:.0f}% (convenção, sem âncora fundamental)", "convenção", "baixa",
        "Dimensione pela perda que o cliente aguenta: a volatilidade passa de 60% ao ano.")
    add("mm", cdi + P["mm_premio"], f"CDI + {P['mm_premio']*100:.1f}% bruto (mediana de gestores, depois das taxas)", src_di + "; convenção", "baixa",
        "A dispersão entre gestores é maior que a diferença entre classes: escolha de gestor manda.")
    add("vgbl", cdi + P["mm_premio"], f"igual ao multimercado, com IR regressivo da previdência no resgate", src_di + "; convenção", "baixa",
        "O benefício é tributário e sucessório; o retorno bruto depende do fundo escolhido dentro do plano.")

    # visoes do Douglas, depois impostos
    for v in visoes:
        cid = v.get("classe")
        if cid in out:
            out[cid].visao_pp += float(v.get("delta_pp", 0.0))
    for cid, p in out.items():
        trib = C.POR_ID[cid].tributo
        p.liquido = fiscal.liquido(p.bruto_total, trib, H, P["dy_fii"])
    return out


def tabela_resumo(prem: dict[str, Premissa]) -> list[dict]:
    return [{"id": c.id, "classe": c.curto, "bruto": prem[c.id].bruto_total, "liquido": prem[c.id].liquido,
             "confianca": prem[c.id].confianca, "metodo": prem[c.id].metodo, "visao_pp": prem[c.id].visao_pp}
            for c in C.CLASSES]
