"""Tests für ablage.py (bis 7.3 in apple): Arbeitskopie holen, Themen wiederverwenden, Herkunft im Datenordner,
Übertragen in dieselbe Originaldatei mit Stand-Schutz, Pfade aus Cowork, die Grenzen von zeigen und ablage_datei für
sprache.py. Alles in einem Temp-Ordner, der Heimordner ist dort ersetzt.

Aufruf im Plugin-Ordner: python3 -B -m unittest discover tests
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN))

import ablage  # noqa: E402


class AblageTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.heim = Path(tmp.name).resolve() / "heim"
        self.daten = Path(tmp.name).resolve() / "daten"
        self.downloads = self.heim / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "Downloads"
        self.sharepoint = self.heim / "Library" / "CloudStorage" / "OneDrive-Firma" / "Team - Dokumente" / "Vertrieb"
        for o in (self.daten, self.downloads, self.sharepoint, self.heim / "Documents", self.heim / ".geheim"):
            o.mkdir(parents=True)
        self.original = self.sharepoint / "Pitch.pptx"
        self.original.write_bytes(b"PK original")
        self.cfg = {"ablage": {"privat": str(self.downloads / "Claude Personal"),
                               "arbeit": str(self.downloads / "Claude Work")}}
        (self.daten / "config.json").write_text(json.dumps(self.cfg))
        self.geoeffnet = self.daten / "geoeffnet.txt"
        programm = Path(tmp.name) / "oeffnen.sh"
        programm.write_text(f'#!/bin/sh\nIFS="|"\necho "$*" >> "{self.geoeffnet}"\n')  # Argumente mit | getrennt
        programm.chmod(0o755)
        for p in (mock.patch.object(ablage, "CONFIG_PATH", self.daten / "config.json"),
                  mock.patch.object(ablage, "DATEN_DIR", self.daten),
                  mock.patch.object(ablage, "HEIM", self.heim),
                  mock.patch.dict(os.environ, {"KITS_OEFFNEN": str(programm), "KITS_FEHLERPROTOKOLL": "aus"})):
            p.start()
            self.addCleanup(p.stop)

    def lauf(self, *argv):
        """(Ausgabe, Exit-Meldung oder None)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                ablage.main(list(argv))
            except SystemExit as e:
                return out.getvalue(), (f"{e.code} {err.getvalue()}" if isinstance(e.code, int) else str(e.code))
        return out.getvalue(), None

    def holen(self, thema="Pitch Q4", pfad=None, *schalter):
        return self.lauf("holen", "--bereich=arbeit", f"--thema={thema}", *schalter, "--", str(pfad or self.original))

    @property
    def kopie(self):
        return self.downloads / "Claude Work" / "Pitch Q4" / "Pitch.pptx"

    def herkunft(self):
        return json.loads((self.daten / "ablage.json").read_text())["kopien"]

    # ---------- holen ----------
    def test_holen_legt_ordner_und_kopie_an(self):
        out, fehler = self.holen()
        self.assertIsNone(fehler)
        self.assertEqual(self.kopie.read_bytes(), b"PK original")
        self.assertIn("In Cowork: Downloads/Claude Work/Pitch Q4/Pitch.pptx", out)
        self.assertEqual(sorted(p.name for p in self.sharepoint.iterdir()), ["Pitch.pptx"])  # nichts neben dem Original
        self.assertEqual(sorted(p.name for p in self.kopie.parent.iterdir()), ["Pitch.pptx"])  # keine Hilfsdateien
        eintrag = self.herkunft()[str(self.kopie)]
        self.assertEqual(eintrag["original"], str(self.original))
        self.assertEqual(eintrag["stand"]["groesse"], len(b"PK original"))

    def test_gleiches_thema_wiederverwenden(self):
        self.holen()
        self.kopie.write_bytes(b"PK iteration 2")
        out, fehler = self.holen(thema="pitch q4")
        self.assertIsNone(fehler)
        self.assertIn("gibt es schon", out)
        self.assertEqual(self.kopie.read_bytes(), b"PK iteration 2")  # Iterationen bleiben
        self.assertEqual([p.name for p in (self.downloads / "Claude Work").iterdir()], ["Pitch Q4"])

    def test_neu_nur_ohne_offene_aenderungen(self):
        self.holen()
        self.kopie.write_bytes(b"PK iteration 2")
        _out, fehler = self.holen("Pitch Q4", None, "--neu")
        self.assertIn("nicht übertragen", fehler)
        self.assertEqual(self.kopie.read_bytes(), b"PK iteration 2")
        self.kopie.write_bytes(b"PK original")
        self.original.write_bytes(b"PK von anderen")
        out, fehler = self.holen("Pitch Q4", None, "--neu")
        self.assertIsNone(fehler)
        self.assertEqual(self.kopie.read_bytes(), b"PK von anderen")

    def test_gleicher_name_aus_anderer_quelle(self):
        self.holen()
        anderes = self.heim / "Documents" / "Pitch.pptx"
        anderes.write_bytes(b"PK anders")
        _out, fehler = self.holen("Pitch Q4", anderes)
        self.assertIn("anderes Thema", fehler)
        self.assertEqual(self.kopie.read_bytes(), b"PK original")

    def test_quellen_grenzen(self):
        faelle = {self.heim / ".geheim" / "a.docx": "versteckt",
                  self.heim / "Library" / "Preferences" / "a.docx": "Heimordner",
                  self.heim / "Documents" / "skript.sh": "Nur Dokumente",
                  self.heim.parent / "fremd.docx": "Heimordner"}
        for pfad, meldung in faelle.items():
            pfad.parent.mkdir(parents=True, exist_ok=True)
            pfad.write_bytes(b"x")
            self.assertIn(meldung, str(self.holen("T", pfad)[1]), pfad)
        verweis = self.heim / "Documents" / "verweis.pptx"
        verweis.symlink_to(self.original)
        self.assertIn("Verweis", str(self.holen("T", verweis)[1]))
        self.assertIn("absolut", str(self.holen("T", "Pitch.pptx")[1]))
        self.holen()
        self.assertIn("schon in der Ablage", str(self.holen("T", self.kopie)[1]))
        for thema in ("../x", "a/b", ".versteckt"):
            self.assertTrue(str(self.holen(thema)[1]).startswith("2 "), thema)

    # ---------- Pfade aus Cowork ----------
    def test_pfad_aus_cowork(self):
        vm = "/sessions/froh-test/mnt/Vertrieb/Pitch.pptx"
        out, fehler = self.holen("Pitch Q4", vm)
        self.assertIsNone(fehler)
        self.assertIn(f"Original: {self.original}", out)
        doppelt = self.heim / "Documents" / "Vertrieb"
        doppelt.mkdir()
        (doppelt / "Pitch.pptx").write_bytes(b"x")
        self.assertIn("mehrfach", str(self.holen("Anderes", vm)[1]))
        self.assertIn("finde ich am Mac nicht", str(self.holen("T", "/sessions/x/mnt/Fehlt/a.pptx")[1]))
        self.assertIn("nur in Cowork", str(self.holen("T", "/sessions/x/mnt/uploads/a.pptx")[1]))

    # ---------- übertragen ----------
    def test_uebertragen_nur_mit_ausfuehren_und_in_dieselbe_datei(self):
        self.holen()
        self.kopie.write_bytes(b"PK neue Fassung")
        inode = self.original.stat().st_ino
        out, fehler = self.lauf("uebertragen", "--bereich=arbeit", "--thema=Pitch Q4", "--", "Pitch.pptx")
        self.assertIsNone(fehler)
        self.assertIn("Vorschau", out)
        self.assertEqual(self.original.read_bytes(), b"PK original")
        out, fehler = self.lauf("--ausfuehren", "uebertragen", "--bereich=arbeit", "--thema=Pitch Q4", "--",
                                "Pitch.pptx")
        self.assertIsNone(fehler)
        self.assertEqual(self.original.read_bytes(), b"PK neue Fassung")
        self.assertEqual(self.original.stat().st_ino, inode)  # dieselbe Datei, nicht gelöscht und neu angelegt
        self.assertEqual(sorted(p.name for p in self.sharepoint.iterdir()), ["Pitch.pptx"])
        sicherung = next((self.daten / "ablage-sicherung").glob("*/Pitch.pptx"))
        self.assertEqual(sicherung.read_bytes(), b"PK original")
        # weitere Iteration nach dem Übertragen, das Original trägt jetzt den neuen Stand
        self.kopie.write_bytes(b"PK dritte Fassung")
        _out, fehler = self.lauf("--ausfuehren", "uebertragen", "--bereich=arbeit", "--thema=Pitch Q4", "--",
                                 "Pitch.pptx")
        self.assertIsNone(fehler)
        self.assertEqual(self.original.read_bytes(), b"PK dritte Fassung")
        self.assertEqual(sicherung.read_bytes(), b"PK neue Fassung")

    def test_ausfuehren_nur_vorn(self):
        self.holen()
        _out, fehler = self.lauf("uebertragen", "--ausfuehren", "--bereich=arbeit", "--thema=Pitch Q4", "--",
                                 "Pitch.pptx")
        self.assertIn("direkt hinter dem Skript", str(fehler))
        self.assertTrue(str(self.lauf("--ausfuehren", "liste")[1]).startswith("2 "))

    def test_stand_schutz(self):
        self.holen()
        self.kopie.write_bytes(b"PK neue Fassung")
        self.original.write_bytes(b"PK von anderen")
        _out, fehler = self.lauf("--ausfuehren", "uebertragen", "--bereich=arbeit", "--thema=Pitch Q4", "--",
                                 "Pitch.pptx")
        self.assertIn("seit dem Holen geändert", fehler)
        self.assertEqual(self.original.read_bytes(), b"PK von anderen")

    def test_office_offen_und_original_weg(self):
        self.holen()
        self.kopie.write_bytes(b"PK neue Fassung")
        sperre = self.sharepoint / "~$Pitch.pptx"
        sperre.write_bytes(b"")
        args = ("--ausfuehren", "uebertragen", "--bereich=arbeit", "--thema=Pitch Q4", "--", "Pitch.pptx")
        self.assertIn("in Office geöffnet", str(self.lauf(*args)[1]))
        sperre.unlink()
        self.original.rename(self.sharepoint / "Umbenannt.pptx")
        self.assertIn("fehlt am alten Ort", str(self.lauf(*args)[1]))

    def test_ohne_herkunft_nicht_uebertragbar(self):
        ordner = self.downloads / "Claude Work" / "Frei"
        ordner.mkdir(parents=True)
        (ordner / "x.docx").write_bytes(b"x")
        _out, fehler = self.lauf("--ausfuehren", "uebertragen", "--bereich=arbeit", "--thema=Frei", "--", "x.docx")
        self.assertIn("keine bekannte Herkunft", fehler)

    def test_unveraendert_nichts_zu_tun(self):
        self.holen()
        out, fehler = self.lauf("--ausfuehren", "uebertragen", "--bereich=arbeit", "--thema=Pitch Q4", "--",
                                "Pitch.pptx")
        self.assertIsNone(fehler)
        self.assertIn("nichts zu übertragen", out)

    # ---------- liste, herkunft, zeigen ----------
    def test_liste_und_herkunft(self):
        self.holen()
        self.kopie.write_bytes(b"PK neue Fassung")
        out, fehler = self.lauf("liste")
        self.assertIsNone(fehler)
        self.assertIn("- Pitch Q4", out)
        self.assertIn("Pitch.pptx: aus Vertrieb, geändert, nicht übertragen", out)
        self.assertIn("privat:", out)
        out, _ = self.lauf("herkunft", "--bereich=arbeit", "--thema=Pitch Q4", "--", "Pitch.pptx")
        self.assertIn(f"Original: {self.original}", out)

    def test_zeigen_nur_in_ablage(self):
        self.holen()
        out, fehler = self.lauf("zeigen", "--bereich=arbeit", "--thema=Pitch Q4", "--", "Pitch.pptx")
        self.assertIsNone(fehler)
        self.assertEqual(self.geoeffnet.read_text().strip().split("|"), [str(self.kopie)])
        pdf = self.kopie.parent / "Bericht.pdf"
        pdf.write_bytes(b"%PDF-")
        self.assertIsNone(self.lauf("zeigen", "--finder", "--", str(pdf))[1])
        self.assertEqual(self.geoeffnet.read_text().splitlines()[-1].split("|"), ["-R", str(pdf)])
        html = self.kopie.parent / "seite.html"
        html.write_text("<script></script>")
        self.lauf("zeigen", "--", str(html))
        self.assertEqual(self.geoeffnet.read_text().splitlines()[-1].split("|"), ["-R", str(html)])  # nur im Finder
        self.assertIn("Zeigen nur", str(self.lauf("zeigen", "--", str(self.original))[1]))
        neben = self.downloads / "Bericht.pdf"  # 8.0: pdf.ordner von apple zählt nicht mehr, nur die Ablage
        neben.write_bytes(b"%PDF-")
        self.assertIn("Zeigen nur in der Ablage", str(self.lauf("zeigen", "--", str(neben))[1]))
        verweis = self.kopie.parent / "v.pdf"
        verweis.symlink_to(self.original)
        self.assertIn("Verweis", str(self.lauf("zeigen", "--", str(verweis))[1]))

    def test_ablage_datei_fuer_andere_skripte(self):
        self.holen()
        cfg = ablage.config()
        self.assertEqual(ablage.ablage_datei(cfg, "arbeit", "Pitch Q4", "Pitch.pptx"), self.kopie)
        self.assertEqual(ablage.ablage_datei(cfg, "", "", str(self.kopie)), self.kopie.resolve())
        with self.assertRaisesRegex(SystemExit, "Nur Arbeitskopien in der Ablage"):
            ablage.ablage_datei(cfg, "", "", str(self.original))
        with self.assertRaisesRegex(SystemExit, "keine Datei"):
            ablage.ablage_datei(cfg, "", "", str(self.kopie.parent))

    def test_ohne_abschnitt_ablage(self):
        (self.daten / "config.json").write_text(json.dumps({"motor": {}}))
        self.assertIn("Abschnitt ablage", str(self.holen()[1]))


if __name__ == "__main__":
    unittest.main()
