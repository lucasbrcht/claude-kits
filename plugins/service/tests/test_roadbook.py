"""Tests für den Skill /roadbook: Syntax aller Skripte, Skill, Referenz und Steckbrief, Öffnungszeiten aus OSM mit
Puffer, Tagesgrenze und Eingaben (model.py), dazu die Skripte als eigene Prozesse mit einer erfundenen Strecke im
Temp-Ordner (gerade nach Norden ab 0,0 im Meer, Läden und Orte erfunden). Ohne Netz, läuft in der Sandbox.

Aufruf im Kit-Ordner: python3.12 -B -m unittest discover tests. Das -B gehört dazu: unittest importiert diese Datei,
bevor sie selbst dont_write_bytecode setzen kann, sonst entsteht tests/__pycache__ im Kit. model.py und die Skripte
brauchen numpy (render.py auch Pillow und reportlab), das liegt in python3.12. Mit python3 laufen nur die Tests zu
Syntax, Skill und Doku, die anderen überspringen sich.
"""
import datetime as dt
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True  # für model.py und die Skripte, die eigene .pyc verhindert nur -B im Aufruf
KIT = Path(__file__).resolve().parent.parent
SKILL = KIT / "skills" / "roadbook"  # als Plugin (V5): Skills liegen unter skills/ im Plugin-Ordner
SKRIPTE = SKILL / "scripts"
NUMPY = importlib.util.find_spec("numpy") is not None
SCHRIFTEN = ("/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf", "/System/Library/Fonts/Avenir Next Condensed.ttc",
             "/System/Library/Fonts/Apple Color Emoji.ttc")
RENDER = NUMPY and all(importlib.util.find_spec(m) for m in ("PIL", "reportlab")) and all(Path(f).is_file() for f in SCHRIFTEN)
if NUMPY:
    sys.path.insert(0, str(SKRIPTE))
    import model  # noqa: E402

FREITAG = dt.datetime(2026, 10, 23)  # ein Freitag
SONNTAG_1 = dt.date(2026, 10, 4)  # erster Sonntag im Oktober 2026
SONNTAG_4 = dt.date(2026, 10, 25)  # vierter und letzter Sonntag im Oktober 2026
GRAD_KM = 6371.0088 * math.pi / 180  # km je Grad Breite, wie die Haversine-Formel in route.py


def bei(km, lon=0.0):
    """Punkt [lat, lon] bei km auf der erfundenen Strecke, lon verschiebt ihn nach Osten (0.001 Grad etwa 111 m)."""
    return [round(km / GRAD_KM, 7), lon]


def strecke(km, schritt=0.5):
    return [bei(i * schritt) for i in range(int(round(km / schritt)) + 1)]


def gpx(punkte, wegpunkte=(), zeiten=None):
    """GPX-Text aus Punkten [lat, lon], Wegpunkten (lat, lon, Name) und Zeiten je Punkt (Text oder None)."""
    zeilen = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">']
    zeilen += [f'<wpt lat="{la}" lon="{lo}"><name>{n}</name></wpt>' for la, lo, n in wegpunkte]
    zeilen.append("<trk><trkseg>")
    for k, (la, lo) in enumerate(punkte):
        zeit = f"<time>{zeiten[k]}</time>" if zeiten and zeiten[k] else ""
        zeilen.append(f'<trkpt lat="{la}" lon="{lo}"><ele>300</ele>{zeit}</trkpt>')
    zeilen.append("</trkseg></trk></gpx>")
    return "\n".join(zeilen)


def knoten(nr, km, tags, lon=0.0):
    la, lo = bei(km, lon)
    return {"type": "node", "id": nr, "lat": la, "lon": lo, "tags": tags}


# Freitag 10 bis 20 Uhr bis km 60 (Übernachtung), Samstag ab 5 Uhr. Ohne Zeiten in der GPX rechnet route.py mit
# 20 km/h, gestreckt auf den Tag: Freitag km/6 Stunden ab 10 Uhr, Samstag (km - 60)/10 Stunden ab 5 Uhr.
ZWEI_TAGE = [{"datum": "2026-10-23", "start": "10:00", "ende": "20:00", "ziel": bei(60, 0.002), "ziel_name": "Fiktivingen"},
             {"datum": "2026-10-24", "start": "05:00", "ende": "11:00"}]
ABEND = knoten(1, 60.5, {"shop": "supermarket", "name": "Abendmarkt", "opening_hours": "Mo-Sa 08:00-22:00"})
MORGEN = knoten(2, 59.5, {"shop": "bakery", "name": "Morgenbäcker", "opening_hours": "Mo-Sa 05:00-12:00"})


class Skill(unittest.TestCase):
    def test_alle_skripte_sind_gueltiges_python(self):
        dateien = sorted(SKRIPTE.glob("*.py"))
        self.assertGreaterEqual(len(dateien), 7)
        for f in dateien:
            compile(f.read_text(encoding="utf-8"), str(f), "exec")  # ohne __pycache__

    def test_skill_nennt_nur_vorhandene_skripte(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        genannt = set(re.findall(r"\$S/(\w+\.py)", text))
        self.assertTrue(genannt)
        for name in genannt:
            self.assertTrue((SKRIPTE / name).is_file(), name)
        self.assertTrue((SKILL / "references" / "google-maps.md").is_file())
        self.assertTrue((SKRIPTE / "icons.js").is_file())

    def test_skripte_laufen_aus_der_ausgerollten_kopie(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        # als Plugin (V5): Claude Code setzt den Ordner des Skills ein, in Anführungszeichen wegen Leerzeichen im Pfad
        self.assertIn('S="${CLAUDE_SKILL_DIR}/scripts"', text)
        self.assertNotIn("{{", text)
        self.assertNotIn("work-kit", text)

    def test_beschreibung_unter_300_zeichen(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertLess(len(re.search(r"^description: (.+)$", text, re.M).group(1)), 300)

    def test_browser_referenz_setzt_namen_sicher_ein_und_prueft_die_anmeldung(self):
        text = (SKILL / "references" / "google-maps.md").read_text(encoding="utf-8")
        self.assertNotRegex(text, r"want\s*=\s*'")  # kein Name als rohes Literal in einfachen Anführungszeichen
        self.assertIn("JSON.stringify", text)
        self.assertIn("SignOutOptions", text)  # Konto-Element im Kopf der Seite
        self.assertIn("angemeldet", (SKILL / "SKILL.md").read_text(encoding="utf-8"))

    def test_genaue_adresse_nur_auf_ja_an_nominatim(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("Ortsmitte oder Adresse", text)
        self.assertIn("search?q=<Ort>", text)
        self.assertRegex(text, r"genaue Adresse[^\n]*nur auf das Ja des Nutzers")

    def test_testaufruf_mit_B_und_steckbrief_mit_pdftoppm(self):
        for name in ("README.md",):  # als Plugin (V5) ohne CLAUDE.md im Plugin-Ordner
            self.assertIn("python3.12 -B -m unittest discover tests", (KIT / name).read_text(encoding="utf-8"), name)
        self.assertIn("pdftoppm", (SKILL / "SKILL.md").read_text(encoding="utf-8"))
        steckbrief = json.loads((KIT / "kit.json").read_text(encoding="utf-8"))
        self.assertIn("pdftoppm", steckbrief["abhaengigkeiten"]["programme"])


@unittest.skipUnless(NUMPY, "numpy fehlt, mit python3.12 starten")
class Oeffnungszeiten(unittest.TestCase):
    def test_wochentage_und_ruhetag(self):
        w = model.parse_oh("Mo-Fr 07:00-20:00; Sa 08:00-18:00; Su off")
        self.assertEqual(w[0], [(420, 1200)])
        self.assertEqual(w[5], [(480, 1080)])
        self.assertEqual(w[6], [])

    def test_rund_um_die_uhr_und_unklar(self):
        self.assertEqual(model.parse_oh("24/7")[3], [(0, 1440)])
        self.assertIsNone(model.parse_oh(""))
        self.assertIsNone(model.parse_oh("nach Vereinbarung"))

    def test_ueber_mitternacht_und_deutsche_kuerzel(self):
        w = model.parse_oh("Fr 18:00-02:00")
        self.assertEqual(w[4], [(1080, 1560)])
        self.assertEqual(model.parse_oh("Di-Do 10:00-14:00")[1], [(600, 840)])

    def test_kuerzel_in_kleinschreibung(self):
        w = model.parse_oh("mo-fr 07:00-19:00")
        self.assertEqual(w[0], [(420, 1140)])
        self.assertEqual(w[4], [(420, 1140)])
        self.assertEqual(w[5], [])
        self.assertEqual(w[6], [])
        self.assertEqual(model.parse_oh("MO-SA 08:00-20:00; su off")[6], [])

    def test_n_ter_wochentag_gilt_nur_an_diesem_tag(self):
        regel = "Mo-Su 06:00-22:00; Su[1] off"
        self.assertEqual(model.parse_oh(regel, datum=SONNTAG_1)[6], [])
        self.assertEqual(model.parse_oh(regel, datum=SONNTAG_4)[6], [(360, 1320)])
        self.assertEqual(model.parse_oh("Mo-Su 06:00-22:00; Su[-1] off", datum=SONNTAG_4)[6], [])
        self.assertEqual(model.parse_oh("Mo-Su 06:00-22:00; Su[1,3] off", datum=SONNTAG_4)[6], [(360, 1320)])
        ohne = model.parse_oh(regel)  # ohne Datum unklar, nie still zu
        self.assertIsNone(ohne[6])
        self.assertEqual(ohne[5], [(360, 1320)])
        sonntag = dt.datetime.combine(SONNTAG_4, dt.time(10))
        self.assertEqual(model.status(ohne, sonntag, 90), ("?", None, None))
        self.assertEqual(model.fmt_day(ohne, sonntag), "?")
        self.assertIsNone(model.parse_oh("Mo-Su 06:00-22:00; Su[-1] -1 day off", datum=SONNTAG_4)[6])

    def test_feiertag_als_regel(self):
        self.assertEqual([model.ostern(j) for j in (2026, 2027, 2028)],
                         [dt.date(2026, 4, 5), dt.date(2027, 3, 28), dt.date(2028, 4, 16)])
        self.assertTrue(model.feiertag(dt.date(2026, 10, 3)))  # Tag der Deutschen Einheit
        self.assertTrue(model.feiertag(dt.date(2026, 4, 3)))  # Karfreitag
        self.assertTrue(model.feiertag(dt.date(2026, 5, 14)))  # Christi Himmelfahrt
        self.assertIsNone(model.feiertag(dt.date(2026, 6, 4)))  # Fronleichnam, nur in einigen Ländern
        self.assertIsNone(model.feiertag(dt.date(2026, 11, 18)))  # Buß- und Bettag, Sachsen
        self.assertFalse(model.feiertag(FREITAG.date()))

    def test_ph_off_am_feiertag(self):
        regel = "Mo-Sa 08:00-20:00; PH off"
        self.assertEqual(model.parse_oh(regel, datum=dt.date(2026, 10, 3))[5], [])  # Samstag, Einheit
        self.assertEqual(model.parse_oh(regel, datum=dt.date(2026, 10, 10))[5], [(480, 1200)])
        self.assertEqual(model.parse_oh(regel)[5], [(480, 1200)])  # ohne Datum wie bisher
        self.assertIsNone(model.parse_oh(regel, datum=dt.date(2026, 6, 4))[3])  # regional: unklar, nie still zu
        self.assertEqual(model.parse_oh("Mo-Fr 08:00-18:00; PH 10:00-12:00", datum=dt.date(2026, 12, 25))[4],
                         [(600, 720)])
        self.assertEqual(model.parse_oh("Su,PH off; Mo-Sa 07:00-19:00", datum=dt.date(2026, 4, 3))[4], [(420, 1140)])

    def test_schulferien_bleiben_unbeachtet(self):
        """V3.1.2: SH Mo-Fr 08:00-18:00 galt an jedem Freitag. Schulferien kennt der Parser nicht, die Grundregel gilt."""
        regel = "Mo-Fr 08:00-12:00; SH Mo-Fr 08:00-18:00"
        for datum in (None, FREITAG.date()):
            self.assertEqual(model.parse_oh(regel, datum=datum)[4], [(480, 720)])
        self.assertEqual(model.parse_oh("mo-sa 07:00-19:00; sh off")[5], [(420, 1140)])
        self.assertIsNone(model.parse_oh("SH Mo-Fr 08:00-18:00"))  # nur Ferienzeiten: unklar
        regel = "Mo-Sa 08:00-20:00; PH,SH off"  # PH gilt weiter, SH fällt weg
        self.assertEqual(model.parse_oh(regel, datum=dt.date(2026, 10, 3))[5], [])
        self.assertEqual(model.parse_oh(regel, datum=dt.date(2026, 10, 10))[5], [(480, 1200)])
        self.assertEqual(model.parse_oh("Mo-Fr,SH 10:00-12:00")[2], [(600, 720)])

    def test_monatsregel(self):
        self.assertIsNone(model.parse_oh("Apr-Oct: Mo-Su 10:00-18:00", monat=11))
        self.assertEqual(model.parse_oh("Apr-Oct: Mo-Su 10:00-18:00", monat=10)[4], [(600, 1080)])
        self.assertIsNone(model.parse_oh("Apr-Oct: Mo-Su 10:00-18:00", datum=dt.date(2026, 11, 6)))

    def test_status_mit_puffer(self):
        w = model.parse_oh("Mo-Su 07:00-20:00")
        self.assertEqual(model.status(w, FREITAG.replace(hour=10), 90), ("ok", 600, None))
        self.assertEqual(model.status(w, FREITAG.replace(hour=19), 90), ("knapp", 60, None))
        self.assertEqual(model.status(w, FREITAG.replace(hour=6), 90), ("zu", None, 420))
        self.assertEqual(model.status(None, FREITAG, 90), ("?", None, None))

    def test_status_ueber_mitternacht(self):
        samstag_1_uhr = FREITAG + dt.timedelta(days=1, hours=1)
        spaet = FREITAG.replace(hour=23, minute=30)
        w = model.parse_oh("Fr 18:00-02:00")
        self.assertEqual(model.status(w, samstag_1_uhr, 90), ("knapp", 60, None))  # vom Vortag über Mitternacht
        self.assertEqual(model.status(w, samstag_1_uhr, 30), ("ok", 60, None))
        self.assertEqual(model.status(w, spaet, 90), ("ok", 150, None))
        nahtlos = model.parse_oh("Fr 18:00-24:00; Sa 00:00-03:00")  # 24:00 geht nahtlos in den Samstag
        self.assertEqual(model.status(nahtlos, spaet, 90), ("ok", 210, None))
        self.assertEqual(model.status(model.parse_oh("Fr 18:00-24:00"), spaet, 90), ("knapp", 30, None))
        self.assertEqual(model.status(model.parse_oh("24/7"), spaet, 90), ("ok", 1470, None))

    def test_anzeige_je_tag(self):
        self.assertEqual(model.fmt_day(model.parse_oh("Mo-Su 07:00-20:00"), FREITAG), "7:00 bis 20:00")
        self.assertEqual(model.fmt_day(model.parse_oh("24/7"), FREITAG), "24h")
        self.assertEqual(model.fmt_day(model.parse_oh("Sa 08:00-12:00"), FREITAG), "zu")

    def test_onroutemap_format(self):
        w = model.orm_weekly({"status": "ok", "weekly": {"5": [["06:00", "22:00"]]}})
        self.assertEqual(w[4], [(360, 1320)])
        self.assertIsNone(model.orm_weekly({"status": "fehler"}))


@unittest.skipUnless(NUMPY, "numpy fehlt, mit python3.12 starten")
class Tagesgrenze(unittest.TestCase):
    """Route und Auswahl ohne Skriptlauf: route.json mit einem Punkt je km, 20 km/h, zwei Tage wie ZWEI_TAGE."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ordner = Path(self._tmp.name)
        (self.ordner / "data").mkdir()
        pts = [bei(km) + [300.0, float(km), km / 20] for km in range(121)]
        (self.ordner / "data" / "route.json").write_text(json.dumps({"pts": pts, "simple": [], "wpts": []}))
        self.cfg = dict(model.STANDARD, _ordner=str(self.ordner), tage=ZWEI_TAGE)
        self.route = model.Route(self.cfg)

    def tearDown(self):
        self._tmp.cleanup()

    def test_tage_an_der_uebernachtung(self):
        r = self.route
        self.assertEqual(r.tage[0]["km1"], 60.0)
        self.assertEqual(r.tage_bei(30), [0])
        self.assertEqual(r.tage_bei(58.1), [0, 1])
        self.assertEqual(r.tage_bei(61.9), [0, 1])
        self.assertEqual(r.tage_bei(62.1), [1])
        self.assertEqual(r.eta(59.5, 1), dt.datetime(2026, 10, 24, 5, 0))  # vor dem Start des Tages gilt die Abfahrt
        self.assertEqual(r.eta(60.5, 0).date(), dt.date(2026, 10, 23))
        self.assertEqual(r.eta(60.5).date(), dt.date(2026, 10, 24))  # ohne Tag wie bisher nach km

    def test_stopp_tag_mit_feld_tag_und_schlaf(self):
        r = self.route
        self.assertEqual(r.stopp_tag({"km": 60.4, "schlaf": True}), 0)  # Schlaf-Stopp hinter dem Zielpunkt
        self.assertEqual(r.stopp_tag({"km": 60.4}), 1)
        self.assertEqual(r.stopp_tag({"km": 60.4, "tag": 1}), 0)
        self.assertEqual(r.stopp_tag({"km": 59.0, "tag": 2}), 1)
        self.assertEqual(r.stopp_tag({"km": 30, "schlaf": True}), 0)
        self.assertEqual(r.stopp_tag({"km": 90, "schlaf": True}), 1)

    def test_auswahl_wird_geprueft(self):
        p = self.ordner / "auswahl.json"
        faelle = {
            "": "leer oder kein gültiges JSON",
            '{"stopps": []}': "keine Stopps",
            '{"stopps": [{"km": 500, "ort": "X"}]}': "nicht auf der Strecke",
            '{"stopps": [{"km": 5}]}': "ort fehlt",
            '{"stopps": [{"km": 5, "ort": "X", "optionen": [{"symbol": "kiosk"}]}]}': "unbekannt",
            '{"stopps": [{"km": 5, "ort": "X", "tag": 3}]}': "tag muss",
        }
        for text, erwartet in faelle.items():
            p.write_text(text, encoding="utf-8")
            with self.assertRaises(SystemExit) as cm:
                model.lade_auswahl(self.cfg, self.route, p)
            self.assertIn(erwartet, str(cm.exception.code), text)
        p.write_text('{"stopps": [{"km": 70, "ort": "B"}, {"km": 60.4, "kurz": "A", "schlaf": true}]}', encoding="utf-8")
        stopps = model.lade_auswahl(self.cfg, self.route, p)
        self.assertEqual([(s["ort"], s["kurz"], s["optionen"]) for s in stopps], [("A", "A", []), ("B", "B", [])])

    def test_quelle_der_oeffnungszeiten_fuer_den_sticker(self):
        g, o = {"symbol": "laden", "quelle": "google"}, {"symbol": "laden", "quelle": "osm"}
        self.assertEqual(model.zeiten_quelle([{"optionen": [g, g]}, {"optionen": []}]), "Öffnungszeiten geprüft mit Google Maps.")
        self.assertIn("einzelne nur aus OpenStreetMap", model.zeiten_quelle([{"optionen": [g, o]}]))
        self.assertNotIn("geprüft mit Google", model.zeiten_quelle([{"optionen": [{"symbol": "laden"}]}]))


@unittest.skipUnless(NUMPY, "numpy fehlt, mit python3.12 starten")
class Eingaben(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ordner = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def abbruch(self, funktion, *args):
        with self.assertRaises(SystemExit) as cm:
            funktion(*args)
        return str(cm.exception.code)

    def test_arbeitsordner_in_sync_ordnern_bricht_ab(self):
        heim = self.ordner / "heim"
        with mock.patch.object(model.Path, "home", return_value=heim):
            for teile in (("Library", "Mobile Documents", "com~apple~CloudDocs", "Downloads", "rb"),
                          ("Library", "CloudStorage", "OneDrive-Firma", "rb"),
                          ("Gruppe", "OneDrive - Firma", "rb")):
                ordner = heim.joinpath(*teile)
                self.assertIn("Sync-Ordner", self.abbruch(model.lade_config, ordner / "roadbook.json"))
                self.assertFalse(ordner.exists())  # Abbruch vor dem ersten Ordner
            # Scratchpad einer Session aus einem OneDrive-Projekt: außerhalb des Home-Ordners kein Sync-Ordner
            for frei in (self.ordner / "rb", self.ordner / "-Users-x-Library-CloudStorage-OneDrive-Firma" / "rb"):
                frei.mkdir(parents=True)
                (frei / "roadbook.json").write_text(json.dumps({"tage": ZWEI_TAGE}), encoding="utf-8")
                model.lade_config(frei / "roadbook.json")
                self.assertTrue((frei / "data" / "overpass").is_dir())

    def test_mehrtaegig_ohne_ziel_bricht_mit_einer_zeile_ab(self):
        p = self.ordner / "roadbook.json"
        p.write_text(json.dumps({"tage": [{"datum": "2026-10-23", "start": "06:00", "ende": "20:00"},
                                          {"datum": "2026-10-24", "start": "06:00", "ende": "18:00"}]}), encoding="utf-8")
        self.assertIn("oder ziel_km fehlt", self.abbruch(model.lade_config, p))
        p.write_text(json.dumps({"tage": [{"datum": "23.10.2026", "start": "06:00", "ende": "20:00"}]}), encoding="utf-8")
        self.assertIn("nicht lesbar", self.abbruch(model.lade_config, p))
        self.assertFalse((self.ordner / "data").exists())

    def test_gpx_leer_kaputt_oder_fehlend(self):
        (self.ordner / "leer.gpx").write_text(gpx([]), encoding="utf-8")
        (self.ordner / "kaputt.gpx").write_text("<gpx><trk>", encoding="utf-8")
        for name, text in (("leer.gpx", "0 Trackpunkte"), ("kaputt.gpx", "nicht lesbar"), ("fehlt.gpx", "GPX fehlt")):
            self.assertIn(text, self.abbruch(model.gpx_lesen, self.ordner / name))

    def test_gpx_zeiten_mit_und_ohne_zone(self):
        datei = self.ordner / "zeiten.gpx"
        datei.write_text(gpx(strecke(1.0), zeiten=["2026-10-23T06:00:00Z", "2026-10-23T07:00:00",
                                                   "2026-10-23T08:00:00+00:00"]), encoding="utf-8")
        pts, _ = model.gpx_lesen(datei)
        self.assertEqual([p[3] for p in pts], [0.0, 1.0, 2.0])

    def test_komoot_kurzlink_und_antwort_ohne_koordinaten(self):
        self.assertEqual(model.komoot_link("https://www.komoot.com/de-de/tour/123456?share_token=abc&ref=wtd"),
                         ("123456", "abc"))
        for link in ("https://komoot.de/r/Ab1Cd2", ""):
            self.assertIn("ohne /tour/", self.abbruch(model.komoot_link, link))
        for roh in (b'{"name": "Tour"}', b"<html>Fehler</html>", b'{"_embedded": {"coordinates": {"items": []}}}'):
            self.assertIn("Komoot-Antwort ohne Koordinaten", self.abbruch(model.komoot_punkte, roh))
        pts = model.komoot_punkte(json.dumps({"_embedded": {"coordinates": {"items": [
            {"lat": 0.0, "lng": 0.0, "alt": 10, "t": 0}, {"lat": 0.01, "lng": 0.0, "alt": 12, "t": 1800000}]}}}).encode())
        self.assertEqual(pts[1], [0.01, 0.0, 12.0, 0.5])


@unittest.skipUnless(NUMPY, "numpy fehlt, mit python3.12 starten")
class Ablauf(unittest.TestCase):
    """Die Skripte als eigener Prozess, so wie der Skill sie aufruft, mit erfundener Strecke im Temp-Ordner."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ordner = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def lauf(self, skript, code=0, args=(), path=None):
        """Skript mit roadbook.json und args, path ersetzt PATH (etwa ohne node)."""
        env = dict(os.environ, PATH=path) if path is not None else None
        r = subprocess.run([sys.executable, "-B", str(SKRIPTE / skript), str(self.ordner / "roadbook.json"), *args],
                           capture_output=True, text=True, timeout=300, env=env)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        if code:
            self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)  # Abbruch mit einer Zeile
        return r

    def roadbook(self, km=120, punkte=None, tage=ZWEI_TAGE, wegpunkte=(), **werte):
        (self.ordner / "strecke.gpx").write_text(gpx(strecke(km) if punkte is None else punkte, wegpunkte), encoding="utf-8")
        cfg = {"titel": "Testfahrt", "gpx": str(self.ordner / "strecke.gpx"), "tage": tage,
               "ignorieren_start_km": 0, "ignorieren_ende_km": 5}
        cfg.update(werte)
        (self.ordner / "roadbook.json").write_text(json.dumps(cfg), encoding="utf-8")

    def overpass(self, **dateien):
        for name, elemente in dateien.items():
            p = self.ordner / "data" / "overpass" / f"{name}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"elements": elemente}), encoding="utf-8")

    def kandidaten(self):
        self.lauf("kandidaten.py")
        return json.loads((self.ordner / "data" / "kandidaten.json").read_text(encoding="utf-8"))

    def auswahl(self, daten):
        (self.ordner / "auswahl.json").write_text(json.dumps(daten), encoding="utf-8")

    def test_laeden_an_der_uebernachtung_zaehlen_abends_und_morgens(self):
        self.roadbook()
        self.lauf("route.py")
        self.overpass(food=[ABEND, MORGEN], gapshops=[], bike=[], places=[])
        k = self.kandidaten()
        status = {(p["name"], p["tag"]): (p["status"], p["eta"][:13]) for p in k["pois"]}
        self.assertEqual(status[("Abendmarkt", 0)], ("ok", "2026-10-23T20"))  # Ankunft am Freitagabend
        self.assertEqual(status[("Abendmarkt", 1)][0], "zu")  # Samstag 5 Uhr noch zu
        self.assertEqual(status[("Morgenbäcker", 0)][0], "zu")
        self.assertEqual(status[("Morgenbäcker", 1)], ("ok", "2026-10-24T05"))  # Abfahrt am Samstagmorgen
        self.assertEqual({(o["tag"], m["name"]) for o in k["orte"] for m in o["members"]},
                         {(0, "Abendmarkt"), (1, "Morgenbäcker")})

    def test_luecken_zaehlen_nur_sicher_offene_optionen_auch_am_anfang_und_ende(self):
        self.roadbook()
        self.lauf("route.py")
        food = [ABEND, MORGEN,
                knoten(3, 25, {"shop": "supermarket", "name": "Markt Mitte", "opening_hours": "Mo-Su 07:00-22:00"}),
                knoten(4, 32, {"amenity": "fuel", "name": "Tankstelle ohne Zeiten"}),
                knoten(5, 38, {"amenity": "fast_food", "name": "Imbiss vor 17 Uhr", "opening_hours": "Mo-Su 10:00-23:00"}),
                knoten(6, 75, {"shop": "supermarket", "name": "Markt Nord", "opening_hours": "Mo-Sa 06:00-20:00"})]
        orte = [knoten(100 + i, km, {"place": "village", "name": n}, lon=0.001) for i, (km, n) in enumerate(
            [(25, "Musterhausen"), (32, "Probenheim"), (38, "Beispielstadt"), (60, "Fiktivingen"), (75, "Testdorf")])]
        self.overpass(food=food, gapshops=[], bike=[], places=orte)
        k = self.kandidaten()
        # je Tag in Fahrtrichtung: der Abendmarkt hinter dem Zielpunkt schließt die Lücke am Freitag an der Ankunft
        self.assertEqual([(lu["tag"], lu["von"], lu["bis"]) for lu in k["luecken"]],
                         [(0, 0.0, 25.0), (0, 25.0, 60.0), (1, 75.0, 115.0)])
        self.assertEqual(k["luecken"][1]["unklar"], ["Probenheim", "Beispielstadt"])
        self.assertEqual((k["luecken"][1]["zeit_von"][:2], k["luecken"][1]["zeit_bis"][:2]), ("Fr", "Fr"))
        self.assertEqual((k["luecken"][0]["von_ort"], k["luecken"][2]["bis_ort"]), ("Anfang des Roadbooks", "Ende des Roadbooks"))
        self.overpass(food=[f for f in food if f is not ABEND])  # ohne Laden am Abend endet die Lücke an der Ankunft
        self.assertEqual(self.kandidaten()["luecken"][1]["bis_ort"], "Fiktivingen (Ankunft)")

    def test_fehlende_daten_melden_sich_laut(self):
        self.roadbook()
        self.lauf("route.py")
        self.assertIn("food.json fehlt", self.lauf("kandidaten.py", code=1).stderr)
        self.overpass(food=[ABEND])
        r = self.lauf("kandidaten.py")
        for name in ("gapshops.json", "bike.json", "places.json"):
            self.assertIn(f"WARNUNG: {name} fehlt", r.stdout)

    def test_route_mit_leerer_gpx_und_ohne_ziel_bricht_mit_einer_zeile_ab(self):
        self.roadbook(punkte=[])
        self.assertIn("Trackpunkte", self.lauf("route.py", code=1).stderr)
        self.roadbook(tage=[{"datum": "2026-10-23", "start": "10:00", "ende": "20:00"}, ZWEI_TAGE[1]])
        self.assertIn("oder ziel_km fehlt", self.lauf("route.py", code=1).stderr)

    def test_namen_bricht_bei_kaputtem_punkt_oder_cache_mit_einer_zeile_ab(self):
        """V3.1.2: Ein Zusatzpunkt ohne Breite,Länge oder ein kaputter Cache endeten mit Traceback. Jetzt eine Zeile,
        vor dem ersten Abruf bei Nominatim."""
        self.roadbook()
        self.assertIn("'Musterhausen' nicht lesbar", self.lauf("namen.py", code=1, args=["0.1,0", "Musterhausen"]).stderr)
        (self.ordner / "data" / "names.json").write_text("{", encoding="utf-8")
        self.assertIn("löschen und namen.py neu laufen lassen", self.lauf("namen.py", code=1).stderr)

    def test_wegpunkte_bei_mehreren_durchfahrten_mit_allen_km(self):
        hin = strecke(30)
        self.roadbook(punkte=hin + hin[-2::-1], tage=[{"datum": "2026-10-23", "start": "08:00", "ende": "12:00"}],
                      wegpunkte=[(*bei(10), "Kontrolle"), (*bei(29.5, 0.02), "Abseits")])
        r = self.lauf("route.py")
        wpts = {w["name"]: w for w in json.loads((self.ordner / "data" / "route.json").read_text())["wpts"]}
        self.assertEqual([round(k) for k in wpts["Kontrolle"]["kms"]], [10, 50])  # hin und zurück
        self.assertIn("Kontrolle: 2 Durchfahrten", r.stdout)
        self.assertIn("m neben der Strecke", r.stdout)

    def test_pruefliste_mit_dem_dokumentierten_beispiel(self):
        # das Beispiel steht seit V4.1 in der Referenz, nicht mehr im Skill
        text = (SKILL / "references" / "dateien-und-fallstricke.md").read_text(encoding="utf-8")
        beispiel = json.loads(next(b for b in re.findall(r"```json\n(.*?)```", text, re.S) if '"stopps"' in b))
        schlaf = next(s for s in beispiel["stopps"] if s.get("schlaf"))
        # Zielpunkt des ersten Tages 200 m vor dem Schlaf-Stopp, so wie route.py ein Ziel auf die Strecke legen kann
        self.roadbook(km=max(s["km"] for s in beispiel["stopps"]) + 20,
                      tage=[{"datum": "2026-10-23", "start": "06:30", "ende": "22:30", "ziel_km": round(schlaf["km"] - 0.2, 1)},
                            {"datum": "2026-10-24", "start": "04:00", "ende": "20:00"}])
        self.lauf("route.py")
        self.auswahl(beispiel)
        zeilen = self.lauf("pruefliste.py").stdout.splitlines()
        for s in beispiel["stopps"]:
            self.assertTrue(any(s["ort"] in z for z in zeilen), s["ort"])
        self.assertIn("| Fr ", next(z for z in zeilen if schlaf["ort"] in z))  # bleibt am Freitagabend
        for s in beispiel["stopps"]:  # ohne Adresse und Zeiten
            for o in s["optionen"]:
                o.pop("adresse", None)
                o.pop("zeiten", None)
        self.auswahl(beispiel)
        self.lauf("pruefliste.py")

    @unittest.skipUnless(RENDER, "Pillow, reportlab oder die Schriften von macOS fehlen")
    def test_render_bricht_bei_unbekanntem_iphone_und_leerer_auswahl_ab(self):
        self.roadbook(iphone="iPhone 99")
        self.assertIn("iphone_px", self.lauf("render.py", code=1).stderr)
        self.roadbook()
        self.lauf("route.py")
        (self.ordner / "auswahl.json").write_text("", encoding="utf-8")
        self.assertIn("auswahl.json", self.lauf("render.py", code=1).stderr)
        self.auswahl({"stopps": [{"km": 25, "ort": "Musterhausen", "optionen": [{"symbol": "laden"}]}]})
        leer = self.ordner / "ohne-node"
        leer.mkdir()
        self.assertIn("node fehlt", self.lauf("render.py", code=1, path=str(leer)).stderr)  # V3.1.2: kein Traceback

    @unittest.skipUnless(RENDER, "Pillow, reportlab oder die Schriften von macOS fehlen")
    def test_render_endfassung_nennt_die_quelle_der_oeffnungszeiten(self):
        from PIL import Image
        self.roadbook(iphone="Testphone", iphone_px=[402, 874])
        self.lauf("route.py")
        icons = self.ordner / "out" / "icons"
        for name in ("laden", "baecker", "tanke", "automat", "imbiss", "rad", "umweg", "schlaf"):  # ohne node
            Image.new("RGBA", (64, 64), (0, 0, 0, 255)).save(icons / f"{name}.png")
        self.auswahl({"stopps": [
            {"km": 25, "ort": "Musterhausen", "optionen": [{"symbol": "laden", "name": "Markt Mitte", "quelle": "google"}]},
            {"km": 60.4, "ort": "Fiktivingen", "wichtig": "Abendessen und Schlafen", "schlaf": True,
             "optionen": [{"symbol": "laden", "name": "Abendmarkt", "quelle": "osm"}]},
            {"km": 75, "ort": "Testdorf", "umweg_m": 300, "optionen": [{"symbol": "baecker", "name": "Morgenbäcker"}]}]})
        r = self.lauf("render.py")
        self.assertIn("Sticker: Öffnungszeiten mit Google Maps geprüft, einzelne nur aus OpenStreetMap.", r.stdout)
        self.assertEqual(len(list((self.ordner / "out").glob("Testfahrt-Sticker-*.pdf"))), 1)
        self.assertEqual(len(list((self.ordner / "out").glob("Testfahrt-Wallpaper-Testphone.png"))), 1)


if __name__ == "__main__":
    unittest.main()
