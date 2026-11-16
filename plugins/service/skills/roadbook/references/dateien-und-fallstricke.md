# Roadbook: Dateiformate, Skriptausgaben und Fallstricke

Lesen beim Anlegen von `roadbook.json` (Schritt 1), beim Schreiben von `auswahl.json` (Schritt 4) und wenn ein Skript abbricht oder Daten fehlen.

## roadbook.json

```json
{
  "titel": "Sugar Gravel 2026",
  "gpx": "~/Library/Mobile Documents/com~apple~CloudDocs/Downloads/<datei>.gpx",
  "onroutemap": "https://onroutemap.de/map/<uuid>",
  "tage": [
    {"datum": "2026-10-09", "start": "06:30", "ende": "22:30", "ziel": [48.8267, 9.0669], "ziel_name": "Ditzingen"},
    {"datum": "2026-10-10", "start": "04:00", "ende": "20:00"}
  ],
  "ignorieren_start_km": 30, "ignorieren_ende_km": 20, "radius_m": 300, "puffer_min": 90,
  "imbiss_ab": "17:00", "sticker_mm": [40, 150], "iphone": "iPhone 16 Pro"
}
```

- Statt `gpx` geht `"komoot": "<Teilen-Link mit share_token>"`: Die Route kommt direkt von Komoot, ohne Export. Ein Kurzlink ohne `/tour/<Nummer>` geht nicht, dann den vollen Link aus dem Browser nehmen.
- Nur die GPX-Datei enthält die Wegpunkte des Veranstalters (Checkpoints), die `route.py` mit km und Planzeit auflistet, bei Rundkurs oder hin und zurück mit jeder Durchfahrt.
- Jeder Tag außer dem letzten braucht `ziel` (oder `ziel_km`), sonst brechen die Skripte mit einer Zeile ab. `ende` ist die Ankunft inkl. Pausen.
- Das Zeitprofil kommt aus den Komoot-Planzeiten (Steigung und Untergrund) und wird je Tag auf Start und Ankunft gestreckt. Ohne Planzeiten rechnet `route.py` mit 20 km/h plus 1 Stunde je 600 Hm.
- Unbekanntes iPhone-Modell: ein bekanntes nennen oder `"iphone_px": [Breite, Höhe]` setzen.

## Was die Skripte ausgeben

- `route.py`: Länge, Tage mit Schnitt und Planzeiten alle 50 km, HINWEIS-Zeilen bei mehrdeutigem oder weit entferntem Ziel.
- `kandidaten.py`: Orte mit Punkten, Lücken über 20 km, ein Stundenraster mit den stärksten Orten je Stunde, offene Radläden und Umweg-Optionen. Eine Lücke bricht nur ein Ort mit einer Option, die zur Planzeit sicher offen ist (ok, Imbiss erst ab `imbiss_ab`). Geprüft wird je Tag in Fahrtrichtung, auch vom Start bis zum ersten Ort und vom letzten bis zur Ankunft. An einer Übernachtung (2 km vor und hinter dem Zielpunkt) steht jeder Laden zweimal da: zur Ankunft am Abend und zur Abfahrt am Morgen. Fehlt eine Datei aus `daten.py`, steht oben eine WARNUNG, ohne `food.json` bricht das Skript ab.
- Alle Abrufe laufen über `curl` mit Wiederholung, weil Python über den Sandbox-Proxy große Antworten abbricht.

## auswahl.json

Symbole: `laden`, `automat`, `baecker`, `imbiss`, `tanke`, `rad`. `wichtig` nur bei den grauen Stopps (Grund als Text), `schlaf` beim Übernachtungsort, `umweg_m` beim Umweg-Stopp. `kurz` ist der Name für Sticker und Wallpaper (höchstens ca. 14 Zeichen, Stuttgart-West als S-West). `quelle` je Option: `google`, wenn Google die Zeiten bestätigt hat, sonst `osm`. `tag` (1 = erster Tag) nur, wenn ein Stopp an einer Übernachtung zu einem anderen Tag gehört, als sein km sagt, etwa das Abendessen hinter dem Zielpunkt. Ein Schlaf-Stopp dort zählt von selbst zum Abend.

```json
{"stopps": [
  {"km": 122.1, "ort": "Reichenbach an der Fils", "kurz": "Reichenbach", "wichtig": "vor der Lücke",
   "optionen": [{"symbol": "laden", "name": "EDEKA Daiber", "adresse": "Olgastraße 14, Reichenbach an der Fils", "zeiten": "bis 21", "abstand_m": 100, "quelle": "google"}]},
  {"km": 282.2, "ort": "Ditzingen", "kurz": "Ditzingen", "wichtig": "Abendessen und Schlafen", "schlaf": true, "optionen": []},
  {"km": 460.5, "ort": "Wurmlingen (Rottenburg)", "kurz": "Wurmlingen", "umweg_m": 350, "optionen": []}
]}
```

## Fallstricke

- Overpass antwortet ohne User-Agent mit 406, die Skripte setzen ihn. Ortsnamen kommen nur mit `out;` samt Koordinaten. Abends ist Overpass oft überlastet: nur den fehlenden Teil neu laden (`daten.py <cfg> places`).
- OSM-Zeiten sind oft veraltet oder fehlen (ein Drittel ohne Angabe). Die Google-Prüfung ist Pflicht für alles, was auf den Sticker kommt.
- Google kennt Läden unter anderem Namen als OSM, bei Treffern immer Name und Adresse vergleichen.
- Komoot und OnRouteMap messen die Strecke leicht verschieden (556,5 zu 557,2 km). Für das Roadbook zählt die GPX.
- Der eingebaute Browser nimmt höchstens 25 Aktionen je Batch.
