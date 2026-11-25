#!/usr/bin/env python3
"""synology_start.py: Einrichtung und Prüfung des MCP-Servers synology, nur im Terminal des Nutzers.

  synology_start.py --einrichten   fragt Adresse, Port, Admin-Konto und Heimnetz, schreibt den Block synology in die
                                   config.json von service, erzeugt zwei Schlüssel (lesen, schreiben) mit zufälliger
                                   Passphrase im Schlüsselbund, pinnt den Host-Schlüssel der DiskStation, legt den Ordner
                                   claude-gate-neu für install.sh an und zeigt die zwei Befehle für die DiskStation.
  synology_start.py --pruefen      nas_status mit beiden Schlüsseln, und dass der Leseschlüssel kein Schreibverb erreicht.

Läuft mit dem Python der Command Line Tools, braucht Schlüsselbund und Heimnetz, also nie in der Sandbox. Die
Passphrase sieht niemand: Sie entsteht hier, geht an ssh-keygen und über ein kurzlebiges askpass an ssh-add, das sie
im Schlüsselbund ablegt. Wiederholbar: Vorhandene Schlüssel bleiben, ein geänderter Host-Schlüssel nur nach Ja.
"""
from __future__ import annotations

import ipaddress
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import mcp_basis as mb
import synology_server as ss

BUENDEL = "claude-gate-neu"
NAS_DATEIEN = ("install.sh", "eingang.sh", "gate.sh", "VERSION")
# DSM erlaubt im Benutzernamen Groß- und Kleinbuchstaben, Ziffern und - _ . (ohne Unterschied von Groß und Klein)
ADMIN_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}")
NETZ_RE = re.compile(r"\d{1,3}(\.\d{1,3}){3}(/\d{1,2})?(,\d{1,3}(\.\d{1,3}){3}(/\d{1,2})?){0,4}")


class Abbruch(Exception):
    pass


def frage(text: str, vorgabe: str = "") -> str:
    wert = input(f"{text}{f' [{vorgabe}]' if vorgabe else ''}: ").strip()
    return wert or vorgabe


def bisher() -> dict:
    cfg = mb._config(ss.datenordner())
    s = cfg.get("synology")
    return s if isinstance(s, dict) else {}


def angaben_abfragen(alt: dict) -> dict:
    host = frage("Adresse der DiskStation im Heimnetz (IP oder Name)", str(alt.get("host", "")))
    if not ss.HOST_RE.fullmatch(host):
        raise Abbruch("Das ist keine Adresse wie 192.168.1.20 oder nas.local.")
    port = frage("SSH-Port der DiskStation", str(alt.get("port", 22)))
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise Abbruch("Der Port ist eine Zahl von 1 bis 65535.")
    benutzer = frage("Benutzer für Claude auf der DiskStation, genau wie in DSM geschrieben",
                     str(alt.get("benutzer", "claude")))
    if not ss.BENUTZER_RE.fullmatch(benutzer) or benutzer.lower() != "claude":
        raise Abbruch("Der Benutzer heißt claude, in beliebiger Schreibweise wie in DSM (install.sh sucht diesen Namen).")
    admin = frage("Dein eigenes Admin-Konto auf der DiskStation (nur für die Befehle unten)", str(alt.get("admin", "")))
    if not ADMIN_RE.fullmatch(admin):
        raise Abbruch("Das ist kein Benutzername (Buchstaben, Ziffern, - _ . ohne Leerzeichen).")
    try:
        vorschlag = str(ipaddress.ip_network(f"{host}/24", strict=False))
    except ValueError:
        vorschlag = ""
    netz = frage("Heimnetz, aus dem der Mac kommt (etwa 192.168.1.0/24)", str(alt.get("netz", vorschlag)))
    if not NETZ_RE.fullmatch(netz):
        raise Abbruch("Das Heimnetz hat die Form 192.168.1.0/24, mehrere mit Komma.")
    return {**alt, "host": host, "port": int(port), "benutzer": benutzer, "admin": admin,
            "netz": netz, "stop_timeout": alt.get("stop_timeout", 120)}


def passphrase_ablegen(schluessel: Path, passphrase: str) -> None:
    """Passphrase über ssh-add --apple-use-keychain in den Schlüsselbund, danach den Schlüssel wieder aus dem Agenten
    nehmen: Andere Programme sollen ihn nicht über den Agenten nutzen können."""
    with tempfile.TemporaryDirectory() as t:
        askpass = Path(t) / "askpass.sh"
        askpass.write_text('#!/bin/sh\nprintf "%s\\n" "$KITS_SSH_PASS"\n', encoding="utf-8")
        askpass.chmod(0o700)
        env = {**os.environ, "SSH_ASKPASS": str(askpass), "SSH_ASKPASS_REQUIRE": "force", "DISPLAY": ":0",
               "KITS_SSH_PASS": passphrase}
        lauf = subprocess.run(["/usr/bin/ssh-add", "--apple-use-keychain", str(schluessel)], env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        if lauf.returncode != 0:
            raise Abbruch(f"ssh-add konnte die Passphrase nicht im Schlüsselbund ablegen: {lauf.stderr.strip()[:200]}")
    subprocess.run(["/usr/bin/ssh-add", "-d", str(schluessel)], capture_output=True, timeout=30)


def schluessel_erzeugen(ordner: Path, rolle: str, schluesselbund: bool = True) -> bool:
    """ed25519 mit zufälliger Passphrase. False, wenn der Schlüssel schon da ist."""
    pfad = ordner / rolle
    if pfad.is_file() and (ordner / f"{rolle}.pub").is_file():
        return False
    passphrase = secrets.token_urlsafe(32)
    for alt in (pfad, ordner / f"{rolle}.pub"):
        if alt.exists():
            alt.unlink()
    lauf = subprocess.run(["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", passphrase, "-C", f"claude-{rolle}",
                           "-f", str(pfad)], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    if lauf.returncode != 0:
        raise Abbruch(f"ssh-keygen scheiterte: {lauf.stderr.strip()[:200]}")
    pfad.chmod(0o600)
    if schluesselbund:
        passphrase_ablegen(pfad, passphrase)
    return True


def host_pinnen(cfg: dict, ordner: Path, ja=frage) -> str:
    """Host-Schlüssel (ed25519) der DiskStation holen und in known_hosts im Datenordner ablegen. Ein anderer als der
    gespeicherte nur nach Ja. Gibt den Fingerabdruck zurück."""
    lauf = subprocess.run(["/usr/bin/ssh-keyscan", "-T", "10", "-p", str(cfg["port"]), "-t", "ed25519", cfg["host"]],
                          capture_output=True, text=True, timeout=30)
    zeilen = [z for z in lauf.stdout.splitlines() if z and not z.startswith("#")]
    if not zeilen:
        raise Abbruch(f"Kein Host-Schlüssel von {cfg['host']}:{cfg['port']}. Ist SSH in DSM an und der Mac im Heimnetz?")
    neu = zeilen[0] + "\n"
    datei = ordner / "known_hosts"
    if datei.is_file() and datei.read_text(encoding="utf-8") != neu:
        if ja("Der Host-Schlüssel der DiskStation hat sich geändert. Nur nach einer Neuinstallation von DSM normal. "
              "Ersetzen? (ja/nein)", "nein").lower() != "ja":
            raise Abbruch("Host-Schlüssel nicht ersetzt.")
    datei.write_text(neu, encoding="utf-8")
    datei.chmod(0o600)
    fp = subprocess.run(["/usr/bin/ssh-keygen", "-lf", str(datei)], capture_output=True, text=True, timeout=30)
    return fp.stdout.strip()


def buendel(cfg: dict, ordner: Path) -> Path:
    """Ordner claude-gate-neu im Datenordner: Skripte aus dem Plugin, die zwei öffentlichen Schlüssel, das Heimnetz."""
    ziel = ss.datenordner() / BUENDEL
    if ziel.exists():
        shutil.rmtree(ziel)
    ziel.mkdir(parents=True)
    for f in NAS_DATEIEN:
        shutil.copy(ss.NAS_ORDNER / f, ziel / f)
    for rolle in ss.ROLLEN:
        if (ordner / f"{rolle}.pub").is_file():
            shutil.copy(ordner / f"{rolle}.pub", ziel / f"{rolle}.pub")
    (ziel / "netz").write_text(cfg["netz"] + "\n", encoding="utf-8")
    return ziel


def befehle(cfg: dict, ziel: Path) -> list:
    """Die zwei Befehle für das Terminal: Ordner kopieren, install.sh mit sudo starten."""
    dateien = " ".join(f.name for f in sorted(ziel.iterdir()))
    ssh = f"ssh -p {cfg['port']} {cfg['admin']}@{cfg['host']}"
    return [f"COPYFILE_DISABLE=1 tar -C '{ziel}' -cf - {dateien} | {ssh} 'mkdir -p {BUENDEL} && tar -xf - -C {BUENDEL}'",
            f"ssh -t -p {cfg['port']} {cfg['admin']}@{cfg['host']} 'sudo bash {BUENDEL}/install.sh'"]


def einrichten() -> int:
    alt = bisher()
    cfg = angaben_abfragen(alt)
    mb.einstellungen_schreiben(ss.PLUGIN, {"synology": cfg})
    ordner = ss.ssh_ordner()
    ordner.mkdir(parents=True, exist_ok=True)
    ordner.chmod(0o700)
    for rolle in ss.ROLLEN:
        neu = schluessel_erzeugen(ordner, rolle)
        print(f"Schlüssel {rolle}: {'neu, Passphrase im Schlüsselbund' if neu else 'schon da, bleibt'}")
    print(f"Host-Schlüssel gepinnt: {host_pinnen(cfg, ordner)}")
    ziel = buendel(cfg, ordner)
    print("\nAuf der DiskStation einrichten, im Terminal nacheinander (fragt dein Passwort):\n")
    for b in befehle(cfg, ziel):
        print(b + "\n")
    print("Danach: synology_start.py --pruefen")
    return 0


def pruefen() -> int:
    cfg = ss.konfiguration()
    ok = True
    for rolle in ss.ROLLEN:
        ss.schluessel_da(rolle)
        code, eintraege, meldung = ss.Verbindung(cfg)(rolle, ["nas_status"])
        system = next((e for e in eintraege if e.get("art") == "system"), {})
        pruefung = next((e for e in eintraege if e.get("art") == "pruefung"), {})
        if code == 0 and system:
            print(f"{rolle}: DiskStation {system.get('modell')}, DSM {system.get('dsm')}, Prüfskript {system.get('gate')} "
                  f"(Plugin {ss.erwartete_version()}), sudoers {'ok' if pruefung.get('sudoers') else 'abweichend'}")
            ok = ok and system.get("gate") == ss.erwartete_version() and bool(pruefung.get("sudoers"))
        else:
            print(f"{rolle}: FEHLER {meldung or code}")
            ok = False
    code, eintraege, meldung = ss.Verbindung(cfg)("lesen", ["container_neustart", "name=probe"])
    if code == 2:
        print("lesen: Schreibverb abgelehnt, wie es sein soll")
    else:
        print(f"lesen: FEHLER, Schreibverb nicht abgelehnt (Code {code} {meldung})")
        ok = False
    print("Prüfung bestanden." if ok else "Prüfung nicht bestanden.")
    return 0 if ok else 1


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv[:1] == ["--einrichten"]:
            return einrichten()
        if argv[:1] == ["--pruefen"]:
            return pruefen()
    except (Abbruch, ss.Grund, mb.Fehler) as e:
        print(f"ABBRUCH: {e}")
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nAbgebrochen.")
        return 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
