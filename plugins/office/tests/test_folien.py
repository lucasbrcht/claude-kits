"""Tests für die Folien-Skripte des Motors (motor/lesen.py, aendern.py, uebernehmen.py, pruefen.py, finden.py) mit
erfundenen Decks.

Die Skripte brauchen python-pptx und lxml. Unter einem Python ohne die Pakete (python3, Python der Command Line Tools)
startet ein einziger Test diese Datei mit python3.12 neu und prüft das Ergebnis, ohne python3.12 wird er übersprungen.
Das Testdeck hat Abschnitte, Notizen, alte und neue Kommentare, eine Tabelle, ein Diagramm (mit eingebetteter
Arbeitsmappe), ein eingebettetes Objekt, eine Markierung eines Add-ins, eine Gruppe mit grpFill, einen Änderungsverlauf
und docProps/app.xml mit alten Zählern.

Aufruf im Plugin-Ordner: python3 -B -m unittest discover tests
"""
import contextlib
import io
import json
import os
import re
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
    import pptx  # noqa: F401
    import lxml  # noqa: F401
    MIT_PAKETEN = True
except ImportError:
    MIT_PAKETEN = False


if not MIT_PAKETEN:
    class UnterPython312(unittest.TestCase):
        @unittest.skipUnless(hilfe.motor_python(), "python3.12 mit python-pptx und lxml fehlt")
        def test_mit_python312(self):
            r = subprocess.run([hilfe.motor_python(), "-B", "-m", "unittest", "-q", "test_folien"], cwd=str(TESTS),
                               capture_output=True, text=True, timeout=600,
                               env={**os.environ, "KITS_FEHLERPROTOKOLL": "aus"})
            self.assertEqual(r.returncode, 0, r.stderr[-4000:])
            self.assertRegex(r.stderr, r"Ran \d+ tests")

else:
    from lxml import etree
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    from pptx.opc.package import Part
    from pptx.opc.packuri import PackURI
    from pptx.util import Cm

    sys.path.insert(0, str(MOTOR))
    import aendern
    import finden
    import lesen
    import pruefen
    from gemeinsam import sha256

    P = "http://schemas.openxmlformats.org/presentationml/2006/main"
    A = "http://schemas.openxmlformats.org/drawingml/2006/main"
    R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    P188 = "http://schemas.microsoft.com/office/powerpoint/2018/8/main"
    ABSCHNITTE = ('<p:ext xmlns:p="%s" uri="{521415D9-36F7-43E2-AB2F-B90AF26B5E84}"><p14:sectionLst '
                  'xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main">%s</p14:sectionLst></p:ext>')
    DECKNAME = "Status Projekt Atlas.pptx"

    def teil(prs, name: str, typ: str, xml: str) -> Part:
        return Part(PackURI(name), typ, prs.part.package, xml.encode("utf-8"))

    def ersetze_im_zip(pfad: Path, name: str, inhalt: str):
        with zipfile.ZipFile(pfad) as z:
            teile = {n: z.read(n) for n in z.namelist()}
        teile[name] = inhalt.encode("utf-8")
        with zipfile.ZipFile(pfad, "w", zipfile.ZIP_DEFLATED) as z:
            for n, d in teile.items():
                z.writestr(n, d)

    def testdeck(pfad: Path) -> Path:
        """Fünf Folien: 1 Titel mit Notiz und neuem Kommentar, 2 Tabelle, Diagramm, Markierung, alter Kommentar,
        3 Gruppe mit grpFill und eingebettetem Objekt, 4 und 5 schlicht. Abschnitte Einleitung (1, 2) und Hauptteil."""
        prs = Presentation()
        s1 = prs.slides.add_slide(prs.slide_layouts[1])
        s1.shapes.title.text = "Status Atlas"
        tf = s1.placeholders[1].text_frame
        tf.text = "Start Q3 "
        lauf = tf.paragraphs[0].add_run()
        lauf.text = "2026 geplant"
        lauf.font.bold = True
        tf.add_paragraph().text = "Zweiter Punkt"
        s1.notes_slide.notes_text_frame.text = "Bitte Zahlen aktualisieren\nFolie behalten"

        s2 = prs.slides.add_slide(prs.slide_layouts[5])
        s2.shapes.title.text = "Zahlen"
        tabelle = s2.shapes.add_table(2, 2, Cm(1), Cm(4), Cm(10), Cm(3)).table
        for (z, sp), t in {(0, 0): "Thema", (0, 1): "Stand", (1, 0): "Umzug", (1, 1): "offen"}.items():
            tabelle.cell(z, sp).text = t
        daten = CategoryChartData()
        daten.categories = ["Q1", "Q2"]
        daten.add_series("Team", (3, 5))
        s2.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Cm(12), Cm(4), Cm(10), Cm(6), daten)
        markiert = s2.shapes.add_shape(1, Cm(1), Cm(8), Cm(4), Cm(2))
        markiert.text = "Roadmap"
        rid = s2.part.relate_to(teil(prs, "/ppt/tags/tag49.xml", "application/vnd.openxmlformats-officedocument."
                                     "presentationml.tags+xml", f'<p:tagLst xmlns:p="{P}"><p:tag name="ADDIN" '
                                     'val="1"/></p:tagLst>'), RT.TAGS)
        markiert._element.find(f"{{{P}}}nvSpPr/{{{P}}}nvPr").append(etree.fromstring(
            f'<p:custDataLst xmlns:p="{P}" xmlns:r="{R}"><p:tags r:id="{rid}"/></p:custDataLst>'))

        s3 = prs.slides.add_slide(prs.slide_layouts[6])
        gruppe = s3.shapes.add_group_shape()
        box = gruppe.shapes.add_shape(1, Cm(2), Cm(2), Cm(4), Cm(2))
        box.text = "Team-Box"
        sp = box._element.find(f"{{{P}}}spPr")
        for fill in sp.findall(f"{{{A}}}solidFill"):
            sp.remove(fill)
        sp.find(f"{{{A}}}prstGeom").addnext(etree.fromstring(f'<a:grpFill xmlns:a="{A}"/>'))
        objekt = pfad.parent / "objekt.bin"
        objekt.write_bytes(b"\x00eingebettet\x00")
        s3.shapes.add_ole_object(str(objekt), "Package", Cm(10), Cm(2), Cm(3), Cm(3))
        objekt.unlink()
        for n in (4, 5):
            s = prs.slides.add_slide(prs.slide_layouts[5])
            s.shapes.title.text = f"Folie {n}"

        authors = teil(prs, "/ppt/authors.xml", "application/vnd.ms-powerpoint.authors+xml",
                       f'<p188:authorLst xmlns:p188="{P188}"><p188:author id="{{A1}}" name="Lena Test" initials="LT" '
                       'userId="x" providerId="None"/></p188:authorLst>')
        prs.part.relate_to(authors, "http://schemas.microsoft.com/office/2018/10/relationships/authors")
        neu = teil(prs, "/ppt/comments/modernComment_1.xml", "application/vnd.ms-powerpoint.comments+xml",
                   f'<p188:cmLst xmlns:p188="{P188}" xmlns:a="{A}"><p188:cm id="{{C1}}" authorId="{{A1}}" '
                   'created="2026-10-21T09:00:00.000"><p188:replyLst><p188:reply id="{R1}" authorId="{A1}" '
                   'created="2026-10-21T10:00:00.000"><p188:txBody><a:bodyPr/><a:p><a:r><a:t>Und Folie 4 ins Backup'
                   '</a:t></a:r></a:p></p188:txBody></p188:reply></p188:replyLst><p188:txBody><a:bodyPr/><a:p><a:r>'
                   '<a:t>Bitte Q4 statt Q3</a:t></a:r></a:p></p188:txBody></p188:cm></p188:cmLst>')
        s1.part.relate_to(neu, "http://schemas.microsoft.com/office/2018/10/relationships/comments")
        autoren_alt = teil(prs, "/ppt/commentAuthors.xml", "application/vnd.openxmlformats-officedocument."
                           "presentationml.commentAuthors+xml", f'<p:cmAuthorLst xmlns:p="{P}"><p:cmAuthor id="0" '
                           'name="Max Alt" initials="MA" lastIdx="1" clrIdx="0"/></p:cmAuthorLst>')
        prs.part.relate_to(autoren_alt, RT.COMMENT_AUTHORS)
        alt = teil(prs, "/ppt/comments/comment1.xml", "application/vnd.openxmlformats-officedocument.presentationml."
                   "comments+xml", f'<p:cmLst xmlns:p="{P}"><p:cm authorId="0" dt="2026-10-20T08:00:00.000" idx="1">'
                   '<p:pos x="10" y="10"/><p:text>Umzug ist erledigt</p:text></p:cm></p:cmLst>')
        s2.part.relate_to(alt, RT.COMMENTS)
        verlauf = teil(prs, "/ppt/changesInfos/changesInfo1.xml", "application/vnd.ms-powerpoint.changesinfo+xml",
                       '<pc:chgInfo xmlns:pc="http://schemas.microsoft.com/office/powerpoint/2013/main/command">'
                       '<pc:docChgLst><pc:docChg chg="Test"><pc:chgData name="Bearbeiter Beispiel" userId="S-1"/>'
                       '</pc:docChg></pc:docChgLst></pc:chgInfo>')
        prs.part.relate_to(verlauf, "http://schemas.microsoft.com/office/2016/11/relationships/changesInfo")

        ids = [s.get("id") for s in prs.slides._sldIdLst]
        abschnitte = "".join(f'<p14:section name="{n}" id="{{{g}}}"><p14:sldIdLst>' +
                             "".join(f'<p14:sldId id="{i}"/>' for i in teil_ids) + "</p14:sldIdLst></p14:section>"
                             for n, g, teil_ids in (("Einleitung", "00000000-0000-0000-0000-000000000001", ids[:2]),
                                                    ("Hauptteil", "00000000-0000-0000-0000-000000000002", ids[2:])))
        ext_lst = etree.SubElement(prs.part._element, f"{{{P}}}extLst")
        ext_lst.append(etree.fromstring(ABSCHNITTE % (P, abschnitte)))
        prs.save(pfad)
        alt_app = ('<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
                   'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Slides>58</Slides>'
                   '<Notes>40</Notes><HiddenSlides>3</HiddenSlides><TitlesOfParts><vt:vector size="1" '
                   'baseType="lpstr"><vt:lpstr>Alte Folie</vt:lpstr></vt:vector></TitlesOfParts></Properties>')
        ersetze_im_zip(pfad, "docProps/app.xml", alt_app)
        return pfad

    def eins_png() -> bytes:
        """Kleines PNG (4 x 4 Pixel) ohne PIL."""
        import struct
        import zlib

        def block(typ, daten):
            return struct.pack(">I", len(daten)) + typ + daten + struct.pack(">I", zlib.crc32(typ + daten) & 0xFFFFFFFF)
        roh = b"".join(b"\x00" + b"\x20\x60\xa0" * 4 for _ in range(4))
        return (b"\x89PNG\r\n\x1a\n" + block(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
                + block(b"IDAT", zlib.compress(roh)) + block(b"IEND", b""))

    ALLE_ARTEN = [
        {"art": "text", "folie": 1, "alt": "Q3 2026", "neu": "Q4 2026"},  # über zwei Läufe, der zweite fett
        {"art": "absaetze", "folie": 1, "form": 2, "absaetze": ["Status Atlas: Start verschoben"]},
        {"art": "zelle", "folie": 2, "form": 3, "zeile": 2, "spalte": 2, "neu": "erledigt"},
        {"art": "notizen", "folie": 1, "neu": "Folie behalten"},
        {"art": "backup", "folie": 4},
        {"art": "verschieben", "folie": 3, "nach": 1},
        {"art": "loeschen", "folie": 5},
        {"art": "lage", "folie": 2, "form": 5, "x": 2},
        {"art": "farbe", "folie": 3, "form": 3, "fuellung": "accent2", "schrift": "FFFFFF"},
    ]

    class Basis(unittest.TestCase):
        """Original in Quelle, Arbeitskopie im Thema der Ablage (wie nach arbeitskopie holen), Zustand im
        Zwischenordner."""

        def setUp(self):
            self.tmp = Path(tempfile.mkdtemp(prefix="folien-test-")).resolve()
            self.quelle = self.tmp / "Quelle"
            self.thema = self.tmp / "Ablage" / "Claude Work" / "Atlas"
            self.zustand = self.tmp / "daten" / "zwischen" / "zustand"
            for o in (self.quelle, self.thema):
                o.mkdir(parents=True)
            self.deck = testdeck(self.quelle / DECKNAME)
            self.arbeit = self.thema / DECKNAME
            shutil.copy(self.deck, self.arbeit)
            self.vergleich = self.thema / ("Status Projekt Atlas" + aendern.VERGLEICH)
            self.alt_env = os.environ.pop(pruefen.VALIDATE, None)

        def tearDown(self):
            if self.alt_env is not None:
                os.environ[pruefen.VALIDATE] = self.alt_env
            shutil.rmtree(self.tmp, ignore_errors=True)

        def lauf(self, modul, *args) -> tuple:
            aus, err = io.StringIO(), io.StringIO()
            alt = sys.argv
            sys.argv = [modul.__file__, *map(str, args)]
            try:
                with contextlib.redirect_stdout(aus), contextlib.redirect_stderr(err):
                    try:
                        code = modul.main()
                    except SystemExit as e:
                        code = e.code if isinstance(e.code, int) else 1
                        err.write(str(e.code))
            finally:
                sys.argv = alt
            return code, aus.getvalue() + err.getvalue()

        def aendern(self, eintraege, vergleich=False) -> tuple:
            liste = self.tmp / "liste.json"
            liste.write_text(json.dumps({"aenderungen": eintraege}), encoding="utf-8")
            return self.lauf(aendern, "--original", self.deck, "--ziel", self.arbeit, "--zustand", self.zustand,
                             *(["--vergleich"] if vergleich else []), liste)

        def ergebnis(self):
            return Presentation(self.arbeit)

        def zustand_json(self) -> dict:
            dateien = list(self.zustand.glob("*.json"))
            self.assertEqual(len(dateien), 1, dateien)
            return json.loads(dateien[0].read_text(encoding="utf-8"))

    class LesenTest(Basis):
        def test_uebersicht_mit_abschnitten_kommentaren_und_notizen(self):
            code, out = self.lauf(lesen, self.deck, "--uebersicht")
            self.assertEqual(code, 0, out)
            for text in ("Abschnitt Einleitung", "1 Status Atlas · 1 Kommentar · Notiz: Bitte Zahlen aktualisieren / "
                         "Folie behalten", "2 Zahlen · 1 Kommentar", "Abschnitt Hauptteil", "5 Folie 5"):
                self.assertIn(text, out)

        def test_formen_kommentare_und_filter(self):
            code, out = self.lauf(lesen, self.deck, "--folie", "1-3")
            self.assertEqual(code, 0, out)
            for text in ("Kommentar Lena Test 2026-10-21: Bitte Q4 statt Q3", "Antwort Lena Test: Und Folie 4 ins Backup",
                         "Kommentar Max Alt 2026-10-20: Umzug ist erledigt",
                         "[Tabelle] Table 2: Thema | Stand | Umzug | offen", "[Diagramm]", "[Tags] Rectangle 4: Roadmap",
                         "[OLE]", "Notizen: Bitte Zahlen aktualisieren"):
                self.assertIn(text, out)
            self.assertNotIn("Folie 3 ", self.lauf(lesen, self.deck, "--kommentare")[1])
            nur_notizen = self.lauf(lesen, self.deck, "--notizen")[1]
            self.assertIn("Folie 1 ", nur_notizen)
            self.assertNotIn("Folie 2 ", nur_notizen)
            self.assertEqual(self.lauf(lesen, self.deck, "--folie")[0], 2)

        def test_freihand_bricht_nicht_ab(self):
            """Freihand (p14:contentPart) hat cNvPr im eigenen Namensraum."""
            prs = Presentation(self.deck)
            p14 = "http://schemas.microsoft.com/office/powerpoint/2010/main"
            prs.slides[0].shapes._spTree.append(etree.fromstring(
                f'<p14:contentPart xmlns:p14="{p14}"><p14:nvContentPartPr><p14:cNvPr id="77" name="Freihand 1"/>'
                '</p14:nvContentPartPr></p14:contentPart>'))
            prs.save(self.deck)
            code, out = self.lauf(lesen, self.deck, "--folie", "1")
            self.assertEqual(code, 0, out)
            self.assertIn("Freihand 1", out)

    class AendernTest(Basis):
        def test_alle_arten_in_der_arbeitskopie(self):
            vorher = self.deck.read_bytes()
            code, out = self.aendern(ALLE_ARTEN)
            self.assertEqual(code, 0, out)
            self.assertEqual(self.deck.read_bytes(), vorher, "Original unangetastet")
            zustand = self.zustand_json()
            self.assertEqual(zustand["sha"], sha256(str(self.deck)))
            self.assertEqual(zustand["arbeitskopie"], sha256(str(self.arbeit)))
            self.assertFalse(self.vergleich.exists(), "Vergleich nur mit --vergleich")
            self.assertEqual(sorted(p.name for p in self.thema.iterdir()), [DECKNAME], "keine Hilfsdateien im Thema")
            for text in ("Folie 1 Text: 'Q3 2026' -> 'Q4 2026' (1-mal)",
                         "Folie 2, Form 3 Zelle 2/2: 'offen' -> 'erledigt'",
                         "Notizen: 'Bitte Zahlen aktualisieren\\nFolie behalten' -> 'Folie behalten'",
                         "Folie 4 ausgeblendet, in Abschnitt Backup", "Folie 5 gelöscht",
                         "OK       keine PowerPoint-Fallen", "XSD-Prüfung aus",
                         "Prüfseiten im PDF der Arbeitskopie: 1, 2, 3", "(4 Folien, Original unverändert)"):
                self.assertIn(text, out)
            prs = self.ergebnis()
            self.assertEqual([lesen.titel(s) for s in prs.slides], ["Status Atlas: Start verschoben", "", "Zahlen",
                                                                    "Folie 4"])
            self.assertEqual(prs.slides[0].placeholders[1].text_frame.paragraphs[0].text, "Start Q4 2026 geplant")
            self.assertEqual(lesen.notizen(prs.slides[0]), "Folie behalten")
            self.assertEqual(prs.slides[3]._element.get("show"), "0")
            self.assertEqual([(n, len(ids)) for n, ids in lesen.abschnitte(prs)],
                             [("Einleitung", 3), ("Hauptteil", 0), ("Backup", 1)])
            box = prs.slides[1].shapes[0].shapes[0]._element  # verschobene Folie 3, Form in der Gruppe
            fuellungen = [etree.QName(k).localname for k in box.find(f"{{{P}}}spPr") if k.tag in pruefen.FUELLUNGEN]
            self.assertEqual(fuellungen, ["solidFill"])
            self.assertAlmostEqual(prs.slides[2].shapes[3].left / 360000, 2.0, places=2)
            with zipfile.ZipFile(self.arbeit) as z:
                namen = z.namelist()
                app = z.read("docProps/app.xml").decode()
            self.assertFalse([n for n in namen if "changesInfo" in n])
            self.assertTrue([n for n in namen if n.startswith("ppt/charts/")] and
                            [n for n in namen if n.startswith("ppt/embeddings/oleObject")])
            self.assertIn("<Slides>4</Slides><Notes>1</Notes><HiddenSlides>1</HiddenSlides>", app)
            self.assertNotIn("Alte Folie", app)

        def test_kein_rahmen_und_kein_vorsatz(self):
            self.assertEqual(self.aendern(ALLE_ARTEN[:1])[0], 0)
            for folie in self.ergebnis().slides:
                for form in folie.shapes:
                    self.assertTrue(form.left is None or form.left >= 0, form.name)
            self.assertFalse(list(self.tmp.rglob("Arbeitskopie_*")))

        def test_vergleich_mit_paaren(self):
            self.assertEqual(self.aendern(ALLE_ARTEN, vergleich=True)[0], 0)
            v = Presentation(self.vergleich)
            marken = [s.shapes[-1].text_frame.text for s in v.slides]
            self.assertEqual(marken, [f"Folie {n} {w}" for n in (1, 2, 3) for w in ("vorher", "nachher")])
            self.assertEqual(lesen.titel(v.slides[0]), "Status Atlas")
            self.assertEqual(lesen.titel(v.slides[1]), "Status Atlas: Start verschoben")
            self.assertEqual(pruefen.analyse(str(self.vergleich))[0], ["6 Folien, davon 0 ausgeblendet"])

        def test_vergleich_mit_eingefuegtem_bild(self):
            """Eingefügte Bilder fehlten früher in den Nachher-Folien des Vergleichs."""
            png = self.tmp / "logo.png"
            png.write_bytes(eins_png())
            (self.tmp / "umbau.py").write_text(f"from pptx.util import Cm\ndef umbau(prs):\n    prs.slides[3].shapes."
                                               f"add_picture({str(png)!r}, Cm(1), Cm(1))\n", encoding="utf-8")
            code, out = self.aendern([{"art": "skript", "datei": "umbau.py"}], vergleich=True)
            self.assertEqual(code, 0, out)
            nachher = Presentation(self.vergleich).slides[1]
            bilder = [s for s in nachher.shapes if s.shape_type == 13]  # MSO_SHAPE_TYPE.PICTURE
            self.assertEqual(len(bilder), 1)
            self.assertEqual(bilder[0].image.blob, png.read_bytes())

        def test_offene_und_vom_nutzer_gespeicherte_arbeitskopie(self):
            self.assertEqual(self.aendern(ALLE_ARTEN[:1])[0], 0)
            sperre = self.thema / ("~$" + DECKNAME)
            sperre.write_text("")
            stand = self.arbeit.read_bytes()
            code, out = self.aendern(ALLE_ARTEN[:2])
            self.assertEqual(code, 1, out)
            self.assertIn("in PowerPoint offen", out)
            self.assertEqual(self.arbeit.read_bytes(), stand, "offen: nichts geschrieben")
            sperre.unlink()
            prs = self.ergebnis()  # der Nutzer ändert und speichert in PowerPoint
            prs.slides[4].shapes.title.text = "Vom Nutzer"
            prs.save(self.arbeit)
            code, out = self.aendern(ALLE_ARTEN[:2])
            self.assertEqual(code, 1, out)
            self.assertIn("ab jetzt die Basis", out)
            code, out = self.aendern([{"art": "text", "folie": 4, "alt": "Folie 4", "neu": "Neu"}])
            self.assertEqual(code, 0, out)
            self.assertIn("Basis ist die Fassung des Nutzers", out)
            titel = [lesen.titel(s) for s in self.ergebnis().slides]
            self.assertEqual((titel[0], titel[3], titel[4]), ("Status Atlas", "Neu", "Vom Nutzer"))
            self.assertIn("Q4 2026", self.ergebnis().slides[0].placeholders[1].text_frame.text, "Stand der Basis bleibt")
            self.deck.write_bytes(self.deck.read_bytes() + b" ")  # jemand speichert das Original
            code, out = self.aendern([])
            self.assertEqual(code, 1, out)
            self.assertIn("Basis ist aber die gespeicherte Fassung des Nutzers", out)

        def test_erster_lauf_auf_bearbeiteter_arbeitskopie(self):
            prs = self.ergebnis()  # der Nutzer hat die Arbeitskopie vor dem ersten Lauf bearbeitet
            prs.slides[4].shapes.title.text = "Vorab geändert"
            prs.save(self.arbeit)
            code, out = self.aendern(ALLE_ARTEN[:1])
            self.assertEqual(code, 0, out)
            self.assertIn("Arbeitskopie weicht vom Original ab", out)
            titel = [lesen.titel(s) for s in self.ergebnis().slides]
            self.assertEqual(titel[4], "Vorab geändert")
            self.assertIn("Q4 2026", self.ergebnis().slides[0].placeholders[1].text_frame.text)
            self.assertEqual(self.aendern(ALLE_ARTEN[:1])[0], 0, "zweiter Lauf auf derselben Basis")

        def test_uebertragen_beginnt_neue_runde(self):
            self.assertEqual(self.aendern(ALLE_ARTEN[:1])[0], 0)
            shutil.copy(self.arbeit, self.deck)  # arbeitskopie_uebertragen
            code, out = self.aendern(ALLE_ARTEN[:1])
            self.assertEqual(code, 1, out)
            self.assertIn("neue Runde", out)
            self.assertEqual(list(self.zustand.glob("*")), [])
            code, out = self.aendern([{"art": "text", "folie": 1, "alt": "Q4 2026", "neu": "Q1 2027"}])
            self.assertEqual(code, 0, out)

        def test_fehler_schreiben_nichts(self):
            stand = self.arbeit.read_bytes()
            faelle = (({"art": "text", "folie": 1, "alt": "gibt es nicht", "neu": "x"}, "Text nicht gefunden"),
                      ({"art": "text", "alt": "Folie", "neu": "Seite"}, "Text 2-mal gefunden"),
                      ({"art": "zelle", "folie": 2, "form": 3, "zeile": 9, "spalte": 1, "neu": "x"},
                       "Zelle 9/1 gibt es nicht"),
                      ({"art": "absaetze", "folie": 2, "form": 99, "absaetze": []}, "Form 99 fehlt"),
                      ({"art": "zaubern", "folie": 1}, "unbekannte Art"),
                      ({"art": "backup", "folie": 9}, "Folie 9 gibt es nicht"),
                      ({"art": "notizen", "folie": 2, "neu": "neu"}, "Notizseite mit Notizfeld"),
                      ({"art": "lage", "folie": 3, "form": 3, "x": 1}, "die ganze Gruppe verschieben"))
            for eintrag, meldung in faelle:
                code, out = self.aendern([ALLE_ARTEN[0], eintrag])
                self.assertEqual(code, 1, out)
                self.assertIn(meldung, out)
                self.assertIn("NICHTS geschrieben", out)
                self.assertEqual(self.arbeit.read_bytes(), stand)
            code, out = self.aendern([ALLE_ARTEN[0], "kein Objekt"])
            self.assertEqual(code, 2, out)
            self.assertIn("Liste von Objekten", out)

        def test_falscher_aufruf(self):
            liste = self.tmp / "liste.json"
            liste.write_text('{"aenderungen": []}')
            self.assertEqual(self.lauf(aendern, "--original", self.deck, liste)[0], 2)
            self.assertEqual(self.lauf(aendern, "--original", self.deck, "--ziel", self.tmp / "fehlt.pptx",
                                       "--zustand", self.zustand, liste)[0], 2)

        def test_text_mit_form_ohne_folie(self):
            code, out = self.aendern([{"art": "text", "form": 3, "alt": "Q3 2026", "neu": "Q4 2026"}])
            self.assertEqual(code, 0, out)
            self.assertIn("'Q3 2026' -> 'Q4 2026' (1-mal)", out)
            self.assertEqual(self.aendern([{"art": "text", "alt": "Folie", "neu": "Seite", "alle": True}])[0], 0)

        def test_ruecknahme_und_neuer_stand_des_originals(self):
            self.assertEqual(self.aendern(ALLE_ARTEN[:2])[0], 0)
            code, out = self.aendern(ALLE_ARTEN[1:2])  # Eintrag 1 gestrichen: Q3 kommt zurück
            self.assertEqual(code, 0, out)
            self.assertIn("Q3 2026", self.ergebnis().slides[0].placeholders[1].text_frame.text)
            prs = Presentation(self.deck)  # jemand speichert das Original
            prs.slides[3].shapes.title.text = "Neu von Lena"
            prs.save(self.deck)
            code, out = self.aendern(ALLE_ARTEN[1:2])
            self.assertIn("HINWEIS  Original seit dem letzten Lauf geändert", out)
            self.assertEqual(lesen.titel(self.ergebnis().slides[3]), "Neu von Lena")

        def test_backup_und_verschieben_ohne_abschnitte(self):
            for pfad in (self.deck, self.arbeit):
                prs = Presentation(pfad)
                ext = prs.part._element.find(f"{{{P}}}extLst")
                ext.getparent().remove(ext)
                prs.save(pfad)
            shutil.copy(self.deck, self.arbeit)
            self.assertEqual(self.aendern([{"art": "verschieben", "folie": 5, "nach": 0}])[0], 0)
            self.assertEqual(lesen.titel(self.ergebnis().slides[0]), "Folie 5")
            self.assertEqual(lesen.abschnitte(self.ergebnis()), [])
            self.assertEqual(self.aendern([{"art": "backup", "folie": 1}])[0], 0)
            self.assertEqual([(n, len(i)) for n, i in lesen.abschnitte(self.ergebnis())],
                             [("Standardabschnitt", 4), ("Backup", 1)])
            self.assertEqual(lesen.titel(self.ergebnis().slides[4]), "Status Atlas")

        def test_skript_als_notausgang(self):
            (self.tmp / "umbau.py").write_text("def umbau(prs):\n    prs.slides[3].shapes.title.text = 'Per Skript'\n"
                                               "    return [4]\n", encoding="utf-8")
            code, out = self.aendern([{"art": "skript", "datei": "umbau.py"}])
            self.assertEqual(code, 0, out)
            self.assertIn("Skript umbau.py: Folien 4", out)
            self.assertEqual(lesen.titel(self.ergebnis().slides[3]), "Per Skript")

        def test_skript_ohne_rueckgabe_erkennt_geaenderte_folien(self):
            (self.tmp / "umbau.py").write_text("def umbau(prs):\n    prs.slides[1].shapes.title.text = 'Neu'\n"
                                               "    prs.slides[3].shapes.title.text = 'Auch neu'\n", encoding="utf-8")
            code, out = self.aendern([{"art": "skript", "datei": "umbau.py"}], vergleich=True)
            self.assertEqual(code, 0, out)
            self.assertIn("Skript umbau.py: Folien 2, 4", out)
            v = Presentation(self.vergleich)
            self.assertEqual([s.shapes[-1].text_frame.text for s in v.slides],
                             [f"Folie {n} {w}" for n in (2, 4) for w in ("vorher", "nachher")])

        def test_lage_fuer_platzhalter_mit_lage_aus_dem_layout(self):
            titel = Presentation(self.deck).slides[3].shapes.title
            self.assertIsNone(titel._element.find(f"{{{P}}}spPr/{{{A}}}xfrm"), "Testdeck: Titel erbt die Lage")
            code, out = self.aendern([{"art": "lage", "folie": 4, "form": titel.name, "b": 20}])
            self.assertEqual(code, 0, out)
            neu = self.ergebnis().slides[3].shapes.title
            self.assertAlmostEqual(neu.width / 360000, 20.0, places=2)
            self.assertEqual((neu.left, neu.top, neu.height), (titel.left, titel.top, titel.height))
            self.assertIn("Folie 4, Form Title 1 Lage:", out)

    class UebernehmenTest(Basis):
        """Folien aus einem zweiten Deck und aus demselben übernehmen: jedes Teil eine eigene Kopie, Layout nach
        Namen, Kommentare bleiben weg."""

        def setUp(self):
            super().setUp()
            (self.tmp / "B").mkdir()
            self.b = testdeck(self.tmp / "B" / "Quelle Beispiel.pptx")

        def teile_je_folie(self, pfad) -> dict:
            with zipfile.ZipFile(pfad) as z:
                return {n: set(re.findall(r'Target="\.\./((?:charts|embeddings|tags)/[^"]+)"', z.read(n).decode()))
                        for n in z.namelist() if re.fullmatch(r"ppt/slides/_rels/slide\d+\.xml\.rels", n)}

        def test_aus_zweitem_deck_mit_eigenen_teilen(self):
            code, out = self.aendern([
                {"art": "uebernehmen", "quelle": str(self.b), "folie": 2, "nach": 1, "als": "zahlen"},
                {"art": "uebernehmen", "quelle": str(self.b), "folie": 3, "nach": "zahlen", "als": "ole"},
                {"art": "uebernehmen", "quelle": str(self.b), "folie": 1, "nach": 0},
                {"art": "zelle", "folie": "zahlen", "form": 3, "zeile": 2, "spalte": 2, "neu": "erledigt"},
            ], vergleich=True)
            self.assertEqual(code, 0, out)
            self.assertIn("Folie zahlen aus Quelle Beispiel.pptx (dort Folie 2) hinter Folie 1", out)
            self.assertIn("OK       keine PowerPoint-Fallen", out)
            prs = self.ergebnis()
            self.assertEqual([lesen.titel(s) for s in prs.slides],
                             ["Status Atlas", "Status Atlas", "Zahlen", "", "Zahlen", "", "Folie 4", "Folie 5"])
            self.assertEqual(prs.slides[2].shapes[1].table.cell(1, 1).text, "erledigt")
            self.assertEqual(prs.slides[4].shapes[1].table.cell(1, 1).text, "offen", "eigene Folie unverändert")
            self.assertEqual(lesen.notizen(prs.slides[0]), "Bitte Zahlen aktualisieren\nFolie behalten")
            self.assertEqual(lesen.kommentare(prs.slides[0], lesen.autoren(prs.part)), [], "Kommentare bleiben weg")
            self.assertEqual([(n, len(i)) for n, i in lesen.abschnitte(prs)], [("Einleitung", 5), ("Hauptteil", 3)])
            teile = [t for t in self.teile_je_folie(self.arbeit).values() if t]
            alle = [x for t in teile for x in t]
            self.assertEqual(len(alle), len(set(alle)), f"geteilte Teile: {teile}")
            self.assertEqual(len([x for x in alle if x.startswith("charts/")]), 2)
            v = Presentation(self.vergleich)
            self.assertEqual([s.shapes[-1].text_frame.text for s in v.slides],
                             ["Folie zahlen neu", "Folie ole neu", "Folie neu1 neu"])

        def test_aus_demselben_deck_und_layout(self):
            code, out = self.aendern([{"art": "uebernehmen", "quelle": str(self.deck), "folie": 2, "nach": 2}])
            self.assertEqual(code, 0, out)
            self.assertEqual(lesen.titel(self.ergebnis().slides[2]), "Zahlen")
            prs = Presentation(self.b)
            prs.slides[1].slide_layout._element.cSld.set("name", "Sonderlayout")
            prs.save(self.b)
            eintrag = {"art": "uebernehmen", "quelle": str(self.b), "folie": 2, "nach": 1}
            code, out = self.aendern([eintrag])
            self.assertEqual(code, 1)
            self.assertIn("Layout 'Sonderlayout' fehlt im Ziel", out)
            self.assertEqual(self.aendern([dict(eintrag, layout="Title Only")])[0], 0)
            for falsch, meldung in (({"folie": 9}, "gibt es in der Quelle nicht"), ({"als": 3}, "als 3 geht nicht"),
                                    ({"nach": 42}, "nach 42 gibt es nicht"), ({"quelle": "/fehlt.pptx"}, "Quelle fehlt")):
                code, out = self.aendern([dict(eintrag, layout="Title Only", **falsch)])
                self.assertEqual(code, 1, out)
                self.assertIn(meldung, out)

    class PruefenTest(Basis):
        def variante(self, aendern_fn) -> Path:
            prs = Presentation(self.deck)
            aendern_fn(prs)
            ziel = self.tmp / f"variante{len(list(self.tmp.glob('variante*')))}.pptx"
            prs.save(ziel)
            return ziel

        def pruefen(self, *args):
            return self.lauf(pruefen, *args, "--ohne-xsd")

        def test_altlasten_im_original_und_baseline(self):
            code, out = self.pruefen(self.deck)
            self.assertEqual(code, 1, out)
            self.assertIn("Änderungsverlauf", out)
            self.assertIn("Zähler Slides 58 statt 5, Notes 40 statt 1, HiddenSlides 3 statt 0", out)
            code, out = self.pruefen(self.deck, "--original", self.deck)
            self.assertEqual(code, 0, out)
            self.assertIn("ORIGINAL docProps/app.xml", out)

        def test_geteilte_markierungen_teile_und_fuellungen(self):
            def kopierte_markierung(prs):
                el = prs.slides[1].shapes[3]._element
                kopie = el.__copy__()
                kopie.find(f".//{{{P}}}cNvPr").set("id", "77")
                el.addnext(kopie)

            def geteiltes_teil(prs):
                quelle = prs.slides[1].part
                chart = next(r.target_part for r in quelle.rels.values() if r.reltype == RT.CHART)
                prs.slides[3].part.relate_to(chart, RT.CHART)

            def zwei_fuellungen(prs):
                sp = prs.slides[2].shapes[0].shapes[0]._element.find(f"{{{P}}}spPr")
                sp.append(etree.fromstring(f'<a:solidFill xmlns:a="{A}"><a:srgbClr val="6E6E6E"/></a:solidFill>'))

            for fn, text in ((kopierte_markierung, "Markierung rId"), (geteiltes_teil, "ppt/charts/chart"),
                             (zwei_fuellungen, "1 Elemente mit mehreren Füllungen (Form-IDs 3)")):
                code, out = self.pruefen(self.variante(fn), "--original", self.deck)
                self.assertEqual(code, 1, out)
                self.assertIn(text, out)

        def test_eingebettete_objekte_duerfen_geteilt_sein(self):
            def geteiltes_objekt(prs):
                ole = next(r.target_part for r in prs.slides[2].part.rels.values() if r.reltype == RT.OLE_OBJECT)
                prs.slides[3].part.relate_to(ole, RT.OLE_OBJECT)
            self.assertEqual(self.pruefen(self.variante(geteiltes_objekt), "--original", self.deck)[0], 0)

        def test_xsd_nur_mit_pfad(self):
            code, out = self.lauf(pruefen, self.deck, "--original", self.deck)
            self.assertEqual(code, 0, out)
            self.assertIn("XSD-Prüfung aus", out)
            os.environ[pruefen.VALIDATE] = str(self.tmp / "fehlt.py")
            try:
                self.assertIn("validate.py nicht gefunden", self.lauf(pruefen, self.deck, "--original", self.deck)[1])
                gut = self.tmp / "validate.py"
                gut.write_text("import sys\nprint('ok', sys.argv[1:])\n")
                os.environ[pruefen.VALIDATE] = str(gut)
                self.assertIn("OK       XSD", self.lauf(pruefen, self.deck, "--original", self.deck)[1])
                gut.write_text("import sys\nprint('Fehler in slide1.xml')\nsys.exit(1)\n")
                code, out = self.lauf(pruefen, self.deck, "--original", self.deck)
                self.assertEqual(code, 1)
                self.assertIn("Fehler in slide1.xml", out)
            finally:
                os.environ.pop(pruefen.VALIDATE, None)

        def test_laeuft_unter_python3_ohne_pakete(self):
            py3 = "/usr/bin/python3"
            if not os.path.exists(py3):
                self.skipTest("kein System-Python")
            r = subprocess.run([py3, "-I", str(MOTOR / "pruefen.py"), str(self.deck), "--ohne-xsd"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertIn("Änderungsverlauf", r.stdout)

    class FindenTest(Basis):
        def test_name_link_und_inhalt(self):
            (self.quelle / "Unterordner").mkdir()
            shutil.copy(self.deck, self.quelle / "Unterordner" / "Atlas Review.pptx")
            (self.quelle / "~$Atlas Review.pptx").write_text("")
            code, out = self.lauf(finden, "atlas", "review", "--ordner", self.quelle)
            self.assertEqual(code, 0, out)
            self.assertIn("1 Treffer (Name: atlas, review)", out)
            link = ("https://firma.sharepoint.com/:p:/r/sites/Team/_layouts/15/Doc.aspx?sourcedoc=%7BX%7D"
                    "&file=Status%20Projekt%20Atlas.pptx&action=edit")
            code, out = self.lauf(finden, link, "--ordner", self.quelle)
            self.assertIn(f"1 Treffer (Link: {DECKNAME})", out)
            self.assertIn(str(self.deck), out)
            code, out = self.lauf(finden, "Umzug", "offen", "--inhalt", "--ordner", self.quelle)
            self.assertEqual(code, 0, out)
            self.assertIn("2 Decks mit Treffern (Inhalt: Umzug, offen), 2 durchsucht", out)
            self.assertIn("Folie 2: Zahlen Thema Stand Umzug offen", out)
            self.assertEqual(self.lauf(finden, "gibtsnicht", "--ordner", self.quelle)[0], 1)
            self.assertEqual(self.lauf(finden, "https://x/Doc.aspx?id=1", "--ordner", self.quelle)[0], 2)
            self.assertEqual(self.lauf(finden, "atlas")[0], 2, "ohne Ordner")


if __name__ == "__main__":
    unittest.main()
