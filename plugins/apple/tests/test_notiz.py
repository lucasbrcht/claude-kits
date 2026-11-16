"""Tests für notiz.py ohne Apple Notes: osascript ist durch einen Ersatz ersetzt, der jedes Skript mitschreibt und
vorbereitete Antworten liefert. Läuft in der Sandbox, berührt keine echte Notiz.

Aufruf im Kit-Ordner: python3 -B -m unittest discover tests
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True  # kein __pycache__ für notiz.py und kit_basis.py, für diese Datei sorgt -B im Aufruf
KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
import notiz  # noqa: E402

T, Z = notiz.TRENNER, notiz.ZEILE


class Notes:
    """Ersatz für osascript: merkt sich jedes Skript und liefert die Antworten der Reihe nach (rc, stdout, stderr).
    Eine Ausnahme als Antwort wird geworfen, etwa subprocess.TimeoutExpired."""

    def __init__(self, *antworten):
        self.skripte, self.antworten = [], list(antworten)

    def __call__(self, script):
        self.skripte.append(script)
        antwort = self.antworten.pop(0) if self.antworten else (0, "", "")
        if isinstance(antwort, BaseException):
            raise antwort
        rc, out, err = antwort
        return subprocess.CompletedProcess(["osascript", "-"], rc, out, err)


class NotizTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="notiz-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.config({"notizen": {"ausgeschlossene_ordner": ["Privat"]}})
        for p in (mock.patch.object(notiz, "KIT", self.tmp), mock.patch.object(notiz.time, "sleep", lambda s: None)):
            p.start()
            self.addCleanup(p.stop)
        alt = os.getcwd()
        os.chdir("/")  # wie ein Kit-Befehl mit absolutem Pfad: die Shell steht nicht im Kit
        self.addCleanup(os.chdir, alt)

    def config(self, cfg):
        (self.tmp / "config.json").write_text(cfg if isinstance(cfg, str) else json.dumps(cfg), encoding="utf-8")

    def lauf(self, notes, *argv):
        """(Ausgabe, Exit-Code oder Meldung, sonst None)."""
        out = io.StringIO()
        with mock.patch.object(notiz, "_lauf", notes), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            try:
                notiz.main(list(argv))
            except SystemExit as e:
                return out.getvalue(), e.code
        return out.getvalue(), None

    def kette_geprueft(self, skript):
        """F9: Der Handler frei steht vor dem Hauptteil und geht die Containerkette bis zum Konto, mit allen
        Ausschlüssen samt Papierkorb, und die Ordnerschleife fragt ihn. Der alte Test nur auf den eigenen Namen fehlt."""
        self.assertIn("on frei(c)", skript)
        self.assertLess(skript.index("end frei"), skript.rindex('tell application "Notes"'))
        for zeile in ("set c to container of c", "if typ is account then return true",
                      "if typ is not folder then return false"):
            self.assertIn(zeile, skript)
        for ordner in ("Privat", "Recently Deleted", "Zuletzt gelöscht"):
            self.assertIn(f'cname is "{ordner}"', skript)
        self.assertIn("my frei(fo)", skript)
        self.assertNotIn("fname is not", skript)

    # --- lesen

    def test_ordner_ohne_ausgeschlossene_und_papierkorb(self):
        notes = Notes((0, f"0{Z}Inbox{T}3{Z}Arbeit{T}5{Z}", ""))  # vorn die Zahl der Ausschlüsse ohne Ordner
        out, fehler = self.lauf(notes, "folders")
        self.assertIsNone(fehler)
        self.assertEqual(out.splitlines(), ["ordner | notizen", "Inbox | 3", "Arbeit | 5"])
        self.kette_geprueft(notes.skripte[0])
        self.assertIn("set fo to contents of f", notes.skripte[0])
        self.assertIn("(count of notes of fo)", notes.skripte[0])

    def test_unterordner_ausgeschlossener_ordner_ueber_die_kette(self):
        """F9 (Prüfung 20.10.2026): Ein Unterordner von Privat heißt anders und kam am Namensvergleich vorbei. Jeder
        Befehl, der Ordner auflistet, sucht, liest, anlegt oder ersetzt, fragt jetzt die ganze Kette."""
        datei = self.tmp / "notiz.md"
        datei.write_text("Text", encoding="utf-8")
        laeufe = (
            (("folders",), Notes((0, f"0{Z}", ""))),
            (("list",), Notes((0, "", ""))),
            (("list", "--folder", "Steuern"), Notes((0, "", ""))),
            (("read", "Plan"), Notes((0, "NICHTGEFUNDEN", ""))),
            (("read", "Plan", "--folder", "Steuern"), Notes((0, "NICHTGEFUNDEN", ""))),
            (("search", "Plan"), Notes((0, "", ""))),
            (("add", "--title", "X", "--file", "notiz.md", "--folder", "Steuern"), Notes((0, "NICHTFREI", ""))),
            (("add", "--title", "X", "--file", "notiz.md"), Notes((0, "NICHTFREI", ""))),
            (("replace", "Plan", "--file", "notiz.md", "--folder", "Steuern"), Notes((0, f"Steuern{Z}", ""),
                                                                                      (0, "Steuern", ""))),
        )
        for befehl, notes in laeufe:
            self.lauf(notes, *befehl)
            self.assertTrue(notes.skripte, befehl)
            for skript in notes.skripte:
                with self.subTest(befehl=befehl):
                    self.kette_geprueft(skript)
            if "Steuern" in befehl:  # der Name allein reicht nicht, die Kette muss frei sein
                self.assertIn('fname is "Steuern" and my frei(fo)', notes.skripte[0], befehl)
            if befehl[0] == "add":  # ohne freien Ordner nichts angelegt, die Textdatei bleibt
                self.assertTrue(datei.exists(), befehl)
        self.assertFalse(datei.exists())  # replace hat sie nach Erfolg gelöscht

    def test_liste_mit_hinweis_daten_statt_anweisungen(self):
        out, _fehler = self.lauf(Notes((0, f"Plan{T}Inbox{T}Montag{Z}", "")), "list", "--limit", "5")
        self.assertIn(notiz.HINWEIS, out)
        self.assertIn("Plan | Inbox | Montag", out)

    def test_steuerzeichen_in_notizen_werden_entfernt(self):
        """Prüfung 20.10.2026: Terminalfarben und Richtungszeichen aus Notizen landen nicht im Transkript."""
        out, _fehler = self.lauf(Notes((0, f"Rot\x1b[31m‮{T}Inbox{T}Montag{Z}", "")), "list")
        self.assertIn("Rot | Inbox | Montag", out)
        self.assertNotIn("\x1b", out)
        out, _fehler = self.lauf(Notes((0, f"Plan{T}Inbox{T}Montag{T}false{T}Zeile 1\n\x1b[0mZeile 2\x07", "")), "read",
                                 "Plan")
        self.assertIn("Zeile 1\nZeile 2", out)
        self.assertNotIn("\x07", out)

    def test_ausgeschlossener_ordner_wird_nie_gefragt_und_nie_bestaetigt(self):
        """Ein ausgeschlossener --folder fragt Notes nie und meldet sich genau wie ein unbekannter (Review 21.10.2026:
        "ist ausgeschlossen" bestätigte den Ausschluss), auch klein geschrieben, mit Leerzeichen oder als Papierkorb."""
        (self.tmp / "notiz.md").write_text("Text", encoding="utf-8")
        faelle = ((("list", "--folder", "{}"), (0, "", "")),
                  (("read", "X", "--folder", "{}"), (0, "NICHTGEFUNDEN", "")),
                  (("add", "--title", "X", "--file", "notiz.md", "--folder", "{}"), (0, "NICHTFREI", "")),
                  (("replace", "X", "--file", "notiz.md", "--folder", "{}"), (0, "", "")))
        for muster, antwort in faelle:
            unbekannt = self.lauf(Notes(antwort), *(a.format("Gibt es nicht") for a in muster))
            for gesperrt in ("Privat", "privat ", "recently deleted"):
                notes = Notes()
                aus = self.lauf(notes, *(a.format(gesperrt) for a in muster))
                with self.subTest(befehl=muster[0], ordner=gesperrt):
                    self.assertEqual(notes.skripte, [])
                    self.assertEqual(aus, tuple(x.replace("Gibt es nicht", gesperrt) if isinstance(x, str) else x
                                                for x in unbekannt))
                    self.assertNotIn("ist ausgeschlossen", str(aus))
        self.assertTrue((self.tmp / "notiz.md").exists())  # nichts angelegt oder ersetzt

    def test_lesen_mit_unerwarteter_antwort_ohne_traceback(self):
        _out, fehler = self.lauf(Notes((0, "nur ein Feld", "")), "read", "Plan")
        self.assertIn("unerwartete Antwort", fehler)

    def test_lesen_bei_dubletten_nennt_die_ordner(self):
        """Prüfung 20.10.2026: read nahm bei zwei Notizen mit gleichem Titel still die erste, jetzt wie replace Code 2
        mit den Ordnern und ohne Inhalt."""
        notes = Notes((0, f"MEHRDEUTIG{Z}Inbox{Z}Arbeit\x1b[31m{Z}", ""))
        out, fehler = self.lauf(notes, "read", "Plan")
        self.assertEqual(fehler, 2)
        self.assertEqual(out.strip(), "2 Notizen heißen 'Plan' (Ordner: Inbox, Arbeit). Nicht eindeutig, nichts "
                                      "gelesen. Mit --folder eingrenzen.")
        skript = notes.skripte[0]
        self.assertIn("set anzahl to anzahl + 1", skript)
        self.assertLess(skript.index(f'if anzahl > 1 then return "MEHRDEUTIG{Z}" & orte'),
                        skript.index("(plaintext of erste)"))  # erst zählen, Inhalt nur bei genau einem Treffer
        out, fehler = self.lauf(Notes((0, f"Plan{T}Arbeit{T}Montag{T}false{T}Text", "")), "read", "Plan", "--folder",
                                "Arbeit")
        self.assertIsNone(fehler)
        self.assertIn("Ordner:   Arbeit", out)

    def test_lesen_mit_obergrenze(self):
        """Prüfung 20.10.2026: read zeigte jede Länge. Jetzt höchstens LESE_MAX Zeichen mit Hinweis, alles mit
        --max-chars 0."""
        lang = "a" * (notiz.LESE_MAX + 5)
        antwort = (0, f"Plan{T}Inbox{T}Montag{T}false{T}{lang}", "")
        out, fehler = self.lauf(Notes(antwort), "read", "Plan")
        self.assertIsNone(fehler)
        self.assertTrue(out.endswith("a" * notiz.LESE_MAX + f"\n[gekürzt, {notiz.LESE_MAX + 5} Zeichen gesamt, alles "
                                                             f"mit --max-chars 0]\n"))
        self.assertNotIn("a" * (notiz.LESE_MAX + 1), out)
        out, fehler = self.lauf(Notes(antwort), "read", "Plan", "--max-chars", "0")
        self.assertIsNone(fehler)
        self.assertTrue(out.endswith(lang + "\n"))
        out, _fehler = self.lauf(Notes(antwort), "read", "Plan", "--max-chars", "10")
        self.assertIn("\n\naaaaaaaaaa\n[gekürzt, ", out)
        kurz = "b" * notiz.LESE_MAX  # genau an der Grenze bleibt alles
        out, _fehler = self.lauf(Notes((0, f"Plan{T}Inbox{T}Montag{T}false{T}{kurz}", "")), "read", "Plan")
        self.assertNotIn("gekürzt", out)

    def test_suche_in_titel_und_inhalt(self):
        """O6 (Prüfung 20.10.2026): search ist der Hauptweg von Testprompt 76 und hatte keinen eigenen Test. Treffer mit
        Kopf und Datenhinweis, Suchtext sicher im Skript, Obergrenze, nur freie Ordner, ohne Treffer eine Zeile."""
        notes = Notes((0, f"Paris Wochenende{T}Reisen{T}Montag{Z}Packliste{T}Inbox\x1b[31m{T}Dienstag{Z}", ""))
        out, fehler = self.lauf(notes, "search", 'Paris "Sa"', "--limit", "5")
        self.assertIsNone(fehler)
        self.assertEqual(out.splitlines(), [f"titel | ordner | geändert  {notiz.HINWEIS}",
                                            "Paris Wochenende | Reisen | Montag", "Packliste | Inbox | Dienstag"])
        skript = notes.skripte[0]
        self.assertIn('if (t contains "Paris \\"Sa\\"") or (k contains "Paris \\"Sa\\"") then', skript)
        self.assertIn("if zaehler >= 5 then exit repeat", skript)
        self.kette_geprueft(skript)
        out, fehler = self.lauf(Notes((0, "", "")), "search", "Gibt es nicht")
        self.assertIsNone(fehler)
        self.assertEqual(out.strip(), "Keine Notiz enthält 'Gibt es nicht'.")

    def test_limit_beendet_auch_die_ordnerschleife(self):
        """Review 21.10.2026: --limit beendete nur die innere Schleife, search las danach alle Ordner weiter. --limit
        unter 1 lieferte still "Keine Notizen gefunden", jetzt Code 2 ohne Frage an Notes."""
        for befehl in (("list", "--limit", "5"), ("search", "Plan", "--limit", "5")):
            notes = Notes((0, "", ""))
            self.lauf(notes, *befehl)
            skript = notes.skripte[0]
            self.assertEqual(skript.count("if zaehler >= 5 then exit repeat"), 2, befehl)
            self.assertLess(skript.index("if zaehler >= 5 then exit repeat"), skript.index("set fo to contents of f"))
        for befehl in (("list", "--limit", "0"), ("search", "Plan", "--limit", "-1"), ("read", "Plan", "--max-chars",
                                                                                         "-1")):
            notes = Notes()
            _out, fehler = self.lauf(notes, *befehl)
            self.assertEqual(fehler, 2, befehl)
            self.assertEqual(notes.skripte, [])

    def test_nummern_in_titeln_bei_list_und_search_maskiert(self):
        """Review 21.10.2026: Titel mit Konto- oder Telefonnummern standen bei list und search im Klartext. read zeigt
        den Titel vollständig."""
        antwort = (0, f"Konto DE36 5900 0000 0059 0010 54{T}Inbox{T}Montag{Z}Tel 0176 1234 5678{T}Inbox{T}Montag{Z}", "")
        for befehl in (("list",), ("search", "Konto")):
            out, fehler = self.lauf(Notes(antwort), *befehl)
            self.assertIsNone(fehler)
            self.assertIn("Konto [Nummer] | Inbox | Montag\nTel [Nummer] | Inbox | Montag", out, befehl)
            self.assertNotIn("5900", out)
        out, _fehler = self.lauf(Notes((0, f"Tel 0176 1234 5678{T}Inbox{T}Montag{T}false{T}Text", "")), "read",
                                 "Tel 0176 1234 5678")
        self.assertIn("Titel:    Tel 0176 1234 5678", out)

    def test_lesen_nennt_geteilte_notizen(self):
        """Review 21.10.2026: read nennt geteilte Notizen und Ordner, damit vor replace klar ist, dass andere die
        Änderung sehen. Ist shared nicht lesbar oder die Antwort unklar, gilt die Notiz als geteilt."""
        out, _fehler = self.lauf(Notes((0, f"Plan{T}Familie{T}Montag{T}true{T}Text", "")), "read", "Plan")
        self.assertIn("Geändert: Montag\nGeteilt:  ja\n", out)
        out, _fehler = self.lauf(Notes((0, f"Plan{T}Familie{T}Montag{T}{T}Text", "")), "read", "Plan")
        self.assertIn("Geteilt:  ja", out)
        notes = Notes((0, f"Plan{T}Inbox{T}Montag{T}false{T}Text", ""))
        out, _fehler = self.lauf(notes, "read", "Plan")
        self.assertNotIn("Geteilt", out)
        skript = notes.skripte[0]
        self.assertIn("set teilt to my geteilt(ersterFo)", skript)
        self.assertIn("if (shared of erste) is not false then set teilt to true\n      on error\n        set teilt to "
                      "true", skript)

    def test_lesen_als_html_fuer_replace(self):
        """Review 21.10.2026: replace baute auf dem Klartext von read auf, Formatierung, Tabellen und Links gingen still
        verloren. read --html liefert den HTML-Inhalt als Grundlage."""
        html_text = '<div><b>Plan</b></div><ul><li>Zelt</li></ul><a href="https://example.com">Ort</a>'
        notes = Notes((0, f"Plan{T}Inbox{T}Montag{T}false{T}{html_text}", ""))
        out, fehler = self.lauf(notes, "read", "Plan", "--html")
        self.assertIsNone(fehler)
        self.assertTrue(out.endswith(f"\n\n{html_text}\n"))
        self.assertIn("(body of erste)", notes.skripte[0])
        self.assertNotIn("plaintext", notes.skripte[0])
        notes = Notes((0, f"Plan{T}Inbox{T}Montag{T}false{T}Plan", ""))
        self.lauf(notes, "read", "Plan")
        self.assertIn("(plaintext of erste)", notes.skripte[0])

    # --- anlegen und ersetzen nur aus der festen Datei

    def test_anlegen_aus_notiz_html_im_kit_auch_ohne_cd(self):
        (self.tmp / "notiz.html").write_text("<table><tr><td>Tag</td></tr></table>", encoding="utf-8")
        notes = Notes((0, f"Reiseplan{T}Notizen{T}false", ""))
        out, fehler = self.lauf(notes, "add", "--title", "Reiseplan", "--file", "notiz.html")
        self.assertIsNone(fehler)
        self.assertEqual(out.strip(), "Angelegt: Reiseplan in Notizen")  # der echte Name des Standardordners
        self.assertIn('make new note at ziel with properties {name:"Reiseplan"', notes.skripte[0])
        self.assertFalse((self.tmp / "notiz.html").exists())  # nach Erfolg gelöscht

    def test_titel_im_inhalt_nicht_doppelt(self):
        """V6 Phase 4, T7: Beginnt der Inhalt mit dem Titel (Markdown-Überschrift, HTML mit Kopf, andere Schreibweise),
        legt add ohne name an, Notes nimmt die erste Zeile als Titel. Sonst mit name wie bisher."""
        faelle = (("notiz.md", "# Test  Phase 4\n\nText", "Test Phase 4", False),
                  ("notiz.md", "test phase 4\nText", "Test Phase 4", False),
                  ("notiz.html", "<html><head><title>Kopf</title></head><body><div><b>Plan&nbsp;Juni</b></div>"
                                 "<div>Text</div></body></html>", "Plan Juni", False),
                  ("notiz.md", "Erledigt\nTest Phase 4", "Test Phase 4", True),
                  ("notiz.md", "Test Phase 4 und mehr", "Test Phase 4", True),
                  ("notiz.html", "<table><tr><td>Tag</td></tr></table>", "Tag 1", True))
        for datei, text, titel, mit_name in faelle:
            (self.tmp / datei).write_text(text, encoding="utf-8")
            notes = Notes((0, f"{titel}{T}Notizen{T}false", ""))
            out, fehler = self.lauf(notes, "add", "--title", titel, "--file", datei)
            self.assertIsNone(fehler, text)
            self.assertEqual(out.strip(), f"Angelegt: {titel} in Notizen")
            self.assertEqual("with properties {name:" in notes.skripte[0], mit_name, text)
            if not mit_name:
                self.assertIn("make new note at ziel with properties {body:t}", notes.skripte[0])

    def test_erste_zeile(self):
        self.assertEqual(notiz.erste_zeile("<br><div> </div><h1>A &amp; B</h1><div>x</div>"), "A & B")
        self.assertEqual(notiz.erste_zeile("<div>a<br>b</div>"), "a")
        self.assertEqual(notiz.erste_zeile(""), "")
        self.assertFalse(notiz.titel_vorn("<div>x</div>", " "))

    def test_anlegen_nur_in_freiem_standardordner(self):
        """Prüfung 20.10.2026: add ohne --folder legte in den Standardordner, ohne ihn gegen die Ausschlüsse zu prüfen.
        Jetzt fragt es erst die Kette und legt sonst nichts an."""
        datei = self.tmp / "notiz.md"
        datei.write_text("Text", encoding="utf-8")
        notes = Notes((0, "NICHTFREI", ""))
        out, fehler = self.lauf(notes, "add", "--title", "X", "--file", "notiz.md")
        self.assertEqual(fehler, "Der Standardordner von Notizen ist ausgeschlossen. Nichts angelegt, mit --folder "
                                 "einen freien Ordner angeben.")
        self.assertEqual(out, "")
        skript = notes.skripte[0]
        self.assertIn("set fo to default folder of default account\n      if my frei(fo) then set ziel to fo", skript)
        self.assertLess(skript.index('if ziel is missing value then return "NICHTFREI"'), skript.index("make new note"))
        self.assertNotIn("at default account", skript)
        self.assertTrue(datei.exists())  # nichts angelegt, die Textdatei bleibt
        _out, fehler = self.lauf(Notes((0, "NICHTFREI", "")), "add", "--title", "X", "--file", "notiz.md",
                                 "--folder", "Steuern")
        self.assertEqual(fehler, "Ordner Steuern nicht gefunden oder ausgeschlossen. Nichts angelegt, freie Ordner zeigt "
                                 "folders.")
        self.assertTrue(datei.exists())

    def test_anlegen_in_geteiltem_ordner_erst_vorschau(self):
        """Review 21.10.2026: add schrieb ohne Rückfrage in geteilte Ordner, andere sahen die Notiz sofort. Jetzt wie bei
        geteilten Erinnerungslisten erst die Vorschau mit Titel, Ordner und Zeichenzahl, --ausfuehren legt an (der Server
        fragt per Dialog nach). Ist shared nicht lesbar oder die Kette unklar, gilt der Ordner als geteilt."""
        datei = self.tmp / "notiz.md"
        text = "Zelt\nSchlafsack"
        datei.write_text(text, encoding="utf-8")
        notes = Notes((0, f"GETEILT{T}Familie\x1b[31m", ""))
        out, fehler = self.lauf(notes, "add", "--title", "Packliste", "--file", "notiz.md", "--folder", "Familie")
        self.assertIsNone(fehler)
        self.assertEqual(out.strip(), f"Vorschau, nichts angelegt: Packliste im geteilten Ordner Familie ({len(text)} "
                                      f"Zeichen, andere sehen die Notiz sofort). Anlegen mit notiz_geteilt, das zeigt "
                                      "einen Dialog am Mac.")
        self.assertTrue(datei.exists())  # bleibt für den Aufruf mit --ausfuehren
        skript = notes.skripte[0]
        self.assertIn("set teilt to my geteilt(ziel)", skript)
        self.assertLess(skript.index(f'if teilt then return "GETEILT{T}" & (name of ziel)'), skript.index("make new note"))
        for zeile in ("if (shared of c) is not false then return true", "on error\n            return true",
                      "if typ is account then return false", "if typ is not folder then return true"):
            self.assertIn(zeile, skript)
        self.assertLess(skript.index("end geteilt"), skript.rindex('tell application "Notes"'))
        _out, fehler = self.lauf(notes, "add", "--title", "Packliste", "--file", "notiz.md", "--folder", "Familie",
                                 "--ausfuehren")  # V3.1: nur direkt hinter dem Skript
        self.assertIn("--ausfuehren steht nur direkt hinter dem Skript", fehler)
        notes = Notes((0, f"Packliste{T}Familie{T}true", ""))
        out, fehler = self.lauf(notes, "--ausfuehren", "add", "--title", "Packliste", "--file", "notiz.md", "--folder",
                                "Familie")
        self.assertIsNone(fehler)
        self.assertEqual(out.strip(), "Angelegt: Packliste in Familie (geteilt, andere sehen die Notiz)")
        self.assertNotIn('return "GETEILT', notes.skripte[0])
        self.assertFalse(datei.exists())

    def test_html_ohne_lokale_dateien_und_fremde_quellen(self):
        """Review 21.10.2026 (vorsorglich): Verweise, die Notes beim Anlegen nachladen könnte, brechen ab, bevor etwas
        an Notes geht. Eingebettete Bilder (data:), Links und Text in Markdown bleiben erlaubt."""
        notes = Notes()
        datei = self.tmp / "notiz.html"
        for html_text in ('<img src="https://example.com/a.png">', "<img src='http://example.com/a.png'>",
                          "<IMG SRC=https://example.com/a.png>", '<a href="file:///etc/hosts">x</a>',
                          '<img src="file:///Users/x/a.png">', '<img srcset="https://example.com/a.png 2x">',
                          '<div style="background:url(https://example.com/a.png)">x</div>',
                          '<style>@import "https://example.com/a.css"</style>'):
            datei.write_text(html_text, encoding="utf-8")
            for befehl in (("add", "--title", "X", "--file", "notiz.html"), ("replace", "X", "--file", "notiz.html")):
                _out, fehler = self.lauf(notes, *befehl)
                self.assertEqual(fehler, "notiz.html verweist auf eine lokale Datei oder lädt Inhalte von außen (file:, "
                                         "src oder url() ohne data:, srcset, @import). Erlaubt sind Text, Links und "
                                         "eingebettete Bilder (data:). Nichts geändert.", html_text)
        self.assertEqual(notes.skripte, [])
        self.assertTrue(datei.exists())
        for html_text in ('<img src="data:image/png,x">', '<a href="https://www.google.com/maps/search/?api=1">Ort</a>',
                          "<div>Profile: Max, url(x), file: a.txt</div>"):
            datei.write_text(html_text, encoding="utf-8")
            self.assertEqual(notiz.datei_als_html(notiz.text_datei("notiz.html")), html_text)
        (self.tmp / "notiz.md").write_text("Siehe file:///etc/hosts und url(http://x)", encoding="utf-8")
        self.assertIn("file:///etc/hosts", notiz.datei_als_html(notiz.text_datei("notiz.md")))  # Markdown lädt nichts
        (self.tmp / "notiz.md").write_text('<div><img src="https://example.com/a.png"></div>', encoding="utf-8")
        _out, fehler = self.lauf(notes, "add", "--title", "X", "--file", "notiz.md")  # Markdown, das als HTML durchgeht
        self.assertIn("notiz.md verweist auf eine lokale Datei", fehler)
        start = time.monotonic()
        self.assertFalse(notiz.fremdquelle("<a " * 100_000))  # mit <[^>]* brauchten 60 KB schon 26 s
        self.assertLess(time.monotonic() - start, 2)

    def test_html_bleibt_markdown_wird_schlichtes_html(self):
        (self.tmp / "notiz.html").write_text("<table><tr><td>A</td></tr></table>", encoding="utf-8")
        self.assertEqual(notiz.datei_als_html(notiz.text_datei("notiz.html")), "<table><tr><td>A</td></tr></table>")
        (self.tmp / "notiz.md").write_text("# Titel\n- Punkt & mehr\n- -20 °C morgens\n## #Hashtag\n", encoding="utf-8")
        text = notiz.datei_als_html(notiz.text_datei("notiz.md"))
        self.assertIn("<h1>Titel</h1>", text)
        self.assertIn("<div>&bull; Punkt &amp; mehr</div>", text)
        self.assertIn("<div>&bull; -20 °C morgens</div>", text)  # Review 20.10.2026: nur das Präfix fällt weg
        self.assertIn("<h2>#Hashtag</h2>", text)

    def test_andere_dateien_werden_nie_gelesen(self):
        fremd = self.tmp / "fremd.md"
        fremd.write_text("Firma vertraulich", encoding="utf-8")
        notes = Notes()
        for angabe in ("fremd.md", str(fremd), "/etc/hosts", "../notiz.md", "unter/notiz.md"):
            _out, fehler = self.lauf(notes, "add", "--title", "X", "--file", angabe)
            self.assertIn("Text nur aus notiz.html oder notiz.md", fehler, angabe)
        (self.tmp / "notiz.md").symlink_to(fremd)  # auch kein Umweg über einen Verweis
        _out, fehler = self.lauf(notes, "add", "--title", "X", "--file", "notiz.md")
        self.assertIn("Text nur aus", fehler)
        (self.tmp / "notiz.md").unlink()
        os.link(fremd, self.tmp / "notiz.md")  # Review 20.10.2026: auch kein harter Verweis
        _out, fehler = self.lauf(notes, "add", "--title", "X", "--file", "notiz.md")
        self.assertIn("harter Verweis", fehler)
        self.assertEqual(notes.skripte, [])
        self.assertTrue(fremd.exists())

    def test_fehlende_oder_falsch_kodierte_datei(self):
        _out, fehler = self.lauf(Notes(), "add", "--title", "X", "--file", "notiz.md")
        self.assertIn("notiz.md fehlt im Kit-Ordner", fehler)
        (self.tmp / "notiz.md").write_bytes(b"\xff\xfe\x00x")
        _out, fehler = self.lauf(Notes(), "add", "--title", "X", "--file", "notiz.md")
        self.assertIn("kein UTF-8", fehler)

    def test_ersetzen_nur_bei_genau_einem_treffer(self):
        datei = self.tmp / "notiz.md"
        datei.write_text("neu", encoding="utf-8")
        zwei = Notes((0, f"Inbox{Z}Arbeit{Z}", ""))
        out, fehler = self.lauf(zwei, "replace", "Plan", "--file", "notiz.md")
        self.assertEqual(fehler, 2)
        self.assertIn("2 Notizen heißen 'Plan' (Ordner: Inbox, Arbeit). Nicht eindeutig, nichts geändert", out)
        self.assertEqual(len(zwei.skripte), 1)  # nur gesucht, nichts geschrieben
        self.assertNotIn("set body", zwei.skripte[0])
        _out, fehler = self.lauf(Notes((0, "", "")), "replace", "Plan", "--file", "notiz.md")
        self.assertIn("Keine Notiz mit dem Titel 'Plan' gefunden. Nichts geändert.", fehler)
        self.assertTrue(datei.exists())
        eins = Notes((0, f"Inbox{Z}", ""), (0, "Inbox", ""))
        out, fehler = self.lauf(eins, "replace", "Plan", "--file", "notiz.md", "--folder", "Inbox")
        self.assertIsNone(fehler)
        self.assertEqual(out.strip(), "Ersetzt: Plan in Inbox")
        self.assertIn("set body of theNote to t", eins.skripte[1])
        self.assertIn('fname is "Inbox"', eins.skripte[0])
        self.assertFalse(datei.exists())

    def test_ersetzen_meldet_neuen_titel(self):
        """Review 21.10.2026: set body benennt die Notiz nach der ersten Zeile um, ohne dass es jemand merkte. replace
        gibt den neuen Namen zurück und nennt ihn, wenn er vom alten Titel abweicht."""
        datei = self.tmp / "notiz.html"
        datei.write_text("<h1>Packliste Paris</h1>", encoding="utf-8")
        notes = Notes((0, f"Inbox{Z}", ""), (0, f"Inbox{T}Packliste Paris", ""))
        out, fehler = self.lauf(notes, "replace", "Packliste", "--file", "notiz.html")
        self.assertIsNone(fehler)
        self.assertEqual(out.splitlines(), ["Ersetzt: Packliste in Inbox",
                                            "Achtung: Notes hat die Notiz in 'Packliste Paris' umbenannt (erste Zeile des "
                                            "Inhalts). Soll der alte Titel bleiben, ihn als erste Zeile in notiz.html "
                                            "setzen und mit replace 'Packliste Paris' erneut ersetzen."])
        self.assertIn(f'set body of theNote to t\n              return fname & "{T}" & (name of theNote)',
                      notes.skripte[1])
        datei.write_text("<h1>Packliste</h1>", encoding="utf-8")
        notes = Notes((0, f"Inbox{Z}", ""), (0, f"Inbox{T}packliste", ""))
        out, _fehler = self.lauf(notes, "replace", "Packliste", "--file", "notiz.html")
        self.assertEqual(out.strip(), "Ersetzt: Packliste in Inbox")  # nur andere Groß- und Kleinschreibung

    def test_ersetzen_in_geteiltem_ordner_erst_vorschau(self):
        """Zusatzrunde V6 Phase 6: Eigene Notizen ersetzt replace ohne Dialog, geteilte (Notiz oder Ordner, im Zweifel
        auch) nur mit --ausfuehren, das der Server erst nach dem Dialog von notiz_geteilt setzt."""
        datei = self.tmp / "notiz.md"
        datei.write_text("neu", encoding="utf-8")
        notes = Notes((0, f"Familie{Z}", ""), (0, f"GETEILT{T}Familie", ""))
        out, fehler = self.lauf(notes, "replace", "Plan", "--file", "notiz.md")
        self.assertIsNone(fehler)
        self.assertEqual(out.strip(), "Vorschau, nichts geändert: Plan liegt geteilt im Ordner Familie, andere sähen "
                                      "die Änderung sofort. Ersetzen mit notiz_geteilt und ersetzen, das zeigt einen "
                                      "Dialog am Mac.")
        self.assertTrue(datei.exists())  # bleibt für notiz_geteilt
        skript = notes.skripte[1]
        self.assertLess(skript.index("set teilt to my geteilt(fo)"), skript.index("set body of theNote to t"))
        self.assertIn("if (shared of theNote) is not false then set teilt to true", skript)
        self.assertLess(skript.index("end geteilt"), skript.rindex('tell application "Notes"'))
        notes = Notes((0, f"Familie{Z}", ""), (0, f"Familie{T}Plan", ""))
        out, fehler = self.lauf(notes, "--ausfuehren", "replace", "Plan", "--file", "notiz.md")
        self.assertIsNone(fehler)
        self.assertEqual(out.strip(), "Ersetzt: Plan in Familie")
        self.assertNotIn('return "GETEILT', notes.skripte[1])
        self.assertFalse(datei.exists())

    # --- Konfiguration, Aufruf, Notes selbst

    def test_kaputte_config_bricht_ab_statt_ausschluesse_zu_verlieren(self):
        for cfg, meldung in (("{kaputt", "kein gültiges JSON"), ({"notizen": []}, "notizen muss ein Objekt"),
                             ({"notizen": {"ausgeschlossene_ordner": "Privat"}}, "Liste von Ordnernamen")):
            self.config(cfg)
            notes = Notes()
            _out, fehler = self.lauf(notes, "folders")
            self.assertIn(meldung, fehler)
            self.assertEqual(notes.skripte, [])
        (self.tmp / "config.json").unlink()  # Review 20.10.2026: ohne Datei fehlen die Ausschlüsse, also Abbruch
        notes = Notes()
        _out, fehler = self.lauf(notes, "folders")
        self.assertIn("config.json fehlt", fehler)
        self.assertEqual(notes.skripte, [])

    def test_ausschluesse_normalisiert_und_unpassende_gezaehlt(self):
        """Review 21.10.2026: "Privat " mit Leerzeichen oder eine andere Unicode-Form ließ den Ordner still offen. Namen
        gehen in NFC und ohne Rand ins Skript, Leerzeichen zählen beim Vergleich nicht. folders nennt die Zahl der
        Einträge ohne passenden Ordner, keinen Namen, wie reminders.py lists."""
        self.config({"notizen": {"ausgeschlossene_ordner": [" Privat ", "Kündigung", "  "]}})
        notes = Notes((0, f"1{Z}Inbox{T}3{Z}", ""))
        out, fehler = self.lauf(notes, "folders")
        self.assertIsNone(fehler)
        self.assertEqual(out.splitlines(), ["ordner | notizen", "Inbox | 3", "Hinweis: 1 Einträge in config.json "
                                            "(ausgeschlossene_ordner) passen zu keinem Ordner."])
        skript = notes.skripte[0]
        self.assertIn('ignoring white space\n            if cname is "Privat" or cname is "Kündigung" or cname '
                      'is "Recently Deleted"', skript)
        self.assertIn('repeat with ausschluss in {"Privat", "Kündigung"}', skript)  # ohne Papierkorb und Leere
        self.assertNotIn("ü", skript)
        out, fehler = self.lauf(Notes((0, f"0{Z}", "")), "folders")
        self.assertEqual((out, fehler), ("Keine Ordner gefunden.\n", None))  # ohne Hinweis, wenn alle passen
        notes = Notes()
        out, fehler = self.lauf(notes, "list", "--folder", "Kündigung ")  # auch bei --folder
        self.assertEqual((out, fehler, notes.skripte), ("Keine Notizen gefunden.\n", None, []))

    def test_keine_abkuerzungen(self):
        for befehl in (("list", "--fol", "X"), ("add", "--tit", "X", "--file", "notiz.md"),
                       ("replace", "X", "--fi", "notiz.md"), ("add", "--title", "X", "--file", "notiz.md", "--aus"),
                       ("read", "X", "--htm")):
            _out, fehler = self.lauf(Notes(), *befehl)
            self.assertEqual(fehler, 2, befehl)

    def test_notes_wird_einmal_gestartet(self):
        notes = Notes((1, "", "execution error: -600"), (0, "", ""), (0, f"0{Z}Inbox{T}1{Z}", ""))
        out, fehler = self.lauf(notes, "folders")
        self.assertIsNone(fehler)
        self.assertEqual(notes.skripte[1], 'launch application "Notes"')
        self.assertIn("Inbox | 1", out)

    def test_sandbox_hinweis_bei_600(self):
        """Probe 21.10.2026: In der Sandbox scheitern beide Versuche mit -600. Die Meldung nennt den Aufruf mit
        absolutem Pfad statt nur den Fehler von Notes, in einer Zeile."""
        notes = Notes((1, "", "execution error: -600"), (0, "", ""), (1, "", "Connection invalid\n(-600)"))
        _out, fehler = self.lauf(notes, "folders")
        self.assertEqual(len(notes.skripte), 3)
        self.assertIn("Lief der Befehl in der Sandbox?", fehler)
        self.assertIn(f'python3 "{notiz.KIT / "notiz.py"}" <befehl>', fehler)
        self.assertNotIn("\n", fehler)

    def test_abgelehnte_automation_mit_klarer_meldung(self):
        _out, fehler = self.lauf(Notes((1, "", "Not authorized to send Apple events (-1743)")), "folders")
        self.assertIn("Automation", fehler)

    def test_meldungen_in_einer_zeile(self):
        """Prüfung 20.10.2026: Die Meldungen zu Automation und Fehlern von Notes liefen über zwei Zeilen."""
        _out, fehler = self.lauf(Notes((1, "", "Not authorized to send Apple events (-1743)")), "folders")
        self.assertEqual(fehler, "Notes hat die Steuerung abgelehnt. Einmalig erlauben unter Systemeinstellungen > "
                                 "Datenschutz & Sicherheit > Automation.")
        _out, fehler = self.lauf(Notes((1, "", "12:40: execution error:\nNotes got an error:\x1b[31m Can’t get "
                                                "folder.\n(-1728)\n")), "folders")
        self.assertEqual(fehler, "Notes meldet einen Fehler: 12:40: execution error: Notes got an error: Can’t get "
                                 "folder. (-1728)")

    def test_osascript_mit_zeitgrenze(self):
        """Prüfung 20.10.2026: osascript lief ohne Timeout und konnte hängen. Jetzt nach OSA_SEKUNDEN eine Zeile, unter
        den 120 s des Bash-Werkzeugs, damit die Meldung ankommt."""
        with mock.patch.object(notiz.subprocess, "run") as run:
            notiz._lauf("return 1")
        self.assertEqual(run.call_args.kwargs["timeout"], notiz.OSA_SEKUNDEN)
        self.assertLess(notiz.OSA_SEKUNDEN, 120)
        notes = Notes(subprocess.TimeoutExpired(["osascript", "-"], notiz.OSA_SEKUNDEN))
        _out, fehler = self.lauf(notes, "folders")
        self.assertEqual(fehler, f"Notes hat nach {notiz.OSA_SEKUNDEN} s nicht geantwortet, abgebrochen. Erneut "
                                 f"versuchen, nach add oder replace vorher in Notizen nachsehen, ob die Änderung schon "
                                 f"da ist.")
        # auch beim zweiten Versuch nach dem Start von Notes
        notes = Notes((1, "", "execution error: -600"), (0, "", ""),
                      subprocess.TimeoutExpired(["osascript", "-"], notiz.OSA_SEKUNDEN))
        _out, fehler = self.lauf(notes, "folders")
        self.assertIn("nicht geantwortet", fehler)
        self.assertEqual(len(notes.skripte), 3)


if __name__ == "__main__":
    unittest.main()
