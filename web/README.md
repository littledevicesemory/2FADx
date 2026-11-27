# 2FA Dx demo software

Two browser demos for the 2FA Dx printed card, built from the same design files as the STLs and paper SVGs in this repository. They run from GitHub Pages (`docs/`), and each page is one self-contained HTML file that also works opened straight from disk.

| Page | What it shows |
|---|---|
| `docs/explainer.html` | **How the card works.** Six animated chapters: the layer stack, sample in, punching valves, crossings and vias, the readout, and all 15 key → code pairs (interactive). |
| `docs/app.html` | **Key and verify.** A clinic console and a patient's phone side by side. The clinic texts a daily key ("your key today is C D and your card is 3"). The patient runs the card on screen (punch valves, add sample, read the glyphs) and texts back the code. The clinic verifies it and logs adherence. |

## How the simulation works
- `web/export_cards.py` runs `adherio_gen.py` + `adherio_print.py` in printed mode and writes `web/cards.json`: vector shapes for every layer, the 8 readout lanes and their 7-segment glyphs, vias, valves, and each card's codebook. The script checks every codebook against `codebook.csv`.
- It also writes a 0.4 mm occupancy grid of both paper layers, labelled by network. In the browser, wicking is the shortest path through paper from the sample pad. The layers join only at vias, and a punched valve removes a 6.35 mm disc of paper. A readout pad reacts when it is fully wet. This reproduces all 45 codebook entries (15 keys × 3 cards).
- Sample volume uses Whatman No.1 at 0.12 µL/mm², as in `adherio_gen.py`. A "small drop" in the app stops the front early, giving an incomplete code.
- Schematic (and labelled so on the pages): the front's timing, the colour of the reacted swatch, the via cross-section's proportions.

## Verification rules (app)
A reply is normalised (upper case, symbols removed), then:
- **Verified**: equals the code for today's card and key.
- **Wrong valves**: a real code for today's card under a different punch pattern.
- **Wrong card**: today's key's code on another card in the patient's kit.
- **Incomplete**: the expected glyphs, in order, with some missing (too little sample, or read too early).
- **Not a code**: nothing in any codebook produces it.

The patient gets three tries per day. A key with no reply when the next day starts is recorded as missed. Keys are drawn from the 14 patterns that punch at least one valve and leave at least one open.

This is demo software for the paper, not a deployment. Both roles run in one page and share the codebook. Texts are simulated, and state is kept in the browser's localStorage. In a real system the codebook would stay on the clinic's server, and the patient's phone would only relay the reply.

## Rebuild
```bash
pip install shapely manifold3d trimesh
python3 web/export_cards.py   # when the card design changes
python3 web/build.py          # inlines cards.json + src/core.js into docs/*.html
```
Sources: `web/src/core.js` (shared simulation and drawing), `web/src/explainer.html`, `web/src/app.html`, `web/src/index.html`.
