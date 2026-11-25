# Diagnose: Container gestoppt oder neu gestartet

Leitfaden für Meldungen wie "stopped unexpectedly" von Container Manager, Neustartschleifen und Container, die nachts oder zu festen Zeiten verschwinden. Alles hier läuft lesend über `synology-lesen` oder `synology`.

## 1. Zustand

- `nas_status`: läuft die DiskStation seit dem Ausfall durch (Laufzeit), Volumes über 80 %, Prüfskript aktuell.
- `container_liste`: Status, Exit-Code, OOMKilled, Zahl der Neustarts, Richtlinie, letzter Start und letztes Ende, Labels von Watchtower.

## 2. Exit-Code lesen

| Befund | Bedeutung |
|---|---|
| Exit 137 und OOMKilled | Speichergrenze des Containers oder RAM der DiskStation erreicht, der Kernel hat beendet |
| Exit 137 ohne OOMKilled | fremdes SIGKILL: meist ein Stopp, dessen Stop-Timeout ablief (Docker wartet ohne Angabe nur 10 Sekunden), oder ein Update-Dienst, der hart beendet |
| Exit 143 | SIGTERM durch einen Stopp, sauber angefragt |
| Exit 0 | sauberes Ende, das Programm hat sich selbst beendet |
| Exit 1 oder andere | Fehler im Programm, Log lesen |
| Neustarts steigen bei laufendem Container | Startschleife, Log ab dem ersten Neustart lesen |
| `gestartet` nach dem Ausfall, `erstellt` (in `container_details`) zur selben Zeit | Container wurde neu angelegt, nicht nur neu gestartet, typisch für Watchtower und Compose |

## 3. Zeitfenster

- Fenster: 15 Minuten vor bis 15 Minuten nach dem gemeldeten Zeitpunkt. Meldungen von DSM sind Ortszeit.
- `container_ereignisse` im Fenster: Folge `kill`, `die`, `destroy`, `create`, `start` ist eine Neuanlage. Nur `die` mit Exit 137 ohne `kill` davor deutet auf OOM oder einen Absturz. Docker hält nur 256 Ereignisse und nichts vor dem letzten Start des Docker-Dienstes: Für Ausfälle von vor Tagen ist das meist leer, dann mit Logs weiter.
- `container_log` des betroffenen Containers im Fenster: letzte Zeilen vor dem Ende (SIGTERM, Shutdown, Fehler), erste nach dem Start.
- Gibt es einen Update-Dienst (Watchtower oder ähnlich, siehe `container_liste` und `zuhause.md`): sein `container_log` mit `suche` auf den Containernamen oder `found new`. Zeilen wie "Found new image", "Stopping", "Creating" zur selben Zeit belegen die Erneuerung.
- `nas_log` mit `log` messages und docker im Fenster, dazu `dmesg` für OOM und Plattenfehler.

## 4. Muster über mehrere Tage

- Gleiche Uhrzeit an mehreren Tagen, gleicher Wochentag: Zeitplan. Kandidaten sind ein Update-Dienst (Zeitplan in seinen Umgebungsnamen wie `WATCHTOWER_SCHEDULE` oder seinem Log), `nas_aufgaben` (Aufgabenplaner) und Sicherungen.
- Mehrere Ausfälle kurz nacheinander direkt nach einem Neubau: Startschleife durch Konfiguration, nicht Zeitplan.
- Ausfälle verschiedener Container zu verschiedenen Zeiten, oft nach neuen Images: Update-Dienst mit Prüfintervall statt festem Zeitplan.

## 5. Folgen prüfen

- Bei Home Assistant zusätzlich das Log von Home Assistant über den Server `homeassistant-lesen` (`ha_get_logs`): Neustart, Meldungen des Recorders zu einer nicht sauber geschlossenen Datenbank. Beides spricht für ein hartes Ende.
- `container_details`: `stop_timeout` leer heißt 10 Sekunden. Für Home Assistant sind 120 Sekunden üblich, damit die Datenbank sauber schließt.
- `docker_images` und `nas_speicher`: Viele alte Images füllen das Volume, wenn ein Update-Dienst alte Images nicht aufräumt.

## 6. Bericht

- Ursache in einem Satz, dann die Belege mit Zeitpunkt und Quelle (Werkzeug, Logzeile, Exit-Code).
- Was die Werkzeuge nicht belegen konnten, offen nennen, etwa wenn Ereignisse schon aus dem Puffer sind.
- Vorschläge mit Wirkung und Rückweg, etwa: den Container vom Update-Dienst ausnehmen (Label) oder nur melden lassen, längeren Stop-Timeout setzen, Updates in ein ruhiges Fenster legen, alte Images in Container Manager aufräumen. Nichts davon ohne Ja des Nutzers, und vieles davon ändert der Nutzer in Container Manager oder in seiner Compose-Datei selbst.
