"""Clean up the EAGLE-imported KiCad board and project without changing copper.

Usage: python3 pcb_fix.py <file.kicad_pcb> <file.kicad_sch> <lib.pretty> <file.kicad_pro>

- SH1/SH2 (EAGLE SHORT footprints) become net ties, so DRC stops reporting them as shorts.
- The two bare mounting holes (dummyfp0/1, UNK_HOLE_*) become H1/H2 on a board-only
  MountingHole_3.2mm_NPTH footprint, so schematic parity ignores them.
- EAGLE had several packages sharing one name (0805, SOT23, SO08) from different libraries; the importer
  kept one copy per name in the .pretty. The other copies are saved under distinct names, taken verbatim
  from the board, and the board and schematic are pointed at them.
- The default net-class clearance becomes 6 mil (0.1524 mm), EAGLE's rule for this board.
"""
import json, os, re, sys

pcb_path, sch_path, pretty, pro_path = sys.argv[1:5]
pcb = open(pcb_path).read()
sch = open(sch_path).read()
LIB = os.path.basename(pretty).replace('.pretty', '')

VARIANTS = {  # ref -> (old name, new name)   [EAGLE source library of each ref: board element attributes]
    'C28': ('0805', '0805_SparkFun-Capacitors'), 'C29': ('0805', '0805_SparkFun-Capacitors'),
    'C32': ('0805', '0805_SparkFun-Capacitors'), 'C33': ('0805', '0805_SparkFun-Capacitors'),
    'Q2': ('SOT23', 'SOT23_transistor-npn'), 'Q3': ('SOT23', 'SOT23_transistor-npn'),
    'IC1': ('SO08', 'SO08_SparkFun-IC-Amplifiers'),
}
HOLES = {'UNK_HOLE_0': 'H1', 'UNK_HOLE_1': 'H2'}
HOLE_FP = 'MountingHole_3.2mm_NPTH'


def blocks(t, head):
    i = 0
    while True:
        k0 = t.find(head, i)
        if k0 < 0:
            return
        d, k = 0, k0
        while True:
            c = t[k]
            if c == '(':
                d += 1
            elif c == ')':
                d -= 1
                if d == 0:
                    break
            k += 1
        yield (k0, k + 1, t[k0:k + 1])
        i = k + 1


def lib_file_from_instance(fp_text, name):
    """Turn a board footprint instance into a .kicad_mod body (verbatim geometry, no instance data)."""
    body = re.sub(r'\(footprint "[^"]*"', f'(footprint "{name}"', fp_text, count=1)
    body = re.sub(r'\n\t\t\(uuid "[^"]*"\)', '', body, count=1)              # footprint-level uuid
    at = re.search(r'\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', body)
    rot = float(at.group(3) or 0)
    body = body[:at.start()] + body[at.end():]                               # placement

    def local_pad_angle(m):                                                  # pad angles are stored absolute
        a = (float(m.group(3) or 0) - rot) % 360
        return f'{m.group(1)}(at {m.group(2)}{"" if a == 0 else f" {a:g}"})'
    body = re.sub(r'(\(pad "[^"]*" \w+ \w+\n\t\t\t)\(at ([-\d.]+ [-\d.]+)(?: ([-\d.]+))?\)', local_pad_angle, body)
    body = re.sub(r'\n\t\t\((path|sheetname|sheetfile) "[^"]*"\)', '', body)
    body = re.sub(r'\n\t\t\t\(net \d+ "[^"]*"\)', '', body)                 # pad nets
    body = re.sub(r'\(property "Reference" "[^"]*"', '(property "Reference" "REF**"', body, count=1)
    body = re.sub(r'\(property "Value" "[^"]*"', f'(property "Value" "{name}"', body, count=1)
    body = body.replace('\n\t', '\n')                                         # board nesting -> file nesting
    body, n = re.subn(r'\n\t\(layer "([^"]*)"\)', r'\n\t(version 20260206)\n\t(generator "pcbnew")\n\t(generator_version "10.0")\n\t(layer "\1")', body, count=1)
    assert n == 1, name
    return body.rstrip() + '\n'


def add_attrs(fp_text, indent, *tokens):
    """Insert footprint-level tokens (attr, net_tie_pad_groups) where KiCad writes them: after the
    properties, before the first graphic/pad. The imported footprints carry no attr line of their own."""
    assert f'\n{indent}(attr ' not in fp_text
    first = min(i for i in (fp_text.find(f'\n{indent}(fp_'), fp_text.find(f'\n{indent}(pad ')) if i >= 0)
    return fp_text[:first] + ''.join(f'\n{indent}({t})' for t in tokens) + fp_text[first:]


written = {}
out = []
last = 0
for b0, e0, fp in blocks(pcb, '\n\t(footprint '):
    ref = re.search(r'\(property "Reference" "([^"]*)"', fp).group(1)
    new = fp
    if ref in ('SH1', 'SH2'):
        new = add_attrs(new, '\t\t', 'attr exclude_from_bom', 'net_tie_pad_groups "1, 2"')
    if ref in HOLES:
        new = re.sub(r'\(footprint "[^"]*"', f'(footprint "{LIB}:{HOLE_FP}"', new, count=1)
        new = new.replace(f'"Reference" "{ref}"', f'"Reference" "{HOLES[ref]}"', 1)
        new = add_attrs(new, '\t\t', 'attr board_only exclude_from_pos_files exclude_from_bom')
        if HOLE_FP not in written:
            written[HOLE_FP] = lib_file_from_instance(new, HOLE_FP)
    if ref in VARIANTS:
        old, name = VARIANTS[ref]
        assert f'(footprint "{LIB}:{old}"' in new, (ref, new[:80])
        new = new.replace(f'(footprint "{LIB}:{old}"', f'(footprint "{LIB}:{name}"', 1)
        if name not in written:
            written[name] = lib_file_from_instance(new, name)
        # every unit of a multi-unit symbol carries its own Footprint property
        sch, n = re.subn(rf'("Reference" "{re.escape(ref)}"\n(?:.|\n)*?\(property "Footprint" ")[^"]*"', rf'\g<1>{LIB}:{name}"', sch)
        assert n >= 1, ref
    out.append(pcb[last:b0]); out.append(new); last = e0
out.append(pcb[last:])
pcb = ''.join(out)
open(pcb_path, 'w').write(pcb)
open(sch_path, 'w').write(sch)

for name, body in written.items():
    open(os.path.join(pretty, name + '.kicad_mod'), 'w').write(body)
mod = os.path.join(pretty, 'SHORT_TOP-50.kicad_mod')
t = open(mod).read()
if 'net_tie_pad_groups' not in t:
    open(mod, 'w').write(add_attrs(t, '\t', 'attr exclude_from_bom', 'net_tie_pad_groups "1, 2"'))
for f in ('dummyfp0.kicad_mod', 'dummyfp1.kicad_mod'):
    p = os.path.join(pretty, f)
    if os.path.exists(p):
        os.remove(p)

pro = json.load(open(pro_path))
for c in pro['net_settings']['classes']:
    if c['name'] == 'Default':
        c['clearance'] = 0.1524
json.dump(pro, open(pro_path, 'w'), indent=2)
open(pro_path, 'a').write('\n')
print('library files written:', sorted(written), '| dummy footprints removed | Default clearance 0.1524 mm')
