"""Testes de estresse: choques hipoteticos, instantaneos, a mercado, sobre a carteira.

Sao HIPOTESES da mesa (ordem de grandeza coerente com crises brasileiras e globais recentes), nao previsoes e
nao medidas historicas exatas; cada choque aparece na tabela do relatorio para o Douglas discordar. O impacto
em cada classe vem de duracao e sensibilidade (receita abaixo), a mesma para toda carteira. O choque mede o
tombo de pico a vale; o carrego do CDI repoe parte dele com o tempo (o resultado mostra em quantos meses).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np

from . import config as C
from . import risco as R

# duracao do spread de credito (anos) por classe: quanto o papel perde por 1 ponto de abertura do spread
DUR_SPREAD = {"pos_isenta": 2.0, "pos_trib": 0.6, "ipca_isenta": 3.0, "pre_isenta": 2.5, "ipca_trib": 0.0,
              "pre_trib": 0.0, "caixa": 0.0}
DUR_MM_JUROS = R.DUR_MM_JUROS


@dataclass
class Cenario:
    id: str
    nome: str
    historia: str            # a historia do choque em uma frase, para o cliente
    d_pre: float = 0.0       # bps na taxa pre
    d_real: float = 0.0      # bps no juro real (NTN-B)
    d_spread: float = 0.0    # bps no spread de credito privado
    usd: float = 0.0         # % de variacao do dolar contra o real (positivo = real perde)
    ibov: float = 0.0        # % bolsa brasileira
    ifix: float = 0.0        # % FIIs
    spx: float = 0.0         # % bolsa dos EUA em dolar
    ouro: float = 0.0        # % ouro em dolar
    cripto: float = 0.0      # % cripto em dolar
    adverso: bool = True
    observado: bool = False


CENARIOS: list[Cenario] = [
    Cenario("fiscal", "Estresse fiscal-eleitoral", "Dólar e juros longos disparam, bolsa cai, cripto acompanha o risco.",
            d_pre=250, d_real=150, d_spread=60, usd=12, ibov=-15, ifix=-9, spx=-3, ouro=4, cripto=-20),
    Cenario("juros_altos", "Juros altos por mais tempo", "A Selic demora a cair; curva pré e real abrem, bolsa e FIIs sofrem.",
            d_pre=120, d_real=80, d_spread=40, usd=4, ibov=-10, ifix=-7, spx=-4, ouro=0, cripto=-15),
    Cenario("risk_off", "Aversão a risco global", "Crise lá fora: bolsa mundial despenca, dolar e ouro sobem, credito abre.",
            d_pre=80, d_real=60, d_spread=150, usd=10, ibov=-18, ifix=-8, spx=-20, ouro=8, cripto=-45),
    Cenario("credito", "Estresse de crédito privado", "Um ciclo de calotes abre o spread e leva junto bolsa e FIIs.",
            d_pre=60, d_real=40, d_spread=300, usd=3, ibov=-12, ifix=-12, spx=-5, ouro=2, cripto=-10),
    Cenario("dolar_inflacao", "Dólar forte com inflação maior", "Câmbio sobe 15% e a inflação esperada acompanha; juros longos abrem.",
            d_pre=150, d_real=100, d_spread=30, usd=15, ibov=-8, ifix=-5, spx=0, ouro=6, cripto=0),
    Cenario("cripto", "Cripto cai 60%", "Aversão ao ativo mais volátil, isolada do resto.", cripto=-60),
    Cenario("juros_caem", "Queda de juros mais rápida", "Desinflação e queda da Selic: papéis longos e bolsa sobem.",
            d_pre=-200, d_real=-120, d_spread=-30, usd=-6, ibov=14, ifix=10, spx=4, ouro=-2, cripto=15, adverso=False),
]


def combinado(a: Cenario, b: Cenario, peso: float = 0.7) -> Cenario:
    """Soma de dois choques, cada um a `peso` da intensidade: o pior dia quando duas coisas ruins coincidem."""
    f = lambda attr: peso * (getattr(a, attr) + getattr(b, attr))
    return Cenario("combinado", "Combinado adverso", f"{a.nome} e {b.nome} ao mesmo tempo, a {peso*100:.0f}% da intensidade de cada um.",
                   d_pre=f("d_pre"), d_real=f("d_real"), d_spread=f("d_spread"), usd=f("usd"), ibov=f("ibov"),
                   ifix=f("ifix"), spx=f("spx"), ouro=f("ouro"), cripto=f("cripto"))


def todos(extra: dict | None = None, duracoes: dict | None = None) -> list[Cenario]:
    """Cenarios da mesa + o combinado + (se o analista gravou) o choque observado de hoje."""
    lista = list(CENARIOS)
    por_id = {c.id: c for c in lista}
    lista.insert(len(lista) - 1, combinado(por_id["fiscal"], por_id["risk_off"]))
    if extra:
        campos = {k: float(extra[k]) for k in ("d_pre", "d_real", "d_spread", "usd", "ibov", "ifix", "spx", "ouro", "cripto") if k in extra}
        lista.insert(0, Cenario("hoje", extra.get("nome", "Choque de hoje (observado)"),
                                extra.get("historia", "Os movimentos de hoje, repetidos como se fossem definitivos."),
                                observado=True, **campos))
    return lista


def impacto_classes(c: Cenario, horizonte: float) -> dict[str, float]:
    """Variacao instantanea (fracao) de cada classe no cenario."""
    d = R.duracoes(horizonte)
    pre, real, spr = c.d_pre / 1e4, c.d_real / 1e4, c.d_spread / 1e4
    usd = c.usd / 100.0
    em_usd = lambda x: (1.0 + x / 100.0) * (1.0 + usd) - 1.0
    out = {
        "caixa": 0.0,
        "pos_isenta": -DUR_SPREAD["pos_isenta"] * spr,
        "pos_trib": -DUR_SPREAD["pos_trib"] * spr,
        "ipca_isenta": -d["ipca_isenta"] * real - DUR_SPREAD["ipca_isenta"] * spr,
        "ipca_trib": -d["ipca_trib"] * real,
        "pre_isenta": -d["pre_isenta"] * pre - DUR_SPREAD["pre_isenta"] * spr,
        "pre_trib": -d["pre_trib"] * pre,
        "rv_br": c.ibov / 100.0,
        "fii": c.ifix / 100.0,
        "rv_int": em_usd(c.spx),
        "alt_ouro": em_usd(c.ouro),
        "cripto": em_usd(c.cripto),
    }
    mm = (R.MIX_MM["rv_br"] * out["rv_br"] + R.MIX_MM["rv_int"] * out["rv_int"]
          + R.MIX_MM["ima"] * (-DUR_MM_JUROS * pre))
    out["mm"] = mm
    out["vgbl"] = mm
    return out


def aplicar(w: np.ndarray, c: Cenario, horizonte: float) -> dict:
    imp = impacto_classes(c, horizonte)
    v = np.array([imp[cid] for cid in C.IDS])
    contrib = w * v
    return {"id": c.id, "nome": c.nome, "historia": c.historia, "adverso": c.adverso, "observado": c.observado,
            "total": float(contrib.sum()), "por_classe": {cid: float(contrib[i]) for i, cid in enumerate(C.IDS)},
            "impacto_classe": imp}


def estresse(w: np.ndarray, horizonte: float, ret_esperado: float, extra: dict | None = None) -> dict:
    """Todos os cenarios para uma carteira, o pior dos adversos e quantos meses de carrego o repoem."""
    res = [aplicar(w, c, horizonte) for c in todos(extra)]
    adversos = [r for r in res if r["adverso"]]
    pior = min(adversos, key=lambda r: r["total"]) if adversos else None
    mensal = (1.0 + ret_esperado) ** (1.0 / 12.0) - 1.0
    for r in res:
        r["meses_para_recuperar"] = (float(np.ceil(-r["total"] / mensal)) if r["total"] < 0 and mensal > 0 else 0.0)
    return {"cenarios": res, "pior": pior}


def ler_extra() -> dict | None:
    """Choque observado de hoje, gravado pelo analista em ajustes.json (chave cenario_hoje)."""
    try:
        d = json.loads((C.CACHE / "ajustes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d.get("cenario_hoje")
