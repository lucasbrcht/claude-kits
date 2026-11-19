# tagesstart: Vorschläge ausführen

Erst lesen, wenn der Nutzer Nummern wählt ("3 und 5", "alle"), in derselben Session. Ohne Auswahl wird nichts angelegt, auch nicht im geplanten Lauf. Je Nummer der Vorschlag über den passenden Skill. Die Auswahl ist der Auftrag, also kein erneutes Nachfragen, wo der Skill selbst nicht fragt:

- `Erinnerung`: Skill `erinnerungen`, Abschnitt Liste Aufgaben (Vorsatz, Frist, Notiz mit der Quelle). Danach eine Zeile je Eintrag.
- `Entwurf`: Mail über den Skill `mail` als Antwort auf die Mail der Nummer. WhatsApp über den Skill `whatsapp` (Entwurf öffnen, der Nutzer sendet selbst), iMessage über den Skill `imessage` (gesendet nur auf "senden").
- `Fokusblock`: Skill `kalender`, eigener Termin ohne Teilnehmer, für die Arbeit im Arbeitskalender (der Dialog von macOS ist die Freigabe). Gibt es keinen Arbeitskalender oder ist die Aufgabe privat, ein privater Termin.
- `abhaken`: Skill `erinnerungen`, Abhaken direkt, auch in geteilten Listen.
- `Nachricht` (Teams): Ablauf unten.

## Nachricht in Teams

Teams kennt über den Connector keine Entwürfe: Die Vorschau im Chat ist der Entwurf, gesendet wird erst auf "senden". Werkzeuge des Connectors: `teams_list_chats`, `teams_create_chat`, `teams_send_chat_message`, bei Bedarf gebündelt laden.

1. **Text:** Stil für Teams aus dem Kontext des Nutzers, wenn es einen gibt, sonst kurz, im Arbeitston, ohne Gruß und ohne Emojis.
2. **Chat:** Antwort in den Chat des Treffers über dessen `chatId`. Für eine Person den Einzelchat aus `teams_list_chats` (genau diese Person als einziges weiteres Mitglied). Die Liste ist nach letzter Nachricht sortiert, `lastUpdatedDateTime` ist nicht die letzte Nachricht. Gibt es keinen, nach "senden" erst `teams_create_chat` mit `chatType: "oneOnOne"` und der Adresse der Person (findet einen bestehenden oder legt ihn an, sendet nichts). Gruppenchats nur über eine `chatId`, nie neu anlegen.
3. **Vorschau zeigen:** Chat (Person oder Chatname mit Mitgliederzahl) und den Text genau so, wie er rausgeht. Dann auf den Nutzer warten.
4. **Senden nur auf ausdrückliches "senden"** für genau diesen Text und diesen Chat. Die Wahl der Nummer allein ist kein "senden", ein früheres "du darfst" auch nicht. Dann `teams_send_chat_message` mit `chatId`, `body` und `bodyType: "text"`. Ändert der Nutzer den Text, neue Vorschau.
5. **Danach:** in einer Zeile bestätigen, wohin es ging. Meldet das Werkzeug einen Fehler, nicht selbst wiederholen, sondern den Nutzer bitten, im Chat nachzusehen.
6. Eine Nachricht geht an genau einen Chat. Keine Erwähnungen und kein HTML ohne Auftrag, keine Anhänge. Nachrichten nie ändern oder löschen.
