# Vorlagen für den Server synology

Stand: 2026-11-25. Öffentliche MCP-Server und ein Artikel, deren Code gelesen wurde, bevor der Server `synology` entstand. Hier steht je Quelle, was übernommen wurde und was nicht. Code stammt nur aus Projekten mit MIT- oder Apache-Lizenz und trägt dann die Herkunft im Kommentar. GPL, AGPL und Projekte ohne Lizenzdatei liefern nur Ideen.

## Übersicht

| Quelle | Sterne, Lizenz | Gelesen | Kern für uns |
|---|---|---|---|
| [atom2ueki/mcp-server-synology](https://github.com/atom2ueki/mcp-server-synology) | 259, MIT, Python | `src/tool_policy.py`, `src/tool_safety.py`, `src/audit.py`, `src/confirm.py`, `src/container/synology_container.py`, `src/mcp_server.py` (Profile), `skills/synology-nas/references/containers.md` | Profil filtert beim Registrieren, Zaun mit Zufallskennung um fremden Text, Audit vor jeder zerstörenden Aktion, Umgebung nur als Namen |
| [joaomelorodrigues/synology-mcp](https://github.com/joaomelorodrigues/synology-mcp) | 0, MIT, TypeScript | `src/config.ts`, `src/credentials.ts`, `src/dsm/client.ts`, `src/tools/docker.ts`, `src/tools/system.ts` | Stufe read als Vorgabe, Schlüsselbund, abgelehnte Zugangsdaten nie erneut senden, Ergebnis offen nach Zeitablauf |
| [rafalr100/synology-mcp](https://github.com/rafalr100/synology-mcp) | 10, MIT, Python | `synology_mcp/tools/docker.py`, `synology_mcp/tools/dashboard.py`, Liste aller 71 Werkzeuge | Felder der Containerliste, Übersicht in einem Aufruf mit weichem Scheitern je Teil |
| [Mrquj/mcp-server-synology](https://github.com/Mrquj/mcp-server-synology) | 1, MIT nur in `package.json`, keine Lizenzdatei, TypeScript | `src/security.ts`, `src/http.ts` | Lesen als Vorgabe, Löschen und Systemsteuerung je eigener Schalter, Ablehnung nennt den Grund |
| [cmeans/mcp-synology](https://github.com/cmeans/mcp-synology) | 17, Apache-2.0, Python | `core/formatting.py`, `core/redaction.py`, `docs/prompt-injection.md`, `docs/specs/storage-module-spec.md`, `docs/specs/system-module-spec.md` | Zeichen, die eine neue Zeile vortäuschen, aus Antworten entfernen und in Argumenten ablehnen. Speicher-APIs von DSM nur für Admins (alle Versionen 7.1 bis 7.4.1) |
| [tufantunc/ssh-mcp](https://github.com/tufantunc/ssh-mcp) | 905, MIT, TypeScript | `src/policy/classifier.ts`, `src/guard/elicitation.ts`, `src/policy/quota.ts`, `src/config/loader.ts`, `src/cli.ts`, `README.md`, `SECURITY.md` | Klassen lesen, schreiben, verboten, Freigabe scheitert geschlossen, Grenzen 60 s und 1 MB, Konfiguration nur mit 600 |
| [fawdyinc/shellguard](https://github.com/fawdyinc/shellguard) | 29, Apache-2.0, Go | `manifest/manifests/docker_*.yaml`, `dmesg.yaml`, `validator/validator.go`, `validator/attack_vectors_test.go`, `output/output.go` | Positivliste als lesbare Datei, Ablehnung sagt warum, Ausgabe höchstens 64 KB |
| [aspectrr/lily](https://github.com/aspectrr/lily) | 2, keine Lizenz, Go | `internal/readonly/validate_test.go`, `SECURITY.md` | Angriffssammlung als Test, Umgehungen über SSH-Konfiguration und Netz außerhalb des Werkzeugs |
| [Guardian-Artikel auf HackerNoon](https://hackernoon.com/dont-hand-claude-your-docker-socket-build-it-a-guarded-one) | Artikel vom 21.10.2026 | ganz | Felder von `inspect` als Positivliste, Umgebung nur als Namen, Test mit eingepflanztem Passwort, Logs Vorgabe 200 und höchstens 5000 Zeilen, Regeln auf den von Docker aufgelösten Namen, Fehler als Daten, Suche nach auffälligen Zeilen |
| [portainer/portainer-mcp](https://github.com/portainer/portainer-mcp) | 242, MIT, Go | `README.md` | Umgebungswerte standardmäßig geschwärzt. Laut README nicht mehr unterstützt, nicht nutzen |
| [ckreiling/mcp-server-docker](https://github.com/ckreiling/mcp-server-docker) | 762, GPL-3.0, Python | `README.md` | Gegenbeispiel: `remove_container`, `remove_image`, `remove_volume` ohne Schutz. Nur gelesen |

## Je Quelle

### atom2ueki/mcp-server-synology

- **Profile beim Registrieren** (`mcp_server.py`, `_profile_allows`): `read_only` und `no_destructive` nehmen Werkzeuge gar nicht erst in `tools/list` auf, statt sie beim Aufruf abzulehnen. Bei uns: Der Server `synology-lesen` registriert nur Stufe lesen und kennt den Schreibschlüssel nicht.
- **Annotationen Pflicht** (`tool_safety.py`): Ein Werkzeug ohne Klasse lässt sich nicht bauen. Bei uns erzwingt `mcp_basis.Werkzeug` die Stufe, die Annotationen folgen daraus.
- **Zaun um fremden Text** (`tool_safety.fence`): Jede erfolgreiche Antwort steht zwischen `<untrusted-data id="...">` und dem passenden Ende mit einer Zufallskennung je Aufruf, damit Text aus einem Log den Zaun nicht vorzeitig schließt. Übernommen als Muster für Logs und Ereignisse, zusätzlich zu `kit_basis.daten_hinweis`.
- **Audit** (`audit.py`): eine JSON-Zeile je Aufruf, Datei mit 600 und `O_NOFOLLOW`, Schlüssel wie `password`, `token`, `secret` werden geschwärzt. Vor einer zerstörenden Aktion muss eine Absichtszeile geschrieben sein, sonst läuft nichts. Danach nur noch nach bestem Bemühen. Übernommen für die Stufe nachfrage, ohne Argumentwerte außer dem Containernamen.
- **Umgebung nur als Namen** (`synology_container.py`, `_sanitize_details`, `env_keys`): Werte aus `env`, `environment`, `env_variables` fallen weg, die Namen bleiben.
- **Nicht übernommen:** Bestätigung über signierte Token und MCP-Elicitation (`confirm.py`). Das Paket fragt über einen Dialog von macOS, den Claude nicht sieht.

### joaomelorodrigues/synology-mcp

- **Stufen** (`config.ts`): `read`, `write`, `admin`, Vorgabe `read`. Neustart, Ausschalten und DSM-Update brauchen einen eigenen Schalter.
- **Schlüsselbund** (`credentials.ts`): Geheimnisse über `security` im Schlüsselbund, nur ohne Schlüsselbund eine Datei.
- **Kein zweiter Versuch mit abgelehnten Zugangsdaten** (`client.ts`, `refusalError`): Wiederholte Fehlversuche lösen den Auto Block von DSM aus. Bei uns: Meldet `ssh` eine Ablehnung des Schlüssels, versucht der Server es bis zum Neustart nicht erneut.
- **Ergebnis offen nach Zeitablauf** (`client.ts`, `outcomeUnknown`): Läuft eine schreibende Anfrage in die Zeitgrenze, sagt die Meldung, dass die Änderung trotzdem geschehen sein kann, erst lesen, dann erneut versuchen. Lesende Anfragen gelten als wiederholbar.
- **Auswahl der Lesewerkzeuge** (`system.ts`, `docker.ts`): Übersicht, Last, Prozesse, Logs, Hardware, Update-Status, Container, Logs je Container, Images, Projekte.

### rafalr100/synology-mcp

- **Containerliste** (`tools/docker.py`): Name, Image, läuft, Status, Exit-Code, Start, Ende. Bei uns dazu OOMKilled, Neustartzahl, Neustart-Richtlinie und Labels.
- **Übersicht** (`tools/dashboard.py`, `get_overview`): ein Aufruf für alles, ein scheiterndes Teilstück erscheint als leer statt den Aufruf abzubrechen. Übernommen für `nas_status`.
- **Checkliste allgemeines Management:** 71 Werkzeuge, davon für uns lesend relevant: System, Last, Speicher, Platten, Logs, Pakete, Aufgaben, Sicherheit, Container. Nicht übernommen: Benutzer, Freigaben, Dateien, Downloads, Neustart, Ausschalten, DSM-Update, Aufgaben starten.

### Mrquj/mcp-server-synology

- **Richtlinie** (`security.ts`): `readOnly`, `allowDelete`, `allowSystemControl`, `allowGenericApi` je eigener Schalter. Ablehnungen nennen die Aktion und den Schalter.
- **Statusseite** nennt die aktive Richtlinie und die Zahl angebotener Werkzeuge. Bei uns nennt `nas_status` Server, Rolle und Version des Prüfskripts.
- Keine Lizenzdatei: nur Ideen.

### cmeans/mcp-synology

- **Zeichen, die eine Zeile vortäuschen** (`core/formatting.py`, `FORGING_RANGES`): C0 außer Tab, DEL und C1, U+061C, U+200E und U+200F, U+2028 und U+2029, Richtungszeichen U+202A bis U+202E und U+2066 bis U+2069, Tag-Zeichen. `kit_basis.ohne_formatzeichen` deckt fast alles ab, U+2028 und U+2029 nicht: Der Server `synology` entfernt sie zusätzlich.
- **Argumente mit Steuerzeichen ablehnen** (`docs/prompt-injection.md`): Ein Aufruf mit solchen Zeichen läuft nicht. Bei uns lehnen schon das Werkzeug und `eingang.sh` alles außerhalb der erlaubten Zeichen ab.
- **Unbekannte Argumente ablehnen**, Fehlertexte wiederholen keine Werte. Macht `mcp_basis` bereits.
- **DSM-Eigenheiten:** Die Speicher-APIs (`SYNO.Core.Storage.*`) erlauben auf allen Versionen 7.1 bis 7.4.1 nur Admins. Ein Grund mehr für SSH statt Web-API.

### tufantunc/ssh-mcp

- **Klassifizierung** (`classifier.ts`): Statt gefährliche Konstrukte aufzuzählen, lehnt der Klassifizierer jedes Zeichen mit Bedeutung für die Shell ab (`;&|<>` Backtick, `$(){}`, Zeilenumbrüche), dazu Platzhalter wie `*`. Bei uns gibt es keine Shell auf dem Text: `eingang.sh` lässt nur `[A-Za-z0-9._:/=-]` zu.
- **Freigabe scheitert geschlossen** (`elicitation.ts`): Jeder Fehler beim Fragen gilt als Nein und wird von einer echten Ablehnung unterschieden. Ihre Wartezeit ist 10 Minuten, das Paket bleibt bei 120 Sekunden.
- **Grenzen** (`cli.ts`): 60 Sekunden je Befehl, 1 MB Ausgabe, Tagesquote je Profil (Vorgabe aus).
- **Konfiguration nur mit 600** (`loader.ts`): sonst Abbruch mit dem Befehl zum Reparieren.
- **Eigene Aussage im README:** Prompt-Injection hat keine allgemeine Lösung, deshalb gilt jeder Befehl als möglicherweise fremd gesteuert. Dazu der Rat, nie auf ein Root-Konto zu zeigen. Bei uns läuft nur `gate.sh` als root, mit festem argv je Verb, der Benutzer `claude` bekommt keine Shell.
- **Nicht übernommen:** Host-Schlüssel per TOFU als Vorgabe. Wir pinnen bei der Einrichtung.

### fawdyinc/shellguard

- **Manifeste** (`manifest/manifests/*.yaml`): je Befehl eine Datei mit erlaubten Schaltern. Bei uns ist die Positivliste der `case` in `gate.sh`, lesbar an einer Stelle.
- **Gegenbeispiel `docker_inspect.yaml`:** erlaubt `--format` frei. Eine Vorlage wie `{{.Config.Env}}` gäbe Geheimnisse heraus. Bei uns steht die Vorlage fest in `gate.sh`.
- **Hilfreiche Ablehnung** (`validator.go`): sagt, was nicht geht und warum.
- **Ausgabe** (`output/output.go`): Vorgabe 64 KB.
- **Angriffssammlung** (`validator/attack_vectors_test.go`, 146 Fälle): ergänzt die aus lily.

### aspectrr/lily

- **Angriffszeichenketten** (`validate_test.go`): Umleitungen `>` `>>` `<` `<<<`, Pipes, `$()` und Backticks auch in doppelten Anführungszeichen, Prozessersetzung `<()`, Zeilenumbrüche `\n` und `\r\n`, Unterschalen, `awk system`, `find -exec`, `sed w`. Die Tests von `eingang.sh` und `gate.sh` nehmen diese Muster als eigene Liste auf, dazu `..`, `VAR=wert` vor dem Befehl, Schalter mit `-` vorn, leere Eingabe, zu lange Eingabe.
- **Bekannte Umgehungen** (`SECURITY.md`): Wer `~/.ssh/config` schreiben kann, setzt `ProxyCommand` oder einen anderen Host. Wer Netz hat, ruft `ssh` am Werkzeug vorbei. Bei uns: `ssh -F /dev/null` mit festen Optionen, Schlüssel und `known_hosts` im gesperrten Datenordner, und die Grenze liegt ohnehin auf der DiskStation.
- Keine Lizenz: nur Ideen.

### Guardian-Artikel auf HackerNoon

- **Name prüfen, nicht die Eingabe:** Docker nimmt auch IDs und Präfixe von IDs. Eine Regel auf den Namen greift nur nach der Auflösung durch Docker. Bei uns nimmt `gate.sh` nur Namen aus der aktuellen Liste der Container, keine IDs.
- **`inspect` als Positivliste der Felder:** Neue Felder einer späteren Docker-Version erscheinen so nie ungeprüft.
- **Eingepflanztes Geheimnis im Test:** Der Test legt ein Passwort in die Umgebung eines erfundenen Containers und prüft, dass es in keiner Ausgabe auftaucht.
- **Logs:** Vorgabe 200 Zeilen, höchstens 5000, Rückgabe gekürzt, ungültiges UTF-8 wird ersetzt statt abzustürzen. Suche nach auffälligen Zeilen (`error`, `fatal`, `panic`, `oom`, `killed`, `timed out`) mit Wortgrenzen, Ergebnis als Zählung.
- **Fehler als Daten:** Jede Ablehnung ist ein Ergebnis mit Code und Grund, der Server läuft weiter.
- **Zeitgrenze** für jeden Aufruf an Docker, sonst hängt ein Aufruf bei einem blockierten Dienst.

### portainer/portainer-mcp und ckreiling/mcp-server-docker

- portainer schwärzt Umgebungswerte standardmäßig, wird aber laut README nicht mehr unterstützt.
- ckreiling bietet Löschen von Containern, Images, Netzen und Volumes ohne Schutz an. GPL-3.0: nichts übernommen.

## Gemeinsame Lehre

- Positivliste statt Verbotsliste, die Grenze dort, wo der Agent sie nicht ändern kann (bei uns auf der DiskStation).
- Werkzeuge außerhalb der Stufe gar nicht anbieten.
- Ausgaben begrenzen, Geheimnisse schwärzen, fremden Text als Daten kennzeichnen.
- Ablehnungen sagen warum, der Server bleibt am Leben.

## Grenzen von Docker selbst

- `docker events` hält nur die letzten 256 Ereignisse im Speicher (moby, `daemon/events/events.go`, `eventsLimit`), nach einem Neustart des Docker-Dienstes ist der Puffer leer. Ältere Ausfälle belegen nur Logs: Container-Logs, Log eines Update-Dienstes wie Watchtower, Systemlog von DSM.
- `docker inspect` zeigt nur den letzten Start und das letzte Ende eines Containers.

## DSM-Eigenheiten

Wird in Phase 3 am echten Gerät ergänzt: Pfad von `docker`, OpenSSH-Version und `restrict`, `visudo`, `timeout`, Gerätenamen für `smartctl`, Befehle für Aufgaben, Pakete und Updates, Ort des Docker-Logs, was ein DSM-Update übersteht.
