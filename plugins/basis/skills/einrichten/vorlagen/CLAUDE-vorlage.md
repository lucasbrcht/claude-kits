# Projekt <Bereich>: Kontext-Index

Mein Wissen für den <Bereich>-Alltag liegt in `wissen/`. Vor Aufgaben mit Personen oder eigenen Texten die passende Datei lesen, sonst bei Bedarf, nie raten. Person, Schreibregeln und feste Regeln stehen in den Instructions for Claude (Quelle `profil.md`), hier steht, wo was liegt.

| Thema | Datei oder Werkzeug |
|---|---|
| Profil, Interessen, Vorlieben, Bereiche und Projekte | `wissen/privat-profil.md` |
| Familie und Freunde, Kanal je Person | `wissen/privat-personen.md` |
| Kolleginnen, Kunden, Rolle je Person | `wissen/arbeit-personen.md` |
| Stil für Texte in meinem Namen | Werkzeuge `mail_stilprofil` und `chat_stilprofil` |
| Adresse, Telefon, Mail, Geburtstag einer Person | Werkzeug `kontakte`, live zeigen, nie merken |
| Kontext pflegen, Fragen aus dem Abgleich beantworten | Skill `/basis:kontext` |

## Bereiche und Kanäle

- Mail, Kalender, Erinnerungen, WhatsApp, iMessage und Notizen laufen über ihre Skills und deren Werkzeuge. Apple-Apps nie per `osascript` oder Skript direkt.
- "Was hat X geschrieben": im Kanal der Person zuerst (Kanal in der Personendatei), dann Mail.

## Pflege von `wissen/`

- `wissen/` ist die gepflegte Basis. Neues aus dem Alltag landet in Memory. Die Dateien hier ändern nur auf meinen ausdrücklichen Auftrag oder mit `/basis:kontext`. Der monatliche Abgleich legt Fragen in `wissen/_interview.md` ab.
- Format: Zeile 2 ist `Stand: JJJJ-MM-TT · Vertraulichkeit: neutral|intern|privat · Pflege: N Tage`. Neue Datei: Zeile im Index oben. Arbeitslisten mit `_` davor stehen nicht im Index.
- Nie hierher: Zugangsdaten, Kontonummern, Ausweisdaten, Telefonnummern, Adressen, Inhalte fremder Mails und Chats.

<!-- Vorlage des Skills einrichten für die CLAUDE.md im Kontextordner (lädt in Cowork aus dem Projektordner): Zeilen ohne passende Datei streichen (ohne Arbeitskonto arbeit-personen.md, ohne Plugin chat chat_stilprofil), <Bereich> ersetzen, keine absoluten Pfade, keine nur-code-Blöcke. Diesen Kommentar beim Schreiben entfernen. -->
