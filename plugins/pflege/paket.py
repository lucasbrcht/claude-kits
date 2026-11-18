#!/usr/bin/env python3
"""paket.py: Pflege des Pakets claude-kits im Code-Tab.

Der Alltag läuft in Cowork über die Werkzeuge der Plugins. Im Code-Tab bleiben Pflege und Release: Plugins aus dem
Ordner laden, die CLAUDE.md der Instanz aus dem Kontextordner, wenige Rechte für die Pflege, Lesen und Schreiben im
Datenordner der Plugins (~/Library/Application Support/Claude Kits), die Sperren der Apple-Datenordner, Prüfen und ZIPs
für den Upload.

  python3 paket.py                 Trockenlauf: was sich in settings.json und CLAUDE.md der Instanz ändert
  python3 paket.py --apply         schreibt beides (im Terminal, der Auto-Modus lässt es aus der Session nicht zu)
  python3 paket.py --pruefen       Skills, gleiche Dateien in den Plugins, SICHERHEIT.md, Doku-Tests von apple und
                                   chat, Persönliches in versionierten Dateien
  python3 paket.py --zips ORDNER   je Plugin <name>-<version>.zip aus dem letzten Commit, ohne tests/, kit.json und
                                   was .gitattributes des Plugins mit export-ignore ausnimmt (eigene Plugins dazu)
  python3 paket.py --instructions  Text für Instructions for Claude: Profil ohne nur-code-Teile nach
                                   <Kontextordner>/einrichtung/instructions.md (wie der Skill einrichten)
  python3 paket.py --einrichtung NAME ...
                                   zweite Instanz auf demselben Rechner: einrichtung.<NAME>.json mit eigenem Stand.
                                   In einer Session wählt das Skript sie selbst (settings im Config-Ordner der
                                   Instanz), im Terminal gilt ohne Angabe immer einrichtung.json

Einstellungen des Nutzers: einrichtung.json im Paketordner (nicht im Git), Vorlage einrichtung.example.json. Die
CLAUDE.md der Instanz entsteht aus profil.md plus CLAUDE.md (Index des Projekts) im Kontextordner, ohne profil.md aus
der CLAUDE.md allein. Nur Standardbibliothek.
"""
import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PAKET = Path(__file__).resolve().parent.parent.parent  # claude-kits/
PLUGINS = PAKET / "plugins"
MARKETPLACE = "claude-kits"
CONFIG = PAKET / "einrichtung.json"
STATE = PAKET / ".einrichtung-state.json"
EINRICHTUNG_NAME = ""  # gewählte zweite Einrichtung (einrichtung.<name>.json), leer für einrichtung.json
KONTEXT_STANDARD = "~/Claude Kits/kontext"
# Datenordner der Plugins (config.json, style/, .venv, .fehler.jsonl), die Server lesen nur hier. Der Code-Tab darf ihn
# lesen und schreiben (Einrichtung, Stilprofile), nur die .venv bleibt für Bash gesperrt.
DATENORDNER = Path.home() / "Library" / "Application Support" / "Claude Kits"
CLAUDE_MD_MARKE = "<!-- Erzeugt von paket.py aus "  # nur eine so markierte CLAUDE.md wird überschrieben
PROFIL = "profil.md"
NAME_RE = re.compile(r"[a-z][a-z0-9-]*")
LISTEN = ("gesperrt", "rechte_extra", "fragen_extra", "verbote_extra", "sandbox_ausnahmen", "namen", "namen_aus",
          "nummern", "ignorieren")
FELDER = ("settings", "kontext", "plugins", "eigene_plugins", "output_style") + LISTEN
SANDBOX_SPERRE = ("[a-zA-Z0-9_]*", ".venv", ".claude", ".git/hooks", ".git/config")  # Bash schreibt hier nie
SCHREIBWORT_RE = re.compile(r"(?<![\w-])(?:send|reply|forward|replace)(?![\w-])")
ZIP_OHNE = ("tests", "kit.json")
KOMMENTAR_HTML_RE = re.compile(r"<!--.*?-->\n?", re.S)
NUR_CODE_BLOCK_RE = re.compile(r"<!--\s*nur-code\s*-->.*?<!--\s*/nur-code\s*-->\n?", re.S)

# Daten, die nie ins Paket gehören
SENSIBEL = (
    ("Telefonnummer", re.compile(
        r"(?<![\w+])(?:(?:\+|00)[1-9]\d(?:[ /-]?\d){6,}|01[5-7]\d(?:[ /-]?\d){6,}|0[2-9]\d{1,4}[ /-]\d{4,}"
        r"|0[2-9]\d{7,12})(?![\w])")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b")),
    ("WhatsApp-Kennung", re.compile(r"@(?:s\.whatsapp\.net|g\.us|lid)\b")),
    ("Zugangsdaten", re.compile(r"(?i)\b(?:passwort|password|kennwort|pin|api[-_ ]?key|token)\s*[:=]\s*\S+")),
)
MAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}(?![\w-])")
MAIL_BEISPIEL = ("example.org", "example.com", "example.net", "example.invalid", "b.de", "beispiel.de", "domain.de",
                 "firma.de", "x.de", "y.de", "c.de", "d.de", "f.de", "github.com", "whatsapp.net", "g.us")
PLATZHALTER_RE = re.compile(r"\{\{[A-Z][A-Z0-9_]*\}\}")
PERSOENLICH_ENDUNGEN = (".md", ".json", ".txt", ".py", ".sh", ".html")
SKILL_KB = 8
# Liegen gleich in apple und chat und als Kopie in Plugins eigener Marketplaces (eigene_plugins der Einrichtung, etwa
# arbeit im work-kit), nur zusammen ändern. --pruefen vergleicht alle Stellen, die diese Instanz lesen kann.
GLEICHE_PLUGINS = ("apple", "chat")
GLEICHE_DATEIEN = ("kit_basis.py", "mcp_basis.py", "tests/test_kit_basis.py", "tests/test_mcp_basis.py")
# Gefahren und Gegenmaßnahmen im Hauptordner. Jedes Werkzeug der Stufe nachfrage aus den Plugins mit Server steht dort,
# deren Doku-Test (tests/test_doku.py: jedes Werkzeug in genau einer Werkzeugtabelle) läuft bei --pruefen mit.
SICHERHEIT = "SICHERHEIT.md"
SERVER_PLUGINS = ("apple", "chat")
DOKU_TEST = "tests/test_doku.py"
DOKU_ZEIT = 120


class KitFehler(Exception):
    pass


def einrichtung_name(wahl: str = None) -> str:
    """Welche Einrichtung gilt: ausdrücklich über --einrichtung oder KITS_EINRICHTUNG. Sonst nur in einer Session von
    Claude Code (CLAUDECODE gesetzt) die Datei, deren settings im Config-Ordner dieser Instanz liegt. Im Terminal ohne
    Angabe immer einrichtung.json: Dort entscheidet nie die Umgebung, in welche Instanz geschrieben wird."""
    name = wahl or os.environ.get("KITS_EINRICHTUNG", "").strip()
    if name:
        if name == "example" or not NAME_RE.fullmatch(name):
            raise KitFehler(f"--einrichtung {name}: Name aus Kleinbuchstaben, Ziffern und Bindestrich, nicht example")
        if not (PAKET / f"einrichtung.{name}.json").is_file():
            raise KitFehler(f"einrichtung.{name}.json fehlt im Paketordner {PAKET}")
        return name
    if not os.environ.get("CLAUDECODE"):
        return ""
    ordner = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser().resolve()
    for p in sorted(PAKET.glob("einrichtung.*.json")):
        n = p.name[len("einrichtung."):-len(".json")]
        if n == "example" or not NAME_RE.fullmatch(n):
            continue
        try:
            ziel = json.loads(p.read_text(encoding="utf-8")).get("settings")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(ziel, str) and Path(ziel).expanduser().resolve().parent == ordner:
            return n
    return ""


def waehle_einrichtung(name: str) -> None:
    global CONFIG, STATE, EINRICHTUNG_NAME
    if name:
        EINRICHTUNG_NAME = name
        CONFIG = PAKET / f"einrichtung.{name}.json"
        STATE = PAKET / f".einrichtung-state.{name}.json"


def load_json(path: Path, was: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise KitFehler(f"{was}: nicht lesbar ({e.strerror})")
    except ValueError as e:
        raise KitFehler(f"{was}: kein gültiges JSON ({e})")


def atomic_write(path: Path, data: bytes) -> None:
    """Schreibt über eine Temp-Datei und benennt dann um, damit nie eine halbe Datei entsteht."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_json(path: Path, data) -> None:
    atomic_write(path, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode())


def eindeutig(liste) -> list:
    return list(dict.fromkeys(liste))


def _texte(wert) -> bool:
    return isinstance(wert, list) and all(isinstance(x, str) and x for x in wert)


# ---------- Einstellungen ----------

def plugin_ordner() -> list:
    """Die Plugins des Marketplace in der Reihenfolge von marketplace.json."""
    m = load_json(PAKET / ".claude-plugin" / "marketplace.json", "marketplace.json")
    return [PAKET / p["source"] for p in m["plugins"]]


def eigene_marktplaetze(cfg: dict) -> list:
    """Eigene lokale Marketplaces neben dem Paket (eigene_plugins {Name: Ordner}): [(Name, Ordner, [(Plugin, Ordner)])]."""
    aus = []
    for markt, ordner in cfg.get("eigene_plugins", {}).items():
        ordner = Path(ordner).expanduser().resolve()
        m = load_json(ordner / ".claude-plugin" / "marketplace.json", f"marketplace.json von {markt}")
        plugins = []
        for p in m.get("plugins", []) if isinstance(m, dict) else []:
            quelle = p.get("source") if isinstance(p, dict) else None
            if not (isinstance(quelle, str) and isinstance(p.get("name"), str) and NAME_RE.fullmatch(p["name"])
                    and ".." not in Path(quelle).parts and not quelle.startswith(("/", "~"))):
                raise KitFehler(f"Marketplace {markt}: Plugin {p!r} braucht name und source als Ordner darin")
            plugins.append((p["name"], (ordner / quelle).resolve()))
        aus.append((markt, ordner, plugins))
    return aus


def kit_verbote(ordner: Path) -> list:
    """Sperren aus kit.json eines Plugins (Datenordner der Apple-Apps, die nur der Server liest), sonst nichts."""
    if not (ordner / "kit.json").is_file():
        return []
    v = load_json(ordner / "kit.json", f"kit.json von {ordner.name}").get("verbote", [])
    if not (v == [] or _texte(v)):
        raise KitFehler(f"kit.json von {ordner.name}: verbote ist eine Liste von Regeln")
    return v


def lade_einrichtung() -> dict:
    """einrichtung.json geprüft, ohne Datei die Standardwerte (alle Plugins)."""
    roh = load_json(CONFIG, CONFIG.name) if CONFIG.is_file() else {}
    if not isinstance(roh, dict):
        raise KitFehler(f"{CONFIG.name} muss ein Objekt sein")
    unbekannt = [k for k in roh if not k.startswith("_") and k not in FELDER]
    if unbekannt:
        raise KitFehler(f"{CONFIG.name}: Feld {', '.join(unbekannt)} unbekannt (gilt seit basis 6.3.0 nicht mehr)")
    namen = [o.name for o in plugin_ordner()]
    plugins = roh.get("plugins", namen)  # fehlt: alle. Liste oder Objekt {Plugin: {...}}, es zählen die Namen
    if not isinstance(plugins, (list, dict)) or any(n not in namen for n in plugins):
        raise KitFehler(f"{CONFIG.name}: plugins nennt Plugins des Pakets ({', '.join(namen)})")
    for k in LISTEN:
        if not (roh.get(k, []) == [] or _texte(roh.get(k))):
            raise KitFehler(f"{CONFIG.name}: {k} ist eine Liste von Texten")
    for k in ("settings", "kontext", "output_style"):
        if k in roh and not isinstance(roh[k], str):
            raise KitFehler(f"{CONFIG.name}: {k} ist ein Text")
    eigene = roh.get("eigene_plugins", {})
    if not (isinstance(eigene, dict) and all(isinstance(k, str) and NAME_RE.fullmatch(k) and k != MARKETPLACE
                                             and isinstance(v, str) and v for k, v in eigene.items())):
        raise KitFehler(f"{CONFIG.name}: eigene_plugins ist ein Objekt {{Marketplace: Ordner}}, nicht {MARKETPLACE}")
    for r in roh.get("rechte_extra", []):
        if SCHREIBWORT_RE.search(r.replace("_", " ")):
            raise KitFehler(f"{CONFIG.name}: rechte_extra darf nichts senden, gehört unter fragen_extra: {r}")
    return {**roh, "plugins": list(plugins), "eigene_plugins": eigene}


def settings_pfad(cfg: dict) -> Path:
    if cfg.get("settings"):
        return Path(cfg["settings"]).expanduser()
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser() / "settings.json"


def kontext_ordner(cfg: dict) -> Path:
    return Path(cfg.get("kontext") or KONTEXT_STANDARD).expanduser()


def gewuenschte_einstellungen(cfg: dict) -> dict:
    """Listen-Einträge in settings.json, die dieses Skript verwaltet: Sperren der Plugins, Rechte für die Pflege des
    Kontextordners und die Extras aus der Einrichtung. Für den Alltag gibt es keine Regeln mehr."""
    ordner = [p for p in plugin_ordner() if p.name in cfg["plugins"]]
    eigene = eigene_marktplaetze(cfg)
    ordner += [p for _m, _o, plugins in eigene for _n, p in plugins]
    k = kontext_ordner(cfg)
    rechte = [f"Read(/{k}/**)", f"Edit(/{k}/wissen/**)", f"Edit(/{k}/einrichtung/**)"] + [
        f'Bash(git -C "{k}" {b})' for b in ("status --short", "diff *", "add -A", "commit -q -m *", "log --oneline *")]
    rechte += [f"Read(/{DATENORDNER}/**)", f"Edit(/{DATENORDNER}/**)"]
    rechte += [f'Bash(git -C "{PAKET}" describe --tags)'] + cfg.get("rechte_extra", [])
    fragen = [f"Edit(/{k}/CLAUDE.md)", f"Edit(/{k}/{PROFIL})", f"Edit(/{CONFIG})"]
    fragen += [f"Edit(/{p / 'kit.json'})" for p in ordner if (p / "kit.json").is_file()] + cfg.get("fragen_extra", [])
    verbote = [v for p in ordner for v in kit_verbote(p)] + cfg.get("verbote_extra", [])
    sperre = [f"{b}/{m}" for b in [PAKET] + ordner for m in SANDBOX_SPERRE]
    sperre += [f"{DATENORDNER / p.name}/.venv" for p in ordner]
    for g in cfg.get("gesperrt", []):  # Ordner, die diese Instanz nie liest oder schreibt (Gegenseite)
        g = Path(g).expanduser()
        verbote += [f"Read(/{g}/**)", f"Edit(/{g}/**)"]
        sperre.append(str(g))
    return {
        "permissions.additionalDirectories": eindeutig([str(PAKET), str(k), str(DATENORDNER)]
                                                       + [str(o) for _m, o, _p in eigene]),
        "permissions.allow": eindeutig(rechte),
        "permissions.ask": eindeutig(fragen),
        "permissions.deny": eindeutig(verbote),
        "sandbox.excludedCommands": eindeutig(cfg.get("sandbox_ausnahmen", [])),
        "sandbox.filesystem.denyWrite": eindeutig(sperre),
    }


LABELS = {
    "permissions.additionalDirectories": "Arbeitsordner", "permissions.allow": "erlaubt",
    "permissions.ask": "fragt nach", "permissions.deny": "gesperrt", "sandbox.excludedCommands": "ohne Sandbox",
    "sandbox.filesystem.denyWrite": "Sandbox gesperrt",
}


def eintrag(s: dict, key: str, anlegen: bool = False) -> tuple:
    """(Objekt, Feld) für einen Schlüssel wie sandbox.filesystem.denyWrite."""
    *wege, feld = key.split(".")
    for w in wege:
        s = s.setdefault(w, {}) if anlegen else s.get(w, {})
    return s, feld


def settings_form(s, path: Path) -> None:
    if not isinstance(s, dict):
        raise KitFehler(f"settings.json ist kein JSON-Objekt ({path})")
    for sect in ("permissions", "sandbox", "extraKnownMarketplaces", "enabledPlugins"):
        if sect in s and not isinstance(s[sect], dict):
            raise KitFehler(f"settings.json: {sect} ist kein Objekt ({path})")
    for key in LABELS:
        obj, feld = eintrag(s, key)
        if not isinstance(obj, dict) or not isinstance(obj.get(feld, []), list):
            raise KitFehler(f"settings.json: {key} ist keine Liste ({path})")


def lade_state() -> dict:
    try:
        s = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return s if isinstance(s, dict) else {}


def plan_settings(cfg: dict, state: dict, pfad: Path = None):
    """(Pfad, neue settings.json, Änderungen, neuer Stand). Fremde Einträge bleiben, Einträge, die dieses Skript früher
    gesetzt hat (laut Stand) und die nicht mehr gewünscht sind, verschwinden."""
    pfad = pfad or settings_pfad(cfg)
    aktuell = load_json(pfad, "settings.json") if pfad.exists() else {}
    settings_form(aktuell, pfad)
    neu = json.loads(json.dumps(aktuell))
    aenderungen = []
    soll = gewuenschte_einstellungen(cfg)
    for key, will in soll.items():
        obj, feld = eintrag(neu, key)
        if not will and not state.get(key) and feld not in obj:
            continue
        liste = eintrag(neu, key, anlegen=True)[0].setdefault(feld, [])
        for item in will:
            if item not in liste:
                liste.append(item)
                aenderungen.append(f"{LABELS[key]}: {item}")
        for item in state.get(key, []):
            if item not in will and item in liste:
                liste.remove(item)
                aenderungen.append(f"{LABELS[key]} entfernt: {item}")
    markt = {MARKETPLACE: (PAKET, [p.name for p in plugin_ordner()], cfg["plugins"])}
    for name, o, plugins in eigene_marktplaetze(cfg):
        markt[name] = (o, [n for n, _p in plugins], [n for n, _p in plugins])
    for name, (o, alle, an) in markt.items():
        quelle = {"source": {"source": "directory", "path": str(o)}}
        if neu.get("extraKnownMarketplaces", {}).get(name) != quelle:
            neu.setdefault("extraKnownMarketplaces", {})[name] = quelle
            aenderungen.append(f"Marketplace {name}: Ordner {o}")
        for n in alle:
            ist = neu.get("enabledPlugins", {}).get(f"{n}@{name}") is True
            if n in an and not ist:
                neu.setdefault("enabledPlugins", {})[f"{n}@{name}"] = True
                aenderungen.append(f"Plugin eingeschaltet: {n}@{name}")
            elif n not in an and ist:
                del neu["enabledPlugins"][f"{n}@{name}"]
                aenderungen.append(f"Plugin ausgeschaltet: {n}@{name}")
        for schluessel in [k for k in neu.get("enabledPlugins", {}) if k.endswith(f"@{name}")]:
            if schluessel[:-len(name) - 1] not in alle:  # Plugin gibt es im Marketplace nicht mehr (7.0: mail)
                del neu["enabledPlugins"][schluessel]
                aenderungen.append(f"Plugin ausgetragen, gibt es nicht mehr: {schluessel}")
    vorher = state.get("eigene_plugins") if isinstance(state.get("eigene_plugins"), dict) else {}
    for name, namen in vorher.items():  # gestrichene eigene Marketplaces samt Plugins austragen
        if name in markt or not isinstance(namen, list):
            continue
        for n in namen:
            if neu.get("enabledPlugins", {}).pop(f"{n}@{name}", None) is not None:
                aenderungen.append(f"Plugin ausgeschaltet: {n}@{name}")
        if neu.get("extraKnownMarketplaces", {}).pop(name, None) is not None:
            aenderungen.append(f"Marketplace {name} ausgetragen")
    if cfg.get("output_style") and neu.get("outputStyle") != cfg["output_style"]:
        aenderungen.append(f"outputStyle: {neu.get('outputStyle')!r} -> {cfg['output_style']!r}")
        neu["outputStyle"] = cfg["output_style"]
    eigene = {n: a for n, (_o, a, _an) in markt.items() if n != MARKETPLACE}
    return pfad, neu, aenderungen, {**soll, "eigene_plugins": eigene}


# ---------- CLAUDE.md der Instanz und Instructions ----------

def ohne_kommentare(text: str) -> str:
    """Kommentare und nur-code-Marker raus (der Inhalt der nur-code-Blöcke bleibt), höchstens eine Leerzeile."""
    return re.sub(r"\n{3,}", "\n\n", KOMMENTAR_HTML_RE.sub("", text)).strip() + "\n"


def profil_quellen(k: Path) -> tuple:
    """(Profil, Index oder None): profil.md plus CLAUDE.md als Index des Projekts, ohne profil.md die CLAUDE.md allein."""
    if (k / PROFIL).is_file():
        return k / PROFIL, (k / "CLAUDE.md" if (k / "CLAUDE.md").is_file() else None)
    return k / "CLAUDE.md", None


def mit_ordner(index: str, k: Path) -> str:
    """Nach der ersten Überschrift des Index eine Zeile mit dem Kontextordner: Die Pfade dort sind relativ."""
    zeile = f"Kontextordner: `{k}`. Die Pfade unten sind relativ dazu."
    kopf, _, rest = index.partition("\n")
    return f"{kopf}\n\n{zeile}\n{rest}" if kopf.startswith("#") else f"{zeile}\n\n{index}"


def plan_claude_md(cfg: dict, settings: Path):
    """(Ziel, neuer Text oder None, Meldung): CLAUDE.md neben settings.json aus Profil und Index, mit Kopfzeile.
    Überschrieben wird nur eine Datei mit dieser Kopfzeile, eine eigene CLAUDE.md des Nutzers bleibt."""
    k = kontext_ordner(cfg)
    quelle, index = profil_quellen(k)
    ziel = settings.parent / "CLAUDE.md"
    if not quelle.is_file():
        return ziel, None, f"CLAUDE.md: Quelle {quelle} fehlt noch (Skill einrichten legt sie an)"
    text = (f"{CLAUDE_MD_MARKE}{quelle}{f' und {index}' if index else ''}. Änderungen dort, dann paket.py --apply. -->"
            f"\n\n" + ohne_kommentare(quelle.read_text(encoding="utf-8")))
    if index:
        text += "\n" + ohne_kommentare(mit_ordner(index.read_text(encoding="utf-8"), k))
    alt = ziel.read_text(encoding="utf-8") if ziel.is_file() else None
    if alt == text:
        return ziel, None, ""
    if alt is not None and not alt.startswith(CLAUDE_MD_MARKE):
        return ziel, None, (f"WARNUNG: {ziel} ist eine eigene Datei und bleibt unverändert. Inhalt nach {quelle} "
                            f"übernehmen und die Datei umbenennen, dann paket.py erneut")
    return ziel, text, f"CLAUDE.md: {'neu aus' if alt is None else 'aktualisiert aus'} {quelle}"


def instructions_text(profil: str) -> str:
    """Profil für Instructions for Claude: ohne nur-code-Blöcke und Kommentare, ohne Überschriften ohne Inhalt."""
    zeilen = ohne_kommentare(NUR_CODE_BLOCK_RE.sub("", profil)).splitlines()
    aus = []
    for i, z in enumerate(zeilen):
        m = re.match(r"^(#+)\s", z)
        if m:
            folgende = [x for x in zeilen[i + 1:] if x.strip()]
            n = re.match(r"^(#+)\s", folgende[0]) if folgende else None
            if not folgende or (n and len(n.group(1)) <= len(m.group(1))):
                continue
        aus.append(z)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(aus)).strip() + "\n"


# ---------- Prüfungen ----------

def skill_pruefung() -> list:
    """Platzhalter {{...}} in Skills und Referenzen, Skills über dem Richtwert."""
    msgs, n = [], 0
    for p in plugin_ordner():
        for md in sorted(p.glob("**/*.md")):
            if "tests" in md.parts or ".venv" in md.parts:
                continue
            text = md.read_text(encoding="utf-8")
            rel = md.relative_to(PAKET)
            if PLATZHALTER_RE.search(text):
                msgs.append(("FEHLER", f"{rel}: Platzhalter mit doppelten geschweiften Klammern, das Paket kennt keine"))
            if md.name == "SKILL.md":
                n += 1
                if len(text.encode("utf-8")) > SKILL_KB * 1024:
                    msgs.append(("WARNUNG", f"{rel}: über {SKILL_KB} KB, Seltenes in references/ auslagern"))
    return msgs or [("OK", f"Skills: {n} ohne Platzhalter und unter {SKILL_KB} KB")]


def kopien_eigener_plugins(cfg: dict) -> tuple:
    """([(Name, Ordner)], [Meldungen]): Plugins der eigenen Marketplaces aus der Einrichtung mit einer Kopie von
    kit_basis.py oder mcp_basis.py (etwa arbeit im work-kit). Ist ein Marketplace nicht lesbar (in der Privat-Instanz
    ist das work-kit gesperrt), eine INFO statt eines Abbruchs."""
    orte, msgs = [], []
    for markt, ordner in (cfg.get("eigene_plugins") or {}).items() if isinstance(cfg.get("eigene_plugins"), dict) else []:
        try:
            liste = eigene_marktplaetze({"eigene_plugins": {markt: ordner}})[0][2]
            orte += [(f"{markt}/{name}", p) for name, p in liste
                     if any((p / d).is_file() for d in GLEICHE_DATEIEN[:2])]
        except (KitFehler, OSError) as e:
            msgs.append(("INFO", f"Gleiche Dateien in {markt} nicht verglichen ({e}), das prüft die Instanz, die "
                                 f"{markt} lesen darf"))
    return orte, msgs


def gleichstand_pruefung(cfg: dict = None) -> list:
    """Gleiche Dateien in apple und chat und in den Kopien eigener Plugins (Pfad aus eigene_plugins der Einrichtung).
    Eine Datei, die eine Kopie nicht hat, zählt dort nicht, eine abweichende ist ein FEHLER."""
    if cfg is None:
        try:
            cfg = load_json(CONFIG, CONFIG.name) if CONFIG.is_file() else {}
        except KitFehler:
            cfg = {}
    fremd, msgs = kopien_eigener_plugins(cfg if isinstance(cfg, dict) else {})
    orte = [(pl, PLUGINS / pl) for pl in GLEICHE_PLUGINS] + fremd
    fehler = []
    for datei in GLEICHE_DATEIEN:
        stand = {name: (ort / datei).read_bytes() for name, ort in orte if (ort / datei).is_file()}
        if len(set(stand.values())) > 1:
            fehler.append(("FEHLER", f"{datei} ist nicht überall gleich ({', '.join(stand)}), nur zusammen ändern"))
    if not fremd and not msgs:
        msgs.append(("INFO", "Gleiche Dateien nur im Paket verglichen: keine eigenen Plugins in dieser Einrichtung "
                             "(die Kopie in arbeit vergleicht die Arbeits-Instanz)"))
    stellen = ", ".join(name for name, _o in orte)
    return fehler + msgs if fehler else [("OK", f"Gleiche Dateien (kit_basis.py, mcp_basis.py samt Tests) sind gleich in "
                                                f"{stellen}")] + msgs


def werkzeuge_mit_stufe(server_py: Path) -> dict:
    """{Name: Stufe} aus den Aufrufen Werkzeug("name", "titel", "beschreibung", "stufe", ...) in server.py, ohne Import
    (beide Server haben ein eigenes mcp_basis)."""
    werkzeuge = {}
    for knoten in ast.walk(ast.parse(server_py.read_text(encoding="utf-8"))):
        if (isinstance(knoten, ast.Call) and isinstance(knoten.func, ast.Name) and knoten.func.id == "Werkzeug"
                and len(knoten.args) >= 4 and all(isinstance(a, ast.Constant) for a in (knoten.args[0], knoten.args[3]))):
            werkzeuge[knoten.args[0].value] = knoten.args[3].value
    return werkzeuge


def sicherheit_pruefung() -> list:
    """SICHERHEIT.md im Hauptordner vorhanden und jedes Werkzeug der Stufe nachfrage aus apple und chat darin genannt
    (in Backticks)."""
    datei = PAKET / SICHERHEIT
    if not datei.is_file():
        return [("FEHLER", f"{SICHERHEIT} fehlt im Hauptordner (Gefahren und Gegenmaßnahmen je Werkzeug)")]
    text = datei.read_text(encoding="utf-8")
    nachfrage = sorted(name for pl in SERVER_PLUGINS if (PLUGINS / pl / "server.py").is_file()
                       for name, stufe in werkzeuge_mit_stufe(PLUGINS / pl / "server.py").items() if stufe == "nachfrage")
    fehlt = [n for n in nachfrage if f"`{n}`" not in text]
    if fehlt:
        return [("FEHLER", f"{SICHERHEIT}: Werkzeug der Stufe nachfrage ohne Zeile: {', '.join(fehlt)}")]
    return [("OK", f"{SICHERHEIT} nennt alle {len(nachfrage)} Werkzeuge der Stufe nachfrage")]


def doku_pruefung() -> list:
    """Doku-Test der Plugins mit Server als Unterprozess: jedes Werkzeug in genau einer Werkzeugtabelle mit der Stufe aus
    server.py. Fehlt der Test oder schlägt er fehl, ein FEHLER mit der letzten Zeile der Ausgabe."""
    msgs, ok = [], []
    for pl in SERVER_PLUGINS:
        if not (PLUGINS / pl / "server.py").is_file():
            continue
        test = PLUGINS / pl / DOKU_TEST
        if not test.is_file():
            msgs.append(("FEHLER", f"{pl}: {DOKU_TEST} fehlt"))
            continue
        try:
            lauf = subprocess.run([sys.executable, "-B", str(test)], capture_output=True, text=True, timeout=DOKU_ZEIT,
                                  cwd=str(PLUGINS / pl), env={**os.environ, "KITS_FEHLERPROTOKOLL": "aus"})
        except (OSError, subprocess.SubprocessError) as e:
            msgs.append(("FEHLER", f"{pl}: Doku-Test lief nicht ({type(e).__name__})"))
            continue
        if lauf.returncode != 0:
            zeilen = [z for z in (lauf.stderr + lauf.stdout).splitlines() if z.strip()]
            grund = next((z.strip() for z in zeilen if z.lstrip().startswith(("'", '"', "AssertionError"))),
                         zeilen[-1].strip() if zeilen else f"Code {lauf.returncode}")
            msgs.append(("FEHLER", f"{pl}: Doku-Test schlägt fehl: {grund[:300]}"))
        else:
            ok.append(pl)
    return msgs + ([("OK", f"Doku-Test: Werkzeugtabellen passen zu den Servern ({', '.join(ok)})")] if ok else [])


def git_dateien(ordner: Path):
    try:
        r = subprocess.run(["git", "-C", str(ordner), "ls-files", "-z"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return [p for p in r.stdout.split("\0") if p] if r.returncode == 0 else None


def nummer_kern(text: str) -> str:
    """Nummer zum Vergleich: ohne Ländervorwahl +49 oder 0049, Trenner und führende 0 (0171 12, +49 171 12: 17112)."""
    kern = re.sub(r"[\W_]", "", re.sub(r"^\s*(?:\+|00)49", "", text)).lstrip("0")
    return kern if len(kern) >= 7 else ""


def namen_aus_dateien(dateien) -> set:
    """Volle Namen (Vorname Nachname) aus fett gesetzten Einträgen und Überschriften der Personendateien des Nutzers."""
    namen = set()
    for f in dateien:
        try:
            text = re.sub(r"<!--.*?-->", "", Path(f).expanduser().read_text(encoding="utf-8"), flags=re.S)
        except OSError:
            continue
        for k in re.findall(r"\*\*([^*\n]+)\*\*", text) + re.findall(r"^###\s+(.+)$", text, re.M):
            k = re.sub(r"\s*\([^)]*\)", "", k).strip(" :")
            if re.fullmatch(r"[A-ZÄÖÜ][\wäöüß-]+(?: [A-ZÄÖÜ][\wäöüß-]+)+", k):
                namen.add(k)
    return namen


def persoenlich_pruefung(cfg: dict = None) -> list:
    """[(Stufe, Meldung)]: Mailadressen, Nummern, Zugangsdaten und die Namen aus der Einrichtung (namen, namen_aus) in
    versionierten Dateien, dazu config.json im Git. Nennt Datei und Zeile, nie den Fund. Erlaubtes unter ignorieren."""
    cfg = cfg if cfg is not None else (load_json(CONFIG, CONFIG.name) if CONFIG.is_file() else {})
    erlaubt = set(cfg.get("ignorieren", []))
    namen = sorted((set(cfg.get("namen", [])) | namen_aus_dateien(cfg.get("namen_aus", []))) - erlaubt,
                   key=len, reverse=True)
    namen_re = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(n) for n in namen) + r")(?!\w)", re.I) if namen else None
    nummern = {nummer_kern(n) for n in cfg.get("nummern", [])} - {""}
    dateien = git_dateien(PAKET)
    if dateien is None:
        return [("INFO", "Persönliche Daten: Paket ohne Git, nicht geprüft")]
    msgs = [("WARNUNG", f"{rel} steht im Git, persönliche Konfiguration gehört nur in den Datenordner")
            for rel in dateien if Path(rel).name == "config.json"]
    funde = []
    for rel in dateien:
        if not rel.endswith(PERSOENLICH_ENDUNGEN):
            continue
        try:
            zeilen = (PAKET / rel).read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        testdatei = "tests" in Path(rel).parts  # erfundene Nummern und Konten gehören zu Testdaten
        for nr, zeile in enumerate(zeilen, 1):
            bereinigt = zeile
            for e in erlaubt:  # erlaubte Werte (etwa der Autor im Manifest) fallen vor der Namenssuche weg
                bereinigt = bereinigt.replace(e, " ")
            if namen_re and namen_re.search(bereinigt):
                funde.append(f"{rel} Zeile {nr} (Name)")
            if nummern and any(n in re.sub(r"[\W_]", "", zeile) for n in nummern):
                funde.append(f"{rel} Zeile {nr} (eigene Nummer)")
            for m in MAIL_RE.finditer(zeile):
                domain = m.group(0).rsplit("@", 1)[1].casefold()
                if m.group(0) not in erlaubt and not any(domain == d or domain.endswith("." + d) for d in MAIL_BEISPIEL):
                    funde.append(f"{rel} Zeile {nr} (Mailadresse)")
            if not testdatei and not rel.endswith((".py", ".sh")):  # in Code sind Nummern und Kennungen Beispiele
                funde += [f"{rel} Zeile {nr} ({a})" for a, muster in SENSIBEL if muster.search(zeile)]
    if funde:
        msgs.append(("WARNUNG", f"Persönliche Daten in versionierten Dateien: {len(funde)} Fund(e), etwa "
                                f"{', '.join(funde[:3])}"))
    return msgs or [("OK", f"Persönliches getrennt: {len(dateien)} versionierte Dateien ohne Namen, Adressen und Nummern")]


# ---------- Ablauf ----------

def cmd_pruefen() -> int:
    msgs = (skill_pruefung() + gleichstand_pruefung() + sicherheit_pruefung() + doku_pruefung()
            + persoenlich_pruefung())
    for stufe, text in msgs:
        print(f"{stufe}: {text}")
    return 1 if any(s == "FEHLER" for s, _t in msgs) else 0


def cmd_einrichten(apply: bool) -> int:
    cfg = lade_einrichtung()
    pfad, neu, aenderungen, soll = plan_settings(cfg, lade_state())
    ziel, claude_md, meldung = plan_claude_md(cfg, pfad)
    print(f"Einstellungen: {pfad}")
    for a in aenderungen:
        print(f"  {a}")
    if meldung:
        print(meldung)
    n = len(aenderungen) + (claude_md is not None)
    if not n:
        print("Nichts zu ändern, Einstellungen und CLAUDE.md stimmen mit Paket und Kontext überein.")
        return 0
    if not apply:
        extra = f" --einrichtung {EINRICHTUNG_NAME}" if EINRICHTUNG_NAME else ""
        print(f"\nTrockenlauf: {n} Änderung(en). Schreiben mit: python3 \"{Path(__file__).resolve()}\" --apply{extra}")
        return 0
    if aenderungen:
        write_json(pfad, neu)
        write_json(STATE, soll)
    if claude_md is not None:
        atomic_write(ziel, claude_md.encode("utf-8"))
    print(f"\n{n} Änderung(en) geschrieben. Plugins und CLAUDE.md laden ab dem nächsten Sessionstart.")
    return 0


def cmd_instructions() -> int:
    k = kontext_ordner(lade_einrichtung())
    profil, _index = profil_quellen(k)
    if not profil.is_file():
        raise KitFehler(f"Profil {profil} fehlt")
    ziel = k / "einrichtung" / "instructions.md"
    text = instructions_text(profil.read_text(encoding="utf-8"))
    if ziel.is_file() and ziel.read_text(encoding="utf-8") == text:
        print(f"Unverändert: {ziel} ({len(text)} Zeichen).")
        return 0
    atomic_write(ziel, text.encode("utf-8"))
    print(f"Neu: {ziel} ({len(text)} Zeichen). In Einstellungen > Instructions for Claude einfügen.")
    return 0


def cmd_zips(ziel: str) -> int:
    """Je Plugin des Pakets und der eigenen Marketplaces ein ZIP aus HEAD. Ein vorhandenes ZIP gleicher Version bleibt,
    Plugins mit nicht committeten Änderungen werden genannt (das ZIP enthält sie nicht)."""
    ziel = Path(ziel).expanduser().resolve()
    ziel.mkdir(parents=True, exist_ok=True)
    plugins = [(p.name, p) for p in plugin_ordner()]
    plugins += [x for _m, _o, liste in eigene_marktplaetze(lade_einrichtung()) for x in liste]
    fehler = 0
    for name, ordner in plugins:
        version = load_json(ordner / ".claude-plugin" / "plugin.json", f"plugin.json von {name}").get("version")
        datei = ziel / f"{name}-{version}.zip"
        wurzel = subprocess.run(["git", "-C", str(ordner), "rev-parse", "--show-toplevel", "--show-prefix"],
                                capture_output=True, text=True, timeout=10).stdout.splitlines()
        offen = subprocess.run(["git", "-C", str(ordner), "status", "--porcelain", "--", "."],
                               capture_output=True, text=True, timeout=10).stdout.strip()
        if datei.exists():
            print(f"{datei.name}: liegt schon da, bleibt" + (" (Änderungen nicht committet)" if offen else ""))
            continue
        befehl = ["git", "-C", wurzel[0], "archive", "--format=zip", "-o", str(datei),
                  f"HEAD:{wurzel[1] if len(wurzel) > 1 else ''}", "--", "."] + [f":(exclude){x}" for x in ZIP_OHNE]
        r = subprocess.run(befehl, capture_output=True, text=True, timeout=60)
        if r.returncode:
            fehler = 1
            print(f"FEHLER {name}: {r.stderr.strip()}")
            continue
        print(f"{datei.name}: gebaut" + (", ACHTUNG: Änderungen im Plugin nicht committet" if offen else ""))
    return fehler


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="settings.json und CLAUDE.md schreiben")
    ap.add_argument("--pruefen", action="store_true", help="Skills, gleiche Dateien und Persönliches prüfen")
    ap.add_argument("--zips", metavar="ORDNER", help="ZIP je Plugin für den Upload bauen")
    ap.add_argument("--instructions", action="store_true", help="Text für Instructions for Claude schreiben")
    ap.add_argument("--einrichtung", metavar="NAME",
                    help="zweite Instanz: einrichtung.<NAME>.json statt einrichtung.json (im Terminal immer angeben)")
    a = ap.parse_args(argv)
    try:
        waehle_einrichtung(einrichtung_name(a.einrichtung))
        if EINRICHTUNG_NAME:
            print(f"Einrichtung: {CONFIG.name}")
        if a.pruefen:
            return cmd_pruefen()
        if a.zips:
            return cmd_zips(a.zips)
        if a.instructions:
            return cmd_instructions()
        return cmd_einrichten(a.apply)
    except KitFehler as e:
        print(f"FEHLER: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
