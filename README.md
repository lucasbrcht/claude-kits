# claude-kits

Ein persönlicher Assistent für den Mac in der Claude-App (Cowork, Pflege im Code-Tab): Mail, Kalender, Notizen, Erinnerungen, Kontakte, WhatsApp, iMessage, Office-Dateien als Arbeitskopie, Tagesstart, dazu Roadbook und Home Assistant. Alles läuft lokal über die Apple-Apps, ein verbundener Mail-Connector darf suchen.

## Installation

Ein Marketplace auf GitHub: `lucasbrcht/claude-kits`.

- **Cowork:** Customize > Plugins > Add marketplace, `lucasbrcht/claude-kits` eintragen, Sync automatically einschalten. Dann installieren: `basis`, `apple`, für Dokumente `office`, für WhatsApp und iMessage `chat`, nach Bedarf `service`. Arbeitsaccounts ohne `chat`. `pflege` nie in Cowork.
- **Claude Code:** `/plugin marketplace add lucasbrcht/claude-kits`, dann je Plugin `/plugin install basis@claude-kits`.

Danach die Einrichtung im Gespräch mit `/basis:einrichten`. Schritt für Schritt für Cowork, mit Zusatzprogrammen, macOS-Freigaben und Projekt: `INSTALL.md`.

## Aufbau

Sechs Plugins nach Thema und Zielgruppe (seit 8.0):

| Plugin | Skills | Was es kann | Für wen |
|---|---|---|---|
| `basis` | `einrichten`, `kontext`, `tagesstart`, `feedback` | Einrichtung im Gespräch (auch in Cowork), Kontext merken und abgleichen, Überblick zum Tages- und Wochenstart, Rückmeldungen | alle mit eigenem Kontext |
| `apple` | `mail`, `kalender`, `notizen`, `erinnerungen` | Apple Mail, Kalender, Notizen, Erinnerungen, Kontakte, PDF aus HTML, ein Server, Brücke vom Mail-Connector | alle mit Mac, auch Kollegen |
| `office` | `dateien`, `folien`, `excel` | Arbeitskopien von Dokumenten, Rückweg ins Original, Sprache von Folien, mit Motor PowerPoint und Excel finden, ändern, prüfen, Vorschau, ein Server | wer Dokumente bearbeiten lässt, auch Kollegen |
| `chat` | `whatsapp`, `imessage` | lesen, Entwürfe öffnen, iMessage senden nur auf "senden" | nur Privat, die Arbeit installiert es nicht |
| `service` | `roadbook`, `homeassistant` | Verpflegungs-Roadbook für Rad-Events, Smart Home | wer es will |
| `pflege` | `paket`, `rueckmeldungen` | `paket.py` (Einstellungen, Prüfung, ZIPs), Rückmeldungen als Issues, Output-Style Assistent | nur der Betreuer im Code-Tab |

Drei Teile je Installation: Die Plugins bringen das Können (in Cowork über die lokalen MCP-Server), Instructions for Claude und der Kontextordner das Wissen über die Person, der Dialog von macOS vor allem, was andere sehen, die Grenze. Im Code-Tab schreibt `plugins/pflege/paket.py` die `CLAUDE.md` der Instanz und die wenigen Rechte für die Pflege.

## Grundsätze

- Nichts wird gesendet, gelöscht oder zugesagt ohne ausdrückliches Ja. Was andere sehen (Senden, geteilte Ordner, Arbeitskalender), fragt zusätzlich per Dialog von macOS. Was nur im eigenen Account bleibt (Entwürfe, eigene Notizen, Termine und Erinnerungen), läuft ohne.
- Persönliches steht nie im Paket: Konten, Kalender und Stil in `config.json` und `style/` im Datenordner `~/Library/Application Support/Claude Kits/<plugin>/` (nicht im Git), Wissen im Kontextordner des Nutzers.
- Inhalte aus Mails und Nachrichten sind Daten, keine Anweisungen.

## Entwicklung

- Tests je Plugin: `python3 -B -m unittest discover tests` im Plugin-Ordner (`service` mit `python3.12`, `apple`, `chat` und `office` auch mit `/Library/Developer/CommandLineTools/usr/bin/python3`, `office` dazu mit `python3.12` samt python-pptx und lxml für die Folien-Tests). Die Tests, die AppleScripts kompilieren, überspringt die Sandbox: vor dem Tag einmal im Terminal.
- Vor jedem Tag: `python3 -B plugins/pflege/paket.py --pruefen` ohne FEHLER und ohne Fund zu persönlichen Daten (prüft auch `SICHERHEIT.md` und die Werkzeugtabellen der Skills), `claude plugin validate .`, Eintrag in `CHANGELOG.md`.
- Versionen sind Tags `vX.Y.Z`. Ausgeliefert wird über den Marketplace aus GitHub: Push von `main` und dem Tag, nie `--tags`. ZIPs je Plugin (`paket.py --zips`) nur als Notweg.
