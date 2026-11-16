# Plugin apple

Apple Mail, Kalender, Notizen, Erinnerungen und Kontakte für Cowork und den Code-Tab, ein lokaler MCP-Server (bis 6.3 die Plugins `mail` und `apple`). Mails lesen, durchsuchen, Entwürfe anlegen und auf Ansage senden, Stilprofile aus eigenen gesendeten Mails, der Gesamtblick über alle Kalender und Termine, Notizen und Erinnerungen lesen und schreiben, Kontakte lesen, HTML-Dateien als PDF drucken. Ein verbundener Mail-Connector (Gmail, Microsoft 365) darf suchen und lesen, geschrieben wird in Apple Mail. Die Regeln stehen in den Skills `mail`, `kalender`, `notizen` und `erinnerungen`. Nichts verlässt das Gerät über das Plugin: keine Cloud-API, nur AppleScript (Mail, Notizen), EventKit (Kalender, Erinnerungen), icalBuddy, die Adressbuch-Datenbank (Kontakte) und WebKit (PDF).

Neutral und ohne Kontext oder Chat: Das Plugin taugt auch für Kollegen mit Mac, die nur die Apple-Apps wollen.

Was das Plugin bewusst nicht kann: Mails, Notizen, Erinnerungen oder Termine löschen, Mails verschieben oder als gelesen markieren, Regeln anlegen, Teilnehmer einladen, Serien anlegen, in Exchange-Kalender schreiben (Ausnahme: eigene Termine ohne Teilnehmer über `termin_mit_nachfrage`), Ordner und Listen anlegen, gesperrte Notizen lesen, Kontakte ändern.

## Installation

In Cowork: Customize > Plugins > Add marketplace mit `lucasbrcht/claude-kits` (Sync automatically), dann `apple` installieren. In Claude Code:

```
/plugin install apple --marketplace lucasbrcht/claude-kits
```

## Werkzeuge

Der lokale MCP-Server `server.py` (über `.mcp.json`, Unterbau `mcp_basis.py`) ruft die Skripte auf, ohne Shell.

| Stufe | Werkzeuge |
|---|---|
| lesen | `mail_suchen`, `mail_neues`, `mail_lesen`, `mail_entwuerfe`, `mail_stilprofil` (mit `stilprobe` eine neue Stichprobe), `termine_lesen`, `erinnerungen_lesen`, `notizen_suchen`, `notiz_lesen`, `kontakte`, `einstellungen` |
| schreiben | `mail_entwurf`, `mail_entwurf_anhang`, `termin_anlegen`, `termin_verschieben` (nur in `allowed_calendars`), `erinnerung_anlegen`, `erinnerung_abhaken`, `notiz_anlegen`, `notiz_ersetzen` (nur außerhalb geteilter Ordner), `pdf_aus_html` (nur in `pdf.ordner`) |
| nachfrage | `mail_senden`, `termin_mit_nachfrage` (Arbeitskalender, Termine mit Teilnehmern), `notiz_geteilt` (geteilte Ordner), `einstellungen_schreiben` (config.json und Stilprofile), erst nach Dialog von macOS. Dazu `pdf_aus_html` mit `ersetzen`: Ein vorhandenes PDF überschreibt es erst nach demselben Dialog. |

`pdf_aus_html` druckt eine HTML-Datei mit WebKit als PDF neben die Quelle: A4 hoch oder mit `quer` quer, ohne Ränder, mit Hintergründen und den Schriften des Mac, optional mit `name` als Dateiname. Rückgabe Pfad und Seitenzahl, die Seitenzahl ist die schnelle Prüfung auf Überlauf. `pdf.py` übersetzt `html2pdf.swift` beim ersten Aufruf einmal nach `bin/` im Datenordner (etwa 40 Sekunden), danach dauert ein Druck wenige Sekunden. WebKit rundet die Seitenhöhe auf ganze CSS-Pixel ab, deshalb druckt das Programm auf 1,5 pt höheres Papier und schneidet jede Seite oben bündig auf A4 zu: Vorlagen mit Seiten von genau 297 mm bekommen so keine leeren Zwischenseiten. Ein eigenes Werkzeug für das Überschreiben gibt es nicht, es sprengte die Obergrenze aller Server.

`einstellungen` und `einstellungen_schreiben` lesen und schreiben den Datenordner von `apple`, `chat` und `service`: für den Skill `einrichten`, weil Claude in Cowork den Ordner nur über den Server erreicht. Geschrieben werden ganze Abschnitte, für `apple` nur die aus `config.example.json` mit gleichem Typ, dazu `mcp_nur_lesen`, oder ein Stilprofil.

## Was wohin

| Aufgabe | Skript |
|---|---|
| Mails sichten, lesen, suchen, Entwürfe, senden | `mail.py`, je Konto ein Profil (`privat`, `arbeit`) |
| Mail aus dem Connector beantworten | `mail.py finden`, dann `draft --reply-to`, Ablauf in `referenzen/connector.md` |
| Stilprofil aus gesendeten Mails | `style_sample.py` |
| Gesamtblick über alle Kalender | `calendar_today.sh` |
| Termine anlegen und verschieben | `add_event.py`, `move_event.py` |
| Erinnerungen | `reminders.py` |
| Notizen | `notiz.py` |
| Kontakte | `kontakte.py` (nur lesen) |
| PDF aus HTML | `pdf.py` mit `html2pdf.swift` (WebKit) |

## Voraussetzungen

- macOS mit Apple Mail (Kontonamen wie in der Seitenleiste), Kalender, Notizen, Erinnerungen, Kontakte und `brew install ical-buddy`. Für `pdf_aus_html` macOS ab 13.3 und `swiftc` aus den Command Line Tools.
- python3 (System-Python ab 3.9), der Server startet mit `/Library/Developer/CommandLineTools/usr/bin/python3`. Für Kalender und Erinnerungen eine `.venv` mit EventKit im Datenordner: `/opt/homebrew/opt/python@3.12/bin/python3.12 -m venv "$HOME/Library/Application Support/Claude Kits/apple/.venv"` und danach `"$HOME/Library/Application Support/Claude Kits/apple/.venv/bin/pip" install pyobjc-framework-EventKit`. Die Skripte starten mit `python3` und wechseln selbst in die `.venv`. Entfernt Homebrew diese Python-Version, die `.venv` neu anlegen.
- Systemeinstellungen > Datenschutz & Sicherheit: Automation (Mail, System Events, Notizen), Bedienungshilfen für Antworten in Mail, Kalender und Erinnerungen auf Vollzugriff, Festplattenvollzugriff für `python3.9` der Command Line Tools (Kontakte). Beim ersten Lauf kommen die Abfragen von selbst.

## Datenordner

`config.json`, `style/`, `.venv` und die Entwurfsdateien liegen unter `~/Library/Application Support/Claude Kits/apple/`, nicht im Git und nicht im Plugin. Der Server liest nur dort und gibt den Ordner den Skripten als `KITS_DATENORDNER` mit. Von Hand ohne die Variable gilt der Plugin-Ordner (für Tests).

## config.json

Eine Datei mit einem Abschnitt je Bereich, Vorlage `config.example.json`. Falsche Typen brechen mit dem Schlüssel ab, ein fehlender Abschnitt `mail` oder `kalender` ebenso, nichts fällt still weg. Optional ganz oben `mcp_nur_lesen` (true oder Liste von Instanzen wie `["arbeit"]`): Dann bietet der Server dort nur die Werkzeuge zum Lesen an.

| Feld | Bedeutung |
|---|---|
| `mail.accounts` | Konten, die suchen, lesen und sichten ohne Profil abdecken. Leer oder fehlend bricht ab, statt alle Konten zu durchsuchen. |
| `mail.default_profile` | Profil für Entwürfe ohne Angabe, meist `privat`. |
| `mail.profiles.<name>` | `account`, `from_name`, `from_address` je Profil, `signature` als Trennmarke für `style_sample.py`, `signatur_html` und `signatur_footer_html` (kurze und lange Signatur, einzige Stelle mit Telefonnummer). |
| `mail.anhang_ordner` | Ordner, aus denen Anhänge kommen dürfen. Alles andere lehnt das Skript ab. |
| `mail.noise` | Teilstrings von Absendern, die `mail_neues` ausblendet. |
| `mail.search`, `mail.triage` | Zeitraum und Trefferzahl ohne Angabe, höchstens so viele nur markierte Mails je Konto. |
| `kalender.default_calendar` | Kalender ohne Angabe, muss in `allowed_calendars` stehen. |
| `kalender.allowed_calendars` | Nur in diese Kalender schreiben die Skripte, nie in einen Exchange-Kalender. |
| `kalender.private_calendars` | Werden nie gelesen und nie beschrieben. |
| `kalender.hidden_calendars`, `dedupe_calendars`, `nur_belegt` | Nur mit `alle` sichtbar, nur einmal gezeigt, nur Zeiten ohne Titel. |
| `kalender.arbeitskalender` | Name des Arbeitskalenders (Exchange). Fehlt er, warnt der Gesamtblick. Einziges Ziel von `termin_mit_nachfrage` mit `arbeitskalender`. |
| `notizen.ausgeschlossene_ordner` | Ordner, die `notiz.py` nie liest, durchsucht oder beschreibt, mit allen Unterordnern. Der Papierkorb ist immer ausgenommen. |
| `reminders.excluded_lists` | Erinnerungslisten, die nie gelesen oder beschrieben werden. |
| `reminders.geteilte_listen` | Listen, die andere sehen. `lists` markiert sie mit `(geteilt)`, `add` und `done` schreiben dort direkt wie überall. |
| `kontakte.eigene_mails` | Eigene Mailadressen, an ihnen erkennt `kontakte.py me` die eigene Karte. |
| `pdf.ordner` | Ordner, unter denen `pdf_aus_html` HTML-Dateien drucken darf, mit allen Unterordnern. Fehlt der Abschnitt, bricht `pdf.py` ab. |

## Aufruf von Hand

Für Tests und Fehlersuche, im Terminal im Plugin-Ordner. Die Skripte brauchen Zugriff außerhalb der Sandbox: im Code-Tab immer mit absolutem Pfad als eigener Befehl, ohne `cd`, Pipe oder Umleitung, mit `KITS_DATENORDNER="$HOME/Library/Application Support/Claude Kits/apple"` davor, sonst gilt der Plugin-Ordner.

```bash
python3 mail.py triage                                               # alle Konten aus accounts, je Konto ein Block
python3 mail.py search --profile privat --from "mueller" --days 30
python3 mail.py finden --message-id "<abc123@mail.example.org>"      # Mail aus dem Connector in Apple Mail
python3 mail.py read 12345 12346                                     # bis 10 Mails
python3 mail.py draft --to a@b.de --subject 'Kurze Frage' --text-file entwurf.txt
python3 mail.py draft --reply-to 12345 --text-file antwort.txt        # echte Antwort mit Verlauf
python3 mail.py --attach ~/Downloads/datei.pdf draft --to a@b.de --subject 'Unterlagen' --text-file entwurf.txt
python3 mail.py drafts                                               # offene Entwürfe mit id, An, Cc, Bcc, Absender
python3 mail.py send 7 --yes                                         # sendet
python3 mail.py signatur --kopieren                                  # Signatur für Apple Mail in die Zwischenablage
python3 style_sample.py --n 40 --profile privat                      # style/privat/samples.md und stats.md

bash calendar_today.sh 7 --all      # heute plus 7 Tage, auch ausgeblendete Kalender
python3 add_event.py --ausfuehren --ort 'Praxis' -- 'Zahnarzt' '2026-10-05 09:30' '2026-10-05 10:15'
python3 move_event.py --ausfuehren -- 'Zahnarzt' '2026-10-05 09:30' '2026-10-06 11:00'

python3 notiz.py search 'Paris'
python3 notiz.py read 'Paris Wochenende' --html                     # HTML als Grundlage für replace
python3 notiz.py add --title 'Packliste' --file notiz.md            # Text aus notiz.md im Datenordner
python3 reminders.py list --days 7
python3 reminders.py add 'Aufgaben' 'Reifen bestellen' 2026-09-30 18:00
python3 reminders.py done 'Reifen bestellen'
python3 kontakte.py search 'Mustermann'
```

Jeder Befehl kennt `--help`. Exit-Codes: 0 ok (auch Vorschau), 1 Fehler und nichts geändert, 2 Aufruf falsch oder mehrdeutig, bei `mail.py` dazu 3 Antwort offen, aber Text nicht eingefügt, 4 neuer Entwurf leer, 5 neuer Entwurf mit anderem Absender als in `config.json`. Jeder Abbruch landet ohne Inhalt im Fehlerprotokoll des Pakets (`kit_basis.starten`).

## Schutz

- Schutz liegt im Werkzeug: Die Werkzeuge der Stufe nachfrage zeigen vorher einen Dialog von macOS mit den Angaben in Stichworten, Abbrechen ist Vorauswahl. Löschen gibt es nicht.
- Schreibende Schalter (`--ausfuehren`, `--attach`, `--exchange`) stehen direkt hinter dem Skript, an anderer Stelle bricht das Skript ab.
- Texte für Entwürfe und Notizen kommen nur aus festen Dateien im Datenordner (`entwurf.txt`, `antwort.txt`, `notiz.md`, `notiz.html`), nie über einen Verweis, Anhänge nur aus `anhang_ordner`.
- `send` gilt nur für Entwürfe, die das Plugin selbst angelegt hat, mit gleichem Betreff und aus demselben Mail-Lauf. Den Stand hält `mail.py` unter `~/Library/Application Support/Claude Kits/`.
- Texte von Mail kommen ohne die Trennzeichen 30 und 31 aus dem AppleScript, die Skripte nehmen nur Datensätze mit genau der erwarteten Feldzahl.
- Für den Code-Tab schreibt `paket.py` (Plugin `pflege`) nur die Sperren aus `kit.json` in die `settings.json`: Die Datenordner von Mail, Kalender, Notizen und Erinnerungen liest nur der Server. Die Sandbox darf im Plugin nicht schreiben, auch nicht in der `.venv`. Dateien nur mit Edit oder Write ändern.

## Verhalten, das man kennen sollte

- Eine neue Mail wird komplett gebaut und sichtbar in Mail geöffnet, Mail hängt die Signatur an. Antworten sind echte Antworten mit Verlauf, der Text kommt über die Zwischenablage (gesichert und wiederhergestellt), danach zählt das Skript nach. `send` prüft bis zu 30 Sekunden im Postfach Gesendet: Ist offen, ob die Mail raus ist, nicht erneut senden.
- `search` sucht über Betreff und Absender, nicht im Mailtext. Dafür den Connector nehmen und mit `finden` zurück nach Apple Mail.
- Ganztägig zählt `add_event.py` das Ende inklusiv (letzter Tag). Mehrere Termine zum selben Titel gehen in einen Aufruf, passt einer nicht, ändert sich keiner. Uhrzeiten, die es wegen der Zeitumstellung zweimal oder gar nicht gibt, brechen schon in der Vorschau ab.
- `notiz.py`: HTML geht unverändert durch, Verweise, die Notes nachladen könnte, lehnt es ab. In einem geteilten Ordner nur Vorschau ohne `--ausfuehren`. `read` und `replace` nehmen eine Notiz nur bei eindeutigem Titel, `replace` setzt den ganzen Inhalt neu, Grundlage ist `read --html`. Eine gekürzt gelesene Notiz nie ersetzen.
- `reminders.py add` nimmt mehrere Fristen zum selben Titel, prüft alle vorher und legt keine Dublette an. `done` vergleicht den Titel so, wie `list` ihn zeigt. `list --verlauf` zeigt eine Liste ganz für einen Tagesstart.
- `kontakte.py` liest `AddressBook-v22.abcddb` aller Quellen als Kopie, nur lesend, Ausgabe nur auf stdout.
- Ausgeschlossene Ordner, Listen und Kalender melden sich überall wie unbekannte.

## Tests

```bash
python3 -B -m unittest discover tests
```

Ersatz für Apple Mail, osascript, EventKit, Foundation, icalBuddy und eine erfundene Adressbuch-Datenbank, läuft in der Sandbox. `tests/test_server.py` prüft den Zuschnitt aller Werkzeuge, `tests/test_server_mail.py` Mail und Kalender. `kit_basis.py`, `mcp_basis.py` und ihre Tests liegen gleich im Plugin `chat`. Abläufe in Mail mit Testentwürfen an die eigene Adresse prüfen, nie an andere senden.
