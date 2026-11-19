"""Tests für die Skills von basis: Kopf jeder SKILL.md (name wie der Ordner, description vorhanden und kurz genug),
der Schnitt seit 8.0 (der Skill dateien und sprache.py liegen im Plugin office, basis ruft keine eigenen Skripte auf)
und der Skill tagesstart (Größe, keine Bash-Befehle, nur Werkzeuge, die es gibt, neutral ohne Adressen).

Aufruf im Plugin-Ordner: python3 -B -m unittest discover tests
"""
import ast
import re
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
PLUGINS = PLUGIN.parent
BESCHREIBUNG_MAX = 1024  # Grenze für description im Kopf eines Skills
SKILL_MAX = 8192  # Bytes je SKILL.md, Einzelheiten gehören in references/
KOPF_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)
TAGESSTART = PLUGIN / "skills" / "tagesstart"
# Werkzeuge der Connectoren, die der Tagesstart nennen darf (Microsoft 365, Gmail)
CONNECTOR = {"outlook_email_search", "chat_message_search", "read_resource", "search_threads",
             "teams_list_chats", "teams_create_chat", "teams_send_chat_message"}
WERKZEUG_RE = re.compile(r"`([a-z]+(?:_[a-z0-9]+)+)`")
BASH_RE = re.compile(r"```(?:bash|sh|zsh|shell)|\b(?:python3?|osascript|sqlite3|curl|git) |\$\(|\bcd ", re.I)


def kopf(md: Path) -> dict:
    treffer = KOPF_RE.match(md.read_text(encoding="utf-8"))
    if not treffer:
        return {}
    werte = {}
    for zeile in treffer.group(1).splitlines():
        if ":" in zeile and not zeile.startswith(" "):
            name, wert = zeile.split(":", 1)
            werte[name.strip()] = wert.strip()
    return werte


def server_werkzeuge(server_py: Path) -> set:
    """Namen aus den Aufrufen Werkzeug("name", ...) in server.py, ohne Import (wie test_doku in apple)."""
    namen = set()
    for knoten in ast.walk(ast.parse(server_py.read_text(encoding="utf-8"))):
        if (isinstance(knoten, ast.Call) and isinstance(knoten.func, ast.Name) and knoten.func.id == "Werkzeug"
                and knoten.args and isinstance(knoten.args[0], ast.Constant)):
            namen.add(knoten.args[0].value)
    return namen


def tagesstart_texte() -> dict:
    return {md.relative_to(TAGESSTART).as_posix(): md.read_text(encoding="utf-8")
            for md in sorted(TAGESSTART.rglob("*.md"))}


class Skills(unittest.TestCase):
    def test_kopf_jeder_skill_md(self):
        skills = sorted(PLUGIN.glob("skills/*/SKILL.md"))
        self.assertTrue(skills)
        for md in skills:
            with self.subTest(skill=md.parent.name):
                werte = kopf(md)
                self.assertEqual(werte.get("name"), md.parent.name)
                self.assertTrue(werte.get("description"))
                self.assertLessEqual(len(werte["description"]), BESCHREIBUNG_MAX)
                self.assertLessEqual(len(md.read_bytes()), SKILL_MAX)

    def test_dateien_liegt_in_office(self):
        self.assertEqual({p.name for p in (PLUGIN / "skills").iterdir() if p.is_dir()},
                         {"einrichten", "kontext", "tagesstart", "feedback"})
        self.assertFalse(list(PLUGIN.glob("skills/*/scripts")))
        for md in PLUGIN.glob("skills/**/*.md"):
            self.assertNotIn("sprache.py", md.read_text(encoding="utf-8"), md)
        office = PLUGINS / "office" / "skills" / "dateien" / "SKILL.md"
        if office.parent.parent.parent.is_dir():  # im Paket liegt office daneben, im ZIP von basis nicht
            self.assertEqual(kopf(office).get("name"), "dateien")


class Tagesstart(unittest.TestCase):
    def test_dateien(self):
        self.assertEqual(set(tagesstart_texte()), {"SKILL.md", "references/beispiel.md",
                                                   "references/vorschlaege.md"})
        skill = tagesstart_texte()["SKILL.md"]
        for verweis in ("references/beispiel.md", "references/vorschlaege.md"):
            self.assertIn(verweis, skill)

    def test_keine_bash_befehle(self):
        for name, text in tagesstart_texte().items():
            with self.subTest(datei=name):
                self.assertIsNone(BASH_RE.search(text))

    def test_nur_vorhandene_werkzeuge(self):
        servers = [PLUGINS / pl / "server.py" for pl in ("apple", "chat", "office")]
        if not all(s.is_file() for s in servers):
            self.skipTest("im ZIP von basis liegen die anderen Plugins nicht daneben")
        bekannt = CONNECTOR.union(*(server_werkzeuge(s) for s in servers))
        genannt = set()
        for name, text in tagesstart_texte().items():
            genannt |= set(WERKZEUG_RE.findall(text))
        self.assertEqual(sorted(genannt - bekannt), [])
        for pflicht in ("termine_lesen", "mail_neues", "erinnerungen_lesen", "chat_neues", "einstellungen"):
            self.assertIn(f"`{pflicht}`", tagesstart_texte()["SKILL.md"])

    def test_verweise_auf_skills_und_kontext(self):
        skill = tagesstart_texte()["SKILL.md"]
        self.assertIn("wissen/_interview.md", skill)
        self.assertIn("/basis:kontext", skill)
        vorschlaege = tagesstart_texte()["references/vorschlaege.md"]
        for verweis in ("`erinnerungen`", "`mail`", "`kalender`", "`whatsapp`", "`imessage`", '"senden"'):
            self.assertIn(verweis, vorschlaege)

    def test_neutral(self):
        for name, text in tagesstart_texte().items():
            with self.subTest(datei=name):
                self.assertNotRegex(text, r"[\w.+-]+@[\w-]+\.[\w.]+")  # keine Adressen
                self.assertNotRegex(text, r"[–—…;]")  # Schreibregeln des Pakets

    def test_abgrenzung_in_den_beschreibungen(self):
        beschreibung = kopf(TAGESSTART / "SKILL.md")["description"]
        for wort in ("mail", "whatsapp", "imessage", "Nicht zum Anlegen"):
            self.assertIn(wort, beschreibung)
        for skill in ("apple/skills/mail", "chat/skills/whatsapp", "chat/skills/imessage"):
            md = PLUGINS / skill / "SKILL.md"
            if md.is_file():
                with self.subTest(skill=skill):
                    self.assertIn("tagesstart", kopf(md)["description"])


if __name__ == "__main__":
    unittest.main()
