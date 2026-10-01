# Monta o artifact "Entrada nos UCITS" a partir dos JSONs da analise e do modelo HTML.
import json, html
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analise import OUT
AQUI = os.path.join(os.path.dirname(os.path.abspath(__file__)), '')
t = json.load(open(OUT + 'tecnica.json', encoding='utf-8'))
c = json.load(open(OUT + 'consolidado.json', encoding='utf-8'))
ia = json.load(open(OUT + 'ia.json', encoding='utf-8'))['etfs']
g = json.load(open(OUT + 'graf.json', encoding='utf-8'))
vh = json.load(open(OUT + 'vhya.json', encoding='utf-8'))

def br(x, d=2):
    if x is None:
        return '—'
    s = f'{x:,.{d}f}'
    return s.replace(',', '#').replace('.', ',').replace('#', '.')

def sinal(x, d=1):
    if x is None:
        return '—'
    return ('+' if x > 0 else ('−' if x < 0 else '')) + br(abs(x), d)

CLS = {'Entrada agora': 'v-sim', 'Em parcelas': 'v-parc', 'Esperar': 'v-nao', 'Caixa': 'v-cx'}

# ---------- veredito por ETF ----------
# (ticker, veredito, entrada, reforco, invalida, nota)
VER = {
 'Carteira modelo': [
  ('CSPX', 'Em parcelas', '1/3 em 818–824', '1/3 em 803–814 ou no fechamento acima de 839; 1/3 depois do Fed de 09/12', 'semana fechando abaixo de 794', 'lateral 818–839 desde 14/08, sem pullback'),
  ('VHYA', 'Entrada agora', 'metade agora', 'metade em 104,0–104,7 ou na virada do MACD', 'semana abaixo de 101,6 (MM200)', 'pullback de 4,4% em tendência de alta'),
  ('DGRA', 'Entrada agora', 'agora', '56,9–57,9 (fundos de julho e MM100)', 'semana abaixo de 56,1 (MM200)', 'RSI 40,6, 3,3% abaixo da máxima'),
  ('IWVL', 'Em parcelas', 'depois da Micron (30/09), acima de 79,7', '76,7–77,3 (fundos de julho)', 'semana abaixo de 76,7', '13,6% da carteira é Micron'),
  ('XEOU', 'Entrada agora', 'agora', '23,0–23,2 (fundos de julho e setembro)', 'abaixo de 22,35 (MM200)', 'Europa com hedge para dólar'),
  ('IJPD', 'Entrada agora', 'agora', '119,4–120,0 (fundo de 10/09 e MM100)', 'semana abaixo de 116,2', 'Japão com hedge; RSI 48,9'),
  ('QNTM', 'Em parcelas', '28,5–29,0 (fundos de setembro)', '27,5 (MM200)', 'abaixo de 26,5', 'correção de 15% da máxima de junho'),
  ('VDCA', 'Entrada agora', 'agora', '—', '—', 'crédito de 1 a 3 anos: o carrego manda'),
  ('CBU7', 'Esperar', '1/3 depois do payroll (02/10), se o 5 anos ficar abaixo de 5,10%', '1/3 no fechamento acima de 141,1 (MM20); 1/3 depois do Fed de 09/12 ou com o 5 anos a 5,40%', 'pausa se o núcleo da inflação acelerar', 'regra diz esperar; eu faço exceção pelo carrego'),
  ('IB01', 'Caixa', 'é onde fica o dinheiro que espera', '—', '—', 'rende perto das letras de 3 a 12 meses (4,28% a 4,59%)'),
  ('STYC', 'Em parcelas', 'metade agora (RSI 24,2)', 'metade se o spread high yield passar de 3,2 pp', 'pausa com spread acima de 3,5 pp', 'spread subiu de 2,67 para 2,93 pp em um mês'),
  ('IGLN', 'Esperar', '1/3 no fechamento acima de 83,8 (MM50)', '1/3 acima de 88,0 (MM200); 1/3 se testar 76,5–77,8 e a semana fechar acima de 77,8', 'semana abaixo de 76,5 cancela a parcela do suporte', '−21,6% da máxima; cai com o juro real'),
 ],
 'IA e infraestrutura de IA': [
  ('XAID', 'Em parcelas', '240–245, depois da Micron', '234,6–237,3 (MM50, MM100 e Fibonacci 23,6%)', 'semana abaixo de 232,85', 'escolhido para a moderada'),
  ('SMH', 'Em parcelas', '106,7–107,9 (MM50 e MM20), depois de 30/09', '101,6–102,1 (fundos de setembro)', 'semana abaixo de 101,6', 'só na arrojada; vol 46%'),
  ('WTAI', 'Em parcelas', '116,6–118,6 (MM50 e MM20)', '114,0–115,2 (fundos de setembro)', 'abaixo de 114,0', 'vol 35%'),
  ('IUIT', 'Em parcelas', '51,0–52,1 (MM50 e MM20)', '49,6–50,3', 'abaixo de 48,1', '17% acima da MM200'),
  ('XDWT', 'Em parcelas', '143,8–146,8', '140,4–141,9', 'abaixo de 135,7', '17% acima da MM200'),
  ('CNDX', 'Em parcelas', '1.686–1.707 (MM50 e MM20)', '1.665–1.674 (fundos de setembro)', 'abaixo de 1.575 (MM200)', 'a 1% da máxima'),
  ('GRDU', 'Em parcelas', '60,1–61,3 (fundo de 14/09 e MM200)', '58,0 (fundo de julho)', 'semana abaixo de 58,0', 'correção de 10,5%, MM50 caindo'),
  ('VPN', 'Em parcelas', '24,5–24,8, posição pequena', '—', 'semana abaixo de 24,0', 'correção de 15,7% com MM200 subindo'),
  ('COPX', 'Em parcelas', '64,7–66,1 (MM200 e MM100)', '—', 'semana abaixo de 64,7', 'vol 42%'),
  ('CIBR', 'Em parcelas', '59,8–61,5 (MM50 e MM20)', '56,7–57,5', 'abaixo de 54,3', '29% acima da MM200'),
  ('USPY', 'Em parcelas', '45,9–46,7', '44,0', 'abaixo de 41,8', 'vol 36%'),
  ('NUCL', 'Esperar', 'gatilho: fechamento acima de 52,8 (MM50)', '—', '—', '−30% da máxima, abaixo da MM200'),
  ('IUUS', 'Esperar', 'gatilho: fechamento acima de 10,7 (MM50)', '—', '—', 'utilities −16%: juro de 5% pesa'),
  ('URNU', 'Esperar', 'gatilho: fechamento acima de 26,3 (MM50)', '—', '—', 'urânio −34%'),
  ('DFNS', 'Esperar', 'gatilho: fechamento acima de 61,9 (MM50)', '—', '—', 'defesa −22%'),
  ('REMX', 'Esperar', 'gatilho: fechamento acima de 14,3 (MM50)', '—', '—', 'terras raras −41%'),
 ],
 'Resto do universo': [
  ('VWRA', 'Em parcelas', '190,2–190,9 (MM100 e fundo de setembro)', '—', 'abaixo de 184,8', 'sem pullback: −1,9%'),
  ('XDEW', 'Entrada agora', 'agora', '114,2–115,1 (MM200 e fundo de junho)', 'semana abaixo de 114,2', 'o S&P sem as gigantes, RSI 26,8'),
  ('IUVL', 'Em parcelas', 'depois de 30/09', '18,2 (fundos de agosto)', 'abaixo de 18,2', '21% da carteira é Micron'),
  ('EMVL', 'Em parcelas', '99,1–100,0 (MM50 e fundo)', '—', 'abaixo de 96,7', 'Samsung e SK hynix: 16% da carteira'),
  ('IUES', 'Entrada agora', 'agora', '12,5 (MM100)', 'abaixo de 11,8 (MM200)', 'energia do S&P; protege no cenário de petróleo'),
  ('CMOD', 'Entrada agora', 'agora', '34,5 (MM50)', 'abaixo de 33,4 (MM100)', 'commodities amplas'),
  ('R2US', 'Entrada agora', 'regra aprova; eu deixo de fora', '—', 'abaixo de 81,1 (MM200)', 'small caps sofrem mais com o Fed subindo'),
 ],
}

def linha_ver(tk, ver, ent, ref, inv, nota):
    r = c.get(tk, {})
    preco = br(r.get('preco'), 2 if (r.get('preco') or 0) < 1000 else 1)
    dmax = sinal(r.get('dist_max52'))
    rot = 'Caixa' if ver == 'Caixa' else ver
    return (f'<tr><th><span class="tk">{tk}</span><span class="sub">{html.escape(nota)}</span></th>'
            f'<td class="n">{preco}<span class="sub">{dmax}% da máx.</span></td>'
            f'<td class="vv"><span class="ver {CLS[ver]}">{rot}</span></td>'
            f'<td class="t"><b>Entrada:</b> {html.escape(ent)}' + (f'<br><b>Reforço:</b> {html.escape(ref)}' if ref != '—' else '')
            + (f'<br><b>Invalida:</b> {html.escape(inv)}' if inv != '—' else '') + '</td></tr>')

blocos = []
for grupo, itens in VER.items():
    linhas = '\n'.join(linha_ver(*i) for i in itens)
    blocos.append(f'<h3>{grupo}</h3>\n<div class="rolagem"><table class="ver-tab"><thead><tr><th>ETF</th><th>Preço</th><th class="e">Veredito</th><th class="e">Níveis (USD)</th></tr></thead><tbody>\n{linhas}\n</tbody></table></div>')
VEREDITOS = '\n'.join(blocos)

# ---------- validacao do snapshot ----------
SEU = {  # preco, dmax, mm50, mm200, rsi, 1m, 12m, vol
 'CSPX': (830.12, -1.0, 0.8, 7.0, 52.6, -0.3, 17.5, 10.8), 'VHYA': (105.60, -4.0, -2.0, 4.0, 35.5, -3.0, 20.5, 7.5),
 'DGRA': (58.37, -2.9, -0.9, 4.1, 43.9, -2.2, 11.4, 8.6), 'IWVL': (81.49, -2.7, 0.7, 13.3, 47.9, 0.2, 49.6, 14.8),
 'IJPD': (121.62, -3.2, 0.3, 7.5, 48.9, -0.5, 35.7, 18.1), 'XEOU': (23.52, -2.1, -0.5, 5.3, 50.3, -1.1, 21.4, 9.9),
 'XAID': (248.45, -3.1, 4.9, 18.8, 58.6, 3.8, 42.2, 24.3), 'SMH': (114.00, -8.7, 7.0, 25.9, 62.0, 8.0, 111.7, 46.1),
 'WTAI': (122.08, -5.9, 4.8, 17.2, 57.7, 2.0, 46.7, 35.1), 'IUIT': (53.66, -0.2, 5.5, 17.4, 63.7, 4.2, 31.3, 22.6),
 'XDWT': (151.16, -0.1, 5.3, 17.3, 63.0, 3.9, 31.6, 23.4), 'CNDX': (1746.20, -0.8, 3.6, 10.9, 60.5, 3.0, 24.1, 19.1),
 'GRDU': (62.36, -9.8, -0.5, 1.8, 49.6, -1.5, 20.9, 25.7), 'VPN': (24.82, -15.7, -2.8, 1.5, 42.3, -4.2, 36.0, 27.8),
 'NUCL': (49.80, -29.1, -5.7, -14.3, 39.1, -13.0, -13.7, 36.4), 'XDEW': (117.22, -5.5, -3.0, 2.7, 29.4, -5.2, 12.7, 9.4),
 'IGLN': (80.66, -21.6, -3.7, -8.4, 34.4, -9.6, 8.5, 24.3), 'CBU7': (139.65, None, -1.8, -2.3, 24.2, -2.5, -1.2, 3.0),
}
lin = []
for tk, s in SEU.items():
    r = t[tk + '.L']
    p = r['preco']
    dmax_meu = 'na mínima' if tk == 'CBU7' else sinal(r['dist_max52']) + '%'
    dmax_seu = 'na mínima' if s[1] is None else sinal(s[1]) + '%'
    dec = 1 if p > 1000 else 2
    lin.append(f'<tr><th>{tk}</th><td class="n">{br(s[0], dec)}<span class="sub f">{br(p, dec)}</span></td>'
               f'<td class="n">{dmax_seu}<span class="sub f">{dmax_meu}</span></td>'
               f'<td class="n">{sinal(s[2])}%<span class="sub f">{sinal(r["dist_mm50"])}%</span></td>'
               f'<td class="n">{sinal(s[3])}%<span class="sub f">{sinal(r["dist_mm200"])}%</span></td>'
               f'<td class="n">{br(s[4], 1)}<span class="sub f">{br(r["rsi14"], 1)}</span></td>'
               f'<td class="n">{sinal(s[5])}%<span class="sub f">{sinal(r["ret_1m"])}%</span></td>'
               f'<td class="n">{sinal(s[6])}%<span class="sub f">{sinal(r["ret_12m"])}%</span></td>'
               f'<td class="n">{br(s[7], 1)}%<span class="sub f">{br(r["vol3m"], 1)}%</span></td></tr>')
VALIDA = '\n'.join(lin)

# ---------- cartoes dos ETFs de IA ----------
IA = [
 ('SMH', 'VanEck Semiconductor', 'MarketVector US Listed Semiconductor 10% Capped (filtro ESG)', 'Nvidia 11,3 · Micron 11,0 · AMD 10,7 · TSMC 10,4 · Broadcom 10,2 · ASML 10,0', 'o fornecedor puro do capex: chips e equipamentos'),
 ('XAID', 'Xtrackers AI & Big Data', 'Nasdaq Global Artificial Intelligence and Big Data', 'Microsoft 5,9 · Nvidia 4,8 · Apple 4,7 · Amazon 4,7 · Meta 4,4 · Alphabet 4,1 · Walmart 4,0 · Samsung 3,8', 'as plataformas que gastam, mais Samsung e Palantir'),
 ('WTAI', 'WisdomTree Artificial Intelligence', 'Nasdaq CTA Artificial Intelligence', 'AMD 4,6 · Marvell 4,1 · Micron 3,7 · Astera 3,0 · Nebius 2,7 · SK hynix 2,6 · Nvidia 2,5', 'o mais pulverizado; muita média empresa de rede e nuvem'),
 ('IUIT', 'iShares S&P 500 Information Technology', 'S&P 500 Capped 35/20 Information Technology', 'Apple 18,8 · Nvidia 18,5 · Microsoft 15,9 · Broadcom 7,3 · Micron 4,4', 'o mais barato (0,15%), mas três nomes são 53%'),
 ('XDWT', 'Xtrackers MSCI World IT', 'MSCI World IT 20/35 Custom', 'Nvidia 18,6 · Apple 17,0 · Microsoft 13,1 · Broadcom 6,1 · Micron 4,0', 'o IUIT com ASML e alguns nomes fora dos EUA'),
 ('CNDX', 'iShares Nasdaq 100', 'Nasdaq-100', 'Nvidia 8,0 · Apple 7,5 · Microsoft 5,7 · Amazon 4,8 · Micron 4,2', 'mais do mesmo CSPX, com inclinação a tecnologia'),
 ('GRDU', 'First Trust Smart Grid Infrastructure', 'Nasdaq Clean Edge Smart Grid Infrastructure', 'Schneider 9,4 · Johnson Controls 8,9 · Eaton 8,6 · ABB 7,9 · Quanta 7,4', 'energia e rede elétrica para o data center'),
 ('VPN', 'Global X Data Center REITs', 'Solactive Data Center REITs & Digital Infrastructure', 'Digital Realty 12,7 · American Tower 12,6 · Equinix 12,3 · Crown Castle 8,7', 'imóvel de data center: sensível a juro'),
 ('NUCL', 'VanEck Uranium and Nuclear', 'MarketVector Global Uranium and Nuclear Energy', 'Cameco 14,7 · NexGen 7,4 · Sprott Uranium 7,4 · Oklo 6,2', 'energia nuclear para IA; em tendência de baixa'),
 ('COPX', 'Global X Copper Miners', 'Solactive Global Copper Miners', 'Hudbay 5,6 · First Quantum 5,2 · BHP 5,2 · Teck 5,1', 'cobre para rede e data center; vol 42%'),
 ('CIBR', 'First Trust Cybersecurity', 'Nasdaq CTA Cybersecurity', 'Palo Alto 9,7 · CrowdStrike 9,0 · Fortinet 8,8 · Cisco 6,5', 'segurança; tese própria, não é capex de IA'),
 ('USPY', 'L&G Cyber Security', 'ISE Cyber Security UCITS', 'Cloudflare 7,4 · CrowdStrike 7,2 · Palo Alto 6,7 · Fortinet 6,7', 'o CIBR mais caro (0,69%)'),
 ('IUUS', 'iShares S&P 500 Utilities', 'S&P 500 Utilities', 'NextEra, Duke, Southern (lista da Avenue)', 'fora da sua lista; incluído para testar a tese de energia'),
]
TAM = {'IUUS': 'US$ 1,3 bi', 'URNU': 'US$ 0,7 bi'}
cards = []
for tk, nome, idx, top, papel in IA:
    r = c[tk]; q = ia.get(tk + '.L', {})
    ter = (r.get('ter_justetf') or (r.get('avenue') or {}).get('ter') or '—').replace(' p.a.', '').replace('.', ',')
    tam = TAM.get(tk) or (r.get('tamanho_justetf') or '—').replace('EUR ', '€ ').replace(',', '.').replace(' m', ' mi')
    emsp = q.get('top10_em_sp500'); cor = q.get('corr_1a'); beta = q.get('beta_1a'); dd = q.get('dd_2022')
    ddtxt = (sinal(dd) + '% (2021–22)') if dd is not None else (sinal(q.get('dd_max_hist')) + '% (' + (q.get('dd_max_data') or '')[:7].replace('-', '/') + ')')
    spread = r.get('spread_pct')
    ver = r['classe'][0]
    cards.append(f'''<article class="etf">
  <header><span class="tk">{tk}</span><span class="ver {CLS[ver]}">{ver}</span></header>
  <p class="nome">{nome}<span class="sub">{idx}</span></p>
  <p class="top">{top}</p>
  <dl>
    <dt>Top 10 em ações do S&amp;P 500</dt><dd>{br(emsp, 0) if emsp is not None else '—'}% do fundo</dd>
    <dt>Correlação e beta com o CSPX (1 ano)</dt><dd>{br(cor, 2)} · {br(beta, 2)}</dd>
    <dt>Taxa e tamanho</dt><dd>{ter} · {tam}</dd>
    <dt>Giro diário e spread na LSE</dt><dd>US$ {br(r.get('giro_dia_usd_mi'), 1)} mi · {br(spread, 3)}%</dd>
    <dt>P/L da carteira</dt><dd>{br(r.get('pl_morningstar'), 1)}x</dd>
    <dt>Pior queda</dt><dd>{ddtxt}</dd>
    <dt>Técnica</dt><dd>{sinal(r['dist_max52'])}% da máx. · {sinal(r['d200'])}% vs MM200 · RSI {br(r['rsi'], 1)}</dd>
  </dl>
  <p class="papel">{papel}</p>
</article>''')
CARDS_IA = '\n'.join(cards)

# ---------- dados dos graficos ----------
dy = vh['dy_mensal']
dados = {k: g[k] for k in ('CSPX', 'VHYA', 'XAID', 'LARGURA')}
dados['DY'] = {'datas': [d[0] + '-15' for d in dy], 'vhya': [d[1] for d in dy], 'vwra': [d[2] for d in dy]}
DADOS = json.dumps(dados, separators=(',', ':'))

modelo = open(AQUI + 'ucits_modelo.html', encoding='utf-8').read()
js = open(AQUI + 'ucits_graficos.js', encoding='utf-8').read()
saida = (modelo.replace('@@VEREDITOS@@', VEREDITOS).replace('@@VALIDA@@', VALIDA).replace('@@CARDS_IA@@', CARDS_IA)
         .replace('@@DADOS@@', DADOS).replace('@@JS@@', js))
assert '@@' not in saida, [x for x in ('@@VEREDITOS@@', '@@VALIDA@@', '@@CARDS_IA@@', '@@DADOS@@', '@@JS@@') if x in saida]
open(OUT + 'ucits.html', 'w', encoding='utf-8').write(saida)
print('ok', len(saida))
