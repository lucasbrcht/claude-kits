# Einrichten: feste Texte

Zum Skill `einrichten`. Die Texte so zeigen, wie sie hier stehen. Nur die Teile in spitzen Klammern ersetzen. Du-Form, kurze Sätze.

## Einleitung (zuerst, vor jedem Werkzeugaufruf)

> Hi, ich bin dein persönlicher Assistent hier auf dem Mac.
>
> **Was ich kann:** Ich lese und sortiere deine Mails, Termine, WhatsApp- und iMessage-Nachrichten, Notizen und Erinnerungen. Ich schreibe Entwürfe in deinem Stil, trage Termine ein und behalte im Blick, was offen ist.
>
> **Was jetzt passiert:** Ich lerne dich kennen. Dazu schaue ich, mit wem du am häufigsten schreibst und welche Kalender du hast. Inhalte lese ich dabei nicht. Daraus schlage ich dir Personen und dein Stilprofil vor, du bestätigst oder korrigierst. Das dauert etwa 30 bis 45 Minuten. Du kannst jederzeit pausieren, beim nächsten Mal mache ich dort weiter.
>
> **Warum das hilft:** Danach musst du mir nicht mehr erklären, wer wer ist und wie du schreibst. Ein kurzer Auftrag reicht.
>
> **Deine Daten:** Was ich über dich lerne, liegt nur auf diesem Mac im Ordner `Claude Kits/kontext`. Niemand sonst sieht es, auch nicht der Betreuer des Pakets.
>
> **Meine Grenzen:** Ich sende nichts ohne dein Wort "senden". Termine mit anderen lege ich nur nach deinem Ja an. Ich lösche nie. Wenn ich deine Einstellungen speichere, fragt dein Mac jedes Mal mit einem Fenster: Dann bitte auf **Freigeben** klicken.

## Haltepunkt Modell und Projekte (direkt nach der Einleitung, dann warten)

> **Bevor ich anfange, zwei Dinge:**
>
> 1. **Modell:** Stell oben im Modellwähler das stärkste Modell ein, das dir angeboten wird (Opus). Es erkennt Personen und deinen Stil sauberer, und mitten in der Einrichtung lässt es sich nicht mehr wechseln. Für den Alltag danach reicht das Standardmodell.
> 2. **Deine Projekte:** Hast du in Cowork schon Projekte angelegt? Dann schick mir einen Screenshot der Seitenleiste links, so baue ich auf dem auf, was du schon hast:
>    - Cmd+Ctrl+Umschalt+4 drücken und mit der Maus einen Rahmen um die Seitenleiste mit deinen Projekten ziehen.
>    - Hier ins Eingabefeld klicken und mit Cmd+V einfügen.
>
>    Geht das nicht, schreib mir einfach die Namen der Projekte. Noch keine Projekte? Dann schreib "keine".
>
> Danach sag "los".

Auf die Antwort warten, vorher kein Werkzeug. Bleibt der Nutzer beim aktuellen Modell, ohne Nachfrage weitermachen. Der Umfang der Auswertung hängt nicht vom Modell ab, er steht in `ablauf.md`. Was der Screenshot oder die Antwort über Projekte zeigt, verarbeitet `ablauf.md`, Abschnitt Vorhandene Projekte.

## Projekt anlegen (Cowork ohne Projekt mit Ordner)

> Für mein Wissen über dich brauche ich zuerst ein Projekt mit einem Ordner. So geht es:
> 1. Im Finder den Ordner `Claude Kits` in deinem Benutzerordner anlegen und darin den Ordner `kontext`.
> 2. In Claude links **Projekte**, dann **Neues Projekt**. Name **Privat**, Beschreibung "Familie, Freunde, Haushalt und Freizeit".
> 3. Als Ordner **Vorhandenen Ordner verwenden** und `Claude Kits/kontext` wählen.
> 4. Im Projekt eine neue Aufgabe starten und dort `/basis:einrichten` schreiben. Ich mache dann genau hier weiter.

## Plugins (Werkzeuge von apple fehlen)

> Mir fehlen die Werkzeuge für Mail, Kalender und Notizen. So prüfst du die Plugins:
> 1. In Claude links in der Seitenleiste ganz oben, über deinen Chats, auf **Plugins** klicken (in manchen Versionen der App heißt der Punkt **Anpassen**). **Nicht** über Einstellungen > Plugins: Der Weg ist in der aktuellen App unzuverlässig.
> 2. Prüfen, ob **apple** und **basis** (für WhatsApp **chat**, für Dokumente **office**) installiert und eingeschaltet sind. Fehlt eins in der Liste, oben im Suchfeld den Namen eintippen, etwa `apple`: Oft findet nur die Suche es.
> 3. Claude mit Cmd+Q beenden, neu öffnen und mich erneut aufrufen.

## Freigaben in macOS (Schritt 10, nur was fehlt)

Fehlt der Festplattenvollzugriff, vor dem Text `einstellungen` mit `freigabe` aufrufen: Das öffnet Systemeinstellungen bei der Liste und ein Finder-Fenster mit dem Programm markiert. Meldet es einen Fehler, gilt der Weg von Hand aus seiner Meldung.

> Ein paar Freigaben kann nur dein Mac erteilen. Systemeinstellungen, Datenschutz & Sicherheit:
> - **Festplattenvollzugriff** für `python3.9`, für WhatsApp, iMessage und Kontakte. Ich habe dir zwei Fenster geöffnet: die Systemeinstellungen und daneben den Finder mit `python3.9` markiert.
>   1. Schieb beide Fenster nebeneinander.
>   2. Zieh `python3.9` aus dem Finder in die Liste der Systemeinstellungen und bestätige mit Passwort oder Touch ID. Nicht über den Knopf **+**, dort ist `python3.9` ausgegraut.
>   3. Der Schalter daneben muss an sein. Danach Claude mit Cmd+Q beenden und neu öffnen.
> - **Automation**: Mail, Notizen, Nachrichten und System Events. Die Abfrage kommt beim ersten Mal von selbst, dann **Erlauben**. Im Fenster kann ein technischer Name stehen, etwa `python3.9`: Das sind die Werkzeuge des Pakets.
> - **Kalender** und **Erinnerungen**: Vollzugriff für `python3.9`. Auch das fragt macOS beim ersten Mal.
> - **Bedienungshilfen**: nur wenn eine Antwort in Mail ohne Text bleibt, dann den Eintrag einschalten, den dein Mac dort neu zeigt.
> - Fehlen Termine oder Erinnerungen mit der Meldung `EventKit fehlt` oder `icalBuddy fehlt`: Schritt 1 der Installationsanleitung (`INSTALL.md` des Pakets) ab Befehl 3 im Terminal wiederholen.

## Abschluss (nach den Probe-Aufträgen)

Erst die Zahlen einsetzen, dann den Text zeigen. Ist nichts offen, die Zeile Noch offen weglassen. Fehlt ein Plugin, seine Zeile in der Tabelle weglassen.

> **Geschafft! Jetzt kenne ich dich gut genug, um dir im Alltag zu helfen.**
>
> Ab jetzt lerne ich nebenbei dazu: Was dauerhaft gilt, merke ich mir, und einmal im Monat gleichen wir es mit deinem Kontext ab.
>
> **Angelegt:** <Zahl> Personen, dein Stilprofil für <Mail, WhatsApp>, <Zahl> Konten, <Zahl> Kalender.
> **Noch offen:** <Punkte mit OFFEN, je Punkt ein paar Wörter>. Ich frage beim nächsten Abgleich danach.
>
> **Das kann ich jetzt**
>
> | Bereich | Was ich mache | Zum Beispiel |
> |---|---|---|
> | Mail | Posteingang sichten, suchen, zusammenfassen, Antworten als Entwurf | "Was ist neu in Mail?" |
> | Kalender | Überblick, Termine eintragen und verschieben | "Trag Zahnarzt am Dienstag um 9 ein." |
> | WhatsApp | Neues zusammenfassen, Antworten als Entwurf im Chat | "Was hat Anna geschrieben?" |
> | iMessage | lesen, Antworten vorbereiten | "Antworte Ben: passt, bis Samstag." |
> | Notizen | finden, anlegen, Übersichten für unterwegs | "Leg eine Packliste für den Urlaub an." |
> | Erinnerungen | anlegen, abhaken, offene Aufgaben | "Erinnere mich Freitag an die Steuer." |
> | Kontakte | Adresse, Telefon, Geburtstag nachsehen | "Wann hat Anna Geburtstag?" |
> | Tagesstart | Termine, Neues aus allen Kanälen und Aufgaben in einem Überblick, mit Vorschlägen | "Tagesstart" oder "Wochenstart" |
> | Dokumente | an einer Arbeitskopie bearbeiten, ins Original erst auf dein Wort übertragen | "Kürz Folie 3 in meiner Präsentation." |
> | Kontext | Neues merken, monatlich abgleichen | "Merk dir: Ben ist jetzt bei der Feuerwehr." |
> | Feedback | Fehler und Wünsche sammeln, als Mail-Entwurf an den Betreuer | "Feedback: Die Erinnerung kam ohne Uhrzeit." |
>
> **Was ich nie ohne dein Ja tue:** senden, Termine mit anderen anlegen, etwas veröffentlichen oder bezahlen. Löschen tue ich gar nicht.
>
> **So holst du am meisten raus**
> - Sag, was am Ende rauskommen soll: Entwurf, Liste, Termin.
> - Kurz reicht. Fehlt etwas, frage ich nach.
> - Korrigiere direkt: "kürzer", "herzlicher", "ohne den zweiten Satz".
> - Mit "merk dir" behalte ich einen Fakt dauerhaft.
>
> **Bereiche verbinden**
> - "Was steht diese Woche an, und wem muss ich noch antworten?"
> - "Anna schlägt in WhatsApp zwei Termine vor. Prüf meinen Kalender und antworte mit dem passenden."
> - "Mach aus der Mail von Ben eine Erinnerung für Donnerstag."
>
> Arbeite jetzt die Prüfliste unten ab und starte danach eine neue Aufgabe im Projekt, dann gilt alles, was wir eingerichtet haben. Viel Freude, ich bin bereit!
