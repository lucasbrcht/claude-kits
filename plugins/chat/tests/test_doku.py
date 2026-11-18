"""Doku-Test: Jedes Werkzeug der Server apple und chat steht in genau einer Werkzeugtabelle eines Skills im Paket, mit
der Stufe aus server.py. Tabellen haben die Kopfzeile | Werkzeug | Zweck | Stufe |, die Stufe nachfrage heißt dort
fragt. Liegt gleich in apple und chat, jedes Plugin prüft seine eigenen Werkzeuge und alle Tabellen.

Aufruf im Plugin-Ordner: python3 -B -m unittest discover tests
"""
import ast
import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
PLUGIN = Path(__file__).resolve().parent.parent
PLUGINS = PLUGIN.parent
SERVER_PLUGINS = ("apple", "chat")
KOPF = ("werkzeug", "zweck", "stufe")
STUFE_IN_TABELLE = {"lesen": "lesen", "schreiben": "schreiben", "fragt": "nachfrage"}
NAME_RE = re.compile(r"^`([a-z][a-z0-9_]*)`$")


def zellen(zeile: str) -> list:
    return [z.strip() for z in zeile.strip().strip("|").split("|")]


def tabellen(plugins: Path = PLUGINS) -> list:
    """[(Name, Stufe wie in der Tabelle, Fundstelle)] aus allen Werkzeugtabellen der SKILL.md im Paket."""
    eintraege = []
    for md in sorted(plugins.glob("*/skills/*/SKILL.md")):
        rel = md.relative_to(plugins)
        in_tabelle = False
        for nr, zeile in enumerate(md.read_text(encoding="utf-8").splitlines(), 1):
            if not zeile.lstrip().startswith("|"):
                in_tabelle = False
                continue
            z = zellen(zeile)
            if tuple(x.casefold() for x in z) == KOPF:
                in_tabelle = True
                continue
            if not in_tabelle or set("".join(z)) <= set("-: "):
                continue
            m = NAME_RE.match(z[0])
            eintraege.append((m.group(1) if m else z[0], z[-1], f"{rel} Zeile {nr}"))
    return eintraege


def werkzeuge_aus_quelltext(server_py: Path) -> dict:
    """{Name: Stufe} aus den Aufrufen Werkzeug("name", "titel", "beschreibung", "stufe", ...) in server.py, ohne Import.
    So lassen sich beide Server in einem Prozess lesen."""
    werkzeuge = {}
    for knoten in ast.walk(ast.parse(server_py.read_text(encoding="utf-8"))):
        if (isinstance(knoten, ast.Call) and isinstance(knoten.func, ast.Name) and knoten.func.id == "Werkzeug"
                and len(knoten.args) >= 4 and all(isinstance(a, ast.Constant) for a in (knoten.args[0], knoten.args[3]))):
            werkzeuge[knoten.args[0].value] = knoten.args[3].value
    return werkzeuge


def abweichungen(eintraege: list, eigene: dict, alle: dict) -> list:
    """Meldungen: Werkzeuge aus eigene ohne Tabelle oder mit falscher Stufe, Namen in Tabellen, die kein Server aus alle
    kennt, und Namen in mehr als einer Zeile."""
    msgs, gesehen = [], {}
    for name, stufe, stelle in eintraege:
        if name in gesehen:
            msgs.append(f"{name} doppelt: {gesehen[name]} und {stelle}")
            continue
        gesehen[name] = stelle
        if name not in alle:
            msgs.append(f"{name} überzählig: {stelle}, kein Server kennt es")
        elif STUFE_IN_TABELLE.get(stufe) is None:
            msgs.append(f"{name}: Stufe {stufe} unbekannt in {stelle}, erlaubt sind {', '.join(STUFE_IN_TABELLE)}")
        elif name in eigene and STUFE_IN_TABELLE[stufe] != eigene[name]:
            msgs.append(f"{name}: Stufe {stufe} in {stelle}, im Server {eigene[name]}")
    msgs += [f"{name} fehlt: steht in keiner Werkzeugtabelle" for name in sorted(eigene) if name not in gesehen]
    return msgs


def alle_werkzeuge(plugins: Path = PLUGINS) -> dict:
    alle = {}
    for pl in SERVER_PLUGINS:
        if (plugins / pl / "server.py").is_file():
            alle.update(werkzeuge_aus_quelltext(plugins / pl / "server.py"))
    return alle


class Abgleich(unittest.TestCase):
    """Die Prüfung selbst mit erfundenen Tabellen."""

    EIGENE = {"a_lesen": "lesen", "b_schreiben": "schreiben", "c_senden": "nachfrage"}
    GUT = [("a_lesen", "lesen", "x"), ("b_schreiben", "schreiben", "x"), ("c_senden", "fragt", "x")]

    def test_vollstaendig(self):
        self.assertEqual(abweichungen(self.GUT, self.EIGENE, self.EIGENE), [])

    def test_fehlend_ueberzaehlig_doppelt_stufe(self):
        alle = {**self.EIGENE, "d_fremd": "lesen"}
        eintraege = [("a_lesen", "schreiben", "s1"), ("a_lesen", "lesen", "s2"), ("b_schreiben", "schreiben", "s3"),
                     ("d_fremd", "lesen", "s4"), ("e_alt", "lesen", "s5"), ("b_schreiben", "lesen", "s6")]
        msgs = " | ".join(abweichungen(eintraege, self.EIGENE, alle))
        for teil in ("a_lesen: Stufe schreiben in s1", "a_lesen doppelt", "b_schreiben doppelt", "e_alt überzählig",
                     "c_senden fehlt"):
            self.assertIn(teil, msgs)
        self.assertNotIn("d_fremd", msgs)  # Werkzeug des anderen Servers, dessen Stufe prüft sein eigener Test

    def test_unbekannte_stufe(self):
        msgs = abweichungen([("a_lesen", "nachfrage", "s1")], {"a_lesen": "lesen"}, {"a_lesen": "lesen"})
        self.assertIn("unbekannt", msgs[0])

    def test_tabelle_lesen(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            skill = Path(t) / "demo" / "skills" / "demo" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("# demo\n\n| Werkzeug | Zweck | Stufe |\n|---|---|---|\n| `a_lesen` | liest | lesen |\n"
                             "| `c_senden` | sendet | fragt |\n\n| Server | Wofür |\n|---|---|\n| `x_y` | z |\n",
                             encoding="utf-8")
            self.assertEqual([(n, s) for n, s, _st in tabellen(Path(t))], [("a_lesen", "lesen"), ("c_senden", "fragt")])


class Paket(unittest.TestCase):
    """Das echte Paket: Werkzeuge dieses Plugins und alle Tabellen."""

    def test_quelltext_wie_import(self):
        sys.path.insert(0, str(PLUGIN))
        try:
            import server
        finally:
            sys.path.remove(str(PLUGIN))
        self.assertEqual(werkzeuge_aus_quelltext(PLUGIN / "server.py"), {w.name: w.stufe for w in server.WERKZEUGE})

    def test_jedes_werkzeug_in_genau_einer_tabelle(self):
        eigene = werkzeuge_aus_quelltext(PLUGIN / "server.py")
        self.assertTrue(eigene)
        self.assertEqual(abweichungen(tabellen(), eigene, alle_werkzeuge()), [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
