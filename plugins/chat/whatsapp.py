#!/usr/bin/env python3
"""WhatsApp (Mac-App) vom Terminal aus: Chats lesen, durchsuchen, Neues sichten, Entwürfe öffnen.

Das Skript liest die lokale Datenbank der WhatsApp-App. Nur lesend: Datenbank und WAL kommen als Kopie in einen
privaten Temp-Ordner, von dort sofort in eine Datenbank im Speicher, dann wird die Kopie gelöscht. Keine Cloud, keine
inoffizielle API, kein Zugriff auf das Konto. Senden kann das Kit nicht: `draft` öffnet den Chat mit vorbereitetem
Text, abgeschickt wird nur mit Enter in WhatsApp.

Befehle:
  check    Zugriff und Datenbank prüfen
  chats    Chats nach letzter Aktivität, mit Nachrichtenzahl im Zeitraum
  members  Mitglieder einer Gruppe, nur Namen
  triage   Neues der letzten Stunden, Einzelchats mit neuer Nachricht zuerst
  read     Verlauf eines Chats
  search   Volltextsuche in Nachrichten und Bildunterschriften
  draft    Entwurf im Chat öffnen (sendet nie)
  style    eigene Nachrichten als Grundlage für das Stilprofil (nur Ausgabe, keine Datei)

Jeder Befehl kennt --help.

Gelernte Fallstricke, die hier eingebaut sind:
- Die App schreibt laufend ins WAL (ChatStorage.sqlite-wal). Ohne diese Datei fehlen die
  neuesten Nachrichten. Kopiert werden Datenbank und WAL, nie die -shm-Datei.
- Schreibt die App während des Kopierens, passen die Teile nicht zusammen. Größe und
  Änderungszeit werden vor und nach dem Kopieren verglichen, sonst neuer Versuch.
- Die Dateikopie lebt nur, bis das Backup im Speicher liegt. SIGTERM, SIGINT und SIGHUP räumen sie auf, Reste eines
  harten Abbruchs löscht der nächste Aufruf.
- Zeitstempel zählen ab 2001-01-01 (Apple-Epoche), nicht ab 1970. Zeiträume rechnen in Sekunden ab jetzt, nie über
  die Wanduhr, sonst verschiebt die Zeitumstellung sie um eine Stunde.
- Weiterlesen läuft über die id der ältesten gezeigten Nachricht (--before-id), nie über eine Uhrzeit: Nachrichten
  in derselben Sekunde, in der doppelten Stunde der Umstellung oder hinter einer Kürzung gehen so nicht verloren.
- Angepinnte Chats tragen in ZLASTMESSAGEDATE ein Datum in ferner Zukunft. Die letzte
  Aktivität kommt deshalb aus ZWAMESSAGE.
- Neuere Chats haben eine LID (@lid) statt einer Telefonnummer. Die Nummer für den Entwurf
  kommt dann aus ContactsV2.sqlite, sonst gibt es keinen direkten Link.
- Namensfelder in ZWAGROUPMEMBER und ZWAMESSAGE.ZPUSHNAME sind kodiert. Anzeigenamen kommen aus dem
  Adressbuch der App (ContactsV2.sqlite) und aus ZWAPROFILEPUSHNAME.
- Erwähnungen stehen im Text als @Nummer oder @LID. Ausgegeben wird @Name oder @[Kontakt], nie die Ziffern.
- Standorte und Kontaktkarten enthalten Koordinaten und Telefonnummern. Ausgegeben wird nur
  der Typ, bei Kontaktkarten der Name.
- Nachrichten können Steuerzeichen enthalten (Terminal-Escapes, Richtungswechsel), Zeilentrenner (U+2028) und
  ungültiges UTF-8. Steuerzeichen fallen weg, Zeilentrenner zählen als Umbruch, kaputte Bytes werden ersetzt.
- Chat- und Gruppennamen wählt jeder Admin. In Ausgaben sind sie auf 60 Zeichen gekürzt und eckige Klammern werden
  runde, damit ein Name keine Hinweise des Skripts nachahmt.
- draft ist ohne Rückfrage freigegeben. --text-file liest darum nur nachricht.txt im Kit-Ordner,
  sonst könnte eine untergeschobene Anweisung beliebige Dateien in einen Entwurf holen.
- open -g schreibt den Entwurf auch im Hintergrund in den Chat (getestet am 28.09.2026 bei geöffneter App). Deshalb
  ist entwurf_im_hintergrund an, auch wenn der Schlüssel in config.json fehlt: Ein Enter in der Claude-App kann so nie
  in WhatsApp landen.
- Lief WhatsApp nicht, startete der Link die App, aber der Text kam nicht im Chat an, obwohl open Erfolg meldete
  (Befund 26.11.2026). draft startet WhatsApp darum vorher im Hintergrund und wartet, bis die App in ihre Datenbank
  schreibt (höchstens START_WARTEN Sekunden). Ob der Text im Chat steht, kann das Kit nicht nachsehen: Die Ausgabe sagt
  übergeben, nicht geöffnet.
- Gruppen und Kontakte ohne Nummer öffnet ein Link nur über die Chat-Auswahl von WhatsApp. Der Weg blieb ungetestet,
  draft öffnet sie nicht, der Text geht zum Kopieren an den Nutzer.
- ZHIDDEN gilt als versteckter oder gesperrter Chat. Ob die Chat-Sperre dort landet, ist nicht belegt, der Test
  entfiel am 28.09.2026 (Entscheidung Lucas).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import statistics
import subprocess
import sys
import time
import urllib.parse
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path

import kit_basis  # schalter_vorn, gleich in apple und chat
# Bausteine für Ausgabe, Sicherheit, Chatsuche und Datenbank-Kopie, gemeinsam mit iMessage
from nachricht_basis import (APPLE_EPOCH, DATEN_HINWEIS, ID_MAX, LANGE_ZEILE, LINK, SMILEY, STEUERZEICHEN, STRICHE,
                             TELEFON, TEXT_MAX, ZEILENTRENNER, absender, als_text, anzeigename, apple, auswahl,
                             bereinige, config_fehler, drucke, entwurfstext, erwaehnt, falscher_aufruf, falte,
                             fange_signale, fundstelle, kopie_ordner, kopiere_db, kuerze, maskiere,
                             norm, positiv, raeume_alte_kopien_auf, standard, starte_app, startzeile, text_utf8,
                             treffer_je_name,
                             varianten, varianten_suche, verbotene_zeichen, vor_sekunden, wert, zeit, zeitpunkt)
from nachricht_basis import finde_chat as _finde_chat
from nachricht_basis import lade_config as _lade_config

KIT_DIR = Path(__file__).resolve().parent
DATEN_DIR = kit_basis.datenordner(KIT_DIR)  # fester Ordner vom MCP-Server, sonst der Plugin-Ordner
CONFIG_PATH = DATEN_DIR / "config.json"
NACHRICHT_DATEI = DATEN_DIR / "nachricht.txt"  # einzige Entwurfsdatei, draft löscht sie nach dem Öffnen
# Absolut, nie über PATH: ein fremdes open davor bekäme sonst jeden Entwurf (Prüfung 20.10.2026). Tests setzen in ihrer
# Kopie des Skripts einen Ersatz ein, eine Umgebungsvariable gibt es nicht
OPEN_BEFEHL = "/usr/bin/open"
PGREP_BEFEHL = "/usr/bin/pgrep"
APP_PROZESS, APP_ID = "WhatsApp", "net.whatsapp.WhatsApp"
START_WARTEN = 15  # Sekunden höchstens, bis WhatsApp nach einem Kaltstart bereit ist
START_RUHE = 2     # Sekunden nach dem ersten Schreiben in die Datenbank, bis der Link kommt
STANDARD_ORDNER = "~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared"
KEIN_ZUGRIFF = (
    "Kein Zugriff auf die WhatsApp-Daten. Zwei mögliche Ursachen: "
    "1. Der Festplattenvollzugriff fehlt für die App, aus der Claude läuft (Systemeinstellungen > Datenschutz & "
    "Sicherheit > Festplattenvollzugriff, danach die App neu starten). "
    "2. Der Befehl lief in der Sandbox, etwa wegen cd im selben Befehl, einer Pipe oder Umleitung. Dann als eigenen "
    f'Befehl mit absolutem Pfad aufrufen: python3 "{KIT_DIR / "whatsapp.py"}" <befehl>, ohne cd davor und ohne | '
    "oder >."
)
KOPIE_PRAEFIX = "message-kit-"
AUFRUF = f'python3 "{KIT_DIR / "whatsapp.py"}"'  # Folgeaufrufe in Hinweisen immer absolut
STAND_WARNUNG = 3600   # Sekunden ohne Änderung an Datenbank und WAL, ab denen die Ausgabe warnt

ARTEN = {"person": "Person", "gruppe": "Gruppe", "community": "Community", "broadcast": "Broadcast",
         "status": "Status", "kanal": "Kanal"}
TEXT_TYPEN = {0, 7}  # Text, Link
EREIGNIS_TYPEN = {6, 10}  # Gruppenereignisse und Systemhinweise
EREIGNIS_SQL = ", ".join(str(t) for t in sorted(EREIGNIS_TYPEN))
MEDIEN = {1: "Bild", 2: "Video", 3: "Sprachnachricht", 4: "Kontaktkarte", 5: "Standort", 8: "Dokument",
          11: "GIF", 15: "Sticker", 46: "Umfrage",
          59: "Anruf"}  # Anruf-Hinweis im Chat (belegt: verpasste Sprachanrufe, 28.09.2026). Kein Ereignis, damit triage ihn zeigt
PFLICHT_SPALTEN = {
    "ZWACHATSESSION": {"Z_PK", "ZCONTACTJID", "ZPARTNERNAME", "ZSESSIONTYPE", "ZARCHIVED", "ZHIDDEN",
                       "ZREMOVED", "ZSAVEDINPUT"},
    "ZWAMESSAGE": {"Z_PK", "ZCHATSESSION", "ZMESSAGEDATE", "ZISFROMME", "ZMESSAGETYPE", "ZTEXT",
                   "ZMEDIAITEM", "ZGROUPMEMBER"},
    "ZWAMEDIAITEM": {"Z_PK", "ZTITLE", "ZVCARDNAME"},
    "ZWAGROUPMEMBER": {"Z_PK", "ZCHATSESSION", "ZMEMBERJID", "ZISACTIVE"},
}

EMOJI = re.compile("[\U0001F000-\U0001F3FA\U0001F400-\U0001FAFF☀-➿⬀-⯿]")
ENDE_EMOJI = re.compile("(?:" + EMOJI.pattern + r"|[:;]-?[)(DPp]|\b[xX]D)[\s️‍\U0001F3FB-\U0001F3FF]*$")
NUR_NUMMER = re.compile(r"[+\d\s()/." + STRICHE + r"-]{6,}")  # auch mit geschützten Leerzeichen, wie WhatsApp sie setzt
ERWAEHNUNG = re.compile(r"(?<!\w)@(\d{6,})(?!\d)")  # @Nummer oder @LID im Text einer Nachricht
LACHEN = re.compile(r"\b(?:ha){2,}h?\b|\b(?:he){2,}\b|\blol\b", re.I)


# ---------- Helfer ----------


def pruefe_config(cfg: dict) -> None:
    """Falsche Typen brechen ab: Ein Text statt einer Liste würde Ausschlüsse sonst still unwirksam machen. Die
    gemeinsamen Einstellungen prüft nachricht_basis.config_fehler, hier die von WhatsApp."""
    fehler = config_fehler(cfg)
    arten = cfg.get("hidden_kinds")
    if arten is not None and (not isinstance(arten, list) or not all(isinstance(x, str) for x in arten)):
        fehler.append("hidden_kinds muss eine Liste von Texten sein")
    elif isinstance(arten, list) and set(arten) - set(ARTEN):
        fehler.append(f"hidden_kinds kennt nur {', '.join(sorted(ARTEN))}")
    for k in ("exclude_hidden", "entwurf_im_hintergrund"):
        if k in cfg and not isinstance(cfg[k], bool):
            fehler.append(f"{k} muss true oder false sein")
    if "database_dir" in cfg and not isinstance(cfg["database_dir"], str):
        fehler.append("database_dir muss ein Text sein")
    if fehler:
        sys.exit("config.json: " + ". ".join(fehler) + ". Nichts gelesen.")


def lade_config() -> dict:
    return _lade_config(CONFIG_PATH, pruefe_config)


# ---------- Datenbank-Kopie ----------

DATENSTAND = {"zeit": None}  # letzte Änderung an Datenbank oder WAL in Unix-Sekunden, gesetzt von snapshot


def _kopiere(src: Path, dst: Path):
    """Datenbank und WAL passend zueinander kopieren (nachricht_basis.kopiere_db). Eigener Name im Modul, damit die
    Tests das Kopieren in ihrer Kopie des Skripts ersetzen können."""
    return kopiere_db(src, dst, "WhatsApp")


def pruefe_schema(con: sqlite3.Connection) -> None:
    if con.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone() is None:  # keine Tabelle: kein Schemafehler
        sys.exit("Die WhatsApp-Datenbank ist leer. Ist WhatsApp für Mac angemeldet und synchronisiert? WhatsApp "
                 "öffnen, bis die Chats zu sehen sind, dann erneut versuchen.")
    fehlend = []
    for tabelle, spalten in PFLICHT_SPALTEN.items():
        vorhanden = {r[1] for r in con.execute(f"PRAGMA table_info({tabelle})")}
        fehlend += [tabelle] if not vorhanden else [f"{tabelle}.{s}" for s in sorted(spalten - vorhanden)]
    if fehlend:
        sys.exit("Das Datenbankschema von WhatsApp hat sich geändert, es fehlt: " + ", ".join(fehlend)
                 + ". whatsapp.py muss angepasst werden.")


@contextmanager
def snapshot(cfg: dict):
    """Chat-Datenbank und Adressbuch der App (für Namen und Nummern) als Datenbank im Speicher. Die Dateikopie im
    privaten Temp-Ordner (0700) lebt nur, bis das Backup im Speicher liegt. Das Original wird nur gelesen, Schlüssel
    und andere Datenbanken der App fasst das Kit nie an."""
    raeume_alte_kopien_auf(KOPIE_PRAEFIX)
    quelle = Path(os.path.expanduser(cfg.get("database_dir") or STANDARD_ORDNER))
    con = sqlite3.connect(":memory:")
    con.text_factory = text_utf8
    try:
        try:
            with kopie_ordner(KOPIE_PRAEFIX) as ziel:
                stand = _kopiere(quelle / "ChatStorage.sqlite", ziel / "ChatStorage.sqlite")
                if stand is None:
                    sys.exit(f"WhatsApp-Datenbank nicht gefunden in {quelle}. Ist WhatsApp für Mac installiert und "
                             "angemeldet?")
                DATENSTAND["zeit"] = max(s[1] for s in stand if s) / 1e9
                datei = sqlite3.connect(ziel / "ChatStorage.sqlite")
                try:
                    datei.backup(con)
                finally:
                    datei.close()
                con.execute("ATTACH DATABASE ':memory:' AS kontakte")
                if _kopiere(quelle / "ContactsV2.sqlite", ziel / "ContactsV2.sqlite"):
                    con.execute("ATTACH DATABASE ? AS kontakte_datei", (str(ziel / "ContactsV2.sqlite"),))
                    try:
                        con.execute("CREATE TABLE kontakte.ZWAADDRESSBOOKCONTACT AS "
                                    "SELECT * FROM kontakte_datei.ZWAADDRESSBOOKCONTACT")
                    except sqlite3.Error:
                        pass  # anderes Schema: Namen in Gruppen fehlen dann, Entwürfe haben keinen direkten Link
                    finally:
                        con.execute("DETACH DATABASE kontakte_datei")
        except PermissionError:
            sys.exit(KEIN_ZUGRIFF)
        except OSError as e:  # etwa database_dir ist eine Datei oder der Datenträger ist voll (Prüfung 20.10.2026)
            sys.exit(f"WhatsApp-Daten nicht lesbar ({e.strerror or type(e).__name__}). database_dir in config.json "
                     "und freien Speicherplatz prüfen, dann erneut versuchen.")
        con.execute("PRAGMA query_only = ON")
        pruefe_schema(con)
        yield con
    finally:
        con.close()


def stand_text() -> str:
    t = DATENSTAND["zeit"]
    return f"Datenstand {zeit(t - APPLE_EPOCH)}" if t else "Datenstand unbekannt"


def stand_hinweis() -> str:
    """Warnzeile, wenn Datenbank und WAL seit über einer Stunde unverändert sind, sonst leer."""
    t = DATENSTAND["zeit"]
    if t is None or time.time() - t <= STAND_WARNUNG:
        return ""
    return (f"Achtung: Die WhatsApp-Daten wurden zuletzt {zeit(t - APPLE_EPOCH)} geändert. Ist WhatsApp am Mac "
            "geschlossen, fehlen neuere Nachrichten.")


# ---------- Chats und Nachrichten ----------


def art_von(jid, typ) -> str:
    jid = als_text(jid)
    dom = jid.rsplit("@", 1)[-1]
    if dom == "newsletter" or typ == 5:
        return "kanal"
    if jid.split("@", 1)[0] == "status" or typ == 3:  # echte Kennung: status@broadcast
        return "status"
    if dom == "broadcast" or typ == 2:
        return "broadcast"
    if dom == "g.us":
        return "community" if typ == 4 else "gruppe"
    return "person"


def lade_chats(con: sqlite3.Connection, cfg: dict, tage: float | None = None) -> list:
    """Alle Chats, die das Kit sehen darf: ohne excluded_chats, ohne versteckte oder gesperrte und
    ohne entfernte. Mit letzter Aktivität und Nachrichtenzahl der letzten `tage` Tage."""
    seit = vor_sekunden(tage * 86400) if tage else 1e18
    ausgeschlossen = set(cfg.get("excluded_chats", []))
    # Namen wie bei der Chatsuche vergleichen, auch in Umschrift: ein Ausschluss Mueller trifft Müller (Prüfung 20.10.2026)
    ausgeschlossen_var = set().union(*(varianten(x) for x in ausgeschlossen)) if ausgeschlossen else set()
    versteckte_raus = cfg.get("exclude_hidden", True)
    chats = []
    for pk, jid, name, typ, archiviert, versteckt, entwurf, erste, letzte, n, n_ich in con.execute(f"""
            SELECT s.Z_PK, s.ZCONTACTJID, s.ZPARTNERNAME, s.ZSESSIONTYPE, COALESCE(s.ZARCHIVED, 0),
                   COALESCE(s.ZHIDDEN, 0), COALESCE(length(s.ZSAVEDINPUT), 0) > 0,
                   a.erste, a.letzte, COALESCE(a.n, 0), COALESCE(a.n_ich, 0)
            FROM ZWACHATSESSION s
            LEFT JOIN (SELECT ZCHATSESSION, MIN(ZMESSAGEDATE) AS erste, MAX(ZMESSAGEDATE) AS letzte,
                              SUM(ZMESSAGEDATE >= :seit) AS n, SUM(ZMESSAGEDATE >= :seit AND ZISFROMME = 1) AS n_ich
                       FROM ZWAMESSAGE WHERE ZMESSAGETYPE NOT IN ({EREIGNIS_SQL}) GROUP BY ZCHATSESSION) a
                   ON a.ZCHATSESSION = s.Z_PK
            WHERE COALESCE(s.ZREMOVED, 0) = 0""", {"seit": seit}):
        jid = als_text(jid)
        voll = bereinige(name)
        namen = varianten(voll) | varianten(anzeigename(voll))  # roh und wie in der Ausgabe ([System], über 60 Zeichen)
        if jid in ausgeschlossen or (voll and namen & ausgeschlossen_var) or (versteckt and versteckte_raus):
            continue
        if not voll or NUR_NUMMER.fullmatch(voll):
            voll = "(Nummer ohne Namen)"  # keine Telefonnummern ausgeben
            namen = varianten(voll)
        chats.append({"id": pk, "jid": jid, "name": anzeigename(voll), "art": art_von(jid, typ),
                      "archiviert": bool(archiviert), "entwurf": bool(entwurf), "erste": erste, "letzte": letzte,
                      "n": n, "n_ich": n_ich, "varianten": namen})
    return chats


def versteckte_arten(cfg: dict) -> set:
    return set(cfg.get("hidden_kinds", ["status", "kanal", "broadcast", "community"]))


def sichtbar(chats: list, cfg: dict, alle: bool = False) -> list:
    """Ohne die Chat-Arten aus hidden_kinds (Status, Kanäle, Broadcasts, Communities)."""
    aus = set() if alle else versteckte_arten(cfg)
    return [c for c in chats if c["art"] not in aus]


def finde_chat(chats: list, anfrage: str | None, chat_id: int | None = None, strikt: bool = False,
               versteckt: set = frozenset(), nur_gruppen: bool = False) -> dict:
    """Chat per id oder Name (nachricht_basis.finde_chat mit den Arten und dem Aufruf von WhatsApp)."""
    return _finde_chat(chats, anfrage, chat_id, strikt, versteckt, nur_gruppen, ARTEN, AUFRUF)


_NAMEN: dict = {}


def kodiert(v: str) -> bool:
    """Manche Namensfelder legt WhatsApp kodiert ab (Base64). Die taugen nicht als Anzeige. Kodiert heißt: nur
    Base64-Zeichen und dazu = am Ende, ein + vorn ohne Kleinbuchstaben oder ab 8 Zeichen Ziffern mit mindestens drei
    Großbuchstaben. Echte kurze Namen wie JJ, Chr, Anna+Tom oder AC/DC bleiben."""
    if not re.fullmatch(r"[A-Za-z0-9+/]+=*", v):
        return False
    if v.endswith("=") or (v.startswith("+") and not any(ch.islower() for ch in v)):
        return True
    return (len(v) >= 8 and any(ch.isdigit() for ch in v) and any(ch.islower() for ch in v)
            and sum(ch.isupper() for ch in v) >= 3)


def namensbuch(con: sqlite3.Connection) -> dict:
    """JID -> Anzeigename. Adressbuch der App zuerst, sonst der selbst gewählte WhatsApp-Name mit ~ davor,
    wie WhatsApp ihn bei Unbekannten zeigt. Nummern und kodierte Felder nie."""
    if id(con) not in _NAMEN:
        namen = {}
        for sql, vorsatz in (("SELECT ZJID, NULL, ZPUSHNAME FROM ZWAPROFILEPUSHNAME", "~"),
                             ("SELECT ZLID, ZWHATSAPPID, ZFULLNAME FROM kontakte.ZWAADDRESSBOOKCONTACT", "")):
            try:
                rows = con.execute(sql).fetchall()
            except sqlite3.Error:  # Tabelle fehlt oder Kontakte nicht kopiert
                continue
            for jid1, jid2, name in rows:
                name = bereinige(name)
                if name and not NUR_NUMMER.fullmatch(name) and not kodiert(name):
                    namen.update({als_text(jid): vorsatz + anzeigename(name) for jid in (jid1, jid2) if jid})
        _NAMEN[id(con)] = namen
    return _NAMEN[id(con)]


def erwaehnungen(text: str, namen: dict) -> str:
    """@Nummer oder @LID durch @Name ersetzen, unbekannte durch @[Kontakt]. Die Ziffern erscheinen nie."""
    def ersetze(m):
        d = m.group(1)
        name = namen.get(f"{d}@s.whatsapp.net") or namen.get(f"{d}@lid")
        return "@" + name if name else "@[Kontakt]"
    return ERWAEHNUNG.sub(ersetze, text)


NACHRICHT_SQL = """
    SELECT m.Z_PK, m.ZCHATSESSION, m.ZMESSAGEDATE, m.ZISFROMME, m.ZMESSAGETYPE, m.ZTEXT, mi.ZTITLE, mi.ZVCARDNAME,
           gm.ZMEMBERJID
    FROM ZWAMESSAGE m
    LEFT JOIN ZWAMEDIAITEM mi ON mi.Z_PK = m.ZMEDIAITEM
    LEFT JOIN ZWAGROUPMEMBER gm ON gm.Z_PK = m.ZGROUPMEMBER
"""


def nachrichten(con, chat_ids, seit=None, bis=None, limit=None, system=False, nur_ich=False, bedingung="",
                werte=(), aufsteigend=False, vor=None, passt=None) -> list:
    """Nachrichten der Chats, neueste zuerst (aufsteigend: älteste zuerst). vor=(Zeitstempel, id): nur ältere als diese
    Nachricht, bei gleicher Sekunde entscheidet die id. passt: Filter in Python, gelesen wird dann nur bis zum Limit."""
    wo = ["m.ZCHATSESSION IN (SELECT value FROM json_each(?))"]
    params = [json.dumps(list(chat_ids))]
    if seit is not None:
        wo.append("m.ZMESSAGEDATE >= ?")
        params.append(seit)
    if bis is not None:
        wo.append("m.ZMESSAGEDATE < ?")
        params.append(bis)
    if vor is not None:
        wo.append("(m.ZMESSAGEDATE < ? OR (m.ZMESSAGEDATE = ? AND m.Z_PK < ?))")
        params += [vor[0], vor[0], vor[1]]
    if not system:
        wo.append(f"m.ZMESSAGETYPE NOT IN ({EREIGNIS_SQL})")
    if nur_ich:
        wo.append("m.ZISFROMME = 1")
    if bedingung:
        wo.append(bedingung)
        params += list(werte)
    richtung = "ASC" if aufsteigend else "DESC"
    sql = NACHRICHT_SQL + " WHERE " + " AND ".join(wo) + f" ORDER BY m.ZMESSAGEDATE {richtung}, m.Z_PK {richtung}"
    if limit and passt is None:
        sql += " LIMIT ?"
        params.append(limit)
    namen = namensbuch(con)
    aus = []
    for r in con.execute(sql, params):
        m = {"id": r[0], "chat": r[1], "ts": r[2], "ich": bool(r[3]), "typ": r[4],
             "text": erwaehnungen(als_text(r[5]), namen) if r[5] is not None else None,
             "titel": erwaehnungen(als_text(r[6]), namen) if r[6] is not None else None,
             "vcard": als_text(r[7]) if r[7] is not None else None,
             "absender": namen.get(als_text(r[8])) if r[8] else None}
        if passt is not None and not passt(m):
            continue
        aus.append(m)
        if limit and len(aus) >= limit:
            break
    return aus


def inhalt(m: dict) -> str:
    typ = m["typ"]
    if typ in TEXT_TYPEN:
        return bereinige(m["text"]) or "[leer]"
    if typ in EREIGNIS_TYPEN:
        return ("[Ereignis] " + bereinige(m["text"])).strip()
    art = MEDIEN.get(typ)
    if art is None:
        return f"[sonstiger Inhalt, Typ {typ}]"  # Typnummer hilft, MEDIEN gezielt zu ergänzen
    if typ == 4:  # nur der Name, nie die Nummern der Karte
        name = anzeigename(TELEFON.sub("", bereinige(m["vcard"])).strip())
        return f"[Kontaktkarte: {name}]" if name else "[Kontaktkarte]"
    if typ == 5:  # keine Koordinaten
        return "[Standort]"
    zusatz = bereinige(m["titel"] or (m["text"] if typ == 8 else ""))
    return f"[{art}] {zusatz}".strip()


def zeile(m: dict, chat: dict, cfg: dict, mit_chat: bool = False, laenge: int = 0) -> str:
    text = inhalt(m)
    text = kuerze(text, laenge) if laenge else text
    return f"{zeit(m['ts'])} | " + (f"{chat['name']} | " if mit_chat else "") + f"{absender(m, chat, cfg)}: {text}"


# ---------- Befehle ----------


def cmd_check(cfg: dict, a: argparse.Namespace) -> None:
    with snapshot(cfg) as con:
        chats = lade_chats(con, cfg)
        alle = con.execute("SELECT ZCONTACTJID, ZPARTNERNAME FROM ZWACHATSESSION WHERE COALESCE(ZREMOVED, 0) = 0"
                           ).fetchall()
        n, neueste = con.execute("SELECT COUNT(*), MAX(ZMESSAGEDATE) FROM ZWAMESSAGE "
                                 "WHERE ZCHATSESSION IN (SELECT value FROM json_each(?))",
                                 (json.dumps([c["id"] for c in chats]),)).fetchone()  # ohne ausgeschlossene Chats
        try:
            kontakte = con.execute("SELECT COUNT(*) FROM kontakte.ZWAADDRESSBOOKCONTACT").fetchone()[0]
        except sqlite3.Error:
            kontakte = None
    ausschluesse = cfg.get("excluded_chats", [])
    jids = {als_text(j) for j, _ in alle}
    namen = set().union(*(varianten(bereinige(nm)) for _, nm in alle)) if alle else set()
    tot = sum(1 for x in ausschluesse if x not in jids and not (varianten(x) & namen))
    print(f"OK: Zugriff auf WhatsApp. {len(chats)} Chats sichtbar, {n} Nachrichten, neueste {zeit(neueste)}. "
          f"{stand_text()}.")
    print(f"Nicht sichtbar: {len(alle) - len(chats)} Chats (excluded_chats: {len(ausschluesse)} Einträge"
          + (f", davon {tot} ohne passenden Chat, umbenannt oder vertippt" if tot else "")
          + f", versteckte oder gesperrte Chats {'ausgeblendet' if cfg.get('exclude_hidden', True) else 'sichtbar'}).")
    print("Kontakte der App (Namen in Gruppen, Entwürfe): " + (f"{kontakte} Einträge" if kontakte is not None else
          "nicht lesbar. Absender in Gruppen erscheinen dann als [unbekannt], Entwürfe haben keinen direkten Link."))
    if not Path("/Applications/WhatsApp.app").exists():
        print("Hinweis: /Applications/WhatsApp.app fehlt, Entwürfe lassen sich nicht öffnen.")
    if stand_hinweis():
        print(stand_hinweis())


def cmd_chats(cfg: dict, a: argparse.Namespace) -> None:
    tage = wert(a.days, cfg, "chats_days", 30)
    with snapshot(cfg) as con:
        chats = sichtbar(lade_chats(con, cfg, tage=tage), cfg, a.all)
        mitglieder = dict(con.execute("SELECT ZCHATSESSION, SUM(COALESCE(ZISACTIVE, 1)) FROM ZWAGROUPMEMBER GROUP BY 1"))
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
            art = ARTEN[c["art"]] + (f", {mitglieder.get(c['id'], 0)} Mitglieder" if c["art"] == "gruppe" else "")
            hinweise = [h for h, an in (("archiviert", c["archiviert"]),
                                        ("neu im Zeitraum", (c["erste"] or 0) >= grenze),
                                        ("ungesendeter Text", c["entwurf"])) if an]
            print(f"{c['id']} | {c['name']} | {art} | {zeit(c['letzte'])} | {c['n']} ({c['n_ich']}) | "
                  f"{', '.join(hinweise)}")

    namen = list(dict.fromkeys(a.query or []))
    if len(namen) > 1:  # je Name ein Block
        print(f"{len(namen)} Namen gesucht. {DATEN_HINWEIS}")
        if stand_hinweis():
            print(stand_hinweis())
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
    if stand_hinweis():
        print(stand_hinweis())
    tabelle(chats)


def cmd_members(cfg: dict, a: argparse.Namespace) -> None:
    with snapshot(cfg) as con:
        chat = finde_chat(lade_chats(con, cfg), a.chat, a.id, versteckt=versteckte_arten(cfg), nur_gruppen=True)
        if chat["art"] not in ("gruppe", "community"):
            sys.exit(f"'{chat['name']}' ist keine Gruppe.")
        rows = con.execute("SELECT ZMEMBERJID FROM ZWAGROUPMEMBER WHERE ZCHATSESSION = ? "
                           "AND COALESCE(ZISACTIVE, 1) = 1", (chat["id"],)).fetchall()
        buch = namensbuch(con)
    namen = [buch.get(als_text(jid)) for (jid,) in rows]
    ohne = namen.count(None)
    namen = sorted({n for n in namen if n}, key=norm)
    print(f"{chat['name']} ({ARTEN[chat['art']]}, id {chat['id']}): {len(rows)} Mitglieder"
          + (f", davon {ohne} ohne gespeicherten Namen" if ohne else "") + f". {DATEN_HINWEIS}")
    if namen:
        print(", ".join(namen))


def cmd_triage(cfg: dict, a: argparse.Namespace) -> None:
    stunden = wert(a.hours, cfg, "triage_hours", 48)
    seit = vor_sekunden(stunden * 3600)
    namen = [norm(n) for n in cfg.get("me_names", [cfg.get("me", "")])]
    with snapshot(cfg) as con:
        chats = {c["id"]: c for c in sichtbar(lade_chats(con, cfg), cfg)}
        rows = nachrichten(con, list(chats), seit=seit, aufsteigend=True)
    je_chat = defaultdict(list)
    for m in rows:
        je_chat[m["chat"]].append(m)
    offen, gruppen, beantwortet, archiv = [], [], [], []
    for cid, ms in je_chat.items():
        c = chats[cid]
        if all(m["ich"] for m in ms):
            continue
        letzte_ich = max((i for i, m in enumerate(ms) if m["ich"]), default=-1)
        neu = ms[letzte_ich + 1:]
        e = {"chat": c, "ms": ms, "neu": neu, "letzte": ms[-1]["ts"],
             "bezug": [m for m in neu if erwaehnt(m["text"], namen)]}
        if c["archiviert"]:
            archiv.append(e)
        elif c["art"] != "person":
            gruppen.append(e)
        else:
            (offen if neu else beantwortet).append(e)
    cfg_me = cfg.get("me", "Ich")
    kopf = (f"WhatsApp, letzte {stunden:g} Stunden, {stand_text()}: "
            f"{len(offen) + len(gruppen) + len(beantwortet) + len(archiv)} Chats mit neuen Nachrichten. {DATEN_HINWEIS}")
    zeilen = [kopf] + ([stand_hinweis()] if stand_hinweis() else [])
    if not je_chat:
        zeilen.append("Nichts Neues.")
    if offen:
        zeilen += ["", f"## Neu seit deiner letzten Nachricht ({len(offen)})"]  # ob eine Antwort nötig ist, sagt der Inhalt
        for e in sorted(offen, key=lambda e: e["letzte"], reverse=True):
            c = e["chat"]
            zeilen.append(f"{c['name']} (id {c['id']}) · {len(e['neu'])} neu seit deiner letzten Nachricht · zuletzt {zeit(e['letzte'])}")
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
            zeilen.append(f"{c['name']} (id {c['id']}) · zuletzt {zeit(e['letzte'])} von {cfg_me}")
    if archiv:
        zeilen += ["", "Archiviert mit neuen Nachrichten: " + ", ".join(
            f"{e['chat']['name']} ({len([m for m in e['ms'] if not m['ich']])})" for e in archiv)]
    drucke(zeilen, wert(a.max_chars, cfg, "max_chars", 6000))


def cmd_read(cfg: dict, a: argparse.Namespace) -> None:
    seit = vor_sekunden(a.days * 86400) if a.days is not None else (apple(zeitpunkt(a.since)) if a.since else None)
    bis = apple(zeitpunkt(a.before)) if a.before else None
    limit = a.limit if a.limit is not None else (500 if seit is not None else standard(cfg, "read_limit", 60))
    max_zeichen = wert(a.max_chars, cfg, "max_chars", 6000)
    typen = "" if a.system else f" AND ZMESSAGETYPE NOT IN ({EREIGNIS_SQL})"
    with snapshot(cfg) as con:
        chat = finde_chat(lade_chats(con, cfg), a.chat, a.id, versteckt=versteckte_arten(cfg))
        vor = None
        if a.before_id is not None:
            r = con.execute("SELECT ZMESSAGEDATE FROM ZWAMESSAGE WHERE Z_PK = ? AND ZCHATSESSION = ?",
                            (a.before_id, chat["id"])).fetchone()
            if r is None:
                sys.exit(f"Nachricht {a.before_id} gehört nicht zu {chat['name']} (id {chat['id']}). Die id aus dem "
                         "Hinweis von read nehmen.")
            vor = (r[0], a.before_id)
        rows = nachrichten(con, [chat["id"]], seit, bis, limit=limit, system=a.system, vor=vor)  # neueste zuerst
        aelter = bool(rows) and con.execute(
            "SELECT 1 FROM ZWAMESSAGE WHERE ZCHATSESSION = ? AND ZMESSAGEDATE >= ? AND (ZMESSAGEDATE < ? OR "
            "(ZMESSAGEDATE = ? AND Z_PK < ?))" + typen + " LIMIT 1",
            (chat["id"], seit if seit is not None else -1e18, rows[-1]["ts"], rows[-1]["ts"], rows[-1]["id"])
        ).fetchone() is not None
    if not rows:
        print(f"{chat['name']} ({ARTEN[chat['art']]}, id {chat['id']}): keine Nachrichten im Zeitraum.")
        if stand_hinweis():
            print(stand_hinweis())
        return
    zeilen = [zeile(m, chat, cfg, laenge=LANGE_ZEILE) for m in reversed(rows)]  # chronologisch
    gezeigt = auswahl(zeilen, max_zeichen, von_hinten=True)
    aeltester, weg = rows[len(gezeigt) - 1], len(rows) - len(gezeigt)
    print(f"{chat['name']} ({ARTEN[chat['art']]}, id {chat['id']}): {len(gezeigt)} Nachrichten vom "
          f"{zeit(aeltester['ts'])} bis {zeit(rows[0]['ts'])}. {DATEN_HINWEIS}")
    if stand_hinweis():
        print(stand_hinweis())
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
        t = varianten_suche(f"{m['text'] or ''} {m['titel'] or ''}")
        return all(any(v in x for v in b for x in t) for b in begriffe)

    with snapshot(cfg) as con:
        chats = lade_chats(con, cfg)
        ziel = [finde_chat(chats, a.chat, versteckt=versteckte_arten(cfg))] if a.chat else sichtbar(chats, cfg, a.all)
        je_id = {c["id"]: c for c in chats}
        rows = nachrichten(con, [c["id"] for c in ziel], seit=seit, nur_ich=a.from_me, passt=passt,
                           bedingung="(m.ZTEXT IS NOT NULL OR mi.ZTITLE IS NOT NULL)",
                           limit=wert(a.limit, cfg, "search_limit", 30))
    suche = " ".join(a.terms)
    print(f"Suche '{suche}': {len(rows)} Treffer in den letzten {tage:g} Tagen, neueste zuerst. {DATEN_HINWEIS}")
    if stand_hinweis():
        print(stand_hinweis())
    zeilen = []
    for m in rows:
        c = je_id[m["chat"]]
        text = inhalt(m)
        if len(text) > 240:
            start = max(0, fundstelle(text, a.terms[0]) - 100)
            text = ("[vorne gekürzt] " if start else "") + kuerze(text[start:], 220)
        zeilen.append(f"{zeit(m['ts'])} | {c['name']} (id {c['id']}) | {absender(m, c, cfg)}: {text}")
    drucke(zeilen, wert(a.max_chars, cfg, "max_chars", 6000))


def stilverstoesse(text: str, cfg: dict) -> list:
    """Zeichen, die laut Schreibregeln nie vorkommen (forbidden_chars). Smileys wie ;-) und Links zählen nicht."""
    return verbotene_zeichen(text, cfg.get("forbidden_chars", []))


def telefonnummer(con: sqlite3.Connection, chat: dict) -> str | None:
    if chat["art"] != "person":
        return None
    nutzer, _, dom = chat["jid"].partition("@")
    if dom == "s.whatsapp.net":
        return nutzer if nutzer.isdigit() else None
    if dom == "lid":
        try:
            r = con.execute("SELECT ZWHATSAPPID FROM kontakte.ZWAADDRESSBOOKCONTACT WHERE ZLID = ? "
                            "AND ZWHATSAPPID LIKE '%@s.whatsapp.net' LIMIT 1", (chat["jid"],)).fetchone()
        except sqlite3.Error:  # Kontakte fehlen oder anderes Schema
            return None
        nutzer = als_text(r[0]).partition("@")[0] if r else ""
        return nutzer if nutzer.isdigit() else None
    return None


def cmd_draft(cfg: dict, a: argparse.Namespace) -> None:
    text = entwurfstext(a.text_file, NACHRICHT_DATEI) if a.text_file else (a.text or "")
    text = text.strip()
    if not text:
        sys.exit("Kein Text für den Entwurf.")
    if len(text) > TEXT_MAX:  # vor dem Lesen der Datenbank, die Länge des Links prüft draft danach (Prüfung 20.10.2026)
        sys.exit(f"Nicht geöffnet: Text mit {len(text)} Zeichen ist länger als {TEXT_MAX}. Kürzen oder aufteilen.")
    verstoesse = stilverstoesse(text, cfg)
    if verstoesse and not a.ignore_style:
        sys.exit("Nicht geöffnet: Der Text enthält " + ", ".join(f"'{z}'" for z in verstoesse)
                 + " (laut Schreibregeln nie verwenden). Text anpassen oder bewusst mit --ignore-style direkt hinter "
                   "dem Skript.")
    with snapshot(cfg) as con:
        chat = finde_chat(lade_chats(con, cfg), a.chat, a.id, strikt=True, versteckt=versteckte_arten(cfg))
        if chat["art"] not in ("person", "gruppe"):
            sys.exit(f"Entwürfe gehen nur an Personen und Gruppen, '{chat['name']}' ist {ARTEN[chat['art']]}.")
        nummer = telefonnummer(con, chat)
    if not nummer:  # ohne Nummer nur über die ungetestete Chat-Auswahl, auch kein Trockenlauf
        art = "Gruppe" if chat["art"] == "gruppe" else "Person ohne gespeicherte Nummer"
        sys.exit(f"Nicht geöffnet: WhatsApp kann den Chat {chat['name']} ({art}, id {chat['id']}) nicht direkt öffnen. "
                 "Den Text zum Kopieren geben.")
    url = "whatsapp://send?" + urllib.parse.urlencode({"phone": nummer, "text": text}, quote_via=urllib.parse.quote)
    if len(url) > 6000:
        sys.exit("Text zu lang für einen Entwurf per Link. Kürzen oder aufteilen.")
    ziel = f"{chat['name']} ({ARTEN[chat['art']]}, id {chat['id']})"
    # Ohne Schlüssel im Hintergrund: Vorn könnte ein Enter in der Claude-App in WhatsApp landen und senden
    hintergrund = cfg.get("entwurf_im_hintergrund", True)
    if a.dry_run:
        print(f"Trockenlauf, nichts geöffnet. Ziel: {ziel}. Der Chat öffnet sich direkt.")
        if chat["entwurf"]:
            print("Achtung: Im Chat liegt ungesendeter Text, der Entwurf würde ihn ersetzen. Öffnen nur mit --replace "
                  "direkt hinter dem Skript.")
        print(f"Text ({len(text)} Zeichen): {bereinige(text)}")
        return
    if chat["entwurf"] and not a.replace:
        sys.exit(f"Nicht geöffnet: Im Chat mit {chat['name']} liegt ungesendeter Text, den der Entwurf ersetzen würde. "
                 "Erst in WhatsApp senden oder löschen, oder bewusst mit --replace direkt hinter dem Skript.")
    # Kaltstart: erst starten und warten, sonst kommt der Link an, während WhatsApp noch lädt (Befund 26.11.2026)
    quelle = Path(os.path.expanduser(cfg.get("database_dir") or STANDARD_ORDNER))
    start = starte_app(OPEN_BEFEHL, PGREP_BEFEHL, APP_PROZESS, APP_ID, quelle / "ChatStorage.sqlite", START_WARTEN,
                       START_RUHE)
    befehl = [OPEN_BEFEHL, "-g", url] if hintergrund else [OPEN_BEFEHL, url]
    try:
        r = subprocess.run(befehl, capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):  # nie die Meldung selbst: sie enthält den Link mit Nummer und Text
        sys.exit("WhatsApp ließ sich nicht öffnen. Ist WhatsApp für Mac installiert?")
    if r.returncode != 0:
        sys.exit(f"WhatsApp ließ sich nicht öffnen (Fehlercode {r.returncode}). Ist WhatsApp für Mac installiert?")
    if a.text_file:
        NACHRICHT_DATEI.unlink(missing_ok=True)
    # Ehrlich melden: open bestätigt nur die Übergabe des Links, ob der Text im Chat steht, sieht das Kit nicht
    print(f"Entwurf für {ziel} an WhatsApp übergeben, {len(text)} Zeichen.")
    zustand = startzeile(start, "WhatsApp")
    if zustand:
        print(zustand)
    print("Im Hintergrund geöffnet: Zum Prüfen und Abschicken WhatsApp nach vorne holen." if hintergrund
          else "WhatsApp ist vorne geöffnet.")
    print("Gesendet wird nur, wenn du in WhatsApp selbst Enter drückst.")


def cmd_style(cfg: dict, a: argparse.Namespace) -> None:
    tage = wert(a.days, cfg, "style_days", 365)
    anzahl = wert(a.n, cfg, "style_n", 200)
    seit = vor_sekunden(tage * 86400)
    with snapshot(cfg) as con:
        chats = {c["id"]: c for c in lade_chats(con, cfg) if c["art"] in ("person", "gruppe")}
        rows = con.execute("SELECT ZCHATSESSION, ZMESSAGEDATE, ZISFROMME, ZTEXT, ZMESSAGETYPE FROM ZWAMESSAGE "
                           f"WHERE ZMESSAGEDATE >= ? AND ZMESSAGETYPE NOT IN ({EREIGNIS_SQL}) "
                           "ORDER BY ZCHATSESSION, ZMESSAGEDATE", (seit,)).fetchall()
        buch = namensbuch(con)
    eigene, serien, lauf, vorher = [], [], 0, None
    for cid, ts, ich, text, typ in rows:
        if cid not in chats:
            continue
        if ich and vorher and vorher[0] == cid and vorher[2] and ts - vorher[1] <= 300:
            lauf += 1
        else:
            if lauf:
                serien.append(lauf)
            lauf = 1 if ich else 0
        vorher = (cid, ts, ich)
        if ich and typ == 0 and bereinige(text):
            roh = STEUERZEICHEN.sub("", ZEILENTRENNER.sub("\n", als_text(text))).strip()
            eigene.append((cid, ts, erwaehnungen(roh, buch)))
    if lauf:
        serien.append(lauf)
    if not eigene:
        sys.exit(f"Keine eigenen Textnachrichten in den letzten {tage:g} Tagen.")

    def woerter(t):
        return re.findall(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", t)

    laengen = [len(woerter(t)) for _, _, t in eigene]
    ende = Counter()
    for _, _, t in eigene:
        s = t.rstrip()
        ende["Emoji oder Smiley" if ENDE_EMOJI.search(s) else
             {".": "Punkt", "!": "Ausrufezeichen", "?": "Fragezeichen"}.get(s[-1:], "ohne Satzzeichen")] += 1
    buchstaben = [next((ch for ch in t if ch.isalpha()), "") for _, _, t in eigene]
    klein = sum(ch.islower() for ch in buchstaben) / max(1, sum(bool(ch) for ch in buchstaben))
    mit_emoji = sum(bool(EMOJI.search(t)) for _, _, t in eigene)
    emojis = Counter(e for _, _, t in eigene for e in EMOJI.findall(t))
    smileys = Counter(s for _, _, t in eigene for s in SMILEY.findall(t))
    lachen = Counter(l.lower() for _, _, t in eigene for l in LACHEN.findall(t))
    zeichen = {z: sum(t.count(z) for _, _, t in eigene) for z in ("—", "–", "…", "...", "!!", " - ")}
    zeichen[";"] = sum(SMILEY.sub("", LINK.sub("", t)).count(";") for _, _, t in eigene)
    erste = Counter(w[0].lower() for w in (woerter(t) for _, _, t in eigene) if w)
    einwort = Counter(w[0].lower() for w in (woerter(t) for _, _, t in eigene) if len(w) == 1)
    je_art = defaultdict(list)
    for (cid, _, _), n in zip(eigene, laengen):
        je_art[chats[cid]["art"]].append(n)

    def anteil(n):
        return f"{100 * n / len(eigene):.0f} %"

    def de(x):
        return f"{x:.1f}".replace(".", ",")

    def top(c, k=12):
        return ", ".join(f"{w} ({n})" for w, n in c.most_common(k)) or "keine"

    aus = [f"Stilgrundlage WhatsApp: {len(eigene)} eigene Textnachrichten der letzten {tage:g} Tage in "
           f"{len({c for c, _, _ in eigene})} Chats. Nichts davon wird gespeichert. {DATEN_HINWEIS}",
           "", "## Statistik",
           f"- Wörter je Nachricht: Ø {de(statistics.mean(laengen))}, Median {statistics.median(laengen):.0f}, "
           f"1 bis 3 Wörter: {anteil(sum(n <= 3 for n in laengen))}, über 25 Wörter: {anteil(sum(n > 25 for n in laengen))}",
           "- Je Art: " + ", ".join(f"{ARTEN[k]} Ø {de(statistics.mean(v))} Wörter ({len(v)} Nachrichten)"
                                   for k, v in sorted(je_art.items())),
           f"- Nachrichten je Wortmeldung (Serie innerhalb 5 Minuten): Ø {de(statistics.mean(serien))}, "
           f"Serien mit 3 und mehr: {100 * sum(s >= 3 for s in serien) / len(serien):.0f} %",
           "- Ende der Nachricht: " + ", ".join(f"{k} {anteil(v)}" for k, v in ende.most_common()),
           f"- Kleiner Anfangsbuchstabe: {100 * klein:.0f} %",
           f"- Emojis: in {anteil(mit_emoji)} der Nachrichten. Häufigste: {top(emojis)}",
           f"- Smileys: {top(smileys, 8)}. Lachen: {top(lachen, 6)}",
           "- Zeichen: " + ", ".join(f"'{k.strip() or k}'{' (mit Leerzeichen)' if k == ' - ' else ''} {v}"
                                     for k, v in zeichen.items()),
           f"- Häufigste erste Wörter: {top(erste, 15)}",
           f"- Häufigste Ein-Wort-Nachrichten: {top(einwort, 15)}"]

    je_chat = Counter()
    probe = []
    deckel = max(3, anzahl // 10)
    for cid, ts, t in sorted(eigene, key=lambda e: e[1], reverse=True):
        if je_chat[cid] >= deckel:
            continue
        je_chat[cid] += 1
        probe.append((cid, ts, t))
        if len(probe) >= anzahl:
            break
    aus += ["", f"## Stichprobe ({len(probe)} Nachrichten, neueste zuerst, höchstens {deckel} je Chat, Nummern, Mails "
                "und Links ersetzt)"]
    for cid, ts, t in probe:
        c = chats[cid]
        aus.append(f"{zeit(ts)} | an {c['name']} ({ARTEN[c['art']]}) | {kuerze(maskiere(bereinige(t)), 300)}")
    drucke(aus, wert(a.max_chars, cfg, "style_max_chars", 20000))


def main() -> None:
    fange_signale()
    p = argparse.ArgumentParser(
        description="WhatsApp (Mac-App): lesen, suchen, Neues sichten, Entwürfe öffnen. Sendet nie.",
        formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    def befehl(name, hilfe):  # ohne Abkürzungen: --ignore darf nie als --ignore-style gelten
        return sub.add_parser(name, help=hilfe, allow_abbrev=False)

    befehl("check", "Zugriff und Datenbank prüfen")

    c = befehl("chats", "Chats nach letzter Aktivität (Standard: letzte 30 Tage)")
    c.add_argument("--days", type=positiv(float), help="Zeitraum für die Nachrichtenzahl in Tagen")
    c.add_argument("--query", action="append",
                   help="nur Chats, deren Name passt (auch ohne Aktivität), mehrfach möglich: je Name ein Block")
    c.add_argument("--kind", choices=sorted(ARTEN), help="nur diese Art")
    c.add_argument("--sort", choices=["aktiv", "anzahl"], default="aktiv", help="nach letzter Nachricht oder Anzahl")
    c.add_argument("--limit", type=positiv(int), help="höchstens so viele Zeilen")
    c.add_argument("--all", action="store_true", help="auch Status, Kanäle, Broadcasts, Communities")

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
    r.add_argument("--system", action="store_true", help="auch Gruppenereignisse und Systemhinweise")

    s = befehl("search", "Volltextsuche, alle Begriffe müssen vorkommen")
    s.add_argument("terms", nargs="+", help="Suchbegriffe")
    s.add_argument("--chat", help="nur in diesem Chat")
    s.add_argument("--days", type=positiv(float), help="Zeitraum in Tagen (Standard aus config.json)")
    s.add_argument("--limit", type=positiv(int))
    s.add_argument("--from-me", action="store_true", help="nur eigene Nachrichten")
    s.add_argument("--all", action="store_true", help="auch Status, Kanäle, Broadcasts, Communities")
    s.add_argument("--max-chars", type=positiv(int))

    d = befehl("draft", "Entwurf im Chat öffnen, sendet nie")
    d.add_argument("chat", nargs="?", help="Chatname, muss eindeutig sein")
    d.add_argument("--id", type=int, help="Chat-id statt Name")
    d.add_argument("--text", help="Text direkt (für kurze Nachrichten)")
    d.add_argument("--text-file", help="nur nachricht.txt im Kit-Ordner, wird danach gelöscht")
    d.add_argument("--dry-run", action="store_true", help="nur zeigen, nichts öffnen")
    d.add_argument("--ignore-style", action="store_true", help="verbotene Zeichen bewusst zulassen")
    d.add_argument("--replace", action="store_true", help="auch öffnen, wenn im Chat ungesendeter Text liegt")

    st = befehl("style", "eigene Nachrichten und Statistik für das Stilprofil ausgeben")
    st.add_argument("--n", type=positiv(int), help="Größe der Stichprobe (Standard 200)")
    st.add_argument("--days", type=positiv(float), help="Zeitraum in Tagen (Standard 365)")
    st.add_argument("--max-chars", type=positiv(int))

    # schreibende Schalter nur direkt hinter dem Skript
    vorn, rest = kit_basis.schalter_vorn(sys.argv[1:], ("--ignore-style", "--replace"))
    a = p.parse_args(rest + vorn)
    if a.cmd == "draft" and bool(a.text) == bool(a.text_file):
        p.error("draft braucht genau eins von --text oder --text-file")
    if a.cmd == "read" and a.before and a.before_id is not None:  # Schalterkonflikte: Exit 2 wie jeder falsche Aufruf
        p.error("read nimmt nur eins von --before und --before-id")
    if a.cmd == "read" and a.days is not None and a.since:
        p.error("read nimmt nur eins von --days und --since")
    cfg = lade_config()
    befehle = {"check": cmd_check, "chats": cmd_chats, "members": cmd_members, "triage": cmd_triage, "read": cmd_read,
               "search": cmd_search, "draft": cmd_draft, "style": cmd_style}
    try:
        befehle[a.cmd](cfg, a)
    except sqlite3.DatabaseError as e:
        sys.exit(f"Datenbank-Kopie nicht lesbar ({e}). Erneut versuchen, WhatsApp schreibt eventuell gerade.")


if __name__ == "__main__":
    kit_basis.starten(main, __file__)
