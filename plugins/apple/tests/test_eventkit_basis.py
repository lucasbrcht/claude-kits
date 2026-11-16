"""Tests für eventkit_basis.py: deutsche Anzeige, Zugriff mit Systemdialog, Konfiguration, Selbststart in die .venv.

Seit 7.0 nur im Plugin apple, wie eventkit_basis.py selbst.
Aufruf im Plugin-Ordner: python3 -B -m unittest discover tests
"""
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ersatz_eventkit import D, KitTest

import eventkit_basis


class Anzeige(unittest.TestCase):
    def test_wochentage_deutsch(self):
        self.assertEqual(eventkit_basis.tag(dt.date(2026, 10, 6)), "Di 06.10.")
        self.assertEqual(eventkit_basis.tag(dt.date(2026, 10, 11)), "So 11.10.")

    def test_volle_und_halbe_stunde(self):
        z = eventkit_basis.zeitraum
        self.assertEqual(z(D("2026-10-06 14:00"), D("2026-10-06 14:30")), "Di 06.10., 14 bis 14:30 Uhr")
        self.assertEqual(z(D("2026-10-06 09:05"), D("2026-10-06 10:00")), "Di 06.10., 9:05 bis 10 Uhr")

    def test_ueber_mitternacht_mit_enddatum(self):
        self.assertEqual(eventkit_basis.zeitraum(D("2026-10-06 22:00"), D("2026-10-07 01:00")),
                         "Di 06.10., 22 Uhr bis Mi 07.10., 1 Uhr")

    def test_ganztaegig(self):
        z = eventkit_basis.zeitraum
        self.assertEqual(z(D("2026-10-12 00:00"), D("2026-10-16 23:59"), True), "Mo 12.10. bis Fr 16.10., ganztägig")
        self.assertEqual(z(D("2026-10-12 00:00"), D("2026-10-12 23:59"), True), "Mo 12.10., ganztägig")
        self.assertEqual(z(D("2026-10-12 00:00"), D("2026-10-13 00:00"), True), "Mo 12.10., ganztägig")


    def test_zeitumstellung(self):
        """V3.1.2: gemeinsam für Kalender und Erinnerungen, die doppelte oder fehlende Stunde bricht ab."""
        eventkit_basis.ortszeit_eindeutig(D("2026-10-25 04:00"), "Nichts angelegt.")
        for wann, text in (("2026-10-25 02:30", "So 25.10., 2:30 Uhr gibt es zweimal"),
                           ("2027-03-28 02:30", "So 28.03., 2:30 Uhr gibt es nicht")):
            with self.assertRaises(SystemExit) as e:
                eventkit_basis.ortszeit_eindeutig(D(wann), "Nichts angelegt.")
            self.assertIn(text, str(e.exception.code))
            self.assertIn("Nichts angelegt.", str(e.exception.code))


class Zugriff(KitTest):
    def test_ohne_eventkit(self):
        with mock.patch.dict(sys.modules, {"EventKit": None}):
            with self.assertRaisesRegex(SystemExit, r"EventKit fehlt, auch in der \.venv.*pyobjc-framework-EventKit"):
                eventkit_basis.store_with_access("events")

    def test_verweigert(self):
        self.store(zugriff=False)
        with self.assertRaisesRegex(SystemExit, "Kein Zugriff auf Kalender.*python3.9.*Claude-App.*absolutem Pfad"):
            eventkit_basis.store_with_access("events")

    def test_dialog_ohne_antwort(self):
        self.store(zugriff=None)
        with self.assertRaisesRegex(SystemExit, "Kein Zugriff auf Erinnerungen"):
            eventkit_basis.store_with_access("reminders")

    def test_config_text_statt_liste(self):
        with self.assertRaisesRegex(SystemExit, "private_calendars muss eine Liste"):
            eventkit_basis.namen({"private_calendars": "Geheim"}, "private_calendars")

    def test_config_fehlt_oder_kaputt(self):
        self.cfg_pfad.write_text("{kaputt", encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "kein gültiges JSON"):
            eventkit_basis.load_config()
        self.cfg_pfad.unlink()
        with self.assertRaisesRegex(SystemExit, "config.json fehlt"):
            eventkit_basis.load_config()


class Selbststart(unittest.TestCase):
    """Die Skripte starten als python3 und wechseln selbst in die .venv des Plugins, nur in eine echte im Plugin."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.venv = self.tmp / ".venv"
        self.gestartet = []
        umgebung = {k: v for k, v in os.environ.items() if k != eventkit_basis.VENV_MARKE}
        for p in (mock.patch.object(eventkit_basis, "VENV", self.venv),
                  mock.patch.object(eventkit_basis.os, "execv", lambda *a: self.gestartet.append(a)),
                  mock.patch.dict(os.environ, umgebung, clear=True),
                  mock.patch.object(sys, "argv", ["add_event.py", "--", "Titel", "2026-10-05 09:30"])):
            p.start()
            self.addCleanup(p.stop)

    def venv_anlegen(self):
        (self.venv / "bin").mkdir(parents=True)
        (self.venv / "bin" / "python3").symlink_to(sys.executable)  # wie die echte: Verweis auf Homebrew-Python

    def starte(self, eventkit=False):
        with mock.patch.dict(sys.modules, {"EventKit": sys.modules["EventKit"] if eventkit else None}):
            eventkit_basis.venv_starten(str(self.tmp / "add_event.py"))

    def test_mit_eventkit_kein_wechsel(self):
        self.venv_anlegen()
        self.starte(eventkit=True)
        self.assertEqual(self.gestartet, [])

    def test_ohne_eventkit_in_die_venv_des_kits(self):
        self.venv_anlegen()
        with mock.patch.object(sys, "dont_write_bytecode", False):
            self.starte()
        python = str(self.venv / "bin" / "python3")
        self.assertEqual(self.gestartet, [(python, [python, str(self.tmp / "add_event.py"), "--", "Titel",
                                                    "2026-10-05 09:30"])])
        self.assertEqual(os.environ[eventkit_basis.VENV_MARKE], "1")

    def test_ohne_bytecode_auch_in_der_venv(self):
        """Prüfung 20.10.2026: Mit -B gestartet bekommt die .venv -B mit, sonst entstünde außerhalb der Session
        __pycache__ im Kit."""
        self.venv_anlegen()
        with mock.patch.object(sys, "dont_write_bytecode", True):
            self.starte()
        python = str(self.venv / "bin" / "python3")
        self.assertEqual(self.gestartet, [(python, [python, "-B", str(self.tmp / "add_event.py"), "--", "Titel",
                                                    "2026-10-05 09:30"])])

    def test_nur_einmal(self):
        self.venv_anlegen()
        os.environ[eventkit_basis.VENV_MARKE] = "1"
        self.starte()
        self.assertEqual(self.gestartet, [])

    def test_ohne_venv_kein_wechsel(self):
        self.starte()
        self.assertEqual(self.gestartet, [])

    def test_kaputte_venv_ohne_traceback(self):
        """Review 20.10.2026: ist .venv/bin/python3 nicht startbar, läuft das Skript weiter und store_with_access meldet
        klar, dass EventKit fehlt, statt mit PermissionError oder Exec format error abzubrechen."""
        self.venv_anlegen()

        def scheitert(*a):
            raise PermissionError(13, "Permission denied")
        with mock.patch.object(eventkit_basis.os, "execv", scheitert):
            self.starte()  # kein Traceback

    def test_verweise_nach_aussen_zaehlen_nicht(self):
        fremd = self.tmp / "fremd"
        (fremd / "bin").mkdir(parents=True)
        (fremd / "bin" / "python3").symlink_to(sys.executable)
        self.venv.symlink_to(fremd)
        self.starte()
        self.assertEqual(self.gestartet, [])
        self.venv.unlink()
        self.venv.mkdir()
        (self.venv / "bin").symlink_to(fremd / "bin")
        self.starte()
        self.assertEqual(self.gestartet, [])


if __name__ == "__main__":
    unittest.main()
