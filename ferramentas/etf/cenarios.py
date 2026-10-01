# Cenarios: episodios de alta de juros, sazonalidade, largura de mercado e sensibilidade do VHYA.
import json, math, sys
import numpy as np, pandas as pd
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analise import serie, OUT

res = {}
spx, _ = serie('^GSPC'); spx = spx['fech'].dropna()
tnx, _ = serie('^TNX'); tnx = tnx['fech'].dropna()

def janela(s, ini, fim):
    t = s.loc[ini:fim]
    pico = t.cummax(); dd = (t / pico - 1)
    fundo = dd.idxmin()
    return {'ini': [t.index[0].strftime('%Y-%m-%d'), round(float(t.iloc[0]), 2)], 'fim': [t.index[-1].strftime('%Y-%m-%d'), round(float(t.iloc[-1]), 2)],
            'ret_pct': round(100 * (t.iloc[-1] / t.iloc[0] - 1), 1), 'dd_max_pct': round(100 * float(dd.min()), 1),
            'fundo': fundo.strftime('%Y-%m-%d'), 'pico_antes': t.loc[:fundo].idxmax().strftime('%Y-%m-%d')}

ep = {
    '2004-06 (Fed de 1% a 5,25%)': ('2004-06-29', '2006-06-30'),
    '2018 (20/09 a 24/12)': ('2018-09-20', '2018-12-24'),
    '2018 ano todo': ('2017-12-29', '2018-12-31'),
    '2022 (03/01 a 12/10)': ('2022-01-03', '2022-10-12'),
}
res['episodios_spx'] = {k: janela(spx, a, b) for k, (a, b) in ep.items()}
res['episodios_tnx'] = {k: {'ini': round(float(tnx.loc[a:b].iloc[0]), 2), 'fim': round(float(tnx.loc[a:b].iloc[-1]), 2),
                            'max': round(float(tnx.loc[a:b].max()), 2)} for k, (a, b) in ep.items()}

# ETFs nos mesmos episodios (retorno total pelo fechamento ajustado)
etfs = {}
for s in ('CSPX.L', 'VHYL.L', 'VWRL.L', 'VHYA.L', 'VWRA.L', 'DGRA.L', 'IWVL.L', 'IJPD.L', 'XEOU.L', 'IGLN.L', 'CBU7.L', 'IUIT.L', 'CNDX.L', 'SMH.L', 'XDEW.L'):
    try:
        df, _ = serie(s); a = df['ajust'].fillna(df['fech']).dropna()
        linha = {'inicio_serie': a.index[0].strftime('%Y-%m-%d')}
        for k, (x, y) in ep.items():
            if a.index[0] <= pd.Timestamp(x):
                linha[k] = janela(a, x, y)
        etfs[s] = linha
    except Exception as e:
        etfs[s] = {'erro': str(e)[:80]}
res['episodios_etfs'] = etfs

# Sazonalidade do S&P 500 desde 1950
m = spx.loc['1949-12-01':].resample('ME').last().pct_change().dropna() * 100
m.index = m.index.to_period('M')
out = m[m.index.month == 10]
res['outubro'] = {'n': int(len(out)), 'media': round(float(out.mean()), 2), 'mediana': round(float(out.median()), 2),
                  'pct_positivo': round(100 * float((out > 0).mean()), 0), 'pior': [str(out.idxmin()), round(float(out.min()), 1)],
                  'melhor': [str(out.idxmax()), round(float(out.max()), 1)]}
midterm = [a for a in range(1950, 2026) if (a - 1950) % 4 == 2]  # 1950 nao: 1954, 1958 ... 2022
midterm = [a for a in range(1954, 2026, 4)]
q4 = {}
for a in range(1950, 2026):
    try:
        ini = spx.loc[:f'{a}-09-30'].iloc[-1]; fim = spx.loc[:f'{a}-12-31'].iloc[-1]
        q4[a] = 100 * (fim / ini - 1)
    except Exception:
        pass
q4 = pd.Series(q4)
res['q4'] = {'todos_media': round(float(q4.mean()), 2), 'todos_pct_pos': round(100 * float((q4 > 0).mean()), 0),
             'midterm_media': round(float(q4[q4.index.isin(midterm)].mean()), 2),
             'midterm_pct_pos': round(100 * float((q4[q4.index.isin(midterm)] > 0).mean()), 0),
             'midterm_anos': {int(a): round(float(v), 1) for a, v in q4[q4.index.isin(midterm)].items()}}
out_mid = out[[p.year in midterm for p in out.index]]
res['outubro_midterm'] = {'n': int(len(out_mid)), 'media': round(float(out_mid.mean()), 2), 'pct_pos': round(100 * float((out_mid > 0).mean()), 0),
                          'anos': {str(p): round(float(v), 1) for p, v in out_mid.items()}}
# 12 meses depois de 30/09 em anos de midterm
d12 = {}
for a in midterm:
    try:
        ini = spx.loc[:f'{a}-09-30'].iloc[-1]; fim = spx.loc[:f'{a+1}-09-30'].iloc[-1]
        d12[a] = round(100 * (fim / ini - 1), 1)
    except Exception:
        pass
res['midterm_12m_depois_set'] = {'media': round(float(np.mean(list(d12.values()))), 1), 'pct_pos': round(100 * np.mean([v > 0 for v in d12.values()]), 0), 'anos': d12}

# Largura: RSP/SPY, XDEW/CSPX, ^SPXEW/^GSPC
def razao(a, b, nome):
    x, _ = serie(a); y, _ = serie(b)
    r = (x['ajust'].fillna(x['fech']) / y['ajust'].fillna(y['fech'])).dropna()
    r = r.loc['2015-01-01':]
    mm200 = r.rolling(200).mean()
    o = {'ultima': r.index[-1].strftime('%Y-%m-%d')}
    for rot, k in (('1m', 21), ('3m', 63), ('6m', 126), ('12m', 252)):
        o[f'rel_{rot}_pp'] = round(100 * (r.iloc[-1] / r.iloc[-1 - k] - 1), 1)
    fim25 = r.loc[:'2025-12-31'].iloc[-1]; o['rel_ytd_pp'] = round(100 * (r.iloc[-1] / fim25 - 1), 1)
    o['vs_mm200_pct'] = round(100 * (r.iloc[-1] / mm200.iloc[-1] - 1), 1)
    o['min_desde'] = r.loc[:r.index[-1] - pd.Timedelta(days=5)].loc[lambda s: s <= r.iloc[-1]].index[-1].strftime('%Y-%m-%d') if (r.iloc[:-5] <= r.iloc[-1]).any() else 'minima da serie desde 2015'
    return o
res['largura'] = {}
for a, b in (('RSP', 'SPY'), ('XDEW.L', 'CSPX.L'), ('^SPXEW', '^GSPC')):
    try:
        res['largura'][f'{a}/{b}'] = razao(a, b, f'{a}/{b}')
    except Exception as e:
        res['largura'][f'{a}/{b}'] = {'erro': str(e)[:80]}

# Sensibilidade semanal a juros (10a) e dolar: VHYA (VHYL antes de 2020), VWRA (VWRL), CSPX
def semanal(s):
    df, _ = serie(s); return df['ajust'].fillna(df['fech']).resample('W-FRI').last()
dxy, _ = serie('DX-Y.NYB'); dxy = dxy['fech'].resample('W-FRI').last()
tw = tnx.resample('W-FRI').last()
sens = {}
for nome, s in (('VHYL', 'VHYL.L'), ('VWRL', 'VWRL.L'), ('CSPX', 'CSPX.L'), ('IWVL', 'IWVL.L'), ('DGRA', 'DGRA.L'), ('XDEW', 'XDEW.L')):
    try:
        p = semanal(s)
        d = pd.DataFrame({'r': p.pct_change() * 100, 'dy': tw.diff(), 'dx': dxy.pct_change() * 100}).dropna().loc['2019-01-01':]
        X = np.column_stack([np.ones(len(d)), d['dy'], d['dx']])
        b, *_ = np.linalg.lstsq(X, d['r'].values, rcond=None)
        resid = d['r'].values - X @ b
        r2 = 1 - resid.var() / d['r'].var()
        sens[nome] = {'n_semanas': int(len(d)), 'beta_10a_por_100bp': round(float(b[1]), 2), 'beta_dolar_por_1pct': round(float(b[2]), 2), 'r2': round(float(r2), 2)}
    except Exception as e:
        sens[nome] = {'erro': str(e)[:80]}
res['sensibilidade_semanal_desde_2019'] = sens

json.dump(res, open(OUT + 'cenarios.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps(res, ensure_ascii=False, indent=1)[:6000])
