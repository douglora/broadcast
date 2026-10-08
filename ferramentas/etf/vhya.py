# VHYA em dolar: dividend yield historico (proventos do VHYD), episodios e sensibilidade
import json, math
import numpy as np, pandas as pd
from analise import serie, git_json, OUT
res = {}
def dy_hist(s):
    df, d = serie(s)
    c = df['fech'].dropna()
    dv = pd.Series({pd.Timestamp(a): v for a, v in d['eventos']['dividendos']}).sort_index()
    out = []
    for dt in pd.date_range('2014-06-30', c.index[-1], freq='ME').append(pd.DatetimeIndex([c.index[-1]])):
        p = c.loc[:dt]
        if not len(p): continue
        soma = dv.loc[dt - pd.Timedelta(days=365) + pd.Timedelta(days=1):dt].sum()
        if soma > 0:
            out.append((dt, 100 * soma / p.iloc[-1]))
    return pd.Series(dict(out)), dv
for nome, s in (('VHYD', 'VHYD.L'), ('VWRD', 'VWRD.L')):
    h, dv = dy_hist(s)
    res[f'dy_{nome}'] = {'atual': round(float(h.iloc[-1]), 2), 'data': h.index[-1].strftime('%Y-%m-%d'),
                         'media_desde_2015': round(float(h.loc['2015':].mean()), 2), 'min': [h.idxmin().strftime('%Y-%m'), round(float(h.min()), 2)],
                         'max': [h.idxmax().strftime('%Y-%m'), round(float(h.max()), 2)],
                         'pct_abaixo': round(100 * float((h.loc['2015':] < h.iloc[-1]).mean()), 0),
                         'fim_ano': {str(y): round(float(h.loc[:f'{y}-12-31'].iloc[-1]), 2) for y in range(2015, 2026)},
                         'ultimos_proventos': [(a.strftime('%Y-%m-%d'), round(float(v), 4)) for a, v in dv.iloc[-5:].items()]}
    res[f'_serie_{nome}'] = h
sp = (res['_serie_VHYD'] - res['_serie_VWRD']).dropna()
res['spread_dy_pp'] = {'atual': round(float(sp.iloc[-1]), 2), 'media_desde_2015': round(float(sp.loc['2015':].mean()), 2),
                       'min': [sp.idxmin().strftime('%Y-%m'), round(float(sp.min()), 2)], 'max': [sp.idxmax().strftime('%Y-%m'), round(float(sp.max()), 2)]}
# serie do DY do VHYD para grafico (mensal)
res['dy_mensal'] = [(a.strftime('%Y-%m'), round(float(v), 2), round(float(res['_serie_VWRD'].get(a, np.nan)), 2)) for a, v in res['_serie_VHYD'].items()]
del res['_serie_VHYD'], res['_serie_VWRD']
# episodios em dolar
def janela(a, ini, fim):
    t = a.loc[ini:fim]; pico = t.cummax(); dd = t / pico - 1
    return {'ret': round(100 * (t.iloc[-1] / t.iloc[0] - 1), 1), 'dd': round(100 * float(dd.min()), 1)}
ep = {'2018_4T': ('2018-09-20', '2018-12-24'), '2018_ano': ('2017-12-29', '2018-12-31'), '2022': ('2022-01-03', '2022-10-12'),
      '2023_ago_out': ('2023-07-31', '2023-10-27'), '2020_covid': ('2020-02-19', '2020-03-23')}
epis = {}
for s in ('VHYD.L', 'VWRD.L', 'CSPX.L', 'VHYA.L', 'VWRA.L', 'DGRA.L', 'XDEW.L', 'IWVL.L', 'IGLN.L', 'CBU7.L', 'XAID.L', 'SMH.L', 'IUIT.L', 'CNDX.L', 'WTAI.L', '^GSPC', '^TNX'):
    df, _ = serie(s); a = df['ajust'].fillna(df['fech']).dropna()
    epis[s] = {k: (janela(a, x, y) if a.index[0] <= pd.Timestamp(x) else None) for k, (x, y) in ep.items()}
res['episodios'] = epis
# sensibilidade semanal desde 2019: VHY (VHYD ate a VHYA existir), VWR (VWRD), CSPX
tnx, _ = serie('^TNX'); tw = tnx['fech'].resample('W-FRI').last()
dxy, _ = serie('DX-Y.NYB'); dw = dxy['fech'].resample('W-FRI').last()
def sem(s):
    df, _ = serie(s); return df['ajust'].fillna(df['fech']).resample('W-FRI').last()
sens = {}
for nome, s in (('VHYA (VHYD)', 'VHYD.L'), ('VWRA (VWRD)', 'VWRD.L'), ('CSPX', 'CSPX.L'), ('DGRA', 'DGRA.L'), ('IWVL', 'IWVL.L'), ('XDEW', 'XDEW.L'), ('XAID', 'XAID.L'), ('SMH', 'SMH.L'), ('IGLN', 'IGLN.L'), ('CBU7', 'CBU7.L')):
    p = sem(s)
    d = pd.DataFrame({'r': p.pct_change() * 100, 'dy': tw.diff(), 'dx': dw.pct_change() * 100}).dropna().loc['2019-01-01':]
    X = np.column_stack([np.ones(len(d)), d['dy'], d['dx']])
    b, *_ = np.linalg.lstsq(X, d['r'].values, rcond=None)
    resid = d['r'].values - X @ b
    up = d[d['dy'] >= 0.15]; dn = d[d['dy'] <= -0.15]; usd = d[d['dx'] >= 1.0]
    sens[nome] = {'n': int(len(d)), 'beta_10a_100bp': round(float(b[1]), 2), 'beta_dolar_1pct': round(float(b[2]), 2),
                  'r2': round(float(1 - resid.var() / d['r'].var()), 2),
                  'media_sem_10a_sobe_15bp': round(float(up['r'].mean()), 2), 'n_up': int(len(up)),
                  'media_sem_10a_cai_15bp': round(float(dn['r'].mean()), 2), 'n_dn': int(len(dn)),
                  'media_sem_dolar_sobe_1pct': round(float(usd['r'].mean()), 2), 'n_usd': int(len(usd))}
res['sensibilidade'] = sens
json.dump(res, open(OUT + 'vhya.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
for k in ('dy_VHYD', 'dy_VWRD', 'spread_dy_pp'):
    print(k, json.dumps(res[k], ensure_ascii=False))
for s, e in epis.items(): print(s, e)
for k, v in sens.items(): print(k, v)
