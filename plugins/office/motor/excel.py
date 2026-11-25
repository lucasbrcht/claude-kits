"""Excel-Arbeitskopie bearbeiten (excel_skript) und nach jeder Runde prüfen (excel_fertig). Die Arbeitskopie legt
arbeitskopie holen im Themen-Ordner der Ablage an, zurück ins Original geht sie nur über arbeitskopie_uebertragen.

Aufruf (der Server gibt die Pfade vor):
  excel.py skript <code.py> <Arbeitskopie.xlsx> --zustand <Ordner> [--original <Original>] [--ueberschreiben]
      Führt den Code von Claude als Runde aus (stand.py): meldet Änderungen von Hand seit der letzten Runde, der Code
      bekommt in sys.argv[1] eine Kopie der Arbeitskopie im Temp-Ordner (gleicher Name). Zurück in die Arbeitskopie
      geht nur, was keine Änderung von Hand überschreibt und nichts verliert, sonst HALT. Danach die geänderten
      Bereiche. Liest der Code nur, bleibt die Arbeitskopie unberührt. Braucht openpyxl.
  excel.py fertig <Arbeitskopie.xlsx> [--original <Original>]
      Prüft die Datei (Zip, XML, Blätter) und nennt die Blätter. HALT (Rückgabewert 1, nichts geändert), wenn die
      Arbeitskopie in Excel offen ist. Ist das Original in Excel offen, ein Hinweis: Excel öffnet nie zwei Mappen
      gleichen Namens zugleich, das Original vorher schließen. Nur Standardbibliothek.
Rückgabewert 0 ohne Fund, 1 bei einem Fund, Fehler im Code, HALT oder offener Arbeitskopie, 2 bei falschem Aufruf.
"""
import os
import runpy
import sys
import traceback
import zipfile
from xml.etree import ElementTree as ET

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gemeinsam import offen_in_office  # noqa: E402

ENDUNGEN = (".xlsx", ".xlsm")
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def pruefe(pfad: str) -> tuple:
    """(Funde, Blattnamen). Zip heil, jedes XML-Teil wohlgeformt, Arbeitsmappe mit Blättern vorhanden."""
    funde, blaetter = [], []
    try:
        with zipfile.ZipFile(pfad) as z:
            defekt = z.testzip()
            if defekt:
                funde.append(f"Zip-Teil defekt: {defekt}")
            namen = set(z.namelist())
            for pflicht in ("[Content_Types].xml", "xl/workbook.xml"):
                if pflicht not in namen:
                    funde.append(f"Teil fehlt: {pflicht}")
            for n in sorted(namen):
                if n.endswith((".xml", ".rels")) and not n.startswith("xl/embeddings/"):
                    try:
                        wurzel = ET.fromstring(z.read(n))
                    except ET.ParseError as x:
                        funde.append(f"XML nicht wohlgeformt: {n} ({x})")
                        continue
                    if n == "xl/workbook.xml":
                        blaetter = [s.get("name") for s in wurzel.iter(NS + "sheet")]
    except (zipfile.BadZipFile, OSError) as x:
        funde.append(f"keine lesbare Excel-Datei: {x}")
    if not blaetter and not funde:
        funde.append("Arbeitsmappe ohne Blätter")
    return funde, blaetter


def fertig(args: list) -> int:
    original = None
    if "--original" in args:
        i = args.index("--original")
        original = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
    if len(args) != 1 or original == "":
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    datei = os.path.abspath(os.path.expanduser(args[0]))
    if not datei.lower().endswith(ENDUNGEN) or not os.path.isfile(datei):
        print(f"Erwartet wird eine Excel-Arbeitskopie (.xlsx, .xlsm): {datei}", file=sys.stderr)
        return 2
    if offen_in_office(datei):
        print(f"HALT  {os.path.basename(datei)} ist in Excel offen. Den Nutzer bitten, das Fenster zu schließen. "
              "Nichts geändert.", file=sys.stderr)
        return 1
    funde, blaetter = pruefe(datei)
    if funde:
        print("NICHT öffnen oder übertragen, Funde beheben:\n  " + "\n  ".join(funde), file=sys.stderr)
        return 1
    print(f"Arbeitskopie geprüft: {datei}\nBlätter ({len(blaetter)}): " + ", ".join(blaetter))
    if original and offen_in_office(original):
        print("HINWEIS  Das Original ist in Excel offen. Excel öffnet nie zwei Mappen gleichen Namens zugleich: "
              "Original schließen, bevor die Arbeitskopie geöffnet wird.")
    return 0


def wert(args: list, name: str):
    """Wert hinter name aus args nehmen, None ohne name, "" ohne Wert."""
    if name not in args:
        return None
    i = args.index(name)
    w = args[i + 1] if i + 1 < len(args) else ""
    del args[i:i + 2]
    return w


def skript(args: list) -> int:
    ueberschreiben = "--ueberschreiben" in args
    args = [a for a in args if a != "--ueberschreiben"]
    zustand, original = wert(args, "--zustand"), wert(args, "--original")
    if len(args) != 2 or not zustand or original == "":
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    code, datei = os.path.abspath(args[0]), os.path.abspath(os.path.expanduser(args[1]))
    if not datei.lower().endswith(ENDUNGEN) or not os.path.isfile(datei) or not os.path.isfile(code):
        print(f"Erwartet werden der Code und eine Excel-Arbeitskopie (.xlsx, .xlsm): {datei}", file=sys.stderr)
        return 2
    import stand  # braucht openpyxl, fertig bleibt bei der Standardbibliothek
    try:
        runde = stand.Runde(datei, zustand, original)
    except stand.Halt as x:
        print(f"HALT  {x}", file=sys.stderr)
        return 1
    try:
        for zeile in runde.meldung_hand():
            print(zeile)
        alt_argv = sys.argv
        sys.argv = [code, runde.arbeit]
        try:
            runpy.run_path(code, run_name="__main__")
        except SystemExit as x:
            if x.code not in (None, 0):
                runde.merken()
                print(f"\nCode endete mit {x.code}. Nichts geschrieben.", file=sys.stderr)
                return 1
        except Exception:  # Fehler im Code von Claude: zeigen, nichts schreiben
            runde.merken()
            zeilen = traceback.format_exc().strip().splitlines()
            print("\nFehler im Code, nichts geschrieben:\n" + "\n".join(zeilen[-12:]), file=sys.stderr)
            return 1
        finally:
            sys.argv = alt_argv
        sys.stdout.flush()
        try:
            ergebnis, zeilen = runde.abschliessen(ueberschreiben)
        except stand.Halt as x:
            print(f"HALT  {x}", file=sys.stderr)
            return 1
        print("\n" + "\n".join(zeilen), file=sys.stderr if ergebnis else sys.stdout)
        return ergebnis
    finally:
        runde.aufraeumen()


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("fertig", "skript"):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    return fertig(sys.argv[2:]) if sys.argv[1] == "fertig" else skript(sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())
