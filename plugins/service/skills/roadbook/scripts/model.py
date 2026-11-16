"""Gemeinsame Bausteine des Roadbooks: Konfiguration und Eingaben (GPX, Komoot, auswahl.json), Zeitmodell über
mehrere Tage, Projektion auf die Route, OSM-Öffnungszeiten mit Puffer, Ortsnamen aus Nominatim-Adressen.
Fehler in Eingaben brechen mit einer Zeile ab (sys.exit), nicht mit einem Traceback.
"""
import calendar
import json
import math
import re
import subprocess
import sys
import time as _uhr
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

sys.dont_write_bytecode = True
import numpy as np  # noqa: E402

WOCHENTAG = ['MONTAG', 'DIENSTAG', 'MITTWOCH', 'DONNERSTAG', 'FREITAG', 'SAMSTAG', 'SONNTAG']
KURZTAG = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']
STANDARD = {
    'ignorieren_start_km': 30, 'ignorieren_ende_km': 20, 'radius_m': 300, 'radius_luecke_m': 1000,
    'radius_rad_m': 4000, 'puffer_min': 90, 'imbiss_ab': '17:00', 'sticker_mm': [40, 150],
    'iphone': 'iPhone 16 Pro', 'titel': 'Roadbook',
}
UA = 'ServiceKitRoadbook/1.0 (private Routenplanung)'  # ohne Namen, Nominatim verlangt eine Kennung
GRENZE_KM = 2.0  # Übernachtung: so weit vor und hinter dem Zielpunkt eines Tages zählen Abend und Morgen
EMOJI = {'laden': '🛒', 'automat': '🥤', 'baecker': '🥐', 'imbiss': '🍔', 'tanke': '⛽', 'rad': '🔧'}  # Prüfliste, Wallpaper
SYMBOLE = tuple(EMOJI)  # erlaubte Werte für symbol in auswahl.json


def sync_wurzel(ordner):
    """Sync-Ordner, in dem ordner liegt (iCloud Drive, OneDrive und andere Cloud-Speicher), sonst None. OneDrive
    ohne CloudStorage (~/OneDrive - Firma, Group Containers der Standalone-App) nur unter dem Home-Ordner, denn der
    Scratchpad unter /tmp trägt den Pfad des Projekts im Namen."""
    ordner = Path(ordner)
    heim = Path.home()
    for wurzel in (heim / 'Library' / 'Mobile Documents', heim / 'Library' / 'CloudStorage'):
        if ordner == wurzel or wurzel in ordner.parents:
            return wurzel
    if heim in ordner.parents:
        teile = ordner.relative_to(heim).parts
        for i, teil in enumerate(teile):
            if teil.startswith('OneDrive'):
                return heim.joinpath(*teile[:i + 1])
    return None


def lies_json(p, hinweis):
    """JSON-Datei lesen. Fehlt sie oder ist sie leer oder kaputt, Abbruch mit einer Zeile samt hinweis."""
    try:
        return json.loads(Path(p).read_text(encoding='utf-8'))
    except FileNotFoundError:
        sys.exit(f'{p} fehlt: {hinweis}')
    except ValueError as e:
        sys.exit(f'{p} ist leer oder kein gültiges JSON ({e}): {hinweis}')


def pruefe_tage(cfg):
    """tage in roadbook.json: je Tag datum, start und ende, jeder Tag außer dem letzten mit ziel oder ziel_km."""
    tage = cfg.get('tage')
    if not isinstance(tage, list) or not tage:
        sys.exit('roadbook.json ohne tage: je Tag datum, start und ende eintragen')
    for i, t in enumerate(tage, 1):
        if not isinstance(t, dict):
            sys.exit(f'Tag {i} in roadbook.json ist kein Objekt mit datum, start und ende')
        wer = f"Tag {i} ({t.get('datum') or 'ohne Datum'})"
        try:
            datetime.fromisoformat(t['datum'])
            time.fromisoformat(t['start'])
            time.fromisoformat(t['ende'])
        except (KeyError, TypeError, ValueError):
            sys.exit(f'{wer}: datum (JJJJ-MM-TT), start und ende (HH:MM) fehlen oder sind nicht lesbar')
        if 'ziel_km' in t and not isinstance(t['ziel_km'], (int, float)):
            sys.exit(f'{wer}: ziel_km muss eine Zahl sein')
        if i < len(tage) and 'ziel_km' not in t:
            ziel = t.get('ziel')
            if not (isinstance(ziel, list) and len(ziel) == 2 and all(isinstance(v, (int, float)) for v in ziel)):
                sys.exit(f'{wer}: ziel ([Breite, Länge] der Übernachtung) oder ziel_km fehlt, Pflicht für jeden Tag '
                         'außer dem letzten')


def lade_config(datei):
    """roadbook.json lesen und prüfen, Standardwerte ergänzen, data/ und out/ daneben anlegen. Liegt die Datei in
    einem Sync-Ordner, Abbruch vor dem ersten Ordner: Der Sync trüge sonst jeden Zwischenstand hoch."""
    datei = Path(datei).expanduser().absolute()
    for ordner in (datei.parent, datei.resolve().parent):
        wurzel = sync_wurzel(ordner)
        if wurzel:
            sys.exit(f'Arbeitsordner {ordner} liegt im Sync-Ordner {wurzel}, die Skripte legen dort data/ und out/ an. '
                     'roadbook.json im Scratchpad oder unter $TMPDIR anlegen, die fertigen Dateien erst am Ende nach '
                     'Freigabe nach Downloads kopieren.')
    cfg = lies_json(datei, 'Pfad zur roadbook.json prüfen')
    if not isinstance(cfg, dict):
        sys.exit(f'{datei} ist kein JSON-Objekt')
    for k, v in STANDARD.items():
        cfg.setdefault(k, v)
    pruefe_tage(cfg)
    ordner = datei.resolve().parent
    cfg['_ordner'] = str(ordner)
    for sub in ('data', 'data/overpass', 'data/orm', 'out', 'out/icons'):
        (ordner / sub).mkdir(parents=True, exist_ok=True)
    return cfg


def pfad(cfg, *teile):
    return Path(cfg['_ordner'], *teile)


def hole(url, daten=None, ua=UA, versuche=4, pause=10, timeout=120):
    """HTTP-Abruf über curl mit Wiederholung. urllib bricht über den Sandbox-Proxy große Antworten ab
    (IncompleteRead), curl nicht. Overpass ist abends oft überlastet (504)."""
    befehl = ['curl', '-s', '-S', '-f', '--compressed', '-m', str(timeout), '-A', ua, url]
    if daten is not None:
        befehl += ['--data-binary', '@-']
    for v in range(versuche):
        r = subprocess.run(befehl, input=daten, capture_output=True)
        if r.returncode == 0 and r.stdout:
            return r.stdout
        print('  Versuch', v + 1, 'Fehler', r.stderr.decode('utf-8', 'ignore').strip()[:120])
        if v < versuche - 1:
            _uhr.sleep(pause)
    return None


def ortsname(a):
    """Name aus einer Nominatim-Adresse: Dorf oder Ortsteil vor Gemeinde, in Großstädten Stadt-Stadtteil
    (Stuttgart-Mühlhausen). Kernstadt-Angaben wie "Reutlingen (Kernstadt)" ergeben nur die Stadt."""
    stadt = a.get('city')
    teil = a.get('suburb') or a.get('city_district')
    if stadt and teil:
        if teil.startswith(stadt + '-'):
            return teil
        if stadt not in teil:
            return f'{stadt}-{teil}'
    return a.get('village') or a.get('town') or a.get('city') or a.get('hamlet') or teil or a.get('municipality') or '?'


# ---------------------------------------------------------------- Eingaben: GPX und Komoot
def zeitpunkt(text):
    """GPX-Zeit als UTC. Ohne Zone (ohne Z oder Versatz) gilt sie als UTC, so passen gemischte Angaben zusammen.
    None, wenn sie nicht lesbar ist."""
    try:
        ts = datetime.fromisoformat((text or '').strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def gpx_lesen(datei):
    """Trackpunkte [lat, lon, Höhe, Stunden ab Start oder None] und Wegpunkte (lat, lon, Name) aus einer GPX.
    Abbruch mit einer Zeile, wenn die Datei fehlt, kein GPX ist oder weniger als zwei Trackpunkte hat."""
    datei = Path(datei).expanduser()
    try:
        root = ET.parse(datei).getroot()
    except FileNotFoundError:
        sys.exit(f'GPX fehlt: {datei}')
    except (ET.ParseError, OSError) as e:
        sys.exit(f'GPX nicht lesbar: {datei} ({e})')
    ns = root.tag.split('}')[0].strip('{') if root.tag.startswith('{') else ''
    q = lambda t: f'{{{ns}}}{t}' if ns else t
    pts, t_start = [], None
    for p in list(root.iter(q('trkpt'))) or list(root.iter(q('rtept'))):
        try:
            lat, lon = float(p.get('lat')), float(p.get('lon'))
        except (TypeError, ValueError):
            continue  # Punkt ohne Koordinaten
        e, t = p.find(q('ele')), p.find(q('time'))
        try:
            hoehe = float(e.text) if e is not None else 0.0
        except (TypeError, ValueError):
            hoehe = 0.0
        ts = zeitpunkt(t.text) if t is not None else None
        h = None
        if ts is not None:
            t_start = t_start or ts
            h = (ts - t_start).total_seconds() / 3600
        pts.append([lat, lon, hoehe, h])
    if len(pts) < 2:
        sys.exit(f'GPX ohne Strecke: {datei} hat {len(pts)} Trackpunkte (trkpt oder rtept), gebraucht werden mindestens 2')
    wpts = []
    for w in root.findall(q('wpt')):
        n = w.find(q('name'))
        try:
            wpts.append((float(w.get('lat')), float(w.get('lon')), (n.text or '') if n is not None else ''))
        except (TypeError, ValueError):
            continue
    return pts, wpts


def komoot_link(link):
    """(Tour-Nummer, share_token) aus einem Komoot-Teilen-Link. Kurzlinks ohne /tour/<Nummer> brechen ab."""
    m = re.search(r'/tour/(\d+)', link or '')
    if not m:
        sys.exit('Komoot-Link ohne /tour/<Nummer> (etwa ein Kurzlink): im Browser öffnen und den vollen Teilen-Link '
                 'mit share_token nehmen oder die Route als GPX exportieren')
    token = urllib.parse.parse_qs(urllib.parse.urlparse(link).query).get('share_token', [''])[0]
    return m.group(1), token


def komoot_punkte(roh):
    """Trackpunkte [lat, lon, Höhe, Stunden ab Start oder None] aus der Antwort von api.komoot.de. Ohne
    Koordinaten (Tour privat, Link abgelaufen, Fehlerseite) Abbruch mit einer Zeile."""
    try:
        items = json.loads(roh)['_embedded']['coordinates']['items']
    except (ValueError, KeyError, TypeError):
        items = None
    pts = []
    for c in items or []:
        try:
            pts.append([float(c['lat']), float(c['lng']), float(c.get('alt') or 0.0),
                        c['t'] / 3600000 if c.get('t') is not None else None])
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    if len(pts) < 2:
        sys.exit('Komoot-Antwort ohne Koordinaten (Tour privat, Link abgelaufen oder ohne share_token): '
                 'Teilen-Link prüfen oder die Route als GPX exportieren')
    return pts


class Route:
    def __init__(self, cfg):
        r = lies_json(pfad(cfg, 'data', 'route.json'), 'erst route.py laufen lassen')
        p = np.array(r['pts'], dtype=float)
        self.lat, self.lon, self.km, self.kt = p[:, 0], p[:, 1], p[:, 3], p[:, 4]
        self.total = float(self.km[-1])
        self.wpts = r.get('wpts', [])
        self.hinweise = []  # für route.py: Ziel mehrdeutig (Rundkurs) oder weit neben der Strecke
        self.km_von = float(cfg['ignorieren_start_km'])
        self.km_bis = self.total - float(cfg['ignorieren_ende_km'])
        self.puffer = int(cfg['puffer_min'])
        lat0 = float(self.lat.mean())
        self.kx = math.cos(math.radians(lat0)) * 111320.0
        self.ky = 110574.0
        self.x, self.y = self.lon * self.kx, self.lat * self.ky
        self.tage = []
        km0 = 0.0
        for i, t in enumerate(cfg['tage']):
            d = datetime.fromisoformat(t['datum']).date()
            t0 = datetime.combine(d, time.fromisoformat(t['start']))
            t1 = datetime.combine(d, time.fromisoformat(t['ende']))
            if t1 <= t0:  # Ankunft nach Mitternacht
                t1 += timedelta(days=1)
            if i == len(cfg['tage']) - 1:
                km1 = self.total
            elif 'ziel_km' in t:
                km1 = float(t['ziel_km'])
            else:
                km1 = self.ziel_auf_strecke(i, t['ziel'][0], t['ziel'][1], km0)
            if not km0 < km1 <= self.total:
                sys.exit(f'Tag {i + 1}: Ziel bei km {km1:.1f} liegt nicht zwischen km {km0:.1f} und {self.total:.1f}, '
                         'ziel oder ziel_km prüfen')
            k0, k1 = self.kt_at(km0), self.kt_at(km1)
            self.tage.append({'t0': t0, 't1': t1, 'km0': km0, 'km1': km1, 'kt0': k0,
                              'f': (t1 - t0).total_seconds() / 3600 / max(k1 - k0, 1e-6),
                              'ziel': t.get('ziel_name', ''), 'tag': WOCHENTAG[t0.weekday()]})
            km0 = km1

    def kt_at(self, km):
        return float(np.interp(km, self.km, self.kt))

    def ziel_auf_strecke(self, i, lat, lon, km0):
        """km des Übernachtungsorts von Tag i: der nächste Streckenpunkt hinter km0. Kommt die Strecke dort mehrmals
        vorbei (Rundkurs, hin und zurück) oder liegt das Ziel weit daneben, steht es in self.hinweise."""
        km1, abstand = self.naechster(lat, lon, ab_km=km0 + 1)
        if not math.isfinite(abstand):
            sys.exit(f'Tag {i + 1}: hinter km {km0 + 1:.1f} gibt es keine Strecke mehr für das Ziel, ziel_km prüfen')
        andere = [k for k, _ in self.passes(lat, lon, abstand + 1000) if k > km0 + 1 and abs(k - km1) > GRENZE_KM]
        if andere:
            self.hinweise.append(f'Tag {i + 1}: Die Strecke kommt mehrmals am Ziel vorbei (km {km1:.1f}, '
                                 + ', '.join(f'{k:.1f}' for k in andere) + f'), genommen ist km {km1:.1f}. '
                                 'Stimmt das nicht, ziel_km setzen.')
        if abstand > 3000:
            self.hinweise.append(f'Tag {i + 1}: Das Ziel liegt {abstand / 1000:.1f} km neben der Strecke, Koordinate prüfen.')
        return km1

    def tag_index(self, km):
        for i, t in enumerate(self.tage):
            if km <= t['km1'] + 1e-6:
                return i
        return len(self.tage) - 1

    def tage_bei(self, km):
        """Tage, zu denen ein Punkt bei km gehört. An einer Übernachtung (GRENZE_KM vor und hinter dem Zielpunkt)
        beide: Ankunft am Abend und Abfahrt am Morgen. Sonst nur der Tag aus tag_index."""
        letzter = len(self.tage) - 1
        tage = [i for i, t in enumerate(self.tage)
                if t['km0'] - (GRENZE_KM if i > 0 else 0) - 1e-6 <= km <= t['km1'] + (GRENZE_KM if i < letzter else 0) + 1e-6]
        return tage or [self.tag_index(km)]

    def stopp_tag(self, s):
        """Tag eines Stopps aus auswahl.json (0 = erster Tag). Das Feld tag (1 = erster Tag) gewinnt, ein
        Schlaf-Stopp an einer Übernachtung gehört zum Abend, sonst zählt der km."""
        if s.get('tag'):
            return int(s['tag']) - 1
        tage = self.tage_bei(s['km'])
        if s.get('schlaf') and len(tage) > 1:
            return tage[0]
        return self.tag_index(s['km'])

    def eta(self, km, tag=None):
        """Planzeit bei km. tag (0 = erster Tag) wählt an einer Übernachtung Abend oder Morgen, ohne tag gilt
        tag_index. Liegt km vor dem Start des Tages, gilt die Abfahrt."""
        t = self.tage[self.tag_index(km) if tag is None else tag]
        if km <= t['km0']:
            return t['t0']
        return t['t0'] + timedelta(hours=(self.kt_at(km) - t['kt0']) * t['f'])

    def naechster(self, lat, lon, ab_km=0.0):
        """(km, abstand_m) des nächsten Streckenpunkts ab ab_km, abstand_m unendlich, wenn dort keiner mehr ist."""
        d = (self.x - lon * self.kx) ** 2 + (self.y - lat * self.ky) ** 2
        d[self.km < ab_km] = np.inf
        j = int(np.argmin(d))
        return float(self.km[j]), float(math.sqrt(d[j]))

    def abstand(self, lat1, lon1, lat2, lon2):
        return math.hypot((lon1 - lon2) * self.kx, (lat1 - lat2) * self.ky)

    def passes(self, lat, lon, radius):
        """Alle Durchfahrten im Radius: Liste (km, abstand_m), je Durchfahrt der nächste Punkt."""
        px, py = lon * self.kx, lat * self.ky
        ax, ay, bx, by = self.x[:-1], self.y[:-1], self.x[1:], self.y[1:]
        dx, dy = bx - ax, by - ay
        ll = dx * dx + dy * dy
        ll[ll == 0] = 1e-9
        t = np.clip(((px - ax) * dx + (py - ay) * dy) / ll, 0, 1)
        dist = np.hypot(px - (ax + t * dx), py - (ay + t * dy))
        kmq = self.km[:-1] + t * (self.km[1:] - self.km[:-1])
        idx = np.where(dist <= radius)[0]
        if len(idx) == 0:
            return []
        gruppen, cur = [], [idx[0]]
        for i in idx[1:]:
            if kmq[i] - kmq[cur[-1]] > 2.0:
                gruppen.append(cur)
                cur = [i]
            else:
                cur.append(i)
        gruppen.append(cur)
        out = []
        for g in gruppen:
            j = g[int(np.argmin(dist[g]))]
            out.append((float(kmq[j]), float(dist[j])))
        return out

    def zeit(self, km, tag=None):
        e = self.eta(km, tag)
        return f'{KURZTAG[e.weekday()]} {e.hour}:{e.minute:02d}'


# ---------------------------------------------------------------- Auswahl (auswahl.json)
def lade_auswahl(cfg, route, datei=None):
    """Stopps aus auswahl.json, geprüft und nach Tag und km sortiert. Fehlende Felder bekommen Standardwerte
    (optionen leer, kurz wie ort), echte Fehler brechen mit einer Zeile ab."""
    p = Path(datei) if datei else pfad(cfg, 'auswahl.json')
    daten = lies_json(p, 'auswahl.json mit "stopps" schreiben (Skill, Abschnitt 4)')
    stopps = daten.get('stopps') if isinstance(daten, dict) else None
    if not isinstance(stopps, list) or not stopps:
        sys.exit(f'{p} enthält keine Stopps, erwartet wird "stopps" als Liste mit mindestens einem Stopp')
    for n, s in enumerate(stopps, 1):
        if not isinstance(s, dict):
            sys.exit(f'Stopp {n} in {p.name} ist kein Objekt')
        wer = f"Stopp {n} ({s.get('ort') or s.get('kurz') or 'ohne Namen'})"
        km = s.get('km')
        if isinstance(km, bool) or not isinstance(km, (int, float)) or not 0 <= km <= route.total:
            sys.exit(f'{wer}: km fehlt oder liegt nicht auf der Strecke (0 bis {route.total:.1f})')
        if not (s.get('ort') or s.get('kurz')):
            sys.exit(f'{wer}: ort fehlt')
        s['ort'] = s.get('ort') or s['kurz']
        s['kurz'] = s.get('kurz') or s['ort']
        if s.setdefault('optionen', []) is None:
            s['optionen'] = []
        if not isinstance(s['optionen'], list):
            sys.exit(f'{wer}: optionen muss eine Liste sein')
        for o in s['optionen']:
            if not isinstance(o, dict) or o.get('symbol') not in SYMBOLE:
                gefunden = o.get('symbol') if isinstance(o, dict) else o
                sys.exit(f"{wer}: Symbol {gefunden!r} unbekannt, erlaubt sind {', '.join(SYMBOLE)}")
        tag = s.get('tag')
        if tag is not None and (isinstance(tag, bool) or not isinstance(tag, int) or not 1 <= tag <= len(route.tage)):
            sys.exit(f'{wer}: tag muss 1 bis {len(route.tage)} sein (1 = erster Tag)')
    return sorted(stopps, key=lambda s: (route.stopp_tag(s), s['km']))


def zeiten_quelle(stopps):
    """Zeile für den Sticker, woher die Öffnungszeiten kommen: Feld quelle je Option, google oder osm."""
    optionen = [o for s in stopps for o in s.get('optionen') or []]
    google = sum(1 for o in optionen if o.get('quelle') == 'google')
    if optionen and google == len(optionen):
        return 'Öffnungszeiten geprüft mit Google Maps.'
    if google:
        return 'Öffnungszeiten mit Google Maps geprüft, einzelne nur aus OpenStreetMap.'
    return 'Öffnungszeiten aus OpenStreetMap, nicht mit Google Maps geprüft.'


# ---------------------------------------------------------------- Öffnungszeiten (OSM)
DAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']
DE = {'Di': 'Tu', 'Mi': 'We', 'Do': 'Th', 'So': 'Su'}
DAYTOK = r'(?:Mo|Tu|We|Th|Fr|Sa|Su|Di|Mi|Do|So|PH|SH)'
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
KANON = {x.lower(): x for x in DAYS + list(DE) + ['PH', 'SH'] + MONTHS}  # mo-fr gilt wie Mo-Fr
KANON_RE = re.compile(r'\b(' + '|'.join(KANON) + r')\b', re.I)


def _day(t):
    return DAYS.index(DE.get(t, t))


def _nter(d, auswahl):
    """Trifft [1], [-1], [1-2] oder [1,3] (n-ter Wochentag im Monat, negativ von hinten gezählt) auf das Datum d
    zu? None, wenn die Angabe nicht lesbar ist."""
    vorn = (d.day - 1) // 7 + 1
    hinten = -((calendar.monthrange(d.year, d.month)[1] - d.day) // 7 + 1)
    for teil in auswahl.split(','):
        m = re.fullmatch(r'\s*(-?[1-5])\s*(?:-\s*(-?[1-5]))?\s*', teil)
        if not m:
            return None
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        n = vorn if a > 0 else hinten
        if min(a, b) <= n <= max(a, b):
            return True
    return False


def ostern(jahr):
    """Ostersonntag nach der Gaußschen Osterformel (gregorianisch, anonyme Fassung)."""
    a, (b, c) = jahr % 19, divmod(jahr, 100)
    d, e = divmod(b, 4)
    g = (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    wt = (32 + 2 * e + 2 * i - h - k) % 7
    monat, tag = divmod(h + wt - 7 * ((a + 11 * h + 22 * wt) // 451) + 114, 31)
    return datetime(jahr, monat, tag + 1).date()


def feiertag(d):
    """True an bundesweiten Feiertagen in Deutschland, None an Tagen, die nur in einigen Ländern frei sind (OSM PH
    dann unklar), sonst False. Regel statt fester Liste, Ostern über ostern()."""
    o = ostern(d.year)
    beweglich = {(o + timedelta(days=k)).timetuple()[1:3]: k for k in (-2, 0, 1, 39, 49, 50, 60)}
    bund = {(1, 1), (5, 1), (10, 3), (12, 25), (12, 26)} | {md for md, k in beweglich.items() if k in (-2, 1, 39, 50)}
    buss = 22 - (datetime(d.year, 11, 22).weekday() - 2) % 7  # Mittwoch vor dem 23.11.
    land = {(1, 6), (3, 8), (8, 15), (9, 20), (10, 31), (11, 1), (11, buss)} | \
        {md for md, k in beweglich.items() if k in (0, 49, 60)}  # Oster- und Pfingstsonntag nur Brandenburg
    md = (d.month, d.day)
    return True if md in bund else (None if md in land else False)


def parse_oh(s, monat=None, datum=None):
    """OSM opening_hours in {wochentag: [(start_min, ende_min)]}, None wenn unklar. monat (1 bis 12) wertet
    Monatsregeln wie "Apr-Oct: Mo-Su 10:00-18:00" aus. datum (der geplante Tag) wertet Regeln für den n-ten Wochentag im Monat
    aus (Su[1] off gilt nur am ersten Sonntag), ohne datum steht so ein Tag auf None (unklar, nie still zu). PH-Regeln
    (PH off, PH 10:00-12:00) gelten am Wochentag von datum, wenn er ein bundesweiter Feiertag ist, an regionalen
    Feiertagen ist der Tag unklar, ohne datum bleiben sie unbeachtet. Regeln nur für Schulferien (SH)
    bleiben immer unbeachtet, es gilt die Grundregel.
    Kommas trennen nur nach einer Uhrzeit neue Regeln (Mo,We 10:00-22:00). Kürzel in jeder Schreibweise."""
    if not s:
        return None
    if datum is not None and monat is None:
        monat = datum.month
    frei = feiertag(datum) if datum is not None else False
    s = s.strip().replace('–', '-').replace('—', '-').replace('||', ';')
    s = KANON_RE.sub(lambda m: KANON[m.group(1).lower()], s)
    if s.lower() in ('24/7', '24/7 open', 'mo-su 00:00-24:00', '00:00-24:00'):
        return {d: [(0, 1440)] for d in range(7)}
    s = re.sub(r'(\d{1,2}:\d{2})\s+(?=' + DAYTOK + r'\b)', r'\1; ', s)
    rules = []
    for part in s.split(';'):
        for sub in re.split(r'(?<=\d),\s*(?=' + DAYTOK + r'\b)', part.strip()):
            if sub.strip():
                rules.append(sub.strip())
    woche = {}  # Wochentag: Datum in den Tagen rund um datum, für Su[1] und Co.
    if datum is not None:
        for k in range(-3, 4):
            woche[(datum + timedelta(days=k)).weekday()] = datum + timedelta(days=k)
    res = {d: [] for d in range(7)}
    seen = False
    for r in rules:
        mm = re.match(r'^(' + '|'.join(MONTHS) + r')(?:\s*-\s*(' + '|'.join(MONTHS) + r'))?\s*:?\s*(.*)$', r)
        if mm:
            a = MONTHS.index(mm.group(1))
            b = MONTHS.index(mm.group(2)) if mm.group(2) else a
            if monat is not None and (monat - 1) not in [(a + k) % 12 for k in range(((b - a) % 12) + 1)]:
                continue
            r = mm.group(3).strip()
        m = re.match(r'^((?:' + DAYTOK + r'(?:\s*-\s*' + DAYTOK + r')?(?:\[[^\]]*\])?\s*,?\s*)+)?\s*(.*)$', r)
        days_part, rest = m.group(1), m.group(2).strip().lstrip(':').strip()
        unklar = set()
        if days_part:
            # Schulferien (SH) kennt der Parser nicht und rechnet ohne sie: Ein Teil der Auswahl mit SH fällt weg, eine
            # Regel nur für die Ferien (SH Mo-Fr 08:00-18:00) also ganz, dann gilt die Grundregel. In PH,SH off bleibt
            # PH
            days_part = ','.join(t for t in days_part.split(',') if not re.search(r'\bSH\b', t))
            if not days_part.strip():
                continue
            sel, only_ph = set(), True
            for a, b, nte in re.findall('(' + DAYTOK + r')(?:\s*-\s*(' + DAYTOK + r'))?(?:\[([^\]]*)\])?', days_part):
                if a == 'PH' and frei is not False:
                    only_ph = False
                    (sel if frei else unklar).add(datum.weekday())
                if a == 'PH':
                    continue
                only_ph = False
                ia = _day(a)
                if b and b != 'PH':
                    wahl = {(ia + k) % 7 for k in range(((_day(b) - ia) % 7) + 1)}
                else:
                    wahl = {ia}
                if not nte:
                    sel |= wahl
                    continue
                for d in wahl:
                    treffer = _nter(woche[d], nte) if woche else None
                    if treffer is None:
                        unklar.add(d)
                    elif treffer:
                        sel.add(d)
            if only_ph:
                continue
        else:
            sel = set(range(7))
        if re.match(r'[+-]\s*\d+\s*days?\b', rest):  # Versatz wie "Su[-1] -1 day" wertet der Parser nicht aus
            for d in sel | unklar:
                res[d] = None
            seen = True
            continue
        for d in unklar:
            res[d] = None
        seen = seen or bool(unklar)
        low = rest.lower()
        if low.startswith('off') or low.startswith('closed'):
            for d in sel:
                res[d] = []
            seen = True
            continue
        if low in ('open', '24/7', '00:00-24:00'):
            for d in sel:
                res[d] = [(0, 1440)]
            seen = True
            continue
        times = re.findall(r'(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})', rest)
        if not times:
            return None
        iv = []
        for h1, m1, h2, m2 in times:
            a, b = int(h1) * 60 + int(m1), int(h2) * 60 + int(m2)
            iv.append((a, b + 1440 if b <= a else b))
        for d in sel:
            res[d] = iv
        seen = True
    return res if seen else None


def orm_weekly(parsed):
    """OnRouteMap-Format (opening_hours_parsed) in das Format von parse_oh."""
    if not parsed or parsed.get('status') != 'ok':
        return None
    if parsed.get('is_24_7'):
        return {d: [(0, 1440)] for d in range(7)}
    res = {d: [] for d in range(7)}
    for k, ivs in (parsed.get('weekly') or {}).items():
        for a, b in ivs:
            x, y = int(a[:2]) * 60 + int(a[3:]), int(b[:2]) * 60 + int(b[3:])
            res[int(k) - 1].append((x, y + 1440 if y <= x else y))
    return res


def status(week, t, puffer):
    """('ok'|'knapp'|'zu'|'?', minuten_bis_schluss, oeffnet_um). ok heißt: offen und danach noch puffer Minuten.
    Ein unklarer Tag (None in week, etwa Su[1] ohne Datum) ergibt '?', nie zu."""
    if week is None:
        return '?', None, None
    wd, m = t.weekday(), t.hour * 60 + t.minute
    heute = week.get(wd, [])
    if heute is None:
        return '?', None, None
    vortag = week.get((wd - 1) % 7) or []
    cand = list(heute) + [(a - 1440, b - 1440) for a, b in vortag if b > 1440]
    for a, b in cand:
        if a <= m < b:
            end = b
            if end >= 1440:  # nahtlos in den nächsten Tag
                for a2, b2 in week.get((wd + 1) % 7) or []:
                    if a2 == 0:
                        end = max(end, 1440 + b2)
            left = end - m
            return ('ok' if left >= puffer else 'knapp'), left, None
    nxt = [a for a, b in heute if a > m]
    return 'zu', None, (min(nxt) if nxt else None)


def fmt_day(week, t):
    if week is None:
        return '?'
    ivs = week.get(t.weekday(), [])
    if ivs is None:
        return '?'
    if not ivs:
        return 'zu'
    if ivs == [(0, 1440)]:
        return '24h'
    f = lambda v: f'{(v // 60) % 24}:{v % 60:02d}'
    return ', '.join(f'{f(a)} bis {f(b)}' for a, b in ivs)
