"""Tests für den MCP-Server office (8.0, Grundstufe): Zuschnitt und eigene Obergrenze der Werkzeuge, Argumente an
ablage.py und sprache.py, Übertragen nur nach dem Dialog mit dem Hinweis auf geteilte Ordner, Umzug aus apple 7.3.

Aufruf im Plugin-Ordner: python3 -B -m unittest discover tests
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN))

import mcp_basis as mb  # noqa: E402
import server  # noqa: E402

# Werkzeuge des Servers office allein, getrennt von der Grenze über apple und chat (Plan 8.0): 3 in der Grundstufe,
# 7 mit dem Motor (folien_finden, folien_lesen, folien_pruefen, folien_aendern, excel_skript, excel_fertig,
# office_vorschau), Entscheidung des Betreuers vom 19.11.2026
GRENZE_OFFICE = 10
# Je Skript, was nur ein Werkzeug der Stufe nachfrage übergeben darf
VERBOTEN_OHNE_NACHFRAGE = {"ablage.py": ("--ausfuehren",), "sprache.py": ("--ausfuehren",)}
NACHFRAGE = {"arbeitskopie_uebertragen"}


class Aufnahme:
    def __init__(self):
        self.aufrufe = []

    def __call__(self, skript, argumente, zeit=mb.ZEIT_STANDARD, textdateien=None):
        self.aufrufe.append((skript, list(argumente), dict(textdateien or {})))
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
        self.assertEqual(namen, {"arbeitskopie", "arbeitskopie_uebertragen", "sprache"})
        self.assertLessEqual(len(namen), GRENZE_OFFICE)

    def test_stufe_passt_zur_annotation(self):
        for w in server.WERKZEUGE:
            a = w.annotationen()
            self.assertEqual(a["readOnlyHint"], w.stufe == "lesen", w.name)
            self.assertEqual(a["destructiveHint"], w.stufe == "nachfrage", w.name)
        self.assertEqual({w.name for w in server.WERKZEUGE if w.stufe == "nachfrage"}, NACHFRAGE)

    def test_modus_lesen_ohne_schreiben(self):
        self.assertEqual(werkzeug_liste(KITS_NUR_LESEN="1"), [])  # die Grundstufe hat kein Werkzeug zum Lesen


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
            "sprache": {"bereich": "arbeit", "thema": "--ausfuehren", "datei": "--ausfuehren"}}
        for w in server.WERKZEUGE:
            if w.stufe == "nachfrage":
                continue
            self.assertIn(w.name, beispiele)
            _fehler, _aus, (skript, argv, _) = self.rufe(w.name, beispiele[w.name])
            vor_trenner = argv[:argv.index("--")] if "--" in argv else argv
            for wort in VERBOTEN_OHNE_NACHFRAGE.get(skript, ()):
                self.assertNotIn(wort, vor_trenner, w.name)

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


if __name__ == "__main__":
    unittest.main()
