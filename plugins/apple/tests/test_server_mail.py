"""Tests für den MCP-Server apple, Teil Mail und Kalender (bis 6.3 eigenes Plugin mail): Argumente an die Skripte,
Sende- und Schreibschutz, Dialoge. Zuschnitt und Schutz aller Werkzeuge stehen in test_server.py."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN))

import mcp_basis as mb  # noqa: E402
import server  # noqa: E402
from test_server import Aufnahme  # noqa: E402


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
        fehler, aus = mb.Server("apple", "t", server.WERKZEUGE).aufrufen(name, args)
        return fehler, aus, (self.auf.aufrufe[-1] if self.auf.aufrufe else None)

    def test_suchen_und_finden(self):
        self.assertEqual(self.rufe("mail_suchen", {"von": "-x", "tage": 30, "ungelesen": True, "profil": "privat"})[2][1],
                         ["search", "--from=-x", "--days=30", "--profile=privat", "--unread"])
        self.assertEqual(self.rufe("mail_suchen", {"postfach": "sent", "tage": 14})[2][1],
                         ["search", "--days=14", "--mailbox=sent"])
        self.assertTrue(self.rufe("mail_suchen", {"tage": 3})[0])  # ohne Filter nichts
        self.assertEqual(self.rufe("mail_suchen", {"message_id": "<a@b>"})[2][1], ["finden", "--message-id=<a@b>"])
        self.assertEqual(self.rufe("mail_suchen", {"betreff": "Angebot", "datum": "2026-11-10"})[2][1],
                         ["finden", "--datum=2026-11-10", "--subject=Angebot"])
        self.assertTrue(self.rufe("mail_suchen", {"postfach": "spam", "von": "x"})[0])

    def test_neues_und_lesen(self):
        self.assertEqual(self.rufe("mail_neues", {})[2][1], ["triage"])
        self.assertEqual(self.rufe("mail_neues", {"profil": "arbeit"})[2][1], ["triage", "48", "arbeit"])
        self.assertEqual(self.rufe("mail_neues", {"stunden": 12})[2][1], ["triage", "12"])
        self.assertEqual(self.rufe("mail_lesen", {"ids": [12, 13], "html": True})[2][1],
                         ["read", "--html", "12", "13"])
        for falsch in ([], ["12"], [True], list(range(1, 12)), [-1]):
            self.assertTrue(self.rufe("mail_lesen", {"ids": falsch})[0], falsch)

    def test_entwurf_neu_und_antwort(self):
        _, _, (skript, argv, dateien) = self.rufe("mail_entwurf", {"an": ["a@b.de"], "cc": ["c@d.de"],
                                                                  "betreff": "Frage", "text": "Hallo\r\nDu"})
        self.assertEqual((skript, argv), ("mail.py", ["draft", "--to=a@b.de", "--cc=c@d.de", "--subject=Frage",
                                                      "--text-file=entwurf.txt"]))
        self.assertEqual(dateien, {"entwurf.txt": "Hallo\nDu"})
        _, _, (_, argv, dateien) = self.rufe("mail_entwurf", {"antwort_auf": 77, "allen": True, "text": "Danke"})
        self.assertEqual(argv, ["draft", "--text-file=antwort.txt", "--reply-to=77", "--all"])
        self.assertEqual(list(dateien), ["antwort.txt"])
        self.assertTrue(self.rufe("mail_entwurf", {"text": "x"})[0])  # weder an noch antwort_auf
        self.assertTrue(self.rufe("mail_entwurf", {"antwort_auf": 1, "an": ["x@y.de"], "text": "x"})[0])
        self.assertTrue(self.rufe("mail_entwurf", {"an": ["x@y.de"], "allen": True, "text": "x"})[0])

    def test_anhang_ohne_und_senden_mit_nachfrage(self):
        with mock.patch.dict(os.environ, {"KITS_DIALOG": "nein"}):  # Entwurf mit Anhang kommt ohne Dialog durch
            _, _, (_, argv, _) = self.rufe("mail_entwurf_anhang", {"an": ["a@b.de"], "betreff": "B", "text": "T",
                                                                 "anhaenge": ["/Users/x/Downloads/a.pdf"]})
        self.assertEqual(argv[:2], ["--attach=/Users/x/Downloads/a.pdf", "draft"])
        self.assertNotIn("send", argv)
        self.assertEqual(self.rufe("mail_senden", {"entwurf_id": 7})[2][1], ["send", "7", "--yes"])
        self.assertTrue(self.rufe("mail_senden", {})[0])

    def test_senden_nur_mit_freigabe_im_dialog(self):
        with mock.patch.dict(os.environ, {"KITS_DIALOG": "nein"}):
            self.assertTrue(self.rufe("mail_senden", {"entwurf_id": 7})[0])
        self.assertEqual([a[1] for a in self.auf.aufrufe], [["drafts"]])  # nur die Vorschau, kein send
        with mock.patch.object(mb, "bestaetigen", return_value=(False, "x")) as dialog:
            self.rufe("mail_senden", {"entwurf_id": 7})
        self.assertEqual(dialog.call_args[0][0],
                         "Claude möchte: Mail senden\n\nEntwurf in Apple Mail nicht gefunden.")
        liste = ("id | betreff | empfänger | von | inhalt\n"
                 "17 | Andere | an x@y.de | ich | 3 Zeichen\n"
                 "7 | Frage | Teil 2 | an a@b.de, Cc c@d.de, e@f.de | Absender | 8 Zeichen (nicht vom Kit)\n"
                 "8 | Leer | (ohne Empfänger) | Ich | 0 Zeichen")
        with mock.patch.object(server, "lauf", return_value=(0, liste)):
            self.assertEqual(server.senden_vorschau({"entwurf_id": 7}),
                             "Betreff: Frage | Teil 2\nAn: a@b.de\nCc: c@d.de, e@f.de\nVon: Absender")
            self.assertEqual(server.senden_vorschau({"entwurf_id": 8}),
                             "Betreff: Leer\nAn: (ohne Empfänger)\nVon: Ich")
            self.assertNotIn("7", server.senden_vorschau({"entwurf_id": 9}))  # keine ID im Dialog

    def test_dialog_in_stichworten(self):
        """Zusatzrunde Phase 6: Dialoge nur mit dem, was die Entscheidung braucht, ohne Text und volle Pfade."""
        heute = server.date(2026, 11, 14)
        with mock.patch.object(server, "date", mock.Mock(today=lambda: heute)):
            self.assertEqual(server.termin_vorschau({
                "aktion": "anlegen", "arbeitskalender": True, "titel": "Fokus",
                "termine": [{"start": "2026-11-20 10:00", "ende": "2026-11-20 11:00"},
                            {"start": "2027-01-08", "ende": "2027-01-08"}]}),
                "Termin: Fokus\nWann: 20.11. 10:00 bis 11:00 (und 1 weitere)\nKalender: Arbeit")
            self.assertEqual(server.termin_vorschau({
                "aktion": "verschieben", "mit_teilnehmern": True, "titel": "Jour",
                "termine": [{"start": "2026-11-20 10:00", "neu_start": "2027-01-08 9:30"}]}),
                "Termin: Jour\nWann: 20.11. 10:00 auf 08.01.2027 9:30\nAchtung: Updates an alle Teilnehmer")
            self.assertEqual(server.termin_vorschau({"aktion": "verschieben", "arbeitskalender": True, "titel": "x",
                                                     "nach_kalender": "Sport", "vorschau": True,
                                                     "termine": [{"start": "2026-11-20"}]}),
                             "Termin: x\nWann: 20.11.\nNach: Sport\nKalender: Arbeit\nNur Vorschau, ändert nichts")

    def test_termine(self):
        self.assertEqual(self.rufe("termine_lesen", {})[2][:2], ("calendar_today.sh", []))
        self.assertEqual(self.rufe("termine_lesen", {"tage": 7, "alle": True})[2][1], ["7", "--all"])
        self.assertEqual(self.rufe("termine_lesen", {"kalenderliste": True})[2][1], ["--list"])
        termine = [{"start": "2026-11-20 10:00", "ende": "2026-11-20 11:00"}]
        self.assertEqual(self.rufe("termin_anlegen", {"titel": "Rad", "termine": termine, "ort": "Stadtpark"})[2][1],
                         ["--ausfuehren", "--ort=Stadtpark", "--", "Rad", "2026-11-20 10:00", "2026-11-20 11:00"])
        self.assertEqual(self.rufe("termin_anlegen", {"titel": "Rad", "termine": termine, "vorschau": True})[2][1],
                         ["--", "Rad", "2026-11-20 10:00", "2026-11-20 11:00"])
        self.assertTrue(self.rufe("termin_anlegen", {"titel": "Rad", "termine": [{"start": "morgen", "ende": "x"}]})[0])
        self.assertEqual(self.rufe("termin_verschieben", {"titel": "Rad", "termine": [
            {"start": "2026-11-20 10:00", "neu_start": "2026-11-21 10:00"}]})[2][:2],
            ("move_event.py", ["--ausfuehren", "--", "Rad", "2026-11-20 10:00", "2026-11-21 10:00"]))
        self.assertEqual(self.rufe("termin_verschieben", {"titel": "Rad", "nach_kalender": "Sport", "termine": [
            {"start": "2026-11-20 10:00"}]})[2][1],
            ["--ausfuehren", "--nach-kalender=Sport", "--", "Rad", "2026-11-20 10:00"])

    def test_termin_mit_nachfrage(self):
        termine = [{"start": "2026-11-20 10:00", "ende": "2026-11-20 11:00"}]
        _, _, (skript, argv, _) = self.rufe("termin_mit_nachfrage", {"aktion": "anlegen", "arbeitskalender": True,
                                                                    "titel": "Fokus", "termine": termine})
        self.assertEqual((skript, argv[:2]), ("add_event.py", ["--exchange", "--ausfuehren"]))
        _, _, (skript, argv, _) = self.rufe("termin_mit_nachfrage", {
            "aktion": "verschieben", "mit_teilnehmern": True, "titel": "Jour",
            "termine": [{"start": "2026-11-20 10:00", "neu_start": "2026-11-20 11:00"}]})
        self.assertEqual(skript, "move_event.py")
        self.assertIn("--mit-teilnehmern", argv)
        self.assertNotIn("--exchange", argv)
        self.assertTrue(self.rufe("termin_mit_nachfrage", {"aktion": "anlegen", "titel": "x", "termine": termine})[0])
        self.assertTrue(self.rufe("termin_mit_nachfrage", {"aktion": "anlegen", "arbeitskalender": True,
                                                           "mit_teilnehmern": True, "titel": "x",
                                                           "termine": termine})[0])

    def test_stilprofil(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "style" / "privat").mkdir(parents=True)
            (Path(t) / "style" / "privat" / "profil.md").write_text("Kurz und klar.", encoding="utf-8")
            with mock.patch.dict(os.environ, {mb.UMGEBUNG: t}):
                self.assertEqual(self.rufe("mail_stilprofil", {})[:2], (False, "Kurz und klar."))
                self.assertTrue(self.rufe("mail_stilprofil", {"profil": "arbeit"})[0])
                self.assertTrue(self.rufe("mail_stilprofil", {"profil": "../privat"})[0])

    def test_stilprobe_fuer_die_einrichtung(self):
        """7.0: Die Stilprobe läuft über den Server, in Cowork erreicht Bash Apple Mail nicht."""
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "config.json").write_text("{}")
            (Path(t) / "style" / "arbeit").mkdir(parents=True)
            (Path(t) / "style" / "arbeit" / "samples.md").write_text("## Mail 1\nHi Anna,", encoding="utf-8")
            with mock.patch.dict(os.environ, {mb.UMGEBUNG: t}):
                fehler, aus, aufruf = self.rufe("mail_stilprofil", {"profil": "arbeit", "stilprobe": 40})
        self.assertFalse(fehler)
        self.assertEqual(aufruf[:2], ("style_sample.py", ["--n=40", "--profile=arbeit"]))
        self.assertEqual(aus, "ok\n\n## Mail 1\nHi Anna,")
        self.assertTrue(self.rufe("mail_stilprofil", {"stilprobe": 1000})[0])


if __name__ == "__main__":
    unittest.main()
