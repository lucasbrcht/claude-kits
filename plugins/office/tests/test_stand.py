"""Tests für motor/stand.py und excel.py skript mit erfundenen Mappen: Änderungen des Nutzers in der Arbeitskopie
bleiben über die Runden von Claude erhalten.

Die Skripte brauchen openpyxl. Unter einem Python ohne das Paket startet ein einziger Test diese Datei mit python3.12
neu, ohne python3.12 wird er übersprungen.

Aufruf im Plugin-Ordner: python3 -B -m unittest discover tests
"""
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True
TESTS = Path(__file__).resolve().parent
MOTOR = TESTS.parent / "motor"
sys.path.insert(0, str(TESTS))
import hilfe  # noqa: E402

try:
    import openpyxl
    MIT_PAKETEN = True
except ImportError:
    MIT_PAKETEN = False


if not MIT_PAKETEN:
    class UnterPython312(unittest.TestCase):
        @unittest.skipUnless(hilfe.motor_python(), "python3.12 mit openpyxl fehlt")
        def test_mit_python312(self):
            r = subprocess.run([hilfe.motor_python(), "-B", "-m", "unittest", "-q", "test_stand"], cwd=str(TESTS),
                               capture_output=True, text=True, timeout=600,
                               env={**os.environ, "KITS_FEHLERPROTOKOLL": "aus"})
            self.assertEqual(r.returncode, 0, r.stderr[-4000:])
            self.assertRegex(r.stderr, r"Ran \d+ tests")

else:
    from openpyxl.styles import Font, PatternFill
    from openpyxl.worksheet.table import Table, TableStyleInfo

    sys.path.insert(0, str(MOTOR))
    import excel
    import stand

    RUNDE_1 = """
import sys, openpyxl
from openpyxl.styles import Font
from openpyxl.worksheet.table import Table, TableStyleInfo
wb = openpyxl.load_workbook(sys.argv[1]); ws = wb.active
for c in ws[1]:
    c.font = Font(bold=True, color="000000")
t = Table(displayName="Liste", ref="A1:C6")
t.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
ws.add_table(t)
wb.save(sys.argv[1])
"""
    NEUE_SPALTE = """
import sys, openpyxl
wb = openpyxl.load_workbook(sys.argv[1]); ws = wb.active
ws["D1"] = "Summe"
for z in range(2, 7):
    ws[f"D{z}"] = f"=B{z}*C{z}"
wb.save(sys.argv[1])
"""
    ALLES_NEU = """
import sys, openpyxl
from openpyxl.styles import Font
wb = openpyxl.load_workbook(sys.argv[1]); ws = wb.active
for c in ws[1]:
    c.font = Font(bold=True, color="000000")
ws.tables["Liste"].tableStyleInfo.showRowStripes = True
ws["E1"] = "neu"
wb.save(sys.argv[1])
"""
    X14 = ('<extLst><ext uri="{78C0D931-6437-407d-A8EE-F0AAD7539E65}" xmlns:x14="http://schemas.microsoft.com/office/'
           'spreadsheetml/2009/9/main"><x14:conditionalFormattings><x14:conditionalFormatting xmlns:xm="http://'
           'schemas.microsoft.com/office/excel/2006/main"><x14:cfRule type="dataBar" id="{00000000-0000-0000-0000-'
           '000000000001}"><x14:dataBar minLength="0" maxLength="100"/></x14:cfRule><xm:sqref>B2:B6</xm:sqref>'
           '</x14:conditionalFormatting></x14:conditionalFormattings></ext></extLst>')

    class Runden(unittest.TestCase):
        def setUp(self):
            self.tmp = Path(tempfile.mkdtemp(prefix="stand-test-")).resolve()
            self.thema = self.tmp / "Ablage" / "T"
            self.thema.mkdir(parents=True)
            self.zustand = self.tmp / "daten" / "zwischen" / "zustand"
            self.kopie = self.thema / "Plan.xlsx"
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Plan"
            ws.append(["Posten", "Menge", "Preis"])
            for i in range(1, 6):
                ws.append([f"Posten {i}", i, 2.5 * i])
            wb.save(self.kopie)
            self.original = self.tmp / "Quelle" / "Plan.xlsx"
            self.original.parent.mkdir()
            shutil.copy(self.kopie, self.original)

        def tearDown(self):
            shutil.rmtree(self.tmp, ignore_errors=True)

        def skript(self, code: str, *mehr) -> tuple:
            datei = self.tmp / f"code{len(list(self.tmp.glob('code*')))}.py"
            datei.write_text(code, encoding="utf-8")
            aus, err = io.StringIO(), io.StringIO()
            alt = sys.argv
            sys.argv = ["excel.py", "skript", str(datei), str(self.kopie), "--zustand", str(self.zustand),
                        "--original", str(self.original), *mehr]
            try:
                with contextlib.redirect_stdout(aus), contextlib.redirect_stderr(err):
                    code_ = excel.main()
            finally:
                sys.argv = alt
            return code_, aus.getvalue() + err.getvalue()

        def von_hand(self):
            """Der Nutzer färbt die Kopfzeile rot und schaltet die Bänderung aus, speichert und schließt."""
            wb = openpyxl.load_workbook(self.kopie)
            ws = wb.active
            for c in ws[1]:
                c.font = Font(bold=True, color="FF0000")
            ws.tables["Liste"].tableStyleInfo.showRowStripes = False
            wb.save(self.kopie)

        def blatt(self):
            return openpyxl.load_workbook(self.kopie).active

        def test_aenderungen_von_hand_bleiben(self):
            """Teil B: Runde 1 per Werkzeug, Änderung von Hand, Runde 2 legt nur eine neue Spalte an."""
            code, out = self.skript(RUNDE_1)
            self.assertEqual(code, 0, out)
            self.assertIn("Blatt Plan: Format A1:C1", out)
            self.assertIn("Blatt Plan: Bereich der Tabelle Liste", out)
            self.von_hand()
            code, out = self.skript(NEUE_SPALTE)
            self.assertEqual(code, 0, out)
            self.assertIn("VON HAND  Arbeitskopie seit der letzten Runde von Hand geändert", out)
            self.assertIn("Blatt Plan: Format der Tabelle (Bänderung, Stil) Liste", out)
            self.assertIn("GEÄNDERT in dieser Runde (für die Übergabe):\n  Blatt Plan: Werte D1:D6", out)
            ws = self.blatt()
            self.assertEqual(ws["A1"].font.color.rgb, "00FF0000", "Kopfzeile bleibt rot")
            self.assertFalse(ws.tables["Liste"].tableStyleInfo.showRowStripes, "keine Bänderung")
            self.assertEqual((ws["D1"].value, ws["D4"].value), ("Summe", "=B4*C4"))
            self.assertEqual(sorted(p.name for p in self.thema.iterdir()), ["Plan.xlsx"], "keine Hilfsdateien")

        def test_ueberschneidung_haelt_an(self):
            self.assertEqual(self.skript(RUNDE_1)[0], 0)
            self.von_hand()
            vorher = self.kopie.read_bytes()
            code, out = self.skript(ALLES_NEU)
            self.assertEqual(code, 1, out)
            self.assertIn("HALT  Nichts geschrieben", out)
            self.assertIn("Der Auftrag würde Änderungen von Hand überschreiben:\n  Blatt Plan: Format A1:C1", out)
            self.assertIn("Format der Tabelle (Bänderung, Stil) Liste", out)
            self.assertEqual(self.kopie.read_bytes(), vorher)
            code, out = self.skript(NEUE_SPALTE)
            self.assertEqual(code, 0, "Änderungen von Hand bleiben gemerkt, auch ohne neue Meldung")
            self.assertNotIn("VON HAND", out)
            self.assertEqual(self.skript(ALLES_NEU)[0], 1, "weiter geschützt")
            code, out = self.skript(ALLES_NEU, "--ueberschreiben")
            self.assertEqual(code, 0, out)
            self.assertIn("ÜBERSCHRIEBEN auf Wunsch", out)
            self.assertEqual(self.blatt()["A1"].font.color.rgb, "00000000")

        def test_nur_lesen_schreibt_nicht(self):
            vorher = self.kopie.read_bytes()
            code, out = self.skript("import sys, openpyxl\nwb = openpyxl.load_workbook(sys.argv[1])\n"
                                    "print(wb.active['A2'].value)\nwb.save(sys.argv[1])\n")
            self.assertEqual(code, 0, out)
            self.assertIn("Posten 1", out)
            self.assertIn("Keine Änderung an der Datei, nichts geschrieben", out)
            self.assertEqual(self.kopie.read_bytes(), vorher)

        def test_fehler_im_code_schreibt_nichts(self):
            vorher = self.kopie.read_bytes()
            code, out = self.skript("import sys, openpyxl\nwb = openpyxl.load_workbook(sys.argv[1])\n"
                                    "wb.active['A1'] = 'x'\nwb.save(sys.argv[1])\nraise ValueError('kaputt')\n")
            self.assertEqual(code, 1, out)
            self.assertIn("Fehler im Code, nichts geschrieben", out)
            self.assertIn("ValueError: kaputt", out)
            self.assertEqual(self.kopie.read_bytes(), vorher)
            self.assertEqual(self.skript("import sys\nsys.exit(3)\n")[0], 1)

        def test_verlust_haelt_an(self):
            with zipfile.ZipFile(self.kopie) as z:
                teile = {n: z.read(n) for n in z.namelist()}
            blatt = teile["xl/worksheets/sheet1.xml"].decode("utf-8")
            teile["xl/worksheets/sheet1.xml"] = blatt.replace("</worksheet>", X14 + "</worksheet>").encode("utf-8")
            with zipfile.ZipFile(self.kopie, "w", zipfile.ZIP_DEFLATED) as z:
                for n, d in teile.items():
                    z.writestr(n, d)
            vorher = self.kopie.read_bytes()
            code, out = self.skript("import sys, openpyxl\nwb = openpyxl.load_workbook(sys.argv[1])\n"
                                    "wb.active['E1'] = 'neu'\nwb.save(sys.argv[1])\n")
            self.assertEqual(code, 1, out)
            self.assertIn("openpyxl würde beim Speichern verlieren: bedingte Formatierung (neuere Art)", out)
            self.assertEqual(self.kopie.read_bytes(), vorher)

        def test_offen_und_aufruf(self):
            (self.thema / "~$Plan.xlsx").write_text("")
            code, out = self.skript("print(1)")
            self.assertEqual(code, 1)
            self.assertIn("in Excel offen", out)
            (self.thema / "~$Plan.xlsx").unlink()
            alt = sys.argv
            for args in (["skript"], ["skript", "a.py", str(self.kopie)], ["skript", "a.py", "x.pptx", "--zustand", "z"]):
                sys.argv = ["excel.py", *args]
                try:
                    with contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(excel.main(), 2, args)
                finally:
                    sys.argv = alt

        def test_zellbereiche(self):
            self.assertEqual(stand.zellbereiche(["A1", "B1", "C1", "A2", "B2", "C2", "E5", "AA10"]),
                             ["A1:C2", "E5", "AA10"])
            self.assertEqual(stand.teile("Plan!2026!B3#format"), ("Plan!2026", "B3", "format"))


if __name__ == "__main__":
    unittest.main()
