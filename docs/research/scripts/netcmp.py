"""Compare pad-level connectivity between two netlists and print the nets that differ.

Usage: python3 netcmp.py <kind> <file> <kind> <file>
  kind: eagle_brd (EAGLE .brd), kicad_pcb (.kicad_pcb), kicad_net (kicad-cli sch export netlist --format kicadsexpr)
Net names are ignored; nets are compared as sets of (refdes, pad). KiCad refs that the EAGLE import
suffixed with 0 (AC0, FTDI0, ...) are mapped back via REN.
"""
import re, sys, xml.etree.ElementTree as ET, collections
def blocks(s, head):
    i = 0
    while True:
        j = s.find(head, i)
        if j < 0: return
        d = 0; k = j
        while True:
            c = s[k]
            if c == '(': d += 1
            elif c == ')':
                d -= 1
                if d == 0: break
            k += 1
        yield s[j:k+1]; i = k+1
REN = {'AC0':'AC','AMP_CT0':'AMP_CT','FTDI0':'FTDI','I2C0':'I2C','PILOT0':'PILOT','TVS0':'TVS','GFCI_CT0':'GFCI_CT','DC_RELAY0':'DC_RELAY'}
def eagle_brd(path):
    b = ET.parse(path).getroot().find('drawing/board'); nets = {}
    for s in b.iterfind('signals/signal'):
        nets[s.get('name')] = {(c.get('element'), c.get('pad')) for c in s.iterfind('contactref')}
    return nets
def kicad_pcb(path):
    t = open(path).read(); nets = collections.defaultdict(set)
    for fp in blocks(t, '\n\t(footprint '):
        ref = REN.get(re.search(r'\(property "Reference" "([^"]*)"', fp).group(1), None) or re.search(r'\(property "Reference" "([^"]*)"', fp).group(1)
        for pd in blocks(fp, '(pad '):
            n = re.search(r'\(net (?:\d+ )?"([^"]*)"\)', pd)
            if n and n.group(1) and not n.group(1).startswith('unconnected'): nets[n.group(1).lstrip('/')].add((ref, re.search(r'\(pad "([^"]*)"', pd).group(1)))
    return nets
def kicad_net(path):
    t = open(path).read(); nets = {}
    nl = t[t.find('(nets'):]
    for nb in blocks(nl, '(net\n'):
        name = re.search(r'\(name "([^"]*)"\)', nb).group(1)
        nodes = {(REN.get(r, r), p) for r, p in re.findall(r'\(ref "([^"]*)"\)\s*\(pin "([^"]*)"\)', nb)}
        if not name.startswith('unconnected'): nets[name.lstrip('/')] = nodes
    return nets
def partition(nets):
    m = {}
    for n, pads in nets.items():
        if len(pads) < 2: continue
        fs = frozenset(pads)
        for p in pads: m[p] = (n, fs)
    return m
LOAD = {'eagle_brd': eagle_brd, 'kicad_pcb': kicad_pcb, 'kicad_net': kicad_net}
A = partition(LOAD[sys.argv[1]](sys.argv[2])); B = partition(LOAD[sys.argv[3]](sys.argv[4]))
skip = re.compile(r'^(GND\d+|P\+\d+|SUPPLY\d+|U\$\d+|@HOLE\d|FID\d|SH\d)$')
seen = set(); out = []
for p in sorted(set(A) | set(B)):
    if skip.match(p[0]): continue
    a = A.get(p); b = B.get(p)
    sa = {q for q in (a[1] if a else {p}) if not skip.match(q[0])}; sb = {q for q in (b[1] if b else {p}) if not skip.match(q[0])}
    if sa != sb:
        key = (a[0] if a else None, b[0] if b else None)
        if key in seen: continue
        seen.add(key)
        out.append(f"{p[0]}.{p[1]}: {sys.argv[1]} net {a[0] if a else '(single)'} has extra {sorted(sa - sb)[:6]} | {sys.argv[3]} net {b[0] if b else '(single)'} has extra {sorted(sb - sa)[:6]}")
print(len(out), 'differing nets'); print('\n'.join(out))
