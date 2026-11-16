"""Route aufbereiten: km und Zeitprofil je Punkt, Wegpunkte mit allen Durchfahrten, vereinfachte Linie für Overpass.
Quelle: "komoot" (Teilen-Link, Netz api.komoot.de) oder "gpx" (Datei, enthält auch die Wegpunkte des Veranstalters).
Zeitprofil: Komoot-Planzeiten (bilden Steigung und Untergrund ab), sonst ein einfaches Modell
(20 km/h plus 1 Stunde je 600 Hm). Beides wird je Tag auf Start und Ankunft gestreckt.

Aufruf: python3.12 -P route.py <roadbook.json>
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True  # kein __pycache__ im Skill-Ordner
from model import Route, gpx_lesen, hole, komoot_link, komoot_punkte, lade_config, pfad  # noqa: E402

WP_RADIUS = 500  # m: so nah an der Strecke zählt jede Durchfahrt an einem Wegpunkt

cfg = lade_config(sys.argv[1])
wpts_roh = []  # Wegpunkte (lat, lon, Name), pts je Punkt [lat, lon, Höhe, Stunden ab Start oder None]
if cfg.get('komoot'):  # Teilen-Link einer Komoot-Tour: Punkte mit Planzeiten, aber ohne Wegpunkte
    tour, token = komoot_link(cfg['komoot'])
    if not token:
        print('Hinweis: Link ohne share_token, der Abruf klappt dann nur bei öffentlichen Touren')
    roh = hole(f'https://api.komoot.de/v007/tours/{tour}?share_token={token}&_embedded=coordinates', ua='Mozilla/5.0', pause=3)
    if roh is None:
        sys.exit('Komoot-Tour nicht abrufbar, Teilen-Link prüfen oder GPX exportieren')
    pts = komoot_punkte(roh)
elif cfg.get('gpx'):
    pts, wpts_roh = gpx_lesen(cfg['gpx'])
else:
    sys.exit('roadbook.json braucht "gpx" (Pfad zur Datei) oder "komoot" (Teilen-Link)')


def hav(a, b):
    r = 6371008.8
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    d = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(d))


cum = [0.0]
for i in range(1, len(pts)):
    cum.append(cum[-1] + hav(pts[i - 1], pts[i]))
if cum[-1] < 1000:
    sys.exit(f'Strecke nur {cum[-1]:.0f} m lang, GPX oder Komoot-Link prüfen')

# Höhen glätten (GPS-Rauschen bläht die Höhenmeter auf)
ele = [p[2] for p in pts]
glatt = [sum(ele[max(0, i - 4):i + 5]) / len(ele[max(0, i - 4):i + 5]) for i in range(len(ele))]
hm = sum(max(0.0, glatt[i] - glatt[i - 1]) for i in range(1, len(glatt)))

zeiten = all(p[3] is not None for p in pts) and pts[-1][3] > pts[0][3]
if zeiten:
    kt = [p[3] - pts[0][3] for p in pts]
    quelle = 'Planzeiten aus Komoot' if cfg.get('komoot') else 'Planzeiten aus der GPX'
else:
    kt = [0.0]
    for i in range(1, len(pts)):
        kt.append(kt[-1] + (cum[i] - cum[i - 1]) / 1000 / 20 + max(0.0, glatt[i] - glatt[i - 1]) / 600)
    quelle = 'Modell 20 km/h plus 1 h je 600 Hm (GPX ohne Zeiten)'

# Douglas-Peucker in lokalen Metern, Toleranz 20 m
lat0 = sum(p[0] for p in pts) / len(pts)
kx, ky = math.cos(math.radians(lat0)) * 111320.0, 110574.0
xy = [(p[1] * kx, p[0] * ky) for p in pts]


def seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == 0 and dy == 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


keep = [False] * len(pts)
keep[0] = keep[-1] = True
stack = [(0, len(pts) - 1)]
while stack:
    s, e = stack.pop()
    best, bi = 0.0, None
    for i in range(s + 1, e):
        d = seg_dist(xy[i], xy[s], xy[e])
        if d > best:
            best, bi = d, i
    if bi is not None and best > 20.0:
        keep[bi] = True
        stack += [(s, bi), (bi, e)]

daten = {
    'pts': [[round(p[0], 6), round(p[1], 6), round(p[2], 1), round(cum[i] / 1000, 4), round(kt[i], 5)]
            for i, p in enumerate(pts)],
    'simple': [[round(pts[i][0], 6), round(pts[i][1], 6)] for i in range(len(pts)) if keep[i]],
    'wpts': [],
}


def speichern():
    """data/route.json schreiben: erst ohne Wegpunkte, denn Route liest die Datei, mit Wegpunkten dann erneut."""
    with open(pfad(cfg, 'data', 'route.json'), 'w') as f:
        json.dump(daten, f)


speichern()

route = Route(cfg)
for la, lo, name in wpts_roh:  # Rundkurs oder hin und zurück: jede Durchfahrt, nicht nur der global nächste Punkt
    ps = route.passes(la, lo, WP_RADIUS)
    if ps:
        kms, abstand = [round(k, 2) for k, _ in ps], min(d for _, d in ps)
    else:
        km, abstand = route.naechster(la, lo)
        kms = [round(km, 2)]
    daten['wpts'].append({'name': name, 'lat': la, 'lon': lo, 'km': kms[0], 'kms': kms, 'abstand_m': round(abstand)})
if daten['wpts']:
    speichern()
wpts = daten['wpts']

print(f'Route {route.total:.1f} km, ca. {hm:.0f} Hm, {len(pts)} Punkte, {sum(keep)} für Overpass, {len(wpts)} Wegpunkte')
print(f'Zeitprofil: {quelle}')
print(f'Roadbook von km {route.km_von:.0f} bis {route.km_bis:.0f}')
for t in route.tage:
    schnitt = (t['km1'] - t['km0']) / ((t['t1'] - t['t0']).total_seconds() / 3600)
    print(f"{t['tag']:<10} km {t['km0']:6.1f} bis {t['km1']:6.1f}  {t['t0']:%d.%m. %H:%M} bis {t['t1']:%d.%m. %H:%M} Uhr"
          f"  Schnitt inkl. Pausen {schnitt:.1f} km/h  {t['ziel']}")
for h in route.hinweise:
    print('HINWEIS:', h)
for km in range(0, int(route.total) + 1, 50):
    print(f'  km {km:4d}  {route.zeit(km)}')
for w in wpts:
    if len(w['kms']) > 1:
        print(f"  Wegpunkt {w['name']}: {len(w['kms'])} Durchfahrten, "
              + ', '.join(f'km {k:.1f} ({route.zeit(k)})' for k in w['kms']))
    else:
        abseits = f", {w['abstand_m']} m neben der Strecke" if w['abstand_m'] > WP_RADIUS else ''
        print(f"  Wegpunkt km {w['km']:6.1f}  {route.zeit(w['km'])}  {w['name']}{abseits}")
