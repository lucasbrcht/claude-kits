#!/bin/bash
# eingang.sh: erzwungener Befehl für den Benutzer claude auf der DiskStation (Plugin service des Pakets claude-kits).
#
# Steht in der authorized_keys von claude vor jedem Schlüssel:
#   command="/volume1/@claude-gate/eingang.sh lesen",...      Leseschlüssel
#   command="/volume1/@claude-gate/eingang.sh schreiben",...  Schreibschlüssel
# Die Rolle kommt also aus dem Schlüssel, nie aus der Anfrage.
#
# SSH legt den gewünschten Befehl des Macs in SSH_ORIGINAL_COMMAND ab. Dieses Skript prüft ihn streng und ruft dann
# gate.sh über sudo mit einzelnen Argumenten auf:
# - höchstens 300 Zeichen, höchstens 8 Wörter mit je genau einem Leerzeichen dazwischen,
# - das erste Wort ist ein Verb aus Kleinbuchstaben und _, die anderen nur aus A-Z a-z 0-9 . _ : / = -,
# - kein Wort beginnt mit - und keins enthält .. (kein Schalter, kein Weg nach oben).
# Kein eval, keine Shell auf dem Text, kein Globbing. sudo setzt die Umgebung zurück, deshalb gehen die Wörter als
# Argumente weiter und nicht als Variable. gate.sh prüft alles noch einmal.
#
# Tests am Mac setzen GATE_WURZEL. Die Variable gilt nur, wenn das Skript nicht am festen Ort liegt.

set -f -u
export LC_ALL=C
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

ORT_FEST=/volume1/@claude-gate
SELBST=${BASH_SOURCE[0]}
W=""
ORT=$ORT_FEST
if [ "$SELBST" != "$ORT_FEST/eingang.sh" ] && [ -n "${GATE_WURZEL:-}" ]; then
  W=$GATE_WURZEL
  ORT=$(cd "$(dirname "$SELBST")" && pwd)
fi
GATE=$ORT/gate.sh
SUDO=$W/usr/bin/sudo
ROLLE=${1:-}

protokoll() {
  local p
  for p in /usr/bin/logger /bin/logger; do
    if [ -x "$W$p" ]; then "$W$p" -t claude-gate "$*" 2>/dev/null || true; return 0; fi
  done
}

# abgelehnt <art> <text>: Fehler als JSON, ins Systemlog ohne den abgelehnten Text, Ende mit Code 2
abgelehnt() {
  printf '{"art":"fehler","code":"%s","text":"%s"}\n{"art":"ende","code":2}\n' "$1" "$2"
  protokoll "eingang abgelehnt rolle=$ROLLE grund=$1 laenge=${#BEFEHL}"
  exit 2
}

BEFEHL=${SSH_ORIGINAL_COMMAND-}

case $ROLLE in
  lesen|schreiben) ;;
  *) ROLLE=unbekannt; abgelehnt rolle "Rolle unbekannt, authorized_keys pruefen" ;;
esac

[ -n "$BEFEHL" ] || abgelehnt leer "Kein Befehl. Erwartet: <verb> [schluessel=wert ...]"
[ ${#BEFEHL} -le 300 ] || abgelehnt zu_lang "Befehl laenger als 300 Zeichen"
MUSTER='^[a-z_]{1,40}( [A-Za-z0-9._:/=-]{1,200}){0,7}$'
[[ $BEFEHL =~ $MUSTER ]] || abgelehnt zeichen "Nur ein Verb und bis zu 7 Woerter aus A-Z a-z 0-9 . _ : / = - mit je einem Leerzeichen"

IFS=' '
# shellcheck disable=SC2086
set -- $BEFEHL
unset IFS
for wort in "$@"; do
  case $wort in
    -*|*..*) abgelehnt wort "Ein Wort beginnt mit - oder enthaelt .." ;;
  esac
done

[ -x "$SUDO" ] || abgelehnt sudo "sudo fehlt"
"$SUDO" -n -l "$GATE" >/dev/null 2>&1 \
  || abgelehnt sudo "sudo fuer gate.sh fehlt, etwa nach einem DSM-Update. install.sh erneut ausfuehren"

exec "$SUDO" -n "$GATE" "$ROLLE" "$@"
