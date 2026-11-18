"""Tests für reminders.py ohne EventKit und ohne Apple Erinnerungen. Ersatzmodule aus ersatz_eventkit.py.

Aufruf im Kit-Ordner: python3 -B -m unittest discover tests
"""
import contextlib
import datetime as dt
import io
import unittest

from ersatz_eventkit import KIT, D, EXCHANGE, Erinnerung, KitTest, Liste, Quelle

import reminders  # noqa: E402


class Reminders(KitTest):
    def setUp(self):
        super().setUp()
        self.aufgaben, self.einkauf, self.tagebuch = Liste("Aufgaben"), Liste("Einkaufsliste"), Liste("Tagebuch")
        self.s = self.store(kalender=[self.aufgaben, self.einkauf, self.tagebuch])
        self.heute = dt.datetime.combine(dt.date.today(), dt.time(0, 0))

    def erinnerung(self, titel, liste=None, tage=None, uhrzeit=None, **kw):
        faellig = None
        if tage is not None:
            faellig = self.heute + dt.timedelta(days=tage)
            if uhrzeit:
                faellig = faellig.replace(hour=uhrzeit[0], minute=uhrzeit[1])
        r = Erinnerung(titel=titel, liste=liste or self.aufgaben, faellig=faellig, mit_zeit=bool(uhrzeit), **kw)
        self.s.erinnerungen.append(r)
        return r

    def lauf_alles(self, *argv) -> str:
        """Ausgabe, Fehlerausgabe und Exit-Meldung in einem Text, auch was aufruf_falsch auf stderr schreibt."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                reminders.main(list(argv))
            except SystemExit as e:
                return out.getvalue() + err.getvalue() + str(e.code)
        return out.getvalue() + err.getvalue()

    def test_sortierung_nach_uhrzeit(self):
        self.erinnerung("Abends", tage=2, uhrzeit=(18, 0))
        self.erinnerung("Morgens", tage=2, uhrzeit=(9, 0))
        self.erinnerung("Ohne Uhrzeit", tage=2)
        self.erinnerung("Morgen", tage=1, uhrzeit=(20, 0))
        out, fehler = self.lauf(reminders.main, "list")
        self.assertIsNone(fehler)
        zeilen = [z.strip() for z in out.splitlines() if z.strip().startswith("- ")]  # ohne Hinweis und Listenname
        self.assertEqual([z.rsplit("  ", 1)[1] for z in zeilen], ["Morgen", "Ohne Uhrzeit", "Morgens", "Abends"])
        self.assertIn(", 9 Uhr  Morgens", out)

    def test_gleichnamige_listen_lesen_beide(self):
        zweite = Liste("Aufgaben", EXCHANGE)
        self.s.kalender.append(zweite)
        self.erinnerung("Privat", tage=1)
        self.erinnerung("Arbeit", liste=zweite, tage=1)
        out, _fehler = self.lauf(reminders.main, "list")
        self.assertIn("Aufgaben (iCloud):", out)
        self.assertIn("Aufgaben (Firma):", out)

    def test_gleichnamige_listen_schreiben_bricht_ab(self):
        """Prüfung 20.10.2026: Eine Liste in zwei Konten ist mehrdeutig, Code 2 wie bei allen Kits (vorher 1)."""
        self.s.kalender.append(Liste("Aufgaben", EXCHANGE))
        meldung = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(meldung):
            with self.assertRaises(SystemExit) as ende:
                reminders.main(["add", "Aufgaben", "Reifen bestellen"])
        self.assertEqual(ende.exception.code, 2)
        self.assertIn("Liste 'Aufgaben' gibt es 2 Mal (Konten: iCloud, Firma)", meldung.getvalue())
        self.assertEqual(self.s.gespeichert, [])

    def test_timeout_meldet_fehler(self):
        self.s.antwortet = False
        _out, fehler = self.lauf(reminders.main, "list")
        self.assertIn("nicht geladen", fehler)

    def test_ohne_lesbare_liste_nichts_durchsucht(self):
        """Etappe 2 von v7.3.0: Ohne eine lesbare Liste meldete list keine offenen Erinnerungen, obwohl es nichts
        gelesen hatte."""
        self.s.kalender.clear()
        out, fehler = self.lauf(reminders.main, "list")
        self.assertIsNone(fehler)
        self.assertTrue(out.startswith("Keine Erinnerungsliste lesbar"), out)
        self.assertNotIn("Keine offenen Erinnerungen", out)

    def test_nur_offene(self):
        self.erinnerung("Erledigt", tage=1, erledigt=True)
        self.erinnerung("Offen", tage=1)
        out, _fehler = self.lauf(reminders.main, "list")
        self.assertIn("Offen", out)
        self.assertNotIn("Erledigt", out)

    def test_keine_erinnerungen_ohne_doppelten_punkt(self):
        out, fehler = self.lauf(reminders.main, "list", "--days", "7")
        self.assertIsNone(fehler)
        self.assertTrue(out.strip().startswith("Keine offenen Erinnerungen mit Frist bis "))
        self.assertFalse(out.strip().endswith(".."))

    def test_ueberfaellig_heute_und_ohne_frist(self):
        self.erinnerung("Alt", tage=-3)
        self.erinnerung("Jetzt", tage=0, uhrzeit=(18, 0))
        self.erinnerung("Irgendwann")
        out, _fehler = self.lauf(reminders.main, "list")
        self.assertIn("ÜBERFÄLLIG", out)
        self.assertIn("HEUTE", out)
        self.assertNotIn("Irgendwann", out)
        out, _fehler = self.lauf(reminders.main, "list", "--all")
        self.assertIn("- Irgendwann", out)

    def test_deutsches_datum_ohne_traceback(self):
        _out, fehler = self.lauf(reminders.main, "add", "Aufgaben", "Reifen", "30.09.2026")
        self.assertIn("JJJJ-MM-TT", fehler)
        _out, fehler = self.lauf(reminders.main, "add", "Aufgaben", "Reifen", "2026-09-30", "18 Uhr")
        self.assertIn("HH:MM", fehler)
        self.assertEqual(self.s.gespeichert, [])

    def test_mit_frist_und_alarm(self):
        out, fehler = self.lauf(reminders.main, "add", "Aufgaben", "Reifen bestellen", "2026-09-30", "18:00",
                                "--notes", "Winterreifen")
        self.assertIsNone(fehler)
        r = self.s.gespeichert[0][0]
        self.assertEqual((r.calendar(), r.notiz, len(r.alarme)), (self.aufgaben, "Winterreifen", 1))
        self.assertEqual(reminders.due_of(r), (D("2026-09-30 18:00"), True))
        self.assertIn("Angelegt in Aufgaben: Reifen bestellen, fällig Mi 30.09., 18 Uhr", out)

    def test_mehrere_fristen_in_einem_aufruf(self):
        """V3.1.2, Befund 13: je Frist eine Erinnerung, Uhrzeit wahlweise je Frist, Notiz für alle, eine Ausgabe."""
        out, fehler = self.lauf(reminders.main, "add", "Aufgaben", "Reifen", "2026-09-30", "18:00", "2026-10-07",
                                "2026-10-14", "9:30", "--notes", "Winter")
        self.assertIsNone(fehler)
        neu = [r for r, _ in self.s.gespeichert]
        self.assertEqual([reminders.due_of(r) for r in neu],
                         [(D("2026-09-30 18:00"), True), (D("2026-10-07 00:00"), False), (D("2026-10-14 09:30"), True)])
        self.assertEqual([(r.title(), r.calendar(), r.notiz, len(r.alarme)) for r in neu],
                         [("Reifen", self.aufgaben, "Winter", 1), ("Reifen", self.aufgaben, "Winter", 0),
                          ("Reifen", self.aufgaben, "Winter", 1)])
        self.assertEqual(out.splitlines(), ["Angelegt in Aufgaben: 3 Erinnerungen Reifen",
                                            "  - fällig Mi 30.09., 18 Uhr", "  - fällig Mi 07.10.",
                                            "  - fällig Mi 14.10., 9:30 Uhr"])

    def test_mehrere_fristen_geteilte_liste_direkt(self):
        """V3.1.3 (Lucas 09.11.2026): auch in geteilten Listen ohne Vorschau, ein Aufruf für alle Fristen."""
        out, fehler = self.lauf(reminders.main, "add", "Einkaufsliste", "Milch", "2026-09-30", "2026-10-01", "8:00")
        self.assertIsNone(fehler)
        self.assertEqual(len(self.s.gespeichert), 2)
        self.assertTrue(out.startswith("Angelegt in Einkaufsliste: 2 Erinnerungen Milch\n"))
        self.assertIn("  - fällig Mi 30.09.\n  - fällig Do 01.10., 8 Uhr\n", out)

    def test_dublette_je_frist_legt_keine_an(self):
        """Wie im Kalender: Steht der Titel mit dieser Frist schon offen in der Liste, legt add keine Frist an."""
        self.s.erinnerungen += [Erinnerung(titel="reifen ", liste=self.aufgaben, faellig=D("2026-10-07 00:00"),
                                           mit_zeit=False),
                                Erinnerung(titel="Reifen", liste=self.aufgaben, faellig=D("2026-10-14 09:30")),
                                Erinnerung(titel="Reifen", liste=self.aufgaben, faellig=D("2026-09-30 18:00"),
                                           erledigt=True),
                                Erinnerung(titel="Reifen", liste=self.einkauf, faellig=D("2026-10-21 00:00"),
                                           mit_zeit=False)]
        _out, fehler = self.lauf(reminders.main, "add", "Aufgaben", "Reifen", "2026-09-30", "18:00", "2026-10-07",
                                 "2026-10-14", "9:30")
        self.assertEqual(fehler, "In Aufgaben steht schon offen: Reifen, Mi 07.10. und Mi 14.10., 9:30 Uhr. Ohne diese "
                                 "Frist erneut aufrufen. Nichts angelegt.")
        self.assertEqual(self.s.gespeichert, [])
        # erledigt, andere Uhrzeit, andere Liste: keine Dublette
        for argv in (("2026-09-30", "18:00"), ("2026-10-07", "8:00"), ("2026-10-14",), ("2026-10-21",)):
            _out, fehler = self.lauf(reminders.main, "add", "Aufgaben", "Reifen", *argv)
            self.assertIsNone(fehler, argv)
        self.assertEqual(len(self.s.gespeichert), 4)
        self.erinnerung("Brot")  # ohne Frist keine Prüfung, wie vor V3.1.2
        _out, fehler = self.lauf(reminders.main, "add", "Aufgaben", "Brot")
        self.assertIsNone(fehler)
        _out, fehler = self.lauf(reminders.main, "add", "Aufgaben", "Brot", "2026-10-07")
        self.assertIsNone(fehler)

    def test_mehrere_fristen_alles_geprueft_bevor_etwas_entsteht(self):
        """Zeitumstellung, Format und doppelte Fristen je Frist, dann ist nichts angelegt und nichts gelesen."""
        faelle = ((("2026-10-24", "2026-10-25", "02:30"), "So 25.10., 2:30 Uhr gibt es zweimal"),
                  (("2026-03-28", "2026-03-29", "02:30"), "So 29.03., 2:30 Uhr gibt es nicht"),
                  (("2026-09-30", "18:00", "19:00"), "Datum '19:00' nicht lesbar"),
                  (("2026-09-30", "2026-10-01", "18 Uhr"), "Uhrzeit '18 Uhr' nicht lesbar"),
                  (("2026-09-30", "30.10.2026"), "Datum '30.10.2026' nicht lesbar"))
        for worte, text in faelle:
            _out, fehler = self.lauf(reminders.main, "add", "Aufgaben", "Reifen", *worte)
            self.assertIn(text, fehler, worte)
            self.assertTrue(fehler.endswith("Nichts angelegt."), worte)
        for worte in (("2026-09-30", "2026-09-30"), ("2026-09-30", "8:00", "2026-09-30", "08:00"),
                      ("2026-09-30", "", "")):
            meldung = self.lauf_alles("add", "Aufgaben", "Reifen", *worte)
            self.assertTrue(meldung.endswith("2"), worte)
        self.assertIn("Frist Mi 30.09. steht zweimal im Aufruf. Nichts angelegt.",
                      self.lauf_alles("add", "Aufgaben", "Reifen", "2026-09-30", "2026-09-30"))
        self.assertEqual((self.s.gespeichert, self.s.abfragen), ([], []))

    def test_speicherfehler_nennt_angelegte_und_fehlende(self):
        echt = self.s.saveReminder_commit_error_
        self.s.saveReminder_commit_error_ = lambda r, c, e: (False, "voll") if len(self.s.gespeichert) == 1 \
            else echt(r, c, e)
        _out, fehler = self.lauf(reminders.main, "add", "Aufgaben", "Reifen", "2026-09-30", "2026-10-07", "18:00",
                                 "2026-10-14")
        self.assertEqual(fehler, "Fehler beim Speichern: voll. Schon angelegt: Mi 30.09. Nicht angelegt: Mi 07.10., "
                                 "18 Uhr und Mi 14.10.")
        self.s.gespeichert.clear()
        self.s.saveReminder_commit_error_ = lambda r, c, e: (False, "voll")
        _out, fehler = self.lauf(reminders.main, "add", "Aufgaben", "Brot")
        self.assertEqual(fehler, "Fehler beim Speichern: voll. Nichts angelegt.")

    def test_eigene_liste_schreibt_direkt(self):
        out, fehler = self.lauf(reminders.main, "add", "Aufgaben", "Brot kaufen")
        self.assertIsNone(fehler)
        self.assertEqual(self.s.gespeichert[0][0].calendar(), self.aufgaben)
        self.assertIn("Angelegt in Aufgaben: Brot kaufen", out)

    def test_geteilte_liste_legt_direkt_an(self):
        """V3.1.3 (Lucas 09.11.2026): geteilte Listen ohne Vorschau, --ausfuehren wirkt nicht mehr, stört aber nicht."""
        out, fehler = self.lauf(reminders.main, "add", "Einkaufsliste", "Milch", "2026-09-30")
        self.assertIsNone(fehler)
        self.assertEqual(self.s.gespeichert[0][0].calendar(), self.einkauf)
        self.assertEqual(out.strip(), "Angelegt in Einkaufsliste: Milch, fällig Mi 30.09.")
        out, fehler = self.lauf(reminders.main, "--ausfuehren", "add", "Einkaufsliste", "Käse")
        self.assertIsNone(fehler)
        self.assertEqual(len(self.s.gespeichert), 2)
        self.assertIn("Angelegt in Einkaufsliste: Käse", out)

    def test_alter_schalter_und_abkuerzungen_gelten_nicht(self):
        for schalter in ("--geteilt", "--aus", "--ausfuehre"):
            _out, fehler = self.lauf(reminders.main, "add", "Einkaufsliste", "Milch", schalter)
            self.assertEqual(fehler, 2, schalter)
        for argv in (("add", "Einkaufsliste", "Milch", "--ausfuehren"), ("done", "--ausfuehren", "Milch")):
            _out, fehler = self.lauf(reminders.main, *argv)  # V3.1: nur direkt hinter dem Skript
            self.assertIn("--ausfuehren steht nur direkt hinter dem Skript", fehler, argv)
        self.assertEqual(self.s.gespeichert, [])

    def test_ausgeschlossene_liste(self):
        self.erinnerung("Geheim", liste=self.tagebuch, tage=1)
        out, _fehler = self.lauf(reminders.main, "list")
        self.assertNotIn("Geheim", out)
        out, _fehler = self.lauf(reminders.main, "lists")  # Review 20.10.2026: auch nicht als Name in der Übersicht
        self.assertNotIn("Tagebuch", out)
        self.assertIn("Einkaufsliste", out)
        # Review 21.10.2026: gesperrt meldet sich wie unbekannt, "ist gesperrt" bestätigte den Ausschluss
        for argv in (("--ausfuehren", "add", "{}", "X"), ("done", "--liste", "{}", "Geheim")):
            _out, gesperrt = self.lauf(reminders.main, *(a.format("Tagebuch") for a in argv))
            _out, unbekannt = self.lauf(reminders.main, *(a.format("Gibt es nicht") for a in argv))
            self.assertEqual(gesperrt, unbekannt.replace("Gibt es nicht", "Tagebuch"), argv)
            self.assertEqual(gesperrt, "Liste 'Tagebuch' nicht gefunden oder gesperrt. Vorhanden: Aufgaben, "
                                       "Einkaufsliste")
        _out, fehler = self.lauf(reminders.main, "--ausfuehren", "done", "Geheim")
        self.assertIn("Nichts gefunden", fehler)

    def test_ausschluss_und_geteilte_listen_unabhaengig_von_schreibweise(self):
        """Prüfung 20.10.2026: Listennamen zählen ohne Groß- und Kleinschreibung und Unicode-Form."""
        self.config(reminders={"excluded_lists": ["tagebuch"], "geteilte_listen": ["EINKAUFSLISTE"]})
        self.erinnerung("Geheim", liste=self.tagebuch, tage=1)
        out, _fehler = self.lauf(reminders.main, "list")
        self.assertNotIn("Geheim", out)
        out, _fehler = self.lauf(reminders.main, "lists")
        self.assertNotIn("Tagebuch", out)
        self.assertIn("(geteilt)", out)
        self.assertNotIn("passen zu keiner Liste", out)
        out, fehler = self.lauf(reminders.main, "add", "einkaufsliste", "Milch")
        self.assertIsNone(fehler)
        self.assertIn("Angelegt in Einkaufsliste: Milch", out)
        _out, fehler = self.lauf(reminders.main, "--ausfuehren", "add", "TAGEBUCH", "X")
        self.assertIn("gesperrt", fehler)
        self.config(reminders={"excluded_lists": ["Gibt es nicht"], "geteilte_listen": []})
        out, _fehler = self.lauf(reminders.main, "lists")
        self.assertIn("1 Einträge in config.json", out)

    def test_steuerzeichen_und_datenhinweis(self):
        """Prüfung 20.10.2026: Titel mit Steuerzeichen landen bereinigt im Transkript, dazu der Datenhinweis."""
        self.erinnerung("Rot\x1b[31m‮", tage=1)
        out, _fehler = self.lauf(reminders.main, "list")
        self.assertIn(reminders.HINWEIS, out)
        self.assertIn("Rot", out)
        self.assertNotIn("\x1b", out)
        self.assertNotIn("‮", out)

    def test_leere_auswahl_liest_nichts(self):
        self.s.kalender = [self.tagebuch]
        self.erinnerung("Geheim", liste=self.tagebuch, tage=1)
        out, _fehler = self.lauf(reminders.main, "list")
        self.assertNotIn("Geheim", out)
        self.assertEqual(self.s.abfragen, [])

    def test_done_hakt_in_eigenen_listen_direkt_ab(self):
        """Probe 21.10.2026 (Lucas): Abhaken in eigenen Listen ohne Vorschau und ohne Rückfrage, wie add."""
        r = self.erinnerung("Brot kaufen", tage=1)
        out, fehler = self.lauf(reminders.main, "done", "Brot kaufen")
        self.assertIsNone(fehler)
        self.assertTrue(r.isCompleted())
        self.assertEqual(out.strip(), "Erledigt: Brot kaufen (Aufgaben)")
        r2 = self.erinnerung("Reifen", tage=1)
        out, fehler = self.lauf(reminders.main, "--ausfuehren", "done", "Reifen")  # mit Schalter geht es weiter
        self.assertIsNone(fehler)
        self.assertTrue(r2.isCompleted())

    def test_done_in_geteilten_listen_direkt(self):
        """V3.1.3 (Lucas 09.11.2026): Abhaken auch in geteilten Listen ohne Vorschau und ohne Rückfrage."""
        r = self.erinnerung("Milch", liste=self.einkauf, tage=1)
        out, fehler = self.lauf(reminders.main, "done", "Milch")
        self.assertIsNone(fehler)
        self.assertTrue(r.isCompleted())
        self.assertEqual(out.strip(), "Erledigt: Milch (Einkaufsliste)")

    def test_done_mehrdeutig(self):
        a, b = self.erinnerung("Brot", tage=1), self.erinnerung("Brot", liste=self.einkauf, tage=1)
        for zusatz in ((), ("--ausfuehren",)):
            out, fehler = self.lauf(reminders.main, *zusatz, "done", "Brot")
            self.assertEqual(fehler, 2)
            self.assertIn("Nicht eindeutig", out)
        self.assertFalse(a.isCompleted() or b.isCompleted())

    def test_done_mit_titel_wie_list_ihn_zeigt(self):
        """Review 21.10.2026: done verglich roh, list zeigt bereinigt. Zwei Leerzeichen, eines am Ende oder ein
        unsichtbares Zeichen ließen sich nie abhaken, done endete immer wieder mit Code 2."""
        r = self.erinnerung("Brot  kaufen ", tage=1)
        r2 = self.erinnerung("Reifen​ wechseln", tage=1)
        out, _fehler = self.lauf(reminders.main, "list")
        self.assertIn("  Brot kaufen\n", out)  # so zeigt list die Titel
        self.assertIn("  Reifen wechseln\n", out)
        for titel, eintrag in (("Brot kaufen", r), ("reifen wechseln", r2)):
            out, fehler = self.lauf(reminders.main, "done", titel)
            self.assertIsNone(fehler, titel)
            self.assertTrue(eintrag.isCompleted(), titel)
        self.assertEqual(out.strip(), "Erledigt: Reifen wechseln (Aufgaben)")

    def test_done_mit_liste_bei_gleichem_titel(self):
        """Review 21.10.2026: Gleicher Titel in zwei Listen blieb ohne Ausweg mehrdeutig. --liste grenzt ein."""
        a, b = self.erinnerung("Butter", tage=1), self.erinnerung("Butter", liste=self.einkauf, tage=1)
        out, fehler = self.lauf(reminders.main, "done", "Butter")
        self.assertEqual(fehler, 2)
        self.assertIn("gleiche Titel in zwei Listen mit --liste eingrenzen", out)
        out, fehler = self.lauf(reminders.main, "done", "--liste", "aufgaben", "Butter")
        self.assertIsNone(fehler)
        self.assertEqual(out.strip(), "Erledigt: Butter (Aufgaben)")
        self.assertTrue(a.isCompleted())
        self.assertFalse(b.isCompleted())
        for argv in (("list", "--liste", "Aufgaben"), ("add", "Aufgaben", "X", "--liste", "Aufgaben"),
                     ("done", "--liste", " ", "Butter")):
            _out, fehler = self.lauf(reminders.main, *argv)
            self.assertEqual(fehler, 2, argv)
        self.assertFalse(b.isCompleted())
        out, fehler = self.lauf(reminders.main, "done", "Butter", "--liste", "Einkaufsliste")  # geteilt: auch direkt
        self.assertIsNone(fehler)
        self.assertTrue(b.isCompleted())

    def test_listen_und_kontonamen_bereinigt(self):
        """Review 21.10.2026: Listen- und Kontonamen kamen roh in die Ausgabe (lists, Vorhanden, Konten, Vorschau,
        Kandidaten, Erledigt). Jetzt ohne Terminalsteuerfolgen und Richtungszeichen."""
        boese = Quelle("Konto\x1b[31m‮", 2)
        haus, aufgaben2 = Liste("Haus\x1b[2J‮", boese), Liste("Aufgaben", boese)
        self.s.kalender += [haus, Liste("Familie‮", boese), aufgaben2]
        self.config(reminders={"excluded_lists": ["Tagebuch"], "geteilte_listen": ["Familie"]})
        self.erinnerung("Brot", liste=haus, tage=1)
        self.erinnerung("Brot", tage=1)
        self.erinnerung("Milch", liste=aufgaben2, tage=1)
        ausgaben = {argv: self.lauf_alles(*argv) for argv in (
            ("lists",), ("add", "Gibt es nicht", "X"), ("add", "Aufgaben", "X"), ("add", "Familie", "Milch"),
            ("done", "Brot"), ("done", "--liste", "Haus", "Brot"), ("list",))}
        for argv, text in ausgaben.items():
            self.assertNotIn("\x1b", text, argv)
            self.assertNotIn("‮", text, argv)
        self.assertRegex(ausgaben[("lists",)], r"Haus +Konto\n")
        self.assertRegex(ausgaben[("lists",)], r"Familie +Konto  \(geteilt\)\n")
        self.assertIn("Vorhanden: Aufgaben, Einkaufsliste, Familie, Haus", ausgaben[("add", "Gibt es nicht", "X")])
        self.assertIn("(Konten: iCloud, Konto)", ausgaben[("add", "Aufgaben", "X")])
        self.assertIn("Angelegt in Familie: Milch", ausgaben[("add", "Familie", "Milch")])
        self.assertIn("  Haus: Brot\n", ausgaben[("done", "Brot")])
        self.assertIn("Erledigt: Brot (Haus)", ausgaben[("done", "--liste", "Haus", "Brot")])
        self.assertIn("Aufgaben (Konto):", ausgaben[("list",)])  # gleiche Namen mit Konto
        # gespeichert haben nur add in Familie (geteilt, direkt seit V3.1.3) und das Abhaken mit --liste
        self.assertEqual([g[0].calendar().title() for g in self.s.gespeichert], ["Familie‮", "Haus\x1b[2J‮"])

    def test_days_nur_von_0_bis_3650(self):
        """Review 21.10.2026: --days 99999999 endete mit OverflowError, negative Werte liefen still."""
        for argv in (("list", "--days", "99999999"), ("list", "--days", "-1"), ("list", "--days", "3651"),
                     ("list", "--days", "-1", "--verlauf", "Aufgaben")):
            _out, fehler = self.lauf(reminders.main, *argv)
            self.assertEqual(fehler, 2, argv)
        self.assertEqual(self.s.abfragen, [])  # nichts gelesen
        for tage in ("0", "3650"):
            _out, fehler = self.lauf(reminders.main, "list", "--days", tage)
            self.assertIsNone(fehler, tage)

    def test_falscher_aufruf_endet_mit_code_2(self):
        """Review 20.10.2026: 0 ok, 1 Fehler und nichts geändert, 2 Aufruf falsch, wie bei allen Kits."""
        for argv in (("add", "Aufgaben"), ("add", "Aufgaben", " "), ("done",), ("loeschen", "X")):
            _out, fehler = self.lauf(reminders.main, *argv)
            self.assertEqual(fehler, 2, argv)
        self.assertEqual(self.s.gespeichert, [])
        out, fehler = self.lauf(reminders.main, "add", "--", "Aufgaben", "-Titel mit Strich")
        self.assertIsNone(fehler)
        self.assertIn("Angelegt in Aufgaben: -Titel mit Strich", out)

    def test_config_text_statt_liste(self):
        self.config(reminders={"excluded_lists": "Tagebuch"})
        _out, fehler = self.lauf(reminders.main, "list")
        self.assertIn("excluded_lists muss eine Liste", fehler)

    # ---------- list --verlauf (V3 Phase 4a, Aufgaben-Screening im Tagesstart) ----------

    def vor(self, tage):
        return self.heute - dt.timedelta(days=tage)

    def t(self, d):
        return reminders.tag_j(d, self.heute)  # mit Jahreszahl, wenn ein Testdatum über den Jahreswechsel fällt

    def test_verlauf_zeigt_die_liste_ganz_mit_anlage_und_notiz(self):
        self.erinnerung("Arbeit: Tracker", tage=30, angelegt=self.vor(1), notiz="Mail Max, 20.10.")
        self.erinnerung("Privat: Jacke", angelegt=self.vor(1))
        self.erinnerung("Milch", liste=self.einkauf, tage=0)
        out, fehler = self.lauf(reminders.main, "list", "--verlauf", "Aufgaben")
        self.assertIsNone(fehler)
        self.assertTrue(out.startswith(reminders.HINWEIS))
        self.assertIn("Aufgaben, Verlauf: 2 offen, 0 erledigt seit " + self.t(self.vor(14)), out)
        self.assertIn(f"- {self.t(self.heute + dt.timedelta(days=30))}  Arbeit: Tracker  (angelegt "
                      f"{self.t(self.vor(1))}, Notiz: Mail Max, 20.10.)", out)
        self.assertIn(f"- ohne Frist  Privat: Jacke  (angelegt {self.t(self.vor(1))})", out)
        self.assertNotIn("Milch", out)  # andere Listen nur mit --days
        self.assertNotIn("liegt seit", out)

    def test_verlauf_liegt_ab_sechs_werktagen_nur_ohne_frist(self):
        self.erinnerung("Neu ohne Frist", angelegt=self.vor(1))
        self.erinnerung("Alt ohne Frist", angelegt=self.vor(14))  # zwei Wochen sind immer 10 Werktage
        self.erinnerung("Alt mit Frist", tage=3, angelegt=self.vor(14))
        out, _fehler = self.lauf(reminders.main, "list", "--verlauf", "Aufgaben")
        zeilen = [z.strip() for z in out.splitlines() if z.strip().startswith("- ")]
        self.assertEqual([z.split("  ")[1] for z in zeilen], ["Alt mit Frist", "Alt ohne Frist", "Neu ohne Frist"])
        self.assertIn("liegt seit 10 Werktagen", zeilen[1])
        self.assertNotIn("liegt", zeilen[0] + zeilen[2])

    def test_verlauf_erledigte_der_letzten_14_tage(self):
        self.erinnerung("Privat: Frisch erledigt", erledigt=True, erledigt_am=self.vor(2), notiz="Termin 18.10.")
        self.erinnerung("Gestern erledigt", erledigt=True, erledigt_am=self.vor(1))
        self.erinnerung("Alt erledigt", erledigt=True, erledigt_am=self.vor(20))
        self.erinnerung("Erledigt im Einkauf", liste=self.einkauf, erledigt=True, erledigt_am=self.vor(1))
        out, fehler = self.lauf(reminders.main, "list", "--verlauf", "Aufgaben")
        self.assertIsNone(fehler)
        self.assertIn("Aufgaben, Verlauf: 0 offen, 2 erledigt seit", out)
        zeilen = [z.strip() for z in out.splitlines() if z.strip().startswith("- ")]
        self.assertEqual(zeilen, [f"- erledigt {self.t(self.vor(1))}  Gestern erledigt",  # neueste zuerst
                                  f"- erledigt {self.t(self.vor(2))}  Privat: Frisch erledigt  (Notiz: Termin 18.10.)"])
        self.assertIn("keine offenen Einträge", out)

    def test_abgehakt_erscheint_im_verlauf_als_erledigt(self):
        """Abgleich am Folgetag: was Lucas abhakt, steht danach unter erledigt und nicht mehr offen."""
        self.erinnerung("Privat: Testaufgabe", tage=-1, angelegt=self.vor(1), notiz="Termin 19.10.")
        out, _fehler = self.lauf(reminders.main, "list", "--verlauf", "Aufgaben")
        self.assertIn("- ÜBERFÄLLIG ", out)
        _out, fehler = self.lauf(reminders.main, "--ausfuehren", "done", "Privat: Testaufgabe")
        self.assertIsNone(fehler)
        out, _fehler = self.lauf(reminders.main, "list", "--verlauf", "Aufgaben")
        self.assertIn("0 offen, 1 erledigt", out)
        self.assertIn(f"- erledigt {self.t(dt.date.today())}  Privat: Testaufgabe  (Notiz: Termin 19.10.)", out)

    def test_verlauf_mit_days_zeigt_andere_listen_nur_mit_frist(self):
        self.erinnerung("Aufgabe heute", tage=0, angelegt=self.vor(1))
        self.erinnerung("Milch heute", liste=self.einkauf, tage=0)
        self.erinnerung("Butter morgen", liste=self.einkauf, tage=1)
        self.erinnerung("Brot ohne Frist", liste=self.einkauf)
        out, fehler = self.lauf(reminders.main, "list", "--days", "0", "--verlauf", "Aufgaben")
        self.assertIsNone(fehler)
        self.assertIn("Andere Listen, fällig bis " + reminders.tag(self.heute) + ":\nEinkaufsliste:\n  - HEUTE ", out)
        self.assertIn("Milch heute", out)
        self.assertNotIn("Butter morgen", out)
        self.assertNotIn("Brot ohne Frist", out)
        self.assertEqual(out.count("Aufgabe heute"), 1)  # die Verlaufsliste nicht noch einmal
        out, _fehler = self.lauf(reminders.main, "list", "--days", "0", "--verlauf", "Aufgaben", "--all")
        self.assertIn("Brot ohne Frist", out)
        self.s.erinnerungen = [r for r in self.s.erinnerungen if r.calendar() is self.aufgaben]
        out, _fehler = self.lauf(reminders.main, "list", "--days", "0", "--verlauf", "Aufgaben")
        self.assertIn("Andere Listen: nichts fällig bis " + reminders.tag(self.heute), out)

    def test_verlauf_gleichnamige_listen_beide_mit_konto(self):
        zweite = Liste("Aufgaben", EXCHANGE)
        self.s.kalender.append(zweite)
        self.erinnerung("Privat", angelegt=self.vor(1))
        self.erinnerung("Arbeit", liste=zweite, angelegt=self.vor(1))
        out, fehler = self.lauf(reminders.main, "list", "--verlauf", "aufgaben")  # Schreibweise egal
        self.assertIsNone(fehler)
        self.assertIn("Aufgaben (iCloud), Verlauf: 1 offen", out)
        self.assertIn("Aufgaben (Firma), Verlauf: 1 offen", out)

    def test_verlauf_gesperrte_und_unbekannte_liste(self):
        """Gesperrt und unbekannt melden sich gleich, damit ein geratener Name nicht verrät, dass es die Liste gibt."""
        self.erinnerung("Geheim", liste=self.tagebuch, angelegt=self.vor(1))
        meldung = "' nicht gefunden oder gesperrt, nichts gelesen. Vorhanden: Aufgaben, Einkaufsliste"
        out, fehler = self.lauf(reminders.main, "list", "--verlauf", "tagebuch")
        self.assertEqual(fehler, "Liste 'tagebuch" + meldung)
        self.assertNotIn("Geheim", out)
        self.assertEqual(self.s.abfragen, [])  # nichts gelesen
        _out, fehler = self.lauf(reminders.main, "list", "--verlauf", "Gibt es nicht")
        self.assertEqual(fehler, "Liste 'Gibt es nicht" + meldung)
        self.assertNotIn("Tagebuch", fehler)  # gesperrte Listen auch nicht als Name

    def test_verlauf_grenzen(self):
        self.erinnerung("Eine Woche alt", angelegt=self.vor(7))  # immer genau 5 Werktage, noch nicht liegen geblieben
        self.erinnerung("Vor 14 Tagen erledigt", erledigt=True, erledigt_am=self.vor(14))
        self.erinnerung("Vor 15 Tagen erledigt", erledigt=True, erledigt_am=self.vor(15))
        self.erinnerung("Geheim heute", liste=self.tagebuch, tage=0)
        out, fehler = self.lauf(reminders.main, "list", "--days", "0", "--verlauf", "Aufgaben")
        self.assertIsNone(fehler)
        self.assertNotIn("liegt seit", next(z for z in out.splitlines() if "Eine Woche alt" in z))
        self.assertIn("Vor 14 Tagen erledigt", out)
        self.assertNotIn("Vor 15 Tagen erledigt", out)
        self.assertNotIn("Geheim", out)
        self.assertNotIn("Tagebuch", out)

    def test_unsichtbare_zeichen_und_nummern_mit_punkten(self):
        """Review 20.10.2026: Nullbreite trennt keine Nummer mehr ab, Punkte auch nicht, ein Datum bleibt stehen. Der
        Verbinder U+200D auch nicht (V3.1.2: sauber nimmt ihn anders als kit_basis.ohne_formatzeichen mit heraus)."""
        self.erinnerung("Arbeit: Konto", tage=1,
                        notiz="Tel 0176​1234\N{ZERO WIDTH JOINER}5678, Kto 1234.5678.90, am 20.10.2026")
        boese = Liste("Einkauf\x1b[2J​")
        self.s.kalender.append(boese)
        self.erinnerung("Brot", liste=boese, tage=0)
        out, fehler = self.lauf(reminders.main, "list", "--days", "0", "--verlauf", "Aufgaben")
        self.assertIsNone(fehler)
        self.assertIn("Notiz: Tel [Nummer], Kto [Nummer], am 20.10.2026)", out)
        self.assertIn("\nEinkauf:\n", out)
        self.assertNotIn("\x1b", out)
        self.assertNotIn("​", out)
        self.assertNotIn("\N{ZERO WIDTH JOINER}", out)

    def test_andere_listen_mit_jahreszahl_aus_dem_vorjahr(self):
        alt = self.heute.replace(year=self.heute.year - 1, day=1)
        self.erinnerung("Alte Rechnung", liste=self.einkauf, tage=(alt - self.heute).days)
        out, _fehler = self.lauf(reminders.main, "list", "--days", "0", "--verlauf", "Aufgaben")
        self.assertIn(f"- ÜBERFÄLLIG {reminders.tag(alt)}{alt.year}  Alte Rechnung", out)

    def test_verlauf_notiz_nur_mit_vorsatz_und_ohne_nummern(self):
        """Am 20.10.2026 stand in einer eigenen Notiz eine Kontonummer: ohne Vorsatz keine Notiz, Nummern maskiert."""
        self.erinnerung("KFZ-Steuer", tage=5, notiz="K110 9667 0359 DE36 5900 0000 0059 0010 54")
        self.erinnerung("privat: Steuer zahlen", tage=5,
                        notiz="Mail Amt, 19.10., DE36 5900 0000 0059 0010 54, Tel +49 6221 123456, Az 2026-10-20")
        out, fehler = self.lauf(reminders.main, "list", "--verlauf", "Aufgaben")
        self.assertIsNone(fehler)
        self.assertNotIn("5900", out)
        self.assertNotIn("6221", out)
        self.assertNotIn("Notiz", next(z for z in out.splitlines() if "KFZ-Steuer" in z))
        self.assertIn("Notiz: Mail Amt, 19.10., [Nummer], Tel [Nummer], Az [Nummer])", out)

    def test_verlauf_mit_jahreszahl_aus_anderen_jahren(self):
        alt = self.heute.replace(year=self.heute.year - 1, month=10, day=24)
        self.erinnerung("Uralt", angelegt=alt)
        out, _fehler = self.lauf(reminders.main, "list", "--verlauf", "Aufgaben")
        self.assertIn(f"(angelegt {reminders.tag(alt)}{alt.year}, liegt seit ", out)

    def test_verlauf_notiz_bereinigt_und_gekuerzt(self):
        self.erinnerung("Arbeit: Lang", angelegt=self.vor(1),
                        notiz="Mail\x1b[31m von Max\nzweite Zeile " + "wort " * 30)
        self.erinnerung("Ohne")  # ohne Anlagedatum und Notiz
        out, fehler = self.lauf(reminders.main, "list", "--verlauf", "Aufgaben")
        self.assertIsNone(fehler)
        notiz = next(z for z in out.splitlines() if "Lang" in z).split("Notiz: ", 1)[1]
        self.assertTrue(notiz.startswith("Mail von Max zweite Zeile wort"))
        self.assertTrue(notiz.endswith(" [gekürzt])"))
        self.assertLessEqual(len(notiz) - len(" [gekürzt])"), reminders.NOTIZ_MAX)
        self.assertNotIn("\x1b", out)
        self.assertNotIn("…", out)
        self.assertTrue(out.rstrip().endswith("- ohne Frist  Ohne"))  # ohne Anlagedatum zuletzt, ohne Klammer

    def test_erledigte_ohne_listen_lesen_nichts(self):
        self.erinnerung("Erledigt", erledigt=True, erledigt_am=self.vor(1))
        self.assertEqual(reminders.fetch(self.s, [], set(), erledigt_seit=self.vor(3)), [])
        self.assertEqual(self.s.abfragen, [])

    def test_verlauf_nur_bei_list_und_list_ohne_listenwort(self):
        for argv in (("done", "X", "--verlauf", "Aufgaben"), ("add", "Aufgaben", "X", "--verlauf", "Aufgaben"),
                     ("list", "Aufgaben"), ("lists", "Aufgaben"), ("list", "--verlauf", " ")):
            _out, fehler = self.lauf(reminders.main, *argv)
            self.assertEqual(fehler, 2, argv)
        self.assertEqual(self.s.gespeichert, [])

    def test_ohne_verlauf_bleibt_list_wie_bisher(self):
        self.erinnerung("In zehn Tagen", tage=10, angelegt=self.vor(30), notiz="geheim")
        self.erinnerung("In zwanzig Tagen", tage=20)
        out, _fehler = self.lauf(reminders.main, "list")  # Standard 14 Tage
        self.assertIn("In zehn Tagen", out)
        self.assertNotIn("In zwanzig Tagen", out)
        self.assertNotIn("Verlauf", out)
        self.assertNotIn("angelegt", out)
        self.assertNotIn("geheim", out)

    def test_werktage(self):
        f = reminders.werktage
        fr, mo = dt.date(2026, 10, 16), dt.date(2026, 10, 19)
        self.assertEqual(f(fr, mo), 1)  # über das Wochenende
        self.assertEqual((f(mo, mo), f(mo, fr)), (0, 0))  # gleicher Tag, rückwärts
        self.assertEqual(f(dt.date(2026, 10, 5), mo), 10)  # zwei Wochen
        self.assertEqual(f(dt.date(2026, 10, 10), dt.date(2026, 10, 11)), 0)  # Sa auf So
        self.assertEqual(f(dt.date(2026, 10, 9), dt.date(2026, 10, 20)), 7)  # Fr bis Di der übernächsten Woche
        self.assertEqual(f(dt.date(2026, 10, 17), dt.date(2026, 10, 23)), 5)  # Sa bis Fr


class Selbststart(unittest.TestCase):
    def test_aufruf_nur_im_hauptprogramm(self):
        text = (KIT / "reminders.py").read_text(encoding="utf-8")
        self.assertIn('if __name__ == "__main__":\n    venv_starten(__file__)\n    kit_basis.starten(main, __file__)', text)


if __name__ == "__main__":
    unittest.main()
