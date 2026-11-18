"""Tests für skills/dateien/scripts/sprache.py: Sprache der Präsentation erkennen, lang an allen Textstellen setzen,
Vorgaben ergänzen, --pruefen ändert nichts, .docx mit w:lang. Kleine Office-Dateien entstehen im Temp-Ordner.

Aufruf im Plugin-Ordner: python3 -B -m unittest discover tests
"""
import contextlib
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN / "skills" / "dateien" / "scripts"))

import sprache  # noqa: E402

FOLIE = ('<p:sld xmlns:a="a" xmlns:p="p"><p:txBody><a:p><a:r><a:rPr lang="{a}" dirty="0"/><a:t>Hallo</a:t></a:r>'
         '<a:r><a:rPr lang="{b}" altLang="en-US"/><a:t>Welt</a:t></a:r><a:endParaRPr lang="{c}"/></a:p>'
         '</p:txBody></p:sld>')
PRAESENTATION = ('<p:presentation xmlns:a="a" xmlns:p="p"><p:defaultTextStyle><a:lvl1pPr><a:defRPr sz="1800">'
                 '<a:latin typeface="+mn-lt"/></a:defRPr></a:lvl1pPr><a:lvl2pPr><a:defRPr lang="en-US"/></a:lvl2pPr>'
                 '</p:defaultTextStyle></p:presentation>')
MASTER = '<p:sldMaster xmlns:a="a" xmlns:p="p"><p:txStyles><a:defRPr/></p:txStyles></p:sldMaster>'
LAYOUT = '<p:sldLayout xmlns:a="a" xmlns:p="p"><a:rPr lang="en-GB"/><a:defRPr/></p:sldLayout>'


class SpracheTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ordner = Path(tmp.name)

    def pptx(self, folien) -> Path:
        pfad = self.ordner / "Pitch.pptx"
        with zipfile.ZipFile(pfad, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("ppt/presentation.xml", PRAESENTATION)
            for i, folie in enumerate(folien, 1):
                z.writestr(f"ppt/slides/slide{i}.xml", folie)
            z.writestr("ppt/slideMasters/slideMaster1.xml", MASTER)
            z.writestr("ppt/slideLayouts/slideLayout1.xml", LAYOUT)
            z.writestr("ppt/media/bild.png", b"\x89PNG lang=\"en-US\"", compress_type=zipfile.ZIP_STORED)
        return pfad

    def lauf(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                sprache.main(list(argv))
            except SystemExit as e:
                return out.getvalue() + err.getvalue(), e.code
        return out.getvalue(), 0

    def teil(self, pfad, name) -> str:
        with zipfile.ZipFile(pfad) as z:
            return z.read(name).decode()

    def test_setzt_auf_sprache_der_praesentation(self):
        pfad = self.pptx([FOLIE.format(a="de-DE", b="en-US", c="de-DE"), FOLIE.format(a="de-DE", b="de-DE", c="en-US")])
        out, code = self.lauf(str(pfad))
        self.assertEqual(code, 0, out)
        self.assertIn("de-DE (Sprache der Präsentation)", out)
        for name in ("ppt/slides/slide1.xml", "ppt/slides/slide2.xml", "ppt/slideLayouts/slideLayout1.xml",
                     "ppt/presentation.xml", "ppt/slideMasters/slideMaster1.xml"):
            text = self.teil(pfad, name)
            self.assertNotIn('lang="en', text.replace('altLang="en-US"', ""), name)
        self.assertIn('<a:defRPr lang="de-DE" sz="1800">', self.teil(pfad, "ppt/presentation.xml"))
        self.assertIn('<a:defRPr lang="de-DE"/>', self.teil(pfad, "ppt/slideMasters/slideMaster1.xml"))
        self.assertIn('<a:defRPr/>', self.teil(pfad, "ppt/slideLayouts/slideLayout1.xml"))  # erbt, keine Vorgabe
        self.assertIn('altLang="en-US"', self.teil(pfad, "ppt/slides/slide1.xml"))
        with zipfile.ZipFile(pfad) as z:
            self.assertEqual(z.read("ppt/media/bild.png"), b"\x89PNG lang=\"en-US\"")
            self.assertEqual(z.namelist()[0], "[Content_Types].xml")
            self.assertEqual(z.getinfo("ppt/media/bild.png").compress_type, zipfile.ZIP_STORED)
        self.assertEqual([p.name for p in self.ordner.iterdir()], ["Pitch.pptx"])  # keine Temp-Datei bleibt
        out, _ = self.lauf(str(pfad))
        self.assertIn("nichts geändert", out)

    def test_pruefen_aendert_nichts(self):
        pfad = self.pptx([FOLIE.format(a="en-US", b="en-US", c="de-DE")])
        vorher = pfad.read_bytes()
        out, code = self.lauf(str(pfad), "--pruefen")
        self.assertEqual(code, 0)
        self.assertIn("en-US (Sprache der Präsentation)", out)
        self.assertIn("de-DE 1", out)
        self.assertEqual(pfad.read_bytes(), vorher)

    def test_sprache_angeben(self):
        pfad = self.pptx([FOLIE.format(a="de-DE", b="de-DE", c="de-DE")])
        out, code = self.lauf(str(pfad), "--sprache=en-US")
        self.assertEqual(code, 0)
        self.assertNotIn('lang="de-DE"', self.teil(pfad, "ppt/slides/slide1.xml"))
        self.assertEqual(self.lauf(str(pfad), "--sprache=deutsch")[1], 2)

    def test_docx(self):
        pfad = self.ordner / "Brief.docx"
        with zipfile.ZipFile(pfad, "w") as z:
            z.writestr("word/document.xml", '<w:document><w:r><w:rPr><w:lang w:val="de-DE"/></w:rPr></w:r>'
                                            '<w:r><w:rPr><w:lang w:val="de-DE"/></w:rPr></w:r>'
                                            '<w:r><w:rPr><w:lang w:val="en-US" w:eastAsia="ja-JP"/></w:rPr></w:r>'
                                            '</w:document>')
            z.writestr("word/styles.xml", '<w:styles><w:rPrDefault><w:lang w:val="en-GB"/></w:rPrDefault></w:styles>')
        out, code = self.lauf(str(pfad))
        self.assertEqual(code, 0, out)
        self.assertNotIn('w:val="en', self.teil(pfad, "word/document.xml") + self.teil(pfad, "word/styles.xml"))
        self.assertIn('w:eastAsia="ja-JP"', self.teil(pfad, "word/document.xml"))

    def test_falsche_dateien(self):
        andere = self.ordner / "a.xlsx"
        andere.write_bytes(b"x")
        self.assertEqual(self.lauf(str(andere))[1], 2)
        kaputt = self.ordner / "b.pptx"
        kaputt.write_bytes(b"kein zip")
        self.assertEqual(self.lauf(str(kaputt))[1], 1)
        self.assertEqual(self.lauf(str(self.ordner / "fehlt.pptx"))[1], 1)


if __name__ == "__main__":
    unittest.main()
