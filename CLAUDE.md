# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Hardware design files for the OpenEVSE PLUS board, an SAE J1772 / IEC 61851 EV charging station controller (ATmega328P MCU, pilot circuit, GFCI, AC detect/ground monitor, relay drivers and on-board power supply). There is nothing to build, lint or test. Every revision is in EAGLE except one KiCad 8 variant. Neither EAGLE nor KiCad (`kicad-cli`) is installed on this machine, so inspect the designs as text (see below). License: CC BY-SA 3.0.

## Layout

Each top-level `OpenEVSE_PLUS_v<rev>/` directory is one board revision. The newest revision is the one on the README's "Current Version" line, currently `OpenEVSE_PLUS_v6.5.1`. A new revision gets its own directory plus a changelog entry at the top of `README.md`, which is ordered newest first and embeds images by absolute GitHub `blob` URLs.

What each file in a revision directory is:

- `.sch` / `.brd`: EAGLE schematic and board. These are the source of truth.
- `*_GERBER.zip` / `*_GERBERS.zip` / `*.Gerbers.zip`: CAM output for a 2-layer board (top and bottom copper, mask, silk, cream, drills). The filenames inside are not consistent: v2.5's zip holds `OpenEVSE_PLUS_v3_L1L2.*` and v5.5's has no basename. v6.5.1 has no Gerbers yet.
- `OpenEVSE_PLUS_v<rev>.zip`: a release bundle of the sch, brd and Gerbers taken at a single point in time. It can be older than the loose files. For example, v4's bundle is EAGLE 7.1.0 with `MEGA8-AI`, while the loose v4 files were updated in 2017 to 7.3.0 with `ATMEGA328P-AU`.
- `.pdf` exported by EAGLE (e.g. `OpenEVSE_PLUS_v5.5.pdf`, `*_SCH.pdf`): a schematic print.
- `.pdf` exported by Visio (`OpenEVSE_v<rev>.pdf`, `Advanced_*.pdf`, `Standard_*.pdf`): connector pinout and station wiring diagrams. The Visio sources are not in the repo, so these can't be regenerated here.

EAGLE file versions range from 6.0 (v1) to 9.6.2 (v5.5, v6.5.1).

`OpenEVSE_PLUS_v6.5.1_6Layer/` is the exception. It is a KiCad 8 project (`v6_6layer.kicad_*`) for a 6-layer board: F.Cu, In1 GND_F, In2 PWR, In3 signal, In4 GND_B, B.Cu. Its Gerbers and drill files are loose `.gbr`/`.drl` files, not zipped. The README doesn't mention it yet. It was imported from EAGLE (its symbol libraries are named `OpenEVSE_PLUS_v6.5RC2-eagle-import`), so it doesn't match the EAGLE v6.5.1 design exactly:

- Connector references gained a `0` suffix (`AC`→`AC0`, `FTDI`→`FTDI0`, `PILOT`→`PILOT0`).
- `C28`, the fiducials and `SH1`/`SH2` are missing.
- EAGLE parts that had no value use their deviceset name as the value.

## Reading design files

The KiCad files are S-expressions with a `(property "Reference" ...)`/`(property "Value" ...)` pair on each placed symbol, so grep or regex works on them. Everything below applies to EAGLE.

The EAGLE `.sch` and `.brd` files are XML of up to about 2.5 MB, with the part libraries embedded. Parse or grep them instead of reading them whole. To dump a netlist with the MCU pin names:

```bash
python3 - OpenEVSE_PLUS_v6.5.1/OpenEVSE_PLUS_v6.5.1.sch <<'EOF'
import sys, xml.etree.ElementTree as ET
s = ET.parse(sys.argv[1]).getroot().find('drawing/schematic')
for net in s.iterfind('sheets/sheet/nets/net'):
    print(net.get('name'), sorted({(p.get('part'), p.get('pin')) for p in net.iter('pinref')}))
EOF
```

- Parts are at `drawing/schematic/parts/part` (`name`, `value`, `deviceset`). Board placements are at `drawing/board/elements/element`.
- For the real component, read `value`, not `deviceset`. Devicesets are reused library symbols: `IC2` is deviceset `MEGA8` with value `ATMEGA328P-AU`, the `LMV358` deviceset holds an LM358 or LF353, and `BAS40-06` holds an AZ23C5V6 zener.
- Unnamed nets are `N$<n>`, and some functionally important nets are unnamed. In v6.5.1, for instance, the board-detect strap on PD7 is `N$12`. Look up MCU signals by `IC2` pin name, not by net name.

## Firmware contract

The firmware lives in a separate repo (OpenEVSE `open_evse`). Which MCU pin each net uses is part of the interface with that firmware. Boards identify themselves to it through strap pins: v5.5+ pulls PD7 high so firmware selects the new pinout (GFCI test moved, DC relays moved to PWM pins for 7.1.2+), and v6.5 pulls ADC6 high to signal the continuous ground-monitoring (CGMI) requirement. A change that moves an MCU pin or a strap needs a matching firmware change and a README note.
