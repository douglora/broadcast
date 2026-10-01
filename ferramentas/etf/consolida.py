import json, subprocess, re
import pandas as pd
from analise import git_json, REPO, OUT, serie, fib, cotacao, cotacao_aberta
t = json.load(open(OUT + 'tecnica.json', encoding='utf-8'))
ia = json.load(open(OUT + 'ia.json', encoding='utf-8'))['etfs']
je = json.load(open(OUT + 'justetf.json', encoding='utf-8'))
cotacao('')  # carrega a mescla das ultimas coletas
import analise
cot = analise._COT
av = subprocess.check_output(['git', 'show', 'origin/dados:etfs/docs/avenue_ucits.txt'], cwd=REPO).decode()
def avenue(tk):
    for ln in av.splitlines():
        m = re.match(r'^(.*?)\s' + re.escape(tk) + r'\s(.+?)\s([A-Z]{2}[A-Z0-9]{10})\s([\d\.]+)\s(.+?)\s([\d,]+%)\s*$', ln)
        if m:
            return {'categoria': m.group(1), 'nome': m.group(2), 'isin': m.group(3), 'aum_mi_usd_31mar': m.group(4), 'gestora': m.group(5), 'ter': m.group(6)}
    return None
U = ['CSPX','VHYA','DGRA','IWVL','XEOU','IJPD','QNTM','VDCA','CBU7','IB01','STYC','IGLN','VWRA','XDEW','R2US','EMVL','IUVL','CMOD',
     'XAID','SMH','WTAI','IUIT','XDWT','CNDX','GRDU','VPN','NUCL','COPX','CIBR','USPY','DFNS','REMX','IUUS','URNU','IUES']
out = {}
for tk in U:
    s = tk + '.L'; r = t.get(s, {}); q = cot.get(s, {}); j = je.get(tk, {}); a = avenue(tk)
    try:
        m = git_json(f'etfs/meta/{s}.json')
        aum_y = (m.get('summaryDetail') or {}).get('totalAssets') or (m.get('defaultKeyStatistics') or {}).get('totalAssets')
        eh = (m.get('topHoldings') or {}).get('equityHoldings') or {}
        pl = round(1 / eh['priceToEarnings'], 1) if eh.get('priceToEarnings') else None
        pvp = round(1 / eh['priceToBook'], 2) if eh.get('priceToBook') else None
    except Exception:
        aum_y = None; pl = pvp = None
    qa = cotacao_aberta(s)  # spread so com o pregao aberto
    bid, ask = qa.get('bid'), qa.get('ask')
    spread = round(100 * (ask - bid) / ((ask + bid) / 2), 3) if bid and ask and ask > bid > 0 else None
    vol3m = q.get('averageDailyVolume3Month')
    px = r.get('preco')
    out[tk] = {
        'preco': px, 'classe': r.get('classe'), 'dist_max52': r.get('dist_max52'), 'max52': r.get('max52_fech'), 'min52': r.get('min52_fech'),
        'mm20': r.get('mm20'), 'mm50': r.get('mm50'), 'mm100': r.get('mm100'), 'mm200': r.get('mm200'),
        'incl50': r.get('incl_mm50_20d'), 'incl200': r.get('incl_mm200_20d'), 'd50': r.get('dist_mm50'), 'd200': r.get('dist_mm200'),
        'rsi': r.get('rsi14'), 'vol3m': r.get('vol3m'), 'ret1m': r.get('ret_1m'), 'ret12m': r.get('ret_12m'), 'ytd': r.get('ret_ytd'),
        'topos': r.get('topos'), 'fundos': r.get('fundos'), 'atr': r.get('atr14'), 'macd_hist': (r.get('macd_hist_5d') or [None])[-1],
        'sem_mm40': r.get('sem_mm40'), 'sem_rsi': r.get('sem_rsi14'),
        'bid': bid, 'ask': ask, 'spread_pct': spread, 'vol_med_3m_cotas': vol3m, 'giro_dia_usd_mi': round(vol3m * px / 1e6, 2) if vol3m and px else None,
        'aum_yahoo_bi': round(aum_y / 1e9, 2) if aum_y else None, 'pl_morningstar': pl, 'pvp_morningstar': pvp,
        'ter_justetf': j.get('ter'), 'tamanho_justetf': j.get('tamanho'), 'indice': j.get('indice'), 'nome': j.get('nome'), 'data_carteira': j.get('data_carteira'),
        'top10_justetf': j.get('top10'), 'peso_top10': j.get('peso_top10'), 'avenue': a,
        'ia': ia.get(s),
    }
json.dump(out, open(OUT + 'consolidado.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
for tk, v in out.items():
    print(f"{tk:5} {v['preco']:>9} {str(v['classe'][0] if v['classe'] else None):13} sprd {v['spread_pct']} giro {v['giro_dia_usd_mi']} aumY {v['aum_yahoo_bi']} TER {v['ter_justetf']} av {(v['avenue'] or {}).get('ter')} PL {v['pl_morningstar']} PVP {v['pvp_morningstar']} idx {str(v['indice'])[:45]}")
