#!/usr/bin/env python3
"""HTML-Datei als PDF drucken, nur mit Bordmitteln von macOS (WebKit über html2pdf.swift), für pdf_aus_html.

Aufruf (für den Server, System-Python der Command Line Tools, ohne Sandbox: WebKit läuft in der Sandbox nicht):
  pdf.py [--ersetzen] [--quer] [--name=<Datei.pdf>] -- <pfad.html>

A4 hoch (mit --quer quer), ohne Ränder, mit Hintergründen und den Schriften des Mac. Das PDF entsteht im Ordner der
HTML-Datei, Name wie die Quelle mit .pdf oder --name (nur ein Dateiname, .pdf wird ergänzt). Ausgabe: Pfad und
Seitenzahl, die Seitenzahl ist die schnelle Prüfung auf Überlauf.

Schutz: Quelle nur unterhalb der Ordner in pdf.ordner der config.json, nur .html oder .htm, keine Hilfsdateien neben
dem Original. Ein vorhandenes PDF ersetzt nur --ersetzen, das der Server erst nach dem Dialog am Mac übergibt
(kit_basis.schalter_vorn: nur direkt hinter dem Skript). Löschen gibt es nicht.

Das Swift-Programm übersetzt das Skript beim ersten Aufruf einmal mit swiftc (etwa 40 Sekunden) nach bin/ im
Datenordner, der Name trägt die Prüfsumme der Quelle: Eine neue Fassung von html2pdf.swift wird so von selbst neu
übersetzt. Exit-Codes: 0 ok, 1 Fehler, 2 Aufruf falsch.
"""
import argparse
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import kit_basis  # Datenordner, config.json, Fehlerprotokoll, gleich in apple und chat

KIT_DIR = Path(__file__).resolve().parent
DATEN_DIR = kit_basis.datenordner(KIT_DIR)
CONFIG_PATH = DATEN_DIR / "config.json"
QUELLE = KIT_DIR / "html2pdf.swift"
SWIFTC = "/usr/bin/swiftc"
ENDUNGEN = (".html", ".htm")
NAME_RE = re.compile(r"[^/\\:\x00-\x1f]{1,120}")
ZEIT_UEBERSETZEN = 150  # Sekunden für swiftc beim ersten Aufruf
ZEIT_DRUCK = 90  # Sekunden je Druck, das Swift-Programm bricht selbst nach 60 ab
FOLGE = "Nichts geschrieben."


def aufruf_falsch(text: str):
    print(text, file=sys.stderr)
    sys.exit(2)


def erlaubte_ordner() -> list:
    """Ordner aus pdf.ordner der config.json, aufgelöst. Ein Text statt einer Liste bricht ab."""
    cfg = kit_basis.lade_config(CONFIG_PATH, folge=FOLGE)
    block = kit_basis.abschnitt(cfg, "pdf", f"Mit einstellungen_schreiben den Abschnitt pdf mit ordner anlegen. {FOLGE}")
    ordner = block.get("ordner", [])
    if (not isinstance(ordner, list) or not ordner
            or not all(isinstance(o, str) and os.path.isabs(os.path.expanduser(o)) for o in ordner)):
        raise kit_basis.abbruch("config.json: pdf.ordner muss eine Liste von Ordnern sein, absolut oder mit ~.", FOLGE)
    return [Path(os.path.expanduser(o)).resolve() for o in ordner]


def quelle_pruefen(angabe: str, ordner: list) -> Path:
    pfad = Path(os.path.expanduser(angabe))
    if not pfad.is_absolute():
        raise kit_basis.abbruch(f"pfad muss absolut sein: {angabe}.", FOLGE)
    try:
        pfad = pfad.resolve(strict=True)
    except (OSError, RuntimeError):
        raise kit_basis.abbruch(f"HTML-Datei nicht gefunden: {angabe}.", FOLGE) from None
    if pfad.suffix.lower() not in ENDUNGEN or not pfad.is_file():
        raise kit_basis.abbruch(f"Nur vorhandene .html-Dateien, nicht {pfad.name}.", FOLGE)
    if not any(o in pfad.parents for o in ordner):
        raise kit_basis.abbruch(f"HTML nur unterhalb von {', '.join(str(o) for o in ordner)}, nicht aus {pfad.parent}.",
                                FOLGE)
    return pfad


def ziel_bestimmen(quelle: Path, name: str) -> Path:
    if not name:
        return quelle.with_suffix(".pdf")
    if not NAME_RE.fullmatch(name) or name.startswith(".") or name.strip() != name:
        raise kit_basis.abbruch(f"name ist nur ein Dateiname ohne Ordner, nicht {name!r}.", FOLGE)
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return quelle.parent / name


def programm() -> Path:
    """Übersetztes html2pdf aus bin/ im Datenordner, beim ersten Aufruf oder nach einer neuen Quelle übersetzen.
    KITS_HTML2PDF setzt ein anderes Programm, nur für die Tests."""
    ersatz = os.environ.get("KITS_HTML2PDF", "").strip()
    if ersatz:
        return Path(ersatz)
    if not QUELLE.is_file():
        raise kit_basis.abbruch(f"html2pdf.swift fehlt im Plugin ({KIT_DIR}).", FOLGE)
    summe = hashlib.sha256(QUELLE.read_bytes()).hexdigest()[:12]
    bin_dir = DATEN_DIR / "bin"
    fertig = bin_dir / f"html2pdf-{summe}"
    if fertig.is_file() and os.access(fertig, os.X_OK) and not fertig.is_symlink():
        return fertig
    if not Path(SWIFTC).exists():
        raise kit_basis.abbruch("swiftc fehlt: Die Command Line Tools installieren (xcode-select --install).", FOLGE)
    bin_dir.mkdir(parents=True, exist_ok=True)
    temp = bin_dir / f".html2pdf-{summe}.{os.getpid()}"
    try:
        lauf = subprocess.run([SWIFTC, "-O", str(QUELLE), "-o", str(temp)], capture_output=True, text=True,
                              timeout=ZEIT_UEBERSETZEN, stdin=subprocess.DEVNULL)
        if lauf.returncode != 0 or not temp.is_file():
            meldung = " ".join(lauf.stderr.split())[-400:]
            raise kit_basis.abbruch(f"html2pdf.swift ließ sich nicht übersetzen: {meldung or lauf.returncode}.", FOLGE)
        os.replace(temp, fertig)
    except subprocess.TimeoutExpired:
        raise kit_basis.abbruch(f"swiftc: keine Antwort nach {ZEIT_UEBERSETZEN} Sekunden.", FOLGE) from None
    finally:
        if temp.exists():
            temp.unlink()
    for alt in bin_dir.glob("html2pdf-*"):  # frühere Fassungen des eigenen Programms
        if alt != fertig and alt.is_file() and not alt.is_symlink():
            alt.unlink()
    return fertig


def seiten_text(n: int) -> str:
    return f"{n} Seite" if n == 1 else f"{n} Seiten"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] and argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    vorn, rest = kit_basis.schalter_vorn(argv, schalter=("--ersetzen",))
    p = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    p.add_argument("--quer", action="store_true")
    p.add_argument("--name", default="")
    p.add_argument("pfad", nargs="?")
    try:
        a = p.parse_args(rest)
    except SystemExit:
        aufruf_falsch(__doc__)
    if not a.pfad:
        aufruf_falsch(f"pfad fehlt (absolute HTML-Datei). {FOLGE}")
    ersetzen = "--ersetzen" in vorn

    quelle = quelle_pruefen(a.pfad, erlaubte_ordner())
    ziel = ziel_bestimmen(quelle, a.name.strip())
    if ziel.is_symlink() or (ziel.exists() and not ziel.is_file()):
        raise kit_basis.abbruch(f"{ziel.name} ist ein Verweis oder keine Datei.", FOLGE)
    if ziel.exists() and not ersetzen:
        raise kit_basis.abbruch(f"{ziel.name} gibt es in {ziel.parent} schon. Ersetzen nur auf ausdrücklichen Wunsch "
                                f"mit ersetzen (Dialog am Mac) oder mit name ein anderer Dateiname.", FOLGE)

    befehl = [str(programm()), str(quelle), str(ziel), *(["quer"] if a.quer else [])]
    try:
        lauf = subprocess.run(befehl, capture_output=True, text=True, timeout=ZEIT_DRUCK, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise kit_basis.abbruch(f"Druck: keine Antwort nach {ZEIT_DRUCK} Sekunden.", FOLGE) from None
    except OSError as e:
        raise kit_basis.abbruch(f"html2pdf nicht startbar: {e.strerror or e}.", FOLGE) from None
    # WebKit schreibt Meldungen ohne Belang auf stderr, entscheidend sind Exit-Code und die letzte Zeile
    letzte = (lauf.stderr or "").strip().splitlines()[-1:] or [""]
    if lauf.returncode != 0:
        raise kit_basis.abbruch(f"PDF-Druck fehlgeschlagen: {letzte[0] or 'Code ' + str(lauf.returncode)}.",
                                "Ein vorhandenes PDF bleibt unverändert.")
    zahl = (lauf.stdout or "").strip().splitlines()[-1:] or [""]
    if not zahl[0].isdigit() or not ziel.is_file():
        raise kit_basis.abbruch("PDF-Druck ohne Ergebnis.", "Ein vorhandenes PDF bleibt unverändert.")
    print(f"PDF: {ziel}")
    print(f"Umfang: {seiten_text(int(zahl[0]))}, A4 {'quer' if a.quer else 'hoch'}"
          + (", vorhandenes PDF ersetzt" if ersetzen else ""))


if __name__ == "__main__":
    kit_basis.starten(main, __file__)
