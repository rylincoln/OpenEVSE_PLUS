"""ngspice simulation of the v6.5.1 J1772 pilot generator (IC1 open-loop, R1 820R) for each EV state.

Usage: python3 pilot_sim.py <models_dir> <work_dir> [rail_volts ...]
models_dir holds TI's unzipped SPICE models: SLOJ039 (LF353), SLOJ070 (TL082), SNOM268 (LM358), SLOM472 (LM358B)
from https://www.ti.com/lit/zip/<id>. work_dir gets the netlists and a .spiceinit selecting PSpice compatibility.
"""
import os, re, subprocess, sys

M, W = sys.argv[1], sys.argv[2]
RAILS = [float(v) for v in sys.argv[3:]] or [12.0]
AMPS = {
    'LF353': ('SLOJ039/LF353.301', 'LF353'),
    'TL082': ('SLOJ070/TL082.301', 'TL082'),
    'LM358': ('SNOM268/lmx58_lm2904.lib', 'LMX58_LM2904'),
    'LM358B': ('SLOM472/LMx58B_LM2904B_PSpice/lmx58b_lm2904b.lib', 'LMX58B_LM2904B'),
    'IDEAL_1k': (None, None),  # J1772 reference generator: +/-rail behind 1 kohm
}
STATES = {'A': None, 'B': 2740, 'C': 882, 'D': 246}  # EV load behind its diode; C = 2.74k || 1.3k
BAND = {'A': (11.4, 12.6), 'B': (8, 10), 'C': (5, 7), 'D': (2, 4)}

def netlist(amp, state, rail):
    lib, sub = AMPS[amp]
    load = '' if STATES[state] is None else f'DEV pilot ev D1N4148\nREV ev 0 {STATES[state]}\n'
    if lib:
        # -12V comes from the TC1044S charge pump: ~70 ohm output resistance, derated 10uF 0805 reservoir
        drv = f'''.include {os.path.join(M, lib)}
VPOS vcc 0 {rail}
VNEGS vneg_s 0 -{rail}
RNEG vneg_s vee 70
CNEG vee 0 2u
VBIAS inn 0 2.5
X1 pwm inn vcc vee out {sub}
R1 out pilot 820'''
    else:
        drv = f'BIDEAL out 0 V = v(pwm) > 2.5 ? {rail} : -{rail}\nR1 out pilot 1000'
    return f'''* pilot {amp} state {state} rail {rail}
{drv}
VPWM pwm 0 PULSE(0 5 0 10n 10n 0.5m 1m)
R7 pilot pread 200k
R6 pread 0 100k
R5 pread v5 56k
V5 v5 0 5
{load}.model D1N4148 D(IS=2.52n RS=0.568 N=1.752 CJO=4p M=0.4 TT=20n BV=100)
.tran 0.2u 3m
.control
run
meas tran vhi avg v(pilot) from=2.30m to=2.48m
meas tran vlo avg v(pilot) from=2.80m to=2.98m
meas tran ohi avg v(out) from=2.30m to=2.48m
meas tran olo avg v(out) from=2.80m to=2.98m
let l10 = olo + 0.1*(ohi-olo)
let l90 = olo + 0.9*(ohi-olo)
meas tran trise trig v(out) val=$&l10 rise=3 targ v(out) val=$&l90 rise=3
meas tran tfall trig v(out) val=$&l90 fall=3 targ v(out) val=$&l10 fall=3
quit
.endc
.end
'''

os.makedirs(W, exist_ok=True)
open(os.path.join(W, '.spiceinit'), 'w').write('set ngbehavior=psa\n')
for rail in RAILS:
    print(f'\nrails +/-{rail} V   (* = outside band; A band is +/-0.6 V, unverified)')
    print(f"{'driver':9} | {'A +V':>7} {'A -V':>7} | {'B +V':>7} | {'C +V':>7} | {'D +V':>7} | rise us | fall us")
    for amp in AMPS:
        r = {}
        for st in STATES:
            path = os.path.join(W, f'{amp}_{st}_{rail}.cir')
            open(path, 'w').write(netlist(amp, st, rail))
            out = subprocess.run(['ngspice', '-b', path], capture_output=True, text=True, cwd=W, timeout=300).stdout
            r[st] = {k: float(v) for k, v in re.findall(r'^(vhi|vlo|trise|tfall)\s*=\s*([-+0-9.eE]+)', out, re.M)}
        f = lambda st: f"{r[st]['vhi']:6.2f}{' ' if BAND[st][0] <= r[st]['vhi'] <= BAND[st][1] else '*'}"
        rise, fall = (r['B'].get(k, 0) * 1e6 for k in ('trise', 'tfall'))
        print(f"{amp:9} | {f('A')} {r['A']['vlo']:7.2f} | {f('B')} | {f('C')} | {f('D')} | {rise:7.2f} | {fall:7.2f}")
