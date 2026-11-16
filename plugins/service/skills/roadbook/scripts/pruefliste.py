"""Prüfliste für den Chat aus auswahl.json: Markdown-Tabelle mit km, Rest, Planzeit, Ort (Google-Maps-Link auf den
ersten Laden, ohne Option kein Link) und Optionen. Darunter Abstände über 25 km zwischen zwei Stopps und der Stand
der Google-Prüfung (Feld quelle je Option).

Aufruf: python3.12 -P pruefliste.py <roadbook.json> [auswahl.json]
"""
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True  # kein __pycache__ im Skill-Ordner
from model import EMOJI, Route, lade_auswahl, lade_config  # noqa: E402

cfg = lade_config(sys.argv[1])
route = Route(cfg)
stopps = lade_auswahl(cfg, route, sys.argv[2] if len(sys.argv) > 2 else None)


def maps(o, ort):
    """Suchlink auf Google Maps: Name ohne Klammerzusatz und Adresse, ohne Adresse der Ort des Stopps."""
    teile = [(o.get('name') or '').split(' (')[0], o.get('adresse') or ort]
    return 'https://www.google.com/maps/search/?api=1&query=' + urllib.parse.quote_plus(', '.join(t for t in teile if t))


def zeit(s):
    return route.zeit(s['km'], route.stopp_tag(s))


print('| km | Rest | Zeit | Ort | Optionen |')
print('|---|---|---|---|---|')
for s in stopps:
    ort = f"[{s['ort']}]({maps(s['optionen'][0], s['ort'])})" if s['optionen'] else s['ort']
    if s.get('wichtig'):
        ort = f"**{ort}** ({s['wichtig']})"
    if s.get('schlaf'):
        ort += ' 🛏️'
    if s.get('umweg_m'):
        ort += f" ↪ {s['umweg_m']} m Umweg"
    opts = ', '.join(' '.join(x for x in (EMOJI[o['symbol']], o.get('name', ''), o.get('zeiten', ''),
                                          '(nur OSM)' if o.get('quelle') == 'osm' else '') if x)
                     for o in s['optionen'])
    print(f"| {round(s['km'])} | {round(route.total - s['km'])} | {zeit(s)} | {ort} | {opts} |")

print('\nAbstände über 25 km:')
for a, b in zip(stopps, stopps[1:]):
    if b['km'] - a['km'] > 25:
        print(f"- {a['ort']} bis {b['ort']}: {b['km'] - a['km']:.0f} km ({zeit(a)} bis {zeit(b)})")
optionen = [o for s in stopps for o in s['optionen']]
google = sum(1 for o in optionen if o.get('quelle') == 'google')
print(f"\n{len(stopps)} Stopps, davon {sum(1 for s in stopps if s.get('wichtig'))} wichtig (grau). "
      f"Google-Prüfung: {google} von {len(optionen)} Optionen (quelle google)")
