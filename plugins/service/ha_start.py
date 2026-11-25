#!/usr/bin/env python3
"""ha_start.py: Starter für die MCP-Server homeassistant und homeassistant-lesen (ha-mcp) aus dem Plugin service.

Liest die Adresse aus der config.json im Datenordner (Block homeassistant), den Token aus dem Schlüsselbund von macOS
und ersetzt sich dann per execve durch ha-mcp über uvx mit festem Pfad. Läuft in Cowork und im Code-Tab gleich, ab
Python 3.9 (Command Line Tools), nur Standardbibliothek.

Was der Starter ha-mcp mitgibt:
  - die Hausregeln aus ha_regeln.md als HAMCP_CUSTOM_INSTRUCTIONS, sie stehen dann in den Instruktionen des Servers
    und gelten auch ohne geladenen Skill,
  - feste Vorgaben (VORGABEN): keine Settings-Seite im Hintergrund, Geheimnisse in Antworten geschwärzt,
  - erlaubte Schalter aus homeassistant.optionen der config.json (ERLAUBTE_OPTIONEN),
  - mit --lesen READ_ONLY_MODE=true, unabhängig von den Optionen (Server homeassistant-lesen).

Fehlt etwas (kein Block homeassistant, kein uvx, kein Token, falsche Adresse), startet ein leerer MCP-Server ohne
Werkzeuge, dessen Instruktionen den Grund nennen. Der Token steht nie in einer Datei, einem Log oder einer Ausgabe.

--rauchtest [ha-mcp@<version>] startet die Version zweimal (normal und lesend), prüft Start, Pflichtwerkzeuge und
einen Leseaufruf und meldet das Ergebnis in wenigen Zeilen. Braucht Schlüsselbund und Heimnetz, also außerhalb der
Sandbox, mit demselben Python wie in .mcp.json.

config.json (Datenordner wie bei apple und chat: ~/Library/Application Support/Claude Kits/service, für Tests
KITS_DATENORDNER, kein Rückfall auf das Repo):
  "homeassistant": {"url": "http://<host>:8123", "paket": "ha-mcp@<version>", "schluesselbund": "<Dienst>",
                    "uvx": "<Pfad, optional>", "optionen": {"<SCHALTER>": <Wert>}}
"""
import json
import os
import re
import select
import subprocess
import sys
import time
from pathlib import Path

HEIM = Path.home()
ORDNER = Path(__file__).resolve().parent
REGELN = ORDNER / "ha_regeln.md"
APP_DATEN = HEIM / "Library" / "Application Support" / "Claude Kits" / "service"
UMGEBUNG = "KITS_DATENORDNER"
UVX_ORTE = ("/opt/homebrew/bin/uvx", "/usr/local/bin/uvx", str(HEIM / ".local" / "bin" / "uvx"),
            str(HEIM / ".cargo" / "bin" / "uvx"))
SECURITY = "/usr/bin/security"
# Mit dem Rauchtest geprüfte Version, gilt ohne homeassistant.paket. Nie latest: Ein Update von ha-mcp kommt erst nach
# dem Rauchtest ins Paket oder in die config.json.
PAKET_STANDARD = "ha-mcp@9.2.0"
SCHLUESSELBUND_STANDARD = "homeassistant-claude"
PAKET_RE = re.compile(r"ha-mcp@\d+\.\d+\.\d+")
URL_RE = re.compile(r"https?://[A-Za-z0-9.\-\[\]:]+(?::\d+)?/?")
DIENST_RE = re.compile(r"[A-Za-z0-9._-]{1,100}")
WERT_RE = re.compile(r"[A-Za-z0-9_,.\- ]{0,500}")
VERSION = "7.2.1"  # gleich der Version in .claude-plugin/plugin.json

# Feste Vorgaben, homeassistant.optionen darf sie überschreiben.
VORGABEN = {
    "HA_MCP_DISABLE_SETTINGS_UI": "1",  # keine Settings-Seite, die nach der Session weiterläuft
    "REDACT_SECRETS": "true",  # Passwörter in Optionen von Apps und Integrationen geschwärzt
}
# Schalter von ha-mcp, die die config.json setzen darf. Alles andere ist ein Fehler, damit kein Tippfehler still wirkt.
ERLAUBTE_OPTIONEN = ("READ_ONLY_MODE", "REDACT_SECRETS", "DISABLED_TOOLS", "BACKUP_READ_ONLY",
                     "ENABLE_SNAPSHOT_DELETE", "ENABLE_AUTO_BACKUP", "HA_MCP_DISABLE_SETTINGS_UI",
                     "HA_MCP_DISABLE_UPDATE_CHECK")
# Werkzeuge, auf die sich Skill und Regeln verlassen. Der Rauchtest prüft sie.
PFLICHT = ("ha_get_skill_guide", "ha_get_overview", "ha_search", "ha_get_state", "ha_call_service",
           "ha_manage_backup", "ha_reload_core")
SCHREIBEND = "ha_call_service"  # fehlt im Lesemodus


class Grund(Exception):
    """Warum ha-mcp nicht startet, ein Satz ohne Geheimnisse."""


def datenordner():
    wert = os.environ.get(UMGEBUNG, "").strip()
    if wert:
        return Path(wert).expanduser()
    return APP_DATEN if (APP_DATEN / "config.json").is_file() else None


def optionen(roh) -> dict:
    """homeassistant.optionen geprüft als Umgebung: nur erlaubte Schalter, Wahrheitswerte als true und false."""
    if roh is None:
        return {}
    if not isinstance(roh, dict):
        raise Grund("homeassistant.optionen in der config.json ist kein Objekt.")
    aus = {}
    for name, wert in roh.items():
        if name not in ERLAUBTE_OPTIONEN:
            raise Grund(f"homeassistant.optionen: {name} ist nicht erlaubt (erlaubt: {', '.join(ERLAUBTE_OPTIONEN)}).")
        if isinstance(wert, bool):
            wert = "true" if wert else "false"
        if not isinstance(wert, str) or not WERT_RE.fullmatch(wert):
            raise Grund(f"homeassistant.optionen: Wert für {name} ist kein einfacher Text.")
        aus[name] = wert
    return aus


def konfiguration() -> dict:
    ordner = datenordner()
    if ordner is None or not (ordner / "config.json").is_file():
        raise Grund(f"Keine config.json für service gefunden (Ablage {APP_DATEN}). Home Assistant ist nicht eingerichtet.")
    try:
        cfg = json.loads((ordner / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise Grund(f"config.json in {ordner} ist kein gültiges JSON.") from None
    ha = cfg.get("homeassistant") if isinstance(cfg, dict) else None
    if not isinstance(ha, dict):
        raise Grund("Home Assistant ist nicht eingerichtet: Block homeassistant fehlt in der config.json von service.")
    url = ha.get("url")
    if not isinstance(url, str) or not URL_RE.fullmatch(url):
        raise Grund("homeassistant.url in der config.json ist keine Adresse wie http://<host>:8123.")
    paket = ha.get("paket", PAKET_STANDARD)
    if not isinstance(paket, str) or not PAKET_RE.fullmatch(paket):
        raise Grund("homeassistant.paket in der config.json ist kein Paket mit fester Version wie ha-mcp@9.2.0.")
    dienst = ha.get("schluesselbund", SCHLUESSELBUND_STANDARD)
    if not isinstance(dienst, str) or not DIENST_RE.fullmatch(dienst):
        raise Grund("homeassistant.schluesselbund in der config.json ist kein gültiger Name.")
    uvx = ha.get("uvx")
    if uvx is not None and not (isinstance(uvx, str) and os.path.isabs(uvx)):
        raise Grund("homeassistant.uvx in der config.json ist kein absoluter Pfad.")
    return {"url": url.rstrip("/"), "paket": paket, "schluesselbund": dienst, "uvx": uvx,
            "optionen": optionen(ha.get("optionen"))}


def finde_uvx(cfg: dict) -> str:
    for ort in ([cfg["uvx"]] if cfg.get("uvx") else UVX_ORTE):
        if os.path.isfile(ort) and os.access(ort, os.X_OK):
            return ort
    raise Grund("uvx nicht gefunden (Homebrew: brew install uv). Home Assistant startet ohne Werkzeuge.")


def token(dienst: str) -> str:
    """Token aus dem Schlüsselbund. Die Ausgabe von security geht nie in eine Meldung."""
    try:
        lauf = subprocess.run([SECURITY, "find-generic-password", "-s", dienst, "-w"], capture_output=True,
                              text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        raise Grund(f"Schlüsselbund nicht lesbar (Eintrag {dienst}). Beim ersten Start Immer erlauben klicken.") from None
    wert = lauf.stdout.strip()
    if lauf.returncode != 0 or not wert:
        raise Grund(f"Kein Token im Schlüsselbund unter {dienst} oder Zugriff abgelehnt.")
    return wert


def regeln() -> str:
    """Hausregeln für die Instruktionen des Servers. Fehlt die Datei, startet ha-mcp ohne sie."""
    try:
        return REGELN.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def startbefehl(lesen: bool = False, paket=None) -> tuple:
    """(argv, env) für execve. Wirft Grund, wenn etwas fehlt."""
    cfg = konfiguration()
    uvx = finde_uvx(cfg)
    env = dict(os.environ)
    env.update(VORGABEN)
    env.update(cfg["optionen"])
    if lesen:
        env["READ_ONLY_MODE"] = "true"
    text = regeln()
    if text:
        env["HAMCP_CUSTOM_INSTRUCTIONS"] = text
    env["HOMEASSISTANT_URL"] = cfg["url"]
    env["HOMEASSISTANT_TOKEN"] = token(cfg["schluesselbund"])
    pfad = env.get("PATH", "")
    env["PATH"] = ":".join(p for p in [os.path.dirname(uvx), pfad or "/usr/bin:/bin"] if p)
    return [uvx, paket or cfg["paket"]], env


def servername(lesen: bool) -> str:
    return "homeassistant-lesen" if lesen else "homeassistant"


def antwort(nachricht_id, ergebnis=None, fehler=None) -> None:
    aus = {"jsonrpc": "2.0", "id": nachricht_id}
    if fehler:
        aus["error"] = {"code": fehler[0], "message": fehler[1]}
    else:
        aus["result"] = ergebnis
    sys.stdout.write(json.dumps(aus, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def leer_dienen(grund: str, lesen: bool = False) -> int:
    """Kleinster MCP-Server über stdio: initialize, tools/list (leer), ping. Der Grund steht in den Instruktionen."""
    for zeile in sys.stdin:
        try:
            n = json.loads(zeile)
        except ValueError:
            continue
        if not isinstance(n, dict) or "id" not in n:
            continue
        methode = n.get("method")
        if methode == "initialize":
            version = (n.get("params") or {}).get("protocolVersion") or "2025-06-18"
            antwort(n["id"], {"protocolVersion": version, "capabilities": {"tools": {}},
                              "serverInfo": {"name": servername(lesen), "version": VERSION},
                              "instructions": f"Home Assistant ist nicht verfügbar: {grund}"})
        elif methode == "tools/list":
            antwort(n["id"], {"tools": []})
        elif methode == "ping":
            antwort(n["id"], {})
        else:
            antwort(n["id"], fehler=(-32601, f"Home Assistant ist nicht verfügbar: {grund}"))
    return 0


class Sitzung:
    """ha-mcp als Kindprozess über stdio, für den Rauchtest. Liest Zeilen mit Frist, ohne Threads."""

    def __init__(self, argv: list, env: dict):
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     env=env, text=True, bufsize=1)
        self.naechste = 0

    def senden(self, methode: str, params=None, mit_id: bool = True):
        n = {"jsonrpc": "2.0", "method": methode}
        if params is not None:
            n["params"] = params
        if mit_id:
            self.naechste += 1
            n["id"] = self.naechste
        self.proc.stdin.write(json.dumps(n) + "\n")
        self.proc.stdin.flush()
        return n.get("id")

    def warten(self, nachricht_id, frist: float) -> dict:
        ende = time.monotonic() + frist
        while True:
            rest = ende - time.monotonic()
            if rest <= 0:
                raise Grund(f"keine Antwort nach {int(frist)} s")
            bereit, _w, _x = select.select([self.proc.stdout], [], [], rest)
            if not bereit:
                continue
            zeile = self.proc.stdout.readline()
            if not zeile:
                raise Grund("ha-mcp hat sich beendet")
            try:
                n = json.loads(zeile)
            except ValueError:
                continue
            if isinstance(n, dict) and n.get("id") == nachricht_id:
                if "error" in n:
                    raise Grund(f"Fehler {n['error'].get('code')}: {str(n['error'].get('message'))[:200]}")
                return n.get("result") or {}

    def frage(self, methode: str, params=None, frist: float = 60) -> dict:
        return self.warten(self.senden(methode, params), frist)

    def ende(self) -> None:
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()
            self.proc.wait()
        self.proc.stdout.close()


def rauchlauf(paket: str, lesen: bool) -> list:
    """Ein Start von ha-mcp: Zeilen fürs Ergebnis. Wirft Grund beim ersten Fehler."""
    argv, env = startbefehl(lesen=lesen, paket=paket)
    beginn = time.monotonic()
    s = Sitzung(argv, env)
    try:
        init = s.frage("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "rauchtest", "version": VERSION}}, frist=300)
        s.senden("notifications/initialized", mit_id=False)
        dauer = int(time.monotonic() - beginn)
        version = (init.get("serverInfo") or {}).get("version", "?")
        if regeln() and "Hausregeln" not in (init.get("instructions") or ""):
            raise Grund("Hausregeln fehlen in den Instruktionen")
        namen = {w.get("name") for w in s.frage("tools/list").get("tools", [])}
        zeilen = [f"gestartet in {dauer} s, Server {version}, {len(namen)} Werkzeuge"]
        if lesen:
            if SCHREIBEND in namen:
                raise Grund(f"{SCHREIBEND} ist im Lesemodus sichtbar")
            zeilen.append(f"Lesemodus wirkt ({SCHREIBEND} fehlt)")
        else:
            fehlen = [p for p in PFLICHT if p not in namen]
            if fehlen:
                raise Grund(f"Pflichtwerkzeuge fehlen: {', '.join(fehlen)}")
            zeilen.append("Pflichtwerkzeuge da")
        ergebnis = s.frage("tools/call", {"name": "ha_get_overview", "arguments": {}}, frist=120)
        if ergebnis.get("isError"):
            raise Grund("ha_get_overview meldet einen Fehler")
        zeilen.append("ha_get_overview antwortet")
        return zeilen
    finally:
        s.ende()


def rauchtest(paket=None) -> int:
    try:
        paket = paket or konfiguration()["paket"]
    except Grund as g:
        print(f"Rauchtest nicht möglich: {g}")
        return 1
    if not PAKET_RE.fullmatch(paket):
        print("Rauchtest nicht möglich: Paket mit fester Version angeben, etwa ha-mcp@9.2.0.")
        return 1
    ok = True
    for lesen in (False, True):
        name = servername(lesen)
        try:
            print(f"{paket} als {name}: " + ", ".join(rauchlauf(paket, lesen)))
        except Grund as g:
            print(f"{paket} als {name}: FEHLER, {g}")
            ok = False
    print("Rauchtest bestanden." if ok else "Rauchtest nicht bestanden, Version nicht übernehmen.")
    return 0 if ok else 1


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--rauchtest"]:
        return rauchtest(argv[1] if len(argv) > 1 else None)
    lesen = "--lesen" in argv
    try:
        befehl, env = startbefehl(lesen=lesen)
    except Grund as g:
        sys.stderr.write(f"{servername(lesen)}: {g}\n")
        return leer_dienen(str(g), lesen)
    os.execve(befehl[0], befehl, env)
    return 1  # nicht erreicht


if __name__ == "__main__":
    sys.exit(main())
