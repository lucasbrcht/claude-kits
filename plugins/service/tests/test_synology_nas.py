#!/usr/bin/env python3
"""Tests für die Skripte auf der DiskStation (synology/nas): eingang.sh, gate.sh, install.sh.

Alles läuft am Mac mit /bin/bash (3.2, strenger als die bash auf DSM) in einer erfundenen Welt unter GATE_WURZEL:
falsche Programme für docker, sudo, smartctl, synoschedtask, logger, df, dmesg und erfundene Dateien unter /proc,
/etc und /var/log. Geprüft wird:
- jede Zeichenkette der Angriffssammlung (Muster aus lily und shellguard) wird abgelehnt, nichts davon erreicht docker,
- jedes Leseverb liefert gültige JSON-Zeilen mit Kopf und Ende,
- Grenzen greifen (Zeilen, Bytes, Argumente),
- ein eingepflanztes Passwort taucht in keiner Ausgabe auf, Steuerzeichen fallen weg,
- docker inspect läuft nur mit fester Vorlage, Umgebung nur als Namen,
- install.sh richtet im Testordner sudoers und authorized_keys ein, wiederholbar, und bricht bei falschen Angaben ab.

Aufruf im Plugin-Ordner: python3 -B -m unittest discover tests
"""
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ORDNER = Path(__file__).resolve().parent.parent
NAS = ORDNER / "synology" / "nas"
BASH = "/bin/bash"
GEHEIM = "Geheim4711x"
NAMEN = ["homeassistant", "pihole", "watchtower", "matter-server"]
IDS = ["a" * 63 + str(i) for i in range(len(NAMEN))]

# Angriffe auf eingang.sh, nach validate_test.go aus lily und attack_vectors_test.go aus shellguard
ANGRIFFE = [
    "nas_status; id", "nas_status && id", "nas_status || id", "nas_status | id", "nas_status & id",
    "nas_status `id`", "nas_status $(id)", 'nas_status "$(id)"', "nas_status '$(id)'", "echo $(rm -rf /)",
    "container_log name=$(id)", "container_log name=`id`", "nas_status > /tmp/x", "nas_status >> /tmp/x",
    "nas_status < /etc/passwd", "cat <<< x", "cat << EOF", "diff <(ls) <(ls)", "nas_status\nid", "nas_status\r\nid",
    "nas_status\rid", "nas_status\tid", "nas_status  name=a", " nas_status", "nas_status ", "NAS_STATUS",
    "nas-status", "container_log name=../../etc/passwd", "container_log name=a/../b", "container_log --since=1h",
    "container_log -n 5","PATH=/tmp nas_status", "x=1 nas_status", "container_log name='a b'",
    'container_log name="a"', "container_log name=a*", "container_log name=a?", "container_log name=[a]",
    "container_log name=~root", "nas_status #x", "nas_status !x", "container_log name=a\\b", "nas_status {a,b}",
    "nas_stätus", "nas_status name=ä", "a b c d e f g h i", "nas_status " + "a" * 300, "", "find / -exec id ;",
    "awk 'BEGIN{system(\"id\")}'", "(id)", "{ id; }", "nas_status%0aid", "nas_status\x1b[31m", "nas_status\x00id",
]
# Angriffe, die durch eingang.sh kommen (nur erlaubte Zeichen), die gate.sh aber ablehnen muss
ANGRIFFE_GATE = [
    "sed w /tmp/x", "find a b", "bash", "sh", "id", "container_neustart name=homeassistant", "nas_status x",
    "nas_status name=homeassistant", "container_log name", "container_log =x", "container_log name=a=b",
    "container_log name=-x", "container_log name=" + IDS[0],"container_log name=" + IDS[0][:12], "container_log name=gibtsnicht",
    "container_log name=homeassistant zeilen=0", "container_log name=homeassistant zeilen=5001",
    "container_log name=homeassistant zeilen=abc", "container_log name=homeassistant seit=gestern",
    "container_log name=homeassistant seit=2026-11-24", "container_log name=homeassistant name=pihole",
    "container_log name=homeassistant suche=a/b", "container_ereignisse seit=1h",
    "nas_log log=/etc/shadow", "nas_log log=shadow", "nas_log von=24.11.2026",
]

FALSCHES_DOCKER = r'''
import json, os, sys
w = os.environ["GATE_WURZEL"]
a = sys.argv[1:]
with open(os.path.join(w, "aufrufe.txt"), "a") as f:
    f.write(json.dumps(a) + "\n")
daten = json.load(open(os.path.join(w, "daten.json")))
_dumps = json.dumps
json.dumps = lambda o: _dumps(o, separators=(",", ":"))  # so kompakt wie {{json}} in docker
namen, ids = daten["namen"], daten["ids"]
fmt = a[a.index("--format") + 1] if "--format" in a else ""
projekt = next((x.split("=", 2)[2] for x in a if x.startswith("label=com.docker.compose.project=")), None)
ORDNER = {"matter-server": "/volume1/docker/matter-server", "boese": "/volume1/docker/../../etc"}
if a[:1] == ["ps"] and projekt is not None:
    if projekt in ORDNER and "-aq" in a:
        print(ids[3])
    elif projekt in ORDNER and "working_dir" in fmt:
        print(ORDNER[projekt])
    elif projekt in ORDNER and "config_files" in fmt:
        print(ORDNER[projekt] + "/compose.yaml")
elif a[:2] == ["compose", "version"]:
    print("Docker Compose version v2.20.1")
elif a[:1] == ["compose"]:
    print(("Pulling matter-server" if a[-1] == "pull" else "Container matter-server  Recreated") + " \x1b[32mdone\x1b[0m")
elif a[:1] == ["ps"]:
    if "-aq" in a:
        print("\n".join(ids))
    elif fmt == "{{.Names}}":
        print("\n".join(namen))
    elif fmt == "{{.State}}":
        print("running\nrunning\nrunning\nexited")
elif a[:1] == ["inspect"]:
    if not fmt:
        print("inspect ohne Vorlage", file=sys.stderr); sys.exit(9)
    ziele = [x for x in a[1:] if x not in ("--format", fmt, "--type", "container")]
    for z in ziele:
        n = namen[ids.index(z)] if z in ids else z
        if '"art":"details"' in fmt:
            print(json.dumps({"art": "details", "name": "/" + n, "env_namen": ["TZ", "PASSWORD", None]}))
        elif '"art":"genutzt"' in fmt:
            print(json.dumps({"art": "genutzt", "name": "/" + n, "image_id": "sha256:" + "b" * 64}))
        else:
            print(json.dumps({"art": "container", "name": "/" + n, "status": "running", "exit": 0, "oom": False,
                              "neustarts": 0, "labels": [["com.centurylinklabs.watchtower.enable", "true"], None]}))
elif a[:1] == ["logs"]:
    anzahl = int(os.environ.get("FAKE_LOG_ZEILEN", "0"))
    out = sys.stdout.buffer
    if anzahl:
        for i in range(anzahl):
            out.write(("2026-11-24T10:%02d:%02d.000000000Z Zeile %d error %s\n" % (i // 60 % 60, i % 60, i, "x" * 80)).encode())
    else:
        out.write(b"2026-11-24T10:10:01.000000000Z INFO Start\n")
        out.write(("2026-11-24T10:10:02.000000000Z db password=%s user=x\n" % daten["geheim"]).encode())
        out.write(("2026-11-24T10:10:03.000000000Z header Authorization: Bearer %s\n" % daten["geheim"]).encode())
        out.write(("2026-11-24T10:10:04.000000000Z {\"api_key\": \"%s\"}\n" % daten["geheim"]).encode())
        out.write(b"2026-11-24T10:10:05.000000000Z \x1b[31mERROR\x1b[0m Farbe\r\n")
        out.write(b"2026-11-24T10:10:06.000000000Z kaputt \xff\xfe utf8\n")
        out.write(b"2026-11-24T10:10:07.000000000Z " + b"L" * 5000 + b"\n")
        out.write(b"2026-11-24T10:13:00.000000000Z Received signal SIGTERM, stopping\n")
elif a[:1] in (["restart"], ["stop"], ["start"]):
    print(a[-1])
elif a[:1] == ["events"]:
    print(json.dumps({"art": "ereignis", "zeit": 1763979000, "aktion": "die", "name": "homeassistant", "exit": "137"}))
    print("Error response from daemon: Kaputt\n", file=sys.stderr)
elif a[:1] == ["images"]:
    print(json.dumps({"art": "image", "repo": "x/ha", "tag": "stable", "id": "sha256:" + "b" * 64, "groesse": "1.9GB"}))
elif a[:2] == ["system", "df"]:
    print(json.dumps({"art": "docker_df", "typ": "Images", "anzahl": "9", "aktiv": "4", "groesse": "8GB",
                      "freigebbar": "5GB (60%)"}))
else:
    print("unbekannt", file=sys.stderr); sys.exit(1)
'''

SMARTCTL = """#!/bin/bash
echo "smartctl 7.x"
echo "SMART overall-health self-assessment test result: PASSED"
echo "ID# ATTRIBUTE_NAME          FLAG     VALUE WORST THRESH TYPE      UPDATED  WHEN_FAILED RAW_VALUE"
echo "  5 Reallocated_Sector_Ct   0x0033   100   100   005    Pre-fail  Always       -       0"
echo "  9 Power_On_Hours          0x0012   096   096   000    Old_age   Always       -       31234"
echo "194 Temperature_Celsius     0x0002   200   200   000    Old_age   Always       -       34 (Min/Max 18/45)"
echo "197 Current_Pending_Sector  0x0022   100   100   000    Old_age   Always       -       0"
"""


def ausfuehrbar(pfad: Path, inhalt: str) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(inhalt, encoding="utf-8")
    pfad.chmod(0o755)


def welt(w: Path) -> None:
    """Erfundene DiskStation unter w."""
    (w / "daten.json").write_text(json.dumps({"namen": NAMEN, "ids": IDS, "geheim": GEHEIM}), encoding="utf-8")
    ausfuehrbar(w / "usr/local/bin/docker", f"#!{sys.executable}\n" + FALSCHES_DOCKER)
    ausfuehrbar(w / "usr/bin/sudo", '#!/bin/bash\necho "$*" >> "$GATE_WURZEL/sudo.txt"\n'
                                    '[ "$1" = -n ] && shift\n[ "$1" = -l ] && exit "${FAKE_SUDO_L:-0}"\n'
                                    'exec /bin/bash "$@"\n')
    ausfuehrbar(w / "usr/bin/logger", '#!/bin/bash\necho "$*" >> "$GATE_WURZEL/logger.txt"\n')
    ausfuehrbar(w / "usr/bin/smartctl", SMARTCTL)
    ausfuehrbar(w / "usr/syno/bin/synoschedtask",
                f"#!/bin/bash\necho 'ID: 3 Name: Sicherung'\necho 'Command: curl -u admin --password={GEHEIM} x'\n"
                "echo 'Status: enabled'\n")
    ausfuehrbar(w / "bin/df", "#!/bin/bash\necho 'Filesystem 1024-blocks Used Available Capacity Mounted on'\n"
                              "echo '/dev/md0 2385528 1500000 785528 66% /'\n"
                              "echo '/dev/mapper/vg1 7000000000 5810000000 1190000000 83% /volume1'\n"
                              "echo 'tmpfs 100 1 99 1% /dev/shm'\n")
    ausfuehrbar(w / "bin/dmesg", "#!/bin/bash\necho '[100.1] usb 1-1: new device'\n"
                                 "echo '[200.2] Out of memory: Killed process 4242 (python3)'\n")
    os.symlink("/usr/bin/gzip", w / "bin/gzip")
    for pfad, inhalt in {
        "etc.defaults/VERSION": 'productversion="7.4.1"\nbuildnumber="90080"\nsmallfixnumber="1"\n',
        "proc/uptime": "123456.78 1000.0\n", "proc/loadavg": "0.52 0.61 0.70 1/300 4242\n",
        "proc/meminfo": "MemTotal:  8000000 kB\nMemFree: 100 kB\nMemAvailable:  3000000 kB\n",
        "proc/mdstat": "Personalities : [raid1]\nmd2 : active raid1 sata1p3[0] sata2p3[1]\n      [2/2] [UU]\n",
        "proc/sys/kernel/syno_hw_version": "DS920+\n",
        "sys/class/thermal/thermal_zone0/temp": "45000\n",
        "etc/sudoers.d/claude-gate": "Defaults:claude env_reset, !requiretty\n"
                                     "claude ALL=(root) NOPASSWD: /volume1/@claude-gate/gate.sh",
        "var/log/messages.1": "2026-11-23T23:59:00+01:00 nas dockerd: gestern\n",
        "var/log/messages": f"2026-11-24T11:09:00+01:00 nas kernel: vorher\n"
                            f"2026-11-24T11:13:02+01:00 nas synoscgi: login password={GEHEIM}\n"
                            f"2026-11-24T11:13:05+01:00 nas dockerd: container died error\n"
                            f"2026-11-24T12:00:00+01:00 nas kernel: spaeter\n",
        "var/packages/ContainerManager/INFO": 'package="ContainerManager"\nversion="24.0.2-1543"\n'
                                              'displayname="Container Manager"\n',
        "var/packages/ContainerManager/enabled": "",
        "var/packages/HyperBackup/INFO": 'package="HyperBackup"\nversion="4.1.0"\ndisplayname="Hyper Backup"\n',
        "etc/group": "administrators:x:101:admin,Claude\nusers:x:100:\n",
        "etc/ssh/sshd_config": "#PermitRootLogin yes\nPermitRootLogin no\nPasswordAuthentication yes\n",
    }.items():
        (w / pfad).parent.mkdir(parents=True, exist_ok=True)
        (w / pfad).write_text(inhalt, encoding="utf-8")
    with gzip.open(w / "var/log/messages.2.gz", "wt") as f:
        f.write("2026-11-10T11:10:00+01:00 nas dockerd: vor zwei Wochen\n")
    (w / "dev").mkdir()
    for d in ("dev/sata1", "dev/sata2"):
        (w / d).write_text("", encoding="utf-8")
    (w / "volume1/@claude-gate").mkdir(parents=True)
    (w / "volume1/docker/matter-server").mkdir(parents=True)
    (w / "volume1/docker/matter-server/compose.yaml").write_text("services: {}\n", encoding="utf-8")


class Basis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = Path(tempfile.mkdtemp(prefix="synology-nas-")).resolve()
        welt(cls.w)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.w)

    def setUp(self):
        for datei in ("aufrufe.txt", "sudo.txt", "logger.txt"):
            (self.w / datei).unlink(missing_ok=True)

    def env(self, **mehr):
        return {"PATH": "/usr/bin:/bin", "GATE_WURZEL": str(self.w), "HOME": str(self.w), **mehr}

    def eingang(self, befehl: str, rolle: str = "lesen", **mehr):
        lauf = subprocess.run([BASH, str(NAS / "eingang.sh"), rolle], capture_output=True, timeout=60,
                              env=self.env(SSH_ORIGINAL_COMMAND=befehl, **mehr))
        return lauf.returncode, lauf.stdout.decode("utf-8", "replace"), lauf.stderr.decode("utf-8", "replace")

    def gate(self, *args, **mehr):
        lauf = subprocess.run([BASH, str(NAS / "gate.sh"), *args], capture_output=True, timeout=60,
                              env=self.env(**mehr))
        return lauf.returncode, lauf.stdout.decode("utf-8", "replace"), lauf.stderr.decode("utf-8", "replace")

    def zeilen(self, ausgabe: str) -> list:
        """Jede Zeile ist ein JSON-Objekt mit art, die letzte ist das Ende."""
        zeilen = [json.loads(z) for z in ausgabe.splitlines()]
        self.assertTrue(zeilen, "keine Ausgabe")
        for z in zeilen:
            self.assertIsInstance(z, dict)
            self.assertIn("art", z)
        self.assertEqual(zeilen[-1]["art"], "ende")
        return zeilen

    def docker_aufrufe(self) -> list:
        datei = self.w / "aufrufe.txt"
        return [json.loads(z) for z in datei.read_text().splitlines()] if datei.is_file() else []


class Eingang(Basis):
    def test_angriffe_abgelehnt_ohne_sudo(self):
        for angriff in ANGRIFFE:
            if "\x00" in angriff:
                continue  # eine Umgebungsvariable kann kein Nullbyte tragen
            with self.subTest(angriff=angriff):
                (self.w / "sudo.txt").unlink(missing_ok=True)
                code, aus, _err = self.eingang(angriff)
                self.assertEqual(code, 2)
                z = self.zeilen(aus)
                self.assertEqual(z[0]["art"], "fehler")
                self.assertEqual(z[-1]["code"], 2)
                self.assertFalse((self.w / "sudo.txt").exists(), "sudo darf nicht laufen")
        self.assertEqual(self.docker_aufrufe(), [])

    def test_angriffe_im_gate_abgelehnt(self):
        for angriff in ANGRIFFE_GATE:
            with self.subTest(angriff=angriff):
                code, aus, _err = self.eingang(angriff)
                self.assertEqual(code, 2)
                z = self.zeilen(aus)
                self.assertTrue(any(x["art"] == "fehler" for x in z))
                self.assertEqual(z[-1]["code"], 2)
        # docker sah höchstens die Abfrage der Namen, nie logs, inspect oder events
        for aufruf in self.docker_aufrufe():
            self.assertEqual(aufruf[:1], ["ps"], aufruf)

    def test_rolle_aus_schluessel(self):
        code, aus, _err = self.eingang("nas_status", rolle="root")
        self.assertEqual(code, 2)
        self.assertIn("Rolle", aus)
        code, aus, _err = self.eingang("nas_status", rolle="schreiben")
        self.assertEqual(code, 0)

    def test_sudo_fehlt_nennt_install(self):
        code, aus, _err = self.eingang("nas_status", FAKE_SUDO_L="1")
        self.assertEqual(code, 2)
        self.assertIn("install.sh", aus)

    def test_ablehnung_im_log_ohne_text(self):
        self.eingang("nas_status; cat /etc/shadow")
        log = (self.w / "logger.txt").read_text()
        self.assertIn("eingang abgelehnt", log)
        self.assertNotIn("shadow", log)

    def test_gate_bekommt_einzelne_argumente(self):
        code, aus, _err = self.eingang("container_log name=homeassistant zeilen=3")
        self.assertEqual(code, 0)
        sudo = (self.w / "sudo.txt").read_text().splitlines()
        self.assertTrue(sudo[-1].endswith("gate.sh lesen container_log name=homeassistant zeilen=3"), sudo)


class Gate(Basis):
    LESEN = {
        "nas_status": [], "nas_speicher": [], "nas_platten": [], "nas_log": [], "nas_aufgaben": [],
        "nas_pakete": [], "nas_sicherheit": [], "container_liste": [], "container_details": ["name=homeassistant"],
        "container_log": ["name=homeassistant"], "docker_images": [],
        "container_ereignisse": ["seit=2026-11-24T10:00Z", "bis=2026-11-24T11:00Z"],
    }

    def test_jedes_leseverb_liefert_json(self):
        for verb, args in self.LESEN.items():
            with self.subTest(verb=verb):
                code, aus, err = self.gate("lesen", verb, *args)
                self.assertEqual(code, 0, aus + err)
                z = self.zeilen(aus)
                version = (NAS / "VERSION").read_text().strip()
                self.assertEqual(z[0], {"art": "kopf", "gate": version, "rolle": "lesen", "verb": verb})
                self.assertEqual(z[-1], {"art": "ende", "code": 0})
                self.assertNotIn(GEHEIM, aus)

    def test_status_inhalt(self):
        z = self.zeilen(self.gate("lesen", "nas_status")[1])
        system = next(x for x in z if x["art"] == "system")
        self.assertEqual((system["modell"], system["dsm"], system["build"], system["update"]),
                         ("DS920+", "7.4.1", "90080", "1"))
        self.assertEqual((system["laufzeit_s"], system["ram_kb"], system["temperatur_c"]), (123456, 8000000, 45))
        self.assertEqual(next(x for x in z if x["art"] == "pruefung")["sudoers"], True)
        vol = [x for x in z if x["art"] == "volume"]
        self.assertEqual([(v["ort"], v["prozent"]) for v in vol], [("/", 66), ("/volume1", 83)])
        zahl = {x["status"]: x["anzahl"] for x in z if x["art"] == "container_zahl"}
        self.assertEqual(zahl, {"running": 3, "exited": 1})

    def test_platten(self):
        z = self.zeilen(self.gate("lesen", "nas_platten")[1])
        platten = [x for x in z if x["art"] == "platte"]
        self.assertEqual([p["geraet"] for p in platten], ["sata1", "sata2"])
        self.assertEqual((platten[0]["gesund"], platten[0]["temperatur_c"], platten[0]["betriebsstunden"]),
                         ("PASSED", 34, 31234))

    def test_container_log_schwaerzt_und_reinigt(self):
        code, aus, _err = self.gate("lesen", "container_log", "name=homeassistant")
        self.assertEqual(code, 0)
        self.assertNotIn(GEHEIM, aus)
        self.assertNotIn("\x1b", aus)
        self.assertNotIn("\\r", aus)
        z = self.zeilen(aus)
        texte = [x["t"] for x in z if x["art"] == "zeile"]
        self.assertIn("password=***", " ".join(texte))
        self.assertIn("Bearer ***", " ".join(texte))
        self.assertTrue(all(len(t) <= 2000 for t in texte))
        worte = {x["wort"] for x in z if x["art"] == "auffaellig"}
        self.assertTrue({"error", "sigterm", "stopping"} <= worte, worte)
        aufruf = [a for a in self.docker_aufrufe() if a[:1] == ["logs"]][-1]
        self.assertEqual(aufruf[-1], "homeassistant")
        self.assertIn("--timestamps", aufruf)

    def test_container_log_grenzen(self):
        code, aus, _err = self.gate("lesen", "container_log", "name=homeassistant", "zeilen=5000",
                                    FAKE_LOG_ZEILEN="30000")
        self.assertEqual(code, 0)
        self.assertLessEqual(len(aus.encode()), 262144 + 4000)
        z = self.zeilen(aus)
        summe = next(x for x in z if x["art"] == "summe")
        self.assertEqual(summe["treffer"], 30000)
        self.assertLessEqual(summe["gezeigt"], 5000)
        self.assertTrue(summe["gekuerzt"])
        # die neuesten Zeilen bleiben, die ältesten fallen weg
        self.assertIn("Zeile 29999 ", [x for x in z if x["art"] == "zeile"][-1]["t"])

    def test_container_log_zeitfenster_auch_ohne_docker(self):
        """Das falsche docker beachtet --since und --until nicht, wie der Log-Treiber von Synology: gate.sh filtert."""
        code, aus, _err = self.gate("lesen", "container_log", "name=homeassistant", "seit=2026-11-24T10:10:02Z",
                                    "bis=2026-11-24T10:10:05Z")
        texte = [x["t"] for x in self.zeilen(aus) if x["art"] == "zeile"]
        self.assertEqual([t[:30] for t in texte], ["2026-11-24T10:10:02.000000000Z", "2026-11-24T10:10:03.000000000Z",
                                                   "2026-11-24T10:10:04.000000000Z", "2026-11-24T10:10:05.000000000Z"])
        aufruf = [a for a in self.docker_aufrufe() if a[:1] == ["logs"]][-1]
        self.assertNotIn("--tail", aufruf)

    def test_container_log_suche_und_zeit(self):
        self.gate("lesen", "container_log", "name=homeassistant", "seit=2026-11-24T10:00Z", "bis=30m", "suche=SIGTERM")
        aufruf = [a for a in self.docker_aufrufe() if a[:1] == ["logs"]][-1]
        self.assertEqual(aufruf[aufruf.index("--since") + 1], "2026-11-24T10:00Z")
        self.assertEqual(aufruf[aufruf.index("--until") + 1], "30m")
        code, aus, _err = self.gate("lesen", "container_log", "name=homeassistant", "suche=sigterm")
        texte = [x["t"] for x in self.zeilen(aus) if x["art"] == "zeile"]
        self.assertEqual(len(texte), 1)

    def test_details_mit_fester_vorlage(self):
        self.gate("lesen", "container_details", "name=homeassistant")
        for aufruf in self.docker_aufrufe():
            if aufruf[:1] == ["inspect"]:
                self.assertIn("--format", aufruf)

    def test_vorlagen_ohne_werte_der_umgebung(self):
        text = (NAS / "gate.sh").read_text(encoding="utf-8")
        vorlagen = re.findall(r"^VORLAGE_[A-Z]+='(.*)'$", text, re.M)
        self.assertEqual(len(vorlagen), 6)
        for v in vorlagen:
            ohne = v.replace('{{range .Config.Env}}{{json (index (split . "=") 0)}},{{end}}', "")
            for verboten in (".Config.Env", "{{json .}}", "{{json .Config}}", ".Healthcheck.Test", ".Config.Cmd",
                             ".Args", ".Config.Entrypoint", "{{json .HostConfig}}", ".State.Health.Log"):
                self.assertNotIn(verboten, ohne)
        self.assertNotRegex(text, r"inspect(?![^\n]*--format)[^\n]*\"\$")
        self.assertNotIn("eval ", text)

    def test_ereignisse(self):
        code, aus, _err = self.gate("lesen", "container_ereignisse", "seit=2026-11-24T10:00Z", "bis=2026-11-24T11:00Z",
                                    "name=homeassistant")
        z = self.zeilen(aus)
        self.assertEqual([x["aktion"] for x in z if x["art"] == "ereignis"], ["die"])
        self.assertTrue(any(x["art"] == "meldung" for x in z))
        self.assertTrue(any(x["art"] == "hinweis" for x in z))
        aufruf = [a for a in self.docker_aufrufe() if a[:1] == ["events"]][-1]
        self.assertIn("container=homeassistant", aufruf)
        self.assertIn("type=container", aufruf)

    def test_nas_log_gedreht_und_zeit(self):
        z = self.zeilen(self.gate("lesen", "nas_log", "log=messages", "von=2026-11-24T11:10",
                                  "bis=2026-11-24T11:13")[1])
        texte = [x["t"] for x in z if x["art"] == "zeile"]
        self.assertEqual(len(texte), 2)
        self.assertIn("password=***", texte[0])
        alle = [x["t"] for x in self.zeilen(self.gate("lesen", "nas_log", "log=messages")[1]) if x["art"] == "zeile"]
        self.assertIn("vor zwei Wochen", alle[0])
        self.assertIn("spaeter", alle[-1])
        liste = {x["name"]: x["da"] for x in self.zeilen(self.gate("lesen", "nas_log")[1]) if x["art"] == "log"}
        self.assertEqual(liste, {"messages": True, "kern": False, "docker": False, "scemd": False, "dmesg": True})
        dmesg = [x["t"] for x in self.zeilen(self.gate("lesen", "nas_log", "log=dmesg")[1]) if x["art"] == "zeile"]
        self.assertEqual(len(dmesg), 1)

    def test_aufgaben_geschwaerzt(self):
        code, aus, _err = self.gate("lesen", "nas_aufgaben")
        self.assertNotIn(GEHEIM, aus)
        self.assertIn("password=***", aus)

    def test_pakete(self):
        z = self.zeilen(self.gate("lesen", "nas_pakete")[1])
        pakete = {x["name"]: (x["version"], x["aktiv"]) for x in z if x["art"] == "paket"}
        self.assertEqual(pakete, {"ContainerManager": ("24.0.2-1543", True), "HyperBackup": ("4.1.0", False)})

    def test_sicherheit(self):
        z = self.zeilen(self.gate("lesen", "nas_sicherheit")[1])
        self.assertEqual(next(x for x in z if x["art"] == "sicherheit")["administratoren"], "admin,Claude")
        sshd = {x["option"]: x["wert"] for x in z if x["art"] == "sshd"}
        self.assertEqual((sshd["PermitRootLogin"], sshd["PasswordAuthentication"], sshd["AllowTcpForwarding"]),
                         ("no", "yes", "Vorgabe"))

    def notbremse_leeren(self):
        shutil.rmtree(self.w / "volume1/@claude-gate/zustand", ignore_errors=True)

    def test_schreiben_nur_mit_rolle_schreiben(self):
        self.notbremse_leeren()
        for verb in ("container_neustart", "container_starten", "container_stoppen"):
            with self.subTest(verb=verb):
                code, aus, _err = self.gate("lesen", verb, "name=homeassistant")
                self.assertEqual(code, 2)
                self.assertIn("braucht die Rolle schreiben", aus)
        self.assertEqual([a for a in self.docker_aufrufe() if a[0] in ("restart", "stop", "start")], [])

    def test_neustart_stopp_start(self):
        self.notbremse_leeren()
        code, aus, err = self.gate("schreiben", "container_neustart", "name=homeassistant")
        self.assertEqual(code, 0, aus + err)
        z = self.zeilen(aus)
        self.assertEqual(next(x for x in z if x["art"] == "aktion")["sekunden"], 120)
        self.assertTrue(any(x["art"] == "container" for x in z))
        self.gate("schreiben", "container_stoppen", "name=pihole", "sekunden=300")
        self.gate("schreiben", "container_starten", "name=pihole")
        aktionen = [a for a in self.docker_aufrufe() if a[0] in ("restart", "stop", "start")]
        self.assertEqual(aktionen, [["restart", "-t", "120", "homeassistant"], ["stop", "-t", "300", "pihole"],
                                    ["start", "pihole"]])
        log = (self.w / "logger.txt").read_text()
        self.assertIn("rolle=schreiben verb=container_stoppen args=name=pihole sekunden=300 code=0", log)

    def test_schreiben_falsche_angaben(self):
        self.notbremse_leeren()
        for args in (["name=homeassistant", "sekunden=5"], ["name=homeassistant", "sekunden=601"],
                     ["name=" + IDS[0]], ["name=gibtsnicht"], []):
            with self.subTest(args=args):
                self.assertEqual(self.gate("schreiben", "container_neustart", *args)[0], 2)
        self.assertEqual(self.gate("schreiben", "container_starten", "name=pihole", "sekunden=30")[0], 2)
        self.assertEqual([a for a in self.docker_aufrufe() if a[0] in ("restart", "stop", "start")], [])

    def test_projekt_aktualisieren(self):
        self.notbremse_leeren()
        code, aus, err = self.gate("schreiben", "projekt_aktualisieren", "name=matter-server", "sekunden=90")
        self.assertEqual(code, 0, aus + err)
        z = self.zeilen(aus)
        self.assertEqual([(x["befehl"], x["code"]) for x in z if x["art"] == "aktion"], [("pull", None), ("up", 0)])
        self.assertNotIn("\x1b", aus)
        compose = [a for a in self.docker_aufrufe() if a[:1] == ["compose"] and a[1] != "version"]
        basis = ["compose", "--project-directory", "/volume1/docker/matter-server", "-p", "matter-server",
                 "-f", "/volume1/docker/matter-server/compose.yaml"]
        self.assertEqual(compose, [basis + ["pull"], basis + ["up", "-d", "-t", "90"]])
        self.assertTrue(any(x["art"] == "container" for x in z))

    def test_projekt_abgelehnt(self):
        self.notbremse_leeren()
        for rolle, args, teil in (("lesen", ["name=matter-server"], "Rolle schreiben"),
                                  ("schreiben", ["name=homeassistant"], "docker run"),
                                  ("schreiben", ["name=boese"], "/volumeN")):
            with self.subTest(args=args):
                code, aus, _err = self.gate(rolle, "projekt_aktualisieren", *args)
                self.assertNotEqual(code, 0)
                self.assertIn(teil, aus)
        self.assertEqual([a for a in self.docker_aufrufe() if a[:1] == ["compose"] and a[1] != "version"], [])

    def test_notbremse(self):
        self.notbremse_leeren()
        for _ in range(10):
            self.assertEqual(self.gate("schreiben", "container_starten", "name=pihole")[0], 0)
        code, aus, _err = self.gate("schreiben", "container_starten", "name=pihole")
        self.assertEqual(code, 2)
        self.assertIn("Notbremse", aus)
        self.assertEqual(len([a for a in self.docker_aufrufe() if a[0] == "start"]), 10)
        self.notbremse_leeren()

    def test_zu_viele_argumente(self):
        code, aus, _err = self.gate("lesen", "nas_status", *["a=b"] * 8)
        self.assertEqual(code, 2)

    def test_protokoll(self):
        self.gate("lesen", "container_log", "name=pihole", "zeilen=10")
        log = (self.w / "logger.txt").read_text()
        self.assertIn("rolle=lesen verb=container_log args=name=pihole zeilen=10 code=0", log)

    def test_ohne_docker(self):
        alt = self.w / "usr/local/bin/docker"
        neu = self.w / "docker.weg"
        alt.rename(neu)
        try:
            code, aus, _err = self.gate("lesen", "container_liste")
            self.assertEqual(code, 4)
            self.assertIn("Container Manager", aus)
        finally:
            neu.rename(alt)

    def test_wurzel_nur_im_test(self):
        """Am festen Ort oder als root zählt GATE_WURZEL nicht."""
        for datei in ("gate.sh", "eingang.sh"):
            text = (NAS / datei).read_text(encoding="utf-8")
            self.assertIn(f'"$SELBST" != "$ORT_FEST/{datei}"', text)
        self.assertIn('[ "$(id -u)" != 0 ]', (NAS / "gate.sh").read_text(encoding="utf-8"))


class Install(unittest.TestCase):
    LESEN = "ssh-ed25519 " + "A" * 68 + " lesen@mac"
    SCHREIBEN = "ssh-ed25519 " + "B" * 68 + " schreiben@mac"

    def setUp(self):
        self.w = Path(tempfile.mkdtemp(prefix="synology-install-")).resolve()
        self.addCleanup(shutil.rmtree, self.w)
        (self.w / "etc/sudoers.d").mkdir(parents=True)
        (self.w / "etc/sudoers").write_text("root ALL=(ALL) ALL\n#includedir /etc/sudoers.d\n", encoding="utf-8")
        (self.w / "etc/passwd").write_text("root:x:0:0::/root:/bin/sh\n"
                                           "claude:x:1030:100::/var/services/homes/claude:/bin/sh\n", encoding="utf-8")
        (self.w / "etc/group").write_text("administrators:x:101:admin,claude\n", encoding="utf-8")
        (self.w / "var/services/homes/claude").mkdir(parents=True)

    def buendel(self, lesen=None, schreiben=None, netz="192.168.1.0/24") -> Path:
        b = self.w / "home" / "claude-gate-neu"
        b.mkdir(parents=True, exist_ok=True)
        for f in ("install.sh", "eingang.sh", "gate.sh", "VERSION"):
            shutil.copy(NAS / f, b / f)
        (b / "lesen.pub").write_text((lesen or self.LESEN) + "\n", encoding="utf-8")
        if schreiben:
            (b / "schreiben.pub").write_text(schreiben + "\n", encoding="utf-8")
        (b / "netz").write_text(netz + "\n", encoding="utf-8")
        return b

    def install(self, b: Path):
        return subprocess.run([BASH, str(b / "install.sh")], capture_output=True, text=True, timeout=60,
                              env={"PATH": "/usr/bin:/bin", "INSTALL_WURZEL": str(self.w)})

    def test_einrichten_und_wiederholen(self):
        lauf = self.install(self.buendel())
        self.assertEqual(lauf.returncode, 0, lauf.stdout + lauf.stderr)
        ziel = self.w / "volume1/@claude-gate"
        self.assertEqual((ziel / "gate.sh").read_bytes(), (NAS / "gate.sh").read_bytes())
        self.assertEqual(oct((ziel / "gate.sh").stat().st_mode & 0o777), "0o755")
        sudoers = self.w / "etc/sudoers.d/claude-gate"
        self.assertEqual(sudoers.read_text(), "Defaults:claude env_reset, !requiretty\n"
                                              "claude ALL=(root) NOPASSWD: /volume1/@claude-gate/gate.sh\n")
        self.assertEqual(oct(sudoers.stat().st_mode & 0o777), "0o440")
        keys = (self.w / "var/services/homes/claude/.ssh/authorized_keys").read_text().splitlines()
        self.assertEqual(len(keys), 1)
        self.assertRegex(keys[0], r'^command="/volume1/@claude-gate/eingang.sh lesen",from="192.168.1.0/24",'
                                  r'(restrict,)?no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding,'
                                  r'no-user-rc ssh-ed25519 A{68} claude-lesen$')
        self.assertFalse((self.w / "home/claude-gate-neu").exists(), "Bündel aufgeräumt")
        # zweiter Lauf mit Schreibschlüssel ersetzt, statt anzuhängen
        lauf = self.install(self.buendel(schreiben=self.SCHREIBEN))
        self.assertEqual(lauf.returncode, 0, lauf.stderr)
        keys = (self.w / "var/services/homes/claude/.ssh/authorized_keys").read_text().splitlines()
        self.assertEqual([k.split('"')[1] for k in keys], ["/volume1/@claude-gate/eingang.sh lesen",
                                                           "/volume1/@claude-gate/eingang.sh schreiben"])

    def test_name_mit_grossbuchstaben(self):
        """DSM behält die Schreibweise aus der Anlage: Claude statt claude gilt, sudoers nimmt den genauen Namen."""
        (self.w / "etc/passwd").write_text("Claude:x:1030:100::/var/services/homes/Claude:/bin/sh\n", encoding="utf-8")
        (self.w / "etc/group").write_text("administrators:x:101:lucas,Claude\n", encoding="utf-8")
        (self.w / "var/services/homes/Claude").mkdir(parents=True, exist_ok=True)  # am Mac oft gleich mit claude
        lauf = self.install(self.buendel())
        self.assertEqual(lauf.returncode, 0, lauf.stderr)
        self.assertEqual((self.w / "etc/sudoers.d/claude-gate").read_text(),
                         "Defaults:Claude env_reset, !requiretty\n"
                         "Claude ALL=(root) NOPASSWD: /volume1/@claude-gate/gate.sh\n")
        self.assertTrue((self.w / "var/services/homes/Claude/.ssh/authorized_keys").is_file())
        self.assertIn("Benutzer auf der DiskStation: Claude", lauf.stdout)

    def test_abbrueche(self):
        faelle = [
            ("kein ed25519", dict(lesen="ssh-rsa " + "A" * 300)),
            ("gleiche Schlüssel", dict(schreiben=self.LESEN)),
            ("Heimnetz", dict(netz="0.0.0.0/0; rm -rf /")),
            ("Heimnetz", dict(netz="*")),
        ]
        for grund, angaben in faelle:
            with self.subTest(grund=grund):
                lauf = self.install(self.buendel(**angaben))
                self.assertEqual(lauf.returncode, 1)
                self.assertIn("ABBRUCH", lauf.stderr)
                self.assertFalse((self.w / "etc/sudoers.d/claude-gate").exists())

    def test_ohne_admin_gruppe_und_includedir(self):
        (self.w / "etc/group").write_text("administrators:x:101:admin\n", encoding="utf-8")
        lauf = self.install(self.buendel())
        self.assertIn("administrators", lauf.stderr)
        (self.w / "etc/group").write_text("administrators:x:101:admin,claude\n", encoding="utf-8")
        (self.w / "etc/sudoers").write_text("root ALL=(ALL) ALL\n", encoding="utf-8")
        lauf = self.install(self.buendel())
        self.assertIn("sudoers.d", lauf.stderr)
        self.assertEqual(lauf.returncode, 1)
        self.assertFalse((self.w / "volume1/@claude-gate").exists())

    def test_plugin_ordner_bleibt(self):
        """install.sh räumt nur einen Ordner namens claude-gate-neu auf, nie das Plugin."""
        text = (NAS / "install.sh").read_text(encoding="utf-8")
        self.assertIn('if [ "$(basename "$QUELLE")" = claude-gate-neu ]; then', text)


class Syntax(unittest.TestCase):
    def test_bash_n_und_shellcheck(self):
        for f in ("eingang.sh", "gate.sh", "install.sh"):
            lauf = subprocess.run([BASH, "-n", str(NAS / f)], capture_output=True, text=True)
            self.assertEqual(lauf.returncode, 0, lauf.stderr)
        sc = shutil.which("shellcheck")
        if sc:
            lauf = subprocess.run([sc, "-S", "warning", *(str(NAS / f) for f in ("eingang.sh", "gate.sh", "install.sh"))],
                                  capture_output=True, text=True)
            self.assertEqual(lauf.returncode, 0, lauf.stdout)

    def test_schreibregeln_in_kommentaren(self):
        for f in ("eingang.sh", "gate.sh", "install.sh"):
            text = (NAS / f).read_text(encoding="utf-8")
            self.assertNotRegex(text, "[–—…]", f)


if __name__ == "__main__":
    unittest.main()
