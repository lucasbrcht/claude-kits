---
name: feedback
description: Fehler und Wünsche zum Paket still sammeln und gesammelt als Mail-Entwurf an den Betreuer vorlegen, auch wenn ein Skill des Pakets erkennbar gescheitert ist. Nicht für Korrekturen am eigenen Kontext (Skill kontext) und für Fehler anderer Programme.
---

# feedback

> **Plugin-Ordner: `${CLAUDE_PLUGIN_ROOT}`.** Der Paketordner ist die Ablage von claude-kits mit `einrichtung.json` und `.claude-plugin/marketplace.json`, standardmäßig `~/Claude Kits/claude-kits`, nur im Code-Tab mit lokalem Marketplace zwei Ebenen über dem Plugin-Ordner. Befehle anderer Plugins immer mit dem ausgeschriebenen Pfad `<Paketordner>/plugins/<plugin>/<skript>`, nie mit `..`.

Das Paket wird besser, wenn Fehler und Wünsche beim Betreuer ankommen. Gesammelt wird still, gemeldet per Mail-Entwurf, den der Nutzer selbst sendet.

**Orte:**
- `<Kontextordner>/wissen/_rueckmeldungen.md`: Rückmeldungen des Nutzers (Format in Zeile 2 der Datei). Den Kontextordner nennt der Kontext-Index der `CLAUDE.md`.
- `~/Library/Application Support/Claude Kits/.fehler.jsonl`: Abbrüche der Skripte, die ein Server gestartet hat, je Zeile Datum, Plugin, Skript, Unterbefehl, Code. Schreiben die Skripte selbst, ohne Inhalte.

## Sammeln

Auslöser: Der Nutzer nennt einen Fehler oder Wunsch, oder ein Skill des Pakets ist gescheitert (Befehl abgelehnt, falsches Konto, Format gebrochen, Datei nicht gefunden).

Eine Zeile unter `## Offen` anhängen: `- JJJJ-MM-TT · Skill · Fehler oder Wunsch · Beschreibung in einem Satz`. Die Beschreibung nennt das Fehlerbild, nicht den Fall:
- Ja: `- 2026-11-12 · mail · Fehler · Antwort landete beim falschen Konto`
- Nein: Namen, Betreffe, Mail- oder Chattexte, Termintitel, Adressen, Nummern.

Nicht erwähnen, außer der Nutzer hat ausdrücklich gemeldet: dann in einer Zeile bestätigen. Nichts doppelt eintragen.

## Fragen

Höchstens einmal je Woche, am Ende einer Antwort, nie mitten in einer Aufgabe: Stehen drei oder mehr Zeilen unter `## Offen`, oder ist die älteste älter als sieben Tage und `Zuletzt gefragt` liegt mehr als sieben Tage zurück, in einem Satz fragen, ob die Rückmeldungen als Mail-Entwurf vorbereitet werden sollen. `Zuletzt gefragt:` auf heute setzen, auch bei Nein.

## Melden

1. Zeilen unter `## Offen` zeigen, dazu aus `.fehler.jsonl` die Abbrüche seit der letzten Meldung, gezählt je Plugin, Skript und Unterbefehl (etwa `mail.py draft, Code 3, 2 Mal`). Der Nutzer streicht oder ergänzt.
2. Empfänger: `owner.email` aus `<Paketordner>/.claude-plugin/marketplace.json`. Fehlt sie, den Entwurf ohne Empfänger anlegen und das sagen.
3. Entwurf mit `mail_entwurf`: `an` die Adresse, `betreff` `[Kits] Rückmeldung JJJJ-MM-TT`, `profil` privat. Inhalt:
   - Version: `git -C "<Paketordner>" describe --tags`, sonst die Version aus `.claude-plugin/plugin.json` dieses Plugins
   - Plattform: macOS-Version, soweit bekannt
   - je Rückmeldung eine Zeile: Skill, Fehler oder Wunsch, Beschreibung
   - die gezählten Abbrüche
   - Gruß wie im Stilprofil privat
4. Den Entwurf vollständig zeigen. Gesendet wird nur auf "senden", nach dem Ablauf im Skill `mail`.
5. Danach die gemeldeten Zeilen nach `## Gemeldet` verschieben, Datum davor. Einträge dort, die älter als sechs Monate sind, löschen. `.fehler.jsonl` bleibt, die nächste Meldung zählt ab dem Datum dieser.

Ohne Plugin apple: den Text im Chat zum Kopieren geben, Betreff und Empfänger dazu.

**Nie in den Bericht:** Mail- und Chattexte, Namen, Adressen, Nummern, Inhalte aus Terminen, Notizen oder Dateien. Braucht der Betreuer mehr, fragt er nach.
