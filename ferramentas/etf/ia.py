# ETFs de IA contra o CSPX: sobreposicao (top 10 x carteira do SPY de 28/09), correlacao, beta, drawdowns
import json, subprocess, math
import numpy as np, pandas as pd
import os
from analise import serie, git_json, OUT, REPO
# carteira diaria do SPY (State Street), guardada pelo coletor em etfs/docs/spy_carteira.xlsx
if not os.path.exists(OUT + 'spy_pesos.csv'):
    with open(OUT + 'spy.xlsx', 'wb') as f:
        f.write(subprocess.check_output(['git', 'show', 'origin/dados:etfs/docs/spy_carteira.xlsx'], cwd=REPO))
    bruto = pd.read_excel(OUT + 'spy.xlsx', header=None)
    linha = next(i for i in range(15) if 'Ticker' in [str(v) for v in bruto.iloc[i].values])
    pd.read_excel(OUT + 'spy.xlsx', header=linha).to_csv(OUT + 'spy_pesos.csv', index=False)
spy = pd.read_csv(OUT + 'spy_pesos.csv')
spy = spy[spy['Ticker'].notna()]
w_spx = {str(t).strip(): float(w) for t, w in zip(spy['Ticker'], spy['Weight']) if pd.notna(w)}
res = {'spy_data': '28/09/2026', 'spy_top10': round(sum(sorted(w_spx.values(), reverse=True)[:10]), 2)}
cspx_df, _ = serie('CSPX.L'); cs = cspx_df['ajust'].fillna(cspx_df['fech'])
out = {}
for s in ['IUUS.L','URNU.L','XAID.L','SMH.L','WTAI.L','IUIT.L','XDWT.L','CNDX.L','GRDU.L','VPN.L','NUCL.L','COPX.L','CIBR.L','USPY.L','QNTM.L','DFNS.L','REMX.L','VHYA.L','VWRA.L','DGRA.L','IWVL.L','XDEW.L','IJPD.L','XEOU.L','IGLN.L','CBU7.L','VDCA.L','STYC.L','IB01.L','EMVL.L','R2US.L','CMOD.L','IUVL.L']:
    r = {}
    try:
        m = git_json(f'etfs/meta/{s}.json')
        hs = (m.get('topHoldings') or {}).get('holdings', [])
        top = [(h.get('symbol'), 100 * h.get('holdingPercent', 0)) for h in hs]
        r['top10'] = [(a, round(b, 2)) for a, b in top]
        r['peso_top10'] = round(sum(b for _, b in top), 2)
        r['top10_em_sp500'] = round(sum(b for a, b in top if a in w_spx), 2)
        r['sobrep_top10_min'] = round(sum(min(b, w_spx.get(a, 0)) for a, b in top), 2)
        r['nvda'] = round(dict(top).get('NVDA', 0), 2)
    except Exception as e:
        r['erro_meta'] = str(e)[:60]
    try:
        df, _ = serie(s); a = df['ajust'].fillna(df['fech'])
        j = pd.concat([a, cs], axis=1, keys=['x', 'c']).dropna()
        wk = j.resample('W-FRI').last().pct_change().dropna()
        for rot, n in (('1a', 52), ('3a', 156)):
            if len(wk) >= n:
                t = wk.iloc[-n:]
                r[f'corr_{rot}'] = round(float(t['x'].corr(t['c'])), 2)
                r[f'beta_{rot}'] = round(float(np.cov(t['x'], t['c'])[0, 1] / t['c'].var()), 2)
        # drawdown 2022 (pico 2021-2022 ao fundo 2022) e maximo historico
        if a.index[0] <= pd.Timestamp('2021-06-30'):
            t = a.loc['2021-01-01':'2022-12-31']; pico = t.cummax(); dd = t / pico - 1
            r['dd_2022'] = round(100 * float(dd.min()), 1); r['fundo_2022'] = dd.idxmin().strftime('%Y-%m-%d')
        pico = a.cummax(); dd = a / pico - 1
        r['dd_max_hist'] = round(100 * float(dd.min()), 1); r['dd_max_data'] = dd.idxmin().strftime('%Y-%m-%d')
        r['inicio'] = a.index[0].strftime('%Y-%m-%d')
        lr = np.log(a).diff().dropna()
        r['vol_1a'] = round(float(lr.iloc[-252:].std() * math.sqrt(252) * 100), 1)
    except Exception as e:
        r['erro_serie'] = str(e)[:60]
    out[s] = r
res['etfs'] = out
json.dump(res, open(OUT + 'ia.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('SPY top10', res['spy_top10'])
for s, r in out.items():
    print(f"{s:7} top10 {r.get('peso_top10')} emSP {r.get('top10_em_sp500')} min {r.get('sobrep_top10_min')} nvda {r.get('nvda')} corr1a {r.get('corr_1a')} beta1a {r.get('beta_1a')} corr3a {r.get('corr_3a')} beta3a {r.get('beta_3a')} dd22 {r.get('dd_2022')} ddmax {r.get('dd_max_hist')} {r.get('dd_max_data')} vol1a {r.get('vol_1a')} ini {r.get('inicio')}")
