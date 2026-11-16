# Apple Mail: Codes und Sonderfälle

Lesen, wenn `mail_entwurf` oder `mail_senden` einen Code (3, 4, 5) meldet oder eine Sendebestätigung aussteht.

## Entwurf ändern

- Ein angelegter Entwurf ist nicht änderbar. Für eine neue Fassung einen neuen Entwurf anlegen und dem Nutzer sagen, dass er den alten in Mail schließt und verwirft. Verwerfen kann das Plugin nicht.
- `mail_senden` gilt nur für Entwürfe, die das Plugin in diesem Mail-Lauf angelegt hat. Nach einem Neustart von Mail sendet der Nutzer selbst.

## Codes

- **Code 3** (Antwort): Antworten fügen den Text per Bedienungshilfen ins Antwortfenster ein und zählen die Zeichen danach nach. Code 3 heißt: Fenster offen, Text nicht oder zu kurz angekommen. Nicht blind wiederholen: den Nutzer im Fenster nachsehen lassen und den Text zum Kopieren geben. Heißt es "ließ sich nicht nachzählen", ist der Text eingefügt, aber ungeprüft, das dazusagen. Die Bedienungshilfen-Freigabe braucht die App, aus der Claude läuft.
- **Code 4** (neue Mail): Der Entwurf ist leer. Bei neuen Mails immer die Zeichenzahl aus der Meldung prüfen.
- **Code 5**: Mail hat den Absender aus der `config.json` nicht übernommen, der Entwurf ist offen. Dem Nutzer das sagen, er wählt im Fenster bei Von das Konto, bis dahin verweigert `mail_senden`.

## Senden

`mail_senden` prüft nach dem Senden bis 30 s im Postfach Gesendet, das Ergebnis weitergeben. Steht die Bestätigung aus oder hat Mail auf das Senden nicht geantwortet, nie erneut senden, sondern mit `mail_suchen` im Postfach `sent` und dem Betreff prüfen.
