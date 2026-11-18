"""Tests für notiz.py ohne Apple Notes: osascript ist durch einen Ersatz ersetzt, der jedes Skript mitschreibt und
vorbereitete Antworten liefert. Läuft in der Sandbox, berührt keine echte Notiz.

Aufruf im Kit-Ordner: python3 -B -m unittest discover tests
"""
import contextlib
import io
import json
import os
import re
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
STAND = "2026-11-18 10:00:00"
NEU = "2026-11-18 10:05:07"


def liste(*zeilen, fehl=0, abbruch=0, fehlordner="", konten="iCloud"):
    """Antwort von list und search: Kopf mit nicht lesbaren Notizen, Abbruch, nicht lesbaren Ordnern und Konten, dann
    je Treffer titel, ordner, stand."""
    return 0, f"{fehl}{T}{abbruch}{T}{fehlordner}{T}{konten}{Z}" + Z.join(T.join(z) for z in zeilen), ""


def eins(body, stand=STAND, anh="0", teilt="false", ordner="Inbox", laenge=None):
    """Antwort des ersten Skripts von replace und append."""
    laenge = len(body) if laenge is None else laenge
    return 0, T.join(["EINS", ordner, "x-coredata://A/ICNote/p1", stand, anh, teilt, str(laenge), body]), ""


def ok(klar, name="Plan", ordner="Inbox", stand=NEU):
    """Antwort des zweiten Skripts von replace und append: geschrieben, mit Titel, neuem Stand und Klartext."""
    return 0, T.join(["OK", ordner, name, stand, klar]), ""


def gelesen(text="Text", stand=STAND, teilt="false", anh="0", titel="Plan", ordner="Inbox"):
    return 0, T.join([titel, ordner, stand, teilt, anh, text]), ""


class Notes:
    """Ersatz für osascript: merkt sich jedes Skript und liefert die Antworten der Reihe nach (rc, stdout, stderr).
    Eine Ausnahme als Antwort wird geworfen, etwa subprocess.TimeoutExpired. Liest ein Skript eine Datei (read POSIX
    file), merkt es sich deren Inhalt in dateien: Das ist der Text, den Notes bekäme."""

    def __init__(self, *antworten):
        self.skripte, self.antworten, self.dateien = [], list(antworten), []

    def __call__(self, script):
        self.skripte.append(script)
        m = re.search(r'read POSIX file "([^"]+)"', script)
        if m:
            self.dateien.append(Path(m.group(1)).read_text(encoding="utf-8"))
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

    def datei(self, text, name="notiz.md"):
        pfad = self.tmp / name
        pfad.write_text(text, encoding="utf-8")
        return pfad

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
        Befehl, der Ordner auflistet, sucht, liest, anlegt, ersetzt oder ergänzt, fragt die ganze Kette, beim Ändern
        beide Skripte."""
        datei = self.datei("Text")
        laeufe = (
            (("folders",), Notes((0, f"0{Z}", ""))),
            (("list",), Notes(liste())),
            (("list", "--folder", "Steuern"), Notes(liste())),
            (("read", "Plan"), Notes((0, "NICHTGEFUNDEN", ""))),
            (("read", "Plan", "--folder", "Steuern"), Notes((0, "NICHTGEFUNDEN", ""))),
            (("search", "Plan"), Notes(liste())),
            (("search", "Plan", "--folder", "Steuern"), Notes(liste())),
            (("add", "--title", "X", "--file", "notiz.md", "--folder", "Steuern"), Notes((0, "NICHTFREI", ""))),
            (("add", "--title", "X", "--file", "notiz.md"), Notes((0, "NICHTFREI", ""))),
            (("append", "Plan", "--file", "notiz.md", "--stand", STAND, "--folder", "Steuern"),
             Notes(eins("<div>Plan</div>", ordner="Steuern"), ok("Plan Text", ordner="Steuern"))),
        )
        for befehl, notes in laeufe:
            self.lauf(notes, *befehl)
            self.assertTrue(notes.skripte, befehl)
            for skript in notes.skripte:
                with self.subTest(befehl=befehl):
                    self.kette_geprueft(skript)
            if "Steuern" in befehl:  # der Name allein reicht nicht, die Kette muss frei sein
                for skript in notes.skripte:
                    self.assertIn('fname is "Steuern" and my frei(fo)', skript, befehl)
            if befehl[0] == "add":  # ohne freien Ordner nichts angelegt, die Textdatei bleibt
                self.assertTrue(datei.exists(), befehl)
        self.assertEqual(len(laeufe[-1][1].skripte), 2)
        self.assertFalse(datei.exists())  # append hat sie nach Erfolg gelöscht

    def test_liste_mit_hinweis_daten_statt_anweisungen(self):
        out, _fehler = self.lauf(Notes(liste(("Plan", "Inbox", STAND))), "list", "--limit", "5")
        self.assertIn(notiz.HINWEIS, out)
        self.assertIn(f"Plan | Inbox | {STAND}", out)

    def test_steuerzeichen_in_notizen_werden_entfernt(self):
        """Prüfung 20.10.2026: Terminalfarben und Richtungszeichen aus Notizen landen nicht im Transkript."""
        out, _fehler = self.lauf(Notes(liste(("Rot\x1b[31m‮", "Inbox", STAND))), "list")
        self.assertIn(f"Rot | Inbox | {STAND}", out)
        self.assertNotIn("\x1b", out)
        out, _fehler = self.lauf(Notes(gelesen("Zeile 1\n\x1b[0mZeile 2\x07")), "read", "Plan")
        self.assertIn("Zeile 1\nZeile 2", out)
        self.assertNotIn("\x07", out)

    def test_ausgeschlossener_ordner_wird_nie_gefragt_und_nie_bestaetigt(self):
        """Ein ausgeschlossener --folder fragt Notes nie und meldet sich genau wie ein unbekannter (Review 21.10.2026:
        "ist ausgeschlossen" bestätigte den Ausschluss), auch klein geschrieben, mit Leerzeichen oder als Papierkorb."""
        self.datei("Text")
        faelle = ((("list", "--folder", "{}"), liste(konten="")),
                  (("search", "x", "--folder", "{}"), liste(konten="")),
                  (("read", "X", "--folder", "{}"), (0, "NICHTGEFUNDEN", "")),
                  (("add", "--title", "X", "--file", "notiz.md", "--folder", "{}"), (0, "NICHTFREI", "")),
                  (("replace", "X", "--file", "notiz.md", "--stand", STAND, "--folder", "{}"),
                   (0, "NICHTGEFUNDEN", "")),
                  (("append", "X", "--file", "notiz.md", "--stand", STAND, "--folder", "{}"),
                   (0, "NICHTGEFUNDEN", "")))
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
        _out, fehler = self.lauf(Notes((0, "kein Kopf", "")), "list")
        self.assertIn("unerwartete Antwort", fehler)

    def test_lesen_bei_dubletten_nennt_die_ordner(self):
        """Prüfung 20.10.2026: read nahm bei zwei Notizen mit gleichem Titel still die erste, jetzt wie replace Code 2
        mit den Ordnern und ohne Inhalt."""
        notes = Notes((0, f"MEHRDEUTIG{Z}Inbox{Z}Arbeit\x1b[31m", ""))
        out, fehler = self.lauf(notes, "read", "Plan")
        self.assertEqual(fehler, 2)
        self.assertEqual(out.strip(), "2 Notizen heißen 'Plan' (Ordner: Inbox, Arbeit). Nicht eindeutig, nichts "
                                      "gelesen. Mit --folder eingrenzen.")
        skript = notes.skripte[0]
        self.assertIn("set anzahl to anzahl + 1", skript)
        self.assertLess(skript.index(f'if anzahl > 1 then return "MEHRDEUTIG{Z}"'),
                        skript.index("(plaintext of erste)"))  # erst zählen, Inhalt nur bei genau einem Treffer
        out, fehler = self.lauf(Notes(gelesen(ordner="Arbeit")), "read", "Plan", "--folder", "Arbeit")
        self.assertIsNone(fehler)
        self.assertIn("Ordner:   Arbeit", out)

    def test_lesen_mit_obergrenze(self):
        """Prüfung 20.10.2026: read zeigte jede Länge. Jetzt höchstens LESE_MAX Zeichen mit Hinweis, alles mit
        --max-chars 0."""
        lang = "a" * (notiz.LESE_MAX + 5)
        out, fehler = self.lauf(Notes(gelesen(lang)), "read", "Plan")
        self.assertIsNone(fehler)
        self.assertTrue(out.endswith("a" * notiz.LESE_MAX + f"\n[gekürzt, {notiz.LESE_MAX + 5} Zeichen gesamt, alles "
                                                             f"mit --max-chars 0]\n"))
        self.assertNotIn("a" * (notiz.LESE_MAX + 1), out)
        out, fehler = self.lauf(Notes(gelesen(lang)), "read", "Plan", "--max-chars", "0")
        self.assertIsNone(fehler)
        self.assertTrue(out.endswith(lang + "\n"))
        out, _fehler = self.lauf(Notes(gelesen(lang)), "read", "Plan", "--max-chars", "10")
        self.assertIn("\n\naaaaaaaaaa\n[gekürzt, ", out)
        kurz = "b" * notiz.LESE_MAX  # genau an der Grenze bleibt alles
        out, _fehler = self.lauf(Notes(gelesen(kurz)), "read", "Plan")
        self.assertNotIn("gekürzt", out)

    def test_lesen_zeigt_stand_und_anhaenge(self):
        """Etappe 3 von v7.3.0: read zeigt den Stand (Änderungsdatum mit Sekunden aus dem Handler stempel), den replace
        und append verlangen, und Anhänge, an denen beide ablehnen."""
        notes = Notes(gelesen())
        out, fehler = self.lauf(notes, "read", "Plan")
        self.assertIsNone(fehler)
        self.assertEqual(out.splitlines()[:3], ["Titel:    Plan", "Ordner:   Inbox", f"Stand:    {STAND}"])
        self.assertNotIn("Anhänge", out)
        skript = notes.skripte[0]
        self.assertIn("my stempel(modification date of erste)", skript)
        self.assertIn("set anh to (count of attachments of erste) as text", skript)
        self.assertIn("set s to time of d", skript)
        out, _fehler = self.lauf(Notes(gelesen(anh="2")), "read", "Plan")
        self.assertIn("Anhänge:  2 (ersetzen und ergänzen lehnen ab)", out)
        out, _fehler = self.lauf(Notes(gelesen(anh="?")), "read", "Plan")
        self.assertIn("Anhänge:  nicht prüfbar", out)

    def test_suche_in_titel_und_inhalt(self):
        """O6 (Prüfung 20.10.2026): search ist der Hauptweg von Testprompt 76 und hatte keinen eigenen Test. Treffer mit
        Kopf und Datenhinweis, Suchtext sicher im Skript, nur freie Ordner, ohne Treffer eine Zeile."""
        notes = Notes(liste(("Packliste", "Inbox\x1b[31m", "2026-11-17 09:00:00"),
                            ("Paris Wochenende", "Reisen", "2026-11-18 08:00:00")))
        out, fehler = self.lauf(notes, "search", 'Paris "Sa"', "--limit", "5")
        self.assertIsNone(fehler)
        self.assertEqual(out.splitlines(), [f"titel | ordner | geändert  {notiz.HINWEIS}",
                                            "Paris Wochenende | Reisen | 2026-11-18 08:00:00",
                                            "Packliste | Inbox | 2026-11-17 09:00:00",
                                            "Durchsucht: Konten iCloud."])
        skript = notes.skripte[0]
        self.assertIn('if ((item i of namen) contains "Paris \\"Sa\\"") or ((item i of texte) contains '
                      '"Paris \\"Sa\\"") then', skript)
        self.kette_geprueft(skript)
        out, fehler = self.lauf(Notes(liste()), "search", "Gibt es nicht")
        self.assertIsNone(fehler)
        self.assertEqual(out.splitlines(), ["Keine Notiz enthält 'Gibt es nicht'.", "Durchsucht: Konten iCloud."])

    def test_suche_mit_ordner(self):
        """Etappe 3 von v7.3.0: search grenzt mit --folder auf einen Ordner ein. Ohne Treffer kann der Ordner auch
        fehlen, die Zeile sagt das. Die Konten nennt sie dann nicht."""
        notes = Notes(liste())
        out, fehler = self.lauf(notes, "search", "Zelt", "--folder", "Reisen")
        self.assertIsNone(fehler)
        self.assertEqual(out.strip(), "Keine Notiz enthält 'Zelt': Ordner Reisen ist leer, unbekannt oder "
                                      "ausgeschlossen, oder ohne Treffer.")
        self.assertIn('fname is "Reisen" and my frei(fo)', notes.skripte[0])

    def test_alles_je_ordner_in_einem_zug(self):
        """Etappe 3 von v7.3.0: list, search und die Suche nach dem Titel fragten Notes je Notiz (name of theNote).
        Jetzt je Ordner eine Liste je Eigenschaft, verglichen wird im Skript. Notiz für Notiz nur, wenn der Zug
        scheitert, dann mit try je Notiz. Jedes Skript läuft mit with timeout."""
        self.datei("Text")
        laeufe = ((("list",), Notes(liste()), ("name", "modification date")),
                  (("search", "x"), Notes(liste()), ("name", "modification date", "plaintext")),
                  (("read", "Plan"), Notes(gelesen()), ("name", "id")),
                  (("replace", "Plan", "--file", "notiz.md", "--stand", STAND), Notes(eins("<div>Plan</div>")),
                   ("name", "id")))
        for befehl, notes, eigenschaften in laeufe:
            self.lauf(notes, *befehl)
            skript = notes.skripte[0]
            with self.subTest(befehl=befehl[0]):
                for e in eigenschaften:
                    self.assertRegex(skript, rf"set \w+ to {e} of notes of fo\n")
                self.assertNotIn("of theNote", skript)
                self.assertIn("repeat with n in liste", skript)  # Notiz für Notiz nur im Ersatzweg
                self.assertLess(skript.index("set ok to false"), skript.index("repeat with n in liste"))
                self.assertIn("set fehlNotizen to fehlNotizen + 1", skript)
                self.assertIn(f"with timeout of {notiz.AS_SEKUNDEN} seconds", skript)
        for befehl, notes in ((("folders",), Notes((0, f"0{Z}", ""))),
                              (("add", "--title", "X", "--file", "notiz.md"), Notes((0, "NICHTFREI", "")))):
            self.lauf(notes, *befehl)
            self.assertIn(f"with timeout of {notiz.AS_SEKUNDEN} seconds", notes.skripte[0], befehl)
        skript = Notes(liste())
        self.lauf(skript, "search", "x")
        self.assertIn(f"if ((my jetzt()) - beginn) > {notiz.SUCH_SEKUNDEN} then", skript.skripte[0])
        self.assertIn("set konten to name of every account", skript.skripte[0])

    def test_uebersprungenes_abbruch_und_konten_nennen(self):
        """Etappe 2 und 3 von v7.3.0: Was nicht lesbar war, bricht die Suche nicht mehr ab, die Ausgabe nennt es. Ein
        Abbruch nach SUCH_SEKUNDEN sagt, dass nicht alles durchsucht ist. Ohne --folder steht da, welche Konten Notes
        kennt, ein deaktiviertes fehlt so sichtbar."""
        antwort = liste(("Plan", "Inbox", STAND), fehl=2, abbruch=1, fehlordner="Alt", konten="iCloud, Auf meinem Mac")
        out, fehler = self.lauf(Notes(antwort), "search", "Plan")
        self.assertIsNone(fehler)
        self.assertEqual(out.splitlines()[2:], [
            f"Abgebrochen nach {notiz.SUCH_SEKUNDEN} s: Nicht alle Ordner durchsucht, es kann weitere Treffer geben. "
            "Mit Ordner eingrenzen.",
            "2 Notizen nicht lesbar (etwa gesperrt), Ordner Alt nicht lesbar, übersprungen.",
            "Durchsucht: Konten iCloud, Auf meinem Mac."])
        out, _fehler = self.lauf(Notes(liste(konten="")), "list")
        self.assertEqual(out.splitlines(), ["Keine Notizen gefunden.", "Nichts durchsucht: Notes zeigt kein Konto."])
        out, _fehler = self.lauf(Notes(liste(("Plan", "Inbox", STAND))), "list", "--folder", "Inbox")
        self.assertNotIn("Durchsucht", out)
        _out, fehler = self.lauf(Notes((0, f"NICHTGEFUNDEN{T}1{T}Alt", "")), "read", "Plan")
        self.assertEqual(fehler, "Keine Notiz mit dem Titel 'Plan' gefunden. 1 Notizen nicht lesbar (etwa gesperrt), "
                                 "Ordner Alt nicht lesbar, übersprungen.")

    def test_neueste_zuerst_und_grenze_nach_dem_sortieren(self):
        """Etappe 3 von v7.3.0: list zeigt die neuesten über alle Ordner (vorher die ersten in Ordnerfolge), die Grenze
        gilt nach dem Sortieren und nennt, wie viele weitere es gibt. --limit unter 1 fragt Notes nicht (Code 2)."""
        antwort = liste(("Alt", "A", "2026-01-01 10:00:00"), ("Neu", "B", "2026-11-18 10:00:00"),
                        ("Mitte", "A", "2026-06-01 10:00:00"))
        out, fehler = self.lauf(Notes(antwort), "list", "--limit", "2")
        self.assertIsNone(fehler)
        self.assertEqual(out.splitlines()[1:4], ["Neu | B | 2026-11-18 10:00:00", "Mitte | A | 2026-06-01 10:00:00",
                                                 "1 weitere, mehr mit --limit."])
        for befehl in (("list", "--limit", "0"), ("search", "Plan", "--limit", "-1"), ("read", "Plan", "--max-chars",
                                                                                         "-1")):
            notes = Notes()
            _out, fehler = self.lauf(notes, *befehl)
            self.assertEqual(fehler, 2, befehl)
            self.assertEqual(notes.skripte, [])

    def test_nummern_in_titeln_bei_list_und_search_maskiert(self):
        """Review 21.10.2026: Titel mit Konto- oder Telefonnummern standen bei list und search im Klartext. read zeigt
        den Titel vollständig."""
        antwort = liste(("Konto DE36 5900 0000 0059 0010 54", "Inbox", STAND), ("Tel 0176 1234 5678", "Inbox", STAND))
        for befehl in (("list",), ("search", "Konto")):
            out, fehler = self.lauf(Notes(antwort), *befehl)
            self.assertIsNone(fehler)
            self.assertIn(f"Konto [Nummer] | Inbox | {STAND}", out, befehl)
            self.assertIn(f"Tel [Nummer] | Inbox | {STAND}", out, befehl)
            self.assertNotIn("5900", out)
        out, _fehler = self.lauf(Notes(gelesen(titel="Tel 0176 1234 5678")), "read", "Tel 0176 1234 5678")
        self.assertIn("Titel:    Tel 0176 1234 5678", out)

    def test_lesen_nennt_geteilte_notizen(self):
        """Review 21.10.2026: read nennt geteilte Notizen und Ordner, damit vor replace klar ist, dass andere die
        Änderung sehen. Ist shared nicht lesbar oder die Antwort unklar, gilt die Notiz als geteilt."""
        out, _fehler = self.lauf(Notes(gelesen(teilt="true", ordner="Familie")), "read", "Plan")
        self.assertIn(f"Stand:    {STAND}\nGeteilt:  ja\n", out)
        out, _fehler = self.lauf(Notes(gelesen(teilt="")), "read", "Plan")
        self.assertIn("Geteilt:  ja", out)
        notes = Notes(gelesen())
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
        notes = Notes(gelesen(html_text))
        out, fehler = self.lauf(notes, "read", "Plan", "--html")
        self.assertIsNone(fehler)
        self.assertTrue(out.endswith(f"\n\n{html_text}\n"))
        self.assertIn("(body of erste)", notes.skripte[0])
        self.assertNotIn("plaintext", notes.skripte[0])
        notes = Notes(gelesen("Plan"))
        self.lauf(notes, "read", "Plan")
        self.assertIn("(plaintext of erste)", notes.skripte[0])

    def test_gefundene_notiz_ueber_die_id(self):
        """Etappe 3 von v7.3.0: Die gefundene Notiz hält das Skript über ihre ID. note i of fo zeigte nach einer Änderung
        im Ordner (Notes sortiert nach Datum) auf eine andere Notiz."""
        notes = Notes(gelesen())
        self.lauf(notes, "read", "Plan")
        self.assertIn("set erste to note id (item i of ids)", notes.skripte[0])
        self.assertNotRegex(notes.skripte[0], r"note i of")

    # --- anlegen und ersetzen nur aus der festen Datei

    def test_anlegen_aus_notiz_html_im_kit_auch_ohne_cd(self):
        self.datei("<table><tr><td>Tag</td></tr></table>", "notiz.html")
        notes = Notes((0, f"Reiseplan{T}Notizen{T}false{T}{NEU}{T}Reiseplan\nTag", ""))
        out, fehler = self.lauf(notes, "add", "--title", "Reiseplan", "--file", "notiz.html")
        self.assertIsNone(fehler)
        self.assertEqual(out.splitlines(), ["Angelegt: Reiseplan in Notizen", f"Stand:    {NEU}"])  # echter Ordnername
        self.assertIn('make new note at ziel with properties {name:"Reiseplan"', notes.skripte[0])
        self.assertIn("my stempel(modification date of n)", notes.skripte[0])
        self.assertIn("(plaintext of n)", notes.skripte[0])
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
            self.datei(text, datei)
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
        datei = self.datei("Text")
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
        text = "Zelt\nSchlafsack"
        datei = self.datei(text)
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
            for befehl in (("add", "--title", "X", "--file", "notiz.html"),
                           ("replace", "X", "--file", "notiz.html", "--stand", STAND),
                           ("append", "X", "--file", "notiz.html", "--stand", STAND)):
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
        self.datei("Siehe file:///etc/hosts und url(http://x)")
        self.assertIn("file:///etc/hosts", notiz.datei_als_html(notiz.text_datei("notiz.md")))  # Markdown lädt nichts
        self.datei('<div><img src="https://example.com/a.png"></div>')
        _out, fehler = self.lauf(notes, "add", "--title", "X", "--file", "notiz.md")  # Markdown, das als HTML durchgeht
        self.assertIn("notiz.md verweist auf eine lokale Datei", fehler)
        start = time.monotonic()
        self.assertFalse(notiz.fremdquelle("<a " * 100_000))  # mit <[^>]* brauchten 60 KB schon 26 s
        self.assertLess(time.monotonic() - start, 2)

    def test_html_bleibt_markdown_wird_schlichtes_html(self):
        self.datei("<table><tr><td>A</td></tr></table>", "notiz.html")
        self.assertEqual(notiz.datei_als_html(notiz.text_datei("notiz.html")), "<table><tr><td>A</td></tr></table>")
        self.datei("# Titel\n- Punkt & mehr\n- -20 °C morgens\n## #Hashtag\n")
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
            for befehl in (("add", "--title", "X", "--file", angabe),
                           ("append", "X", "--file", angabe, "--stand", STAND)):
                _out, fehler = self.lauf(notes, *befehl)
                self.assertIn("Text nur aus notiz.html oder notiz.md", fehler, befehl)
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
        datei = self.datei("neu")
        zwei = Notes((0, f"MEHRDEUTIG{Z}Inbox{Z}Arbeit", ""))
        out, fehler = self.lauf(zwei, "replace", "Plan", "--file", "notiz.md", "--stand", STAND)
        self.assertEqual(fehler, 2)
        self.assertIn("2 Notizen heißen 'Plan' (Ordner: Inbox, Arbeit). Nicht eindeutig, nichts geändert", out)
        self.assertEqual(len(zwei.skripte), 1)  # nur gesucht, nichts geschrieben
        self.assertNotIn("set body", zwei.skripte[0])
        _out, fehler = self.lauf(Notes((0, "NICHTGEFUNDEN", "")), "replace", "Plan", "--file", "notiz.md", "--stand",
                                 STAND)
        self.assertEqual(fehler, "Keine Notiz mit dem Titel 'Plan' gefunden. Nichts geändert.")
        self.assertTrue(datei.exists())
        eins_ = Notes(eins("<div>Plan</div><div>alt</div>"), ok("neu"))
        out, fehler = self.lauf(eins_, "replace", "Plan", "--file", "notiz.md", "--stand", STAND, "--folder", "Inbox")
        self.assertIsNone(fehler)
        self.assertEqual(out.splitlines()[:2], ["Ersetzt: Plan in Inbox", f"Stand:    {NEU}"])
        self.assertIn("set body of n to t", eins_.skripte[1])
        self.assertIn('fname is "Inbox"', eins_.skripte[0])
        self.assertFalse(datei.exists())

    def test_ersetzen_meldet_neuen_titel(self):
        """Review 21.10.2026: set body benennt die Notiz nach der ersten Zeile um, ohne dass es jemand merkte. replace
        gibt den neuen Namen zurück und nennt ihn, wenn er vom alten Titel abweicht."""
        self.datei("<h1>Packliste Paris</h1>", "notiz.html")
        notes = Notes(eins("<div>Packliste</div>"), ok("Packliste Paris", name="Packliste Paris"))
        out, fehler = self.lauf(notes, "replace", "Packliste", "--file", "notiz.html", "--stand", STAND)
        self.assertIsNone(fehler)
        self.assertEqual(out.splitlines(), ["Ersetzt: Packliste in Inbox", f"Stand:    {NEU}",
                                            "Achtung: Notes hat die Notiz in 'Packliste Paris' umbenannt (erste Zeile des "
                                            "Inhalts). Soll der alte Titel bleiben, ihn als erste Zeile in notiz.html "
                                            "setzen und mit replace 'Packliste Paris' erneut ersetzen."])
        self.assertIn(f'set body of n to t\n      return "OK{T}" & fname & "{T}" & (name of n)', notes.skripte[1])
        self.datei("<h1>Packliste</h1>", "notiz.html")
        notes = Notes(eins("<div>Packliste</div>"), ok("Packliste", name="packliste"))
        out, _fehler = self.lauf(notes, "replace", "Packliste", "--file", "notiz.html", "--stand", STAND)
        self.assertEqual(out.splitlines(), ["Ersetzt: Packliste in Inbox", f"Stand:    {NEU}"])  # nur Groß und Klein

    def test_ersetzen_in_geteiltem_ordner_erst_vorschau(self):
        """Zusatzrunde V6 Phase 6: Eigene Notizen ersetzt replace ohne Dialog, geteilte (Notiz oder Ordner, im Zweifel
        auch) nur mit --ausfuehren, das der Server erst nach dem Dialog von notiz_geteilt setzt. Die Vorschau kommt
        erst, wenn Stand, Anhänge und Links passen: Der Dialog soll nicht umsonst kommen."""
        datei = self.datei("neu")
        notes = Notes(eins("<div>Plan</div>", teilt="true", ordner="Familie"))
        out, fehler = self.lauf(notes, "replace", "Plan", "--file", "notiz.md", "--stand", STAND)
        self.assertIsNone(fehler)
        self.assertEqual(out.strip(), "Vorschau, nichts geändert: Plan liegt geteilt im Ordner Familie, andere sähen "
                                      "die Änderung sofort. Weiter mit notiz_geteilt mit ersetzen, das zeigt einen "
                                      "Dialog am Mac.")
        self.assertEqual(len(notes.skripte), 1)  # nichts geschrieben
        self.assertTrue(datei.exists())  # bleibt für notiz_geteilt
        skript = notes.skripte[0]
        self.assertIn("set teilt to my geteilt(ersterFo)", skript)
        self.assertIn("if (shared of erste) is not false then set teilt to true", skript)
        self.assertLess(skript.index("end geteilt"), skript.rindex('tell application "Notes"'))
        _out, fehler = self.lauf(Notes(eins("<div>Plan</div>", teilt="true", stand=NEU)), "replace", "Plan", "--file",
                                 "notiz.md", "--stand", STAND)
        self.assertIn("hat sich seit dem Lesen geändert", fehler)  # Stand vor der Vorschau
        notes = Notes(eins("<div>Plan</div>", teilt="true", ordner="Familie"), ok("neu", name="neu", ordner="Familie"))
        out, fehler = self.lauf(notes, "--ausfuehren", "replace", "Plan", "--file", "notiz.md", "--stand", STAND)
        self.assertIsNone(fehler)
        self.assertTrue(out.startswith("Ersetzt: Plan in Familie\n"))
        self.assertNotIn('return "GETEILT', notes.skripte[1])
        self.assertFalse(datei.exists())
        # ohne --ausfuehren prüft auch das schreibende Skript die Teilung noch einmal
        self.datei("neu")
        notes = Notes(eins("<div>Plan</div>"), (0, f"GETEILT{T}Familie", ""))
        out, _fehler = self.lauf(notes, "replace", "Plan", "--file", "notiz.md", "--stand", STAND)
        self.assertIn("Vorschau, nichts geändert", out)
        self.assertLess(notes.skripte[1].index("set teilt to my geteilt(fo)"), notes.skripte[1].index("set body"))

    # --- Schutz beim Ändern (Etappe 3 von v7.3.0)

    def test_stand_ist_pflicht_und_wird_verglichen(self):
        """Vorbild expectedContentHash in apple-notes-mcp: replace und append schreiben nur, wenn die Notiz noch den
        Stand hat, den read gezeigt hat. Das prüft das erste Skript und im schreibenden noch einmal Stand und Länge des
        HTML, direkt vor set body."""
        datei = self.datei("neu")
        for befehl in ("replace", "append"):
            notes = Notes()
            _out, fehler = self.lauf(notes, befehl, "Plan", "--file", "notiz.md")
            self.assertEqual(fehler, 2, befehl)  # argparse: --stand fehlt
            for falsch in ("Montag", "2026-11-18", "18.11.2026 10:00:00"):
                _out, fehler = self.lauf(notes, befehl, "Plan", "--file", "notiz.md", "--stand", falsch)
                self.assertEqual(fehler, 2, falsch)
            self.assertEqual(notes.skripte, [])
            notes = Notes(eins("<div>Plan</div>", stand=NEU))
            _out, fehler = self.lauf(notes, befehl, "Plan", "--file", "notiz.md", "--stand", STAND)
            self.assertEqual(fehler, f"'Plan' hat sich seit dem Lesen geändert (Stand jetzt {NEU}, gelesen {STAND}). "
                                     "Nichts geändert. Erst notiz_lesen, dann mit der neuen Fassung und dem neuen Stand "
                                     "erneut.")
            self.assertEqual(len(notes.skripte), 1)
            notes = Notes(eins("<div>Plan</div>"), (0, f"STAND{T}{NEU}", ""))
            _out, fehler = self.lauf(notes, befehl, "Plan", "--file", "notiz.md", "--stand", STAND)
            self.assertEqual(fehler, f"'Plan' hat sich gerade geändert (Stand jetzt {NEU}). Nichts geändert. Erst "
                                     "notiz_lesen, dann erneut.")
            skript = notes.skripte[1]
            self.assertIn(f'if standJetzt is not "{STAND}" or (count of (body of n)) is not 15 then return "STAND',
                          skript)
            self.assertLess(skript.index("if standJetzt is not"), skript.index("set body of n to t"))
            self.assertIn('if ids contains "x-coredata://A/ICNote/p1" then\n            set n to note id '
                          '"x-coredata://A/ICNote/p1"', skript)
            self.assertTrue(datei.exists())
        # zusätzlicher Leerraum aus dem Chat stört nicht
        notes = Notes(eins("<div>Plan</div>"), ok("Plan neu"))
        _out, fehler = self.lauf(notes, "append", "Plan", "--file", "notiz.md", "--stand", f" {STAND.replace(' ', '  ')}")
        self.assertIsNone(fehler)

    def test_anhaenge_verhindern_ersetzen_und_ergaenzen(self):
        """Notes verliert Anhänge, wenn der Body neu geschrieben wird, auch beim Anfügen. Ist die Zahl nicht lesbar,
        gilt dasselbe. Geprüft im ersten und im schreibenden Skript."""
        datei = self.datei("neu")
        for befehl in ("replace", "append"):
            for anh, wie in (("2", "2 Anhänge"), ("?", "möglicherweise Anhänge (nicht prüfbar)")):
                notes = Notes(eins("<div>Plan</div>", anh=anh))
                _out, fehler = self.lauf(notes, befehl, "Plan", "--file", "notiz.md", "--stand", STAND)
                self.assertEqual(fehler, f"Die Notiz hat {wie} (Bilder, Dateien, Zeichnungen oder Scans). Notes "
                                         "verliert sie, wenn der Inhalt neu geschrieben wird, auch beim Ergänzen. Nichts "
                                         "geändert, die Änderung macht der Nutzer selbst in Notizen.")
                self.assertEqual(len(notes.skripte), 1)
            notes = Notes(eins("<div>Plan</div>"), (0, f"ANHAENGE{T}1", ""))
            _out, fehler = self.lauf(notes, befehl, "Plan", "--file", "notiz.md", "--stand", STAND)
            self.assertIn("Die Notiz hat 1 Anhänge", fehler)
            self.assertLess(notes.skripte[1].index('if anh is not "0" then return "ANHAENGE'),
                            notes.skripte[1].index("set body of n to t"))
        self.assertTrue(datei.exists())

    def test_ersetzen_ohne_links_der_alten_fassung_nur_mit_schalter(self):
        """Ein Link, der in der neuen Fassung fehlt, ging still verloren (etwa Markdown statt HTML aus read --html).
        replace lehnt ab und nennt bis zu drei, mit --links-entfernen geht es."""
        alt = ('<div>Plan</div><a href="https://a.example/x?y=1&amp;z=2">A</a><a href=\'https://b.example\'>B</a>'
               '<a href=https://c.example>C</a><a href="https://d.example">D</a>')
        self.datei("<div>Plan</div><a href='https://b.example'>B</a>", "notiz.html")
        notes = Notes(eins(alt))
        _out, fehler = self.lauf(notes, "replace", "Plan", "--file", "notiz.html", "--stand", STAND)
        self.assertEqual(fehler, "Die neue Fassung lässt 3 Links der Notiz weg (https://a.example/x?y=1&z=2, "
                                 "https://c.example, https://d.example). Nichts geändert. Links aus notiz_lesen mit html "
                                 "übernehmen, oder nur auf Wunsch des Nutzers mit links_entfernen.")
        self.assertEqual(len(notes.skripte), 1)
        notes = Notes(eins(alt), ok("Plan B"))
        out, fehler = self.lauf(notes, "replace", "Plan", "--file", "notiz.html", "--stand", STAND, "--links-entfernen")
        self.assertIsNone(fehler)
        self.assertTrue(out.startswith("Ersetzt: Plan in Inbox"))
        self.datei(alt.replace("&amp;", "&"), "notiz.html")  # dieselben Links, anders geschrieben
        out, fehler = self.lauf(Notes(eins(alt), ok("Plan A B C D")), "replace", "Plan", "--file", "notiz.html",
                                "--stand", STAND)
        self.assertIsNone(fehler)
        self.assertEqual(notiz.links('<a href="">x</a><a class="href=" title=y>'), set())

    def test_nachkontrolle(self):
        """Nach add, replace und append liest das Skript den Klartext zurück. Weichen die Wörter vom geschriebenen Text
        ab, sagt eine Zeile das statt nur Ersetzt. Leerraum, Striche, Entities und Groß- und Kleinschreibung zählen
        nicht, bei add darf der Titel davor stehen."""
        self.datei("# Plan\n- Zelt &amp; Kocher\n- -20 °C", "notiz.md")
        notes = Notes(eins("<div>Plan</div>"), ok("PLAN\n• Zelt &amp; Kocher\n• -20 °C"))
        out, fehler = self.lauf(notes, "replace", "Plan", "--file", "notiz.md", "--stand", STAND)
        self.assertIsNone(fehler)
        self.assertNotIn("Nachkontrolle", out)
        self.datei("# Plan\n- Zelt")
        notes = Notes(eins("<div>Plan</div>"), ok("Plan"))
        out, _fehler = self.lauf(notes, "replace", "Plan", "--file", "notiz.md", "--stand", STAND)
        self.assertIn("Nachkontrolle: Notes zeigt nicht genau den geschriebenen Text (2 Wörter geschrieben, 1 in Notes, "
                      "ab Wort 2 erwartet 'zelt', in Notes '(Ende)'). Mit notiz_lesen prüfen.", out)
        self.assertIn('& "{T}" & (plaintext of n)'.format(T=T), notes.skripte[1])
        self.datei("Zelt")
        out, _fehler = self.lauf(Notes((0, f"Packliste{T}Notizen{T}false{T}{NEU}{T}Packliste\nZelt", "")), "add",
                                 "--title", "Packliste", "--file", "notiz.md")
        self.assertNotIn("Nachkontrolle", out)  # Titel als eigene Zeile davor
        self.datei("Zelt")
        out, _fehler = self.lauf(Notes((0, f"Packliste{T}Notizen{T}false{T}{NEU}{T}Packliste", "")), "add",
                                 "--title", "Packliste", "--file", "notiz.md")
        self.assertIn("Nachkontrolle", out)
        self.assertEqual(notiz.woerter(notiz.klartext("<html><head><style>p{x:1}</style><title>K</title></head><body>"
                                                      "<p>Gr&uuml;&szlig;e</p><td>A</td><td>B</td></body></html>")),
                         ["grüsse", "a", "b"])  # casefold macht aus ß ss, auf beiden Seiten gleich

    # --- ergänzen

    def test_ergaenzt_unten_und_oben(self):
        self.assertEqual(notiz.ergaenzt("<div>Plan</div><div>alt</div>", "<div>neu</div>", "unten"),
                         "<div>Plan</div><div>alt</div><div>neu</div>")
        self.assertEqual(notiz.ergaenzt("<html><body><div>A</div></body></html>", "<html><body><div>neu</div>"
                                        "</body></html>", "unten"),
                         "<html><body><div>A</div><div>neu</div></body></html>")
        self.assertEqual(notiz.ergaenzt("<div><h1>Plan</h1></div>\n<div>alt</div>", "<div>neu</div>", "oben"),
                         "<div><h1>Plan</h1></div><div>neu</div>\n<div>alt</div>")
        self.assertEqual(notiz.ergaenzt("<div><b>Plan</b><br></div><div>alt</div>", "<div>neu</div>", "oben"),
                         "<div><b>Plan</b><br></div><div>neu</div><div>alt</div>")
        self.assertEqual(notiz.ergaenzt("<div><br></div><div>Plan</div><div>alt</div>", "<div>neu</div>", "oben"),
                         "<div><br></div><div>Plan</div><div>neu</div><div>alt</div>")  # leere Zeile vorn zählt nicht
        self.assertEqual(notiz.ergaenzt("<html><body>Plan</body></html>", "<div>neu</div>", "oben"),
                         "<html><body>Plan<div>neu</div></body></html>")  # ohne Zeilenende ans Ende
        self.assertEqual(notiz.koerper("<!DOCTYPE html><html><head><title>x</title></head><div>a</div></html>"),
                         "<div>a</div>")

    def test_ergaenzen_liest_selbst_und_schreibt_das_ganze(self):
        """notiz_ergaenzen: Claude gibt nur den neuen Teil, notiz.py holt das HTML, setzt an und schreibt das Ganze.
        Der Rest bleibt Zeichen für Zeichen, Links prüft append nicht (die alten bleiben), der Titel bleibt."""
        alt = '<div><h1>Plan</h1></div><div><a href="https://a.example">Ort</a></div>'
        datei = self.datei("- Zelt")
        notes = Notes(eins(alt), ok("Plan\nOrt\n• Zelt"))
        out, fehler = self.lauf(notes, "append", "Plan", "--file", "notiz.md", "--stand", STAND)
        self.assertIsNone(fehler)
        self.assertEqual(out.splitlines(), ["Ergänzt: Plan in Inbox", f"Stand:    {NEU}"])
        self.assertEqual(notes.dateien, [alt + "<div>&bull; Zelt</div>"])
        self.assertFalse(datei.exists())
        self.assertIn("set b to body of erste", notes.skripte[0])
        self.datei("<div>Heute</div>", "notiz.html")
        notes = Notes(eins(alt), ok("Plan\nHeute\nOrt"))
        out, fehler = self.lauf(notes, "append", "Plan", "--file", "notiz.html", "--stand", STAND, "--wo", "oben")
        self.assertIsNone(fehler)
        self.assertEqual(notes.dateien, ['<div><h1>Plan</h1></div><div>Heute</div><div><a href="https://a.example">'
                                         'Ort</a></div>'])
        self.assertNotIn("Nachkontrolle", out)
        _out, fehler = self.lauf(Notes(), "append", "Plan", "--file", "notiz.html", "--stand", STAND, "--wo", "mitte")
        self.assertEqual(fehler, 2)

    def test_ergaenzen_in_geteiltem_ordner_erst_vorschau(self):
        datei = self.datei("Zelt")
        notes = Notes(eins("<div>Plan</div>", teilt="true", ordner="Familie"))
        out, fehler = self.lauf(notes, "append", "Plan", "--file", "notiz.md", "--stand", STAND)
        self.assertIsNone(fehler)
        self.assertEqual(out.strip(), "Vorschau, nichts geändert: Plan liegt geteilt im Ordner Familie, andere sähen "
                                      "die Ergänzung sofort. Weiter mit notiz_geteilt mit ergaenzen, das zeigt einen "
                                      "Dialog am Mac.")
        self.assertTrue(datei.exists())
        notes = Notes(eins("<div>Plan</div>", teilt="true", ordner="Familie"), ok("Plan Zelt", ordner="Familie"))
        out, fehler = self.lauf(notes, "--ausfuehren", "append", "Plan", "--file", "notiz.md", "--stand", STAND)
        self.assertIsNone(fehler)
        self.assertTrue(out.startswith("Ergänzt: Plan in Familie"))
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
        self.config({"notizen": {"ausgeschlossene_ordner": [" Privat ", "Kündigung", "  "]}})  # zerlegt (NFD)
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
        out, fehler = self.lauf(notes, "list", "--folder", "Kündigung")  # auch bei --folder
        leer = "Keine Notizen gefunden: Ordner Kündigung ist leer, unbekannt oder ausgeschlossen. Freie Ordner zeigt folders.\n"
        self.assertEqual((out, fehler, notes.skripte), (leer, None, []))
        # Etappe 2 von v7.3.0: Ein unbekannter Ordner meldet sich gleich, statt wie ein leerer auszusehen
        out, fehler = self.lauf(Notes(liste()), "list", "--folder", "Kündigung")
        self.assertEqual((out, fehler), (leer, None))

    def test_keine_abkuerzungen(self):
        for befehl in (("list", "--fol", "X"), ("add", "--tit", "X", "--file", "notiz.md"),
                       ("replace", "X", "--fi", "notiz.md", "--stand", STAND),
                       ("replace", "X", "--file", "notiz.md", "--sta", STAND),
                       ("append", "X", "--file", "notiz.md", "--stand", STAND, "--links-entfernen"),
                       ("add", "--title", "X", "--file", "notiz.md", "--aus"), ("read", "X", "--htm")):
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
        den 120 s des Bash-Werkzeugs, damit die Meldung ankommt. Das with timeout im Skript (-1712) endet ebenso."""
        with mock.patch.object(notiz.subprocess, "run") as run:
            notiz._lauf("return 1")
        self.assertEqual(run.call_args.kwargs["timeout"], notiz.OSA_SEKUNDEN)
        self.assertLess(notiz.OSA_SEKUNDEN, 120)
        self.assertLess(notiz.SUCH_SEKUNDEN, notiz.AS_SEKUNDEN)
        self.assertLess(notiz.AS_SEKUNDEN, notiz.OSA_SEKUNDEN)
        notes = Notes(subprocess.TimeoutExpired(["osascript", "-"], notiz.OSA_SEKUNDEN))
        _out, fehler = self.lauf(notes, "folders")
        self.assertEqual(fehler, f"Notes hat nach {notiz.OSA_SEKUNDEN} s nicht geantwortet, abgebrochen. Erneut "
                                 f"versuchen, nach add, replace oder append vorher in Notizen nachsehen, ob die Änderung "
                                 f"schon da ist.")
        # auch beim zweiten Versuch nach dem Start von Notes
        notes = Notes((1, "", "execution error: -600"), (0, "", ""),
                      subprocess.TimeoutExpired(["osascript", "-"], notiz.OSA_SEKUNDEN))
        _out, fehler = self.lauf(notes, "folders")
        self.assertIn("nicht geantwortet", fehler)
        self.assertEqual(len(notes.skripte), 3)
        _out, fehler = self.lauf(Notes((1, "", "execution error: Notes got an error: AppleEvent timed out. (-1712)")),
                                 "search", "x")
        self.assertTrue(fehler.startswith(f"Notes hat nach {notiz.AS_SEKUNDEN} s nicht geantwortet, abgebrochen."))


def alle_skripte(tmp: Path) -> list:
    """Jedes AppleScript, das notiz.py baut, mit Ersatzantworten erzeugt."""
    (tmp / "config.json").write_text(json.dumps({"notizen": {"ausgeschlossene_ordner": ["Privat"]}}), encoding="utf-8")
    notes = Notes((0, f"0{Z}", ""), liste(), liste(), (0, "NICHTGEFUNDEN", ""), (0, "", ""), eins("<div>P</div>"),
                  ok("x"), eins("<div>P</div>"), ok("x"))
    laeufe = (("folders",), ("list",), ("search", "x", "--folder", "A"), ("read", "x"),
              ("add", "--title", "x", "--file", "notiz.md", "--folder", "A"),
              ("replace", "x", "--file", "notiz.md", "--stand", STAND),
              ("--ausfuehren", "append", "x", "--file", "notiz.md", "--stand", STAND, "--wo", "oben"))
    with mock.patch.object(notiz, "KIT", tmp), mock.patch.object(notiz, "_lauf", notes), \
            contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        for befehl in laeufe:
            (tmp / "notiz.md").write_text("Text", encoding="utf-8")
            try:
                notiz.main(list(befehl))
            except SystemExit:
                pass
    return notes.skripte


@unittest.skipUnless(shutil.which("osacompile"), "osacompile fehlt (kein macOS)")
class AppleScriptSyntax(unittest.TestCase):
    """Alle AppleScripts von notiz.py kompilieren (nur Syntax, osacompile startet Notes nicht). Die Standard-Zusätze
    (current date, read) kennt osacompile in der Sandbox nicht: Für die Prüfung stehen dort gleichwertige Ausdrücke,
    so läuft der Test auch in der Sandbox."""

    def test_alle_skripte_kompilieren(self):
        with tempfile.TemporaryDirectory() as t:
            skripte = alle_skripte(Path(t).resolve())
            self.assertEqual(len(skripte), 9)
            for i, script in enumerate(skripte):
                ohne_zusaetze = re.sub(r"set t to \(read POSIX file .*", 'set t to "x"',
                                       script.replace("return current date", 'return date "1.1.2026"'))
                r = subprocess.run(["osacompile", "-o", str(Path(t) / f"{i}.scpt")], input=ohne_zusaetze,
                                   capture_output=True, text=True)
                with self.subTest(nummer=i + 1):
                    self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
