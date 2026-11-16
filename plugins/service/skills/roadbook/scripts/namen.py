"""Ortsteil-Namen per Nominatim-Rückwärtssuche für alle Kandidaten-Orte (1 Anfrage je Sekunde, Cache in
data/names.json). Danach kandidaten.py erneut laufen lassen, dann stehen dort die Ortsteile (z.B. Oberlenningen
statt Lenningen, Stuttgart-Mühlhausen statt Stuttgart).

Aufruf: python3.12 -P namen.py <roadbook.json> [lat,lon ...]
Netz: nominatim.openstreetmap.org
"""
import json
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True  # kein __pycache__ im Skill-Ordner
from model import hole, lade_config, lies_json, ortsname, pfad  # noqa: E402


def punkt(arg):
    """Zusatzpunkt lat,lon aus dem Aufruf, sonst Abbruch mit einer Zeile vor dem ersten Abruf."""
    try:
        la, lo = (float(v) for v in arg.split(','))
    except ValueError:
        sys.exit(f'Punkt {arg!r} nicht lesbar, erwartet Breite,Länge wie 48.6789,9.4321')
    return la, lo


cfg = lade_config(sys.argv[1])
zusatz = ' '.join(sys.argv[2:]).split()
zusatz_punkte = [punkt(arg) for arg in zusatz]
cache_p = pfad(cfg, 'data', 'names.json')
cache = lies_json(cache_p, 'löschen und namen.py neu laufen lassen') if cache_p.exists() else {}
punkte = [(o['lat'], o['lon']) for o in lies_json(pfad(cfg, 'data', 'kandidaten.json'), 'erst kandidaten.py laufen lassen')['orte']]
punkte += zusatz_punkte

neu = 0
for la, lo in punkte:
    key = f'{la:.5f},{lo:.5f}'
    if key in cache:
        continue
    url = 'https://nominatim.openstreetmap.org/reverse?' + urllib.parse.urlencode(
        {'format': 'jsonv2', 'lat': la, 'lon': lo, 'zoom': 16, 'accept-language': 'de'})
    roh = hole(url, versuche=2, pause=2, timeout=30)
    try:
        antwort = json.loads(roh) if roh else None
    except ValueError:  # etwa eine HTML-Seite statt JSON, der Punkt bleibt offen wie bei einem gescheiterten Abruf
        antwort = None
        print(f'  {key}: Nominatim-Antwort nicht lesbar, beim nächsten Lauf erneut')
    if isinstance(antwort, dict):
        cache[key] = antwort.get('address', {})
        neu += 1
    time.sleep(1.1)  # Nutzungsregel von Nominatim: höchstens 1 Anfrage je Sekunde
with open(cache_p, 'w', encoding='utf-8') as f:
    json.dump(cache, f, ensure_ascii=False)
print(f'{neu} neu, {len(cache)} im Cache')
for arg, (la, lo) in zip(zusatz, zusatz_punkte):  # Zusatzpunkte direkt mit Namen ausgeben
    print(f'{arg}: {ortsname(cache.get(f"{la:.5f},{lo:.5f}", {}))}')
