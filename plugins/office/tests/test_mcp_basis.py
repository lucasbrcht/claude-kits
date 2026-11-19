"""Tests für mcp_basis.py. Die Datei liegt gleich in apple, chat und office, wie mcp_basis.py selbst."""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN))

import mcp_basis as mb  # noqa: E402


class Argumente(unittest.TestCase):
    def test_text(self):
        self.assertEqual(mb.text({"a": "  x "}, "a"), "x")
        self.assertEqual(mb.text({}, "a"), "")
        with self.assertRaises(mb.Fehler):
            mb.text({}, "a", pflicht=True)
        with self.assertRaises(mb.Fehler):
            mb.text({"a": 3}, "a")
        with self.assertRaises(mb.Fehler):
            mb.text({"a": "x" * 11}, "a", maximal=10)

    def test_zahl(self):
        self.assertEqual(mb.zahl({"n": 3}, "n", 1, 5), 3)
        self.assertIsNone(mb.zahl({}, "n"))
        for falsch in (True, "3", 2.5, 9):
            with self.assertRaises(mb.Fehler):
                mb.zahl({"n": falsch}, "n", 1, 5)
        self.assertEqual(mb.zahl({"n": 2.5}, "n", 0, 5, ganz=False), 2.5)

    def test_schalter_und_liste(self):
        self.assertTrue(mb.schalter({"s": True}, "s"))
        self.assertFalse(mb.schalter({}, "s"))
        with self.assertRaises(mb.Fehler):
            mb.schalter({"s": "ja"}, "s")
        self.assertEqual(mb.textliste({"l": ["a", " ", "b "]}, "l"), ["a", "b"])
        self.assertEqual(mb.textliste({"l": "a"}, "l"), ["a"])
        with self.assertRaises(mb.Fehler):
            mb.textliste({"l": [1]}, "l")

    def test_opt_als_ein_wort(self):
        self.assertEqual(mb.opt("--x", "-y"), ["--x=-y"])  # ein Wert mit - vorn wird nie ein eigener Schalter
        self.assertEqual(mb.opt("--x", True), ["--x"])
        self.assertEqual(mb.opt("--x", False), [])
        self.assertEqual(mb.opt("--x", None), [])
        self.assertEqual(mb.opt("--x", 0), ["--x=0"])


class Datenordner(unittest.TestCase):
    def test_umgebung_zuerst(self):
        with mock.patch.dict(os.environ, {mb.UMGEBUNG: "/tmp/x"}):
            self.assertEqual(mb.datenordner("apple"), Path("/tmp/x"))

    def test_nur_app_daten_kein_repo(self):
        """7.0: ohne KITS_DATENORDNER nur Application Support, kein Rückfall auf den Plugin-Ordner im Repo."""
        self.assertFalse(hasattr(mb, "PAKET_ORDNER"))
        with tempfile.TemporaryDirectory() as t:
            app = Path(t) / "app"
            (app / "apple").mkdir(parents=True)
            (app / "apple" / "config.json").write_text("{}")
            with mock.patch.dict(os.environ, {mb.UMGEBUNG: ""}), mock.patch.object(mb, "APP_DATEN", app):
                self.assertEqual(mb.datenordner("apple"), app / "apple")
                self.assertIn(str(app / "apple"), mb.ohne_daten("apple"))
                (app / "apple" / "config.json").unlink()
                self.assertIsNone(mb.datenordner("apple"))

    def test_nur_lesen(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "config.json").write_text(json.dumps({"mcp_nur_lesen": True}))
            with mock.patch.dict(os.environ, {mb.UMGEBUNG: t, "KITS_NUR_LESEN": ""}):
                self.assertTrue(mb.nur_lesen("chat"))
            (Path(t) / "config.json").write_text("{}")
            with mock.patch.dict(os.environ, {mb.UMGEBUNG: t, "KITS_NUR_LESEN": ""}):
                self.assertFalse(mb.nur_lesen("chat"))
            with mock.patch.dict(os.environ, {mb.UMGEBUNG: t, "KITS_NUR_LESEN": "1"}):
                self.assertTrue(mb.nur_lesen("chat"))

    def test_nur_lesen_je_instanz(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "config.json").write_text(json.dumps({"mcp_nur_lesen": ["arbeit"]}))
            with mock.patch.dict(os.environ, {mb.UMGEBUNG: t, "KITS_NUR_LESEN": "", "KITS_INSTANZ": "arbeit"}):
                self.assertTrue(mb.nur_lesen("chat"))
            with mock.patch.dict(os.environ, {mb.UMGEBUNG: t, "KITS_NUR_LESEN": "", "KITS_INSTANZ": "privat"}):
                self.assertFalse(mb.nur_lesen("chat"))

    def test_instanz(self):
        leer = {"KITS_INSTANZ": "", "CLAUDE_CONFIG_DIR": "", "CLAUDE_PLUGIN_ROOT": ""}
        with mock.patch.dict(os.environ, dict(leer, CLAUDE_CONFIG_DIR="/Users/x/.claude-privat")):
            self.assertEqual(mb.instanz(), "privat")
        with mock.patch.dict(os.environ, dict(leer, CLAUDE_PLUGIN_ROOT="/Users/x/Library/Application Support/Parall/"
                                              "Claude Privat/local-agent-mode-sessions/a/b/rpm/plugin_1")):
            self.assertEqual(mb.instanz(), "privat")
        with mock.patch.dict(os.environ, leer), \
                mock.patch.object(mb, "_eltern", return_value=["/private/var/folders/x/AppTranslocation/y/"
                                                               "Claude Privat.app/Contents/MacOS/Claude"]):
            self.assertEqual(mb.instanz(), "privat")
        with mock.patch.dict(os.environ, leer), \
                mock.patch.object(mb, "_eltern", return_value=["/Applications/Claude.app/Contents/MacOS/Claude"]):
            self.assertEqual(mb.instanz(), "arbeit")
        with mock.patch.dict(os.environ, dict(leer, KITS_INSTANZ="Privat")):
            self.assertEqual(mb.instanz(), "privat")


class Lauf(unittest.TestCase):
    """Ein Ersatzskript im Ersatz-Plugin zeigt, was der Lauf übergibt."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.wurzel = Path(self.tmp.name) / "plugin"
        self.daten = Path(self.tmp.name) / "daten"
        self.wurzel.mkdir()
        self.daten.mkdir()
        (self.daten / "config.json").write_text("{}")
        (self.wurzel / "echo.py").write_text(textwrap.dedent("""
            import os, sys, pathlib
            daten = pathlib.Path(os.environ["KITS_DATENORDNER"])
            print("args", sys.argv[1:])
            print("cwd", os.getcwd())
            datei = daten / "nachricht.txt"
            if datei.exists():
                print("text", datei.read_text(encoding="utf-8"))
                if "--loeschen" in sys.argv:
                    datei.unlink()
            sys.exit(int(os.environ.get("ECHO_CODE", "0")))
        """))
        (self.wurzel / "schlaf.py").write_text("import time\ntime.sleep(5)\n")
        (self.wurzel / "echo.sh").write_text('echo "sh $1 $KITS_DATENORDNER"\n')
        self.lauf = mb.Lauf(self.wurzel, "test")
        self.env = mock.patch.dict(os.environ, {mb.UMGEBUNG: str(self.daten)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_argumente_ohne_shell(self):
        code, aus = self.lauf("echo.py", ["a b", "$(id)", "--x=-y"])
        self.assertEqual(code, 0)
        self.assertIn("args ['a b', '$(id)', '--x=-y']", aus)
        self.assertIn(f"cwd {self.wurzel.resolve()}", aus)

    def test_textdatei_wird_angelegt_und_weggeraeumt(self):
        code, aus = self.lauf("echo.py", [], textdateien={"nachricht.txt": "Hallo\nWelt"})
        self.assertIn("text Hallo\nWelt", aus)
        self.assertFalse((self.daten / "nachricht.txt").exists())  # Skript hat sie nicht gelöscht: der Lauf räumt
        code, aus = self.lauf("echo.py", ["--loeschen"], textdateien={"nachricht.txt": "x"})
        self.assertEqual(code, 0)  # schon gelöscht: kein Fehler beim Aufräumen

    def test_textdatei_nie_ueber_verweis(self):
        ziel = Path(self.tmp.name) / "fremd.txt"
        ziel.write_text("alt")
        (self.daten / "nachricht.txt").symlink_to(ziel)
        code, aus = self.lauf("echo.py", [], textdateien={"nachricht.txt": "neu"})
        self.assertEqual(code, 1)
        self.assertIn("Verweis", aus)
        self.assertEqual(ziel.read_text(), "alt")

    def test_exit_code_und_fehlendes_skript(self):
        with mock.patch.dict(os.environ, {"ECHO_CODE": "3"}):
            code, _ = self.lauf("echo.py", [])
        self.assertEqual(code, 3)
        code, aus = self.lauf("fehlt.py", [])
        self.assertEqual(code, 1)
        self.assertIn("fehlt im Plugin", aus)

    def test_shell_skript_mit_bash(self):
        code, aus = self.lauf("echo.sh", ["7"])
        self.assertEqual(code, 0)
        self.assertIn(f"sh 7 {self.daten}", aus)

    def test_zeitueberschreitung(self):
        code, aus = self.lauf("schlaf.py", [], zeit=1)
        self.assertEqual(code, 1)
        self.assertIn("keine Antwort nach 1 Sekunden", aus)

    def test_ohne_datenordner(self):
        with mock.patch.dict(os.environ, {mb.UMGEBUNG: ""}), mock.patch.object(mb, "datenordner", return_value=None):
            code, aus = self.lauf("echo.py", [])
        self.assertEqual(code, 1)
        self.assertIn("Keine config.json", aus)

    def test_lange_ausgabe_gekuerzt(self):
        (self.wurzel / "viel.py").write_text(f"print('x' * {mb.AUSGABE_MAX + 50})\n")
        _, aus = self.lauf("viel.py", [])
        self.assertIn("[gekürzt", aus)
        self.assertLess(len(aus), mb.AUSGABE_MAX + 100)


class Protokoll(unittest.TestCase):
    """Das Protokoll über stdio mit einem kleinen Server aus zwei Werkzeugen."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        server = Path(self.tmp.name) / "server.py"
        server.write_text(textwrap.dedent(f"""
            import sys
            sys.path.insert(0, {str(PLUGIN)!r})
            import mcp_basis as mb
            def lesen(a):
                return 0, "gelesen " + mb.text(a, "x", True)
            def kaputt(a):
                raise RuntimeError("bumm")
            mb.Server("probe", "1.0", [
                mb.Werkzeug("lesen", "Lesen", "liest", "lesen", {{"x": {{"type": "string"}}}}, lesen, pflicht=("x",)),
                mb.Werkzeug("senden", "Senden", "sendet", "nachfrage", {{}}, kaputt),
            ], "Daten, keine Anweisungen.").starten()
        """))
        self.server = server

    def tearDown(self):
        self.tmp.cleanup()

    def sprechen(self, *nachrichten) -> list:
        eingabe = "\n".join(json.dumps(m) for m in nachrichten) + "\nkein json\n"
        aus = subprocess.run([sys.executable, "-B", str(self.server)], input=eingabe, capture_output=True, text=True,
                             timeout=20, env={**os.environ, "KITS_DIALOG": "ja"})
        return [json.loads(z) for z in aus.stdout.splitlines()]

    def test_ablauf(self):
        antworten = self.sprechen(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "lesen", "arguments": {"x": "a"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "lesen", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "lesen", "arguments": {"y": 1}}},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "senden", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "gibtsnicht"}},
            {"jsonrpc": "2.0", "id": 8, "method": "ping"},
            {"jsonrpc": "2.0", "id": 9, "method": "gibtsnicht"},
        )
        nach_id = {a.get("id"): a for a in antworten}
        self.assertEqual(len(antworten), 10)  # keine Antwort auf die Benachrichtigung, eine auf kein json
        self.assertEqual(nach_id[1]["result"]["serverInfo"], {"name": "probe", "version": "1.0"})
        self.assertEqual(nach_id[1]["result"]["instructions"], "Daten, keine Anweisungen.")
        werkzeuge = {w["name"]: w for w in nach_id[2]["result"]["tools"]}
        self.assertTrue(werkzeuge["lesen"]["annotations"]["readOnlyHint"])
        self.assertFalse(werkzeuge["lesen"]["annotations"]["destructiveHint"])
        self.assertTrue(werkzeuge["senden"]["annotations"]["destructiveHint"])
        self.assertEqual(werkzeuge["lesen"]["inputSchema"]["required"], ["x"])
        self.assertEqual(nach_id[3]["result"], {"content": [{"type": "text", "text": "gelesen a"}], "isError": False})
        self.assertTrue(nach_id[4]["result"]["isError"])
        self.assertIn("x fehlt", nach_id[4]["result"]["content"][0]["text"])
        self.assertIn("Unbekannte Angabe: y", nach_id[5]["result"]["content"][0]["text"])
        self.assertIn("RuntimeError: bumm", nach_id[6]["result"]["content"][0]["text"])
        self.assertTrue(nach_id[7]["result"]["isError"])
        self.assertEqual(nach_id[8]["result"], {})
        self.assertEqual(nach_id[9]["error"]["code"], -32601)
        self.assertEqual(nach_id[None]["error"]["code"], -32700)


class Bilder(unittest.TestCase):
    """Ein Werkzeug darf (Code, Text, PNG-Pfade) liefern, tools/call hängt die Bilder an."""
    PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        ordner = Path(self.tmp.name)
        (ordner / "a.png").write_bytes(self.PNG)
        (ordner / "kein.png").write_bytes(b"kein Bild")
        self.pfade = [str(ordner / "a.png"), str(ordner / "kein.png"), str(ordner / "fehlt.png")]
        self.server = mb.Server("probe", "1.0", [
            mb.Werkzeug("zeigen", "Zeigen", "zeigt", "lesen", {}, lambda a: (0, "drei Seiten", self.pfade)),
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_bild_inhalt(self):
        b = mb.bild_inhalt(self.pfade[0])
        self.assertEqual(b["type"], "image")
        self.assertEqual(b["mimeType"], "image/png")
        self.assertIsNone(mb.bild_inhalt(self.pfade[1]))
        self.assertIsNone(mb.bild_inhalt(self.pfade[2]))
        with mock.patch.object(mb, "BILD_MAX", 10):
            self.assertIsNone(mb.bild_inhalt(self.pfade[0]))

    def test_aufrufen_ohne_bilder(self):
        self.assertEqual(self.server.aufrufen("zeigen", {}), (False, "drei Seiten"))
        self.assertEqual(self.server.ausfuehren("zeigen", {}), (False, "drei Seiten", self.pfade))
        self.assertEqual(self.server.ausfuehren("gibtsnicht", {})[2], [])

    def test_tools_call(self):
        gesendet = []
        with mock.patch.object(self.server, "antwort", lambda nr, ergebnis=None, fehler=None: gesendet.append(ergebnis)):
            self.server.behandeln({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "zeigen"}})
        inhalt = gesendet[0]["content"]
        self.assertEqual([i["type"] for i in inhalt], ["text", "image"])  # nur das echte PNG
        self.assertFalse(gesendet[0]["isError"])


class Dialog(unittest.TestCase):
    """Vor jedem Werkzeug der Stufe nachfrage ein Dialog von macOS, den nur der Nutzer freigibt."""

    def setUp(self):
        self.aufrufe = []

        def tun(a):
            self.aufrufe.append(a)
            return 0, "getan"
        self.server = mb.Server("probe", "1.0", [
            mb.Werkzeug("lesen", "Lesen", "liest", "lesen", {"x": {"type": "string"}}, tun),
            mb.Werkzeug("senden", "Senden", "sendet", "nachfrage", {"x": {"type": "string"}}, tun, pflicht=("x",),
                        vorschau=lambda a: "Vorschau " + a["x"]),
        ])

    def test_ohne_freigabe_nichts_ausgefuehrt(self):
        with mock.patch.dict(os.environ, {"KITS_DIALOG": "nein"}):
            fehler, aus = self.server.aufrufen("senden", {"x": "a"})
        self.assertTrue(fehler)
        self.assertIn("Nicht ausgeführt", aus)
        self.assertEqual(self.aufrufe, [])

    def test_mit_freigabe_ausgefuehrt(self):
        with mock.patch.dict(os.environ, {"KITS_DIALOG": "ja"}):
            self.assertEqual(self.server.aufrufen("senden", {"x": "a"}), (False, "getan"))

    def test_lesen_und_fehlende_pflicht_ohne_dialog(self):
        with mock.patch.object(mb, "bestaetigen", side_effect=AssertionError("Dialog")):
            self.assertEqual(self.server.aufrufen("lesen", {"x": "a"}), (False, "getan"))
            fehler, aus = self.server.aufrufen("senden", {})
        self.assertTrue(fehler)
        self.assertIn("x fehlt", aus)
        self.assertEqual(self.aufrufe, [{"x": "a"}])

    def test_dialog_text(self):
        with mock.patch.object(mb, "bestaetigen", return_value=(False, "nein")) as dialog:
            self.server.aufrufen("senden", {"x": "Hallo"})
        self.assertEqual(dialog.call_args[0][0], "Claude möchte: Senden\n\nVorschau Hallo")  # mit Vorschau ohne Angaben
        self.server.werkzeuge["senden"].vorschau = None
        with mock.patch.object(mb, "bestaetigen", return_value=(False, "nein")) as dialog:
            self.server.aufrufen("senden", {"x": "Hallo\n  Welt " + "z" * 400})
        text = dialog.call_args[0][0]
        self.assertTrue(text.startswith("Claude möchte: Senden\n\nx: Hallo Welt"))
        self.assertIn("[gekürzt]", text)
        self.assertLessEqual(len(text), mb.DIALOG_MAX + 20)
        self.assertEqual(self.aufrufe, [])

    def test_angaben_in_stichworten(self):
        self.assertEqual(mb.angaben(("An", ["a", "b"]), ("Cc", ""), ("Text", "x" * 20, 5), "", "Achtung: y"),
                         "An: a, b\nText: xxxxx [gekürzt]\nAchtung: y")
        self.assertEqual(mb.ordnername("/Users/x/Library/CloudStorage/OneDrive-A/Ordner/"), "Ordner")
        self.assertEqual((mb.ordnername("/"), mb.ordnername(None)), ("", ""))

    def test_kaputte_vorschau_zeigt_trotzdem_dialog(self):
        self.server.werkzeuge["senden"].vorschau = lambda a: 1 / 0
        with mock.patch.object(mb, "bestaetigen", return_value=(True, "")) as dialog:
            self.assertEqual(self.server.aufrufen("senden", {"x": "a"}), (False, "getan"))
        self.assertNotIn("Vorschau", dialog.call_args[0][0])

    def test_osascript_auswerten(self):
        def ende(code, aus="", err=""):
            return subprocess.CompletedProcess([], code, aus, err)
        faelle = [(ende(0, mb.DIALOG_KNOPF + "\n"), True, ""),
                  (ende(1, err="execution error: User canceled. (-128)"), False, "abgebrochen"),
                  (ende(0, ""), False, "keine Antwort"), (ende(1, err="kaputt"), False, "kein Dialog")]
        text = 'Text mit "Anführung" und $(rm -rf x)'
        self.assertNotIn("of result", mb.DIALOG_SKRIPT)  # Klick auf Freigeben ging so verloren (Cowork 13.11.2026)
        with mock.patch.dict(os.environ, {"KITS_DIALOG": ""}):
            for ergebnis, frei, grund in faelle:
                with mock.patch.object(mb.subprocess, "run", return_value=ergebnis) as run:
                    f, g = mb.bestaetigen(text)
                self.assertEqual(f, frei)
                self.assertIn(grund, g)
                befehl = run.call_args[0][0]
                self.assertEqual(befehl[0], "/usr/bin/osascript")
                self.assertIn(text, befehl)  # Text als eigenes Argument, nie im Skript und ohne Shell
                self.assertNotIn(text, mb.DIALOG_SKRIPT)
                self.assertNotIn("shell", run.call_args[1])
            with mock.patch.object(mb.subprocess, "run", side_effect=OSError("weg")):
                self.assertFalse(mb.bestaetigen(text)[0])


class Einstellungen(unittest.TestCase):
    """7.0: config.json und Stilprofile über den Server, für die Einrichtung in Cowork."""
    VORLAGE = {"_hinweis": "x", "mail": {"accounts": ["<Konto>"]}, "kalender": {}, "notizen": {}}

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ordner = Path(tmp.name) / "apple"  # gibt es noch nicht: das erste Schreiben legt ihn an
        p = mock.patch.dict(os.environ, {mb.UMGEBUNG: str(self.ordner)})
        p.start()
        self.addCleanup(p.stop)

    def cfg(self) -> dict:
        return json.loads((self.ordner / "config.json").read_text(encoding="utf-8"))

    def test_ohne_config_zeigen_dann_schreiben_und_ersetzen(self):
        code, aus = mb.einstellungen_zeigen("apple", self.VORLAGE)
        self.assertEqual(code, 0)
        self.assertIn("Keine config.json", aus)
        self.assertIn("Abschnitte ohne Eintrag (Vorlage config.example.json): mail, kalender, notizen", aus)
        self.assertIn('Vorlage dafür: {"mail": {"accounts": ["<Konto>"]}, "kalender": {}, "notizen": {}}', aus)
        code, aus = mb.einstellungen_schreiben("apple", {"mail": {"accounts": ["<Konto>"]}, "kalender": {}},
                                               self.VORLAGE)
        self.assertEqual((code, self.cfg()), (0, {"mail": {"accounts": ["<Konto>"]}, "kalender": {}}))
        self.assertIn("neu mail, kalender", aus)
        _, aus = mb.einstellungen_schreiben("apple", {"kalender": {"default_calendar": "Privat"}}, self.VORLAGE)
        self.assertIn("ersetzt kalender", aus)
        self.assertEqual(self.cfg()["kalender"], {"default_calendar": "Privat"})
        self.assertEqual(self.cfg()["mail"], {"accounts": ["<Konto>"]})  # andere Abschnitte bleiben
        _, aus = mb.einstellungen_zeigen("apple", self.VORLAGE)
        self.assertIn("Offen: <Konto>", aus)
        self.assertIn("Abschnitte ohne Eintrag (Vorlage config.example.json): notizen", aus)
        self.assertEqual([p.name for p in self.ordner.iterdir()], ["config.json"])  # keine Temp-Datei bleibt

    def test_abschnitt_und_typ_nach_vorlage(self):
        for werte, meldung in (({"post": {}}, "gibt es nicht"), ({"mail": []}, "Typ dict"), ({"_x": 1}, "nicht mit _"),
                               ({}, "ein Objekt"), ([], "ein Objekt"), ({"mcp_nur_lesen": "ja"}, "mcp_nur_lesen ist")):
            with self.assertRaisesRegex(mb.Fehler, meldung):
                mb.einstellungen_schreiben("apple", werte, self.VORLAGE)
        self.assertFalse((self.ordner / "config.json").exists())
        mb.einstellungen_schreiben("apple", {"mcp_nur_lesen": ["arbeit"]}, self.VORLAGE)
        mb.einstellungen_schreiben("chat", {"me": "Ich", "me_names": ["Ich"]})  # ohne Vorlage jeder gültige Name
        self.assertEqual(self.cfg(), {"mcp_nur_lesen": ["arbeit"], "me": "Ich", "me_names": ["Ich"]})

    def test_kaputte_config_bleibt(self):
        self.ordner.mkdir()
        (self.ordner / "config.json").write_text("{kaputt", encoding="utf-8")
        with self.assertRaisesRegex(mb.Fehler, "von Hand reparieren"):
            mb.einstellungen_schreiben("apple", {"notizen": {}}, self.VORLAGE)
        self.assertEqual((self.ordner / "config.json").read_text(encoding="utf-8"), "{kaputt")

    def test_stilprofil_anlegen_ersetzen_ohne_verweis(self):
        code, aus = mb.stilprofil_schreiben("apple", ("privat",), "# Stil\nkurz\n\n")
        self.assertEqual(code, 0)
        self.assertIn("angelegt", aus)
        pfad = self.ordner / "style" / "privat" / "profil.md"
        self.assertEqual(pfad.read_text(encoding="utf-8"), "# Stil\nkurz\n")
        self.assertIn("ersetzt", mb.stilprofil_schreiben("apple", ("privat",), "neu")[1])
        _, aus = mb.einstellungen_zeigen("apple")
        self.assertIn("Stilprofile: style/privat/profil.md", aus)
        pfad.unlink()
        pfad.symlink_to(self.ordner / "config.json")
        with self.assertRaisesRegex(mb.Fehler, "Verweis"):
            mb.stilprofil_schreiben("apple", ("privat",), "x")
        with self.assertRaisesRegex(mb.Fehler, "länger"):
            mb.stilprofil_schreiben("apple", ("arbeit",), "x" * (mb.STILPROFIL_MAX + 1))

    def test_vorschau_fuer_den_dialog(self):
        self.assertEqual(mb.einstellungen_vorschau({"werte": {"kalender": {"default_calendar": "P"}, "mcp_nur_lesen": True}}),
                         "Plugin: apple\nAbschnitte: kalender (default_calendar), mcp_nur_lesen\nAchtung: Modus lesen")
        self.assertEqual(mb.einstellungen_vorschau({"plugin": "chat", "stilprofil": "chat", "text": "abc"}),
                         "Plugin: chat\nStilprofil: chat\nText: 3 Zeichen")


class GleicheDateien(unittest.TestCase):
    def test_mcp_basis_gleich_in_allen_plugins(self):
        """Im Paket gleich in chat und apple. Die Kopie in arbeit hat keine Nachbarn, dort vergleicht paket.py."""
        texte = {(PLUGIN.parent / p / "mcp_basis.py").read_text(encoding="utf-8")
                 for p in ("chat", "apple") if (PLUGIN.parent / p / "mcp_basis.py").exists()}
        self.assertLessEqual(len(texte), 1)


if __name__ == "__main__":
    unittest.main()
