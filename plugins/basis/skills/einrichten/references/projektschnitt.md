# Projektschnitt: welche Cowork-Projekte mit welchen Ordnern

Für den Skill `einrichten` (Runde 5 des Interviews, Projekte in `cowork.md`). Claude empfiehlt aus den Befunden einen Schnitt, je Projekt mit kurzer Begründung. Der Nutzer entscheidet, Claude legt nichts selbst an. Das Projekt für den Grundbereich besteht schon, die Einrichtung läuft darin.

## Was ein Projekt ist (Doku von Anthropic, abgerufen 14.11.2026)

Quellen: claude.com/docs/cowork/guide/projects, Hilfe-Center "Organize your tasks with projects in Claude Cowork", "What are projects?" und "Use Claude's chat search and memory".
- Ein Projekt bündelt alles für einen **wiederkehrenden Bereich**: Ordner, Instruktionen, Links, geplante Aufgaben und ein **eigenes Memory**. Jede Session im Projekt startet damit.
- Was Claude in einem Projekt lernt, geht nicht in andere Projekte. Das Memory außerhalb von Projekten nutzt es mit, neues Projekt-Memory kann dorthin zurückwirken. Ganz getrennt nur mit **Use account memory aus** auf der Seite des Projekts.
- Die **Beschreibung** sagt, wofür das Projekt da ist. Dispatch wählt danach das Projekt für eine Aufgabe.
- Hineingezogene Dateien landen im **ersten Ordner** des Projekts. Archivieren löscht Instruktionen, Links und Memory, die Ordner bleiben.

## Regeln für den Schnitt

1. **Ein Projekt je dauerhaftem Bereich**, in dem sich mindestens eins unterscheidet: Wissen und Unterlagen, Instruktionen (Ton, Regeln, Anrede) oder was Claude sich merken soll. Prüffrage: Würde das Memory aus dem einen Bereich im anderen stören oder dort nicht hingehören?
2. **Nach Vertraulichkeit trennen.** Daten Dritter mit Schweigepflicht oder Vertrag (Klienten, Mandanten, Patienten, Kundenunterlagen) und eigene Steuern, Finanzen und Anträge bekommen ein eigenes Projekt mit Use account memory aus. Gibt es für die Arbeit einen Account der Firma, gehört die Arbeit dorthin (zweiter Account mit eigener Einrichtung), nicht als Projekt in den privaten.
3. **Nicht zu fein.** Kein Projekt je Person, Kunde, Monat oder Einzelvorhaben. Ein Vorhaben unter drei Monaten (Reise, Umzug, Feier) läuft im Bereich mit. Ein längeres mit eigenen Unterlagen und Beteiligten (Hausbau, Studium, Pflege eines Angehörigen) darf eins werden und wird danach archiviert. Meist reichen zwei bis vier Projekte je Account, mehr als fünf nur mit Grund.
4. **Gemeinsames gehört nicht ins Projekt.** Person, Schreibregeln und feste Regeln stehen einmal in den Instructions for Claude und gelten in jedem Projekt. Instruktionen des Projekts nennen nur, was dort anders ist.

## Von den Befunden zum Schnitt

| Befund (Interview, Kontextordner) | Empfehlung |
|---|---|
| immer | Projekt **Privat**: Familie, Freunde, Haushalt, Freizeit. Kontextordner als erster Ordner, Use account memory an |
| angestellt, Account der Firma vorhanden | Arbeit im Account der Firma, dort meist ein Projekt **Arbeit**. Ein eigenes Projekt je Kunde nur bei eigener Ablage mit Geheimhaltung |
| angestellt, kein Account der Firma | Projekt **Arbeit** im selben Account, Use account memory aus, wenn Kundendaten darin liegen |
| selbständig | Projekte nach Arbeitsfeld, nicht nach Kunde: die Arbeit mit Kunden oder Klienten und die Verwaltung (Rechnungen, Steuern, Anträge) getrennt, beide mit Use account memory aus |
| Ehrenamt, Verein, Studium, eigene Immobilie, Pflege eines Angehörigen | eigenes Projekt, wenn dauerhaft und mit eigenen Unterlagen, sonst Teil von Privat |
| private Steuern, Verträge, Gesundheit | nur auf Wunsch ein Projekt, dann Use account memory aus. Sonst Unterlagen im Ordner lassen und bei Bedarf in Privat nennen |

Beispiele (nur zur Verdeutlichung):
- Selbständiger Personal Trainer: **Privat**, **Arbeit Klientenorganisation** (Termine, Trainingspläne, Kommunikation mit Klienten), **Arbeit Steuern und Anträge** (Rechnungen, Steuer, Förderanträge).
- Angestellte Projektleiterin mit Account der Firma: im privaten Account **Privat**, im Account der Firma **Arbeit**.
- Im Ruhestand mit Vereinsvorsitz: **Privat**, **Verein**.

## Ordner je Projekt

- **Erster Ordner** ist der, in dem die Unterlagen des Bereichs schon liegen (Use an existing folder), sonst ein neuer Ordner mit dem Namen des Projekts. Nie der Kontextordner selbst, außer im Projekt, dessen Wissen er ist (meist Privat, im Account der Firma Arbeit).
- **Kontextordner** als weiterer Ordner in jedem Projekt desselben Accounts: Er bringt Index, Personen und Wissen. In Projekten mit Use account memory aus dazu die Zeile `<Kontextordner>: nur lesen, ändern nur auf meinen Zuruf` in den Instruktionen, damit nichts Vertrauliches in `wissen/` landet (Cowork kennt keinen Schreibschutz je Ordner).
- Geteilte oder synchronisierte Bibliotheken (OneDrive, SharePoint, geteilte iCloud-Ordner) nur, wenn der Nutzer sie im Projekt will, mit derselben Zeile `nur lesen`.
- Ordner in iCloud Drive gehen für Unterlagen. Der Kontextordner bleibt lokal mit eigenem Git.

## Empfehlung zeigen

Eine Tabelle, dann die Frage, ob der Schnitt so passt (Auswahlfrage: so übernehmen, zusammenlegen, weiter teilen):

| Projekt | Beschreibung (für Dispatch) | Ordner | Memory | Warum eigenes Projekt |
|---|---|---|---|---|
| Privat | Familie, Freunde, Haushalt und Freizeit | Kontextordner | Use account memory an | Standardbereich, Wissen im Kontextordner |

Je Projekt eine Zeile Begründung nach den Regeln oben. Was der Nutzer verwirft oder zusammenlegt, gilt. Unklares (etwa ob ein Account der Firma kommt) als `OFFEN:`.
