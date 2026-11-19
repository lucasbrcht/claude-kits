#!/usr/bin/env python3
"""Vorschau und Nachrechnen mit LibreOffice für die Werkzeuge office_vorschau und excel_fertig des Plugins office.

Aufruf (für den Server, Python ab 3.9, nur Standardbibliothek):
  office.py pdf --bereich=B --thema=T [--seiten=3,5] [--dry-run] -- <Datei im Thema>
      PDF einer Office-Datei aus der Ablage in den Zwischenordner (<Datenordner>/zwischen/vorschau), mit seiten die
      Seiten auch als PNG daneben (pdftoppm). Ein PDF aus der Ablage wird nur kopiert und in Bilder zerlegt.
  office.py nachrechnen --bereich=B --thema=T -- <Mappe im Thema>
      Rechnet eine Kopie der Mappe mit LibreOffice nach und nennt Fehler je Zelle (#DIV/0!, #REF!, #NAME? und
      andere). Die Arbeitskopie bleibt unverändert, Excel rechnet beim Öffnen selbst.
Nie in die Ablage: PDF und Bilder gehen nur in den Zwischenordner.

Warum so: LibreOffice scheitert in der Sandbox von Claude Code still, und ohne festes Profil stört eine offene
LibreOffice-Instanz oder ein beschädigtes Standardprofil. Das Skript läuft darum ohne diese Sandbox, die Ablage und der
Zwischenordner sind aber aus der Sandbox der Motor-Skripte beschreibbar. Deshalb:
- Eingaben nur aus der Ablage, jeder Pfadteil ohne Folgen von Verweisen geöffnet (O_NOFOLLOW über den
  Ordner-Deskriptor). Ein Verweis oder ein Tausch eines Ordners gegen einen Verweis auf gesperrte Orte greift so nicht.
- Umgewandelt wird eine Kopie in staging/ im Datenordner, wohin die Motor-Sandbox nicht schreibt. PDF und Bilder kommen
  über eine Temp-Datei und rename im Ordner-Deskriptor in den Zwischenordner, nie über einen Pfad, der zwischendurch
  umgebogen sein könnte.
- LibreOffice und pdftoppm laufen unter sandbox-exec ohne Verbindungen ins Netz und dürfen die gesperrten Orte
  (sperren.py, dazu motor.gesperrt der config.json) weder lesen noch schreiben. So holt auch ein verknüpftes Bild in
  einem präparierten Dokument nichts von dort.
- Feste Profile im Datenordner: libreoffice-profil für PDF, libreoffice-rechnen mit Neuberechnung beim Laden.

Schriftschnitte: Themes nennen oft einen Schnitt statt der Familie, etwa Open Sans Bold. PowerPoint löst das auf,
LibreOffice nimmt eine Ersatzschrift. In der Kopie, nie in der Datei selbst, wird darum bei PowerPoint-Dateien ein
Schnitt mit installierter Familie (fc-list) zur Familie plus fett oder kursiv. Eigene Familien wie Open Sans Semibold
bleiben. motor.umgebung der config.json ergänzt die Umgebung (FONTCONFIG_FILE: sonst findet LibreOffice ohne
Bildschirm die Schriften in ~/Library/Fonts nicht).

Exit-Codes: 0 fertig, 1 Umwandlung gescheitert oder Fehler in Zellen, 2 Aufruf falsch (Datei fehlt, falscher Ordner,
Format, Verweis).
"""
import argparse
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import ablage
import kit_basis
import sperren

KIT_DIR = Path(__file__).resolve().parent
DATEN_DIR = kit_basis.datenordner(KIT_DIR)
HEIM = Path(pwd.getpwuid(os.getuid()).pw_dir)
APP_DATEN = HEIM / "Library" / "Application Support" / "Claude Kits"
FOLGE = "Nichts geändert."
ZWISCHEN, VORSCHAU, STAGING = "zwischen", "vorschau", "staging"
PROFIL, RECHNEN = "libreoffice-profil", "libreoffice-rechnen"
FORMATE = {".pptx", ".ppt", ".potx", ".pps", ".ppsx", ".docx", ".doc", ".dotx", ".rtf", ".odt", ".odp", ".ods",
           ".xlsx", ".xlsm", ".xls", ".csv"}
MAPPEN = {".xlsx", ".xlsm"}
ZEITLIMIT = 180  # Sekunden je Lauf von LibreOffice
SEITEN_MAX = 6
SOFFICE_MAC = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
UMGEBUNG_ERLAUBT = ("FONTCONFIG_FILE", "FONTCONFIG_PATH", "LANG", "LC_ALL")
PRAESENTATION = {".pptx", ".potx", ".ppsx"}  # dort korrigiert schrift_korrigieren Schnittnamen
SCHNITTE = (("Bold Italic", "bi"), ("Regular", ""), ("Italic", "i"), ("Bold", "b"))  # längster zuerst
TEILE = re.compile(r"ppt/(?:slides/slide|slideLayouts/slideLayout|slideMasters/slideMaster)\d+\.xml")
RPR = re.compile(r"<a:(?:rPr|defRPr|endParaRPr)\b[^>]*?(/?)>")
RPR_ENDE = re.compile(r"</a:(?:rPr|defRPr|endParaRPr)>")
NEU_RECHNEN = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" \
xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
{eintraege}</oor:items>
"""
RECHNEN_EINTRAEGE = "".join(
    f'<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="{n}" oor:op="fuse"><value>0</value>'
    f'</prop></item>\n' for n in ("OOXMLRecalcMode", "ODFRecalcMode"))
X = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
XR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"


class Ablehnung(Exception):
    """Aufruf falsch: Datei nicht in der Ablage, Verweis, Format. Exit 2."""


# ---------- Orte ----------
def lade_config() -> dict:
    return kit_basis.lade_config(DATEN_DIR / "config.json", folge=FOLGE)


def ordner_oeffnen(name, dir_fd=None, anlegen: bool = False) -> int:
    """Deskriptor eines Ordners, der selbst kein Verweis ist. anlegen legt ihn vorher an."""
    if anlegen:
        try:
            os.mkdir(name, 0o755, dir_fd=dir_fd)
        except FileExistsError:
            pass
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)


def eingabe(cfg: dict, bereich: str, thema: str, datei: str, formate: set) -> int:
    """Deskriptor einer Datei im Themen-Ordner der Ablage, jeder Teil ohne Folgen von Verweisen geöffnet."""
    orte = ablage.ablage(cfg)
    if bereich not in orte:
        raise Ablehnung(f"bereich {bereich!r}: in der config.json ist dafür keine Ablage eingetragen.")
    thema, datei = thema.strip(), datei.strip()
    if not ablage.THEMA_RE.fullmatch(thema) or thema.startswith("."):
        raise Ablehnung(f"thema {thema!r} ist kein Ordnername.")
    if not ablage.NAME_RE.fullmatch(datei) or datei.startswith((".", "~$")):
        raise Ablehnung(f"datei {datei!r} ist kein Dateiname.")
    if Path(datei).suffix.lower() not in formate:
        raise Ablehnung(f"{datei}: Format {Path(datei).suffix or 'ohne Endung'} geht hier nicht "
                        f"(möglich: {', '.join(sorted(formate))}).")
    try:
        wurzel = ordner_oeffnen(str(orte[bereich]))
    except FileNotFoundError:
        raise Ablehnung(f"Noch keine Ablage in {orte[bereich]}.") from None
    except OSError:
        raise Ablehnung(f"{orte[bereich]} ist ein Verweis oder kein Ordner.") from None
    try:
        namen = [n for n in os.listdir(wurzel) if n.casefold() == thema.casefold()]
        if not namen:
            raise Ablehnung(f"Thema {thema} gibt es in {orte[bereich]} nicht.")
        try:
            thema_fd = ordner_oeffnen(namen[0], wurzel)
        except OSError:
            raise Ablehnung(f"Thema {namen[0]} ist ein Verweis oder kein Ordner.") from None
    finally:
        os.close(wurzel)
    try:
        fd = os.open(datei, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=thema_fd)
    except FileNotFoundError:
        raise Ablehnung(f"{datei} gibt es im Thema {thema} nicht.") from None
    except OSError:
        raise Ablehnung(f"{datei} ist ein Verweis. Nur echte Dateien in der Ablage.") from None
    finally:
        os.close(thema_fd)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise Ablehnung(f"{datei} ist keine Datei.")
    return fd


def vorschau_oeffnen() -> int:
    """Deskriptor von zwischen/vorschau im Datenordner, beide Teile ohne Verweise."""
    daten = os.open(str(DATEN_DIR), os.O_RDONLY | os.O_DIRECTORY)
    try:
        z = ordner_oeffnen(ZWISCHEN, daten, anlegen=True)
    except OSError:
        os.close(daten)
        raise Ablehnung(f"{ZWISCHEN} im Datenordner ist ein Verweis oder kein Ordner.") from None
    os.close(daten)
    try:
        return ordner_oeffnen(VORSCHAU, z, anlegen=True)
    except OSError:
        raise Ablehnung(f"{ZWISCHEN}/{VORSCHAU} im Datenordner ist ein Verweis oder kein Ordner.") from None
    finally:
        os.close(z)


def kopie(fd: int, ziel: Path) -> None:
    """Inhalt aus dem geöffneten Deskriptor, nie über den Pfad."""
    os.lseek(fd, 0, os.SEEK_SET)
    with open(ziel, "wb") as aus:
        for block in iter(lambda: os.read(fd, 1 << 20), b""):
            aus.write(block)


def zurueckschreiben(daten: bytes, name: str, ordner_fd: int) -> None:
    """Datei in einen Ordner: Temp-Datei exklusiv anlegen, dann rename, beides relativ zum Ordner-Deskriptor. Ein Verweis
    mit dem Zielnamen wird dabei ersetzt, nie verfolgt."""
    tmp = f".{name}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=ordner_fd)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(daten)
        os.rename(tmp, name, src_dir_fd=ordner_fd, dst_dir_fd=ordner_fd)
    except BaseException:
        try:
            os.unlink(tmp, dir_fd=ordner_fd)
        except OSError:
            pass
        raise


# ---------- Programme ----------
def soffice() -> str:
    return shutil.which("soffice") or (SOFFICE_MAC if os.path.exists(SOFFICE_MAC) else "")


def sandbox_profil(cfg: dict) -> str:
    """Alles erlaubt außer Verbindungen ins Netz und Lesen oder Schreiben an den gesperrten Orten: LibreOffice braucht
    Schriften, Bibliotheken und Temp-Ordner, aber nie Mail, Nachrichten oder Schlüsselbund."""
    regeln = ["(version 1)", "(allow default)", "(deny network-outbound (remote ip))"]
    regeln += sperren.sperr_regeln(sperren.orte(cfg, HEIM, APP_DATEN))
    return "\n".join(regeln) + "\n"


def umgebung(cfg: dict) -> dict:
    """Umgebung plus fehlende Werte aus motor.umgebung, nur Schriften und Sprache."""
    env = dict(os.environ)
    motor = cfg.get("motor") if isinstance(cfg.get("motor"), dict) else {}
    for name, wert in (motor.get("umgebung") or {}).items():
        if name in UMGEBUNG_ERLAUBT and isinstance(wert, str) and wert and not env.get(name):
            env[name] = wert
    teile = [p for p in env.get("PATH", "").split(":") if p]
    env["PATH"] = ":".join(teile + [p for p in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin")
                                    if p not in teile])
    return env


def starte(befehl, profil: Path, env: dict, zeitlimit: int):
    """Programm mit festem Profil starten. Zwei Läufe mit demselben Profil laufen nacheinander, nie gleichzeitig."""
    import fcntl
    with open(profil.parent / (profil.name + ".lock"), "w") as sperre:
        fcntl.flock(sperre, fcntl.LOCK_EX)
        return subprocess.run(befehl, capture_output=True, text=True, timeout=zeitlimit, env=env,
                              stdin=subprocess.DEVNULL)


def libreoffice(profil_text: str, profil: Path, dateien: list, ausgabe: Path, ziel: str, env: dict,
                zeitlimit: int) -> str:
    """LibreOffice unter sandbox-exec, liefert die Meldung für den Fehlerfall."""
    befehl = [SANDBOX_EXEC, "-p", profil_text, soffice(), f"-env:UserInstallation={profil.as_uri()}", "--headless",
              "--norestore", "--convert-to", ziel, "--outdir", str(ausgabe), *[str(d) for d in dateien]]
    r = starte(befehl, profil, env, zeitlimit)
    meldung = " ".join(z for z in (r.stderr or r.stdout or "").splitlines() if not z.startswith("Fontconfig"))
    return " ".join(meldung.split())[:300]


# ---------- Schriftschnitte ----------
def familien(env: dict) -> set:
    """Installierte Schriftfamilien laut fontconfig (alle Namen je Schrift), leer ohne fc-list."""
    programm = shutil.which("fc-list", path=env.get("PATH")) or ""
    if not programm:
        return set()
    try:
        r = subprocess.run([programm, ":", "family"], capture_output=True, text=True, env=env, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return set()
    return {f.strip() for zeile in r.stdout.splitlines() for f in zeile.split(",") if f.strip()}


def schnitt(name: str, fam: set):
    """(Familie, Auszeichnung b/i/bi/"") für einen Schnittnamen wie Open Sans Bold, sonst None."""
    if name in fam:
        return None
    for s, kurz in SCHNITTE:
        if name.endswith(" " + s) and name[:-len(s) - 1] in fam:
            return name[:-len(s) - 1], kurz
    return None


def auszeichnen(tag: str, kurz: str) -> str:
    """b="1" und i="1" in einen Start-Tag, ausdrücklich gesetzte Werte bleiben."""
    for buchstabe in kurz:
        if not re.search(rf'\s{buchstabe}="', tag):
            tag = re.sub(r"^(<a:\w+)", rf'\1 {buchstabe}="1"', tag)
    return tag


def latin_korrigieren(xml: str, fam: set, thema: dict) -> str:
    """a:latin in Lauf-Eigenschaften: Schnitt zur Familie, Auszeichnung an den Eltern-Tag. Verweise +mj-lt und +mn-lt
    bleiben, bekommen aber die Auszeichnung des Theme-Schnitts."""
    aenderungen = []
    for m in re.finditer(r'<a:latin typeface="([^"]+)"', xml):
        name = m.group(1)
        s = (name, thema[name]) if name in thema else schnitt(name, fam)
        if not s or not s[1] and s[0] == name:
            continue
        eltern = None
        for e in RPR.finditer(xml, 0, m.start()):
            eltern = e
        ende = None
        for e in RPR_ENDE.finditer(xml, 0, m.start()):
            ende = e
        if eltern is None or eltern.group(1) or (ende is not None and ende.start() > eltern.start()):
            continue
        aenderungen.append((m.start(1), m.end(1), s[0]))
        if s[1]:
            aenderungen.append((eltern.start(), eltern.end(), auszeichnen(eltern.group(0), s[1])))
    for a, b, neu in sorted(set(aenderungen), reverse=True):
        xml = xml[:a] + neu + xml[b:]
    return xml


def stil_auszeichnen(xml: str, stil: str, kurz: str) -> str:
    """Alle a:defRPr in p:titleStyle oder p:bodyStyle eines Masters auszeichnen."""
    m = re.search(rf"<p:{stil}>.*?</p:{stil}>", xml, re.S)
    if not m or not kurz:
        return xml
    block = re.sub(r"<a:defRPr\b[^>]*?/?>", lambda t: auszeichnen(t.group(0), kurz), m.group(0))
    return xml[:m.start()] + block + xml[m.end():]


def schrift_korrigieren(pfad: Path, fam: set) -> list:
    """Schnittnamen in der Kopie einer Präsentation zu Familie plus Auszeichnung. Liefert die Umsetzungen als Text."""
    try:
        with zipfile.ZipFile(pfad) as z:
            infos = z.infolist()
            teile = {i.filename: z.read(i.filename) for i in infos}
    except (zipfile.BadZipFile, OSError):
        return []
    thema, gemeldet, neu = {}, {}, {}
    for name, daten in teile.items():
        if re.fullmatch(r"ppt/theme/theme\d+\.xml", name):
            xml = daten.decode("utf-8")
            for rolle, verweis in (("majorFont", "+mj-lt"), ("minorFont", "+mn-lt")):
                m = re.search(rf'<a:{rolle}>\s*<a:latin typeface="([^"]+)"', xml)
                s = schnitt(m.group(1), fam) if m else None
                if s:
                    xml = xml[:m.start(1)] + s[0] + xml[m.end(1):]
                    thema[verweis] = s[1]
                    gemeldet[m.group(1)] = s
            neu[name] = xml
    for name, daten in teile.items():
        if TEILE.fullmatch(name):
            alt = daten.decode("utf-8")
            xml = latin_korrigieren(alt, fam, thema)
            if "slideMaster" in name:
                xml = stil_auszeichnen(xml, "titleStyle", thema.get("+mj-lt", ""))
                xml = stil_auszeichnen(xml, "bodyStyle", thema.get("+mn-lt", ""))
            for m in re.finditer(r'<a:latin typeface="([^"]+)"', alt):
                if schnitt(m.group(1), fam):
                    gemeldet[m.group(1)] = schnitt(m.group(1), fam)
            if xml != alt:
                neu[name] = xml
    if not gemeldet:
        return []
    tmp = pfad.with_name(pfad.name + ".schrift")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for i in infos:
            z.writestr(i, neu[i.filename].encode("utf-8") if i.filename in neu else teile[i.filename])
    os.replace(tmp, pfad)
    art = {"": "", "b": " fett", "i": " kursiv", "bi": " fett kursiv"}
    return [f"{alt} als {fam_}{art[k]}" for alt, (fam_, k) in sorted(gemeldet.items())]


# ---------- Befehle ----------
def seitenliste(wert: str) -> list:
    seiten = []
    for teil in [t.strip() for t in (wert or "").split(",") if t.strip()]:
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", teil)
        if not m:
            raise Ablehnung("seiten wie 3 oder 2,5 oder 4-6.")
        von, bis = int(m.group(1)), int(m.group(2) or m.group(1))
        seiten += list(range(von, min(bis, von + SEITEN_MAX) + 1))
    seiten = list(dict.fromkeys(s for s in seiten if s > 0))
    if len(seiten) > SEITEN_MAX:
        raise Ablehnung(f"Höchstens {SEITEN_MAX} Seiten je Vorschau.")
    return seiten


def staging() -> Path:
    ordner = DATEN_DIR / STAGING
    if ordner.is_symlink():
        raise Ablehnung(f"{STAGING} im Datenordner ist ein Verweis.")
    ordner.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(dir=str(ordner)))


def cmd_pdf(cfg: dict, bereich: str, thema: str, datei: str, seiten: list, dry_run: bool,
            zeitlimit: int = ZEITLIMIT) -> int:
    fd = eingabe(cfg, bereich, thema, datei, FORMATE | {".pdf"})
    stamm = Path(datei).stem
    ziel_ordner = DATEN_DIR / ZWISCHEN / VORSCHAU
    try:
        ist_pdf = Path(datei).suffix.lower() == ".pdf"
        if not ist_pdf and not soffice():
            print("LibreOffice fehlt. Installieren: brew install --cask libreoffice", file=sys.stderr)
            return 1
        if dry_run:
            print(f"Probelauf, nichts umgewandelt: {datei} -> {ziel_ordner / (stamm + '.pdf')}")
            return 0
        profil_text = sandbox_profil(cfg)
        ziel_fd = vorschau_oeffnen()
        try:
            lauf = staging()
        except BaseException:
            os.close(ziel_fd)
            raise
        try:
            env = umgebung(cfg)
            kopiert = lauf / datei
            kopie(fd, kopiert)
            if ist_pdf:
                pdf = kopiert
            else:
                if kopiert.suffix.lower() in PRAESENTATION:
                    fam = familien(env)
                    umgesetzt = schrift_korrigieren(kopiert, fam) if fam else []
                    if umgesetzt:
                        print("Schrift nur im PDF: " + ", ".join(umgesetzt))
                profil = DATEN_DIR / PROFIL
                profil.mkdir(exist_ok=True)
                (lauf / "pdf").mkdir()
                try:
                    meldung = libreoffice(profil_text, profil, [kopiert], lauf / "pdf", "pdf", env, zeitlimit)
                except subprocess.TimeoutExpired:
                    print(f"LibreOffice hängt seit {zeitlimit} Sekunden. Läuft LibreOffice mit einem Dialog? Fenster "
                          "schließen, dann erneut versuchen.", file=sys.stderr)
                    return 1
                pdf = lauf / "pdf" / (stamm + ".pdf")
                if not pdf.is_file() or pdf.is_symlink() or pdf.stat().st_size == 0:
                    if "sandbox_apply" in meldung:
                        print("Sandbox nicht verfügbar (sandbox-exec), aus Sicherheitsgründen nichts umgewandelt.",
                              file=sys.stderr)
                    else:
                        print(f"Kein PDF für {datei}" + (f" (LibreOffice: {meldung})" if meldung else "")
                              + ". Datei in Office öffnen und prüfen, ob sie beschädigt ist.", file=sys.stderr)
                    return 1
            zurueckschreiben(pdf.read_bytes(), stamm + ".pdf", ziel_fd)
            print(f"PDF: {ziel_ordner / (stamm + '.pdf')}")
            return bilder(profil_text, pdf, stamm, seiten, lauf, ziel_fd, ziel_ordner, env)
        finally:
            shutil.rmtree(lauf, ignore_errors=True)
            os.close(ziel_fd)
    finally:
        os.close(fd)


def bilder(profil_text: str, pdf: Path, stamm: str, seiten: list, lauf: Path, ziel_fd: int, ziel_ordner: Path,
           env: dict) -> int:
    """Seiten als PNG (pdftoppm unter sandbox-exec) in den Zwischenordner."""
    if not seiten:
        return 0
    programm = shutil.which("pdftoppm", path=env.get("PATH")) or ""
    if not programm:
        print("Keine Bilder: pdftoppm fehlt. Installieren: brew install poppler")
        return 0
    for s in seiten:
        bild = lauf / f"seite-{s}"
        try:
            r = subprocess.run([SANDBOX_EXEC, "-p", profil_text, programm, "-png", "-scale-to", "900", "-f", str(s),
                                "-l", str(s), "-singlefile", str(pdf), str(bild)], capture_output=True, text=True,
                               timeout=60, env=env, stdin=subprocess.DEVNULL)
            meldung = " ".join((r.stderr or "").split())[:200]
        except subprocess.TimeoutExpired:
            meldung = "keine Antwort nach 60 Sekunden"
        png = Path(str(bild) + ".png")
        if png.is_file() and not png.is_symlink() and png.stat().st_size > 0:
            name = f"{stamm}-{s}.png"
            zurueckschreiben(png.read_bytes(), name, ziel_fd)
            print(f"Seite {s}: {ziel_ordner / name}")
        else:
            print(f"Seite {s}: kein Bild ({meldung or 'Seite gibt es nicht'})")
    return 0


def rechnen_profil() -> Path:
    """Profil mit Neuberechnung beim Laden (OOXMLRecalcMode und ODFRecalcMode 0 heißt immer)."""
    profil = DATEN_DIR / RECHNEN
    datei = profil / "user" / "registrymodifications.xcu"
    if profil.is_symlink() or datei.is_symlink():
        raise Ablehnung(f"{RECHNEN} im Datenordner ist ein Verweis.")
    datei.parent.mkdir(parents=True, exist_ok=True)
    text = datei.read_text(encoding="utf-8") if datei.is_file() else ""
    if "OOXMLRecalcMode" not in text:
        if "</oor:items>" in text:
            text = text.replace("</oor:items>", RECHNEN_EINTRAEGE + "</oor:items>")
        else:
            text = NEU_RECHNEN.format(eintraege=RECHNEN_EINTRAEGE)
        datei.write_text(text, encoding="utf-8")
    return profil


def blaetter(z: zipfile.ZipFile) -> list:
    """[(Blattname, Teil im Paket)] in der Reihenfolge der Mappe."""
    rels = {}
    if "xl/_rels/workbook.xml.rels" in z.namelist():
        for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).iter(PR + "Relationship"):
            ziel = r.get("Target") or ""
            rels[r.get("Id")] = ziel.lstrip("/") if ziel.startswith("/") else "xl/" + ziel
    return [(s.get("name"), rels.get(s.get(XR + "id"), "")) for s in
            ET.fromstring(z.read("xl/workbook.xml")).iter(X + "sheet")]


def fehler_zellen(pfad: Path) -> tuple:
    """(Formeln, Blätter, [(Blatt, Zelle, Fehler)]) einer nachgerechneten Mappe."""
    formeln, funde, liste = 0, [], []
    with zipfile.ZipFile(pfad) as z:
        liste = blaetter(z)
        for name, teil in liste:
            if teil not in z.namelist():
                continue
            for c in ET.fromstring(z.read(teil)).iter(X + "c"):
                if c.find(X + "f") is not None:
                    formeln += 1
                if c.get("t") == "e":
                    funde.append((name, c.get("r") or "?", c.findtext(X + "v") or "#?"))
    return formeln, len(liste), funde


def cmd_nachrechnen(cfg: dict, bereich: str, thema: str, datei: str, zeitlimit: int = ZEITLIMIT) -> int:
    fd = eingabe(cfg, bereich, thema, datei, MAPPEN)
    try:
        if not soffice():
            print("LibreOffice fehlt. Installieren: brew install --cask libreoffice", file=sys.stderr)
            return 1
        profil_text = sandbox_profil(cfg)
        profil = rechnen_profil()
        lauf = staging()
        try:
            (lauf / "ein").mkdir()
            (lauf / "aus").mkdir()
            kopiert = lauf / "ein" / datei
            kopie(fd, kopiert)
            try:
                meldung = libreoffice(profil_text, profil, [kopiert], lauf / "aus", "xlsx", umgebung(cfg), zeitlimit)
            except subprocess.TimeoutExpired:
                print(f"LibreOffice hängt seit {zeitlimit} Sekunden. Läuft LibreOffice mit einem Dialog? Fenster "
                      "schließen, dann erneut versuchen.", file=sys.stderr)
                return 1
            ergebnis = lauf / "aus" / (Path(datei).stem + ".xlsx")
            if not ergebnis.is_file() or ergebnis.is_symlink():
                print(f"Nicht nachgerechnet: {datei}" + (f" (LibreOffice: {meldung})" if meldung else "") + ".",
                      file=sys.stderr)
                return 1
            try:
                formeln, zahl, funde = fehler_zellen(ergebnis)
            except (zipfile.BadZipFile, ET.ParseError, KeyError) as e:
                print(f"Ergebnis von LibreOffice nicht lesbar ({type(e).__name__}).", file=sys.stderr)
                return 1
        finally:
            shutil.rmtree(lauf, ignore_errors=True)
    finally:
        os.close(fd)
    print(f"Nachgerechnet mit LibreOffice: {formeln} Formeln in {zahl} Blättern, {len(funde)} Fehler. Die Arbeitskopie "
          "bleibt unverändert.")
    for blatt, zelle, wert in funde[:40]:
        print(f"  {blatt}!{zelle}: {wert}")
    if len(funde) > 40:
        print(f"  und {len(funde) - 40} weitere")
    return 1 if funde else 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    nach = argv[argv.index("--") + 1:] if "--" in argv else []
    vor = argv[:argv.index("--")] if "--" in argv else argv
    p = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    p.add_argument("befehl", choices=("pdf", "nachrechnen"))
    p.add_argument("--bereich", default="")
    p.add_argument("--thema", default="")
    p.add_argument("--seiten", default="")
    p.add_argument("--dry-run", action="store_true")
    try:
        a = p.parse_args(vor)
    except SystemExit:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    if len(nach) != 1 or not a.bereich or not a.thema:
        print(f"bereich, thema und hinter -- genau eine Datei angeben. {FOLGE}", file=sys.stderr)
        return 2
    try:
        cfg = lade_config()
        if a.befehl == "pdf":
            return cmd_pdf(cfg, a.bereich, a.thema, nach[0], seitenliste(a.seiten), a.dry_run)
        if a.seiten or a.dry_run:
            raise Ablehnung("seiten und dry-run gelten nur für pdf.")
        return cmd_nachrechnen(cfg, a.bereich, a.thema, nach[0])
    except Ablehnung as e:
        print(f"Nicht ausgeführt: {e}", file=sys.stderr)
        return 2
    except sperren.Falsch as e:
        print(f"{e} {FOLGE}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    kit_basis.starten(lambda: sys.exit(main()), __file__)
