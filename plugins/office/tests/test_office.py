"""Tests für office.py (Vorschau und Nachrechnen mit LibreOffice) und sperren.py. Laufen im Prozess mit Ersatz für
soffice, pdftoppm und sandbox-exec in einem Temp-Ordner mit eigenem Heimordner. Starten nie das echte LibreOffice und
schreiben nie in den echten Datenordner.

Aufruf im Plugin-Ordner: python3 -B -m unittest discover tests
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hilfe  # noqa: E402
import sperren  # noqa: E402

SOFFICE = """#!/bin/bash
# Ersatz für soffice: merkt Argumente und Umgebung. pdf: schreibt je Datei ein PDF in --outdir (außer bei kaputt im
# Namen). xlsx: kopiert die Mappe unverändert (die Testmappen tragen ihre Fehlerwerte schon).
echo "$@" >> "$(dirname "$0")/soffice.txt"
echo "FONTCONFIG_FILE=$FONTCONFIG_FILE" >> "$(dirname "$0")/soffice.txt"
out=""; ziel=""; dateien=()
while [ $# -gt 0 ]; do
  case "$1" in
    --outdir) out="$2"; shift 2 ;;
    --convert-to) ziel="$2"; shift 2 ;;
    -*) shift ;;
    *) dateien+=("$1"); shift ;;
  esac
done
for d in "${dateien[@]}"; do
  n=$(basename "$d"); n="${n%.*}"
  case "$n" in
    *kaputt*) echo "Error: source file could not be loaded" >&2 ;;
    *) if [ "$ziel" = "pdf" ]; then printf '%%PDF aus %s\\n' "$n" > "$out/$n.pdf"; else cp "$d" "$out/$n.xlsx"; fi ;;
  esac
done
"""
PDFTOPPM = """#!/bin/bash
# Ersatz für pdftoppm: -f Seite, letztes Argument der Stamm. Seiten über 3 gibt es nicht.
seite=""; args=("$@")
for ((i=0; i<${#args[@]}; i++)); do [ "${args[$i]}" = "-f" ] && seite="${args[$((i+1))]}"; done
stamm="${args[${#args[@]}-1]}"
[ "$seite" -gt 3 ] && { echo "Wrong page range given" >&2; exit 99; }
printf '\\x89PNG\\r\\n\\x1a\\nSeite %s' "$seite" > "$stamm.png"
"""
SHEET = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1">'
         '<c r="A1"><v>2</v></c><c r="A2"><f>A1*3</f><v>6</v></c>{}</row></sheetData></worksheet>')
FEHLER_ZELLEN = '<c r="A3" t="e"><f>1/0</f><v>#DIV/0!</v></c><c r="B1" t="e"><f>Fehlt!A1</f><v>#REF!</v></c>'


def lade_office():
    spec = importlib.util.spec_from_file_location("office_im_test", PLUGIN / "office.py")
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def mappe(pfad: Path, zellen: str = "") -> Path:
    with zipfile.ZipFile(pfad, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   '<sheet name="Liste" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                   'relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", SHEET.format(zellen))
    return pfad


class OfficeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="office-test-")).resolve()
        self.heim = self.tmp / "heim"
        self.daten = self.heim / "Library" / "Application Support" / "Claude Kits" / "office"
        self.ablage = self.heim / "Downloads" / "Claude Work"
        self.thema = self.ablage / "Pitch Q4"
        for o in (self.daten, self.thema):
            o.mkdir(parents=True)
        self.cfg = {"ablage": {"arbeit": str(self.ablage)},
                    "motor": {"gesperrt": ["~/Kontext"], "umgebung": {"FONTCONFIG_FILE": "/x/fonts.conf",
                                                                       "DYLD_INSERT_LIBRARIES": "/x/böse.dylib"}}}
        (self.daten / "config.json").write_text(json.dumps(self.cfg))
        self.bin = self.tmp / "bin"
        hilfe.sandbox_ersatz(self.bin)
        for name, text in (("soffice", SOFFICE), ("pdftoppm", PDFTOPPM)):
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)
        self.alt_env = {k: os.environ.get(k) for k in ("PATH", "FONTCONFIG_FILE", "KITS_DATENORDNER")}
        os.environ.update(PATH=f"{self.bin}:/usr/bin:/bin", KITS_FEHLERPROTOKOLL="aus")
        os.environ.pop("FONTCONFIG_FILE", None)
        os.environ.pop("KITS_DATENORDNER", None)
        self.o = lade_office()
        self.o.DATEN_DIR, self.o.HEIM = self.daten, self.heim
        self.o.APP_DATEN = self.heim / "Library" / "Application Support" / "Claude Kits"
        self.o.SANDBOX_EXEC = str(self.bin / "sandbox-exec")
        self.o.SOFFICE_MAC = str(self.tmp / "kein-soffice")
        self.vorschau = self.daten / "zwischen" / "vorschau"

    def tearDown(self):
        for k, v in self.alt_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def lauf(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.o.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def pdf(self, datei, *mehr, thema="Pitch Q4"):
        return self.lauf("pdf", "--bereich=arbeit", f"--thema={thema}", *mehr, "--", datei)

    def aufrufe(self) -> str:
        p = self.bin / "soffice.txt"
        return p.read_text() if p.exists() else ""

    def ablage_dateien(self) -> list:
        return sorted(str(p.relative_to(self.ablage)) for p in self.ablage.rglob("*"))

    # ---------- pdf ----------
    def test_pdf_in_den_zwischenordner_mit_sandbox(self):
        (self.thema / "Deck.pptx").write_text("x")
        code, out, err = self.pdf("Deck.pptx", thema="pitch q4")  # Thema ohne Rücksicht auf Groß und Klein
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), f"PDF: {self.vorschau / 'Deck.pdf'}")
        self.assertEqual((self.vorschau / "Deck.pdf").read_text(), "%PDF aus Deck\n")
        self.assertEqual(self.ablage_dateien(), ["Pitch Q4", "Pitch Q4/Deck.pptx"], "nie in die Ablage")
        aufruf = self.aufrufe()
        self.assertIn(f"-env:UserInstallation={(self.daten / 'libreoffice-profil').as_uri()}", aufruf)
        self.assertIn(f"--convert-to pdf --outdir {self.daten / 'staging'}", aufruf)
        self.assertNotIn(str(self.ablage), aufruf)  # LibreOffice sieht nur die Kopie
        self.assertIn("FONTCONFIG_FILE=/x/fonts.conf", aufruf)
        profil = (self.bin / "profil.sb").read_text()
        self.assertIn("(deny network-outbound (remote ip))", profil)
        for ort in ("Library/Mail", "Library/Messages", "Library/Keychains", "Kontext",
                    "Library/Application Support/Claude Kits/apple"):
            self.assertIn(f'(deny file-read* file-write* (subpath "{self.heim / ort}"))', profil)
        self.assertNotIn(f'"{self.daten}"', profil)
        self.assertEqual(list((self.daten / "staging").iterdir()), [], "Kopien wieder weg")
        self.assertEqual(hilfe.profil_uebersetzt(profil), "")

    def test_umgebung_nur_erlaubte_werte(self):
        env = self.o.umgebung(self.cfg)
        self.assertEqual(env["FONTCONFIG_FILE"], "/x/fonts.conf")
        self.assertNotIn("DYLD_INSERT_LIBRARIES", env)

    def test_seiten_als_bilder(self):
        (self.thema / "Deck.pptx").write_text("x")
        code, out, err = self.pdf("Deck.pptx", "--seiten=2,9")
        self.assertEqual(code, 0, err)
        self.assertIn(f"Seite 2: {self.vorschau / 'Deck-2.png'}", out)
        self.assertIn("Seite 9: kein Bild (Wrong page range given)", out)
        self.assertTrue((self.vorschau / "Deck-2.png").read_bytes().startswith(b"\x89PNG"))
        self.assertEqual(self.ablage_dateien(), ["Pitch Q4", "Pitch Q4/Deck.pptx"])
        self.assertEqual(self.pdf("Deck.pptx", "--seiten=1-9")[0], 2, "höchstens 6 Seiten")

    def test_pdf_aus_der_ablage_nur_bilder(self):
        (self.thema / "Plan.pdf").write_bytes(b"%PDF eigen")
        code, out, err = self.pdf("Plan.pdf", "--seiten=1")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.aufrufe(), "", "kein LibreOffice für ein PDF")
        self.assertEqual((self.vorschau / "Plan.pdf").read_bytes(), b"%PDF eigen")
        self.assertIn("Seite 1:", out)

    def test_nur_echte_dateien_aus_der_ablage(self):
        draussen = self.tmp / "Geheim.pptx"
        draussen.write_text("geheim")
        (self.thema / "link.pptx").symlink_to(draussen)
        (self.tmp / "fremd").mkdir()
        (self.tmp / "fremd" / "x.pptx").write_text("geheim")
        (self.ablage / "Verweis").symlink_to(self.tmp / "fremd")
        (self.thema / "notiz.sh").write_text("x")
        (self.thema / "~$Deck.pptx").write_text("")
        faelle = (("link.pptx", "Pitch Q4", "ist ein Verweis"), ("x.pptx", "Verweis", "ist ein Verweis"),
                  ("../Geheim.pptx", "Pitch Q4", "kein Dateiname"), ("fehlt.pptx", "Pitch Q4", "gibt es im Thema"),
                  ("notiz.sh", "Pitch Q4", "Format .sh"), ("~$Deck.pptx", "Pitch Q4", "kein Dateiname"),
                  ("x.pptx", "Gibt es nicht", "gibt es in"), ("x.pptx", "../fremd", "kein Ordnername"))
        for datei, thema, text in faelle:
            code, _out, err = self.pdf(datei, thema=thema)
            self.assertEqual(code, 2, (datei, thema, err))
            self.assertIn(text, err, (datei, thema))
        code, _out, err = self.lauf("pdf", "--bereich=privat", "--thema=Pitch Q4", "--", "x.pptx")
        self.assertEqual(code, 2)
        self.assertIn("keine Ablage eingetragen", err)
        self.assertEqual(self.aufrufe(), "", "LibreOffice lief nie")

    def test_ablage_und_zwischenordner_als_verweis(self):
        (self.thema / "Deck.pptx").write_text("x")
        echt = self.tmp / "woanders"
        echt.mkdir()
        (self.daten / "zwischen").symlink_to(echt)  # Tausch aus der Sandbox des Motors heraus
        code, _out, err = self.pdf("Deck.pptx")
        self.assertEqual(code, 2)
        self.assertIn("ist ein Verweis", err)
        self.assertEqual(list(echt.iterdir()), [])
        (self.daten / "zwischen").unlink()
        shutil.move(str(self.ablage), str(self.tmp / "Ablage echt"))
        self.ablage.symlink_to(self.tmp / "Ablage echt")
        code, _out, err = self.pdf("Deck.pptx")
        self.assertEqual(code, 2)
        self.assertIn("ist ein Verweis oder kein Ordner", err)

    def test_ziel_als_verweis_wird_ersetzt_nicht_verfolgt(self):
        (self.thema / "Deck.pptx").write_text("x")
        self.vorschau.mkdir(parents=True)
        fremd = self.tmp / "wichtig.txt"
        fremd.write_text("bleibt")
        (self.vorschau / "Deck.pdf").symlink_to(fremd)
        code, _out, err = self.pdf("Deck.pptx")
        self.assertEqual(code, 0, err)
        self.assertFalse((self.vorschau / "Deck.pdf").is_symlink())
        self.assertEqual(fremd.read_text(), "bleibt")

    def test_probelauf_gescheitert_und_ohne_libreoffice(self):
        (self.thema / "Deck.pptx").write_text("x")
        code, out, _err = self.pdf("Deck.pptx", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("Probelauf, nichts umgewandelt", out)
        self.assertEqual(self.aufrufe(), "")
        (self.thema / "kaputt.pptx").write_text("x")
        code, _out, err = self.pdf("kaputt.pptx")
        self.assertEqual(code, 1)
        self.assertIn("Kein PDF für kaputt.pptx (LibreOffice: Error: source file could not be loaded)", err)
        (self.bin / "soffice").unlink()
        code, _out, err = self.pdf("Deck.pptx")
        self.assertEqual(code, 1)
        self.assertIn("LibreOffice fehlt", err)

    def test_zeitlimit(self):
        (self.bin / "soffice").write_text("#!/bin/bash\nsleep 5\n")
        (self.thema / "Deck.pptx").write_text("x")
        with contextlib.redirect_stderr(io.StringIO()) as err, contextlib.redirect_stdout(io.StringIO()):
            code = self.o.cmd_pdf(self.cfg, "arbeit", "Pitch Q4", "Deck.pptx", [], False, zeitlimit=1)
        self.assertEqual(code, 1)
        self.assertIn("LibreOffice hängt seit 1 Sekunden", err.getvalue())
        self.assertEqual(list((self.daten / "staging").iterdir()), [])

    def test_aufruf_falsch(self):
        self.assertEqual(self.lauf()[0], 2)
        self.assertEqual(self.lauf("pdf", "--bereich=arbeit", "--thema=T")[0], 2)
        self.assertEqual(self.lauf("pdf", "--ber=arbeit", "--thema=T", "--", "a.pptx")[0], 2)  # keine Abkürzungen
        self.assertEqual(self.lauf("loeschen", "--bereich=arbeit", "--thema=T", "--", "a.pptx")[0], 2)
        self.assertEqual(self.lauf("nachrechnen", "--bereich=arbeit", "--thema=T", "--seiten=1", "--", "a.xlsx")[0], 2)
        self.cfg["motor"]["gesperrt"] = "~/Kontext"
        (self.daten / "config.json").write_text(json.dumps(self.cfg))
        (self.thema / "Deck.pptx").write_text("x")
        code, _out, err = self.pdf("Deck.pptx")
        self.assertEqual(code, 2)
        self.assertIn("motor.gesperrt", err)

    # ---------- nachrechnen ----------
    def nachrechnen(self, datei):
        return self.lauf("nachrechnen", "--bereich=arbeit", "--thema=Pitch Q4", "--", datei)

    def test_nachrechnen_meldet_fehler_je_zelle(self):
        kopie = mappe(self.thema / "Liste.xlsx", FEHLER_ZELLEN)
        vorher = kopie.read_bytes()
        code, out, err = self.nachrechnen("Liste.xlsx")
        self.assertEqual(code, 1, err)
        self.assertIn("3 Formeln in 1 Blättern, 2 Fehler", out)
        self.assertIn("Liste!A3: #DIV/0!", out)
        self.assertIn("Liste!B1: #REF!", out)
        self.assertEqual(kopie.read_bytes(), vorher, "Arbeitskopie unverändert")
        self.assertEqual(self.ablage_dateien(), ["Pitch Q4", "Pitch Q4/Liste.xlsx"])
        xcu = (self.daten / "libreoffice-rechnen" / "user" / "registrymodifications.xcu").read_text()
        self.assertIn('oor:name="OOXMLRecalcMode"', xcu)
        self.assertIn(f"-env:UserInstallation={(self.daten / 'libreoffice-rechnen').as_uri()}", self.aufrufe())
        self.assertIn("--convert-to xlsx", self.aufrufe())

    def test_nachrechnen_ohne_fehler_und_vorhandenes_profil(self):
        mappe(self.thema / "Liste.xlsm")
        xcu = self.daten / "libreoffice-rechnen" / "user" / "registrymodifications.xcu"
        xcu.parent.mkdir(parents=True)
        xcu.write_text('<?xml version="1.0"?>\n<oor:items xmlns:oor="http://openoffice.org/2001/registry">\n'
                       '<item oor:path="/x"><prop oor:name="Eigen"><value>1</value></prop></item>\n</oor:items>\n')
        code, out, err = self.nachrechnen("Liste.xlsm")
        self.assertEqual(code, 0, err)
        self.assertIn("1 Formeln in 1 Blättern, 0 Fehler", out)
        text = xcu.read_text()
        self.assertIn('oor:name="Eigen"', text)
        self.assertEqual(text.count("OOXMLRecalcMode"), 1)
        self.nachrechnen("Liste.xlsm")
        self.assertEqual(xcu.read_text().count("OOXMLRecalcMode"), 1, "nur einmal eingetragen")
        self.assertEqual(self.nachrechnen("Deck.pptx")[0], 2, "nur Mappen")

    # ---------- Schriftschnitte ----------
    def test_schriftschnitte_nur_in_der_kopie(self):
        deck = self.tmp / "schrift.pptx"
        with zipfile.ZipFile(deck, "w") as z:
            z.writestr("ppt/theme/theme1.xml", '<a:theme xmlns:a="a"><a:majorFont><a:latin typeface="Open Sans Bold"/>'
                       '</a:majorFont><a:minorFont><a:latin typeface="Open Sans"/></a:minorFont></a:theme>')
            z.writestr("ppt/slideMasters/slideMaster1.xml", '<p:sldMaster xmlns:p="p" xmlns:a="a"><p:titleStyle>'
                       '<a:lvl1pPr><a:defRPr sz="2000"/></a:lvl1pPr></p:titleStyle></p:sldMaster>')
            z.writestr("ppt/slides/slide1.xml", '<p:sld xmlns:p="p" xmlns:a="a"><a:r><a:rPr lang="de-DE"><a:latin '
                       'typeface="Open Sans Italic"/></a:rPr><a:t>x</a:t></a:r></p:sld>')
        meldung = self.o.schrift_korrigieren(deck, {"Open Sans"})
        self.assertEqual(meldung, ["Open Sans Bold als Open Sans fett", "Open Sans Italic als Open Sans kursiv"])
        with zipfile.ZipFile(deck) as z:
            self.assertIn('typeface="Open Sans"', z.read("ppt/theme/theme1.xml").decode())
            self.assertIn('<a:defRPr b="1" sz="2000"/>', z.read("ppt/slideMasters/slideMaster1.xml").decode())
            self.assertIn('<a:rPr i="1" lang="de-DE">', z.read("ppt/slides/slide1.xml").decode())
        self.assertEqual(self.o.schrift_korrigieren(deck, {"Open Sans"}), [], "zweiter Lauf ändert nichts")


class SperrenTest(unittest.TestCase):
    def test_feste_und_eigene_orte(self):
        heim, app = Path("/Users/test"), Path("/Users/test/Library/Application Support/Claude Kits")
        orte = sperren.orte({"motor": {"gesperrt": ["~/Kontext/", "/Volumes/Geheim", " "]}}, heim, app)
        for ort in ("/Users/test/Library/Mail", "/Users/test/Library/Group Containers/group.com.apple.notes",
                    "/Users/test/.ssh", f"{app}/apple", f"{app}/.fehler.jsonl", "/Users/test/Kontext",
                    "/Volumes/Geheim"):
            self.assertIn(ort, orte)
        self.assertNotIn(f"{app}/office", orte)
        self.assertEqual(len(orte), len(set(orte)))
        regeln = sperren.sperr_regeln(orte + ['/x"y'])
        self.assertIn('(deny file-read* file-write* (subpath "/Users/test/Library/Mail"))', regeln)
        self.assertIn('(deny file-read* file-write* (regex #"^/Users/test/Library/Containers/net\\.whatsapp\\.'
                      'WhatsApp[^/]*(/|$)"))', regeln)
        self.assertFalse([r for r in regeln if '/x"y' in r])

    def test_wie_die_sperren_in_kit_json(self):
        """Was apple und chat im Code-Tab sperren, sperrt auch der Motor."""
        plugins = PLUGIN.parent
        for plugin in ("apple", "chat"):
            kit = plugins / plugin / "kit.json"
            if not kit.is_file():
                continue
            for regel in json.loads(kit.read_text(encoding="utf-8"))["verbote"]:
                if regel.startswith("Read(~/"):
                    ort = regel[len("Read(~/"):-len("/**)")]
                    self.assertIn(ort, sperren.FEST, f"{plugin}: {regel}")

    def test_falsche_angaben(self):
        heim = Path("/Users/test")
        self.assertEqual(sperren.eigene({}, heim), [])
        for falsch in ({"motor": []}, {"motor": {"gesperrt": "x"}}, {"motor": {"gesperrt": [1]}},
                       {"motor": {"gesperrt": ["relativ"]}}, {"motor": {"gesperrt": ["/a/../b"]}},
                       {"motor": {"gesperrt": ['/a"b']}}):
            with self.assertRaises(sperren.Falsch, msg=falsch):
                sperren.eigene(falsch, heim)

    def test_profil_wird_uebersetzt(self):
        regeln = sperren.sperr_regeln(sperren.orte({}, Path("/Users/test"), Path("/Users/test/L/Claude Kits")))
        self.assertEqual(hilfe.profil_uebersetzt("(version 1)\n(allow default)\n" + "\n".join(regeln)), "")


if __name__ == "__main__":
    unittest.main()
