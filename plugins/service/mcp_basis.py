"""Gemeinsamer Unterbau der lokalen MCP-Server: Protokoll über stdio, Werkzeuge mit Stufe, Aufruf der Skripte.

Die Datei liegt gleich in den Plugins apple, chat, office und service (wie kit_basis.py). Ändern nur
zusammen, die Tests in tests/test_mcp_basis.py ebenso, paket.py --pruefen vergleicht alle Stellen. Nur
Standardbibliothek, läuft ab Python 3.9.

Bauform: Der Server ist eine dünne Schicht. Jedes Werkzeug baut eine Argumentliste und startet das
vorhandene Skript des Plugins als eigenen Prozess, ohne Shell. Die Logik bleibt in den Skripten, ihre Tests gelten
weiter, ein Absturz trifft nur den einen Aufruf. Ein Werkzeug liefert (Code, Text) oder (Code, Text, PNG-Pfade),
die Bilder hängt tools/call als MCP-Bildinhalt an. Persönliches (config.json, style/, Textdateien, .venv) kommt aus dem
Datenordner ~/Library/Application Support/Claude Kits/<plugin> (datenordner()), den das Skript als KITS_DATENORDNER
bekommt. Einen Rückfall auf das Repo gibt es nicht (7.0), Tests setzen KITS_DATENORDNER selbst.

Stufen und Annotationen: lesen (readOnlyHint, läuft ohne Rückfrage), schreiben (legt Neues an oder öffnet einen
Entwurf, ändert nichts Bestehendes und sendet nie) und nachfrage (destructiveHint und vor jedem Aufruf ein Dialog von
macOS, den nur der Nutzer am Mac freigibt). Den Dialog zeigt der Server selbst: Die App fragt bei Plugin-Servern in
Cowork trotz destructiveHint nicht und hat dort keine Schalter je Werkzeug.
Senden, Überschreiben und Schreiben mit Wirkung auf andere gibt es nur in der Stufe nachfrage. Löschen gibt es nicht.
"""
from __future__ import annotations

import base64
import fcntl
import json
import os
import pwd
import re
import subprocess
import sys
from pathlib import Path

PROTOKOLL = "2025-06-18"
HEIM = Path(pwd.getpwuid(os.getuid()).pw_dir)  # aus der Benutzerdatenbank, nicht aus HOME (wie mail.py)
APP_DATEN = HEIM / "Library" / "Application Support" / "Claude Kits"
UMGEBUNG = "KITS_DATENORDNER"
AUSGABE_MAX = 60_000  # Zeichen je Antwort, darüber wird gekürzt
ZEIT_STANDARD = 100  # Sekunden je Skriptaufruf, mail_senden und Antworten bekommen mehr
BESCHREIBUNG_MAX = 200
BILD_MAX = 4_000_000  # Bytes je Bild, größere gehen nur als Pfad im Text zurück
STUFEN = ("lesen", "schreiben", "nachfrage")
PATH_ZUSATZ = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin")


class Fehler(Exception):
    """Falsche Argumente eines Werkzeugs: geht als Text mit isError an Claude zurück, der Server läuft weiter."""


class Werkzeug:
    def __init__(self, name: str, titel: str, beschreibung: str, stufe: str, eigenschaften: dict, aufruf,
                 pflicht=(), zeit: int = ZEIT_STANDARD, vorschau=None):
        if stufe not in STUFEN:
            raise ValueError(f"Stufe unbekannt: {stufe}")
        self.name, self.titel, self.beschreibung, self.stufe = name, titel, beschreibung, stufe
        self.eigenschaften, self.pflicht, self.aufruf, self.zeit = eigenschaften, tuple(pflicht), aufruf, zeit
        self.vorschau = vorschau  # nur Stufe nachfrage: Text für den Dialog, etwa Empfänger und Betreff eines Entwurfs

    def annotationen(self) -> dict:
        return {"title": self.titel, "readOnlyHint": self.stufe == "lesen",
                "destructiveHint": self.stufe == "nachfrage", "idempotentHint": self.stufe == "lesen",
                "openWorldHint": self.stufe == "nachfrage"}

    def liste(self) -> dict:
        schema = {"type": "object", "properties": self.eigenschaften, "additionalProperties": False}
        if self.pflicht:
            schema["required"] = list(self.pflicht)
        return {"name": self.name, "title": self.titel, "description": self.beschreibung, "inputSchema": schema,
                "annotations": self.annotationen()}


# ---------- Argumente ----------
def text(args: dict, name: str, pflicht: bool = False, maximal: int = 500) -> str:
    wert = args.get(name)
    if wert is None or (isinstance(wert, str) and not wert.strip()):
        if pflicht:
            raise Fehler(f"{name} fehlt.")
        return ""
    if not isinstance(wert, str):
        raise Fehler(f"{name} muss ein Text sein.")
    if len(wert) > maximal:
        raise Fehler(f"{name} ist länger als {maximal} Zeichen.")
    return wert.strip()


def langtext(args: dict, name: str, maximal: int = 100_000) -> str:
    """Ein Text mit Zeilenumbrüchen (Mail, Nachricht, Notiz), Leerraum am Rand fällt weg."""
    wert = text(args, name, pflicht=True, maximal=maximal)
    return wert.replace("\r\n", "\n")


def zahl(args: dict, name: str, minimum: float = 0, maximum: float = 10_000, ganz: bool = True):
    wert = args.get(name)
    if wert is None:
        return None
    if isinstance(wert, bool) or not isinstance(wert, (int, float)) or (ganz and int(wert) != wert):
        raise Fehler(f"{name} muss eine {'ganze ' if ganz else ''}Zahl sein.")
    if not minimum <= wert <= maximum:
        raise Fehler(f"{name} muss zwischen {minimum} und {maximum} liegen.")
    return int(wert) if ganz else wert


def schalter(args: dict, name: str) -> bool:
    wert = args.get(name, False)
    if not isinstance(wert, bool):
        raise Fehler(f"{name} muss true oder false sein.")
    return wert


def textliste(args: dict, name: str, maximal: int = 20, laenge: int = 300) -> list:
    wert = args.get(name)
    if wert is None:
        return []
    if isinstance(wert, str):
        wert = [wert]
    if not isinstance(wert, list) or not all(isinstance(x, str) for x in wert):
        raise Fehler(f"{name} muss eine Liste von Texten sein.")
    wert = [x.strip() for x in wert if x.strip()]
    if len(wert) > maximal or any(len(x) > laenge for x in wert):
        raise Fehler(f"{name}: höchstens {maximal} Einträge mit je {laenge} Zeichen.")
    return wert


def opt(name: str, wert) -> list:
    """Option als ein Wort --name=wert: Ein Wert mit - vorn gilt so nie als eigener Schalter."""
    if wert is None or wert == "" or wert is False:
        return []
    if wert is True:
        return [name]
    return [f"{name}={wert}"]


# ---------- Datenordner und Aufruf ----------
def datenordner(plugin: str) -> Path | None:
    """Fester Ordner mit config.json: KITS_DATENORDNER (nur Tests), sonst ~/Library/Application Support/Claude Kits/<plugin>.
    None, wenn dort keine config.json liegt. Das Repo zählt nicht: Ein Plugin aus dem Account liegt woanders."""
    wert = os.environ.get(UMGEBUNG, "").strip()
    if wert:
        return Path(wert).expanduser()
    ort = APP_DATEN / plugin
    return ort if (ort / "config.json").is_file() else None


def ohne_daten(plugin: str) -> str:
    return (f"Keine config.json für {plugin} gefunden. Anlegen unter {APP_DATEN / plugin}/config.json (Vorlage "
            f"config.example.json im Plugin, die Einrichtung mit dem Skill einrichten schreibt sie). Nichts ausgeführt.")


# ---------- Einstellungen und Stilprofile im Datenordner ----------
# Für den Skill einrichten, auch in Cowork: Dort erreicht Claude den Datenordner nicht mit Read und Write, nur über den
# Server. Lesen zeigt config.json und die Stilprofile, Schreiben ersetzt ganze Abschnitte oder ein Stilprofil.
EINSTELLUNG_MAX = 30_000  # Zeichen JSON je Aufruf
STILPROFIL_MAX = 40_000  # Zeichen je Stilprofil
SCHLUESSEL_RE = re.compile(r"[a-z][a-z0-9_]{0,40}")
OFFEN_RE = re.compile(r"<[^<>\n]{2,120}>|\bOFFEN\b")


def datenordner_pfad(plugin: str) -> Path:
    """Wie datenordner(), aber auch ohne config.json: für das erste Schreiben."""
    wert = os.environ.get(UMGEBUNG, "").strip()
    return Path(wert).expanduser() if wert else APP_DATEN / plugin


def _sicher_schreiben(pfad: Path, inhalt: str) -> None:
    """Ganz oder gar nicht: erst eine Temp-Datei daneben, dann umbenennen. Kein Schreiben durch einen Verweis."""
    if pfad.is_symlink() or pfad.parent.is_symlink():
        raise Fehler(f"{pfad.name} oder sein Ordner ist ein Verweis.")
    pfad.parent.mkdir(parents=True, exist_ok=True)
    temp = pfad.with_name(f".{pfad.name}.neu")
    temp.write_text(inhalt, encoding="utf-8")
    os.replace(temp, pfad)


def _config(ordner: Path) -> dict:
    pfad = ordner / "config.json"
    if not pfad.is_file():
        return {}
    try:
        cfg = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Fehler(f"config.json ist nicht lesbar ({type(e).__name__}), erst von Hand reparieren.") from None
    if not isinstance(cfg, dict):
        raise Fehler("config.json ist kein Objekt, erst von Hand reparieren.")
    return cfg


def einstellungen_zeigen(plugin: str, vorlage: dict = None) -> tuple:
    """(0, Text): config.json des Plugins, offene Werte (spitze Klammern, OFFEN), fehlende Abschnitte der Vorlage und
    die Stilprofile unter style/. Ohne config.json sagt der Text, welche Abschnitte zu schreiben sind."""
    ordner = datenordner_pfad(plugin)
    cfg = _config(ordner)
    zeilen = [f"Datenordner {plugin}: {ordner}"]
    if cfg:
        text = json.dumps(cfg, ensure_ascii=False, indent=2)
        zeilen += ["config.json:", text]
        offen = sorted(set(OFFEN_RE.findall(text)))
        if offen:
            zeilen.append(f"Offen: {', '.join(offen[:20])}")
    else:
        zeilen.append("Keine config.json, die Einrichtung schreibt sie mit einstellungen_schreiben.")
    if vorlage:
        fehlt = [k for k in vorlage if not k.startswith("_") and k not in cfg]
        if fehlt:
            zeilen.append(f"Abschnitte ohne Eintrag (Vorlage config.example.json): {', '.join(fehlt)}")
            zeilen.append("Vorlage dafür: " + json.dumps({k: vorlage[k] for k in fehlt}, ensure_ascii=False))
    stile = sorted(str(p.relative_to(ordner)) for p in (ordner / "style").glob("**/profil.md")) \
        if (ordner / "style").is_dir() else []
    zeilen.append(f"Stilprofile: {', '.join(stile) if stile else 'keine'}")
    return 0, "\n".join(zeilen)


def einstellungen_schreiben(plugin: str, werte, vorlage: dict = None) -> tuple:
    """(0, Text): ersetzt die genannten Abschnitte der config.json ({Abschnitt: Wert}), alle anderen bleiben. Mit
    vorlage nur Abschnitte aus config.example.json (dazu mcp_nur_lesen) und mit demselben Typ wie dort."""
    if not isinstance(werte, dict) or not werte:
        raise Fehler("werte: ein Objekt {Abschnitt: Wert}, etwa {\"kalender\": {...}}.")
    if len(json.dumps(werte, ensure_ascii=False)) > EINSTELLUNG_MAX:
        raise Fehler(f"werte ist länger als {EINSTELLUNG_MAX} Zeichen.")
    for name, wert in werte.items():
        if not SCHLUESSEL_RE.fullmatch(name):
            raise Fehler(f"Abschnitt {name!r}: Kleinbuchstaben, Ziffern und _, nicht mit _ vorn.")
        if name == "mcp_nur_lesen":
            if not (wert is True or wert is False or (isinstance(wert, list) and all(isinstance(x, str) for x in wert))):
                raise Fehler("mcp_nur_lesen ist true, false oder eine Liste von Instanzen wie [\"arbeit\"].")
        elif vorlage is not None:
            if name not in vorlage:
                erlaubt = ", ".join(k for k in vorlage if not k.startswith("_"))
                raise Fehler(f"Abschnitt {name} gibt es nicht. Erlaubt: {erlaubt}, mcp_nur_lesen.")
            if type(wert) is not type(vorlage[name]):
                raise Fehler(f"Abschnitt {name} muss vom Typ {type(vorlage[name]).__name__} sein wie in der Vorlage.")
    ordner = datenordner_pfad(plugin)
    cfg = _config(ordner)
    neu = [n for n in werte if n not in cfg]
    cfg.update(werte)
    _sicher_schreiben(ordner / "config.json", json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
    ersetzt = [n for n in werte if n not in neu]
    return 0, (f"config.json von {plugin} geschrieben: " + "; ".join(
        x for x in (f"neu {', '.join(neu)}" if neu else "", f"ersetzt {', '.join(ersetzt)}" if ersetzt else "") if x)
        + f". Ort: {ordner / 'config.json'}")


def stilprofil_schreiben(plugin: str, teile: tuple, inhalt: str) -> tuple:
    """(0, Text): style/<teile>/profil.md im Datenordner schreiben oder ersetzen (Markdown, ohne Verweise)."""
    if len(inhalt) > STILPROFIL_MAX:
        raise Fehler(f"text ist länger als {STILPROFIL_MAX} Zeichen.")
    ordner = datenordner_pfad(plugin)
    pfad = ordner.joinpath("style", *teile, "profil.md")
    alt = pfad.is_file()
    _sicher_schreiben(pfad, inhalt.rstrip() + "\n")
    return 0, f"Stilprofil {'ersetzt' if alt else 'angelegt'}: {pfad} ({len(inhalt)} Zeichen)."


def einstellungen_vorschau(a: dict) -> str:
    """Für den Dialog vor einstellungen_schreiben: Plugin, Abschnitte mit ihren Schlüsseln oder das Stilprofil."""
    werte = a.get("werte") if isinstance(a.get("werte"), dict) else {}
    abschnitte = [f"{k} ({', '.join(list(v)[:8])})" if isinstance(v, dict) else k for k, v in werte.items()]
    return angaben(("Plugin", a.get("plugin") or "apple"), ("Abschnitte", abschnitte),
                   ("Stilprofil", a.get("stilprofil")),
                   f"Text: {len(a.get('text') or '')} Zeichen" if a.get("stilprofil") else "",
                   "Achtung: Modus lesen" if "mcp_nur_lesen" in werte else "")


class Lauf:
    """Startet Skripte des Plugins ohne Shell. wurzel ist der Plugin-Ordner (CLAUDE_PLUGIN_ROOT oder Ordner des
    Servers), plugin der Name für den Datenordner."""

    def __init__(self, wurzel: Path, plugin: str):
        self.wurzel, self.plugin = Path(wurzel).resolve(), plugin

    def umgebung(self, daten: Path) -> dict:
        env = dict(os.environ)
        env[UMGEBUNG] = str(daten)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        teile = [p for p in env.get("PATH", "").split(":") if p]
        env["PATH"] = ":".join(teile + [p for p in PATH_ZUSATZ if p not in teile])
        return env

    def __call__(self, skript: str, argumente: list, zeit: int = ZEIT_STANDARD, textdateien: dict = None) -> tuple:
        """(Exit-Code, Ausgabe). textdateien {Name: Text} legt der Lauf vorher im Datenordner an (die Skripte lesen
        Entwürfe nur aus festen Dateien) und räumt sie danach weg, wenn das Skript sie nicht selbst gelöscht hat."""
        daten = datenordner(self.plugin)
        if daten is None:
            return 1, ohne_daten(self.plugin)
        datei = self.wurzel / skript
        if not datei.is_file():
            return 1, f"{skript} fehlt im Plugin ({self.wurzel}). Nichts ausgeführt."
        befehl = (["/bin/bash", str(datei)] if skript.endswith(".sh") else [sys.executable, "-B", str(datei)])
        befehl += [str(a) for a in argumente]
        geschrieben = []
        sperre = None
        try:
            if textdateien:
                daten.mkdir(parents=True, exist_ok=True)
                sperre = open(daten / ".mcp.lock", "w")
                fcntl.flock(sperre, fcntl.LOCK_EX)  # zwei Sitzungen schreiben nie gleichzeitig dieselbe Entwurfsdatei
                for name, inhalt in textdateien.items():
                    pfad = daten / name
                    if pfad.is_symlink():
                        return 1, f"{name} im Datenordner ist ein Verweis. Nichts ausgeführt."
                    pfad.write_text(inhalt, encoding="utf-8")
                    geschrieben.append(pfad)
            lauf = subprocess.run(befehl, capture_output=True, text=True, timeout=zeit, cwd=str(self.wurzel),
                                  env=self.umgebung(daten), stdin=subprocess.DEVNULL)
            code, aus = lauf.returncode, (lauf.stdout or "") + (("\n" + lauf.stderr) if lauf.stderr.strip() else "")
        except subprocess.TimeoutExpired:
            code, aus = 1, (f"{skript}: keine Antwort nach {zeit} Sekunden. Wartet vermutlich ein macOS-Dialog "
                            f"(Freigabe für die Claude-App) oder die App reagiert nicht. Ob etwas geschah, vor einem "
                            f"zweiten Versuch prüfen.")
        except OSError as e:
            code, aus = 1, f"{skript} nicht startbar: {e.strerror or e}."
        finally:
            for pfad in geschrieben:
                try:
                    pfad.unlink()
                except FileNotFoundError:
                    pass
            if sperre:
                sperre.close()
        aus = aus.strip() or ("(keine Ausgabe)" if code == 0 else f"{skript} endete mit Code {code} ohne Meldung.")
        if len(aus) > AUSGABE_MAX:
            aus = aus[:AUSGABE_MAX] + f"\n[gekürzt auf {AUSGABE_MAX} Zeichen]"
        return code, aus


# ---------- Dialog vor der Stufe nachfrage ----------
DIALOG_ZEIT = 120  # Sekunden, ohne Klick gilt der Dialog als abgelehnt
DIALOG_MAX = 1500  # Zeichen im Dialog
DIALOG_WERT_MAX = 300  # Zeichen je Angabe
DIALOG_KNOPF = "Freigeben"
DIALOG_SKRIPT = (
    "on run argv\n"
    "  set antwort to display dialog (item 1 of argv) with title (item 2 of argv) "
    "buttons {\"Abbrechen\", (item 3 of argv)} default button \"Abbrechen\" cancel button \"Abbrechen\" "
    "with icon caution giving up after ((item 4 of argv) as integer)\n"
    "  if gave up of antwort then return \"\"\n"  # eigene Variable: result zeigt nach dem if nicht mehr auf den Dialog
    "  return button returned of antwort\n"
    "end run")


def _kurz(wert, maximal: int = DIALOG_WERT_MAX) -> str:
    if isinstance(wert, list):
        wert = ", ".join(str(x) for x in wert)
    wert = " ".join(str(wert).split())
    return wert if len(wert) <= maximal else wert[:maximal] + " [gekürzt]"


def angaben(*zeilen) -> str:
    """Vorschau für den Dialog in Stichworten: ("Name", Wert) oder ("Name", Wert, maximal)
    wird zu "Name: Wert", ein Text bleibt eine Zeile für sich. Leere Werte fallen weg. Nur, was die Entscheidung
    braucht: Empfänger, Ziel, Datei, Hinweis."""
    aus = []
    for z in zeilen:
        if isinstance(z, tuple):
            if z[1] not in (None, "", [], False):
                aus.append(f"{z[0]}: {_kurz(*z[1:])}")
        elif z:
            aus.append(str(z))
    return "\n".join(aus)


def ordnername(pfad) -> str:
    """Letzter Teil eines Pfads: Im Dialog entscheidet der volle Pfad selten etwas."""
    pfad = str(pfad or "").rstrip("/")
    return Path(pfad).name or pfad


def dialog_text(werkzeug: Werkzeug, args: dict, vorschau: str = "") -> str:
    """Was der Nutzer im Dialog sieht: was Claude tun möchte, darunter die Vorschau des Werkzeugs (etwa Betreff und
    Empfänger) oder ohne Vorschau die gesetzten Angaben."""
    zeilen = [f"Claude möchte: {werkzeug.titel}", ""]
    if vorschau:
        zeilen.append(vorschau)
    else:
        zeilen += [f"{k}: {_kurz(v)}" for k, v in args.items() if v not in (None, "", [], False)]
    text = "\n".join(zeilen).strip()
    return text if len(text) <= DIALOG_MAX else text[:DIALOG_MAX] + " [gekürzt]"


def bestaetigen(text: str) -> tuple:
    """(frei, Grund). Dialog von macOS über osascript, Text als Argument, ohne Shell. Freigeben kann nur ein Klick am
    Mac, Claude sieht den Dialog nicht. Abbrechen, keine Antwort in DIALOG_ZEIT oder kein Dialog möglich: abgelehnt.
    KITS_DIALOG=ja oder nein ersetzt den Dialog, nur für die Tests."""
    test = os.environ.get("KITS_DIALOG", "").strip()
    if test in ("ja", "nein"):
        return test == "ja", "im Test abgelehnt"
    try:
        lauf = subprocess.run(["/usr/bin/osascript", "-e", DIALOG_SKRIPT, text, "Claude Kits", DIALOG_KNOPF,
                               str(DIALOG_ZEIT)], capture_output=True, text=True, timeout=DIALOG_ZEIT + 30,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"kein Dialog möglich ({type(e).__name__})"
    if lauf.returncode == 0 and lauf.stdout.strip() == DIALOG_KNOPF:
        return True, ""
    if lauf.returncode == 0:
        return False, f"keine Antwort im Dialog nach {DIALOG_ZEIT} Sekunden"
    if "-128" in lauf.stderr:
        return False, "im Dialog abgebrochen"
    return False, f"kein Dialog möglich ({' '.join(lauf.stderr.split())[:200] or 'Code ' + str(lauf.returncode)})"


# ---------- Bilder ----------
def bild_inhalt(pfad) -> dict | None:
    """MCP-Bildinhalt für eine PNG-Datei, None bei fehlender, leerer, zu großer oder fremder Datei. Für Werkzeuge,
    die neben dem Text eine Vorschau zeigen (in Cowork sieht Claude Dateien am Mac sonst nicht)."""
    try:
        daten = Path(pfad).read_bytes()
    except (OSError, TypeError, ValueError):
        return None
    if not daten or len(daten) > BILD_MAX or not daten.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    return {"type": "image", "data": base64.b64encode(daten).decode("ascii"), "mimeType": "image/png"}


# ---------- Protokoll ----------
class Server:
    def __init__(self, name: str, version: str, werkzeuge: list, anleitung: str = ""):
        self.name, self.version, self.anleitung = name, version, anleitung
        self.werkzeuge = {w.name: w for w in werkzeuge}
        if len(self.werkzeuge) != len(werkzeuge):
            raise ValueError("Werkzeugname doppelt")

    def antwort(self, nr, ergebnis=None, fehler=None) -> None:
        nachricht = {"jsonrpc": "2.0", "id": nr}
        if fehler is not None:
            nachricht["error"] = fehler
        else:
            nachricht["result"] = ergebnis
        sys.stdout.write(json.dumps(nachricht, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def aufrufen(self, name: str, args: dict) -> tuple:
        """(ist_fehler, Text) wie ausfuehren(), ohne Bilder."""
        return self.ausfuehren(name, args)[:2]

    def ausfuehren(self, name: str, args: dict) -> tuple:
        """(ist_fehler, Text, [PNG-Pfade]). Ein Werkzeug liefert (Code, Text) oder (Code, Text, Bilder)."""
        werkzeug = self.werkzeuge.get(name)
        if werkzeug is None:
            return True, f"Werkzeug unbekannt: {name}", []
        if not isinstance(args, dict):
            return True, "arguments muss ein Objekt sein.", []
        fremd = sorted(set(args) - set(werkzeug.eigenschaften))
        if fremd:
            return True, f"Unbekannte Angabe: {', '.join(fremd)}. Erlaubt: {', '.join(werkzeug.eigenschaften)}.", []
        if werkzeug.stufe == "nachfrage":
            fehlt = [p for p in werkzeug.pflicht if args.get(p) in (None, "", [])]
            if fehlt:
                return True, f"{', '.join(fehlt)} fehlt. Nichts ausgeführt.", []
            try:
                vorschau = werkzeug.vorschau(args) if werkzeug.vorschau else ""
            except Exception:  # die Vorschau ist nur Hilfe für den Nutzer, ohne sie zeigt der Dialog die Angaben
                vorschau = ""
            frei, grund = bestaetigen(dialog_text(werkzeug, args, vorschau))
            if not frei:
                return True, (f"Nicht ausgeführt: {grund}. {werkzeug.name} gibt nur der Nutzer selbst im Dialog am Mac "
                              "frei. Nicht erneut aufrufen, außer er bittet ausdrücklich darum."), []
        try:
            ergebnis = werkzeug.aufruf(args)
        except Fehler as e:
            return True, f"{e} Nichts ausgeführt.", []
        except Exception as e:  # Fehler im Server: als Text zurück, der Server läuft weiter
            return True, f"Fehler im Server {self.name}: {type(e).__name__}: {e}", []
        code, aus = ergebnis[0], ergebnis[1]
        bilder = list(ergebnis[2] or []) if len(ergebnis) > 2 else []
        return code != 0, aus, bilder

    def behandeln(self, nachricht: dict) -> None:
        methode, nr = nachricht.get("method"), nachricht.get("id")
        if nr is None:  # Benachrichtigung, etwa notifications/initialized
            return
        if methode == "initialize":
            version = (nachricht.get("params") or {}).get("protocolVersion") or PROTOKOLL
            ergebnis = {"protocolVersion": version, "capabilities": {"tools": {}},
                        "serverInfo": {"name": self.name, "version": self.version}}
            if self.anleitung:
                ergebnis["instructions"] = self.anleitung
            self.antwort(nr, ergebnis)
        elif methode == "ping":
            self.antwort(nr, {})
        elif methode == "tools/list":
            self.antwort(nr, {"tools": [w.liste() for w in self.werkzeuge.values()]})
        elif methode == "tools/call":
            params = nachricht.get("params") or {}
            ist_fehler, aus, bilder = self.ausfuehren(params.get("name"), params.get("arguments") or {})
            inhalt = [{"type": "text", "text": aus}]
            inhalt += [b for b in (bild_inhalt(p) for p in bilder) if b]
            self.antwort(nr, {"content": inhalt, "isError": ist_fehler})
        elif methode in ("resources/list", "prompts/list"):
            self.antwort(nr, {methode.split("/")[0]: []})
        else:
            self.antwort(nr, fehler={"code": -32601, "message": f"Methode unbekannt: {methode}"})

    def starten(self) -> None:
        for zeile in sys.stdin:
            zeile = zeile.strip()
            if not zeile:
                continue
            try:
                nachricht = json.loads(zeile)
            except json.JSONDecodeError:
                self.antwort(None, fehler={"code": -32700, "message": "kein JSON"})
                continue
            if isinstance(nachricht, dict):
                self.behandeln(nachricht)


def _eltern(tiefe: int = 12) -> list:
    """Programme der Elternprozesse, nächster zuerst (ps -o comm zeigt am Mac den vollen Pfad)."""
    pfade, pid = [], os.getppid()
    for _ in range(tiefe):
        if pid <= 1:
            break
        try:
            aus = subprocess.run(["/bin/ps", "-o", "ppid=,comm=", "-p", str(pid)], capture_output=True, text=True,
                                 timeout=3).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            break
        teile = aus.split(None, 1)
        if len(teile) < 2 or not teile[0].isdigit():
            break
        pfade.append(teile[1])
        pid = int(teile[0])
    return pfade


def instanz() -> str:
    """Welche App den Server startet: privat für Claude Privat (Config-Ordner .claude-privat, Plugin-Ordner
    oder Elternprozess unter Claude Privat), sonst arbeit. KITS_INSTANZ setzt den Wert fest (Tests, Terminal). Im
    Zweifel arbeit: Der Modus lesen greift dann eher zu oft als zu selten."""
    fest = os.environ.get("KITS_INSTANZ", "").strip().lower()
    if fest:
        return fest
    for wert in (os.environ.get("CLAUDE_CONFIG_DIR", ""), os.environ.get("CLAUDE_PLUGIN_ROOT", "")):
        if "claude-privat" in wert.lower() or "claude privat" in wert.lower():
            return "privat"
    if any("claude privat" in p.lower() for p in _eltern()):
        return "privat"
    return "arbeit"


def nur_lesen(plugin: str) -> bool:
    """Modus lesen (für die Arbeit): KITS_NUR_LESEN=1 oder mcp_nur_lesen in der config.json des Plugins, entweder
    true (immer) oder eine Liste von Instanzen wie ["arbeit"] (nur wenn instanz() dazu passt). Dann bietet der Server
    nur Werkzeuge der Stufe lesen an."""
    if os.environ.get("KITS_NUR_LESEN", "").strip() in ("1", "ja", "true"):
        return True
    daten = datenordner(plugin)
    if daten is None:
        return False
    try:
        cfg = json.loads((daten / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    wert = cfg.get("mcp_nur_lesen") if isinstance(cfg, dict) else None
    if wert is True:
        return True
    if isinstance(wert, list):
        return instanz() in [str(x).strip().lower() for x in wert]
    return False
