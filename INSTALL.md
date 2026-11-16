# Installation

Für deinen Mac mit der Claude-App. Du richtest einmal ein, danach hilft dir dein Assistent in Cowork bei Mail, Kalender, Nachrichten, Notizen und Erinnerungen.

- **Dauer:** etwa 25 Minuten für die Installation (Schritte 1 bis 5), danach 30 bis 45 Minuten Einrichtung im Gespräch (Schritt 6). Beides geht an einem Termin oder an zwei.
- **Am einfachsten** lässt du dich von Claude durchführen (nächster Abschnitt). Die Schritte darunter sind zum Nachlesen oder für den Weg von Hand.
- **Was du tippen sollst**, steht in einem grauen Kasten: kopieren, einfügen, Enter.
- **Menüs der App** stehen hier mit ihren englischen Namen (Customize, Plugins). Zeigt deine App sie auf Deutsch, heißen sie entsprechend.

## Was du brauchst

- Einen Mac mit macOS 14 (Sonoma) oder neuer und das Passwort, mit dem du dich am Mac anmeldest.
- Die Claude-App für den Mac, angemeldet mit deinem Konto. In der App gibt es Cowork.
- Apple Mail mit deinen Mailkonten, dazu Kalender, Notizen, Erinnerungen und Kontakte, so wie du sie heute nutzt.
- WhatsApp für Mac, angemeldet, wenn Claude auch WhatsApp lesen soll.
- Internet.

## Der einfache Weg: Claude führt dich durch

Claude erledigt im Code-Tab der App alles, was sich am Mac per Befehl machen lässt, und prüft es. Was nur du klicken kannst, sagt er dir Schritt für Schritt an.

1. Claude-App öffnen und oben auf **Code** wechseln.
2. Fragt die App nach einem Ordner, deinen Benutzerordner wählen (der mit deinem Namen und dem Haus-Symbol).
3. Diesen Text einfügen und Enter:

   ```text
   Führe mich durch die Installation des Pakets claude-kits auf diesem Mac. Die Anleitung: https://raw.githubusercontent.com/lucasbrcht/claude-kits/main/INSTALL.md
   So arbeitest du:
   - Lies erst die ganze Anleitung. Dann Schritt 1 bis 5 der Reihe nach, immer nur einen Schritt, in einfachen Worten.
   - Prüf vor jedem Schritt, was schon da ist, und überspring es.
   - Befehle aus der Anleitung führst du selbst aus und prüfst das Ergebnis. Den Homebrew-Befehl (Schritt 1, Befehl 2) gibst du mir zum Einfügen ins Terminal, er braucht mein Passwort.
   - Was ich in macOS oder in der Claude-App klicken muss, sagst du Klick für Klick an und wartest auf mein "fertig".
   - Installiere nichts außer dem, was in der Anleitung steht. Lösche nichts.
   - Zum Schluss sag mir, wie ich Schritt 6 in Cowork starte.
   ```

4. Vor jedem Befehl fragt Claude, ob er ihn ausführen darf: erlauben. Fenster von macOS bestätigst du selbst.

Zwei Dinge macht Claude nicht für dich: Plugins und Projekt gehören in dein Claude-Konto, das stellst du in der App ein (Schritte 3 und 5). Die Einrichtung im Gespräch (Schritt 6) startest du danach in Cowork, dort arbeitest du auch im Alltag.

## Schritt 1: Zusatzprogramme für den Mac (Terminal, etwa 15 Minuten)

Für Kalender und Erinnerungen braucht dein Mac ein paar kostenlose Zusatzprogramme. Öffne das Programm **Terminal**: Cmd+Leertaste, `Terminal` tippen, Enter.

1. **Entwicklerwerkzeuge von Apple.** Einfügen, Enter:

   ```bash
   xcode-select --install
   ```

   Im Fenster **Installieren** und **Akzeptieren** klicken und warten, bis es fertig ist (5 bis 10 Minuten). Meldet das Terminal `already installed`, sind sie schon da.

2. **Homebrew**, das holt die übrigen Programme. Einfügen, Enter, dann dein Mac-Passwort (beim Tippen erscheint nichts) und Enter. Fragt es nach `RETURN`, noch einmal Enter:

   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```

   Die Hinweise am Ende (Next steps) brauchst du nicht.

3. **Kalender-Hilfe und Python.** Einfügen, Enter (2 bis 5 Minuten):

   ```bash
   /opt/homebrew/bin/brew install ical-buddy python@3.12
   ```

4. **Zugang zu Kalender und Erinnerungen.** Beide Zeilen zusammen einfügen, Enter (etwa 1 Minute):

   ```bash
   /opt/homebrew/opt/python@3.12/bin/python3.12 -m venv "$HOME/Library/Application Support/Claude Kits/apple/.venv"
   "$HOME/Library/Application Support/Claude Kits/apple/.venv/bin/pip" install pyobjc-framework-EventKit
   ```

5. **Prüfen.** Einfügen, Enter:

   ```bash
   "$HOME/Library/Application Support/Claude Kits/apple/.venv/bin/python3" -c "import EventKit" && echo "EventKit ok"
   ```

   Steht da `EventKit ok`, ist Schritt 1 fertig. Terminal schließen.

Mac mit Intel-Prozessor (Apfelmenü > Über diesen Mac, Zeile Prozessor statt Chip): in den Befehlen 3 und 4 `/opt/homebrew` durch `/usr/local` ersetzen.

## Schritt 2: Freigabe in macOS (2 Minuten)

Damit Claude WhatsApp, iMessage und Kontakte lesen kann, braucht ein Programm der Entwicklerwerkzeuge den Festplattenvollzugriff. Mit ihm laufen die Werkzeuge des Pakets.

1. Systemeinstellungen > Datenschutz & Sicherheit > **Festplattenvollzugriff**.
2. Unten auf **+** klicken und mit Passwort oder Touch ID bestätigen.
3. Im Fenster Cmd+Umschalt+G drücken, diesen Pfad einfügen, Enter:

   ```text
   /Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin
   ```

4. `python3.9` wählen, **Öffnen**. Der Schalter daneben muss an sein.

Alle anderen Freigaben fragt dein Mac später von selbst, wenn Claude zum ersten Mal Mail, Kalender, Erinnerungen, Notizen oder Nachrichten braucht. Dann **OK** oder **Erlauben** klicken, bei Kalender und Erinnerungen **Vollzugriff**. Im Fenster kann ein technischer Name stehen, etwa `python3.9`: Das sind die Werkzeuge des Pakets.

## Schritt 3: Plugins in Claude (5 Minuten)

1. Claude öffnen, links **Customize**, dann **Plugins**.
2. **Add marketplace** wählen, das hier eintragen und bestätigen:

   ```text
   lucasbrcht/claude-kits
   ```

3. Beim neuen Marketplace **Sync automatically** einschalten. Dann kommen Verbesserungen von selbst.
4. Diese Plugins installieren, je Plugin **Install**:

   | Plugin | Wofür | Installieren |
   |---|---|---|
   | `basis` | Einrichtung, Gedächtnis, Feedback | immer |
   | `apple` | Mail, Kalender, Notizen, Erinnerungen, Kontakte | immer |
   | `chat` | WhatsApp und iMessage | wenn du das nutzt |
   | `service` | Roadbook für Rad-Events, Home Assistant | nur nach Absprache mit dem Betreuer, braucht weitere Programme |
   | `pflege` | Werkzeug des Betreuers | nie |

5. Claude mit **Cmd+Q** ganz beenden und neu öffnen. Erst dann starten die Plugins.

Fragt Claude beim Marketplace nach einer Verbindung mit GitHub, gib dem Betreuer Bescheid.

## Schritt 4: Mail-Connector (nach Wunsch, 2 Minuten)

Liegt deine Mail bei Gmail, kann Claude dort auch im Text der Mails suchen. Links **Customize**, dann **Connectors**, **Gmail** wählen, verbinden und mit deinem Google-Konto anmelden. Welche Rechte du dort einstellst, sagt dir die Einrichtung in Schritt 6. Geschrieben und gesendet wird immer über Apple Mail. Ohne Connector geht alles auch, Claude sucht dann nur in Betreff und Absender.

## Schritt 5: Projekt Privat (3 Minuten)

Was Claude über dich lernt, liegt in einem Ordner auf deinem Mac. Ein Projekt in Cowork verbindet ihn mit Claude.

1. Im Finder deinen Benutzerordner öffnen (Cmd+Umschalt+H). Darin den Ordner `Claude Kits` anlegen und darin den Ordner `kontext`. Nicht in iCloud Drive.
2. In Claude in Cowork links **Projects**, dann **New project**. Name `Privat`, Beschreibung `Familie, Freunde, Haushalt und Freizeit`.
3. Als Ordner **Use an existing folder** wählen und `Claude Kits/kontext` aussuchen.

Nutzt du Claude auch für die Arbeit, leg trotzdem erst nur Privat an. In Schritt 6 fragt Claude nach deinen Bereichen (Arbeit, Selbständigkeit, Verein) und ob deine Firma ein eigenes Claude-Konto hat. Danach empfiehlt er dir weitere Projekte, je mit Ordnern, Instruktionen und Memory, und schreibt sie in deine Prüfliste.

## Schritt 6: Einrichtung im Gespräch (30 bis 45 Minuten)

1. Im Projekt Privat eine neue Aufgabe starten und das hier eingeben:

   ```text
   /basis:einrichten
   ```

2. Claude stellt sich vor und bittet dich, oben das stärkste Modell zu wählen. Danach `los` schreiben.
3. Claude schaut, mit wem du am häufigsten schreibst und welche Kalender du hast. Inhalte liest es dabei nicht. Du bestätigst Personen, beantwortest ein paar Fragen und prüfst dein Stilprofil.
4. Wenn Claude deine Einstellungen speichert, fragt dein Mac jedes Mal mit einem Fenster: **Freigeben** klicken.
5. Zum Schluss bekommst du eine Prüfliste mit dem, was nur du in der App einstellen kannst: Text für die Instructions for Claude, Memory, Rechte der Connectoren, geplante Aufgaben. Sie liegt auch als Datei `einrichtung/pruefliste.md` im Ordner `kontext`. Danach ein paar kurze Proben.

Pausieren geht jederzeit. Später im Projekt Privat wieder `/basis:einrichten` eingeben, Claude macht dort weiter.

## Wenn etwas hakt

| Was passiert | Was hilft |
|---|---|
| Claude findet keine Werkzeuge für Mail oder Kalender | Customize > Plugins: `basis` und `apple` installiert und eingeschaltet? Dann Claude mit Cmd+Q beenden und neu öffnen |
| Kontakte, WhatsApp oder iMessage lassen sich nicht lesen | Schritt 2 prüfen, danach Claude mit Cmd+Q neu starten |
| Meldung `EventKit fehlt` oder `icalBuddy fehlt` | Schritt 1 ab Befehl 3 wiederholen |
| Meldung `Kein Zugriff auf Kalender` oder `Erinnerungen` | Systemeinstellungen > Datenschutz & Sicherheit > Kalender oder Erinnerungen: beim Eintrag `python3.9` Vollzugriff wählen |
| Meldung zu Automation bei Mail oder Notizen | Systemeinstellungen > Datenschutz & Sicherheit > Automation: beim gezeigten Eintrag Mail oder Notizen einschalten |
| Antwort in Mail ohne Text, Meldung zu Bedienungshilfen | Systemeinstellungen > Datenschutz & Sicherheit > Bedienungshilfen: den Eintrag einschalten, den dein Mac dort neu zeigt |
| Fenster deines Macs nicht gesehen oder Abbrechen geklickt | Claude bitten, es noch einmal zu versuchen, und auf den Mac schauen |
| Nach einem Update von macOS geht WhatsApp oder Kontakte nicht mehr | Schritt 2 wiederholen. Gibt es den Ordner `3.9` nicht mehr, dem Betreuer Bescheid geben |

## Im Alltag

- **Updates** kommen von selbst (Sync automatically). Wirkt etwas Neues nicht, Claude mit Cmd+Q neu starten.
- **Geplante Aufgaben** laufen nur, wenn die Claude-App am Mac offen ist.
- **Feedback:** Sag zum Beispiel "Feedback: Die Erinnerung kam ohne Uhrzeit." Claude sammelt das und legt dir bei Gelegenheit einen Mail-Entwurf an den Betreuer vor, ohne Namen oder Inhalte. Die Adresse des Betreuers trägst du selbst ein.

## Was wo liegt

| Ort | Inhalt | Wer es sieht |
|---|---|---|
| Customize > Plugins | die Plugins aus dem Marketplace | Das Paket ist öffentlich, deine Daten sind nicht darin |
| `~/Claude Kits/kontext/` | dein Kontext: Profil, Personen, Vorlieben, Prüfliste | nur du, nur auf diesem Mac |
| `~/Library/Application Support/Claude Kits/<plugin>/` | Einstellungen je Plugin (`apple`, `chat`, `service`): `config.json`, Stilprofile in `style/`, bei `apple` die `.venv` aus Schritt 1 | nur du, nur auf diesem Mac |
| Instructions for Claude, Memory, Projekte | dein Claude-Konto | nur du |

## Entfernen

Customize > Plugins, je Plugin **Remove**. Deine Ordner bleiben: `~/Claude Kits/kontext/` und `~/Library/Application Support/Claude Kits/` löschst du bei Bedarf selbst im Finder.

## Für den Betreuer: Code-Tab

Nur für Pflege und Fehlersuche, nicht für den Alltag. Plugins aus dem Konto erscheinen im Code-Tab von selbst. Für die Pflege mit `paket.py`:

1. Repository klonen: `git clone https://github.com/lucasbrcht/claude-kits.git "$HOME/Claude Kits/claude-kits"`.
2. `einrichtung.example.json` im Paketordner als `einrichtung.json` ablegen und anpassen (nicht im Git).
3. `python3 "$HOME/Claude Kits/claude-kits/plugins/pflege/paket.py"` zeigt, was sich in `settings.json` und der `CLAUDE.md` der Instanz ändert, `--apply` im Terminal schreibt es.
4. Tests, Prüfung und Release: `README.md` (Abschnitt Entwicklung) und `CLAUDE.md` im Repository.
