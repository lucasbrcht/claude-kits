# Plugin service

Dienste für Alltag und Unterwegs: das Verpflegungs-Roadbook für Ultra- und Gravel-Events (aus einer GPX oder einem Komoot-Link Stopps im Stundentakt, Öffnungszeiten zur geplanten Durchfahrt aus OpenStreetMap, mit Google Maps gegengeprüft, ein Sticker für den Vorbau als PDF und ein Wallpaper fürs iPhone) und das Smart Home mit Home Assistant.

## Installation

In Cowork: Seitenleiste oben > Plugins (nicht Einstellungen > Plugins) > Add marketplace mit `lucasbrcht/claude-kits` (Sync automatically), dann `service` installieren. In Claude Code:

```
/plugin install service --marketplace lucasbrcht/claude-kits
```

## Aufbau

| Pfad | Inhalt |
|---|---|
| `skills/roadbook/SKILL.md` | Ablauf in Stufen: Eckdaten, Daten und Kandidaten, Auswahl, Prüfliste im Chat, Endfassung |
| `skills/roadbook/scripts/` | `route.py`, `daten.py`, `kandidaten.py`, `namen.py`, `pruefliste.py`, `render.py`, gemeinsam `model.py`, dazu `icons.js` |
| `skills/roadbook/references/` | Google Maps im eingebauten Browser, Dateien und Fallstricke |
| `skills/homeassistant/SKILL.md` | Home Assistant über den MCP-Server `homeassistant`, Adresse und Eigenheiten des Zuhauses stehen im Kontextordner (`zuhause.md`) |
| `ha_start.py`, `.mcp.json` | Starter für die MCP-Server `homeassistant` und `homeassistant-lesen` (mit `--lesen`, Schreiben gesperrt): Adresse aus `config.json`, Token aus dem Schlüsselbund, Vorgaben und erlaubte Schalter, dann ha-mcp per `uvx`. Mit `--rauchtest` Prüfung einer Version |
| `ha_regeln.md` | Hausregeln, die der Starter ha-mcp als eigene Instruktionen mitgibt (`HAMCP_CUSTOM_INSTRUCTIONS`), sie gelten auch ohne geladenen Skill |
| `kit.json` | Steckbrief: Abhängigkeiten (curl, node, pdftoppm, uvx, python3.12 mit numpy, Pillow, reportlab), keine Sperren |
| `tests/test_roadbook.py` | Syntax, Skill und Doku, Öffnungszeiten, Tagesgrenze, Eingaben, die Skripte mit erfundener Strecke im Temp-Ordner |

## Voraussetzungen

- Roadbook: python3.12 von Homebrew mit numpy, Pillow und reportlab, dazu node mit react, react-dom, react-icons und sharp (global, `NODE_PATH` in der `settings.json` unter `env`), für die Sichtprüfung `pdftoppm` (poppler). Für Google Maps der eingebaute Browser der Claude-App, ohne Anmeldung.
- Home Assistant: `uvx`, im Datenordner eine `config.json` mit Block `homeassistant` (Adresse), der Token im Schlüsselbund von macOS, nie im Paket. Was im Code-Tab fragt (Neustart, Löschen), trägt der Nutzer unter `fragen_extra` in `einrichtung.json` ein.

## Aufruf

Die Roadbook-Skripte laufen in der Sandbox aus dem Skill-Ordner, so wie sie im Skill stehen: `python3.12 -P "${CLAUDE_SKILL_DIR}/scripts/<skript>.py" <ordner>/roadbook.json`. Netzabrufe brauchen die im Skill genannten Hosts unter `allowed_domains`.

## Neue Version von ha-mcp

Der Starter nimmt nie `latest`. Ohne `paket` in der `config.json` gilt `PAKET_STANDARD` in `ha_start.py`, die zuletzt geprüfte Version. Vor einem Wechsel im Terminal oder im Code-Tab außerhalb der Sandbox (Schlüsselbund und Heimnetz):

```bash
/Library/Developer/CommandLineTools/usr/bin/python3 "<Plugin-Ordner>/ha_start.py" --rauchtest ha-mcp@<version>
```

Er startet die Version einmal normal und einmal lesend, prüft die Hausregeln in den Instruktionen, die Pflichtwerkzeuge, dass der Lesemodus `ha_call_service` versteckt, und ruft `ha_get_overview` auf. Erst bei "Rauchtest bestanden" `paket` in der `config.json` oder `PAKET_STANDARD` heben, danach beide Server neu verbinden.

## Tests

```bash
python3.12 -B -m unittest discover tests
```

Mit `python3` laufen nur die Tests zu Syntax, Skill und Doku, die anderen brauchen numpy, die zu `render.py` auch Pillow, reportlab und die Schriften von macOS. Die Skripte laufen dabei als eigene Prozesse mit einer erfundenen Strecke im Temp-Ordner, ohne Netz.

## config.json

Persönlich, im Datenordner `~/Library/Application Support/Claude Kits/service/config.json`, nicht im Git und nicht im Plugin. Vorlage ist `config.example.json`. Darin unter `skill_werte.ROADBOOK_VORGABEN` die eigenen Vorgaben fürs Roadbook als Liste von Zeilen, der Skill liest sie beim Start, und der Block `homeassistant` für `ha_start.py`.
