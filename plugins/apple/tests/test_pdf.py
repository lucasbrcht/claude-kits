"""Tests für pdf.py ohne WebKit: Ein Ersatzprogramm (KITS_HTML2PDF) schreibt ein PDF-Stück und meldet eine Seitenzahl.
Geprüft werden erlaubte Ordner, Endung, Zielname, kein Überschreiben ohne --ersetzen und der Abschnitt pdf.

Aufruf im Kit-Ordner: python3 -B -m unittest discover tests
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

import pdf  # noqa: E402

ERSATZ = """#!/bin/sh
# Ersatz für html2pdf: argv quelle ziel [quer]
[ "$ERSATZ_FEHLER" = 1 ] && { echo "Laden fehlgeschlagen" >&2; exit 1; }
printf '%%PDF-ersatz %s\\n' "$3" > "$2"
echo "WebKit plaudert" >&2
echo 3
"""


class PdfTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        wurzel = Path(tmp.name).resolve()
        self.daten, self.erlaubt, self.fremd = wurzel / "daten", wurzel / "Downloads", wurzel / "anderswo"
        for o in (self.daten, self.erlaubt / "Projekt", self.fremd):
            o.mkdir(parents=True)
        programm = wurzel / "ersatz.sh"
        programm.write_text(ERSATZ)
        programm.chmod(0o755)
        self.config({"ordner": [str(self.erlaubt)]})
        for p in (mock.patch.object(pdf, "CONFIG_PATH", self.daten / "config.json"),
                  mock.patch.object(pdf, "DATEN_DIR", self.daten),
                  mock.patch.dict(os.environ, {"KITS_HTML2PDF": str(programm), "KITS_FEHLERPROTOKOLL": "aus"})):
            p.start()
            self.addCleanup(p.stop)
        self.html = self.erlaubt / "Projekt" / "pitch.html"
        self.html.write_text("<p>x</p>")

    def config(self, block):
        inhalt = {"mail": {}} if block is None else {"pdf": block}
        (self.daten / "config.json").write_text(json.dumps(inhalt))

    def lauf(self, *argv):
        """(Ausgabe, Exit-Meldung oder None)."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                pdf.main(list(argv))
            except SystemExit as e:
                return out.getvalue(), e.code
        return out.getvalue(), None

    def test_neu_im_selben_ordner(self):
        out, fehler = self.lauf("--", str(self.html))
        self.assertIsNone(fehler)
        ziel = self.html.with_suffix(".pdf")
        self.assertEqual(out.splitlines(), [f"PDF: {ziel}", "Umfang: 3 Seiten, A4 hoch"])
        self.assertTrue(ziel.read_text().startswith("%PDF-ersatz"))
        self.assertEqual(sorted(p.name for p in self.html.parent.iterdir()), ["pitch.html", "pitch.pdf"])

    def test_quer_und_name(self):
        out, fehler = self.lauf("--quer", "--name=Pitch-Name", "--", str(self.html))
        self.assertIsNone(fehler)
        ziel = self.html.parent / "Pitch-Name.pdf"
        self.assertEqual(ziel.read_text().strip(), "%PDF-ersatz quer")
        self.assertIn("A4 quer", out)

    def test_name_nur_dateiname(self):
        for name in ("../x.pdf", "a/b.pdf", ".versteckt.pdf"):
            _out, fehler = self.lauf(f"--name={name}", "--", str(self.html))
            self.assertIn("nur ein Dateiname", str(fehler), name)
        self.assertFalse(list(self.html.parent.glob("*.pdf")))

    def test_vorhandenes_pdf_nur_mit_ersetzen(self):
        ziel = self.html.with_suffix(".pdf")
        ziel.write_text("alt")
        _out, fehler = self.lauf("--", str(self.html))
        self.assertIn("gibt es", str(fehler))
        self.assertEqual(ziel.read_text(), "alt")
        out, fehler = self.lauf("--ersetzen", "--", str(self.html))
        self.assertIsNone(fehler)
        self.assertIn("vorhandenes PDF ersetzt", out)
        self.assertNotEqual(ziel.read_text(), "alt")

    def test_ersetzen_nur_direkt_hinter_dem_skript(self):
        _out, fehler = self.lauf("--quer", "--ersetzen", "--", str(self.html))
        self.assertIn("direkt hinter dem Skript", str(fehler))

    def test_fehler_laesst_vorhandenes_pdf_stehen(self):
        ziel = self.html.with_suffix(".pdf")
        ziel.write_text("alt")
        with mock.patch.dict(os.environ, {"ERSATZ_FEHLER": "1"}):
            _out, fehler = self.lauf("--ersetzen", "--", str(self.html))
        self.assertIn("Laden fehlgeschlagen", str(fehler))
        self.assertEqual(ziel.read_text(), "alt")

    def test_nur_erlaubte_ordner_und_html(self):
        fremd = self.fremd / "a.html"
        fremd.write_text("<p>x</p>")
        _out, fehler = self.lauf("--", str(fremd))
        self.assertIn("nur unterhalb", str(fehler))
        self.assertFalse((self.fremd / "a.pdf").exists())
        verweis = self.erlaubt / "verweis.html"  # Verweis im erlaubten Ordner auf eine Datei anderswo
        verweis.symlink_to(fremd)
        _out, fehler = self.lauf("--", str(verweis))
        self.assertIn("nur unterhalb", str(fehler))
        text = self.erlaubt / "a.txt"
        text.write_text("x")
        self.assertIn("Nur vorhandene .html", str(self.lauf("--", str(text))[1]))
        self.assertIn("nicht gefunden", str(self.lauf("--", str(self.erlaubt / "fehlt.html"))[1]))
        self.assertIn("absolut", str(self.lauf("--", "pitch.html")[1]))

    def test_abschnitt_pdf_pflicht(self):
        self.config(None)
        self.assertIn("Abschnitt pdf", str(self.lauf("--", str(self.html))[1]))
        self.config({"ordner": str(self.erlaubt)})
        self.assertIn("pdf.ordner muss eine Liste", str(self.lauf("--", str(self.html))[1]))
        self.config({"ordner": []})
        self.assertIn("pdf.ordner muss eine Liste", str(self.lauf("--", str(self.html))[1]))

    def test_aufruf_falsch(self):
        self.assertEqual(self.lauf()[1], 2)
        self.assertEqual(self.lauf("--unbekannt", str(self.html))[1], 2)


if __name__ == "__main__":
    unittest.main()
