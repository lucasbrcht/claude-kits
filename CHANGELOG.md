# Änderungen

Je Version, was sich für Nutzer ändert. Behobene Rückmeldungen mit der Nummer des Issues.

## v8.2.0 (25.11.2026)

`office` 8.1.0, `basis` 8.1.1 (Befehl für den Motor), die anderen Plugins bleiben. Zwei Befunde aus dem Alltag mit Decks und Mappen.

- **Eigene Änderungen bleiben erhalten (office):** Ändert der Nutzer die Arbeitskopie zwischen zwei Runden selbst (Füllfarbe, Formate, Bänderung, Text), meldet die nächste Runde von `excel_skript` und `folien_aendern` das als VON HAND und überschreibt es nicht. Würde der Code eine solche Stelle ändern, schreibt das Werkzeug nichts (HALT), `ueberschreiben` nur nach Ja des Nutzers. Jede Runde nennt die geänderten Bereiche für die Übergabe. Excel stoppt auch, wenn openpyxl beim Speichern Inhalte verlieren würde (Bilder, Makros, bedingte Formatierung neuerer Art). Liest der Code nur, bleibt die Datei unberührt.
- **folien_aendern arbeitet auf dem aktuellen Stand (office):** Die Liste enthält nur noch die neuen Wünsche, Foliennummern wie `folien_lesen` sie jetzt zeigt. Bis 8.0 spielte jeder Lauf die ganze Liste erneut auf das Original ab, eine Liste mit nur neuen Wünschen hätte frühere Runden verworfen. Rücknahme der letzten Runde jetzt mit `arbeitskopie` und `aktion` zuruecknehmen.
- **folien_pruefen findet, woran PowerPoint scheitert (office):** Verweise ohne Beziehung in allen Teilen (auch Layouts und Master), Beziehungen auf fehlende Teile, Teile ohne Inhaltstyp, kaputte Zip- oder XML-Teile ohne Absturz. Eigener Fund für eingebettete Schriften ohne Datei (PowerPoint: "found a problem with content", die XSD-Prüfung merkt es nicht), Behebung mit der neuen Art `reparieren` in `folien_aendern`. `[trash]/` von PowerPoint für Mac zählt nie. Skill `folien` mit Abschnitt "Datei lässt sich nicht öffnen".
- **XSD-Prüfung ohne Einstellung (office):** Ist `motor.pptx_validate` leer, sucht der Server `validate.py` des Skills pptx, den Cowork am Mac ablegt. Dafür braucht die `.venv` `defusedxml`, fehlt es, nennt die Prüfung den Befehl.
- **Skills `dateien`, `excel`, `folien`:** Jede Runde beginnt mit dem aktuellen Stand der Arbeitskopie, Änderungen des Nutzers gelten, nur der neue Auftrag wird umgesetzt, frühere Skripte nie erneut abspielen, die Übergabe nennt die geänderten Bereiche.
- **Update:** Claude einmal mit Cmd+Q beenden und neu öffnen, für laufende Arbeit an Decks einen neuen Chat beginnen. Einstellungen bleiben. Schickt ein alter Chat die frühere Liste mit verschieben, backup, loeschen oder uebernehmen erneut, hält die erste Runde einmal an, statt andere Folien zu treffen. `defusedxml` ist optional, ohne fehlt nur die XSD-Prüfung, `folien_pruefen` nennt dann den Befehl.

## v8.1.0 (23.11.2026)

`apple` 8.1.0, `basis` 8.1.0, `chat` 7.0.3 (Hinweise in den Skills), `pflege` 7.1.3 (Hinweis zu ZIPs), `office` und `service` bleiben. Befunde aus einer Einrichtung bei einer neuen Nutzerin.

- **Festplattenvollzugriff einfacher (apple):** `einstellungen` mit `freigabe` öffnet die Systemeinstellungen bei Festplattenvollzugriff und daneben ein Finder-Fenster mit `python3.9` markiert. Man zieht es nur noch in die Liste. Der Knopf **+** graut `python3.9` aus, deshalb führen Einrichtung, Fehlermeldungen von Kontakte und die Skills für WhatsApp und iMessage jetzt diesen Weg. `INSTALL.md` Schritt 2 öffnet beide Fenster mit einem Befehl im Terminal.
- **Plugins über die Seitenleiste:** Installieren, prüfen und entfernen immer über **Plugins** in der Seitenleiste ganz oben über den Chats, nie über Einstellungen > Plugins (in der aktuellen App unzuverlässig). Fehlt ein Plugin in der Liste, findet es das Suchfeld. Gilt in `INSTALL.md`, den READMEs und der Einrichtung.
- **Einrichtung fragt nach vorhandenen Projekten (basis):** Der Haltepunkt vor der ersten Suche bittet neben dem Modell um einen Screenshot der Seitenleiste oder die Namen der Projekte. Der Projektschnitt geht davon aus: vorhandene behalten und ergänzen, neue nur für Bereiche ohne Projekt, Spalte Stand in der Empfehlung. Die Liste steht unter `Vorhanden:` in `wissen/privat-profil.md`.
- **Texte zum Kopieren gut sichtbar (basis):** Instructions for Claude und alles je Projekt (Name, Beschreibung, Instruktionen) stehen immer direkt im Chat, je Ziel mit Überschrift und Wo, je Text ein eigener Codeblock, in einer Nachricht am Ende der Runde. Die Datei in `einrichtung/` ist nur die Sicherung.

## v8.0.2 (19.11.2026)

`pflege` 7.1.2, die anderen Plugins bleiben wie in 8.0.1. Nur für den Betreuer im Code-Tab.

- **Vorlage `einrichtung.example.json`:** nennt `office` in der Liste der Plugins.
- **Skill `paket` (pflege):** `--pruefen` vergleicht die gleichen Dateien, `SICHERHEIT.md` und die Doku-Tests auch für `office`. Der Hinweis auf das zurückgebaute Plugin `arbeit` entfällt.
- **Für den Betreuer:** Docstrings von `kit_basis.py` und `mcp_basis.py` und Hinweise in `paket.py` ohne das Plugin `arbeit`, Testdaten in `pflege` neutral.

## v8.0.1 (19.11.2026)

`basis` 8.0.1, die anderen Plugins bleiben wie in 8.0.0.

- **Dokumente einrichten (basis):** Die Einrichtung prüft jetzt erst mit `folien_finden`, ob der Motor schon läuft, und bietet ihn nur an, wenn er fehlt. Die Befehle für das Terminal stehen direkt im Skill, Cowork konnte `INSTALL.md` nicht lesen.

## v8.0.0 (19.11.2026)

`office` 8.0.0 (neu), `apple` 8.0.0, `basis` 8.0.0, `chat` 7.0.2 (Beschreibungen der Skills), `pflege` 7.1.1 (`paket.py` kennt `office`), `service` bleibt 7.1.0.

Ein Thema, ein Plugin: Alles rund um Dokumente liegt jetzt im neuen Plugin `office`. `basis` ist der Kern mit Einrichtung, Kontext, Tagesstart und Feedback, `apple` bleibt bei den Apple-Apps.

Für bestehende Nutzer:

- **Plugin `office` installieren:** Customize > Plugins, `office` aus dem Marketplace `claude-kits`, danach Claude mit Cmd+Q neu starten. Ohne `office` gibt es keine Arbeitskopien mehr, `apple` hat die Werkzeuge abgegeben.
- **`/basis:dateien` heißt jetzt `/office:dateien`.** Eigene Abläufe, geplante Aufgaben und Instructions, die den alten Namen nennen, anpassen.
- **Umzug läuft von selbst:** Beim ersten Start übernimmt `office` den Abschnitt `ablage` aus der `config.json` von `apple`, dazu die Herkunft der Arbeitskopien und die Sicherungen. Laufende Themen in `Claude Personal` und `Claude Work` gehen weiter, nichts wird gelöscht.
- **Neu `/basis:tagesstart`:** Überblick zum Start des Tages oder der Woche. Eine geplante Aufgabe Tagesstart mit freiem Text kann auf `/basis:tagesstart` umgestellt werden (montags `/basis:tagesstart Wochenstart`). Bereiche, Arbeitsadresse für Teams und wiederkehrende Fristen stehen am besten als Abschnitt Tagesstart in den Instructions (Vorlage `profil.md` in `einrichten`), ohne ihn nimmt der Skill einen Standard.
- **Motor für PowerPoint und Excel (nach Wunsch):** Abschnitt Motor für Office in `INSTALL.md` im Terminal, oder `/basis:einrichten` mit "Dokumente einrichten".

Neu:

- **Plugin `office` (Grundstufe):** `arbeitskopie` (holen, liste, zeigen) und `arbeitskopie_uebertragen` mit Dialog am Mac wie bisher, dazu das Werkzeug `sprache` (prüfen oder setzen für .pptx und .docx). Es ersetzt das Skript `sprache.py` und läuft so auch in Cowork am Mac. Nur in der Ablage, keine Verweise.
- **Motor für PowerPoint und Excel (office):** `folien_finden`, `folien_lesen`, `folien_pruefen` (lesen), `folien_aendern`, `excel_skript`, `excel_fertig`, `office_vorschau` (schreiben). Bestehende Decks finden (Suchordner aus `suche.ordner`), lesen, mit einer Änderungsliste ändern, auf PowerPoint-Fallen prüfen, Mappen per Skript ändern und mit LibreOffice nachrechnen, Vorschau als PDF und Bild. Geändert wird nur die Arbeitskopie im Thema, ohne Rahmen und ohne Vorsatz im Namen, ein Vergleich liegt auf Wunsch daneben.
- **Skills `folien` und `excel` (office):** Regeln für bestehende Decks und Mappen. Ablage und Rückweg stehen im Skill `dateien`. Regeln von Kunden oder Arbeitgebern gehören in den Kontextordner.
- **Skill `tagesstart` (basis):** Termine, Mail, WhatsApp, iMessage, Erinnerungen und, wenn verbunden, Outlook, Teams und Gmail in einem Überblick fürs Handy, mit nummerierten Vorschlägen. Ausgeführt wird erst nach Wahl der Nummern, gesendet nur auf "senden". Varianten Tagesstart, Wochenstart und was gibt's Neues. Was nicht installiert ist, fällt still weg.
- **Einrichtung (basis):** fragt nach Dokumenten, schreibt `ablage`, `suche` und `motor` in die `config.json` von `office` und bietet den Motor an. Neuer Abschnitt Tagesstart in der Vorlage `profil.md` (Bereiche, Arbeitsadresse, Fristen), Stil für Teams unter Texte in meinem Namen. Die geplante Aufgabe Tagesstart startet `/basis:tagesstart`.

Sicherer:

- **Motor in der Sandbox (office):** Jedes Skript des Motors und jeder Code für Excel läuft unter `sandbox-exec` ohne Netz, schreibt nur in Ablage, Zwischenordner und Temp und liest weder die Datenordner von Mail, Nachrichten, Kalender, Notizen, Erinnerungen, Kontakten, WhatsApp und der anderen Plugins noch den Schlüsselbund oder Ordner aus `motor.gesperrt`. LibreOffice und pdftoppm ebenso, Eingaben nur aus der Ablage.

Entfallen:

- **`apple`:** `arbeitskopie`, `arbeitskopie_uebertragen` und `ablage.py` (jetzt in `office`), der Abschnitt `ablage` der `config.json` von `apple` wird nicht mehr gelesen. `arbeitskopie zeigen` öffnet nur noch Dateien aus der Ablage, nicht mehr aus `pdf.ordner`.
- **`basis`:** Skill `dateien` und `sprache.py` (jetzt in `office`).

Für den Betreuer:

- **Sechs Plugins:** `marketplace.json`, `paket.py` (`GLEICHE_PLUGINS`, `SERVER_PLUGINS`), `CLAUDE.md`, README, `INSTALL.md` und neue README von `office`. `kit_basis.py`, `mcp_basis.py` und `test_doku.py` liegen gleich in `apple`, `chat` und `office`.
- **Tests:** `office` mit `python3`, dem Python der Command Line Tools und `python3.12` (Folien-Tests mit python-pptx und lxml). Obergrenze der Werkzeuge in `apple` und `chat` von 36 auf 34, `office` hat eine eigene Grenze von 10. `basis` testet die Skills, `apple` die Einstellungen für `office`.
- **`SICHERHEIT.md`:** Zeilen der Arbeitskopien unter `office`, neu `sprache` außerhalb der Ablage und Code im Motor.

## v7.3.1 (19.11.2026)

`apple` 7.2.1, die anderen Plugins bleiben wie in 7.3.0.

Ein Patch statt Warten auf das nächste Release: Der Hinweis soll schon vor dem ersten Übertragen in einen geteilten Ordner da sein.

- **Hinweis auf geteilte Ordner beim Übertragen (apple):** Liegt das Original unter `Library/CloudStorage` oder in einem OneDrive-Ordner, zeigt der Dialog vor `arbeitskopie_uebertragen` die Zeile `Achtung: Shared Folder`. Andere sehen die Änderung dort sofort.

## v7.3.0 (18.11.2026)

`apple` 7.2.0, `basis` 7.1.0, `pflege` 7.1.0, `chat` 7.0.1 (nur Werkzeugtabellen in den Skills), `service` bleibt 7.1.0.

Für bestehende Nutzer einmal nötig:

- **Abschnitt `ablage` in der `config.json` von `apple`:** Ohne ihn bricht `arbeitskopie` ab. Nachtragen mit `einstellungen_schreiben` (Vorlage in `config.example.json`: `Claude Personal` und `Claude Work` im Downloads-Ordner) oder `/basis:einrichten` fortsetzen.
- **Zeile zum Ablage-Ort in den Instructions:** Die Vorlage `profil.md` hat eine neue Regel (nie am Original arbeiten, Arbeitskopie je Thema). Bestehende Instructions bekommen sie von Hand.
- **`notiz_ersetzen` verlangt jetzt `stand`** aus `notiz_lesen`, ebenso `notiz_ergaenzen` und `notiz_geteilt` beim Ändern. Ohne passenden Stand ändert sich nichts.
- **`mail_entwurf` mit `betreff_erwartet`:** Der Skill `mail` setzt ihn bei jeder Antwort. Eigene Abläufe mit `antwort_auf` sollten ihn mitgeben.
- **In Cowork einmal Immer erlauben:** Fragt Cowork beim ersten Aufruf eines Werkzeugs der Stufe schreiben (etwa `pdf_aus_html`, `arbeitskopie`, `notiz_ergaenzen`), dort Immer erlauben wählen. Was andere sehen, fragt weiter der Dialog am Mac.

Neu:

- **Arbeitskopien von Dokumenten (basis, apple):** neuer Skill `dateien` für Office-Dateien und andere Dokumente, privat und für die Arbeit. Das Original bleibt unberührt, die Arbeitskopie liegt je Thema in `Claude Personal/<Thema>/` oder `Claude Work/<Thema>/` im Downloads-Ordner. Zurück ins Original erst auf "übertragen". Werkzeuge `arbeitskopie` (schreiben: `holen`, `liste`, `zeigen`) und `arbeitskopie_uebertragen` (nachfrage, Dialog am Mac), Skript `ablage.py`. Übertragen schreibt in dieselbe Datei, Links und Versionsverlauf in SharePoint bleiben. Es bricht ab, wenn das Original seit dem Holen geändert wurde oder in Office offen ist, und hebt den alten Stand im Datenordner auf. Pfade aus der VM von Cowork findet es am Mac über den Ordnernamen.
- **Sprache von Folien (basis):** `dateien/scripts/sprache.py` setzt `lang` an allen Textstellen einer .pptx oder .docx auf die Sprache des Dokuments, Pflichtschritt vor jeder Übergabe. Läuft in der Sandbox von Cowork.
- **Erinnerungen ändern (apple):** neues Werkzeug `erinnerung_aendern` (schreiben). Frist verschieben oder entfernen, Titel, Notiz, Liste und Priorität ändern, versehentlich Abgehaktes wieder öffnen, alles in einem Aufruf. Der Wecker zur alten Uhrzeit rückt mit, andere bleiben.
- **Erinnerungen suchen und priorisieren (apple):** `erinnerungen_lesen` mit `text` sucht in Titel und Notiz aller Listen, offen und erledigt, `erledigt` zeigt Geschafftes. `erinnerung_anlegen` setzt `prioritaet`, die Ausgabe zeigt `!!!`, `!!`, `!` wie die App, Heutiges mit Priorität steht vorn.
- **Notizen ergänzen (apple):** neues Werkzeug `notiz_ergaenzen` (schreiben) setzt Text unten oder direkt unter dem Titel an, der Rest bleibt. In geteilten Ordnern über `notiz_geteilt` mit `ergaenzen` und Dialog.
- **PDF ohne Dialog (apple):** Ein PDF, das `pdf_aus_html` selbst gedruckt hat (Kennung im Feld Creator), ersetzt der nächste Druck ohne Rückfrage. Nur ein fremdes PDF gleichen Namens fragt mit `ersetzen` per Dialog.

Sicherer:

- **Stand-Schutz für Notizen (apple):** `notiz_lesen` zeigt `Stand` mit Sekunden und Anhänge. Ersetzen und Ergänzen ändern nichts, wenn die Notiz seitdem geändert wurde, etwa am iPhone. Geprüft wird direkt vor dem Schreiben noch einmal.
- **Kein Verlust beim Ändern von Notizen (apple):** Mit Anhängen lehnen Ersetzen und Ergänzen ab, Notes würde sie verlieren. Fehlt in der neuen Fassung ein Link der alten, lehnt `notiz_ersetzen` ab, außer mit `links_entfernen`.
- **Antwort nur auf die erwartete Mail (apple):** `mail_entwurf` mit `antwort_auf` und `betreff_erwartet` vergleicht den Betreff vor der Antwort, ohne Re:, AW:, WG:, Fwd:, Groß und Klein. Passt er nicht, öffnet sich nichts, die Meldung nennt beide Betreffs.
- **Nachkontrolle (apple):** Nach Anlegen, Ersetzen und Ergänzen von Notizen, nach `erinnerung_aendern` und nach `termin_anlegen`, `termin_verschieben` und `termin_mit_nachfrage` lesen die Skripte frisch zurück und nennen Abweichungen.
- **Nicht durchsucht ist nicht leer (apple):** Ein Konto aus `accounts`, das Mail nicht findet, fiel bisher still weg. Jetzt nennen `mail_neues`, `mail_suchen` und die Stilprobe es als nicht durchsucht. `erinnerungen_lesen` meldet, wenn keine Liste lesbar ist. `notizen_suchen` mit `ordner` sagt ohne Treffer, ob der Ordner leer, unbekannt oder ausgeschlossen ist.

Schneller:

- **Notizsuche (apple):** `notizen_suchen` und die Titelsuche holen je Ordner alle Notizen in einem Zug, gemessen gut fünfmal schneller. Neueste zuerst, `ordner` grenzt auch die Suche mit `text` ein. Nach 60 Sekunden hört die Suche auf und sagt es. Nicht Lesbares überspringt sie mit Hinweis, ohne `ordner` nennt sie die durchsuchten Konten.

Für den Betreuer:

- **`SICHERHEIT.md`:** neue Übersicht im Hauptordner mit Gefahr, Auslöser, Folge, Gegenmaßnahme und ob Code oder Skill sie erzwingt, dazu ein Abschnitt, was nur im Skill steht.
- **Werkzeugtabellen und Doku-Test (apple, chat):** Alle Skills zeigen ihre Werkzeuge als Tabelle mit Zweck und Stufe. `tests/test_doku.py` prüft, dass jedes Werkzeug in genau einer Tabelle steht. `paket.py --pruefen` (pflege) lässt die Doku-Tests mitlaufen und meldet einen FEHLER, wenn `SICHERHEIT.md` fehlt oder ein Werkzeug der Stufe nachfrage dort fehlt.
- **Obergrenze der Werkzeuge** aller Server von 32 auf 36 (`test_server.py` in `apple` und `chat`), jetzt ausgeschöpft.
- **Einrichtung (basis, apple):** `einstellungen` nennt den Downloads-Ordner (iCloud Drive, sonst `~/Downloads`), `einrichten` nimmt ihn für `pdf.ordner` und `ablage` und fragt, ob Arbeitsdokumente in iCloud Drive liegen dürfen. `cowork.md` empfiehlt Immer erlauben für Werkzeuge des Pakets.
- **Tests:** `basis` hat jetzt `tests/`. Ein Test kompiliert alle AppleScripts von `notiz.py`, auch in der Sandbox.

## v7.2.0 (17.11.2026)

`service` 7.1.0, `pflege` 7.0.1 (Rauchtest im Release-Check, Ausrollen per GitHub, ZIPs nur auf Wunsch), die anderen Plugins bleiben wie in 7.1.1.

- **Hausregeln in den Instruktionen von ha-mcp:** Der Starter gibt `ha_regeln.md` als `HAMCP_CUSTOM_INSTRUCTIONS` mit. Rückfragen, Schlösser, Löschen und Token gelten damit auch, wenn Claude die Werkzeuge ohne den Skill nutzt.
- **Zweiter Server `homeassistant-lesen`:** derselbe Starter mit `--lesen`, ha-mcp sperrt dort jedes Schreiben (`READ_ONLY_MODE`). Für geplante Aufgaben, Routinen und Analysen.
- **Vorgaben und Schalter:** keine Settings-Seite von ha-mcp mehr, die nach der Session im Hintergrund weiterläuft (eine laufende beendet der nächste Start), Passwörter in Optionen von Apps und Integrationen geschwärzt. Unter `homeassistant.optionen` in der `config.json` lassen sich erlaubte Schalter setzen, unbekannte sind ein Fehler.
- **Feste Version:** ohne `paket` gilt ha-mcp 9.2.0 statt `latest`, `paket` muss eine Version wie `ha-mcp@9.2.0` nennen.
- **Rauchtest:** `ha_start.py --rauchtest ha-mcp@<version>` prüft eine neue Version normal und lesend, bevor sie in die `config.json` kommt.
- **Skill `homeassistant` schlanker:** allgemeine Best Practices kommen aus `ha_get_skill_guide`, Namen nach dem Schema in `zuhause.md`. Neu der Abschnitt Rückweg mit den automatischen Backups von ha-mcp (`ha_manage_backup`, scope `edits`), auch in Cowork ohne Git.

## v7.1.1 (16.11.2026)

`basis` 7.0.3, die anderen Plugins bleiben wie in 7.1.0.

- **Memory merkt Grund und Datum:** Die Vorlage für das Profil sagt, dass Memory den Grund einer Vorliebe mit merkt und Zeitangaben als Datum statt relativ. Gilt für neue Einrichtungen, bestehende Profile bekommen die Zeile von Hand.
- **Abgleich meldet unscharfe Memory-Einträge:** Einträge mit relativer Zeitangabe oder abgelaufenem Datum stehen im Abschluss als Aufgabe "in Memory korrigieren", ohne Frage.

## v7.1.0 (16.11.2026)

`apple` 7.1.0, `basis` 7.0.2, die anderen Plugins bleiben 7.0.0.

- **Neues Werkzeug `pdf_aus_html` in `apple`:** druckt eine HTML-Datei als PDF neben die Quelle, nur mit Bordmitteln von macOS (WebKit über `html2pdf.swift`). A4 hoch oder mit `quer` quer, ohne Ränder, mit Hintergründen und den Schriften des Mac, ohne Chrome, Klick oder Dialog. `name` setzt den Dateinamen. Rückgabe Pfad und Seitenzahl als Prüfung auf Überlauf. Stufe schreiben, ein vorhandenes PDF ersetzt es nur mit `ersetzen` nach dem Dialog am Mac. Läuft nur, wo die Plugins am Mac laden (Cowork, Code-Tab), nicht in Cloud-Sitzungen und am iPhone.
- **Neuer Abschnitt `pdf` in der `config.json`** mit `ordner`: Nur darunter druckt das Werkzeug. Ohne den Abschnitt bricht es ab, nachtragen mit `einstellungen_schreiben` (Vorlage: Downloads im iCloud Drive). `einrichten` schreibt ihn bei neuen Einrichtungen mit.
- Beim ersten Aufruf übersetzt `pdf.py` das Swift-Programm einmal nach `bin/` im Datenordner (etwa 40 Sekunden, braucht `swiftc` der Command Line Tools).
- Vorlagen mit Seiten von genau 297 mm bekommen keine leeren Zwischenseiten: WebKit rundet die Seitenhöhe ab, das Programm druckt deshalb auf minimal höheres Papier und schneidet auf A4 zu.

## v7.0.3 (16.11.2026)

Nur Doku, die Plugins bleiben wie in 7.0.2.

- **`INSTALL.md` mit Start-Prompt:** Claude führt im Code-Tab durch die Schritte 1 bis 5, führt die Befehle selbst aus und sagt an, was nur der Nutzer klicken kann (Homebrew mit Passwort, Festplattenvollzugriff, Plugins und Projekt im Konto). Die Einrichtung startet weiter in Cowork.
- Schritt 5 sagt, dass bei Arbeit und Privat gemischt erst nur das Projekt Privat entsteht und `einrichten` die weiteren Projekte empfiehlt.

## v7.0.2 (16.11.2026)

`basis` 7.0.1, die anderen Plugins bleiben 7.0.0.

- **`einrichten` passt zu `INSTALL.md`:** Der Text Freigaben nennt `python3.9` als Eintrag für Automation, Kalender und Erinnerungen, Bedienungshilfen nur bei Bedarf und den Weg bei `EventKit fehlt` oder `icalBuddy fehlt`. Punkt 7 der Prüfliste verweist auf Schritt 1 von `INSTALL.md` statt auf den Befehl aus der Meldung.

## v7.0.1 (16.11.2026)

Nur Doku, die Plugins bleiben 7.0.0.

- **`INSTALL.md` neu für Cowork:** Zusatzprogramme im Terminal (Entwicklerwerkzeuge, Homebrew, icalBuddy, `.venv` mit EventKit), Festplattenvollzugriff für `python3.9`, Marketplace mit Sync automatically, welche Plugins, Mail-Connector, Projekt Privat mit Kontextordner, dann `/basis:einrichten`. Der Weg über Klon und `paket.py` steht nur noch kurz für den Betreuer am Ende.

## v7.0.0 (16.11.2026)

Alle Plugins auf 7.0.0. Fünf Plugins nach Zielgruppe statt nach App: `basis`, `apple`, `chat`, `service`, `pflege`.

Teil d, öffentlicher Marketplace (16.11.2026):

- **Ein Marketplace auf GitHub** für alle Accounts: `lucasbrcht/claude-kits`, öffentlich, beginnt mit diesem Stand. In Cowork über Customize > Plugins > Add marketplace mit Sync automatically, neue Versionen kommen dann ohne ZIP. Installationszeilen in den READMEs.
- `marketplace.json` ohne Mailadresse. Der Skill `feedback` legt den Entwurf dann ohne Empfänger an und sagt das.

Teil b, Plugins nach Zielgruppe (16.11.2026):

- **`apple` übernimmt `mail`.** Mail, Kalender, Notizen, Erinnerungen und Kontakte laufen über einen Server. Die Werkzeuge heißen gleich, ihr Präfix wechselt von `mcp__plugin_mail_mail__` auf `mcp__plugin_apple_apple__` (Aufgabentexte und Rechte prüfen). Das Plugin `mail` entfällt: im Account entfernen, `apple` neu installieren.
- **Eine `config.json` für `apple`** mit Abschnitten `mail`, `kalender`, `notizen`, `reminders` und `kontakte` in `~/Library/Application Support/Claude Kits/apple/`. Umzug: die bisherige `mail/config.json` aufteilen (Konten, Profile, Anhänge, Suche, Triage nach `mail`, die Kalenderfelder nach `kalender`), `mail/style/` nach `apple/style/`. Eine `.venv` statt zwei.
- **`basis` nur noch für Nutzer:** `einrichten`, `kontext`, `feedback`. `umzug` entfällt. `einrichten` läuft jetzt auch in Cowork: Haltepunkt für das Modell vor der ersten Recherche, Einstellungen und Stilprofile über Werkzeuge statt Bash, Personen nur bei Vorkommen über mindestens zwei Monate und ins Wissen des Projekts, vorhandene Instructions ergänzen statt ersetzen, Projektschnitt, Text für Instructions for Claude, Rechte der Connectoren in Alltagssprache, geplante Aufgaben als eigener Schritt, nummerierte Proben mit Ort, Eingabe und Erwartung. Vorlagen `profil.md` (Quelle der Instructions) und `CLAUDE-vorlage.md` (Index des Projekts).
- **Neues Plugin `pflege`** nur für den Betreuer im Code-Tab: `paket.py`, Skills `paket` und `rueckmeldungen`, Output-Style (jetzt `pflege:Assistent`). `--pruefen` vergleicht `kit_basis.py` und `mcp_basis.py` in `apple`, `chat` und über `eigene_plugins` der Einrichtung im Plugin `arbeit`. `--instructions` schreibt nach `einrichtung/instructions.md`.
- **Neue Werkzeuge in `apple`:** `einstellungen` (lesen) und `einstellungen_schreiben` (Dialog am Mac) für `config.json` und Stilprofile von `apple`, `chat` und `service`. `mail_stilprofil` und `chat_stilprofil` holen mit `stilprobe` eine neue Stichprobe. So erreicht Claude den Datenordner auch in Cowork, auch `roadbook` für seine Vorgaben.

Nachtrag aus der Arbeits-Instanz (16.11.2026):

- `mcp_basis.py` in `apple` und `chat`: Werkzeuge dürfen PNG-Bilder zurückgeben (MCP-Bildinhalt, nur echte PNG bis zu einer Größengrenze). Gebraucht für die Vorschau im Plugin `arbeit`, an den Werkzeugen von `apple` und `chat` ändert sich nichts.

Teil a, Datenordner (15.11.2026):

- Die Server von `mail`, `chat`, `apple` und `service` lesen `config.json`, `style/` und `.venv` nur noch aus `~/Library/Application Support/Claude Kits/<plugin>/`. Der Rückfall auf den Plugin-Ordner im Repo entfällt, damit laufen die Plugins aus dem Account auch ohne Klon des Repos. Wer bisher dort seine Einstellungen hatte, verschiebt `config.json` und `style/` je Plugin in den Datenordner und baut die `.venv` dort neu (Befehl in den READMEs von `mail` und `apple`).
- Fehlerprotokoll `.fehler.jsonl` in der Wurzel des Datenordners, geschrieben nur bei Start über einen Server.
- `paket.py` gibt dem Code-Tab Lesen und Schreiben im Datenordner, die `.venv` dort bleibt für Bash gesperrt.
- `einrichten`, `feedback`, Stil-Referenzen und `roadbook` nennen den Datenordner. Tests brauchen keine `config.json` im Plugin-Ordner mehr.

Nachtrag (16.11.2026):

- Skill `mail`: Eine Mail an den Nutzer selbst geht an die Absenderadresse des passenden Kontos, nicht an die Mailadresse des Claude-Accounts.

## v6.3.1 (14.11.2026)

Alle fünf Plugins auf 6.3.1 (`service` von 6.1.0). Aufräumrunde ohne Änderung am Verhalten der Werkzeuge.

- `kit.json` je Plugin nur noch mit `verbote` (Sperren im Code-Tab) und `abhaengigkeiten`, ohne Bash-Muster, Version und Skill-Liste.
- Meldungen ohne Zugriff (Kalender, Erinnerungen, Kontakte) nennen zuerst die Freigabe für `python3.9` der Command Line Tools, mit der die Werkzeuge laufen.
- READMEs beschreiben Server, Werkzeuge und Stufen statt Aufrufe im Code-Tab, Kommentare ohne alte Versionsmarken.
- `einrichten` ohne Pflegetag und `_eingang.md`: Neues merkt sich Memory, der monatliche Abgleich übernimmt es. `kontext` ohne den Rest aus V5.

## v6.3.0 (14.11.2026)

`basis`, `mail`, `chat` und `apple` auf 6.3.0, `service` unverändert auf 6.1.0. Der Code-Tab dient nur noch der Pflege, die Dialoge sind kurz.

- Dialog nur noch, wenn andere es sehen oder es sich nicht rückgängig machen lässt. `mail_entwurf_anhang` und `notiz_ersetzen` sind jetzt Stufe schreiben (bleibt im eigenen Account). Geteilte Notizordner fragen weiter: `notiz_anlegen_geteilt` heißt jetzt `notiz_geteilt` und ersetzt mit `ersetzen` auch Inhalte. `notiz.py replace` ändert eine geteilte Notiz (oder eine in geteiltem Ordner, im Zweifel auch) nur mit `--ausfuehren`, sonst kommt eine Vorschau.
- Dialoge vor der Stufe nachfrage in Stichworten, nur was die Entscheidung braucht: `mail_senden` Betreff, An, Cc, Bcc, Von. `termin_mit_nachfrage` Termin, Wann (20.11. 10:00 bis 11:00), Kalender, Hinweis auf Updates an alle Teilnehmer. `imessage_senden` An und Text (höchstens 160 Zeichen). `notiz_geteilt` Notiz, Ordner und ob der Inhalt ersetzt wird, ohne Inhalt. Abbrechen bleibt Vorauswahl. Neu in `mcp_basis.py` (gleich in `mail`, `chat`, `apple`): `angaben` und `ordnername`.
- Skills `einrichten` und `umzug` empfehlen einen Schnitt der Cowork-Projekte samt Ordnern aus den Befunden des Kontextordners (Runde 5 im Interview, Schritt 4 im Umzug), je Projekt mit Begründung, nach den Empfehlungen von Anthropic zu Projekten und Memory: ein Projekt je dauerhaftem Bereich, Trennung nach Vertraulichkeit mit Use account memory aus, nicht zu fein. Neu `einrichten/references/projektschnitt.md`, in der Vorlage `privat-profil.md` der Abschnitt Bereiche und Projekte.

- `paket.py` schlank (602 statt 1.274 Zeilen): Einrichten schreibt Marketplace, Plugins, Output-Style, die `CLAUDE.md` der Instanz, Rechte für die Pflege des Kontextordners und die Sperren der Apple-Datenordner aus `kit.json`. Keine Regeln mehr für Skripte und Connectoren im Alltag, alte Einträge entfernt der nächste `--apply` (laut Stand). Neu `--zips ORDNER` (ZIP je Plugin aus dem letzten Commit, ohne `tests/` und `kit.json`, `export-ignore` aus `.gitattributes` gilt) und `--instructions` (Text für Instructions for Claude nach `umzug/instructions.md`). Entfallen: `--neu`, `--aktualisieren`, `--wochencheck`, `--exporte`, `--abloesen`, die Felder `connectoren`, `zuender`, `pflegetag`, `exporte`, `profil_im_account` und `modus` je Plugin. `plugins` darf eine Liste sein. `--pruefen` vergleicht jetzt auch `mcp_basis.py`.
- `zuender.py` gelöscht.
- Skill `paket` auf Pflege und Release, `umzug` nutzt `--instructions` und liest die Connectoren aus der Session, `kontext` verweist für Memory auf die Regeln der Instructions statt einer eigenen Liste.

## v6.2.0 (14.11.2026)

`basis`, `mail`, `chat` und `apple` auf 6.2.0, `service` unverändert auf 6.1.0. Für den Umzug eines zweiten Accounts nach Cowork.

- Modus lesen je Account: `mcp_nur_lesen` in der `config.json` darf eine Liste von Instanzen sein, etwa `["arbeit"]`. Der Server erkennt die startende App (`privat` für Claude Privat über Config-Ordner, Plugin-Ordner oder Elternprozess, sonst `arbeit`, `KITS_INSTANZ` setzt den Wert fest). So teilen sich zwei Accounts eine `config.json`, und `chat` bietet nur in einem Entwürfe und Senden an. `true` gilt wie bisher immer. Gleich in `mcp_basis.py` von `mail`, `chat` und `apple`.
- Skill `umzug`: Regeln für einen Account mit Instruktionen der Organisation, für geteilte Bibliotheken als Ordner im Projekt (nur lesen per Instruktion, je Mandat ein Projekt) und für eigene Plugins und den Modus lesen in der Prüfliste.

## v6.1.1 (13.11.2026)

`mail`, `chat` und `apple` auf 6.1.1, `basis` und `service` unverändert auf 6.1.0. Funde aus der Abnahme in Cowork.

- `mail_neues` (`mail.py triage`) trennt nach Konto: ohne Profil alle Konten aus `accounts`, je Konto ein Kopf `Konto ...:`, ein Konto ohne Neues mit nichts Neues. Die Grenze `triage.max_markiert` gilt je Konto. Der Skill `mail` nennt die Konten getrennt.
- `notiz_anlegen`: Beginnt der Inhalt schon mit dem Titel (etwa als Überschrift), steht er in der Notiz nicht mehr doppelt.
- Skill `imessage`: Nennt der Nutzer Empfänger und wörtlichen Text mit einem Sendewort (`Schick X: Text`), sendet Claude gleich mit `imessage_senden`, der Dialog am Mac ist die Freigabe. Kein Entwurf mehr, wenn Claude senden soll, damit der Text nicht im Eingabefeld stehen bleibt.

## v6.1.0 (13.11.2026)

`basis` und `service` auf 6.1.0, `mail`, `chat` und `apple` unverändert auf 6.0.0.

- Neuer Skill `/basis:umzug` (Code-Tab): schreibt im Kontextordner `umzug/` mit dem Text für Instructions for Claude, den Cowork-Projekten, den Connector-Rechten zum Abhaken, den geplanten Aufgaben für Cowork und einer Prüfliste. Prüft den Index des Projekts, Vorlage `projekt-index.md`.
- Profil und Index getrennt: Liegt `profil.md` im Kontextordner, schreibt `paket.py` die `CLAUDE.md` der Instanz aus `profil.md` plus `CLAUDE.md` (Index des Projekts, lädt in Cowork aus dem Projektordner). `praeferenzen.txt` kommt nur aus dem Profil. Schalter `profil_im_account` für die Zeit, in der die Instructions for Claude auch im Code-Tab wirken. Ohne `profil.md` bleibt alles wie bisher.
- `/basis:kontext`: Merken heißt Memory, `wissen/` ändert sich nur durch Interview, Abgleich oder ausdrücklichen Auftrag. `aktualisieren` ist der monatliche Abgleich: Memory gegen `wissen/`, neue Personen aus WhatsApp, iMessage, gesendeten Mails und Kalender, Fragen in `_interview.md`. Der Eingang entfällt, ein alter wird im Interview abgearbeitet.
- Kontext-Zünder (Hook bei jedem Prompt) entfällt, auch im Code-Tab.
- Home Assistant als lokaler MCP-Server im Plugin `service`: Adresse und Paket im Block `homeassistant` der `config.json`, Token aus dem Schlüsselbund, ha-mcp über `uvx`. Ohne Konfiguration startet er ohne Werkzeuge und nennt den Grund.

## v6.0.0 (13.11.2026)

Alle fünf Plugins auf 6.0.0.

- Lokale MCP-Server in `mail` (12 Werkzeuge), `chat` (8) und `apple` (9): Die Skripte laufen jetzt auch in Cowork, wo Bash in einer VM ohne Apple-Apps läuft. Der Server ist eine dünne Schicht über den vorhandenen Skripten (`mcp_basis.py`, gleich in drei Plugins), Start über `.mcp.json` mit `python3` ab 3.9.
- Stufen je Werkzeug als Annotation: lesen läuft ohne Rückfrage, schreiben legt Entwürfe, Erinnerungen, Notizen und eigene Termine an, nachfrage (Mail senden, Anhang, Arbeitskalender, Termine mit Teilnehmern, iMessage senden, Notiz ersetzen, geteilte Ordner) trägt `destructiveHint`, ihre Beschreibung nennt die Bedingung für den Aufruf. Löschen und Verwerfen gibt es nicht.
- Datenordner: `config.json`, `style/`, Textdateien und `.venv` kommen aus `~/Library/Application Support/Claude Kits/<plugin>/`, sonst wie bisher aus dem Plugin-Ordner unter `~/Claude Kits/claude-kits/plugins/<plugin>/`. Ein Plugin aus dem Account liegt bei jeder Version woanders.
- Modus lesen für `chat`: `mcp_nur_lesen: true` in der `config.json` oder `KITS_NUR_LESEN=1` bietet nur die Lese-Werkzeuge an.
- Die Skills `mail`, `kalender`, `whatsapp`, `imessage`, `erinnerungen` und `notizen` nennen Werkzeuge statt Bash-Befehle, Beschreibungen ohne Liste der Auslöser. `einrichten` und `paket` bleiben im Code-Tab.
- Wochen-Check beim Sessionstart entfällt, Updates kommen über den Marketplace im Account.
- Test der Arbeitssignatur ohne feste Texte aus der echten Signatur.
- Prompt-Audit vor dem Release: jeder Parameter der Werkzeuge mit Beschreibung, `einrichten` nutzt die Werkzeuge, Paketordner über seine feste Ablage statt über den Plugin-Ordner, Befehle in der langen Form (`/basis:kontext`, `/service:homeassistant`, `/service:roadbook`), Beschreibungen von `einrichten`, `feedback`, `paket`, `homeassistant` und `roadbook` ohne Liste der Auslöser.

## v5.1.0 (12.11.2026)

`basis` und `mail` auf 5.1.0, die anderen Plugins unverändert.

- Umstieg vom alten Motor: `paket.py --abloesen`, `gesperrt`, `--exporte`, Pflegetag-Hinweis, Kontext-Zünder als Hook, `/kontext aktualisieren`.
- Zwei Instanzen auf einem Rechner: `einrichtung.<name>.json` neben `einrichtung.json`, je mit eigenem Stand. In einer Session wählen `paket.py` und der Zünder die Datei selbst, im Terminal `--einrichtung <name>`.
- Eigene Plugins neben dem Paket: `eigene_plugins` in der Einrichtung trägt eigene lokale Marketplaces samt Rechten aus deren `kit.json` ein.
- Microsoft 365: `mail` und `kalender` haben Abläufe für den Connector (Triage mit Gesendet, Adressen, Weiterleiten, Termine mit Teilnehmern, Antworten auf Einladungen, Abwesenheit).
- `/kontext aktualisieren` nimmt eine eigene `pflegelauf.md` im Kontextordner, wenn dort eine liegt.

## v5.0.1 (11.11.2026)

- `einrichten` nach dem Vorbild der Alfred-Einrichtung 1.1: feste Obergrenzen der Auswertung je Schritt für jedes Modell, nach jedem Schritt eine Zeile statt Rückfrage, offene Frage "Wer fehlt noch" mit festem Text, Hinweise bei fehlenden Freigaben statt endlosem Probieren, Probe überspringbar, Abschluss mit gezählten Personen, Konten, Kalender und offenen Punkten, Modell-Tipp für die Desktop-App.

## v5.0.0 (11.11.2026)

Erste Version.

- Paket aus den bisherigen Kits als fünf Plugins: `basis`, `mail`, `chat`, `apple`, `service`.
- `paket.py`: Rechte, Marketplace und Plugins in die `settings.json`, `CLAUDE.md` aus dem Kontextordner, Prüfung des Pakets, Updates auf den neuesten Tag, Wochen-Check beim Sessionstart.
- Neue Skills: `einrichten` (Kennenlernen im Gespräch), `feedback` (Rückmeldungen als Mail-Entwurf), `paket` (Rechte und Updates), `rueckmeldungen` (nur für den Betreuer).
- `mail.py finden`: eine Mail aus dem Mail-Connector in Apple Mail finden und dort beantworten.
- Fehlerprotokoll: Abbrüche der Skripte landen ohne Inhalt in `.fehler.jsonl`, `feedback` zählt sie für den Bericht.
- Neutral: Profil `arbeit` statt eines Firmennamens, keine Namen in Code, Tests und Texten.
