"""Clean up the EAGLE-imported KiCad schematic without changing connectivity.

Usage: python3 sch_fix.py <file.kicad_sch> <erc.json> <eagle.sch> [power.kicad_sym]
  erc.json comes from: kicad-cli sch erc --severity-all --format json -o erc.json <file.kicad_sch>
  eagle.sch is the EAGLE source schematic.
  power.kicad_sym is KiCad's stock power library (PWR_FLAG is copied from it verbatim);
  defaults to the macOS KiCad.app location.

Edits driven by the ERC report (nothing is hard-coded by eye):
- pin_not_connected       -> a no-connect flag on that pin, except where the pin's wire dangles onto the
                             body of another wire (an EAGLE T-junction the importer dropped): add a junction.
- power_pin_not_driven    -> a PWR_FLAG stacked on that pin.
- unconnected_wire_endpoint:
    * a net label sits on the wire body -> shorten the wire to end at the label (or drop it if that empties it)
    * the end sits on another wire's body -> add a junction
    * nothing anywhere (EAGLE's own dangling stubs) -> delete the stub

Edits driven by the EAGLE schematic:
- EAGLE keeps a net's name without any label on the sheet; KiCad cannot, so the importer silently drops
  those names (XGND, -12V1, DC_RELAY_*, ...) and the board's zones/nets would be renamed on the next
  "Update PCB from Schematic". Every named, label-less EAGLE net gets a local label on one of its wires.
- Symbols whose EAGLE BOM attribute is "no" (the SH1/SH2 shorts) are marked (in_bom no).

Verify afterwards with ERC, a netlist export and docs/research/scripts/netcmp.py against the EAGLE board.
"""
import json, math, re, sys, uuid
import xml.etree.ElementTree as ET

path, erc_path, eagle_path = sys.argv[1], sys.argv[2], sys.argv[3]
power_lib = sys.argv[4] if len(sys.argv) > 4 else '/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols/power.kicad_sym'
s = open(path).read()
erc = json.load(open(erc_path))['sheets'][0]['violations']


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


def pos(v):
    p = v['items'][0]['pos']
    return (round(p['x'], 4), round(p['y'], 4))


# --- geometry we need: pin endpoints, wires, labels, junctions -------------------------------------
lib_start = s.find('(lib_symbols')
lib_end = next(e for b, e, _ in blocks(s, '\n\t(lib_symbols'))
lib = s[lib_start:lib_end]
libpins = {}
for _, _, b in blocks(lib, '\n\t\t(symbol "'):
    name = re.search(r'\(symbol "([^"]*)"', b).group(1)
    libpins[name] = []
    for _, _, pb in blocks(b, '(pin '):
        m = re.search(r'\(at ([-\d.]+) ([-\d.]+) [-\d.]+\)', pb)
        libpins[name].append((re.search(r'\(name "([^"]*)"', pb).group(1), float(m.group(1)), float(m.group(2))))
pins = set()
pin_at = {}        # (reference, pin name) -> sheet position
bom_no = set()     # symbol uuids with EAGLE attribute BOM=no
for _, _, b in blocks(s, '\n\t(symbol\n'):
    lid = re.search(r'\(lib_id "([^"]*)"', b).group(1)
    ref = re.search(r'\(property "Reference" "([^"]*)"', b).group(1)
    if re.search(r'\(property "BOM" "no"', b):
        bom_no.add(re.search(r'\n\t\t\(uuid "([^"]*)"\)', b).group(1))
    at = re.search(r'\n\t\t\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)', b)
    x0, y0, rot = float(at.group(1)), float(at.group(2)), float(at.group(3))
    mir = re.search(r'\n\t\t\(mirror (\w)\)', b)
    for pname, px, py in libpins.get(lid, []):
        if mir and mir.group(1) == 'y':
            px = -px
        if mir and mir.group(1) == 'x':
            py = -py
        a = math.radians(rot)
        rx, ry = px * math.cos(a) - py * math.sin(a), px * math.sin(a) + py * math.cos(a)
        p = (round(x0 + rx, 4), round(y0 - ry, 4))
        pins.add(p)
        pin_at[(ref, pname)] = p
wires = {}
for b0, e0, b in blocks(s, '\n\t(wire\n'):
    pts = [(float(a), float(c)) for a, c in re.findall(r'\(xy ([-\d.]+) ([-\d.]+)\)', b)]
    wires[re.search(r'\(uuid "([^"]*)"', b).group(1)] = (b0, e0, pts)
labels = {}
for _, _, b in blocks(s, '\n\t(global_label'):
    m = re.search(r'\(at ([-\d.]+) ([-\d.]+)', b)
    labels[(float(m.group(1)), float(m.group(2)))] = re.search(r'"([^"]*)"', b).group(1)
junctions = {(float(a), float(c)) for _, _, b in blocks(s, '\n\t(junction') for a, c in [re.search(r'\(at ([-\d.]+) ([-\d.]+)', b).groups()]}
ends = {}
for u, (_, _, pts) in wires.items():
    for p in (pts[0], pts[-1]):
        ends.setdefault(p, []).append(u)


def onbody(p, pts):
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    x, y = p
    if (x, y) in ((x1, y1), (x2, y2)):
        return False
    return (min(x1, x2) - 1e-6 <= x <= max(x1, x2) + 1e-6 and min(y1, y2) - 1e-6 <= y <= max(y1, y2) + 1e-6
            and abs((x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)) < 1e-6)


def connected(p, exclude_wire):
    return p in pins or p in labels or p in junctions or any(u != exclude_wire for u in ends.get(p, []))


# --- plan the edits ---------------------------------------------------------------------------------
new_junctions, new_noconnects, new_flags = set(), [], []
replace = {}   # wire uuid -> new text ('' deletes)
log = []

for v in erc:
    if v['type'] != 'unconnected_wire_endpoint':
        continue
    u = v['items'][0]['uuid']
    b0, e0, pts = wires[u]
    for p in (pts[0], pts[-1]):
        if connected(p, u):
            continue
        other = pts[-1] if p == pts[0] else pts[0]
        on_label = [lp for lp in labels if onbody(lp, pts)]
        on_wire = [u2 for u2, (_, _, pts2) in wires.items() if u2 != u and onbody(p, pts2)]
        if on_label:
            lp = on_label[0]
            if lp == other:
                replace[u] = ''
                log.append(f'delete wire {p}->{other}: label {labels[lp]} already at its other end')
            else:
                txt = s[b0:e0].replace(f'(xy {p[0]:g} {p[1]:g})', f'(xy {lp[0]:g} {lp[1]:g})')
                assert txt != s[b0:e0], (p, s[b0:e0])
                replace[u] = txt
                log.append(f'trim wire end {p} to label {labels[lp]} at {lp}')
        elif on_wire:
            new_junctions.add(p)
            log.append(f'junction at {p}: wire end on body of another wire (dropped EAGLE T)')
        else:
            replace[u] = ''
            log.append(f'delete stub {p}->{other}: EAGLE stub with no connection at either side beyond {other}')

# sanity check on the symbol transform above: every placed pin that has a wire must land on a wire end
hits = sum(1 for p in pins if p in ends)
assert hits > 0.8 * len(pins), f'pin transform looks wrong: only {hits}/{len(pins)} pins sit on wire ends'

# named EAGLE nets that have no label element: give each a local label on the wire leaving one of its pins
new_labels = []
for net in ET.parse(eagle_path).iter('net'):
    name = net.get('name')
    if name.startswith('N$') or any(True for _ in net.iter('label')):
        continue
    if any(('#' + pr.get('part'), pr.get('pin')) in pin_at for pr in net.iter('pinref')):
        continue        # an EAGLE supply part became a KiCad power symbol; it already names the net
    for pr in net.iter('pinref'):
        part = pr.get('part')
        kref = part if part[-1].isdigit() else part + '0'      # the importer suffixes refs lacking a digit
        p = pin_at.get((kref, pr.get('pin')))
        if p is None or p not in ends:
            continue
        _, _, pts = wires[ends[p][0]]
        other = pts[-1] if p == pts[0] else pts[0]
        mid = (round((p[0] + other[0]) / 2, 4), round((p[1] + other[1]) / 2, 4))
        rot = 0 if other[1] == p[1] else 90
        new_labels.append((name, mid, rot))
        log.append(f'global label {name} on wire {p}->{other} of {kref}.{pr.get("pin")} (EAGLE net named but unlabelled)')
        break
    else:
        sys.exit(f'no wire found to carry the net name {name}: {[(pr.get("part"), pr.get("pin")) for pr in net.iter("pinref")]}')

for v in erc:
    if v['type'] == 'pin_not_connected':
        p = pos(v)
        if any(onbody(p, pts) is False and p in (pts[0], pts[-1]) for _, _, pts in wires.values()):
            # pin has a wire; the wire-end handler above adds the junction
            continue
        new_noconnects.append(p)
        log.append(f'no-connect on {v["items"][0]["description"]} at {p}')
    if v['type'] == 'power_pin_not_driven':
        p = pos(v)
        new_flags.append(p)
        log.append(f'PWR_FLAG on {v["items"][0]["description"]} at {p}')

# --- apply ------------------------------------------------------------------------------------------
project = re.search(r'\(project "([^"]*)"', s).group(1)
sheet_path = re.search(r'\(path "(/[0-9a-f-]+)"', s).group(1)

# PWR_FLAG comes verbatim from the stock library (one tab deeper, lib-qualified name) so ERC's
# lib_symbol_mismatch check stays quiet.
_, _, flag_src = next(b for b in blocks(open(power_lib).read(), '\n\t(symbol "PWR_FLAG"'))
PWR_FLAG_LIB = '\t' + flag_src.lstrip('\n').replace('\n', '\n\t').replace('(symbol "PWR_FLAG"', '(symbol "power:PWR_FLAG"', 1) + '\n'


def prop(name, val, x, y, hide):
    h = '\n\t\t\t(hide yes)' if hide else ''
    return f'\t\t(property "{name}" "{val}"\n\t\t\t(at {x:g} {y:g} 0){h}\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n'


def flag_instance(n, p):
    x, y = p
    return (f'\t(symbol\n\t\t(lib_id "power:PWR_FLAG")\n\t\t(at {x:g} {y:g} 0)\n\t\t(unit 1)\n\t\t(body_style 1)\n'
            f'\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n\t\t(on_board yes)\n\t\t(in_pos_files yes)\n\t\t(dnp no)\n'
            f'\t\t(uuid "{uuid.uuid4()}")\n'
            + prop('Reference', f'#FLG0{n}', x, y - 1.905, True) + prop('Value', 'PWR_FLAG', x, y - 3.81, False)
            + prop('Footprint', '', x, y, True) + prop('Datasheet', '', x, y, True)
            + prop('Description', 'Special symbol for telling ERC where power comes from', x, y, True)
            + f'\t\t(pin "1"\n\t\t\t(uuid "{uuid.uuid4()}")\n\t\t)\n'
            f'\t\t(instances\n\t\t\t(project "{project}"\n\t\t\t\t(path "{sheet_path}"\n\t\t\t\t\t(reference "#FLG0{n}")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n')


# wires: rewrite from the end so offsets stay valid
for u in sorted(replace, key=lambda k: wires[k][0], reverse=True):
    b0, e0, _ = wires[u]
    txt = replace[u]
    s = s[:b0] + ('' if txt == '' else '\n\t' + txt.lstrip('\n\t')) + s[e0:]
# new items go right after lib_symbols
add = ''.join(f'\t(junction\n\t\t(at {x:g} {y:g})\n\t\t(diameter 0)\n\t\t(color 0 0 0 0)\n\t\t(uuid "{uuid.uuid4()}")\n\t)\n' for x, y in sorted(new_junctions))
add += ''.join(f'\t(no_connect\n\t\t(at {x:g} {y:g})\n\t\t(uuid "{uuid.uuid4()}")\n\t)\n' for x, y in new_noconnects)
add += ''.join(flag_instance(i + 1, p) for i, p in enumerate(new_flags))
# global (not local) labels: the board's EAGLE net names have no sheet-path prefix, same as the importer's labels
add += ''.join(f'\t(global_label "{n}"\n\t\t(shape bidirectional)\n\t\t(at {x:g} {y:g} {r})\n\t\t(fields_autoplaced yes)\n'
               f'\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.2446 1.2446)\n\t\t\t)\n\t\t\t(justify left)\n\t\t)\n\t\t(uuid "{uuid.uuid4()}")\n'
               f'\t\t(property "Intersheetrefs" "${{INTERSHEET_REFS}}"\n\t\t\t(at {x:g} {y:g} 0)\n\t\t\t(hide yes)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n'
               f'\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t\t(justify left)\n\t\t\t)\n\t\t)\n\t)\n'
               for n, (x, y), r in new_labels)
lib_end = next(e for b, e, _ in blocks(s, '\n\t(lib_symbols'))
s = s[:lib_end - 1] + PWR_FLAG_LIB + '\t)\n' + add + s[lib_end + 1:]
for u in bom_no:
    i = s.find(f'(uuid "{u}")')
    j = s.rfind('(in_bom yes)', 0, i)
    assert j > 0 and s.rfind('\n\t(symbol\n', 0, i) < j
    s = s[:j] + '(in_bom no)' + s[j + len('(in_bom yes)'):]
    log.append(f'in_bom no on symbol {u} (EAGLE BOM=no)')
open(path, 'w').write(s)
print('\n'.join(log))
print(f'{len(replace)} wires changed, {len(new_junctions)} junctions, {len(new_noconnects)} no-connects, '
      f'{len(new_flags)} PWR_FLAGs, {len(new_labels)} net-name labels, {len(bom_no)} in_bom=no')
