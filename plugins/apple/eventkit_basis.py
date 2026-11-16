"""Gemeinsame Apple-Hilfen mit EventKit für Kalender (add_event.py, move_event.py) und Erinnerungen (reminders.py).

Bis 6.3 lag die Datei als Kopie in den Plugins mail und apple, seit 7.0 nur noch hier. Was ein Bereich allein braucht
(Kalendernamen, Listen), steht in kalender_basis.py und reminders.py.

Inhalt: config.json des Plugins laden (über kit_basis.py), Selbststart in die .venv des Datenordners, Zugriff mit
Systemdialog, Datum zwischen Python und Foundation, Konto und Exchange-Erkennung, deutsche Anzeige, Uhrzeiten an der
Zeitumstellung. EventKit und Foundation laden erst die Funktionen, die sie brauchen. So kommt ohne .venv eine klare
Meldung statt eines Tracebacks, und die Tests setzen Ersatzmodule ein. Läuft auch mit dem System-Python 3.9, denn die
Skripte starten als python3 und wechseln erst dann in die .venv.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import time
from pathlib import Path

import kit_basis

KIT_DIR = Path(__file__).resolve().parent
DATEN_DIR = kit_basis.datenordner(KIT_DIR)  # fester Ordner vom MCP-Server, sonst der Plugin-Ordner
CONFIG_PATH = DATEN_DIR / "config.json"
VENV = DATEN_DIR / ".venv"
VENV_MARKE = "KIT_VENV_GESTARTET"  # einmal gewechselt: fehlt EventKit auch dort, keine Schleife
WOCHENTAGE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
EK_EVENT, EK_REMINDER = 0, 1   # EKEntityType
EK_SOURCE_EXCHANGE = 1         # EKSourceTypeExchange
EK_CALENDAR_EXCHANGE = 2       # EKCalendarTypeExchange


def load_config() -> dict:
    return kit_basis.lade_config(CONFIG_PATH)


def namen(block: dict, schluessel: str, standard=()) -> list:
    """Liste von Namen aus config.json. Ein Text statt einer Liste bricht ab, statt still nichts auszuschließen."""
    wert = block.get(schluessel, list(standard))
    if not isinstance(wert, list) or not all(isinstance(x, str) for x in wert):
        sys.exit(f"config.json: {schluessel} muss eine Liste von Namen sein.")
    return wert


# ---------- Selbststart in die .venv (V3) ----------
def eventkit_da() -> bool:
    """Findet dieser Interpreter EventKit? Ein Eintrag in sys.modules zählt (Ersatzmodule der Tests, None heißt fehlt)."""
    if "EventKit" in sys.modules:
        return sys.modules["EventKit"] is not None
    import importlib.util
    try:
        return importlib.util.find_spec("EventKit") is not None
    except (ImportError, ValueError):
        return False


def venv_starten(skript: str) -> None:
    """Die Skripte laufen als python3 "<Plugin>/skript.py", EventKit liegt aber nur in der .venv des Plugins. Fehlt es, startet
    das Skript sich mit deren Interpreter neu (os.execv: derselbe Prozess, dieselbe Ausnahme von der Sandbox). Nur in eine
    echte .venv im eigenen Kit-Ordner, nie über einen Verweis nach außen, und nur einmal. Lief der Start ohne Bytecode (-B
    oder PYTHONDONTWRITEBYTECODE), bekommt die .venv -B mit, sonst legte sie außerhalb der Session __pycache__ im Kit an
    (Prüfung 20.10.2026). Die Sandbox darf die .venv nicht beschreiben (denyWrite)."""
    if eventkit_da() or os.environ.get(VENV_MARKE):
        return
    python = VENV / "bin" / "python3"
    if VENV.is_symlink() or (VENV / "bin").is_symlink() or not VENV.is_dir() or not python.exists():
        return  # store_with_access sagt dann, dass EventKit fehlt und wie die .venv entsteht
    os.environ[VENV_MARKE] = "1"
    sys.stdout.flush()
    ohne_bytecode = ["-B"] if sys.dont_write_bytecode else []
    try:
        os.execv(str(python), [str(python), *ohne_bytecode, os.path.realpath(skript), *sys.argv[1:]])
    except OSError:
        return  # .venv kaputt (nicht ausführbar, falsches Format): store_with_access meldet es klar, kein Traceback


# ---------- EventKit (lazy, nur auf dem Mac) ----------
def store_with_access(kind: str = "events"):
    """kind: 'events' oder 'reminders'. Fragt einmalig die Systemfreigabe ab."""
    try:
        import EventKit
    except ImportError:
        sys.exit(f"EventKit fehlt, auch in der .venv des Datenordners ({VENV}). Die .venv im Terminal neu anlegen "
                 f"(Netz, etwa 1 Minute): python3.12 -m venv --clear \"{VENV}\" und danach \"{VENV}/bin/pip\" install "
                 f"pyobjc-framework-EventKit")
    store = EventKit.EKEventStore.alloc().init()
    state = {"ok": None}
    cb = lambda g, e: state.__setitem__("ok", g)
    if kind == "reminders":
        store.requestFullAccessToRemindersWithCompletion_(cb)
        hint = "Erinnerungen"
    else:
        store.requestFullAccessToEventsWithCompletion_(cb)
        hint = "Kalender"
    for _ in range(600):   # 30s: der erste Freigabe-Dialog braucht einen Klick, nicht nur eine Antwort
        if state["ok"] is not None:
            break
        time.sleep(0.05)
    if not state["ok"]:
        sys.exit(f"Kein Zugriff auf {hint}. Systemeinstellungen > Datenschutz & Sicherheit > {hint}: Vollzugriff für "
                 f"python3.9 der Command Line Tools (damit laufen die Werkzeuge) oder die Claude-App. Im Code-Tab per "
                 f"Bash als eigenen Befehl mit absolutem Pfad starten (python3 \"{KIT_DIR}/<skript>.py\" ...), ohne cd, "
                 f"Pipe oder Umleitung.")
    return store


def konto(cal) -> str:
    src = cal.source()
    return (src.title() if src is not None else "") or "?"


def ist_exchange(cal) -> bool:
    src = cal.source()
    return (src is not None and src.sourceType() == EK_SOURCE_EXCHANGE) or cal.type() == EK_CALENDAR_EXCHANGE


def nsdate(d: dt.datetime):
    return nsdate_ts(d.timestamp())


def nsdate_ts(t: float):
    import Foundation
    return Foundation.NSDate.dateWithTimeIntervalSince1970_(t)


def ts(nsd) -> float:
    return nsd.timeIntervalSince1970()


def pydt(nsd) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts(nsd))


# ---------- Anzeige ----------
def tag(d) -> str:
    """Di 06.10."""
    return f"{WOCHENTAGE[d.weekday()]} {d:%d.%m.}"


def uhr(t) -> str:
    """14 oder 14:30"""
    return f"{t.hour}" if t.minute == 0 else f"{t.hour}:{t.minute:02d}"


def zeitraum(start: dt.datetime, ende: dt.datetime, ganztaegig: bool = False) -> str:
    """Di 06.10., 14 bis 14:30 Uhr, über Mitternacht Di 06.10., 22 Uhr bis Mi 07.10., 1 Uhr, ganztägig
    Mo 12.10. bis Fr 16.10., ganztägig. Ganztägig zählt das Ende inklusiv, 00:00 des Folgetags gilt als Vortag."""
    if ganztaegig:
        letzter = ende.date()
        if ende.time() == dt.time(0, 0) and letzter > start.date():
            letzter -= dt.timedelta(days=1)
        if letzter <= start.date():
            return f"{tag(start)}, ganztägig"
        return f"{tag(start)} bis {tag(letzter)}, ganztägig"
    if ende <= start:
        return f"{tag(start)}, {uhr(start)} Uhr"
    if ende.date() == start.date():
        return f"{tag(start)}, {uhr(start)} bis {uhr(ende)} Uhr"
    return f"{tag(start)}, {uhr(start)} Uhr bis {tag(ende)}, {uhr(ende)} Uhr"


def ortszeit_eindeutig(d: dt.datetime, folge: str) -> None:
    """Bricht ab, wenn es die Wanduhrzeit d in der Zeitzone des Macs nicht genau einmal gibt (Prüfung 20.10.2026, auch
    für Erinnerungen). Wird die Uhr zurückgestellt, gibt es eine Stunde zweimal, springt sie vor, fehlt eine
    (in Deutschland 2 bis 3 Uhr am letzten Sonntag im Oktober und im März). Python nähme sonst still die erste Fassung
    oder verschöbe um eine Stunde. In beiden Fällen ergeben fold=0 und fold=1 verschiedene Zeitpunkte: Bei doppelter
    Stunde liefert fold=0 den früheren, bei fehlender den späteren."""
    erste, zweite = d.replace(fold=0).timestamp(), d.replace(fold=1).timestamp()
    if erste == zweite:
        return
    wann = f"{tag(d)}, {uhr(d)} Uhr"
    if erste < zweite:
        sys.exit(f"{wann} gibt es zweimal, in dieser Nacht wird die Uhr zurückgestellt. Eine andere Uhrzeit wählen. "
                 f"{folge}")
    sys.exit(f"{wann} gibt es nicht, in dieser Nacht springt die Uhr vor. Eine andere Uhrzeit wählen. {folge}")
