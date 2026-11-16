# Mail: Signatur einrichten und Stilprofil auffrischen

Selten gebraucht, deshalb nicht im Skill `mail` selbst. `config.json` (Abschnitt `mail`) und `style/` liegen im Datenordner `~/Library/Application Support/Claude Kits/apple/`.

## Stilprofil erstellen oder auffrischen

In Cowork und im Code-Tab gleich, über die Werkzeuge:

1. `mail_stilprofil` mit `profil` und `stilprobe` 40: wertet die neuesten gesendeten Mails aus (ohne Zitate und Signatur, Adressen, Nummern und Namen ersetzt) und gibt Statistik und Beispiele zurück.
2. Daraus das Profil nach `${CLAUDE_PLUGIN_ROOT}/style/profil_vorlage.md` schreiben, jede Aussage belegen, den Abschnitt "Kurzfassung für Exporte" (ohne Namen, Belege, Nummern, Adressen) mitziehen. Ein vorhandenes Profil vorher mit `mail_stilprofil` lesen, die Notizen des Nutzers bleiben.
3. Dem Nutzer zeigen, Korrekturen unter "Notizen des Nutzers" eintragen.
4. Speichern mit `einstellungen_schreiben`, `stilprofil` gleich dem Profil, `text` das ganze Profil (Dialog am Mac).

## Signatur in Apple Mail und am iPhone

Nur im Code-Tab. Hat ein Profil im Abschnitt `mail` die Einträge `signatur_html` und `signatur_footer_html` (üblich im Arbeitsprofil: `style/<profil>/signatur.html` und `style/<profil>/signatur_footer.html`), sind diese Dateien die Quelle der Signaturen in Apple Mail, eine kurze als Standard und eine lange. Ändert sich eine Datei, den Nutzer darauf hinweisen. Erst wenn er die Fassung für Apple Mail haben will: `KITS_DATENORDNER="$HOME/Library/Application Support/Claude Kits/apple" python3 "${CLAUDE_PLUGIN_ROOT}/mail.py" signatur --kopieren` (kurz, mit `--lang` die lange) legt sie in die Zwischenablage (ersetzt deren Inhalt) und ändert nichts in Mail. Der Nutzer fügt sie unter Mail, Einstellungen, Signaturen beim passenden Konto ein, Häkchen "Immer meiner Standardschrift entsprechen" an. Am iPhone auf Wunsch die kurze unter Einstellungen, Apps, Mail, Signatur.
