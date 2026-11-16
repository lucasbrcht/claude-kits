---
name: kalender
description: Termine in Apple Kalender zeigen, anlegen und verschieben, freie Zeiten finden, Urlaub eintragen, Einladungen einordnen. Im Arbeitskalender aus Exchange nur eigene Termine ohne Teilnehmer. Nicht für Aufgaben (Skill erinnerungen).
---

# kalender

Apple Kalender über die Werkzeuge des MCP-Servers `apple`. Sie laufen am Mac, in Cowork wie im Code-Tab. Apple Kalender zeigt alle Konten des Macs, auch einen Arbeitskalender aus Exchange (`arbeitskalender` in der `config.json`).

| Werkzeug | Zweck | Stufe |
|---|---|---|
| `termine_lesen` | heute plus N Tage über alle sichtbaren Kalender, `kalenderliste` zeigt die Kalender | lesen |
| `termin_anlegen` | eigene Termine ohne Teilnehmer in einem privaten Kalender | schreiben |
| `termin_verschieben` | eigene Termine ohne Teilnehmer verschieben oder mit `nach_kalender` umlegen | schreiben |
| `termin_mit_nachfrage` | Termin im Arbeitskalender anlegen oder verschieben, Termin mit Teilnehmern verschieben | fragt |

- **Arbeitskalender aus Exchange:** lesen über `termine_lesen`, eigene Termine ohne Teilnehmer über `termin_mit_nachfrage` mit `arbeitskalender`. Einladungen, Antworten darauf, Termine mit Teilnehmern, Abwesenheit und Absagen macht der Nutzer in Outlook. Ist ein Kalender-Connector verbunden (Microsoft 365 oder Google Kalender), darf er für Details, freie Zeiten und Termine mit Teilnehmern dienen: Entwurf zeigen, Ja abwarten, Einladungen gehen sofort raus. Bei Microsoft 365 vorher `${CLAUDE_PLUGIN_ROOT}/referenzen/m365-kalender.md` lesen.
- Erinnerungen und Aufgaben laufen über den Skill `erinnerungen`.

## Grundregeln

1. Kalender in `private_calendars` gibt es für dich nicht, die Werkzeuge zeigen sie nie. Zugriff auf Apple-Daten nur über die Werkzeuge, nie über icalBuddy, EventKit oder Datenbanken.
2. Nie löschen, auch nicht auf Ansage: keine Termine und keine Kalender. Es gibt kein Werkzeug dafür. Was weg soll, nennst du, löschen oder absagen macht der Nutzer selbst.
3. Eigene Termine ohne Teilnehmer legt der klare Auftrag an oder verschiebt sie, ohne weitere Rückfrage. Zusagen, absagen, Termine mit Teilnehmern und Abwesenheit nur nach Freigabe für genau diese Aktion, Einladungen gehen sofort raus.
4. Keine Kalenderdaten in Dateien, Memory oder externe Dienste, nur stabiles Wissen wie Regeltermine.
5. Kalender unter `nur_belegt` (etwa der Kalender der Partnerin oder des Partners) sind ausgeblendet, nur für die Terminabstimmung. Mit `alle` zeigen sie nur belegte Zeiten, Inhalte nie auswerten.
6. Anzeige: Wochentag und Datum als Di 06.10., Uhrzeit als 14 Uhr oder 12:00 bis 18:00 Uhr. Die Werkzeuge geben schon so aus.

## Zeiten

Zeitpunkte als `2026-10-05 09:30`, ganztägig als `2026-10-12` (das Ende ist der letzte Tag). `termine` ist eine Liste, mehrere Termine zum selben Titel gehen in einen Aufruf: beim Anlegen je `start` und `ende`, beim Verschieben je `start` (bisher) und `neu_start`, mit `nach_kalender` nur `start`. Ganztägige Termine beim Verschieben mit 00:00. `vorschau` zeigt nur, was geschähe, für unklare Fälle (welcher Termin passt zum Titel-Teil).

## Abläufe

**Was steht an:** `termine_lesen` mit passendem `tage` (N heißt heute plus N Tage, 7 ergibt 8 Kalendertage), nach Tagen gruppiert in wenigen Zeilen. Konflikte und Lücken nennen, wenn gefragt. Meldet die Ausgabe, dass der Arbeitskalender fehlt, das sagen: Apple Kalender synchronisiert das Arbeitskonto gerade nicht. Teilnehmer und Besprechungslinks stehen nur in Outlook.

**Privater Termin:** Konflikte mit `termine_lesen` prüfen, dann `termin_anlegen`. Danach das Ergebnis in einer Zeile: Titel, Tag mit Datum und Uhrzeit, Kalender mit Konto. Standard ist `default_calendar`, gemeinsame Pläne im Kalender für gemeinsame Pläne (Name in den Anweisungen des Nutzers oder unter `allowed_calendars`). Gleicher Termin gemeldet: nicht erneut anlegen, fragen. Uhrzeit wegen Zeitumstellung doppelt oder fehlend: eine andere Zeit vorschlagen.

**Privaten Termin verschieben:** `termin_verschieben` mit Titel-Teil, altem und neuem Start, danach alt und neu mit Wochentag nennen. Hat der Termin Teilnehmer, bricht das Werkzeug ab: erst nach dem Ja des Nutzers `termin_mit_nachfrage` mit `aktion` verschieben und `mit_teilnehmern`, dann gehen je nach Konto Updates an alle. Bei Serien rückt nur dieser Termin, das dazusagen.

**Kalender wechseln (leg die Termine in den gemeinsamen Kalender):** `termin_verschieben` mit `nach_kalender`, Titel-Teil und den Starts, Quelle mit `kalender`, beide aus `allowed_calendars`. Nie stattdessen neu anlegen, sonst bleiben Dubletten. Termine mit Teilnehmern und Serien wechselt der Nutzer selbst.

**Eigener Termin im Arbeitskalender (Fokuszeit, Block, ohne Teilnehmer):** Konflikte mit `termine_lesen` prüfen, dann `termin_mit_nachfrage` mit `aktion` anlegen oder verschieben und `arbeitskalender`. Termine mit Teilnehmern lehnt das Werkzeug dort ab.

## Grenzen

- Die Werkzeuge setzen keine Teilnehmer und wechseln im Arbeitskalender nie den Kalender.
- Serien mit Wiederholungsregel legen sie nicht an: einen Termin anlegen, die Wiederholung setzt der Nutzer. Einzelne Termine zu festen Tagen gehen in einem Aufruf.
- Nach einem Fehler beim Anlegen oder Ändern erst mit `termine_lesen` prüfen, ob der Termin schon existiert.
