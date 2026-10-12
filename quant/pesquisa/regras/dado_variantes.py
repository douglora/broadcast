"""
Variantes SO MEDIDAS da reversao do dado (estudo de 12/10/2026, rodadas 2 e 3): a mesma regra congelada (2 min, gatilho 3
pontos, stop 40, tempo 120), filtrada por um rotulo conhecido no instante do sinal. Nenhuma passou o criterio de candidata
na descoberta (todas com n < 200); entram na prova viva para serem cobradas com dado NOVO, contra a referencia
`dado_base` medida nos mesmos pregoes. Gate (prova_viva.py): 60 negocios, media positiva e t >= 2; para virar regra ainda
precisa render mais que a base nos mesmos dias e do "pode" do Douglas por escrito. Nada aqui opera.
"""
import numpy as np
import pandas as pd

from quant.dados import calendario_eua as ce
from quant.pesquisa import lab
from quant.saida.pesquisa5.calendario import regras

PARAM = dict(r=2, thr=3.0)
SAIDA = dict(stop=40.0, alvo=None, tempo=120)


def base(m):
    """A regra congelada, como referencia nos mesmos pregoes."""
    return regras.reverte_dado_ny(m, **PARAM)


def _dias(m):
    return pd.DatetimeIndex(pd.to_datetime(lab.dia(m)))


def _por_dia(m, ok):
    """Vetor por barra (1.0 nos dias em que `ok` (Series indexada por dia) e True)."""
    d = _dias(m)
    return pd.Series(ok).reindex(d).fillna(False).to_numpy(dtype=bool).astype(float)


def so_dia_de_dado(m):
    """So nos dias com divulgacao conhecida as 8h30 de NY (calendario do BLS e pedidos de auxilio). Descoberta: +R$ 137/neg
    (t 3,2) contra +100 da base; por pregao rende menos (R$ 31 contra 42), por isso nao filtra a regra."""
    mapa = ce.tipos_por_dia()
    dias = sorted(set(_dias(m)))
    ok = pd.Series({d: ce.tipo_do_dia(d.date(), mapa) != "nenhum" for d in dias})
    return base(m) * _por_dia(m, ok)


def vol_alta(m):
    """So com a vol realizada do dolar (20 pregoes) acima da mediana movel de 1 ano, tudo conhecido na vespera (tabela de
    regimes do terminal). Descoberta: +R$ 181/neg (n 128) contra +51 com vol baixa."""
    from quant.pesquisa import regimes
    f = regimes.tabela()
    if f.empty or "usdbrl_vol20" not in f:
        return np.zeros(len(m))
    alta = (f.usdbrl_vol20 > f.usdbrl_vol20.rolling(252, min_periods=120).median().shift(1)).to_frame("alta")
    ok = regimes.no_dia(alta, sorted(set(_dias(m))))["alta"].fillna(False).astype(bool)
    return base(m) * _por_dia(m, ok)


def ontem_perdeu(m):
    """So no pregao seguinte a um negocio perdedor da propria regra (resultado conhecido na vespera). Descoberta: +R$ 176/neg
    (n 142, t 3,7, 7 de 7 semestres) contra +48 depois de um ganho."""
    s = base(m)
    t = lab.medir(lab.negocios(m, s, SAIDA["stop"], SAIDA["alvo"], SAIDA["tempo"], tick=0.5))
    if not len(t):
        return np.zeros(len(m))
    res = t.groupby(pd.to_datetime(t.dia)).res.sum()
    dias = pd.DatetimeIndex(sorted(set(_dias(m))))
    ultimo = res.reindex(dias).ffill(limit=10).shift(1)           # resultado do ultimo setup operado antes de hoje
    ok = (ultimo <= 0) & ultimo.notna()
    return s * _por_dia(m, ok)


def contra_surpresa(m):
    """So quando a reacao dos 2 minutos foi CONTRA o sentido da surpresa real (|S| >= 0,5; S do calendario do MetaTrader,
    reexportado por mes: sem a exportacao do mes, o dia fica sem S e nao conta). Descoberta: +R$ 228/neg (n 56) contra +71 a favor."""
    s = base(m)
    S = ce.tabela_surpresa_dia()
    if S.empty:
        return np.zeros(len(m))
    Sd = S.S.reindex(_dias(m)).to_numpy(dtype=float)
    mv = np.nan_to_num(regras._mov(m, PARAM["r"]))
    contra = (np.sign(mv) == -np.sign(Sd)) & (np.abs(Sd) >= 0.5)
    return np.where(contra & ~np.isnan(Sd), s, 0.0)
