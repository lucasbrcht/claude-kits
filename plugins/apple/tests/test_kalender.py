"""Tests für die Kalender-Skripte ohne EventKit und ohne Apple Kalender: Schreibziel, add_event.py, move_event.py,
calendar_today.sh.

Die Ersatzmodule für EventKit und Foundation kommen aus ersatz_eventkit.py. calendar_today.sh läuft als Kopie in einem
Temp-Ordner mit einem Ersatz für icalBuddy im PATH. Die Tests laufen in der Sandbox, die Skripte selbst außerhalb
(sandbox: aus in kit.json), weil sie Kalender- und Maildaten lesen.

Aufruf im Kit-Ordner: python3 -B -m unittest discover tests
"""
import datetime as dt
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from ersatz_eventkit import CFG, D, EXCHANGE, ICLOUD, KIT, LOKAL, Kalender, KitTest, NSDate, Store, Termin

import add_event  # noqa: E402
import eventkit_basis  # noqa: E402
import kalender_basis  # noqa: E402
import move_event  # noqa: E402


class Schreibziel(unittest.TestCase):
    def ziel(self, name, *kalender):
        return kalender_basis.target_calendar(Store(kalender=kalender), name, CFG)

    def test_nicht_erlaubt(self):
        with self.assertRaisesRegex(SystemExit, "nicht erlaubt"):
            self.ziel("Kalender", Kalender("Kalender", EXCHANGE, 2))

    def test_privat_gewinnt(self):
        with self.assertRaisesRegex(SystemExit, "nicht erlaubt"):
            self.ziel("Geheim", Kalender("Geheim"))

    def test_dublette(self):
        with self.assertRaisesRegex(SystemExit, "nicht eindeutig.*iCloud, Auf meinem Mac"):
            self.ziel("Privat", Kalender("Privat"), Kalender("Privat", LOKAL, 0))

    def test_exchange_quelle(self):
        with self.assertRaisesRegex(SystemExit, "Exchange-Konto Firma"):
            self.ziel("Privat", Kalender("Privat", EXCHANGE, 1))

    def test_exchange_typ(self):
        with self.assertRaisesRegex(SystemExit, "Exchange"):
            self.ziel("Privat", Kalender("Privat", ICLOUD, 2))

    def test_nicht_gefunden(self):
        with self.assertRaisesRegex(SystemExit, "nicht gefunden"):
            self.ziel("Privat", Kalender("T&L Kalender"))

    def test_gueltig(self):
        privat = Kalender("Privat")
        self.assertIs(self.ziel("Privat", privat, Kalender("T&L Kalender")), privat)

    def test_config_text_statt_liste(self):
        with self.assertRaisesRegex(SystemExit, "private_calendars muss eine Liste"):
            kalender_basis.allowed_calendars({"allowed_calendars": ["Privat"], "private_calendars": "Geheim"})

    def test_default_calendar_als_liste(self):
        """Review 21.10.2026: default_calendar als Liste endete mit TypeError. Jetzt eine Meldung mit dem Schlüssel."""
        with self.assertRaisesRegex(SystemExit, "default_calendar muss ein Kalendername als Text sein"):
            kalender_basis.kalender_name({**CFG, "default_calendar": ["Privat"]}, None)


# ---------- add_event.py ----------

class AddEvent(KitTest):
    def setUp(self):
        super().setUp()
        self.privat, self.tl = Kalender("Privat"), Kalender("T&L Kalender")
        self.s = self.store(kalender=[self.privat, self.tl, Kalender("Kalender", EXCHANGE, 2)])

    def gespeichert(self):
        return [ev for ev, _span in self.s.gespeichert]

    def test_nachkontrolle_nach_dem_anlegen(self):
        """Etappe 4 von v7.3.0: ganztägig zählt nur der Tag, auch mit Ende 0 Uhr des Folgetags, verloren ist verloren."""
        self.s.nach_speichern = lambda ev: ev.setEndDate_(NSDate(D("2026-10-17 00:00").timestamp()))
        out, fehler = self.lauf(add_event.main, "--ausfuehren", "Urlaub", "2026-10-12", "2026-10-16")
        self.assertIsNone(fehler)
        self.assertNotIn("Nachkontrolle", out)
        self.s.nach_speichern = None
        self.s.eventWithIdentifier_ = lambda ident: None
        out, _ = self.lauf(add_event.main, "--ausfuehren", "Rad", "2026-10-20 10:00", "2026-10-20 12:00")
        self.assertIn("Angelegt: Rad", out)
        self.assertIn("Nachkontrolle: 'Rad' nach dem Speichern nicht wiedergefunden", out)

    def test_ganztaegig_inklusiv(self):
        self.assertEqual(add_event.parse_range("2026-10-12", "2026-10-16"),
                         (D("2026-10-12 00:00"), D("2026-10-16 23:59"), True))
        out, fehler = self.lauf(add_event.main, "--ausfuehren", "Urlaub", "2026-10-12", "2026-10-16")
        self.assertIsNone(fehler)
        ev = self.gespeichert()[0]
        self.assertTrue(ev.isAllDay())
        self.assertEqual(eventkit_basis.pydt(ev.endDate()).date(), dt.date(2026, 10, 16))
        self.assertIn("Urlaub, Mo 12.10. bis Fr 16.10., ganztägig, Kalender Privat (Konto iCloud)", out)

    def test_ende_vor_start(self):
        _out, fehler = self.lauf(add_event.main, "X", "2026-10-05 10:00", "2026-10-05 09:00")
        self.assertIn("nicht nach dem Start", fehler)
        with self.assertRaisesRegex(SystemExit, "nicht nach dem Start"):
            add_event.parse_range("2026-10-16", "2026-10-12")
        self.assertEqual(self.gespeichert(), [])

    def test_gemischtes_format(self):
        _out, fehler = self.lauf(add_event.main, "X", "2026-10-05", "2026-10-05 10:00")
        self.assertIn("JJJJ-MM-TT HH:MM", fehler)
        self.assertEqual(self.gespeichert(), [])

    def test_dublette(self):
        self.s.termine.append(Termin(titel="Zahnarzt", start="2026-10-05 09:30", ende="2026-10-05 10:15",
                                     kalender=self.privat))
        _out, fehler = self.lauf(add_event.main, "zahnarzt ", "2026-10-05 09:30", "2026-10-05 10:00")
        self.assertIn("steht schon", fehler)
        self.assertEqual(self.gespeichert(), [])

    def test_dublette_nur_im_zielkalender(self):
        self.s.termine.append(Termin(titel="Zahnarzt", start="2026-10-05 09:30", ende="2026-10-05 10:15",
                                     kalender=self.tl))
        _out, fehler = self.lauf(add_event.main, "--ausfuehren", "Zahnarzt", "2026-10-05 09:30", "2026-10-05 10:15")
        self.assertIsNone(fehler)
        self.assertEqual(len(self.gespeichert()), 1)

    def test_vorschau_speichert_nicht(self):
        out, fehler = self.lauf(add_event.main, "--ort", "Praxis", "--", "Zahnarzt", "2026-10-05 09:30",
                                "2026-10-05 10:15")
        self.assertIsNone(fehler)
        self.assertEqual(out.strip(), "Probelauf, nichts gespeichert: Zahnarzt, Mo 05.10., 9:30 bis 10:15 Uhr, "
                                      "Ort Praxis, Kalender Privat (Konto iCloud)")
        self.assertEqual(self.gespeichert(), [])

    def test_ohne_ausfuehren_nur_vorschau(self):
        """V3 (19.10.2026): Die Vorschau ist Standard und läuft ohne Rückfrage, nur --ausfuehren speichert."""
        out, fehler = self.lauf(add_event.main, "--", "Zahnarzt", "2026-10-05 09:30", "2026-10-05 10:15")
        self.assertIsNone(fehler)
        self.assertTrue(out.startswith("Probelauf, nichts gespeichert: Zahnarzt, Mo 05.10."))
        self.assertEqual(self.gespeichert(), [])
        for kurz in ("--aus", "--ausfuehre"):  # Abkürzungen gälten sonst als --ausfuehren, ohne dass die Regel greift
            _out, fehler = self.lauf(add_event.main, kurz, "X", "2026-10-05 09:30", "2026-10-05 10:15")
            self.assertEqual(fehler, 2, kurz)
        self.assertEqual(self.gespeichert(), [])
        for argv in (("--", "Titel", "2026-10-05 09:30", "2026-10-05 10:15", "--ausfuehren"),
                     ("--calendar", "Privat", "--ausfuehren", "--", "X", "2026-10-05 09:30", "2026-10-05 10:15")):
            _out, fehler = self.lauf(add_event.main, *argv)  # V3.1: der Schalter nur direkt hinter dem Skript
            self.assertIn("--ausfuehren steht nur direkt hinter dem Skript", fehler, argv)
        self.assertEqual(self.gespeichert(), [])

    def test_wanduhrzeit_am_25_10(self):
        out, fehler = self.lauf(add_event.main, "--ausfuehren", "Nachtzug", "2026-10-25 01:30", "2026-10-25 03:30")
        self.assertIsNone(fehler)
        ev = self.gespeichert()[0]
        self.assertEqual(ev.startDate().t, D("2026-10-25 01:30").timestamp())
        self.assertEqual(ev.endDate().t - ev.startDate().t, 3 * 3600)  # eine Stunde doppelt: 3 statt 2 Stunden
        self.assertIn("So 25.10., 1:30 bis 3:30 Uhr", out)

    def test_zeitumstellung_doppelte_oder_fehlende_uhrzeit(self):
        """Prüfung 20.10.2026: 2 bis 3 Uhr gibt es am letzten Sonntag im Oktober zweimal und im März gar nicht. Das Skript
        meldet das an jedem solchen Tag, auch in der Vorschau, statt still die erste Fassung zu nehmen oder um eine
        Stunde zu verschieben. Ganztägige Termine und 3 Uhr bleiben erlaubt."""
        faelle = (("2026-10-25 02:30", "2026-10-25 04:00", "So 25.10., 2:30 Uhr gibt es zweimal"),
                  ("2026-10-25 01:00", "2026-10-25 02:00", "So 25.10., 2 Uhr gibt es zweimal"),
                  ("2027-10-31 02:59", "2027-10-31 05:00", "So 31.10., 2:59 Uhr gibt es zweimal"),
                  ("2027-03-28 02:15", "2027-03-28 04:00", "So 28.03., 2:15 Uhr gibt es nicht"),
                  ("2026-03-28 23:00", "2026-03-29 02:00", "So 29.03., 2 Uhr gibt es nicht"))
        for start, ende, meldung in faelle:
            for schalter in ((), ("--ausfuehren",)):
                _out, fehler = self.lauf(add_event.main, *schalter, "--", "Nachtzug", start, ende)
                self.assertIn(meldung, str(fehler), (start, schalter))
                self.assertIn("Nichts angelegt.", fehler)
        self.assertEqual(self.gespeichert(), [])
        for argv in (("Nachtzug", "2026-10-25 03:00", "2026-10-25 04:00"), ("Urlaub", "2026-10-25", "2026-10-25"),
                     ("Frühzug", "2027-03-28 03:00", "2027-03-28 04:00")):
            _out, fehler = self.lauf(add_event.main, "--ausfuehren", *argv)
            self.assertIsNone(fehler, argv)
        self.assertEqual(len(self.gespeichert()), 3)

    def test_ueber_mitternacht(self):
        out, _fehler = self.lauf(add_event.main, "Party", "2026-10-05 22:00", "2026-10-06 01:00")
        self.assertIn("Mo 05.10., 22 Uhr bis Di 06.10., 1 Uhr", out)

    def test_ort_notiz_und_kalender(self):
        _out, fehler = self.lauf(add_event.main, "--ausfuehren", "--calendar", "T&L Kalender", "--ort", "Kino am Markt",
                                 "--notiz", "Karten abholen", "--", "Kino", "2026-10-09 20:00", "2026-10-09 22:30")
        self.assertIsNone(fehler)
        ev = self.gespeichert()[0]
        self.assertEqual((ev.calendar(), ev.ort, ev.notiz), (self.tl, "Kino am Markt", "Karten abholen"))

    def test_alte_form_mit_ort_bricht_ab(self):
        """V3.1.2, Befund 13: Nach dem Titel stehen nur noch Zeiten. Ort und Notiz an alter Stelle brechen mit Hinweis
        auf --ort und --notiz ab, statt als Zeit oder still als Ort zu gelten."""
        for rest in (("Praxis",), ("Praxis", "Karten abholen")):
            _out, fehler = self.lauf(add_event.main, "--ausfuehren", "--", "Zahnarzt", "2026-10-05 09:30",
                                     "2026-10-05 10:15", *rest)
            self.assertIn("--ort und --notiz", str(fehler), rest)
            self.assertIn("Nichts angelegt.", fehler)
        self.assertEqual(self.gespeichert(), [])

    def test_mehrere_termine_in_einem_aufruf(self):
        """V3.1.2, Befund 13 (Lucas 30.10., Option a): mehrere Zeiträume zum selben Titel, eine Vorschau und ein
        Speichern für alle, Ort und Notiz an jedem Termin."""
        samstage = ("2026-11-07", "2026-11-14", "2026-11-21", "2026-11-28", "2026-12-05")
        zeiten = [z for tag in samstage for z in (f"{tag} 14:00", f"{tag} 17:00")]
        out, fehler = self.lauf(add_event.main, "--ort", "Treffpunkt", "--", "Radtour", *zeiten)
        self.assertIsNone(fehler)
        self.assertEqual(out.splitlines(), [
            "Probelauf, nichts gespeichert: 5 Termine Radtour, Ort Treffpunkt, Kalender Privat (Konto iCloud)",
            "- Sa 07.11., 14 bis 17 Uhr", "- Sa 14.11., 14 bis 17 Uhr", "- Sa 21.11., 14 bis 17 Uhr",
            "- Sa 28.11., 14 bis 17 Uhr", "- Sa 05.12., 14 bis 17 Uhr"])
        self.assertEqual(self.gespeichert(), [])
        out, fehler = self.lauf(add_event.main, "--ausfuehren", "--ort", "Treffpunkt", "--notiz", "Licht mitnehmen", "--",
                                "Radtour", *zeiten)
        self.assertIsNone(fehler)
        self.assertTrue(out.startswith("Angelegt: 5 Termine Radtour, Ort Treffpunkt, Kalender Privat (Konto iCloud)\n"))
        evs = self.gespeichert()
        self.assertEqual([eventkit_basis.pydt(ev.startDate()) for ev in evs],
                         [D(f"{tag} 14:00") for tag in samstage])
        self.assertTrue(all((ev.title(), ev.calendar(), ev.ort, ev.notiz) == ("Radtour", self.privat, "Treffpunkt",
                                                                             "Licht mitnehmen") for ev in evs))
        self.assertEqual(len({id(ev) for ev in evs}), 5)

    def test_mehrere_dublette_je_termin(self):
        """Steht einer der Termine schon im Zielkalender, legt das Skript keinen an und nennt jeden gleichen."""
        for tag in ("2026-11-14", "2026-11-28"):
            self.s.termine.append(Termin(titel="Radtour", start=f"{tag} 14:00", ende=f"{tag} 17:00",
                                         kalender=self.privat))
        _out, fehler = self.lauf(add_event.main, "--ausfuehren", "--", "radtour", "2026-11-07 14:00", "2026-11-07 17:00",
                                 "2026-11-14 14:00", "2026-11-14 17:00", "2026-11-28 14:00", "2026-11-28 17:00")
        zeilen = str(fehler).splitlines()
        self.assertEqual(len(zeilen), 3)
        self.assertIn("steht schon 'radtour' mit Start Sa 14.11., 14 bis 17 Uhr", zeilen[0])
        self.assertIn("Sa 28.11.", zeilen[1])
        self.assertEqual(zeilen[2], "Nichts angelegt.")
        self.assertEqual(self.gespeichert(), [])

    def test_mehrere_aufruf_falsch(self):
        """Ungerade Zahl, ein Start doppelt im Aufruf oder ein falsches Paar mitten in der Liste: nichts angelegt, auch
        die gültigen Paare davor nicht."""
        faelle = ((("2026-11-07 14:00", "2026-11-07 17:00", "2026-11-14 14:00"), "paarweise"),
                  (("2026-11-07 14:00", "2026-11-07 17:00", "2026-11-07 14:00", "2026-11-07 16:00"),
                   "Start Sa 07.11., 14 bis 17 Uhr steht zweimal im Aufruf"),
                  (("2026-11-07 14:00", "2026-11-07 17:00", "2026-11-14 17:00", "2026-11-14 14:00"),
                   "nicht nach dem Start"))
        for zeiten, meldung in faelle:
            _out, fehler = self.lauf(add_event.main, "--ausfuehren", "--", "Radtour", *zeiten)
            self.assertIn(meldung, str(fehler), zeiten)
        self.assertEqual(self.gespeichert(), [])

    def test_titel_mit_bindestrich(self):
        _out, fehler = self.lauf(add_event.main, "--", "-Vorbereitung", "2026-10-05 09:30", "2026-10-05 10:00")
        self.assertIsNone(fehler)

    def test_exchange_nie_ziel(self):
        self.config(allowed_calendars=["Privat", "Kalender"])
        _out, fehler = self.lauf(add_event.main, "--calendar", "Kalender", "Block", "2026-10-05 09:00",
                                 "2026-10-05 10:00")
        self.assertIn("Exchange", fehler)
        self.assertEqual(self.gespeichert(), [])

    def test_nicht_erlaubt_vor_dem_zugriff(self):
        self.store(zugriff=False)
        _out, fehler = self.lauf(add_event.main, "--calendar", "Kalender", "X", "2026-10-05 09:00", "2026-10-05 10:00")
        self.assertIn("nicht erlaubt", fehler)

    def test_exchange_schalter_legt_im_arbeitskalender_an(self):
        """V4 (Profil privat): --exchange legt eigene Termine ohne Teilnehmer im Arbeitskalender an, erst als Vorschau."""
        self.config(arbeitskalender="Kalender")
        out, fehler = self.lauf(add_event.main, "--exchange", "--", "Block", "2026-10-05 09:00", "2026-10-05 10:00")
        self.assertIsNone(fehler)
        self.assertEqual(out.strip(), "Probelauf, nichts gespeichert: Block, Mo 05.10., 9 bis 10 Uhr, Kalender Kalender "
                                      "(Konto Firma)")
        self.assertEqual(self.gespeichert(), [])
        out, fehler = self.lauf(add_event.main, "--exchange", "--ausfuehren", "--ort", "Büro", "--", "Block",
                                "2026-10-05 09:00", "2026-10-05 10:00")
        self.assertIsNone(fehler)
        self.assertIn("Angelegt: Block, Mo 05.10., 9 bis 10 Uhr, Ort Büro, Kalender Kalender (Konto Firma)", out)
        self.assertEqual([ev.calendar().title() for ev in self.gespeichert()], ["Kalender"])

    def test_exchange_schalter_nur_als_erstes_argument(self):
        """Die Sperre in der Arbeit (verbote) steht auf --exchange direkt hinter dem Skript, jede andere Stelle bricht ab."""
        self.config(arbeitskalender="Kalender")
        for argv in (("--ausfuehren", "--exchange", "--", "Block", "2026-10-05 09:00", "2026-10-05 10:00"),
                     ("--", "Block", "2026-10-05 09:00", "2026-10-05 10:00", "--exchange"),
                     ("--ort", "Büro", "--exchange", "--", "Block", "2026-10-05 09:00", "2026-10-05 10:00")):
            _out, fehler = self.lauf(add_event.main, *argv)
            self.assertIn("--exchange steht", str(fehler), argv)
        _out, fehler = self.lauf(add_event.main, "--exch", "--", "Block", "2026-10-05 09:00", "2026-10-05 10:00")
        self.assertEqual(fehler, 2)
        self.assertEqual(self.gespeichert(), [])

    def test_exchange_schalter_nur_arbeitskalender(self):
        _out, fehler = self.lauf(add_event.main, "--exchange", "--", "Block", "2026-10-05 09:00", "2026-10-05 10:00")
        self.assertIn("braucht arbeitskalender", fehler)
        self.config(arbeitskalender="Kalender")
        _out, fehler = self.lauf(add_event.main, "--exchange", "--calendar", "Privat", "--", "Block",
                                 "2026-10-05 09:00", "2026-10-05 10:00")
        self.assertIn("nur der Arbeitskalender aus config.json (Kalender)", fehler)
        self.config(arbeitskalender="Privat")  # gleichnamig, aber iCloud: nie Ziel mit --exchange
        _out, fehler = self.lauf(add_event.main, "--exchange", "--", "Block", "2026-10-05 09:00", "2026-10-05 10:00")
        self.assertIn("Kein Exchange-Kalender 'Privat'", fehler)
        self.assertEqual(self.gespeichert(), [])


# ---------- move_event.py ----------

class MoveEvent(KitTest):
    def setUp(self):
        super().setUp()
        self.privat, self.tl = Kalender("Privat"), Kalender("T&L Kalender")
        self.s = self.store(kalender=[self.privat, self.tl])

    def termin(self, titel="Zahnarzt", start="2026-10-05 09:30", ende="2026-10-05 10:15", kalender=None, **kw):
        t = Termin(titel=titel, start=start, ende=ende, kalender=kalender or self.privat, **kw)
        self.s.termine.append(t)
        return t

    def samstage(self, titel="Radtour", kalender=None, **kw):
        return [self.termin(titel, f"{tag} 14:00", f"{tag} 17:00", kalender, **kw)
                for tag in ("2026-11-07", "2026-11-14", "2026-11-21")]

    def test_dublette_im_kalendernamen(self):
        self.s.kalender.append(Kalender("Privat", LOKAL, 0))
        _out, fehler = self.lauf(move_event.main, "Zahnarzt", "2026-10-05 09:30", "2026-10-06 09:30")
        self.assertIn("nicht eindeutig", fehler)

    def test_mehrere_treffer(self):
        self.termin("Training A")
        self.termin("Training B")
        _out, fehler = self.lauf(move_event.main, "training", "2026-10-05 09:30", "2026-10-06 09:30")
        self.assertIn("2 Treffer", fehler)
        self.assertEqual(self.s.gespeichert, [])

    def test_kein_treffer(self):
        self.termin()
        _out, fehler = self.lauf(move_event.main, "Zahnarzt", "2026-10-05 10:00", "2026-10-06 09:30")
        self.assertIn("0 Treffer", fehler)

    def test_verschieben_mit_teil_des_titels(self):
        t = self.termin()
        out, fehler = self.lauf(move_event.main, "--ausfuehren", "zahn", "2026-10-05 09:30", "2026-10-06 11:00")
        self.assertIsNone(fehler)
        self.assertEqual(t.startDate().t, D("2026-10-06 11:00").timestamp())
        self.assertEqual(t.endDate().t, D("2026-10-06 11:45").timestamp())
        self.assertIn("von Mo 05.10., 9:30 bis 10:15 Uhr auf Di 06.10., 11 bis 11:45 Uhr", out)

    def test_dauer_ueber_die_umstellung(self):
        t = self.termin("Radtour", "2026-10-24 10:00", "2026-10-24 13:00")
        out, fehler = self.lauf(move_event.main, "--ausfuehren", "Radtour", "2026-10-24 10:00", "2026-10-25 01:00")
        self.assertIsNone(fehler)
        self.assertEqual(t.endDate().t - t.startDate().t, 3 * 3600)  # Wanduhr hätte 4 Stunden ergeben
        self.assertIn("auf So 25.10., 1 bis 3 Uhr", out)

    def test_zeitumstellung_alter_oder_neuer_start(self):
        """Prüfung 20.10.2026: Einen Start, den es wegen der Zeitumstellung zweimal oder nicht gibt, meldet auch
        move_event.py, vor dem Kalenderzugriff. Ein nicht existierender alter Start träfe sonst den Termin eine Stunde
        später."""
        t = self.termin("Radtour", "2027-03-28 03:30", "2027-03-28 05:00")
        for alt, neu, meldung in (("2027-03-28 03:30", "2026-10-25 02:30", "So 25.10., 2:30 Uhr gibt es zweimal"),
                                  ("2027-03-28 02:30", "2027-03-29 10:00", "So 28.03., 2:30 Uhr gibt es nicht")):
            self.store(zugriff=False)  # bräche ohne Freigabe ab, die Prüfung kommt vorher
            _out, fehler = self.lauf(move_event.main, "--ausfuehren", "Radtour", alt, neu)
            self.assertIn(meldung, str(fehler))
            self.assertIn("Nichts geändert.", fehler)
        self.assertEqual(t.startDate().t, D("2027-03-28 03:30").timestamp())

    def test_teilnehmer_ohne_schalter(self):
        self.termin(teilnehmer=True)
        _out, fehler = self.lauf(move_event.main, "Zahnarzt", "2026-10-05 09:30", "2026-10-06 09:30")
        self.assertIn("--mit-teilnehmern", fehler)
        self.assertEqual(self.s.gespeichert, [])

    def test_teilnehmer_mit_schalter(self):
        self.termin(teilnehmer=True)
        _out, fehler = self.lauf(move_event.main, "--ausfuehren", "--mit-teilnehmern", "Zahnarzt", "2026-10-05 09:30",
                                 "2026-10-06 09:30")
        self.assertIsNone(fehler)
        self.assertEqual(len(self.s.gespeichert), 1)

    def test_serie_mit_hinweis(self):
        self.termin(serie=True)
        out, fehler = self.lauf(move_event.main, "--ausfuehren", "Zahnarzt", "2026-10-05 09:30", "2026-10-06 09:30")
        self.assertIsNone(fehler)
        self.assertIn("Serientermin: nur dieser eine Termin", out)
        self.assertEqual(self.s.gespeichert[0][1], 0)  # EKSpanThisEvent

    def test_genauer_titel_vor_teiltreffern(self):
        """V3.1.2: Passen mehrere Termine zur gleichen Zeit und heißt genau einer wie der Titel-Teil, rückt nur dieser.
        Zwei gleichnamige bleiben mehrdeutig."""
        genau = self.termin("Training")
        andere = self.termin("Training B")
        out, fehler = self.lauf(move_event.main, "--ausfuehren", "training", "2026-10-05 09:30", "2026-10-06 09:30")
        self.assertIsNone(fehler)
        self.assertIn("Verschoben: Training (Privat", out)
        self.assertEqual(genau.startDate().t, D("2026-10-06 09:30").timestamp())
        self.assertEqual(andere.startDate().t, D("2026-10-05 09:30").timestamp())
        self.termin("Training", "2026-10-06 09:30", "2026-10-06 10:15")
        _out, fehler = self.lauf(move_event.main, "Training", "2026-10-06 09:30", "2026-10-07 09:30")
        self.assertIn("2 Treffer", fehler)

    def test_ohne_ausfuehren_nur_vorschau(self):
        t = self.termin()
        out, fehler = self.lauf(move_event.main, "--", "Zahnarzt", "2026-10-05 09:30", "2026-10-06 09:30")
        self.assertIsNone(fehler)
        self.assertTrue(out.startswith("Probelauf, nichts gespeichert: Zahnarzt (Privat, Konto iCloud)"))
        self.assertEqual((self.s.gespeichert, t.startDate().t), ([], D("2026-10-05 09:30").timestamp()))
        _out, fehler = self.lauf(move_event.main, "--ausf", "Zahnarzt", "2026-10-05 09:30", "2026-10-06 09:30")
        self.assertEqual(fehler, 2)
        _out, fehler = self.lauf(move_event.main, "--mit-teilnehmern", "--ausfuehren", "Zahnarzt", "2026-10-05 09:30",
                                 "2026-10-06 09:30")
        self.assertIn("--ausfuehren steht nur direkt hinter dem Skript", fehler)
        self.assertEqual(self.s.gespeichert, [])

    def test_nachkontrolle_nach_dem_verschieben(self):
        """Etappe 4 von v7.3.0: nach dem Speichern frisch laden, Abweichung bei Zeit oder Kalender nennen."""
        t = self.termin()
        out, fehler = self.lauf(move_event.main, "--ausfuehren", "Zahnarzt", "2026-10-05 09:30", "2026-10-06 11:00")
        self.assertIsNone(fehler)
        self.assertNotIn("Nachkontrolle", out)
        self.assertEqual(self.s.zurueckgesetzt, 1)
        alt = t.startDate()
        self.s.nach_speichern = lambda ev: ev.setStartDate_(alt)  # Kalender übernimmt die neue Zeit nicht
        out, fehler = self.lauf(move_event.main, "--ausfuehren", "Zahnarzt", "2026-10-06 11:00", "2026-10-07 11:00")
        self.assertIsNone(fehler)
        self.assertIn("Nachkontrolle: 'Zahnarzt' steht im Kalender von 06.10. 11:00 bis 07.10. 11:45, gewollt "
                      "07.10. 11:00 bis 07.10. 11:45.", out)
        self.s.nach_speichern = lambda ev: ev.setCalendar_(self.privat)
        out, _ = self.lauf(move_event.main, "--ausfuehren", "--nach-kalender", "T&L Kalender", "Zahnarzt",
                           "2026-10-06 11:00")
        self.assertIn("Nachkontrolle: 'Zahnarzt' steht in Privat, gewollt T&L Kalender.", out)

    def test_ganztaegig_um_ganze_tage(self):
        t = self.termin("Urlaub", "2026-10-12 00:00", "2026-10-16 23:59", ganztaegig=True)
        out, fehler = self.lauf(move_event.main, "--ausfuehren", "Urlaub", "2026-10-12 00:00", "2026-10-19 00:00")
        self.assertIsNone(fehler)
        self.assertEqual(eventkit_basis.pydt(t.endDate()), D("2026-10-23 23:59"))
        self.assertIn("auf Mo 19.10. bis Fr 23.10., ganztägig", out)

    def test_exchange_nie_ziel(self):
        self.config(allowed_calendars=["Privat", "Kalender"])
        self.s.kalender.append(Kalender("Kalender", EXCHANGE, 2))
        _out, fehler = self.lauf(move_event.main, "--calendar", "Kalender", "Sync", "2026-10-05 09:30",
                                 "2026-10-05 11:00")
        self.assertIn("Exchange", fehler)

    def test_mehrere_verschieben(self):
        """V3.1.2, Befund 13: bisheriger und neuer Start paarweise, eine Vorschau und ein Speichern für alle. Passt zu
        einem Start kein Termin, rückt keiner."""
        a, b, c = self.samstage()
        argv = ("Radtour", "2026-11-07 14:00", "2026-11-07 15:00", "2026-11-14 14:00", "2026-11-14 15:00")
        out, fehler = self.lauf(move_event.main, "--", *argv)
        self.assertIsNone(fehler)
        self.assertEqual(out.splitlines(), [
            "Probelauf, nichts gespeichert: 2 Termine (Privat, Konto iCloud)",
            "- Radtour von Sa 07.11., 14 bis 17 Uhr auf Sa 07.11., 15 bis 18 Uhr",
            "- Radtour von Sa 14.11., 14 bis 17 Uhr auf Sa 14.11., 15 bis 18 Uhr"])
        self.assertEqual(self.s.gespeichert, [])
        _out, fehler = self.lauf(move_event.main, "--ausfuehren", *argv, "2026-11-28 14:00", "2026-11-28 15:00")
        self.assertIn("0 Treffer für 'Radtour' mit Start 2026-11-28 14:00", fehler)
        self.assertTrue(fehler.endswith("Nichts geändert."))
        self.assertEqual(self.s.gespeichert, [])
        out, fehler = self.lauf(move_event.main, "--ausfuehren", *argv)
        self.assertIsNone(fehler)
        self.assertTrue(out.startswith("Verschoben: 2 Termine (Privat, Konto iCloud)\n"))
        self.assertEqual([t.startDate().t for t in (a, b, c)],
                         [D(s).timestamp() for s in ("2026-11-07 15:00", "2026-11-14 15:00", "2026-11-21 14:00")])
        _out, fehler = self.lauf(move_event.main, "--", "Radtour", "2026-11-21 14:00")
        self.assertIn("paarweise", fehler)
        _out, fehler = self.lauf(move_event.main, "--", "Radtour", "2026-11-21 14:00", "2026-11-22 14:00",
                                 "2026-11-21 14:00", "2026-11-23 14:00")
        self.assertIn("Start 2026-11-21 14:00 steht zweimal im Aufruf", fehler)

    # ---------- Kalender wechseln (V3.1.2, Befund 14) ----------

    def test_kalender_wechseln(self):
        """Derselbe Termin bekommt nur einen anderen Kalender: Zeit, Titel und Zahl der Termine bleiben, nichts wird neu
        angelegt. Die Vorschau zeigt alten und neuen Kalender."""
        t = self.termin("Radtour", "2026-11-07 14:00", "2026-11-07 17:00")
        argv = ("--nach-kalender", "T&L Kalender", "--", "radtour", "2026-11-07 14:00")
        out, fehler = self.lauf(move_event.main, *argv)
        self.assertIsNone(fehler)
        self.assertEqual(out.strip(), "Probelauf, nichts gespeichert: Radtour, Sa 07.11., 14 bis 17 Uhr, von Privat "
                                      "(Konto iCloud) nach T&L Kalender (Konto iCloud)")
        self.assertEqual((self.s.gespeichert, t.calendar()), ([], self.privat))
        out, fehler = self.lauf(move_event.main, "--ausfuehren", *argv)
        self.assertIsNone(fehler)
        self.assertTrue(out.startswith("Kalender gewechselt: Radtour, Sa 07.11., 14 bis 17 Uhr, von Privat"))
        self.assertEqual(self.s.gespeichert, [(t, 0)])
        self.assertEqual((t.calendar(), t.startDate().t, t.endDate().t, len(self.s.termine)),
                         (self.tl, D("2026-11-07 14:00").timestamp(), D("2026-11-07 17:00").timestamp(), 1))

    def test_kalender_wechseln_mehrere(self):
        """Mehrere Starts in einem Aufruf. Fehlt einer, wechselt keiner."""
        termine = self.samstage()
        starts = ("2026-11-07 14:00", "2026-11-14 14:00", "2026-11-21 14:00")
        _out, fehler = self.lauf(move_event.main, "--ausfuehren", "--nach-kalender", "T&L Kalender", "--", "Radtour",
                                 *starts, "2026-11-28 14:00")
        self.assertIn("0 Treffer", fehler)
        self.assertEqual((self.s.gespeichert, {t.calendar() for t in termine}), ([], {self.privat}))
        out, fehler = self.lauf(move_event.main, "--ausfuehren", "--nach-kalender", "T&L Kalender", "--", "Radtour",
                                *starts)
        self.assertIsNone(fehler)
        self.assertEqual(out.splitlines(), [
            "Kalender gewechselt: 3 Termine von Privat (Konto iCloud) nach T&L Kalender (Konto iCloud)",
            "- Radtour, Sa 07.11., 14 bis 17 Uhr", "- Radtour, Sa 14.11., 14 bis 17 Uhr",
            "- Radtour, Sa 21.11., 14 bis 17 Uhr"])
        self.assertEqual({t.calendar() for t in termine}, {self.tl})
        self.assertEqual(len(self.s.termine), 3)

    def test_kalender_wechseln_nur_erlaubte_kalender(self):
        """Ziel und Quelle aus allowed_calendars, private_calendars nie, geprüft vor dem Kalenderzugriff. Exchange nie
        als Ziel. Gleicher oder leerer Zielkalender bricht ab."""
        self.store(zugriff=False)
        for ziel in ("Geheim", "Familie"):
            _out, fehler = self.lauf(move_event.main, "--nach-kalender", ziel, "--", "Radtour", "2026-11-07 14:00")
            self.assertIn(f"Kalender '{ziel}' nicht erlaubt", fehler)
        _out, fehler = self.lauf(move_event.main, "--calendar", "Familie", "--nach-kalender", "Privat", "--", "Radtour",
                                 "2026-11-07 14:00")
        self.assertIn("Kalender 'Familie' nicht erlaubt", fehler)
        _out, fehler = self.lauf(move_event.main, "--nach-kalender", "Privat", "--", "Radtour", "2026-11-07 14:00")
        self.assertIn("Quell- und Zielkalender sind beide Privat", fehler)
        _out, fehler = self.lauf(move_event.main, "--nach-kalender", " ", "--", "Radtour", "2026-11-07 14:00")
        self.assertIn("Zielkalender fehlt", fehler)
        self.config(allowed_calendars=["Privat", "Kalender"])
        s = self.store(kalender=[self.privat, Kalender("Kalender", EXCHANGE, 2)])
        self.termin("Radtour", "2026-11-07 14:00", "2026-11-07 17:00")
        s.termine = self.s.termine
        _out, fehler = self.lauf(move_event.main, "--ausfuehren", "--nach-kalender", "Kalender", "--", "Radtour",
                                 "2026-11-07 14:00")
        self.assertIn("Exchange", fehler)
        self.assertEqual(s.gespeichert, [])

    def test_kalender_wechseln_bricht_ab(self):
        """Teilnehmer (auch mit --mit-teilnehmern), Serie und ein gleicher Termin im Zielkalender: nichts wechselt, jede
        Ursache steht in einer eigenen Zeile."""
        self.termin("Radtour", "2026-11-07 14:00", "2026-11-07 17:00", teilnehmer=True)
        self.termin("Radtour", "2026-11-14 14:00", "2026-11-14 17:00", serie=True)
        self.termin("Radtour", "2026-11-21 14:00", "2026-11-21 17:00")
        self.termin("Radtour", "2026-11-21 14:00", "2026-11-21 17:00", kalender=self.tl)
        ok = self.termin("Radtour", "2026-11-28 14:00", "2026-11-28 17:00")
        _out, fehler = self.lauf(move_event.main, "--ausfuehren", "--mit-teilnehmern", "--nach-kalender", "T&L Kalender",
                                 "--", "Radtour", "2026-11-07 14:00", "2026-11-14 14:00", "2026-11-21 14:00",
                                 "2026-11-28 14:00")
        zeilen = str(fehler).splitlines()
        self.assertIn("hat Teilnehmer. Den Kalender wechselt das Skript dann nicht", zeilen[0])
        self.assertIn("ist ein Serientermin", zeilen[1])
        self.assertIn("In T&L Kalender steht schon 'Radtour' mit Start Sa 21.11., 14 bis 17 Uhr", zeilen[2])
        self.assertEqual(zeilen[3:], ["Nichts geändert."])
        self.assertEqual((self.s.gespeichert, ok.calendar()), ([], self.privat))

    def test_exchange_schalter_verschiebt_eigene_termine(self):
        """V4 (Profil privat): --exchange verschiebt eigene Termine ohne Teilnehmer im Arbeitskalender."""
        self.config(arbeitskalender="Kalender")
        ex = Kalender("Kalender", EXCHANGE, 2)
        self.s.kalender.append(ex)
        t = self.termin("Block", kalender=ex)
        out, fehler = self.lauf(move_event.main, "--exchange", "--ausfuehren", "--", "Block", "2026-10-05 09:30",
                                "2026-10-06 11:00")
        self.assertIsNone(fehler)
        self.assertEqual(t.startDate().t, D("2026-10-06 11:00").timestamp())
        self.assertIn("Block (Kalender, Konto Firma) von Mo 05.10., 9:30 bis 10:15 Uhr auf Di 06.10.", out)

    def test_exchange_schalter_nie_mit_teilnehmern(self):
        self.config(arbeitskalender="Kalender")
        ex = Kalender("Kalender", EXCHANGE, 2)
        self.s.kalender.append(ex)
        t = self.termin("Jour fixe", kalender=ex, teilnehmer=True)
        _out, fehler = self.lauf(move_event.main, "--exchange", "--ausfuehren", "--", "Jour fixe", "2026-10-05 09:30",
                                 "2026-10-06 11:00")
        self.assertIn("hat Teilnehmer. Im Arbeitskalender", fehler)
        for argv in (("--exchange", "--mit-teilnehmern", "--", "Jour fixe", "2026-10-05 09:30", "2026-10-06 11:00"),
                     ("--exchange", "--nach-kalender", "Privat", "--", "Jour fixe", "2026-10-05 09:30")):
            _out, fehler = self.lauf(move_event.main, *argv)
            self.assertIn("nur verschieben", fehler, argv)
        _out, fehler = self.lauf(move_event.main, "--ausfuehren", "--exchange", "--", "Jour fixe", "2026-10-05 09:30",
                                 "2026-10-06 11:00")
        self.assertIn("--exchange steht als erstes Argument", fehler)
        self.assertEqual((self.s.gespeichert, t.startDate().t), ([], D("2026-10-05 09:30").timestamp()))

    def test_kalender_wechseln_schalter_nur_vorn(self):
        self.termin("Radtour", "2026-11-07 14:00", "2026-11-07 17:00")
        _out, fehler = self.lauf(move_event.main, "--nach-kalender", "T&L Kalender", "--ausfuehren", "--", "Radtour",
                                 "2026-11-07 14:00")
        self.assertIn("--ausfuehren steht nur direkt hinter dem Skript", fehler)
        _out, fehler = self.lauf(move_event.main, "--nach-k", "T&L Kalender", "--", "Radtour", "2026-11-07 14:00")
        self.assertEqual(fehler, 2)
        self.assertEqual(self.s.gespeichert, [])


class Selbststart(unittest.TestCase):
    """Die Skripte rufen den Selbststart nur beim Start als Programm auf, nie beim Import (Tests)."""

    def test_aufruf_nur_im_hauptprogramm(self):
        for skript in ("add_event.py", "move_event.py"):
            text = (KIT / skript).read_text(encoding="utf-8")
            self.assertIn('if __name__ == "__main__":\n    venv_starten(__file__)\n    kit_basis.starten(main, __file__)', text, skript)


# ---------- calendar_today.sh ----------

ICALBUDDY = """#!/bin/bash
d="$(cd "$(dirname "$0")" && pwd)"
printf '%s\\n' "$@" > "$d/argumente.txt"
if [ "$1" = "calendars" ]; then cat "$d/kalender.txt"; exit 0; fi
if [ -f "$d/warnung.txt" ]; then cat "$d/warnung.txt" >&2; fi
cat "$d/termine.txt"
exit "$(cat "$d/exitcode.txt" 2>/dev/null || echo 0)"
"""
KALENDERLISTE = ("• Kalender\n  type: Exchange\n  UID: A1\n• Privat\n  type: CalDAV\n  UID: B2\n"
                 "• Geheim\n  type: CalDAV\n  UID: C3\n• Kim\n  type: CalDAV\n  UID: D4\n")
BLOCK = "{name}:\n------------------------\n{zeilen}\n"
TERMINE = "".join([
    BLOCK.format(name="Kalender", zeilen="- Mo 28.09. at 09:00 - 10:00\n    Jour fixe\n    Agenda:"),
    BLOCK.format(name="Geheim", zeilen="- Mo 28.09. at 12:00 - 13:00\n    Arzt\nNotiz:\n- Mo 28.09. at 14:00 - 15:00"),
    BLOCK.format(name="Kalender", zeilen="- Mo 28.09. at 16:00 - 17:00\n    Zweites Konto"),
    BLOCK.format(name="Geburtstage", zeilen="- Mo 28.09.\n    Anna"),
    BLOCK.format(name="Geburtstage", zeilen="- Mo 28.09.\n    Anna"),
    BLOCK.format(name="Kim", zeilen="- Mo 28.09. at 18:00 - 19:00\n    Yoga\n    location: Studio"),
])


class CalendarToday(unittest.TestCase):
    CFG = {"private_calendars": ["Geheim"], "hidden_calendars": ["Kim", "Familie"],
           "dedupe_calendars": ["Geburtstage"], "nur_belegt": ["Kim"], "arbeitskalender": "Kalender"}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        shutil.copy(KIT / "calendar_today.sh", self.tmp)
        self.schreibe("config.json", json.dumps({"kalender": self.CFG}))
        self.schreibe("icalBuddy", ICALBUDDY)
        (self.tmp / "icalBuddy").chmod(0o755)
        self.schreibe("kalender.txt", KALENDERLISTE)
        self.schreibe("termine.txt", TERMINE)

    def schreibe(self, name, text):
        (self.tmp / name).write_text(text, encoding="utf-8")

    def lauf(self, *args, bash="bash"):
        env = {**os.environ, "PATH": f"{self.tmp}{os.pathsep}{os.environ.get('PATH', '')}"}
        return subprocess.run([bash, str(self.tmp / "calendar_today.sh"), *args], capture_output=True, text=True,
                              env=env, timeout=30)

    def argumente(self):
        return (self.tmp / "argumente.txt").read_text(encoding="utf-8").splitlines()

    def test_privater_block_fehlt_auch_mit_all(self):
        for args in ((), ("--all",)):
            r = self.lauf(*args)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("Arzt", r.stdout)
            self.assertNotIn("14:00", r.stdout)  # Zeile nach "Notiz:" ohne Strichlinie bleibt im privaten Block

    def test_gleichnamiger_block_bleibt_ausser_bei_dedupe(self):
        out = self.lauf().stdout
        self.assertEqual(out.count("Kalender:\n"), 2)
        self.assertIn("Zweites Konto", out)
        self.assertEqual(out.count("Geburtstage:\n"), 1)

    def test_kopfzeile_nur_mit_strichlinie(self):
        self.assertIn("    Agenda:", self.lauf().stdout)

    def test_nur_belegt(self):
        out = self.lauf("--all").stdout
        self.assertIn("Kim:\n", out)
        self.assertIn("- Mo 28.09. at 18:00 - 19:00  belegt", out)
        self.assertNotIn("Yoga", out)
        self.assertNotIn("Studio", out)

    def test_nur_belegt_zeigt_nur_zeiten(self):
        """Review 21.10.2026: In nur_belegt steht eine Zeile mit Bindestrich nur dann mit Zeit da, wenn sie aus Wochentag,
        Datum, at und Uhrzeit besteht. Sonst nur "- belegt", etwa bei einem Titel, der mit Zeilenumbruch wie eine neue
        Zeile aussieht."""
        zeilen = "- Mo 28.09. at 18:00 - 19:00\n    Yoga\n- Arzt Dr. Beispiel\n- Di 29.09.\n    Urlaub\n- 10:00 Zoo"
        self.schreibe("termine.txt", BLOCK.format(name="Kim", zeilen=zeilen))
        zeilen = self.lauf("--all").stdout.splitlines()
        self.assertIn("- Mo 28.09. at 18:00 - 19:00  belegt", zeilen)
        self.assertIn("- Di 29.09.  belegt", zeilen)
        self.assertEqual(zeilen.count("- belegt"), 2)
        for wort in ("Arzt", "Beispiel", "Zoo", "Yoga", "Urlaub"):
            self.assertNotIn(wort, "\n".join(zeilen))

    def test_kalendername_mit_backslash(self):
        """Review 21.10.2026: awk -v liest Backslashes als Escape, ein privater Kalender mit \\ im Namen erschien. Die
        Namen kommen jetzt über ENVIRON, auch bei --list."""
        name = "Tage\\buch"
        self.schreibe("config.json", json.dumps({"kalender": {**self.CFG, "private_calendars": ["Geheim", name]}}))
        self.schreibe("termine.txt", TERMINE + BLOCK.format(name=name, zeilen="- Mo 28.09. at 20:00 - 21:00\n    Notiz"))
        self.schreibe("kalender.txt", KALENDERLISTE + f"• {name}\n  type: CalDAV\n  UID: E5\n")
        for args in ((), ("--all",), ("--list",)):
            out = self.lauf(*args).stdout
            self.assertNotIn(name, out, args)
            self.assertNotIn("Notiz", out, args)

    def test_ausblenden_ueber_ec(self):
        self.lauf()
        a = self.argumente()
        self.assertEqual(a[a.index("-ec") + 1], "Geheim,Kim,Familie")
        self.lauf("--all")
        a = self.argumente()
        self.assertEqual(a[a.index("-ec") + 1], "Geheim")

    def test_ausgeblendete_kalender_fehlen_ohne_all_auch_im_nachfilter(self):
        """Prüfung 20.10.2026: hidden_calendars laufen ohne --all auch durch den awk-Nachfilter, weil icalBuddy -ec
        an Leerzeichen im Namen scheitert. Der Ersatz für icalBuddy liefert den Block trotz -ec."""
        out = self.lauf().stdout
        self.assertNotIn("Kim:", out)
        self.assertNotIn("Yoga", out)
        self.assertIn("Kim:", self.lauf("--all").stdout)

    def test_tage(self):
        for args, befehl in (((), "eventsToday+1"), (("7",), "eventsToday+7"), (("0",), "eventsToday"),
                             (("08",), "eventsToday+8")):
            self.assertEqual(self.lauf(*args).returncode, 0)
            self.assertEqual(self.argumente()[-1], befehl)

    def test_falsche_zahl(self):
        """Falscher Aufruf endet mit 2 wie bei den Python-Skripten (Prüfung 20.10.2026), Fehler beim Lesen mit 1."""
        for arg in ("7abc", "morgen", "-3", ""):
            r = self.lauf(arg)
            self.assertEqual(r.returncode, 2, arg)
            self.assertIn("Unbekanntes Argument", r.stderr)
        r = self.lauf("400")
        self.assertEqual(r.returncode, 2)
        self.assertIn("366", r.stderr)

    def test_list_mit_typ_ohne_private(self):
        r = self.lauf("--list")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), ["Kalender (Exchange)", "Privat (CalDAV)", "Kim (CalDAV)"])

    def test_arbeitskalender_fehlt(self):
        self.assertNotIn("Hinweis", self.lauf().stdout)
        self.schreibe("kalender.txt", KALENDERLISTE.replace("• Kalender\n", "• Kalender alt\n"))
        self.assertTrue(self.lauf().stdout.startswith("Hinweis: Der Arbeitskalender 'Kalender' fehlt"))
        self.schreibe("kalender.txt", KALENDERLISTE)
        self.schreibe("config.json", json.dumps({"kalender": {**self.CFG, "arbeitskalender": "Kal*"}}))  # zählt wörtlich, kein Muster
        self.assertTrue(self.lauf().stdout.startswith("Hinweis: Der Arbeitskalender 'Kal*' fehlt"))

    def test_warnungen_von_icalbuddy_nie_als_termin(self):
        """V3.1.2: stderr von icalBuddy lief mit 2>&1 durch den Filter und erschien als Terminzeile. Jetzt geht es nach
        stderr, ein Abbruch von icalBuddy endet mit eigener Meldung statt mit Keine Termine im Zeitraum."""
        self.schreibe("warnung.txt", "- Mo 28.09. at 08:00 - 09:00\n    Fremde Zeile\n")
        r = self.lauf()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Fremde Zeile", r.stdout)
        self.assertIn("Fremde Zeile", r.stderr)
        self.assertIn("Jour fixe", r.stdout)
        self.schreibe("exitcode.txt", "3")
        r = self.lauf()
        self.assertEqual(r.returncode, 1)
        self.assertIn("icalBuddy ist mit Code 3 abgebrochen", r.stderr)
        self.assertNotIn("Keine Termine", r.stdout)

    def test_kein_zugriff(self):
        self.schreibe("kalender.txt", "")
        r = self.lauf()
        self.assertEqual(r.returncode, 1)
        self.assertIn("Kein Zugriff auf Apple Kalender", r.stderr)

    def test_exit_code_von_icalbuddy(self):
        self.schreibe("exitcode.txt", "3")
        self.assertNotEqual(self.lauf().returncode, 0)

    def test_keine_termine(self):
        self.schreibe("termine.txt", "")
        self.assertEqual(self.lauf().stdout.strip(), "Keine Termine im Zeitraum.")

    def test_config_typfehler(self):
        self.schreibe("config.json", json.dumps({"kalender": {**self.CFG, "private_calendars": "Geheim"}}))
        r = self.lauf()
        self.assertEqual(r.returncode, 1)
        self.assertIn("private_calendars muss eine Liste", r.stderr)

    def test_bash_von_macos(self):
        if not os.path.exists("/bin/bash"):
            self.skipTest("kein /bin/bash")
        r = self.lauf("--all", bash="/bin/bash")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("belegt", r.stdout)


if __name__ == "__main__":
    unittest.main()
