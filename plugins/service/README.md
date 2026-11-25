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
| `skills/synology/SKILL.md` | DiskStation über die MCP-Server `synology` und `synology-lesen`, Leitfaden zur Diagnose und die Vorlagen in `references/` |
| `synology_server.py`, `synology_regeln.md` | MCP-Server für die DiskStation (mit `--lesen` nur Lesewerkzeuge, ohne Schreibschlüssel). Ruft über `/usr/bin/ssh` mit festen Optionen das Prüfskript auf, Hausregeln als Instruktionen |
| `synology_start.py` | Einrichtung (`--einrichten`) und Prüfung (`--pruefen`) im Terminal |
| `synology/nas/` | Prüfskript für die DiskStation: `eingang.sh` (erzwungener Befehl), `gate.sh` (Positivliste, als root über sudo), `install.sh`, `VERSION` |
| `mcp_basis.py`, `kit_basis.py` | Unterbau, gleich in apple, chat, office und service |
| `kit.json` | Steckbrief: Abhängigkeiten (curl, node, pdftoppm, uvx, ssh, python3.12 mit numpy, Pillow, reportlab), Sperre des Ordners `ssh/` im Datenordner für Read und Edit |
| `tests/` | Roadbook, Starter für Home Assistant, Server und Prüfskript der DiskStation (mit falschen Programmen in einer erfundenen Welt), Unterbau und Doku |

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

## DiskStation einrichten

Der Server spricht per SSH mit einem eigenen Benutzer `claude`, dessen Schlüssel auf der DiskStation nur das Prüfskript erreichen. Lesen und Schreiben haben getrennte Schlüssel. Einmal je DiskStation:

1. In DSM: Benutzer `claude` anlegen (Gruppe administrators, sonst erlaubt DSM kein SSH), Zugriff auf Apps und Ordner verweigern, starkes Passwort, das nur der Nutzer kennt. Unter Benutzer > Erweitert den Benutzer-Home-Dienst aktivieren. Unter Terminal SSH aktivieren, in der Firewall nur aus dem Heimnetz.
2. Im Terminal am Mac, außerhalb der Sandbox: `/Library/Developer/CommandLineTools/usr/bin/python3 "<Plugin-Ordner>/synology_start.py" --einrichten`. Fragt Adresse, Port, eigenes Admin-Konto und Heimnetz, erzeugt die Schlüssel mit Passphrase im Schlüsselbund, pinnt den Host-Schlüssel und zeigt zwei Befehle.
3. Die zwei Befehle im Terminal ausführen: Der erste kopiert den Ordner `claude-gate-neu` ins eigene Home auf der DiskStation, der zweite startet `install.sh` mit sudo (fragt das eigene Passwort).
4. `synology_start.py --pruefen`, danach in der Claude-App die Server `synology` und `synology-lesen` neu verbinden.

Nach einem DSM-Update meldet `nas_status`, wenn sudoers oder das Prüfskript fehlen. Dann Schritt 2 und 3 wiederholen, vorhandene Schlüssel bleiben. Rückbau steht im Kopf von `install.sh`.

## Tests

```bash
python3.12 -B -m unittest discover tests
```

Mit `python3` laufen nur die Tests zu Syntax, Skill und Doku, die anderen brauchen numpy, die zu `render.py` auch Pillow, reportlab und die Schriften von macOS. Die Skripte laufen dabei als eigene Prozesse mit einer erfundenen Strecke im Temp-Ordner, ohne Netz.

## config.json

Persönlich, im Datenordner `~/Library/Application Support/Claude Kits/service/config.json`, nicht im Git und nicht im Plugin. Vorlage ist `config.example.json`. Darin unter `skill_werte.ROADBOOK_VORGABEN` die eigenen Vorgaben fürs Roadbook als Liste von Zeilen, der Skill liest sie beim Start, und der Block `homeassistant` für `ha_start.py`.
