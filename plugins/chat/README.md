# Plugin chat

WhatsApp (`whatsapp.py`, Skill `whatsapp`) und iMessage und SMS der Nachrichten-App (`imessage.py`, Skill `imessage`, Abschnitt iMessage und SMS unten). Gemeinsame Teile stehen in `nachricht_basis.py` und `kit_basis.py`.

WhatsApp für Mac lesen, durchsuchen, zusammenfassen lassen und Antworten als Entwurf öffnen, in Cowork und im Code-Tab über die Werkzeuge des Servers. Nichts verlässt das Gerät: keine Cloud, keine inoffizielle API, kein zweites verknüpftes Gerät. Das Skript liest nur die Datenbank, die die WhatsApp-App ohnehin lokal führt.

Was das Plugin bei WhatsApp bewusst nicht kann: senden, löschen, als gelesen markieren, Medien öffnen. Ein Entwurf ist ein geöffneter Chat mit vorausgefülltem Text. Abgeschickt wird nur mit deinem Enter.

## Installation

In Cowork: Customize > Plugins > Add marketplace mit `lucasbrcht/claude-kits` (Sync automatically), dann `chat` installieren. In Claude Code:

```
/plugin install chat --marketplace lucasbrcht/claude-kits
```

## Voraussetzungen

- macOS mit WhatsApp für Mac (App aus dem App Store), angemeldet und synchronisiert.
- python3 (bei macOS dabei, keine Pakete nötig).
- Festplattenvollzugriff für `python3.9` der Command Line Tools (damit startet der Server), für Aufrufe von Hand für die Claude-App oder das Terminal: Systemeinstellungen > Datenschutz & Sicherheit > Festplattenvollzugriff. macOS bietet für den WhatsApp-Ordner keine Einzelfreigabe. Danach die App neu starten.

## Setup

1. `python3 whatsapp.py check` ausführen. Kommt `OK: Zugriff auf WhatsApp`, stimmt alles.
2. `config.json` prüfen, vor allem `excluded_chats` (siehe unten). `check` meldet, wie viele Ausschlüsse zu keinem Chat passen. Die Datei ist persönlich und steht nicht im Git: Neu anlegen aus der Vorlage `config.example.json` (gleiche Schlüssel, Werte in spitzen Klammern).
3. Optional, aber empfohlen: `python3 whatsapp.py style` und daraus mit Claude `style/profil.md` bauen lassen. Dann klingen Entwürfe nach dir.

## Werkzeuge

Der lokale MCP-Server `server.py` (über `.mcp.json`, Unterbau `mcp_basis.py`) ruft die Skripte auf, ohne Shell. Mit `mcp_nur_lesen` in der `config.json` bietet er nur die Lesewerkzeuge. `config.json`, `style/profil.md` und die Textdateien liegen im Datenordner `~/Library/Application Support/Claude Kits/chat/`, der Server liest nur dort und gibt ihn als `KITS_DATENORDNER` mit. Von Hand ohne die Variable gilt der Plugin-Ordner (für Tests).

| Stufe | Werkzeuge |
|---|---|
| lesen | `chat_neues`, `chat_lesen`, `chat_suchen`, `chat_liste`, `chat_stilprofil` (mit `stilprobe` eigene Nachrichten für ein neues Profil) |
| schreiben | `whatsapp_entwurf`, `imessage_entwurf` (Entwurf öffnen, der Nutzer sendet selbst) |
| nachfrage | `imessage_senden`, erst nach Dialog von macOS |

`config.json` und das Stilprofil schreibt in Cowork das Werkzeug `einstellungen_schreiben` aus dem Plugin `apple` (mit `plugin` chat), Claude erreicht den Datenordner dort nur über einen Server. Für den Code-Tab schreibt `paket.py` (Plugin pflege) nur die Sperren für direkte Zugriffe auf den WhatsApp-Ordner, die Nachrichten-App und das Adressbuch aus `kit.json` in die `settings.json`. Schreibende Schalter stehen direkt hinter dem Skript (`whatsapp.py --replace draft --id 12 --text-file nachricht.txt`), an anderer Stelle bricht das Skript ab. Die Sandbox darf im Plugin nicht schreiben, Dateien nur mit Edit oder Write ändern. Von Hand laufen die Befehle mit absolutem Pfad als eigener Befehl, ohne `cd`, Pipe oder Umleitung.

## config.json

| Feld | Bedeutung |
|---|---|
| `database_dir` | Ordner der App. Gelesen werden nur `ChatStorage.sqlite` und `ContactsV2.sqlite` (Namen für Absender in Gruppen und Erwähnungen, Nummern für Entwürfe). |
| `me`, `me_names` | Name für eigene Nachrichten in der Ausgabe und Namen, an denen `triage` Erwähnungen in Gruppen erkennt. |
| `excluded_chats` | Chats, die das Skript nie liest, durchsucht, zählt oder anzeigt. Name wie in WhatsApp oder wie in der Ausgabe des Skripts, oder JID (robuster, Namen ändern sich). |
| `exclude_hidden` | Versteckte Chats (Feld `ZHIDDEN`, vermutlich auch die Chat-Sperre, nicht getestet) bleiben unsichtbar. Standard `true`. |
| `hidden_kinds` | Chat-Arten, die in Übersicht, Triage und Suche fehlen: Status, Kanäle, Broadcasts, Communities. Mit `--all` sichtbar. |
| `forbidden_chars` | Zeichen, mit denen `draft` keinen Entwurf öffnet: Gedankenstriche, Auslassungspunkte (auch drei Punkte), Semikolons, deutsche Anführungszeichen. Smileys wie `;-)` und Links zählen nicht. |
| `entwurf_im_hintergrund` | `true` öffnet Entwürfe mit `open -g`, ohne WhatsApp nach vorn zu holen. Gilt auch ohne den Schlüssel (siehe Grenzen). Nur `false` holt WhatsApp nach vorn. |
| `defaults` | Zeiträume und Grenzen, u.a. `max_chars` (Obergrenze je Ausgabe, schützt den Kontext) und `style_max_chars`. |

Falsche Typen, etwa ein Text statt einer Liste bei `excluded_chats`, brechen jeden Befehl mit einer klaren Meldung ab, statt still zu wirken.

## Beispielaufrufe

```bash
python3 whatsapp.py check
python3 whatsapp.py triage                    # letzte 48 Stunden, Einzelchats mit neuer Nachricht zuerst
python3 whatsapp.py triage 12
python3 whatsapp.py chats --days 30           # aktive Chats mit Nachrichtenzahl
python3 whatsapp.py chats --query rsv         # Chats nach Namen finden
python3 whatsapp.py chats --query rsv --query 'Anna'   # mehrere Namen in einem Aufruf, je Name ein Block (auch imessage.py)
python3 whatsapp.py chats --days 365 --sort anzahl --kind gruppe
python3 whatsapp.py members 'Familie'         # Mitglieder einer Gruppe, nur Namen
python3 whatsapp.py read 'Erika' --days 7
python3 whatsapp.py read --id 515 --before-id 90210   # weiterlesen, so wie der Hinweis es vorgibt
python3 whatsapp.py search trikot bioracer
python3 whatsapp.py search termin --chat 'Familie' --days 60
python3 whatsapp.py draft --id 515 --text 'Bin in 10 Minuten da' --dry-run
python3 whatsapp.py draft --id 515 --text 'Bin in 10 Minuten da'
python3 whatsapp.py draft --id 515 --text-file nachricht.txt
python3 whatsapp.py style --n 200
python3 -B -m unittest discover tests         # alle Tests auf künstlichen Datenbanken (auch imessage.py)
```

Jeder Befehl kennt `--help`, Abkürzungen von Optionen gelten nicht. Mehrdeutige Namen listet das Skript mit id, dann `--id` verwenden. Für Entwürfe und Senden stehen Name und `--id` zusammen im Aufruf, so wie der Hinweis von `imessage.py draft --dry-run` ihn nennt (`send 'Erika' --id 482`): Dann zeigt jede Rückfrage, an wen es geht, und das Skript prüft, dass beide zum selben Chat passen. Der Name muss genau der Name dieses Chats sein (auch ein erzeugter wie Gruppe mit Anna, Ben) oder allein genau ihn treffen, sonst bricht der Befehl mit Exit 2 ab. Falsche Aufrufe enden immer mit Exit 2, Fehler beim Lesen oder Öffnen mit Exit 1. Ein ganzes Wort zählt vor einem Wortanfang ("Erika" trifft "Erika Muster", nicht die Gruppe "Erikas 40."). Status-Chats und Kanäle zählen beim Namen nur, wenn sonst nichts passt. Für Entwürfe rät das Skript nie: Passen nur Wortanfänge, mehrere gleich gut oder noch eine zweite Person ("Paul" und "Paul Beispiel"), kommt "Mehrdeutig".

Lange Verläufe liest man seitenweise: Der Hinweis unter dem Kopf nennt den Folgeaufruf mit `--before-id` (id der ältesten gezeigten Nachricht). So fehlt keine Nachricht, auch nicht bei gleicher Sekunde, in der doppelten Stunde der Zeitumstellung oder hinter einer Kürzung.

## Sicherheit und Datenschutz

| Schutz | Wie er greift |
|---|---|
| Nur lesen | Das Skript kopiert Datenbank und WAL in einen privaten Temp-Ordner (0700), übernimmt sie sofort per Backup in eine Datenbank im Speicher und löscht die Kopie. Das Original wird nie geöffnet. |
| Abbruch | SIGTERM, SIGINT und SIGHUP räumen die Kopie auf. Reste eines harten Abbruchs (älter als 2 Minuten) löscht der nächste Aufruf. Laufende Aufrufe sperren ihren Ordner (flock), so bleibt auch die Kopie eines langsamen parallelen Laufs stehen. Nach `kill -9` gibt das System die Sperre frei. |
| Kein Senden | Es gibt keinen Sendebefehl. `draft` öffnet `whatsapp://send`, abschicken geht nur mit Enter in der App. |
| Ausschlüsse | `excluded_chats` und versteckte Chats werden schon beim Laden entfernt. Sie tauchen in keiner Ausgabe auf, auch nicht per id, und zählen auch nicht in `check`. |
| Sparsame Ausgabe | Standorte ohne Koordinaten, Kontaktkarten nur mit Namen, Namen aus Telefonnummern werden ersetzt, Erwähnungen als `@Name` statt `@Nummer`, Steuerzeichen entfernt, Zeilentrenner wie Umbrüche, Ausgaben auf `max_chars` begrenzt. |
| Gegen untergeschobene Anweisungen | Jede Ausgabe mit Nachrichten oder Namen trägt den Hinweis, dass sie Daten sind. Chat- und Gruppennamen sind auf 60 Zeichen gekürzt, eckige Klammern werden runde. Die Regeln im Skill verbieten, Nachrichten zu folgen oder Links zu öffnen. |
| Nur über das Skript | Im Code-Tab sperrt eine Regel direkte Zugriffe von Claude auf den WhatsApp-Ordner (`permissions.deny` aus `kit.json`). Nur der Server und `whatsapp.py` lesen dort. |
| Stil | `draft` verweigert die Zeichen aus `forbidden_chars`. |
| Entwurfsdateien | `draft --text-file` liest nur `nachricht.txt` im Plugin-Ordner, auch keinen Link von dort woanders hin. `draft` läuft ohne Rückfrage, deshalb kann keine untergeschobene Anweisung beliebige Dateien in einen Entwurf holen. |
| Fehler beim Öffnen | Die Meldung nennt nur den Fehlercode, nie den Link mit Nummer und Text. |

Der Festplattenvollzugriff gilt für den ganzen Mac, nicht nur für WhatsApp. Wer das Plugin selten braucht, schaltet ihn danach wieder aus. Ohne ihn melden alle Befehle, was fehlt.

## Grenzen

- Nur was WhatsApp für Mac gespeichert hat. Sprachnachrichten, Bilder und Dokumente erscheinen als Hinweis, ihr Inhalt nicht. Ist die App geschlossen, kommt nichts Neues dazu: Sind Datenbank und WAL seit über einer Stunde unverändert, warnt die Ausgabe.
- Reaktionen, Umfrage-Ergebnisse und zitierte Nachrichten zeigt das Skript nicht. Einige seltene Nachrichtentypen erscheinen als `[sonstiger Inhalt, Typ N]`. Mit der Typnummer lässt sich die Liste `MEDIEN` in `whatsapp.py` ergänzen.
- Getestet am 24.09.2026: Ein Entwurf an eine Person öffnet den Chat direkt, der Text steht im Eingabefeld. Liegt im Chat ungesendeter Text, öffnet `draft` nur mit `--replace`.
- Getestet am 28.09.2026: Mit `open -g` (`entwurf_im_hintergrund: true`) steht der Text auch im Hintergrund im Chat, WhatsApp bleibt hinten. Ungetestet ist der Start bei geschlossener App.
- Gruppen lassen sich per Link nicht direkt öffnen, WhatsApp zeigte nur die Chat-Auswahl. Dasselbe gilt für neue Kontakte, deren Nummer WhatsApp nicht preisgibt (LID). Der Weg blieb ungetestet, `draft` bricht dort mit einer Zeile ab (Exit 1, Text zum Kopieren geben).
- Die Datenbank ist nicht dokumentiert. Ändert WhatsApp das Schema, meldet das Skript die fehlenden Spalten, statt falsche Ergebnisse zu liefern. Eine leere Datenbank (App noch nicht angemeldet) meldet es als leer.

## iMessage und SMS

`imessage.py` liest `~/Library/Messages/chat.db` der Nachrichten-App genauso wie `whatsapp.py`: Kopie von Datenbank und WAL, sofort in den Speicher, Kopie weg. Namen kommen aus dem Adressbuch des Macs (`AddressBook-v22.abcddb` aller Quellen), Nummern und Mailadressen erscheinen nie in einer Ausgabe. Befehle: `check`, `chats`, `members`, `triage`, `read`, `search` wie bei WhatsApp, dazu `draft` und `send`.

```bash
python3 imessage.py check                                  # Zugriff, Datenbank, Adressbuch, nur Zahlen
python3 imessage.py triage 48
python3 imessage.py read 'Erika' --days 7
python3 imessage.py draft --id 482 --text 'Bin gleich da' --dry-run   # Vorschau: Empfänger, Dienst, Text, Aufruf für send
python3 imessage.py draft --id 482 --text-file nachricht.txt          # Entwurf im Hintergrund, man sendet selbst
python3 imessage.py send 'Erika' --id 482 --text 'Bin gleich da'      # senden mit Sendeprüfung, Name und id wie in der Vorschau
python3 imessage.py send 'Erika' --id 482 --text-file nachricht.txt --code 1a2b3c4d --anfang 'Bin gleich da'
python3 -B -m unittest discover tests      # Tests beider Skripte, wie bei WhatsApp
```

| Thema | Wie es gelöst ist |
|---|---|
| Text im Blob | Der Text steht meist nur in `attributedBody` (typedstream). Der Dekoder liest die Länge als Byte, nach `0x81` aus 2 Byte und nach `0x82` aus 4 Byte und verlangt danach die Endmarke `0x86`. Geprüft am 20.10.2026 auf macOS 27 mit einer Diagnose in `check` (heute entfernt, die Unit-Tests decken die Grenzen ab): alle Blobs gelesen, auch die Grenzfälle 127, 128, 255, 256 und über 300 Byte mit Umlauten und Emoji. |
| Chats | Einzelchats derselben Person (Nummer und Mailadresse, iMessage und SMS) erscheinen als ein Chat, zusammengefasst über die Adresse oder die Kontaktkarte, nie über den Namen. Die id ist die des zuletzt aktiven Chats, frühere ids gelten weiter. Hat ein Chat mehrere Teilchats (Nummer und Mailadresse, eine Kontaktkarte Eltern mit zwei Nummern), nennt `read` sie mit id, Art wie Nummer 1 von 2 und letzter Aktivität, jede Nachricht trägt die id ihres Teilchats, und `draft` und `send` ohne `--id` enden mit Mehrdeutig und dieser Liste. Nummern gleichen Kontakte nur genau ab, genormt mit der Landesvorwahl (+49 176, +49 0176, 0176 und ohne Präfix gespeicherte Ziffern sind gleich), nie über eine gleiche Endung (Review 21.10.2026). SMS-Absender ohne Rufnummer (Firmen, Kurzwahlen, Codes) sind Art Dienst und standardmäßig ausgeblendet (`imessage.hidden_kinds`), auch `read` zeigt sie nur mit `--all`. Gruppen ohne Namen heißen Gruppe mit Anna, Ben und sind nur per id erreichbar. `excluded_chats` gilt für Namen (wie im Adressbuch oder wie in der Ausgabe, auch mit eckigen Klammern und über 60 Zeichen), Nummern in jeder Schreibweise, Mailadressen und Chat-GUIDs, ausgeschlossene Mitglieder blenden gemeinsame Gruppen nicht aus. Stehen Namen darin und ist das Adressbuch nicht lesbar, brechen alle Befehle außer `check` ab. |
| Verlauf | Reaktionen (Tapbacks) fehlen, Gruppenereignisse nur mit `--system`, Anhänge als `[Bild]`, `[Video]`, `[Sprachnachricht]` oder `[Dokument] Name`, zurückgezogene und bearbeitete Nachrichten markiert. iCloud-Dubletten (gleicher Text, gleiche Richtung, höchstens 2 Sekunden Abstand) erscheinen einmal, auch beim Weiterlesen über die Grenze einer Seite. |
| Senden | `send` nimmt Text aus `--text` (steht dann in der Rückfrage) oder aus `nachricht.txt` (dann nur mit `--code` und `--anfang` aus dem Hinweis von `draft --dry-run`: Der Code bindet die Rückfrage an genau diesen Text und dieses Ziel, `--anfang` zeigt dort die ersten 40 Zeichen. Fehlt eins oder passt der Anfang nicht, Exit 2), lehnt verbotene und unsichtbare Zeichen ab, prüft Dubletten (derselbe Text in 10 Minuten nur mit `--nochmal`) und die Spalten für die Sendeprüfung und sendet per AppleScript an die Chat-GUID, Text und Ziel als argv. Mit `--id` geht es genau an diesen Teilchat (Nummer oder Mailadresse), der Hinweis der Vorschau nennt `send 'Name' --id N`, damit der Name in der Rückfrage steht. Beim Namen allein trifft eine Gruppe nur mit ihrem ganzen Namen. Seit macOS 26 beginnen GUIDs mit `any`, scheitert das mit Fehler -1728, sendet es bei Einzelchats an `participant` im Konto des Dienstes. Danach sucht es bis etwa 20 Sekunden in `chat.db` die eigene Nachricht mit gleichem Text: Exit 0 gesendet, 3 nicht bestätigt (auch bei Zeitüberschreitung oder wenn die Prüfung selbst scheitert, nie selbst wiederholen), 4 mit Fehler. Die Meldung von `osascript` erscheint nie, sie enthält die Nummer. |
| Entwurf | `draft` öffnet die Nachrichten-App im Hintergrund mit vorbelegtem Text über `imessage.entwurf_link`, nur bei Einzelchats. Getestet am 20.10.2026: `sms:{adresse}&body={text}` belegt den Text vor. Ist der Eintrag leer, geht nur die Vorschau mit `--dry-run`, ohne sie bricht `draft` mit Exit 1 ab (den Text zum Kopieren geben). |
| Rechte | Festplattenvollzugriff wie bei WhatsApp, beim ersten Senden der macOS-Dialog Automation für Nachrichten. Lesen und `imessage_entwurf` laufen ohne Rückfrage, `imessage_senden` zeigt immer den Dialog von macOS. Im Modus lesen (`mcp_nur_lesen`) gibt es nur die Lesewerkzeuge. Im Code-Tab sind direkte Zugriffe auf `~/Library/Messages` und das Adressbuch gesperrt. Eine zweite App (etwa eine Parall-Kopie) braucht eigene macOS-Freigaben, `check` meldet, was fehlt. |
