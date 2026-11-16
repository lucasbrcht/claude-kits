# Einrichten: Ablauf im Einzelnen

Zum Skill `einrichten`. Reihenfolge wie im Skill. Vorher Einleitung und Haltepunkt Modell aus `texte.md`. Nach jedem Schritt eine Zeile, was angelegt wurde ("Ich lege jetzt deinen Kontextordner an.", "3 Kalender eingetragen."), dann ohne Rückfrage weiter. Bricht der Nutzer ab, bleibt der Stand erhalten: Der nächste Aufruf macht bei den Zeilen mit `OFFEN:` weiter.

Ziel: Der Nutzer tut so wenig wie möglich. Alles, was sich lesen oder schreiben lässt, macht der Assistent selbst. Der Nutzer entscheidet, bestätigt, gibt Dialoge am Mac frei und erteilt Freigaben.

## Umfang der Auswertung

Fest für jedes Modell. Nicht mehr suchen, nicht weniger, keine weiteren Quellen (keine Notizen, keine Erinnerungen, keine Mailinhalte, keine Anhänge). Reichen die Treffer nicht, fragen statt weiter zu suchen. Werkzeuge in `quellen-apple.md`.

| Schritt | Quelle | Zeitraum | Aufrufe höchstens | Ergebnis höchstens |
|---|---|---|---|---|
| 3 Person | `kontakte` mit `ich` | aktuell | 1 | eigene Karte, nur Name |
| 4 Kalender | `termine_lesen` mit `kalenderliste` | aktuell | 1 | Namen der Kalender |
| 5 Personen | `mail_suchen` im Postfach sent | 90 Tage | 1 je Profil | in den 25 enthalten |
| 5 Personen | `chat_liste` whatsapp | 90 Tage | 1 | in den 25 enthalten |
| 5 Personen | `chat_liste` imessage | 90 Tage | 1 | in den 25 enthalten |
| 5 Personen | `termine_lesen` 30 Tage mit `alle` | 30 Tage voraus | 1 | Regeltermine, gemeinsame Kalender |
| 5 Personen | `kontakte` mit `suche` | aktuell | 1 je genannte Person | Schreibweise, Firma |
| 5 Ergebnis | Treffer oben | wie oben | 0 zusätzlich | 25 Vorschläge |
| 7 Stil Mail | `mail_stilprofil` mit `stilprobe` 40 | neueste | 1 je Profil | Merkmale, keine Inhalte |
| 7 Stil WhatsApp | `chat_stilprofil` mit `stilprobe` 200 | neueste | 1 | Merkmale, keine Inhalte |

## Voraussetzungen prüfen (Schritt 1)

Fehlt etwas, das nur der Nutzer beheben kann, das in einem Satz sagen, den Text aus `texte.md` zeigen und anhalten oder die Quelle überspringen, nicht lange probieren:
- **Cowork ohne Projekt mit Ordner:** Das Projekt für den Grundbereich (meist Privat) kommt immer zuerst. Text Projekt anlegen, dann anhalten. Die Einrichtung startet danach neu in einer Aufgabe dieses Projekts.
- **Werkzeuge von `apple` fehlen:** Plugin nicht installiert oder der Server startet nicht. Text Plugins, dann anhalten.
- **`kontakte` oder ein Chat-Werkzeug meldet fehlenden Zugriff:** Festplattenvollzugriff fehlt (Text Freigaben). Danach Claude neu starten, die Einrichtung macht beim nächsten Aufruf weiter.
- **WhatsApp fehlt am Mac oder der Nutzer nutzt es nicht, Plugin `chat` fehlt:** die Zeilen zu WhatsApp und iMessage überspringen, kein Stilprofil dafür.
- **Dialog am Mac abgelehnt oder nicht gesehen:** `einstellungen_schreiben` meldet es. Den Nutzer bitten, auf den Mac zu schauen, dann einmal erneut.

## Kontextordner (Schritt 2)

Aus `vorlagen/` im Skill-Ordner, je Datei mit Write, nur was fehlt. Ohne Rückfrage, eine Zeile Ansage reicht. `vorlagen/CLAUDE-vorlage.md` wird `CLAUDE.md` (im Paket heißt sie anders, damit Claude Code sie nicht als eigene Anweisung lädt):

```
<Kontextordner>/
  profil.md                 Person, Arbeitsweise, Kommunikation, Schreibregeln, Regeln, Memory: Quelle der Instructions for Claude
  CLAUDE.md                 Index des Projekts: wo was liegt (lädt in Cowork aus dem Projektordner)
  wissen/privat-profil.md   Interessen, Vorlieben, Bereiche und Projekte
  wissen/privat-personen.md Familie, Freunde, je Person Beziehung und Kanal
  wissen/arbeit-personen.md nur mit Arbeitskonto: Kolleginnen, Kunden, je Person Rolle, Organisation, Du oder Sie
  wissen/_interview.md, _verworfen.md, _rueckmeldungen.md
  einrichtung/              instructions.md und pruefliste.md aus Schritt 9
```

Personen gehören ins Wissen des Projekts, nie in `profil.md` oder die Instructions. Ohne Arbeitskonto `arbeit-personen.md` weglassen und die Zeile im Index streichen. Liegt der gewünschte Ort in iCloud Drive oder einem anderen Cloud-Ordner, darauf hinweisen und den Standard empfehlen.

## config.json der Plugins (Schritte 3 und 4)

`einstellungen` zeigt den Stand und für fehlende Abschnitte die Vorlage aus `config.example.json`. Werte in spitzen Klammern ersetzen, Felder mit `_` am Anfang weglassen. Was der Nutzer nicht weiß, als Wert `OFFEN` lassen und am Ende nennen. Ein Aufruf `einstellungen_schreiben` je Plugin, `werte` mit den ganzen Abschnitten (ein Abschnitt ersetzt den alten vollständig, also bei einer Fortsetzung den Stand aus `einstellungen` übernehmen und ergänzen).

- `apple`, Abschnitt `mail`: `accounts`, `profiles.privat` (Konto, Name, eigene Adresse aus der Frage, nicht aus Kontakte), `profiles.arbeit` nur mit Arbeitskonto, sonst den Block und das zweite Konto streichen, `default_profile` privat, `anhang_ordner`, `noise`, `search` und `triage` wie in der Vorlage.
- `apple`, Abschnitt `kalender`: `default_calendar`, `allowed_calendars` (private und gemeinsame Kalender, die der Nutzer beschreiben lassen will), `arbeitskalender` (Exchange, sonst leer), Rest wie in der Vorlage ohne Platzhalter.
- `apple`, Abschnitte `kontakte` (`eigene_mails`), `notizen` und `reminders` (Ausschlüsse und geteilte Listen nur auf Nennung, sonst leere Listen).
- `apple`, Abschnitt `pdf`: `ordner` wie in der Vorlage (Downloads im iCloud Drive), weitere Ordner nur auf Nennung.
- `chat` mit `plugin` chat, nur diese Abschnitte, alles andere hat Standardwerte: `me` (Vorname), `me_names` (Vorname und Spitzname), `forbidden_chars` aus Runde 3 des Interviews (leere Liste, wenn der Nutzer nichts ausschließt, sonst zum Beispiel Gedankenstriche, Auslassungspunkte, Semikolon), `excluded_chats` nur, wenn der Nutzer welche nennt.

## Personen (Schritt 5)

Vorschläge in Auswahlfragen nach `../../kontext/references/fragen.md`, jede Person einzeln bestätigen lassen. Format in `privat-personen.md`: `- **Vorname Nachname**: Beziehung, Merken` und darunter bei Bedarf `  - Kanal iMessage`, wenn nicht WhatsApp. In `arbeit-personen.md`: `- **Vorname Nachname** (Organisation): Rolle, Du oder Sie`. Abschnitte nach Gruppen (`## Familie`, `## Freunde`, `## Kollegen`). Verworfene Vorschläge nach `_verworfen.md`, "neu, später prüfen" nach `_interview.md`.

**Wer fehlt noch.** Nach den Vorschlägen offen fragen, als normale Frage im Chat, nicht als Auswahl. Erst privat, dann bei Arbeitskonto für die Arbeit:

> Wer ist dir sonst noch wichtig, mit dem ich nichts gefunden habe? Name und Beziehung reichen, etwa "Anna Beispiel, meine Schwester".

> Und bei der Arbeit: Mit wem hast du viel zu tun? Name, Rolle, Du oder Sie.

- Genannte Personen mit `kontakte` und `suche` auf Schreibweise prüfen, den Treffer bestätigen lassen. Nummern und Adressen aus der Karte nicht übernehmen.
- Fehlt der Kanal, gilt WhatsApp. Fehlt die Beziehung oder Rolle, `OFFEN`.
- "Niemand" oder "später" ist eine gültige Antwort, dann weiter.

## Fragen je Runde (Schritt 6)

| Runde | Fragen |
|---|---|
| 1 Anrede | Anrede privat (meist Du, Vorname), Gruß privat, Emojis privat (nie, sparsam, eins am Ende) |
| 2 Arbeit | nur mit Arbeitskonto: Arbeitgeber, Rolle, Anrede und Gruß in Arbeitsmails, Du oder Sie intern und extern |
| 3 Schreiben | Zeichen oder Wörter, die nie vorkommen sollen, Datum und Uhrzeit, Länge von Nachrichten |
| 4 Alltag | Interessen, wofür der Assistent am meisten helfen soll |
| 5 Bereiche | angestellt, selbständig oder ohne Beruf, Account der Firma ja oder nein, dauerhafte Bereiche mit eigenen Unterlagen (Verein, Studium, Verwaltung), was vertraulich bleiben muss. Dann die Empfehlung nach `projektschnitt.md` zeigen und den Schnitt bestätigen lassen |

Je Frage zwei bis drei konkrete Optionen mit fertigem Text, "Empfohlen" für die naheliegende, Freitext über die eingebaute Option Sonstiges. Was der Assistent aus den Quellen schon weiß (Gruß in gesendeten Mails, Emojis in WhatsApp), als Empfehlung vorschlagen statt offen zu fragen.

## Stil (Schritt 7)

Je Mailprofil `mail_stilprofil` mit `profil` und `stilprobe` 40. Daraus das Profil nach der Vorlage des Plugins `apple` (Überschrift `# Stilprofil (<profil>)`, Abschnitte Anrede und Gruß je Kontext, Ton und Satzbau, Zeichensetzung und Typografie, Länge, Nie verwenden, Belege, Notizen des Nutzers), jede Aussage mit einer Zahl aus der Statistik belegt, keine Namen Dritter und keine Mailtexte. WhatsApp mit `chat_stilprofil` und `stilprobe` 200, Abschnitte und Grenzen wie in `stilprofil-pflege.md` des Plugins `chat`. Zeigen, Korrekturen unter Notizen des Nutzers, dann je Profil ein Aufruf `einstellungen_schreiben` mit `stilprofil` (privat, arbeit oder chat mit `plugin` chat) und `text`.

## Profil und Index (Schritt 8)

`profil.md` hat feste Abschnitte. `OFFEN:`-Zeilen ersetzen, nichts Neues erfinden, höchstens 120 Zeilen. Der Abschnitt Nur im Code-Tab bleibt in `<!-- nur-code -->` und fällt aus den Instructions. Im Index `<Bereich>` ersetzen und Zeilen ohne Datei streichen. Beides zeigen, auf Ja speichern.

## Abschluss (Schritt 12)

Text Abschluss aus `texte.md` zeigen. Vorher zählen: Personen in `privat-personen.md` und `arbeit-personen.md`, Konten in `accounts`, Kalender in `allowed_calendars`, Zeilen mit `OFFEN:` im Kontextordner und in den `config.json` (als kurze Stichworte, höchstens fünf, Rest als Anzahl). Tabelle und Beispiele nicht kürzen, nur Zeilen für fehlende Plugins weglassen. Darunter "Deine Schritte" aus `einrichtung/pruefliste.md`, je Punkt Wo und Wie.
