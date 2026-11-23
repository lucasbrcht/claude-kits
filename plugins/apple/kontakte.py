#!/usr/bin/env python3
"""Apple Kontakte lesen (Datenbank des Adressbuchs als Kopie), nur lesen, kein Schreibweg.

Aufruf (System-Python, ohne Sandbox, braucht Festplattenvollzugriff wie imessage.py, für den Server python3.9 der
Command Line Tools):
  kontakte.py me                 die eigene Karte mit allen Feldern
  kontakte.py search "<Text>"    Kontakte, deren Name, Spitzname, Firma, Mail oder Telefon den Text enthält, mit ID
  kontakte.py show "<ID>"        ein Kontakt mit allen Feldern: Telefon, Mail, Adressen, Geburtstag, Daten, Firma,
                                 Abteilung, Position, Beziehungen, URLs

Zweck: Adresse, Telefon, Mail oder Geburtstag einer Person oder die eigenen live aus Kontakte statt aus einer Datei
oder einer Auswahlfrage. Ausgabe nur auf stdout, nichts wird gespeichert. Das Contacts-Framework fragt in der
Claude-App nie nach (der App fehlt der Berechtigungstext), deshalb liest das Skript AddressBook-v22.abcddb aller
Quellen als Kopie, so wie imessage.py im Plugin chat. Spalten
prüft es beim Lauf und nutzt nur, was es findet. Die eigene Karte erkennt es an kontakte.eigene_mails in config.json.
Exit-Codes: 0 ok, 1 Fehler (kein Zugriff, nichts gefunden), 2 Aufruf falsch. Abkürzungen gelten nicht.
"""
import argparse
import contextlib
import datetime
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unicodedata
from pathlib import Path

import kit_basis  # Steuer- und Formatzeichen, Datenhinweis, gleich in apple und chat
from eventkit_basis import KIT_DIR, load_config

HINWEIS = f"({kit_basis.daten_hinweis('Inhalte von Kontakten')})"
ADRESSBUCH = Path("~/Library/Application Support/AddressBook")
DATEI = "AddressBook-v22.abcddb"
TREFFER_MAX = 25
CORE_DATA_NULL = datetime.datetime(2001, 1, 1, tzinfo=datetime.timezone.utc)
OHNE_JAHR = 1604  # Kontakte legt Geburtstage ohne Jahr im Jahr 1604 ab
ETIKETTEN = {"home": "Privat", "work": "Arbeit", "mobile": "Mobil", "iphone": "iPhone", "main": "Haupt",
             "homefax": "Fax privat", "workfax": "Fax Arbeit", "other": "Andere", "homepage": "Homepage",
             "anniversary": "Jahrestag", "mother": "Mutter", "father": "Vater", "parent": "Elternteil",
             "brother": "Bruder", "sister": "Schwester", "child": "Kind", "spouse": "Ehepartner",
             "partner": "Partner", "friend": "Freund", "assistant": "Assistenz", "manager": "Vorgesetzt"}
# Tabelle: (Feld in der Ausgabe, Wertspalten). Fehlt eine Tabelle oder Spalte, fällt das Feld weg
FELDTABELLEN = (("ZABCDPHONENUMBER", "Telefon", ("ZFULLNUMBER",)),
                ("ZABCDEMAILADDRESS", "Mail", ("ZADDRESS",)),
                ("ZABCDPOSTALADDRESS", "Adresse", ("ZSTREET", "ZZIPCODE", "ZCITY", "ZSTATE", "ZCOUNTRYNAME")),
                ("ZABCDCONTACTDATE", "Datum", ("ZDATE",)),
                ("ZABCDRELATEDNAME", "Beziehung", ("ZNAME",)),
                ("ZABCDURLADDRESS", "URL", ("ZURL",)))
PERSON_SPALTEN = ("ZUNIQUEID", "ZFIRSTNAME", "ZMIDDLENAME", "ZLASTNAME", "ZNICKNAME", "ZORGANIZATION", "ZDEPARTMENT",
                  "ZJOBTITLE", "ZBIRTHDAY", "ZDISPLAYFLAGS")


def aufruf_falsch(text: str):
    """Falscher Aufruf: Text auf stderr, Exit 2 wie bei allen Kits (Fehler mit nichts gelesen ist 1)."""
    print(text, file=sys.stderr)
    sys.exit(2)


def sauber(s) -> str:
    """Ein Feld für die Ausgabe: ohne Terminalsteuerfolgen, Steuer-, Richtungs- und unsichtbare Formatzeichen
    (kit_basis), eine Zeile. Nummern bleiben stehen, sie sind der Zweck des Skripts."""
    if isinstance(s, bytes):
        s = s.decode("utf-8", "replace")
    return " ".join(kit_basis.ohne_formatzeichen(str(s) if s is not None else "").split())


def norm(s) -> str:
    """Für die Suche: ohne Groß- und Kleinschreibung und Unicode-Form, so wie die Ausgabe es zeigt."""
    return unicodedata.normalize("NFC", sauber(s)).casefold()


def ziffern(s) -> str:
    return re.sub(r"\D", "", s or "")


def etikett(label) -> str:
    """_$!<Home>!$_ wird Privat, eigene Etiketten bleiben, wie sie sind."""
    roh = sauber(re.sub(r"^_\$!<(.*)>!\$_$", r"\1", sauber(label)))
    return ETIKETTEN.get(roh.casefold(), roh)


def datum(wert) -> str:
    """Core-Data-Zeit (Sekunden ab 2001) als TT.MM.JJJJ, ohne Jahr TT.MM. Kontakte speichert den Tag um Mitternacht
    einer Zeitzone, 12 Stunden dazu treffen ihn in jeder."""
    if wert in (None, ""):
        return ""
    try:
        t = CORE_DATA_NULL + datetime.timedelta(seconds=float(wert) + 43200)
    except (TypeError, ValueError, OverflowError):
        return ""
    return f"{t.day:02d}.{t.month:02d}." + ("" if t.year == OHNE_JAHR else f"{t.year}")


def quellen() -> list:
    wurzel = Path(os.path.expanduser(str(ADRESSBUCH)))
    return [p for p in [wurzel / DATEI, *sorted(wurzel.glob(f"Sources/*/{DATEI}"))] if p.is_file()]


def kopiere(src: Path, dst: Path) -> None:
    """Datenbank und WAL zusammen kopieren, nie die -shm-Datei (SQLite baut sie aus dem WAL neu)."""
    shutil.copyfile(src, dst)
    if Path(f"{src}-wal").is_file():
        shutil.copyfile(f"{src}-wal", f"{dst}-wal")


def spalten(con, tabelle: str) -> set:
    return {r[1] for r in con.execute(f"PRAGMA table_info({tabelle})")}


def lies_quelle(con, nr: int) -> list:
    """Alle Personen einer Datenbank als Wörterbücher mit Feldern und Listen (Feld, Etikett, Wert)."""
    vorhanden = spalten(con, "ZABCDRECORD")
    if not {"Z_PK", "ZUNIQUEID"} <= vorhanden:
        return []
    wahl = [s for s in PERSON_SPALTEN if s in vorhanden]
    personen = {}
    for zeile in con.execute(f"SELECT Z_PK, {', '.join(wahl)} FROM ZABCDRECORD"):
        p = dict(zip(wahl, zeile[1:]))
        if not any(sauber(p.get(s)) for s in ("ZFIRSTNAME", "ZLASTNAME", "ZNICKNAME", "ZORGANIZATION")):
            continue  # Gruppen, Konten und leere Karten
        p["felder"], p["quelle"] = [], nr
        personen[zeile[0]] = p
    for tabelle, feld, werte in FELDTABELLEN:
        da = spalten(con, tabelle)
        if "ZOWNER" not in da or not any(w in da for w in werte):
            continue
        wahl = [w for w in werte if w in da]
        label = "ZLABEL" if "ZLABEL" in da else "NULL"
        sortierung = " ORDER BY ZORDERINGINDEX" if "ZORDERINGINDEX" in da else ""
        for besitzer, lab, *teile in con.execute(f"SELECT ZOWNER, {label}, {', '.join(wahl)} FROM {tabelle}"
                                                 f"{sortierung}"):
            if besitzer not in personen:
                continue
            if feld == "Datum":
                wert = datum(teile[0])
            elif feld == "Adresse":
                t = dict(zip(wahl, teile))
                strasse = ", ".join(sauber(z) for z in str(t.get("ZSTREET") or "").splitlines() if sauber(z))
                ort = " ".join(x for x in (sauber(t.get("ZZIPCODE")), sauber(t.get("ZCITY"))) if x)
                wert = ", ".join(x for x in (strasse, ort, sauber(t.get("ZSTATE")), sauber(t.get("ZCOUNTRYNAME")))
                                 if x)
            else:
                wert = sauber(teile[0])
            if wert:
                personen[besitzer]["felder"].append((feld, etikett(lab), wert))
    return list(personen.values())


def alle_kontakte() -> list:
    """Personen aus allen Quellen. Ohne Lesezugriff eine Zeile mit dem Weg und Exit 1."""
    dateien = quellen()
    if not dateien:
        sys.exit("Keine Kontakte-Datenbank gefunden oder kein Zugriff. Systemeinstellungen > Datenschutz & Sicherheit > "
                 "Festplattenvollzugriff: python3.9 der Command Line Tools (damit laufen die Werkzeuge) oder die "
                 "Claude-App einschalten (Werkzeug einstellungen mit freigabe öffnet beides). Im Code-Tab per Bash als "
                 "eigenen Befehl mit absolutem Pfad starten "
                 f"(python3 \"{KIT_DIR}/kontakte.py\" ...), ohne cd, Pipe oder Umleitung.")
    personen = []
    with tempfile.TemporaryDirectory(prefix="apple-kit-kontakte-") as tmp:
        for nr, quelle in enumerate(dateien):
            ziel = Path(tmp) / f"ab{nr}.abcddb"
            try:
                kopiere(quelle, ziel)
                with contextlib.closing(sqlite3.connect(ziel)) as con:
                    con.text_factory = lambda b: b.decode("utf-8", "replace")
                    personen += lies_quelle(con, nr)
            except PermissionError:
                sys.exit("Kein Zugriff auf die Kontakte-Datenbank. Systemeinstellungen > Datenschutz & Sicherheit > "
                         "Festplattenvollzugriff: python3.9 der Command Line Tools (damit laufen die Werkzeuge) "
                         "oder die Claude-App einschalten (Werkzeug einstellungen mit freigabe öffnet beides). Im "
                         "Code-Tab per Bash als eigenen Befehl mit absolutem Pfad "
                         f"starten (python3 \"{KIT_DIR}/kontakte.py\" ...), ohne cd, Pipe oder Umleitung.")
            except (OSError, sqlite3.Error) as e:
                print(f"Hinweis: eine Quelle von Kontakte nicht lesbar ({type(e).__name__}), ohne sie weiter.",
                      file=sys.stderr)
    return personen


def ist_firma(p) -> bool:
    return bool(int(p.get("ZDISPLAYFLAGS") or 0) & 1)


def anzeigename(p) -> str:
    """Vorname, zweiter Vorname, Nachname, bei Firmenkarten oder ohne Namen die Firma."""
    name = " ".join(t for t in (sauber(p.get(s)) for s in ("ZFIRSTNAME", "ZMIDDLENAME", "ZLASTNAME")) if t)
    if ist_firma(p) or not name:
        return sauber(p.get("ZORGANIZATION")) or name or sauber(p.get("ZNICKNAME")) or "(ohne Namen)"
    return name


def kennung(p) -> str:
    return sauber(p.get("ZUNIQUEID"))


def zeilen(p) -> list:
    """Alle Felder eines Kontakts als Zeilen, leere fallen weg."""
    out = [anzeigename(p), f"ID: {kennung(p)}"]
    for feld, spalte in (("Spitzname", "ZNICKNAME"), ("Firma", "" if ist_firma(p) else "ZORGANIZATION"),
                         ("Abteilung", "ZDEPARTMENT"), ("Position", "ZJOBTITLE")):
        if spalte and sauber(p.get(spalte)):
            out.append(f"{feld}: {sauber(p.get(spalte))}")
    reihenfolge = [f for _t, f, _w in FELDTABELLEN]
    felder = sorted(p["felder"], key=lambda f: reihenfolge.index(f[0]))
    geburtstag = datum(p.get("ZBIRTHDAY"))
    for feld, lab, wert in felder:
        if feld == "Datum" and geburtstag and not any(f == "Geburtstag" for f in out):
            out.append(f"Geburtstag: {geburtstag}")
        out.append(f"{feld} ({lab}): {wert}" if lab else f"{feld}: {wert}")
    if geburtstag and not any(z.startswith("Geburtstag:") for z in out):
        out.append(f"Geburtstag: {geburtstag}")
    return list(dict.fromkeys(out))


def eigene_mails() -> set:
    cfg = load_config().get("kontakte") or {}
    if not isinstance(cfg, dict) or not isinstance(cfg.get("eigene_mails", []), list):
        sys.exit("config.json: kontakte.eigene_mails muss eine Liste sein.")
    return {norm(m) for m in cfg.get("eigene_mails", []) if sauber(m)}


def cmd_me(personen) -> None:
    mails = eigene_mails()
    if not mails:
        sys.exit("Für die eigene Karte fehlt kontakte.eigene_mails in config.json des Plugins apple (eigene Mailadressen).")
    treffer = [p for p in personen if any(f == "Mail" and norm(w) in mails for f, _l, w in p["felder"])]
    if not treffer:
        sys.exit("Keine Karte mit den eigenen Mailadressen in Kontakte. Adressen in kontakte.eigene_mails prüfen.")
    drucke(treffer)


def cmd_show(personen, gesucht: str) -> None:
    treffer = [p for p in personen if kennung(p) == gesucht or kennung(p).split(":")[0] == gesucht]
    if not treffer:
        sys.exit(f"Kein Kontakt mit der ID {sauber(gesucht)}. IDs nennt kontakte.py search.")
    drucke(treffer)


def drucke(treffer) -> None:
    """Eine Karte, auch wenn sie in mehreren Quellen steht: gleiche Zeilen nur einmal."""
    print(HINWEIS)
    gesehen = []
    for p in treffer:
        z = zeilen(p)
        if z[2:] in [g[2:] for g in gesehen]:
            continue
        if gesehen:
            print()
        print("\n".join(z))
        gesehen.append(z)


def passt(p, text: str) -> bool:
    """Name, Spitzname, Firma und Mail enthalten den Text (ohne Groß- und Kleinschreibung). Telefon ab drei Ziffern im
    Text nach Ziffern, ohne führende Nullen: 0176 1 findet auch +49 176 1."""
    gesucht = norm(text)
    felder = [anzeigename(p), *(p.get(s) for s in ("ZFIRSTNAME", "ZLASTNAME", "ZNICKNAME", "ZORGANIZATION")),
              *(w for f, _l, w in p["felder"] if f == "Mail")]
    if any(gesucht in norm(f) for f in felder):
        return True
    z = ziffern(text)
    if len(z) < 3:
        return False
    z = z.lstrip("0") or z
    return any(z in ziffern(w) for f, _l, w in p["felder"] if f == "Telefon")


def cmd_search(personen, text: str) -> None:
    treffer, ids = [], set()
    for p in sorted(personen, key=lambda p: norm(anzeigename(p))):
        if passt(p, text) and kennung(p) not in ids:
            treffer.append(p)
            ids.add(kennung(p))
    if not treffer:
        print(f"Kein Kontakt zu '{sauber(text)}'.")
        return
    print(HINWEIS)
    print(f"{len(treffer)} Treffer zu '{sauber(text)}':")
    for p in treffer[:TREFFER_MAX]:
        zusatz = [t for t in ("" if ist_firma(p) else sauber(p.get("ZORGANIZATION")), sauber(p.get("ZJOBTITLE")))
                  if t]
        print(f"- {anzeigename(p)}" + (f", {', '.join(zusatz)}" if zusatz else "") + f"  (ID {kennung(p)})")
    if len(treffer) > TREFFER_MAX:
        print(f"Weitere {len(treffer) - TREFFER_MAX} Treffer nicht gezeigt, die Suche genauer fassen.")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] and argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    p = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    p.add_argument("cmd", nargs="?", default="")
    p.add_argument("args", nargs="*")
    a = p.parse_args(argv)
    if a.cmd == "me":
        if a.args:
            aufruf_falsch("me nimmt keine Worte. Nichts gelesen.")
        eigene_mails()  # Konfigurationsfehler vor dem Lesen
        cmd_me(alle_kontakte())
    elif a.cmd in ("search", "show"):
        wort = "einen Text, etwa search 'Muster'" if a.cmd == "search" else "eine ID aus search"
        if len(a.args) != 1 or not a.args[0].strip():
            aufruf_falsch(f"{a.cmd} braucht genau {wort}, mit Leerzeichen in Anführungszeichen. Nichts gelesen.")
        (cmd_search if a.cmd == "search" else cmd_show)(alle_kontakte(), a.args[0].strip())
    else:
        aufruf_falsch(__doc__)


if __name__ == "__main__":
    kit_basis.starten(main, __file__)
