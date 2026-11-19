"""Tests für motor/excel.py (excel_fertig) mit erfundenen Mappen, nur Standardbibliothek: Prüfung von Zip, XML und
Blättern, HALT bei offener Arbeitskopie, Hinweis bei offenem Original gleichen Namens.

Aufruf im Plugin-Ordner: python3 -B -m unittest discover tests
"""
import contextlib
import io
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True
MOTOR = Path(__file__).resolve().parent.parent / "motor"
sys.path.insert(0, str(MOTOR))
import excel  # noqa: E402

WORKBOOK = ('<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>{}</sheets>'
            '</workbook>')


def mappe(pfad: Path, blaetter=("Liste", "Plan"), kaputt: str = "") -> Path:
    with zipfile.ZipFile(pfad, "w") as z:
        z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("xl/workbook.xml", WORKBOOK.format("".join(f'<sheet name="{b}" sheetId="{i}" r:id="rId{i}"/>'
                                                              for i, b in enumerate(blaetter, 1))))
        if kaputt:
            z.writestr(kaputt, "<offen>")
    return pfad


class FertigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="excel-test-")).resolve()
        self.thema = self.tmp / "Ablage" / "T"
        self.quelle = self.tmp / "Quelle"
        for o in (self.thema, self.quelle):
            o.mkdir(parents=True)
        self.kopie = mappe(self.thema / "Liste.xlsx")
        self.original = mappe(self.quelle / "Liste.xlsx")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def lauf(self, *args):
        aus, err = io.StringIO(), io.StringIO()
        alt = sys.argv
        sys.argv = ["excel.py", *map(str, args)]
        try:
            with contextlib.redirect_stdout(aus), contextlib.redirect_stderr(err):
                code = excel.main()
        finally:
            sys.argv = alt
        return code, aus.getvalue() + err.getvalue()

    def test_prueft_und_nennt_blaetter(self):
        code, out = self.lauf("fertig", self.kopie, "--original", self.original)
        self.assertEqual(code, 0, out)
        self.assertIn("Blätter (2): Liste, Plan", out)
        self.assertNotIn("HINWEIS", out)
        self.assertEqual(sorted(p.name for p in self.thema.iterdir()), ["Liste.xlsx"], "keine Begleitdateien")

    def test_funde(self):
        for datei, text in ((mappe(self.thema / "a.xlsx", kaputt="xl/worksheets/sheet1.xml"), "XML nicht wohlgeformt"),
                            (mappe(self.thema / "b.xlsx", blaetter=()), "Arbeitsmappe ohne Blätter")):
            code, out = self.lauf("fertig", datei)
            self.assertEqual(code, 1, out)
            self.assertIn(text, out)
        (self.thema / "c.xlsx").write_bytes(b"kein zip")
        self.assertIn("keine lesbare Excel-Datei", self.lauf("fertig", self.thema / "c.xlsx")[1])

    def test_offen_halt_und_hinweis(self):
        (self.thema / "~$Liste.xlsx").write_text("")
        code, out = self.lauf("fertig", self.kopie)
        self.assertEqual(code, 1)
        self.assertIn("HALT", out)
        (self.thema / "~$Liste.xlsx").unlink()
        (self.quelle / "~$Liste.xlsx").write_text("")
        code, out = self.lauf("fertig", self.kopie, "--original", self.original)
        self.assertEqual(code, 0, out)
        self.assertIn("Excel öffnet nie zwei Mappen gleichen Namens zugleich", out)

    def test_falsche_aufrufe(self):
        for args in ((), ("start", self.kopie), ("fertig",), ("fertig", self.tmp / "fehlt.xlsx"),
                     ("fertig", self.kopie, "--original"), ("fertig", self.tmp / "a.pptx")):
            self.assertEqual(self.lauf(*args)[0], 2, args)


if __name__ == "__main__":
    unittest.main()
