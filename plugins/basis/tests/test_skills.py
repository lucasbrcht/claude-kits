"""Tests für die Skills von basis: Kopf jeder SKILL.md (name wie der Ordner, description vorhanden und kurz genug) und
der Schnitt seit 8.0: Der Skill dateien und sprache.py liegen im Plugin office, basis ruft keine eigenen Skripte auf.

Aufruf im Plugin-Ordner: python3 -B -m unittest discover tests
"""
import re
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
BESCHREIBUNG_MAX = 1024  # Grenze für description im Kopf eines Skills
KOPF_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)


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

    def test_dateien_liegt_in_office(self):
        self.assertEqual({p.name for p in (PLUGIN / "skills").iterdir() if p.is_dir()},
                         {"einrichten", "kontext", "feedback"})
        self.assertFalse(list(PLUGIN.glob("skills/*/scripts")))
        for md in PLUGIN.glob("skills/**/*.md"):
            self.assertNotIn("sprache.py", md.read_text(encoding="utf-8"), md)
        office = PLUGIN.parent / "office" / "skills" / "dateien" / "SKILL.md"
        if office.parent.parent.parent.is_dir():  # im Paket liegt office daneben, im ZIP von basis nicht
            self.assertEqual(kopf(office).get("name"), "dateien")


if __name__ == "__main__":
    unittest.main()
