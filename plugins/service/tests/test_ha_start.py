#!/usr/bin/env python3
"""Tests für ha_start.py (V6 Phase 4): leerer Server ohne Konfiguration, Startbefehl mit Adresse und Token, kein Token
in Meldungen, .mcp.json mit festem Python. Nichts erreicht den echten Schlüsselbund oder Home Assistant.

Aufruf im Plugin-Ordner: python3.12 -B -m unittest discover tests
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
ORDNER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ORDNER))
import ha_start  # noqa: E402

GEHEIM = "geheim-123-token"


class HaStart(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ha-start-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp)
        patcher = mock.patch.dict(os.environ, {"KITS_DATENORDNER": str(self.tmp)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.uvx = self.tmp / "uvx"
        self.uvx.write_text("#!/bin/sh\n", encoding="utf-8")
        self.uvx.chmod(0o755)
        self.security = self.tmp / "security"
        self.security.write_text(f"#!/bin/sh\necho {GEHEIM}\n", encoding="utf-8")
        self.security.chmod(0o755)
        p = mock.patch.object(ha_start, "SECURITY", str(self.security))
        p.start()
        self.addCleanup(p.stop)

    def config(self, ha):
        (self.tmp / "config.json").write_text(json.dumps({"skill_werte": {}, **({"homeassistant": ha} if ha else {})}),
                                              encoding="utf-8")

    def server(self, *nachrichten):
        """ha_start.py als Prozess wie in .mcp.json, Antworten je Zeile."""
        env = {**os.environ, "KITS_DATENORDNER": str(self.tmp)}
        eingabe = "".join(json.dumps(n) + "\n" for n in nachrichten)
        lauf = subprocess.run([sys.executable, "-B", str(ORDNER / "ha_start.py")], input=eingabe, capture_output=True,
                              text=True, timeout=30, env=env)
        return [json.loads(z) for z in lauf.stdout.splitlines()], lauf.stderr

    def test_datenordner_nur_application_support(self):
        """7.0: ohne KITS_DATENORDNER nur Application Support, kein Rückfall auf den Plugin-Ordner im Repo."""
        self.assertFalse(hasattr(ha_start, "PAKET_ORDNER"))
        app = self.tmp / "app"
        app.mkdir()
        with mock.patch.dict(os.environ, {"KITS_DATENORDNER": ""}), mock.patch.object(ha_start, "APP_DATEN", app):
            self.assertIsNone(ha_start.datenordner())
            (app / "config.json").write_text("{}", encoding="utf-8")
            self.assertEqual(ha_start.datenordner(), app)

    def test_ohne_block_leerer_server_mit_grund(self):
        self.config(None)
        antworten, fehler = self.server(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "ha_get_state"}})
        self.assertEqual(antworten[0]["result"]["serverInfo"]["name"], "homeassistant")
        self.assertIn("Block homeassistant fehlt", antworten[0]["result"]["instructions"])
        self.assertEqual(antworten[1]["result"], {"tools": []})
        self.assertEqual(antworten[2]["error"]["code"], -32601)
        self.assertIn("Block homeassistant fehlt", fehler)

    def test_ohne_config_leerer_server(self):
        antworten, _f = self.server({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(antworten[0]["result"], {"tools": []})

    def test_startbefehl_mit_adresse_und_token(self):
        self.config({"url": "http://192.0.2.10:8123/", "paket": "ha-mcp@9.1.2", "uvx": str(self.uvx)})
        argv, env = ha_start.startbefehl()
        self.assertEqual(argv, [str(self.uvx), "ha-mcp@9.1.2"])
        self.assertEqual(ha_start.startbefehl(paket="ha-mcp@9.2.0")[0][1], "ha-mcp@9.2.0")
        self.assertEqual(env["HOMEASSISTANT_URL"], "http://192.0.2.10:8123")
        self.assertEqual(env["HOMEASSISTANT_TOKEN"], GEHEIM)
        self.assertTrue(env["PATH"].startswith(str(self.tmp)))

    def test_token_nie_in_meldungen(self):
        self.security.write_text(f"#!/bin/sh\necho {GEHEIM}\nexit 44\n", encoding="utf-8")
        self.config({"url": "http://192.0.2.10:8123", "uvx": str(self.uvx)})
        with self.assertRaises(ha_start.Grund) as fall:
            ha_start.startbefehl()
        self.assertIn("homeassistant-claude", str(fall.exception))
        self.assertNotIn(GEHEIM, str(fall.exception))
        antworten, fehler = self.server({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertNotIn(GEHEIM, json.dumps(antworten) + fehler)

    def test_falsche_werte_werden_grund(self):
        for ha, text in (({"url": "ftp://x"}, "homeassistant.url"),
                         ({"url": "http://x:8123", "paket": "anderes-paket"}, "homeassistant.paket"),
                         ({"url": "http://x:8123", "schluesselbund": "a b; rm"}, "schluesselbund"),
                         ({"url": "http://x:8123", "uvx": "uvx"}, "homeassistant.uvx"),
                         ({"url": "http://x:8123", "uvx": str(self.tmp / "fehlt")}, "uvx nicht gefunden")):
            self.config(ha)
            with self.subTest(ha=ha), self.assertRaisesRegex(ha_start.Grund, text):
                ha_start.startbefehl()

    def test_mcp_json_startet_mit_festem_python(self):
        mcp = json.loads((ORDNER / ".mcp.json").read_text(encoding="utf-8"))
        ha = mcp["mcpServers"]["homeassistant"]
        self.assertEqual(ha["command"], "/Library/Developer/CommandLineTools/usr/bin/python3")
        self.assertEqual(ha["args"], ["${CLAUDE_PLUGIN_ROOT}/ha_start.py"])
        lesen = mcp["mcpServers"]["homeassistant-lesen"]
        self.assertEqual(lesen["command"], ha["command"])
        self.assertEqual(lesen["args"], ["${CLAUDE_PLUGIN_ROOT}/ha_start.py", "--lesen"])

    def test_vorgaben_und_hausregeln(self):
        """7.1: keine Settings-Seite, Geheimnisse geschwärzt, Hausregeln als eigene Instruktionen, kein Lesemodus."""
        self.config({"url": "http://192.0.2.10:8123", "uvx": str(self.uvx)})
        with mock.patch.dict(os.environ, {"READ_ONLY_MODE": ""}):
            _argv, env = ha_start.startbefehl()
        self.assertEqual(env["HA_MCP_DISABLE_SETTINGS_UI"], "1")
        self.assertEqual(env["REDACT_SECRETS"], "true")
        self.assertEqual(env["READ_ONLY_MODE"], "")
        self.assertIn("Hausregeln", env["HAMCP_CUSTOM_INSTRUCTIONS"])
        self.assertIn("ha_manage_backup", env["HAMCP_CUSTOM_INSTRUCTIONS"])
        self.assertEqual(_argv[1], ha_start.PAKET_STANDARD)

    def test_hausregeln_neutral_und_ohne_ki_zeichen(self):
        text = (ORDNER / "ha_regeln.md").read_text(encoding="utf-8")
        for zeichen in ("—", "–", "…", ";"):
            self.assertNotIn(zeichen, text)
        self.assertNotRegex(text, r"\d+\.\d+\.\d+\.\d+")  # keine Adresse
        self.assertLess(len(text), 2500)

    def test_ohne_hausregeln_startet_er_trotzdem(self):
        self.config({"url": "http://192.0.2.10:8123", "uvx": str(self.uvx)})
        with mock.patch.object(ha_start, "REGELN", self.tmp / "fehlt.md"), \
                mock.patch.dict(os.environ, {"HAMCP_CUSTOM_INSTRUCTIONS": ""}):
            _argv, env = ha_start.startbefehl()
        self.assertEqual(env["HAMCP_CUSTOM_INSTRUCTIONS"], "")

    def test_lesemodus_schlaegt_optionen(self):
        self.config({"url": "http://192.0.2.10:8123", "uvx": str(self.uvx), "optionen": {"READ_ONLY_MODE": False}})
        _argv, env = ha_start.startbefehl(lesen=True)
        self.assertEqual(env["READ_ONLY_MODE"], "true")
        _argv, env = ha_start.startbefehl(lesen=False)
        self.assertEqual(env["READ_ONLY_MODE"], "false")

    def test_optionen_ueberschreiben_vorgaben(self):
        self.config({"url": "http://192.0.2.10:8123", "uvx": str(self.uvx),
                     "optionen": {"HA_MCP_DISABLE_SETTINGS_UI": "0", "DISABLED_TOOLS": "ha_manage_hacs,ha_restart",
                                  "BACKUP_READ_ONLY": True}})
        _argv, env = ha_start.startbefehl()
        self.assertEqual(env["HA_MCP_DISABLE_SETTINGS_UI"], "0")
        self.assertEqual(env["DISABLED_TOOLS"], "ha_manage_hacs,ha_restart")
        self.assertEqual(env["BACKUP_READ_ONLY"], "true")

    def test_falsche_optionen_werden_grund(self):
        for roh, text in (([], "kein Objekt"), ({"HOMEASSISTANT_TOKEN": "x"}, "nicht erlaubt"),
                          ({"HAMCP_CUSTOM_INSTRUCTIONS": "x"}, "nicht erlaubt"),
                          ({"DISABLED_TOOLS": "a$(rm)"}, "kein einfacher Text"), ({"READ_ONLY_MODE": 1}, "kein einfacher")):
            self.config({"url": "http://x:8123", "uvx": str(self.uvx), "optionen": roh})
            with self.subTest(roh=roh), self.assertRaisesRegex(ha_start.Grund, text):
                ha_start.startbefehl()

    def test_paket_nur_mit_fester_version(self):
        self.assertRegex(ha_start.PAKET_STANDARD, ha_start.PAKET_RE)
        for paket in ("ha-mcp", "ha-mcp@latest", "ha-mcp@9.2"):
            self.config({"url": "http://x:8123", "uvx": str(self.uvx), "paket": paket})
            with self.subTest(paket=paket), self.assertRaisesRegex(ha_start.Grund, "feste"):
                ha_start.startbefehl()

    def test_lesen_leerer_server_traegt_eigenen_namen(self):
        env = {**os.environ, "KITS_DATENORDNER": str(self.tmp)}
        lauf = subprocess.run([sys.executable, "-B", str(ORDNER / "ha_start.py"), "--lesen"],
                              input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n",
                              capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual(json.loads(lauf.stdout)["result"]["serverInfo"]["name"], "homeassistant-lesen")
        self.assertIn("homeassistant-lesen:", lauf.stderr)

    def test_version_gleich_plugin_json(self):
        plugin = json.loads((ORDNER / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(ha_start.VERSION, plugin["version"])

    def test_rauchtest_mit_falschem_paket(self):
        self.config({"url": "http://x:8123", "uvx": str(self.uvx)})
        with mock.patch("builtins.print") as ausgabe:
            self.assertEqual(ha_start.main(["--rauchtest", "ha-mcp@latest"]), 1)
        self.assertIn("feste", ausgabe.call_args[0][0])

    def test_rauchtest_gegen_falschen_server(self):
        """Rauchtest mit einem erfundenen ha-mcp: normal fehlt ein Pflichtwerkzeug, lesend ist ha_call_service da."""
        falsch = self.tmp / "falsch.py"
        falsch.write_text(
            "import json, sys\n"
            "for z in sys.stdin:\n"
            "    n = json.loads(z)\n"
            "    if 'id' not in n: continue\n"
            "    m = n['method']\n"
            "    r = {'serverInfo': {'version': '0'}, 'instructions': 'Hausregeln'} if m == 'initialize' else \\\n"
            "        {'tools': [{'name': 'ha_call_service'}]} if m == 'tools/list' else {'content': []}\n"
            "    print(json.dumps({'jsonrpc': '2.0', 'id': n['id'], 'result': r}), flush=True)\n", encoding="utf-8")
        self.uvx.write_text(f"#!/bin/sh\nexec {sys.executable} -B {falsch}\n", encoding="utf-8")
        self.config({"url": "http://x:8123", "uvx": str(self.uvx)})
        with mock.patch("builtins.print") as ausgabe:
            self.assertEqual(ha_start.main(["--rauchtest", "ha-mcp@9.2.0"]), 1)
        zeilen = [c[0][0] for c in ausgabe.call_args_list]
        self.assertIn("Pflichtwerkzeuge fehlen", zeilen[0])
        self.assertIn("im Lesemodus sichtbar", zeilen[1])
        self.assertIn("nicht bestanden", zeilen[2])
        self.assertNotIn(GEHEIM, "".join(zeilen))

    def test_nur_standardbibliothek_ab_39(self):
        quelle = (ORDNER / "ha_start.py").read_text(encoding="utf-8")
        self.assertNotIn(" | None", quelle)  # kein Union-Typ in Annotationen, sonst bricht Python 3.9
        self.assertNotIn("match ", quelle)


if __name__ == "__main__":
    unittest.main()
