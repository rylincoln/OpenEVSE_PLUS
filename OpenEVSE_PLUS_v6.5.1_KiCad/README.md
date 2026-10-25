# OpenEVSE PLUS v6.5.1 — KiCad port (2-layer)

A 1:1 port of `../OpenEVSE_PLUS_v6.5.1/OpenEVSE_PLUS_v6.5.1.sch` / `.brd` (EAGLE 9.6.2) to KiCad 10. No design changes: same parts, same nets, same copper. The EAGLE files stay as the upstream reference; new work happens here.

## How it was made

1. KiCad 10 GUI, EAGLE project import of the `.sch`/`.brd`, saved into this directory. The importer embeds the EAGLE libraries as `OpenEVSE_PLUS_v6.5.1-eagle-import.kicad_sym` and `OpenEVSE_PLUS_v6.5.1-import-fps.pretty/`, both project-local.
2. `docs/research/scripts/port/sch_fix.py` on the schematic, driven by the ERC report and the EAGLE `.sch`:
   - 40 wire stubs trimmed back to their net labels and 3 EAGLE dangling stubs removed (AMP_READ, GFCI_INT, ACRELAY) — none changed a net.
   - 1 junction restored where the importer dropped an EAGLE T-connection (U1 FB onto +5V).
   - 5 no-connect flags on pins EAGLE also leaves open: D1.3, D11.3, IC4 LV, IC4 OSC, IC7 pin 5.
   - 7 PWR_FLAGs: +12V, +5V, XGND, UGND, VCC, GND, PE.
   - 8 global labels for nets EAGLE named without placing a label (the importer drops such names): XGND, -12V1, DAMP, GFI_TEST_O, DC_RELAY_1_O, DC_RELAY_1_T, DC_RELAY_2_O, DC_RELAY_2_T.
   - SH1/SH2 excluded from BOM (EAGLE attribute BOM=no).
3. `docs/research/scripts/port/pcb_fix.py` on the board, library and project:
   - SH1/SH2 (`SHORT_TOP-50`) are net ties.
   - The two bare 3.2 mm holes are H1/H2 on a board-only `MountingHole_3.2mm_NPTH`.
   - EAGLE packages that shared a name across libraries got distinct footprints: `0805_SparkFun-Capacitors` (C28, C29, C32, C33), `SOT23_transistor-npn` (Q2, Q3), `SO08_SparkFun-IC-Amplifiers` (IC1).
   - Default net class clearance 0.2 → 0.1524 mm (EAGLE's 6 mil rule for this board).

Both scripts expect the raw import as input (they are not idempotent). To rerun from a fresh import:

```bash
KICAD=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
$KICAD sch erc --severity-all --format json -o erc.json OpenEVSE_PLUS_v6.5.1_KiCad/OpenEVSE_PLUS_v6.5.1.kicad_sch
python3 docs/research/scripts/port/sch_fix.py OpenEVSE_PLUS_v6.5.1_KiCad/OpenEVSE_PLUS_v6.5.1.kicad_sch erc.json OpenEVSE_PLUS_v6.5.1/OpenEVSE_PLUS_v6.5.1.sch
python3 docs/research/scripts/port/pcb_fix.py OpenEVSE_PLUS_v6.5.1_KiCad/OpenEVSE_PLUS_v6.5.1.kicad_pcb OpenEVSE_PLUS_v6.5.1_KiCad/OpenEVSE_PLUS_v6.5.1.kicad_sch OpenEVSE_PLUS_v6.5.1_KiCad/OpenEVSE_PLUS_v6.5.1-import-fps.pretty OpenEVSE_PLUS_v6.5.1_KiCad/OpenEVSE_PLUS_v6.5.1.kicad_pro
```

## Verification (kicad-cli 10.0.7)

Connectivity, compared pad for pad with `docs/research/scripts/netcmp.py`:

| comparison | differing nets |
|---|---|
| KiCad schematic netlist ↔ EAGLE `.brd` | 0 |
| KiCad schematic netlist ↔ `.kicad_pcb` | 0 |
| `.kicad_pcb` ↔ EAGLE `.brd` | 0 |

ERC: 0 errors, 42 warnings, all accepted:

- 23 `pin_to_pin` — the importer types every EAGLE `io` pin as *bidirectional*, which KiCad flags against the PWR_FLAG *power output*. Fixing pin types needs per-part datasheet work.
- 18 `endpoint_off_grid` — 0.635 mm EAGLE geometry.
- 1 `isolated_pin_label` — ADC7 label with nothing else on the net, as in EAGLE.

DRC (`--refill-zones`): 0 unconnected items, 3 errors, 230 warnings. The raw import had 8 clearance, 2 shorting-items and 7 library-mismatch violations; those are gone. What remains is in the EAGLE geometry itself:

- `starved_thermal` ×2 — Q1 pad 3 (XGND zone) and SH1 pad 2 (GND zone) get one spoke instead of KiCad's default minimum of two.
- `solder_mask_bridge` ×1 — IC2 pad 32 and L3 pad 2 are 0.153 mm apart.
- Warnings: 98 `text_height`, 62 `text_thickness` (EAGLE silk sizes), 47 `silk_over_copper`, 17 `silk_overlap`, 3 `isolated_copper` (UGND islands; EAGLE polygon had orphans=yes), 2 `silk_edge_clearance`, 1 `nonmirrored_text_on_back_layer`.

Zone fills are not stored in the files; press **B** (Refill zones) after opening the board.

## Remaining step: link board to schematic

The imported footprints carry no link to the schematic symbols yet. In the schematic editor run **Tools → Update PCB from Schematic** with *Re-link footprints to schematic symbols based on their reference designators* ON and *Delete footprints with no symbols* OFF. Footprint IDs already agree for all 115 parts, so nothing moves or swaps. Expected changes:

- 30 EAGLE auto-named nets `N$…` take KiCad names `Net-(…)`.
- 21 symbol fields (PROD_ID, MPN, MF, BOM, …) copied to footprints.
- I2C0, JP2 and PILOT0 get their symbol values (`M04JST-PTH-VERT`, `M06POLAR_LOCK`, `M025MM` — EAGLE deviceset names, as these parts had no value).
- The 5 open pads get `unconnected-…` nets.

## Known differences from the EAGLE files

- References without a trailing digit gained a `0`: AC0, FTDI0, I2C0, PILOT0, TVS0, GFCI_CT0, AMP_CT0, DC_RELAY0 (schematic and board agree).
- Parts that had no EAGLE value show their deviceset name as the value.
