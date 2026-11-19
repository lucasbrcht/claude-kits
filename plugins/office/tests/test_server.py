"""Tests für den MCP-Server office (8.0): Zuschnitt und eigene Obergrenze der Werkzeuge, Argumente an ablage.py,
sprache.py, office.py und die Motor-Skripte, Übertragen nur nach dem Dialog mit dem Hinweis auf geteilte Ordner, Umzug
aus apple 7.3, Sandbox-Profil des Motors und der Motor mit echten Skripten (python3.12 mit python-pptx und openpyxl,
sonst übersprungen). sandbox-exec ersetzt dabei ein Skript (hilfe.sandbox_ersatz), alle Dateien sind erfunden.

Aufruf im Plugin-Ordner: python3 -B -m unittest discover tests
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hilfe  # noqa: E402
import mcp_basis as mb  # noqa: E402
import server  # noqa: E402

# Werkzeuge des Servers office allein, getrennt von der Grenze über apple und chat (Plan 8.0): 3 in der Grundstufe,
# 7 mit dem Motor (folien_finden, folien_lesen, folien_pruefen, folien_aendern, excel_skript, excel_fertig,
# office_vorschau), Entscheidung des Betreuers vom 19.11.2026
GRENZE_OFFICE = 10
# Je Skript, was nur ein Werkzeug der Stufe nachfrage übergeben darf
VERBOTEN_OHNE_NACHFRAGE = {"ablage.py": ("--ausfuehren",), "sprache.py": ("--ausfuehren",),
                           "office.py": ("--ausfuehren",)}
NACHFRAGE = {"arbeitskopie_uebertragen"}
GRUND = {"arbeitskopie", "arbeitskopie_uebertragen", "sprache"}
MOTOR = {"folien_finden", "folien_lesen", "folien_pruefen", "folien_aendern", "excel_skript", "excel_fertig",
         "office_vorschau"}
LESEN = {"folien_finden", "folien_lesen", "folien_pruefen"}


class Aufnahme:
    """Ersatz für server.lauf: merkt die Aufrufe, herkunft liefert eine Arbeitskopie im Thema T."""

    def __init__(self, ablage: Path = Path("/a")):
        self.aufrufe, self.ablage = [], ablage

    def __call__(self, skript, argumente, zeit=mb.ZEIT_STANDARD, textdateien=None):
        self.aufrufe.append((skript, list(argumente), dict(textdateien or {})))
        if skript == "ablage.py" and argumente[:1] == ["herkunft"]:
            datei = argumente[-1]
            return 0, f"Arbeitskopie: {self.ablage / 'T' / datei}\nOriginal: /o/{datei}\nGeholt: heute"
        return 0, "ok"


def werkzeug_liste(**umgebung) -> list:
    with tempfile.TemporaryDirectory() as t:
        (Path(t) / "config.json").write_text("{}")
        env = {**os.environ, mb.UMGEBUNG: t, "KITS_NUR_LESEN": "", **umgebung}
        eingabe = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
        aus = subprocess.run([sys.executable, "-B", str(PLUGIN / "server.py")], input=eingabe,
                             capture_output=True, text=True, timeout=20, env=env)
    return json.loads(aus.stdout.splitlines()[0])["result"]["tools"]


class Zuschnitt(unittest.TestCase):
    def test_werkzeuge_und_grenzen(self):
        for w in server.WERKZEUGE:
            liste = w.liste()
            self.assertRegex(w.name, r"^[a-z_]{3,64}$")
            self.assertLessEqual(len(w.beschreibung), mb.BESCHREIBUNG_MAX, w.name)
            self.assertTrue(liste["annotations"]["title"])
            self.assertFalse(liste["inputSchema"]["additionalProperties"])
            self.assertLessEqual(set(liste["inputSchema"].get("required", [])), set(w.eigenschaften), w.name)
            self.assertNotRegex(w.name, r"loesch|lösch|delete|verwerf|discard|entfern")

    def test_eigene_obergrenze(self):
        namen = {w["name"] for w in werkzeug_liste()}
        self.assertEqual(namen, GRUND | MOTOR)
        self.assertLessEqual(len(namen), GRENZE_OFFICE)
        self.assertEqual({w.name for w in server.WERKZEUGE if w.stufe == "lesen"}, LESEN)

    def test_beschreibungen_ohne_sonderzeichen(self):
        for w in server.WERKZEUGE:
            texte = [w.beschreibung, w.titel] + [str(e.get("description", "")) for e in w.eigenschaften.values()]
            for t in texte:
                for zeichen in ("—", "–", "…", ";"):
                    self.assertNotIn(zeichen, t, w.name)

    def test_stufe_passt_zur_annotation(self):
        for w in server.WERKZEUGE:
            a = w.annotationen()
            self.assertEqual(a["readOnlyHint"], w.stufe == "lesen", w.name)
            self.assertEqual(a["destructiveHint"], w.stufe == "nachfrage", w.name)
        self.assertEqual({w.name for w in server.WERKZEUGE if w.stufe == "nachfrage"}, NACHFRAGE)

    def test_modus_lesen_ohne_schreiben(self):
        # die Grundstufe hat kein Werkzeug zum Lesen, nur finden, lesen und prüfen von Decks bleiben
        self.assertEqual({w["name"] for w in werkzeug_liste(KITS_NUR_LESEN="1")}, LESEN)


class Argumente(unittest.TestCase):
    def setUp(self):
        self.auf = Aufnahme()
        for p in (mock.patch.object(server, "lauf", self.auf),
                  mock.patch.dict(os.environ, {"KITS_DIALOG": "ja"})):  # Dialog vor der Stufe nachfrage gilt als frei
            p.start()
            self.addCleanup(p.stop)

    def rufe(self, name, args):
        self.auf.aufrufe.clear()
        fehler, aus = mb.Server("office", "t", server.WERKZEUGE).aufrufen(name, args)
        return fehler, aus, (self.auf.aufrufe[-1] if self.auf.aufrufe else None)

    def test_arbeitskopie(self):
        self.assertEqual(self.rufe("arbeitskopie", {"aktion": "liste"})[2][:2], ("ablage.py", ["liste"]))
        self.assertEqual(self.rufe("arbeitskopie", {"aktion": "holen", "bereich": "privat", "thema": "Reise",
                                                    "pfad": "/sessions/a/mnt/Docs/x.docx"})[2][1],
                         ["holen", "--bereich=privat", "--thema=Reise", "--", "/sessions/a/mnt/Docs/x.docx"])
        self.assertEqual(self.rufe("arbeitskopie", {"aktion": "zeigen", "bereich": "arbeit", "thema": "T",
                                                    "datei": "a.pptx", "finder": True})[2][1],
                         ["zeigen", "--finder", "--bereich=arbeit", "--thema=T", "--", "a.pptx"])
        self.assertEqual(self.rufe("arbeitskopie", {"aktion": "zeigen", "pfad": "/x/a.pdf"})[2][1],
                         ["zeigen", "--", "/x/a.pdf"])
        for falsch in ({"aktion": "holen", "bereich": "arbeit", "thema": "T"},
                       {"aktion": "holen", "bereich": "firma", "thema": "T", "pfad": "/x"},
                       {"aktion": "uebertragen"}):
            self.assertTrue(self.rufe("arbeitskopie", falsch)[0], falsch)
        _f, _a, (skript, argv, _) = self.rufe("arbeitskopie_uebertragen",
                                              {"bereich": "arbeit", "thema": "T", "datei": "a.pptx"})
        self.assertEqual(argv, ["--ausfuehren", "uebertragen", "--bereich=arbeit", "--thema=T", "--", "a.pptx"])

    def test_sprache(self):
        self.assertEqual(self.rufe("sprache", {"bereich": "arbeit", "thema": "T", "datei": "a.pptx"})[2][:2],
                         ("sprache.py", ["--bereich=arbeit", "--thema=T", "--", "a.pptx"]))
        self.assertEqual(self.rufe("sprache", {"pfad": "/sessions/a/mnt/Downloads/Claude Work/T/a.pptx",
                                               "sprache": "en-US", "pruefen": True})[2][1],
                         ["--sprache=en-US", "--pruefen", "--", "/sessions/a/mnt/Downloads/Claude Work/T/a.pptx"])
        for falsch in ({}, {"bereich": "arbeit", "thema": "T"}, {"datei": "a.pptx"},
                       {"pfad": "/x/a.pptx", "sprache": "--ausfuehren"}, {"pfad": "/x/a.pptx", "sprache": "deutsch"}):
            fehler, _aus, aufruf = self.rufe("sprache", falsch)
            self.assertTrue(fehler, falsch)
            self.assertIsNone(aufruf, falsch)

    def test_ohne_nachfrage_nie_ausfuehren(self):
        beispiele = {
            "arbeitskopie": {"aktion": "holen", "bereich": "arbeit", "thema": "--ausfuehren", "pfad": "--ausfuehren",
                             "neu": True},
            "sprache": {"bereich": "arbeit", "thema": "--ausfuehren", "datei": "--ausfuehren"},
            "folien_finden": {"begriffe": ["--ausfuehren"], "ordner": "/tmp"},
            "folien_lesen": {"datei": "/x/--ausfuehren.pptx"},
            "folien_pruefen": {"datei": "/x/a.pptx", "original": "/x/--ausfuehren.pptx"},
            "folien_aendern": {"bereich": "arbeit", "thema": "--ausfuehren", "datei": "a.pptx",
                               "liste": {"aenderungen": []}},
            "excel_skript": {"bereich": "arbeit", "thema": "--ausfuehren", "datei": "a.xlsx", "code": "print(1)"},
            "excel_fertig": {"bereich": "arbeit", "thema": "--ausfuehren", "datei": "a.xlsx", "nachrechnen": True},
            "office_vorschau": {"bereich": "arbeit", "thema": "--ausfuehren", "datei": "--ausfuehren.pptx",
                                "seiten": "1"}}
        motor = []
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, {mb.UMGEBUNG: t}), \
                mock.patch.object(server, "motor", lambda datei, args, zeit=0: (motor.append(list(args)), (0, "ok"))[1]):
            (Path(t) / "config.json").write_text("{}")
            for w in server.WERKZEUGE:
                if w.stufe == "nachfrage":
                    continue
                self.assertIn(w.name, beispiele)
                self.auf.aufrufe.clear()
                fehler, aus = mb.Server("office", "t", server.WERKZEUGE).aufrufen(w.name, beispiele[w.name])
                self.assertFalse(fehler, f"{w.name}: {aus}")
                for skript, argv, _ in self.auf.aufrufe:
                    vor_trenner = argv[:argv.index("--")] if "--" in argv else argv
                    for wort in VERBOTEN_OHNE_NACHFRAGE.get(skript, ()):
                        self.assertNotIn(wort, vor_trenner, w.name)
        self.assertTrue(motor)  # die Motor-Werkzeuge liefen bis zum Motor durch

    def test_uebertragen_ohne_dialog_nie(self):
        with mock.patch.dict(os.environ, {"KITS_DIALOG": "nein"}):
            fehler, aus, aufruf = self.rufe("arbeitskopie_uebertragen",
                                            {"bereich": "arbeit", "thema": "T", "datei": "a.pptx"})
        self.assertTrue(fehler)
        self.assertNotIn("--ausfuehren", [a for _s, argv, _t in self.auf.aufrufe for a in argv])
        self.assertIn("Nicht ausgeführt", aus)

    def test_uebertragen_vorschau(self):
        with mock.patch.object(server, "lauf", lambda *a, **k: (0, "Arbeitskopie: /a/T/a.pptx\n"
                                                                     "Original: /cloud/Team/Vertrieb/a.pptx")):
            text = server.uebertragen_vorschau({"bereich": "arbeit", "thema": "T", "datei": "a.pptx"})
        self.assertEqual(text, "Datei: a.pptx\nNach: Vertrieb\nThema: T\nErsetzt den Inhalt des Originals, andere sehen es")

    def test_uebertragen_vorschau_geteilter_ordner(self):
        args = {"bereich": "arbeit", "thema": "T", "datei": "a.pptx"}
        for original in ("/Users/x/Library/CloudStorage/OneDrive-Firma/Team/a.pptx",
                         "/Users/x/Library/CloudStorage/SharePoint-Bibliothek/Team/a.pptx",
                         "/Users/x/OneDrive - Firma/Team/a.pptx"):
            with self.subTest(original=original), mock.patch.object(
                    server, "lauf", lambda *a, o=original, **k: (0, f"Arbeitskopie: /a/T/a.pptx\nOriginal: {o}")):
                text = server.uebertragen_vorschau(args)
            self.assertEqual(text.splitlines()[-1], "Achtung: Shared Folder")
            self.assertIn("Nach: Team", text)
        for original in ("/Users/x/Library/Mobile Documents/com~apple~CloudDocs/Team/a.pptx", "/Users/x/Dokumente/a.pptx"):
            with self.subTest(original=original), mock.patch.object(
                    server, "lauf", lambda *a, o=original, **k: (0, f"Arbeitskopie: /a/T/a.pptx\nOriginal: {o}")):
                self.assertNotIn("Shared Folder", server.uebertragen_vorschau(args))
        with mock.patch.object(server, "lauf", lambda *a, **k: (1, "")):
            self.assertNotIn("Shared Folder", server.uebertragen_vorschau(args))

    def test_hinweis_im_dialog(self):
        """Der Text des Dialogs am Mac trägt die Zeile Achtung: Shared Folder."""
        gezeigt = []
        with mock.patch.object(server, "lauf", lambda *a, **k: (0, "Original: /Users/x/Library/CloudStorage/OD/a.pptx")), \
                mock.patch.object(mb, "bestaetigen", lambda t: (gezeigt.append(t), (False, "abgelehnt"))[1]):
            fehler, _aus = mb.Server("office", "t", server.WERKZEUGE).aufrufen(
                "arbeitskopie_uebertragen", {"bereich": "arbeit", "thema": "T", "datei": "a.pptx"})
        self.assertTrue(fehler)
        self.assertIn("Achtung: Shared Folder", gezeigt[0])


class Umzug(unittest.TestCase):
    """8.0: Fehlt ablage in der config.json von office, übernimmt der Server Abschnitt und Dateien aus apple 7.3."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        wurzel = Path(tmp.name)
        self.apple, self.office = wurzel / "apple", wurzel / "office"
        (self.apple / "ablage-sicherung" / "abc123").mkdir(parents=True)
        (self.apple / "config.json").write_text(json.dumps(
            {"mail": {"accounts": ["Privat"]},
             "ablage": {"_hinweis": "alt", "privat": "~/Downloads/Claude Personal", "arbeit": "~/Downloads/Claude Work"}}))
        (self.apple / "ablage.json").write_text('{"kopien": {"/k/T/a.pptx": {"original": "/o/a.pptx"}}}')
        (self.apple / "ablage-sicherung" / "abc123" / "a.pptx").write_bytes(b"PK alt")
        (self.apple / "ablage-sicherung" / "verweis").symlink_to(self.apple / "config.json")

    def test_erster_start_uebernimmt(self):
        meldung = server.umzug(self.office, self.apple)
        self.assertIn("ablage", meldung)
        cfg = json.loads((self.office / "config.json").read_text())
        self.assertEqual(cfg, {"ablage": {"privat": "~/Downloads/Claude Personal", "arbeit": "~/Downloads/Claude Work"}})
        self.assertEqual((self.office / "ablage.json").read_text(), (self.apple / "ablage.json").read_text())
        self.assertEqual((self.office / "ablage-sicherung" / "abc123" / "a.pptx").read_bytes(), b"PK alt")
        self.assertFalse((self.office / "ablage-sicherung" / "verweis").exists())  # Verweise bleiben liegen
        self.assertTrue((self.apple / "ablage.json").is_file())  # apple behält seine Dateien, nichts gelöscht
        self.assertEqual(server.umzug(self.office, self.apple), "")  # danach nur noch eigene Dateien

    def test_eigene_einstellungen_bleiben(self):
        (self.office / "ablage-sicherung").mkdir(parents=True)
        (self.office / "config.json").write_text(json.dumps({"motor": {"aus": True}}))
        (self.office / "ablage.json").write_text('{"kopien": {}}')
        server.umzug(self.office, self.apple)
        cfg = json.loads((self.office / "config.json").read_text())
        self.assertEqual(cfg["motor"], {"aus": True})
        self.assertIn("ablage", cfg)
        self.assertEqual((self.office / "ablage.json").read_text(), '{"kopien": {}}')  # Vorhandenes bleibt
        (self.office / "config.json").write_text(json.dumps({"ablage": {"privat": "/eigen"}}))
        self.assertEqual(server.umzug(self.office, self.apple), "")
        self.assertEqual(json.loads((self.office / "config.json").read_text()), {"ablage": {"privat": "/eigen"}})

    def test_nichts_zu_tun(self):
        (self.apple / "config.json").write_text(json.dumps({"mail": {}}))
        self.assertEqual(server.umzug(self.office, self.apple), "")
        self.assertFalse(self.office.exists())
        self.office.mkdir()
        (self.office / "config.json").write_text("{kaputt")
        (self.apple / "config.json").write_text(json.dumps({"ablage": {"privat": "/p"}}))
        self.assertEqual(server.umzug(self.office, self.apple), "")
        self.assertEqual((self.office / "config.json").read_text(), "{kaputt")

    def test_tests_beruehren_nie_echte_ordner(self):
        with mock.patch.dict(os.environ, {mb.UMGEBUNG: str(self.office)}):
            self.assertEqual(server.umzug(), "")
        self.assertFalse(self.office.exists())


class MotorBasis(unittest.TestCase):
    """Temp-Datenordner mit config.json und Ablage, server.lauf liefert die Herkunft aus Aufnahme."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.daten, self.ablage, self.such = self.tmp / "daten", self.tmp / "Ablage" / "Claude Work", self.tmp / "Such"
        for o in (self.daten, self.ablage / "T", self.such):
            o.mkdir(parents=True)
        self.cfg = {"ablage": {"arbeit": str(self.ablage)}, "suche": {"ordner": [str(self.such), "/gibt/es/nicht"]},
                    "motor": {"gesperrt": ["~/Kontext", "/Volumes/Geheim"], "pptx_validate": "/x/validate.py"}}
        (self.daten / "config.json").write_text(json.dumps(self.cfg))
        self.auf = Aufnahme(self.ablage)
        for p in (mock.patch.dict(os.environ, {mb.UMGEBUNG: str(self.daten), "KITS_DIALOG": "nein",
                                               "KITS_FEHLERPROTOKOLL": "aus"}),
                  mock.patch.object(server, "lauf", self.auf)):
            p.start()
            self.addCleanup(p.stop)

    def rufe(self, name, args):
        return mb.Server("office", "t", server.WERKZEUGE).ausfuehren(name, args)


class MotorArgumente(MotorBasis):
    def setUp(self):
        super().setUp()
        self.motor = []
        p = mock.patch.object(server, "motor", lambda datei, args, zeit=120: (
            self.motor.append((Path(datei).name, list(args))), (0, "ok"))[1])
        p.start()
        self.addCleanup(p.stop)

    def test_finden_mit_suchordnern_oder_ordner(self):
        self.assertFalse(self.rufe("folien_finden", {"begriffe": ["status", "q4"], "inhalt": True})[0])
        self.assertEqual(self.motor, [("finden.py", ["status", "q4", "--inhalt", "--ordner", str(self.such)])])
        self.motor.clear()
        self.rufe("folien_finden", {"begriffe": ["x"], "ordner": str(self.tmp)})
        self.assertEqual(self.motor, [("finden.py", ["x", "--ordner", str(self.tmp)])])
        self.cfg["suche"] = {"ordner": ["/gibt/es/nicht"]}
        (self.daten / "config.json").write_text(json.dumps(self.cfg))
        fehler, aus, _ = self.rufe("folien_finden", {"begriffe": ["x"]})
        self.assertTrue(fehler)
        self.assertIn("suche.ordner", aus)
        for falsch in ({"begriffe": []}, {"begriffe": ["x"], "ordner": "relativ"},
                       {"begriffe": ["x"], "ordner": "/sessions/a/mnt/Docs"}):
            self.assertTrue(self.rufe("folien_finden", falsch)[0], falsch)

    def test_lesen_und_pruefen(self):
        self.rufe("folien_lesen", {"datei": "/x/Deck.pptx", "uebersicht": True, "folien": "2-4, 7", "voll": True})
        self.assertEqual(self.motor[-1], ("lesen.py", ["/x/Deck.pptx", "--folie", "2-4,7", "--uebersicht", "--voll"]))
        self.rufe("folien_pruefen", {"datei": "/x/a.pptx", "original": "/y/a.pptx"})
        self.assertEqual(self.motor[-1], ("pruefen.py", ["/x/a.pptx", "--original", "/y/a.pptx"]))
        for name, falsch in (("folien_lesen", {"datei": "/x/a.xlsx"}), ("folien_lesen", {"datei": "/x/a.pptx",
                                                                                          "folien": "1;rm"}),
                             ("folien_lesen", {"datei": "/sessions/x/mnt/a.pptx"}), ("folien_pruefen", {})):
            self.motor.clear()
            self.assertTrue(self.rufe(name, falsch)[0], falsch)
            self.assertEqual(self.motor, [])

    def test_aendern_mit_herkunft_liste_und_skript(self):
        fehler, aus, _ = self.rufe("folien_aendern", {
            "bereich": "arbeit", "thema": "T", "datei": "Deck.pptx", "vergleich": True,
            "skript": "def umbau(prs):\n    pass\n",
            "liste": {"original": "/woanders/x.pptx", "aenderungen": [{"art": "skript", "datei": "/etc/passwd"}]}})
        self.assertFalse(fehler, aus)
        self.assertEqual(self.auf.aufrufe[0][:2], ("ablage.py", ["herkunft", "--bereich=arbeit", "--thema=T", "--",
                                                                 "Deck.pptx"]))
        name, args = self.motor[-1]
        kopie = str(self.ablage / "T" / "Deck.pptx")
        self.assertEqual((name, args[:7]), ("aendern.py", ["--original", "/o/Deck.pptx", "--ziel", kopie, "--zustand",
                                                           str(self.daten / "zwischen" / "zustand"), "--vergleich"]))
        liste = json.loads(Path(args[-1]).read_text())
        self.assertEqual(list(liste), ["aenderungen"])  # das Original kommt aus der Herkunft, nie aus der Liste
        umbau = Path(liste["aenderungen"][0]["datei"])
        self.assertEqual(umbau.parent, self.daten / "zwischen" / "listen")
        self.assertIn("def umbau", umbau.read_text())

    def test_aendern_grenzen(self):
        basis = {"bereich": "arbeit", "thema": "T", "datei": "Deck.pptx"}
        (self.ablage / "T" / "~$Deck.pptx").write_text("")
        fehler, aus, _ = self.rufe("folien_aendern", {**basis, "liste": {"aenderungen": []}})
        self.assertIn("in PowerPoint offen", aus)
        (self.ablage / "T" / "~$Deck.pptx").unlink()
        for falsch in ({**basis, "liste": {"aenderungen": [{"art": "skript"}]}},
                       {**basis, "liste": []}, {**basis, "datei": "Mappe.xlsx", "liste": {"aenderungen": []}},
                       {**basis, "skript": "", "liste": {"aenderungen": []}}):
            self.assertTrue(self.rufe("folien_aendern", falsch)[0], falsch)
        self.assertEqual(self.motor, [])
        with mock.patch.object(server, "lauf", lambda *a, **k: (1, "Mappe.pptx gibt es in T nicht als Datei.")):
            fehler, aus, _ = self.rufe("folien_aendern", {**basis, "liste": {"aenderungen": []}})
        self.assertTrue(fehler)
        self.assertIn("Erst mit arbeitskopie holen", aus)

    def test_excel(self):
        args = {"bereich": "arbeit", "thema": "T", "datei": "Liste.xlsx"}
        self.assertFalse(self.rufe("excel_skript", {**args, "code": "import sys\nprint(sys.argv[1])"})[0])
        name, argv = self.motor[-1]
        self.assertTrue(name.startswith("Liste-") and name.endswith("_excel.py"), name)
        self.assertEqual(argv, [str(self.ablage / "T" / "Liste.xlsx")])
        self.assertFalse(self.rufe("excel_fertig", {**args, "nachrechnen": True})[0])
        self.assertEqual(self.auf.aufrufe[-1][:2], ("office.py", ["nachrechnen", "--bereich=arbeit", "--thema=T", "--",
                                                                  "Liste.xlsx"]))
        self.assertEqual(self.motor[-1], ("excel.py", ["fertig", str(self.ablage / "T" / "Liste.xlsx"), "--original",
                                                       "/o/Liste.xlsx"]))
        (self.ablage / "T" / "~$Liste.xlsx").write_text("")
        self.assertIn("in Excel offen", self.rufe("excel_skript", {**args, "code": "x"})[1])
        self.assertTrue(self.rufe("excel_skript", {**args, "datei": "Deck.pptx", "code": "x"})[0])

    def test_nachrechnen_mit_fehlern_haelt_an(self):
        with mock.patch.object(server, "lauf", lambda s, a, **k: (
                (0, "Arbeitskopie: /a/T/L.xlsx\nOriginal: /o/L.xlsx") if a[0] == "herkunft" else (1, "Liste!A3: #DIV/0!"))):
            fehler, aus, _ = self.rufe("excel_fertig", {"bereich": "arbeit", "thema": "T", "datei": "L.xlsx",
                                                        "nachrechnen": True})
        self.assertTrue(fehler)
        self.assertIn("#DIV/0!", aus)
        self.assertEqual(self.motor, [])

    def test_vorschau_mit_bildern(self):
        bild = self.tmp / "Deck-2.png"
        bild.write_bytes(b"\x89PNG\r\n\x1a\nxx")
        with mock.patch.object(server, "lauf", lambda s, a, **k: (
                self.auf.aufrufe.append((s, a, {})), (0, f"PDF: /z/Deck.pdf\nSeite 2: {bild}\nSeite 9: kein Bild"))[1]):
            fehler, aus, bilder = self.rufe("office_vorschau", {"bereich": "arbeit", "thema": "T", "datei": "Deck.pptx",
                                                                "seiten": "2, 9"})
        self.assertFalse(fehler)
        self.assertEqual(bilder, [str(bild)])
        self.assertEqual(self.auf.aufrufe[-1][:2], ("office.py", ["pdf", "--bereich=arbeit", "--thema=T",
                                                                  "--seiten=2,9", "--", "Deck.pptx"]))
        self.assertTrue(self.rufe("office_vorschau", {"bereich": "arbeit", "thema": "T", "datei": "a.pptx",
                                                      "seiten": "1;2"})[0])


class Sandbox(MotorBasis):
    def test_profil_des_motors(self):
        z = server.zwischenordner(self.daten)
        profil = server.sandbox_profil(self.cfg, z)
        zeilen = profil.splitlines()
        self.assertEqual(zeilen[:4], ["(version 1)", "(allow default)", "(deny network*)", "(deny file-write*)"])
        for ort in (os.path.realpath(str(z)), "/private/var/folders", os.path.realpath(str(self.ablage))):
            self.assertIn(f'(allow file-write* (subpath "{ort}"))', zeilen)
        for ort in (mb.HEIM / "Library/Mail", mb.HEIM / "Library/Keychains", mb.HEIM / "Kontext", "/Volumes/Geheim",
                    mb.APP_DATEN / "apple", mb.APP_DATEN / "chat"):
            self.assertIn(f'(deny file-read* file-write* (subpath "{ort}"))', zeilen)
        self.assertIn(f'(deny file-read* file-write* (regex #"^{mb.HEIM}/Library/Group Containers/group\\.net\\.'
                      'whatsapp\\.[^/]*(/|$)"))', zeilen)
        self.assertNotIn(str(mb.APP_DATEN / "office"), profil)  # die .venv bleibt lesbar
        letzte_erlaubnis = max(i for i, z_ in enumerate(zeilen) if z_.startswith("(allow file-write*"))
        self.assertLess(letzte_erlaubnis, min(i for i, z_ in enumerate(zeilen) if z_.startswith("(deny file-read*")))
        self.assertEqual(hilfe.profil_uebersetzt(profil), "")

    def test_falsche_sperren_brechen_ab(self):
        for falsch in ({"gesperrt": "~/x"}, {"gesperrt": ["relativ"]}, {"gesperrt": ["/a/../b"]}, "kein Objekt"):
            with self.assertRaises(mb.Fehler, msg=falsch):
                server.sandbox_profil({"motor": falsch}, self.tmp)

    def test_zwischenordner_ohne_verweise(self):
        ziel = self.tmp / "woanders"
        ziel.mkdir()
        (self.daten / "zwischen").symlink_to(ziel)
        with self.assertRaises(mb.Fehler):
            server.zwischenordner(self.daten)

    def test_ohne_motor_ein_hinweis(self):
        fehler, aus, _ = self.rufe("folien_lesen", {"datei": "/x/a.pptx"})
        self.assertTrue(fehler)
        self.assertIn("Motor nicht eingerichtet", aus)
        self.assertIn("python-pptx openpyxl lxml", aus)

    def test_ohne_sandbox_laeuft_nichts(self):
        py = self.daten / ".venv" / "bin" / "python3"
        py.parent.mkdir(parents=True)
        py.write_text("#!/bin/sh\necho lief\n")
        py.chmod(0o755)
        falsch = self.tmp / "sandbox-exec"
        falsch.write_text("#!/bin/sh\necho 'sandbox-exec: sandbox_apply: Operation not permitted' >&2\nexit 71\n")
        falsch.chmod(0o755)
        with mock.patch.object(server, "SANDBOX_EXEC", str(falsch)):
            code, aus = server.motor(server.MOTOR / "lesen.py", ["/x/a.pptx"])
        self.assertEqual(code, 1)
        self.assertIn("Sandbox nicht verfügbar", aus)
        self.assertNotIn("lief", aus.split("?")[0])


@unittest.skipUnless(hilfe.motor_python(), "python3.12 mit python-pptx und openpyxl fehlt")
class MotorEcht(MotorBasis):
    """Werkzeuge mit den echten Motor-Skripten, sandbox-exec ersetzt."""

    def setUp(self):
        super().setUp()
        hilfe.venv_ersatz(self.daten)
        self.sandbox = hilfe.sandbox_ersatz(self.tmp / "bin")
        p = mock.patch.object(server, "SANDBOX_EXEC", str(self.sandbox))
        p.start()
        self.addCleanup(p.stop)
        self.quelle = self.tmp / "Quelle"
        self.quelle.mkdir()
        self.original = hilfe.erzeuge(hilfe.DECK, self.quelle / "Status.pptx")
        self.kopie = self.ablage / "T" / "Status.pptx"
        shutil.copy(self.original, self.kopie)  # wie arbeitskopie holen
        self.auf_echt = lambda s, a, **k: (0, f"Arbeitskopie: {self.ablage / 'T' / a[-1]}\n"
                                              f"Original: {self.quelle / a[-1]}")
        p = mock.patch.object(server, "lauf", self.auf_echt)
        p.start()
        self.addCleanup(p.stop)

    def test_lesen_aendern_und_runde(self):
        fehler, aus, _ = self.rufe("folien_lesen", {"datei": str(self.kopie), "uebersicht": True})
        self.assertFalse(fehler, aus)
        self.assertIn("1 Test Titel", aus)
        vorher = self.original.read_bytes()
        args = {"bereich": "arbeit", "thema": "T", "datei": "Status.pptx",
                "liste": {"aenderungen": [{"art": "text", "folie": 1, "alt": "Punkt alt", "neu": "Punkt neu"}]}}
        fehler, aus, _ = self.rufe("folien_aendern", args)
        self.assertFalse(fehler, aus)
        self.assertIn("'Punkt alt' -> 'Punkt neu'", aus)
        self.assertIn("XSD-Prüfung", aus)
        self.assertEqual(self.original.read_bytes(), vorher, "Original unangetastet")
        self.assertIn("Punkt neu", self.rufe("folien_lesen", {"datei": str(self.kopie), "folien": "1"})[1])
        self.assertEqual(sorted(p.name for p in (self.ablage / "T").iterdir()), ["Status.pptx"], "keine Hilfsdateien")
        self.assertTrue(list((self.daten / "zwischen" / "zustand").glob("*.json")))
        profil = (self.tmp / "bin" / "profil.sb").read_text()
        self.assertIn("(deny network*)", profil)
        shutil.copy(self.kopie, self.original)  # übertragen: Original gleich der Arbeitskopie
        fehler, aus, _ = self.rufe("folien_aendern", args)
        self.assertTrue(fehler)
        self.assertIn("neue Runde", aus)

    def test_pruefen_und_finden(self):
        fehler, aus, _ = self.rufe("folien_pruefen", {"datei": str(self.kopie), "original": str(self.original)})
        self.assertFalse(fehler, aus)
        self.assertIn("OK       keine PowerPoint-Fallen", aus)
        shutil.copy(self.original, self.such / "Status Bericht.pptx")
        fehler, aus, _ = self.rufe("folien_finden", {"begriffe": ["bericht"]})
        self.assertFalse(fehler, aus)
        self.assertIn(str(self.such / "Status Bericht.pptx"), aus)
        fehler, aus, _ = self.rufe("folien_finden", {"begriffe": ["Punkt", "alt"], "inhalt": True})
        self.assertIn("Folie 1:", aus)

    def test_excel_ohne_netz_nur_auf_der_arbeitskopie(self):
        hilfe.erzeuge(hilfe.MAPPE, self.ablage / "T" / "Liste.xlsx")
        shutil.copy(self.ablage / "T" / "Liste.xlsx", self.quelle / "Liste.xlsx")
        args = {"bereich": "arbeit", "thema": "T", "datei": "Liste.xlsx"}
        code = ("import sys, openpyxl\nwb = openpyxl.load_workbook(sys.argv[1])\nwb.active['A1'] = 'neu'\n"
                "wb.save(sys.argv[1])\nprint('geschrieben')\n")
        fehler, aus, _ = self.rufe("excel_skript", {**args, "code": code})
        self.assertFalse(fehler, aus)
        self.assertIn("geschrieben", aus)
        fehler, aus, _ = self.rufe("excel_fertig", args)
        self.assertFalse(fehler, aus)
        self.assertIn("Blätter (1): Liste", aus)
        lesen = "import sys, openpyxl\nprint(openpyxl.load_workbook(sys.argv[1]).active['A1'].value)\n"
        self.assertIn("neu", self.rufe("excel_skript", {**args, "code": lesen})[1])
        (self.quelle / "~$Liste.xlsx").write_text("")
        self.assertIn("Excel öffnet nie zwei Mappen gleichen Namens", self.rufe("excel_fertig", args)[1])


if __name__ == "__main__":
    unittest.main()
