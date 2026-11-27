#!/usr/bin/env python3
"""
Adherio, 3D-printed holder version.  Same 3 networks / codebooks as the laser-film cards.

Stack (bottom -> top), all printed on a Bambu with 0.2 mm first layer + 0.08 mm layers:
  BASE       0.52 mm  pockets 0.16 deep that hold the L1 paper pieces, 3 corner pins + interior stake pins
  L1 paper   (Whatman No.1, ~0.18 mm) drops into the base pockets
  SEPARATOR  0.44 mm  flat bottom insulates L1; top pockets hold L2 paper; via holes (with paper plugs)
  L2 paper   drops into separator pockets
  COVER      0.60 mm  opaque: sample port + 7-segment glyph windows, debossed labels, nubs under each via
Valves: 8 mm holes through all three printed parts, so the 1/4" punch only ever cuts paper.
Needs: pip install shapely manifold3d trimesh
"""
import os, sys, json, itertools
import numpy as np, trimesh
from shapely.geometry import Point, box, MultiPolygon, Polygon
from shapely.ops import unary_union
from shapely import affinity
from manifold3d import Manifold, CrossSection, FillRule

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adherio_gen as G

# ------------------------------------------------------------------ printed-mode geometry
FIRST, LAYER = 0.20, 0.08
PAPER_T = 0.18                    # Whatman No.1
POCKET = 0.16                     # 2 layers: paper sits 0.02 proud -> gets clamped
BASE_T = FIRST + 2 * LAYER + POCKET          # 0.52
SEP_FLOOR = FIRST + LAYER                    # 0.28 insulating floor under L2
SEP_T = SEP_FLOOR + POCKET                   # 0.44
COVER_T = FIRST + 5 * LAYER                  # 0.60
NUB_H, NUB_R = 3 * LAYER, 1.15               # presses L2 pad onto the via plug
DEBOSS = FIRST                               # labels = gaps in the first (visible) layer
POCKET_CLR = 0.15                             # pocket = paper outline + 0.15 mm
PIN_R, PIN_HOLE_R = 1.1, 1.25
PIN_H = SEP_T + COVER_T                      # flush with cover top
PLUG_R = 1.25                                # paper plug discs for the vias (cut on the L2 sheet)
CORNER_PINS = [(3.0, 3.0), (G.W - 3.0, 3.0), (3.0, G.H - 3.0)]   # asymmetric
N_STAKES = 4

def configure():
    """switch adherio_gen into printed mode (bigger gaps so pocket walls print, printable glyphs)."""
    G.PRINTED = True
    G.CLEAR = 1.2                 # 0.9 mm plastic wall between pockets after the 0.15 mm pocket clearance
    G.GLYPH_W, G.GLYPH_H, G.SEG_T, G.SEG_G = 4.6, 7.0, 0.9, 0.7
    G.GZ_W, G.GZ_H = 5.6, 8.0
    G.GWIN_PAD = 0.2
    G.YA, G.YB = 28.0, 51.5      # taller scramble band so every pocket wall is >= 0.9 mm
    G.LEVELS = [58.0, 67.3, 76.6]
    G.BRACKET = (3.0, 5.0, 4.0)
    G.LABEL_W, G.LABEL_H = 2.6, 3.8

# ------------------------------------------------------------------ helpers
SEG = 64
def flipY(g):                       # card coords (y down) -> printer coords (y up), no mirroring of the part
    return affinity.translate(affinity.scale(g, 1, -1, origin=(0, 0)), 0, G.H)

def cs(geom):
    geom = flipY(geom)
    polys = list(geom.geoms) if hasattr(geom, 'geoms') else [geom]
    rings = []
    for p in polys:
        if p.is_empty:
            continue
        rings.append([tuple(c) for c in list(p.exterior.coords)[:-1]])
        rings += [[tuple(c) for c in list(r.coords)[:-1]] for r in p.interiors]
    return CrossSection(rings, FillRule.EvenOdd)

def slab(geom, z0, z1):
    return Manifold.extrude(cs(geom), z1 - z0).translate([0, 0, z0])

def circ(c, r):
    return Point(c).buffer(r, resolution=32)

def to_trimesh(m):
    m = m.simplify(0.005)
    mesh = m.to_mesh()
    return trimesh.Trimesh(vertices=np.asarray(mesh.vert_properties)[:, :3], faces=np.asarray(mesh.tri_verts), process=False)

def card_outline():
    return G.rounded_rect(0, 0, G.W, G.H, G.CARD_R)

def stroke_geom(ch, cx, cy, w, h, lw=0.6):
    return unary_union([__import__('shapely.geometry', fromlist=['LineString']).LineString(st).buffer(lw / 2, cap_style=2)
                        for st in G.seg_strokes(ch, cx, cy, w, h)])

# ------------------------------------------------------------------ stake pins in empty land
def pick_stakes(E, WIN, n=N_STAKES):
    keep_out = unary_union([e['geom'] for e in E] + [w['geom'] for w in WIN]).buffer(PIN_R + 1.3)
    inner = card_outline().buffer(-(PIN_R + 2.0))
    grid = [Point(x, y) for x in np.arange(3, G.W - 3, 0.5) for y in np.arange(G.YA - 4, G.YB + 2, 0.5)]
    ok = [p for p in grid if inner.contains(p) and not keep_out.contains(p)]
    chosen = []
    for _ in range(n):
        if not ok:
            break
        if not chosen:   # start nearest the card centre of the network band
            p = min(ok, key=lambda q: q.distance(Point(G.W / 2, (G.YA + G.YB) / 2)))
        else:
            p = max(ok, key=lambda q: min(q.distance(c) for c in chosen + [Point(x, y) for x, y in CORNER_PINS]))
        chosen.append(p)
        ok = [q for q in ok if q.distance(p) > 8]
    return [(p.x, p.y) for p in chosen]

def check_pins(E, WIN, pins):
    bad = []
    feats = unary_union([e['geom'] for e in E] + [w['geom'] for w in WIN])
    for p in pins:
        d = Point(p).distance(feats)
        if d < PIN_HOLE_R + POCKET_CLR + 0.8:
            bad.append((p, round(d, 2)))
    return bad

# ------------------------------------------------------------------ parts
def parts_for_card(card_no, gl, lv, E, WIN):
    L1 = unary_union([e['geom'] for e in E if e['layer'] == 1])
    L2 = unary_union([e['geom'] for e in E if e['layer'] == 2])
    holes = unary_union([w['geom'] for w in WIN if w['kind'] == 'valvehole'])
    vias = [w for w in WIN if w['kind'] == 'via']
    through_sep = unary_union([w['geom'] for w in WIN if w['kind'] in ('via', 'glyph', 'sample', 'valvehole')])
    stakes = pick_stakes(E, WIN)
    pins = CORNER_PINS + stakes
    bad = check_pins(E, WIN, pins)
    if bad:
        raise RuntimeError(f"card {card_no}: pin too close to features {bad}")
    pin_holes = unary_union([circ(p, PIN_HOLE_R) for p in pins])
    outline = card_outline()
    big = 10.0

    # BASE
    base = slab(outline, 0, BASE_T)
    base = base - slab(L1.buffer(POCKET_CLR, join_style=1), BASE_T - POCKET, BASE_T + 1)
    base = base - slab(holes, -1, BASE_T + 1)
    for p in pins:
        q = flipY(Point(p))
        base = base + Manifold.cylinder(PIN_H + 0.1, PIN_R, PIN_R, SEG).translate([q.x, q.y, BASE_T - 0.1])
        base = base + Manifold.cylinder(0.25, PIN_R, PIN_R - 0.3, SEG).translate([q.x, q.y, BASE_T + PIN_H])

    # SEPARATOR (printed as modelled: flat insulating face on the bed)
    sep = slab(outline, 0, SEP_T)
    sep = sep - slab(L2.buffer(POCKET_CLR, join_style=1), SEP_FLOOR, SEP_T + 1)
    sep = sep - slab(through_sep, -1, SEP_T + 1)
    sep = sep - slab(pin_holes, -1, SEP_T + 1)

    # COVER (modelled visible-face-up, then flipped so the visible face prints on the bed)
    win = [circ(G.S, G.S_WIN), holes, pin_holes]
    for l in range(8):
        win += G.seg_rects(gl[l], G.LX[l], lv[l], G.GLYPH_W, G.GLYPH_H, G.SEG_T, G.SEG_G)
    cover = slab(outline, 0, COVER_T) - slab(unary_union(win), -1, COVER_T + 1)
    labels = []
    for i, vx in enumerate(G.VX):
        labels.append(stroke_geom(G.LABEL_GLYPH[G.VALVE_NAMES[i]], vx, G.VY + G.VALVE_HOLE_R + 0.9 + G.LABEL_H / 2,
                                  G.LABEL_W, G.LABEL_H))
        ring = circ((vx, G.VY), G.VALVE_HOLE_R + 1.1).difference(circ((vx, G.VY), G.VALVE_HOLE_R + 0.5))
        labels.append(ring)
    labels.append(stroke_geom(str(card_no), G.ID_POS[0] + 1.5, G.ID_POS[1], G.ID_W + 0.4, G.ID_H))
    labels.append(circ(G.S, G.S_WIN + 1.3).difference(circ(G.S, G.S_WIN + 0.7)))
    br = G.rounded_rect(G.LX[0] - G.BRACKET[0], G.LEVELS[0] - G.BRACKET[1], G.LX[7] + G.BRACKET[0],
                        G.LEVELS[-1] + G.BRACKET[2], 1.5)
    labels.append(br.difference(br.buffer(-0.6)))
    cover = cover - slab(unary_union(labels), COVER_T - DEBOSS, COVER_T + 1)
    for w in vias:
        c = w['geom'].centroid
        q = flipY(Point(c.x, c.y))
        cover = cover + Manifold.cylinder(NUB_H + 0.05, NUB_R, NUB_R, SEG).translate([q.x, q.y, -NUB_H])
    cover_print = cover.rotate([180, 0, 0]).translate([0, G.H, COVER_T])  # visible face down, nubs up

    return dict(base=base, separator=sep, cover=cover_print), pins, len(vias), cover

# ------------------------------------------------------------------ paper SVGs (pieces on a tabbed frame) + via plugs
def paper_svgs(card_no, E, nvias, outdir):
    files = []
    for lay in (1, 2):
        sheet, feats, bridges, ncomp = G.paper_layer(E, lay)
        extra = ''
        if lay == 2:
            # via plug discs in the bottom frame margin, each held by two 0.4 mm tabs
            for k in range(nvias + 2):
                cx, cy = G.M + 4 + k * 4.2, G.M + G.H + 6
                disc = circ((cx, cy), PLUG_R)
                ring = circ((cx, cy), PLUG_R + 0.6).difference(disc)
                tabs = box(cx - PLUG_R - 1, cy - 0.2, cx + PLUG_R + 1, cy + 0.2)
                sheet = sheet.difference(ring.difference(tabs))
        fn = os.path.join(outdir, f'card{card_no}_L{lay}_paper{"_with_via_plugs" if lay == 2 else ""}.svg')
        open(fn, 'w').write(G.svg_doc(G.paths_svg(sheet, G.CUT),
                                      f'Adherio printed-holder card {card_no} - L{lay} paper'))
        files.append(fn)
    return files

# ------------------------------------------------------------------ preview (2D, per card)
def preview_svg(card_no, gl, lv, E, WIN, pins, lane_valve):
    vcol = ['#d1495b', '#edae49', '#00798c', '#6a4c93']
    def P(g, fill, op=1, stroke='none', sw=0.2):
        polys = list(g.geoms) if hasattr(g, 'geoms') else [g]
        d = ''
        for p in polys:
            for r in [p.exterior] + list(p.interiors):
                d += 'M' + ' L'.join(f'{x:.2f},{y:.2f}' for x, y in list(r.coords)[:-1]) + ' Z '
        return f'<path d="{d}" fill="{fill}" fill-opacity="{op}" stroke="{stroke}" stroke-width="{sw}" fill-rule="evenodd"/>'
    L1 = unary_union([e['geom'] for e in E if e['layer'] == 1])
    L2 = unary_union([e['geom'] for e in E if e['layer'] == 2])
    holes = unary_union([w['geom'] for w in WIN if w['kind'] == 'valvehole'])
    oc = card_outline()
    gap = 8
    out = []
    # base
    g = [P(oc, '#e8e3d8'), P(L1.buffer(POCKET_CLR), '#b9b2a2'), P(holes, '#fff', 1, '#999')]
    g += [P(circ(p, PIN_R), '#555') for p in pins]
    out.append(('1 BASE + L1 pockets', g))
    # separator
    g = [P(oc, '#cfd6dd'), P(L2.buffer(POCKET_CLR), '#9aa7b3')]
    for w in WIN:
        g.append(P(w['geom'], '#fff', 1, '#333' if w['kind'] == 'via' else '#999'))
    g += [P(circ(p, PIN_HOLE_R), '#fff', 1, '#555') for p in pins]
    out.append(('2 SEPARATOR + L2 pockets, vias', g))
    # inside wiring
    g = [P(oc, '#f4f1ea')]
    for lay, op in ((1, 0.55), (2, 0.95)):
        for e in E:
            if e['layer'] == lay:
                t = e['tag']; col = vcol[int(t[-1])] if t[0] in 'NV' or t.startswith('Sp') else '#555'
                g.append(P(e['geom'], col, op, '#111' if lay == 2 else 'none', 0.15))
    for w in WIN:
        if w['kind'] == 'via':
            g.append(P(w['geom'], 'none', 1, '#000', 0.25))
        if w['kind'] == 'valvehole':
            g.append(P(w['geom'].exterior.buffer(0.1), '#000', 0.6))
    out.append(('paper wiring (L2 outlined)', g))
    # cover
    win = [circ(G.S, G.S_WIN)]
    g = [P(oc.difference(unary_union([holes] + [circ(p, PIN_HOLE_R) for p in pins])), '#262626'),
         P(circ(G.S, G.S_WIN), '#f4f1ea')]
    for l in range(8):
        for r in G.seg_rects(gl[l], G.LX[l], lv[l], G.GLYPH_W, G.GLYPH_H, G.SEG_T, G.SEG_G):
            g.append(P(r, vcol[lane_valve[l]]))
    for i, vx in enumerate(G.VX):
        g.append(P(stroke_geom(G.LABEL_GLYPH[G.VALVE_NAMES[i]], vx, G.VY + G.VALVE_HOLE_R + 0.9 + G.LABEL_H / 2,
                               G.LABEL_W, G.LABEL_H), '#8a9aa8'))
    g.append(P(stroke_geom(str(card_no), G.ID_POS[0] + 1.5, G.ID_POS[1], G.ID_W + 0.4, G.ID_H), '#8a9aa8'))
    out.append(('3 COVER (glyph colour = feeding valve)', g))
    body = ''
    for k, (title, gs) in enumerate(out):
        x0 = k * (G.W + gap)
        body += f'<g transform="translate({x0},8)">' + ''.join(gs) + '</g>'
        body += f'<text x="{x0}" y="5" font-family="Helvetica" font-size="3">{title}</text>'
    Wt, Ht = 4 * (G.W + gap), G.H + 12
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{Wt*8}" height="{Ht*8}" viewBox="0 0 {Wt} {Ht}"><rect width="100%" height="100%" fill="#fff"/>{body}</svg>'

# ------------------------------------------------------------------ main
def main(outdir='printed'):
    laser = G.choose_cards()                       # same 3 networks, glyphs and height order as the laser cards
    levels_idx = [[G.LEVELS.index(v) for v in c[2]] for c in laser]
    configure()
    os.makedirs(outdir, exist_ok=True)
    report = []
    for n, (c, gl, lv_old, *_rest) in enumerate(laser, 1):
        lv = [G.LEVELS[k] for k in levels_idx[n - 1]]
        E, WIN, lane_valve, trace_layer = G.build_card(c, gl, lv)
        errs = G.validate(E, WIN)
        if errs:
            raise SystemExit(f"card {n} fails printed-mode checks:\n  " + "\n  ".join(sorted(set(errs))))
        d = os.path.join(outdir, f'card{n}')
        os.makedirs(d, exist_ok=True)
        parts, pins, nvias, cover_up = parts_for_card(n, gl, lv, E, WIN)
        meshes = {}
        for k, (name, m) in enumerate(parts.items()):
            tm = to_trimesh(m)
            fn = os.path.join(d, f'card{n}_{"ABC"[k]}_{name}.stl')
            tm.export(fn)
            meshes[name] = tm
        # one 3MF plate per card, parts side by side
        scene = trimesh.Scene()
        offs = {'base': (0, 0), 'separator': (G.W + 6, 0), 'cover': (0, G.H + 6)}   # fits a 180 mm A1 mini bed
        for name in ['base', 'separator', 'cover']:
            scene.add_geometry(meshes[name].copy().apply_translation([*offs[name], 0]), node_name=f'card{n}_{name}',
                               geom_name=f'card{n}_{name}')
        try:
            scene.export(os.path.join(d, f'card{n}_plate.3mf'))
        except Exception as ex:
            print('3mf export skipped:', ex)
        paper_svgs(n, E, nvias, d)
        open(os.path.join(d, f'card{n}_preview.svg'), 'w').write(preview_svg(n, gl, lv, E, WIN, pins, lane_valve))
        report.append(dict(card=n, vias=nvias, pins=len(pins),
                           thickness={'base': BASE_T, 'separator': SEP_T, 'cover': COVER_T,
                                      'stack': round(BASE_T + SEP_T + COVER_T, 2)},
                           valve_to_glyphs={G.VALVE_NAMES[i]: ''.join(gl[l] for l in sorted(c['pairs'][i])) for i in range(4)}))
        print(n, report[-1])
    json.dump(report, open(os.path.join(outdir, 'printed_summary.json'), 'w'), indent=1)

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'printed')
