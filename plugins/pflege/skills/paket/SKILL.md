---
name: paket
description: Das Paket claude-kits im Code-Tab pflegen mit paket.py, Einstellungen und CLAUDE.md der Instanz neu schreiben, vor einem Release prüfen und ZIPs bauen. Nicht für das erste Kennenlernen (Skill einrichten) und den Kontext selbst (Skill kontext).
---

# paket

> **Plugin-Ordner: `${CLAUDE_PLUGIN_ROOT}`.** Befehle wie unten: absoluter Pfad, je ein eigener Befehl ohne `cd`, Pipe oder Umleitung.

Der Alltag läuft in Cowork über die Werkzeuge der Plugins. `paket.py` gehört zur Pflege im Code-Tab: Es lädt die Plugins aus dem Paketordner, schreibt die `CLAUDE.md` der Instanz aus `profil.md` und Index des Kontextordners, wenige Rechte für die Pflege und die Sperren der Apple-Datenordner in die `settings.json`. Der Paketordner ist die Ablage von claude-kits mit `einrichtung.json` und `.claude-plugin/marketplace.json`, standardmäßig `~/Claude Kits/claude-kits`.

## Bausteine

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/paket.py"                      # Trockenlauf, ändert nichts
python3 "${CLAUDE_PLUGIN_ROOT}/paket.py" --apply              # schreibt settings.json und CLAUDE.md
python3 "${CLAUDE_PLUGIN_ROOT}/paket.py" --pruefen            # Skills, gleiche Dateien, Sicherheit, Doku, Persönliches
python3 "${CLAUDE_PLUGIN_ROOT}/paket.py" --zips "<Ordner>"    # ZIP je Plugin aus dem letzten Commit
python3 "${CLAUDE_PLUGIN_ROOT}/paket.py" --instructions       # Text für Instructions for Claude nach einrichtung/
```

`--pruefen` vergleicht `kit_basis.py` und `mcp_basis.py` samt Tests in `apple` und `chat` und in den Plugins der eigenen Marketplaces aus `eigene_plugins` der Einrichtung (etwa `arbeit` im work-kit). Kann diese Instanz einen eigenen Marketplace nicht lesen, steht dort eine INFO: Den Vergleich macht dann die Instanz, die ihn lesen darf.

Dazu prüft `--pruefen`:
- **`SICHERHEIT.md`** im Hauptordner: FEHLER, wenn die Datei fehlt oder ein Werkzeug der Stufe nachfrage aus `apple` oder `chat` dort nicht in Backticks steht. Neues Werkzeug mit Dialog: eine Zeile mit Gefahr, Gegenmaßnahme und Stelle ergänzen, `Stand` auf heute.
- **Doku-Tests** `tests/test_doku.py` von `apple` und `chat` als eigener Lauf: Jedes Werkzeug aus `WERKZEUGE` in `server.py` steht in genau einer Tabelle `| Werkzeug | Zweck | Stufe |` eines Skills im Paket, mit der Stufe aus dem Server (nachfrage heißt dort `fragt`). Fehlt der Test oder schlägt er fehl, ein FEHLER mit dem Grund. Neues Werkzeug: Zeile in der Tabelle des passenden Skills.

## Einstellungen oder CLAUDE.md neu schreiben

Nach einer Änderung an `einrichtung.json`, an `profil.md` oder am Index im Kontextordner:
1. Trockenlauf ausführen und die Änderungen in wenigen Zeilen zusammenfassen.
2. `--apply` läuft im Terminal, der Auto-Modus lässt es aus der Session nicht zu: den Befehl ausgeschrieben nennen.
3. Sagen: Plugins und `CLAUDE.md` gelten ab der nächsten Session, die Rechte sofort.

Meldet der Trockenlauf eine eigene `CLAUDE.md` des Nutzers, nichts überschreiben: den Inhalt mit ihm in `profil.md` übernehmen, er benennt die alte Datei selbst um.

## Release

1. Tests je geänderten Plugin, dann `--pruefen`: FEHLER zuerst nennen, WARNUNG danach, je mit Datei. Funde zu persönlichen Daten zeigen nie den Fund selbst, nur Datei und Zeile: die Stelle lesen und neutral umschreiben.
   Ändert sich die Version von ha-mcp (`PAKET_STANDARD` in `service/ha_start.py` oder `paket` in der `config.json` von service), vorher der Rauchtest außerhalb der Sandbox: `/Library/Developer/CommandLineTools/usr/bin/python3 "${CLAUDE_PLUGIN_ROOT}/../service/ha_start.py" --rauchtest ha-mcp@<version>`. Nur bei "Rauchtest bestanden" weiter, sonst die Fehlerzeile nennen und die alte Version lassen.
2. Version in `.claude-plugin/plugin.json` jedes geänderten Plugins erhöhen, `CHANGELOG.md` ergänzen, committen.
3. Ausgerollt wird über GitHub: Tag `v<Paketversion>` auf den Commit, dann Push von `main` und Tag nach `origin`. Push nur nach Ja des Nutzers. Ein Marketplace mit Sync automatically holt die neue Version nach dem Push selbst.
4. ZIPs mit `--zips` nur auf Wunsch, für hochgeladene Plugins (Einstellungen > Plugins gegen das neue ZIP tauschen). Ein ZIP gleicher Version bleibt liegen, meldet das Skript nicht committete Änderungen, erst committen.
