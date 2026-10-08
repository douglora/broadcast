const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('fs');
(async () => {
  const html = fs.readFileSync(process.argv[2] || 'saida/ucits.html', 'utf8');
  const page = '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><style>:root{color-scheme:light}body{margin:0}[hidden]{display:none!important}</style></head><body>' + html + '</body></html>';
  const b = await chromium.launch();
  for (const [nome, w] of [['cel', 390], ['pc', 1200]]) {
    const ctx = await b.newContext({ viewport: { width: w, height: 900 }, deviceScaleFactor: 1 });
    const pg = await ctx.newPage();
    const erros = [];
    pg.on('pageerror', e => erros.push(String(e)));
    pg.on('console', m => { if (['error', 'warning'].includes(m.type())) erros.push(m.type() + ': ' + m.text()); });
    await pg.setContent(page, { waitUntil: 'networkidle' }).catch(e => erros.push('load ' + e));
    await pg.waitForTimeout(1200);
    console.log(nome, 'scrollWidth', await pg.evaluate('document.documentElement.scrollWidth'), 'altura', await pg.evaluate('document.body.scrollHeight'), 'erros', JSON.stringify(erros).slice(0, 400));
    console.log('  largos:', JSON.stringify(await pg.evaluate(`Array.from(document.querySelectorAll('main *')).filter(e => e.getBoundingClientRect().right > ${w} + 1 && !e.closest('.rolagem')).slice(0,8).map(e => e.tagName + '.' + e.className)`)));
    console.log('  svg fora:', JSON.stringify(await pg.evaluate(`Array.from(document.querySelectorAll('svg text')).map(t => { const r = t.getBoundingClientRect(); const s = t.closest('.grafico').getBoundingClientRect(); return [t.textContent, Math.round(r.left), Math.round(r.right), Math.round(s.left), Math.round(s.right)]; }).filter(x => x[2] > x[4] + 2 || x[1] < x[3] - 2).slice(0,10)`)));
    for (const sec of ['veredito', 'cspx', 'vhya', 'ia', 'ranking', 'carteira']) {
      const el = await pg.$('#' + sec);
      if (el) await el.screenshot({ path: `shot_${sec}_${nome}.png` });
    }
    await pg.screenshot({ path: `shot_topo_${nome}.png` });
    await ctx.close();
  }
  await b.close();
})();
