/* 2FA Dx core: card data, wicking simulation and card drawing. Shared by explainer.html and app.html.
   Geometry and codebooks come from web/cards.json (exported from adherio_gen.py / adherio_print.py). */
const AD = (() => {
  const DATA = window.ADHERIO_DATA;
  const UL_PER_MM2 = 0.12;                 // Whatman No.1 bed volume, as in adherio_gen.PAPER_UL_PER_MM2
  const NET_COL = ['#ffffff', '#cfd8dc', '#ff5d6c', '#f6b73c', '#22b5c4', '#a084e8']; // 0 none,1 sample,2..5 A..D
  const VALVES = 'ABCD';

  function unrle(a, n) {
    const out = new Uint8Array(n); let p = 0;
    for (let k = 0; k < a.length; k += 2) { out.fill(a[k], p, p + a[k + 1]); p += a[k + 1]; }
    return out;
  }
  const cache = new Map();
  function card(n) {
    if (cache.has(n)) return cache.get(n);
    const c = DATA.cards[n - 1];
    const g = c.grid, N = g.nx * g.ny;
    const P = (d) => new Path2D(d);
    const o = {
      ...c, N, nx: g.nx, ny: g.ny, cell: g.cell,
      L: [unrle(g.L1, N), unrle(g.L2, N)], via: unrle(g.via, N),
      path: {
        outline: roundRect(0, 0, c.W, c.H, c.R),
        L1: Object.fromEntries(Object.entries(c.paper.L1).map(([k, d]) => [k, P(d)])),
        L2: Object.fromEntries(Object.entries(c.paper.L2).map(([k, d]) => [k, P(d)])),
        L1all: P(Object.values(c.paper.L1).join('')), L2all: P(Object.values(c.paper.L2).join('')),
        glyphWin: P(c.glyph_windows.join('')),
        labels: P(c.labels.join('') + c.card_id + c.bracket),
        segs: c.lanes.map(l => P(l.segments)),
      },
    };
    cache.set(n, o);
    return o;
  }
  function roundRect(x, y, w, h, r) {
    const p = new Path2D(); p.roundRect(x, y, w, h, r); return p;
  }
  function circle(x, y, r) { const p = new Path2D(); p.arc(x, y, r, 0, Math.PI * 2); return p; }

  /* ---------- wicking: Dijkstra from the sample pad over both paper layers, vias join layers ---------- */
  function simulate(n, punch = '', opts = {}) {
    const c = card(n), { nx, ny, cell, N } = c;
    const holes = new Uint8Array(N);
    for (const v of c.valves) if (punch.includes(v.name)) {
      const r2 = c.punch_r * c.punch_r;
      for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
        const x = (i + .5) * cell - v.x, y = (j + .5) * cell - v.y;
        if (x * x + y * y <= r2) holes[j * nx + i] = 1;
      }
    }
    const ok = (k, idx) => c.L[k][idx] > 0 && !holes[idx];
    const dist = new Float64Array(2 * N).fill(Infinity);
    const heap = new Heap();
    for (let k = 0; k < 2; k++) for (let idx = 0; idx < N; idx++)
      if (c.L[k][idx] === 1 && ok(k, idx)) { dist[k * N + idx] = 0; heap.push(0, k * N + idx); }
    const D8 = [[1, 0, 1], [-1, 0, 1], [0, 1, 1], [0, -1, 1], [1, 1, Math.SQRT2], [1, -1, Math.SQRT2], [-1, 1, Math.SQRT2], [-1, -1, Math.SQRT2]];
    while (heap.size) {
      const [d, u] = heap.pop();
      if (d > dist[u]) continue;
      const k = u >= N ? 1 : 0, idx = u - k * N, j = (idx / nx) | 0, i = idx - j * nx;
      for (const [di, dj, w] of D8) {
        const ii = i + di, jj = j + dj;
        if (ii < 0 || jj < 0 || ii >= nx || jj >= ny) continue;
        const v = jj * nx + ii;
        if (!ok(k, v)) continue;
        const nd = d + w * cell, vv = k * N + v;
        if (nd < dist[vv]) { dist[vv] = nd; heap.push(nd, vv); }
      }
      if (c.via[idx] && ok(1 - k, idx)) {
        const vv = (1 - k) * N + idx, nd = d + 0.5;
        if (nd < dist[vv]) { dist[vv] = nd; heap.push(nd, vv); }
      }
    }
    // volume cap: paper fills in arrival order until the sample volume is used up
    const cellUL = cell * cell * UL_PER_MM2;
    const reach = [];
    for (let u = 0; u < 2 * N; u++) if (isFinite(dist[u])) reach.push(dist[u]);
    reach.sort((a, b) => a - b);
    const capUL = reach.length * cellUL;
    let dStop = reach.length ? reach[reach.length - 1] : 0;
    if (opts.volume != null && opts.volume < capUL) dStop = reach[Math.max(0, Math.floor(opts.volume / cellUL) - 1)] ?? 0;
    // readout pads (on L1): first arrival in each lane's zone
    const lanes = c.lanes.map(l => {
      const [x, y, w, h] = l.zone; let best = Infinity, cnt = 0, tot = 0;
      for (let j = Math.floor(y / cell); j < Math.ceil((y + h) / cell); j++)
        for (let i = Math.floor(x / cell); i < Math.ceil((x + w) / cell); i++) {
          const dd = dist[j * nx + i]; if (c.L[0][j * nx + i]) tot++;
          if (isFinite(dd)) { cnt++; best = Math.min(best, dd); }
        }
      const full = []; // distance at which the zone is fully wet
      for (let j = Math.floor(y / cell); j < Math.ceil((y + h) / cell); j++)
        for (let i = Math.floor(x / cell); i < Math.ceil((x + w) / cell); i++) { const dd = dist[j * nx + i]; if (isFinite(dd)) full.push(dd); }
      const dFull = full.length ? Math.max(...full) : Infinity;
      return { ...l, dArrive: best, dFull, reachable: cnt > 0 };
    });
    const valves = c.valves.map(v => {
      let best = Infinity; const r = v.pad + 0.6;
      for (let j = Math.floor((v.y - r) / cell); j <= Math.ceil((v.y + r) / cell); j++)
        for (let i = Math.floor((v.x - r) / cell); i <= Math.ceil((v.x + r) / cell); i++)
          for (let k = 0; k < 2; k++) { const dd = dist[k * N + j * nx + i]; if (isFinite(dd) && dd < best) best = dd; }
      return { ...v, dArrive: best };
    });
    const dMax = reach.length ? reach[reach.length - 1] : 0;
    return { n, punch, dist, dMax, dStop, capUL, lanes, valves, holes };
  }
  // the readout a patient would see when the front has advanced to distance d
  function litLanes(sim, d, ph = true) {
    if (!ph) return [];
    const lim = Math.min(d, sim.dStop);
    return sim.lanes.filter(l => l.dFull <= lim + 1e-6);
  }
  function codeOf(lanes) { return lanes.slice().sort((a, b) => a.x - b.x).map(l => l.glyph).join(''); }

  class Heap {
    constructor() { this.k = []; this.v = []; }
    get size() { return this.k.length; }
    push(k, v) {
      const K = this.k, V = this.v; let i = K.length; K.push(k); V.push(v);
      while (i > 0) { const p = (i - 1) >> 1; if (K[p] <= k) break; K[i] = K[p]; V[i] = V[p]; i = p; }
      K[i] = k; V[i] = v;
    }
    pop() {
      const K = this.k, V = this.v, rk = K[0], rv = V[0], lk = K.pop(), lv = V.pop(), n = K.length;
      if (n) {
        let i = 0;
        for (;;) {
          let c = 2 * i + 1; if (c >= n) break;
          if (c + 1 < n && K[c + 1] < K[c]) c++;
          if (K[c] >= lk) break;
          K[i] = K[c]; V[i] = V[c]; i = c;
        }
        K[i] = lk; V[i] = lv;
      }
      return [rk, rv];
    }
  }

  /* ---------- codebook ---------- */
  function normCode(s) {
    return (s || '').toUpperCase().replace(/[^0-9A-Z]/g, '');
  }
  function expected(n, punch) {
    const p = [...punch].sort().join('');
    const e = DATA.cards[n - 1].codebook.find(r => r.punch === p);
    return e ? e.code : null;
  }
  // every (card, punch) whose code equals s, and every one whose code contains all of s's glyphs
  function lookup(s) {
    const exact = [], partialOf = [];
    for (const c of DATA.cards) for (const r of c.codebook) {
      if (r.code === s) exact.push({ card: c.card, ...r });
      else if (s && isSubseq(s, r.code)) partialOf.push({ card: c.card, ...r });
    }
    return { exact, partialOf };
  }
  function isSubseq(a, b) { let i = 0; for (const ch of b) if (ch === a[i]) i++; return i === a.length; }

  /* ---------- drawing ---------- */
  const COL = {
    pla: '#e2fa1e', plaEdge: '#8ea10c', plaDeboss: '#b9cc14', paper: '#ffffff', paperEdge: '#c9ccd0',
    swatch: '#f0a21c', react: '#2b59d9', hole: '#0d0f12', liquid: '#5fb8ff',
  };
  // wet overlay: offscreen canvas per layer, alpha ramps at the front
  function wetImage(sim, layer, d, colorBy = 'net') {
    const c = card(sim.n), { nx, ny, N } = c;
    const cv = (wetImage._cv ||= []); const key = layer;
    const can = cv[key] ||= document.createElement('canvas');
    can.width = nx; can.height = ny;
    const ctx = can.getContext('2d'), img = ctx.createImageData(nx, ny), px = img.data;
    const lim = Math.min(d, sim.dStop), soft = 0.8;
    for (let idx = 0; idx < N; idx++) {
      const dd = sim.dist[layer * N + idx]; if (!isFinite(dd) || dd > lim) continue;
      const a = Math.min(1, (lim - dd) / soft + 0.25);
      const net = c.L[layer][idx];
      const hex = colorBy === 'net' ? NET_COL[net] : COL.liquid;
      const r = parseInt(hex.slice(1, 3), 16), g = parseInt(hex.slice(3, 5), 16), b = parseInt(hex.slice(5, 7), 16);
      const o = idx * 4; px[o] = r; px[o + 1] = g; px[o + 2] = b; px[o + 3] = 255 * a * (colorBy === 'net' && net === 1 ? .55 : .85);
    }
    ctx.putImageData(img, 0, 0);
    return can;
  }
  /* draw a top view of card n into ctx (already scaled to mm units)
     opts: { sim, d, xray (0..1: cover opacity inverse), colorBy, layers:'both'|'L1'|'L2', ph, showVias, highlightVias, punch } */
  function drawTop(ctx, n, o = {}) {
    const c = card(n), P = c.path;
    const punch = o.punch ?? (o.sim ? o.sim.punch : '');
    // ground under the card (what shows through holes)
    ctx.fillStyle = COL.pla; ctx.fill(P.outline);
    ctx.fillStyle = COL.plaDeboss; ctx.globalAlpha = .55; ctx.fill(P.L1all); ctx.globalAlpha = 1;
    for (const v of c.valves) { ctx.fillStyle = COL.hole; ctx.fill(circle(v.x, v.y, v.hole)); }
    const showL1 = o.layers !== 'L2', showL2 = o.layers !== 'L1';
    const paintLayer = (k) => {
      const all = k === 0 ? P.L1all : P.L2all;
      ctx.save();
      if (k === 1) { ctx.shadowColor = 'rgba(0,0,0,.45)'; ctx.shadowBlur = 0.8; ctx.shadowOffsetY = 0.25; }
      ctx.fillStyle = COL.paper; ctx.fill(all); ctx.restore();
      if (o.colorBy === 'net-paper') {
        for (const [net, p] of Object.entries(k === 0 ? P.L1 : P.L2)) {
          ctx.globalAlpha = k === 0 ? .32 : .5; ctx.fillStyle = NET_COL[net]; ctx.fill(p); ctx.globalAlpha = 1;
        }
      }
      if (o.sim) {
        ctx.save(); ctx.clip(all); ctx.imageSmoothingEnabled = true;
        ctx.drawImage(wetImage(o.sim, k, o.d ?? Infinity, o.colorBy === 'liquid' ? 'liquid' : 'net'), 0, 0, c.W, c.H);
        ctx.restore();
      }
      if (k === 1) { ctx.lineWidth = .18; ctx.strokeStyle = 'rgba(20,24,28,.55)'; ctx.stroke(all); }
    };
    if (showL1) paintLayer(0);
    if (o.separator) { ctx.globalAlpha = o.separator; ctx.fillStyle = COL.pla; ctx.fill(P.outline); ctx.globalAlpha = 1; }
    if (o.showVias) for (const v of c.vias) {
      ctx.fillStyle = o.highlightVias ? '#ffffff' : '#e8e2cf'; ctx.fill(circle(v.x, v.y, 1.25));
      if (o.highlightVias) { ctx.lineWidth = .35; ctx.strokeStyle = '#111'; ctx.stroke(circle(v.x, v.y, 1.4)); }
    }
    if (showL2) paintLayer(1);
    // punched holes: paper removed
    for (const v of c.valves) if (punch.includes(v.name)) {
      ctx.fillStyle = COL.hole; ctx.fill(circle(v.x, v.y, c.punch_r));
    }
    // swatches / readout zones under the windows
    if (o.cover != null) drawCover(ctx, n, o);
  }
  function swatchColor(l, lit) { return lit ? COL.react : COL.swatch; }
  function drawCover(ctx, n, o) {
    const c = card(n), P = c.path, alpha = o.cover;
    const lit = new Set((o.lit || []).map(l => l.lane));
    // swatches visible through glyph windows
    for (const l of c.lanes) {
      ctx.fillStyle = swatchColor(l, lit.has(l.lane));
      const [x, y, w, h] = l.zone; ctx.globalAlpha = Math.max(alpha, o.swatchAlpha ?? 0);
      ctx.fillRect(x, y, w, h); ctx.globalAlpha = 1;
    }
    if (alpha <= 0) return;
    const cover = new Path2D(); cover.addPath(P.outline);
    for (const v of c.valves) cover.addPath(circle(v.x, v.y, v.hole));
    cover.addPath(circle(c.sample.x, c.sample.y, c.sample.win));
    for (const s of P.segs) cover.addPath(s);
    for (const p of c.pins) cover.addPath(circle(p.x, p.y, 1.25));
    ctx.save(); ctx.globalAlpha = alpha;
    ctx.fillStyle = COL.pla; ctx.fill(cover, 'evenodd');
    ctx.fillStyle = COL.plaDeboss; ctx.fill(P.labels);
    for (const v of c.valves) {
      ctx.lineWidth = .6; ctx.strokeStyle = COL.plaDeboss;
      ctx.beginPath(); ctx.arc(v.x, v.y, v.hole + 0.8, 0, Math.PI * 2); ctx.stroke();
    }
    ctx.lineWidth = .6; ctx.beginPath(); ctx.arc(c.sample.x, c.sample.y, c.sample.win + 1, 0, Math.PI * 2); ctx.stroke();
    // inner shadow on every window so they read as cut-outs
    ctx.lineWidth = .22; ctx.strokeStyle = COL.plaEdge;
    for (const s of P.segs) ctx.stroke(s);
    for (const v of c.valves) ctx.stroke(circle(v.x, v.y, v.hole));
    ctx.stroke(circle(c.sample.x, c.sample.y, c.sample.win));
    for (const p of c.pins) { ctx.fillStyle = COL.plaEdge; ctx.fill(circle(p.x, p.y, 1.1)); ctx.fillStyle = COL.pla; ctx.fill(circle(p.x - .15, p.y - .15, .85)); }
    ctx.restore();
  }
  // fit a mm-space drawing of size w x h into a canvas box; returns the transform scale
  function fit(ctx, cw, ch, w, h, pad = 12) {
    const s = Math.min((cw - 2 * pad) / w, (ch - 2 * pad) / h);
    ctx.setTransform(s * DPR(), 0, 0, s * DPR(), (cw - w * s) / 2 * DPR(), (ch - h * s) / 2 * DPR());
    return s;
  }
  const DPR = () => Math.min(3, window.devicePixelRatio || 1);
  function sizeCanvas(cv) {
    const r = cv.getBoundingClientRect(), d = DPR();
    const w = Math.max(1, Math.round(r.width * d)), h = Math.max(1, Math.round(r.height * d));
    if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
    return [r.width, r.height];
  }
  // 7-segment glyph as SVG (for keypads and messages), same proportions as the printed windows
  function glyphSVG(ch, { w = 22, h = 34, on = 'currentColor', off = 'none' } = {}) {
    const segs = DATA.seg[ch] || '';
    const t = 0.9 / 4.6 * w, g = 0.7 / 4.6 * w, cy = h / 2;
    const R = {
      a: [t + g, 0, w - 2 * t - 2 * g, t], g: [t + g, cy - t / 2, w - 2 * t - 2 * g, t], d: [t + g, h - t, w - 2 * t - 2 * g, t],
      f: [0, 0, t, cy - g], e: [0, cy + g, t, h - cy - g], b: [w - t, 0, t, cy - g], c: [w - t, cy + g, t, h - cy - g],
    };
    return `<svg viewBox="-1 -1 ${w + 2} ${h + 2}" width="${w}" height="${h}" aria-hidden="true">` +
      Object.entries(R).filter(([k]) => segs.includes(k)).map(([k, [x, y, ww, hh]]) => `<rect x="${x}" y="${y}" width="${ww}" height="${hh}" rx="${t * .25}" fill="${on}"/>`).join('') + '</svg>';
  }
  return { DATA, VALVES, NET_COL, COL, card, simulate, litLanes, codeOf, expected, lookup, normCode, drawTop, drawCover,
           circle, fit, sizeCanvas, DPR, glyphSVG, UL_PER_MM2 };
})();
