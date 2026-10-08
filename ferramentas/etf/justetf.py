# Le os perfis do justETF guardados em etfs/justetf/<ISIN>.html (branch dados).
import re, html, json, subprocess
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analise import REPO, OUT

def texto(isin):
    h = subprocess.check_output(['git', 'show', f'origin/dados:etfs/justetf/{isin}.html'], cwd=REPO).decode('utf-8', 'replace')
    t = re.sub(r'<[^>]+>', ' | ', h); t = html.unescape(re.sub(r'\s+', ' ', t))
    return re.sub(r'(\s*\|\s*)+', ' | ', t)

def campo(t, rotulo, rx=r'([^|]+)'):
    m = re.search(re.escape(rotulo) + r'\s*\|\s*' + rx, t)
    return m.group(1).strip() if m else None

def lista(t, titulo, fim_rx):
    i = t.find(titulo)
    if i < 0: return []
    trecho = t[i + len(titulo): i + len(titulo) + 1500]
    j = re.search(fim_rx, trecho)
    if j: trecho = trecho[:j.start()]
    pares = re.findall(r'\|\s*([^|%]{2,60}?)\s*\|\s*(-?\d+[.,]?\d*)%', trecho)
    return [(n.strip(), float(v.replace(',', '.'))) for n, v in pares]

def perfil(isin):
    t = texto(isin)
    r = {'isin': isin}
    r['nome'] = (re.search(r'^\s*\|?\s*([^|]{10,140}?(?:ETF|ETC)[^|]{0,60}?)\s*\|', t) or [None, None])[1]
    r['indice'] = campo(t, 'Index')
    r['ter'] = campo(t, 'Total expense ratio', r'([\d.,]+% p\.a\.)')
    r['tamanho'] = campo(t, 'Fund size', r'(EUR [\d,\.]+ m)')
    r['replicacao'] = campo(t, 'Replication', r'([A-Za-z ]+)')
    r['distribuicao'] = campo(t, 'Distribution policy')
    r['cambio'] = campo(t, 'Currency risk')
    r['inicio'] = campo(t, 'Inception/ Listing Date')
    r['n_posicoes'] = campo(t, 'Holdings', r'(\d[\d,]*)')
    m = re.search(r'Weight of top 10 holdings\s*\|\s*out of ([\d,]+)\s*\|\s*([\d.]+)%', t)
    if m: r['n_carteira'] = m.group(1); r['peso_top10'] = float(m.group(2))
    r['top10'] = lista(t, 'Top 10 Holdings', r'Countries')[1:] if 'Top 10 Holdings' in t else []
    r['top10'] = [x for x in r['top10'] if not x[0].startswith('Weight')]
    r['paises'] = lista(t, 'Countries', r'Sectors')
    r['setores'] = lista(t, 'Sectors', r'Show more|As of')
    m = re.search(r'As of (\d\d/\d\d/\d{4})', t); r['data_carteira'] = m.group(1) if m else None
    r['vol_1a_eur'] = campo(t, 'Volatility 1 year (in EUR)', r'([\d.]+%)')
    r['div_atual'] = campo(t, 'Current dividend yield', r'([\d.]+%)')
    r['div_12m'] = campo(t, 'Dividends (last 12 months)', r'([^|]+)')
    return r

if __name__ == '__main__':
    usados = json.loads(subprocess.check_output(['git', 'show', 'origin/dados:etfs/isins.json'], cwd=REPO))['usados']
    arquivos = subprocess.check_output(['git', 'ls-tree', '--name-only', 'origin/dados', 'etfs/justetf/'], cwd=REPO).decode().split()
    tem = {a.split('/')[-1][:-5] for a in arquivos}
    out = {}
    for t, isin in sorted(usados.items()):
        if isin in tem:
            try: out[t] = perfil(isin)
            except Exception as e: out[t] = {'isin': isin, 'erro': str(e)[:80]}
    json.dump(out, open(OUT + 'justetf.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    for t, r in out.items():
        print(t, r.get('isin'), '|', r.get('nome'), '|', r.get('indice'), '|', r.get('ter'), '|', r.get('tamanho'), '|', r.get('cambio'), '| top10', r.get('peso_top10'), r.get('data_carteira'))
        print('    ', r.get('top10')[:10])
