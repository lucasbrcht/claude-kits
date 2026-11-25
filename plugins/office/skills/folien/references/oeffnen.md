# Datei lässt sich nicht öffnen

Meldet PowerPoint "found a problem with content" oder "couldn't repair the file", prüft `folien_pruefen` in dieser Reihenfolge: Zip lesbar, XML wohlgeformt, Inhaltstypen, alle Verweise in allen Teilen samt leerer (`r:id=""` dort, wo PowerPoint ein Ziel braucht), eingebettete Schriften, zuletzt XSD. Die FEHLER-Zeilen nennen Teil und Element.

- `[trash]/` im Paket legt PowerPoint für Mac selbst an, ohne Inhaltstyp. Das ist normal und nie die Ursache.
- **Eingebettete Schriften fehlen:** PowerPoint sollte Schriften einbetten, die das nicht erlauben (oft Firmenschriften), und schrieb leere Verweise. Auf Wunsch `folien_aendern` mit `{"aenderungen": [{"art": "reparieren"}]}`, das entfernt die leeren Einträge, die Liste und `embedTrueTypeFonts`. Den Nutzer bitten, in PowerPoint für dieses Deck Schriftarten in die Datei einbetten auszuschalten (Einstellungen > Speichern), sonst kommt der Fehler beim nächsten Speichern zurück.
- **Verweis ohne Beziehung oder Beziehung auf ein fehlendes Teil:** stammt meist aus einer Kopie zwischen Decks. Die Folie mit `uebernehmen` neu aus der Quelle holen statt sie zu reparieren, sonst den Nutzer fragen.
- Behoben wird nur in der Arbeitskopie, nie am Original. Danach `folien_pruefen` und `office_vorschau`, dann übertragen nach dem Skill `dateien`.
- Nach dem Übertragen den Nutzer bitten, das Deck in PowerPoint zu öffnen. Die Vorschau mit LibreOffice öffnet auch Dateien, an denen PowerPoint scheitert, sie beweist nichts.
- Ohne XSD-Prüfung meldet `folien_pruefen` das als INFO oder WARNUNG mit dem Befehl, der fehlt: den Befehl dem Nutzer für das Terminal geben.
