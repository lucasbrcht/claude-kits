#!/usr/bin/env python3
"""Apple Notes lesen und schreiben.

Der Weg zu Notes, ohne osascript allgemein freizugeben: Dieses Skript ruft
osascript intern auf, genau wie mail.py und imessage.py (Plugin chat)
(Plugin chat) es für ihre Apps tun. Bash(osascript *) bleibt im Code-Tab gesperrt.

Befehle (der Server ruft sie auf, von Hand immer mit absolutem Pfad: python3 "<Plugin>/notiz.py" ...):
  folders                                     Ordner mit Anzahl der Notizen
  list [--folder X] [--limit N]               Notizen auflisten
  read <titel> [--folder X] [--max-chars N] [--html]
                                              Inhalt als Text, höchstens 20000 Zeichen (0 = alles), --html als HTML
  search <text> [--limit N]                   Titel und Inhalt durchsuchen
  [--ausfuehren] add --title X --file notiz.html [--folder Z]
                                              Notiz anlegen, Inhalt aus der Datei im Plugin, in geteilten Ordnern erst
                                              mit --ausfuehren direkt hinter dem Skript (an anderer Stelle bricht das
                                              Skript ab)
  [--ausfuehren] replace <titel> --file notiz.html [--folder X]
                                              Inhalt einer Notiz ersetzen, in geteilten Ordnern erst mit --ausfuehren

Löschen gibt es bewusst nicht, auch nicht auf Ansage.

Text kommt nur aus notiz.html oder notiz.md im Kit-Ordner (ein Name gilt dort, egal wo die Shell
steht), nie aus anderen Dateien: add läuft ohne Rückfrage außerhalb der Sandbox, eine untergeschobene
Anweisung könnte sonst etwa ein Firmendokument in iCloud-Notizen holen. Nach Erfolg löscht das Skript
die Datei. HTML (notiz.html, oder Text, der mit <html, <!doctype, <div oder <h1 beginnt) geht
unverändert durch, so zeigt Notes Tabellen und Links. Markdown wird in das schlichte HTML umgewandelt,
das Notes zuverlässig darstellt (Überschriften, Absätze, Striche). Verweise, die Notes nachladen könnte
(file: in einem Tag, src oder url() ohne data:, srcset, @import), brechen ab, bevor etwas an Notes geht.

Geteilte Ordner (shared in Notes, auch für einen Ordner darüber, im Zweifel gilt geteilt): Andere sehen
jede neue Notiz und jede Änderung sofort. add und replace zeigen dort ohne --ausfuehren nur eine Vorschau mit
Titel, Ordner und Zeichenzahl und ändern nichts, die Textdatei bleibt (Dialog nur, wo
andere es sehen). Eine selbst geteilte Notiz in einem eigenen Ordner gilt ebenso als geteilt. read zeigt dann die
Zeile "Geteilt: ja".

read und replace nehmen eine Notiz nur, wenn genau eine den Titel trägt (in den erlaubten Ordnern, mit
--folder eingegrenzt). Sonst nennen sie die Ordner der Treffer, lesen oder ändern nichts (Exit 2).
replace setzt den ganzen Inhalt neu, Grundlage bei formatierten Notizen ist read --html (der Klartext
verliert Formatierung, Tabellen und Links). Notes nimmt die erste Zeile als Titel, ein neuer Titel kommt
als Hinweis.

Ordner in config.json unter notizen.ausgeschlossene_ordner werden mit allen Unterordnern nie gelesen,
durchsucht oder beschrieben, auch nicht in anderer Groß- und Kleinschreibung, Unicode-Form oder mit
anderen Leerzeichen. Der Papierkorb ist immer ausgenommen. Ein ausgeschlossener --folder meldet sich wie
ein unbekannter. add ohne --folder legt nur an, wenn der Standardordner frei ist. Eine fehlende oder kaputte
config.json bricht ab, statt die Ausschlüsse still fallen zu lassen. Antwortet Notes nicht, bricht osascript
nach OSA_SEKUNDEN ab.

AppleScript-Fallstrick: In "repeat with n in notes of f" ist n nur eine Referenz, "container of n"
scheitert damit. Deshalb läuft alles über eine Ordnerschleife aussen und "contents of n" innen. Ordner
ebenso: erst "contents of f", dann fragt die Kette der Ausschlüsse (Handler frei) "container".
"""

from __future__ import annotations  # str | None in Signaturen, python3 ist das System-Python 3.9 (seit 12.10.2026)

import argparse
import html
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time
import unicodedata

import kit_basis  # Konfiguration, Steuerzeichen, Datenhinweis, Textdatei, gleich in apple und chat

KIT = pathlib.Path(__file__).resolve().parent
TRENNER = "\x1e"          # trennt Felder, kommt in Notizen nicht vor
ZEILE = "\x1d"            # trennt Datensätze
HINWEIS = f"({kit_basis.daten_hinweis('Notizinhalte')})"


def sauber(s: str) -> str:
    """Ausgabe ohne Terminalsteuerfolgen, Steuer- und Richtungszeichen (kit_basis, Prüfung 20.10.2026), Zeilenumbrüche
    und Tabs bleiben. Erst nach dem Zerlegen anwenden: TRENNER und ZEILE sind selbst Steuerzeichen."""
    return kit_basis.ohne_steuerzeichen(s)


# Papierkorb: Notes nennt ihn je nach Systemsprache so. AppleScript kennt kein anderes Merkmal für ihn, die Datenbank
# ist gesperrt, deshalb bleibt es bei den Namen (Prüfung 20.10.2026)
IMMER_AUS = ["Recently Deleted", "Zuletzt gelöscht"]
TEXT_DATEIEN = ("notiz.html", "notiz.md")  # einzige Quellen für add und replace, im Kit-Ordner
MAX_BYTES = 2_000_000
OSA_SEKUNDEN = 90  # wie mail.py unter den 120 s des Bash-Werkzeugs, damit die eigene Meldung ankommt
LESE_MAX = 20_000  # Zeichen, die read ohne --max-chars zeigt: Eine riesige Notiz verdrängt sonst den Verlauf
# Verweise, die Notes beim Anlegen nachladen könnte (vorsorglich, Review 21.10.2026): file: in einem Tag holte eine
# lokale Datei in iCloud, src ohne data:, srcset, url() ohne data: und @import laden Bilder und Stile von außen. TAG
# ist ein Tag mit Attributen in Anführungszeichen, das > am Ende ist optional: So scheitert kein Treffer, und die Suche
# bleibt bei vielen offenen spitzen Klammern linear (ein Muster mit <[^>]* brauchte für 60 KB schon 26 s)
TAG = re.compile(r"<(?:[^<>\"']|\"[^\"]*\"|'[^']*')*>?")
FREMD_IM_TAG = re.compile(r"\bfile:|\bsrcset\s*=|\bsrc\s*=\s*(?![\"']?\s*data:)|\burl\(\s*(?![\"']?\s*data:)", re.I)
FREMD_IM_STIL = re.compile(r"url\(\s*(?![\"']?\s*data:)|@import")
# Zeilenende im HTML für Notes: Zeilenumbruch, Ende eines Blocks, Trennlinie (erste_zeile)
BLOCK_ENDE = re.compile(r"<br\s*/?>|</(?:div|p|h[1-6]|li|tr|td|th|ul|ol|table)\s*>|<hr\b[^<>]*>", re.I)


def config() -> dict:
    """config.json des Kits (kit_basis). Fehlt sie oder ist sie kaputt, bricht der Befehl ab: Ausschlüsse fallen nie
    still weg (Review 20.10.2026, wie reminders.py)."""
    return kit_basis.lade_config(kit_basis.datenordner(KIT) / "config.json", folge="Nichts gelesen oder geändert.")


def name_norm(s: str) -> str:
    """Ordnernamen aus config.json und --folder in NFC und ohne Leerzeichen am Rand (Review 21.10.2026): "Privat " oder
    eine andere Unicode-Form ließ den Ordner sonst still offen. Groß- und Kleinschreibung zählt in AppleScript nicht."""
    return unicodedata.normalize("NFC", s).strip()


def eigene_ausschluesse() -> list:
    """Die Ordner aus config.json, normalisiert, leere Einträge fallen weg."""
    block = config().get("notizen", {})
    if not isinstance(block, dict):
        sys.exit("config.json: notizen muss ein Objekt sein. Nichts gelesen oder geändert.")
    eigene = block.get("ausgeschlossene_ordner", [])
    if not isinstance(eigene, list) or not all(isinstance(o, str) for o in eigene):
        sys.exit("config.json: notizen.ausgeschlossene_ordner muss eine Liste von Ordnernamen sein. Nichts gelesen "
                 "oder geändert.")
    return [n for n in (name_norm(o) for o in eigene) if n]


def ausgeschlossen() -> list:
    return eigene_ausschluesse() + IMMER_AUS


def quote(text: str) -> str:
    """Ein Python-String als AppleScript-Literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _lauf(script: str):
    return subprocess.run(
        ["osascript", "-"], input=script, text=True, capture_output=True, timeout=OSA_SEKUNDEN
    )


def osa(script: str) -> str:
    """Ein AppleScript an Notes, die Antwort als Text. Zeitüberschreitung und Fehler enden mit einer Zeile statt
    hängen zu bleiben (Prüfung 20.10.2026)."""
    try:
        fertig = _lauf(script)
        fehler = (fertig.stderr or "").strip()
        if fertig.returncode != 0 and "-600" in fehler:
            # Notes war nicht gestartet. Einmal im Hintergrund starten, dann erneut.
            _lauf('launch application "Notes"')
            time.sleep(2)
            fertig = _lauf(script)
            fehler = (fertig.stderr or "").strip()
    except subprocess.TimeoutExpired:
        sys.exit(f"Notes hat nach {OSA_SEKUNDEN} s nicht geantwortet, abgebrochen. Erneut versuchen, nach add oder "
                 f"replace vorher in Notizen nachsehen, ob die Änderung schon da ist.")
    if fertig.returncode != 0:
        if "-1743" in fehler or "not allowed" in fehler.lower():
            sys.exit("Notes hat die Steuerung abgelehnt. Einmalig erlauben unter Systemeinstellungen > Datenschutz & "
                     "Sicherheit > Automation.")
        if "-600" in fehler or "-10810" in fehler:
            # In der Sandbox sind Apple Events gesperrt, dort hilft auch der Start oben nicht (Probe 21.10.2026)
            sys.exit(f"Notes ist nicht erreichbar (-600). Lief der Befehl in der Sandbox? Dann als eigenen Befehl mit "
                     f'absolutem Pfad aufrufen: python3 "{KIT / "notiz.py"}" <befehl>, ohne cd davor und ohne Pipe '
                     f"oder Umleitung. Sonst Notizen öffnen und erneut versuchen.")
        sys.exit(f"Notes meldet einen Fehler: {sauber(' '.join(fehler.split()))}")
    return fertig.stdout.rstrip("\n")


def saetze(roh: str) -> list:
    return [z.split(TRENNER) for z in roh.split(ZEILE) if z.strip()]


def aufruf_falsch(text: str) -> None:
    """Falscher Aufruf: eine Zeile auf stderr, Code 2 wie in allen Kits."""
    print(text, file=sys.stderr)
    sys.exit(2)


def kette() -> str:
    """AppleScript-Handler frei(c) für den Anfang jedes Skripts, das Ordner durchgeht (F9, Prüfung 20.10.2026): true
    nur, wenn weder der Ordner c noch ein Ordner darüber ausgeschlossen ist. Unterordner heißen anders als ihr
    ausgeschlossener Elternordner und wären sonst offen. Die Kette geht über container (ein Ordner oder das Konto) bis
    zum Konto. Was dort nicht ankommt, auch nach 50 Ebenen, gilt als ausgeschlossen. AppleScript vergleicht Text ohne
    Rücksicht auf Groß- und Kleinschreibung, Leerzeichen zählen dabei nicht (Review 21.10.2026)."""
    gleich = " or ".join(f"cname is {quote(n)}" for n in ausgeschlossen())
    return f'''
    on frei(c)
      tell application "Notes"
        repeat 50 times
          set cname to name of c
          ignoring white space
            if {gleich} then return false
          end ignoring
          set c to container of c
          set typ to class of c
          if typ is account then return true
          if typ is not folder then return false
        end repeat
      end tell
      return false
    end frei
    '''


def teilung() -> str:
    """AppleScript-Handler geteilt(c) (Review 21.10.2026): true, wenn der Ordner c oder ein Ordner darüber geteilt ist,
    dann sehen alle, mit denen er geteilt ist, jede neue Notiz sofort. Ist shared nicht lesbar oder die Kette unklar,
    gilt der Ordner als geteilt (sicher)."""
    return '''
    on geteilt(c)
      tell application "Notes"
        repeat 50 times
          try
            if (shared of c) is not false then return true
          on error
            return true
          end try
          set c to container of c
          set typ to class of c
          if typ is account then return false
          if typ is not folder then return true
        end repeat
      end tell
      return true
    end geteilt
    '''


def ordner_bedingung(nur: str | None) -> str:
    """AppleScript-Test über fo (der Ordner, contents of f) und fname (sein Name): frei nach der Kette, mit --folder
    dazu genau dieser Name. Der Name steht vorn, so fragt die Kette nur passende Ordner."""
    return f"fname is {quote(name_norm(nur))} and my frei(fo)" if nur else "my frei(fo)"


def mehrdeutig(titel: str, orte: list, folge: str) -> None:
    """Mehrere Notizen mit dem Titel: Ordner nennen und mit Code 2 enden (Aufruf mehrdeutig, wie im Kit üblich)."""
    print(f"{len(orte)} Notizen heißen {titel!r} (Ordner: {', '.join(sauber(o) for o in orte)}). Nicht eindeutig, "
          f"{folge} Mit --folder eingrenzen.")
    sys.exit(2)


def nicht_gefunden(titel: str, folge: str = "") -> None:
    """Keine Notiz mit dem Titel, gleich ob --folder unbekannt oder ausgeschlossen ist (Review 21.10.2026)."""
    sys.exit(f"Keine Notiz mit dem Titel {titel!r} gefunden." + (f" {folge}" if folge else ""))


def ordner_gesperrt(ordner: str | None) -> bool:
    """Ist --folder selbst ausgeschlossen? Dann fragt der Befehl Notes gar nicht und meldet sich wie bei einem
    unbekannten Ordner, damit keine Meldung den Ausschluss bestätigt (Review 21.10.2026). Ohne Rücksicht auf Groß- und
    Kleinschreibung wie in AppleScript, sonst käme add --folder privat an Privat vorbei. Unterordner prüft die Kette
    in Notes."""
    return bool(ordner) and name_norm(ordner).casefold() in {n.casefold() for n in ausgeschlossen()}


def ordner_nicht_frei(ordner: str | None) -> None:
    """add findet keinen freien Zielordner: unbekannt, ausgeschlossen oder in einem ausgeschlossenen Ordner."""
    if ordner:
        sys.exit(f"Ordner {ordner} nicht gefunden oder ausgeschlossen. Nichts angelegt, freie Ordner zeigt folders.")
    sys.exit("Der Standardordner von Notizen ist ausgeschlossen. Nichts angelegt, mit --folder einen freien Ordner "
             "angeben.")


def treffer_zeile(z: list) -> str:
    """titel | ordner | geändert für list und search, Nummern im Titel maskiert (Review 21.10.2026). read zeigt den
    Titel vollständig."""
    return " | ".join([kit_basis.maskiere_nummern(sauber(z[0]))] + [sauber(x) for x in z[1:]])


def ist_html(text: str) -> bool:
    """Markdown, das so beginnt, geht als HTML unverändert durch."""
    return text.lstrip().lower().startswith(("<html", "<!doctype", "<div", "<h1"))


def fremdquelle(inhalt: str) -> bool:
    """Lädt das HTML beim Anlegen etwas nach? In einem Tag file:, src ohne data:, srcset oder url() ohne data:, in
    style-Blöcken url() ohne data: oder @import (FREMD_IM_TAG, FREMD_IM_STIL). Text außerhalb der Tags zählt nicht."""
    if any(FREMD_IM_TAG.search(tag.group(0)) for tag in TAG.finditer(inhalt)):
        return True
    klein = inhalt.lower()
    start = klein.find("<style")
    while start != -1:
        ende = klein.find("</style", start)
        ende = len(klein) if ende == -1 else ende
        if FREMD_IM_STIL.search(klein, start, ende):
            return True
        start = klein.find("<style", ende)
    return False


def markdown_zu_html(text: str) -> str:
    """Nur so viel HTML, wie Notes zuverlässig darstellt."""
    if ist_html(text):
        return text
    teile = []
    for roh in text.split("\n"):
        zeile = roh.rstrip()
        # nur das Präfix abschneiden, nie Zeichen aus dem Inhalt (- -20 °C, ## #Hashtag)
        kopf = next(((len(p), tag) for p, tag in (("# ", "h1"), ("## ", "h2"), ("### ", "h3")) if zeile.startswith(p)),
                    None)
        if kopf:
            teile.append(f"<{kopf[1]}>{html.escape(zeile[kopf[0]:].strip())}</{kopf[1]}>")
        elif zeile.startswith("- "):
            teile.append(f"<div>&bull; {html.escape(zeile[2:].strip())}</div>")
        elif zeile.strip() in ("---", "***"):
            teile.append("<hr>")
        elif not zeile.strip():
            teile.append("<br>")
        else:
            teile.append(f"<div>{html.escape(zeile)}</div>")
    return "<html><body>" + "\n".join(teile) + "</body></html>"


def erste_zeile(inhalt: str) -> str:
    """Klartext der ersten nicht leeren Zeile des HTML für Notes, Leerraum zusammengefasst. Gelesen wird ab <body,
    höchstens 20.000 Zeichen: Der Kopf mit title und style ist keine Zeile der Notiz."""
    start = inhalt.lower().find("<body")
    rest = (inhalt[start:] if start != -1 else inhalt)[:20000]
    for zeile in html.unescape(TAG.sub("", BLOCK_ENDE.sub("\n", rest))).split("\n"):
        zeile = " ".join(zeile.split())
        if zeile:
            return zeile
    return ""


def titel_vorn(inhalt: str, titel: str) -> bool:
    """Beginnt der Inhalt schon mit dem Titel (Groß- und Kleinschreibung, Unicode-Form und Leerraum egal)? Dann legt add
    die Notiz ohne name an: Mit name setzt Notes den Titel als eigene Zeile davor, und er stand doppelt in der Notiz
    Ohne name nimmt Notes die erste Zeile als Titel."""
    def norm(s: str) -> str:
        return " ".join(name_norm(s).split()).casefold()
    return bool(titel.strip()) and norm(erste_zeile(inhalt)) == norm(titel)


def text_datei(angabe: str) -> pathlib.Path:
    """Die Textdatei im Kit (kit_basis): nur notiz.html oder notiz.md, ein relativer Name gilt im Kit-Ordner, kein
    Verweis von dort woanders hin und kein harter Verweis."""
    return kit_basis.textdatei(angabe, kit_basis.datenordner(KIT), TEXT_DATEIEN, folge="Nichts geändert.")


def html_fuer_notes(p: pathlib.Path, text: str) -> str:
    """notiz.html geht unverändert durch, Markdown wird schlichtes HTML. Verweise, die Notes nachladen könnte
    (fremdquelle), brechen ab, bevor etwas an Notes geht. Geprüft wird nur HTML, das unverändert durchgeht: Markdown ist
    maskiert und lädt nichts."""
    roh = p.suffix == ".html" or ist_html(text)
    inhalt = text if roh else markdown_zu_html(text)
    if roh and fremdquelle(inhalt):
        sys.exit(f"{p.name} verweist auf eine lokale Datei oder lädt Inhalte von außen (file:, src oder url() ohne data:, "
                 f"srcset, @import). Erlaubt sind Text, Links und eingebettete Bilder (data:). Nichts geändert.")
    return inhalt


def datei_als_html(p: pathlib.Path) -> str:
    """Die geprüfte Textdatei p (aus text_datei) als HTML für Notes."""
    return html_fuer_notes(p, kit_basis.lies_text(p, "Nichts geändert.", MAX_BYTES))


def html_in_tempdatei(inhalt: str) -> pathlib.Path:
    """Langen Text nicht als Argument übergeben, sondern aus einer Datei lesen
    lassen. Das spart Escaping und verträgt jede Zeichenlänge."""
    fd, name = tempfile.mkstemp(suffix=".html", prefix="notiz-")
    os.close(fd)
    p = pathlib.Path(name)
    p.write_text(inhalt, encoding="utf-8")
    return p


# --- Befehle ---------------------------------------------------------------

def cmd_folders(args) -> None:
    """Freie Ordner mit Anzahl der Notizen. Passt ein Eintrag aus config.json zu keinem Ordner (etwa ein Tippfehler,
    der den Ordner offen ließe), nennt es wie reminders.py lists nur die Zahl, keinen Namen (Review 21.10.2026)."""
    eigene = "{" + ", ".join(quote(n) for n in eigene_ausschluesse()) + "}"
    script = f'''
    {kette()}
    tell application "Notes"
      set out to ""
      repeat with f in folders
        set fo to contents of f
        set fname to name of fo
        if {ordner_bedingung(None)} then
          set out to out & fname & "{TRENNER}" & (count of notes of fo) & "{ZEILE}"
        end if
      end repeat
      set namen to name of every folder
      set ohne to 0
      ignoring white space
        repeat with ausschluss in {eigene}
          set da to false
          repeat with nm in namen
            if (contents of nm) is (contents of ausschluss) then
              set da to true
              exit repeat
            end if
          end repeat
          if not da then set ohne to ohne + 1
        end repeat
      end ignoring
      return (ohne as text) & "{ZEILE}" & out
    end tell
    '''
    kopf, _, rest = osa(script).partition(ZEILE)
    if not kopf.strip().isdigit():
        sys.exit("Notes hat eine unerwartete Antwort geliefert. Nichts gelesen.")
    zeilen = saetze(rest)
    if not zeilen:
        print("Keine Ordner gefunden.")
    else:
        print("ordner | notizen")
        for z in zeilen:
            print(f"{sauber(z[0])} | {z[1] if len(z) > 1 else '?'}")
    if int(kopf):
        print(f"Hinweis: {int(kopf)} Einträge in config.json (ausgeschlossene_ordner) passen zu keinem Ordner.")


def keine_notizen(ordner: str | None) -> None:
    """Leeres list. Mit --folder sagt die Zeile, dass der Ordner auch fehlen kann: Ein Tippfehler im Namen sähe sonst
    aus wie ein leerer Ordner (Etappe 2 von v7.3.0). Gleicher Text für einen ausgeschlossenen Ordner, er bestätigt so
    keinen Ausschluss."""
    if ordner:
        print(f"Keine Notizen gefunden: Ordner {sauber(ordner)} ist leer, unbekannt oder ausgeschlossen. Freie Ordner "
              "zeigt folders.")
    else:
        print("Keine Notizen gefunden.")


def cmd_list(args) -> None:
    """Notizen auflisten. --limit beendet beide Schleifen (Review 21.10.2026), ein ausgeschlossener --folder fragt Notes
    nicht und meldet sich wie ein unbekannter."""
    if ordner_gesperrt(args.folder):
        keine_notizen(args.folder)
        return
    grenze = int(args.limit)
    script = f'''
    {kette()}
    tell application "Notes"
      set out to ""
      set zaehler to 0
      repeat with f in folders
        if zaehler >= {grenze} then exit repeat
        set fo to contents of f
        set fname to name of fo
        if {ordner_bedingung(args.folder)} then
          repeat with n in notes of fo
            if zaehler >= {grenze} then exit repeat
            set theNote to contents of n
            set zaehler to zaehler + 1
            set out to out & (name of theNote) & "{TRENNER}" & fname & "{TRENNER}" & ((modification date of theNote) as string) & "{ZEILE}"
          end repeat
        end if
      end repeat
      return out
    end tell
    '''
    zeilen = saetze(osa(script))
    if not zeilen:
        keine_notizen(args.folder)
        return
    print(f"titel | ordner | geändert  {HINWEIS}")
    for z in zeilen:
        print(treffer_zeile(z))


def cmd_read(args) -> None:
    """Genau eine Notiz mit dem Titel lesen. Bei mehreren nennt es die Ordner (Code 2) statt still die erste zu nehmen,
    langer Text endet nach --max-chars Zeichen mit Hinweis (Prüfung 20.10.2026). --html liefert den HTML-Inhalt als
    Grundlage für replace, geteilte Notizen und Ordner (im Zweifel auch) tragen die Zeile Geteilt: ja (Review
    21.10.2026)."""
    if ordner_gesperrt(args.folder):
        nicht_gefunden(args.titel)
    inhalt = "body" if args.html else "plaintext"
    script = f'''
    {kette()}
    {teilung()}
    tell application "Notes"
      set anzahl to 0
      set orte to ""
      repeat with f in folders
        set fo to contents of f
        set fname to name of fo
        if {ordner_bedingung(args.folder)} then
          repeat with n in notes of fo
            set theNote to contents of n
            if (name of theNote) is {quote(args.titel)} then
              set anzahl to anzahl + 1
              set orte to orte & fname & "{ZEILE}"
              if anzahl is 1 then
                set erste to theNote
                set ersterOrdner to fname
                set ersterFo to fo
              end if
            end if
          end repeat
        end if
      end repeat
      if anzahl is 0 then return "NICHTGEFUNDEN"
      if anzahl > 1 then return "MEHRDEUTIG{ZEILE}" & orte
      set teilt to my geteilt(ersterFo)
      try
        if (shared of erste) is not false then set teilt to true
      on error
        set teilt to true
      end try
      return (name of erste) & "{TRENNER}" & ersterOrdner & "{TRENNER}" & ((modification date of erste) as string) & "{TRENNER}" & teilt & "{TRENNER}" & ({inhalt} of erste)
    end tell
    '''
    roh = osa(script)
    if roh.strip() == "NICHTGEFUNDEN":
        nicht_gefunden(args.titel)
    if roh.startswith("MEHRDEUTIG" + ZEILE):
        mehrdeutig(args.titel, [z for z in roh.split(ZEILE)[1:] if z.strip()], "nichts gelesen.")
    teile = roh.split(TRENNER, 4)
    if len(teile) < 4:
        sys.exit("Notes hat eine unerwartete Antwort geliefert. Nichts gelesen.")
    print(f"Titel:    {sauber(teile[0])}")
    print(f"Ordner:   {sauber(teile[1])}")
    print(f"Geändert: {sauber(teile[2])}")
    if teile[3].strip() != "false":  # im Zweifel geteilt
        print("Geteilt:  ja")
    print(HINWEIS)
    print()
    text = sauber(teile[4]) if len(teile) > 4 else ""
    if args.max_chars > 0 and len(text) > args.max_chars:
        text = text[:args.max_chars] + f"\n[gekürzt, {len(text)} Zeichen gesamt, alles mit --max-chars 0]"
    print(text)


def cmd_search(args) -> None:
    """Titel und Inhalt durchsuchen. --limit beendet beide Schleifen (Review 21.10.2026)."""
    grenze = int(args.limit)
    script = f'''
    {kette()}
    tell application "Notes"
      set out to ""
      set zaehler to 0
      repeat with f in folders
        if zaehler >= {grenze} then exit repeat
        set fo to contents of f
        set fname to name of fo
        if {ordner_bedingung(None)} then
          repeat with n in notes of fo
            set theNote to contents of n
            set t to (name of theNote)
            set k to (plaintext of theNote)
            if (t contains {quote(args.text)}) or (k contains {quote(args.text)}) then
              set zaehler to zaehler + 1
              set out to out & t & "{TRENNER}" & fname & "{TRENNER}" & ((modification date of theNote) as string) & "{ZEILE}"
              if zaehler >= {grenze} then exit repeat
            end if
          end repeat
        end if
      end repeat
      return out
    end tell
    '''
    zeilen = saetze(osa(script))
    if not zeilen:
        print(f"Keine Notiz enthält {args.text!r}.")
        return
    print(f"titel | ordner | geändert  {HINWEIS}")
    for z in zeilen:
        print(treffer_zeile(z))


def treffer_ordner(titel: str, ordner: str | None) -> list:
    """Ordner aller Notizen mit genau diesem Titel in den erlaubten Ordnern, nur lesend."""
    script = f'''
    {kette()}
    tell application "Notes"
      set out to ""
      repeat with f in folders
        set fo to contents of f
        set fname to name of fo
        if {ordner_bedingung(ordner)} then
          repeat with n in notes of fo
            set theNote to contents of n
            if (name of theNote) is {quote(titel)} then
              set out to out & fname & "{ZEILE}"
            end if
          end repeat
        end if
      end repeat
      return out
    end tell
    '''
    return [z[0] for z in saetze(osa(script))]


def cmd_add(args) -> None:
    """Neue Notiz nur in einem freien Ordner: mit --folder über die Kette gesucht, nie direkt über den Namen (ein
    Unterordner eines ausgeschlossenen Ordners heißt anders, F9), ohne --folder der Standardordner, auch er nur, wenn
    er frei ist (Prüfung 20.10.2026). Ist der Ordner geteilt, ohne --ausfuehren nur die Vorschau (Review 21.10.2026).
    Ein ausgeschlossener --folder meldet sich an derselben Stelle wie ein unbekannter, nach der Prüfung der Datei."""
    quelle = text_datei(args.file)
    text = kit_basis.lies_text(quelle, "Nichts geändert.", MAX_BYTES)
    inhalt = html_fuer_notes(quelle, text)
    if ordner_gesperrt(args.folder):
        ordner_nicht_frei(args.folder)
    tmp = html_in_tempdatei(inhalt)
    if args.folder:
        suche = f'''
      repeat with f in folders
        set fo to contents of f
        set fname to name of fo
        if {ordner_bedingung(args.folder)} then
          set ziel to fo
          exit repeat
        end if
      end repeat'''
    else:
        suche = '''
      set fo to default folder of default account
      if my frei(fo) then set ziel to fo'''
    vorschau = "" if args.ausfuehren else f'''
      if teilt then return "GETEILT{TRENNER}" & (name of ziel)'''
    eigenschaften = "{body:t}" if titel_vorn(inhalt, args.title) else f"{{name:{quote(args.title)}, body:t}}"
    script = f'''
    {kette()}
    {teilung()}
    set t to (read POSIX file {quote(str(tmp))} as «class utf8»)
    tell application "Notes"
      set ziel to missing value{suche}
      if ziel is missing value then return "NICHTFREI"
      set teilt to my geteilt(ziel){vorschau}
      set n to make new note at ziel with properties {eigenschaften}
      return (name of n) & "{TRENNER}" & (name of ziel) & "{TRENNER}" & teilt
    end tell
    '''
    try:
        roh = osa(script)
    finally:
        tmp.unlink(missing_ok=True)
    if roh.strip() == "NICHTFREI":  # nichts angelegt, die Textdatei bleibt für den nächsten Versuch
        ordner_nicht_frei(args.folder)
    if roh.startswith("GETEILT" + TRENNER):  # nichts angelegt, die Textdatei bleibt für den Aufruf mit --ausfuehren
        print(f"Vorschau, nichts angelegt: {sauber(args.title)} im geteilten Ordner {sauber(roh.split(TRENNER, 1)[1])} "
              f"({len(text)} Zeichen, andere sehen die Notiz sofort). Anlegen mit notiz_geteilt, das zeigt einen "
              "Dialog am Mac.")
        return
    quelle.unlink(missing_ok=True)
    name, wo, teilt = (roh.split(TRENNER) + ["", ""])[:3]
    print(f"Angelegt: {sauber(name)} in {sauber(wo) or args.folder or 'Standardordner'}"
          + (" (geteilt, andere sehen die Notiz)" if teilt.strip() == "true" else ""))


def cmd_replace(args) -> None:
    """Den ganzen Inhalt einer Notiz ersetzen. Notes nimmt danach die erste Zeile als Titel: Weicht er vom alten ab,
    kommt ein Hinweis mit dem neuen (Review 21.10.2026). Ist die Notiz oder ihr Ordner geteilt (im Zweifel auch), ohne
    --ausfuehren nur die Vorschau: Andere sähen die Änderung sofort."""
    quelle = text_datei(args.file)
    inhalt = datei_als_html(quelle)
    orte = [] if ordner_gesperrt(args.folder) else treffer_ordner(args.titel, args.folder)
    if not orte:
        nicht_gefunden(args.titel, "Nichts geändert.")
    if len(orte) > 1:
        mehrdeutig(args.titel, orte, "nichts geändert.")
    tmp = html_in_tempdatei(inhalt)
    vorschau = "" if args.ausfuehren else f'''
              set teilt to my geteilt(fo)
              try
                if (shared of theNote) is not false then set teilt to true
              on error
                set teilt to true
              end try
              if teilt then return "GETEILT{TRENNER}" & fname'''
    script = f'''
    {kette()}
    {teilung()}
    set t to (read POSIX file {quote(str(tmp))} as «class utf8»)
    tell application "Notes"
      repeat with f in folders
        set fo to contents of f
        set fname to name of fo
        if {ordner_bedingung(args.folder)} then
          repeat with n in notes of fo
            set theNote to contents of n
            if (name of theNote) is {quote(args.titel)} then{vorschau}
              set body of theNote to t
              return fname & "{TRENNER}" & (name of theNote)
            end if
          end repeat
        end if
      end repeat
      return "NICHTGEFUNDEN"
    end tell
    '''
    try:
        roh = osa(script)
    finally:
        tmp.unlink(missing_ok=True)
    if roh.strip() == "NICHTGEFUNDEN":
        nicht_gefunden(args.titel, "Nichts geändert.")
    if roh.startswith("GETEILT" + TRENNER):  # nichts geändert, die Textdatei bleibt für notiz_geteilt
        print(f"Vorschau, nichts geändert: {args.titel} liegt geteilt im Ordner {sauber(roh.split(TRENNER, 1)[1])}, "
              "andere sähen die Änderung sofort. Ersetzen mit notiz_geteilt und ersetzen, das zeigt einen Dialog am "
              "Mac.")
        return
    quelle.unlink(missing_ok=True)
    ordner, _, neu = roh.partition(TRENNER)
    print(f"Ersetzt: {args.titel} in {sauber(ordner)}")
    neu = sauber(neu).strip()
    if neu and name_norm(neu).casefold() != name_norm(args.titel).casefold():
        print(f"Achtung: Notes hat die Notiz in {neu!r} umbenannt (erste Zeile des Inhalts). Soll der alte Titel "
              f"bleiben, ihn als erste Zeile in notiz.html setzen und mit replace {neu!r} erneut ersetzen.")


def main(argv=None) -> None:
    # ohne Abkürzungen: --fol gälte sonst als --folder, und eine Prüfung auf den Schalter sähe ihn nicht
    p = argparse.ArgumentParser(description="Apple Notes lesen und schreiben.", allow_abbrev=False)
    sub = p.add_subparsers(dest="befehl", required=True)

    sub.add_parser("folders", help="Ordner auflisten", allow_abbrev=False).set_defaults(func=cmd_folders)

    pl = sub.add_parser("list", help="Notizen auflisten", allow_abbrev=False)
    pl.add_argument("--folder")
    pl.add_argument("--limit", type=int, default=25)
    pl.set_defaults(func=cmd_list)

    pr = sub.add_parser("read", help="Inhalt einer Notiz", allow_abbrev=False)
    pr.add_argument("titel")
    pr.add_argument("--folder")
    pr.add_argument("--max-chars", type=int, default=LESE_MAX, help=f"Text nach N Zeichen kürzen (Standard {LESE_MAX}, "
                                                                    f"0 = alles)")
    pr.add_argument("--html", action="store_true", help="HTML-Inhalt statt Klartext, Grundlage für replace")
    pr.set_defaults(func=cmd_read)

    ps = sub.add_parser("search", help="Titel und Inhalt durchsuchen", allow_abbrev=False)
    ps.add_argument("text")
    ps.add_argument("--limit", type=int, default=25)
    ps.set_defaults(func=cmd_search)

    pa = sub.add_parser("add", help="Notiz anlegen", allow_abbrev=False)
    pa.add_argument("--title", required=True)
    pa.add_argument("--file", required=True, help="notiz.html oder notiz.md im Kit-Ordner")
    pa.add_argument("--folder")
    pa.add_argument("--ausfuehren", action="store_true", help="in einem geteilten Ordner wirklich anlegen (fragt nach)")
    pa.set_defaults(func=cmd_add)

    px = sub.add_parser("replace", help="Inhalt einer Notiz ersetzen", allow_abbrev=False)
    px.add_argument("titel")
    px.add_argument("--file", required=True, help="notiz.html oder notiz.md im Kit-Ordner")
    px.add_argument("--folder")
    px.add_argument("--ausfuehren", action="store_true", help="in einem geteilten Ordner wirklich ersetzen")
    px.set_defaults(func=cmd_replace)

    vorn, rest = kit_basis.schalter_vorn(sys.argv[1:] if argv is None else list(argv), ("--ausfuehren",))
    args = p.parse_args(rest + vorn)  # --ausfuehren gehört zu add und replace, steht aber direkt hinter dem Skript
    if getattr(args, "limit", 1) < 1:  # Review 21.10.2026: sonst still "Keine Notizen gefunden"
        aufruf_falsch("--limit braucht 1 oder mehr, etwa --limit 25. Nichts gelesen.")
    if getattr(args, "max_chars", 0) < 0:
        aufruf_falsch("--max-chars braucht 0 oder mehr, 0 zeigt alles. Nichts gelesen.")
    args.func(args)


if __name__ == "__main__":
    kit_basis.starten(main, __file__)
