"""Tests für den MCP-Server apple (7.0): Zuschnitt aller Werkzeuge, Schutz ohne Nachfrage, Notizen, Erinnerungen,
Kontakte und die Einrichtung. Mail und Kalender stehen in test_server_mail.py."""
import json
import os
import re
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

# Werkzeuge aller Server des Pakets zusammen (Tokenlast). 7.0: 31 mit einstellungen und einstellungen_schreiben
GRENZE_ALLE_SERVER = 32
# Je Skript, was nur ein Werkzeug der Stufe nachfrage übergeben darf: senden, Arbeitskalender, Termine mit Teilnehmern,
# geteilte Notizordner. Verwerfen gibt es gar nicht. Eigene Termine, Entwürfe auch mit Anhang und eigene Notizen
# bleiben im eigenen Account und brauchen keine (Zusatzrunde V6 Phase 6)
VERBOTEN_OHNE_NACHFRAGE = {"mail.py": ("send", "--yes", "discard"), "add_event.py": ("--exchange",),
                           "move_event.py": ("--exchange", "--mit-teilnehmern"), "notiz.py": ("--ausfuehren",),
                           "pdf.py": ("--ersetzen",)}
NACHFRAGE = {"mail_senden", "termin_mit_nachfrage", "notiz_geteilt", "einstellungen_schreiben"}


class Aufnahme:
    def __init__(self):
        self.aufrufe = []

    def __call__(self, skript, argumente, zeit=mb.ZEIT_STANDARD, textdateien=None):
        self.aufrufe.append((skript, list(argumente), dict(textdateien or {})))
        return 0, "ok"


def werkzeug_liste(plugin: str) -> list:
    with tempfile.TemporaryDirectory() as t:
        (Path(t) / "config.json").write_text("{}")
        env = {**os.environ, mb.UMGEBUNG: t, "KITS_NUR_LESEN": ""}
        eingabe = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
        aus = subprocess.run([sys.executable, "-B", str(PLUGIN.parent / plugin / "server.py")], input=eingabe,
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

    def test_obergrenze_ueber_alle_server(self):
        gesamt = sum(len(werkzeug_liste(p)) for p in ("chat", "apple") if (PLUGIN.parent / p / "server.py").exists())
        self.assertLessEqual(gesamt, GRENZE_ALLE_SERVER)

    def test_stufe_passt_zur_annotation(self):
        for w in server.WERKZEUGE:
            a = w.annotationen()
            self.assertEqual(a["readOnlyHint"], w.stufe == "lesen", w.name)
            self.assertEqual(a["destructiveHint"], w.stufe == "nachfrage", w.name)
        self.assertEqual({w.name for w in server.WERKZEUGE if w.stufe == "nachfrage"}, NACHFRAGE)

    def test_modus_lesen(self):
        with mock.patch.dict(os.environ, {"KITS_NUR_LESEN": "1"}):
            werkzeuge = server.server().werkzeuge
        self.assertEqual({w.stufe for w in werkzeuge.values()}, {"lesen"})
        self.assertIn("einstellungen", werkzeuge)
        self.assertNotIn("einstellungen_schreiben", werkzeuge)


class Argumente(unittest.TestCase):
    def setUp(self):
        self.auf = Aufnahme()
        patcher = mock.patch.object(server, "lauf", self.auf)
        patcher.start()
        self.addCleanup(patcher.stop)
        dialog = mock.patch.dict(os.environ, {"KITS_DIALOG": "ja"})  # Dialog vor der Stufe nachfrage gilt als frei
        dialog.start()
        self.addCleanup(dialog.stop)

    def rufe(self, name, args):
        self.auf.aufrufe.clear()
        srv = mb.Server("apple", "t", server.WERKZEUGE)
        fehler, aus = srv.aufrufen(name, args)
        return fehler, aus, (self.auf.aufrufe[-1] if self.auf.aufrufe else None)

    def test_erinnerungen(self):
        self.assertEqual(self.rufe("erinnerungen_lesen", {})[2][:2], ("reminders.py", ["list"]))
        self.assertEqual(self.rufe("erinnerungen_lesen", {"tage": 7, "alle": True, "liste": "Aufgaben"})[2][1],
                         ["list", "--days=7", "--all", "--verlauf=Aufgaben"])
        self.assertEqual(self.rufe("erinnerungen_lesen", {"nur_listen": True})[2][1], ["lists"])
        self.assertEqual(self.rufe("erinnerung_anlegen", {"liste": "Aufgaben", "titel": "-Milch",
                                                          "fristen": ["2026-11-20", "2026-11-21 18:00"],
                                                          "notiz": "privat: x"})[2][1],
                         ["add", "--notes=privat: x", "--", "Aufgaben", "-Milch", "2026-11-20", "2026-11-21", "18:00"])
        self.assertEqual(self.rufe("erinnerung_abhaken", {"titel": "Milch", "liste": "Einkauf"})[2][1],
                         ["done", "--liste=Einkauf", "--", "Milch"])

    def test_notizen(self):
        self.assertEqual(self.rufe("notizen_suchen", {"text": "Rad"})[2][1], ["search", "--", "Rad"])
        self.assertEqual(self.rufe("notizen_suchen", {"ordner": "Privat", "limit": 5})[2][1],
                         ["list", "--folder=Privat", "--limit=5"])
        self.assertEqual(self.rufe("notizen_suchen", {"nur_ordner": True})[2][1], ["folders"])
        self.assertEqual(self.rufe("notiz_lesen", {"titel": "Liste", "html": True, "max_zeichen": 0})[2][1],
                         ["read", "--max-chars=0", "--html", "--", "Liste"])
        _, _, (skript, argv, dateien) = self.rufe("notiz_anlegen", {"titel": "T", "inhalt": "# Kopf\nText"})
        self.assertEqual(argv, ["add", "--title=T", "--file=notiz.md"])
        self.assertEqual(dateien, {"notiz.md": "# Kopf\nText"})
        _, _, (_, argv, dateien) = self.rufe("notiz_geteilt", {"titel": "T", "inhalt": "<p>x</p>",
                                                               "ordner": "Familie", "format": "html"})
        self.assertEqual(argv, ["--ausfuehren", "add", "--title=T", "--file=notiz.html", "--folder=Familie"])
        self.assertTrue(self.rufe("notiz_geteilt", {"titel": "T", "inhalt": "x"})[0])  # anlegen nur mit ordner
        self.assertEqual(self.rufe("notiz_geteilt", {"titel": "T", "inhalt": "neu", "ersetzen": True})[2][1],
                         ["--ausfuehren", "replace", "--file=notiz.md", "--", "T"])
        self.assertEqual(self.rufe("notiz_ersetzen", {"titel": "T", "inhalt": "neu"})[2][1],
                         ["replace", "--file=notiz.md", "--", "T"])
        self.assertEqual(server.notiz_vorschau({"titel": "Einkauf", "inhalt": "langer Inhalt", "ordner": "Familie"}),
                         "Notiz: Einkauf\nOrdner: Familie")  # Dialog in Stichworten, ohne Inhalt
        self.assertEqual(server.notiz_vorschau({"titel": "Einkauf", "inhalt": "x", "ersetzen": True}),
                         "Notiz: Einkauf\nErsetzt den Inhalt")
        fehler, aus, _ = self.rufe("notiz_anlegen", {"titel": "T", "inhalt": "x", "format": "pdf"})
        self.assertTrue(fehler)

    def test_kontakte(self):
        self.assertEqual(self.rufe("kontakte", {"ich": True})[2][1], ["me"])
        self.assertEqual(self.rufe("kontakte", {"suche": "Muster"})[2][1], ["search", "--", "Muster"])
        self.assertEqual(self.rufe("kontakte", {"id": "ABC"})[2][1], ["show", "--", "ABC"])
        self.assertTrue(self.rufe("kontakte", {})[0])

    def test_ohne_nachfrage_nie_senden_oder_geteilt(self):
        termine = [{"start": "2026-11-20 10:00", "ende": "2026-11-20 11:00"}]
        beispiele = {
            "mail_suchen": {"von": "send"}, "mail_neues": {}, "mail_lesen": {"ids": [1]},
            "mail_entwurf": {"antwort_auf": 1, "allen": True, "text": "send --yes"}, "mail_entwuerfe": {},
            "mail_entwurf_anhang": {"an": ["a@b.de"], "betreff": "send", "text": "--yes",
                                    "anhaenge": ["/Users/x/Downloads/a.pdf"]},
            "mail_stilprofil": {"stilprobe": 40}, "termine_lesen": {"alle": True},
            "termin_anlegen": {"titel": "--exchange", "termine": termine},
            "termin_verschieben": {"titel": "x", "termine": [{"start": "2026-11-20 10:00",
                                                              "neu_start": "2026-11-20 11:00"}]},
            "erinnerungen_lesen": {"liste": "x"}, "erinnerung_anlegen": {"liste": "x", "titel": "y"},
            "erinnerung_abhaken": {"titel": "y"}, "notizen_suchen": {"text": "x"}, "notiz_lesen": {"titel": "x"},
            "notiz_anlegen": {"titel": "x", "inhalt": "y", "ordner": "z"},
            "notiz_ersetzen": {"titel": "x", "inhalt": "y", "ordner": "z"}, "kontakte": {"suche": "x"},
            "pdf_aus_html": {"pfad": "--ersetzen", "name": "--ersetzen", "quer": True}, "einstellungen": {}}
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, {mb.UMGEBUNG: t}):
            for w in server.WERKZEUGE:
                if w.stufe == "nachfrage":
                    continue
                self.assertIn(w.name, beispiele)
                fehler, aus, aufruf = self.rufe(w.name, beispiele[w.name])
                if aufruf is None:
                    self.assertEqual(w.name, "einstellungen")  # liest ohne Skript
                    continue
                skript, argv, _ = aufruf
                vor_trenner = argv[:argv.index("--")] if "--" in argv else argv
                for wort in VERBOTEN_OHNE_NACHFRAGE.get(skript, ()):
                    self.assertNotIn(wort, vor_trenner, w.name)

    def test_pdf(self):
        self.assertEqual(self.rufe("pdf_aus_html", {"pfad": "/x/a.html"})[2][:2], ("pdf.py", ["--", "/x/a.html"]))
        self.assertEqual(self.rufe("pdf_aus_html", {"pfad": "/x/a.html", "quer": True, "name": "B.pdf"})[2][1],
                         ["--quer", "--name=B.pdf", "--", "/x/a.html"])
        self.assertEqual(self.rufe("pdf_aus_html", {"pfad": "/x/a.html", "ersetzen": True})[2][1],
                         ["--ersetzen", "--", "/x/a.html"])  # Dialog im Test frei
        self.assertTrue(self.rufe("pdf_aus_html", {})[0])  # pfad ist Pflicht
        self.assertEqual(server.pdf_vorschau({"pfad": "/x/Ordner/a.html", "name": "B"}),
                         "PDF: B.pdf\nOrdner: Ordner\nAus: a.html\nErsetzt das vorhandene PDF")

    def test_pdf_ersetzen_ohne_dialog_nie(self):
        with mock.patch.dict(os.environ, {"KITS_DIALOG": "nein"}):
            fehler, aus, aufruf = self.rufe("pdf_aus_html", {"pfad": "/x/a.html", "ersetzen": True})
        self.assertTrue(fehler)
        self.assertIsNone(aufruf)
        self.assertIn("Nicht ausgeführt", aus)

    def test_schadhafte_werte_bleiben_daten(self):
        _, _, (_, argv, _) = self.rufe("notiz_lesen", {"titel": "--ausfuehren", "ordner": "--html"})
        self.assertEqual(argv, ["read", "--folder=--html", "--", "--ausfuehren"])  # schalter_vorn bricht dann ab
        self.assertTrue(re.match(r"^--folder=", argv[1]))


class Einrichtung(unittest.TestCase):
    """7.0: einstellungen und einstellungen_schreiben für den Skill einrichten, auch für chat und service."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ordner = Path(tmp.name)
        p = mock.patch.dict(os.environ, {mb.UMGEBUNG: tmp.name, "KITS_DIALOG": "ja"})
        p.start()
        self.addCleanup(p.stop)

    def rufe(self, name, args):
        return mb.Server("apple", "t", server.WERKZEUGE).aufrufen(name, args)

    def test_vorlage_hat_alle_abschnitte(self):
        self.assertEqual([k for k in server.vorlage() if not k.startswith("_")],
                         ["mail", "kalender", "notizen", "reminders", "kontakte", "pdf"])

    def test_schreiben_nur_nach_vorlage_und_dialog(self):
        fehler, aus = self.rufe("einstellungen_schreiben", {"werte": {"kalender": {"default_calendar": "Privat"}}})
        self.assertFalse(fehler, aus)
        self.assertEqual(json.loads((self.ordner / "config.json").read_text())["kalender"]["default_calendar"],
                         "Privat")
        self.assertIn("gibt es nicht", self.rufe("einstellungen_schreiben", {"werte": {"post": {}}})[1])
        fehler, aus = self.rufe("einstellungen_schreiben", {"plugin": "chat", "werte": {"me": "Ich"}})
        self.assertFalse(fehler, aus)  # chat ohne Vorlage im Plugin apple
        self.assertTrue(self.rufe("einstellungen_schreiben", {"plugin": "fremd", "werte": {"x": 1}})[0])
        with mock.patch.dict(os.environ, {"KITS_DIALOG": "nein"}):
            fehler, aus = self.rufe("einstellungen_schreiben", {"werte": {"notizen": {}}})
        self.assertTrue(fehler)
        self.assertNotIn("notizen", json.loads((self.ordner / "config.json").read_text()))
        fehler, aus = self.rufe("einstellungen", {})
        self.assertFalse(fehler)
        self.assertIn('"default_calendar": "Privat"', aus)

    def test_stilprofile(self):
        self.assertFalse(self.rufe("einstellungen_schreiben", {"stilprofil": "privat", "text": "Kurz."})[0])
        self.assertEqual((self.ordner / "style" / "privat" / "profil.md").read_text(), "Kurz.\n")
        self.assertFalse(self.rufe("einstellungen_schreiben", {"plugin": "chat", "stilprofil": "chat",
                                                               "text": "Locker."})[0])
        self.assertEqual((self.ordner / "style" / "profil.md").read_text(), "Locker.\n")
        for falsch in ({"stilprofil": "../x", "text": "a"}, {"plugin": "chat", "stilprofil": "privat", "text": "a"},
                       {"plugin": "service", "stilprofil": "privat", "text": "a"}, {"stilprofil": "privat"},
                       {"stilprofil": "privat", "text": "a", "werte": {"notizen": {}}}, {"text": "a"}):
            self.assertTrue(self.rufe("einstellungen_schreiben", falsch)[0], falsch)


if __name__ == "__main__":
    unittest.main()
