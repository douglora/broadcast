# Analise tecnica e de cenarios dos ETFs a partir de etfs/ no branch dados.
import datetime as _dt, json, math, os, subprocess, sys
import numpy as np, pandas as pd

# Raiz do repositorio e pasta de saida (ignorada pelo git: os JSONs sao dado de mercado)
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
OUT = os.path.join(os.environ.get('ETF_SAIDA', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'saida')), '')
os.makedirs(OUT, exist_ok=True)

def git_json(p):
    return json.loads(subprocess.check_output(['git', 'show', 'origin/dados:' + p], cwd=REPO))

def arq(s):
    return s.replace('^', '_').replace('=', '_').replace('/', '_')

_COT = None
def cotacao(s):
    global _COT
    if _COT is None:
        # uma coleta parcial sobrescreve etfs/cotacoes.json: mescla os ultimos commits, o mais novo vence
        _COT = {}
        refs = subprocess.check_output(['git', 'log', '-n', '6', '--format=%h', 'origin/dados', '--', 'etfs/cotacoes.json'], cwd=REPO).decode().split()
        for ref in reversed(refs):
            txt = subprocess.check_output(['git', 'show', ref + ':etfs/cotacoes.json'], cwd=REPO)
            lote = {q.get('symbol'): q for q in json.loads(txt)['cotacoes']}
            _COTS.append(lote)
            _COT.update(lote)
    return _COT.get(s) or {}

_COTS = []
def cotacao_aberta(s):
    """Cotacao mais recente tirada com o pregao aberto: bid e ask depois do fechamento nao
    representam o spread de quem opera (visto em 29/09/2026 na LSE)."""
    cotacao('')
    for lote in reversed(_COTS):
        q = lote.get(s) or {}
        if q.get('marketState') == 'REGULAR' and q.get('bid') and q.get('ask'):
            return q
    return {}

def barra_livro(s, dia):
    """O livro guarda a barra do pregao anterior (coleta do fechamento); o Yahoo pode omiti-la
    no diario da LSE enquanto o pregao seguinte esta aberto (visto em 28-29/09/2026)."""
    try:
        d = git_json(f'livro/series/{arq(s)}.json')
    except Exception:
        return None
    for b in d.get('barras', []):
        if b[0] == dia:
            return b
    return None

def serie(s):
    d = git_json(f'etfs/series/{arq(s)}.json')
    df = pd.DataFrame(d['barras'], columns=['data', 'abre', 'max', 'min', 'fech', 'ajust', 'vol'])
    df['data'] = pd.to_datetime(df['data'])
    df = df.set_index('data').sort_index()
    df = df[~df.index.duplicated(keep='last')]
    for k in ('abre', 'max', 'min', 'fech', 'ajust', 'vol'):
        df[k] = pd.to_numeric(df[k], errors='coerce')
    # pregao anterior ausente (ultimo dia util antes da ultima barra): livro (OHLC) ou fechamento anterior da cotacao v7
    d['pregao_anterior'] = None
    if len(df) > 2:
        ult = df.index[-1]
        ant = (ult - pd.offsets.BDay(1)).normalize()
        if ant not in df.index and df.index[-2] < ant:
            dia = ant.strftime('%Y-%m-%d')
            b = barra_livro(s, dia)
            if b is not None:
                df.loc[ant] = [b[1], b[2], b[3], b[4], b[5] if b[5] is not None else b[4], b[6]]
                d['pregao_anterior'] = 'livro'
            else:
                # so vale se a cotacao for do mesmo pregao da ultima barra e o fechamento anterior
                # for diferente da penultima barra (senao foi feriado, nao lacuna)
                q = cotacao(s); pc = q.get('regularMarketPreviousClose'); t = q.get('regularMarketTime')
                mesmo_dia = bool(t) and _dt.datetime.fromtimestamp(t, _dt.timezone.utc).date() == ult.date()
                if pc and mesmo_dia and abs(pc - float(df['fech'].iloc[-2])) > 1e-9:
                    df.loc[ant] = [pc, pc, pc, pc, pc, np.nan]
                    d['pregao_anterior'] = 'cotacao_v7'
            df = df.sort_index()
    return df, d

def rsi(c, n=14):
    d = c.diff(); up = d.clip(lower=0); dn = -d.clip(upper=0)
    au = up.ewm(alpha=1/n, adjust=False).mean(); ad = dn.ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + au / ad)

def macd(c):
    m = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    return m, m.ewm(span=9, adjust=False).mean()

def atr(df, n=14):
    h, l, c = df['max'], df['min'], df['fech']
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def extremos(s, janela, fn):
    v = s.values; out = []
    for i in range(janela, len(v) - janela):
        if not np.isnan(v[i]) and v[i] == fn(v[i-janela:i+janela+1]):
            out.append((s.index[i].strftime('%d/%m/%Y'), round(float(v[i]), 2)))
    return out

def tecnica(s, df, ate=None):
    df = df.dropna(subset=['fech'])
    if ate is not None:
        df = df.loc[:ate]
    c = df['fech']; a = df['ajust'].fillna(c)
    r = {'simbolo': s, 'ultima': c.index[-1].strftime('%Y-%m-%d'), 'preco': round(float(c.iloc[-1]), 4), 'barras': len(c)}
    for k in (20, 50, 100, 200):
        mm = c.rolling(k).mean()
        if len(c) > k + 21:
            r[f'mm{k}'] = round(float(mm.iloc[-1]), 4)
            r[f'dist_mm{k}'] = round(100 * (c.iloc[-1] / mm.iloc[-1] - 1), 2)
            r[f'incl_mm{k}_20d'] = round(100 * (mm.iloc[-1] / mm.iloc[-21] - 1), 2)
    # a barra de hoje e parcial enquanto o pregao esta aberto: fica fora da maxima e da minima de fechamento
    cf = c.iloc[:-1] if c.index[-1].date() >= _dt.date.today() else c
    r['parcial'] = bool(len(cf) < len(c))
    j = cf.loc[cf.index[-1] - pd.Timedelta(days=365):]
    r['max52_fech'] = [j.idxmax().strftime('%Y-%m-%d'), round(float(j.max()), 4)]
    r['min52_fech'] = [j.idxmin().strftime('%Y-%m-%d'), round(float(j.min()), 4)]
    r['dist_max52'] = round(100 * (c.iloc[-1] / j.max() - 1), 2)
    jh = df['max'].loc[j.index[0]:]
    r['max52_intradia'] = round(float(jh.max()), 4) if jh.notna().any() else None
    rs = rsi(c); r['rsi14'] = round(float(rs.iloc[-1]), 1); r['rsi14_5d'] = [round(float(x), 1) for x in rs.iloc[-5:]]
    m, sg = macd(c); r['macd'] = round(float(m.iloc[-1]), 4); r['macd_sinal'] = round(float(sg.iloc[-1]), 4)
    r['macd_hist_5d'] = [round(float(x), 4) for x in (m - sg).iloc[-5:]]
    mm20 = c.rolling(20).mean(); dp = c.rolling(20).std()
    r['boll_pctb'] = round(float((c.iloc[-1] - (mm20.iloc[-1] - 2 * dp.iloc[-1])) / (4 * dp.iloc[-1])), 2)
    r['boll_inf'] = round(float(mm20.iloc[-1] - 2 * dp.iloc[-1]), 4)
    r['atr14'] = round(float(atr(df).iloc[-1]), 4)
    lr = np.log(a).diff().dropna()
    r['vol3m'] = round(float(lr.iloc[-63:].std() * math.sqrt(252) * 100), 1)
    r['vol12m'] = round(float(lr.iloc[-252:].std() * math.sqrt(252) * 100), 1)
    for rot, k in (('1s', 5), ('1m', 21), ('3m', 63), ('6m', 126), ('12m', 252)):
        if len(a) > k:
            r[f'ret_{rot}'] = round(100 * (a.iloc[-1] / a.iloc[-1 - k] - 1), 1)
    fim25 = a.loc[:'2025-12-31']
    if len(fim25):
        r['ret_ytd'] = round(100 * (a.iloc[-1] / fim25.iloc[-1] - 1), 1)
    pico = a.cummax(); r['dd_atual_ajust'] = round(100 * (a.iloc[-1] / pico.iloc[-1] - 1), 1)
    u = df.loc[df.index[-1] - pd.Timedelta(days=200):]
    r['topos'] = extremos(u['fech'], 5, max)[-8:]
    r['fundos'] = extremos(u['fech'], 5, min)[-8:]
    v = df['vol'].replace(0, np.nan)
    r['vol_med'] = {k: (round(float(v.iloc[-k:].mean()), 0) if v.iloc[-k:].notna().any() else None) for k in (20, 60, 252)}
    # semanal
    w = c.resample('W-FRI').last().dropna()
    if len(w) > 45:
        r['sem_mm10'] = round(float(w.rolling(10).mean().iloc[-1]), 4)
        r['sem_mm40'] = round(float(w.rolling(40).mean().iloc[-1]), 4)
        r['sem_incl_mm40_4s'] = round(100 * (w.rolling(40).mean().iloc[-1] / w.rolling(40).mean().iloc[-5] - 1), 2)
        r['sem_rsi14'] = round(float(rsi(w).iloc[-1]), 1)
        mw, sw = macd(w); r['sem_macd_hist'] = round(float((mw - sw).iloc[-1]), 4)
        r['sem_ult8'] = [(i.strftime('%d/%m'), round(float(x), 2)) for i, x in w.iloc[-8:].items()]
    return r

def fib(df, ini, fim):
    c = df['fech']
    trecho = c.loc[ini:fim]
    lo_d, hi_d = trecho.idxmin(), trecho.idxmax()
    lo, hi = float(trecho.min()), float(trecho.max())
    return {'fundo': [lo_d.strftime('%Y-%m-%d'), round(lo, 2)], 'topo': [hi_d.strftime('%Y-%m-%d'), round(hi, 2)],
            **{f'{int(p*1000)/10}%': round(hi - p * (hi - lo), 2) for p in (0.236, 0.382, 0.5, 0.618)}}

EVENTO = {  # peso >= 10% num nome com resultado nos proximos dias (Micron em 30/09, apos o fechamento em NY)
    'IWVL.L': 'Micron 14% da carteira, resultado 30/09',
    'IUVL.L': 'Micron 21% da carteira, resultado 30/09',
    'SMH.L': 'Micron 11% da carteira, resultado 30/09',
    'EMVL.L': 'SK hynix + Samsung 16,5%, leem o resultado da Micron',
}

def classifica(r):
    """Regra fixada antes de ver os dados: tendencia + pullback + nao esticado.
    Pullback = 2% a 10% abaixo da maxima de fechamento de 52 semanas, ou RSI < 45.
    Queda maior que 10% e correcao, nao pullback; maior que 20%, mercado de baixa."""
    s = r['simbolo']
    dmax = r['dist_max52']
    alta = r.get('dist_mm200', -99) > 0 and r.get('incl_mm200_20d', -99) > 0 and r.get('mm50', 0) > r.get('mm200', 1e9)
    mm200_sobe = r.get('incl_mm200_20d', -99) > 0
    pullback = (-10 <= dmax <= -2) or (r['rsi14'] < 45 and dmax >= -10)
    esticado = r.get('dist_mm50', 0) > 5 or r['rsi14'] > 65 or r.get('dist_mm200', 0) > 15
    if (r.get('dist_mm200', 99) < 0 and not mm200_sobe) or (r.get('mm50', 0) < r.get('mm200', 0) and r.get('dist_mm200', 0) < 0):
        return 'Esperar', 'abaixo da MM200 em queda, ou MM50 abaixo da MM200'
    if dmax < -20:
        return 'Esperar', 'queda maior que 20% da maxima'
    if s in EVENTO:
        return 'Em parcelas', 'evento binario: ' + EVENTO[s]
    if r.get('vol3m', 0) > 35:
        return 'Em parcelas', f"volatilidade de 3 meses de {r['vol3m']}%"
    if dmax < -10:
        return 'Em parcelas', 'correcao de 10% a 20% com MM200 subindo' if mm200_sobe else 'correcao de 10% a 20%'
    if alta and pullback and not esticado:
        return 'Entrada agora', 'tendencia de alta com pullback e sem esticar'
    if alta and esticado:
        return 'Em parcelas', 'tendencia de alta, mas esticado'
    if alta:
        return 'Em parcelas', 'tendencia de alta sem pullback'
    return 'Em parcelas', 'tendencia indefinida'

if __name__ == '__main__':
    simbolos = sys.argv[1].split(',')
    out = {}
    for s in simbolos:
        try:
            df, d = serie(s)
            r = tecnica(s, df)
            r['classe'] = classifica(r)
            r['moeda'] = d.get('moeda'); r['estado'] = d.get('meta', {}).get('marketState'); r['pregao_anterior'] = d.get('pregao_anterior')
            out[s] = r
        except Exception as e:
            out[s] = {'erro': f'{type(e).__name__}: {e}'}
    json.dump(out, open(OUT + 'tecnica.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    for s, r in out.items():
        if 'erro' in r:
            print(s, r['erro']); continue
        print(f"{s:9} {r['ultima']} {r['preco']:>10} max52 {r['dist_max52']:>6}% mm50 {r.get('dist_mm50')}% mm200 {r.get('dist_mm200')}% "
              f"rsi {r['rsi14']} 1m {r.get('ret_1m')} 12m {r.get('ret_12m')} vol3m {r['vol3m']} -> {r['classe'][0]}")
