"""Constantes da mesa de asset allocation: caminhos, taxonomia de classes e perfis.

Tudo que o Douglas pode querer ajustar sem mexer em logica mora aqui ou em
premissas.py (parametros com fonte e nota). Dado de cliente NUNCA fica no
repositorio: a pasta de clientes e ~/Documents/Asset Allocation (LGPD).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

HOME = Path.home()
TERMINAL = Path(os.environ.get("ALOCACAO_TERMINAL", HOME / "Desktop" / "terminal-artefato"))
OUT = TERMINAL / "cache" / "out"
HIST = OUT / "hist"
BANCO = TERMINAL / "cache" / "banco" / "terminal.sqlite"
CLIENTES = Path(os.environ.get("ALOCACAO_CLIENTES", HOME / "Documents" / "Asset Allocation"))
CACHE = CLIENTES / "_mercado"

SEMENTE = 20261026  # Monte Carlo reprodutivel: mesma entrada, mesmo numero


@dataclass(frozen=True)
class Classe:
    id: str
    nome: str
    curto: str
    grupo: str
    cor: str
    liquidez_dias: int      # prazo tipico para virar caixa (D+n)
    moeda: str              # BRL ou USD (exposicao cambial)
    tributo: str            # chave de fiscal.TRIBUTOS
    blindagem: str          # IRPFM: excluido | diferido | neutralizado | exposto
    papel: str              # a funcao da classe na carteira, em uma frase


CLASSES: list[Classe] = [
    Classe("caixa", "Caixa e liquidez (Tesouro Selic, CDB liquidez diária)", "Caixa", "Liquidez",
           "#9aa6bf", 1, "BRL", "caixa", "neutralizado",
           "Reserva para despesas e oportunidades; não é lugar de render, é lugar de ter."),
    Classe("pos_isenta", "RF isenta pós-CDI (LCA, LCI, CRA/CRI CDI, incentivadas)", "RF isenta pós-CDI",
           "Renda fixa isenta", "#1f4e9c", 30, "BRL", "isento", "excluido",
           "Carrego do CDI sem imposto: a base de retorno previsível."),
    Classe("ipca_isenta", "RF isenta IPCA+ (incentivadas, CRA/CRI, FI-Infra)", "RF isenta IPCA+",
           "Renda fixa isenta", "#3b73c9", 90, "BRL", "isento", "excluido",
           "Trava juro real alto sem imposto e protege o poder de compra no prazo longo."),
    Classe("pre_isenta", "RF isenta pré-fixada (LCA/CRA pré, incentivadas pré)", "RF isenta pré",
           "Renda fixa isenta", "#7aa3e0", 90, "BRL", "isento", "excluido",
           "Trava taxa nominal; ganha se os juros caírem e perde marcação se subirem."),
    Classe("pos_trib", "RF tributável pós-CDI (CDB, LF, fundos DI)", "RF tributável pós-CDI",
           "Renda fixa tributável", "#5c6b8a", 30, "BRL", "regressivo", "neutralizado",
           "Pós-CDI com IR na fonte (15% a 22,5%); útil quando a isenta não alcança."),
    Classe("ipca_trib", "RF tributável IPCA+ (Tesouro IPCA+, CDB IPCA)", "RF tributável IPCA+",
           "Renda fixa tributável", "#7f8da8", 2, "BRL", "regressivo", "neutralizado",
           "Juro real do Tesouro com liquidez diária (a mercado) e risco soberano."),
    Classe("pre_trib", "RF tributável pré-fixada (Tesouro Prefixado, CDB pré)", "RF tributável pré",
           "Renda fixa tributável", "#aab4c8", 2, "BRL", "regressivo", "neutralizado",
           "Taxa nominal travada do soberano; sensível à marcação a mercado."),
    Classe("mm", "Multimercado", "Multimercado", "Multimercado e previdência",
           "#8c6d3f", 30, "BRL", "fundo_cota", "neutralizado",
           "Diversifica fonte de retorno (macro, juros, câmbio); depende de gestor."),
    Classe("vgbl", "Previdência VGBL/PGBL (multimercado ou renda fixa)", "VGBL/PGBL",
           "Multimercado e previdência", "#b39b6b", 5, "BRL", "previdencia", "diferido",
           "Diferimento de IR sem come-cotas e sucessão fora do inventário."),
    Classe("rv_br", "Ações Brasil", "Ações Brasil", "Renda variável",
           "#2e7d6b", 2, "BRL", "ganho_15", "exposto",
           "Dono de empresa brasileira: crescimento real de longo prazo, com volatilidade."),
    Classe("fii", "Fundos imobiliários (FIIs)", "FIIs", "Renda variável",
           "#5aa38f", 2, "BRL", "fii", "exposto",
           "Renda mensal isenta para pessoa física e exposição a imóvel e crédito imobiliário."),
    Classe("rv_int", "Renda variável internacional (ETFs UCITS, BDR, ações EUA)", "RV internacional",
           "Renda variável", "#1e6f8c", 3, "USD", "ganho_15", "exposto",
           "Diversifica país e moeda: dólar protege quando o risco Brasil pesa."),
    Classe("alt_ouro", "Ouro e alternativos líquidos", "Ouro", "Alternativos",
           "#d1b05a", 2, "USD", "ganho_15", "exposto",
           "Seguro contra choque: rende pouco, paga quando o resto sofre."),
    Classe("cripto", "Criptoativos", "Cripto", "Alternativos",
           "#a1534a", 1, "USD", "ganho_15", "exposto",
           "Opção de alto risco; dimensionada pela perda que o cliente aguenta, não pelo retorno."),
]

POR_ID = {c.id: c for c in CLASSES}
IDS = [c.id for c in CLASSES]


def _b(**kw) -> dict:
    """Bandas em % (min, max); classe nao citada = (0, 0)."""
    return {k: (float(v[0]) / 100.0, float(v[1]) / 100.0) for k, v in kw.items()}


# Perfil -> bandas por classe, orcamento de volatilidade (um pouco acima da carteira modelo do perfil) e queda
# maxima tolerada de pico a vale.
# Sao padroes da mesa; o limite que o CLIENTE declarou na ficha sempre vale mais.
PERFIS = {
    "conservador": {
        "vol_alvo": 0.021, "perda_12m": 0.05, "rv_max": 0.08,
        "bandas": _b(caixa=(5, 20), pos_isenta=(10, 50), ipca_isenta=(0, 30), pre_isenta=(0, 10),
                     pos_trib=(0, 30), ipca_trib=(0, 15), pre_trib=(0, 5), mm=(0, 10), vgbl=(0, 15),
                     rv_br=(0, 5), fii=(0, 5), rv_int=(0, 5), alt_ouro=(0, 3), cripto=(0, 0)),
    },
    "moderado": {
        "vol_alvo": 0.036, "perda_12m": 0.09, "rv_max": 0.25,
        "bandas": _b(caixa=(3, 15), pos_isenta=(5, 40), ipca_isenta=(5, 35), pre_isenta=(0, 15),
                     pos_trib=(0, 25), ipca_trib=(0, 15), pre_trib=(0, 10), mm=(0, 15), vgbl=(0, 15),
                     rv_br=(3, 15), fii=(0, 10), rv_int=(3, 15), alt_ouro=(0, 5), cripto=(0, 2)),
    },
    "arrojado": {
        "vol_alvo": 0.050, "perda_12m": 0.13, "rv_max": 0.45,
        "bandas": _b(caixa=(2, 10), pos_isenta=(5, 35), ipca_isenta=(5, 35), pre_isenta=(0, 15),
                     pos_trib=(0, 20), ipca_trib=(0, 15), pre_trib=(0, 10), mm=(0, 15), vgbl=(0, 15),
                     rv_br=(5, 25), fii=(0, 12), rv_int=(5, 25), alt_ouro=(0, 6), cripto=(0, 5)),
    },
    "agressivo": {
        "vol_alvo": 0.070, "perda_12m": 0.18, "rv_max": 0.70,
        "bandas": _b(caixa=(1, 8), pos_isenta=(0, 25), ipca_isenta=(0, 30), pre_isenta=(0, 15),
                     pos_trib=(0, 15), ipca_trib=(0, 15), pre_trib=(0, 10), mm=(0, 15), vgbl=(0, 15),
                     rv_br=(10, 35), fii=(0, 15), rv_int=(10, 35), alt_ouro=(0, 8), cripto=(0, 8)),
    },
}

# Carteira modelo da mesa para cada perfil (soma 100). E o ponto de partida do otimizador: o mercado desloca dela
# pelo que paga hoje. Sao ideias da mesa, editaveis aqui, e o relatorio sempre mostra a distancia para elas.
_NEUTRO = {
    "conservador": dict(caixa=12, pos_isenta=38, ipca_isenta=14, pre_isenta=3, pos_trib=8, ipca_trib=6, pre_trib=0,
                        mm=4, vgbl=8, rv_br=2, fii=2, rv_int=2, alt_ouro=1, cripto=0),
    "moderado": dict(caixa=6, pos_isenta=20, ipca_isenta=20, pre_isenta=3, pos_trib=5, ipca_trib=5, pre_trib=2,
                     mm=8, vgbl=6, rv_br=8, fii=5, rv_int=8, alt_ouro=3, cripto=1),
    "arrojado": dict(caixa=4, pos_isenta=12, ipca_isenta=17, pre_isenta=3, pos_trib=3, ipca_trib=4, pre_trib=2,
                     mm=8, vgbl=6, rv_br=14, fii=7, rv_int=15, alt_ouro=4, cripto=1),
    "agressivo": dict(caixa=3, pos_isenta=6, ipca_isenta=12, pre_isenta=3, pos_trib=2, ipca_trib=3, pre_trib=2,
                      mm=8, vgbl=6, rv_br=20, fii=8, rv_int=20, alt_ouro=4, cripto=3),
}
NEUTRO = {p: {cid: v.get(cid, 0) / 100.0 for cid in IDS} for p, v in _NEUTRO.items()}

# Classes que contam como "risco" no teto de renda variavel do perfil.
GRUPO_RV = ("rv_br", "fii", "rv_int", "cripto")
# Custo embutido tipico (% a.a. sobre o saldo): ja descontado das premissas, mostrado para o cliente ver.
CUSTO_AA = {"caixa": 0.0, "pos_isenta": 0.0, "ipca_isenta": 0.0, "pre_isenta": 0.0, "pos_trib": 0.0,
            "ipca_trib": 0.002, "pre_trib": 0.002, "mm": 0.018, "vgbl": 0.012, "rv_br": 0.004,
            "fii": 0.008, "rv_int": 0.004, "alt_ouro": 0.006, "cripto": 0.012}

ROTULOS_PERFIL = {"conservador": "Conservador", "moderado": "Moderado",
                  "arrojado": "Arrojado", "agressivo": "Agressivo"}


def bandas_do_perfil(perfil: str) -> dict:
    p = PERFIS.get((perfil or "").lower())
    if p is None:
        raise ValueError(f"perfil desconhecido: {perfil!r} (use {', '.join(PERFIS)})")
    return {cid: p["bandas"].get(cid, (0.0, 0.0)) for cid in IDS}
