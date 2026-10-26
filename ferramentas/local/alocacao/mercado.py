"""Retrato de mercado que alimenta as premissas: tudo lido do terminal, com fonte e data.

Nada aqui e opiniao. Le cache/out/rf.json, macro.json, tir_estado.json e o banco do
terminal (~/Desktop/terminal-artefato) e devolve um Mercado com o veredito de frescor.
Curva viva: quando o DI tem negocio de HOJE (intradia da B3), ela vale mais que o ajuste
de ontem; e quando as duas divergem muito, o retrato avisa que o mercado esta em choque.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import config as C


def _json(caminho: Path, padrao=None):
    try:
        return json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return padrao


def interp(curva: list, x: float) -> float | None:
    """Interpolacao linear numa curva [[x, y], ...]; fora do alcance vale a ponta (flat)."""
    pts = sorted((float(a), float(b)) for a, b in curva if a is not None and b is not None)
    if not pts:
        return None
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 > x0 else y0
    return pts[-1][1]


@dataclass
class Mercado:
    consulta: str                       # AAAA-MM-DD da leitura
    gerado: str = ""                    # carimbo do rf.json
    selic_meta: float = 0.0
    cdi: float = 0.0
    ipca_12m: float = 0.0
    di_ajuste: list = field(default_factory=list)   # [[du, taxa]] ajuste do ultimo pregao
    di_vivo: list = field(default_factory=list)     # [[du, taxa]] ultimo negocio de hoje
    di_vivo_hora: str = ""
    di_data: str = ""
    ntnb: list = field(default_factory=list)        # [[anos, juro real]] ANBIMA
    ntnb_data: str = ""
    pre: list = field(default_factory=list)         # [[anos, taxa]] LTN/NTN-F ANBIMA
    focus: dict = field(default_factory=dict)       # {"IPCA": {2026: 5.19}, ...}
    focus_data: str = ""
    ust: list = field(default_factory=list)         # [[anos, taxa]]
    ust_data: str = ""
    ust10: float = 0.0
    spread_hy_bps: float | None = None
    spread_ig_bps: float | None = None
    deb_ipca_spread_bps: float = 70.0               # incentivadas IPCA+ sobre a NTN-B
    deb_di_spread_bps: float = 97.0                 # DI+ sobre o DI
    deb_pre_spread_bps: float = 71.0
    ptax: float = 0.0
    ptax_data: str = ""
    tir_mediana_real: float | None = None           # mediana da bolsa, metodo Safra (fracao)
    tir_k_real: float | None = None
    tir_data: str = ""
    ima: dict = field(default_factory=dict)
    fed_funds: float | None = None
    avisos: list = field(default_factory=list)
    fontes: list = field(default_factory=list)      # [(rotulo, data/hora)]
    veredito: str = "VELHO"
    ajustes: dict = field(default_factory=dict)     # deslocamentos manuais (bps) que o analista aplicou

    # --- derivados -----------------------------------------------------------------
    @property
    def di(self) -> list:
        return self.di_vivo if len(self.di_vivo) >= 8 else self.di_ajuste

    def di_aa(self, anos: float) -> float:
        """DI x pre (% a.a., base 252) para um prazo em anos, na curva em uso."""
        v = interp(self.di, 252.0 * max(anos, 0.05))
        return float(v) if v is not None else self.cdi

    def di_ajuste_aa(self, anos: float) -> float:
        v = interp(self.di_ajuste, 252.0 * max(anos, 0.05))
        return float(v) if v is not None else self.cdi

    def real_choque_bps(self, anos: float) -> float:
        """Deslocamento (bps) aplicado ao juro real da ANBIMA: o manual, se o analista deu um; senao,
        em dia de choque, metade do deslocamento do DI no mesmo prazo (ESTIMATIVA, sempre avisada)."""
        if "real_bps" in self.ajustes:
            return float(self.ajustes["real_bps"])
        if self.em_choque:
            return round(0.5 * (self.di_aa(anos) - self.di_ajuste_aa(anos)) * 100.0, 1)
        return 0.0

    def real_aa(self, anos: float) -> float:
        """Juro real da NTN-B (% a.a.): curva ANBIMA mais o deslocamento de choque, se houver."""
        v = interp(self.ntnb, anos)
        base = float(v) if v is not None else 6.5
        return base + self.real_choque_bps(anos) / 100.0

    def pre_aa(self, anos: float) -> float:
        """Taxa pre do Tesouro (LTN/NTN-F) no prazo. A taxa ANBIMA e de ontem; quando o DI de hoje
        andou, soma o deslocamento do DI naquele prazo (estimativa, avisada no retrato)."""
        v = interp(self.pre, anos)
        if v is None:
            return self.di_aa(anos)
        return float(v) + (self.di_aa(anos) - self.di_ajuste_aa(anos))

    def ipca_focus(self, ano: int) -> float:
        d = self.focus.get("IPCA", {})
        if ano in d:
            return float(d[ano])
        if d:
            ultimo = max(d)
            return float(d[ultimo]) if ano > ultimo else float(d[min(d)])
        return 4.0

    def ipca_esperado(self, anos: float) -> float:
        """IPCA medio esperado nos proximos `anos` (% a.a.): Focus nos anos que ele cobre,
        e depois o centro de longo prazo (3,5%) que o proprio Focus de 2028 sinaliza."""
        n = max(1, int(round(anos)))
        ano0 = int(self.consulta[:4])
        anuais = []
        for k in range(n):
            ano = ano0 + k
            if ano in self.focus.get("IPCA", {}):
                anuais.append(float(self.focus["IPCA"][ano]))
            else:
                anuais.append(3.5)
        prod = 1.0
        for a in anuais:
            prod *= 1.0 + a / 100.0
        return (prod ** (1.0 / n) - 1.0) * 100.0

    def selic_focus_media(self, anos: float) -> float:
        n = max(1, int(round(anos)))
        ano0 = int(self.consulta[:4])
        d = self.focus.get("Selic", {})
        if not d:
            return self.selic_meta
        ult = d[max(d)]
        serie = [float(d.get(ano0 + k, ult)) for k in range(n)]
        return sum(serie) / len(serie)

    @property
    def choque_bps(self) -> float:
        """Diferenca (bps) entre o DI vivo de hoje e o ajuste do ultimo pregao, em ~3 anos."""
        if len(self.di_vivo) < 8 or not self.di_ajuste:
            return 0.0
        du = 252 * 3
        a = interp(self.di_vivo, du)
        b = interp(self.di_ajuste, du)
        return round((a - b) * 100.0, 1) if a is not None and b is not None else 0.0

    @property
    def em_choque(self) -> bool:
        return abs(self.choque_bps) >= 75.0


def _dt(txt: str):
    try:
        return datetime.fromisoformat(txt)
    except (TypeError, ValueError):
        return None


def carregar(hoje: str | None = None, curva: str = "viva") -> Mercado:
    """Le o terminal e monta o Mercado. `hoje` so serve para teste. `curva`: 'viva' usa o ultimo negocio do DI
    de hoje quando houver; 'ontem' fica no ajuste do ultimo pregao (a leitura estrutural, sem o ruido do dia)."""
    hoje = hoje or date.today().isoformat()
    m = Mercado(consulta=hoje)
    rf = _json(C.OUT / "rf.json", {})
    macro = _json(C.OUT / "macro.json", {})
    if not rf:
        m.avisos.append("rf.json ausente: o terminal nao gravou renda fixa (motor parado?)")
        m.veredito = "VELHO"
        return m

    m.gerado = rf.get("gerado", "")
    # --- Selic, CDI, IPCA ---------------------------------------------------------------
    ref = {i["k"]: i for i in rf.get("referencias", {}).get("itens", [])}
    m.selic_meta = float(ref.get("selic_meta", {}).get("valor", 0.0))
    m.cdi = float(ref.get("cdi", {}).get("valor", 0.0))
    m.ipca_12m = float(ref.get("ipca_12m", {}).get("valor", 0.0))
    m.fontes.append(("Selic meta, CDI, IPCA (BCB SGS)", ref.get("cdi", {}).get("data", "")))

    # --- DI: ajuste do ultimo pregao e ultimo negocio de hoje ---------------------------------
    di = rf.get("di", {})
    m.di_data = di.get("data", "")
    m.di_ajuste = [[it["du"], it["taxa"]] for it in di.get("itens", []) if it.get("taxa") is not None]
    intr = di.get("intradia", {})
    if curva == "viva" and intr.get("data") == hoje:
        vivo = [[it["du"], it["intradia"]["taxa"]] for it in di.get("itens", [])
                if it.get("intradia") and it["intradia"].get("taxa") is not None]
        if len(vivo) >= 8:
            m.di_vivo = vivo
            m.di_vivo_hora = intr.get("hora", "")
    m.fontes.append(("Curva DI (B3, ajuste)", m.di_data))
    if m.di_vivo:
        m.fontes.append(("Curva DI (B3, último negócio)", f"{hoje} {m.di_vivo_hora}"))

    # --- NTN-B (juro real) e pre ---------------------------------------------------------------
    real = rf.get("real", {})
    m.ntnb_data = real.get("data", "")
    m.ntnb = real.get("curvas", {}).get("hoje", [])
    m.fontes.append(("NTN-B, juro real (ANBIMA)", m.ntnb_data))
    tpf = rf.get("anbima_tpf", {})
    m.pre = [[it["prazo_anos"], it["taxa_indicativa"]] for it in tpf.get("itens", [])
             if it.get("tipo") in ("LTN", "NTN-F") and it.get("taxa_indicativa") is not None]
    m.fontes.append(("Pré-fixados LTN/NTN-F (ANBIMA)", tpf.get("data", "")))

    # --- Credito privado ---------------------------------------------------------------------------
    for r in rf.get("debentures", {}).get("resumo", []):
        if r.get("spread_mediano") is None:
            continue
        if r["indexador"] == "IPCA+":
            m.deb_ipca_spread_bps = float(r["spread_mediano"])
        elif r["indexador"] == "DI+":
            m.deb_di_spread_bps = float(r["spread_mediano"])
        elif r["indexador"] == "Pré":
            m.deb_pre_spread_bps = float(r["spread_mediano"])
    m.fontes.append(("Debêntures: spread mediano (ANBIMA)", rf.get("debentures", {}).get("data", "")))

    # --- EUA ------------------------------------------------------------------------------------------
    ust = rf.get("ust", {})
    m.ust = [[it["anos"], it["taxa"]] for it in ust.get("curva", []) if it.get("taxa") is not None]
    m.ust_data = ust.get("data", "")
    m.ust10 = float(interp(m.ust, 10.0) or 0.0)
    for it in rf.get("spreads", {}).get("itens", []):
        if it.get("k") == "hy":
            m.spread_hy_bps = it.get("bps")
        elif it.get("k") == "ig":
            m.spread_ig_bps = it.get("bps")
    m.fontes.append(("Treasuries (Tesouro dos EUA)", m.ust_data))

    # --- Focus, dolar, Fed -----------------------------------------------------------------------------
    foc = macro.get("focus", {})
    m.focus_data = foc.get("data", "")
    for it in foc.get("itens", []):
        m.focus.setdefault(it["indicador"], {})[int(it["ano"])] = float(it["mediana"])
    m.fontes.append(("Focus (BCB)", m.focus_data))
    for ind in macro.get("indicadores", []):
        if ind.get("id") == "ptax":
            m.ptax, m.ptax_data = float(ind["valor"]), ind.get("data", "")
        elif ind.get("id") == "fed_funds":
            m.fed_funds = float(ind["valor"])

    # --- IMA ----------------------------------------------------------------------------------------------
    for it in rf.get("referencias", {}).get("ima", {}).get("itens", []):
        m.ima[it["indice"]] = it

    # --- TIR da bolsa (metodo Safra do terminal) ---------------------------------------------------------
    tir = _json(C.OUT / "tir_estado.json", {})
    if tir.get("mediana_tir") is not None:
        m.tir_mediana_real = float(tir["mediana_tir"])
    try:
        con = sqlite3.connect(f"file:{C.BANCO}?mode=ro", uri=True)
        linha = con.execute("select data, k_real_pct from tir_geral order by data desc limit 1").fetchone()
        con.close()
        if linha:
            m.tir_data, m.tir_k_real = linha[0], float(linha[1])
    except sqlite3.Error:
        pass
    m.fontes.append(("TIR mediana da bolsa (método Safra, terminal)", m.tir_data or tir.get("gerado", "")))

    # --- ajustes manuais do analista (choque que o dado ainda nao mostra) ------------------------------------
    m.ajustes = _json(C.CACHE / "ajustes.json", {}) or {}

    # --- frescor e avisos ------------------------------------------------------------------------------------
    g = _dt(m.gerado)
    idade_h = None
    if g is not None:
        agora = datetime.now(g.tzinfo or timezone.utc)
        idade_h = (agora - g).total_seconds() / 3600.0
    dias_ntnb = None
    if m.ntnb_data:
        dias_ntnb = (date.fromisoformat(hoje) - date.fromisoformat(m.ntnb_data)).days
    velho = []
    if idade_h is None or idade_h > 30:
        velho.append(f"rf.json gerado ha {idade_h:.0f} h" if idade_h is not None else "rf.json sem carimbo")
    if dias_ntnb is not None and dias_ntnb > 4:
        velho.append(f"NTN-B de {m.ntnb_data} ({dias_ntnb} dias)")
    if not m.focus:
        velho.append("Focus ausente")
    m.veredito = "VELHO" if velho else "ATUAL"
    m.avisos.extend(f"dado velho: {v}" for v in velho)

    if m.em_choque:
        m.avisos.append(
            f"MERCADO EM CHOQUE: o DI de 3 anos negocia hoje {m.choque_bps:+.0f} pontos-base contra o ajuste de "
            f"{m.di_data}. A NTN-B ({m.ntnb_data}) da ANBIMA ainda nao reflete isso. "
            + ("O juro real usado e ESTIMATIVA (a ANBIMA de ontem mais metade do deslocamento do DI): confirme a taxa no balcao. "
               if "real_bps" not in m.ajustes else f"Deslocamento manual do juro real: {m.ajustes['real_bps']:+.0f} bps. ")
            + "Pre-fixados tambem somam o deslocamento do DI. Para fixar o numero, use `alocar.py ajuste real_bps N`."
        )
    if m.ptax_data and m.ptax_data < hoje:
        m.avisos.append(f"dolar PTAX do terminal e de {m.ptax_data} (fechamento); veja o mini-dolar para o dia")
    return m
