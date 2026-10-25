"""Compare two .kicad_pcb files as geometry, ignoring uuids, item order and net renames.

Usage: python3 pcb_geomdiff.py <old.kicad_pcb> <new.kicad_pcb>

Nets are matched by the set of (reference, pad) they connect, so a net that was only renamed
(N$7 -> Net-(D11-K1)) is the same net. Reports, per category, the items only in one file.
Categories: footprints (placement + every pad's absolute position/size/net + count of graphics),
segments, arcs, vias, zones (net, layers, priority, outline) and board graphics/text.
"""
import re, sys
from collections import Counter


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
        yield t[k0:k + 1]
        i = k + 1


def field(b, name, indent):
    m = re.search(rf'\n{indent}\({name} ([^)\n]*)\)', b)
    return m.group(1) if m else ''


def parse(path):
    t = open(path).read()
    # pre-10 files number nets in a table and reference them as (net 5 "GND") or (net 5); KiCad 10 writes (net "GND")
    nets = {m.group(1): m.group(2) for m in re.finditer(r'\n\t\(net (\d+) "([^"]*)"\)', t)}

    def netname(b, indent):
        m = re.search(rf'\n{indent}\(net (?:(\d+))?\s*(?:"([^"]*)")?\)', b)
        if not m:
            return ''
        return m.group(2) if m.group(2) is not None else nets.get(m.group(1), '')

    fps, pads_by_net = {}, {}
    for b in blocks(t, '\n\t(footprint '):
        ref = re.search(r'\(property "Reference" "([^"]*)"', b).group(1)
        lib = re.search(r'\(footprint "([^"]*)"', b).group(1)
        pads, pad_nets = [], []
        for pb in blocks(b, '\n\t\t(pad '):
            num = re.search(r'\(pad "([^"]*)" (\w+) (\w+)', pb)
            n = netname(pb, '\t\t\t')
            pads.append((num.group(1), num.group(2), num.group(3), field(pb, 'at', '\t\t\t'), field(pb, 'size', '\t\t\t'),
                         field(pb, 'drill', '\t\t\t'), field(pb, 'layers', '\t\t\t')))
            pad_nets.append((num.group(1), n))
            pads_by_net.setdefault(n, set()).add((ref, num.group(1)))
        gfx = Counter(re.findall(r'\n\t\t\((fp_line|fp_arc|fp_circle|fp_rect|fp_poly|fp_text)', b))
        coords = sorted(re.findall(r'\n\t\t\t\((?:start|end|center|mid) ([^)]*)\)', b))
        attrs = field(b, 'attr', '\t\t') + '|' + field(b, 'net_tie_pad_groups', '\t\t')
        # pad nets are kept as the last element so they can be compared through the net mapping
        fps[ref] = (lib, field(b, 'at', '\t\t'), field(b, 'layer', '\t\t'), attrs, tuple(sorted(gfx.items())), tuple(coords),
                    tuple(sorted(pads)), tuple(sorted(pad_nets)))
    segs = Counter((field(b, 'start', '\t\t'), field(b, 'end', '\t\t'), field(b, 'width', '\t\t'), field(b, 'layer', '\t\t'), netname(b, '\t\t'))
                   for b in blocks(t, '\n\t(segment'))
    arcs = Counter((field(b, 'start', '\t\t'), field(b, 'mid', '\t\t'), field(b, 'end', '\t\t'), field(b, 'width', '\t\t'), field(b, 'layer', '\t\t'), netname(b, '\t\t'))
                   for b in blocks(t, '\n\t(arc'))
    vias = Counter((field(b, 'at', '\t\t'), field(b, 'size', '\t\t'), field(b, 'drill', '\t\t'), field(b, 'layers', '\t\t'), netname(b, '\t\t'))
                   for b in blocks(t, '\n\t(via'))
    zones = Counter()
    for b in blocks(t, '\n\t(zone'):
        outline = re.search(r'\n\t\t\(polygon\n\t\t\t\(pts\n((?:.|\n)*?)\n\t\t\t\)', b)
        zones[(netname(b, '\t\t'), field(b, 'layers', '\t\t') or field(b, 'layer', '\t\t'), field(b, 'priority', '\t\t'),
               'keepout' in b, re.sub(r'\s+', ' ', outline.group(1)) if outline else '')] += 1
    gfx = Counter()
    for kind in ('gr_line', 'gr_arc', 'gr_circle', 'gr_rect', 'gr_poly', 'gr_text'):
        for b in blocks(t, f'\n\t({kind}'):
            gfx[(kind, field(b, 'layer', '\t\t'), tuple(re.findall(r'\((?:start|end|center|mid|at|xy) ([^)]*)\)', b)),
                 re.search(r'\(gr_text "([^"]*)"', b).group(1) if kind == 'gr_text' else '')] += 1
    return dict(nets=nets, pads_by_net=pads_by_net, fps=fps, segs=segs, arcs=arcs, vias=vias, zones=zones, gfx=gfx)


old, new = parse(sys.argv[1]), parse(sys.argv[2])
# net mapping old name -> new name through identical pad sets
by_pads_new = {frozenset(v): k for k, v in new['pads_by_net'].items()}
netmap, unmatched = {}, []
for k, v in old['pads_by_net'].items():
    if frozenset(v) in by_pads_new:
        netmap[k] = by_pads_new[frozenset(v)]
    else:
        unmatched.append(k)
renamed = sorted((a, b) for a, b in netmap.items() if a != b)
print(f'nets: {len(old["pads_by_net"])} old, {len(new["pads_by_net"])} new, {len(renamed)} renamed, {len(unmatched)} old nets without an identical new net: {unmatched}')
for a, b in renamed:
    print(f'  {a} -> {b}')
m = lambda n: netmap.get(n, n)


def diff(name, a, b, remap):
    a2 = Counter({remap(k): v for k, v in a.items()})
    only_old, only_new = a2 - b, b - a2
    print(f'{name}: {sum(a.values())} old, {sum(b.values())} new, {sum(only_old.values())} only-old, {sum(only_new.values())} only-new')
    for k in list(only_old)[:8]:
        print('  old:', k)
    for k in list(only_new)[:8]:
        print('  new:', k)


diff('segments', old['segs'], new['segs'], lambda k: k[:-1] + (m(k[-1]),))
diff('arcs', old['arcs'], new['arcs'], lambda k: k[:-1] + (m(k[-1]),))
diff('vias', old['vias'], new['vias'], lambda k: k[:-1] + (m(k[-1]),))
diff('zones', old['zones'], new['zones'], lambda k: (m(k[0]),) + k[1:])
diff('graphics', old['gfx'], new['gfx'], lambda k: k)
fo, fn = old['fps'], new['fps']
print(f'footprints: {len(fo)} old, {len(fn)} new; only-old {sorted(set(fo) - set(fn))}, only-new {sorted(set(fn) - set(fo))}')
for ref in sorted(set(fo) & set(fn)):
    a, b = fo[ref], fn[ref]
    a = a[:7] + (tuple((p, m(n)) for p, n in a[7]),)
    if a != b:
        labels = ('lib', 'at', 'layer', 'attrs', 'graphics', 'coords', 'pads', 'pad nets')
        print(f'  {ref} differs in', [labels[i] for i in range(8) if a[i] != b[i]])
        for i in range(8):
            if a[i] != b[i] and i in (0, 1, 2, 3):
                print(f'     {labels[i]}: {a[i]!r} -> {b[i]!r}')
