# Adherio: 3D-printed holder version (Bambu Lab)

The same 3 cards and **the same codebooks** as the laser-film version (see `codebook.csv`): card 2, punch B → `U 9 A 2 5 E`, etc.
Finished card: 58 × 84 mm. Printed stack: **1.56 mm** (base 0.52 + separator 0.44 + cover 0.60).

## Per card (`cardN/`)
| File | What | Print / cut |
|---|---|---|
| `cardN_plate.3mf` | all 3 parts laid out (fits an A1 mini) | open in Bambu Studio |
| `cardN_A_base.stl` | 0.16 mm-deep pockets for the L1 paper, 3 corner pins + 4 stake pins | any opaque PLA |
| `cardN_B_separator.stl` | flat bottom insulates L1; 0.16 mm pockets on top for L2; via holes; glyph and sample windows | any opaque PLA |
| `cardN_C_cover.stl` | already flipped: visible face on the bed, nubs up | **black/dark PLA** |
| `cardN_L1_paper.svg` | paper pieces for the base pockets (held by tabs) | laser, red = cut |
| `cardN_L2_paper_with_via_plugs.svg` | overpass pieces + one 2.5 mm plug disc per via (+2 spares, bottom row) | laser |

## Printer settings
- 0.4 mm nozzle, **"0.08 mm Extra Fine"** profile with a **0.20 mm first layer** (the default). Every thickness is 0.20 + n × 0.08, so check that both values are exact.
- No brim, no supports. The default Arachne walls print the 0.9 mm pocket walls.
- The cover's labels (A b C d, card number, rings) are recessed into the first layer, the face you see.

## Assembly
1. Base on the table, pins up.
2. Snip the L1 pieces off their paper frame and drop them into the base pockets (tweezers). Pockets have 0.15 mm clearance, so snip tab stubs flush.
3. Separator over the pins, flat side down.
4. Drop a **paper plug** into every small via hole (the round holes inside the separator's pockets).
5. L2 pieces into the separator pockets.
6. Cover over the pins, visible face up. The nubs underneath press each L2 pad onto its plug.
7. Lock it: melt the pin tips flat with a soldering iron (heat stake), or a drop of CA glue on each. Use binder clips if you want to take it apart again.

## Punching
Each valve is an 8 mm hole through all three printed parts, with only paper crossing it. Centre a 1/4" (6.35 mm) punch in the hole: it cuts only paper, so the plastic isn't touched. Valves are 8 mm from the top edge. Check that your punch's slot takes the 1.6 mm stack.

## Changing it
`python3 adherio_print.py printed` (needs `pip install shapely manifold3d trimesh`). The settings are at the top of `adherio_print.py`, e.g. `PAPER_T` / `POCKET` for thicker paper. It reuses the same networks as `adherio_gen.py` and refuses to output anything with a pocket wall under 0.9 mm or a punch that doesn't isolate its valve.
