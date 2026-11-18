#!/usr/bin/env python3
"""Apple Notes lesen und schreiben.

Der Weg zu Notes, ohne osascript allgemein freizugeben: Dieses Skript ruft
osascript intern auf, genau wie mail.py und imessage.py (Plugin chat)
es für ihre Apps tun. Bash(osascript *) bleibt im Code-Tab gesperrt.

Befehle (der Server ruft sie auf, von Hand immer mit absolutem Pfad: python3 "<Plugin>/notiz.py" ...):
  folders                                     Ordner mit Anzahl der Notizen
  list [--folder X] [--limit N]               Notizen auflisten, neueste zuerst
  read <titel> [--folder X] [--max-chars N] [--html]
                                              Inhalt als Text, höchstens 20000 Zeichen (0 = alles), --html als HTML,
                                              mit der Zeile Stand für replace und append
  search <text> [--folder X] [--limit N]      Titel und Inhalt durchsuchen, neueste zuerst
  [--ausfuehren] add --title X --file notiz.html [--folder Z]
                                              Notiz anlegen, Inhalt aus der Datei im Plugin, in geteilten Ordnern erst
                                              mit --ausfuehren direkt hinter dem Skript (an anderer Stelle bricht das
                                              Skript ab)
  [--ausfuehren] replace <titel> --file notiz.html --stand S [--folder X] [--links-entfernen]
                                              Inhalt einer Notiz ersetzen, in geteilten Ordnern erst mit --ausfuehren
  [--ausfuehren] append <titel> --file notiz.md --stand S [--wo unten|oben] [--folder X]
                                              Text unten oder direkt unter dem Titel anfügen, sonst wie replace

Löschen gibt es bewusst nicht, auch nicht auf Ansage.

Text kommt nur aus notiz.html oder notiz.md im Kit-Ordner (ein Name gilt dort, egal wo die Shell
steht), nie aus anderen Dateien: add läuft ohne Rückfrage außerhalb der Sandbox, eine untergeschobene
Anweisung könnte sonst etwa ein Firmendokument in iCloud-Notizen holen. Nach Erfolg löscht das Skript
die Datei. HTML (notiz.html, oder Text, der mit <html, <!doctype, <div oder <h1 beginnt) geht
unverändert durch, so zeigt Notes Tabellen und Links. Markdown wird in das schlichte HTML umgewandelt,
das Notes zuverlässig darstellt (Überschriften, Absätze, Striche). Verweise, die Notes nachladen könnte
(file: in einem Tag, src oder url() ohne data:, srcset, @import), brechen ab, bevor etwas an Notes geht.

Geteilte Ordner (shared in Notes, auch für einen Ordner darüber, im Zweifel gilt geteilt): Andere sehen
jede neue Notiz und jede Änderung sofort. add, replace und append zeigen dort ohne --ausfuehren nur eine Vorschau
und ändern nichts, die Textdatei bleibt (Dialog nur, wo andere es sehen). Eine selbst geteilte Notiz in einem eigenen
Ordner gilt ebenso als geteilt. read zeigt dann die Zeile "Geteilt: ja".

read, replace und append nehmen eine Notiz nur, wenn genau eine den Titel trägt (in den erlaubten Ordnern, mit
--folder eingegrenzt). Sonst nennen sie die Ordner der Treffer, lesen oder ändern nichts (Exit 2).
replace setzt den ganzen Inhalt neu, Grundlage bei formatierten Notizen ist read --html (der Klartext
verliert Formatierung, Tabellen und Links). Notes nimmt die erste Zeile als Titel, ein neuer Titel kommt
als Hinweis.

Schutz beim Ändern (Etappe 3 von v7.3.0, Vorbild expectedContentHash in apple-notes-mcp): replace und append
verlangen --stand aus der Zeile Stand von read (Änderungsdatum mit Sekunden). Ein erstes AppleScript liest Stand,
Anhänge, Teilung und HTML, ein zweites schreibt und prüft davor im selben Skript Stand und Länge des HTML noch einmal.
Hat sich die Notiz geändert, hat sie Anhänge (Notes verliert sie beim Neuschreiben des Body, auch beim Anfügen) oder
fehlt in der neuen Fassung ein Link der alten (replace ohne --links-entfernen), ändert sich nichts. Nach add, replace
und append liest das Skript den Klartext zurück und nennt Abweichungen vom geschriebenen Text (Nachkontrolle).

Ordner in config.json unter notizen.ausgeschlossene_ordner werden mit allen Unterordnern nie gelesen,
durchsucht oder beschrieben, auch nicht in anderer Groß- und Kleinschreibung, Unicode-Form oder mit
anderen Leerzeichen. Der Papierkorb ist immer ausgenommen. Ein ausgeschlossener --folder meldet sich wie
ein unbekannter. add ohne --folder legt nur an, wenn der Standardordner frei ist. Eine fehlende oder kaputte
config.json bricht ab, statt die Ausschlüsse still fallen zu lassen.

Tempo und Abbruch (Etappe 3 von v7.3.0): list, search und die Suche nach dem Titel holen je Ordner Namen, IDs, Datum
und Klartext aller Notizen in einem Zug (name of notes of fo) und vergleichen danach lokal, statt Notes je Notiz zu
fragen. Scheitert der Zug, liest das Skript den Ordner Notiz für Notiz und überspringt, was nicht lesbar ist, die
Ausgabe nennt es. list und search hören nach SUCH_SEKUNDEN auf und sagen, dass nicht alles durchsucht ist. Jedes
Skript läuft in "with timeout of AS_SEKUNDEN seconds", antwortet Notes nicht, bricht osascript nach OSA_SEKUNDEN ab.

AppleScript-Fallstrick: In "repeat with n in notes of f" ist n nur eine Referenz, "container of n"
scheitert damit. Deshalb läuft alles über eine Ordnerschleife aussen und "contents of n" innen. Ordner
ebenso: erst "contents of f", dann fragt die Kette der Ausschlüsse (Handler frei) "container". Eine gefundene Notiz
hält das Skript über ihre ID (note id ...), denn eine Referenz über die Nummer im Ordner zeigt nach einer Änderung
auf eine andere Notiz.
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
TEXT_DATEIEN = ("notiz.html", "notiz.md")  # einzige Quellen für add, replace und append, im Kit-Ordner
MAX_BYTES = 2_000_000
OSA_SEKUNDEN = 90  # wie mail.py unter den 120 s des Bash-Werkzeugs, damit die eigene Meldung ankommt
AS_SEKUNDEN = 80   # with timeout im AppleScript wie in mail.py: Notes meldet -1712 vor dem Abbruch von außen
SUCH_SEKUNDEN = 60  # list und search hören danach auf und nennen es, statt am Ende gar nichts zu liefern
LESE_MAX = 20_000  # Zeichen, die read ohne --max-chars zeigt: Eine riesige Notiz verdrängt sonst den Verlauf
STAND = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")  # Zeile Stand von read, JJJJ-MM-TT HH:MM:SS
# Verweise, die Notes beim Anlegen nachladen könnte (vorsorglich, Review 21.10.2026): file: in einem Tag holte eine
# lokale Datei in iCloud, src ohne data:, srcset, url() ohne data: und @import laden Bilder und Stile von außen. TAG
# ist ein Tag mit Attributen in Anführungszeichen, das > am Ende ist optional: So scheitert kein Treffer, und die Suche
# bleibt bei vielen offenen spitzen Klammern linear (ein Muster mit <[^>]* brauchte für 60 KB schon 26 s)
TAG = re.compile(r"<(?:[^<>\"']|\"[^\"]*\"|'[^']*')*>?")
FREMD_IM_TAG = re.compile(r"\bfile:|\bsrcset\s*=|\bsrc\s*=\s*(?![\"']?\s*data:)|\burl\(\s*(?![\"']?\s*data:)", re.I)
FREMD_IM_STIL = re.compile(r"url\(\s*(?![\"']?\s*data:)|@import")
# Zeilenende im HTML für Notes: Zeilenumbruch, Ende eines Blocks, Trennlinie (erste_zeile)
BLOCK_ENDE = re.compile(r"<br\s*/?>|</(?:div|p|h[1-6]|li|tr|td|th|ul|ol|table)\s*>|<hr\b[^<>]*>", re.I)
HREF = re.compile(r"""\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'<>]+))""", re.I)
KOERPER = re.compile(r"<body\b[^<>]*>(.*)</body\s*>", re.I | re.S)
KOPF_BLOECKE = re.compile(r"<(style|script|head|title)\b.*?</\1\s*>", re.I | re.S)
# schließende Tags direkt nach der Titelzeile, append --wo oben setzt danach an (<div><h1>Titel</h1></div>)
SCHLIESSEND = re.compile(r"(?:\s*</(?:div|p|h[1-6]|b|i|u|strong|em|span|font)\s*>)*", re.I)


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


def zeitablauf(sekunden: int) -> None:
    sys.exit(f"Notes hat nach {sekunden} s nicht geantwortet, abgebrochen. Erneut versuchen, nach add, replace oder "
             f"append vorher in Notizen nachsehen, ob die Änderung schon da ist.")


def osa(script: str) -> str:
    """Ein AppleScript an Notes, die Antwort als Text. Zeitüberschreitung und Fehler enden mit einer Zeile statt
    hängen zu bleiben (Prüfung 20.10.2026). -1712 ist das with timeout im Skript selbst (Etappe 3 von v7.3.0)."""
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
        zeitablauf(OSA_SEKUNDEN)
    if fertig.returncode != 0:
        if "-1743" in fehler or "not allowed" in fehler.lower():
            sys.exit("Notes hat die Steuerung abgelehnt. Einmalig erlauben unter Systemeinstellungen > Datenschutz & "
                     "Sicherheit > Automation.")
        if "-1712" in fehler:
            zeitablauf(AS_SEKUNDEN)
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


def unerwartet(folge: str) -> None:
    sys.exit(f"Notes hat eine unerwartete Antwort geliefert. {folge}")


# --- AppleScript-Bausteine --------------------------------------------------

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


def helfer() -> str:
    """Handler ohne Notes (Etappe 3 von v7.3.0): stempel(d) schreibt ein Datum als JJJJ-MM-TT HH:MM:SS, den Stand für
    replace und append, eindeutig und sortierbar (as string hinge an der Systemsprache und hat nicht immer Sekunden).
    jetzt() für das Zeitbudget der Suche, verbinden(liste, trenner) fügt Text in einem Zug zusammen: out & ... in einer
    Schleife kopiert bei vielen Notizen jedes Mal alles."""
    return '''
    on zwei(x)
      return text -2 thru -1 of ("0" & x)
    end zwei
    on stempel(d)
      set s to time of d
      return ((year of d) as text) & "-" & my zwei((month of d) as integer) & "-" & my zwei(day of d) & " " & my zwei(s div 3600) & ":" & my zwei((s mod 3600) div 60) & ":" & my zwei(s mod 60)
    end stempel
    on jetzt()
      return current date
    end jetzt
    on verbinden(liste, trenner)
      set vorher to AppleScript's text item delimiters
      set AppleScript's text item delimiters to trenner
      set ergebnis to liste as text
      set AppleScript's text item delimiters to vorher
      return ergebnis
    end verbinden
    '''


def je_ordner_lesen(felder: list) -> str:
    """AppleScript-Teil im Ordner fo (Etappe 3 von v7.3.0): je (Variable, Eigenschaft) aus felder eine Liste über alle
    Notizen in einem Zug, etwa set namen to name of notes of fo. Scheitert das oder passen die Längen nicht (eine Notiz
    kam dazwischen), liest es Notiz für Notiz und zählt nicht lesbare in fehlNotizen, einen nicht lesbaren Ordner in
    fehlOrdner. Beide Zähler legt der Aufrufer vorher an."""
    erste = felder[0][0]
    zug = "\n".join(f"            set {v} to {e} of notes of fo" for v, e in felder)
    gleich = " and ".join(f"(count of {v}) is (count of {erste})" for v, _ in felder[1:]) or "true"
    leer = "\n".join(f"          set {v} to {{}}" for v, _ in felder)
    holen = "\n".join(f"                set w{i} to {e} of nn" for i, (_, e) in enumerate(felder))
    merken = "\n".join(f"                set end of {v} to w{i}" for i, (v, _) in enumerate(felder))
    return f'''
          try
{zug}
            set ok to {gleich}
          on error
            set ok to false
          end try
          if not ok then
{leer}
            try
              set liste to notes of fo
            on error
              set liste to {{}}
              set end of fehlOrdner to fname
            end try
            repeat with n in liste
              try
                set nn to contents of n
{holen}
{merken}
              on error
                set fehlNotizen to fehlNotizen + 1
              end try
            end repeat
          end if'''


def ordner_bedingung(nur: str | None) -> str:
    """AppleScript-Test über fo (der Ordner, contents of f) und fname (sein Name): frei nach der Kette, mit --folder
    dazu genau dieser Name. Der Name steht vorn, so fragt die Kette nur passende Ordner."""
    return f"fname is {quote(name_norm(nur))} and my frei(fo)" if nur else "my frei(fo)"


def titel_suche(titel: str, ordner: str | None) -> str:
    """AppleScript-Teil für read, replace und append: zählt die Notizen mit genau dem Titel in den freien Ordnern, Namen
    und IDs je Ordner in einem Zug. Kein Treffer: NICHTGEFUNDEN mit den nicht lesbaren Notizen und Ordnern, mehrere:
    MEHRDEUTIG mit den Ordnern. Sonst stehen erste (über die ID), ersterOrdner und ersterFo bereit."""
    return f'''
      set anzahl to 0
      set orte to {{}}
      set fehlNotizen to 0
      set fehlOrdner to {{}}
      repeat with f in folders
        set fo to contents of f
        set fname to name of fo
        if {ordner_bedingung(ordner)} then{je_ordner_lesen([("namen", "name"), ("ids", "id")])}
          repeat with i from 1 to count of namen
            if item i of namen is {quote(titel)} then
              set anzahl to anzahl + 1
              set end of orte to fname
              if anzahl is 1 then
                set erste to note id (item i of ids)
                set ersterOrdner to fname
                set ersterFo to fo
              end if
            end if
          end repeat
        end if
      end repeat
      if anzahl is 0 then return "NICHTGEFUNDEN{TRENNER}" & fehlNotizen & "{TRENNER}" & my verbinden(fehlOrdner, ", ")
      if anzahl > 1 then return "MEHRDEUTIG{ZEILE}" & my verbinden(orte, "{ZEILE}")'''


def teilt_notiz(notiz: str, ordner: str) -> str:
    """AppleScript-Teil: teilt ist true, wenn der Ordner oder die Notiz selbst geteilt ist, im Zweifel auch."""
    return f'''
      set teilt to my geteilt({ordner})
      try
        if (shared of {notiz}) is not false then set teilt to true
      on error
        set teilt to true
      end try'''


# --- Meldungen ---------------------------------------------------------------

def mehrdeutig(titel: str, orte: list, folge: str) -> None:
    """Mehrere Notizen mit dem Titel: Ordner nennen und mit Code 2 enden (Aufruf mehrdeutig, wie im Kit üblich)."""
    print(f"{len(orte)} Notizen heißen {titel!r} (Ordner: {', '.join(sauber(o) for o in orte)}). Nicht eindeutig, "
          f"{folge} Mit --folder eingrenzen.")
    sys.exit(2)


def unlesbar(anzahl, ordner: str) -> str:
    """Satz zu übersprungenen Notizen und Ordnern, leer wenn nichts übersprungen ist."""
    teile = []
    if str(anzahl).strip().isdigit() and int(anzahl):
        teile.append(f"{int(anzahl)} Notizen nicht lesbar (etwa gesperrt)")
    if ordner.strip():
        teile.append(f"Ordner {sauber(ordner.strip())} nicht lesbar")
    return (", ".join(teile) + ", übersprungen.") if teile else ""


def nicht_gefunden(titel: str, folge: str = "", roh: str = "") -> None:
    """Keine Notiz mit dem Titel, gleich ob --folder unbekannt oder ausgeschlossen ist (Review 21.10.2026). roh ist die
    Antwort NICHTGEFUNDEN mit den übersprungenen Notizen und Ordnern: Die Notiz kann dort liegen."""
    teile = roh.split(TRENNER) + ["", ""]
    zusatz = unlesbar(teile[1], teile[2])
    sys.exit(f"Keine Notiz mit dem Titel {titel!r} gefunden." + (f" {zusatz}" if zusatz else "")
             + (f" {folge}" if folge else ""))


def treffer_pruefen(roh: str, titel: str, folge: str, mit_folge: bool = True) -> None:
    """Gemeinsame Antworten der Titelsuche: kein Treffer oder mehrere."""
    if roh.startswith("NICHTGEFUNDEN"):
        nicht_gefunden(titel, folge if mit_folge else "", roh)
    if roh.startswith("MEHRDEUTIG" + ZEILE):
        mehrdeutig(titel, [z for z in roh.split(ZEILE)[1:] if z.strip()], folge[:1].lower() + folge[1:])


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


# --- HTML --------------------------------------------------------------------

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


def klartext(inhalt: str) -> str:
    """Der Text, den Notes aus dem HTML zeigen sollte: ab <body, ohne style, script und Kopf, Blockenden als Zeilen."""
    start = inhalt.lower().find("<body")
    rest = KOPF_BLOECKE.sub(" ", inhalt[start:] if start != -1 else inhalt)
    return html.unescape(TAG.sub("", BLOCK_ENDE.sub("\n", rest)))


def woerter(text: str) -> list:
    """Wörter und Zahlen in Reihenfolge, NFC und ohne Groß- und Kleinschreibung: Notes schreibt das HTML um (Striche,
    Leerraum, Entities), die Wörter bleiben."""
    return re.findall(r"\w+", unicodedata.normalize("NFC", text).casefold())


def nachkontrolle(geschrieben: str, in_notes: str, titel: str = "") -> str:
    """Zeile zur Nachkontrolle (Etappe 3 von v7.3.0): leer, wenn der Klartext in Notes dieselben Wörter in derselben
    Reihenfolge hat wie das geschriebene HTML. Bei add mit Titel darf der Titel davor stehen."""
    soll, ist = woerter(klartext(geschrieben)), woerter(in_notes)
    if ist == soll or (titel and ist == woerter(titel) + soll):
        return ""
    i = next((k for k, (a, b) in enumerate(zip(soll, ist)) if a != b), min(len(soll), len(ist)))
    erwartet = soll[i] if i < len(soll) else "(Ende)"
    gefunden = ist[i] if i < len(ist) else "(Ende)"
    return (f"Nachkontrolle: Notes zeigt nicht genau den geschriebenen Text ({len(soll)} Wörter geschrieben, "
            f"{len(ist)} in Notes, ab Wort {i + 1} erwartet {sauber(erwartet)!r}, in Notes {sauber(gefunden)!r}). Mit "
            f"notiz_lesen prüfen.")


def links(inhalt: str) -> set:
    """Alle href aus den Tags, Entities aufgelöst, leere fallen weg."""
    gefunden = set()
    for tag in TAG.finditer(inhalt):
        for m in HREF.finditer(tag.group(0)):
            wert = html.unescape(next(g for g in m.groups() if g is not None)).strip()
            if wert:
                gefunden.add(wert)
    return gefunden


def koerper(inhalt: str) -> str:
    """Das Innere von <body> oder ohne body das HTML ohne doctype, html und head: der Teil, den append einsetzt."""
    m = KOERPER.search(inhalt)
    if m:
        return m.group(1)
    ohne_kopf = re.sub(r"<head\b.*?</head\s*>", "", inhalt, flags=re.I | re.S)
    return re.sub(r"</?html\b[^<>]*>|<!doctype[^<>]*>", "", ohne_kopf, flags=re.I)


def ergaenzt(alt: str, neu: str, wo: str) -> str:
    """Das HTML der Notiz mit dem neuen Teil: unten vor </body> oder am Ende, oben direkt nach der ersten Zeile mit Text
    (dem Titel) samt den schließenden Tags danach. Ohne Zeilenende nach dem Titel geht der Teil ans Ende."""
    teil = koerper(neu)
    if wo == "oben":
        start = alt.lower().find("<body")
        start = alt.find(">", start) + 1 if start != -1 else 0
        for m in BLOCK_ENDE.finditer(alt, start):
            if html.unescape(TAG.sub("", alt[start:m.start()])).strip():
                ende = SCHLIESSEND.match(alt, m.end()).end()
                return alt[:ende] + teil + alt[ende:]
    ende = alt.lower().rfind("</body")
    return alt[:ende] + teil + alt[ende:] if ende != -1 else alt + teil


# --- Textdatei ---------------------------------------------------------------

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
      with timeout of {AS_SEKUNDEN} seconds
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
      end timeout
    end tell
    '''
    kopf, _, rest = osa(script).partition(ZEILE)
    if not kopf.strip().isdigit():
        unerwartet("Nichts gelesen.")
    zeilen = saetze(rest)
    if not zeilen:
        print("Keine Ordner gefunden.")
    else:
        print("ordner | notizen")
        for z in zeilen:
            print(f"{sauber(z[0])} | {z[1] if len(z) > 1 else '?'}")
    if int(kopf):
        print(f"Hinweis: {int(kopf)} Einträge in config.json (ausgeschlossene_ordner) passen zu keinem Ordner.")


def sammeln(ordner: str | None, such: str | None) -> tuple:
    """Notizen der freien Ordner für list (such None) und search (Etappe 3 von v7.3.0): je Ordner Namen und Datum, bei
    search dazu der Klartext, in einem Zug, verglichen wird im Skript ohne weitere Fragen an Notes. Nach SUCH_SEKUNDEN
    hört es auf. (Zeilen titel, ordner, stand), (nicht lesbare Notizen, abgebrochen, nicht lesbare Ordner, Konten)."""
    felder = [("namen", "name"), ("daten", "modification date")]
    zeile = f'set end of treffer to (item i of namen) & "{TRENNER}" & fname & "{TRENNER}" & my stempel(item i of daten)'
    if such is None:
        vergleich = f"            {zeile}"
    else:
        felder.append(("texte", "plaintext"))
        q = quote(such)
        vergleich = f'''            if ((item i of namen) contains {q}) or ((item i of texte) contains {q}) then
              {zeile}
            end if'''
    script = f'''
    {kette()}
    {helfer()}
    tell application "Notes"
      with timeout of {AS_SEKUNDEN} seconds
      set beginn to my jetzt()
      set treffer to {{}}
      set fehlNotizen to 0
      set fehlOrdner to {{}}
      set abbruch to 0
      repeat with f in folders
        if ((my jetzt()) - beginn) > {SUCH_SEKUNDEN} then
          set abbruch to 1
          exit repeat
        end if
        set fo to contents of f
        set fname to name of fo
        if {ordner_bedingung(ordner)} then{je_ordner_lesen(felder)}
          repeat with i from 1 to count of namen
{vergleich}
          end repeat
        end if
      end repeat
      set konten to name of every account
      end timeout
    end tell
    return (fehlNotizen as text) & "{TRENNER}" & abbruch & "{TRENNER}" & my verbinden(fehlOrdner, ", ") & "{TRENNER}" & my verbinden(konten, ", ") & "{ZEILE}" & my verbinden(treffer, "{ZEILE}")
    '''
    kopf, _, rest = osa(script).partition(ZEILE)
    info = kopf.split(TRENNER)
    if len(info) < 4 or not info[0].strip().isdigit():
        unerwartet("Nichts gelesen.")
    zeilen = sorted(saetze(rest), key=lambda z: z[2] if len(z) > 2 else "", reverse=True)  # neueste zuerst
    return zeilen, info


def ausgeben(zeilen: list, grenze: int) -> None:
    print(f"titel | ordner | geändert  {HINWEIS}")
    for z in zeilen[:grenze]:
        print(treffer_zeile(z))
    if len(zeilen) > grenze:
        print(f"{len(zeilen) - grenze} weitere, mehr mit --limit.")


def nachsatz(info: list, mit_konten: bool) -> None:
    """Was nicht oder nicht ganz durchsucht ist (Etappe 2 und 3 von v7.3.0): Abbruch nach SUCH_SEKUNDEN, nicht lesbare
    Notizen und Ordner, ohne --folder die Konten. Ein in Notes deaktiviertes Konto taucht hier nicht auf, Notes kennt es
    dann gar nicht: Die Zeile Durchsucht macht das sichtbar."""
    fehl_notizen, abbruch, fehl_ordner, konten = (info + ["", "", "", ""])[:4]
    if abbruch.strip() == "1":
        print(f"Abgebrochen nach {SUCH_SEKUNDEN} s: Nicht alle Ordner durchsucht, es kann weitere Treffer geben. Mit "
              f"Ordner eingrenzen.")
    satz = unlesbar(fehl_notizen, fehl_ordner)
    if satz:
        print(satz)
    if mit_konten:
        print(f"Durchsucht: Konten {sauber(konten.strip())}." if konten.strip()
              else "Nichts durchsucht: Notes zeigt kein Konto.")


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
    """Die neuesten Notizen. Ein ausgeschlossener --folder fragt Notes nicht und meldet sich wie ein unbekannter. Die
    Grenze gilt nach dem Sortieren, Notes liefert alle Namen und Daten je Ordner in einem Zug."""
    if ordner_gesperrt(args.folder):
        keine_notizen(args.folder)
        return
    zeilen, info = sammeln(args.folder, None)
    if not zeilen:
        keine_notizen(args.folder)
    else:
        ausgeben(zeilen, int(args.limit))
    nachsatz(info, not args.folder)


def cmd_search(args) -> None:
    """Titel und Inhalt durchsuchen, neueste zuerst, mit --folder in einem Ordner (Etappe 3 von v7.3.0)."""
    leer = f"Keine Notiz enthält {args.text!r}" + (f": Ordner {sauber(args.folder)} ist leer, unbekannt oder "
                                                    f"ausgeschlossen, oder ohne Treffer." if args.folder else ".")
    if ordner_gesperrt(args.folder):  # gleiche Zeile wie ein unbekannter Ordner, sie bestätigt keinen Ausschluss
        print(leer)
        return
    zeilen, info = sammeln(args.folder, args.text)
    if not zeilen:
        print(leer)
    else:
        ausgeben(zeilen, int(args.limit))
    nachsatz(info, not args.folder)


def cmd_read(args) -> None:
    """Genau eine Notiz mit dem Titel lesen. Bei mehreren nennt es die Ordner (Code 2) statt still die erste zu nehmen,
    langer Text endet nach --max-chars Zeichen mit Hinweis (Prüfung 20.10.2026). --html liefert den HTML-Inhalt als
    Grundlage für replace, geteilte Notizen und Ordner (im Zweifel auch) tragen die Zeile Geteilt: ja (Review
    21.10.2026). Stand ist das Änderungsdatum mit Sekunden für replace und append, Anhänge nennt eine eigene Zeile
    (Etappe 3 von v7.3.0)."""
    if ordner_gesperrt(args.folder):
        nicht_gefunden(args.titel)
    inhalt = "body" if args.html else "plaintext"
    script = f'''
    {kette()}
    {teilung()}
    {helfer()}
    tell application "Notes"
      with timeout of {AS_SEKUNDEN} seconds{titel_suche(args.titel, args.folder)}{teilt_notiz("erste", "ersterFo")}
      try
        set anh to (count of attachments of erste) as text
      on error
        set anh to "?"
      end try
      return (name of erste) & "{TRENNER}" & ersterOrdner & "{TRENNER}" & my stempel(modification date of erste) & "{TRENNER}" & teilt & "{TRENNER}" & anh & "{TRENNER}" & ({inhalt} of erste)
      end timeout
    end tell
    '''
    roh = osa(script)
    treffer_pruefen(roh, args.titel, "Nichts gelesen.", mit_folge=False)
    teile = roh.split(TRENNER, 5)
    if len(teile) < 5:
        unerwartet("Nichts gelesen.")
    print(f"Titel:    {sauber(teile[0])}")
    print(f"Ordner:   {sauber(teile[1])}")
    print(f"Stand:    {sauber(teile[2])}")
    if teile[3].strip() != "false":  # im Zweifel geteilt
        print("Geteilt:  ja")
    anh = teile[4].strip()
    if anh != "0":
        print(f"Anhänge:  {anh if anh.isdigit() else 'nicht prüfbar'} (ersetzen und ergänzen lehnen ab)")
    print(HINWEIS)
    print()
    text = sauber(teile[5]) if len(teile) > 5 else ""
    if args.max_chars > 0 and len(text) > args.max_chars:
        text = text[:args.max_chars] + f"\n[gekürzt, {len(text)} Zeichen gesamt, alles mit --max-chars 0]"
    print(text)


def cmd_add(args) -> None:
    """Neue Notiz nur in einem freien Ordner: mit --folder über die Kette gesucht, nie direkt über den Namen (ein
    Unterordner eines ausgeschlossenen Ordners heißt anders, F9), ohne --folder der Standardordner, auch er nur, wenn
    er frei ist (Prüfung 20.10.2026). Ist der Ordner geteilt, ohne --ausfuehren nur die Vorschau (Review 21.10.2026).
    Ein ausgeschlossener --folder meldet sich an derselben Stelle wie ein unbekannter, nach der Prüfung der Datei.
    Danach Stand und Nachkontrolle (Etappe 3 von v7.3.0)."""
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
    mit_name = not titel_vorn(inhalt, args.title)
    eigenschaften = f"{{name:{quote(args.title)}, body:t}}" if mit_name else "{body:t}"
    script = f'''
    {kette()}
    {teilung()}
    {helfer()}
    set t to (read POSIX file {quote(str(tmp))} as «class utf8»)
    tell application "Notes"
      with timeout of {AS_SEKUNDEN} seconds
      set ziel to missing value{suche}
      if ziel is missing value then return "NICHTFREI"
      set teilt to my geteilt(ziel){vorschau}
      set n to make new note at ziel with properties {eigenschaften}
      return (name of n) & "{TRENNER}" & (name of ziel) & "{TRENNER}" & teilt & "{TRENNER}" & my stempel(modification date of n) & "{TRENNER}" & (plaintext of n)
      end timeout
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
    name, wo, teilt, stand, klar = (roh.split(TRENNER, 4) + ["", "", "", ""])[:5]
    print(f"Angelegt: {sauber(name)} in {sauber(wo) or args.folder or 'Standardordner'}"
          + (" (geteilt, andere sehen die Notiz)" if teilt.strip() == "true" else ""))
    if stand.strip():
        print(f"Stand:    {sauber(stand.strip())}")
        satz = nachkontrolle(inhalt, klar, args.title if mit_name else "")
        if satz:
            print(satz)


def stand_wert(stand: str) -> str:
    wert = " ".join(stand.split())
    if not STAND.fullmatch(wert):
        aufruf_falsch(f"--stand braucht die Zeile Stand aus read, etwa 2026-11-18 14:03:22, nicht {sauber(stand)!r}. "
                      "Nichts geändert.")
    return wert


def anhaenge_abbruch(anzahl: str) -> None:
    wie = f"{anzahl} Anhänge" if anzahl.strip().isdigit() else "möglicherweise Anhänge (nicht prüfbar)"
    sys.exit(f"Die Notiz hat {wie} (Bilder, Dateien, Zeichnungen oder Scans). Notes verliert sie, wenn der Inhalt neu "
             "geschrieben wird, auch beim Ergänzen. Nichts geändert, die Änderung macht der Nutzer selbst in Notizen.")


def cmd_aendern(args) -> None:
    """replace und append (Etappe 3 von v7.3.0). Erstes AppleScript: genau eine Notiz mit dem Titel, ihr Stand,
    Anhänge, Teilung und HTML. Dann prüft Python Stand, Anhänge und bei replace die Links und baut bei append das neue
    HTML. Das zweite AppleScript findet die Notiz über ihre ID, prüft Stand und Länge des HTML noch einmal, schreibt und
    liest Titel, neuen Stand und Klartext zurück. So kommt keine Änderung dazwischen, die ein anderer Mac oder das
    iPhone in der Zwischenzeit gemacht hat, ohne dass Stand oder Länge abweichen."""
    anfuegen = args.befehl == "append"
    quelle = text_datei(args.file)
    inhalt = datei_als_html(quelle)
    stand = stand_wert(args.stand)
    if ordner_gesperrt(args.folder):
        nicht_gefunden(args.titel, "Nichts geändert.")
    pruefen = f'''
    {kette()}
    {teilung()}
    {helfer()}
    tell application "Notes"
      with timeout of {AS_SEKUNDEN} seconds{titel_suche(args.titel, args.folder)}{teilt_notiz("erste", "ersterFo")}
      try
        set anh to (count of attachments of erste) as text
      on error
        set anh to "?"
      end try
      set b to body of erste
      return "EINS{TRENNER}" & ersterOrdner & "{TRENNER}" & (id of erste) & "{TRENNER}" & my stempel(modification date of erste) & "{TRENNER}" & anh & "{TRENNER}" & teilt & "{TRENNER}" & (count of b) & "{TRENNER}" & b
      end timeout
    end tell
    '''
    roh = osa(pruefen)
    treffer_pruefen(roh, args.titel, "Nichts geändert.")
    teile = roh.split(TRENNER, 7)
    if len(teile) < 8 or teile[0] != "EINS" or not teile[6].strip().isdigit():
        unerwartet("Nichts geändert.")
    _, ordner, nid, jetzt, anh, teilt, laenge, alt = teile
    if jetzt.strip() != stand:
        sys.exit(f"{args.titel!r} hat sich seit dem Lesen geändert (Stand jetzt {sauber(jetzt.strip())}, gelesen "
                 f"{stand}). Nichts geändert. Erst notiz_lesen, dann mit der neuen Fassung und dem neuen Stand erneut.")
    if anh.strip() != "0":
        anhaenge_abbruch(anh)
    neu = ergaenzt(alt, inhalt, args.wo) if anfuegen else inhalt
    if not anfuegen and not args.links_entfernen:
        fehlen = sorted(links(alt) - links(neu))
        if fehlen:
            beispiele = ", ".join(sauber(x) for x in fehlen[:3]) + (" und weitere" if len(fehlen) > 3 else "")
            sys.exit(f"Die neue Fassung lässt {len(fehlen)} Links der Notiz weg ({beispiele}). Nichts geändert. Links aus "
                     "notiz_lesen mit html übernehmen, oder nur auf Wunsch des Nutzers mit links_entfernen.")
    was = "Ergänzung" if anfuegen else "Änderung"
    weg = "notiz_geteilt mit ergaenzen" if anfuegen else "notiz_geteilt mit ersetzen"
    if teilt.strip() != "false" and not args.ausfuehren:  # nichts geändert, die Textdatei bleibt für notiz_geteilt
        print(f"Vorschau, nichts geändert: {args.titel} liegt geteilt im Ordner {sauber(ordner)}, andere sähen die "
              f"{was} sofort. Weiter mit {weg}, das zeigt einen Dialog am Mac.")
        return
    vorschau = "" if args.ausfuehren else f'''{teilt_notiz("n", "fo")}
      if teilt then return "GETEILT{TRENNER}" & fname'''
    tmp = html_in_tempdatei(neu)
    schreiben = f'''
    {kette()}
    {teilung()}
    {helfer()}
    set t to (read POSIX file {quote(str(tmp))} as «class utf8»)
    tell application "Notes"
      with timeout of {AS_SEKUNDEN} seconds
      set n to missing value
      repeat with f in folders
        set fo to contents of f
        set fname to name of fo
        if {ordner_bedingung(args.folder)} then
          try
            set ids to id of notes of fo
          on error
            set ids to {{}}
          end try
          if ids contains {quote(nid)} then
            set n to note id {quote(nid)}
            exit repeat
          end if
        end if
      end repeat
      if n is missing value then return "NICHTGEFUNDEN"
      set standJetzt to my stempel(modification date of n)
      if standJetzt is not {quote(stand)} or (count of (body of n)) is not {int(laenge)} then return "STAND{TRENNER}" & standJetzt
      try
        set anh to (count of attachments of n) as text
      on error
        set anh to "?"
      end try
      if anh is not "0" then return "ANHAENGE{TRENNER}" & anh{vorschau}
      set body of n to t
      return "OK{TRENNER}" & fname & "{TRENNER}" & (name of n) & "{TRENNER}" & my stempel(modification date of n) & "{TRENNER}" & (plaintext of n)
      end timeout
    end tell
    '''
    try:
        roh = osa(schreiben)
    finally:
        tmp.unlink(missing_ok=True)
    if roh.startswith("NICHTGEFUNDEN"):
        nicht_gefunden(args.titel, "Nichts geändert, sie wurde wohl gerade verschoben.")
    if roh.startswith("STAND" + TRENNER):
        sys.exit(f"{args.titel!r} hat sich gerade geändert (Stand jetzt {sauber(roh.split(TRENNER, 1)[1].strip())}). "
                 f"Nichts geändert. Erst notiz_lesen, dann erneut.")
    if roh.startswith("ANHAENGE" + TRENNER):
        anhaenge_abbruch(roh.split(TRENNER, 1)[1])
    if roh.startswith("GETEILT" + TRENNER):
        print(f"Vorschau, nichts geändert: {args.titel} liegt geteilt im Ordner {sauber(roh.split(TRENNER, 1)[1])}, "
              f"andere sähen die {was} sofort. Weiter mit {weg}, das zeigt einen Dialog am Mac.")
        return
    teile = roh.split(TRENNER, 4)
    if len(teile) < 4 or teile[0] != "OK":
        unerwartet("Ob die Notiz geändert ist, mit notiz_lesen prüfen.")
    quelle.unlink(missing_ok=True)
    _, wo, name_neu, stand_neu = teile[:4]
    klar = teile[4] if len(teile) > 4 else ""
    print(f"{'Ergänzt' if anfuegen else 'Ersetzt'}: {args.titel} in {sauber(wo)}")
    print(f"Stand:    {sauber(stand_neu.strip())}")
    satz = nachkontrolle(neu, klar)
    if satz:
        print(satz)
    name_neu = sauber(name_neu).strip()
    if name_neu and name_norm(name_neu).casefold() != name_norm(args.titel).casefold():
        print(f"Achtung: Notes hat die Notiz in {name_neu!r} umbenannt (erste Zeile des Inhalts). Soll der alte Titel "
              f"bleiben, ihn als erste Zeile in notiz.html setzen und mit replace {name_neu!r} erneut ersetzen.")


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
    ps.add_argument("--folder")
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
    px.add_argument("--stand", required=True, help="Zeile Stand aus read, JJJJ-MM-TT HH:MM:SS")
    px.add_argument("--folder")
    px.add_argument("--links-entfernen", action="store_true", help="Links der alten Fassung dürfen fehlen")
    px.add_argument("--ausfuehren", action="store_true", help="in einem geteilten Ordner wirklich ersetzen")
    px.set_defaults(func=cmd_aendern, wo="unten")

    pe = sub.add_parser("append", help="Text an eine Notiz anfügen", allow_abbrev=False)
    pe.add_argument("titel")
    pe.add_argument("--file", required=True, help="notiz.html oder notiz.md im Kit-Ordner")
    pe.add_argument("--stand", required=True, help="Zeile Stand aus read, JJJJ-MM-TT HH:MM:SS")
    pe.add_argument("--wo", choices=("unten", "oben"), default="unten", help="unten (Standard) oder direkt unter dem "
                                                                              "Titel")
    pe.add_argument("--folder")
    pe.add_argument("--ausfuehren", action="store_true", help="in einem geteilten Ordner wirklich ergänzen")
    pe.set_defaults(func=cmd_aendern, links_entfernen=False)

    vorn, rest = kit_basis.schalter_vorn(sys.argv[1:] if argv is None else list(argv), ("--ausfuehren",))
    args = p.parse_args(rest + vorn)  # --ausfuehren gehört zu add, replace und append, steht aber direkt hinter dem Skript
    if getattr(args, "limit", 1) < 1:  # Review 21.10.2026: sonst still "Keine Notizen gefunden"
        aufruf_falsch("--limit braucht 1 oder mehr, etwa --limit 25. Nichts gelesen.")
    if getattr(args, "max_chars", 0) < 0:
        aufruf_falsch("--max-chars braucht 0 oder mehr, 0 zeigt alles. Nichts gelesen.")
    args.func(args)


if __name__ == "__main__":
    kit_basis.starten(main, __file__)
