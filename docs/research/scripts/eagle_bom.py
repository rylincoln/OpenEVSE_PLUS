"""Grouped BOM from an EAGLE .sch: python3 eagle_bom.py <file.sch> > bom.csv

`value` is the intended part; `eagle_device` and `attributes` are often library placeholders.
"""
import re, sys, xml.etree.ElementTree as ET, collections, csv
sch = ET.parse(sys.argv[1]).getroot().find('drawing/schematic')
libs = {(l.get('name'), l.get('urn')): l for l in sch.iterfind('libraries/library')}
def devinfo(p):
    lib = libs[(p.get('library'), p.get('library_urn'))]
    ds = lib.find(f"devicesets/deviceset[@name='{p.get('deviceset')}']")
    dev = ds.find(f"devices/device[@name='{p.get('device')}']")
    pkg = dev.get('package') if dev is not None else None
    attrs = {}
    if dev is not None:
        for t in dev.iterfind('technologies/technology'):
            if t.get('name') == (p.get('technology') or ''):
                attrs = {a.get('name'): a.get('value') for a in t.iter('attribute')}
    attrs.update({a.get('name'): a.get('value') for a in p.iter('attribute')})
    pk = lib.find(f"packages/package[@name='{pkg}']") if pkg else None
    return pkg, attrs, (len(pk.findall('smd')) if pk is not None else 0), (len(pk.findall('pad')) if pk is not None else 0)
rows = collections.OrderedDict()
for p in sch.iterfind('parts/part'):
    pkg, attrs, smd, tht = devinfo(p)
    if pkg is None: continue
    key = (p.get('value') or p.get('deviceset'), pkg)
    r = rows.setdefault(key, {'refs': [], 'attrs': attrs, 'smd': smd, 'tht': tht, 'lib': f"{p.get('library')}/{p.get('deviceset')}{p.get('device')}"})
    r['refs'].append(p.get('name'))
nat = lambda x: (re.sub(r'\d', '', x), int(re.sub(r'\D', '', x) or 0))
w = csv.writer(sys.stdout)
w.writerow(['qty', 'value', 'package', 'mount', 'eagle_device', 'refs', 'attributes'])
for (val, pkg), r in sorted(rows.items(), key=lambda kv: nat(sorted(kv[1]['refs'], key=nat)[0])):
    mount = 'THT' if r['tht'] and not r['smd'] else 'SMD' if r['smd'] and not r['tht'] else 'MIX' if r['smd'] else 'none'
    a = '; '.join(f'{k}={v}' for k, v in r['attrs'].items() if v)
    w.writerow([len(r['refs']), val, pkg, mount, r['lib'], ' '.join(sorted(r['refs'], key=nat)), a])
