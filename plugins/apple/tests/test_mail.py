"""Tests für mail.py ohne Mail und ohne AppleScript: reine Funktionen und die Befehle mit einem Ersatz für run_as.

Aufruf im Kit-Ordner: python3 -B -m unittest discover tests
"""
import argparse
import contextlib
import datetime as dt
import io
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True  # hält __pycache__ aus dem Kit-Ordner heraus
os.environ.setdefault("KITS_FEHLERPROTOKOLL", "aus")  # Testläufe schreiben nicht ins Fehlerprotokoll des Pakets
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mail  # noqa: E402
import style_sample  # noqa: E402


def rec(*felder: str) -> str:
    """Ein Datensatz, wie ihn die AppleScript-Teile liefern."""
    return mail.FSEP.join(felder) + mail.RSEP


class BuildBody(unittest.TestCase):
    def test_genau_ein_umbruch_vor_der_signatur(self):
        """Mail setzt vor die Signatur selbst einen Umbruch, der Gruß bleibt im Text (Apple Mail hängt nur die Signatur
        an, signature_closing gibt es seit V3.1.2 nicht mehr)."""
        self.assertEqual(mail.build_body("Hi A,\nText.\n\nBeste Grüße\nLucas\n\n"),
                         "Hi A,\nText.\n\nBeste Grüße\nLucas\n")
        self.assertEqual(mail.build_body("Text"), "Text\n")


class Fingerprint(unittest.TestCase):
    def test_wiedererkennung_trotz_leerraum(self):
        fp = mail.fingerprint("Hi Max,\n\ndanke dir. Anna ist auf der Liste.")
        self.assertTrue(mail.matches_fingerprint(
            "Hi Max,\n\ndanke dir. Anna ist auf der Liste.\nBeste Grüße\nLucas\n> Zitat", fp))

    def test_umlaute_nfd_und_nfc(self):
        import unicodedata
        fp = mail.fingerprint("Rückmeldung vollständig")
        self.assertTrue(mail.matches_fingerprint(unicodedata.normalize("NFD", "Rückmeldung vollständig"), fp))

    def test_abweichender_text(self):
        fp = mail.fingerprint("Hi Max,\n\ndanke dir.")
        self.assertFalse(mail.matches_fingerprint("Hi Max,\n\nvielen Dank.", fp))

    def test_kein_klartext(self):
        fp = mail.fingerprint("geheimer Inhalt")
        self.assertNotIn("geheim", str(fp))


class Ausgabe(unittest.TestCase):
    def test_felder_und_saetze_trotz_trennzeichen_im_betreff(self):
        out = rec("1", "2026-09-28 10:00", "A <a@b.de>", "Re: X | Y Chef | 99 | ungelesen", "gelesen")
        rows = mail.records(out + rec("2", "2026-09-27 09:00", "B", "Z", "ungelesen"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][4], "gelesen")
        self.assertEqual(mail.clean(rows[0][3]), "Re: X / Y Chef / 99 / ungelesen")
        self.assertNotIn("\n", mail.clean("a\nb c\x1fd"))


class Unsichtbar(unittest.TestCase):
    def test_unsichtbare_zeichen_und_terminalfolgen_im_feld(self):
        """Review 21.10.2026: clean entfernt auch Richtungs- und Nullbreitenzeichen (Kategorie Cf, etwa U+202E und
        U+200B) und Terminalfolgen. Ein Betreff kann so nichts umdrehen oder verstecken."""
        self.assertEqual(mail.clean("Rechnung‮ fdp.exe​ \x1b[31mrot neu﻿"),
                         "Rechnung fdp.exe rot neu")
        self.assertEqual(mail.empfaenger("a@x.de​", "", "b@x.de"), "an a@x.de, Bcc b@x.de")
        self.assertEqual(mail.empfaenger("", "", ""), "(ohne Empfänger)")


class State(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = mail.DRAFT_STATE
        mail.DRAFT_STATE = Path(self.tmp.name) / "state.json"

    def tearDown(self):
        mail.DRAFT_STATE = self.old
        self.tmp.cleanup()

    def test_speichern_laden_loeschen(self):
        self.assertEqual(mail.load_state(), {})
        mail.save_state({"7": {"betreff": "Re: X", "eingefuegt": True}})
        self.assertEqual(mail.load_state()["7"]["betreff"], "Re: X")
        self.assertFalse(list(Path(self.tmp.name).glob("*.tmp")))  # atomar, keine Reste
        mail.save_state({})
        self.assertFalse(mail.DRAFT_STATE.exists())

    def test_kaputte_datei(self):
        mail.DRAFT_STATE.write_text("[1, 2]", encoding="utf-8")
        self.assertEqual(mail.load_state(), {})


class MailStart(unittest.TestCase):
    def test_startzeit_in_utc(self):
        """V3.1.2: ps rechnet die Startzeit von Mail in UTC. Nach einem Wechsel der Zeitzone sähen sonst alle
        Kit-Entwürfe fremd aus, send und discard verweigerten."""
        aufrufe = []

        def run(befehl, **kw):
            aufrufe.append((befehl, kw.get("env")))
            return subprocess.CompletedProcess(befehl, 0, "123\n" if befehl[0] == "pgrep" else
                                               "Fri Oct 23 08:00:00 2026\n", "")
        mail.mail_start.cache_clear()
        self.addCleanup(mail.mail_start.cache_clear)
        with mock.patch.object(mail.subprocess, "run", run), mock.patch.dict(os.environ, {"TZ": "Asia/Tokyo"}):
            self.assertEqual(mail.mail_start(), "Fri Oct 23 08:00:00 2026")
        befehl, env = aufrufe[-1]
        self.assertEqual(befehl, ["ps", "-o", "lstart=", "-p", "123"])
        self.assertEqual(env["TZ"], "UTC")


class HtmlPart(unittest.TestCase):
    def test_html_aus_multipart(self):
        src = ("MIME-Version: 1.0\nContent-Type: multipart/alternative; boundary=XX\n\n"
               "--XX\nContent-Type: text/plain; charset=utf-8\n\nHallo\n"
               "--XX\nContent-Type: text/html; charset=utf-8\nContent-Transfer-Encoding: quoted-printable\n\n"
               "<p>Gr=C3=BC=C3=9Fe</p>\n--XX--\n")
        self.assertIn("<p>Grüße</p>", mail.html_part(src))

    def test_ohne_html(self):
        self.assertEqual(mail.html_part("Content-Type: text/plain\n\nHallo\n"), "")

    def test_unbekannter_zeichensatz_klare_meldung(self):
        with self.assertRaises(SystemExit) as cm:
            mail.html_part("Content-Type: text/html; charset=gibtsnicht-7\n\n<p>x</p>\n")
        self.assertIn("HTML-Teil nicht lesbar", str(cm.exception.code))


class TextDateien(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name).resolve()  # macOS: /var -> /private/var
        self.old = mail.KIT_DIR
        self.kit_file = self.dir / "entwurf.txt"
        mail.KIT_DIR = self.dir  # die festen Textdateien gelten im Kit-Ordner (kit_basis.textdatei)

    def tearDown(self):
        mail.KIT_DIR = self.old
        self.tmp.cleanup()

    def ns(self, **kw):
        return argparse.Namespace(**{"text_file": None, "text": None, **kw})

    def test_kit_datei_wird_gelesen_und_geloescht(self):
        self.kit_file.write_text("Hi", encoding="utf-8")
        self.assertEqual(mail.read_text(self.ns(text_file=str(self.kit_file))), "Hi")
        mail.remove_text_file(self.ns(text_file=str(self.kit_file)))
        self.assertFalse(self.kit_file.exists())

    def test_relativer_name_gilt_im_kit_ordner_egal_wo_die_shell_steht(self):
        """V3: Kit-Befehle laufen mit absolutem Pfad ohne cd, entwurf.txt meint trotzdem die Datei im Kit."""
        self.kit_file.write_text("Hi", encoding="utf-8")
        alt = os.getcwd()
        os.chdir("/")
        try:
            self.assertEqual(mail.read_text(self.ns(text_file="entwurf.txt")), "Hi")
            mail.remove_text_file(self.ns(text_file="entwurf.txt"))
            self.assertFalse(self.kit_file.exists())
            with self.assertRaises(SystemExit):
                mail.read_text(self.ns(text_file="../entwurf.txt"))  # nur die Datei im Kit selbst
        finally:
            os.chdir(alt)

    def test_andere_datei_wird_nie_gelesen(self):
        other = self.dir / "geheim.txt"
        other.write_text("geheim", encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            mail.read_text(self.ns(text_file=str(other)))
        self.assertIn("Text nur aus entwurf.txt", str(cm.exception.code))
        mail.remove_text_file(self.ns(text_file=str(other)))
        self.assertTrue(other.exists())

    def test_fehlende_oder_falsch_kodierte_datei_ohne_traceback(self):
        with self.assertRaises(SystemExit) as cm:
            mail.read_text(self.ns(text_file=str(self.kit_file)))
        self.assertIn("fehlt", str(cm.exception.code))
        self.kit_file.write_bytes(b"\xff\xfe\x00Hi")
        with self.assertRaises(SystemExit) as cm:
            mail.read_text(self.ns(text_file=str(self.kit_file)))
        self.assertIn("kein UTF-8", str(cm.exception.code))

    def test_text_nur_aus_der_datei_und_nie_leer(self):
        """Prüfung 20.10.2026: --text gibt es nicht mehr, Text kommt nur aus der festen Datei im Kit."""
        with self.assertRaises(SystemExit) as cm:
            mail.read_text(self.ns())
        self.assertIn("--text-file", str(cm.exception.code))
        self.kit_file.write_text("  ", encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            mail.read_text(self.ns(text_file=str(self.kit_file)))
        self.assertIn("leer", str(cm.exception.code))

    def test_harter_verweis_wird_abgelehnt(self):
        fremd = self.dir / "fremd.txt"
        fremd.write_text("geheim", encoding="utf-8")
        os.link(fremd, self.kit_file)
        with self.assertRaises(SystemExit) as cm:
            mail.read_text(self.ns(text_file=str(self.kit_file)))
        self.assertIn("harter Verweis", str(cm.exception.code))


class ReadAusgabe(unittest.TestCase):
    def test_steuerzeichen_im_mailtext_werden_entfernt(self):
        """Prüfung 20.10.2026: Terminalfarben und versteckte Zeichen aus fremden Mails landen nicht im Transkript."""
        m = {"subject": "Hi\x07", "sender": "a@b.de", "to": "c@d.de", "cc": "", "attachments": "", "date": "2026-10-20",
             "body": "Zeile 1\n\x1b[31mrot\x1b[0m\tTab‮umgedreht"}
        out = io.StringIO()
        with mock.patch.object(mail, "fetch_message", return_value=m), contextlib.redirect_stdout(out):
            mail.cmd_read({}, argparse.Namespace(id="1", mailbox=None, profile=None, html=False, max_chars=None))
        text = out.getvalue()
        self.assertIn("Zeile 1\nrot\tTabumgedreht", text)
        for z in ("\x1b", "\x07", "‮"):
            self.assertNotIn(z, text)


def probe_mail(n: int, body: str) -> dict:
    return {"subject": f"Betreff {n}", "sender": f"a{n}@example.org", "to": "b@example.org", "cc": "", "bcc": "",
            "attachments": "", "date": "2026-10-21 10:00", "body": body}


class ReadMehrere(unittest.TestCase):
    """V3.1 (Optimierung 21.10.2026): read mit bis zu 10 IDs in einem Aufruf statt vieler Einzelaufrufe. Eine ID gibt
    genau die Ausgabe wie bisher."""

    def setUp(self):
        self.mails = {5: probe_mail(5, "Text 5"), 6: probe_mail(6, "Text​ 6"), 7: probe_mail(7, "Text 7")}
        self.gelesen = []

    def fetch(self, cfg, msg_id, mailbox, profile=None, source=False, timeout=90):
        self.gelesen.append(msg_id)
        if isinstance(self.mails.get(msg_id), str):
            sys.exit(self.mails[msg_id])
        if msg_id not in self.mails:
            sys.exit("AppleScript-Fehler: Mail kann message nicht finden.")
        return self.mails[msg_id]

    def lauf(self, ids, max_chars=0, html=False):
        out = io.StringIO()
        with mock.patch.object(mail, "fetch_message", self.fetch), contextlib.redirect_stdout(out):
            mail.cmd_read({"accounts": ["Privat"]}, argparse.Namespace(id=ids, mailbox="inbox", profile=None, html=html,
                                                                       max_chars=max_chars))
        return out.getvalue()

    def test_eine_id_wie_bisher(self):
        erwartet = ("Betreff: Betreff 5\nVon:     a5@example.org\nAn:      b@example.org\nDatum:   2026-10-21 10:00\n"
                    f"({mail.DATA_NOTE})\n\nText 5\n")
        self.assertEqual(self.lauf(5), erwartet)
        self.assertEqual(self.lauf([5]), erwartet)

    def test_drei_ids_je_mail_ein_kopf_in_der_reihenfolge(self):
        out = self.lauf([7, 5, 6])
        self.assertTrue(out.startswith(f"3 Mails, zusammen höchstens 12000 Zeichen ({mail.DATA_NOTE})\n"))
        self.assertLess(out.index("## Mail 7\n"), out.index("## Mail 5\n"))
        self.assertLess(out.index("## Mail 5\n"), out.index("## Mail 6\n"))
        self.assertIn("## Mail 6\nBetreff: Betreff 6\nVon:     a6@example.org\n", out)
        self.assertIn("\nText 6\n", out)  # Nullbreite entfernt
        self.assertEqual(out.count(mail.DATA_NOTE), 1)
        self.assertEqual(self.gelesen, [7, 5, 6])

    def test_gemeinsame_grenze_kurze_mails_bleiben_ganz(self):
        self.mails = {1: probe_mail(1, "a" * 100), 2: probe_mail(2, "b" * 5000), 3: probe_mail(3, "c" * 20000)}
        out = self.lauf([1, 2, 3])
        self.assertIn("a" * 100 + "\n", out)
        self.assertIn("b" * 5000 + "\n", out)
        self.assertIn("c" * 6900 + "\n[gekürzt, 20000 Zeichen gesamt, mehr mit --max-chars oder einzeln lesen]", out)
        self.assertNotIn("c" * 6901, out)
        self.assertEqual(mail.verteile([100, 5000, 20000], 3000), [100, 1450, 1450])
        self.assertEqual(mail.verteile([10, 20], 1000), [10, 20])
        out = self.lauf([1, 2, 3], max_chars=3000)
        self.assertIn("zusammen höchstens 3000 Zeichen", out)
        self.assertIn("b" * 1450 + "\n[gekürzt, 5000 Zeichen gesamt", out)

    def test_nicht_lesbare_mail_eine_zeile_die_anderen_kommen(self):
        out = self.lauf([5, 99, 6])
        self.assertIn("## Mail 99\nnicht lesbar: AppleScript-Fehler: Mail kann message nicht finden.\n", out)
        self.assertIn("Text 5", out)
        self.assertIn("Text 6", out)
        self.mails = {}
        with self.assertRaises(SystemExit) as cm:
            self.lauf([1, 2])
        self.assertIn("Keine der 2 Mails lesbar", str(cm.exception.code))

    def test_nach_zeitueberschreitung_kein_weiterer_versuch(self):
        self.mails[6] = "Mail hat nach 90 s nicht geantwortet. Zeitraum oder Treffer eingrenzen."
        out = self.lauf([5, 6, 7])
        self.assertEqual(self.gelesen, [5, 6])
        self.assertIn("## Mail 7\nnicht gelesen: Mail antwortet nicht, später einzeln lesen.\n", out)

    def test_jede_mail_nur_mit_der_restzeit(self):
        """V3.1.2: Jede Mail bekam bis 90 s, eine Anfrage kurz vor READ_ZEIT riss so die 120 s des Bash-Werkzeugs. Jetzt
        geht nur die Restzeit an run_as, der ganze Aufruf endet spätestens bei READ_ZEIT. Mail ersetzt eine falsche Uhr:
        jede Mail dauert 25 s."""
        uhr, zeitlimits = [0.0], []

        def run_as(script, *args, timeout=90, **kw):
            zeitlimits.append(timeout)
            uhr[0] += min(25, timeout)
            if timeout < 25:
                sys.exit(f"Mail hat nach {timeout} s nicht geantwortet. Zeitraum oder Treffer eingrenzen.")
            kopf = ["Betreff", "a@example.org", "Privat", "b@example.org", "", "", "", "2026-10-21 10:00"]
            return mail.FSEP.join(kopf) + mail.RSEP + "Text"
        out = io.StringIO()
        with mock.patch.object(mail, "run_as", run_as), mock.patch.object(mail.time, "monotonic", lambda: uhr[0]), \
                contextlib.redirect_stdout(out):
            mail.cmd_read({"accounts": ["Privat"]}, argparse.Namespace(id=[1, 2, 3, 4], mailbox="inbox", profile=None,
                                                                       html=False, max_chars=0))
        self.assertEqual(zeitlimits, [mail.READ_ZEIT, mail.READ_ZEIT - 25, mail.READ_ZEIT - 50])
        self.assertLessEqual(uhr[0], mail.READ_ZEIT)
        self.assertLess(mail.READ_ZEIT, 120)
        self.assertIn("## Mail 3\nnicht gelesen: Mail antwortet nicht", out.getvalue())
        self.assertIn("## Mail 4\nnicht gelesen: Mail antwortet nicht", out.getvalue())

    def test_falsche_aufrufe_mit_code_2(self):
        for ids, html, meldung in (([1] * 1 + list(range(2, 13)), False, "höchstens 10 IDs"),
                                   ([5, 6], True, "--html nur mit einer ID")):
            err = io.StringIO()
            with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
                self.lauf(ids, html=html)
            self.assertEqual(cm.exception.code, 2)
            self.assertIn(meldung, err.getvalue())
        self.assertEqual(self.gelesen, [])
        self.assertTrue(self.lauf([5, 5, 6]).startswith("2 Mails"))  # doppelte IDs einmal

    def test_konto_wird_vor_dem_lesen_geprueft(self):
        with self.assertRaises(SystemExit) as cm, mock.patch.object(mail, "fetch_message", self.fetch):
            mail.cmd_read({"accounts": []}, argparse.Namespace(id=[5, 6], mailbox="inbox", profile=None, html=False,
                                                               max_chars=0))
        self.assertIn("accounts ist leer", str(cm.exception.code))
        self.assertEqual(self.gelesen, [])

    def test_parser_nimmt_mehrere_ids(self):
        gesehen = []
        with mock.patch.object(mail, "cmd_read", lambda cfg, a: gesehen.append((a.id, a.max_chars))), \
                mock.patch.object(mail, "load_config", lambda: {}), \
                mock.patch.object(sys, "argv", ["mail.py", "read", "5", "6", "7", "--max-chars", "900"]):
            mail.main()
        with mock.patch.object(mail, "cmd_read", lambda cfg, a: gesehen.append((a.id, a.max_chars))), \
                mock.patch.object(mail, "load_config", lambda: {}), mock.patch.object(sys, "argv", ["mail.py", "read", "5"]):
            mail.main()
        self.assertEqual(gesehen, [([5, 6, 7], 900), ([5], 0)])

    def test_zahlen_nur_ab_1(self):
        """V3.1.2: --days, --limit und --max-chars nehmen nur ganze Zahlen ab 1. Vorher galt 0 still als Standard, eine
        negative Zahl suchte nichts oder kürzte verkehrt herum. Code 2, bevor config.json oder Mail gefragt werden."""
        for argv in (("search", "--from", "x", "--days", "0"), ("search", "--from", "x", "--days", "-3"),
                     ("search", "--from", "x", "--limit", "0"), ("search", "--from", "x", "--limit", "zwei"),
                     ("read", "5", "--max-chars", "0"), ("read", "5", "--max-chars", "-100")):
            err = io.StringIO()
            with mock.patch.object(sys, "argv", ["mail.py", *argv]), contextlib.redirect_stderr(err), \
                    mock.patch.object(mail, "load_config", side_effect=AssertionError(f"kein Abbruch bei {argv}")), \
                    self.assertRaises(SystemExit) as cm:
                mail.main()
            self.assertEqual(cm.exception.code, 2, argv)
            self.assertRegex(err.getvalue(), "muss größer als 0 sein|keine ganze Zahl|expected one argument", argv)


class Anhaenge(unittest.TestCase):
    def test_nur_aus_erlaubten_ordnern(self):
        with tempfile.TemporaryDirectory() as tmp:
            erlaubt, fremd = Path(tmp, "downloads"), Path(tmp, "OneDrive-Firma")
            erlaubt.mkdir()
            fremd.mkdir()
            (erlaubt / "a.pdf").write_text("x")
            (fremd / "deck.pptx").write_text("x")
            cfg = {"anhang_ordner": [str(erlaubt)]}
            self.assertEqual(mail.check_attachments(cfg, [str(erlaubt / "a.pdf")]), [str((erlaubt / "a.pdf").resolve())])
            with self.assertRaises(SystemExit) as cm:
                mail.check_attachments(cfg, [str(fremd / "deck.pptx")])
            self.assertIn("Anhang nur aus diesen Ordnern", str(cm.exception.code))
            with self.assertRaises(SystemExit) as cm:
                mail.check_attachments(cfg, [str(erlaubt / "weg.pdf")])
            self.assertIn("nicht gefunden", str(cm.exception.code))
            with self.assertRaises(SystemExit):
                mail.check_attachments({}, [str(erlaubt / "a.pdf")])  # ohne Liste nichts


# Erfundene Einstellungen: das Privatkonto in accounts mit Absender, das Arbeitskonto nur für Stilprobe und Signatur
KONTEN = {"accounts": ["Privat"], "default_profile": "privat",
          "profiles": {"privat": {"account": "Privat", "from_name": "Max Muster", "from_address": "max@example.org"},
                       "arbeit": {"account": "Firma", "from_name": "Max Muster",
                                  "from_address": "max@arbeit.example.com"}}}


class MitMail(unittest.TestCase):
    """Befehle mit einem Ersatz für run_as, inspect_draft und die Suche im Postfach Gesendet."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.alt = {n: getattr(mail, n) for n in ("DRAFT_STATE", "run_as", "mail_start", "inspect_draft",
                                                  "find_sent", "find_autosaves", "delete_drafts", "KIT_DIR")}
        mail.DRAFT_STATE = Path(self.tmp.name) / "state.json"
        mail.mail_start = lambda: "Mo 28 Sep 10:00:00 2026"
        self.aufrufe = []
        self.gesendet = "true"
        # Antwort von Mail nach draft: id, Länge, Absender, An, Cc, Bcc
        self.neu = ["12", "0", "Max Muster <max@example.org>", "nils@example.org", "", ""]
        mail.run_as = self.fake_run_as
        mail.find_sent = lambda subject, fp, ende: "gefunden"
        mail.find_autosaves = lambda subject, fp, since: []
        mail.delete_drafts = lambda ids: None

    def tearDown(self):
        for n, v in self.alt.items():
            setattr(mail, n, v)
        self.tmp.cleanup()

    def fake_run_as(self, script, *args, timeout=90, **kw):
        self.aufrufe.append((script, args))
        if "set ok to send" in script:
            return self.gesendet
        if "delete d" in script:
            return "ok\n" + args[1]
        if "make new outgoing message" in script:
            return mail.FSEP.join(self.neu)
        if "get outgoing messages" in script:
            return self.entwuerfe
        if "reply m with opening window" in script:  # id, Betreff, An, Cc, Bcc, Ergebnis des Einfügens
            return mail.FSEP.join(["12", "Re: Frage", "nils@example.org", "anna@example.org", "", self.einfuegen])
        if "return name of account of mailbox of m" in script:
            return "Privat"
        if "whose date received > cutoff" in script:
            return self.treffer
        raise AssertionError("unerwartetes Skript")

    def textdatei(self, text: str) -> str:
        """Entwurfstext als feste Datei im Temp-Ordner (Prüfung 20.10.2026: --text gibt es nicht mehr)."""
        datei = (Path(self.tmp.name) / "entwurf.txt").resolve()
        datei.write_text(text, encoding="utf-8")
        mail.KIT_DIR = datei.parent  # die festen Textdateien gelten im Kit-Ordner (kit_basis.textdatei)
        return str(datei)

    def entwurf(self, id_="7", betreff="Wochenende", text="Hi Nils,\n\nPasst Samstag?", laenge="30", cc="", bcc=""):
        fenster = mail.Entwurf(id_, betreff, "nils@example.org", cc, bcc, "Max Muster <max@example.org>", laenge, text)
        mail.inspect_draft = lambda draft_id: fenster

    def eintrag(self, art="neu", betreff="Wochenende", text="Hi Nils,\n\nPasst Samstag?", **kw):
        e = {"art": art, "betreff": betreff, "erstellt": 0, "eingefuegt": True, "kennung": mail.fingerprint(text),
             "mail_start": "Mo 28 Sep 10:00:00 2026", **kw}
        if art == "neu":  # wie draft: Prüfsumme für discard und der verlangte Absender
            e = {"kennung_text": mail.fingerprint(text, mail.TEXT_PRUEFUNG), "absender": "max@example.org", **e}
        state = mail.load_state()
        state["7"] = e
        mail.save_state(state)

    def lauf(self, fn, cfg=None, **kw):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            fn(cfg or {}, argparse.Namespace(**kw))
        return out.getvalue()

    def test_send_nur_fuer_kit_entwuerfe(self):
        self.entwurf()
        with self.assertRaises(SystemExit) as cm:
            self.lauf(mail.cmd_send, id=7, yes=True)
        self.assertIn("nicht angelegt", str(cm.exception.code))
        self.assertFalse(any("set ok to send" in s for s, _ in self.aufrufe))

    def test_send_nach_neustart_von_mail_verweigert(self):
        self.entwurf()
        self.eintrag(mail_start="So 27 Sep 08:00:00 2026")
        with self.assertRaises(SystemExit):
            self.lauf(mail.cmd_send, id=7, yes=True)
        self.assertEqual(mail.load_state(), {})  # veralteter Eintrag ist weg

    def test_send_leer_und_antwort_ohne_text_verweigert(self):
        self.entwurf(laenge="0", text="")
        self.eintrag()
        with self.assertRaises(SystemExit) as cm:
            self.lauf(mail.cmd_send, id=7, yes=True)
        self.assertIn("leer", str(cm.exception.code))
        self.entwurf(betreff="Re: Frage", laenge="0", text="")
        self.eintrag(art="antwort", betreff="Re: Frage", eingefuegt=False)
        with self.assertRaises(SystemExit) as cm:
            self.lauf(mail.cmd_send, id=7, yes=True)
        self.assertIn("nicht eingefügt", str(cm.exception.code))

    def test_send_ohne_yes_zeigt_nur(self):
        self.entwurf()
        self.eintrag()
        with self.assertRaises(SystemExit) as cm:
            self.lauf(mail.cmd_send, id=7, yes=False)
        self.assertEqual(cm.exception.code, 1)
        self.assertFalse(any("set ok to send" in s for s, _ in self.aufrufe))

    def test_send_wertet_antwort_von_mail_aus(self):
        self.entwurf()
        self.eintrag()
        self.gesendet = "false"
        with self.assertRaises(SystemExit) as cm:
            self.lauf(mail.cmd_send, id=7, yes=True)
        self.assertIn("nicht gesendet", str(cm.exception.code))
        self.assertIn("7", mail.load_state())  # bleibt offen und verwaltet
        self.gesendet = "true"
        out = self.lauf(mail.cmd_send, id=7, yes=True)
        self.assertIn("Gesendet: 7 | Wochenende | an nils@example.org | Max Muster <max@example.org>", out)
        self.assertIn("Geprüft", out)
        self.assertEqual(mail.load_state(), {})

    def test_send_meldet_im_fenster_geaenderten_text(self):
        self.entwurf(text="Hi Nils,\n\nDoch lieber Sonntag?")
        self.eintrag()
        self.assertIn("(Textanfang im Fenster geändert)", self.lauf(mail.cmd_send, id=7, yes=True))

    def test_discard_schuetzt_eigene_aenderungen(self):
        self.entwurf(text="Hi Nils,\n\nMein eigener Nachtrag")
        self.eintrag()
        with self.assertRaises(SystemExit) as cm:
            self.lauf(mail.cmd_discard, id=7)
        self.assertIn("im Fenster geändert", str(cm.exception.code))
        self.assertFalse(any("delete d" in s for s, _ in self.aufrufe))
        self.entwurf()
        self.assertIn("Entwurf 7 verworfen: Wochenende", self.lauf(mail.cmd_discard, id=7))
        self.assertEqual(mail.load_state(), {})

    def test_discard_prueft_bei_neuen_mails_300_zeichen(self):
        """Lucas 21.10.2026: discard ohne Rückfrage. Dafür vergleicht es bei neuen Mails 300 Zeichen des eigenen Textes
        (kennung_text aus draft), nicht nur die 80 für die Wiedererkennung. Eine Änderung nach Zeichen 80 fällt so auf.
        Was hinter dem eigenen Text dazukommt, sieht die Prüfung nicht (Grenze, im Skill genannt)."""
        text = "Hi Nils,\n\n" + "danke für deine Nachricht. " * 5 + "Bis Samstag!"
        self.assertTrue(mail.matches_fingerprint(text.replace("Samstag", "Sonntag"), mail.fingerprint(text)))  # 80
        self.entwurf(text=text.replace("Samstag", "Sonntag"))
        self.eintrag(text=text, kennung_text=mail.fingerprint(text, mail.TEXT_PRUEFUNG))
        with self.assertRaises(SystemExit) as cm:
            self.lauf(mail.cmd_discard, id=7)
        self.assertIn("im Fenster geändert", str(cm.exception.code))
        self.assertFalse(any("delete d" in s for s, _ in self.aufrufe))
        self.entwurf(text=text)
        self.assertIn("Entwurf 7 verworfen: Wochenende", self.lauf(mail.cmd_discard, id=7))

    def test_eintrag_ohne_pruefsumme_oder_absender_verweigert(self):
        """V3.1.2: Den Rückfall für Einträge ohne kennung_text und absender (vor dem 21.10.2026) gibt es nicht mehr. Ein
        solcher Eintrag verwirft und sendet nicht, statt mit einem Traceback abzubrechen."""
        self.entwurf()
        self.eintrag(kennung_text=None)
        with self.assertRaises(SystemExit) as cm:
            self.lauf(mail.cmd_discard, id=7)
        self.assertIn("Nicht verworfen", str(cm.exception.code))
        self.eintrag(absender="")
        with self.assertRaises(SystemExit) as cm:
            self.lauf(mail.cmd_send, id=7, yes=True)
        self.assertIn("Nicht gesendet: Absender ist Max Muster <max@example.org>, erwartet keiner",
                      str(cm.exception.code))
        self.assertFalse(any("set ok to send" in s or "delete d" in s for s, _ in self.aufrufe))

    def test_draft_merkt_sich_die_pruefsumme_fuer_discard(self):
        self.neu[1] = "30"
        self.lauf(mail.cmd_draft, cfg=KONTEN, text_file=self.textdatei("Hi Nils,\n\nPasst Samstag?"), reply_to=None,
                  all=False, profile=None, to=["nils@example.org"], cc=None, subject="Wochenende", attach=None)
        e = mail.load_state()["12"]
        self.assertEqual(e["kennung_text"], mail.fingerprint("Hi Nils,\n\nPasst Samstag?", mail.TEXT_PRUEFUNG))
        self.assertEqual(e["kennung"], mail.fingerprint("Hi Nils,\n\nPasst Samstag?"))

    def test_discard_antwort_nur_mit_ausfuehren(self):
        """Den Text einer Antwort liest AppleScript nicht: ohne --ausfuehren nur ein Hinweis, mit --ausfuehren verwirft
        es (darauf liegt die Rückfrage)."""
        self.entwurf(betreff="Re: Frage", text="")
        self.eintrag(art="antwort", betreff="Re: Frage")
        out = self.lauf(mail.cmd_discard, id=7, ausfuehren=False)
        self.assertIn("Vorschau, nichts verworfen: Antwortentwurf 7 (Re: Frage)", out)
        self.assertFalse(any("delete d" in s for s, _ in self.aufrufe))
        self.assertIn("7", mail.load_state())
        self.assertIn("Entwurf 7 verworfen: Re: Frage", self.lauf(mail.cmd_discard, id=7, ausfuehren=True))
        self.assertEqual(mail.load_state(), {})

    def test_discard_nur_fuer_kit_entwuerfe(self):
        self.entwurf()
        with self.assertRaises(SystemExit) as cm:
            self.lauf(mail.cmd_discard, id=7)
        self.assertIn("nicht das Kit angelegt", str(cm.exception.code))

    def test_drafts_zeigt_absender_und_raeumt_status_auf(self):
        self.eintrag()
        state = mail.load_state()
        state["8"] = {**state["7"], "betreff": "alt"}  # gehört inzwischen zu einem anderen Fenster
        mail.save_state(state)
        self.entwuerfe = (rec("7", "Wochenende", "nils@example.org", "", "", "Max Muster <max@example.org>", "30",
                              "Hi Nils")
                          + rec("8", "Rechnung | Juli", "", "", "", "Max Muster <max@example.org>", "5", "x"))
        out = self.lauf(mail.cmd_drafts)
        self.assertIn("7 | Wochenende | an nils@example.org | Max Muster <max@example.org> | 30 Zeichen", out)
        self.assertIn("8 | Rechnung / Juli | (ohne Empfänger)", out)
        self.assertIn("(nicht vom Kit)", out)
        self.assertEqual(set(mail.load_state()), {"7"})

    def test_leerer_neuer_entwurf_endet_mit_code_4(self):
        with self.assertRaises(SystemExit) as cm:
            self.lauf(mail.cmd_draft, cfg=KONTEN, text_file=self.textdatei("Hallo"), reply_to=None, all=False,
                      profile=None, to=["nils@example.org"], cc=None, subject="Test", attach=None)
        self.assertEqual(cm.exception.code, mail.EXIT_EMPTY)

    def test_suche_sortiert_vor_dem_kuerzen(self):
        self.treffer = (rec("1", "2026-09-20 08:00", "A", "alt", "gelesen") + rec("3", "2026-09-28 09:00", "C", "neu",
                        "ungelesen") + rec("2", "2026-09-25 12:00", "B", "mittel", "gelesen"))
        ns = dict(sender="x", subject=None, text=None, unread=False, days=30, limit=2, profile=None, mailbox="inbox")
        cfg = {"accounts": ["Privat"]}
        out = self.lauf(mail.cmd_search, cfg=cfg, **ns)
        zeilen = out.strip().splitlines()
        self.assertTrue(zeilen[1].startswith("3 | 2026-09-28"))
        self.assertTrue(zeilen[2].startswith("2 | 2026-09-25"))
        self.assertIn("1 weitere Treffer", out)
        self.treffer = rec("5", "2026-09-28 09:00", "an x@y.de, z@y.de, Cc c@y.de", "Termin", "gesendet")
        out = self.lauf(mail.cmd_search, cfg=cfg, **{**ns, "mailbox": "sent", "sender": None})
        self.assertIn("id | datum | empfänger | betreff | status", out)
        self.assertIn("an x@y.de, z@y.de, Cc c@y.de", out)

    def finden_ns(self, **kw):
        return dict({"message_id": None, "subject": None, "sender": None, "datum": None, "days": None,
                     "mailbox": "inbox", "profile": None}, **kw)

    def test_finden_ueber_message_id_eindeutig(self):
        """V5, Mail-Brücke: Die Message-ID aus dem Connector findet die Mail in Apple Mail, ohne spitze Klammern."""
        self.treffer = rec("41", "2026-11-10 09:12", "Anna <anna@example.org>", "Angebot", "gelesen")
        out = self.lauf(mail.cmd_finden, cfg={"accounts": ["Privat"]},
                        **self.finden_ns(message_id=" <abc.123@mail.example.org> "))
        self.assertIn("41 | 2026-11-10 09:12 | Anna <anna@example.org> | Angebot | gelesen", out)
        self.assertIn("Eindeutig: id 41, für die Antwort draft --reply-to 41.", out)
        script, args = self.aufrufe[-1]
        self.assertEqual(args, ("365", "-1", "1", "Privat", "abc.123@mail.example.org"))
        self.assertIn("message id is (item 5 of argv)", script)
        self.assertIn("date received < bis", script)

    def test_finden_ueber_betreff_absender_datum(self):
        self.treffer = (rec("7", "2026-11-09 18:00", "B <b@x.de>", "Re: Angebot", "gelesen")
                        + rec("8", "2026-11-10 08:00", "B <b@x.de>", "Angebot", "ungelesen"))
        out = self.lauf(mail.cmd_finden, cfg={"accounts": ["Privat", "Arbeit"]},
                        **self.finden_ns(subject="Angebot", sender="b@x.de", datum=str(dt.date.today())))
        zeilen = out.strip().splitlines()
        self.assertTrue(zeilen[1].startswith("8 | "))  # neueste zuerst
        self.assertIn("2 Treffer, nicht eindeutig", out)
        script, args = self.aufrufe[-1]
        self.assertEqual(args[:5], ("1", "-1", "2", "Privat", "Arbeit"))
        self.assertIn("subject contains (item 6 of argv) and sender contains (item 7 of argv)", script)

    def test_finden_ohne_treffer_und_falsche_angaben(self):
        self.treffer = ""
        out = self.lauf(mail.cmd_finden, cfg={"accounts": ["Privat"]}, **self.finden_ns(subject="Nichts"))
        self.assertIn("Keine passende Mail in Apple Mail (Posteingang)", out)
        for kw in ({}, {"sender": "b@x.de"}, {"message_id": "keine id"}, {"subject": "x", "datum": "10.11.2026"},
                   {"subject": "x", "datum": "2099-01-01"}):
            with self.subTest(kw=kw), contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit) as cm:
                self.lauf(mail.cmd_finden, cfg={"accounts": ["Privat"]}, **self.finden_ns(**kw))
            self.assertEqual(cm.exception.code, 2)

    def test_finden_zeitfenster_um_den_tag(self):
        heute = dt.date(2026, 11, 11)
        ns = argparse.Namespace(**self.finden_ns(subject="x", datum="2026-11-01"))
        self.assertEqual(mail.finden_suche(ns, heute)[:2], (11, 9))
        ns = argparse.Namespace(**self.finden_ns(subject="x", days=30))
        self.assertEqual(mail.finden_suche(ns, heute)[:2], (30, -1))

    def test_suche_verwirft_gefaelschte_zeilen(self):
        """Review 21.10.2026: Ein fremder Betreff mit den Trennzeichen konnte Zeilen fälschen, etwa eine id mit anderem
        Absender. Das AppleScript ersetzt die Zeichen (no_sep), Python nimmt nur Datensätze mit genau fünf Feldern, id
        und Datum, die übrigen zählt eine Zeile. Ein #weg zählt nur als erster Datensatz."""
        self.treffer = (rec("#weg", "konto") + rec("1", "2026-09-28 08:00", "A <a@x.de>", "Hallo‮​", "gelesen")
                        + rec("99999", "2026-09-28 09:00", "chef@x.de", "Gefälscht", "ungelesen", "zu viel")
                        + rec("x1", "2026-09-28 09:00", "chef@x.de", "Gefälscht", "ungelesen")
                        + rec("2", "morgen", "chef@x.de", "Gefälscht", "ungelesen") + rec("#weg", "sammel"))
        out = self.lauf(mail.cmd_search, cfg={"accounts": ["Privat"]}, sender="x", subject=None, text=None,
                        unread=False, days=30, limit=5, profile=None, mailbox="inbox")
        self.assertIn("1 | 2026-09-28 08:00 | A <a@x.de> | Hallo | gelesen", out)
        self.assertNotIn("Gefälscht", out)
        self.assertIn("[4 Datensätze von Mail in unerwartetem Format übersprungen]", out)
        for teil in ("my no_sep(sender of m)", "my no_sep(subject of m)", "character id 30, character id 31"):
            self.assertIn(teil, mail.AS_COMMON)

    def test_read_mit_bcc_und_nur_mit_vollstaendigem_kopf(self):
        """Review 21.10.2026: read zeigt auch Bcc (bei gesendeten Mails) und bricht ab, wenn der Kopf nicht genau acht
        Felder mit Datum hat. Sonst könnte ein Betreff mit Trennzeichen einen anderen Absender vortäuschen."""
        kopf = ["Betreff", "A <a@x.de>", "Privat", "b@x.de", "c@x.de", "d@x.de", "", "2026-09-28 08:00"]
        mail.run_as = lambda script, *args, **kw: mail.FSEP.join(kopf) + mail.RSEP + "Text"
        ns = dict(id=5, mailbox="sent", profile=None, html=False, max_chars=0)
        out = self.lauf(mail.cmd_read, cfg={"accounts": ["Privat"]}, **ns)
        self.assertIn("An:      b@x.de\nCc:      c@x.de\nBcc:     d@x.de\n", out)
        kopf[0] = "Betreff" + mail.FSEP + "chef@x.de"
        with self.assertRaises(SystemExit) as cm:
            self.lauf(mail.cmd_read, cfg={"accounts": ["Privat"]}, **ns)
        self.assertIn("in unerwartetem Format. Nichts ausgegeben.", str(cm.exception.code))

    def test_suche_im_postfach_des_kontos_und_rueckfall(self):
        cfg = {"accounts": ["Privat"]}
        ns = dict(sender="x", subject=None, text=None, unread=False, days=30, limit=5, profile=None, mailbox="inbox")
        self.treffer = rec("#weg", "konto")
        self.assertEqual(self.lauf(mail.cmd_search, cfg=cfg, **ns).strip(), "Keine Treffer (Posteingang von Privat, 30 Tage).")
        script, args = self.aufrufe[-1]
        self.assertIn('account_boxes("inbox", acctNames)', script)
        self.assertIn("items 4 thru (3 + nAcct) of argv", script)
        self.assertEqual(args[:4], ("30", "250", "1", "Privat"))
        self.treffer = rec("#weg", "sammel") + rec("1", "2026-09-28 08:00", "A", "B", "gelesen")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            out = self.lauf(mail.cmd_search, cfg=cfg, **{**ns, "mailbox": "sent"})
        self.assertIn("gesucht wurde im Sammelpostfach", err.getvalue())
        self.assertIn('account_boxes("sent", acctNames)', self.aufrufe[-1][0])
        self.assertEqual(len(out.strip().splitlines()), 2)  # Kopf und eine Zeile, der Weg ist kein Treffer

    def test_suche_nennt_nicht_gefundene_konten(self):
        """Etappe 2 von v7.3.0: Ein Konto aus accounts, das Mail nicht liefert, fiel still weg. Jetzt meldet das
        AppleScript es als #fehlt, die Ausgabe nennt es als nicht durchsucht und lässt es aus dem Wo weg."""
        cfg = {"accounts": ["Privat", "Verein"]}
        ns = dict(sender="x", subject=None, text=None, unread=False, days=30, limit=5, profile=None, mailbox="inbox")
        self.treffer = rec("#weg", "konto") + rec("#fehlt", "verein")  # AppleScript vergleicht ohne Groß und Klein
        out = self.lauf(mail.cmd_search, cfg=cfg, **ns)
        self.assertEqual(out.splitlines(), [
            "Keine Treffer (Posteingang von Privat, 30 Tage).",
            "Konto Verein: in Mail nicht gefunden (deaktiviert oder umbenannt?), Posteingang nicht durchsucht. Name in "
            "accounts der config.json mit Apple Mail abgleichen."])
        self.assertIn("my missing_accounts(boxes, acctNames)", self.aufrufe[-1][0])
        # Gesendet, mit Treffer: die Zeile steht nach den Treffern
        self.treffer = (rec("#weg", "sammel") + rec("#fehlt", "Verein")
                        + rec("1", "2026-09-28 08:00", "an a@x.de", "B", "gesendet"))
        with contextlib.redirect_stderr(io.StringIO()):
            out = self.lauf(mail.cmd_search, cfg=cfg, **{**ns, "mailbox": "sent"})
        self.assertTrue(out.splitlines()[1].startswith("1 | "))
        self.assertIn("Konto Verein: in Mail nicht gefunden (deaktiviert oder umbenannt?), Postfach Gesendet nicht "
                      "durchsucht.", out.splitlines()[2])
        # Kein Konto gefunden: nichts durchsucht statt keine Treffer
        self.treffer = rec("#weg", "sammel") + rec("#fehlt", "Privat") + rec("#fehlt", "Verein")
        with contextlib.redirect_stderr(io.StringIO()):
            out = self.lauf(mail.cmd_search, cfg=cfg, **ns)
        self.assertTrue(out.startswith("Nichts durchsucht: kein Konto aus accounts in Mail gefunden.\n"), out)
        self.assertNotIn("Keine Treffer", out)
        self.assertEqual(out.count("nicht durchsucht"), 2)

    def test_fehlt_nur_vorn_und_nur_fuer_eigene_konten(self):
        """Ein #fehlt zwischen den Mails zählt als unerwartetes Format, ein #fehlt für ein Konto außerhalb von accounts
        fällt weg."""
        self.treffer = (rec("#weg", "konto") + rec("#fehlt", "Fremd")
                        + rec("1", "2026-09-28 08:00", "A", "B", "gelesen") + rec("#fehlt", "Privat"))
        out = self.lauf(mail.cmd_search, cfg={"accounts": ["Privat"]}, sender="x", subject=None, text=None,
                        unread=False, days=30, limit=5, profile=None, mailbox="inbox")
        self.assertNotIn("nicht durchsucht", out)
        self.assertIn("[1 Datensätze von Mail in unerwartetem Format übersprungen]", out)

    def test_finden_nennt_nicht_gefundene_konten(self):
        self.treffer = rec("#fehlt", "Verein")
        out = self.lauf(mail.cmd_finden, cfg={"accounts": ["Privat", "Verein"]}, **self.finden_ns(subject="Angebot"))
        self.assertIn("Keine passende Mail in Apple Mail (Posteingang)", out)
        self.assertIn("Konto Verein: in Mail nicht gefunden", out)
        self.assertIn("my missing_accounts(boxes, acctNames)", self.aufrufe[-1][0])
        self.treffer = rec("#fehlt", "Privat")
        out = self.lauf(mail.cmd_finden, cfg={"accounts": ["Privat"]}, **self.finden_ns(subject="Angebot"))
        self.assertTrue(out.startswith("Nichts durchsucht"), out)

    def antwort(self, einfuegen):
        self.einfuegen = einfuegen
        cfg = {"accounts": ["Privat"], "profiles": {"privat": {"account": "Privat"}}}
        ns = dict(text_file=self.textdatei("Hi Nils,\n\nPasst."), reply_to=5, all=False, profile=None, to=None,
                  cc=None, subject=None, attach=None)
        return self.lauf(mail.cmd_draft, cfg=cfg, **ns)

    def test_antwort_zaehlt_nach_dem_einfuegen_nach(self):
        out = self.antwort("ok")
        self.assertIn("Text eingefügt und im Fenster nachgezählt", out)
        # Review 21.10.2026: Empfänger einer Antwort setzt Mail, mit --all auch Cc, die Ausgabe zeigt sie
        self.assertIn("Antwort-Entwurf 12 geöffnet (Profil: privat): an nils@example.org, Cc anna@example.org | "
                      "Betreff: Re: Frage", out)
        script, args = self.aufrufe[-1]
        for liste in ("to recipients of d", "cc recipients of d", "bcc recipients of d"):
            self.assertIn(f"my addr_list({liste})", script)
        self.assertEqual(args[5], str(mail.mindest_zeichen("Hi Nils,\n\nPasst.")))  # Mindestzahl neuer Zeichen
        self.assertIn("in_accounts(m, argv, 8 + nCc, nAcct)", script)
        self.assertEqual(args[6], "")  # ohne --betreff-erwartet keine Prüfung
        self.assertTrue(mail.load_state()["12"]["eingefuegt"])
        self.assertIn("ließ sich nicht nachzählen", self.antwort("ok ungeprueft"))
        self.assertTrue(mail.load_state()["12"]["eingefuegt"])
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            self.antwort("leer 120 121")
        self.assertEqual(cm.exception.code, mail.EXIT_NOT_INSERTED)
        self.assertIn("zu wenige Zeichen an (Zahl vorher und nachher). (120 121)", err.getvalue())
        self.assertIn("Fehlt der Text im Fenster", err.getvalue())
        self.assertFalse(mail.load_state()["12"]["eingefuegt"])  # send verweigert dann

    def test_antwort_prueft_den_betreff_vor_reply(self):
        """Etappe 2 von v7.3.0: Mit --betreff-erwartet vergleicht das AppleScript den Betreff vor reply. Passt er, läuft
        alles wie bisher. Passt er nicht, bricht draft mit beiden Betreffs ab, ohne Fenster und ohne Statuseintrag, die
        Textdatei bleibt für den nächsten Versuch."""
        self.einfuegen = "ok"
        cfg = {"accounts": ["Privat"], "profiles": {"privat": {"account": "Privat"}}}
        ns = dict(text_file=self.textdatei("Hi Nils,\n\nPasst."), reply_to=5, all=False, profile=None, to=None,
                  cc=None, subject=None, attach=None, betreff_erwartet="AW:  frage ")
        out = self.lauf(mail.cmd_draft, cfg=cfg, **ns)
        self.assertIn("Antwort-Entwurf 12 geöffnet", out)
        script, args = self.aufrufe[-1]
        self.assertEqual(args[6], "AW:  frage")
        self.assertLess(script.index("my same_subject(ist, erwartet)"), script.index("reply m with opening window"))
        self.assertIn(mail.BETREFF_PRAEFIX.replace("\\", "\\\\"), script)  # dieselbe Regel wie betreff_kern

        mail.save_state({})
        mail.run_as = lambda script, *args, **kw: "#betreff" + mail.FSEP + "Rechnung März"
        datei = self.textdatei("Hi Nils,\n\nPasst.")
        with self.assertRaises(SystemExit) as cm:
            self.lauf(mail.cmd_draft, cfg=cfg, **{**ns, "text_file": datei, "betreff_erwartet": "Frage"})
        meldung = str(cm.exception.code)
        self.assertIn("nichts geöffnet: Mail 5 hat den Betreff Rechnung März, erwartet war Frage", meldung)
        self.assertEqual(mail.load_state(), {})
        self.assertTrue(Path(datei).exists())

    def test_betreff_erwartet_nur_bei_antworten_und_nie_leer(self):
        cfg = {"accounts": ["Privat"], "profiles": {"privat": {"account": "Privat", "from_address": "max@example.org"}},
               "default_profile": "privat"}
        neu = dict(text_file=self.textdatei("Hallo"), reply_to=None, all=False, profile=None, to=["a@b.de"], cc=None,
                   subject="Frage", attach=None, betreff_erwartet="Frage")
        antwort = {**neu, "reply_to": 5, "to": None, "subject": None, "betreff_erwartet": " Re: "}
        for ns in (neu, antwort):
            with self.subTest(ns=ns), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                self.lauf(mail.cmd_draft, cfg=cfg, **ns)
            self.assertEqual(cm.exception.code, 2)
        self.assertEqual(self.aufrufe, [])  # abgebrochen, bevor Mail etwas gefragt wird

    def test_betreff_kern(self):
        for ist, erwartet in (("AW: WG:  Angebot  Q4", "angebot q4"), ("Re[2]: Fwd: Übergabe", "übergabe"),
                              (" RE :Termin morgen", "Termin morgen"), ("Fw: Antw: Bericht", "BERICHT"),
                              ("Re: Re: ", "")):
            with self.subTest(ist=ist):
                self.assertEqual(mail.betreff_kern(ist), mail.betreff_kern(erwartet))
        for ist, erwartet in (("Re: Angebot", "Angebot neu"), ("Reise: Plan", "Plan"), ("Rechnung", "Re: Rechnung 2")):
            with self.subTest(ist=ist):
                self.assertNotEqual(mail.betreff_kern(ist), mail.betreff_kern(erwartet))

    def test_mindestzahl_ohne_leerraum_und_nie_null(self):
        self.assertEqual(mail.mindest_zeichen("ab cd\n\nef"), 3)
        self.assertEqual(mail.mindest_zeichen("a"), 1)

    def test_leere_konten_erlauben_nicht_alles(self):
        """Prüfung 20.10.2026: Leere accounts hießen für die AppleScripts alle Konten, auch das Exchange-Postfach. Jetzt
        brechen search, read und Antworten vor Mail ab. Mit --profile gilt dessen Konto, ein Profil ohne Konto bricht ab."""
        ns = dict(sender="x", subject=None, text=None, unread=False, days=30, limit=5, profile=None, mailbox="inbox")
        for cfg in ({}, {"accounts": []}):
            with self.assertRaises(SystemExit) as cm:
                self.lauf(mail.cmd_search, cfg=cfg, **ns)
            self.assertIn("accounts ist leer", str(cm.exception.code))
        with self.assertRaises(SystemExit) as cm:
            self.lauf(mail.cmd_read, cfg={"accounts": []}, id=5, mailbox="inbox", profile=None, html=False, max_chars=0)
        self.assertIn("accounts ist leer", str(cm.exception.code))
        with self.assertRaises(SystemExit) as cm:
            self.lauf(mail.cmd_draft, cfg={"accounts": []}, text_file=self.textdatei("Hi"), reply_to=5, all=False,
                      profile=None, to=None, cc=None, subject=None, attach=None)
        self.assertIn("accounts ist leer", str(cm.exception.code))
        self.assertEqual(self.aufrufe, [])  # Mail nie gefragt
        cfg = {"accounts": ["Privat"], "profiles": {"privat": {"account": "Privat"}, "ohne": {"from_name": "Max"}}}
        self.treffer = rec("#weg", "konto")
        self.lauf(mail.cmd_search, cfg=cfg, **{**ns, "profile": "privat"})
        self.assertEqual(self.aufrufe[-1][1][:4], ("30", "250", "1", "Privat"))
        with self.assertRaises(SystemExit) as cm:
            self.lauf(mail.cmd_search, cfg=cfg, **{**ns, "profile": "ohne"})
        self.assertIn("Profil ohne hat kein account", str(cm.exception.code))
        self.assertIn("if n is 0 then return false", mail.AS_COMMON)  # auch das AppleScript lässt dann nichts durch

    def test_arbeitskonto_nie_ueber_apple_mail(self):
        """Review 21.10.2026: --profile arbeit öffnete Arbeitsmails und Entwürfe des Exchange-Kontos über Apple Mail ohne
        Rückfrage. search, read und draft gelten nur für Konten aus accounts, sonst Code 2 vor jedem Zugriff auf Mail.
        Ein unbekanntes Profil ist ebenso ein falscher Aufruf."""
        ns = dict(sender="x", subject=None, text=None, unread=False, days=30, limit=5, mailbox="inbox")
        neu = dict(text_file=self.textdatei("Hi"), reply_to=None, all=False, to=["a@example.org"], cc=None,
                   subject="X", attach=None)
        aufrufe = ((mail.cmd_search, ns), (mail.cmd_read, dict(id=5, mailbox="inbox", html=False, max_chars=0)),
                   (mail.cmd_draft, neu), (mail.cmd_draft, {**neu, "reply_to": 5, "to": None, "subject": None}))
        for profil, meldung in (("arbeit", "Profil arbeit (Konto Firma) gilt hier nicht"),
                                ("gibtsnicht", "Unbekanntes Profil: gibtsnicht")):
            for fn, kw in aufrufe:
                err = io.StringIO()
                with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
                    self.lauf(fn, cfg=KONTEN, profile=profil, **kw)
                self.assertEqual(cm.exception.code, 2, (fn.__name__, profil))
                self.assertIn(meldung, err.getvalue())
        self.assertEqual(self.aufrufe, [])  # Mail nie gefragt
        with self.assertRaises(SystemExit) as cm:
            self.lauf(mail.cmd_draft, cfg={**KONTEN, "default_profile": "arbeit"}, profile=None, **neu)
        self.assertEqual(cm.exception.code, 2)  # auch nicht über default_profile

    def test_neue_mail_nur_mit_absender(self):
        """Review 21.10.2026: Ohne from_address oder Profil entfiel die Prüfung des Absenders still. draft verlangt beides
        für neue Mails und fragt Mail vorher nicht."""
        neu = dict(text_file=self.textdatei("Hi"), reply_to=None, all=False, profile=None, to=["a@example.org"], cc=None,
                   subject="X", attach=None)
        ohne = {"accounts": ["Privat"], "default_profile": "privat", "profiles": {"privat": {"account": "Privat"}}}
        for cfg, meldung in ((ohne, "Profil privat hat kein from_address"), ({"accounts": ["Privat"]}, "Kein Profil")):
            with self.assertRaises(SystemExit) as cm:
                self.lauf(mail.cmd_draft, cfg=cfg, **neu)
            self.assertIn(meldung, str(cm.exception.code))
        self.assertEqual(self.aufrufe, [])

    def test_neue_mail_zeigt_alle_empfaenger(self):
        """Review 21.10.2026: draft zeigte nur An. Die Ausgabe nennt An, Cc und Bcc so, wie Mail sie nach dem Anlegen hat."""
        self.neu = ["12", "30", "Max Muster <max@example.org>", "nils@example.org", "anna@example.org",
                    "max@example.org"]
        out = self.lauf(mail.cmd_draft, cfg=KONTEN, text_file=self.textdatei("Hi Nils,\n\nPasst Samstag?"),
                        reply_to=None, all=False, profile=None, to=["nils@example.org"], cc=["anna@example.org"],
                        subject="Wochenende", attach=None)
        self.assertIn("): an nils@example.org, Cc anna@example.org, Bcc max@example.org | Betreff: Wochenende", out)
        script = next(s for s, _ in self.aufrufe if "make new outgoing message" in s)
        for liste in ("to recipients of d", "cc recipients of d", "bcc recipients of d"):
            self.assertIn(f"my addr_list({liste})", script)

    def test_send_und_drafts_zeigen_cc_und_bcc(self):
        """Review 21.10.2026: Vor dem Senden sieht Lucas alle Empfänger, auch Cc und Bcc, in der Vorschau und in drafts."""
        self.entwurf(cc="anna@example.org", bcc="ben@example.org")
        self.eintrag()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):  # ohne --yes nur die Vorschau
            mail.cmd_send({}, argparse.Namespace(id=7, yes=False))
        self.assertIn("Nicht gesendet. Entwurf: 7 | Wochenende | an nils@example.org, Cc anna@example.org, Bcc "
                      "ben@example.org | Max Muster <max@example.org> | 30 Zeichen", out.getvalue())
        self.entwuerfe = rec("7", "Wochenende", "nils@example.org", "anna@example.org", "ben@example.org",
                             "Max Muster <max@example.org>", "30", "Hi Nils")
        self.assertIn("7 | Wochenende | an nils@example.org, Cc anna@example.org, Bcc ben@example.org |",
                      self.lauf(mail.cmd_drafts))
        for liste in ("to recipients of d", "cc recipients of d", "bcc recipients of d"):
            self.assertIn(f"my addr_list({liste})", mail.AS_DRAFT_LINE)

    def neuer_entwurf(self, absender_in_mail: str) -> str:
        """draft mit Profil privat, Mail meldet nach dem Anlegen absender_in_mail als Absender."""
        self.neu = ["12", "30", absender_in_mail, "nils@example.org", "", ""]
        return self.lauf(mail.cmd_draft, cfg=KONTEN, text_file=self.textdatei("Hi Nils,\n\nPasst Samstag?"),
                         reply_to=None, all=False, profile=None, to=["nils@example.org"], cc=None, subject="Wochenende",
                         attach=None)

    def test_draft_prueft_den_absender(self):
        """Prüfung 20.10.2026: Übernimmt Mail den Absender aus config.json nicht, endet draft mit Code 5 und sagt, was im
        Entwurf steht. send verweigert dann, bis im Fenster bei Von das richtige Konto steht."""
        self.assertIn("Absender: Max Muster <max@example.org>", self.neuer_entwurf("Max Muster <MAX@example.org>"))
        self.assertEqual(mail.load_state()["12"]["absender"], "max@example.org")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            self.neuer_entwurf("Max Muster <max@arbeit.example.com>")
        self.assertEqual(cm.exception.code, mail.EXIT_ABSENDER)
        self.assertIn("im Entwurf steht Max Muster <max@arbeit.example.com> statt max@example.org", err.getvalue())
        self.assertTrue((Path(self.tmp.name) / "entwurf.txt").exists())  # Text bleibt für einen neuen Versuch
        fenster = mail.Entwurf("12", "Wochenende", "nils@example.org", "", "", "Max Muster <max@arbeit.example.com>",
                               "30", "Hi Nils,\n\nPasst Samstag?")
        mail.inspect_draft = lambda draft_id: fenster
        with self.assertRaises(SystemExit) as cm:
            self.lauf(mail.cmd_send, id=12, yes=True)
        self.assertIn("Nicht gesendet: Absender ist Max Muster <max@arbeit.example.com>, erwartet max@example.org",
                      str(cm.exception.code))
        self.assertFalse(any("set ok to send" in s for s, _ in self.aufrufe))
        fenster = fenster._replace(von="Max Muster <max@example.org>")  # Lucas hat bei Von das Konto gewählt
        self.assertIn("Gesendet: 12 | Wochenende", self.lauf(mail.cmd_send, id=12, yes=True))

    def test_send_bleibt_unter_120_s(self):
        """Prüfung 20.10.2026: send samt Suche im Postfach Gesendet endet vor den 120 s des Bash-Werkzeugs, auch wenn
        Mail jede Anfrage bis zum Zeitlimit liegen lässt. Die Bestätigung meldet send dann als offen und endet mit 0,
        denn gesendet hat Mail schon."""
        uhr, aufrufe = [0.0], []

        def run_as(script, *args, timeout=90, zeitablauf=""):
            aufrufe.append((timeout, zeitablauf))
            uhr[0] += timeout  # Mail antwortet erst am Zeitlimit
            if "set ok to send" in script:
                return "true"
            sys.exit("Mail hat nicht geantwortet")  # wie run_as beim Zeitablauf

        def fenster(draft_id):
            uhr[0] += mail.SEND_SCHRITT  # auch das Prüfen des Entwurfs dauert bis zum Zeitlimit
            return mail.Entwurf("7", "Wochenende", "nils@example.org", "", "", "Max Muster <max@example.org>", "30",
                                "Hi Nils,\n\nPasst Samstag?")

        self.eintrag()
        mail.run_as, mail.inspect_draft, mail.find_sent = run_as, fenster, self.alt["find_sent"]
        with mock.patch.object(mail.time, "monotonic", lambda: uhr[0]), \
                mock.patch.object(mail.time, "sleep", lambda s: uhr.__setitem__(0, uhr[0] + s)):
            out = self.lauf(mail.cmd_send, id=7, yes=True)
        self.assertIn("Gesendet: 7 | Wochenende", out)
        self.assertIn("Bestätigung steht aus, Mail hat nicht rechtzeitig geantwortet. Nicht erneut senden", out)
        self.assertLessEqual(uhr[0], mail.SEND_GRENZE)
        self.assertLess(mail.SEND_GRENZE, 120)
        self.assertEqual(aufrufe[0][0], mail.SEND_SCHRITT)  # das Senden selbst
        self.assertIn("nicht erneut senden", aufrufe[0][1])
        self.assertEqual(mail.load_state(), {})


class SendFrist(unittest.TestCase):
    """find_sent und run_as mit Zeitlimit, ohne Mail: eine falsche Uhr statt Warten."""

    def setUp(self):
        self.uhr, self.zeitlimits, self.inhalt, self.dauer = [0.0], [], "", 2
        for p in (mock.patch.object(mail, "run_as", self.run_as),
                  mock.patch.object(mail.time, "monotonic", lambda: self.uhr[0]),
                  mock.patch.object(mail.time, "sleep", lambda s: self.uhr.__setitem__(0, self.uhr[0] + s))):
            p.start()
            self.addCleanup(p.stop)

    def run_as(self, script, *args, timeout=90, **kw):
        self.zeitlimits.append(timeout)
        if self.dauer > timeout:
            self.uhr[0] += timeout
            sys.exit("Mail hat nicht geantwortet")
        self.uhr[0] += self.dauer
        return self.inhalt

    def test_suche_endet_vor_der_frist(self):
        fp = mail.fingerprint("Hi Nils,\n\nPasst Samstag?")
        self.assertEqual(mail.find_sent("Wochenende", fp, ende=100.0), "fehlt")  # sucht 30 s, dann Schluss
        self.assertLessEqual(self.uhr[0], 40)
        self.assertTrue(all(t <= 100 for t in self.zeitlimits))
        self.uhr[0], self.inhalt = 0.0, mail.SENT_SEP + "Hi Nils,\n\nPasst Samstag?\n\nBeste Grüße"
        self.assertEqual(mail.find_sent("Wochenende", fp, ende=100.0), "gefunden")
        self.inhalt = mail.SENT_SEP + "Ganz anderer Text"
        self.assertEqual(mail.find_sent("Wochenende", fp, ende=self.uhr[0] + 20), "abweichend")
        self.zeitlimits.clear()
        self.assertEqual(mail.find_sent("Wochenende", fp, ende=self.uhr[0] + 4), "offen")  # zu knapp: keine Suche
        self.assertEqual(self.zeitlimits, [])

    def test_mail_haengt_bestaetigung_offen(self):
        self.dauer = 500
        start = self.uhr[0]
        self.assertEqual(mail.find_sent("Wochenende", {"laenge": 0, "sha256": ""}, ende=start + 45), "offen")
        self.assertEqual(self.uhr[0], start + 45)  # das Zeitlimit des Aufrufs endet genau an der Frist


class RunAsZeitablauf(unittest.TestCase):
    def test_eigene_meldung_bei_zeitablauf(self):
        """Das echte run_as, nur subprocess.run ist ersetzt: osascript läuft nie."""
        with mock.patch.object(mail.subprocess, "run", side_effect=subprocess.TimeoutExpired("osascript", 30)):
            with self.assertRaises(SystemExit) as cm:
                mail.run_as("return 1", timeout=30, zeitablauf="Ob die Mail raus ist, ist offen.")
            self.assertEqual(cm.exception.code, "Ob die Mail raus ist, ist offen.")
            with self.assertRaises(SystemExit) as cm:
                mail.run_as("return 1", timeout=30)
            self.assertIn("nach 30 s nicht geantwortet", cm.exception.code)


def triage_lauf(cfg: dict, *argv: str, zeilen=()) -> tuple:
    """mail.py triage über main(): config.json aus einem Temp-Ordner (samt pruefe_config), ein Ersatz für run_as liefert
    zeilen als Datensätze und merkt sich seine Argumente. So fragt der Test nie das echte Mail ab. Ergebnis: (Exit-Code,
    Ausgabe, Fehlerausgabe, Argumente je Aufruf von run_as)."""
    aufrufe = []

    def ersatz(script, *args, **kw):
        aufrufe.append(args)
        return "".join(mail.FSEP.join(z) + mail.RSEP for z in zeilen)
    out, err, code = io.StringIO(), io.StringIO(), 0
    with tempfile.TemporaryDirectory() as tmp:
        pfad = Path(tmp) / "config.json"
        pfad.write_text(json.dumps({"mail": cfg}), encoding="utf-8")  # 7.0: Abschnitt mail
        with mock.patch.object(mail, "CONFIG_PATH", pfad), mock.patch.object(mail, "run_as", ersatz), \
                mock.patch.object(sys, "argv", ["mail.py", "triage", *argv]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                mail.main()
            except SystemExit as e:  # wie der Interpreter: ein Text geht nach stderr und ergibt Code 1
                if isinstance(e.code, str):
                    err.write(e.code)
                code = 1 if isinstance(e.code, str) else (e.code or 0)
    return code, out.getvalue(), err.getvalue(), aufrufe


class TriageGrenze(unittest.TestCase):
    def test_nur_markierte_mails_mit_obergrenze(self):
        zeilen = [("1", "2026-09-28 09:00", "Anna <a@x.de>", "Neu", "ungelesen", "n", "Privat"),
                  ("2", "2026-09-28 08:00", "newsletter@x.de", "Werbung", "ungelesen", "n", "Privat")]
        zeilen += [(str(10 + i), f"2026-08-{10 + i:02d} 10:00", "Bert <b@x.de>", f"Alt {i:02d}", "gelesen, markiert", "m",
                    "Privat") for i in range(12)]
        cfg = {"accounts": ["Privat"], "noise": ["newsletter"], "triage": {"max_markiert": 10}}
        code, out, err, _ = triage_lauf(cfg, "48", zeilen=zeilen)
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith(f"id | datum | absender | betreff | status  ({mail.DATA_NOTE})\n"
                                       "Konto Privat:\n"
                                       "1 | 2026-09-28 09:00 | Anna <a@x.de> | Neu | ungelesen\n"
                                       "21 | 2026-08-21 10:00 | Bert <b@x.de> | Alt 11 | gelesen, markiert\n"), out)
        self.assertNotIn("Werbung", out)
        self.assertIn("Alt 02", out)
        self.assertNotIn("Alt 01", out)
        self.assertTrue(out.endswith("[2 ältere markierte Mails ausgelassen, Grenze 10 je Konto in config.json unter "
                                     "triage.max_markiert]\n"), out)

    def test_ohne_eintrag_in_config_gilt_zehn(self):
        zeilen = [(str(i), f"2026-08-{10 + i:02d} 10:00", "Bert", f"Alt {i:02d}", "gelesen, markiert", "m", "Privat")
                  for i in range(11)]
        _code, out, _err, _ = triage_lauf({"accounts": ["Privat"]}, "48", zeilen=zeilen)
        self.assertIn("[1 ältere markierte Mails ausgelassen, Grenze 10", out)

    def test_nichts_neues(self):
        code, out, _err, aufrufe = triage_lauf({"accounts": ["Privat", "Firma"], "noise": ["NEWSLETTER"]}, zeilen=[
            ("2", "2026-09-28 08:00", "Newsletter@x.de", "Werbung", "ungelesen", "n", "Privat")])
        self.assertEqual((code, out), (0, "Nichts Neues in Privat, Firma: keine ungelesenen oder markierten Mails im "
                                          "Zeitraum.\n"))
        self.assertEqual(aufrufe, [("48", "2", "Privat", "Firma")])  # ohne Angabe 48 Stunden, Konten aus accounts

    def test_nach_konto_getrennt(self):
        """V6 Phase 4, T1: Ohne Profil kommen alle Konten aus accounts, je Konto ein Kopf in deren Reihenfolge, ein
        Konto ohne Treffer mit nichts Neues. Die Grenze für markierte Mails gilt je Konto."""
        zeilen = [("1", "2026-09-28 09:00", "Anna", "Privat neu", "ungelesen", "n", "Privat"),
                  ("2", "2026-09-28 10:00", "Chef", "Firma neu", "ungelesen", "n", "Firma"),
                  ("3", "2026-08-01 10:00", "Bert", "Firma alt", "gelesen, markiert", "m", "Firma"),
                  ("4", "2026-08-02 10:00", "Bert", "Firma alt 2", "gelesen, markiert", "m", "Firma"),
                  ("5", "2026-08-03 10:00", "Carla", "Privat alt", "gelesen, markiert", "m", "Privat")]
        cfg = {"accounts": ["Privat", "Firma", "Verein"], "triage": {"max_markiert": 1}}
        code, out, err, _ = triage_lauf(cfg, "48", zeilen=zeilen)
        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines()[1:], [
            "Konto Privat:",
            "1 | 2026-09-28 09:00 | Anna | Privat neu | ungelesen",
            "5 | 2026-08-03 10:00 | Carla | Privat alt | gelesen, markiert",
            "Konto Firma:",
            "2 | 2026-09-28 10:00 | Chef | Firma neu | ungelesen",
            "4 | 2026-08-02 10:00 | Bert | Firma alt 2 | gelesen, markiert",
            "Konto Verein: nichts Neues",
            "[1 ältere markierte Mails ausgelassen, Grenze 1 je Konto in config.json unter triage.max_markiert]"])

    def test_nicht_gefundenes_konto_ist_nicht_nichts_neues(self):
        """Etappe 2 von v7.3.0: Ein deaktiviertes oder umbenanntes Konto meldete nichts Neues, obwohl nie gesucht wurde.
        Jetzt steht es als nicht gefunden in der Ausgabe, auch nicht in der Zeile Nichts Neues."""
        cfg = {"accounts": ["Privat", "Firma", "Verein"]}
        code, out, err, _ = triage_lauf(cfg, "48", zeilen=[("#fehlt", "Verein")])
        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines(), [
            "Nichts Neues in Privat, Firma: keine ungelesenen oder markierten Mails im Zeitraum.",
            "Konto Verein: in Mail nicht gefunden (deaktiviert oder umbenannt?), Posteingang nicht durchsucht. Name in "
            "accounts der config.json mit Apple Mail abgleichen."])
        zeilen = [("#fehlt", "Firma"), ("1", "2026-09-28 09:00", "Anna", "Neu", "ungelesen", "n", "Privat")]
        _code, out, _err, _ = triage_lauf(cfg, "48", zeilen=zeilen)
        self.assertEqual(out.splitlines()[1:], [
            "Konto Privat:", "1 | 2026-09-28 09:00 | Anna | Neu | ungelesen",
            "Konto Firma: in Mail nicht gefunden (deaktiviert oder umbenannt?), Posteingang nicht durchsucht. Name in "
            "accounts der config.json mit Apple Mail abgleichen.",
            "Konto Verein: nichts Neues"])
        _code, out, _err, _ = triage_lauf({"accounts": ["Privat"]}, "48", zeilen=[("#fehlt", "Privat")])
        self.assertTrue(out.startswith("Nichts durchsucht: kein Konto aus accounts in Mail gefunden.\n"), out)
        self.assertNotIn("Nichts Neues", out)
        self.assertIn("my missing_accounts(boxes, acctNames)", mail.AS_TRIAGE)

    def test_ohne_konto_uebersprungen(self):
        """Ein Datensatz ohne Konto (leeres siebtes Feld) zählt als unerwartetes Format, statt unter keinem Konto zu
        landen."""
        zeilen = [("1", "2026-09-28 09:00", "Anna", "Ohne Konto", "ungelesen", "n", " "),
                  ("2", "2026-09-28 09:00", "Anna", "Mit Konto", "ungelesen", "n", "Privat")]
        _code, out, _err, _ = triage_lauf({"accounts": ["Privat"]}, "48", zeilen=zeilen)
        self.assertNotIn("Ohne Konto", out)
        self.assertIn("Mit Konto", out)
        self.assertIn("[1 Datensätze von Mail in unerwartetem Format übersprungen]", out)


class StilProbe(unittest.TestCase):
    def test_marke_im_fliesstext_schneidet_nicht_ab(self):
        body = ("Hi Tim,\n\ndie Firma GmbH bietet das an.\nWeiterer Text folgt hier.\n\nBeste Grüße\nLucas\n\n"
                "Max Muster\nSenior Consultant\nFirma GmbH & Co. KG\n")
        t = style_sample.cut_quotes_and_signature(body, {"signature": "Firma GmbH"})
        self.assertIn("Weiterer Text folgt hier.", t)
        self.assertTrue(t.endswith("Beste Grüße\nLucas"))
        self.assertNotIn("Senior Consultant", t)

    def test_grussformel_als_marke_bleibt_fuer_die_statistik(self):
        t = style_sample.cut_quotes_and_signature("Hi,\n\nText hier.\n\nBeste Grüße\nLucas\nFirma", {"signature": "Beste Grüße\nLucas"})
        self.assertTrue(t.endswith("Beste Grüße"))

    def test_profil_anhang_bleibt_beim_neuen_lauf(self):
        alt = "# Stil-Statistik\n\n## Gesamt\n\n| a | 1 |\n\n## Aus dem Profil\n\nBelege\n"
        self.assertEqual(style_sample.profil_anhang(alt), "\n## Aus dem Profil\n\nBelege\n")
        self.assertEqual(style_sample.profil_anhang("# Stil-Statistik\n\n## Gesamt\n"), "")

    def test_zeitraeume(self):
        self.assertEqual(style_sample.zeitraeume(365), [30, 90, 180, 365])
        self.assertEqual(style_sample.zeitraeume(60), [30, 60])
        self.assertEqual(style_sample.zeitraeume(30), [30])

    def test_sucht_erst_kurz_und_nur_bei_bedarf_weiter(self):
        aufrufe = []

        def ersatz(script, *args, timeout=90):
            aufrufe.append((script, args))
            if '& "|" &' in script:  # Datum und id
                n = 5 if int(args[0]) <= 30 * 86400 else 60
                return "".join(f"{i}|2026-09-{1 + i % 27:02d} 10:00\n" for i in range(n))
            return "".join(mail.FSEP.join([str(i), f"2026-09-{1 + i % 27:02d} 10:00", "Betreff", "Tim, ", "Text"]) + mail.RSEP
                           for i in range(60))
        alt = mail.run_as
        mail.run_as = ersatz
        try:
            mails = style_sample.fetch_sent({"account": "Firma"}, 40, 365)
        finally:
            mail.run_as = alt
        self.assertEqual(len(mails), 40)
        tage = [int(a[0]) // 86400 for s, a in aufrufe if '& "|" &' in s]
        self.assertEqual(tage, [30, 90])  # 180 und 365 Tage bleiben aus
        self.assertTrue(all(a[1] == "Firma" for _s, a in aufrufe))
        self.assertIn('account_boxes("sent", {acct})', aufrufe[0][0])
        self.assertIn("cc recipients of m", style_sample.TEXT_ZEILE)  # Namen aus Cc ersetzt die Stilprobe auch

    def test_konto_nicht_in_mail(self):
        """Etappe 2 von v7.3.0: Kennt Mail das Konto nicht, bricht die Stilprobe mit dem Grund ab, statt keine
        gesendeten Mails zu melden."""
        with mock.patch.object(mail, "run_as", lambda script, *args, **kw: "#fehlt"), \
                self.assertRaises(SystemExit) as cm:
            style_sample.fetch_sent({"account": "Verein"}, 2, 30)
        self.assertIn("Konto Verein: in Mail nicht gefunden (deaktiviert oder umbenannt?), Postfach Gesendet nicht "
                      "durchsucht.", str(cm.exception.code))
        self.assertIn('my missing_accounts(boxes, {acct})', style_sample.AS_SENT_RUN)

    def test_nur_vollstaendige_mails(self):
        """Review 21.10.2026: Trennzeichen in Betreff, Namen und Text ersetzt das AppleScript (no_sep). Datensätze ohne
        genau fünf Felder, id und Datum fallen weg und werden gezählt, ebenso kaputte Zeilen mit id und Datum."""
        def ersatz(script, *args, timeout=90, **kw):
            if '& "|" &' in script:
                return "1|2026-10-12 10:00\n2|2026-10-11 10:00\nx|kaputt\n"
            return (rec("1", "2026-10-12 10:00", "Betreff", "Tim, ", "Text")
                    + rec("2", "2026-10-11 10:00", "Betreff", "Tim, ", "Text", "zu viel")
                    + rec("3", "gestern", "Betreff", "Tim, ", "Text"))
        err = io.StringIO()
        with mock.patch.object(mail, "run_as", ersatz), contextlib.redirect_stderr(err):
            mails = style_sample.fetch_sent({"account": "Privat"}, 2, 30)
        self.assertEqual([m["id"] for m in mails], ["1"])
        self.assertIn("[2 Datensätze von Mail in unerwartetem Format übersprungen]", err.getvalue())
        for teil in ("my no_sep(subject of m)", "my no_sep(name of r)", "my no_sep(content of m)"):
            self.assertIn(teil, style_sample.TEXT_ZEILE)


# Erfundene Testdaten: id, Datum, Betreff, Namen aus An und Cc, Text. Adressen unter example.org, Nummern aus Nullen,
# einmal NFD (Ju + Trema), wie Mail es teils liefert, dazu ein geschütztes Leerzeichen in der Telefonnummer
STILPROBE = [
    ("1", "2026-10-12 10:00", "Unterlagen für Jürgen", "Jürgen Beispiel, Anna Quast, ",
     "Hallo Jürgen,\n\nanbei Annas Unterlagen. Jürgen bekommt eine Kopie.\n"
     "Ruf mich gern an unter 0170 0000000 oder +49 (0) 30 000 000-00.\n"
     "Meine IBAN: DE00 0000 0000 0000 0000 00, Kopie an anna@example.org.\n\nLiebe Grüße\nMax\n\n"
     "Am 10.10.2026 schrieb Jürgen Beispiel <juergen@example.org>:\n> Alte Nachricht"),
    ("2", "2026-10-11 10:00", "Treffen", "Ben Kruse, ",
     "Hallo zusammen,\n\nwir treffen uns bei Ben. Vielen Dank für die Unterlagen!\n"
     "Die Nummer 0170.000.0000 bitte nicht weitergeben.\n\nViele Grüße\nMax Muster"),
    ("3", "2026-10-10 10:00", "Termin", "",
     "Hi Clara und danke für die Rückmeldung!\n\nClaras Termin passt. Die Rückmeldung kam schnell.\n\nLiebe Grüße\nMax"),
]


class Anonymisierung(unittest.TestCase):
    """O6 (Prüfung 20.10.2026): Was style_sample.py in samples.md schreibt, hat keine Namen, Adressen und Nummern mehr,
    Anreden und Grüße bleiben für die Statistik lesbar. Mail ersetzt ein Ersatz für run_as, geschrieben wird nur in einen
    Temp-Ordner."""

    def stilprobe(self) -> tuple:
        def ersatz(script, *args, timeout=90, **kw):
            if '& "|" &' in script:  # erst id und Datum, dann der Text
                return "".join(f"{m[0]}|{m[1]}\n" for m in STILPROBE)
            return "".join(mail.FSEP.join(m) + mail.RSEP for m in STILPROBE)
        cfg = {"profiles": {"privat": {"account": "Privat", "from_name": "Max Muster", "signature": ""}}}
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(sys, "argv", ["style_sample.py", "--profile", "privat", "--n", "3"]), \
                    mock.patch.object(mail, "load_config", return_value=cfg), mock.patch.object(mail, "run_as", ersatz), \
                    mock.patch.object(style_sample, "KIT_DIR", Path(tmp)), contextlib.redirect_stdout(io.StringIO()):
                style_sample.main()
            ordner = Path(tmp) / "style" / "privat"
            return (ordner / "samples.md").read_text(encoding="utf-8"), (ordner / "stats.md").read_text(encoding="utf-8")

    def test_samples_ohne_namen_adressen_und_nummern(self):
        samples, _stats = self.stilprobe()
        for name in ("Jürgen", "Jürgen", "Beispiel", "Anna", "Quast", "Ben", "Kruse", "Clara", "Max", "Muster"):
            self.assertIsNone(re.search(rf"\b{name}", unicodedata.normalize("NFC", samples)), name)
            self.assertNotIn(name, samples)
        for rest in ("example.org", "0170", "000-00", "DE00", "000.0000", "Alte Nachricht"):
            self.assertNotIn(rest, samples)
        self.assertEqual(samples.count("[TEL]"), 4)  # geschütztes Leerzeichen, Klammern, IBAN, Punkte
        self.assertIn("Kopie an [MAIL].", samples)
        self.assertIn("Hallo [NAME],\n\nanbei [NAME] Unterlagen. [NAME] bekommt eine Kopie.", samples)  # Genitiv, NFD
        self.assertIn("wir treffen uns bei [NAME].", samples)
        self.assertIn("| Unterlagen für [NAME]", samples)  # Betreff

    def test_anreden_und_gruesse_bleiben_fuer_die_statistik(self):
        """Vorher wurde Liebe Grüße zu Liebe [NAME] und fehlte in der Statistik, Hallo zusammen wurde zu Hallo [NAME],
        und Wörter aus dem Rest einer Anrede wie Rückmeldung galten in allen Mails als Name."""
        samples, stats = self.stilprobe()
        self.assertEqual(samples.count("Liebe Grüße\n[NAME]"), 2)
        self.assertIn("Hallo zusammen,", samples)
        self.assertIn("Vielen Dank für die Unterlagen!", samples)
        self.assertIn("[NAME] Termin passt. Die Rückmeldung kam schnell.", samples)
        for zeile in ("- Liebe Grüße: 2", "- Viele Grüße: 1", "- Hallo zusammen: 1"):
            self.assertIn(zeile, stats)

    def test_namen_aus_der_anrede(self):
        for rest, name in (("Anna", "Anna"), ("Anna und Ben", "Anna und Ben"), ("Dr. Müller", "Dr. Müller"),
                           ("A. Schmidt", "A. Schmidt"), ("Anna. Kurze Frage", "Anna"), ("Anna? Kurz", "Anna"),
                           ("Anna und danke für die Unterlagen", "Anna"), ("zusammen", ""), ("", "")):
            self.assertEqual(style_sample.anrede_name(rest), name, rest)
        mails = [{"to_names": ["Team Nord"], "body": "Hallo Damen und Herren\nDanke!\nLiebe Grüße"}]
        self.assertEqual(style_sample.collect_names({}, mails), {"Team Nord", "Nord"})  # Grüße, Damen, Herren nicht

    def test_ein_platzhalter_je_name_zeilen_bleiben(self):
        self.assertEqual(style_sample.anonymise("mit Anna Quast.\nAnna\nQuast", {"Anna", "Quast"}),
                         "mit [NAME].\n[NAME]\n[NAME]")
        for text in ("Sehr geehrte Damen und Herren,", "Moin Moin", "Hi Team!"):
            self.assertEqual(style_sample.anonymise(text, set()), text)


def zusaetze_da() -> bool:
    """Kennt osacompile die Standard-Zusätze (current date)? In der Sandbox von Claude Code nicht, dort scheitert
    sonst jedes Kit-Skript. Die Syntaxprüfung läuft deshalb nur im Terminal."""
    if not shutil.which("osacompile"):
        return False
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run(["osacompile", "-o", str(Path(tmp) / "p.scpt")], input="set c to current date\n",
                           capture_output=True, text=True)
    return r.returncode == 0


TEXT_PROBE = "Hi,\n\nkurzer Text."
ABSENDER_PROBE = "Max Muster <max@example.org>"
ENTWURF_PROBE = rec("12", "Wochenende", "a@example.org", "c@example.org", "", ABSENDER_PROBE, "30", TEXT_PROBE)
# Kennzeichen je AppleScript, in dieser Reihenfolge geprüft, und die Antwort, die der Ersatz für run_as gibt. discard
# antwortet mit dem Betreff aus argv, siehe alle_skripte.
SKRIPTE = (
    ("send", "set ok to send", "true"),
    ("Antwort", "reply m with opening window",
     mail.FSEP.join(["13", "Re: X", "a@example.org", "c@example.org", "", "ok"])),
    ("Konto der Mail", "return name of account of mailbox of m", "Privat"),
    ("draft", "make new outgoing message", mail.FSEP.join(["12", "30", ABSENDER_PROBE, "a@example.org", "", ""])),
    ("discard", "delete d", None),
    ("Kopie löschen", "then delete m", ""),
    ("Kopie suchen", "drafts mailbox", mail.SENT_SEP + "15\n" + TEXT_PROBE),
    ("Gesendet prüfen", "sent mailbox whose subject is subj", mail.SENT_SEP + TEXT_PROBE),
    ("drafts", "get outgoing messages", ENTWURF_PROBE),
    ("Entwurf prüfen", "first outgoing message whose id is did", ENTWURF_PROBE),
    ("read", "set c to", mail.FSEP.join(["Betreff", "a@example.org", "Privat", "b@example.org", "", "", "",
                                         "2026-10-21 10:00"]) + mail.RSEP
     + "Content-Type: text/html; charset=utf-8\n\n<p>Hallo</p>\n"),
    ("Stilprobe Datum", '& "|" &', "12|2026-10-12 10:00\n"),
    ("Stilprobe Text", "on zeile(m)", rec("12", "2026-10-12 10:00", "Betreff", "Tim, ", "Text")),
    ("signatur", 'forType:"public.html"', "ok"),
    ("search", '"#weg"', rec("#weg", "konto")),
    ("Triage", "on triage_line(", rec("1", "2026-10-21 10:00", "a@example.org", "Betreff", "ungelesen", "n", "Privat")),
)


def alle_skripte() -> list:
    """(Name, AppleScript) für alles, was die Befehle an Mail schicken: search, read mit Text und HTML, draft neu und als
    Antwort, drafts, send samt Prüfung im Postfach Gesendet, discard samt automatischer Kopie, signatur --kopieren, die
    Stilprobe und die Triage. Ein Ersatz für run_as sammelt sie ein und antwortet passend, Mail wird nie gefragt.
    Review 21.10.2026: Der alte Syntaxtest rief draft mit text= auf, brach im Terminal ab und kompilierte nichts."""
    skripte = []

    def ersatz(script, *args, timeout=90, **kw):
        name, antwort = next(((n, a) for n, kennung, a in SKRIPTE if kennung in script), (None, None))
        if name is None:
            raise AssertionError(f"unbekanntes AppleScript: {script[:200]}")
        skripte.append((name, script))
        return "ok\n" + args[1] if name == "discard" else antwort

    with tempfile.TemporaryDirectory() as tmp:
        kit = Path(tmp).resolve()
        (kit / "style" / "arbeit").mkdir(parents=True)
        (kit / "style" / "arbeit" / "signatur.html").write_text("<p><b>Max Muster</b></p>", encoding="utf-8")
        cfg = {"accounts": ["Privat"], "default_profile": "privat",
               "profiles": {"privat": {"account": "Privat", "from_name": "Max Muster", "from_address": "max@example.org"},
                            "arbeit": {"account": "Firma", "signatur_html": "style/arbeit/signatur.html"}}}
        ns = argparse.Namespace
        neu = dict(text_file="entwurf.txt", reply_to=None, all=False, profile=None, to=["a@example.org"],
                   cc=["c@example.org"], subject="Wochenende", attach=None)
        with mock.patch.object(mail, "run_as", ersatz), mock.patch.object(mail, "mail_start", lambda: ""), \
                mock.patch.object(mail, "DRAFT_STATE", kit / "state.json"), mock.patch.object(mail, "KIT_DIR", kit), \
                mock.patch.object(mail.time, "sleep", lambda s: None), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            for box in ("inbox", "sent"):
                mail.cmd_search(cfg, ns(sender="x", subject="y", text="z", unread=True, days=3, limit=5, profile=None,
                                        mailbox=box))
            mail.cmd_triage(cfg, ns(stunden=48, profil=None))
            for html in (False, True):
                mail.cmd_read(cfg, ns(id=5, mailbox="inbox", profile=None, html=html, max_chars=0))
            for befehl, kw in ((mail.cmd_send, dict(id=12, yes=True)), (mail.cmd_discard, dict(id=12, ausfuehren=False))):
                (kit / "entwurf.txt").write_text(TEXT_PROBE, encoding="utf-8")
                mail.cmd_draft(cfg, ns(**neu))
                mail.cmd_drafts(cfg, ns())
                befehl(cfg, ns(**kw))
            (kit / "antwort.txt").write_text(TEXT_PROBE, encoding="utf-8")
            mail.cmd_draft(cfg, ns(**{**neu, "text_file": "antwort.txt", "reply_to": 5, "all": True, "to": None,
                                     "subject": None}))
            mail.cmd_signatur(cfg, ns(profile="arbeit", kopieren=True, lang=False, html=False))
            style_sample.fetch_sent(cfg["profiles"]["privat"], 1, 30)
    return skripte


class Skripte(unittest.TestCase):
    def test_jeder_befehl_liefert_seine_skripte(self):
        """Läuft auch in der Sandbox: Fehlt hier ein Skript, kompiliert auch AppleScriptSyntax es nicht."""
        namen = {name for name, _ in alle_skripte()}
        self.assertEqual(namen, {n for n, _k, _a in SKRIPTE})


@unittest.skipUnless(zusaetze_da(), "osacompile ohne Standard-Zusätze (Sandbox oder kein macOS), nur im Terminal prüfbar")
class AppleScriptSyntax(unittest.TestCase):
    """Alle AppleScripts kompilieren (nur Syntax, osacompile startet Mail nicht und fragt nichts ab)."""

    def kompiliert(self, script: str, name: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run(["osacompile", "-o", str(Path(tmp) / "x.scpt")], input=script, capture_output=True,
                               text=True)
        self.assertEqual(r.returncode, 0, f"{name}: {r.stderr}")

    def test_alle_skripte_kompilieren(self):
        for i, (name, script) in enumerate(alle_skripte()):
            with self.subTest(name=name, nummer=i + 1):
                self.kompiliert(script, name)


# Die früheren Umgebungsvariablen, die eine fremde config.json oder einen fremden Entwurfsstand unterschieben konnten
FREMDE_PFADE = {"MAIL_KIT_CONFIG": "/nirgends/config.json", "MAIL_KIT_STATE": "/nirgends/entwuerfe.json"}


def mail_kopie(tmp: Path, config_text: str) -> Path:
    """Kopie von mail.py mit eigener config.json daneben. mail.py liest config.json nur aus seinem eigenen Ordner."""
    kopie = tmp / "mail.py"
    kopie.write_text(Path(mail.__file__).read_text(encoding="utf-8"), encoding="utf-8")
    basis = Path(mail.__file__).with_name("kit_basis.py")  # gemeinsame Bausteine, mail.py importiert sie (V3, O8)
    (tmp / "kit_basis.py").write_text(basis.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp / "config.json").write_text(config_text, encoding="utf-8")
    return kopie


class Config(unittest.TestCase):
    def test_kaputte_config_klare_meldung(self):
        with tempfile.TemporaryDirectory() as tmp:
            kopie = mail_kopie(Path(tmp), "{kaputt")
            r = subprocess.run([sys.executable, "-B", str(kopie), "drafts"], capture_output=True, text=True, cwd=tmp)
        self.assertEqual(r.returncode, 1)
        self.assertIn("kein gültiges JSON", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_umgebung_legt_keine_andere_config_unter(self):
        """config.json liegt fest im Kit, der Entwurfsstand seit dem Review 21.10.2026 fest unter Application Support des
        Benutzers. Weder die alten Variablen noch HOME legen andere Pfade unter."""
        code = "import sys\nsys.path.insert(0, sys.argv[1])\nimport mail\nprint(mail.CONFIG_PATH)\nprint(mail.DRAFT_STATE)"
        stand = (Path(pwd.getpwuid(os.getuid()).pw_dir) / "Library" / "Application Support" / "Claude Kits"
                 / "communication-kit" / "entwuerfe.json")
        with tempfile.TemporaryDirectory() as tmp:
            kit = Path(tmp).resolve()  # macOS: /var -> /private/var
            kopie = mail_kopie(kit, "{kaputt")
            umgebung = {**os.environ, **FREMDE_PFADE, "HOME": str(kit)}
            pfade = subprocess.run([sys.executable, "-B", "-c", code, str(kit)], capture_output=True, text=True, cwd=kit,
                                   env=umgebung)
            lauf = subprocess.run([sys.executable, "-B", str(kopie), "drafts"], capture_output=True, text=True, cwd=kit,
                                  env=umgebung)
        self.assertEqual(pfade.stdout.splitlines(), [str(kit / "config.json"), str(stand)], pfade.stderr)
        self.assertIn("kein gültiges JSON", lauf.stderr)  # die kaputte config.json neben der Kopie, nicht die fremde

    def test_standard_ist_privat(self):
        """Seit V4 steht auch das Arbeitskonto unter accounts (Privat-Instanz über Apple Mail), Standard bleibt privat.
        Jedes Konto aus accounts gehört zu einem Profil, sonst fände draft keinen Absender. 7.0: geprüft an der Vorlage,
        die persönliche config.json liegt im Datenordner, nicht im Plugin."""
        with mock.patch.object(mail, "CONFIG_PATH", Path(mail.__file__).parent / "config.example.json"):
            cfg = mail.load_config()
        self.assertEqual(cfg["default_profile"], "privat")
        self.assertEqual(cfg["accounts"][0], cfg["profiles"]["privat"]["account"])
        konten = {p.get("account") for p in cfg["profiles"].values()}
        self.assertEqual([k for k in cfg["accounts"] if k not in konten], [])


class ConfigTypen(unittest.TestCase):
    """Prüfung 20.10.2026: Typfehler in config.json enden mit dem Schlüssel statt mit einem Traceback."""

    def meldung(self, cfg: dict) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "config.json"
            pfad.write_text(json.dumps({"mail": cfg}), encoding="utf-8")
            with mock.patch.object(mail, "CONFIG_PATH", pfad), self.assertRaises(SystemExit) as cm:
                mail.load_config()
        return str(cm.exception.code)

    def test_falscher_typ_nennt_den_schluessel(self):
        for cfg, schluessel in (({"accounts": "Privat"}, "accounts muss eine Liste"),
                                ({"accounts": ["Privat", 3]}, "accounts muss eine Liste"),
                                ({"default_profile": ["privat"]}, "default_profile muss ein Profilname"),
                                ({"default_profile": "fehlt"}, "default_profile fehlt steht nicht unter profiles"),
                                ({"profiles": ["privat"]}, "profiles muss ein Objekt"),
                                ({"profiles": {"privat": "Privat"}}, "profiles.privat muss ein Objekt"),
                                ({"profiles": {"privat": {"account": ["Privat"]}}}, "profiles.privat.account muss ein Text"),
                                ({"profiles": {"arbeit": {"signatur_html": 1}}}, "profiles.arbeit.signatur_html muss ein"),
                                ({"search": [90]}, "search muss ein Objekt"),
                                ({"search": {"default_days": "90"}}, "search.default_days muss eine ganze Zahl"),
                                ({"search": {"default_limit": True}}, "search.default_limit muss eine ganze Zahl"),
                                ({"anhang_ordner": "~/Downloads"}, "anhang_ordner muss eine Liste"),
                                ({"anhang_ordner": ["Downloads"]}, "anhang_ordner muss eine Liste")):
            self.assertIn(f"config.json: {schluessel}", self.meldung(cfg), cfg)

    def test_mehrere_fehler_in_einer_meldung(self):
        m = self.meldung({"accounts": "Privat", "anhang_ordner": "~"})
        self.assertIn("accounts muss", m)
        self.assertIn("anhang_ordner muss", m)
        self.assertTrue(m.endswith("Nichts geändert."))

    def test_gueltige_config_bleibt_wie_sie_ist(self):
        cfg = {"accounts": ["Privat"], "default_profile": "privat", "anhang_ordner": ["~/Downloads", "/tmp/office"],
               "profiles": {"privat": {"account": "Privat", "signature": "", "_hinweis": ["frei"]}},
               "search": {"default_days": 90, "default_limit": 50}, "noise": ["newsletter"],
               "triage": {"max_markiert": 0}}
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "config.json"
            pfad.write_text(json.dumps({"mail": cfg, "kalender": {"default_calendar": "Privat"}}), encoding="utf-8")
            with mock.patch.object(mail, "CONFIG_PATH", pfad):
                self.assertEqual(mail.load_config(), cfg)  # nur der Abschnitt mail

    def test_ohne_abschnitt_mail(self):
        """7.0: eine config.json mit Abschnitten. Liegt mail flach oder fehlt der Abschnitt, bricht der Befehl ab."""
        for cfg in ({"accounts": ["Privat"]}, {"mail": ["Privat"]}):
            self.assertEqual(self.meldung_roh(cfg),
                             "config.json: Abschnitt mail fehlt oder ist kein Objekt. Nichts geändert.")

    def meldung_roh(self, cfg: dict) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "config.json"
            pfad.write_text(json.dumps(cfg), encoding="utf-8")
            with mock.patch.object(mail, "CONFIG_PATH", pfad), self.assertRaises(SystemExit) as cm:
                mail.load_config()
        return str(cm.exception.code)

    def test_ohne_traceback_im_aufruf(self):
        """Als Befehl: Meldung mit Schlüssel, Code 1, kein Traceback. signatur ohne --kopieren fragt Mail nie."""
        with tempfile.TemporaryDirectory() as tmp:
            kopie = mail_kopie(Path(tmp), json.dumps({"mail": {"accounts": ["Privat"], "anhang_ordner": "~/Downloads"}}))
            r = subprocess.run([sys.executable, "-B", str(kopie), "signatur"], capture_output=True, text=True, cwd=tmp)
        self.assertEqual(r.returncode, 1)
        self.assertIn("config.json: anhang_ordner muss eine Liste", r.stderr)
        self.assertNotIn("Traceback", r.stderr)


class Profile(unittest.TestCase):
    def test_profil_zum_konto(self):
        cfg = {"profiles": {"arbeit": {"account": "Firma"}, "privat": {"account": "Privat"}}}
        self.assertEqual(mail.profile_for_account(cfg, "Privat")[0], "privat")
        self.assertEqual(mail.profile_for_account(cfg, "Unbekannt"), ("", {}))


class Triage(unittest.TestCase):
    """mail.py triage, bis V3.1.2 mail_triage.sh: dieselben Prüfungen und dieselbe Ausgabe, Mail ersetzt ein Ersatz für
    run_as (triage_lauf)."""

    def abbruch(self, *argv: str) -> tuple:
        """(Exit-Code, Fehlerausgabe), wenn triage schon beim Lesen der Argumente abbricht, vor config.json und Mail."""
        err = io.StringIO()
        with mock.patch.object(sys, "argv", ["mail.py", "triage", *argv]), contextlib.redirect_stderr(err), \
                mock.patch.object(mail, "load_config", side_effect=AssertionError(f"kein Abbruch bei {argv}")), \
                self.assertRaises(SystemExit) as cm:
            mail.main()
        return cm.exception.code, err.getvalue()

    def test_falsche_stundenzahl_klare_meldung(self):
        """Falscher Aufruf endet mit 2 (Prüfung 20.10.2026). Bricht vor config.json und Mail ab, auch wenn nur das
        Profil dasteht."""
        for argv in (["morgen"], ["-3"], [""], ["privat"]):
            code, err = self.abbruch(*argv)
            self.assertEqual(code, 2, argv)
            self.assertIn("Stunden als ganze Zahl", err, argv)

    def test_obergrenze_und_zu_viele_argumente(self):
        """Prüfung 20.10.2026: höchstens ein Jahr wie bei den markierten Mails, mehr als zwei Argumente sind ein
        Tippfehler. Beides bricht vor Mail ab."""
        for argv, meldung in ((["8761"], "Höchstens 8760 Stunden"), (["99999999999999999999"], "Höchstens 8760 Stunden"),
                              (["48", "privat", "mehr"], "mehr")):
            code, err = self.abbruch(*argv)
            self.assertEqual(code, 2, argv)
            self.assertIn(meldung, err, argv)
        zeilen = [("1", "2026-09-28 09:00", "Anna <a@x.de>", "Neu", "ungelesen", "n", "Privat")]
        for eingabe, stunden in (("8760", "8760"), ("048", "48")):  # an AppleScript ohne führende Null
            code, _out, err, aufrufe = triage_lauf({"accounts": ["Privat"]}, eingabe, zeilen=zeilen)
            self.assertEqual(code, 0, err)
            self.assertEqual(aufrufe, [(stunden, "1", "Privat")])

    def test_leere_konten_und_typfehler_vor_mail(self):
        """Prüfung 20.10.2026: Leere accounts hießen alle Konten, auch das Exchange-Postfach. Typfehler enden mit dem
        Schlüssel (pruefe_config) statt mit einem Traceback, ein Text in noise blendete sonst fast alles aus. Mail wird
        nie gefragt."""
        faelle = (({"accounts": []}, [], 1, "accounts ist leer"),
                  ({}, [], 1, "accounts ist leer"),
                  ({"accounts": "Privat"}, [], 1, "accounts muss eine Liste"),
                  ({"accounts": ["Privat"], "noise": "newsletter"}, [], 1, "noise muss eine Liste"),
                  ({"accounts": ["Privat"], "triage": [10]}, [], 1, "triage muss ein Objekt sein"),
                  ({"accounts": ["Privat"], "triage": {"max_markiert": "10"}}, [], 1,
                   "triage.max_markiert muss eine ganze Zahl ab 0 sein"),
                  ({"profiles": {"privat": {"from_name": "Max"}}}, ["privat"], 1, "Profil privat hat kein account"),
                  ({"profiles": {"privat": "Privat"}}, ["privat"], 1, "profiles.privat muss ein Objekt sein"),
                  # Review 21.10.2026: unbekanntes Profil und das Arbeitskonto sind ein falscher Aufruf (Code 2)
                  ({"accounts": ["Privat"], "profiles": {}}, ["privat"], 2, "Unbekanntes Profil: privat"),
                  (KONTEN, ["arbeit"], 2, "Profil arbeit (Konto Firma) gilt hier nicht"))
        for cfg, profil, code, meldung in faelle:
            ist, _out, err, aufrufe = triage_lauf(cfg, "48", *profil)
            self.assertEqual(ist, code, cfg)
            self.assertIn(meldung, err, cfg)
            self.assertEqual(aufrufe, [], cfg)
        _code, _out, err, aufrufe = triage_lauf(KONTEN, "72", "privat")
        self.assertEqual(aufrufe, [("72", "1", "Privat")], err)

    def test_gefaelschte_zeilen_und_unsichtbare_zeichen(self):
        """Review 21.10.2026: Trennzeichen in einem fremden Betreff ersetzt schon das AppleScript (no_sep). Was trotzdem
        nicht genau sieben Felder mit id, Datum, Herkunft und Konto hat, fällt weg und wird gezählt. Richtungs- und
        Nullbreitenzeichen und Terminalfolgen im Betreff erscheinen nicht."""
        zeilen = [("1", "2026-09-28 09:00", "Anna <a@x.de>", "Rechnung‮ fdp.exe​ \x1b[31mrot", "ungelesen", "n",
                   "Privat"),
                  ("99", "2026-09-28 10:00", "chef@x.de", "Dringend", "ungelesen", "n", "Privat", "zu viel"),
                  ("abc", "2026-09-28 10:00", "chef@x.de", "Dringend", "ungelesen", "n", "Privat"),
                  ("98", "gestern", "chef@x.de", "Dringend", "ungelesen", "n", "Privat"),
                  ("97", "2026-09-28 10:00", "chef@x.de", "Dringend", "ungelesen", "x", "Privat")]
        code, out, err, _ = triage_lauf({"accounts": ["Privat"]}, "48", zeilen=zeilen)
        self.assertEqual(code, 0, err)
        self.assertIn("1 | 2026-09-28 09:00 | Anna <a@x.de> | Rechnung fdp.exe rot | ungelesen", out)
        self.assertNotIn("Dringend", out)
        self.assertIn("[4 Datensätze von Mail in unerwartetem Format übersprungen]", out)
        for zeichen in ("‮", "​", "\x1b"):
            self.assertNotIn(zeichen, out)
        zeile = mail.AS_TRIAGE.split("on triage_line(", 1)[1].split("end triage_line", 1)[0]
        for teil in ("my no_sep(sender of m)", "my no_sep(subject of m)", "my no_sep(kontoTxt)"):
            self.assertIn(teil, zeile)

    def test_umgebung_legt_keine_andere_config_unter(self):
        """config.json liegt fest neben mail.py, auch für triage, die früheren Variablen legen keine andere unter. Die
        Kopie bricht am Typfehler ihrer eigenen config.json ab, bevor sie Mail fragt."""
        with tempfile.TemporaryDirectory() as tmp:
            kopie = mail_kopie(Path(tmp), json.dumps({"mail": {"accounts": ["Privat"], "triage": [10]}}))
            r = subprocess.run([sys.executable, "-B", str(kopie), "triage", "48"], capture_output=True, text=True,
                               cwd=tmp, env={**os.environ, **FREMDE_PFADE})
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("config.json: triage muss ein Objekt sein", r.stderr)  # sonst: config.json fehlt: /nirgends/...
        self.assertNotIn("Traceback", r.stderr)


SIG = ('<p><b>Max Muster</b> | Senior Consultant</p>\n'
       '<p><b>Firma GmbH &amp; Co. KG</b><br><i>www.example.com</i><br>'
       'Mobil 0000 | E-Mail <a href="mailto:max@example.com">max@example.com</a></p>\n'
       '<p>Sitz Musterstadt<br>Geschäftsführer: A | B</p>\n')
FOOT = '<p>Musterstr. 1, 12345 Musterstadt<br>Geschäftsführer: C | D</p>\n'


class Signatur(unittest.TestCase):
    """mail.py signatur: Fassung für Apple Mail aus signatur.html, ohne Mail und ohne echte Zwischenablage."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kit = Path(self.tmp.name).resolve()
        (self.kit / "style" / "arbeit").mkdir(parents=True)
        (self.kit / "style" / "arbeit" / "signatur.html").write_text(SIG, encoding="utf-8")
        (self.kit / "style" / "arbeit" / "signatur_footer.html").write_text(FOOT, encoding="utf-8")
        self.cfg = {"profiles": {"arbeit": {"account": "Firma", "signatur_html": "style/arbeit/signatur.html",
                                            "signatur_footer_html": "style/arbeit/signatur_footer.html"}}}
        self.alt = {n: getattr(mail, n) for n in ("KIT_DIR", "run_as")}
        mail.KIT_DIR = self.kit
        self.aufrufe = []
        self.antwort = "ok"

        def ersatz(script, *args, timeout=90):
            self.aufrufe.append((script, args))
            return self.antwort
        mail.run_as = ersatz

    def tearDown(self):
        for n, v in self.alt.items():
            setattr(mail, n, v)
        self.tmp.cleanup()

    def lauf(self, *argv: str) -> str:
        a = argparse.Namespace(profile="arbeit", kopieren="--kopieren" in argv, html="--html" in argv,
                               lang="--lang" in argv)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            mail.cmd_signatur(self.cfg, a)
        return out.getvalue()

    def fehler(self, quelle: str) -> str:
        with self.assertRaises(SystemExit) as cm:
            mail.signatur_parsen(quelle)
        return str(cm.exception.code)

    def test_text_mit_gleichen_zeilen(self):
        self.assertEqual(mail.signatur_text(mail.signatur_parsen(SIG)),
                         "Max Muster | Senior Consultant\n\nFirma GmbH & Co. KG\nwww.example.com\n"
                         "Mobil 0000 | E-Mail max@example.com\n\nSitz Musterstadt\nGeschäftsführer: A | B")

    def test_apple_mail_markup_ohne_schrift_und_farbe(self):
        h = mail.signatur_apple_html(mail.signatur_parsen(SIG))
        self.assertEqual(h, '<div><b>Max Muster</b> | Senior Consultant</div><div><br></div>'
                            '<div><b>Firma GmbH &amp; Co. KG</b></div><div><i>www.example.com</i></div>'
                            '<div>Mobil 0000 | E-Mail <a href="mailto:max@example.com">max@example.com</a></div>'
                            '<div><br></div><div>Sitz Musterstadt</div><div>Geschäftsführer: A | B</div>')
        for verboten in ("style", "font", "color", "<img", "<span", "<p"):
            self.assertNotIn(verboten, h)

    def test_ohne_kopieren_nur_anzeigen(self):
        out = self.lauf()
        self.assertIn("Mobil 0000 | E-Mail max@example.com", out)
        self.assertEqual(self.aufrufe, [])

    def test_kopieren_legt_html_und_text_in_die_zwischenablage(self):
        out = self.lauf("--kopieren")
        script, args = self.aufrufe[0]
        self.assertIn('forType:"public.html"', script)
        self.assertTrue(script.startswith(mail.AS_USE_OBJC))
        self.assertEqual(args, (mail.signatur_apple_html(mail.signatur_parsen(SIG)),
                                mail.signatur_text(mail.signatur_parsen(SIG))))
        self.assertIn("Konto Firma, Signatur Firma wählen", out)
        self.assertIn("kurze Fassung", out)
        self.assertIn("Standardschrift", out)

    def test_kurz_ist_standard_lang_haengt_den_footer_an(self):
        kurz = mail.signatur_text(mail.signatur_lesen(self.cfg, "arbeit"))
        lang = mail.signatur_text(mail.signatur_lesen(self.cfg, "arbeit", lang=True))
        self.assertNotIn("Musterstr.", kurz)
        self.assertEqual(lang, kurz + "\n\nMusterstr. 1, 12345 Musterstadt\nGeschäftsführer: C | D")
        out = self.lauf("--lang", "--kopieren")
        self.assertIn("Musterstr. 1", self.aufrufe[0][1][1])
        self.assertIn("lange Fassung", out)
        self.assertIn("Signatur Firma lang wählen", out)

    def test_lang_ohne_footer_klare_meldung(self):
        del self.cfg["profiles"]["arbeit"]["signatur_footer_html"]
        self.assertTrue(self.lauf())  # kurz geht weiter
        with self.assertRaises(SystemExit) as cm:
            self.lauf("--lang")
        self.assertIn("kein signatur_footer_html", str(cm.exception.code))

    def test_zwischenablage_scheitert_klar(self):
        self.antwort = "fehler"
        with self.assertRaises(SystemExit) as cm:
            self.lauf("--kopieren")
        self.assertIn("nicht gesetzt", str(cm.exception.code))

    def test_anzeige_ohne_telefonnummer(self):
        mobil = "0151 " + "23456789"  # erfunden, in zwei Teilen: keine echte Nummer im Kit
        self.assertEqual(mail.ohne_nummern(f"Mobil {mobil} | E-Mail a@b.de"), "Mobil [Nummer] | E-Mail a@b.de")
        self.assertEqual(mail.ohne_nummern("Tel. +49 (6196) 123-456"), "Tel. [Nummer]")
        for bleibt in ("Str. 8, 65824 Schwalbach", "HRA 3685", "Mobil 0000"):
            self.assertEqual(mail.ohne_nummern(bleibt), bleibt)

    def test_html_ausgabe(self):
        self.assertTrue(self.lauf("--html").startswith("<div><b>Max Muster</b>"))

    def test_nur_erlaubte_tags_und_attribute(self):
        self.assertIn("<span>", self.fehler('<p><span>x</span></p>'))
        self.assertIn("<img>", self.fehler('<p><img src="logo.png"></p>'))
        self.assertIn("Attribut an <p>", self.fehler('<p style="color:red">x</p>'))
        self.assertIn("Link ohne mailto", self.fehler('<p><a href="javascript:x">x</a></p>'))

    def test_kaputtes_html_faellt_auf(self):
        # so sah eine Zeile nach einem Tippfehler aus: aus <a href wurde < href
        self.assertIn("</a> ohne Anfang", self.fehler('<p>E-Mail < href="mailto:a@b.de">a@b.de</a></p>'))
        self.assertIn("vor dem Ende von <b>", self.fehler('<p><b>x</p>'))
        self.assertIn("nicht geschlossen", self.fehler('<p><b>x</b>'))
        self.assertIn("außerhalb von <p>", self.fehler('x<p>y</p>'))
        self.assertIn("leer", self.fehler('<p> </p>'))

    def test_nur_dateien_unter_style(self):
        self.cfg["profiles"]["arbeit"]["signatur_html"] = "../anderswo.html"
        with self.assertRaises(SystemExit) as cm:
            mail.signatur_lesen(self.cfg, "arbeit")
        self.assertIn("unter style/", str(cm.exception.code))

    @unittest.skipUnless(zusaetze_da(), "osacompile ohne Standard-Zusätze (Sandbox oder kein macOS)")
    def test_applescript_kompiliert(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run(["osacompile", "-o", str(Path(tmp) / "x.scpt")],
                               input=mail.AS_USE_OBJC + mail.AS_SIG_CLIP, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    @unittest.skipUnless((Path(mail.__file__).parent / "style" / "arbeit" / "signatur.html").exists(),
                         "signatur.html ist persönlich und nicht versioniert")
    def test_echte_signatur_ohne_symbole_mit_marker(self):
        # V6 (R2): ohne feste Texte aus der echten Signatur, geprüft wird die lokale Datei gegen sich selbst
        mail.KIT_DIR = Path(mail.__file__).resolve().parent
        cfg = mail.load_config()
        kurz = mail.signatur_text(mail.signatur_lesen(cfg, "arbeit"))
        lang = mail.signatur_text(mail.signatur_lesen(cfg, "arbeit", lang=True))
        zeilen = [z.strip() for z in kurz.splitlines() if z.strip()]
        self.assertTrue(zeilen)
        for text in (kurz, lang):
            for zeile in zeilen:  # jede Zeile der kurzen Fassung genau einmal, auch Marker und Firmenname
                self.assertEqual(text.count(zeile), 1, zeile[:20])
            self.assertFalse([z for z in text if unicodedata.category(z) == "So"], "Symbole in der Signatur")
        self.assertTrue(lang.startswith(kurz + "\n\n"))  # kurz ist Standard, der Footer kommt nur in lang dazu
        self.assertGreater(len(lang), len(kurz) + 2)


class Aufruf(unittest.TestCase):
    """V3 Review 20.10.2026: Rückfragen hängen am Wortlaut der Regeln, Abkürzungen und die Form mit = dürfen sie nicht
    umgehen (etwa draft --att x oder --attach=x neben der freien Regel draft *)."""

    def abbruch(self, modul, *argv: str) -> int:
        """Exit-Code, wenn das Skript schon beim Lesen der Argumente abbricht, sonst schlägt der Test fehl."""
        with mock.patch.object(sys, "argv", [modul.__name__ + ".py", *argv]), \
                mock.patch.object(mail, "load_config", side_effect=AssertionError(f"kein Abbruch bei {argv}")), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                modul.main()
        return cm.exception.code

    def test_keine_abkuerzungen(self):
        for argv in (("draft", "--att", "/tmp/x.pdf", "--text", "x"), ("send", "7", "--y"), ("search", "--fro", "x"),
                     ("signatur", "--kop")):
            self.assertEqual(self.abbruch(mail, *argv), 2, argv)

    def test_schreibende_schalter_nur_direkt_hinter_dem_skript(self):
        """--attach und --ausfuehren gelten nur direkt hinter dem Skript, an anderer Stelle bricht das Skript ab."""
        for argv in (("draft", "--to", "a@b.de", "--text", "x", "--attach", "/tmp/x.pdf"),
                     ("draft", "--attach=/tmp/x.pdf", "--to", "a@b.de"), ("discard", "7", "--ausfuehren")):
            self.assertIn("steht nur direkt hinter dem Skript", str(self.abbruch(mail, *argv)), argv)

    def test_stilproben_nur_unter_style_im_kit(self):
        stil = (Path(mail.__file__).parent / "style").resolve()
        for ziel in ("/tmp/fremd", "../anderswo", str(stil) + "-kopie", "style/../.."):
            with mock.patch.object(sys, "argv", ["style_sample.py", "--profile", "privat", "--out", ziel]), \
                    mock.patch.object(mail, "CONFIG_PATH", Path(mail.__file__).parent / "config.example.json"), \
                    mock.patch.object(style_sample, "fetch_sent", side_effect=AssertionError(f"kein Abbruch bei {ziel}")):
                with self.assertRaises(SystemExit) as cm:
                    style_sample.main()
            self.assertIn("muss unter", str(cm.exception.code), ziel)


    def test_stilprobe_mit_n_und_days_ab_1(self):
        """Review 21.10.2026: --n 0 endete mit IndexError, negative Werte suchten nichts. Jetzt Code 2 vor Mail."""
        for argv in (["--n", "0"], ["--n", "-3"], ["--days", "0"]):
            with mock.patch.object(sys, "argv", ["style_sample.py", "--profile", "privat", *argv]), \
                    mock.patch.object(mail, "load_config", side_effect=AssertionError(f"kein Abbruch bei {argv}")), \
                    contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit) as cm:
                style_sample.main()
            self.assertEqual(cm.exception.code, 2, argv)
            self.assertIn("--n und --days ab 1", err.getvalue())

    def test_stilprobe_nur_mit_profil_und_konto(self):
        """Prüfung 20.10.2026: Ohne Konto läse die Stilprobe die gesendeten Mails aller Konten, auch der Arbeit."""
        for argv, cfg, meldung in ((["--profile", "privat"], {"profiles": {"privat": {"account": ""}}}, "hat kein account"),
                                   ([], {"profiles": {"privat": {"account": "Privat"}}}, "Kein Profil")):
            with mock.patch.object(sys, "argv", ["style_sample.py", *argv]), \
                    mock.patch.object(mail, "load_config", return_value=cfg), \
                    mock.patch.object(style_sample, "fetch_sent", side_effect=AssertionError("Mail gefragt")):
                with self.assertRaises(SystemExit) as cm:
                    style_sample.main()
            self.assertIn(meldung, str(cm.exception.code))


if __name__ == "__main__":
    unittest.main()
