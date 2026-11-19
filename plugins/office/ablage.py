#!/usr/bin/env python3
"""Arbeitskopien von Dokumenten im Ablage-Ordner, für die Werkzeuge arbeitskopie und arbeitskopie_uebertragen des
Plugins office (bis 7.3 im Plugin apple). sprache.py findet seine Datei über ablage_datei.

Aufruf (für den Server):
  ablage.py liste [--bereich=privat|arbeit]
  ablage.py holen --bereich=B --thema=T [--neu] -- <Original>
  ablage.py zeigen [--finder] [--bereich=B --thema=T] -- <Datei im Thema oder Pfad>
  ablage.py herkunft --bereich=B --thema=T -- <Datei>
  ablage.py [--ausfuehren] uebertragen --bereich=B --thema=T -- <Datei>

Ablauf: Das Original bleibt, wo es ist. holen kopiert es nach <ablage.<bereich>>/<Thema>/<Dateiname wie das Original>,
ein Ordner je Thema ohne Datum, ein vorhandener Themen-Ordner gleichen Namens wird wiederverwendet. Alle Iterationen
laufen in dieser Arbeitskopie. uebertragen schreibt ihren Inhalt in die Originaldatei am selben Ort, ohne Löschen und
Neuanlegen (gleiche Datei, gleicher Name): So bleiben Links und Versionsverlauf in SharePoint oder OneDrive.

Herkunft (Pfad des Originals, Stand beim Holen mit Änderungszeit, Größe und Prüfsumme) liegt in ablage.json im
Datenordner, nie neben der Arbeitskopie. Der alte Stand des Originals vor dem letzten Übertragen liegt in
ablage-sicherung/ im Datenordner (je Original nur der letzte).

Pfade aus Cowork: Die VM bindet Ordner des Mac als /sessions/<id>/mnt/<Ordnername>/... ein. Ein solcher Pfad wird am
Mac über den Ordnernamen gesucht (Heimordner, iCloud Drive, ~/Library/CloudStorage), nur ein eindeutiger Treffer zählt.

Schutz: Originale nur unter dem Heimordner, aus ~/Library nur iCloud Drive und CloudStorage, keine versteckten Ordner,
keine Verweise, nur Dokumente (ENDUNGEN). zeigen nur unter den Ablage-Ordnern, öffnen nur Dokumente ohne Skripte und
Makros (OEFFNEN_ENDUNGEN) und Ordner, alles andere nur im Finder zeigen. uebertragen schreibt nur mit --ausfuehren
direkt hinter dem Skript, das der Server erst nach dem Dialog am Mac übergibt, und nur, wenn sich das Original seit dem
Holen nicht geändert hat und Office es nicht offen hat. Löschen gibt es nicht. Exit-Codes: 0 ok, 1 Fehler, 2 Aufruf
falsch.
"""
import argparse
import datetime
import hashlib
import json
import os
import pwd
import re
import stat
import subprocess
import sys
from pathlib import Path

import kit_basis  # Datenordner, config.json, Fehlerprotokoll, gleich in apple, chat und office

KIT_DIR = Path(__file__).resolve().parent
DATEN_DIR = kit_basis.datenordner(KIT_DIR)
CONFIG_PATH = DATEN_DIR / "config.json"
HERKUNFT_DATEI = "ablage.json"
SICHERUNG_ORDNER = "ablage-sicherung"
HEIM = Path(pwd.getpwuid(os.getuid()).pw_dir)  # aus der Benutzerdatenbank, nicht aus HOME
BEREICHE = ("privat", "arbeit")
ENDUNGEN = {".pptx", ".ppt", ".potx", ".docx", ".doc", ".dotx", ".xlsx", ".xlsm", ".xls", ".xltx", ".csv", ".pdf",
            ".key", ".pages", ".numbers", ".odt", ".ods", ".odp", ".rtf", ".txt", ".md", ".html", ".htm", ".vsdx",
            ".json", ".xml", ".png", ".jpg", ".jpeg", ".svg"}
# zeigen öffnet nur diese, alles andere (HTML mit Skripten, Makros) nur im Finder
OEFFNEN_ENDUNGEN = ENDUNGEN - {".html", ".htm", ".svg", ".xml", ".json", ".xlsm"}
GROESSE_MAX = 300_000_000  # Bytes je Datei
NAME_RE = re.compile(r"[^/\\:\x00-\x1f]{1,120}")
THEMA_RE = re.compile(r"[^/\\:\x00-\x1f]{1,80}")
VM_RE = re.compile(r"/sessions/[^/]+/mnt/([^/]+)/(.+)")
NUR_COWORK = ("outputs", "uploads", ".claude", ".skills")  # Ordner der VM ohne Gegenstück am Mac
SUCHE_MAX = 40_000  # Ordner, die die Suche nach einem Pfad aus Cowork höchstens ansieht
FOLGE = "Nichts geändert."


def aufruf_falsch(text: str):
    print(text, file=sys.stderr)
    sys.exit(2)


def jetzt() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def zeit_text(sekunden: float) -> str:
    t = datetime.datetime.fromtimestamp(sekunden)
    return t.strftime("%d.%m. %H:%M") if t.year == datetime.date.today().year else t.strftime("%d.%m.%Y %H:%M")


def unter(pfad: Path, wurzel: Path) -> bool:
    return pfad == wurzel or wurzel in pfad.parents


# ---------- Einstellungen ----------
def config() -> dict:
    return kit_basis.lade_config(CONFIG_PATH, folge=FOLGE)


def ablage(cfg: dict) -> dict:
    """{bereich: Ordner} aus dem Abschnitt ablage, nicht aufgelöst (der Ordner darf noch fehlen)."""
    block = kit_basis.abschnitt(cfg, "ablage", f"Mit einstellungen_schreiben den Abschnitt ablage mit privat und arbeit "
                                              f"anlegen. {FOLGE}")
    aus = {}
    for bereich in BEREICHE:
        wert = block.get(bereich)
        if wert in (None, ""):
            continue
        if not isinstance(wert, str) or not os.path.isabs(os.path.expanduser(wert)):
            raise kit_basis.abbruch(f"config.json: ablage.{bereich} muss ein Ordner sein, absolut oder mit ~.", FOLGE)
        aus[bereich] = Path(os.path.expanduser(wert))
    return aus


def bereich_ordner(cfg: dict, bereich: str, anlegen: bool = False) -> Path:
    if bereich not in BEREICHE:
        aufruf_falsch(f"bereich ist privat oder arbeit, nicht {bereich!r}. {FOLGE}")
    orte = ablage(cfg)
    if bereich not in orte:
        raise kit_basis.abbruch(f"config.json: ablage.{bereich} ist leer.", FOLGE)
    ort = orte[bereich]
    if ort.is_symlink() or (ort.exists() and not ort.is_dir()):
        raise kit_basis.abbruch(f"{ort} ist ein Verweis oder kein Ordner.", FOLGE)
    if not ort.exists():
        if not anlegen:
            raise kit_basis.abbruch(f"Noch keine Arbeitskopien in {ort}.", FOLGE)
        if not ort.parent.is_dir():
            raise kit_basis.abbruch(f"Der Ordner {ort.parent} fehlt, ablage.{bereich} in der config.json prüfen.", FOLGE)
        ort.mkdir()
    return ort.resolve()


def thema_ordner(basis: Path, thema: str, anlegen: bool = False) -> Path:
    """Themen-Ordner direkt unter basis. Gleicher Name ohne Rücksicht auf Groß- und Kleinschreibung wird wiederverwendet."""
    thema = thema.strip()
    if not THEMA_RE.fullmatch(thema) or thema.startswith(".") or thema in (".", ".."):
        aufruf_falsch(f"thema ist ein Ordnername ohne / und ohne Punkt vorn, nicht {thema!r}. {FOLGE}")
    for ordner in sorted(basis.iterdir()):
        if ordner.name.casefold() == thema.casefold() and ordner.is_dir() and not ordner.is_symlink():
            return ordner
    if not anlegen:
        themen = [o.name for o in sorted(basis.iterdir()) if o.is_dir() and not o.name.startswith(".")]
        raise kit_basis.abbruch(f"Thema {thema} gibt es in {basis} nicht. Vorhanden: {', '.join(themen) or 'keine'}.",
                                FOLGE)
    ordner = basis / thema
    ordner.mkdir()
    return ordner


def dateiname(name: str) -> str:
    name = name.strip()
    if not NAME_RE.fullmatch(name) or name.startswith(".") or name.startswith("~$"):
        aufruf_falsch(f"datei ist nur ein Dateiname ohne Ordner, nicht {name!r}. {FOLGE}")
    return name


# ---------- Pfade aus Cowork ----------
def suchwurzeln() -> list:
    """(Ordner, Tiefe): wo ein in Cowork eingebundener Ordner am Mac liegen kann."""
    return [(HEIM, 4), (HEIM / "Library" / "CloudStorage", 4),
            (HEIM / "Library" / "Mobile Documents" / "com~apple~CloudDocs", 4)]


def vm_aufloesen(ordnername: str, rest: str) -> Path:
    """Pfad am Mac zu /sessions/<id>/mnt/<ordnername>/<rest>: alle Ordner dieses Namens in den Suchwurzeln, in denen
    rest liegt. Nur ein Treffer zählt."""
    treffer, gesehen = set(), 0
    for wurzel, tiefe in suchwurzeln():
        stapel = [(wurzel, 0)]
        while stapel and gesehen < SUCHE_MAX:
            ordner, ebene = stapel.pop()
            gesehen += 1
            if ordner.name == ordnername and (ordner / rest).exists():
                treffer.add(ordner / rest)
            if ebene >= tiefe:
                continue
            try:
                eintraege = list(os.scandir(ordner))
            except OSError:
                continue
            for e in eintraege:
                if e.name.startswith(".") or e.name.endswith(".app") or not e.is_dir(follow_symlinks=False):
                    continue
                if ordner == HEIM and e.name == "Library":  # eigene Wurzeln für iCloud Drive und CloudStorage
                    continue
                stapel.append((Path(e.path), ebene + 1))
    if len(treffer) == 1:
        return treffer.pop()
    if not treffer:
        raise kit_basis.abbruch(f"Den Ordner {ordnername} aus Cowork mit {rest} finde ich am Mac nicht. Den Pfad am Mac "
                                f"angeben oder den Nutzer fragen.", FOLGE)
    beispiele = ", ".join(str(t) for t in sorted(treffer)[:4])
    raise kit_basis.abbruch(f"{ordnername}/{rest} gibt es am Mac mehrfach ({beispiele}). Den Pfad am Mac angeben.", FOLGE)


def mac_pfad(angabe: str) -> Path:
    """Absoluter Pfad am Mac, auch aus einem Pfad der VM von Cowork. Nicht aufgelöst: Verweise prüft der Aufrufer."""
    angabe = angabe.strip()
    treffer = VM_RE.fullmatch(angabe)
    if treffer:
        ordnername, rest = treffer.groups()
        if ordnername in NUR_COWORK:
            raise kit_basis.abbruch(f"{angabe} liegt nur in Cowork (Upload oder Ausgabe), am Mac gibt es kein Original "
                                    f"dazu.", FOLGE)
        return vm_aufloesen(ordnername, rest.rstrip("/"))
    pfad = Path(os.path.expanduser(angabe))
    if not pfad.is_absolute():
        raise kit_basis.abbruch(f"Pfad muss absolut sein: {angabe}.", FOLGE)
    return pfad


# ---------- Herkunft ----------
def herkunft_laden() -> dict:
    pfad = DATEN_DIR / HERKUNFT_DATEI
    if pfad.is_symlink():
        raise kit_basis.abbruch(f"{HERKUNFT_DATEI} im Datenordner ist ein Verweis.", FOLGE)
    if not pfad.is_file():
        return {}
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise kit_basis.abbruch(f"{HERKUNFT_DATEI} im Datenordner ist nicht lesbar.", FOLGE) from None
    kopien = daten.get("kopien") if isinstance(daten, dict) else None
    return kopien if isinstance(kopien, dict) else {}


def herkunft_speichern(kopien: dict) -> None:
    """Ganz oder gar nicht, Einträge ohne Arbeitskopie fallen weg."""
    kopien = {k: v for k, v in kopien.items() if Path(k).is_file()}
    pfad = DATEN_DIR / HERKUNFT_DATEI
    if pfad.is_symlink():
        raise kit_basis.abbruch(f"{HERKUNFT_DATEI} im Datenordner ist ein Verweis.", FOLGE)
    temp = pfad.with_name(f".{HERKUNFT_DATEI}.neu")
    temp.write_text(json.dumps({"kopien": kopien}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, pfad)


def pruefsumme(pfad: Path) -> str:
    summe = hashlib.sha256()
    with open(pfad, "rb") as f:
        for stueck in iter(lambda: f.read(1_000_000), b""):
            summe.update(stueck)
    return summe.hexdigest()


def stand(pfad: Path) -> dict:
    st = pfad.stat()
    return {"mtime": st.st_mtime, "groesse": st.st_size, "sha256": pruefsumme(pfad)}


def schnell_geaendert(pfad: Path, alt: dict) -> bool:
    """Ohne die Datei zu lesen (ein Original in der Cloud würde sonst geladen): Zeit oder Größe weichen ab."""
    try:
        st = pfad.stat()
    except OSError:
        return True
    return st.st_size != alt.get("groesse") or abs(st.st_mtime - float(alt.get("mtime") or 0)) > 0.001


# ---------- Prüfungen ----------
def quelle_pruefen(pfad: Path, cfg: dict) -> Path:
    if pfad.is_symlink():
        raise kit_basis.abbruch(f"{pfad} ist ein Verweis. Nur das Original selbst.", FOLGE)
    try:
        echt = pfad.resolve(strict=True)
    except (OSError, RuntimeError):
        raise kit_basis.abbruch(f"Original nicht gefunden: {pfad}.", FOLGE) from None
    if not echt.is_file():
        raise kit_basis.abbruch(f"{echt.name} ist keine Datei.", FOLGE)
    heim = HEIM.resolve()
    bibliothek = heim / "Library"
    cloud = (bibliothek / "CloudStorage", bibliothek / "Mobile Documents")
    if not unter(echt, heim) or (unter(echt, bibliothek) and not any(unter(echt, c) for c in cloud)):
        raise kit_basis.abbruch(f"Originale nur aus dem eigenen Heimordner, iCloud Drive oder CloudStorage, nicht aus "
                                f"{echt.parent}.", FOLGE)
    teile = echt.relative_to(heim).parts
    if any(t.startswith(".") for t in teile) or echt.name.startswith("~$"):
        raise kit_basis.abbruch(f"{echt.name} liegt in einem versteckten Ordner oder ist eine Sperrdatei.", FOLGE)
    if echt.suffix.lower() not in ENDUNGEN:
        raise kit_basis.abbruch(f"Nur Dokumente ({', '.join(sorted(ENDUNGEN))}), nicht {echt.name}.", FOLGE)
    for ort in ablage(cfg).values():
        if ort.exists() and unter(echt, ort.resolve()):
            raise kit_basis.abbruch(f"{echt.name} liegt schon in der Ablage, dort direkt weiterarbeiten.", FOLGE)
    if echt.stat().st_size > GROESSE_MAX:
        raise kit_basis.abbruch(f"{echt.name} ist größer als {GROESSE_MAX // 1_000_000} MB.", FOLGE)
    return echt


def office_offen(original: Path) -> bool:
    """Sperrdatei von Office neben dem Original: ~$ vor dem Namen, bei langen Namen ersetzt sie die ersten zwei Zeichen."""
    return any((original.parent / n).exists() for n in {f"~${original.name}", f"~${original.name[2:]}"})


def kopie_pruefen(cfg: dict, bereich: str, thema: str, datei: str) -> Path:
    ordner = thema_ordner(bereich_ordner(cfg, bereich), thema)
    kopie = ordner / dateiname(datei)
    if kopie.is_symlink() or not kopie.is_file():
        raise kit_basis.abbruch(f"{datei} gibt es in {ordner} nicht als Datei.", FOLGE)
    return kopie


def in_ablage(echt: Path, cfg: dict) -> bool:
    """Aufgelöster Pfad liegt unter einem vorhandenen Ablage-Ordner."""
    return any(unter(echt, o.resolve()) for o in ablage(cfg).values() if o.is_dir() and not o.is_symlink())


def ablage_datei(cfg: dict, bereich: str, thema: str, angabe: str) -> Path:
    """Datei in der Ablage für andere Skripte des Plugins (sprache.py): mit bereich und thema ein Dateiname im Thema,
    sonst ein Pfad am Mac oder aus Cowork. Nur eine normale Datei unter einem Ablage-Ordner, kein Verweis."""
    if bereich or thema:
        return kopie_pruefen(cfg, bereich, thema, angabe)
    if not angabe:
        aufruf_falsch(f"pfad oder bereich, thema und datei angeben. {FOLGE}")
    pfad = mac_pfad(angabe)
    if pfad.is_symlink():
        raise kit_basis.abbruch(f"{pfad.name} ist ein Verweis.", FOLGE)
    try:
        echt = pfad.resolve(strict=True)
    except (OSError, RuntimeError):
        raise kit_basis.abbruch(f"Nicht gefunden: {pfad}.", FOLGE) from None
    if not echt.is_file():
        raise kit_basis.abbruch(f"{echt.name} ist keine Datei.", FOLGE)
    if not in_ablage(echt, cfg):
        raise kit_basis.abbruch(f"Nur Arbeitskopien in der Ablage, nicht {echt.parent}. Erst mit arbeitskopie holen.",
                                FOLGE)
    return echt


def cowork_pfad(kopie: Path, cfg: dict) -> str:
    """Wie Claude in Cowork die Arbeitskopie findet: ab dem Ordner über der Ablage, meist Downloads/Claude Work/..."""
    for ort in ablage(cfg).values():
        if ort.exists() and unter(kopie, ort.resolve()):
            return str(kopie.relative_to(ort.resolve().parent.parent))
    return kopie.name


# ---------- Befehle ----------
def kopieren(quelle: Path, ziel: Path) -> str:
    """Kopiert quelle nach ziel und liefert die Prüfsumme dessen, was geschrieben wurde. ziel ist danach eine eigene,
    neue Datei (kein Verweis)."""
    summe = hashlib.sha256()
    fd = os.open(ziel, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    try:
        with open(quelle, "rb") as ein, os.fdopen(fd, "wb", closefd=False) as aus:
            for stueck in iter(lambda: ein.read(1_000_000), b""):
                summe.update(stueck)
                aus.write(stueck)
    finally:
        os.close(fd)
    return summe.hexdigest()


def cmd_holen(cfg: dict, bereich: str, thema: str, angabe: str, neu: bool) -> None:
    quelle = quelle_pruefen(mac_pfad(angabe), cfg)
    ordner = thema_ordner(bereich_ordner(cfg, bereich, anlegen=True), thema, anlegen=True)
    kopie = ordner / quelle.name
    kopien = herkunft_laden()
    eintrag = kopien.get(str(kopie))
    vorhanden = kopie.exists() or kopie.is_symlink()
    if vorhanden:
        if kopie.is_symlink() or not kopie.is_file():
            raise kit_basis.abbruch(f"{kopie.name} in {ordner.name} ist ein Verweis oder keine Datei.", FOLGE)
        if not eintrag or eintrag.get("original") != str(quelle):
            woher = eintrag.get("original") if eintrag else "ohne bekannte Herkunft"
            raise kit_basis.abbruch(f"{kopie.name} liegt in {ordner.name} schon ({woher}). Ein anderes Thema wählen.",
                                    FOLGE)
        if not neu:
            print(f"Arbeitskopie gibt es schon, darin weiterarbeiten: {kopie}")
            print(f"In Cowork: {cowork_pfad(kopie, cfg)}")
            print(f"Original: {quelle}")
            if schnell_geaendert(quelle, eintrag.get("stand") or {}):
                print("Achtung: Das Original hat sich seit dem Holen geändert. Übertragen bricht dann ab, mit neu "
                      "frisch holen (nur ohne offene Änderungen).")
            return
        if pruefsumme(kopie) != eintrag.get("kopie_sha256"):
            raise kit_basis.abbruch(f"Die Arbeitskopie {kopie.name} hat Änderungen, die nicht übertragen sind. Erst "
                                    f"übertragen, oder der Nutzer verwirft sie selbst im Finder.", FOLGE)
    vorher = quelle.stat()
    try:
        summe = kopieren(quelle, kopie)
    except OSError as e:
        if not vorhanden:
            try:
                kopie.unlink()  # nur die eigene, halb geschriebene Kopie
            except OSError:
                pass
        raise kit_basis.abbruch(f"Kopieren fehlgeschlagen: {e.strerror or e}.", FOLGE) from None
    kopien[str(kopie)] = {"original": str(quelle), "bereich": bereich, "thema": ordner.name, "geholt": jetzt(),
                          "stand": {"mtime": vorher.st_mtime, "groesse": vorher.st_size, "sha256": summe},
                          "kopie_sha256": summe, "uebertragen": None}
    herkunft_speichern(kopien)
    print(f"Arbeitskopie: {kopie}")
    print(f"In Cowork: {cowork_pfad(kopie, cfg)}")
    print(f"Original: {quelle}")
    print(f"Stand des Originals: {zeit_text(vorher.st_mtime)}" + (", frisch geholt" if vorhanden else ""))


def cmd_liste(cfg: dict, nur: str) -> None:
    kopien = herkunft_laden()
    orte = ablage(cfg)
    if nur and nur not in BEREICHE:
        aufruf_falsch(f"bereich ist privat oder arbeit. {FOLGE}")
    zeilen = []
    for bereich, ort in orte.items():
        if nur and bereich != nur:
            continue
        if not ort.is_dir() or ort.is_symlink():
            zeilen.append(f"{bereich}: {ort} (noch leer)")
            continue
        themen = [o for o in sorted(ort.iterdir()) if o.is_dir() and not o.is_symlink() and not o.name.startswith(".")]
        zeilen.append(f"{bereich}: {ort} ({len(themen)} Themen)")
        for thema in themen:
            dateien = [d for d in sorted(thema.iterdir()) if d.is_file() and not d.is_symlink()
                       and not d.name.startswith((".", "~$"))]
            zuletzt = max((d.stat().st_mtime for d in dateien), default=thema.stat().st_mtime)
            zeilen.append(f"- {thema.name} (zuletzt {zeit_text(zuletzt)})")
            for d in dateien:
                e = kopien.get(str(d.resolve()))
                if not e:
                    zeilen.append(f"  - {d.name}: ohne Herkunft, nicht übertragbar")
                    continue
                teile = [f"aus {Path(e['original']).parent.name}"]
                teile.append("geändert, nicht übertragen" if pruefsumme(d) != e.get("kopie_sha256")
                             else ("übertragen" if e.get("uebertragen") else "unverändert"))
                if not Path(e["original"]).is_file():
                    teile.append("Original fehlt am alten Ort")
                elif schnell_geaendert(Path(e["original"]), e.get("stand") or {}):
                    teile.append("Original seit dem Holen geändert")
                zeilen.append(f"  - {d.name}: {', '.join(teile)}")
    print("\n".join(zeilen) if zeilen else "Keine Ablage eingerichtet.")


def cmd_herkunft(cfg: dict, bereich: str, thema: str, datei: str) -> None:
    kopie = kopie_pruefen(cfg, bereich, thema, datei)
    e = herkunft_laden().get(str(kopie))
    if not e:
        raise kit_basis.abbruch(f"{kopie.name} hat keine bekannte Herkunft, sie kam nicht über arbeitskopie.", FOLGE)
    print(f"Arbeitskopie: {kopie}")
    print(f"Original: {e['original']}")
    print(f"Geholt: {e.get('geholt', '')}")


def in_place_schreiben(ziel: Path, quelle: Path) -> None:
    """Inhalt von quelle in die vorhandene Datei ziel: dieselbe Datei, kein Löschen und Neuanlegen, kein Verweis."""
    fd = os.open(ziel, os.O_RDWR | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("keine normale Datei")
        with open(quelle, "rb") as ein, os.fdopen(fd, "r+b", closefd=False) as aus:
            aus.seek(0)
            for stueck in iter(lambda: ein.read(1_000_000), b""):
                aus.write(stueck)
            aus.truncate()
            aus.flush()
            os.fsync(aus.fileno())
    finally:
        os.close(fd)


def cmd_uebertragen(cfg: dict, bereich: str, thema: str, datei: str, ausfuehren: bool) -> None:
    kopie = kopie_pruefen(cfg, bereich, thema, datei)
    kopien = herkunft_laden()
    e = kopien.get(str(kopie))
    if not e:
        raise kit_basis.abbruch(f"{kopie.name} hat keine bekannte Herkunft, sie kam nicht über arbeitskopie.", FOLGE)
    original = Path(e["original"])
    if original.is_symlink() or not original.is_file():
        raise kit_basis.abbruch(f"Das Original fehlt am alten Ort ({original}), verschoben oder umbenannt. Den Nutzer "
                                f"fragen.", FOLGE)
    if office_offen(original):
        raise kit_basis.abbruch(f"{original.name} ist in Office geöffnet. Erst dort schließen.", FOLGE)
    alt = e.get("stand") or {}
    if pruefsumme(original) != alt.get("sha256"):
        raise kit_basis.abbruch(f"Das Original hat sich seit dem Holen geändert (zuletzt "
                                f"{zeit_text(original.stat().st_mtime)}), etwa durch andere in SharePoint. Den Nutzer "
                                f"fragen: neu holen und Änderungen nachziehen, oder er überträgt selbst.", FOLGE)
    neu = pruefsumme(kopie)
    if neu == alt.get("sha256"):
        print(f"Arbeitskopie und Original sind gleich, nichts zu übertragen: {original}")
        return
    if not ausfuehren:
        print(f"Vorschau, nichts geändert: {kopie.name} ersetzt den Inhalt von {original}.")
        return
    sicherung = DATEN_DIR / SICHERUNG_ORDNER / hashlib.sha256(str(original).encode()).hexdigest()[:16]
    if sicherung.is_symlink() or (DATEN_DIR / SICHERUNG_ORDNER).is_symlink():
        raise kit_basis.abbruch("Der Ordner für die Sicherung ist ein Verweis.", FOLGE)
    sicherung.mkdir(parents=True, exist_ok=True)
    alt_datei = sicherung / original.name
    for weg in sicherung.iterdir():  # nur der letzte Stand je Original
        if weg != alt_datei and weg.is_file() and not weg.is_symlink():
            weg.unlink()
    if pruefsumme_kopieren(original, alt_datei) != alt.get("sha256"):
        raise kit_basis.abbruch("Das Original hat sich gerade geändert.", FOLGE)
    try:
        in_place_schreiben(original, kopie)
    except OSError as fehler:
        try:
            in_place_schreiben(original, alt_datei)
            zurueck = "Der alte Stand ist zurückgeschrieben."
        except OSError:
            zurueck = f"Achtung: Das Original kann halb geschrieben sein, der alte Stand liegt in {alt_datei}."
        raise kit_basis.abbruch(f"Übertragen fehlgeschlagen: {fehler.strerror or fehler}. {zurueck}") from None
    if pruefsumme(original) != neu:
        raise kit_basis.abbruch(f"Nach dem Übertragen weicht das Original von der Arbeitskopie ab. Alter Stand in "
                                f"{alt_datei}.")
    st = original.stat()
    e.update({"stand": {"mtime": st.st_mtime, "groesse": st.st_size, "sha256": neu}, "kopie_sha256": neu,
              "uebertragen": jetzt()})
    herkunft_speichern(kopien)
    print(f"Übertragen: {original}")
    print(f"Gleiche Datei am selben Ort, Links bleiben. Alter Stand gesichert: {alt_datei}")


def pruefsumme_kopieren(quelle: Path, ziel: Path) -> str:
    if ziel.is_symlink():
        ziel.unlink()
    return kopieren(quelle, ziel)


OEFFNEN = "/usr/bin/open"


def cmd_zeigen(cfg: dict, bereich: str, thema: str, angabe: str, finder: bool) -> None:
    if bereich or thema:
        ordner = thema_ordner(bereich_ordner(cfg, bereich), thema)
        pfad = ordner / dateiname(angabe) if angabe else ordner
    else:
        if not angabe:
            aufruf_falsch(f"pfad oder bereich und thema angeben. {FOLGE}")
        pfad = mac_pfad(angabe)
    if pfad.is_symlink():
        raise kit_basis.abbruch(f"{pfad.name} ist ein Verweis.", FOLGE)
    try:
        echt = pfad.resolve(strict=True)
    except (OSError, RuntimeError):
        raise kit_basis.abbruch(f"Nicht gefunden: {pfad}.", FOLGE) from None
    if not in_ablage(echt, cfg):
        raise kit_basis.abbruch(f"Zeigen nur in der Ablage, nicht {echt.parent}.", FOLGE)
    dokument = echt.is_dir() or (echt.is_file() and echt.suffix.lower() in OEFFNEN_ENDUNGEN)
    im_finder = finder or not dokument
    befehl = [os.environ.get("KITS_OEFFNEN", "").strip() or OEFFNEN, *(["-R"] if im_finder else []), str(echt)]
    try:
        lauf = subprocess.run(befehl, capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise kit_basis.abbruch(f"Öffnen nicht möglich: {type(e).__name__}.", FOLGE) from None
    if lauf.returncode != 0:
        raise kit_basis.abbruch(f"Öffnen nicht möglich: {' '.join(lauf.stderr.split())[:200]}.", FOLGE)
    print(f"{'Im Finder gezeigt' if im_finder else 'Geöffnet'}: {echt}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] and argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    vorn, rest = kit_basis.schalter_vorn(argv, schalter=("--ausfuehren",))
    p = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    p.add_argument("befehl", choices=("liste", "holen", "zeigen", "herkunft", "uebertragen"))
    p.add_argument("--bereich", default="")
    p.add_argument("--thema", default="")
    p.add_argument("--neu", action="store_true")
    p.add_argument("--finder", action="store_true")
    p.add_argument("angabe", nargs="?", default="")
    # Python 3.9 nimmt -- vor dem zweiten Positionsargument nicht an: den Teil dahinter selbst abtrennen
    nach = rest[rest.index("--") + 1:] if "--" in rest else None
    vor = rest[:rest.index("--")] if "--" in rest else rest
    if nach is not None and len(nach) != 1:
        aufruf_falsch(f"Hinter -- genau eine Angabe. {FOLGE}")
    try:
        a = p.parse_args(vor)
    except SystemExit:
        aufruf_falsch(__doc__)
    if nach is not None:
        if a.angabe:
            aufruf_falsch(f"Die Angabe steht hinter --. {FOLGE}")
        a.angabe = nach[0]
    if vorn and a.befehl != "uebertragen":
        aufruf_falsch(f"--ausfuehren gilt nur für uebertragen. {FOLGE}")
    cfg = config()
    if a.befehl == "liste":
        return cmd_liste(cfg, a.bereich)
    if a.befehl == "zeigen":
        return cmd_zeigen(cfg, a.bereich, a.thema, a.angabe, a.finder)
    if not (a.bereich and a.thema and a.angabe):
        aufruf_falsch(f"bereich, thema und {'das Original' if a.befehl == 'holen' else 'datei'} angeben. {FOLGE}")
    if a.befehl == "holen":
        return cmd_holen(cfg, a.bereich, a.thema, a.angabe, a.neu)
    if a.befehl == "herkunft":
        return cmd_herkunft(cfg, a.bereich, a.thema, a.angabe)
    return cmd_uebertragen(cfg, a.bereich, a.thema, a.angabe, "--ausfuehren" in vorn)


if __name__ == "__main__":
    kit_basis.starten(main, __file__)
