#!/usr/bin/env python3
"""
Adherio two-factor-authentication card generator (laser-cut layers).

Stack, bottom -> top (all layers share the same sheet and 3 registration holes):
  1. base_film      sticky film, adhesive UP (or cardstock)   - outline + reg holes
  2. L1_paper       paper: sample pad, spokes B/C, valves, stems, some network traces, lanes, readout zones
  3. separator_film sticky plastic, adhesive DOWN              - insulates crossings; holes ("vias") only
                                                                where L1 and L2 must touch, + glyph/sample windows
  4. L2_paper       paper: the "overpass" channels (spokes A/D and crossing network traces)
  5. lid_film       opaque sticky film, adhesive DOWN          - sample window, 7-segment glyph windows (cut),
                                                                valve targets, labels, card outline (score)

Valve = paper pad punched out with a 1/4" hole punch (punch = channel closed).
Units: mm. Colours: red = CUT, blue = SCORE/engrave (light power).
"""
import itertools, random, math, os, json, sys
from shapely.geometry import Point, LineString, Polygon, MultiPolygon, box
from shapely.ops import unary_union
from shapely import affinity

# ------------------------------------------------------------------ parameters
W, H = 58.0, 84.0             # finished card (a little smaller than a 63.5 x 88.9 poker card)
M = 12.0                      # frame margin around the card (holds reg holes, trimmed off)
SW, SH = W + 2 * M, H + 2 * M
CARD_R = 3.5
REG_D = 3.2                   # 1/8" dowel / pin
REG = [(6, 6), (SW - 6, 6), (6, SH - 6)]       # asymmetric -> layers can't go on flipped

VY = 8.0                      # valve row, mm from top edge of card (punch reach!)
VX = [9.5, 22.5, 35.5, 48.5]  # valves A B C D (13 mm pitch for a 1/4" punch)
VR = 2.2                      # valve pad radius (punch 1/4" = 6.35 mm removes it fully)
PUNCH_D = 6.35
KNEE = 5.0                    # spoke enters the valve horizontally from this far inboard
S = (29.0, 20.0); SR = 4.5    # sample pad
S_WIN = 3.5                   # sample window radius (lid + separator)
W_SPOKE, W_CH = 1.4, 1.2      # channel widths
YA, YB = 30.0, 50.0           # network band: junctions at YA, lane heads at YB
JR = 2.0                      # junction / lane-head pad radius
WIN_R = 1.4                   # separator via-hole radius (pad overlaps by 0.6 mm)
LX = [W / 2 + (k - 3.5) * 6.0 for k in range(8)]   # 8 readout lanes, 6 mm pitch
GZ_W, GZ_H = 4.8, 7.2         # readout (reaction) zone in paper
GLYPH_W, GLYPH_H, SEG_T, SEG_G = 3.4, 5.6, 0.7, 0.35
GWIN_PAD = 0.4                # separator window margin around each glyph
LEVELS = [58.0, 65.5, 73.0]   # staggered glyph heights
CLEAR = 0.8                   # min paper-to-paper gap between different nets (same layer)
BRIDGE_W = 0.6                # holding tabs, snipped after placement
PAPER_UL_PER_MM2 = 0.12       # Whatman No.1 approx bed volume
LABEL_DY, LABEL_W, LABEL_H = 7.2, 2.2, 3.6     # valve letters, scored under each ring
ID_POS, ID_W, ID_H = (4.0, 20.0), 1.8, 4.0     # card number, scored
BRACKET = (3.5, 5.5, 5.0)     # readout frame: side margin, above first level, below last level

# printed-holder mode (set by adherio_print.py); False = laser film stack, unchanged
PRINTED = False
VALVE_HOLE_R = 4.0            # printed mode: hole through every printed layer so the punch only cuts paper
STEM_VIA_DY = 7.5             # printed mode: overpass valves drop to L1 this far below the valve
SPOKE_SIDE = 6.5              # printed mode: overpass spokes run sideways then up, clear of the next valve hole

VALVE_NAMES = "ABCD"
GLYPH_POOL = list("234579ACEFHLPU")
SEG = {'0': 'abcdef', '1': 'bc', '2': 'abdeg', '3': 'abcdg', '4': 'bcfg', '5': 'acdfg', '6': 'acdefg',
       '7': 'abc', '8': 'abcdefg', '9': 'abcdfg', 'A': 'abcefg', 'b': 'cdefg', 'C': 'adef', 'd': 'bcdeg',
       'E': 'adefg', 'F': 'aefg', 'H': 'bcefg', 'L': 'def', 'P': 'abefg', 'U': 'bcdef'}
LABEL_GLYPH = {'A': 'A', 'B': 'b', 'C': 'C', 'D': 'd'}

def T(g):  # card coords -> sheet coords
    return affinity.translate(g, M, M)

def seg_line(a, b, w):
    return LineString([a, b]).buffer(w / 2, cap_style=1, resolution=24)

def poly_line(pts, w):
    return LineString(pts).buffer(w / 2, cap_style=1, join_style=1, resolution=24)

def circ(c, r):
    return Point(c).buffer(r, resolution=48)

def rounded_rect(x0, y0, x1, y1, r):
    return box(x0 + r, y0 + r, x1 - r, y1 - r).buffer(r, resolution=24)

# ------------------------------------------------------------------ 7-segment helpers
def seg_rects(ch, cx, cy, w=GLYPH_W, h=GLYPH_H, t=SEG_T, g=SEG_G):
    x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
    R = {
        'a': box(x0 + t + g, y0, x1 - t - g, y0 + t),
        'g': box(x0 + t + g, cy - t / 2, x1 - t - g, cy + t / 2),
        'd': box(x0 + t + g, y1 - t, x1 - t - g, y1),
        'f': box(x0, y0, x0 + t, cy - g), 'e': box(x0, cy + g, x0 + t, y1),
        'b': box(x1 - t, y0, x1, cy - g), 'c': box(x1 - t, cy + g, x1, y1),
    }
    return [R[s] for s in SEG[ch]]

def seg_strokes(ch, cx, cy, w, h):
    x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
    L = {'a': [(x0, y0), (x1, y0)], 'b': [(x1, y0), (x1, cy)], 'c': [(x1, cy), (x1, y1)],
         'd': [(x0, y1), (x1, y1)], 'e': [(x0, cy), (x0, y1)], 'f': [(x0, y0), (x0, cy)],
         'g': [(x0, cy), (x1, cy)]}
    return [L[s] for s in SEG[ch]]

# ------------------------------------------------------------------ network choice
def candidate_mappings(rng):
    """valve i -> 2 lanes. Keep mappings that route on 2 layers with straight traces."""
    seen, out = set(), []
    for perm in itertools.permutations(range(8)):
        pairs = tuple(tuple(sorted(perm[2 * i:2 * i + 2])) for i in range(4))
        if pairs in seen:
            continue
        seen.add(pairs)
        # scramble rules: a valve's two lanes are not neighbours, and not "its own" lanes below it
        if any(abs(a - b) <= 1 for a, b in pairs):
            continue
        if sum(l in (2 * i, 2 * i + 1) for i, p in enumerate(pairs) for l in p) > 1:
            continue
        traces = [(i, l) for i, p in enumerate(pairs) for l in p]
        adj = {t: set() for t in traces}
        ncross = 0
        for t1, t2 in itertools.combinations(traces, 2):
            if t1[0] != t2[0] and (VX[t1[0]] - VX[t2[0]]) * (LX[t1[1]] - LX[t2[1]]) < 0:
                adj[t1].add(t2); adj[t2].add(t1); ncross += 1
        # 2-colour the crossing graph, minimising traces on L2 per component
        color, ok = {}, True
        for t in traces:
            if t in color:
                continue
            comp, stack = [t], [t]; color[t] = 0
            while stack and ok:
                u = stack.pop()
                for v in adj[u]:
                    if v not in color:
                        color[v] = 1 - color[u]; comp.append(v); stack.append(v)
                    elif color[v] == color[u]:
                        ok = False; break
            if not ok:
                break
            if sum(color[c] for c in comp) > len(comp) / 2:
                for c in comp:
                    color[c] = 1 - color[c]
        if not ok:
            continue
        n2 = sum(color.values())
        if ncross < 6 or n2 > 4:
            continue
        out.append(dict(pairs=pairs, layer=color, ncross=ncross, n2=n2, score=ncross - 1.5 * n2 + rng.random()))
    out.sort(key=lambda d: -d['score'])
    return out

# ------------------------------------------------------------------ build one card
def build_card(mapping, glyphs, levels):
    E = []   # elements: dict(layer, tag, geom)
    WIN = [] # separator windows: dict(geom, tag, kind)
    def add(layer, tag, g): E.append(dict(layer=layer, tag=tag, geom=g))

    lane_valve = {l: i for i, p in enumerate(mapping['pairs']) for l in p}
    trace_layer = {(i, l): mapping['layer'][(i, l)] + 1 for i, p in enumerate(mapping['pairs']) for l in p}

    # sample pad on both layers
    add(1, 'S', circ(S, SR)); add(2, 'S', circ(S, SR))
    WIN.append(dict(geom=circ(S, S_WIN), tag='S', kind='sample'))
    for i, vx in enumerate(VX):
        inward = 1 if vx < S[0] else -1
        layer = 2 if i in (0, 3) else 1           # outer spokes go over the inner stems
        knee = (vx + inward * KNEE, VY)
        if PRINTED:
            WIN.append(dict(geom=circ((vx, VY), VALVE_HOLE_R), tag=f'V{i}', kind='valvehole'))
        if PRINTED and layer == 2:
            # valve pad lives on L2 only; stem drops through a via below the punch hole
            side = vx + inward * SPOKE_SIDE
            add(2, f'Sp{i}', poly_line([S, (side, S[1]), (side, VY), (vx, VY)], W_SPOKE))
            add(2, f'V{i}', circ((vx, VY), VR))
            vy2 = VY + STEM_VIA_DY
            add(2, f'N{i}', seg_line((vx, VY), (vx, vy2), W_CH))
            add(2, f'N{i}', circ((vx, vy2), JR)); add(1, f'N{i}', circ((vx, vy2), JR))
            WIN.append(dict(geom=circ((vx, vy2), WIN_R), tag=f'N{i}', kind='via'))
            stem_top = vy2
        else:
            add(layer, f'Sp{i}', poly_line([S, knee, (vx, VY)], W_SPOKE))
            add(1, f'V{i}', circ((vx, VY), VR))
            if layer == 2:
                add(2, f'V{i}', circ((vx, VY), VR))
                WIN.append(dict(geom=circ((vx, VY), WIN_R), tag=f'V{i}', kind='via'))
            stem_top = VY
        # stem + junction
        add(1, f'N{i}', seg_line((vx, stem_top), (vx, YA), W_CH))
        add(1, f'N{i}', circ((vx, YA), JR))
        if any(trace_layer[(i, l)] == 2 for l in mapping['pairs'][i]):
            add(2, f'N{i}', circ((vx, YA), JR))
            WIN.append(dict(geom=circ((vx, YA), WIN_R), tag=f'N{i}', kind='via'))
    for (i, l), lay in trace_layer.items():
        add(lay, f'N{i}', seg_line((VX[i], YA), (LX[l], YB), W_CH))
    for l in range(8):
        i = lane_valve[l]; x = LX[l]; cy = levels[l]
        add(1, f'N{i}', circ((x, YB), JR))
        if trace_layer[(i, l)] == 2:
            add(2, f'N{i}', circ((x, YB), JR))
            WIN.append(dict(geom=circ((x, YB), WIN_R), tag=f'N{i}', kind='via'))
        add(1, f'N{i}', seg_line((x, YB), (x, cy - GZ_H / 2 + 0.5), W_CH))
        add(1, f'N{i}', box(x - GZ_W / 2, cy - GZ_H / 2, x + GZ_W / 2, cy + GZ_H / 2))
        WIN.append(dict(geom=box(x - GLYPH_W / 2 - GWIN_PAD, cy - GLYPH_H / 2 - GWIN_PAD,
                                 x + GLYPH_W / 2 + GWIN_PAD, cy + GLYPH_H / 2 + GWIN_PAD), tag=f'N{i}', kind='glyph'))
    return E, WIN, lane_valve, trace_layer

def allowed(a, b):
    if a == b:
        return True
    s = {a, b}
    if a.startswith('Sp') and b.startswith('Sp'):
        return True                      # spokes all meet at the sample pad
    for i in range(4):
        if s == {f'Sp{i}', f'N{i}'}:     # meet only inside the valve pad (punch test checks isolation)
            return True
        if s in ({'S', f'Sp{i}'}, {f'Sp{i}', f'V{i}'}, {f'V{i}', f'N{i}'}):
            return True
    return False

def validate(E, WIN):
    errs = []
    for lay in (1, 2):
        el = [e for e in E if e['layer'] == lay]
        for a, b in itertools.combinations(el, 2):
            if not allowed(a['tag'], b['tag']):
                d = a['geom'].distance(b['geom'])
                if d < CLEAR:
                    errs.append(f"L{lay}: {a['tag']} vs {b['tag']} gap {d:.2f}")
    for w in WIN:
        for e in E:
            if PRINTED and not allowed(e['tag'], w['tag']) and e['geom'].distance(w['geom']) < CLEAR * 0.75:
                errs.append(f"printed wall too thin: window {w['tag']} ({w['kind']}) vs L{e['layer']} {e['tag']}")
            if e['geom'].intersects(w['geom'].buffer(0.3)):
                if w['kind'] == 'glyph' and e['layer'] == 2:
                    errs.append(f"L2 {e['tag']} under glyph window")
                elif not allowed(e['tag'], w['tag']):
                    errs.append(f"window {w['tag']} touches L{e['layer']} {e['tag']}")
    # card edge
    inner = rounded_rect(0, 0, W, H, CARD_R).buffer(-1.5)
    for e in E:
        if not inner.contains(e['geom']):
            errs.append(f"{e['tag']} too close to card edge")
    # punch isolation
    for i, vx in enumerate(VX):
        P = circ((vx, VY), PUNCH_D / 2)
        for lay in (1, 2):
            el = [e for e in E if e['layer'] == lay]
            up = unary_union([e['geom'] for e in el if e['tag'] == 'S' or e['tag'].startswith('Sp')])
            dn = unary_union([e['geom'] for e in el if e['tag'] == f'N{i}'])
            if not up.is_empty and not dn.is_empty and up.difference(P).distance(dn.difference(P)) < (CLEAR if PRINTED else 0.4):
                errs.append(f"punch {VALVE_NAMES[i]} does not isolate on L{lay}")
            for e in el:
                if e['tag'] not in ('S', f'Sp{i}', f'V{i}', f'N{i}') and e['geom'].distance(P) < 0.5:
                    errs.append(f"punch {VALVE_NAMES[i]} hits {e['tag']} L{lay}")
    return errs

# ------------------------------------------------------------------ paper layer with holding tabs
def paper_layer(E, lay):
    feats = unary_union([e['geom'] for e in E if e['layer'] == lay])
    comps = list(feats.geoms) if isinstance(feats, MultiPolygon) else [feats]
    card = rounded_rect(0, 0, W, H, CARD_R)
    bridges = []
    for ci, c in enumerate(comps):
        others = unary_union([o for j, o in enumerate(comps) if j != ci] + bridges)
        obst = others.buffer(CLEAR + BRIDGE_W / 2) if not others.is_empty else others
        minx, miny, maxx, maxy = c.bounds
        cands = []
        for d in ('down', 'up', 'left', 'right'):
            rng_ = (minx, maxx) if d in ('down', 'up') else (miny, maxy)
            v = rng_[0] + 0.8
            while v < rng_[1] - 0.8:
                if d in ('down', 'up'):
                    ray = LineString([(v, -5), (v, H + 5)])
                else:
                    ray = LineString([(-5, v), (W + 5, v)])
                hit = ray.intersection(c)
                if not hit.is_empty:
                    xs = [p for g in getattr(hit, 'geoms', [hit]) for p in g.coords]
                    if d == 'down':
                        p = max(xs, key=lambda q: q[1]); a, b = (v, p[1] - 0.4), (v, H + 2)
                    elif d == 'up':
                        p = min(xs, key=lambda q: q[1]); a, b = (v, p[1] + 0.4), (v, -2)
                    elif d == 'left':
                        p = min(xs, key=lambda q: q[0]); a, b = (p[0] + 0.4, v), (-2, v)
                    else:
                        p = max(xs, key=lambda q: q[0]); a, b = (p[0] - 0.4, v), (W + 2, v)
                    br = LineString([a, b]).buffer(BRIDGE_W / 2, cap_style=2)
                    if obst.is_empty or not br.intersects(obst):
                        cands.append((LineString([a, b]).length, a, br))
                v += 0.5
        cands.sort(key=lambda t: t[0])
        if not cands:
            raise RuntimeError(f"no tab for component {ci} on L{lay}")
        chosen = [cands[0]]
        for cd in cands[1:]:
            if all(Point(cd[1]).distance(Point(ch[1])) > 12 for ch in chosen) and cd[0] < 45:
                chosen.append(cd); break
        bridges += [ch[2] for ch in chosen]
    frame = box(-M, -M, W + M, H + M).difference(card)
    sheet = unary_union([frame, feats] + bridges)
    for (x, y) in REG:
        sheet = sheet.difference(circ((x - M, y - M), REG_D / 2))
    return T(sheet), T(feats), [T(b) for b in bridges], len(comps)

# ------------------------------------------------------------------ SVG output
def path_d(geom):
    out = []
    polys = list(geom.geoms) if hasattr(geom, 'geoms') else [geom]
    for p in polys:
        for ring in [p.exterior] + list(p.interiors):
            c = list(ring.coords)
            out.append('M' + ' L'.join(f'{x:.3f},{y:.3f}' for x, y in c[:-1]) + ' Z')
    return ' '.join(out)

CUT = 'fill="none" stroke="#FF0000" stroke-width="0.1"'
SCORE = 'fill="none" stroke="#0000FF" stroke-width="0.1"'

def paths_svg(geom, style):
    """every closed contour as its own simple <path> (xTool / Glowforge / LightBurn safe)"""
    out = ''
    polys = list(geom.geoms) if hasattr(geom, 'geoms') else [geom]
    for p in polys:
        for ring in [p.exterior] + list(p.interiors):
            c = list(ring.coords)
            out += '<path d="M' + ' L'.join(f'{x:.3f},{y:.3f}' for x, y in c[:-1]) + f' Z" {style}/>\n'
    return out

def svg_doc(body, title):
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{SW}mm" height="{SH}mm" viewBox="0 0 {SW} {SH}">\n'
            f'<title>{title}</title>\n<!-- red = CUT, blue = SCORE. 1 unit = 1 mm. Do not scale. -->\n{body}</svg>\n')

def sheet_and_holes():
    s = f'<path d="M0,0 L{SW},0 L{SW},{SH} L0,{SH} Z" {CUT}/>\n'
    for x, y in REG:
        s += paths_svg(circ((x, y), REG_D / 2), CUT)
    return s

def circle_svg(c, r, style):
    return paths_svg(T(circ(c, r)), style) if ('#FF0000' in style or '#0000FF' in style) else \
        f'<circle cx="{c[0]+M:.3f}" cy="{c[1]+M:.3f}" r="{r}" {style}/>\n'

def polyline_svg(pts, style):
    return '<path d="M' + ' L'.join(f'{x+M:.3f},{y+M:.3f}' for x, y in pts) + f'" {style}/>\n'

def lid_svg(card_no, glyphs, levels):
    s = sheet_and_holes()
    s += circle_svg(S, S_WIN, CUT)
    for l in range(8):
        for r in seg_rects(glyphs[l], LX[l], levels[l]):
            s += paths_svg(T(r), CUT)
    # score layer
    s += paths_svg(T(rounded_rect(0, 0, W, H, CARD_R)), SCORE)
    s += circle_svg(S, SR + 1.0, SCORE)
    for i, vx in enumerate(VX):
        s += circle_svg((vx, VY), PUNCH_D / 2 + 0.6, SCORE)
        s += polyline_svg([(vx - 1.2, VY), (vx + 1.2, VY)], SCORE) + polyline_svg([(vx, VY - 1.2), (vx, VY + 1.2)], SCORE)
        for st in seg_strokes(LABEL_GLYPH[VALVE_NAMES[i]], vx, VY + LABEL_DY, LABEL_W, LABEL_H):
            s += polyline_svg(st, SCORE)
    for st in seg_strokes(str(card_no), ID_POS[0], ID_POS[1], ID_W, ID_H):
        s += polyline_svg(st, SCORE)
    s += paths_svg(T(rounded_rect(LX[0]-BRACKET[0], LEVELS[0]-BRACKET[1], LX[7]+BRACKET[0], LEVELS[-1]+BRACKET[2], 1.5)), SCORE)
    return svg_doc(s, f'Adherio card {card_no} - LID film (opaque, adhesive down)')

def separator_svg(card_no, WIN):
    s = sheet_and_holes()
    for w in WIN:
        s += paths_svg(T(w["geom"]), CUT)
    return svg_doc(s, f'Adherio card {card_no} - SEPARATOR film (insulator, adhesive down)')

def paper_svg(card_no, lay, sheet):
    return svg_doc(paths_svg(sheet, CUT),
                   f'Adherio card {card_no} - L{lay} paper')

def base_svg():
    s = sheet_and_holes()
    s += paths_svg(T(rounded_rect(0, 0, W, H, CARD_R)), SCORE)
    return svg_doc(s, 'Adherio BASE film (adhesive up) - same for all cards')

# ------------------------------------------------------------------ previews
def preview_panels(card_no, E, WIN, glyphs, levels, lane_valve, bridges):
    """two panels: inside (lid off, layers coloured) and outside (lid on)."""
    def P(g, fill, stroke='none', op=1, extra=''):
        return f'<path d="{path_d(g)}" fill="{fill}" fill-opacity="{op}" stroke="{stroke}" stroke-width="0.25" fill-rule="evenodd" {extra}/>\n'
    vcol = ['#d1495b', '#edae49', '#00798c', '#6a4c93']
    inside = f'<rect x="{M}" y="{M}" width="{W}" height="{H}" rx="{CARD_R}" fill="#f4f1ea" stroke="#999" stroke-width="0.3"/>\n'
    for lay, op in ((1, 0.9), (2, 0.95)):
        for e in E:
            if e['layer'] != lay:
                continue
            t = e['tag']
            col = vcol[int(t[-1])] if t[0] in 'NV' or t.startswith('Sp') else '#555'
            if lay == 2:
                inside += P(T(e['geom']), col, '#111', op, 'stroke-dasharray="0.8,0.5"')
            else:
                inside += P(T(e['geom']), col, 'none', 0.55)
    for b in bridges:
        inside += P(b, '#bbb', 'none', 0.8)
    for w in WIN:
        if w['kind'] == 'via':
            inside += P(T(w['geom']), 'none', '#000', 1)
    for i, vx in enumerate(VX):
        inside += f'<circle cx="{vx+M}" cy="{VY+M}" r="{PUNCH_D/2}" fill="none" stroke="#000" stroke-width="0.25" stroke-dasharray="1,0.6"/>\n'
        inside += f'<text x="{vx+M+3.4}" y="{VY+M+5.0}" font-family="Helvetica" font-weight="bold" font-size="3" fill="{vcol[i]}">{VALVE_NAMES[i]}</text>\n'
    for l in range(8):
        inside += f'<text x="{LX[l]+M}" y="{levels[l]+M+1.2}" text-anchor="middle" font-family="Helvetica" font-weight="bold" font-size="3.4" fill="#fff">{glyphs[l]}</text>\n'
    # outside
    out = f'<rect x="{M}" y="{M}" width="{W}" height="{H}" rx="{CARD_R}" fill="#2b2b2b"/>\n'
    out += circle_svg(S, S_WIN, 'fill="#f4f1ea"')
    for l in range(8):
        col = vcol[lane_valve[l]]
        for r in seg_rects(glyphs[l], LX[l], levels[l]):
            out += P(T(r), col, 'none', 1)
    out += f'<path d="{path_d(T(rounded_rect(LX[0]-BRACKET[0], LEVELS[0]-BRACKET[1], LX[7]+BRACKET[0], LEVELS[-1]+BRACKET[2], 1.5)))}" fill="none" stroke="#9ab" stroke-width="0.3"/>\n'
    for i, vx in enumerate(VX):
        out += circle_svg((vx, VY), PUNCH_D / 2 + 0.6, 'fill="none" stroke="#9ab" stroke-width="0.3"')
        for st in seg_strokes(LABEL_GLYPH[VALVE_NAMES[i]], vx, VY + LABEL_DY, LABEL_W, LABEL_H):
            out += polyline_svg(st, 'fill="none" stroke="#9ab" stroke-width="0.35"')
    for st in seg_strokes(str(card_no), ID_POS[0], ID_POS[1], ID_W, ID_H):
        out += polyline_svg(st, 'fill="none" stroke="#9ab" stroke-width="0.35"')
    out += circle_svg(S, SR + 1.0, 'fill="none" stroke="#9ab" stroke-width="0.3"')
    return inside, out

# ------------------------------------------------------------------ main
def choose_cards(seed=2026):
    """deterministic: returns [(mapping, glyphs, levels, E, WIN, lane_valve, trace_layer)] x3"""
    rng = random.Random(seed)
    cands = candidate_mappings(rng)
    chosen, cards = [], []
    for c in cands:
        mir = tuple(tuple(sorted(7 - l for l in c['pairs'][3 - i])) for i in range(4))
        if any(sum(1 for i in range(4) if set(p[i]) != set(o['pairs'][i])) < 4 for o in chosen for p in (c['pairs'], mir)):
            continue
        for _ in range(2000):
            lv = [rng.choice(LEVELS) for _ in range(8)]
            if all(lv[k] != lv[k + 1] for k in range(7)) and max(map(lv.count, LEVELS)) - min(map(lv.count, LEVELS)) <= 1:
                break
        gl = rng.sample(GLYPH_POOL, 8)
        E, WIN, lane_valve, trace_layer = build_card(c, gl, lv)
        if validate(E, WIN):
            continue
        chosen.append(c); cards.append((c, gl, lv, E, WIN, lane_valve, trace_layer))
        if len(cards) == 3:
            break
    return cards

def main(outdir, seed=2026):
    rng = random.Random(seed)
    cands = candidate_mappings(rng)
    print(f"{len(cands)} routable scrambled networks found")
    chosen, cards = [], []
    for c in cands:
        mir = tuple(tuple(sorted(7 - l for l in c['pairs'][3 - i])) for i in range(4))
        if any(sum(1 for i in range(4) if set(p[i]) != set(o['pairs'][i])) < 4 for o in chosen for p in (c['pairs'], mir)):
            continue
        # glyphs + staggered heights (neighbouring lanes never share a height)
        for _ in range(2000):
            lv = [rng.choice(LEVELS) for _ in range(8)]
            if all(lv[k] != lv[k + 1] for k in range(7)) and max(map(lv.count, LEVELS)) - min(map(lv.count, LEVELS)) <= 1:
                break
        gl = rng.sample(GLYPH_POOL, 8)
        E, WIN, lane_valve, trace_layer = build_card(c, gl, lv)
        errs = validate(E, WIN)
        if errs:
            continue
        chosen.append(c); cards.append((c, gl, lv, E, WIN, lane_valve, trace_layer))
        if len(cards) == 3:
            break
    if len(cards) < 3:
        sys.exit("could not find 3 valid cards")

    os.makedirs(outdir, exist_ok=True)
    open(os.path.join(outdir, 'common_base_film.svg'), 'w').write(base_svg())
    summary, prev_in, prev_out = [], [], []
    for n, (c, gl, lv, E, WIN, lane_valve, trace_layer) in enumerate(cards, 1):
        d = os.path.join(outdir, f'card{n}')
        os.makedirs(d, exist_ok=True)
        bridges_all = []
        for lay in (1, 2):
            sheet, feats, bridges, ncomp = paper_layer(E, lay)
            bridges_all += bridges
            open(os.path.join(d, f'card{n}_2_L1_paper.svg' if lay == 1 else f'card{n}_4_L2_paper.svg'), 'w').write(
                paper_svg(n, lay, sheet))
        open(os.path.join(d, f'card{n}_3_separator_film.svg'), 'w').write(separator_svg(n, WIN))
        open(os.path.join(d, f'card{n}_5_lid_film.svg'), 'w').write(lid_svg(n, gl, lv))
        pin, pout = preview_panels(n, E, WIN, gl, lv, lane_valve, bridges_all)
        prev_in.append(pin); prev_out.append(pout)
        # codebook
        vol = {}
        for i in range(4):
            g = unary_union([e['geom'] for e in E if e['tag'] == f'N{i}'])
            vol[VALVE_NAMES[i]] = round(g.area * PAPER_UL_PER_MM2, 1)
        book = []
        for k in range(1, 5):
            for open_set in itertools.combinations(range(4), k):
                lit = [gl[l] for l in range(8) if lane_valve[l] in open_set]
                book.append(dict(open=''.join(VALVE_NAMES[i] for i in open_set),
                                 punch=''.join(VALVE_NAMES[i] for i in range(4) if i not in open_set),
                                 code=''.join(lit)))
        summary.append(dict(card=n, glyphs_left_to_right=''.join(gl),
                            valve_to_glyphs={VALVE_NAMES[i]: ''.join(gl[l] for l in sorted(c['pairs'][i])) for i in range(4)},
                            valve_to_lanes={VALVE_NAMES[i]: [l + 1 for l in c['pairs'][i]] for i in range(4)},
                            crossings=c['ncross'], overpass_traces_on_L2=c['n2'],
                            downstream_paper_uL=vol, codebook=book))
    json.dump(summary, open(os.path.join(outdir, 'codebook.json'), 'w'), indent=1)
    return summary, prev_in, prev_out

if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else 'out'
    summary, pin, pout = main(out)
    import pickle
    pickle.dump((summary, pin, pout), open(os.path.join(out, '.preview.pkl'), 'wb'))
    for s in summary:
        print(s['card'], s['valve_to_glyphs'], 'crossings', s['crossings'], 'L2', s['overpass_traces_on_L2'], s['downstream_paper_uL'])
