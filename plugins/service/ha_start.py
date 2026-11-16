#!/usr/bin/env python3
"""ha_start.py: Starter für den MCP-Server homeassistant (ha-mcp) aus dem Plugin service.

Liest die Adresse aus der config.json im Datenordner (Block homeassistant), den Token aus dem Schlüsselbund von macOS
und ersetzt sich dann per execve durch ha-mcp über uvx mit festem Pfad. Läuft in Cowork und im Code-Tab gleich, ab
Python 3.9 (Command Line Tools), nur Standardbibliothek.

Fehlt etwas (kein Block homeassistant, kein uvx, kein Token, falsche Adresse), startet ein leerer MCP-Server ohne
Werkzeuge, dessen Instruktionen den Grund nennen. Der Token steht nie in einer Datei, einem Log oder einer Ausgabe.

config.json (Datenordner wie bei apple und chat: ~/Library/Application Support/Claude Kits/service, für Tests
KITS_DATENORDNER, kein Rückfall auf das Repo):
  "homeassistant": {"url": "http://<host>:8123", "paket": "ha-mcp@<version>", "schluesselbund": "<Dienst>",
                    "uvx": "<Pfad, optional>"}
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HEIM = Path.home()
APP_DATEN = HEIM / "Library" / "Application Support" / "Claude Kits" / "service"
UMGEBUNG = "KITS_DATENORDNER"
UVX_ORTE = ("/opt/homebrew/bin/uvx", "/usr/local/bin/uvx", str(HEIM / ".local" / "bin" / "uvx"),
            str(HEIM / ".cargo" / "bin" / "uvx"))
SECURITY = "/usr/bin/security"
PAKET_STANDARD = "ha-mcp@latest"
SCHLUESSELBUND_STANDARD = "homeassistant-claude"
PAKET_RE = re.compile(r"ha-mcp(?:@[A-Za-z0-9.]+)?")
URL_RE = re.compile(r"https?://[A-Za-z0-9.\-\[\]:]+(?::\d+)?/?")
DIENST_RE = re.compile(r"[A-Za-z0-9._-]{1,100}")
VERSION = "6.3.1"


class Grund(Exception):
    """Warum ha-mcp nicht startet, ein Satz ohne Geheimnisse."""


def datenordner():
    wert = os.environ.get(UMGEBUNG, "").strip()
    if wert:
        return Path(wert).expanduser()
    return APP_DATEN if (APP_DATEN / "config.json").is_file() else None


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
        raise Grund("homeassistant.paket in der config.json ist kein Paket wie ha-mcp@<version>.")
    dienst = ha.get("schluesselbund", SCHLUESSELBUND_STANDARD)
    if not isinstance(dienst, str) or not DIENST_RE.fullmatch(dienst):
        raise Grund("homeassistant.schluesselbund in der config.json ist kein gültiger Name.")
    uvx = ha.get("uvx")
    if uvx is not None and not (isinstance(uvx, str) and os.path.isabs(uvx)):
        raise Grund("homeassistant.uvx in der config.json ist kein absoluter Pfad.")
    return {"url": url.rstrip("/"), "paket": paket, "schluesselbund": dienst, "uvx": uvx}


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


def startbefehl() -> tuple:
    """(argv, env) für execve. Wirft Grund, wenn etwas fehlt."""
    cfg = konfiguration()
    uvx = finde_uvx(cfg)
    env = dict(os.environ)
    env["HOMEASSISTANT_URL"] = cfg["url"]
    env["HOMEASSISTANT_TOKEN"] = token(cfg["schluesselbund"])
    pfad = env.get("PATH", "")
    env["PATH"] = ":".join(p for p in [os.path.dirname(uvx), pfad or "/usr/bin:/bin"] if p)
    return [uvx, cfg["paket"]], env


def antwort(nachricht_id, ergebnis=None, fehler=None) -> None:
    aus = {"jsonrpc": "2.0", "id": nachricht_id}
    if fehler:
        aus["error"] = {"code": fehler[0], "message": fehler[1]}
    else:
        aus["result"] = ergebnis
    sys.stdout.write(json.dumps(aus, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def leer_dienen(grund: str) -> int:
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
                              "serverInfo": {"name": "homeassistant", "version": VERSION},
                              "instructions": f"Home Assistant ist nicht verfügbar: {grund}"})
        elif methode == "tools/list":
            antwort(n["id"], {"tools": []})
        elif methode == "ping":
            antwort(n["id"], {})
        else:
            antwort(n["id"], fehler=(-32601, f"Home Assistant ist nicht verfügbar: {grund}"))
    return 0


def main() -> int:
    try:
        argv, env = startbefehl()
    except Grund as g:
        sys.stderr.write(f"homeassistant: {g}\n")
        return leer_dienen(str(g))
    os.execve(argv[0], argv, env)
    return 1  # nicht erreicht


if __name__ == "__main__":
    sys.exit(main())
