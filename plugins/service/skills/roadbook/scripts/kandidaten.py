"""Kandidaten: POIs auf die Route projizieren, Öffnungszeiten zur Planzeit prüfen, zu Orten bündeln, bewerten.
Schreibt data/kandidaten.json und gibt eine Übersicht aus: Orte, Lücken, Stundenraster, Radläden, Umweg-Optionen.
An einer Übernachtung (GRENZE_KM vor und hinter dem Zielpunkt eines Tages) zählt jeder Laden zweimal: zur Ankunft
am Abend und zur Abfahrt am Morgen.

Aufruf: python3.12 -P kandidaten.py <roadbook.json>
"""
import json
import re
import sys
from collections import Counter
from datetime import datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True  # kein __pycache__ im Skill-Ordner
from model import (Route, fmt_day, lade_config, lies_json, orm_weekly, ortsname, parse_oh, pfad,  # noqa: E402
                   status)

cfg = lade_config(sys.argv[1])
route = Route(cfg)
warnungen = []


def lade(name, wozu, pflicht=False):
    """Overpass-Daten aus data/overpass. Fehlt eine Datei, ist sie leer oder meldet Overpass einen Abbruch, steht es
    als WARNUNG oben in der Ausgabe. Ohne Pflichtdatei bricht das Skript ab."""
    p = pfad(cfg, 'data', 'overpass', f'{name}.json')
    nachladen = f'daten.py <roadbook.json> {name}'
    if not p.exists():
        if pflicht:
            sys.exit(f'{p} fehlt, ohne sie gibt es keine Kandidaten: erst {nachladen} laufen lassen')
        warnungen.append(f'{p.name} fehlt, ohne {wozu}. Nachladen mit {nachladen}')
        return []
    daten = lies_json(p, f'neu laden mit {nachladen}')
    if daten.get('remark'):
        warnungen.append(f"{p.name} ist unvollständig, Overpass meldet: {daten['remark'][:100]}. Nachladen mit {nachladen}")
    elif not daten.get('elements'):
        warnungen.append(f'{p.name} ist leer, ohne {wozu}. Prüfen oder nachladen mit {nachladen}')
    return daten.get('elements') or []


food = lade('food', 'Verpflegung im Korridor', pflicht=True)
gaps = lade('gapshops', 'Umweg-Optionen bis 1 km')
bikes = lade('bike', 'Radläden')
places = lade('places', 'Ortsnamen aus OSM')
orm_p = pfad(cfg, 'data', 'orm', 'pois.json')
orm = lies_json(orm_p, 'neu laden mit daten.py <roadbook.json> orm') if orm_p.exists() else []
if cfg.get('onroutemap') and not orm_p.exists():
    warnungen.append('data/orm/pois.json fehlt, ohne Zeiten aus OnRouteMap. Nachladen mit daten.py <roadbook.json> orm')
namen_p = pfad(cfg, 'data', 'names.json')
namen = lies_json(namen_p, 'löschen und namen.py neu laufen lassen') if namen_p.exists() else {}
R, R_GAP, R_RAD = float(cfg['radius_m']), float(cfg['radius_luecke_m']), float(cfg['radius_rad_m'])
IMBISS_AB = time.fromisoformat(cfg['imbiss_ab'])
LUECKE_KM = 20

VEND_OK = re.compile(r'food|drink|sweet|milk|egg|bread|meat|sausage|snack|potato|honey|cheese|ice_cream|coffee|water|pizza|noodle|fruit|vegetable|baked|cake|soup|farm|regional|beverage|juice', re.I)
VEND_BAD = re.compile(r'cigarette|tobacco|parking|ticket|condom|stamp|telephone|photo|toy|excrement|sim_card|bottle_return|admission|chewing_gum|fuel|charging|newspaper|money|cash|key|bicycle|tube|pet_food|feed|bait|fishing', re.I)
VEND_NAME = re.compile(r'regio|milch|eier|hof|snack|getränk|brot|bäck|wurst|fleisch|kartoffel|honig|käse|verpflegung|lebensmittel', re.I)
FUEL_SB = re.compile(r'\bSB\b|automat|raiffeisen|baywa|agrar|landhandel|genossenschaft|\bZG\b|tankpool', re.I)
NICHT_OEFFENTLICH = re.compile(r'exchange|commissary|aafes|shoppette|kaserne|barracks', re.I)  # US-Militärläden


def coord(e):
    if 'lat' in e:
        return e['lat'], e['lon']
    c = e.get('center')
    return (c['lat'], c['lon']) if c else (None, None)


def kategorie(t):
    shop, am = t.get('shop'), t.get('amenity')
    if shop == 'supermarket':
        return 'super'
    if shop in ('convenience', 'kiosk', 'beverages'):
        return 'laden'
    if shop in ('bakery', 'pastry'):
        return 'baecker'
    if am == 'fuel':
        nm = ' '.join([t.get('name', ''), t.get('brand', ''), t.get('operator', '')])
        return 'tanke_sb' if t.get('automated') == 'yes' or t.get('shop') == 'no' or FUEL_SB.search(nm) else 'tanke'
    if am == 'fast_food':
        return 'imbiss'
    if am == 'vending_machine':
        v, nm = t.get('vending', ''), t.get('name', '')
        if VEND_BAD.search(v) and not VEND_OK.search(v):
            return None
        return 'automat' if VEND_OK.search(v) or VEND_NAME.search(nm) else None
    if shop == 'bicycle':
        return 'rad'
    return None


def ausgeschlossen(t):
    if t.get('access') in ('private', 'no'):
        return True
    if NICHT_OEFFENTLICH.search(' '.join([t.get('name', ''), t.get('operator', '')])):
        return True
    return (t.get('opening_hours') or '').strip().lower() in ('closed', 'off')


def orm_treffer(lat, lon):
    best = None
    for p in orm:
        d = route.abstand(lat, lon, p['lat'], p['lon'])
        if d < 35 and (best is None or d < best[0]):
            best = (d, p)
    return best[1] if best else None


def eintrag(e, t, cat, km, dist, tag):
    lat, lon = coord(e)
    eta = route.eta(km, tag)
    week = parse_oh(t.get('opening_hours'), datum=eta.date())
    if week is None:
        m = orm_treffer(lat, lon)
        week = orm_weekly(m.get('opening_hours_parsed')) if m else None
    st, left, nxt = status(week, eta, route.puffer)
    return {'osm': f"{e['type']}/{e['id']}", 'cat': cat, 'name': t.get('name') or t.get('brand') or '',
            'street': t.get('addr:street', ''), 'hn': t.get('addr:housenumber', ''), 'city': t.get('addr:city', ''),
            'lat': round(lat, 6), 'lon': round(lon, 6), 'km': round(km, 2), 'dist': round(dist), 'tag': tag,
            'eta': eta.isoformat(timespec='minutes'), 'status': st, 'left': left, 'day': fmt_day(week, eta),
            'oh': t.get('opening_hours', ''), 'vending': t.get('vending', ''), 'umweg': dist > R}


def eintraege(e, t, cat, ps):
    """Ein Eintrag je Durchfahrt im Roadbook-Bereich, an einer Übernachtung je Tag einer (Abend und Morgen)."""
    return [eintrag(e, t, cat, km, d, tag) for km, d in ps if route.km_von <= km <= route.km_bis
            for tag in route.tage_bei(km)]


pois, seen = [], set()
for elems, radius in ((food, R), (gaps, R_GAP)):
    for e in elems:
        key = (e['type'], e['id'])
        t = e.get('tags', {})
        cat = kategorie(t)
        lat, lon = coord(e)
        if key in seen or not cat or cat == 'rad' or ausgeschlossen(t) or lat is None:
            continue
        ps = route.passes(lat, lon, radius)
        if ps:
            seen.add(key)
            pois += eintraege(e, t, cat, ps)

rad = []
for e in bikes:
    t = e.get('tags', {})
    lat, lon = coord(e)
    if lat is None or ausgeschlossen(t):
        continue
    rad += eintraege(e, t, 'rad', route.passes(lat, lon, R_RAD))

W = {'city': 1.0, 'town': 1.0, 'village': 1.0, 'suburb': 1.0, 'quarter': 1.3, 'neighbourhood': 1.6, 'hamlet': 1.6}
pl = [(e['lat'], e['lon'], e['tags'].get('place'), e['tags']['name']) for e in places
      if e.get('tags', {}).get('name') and 'lat' in e]


def name_fuer(lat, lon, staedte):
    a = namen.get(f'{lat:.5f},{lon:.5f}')
    if a:
        return ortsname(a)
    best = min(((route.abstand(lat, lon, la, lo) * W.get(typ, 2.0), nm) for la, lo, typ, nm in pl), default=None)
    if best and best[0] < 2500:
        return best[1]
    return max(set(staedte), key=staedte.count) if staedte else '?'


GEWICHT = {'super': 5, 'tanke': 4, 'baecker': 3, 'laden': 2, 'imbiss': 3, 'automat': 1}
KUERZEL = {'super': 'S', 'laden': 'L', 'baecker': 'B', 'tanke': 'T', 'imbiss': 'I', 'automat': 'A'}
STW = {'ok': 1.0, '?': 0.5, 'knapp': 0.4}


def gewicht(cat, eta):
    if cat == 'imbiss':
        return 3 if eta.time() >= IMBISS_AB else 0
    if cat == 'automat' and eta.hour < 7:
        return 4  # nachts oft die einzige Option
    if cat == 'baecker' and eta.hour < 14:
        return 3.5
    return GEWICHT.get(cat, 0)


kand = sorted([p for p in pois if not p['umweg'] and p['status'] != 'zu' and p['cat'] != 'tanke_sb'],
              key=lambda p: (p['tag'], p['km']))
orte = []
for p in kand:
    if orte and orte[-1]['tag'] == p['tag'] and p['km'] - orte[-1]['members'][-1]['km'] <= 1.5:
        orte[-1]['members'].append(p)
    else:
        orte.append({'tag': p['tag'], 'members': [p]})
for o in orte:
    ms = o['members']
    kms = sorted(m['km'] for m in ms)
    o['km'] = round(kms[len(kms) // 2], 1)
    o['eta'] = route.eta(o['km'], o['tag']).isoformat(timespec='minutes')
    o['lat'] = sorted(m['lat'] for m in ms)[len(ms) // 2]
    o['lon'] = sorted(m['lon'] for m in ms)[len(ms) // 2]
    o['ort'] = name_fuer(o['lat'], o['lon'], [m['city'] for m in ms if m['city']])
    best = {}
    for m in ms:
        best[m['cat']] = max(best.get(m['cat'], 0), gewicht(m['cat'], datetime.fromisoformat(m['eta'])) * STW[m['status']])
    # km der Optionen, die zur Planzeit sicher offen sind und zählen: nur sie brechen eine Lücke
    o['sicher'] = [m['km'] for m in ms if m['status'] == 'ok' and gewicht(m['cat'], datetime.fromisoformat(m['eta'])) > 0]
    o['score'] = round(sum(best.values()) + min(len(o['sicher']), 6) * 0.3, 1)
    zaehler = Counter(KUERZEL[m['cat']] + {'ok': '', '?': '?'}.get(m['status'], '~') for m in ms)
    o['kurz'] = ' '.join(f'{k}{v}' for k, v in sorted(zaehler.items()))


def luecken():
    """Abschnitte über LUECKE_KM ohne sicher offene Option, je Tag in Fahrtrichtung: vom Anfang des Roadbooks oder
    der Abfahrt an der Übernachtung bis zur ersten Option und von der letzten bis zur Ankunft oder zum Ende. Läden an
    der Übernachtung zählen am Abend und am Morgen dort, wo der Tag endet oder beginnt. Orte nur mit unklaren oder
    knappen Optionen brechen keine Lücke, sie stehen dabei."""
    out = []
    for i, t in enumerate(route.tage):
        von, bis = max(t['km0'], route.km_von), min(t['km1'], route.km_bis)
        if bis <= von:
            continue
        anfang = f"{route.tage[i - 1]['ziel'] or 'Übernachtung'} (Abfahrt)" if i else 'Anfang des Roadbooks'
        ende = 'Ende des Roadbooks' if i == len(route.tage) - 1 else f"{t['ziel'] or 'Übernachtung'} (Ankunft)"
        punkte = sorted((min(max(km, von), bis), o['ort']) for o in orte if o['tag'] == i for km in o['sicher'])
        punkte = [(von, anfang)] + punkte + [(bis, ende)]
        for (a, na), (b, nb) in zip(punkte, punkte[1:]):
            if b - a > LUECKE_KM:
                unklar = list(dict.fromkeys(o['ort'] for o in orte if o['tag'] == i and not o['sicher'] and a < o['km'] < b))
                out.append({'tag': i, 'von': round(a, 1), 'bis': round(b, 1), 'von_ort': na, 'bis_ort': nb,
                            'zeit_von': route.zeit(a, i), 'zeit_bis': route.zeit(b, i), 'unklar': unklar})
    return out


lueckenliste = luecken()
with open(pfad(cfg, 'data', 'kandidaten.json'), 'w', encoding='utf-8') as f:
    json.dump({'pois': pois, 'rad': rad, 'orte': orte, 'luecken': lueckenliste}, f, ensure_ascii=False)

for w in warnungen:
    print('WARNUNG:', w)
print(f'POIs {len(pois)}, Radläden-Durchfahrten {len(rad)}, Orte {len(orte)}. Legende: S Supermarkt, L Laden, B Bäcker, '
      f'T Tanke, I Imbiss, A Automat, ? ohne Zeiten, ~ knapp (schließt vor Ablauf des Puffers)')
print('\n## Orte (km, Planzeit, Punkte, Name, Optionen)')
for o in orte:
    print(f"{o['km']:6.1f} {route.zeit(o['km'], o['tag']):9} {o['score']:5.1f}  {o['ort'][:28]:28} {o['kurz']}  {o['lat']},{o['lon']}")

print(f'\n## Lücken über {LUECKE_KM} km ohne sicher offene Option (unklare und knappe zählen nicht)')
for lu in lueckenliste:
    zusatz = f", dazwischen nur unklar oder knapp: {', '.join(lu['unklar'][:5])}" if lu['unklar'] else ''
    print(f"km {lu['von']:.0f} bis {lu['bis']:.0f} ({lu['zeit_von']} bis {lu['zeit_bis']}): "
          f"{lu['von_ort']} bis {lu['bis_ort']}{zusatz}")

print('\n## Stundenraster (je Stunde die drei stärksten Orte)')
slots = {}
for o in orte:
    e = datetime.fromisoformat(o['eta'])
    slots.setdefault(e.strftime('%d.%m. %H'), []).append(o)
for k, os_ in slots.items():
    top = sorted(os_, key=lambda o: -o['score'])[:3]
    print(f"{k} Uhr: " + ' | '.join(f"km {o['km']:.0f} {o['ort']} ({o['score']})" for o in top))

print('\n## Radläden bis ' + f'{R_RAD / 1000:.0f} km, offen oder unklar zur Planzeit')
for p in sorted([p for p in rad if p['status'] != 'zu'], key=lambda p: (p['km'], p['tag'])):
    print(f"km {p['km']:6.1f} {route.zeit(p['km'], p['tag']):9} {p['dist']:5d} m {p['status']:5} {p['name'][:32]:32} "
          f"{p['street']} {p['hn']} {p['city']}  {p['day']}")

print(f'\n## Umweg-Optionen {R:.0f} m bis {R_GAP:.0f} m (nur für Lücken gedacht)')
for p in sorted([p for p in pois if p['umweg'] and p['status'] != 'zu' and p['cat'] in ('super', 'tanke', 'baecker', 'laden')],
                key=lambda p: (p['km'], p['tag'])):
    print(f"km {p['km']:6.1f} {route.zeit(p['km'], p['tag']):9} {p['dist']:4d} m {p['cat']:7} {p['status']:5} "
          f"{p['name'][:30]:30} {p['city'][:18]:18} {p['day']}")
