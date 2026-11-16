#!/bin/bash
# Gesamtblick über Apple Kalender (icalBuddy), gruppiert nach Kalender. Einstellungen aus dem Abschnitt kalender der
# config.json.
# Aufruf: bash calendar_today.sh [N] [--all]   heute plus N Tage (Standard 1: heute und morgen, 7 ergibt 8 Kalendertage)
#         bash calendar_today.sh --list        alle Kalender mit Typ (etwa CalDAV, Exchange, Local), ohne private
# Ohne --all fehlen hidden_calendars, private_calendars fehlen immer. Kalender aus dedupe_calendars erscheinen nur
# einmal, auch wenn mehrere Konten sie liefern (Geburtstage). Kalender aus nur_belegt zeigen nur Zeiten, nie Titel
# oder Ort. Fehlt arbeitskalender in Apple Kalender, steht vorn eine Warnzeile. Exit 2 bei falschem Aufruf, 1 bei jedem
# anderen Fehler.
set -o pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# Der MCP-Server übergibt den festen Datenordner, erlaubt nur unter denselben Wurzeln wie kit_basis.datenordner
DATEN="$DIR"
if [ -n "$KITS_DATENORDNER" ]; then
  HEIM=$(eval echo "~$(id -un)")
  case "$KITS_DATENORDNER" in
    "$HEIM/Library/Application Support/Claude Kits"|"$HEIM/Library/Application Support/Claude Kits/"*|"$HEIM/Claude Kits"|"$HEIM/Claude Kits/"*)
      case "$KITS_DATENORDNER" in *..*) echo "KITS_DATENORDNER mit .. ist nicht erlaubt." >&2; exit 1 ;; esac
      DATEN="$KITS_DATENORDNER" ;;
    *) echo "KITS_DATENORDNER liegt nicht unter ~/Library/Application Support/Claude Kits oder ~/Claude Kits." >&2; exit 1 ;;
  esac
fi
CFG="$DATEN/config.json"
[ -f "$CFG" ] || { echo "config.json fehlt in $DATEN" >&2; exit 1; }
command -v icalBuddy >/dev/null || { echo "icalBuddy fehlt: brew install ical-buddy" >&2; exit 1; }

# Argumente vor jedem Zugriff prüfen: ein Tippfehler wie 7abc oder morgen läuft nie still als Standard
list=0; all=0; days=1
for a in "$@"; do
  case "$a" in
    --list) list=1 ;;
    --all) all=1 ;;
    ''|*[!0-9]*) echo "Unbekanntes Argument '$a'. Aufruf: bash calendar_today.sh [Tage] [--all] oder --list" >&2; exit 2 ;;
    *) { [ ${#a} -le 3 ] && [ $((10#$a)) -le 366 ]; } || { echo "Höchstens 366 Tage." >&2; exit 2; }
       days=$((10#$a)) ;;
  esac
done

# Ohne Kalenderzugriff (Sandbox, fehlende Freigabe) liefert icalBuddy still nichts. Dann laut abbrechen,
# damit eine leere Ausgabe nie als "keine Termine" gelesen wird. Zeilen prüft case statt grep mit Here-String: Dafür
# legt /bin/bash 3.2 eine Temp-Datei an, das scheitert in der Sandbox (Tests).
CALS=$(icalBuddy calendars 2>/dev/null)
case $'\n'"$CALS" in
  *$'\n•'*) ;;
  *) echo "Kein Zugriff auf Apple Kalender. Lief der Befehl in der Sandbox? Dann als eigenen Befehl mit absolutem Pfad aufrufen: bash \"$DIR/calendar_today.sh\", ohne cd davor und ohne Pipe oder Umleitung. Sonst Systemeinstellungen > Datenschutz & Sicherheit > Kalender prüfen." >&2
     exit 1 ;;
esac

# Einstellungen aus config.json in einem Aufruf, eine Zeile je Wert: kommagetrennt für icalBuddy -ec,
# mit Trennzeichen \x1f für die Filter unten
CFG_OUT=$(python3 -c '
import json, sys
try:
    c = json.load(open(sys.argv[1], encoding="utf-8"))
except ValueError as e:
    sys.exit(f"config.json ist kein gültiges JSON: {e}")
c = c.get("kalender") if isinstance(c, dict) else None
if not isinstance(c, dict):
    sys.exit("config.json: Abschnitt kalender fehlt oder ist kein Objekt.")
def namen(schluessel, standard):
    v = c.get(schluessel, standard)
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        sys.exit(f"config.json: {schluessel} muss eine Liste von Kalendernamen sein.")
    return [x.replace("\n", " ") for x in v]
priv, hidden = namen("private_calendars", []), namen("hidden_calendars", [])
arbeit = c.get("arbeitskalender", "")
if not isinstance(arbeit, str):
    sys.exit("config.json: arbeitskalender muss ein Kalendername sein.")
print(",".join(priv)); print(",".join(hidden)); print("\x1f".join(priv)); print("\x1f".join(hidden))
print("\x1f".join(namen("dedupe_calendars", ["Geburtstage"]))); print("\x1f".join(namen("nur_belegt", [])))
print(arbeit.replace("\n", " "))
' "$CFG") || exit 1
{ IFS= read -r PRIVATE; IFS= read -r HIDDEN; IFS= read -r PRIV_SEP; IFS= read -r HID_SEP; IFS= read -r DEDUPE_SEP
  IFS= read -r BELEGT_SEP; IFS= read -r ARBEIT; } < <(printf '%s\n' "$CFG_OUT")

# Kalendernamen kommen über ENVIRON an awk, nicht mit -v: Das läse Backslashes als Escape, ein privater Kalender mit
# \ im Namen erschiene sonst (Review 21.10.2026).
if [ $list -eq 1 ]; then
  # Unter jedem "• Name" liefert icalBuddy eingerückt "type: <Typ>" (und die UID, die hier wegfällt)
  printf '%s\n' "$CALS" | KAL_PRIV="$PRIV_SEP" awk '
    BEGIN { n = split(ENVIRON["KAL_PRIV"], p, "\x1f"); for (i = 1; i <= n; i++) bad[p[i]] = 1 }
    function zeige() { if (name != "" && !(name in bad)) print name (typ != "" ? " (" typ ")" : "") }
    /^• / { zeige(); name = $0; sub(/^• /, "", name); typ = ""; next }
    /^[ \t]+type:/ { typ = $0; sub(/^[ \t]+type:[ \t]*/, "", typ) }
    END { zeige() }'
  exit
fi

# Genau die Zeile "• Name", der Name in Anführungszeichen zählt wörtlich, auch mit * oder ? darin
if [ -n "$ARBEIT" ]; then
  case $'\n'"$CALS"$'\n' in
    *$'\n'"• $ARBEIT"$'\n'*) ;;
    *) echo "Hinweis: Der Arbeitskalender '$ARBEIT' fehlt in Apple Kalender. Dieser Gesamtblick zeigt keine Arbeitstermine, sie über den Connector prüfen." ;;
  esac
fi

opts=(-nrd -sc -iep "datetime,title,location" -po "datetime,title,location" -df "%a %d.%m." -tf "%H:%M" -b "- ")
ec="$PRIVATE"
[ $all -eq 0 ] && ec="$PRIVATE,$HIDDEN"
ec="${ec#,}"; ec="${ec%,}"
[ -n "$ec" ] && opts+=(-ec "$ec")
befehl="eventsToday"
[ "$days" -gt 0 ] && befehl="eventsToday+$days"

# Nachfilter. Kopfzeile eines Kalenderblocks ist "Name:" ohne Einrückung, darunter eine Zeile nur aus Bindestrichen
# (Trenner von icalBuddy -sc), deshalb läuft die Ausgabe eine Zeile versetzt. Private Kalender hart verwerfen, ohne
# --all auch die ausgeblendeten (icalBuddy -ec scheitert an Leerzeichen im Namen, Prüfung 20.10.2026), dedupe_calendars
# nur einmal zeigen, in nur_belegt je Termin nur die erste Zeile (Datum und Uhrzeit, siehe -po) mit dem Wort belegt.
# Warnungen und Fehler von icalBuddy gehen nach stderr, nie in den Filter: Dort erschienen sie sonst als Terminzeile.
# Bricht icalBuddy ab, endet das Skript laut statt mit "Keine Termine im Zeitraum."
TERMINE=$(icalBuddy "${opts[@]}" "$befehl") || { echo "icalBuddy ist mit Code $? abgebrochen, keine Termine gelesen." >&2; exit 1; }
if [ -n "$TERMINE" ]; then printf '%s\n' "$TERMINE"; fi | KAL_PRIV="$PRIV_SEP" KAL_HID="$HID_SEP" \
  KAL_EINMAL="$DEDUPE_SEP" KAL_BELEGT="$BELEGT_SEP" awk -v all="$all" '
  BEGIN {
    n = split(ENVIRON["KAL_PRIV"], p, "\x1f");   for (i = 1; i <= n; i++) bad[p[i]] = 1
    if (all == 0) { n = split(ENVIRON["KAL_HID"], p, "\x1f"); for (i = 1; i <= n; i++) bad[p[i]] = 1 }
    n = split(ENVIRON["KAL_EINMAL"], p, "\x1f"); for (i = 1; i <= n; i++) einmal[p[i]] = 1
    n = split(ENVIRON["KAL_BELEGT"], p, "\x1f"); for (i = 1; i <= n; i++) nurzeit[p[i]] = 1
    n = split("Mo Di Mi Do Fr Sa So Mon Tue Wed Thu Fri Sat Sun at", p, " ")
    for (i = 1; i <= n; i++) zeitwort[p[i]] = 1
  }
  # Zeile eines Termins in nur_belegt: nur Wochentag, Datum, at, Uhrzeit und Bindestrich, dazu mindestens ein Datum oder
  # eine Uhrzeit. Alles andere, etwa ein Titel mit Zeilenumbruch, zeigt nur "- belegt" (Review 21.10.2026).
  function nur_zeit(rest,   t, n, i, w, zeit) {
    n = split(rest, t, " ")
    for (i = 1; i <= n; i++) {
      w = t[i]; sub(/[.,]$/, "", w)
      if (t[i] ~ /^[0-9][0-9]?\.[0-9][0-9]?\.([0-9][0-9]([0-9][0-9])?)?$/ || t[i] ~ /^[0-9][0-9]?:[0-9][0-9]$/) zeit = 1
      else if (!(w in zeitwort) && t[i] != "-") return 0
    }
    return zeit
  }
  function aus(z) {
    if (skip) return
    if (!zeiten || z == kopf || z == "" || z ~ /^-+$/) print z
    else if (z ~ /^- /) print (nur_zeit(substr(z, 3)) ? z "  belegt" : "- belegt")
    else return
    if (z != "") gedruckt++
  }
  NR > 1 {
    if ($0 ~ /^-+$/ && vorher ~ /:$/ && vorher !~ /^[ \t-]/) {
      name = vorher; sub(/:$/, "", name)
      skip = (name in bad) || ((name in einmal) && (name in gesehen)); gesehen[name] = 1
      zeiten = (name in nurzeit); kopf = vorher
    }
    aus(vorher)
  }
  { vorher = $0 }
  END { if (NR > 0) aus(vorher); if (!gedruckt) print "Keine Termine im Zeitraum." }'
