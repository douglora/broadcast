(function(){
  var D = JSON.parse(document.getElementById('dados').textContent);
  var MESES = ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'];
  var NS = 'http://www.w3.org/2000/svg';
  function num(v, dec){ return v == null ? '—' : v.toLocaleString('pt-BR', {minimumFractionDigits: dec, maximumFractionDigits: dec}); }
  function dataBR(s, mensal){ var p = s.split('-'); return mensal ? MESES[+p[1] - 1] + '/' + p[0] : p[2] + '/' + p[1] + '/' + p[0]; }
  function el(tag, attrs, pai){ var e = document.createElementNS(NS, tag); for (var k in attrs) e.setAttribute(k, attrs[k]); if (pai) pai.appendChild(e); return e; }
  function txt(tag, attrs, t, pai){ var e = el(tag, attrs, pai); e.textContent = t; return e; }
  function passo(min, max, n){
    var bruto = (max - min) / n, pot = Math.pow(10, Math.floor(Math.log10(bruto))), r = bruto / pot;
    var f = r <= 1 ? 1 : r <= 2 ? 2 : r <= 2.5 ? 2.5 : r <= 5 ? 5 : 10; return f * pot;
  }
  var grupos = {};

  function Grafico(id, cfg){
    this.caixa = document.getElementById(id); this.cfg = cfg; this.i = null;
    if (!this.caixa) return;
    this.dica = document.createElement('div'); this.dica.className = 'dica'; this.dica.hidden = true;
    this.caixa.appendChild(this.dica);
    if (cfg.grupo){ (grupos[cfg.grupo] = grupos[cfg.grupo] || []).push(this); }
    var self = this;
    this.desenha();
    if (window.ResizeObserver){ new ResizeObserver(function(){ self.desenha(); }).observe(this.caixa); }
    this.caixa.addEventListener('pointermove', function(e){ self.aponta(e); });
    this.caixa.addEventListener('pointerleave', function(){ self.sincroniza(null); });
    this.caixa.addEventListener('keydown', function(e){
      var n = self.cfg.datas.length;
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight'){
        e.preventDefault();
        var i = self.i == null ? n - 1 : self.i + (e.key === 'ArrowRight' ? 1 : -1);
        self.sincroniza(Math.max(0, Math.min(n - 1, i)));
      }
    });
    this.caixa.addEventListener('blur', function(){ self.sincroniza(null); });
  }
  Grafico.prototype.desenha = function(){
    var c = this.cfg, caixa = this.caixa;
    var W = Math.max(280, caixa.clientWidth), H = c.altura;
    var estreito = W < 480;
    var ml = c.margemEsq || 44, mr = c.margemDir || (estreito ? 50 : 60), mt = 8, mb = c.semEixoX ? 6 : 22;
    var n = c.datas.length;
    var vals = [];
    c.series.forEach(function(s){ s.v.forEach(function(v){ if (v != null) vals.push(v); }); });
    (c.niveis || []).forEach(function(l){ vals.push(l.v); });
    var ymin = c.dominio ? c.dominio[0] : Math.min.apply(null, vals), ymax = c.dominio ? c.dominio[1] : Math.max.apply(null, vals);
    if (!c.dominio){ var pad = (ymax - ymin) * 0.06; ymin -= pad; ymax += pad; }
    var st = c.ticks ? null : passo(ymin, ymax, H < 140 ? 3 : 5);
    var pw = W - ml - mr, ph = H - mt - mb;
    var X = function(i){ return ml + i * pw / (n - 1); };
    var Y = function(v){ return mt + (ymax - v) * ph / (ymax - ymin); };
    this.geo = {X: X, Y: Y, ml: ml, mr: mr, mt: mt, mb: mb, W: W, H: H, pw: pw};
    var svg = el('svg', {viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, role: 'img', 'aria-label': caixa.getAttribute('aria-label') || ''});
    var ticks = c.ticks || (function(){ var t = []; for (var v = Math.ceil(ymin / st) * st; v <= ymax + 1e-9; v += st) t.push((Math.round(v * 1000) / 1000) || 0); return t; })();
    var decEixo = c.decEixo == null ? (st && st < 1 ? 1 : 0) : c.decEixo;
    ticks.forEach(function(v){
      el('line', {x1: ml, x2: W - mr, y1: Y(v), y2: Y(v), 'class': 'g-grade'}, svg);
      txt('text', {x: ml - 6, y: Y(v) + 3.5, 'text-anchor': 'end', 'class': 'g-eixo'}, num(v, decEixo) + (c.sufixo || ''), svg);
    });
    (c.faixas || []).forEach(function(f){
      el('line', {x1: ml, x2: W - mr, y1: Y(f.v), y2: Y(f.v), 'class': 'g-faixa'}, svg);
      if (f.r) txt('text', {x: ml + 4 + (f.pos || 0) * pw * (W < 480 ? 0.3 : 1), y: Y(f.v) + (f.abaixo ? 11 : -3), 'class': 'g-rot2 halo'}, f.r, svg);
    });
    if (!c.semEixoX){
      el('line', {x1: ml, x2: W - mr, y1: mt + ph, y2: mt + ph, 'class': 'g-base'}, svg);
      var ultimoX = -99, ant = null;
      c.datas.forEach(function(d, i){
        var chave = c.anual ? d.slice(0, 4) : d.slice(0, 7);
        if (chave !== ant){
          ant = chave;
          var x = X(i), rot;
          if (c.anual){ rot = d.slice(0, 4); }
          else { var mm = +d.slice(5, 7) - 1; rot = MESES[mm] + (mm === 0 ? '/' + d.slice(2, 4) : ''); }
          if (i > 0 && x - ultimoX >= (estreito ? 44 : 34) && x < W - mr - 10){
            el('line', {x1: x, x2: x, y1: mt + ph, y2: mt + ph + 4, 'class': 'g-base'}, svg);
            txt('text', {x: x, y: H - 6, 'text-anchor': 'middle', 'class': 'g-eixo'}, c.anual && estreito ? "'" + rot.slice(2) : rot, svg);
            ultimoX = x;
          }
        }
      });
    }
    (c.niveis || []).forEach(function(l){
      el('line', {x1: ml, x2: W - mr, y1: Y(l.v), y2: Y(l.v), 'class': 'g-nivel ' + (l.tipo || '')}, svg);
      if (l.r) txt('text', {x: ml + 4 + (l.pos || 0) * pw * (W < 480 ? 0.6 : 1), y: Y(l.v) + (l.abaixo ? 12 : -4), 'class': 'g-rot2 halo ' + (l.tipo || '')}, l.r, svg);
    });
    var fins = [];
    c.series.forEach(function(s){
      var d = '', dentro = false;
      s.v.forEach(function(v, i){
        if (v == null){ dentro = false; return; }
        d += (dentro ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(v).toFixed(1); dentro = true;
      });
      el('path', {d: d, 'class': 'g-lin s-' + s.cls + (s.forte ? ' forte' : '') + (s.tr ? ' tr' : '')}, svg);
      var ult = s.v.length - 1; while (ult >= 0 && s.v[ult] == null) ult--;
      if (ult >= 0 && s.rotulo !== false) fins.push({y: Y(s.v[ult]), t: s.rotulo || num(s.v[ult], s.dec == null ? 2 : s.dec), forte: !!s.forte, cls: s.cls});
    });
    fins.sort(function(a, b){ return (b.forte ? 1 : 0) - (a.forte ? 1 : 0); });
    var usados = [];
    fins.forEach(function(f){
      var y = f.y;
      for (var k = 0; k < 6 && usados.some(function(u){ return Math.abs(u - y) < 12; }); k++){
        var perto = usados.filter(function(u){ return Math.abs(u - y) < 12; })[0];
        y = y >= perto ? perto + 12 : perto - 12;
      }
      if (usados.some(function(u){ return Math.abs(u - y) < 12; })) return;
      usados.push(y);
      txt('text', {x: W - mr + 6, y: y + 3.5, 'class': (f.forte ? 'g-rot' : 'g-rot2') + ' t-' + f.cls}, f.t, svg);
    });
    this.mira = el('line', {x1: 0, x2: 0, y1: mt, y2: mt + ph, 'class': 'g-mira', visibility: 'hidden'}, svg);
    this.pontos = c.series.map(function(s){ return el('circle', {r: 4, 'class': 'f-' + s.cls + ' g-anel', visibility: 'hidden'}, svg); });
    if (this.svg) caixa.removeChild(this.svg);
    caixa.insertBefore(svg, this.dica); this.svg = svg;
    if (this.i != null) this.marca(this.i);
  };
  Grafico.prototype.aponta = function(e){
    var r = this.caixa.getBoundingClientRect(), g = this.geo, n = this.cfg.datas.length;
    var i = Math.round((e.clientX - r.left - g.ml) / (g.pw / (n - 1)));
    this.sincroniza(Math.max(0, Math.min(n - 1, i)));
  };
  Grafico.prototype.sincroniza = function(i){
    (this.cfg.grupo ? grupos[this.cfg.grupo] : [this]).forEach(function(g){ g.marca(i); });
  };
  Grafico.prototype.marca = function(i){
    this.i = i;
    if (i == null){ this.mira.setAttribute('visibility', 'hidden'); this.pontos.forEach(function(p){ p.setAttribute('visibility', 'hidden'); }); this.dica.hidden = true; return; }
    var g = this.geo, c = this.cfg, x = g.X(i);
    this.mira.setAttribute('x1', x); this.mira.setAttribute('x2', x); this.mira.setAttribute('visibility', 'visible');
    var dica = this.dica; dica.textContent = '';
    var dd = document.createElement('div'); dd.className = 'd'; dd.textContent = dataBR(c.datas[i], c.anual); dica.appendChild(dd);
    var self = this;
    c.series.forEach(function(s, k){
      var v = s.v[i], p = self.pontos[k];
      if (v == null){ p.setAttribute('visibility', 'hidden'); return; }
      p.setAttribute('cx', x); p.setAttribute('cy', g.Y(v)); p.setAttribute('visibility', 'visible');
      var row = document.createElement('div'); row.className = 'r'; row.style.setProperty('--c', 'var(--' + s.cls + ')');
      var ic = document.createElement('i'); var b = document.createElement('b'); b.textContent = num(v, s.dec == null ? 2 : s.dec) + (c.sufixo || '');
      var sp = document.createElement('span'); sp.textContent = s.nome;
      row.appendChild(ic); row.appendChild(b); row.appendChild(sp); dica.appendChild(row);
    });
    dica.hidden = false;
    var w = dica.offsetWidth, left = x + 12;
    if (left + w > g.W - 4) left = x - 12 - w;
    dica.style.transform = 'translate(' + Math.max(0, left) + 'px,' + (g.mt + 2) + 'px)';
  };

  function tecnica(tk, nome, niveis, dec){
    var S = D[tk];
    new Grafico('g-' + tk, {datas: S.datas, altura: 260, grupo: tk, series: [
      {nome: 'média de 200 dias', cls: 'mm200', v: S.mm200, rotulo: 'MM200', dec: dec},
      {nome: 'média de 50 dias', cls: 'mm50', v: S.mm50, rotulo: 'MM50', dec: dec},
      {nome: nome, cls: 'preco', v: S.p, forte: true, dec: dec}
    ], niveis: niveis});
    new Grafico('r-' + tk, {datas: S.datas, altura: 88, grupo: tk, dominio: [0, 100], ticks: [30, 50, 70], decEixo: 0, semEixoX: true,
      series: [{nome: 'RSI 14', cls: 'rsi', v: S.rsi, dec: 1, forte: true, rotulo: false}],
      faixas: [{v: 30, r: 'sobrevenda', abaixo: true}, {v: 70, r: 'sobrecompra'}]});
  }
  tecnica('CSPX', 'CSPX (US$)', [
    {v: 838.69, r: 'topo 838,69 (14/08) · rompimento projeta ~860'},
    {v: 818.15, r: 'entrada: fundo 818,15 (15/09)', tipo: 'ent'},
    {v: 803.05, r: 'reforço: Fibonacci 23,6% em 803', abaixo: true, tipo: 'ref', pos: 0.28},
    {v: 793.8, r: 'invalida: semana abaixo de 794', abaixo: true, tipo: 'inv', pos: 0.56}
  ], 2);
  tecnica('VHYA', 'VHYA (US$)', [
    {v: 109.94, r: 'topo 109,94 (03/09)'},
    {v: 104.68, r: 'reforço 104,0–104,7', abaixo: true, tipo: 'ref', pos: 0.3},
    {v: 101.56, r: 'invalida: semana abaixo de 101,6 (MM200)', abaixo: true, tipo: 'inv', pos: 0.1}
  ], 2);
  tecnica('XAID', 'XAID (US$)', [
    {v: 256.35, r: 'topo 256,35 (02/06)'},
    {v: 240.2, r: 'entrada 240–245 (fundo de 10/09)', abaixo: true, tipo: 'ent'},
    {v: 234.57, r: 'reforço 234,6–237,3', abaixo: true, tipo: 'ref', pos: 0.25},
    {v: 232.85, r: 'invalida: semana abaixo de 232,85', abaixo: true, tipo: 'inv', pos: 0.5}
  ], 2);

  var L = D.LARGURA;
  new Grafico('g-largura', {datas: L.datas, altura: 200, decEixo: 0, faixas: [{v: 100, r: 'base 100 em 02/06/2025', pos: 0.4}], series: [
    {nome: 'RSP / SPY (EUA)', cls: 'l2', v: L.rsp, dec: 1},
    {nome: 'XDEW / CSPX (LSE)', cls: 'l1', v: L.xdew, dec: 1, forte: true}
  ]});

  var Y = D.DY;
  new Grafico('g-dy', {datas: Y.datas, altura: 210, anual: true, decEixo: 1, sufixo: '%', series: [
    {nome: 'VWRA (via VWRD)', cls: 'vwra', v: Y.vwra, dec: 2},
    {nome: 'VHYA (via VHYD)', cls: 'vhya', v: Y.vhya, dec: 2, forte: true}
  ], faixas: [{v: 3.23, r: 'média do VHYA desde 2015: 3,23%', abaixo: true, pos: 0.52}]});
})();
