# Neue Folien

Gilt für jede neue Folie und jedes neue Deck, auch für einen OnePager.

## Weg

1. **Vorbild klären, vor dem Bauen.** Im Kontext des Nutzers nachsehen, ob es für die Vorlage Musterfolien oder Vorbilddecks gibt. Fehlt das, mit den Rückfragen zum Inhalt eine Frage nach einer Vorbildfolie stellen. Eine leere Mastervorlage zeigt den Stil nicht (Karten, Schatten, Icons).
2. **Mit Vorbild:** `arbeitskopie` mit `aktion` anlegen, `pfad` die Mastervorlage oder das Vorbilddeck, `datei` der neue Name. Dann `folien_aendern` mit `uebernehmen` für die Musterfolien, Text mit `text` und `absaetze`, nicht passende Folien mit `loeschen`. So bleiben Formen, Schatten, Icons und echte Aufzählungen der Vorlage.
3. **Ohne Vorbild baut der pptx-Skill** im Themen-Ordner. Danach sofort `arbeitskopie` mit `aktion` anlegen (ohne `pfad`), das setzt die Sprache, prüft und merkt den Stand. Ab dann jede Runde mit `folien_aendern`, nie neu bauen.
4. **Prüfen:** Die WARNUNG-Zeilen von `folien_pruefen` (nach `anlegen` und nach jeder Runde von `folien_aendern` dabei) beheben: `in_form` für Textfelder auf Formen, `absaetze` mit `punkt` für getippte Zeichen, größere Schrift. Danach Vorschau wie im Ablauf des Skills.

## Regeln für den Bau

Gelten auch für eigenen Code mit python-pptx.

- **Text in die Form**, die ihn trägt (Karte, Kasten, Pfeil), nicht als Textfeld darüber. In python-pptx `shape.text_frame` der Form füllen, kein `add_textbox` auf eine Form. Sonst trennt jedes Verschieben Text und Form. Der Weg über HTML im pptx-Skill legt Textfelder über Formen, für Folien in einer Firmenvorlage darum python-pptx oder Musterfolien.
- **Aufzählungen als Absatzformat** (`buChar` mit hängendem Einzug), nie Zeichen wie • oder - in den Text tippen. Ein Absatz ein Lauf, kein eigener Lauf mit anderem Format für das Zeichen. Sonst rutscht die zweite Zeile unter das Zeichen und Fett mischt sich beim Markieren.
- **Schriftgrößen:** Folien, die gezeigt werden (All-Hands, Beamer), Fließtext ab 14 pt, Überschriften größer, lieber weniger Text. 9 bis 10 pt nur für Quellen und Fußnoten. Wichtiges (nächste Schritte, Fazit) nicht klein und unten verstecken.
- **Platzhalter des Layouts nutzen** (Titel, Inhalt), statt eigene Textfelder an ihre Stelle zu legen.
- **Stil der Vorlage übernehmen:** Schatten, Ecken, Farben und Icons wie in den Musterfolien, nicht abschalten oder frei wählen.
- **Zähler und Sprache** macht `anlegen` und jede Runde von `folien_aendern`, nicht selbst im Code.
