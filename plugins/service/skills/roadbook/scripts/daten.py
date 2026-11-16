"""Daten laden: OnRouteMap-Export (wenn ein Link in der Konfiguration steht) und Overpass (OpenStreetMap) für
Verpflegung im Korridor, Läden bis 1 km für Lücken, Radläden und Ortsnamen im Rahmen der Route.
Overpass ist abends oft überlastet (504, abgebrochene Antworten): Wiederholungen mit Pause, Ortsnamen in Kacheln.

Aufruf: python3.12 -P daten.py <roadbook.json> [orm food gapshops bike places]
Netz: overpass-api.de, onroutemap.de
"""
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True  # kein __pycache__ im Skill-Ordner
from model import hole, lade_config, lies_json, pfad  # noqa: E402

cfg = lade_config(sys.argv[1])
nur = set(sys.argv[2:])
route = lies_json(pfad(cfg, 'data', 'route.json'), 'erst route.py laufen lassen')
URL = 'https://overpass-api.de/api/interpreter'
coords = ','.join(f'{la},{lo}' for la, lo in route['simple'])
lats = [p[0] for p in route['pts']]
lons = [p[1] for p in route['pts']]
S, W, N, E = min(lats) - 0.04, min(lons) - 0.06, max(lats) + 0.04, max(lons) + 0.06
r_food, r_gap = int(cfg['radius_m']) + 20, int(cfg['radius_luecke_m']) + 100


def overpass(ql, versuche=4, timeout=360):
    roh = hole(URL, urllib.parse.urlencode({'data': ql}).encode(), versuche=versuche, pause=20, timeout=timeout)
    try:
        return json.loads(roh) if roh else None
    except ValueError:
        return None


def speichern(name, data):
    with open(pfad(cfg, 'data', 'overpass', f'{name}.json'), 'w') as f:
        json.dump(data, f)
    print(name, 'Elemente', len(data.get('elements', [])))
    if data.get('remark'):  # Overpass meldet Abbrüche (Zeitlimit, Speicher) im Text, die Antwort ist dann unvollständig
        print(f"WARNUNG {name}: Overpass meldet {data['remark'][:120]}. Mit daten.py <roadbook.json> {name} wiederholen")


def soll(name):
    return not nur or name in nur


if soll('orm') and cfg.get('onroutemap'):
    m = re.search(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', cfg['onroutemap'])
    if m:
        roh = hole(f'https://onroutemap.de/api/map/{m.group(1)}/export/mapdata?format=embed', ua='Mozilla/5.0', pause=3)
        try:  # kein UTF-8 oder kaputtes JSON (beides ValueError): wie eine Seite ohne poi_data, kein Traceback
            seite = roh.decode('utf-8') if roh else ''
            treffer = re.search(r'window\.poi_data\s*=\s*(\[.*?\]);\s*(?:window\.|$)', seite, re.S)
            pois = json.loads(treffer.group(1)) if treffer else None
        except ValueError:
            pois = None
        if pois is not None:
            with open(pfad(cfg, 'data', 'orm', 'pois.json'), 'w', encoding='utf-8') as f:
                json.dump(pois, f, ensure_ascii=False)
            print('OnRouteMap POIs', len(pois))
        else:
            print('OnRouteMap nicht lesbar, weiter nur mit Overpass')

anfragen = {
    'food': f'''[out:json][timeout:300];
(
  nwr["shop"~"^(supermarket|convenience|kiosk|bakery|pastry|beverages)$"](around:{r_food},{coords});
  nwr["amenity"~"^(fuel|fast_food)$"](around:{r_food},{coords});
  nwr["amenity"="vending_machine"](around:{r_food},{coords});
);
out center tags;''',
    'gapshops': f'''[out:json][timeout:300];
(
  nwr["shop"~"^(supermarket|convenience|kiosk|bakery|pastry|beverages)$"](around:{r_gap},{coords});
  nwr["amenity"="fuel"](around:{r_gap},{coords});
);
out center tags;''',
    'bike': f'[out:json][timeout:180];nwr["shop"="bicycle"]({S:.4f},{W:.4f},{N:.4f},{E:.4f});out center tags;',
}
for name, ql in anfragen.items():
    if soll(name):
        data = overpass(ql)
        if data:
            speichern(name, data)
        else:
            print(name, 'FEHLGESCHLAGEN, später mit gleichem Aufruf und Namen wiederholen')
        time.sleep(5)

if soll('places'):  # Ortsnamen in 3 x 3 Kacheln, "out;" liefert die Koordinaten mit
    els, fehlt = {}, 0
    for i in range(3):
        for j in range(3):
            bb = f'{S + (N - S) * i / 3:.4f},{W + (E - W) * j / 3:.4f},{S + (N - S) * (i + 1) / 3:.4f},{W + (E - W) * (j + 1) / 3:.4f}'
            d = overpass(f'[out:json][timeout:90];node["place"~"^(city|town|village|suburb|quarter|hamlet|neighbourhood)$"]({bb});out;',
                         versuche=4, timeout=120)
            if d:
                els.update({x['id']: x for x in d['elements']})
            else:
                fehlt += 1
            time.sleep(3)
    speichern('places', {'elements': list(els.values())})
    if fehlt:
        print(f'places: {fehlt} von 9 Kacheln fehlen, Namen kommen dann aus Nominatim (namen.py)')
