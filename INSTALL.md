# Installation

Für einen Mac mit Claude (Desktop-App mit Claude Code oder Claude Code im Terminal). Dauer: etwa 15 Minuten für die Installation, danach 30 bis 45 Minuten Einrichtung im Gespräch.

## Vorher

- macOS mit Apple Mail, Kalender, Notizen, Erinnerungen, Kontakte. WhatsApp für Mac, wenn gewünscht.
- Ein Zugang zum Repository des Pakets (Einladung des Betreuers) und Git: `xcode-select --install` im Terminal, falls `git --version` fehlt.
- Python 3 ist mit den Entwicklerwerkzeugen dabei. Für Kalender und Erinnerungen kommt später eine `.venv` dazu, die Einrichtung sagt, wann.

## Ein Auftrag zum Einfügen

Eine neue Session in Claude Code starten (Ordner egal) und diesen Text einfügen:

```text
Installiere das Paket claude-kits für mich:
1. Lege den Ordner ~/Claude Kits an und klone das Repository des Pakets nach "~/Claude Kits/claude-kits". Die Adresse gebe ich dir, wenn du fragst.
2. Wechsle im Klon auf die neueste Version: git -C "~/Claude Kits/claude-kits" tag --list, dann git -C "~/Claude Kits/claude-kits" checkout -q <höchster Tag>.
3. Führe python3 "~/Claude Kits/claude-kits/plugins/pflege/paket.py" aus (Trockenlauf) und erkläre mir in wenigen Sätzen, was sich ändert.
4. Nach meinem Ja: python3 "~/Claude Kits/claude-kits/plugins/pflege/paket.py" --apply.
5. Sag mir dann, dass ich eine neue Session starten und dort /basis:einrichten aufrufen soll.
Ersetze ~ in allen Befehlen durch meinen Benutzerordner. Nichts senden, nichts löschen.
```

## Danach

- In der neuen Session `/basis:einrichten`. Der Assistent lernt dich im Gespräch kennen und schreibt deine persönlichen Einstellungen. Was nur du tun kannst (Freigaben in macOS, `.venv`), sammelt er am Ende als Liste.
- Updates: über den Marketplace des Pakets in Customize > Plugins mit Sync automatically, sonst neue ZIPs hochladen.
- Probleme oder Wünsche: "Feedback: ..." sagen. Der Assistent sammelt und legt dir bei Gelegenheit einen Mail-Entwurf an den Betreuer vor, ohne Namen oder Inhalte.

## Was wo liegt

| Ordner | Inhalt | Geteilt |
|---|---|---|
| `~/Claude Kits/claude-kits/` | das Paket: Plugins, Skripte, Tests | vom Betreuer, du änderst nichts |
| `~/Library/Application Support/Claude Kits/<plugin>/` | Datenordner je Plugin (`apple`, `chat`, `service`): `config.json` (bei `apple` ein Abschnitt je Bereich: Mail, Kalender, Notizen, Erinnerungen, Kontakte), `style/` (Stilprofile), `.venv`, dazu `.fehler.jsonl` in der Wurzel | nein, nur auf diesem Mac |
| `~/Claude Kits/kontext/` | dein Kontext: CLAUDE.md, Personen, Vorlieben, mit eigenem Git ohne Server | nein, nur auf diesem Mac |
| `~/.claude/settings.json`, `~/.claude/CLAUDE.md` | Rechte und Kopie deiner CLAUDE.md, geschrieben von `paket.py` | nein |
