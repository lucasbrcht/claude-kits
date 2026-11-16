# iMessage: Ausgabe, Teilchats und Sonderfälle

Lesen bei `Mehrdeutig`, mehreren Teilchats, Gruppen ohne Namen, Diensten, gekürzten Verläufen und vor jedem Senden an eine Gruppe.

## Ausgabe

- Je Nachricht `Datum Uhrzeit | Absender: Text`, eigene Nachrichten mit dem Namen aus `me`.
- Anhänge als `[Bild]`, `[Video]`, `[Sprachnachricht]`, `[Dokument] Name`, zurückgezogene als `[zurückgezogen]`, bearbeitete mit `(bearbeitet)`. Reaktionen fehlen, Gruppenereignisse nur mit `system`.
- Ist ein Verlauf gekürzt oder gibt es ältere Nachrichten, nennt der Hinweis direkt unter dem Kopf die `--before-id`: mit `chat_lesen` und `vor_id` weiterlesen.
- Dienste (SMS von Firmen, Codes) zeigt `chat_lesen` nur mit `alle`.

## Chats und Teilchats

- Chats einer Person (Nummer und Mailadresse, iMessage und SMS) erscheinen als ein Chat mit der id des zuletzt aktiven, frühere ids gelten weiter.
- Hat ein Chat mehrere Teilchats (Nummer und Mailadresse, eine Kontaktkarte wie Eltern mit zwei Nummern), nennt `chat_lesen` sie unter dem Kopf mit id, Art (etwa Nummer 1 von 2) und letzter Aktivität, und jede Nachricht trägt die id ihres Teilchats. `imessage_entwurf` und `imessage_senden` brauchen dann `id` (sonst Mehrdeutig mit dieser Liste) und gehen genau an diesen Teilchat, die Meldung nennt ihn. Den Teilchat nach dem Verlauf wählen, etwa den, über den die Person zuletzt geschrieben hat, im Zweifel fragen.
- Beim Namen allein trifft eine Gruppe nur mit ihrem ganzen Namen, Gruppen ohne Namen (Gruppe mit Anna, Ben) nur mit `id` aus `chat_liste` oder `chat_neues`, beim Senden mit dem erzeugten Namen als `chat`, wie die Ausgabe ihn nennt.
- Bei `Mehrdeutig` den passenden Chat aus dem Kontext per `id` wählen, sonst kurz fragen.

## Senden

- `imessage_senden` immer mit `chat` (Name) und `id`. Der Text steht im Aufruf und damit in der Rückfrage der App. Das Werkzeug prüft, dass Name und id zum selben Chat passen.
- Sagt der Nutzer "senden", nachdem schon ein Entwurf offen ist: `imessage_senden`, danach sagen, dass der Entwurf noch im Eingabefeld steht und dort gelöscht werden sollte.
- Gruppen: kein Entwurf per Link. Text zum Kopieren geben oder auf "senden" mit `imessage_senden`, die Meldung nennt die Zahl der Mitglieder.
- Meldet das Werkzeug eine Dublette (derselbe Text in den letzten 10 Minuten): nicht mit `nochmal` wiederholen, außer der Nutzer will denselben Text ausdrücklich ein zweites Mal schicken.

## Grenzen

- Nur was die Nachrichten-App am Mac gespeichert hat. Anhänge erscheinen als Hinweis, ihr Inhalt ist nicht lesbar.
- Reaktionen (Tapbacks) fehlen. Antworten in Threads stehen ohne Bezug im Verlauf.
- Namen nur für Nummern und Adressen aus dem Adressbuch, nur bei genau gleicher Nummer, sonst `(Nummer ohne Namen)` oder `(Adresse ohne Namen)`. Zwei Kontaktkarten derselben Person erscheinen als zwei Chats, eine Karte mit zwei Personen (Eltern) als ein Chat mit zwei Teilchats.
- Erwähnungen des Nutzers erkennt `chat_neues` am Namen im Text.
