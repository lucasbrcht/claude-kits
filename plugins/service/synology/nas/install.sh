#!/bin/bash
# install.sh: richtet das Prüfskript für den MCP-Server synology auf der DiskStation ein (Plugin service).
#
# Läuft einmal als root, gestartet vom Nutzer im Terminal mit seinem eigenen Admin-Konto. Die Befehle dafür gibt
# synology_start.py --einrichten am Mac aus:
#   1. Ordner claude-gate-neu mit diesem Skript, eingang.sh, gate.sh, VERSION, lesen.pub, schreiben.pub (optional)
#      und netz in das Home des Admin-Kontos kopieren,
#   2. sudo bash ~/claude-gate-neu/install.sh
#
# Was es tut, jeder Schritt erst nach den Prüfungen davor und beliebig oft wiederholbar:
#   - prüft: läuft als root, Benutzer claude gibt es, er ist in administrators (DSM erlaubt SSH nur Admins), hat
#     ein Home und eine Shell, /etc/sudoers liest /etc/sudoers.d, Schlüssel und Heimnetz haben die richtige Form,
#   - legt /volume1/@claude-gate an (root, 755, kein freigegebener Ordner) und kopiert eingang.sh, gate.sh und
#     VERSION hinein (root, 755 und 644),
#   - schreibt /etc/sudoers.d/claude-gate (root, 440): claude darf genau gate.sh als root starten, ohne Passwort,
#     mit leerer Umgebung. Vorher Prüfung mit visudo, ein kaputtes sudoers sperrte sudo für alle,
#   - schreibt die authorized_keys von claude neu (root, 644, Ordner .ssh root 755): je Schlüssel der erzwungene
#     Befehl eingang.sh mit Rolle, nur aus dem Heimnetz, ohne Terminal, Weiterleitung und eigene Startdateien.
#     Andere Schlüssel von claude fallen dabei weg, das Konto ist nur für Claude da,
#   - Selbsttest: nas_status mit Rolle lesen als claude,
#   - löscht danach nur die eigenen Dateien in claude-gate-neu und den leeren Ordner.
# Es ändert nichts an DSM, an Paketen, Freigaben oder anderen Benutzern.
#
# Rückbau von Hand als root: rm /etc/sudoers.d/claude-gate, rm -r /volume1/@claude-gate, die authorized_keys von
# claude leeren, Benutzer claude in DSM löschen oder deaktivieren.
#
# Tests am Mac setzen INSTALL_WURZEL. Dann läuft es ohne root, alle Pfade liegen unter diesem Ordner und chown
# entfällt. Als root wirkt die Variable nie.

set -f -u
umask 022
export LC_ALL=C
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

QUELLE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
W=""
TEST=false
if [ "$(id -u)" != 0 ] && [ -n "${INSTALL_WURZEL:-}" ]; then
  W=$INSTALL_WURZEL
  TEST=true
fi

ZIEL=/volume1/@claude-gate
SUDOERS=/etc/sudoers.d/claude-gate
NUTZER=claude

schritt() { printf '%s\n' "- $*"; }
halt() { printf 'ABBRUCH: %s\nNichts weiter geändert.\n' "$*" >&2; exit 1; }
besitzer() { if [ "$TEST" = false ]; then chown "$@"; fi; }

# ---------- Prüfungen ----------

if [ "$TEST" = false ] && [ "$(id -u)" != 0 ]; then
  halt "Bitte als root starten: sudo bash $QUELLE/install.sh"
fi

for f in eingang.sh gate.sh VERSION lesen.pub netz; do
  [ -f "$QUELLE/$f" ] || halt "$f fehlt neben install.sh ($QUELLE)."
done

# DSM übernimmt die Schreibweise aus der Anlage (etwa Claude). Gesucht wird ohne Unterschied von Groß und Klein, danach
# gilt der genaue Name für sudoers, Gruppe und Selbsttest.
ZEILE=$(awk -F: -v n="$NUTZER" 'tolower($1) == n' "$W/etc/passwd")
[ -n "$ZEILE" ] || halt "Benutzer $NUTZER fehlt. In DSM unter Systemsteuerung > Benutzer anlegen."
[ "$(printf '%s\n' "$ZEILE" | wc -l | tr -d ' ')" = 1 ] || halt "Mehrere Benutzer namens $NUTZER in verschiedener Schreibweise."
NUTZER=$(printf '%s' "$ZEILE" | awk -F: '{ print $1 }')
[[ $NUTZER =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,31}$ ]] || halt "Der Name des Benutzers hat unerwartete Zeichen."
HEIM=$(printf '%s' "$ZEILE" | awk -F: '{ print $6 }')
SCHALE=$(printf '%s' "$ZEILE" | awk -F: '{ print $7 }')
case $SCHALE in
  /bin/sh|/bin/bash|/bin/ash) ;;
  *) halt "$NUTZER hat keine Shell ($SCHALE). DSM gibt sie Mitgliedern von administrators, Gruppe prüfen." ;;
esac
awk -F: -v n="$(printf '%s' "$NUTZER" | tr 'A-Z' 'a-z')" '$1 == "administrators" { k = split($4, m, ","); for (i = 1; i <= k; i++) if (tolower(m[i]) == n) f = 1 }
  END { exit f ? 0 : 1 }' "$W/etc/group" \
  || halt "$NUTZER ist nicht in der Gruppe administrators. DSM erlaubt SSH nur Admins."
[ -n "$HEIM" ] && [ -d "$W$HEIM" ] || halt "Home von $NUTZER fehlt ($HEIM). In DSM den Benutzer-Home-Dienst aktivieren."

grep -E -q '^[#@]includedir[[:space:]]+/etc/sudoers\.d[[:space:]]*$' "$W/etc/sudoers" \
  || halt "/etc/sudoers liest /etc/sudoers.d nicht ein. Ohne diese Zeile geht es nicht, /etc/sudoers bleibt unberührt."

SCHLUESSEL_RE='^ssh-ed25519 [A-Za-z0-9+/]{60,80}={0,2}$'
# schluessel <datei>: setzt S auf Typ und Schlüssel ohne Kommentar, geprüft. Direkt aufrufen, nicht in $( ).
schluessel() {
  S=$(awk 'NF >= 2 { print $1, $2; exit }' "$1")
  [[ $S =~ $SCHLUESSEL_RE ]] || halt "$(basename "$1") ist kein ed25519-Schlüssel in einer Zeile."
}
schluessel "$QUELLE/lesen.pub"
LESEN=$S
SCHREIBEN=""
if [ -f "$QUELLE/schreiben.pub" ]; then
  schluessel "$QUELLE/schreiben.pub"
  SCHREIBEN=$S
  [ "$SCHREIBEN" != "$LESEN" ] || halt "Lese- und Schreibschlüssel sind gleich, es braucht zwei verschiedene."
fi

NETZ=$(tr -d ' \n\r\t' < "$QUELLE/netz")
NETZ_RE='^[0-9]{1,3}(\.[0-9]{1,3}){3}(/[0-9]{1,2})?(,[0-9]{1,3}(\.[0-9]{1,3}){3}(/[0-9]{1,2})?){0,4}$'
[[ $NETZ =~ $NETZ_RE ]] || halt "netz ist kein Heimnetz wie 192.168.1.0/24 (bis zu fünf, mit Komma getrennt)."

[ "$(head -c 3 "$QUELLE/gate.sh")" = '#!/' ] || halt "gate.sh sieht nicht wie ein Skript aus."
[ "$(head -c 3 "$QUELLE/eingang.sh")" = '#!/' ] || halt "eingang.sh sieht nicht wie ein Skript aus."
VERSION=$(tr -cd '0-9.' < "$QUELLE/VERSION")
[ -n "$VERSION" ] || halt "VERSION ist leer."

printf 'Prüfskript %s für %s, Heimnetz %s\n' "$VERSION" "$NUTZER" "$NETZ"

# ---------- Ordner und Skripte ----------

mkdir -p "$W$ZIEL"
besitzer root:root "$W$ZIEL"
chmod 755 "$W$ZIEL"
for f in eingang.sh gate.sh VERSION; do
  cp "$QUELLE/$f" "$W$ZIEL/.$f.neu"
  besitzer root:root "$W$ZIEL/.$f.neu"
  if [ "$f" = VERSION ]; then chmod 644 "$W$ZIEL/.$f.neu"; else chmod 755 "$W$ZIEL/.$f.neu"; fi
  mv -f "$W$ZIEL/.$f.neu" "$W$ZIEL/$f"
done
schritt "$ZIEL mit eingang.sh, gate.sh und VERSION (root, 755)"

# ---------- sudoers ----------

NEU=$W/etc/sudoers.d/.claude-gate.neu   # mit Punkt: sudo liest die Datei so noch nicht
printf 'Defaults:%s env_reset, !requiretty\n%s ALL=(root) NOPASSWD: %s/gate.sh\n' "$NUTZER" "$NUTZER" "$ZIEL" > "$NEU"
besitzer root:root "$NEU"
chmod 440 "$NEU"
VISUDO=""
for p in /usr/sbin/visudo /usr/bin/visudo /sbin/visudo /bin/visudo; do
  if [ -x "$W$p" ]; then VISUDO=$W$p; break; fi
done
if [ -n "$VISUDO" ]; then
  "$VISUDO" -cf "$NEU" >/dev/null || { rm -f "$NEU"; halt "visudo lehnt die neue sudoers-Zeile ab."; }
  schritt "sudoers mit visudo geprüft"
else
  schritt "visudo fehlt, sudoers hat die feste Form aus diesem Skript"
fi
mv -f "$NEU" "$W$SUDOERS"
schritt "$SUDOERS (440): $NUTZER darf nur $ZIEL/gate.sh als root starten"

# ---------- authorized_keys ----------

OPTIONEN='no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-user-rc'
# restrict sperrt auch künftige Weiterleitungen, ab OpenSSH 7.2
SSH_V=$(ssh -V 2>&1 | sed -n 's/^OpenSSH_\([0-9]*\)\.\([0-9]*\).*/\1 \2/p')
if [ -n "$SSH_V" ] && [ "${SSH_V% *}" -gt 7 -o \( "${SSH_V% *}" -eq 7 -a "${SSH_V#* }" -ge 2 \) ]; then
  OPTIONEN="restrict,$OPTIONEN"
fi
zeile() {  # zeile <rolle> <schlüssel>
  printf 'command="%s/eingang.sh %s",from="%s",%s %s claude-%s\n' "$ZIEL" "$1" "$NETZ" "$OPTIONEN" "$2" "$1"
}
SSH_ORDNER=$W$HEIM/.ssh
mkdir -p "$SSH_ORDNER"
{
  zeile lesen "$LESEN"
  [ -z "$SCHREIBEN" ] || zeile schreiben "$SCHREIBEN"
} > "$SSH_ORDNER/.authorized_keys.neu"
besitzer root:root "$SSH_ORDNER" "$SSH_ORDNER/.authorized_keys.neu"
chmod 755 "$SSH_ORDNER"
chmod 644 "$SSH_ORDNER/.authorized_keys.neu"
mv -f "$SSH_ORDNER/.authorized_keys.neu" "$SSH_ORDNER/authorized_keys"
# sshd nimmt Schlüssel nur an, wenn das Home nicht für andere beschreibbar ist
chmod go-w "$W$HEIM"
if [ -n "$SCHREIBEN" ]; then
  schritt "authorized_keys von $NUTZER: Leseschlüssel und Schreibschlüssel, nur aus $NETZ"
else
  schritt "authorized_keys von $NUTZER: Leseschlüssel, nur aus $NETZ"
fi

# ---------- Selbsttest ----------

if [ "$TEST" = false ]; then
  printf '\nSelbsttest als %s mit Rolle lesen:\n' "$NUTZER"
  sudo -u "$NUTZER" env SSH_ORIGINAL_COMMAND=nas_status "$ZIEL/eingang.sh" lesen | head -n 4
fi

# ---------- Aufräumen ----------

# nur im kopierten Ordner claude-gate-neu, nie im Plugin selbst
if [ "$(basename "$QUELLE")" = claude-gate-neu ]; then
  for f in install.sh eingang.sh gate.sh VERSION lesen.pub schreiben.pub netz; do
    rm -f "$QUELLE/$f"
  done
  rmdir "$QUELLE" 2>/dev/null || true
fi

printf '\nFertig. Benutzer auf der DiskStation: %s. Am Mac geht es mit synology_start.py --pruefen weiter.\n' "$NUTZER"
