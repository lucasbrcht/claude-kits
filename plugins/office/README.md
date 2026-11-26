# Plugin office

Dokumente bearbeiten, ohne das Original anzufassen, für Cowork und den Code-Tab, ein lokaler MCP-Server (seit 8.0, vorher Teil von `apple` und `basis`). Claude holt eine Arbeitskopie je Thema in die Ablage, alle Runden laufen darin, ins Original geht sie erst auf ausdrückliches "übertragen". Mit dem Motor findet, liest, ändert und prüft Claude PowerPoint-Decks und Excel-Mappen und zeigt sie als Vorschau. Neue Folien entstehen aus Musterfolien einer Vorlage oder mit den Skills `pptx`, `xlsx` und `docx` von Anthropic, danach werden sie mit `anlegen` zur Arbeitskopie. Word bearbeitet der Skill `docx`. Nichts verlässt das Gerät über das Plugin: kein Netz, auch nicht für LibreOffice.

Neutral und ohne Kontext: Das Plugin taugt auch für Kollegen mit Mac. Regeln eines Kunden oder Arbeitgebers (Vorlagen, Add-ins) gehören in den Kontextordner des Nutzers, nie in die Skills.

Was das Plugin bewusst nicht kann: löschen, neue Dateien oder Ordner neben dem Original anlegen, das Original direkt bearbeiten, Word-Inhalte ändern (nur die Sprache).

## Installation

In Cowork: Seitenleiste oben > Plugins oder Anpassen (je nach App, nicht Einstellungen > Plugins) > Add marketplace mit `lucasbrcht/claude-kits` (Sync automatically), dann `office` installieren. In Claude Code:

```
/plugin install office --marketplace lucasbrcht/claude-kits
```

Die Grundstufe braucht nur macOS. Den Motor richtet `/basis:einrichten` ein oder der Abschnitt Motor für Office in `INSTALL.md` des Pakets.

## Werkzeuge

Der Server `server.py` (über `.mcp.json` mit dem Python der Command Line Tools, Unterbau `mcp_basis.py`) ruft die Skripte ohne Shell auf. Höchstens 10 Werkzeuge (`GRENZE_OFFICE` in `tests/test_server.py`).

| Stufe | Grundstufe | Motor |
|---|---|---|
| lesen | | `folien_finden`, `folien_lesen`, `folien_pruefen` |
| schreiben | `arbeitskopie` (holen, anlegen, liste, zeigen, zuruecknehmen mit Motor), `sprache` (prüfen oder setzen, .pptx und .docx) | `folien_aendern`, `excel_skript`, `excel_fertig`, `office_vorschau` |
| nachfrage | `arbeitskopie_uebertragen` (Arbeitskopie ins Original, Dialog von macOS mit `Achtung: Shared Folder` bei geteilten Ordnern) | |

Mit `mcp_nur_lesen` bleiben die drei lesenden Werkzeuge des Motors. Fehlt der Motor, melden seine Werkzeuge das mit Installationszeile, die Grundstufe läuft weiter.

**Runden und Änderungen von Hand (seit 8.1):** `excel_skript` und `folien_aendern` arbeiten auf dem aktuellen Stand der Arbeitskopie. Jede Runde läuft über `motor/stand.py`: Merkmale je Zelle, Format, Tabelle, Form, Text und Folie nach der letzten Runde liegen im Zustandsordner, Abweichungen meldet die nächste Runde als VON HAND und schützt sie. Die Änderung entsteht in einer Kopie im Temp-Ordner und geht nur ohne Überschneidung zurück (bei Excel auch ohne Verlust durch openpyxl), sonst HALT, `ueberschreiben` nur nach Ja des Nutzers. Danach stehen die geänderten Bereiche unter GEÄNDERT. `arbeitskopie` mit `aktion` zuruecknehmen setzt die letzte Runde zurück, solange niemand die Datei danach geändert hat. Bis 8.0 spielte `folien_aendern` die ganze Liste bei jedem Lauf auf das Original ab, dessen Zustand fällt beim ersten Lauf weg.

**Neue Dateien (seit 8.2):** `arbeitskopie` mit `aktion` anlegen macht eine neue Datei zur Arbeitskopie ohne Original, aus einer Vorlage (.potx, .dotx, .xltx werden .pptx, .docx, .xlsx) oder so, wie ein Skill sie im Thema gebaut hat. Den Stand beim Anlegen hebt `ablage-ausgang/` im Datenordner auf, er steht in den Runden für das Original: So erkennt schon die erste Runde Änderungen von Hand, und Altlasten der Vorlage zählen in der Prüfung nicht. Danach setzt der Server die Sprache und prüft das Deck. Übertragen gibt es für neue Dateien nicht.

**Gestaltung (seit 8.2):** `folien_pruefen` meldet zusätzlich als WARNUNG, ohne dass sie als Fund zählen: getippte Aufzählungszeichen, Schrift unter 10 pt, Formen über den Folienrand und Textfelder auf einer Form ohne eigenen Text. `folien_aendern` behebt das mit `absaetze` und `punkt` (echte Aufzählung) und mit `in_form` (Text in die Form, Textfeld weg). `sprache` ergänzt lang auch an Textstellen ohne Sprache, wie python-pptx sie schreibt. `stand.py` zählt einen Lauf ohne `a:rPr` wie einen mit leerem, so wird das keine Änderung von Hand.

**Prüfung von Decks:** `folien_pruefen` prüft Zip, XML, Inhaltstypen, alle Verweise in allen Teilen, fehlende Ziele von Beziehungen und eingebettete Schriften ohne Datei (daran scheitert PowerPoint, die XSD-Prüfung merkt es nicht), dazu die bekannten Fallen. `[trash]/` von PowerPoint für Mac zählt nie. Die XSD-Prüfung nimmt `validate.py` aus `motor.pptx_validate` oder sucht den Skill pptx, den Cowork am Mac ablegt, und braucht `defusedxml` in der `.venv`.

## Skills

| Skill | Inhalt |
|---|---|
| `dateien` | Ablage je Thema, Holen, Übertragen, Aufräumen, Sprache, PDF aus HTML. Gilt für alle Formate |
| `folien` | bestehende Decks finden, lesen, ändern, prüfen, Vorschau, Sprache nach jeder Änderung |
| `excel` | bestehende Mappen ändern, prüfen, nachrechnen. Original vorher schließen, Excel öffnet nie zwei Mappen gleichen Namens |

## Aufbau

| Datei | Aufgabe |
|---|---|
| `server.py` | Werkzeuge, Stufen, Umzug aus 7.3, Start des Motors unter `sandbox-exec` |
| `ablage.py` | Arbeitskopien: `holen`, `liste`, `zeigen`, `uebertragen` mit Stand-Schutz (Prüfsumme), Sperrdatei von Office und Sicherung |
| `sprache.py` | Sprache von .pptx und .docx prüfen und setzen, nur in der Ablage |
| `office.py` | Vorschau (PDF, PNG) und Nachrechnen mit LibreOffice und pdftoppm, mit dem Python des Servers |
| `sperren.py` | gesperrte Orte und Regeln für `sandbox-exec`, gemeinsam für Server und `office.py` |
| `motor/` | `finden.py`, `lesen.py`, `pruefen.py`, `aendern.py` mit `uebernehmen.py`, `excel.py`, `stand.py` (Runden, Änderungen von Hand, zurücknehmen), `gemeinsam.py`. Laufen mit der `.venv` (python-pptx, openpyxl, lxml, defusedxml) |
| `kit_basis.py`, `mcp_basis.py` | gleich in `apple`, `chat` und `office`, nur zusammen ändern |

## Sandbox des Motors

Jedes Skript in `motor/` und jeder Python-Code für Excel läuft unter `sandbox-exec`: kein Netz, Schreiben nur im Zwischenordner, in Temp und in den Ordnern der Ablage, kein Lesen der gesperrten Orte. Gesperrt sind immer die Datenordner von Mail, Kalender, Notizen, Erinnerungen, Kontakten, Nachrichten und WhatsApp wie in `kit.json` von `apple` und `chat`, Schlüsselbund, Cookies, Safari, `.ssh`, `.gnupg`, die Datenordner der anderen Plugins und das Fehlerprotokoll, dazu `motor.gesperrt`. Ohne Sandbox läuft nichts, es gibt keinen Schalter dafür.

`office.py` nimmt Eingaben nur aus dem Thema der Ablage, jeden Pfadteil mit `O_NOFOLLOW`, wandelt eine Kopie in `staging/` um und legt PDF und Bilder per rename über den Ordner-Deskriptor in `zwischen/vorschau`. LibreOffice und pdftoppm laufen unter `sandbox-exec` ohne Verbindungen ins Netz und ohne Zugriff auf die gesperrten Orte.

## Datenordner

`~/Library/Application Support/Claude Kits/office/`, nicht im Git und nicht im Plugin:

| Ort | Inhalt |
|---|---|
| `config.json` | Abschnitte `ablage`, `motor`, `suche` (Vorlage `config.example.json`) |
| `ablage.json`, `ablage-sicherung/` | Herkunft und Stand jeder Arbeitskopie, alter Stand vor dem letzten Übertragen |
| `ablage-ausgang/` | Stand neuer Dateien beim Anlegen, Vergleich für die Runden, verwaiste fallen beim nächsten Anlegen weg |
| `.venv` | python3.12 mit python-pptx, openpyxl, lxml, defusedxml (für Bash gesperrt) |
| `zwischen/` | `listen`, `zustand` (je Arbeitskopie Stand und Stand davor), `vorschau`, `tmp`: einziger Schreibort des Motors außer Ablage und Temp |
| `staging/`, `libreoffice-profil/`, `libreoffice-rechnen/` | für `office.py`, für den Motor nicht beschreibbar |

Gelesen und geschrieben wird die `config.json` über `einstellungen` und `einstellungen_schreiben` des Plugins `apple` mit `plugin` office.

**Umzug aus 7.3:** Fehlt `ablage` in der eigenen `config.json`, übernimmt der Server beim ersten Start den Abschnitt aus der `config.json` von `apple` und kopiert `ablage.json` und `ablage-sicherung/` aus dessen Datenordner. Die Dateien bei `apple` bleiben liegen.

## config.json

| Feld | Bedeutung |
|---|---|
| `ablage.privat`, `ablage.arbeit` | Ordner der Arbeitskopien, Standard `Claude Personal` und `Claude Work` im Downloads-Ordner von iCloud Drive (ohne iCloud Drive für Downloads in `~/Downloads`). Fehlt der Ordner, legt das erste `holen` ihn an. Ohne Arbeit `arbeit` leer |
| `suche.ordner` | Ordner, in denen `folien_finden` ohne eigenen `ordner` sucht |
| `motor.gesperrt` | weitere Ordner, die der Motor weder lesen noch schreiben darf, etwa der Kontextordner. Ein falscher Eintrag bricht ab |
| `motor.umgebung` | `FONTCONFIG_FILE` für LibreOffice, sonst Ersatzschriften |
| `motor.pptx_validate` | Pfad zu `validate.py` aus dem Skill `pptx` von Anthropic für die XSD-Prüfung. Leer sucht der Server ihn unter `~/Library/Application Support/*/local-agent-mode-sessions/skills-plugin/`, `aus` schaltet die XSD-Prüfung ab |

## Voraussetzungen

- Grundstufe: macOS, der Server startet mit `/Library/Developer/CommandLineTools/usr/bin/python3`.
- Motor: `brew install python@3.12 poppler`, `brew install --cask libreoffice`, eine `.venv` im Datenordner mit `pip install python-pptx openpyxl lxml defusedxml`. Befehle in `INSTALL.md`.

## Tests

Im Plugin-Ordner `python3 -B -m unittest discover tests`, dazu mit `/Library/Developer/CommandLineTools/usr/bin/python3` (so startet der Server) und mit `python3.12`, wenn python-pptx und lxml dort installiert sind: Ohne sie überspringen sich die Folien-Tests. `sandbox-exec`, `soffice` und `pdftoppm` ersetzen in den Tests Skripte, die Profile prüft ein Test mit dem echten `sandbox-exec` auf Syntax.
