#!/usr/bin/env python3
"""Tests für paket.py: Einstellungen, CLAUDE.md und Instructions aus dem Kontextordner, Prüfungen, ZIPs, zwei
Instanzen. Jeder Test baut ein kleines Paket im Temp-Ordner, nichts berührt das echte Paket oder die echte
settings.json.

Aufruf im Plugin-Ordner: python3 -B -m unittest discover tests
"""
import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import paket  # noqa: E402

KIT = {"name": "demo", "version": "1.0.0", "zweck": "Test", "skills": ["demo"], "skripte": [],
       "verbote": ["Read(~/Library/Demo/**)"]}
SKILL = "---\nname: demo\ndescription: Test\n---\n\nNutzt das Werkzeug demo_lesen.\n"
GIT = ["-c", "user.email=test@example.org", "-c", "user.name=Test"]


class PaketTest(unittest.TestCase):
    """Ein Paket mit dem Plugin demo im Temp-Ordner, die Konstanten von paket.py zeigen dorthin."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="paket-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.paket = self.tmp / "claude-kits"
        self.plugin = self.paket / "plugins" / "demo"
        (self.paket / ".claude-plugin").mkdir(parents=True)
        (self.paket / ".claude-plugin" / "marketplace.json").write_text(json.dumps(
            {"name": "claude-kits", "plugins": [{"name": "demo", "source": "./plugins/demo"}]}), encoding="utf-8")
        (self.plugin / "skills" / "demo").mkdir(parents=True)
        (self.plugin / "skills" / "demo" / "SKILL.md").write_text(SKILL, encoding="utf-8")
        (self.plugin / ".claude-plugin").mkdir()
        (self.plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "demo", "version": "1.2.0"}),
                                                                    encoding="utf-8")
        (self.plugin / "kit.json").write_text(json.dumps(KIT), encoding="utf-8")
        self.kontext = self.tmp / "kontext"
        self.settings = self.tmp / "claude" / "settings.json"
        for name, wert in (("PAKET", self.paket), ("PLUGINS", self.paket / "plugins"),
                           ("CONFIG", self.paket / "einrichtung.json"), ("STATE", self.paket / ".state.json"),
                           ("EINRICHTUNG_NAME", ""), ("DATENORDNER", self.tmp / "daten")):
            patcher = mock.patch.object(paket, name, wert)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.einrichtung({})

    def einrichtung(self, roh):
        roh = {"settings": str(self.settings), "kontext": str(self.kontext), **roh}
        (self.paket / "einrichtung.json").write_text(json.dumps(roh), encoding="utf-8")

    def lauf(self, fn, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = fn(*args)
        return code, out.getvalue()

    def git(self, ordner, *args):
        if subprocess.run(["git", *GIT, "-C", str(ordner), *args], capture_output=True).returncode:
            self.skipTest("git nicht verfügbar")

    def settings_json(self) -> dict:
        return json.loads(self.settings.read_text(encoding="utf-8"))


class Einrichtung(PaketTest):
    def test_einrichtung_wird_geprueft(self):
        for roh, text in (({"zuender": {}}, "zuender unbekannt"), ({"connectoren": {}}, "connectoren unbekannt"),
                          ({"plugins": {"fremd": {}}}, "plugins nennt"), ({"rechte_extra": ["mcp__g__send_message"]},
                                                                          "nichts senden"),
                          ({"kontext": 3}, "kontext ist ein Text"), ({"fragen_extra": "x"}, "Liste")):
            self.einrichtung(roh)
            with self.subTest(roh=roh), self.assertRaisesRegex(paket.KitFehler, text):
                paket.lade_einrichtung()

    def test_plugins_als_liste_oder_objekt(self):
        for wert in (["demo"], {"demo": {"modus": "voll"}}):
            self.einrichtung({"plugins": wert})
            self.assertEqual(paket.lade_einrichtung()["plugins"], ["demo"])
        self.einrichtung({})
        self.assertEqual(paket.lade_einrichtung()["plugins"], ["demo"])


class Einstellungen(PaketTest):
    def test_trockenlauf_aendert_nichts_apply_schreibt_und_ist_dann_still(self):
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}, "model": "x"}), encoding="utf-8")
        code, out = self.lauf(paket.cmd_einrichten, False)
        self.assertEqual(code, 0)
        self.assertIn("Trockenlauf", out)
        self.assertEqual(self.settings_json()["permissions"]["allow"], ["Bash(ls)"])
        self.lauf(paket.cmd_einrichten, True)
        s = self.settings_json()
        self.assertEqual(s["model"], "x")
        self.assertIn("Bash(ls)", s["permissions"]["allow"])
        self.assertIn(f"Read(/{self.kontext}/**)", s["permissions"]["allow"])
        self.assertIn(f"Edit(/{self.kontext}/profil.md)", s["permissions"]["ask"])
        self.assertIn("Read(~/Library/Demo/**)", s["permissions"]["deny"])  # Sperren aus kit.json bleiben
        self.assertIn(f"{self.plugin}/.venv", s["sandbox"]["filesystem"]["denyWrite"])
        daten = self.tmp / "daten"  # Datenordner der Plugins: lesen und schreiben, die .venv bleibt für Bash zu
        self.assertIn(f"Read(/{daten}/**)", s["permissions"]["allow"])
        self.assertIn(f"Edit(/{daten}/**)", s["permissions"]["allow"])
        self.assertIn(str(daten), s["permissions"]["additionalDirectories"])
        self.assertIn(f"{daten}/demo/.venv", s["sandbox"]["filesystem"]["denyWrite"])
        self.assertIs(s["enabledPlugins"]["demo@claude-kits"], True)
        self.assertEqual(s["extraKnownMarketplaces"]["claude-kits"]["source"]["path"], str(self.paket))
        _code, out = self.lauf(paket.cmd_einrichten, True)
        self.assertIn("Nichts zu ändern", out)

    def test_alte_regeln_aus_dem_stand_verschwinden_fremde_bleiben(self):
        alt = 'Bash(python3 "/x/demo.py" read *)'
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text(json.dumps({"permissions": {"allow": [alt, "WebSearch"]}}), encoding="utf-8")
        (self.paket / ".state.json").write_text(json.dumps({"permissions.allow": [alt]}), encoding="utf-8")
        _code, out = self.lauf(paket.cmd_einrichten, True)
        self.assertIn(f"erlaubt entfernt: {alt}", out)
        self.assertEqual([r for r in self.settings_json()["permissions"]["allow"] if r in (alt, "WebSearch")],
                         ["WebSearch"])

    def test_plugin_ohne_ordner_faellt_weg(self):
        """7.0: mail ging in apple auf. Ein Eintrag des Paket-Marketplace ohne Plugin verschwindet, fremde bleiben."""
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text(json.dumps({"enabledPlugins": {"mail@claude-kits": True, "x@anderer": True}}),
                                 encoding="utf-8")
        _code, out = self.lauf(paket.cmd_einrichten, True)
        self.assertIn("Plugin ausgetragen, gibt es nicht mehr: mail@claude-kits", out)
        self.assertEqual(self.settings_json()["enabledPlugins"], {"x@anderer": True, "demo@claude-kits": True})

    def test_extras_gesperrt_und_plugin_aus(self):
        self.einrichtung({"plugins": [], "fragen_extra": ["mcp__gmail__send_message"],
                          "verbote_extra": ["mcp__gmail__trash_thread"], "gesperrt": [str(self.tmp / "gegenseite")],
                          "sandbox_ausnahmen": ["open -a Excel *"], "output_style": "pflege:Assistent"})
        self.lauf(paket.cmd_einrichten, True)
        s = self.settings_json()
        self.assertIn("mcp__gmail__send_message", s["permissions"]["ask"])
        self.assertIn("mcp__gmail__trash_thread", s["permissions"]["deny"])
        self.assertIn(f"Read(/{self.tmp / 'gegenseite'}/**)", s["permissions"]["deny"])
        self.assertNotIn("Read(~/Library/Demo/**)", s["permissions"]["deny"])  # Plugin aus, keine Sperre von ihm
        self.assertEqual(s["sandbox"]["excludedCommands"], ["open -a Excel *"])
        self.assertEqual(s["outputStyle"], "pflege:Assistent")
        self.assertNotIn("demo@claude-kits", s.get("enabledPlugins", {}))

    def test_eigene_plugins_neben_dem_paket(self):
        eigen = self.tmp / "eigen"
        (eigen / ".claude-plugin").mkdir(parents=True)
        (eigen / ".claude-plugin" / "marketplace.json").write_text(json.dumps(
            {"name": "eigen", "plugins": [{"name": "arbeit", "source": "./"}]}), encoding="utf-8")
        (eigen / "kit.json").write_text(json.dumps({"verbote": ["Read(~/Eigen/**)"]}), encoding="utf-8")
        self.einrichtung({"eigene_plugins": {"eigen": str(eigen)}})
        _code, out = self.lauf(paket.cmd_einrichten, True)
        self.assertIn("Plugin eingeschaltet: arbeit@eigen", out)
        s = self.settings_json()
        self.assertEqual(s["extraKnownMarketplaces"]["eigen"], {"source": {"source": "directory", "path": str(eigen)}})
        self.assertIn("Read(~/Eigen/**)", s["permissions"]["deny"])
        self.assertIn(f"Edit(/{eigen / 'kit.json'})", s["permissions"]["ask"])
        self.assertIn(str(eigen), s["permissions"]["additionalDirectories"])
        self.einrichtung({})
        self.lauf(paket.cmd_einrichten, True)
        s = self.settings_json()
        self.assertNotIn("arbeit@eigen", s["enabledPlugins"])
        self.assertNotIn("eigen", s["extraKnownMarketplaces"])
        self.assertNotIn("Read(~/Eigen/**)", s["permissions"]["deny"])
        for falsch in ({"claude-kits": str(eigen)}, {"Eigen": str(eigen)}, ["x"]):
            self.einrichtung({"eigene_plugins": falsch})
            with self.subTest(falsch=falsch), self.assertRaisesRegex(paket.KitFehler, "eigene_plugins"):
                paket.lade_einrichtung()

    def test_kaputte_settings_brechen_mit_meldung_ab(self):
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text(json.dumps({"permissions": {"allow": "Bash(ls)"}}), encoding="utf-8")
        with self.assertRaisesRegex(paket.KitFehler, "permissions.allow ist keine Liste"):
            paket.cmd_einrichten(False)


class ClaudeMdUndInstructions(PaketTest):
    def profil_und_index(self):
        self.kontext.mkdir()
        (self.kontext / "profil.md").write_text("# Über mich\n- Person\n<!-- nur-code -->\n- Nie cd\n"
                                                "<!-- /nur-code -->\n\n# Regeln\n- Senden nur nach Ja\n\n"
                                                "<!-- nur-code -->\n# Nur im Code-Tab\n- Pfade absolut\n"
                                                "<!-- /nur-code -->\n", encoding="utf-8")
        (self.kontext / "CLAUDE.md").write_text("# Kontext-Index\n\n| Personen | `wissen/personen.md` |\n",
                                                encoding="utf-8")

    def test_kopie_nur_mit_marke(self):
        ziel = self.settings.parent / "CLAUDE.md"
        _z, text, meldung = paket.plan_claude_md({"kontext": str(self.kontext)}, self.settings)
        self.assertIsNone(text)
        self.assertIn("fehlt noch", meldung)
        self.kontext.mkdir()
        (self.kontext / "CLAUDE.md").write_text("# Über mich\n", encoding="utf-8")
        self.lauf(paket.cmd_einrichten, True)
        self.assertTrue(ziel.read_text().startswith(paket.CLAUDE_MD_MARKE))
        self.assertTrue(ziel.read_text().endswith("# Über mich\n"))
        ziel.write_text("# Eigene Datei\n", encoding="utf-8")
        _code, out = self.lauf(paket.cmd_einrichten, True)
        self.assertIn("eigene Datei und bleibt unverändert", out)
        self.assertEqual(ziel.read_text(), "# Eigene Datei\n")

    def test_profil_plus_index(self):
        self.profil_und_index()
        _z, text, meldung = paket.plan_claude_md({"kontext": str(self.kontext)}, self.settings)
        self.assertIn(f"{self.kontext / 'profil.md'} und {self.kontext / 'CLAUDE.md'}", text.splitlines()[0])
        rumpf = text.split("-->\n\n", 1)[1]
        self.assertEqual(rumpf, "# Über mich\n- Person\n- Nie cd\n\n# Regeln\n- Senden nur nach Ja\n\n"
                                "# Nur im Code-Tab\n- Pfade absolut\n\n"
                                f"# Kontext-Index\n\nKontextordner: `{self.kontext}`. Die Pfade unten sind relativ "
                                "dazu.\n\n| Personen | `wissen/personen.md` |\n")
        self.assertIn("profil.md", meldung)

    def test_instructions_ohne_nur_code(self):
        self.profil_und_index()
        _code, out = self.lauf(paket.cmd_instructions)
        self.assertIn("Neu:", out)
        self.assertEqual((self.kontext / "einrichtung" / "instructions.md").read_text(),
                         "# Über mich\n- Person\n\n# Regeln\n- Senden nur nach Ja\n")
        _code, out = self.lauf(paket.cmd_instructions)
        self.assertIn("Unverändert", out)


class Pruefungen(PaketTest):
    def test_platzhalter_und_groesse(self):
        (self.plugin / "skills" / "demo" / "SKILL.md").write_text(SKILL + "{{KIT}}\n" + "x" * 9000, encoding="utf-8")
        self.assertEqual({s for s, _t in paket.skill_pruefung()}, {"FEHLER", "WARNUNG"})

    def test_gleiche_dateien(self):
        for pl, inhalt in (("chat", "a"), ("apple", "b")):
            (self.paket / "plugins" / pl).mkdir(parents=True)
            (self.paket / "plugins" / pl / "mcp_basis.py").write_text(inhalt, encoding="utf-8")
        self.assertIn("mcp_basis.py", " ".join(t for s, t in paket.gleichstand_pruefung({}) if s == "FEHLER"))

    def test_gleiche_dateien_auch_im_eigenen_plugin(self):
        """7.0: Die Kopie im Plugin arbeit des work-kit zählt mit, über den Pfad aus eigene_plugins der Einrichtung."""
        for pl in ("chat", "apple"):
            (self.paket / "plugins" / pl).mkdir(parents=True)
            (self.paket / "plugins" / pl / "mcp_basis.py").write_text("a", encoding="utf-8")
        werk = self.tmp / "work-kit"
        (werk / ".claude-plugin").mkdir(parents=True)
        (werk / ".claude-plugin" / "marketplace.json").write_text(json.dumps(
            {"name": "work-kit", "plugins": [{"name": "arbeit", "source": "./plugin"}]}), encoding="utf-8")
        (werk / "plugin").mkdir()
        (werk / "plugin" / "mcp_basis.py").write_text("a", encoding="utf-8")
        cfg = {"eigene_plugins": {"work-kit": str(werk)}}
        msgs = paket.gleichstand_pruefung(cfg)
        self.assertEqual([s for s, _t in msgs], ["OK"])
        self.assertIn("apple, chat, work-kit/arbeit", msgs[0][1])
        (werk / "plugin" / "mcp_basis.py").write_text("alt", encoding="utf-8")
        self.assertIn("work-kit/arbeit", " ".join(t for s, t in paket.gleichstand_pruefung(cfg) if s == "FEHLER"))
        msgs = paket.gleichstand_pruefung({"eigene_plugins": {"work-kit": str(self.tmp / "gesperrt")}})
        self.assertEqual([s for s, _t in msgs], ["OK", "INFO"])  # nicht lesbar: kein Abbruch, die andere Instanz prüft
        self.assertIn("nicht verglichen", msgs[1][1])

    def test_persoenliches_in_versionierten_dateien(self):
        self.git(self.paket, "init", "-q")
        adresse = "anna" + "@" + "beispiel-firma.de"  # zusammengesetzt, sonst fände die Prüfung diese Testdatei
        (self.plugin / "README.md").write_text(f"Max Muster\nschreib an {adresse}\nTel 0171 1234567\n",
                                               encoding="utf-8")
        (self.plugin / "tests").mkdir()
        (self.plugin / "tests" / "test_x.py").write_text("NUMMER = '0171 1234567'\n", encoding="utf-8")
        (self.plugin / "config.json").write_text("{}", encoding="utf-8")
        self.git(self.paket, "add", "-A")
        msgs = paket.persoenlich_pruefung({"namen": ["Muster"]})
        text = " | ".join(t for _s, t in msgs)
        self.assertIn("config.json steht im Git", text)
        self.assertIn("3 Fund(e)", text)
        self.assertNotIn("anna@", text)  # nie den Fund selbst
        msgs = paket.persoenlich_pruefung({"namen": ["Muster"], "ignorieren": ["Max Muster", adresse]})
        self.assertIn("1 Fund(e)", msgs[-1][1])  # die Nummer im README, die im Test zählt nicht

    def test_namen_aus_personendatei(self):
        f = self.tmp / "privat-personen.md"
        f.write_text("## Familie\n- **Erika Muster**: Schwester\n- **Ben**: Freund\n<!-- - **Geheim Kommentar**: x -->\n"
                     "### Max Beispiel (Verein)\n", encoding="utf-8")
        self.assertEqual(paket.namen_aus_dateien([str(f)]), {"Erika Muster", "Max Beispiel"})


class Zips(PaketTest):
    def test_zip_aus_head_ohne_tests_und_kit_json(self):
        (self.plugin / "tests").mkdir()
        (self.plugin / "tests" / "test_x.py").write_text("x = 1\n", encoding="utf-8")
        (self.plugin / ".gitattributes").write_text("intern.md export-ignore\n.gitattributes export-ignore\n",
                                                    encoding="utf-8")
        (self.plugin / "intern.md").write_text("nur lokal\n", encoding="utf-8")
        self.git(self.paket, "init", "-q")
        self.git(self.paket, "add", "-A")
        self.git(self.paket, "commit", "-qm", "x")
        (self.plugin / "skills" / "demo" / "SKILL.md").write_text(SKILL + "neu\n", encoding="utf-8")
        ziel = self.tmp / "dist"
        code, out = self.lauf(paket.cmd_zips, str(ziel))
        self.assertEqual(code, 0)
        self.assertIn("demo-1.2.0.zip: gebaut, ACHTUNG", out)
        namen = zipfile.ZipFile(ziel / "demo-1.2.0.zip").namelist()
        self.assertIn(".claude-plugin/plugin.json", namen)
        self.assertIn("skills/demo/SKILL.md", namen)
        for weg in ("kit.json", "tests/test_x.py", "intern.md", ".gitattributes"):
            self.assertNotIn(weg, namen)
        self.assertNotIn(b"neu", zipfile.ZipFile(ziel / "demo-1.2.0.zip").read("skills/demo/SKILL.md"))
        _code, out = self.lauf(paket.cmd_zips, str(ziel))
        self.assertIn("liegt schon da", out)


class ZweiInstanzen(PaketTest):
    """Zwei Instanzen von Claude Code nutzen dasselbe Paket: einrichtung.json und einrichtung.<name>.json."""

    def setUp(self):
        super().setUp()
        self.zweite = self.tmp / "claude-zwei" / "settings.json"
        (self.paket / "einrichtung.zwei.json").write_text(json.dumps(
            {"settings": str(self.zweite), "kontext": str(self.tmp / "kontext-zwei")}), encoding="utf-8")

    def umgebung(self, **werte):
        leer = {"KITS_EINRICHTUNG": "", "CLAUDECODE": "", "CLAUDE_CONFIG_DIR": ""}
        p = mock.patch.dict("os.environ", {**leer, **werte})
        p.start()
        self.addCleanup(p.stop)

    def test_terminal_ohne_angabe_nimmt_die_erste(self):
        self.umgebung(CLAUDE_CONFIG_DIR=str(self.zweite.parent))  # ohne CLAUDECODE zählt die Umgebung nicht
        self.assertEqual(paket.einrichtung_name(), "")

    def test_session_waehlt_nach_config_ordner(self):
        self.umgebung(CLAUDECODE="1", CLAUDE_CONFIG_DIR=str(self.zweite.parent))
        self.assertEqual(paket.einrichtung_name(), "zwei")
        self.umgebung(CLAUDECODE="1", CLAUDE_CONFIG_DIR=str(self.settings.parent))
        self.assertEqual(paket.einrichtung_name(), "")

    def test_angabe_schlaegt_umgebung_und_prueft(self):
        self.umgebung(CLAUDECODE="1", CLAUDE_CONFIG_DIR=str(self.settings.parent))
        self.assertEqual(paket.einrichtung_name("zwei"), "zwei")
        for falsch in ("drei", "example", "../x"):
            with self.assertRaises(paket.KitFehler):
                paket.einrichtung_name(falsch)

    def test_eigener_stand_und_hinweis(self):
        self.umgebung()
        code, out = self.lauf(paket.main, ["--einrichtung", "zwei"])
        self.assertEqual(code, 0)
        self.assertIn(f"Einstellungen: {self.zweite}", out)
        self.assertIn("--apply --einrichtung zwei", out)
        self.lauf(paket.main, ["--apply", "--einrichtung", "zwei"])
        self.assertTrue(self.zweite.is_file())
        self.assertTrue((self.paket / ".einrichtung-state.zwei.json").is_file())
        self.assertFalse(self.settings.exists())
        self.assertFalse((self.paket / ".state.json").exists())


class EchtesPaket(unittest.TestCase):
    """Das Paket selbst besteht seine Prüfungen ohne FEHLER."""

    def test_pruefungen_ohne_fehler(self):
        msgs = paket.skill_pruefung() + paket.gleichstand_pruefung({})
        self.assertEqual([t for s, t in msgs if s == "FEHLER"], [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
