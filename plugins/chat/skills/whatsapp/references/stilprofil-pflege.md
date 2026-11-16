# WhatsApp: Stilprofil erstellen oder auffrischen

Nur lesen, wenn das Stilprofil fehlt oder der Nutzer es neu erstellen oder auffrischen will. In Cowork und im Code-Tab gleich, über die Werkzeuge.

1. `chat_stilprofil` mit `stilprobe` 200: eigene Nachrichten mit Statistik (braucht die `config.json` von `chat` im Datenordner).
2. Das Profil mit diesen Abschnitten schreiben: Grundton, Länge und Rhythmus, Zeichensetzung und Schreibweise, Emojis und Smileys, typische Wendungen, je Gegenüber (Partnerin oder Partner, Familie, Freunde, Gruppen, Dienstleister), Nie verwenden, Belege (Zahlen aus der Statistik), Notizen des Nutzers. Ein vorhandenes Profil vorher mit `chat_stilprofil` lesen, die Notizen des Nutzers bleiben.
3. Höchstens 60 Zeilen, als Beispiele nur kurze eigene Nachrichten ohne Namen Dritter. Keine Gedankenstriche oder Auslassungspunkte im Profil selbst.
4. Dem Nutzer zeigen, Korrekturen unter Notizen des Nutzers eintragen.
5. Speichern mit `einstellungen_schreiben` aus dem Plugin `apple`: `plugin` chat, `stilprofil` chat, `text` das ganze Profil (Dialog am Mac). Es landet in `~/Library/Application Support/Claude Kits/chat/style/profil.md`, dort liest `chat_stilprofil`.
