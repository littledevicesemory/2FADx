#!/usr/bin/env python3
"""
Export the three printed Adherio / 2FA Dx cards to one JSON file for the web demos.

Runs the same generator path as adherio_print.py (printed mode), then writes, per card:
  * vector shapes (SVG path strings, card coordinates in mm, y down): paper L1/L2 by net,
    vias, valve holes, sample window, readout zones, 7-segment glyph windows, cover labels
  * a 0.4 mm occupancy grid of both paper layers, run-length encoded, labelled by net
    (0 = no paper, 1 = sample pad, 2..5 = valve A..D net) plus a via mask, so the browser
    can simulate wicking (Dijkstra from the sample pad) for any punch pattern
  * the codebook, checked against codebook.csv

Usage:  python3 web/export_cards.py  [out.json]     (needs shapely, manifold3d, trimesh)
"""
import os, sys, json, csv, itertools
import numpy as np
from shapely.geometry import Point, box
from shapely.ops import unary_union
from shapely import prepared

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import adherio_gen as G
import adherio_print as P

CELL = 0.4  # mm

def path_d(g, nd=2):
    if g is None or g.is_empty:
        return ""
    polys = list(g.geoms) if hasattr(g, "geoms") else [g]
    out = []
    for p in polys:
        if p.is_empty or p.geom_type != "Polygon":
            continue
        for r in [p.exterior] + list(p.interiors):
            cs = list(r.coords)[:-1]
            out.append("M" + "L".join(f"{x:.{nd}f},{y:.{nd}f}" for x, y in cs) + "Z")
    return "".join(out)

def rle(arr):
    flat = arr.ravel().tolist()
    out, cur, n = [], flat[0], 0
    for v in flat:
        if v == cur:
            n += 1
        else:
            out += [cur, n]; cur, n = v, 1
    out += [cur, n]
    return out

def raster(geoms_labels, nx, ny):
    """geoms_labels: list of (geom, label). Later entries win."""
    grid = np.zeros((ny, nx), dtype=np.uint8)
    xs = (np.arange(nx) + 0.5) * CELL
    ys = (np.arange(ny) + 0.5) * CELL
    for g, lab in geoms_labels:
        pg = prepared.prep(g)
        x0, y0, x1, y1 = g.bounds
        i0, i1 = max(0, int(x0 / CELL) - 1), min(nx, int(x1 / CELL) + 2)
        j0, j1 = max(0, int(y0 / CELL) - 1), min(ny, int(y1 / CELL) + 2)
        for j in range(j0, j1):
            for i in range(i0, i1):
                if pg.contains(Point(xs[i], ys[j])):
                    grid[j, i] = lab
    return grid

def net_label(tag):
    if tag == "S":
        return 1
    return 2 + int(tag[-1])

def main(out):
    laser = G.choose_cards()
    levels_idx = [[G.LEVELS.index(v) for v in c[2]] for c in laser]
    P.configure()
    nx, ny = int(round(G.W / CELL)), int(round(G.H / CELL))
    book_csv = {}
    with open(os.path.join(ROOT, "codebook.csv")) as f:
        for r in csv.DictReader(f):
            book_csv[(int(r["card"]), r["open_valves"])] = r["code_left_to_right"]

    cards = []
    for n, (c, gl, *_r) in enumerate(laser, 1):
        lv = [G.LEVELS[k] for k in levels_idx[n - 1]]
        E, WIN, lane_valve, trace_layer = G.build_card(c, gl, lv)
        errs = G.validate(E, WIN)
        assert not errs, errs
        stakes = P.pick_stakes(E, WIN)
        pins = P.CORNER_PINS + stakes

        # ---------------- vector shapes
        paper = {}
        for lay in (1, 2):
            nets = {}
            for e in E:
                if e["layer"] == lay:
                    nets.setdefault(net_label(e["tag"]), []).append(e["geom"])
            paper[f"L{lay}"] = {str(k): path_d(unary_union(v)) for k, v in sorted(nets.items())}
        vias = [dict(x=round(w["geom"].centroid.x, 3), y=round(w["geom"].centroid.y, 3), r=G.WIN_R,
                     net=net_label(w["tag"])) for w in WIN if w["kind"] == "via"]
        glyph_win = [path_d(w["geom"]) for w in WIN if w["kind"] == "glyph"]
        lanes = []
        for l in range(8):
            segs = G.seg_rects(gl[l], G.LX[l], lv[l], G.GLYPH_W, G.GLYPH_H, G.SEG_T, G.SEG_G)
            lanes.append(dict(lane=l, x=G.LX[l], y=lv[l], glyph=gl[l], valve=lane_valve[l],
                              layer=trace_layer[(lane_valve[l], l)],
                              zone=[G.LX[l] - G.GZ_W / 2, lv[l] - G.GZ_H / 2, G.GZ_W, G.GZ_H],
                              segments=path_d(unary_union(segs))))
        labels = []
        for i, vx in enumerate(G.VX):
            labels.append(path_d(P.stroke_geom(G.LABEL_GLYPH[G.VALVE_NAMES[i]], vx,
                                               G.VY + G.VALVE_HOLE_R + 0.9 + G.LABEL_H / 2, G.LABEL_W, G.LABEL_H)))
        card_id = path_d(P.stroke_geom(str(n), G.ID_POS[0] + 1.5, G.ID_POS[1], G.ID_W + 0.4, G.ID_H))
        br = G.rounded_rect(G.LX[0] - G.BRACKET[0], G.LEVELS[0] - G.BRACKET[1], G.LX[7] + G.BRACKET[0],
                            G.LEVELS[-1] + G.BRACKET[2], 1.5)
        bracket = path_d(br.difference(br.buffer(-0.6)))

        # ---------------- wicking grid
        grids = {}
        for lay in (1, 2):
            gls = [(e["geom"], net_label(e["tag"])) for e in E if e["layer"] == lay and e["tag"] != "S"]
            gls = [(e["geom"], 1) for e in E if e["layer"] == lay and e["tag"] == "S"] + gls
            grids[lay] = raster(gls, nx, ny)
        via_mask = raster([(w["geom"], 1) for w in WIN if w["kind"] == "via"], nx, ny)

        # ---------------- codebook (open set -> glyphs fed, read left to right)
        book = []
        for k in range(1, 5):
            for open_set in itertools.combinations(range(4), k):
                code = "".join(gl[l] for l in range(8) if lane_valve[l] in open_set)
                o = "".join(G.VALVE_NAMES[i] for i in open_set)
                p = "".join(G.VALVE_NAMES[i] for i in range(4) if i not in open_set)
                assert book_csv[(n, o)] == code, (n, o, code, book_csv[(n, o)])
                book.append(dict(open=o, punch=p, code=code))

        vol = {G.VALVE_NAMES[i]: round(unary_union([e["geom"] for e in E if e["tag"] == f"N{i}"]).area
                                       * G.PAPER_UL_PER_MM2, 1) for i in range(4)}
        cards.append(dict(
            card=n, W=G.W, H=G.H, R=G.CARD_R,
            sample=dict(x=G.S[0], y=G.S[1], r=G.SR, win=G.S_WIN),
            valves=[dict(name=G.VALVE_NAMES[i], x=G.VX[i], y=G.VY, hole=G.VALVE_HOLE_R, pad=G.VR,
                         spoke_layer=2 if i in (0, 3) else 1) for i in range(4)],
            punch_r=G.PUNCH_D / 2,
            pins=[dict(x=round(x, 2), y=round(y, 2)) for x, y in pins], pin_r=P.PIN_R,
            paper=paper, vias=vias, glyph_windows=glyph_win, lanes=lanes,
            labels=labels, card_id=card_id, bracket=bracket,
            valve_to_lanes={G.VALVE_NAMES[i]: sorted(c["pairs"][i]) for i in range(4)},
            crossings=c["ncross"], downstream_paper_uL=vol,
            thickness=dict(base=P.BASE_T, separator=P.SEP_T, cover=P.COVER_T, paper=P.PAPER_T),
            grid=dict(cell=CELL, nx=nx, ny=ny, L1=rle(grids[1]), L2=rle(grids[2]), via=rle(via_mask)),
            codebook=book,
        ))
        print(f"card {n}: glyphs {''.join(gl)}  vias {len(vias)}  grid {nx}x{ny}")
    json.dump(dict(source="adherio_gen.py + adherio_print.py (printed mode), seed 2026",
                   glyph_pool=G.GLYPH_POOL, seg=G.SEG, cards=cards), open(out, "w"), separators=(",", ":"))
    print("wrote", out, os.path.getsize(out) // 1024, "KB")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "cards.json"))
