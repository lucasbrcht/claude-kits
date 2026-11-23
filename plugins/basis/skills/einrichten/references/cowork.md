# Einrichten: Cowork vorbereiten (Schritte 9 bis 11)

Was im Account steht (Instructions, Projekte, Connectoren), kann Claude nicht selbst einstellen. Der Skill schreibt es fertig nach `<Kontextordner>/einrichtung/`, der Nutzer klickt es nach der Prüfliste ein. Geplante Aufgaben legt Claude selbst an, wenn ein Werkzeug dafür da ist. Menüs heißen in der Desktop-App: Einstellungen > Your Claude (Instructions for Claude), Einstellungen > Capabilities (Memory), Customize > Connectors, Plugins in der Seitenleiste ganz oben über den Chats (nie Einstellungen > Plugins, der Weg ist unzuverlässig, fehlende Plugins über das Suchfeld). Weichen sie ab, den Weg nehmen, den der Nutzer nennt.

Nichts in `einrichtung/` darf Zugangsdaten, Telefonnummern, Adressen oder Inhalte aus Mails und Chats enthalten.

## Texte zum Kopieren im Chat

Instructions for Claude und alles, was je Projekt einzutragen ist, stehen **immer direkt im Chat**, gut sichtbar und fertig zum Kopieren. Die Dateien in `einrichtung/` sind nur die Sicherung, nie der Ersatz ("steht in der Datei" reicht nicht).

- **Eine eigene Nachricht am Ende der Runde,** ohne Werkzeugaufruf danach: Text zwischen Werkzeugaufrufen klappt die App ein. Erst speichern (Write), dann die Nachricht zeigen und warten, bis der Nutzer "fertig" sagt.
- **Je Ziel eine Überschrift** (`## Deine Instructions for Claude`, `## Projekt <Name> (vorhanden|neu)`), darunter **Wo** in einem Satz und was ersetzt oder ergänzt wird.
- **Jeder Text zum Einfügen in einem eigenen Codeblock** mit `text` (so zeigt die App den Knopf Kopieren): ganz, wörtlich, ohne Kürzung, ohne Kommentar, Überschrift oder Wo im Block. Nicht in ein Zitat oder eine eingerückte Liste setzen. Enthält der Text selbst drei Backticks, den Block mit vier öffnen und schließen.
- Kurze Werte wie Name und Beschreibung eines Projekts ebenfalls je in einem eigenen kleinen Block, Ordner und Memory als Tabelle daneben.
- Der Nutzer arbeitet von oben nach unten: Instructions zuerst, dann die Projekte in der Reihenfolge der Prüfliste.

Beispiel (Inhalte erfunden):

````
## Deine Instructions for Claude

**Wo:** Einstellungen > Your Claude > Instructions for Claude. Alten Text sichern, dann alles durch diesen ersetzen. Länge: 6.180 Zeichen.

```text
# Über mich
- Anna Beispiel, wohnhaft in Musterstadt.
...
```

## Projekt Privat (vorhanden)

| | |
|---|---|
| **Wo** | Seitenleiste > Projects > Privat > Einstellungen des Projekts |
| **Ordner** | 1. `Claude Kits/kontext` (ist schon verbunden) |
| **Memory** | an, Use account memory an |

**Beschreibung:**

```text
Familie, Freunde, Haushalt und Freizeit
```

**Instruktionen des Projekts:**

```text
Projekt für Privat. Am Mac liegt das Wissen im Ordner kontext, ...
```
````

## Instructions for Claude (`einrichtung/instructions.md`)

Der Text ist `profil.md` ohne die Blöcke zwischen `<!-- nur-code -->` und `<!-- /nur-code -->`, ohne HTML-Kommentare und ohne Überschriften, unter denen nichts steht. Wörtlich, ohne Kopfzeile.
- Abschnitte Über mich, Wie du arbeitest, Kommunikation, Schreibregeln, Texte in meinem Namen, Regeln, Memory müssen da sein. Keine Personen, keine Pfade, kein `cd`.
- Länge in Zeichen nennen. Bis rund 8.600 Zeichen sind belegt, darüber auf Abschneiden achten (die letzte Zeile muss nach dem Einfügen sichtbar sein).
- Sieht Claude schon Instructions in dieser Session: Zeilen, die dort stehen und im Profil fehlen, als Ergänzung für `profil.md` vorschlagen statt still wegzulassen, und sagen, dass der neue Text den alten ersetzt. In einem Account mit Instruktionen der Organisation: Widersprüche als Befund nennen, nicht selbst ändern.
- Speichern und im Chat zeigen nach Abschnitt Texte zum Kopieren, als ersten Teil der Nachricht.

## Projekte

Der Schnitt aus Runde 5 steht in `wissen/privat-profil.md`. Je Projekt in der Prüfliste und im Chat nach Abschnitt Texte zum Kopieren, vorhandene Projekte nur mit dem, was fehlt oder sich ändert:
- **Name und Beschreibung** (ein Satz, wofür das Projekt da ist, Dispatch wählt danach).
- **Ordner** in dieser Reihenfolge: zuerst der Ordner mit den Unterlagen des Bereichs, im Projekt des Kontextordners der Kontextordner selbst. Dann der Kontextordner in den übrigen Projekten des Accounts.
- **Instruktionen des Projekts** als Block zum Kopieren, kurz, weil der Index aus der `CLAUDE.md` im Ordner kommt:
  ```
  Projekt für <Bereich>. Am Mac liegt das Wissen im Ordner <Name des Kontextordners>, wo was liegt, sagt dessen CLAUDE.md. Unterwegs ohne Ordner gilt das Projektwissen. Neues merken in Memory, nicht in Dateien.
  ```
  In Projekten mit Use account memory aus dazu die Zeile `<Name des Kontextordners>: nur lesen, ändern nur auf meinen Zuruf`.
- **Memory:** an, Use account memory an oder aus nach dem Schnitt.

Das Projekt für den Grundbereich (meist Privat) besteht schon, die Einrichtung läuft darin. Es braucht nur noch Beschreibung und Instruktionen. Hat ein vorhandenes Projekt schon eigene Instruktionen, die der Nutzer eingefügt hat, den neuen Block als Ergänzung bauen: Bestehendes bleibt, Neues kommt dazu, der Block zeigt den ganzen neuen Text.

## Rechte der Connectoren

In Alltagssprache, ohne Tabelle je Werkzeug: "Stell bei jedem Connector alles auf Immer erlauben, außer diese auf Fragen:" und eine kurze Liste der Werkzeuge, die senden, antworten, weiterleiten, einladen, zusagen, teilen oder veröffentlichen, mit ihrem Namen in der App. Löschen auf Blockiert, wenn der Connector es anbietet. Nichts sonst auf Blockiert.

Für die Plugins des Pakets gibt es in Cowork keine Schalter je Werkzeug. Dafür ein Satz: Was andere sehen (Senden, Arbeitskalender, Termine mit Teilnehmern, geteilte Notizordner, Übertragen ins Original) und Änderungen der Einstellungen fragen mit einem Dialog am Mac, alles andere bleibt im eigenen Account. Fragt Cowork beim ersten Aufruf eines Werkzeugs aus dem Paket selbst nach einer Freigabe, dort Immer erlauben wählen: Den Schutz vor Wirkung auf andere hält der Dialog am Mac.

## Geplante Aufgaben

Ein eigener Schritt, keine Frage am Rand. Erst erklären: Eine geplante Aufgabe läuft zu einer festen Zeit von selbst in einem Projekt, das Ergebnis steht danach als Aufgabe in der Seitenleiste, sie sendet nie etwas und läuft nur, wenn die App am Mac offen ist. Dann zwei Vorschläge, je mit eigenem Ja:

| Aufgabe | Projekt | Wann | Text |
|---|---|---|---|
| Tagesstart | Grundbereich | werktags 7:30 Uhr, auf Wunsch montags als eigene Aufgabe mit Wochenstart | `/basis:tagesstart` (montags `/basis:tagesstart Wochenstart`) und darunter: `Lauf ohne Aufsicht, nichts senden.` |
| Kontext abgleichen | Projekt des Kontextordners | monatlich am ersten Freitag 10 Uhr, sonst wöchentlich freitags | `/basis:kontext aktualisieren` und darunter: `Lauf ohne Aufsicht. Nur am ersten Freitag im Monat (Tag 1 bis 7): an anderen Tagen nur "Kein Abgleich heute." antworten und enden. Fragen bleiben in wissen/_interview.md, nichts senden.` |

Gibt es in der Session ein Werkzeug für geplante Aufgaben, legt Claude die bestätigten selbst an und nennt Name und Zeit. Sonst stehen sie mit Text und Zeitplan in der Prüfliste. Startet der Befehl in einer Aufgabe den Skill nicht, ersetzt ihn die Zeile `Lies den Skill kontext im Plugin basis und führe den Modus aktualisieren aus.`, beim Tagesstart `Lies den Skill tagesstart im Plugin basis und führe ihn aus.`

## Prüfliste (`einrichtung/pruefliste.md`)

Erste Zeile `Erzeugt von /basis:einrichten am JJJJ-MM-TT`. Was der Nutzer selbst tut, in dieser Reihenfolge, je Punkt `- [ ]`, Wo und Wie in einem Satz, nur was für ihn gilt:
1. Einstellungen > Your Claude: alten Text der Instructions sichern, dann `einrichtung/instructions.md` einfügen, letzte Zeile sichtbar.
2. Einstellungen > Capabilities: Memory an, Account-Memory an.
3. Projekte: je Projekt Beschreibung, Ordner in der genannten Reihenfolge, Instruktionen, Use account memory.
4. Customize > Connectors: Rechte wie oben.
5. Geplante Aufgaben, die Claude nicht selbst anlegen konnte.
6. Freigaben in macOS, die noch fehlen.
7. Zusatzprogramme für Kalender und Erinnerungen, wenn `termine_lesen`, `termin_anlegen` oder `erinnerungen_lesen` `EventKit fehlt` oder `icalBuddy fehlt` melden: im Terminal Schritt 1 von `INSTALL.md` des Pakets ab Befehl 3 (Homebrew mit `ical-buddy` und `python@3.12`, dann die `.venv`).
8. Motor für Office, nur wenn er in Schritt 4 fehlte und der Nutzer ihn wollte: im Terminal die drei Befehle aus `ablauf.md` (Abschnitt Dokumente) wörtlich in die Prüfliste, danach Claude mit Cmd+Q neu starten.
9. Kontextordner ohne Git: im Terminal `git -C "<Kontextordner>" init -q`, wenn gewünscht.

## Proben (Schritt 11)

Nummeriert ab 1, eine nach der anderen. Je Probe vier Zeilen: **Wo** (neue Aufgabe in Cowork, in welchem Projekt oder ohne), **Eingabe** (wörtlich), **Erwartung**, **Wenn nicht** (was dann zu tun ist). Nach jeder fragen, ob es passt, Auffälliges als Zeile in `wissen/_rueckmeldungen.md` (Skill `feedback`).

1. Ohne Projekt: "Wie soll ich dich ansprechen, und was schreibe ich nie?" Erwartung: Anrede und verbotene Zeichen aus den Instructions. Wenn nicht: Instructions eingefügt und neue Aufgabe gestartet?
2. Projekt Grundbereich: "Was ist neu in Mail?" Erwartung: neue Mails je Konto, Newsletter ausgeblendet. Wenn nicht: Automation für Mail in den Systemeinstellungen.
3. Projekt Grundbereich: "Was steht morgen an?" Erwartung: Termine nach Kalender. Wenn nicht: Kalender-Freigabe, `.venv`.
4. Projekt Grundbereich, mit Plugin `chat`: "Neue WhatsApp-Nachrichten?" Erwartung: Einzelchats zuerst. Wenn nicht: Festplattenvollzugriff, `einstellungen` mit `freigabe` öffnet beide Fenster.
5. Projekt Grundbereich: "Wer ist <Name aus privat-personen.md>?" Erwartung: Beziehung und Kanal aus dem Wissen. Wenn nicht: Kontextordner als Ordner im Projekt?
6. Projekt Grundbereich: "Schreib mir selbst eine Mail mit dem Betreff Test." Erwartung: Entwurf in Apple Mail, gesendet wird nichts ohne "senden".
