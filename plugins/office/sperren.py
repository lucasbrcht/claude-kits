"""Gesperrte Orte und Regeln für sandbox-exec, gemeinsam für server.py (Motor-Skripte) und office.py (LibreOffice und
pdftoppm). Nur Standardbibliothek, ab Python 3.9, ohne Nebenwirkung beim Import.

Gesperrt sind immer die Datenordner der Apple-Apps und von WhatsApp wie in kit.json von apple und chat, dazu Orte mit
Zugangsdaten (Schlüsselbund, Cookies, Safari, .ssh, .gnupg) und die Datenordner der anderen Plugins des Pakets. Dazu
kommt, was motor.gesperrt in der config.json von office nennt (absolut oder mit ~, * als Platzhalter innerhalb eines
Ordnernamens), etwa der Kontextordner. Der Datenordner von office selbst bleibt lesbar, dort liegt die .venv.

SBPL: Je Ort eine eigene Regel, denn mehrere Filter in einer Regel verknüpft sandbox-exec nicht wie erwartet. Die
letzte passende Regel gilt, darum stehen die Sperren am Ende eines Profils.
"""
import os
import re
from pathlib import Path

FEST = (
    "Library/Mail",
    "Library/Messages",
    "Library/Calendars",
    "Library/Group Containers/group.com.apple.calendar",
    "Library/Group Containers/group.com.apple.reminders",
    "Library/Group Containers/group.com.apple.notes",
    "Library/Group Containers/group.com.apple.usernoted",
    "Library/Application Support/AddressBook",
    "Library/Application Support/WhatsApp",
    "Library/Group Containers/group.net.whatsapp.*",
    "Library/Group Containers/57T9237FN3.desktop.WhatsApp",
    "Library/Containers/net.whatsapp.WhatsApp*",
    "Library/Keychains",
    "Library/Cookies",
    "Library/Safari",
    ".ssh",
    ".gnupg",
)
ANDERE_PLUGINS = ("apple", "chat", "basis", "service", "pflege")
FEHLERPROTOKOLL = ".fehler.jsonl"


class Falsch(ValueError):
    """motor.gesperrt in der config.json ist falsch angegeben."""


def eigene(cfg: dict, heim: Path) -> list:
    """Absolute Pfade aus motor.gesperrt. Ein falscher Eintrag bricht ab, statt still wegzufallen."""
    motor = cfg.get("motor") if isinstance(cfg, dict) else None
    if motor is None:
        return []
    if not isinstance(motor, dict):
        raise Falsch("config.json: Abschnitt motor muss ein Objekt sein.")
    liste = motor.get("gesperrt", [])
    if not isinstance(liste, list) or not all(isinstance(x, str) for x in liste):
        raise Falsch("config.json: motor.gesperrt muss eine Liste von Ordnern sein.")
    aus = []
    for eintrag in (x.strip() for x in liste):
        if not eintrag:
            continue
        pfad = str(heim / eintrag[2:]) if eintrag.startswith("~/") else eintrag
        if not os.path.isabs(pfad) or '"' in pfad or "\\" in pfad or ".." in pfad.split("/"):
            raise Falsch(f"config.json: motor.gesperrt nimmt nur absolute Ordner oder ~/..., nicht {eintrag!r}.")
        aus.append(pfad.rstrip("/") or "/")
    return aus


def orte(cfg: dict, heim: Path, app_daten: Path) -> list:
    """Alle gesperrten Orte als absolute Pfade, Einträge mit * als Muster."""
    liste = [str(heim / o) for o in FEST]
    liste += [str(app_daten / p) for p in ANDERE_PLUGINS] + [str(app_daten / FEHLERPROTOKOLL)]
    return list(dict.fromkeys(liste + eigene(cfg, heim)))


def filter_(pfad: str) -> str:
    """SBPL-Filter für einen Ort: subpath, mit * ein regex auf den Ort und alles darunter."""
    if "*" not in pfad:
        return f'(subpath "{pfad}")'
    teile = re.split(r"(\*)", pfad)
    rx = "".join("[^/]*" if t == "*" else re.sub(r"([.^$+?()\[\]{}|])", r"\\\1", t) for t in teile)
    return f'(regex #"^{rx}(/|$)")'


def sperr_regeln(liste) -> list:
    return [f"(deny file-read* file-write* {filter_(o)})" for o in liste if '"' not in o and "\\" not in o]
