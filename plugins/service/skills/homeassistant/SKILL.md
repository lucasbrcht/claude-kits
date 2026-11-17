---
name: homeassistant
description: Home Assistant zu Hause lesen, steuern und einrichten über den MCP-Server homeassistant: Licht, Heizung, Szenen, Automationen, Dashboards, Anwesenheit. Nicht für Apple Home.
argument-hint: [Auftrag]
effort: medium
---

# homeassistant

Home Assistant des Nutzers über ha-mcp aus diesem Plugin, in Cowork und im Code-Tab gleich. Fakten zum Zuhause stehen in `zuhause.md` im Kontextordner (in Cowork der Projektordner, sonst der Ordner, den der Kontext-Index der `CLAUDE.md` nennt): Adresse des Servers, Config-Ordner, Räume, Namensschema, wie der Nutzer mitarbeiten will. Vor Umbauten lesen und danach richten. Aufruf `/service:homeassistant $ARGUMENTS`.

## Zwei Server

| Server | Wofür |
|---|---|
| `homeassistant` | Lesen, Schalten, Einrichten |
| `homeassistant-lesen` | Nur lesen, Schreiben sperrt der Server selbst: für geplante Aufgaben, Routinen, Analysen und Audits |

- Werkzeuge laden je nach Oberfläche verzögert: dann gebündelt in einem Aufruf mit `ToolSearch` (`ha_get_skill_guide`, `ha_get_overview`, `ha_search`, `ha_get_state`, `ha_call_service`), weitere mit `+homeassistant <Stichwort>`. Für den Lesemodus `+homeassistant-lesen`.
- Die Hausregeln (Rückfragen, Schlösser, Löschen, Token) schickt der Server in seinen Instruktionen mit, sie gelten immer. Hier steht nur, was darüber hinausgeht.
- Hat ein Server keine Werkzeuge, nennen seine Instruktionen den Grund (keine Konfiguration, kein uvx, kein Token). Den Grund in einem Satz sagen, nicht über Bash oder `curl` ausweichen. Einrichtung: Block `homeassistant` in der `config.json` von service (Vorlage `config.example.json`), Token im Schlüsselbund unter dem dort genannten Dienst, beim ersten Start Immer erlauben.
- Fehler beim Verbinden: Mac nicht im Heimnetz oder VPN, Token abgelaufen, erster Start einer neuen Version von ha-mcp dauert länger.

## Arbeitsweise

- Vor dem ersten Umbau einer Session `ha_get_skill_guide` lesen und die Referenzdatei, auf die er für die Aufgabe zeigt. Die allgemeinen Best Practices (entity_id statt device_id, Modus der Automation, Helfer statt Templates) stehen dort, nicht hier.
- Aktuelles immer live lesen (`ha_get_overview`, `ha_search`, `ha_get_state`), nie aus dem Gedächtnis.
- Namen nach dem Schema in `zuhause.md`. Fehlt dort eines, das Schema der vorhandenen Geräte und Entitäten übernehmen.
- Automationen mit sprechender `alias` und `description`, Auslöser mit `id`. Abwesenheit, Zeiten und Zonen über `person.*` und `zone.home`, nicht über einzelne Geräte.
- Kleine Korrekturen an Namen oder Räumen ohne Vorschau, wenn der Nutzer sie genau so nennt.
- Meldet `ha_get_overview` eine neuere Version von ha-mcp: einmal nennen. Die Version wechselt erst nach dem Rauchtest im Code-Tab (Skill `/pflege:paket`, beim Betreuer), nicht in der Session.

## Rückweg

Zwei Wege, je nachdem, wie geändert wurde:

- **Über die Werkzeuge** (Automation, Skript, Szene, Helfer, Entität, Dashboard): ha-mcp legt vor jeder Änderung selbst ein Backup an, lokal am Mac. `ha_manage_backup` mit scope `edits` listet sie je Objekt, zeigt den Diff zum aktuellen Stand und stellt wieder her. Wiederherstellen nur nach Ja, vorher den Diff zeigen. Das ist auch der Rückweg in Cowork, wo der Git-Commit fehlt.
- **YAML-Dateien im Config-Ordner:** über Git, siehe unten.

## Versionierung mit Git

Gilt nur, wenn `zuhause.md` einen Config-Ordner nennt, der als lokales Git-Repo eingerichtet ist (ohne Remote, nie Push, Laufzeitdaten und Zugangsdaten in `.gitignore`). `<config>` ist dieser Ordner.

- Nach jeder Änderung durch Claude committen: `git -C <config> add -A` und `git -C <config> commit -m "<Was, kurz>"`. Läuft nur im Code-Tab außerhalb der Sandbox. In Cowork erreicht Bash das Netzlaufwerk nicht: Änderung über die Werkzeuge machen und sagen, dass der Commit beim nächsten Mal im Code-Tab fehlt. Das Backup von ha-mcp gibt es trotzdem.
- Vor dem Commit `git -C <config> status --short` lesen. Taucht eine Datei mit Zugangsdaten auf (`secrets.yaml`, `.storage/auth*`, `core.config_entries`), nicht committen, sondern melden.
- Ist der Ordner nicht erreichbar (Netzlaufwerk nicht eingebunden): Änderung trotzdem machen, aber sagen, dass der Commit fehlt.
- Zurückdrehen nur auf Ja: das Diff zeigen, dann `git -C <config> revert <commit>` und in Home Assistant die betroffenen Teile neu laden (`ha_reload_core`).
- YAML-Dateien im Ordner nur mit Edit oder Write ändern, danach `ha_reload_core`. Bevorzugt aber über die Werkzeuge von ha-mcp, sie prüfen die Konfiguration und legen das Backup an.

## Abschluss

- Kurz sagen, was sich geändert hat, und den Commit nennen, wenn es einen gibt.
- Dauerhafte Fakten zum Zuhause (neuer Raum, neues Gerät mit Rolle, eine Vorliebe für Licht oder Heizung) still in Memory, nicht in `zuhause.md`. Der monatliche Abgleich fragt, ob sie in die Datei sollen.
