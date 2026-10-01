# Series para os graficos do artifact: preco, MM50, MM200 e RSI dos ultimos ~13 meses
import json
from analise import serie, rsi, OUT
out = {}
for s in ('CSPX.L', 'VHYA.L', 'XAID.L', 'SMH.L', 'IGLN.L', 'CBU7.L'):
    df, d = serie(s)
    c = df['fech'].dropna()
    mm50 = c.rolling(50).mean(); mm200 = c.rolling(200).mean(); r = rsi(c)
    j = c.index[-275:]
    out[s.replace('.L', '')] = {'datas': [x.strftime('%Y-%m-%d') for x in j], 'p': [round(float(c[x]), 2) for x in j],
                               'mm50': [round(float(mm50[x]), 2) for x in j], 'mm200': [round(float(mm200[x]), 2) for x in j],
                               'rsi': [round(float(r[x]), 1) for x in j], 'fonte_pregao_anterior': d.get('pregao_anterior')}
# razao de largura XDEW/CSPX e RSP/SPY normalizada
import pandas as pd
def aj(s):
    df, _ = serie(s); return df['ajust'].fillna(df['fech'])
ra = (aj('XDEW.L') / aj('CSPX.L')).dropna(); rb = (aj('RSP') / aj('SPY')).dropna()
j = pd.concat([ra, rb], axis=1, keys=['xdew', 'rsp']).dropna().loc['2025-06-02':]
j = 100 * j / j.iloc[0]
out['LARGURA'] = {'datas': [x.strftime('%Y-%m-%d') for x in j.index], 'xdew': [round(float(v), 2) for v in j['xdew']], 'rsp': [round(float(v), 2) for v in j['rsp']]}
json.dump(out, open(OUT + 'graf.json', 'w', encoding='utf-8'), separators=(',', ':'))
for k, v in out.items():
    print(k, len(v['datas']), v['datas'][-3:], (v.get('p') or v.get('v') or v.get('xdew'))[-3:], v.get('fonte_pregao_anterior'))
