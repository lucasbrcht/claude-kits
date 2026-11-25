#!/bin/bash
# gate.sh: Prüfskript auf der DiskStation für den MCP-Server synology (Plugin service des Pakets claude-kits).
#
# Aufruf nur über sudo aus eingang.sh:   gate.sh <rolle> <verb> [schluessel=wert ...]
#
# - Rolle lesen erreicht nur die Leseverben. Rolle schreiben erreicht dazu Neustart, Start und Stopp eines Containers,
#   höchstens 10 je Stunde (Notbremse auf der DiskStation, nicht am Mac). Löschen, Images, Updates und freie Befehle
#   gibt es in keiner Rolle.
# - Jedes Verb hat einen festen Befehl. Argumente sind nur Werte nach engen Mustern aus einer festen Liste von
#   Schlüsseln je Verb. Kein eval, keine Shell auf fremdem Text, kein Globbing (set -f).
# - Container gibt es nur über ihren exakten Namen aus der aktuellen Liste, nie über eine ID.
# - docker inspect läuft nur mit fester Vorlage: Umgebungsvariablen nur als Namen, der Healthcheck ohne Befehl.
# - Texte aus Logs und Aufgaben laufen durch schwaerze: Werte hinter password, token, secret, key und Bearer
#   werden zu ***.
# - Zeitgrenze je Befehl, Ausgabe höchstens 256 KB, Zeilen je Log höchstens 5000.
# - Jede Anfrage steht mit Rolle, Verb, Argumenten und Ergebnis im Systemlog (logger -t claude-gate).
# - Ausgabe: eine JSON-Zeile je Eintrag. Die letzte Zeile ist {"art":"ende","code":N}.
#   Codes: 0 gut, 2 abgelehnt (falsche Eingabe), 3 Befehl gescheitert, 4 Programm fehlt.
#
# Tests am Mac setzen GATE_WURZEL auf einen Ordner mit falschen Programmen und Dateien. Die Variable gilt nur,
# wenn das Skript nicht am festen Ort liegt und nicht als root läuft. Auf der DiskStation wirkt sie nie.

set -f -u
umask 077
export LC_ALL=C
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

ORT_FEST=/volume1/@claude-gate
SELBST=${BASH_SOURCE[0]}
W=""
ORT=$ORT_FEST
if [ "$SELBST" != "$ORT_FEST/gate.sh" ] && [ "$(id -u)" != 0 ] && [ -n "${GATE_WURZEL:-}" ]; then
  W=$GATE_WURZEL
  ORT=$(cd "$(dirname "$SELBST")" && pwd)
fi

MAX_BYTES=262144        # Ausgabe je Verb
MAX_ZEILEN=5000         # Zeilen je Log
ROH_ZEILEN=20000        # so viele Zeilen liest container_log höchstens, für Suche und Zählung
ZEIT=50                 # Sekunden je Befehl, der Mac wartet 60
VERSION=$(head -c 40 "$ORT/VERSION" 2>/dev/null | tr -cd '0-9.')
[ -n "$VERSION" ] || VERSION=unbekannt

LESEVERBEN="nas_status nas_speicher nas_platten nas_log nas_aufgaben nas_pakete nas_sicherheit container_liste container_details container_log container_ereignisse docker_images"
SCHREIBVERBEN="container_neustart container_starten container_stoppen"
SCHREIB_PRO_STUNDE=10   # Notbremse: so viele Aktionen der Rolle schreiben je Stunde, Zähler unter $ORT_FEST/zustand
LOGS="messages kern docker scemd dmesg"

# ---------- Hilfen ----------

# finde <pfad>...: der erste ausführbare Pfad (unter GATE_WURZEL im Test), sonst Code 1
finde() {
  local p
  for p in "$@"; do
    if [ -x "$W$p" ] && [ ! -d "$W$p" ]; then printf '%s' "$W$p"; return 0; fi
  done
  return 1
}

# js <text>: Text als JSON-String, Steuerzeichen fallen weg
js() {
  local s=$1
  s=${s//\\/\\\\}
  s=${s//\"/\\\"}
  s=${s//[$'\001'-$'\037'$'\177']/}
  printf '"%s"' "$s"
}

# zahl <text>: Ziffern oder null
zahl() {
  case $1 in ''|*[!0-9]*) printf 'null' ;; *) printf '%s' "$1" ;; esac
}

protokoll() {
  local p
  p=$(finde /usr/bin/logger /bin/logger) || return 0
  "$p" -t claude-gate "$*" 2>/dev/null || true
}

ROLLE=${1:-}
VERB=${2:-}
if [ $# -ge 2 ]; then shift 2; else shift $#; fi
ARGS=("$@")

ende() {
  printf '{"art":"ende","code":%d}\n' "$1"
  protokoll "rolle=$ROLLE verb=$VERB args=${ARGS[*]+${ARGS[*]}} code=$1"
  exit "$1"
}

# abbruch <code> <art> <text>: Fehler als Daten, dann Ende
abbruch() {
  printf '{"art":"fehler","code":"%s","text":%s}\n' "$2" "$(js "$3")"
  ende "$1"
}

TIMEOUT=$(finde /usr/bin/timeout /bin/timeout) || TIMEOUT=""
# mit_zeit <sekunden> <befehl>...: mit Zeitgrenze, wenn timeout da ist
mit_zeit() {
  local s=$1
  shift
  if [ -n "$TIMEOUT" ]; then "$TIMEOUT" "$s" "$@"; else "$@"; fi
}

# Bibliothek für awk: esc macht einen JSON-String, schwaerze ersetzt Werte hinter Schlüsseln wie password= oder
# token: und hinter Bearer durch ***. \047 ist das einfache Anführungszeichen.
AWK_BIB='
function esc(s) {
  gsub(/\033\[[0-9;?]*[A-Za-z]/, "", s)
  gsub(/\\/, "\\\\", s); gsub(/"/, "\\\"", s); gsub(/\t/, "\\t", s)
  gsub(/[\001-\010\013-\037\177]/, "", s)
  return s
}
function schwaerze(s,    l, aus, ra, la, rb, lb, st, ln, rest) {
  aus = ""
  while (s != "") {
    l = tolower(s)
    ra = match(l, /(passw(or)?d|passwort|kennwort|secret|token|api_?key|apikey|credential|private_?key)[a-z0-9_]*["\047]?[ \t]*[:=][ \t]*["\047]?/); la = RLENGTH
    rb = match(l, /bearer[ \t]+/); lb = RLENGTH
    if (ra == 0 && rb == 0) break
    if (ra == 0 || (rb > 0 && rb < ra)) { st = rb; ln = lb } else { st = ra; ln = la }
    aus = aus substr(s, 1, st + ln - 1)
    rest = substr(s, st + ln)
    if (match(rest, /^[^ \t"\047,;&]+/)) { aus = aus "***"; rest = substr(rest, RLENGTH + 1) }
    s = rest
  }
  return aus s
}
'

# Zeilen filtern, zählen und als JSON ausgeben. Variablen: von, bis (Anfang der ersten Spalte, als Text verglichen),
# suche (klein geschrieben), n (letzte n Treffer), max (Bytes). Am Ende je auffälligem Wort eine Zählung mit erstem
# und letztem Zeitpunkt (erste Spalte) und eine Summe.
AWK_ZEILEN='
BEGIN {
  n = n + 0; max = max + 0
  split("error fatal panic exception traceback critical oom out_of_memory killed sigterm sigkill segfault timeout timed_out unhealthy stopping shutdown found_new", K, " ")
  for (i = 1; i in K; i++) gsub(/_/, " ", K[i])
}
{
  gsub(/\033\[[0-9;?]*[A-Za-z]/, "")   # Farbfolgen weg, sonst klebt etwa [31m am Wort
  if (von != "" && substr($1, 1, length(von)) < von) next
  if (bis != "" && substr($1, 1, length(bis)) > bis) next
  l = tolower($0)
  if (suche != "" && index(l, suche) == 0) next
  gesamt++
  for (i = 1; i in K; i++) {
    if (match(l, "(^|[^a-z])" K[i] "([^a-z]|$)")) {
      anz[K[i]]++
      if (!(K[i] in erst)) erst[K[i]] = $1
      letzt[K[i]] = $1
    }
  }
  puffer[gesamt % n] = substr($0, 1, 2000)
}
END {
  beginn = gesamt - n + 1
  if (beginn < 1) beginn = 1
  start = gesamt + 1
  groesse = 0
  for (i = gesamt; i >= beginn; i--) {
    z[i] = esc(schwaerze(puffer[i % n]))
    if (groesse + length(z[i]) + 25 > max) { gekuerzt = 1; break }
    groesse += length(z[i]) + 25
    start = i
  }
  for (i = start; i <= gesamt; i++) printf "{\"art\":\"zeile\",\"t\":\"%s\"}\n", z[i]
  for (k in anz) printf "{\"art\":\"auffaellig\",\"wort\":\"%s\",\"anzahl\":%d,\"erste\":\"%s\",\"letzte\":\"%s\"}\n", k, anz[k], esc(erst[k]), esc(letzt[k])
  printf "{\"art\":\"summe\",\"treffer\":%d,\"gezeigt\":%d,\"gekuerzt\":%s}\n", gesamt, gesamt - start + 1, (gekuerzt || gesamt - beginn + 1 < gesamt) ? "true" : "false"
}
'

zeilen_json() {  # zeilen_json <von> <bis> <suche> <n>: Zeilen von stdin
  awk -v von="$1" -v bis="$2" -v suche="$3" -v n="$4" -v max="$MAX_BYTES" "$AWK_BIB$AWK_ZEILEN"
}

text_json() {  # Zeilen von stdin als {"art":"zeile"}, geschwärzt, höchstens 2000
  awk -v max="$MAX_BYTES" "$AWK_BIB"'
    NR > 2000 { gekuerzt = 1; exit }
    { z = esc(schwaerze(substr($0, 1, 2000))); groesse += length(z) + 25; if (groesse > max) { gekuerzt = 1; exit }
      printf "{\"art\":\"zeile\",\"t\":\"%s\"}\n", z }
    END { if (gekuerzt) print "{\"art\":\"summe\",\"gekuerzt\":true}" }'
}

# Ausgabe einer festen Docker-Vorlage: Zeilen der Vorlage gehen durch, jede andere Zeile (Fehlertext) wird zur
# Meldung. Höchstens <max> Zeilen.
docker_zeilen() {
  awk -v max="$1" "$AWK_BIB"'
    NR > max { gekuerzt = 1; exit }
    /^\{"art":"/ { print; next }
    { printf "{\"art\":\"meldung\",\"t\":\"%s\"}\n", esc(substr($0, 1, 500)) }
    END { if (gekuerzt) print "{\"art\":\"summe\",\"gekuerzt\":true}" }'
}

# ---------- Argumente ----------

muster() {
  case $1 in
    NAME)  printf '%s' '^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$' ;;
    ZEITD) printf '%s' '^([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(:[0-9]{2})?Z|[0-9]{1,4}[smh])$' ;;
    ZEITL) printf '%s' '^[0-9]{4}-[0-9]{2}-[0-9]{2}(T[0-9]{2}(:[0-9]{2}(:[0-9]{2})?)?)?$' ;;
    ZAHL)  printf '%s' '^[0-9]{1,4}$' ;;
    WORT)  printf '%s' '^[A-Za-z0-9_.-]{1,40}$' ;;
    SEK)   printf '%s' '^[0-9]{1,3}$' ;;
    LOG)   printf '%s' '^(messages|kern|docker|scemd|dmesg)$' ;;
    *)     printf '%s' '^$' ;;
  esac
}

erklaerung() {
  case $1 in
    NAME)  printf 'Containername aus container_liste' ;;
    ZEITD) printf 'Zeit in UTC wie 2026-01-31T10:00Z oder relativ wie 30m, 6h' ;;
    ZEITL) printf 'Ortszeit der DiskStation wie 2026-01-31T10:00 oder 2026-01-31' ;;
    ZAHL)  printf 'Zahl von 1 bis %s' "$MAX_ZEILEN" ;;
    WORT)  printf 'ein Wort aus A-Z, 0-9, _ . - mit höchstens 40 Zeichen' ;;
    SEK)   printf 'Sekunden von 10 bis 600' ;;
    LOG)   printf 'eins von: %s' "$LOGS" ;;
  esac
}

# pruefe_args "<schluessel:typ> ...": jedes Argument ist schluessel=wert, der Schlüssel steht in der Liste und
# kommt nur einmal vor, der Wert passt zum Typ. Fehlertexte nennen nie den Wert.
pruefe_args() {
  local liste=" $1 " a k v typ m gesehen=" "
  for a in ${ARGS[@]+"${ARGS[@]}"}; do
    case $a in
      *=*) ;;
      *) abbruch 2 argument "Argumente haben die Form schluessel=wert. Erlaubt bei $VERB: ${1:-keine}" ;;
    esac
    k=${a%%=*}
    v=${a#*=}
    case $liste in
      *" $k:"*) ;;
      *) abbruch 2 argument "Schlüssel $k gibt es bei $VERB nicht. Erlaubt: ${1:-keine}" ;;
    esac
    case $gesehen in *" $k "*) abbruch 2 argument "Schlüssel $k steht doppelt" ;; esac
    gesehen="$gesehen$k "
    typ=${liste#*" $k:"}
    typ=${typ%% *}
    m=$(muster "$typ")
    [[ $v =~ $m ]] || abbruch 2 argument "Wert für $k passt nicht: $(erklaerung "$typ")"
    if [ "$typ" = ZAHL ] && { [ "$v" -lt 1 ] || [ "$v" -gt "$MAX_ZEILEN" ]; }; then
      abbruch 2 argument "Wert für $k passt nicht: $(erklaerung ZAHL)"
    fi
    if [ "$typ" = SEK ] && { [ "$v" -lt 10 ] || [ "$v" -gt 600 ]; }; then
      abbruch 2 argument "Wert für $k passt nicht: $(erklaerung SEK)"
    fi
  done
}

wert() {  # wert <schluessel> [vorgabe]
  local a
  for a in ${ARGS[@]+"${ARGS[@]}"}; do
    case $a in "$1="*) printf '%s' "${a#*=}"; return 0 ;; esac
  done
  printf '%s' "${2:-}"
}

# ---------- Docker ----------

docker_pfad() {
  DOCKER=$(finde /usr/local/bin/docker /var/packages/ContainerManager/target/usr/bin/docker \
    /var/packages/Docker/target/usr/bin/docker /usr/bin/docker) \
    || abbruch 4 programm "docker nicht gefunden. Ist Container Manager installiert und gestartet?"
}

# container_name: setzt NAME auf den Wert von name, nur wenn genau dieser Name in der Liste aller Container steht.
# Direkt aufrufen, nicht in $( ), sonst geht die Ablehnung in der Variable verloren.
container_name() {
  local n
  NAME=$(wert name)
  [ -n "$NAME" ] || abbruch 2 argument "name fehlt: $(erklaerung NAME)"
  while IFS= read -r n; do
    if [ "$n" = "$NAME" ]; then return 0; fi
  done < <(mit_zeit 20 "$DOCKER" ps -a --format '{{.Names}}' 2>/dev/null)
  abbruch 2 container "Diesen Container gibt es nicht. Namen stehen in container_liste, IDs gelten nicht"
}

# Vorlage für container_liste: nur Zustand und wenige Labels (Watchtower, Compose)
VORLAGE_LISTE='{"art":"container","name":{{json .Name}},"image":{{json .Config.Image}},"status":{{json .State.Status}},"gestartet":{{json .State.StartedAt}},"beendet":{{json .State.FinishedAt}},"exit":{{.State.ExitCode}},"oom":{{.State.OOMKilled}},"neustarts":{{.RestartCount}},"richtlinie":{{json .HostConfig.RestartPolicy.Name}},"health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}},"labels":[{{range $k, $v := .Config.Labels}}{{if or (eq $k "com.centurylinklabs.watchtower.enable") (eq $k "com.centurylinklabs.watchtower.monitor-only") (eq $k "com.docker.compose.project") (eq $k "com.docker.compose.service")}}[{{json $k}},{{json $v}}],{{end}}{{end}}null]}'

# Vorlage für container_details: Positivliste der Felder. Umgebung nur als Namen (Teil vor dem ersten =), Healthcheck
# ohne Befehl, Mounts nur mit Pfaden.
VORLAGE_DETAILS='{"art":"details","name":{{json .Name}},"image":{{json .Config.Image}},"image_id":{{json .Image}},"erstellt":{{json .Created}},"status":{{json .State.Status}},"gestartet":{{json .State.StartedAt}},"beendet":{{json .State.FinishedAt}},"exit":{{.State.ExitCode}},"oom":{{.State.OOMKilled}},"fehler":{{json .State.Error}},"neustarts":{{.RestartCount}},"richtlinie":{{json .HostConfig.RestartPolicy}},"stop_timeout":{{json .Config.StopTimeout}},"stop_signal":{{json .Config.StopSignal}},"speichergrenze":{{json .HostConfig.Memory}},"health":{{if .State.Health}}{"status":{{json .State.Health.Status}},"fehlschlaege":{{json .State.Health.FailingStreak}}}{{else}}null{{end}},"healthcheck":{{if .Config.Healthcheck}}{"intervall":{{json .Config.Healthcheck.Interval}},"timeout":{{json .Config.Healthcheck.Timeout}},"versuche":{{json .Config.Healthcheck.Retries}}}{{else}}null{{end}},"netz":{{json .HostConfig.NetworkMode}},"ports":{{json .NetworkSettings.Ports}},"mounts":[{{range .Mounts}}{"quelle":{{json .Source}},"ziel":{{json .Destination}},"rw":{{json .RW}}},{{end}}null],"labels":[{{range $k, $v := .Config.Labels}}[{{json $k}},{{json $v}}],{{end}}null],"env_namen":[{{range .Config.Env}}{{json (index (split . "=") 0)}},{{end}}null]}'

VORLAGE_EREIGNIS='{"art":"ereignis","zeit":{{json .Time}},"zeit_ns":{{json .TimeNano}},"aktion":{{json .Action}},"name":{{json (index .Actor.Attributes "name")}},"image":{{json (index .Actor.Attributes "image")}},"exit":{{json (index .Actor.Attributes "exitCode")}},"signal":{{json (index .Actor.Attributes "signal")}}}'

VORLAGE_IMAGE='{"art":"image","repo":{{json .Repository}},"tag":{{json .Tag}},"id":{{json .ID}},"erstellt":{{json .CreatedAt}},"groesse":{{json .Size}}}'
VORLAGE_GENUTZT='{"art":"genutzt","name":{{json .Name}},"image_id":{{json .Image}}}'
VORLAGE_DF='{"art":"docker_df","typ":{{json .Type}},"anzahl":{{json .TotalCount}},"aktiv":{{json .Active}},"groesse":{{json .Size}},"freigebbar":{{json .Reclaimable}}}'

# alle_container <vorlage>: docker inspect mit fester Vorlage über alle Container
alle_container() {
  local ids
  ids=$(mit_zeit 20 "$DOCKER" ps -aq --no-trunc 2>/dev/null | tr -cd '0-9a-f\n')
  [ -n "$ids" ] || return 0
  # shellcheck disable=SC2086
  mit_zeit "$ZEIT" "$DOCKER" inspect --format "$1" $ids 2>&1 | docker_zeilen 500
}

# ---------- Verben ----------

v_nas_status() {
  pruefe_args ""
  local modell dsm build fix laufzeit last ram frei temp ssh_v sudoers=false ordner=false erwartet
  modell=$(head -c 100 "$W/proc/sys/kernel/syno_hw_version" 2>/dev/null)
  dsm=$(awk -F'"' '$1 == "productversion=" { print $2 }' "$W/etc.defaults/VERSION" 2>/dev/null)
  build=$(awk -F'"' '$1 == "buildnumber=" { print $2 }' "$W/etc.defaults/VERSION" 2>/dev/null)
  fix=$(awk -F'"' '$1 == "smallfixnumber=" { print $2 }' "$W/etc.defaults/VERSION" 2>/dev/null)
  laufzeit=$(awk '{ printf "%d", $1 }' "$W/proc/uptime" 2>/dev/null)
  last=$(awk '{ print $1, $2, $3 }' "$W/proc/loadavg" 2>/dev/null)
  ram=$(awk '$1 == "MemTotal:" { print $2 }' "$W/proc/meminfo" 2>/dev/null)
  frei=$(awk '$1 == "MemAvailable:" { print $2 }' "$W/proc/meminfo" 2>/dev/null)
  temp=$(awk '{ printf "%d", $1 / 1000 }' "$W/sys/class/thermal/thermal_zone0/temp" 2>/dev/null)
  ssh_v=$(ssh -V 2>&1 | awk '{ sub(/,$/, "", $1); print $1; exit }')
  erwartet=$(sudoers_text)
  if [ -f "$W/etc/sudoers.d/claude-gate" ] && [ "$(cat "$W/etc/sudoers.d/claude-gate")" = "$erwartet" ]; then
    sudoers=true
  fi
  [ -d "$W$ORT_FEST" ] && ordner=true
  printf '{"art":"system","modell":%s,"dsm":%s,"build":%s,"update":%s,"laufzeit_s":%s,"last":%s,"ram_kb":%s,"ram_verfuegbar_kb":%s,"temperatur_c":%s,"openssh":%s,"gate":%s}\n' \
    "$(js "$modell")" "$(js "$dsm")" "$(js "$build")" "$(js "$fix")" "$(zahl "$laufzeit")" "$(js "$last")" \
    "$(zahl "$ram")" "$(zahl "$frei")" "$(zahl "$temp")" "$(js "$ssh_v")" "$(js "$VERSION")"
  printf '{"art":"pruefung","sudoers":%s,"ordner":%s,"rolle":%s}\n' "$sudoers" "$ordner" "$(js "$ROLLE")"
  volumes
  if DOCKER=$(finde /usr/local/bin/docker /var/packages/ContainerManager/target/usr/bin/docker \
      /var/packages/Docker/target/usr/bin/docker /usr/bin/docker); then
    mit_zeit 20 "$DOCKER" ps -a --format '{{.State}}' 2>/dev/null | sort | uniq -c | \
      awk '$2 ~ /^[a-z]+$/ { printf "{\"art\":\"container_zahl\",\"status\":\"%s\",\"anzahl\":%d}\n", $2, $1 }'
  else
    printf '{"art":"meldung","t":"docker nicht gefunden"}\n'
  fi
  ende 0
}

# Erwarteter Inhalt von /etc/sudoers.d/claude-gate. SUDO_USER setzt sudo selbst auf den aufrufenden Benutzer, DSM
# behält dessen Schreibweise aus der Anlage (etwa Claude).
sudoers_text() {
  local n=${SUDO_USER:-claude}
  [[ $n =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,31}$ ]] || n=claude
  printf 'Defaults:%s env_reset, !requiretty\n%s ALL=(root) NOPASSWD: %s/gate.sh' "$n" "$n" "$ORT_FEST"
}

volumes() {  # Belegung von / und /volumeN in Prozent
  local df
  df=$(finde /bin/df /usr/bin/df) || return 0
  "$df" -P -k 2>/dev/null | awk '
    NR > 1 && ($6 == "/" || $6 ~ /^\/volume[0-9]+$/) {
      p = $5; sub(/%/, "", p)
      # %.0f statt %d: Volumes über 2 TB sprengen in mancher awk eine 32-Bit-Zahl
      printf "{\"art\":\"volume\",\"ort\":\"%s\",\"groesse_kb\":%.0f,\"belegt_kb\":%.0f,\"frei_kb\":%.0f,\"prozent\":%d}\n", $6, $2, $3, $4, p
    }'
}

v_nas_speicher() {
  pruefe_args ""
  volumes
  if [ -r "$W/proc/mdstat" ]; then
    head -n 60 "$W/proc/mdstat" | awk "$AWK_BIB"'NF { printf "{\"art\":\"raid\",\"t\":\"%s\"}\n", esc($0) }'
  fi
  if DOCKER=$(finde /usr/local/bin/docker /var/packages/ContainerManager/target/usr/bin/docker \
      /var/packages/Docker/target/usr/bin/docker /usr/bin/docker); then
    mit_zeit "$ZEIT" "$DOCKER" system df --format "$VORLAGE_DF" 2>&1 | docker_zeilen 20
  fi
  ende 0
}

v_nas_platten() {
  pruefe_args ""
  local smart d geraete="" typ
  smart=$(finde /usr/bin/smartctl /bin/smartctl /usr/sbin/smartctl /usr/syno/bin/smartctl /usr/syno/sbin/smartctl) \
    || abbruch 4 programm "smartctl nicht gefunden"
  set +f
  for d in "$W"/dev/sata[0-9] "$W"/dev/sata[0-9][0-9] "$W"/dev/sd[a-z] "$W"/dev/nvme[0-9]n1; do
    [ -e "$d" ] && geraete="$geraete ${d#"$W"}"
  done
  set -f
  [ -n "$geraete" ] || abbruch 3 geraete "Keine Platten unter /dev gefunden"
  for d in $geraete; do
    typ=""
    case $d in /dev/sata*) typ="-d sat" ;; esac
    # shellcheck disable=SC2086
    mit_zeit 30 "$smart" -H -A $typ "$d" 2>&1 | awk -v geraet="${d#/dev/}" '
      /self-assessment test result:|SMART Health Status:/ { g = $NF }
      $1 ~ /^[0-9]+$/ && NF >= 10 { roh[$1] = $10 }
      END {
        printf "{\"art\":\"platte\",\"geraet\":\"%s\",\"gesund\":\"%s\",\"temperatur_c\":%s,\"betriebsstunden\":%s,\"umgelagert\":%s,\"ausstehend\":%s,\"unkorrigierbar\":%s,\"crc_fehler\":%s}\n",
          geraet, g, w(roh[194]), w(roh[9]), w(roh[5]), w(roh[197]), w(roh[198]), w(roh[199])
      }
      function w(x) { return (x ~ /^[0-9]+$/) ? x : "null" }'
  done
  ende 0
}

# Kandidaten je Log, das erste vorhandene gilt
log_pfad() {
  case $1 in
    messages) finde_datei /var/log/messages ;;
    kern)     finde_datei /var/log/kern.log ;;
    # DSM 7.4 schreibt dockerd nicht ins Systemlog, Kandidaten für Container Manager
    docker)   finde_datei /var/log/packages/ContainerManager.log /var/packages/ContainerManager/var/docker.log \
                /var/packages/ContainerManager/var/log/docker.log /var/log/docker.log \
                /var/packages/Docker/var/docker.log ;;
    scemd)    finde_datei /var/log/scemd.log ;;
  esac
}

finde_datei() {
  local p
  for p in "$@"; do
    if [ -f "$W$p" ]; then printf '%s' "$W$p"; return 0; fi
  done
  return 1
}

# log_lesen <pfad>: gedrehte Fassungen (.N, .N.gz, .N.xz, .N.bz2) von alt nach neu, dann die Datei selbst
log_lesen() {
  local i e f entpacker
  i=20
  while [ $i -ge 1 ]; do
    for e in "" .gz .xz .bz2; do
      f="$1.$i$e"
      [ -f "$f" ] || continue
      case $e in
        "")   cat "$f" ;;
        .gz)  entpacker=$(finde /bin/gzip /usr/bin/gzip) && "$entpacker" -dc "$f" ;;
        .xz)  entpacker=$(finde /bin/xz /usr/bin/xz) && "$entpacker" -dc "$f" ;;
        .bz2) entpacker=$(finde /bin/bzip2 /usr/bin/bzip2) && "$entpacker" -dc "$f" ;;
      esac
    done
    i=$((i - 1))
  done
  cat "$1"
}

v_nas_log() {
  pruefe_args "log:LOG von:ZEITL bis:ZEITL suche:WORT zeilen:ZAHL"
  local log pfad suche n l
  log=$(wert log)
  suche=$(wert suche | tr 'A-Z' 'a-z')
  n=$(wert zeilen 200)
  if [ -z "$log" ]; then
    for l in $LOGS; do
      if [ "$l" = dmesg ]; then
        finde /bin/dmesg /usr/bin/dmesg >/dev/null && printf '{"art":"log","name":"dmesg","da":true}\n'
      elif pfad=$(log_pfad "$l"); then
        printf '{"art":"log","name":"%s","da":true,"bytes":%s}\n' "$l" "$(zahl "$(wc -c < "$pfad" | tr -d ' ')")"
      else
        printf '{"art":"log","name":"%s","da":false}\n' "$l"
      fi
    done
    ende 0
  fi
  if [ "$log" = dmesg ]; then
    # Kernel: nur Zeilen zu Speicher, beendeten Prozessen und Hängern, ohne Zeitfilter
    local dm
    dm=$(finde /bin/dmesg /usr/bin/dmesg) || abbruch 4 programm "dmesg nicht gefunden"
    mit_zeit 20 "$dm" 2>&1 | grep -i -E 'oom|out of memory|killed process|segfault|blocked for more|i/o error|ata[0-9]' \
      | zeilen_json "" "" "$suche" "$n"
    ende 0
  fi
  pfad=$(log_pfad "$log") || abbruch 3 log "Log $log gibt es auf dieser DiskStation nicht"
  log_lesen "$pfad" | zeilen_json "$(wert von)" "$(wert bis)" "$suche" "$n"
  ende 0
}

v_nas_aufgaben() {
  pruefe_args ""
  local p
  p=$(finde /usr/syno/bin/synoschedtask /usr/syno/sbin/synoschedtask) || abbruch 4 programm "synoschedtask nicht gefunden"
  mit_zeit 30 "$p" --get 2>&1 | text_json
  ende 0
}

v_nas_pakete() {
  pruefe_args ""
  local f ordner name
  set +f
  for f in "$W"/var/packages/*/INFO; do
    [ -f "$f" ] || continue
    ordner=${f%/INFO}
    name=${ordner##*/}
    awk -F= -v aktiv="$([ -e "$ordner/enabled" ] && echo true || echo false)" -v name="$name" "$AWK_BIB"'
      $1 == "version" || $1 == "displayname" { v = $2; gsub(/"/, "", v); w[$1] = v }
      END { printf "{\"art\":\"paket\",\"name\":\"%s\",\"anzeige\":\"%s\",\"version\":\"%s\",\"aktiv\":%s}\n", esc(name), esc(w["displayname"]), esc(w["version"]), aktiv }' "$f"
  done
  set -f
  ende 0
}

v_container_liste() {
  pruefe_args ""
  docker_pfad
  alle_container "$VORLAGE_LISTE"
  ende 0
}

v_container_details() {
  pruefe_args "name:NAME"
  docker_pfad
  container_name
  mit_zeit "$ZEIT" "$DOCKER" inspect --type container --format "$VORLAGE_DETAILS" "$NAME" 2>&1 | docker_zeilen 5
  ende 0
}

v_container_log() {
  pruefe_args "name:NAME seit:ZEITD bis:ZEITD zeilen:ZAHL suche:WORT"
  docker_pfad
  local seit bis von="" bis_awk=""
  container_name
  seit=$(wert seit)
  bis=$(wert bis)
  # Der Log-Treiber von Synology (db) beachtet --since und --until nicht. Deshalb filtert awk zusätzlich auf den
  # Zeitstempel am Zeilenanfang (UTC), und mit Zeitraum gilt keine Grenze der Zeilen, sonst fehlte ein altes Fenster.
  case $seit in *Z) von=${seit%Z} ;; esac
  case $bis in *Z) bis_awk=${bis%Z} ;; esac
  set -- logs --timestamps
  if [ -n "$seit" ]; then set -- "$@" --since "$seit"; else set -- "$@" --tail "$ROH_ZEILEN"; fi
  if [ -n "$bis" ]; then set -- "$@" --until "$bis"; fi
  mit_zeit "$ZEIT" "$DOCKER" "$@" "$NAME" 2>&1 | zeilen_json "$von" "$bis_awk" "$(wert suche | tr 'A-Z' 'a-z')" "$(wert zeilen 200)"
  [ "${PIPESTATUS[0]}" = 0 ] || ende 3
  ende 0
}

v_container_ereignisse() {
  pruefe_args "seit:ZEITD bis:ZEITD name:NAME"
  docker_pfad
  local seit bis a
  seit=$(wert seit)
  bis=$(wert bis)
  if [ -z "$seit" ] || [ -z "$bis" ]; then
    abbruch 2 argument "seit und bis sind Pflicht (sonst wartet docker events endlos): $(erklaerung ZEITD)"
  fi
  set -- events --since "$seit" --until "$bis" --filter type=container
  for a in die oom kill stop start restart create destroy health_status; do set -- "$@" --filter "event=$a"; done
  if [ -n "$(wert name)" ]; then
    container_name
    set -- "$@" --filter "container=$NAME"
  fi
  mit_zeit 20 "$DOCKER" "$@" --format "$VORLAGE_EREIGNIS" 2>&1 | docker_zeilen 2000
  printf '{"art":"hinweis","t":"docker events kennt nur die letzten 256 Ereignisse und nichts vor dem letzten Start des Docker-Dienstes"}\n'
  ende 0
}

v_docker_images() {
  pruefe_args ""
  docker_pfad
  mit_zeit "$ZEIT" "$DOCKER" images --no-trunc --format "$VORLAGE_IMAGE" 2>&1 | docker_zeilen 1000
  alle_container "$VORLAGE_GENUTZT"
  mit_zeit "$ZEIT" "$DOCKER" system df --format "$VORLAGE_DF" 2>&1 | docker_zeilen 20
  ende 0
}

v_nas_sicherheit() {
  pruefe_args ""
  local admins ssh_an=false telnet_an=false p wert
  admins=$(awk -F: '$1 == "administrators" { print $4 }' "$W/etc/group" 2>/dev/null)
  printf '{"art":"sicherheit","administratoren":%s}\n' "$(js "$admins")"
  pgrep -x sshd >/dev/null 2>&1 && ssh_an=true
  pgrep -x telnetd >/dev/null 2>&1 && telnet_an=true
  printf '{"art":"dienste","ssh":%s,"telnet":%s}\n' "$ssh_an" "$telnet_an"
  for p in PermitRootLogin PasswordAuthentication PubkeyAuthentication PermitUserEnvironment AllowTcpForwarding; do
    wert=$(awk -v p="$p" 'tolower($1) == tolower(p) { w = $2 } END { print w }' "$W/etc/ssh/sshd_config" 2>/dev/null)
    printf '{"art":"sshd","option":"%s","wert":%s}\n' "$p" "$(js "${wert:-Vorgabe}")"
  done
  # Anmeldungen per SSH und an DSM aus dem Systemlog, die letzten 30
  log_lesen "$(log_pfad messages)" 2>/dev/null \
    | grep -E 'Accepted (publickey|password)|Failed password|authentication failure|Invalid user|logged in|failed to log in' \
    | zeilen_json "" "" "" 30
  ende 0
}

# Notbremse für die Rolle schreiben: höchstens SCHREIB_PRO_STUNDE Aktionen je Stunde. Der Eintrag entsteht vor der
# Aktion, eine gescheiterte zählt mit.
notbremse() {
  local ordner=$W$ORT_FEST/zustand jetzt datei
  mkdir -p "$ordner" 2>/dev/null || abbruch 3 zustand "Zustand der Notbremse nicht schreibbar, nichts ausgeführt"
  datei=$ordner/schreiben
  jetzt=$(date +%s)
  touch "$datei" 2>/dev/null || abbruch 3 zustand "Zustand der Notbremse nicht schreibbar, nichts ausgeführt"
  awk -v grenze=$((jetzt - 3600)) '$1 + 0 > grenze' "$datei" > "$datei.neu" && mv -f "$datei.neu" "$datei"
  if [ "$(wc -l < "$datei" | tr -d ' ')" -ge "$SCHREIB_PRO_STUNDE" ]; then
    abbruch 2 notbremse "Schon $SCHREIB_PRO_STUNDE Aktionen in der letzten Stunde. Notbremse der DiskStation, später erneut"
  fi
  printf '%s %s %s\n' "$jetzt" "$VERB" "$NAME" >> "$datei"
}

# Aktion an einem Container: nur über den Namen aus der Liste, danach der neue Zustand
aktion() {  # aktion <docker-befehl> [mit_timeout]
  local sek rc
  pruefe_args "name:NAME sekunden:SEK"
  docker_pfad
  container_name
  notbremse
  sek=$(wert sekunden 120)
  if [ "${2:-}" = mit_timeout ]; then
    mit_zeit $((sek + 30)) "$DOCKER" "$1" -t "$sek" "$NAME" > /dev/null 2>"$W$ORT_FEST/zustand/fehler" ; rc=$?
  else
    mit_zeit "$ZEIT" "$DOCKER" "$1" "$NAME" > /dev/null 2>"$W$ORT_FEST/zustand/fehler" ; rc=$?
  fi
  printf '{"art":"aktion","befehl":"%s","name":%s,"sekunden":%s,"code":%d}\n' "$1" "$(js "$NAME")" \
    "$([ "${2:-}" = mit_timeout ] && echo "$sek" || echo null)" "$rc"
  if [ "$rc" != 0 ]; then
    head -c 500 "$W$ORT_FEST/zustand/fehler" | text_json
    ende 3
  fi
  mit_zeit 20 "$DOCKER" inspect --type container --format "$VORLAGE_LISTE" "$NAME" 2>&1 | docker_zeilen 5
  ende 0
}

v_container_neustart() { aktion restart mit_timeout; }
v_container_stoppen() { aktion stop mit_timeout; }
v_container_starten() {
  [ -z "$(wert sekunden)" ] || abbruch 2 argument "sekunden gibt es nur bei Neustart und Stopp"
  aktion start
}

# ---------- Ablauf ----------

case $ROLLE in
  lesen) ERLAUBT=$LESEVERBEN ;;
  schreiben) ERLAUBT="$LESEVERBEN $SCHREIBVERBEN" ;;
  *) VERB=""; abbruch 2 rolle "Rolle unbekannt" ;;
esac

[[ $VERB =~ ^[a-z_]{1,40}$ ]] || { VERB=""; abbruch 2 verb "Verb fehlt oder hat falsche Zeichen. Verben: $ERLAUBT"; }
case " $ERLAUBT " in
  *" $VERB "*) ;;
  *)
    case " $SCHREIBVERBEN " in
      *" $VERB "*) abbruch 2 rolle "$VERB braucht die Rolle schreiben" ;;
    esac
    abbruch 2 verb "Verb $VERB gibt es nicht. Verben: $ERLAUBT"
    ;;
esac

# Zweite Prüfung jedes Arguments wie in eingang.sh: nur erlaubte Zeichen, kein .. und kein - vorn
[ ${#ARGS[@]} -le 7 ] || abbruch 2 argument "Höchstens 7 Argumente"
for a in ${ARGS[@]+"${ARGS[@]}"}; do
  [[ $a =~ ^[A-Za-z0-9._:/=-]{1,200}$ ]] || abbruch 2 argument "Argument mit falschen Zeichen"
  case $a in -*|*..*) abbruch 2 argument "Argument beginnt mit - oder enthält .." ;; esac
done

printf '{"art":"kopf","gate":%s,"rolle":%s,"verb":%s}\n' "$(js "$VERSION")" "$(js "$ROLLE")" "$(js "$VERB")"
"v_$VERB"
