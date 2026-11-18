#!/usr/bin/env python3
"""Apple Mail vom Terminal aus: suchen, lesen, Entwürfe anlegen, senden. Für das Privatkonto.

Ein verbundener Mail-Connector darf Arbeitsmails suchen (Skill /mail), geschrieben wird mit diesem Skript, auch
für das Arbeitskonto, und für style_sample.py. Alles läuft über AppleScript (osascript). Konto,
Absender und Anhang-Ordner kommen aus dem Abschnitt mail der config.json im Datenordner.

Befehle:
  search   Mails im Posteingang (oder Gesendet) nach Absender, Betreff, Zeitraum finden
  triage   ungelesene Mails der letzten N Stunden plus markierte des letzten Jahres, Newsletter ausgeblendet
  read     eine Mail anhand ihrer ID ausgeben (--html: HTML-Quelltext)
  draft    Entwurf sichtbar in Mail anlegen (nicht senden), mit --reply-to als echte Antwort
  drafts   offene Entwürfe auflisten
  send     einen vom Kit angelegten Entwurf senden (braucht --yes, fragt in Claude Code immer nach)
  discard  einen vom Kit angelegten Entwurf verwerfen: neue Mails direkt, Antworten nur mit --ausfuehren (fragt
           in Claude Code nach, weil das Kit den Text einer Antwort nicht lesen kann)
  signatur die Arbeitssignatur als Fassung für Apple Mail zeigen, mit --kopieren in die Zwischenablage,
           mit --lang samt Footer

Schreibende Schalter (--ausfuehren, --attach) stehen direkt hinter dem Skript, etwa mail.py --ausfuehren discard 12
oder mail.py --attach <Datei> draft --to <Adresse>: Nur auf diese Form greift die Rückfrage, an anderer Stelle
bricht das Skript ab.

Jeder Befehl kennt --help.

Gelernte Fallstricke, die hier eingebaut sind:
- Treffer eines "whose"-Filters immer mit "get" in eine Liste auflösen, sonst
  wertet AppleScript den Filter bei jedem Zugriff neu aus (Minuten statt Sekunden).
- Der Inhalt eines offenen Entwurfs lässt sich nachträglich nicht setzen
  (Fehler -10006). Neue Mails werden darum vorab fertig gebaut, in eine Datei
  geschrieben und beim Anlegen geladen. Für Änderungen: verwerfen und neu anlegen.
- Nach dem Anlegen einer neuen Mail wird die Länge des Inhalts geprüft. Ein
  Entwurf mit leerem Text ist ein Fehler, kein Erfolg.
- "whose"-Filter auf dem Entwürfe-Postfach von Exchange-Konten liefern Fehler
  -1728. Offene Entwürfe werden deshalb als "outgoing messages" angesprochen.
- Antworten laufen über den Mail-Befehl "reply" mit Fenster. Nur so stimmen
  Zitatebene, kompletter Verlauf, Signatur direkt unter dem Text und die
  Thread-Header. Der Inhalt eines solchen Entwurfs ist für AppleScript leer und
  nicht setzbar. Der Text wird darum mit "Einsetzen und Stil anpassen"
  (Cmd+Wahl+Umschalt+V) eingefügt, in der Schrift an der Schreibmarke und mit
  einem leeren Absatz vor der Signatur. Vorher prüft das Skript, dass Mail vorne
  ist, das Antwortfenster aktiv ist und die Schreibmarke im Nachrichtentext
  steht (AXWebArea). Dafür braucht die App, die osascript startet, die
  Bedienungshilfen-Freigabe.
- Die Zwischenablage wird dafür komplett gesichert (alle Typen, auch Bilder)
  und danach wiederhergestellt. "the clipboard as text" reicht nicht, Bilder
  gingen dabei verloren. Der eingefügte Text ist als flüchtig markiert, damit
  Zwischenablage-Verläufe ihn nicht speichern.
- Weil der Inhalt einer Antwort nicht lesbar ist, merkt sich das Kit pro Entwurf
  Art, Betreff, Zeitpunkt, ob der Text eingefügt wurde, eine Prüfsumme des
  Textanfangs (DRAFT_STATE, kein Klartext) und den Start des Mail-Prozesses. Nach
  einem Neustart vergibt Mail Entwurfs-IDs neu, alte Einträge gelten dann nicht mehr.
- Beim Schließen eines Antwortfensters fragt Mail nach dem Sichern.
  "delete" auf der outgoing message verwirft ohne Rückfrage, lässt aber die
  Kopie liegen, die Mail nach etwa 30 Sekunden automatisch ins Postfach
  Entwürfe sichert. discard entfernt diese Kopie mit, aber nur bei gleichem
  Betreff, passendem Zeitraum und gleicher Prüfsumme.
- In Skripten mit "use framework" nimmt "POSIX file" keine Variable,
  stattdessen "(pfad as POSIX file)".
- Variablennamen wie "pop", "before", "after" oder "rd" kollidieren mit
  AppleScript oder dem Mail-Wörterbuch (Fehler -1700, -2741).
- Jede Eigenschaft einer Mail ist ein eigener Apple Event (etwa 7 ms). Pro Mail
  nur die nötigen Eigenschaften holen: im Postfach Gesendet ohne Lese- und
  Markierungsstatus, dafür die Empfänger.
- AppleScript trennt Felder mit dem Zeichen 31 und Datensätze mit 30. Betreffe mit
  Senkrechtstrich oder Zeilentrennern (U+2028) verwirren so weder die Auswertung
  noch die Ausgabe. Die beiden Zeichen selbst ersetzt no_sep schon im AppleScript in
  Betreff, Absender und Namen, Python nimmt nur Datensätze mit genau der erwarteten
  Feldzahl, id und Datum (gueltige). Ein fremder Betreff fälscht so keine Zeile.
- send und discard gelten nur für Entwürfe, die das Kit selbst angelegt hat (Eintrag
  in DRAFT_STATE mit gleichem Betreff aus demselben Mail-Lauf). Eigene offene
  Entwurfsfenster bleiben unberührt. discard verwirft neue
  Mails ohne Rückfrage, wenn die ersten 300 Zeichen des eigenen Textes unverändert
  sind (TEXT_PRUEFUNG). Antworten nur mit --ausfuehren: ihren Text liest AppleScript nicht.
- inbox und sent mailbox sind Sammelpostfächer über alle Konten, auch das große
  Exchange-Postfach. search sucht deshalb in den Postfächern der Konten darunter
  (account_boxes). Liefert Mail sie nicht einzeln, sucht es wie früher im
  Sammelpostfach und prüft das Konto je Treffer.
- Ein Konto aus accounts, das Mail nicht kennt (deaktiviert oder umbenannt), fiele
  dabei still weg, und "nichts Neues" wäre gelogen. missing_accounts meldet es als
  Steuersatz #fehlt, search, finden und triage nennen es in der Ausgabe als nicht
  durchsucht (Etappe 2 von v7.3.0).
- draft --reply-to mit --betreff-erwartet vergleicht den Betreff der Mail im selben
  AppleScript vor reply, ohne Re:, AW:, WG:, Fwd: und Leerraum, Groß und Klein egal.
  Passt er nicht, öffnet sich nichts: Schutz gegen eine verwechselte Mail-ID.
- Nach dem Einfügen einer Antwort zählt das Skript die Zeichen im Nachrichtentext
  (AXNumberOfCharacters) vorher und nachher. Kommt deutlich weniger an als erwartet,
  gilt der Text als nicht eingefügt. Liefern die Bedienungshilfen keine Zahl, gilt er
  als eingefügt, und die Meldung sagt, dass sich nichts nachzählen ließ.
- Setzt Mail den Absender einer neuen Mail nicht wie verlangt (etwa eine Adresse, die
  kein Konto kennt), ginge sie still von einem anderen Konto. draft liest den Absender
  nach dem Anlegen zurück und endet bei einer Abweichung mit Code 5, send verweigert
  dann (Prüfung 20.10.2026).
- send bleibt samt Prüfung im Postfach Gesendet unter den 120 s des Bash-Werkzeugs
  (SEND_GRENZE). Antwortet Mail nicht rechtzeitig, meldet send die Bestätigung als
  offen, statt abzubrechen: Gesendet hat Mail dann schon.
- Eine leere Liste accounts hieße für die AppleScripts alle Konten, auch das große
  Exchange-Postfach. resolve_accounts bricht deshalb ab, in_accounts lässt bei null
  Konten keine Mail durch. Ein Profil gilt für search, read und draft nur, wenn sein
  Konto in accounts steht (mail_profil). Dort steht auch das Arbeitskonto: Arbeitsmails
  liest und entwirft das Skript mit --profile arbeit.
"""
from __future__ import annotations  # Typangaben wie str | None auch mit dem System-Python 3.9

import argparse
import email
import email.policy
import email.utils
import functools
import hashlib
import html
import json
import os
import pwd
import re
import shlex
import subprocess
import sys
import tempfile
import time
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from typing import NamedTuple

import kit_basis  # gemeinsame Bausteine, gleich in apple und chat

KIT_DIR = Path(__file__).resolve().parent
# Beide Pfade fest. Aus der Umgebung nur der Datenordner des MCP-Servers, und nur unter den erlaubten Wurzeln
# (kit_basis.datenordner): Das Skript läuft außerhalb der Sandbox.
CONFIG_PATH = kit_basis.datenordner(KIT_DIR) / "config.json"
# Offene Entwürfe des Kits: Art, Betreff, Zeitpunkt, eingefügt ja/nein, Prüfsummen, Mail-Start, Absender. Der Stand
# entscheidet, was send und discard als Kit-Entwurf ansehen. Deshalb liegt er außerhalb des Kit-Ordners, den die Sandbox
# beschreiben darf, der Ordner kommt aus der Benutzerdatenbank und nicht aus HOME. Der Ordnername communication-kit
# bleibt, damit offene Entwürfe über Updates erkannt werden.
DRAFT_STATE = (Path(pwd.getpwuid(os.getuid()).pw_dir) / "Library" / "Application Support" / "Claude Kits"
               / "communication-kit" / "entwuerfe.json")
# So viele Zeichen des eigenen Textes vergleicht discard bei neuen Mails, bevor es ohne Rückfrage verwirft. Bei kurzen
# Mails der ganze Text. draft_line liefert 400 Zeichen roh, normalize fasst Leerraum zusammen, 300 lässt Spielraum.
TEXT_PRUEFUNG = 300

# Einzige Textdateien für Entwürfe, im Kit-Ordner (kit_basis.textdatei). draft löscht sie nach einem Erfolg selbst.
TEXT_NAMEN = ("entwurf.txt", "antwort.txt")
DATA_NOTE = kit_basis.daten_hinweis("Mailinhalte")
FSEP, RSEP = "\x1f", "\x1e"  # Feld- und Datensatztrenner in der AppleScript-Ausgabe
STEUERZEICHEN = re.compile(r"[\x00-\x1f\x7f\u0085  ]")
MAX_TREFFER = 250  # Obergrenze je Suche, bevor sortiert und auf --limit gekürzt wird
NUR_ZIFFERN = re.compile(r"[0-9]+")
ISO_ZEIT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}")  # wie iso() in AS_COMMON

# Exit-Codes: 1 nicht gesendet oder Fehler, 2 Aufruf falsch (argparse), 3 Antwort offen, Text nicht eingefügt,
# 4 neuer Entwurf leer, 5 neuer Entwurf mit anderem Absender als in config.json
EXIT_NOT_INSERTED = 3
EXIT_EMPTY = 4
EXIT_ABSENDER = 5

# send bleibt sicher unter den 120 s des Bash-Werkzeugs (Prüfung 20.10.2026): Entwurf prüfen und senden je höchstens
# SEND_SCHRITT Sekunden, die Suche im Postfach Gesendet endet spätestens SEND_GRENZE Sekunden nach dem Start.
SEND_SCHRITT = 30
SEND_GRENZE = 100

# Texte je Kontoprofil, die mail.py und style_sample.py lesen
PROFIL_TEXTE = ("account", "from_name", "from_address", "signature", "signatur_html", "signatur_footer_html")

# triage: Standard und Obergrenze der Stunden (ein Jahr wie bei den markierten Mails, sonst rechnet AppleScript mit
# unsinnigen Zeiträumen), Standard für triage.max_markiert
TRIAGE_STUNDEN = 48
TRIAGE_MAX_STUNDEN = 8760
TRIAGE_MARKIERT = 10

# ---------- Helfer ----------


def pruefe_config(cfg: dict) -> None:
    """Falsche Typen brechen mit dem Schlüssel ab statt mit einem Traceback (Prüfung 20.10.2026). Ein Text statt einer
    Liste machte anhang_ordner sonst still zu fast jedem Ordner: Jedes Zeichen gälte als Ordner, darunter /."""
    fehler = []
    konten = cfg.get("accounts", [])
    if not isinstance(konten, list) or not all(isinstance(k, str) and k.strip() for k in konten):
        fehler.append("accounts muss eine Liste von Kontonamen sein (wie in Apple Mail)")
    if not isinstance(cfg.get("default_profile", ""), str):
        fehler.append("default_profile muss ein Profilname sein")
    profile = cfg.get("profiles", {})
    if not isinstance(profile, dict):
        fehler.append("profiles muss ein Objekt sein")
        profile = {}
    for name, prof in profile.items():
        if not isinstance(prof, dict):
            fehler.append(f"profiles.{name} muss ein Objekt sein")
            continue
        fehler += [f"profiles.{name}.{k} muss ein Text sein" for k in PROFIL_TEXTE
                   if k in prof and not isinstance(prof[k], str)]
    standard = cfg.get("default_profile", "")
    if isinstance(standard, str) and standard and standard not in profile:
        fehler.append(f"default_profile {standard} steht nicht unter profiles")
    ordner = cfg.get("anhang_ordner", [])
    if not isinstance(ordner, list) or not all(isinstance(o, str) and os.path.isabs(os.path.expanduser(o))
                                               for o in ordner):
        fehler.append("anhang_ordner muss eine Liste von Ordnern sein, absolut oder mit ~")
    suche = cfg.get("search", {})
    if not isinstance(suche, dict):
        fehler.append("search muss ein Objekt sein")
    else:
        fehler += [f"search.{k} muss eine ganze Zahl ab 1 sein" for k in ("default_days", "default_limit")
                   if k in suche and (type(suche[k]) is not int or suche[k] < 1)]
    # Ein Text statt einer Liste in noise blendete in der Triage fast alles aus (Prüfung 20.10.2026)
    noise = cfg.get("noise", [])
    if not isinstance(noise, list) or not all(isinstance(n, str) for n in noise):
        fehler.append("noise muss eine Liste von Texten sein")
    triage = cfg.get("triage", {})
    if not isinstance(triage, dict):
        fehler.append("triage muss ein Objekt sein")
    elif "max_markiert" in triage and (type(triage["max_markiert"]) is not int or triage["max_markiert"] < 0):
        fehler.append("triage.max_markiert muss eine ganze Zahl ab 0 sein")
    if fehler:
        sys.exit("config.json: " + ". ".join(fehler) + ". Nichts geändert.")


def load_config() -> dict:
    """Abschnitt mail der config.json im Datenordner (eine Datei für Mail, Kalender, Notizen, Erinnerungen, Kontakte)."""
    cfg = kit_basis.abschnitt(kit_basis.lade_config(CONFIG_PATH), "mail", "Nichts geändert.")
    pruefe_config(cfg)
    return cfg


def falscher_aufruf(text: str) -> None:
    """Abbruch mit Code 2 wie bei argparse: Der Aufruf passt nicht (Review 21.10.2026)."""
    print(text, file=sys.stderr)
    sys.exit(2)


def positiv(text: str) -> int:
    """argparse-Typ für --days, --limit und --max-chars: ganze Zahl ab 1, sonst ein falscher Aufruf (Code 2). Vorher
    galt 0 still als Standard und eine negative Zahl suchte nichts oder kürzte verkehrt herum."""
    try:
        zahl = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"keine ganze Zahl: {text}") from None
    if zahl < 1:
        raise argparse.ArgumentTypeError(f"muss größer als 0 sein: {text}")
    return zahl


def stunden(text: str) -> int:
    """argparse-Typ für die Stunden der Triage: nur Ziffern, höchstens TRIAGE_MAX_STUNDEN. Führende Nullen zählen nicht
    (048 sind 48 Stunden)."""
    if not NUR_ZIFFERN.fullmatch(text):
        raise argparse.ArgumentTypeError(f"Stunden als ganze Zahl angeben, nicht {text}. Aufruf: mail.py triage "
                                         "[stunden] [profil], etwa mail.py triage 48 privat")
    zahl = int(text)
    if zahl > TRIAGE_MAX_STUNDEN:
        raise argparse.ArgumentTypeError(f"Höchstens {TRIAGE_MAX_STUNDEN} Stunden (ein Jahr). Weiter zurück sucht "
                                         "mail.py search --unread --days N.")
    return zahl


def get_profile(cfg: dict, name: str) -> dict:
    """Kontoprofil aus config.json['profiles'] holen (Konto, Absender, Signatur). Ein unbekanntes Profil ist ein
    falscher Aufruf, default_profile prüft schon pruefe_config."""
    profiles = cfg.get("profiles", {})
    if name not in profiles:
        falscher_aufruf(f"Unbekanntes Profil: {name}. Verfügbar: {', '.join(profiles) or '(keine)'}")
    return profiles[name]


def mail_profil(cfg: dict, name: str) -> dict:
    """Profil für search, read und draft: Sein Konto muss in accounts stehen (Review 21.10.2026). Auch das
    Arbeitskonto steht dort, geschrieben wird in Apple Mail, nie über einen Connector."""
    prof = get_profile(cfg, name)
    konto = prof.get("account", "")
    if not konto.strip():
        sys.exit(f"Profil {name} hat kein account in config.json. Den Kontonamen wie in Apple Mail eintragen.")
    if konto not in cfg.get("accounts", []):
        falscher_aufruf(f"Profil {name} (Konto {konto}) gilt hier nicht: search, read, Triage und draft nur für Konten "
                        "aus accounts in config.json. Ein weiteres Konto dort eintragen, Skill /mail.")
    return prof


def profile_for_account(cfg: dict, account: str) -> tuple[str, dict]:
    """Profil, dessen Konto zu einem Mail-Kontonamen passt. Ohne Treffer: leeres Profil."""
    for name, prof in cfg.get("profiles", {}).items():
        if prof.get("account") == account:
            return name, prof
    return "", {}


def resolve_accounts(cfg: dict, profile: str | None) -> list[str]:
    """Kontonamen zum Filtern: bei --profile nur dessen Konto, und nur, wenn es in accounts steht (mail_profil), sonst
    cfg['accounts']. Nie leer: Für die AppleScripts hieße das alle Konten, auch das Exchange-Postfach der Arbeit
    (Prüfung 20.10.2026)."""
    if profile:
        return [mail_profil(cfg, profile)["account"]]
    konten = cfg.get("accounts", [])
    if not konten:
        sys.exit("config.json: accounts ist leer. Mindestens ein Konto eintragen (Name wie in Apple Mail) oder --profile "
                 "angeben.")
    return konten


def run_as(script: str, *args: str, timeout: int = 90, zeitablauf: str = "") -> str:
    """AppleScript über stdin ausführen, Argumente als argv übergeben.

    Argumente laufen nie durch String-Interpolation ins Skript, damit
    Anführungszeichen und Sonderzeichen keine Syntaxfehler auslösen. Der Timeout liegt unter den 120 s des
    Bash-Werkzeugs, damit die eigene Meldung ankommt. zeitablauf ersetzt die Meldung, wenn Mail nicht rechtzeitig
    antwortet, etwa bei send, wo dann offen ist, ob die Mail schon raus ist.
    """
    try:
        r = subprocess.run(
            ["osascript", "-", *args],
            input=script,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        sys.exit("osascript nicht gefunden. Das Kit läuft nur auf macOS.")
    except subprocess.TimeoutExpired:
        sys.exit(zeitablauf or f"Mail hat nach {timeout} s nicht geantwortet. Zeitraum oder Treffer eingrenzen.")
    if r.returncode != 0:
        msg = r.stderr.strip() or "unbekannter AppleScript-Fehler"
        if "-1743" in msg or "nicht erlaubt" in msg or "not allowed" in msg:
            msg += ("\nHinweis: Systemeinstellungen > Datenschutz & Sicherheit > Automation: "
                    "der App, die das Kit startet, den Zugriff auf Mail erlauben.")
        if "-600" in msg or "-10810" in msg:
            msg += ("\nHinweis: Lief der Befehl in der Sandbox? Dann als eigenen Befehl mit absolutem Pfad aufrufen: "
                    f'python3 "{KIT_DIR / "mail.py"}" <befehl>, ohne cd davor und ohne Pipe oder Umleitung.')
        sys.exit(f"AppleScript-Fehler: {msg}")
    return r.stdout.rstrip("\n")


def write_temp(text: str) -> str:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
    tmp.write(text)
    tmp.close()
    return tmp.name


def clean(s: str) -> str:
    """Feld für die Ausgabe in einer Zeile: Terminalfolgen und Richtungszeichen (kit_basis.ohne_steuerzeichen),
    Nullbreiten- und andere Formatzeichen (Kategorie Cf) raus, Zeilentrenner als Leerzeichen, Senkrechtstrich als
    Schrägstrich. Ein fremder Betreff kann so nichts umdrehen oder verstecken (Review 21.10.2026)."""
    s = "".join(z for z in kit_basis.ohne_steuerzeichen(s) if unicodedata.category(z) != "Cf")
    return " ".join(STEUERZEICHEN.sub(" ", s).split()).replace("|", "/")


def empfaenger(an: str, cc: str = "", bcc: str = "") -> str:
    """Alle Empfänger in einem Feld: an a@b.de, Cc c@d.de, Bcc e@f.de. Leere Gruppen fehlen, ohne jeden Empfänger
    (ohne Empfänger). Cc und Bcc gehören in jede Anzeige vor dem Senden (Review 21.10.2026)."""
    teile = [f"{name} {clean(wer)}" for name, wer in (("an", an), ("Cc", cc), ("Bcc", bcc)) if clean(wer)]
    return ", ".join(teile) or "(ohne Empfänger)"


def records(out: str) -> list[list[str]]:
    """AppleScript-Ausgabe mit Datensätzen (Zeichen 30) und Feldern (Zeichen 31) zerlegen."""
    return [rec.split(FSEP) for rec in out.split(RSEP) if rec.strip("\n")]


def gueltige(recs: list[list[str]], felder: int, datum: int | None = None) -> tuple[list[list[str]], int]:
    """Datensätze mit genau felder Feldern, einer id aus Ziffern vorn und, wenn datum gesetzt ist, einem Datum
    JJJJ-MM-TT HH:MM an dieser Stelle, dazu die Zahl der übrigen. Die AppleScripts ersetzen die Trennzeichen schon in
    Betreff, Absender und Namen (no_sep), das hier fängt ab, was trotzdem Felder verschöbe (Review 21.10.2026)."""
    gut = [r for r in recs if len(r) == felder and NUR_ZIFFERN.fullmatch(r[0])
           and (datum is None or ISO_ZEIT.fullmatch(r[datum]))]
    return gut, len(recs) - len(gut)


def uebersprungen(anzahl: int) -> str:
    """Zeile für die Ausgabe, wenn gueltige Datensätze verworfen hat. Leer bei 0."""
    return f"[{anzahl} Datensätze von Mail in unerwartetem Format übersprungen]" if anzahl else ""


def steuersaetze(recs: list[list[str]], konten: list[str]) -> tuple[str, list[str], list[list[str]]]:
    """Steuersätze vorn in der Ausgabe abtrennen: #weg (konto oder sammel, nur als erster Datensatz) und je ein #fehlt
    für ein Konto aus accounts, das Mail nicht liefert (missing_accounts). Ergebnis: Weg, fehlende Konten in der
    Reihenfolge von konten, übrige Datensätze. Ein Steuersatz zwischen den Mails bleibt drin und zählt in gueltige als
    unerwartetes Format. Ein #fehlt mit einem Namen außerhalb von konten fällt weg."""
    weg, fehlt, i = "", set(), 0
    if recs and len(recs[0]) == 2 and recs[0][0] == "#weg":
        weg, i = recs[0][1], 1
    while i < len(recs) and len(recs[i]) == 2 and recs[i][0] == "#fehlt":
        fehlt.add(recs[i][1].casefold())  # AppleScript vergleicht Namen ohne Groß und Klein
        i += 1
    return weg, [k for k in konten if k.casefold() in fehlt], recs[i:]


def nicht_gefunden(fehlt: list[str], postfach: str) -> list[str]:
    """Je Konto aus accounts, das Mail nicht liefert, eine Zeile. Ein leeres Ergebnis ist sonst kein Beweis: Das Konto
    wurde nie durchsucht (Etappe 2 von v7.3.0)."""
    return [f"Konto {clean(k)}: in Mail nicht gefunden (deaktiviert oder umbenannt?), {postfach} nicht durchsucht. "
            "Name in accounts der config.json mit Apple Mail abgleichen." for k in fehlt]


@functools.lru_cache(maxsize=1)
def mail_start() -> str:
    """Startzeit des laufenden Mail-Prozesses. Mail vergibt Entwurfs-IDs nach einem Neustart neu, deshalb gehört
    ein Statuseintrag nur zu dem Mail-Lauf, in dem er entstand. Leer, wenn sich das nicht feststellen lässt. ps rechnet
    in UTC: Nach einem Wechsel der Zeitzone (Reise) sähen sonst alle Kit-Entwürfe fremd aus."""
    try:
        pid = subprocess.run(["pgrep", "-x", "Mail"], capture_output=True, text=True, timeout=5).stdout.split()
        if not pid:
            return ""
        return subprocess.run(["ps", "-o", "lstart=", "-p", pid[0]], capture_output=True, text=True, timeout=5,
                              env={**os.environ, "TZ": "UTC"}).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


# Texte von Mail ohne die Trennzeichen 30 und 31: Ein fremder Betreff, Absender oder Name könnte sonst Felder
# verschieben oder ganze Zeilen vortäuschen (Review 21.10.2026). addr_list liefert die Adressen einer Empfängerliste
# (An, Cc, Bcc).
AS_REIN = '''
on no_sep(txt)
  set txt to txt as string
  set oldTID to AppleScript's text item delimiters
  set AppleScript's text item delimiters to {character id 30, character id 31}
  set pieces to text items of txt
  set AppleScript's text item delimiters to " "
  set txt to pieces as string
  set AppleScript's text item delimiters to oldTID
  return txt
end no_sep
on addr_list(rs)
  set out to ""
  tell application "Mail"
    repeat with r in rs
      if out is not "" then set out to out & ", "
      set out to out & (address of r)
    end repeat
  end tell
  return my no_sep(out)
end addr_list
'''

# Gemeinsame AppleScript-Handler: Datum als ISO, Zeilen für die Suche, Kontoprüfung.
AS_COMMON = AS_REIN + '''
on pad(n)
  set s to n as string
  if (count s) < 2 then set s to "0" & s
  return s
end pad
on iso(d)
  return (year of d as string) & "-" & my pad(month of d as integer) & "-" & my pad(day of d) & " " & my pad(hours of d) & ":" & my pad(minutes of d)
end iso
on line_for(m)
  tell application "Mail"
    set statusTxt to "gelesen"
    if read status of m is false then set statusTxt to "ungelesen"
    if flagged status of m then set statusTxt to statusTxt & ", markiert"
    return (id of m as string) & "@F@" & my iso(date received of m) & "@F@" & my no_sep(sender of m) & "@F@" & my no_sep(subject of m) & "@F@" & statusTxt & "@R@"
  end tell
end line_for
on line_for_sent(m)
  tell application "Mail"
    set wer to "an " & my addr_list(to recipients of m)
    set ccList to my addr_list(cc recipients of m)
    if ccList is not "" then set wer to wer & ", Cc " & ccList
    set bccList to my addr_list(bcc recipients of m)
    if bccList is not "" then set wer to wer & ", Bcc " & bccList
    return (id of m as string) & "@F@" & my iso(date received of m) & "@F@" & wer & "@F@" & my no_sep(subject of m) & "@F@" & "gesendet" & "@R@"
  end tell
end line_for_sent
on in_accounts(m, argv, startIdx, n)
  if n is 0 then return false
  tell application "Mail" to set acctName to (name of account of mailbox of m)
  repeat with i from startIdx to (startIdx + n - 1)
    if acctName is (item i of argv) then return true
  end repeat
  return false
end in_accounts
on account_boxes(which, acctNames)
  set boxes to {}
  if (count acctNames) is 0 then return boxes
  tell application "Mail"
    try
      if which is "sent" then
        set tops to (get mailboxes of sent mailbox)
      else
        set tops to (get mailboxes of inbox)
      end if
      repeat with mb in tops
        if acctNames contains (name of account of mb) then set end of boxes to (contents of mb)
      end repeat
    on error
      return {}
    end try
  end tell
  return boxes
end account_boxes
on missing_accounts(boxes, acctNames)
  set found to {}
  tell application "Mail"
    try
      if (count boxes) > 0 then
        repeat with mb in boxes
          set end of found to (name of account of (contents of mb))
        end repeat
      else
        repeat with ac in (get accounts)
          if enabled of ac then set end of found to (name of ac)
        end repeat
      end if
    on error
      set found to {}
    end try
  end tell
  set out to ""
  repeat with nm in acctNames
    if found does not contain (contents of nm) then set out to out & "#fehlt@F@" & my no_sep(contents of nm) & "@R@"
  end repeat
  return out
end missing_accounts
'''.replace("@F@", FSEP).replace("@R@", RSEP)

# Muss ganz oben im Skript stehen. Nötig für die Zwischenablage (NSPasteboard).
AS_USE_OBJC = '''use AppleScript version "2.4"
use framework "Foundation"
use framework "AppKit"
use scripting additions
'''

# Zwischenablage komplett sichern und wiederherstellen, Text flüchtig setzen.
AS_CLIPBOARD = '''
on clip_save()
  set pb to current application's NSPasteboard's generalPasteboard()
  set saved to {}
  set theItems to pb's pasteboardItems()
  if theItems is missing value then return saved
  repeat with anItem in (theItems as list)
    set dataDict to current application's NSMutableDictionary's dictionary()
    repeat with t in ((anItem's types()) as list)
      set d to (anItem's dataForType:t)
      if d is not missing value then (dataDict's setObject:d forKey:t)
    end repeat
    set end of saved to dataDict
  end repeat
  return saved
end clip_save

on clip_set_text(txt)
  set pb to current application's NSPasteboard's generalPasteboard()
  pb's clearContents()
  set anItem to current application's NSPasteboardItem's alloc()'s init()
  anItem's setString:txt forType:(current application's NSPasteboardTypeString)
  anItem's setString:"" forType:"org.nspasteboard.TransientType"
  anItem's setString:"" forType:"org.nspasteboard.ConcealedType"
  pb's writeObjects:{anItem}
end clip_set_text

on clip_restore(saved)
  set pb to current application's NSPasteboard's generalPasteboard()
  pb's clearContents()
  if (count of saved) is 0 then return
  set newItems to {}
  repeat with dataDict in saved
    set anItem to current application's NSPasteboardItem's alloc()'s init()
    repeat with t in ((dataDict's allKeys()) as list)
      (anItem's setData:(dataDict's objectForKey:t) forType:t)
    end repeat
    set end of newItems to anItem
  end repeat
  pb's writeObjects:newItems
end clip_restore
'''

# Text in das Antwortfenster einfügen. Ergebnis: ok, ok ungeprueft, leer <vorher> <nachher>, fenster, freigabe ...,
# fokus ..., fehler ...
# Die Zwischenablage wird vor der Fokusprüfung gesichert, damit zwischen Prüfung und Tastendruck nichts Langsames liegt.
# Danach zählt chars_in_focus die Zeichen im Nachrichtentext: Steigt die Zahl um weniger als mindest, kam der Text nicht
# an. -1 heißt, die Bedienungshilfen liefern keine Zahl, dann bleibt es ungeprüft.
AS_INSERT = '''
on focus_ok(subj)
  tell application "System Events" to set fm to name of first application process whose frontmost is true
  if fm is not "Mail" then return false
  tell application "Mail" to set wn to name of window 1
  return wn is subj
end focus_ok

on chars_in_focus()
  try
    tell application "System Events" to tell process "Mail"
      return (value of attribute "AXNumberOfCharacters" of (value of attribute "AXFocusedUIElement")) as integer
    end tell
  on error
    return -1
  end try
end chars_in_focus

on insert_text(txt, subj, mindest)
  tell application "Mail" to activate
  set ready to false
  repeat 40 times
    if my focus_ok(subj) then
      set ready to true
      exit repeat
    end if
    delay 0.2
  end repeat
  if not ready then return "fenster"
  set saved to my clip_save()
  try
    tell application "System Events" to tell process "Mail"
      set fRole to value of attribute "AXRole" of (value of attribute "AXFocusedUIElement")
    end tell
  on error e
    return "freigabe " & e
  end try
  if fRole is not "AXWebArea" then return "fokus " & fRole
  set vorN to my chars_in_focus()
  my clip_set_text(txt)
  set res to "ok"
  try
    if not my focus_ok(subj) then error "Fenster nicht mehr vorne"
    tell application "System Events" to keystroke "v" using {command down, option down, shift down}
    delay 1.5
  on error e
    set res to "fehler " & e
  end try
  my clip_restore(saved)
  if res is "ok" then
    set nachN to my chars_in_focus()
    if vorN < 0 or nachN < 0 then
      set res to "ok ungeprueft"
    else if (nachN - vorN) < mindest then
      set res to "leer " & vorN & " " & nachN
    end if
  end if
  return res
end insert_text
'''


def mailbox_ref(name: str) -> str:
    """AppleScript-Referenz auf ein Standardpostfach (sprachunabhängig)."""
    return {"inbox": "inbox", "sent": "sent mailbox"}[name]


# ---------- Text und Prüfsumme ----------


def normalize(s: str) -> str:
    """Leerraum vereinheitlichen und Umlaute in eine Form bringen (Mail liefert teils NFD)."""
    return " ".join(unicodedata.normalize("NFC", s).split())


def fingerprint(text: str, laenge: int = 80) -> dict:
    """Prüfsumme des Textanfangs ohne Klartext. 80 Zeichen erkennen die gesendete Mail wieder, discard prüft mehr
    (TEXT_PRUEFUNG)."""
    head = normalize(text)[:laenge]
    return {"laenge": len(head), "sha256": hashlib.sha256(head.encode("utf-8")).hexdigest()}


def matches_fingerprint(content: str, fp: dict) -> bool:
    head = normalize(content)[: fp["laenge"]]
    return hashlib.sha256(head.encode("utf-8")).hexdigest() == fp["sha256"]


def load_state() -> dict:
    try:
        data = json.loads(DRAFT_STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(state: dict) -> None:
    """Atomar schreiben, damit ein Abbruch nie eine halbe Statusdatei hinterlässt."""
    if not state:
        DRAFT_STATE.unlink(missing_ok=True)
        return
    DRAFT_STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = DRAFT_STATE.with_name(DRAFT_STATE.name + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, DRAFT_STATE)


def kit_entry(state: dict, draft_id: str, subject: str) -> dict | None:
    """Statuseintrag, wenn er zu diesem offenen Entwurf gehört: gleicher Betreff, derselbe Mail-Lauf."""
    entry = state.get(draft_id)
    if not entry or normalize(entry.get("betreff") or "") != normalize(subject or ""):  # Mail liefert teils NFD
        return None
    start = mail_start()
    if entry.get("mail_start") and start and entry["mail_start"] != start:
        return None  # Mail wurde neu gestartet, die ID gehört jetzt zu einem anderen Fenster
    return entry


# ---------- search ----------


def cmd_search(cfg: dict, a: argparse.Namespace) -> None:
    if not (a.sender or a.subject or a.text or a.unread) and a.mailbox != "sent":
        sys.exit("Mindestens ein Filter angeben: --from, --subject, --text oder --unread "
                 "(im Postfach Gesendet reicht der Zeitraum).")
    days = a.days or cfg.get("search", {}).get("default_days", 90)
    limit = a.limit or cfg.get("search", {}).get("default_limit", 50)
    accounts = resolve_accounts(cfg, a.profile)

    clauses = ["date received > cutoff"]
    argv = [str(days), str(max(limit, MAX_TREFFER)), str(len(accounts))] + accounts
    acct_start = 4
    if a.sender:
        argv.append(a.sender)
        clauses.append(f"sender contains (item {len(argv)} of argv)")
    if a.subject:
        argv.append(a.subject)
        clauses.append(f"subject contains (item {len(argv)} of argv)")
    if a.text:
        argv.append(a.text)
        n = len(argv)
        clauses.append(f"(subject contains (item {n} of argv) or sender contains (item {n} of argv))")
    if a.unread:
        clauses.append("read status is false")
    where = " and ".join(clauses)
    line_handler = "line_for_sent" if a.mailbox == "sent" else "line_for"

    # Erst die Postfächer der Konten (schnell, ohne Exchange), sonst das Sammelpostfach mit Kontoprüfung je Treffer.
    # Der erste Datensatz sagt, welcher Weg lief: #weg + konto oder sammel.
    script = AS_COMMON + f'''
on run argv
  set d to (item 1 of argv) as integer
  set lim to (item 2 of argv) as integer
  set nAcct to (item 3 of argv) as integer
  set cutoff to (current date) - d * days
  set acctNames to {{}}
  if nAcct > 0 then set acctNames to items {acct_start} thru ({acct_start - 1} + nAcct) of argv
  set out to ""
  set n to 0
  tell application "Mail"
    with timeout of 80 seconds
      set boxes to my account_boxes("{a.mailbox}", acctNames)
      set fehlt to my missing_accounts(boxes, acctNames)
      if (count boxes) > 0 then
        set out to "#weg" & (character id 31) & "konto" & (character id 30) & fehlt
        repeat with mb in boxes
          set hits to (get messages of (contents of mb) whose {where})
          repeat with m in hits
            set out to out & my {line_handler}(m)
            set n to n + 1
            if n is greater than or equal to lim then exit repeat
          end repeat
          if n is greater than or equal to lim then exit repeat
        end repeat
      else
        set out to "#weg" & (character id 31) & "sammel" & (character id 30) & fehlt
        set hits to (get messages of {mailbox_ref(a.mailbox)} whose {where})
        repeat with m in hits
          if my in_accounts(m, argv, {acct_start}, nAcct) then
            set out to out & my {line_handler}(m)
            set n to n + 1
            if n is greater than or equal to lim then exit repeat
          end if
        end repeat
      end if
    end timeout
  end tell
  return out
end run
'''
    weg, fehlt, recs = steuersaetze(records(run_as(script, *argv)), accounts)
    rows, falsch = gueltige(recs, 5, datum=1)
    postfach = "Gesendet" if a.mailbox == "sent" else "Posteingang"
    gesucht = [k for k in accounts if k not in fehlt]
    luecken = nicht_gefunden(fehlt, "Postfach Gesendet" if a.mailbox == "sent" else "Posteingang")
    if weg == "konto":
        wo = f"{postfach} von {', '.join(gesucht)}"
    else:
        wo = f"{postfach} aller Konten" + (f", nur {', '.join(gesucht)}" if gesucht else "")
        if weg == "sammel" and gesucht:
            print("HINWEIS: Mail liefert die Postfächer der Konten nicht einzeln, gesucht wurde im Sammelpostfach "
                  "(langsamer).", file=sys.stderr)
    if not rows:
        if gesucht:
            print(f"Keine Treffer ({wo}, {days} Tage).")
        else:
            print("Nichts durchsucht: kein Konto aus accounts in Mail gefunden.")
        for zeile in luecken:
            print(zeile)
        if falsch:
            print(uebersprungen(falsch))
        return
    rows.sort(key=lambda r: r[1], reverse=True)  # erst sortieren, dann kürzen: Mail liefert in eigener Reihenfolge
    kopf = ("id | datum | empfänger | betreff | status" if a.mailbox == "sent"
            else "id | datum | absender | betreff | status")
    print(f"{kopf}  ({DATA_NOTE})")
    for r in rows[:limit]:
        print(" | ".join(clean(f) for f in r))
    if len(rows) > limit:
        print(f"[{len(rows) - limit} weitere Treffer, Zeitraum eingrenzen oder --limit erhöhen]")
    for zeile in luecken:
        print(zeile)
    if falsch:
        print(uebersprungen(falsch))


# ---------- finden: Brücke vom Mail-Connector zu Apple Mail ----------

# Ein Connector (Gmail, Microsoft 365) findet Mails schnell, Antworten entstehen aber in Apple Mail. finden sucht die
# Mail aus dem Connector in Apple Mail und liefert die id für draft --reply-to: über die Message-ID (genau) oder über
# Betreff, Absender und Datum (Tag der Mail, ein Tag Spielraum für Zeitzonen).
MESSAGE_ID = re.compile(r"<?([^<>\s@]+@[^<>\s@]+)>?")
FINDEN_TAGE = 365  # Zeitraum ohne --datum
FINDEN_ZEIGEN = 10


def finden_suche(a: argparse.Namespace, heute=None) -> tuple[int, int, list[str], list[str]]:
    """(Tage zurück für den Anfang, Tage zurück für das Ende, Bedingungen, Werte) für das AppleScript. Die Werte stehen
    in argv ab Position start, die Bedingungen nennen sie über ihre Position. Bricht mit Code 2 ab, wenn die Angaben
    nicht reichen oder nicht passen."""
    import datetime as dt
    mid = ""
    if a.message_id:
        m = MESSAGE_ID.fullmatch(a.message_id.strip())
        if not m:
            falscher_aufruf("--message-id sieht nicht wie eine Message-ID aus (etwa <abc123@mail.example.org>).")
        mid = m.group(1)
    if not (mid or a.subject or (a.sender and a.datum)):
        falscher_aufruf("finden braucht --message-id, --subject oder --from zusammen mit --datum.")
    heute = heute or dt.date.today()
    if a.datum:
        try:
            tag = dt.date.fromisoformat(a.datum)
        except ValueError:
            falscher_aufruf(f"--datum als JJJJ-MM-TT, nicht {a.datum}.")
        abstand = (heute - tag).days
        if abstand < -1:
            falscher_aufruf(f"--datum {a.datum} liegt in der Zukunft.")
        von, bis = abstand + 1, abstand - 1  # ein Tag Spielraum je Seite für Zeitzonen
    else:
        von, bis = a.days or FINDEN_TAGE, -1
    bedingungen, werte = [], []
    for wert, klausel in ((mid, "message id is"), (a.subject and a.subject.strip(), "subject contains"),
                          (a.sender and a.sender.strip(), "sender contains")):
        if wert:
            werte.append(wert)
            bedingungen.append((klausel, len(werte) - 1))
    return von, bis, bedingungen, werte


def cmd_finden(cfg: dict, a: argparse.Namespace) -> None:
    von, bis, bedingungen, werte = finden_suche(a)
    accounts = resolve_accounts(cfg, a.profile)
    argv = [str(von), str(bis), str(len(accounts))] + accounts
    start = len(argv) + 1  # Position des ersten Wertes in argv (AppleScript zählt ab 1)
    argv += werte
    where = " and ".join(["date received > cutoff", "date received < bis"]
                         + [f"{k} (item {start + i} of argv)" for k, i in bedingungen])
    line_handler = "line_for_sent" if a.mailbox == "sent" else "line_for"
    script = AS_COMMON + f'''
on run argv
  set cutoff to (current date) - ((item 1 of argv) as integer) * days
  set bis to (current date) - ((item 2 of argv) as integer) * days
  set nAcct to (item 3 of argv) as integer
  set acctNames to {{}}
  if nAcct > 0 then set acctNames to items 4 thru (3 + nAcct) of argv
  set out to ""
  tell application "Mail"
    with timeout of 80 seconds
      set boxes to my account_boxes("{a.mailbox}", acctNames)
      set out to my missing_accounts(boxes, acctNames)
      if (count boxes) > 0 then
        repeat with mb in boxes
          repeat with m in (get messages of (contents of mb) whose {where})
            set out to out & my {line_handler}(m)
          end repeat
        end repeat
      else
        repeat with m in (get messages of {mailbox_ref(a.mailbox)} whose {where})
          if nAcct is 0 or my in_accounts(m, argv, 4, nAcct) then set out to out & my {line_handler}(m)
        end repeat
      end if
    end timeout
  end tell
  return out
end run
'''
    _weg, fehlt, recs = steuersaetze(records(run_as(script, *argv)), accounts)
    rows, falsch = gueltige(recs, 5, datum=1)
    postfach = "Gesendet" if a.mailbox == "sent" else "Posteingang"
    luecken = nicht_gefunden(fehlt, "Postfach Gesendet" if a.mailbox == "sent" else "Posteingang")
    if not rows:
        if len(fehlt) == len(accounts):
            print("Nichts durchsucht: kein Konto aus accounts in Mail gefunden.")
        else:
            print(f"Keine passende Mail in Apple Mail ({postfach}). Angaben aus dem Connector prüfen oder mit search "
                  f"weitersuchen, etwa über den Absender.")
        for zeile in luecken:
            print(zeile)
        if falsch:
            print(uebersprungen(falsch))
        return
    rows.sort(key=lambda r: r[1], reverse=True)
    kopf = "id | datum | empfänger | betreff | status" if a.mailbox == "sent" else "id | datum | absender | betreff | status"
    print(f"{kopf}  ({DATA_NOTE})")
    for r in rows[:FINDEN_ZEIGEN]:
        print(" | ".join(clean(f) for f in r))
    if len(rows) == 1:
        print(f"Eindeutig: id {rows[0][0]}, für die Antwort draft --reply-to {rows[0][0]}.")
    else:
        print(f"{len(rows)} Treffer, nicht eindeutig: mit --from oder --datum eingrenzen oder die id nach Absender und "
              f"Datum wählen.")
    for zeile in luecken:
        print(zeile)
    if falsch:
        print(uebersprungen(falsch))


# ---------- triage ----------

# Ein Datensatz je Mail: id, Datum, Absender, Betreff, Status, die Herkunft (n neu im Zeitraum, m nur markiert, für
# die Obergrenze) und das Konto (ohne Konto ließe sich Privat und Arbeit nicht trennen). Markierte Mails:
# gelesene aller Zeit im Jahr und ungelesene, die älter als der Zeitraum sind (die neueren stehen schon unter n).
# Gesucht wird in den Posteingängen der Konten (Konto einmal je Postfach), sonst im Sammel-Posteingang mit Kontoprüfung
# und Konto je Mail wie bei search.
AS_TRIAGE = AS_COMMON + '''
on triage_line(m, statusTxt, src, kontoTxt)
  tell application "Mail"
    if flagged status of m then set statusTxt to statusTxt & ", markiert"
    if kontoTxt is "" then set kontoTxt to (name of account of mailbox of m)
    return (id of m as string) & "@F@" & my iso(date received of m) & "@F@" & my no_sep(sender of m) & "@F@" & my no_sep(subject of m) & "@F@" & statusTxt & "@F@" & src & "@F@" & my no_sep(kontoTxt) & "@R@"
  end tell
end triage_line
on run argv
  set h to (item 1 of argv) as integer
  set nAcct to (item 2 of argv) as integer
  set acctNames to {}
  if nAcct > 0 then set acctNames to items 3 thru (2 + nAcct) of argv
  set cutoff to (current date) - h * hours
  set flagCutoff to (current date) - 365 * days
  set out to ""
  tell application "Mail"
    with timeout of 80 seconds
      set boxes to my account_boxes("inbox", acctNames)
      set out to my missing_accounts(boxes, acctNames)
      set perAcct to (count boxes) > 0
      if not perAcct then set boxes to {inbox}
      repeat with mb in boxes
        set kontoName to ""
        if perAcct then set kontoName to (name of account of (contents of mb))
        set unreadMsgs to (get messages of (contents of mb) whose read status is false and date received > cutoff)
        set flaggedMsgs to (get messages of (contents of mb) whose flagged status is true and date received > flagCutoff)
        repeat with m in unreadMsgs
          if perAcct or my in_accounts(m, argv, 3, nAcct) then set out to out & my triage_line(m, "ungelesen", "n", kontoName)
        end repeat
        repeat with m in flaggedMsgs
          set isRead to read status of m
          if isRead or (date received of m) < cutoff then
            if perAcct or my in_accounts(m, argv, 3, nAcct) then
              if isRead then
                set out to out & my triage_line(m, "gelesen", "m", kontoName)
              else
                set out to out & my triage_line(m, "ungelesen", "m", kontoName)
              end if
            end if
          end if
        end repeat
      end repeat
    end timeout
  end tell
  return out
end run
'''.replace("@F@", FSEP).replace("@R@", RSEP)


def cmd_triage(cfg: dict, a: argparse.Namespace) -> None:
    """Was ist neu in den Konten aus accounts (oder nur im Konto von a.profil): ungelesene Mails der letzten a.stunden
    Stunden und von den nur markierten Mails des letzten Jahres je Konto höchstens triage.max_markiert (die neuesten),
    nach Konto in der Reihenfolge von accounts, darin neueste zuerst. Ein Konto ohne Treffer bekommt die Zeile nichts
    Neues, damit Claude Privat und Arbeit getrennt nennen kann. Ein Konto, das Mail nicht liefert, bekommt
    stattdessen die Zeile nicht gefunden, nicht durchsucht (nicht_gefunden). Newsletter (noise: Teilstring im
    Absender, Groß- und Kleinschreibung egal) fallen weg. Kein Volltext, nichts wird verändert."""
    konten = resolve_accounts(cfg, a.profil)  # vor Mail: leere Konten oder das Arbeitskonto brechen hier ab
    grenze = cfg.get("triage", {}).get("max_markiert", TRIAGE_MARKIERT)
    noise = [n.casefold() for n in cfg.get("noise", []) if n]
    _weg, fehlt, recs = steuersaetze(records(run_as(AS_TRIAGE, str(a.stunden), str(len(konten)), *konten)), konten)
    gut, falsch = gueltige(recs, 7, datum=1)
    rows = [r for r in gut if r[5] in ("n", "m") and r[6].strip()]
    falsch += len(gut) - len(rows)
    rows = [r for r in rows if not any(n in r[2].casefold() for n in noise)]
    gesucht = [k for k in konten if k not in fehlt]
    if not rows:
        if gesucht:
            print(f"Nichts Neues in {', '.join(clean(k) for k in gesucht)}: keine ungelesenen oder markierten Mails im "
                  "Zeitraum.")
        else:
            print("Nichts durchsucht: kein Konto aus accounts in Mail gefunden.")
        for zeile in nicht_gefunden(fehlt, "Posteingang"):
            print(zeile)
        if falsch:
            print(uebersprungen(falsch))
        return
    rows.sort(key=lambda r: r[1], reverse=True)
    reihe = konten + sorted({r[6] for r in rows} - set(konten))
    ausgelassen = 0
    print(f"id | datum | absender | betreff | status  ({DATA_NOTE})")
    for konto in reihe:
        eigene = [r for r in rows if r[6] == konto]
        if not eigene and konto in fehlt:
            print(nicht_gefunden([konto], "Posteingang")[0])
            continue
        if not eigene:
            print(f"Konto {clean(konto)}: nichts Neues")
            continue
        markiert = [r for r in eigene if r[5] == "m"]
        behalten = {id(r) for r in markiert[:grenze]}
        ausgelassen += max(0, len(markiert) - grenze)
        print(f"Konto {clean(konto)}:")
        for r in eigene:
            if r[5] == "n" or id(r) in behalten:
                print(" | ".join(clean(f) for f in r[:5]))
    if ausgelassen:
        print(f"[{ausgelassen} ältere markierte Mails ausgelassen, Grenze {grenze} je Konto in config.json unter "
              "triage.max_markiert]")
    if falsch:
        print(uebersprungen(falsch))


# ---------- read ----------


def fetch_message(cfg: dict, msg_id: int, mailbox: str, profile: str | None = None,
                  source: bool = False, timeout: int = 90) -> dict:
    """Mail lesen. source=True liefert statt des Textes den Rohquelltext (MIME). timeout begrenzt die Wartezeit auf Mail
    (read mit mehreren IDs gibt nur die Restzeit)."""
    accounts = resolve_accounts(cfg, profile)
    argv0 = [str(msg_id), str(len(accounts))] + accounts
    part = "source" if source else "content"
    script = AS_COMMON + f'''
on run argv
  set mid to (item 1 of argv) as integer
  set nAcct to (item 2 of argv) as integer
  tell application "Mail"
    with timeout of 60 seconds
      set m to (first message of {mailbox_ref(mailbox)} whose id is mid)
      if not my in_accounts(m, argv, 3, nAcct) then error "Mail gehört nicht zu den erlaubten Konten"
      set c to {part} of m
      set att to ""
      repeat with x in mail attachments of m
        if att is not "" then set att to att & ", "
        set att to att & (name of x)
      end repeat
      return my no_sep(subject of m) & "@F@" & my no_sep(sender of m) & "@F@" & my no_sep(name of account of mailbox of m) & "@F@" & my addr_list(to recipients of m) & "@F@" & my addr_list(cc recipients of m) & "@F@" & my addr_list(bcc recipients of m) & "@F@" & my no_sep(att) & "@F@" & my iso(date received of m) & "@R@" & c
    end timeout
  end tell
end run
'''.replace("@F@", FSEP).replace("@R@", RSEP)
    out = run_as(script, *argv0, timeout=timeout)
    head, _, body = out.partition(RSEP)
    parts = head.split(FSEP)
    # Kopf genau wie erwartet, sonst stimmen Absender oder Betreff womöglich nicht (Review 21.10.2026)
    if len(parts) != 8 or not ISO_ZEIT.fullmatch(parts[7]):
        sys.exit(f"Mail lieferte den Kopf von Mail {msg_id} in unerwartetem Format. Nichts ausgegeben.")
    return {
        "subject": parts[0],
        "sender": parts[1],
        "account": parts[2],
        "to": parts[3],
        "cc": parts[4],
        "bcc": parts[5],
        "attachments": parts[6],
        "date": parts[7],
        "body": body,
    }


def html_part(source: str) -> str:
    """HTML-Teil aus dem Rohquelltext einer Mail, dekodiert. Leer, wenn es keinen gibt."""
    msg = email.message_from_string(source, policy=email.policy.default)
    part = msg.get_body(preferencelist=("html",))
    if not part:
        return ""
    try:
        return part.get_content()
    except (LookupError, ValueError) as e:  # unbekannter Zeichensatz oder kaputte Kodierung
        sys.exit(f"HTML-Teil nicht lesbar ({type(e).__name__}: {e}). Ohne --html lesen.")


READ_MAX_IDS = 10
READ_GRENZE = 12000  # Zeichen für alle Texte zusammen, wenn read mehrere IDs bekommt und --max-chars fehlt
# Sekunden für read mit mehreren IDs zusammen: Jede Mail bekommt nur die Restzeit als Zeitlimit, so bleibt der ganze
# Aufruf klar unter 120 s. Unter READ_REST Sekunden
# Restzeit liest read keine weitere Mail.
READ_ZEIT = 60
READ_REST = 5


def verteile(laengen: list[int], grenze: int) -> list[int]:
    """Zeichen je Text bei gemeinsamer Grenze: Kurze Texte bleiben ganz, der Rest geht gleichmäßig an die langen."""
    anteile = [0] * len(laengen)
    reihe = sorted(range(len(laengen)), key=lambda i: laengen[i])
    rest = grenze
    for n, i in enumerate(reihe):
        anteile[i] = min(laengen[i], rest // (len(reihe) - n))
        rest -= anteile[i]
    return anteile


def print_kopf(m: dict) -> None:
    print(f"Betreff: {clean(m['subject'])}")
    print(f"Von:     {clean(m['sender'])}")
    print(f"An:      {clean(m['to'])}")
    if m["cc"]:
        print(f"Cc:      {clean(m['cc'])}")
    if m.get("bcc"):
        print(f"Bcc:     {clean(m['bcc'])}")
    if m["attachments"]:
        print(f"Anhänge: {clean(m['attachments'])}")
    print(f"Datum:   {m['date']}")


def cmd_read(cfg: dict, a: argparse.Namespace) -> None:
    ids = list(dict.fromkeys(a.id if isinstance(a.id, list) else [a.id]))
    if len(ids) == 1:
        read_one(cfg, a, ids[0])
    else:
        read_many(cfg, a, ids)


def read_many(cfg: dict, a: argparse.Namespace, ids: list) -> None:
    """Mehrere Mails in einem Aufruf. Je Mail ein
    Kopf, eine gemeinsame Zeichengrenze. Eine nicht lesbare Mail ist eine Zeile, die anderen kommen trotzdem. Antwortet
    Mail nicht, liest read keine weitere: Jede wartete sonst bis zur Zeitgrenze."""
    if len(ids) > READ_MAX_IDS:
        falscher_aufruf(f"read nimmt höchstens {READ_MAX_IDS} IDs, hier {len(ids)}. In Gruppen lesen.")
    if a.html:
        falscher_aufruf("--html nur mit einer ID.")
    resolve_accounts(cfg, a.profile)  # Konto vorab: ein falsches Profil bricht vor Mail ab, nicht je ID
    grenze = a.max_chars or READ_GRENZE
    ende = time.monotonic() + READ_ZEIT
    gelesen, fehler = {}, {}
    for msg_id in ids:
        rest = int(ende - time.monotonic())
        if rest < READ_REST or any(GRUND_KEINE_ANTWORT in g for g in fehler.values()):
            fehler[msg_id] = GRUND_KEINE_ANTWORT
            continue
        try:
            gelesen[msg_id] = fetch_message(cfg, msg_id, a.mailbox, a.profile, timeout=rest)
        except SystemExit as e:
            text = str(e.code)
            fehler[msg_id] = GRUND_KEINE_ANTWORT if "nicht geantwortet" in text else "nicht lesbar: " + text
    if not gelesen:
        sys.exit(f"Keine der {len(ids)} Mails lesbar. Erste Meldung: {fehler[ids[0]]}")
    texte = {i: kit_basis.ohne_formatzeichen(m["body"]) for i, m in gelesen.items()}
    anteile = dict(zip(texte, verteile([len(t) for t in texte.values()], grenze)))
    print(f"{len(ids)} Mails, zusammen höchstens {grenze} Zeichen ({DATA_NOTE})")
    for msg_id in ids:
        print(f"\n## Mail {msg_id}")
        if msg_id in fehler:
            print(fehler[msg_id])
            continue
        print_kopf(gelesen[msg_id])
        print()
        body = texte[msg_id]
        if len(body) > anteile[msg_id]:
            body = (body[: anteile[msg_id]]
                    + f"\n[gekürzt, {len(body)} Zeichen gesamt, mehr mit --max-chars oder einzeln lesen]")
        print(body)


GRUND_KEINE_ANTWORT = "nicht gelesen: Mail antwortet nicht, später einzeln lesen."


def read_one(cfg: dict, a: argparse.Namespace, msg_id) -> None:
    m = fetch_message(cfg, msg_id, a.mailbox, a.profile, source=a.html)
    print_kopf(m)
    print(f"({DATA_NOTE})")
    print()
    body = html_part(m["body"]) if a.html else m["body"]
    if a.html and not body:
        sys.exit("Die Mail hat keinen HTML-Teil.")
    # Terminalsteuerfolgen, Steuer-, Richtungs- und Formatzeichen raus, damit eine fremde Mail im Transkript nichts
    # färben oder verstecken kann (Prüfung 20.10.2026, auch Nullbreiten), Tab und Umbruch bleiben
    body = kit_basis.ohne_formatzeichen(body)
    if a.max_chars and len(body) > a.max_chars:
        body = body[: a.max_chars] + f"\n[gekürzt, {len(body)} Zeichen gesamt, mehr mit --max-chars]"
    print(body)


# ---------- draft ----------


def read_text(a: argparse.Namespace) -> str:
    """Text nur aus entwurf.txt oder antwort.txt im Kit (kit_basis: auch ohne cd, kein Verweis, kein harter Verweis).
    Andere Dateien und ein Argumenttext liest das Kit nie: draft läuft ohne Rückfrage außerhalb der Sandbox, deren
    Lesesperren sonst nicht gälten, und ein Text im Argument umginge die Regel der festen Datei (Prüfung 20.10.2026,
    vorher --text)."""
    if not a.text_file:
        sys.exit("Text fehlt: --text-file entwurf.txt oder --text-file antwort.txt angeben (Datei im Kit-Ordner).")
    text = kit_basis.lies_text(kit_basis.textdatei(a.text_file, kit_basis.datenordner(KIT_DIR), TEXT_NAMEN))
    if not text.strip():
        sys.exit("Der Text ist leer.")
    return text


def check_attachments(cfg: dict, paths: list[str]) -> list[str]:
    """Absolute Pfade der Anhänge. Erlaubt sind nur Dateien in config.json 'anhang_ordner'. Das hält Dateien unter
    ~/Library und aus dem Ordner mit Firmenunterlagen fern. Eine Firmendatei in einem erlaubten Ordner
    erkennt die Prüfung aber nicht, etwa eine Folie im Office-Ordner. Dort schützen nur die Rückfrage bei --attach und
    die Regel für Claude: Firmenunterlagen nie anhängen."""
    erlaubt = [Path(os.path.expanduser(d)).resolve() for d in cfg.get("anhang_ordner", [])]
    ergebnis = []
    for p in paths:
        datei = Path(os.path.expanduser(p)).resolve()
        if not datei.is_file():
            sys.exit(f"Anhang nicht gefunden: {p}")
        if not any(o == datei.parent or o in datei.parents for o in erlaubt):
            sys.exit(f"Anhang nur aus diesen Ordnern: {', '.join(str(o) for o in erlaubt) or '(keine, anhang_ordner leer)'}."
                     f" Nicht aus {datei.parent}.")
        ergebnis.append(str(datei))
    return ergebnis


def remove_text_file(a: argparse.Namespace) -> None:
    """entwurf.txt oder antwort.txt im Kit nach einem erfolgreichen Entwurf löschen. Andere Dateien bleiben."""
    if not a.text_file:
        return
    try:
        pfad = kit_basis.textdatei(a.text_file, kit_basis.datenordner(KIT_DIR), TEXT_NAMEN)
    except SystemExit:  # keine der festen Dateien im Kit: nichts löschen
        return
    pfad.unlink(missing_ok=True)


def build_body(text: str) -> str:
    """Inhalt einer neuen Mail. Die Signatur hängt Mail selbst an.

    Mail setzt vor die eigene Signatur schon einen Zeilenumbruch. Ein Umbruch am
    Textende ergibt so genau einen leeren Absatz zwischen Text und Signatur.
    """
    return text.rstrip() + "\n"


def adresse(text: str) -> str:
    """Mailadresse aus 'Name <a@b.de>' oder 'a@b.de', klein geschrieben, für den Vergleich des Absenders."""
    return email.utils.parseaddr(text or "")[1].casefold()


def cmd_draft(cfg: dict, a: argparse.Namespace) -> None:
    text = read_text(a)
    if a.reply_to:
        draft_reply(cfg, a, text)
        return
    if a.all:
        sys.exit("--all gibt es nur zusammen mit --reply-to.")
    if getattr(a, "betreff_erwartet", None) is not None:
        falscher_aufruf("--betreff-erwartet gibt es nur zusammen mit --reply-to.")

    profile_name = a.profile or cfg.get("default_profile")
    if not profile_name:
        sys.exit("Kein Profil: --profile angeben oder default_profile in config.json setzen.")
    prof = mail_profil(cfg, profile_name)  # nur Konten aus accounts, nie das Arbeitskonto
    absender = prof.get("from_address", "")
    # Ohne Absender wählte Mail das Konto selbst, und die Prüfung nach dem Anlegen entfiele still (Review 21.10.2026)
    if not absender.strip():
        sys.exit(f"Profil {profile_name} hat kein from_address in config.json. Ohne Absender legt draft keine neue "
                 "Mail an.")
    to = list(a.to or [])
    subject = a.subject
    if not to:
        sys.exit("Empfänger fehlt: --to ADRESSE")
    if not subject:
        sys.exit("Betreff fehlt: --subject TEXT")
    anhaenge = check_attachments(cfg, a.attach or [])

    body = build_body(text)
    name = prof.get("from_name", "")
    sender = f"{name} <{absender}>" if name else absender

    tmp = write_temp(body)
    # argv: 1 Textdatei, 2 Betreff, 3 Absender, 4 Anzahl To, 5 Anzahl Cc, 6 Anzahl Anhänge, dann die Listen
    argv = [tmp, subject, sender, str(len(to)), str(len(a.cc or [])), str(len(anhaenge))]
    argv += to + list(a.cc or []) + anhaenge

    # Zurück kommen id, Länge des Inhalts, Absender und die Empfänger (An, Cc, Bcc), wie Mail sie jetzt hat
    script = AS_REIN + '''
on run argv
  set p to item 1 of argv
  set subj to item 2 of argv
  set snd to item 3 of argv
  set nTo to (item 4 of argv) as integer
  set nCc to (item 5 of argv) as integer
  set nAt to (item 6 of argv) as integer
  set txt to read POSIX file p as «class utf8»
  set i to 7
  tell application "Mail"
    set d to make new outgoing message with properties {subject:subj, content:txt, sender:snd, visible:true}
    repeat nTo times
      tell d to make new to recipient at end of to recipients with properties {address:(item i of argv)}
      set i to i + 1
    end repeat
    repeat nCc times
      tell d to make new cc recipient at end of cc recipients with properties {address:(item i of argv)}
      set i to i + 1
    end repeat
    repeat nAt times
      tell d to make new attachment with properties {file name:(POSIX file (item i of argv))} at after the last paragraph
      set i to i + 1
    end repeat
    set c to content of d
    set gotSnd to ""
    try
      set gotSnd to (sender of d) as string
    end try
    return (id of d as string) & "@F@" & (length of c as string) & "@F@" & my no_sep(gotSnd) & "@F@" & my addr_list(to recipients of d) & "@F@" & my addr_list(cc recipients of d) & "@F@" & my addr_list(bcc recipients of d)
  end tell
end run
'''.replace("@F@", FSEP)
    try:
        out = run_as(script, *argv)
    finally:
        os.unlink(tmp)
    draft_id, got_len, got_sender, an, cc, bcc = (out.split(FSEP) + [""] * 5)[:6]
    state = load_state()
    state[draft_id] = {"art": "neu", "betreff": subject, "erstellt": time.time(), "eingefuegt": True,
                       "kennung": fingerprint(text), "kennung_text": fingerprint(text, TEXT_PRUEFUNG),
                       "mail_start": mail_start(), "profil": profile_name, "absender": absender}
    save_state(state)
    got = int(got_len) if NUR_ZIFFERN.fullmatch(got_len) else 0
    print(f"Entwurf {draft_id} angelegt (Profil: {profile_name}, Absender: {sender}): {empfaenger(an, cc, bcc)} | "
          f"Betreff: {subject}")
    print(f"Inhalt: {got} Zeichen (erwartet ungefähr {len(body)})")
    if got == 0:
        print("WARNUNG: Der Entwurf ist leer. Verwerfen (discard) und neu anlegen.", file=sys.stderr)
        sys.exit(EXIT_EMPTY)
    if adresse(got_sender) != adresse(absender):
        print(f"WARNUNG: Mail hat den Absender nicht übernommen, im Entwurf steht {clean(got_sender) or 'keiner'} statt "
              f"{absender}. In Mail bei Von das Konto wählen, bis dahin verweigert send. Sonst from_address in "
              "config.json mit der Adresse des Kontos in Mail abgleichen.", file=sys.stderr)
        sys.exit(EXIT_ABSENDER)
    if got < len(body) * 0.8:
        print("WARNUNG: Der Inhalt ist deutlich kürzer als erwartet. Bitte in Mail prüfen.", file=sys.stderr)
        return
    remove_text_file(a)


def message_account(cfg: dict, msg_id: int, mailbox: str, profile: str | None) -> str:
    """Kontoname der Mail, auf die geantwortet wird. Prüft dabei die erlaubten Konten."""
    accounts = resolve_accounts(cfg, profile)
    script = AS_COMMON + '''
on run argv
  set mid to (item 1 of argv) as integer
  set nAcct to (item 2 of argv) as integer
  tell application "Mail"
    with timeout of 60 seconds
      set m to (first message of @MAILBOX@ whose id is mid)
      if not my in_accounts(m, argv, 3, nAcct) then error "Mail gehört nicht zu den erlaubten Konten"
      return name of account of mailbox of m
    end timeout
  end tell
end run
'''.replace("@MAILBOX@", mailbox_ref(mailbox))
    return run_as(script, str(msg_id), str(len(accounts)), *accounts)


INSERT_PROBLEMS = {
    "fenster": "Das Antwortfenster kam nicht nach vorne.",
    "freigabe": ("Keine Bedienungshilfen-Freigabe. Dauerhaft lösen: der App, die das Kit startet, "
                 "unter Systemeinstellungen > Datenschutz & Sicherheit > Bedienungshilfen den Zugriff erlauben."),
    "fokus": "Die Schreibmarke stand nicht im Nachrichtentext.",
    "fehler": "Einfügen fehlgeschlagen.",
    "leer": "Nach dem Einfügen kamen im Nachrichtentext zu wenige Zeichen an (Zahl vorher und nachher).",
}


# Präfixe vor dem Betreff einer Antwort oder Weiterleitung, auch gestapelt und mit Zähler (Re[2]:). Gilt gleich in
# Python (betreff_kern, für Tests und Meldungen) und im AppleScript (same_subject über NSRegularExpression, ICU).
BETREFF_PRAEFIX = r"(?i)^(?:\s*(?:re|aw|wg|fwd?|antw)\s*(?:\[\d+\])?\s*:)+"


def betreff_kern(betreff: str) -> str:
    """Betreff ohne Re:, AW:, WG:, Fwd: vorn, Leerraum vereinheitlicht, Groß und Klein egal, Umlaute in einer Form."""
    kern = re.sub(BETREFF_PRAEFIX, "", unicodedata.normalize("NFC", betreff or ""))
    return " ".join(kern.split()).lower()


# Vergleich des Betreffs vor reply, Logik wie betreff_kern. Braucht AS_USE_OBJC.
AS_BETREFF = '''
on subj_core(s)
  set ns to current application's NSString's stringWithString:(s as string)
  set ns to ns's precomposedStringWithCanonicalMapping()
  set ns to ns's stringByReplacingOccurrencesOfString:"@PRAEFIX@" withString:"" options:(current application's NSRegularExpressionSearch) range:{0, ns's |length|()}
  set ns to ns's stringByReplacingOccurrencesOfString:"\\\\s+" withString:" " options:(current application's NSRegularExpressionSearch) range:{0, ns's |length|()}
  set ns to ns's stringByTrimmingCharactersInSet:(current application's NSCharacterSet's whitespaceAndNewlineCharacterSet())
  return ns's lowercaseString()
end subj_core
on same_subject(ist, erwartet)
  return ((my subj_core(ist))'s isEqualToString:(my subj_core(erwartet))) as boolean
end same_subject
'''.replace("@PRAEFIX@", BETREFF_PRAEFIX.replace("\\", "\\\\"))


def mindest_zeichen(body: str) -> int:
    """So viele Zeichen muss der Nachrichtentext nach dem Einfügen mindestens mehr haben. Die Hälfte des Textes ohne
    Leerraum, weil Mail Umbrüche und Umlaute beim Einsetzen anders zählen kann."""
    return max(1, len("".join(body.split())) // 2)


def draft_reply(cfg: dict, a: argparse.Namespace, text: str) -> None:
    """Echte Antwort in Mail öffnen und den Text über der Signatur einfügen."""
    if a.to or a.subject or a.attach:
        sys.exit("Bei --reply-to setzt Mail Empfänger und Betreff selbst. "
                 "--to, --subject und --attach weglassen, Anhänge im Fenster ergänzen.")
    erwartet = (getattr(a, "betreff_erwartet", None) or "").strip()
    if getattr(a, "betreff_erwartet", None) is not None and not betreff_kern(erwartet):
        falscher_aufruf("--betreff-erwartet ist leer. Den Betreff der Mail angeben, auf die geantwortet wird.")
    # Profil und Signatur hängen am Konto der Mail, nicht am Standardprofil.
    # Nur Posteingang: auf eigene gesendete Mails adressiert Mail die Antwort an einen selbst.
    account = message_account(cfg, a.reply_to, "inbox", a.profile)
    profile_name, _prof = profile_for_account(cfg, account)
    body = text.rstrip()
    accounts = resolve_accounts(cfg, a.profile)

    tmp = write_temp(body + "\n")  # der Zeilenumbruch lässt einen leeren Absatz vor der Signatur
    cc = list(a.cc or [])
    # argv: 1 Mail-ID, 2 Textdatei, 3 Allen antworten, 4 Anzahl Cc, 5 Anzahl Konten, 6 Mindestzahl neuer Zeichen,
    # 7 erwarteter Betreff (leer: keine Prüfung), dann Cc und Konten
    argv = [str(a.reply_to), tmp, "yes" if a.all else "no", str(len(cc)), str(len(accounts)), str(mindest_zeichen(body)),
            erwartet]
    argv += cc + accounts

    # Mit erwartetem Betreff prüft das Skript ihn vor reply: Passt er nicht, öffnet sich kein Fenster, zurück kommt
    # #betreff und der Betreff der Mail.
    script = AS_USE_OBJC + AS_COMMON + AS_CLIPBOARD + AS_INSERT + AS_BETREFF + '''
on run argv
  set mid to (item 1 of argv) as integer
  set txt to read ((item 2 of argv) as POSIX file) as «class utf8»
  set toAll to (item 3 of argv) is "yes"
  set nCc to (item 4 of argv) as integer
  set nAcct to (item 5 of argv) as integer
  set mindest to (item 6 of argv) as integer
  set erwartet to item 7 of argv
  tell application "Mail"
    with timeout of 60 seconds
      set m to (first message of @MAILBOX@ whose id is mid)
      if not my in_accounts(m, argv, 8 + nCc, nAcct) then error "Mail gehört nicht zu den erlaubten Konten"
      if erwartet is not "" then
        set ist to ""
        try
          set ist to (subject of m) as string
        end try
        if not my same_subject(ist, erwartet) then return "#betreff@F@" & my no_sep(ist)
      end if
      if toAll then
        set d to reply m with opening window and reply to all
      else
        set d to reply m with opening window
      end if
      repeat with i from 8 to (7 + nCc)
        tell d to make new cc recipient at end of cc recipients with properties {address:(item i of argv)}
      end repeat
      set did to id of d
      set subj to subject of d
      set toList to my addr_list(to recipients of d)
      set ccList to my addr_list(cc recipients of d)
      set bccList to my addr_list(bcc recipients of d)
    end timeout
  end tell
  set res to my insert_text(txt, subj, mindest)
  return (did as string) & "@F@" & my no_sep(subj) & "@F@" & toList & "@F@" & ccList & "@F@" & bccList & "@F@" & res
end run
'''.replace("@MAILBOX@", mailbox_ref("inbox")).replace("@F@", FSEP)
    try:
        out = run_as(script, *argv)
    finally:
        os.unlink(tmp)
    if out.startswith("#betreff" + FSEP):
        ist = out.split(FSEP, 1)[1]
        sys.exit(f"Abgebrochen, nichts geöffnet: Mail {a.reply_to} hat den Betreff {clean(ist) or '(leer)'}, erwartet "
                 f"war {clean(erwartet)}. Die id mit mail_suchen oder mail_neues neu holen.")
    # Empfänger setzt Mail bei einer Antwort selbst, mit --all auch Cc: Sie gehören in die Ausgabe (Review 21.10.2026)
    draft_id, subj, an, cc_ist, bcc, res = (out.split(FSEP, 5) + [""] * 5)[:6]
    kind, _, detail = res.partition(" ")
    inserted = kind == "ok"
    state = load_state()
    state[draft_id] = {"art": "antwort", "betreff": subj, "erstellt": time.time(), "eingefuegt": inserted,
                       "kennung": fingerprint(body), "mail_start": mail_start(), "profil": profile_name or account}
    save_state(state)

    print(f"Antwort-Entwurf {draft_id} geöffnet (Profil: {profile_name or account}): {empfaenger(an, cc_ist, bcc)} | "
          f"Betreff: {clean(subj)}")
    if inserted:
        if detail:  # ok ungeprueft
            print("Text eingefügt, die Zeichenzahl im Fenster ließ sich nicht nachzählen. Bitte im Fenster prüfen.")
        else:
            print("Text eingefügt und im Fenster nachgezählt. Den Inhalt einer Antwort kann das Skript nicht lesen, "
                  "bitte im Fenster prüfen.")
        remove_text_file(a)
        return
    reason = INSERT_PROBLEMS.get(kind, "Unbekannter Fehler.")
    print(f"WARNUNG: Text nicht eingefügt. {reason}" + (f" ({detail})" if detail else ""), file=sys.stderr)
    print(f"Das Antwortfenster ist offen, die Zwischenablage unverändert. Fehlt der Text im Fenster, ihn selbst "
          f"einfügen und in Mail senden, oder mit discard {draft_id} verwerfen.", file=sys.stderr)
    sys.exit(EXIT_NOT_INSERTED)


# ---------- drafts / send / discard ----------

# Ein Datensatz je offenem Entwurf, Felder wie in Entwurf: id, Betreff, An, Cc, Bcc, Absender, Länge, Textanfang (für
# die Prüfsumme)
AS_DRAFT_LINE = AS_REIN + '''
on draft_line(d)
  tell application "Mail"
    set c to content of d as string
    set head to c
    if (count c) > 400 then set head to text 1 thru 400 of c
    return (id of d as string) & "@F@" & my no_sep(subject of d) & "@F@" & my addr_list(to recipients of d) & "@F@" & my addr_list(cc recipients of d) & "@F@" & my addr_list(bcc recipients of d) & "@F@" & my no_sep(sender of d) & "@F@" & (length of c as string) & "@F@" & my no_sep(head) & "@R@"
  end tell
end draft_line
'''.replace("@F@", FSEP).replace("@R@", RSEP)


class Entwurf(NamedTuple):
    """Ein offener Entwurf, wie draft_line ihn liefert."""
    id: str
    betreff: str
    an: str
    cc: str
    bcc: str
    von: str
    laenge: str
    anfang: str


def entwuerfe(out: str) -> tuple[list[Entwurf], int]:
    """Entwürfe aus der Ausgabe von draft_line, nur vollständige Datensätze, dazu die Zahl der übrigen."""
    gut, falsch = gueltige(records(out), len(Entwurf._fields))
    return [Entwurf(*r) for r in gut], falsch


def reply_note(entry: dict | None) -> str:
    if not entry or entry.get("art") != "antwort":
        return ""
    if entry.get("eingefuegt"):
        return " (Antwort, Text eingefügt, Inhalt nicht lesbar)"
    return " (Antwort, Text NICHT eingefügt)"


def draft_info(r: Entwurf) -> str:
    """Anzeige eines Entwurfs: id | Betreff | an, Cc, Bcc | von | Länge."""
    return " | ".join([r.id, clean(r.betreff), empfaenger(r.an, r.cc, r.bcc), clean(r.von), f"{r.laenge} Zeichen"])


def cmd_drafts(cfg: dict, a: argparse.Namespace) -> None:
    script = AS_DRAFT_LINE + '''
on run argv
  set out to ""
  tell application "Mail"
    repeat with d in (get outgoing messages)
      set out to out & my draft_line(d)
    end repeat
  end tell
  return out
end run
'''
    rows, falsch = entwuerfe(run_as(script))
    state = load_state()
    # nur Einträge behalten, deren Entwurf noch offen ist, denselben Betreff hat und aus diesem Mail-Lauf stammt
    fresh = {r.id: state[r.id] for r in rows if kit_entry(state, r.id, r.betreff)}
    if fresh != state:
        save_state(fresh)
    if not rows:
        print("Keine offenen Entwürfe. (Nur offene Entwurfsfenster werden gelistet, nicht das Postfach Entwürfe.)")
    else:
        print("id | betreff | empfänger | von | inhalt")
        for r in rows:
            print(draft_info(r) + reply_note(fresh.get(r.id)) + ("" if r.id in fresh else " (nicht vom Kit)"))
    if falsch:
        print(uebersprungen(falsch))


def inspect_draft(draft_id: int) -> Entwurf:
    """Felder eines offenen Entwurfs wie in draft_line, sonst Abbruch mit Meldung."""
    script = AS_DRAFT_LINE + '''
on run argv
  set did to (item 1 of argv) as integer
  tell application "Mail"
    try
      set d to (first outgoing message whose id is did)
    on error
      return ""
    end try
    return my draft_line(d)
  end tell
end run
'''
    out = run_as(script, str(draft_id), timeout=SEND_SCHRITT,
                 zeitablauf=f"Mail hat nach {SEND_SCHRITT} s nicht geantwortet. Nichts geändert, später erneut versuchen.")
    rows, _falsch = entwuerfe(out)
    if not rows:
        sys.exit(f'Kein offener Entwurf {draft_id}. Offene Entwürfe zeigt: python3 "{KIT_DIR / "mail.py"}" drafts')
    return rows[0]


SENT_SEP = "\n<<<communication-kit>>>\n"


def find_sent(subject: str, fp: dict, ende: float, wait: int = 30, window: int = 600) -> str:
    """Gesendete Mail der letzten window Sekunden im Postfach Gesendet suchen, wait Sekunden lang und nie über ende
    (time.monotonic) hinaus, damit send unter den 120 s des Bash-Werkzeugs bleibt.

    Im selben Verlauf haben mehrere Antworten denselben Betreff, darum zählt jede
    Mail im Zeitfenster. Ergebnis: gefunden, abweichend (Textanfang anders), fehlt oder
    offen (Mail hat nicht rechtzeitig geantwortet).
    """
    script = '''
on run argv
  set subj to item 1 of argv
  set cutoff to (current date) - ((item 2 of argv) as integer)
  set sep to item 3 of argv
  set out to ""
  tell application "Mail"
    with timeout of 60 seconds
      set hits to (get messages of sent mailbox whose subject is subj and date received > cutoff)
      repeat with m in hits
        set out to out & sep & (content of m)
      end repeat
    end timeout
  end tell
  return out
end run
'''
    deadline = min(time.monotonic() + wait, ende)
    ergebnis = "offen"
    while True:
        rest = int(ende - time.monotonic())
        if rest < 5:  # zu knapp für eine weitere Suche
            return ergebnis
        try:
            out = run_as(script, subject, str(window), SENT_SEP, timeout=rest)
        except SystemExit:  # Zeitablauf oder Fehler in Mail: gesendet ist die Mail trotzdem, nur unbestätigt
            return "offen"
        contents = [c for c in out.split(SENT_SEP) if c]
        if any(matches_fingerprint(c, fp) for c in contents):
            return "gefunden"
        ergebnis = "abweichend" if contents else "fehlt"
        if time.monotonic() + 5 >= deadline:  # keine Zeit für Pause und weitere Suche
            return ergebnis
        time.sleep(5)


def cmd_send(cfg: dict, a: argparse.Namespace) -> None:
    ende = time.monotonic() + SEND_GRENZE  # der ganze Aufruf bleibt unter den 120 s des Bash-Werkzeugs
    r = inspect_draft(a.id)
    key, subject = r.id, r.betreff
    state = load_state()
    entry = kit_entry(state, key, subject)
    info = draft_info(r) + reply_note(entry)  # mit An, Cc und Bcc, auch in der Vorschau ohne --yes
    if entry is None:
        if key in state:  # gehört zu einem anderen Entwurf oder einem früheren Mail-Lauf
            state.pop(key)
            save_state(state)
        sys.exit(f"Nicht gesendet: Diesen Entwurf hat das Kit nicht angelegt (oder Mail wurde seither neu "
                 f"gestartet). Eigene Entwürfe in Mail selbst senden: {info}")
    is_reply = entry.get("art") == "antwort"
    if not is_reply and r.laenge == "0":
        sys.exit(f"Entwurf ist leer, wird nicht gesendet: {info}")
    if is_reply and not entry.get("eingefuegt"):
        sys.exit(f"Den Text dieser Antwort hat das Kit nicht eingefügt. Bitte in Mail prüfen und dort "
                 f"selbst senden: {info}")
    if not is_reply and not matches_fingerprint(r.anfang, entry["kennung"]):
        info += " (Textanfang im Fenster geändert)"
    # Absender, den draft verlangt hat. Antworten setzt Mail selbst.
    if not is_reply and (not entry.get("absender") or adresse(r.von) != adresse(entry["absender"])):
        sys.exit(f"Nicht gesendet: Absender ist {clean(r.von) or 'keiner'}, erwartet "
                 f"{entry.get('absender') or 'keiner'}. In Mail bei Von das Konto wählen, dann erneut senden: {info}")
    if not a.yes:
        print(f"Nicht gesendet. Entwurf: {info}")
        print("Zum Senden denselben Befehl mit --yes aufrufen.")
        sys.exit(1)

    ok = run_as('''
on run argv
  set did to (item 1 of argv) as integer
  tell application "Mail" to set ok to send (first outgoing message whose id is did)
  return ok as string
end run
''', key, timeout=SEND_SCHRITT, zeitablauf=f"Mail hat nach {SEND_SCHRITT} s nicht auf Senden geantwortet. Ob die Mail "
                                           "raus ist, ist offen: nicht erneut senden, erst mit drafts prüfen, ob der "
                                           "Entwurf noch offen ist.")
    if ok.strip().lower() == "false":
        sys.exit(f"Mail hat den Entwurf nicht gesendet (Konto offline oder Server lehnt ab). Er bleibt offen: {info}")
    print(f"Gesendet: {info}")
    state.pop(key, None)
    save_state(state)
    result = find_sent(entry["betreff"], entry["kennung"], ende)
    # Betreff kann vom Absender stammen
    pruefen = (f'python3 "{KIT_DIR / "mail.py"}" search --mailbox sent --subject {shlex.quote(entry["betreff"])} '
               "--days 1")
    if result == "gefunden":
        print("Geprüft: Die Mail liegt im Postfach Gesendet, der Text ist drin.")
    elif result == "abweichend":
        print("HINWEIS: Die Mail liegt im Postfach Gesendet, der Textanfang weicht aber vom Entwurf ab. "
              "Normal, wenn im Fenster geändert wurde. Sonst mit read --mailbox sent prüfen.")
    elif result == "fehlt":
        print(f"HINWEIS: Noch nicht im Postfach Gesendet. Später prüfen mit: {pruefen}")
    else:
        print(f"HINWEIS: Bestätigung steht aus, Mail hat nicht rechtzeitig geantwortet. Nicht erneut senden, später "
              f"prüfen mit: {pruefen}")


def find_autosaves(subject: str, fp: dict, since: float) -> list[str]:
    """IDs automatisch gesicherter Kopien eines Kit-Entwurfs im Postfach Entwürfe.

    Kein "whose" auf dem Entwürfe-Postfach (Exchange, Fehler -1728), darum eine Schleife.
    """
    script = '''
on run argv
  set subj to item 1 of argv
  set cutoff to (current date) - ((item 2 of argv) as integer)
  set sep to item 3 of argv
  set out to ""
  tell application "Mail"
    with timeout of 60 seconds
      repeat with m in (get messages of drafts mailbox)
        try
          if (subject of m) is subj and (date received of m) > cutoff then
            set out to out & sep & (id of m as string) & linefeed & (content of m)
          end if
        end try
      end repeat
    end timeout
  end tell
  return out
end run
'''
    window = int(time.time() - since) + 120
    ids = []
    for chunk in run_as(script, subject, str(window), SENT_SEP).split(SENT_SEP):
        msg_id, _, content = chunk.partition("\n")
        if msg_id and matches_fingerprint(content, fp):
            ids.append(msg_id)
    return ids


def delete_drafts(ids: list[str]) -> None:
    """Kopien im Postfach Entwürfe löschen (landen im Papierkorb)."""
    script = '''
on run argv
  tell application "Mail"
    repeat with m in (get messages of drafts mailbox)
      try
        if (id of m as string) is in argv then delete m
      end try
    end repeat
  end tell
end run
'''
    run_as(script, *ids)


def cmd_discard(cfg: dict, a: argparse.Namespace) -> None:
    r = inspect_draft(a.id)
    key, subject = r.id, r.betreff
    state = load_state()
    entry = kit_entry(state, key, subject)
    if entry is None:
        sys.exit(f"Entwurf {a.id} hat nicht das Kit angelegt (oder Mail wurde seither neu gestartet). Nicht "
                 "verworfen: eigene Entwürfe nur in Mail selbst schließen.")
    # Neue Mails ohne Rückfrage, solange der eigene Text unverändert ist (TEXT_PRUEFUNG Zeichen)
    kennung = entry.get("kennung_text")
    if entry.get("art") == "neu" and not (kennung and matches_fingerprint(r.anfang, kennung)):
        sys.exit(f"Nicht verworfen: Der Text von Entwurf {a.id} wurde im Fenster geändert. In Mail selbst "
                 "schließen, damit nichts Eigenes verloren geht.")
    if entry.get("art") == "antwort" and not getattr(a, "ausfuehren", False):
        print(f"Vorschau, nichts verworfen: Antwortentwurf {a.id} ({clean(subject)}). Den Text im Antwortfenster kann "
              f"das Kit nicht lesen, auch nicht, ob du etwas ergänzt hast. Mit mail.py --ausfuehren discard {a.id} "
              "verwerfen, das fragt nach.")
        return
    # Löscht nur, wenn der Betreff noch zum Kit-Entwurf passt. Sonst gehört die id inzwischen zu einem anderen Fenster.
    script = '''
on run argv
  set did to (item 1 of argv) as integer
  tell application "Mail"
    set d to (first outgoing message whose id is did)
    set subj to subject of d
    if subj is not (item 2 of argv) then return "anders" & linefeed & subj
    delete d
    return "ok" & linefeed & subj
  end tell
end run
'''
    res, _, subj = run_as(script, key, entry.get("betreff", "")).partition("\n")
    state.pop(key, None)
    save_state(state)
    if res != "ok":
        sys.exit(f"Nicht verworfen: Entwurf {a.id} heißt jetzt „{clean(subj)}“ und stammt nicht vom Kit.")
    print(f"Entwurf {a.id} verworfen: {clean(subj)}")
    ids = find_autosaves(subj, entry["kennung"], entry["erstellt"])
    if ids:
        delete_drafts(ids)
        print(f"Automatisch gesicherte Kopie im Postfach Entwürfe entfernt ({len(ids)}).")


# ---------- Signatur für Apple Mail ----------

# Was signatur.html enthalten darf: dieselben Tags lässt der Connector in Entwürfen zu, Attribute nur href an a.
SIG_TAGS = {"p", "br", "b", "strong", "i", "em", "a"}
SIG_FETT, SIG_KURSIV = {"b", "strong"}, {"i", "em"}

# HTML und Text in die Zwischenablage. Nicht flüchtig markiert: Der Nutzer fügt die Signatur gleich danach ein,
# auch am iPhone über die geteilte Zwischenablage.
AS_SIG_CLIP = '''
on run argv
  set pb to current application's NSPasteboard's generalPasteboard()
  pb's clearContents()
  set anItem to current application's NSPasteboardItem's alloc()'s init()
  anItem's setString:(item 1 of argv) forType:"public.html"
  anItem's setString:(item 2 of argv) forType:(current application's NSPasteboardTypeString)
  if ((pb's writeObjects:{anItem}) as boolean) then return "ok"
  return "fehler"
end run
'''


class SignaturParser(HTMLParser):
    """Signatur-HTML in Absätze aus Zeilen aus Stücken (Text, fett, kursiv, Link) zerlegen.

    Erlaubt sind nur SIG_TAGS. Alles andere landet in fehler, damit eine kaputte oder erweiterte signatur.html
    auffällt, bevor sie in Apple Mail landet oder der Connector den Entwurf ablehnt."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.absaetze: list[list[list[tuple[str, bool, bool, str]]]] = []
        self.offen: list[str] = []
        self.href = ""
        self.im_absatz = False
        self.fehler: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag not in SIG_TAGS:
            self.fehler.append(f"<{tag}>")
            return
        namen = {n for n, _ in attrs}
        if namen - ({"href"} if tag == "a" else set()):
            self.fehler.append(f"Attribut an <{tag}>")
        if tag == "p":
            if self.im_absatz:
                self.fehler.append("<p> ohne </p>")
            self.absaetze.append([[]])
            self.im_absatz = True
        elif tag == "br":
            if self.im_absatz:
                self.absaetze[-1].append([])
            else:
                self.fehler.append("<br> außerhalb von <p>")
        elif tag == "a":
            self.href = dict(attrs).get("href") or ""
            if not self.href.startswith(("mailto:", "https://", "http://")):
                self.fehler.append("Link ohne mailto oder http")
        else:
            self.offen.append(tag)

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self.im_absatz:
            self.im_absatz = False
            if self.offen or self.href:
                self.fehler.append("</p> vor dem Ende von <b>, <i> oder <a>")
                self.offen, self.href = [], ""
        elif tag == "a" and self.href:
            self.href = ""
        elif tag in self.offen:
            del self.offen[len(self.offen) - 1 - self.offen[::-1].index(tag)]
        elif tag != "br":
            self.fehler.append(f"</{tag}> ohne Anfang")

    def handle_data(self, data: str) -> None:
        text = re.sub(r"\s+", " ", data)
        if not self.im_absatz:
            if text.strip():
                self.fehler.append("Text außerhalb von <p>")
            return
        fett = any(t in SIG_FETT for t in self.offen)
        kursiv = any(t in SIG_KURSIV for t in self.offen)
        self.absaetze[-1][-1].append((text, fett, kursiv, self.href))

    def close(self) -> None:
        super().close()
        if self.im_absatz or self.offen or self.href:
            self.fehler.append("Tag nicht geschlossen")


def signatur_parsen(quelle: str) -> list[list[list[tuple[str, bool, bool, str]]]]:
    """Absätze, Zeilen und Stücke einer signatur.html. Leerzeichen am Zeilenrand fallen weg wie im Browser."""
    p = SignaturParser()
    p.feed(quelle)
    p.close()
    if p.fehler:
        sys.exit("Signatur enthält, was Connector oder Apple Mail nicht sauber zeigen: "
                 + ", ".join(dict.fromkeys(p.fehler)) + ". Erlaubt: p, br, b, strong, i, em, a mit href.")
    def raender(zeile: list) -> list:
        if zeile:
            zeile[0] = (zeile[0][0].lstrip(), *zeile[0][1:])
            zeile[-1] = (zeile[-1][0].rstrip(), *zeile[-1][1:])
        return [s for s in zeile if s[0]]

    absaetze = [[raender(zeile) for zeile in absatz] for absatz in p.absaetze]
    if not any(z for a in absaetze for z in a):
        sys.exit("Signatur ist leer.")
    return absaetze


def signatur_text(absaetze: list) -> str:
    """Reiner Text: eine Zeile je Zeile, eine Leerzeile zwischen Absätzen."""
    return "\n\n".join("\n".join("".join(s[0] for s in zeile) for zeile in absatz) for absatz in absaetze)


def signatur_apple_html(absaetze: list) -> str:
    """Markup wie Apple Mail es selbst schreibt: eine div je Zeile, <div><br></div> als Leerzeile zwischen
    Absätzen. Keine Schrift, keine Farbe, keine Bilder, damit Mail die Standardschrift nimmt."""
    def stueck(text: str, fett: bool, kursiv: bool, href: str) -> str:
        h = html.escape(text, quote=False)
        if href:
            h = f'<a href="{html.escape(href)}">{h}</a>'
        if kursiv:
            h = f"<i>{h}</i>"
        return f"<b>{h}</b>" if fett else h

    teile = []
    for i, absatz in enumerate(absaetze):
        if i:
            teile.append("<div><br></div>")
        teile += [f"<div>{''.join(stueck(*s) for s in zeile) or '<br>'}</div>" for zeile in absatz]
    return "".join(teile)


def signatur_lesen(cfg: dict, profile: str, lang: bool = False) -> list:
    """Kurze Signatur (signatur_html) des Profils lesen und zerlegen, mit lang den Footer (signatur_footer_html)
    als weitere Absätze dahinter. Nur Dateien unter style/ im Kit."""
    prof = get_profile(cfg, profile)
    absaetze = []
    for schluessel in ("signatur_html", "signatur_footer_html") if lang else ("signatur_html",):
        rel = prof.get(schluessel)
        if not rel:
            sys.exit(f"Profil {profile} hat kein {schluessel} in config.json.")
        daten = kit_basis.datenordner(KIT_DIR)
        pfad = (daten / rel).resolve()
        if not pfad.is_relative_to(daten / "style"):
            sys.exit(f"{schluessel} muss unter style/ im Kit liegen: {rel}")
        try:
            absaetze += signatur_parsen(pfad.read_text(encoding="utf-8"))
        except OSError as e:
            sys.exit(f"Signatur nicht lesbar: {rel} ({e.strerror})")
    return absaetze


def ohne_nummern(text: str) -> str:
    """Telefonnummern für die Anzeige ersetzen (kit_basis): Die Ausgabe landet im Transkript, die Nummer bleibt in
    signatur.html."""
    return kit_basis.maskiere_nummern(text)


def cmd_signatur(cfg: dict, a: argparse.Namespace) -> None:
    absaetze = signatur_lesen(cfg, a.profile, a.lang)
    apple, text = signatur_apple_html(absaetze), signatur_text(absaetze)
    print(ohne_nummern(apple if a.html else text))
    if not a.kopieren:
        print("\nMit --kopieren liegt diese Fassung als HTML und Text in der Zwischenablage.")
        return
    if run_as(AS_USE_OBJC + AS_SIG_CLIP, apple, text, timeout=30).strip() != "ok":
        sys.exit("Zwischenablage nicht gesetzt. Nichts geändert, bitte erneut versuchen.")
    konto = get_profile(cfg, a.profile).get("account") or a.profile
    name = f"{konto} lang" if a.lang else konto
    print(f"\nIn der Zwischenablage ({'lange' if a.lang else 'kurze'} Fassung). Einfügen in Mail: Einstellungen, "
          f"Signaturen, Konto {konto}, Signatur {name} wählen (fehlt sie, mit + anlegen), rechts alles markieren und "
          "einsetzen. Darunter das Häkchen 'Immer meiner Standardschrift entsprechen' setzen.")


# ---------- CLI ----------


def main() -> None:
    p = argparse.ArgumentParser(
        description="Apple Mail vom Terminal: suchen, sichten, lesen, Entwürfe, senden. Einstellungen in config.json.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,  # sonst gälte etwa --att als --attach, ohne dass die Rückfrage greift
        epilog="""Beispiele:
  mail.py search --profile privat --from "mueller" --days 30
  mail.py search --profile privat --subject "Rechnung" --unread
  mail.py search --profile privat --mailbox sent --days 14
  mail.py finden --message-id "<abc123@mail.example.org>"
  mail.py finden --subject "Angebot" --from "mueller" --datum 2026-11-10
  mail.py triage 48 privat
  mail.py read 12345
  mail.py read 12345 12346 12347
  mail.py read 12345 --mailbox sent --html
  mail.py draft --profile privat --to a@b.de --subject "Kurze Frage" --text-file entwurf.txt
  mail.py draft --reply-to 12345 --text-file antwort.txt
  mail.py draft --reply-to 12345 --all --text-file antwort.txt
  mail.py draft --reply-to 12345 --betreff-erwartet "Angebot" --text-file antwort.txt
  mail.py drafts
  mail.py send 7 --yes
  mail.py discard 7
  mail.py --ausfuehren discard 12
  mail.py --attach ~/Downloads/a.pdf draft --profile privat --to a@b.de --subject "Unterlagen" --text-file entwurf.txt
  mail.py signatur --kopieren

Exit-Codes: 0 ok, 1 nicht gesendet oder Fehler, 2 Aufruf falsch, 3 Antwort offen, aber Text nicht
eingefügt, 4 neuer Entwurf leer, 5 neuer Entwurf mit anderem Absender als in config.json.
""",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="Mails finden (Posteingang, Standard 90 Tage)", allow_abbrev=False)
    s.add_argument("--from", dest="sender", help="Absender enthält (Name oder Adresse)")
    s.add_argument("--subject", help="Betreff enthält")
    s.add_argument("--text", help="Betreff oder Absender enthält")
    s.add_argument("--days", type=positiv, help="Zeitraum in Tagen zurück (Standard aus config.json)")
    s.add_argument("--unread", action="store_true", help="nur ungelesene")
    s.add_argument("--mailbox", choices=["inbox", "sent"], default="inbox",
                   help="Posteingang oder Gesendet (dort mit Empfängern statt Absender)")
    s.add_argument("--limit", type=positiv, help="maximale Trefferzahl, die neuesten zuerst")
    s.add_argument("--profile", help="nur dieses Kontoprofil durchsuchen, sein Konto muss in config.json/accounts "
                                     "stehen (sonst alle aus accounts)")
    s.set_defaults(fn=cmd_search)

    f = sub.add_parser("finden", help="Mail aus einem Connector in Apple Mail finden, liefert die id für "
                                      "draft --reply-to", allow_abbrev=False)
    f.add_argument("--message-id", help="Message-ID aus dem Connector, genau (mit oder ohne spitze Klammern)")
    f.add_argument("--subject", help="Betreff enthält")
    f.add_argument("--from", dest="sender", help="Absender enthält (Name oder Adresse)")
    f.add_argument("--datum", help="Tag der Mail als JJJJ-MM-TT, ein Tag Spielraum")
    f.add_argument("--days", type=positiv, help=f"Zeitraum ohne --datum (Standard {FINDEN_TAGE} Tage)")
    f.add_argument("--mailbox", choices=["inbox", "sent"], default="inbox", help="Posteingang oder Gesendet")
    f.add_argument("--profile", help="nur dieses Kontoprofil, sonst alle aus accounts")
    f.set_defaults(fn=cmd_finden)

    t = sub.add_parser("triage", help=f"ungelesene Mails der letzten N Stunden (Standard {TRIAGE_STUNDEN}) plus "
                                      "markierte des letzten Jahres, Newsletter aus noise ausgeblendet",
                       allow_abbrev=False)
    t.add_argument("stunden", nargs="?", type=stunden, default=TRIAGE_STUNDEN,
                   help=f"Zeitraum in Stunden, höchstens {TRIAGE_MAX_STUNDEN} (Standard {TRIAGE_STUNDEN})")
    t.add_argument("profil", nargs="?", help="nur dieses Kontoprofil, sein Konto muss in config.json/accounts stehen "
                                             "(sonst alle aus accounts)")
    t.set_defaults(fn=cmd_triage)

    r = sub.add_parser("read", help="Mails anhand der IDs aus der Suche ausgeben, bis zu 10 in einem Aufruf",
                       allow_abbrev=False)
    r.add_argument("id", type=int, nargs="+", help="eine oder mehrere IDs, mehrere mit gemeinsamer Zeichengrenze")
    r.add_argument("--mailbox", choices=["inbox", "sent"], default="inbox")
    r.add_argument("--max-chars", type=positiv, default=0,
                   help=f"Text nach N Zeichen kürzen (ohne Angabe alles), bei mehreren IDs für alle zusammen "
                        f"(Standard {READ_GRENZE})")
    r.add_argument("--html", action="store_true",
                   help="HTML-Quelltext statt Text ausgeben (Formatierung, Zitat, Signatur prüfen)")
    r.add_argument("--profile", help="nur dieses Kontoprofil erlauben, sein Konto muss in config.json/accounts stehen "
                                     "(sonst alle aus accounts)")
    r.set_defaults(fn=cmd_read)

    d = sub.add_parser("draft", help="Entwurf sichtbar in Mail anlegen, nicht senden", allow_abbrev=False)
    d.add_argument("--to", action="append", help="Empfänger, mehrfach möglich (nur neue Mail)")
    d.add_argument("--cc", action="append", help="Kopie, mehrfach möglich")
    d.add_argument("--subject", help="Betreff (nur neue Mail, bei --reply-to setzt Mail ihn)")
    d.add_argument("--text-file", help="entwurf.txt oder antwort.txt im Kit (UTF-8), wird nach Erfolg gelöscht")
    d.add_argument("--reply-to", type=int, metavar="ID",
                   help="echte Antwort auf diese Mail im Posteingang: Verlauf, Zitat, Signatur und Konto setzt Mail")
    d.add_argument("--all", action="store_true", help="mit --reply-to: allen antworten")
    d.add_argument("--betreff-erwartet", metavar="BETREFF",
                   help="mit --reply-to: Betreff der Mail, auf die geantwortet wird. Passt er nicht (ohne Re:, AW:, "
                        "WG:, Fwd:, Leerraum, Groß und Klein), bricht draft ab und öffnet nichts")
    d.add_argument("--attach", action="append",
                   help="Anhang (Pfad) aus einem Ordner in config.json/anhang_ordner, mehrfach möglich (nur neue Mail)")
    d.add_argument("--profile", help="Kontoprofil mit Konto aus config.json/accounts und from_address "
                                     "(Standard: default_profile, also privat)")
    d.set_defaults(fn=cmd_draft)

    ls = sub.add_parser("drafts", help="offene Entwurfsfenster auflisten", allow_abbrev=False)
    ls.set_defaults(fn=cmd_drafts)

    sn = sub.add_parser("send", help="vom Kit angelegten Entwurf senden (nur mit --yes)", allow_abbrev=False)
    sn.add_argument("id", type=int, help="Entwurfs-ID aus draft oder drafts")
    sn.add_argument("--yes", action="store_true", help="wirklich senden")
    sn.set_defaults(fn=cmd_send)

    dc = sub.add_parser("discard", help="vom Kit angelegten Entwurf verwerfen, samt automatischer Kopie",
                        allow_abbrev=False)
    dc.add_argument("id", type=int)
    dc.add_argument("--ausfuehren", action="store_true",
                    help="auch einen Antwortentwurf verwerfen (sein Text ist nicht lesbar, fragt in Claude Code nach)")
    dc.set_defaults(fn=cmd_discard)

    sg = sub.add_parser("signatur", help="Arbeitssignatur als Fassung für Apple Mail zeigen, ändert nichts in Mail",
                        allow_abbrev=False)
    sg.add_argument("--profile", default="arbeit", help="Kontoprofil mit signatur_html (Standard: arbeit)")
    sg.add_argument("--kopieren", action="store_true", help="Fassung als HTML und Text in die Zwischenablage legen")
    sg.add_argument("--lang", action="store_true", help="lange Fassung: mit Footer aus signatur_footer_html")
    sg.add_argument("--html", action="store_true", help="die Apple-Mail-Fassung als HTML statt als Text zeigen")
    sg.set_defaults(fn=cmd_signatur)

    vorn, rest = kit_basis.schalter_vorn(sys.argv[1:], ("--ausfuehren",), ("--attach",))
    a = p.parse_args(rest + vorn)  # die Schalter gehören zu den Unterbefehlen discard und draft
    cfg = load_config()
    a.fn(cfg, a)


if __name__ == "__main__":
    kit_basis.starten(main, __file__)
