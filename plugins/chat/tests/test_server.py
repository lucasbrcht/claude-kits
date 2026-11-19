"""Tests für den MCP-Server chat: Zuschnitt der Werkzeuge, Argumente an die Skripte, Sendeschutz, Modus lesen."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN))

import mcp_basis as mb  # noqa: E402
import server  # noqa: E402

GRENZE_ALLE_SERVER = 34  # wie in apple/tests/test_server.py, 7.0: 31, 7.3: 36, 8.0: 34 (Arbeitskopien in office)


class Aufnahme:
    def __init__(self):
        self.aufrufe = []

    def __call__(self, skript, argumente, zeit=mb.ZEIT_STANDARD, textdateien=None):
        self.aufrufe.append((skript, list(argumente), dict(textdateien or {})))
        return 0, "ok"


def werkzeug_liste(plugin: str, **umgebung) -> list:
    with tempfile.TemporaryDirectory() as t:
        (Path(t) / "config.json").write_text("{}")
        env = {**os.environ, mb.UMGEBUNG: t, "KITS_NUR_LESEN": "", **umgebung}
        eingabe = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
        aus = subprocess.run([sys.executable, "-B", str(PLUGIN.parent / plugin / "server.py")], input=eingabe,
                             capture_output=True, text=True, timeout=20, env=env)
    return json.loads(aus.stdout.splitlines()[0])["result"]["tools"]


class Zuschnitt(unittest.TestCase):
    def test_werkzeuge_und_grenzen(self):
        for w in server.WERKZEUGE:
            liste = w.liste()
            self.assertRegex(w.name, r"^[a-z_]{3,64}$")
            self.assertLessEqual(len(w.beschreibung), mb.BESCHREIBUNG_MAX, w.name)
            self.assertTrue(liste["annotations"]["title"])
            self.assertFalse(liste["inputSchema"]["additionalProperties"])
            self.assertLessEqual(set(liste["inputSchema"].get("required", [])), set(w.eigenschaften), w.name)
            self.assertNotRegex(w.name, r"loesch|lösch|delete|verwerf|discard|entfern")

    def test_obergrenze_ueber_alle_server(self):
        gesamt = sum(len(werkzeug_liste(p)) for p in ("chat", "apple") if (PLUGIN.parent / p / "server.py").exists())
        self.assertLessEqual(gesamt, GRENZE_ALLE_SERVER)

    def test_stufe_passt_zur_annotation(self):
        for w in server.WERKZEUGE:
            a = w.annotationen()
            self.assertEqual(a["readOnlyHint"], w.stufe == "lesen", w.name)
            self.assertEqual(a["destructiveHint"], w.stufe == "nachfrage", w.name)
        self.assertEqual({w.name for w in server.WERKZEUGE if w.stufe == "nachfrage"}, {"imessage_senden"})

    def test_modus_lesen_ueber_protokoll(self):
        namen = {w["name"] for w in werkzeug_liste("chat", KITS_NUR_LESEN="1")}
        self.assertEqual(namen, {w.name for w in server.WERKZEUGE if w.stufe == "lesen"})
        self.assertNotIn("imessage_senden", namen)
        self.assertNotIn("whatsapp_entwurf", namen)


class Argumente(unittest.TestCase):
    def setUp(self):
        self.auf = Aufnahme()
        patcher = mock.patch.object(server, "lauf", self.auf)
        patcher.start()
        self.addCleanup(patcher.stop)
        dialog = mock.patch.dict(os.environ, {"KITS_DIALOG": "ja"})  # Dialog vor der Stufe nachfrage gilt als frei
        dialog.start()
        self.addCleanup(dialog.stop)

    def rufe(self, name, args):
        self.auf.aufrufe.clear()
        fehler, aus = mb.Server("chat", "t", server.WERKZEUGE).aufrufen(name, args)
        return fehler, aus, (self.auf.aufrufe[-1] if self.auf.aufrufe else None)

    def test_lesen(self):
        self.assertEqual(self.rufe("chat_neues", {"dienst": "whatsapp", "stunden": 6})[2][:2],
                         ("whatsapp.py", ["triage", "6"]))
        self.assertEqual(self.rufe("chat_lesen", {"dienst": "imessage", "chat": "-Mama", "limit": 20,
                                                  "alle": True})[2][:2],
                         ("imessage.py", ["read", "--limit=20", "--all", "--", "-Mama"]))
        self.assertEqual(self.rufe("chat_lesen", {"dienst": "whatsapp", "id": 5, "seit": "2026-11-01"})[2][1],
                         ["read", "--id=5", "--since=2026-11-01"])
        self.assertTrue(self.rufe("chat_lesen", {"dienst": "whatsapp", "chat": "x", "alle": True})[0])
        self.assertTrue(self.rufe("chat_lesen", {"dienst": "whatsapp"})[0])  # ohne Ziel
        self.assertTrue(self.rufe("chat_lesen", {"dienst": "signal", "chat": "x"})[0])
        self.assertEqual(self.rufe("chat_suchen", {"dienst": "whatsapp", "begriffe": ["Grill", "-Samstag"],
                                                   "von_mir": True})[2][1],
                         ["search", "--from-me", "--", "Grill", "-Samstag"])
        self.assertEqual(self.rufe("chat_liste", {"dienst": "imessage", "suche": ["Ma"], "limit": 5})[2][1],
                         ["chats", "--query=Ma", "--limit=5"])
        self.assertEqual(self.rufe("chat_liste", {"dienst": "whatsapp", "mitglieder_von": "Familie"})[2][1],
                         ["members", "--", "Familie"])

    def test_entwuerfe_senden_nie(self):
        _, _, (skript, argv, dateien) = self.rufe("whatsapp_entwurf", {"chat": "Mama", "text": "Bis gleich 😊",
                                                                     "ersetzen": True})
        self.assertEqual((skript, argv), ("whatsapp.py", ["--replace", "draft", "--text-file=nachricht.txt",
                                                          "--", "Mama"]))
        self.assertEqual(dateien, {"nachricht.txt": "Bis gleich 😊"})
        _, _, (skript, argv, _) = self.rufe("imessage_entwurf", {"id": 3, "text": "Hi", "stil_ignorieren": True})
        self.assertEqual((skript, argv), ("imessage.py", ["--ignore-style", "draft", "--id=3",
                                                          "--text-file=nachricht.txt"]))
        for name in ("whatsapp_entwurf", "imessage_entwurf"):
            _, _, (_, argv, _) = self.rufe(name, {"chat": "send", "text": "send"})
            self.assertNotIn("send", argv[:argv.index("--")], name)

    def test_imessage_senden(self):
        _, _, (skript, argv, dateien) = self.rufe("imessage_senden", {"chat": "Mama", "id": 3, "text": "Bin da"})
        self.assertEqual((skript, argv), ("imessage.py", ["send", "--id=3", "--text=Bin da", "--", "Mama"]))
        self.assertEqual(dateien, {})
        self.assertTrue(self.rufe("imessage_senden", {"chat": "Mama"})[0])

    def test_dialog_in_stichworten(self):
        self.assertEqual(server.senden_vorschau({"chat": "Mama", "id": 3, "text": "Bin\n da", "stil_ignorieren": True}),
                         "An: Mama\nText: Bin da")
        lang = server.senden_vorschau({"id": 3, "text": "x" * 500, "nochmal": True})
        self.assertTrue(lang.startswith("An: Chat-ID 3\nText: " + "x" * 160 + " [gekürzt]"))
        self.assertTrue(lang.endswith("\nErneut, gleicher Text"))

    def test_stilprofil(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "style").mkdir()
            (Path(t) / "style" / "profil.md").write_text("Kurz.", encoding="utf-8")
            with mock.patch.dict(os.environ, {mb.UMGEBUNG: t}):
                self.assertEqual(self.rufe("chat_stilprofil", {})[:2], (False, "Kurz."))

    def test_stilprobe_fuer_die_einrichtung(self):
        """7.0: Die Stilprobe läuft über den Server, in Cowork erreicht Bash WhatsApp nicht."""
        self.assertEqual(self.rufe("chat_stilprofil", {"stilprobe": 200})[2][:2],
                         ("whatsapp.py", ["style", "--n=200", "--max-chars=50000"]))
        self.assertTrue(self.rufe("chat_stilprofil", {"stilprobe": 5})[0])


if __name__ == "__main__":
    unittest.main()
