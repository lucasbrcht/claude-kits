#!/usr/bin/env python3
"""iMessage und SMS (Nachrichten-App am Mac) vom Terminal aus: Chats lesen, durchsuchen, Neues sichten, senden nach
ausdrücklicher Freigabe.

Das Skript liest die lokale Datenbank der Nachrichten-App (~/Library/Messages/chat.db). Nur lesend: Datenbank und WAL
kommen als Kopie in einen privaten Temp-Ordner, von dort sofort in eine Datenbank im Speicher, dann wird die Kopie
gelöscht. Namen kommen aus dem Adressbuch des Macs, Nummern und Mailadressen erscheinen nie in der Ausgabe. send läuft
nur nach "senden" im Chat und mit Rückfrage (Dialog von macOS im Server), danach prüft das Skript in der Datenbank, ob die
Nachricht wirklich erschienen ist.

Befehle:
  check    Zugriff, Datenbank und Adressbuch prüfen (nur Zahlen)
  chats    Chats nach letzter Aktivität, mit Nachrichtenzahl im Zeitraum
  members  Mitglieder einer Gruppe, nur Namen
  triage   Neues der letzten Stunden, Einzelchats mit neuer Nachricht zuerst
  read     Verlauf eines Chats
  search   Volltextsuche in Nachrichten
  draft    Vorschau einer Nachricht (--dry-run), Entwurf in der App nur mit getestetem Link (entwurf_link)
  send     Nachricht senden, danach Sendeprüfung in der Datenbank (der Server fragt immer nach)

Jeder Befehl kennt --help.

Gelernte Fallstricke, die hier eingebaut sind (Recherche vom 19.10.2026):
- Neue Nachrichten stehen zuerst im WAL (chat.db-wal). Kopiert werden Datenbank und WAL, nie die -shm-Datei.
- Der Text steht oft nur im Blob attributedBody (typedstream, nicht NSKeyedArchiver). Die Länge vor dem Text ist ein
  Byte unter 0x80, sonst folgt auf 0x81 eine Zahl aus 2 Byte und auf 0x82 eine aus 4 Byte, Little Endian. Wer 0x81 mit
  einem Byte liest (Fehler im offiziellen Plugin), schneidet Nachrichten ab 128 Byte ab oder verliert sie bei
  Vielfachen von 256. Hinter dem Text muss die Endmarke 0x86 stehen, sonst gilt die Länge als zweifelhaft.
- date zählt in Nanosekunden ab 2001, ältere Zeilen in Sekunden. Werte ab 1e12 sind Nanosekunden.
- Reaktionen (Tapbacks, Sticker) sind eigene Zeilen mit associated_message_type 1000 bis 3999, sie fehlen im Verlauf.
  Gruppenereignisse haben item_type ungleich 0 und erscheinen nur mit --system.
- Einzelchats haben style 45, Gruppen 43. Seit macOS 26 beginnen GUIDs von Einzelchats mit any, AppleScript findet sie
  dann teils nicht (Fehler -1728): Rückfall auf participant im Konto des Dienstes.
- osascript meldet auch gescheiterte Sendungen als Erfolg. Erst die Zeile in chat.db mit is_from_me 1 und gleichem Text
  zählt, error ungleich 0 heißt gescheitert. Die Fehlermeldung von osascript enthält die Chat-GUID mit der Nummer, sie
  erscheint nie, nur ihre Fehlernummer.
- iCloud spielt Nachrichten teils doppelt ein (neue ROWID, altes Datum). Gleicher Text derselben Richtung im selben
  Chat innerhalb von 2 Sekunden erscheint einmal. Weiterlesen läuft über Datum und ROWID (--before-id), nie über die
  ROWID allein.
- Chats einer Person (Nummer und Mail, iMessage und SMS) fasst das Skript über die Adresse und den Kontakt zusammen,
  die id ist die des zuletzt aktiven Chats. Nie über den Namen: Zwei Personen gleichen Namens bleiben getrennt.
- Eine Kontaktkarte kann zwei Personen tragen (Eltern mit zwei Nummern). Hat ein Chat mehrere Teilchats, gehen draft
  und send nur mit --id, read nennt die Teilchats. Nummern gelten nur genau gleich, nie über die letzten Ziffern.
- SMS-Absender ohne Rufnummer (Firmen, Kurzwahlen, Codes) sind Art Dienst und standardmäßig ausgeblendet.
- Chat- und Gruppennamen wählen andere. In Ausgaben sind sie auf 60 Zeichen gekürzt und eckige Klammern werden runde.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import time
import unicodedata
import urllib.parse
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

import kit_basis  # schalter_vorn, gleich in apple und chat
# Bausteine für Ausgabe, Sicherheit, Chatsuche und Datenbank-Kopie, gemeinsam mit WhatsApp
from nachricht_basis import (APPLE_EPOCH, DATEN_HINWEIS, ID_MAX, LANGE_ZEILE, STEUERZEICHEN, TEXT_MAX, SchreibtGerade,
                             absender, als_text, anzeigename, apple, auswahl,
                             bereinige, config_fehler, drucke, entwurfstext, erwaehnt, falscher_aufruf, falte,
                             fange_signale, fundstelle, kopie_ordner, kopiere_db, kuerze, norm, positiv,
                             raeume_alte_kopien_auf, standard, text_utf8, treffer_je_name, varianten,
                             varianten_suche, verbotene_zeichen, vor_sekunden, wert, zeit, zeitpunkt)
from nachricht_basis import finde_chat as _finde_chat
from nachricht_basis import lade_config as _lade_config

KIT_DIR = Path(__file__).resolve().parent
DATEN_DIR = kit_basis.datenordner(KIT_DIR)  # fester Ordner vom MCP-Server, sonst der Plugin-Ordner
CONFIG_PATH = DATEN_DIR / "config.json"
NACHRICHT_DATEI = DATEN_DIR / "nachricht.txt"  # einzige Textdatei für draft und send, wird nach Erfolg gelöscht
# Absolut, nie über PATH, wie bei whatsapp.py (Prüfung 20.10.2026). Tests setzen in ihrer Kopie des Skripts
# Ersatzbefehle ein, Umgebungsvariablen gibt es nicht
OSASCRIPT_BEFEHL = "/usr/bin/osascript"
OPEN_BEFEHL = "/usr/bin/open"
PRUEF_WARTEN = (1, 1, 2, 3, 5, 8)  # Sekunden zwischen den Blicken in chat.db nach dem Senden, zusammen 20
OSASCRIPT_ZEIT = 30  # Sekunden für die Nachrichten-App, unter den 120 s des Bash-Werkzeugs
STANDARD_DB = "~/Library/Messages/chat.db"
STANDARD_ADRESSBUCH = "~/Library/Application Support/AddressBook"
KOPIE_PRAEFIX = "message-kit-imessage-"
AUFRUF = f'python3 "{KIT_DIR / "imessage.py"}"'  # Folgeaufrufe in Hinweisen immer absolut, wie bei whatsapp.py
DUBLETTE_SEKUNDEN = 600  # gleicher Text an denselben Chat so kurz nach einer eigenen Nachricht nur mit --nochmal
DOPPELT_SEKUNDEN = 2     # iCloud-Kopien: gleicher Text derselben Richtung so dicht hintereinander erscheint einmal
ANFANG_ZEICHEN = 40      # so viele Zeichen vom Anfang verlangt send --text-file als --anfang, für die Rückfrage
EXIT_OFFEN = 3          # laut AppleScript gesendet, in chat.db nicht oder noch nicht als gesendet bestätigt
EXIT_FEHLER = 4          # in chat.db mit Fehler, nicht zugestellt
KEIN_ZUGRIFF = (
    "Kein Zugriff auf die Nachrichten-Daten. Zwei mögliche Ursachen: "
    "1. Der Festplattenvollzugriff fehlt für die App, aus der Claude läuft (Systemeinstellungen > Datenschutz & "
    "Sicherheit > Festplattenvollzugriff, danach die App neu starten). "
    "2. Der Befehl lief in der Sandbox, etwa wegen cd im selben Befehl, einer Pipe oder Umleitung. Dann als eigenen "
    f'Befehl mit absolutem Pfad aufrufen: python3 "{KIT_DIR / "imessage.py"}" <befehl>, ohne cd davor und ohne | '
    "oder >."
)

ARTEN = {"person": "Person", "gruppe": "Gruppe", "dienst": "Dienst"}
STIL_GRUPPE = 43  # chat.style, Einzelchats haben 45
STREAM_KOPF = b"\x04\x0bstreamtyped"
TS = "(CASE WHEN m.date > 1000000000000 THEN m.date / 1000000000.0 ELSE m.date * 1.0 END)"
REAKTION_FREI = "COALESCE(m.associated_message_type, 0) NOT BETWEEN 1000 AND 3999"
NORMAL_SQL = f"{REAKTION_FREI} AND COALESCE(m.item_type, 0) = 0"
PFLICHT_SPALTEN = {
    "message": {"ROWID", "guid", "text", "attributedBody", "handle_id", "date", "is_from_me",
                "associated_message_type", "item_type", "cache_has_attachments"},
    "chat": {"ROWID", "guid", "style", "chat_identifier", "display_name"},
    "handle": {"ROWID", "id"},
    "chat_message_join": {"chat_id", "message_id"},
    "chat_handle_join": {"chat_id", "handle_id"},
}
WAHLFREI = {  # Spalte, Ersatz, wenn sie fehlt (das Schema wächst mit jeder macOS-Version)
    "service": "''", "error": "0", "is_sent": "1", "is_delivered": "0", "date_retracted": "0", "date_edited": "0",
    "is_audio_message": "0", "balloon_bundle_id": "''", "group_title": "''", "group_action_type": "0",
}
ANHAENGE = (("image/gif", "GIF"), ("image/", "Bild"), ("video/", "Video"), ("audio/", "Audio"),
            ("text/vcard", "Kontaktkarte"), ("text/x-vlocation", "Standort"))


# ---------- Konfiguration ----------


def block(cfg: dict) -> dict:
    return cfg.get("imessage") or {}


def pruefe_config(cfg: dict) -> None:
    """Falsche Typen brechen ab: Ein Text statt einer Liste würde Ausschlüsse sonst still unwirksam machen. Die
    gemeinsamen Einstellungen prüft nachricht_basis.config_fehler, hier den Block imessage."""
    fehler = config_fehler(cfg)
    b = cfg.get("imessage", {})
    if not isinstance(b, dict):
        fehler.append("imessage muss ein Objekt sein")
        b = {}
    for k in ("database", "adressbuch", "landesvorwahl", "entwurf_link"):
        if k in b and not isinstance(b[k], str):
            fehler.append(f"imessage.{k} muss ein Text sein")
    if "landesvorwahl" in b and isinstance(b["landesvorwahl"], str) and not b["landesvorwahl"].isdigit():
        fehler.append("imessage.landesvorwahl nur aus Ziffern, etwa 49")
    arten = b.get("hidden_kinds")
    if arten is not None and (not isinstance(arten, list) or not all(isinstance(x, str) for x in arten)):
        fehler.append("imessage.hidden_kinds muss eine Liste von Texten sein")
    elif isinstance(arten, list) and set(arten) - set(ARTEN):
        fehler.append(f"imessage.hidden_kinds kennt nur {', '.join(sorted(ARTEN))}")
    if "entwurf_im_hintergrund" in b and not isinstance(b["entwurf_im_hintergrund"], bool):
        fehler.append("imessage.entwurf_im_hintergrund muss true oder false sein")
    link = b.get("entwurf_link")
    if isinstance(link, str) and link and not (link.startswith(("sms:", "imessage:")) and "{adresse}" in link
                                               and "{text}" in link):
        fehler.append("imessage.entwurf_link beginnt mit sms: oder imessage: und enthält {adresse} und {text}")
    if fehler:
        sys.exit("config.json: " + ". ".join(fehler) + ". Nichts gelesen.")


def lade_config() -> dict:
    return _lade_config(CONFIG_PATH, pruefe_config)


def landesvorwahl(cfg: dict) -> str:
    return block(cfg).get("landesvorwahl") or "49"


def versteckte_arten(cfg: dict) -> set:
    return set(block(cfg).get("hidden_kinds", ["dienst"]))


# ---------- Datenbank-Kopie ----------

DATENSTAND = {"zeit": None}  # letzte Änderung an Datenbank oder WAL in Unix-Sekunden, gesetzt von snapshot
SPALTEN = {}                 # vorhandene Spalten je Tabelle, gesetzt von pruefe_schema


def _kopiere(src: Path, dst: Path, app: str = "Die Nachrichten-App"):
    """Datenbank und WAL passend zueinander kopieren (nachricht_basis.kopiere_db). Eigener Name im Modul, damit die
    Tests das Kopieren in ihrer Kopie des Skripts ersetzen können. app nennt in der Meldung, wer gerade schreibt."""
    return kopiere_db(src, dst, app)


def pruefe_schema(con: sqlite3.Connection) -> None:
    if con.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone() is None:  # keine Tabelle: kein Schemafehler
        sys.exit("Die Nachrichten-Datenbank ist leer. Ist die Nachrichten-App am Mac angemeldet? Nachrichten öffnen, "
                 "bis die Chats zu sehen sind, dann erneut versuchen.")
    fehlend = []
    SPALTEN.clear()
    for tabelle in (*PFLICHT_SPALTEN, "attachment", "message_attachment_join"):
        SPALTEN[tabelle] = {r[1] for r in con.execute(f"PRAGMA table_info({tabelle})")}
    for tabelle, spalten in PFLICHT_SPALTEN.items():
        vorhanden = SPALTEN[tabelle]
        fehlend += [tabelle] if not vorhanden else [f"{tabelle}.{s}" for s in sorted(spalten - vorhanden)]
    if fehlend:
        sys.exit("Das Datenbankschema der Nachrichten-App hat sich geändert, es fehlt: " + ", ".join(fehlend)
                 + ". imessage.py muss angepasst werden.")


def feld(name: str) -> str:
    """Spalte von message im SQL, wenn es sie gibt, sonst ihr Ersatzwert aus WAHLFREI."""
    return f"m.{name}" if name in SPALTEN.get("message", ()) else WAHLFREI[name]


@contextmanager
def snapshot(cfg: dict):
    """chat.db als Datenbank im Speicher. Die Dateikopie im privaten Temp-Ordner (0700) lebt nur, bis das Backup im
    Speicher liegt. Das Original wird nur gelesen."""
    raeume_alte_kopien_auf(KOPIE_PRAEFIX)
    quelle = Path(os.path.expanduser(block(cfg).get("database") or STANDARD_DB))
    con = sqlite3.connect(":memory:")
    con.text_factory = text_utf8
    try:
        try:
            with kopie_ordner(KOPIE_PRAEFIX) as tmp:
                ziel = tmp / "chat.db"
                stand = _kopiere(quelle, ziel)
                if stand is None:
                    sys.exit(f"Nachrichten-Datenbank nicht gefunden: {quelle}. Ist die Nachrichten-App am Mac "
                             "angemeldet?")
                DATENSTAND["zeit"] = max(s[1] for s in stand if s) / 1e9
                datei = sqlite3.connect(ziel)
                try:
                    datei.backup(con)
                finally:
                    datei.close()
        except PermissionError:
            sys.exit(KEIN_ZUGRIFF)
        except OSError as e:  # etwa imessage.database ist ein Ordner oder der Datenträger ist voll (Prüfung 20.10.2026)
            sys.exit(f"Nachrichten-Datenbank nicht lesbar ({e.strerror or type(e).__name__}). imessage.database in "
                     "config.json und freien Speicherplatz prüfen, dann erneut versuchen.")
        con.execute("PRAGMA query_only = ON")
        pruefe_schema(con)
        yield con
    finally:
        con.close()


def stand_text() -> str:
    t = DATENSTAND["zeit"]
    return f"Datenstand {zeit(t - APPLE_EPOCH)}" if t else "Datenstand unbekannt"


# ---------- Adressbuch ----------


def nummer_schluessel(s, land: str = "49") -> str:
    """Rufnummer als Ziffern mit Landesvorwahl, verglichen wird nur genau: +49 176 1234567, 0176 1234567,
    0049 176 1234567, +49 (0)176 1234567, +49 0176 1234567 und ohne Präfix gespeichert 1761234567 ergeben
    491761234567. Leer, wenn keine Ziffer vorkommt. Einen Abgleich über die letzten Ziffern gibt es nicht mehr: Er
    fasste Fremde mit gleicher Endung mit einem Kontakt zusammen (Review 21.10.2026)."""
    t = als_text(s).replace("(0)", "")
    ziffern = re.sub(r"\D", "", t)
    if not ziffern:
        return ""
    if t.lstrip().startswith("+"):
        pass
    elif ziffern.startswith("00"):
        ziffern = ziffern[2:]
    elif ziffern.startswith("0"):
        ziffern = land + ziffern[1:]
    else:
        ziffern = land + ziffern  # ohne Präfix gespeichert: Inlandsnummer ohne die 0
    if land != "39" and ziffern.startswith(land + "0"):  # +49 0176: die 0 fällt weg, nur Italien behält sie
        ziffern = land + ziffern[len(land) + 1:]
    return ziffern


def nummer_varianten(s, land: str = "49") -> set:
    """Schlüssel für einen Ausschluss per Nummer: Ohne Präfix eingetragene Ziffern gelten auch als internationale
    Nummer (4917612345 wie +4917612345). Ausschlüsse greifen lieber einmal zu oft als nie."""
    schluessel = {nummer_schluessel(s, land)}
    t = als_text(s).replace("(0)", "").strip()
    if not t.startswith(("+", "0")):
        schluessel.add(nummer_schluessel("+" + t, land))
    return schluessel - {""}


def ist_rufnummer(adresse: str) -> bool:
    """Eine echte Rufnummer: höchstens Ziffern, Leerzeichen, Klammern, Striche und ein + vorn, mindestens 7 Ziffern.
    Kurzwahlen und Firmennamen (SMS-Absender wie DHL) sind keine."""
    a = als_text(adresse).strip()
    return bool(re.fullmatch(r"\+?[\d\s()./-]+", a)) and len(re.sub(r"\D", "", a)) >= 7


def adressbuch(cfg: dict) -> dict:
    """Kontakte aus allen Quellen des Adressbuchs (AddressBook-v22.abcddb, auch unter Sources/*): Rufnummern und
    Mailadressen zu (Kontakt, Name). Nur zum Abgleich mit den Adressen in chat.db, Nummern und Adressen erscheinen nie.
    Die Kopien liegen nur Sekundenbruchteile im privaten Temp-Ordner. Ohne Zugriff gibt es keine Namen, aber keinen
    Abbruch. Namen bleiben roh (bereinigt, ungekürzt), damit Ausschlüsse sie treffen, anzeigename gilt nur für Ausgaben
    (Review 21.10.2026)."""
    buch = {"tel": {}, "mail": {}, "kontakte": 0, "quellen": 0, "fehler": ""}
    try:
        _lies_adressbuch(cfg, buch)
    except OSError as e:  # etwa ohne Festplattenvollzugriff: dann ohne Namen weiter
        buch["fehler"] = "kein Zugriff" if isinstance(e, PermissionError) else type(e).__name__
    return buch


def _lies_adressbuch(cfg: dict, buch: dict) -> None:
    wurzel = Path(os.path.expanduser(block(cfg).get("adressbuch") or STANDARD_ADRESSBUCH))
    land = landesvorwahl(cfg)
    dateien = [p for p in [wurzel / "AddressBook-v22.abcddb", *sorted(wurzel.glob("Sources/*/AddressBook-v22.abcddb"))]
               if p.is_file()]
    if not dateien:
        buch["fehler"] = "keine Datenbank gefunden"
        return
    with kopie_ordner(KOPIE_PRAEFIX) as tmp:
        for i, quelle in enumerate(dateien):
            ziel = tmp / f"ab{i}.abcddb"
            try:
                if not _kopiere(quelle, ziel, "Das Adressbuch"):
                    continue
                con = sqlite3.connect(ziel)
                con.text_factory = text_utf8
                try:
                    namen = {}
                    for pk, vor, nach, spitz, firma in con.execute(
                            "SELECT Z_PK, ZFIRSTNAME, ZLASTNAME, ZNICKNAME, ZORGANIZATION FROM ZABCDRECORD"):
                        name = " ".join(x for x in (bereinige(vor), bereinige(nach)) if x) or bereinige(spitz) \
                            or bereinige(firma)
                        if name:
                            namen[pk] = (f"{i}:{pk}", name)
                    for besitzer, nummer in con.execute("SELECT ZOWNER, ZFULLNUMBER FROM ZABCDPHONENUMBER"):
                        k = nummer_schluessel(nummer, land)
                        if besitzer in namen and len(re.sub(r"\D", "", als_text(nummer))) >= 7:
                            buch["tel"].setdefault(k, namen[besitzer])
                    for besitzer, adresse in con.execute("SELECT ZOWNER, ZADDRESS FROM ZABCDEMAILADDRESS"):
                        a = als_text(adresse).strip().casefold()
                        if besitzer in namen and "@" in a:
                            buch["mail"].setdefault(a, namen[besitzer])
                    buch["kontakte"] += len(namen)
                    buch["quellen"] += 1
                finally:
                    con.close()
            except PermissionError:
                buch["fehler"] = "kein Zugriff"
            except sqlite3.Error:
                buch["fehler"] = buch["fehler"] or "Schema einer Quelle unbekannt"
            except SchreibtGerade:  # nur diese Quelle fehlt, kein Abbruch mit falschem App-Namen (Review 21.10.2026)
                buch["fehler"] = buch["fehler"] or "wird gerade geschrieben"


def ist_kennung(eintrag: str) -> bool:
    """Ein Eintrag aus excluded_chats, der eine Adresse oder Kennung ist (Rufnummer, Mailadresse, WhatsApp-JID, Chat-GUID
    oder chat_identifier einer Gruppe) und kein Name."""
    x = als_text(eintrag).strip()
    return "@" in x or ";" in x or ist_rufnummer(x) or bool(re.fullmatch(r"chat\d+", x))


def lade_buch(cfg: dict) -> dict:
    """Adressbuch für alle Befehle außer check. Stehen Namen in excluded_chats und ist das Adressbuch nicht ganz lesbar,
    bricht der Befehl ab: Ein ausgeschlossener Chat hieße sonst (Nummer ohne Namen) und wäre sichtbar (Review
    20.10.2026)."""
    buch = adressbuch(cfg)
    if any(not ist_kennung(x) for x in cfg.get("excluded_chats", [])) and (buch["fehler"] or not buch["quellen"]):
        grund = buch["fehler"] or "keine Quelle"
        sys.exit(f"Ausschlüsse per Name brauchen das Adressbuch, es ist nicht ganz lesbar ({grund}). Nichts gelesen. "
                 "Abhilfe: Festplattenvollzugriff prüfen oder den Ausschluss in config.json als Nummer, Mailadresse "
                 "oder Chat-GUID eintragen.")
    return buch


def ausschluss_passt(eintrag: str, land: str, kennungen: set, tel: set, mail: set, namen: set) -> bool:
    """Trifft ein Eintrag aus excluded_chats diesen Chat? Kennungen genau, Rufnummern in jeder Schreibweise (+49 176,
    +49 0176, 0176, 0049, ohne Präfix), Mailadressen ohne Groß- und Kleinschreibung, Namen wie bei der Chatsuche, roh
    und wie in der Ausgabe (Review 20.10. und 21.10.2026)."""
    x = als_text(eintrag).strip()
    if x in kennungen:
        return True
    if "@" in x:
        return x.casefold() in mail
    if ist_rufnummer(x):
        return bool(nummer_varianten(x, land) & tel)
    return bool(varianten(x) & namen)


def kontakt(buch: dict, adresse: str, land: str):
    """(Kontakt, roher Name) zu einer Adresse aus chat.db oder None. Mailadressen und Rufnummern nur genau (Schlüssel
    mit Landesvorwahl, nummer_schluessel), nie über eine gleiche Endung: Sonst hieße ein Fremder wie ein Kontakt und
    ginge send an ihn (Review 21.10.2026). Kennungen ohne Rufnummer (Firmen, urn:biz) haben keinen Kontakt. Für
    Ausgaben den Namen durch anzeigename geben."""
    a = als_text(adresse).strip()
    if "@" in a:
        return buch["mail"].get(a.casefold())
    if not ist_rufnummer(a):
        return None
    return buch["tel"].get(nummer_schluessel(a, land))


# ---------- Dekoder für attributedBody ----------


def dekodiere(blob) -> tuple:
    """Text aus attributedBody (typedstream). Gibt (Text, Länge in Byte, Längenmarke, Endmarke gefunden, Grund) zurück,
    Text None, wenn der Blob nicht lesbar ist. Längenmarke 0 heißt ein Byte, sonst 0x81 (2 Byte) oder 0x82 (4 Byte).
    Gesucht wird der Typ + (84 01 2B) gleich hinter dem Klassennamen NSString, nie irgendein 2B im Blob."""
    b = bytes(blob or b"")
    if not b.startswith(STREAM_KOPF):
        return None, 0, 0, False, "kopf"
    p = b.find(b"NSString", len(STREAM_KOPF))
    if p < 0:
        return None, 0, 0, False, "klasse"
    i = b.find(b"\x84\x01\x2b", p + 8, p + 40)
    if i < 0:
        return None, 0, 0, False, "typ"
    i += 3
    if i >= len(b):
        return None, 0, 0, False, "kurz"
    marke = b[i]
    if marke < 0x80:
        laenge, start, marke = marke, i + 1, 0
    elif marke == 0x81:
        laenge, start = int.from_bytes(b[i + 1:i + 3], "little", signed=True), i + 3
    elif marke == 0x82:
        laenge, start = int.from_bytes(b[i + 1:i + 5], "little", signed=True), i + 5
    else:
        return None, 0, marke, False, "laenge"
    if laenge < 0 or start + laenge > len(b):
        return None, laenge, marke, False, "kurz"
    roh = b[start:start + laenge]
    ende = start + laenge < len(b) and b[start + laenge] == 0x86
    try:
        return roh.decode("utf-8"), laenge, marke, ende, ""
    except UnicodeDecodeError:
        return roh.decode("utf-8", "replace"), laenge, marke, ende, "utf8"


def nachrichtentext(text_feld, blob) -> str:
    """Text einer Nachricht: aus dem Blob, wenn er mit Endmarke lesbar ist, sonst das Feld text, sonst der Blob ohne
    Endmarke. So macht es auch imessage-exporter (erst typedstream, dann text)."""
    t, _laenge, _marke, ende, grund = dekodiere(blob) if blob else (None, 0, 0, False, "leer")
    if t is not None and ende and not grund:
        return t
    feld_text = als_text(text_feld)
    return feld_text or (t or "")


def vergleichstext(s) -> str:
    """Für den Abgleich nach dem Senden: NFC, Leerraum zusammengefasst, Platzhalter für Anhänge weg."""
    return " ".join(unicodedata.normalize("NFC", als_text(s)).replace("￼", " ").split())


# ---------- Chats ----------


def teilnehmer(con: sqlite3.Connection) -> dict:
    """chat ROWID zu den Adressen (handle.id) seiner Teilnehmer."""
    je = defaultdict(list)
    for chat_id, adresse in con.execute("SELECT chj.chat_id, h.id FROM chat_handle_join chj "
                                        "JOIN handle h ON h.ROWID = chj.handle_id ORDER BY chj.handle_id"):
        je[chat_id].append(als_text(adresse))
    return je


def gruppenname(adressen: list, buch: dict, land: str) -> str:
    vornamen = [k[1].split()[0] for k in (kontakt(buch, a, land) for a in adressen) if k]
    if not vornamen:
        return "(Gruppe ohne Namen)"
    rest = len(adressen) - min(3, len(vornamen))
    return "Gruppe mit " + ", ".join(vornamen[:3]) + (f" und {rest} weiteren" if rest > 0 else "")


def bezeichnungen(teile: list, land: str) -> dict:
    """Teilchat (rowid) zu seiner Bezeichnung für Ausgaben, nie die Adresse selbst: Nummer, Mailadresse oder Absender,
    bei mehreren verschiedenen Adressen einer Art etwa Nummer 1 von 2, gezählt in der Reihenfolge der Anlage (Review
    21.10.2026: eine Kontaktkarte Eltern mit zwei Nummern ist ein Chat mit zwei Teilchats)."""
    art_von = {}
    for e in teile:
        a = e["adresse"]
        if "@" in a:
            art_von[e["rowid"]] = ("Mailadresse", a.casefold())
        elif ist_rufnummer(a):
            art_von[e["rowid"]] = ("Nummer", nummer_schluessel(a, land))
        else:
            art_von[e["rowid"]] = ("Absender", a)
    reihe = defaultdict(list)
    for rowid in sorted(art_von):
        art, schluessel = art_von[rowid]
        if schluessel not in reihe[art]:
            reihe[art].append(schluessel)
    return {rowid: art if len(reihe[art]) == 1 else f"{art} {reihe[art].index(s) + 1} von {len(reihe[art])}"
            for rowid, (art, s) in art_von.items()}


def lade_chats(con: sqlite3.Connection, cfg: dict, buch: dict, tage: float | None = None,
               ausschluss: dict | None = None) -> list:
    """Alle Chats, die das Kit sehen darf, ohne excluded_chats. Einzelchats derselben Person (gleiche Adresse oder
    gleicher Kontakt) als ein Chat mit allen ids, die id ist die des zuletzt aktiven. Mit letzter Aktivität und
    Nachrichtenzahl der letzten `tage` Tage. ausschluss (für check) zählt die ausgeschlossenen Chats und merkt sich,
    welche Einträge aus excluded_chats einen Chat getroffen haben."""
    seit = vor_sekunden(tage * 86400) if tage else 1e18
    land = landesvorwahl(cfg)
    dienst_spalte = "c.service_name" if "service_name" in SPALTEN.get("chat", ()) else "''"
    leute = teilnehmer(con)
    roh = con.execute(f"""
        SELECT c.ROWID, c.guid, c.style, c.chat_identifier, c.display_name, {dienst_spalte},
               a.erste, a.letzte, COALESCE(a.n, 0), COALESCE(a.n_ich, 0), a.dienst
        FROM chat c
        LEFT JOIN (SELECT cmj.chat_id, MIN({TS}) AS erste, MAX({TS}) AS letzte, SUM({TS} >= :seit) AS n,
                          SUM({TS} >= :seit AND m.is_from_me = 1) AS n_ich,
                          (SELECT {feld("service")} FROM message m JOIN chat_message_join j ON j.message_id = m.ROWID
                           WHERE j.chat_id = cmj.chat_id ORDER BY {TS} DESC LIMIT 1) AS dienst
                   FROM chat_message_join cmj JOIN message m ON m.ROWID = cmj.message_id
                   WHERE {NORMAL_SQL} GROUP BY cmj.chat_id) a ON a.chat_id = c.ROWID""", {"seit": seit}).fetchall()
    gruppen = defaultdict(list)
    for rowid, guid, stil, kennung, anzeige, dienst_chat, erste, letzte, n, n_ich, dienst in roh:
        adressen = leute.get(rowid) or ([als_text(kennung)] if stil != STIL_GRUPPE else [])
        e = {"rowid": rowid, "guid": als_text(guid), "kennung": als_text(kennung), "anzeige": bereinige(anzeige),
             "gruppe": stil == STIL_GRUPPE, "adressen": adressen, "erste": erste, "letzte": letzte, "n": n,
             "n_ich": n_ich, "dienst": als_text(dienst) or als_text(dienst_chat)}
        if e["gruppe"]:
            gruppen[("gruppe", rowid)].append(e)
            continue
        adresse = adressen[0] if adressen else e["kennung"]
        k = kontakt(buch, adresse, land)
        schluessel = ("kontakt", k[0]) if k else ("adresse", adresse.casefold() if "@" in adresse
                                                  else nummer_schluessel(adresse, land) if ist_rufnummer(adresse)
                                                  else adresse)
        gruppen[schluessel].append({**e, "adresse": adresse, "kontakt": k})
    ausgeschlossen = cfg.get("excluded_chats", [])
    chats = []
    for teile in gruppen.values():
        teile.sort(key=lambda e: (e["letzte"] or -1e18, e["rowid"]), reverse=True)
        haupt = teile[0]
        if haupt["gruppe"]:
            art = "gruppe"
            voll = haupt["anzeige"] or gruppenname(haupt["adressen"], buch, land)
        else:
            k = next((e["kontakt"] for e in teile if e["kontakt"]), None)
            if k:
                art, voll = "person", k[1]
            elif "@" in haupt["adresse"]:
                art, voll = "person", "(Adresse ohne Namen)"
            elif ist_rufnummer(haupt["adresse"]):
                art, voll = "person", "(Nummer ohne Namen)"
            else:
                art = "dienst"
                voll = haupt["adresse"] if re.search(r"[^\W\d_]", haupt["adresse"]) else "(Kurzwahl)"
        # Gruppen nur über GUID, Kennung und Namen: Mitglieder, die ausgeschlossen sind, blenden gemeinsame Gruppen nicht
        # aus (Review 20.10.2026, wie bei WhatsApp). Namen roh und wie in der Ausgabe: [Arbeit] und Namen über 60
        # Zeichen treffen so auch (Review 21.10.2026)
        kennungen = {x for e in teile for x in (e["guid"], e["kennung"], *([] if e["gruppe"] else [e["adresse"]]))}
        tel = {nummer_schluessel(e["adresse"], land) for e in teile if not e["gruppe"] and ist_rufnummer(e["adresse"])}
        mail = {e["adresse"].casefold() for e in teile if not e["gruppe"] and "@" in e["adresse"]}
        namen = varianten(voll) | varianten(anzeigename(voll))
        treffer = [x for x in ausgeschlossen if ausschluss_passt(x, land, kennungen, tel, mail, namen)]
        if treffer:
            if ausschluss is not None:
                ausschluss["chats"] = ausschluss.get("chats", 0) + 1
                ausschluss.setdefault("treffer", set()).update(treffer)
            continue
        teil_namen = {} if haupt["gruppe"] else bezeichnungen(teile, land)
        chats.append({
            "id": haupt["rowid"], "ids": [e["rowid"] for e in teile], "name": anzeigename(voll), "art": art,
            "varianten": namen, "generiert": haupt["gruppe"] and not haupt["anzeige"],
            "teile": [{"rowid": e["rowid"], "guid": e["guid"], "adresse": "" if e["gruppe"] else e["adresse"],
                       "dienst": e["dienst"] or "iMessage", "letzte": e["letzte"],
                       "bezeichnung": teil_namen.get(e["rowid"], "Gruppe")} for e in teile],
            "mitglieder": len(haupt["adressen"]) if haupt["gruppe"] else 1, "dienst": haupt["dienst"] or "iMessage",
            "erste": min((e["erste"] for e in teile if e["erste"] is not None), default=None),
            "letzte": max((e["letzte"] for e in teile if e["letzte"] is not None), default=None),
            "n": sum(e["n"] for e in teile), "n_ich": sum(e["n_ich"] for e in teile)})
    return chats


def sichtbar(chats: list, cfg: dict, alle: bool = False) -> list:
    """Ohne die Chat-Arten aus imessage.hidden_kinds (Standard: Dienste)."""
    aus = set() if alle else versteckte_arten(cfg)
    return [c for c in chats if c["art"] not in aus]


def nur_mit_all(chat: dict, cfg: dict, alle: bool) -> dict:
    """Chats der ausgeblendeten Arten (Standard: Dienste mit Codes) liest read und search --chat nur mit --all, auch
    per --id (Review 20.10.2026)."""
    if chat["art"] in versteckte_arten(cfg) and not alle:
        sys.exit(f"'{chat['name']}' ist ein {ARTEN[chat['art']]} (SMS von Firmen, Codes) und ist ausgeblendet. Nur mit "
                 "--all und nur, wenn der Nutzer danach fragt.")
    return chat


def finde_chat(chats: list, anfrage: str | None, chat_id: int | None = None, strikt: bool = False,
               versteckt: set = frozenset(), nur_gruppen: bool = False) -> dict:
    """Chat per id oder Name (nachricht_basis.finde_chat mit den Arten und dem Aufruf von iMessage). Erzeugte
    Gruppennamen (Gruppe mit Anna, Ben) zählen beim Namen nie, und für Entwürfe und Senden (strikt) trifft eine Gruppe
    nur mit ihrem ganzen Namen: Sonst ginge "send 'Ben'" an eine Gruppe, in der Ben ist (Review 20.10.2026). Per --id
    bleibt jeder Chat erreichbar, chats --query findet auch die Gruppen. Dieselbe Auswahl gilt für den Abgleich, wenn
    Name und --id beide dastehen."""
    namens_chats = None
    if anfrage:
        q = varianten(anfrage)
        namens_chats = [c for c in chats
                        if not c["generiert"] and not (strikt and c["art"] == "gruppe" and not q & c["varianten"])]
    return _finde_chat(chats, anfrage, chat_id, strikt, versteckt, nur_gruppen, ARTEN, AUFRUF, namens_chats)


# ---------- Nachrichten ----------


def nachrichten_sql() -> str:
    return f"""
        SELECT m.ROWID, cmj.chat_id, {TS} AS ts, m.is_from_me, m.text, m.attributedBody, h.id,
               COALESCE(m.cache_has_attachments, 0), COALESCE(m.item_type, 0), {feld("group_title")},
               {feld("group_action_type")}, {feld("date_retracted")}, {feld("date_edited")}, {feld("is_audio_message")},
               {feld("balloon_bundle_id")}, {feld("error")}, {feld("is_sent")}, {feld("is_delivered")}, {feld("service")}
        FROM message m
        JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
        LEFT JOIN handle h ON h.ROWID = m.handle_id"""


def anhaenge(con: sqlite3.Connection, ids: list) -> dict:
    """Nachricht zu ihren Anhängen als (MIME-Typ, Dateiname, Sticker). Leer, wenn die Tabellen fehlen."""
    a_sp, j_sp = SPALTEN.get("attachment", set()), SPALTEN.get("message_attachment_join", set())
    if not ids or not {"ROWID", "mime_type"} <= a_sp or not {"message_id", "attachment_id"} <= j_sp:
        return {}
    name = "a.transfer_name" if "transfer_name" in a_sp else "''"
    sticker = "COALESCE(a.is_sticker, 0)" if "is_sticker" in a_sp else "0"
    je = defaultdict(list)
    for mid, mime, datei, ist_sticker in con.execute(
            f"SELECT j.message_id, a.mime_type, {name}, {sticker} FROM message_attachment_join j "
            "JOIN attachment a ON a.ROWID = j.attachment_id WHERE j.message_id IN (SELECT value FROM json_each(?))",
            (json.dumps(ids),)):
        je[mid].append((als_text(mime), als_text(datei), bool(ist_sticker)))
    return je


def nachrichten(con, chats_je_id: dict, buch: dict, cfg: dict, seit=None, bis=None, limit=None, system=False,
                nur_ich=False, aufsteigend=False, vor=None, passt=None) -> list:
    """Nachrichten der Datenbank-Chats in chats_je_id (ROWID zu Chat), neueste zuerst (aufsteigend: älteste zuerst).
    vor=(Zeitstempel, ROWID): nur ältere als diese Nachricht. passt: Filter in Python (der Text steht oft nur im Blob),
    gelesen wird dann nur bis zum Limit. iCloud-Dubletten (gleicher Chat, gleiche Richtung, gleicher Text, höchstens
    2 Sekunden Abstand) erscheinen einmal, auch über die Grenze einer Seite hinweg: Mit vor zählen die Nachrichten ab
    der Grenze bis 2 Sekunden danach als schon gezeigt (Review 21.10.2026). teil ist der Datenbank-Chat der
    Nachricht."""
    land = landesvorwahl(cfg)
    basis = ["cmj.chat_id IN (SELECT value FROM json_each(?))", REAKTION_FREI]
    if not system:
        basis.append("COALESCE(m.item_type, 0) = 0")
    if nur_ich:
        basis.append("m.is_from_me = 1")
    wo, params = list(basis), [json.dumps(list(chats_je_id))]
    if seit is not None:
        wo.append(f"{TS} >= ?")
        params.append(seit)
    if bis is not None:
        wo.append(f"{TS} < ?")
        params.append(bis)
    if vor is not None:
        wo.append(f"({TS} < ? OR ({TS} = ? AND m.ROWID < ?))")
        params += [vor[0], vor[0], vor[1]]
    richtung = "ASC" if aufsteigend else "DESC"
    sql = nachrichten_sql() + " WHERE " + " AND ".join(wo) + f" ORDER BY ts {richtung}, m.ROWID {richtung}"
    aus, zuletzt, namen = [], {}, {}
    if vor is not None:  # Grenze der vorigen Seite: was dort stand, erscheint hier nicht noch einmal als Dublette
        rand = basis + [f"{TS} <= ?", f"({TS} > ? OR ({TS} = ? AND m.ROWID >= ?))"]
        for r in con.execute(nachrichten_sql() + " WHERE " + " AND ".join(rand),
                             [json.dumps(list(chats_je_id)), vor[0] + DOPPELT_SEKUNDEN, vor[0], vor[0], vor[1]]):
            schluessel = (chats_je_id[r[1]]["id"], bool(r[3]), vergleichstext(nachrichtentext(r[4], r[5])))
            zuletzt[schluessel] = min(zuletzt.get(schluessel, r[2]), r[2])
    for r in con.execute(sql, params):
        absender_name = None
        if r[6] and not r[3]:
            if r[6] not in namen:
                k = kontakt(buch, r[6], land)
                namen[r[6]] = anzeigename(k[1]) if k else None
            absender_name = namen[r[6]]
        m = {"id": r[0], "chat": chats_je_id[r[1]]["id"], "teil": r[1], "ts": r[2], "ich": bool(r[3]),
             "text": nachrichtentext(r[4], r[5]), "absender": absender_name, "anhang": bool(r[7]),
             "item_type": r[8], "titel": als_text(r[9]), "aktion": r[10] or 0, "zurueckgezogen": bool(r[11]),
             "bearbeitet": bool(r[12]), "audio": bool(r[13]), "app": bool(als_text(r[14])), "fehler": r[15] or 0,
             "gesendet": bool(r[16]), "zugestellt": bool(r[17]), "dienst": als_text(r[18]), "anhaenge": []}
        schluessel = (m["chat"], m["ich"], vergleichstext(m["text"]))
        frueher = zuletzt.get(schluessel)
        if frueher is not None and abs(frueher - m["ts"]) <= DOPPELT_SEKUNDEN and m["text"]:
            continue
        zuletzt[schluessel] = m["ts"]
        if passt is not None and not passt(m):
            continue
        aus.append(m)
        if limit and len(aus) >= limit:
            break
    mit_anhang = [m["id"] for m in aus if m["anhang"]]
    for mid, liste in anhaenge(con, mit_anhang).items():
        for m in aus:
            if m["id"] == mid:
                m["anhaenge"] = liste
    return aus


def anhang_text(mime: str, datei: str, sticker: bool, audio: bool) -> str:
    if sticker:
        return "[Sticker]"
    if audio or mime == "audio/x-caf" or datei.lower().endswith(".caf"):
        return "[Sprachnachricht]"
    for vorn, art in ANHAENGE:
        if mime.startswith(vorn):
            return f"[{art}]"
    name = anzeigename(datei)
    return f"[Dokument] {name}" if name else "[Datei]"


def ereignis(m: dict) -> str:
    if m["item_type"] == 2:
        return ("[Ereignis] Gruppe umbenannt: " + anzeigename(m["titel"])).strip()
    if m["item_type"] == 1:
        return "[Ereignis] Mitglied entfernt" if m["aktion"] == 1 else "[Ereignis] Mitglied hinzugefügt"
    if m["item_type"] == 3:
        return "[Ereignis] Gruppe verlassen oder Gruppenbild geändert"
    return f"[Ereignis, Typ {m['item_type']}]"


def inhalt(m: dict) -> str:
    if m["zurueckgezogen"]:
        return "[zurückgezogen]"
    if m["item_type"]:
        return ereignis(m)
    text = bereinige(m["text"].replace("￼", " "))
    teile = [anhang_text(mime, datei, st, m["audio"]) for mime, datei, st in m["anhaenge"]]
    if m["audio"] and not teile:
        teile = ["[Sprachnachricht]"]
    elif m["anhang"] and not teile:
        teile = ["[Anhang]"]
    aus = " ".join(teile + ([text] if text else []))
    if not aus:
        aus = "[App-Nachricht]" if m["app"] else "[leer]"
    return aus + (" (bearbeitet)" if m["bearbeitet"] else "")


def zeile(m: dict, chat: dict, cfg: dict, mit_chat: bool = False, laenge: int = 0, mit_teil: bool = False) -> str:
    """Eine Nachricht als Zeile. mit_teil (read bei mehreren Teilchats) nennt den Teilchat mit seiner id."""
    text = inhalt(m)
    text = kuerze(text, laenge) if laenge else text
    vorn = f"{zeit(m['ts'])} | " + (f"id {m['teil']} | " if mit_teil else "")
    return vorn + (f"{chat['name']} | " if mit_chat else "") + f"{absender(m, chat, cfg)}: {text}"


def je_db_id(chats: list) -> dict:
    """Datenbank-Chat (ROWID) zu seinem zusammengefassten Chat."""
    return {i: c for c in chats for i in c["ids"]}


# ---------- Befehle: lesen ----------


def cmd_check(cfg: dict, a: argparse.Namespace) -> None:
    buch = adressbuch(cfg)  # check meldet ein unlesbares Adressbuch nur, statt abzubrechen
    ausschluss = {}
    with snapshot(cfg) as con:
        alle = lade_chats(con, cfg, buch, ausschluss=ausschluss)
        chats = sichtbar(alle, cfg)
        roh = con.execute("SELECT COUNT(*) FROM chat").fetchone()[0]
        ids = [i for c in alle for i in c["ids"]]
        # Nur zählen: Die Diagnose des Dekoders über alle Blobs entfiel, sie lief am 20.10.2026 ohne Befund
        anzahl = con.execute("SELECT COUNT(*) FROM message m JOIN chat_message_join cmj ON cmj.message_id = m.ROWID "
                             f"WHERE cmj.chat_id IN (SELECT value FROM json_each(?)) AND {REAKTION_FREI}",
                             (json.dumps(ids),)).fetchone()[0]
    neueste = max((c["letzte"] for c in chats if c["letzte"] is not None), default=None)
    einzel = [c for c in alle if c["art"] == "person"]
    print(f"OK: Zugriff auf Nachrichten. {len(chats)} Chats sichtbar, {anzahl} Nachrichten, neueste "
          f"{zeit(neueste)}. {stand_text()}.")
    ausschluesse = cfg.get("excluded_chats", [])
    getroffen = ausschluss.get("treffer", set())
    nur_wa = [x for x in ausschluesse if re.search(r"@(?:s\.whatsapp\.net|g\.us|lid|newsletter|broadcast)$", x)]
    offen = [x for x in ausschluesse if x not in getroffen and x not in nur_wa]
    offen_kennung = sum(1 for x in offen if ist_kennung(x))  # Adresse oder GUID ohne Treffer: vermutlich vertippt
    teile_aus = [f"davon {offen_kennung} Adressen oder GUIDs ohne Treffer" if offen_kennung else "",
                 f"{len(offen) - offen_kennung} Namen ohne Treffer in iMessage" if len(offen) > offen_kennung else "",
                 f"{len(nur_wa)} nur für WhatsApp" if nur_wa else ""]
    print(f"Nicht sichtbar: {len(alle) - len(chats)} Chats der Arten "
          f"{', '.join(sorted(versteckte_arten(cfg))) or 'keine'}, {ausschluss.get('chats', 0)} ausgeschlossen "
          f"(excluded_chats: {len(ausschluesse)} Einträge" + "".join(f", {t}" for t in teile_aus if t)
          + f"). Datenbank: {roh} Chats, zusammengefasst {len(alle) + ausschluss.get('chats', 0)}.")
    if buch["quellen"]:
        mit_namen = sum(1 for c in einzel if not c["name"].startswith("("))
        aktiv = [c for c in einzel if (c["letzte"] or 0) >= vor_sekunden(90 * 86400)]
        ohne = [c for c in einzel if c["name"].startswith("(")]
        print(f"Adressbuch: {buch['kontakte']} Kontakte aus {buch['quellen']} Quellen, {mit_namen} von {len(einzel)} "
              f"Chats mit Personen haben einen Namen, in den letzten 90 Tagen "
              f"{sum(1 for c in aktiv if not c['name'].startswith('('))} von {len(aktiv)}. Ohne Namen: "
              f"{sum(1 for c in ohne if c['name'] == '(Nummer ohne Namen)')} Nummern, davon "
              f"{sum(1 for c in ohne if c['teile'][0]['adresse'].startswith('+' + landesvorwahl(cfg)))} mit Landesvorwahl "
              f"{landesvorwahl(cfg)}, "
              f"{sum(1 for c in ohne if c['name'] == '(Adresse ohne Namen)')} Mailadressen"
              + (f" (eine Quelle nicht lesbar: {buch['fehler']})" if buch["fehler"] else "") + ".")
    else:
        print(f"Adressbuch: nicht lesbar ({buch['fehler'] or 'unbekannt'}). Chats erscheinen dann ohne Namen.")


def cmd_chats(cfg: dict, a: argparse.Namespace) -> None:
    tage = wert(a.days, cfg, "chats_days", 30)
    buch = lade_buch(cfg)
    with snapshot(cfg) as con:
        chats = sichtbar(lade_chats(con, cfg, buch, tage=tage), cfg, a.all)
    limit = wert(a.limit, cfg, "chats_limit", 40)
    grenze = vor_sekunden(tage * 86400)

    def ordne(liste: list) -> list:
        if a.kind:
            liste = [c for c in liste if c["art"] == a.kind]
        if a.sort == "anzahl":
            return sorted(liste, key=lambda c: (c["n"], c["letzte"] or 0), reverse=True)
        return sorted(liste, key=lambda c: c["letzte"] or 0, reverse=True)

    def tabelle(liste: list) -> None:
        print(f"id | Chat | Art | zuletzt | Nachrichten {tage:g} T (davon von dir) | Hinweis")
        for c in liste[:limit]:
            art = ARTEN[c["art"]] + (f", {c['mitglieder']} Mitglieder" if c["art"] == "gruppe" else "")
            hinweise = [h for h, an in (("neu im Zeitraum", (c["erste"] or 0) >= grenze),
                                        ("SMS", c["dienst"] in ("SMS", "RCS")),
                                        ("mehrere Adressen", len(c["ids"]) > 1)) if an]
            print(f"{c['id']} | {c['name']} | {art} | {zeit(c['letzte'])} | {c['n']} ({c['n_ich']}) | "
                  f"{', '.join(hinweise)}")

    namen = list(dict.fromkeys(a.query or []))
    if len(namen) > 1:  # je Name ein Block
        print(f"{len(namen)} Namen gesucht. {DATEN_HINWEIS}")
        for name, treffer in treffer_je_name(chats, namen):
            treffer = ordne(treffer)
            mehr = f", Anzeige der ersten {limit}" if len(treffer) > limit else ""
            print(f"\n## {name}: " + (f"{len(treffer)} Chats{mehr}" if treffer else "kein Chat"))
            if treffer:
                tabelle(treffer)
        return
    query = namen[0] if namen else None
    chats = ordne(treffer_je_name(chats, namen)[0][1] if query else [c for c in chats if c["n"] > 0])
    print(f"{len(chats)} Chats" + (f" zu '{query}'" if query else f" mit Nachrichten in den letzten {tage:g} Tagen")
          + (f", Anzeige der ersten {limit}" if len(chats) > limit else "") + f". {DATEN_HINWEIS}")
    tabelle(chats)


def cmd_members(cfg: dict, a: argparse.Namespace) -> None:
    buch = lade_buch(cfg)
    land = landesvorwahl(cfg)
    with snapshot(cfg) as con:
        chat = finde_chat(lade_chats(con, cfg, buch), a.chat, a.id, versteckt=versteckte_arten(cfg), nur_gruppen=True)
        if chat["art"] != "gruppe":
            sys.exit(f"'{chat['name']}' ist keine Gruppe.")
        adressen = teilnehmer(con).get(chat["id"], [])
    namen = [anzeigename(k[1]) if k else None for k in (kontakt(buch, x, land) for x in adressen)]
    ohne = namen.count(None)
    namen = sorted({n for n in namen if n}, key=norm)
    print(f"{chat['name']} (Gruppe, id {chat['id']}): {len(adressen)} Mitglieder außer dir"
          + (f", davon {ohne} ohne Kontakt im Adressbuch" if ohne else "") + f". {DATEN_HINWEIS}")
    if namen:
        print(", ".join(namen))


def cmd_triage(cfg: dict, a: argparse.Namespace) -> None:
    stunden = wert(a.hours, cfg, "triage_hours", 48)
    seit = vor_sekunden(stunden * 3600)
    namen = [norm(n) for n in cfg.get("me_names", [cfg.get("me", "")])]
    buch = lade_buch(cfg)
    with snapshot(cfg) as con:
        chats = sichtbar(lade_chats(con, cfg, buch), cfg)
        rows = nachrichten(con, je_db_id(chats), buch, cfg, seit=seit, aufsteigend=True)
    je_id = {c["id"]: c for c in chats}
    je_chat = defaultdict(list)
    for m in rows:
        je_chat[m["chat"]].append(m)
    offen, gruppen, beantwortet = [], [], []
    for cid, ms in je_chat.items():
        c = je_id[cid]
        if all(m["ich"] for m in ms):
            continue
        letzte_ich = max((i for i, m in enumerate(ms) if m["ich"]), default=-1)
        neu = ms[letzte_ich + 1:]
        e = {"chat": c, "ms": ms, "neu": neu, "letzte": ms[-1]["ts"],
             "bezug": [m for m in neu if erwaehnt(m["text"], namen)]}
        if c["art"] == "gruppe":
            gruppen.append(e)
        else:
            (offen if neu else beantwortet).append(e)
    kopf = (f"iMessage und SMS, letzte {stunden:g} Stunden, {stand_text()}: "
            f"{len(offen) + len(gruppen) + len(beantwortet)} Chats mit neuen Nachrichten. {DATEN_HINWEIS}")
    zeilen = [kopf]
    if not je_chat:
        zeilen.append("Nichts Neues.")
    if offen:
        zeilen += ["", f"## Neu seit deiner letzten Nachricht ({len(offen)})"]  # ob eine Antwort nötig ist, sagt der Inhalt
        for e in sorted(offen, key=lambda e: e["letzte"], reverse=True):
            c = e["chat"]
            zeilen.append(f"{c['name']} (id {c['id']}) · {len(e['neu'])} neu seit deiner letzten Nachricht · zuletzt "
                          f"{zeit(e['letzte'])}" + (" · SMS" if c["dienst"] in ("SMS", "RCS") else ""))
            zeilen += ["  " + zeile(m, c, cfg, laenge=220) for m in e["neu"][-5:]]
    if gruppen:
        zeilen += ["", f"## Gruppen ({len(gruppen)})"]
        for e in sorted(gruppen, key=lambda e: (bool(e["bezug"]), len(e["neu"])), reverse=True):
            c = e["chat"]
            zeilen.append(f"{c['name']} (id {c['id']}) · {len(e['neu'])} neu · zuletzt {zeit(e['letzte'])}"
                          + (" · erwähnt dich" if e["bezug"] else ""))
            zeigen = e["bezug"][-3:] or [m for m in e["ms"] if not m["ich"]][-1:]
            zeilen += ["  " + zeile(m, c, cfg, laenge=220 if e["bezug"] else 120) for m in zeigen]
    if beantwortet:
        zeilen += ["", f"## Beantwortet ({len(beantwortet)})"]
        for e in sorted(beantwortet, key=lambda e: e["letzte"], reverse=True):
            c = e["chat"]
            zeilen.append(f"{c['name']} (id {c['id']}) · zuletzt {zeit(e['letzte'])} von {cfg.get('me', 'Ich')}")
    drucke(zeilen, wert(a.max_chars, cfg, "max_chars", 6000))


def cmd_read(cfg: dict, a: argparse.Namespace) -> None:
    seit = vor_sekunden(a.days * 86400) if a.days is not None else (apple(zeitpunkt(a.since)) if a.since else None)
    bis = apple(zeitpunkt(a.before)) if a.before else None
    limit = a.limit if a.limit is not None else (500 if seit is not None else standard(cfg, "read_limit", 60))
    max_zeichen = wert(a.max_chars, cfg, "max_chars", 6000)
    buch = lade_buch(cfg)
    with snapshot(cfg) as con:
        chats = lade_chats(con, cfg, buch)
        chat = nur_mit_all(finde_chat(chats, a.chat, a.id, versteckt=versteckte_arten(cfg)), cfg, a.all)
        zuordnung = {i: chat for i in chat["ids"]}
        vor = None
        if a.before_id is not None:
            r = con.execute(f"SELECT {TS} FROM message m JOIN chat_message_join cmj ON cmj.message_id = m.ROWID "
                            "WHERE m.ROWID = ? AND cmj.chat_id IN (SELECT value FROM json_each(?))",
                            (a.before_id, json.dumps(chat["ids"]))).fetchone()
            if r is None:
                sys.exit(f"Nachricht {a.before_id} gehört nicht zu {chat['name']} (id {chat['id']}). Die id aus dem "
                         "Hinweis von read nehmen.")
            vor = (r[0], a.before_id)
        rows = nachrichten(con, zuordnung, buch, cfg, seit, bis, limit=limit, system=a.system, vor=vor)
        aelter = bool(rows) and bool(nachrichten(con, zuordnung, buch, cfg, seit, None, limit=1, system=a.system,
                                                 vor=(rows[-1]["ts"], rows[-1]["id"])))
    if not rows:
        print(f"{chat['name']} ({ARTEN[chat['art']]}, id {chat['id']}): keine Nachrichten im Zeitraum.")
        return
    mehrere = len(chat["teile"]) > 1  # etwa Nummer und Mailadresse oder eine Kontaktkarte mit zwei Personen
    zeilen = [zeile(m, chat, cfg, laenge=LANGE_ZEILE, mit_teil=mehrere) for m in reversed(rows)]  # chronologisch
    gezeigt = auswahl(zeilen, max_zeichen, von_hinten=True)
    aeltester, weg = rows[len(gezeigt) - 1], len(rows) - len(gezeigt)
    print(f"{chat['name']} ({ARTEN[chat['art']]}, id {chat['id']}): {len(gezeigt)} Nachrichten vom "
          f"{zeit(aeltester['ts'])} bis {zeit(rows[0]['ts'])}. {DATEN_HINWEIS}")
    if mehrere:  # Review 21.10.2026: welche Nachricht über welche Adresse kam, ohne die Adresse zu zeigen
        print("Teilchats (Nachrichten tragen ihre id, draft und send nur mit Name und --id): " + " · ".join(
            f"id {t['rowid']} {t['bezeichnung']}, {t['dienst']}, zuletzt {zeit(t['letzte'])}"
            for t in sorted(chat["teile"], key=lambda t: t["rowid"])))
    if weg or aelter:
        folge = f"{AUFRUF} read --id {chat['id']} --before-id {aeltester['id']}"
        for option, wert_ in (("--days", a.days), ("--since", a.since), ("--limit", a.limit),
                              ("--max-chars", a.max_chars)):
            if wert_ is not None:
                folge += f" {option} " + (f"{wert_:g}" if isinstance(wert_, float) else f"'{wert_}'"
                                          if isinstance(wert_, str) else f"{wert_}")
        folge += " --system" if a.system else ""
        teil = f"{weg} ältere Zeilen ausgelassen, Grenze {max_zeichen} Zeichen. " if weg else ""
        print(f"[{teil}Ältere Nachrichten vorhanden, weiterlesen mit: {folge}]")
    print("\n".join(gezeigt))


def cmd_search(cfg: dict, a: argparse.Namespace) -> None:
    begriffe = [varianten_suche(b) for b in a.terms if falte(b)]
    if not begriffe:
        falscher_aufruf("Suchbegriff fehlt.")
    tage = wert(a.days, cfg, "search_days", 365)
    seit = vor_sekunden(tage * 86400)

    def passt(m):  # alle Begriffe, ohne Groß- und Kleinschreibung, Akzente und Umlautschreibweise
        t = varianten_suche(m["text"])
        return all(any(v in x for v in b for x in t) for b in begriffe)

    buch = lade_buch(cfg)
    with snapshot(cfg) as con:
        chats = lade_chats(con, cfg, buch)
        ziel = ([nur_mit_all(finde_chat(chats, a.chat, versteckt=versteckte_arten(cfg)), cfg, a.all)] if a.chat
                else sichtbar(chats, cfg, a.all))
        rows = nachrichten(con, je_db_id(ziel), buch, cfg, seit=seit, nur_ich=a.from_me, passt=passt,
                           limit=wert(a.limit, cfg, "search_limit", 30))
    je_id = {c["id"]: c for c in ziel}
    suche = " ".join(a.terms)
    print(f"Suche '{suche}': {len(rows)} Treffer in den letzten {tage:g} Tagen, neueste zuerst. {DATEN_HINWEIS}")
    zeilen = []
    for m in rows:
        c = je_id[m["chat"]]
        text = inhalt(m)
        if len(text) > 240:
            start = max(0, fundstelle(text, a.terms[0]) - 100)
            text = ("[vorne gekürzt] " if start else "") + kuerze(text[start:], 220)
        zeilen.append(f"{zeit(m['ts'])} | {c['name']} (id {c['id']}) | {absender(m, c, cfg)}: {text}")
    drucke(zeilen, wert(a.max_chars, cfg, "max_chars", 6000))


# ---------- Befehle: Vorschau, Entwurf, Senden ----------


def text_aus(a: argparse.Namespace, cfg: dict) -> str:
    """Text aus --text oder nachricht.txt im Kit, geprüft auf Länge, unsichtbare und verbotene Zeichen. Ein Abbruch
    meldet bei send Nichts gesendet, bei draft Nichts geöffnet."""
    text = (entwurfstext(a.text_file, NACHRICHT_DATEI) if a.text_file else (a.text or "")).replace("\r\n", "\n").strip()
    was = "gesendet" if a.cmd == "send" else "geöffnet"
    if not text:
        sys.exit(f"Kein Text. Nichts {was}.")
    if len(text) > TEXT_MAX:
        sys.exit(f"Text mit {len(text)} Zeichen ist länger als {TEXT_MAX}. Kürzen oder aufteilen. Nichts {was}.")
    if STEUERZEICHEN.search(text):  # Vorschau und Rückfrage zeigten sie nicht, gesendet würden sie (Review 20.10.2026)
        sys.exit(f"Nicht {was}: Der Text enthält unsichtbare Steuer- oder Richtungszeichen. Text neu schreiben.")
    verstoesse = verbotene_zeichen(text, cfg.get("forbidden_chars", []))
    if verstoesse and not a.ignore_style:
        sys.exit(f"Nicht {was}: Der Text enthält " + ", ".join(f"'{z}'" for z in verstoesse)
                 + " (laut Schreibregeln nie verwenden). Text anpassen oder bewusst mit --ignore-style direkt hinter "
                   "dem Skript.")
    return text


def textanfang(text: str) -> str:
    """Die ersten ANFANG_ZEICHEN Zeichen, Leerraum zusammengefasst. send --text-file verlangt sie als --anfang, damit
    die Rückfrage zeigt, womit der Text beginnt (Review 21.10.2026)."""
    return vergleichstext(text)[:ANFANG_ZEICHEN].rstrip()


def ziel_teil(chat: dict, chat_id) -> dict:
    """Der Datenbank-Chat, an den draft und send gehen: bei --id genau dieser (Review 20.10.2026). Ohne --id nur, wenn
    der Chat einen einzigen Teilchat hat, sonst Mehrdeutig mit der Liste: Eine Kontaktkarte Eltern mit zwei Nummern ging
    sonst still an die zuletzt aktive (Review 21.10.2026)."""
    if chat_id is not None:
        return next((t for t in chat["teile"] if t["rowid"] == chat_id), chat["teile"][0])
    if len(chat["teile"]) == 1:
        return chat["teile"][0]
    print(f"Mehrdeutig: {chat['name']} hat {len(chat['teile'])} Teilchats. Mit Name und --id wählen:")
    for t in sorted(chat["teile"], key=lambda t: t["rowid"]):
        print(f"  id {t['rowid']} | {t['bezeichnung']} | {t['dienst']} | zuletzt {zeit(t['letzte'])}")
    sys.exit(2)


def ziel_text(chat: dict, teil: dict) -> str:
    """Empfänger für Vorschau, Rückfrage und Sendezeile: Name, Art, Teilchat (über Nummer, über Mailadresse, über
    Nummer 1 von 2) und id, nie die Adresse selbst."""
    if chat["art"] == "gruppe":
        art = f"Gruppe mit {chat['mitglieder']} Personen außer dir"
    else:
        art = f"{ARTEN[chat['art']]}, über {teil['bezeichnung']}"
    return f"{chat['name']} ({art}, id {teil['rowid']})"


def dienst_von(teil: dict) -> str:
    return "SMS" if teil["dienst"] in ("SMS", "RCS") else "iMessage"


def pruefcode(teil: dict, text: str) -> str:
    """Kurzer Code aus Ziel und Text: draft --dry-run zeigt ihn, send --text-file verlangt ihn. So steht in der Rückfrage
    etwas, das genau an diesen Text und diesen Chat gebunden ist, auch wenn der Text nur in nachricht.txt steht."""
    return hashlib.sha256(f"{teil['guid']}\n{vergleichstext(text)}".encode("utf-8")).hexdigest()[:8]


def eigene_nachrichten(con, chat: dict, teil: dict, seit_unix: float, buch: dict, cfg: dict) -> list:
    """Eigene Nachrichten seit seit_unix in den Chats der Person oder Gruppe, auch in einem Chat, den die
    Nachrichten-App für dieselbe Adresse neu angelegt hat (Rückfall auf participant)."""
    ids = set(chat["ids"])
    if teil["adresse"]:
        ids |= {r for (r,) in con.execute("SELECT ROWID FROM chat WHERE chat_identifier = ?", (teil["adresse"],))}
    return nachrichten(con, {i: chat for i in ids}, buch, cfg, seit=seit_unix - APPLE_EPOCH, nur_ich=True,
                       aufsteigend=True)


def ziel_aufloesen(con, cfg: dict, a: argparse.Namespace, buch: dict) -> dict:
    """Ziel für draft und send: nur eindeutig (strikt), nie an Dienste."""
    chat = finde_chat(lade_chats(con, cfg, buch), a.chat, a.id, strikt=True, versteckt=versteckte_arten(cfg))
    if chat["art"] == "dienst":
        sys.exit(f"An Dienste ({chat['name']}) sendet das Kit nicht, sie nehmen meist keine Antworten an. Nichts "
                 "gesendet.")
    return chat


def osascript(skript: str, *argumente: str):
    """AppleScript über stdin, Argumente als argv (nie in den Quelltext eingesetzt). (Exit-Code, Fehlernummer) ohne
    den Text der Meldung, denn der enthält die Chat-GUID mit der Nummer."""
    try:
        r = subprocess.run([OSASCRIPT_BEFEHL, "-", *argumente], input=skript, capture_output=True, text=True,
                           timeout=OSASCRIPT_ZEIT)
    except FileNotFoundError:
        sys.exit("osascript nicht gefunden. Das Kit läuft nur auf macOS. Nichts gesendet.")
    except subprocess.TimeoutExpired:
        return None, "zeit"  # vielleicht gesendet: der Aufrufer meldet Exit 3 mit dem Chat
    nummer = re.search(r"\((-?\d+)\)\s*$", r.stderr.strip())
    return r.returncode, (nummer.group(1) if nummer else "")


AS_CHAT = """on run argv
\ttell application "Messages"
\t\tsend (item 1 of argv) to chat id (item 2 of argv)
\tend tell
end run
"""
AS_PERSON = """on run argv
\ttell application "Messages"
\t\tif (item 3 of argv) is "SMS" then
\t\t\tset konto to first account whose service type is SMS
\t\telse
\t\t\tset konto to first account whose service type is iMessage
\t\tend if
\t\tsend (item 1 of argv) to participant (item 2 of argv) of konto
\tend tell
end run
"""


def cmd_draft(cfg: dict, a: argparse.Namespace) -> None:
    text = text_aus(a, cfg)
    buch = lade_buch(cfg)
    with snapshot(cfg) as con:
        chat = ziel_aufloesen(con, cfg, a, buch)
    teil = ziel_teil(chat, a.id)
    vorlage = block(cfg).get("entwurf_link", "")
    if a.dry_run:
        code = pruefcode(teil, text)
        print(f"Trockenlauf, nichts geöffnet und nichts gesendet. Ziel: {ziel_text(chat, teil)}, Dienst "
              f"{dienst_von(teil)}. Prüfcode {code}.")
        print(f"Text ({len(text)} Zeichen): {bereinige(text)}")
        quelle = (f"--text-file nachricht.txt --code {code} --anfang {shlex.quote(textanfang(text))}" if a.text_file
                  else "und demselben --text")
        # Name und id: Die Rückfrage zeigt so, an wen, und der Abgleich prüft, dass beide passen (Review 21.10.2026)
        print("Senden nur nach ausdrücklichem senden für genau diesen Text, mit "
              f"{AUFRUF} send {shlex.quote(chat['name'])} --id {teil['rowid']} {quelle} (Rückfrage).")
        return
    if not vorlage:
        sys.exit("Nicht geöffnet: Ein Entwurf mit Text in der Nachrichten-App ist auf diesem Mac nicht getestet "
                 "(imessage.entwurf_link in config.json ist leer). Den Text zum Kopieren geben oder nach senden mit "
                 "send schicken.")
    if chat["art"] != "person" or not teil["adresse"]:
        sys.exit("Nicht geöffnet: Gruppen lassen sich per Link nicht öffnen. Den Text zum Kopieren geben oder nach "
                 "senden mit send schicken.")
    url = vorlage.replace("{adresse}", urllib.parse.quote(teil["adresse"], safe="+@")).replace(
        "{text}", urllib.parse.quote(text, safe=""))
    hintergrund = block(cfg).get("entwurf_im_hintergrund", True)
    befehl = [OPEN_BEFEHL, "-g", url] if hintergrund else [OPEN_BEFEHL, url]
    try:
        r = subprocess.run(befehl, capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):  # nie die Meldung selbst: sie enthält den Link mit Nummer und Text
        sys.exit("Die Nachrichten-App ließ sich nicht öffnen.")
    if r.returncode != 0:
        sys.exit(f"Die Nachrichten-App ließ sich nicht öffnen (Fehlercode {r.returncode}).")
    if a.text_file:
        NACHRICHT_DATEI.unlink(missing_ok=True)
    print(f"Entwurf für {ziel_text(chat, teil)} in Nachrichten geöffnet{' im Hintergrund' if hintergrund else ''}, "
          f"{len(text)} Zeichen. Gesendet wird nur, wenn du in Nachrichten selbst Enter drückst.")


def cmd_send(cfg: dict, a: argparse.Namespace) -> None:
    text = text_aus(a, cfg)
    if a.text_file and vergleichstext(a.anfang) != textanfang(text):  # die Rückfrage zeigt den Anfang (Review 21.10.)
        falscher_aufruf(f"Nicht gesendet: --anfang passt nicht zum Anfang von nachricht.txt. Genau die ersten "
                        f"{ANFANG_ZEICHEN} Zeichen nehmen, wie sie der Hinweis von draft --dry-run nennt.")
    buch = lade_buch(cfg)
    erwartet = vergleichstext(text)
    with snapshot(cfg) as con:
        chat = ziel_aufloesen(con, cfg, a, buch)
        teil = ziel_teil(chat, a.id)
        if not {"is_sent", "error"} <= SPALTEN["message"]:  # ohne sie gälte jede Zeile als gesendet (Review 20.10.2026)
            sys.exit("Nicht gesendet: Der Nachrichten-Datenbank fehlen die Spalten für die Sendeprüfung (is_sent, "
                     "error). imessage.py muss angepasst werden.")
        frueher = [m for m in eigene_nachrichten(con, chat, teil, time.time() - DUBLETTE_SEKUNDEN, buch, cfg)
                   if vergleichstext(m["text"]) == erwartet]
    if a.text_file and a.code != pruefcode(teil, text):
        sys.exit("Nicht gesendet: Der Code passt nicht, Text oder Ziel haben sich seit der Vorschau geändert. Erst "
                 "draft --dry-run mit derselben id, dann send mit dessen --code und --anfang.")
    dienst = dienst_von(teil)
    if frueher and not a.nochmal:
        sys.exit(f"Nicht gesendet: Derselbe Text ging um {zeit(frueher[-1]['ts'])} schon an {chat['name']}. Erneut nur "
                 "mit --nochmal, wenn der Nutzer das ausdrücklich will.")
    print(f"Sende an {ziel_text(chat, teil)} über {dienst}, {len(text)} Zeichen: {bereinige(text)}")
    start = time.time()
    code, nummer = osascript(AS_CHAT, text, teil["guid"])
    weg = "Chat"
    if code != 0 and nummer == "-1728" and chat["art"] == "person" and teil["adresse"]:
        code, nummer = osascript(AS_PERSON, text, teil["adresse"], dienst)  # GUID mit any, Rückfall (Plugin-Issue 1678)
        weg = "Adresse"
    if code is None:  # Zeitüberschreitung: vielleicht gesendet
        print(f"Nicht bestätigt: Die Nachrichten-App hat nach {OSASCRIPT_ZEIT} s nicht geantwortet. Ob die Nachricht "
              "rausging, zeigt "
              f"{AUFRUF} read --id {teil['rowid']} --limit 3. Nicht erneut senden, bevor das geklärt ist.")
        sys.exit(EXIT_OFFEN)
    if code != 0:
        if nummer == "-1743":
            sys.exit("Nicht gesendet: Die Automation für Nachrichten ist nicht erlaubt. Systemeinstellungen > "
                     "Datenschutz & Sicherheit > Automation: der App, aus der Claude läuft, Nachrichten erlauben.")
        if nummer in ("-600", "-10810"):
            sys.exit("Nicht gesendet: Die Nachrichten-App war nicht erreichbar, vermutlich lief der Befehl in der "
                     f"Sandbox. Als eigenen Befehl mit absolutem Pfad aufrufen: {AUFRUF} send --id {teil['rowid']} "
                     "mit demselben Text, ohne cd, Pipe oder Umleitung.")
        sys.exit(f"Nicht gesendet: AppleScript-Fehler {nummer or code} beim Senden an {chat['name']} ({weg}).")
    status, m = "fehlt", None
    try:  # nach dem Senden nie Exit 1: das läse sich wie ein Fehlschlag, und eine Wiederholung sendete doppelt
        for warten in PRUEF_WARTEN:
            time.sleep(warten)
            with snapshot(cfg) as con:
                treffer = [x for x in eigene_nachrichten(con, chat, teil, start - 5, buch, cfg)
                           if vergleichstext(x["text"]) == erwartet]
            if treffer:
                m = treffer[-1]
                status = "fehler" if m["fehler"] else ("gesendet" if m["gesendet"] or m["zugestellt"] else "offen")
                if status != "offen":
                    break
    except (Exception, SystemExit):
        status = "unklar"
    if status == "gesendet":
        if a.text_file:
            NACHRICHT_DATEI.unlink(missing_ok=True)
        print(f"Gesendet an {chat['name']} über {m['dienst'] or dienst}, in der Nachrichten-Datenbank bestätigt "
              f"({zeit(m['ts'])}" + (", zugestellt" if m["zugestellt"] else "")
              + (", über die Adresse nach Fehler -1728 mit der Chat-GUID" if weg == "Adresse" else "") + ").")
        return
    if status == "fehler":
        print(f"Nicht zugestellt: Die Nachricht an {chat['name']} steht mit Fehler {m['fehler']} in der "
              "Nachrichten-Datenbank (rotes Ausrufezeichen in der App). Nicht automatisch erneut senden.")
        sys.exit(EXIT_FEHLER)
    grund = {"offen": "steht in der Datenbank, ist aber noch nicht gesendet",
             "unklar": "ließ sich in der Datenbank nicht prüfen",
             "fehlt": "ist nach 20 Sekunden nicht in der Datenbank erschienen"}[status]
    print(f"Nicht bestätigt: Die Nachricht an {chat['name']} {grund}. AppleScript meldet Erfolg auch bei "
          f"gescheiterten Sendungen. In Nachrichten nachsehen oder später {AUFRUF} read --id {teil['rowid']} --limit 3. "
          "Nicht erneut senden, bevor das geklärt ist.")
    sys.exit(EXIT_OFFEN)


def main() -> None:
    fange_signale()
    p = argparse.ArgumentParser(
        description="iMessage und SMS (Nachrichten-App am Mac): lesen, suchen, Neues sichten, senden nach Freigabe.",
        formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    def befehl(name, hilfe):  # ohne Abkürzungen: --ignore darf nie als --ignore-style gelten
        return sub.add_parser(name, help=hilfe, allow_abbrev=False)

    befehl("check", "Zugriff, Datenbank und Adressbuch prüfen (nur Zahlen)")

    c = befehl("chats", "Chats nach letzter Aktivität (Standard: letzte 30 Tage)")
    c.add_argument("--days", type=positiv(float), help="Zeitraum für die Nachrichtenzahl in Tagen")
    c.add_argument("--query", action="append",
                   help="nur Chats, deren Name passt (auch ohne Aktivität), mehrfach möglich: je Name ein Block")
    c.add_argument("--kind", choices=sorted(ARTEN), help="nur diese Art")
    c.add_argument("--sort", choices=["aktiv", "anzahl"], default="aktiv", help="nach letzter Nachricht oder Anzahl")
    c.add_argument("--limit", type=positiv(int), help="höchstens so viele Zeilen")
    c.add_argument("--all", action="store_true", help="auch Dienste (SMS von Firmen, Kurzwahlen)")

    mb = befehl("members", "Mitglieder einer Gruppe, nur Namen")
    mb.add_argument("chat", nargs="?", help="Gruppenname oder Teil davon")
    mb.add_argument("--id", type=int, help="Chat-id statt Name")

    t = befehl("triage", "Neues der letzten Stunden, Einzelchats mit neuer Nachricht zuerst")
    t.add_argument("hours", nargs="?", type=positiv(float), help="Zeitraum in Stunden (Standard aus config.json)")
    t.add_argument("--max-chars", type=positiv(int))

    r = befehl("read", "Verlauf eines Chats, neueste Nachrichten")
    r.add_argument("chat", nargs="?", help="Chatname oder Teil davon")
    r.add_argument("--id", type=int, help="Chat-id aus chats, triage oder search")
    r.add_argument("--days", type=positiv(float), help="nur die letzten N Tage")
    r.add_argument("--since", help="ab Datum (JJJJ-MM-TT)")
    r.add_argument("--before", help="nur Nachrichten vor diesem Zeitpunkt (JJJJ-MM-TT HH:MM)")
    r.add_argument("--before-id", type=positiv(int, ID_MAX),
                   help="nur Nachrichten vor dieser Nachricht (zum Weiterlesen, id aus dem Hinweis)")
    r.add_argument("--limit", type=positiv(int), help="höchstens N Nachrichten (Standard aus config.json)")
    r.add_argument("--max-chars", type=positiv(int))
    r.add_argument("--system", action="store_true", help="auch Gruppenereignisse")
    r.add_argument("--all", action="store_true", help="auch Dienste (SMS von Firmen, Codes), nur auf Nachfrage")

    s = befehl("search", "Volltextsuche, alle Begriffe müssen vorkommen")
    s.add_argument("terms", nargs="+", help="Suchbegriffe")
    s.add_argument("--chat", help="nur in diesem Chat")
    s.add_argument("--days", type=positiv(float), help="Zeitraum in Tagen (Standard aus config.json)")
    s.add_argument("--limit", type=positiv(int))
    s.add_argument("--from-me", action="store_true", help="nur eigene Nachrichten")
    s.add_argument("--all", action="store_true", help="auch Dienste")
    s.add_argument("--max-chars", type=positiv(int))

    for name, hilfe in (("draft", "Vorschau (--dry-run), Entwurf in der App nur mit getestetem Link"),
                        ("send", "Nachricht senden, danach Sendeprüfung (der Server fragt immer nach)")):
        d = befehl(name, hilfe)
        d.add_argument("chat", nargs="?", help="Chatname, muss eindeutig sein")
        d.add_argument("--id", type=int, help="Chat-id aus read, triage oder chats")
        d.add_argument("--text", help="Text direkt (für kurze Nachrichten, steht dann auch in der Rückfrage)")
        d.add_argument("--text-file", help="nur nachricht.txt im Kit-Ordner, wird nach Erfolg gelöscht")
        d.add_argument("--ignore-style", action="store_true", help="verbotene Zeichen bewusst zulassen")
        if name == "draft":
            d.add_argument("--dry-run", action="store_true", help="nur zeigen, nichts öffnen und nichts senden")
        else:
            d.add_argument("--nochmal", action="store_true", help="denselben Text innerhalb von 10 Minuten erneut")
            d.add_argument("--code", help="Prüfcode aus draft --dry-run, Pflicht mit --text-file")
            d.add_argument("--anfang", help=f"die ersten {ANFANG_ZEICHEN} Zeichen des Textes wie in draft --dry-run, "
                                            "Pflicht mit --text-file")

    # --ignore-style nur direkt hinter dem Skript
    vorn, rest = kit_basis.schalter_vorn(sys.argv[1:], ("--ignore-style",))
    a = p.parse_args(rest + vorn)
    if a.cmd in ("draft", "send") and bool(a.text) == bool(a.text_file):
        p.error(f"{a.cmd} braucht genau eins von --text oder --text-file")
    if a.cmd == "send" and a.text_file and not (a.code and a.anfang):  # Review 21.10.2026: falscher Aufruf, Exit 2
        p.error("send mit --text-file braucht --code aus draft --dry-run und --anfang, sonst ist die Rückfrage an "
                "keinen Text gebunden")
    if a.cmd == "read" and a.before and a.before_id is not None:  # Schalterkonflikte: Exit 2 wie jeder falsche Aufruf
        p.error("read nimmt nur eins von --before und --before-id")
    if a.cmd == "read" and a.days is not None and a.since:
        p.error("read nimmt nur eins von --days und --since")
    cfg = lade_config()
    befehle = {"check": cmd_check, "chats": cmd_chats, "members": cmd_members, "triage": cmd_triage, "read": cmd_read,
               "search": cmd_search, "draft": cmd_draft, "send": cmd_send}
    try:
        befehle[a.cmd](cfg, a)
    except sqlite3.DatabaseError as e:
        sys.exit(f"Datenbank-Kopie nicht lesbar ({e}). Erneut versuchen, die Nachrichten-App schreibt eventuell gerade.")


if __name__ == "__main__":
    kit_basis.starten(main, __file__)
