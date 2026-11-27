#!/usr/bin/env python3
"""Build the self-contained demo pages into docs/ (served by GitHub Pages).

  python3 web/export_cards.py     # only when the card design changes (needs shapely, manifold3d, trimesh)
  python3 web/build.py            # inlines web/cards.json + web/src/core.js into each page
"""
import os, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "docs")

data = open(os.path.join(HERE, "cards.json")).read()
core = open(os.path.join(HERE, "src", "core.js")).read()
os.makedirs(OUT, exist_ok=True)
for name in ("explainer.html", "app.html", "index.html"):
    src = open(os.path.join(HERE, "src", name)).read()
    src = src.replace("/*@DATA@*/", data).replace("/*@CORE@*/", core)
    open(os.path.join(OUT, name), "w").write(src)
    print("wrote", os.path.join("docs", name), os.path.getsize(os.path.join(OUT, name)) // 1024, "KB")
open(os.path.join(OUT, ".nojekyll"), "w").write("")
