"""Ersatz für EventKit und Foundation, gemeinsam für alle Tests des Plugins: ein Store aus Kalendern, Terminen und
Erinnerungen, dazu die Basisklasse KitTest. Seit 7.0 nur im Plugin apple.

Eine Datei für alle Tests, weil unittest discover erst alle Testdateien importiert und dann laufen lässt: Setzte jede
Datei eigene Ersatzmodule, gälten am Ende die der zuletzt importierten. Zeitzone fest Europe/Berlin, damit die Fälle zur
Zeitumstellung am 25.10.2026 überall gleich rechnen. Läuft in der Sandbox.
"""
import contextlib
import datetime as dt
import io
import json
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True  # kein __pycache__ im Kit
os.environ["TZ"] = "Europe/Berlin"
os.environ.setdefault("KITS_FEHLERPROTOKOLL", "aus")  # Testläufe schreiben nicht ins Fehlerprotokoll des Pakets
time.tzset()

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))


def D(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M")


# ---------- Ersatz für Foundation und EventKit ----------

class NSDate:
    def __init__(self, t):
        self.t = float(t)

    @classmethod
    def dateWithTimeIntervalSince1970_(cls, t):
        return cls(t)

    def timeIntervalSince1970(self):
        return self.t


class NSDateComponents:
    UNDEFINIERT = sys.maxsize  # wie NSDateComponentUndefined

    @classmethod
    def alloc(cls):
        return cls()

    def init(self):
        self.w = {}
        return self

    def setYear_(self, v):
        self.w["year"] = v

    def setMonth_(self, v):
        self.w["month"] = v

    def setDay_(self, v):
        self.w["day"] = v

    def setHour_(self, v):
        self.w["hour"] = v

    def setMinute_(self, v):
        self.w["minute"] = v

    def year(self):
        return self.w.get("year", self.UNDEFINIERT)

    def month(self):
        return self.w.get("month", self.UNDEFINIERT)

    def day(self):
        return self.w.get("day", self.UNDEFINIERT)

    def hour(self):
        return self.w.get("hour", self.UNDEFINIERT)

    def minute(self):
        return self.w.get("minute", self.UNDEFINIERT)


class Quelle:
    def __init__(self, titel, typ):
        self._titel, self._typ = titel, typ

    def title(self):
        return self._titel

    def sourceType(self):
        return self._typ


ICLOUD = Quelle("iCloud", 2)            # EKSourceTypeCalDAV
LOKAL = Quelle("Auf meinem Mac", 0)     # EKSourceTypeLocal
EXCHANGE = Quelle("Firma", 1)          # EKSourceTypeExchange


class Kalender:
    def __init__(self, titel, quelle=ICLOUD, typ=1, art=0):  # typ: EKCalendarType, art: 0 Termine, 1 Erinnerungen
        self._titel, self._quelle, self._typ, self.art = titel, quelle, typ, art

    def title(self):
        return self._titel

    def source(self):
        return self._quelle

    def type(self):
        return self._typ


def Liste(titel, quelle=ICLOUD):
    return Kalender(titel, quelle, art=1)


class Termin:
    def __init__(self, store=None, titel="", start=None, ende=None, kalender=None, ganztaegig=False,
                 teilnehmer=False, serie=False):
        self._titel, self._kalender, self._ganz = titel, kalender, ganztaegig
        self._start = NSDate(D(start).timestamp()) if start else None
        self._ende = NSDate(D(ende).timestamp()) if ende else None
        self._teilnehmer, self._serie = teilnehmer, serie
        self.ort = self.notiz = None

    @classmethod
    def eventWithEventStore_(cls, store):
        return cls(store)

    def title(self):
        return self._titel

    def setTitle_(self, v):
        self._titel = v

    def startDate(self):
        return self._start

    def setStartDate_(self, v):
        self._start = v

    def endDate(self):
        return self._ende

    def setEndDate_(self, v):
        self._ende = v

    def calendar(self):
        return self._kalender

    def setCalendar_(self, v):
        self._kalender = v

    def isAllDay(self):
        return self._ganz

    def setAllDay_(self, v):
        self._ganz = v

    def setLocation_(self, v):
        self.ort = v

    def setNotes_(self, v):
        self.notiz = v

    def hasAttendees(self):
        return self._teilnehmer

    def hasRecurrenceRules(self):
        return self._serie


class Erinnerung:
    def __init__(self, store=None, titel="", liste=None, faellig=None, mit_zeit=True, erledigt=False, angelegt=None,
                 erledigt_am=None, notiz=None):
        self._titel, self._liste, self._erledigt = titel, liste, erledigt
        self._comp, self.alarme, self.notiz = None, [], notiz
        # wie EventKit: Anlage- und Erledigtdatum als NSDate oder None (V3 Phase 4a, Verlauf im Tagesstart), erledigt
        # ohne Datum heißt jetzt erledigt
        self._angelegt = NSDate(angelegt.timestamp()) if angelegt else None
        self._erledigt_am = (NSDate(erledigt_am.timestamp()) if erledigt_am else NSDate(time.time()) if erledigt
                             else None)
        if faellig:
            self._comp = NSDateComponents().init()
            self._comp.setYear_(faellig.year)
            self._comp.setMonth_(faellig.month)
            self._comp.setDay_(faellig.day)
            if mit_zeit:
                self._comp.setHour_(faellig.hour)
                self._comp.setMinute_(faellig.minute)

    @classmethod
    def reminderWithEventStore_(cls, store):
        return cls(store)

    def title(self):
        return self._titel

    def setTitle_(self, v):
        self._titel = v

    def calendar(self):
        return self._liste

    def setCalendar_(self, v):
        self._liste = v

    def setNotes_(self, v):
        self.notiz = v

    def notes(self):
        return self.notiz

    def creationDate(self):
        return self._angelegt

    def completionDate(self):
        return self._erledigt_am

    def isCompleted(self):
        return self._erledigt

    def setCompleted_(self, v):
        self._erledigt = v
        self._erledigt_am = NSDate(time.time()) if v else None  # wie EventKit: Abhaken setzt das Erledigtdatum

    def dueDateComponents(self):
        return self._comp

    def setDueDateComponents_(self, v):
        self._comp = v

    def addAlarm_(self, a):
        self.alarme.append(a)


class EKAlarm:
    @classmethod
    def alarmWithAbsoluteDate_(cls, datum):
        a = cls()
        a.datum = datum
        return a


class ErledigtAbfrage:
    """Prädikat für erledigte Erinnerungen: Listen (None heißt alle, wie EventKit) und Zeitraum der Erledigung."""

    def __init__(self, s, e, cals):
        self.von, self.bis = (s.t if s else None), (e.t if e else None)
        self.listen = list(cals) if cals else None

    def passt(self, r) -> bool:
        am = r.completionDate()
        return (r.isCompleted() and am is not None and (self.listen is None or r.calendar() in self.listen)
                and (self.von is None or am.t >= self.von) and (self.bis is None or am.t <= self.bis))


class Store:
    def __init__(self, kalender=(), termine=(), erinnerungen=(), zugriff=True, antwortet=True):
        self.kalender, self.termine, self.erinnerungen = list(kalender), list(termine), list(erinnerungen)
        self.zugriff, self.antwortet = zugriff, antwortet  # zugriff None: der Freigabe-Dialog antwortet nie
        self.gespeichert, self.abfragen = [], []

    def init(self):
        return self

    def requestFullAccessToEventsWithCompletion_(self, cb):
        if self.zugriff is not None:
            cb(self.zugriff, None)

    requestFullAccessToRemindersWithCompletion_ = requestFullAccessToEventsWithCompletion_

    def calendarsForEntityType_(self, art):
        return [k for k in self.kalender if k.art == art]

    def predicateForEventsWithStartDate_endDate_calendars_(self, s, e, cals):
        return s.t, e.t, list(cals)

    def eventsMatchingPredicate_(self, pred):
        s, e, cals = pred  # wie EventKit: alle Termine, die den Zeitraum überlappen
        return [t for t in self.termine if t.calendar() in cals and t.startDate().t < e and t.endDate().t > s]

    def saveEvent_span_commit_error_(self, ev, span, commit, err):
        self.gespeichert.append((ev, span))
        if ev not in self.termine:
            self.termine.append(ev)
        return True, None

    def predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(self, s, e, cals):
        self.abfragen.append(cals)
        return list(cals) if cals else None  # wie EventKit: ohne Auswahl gelten alle Listen

    def predicateForCompletedRemindersWithCompletionDateStarting_ending_calendars_(self, s, e, cals):
        self.abfragen.append(cals)
        return ErledigtAbfrage(s, e, cals)

    def fetchRemindersMatchingPredicate_completion_(self, pred, cb):
        if not self.antwortet:
            return
        if isinstance(pred, ErledigtAbfrage):
            cb([r for r in self.erinnerungen if pred.passt(r)])
        else:
            cb([r for r in self.erinnerungen if (pred is None or r.calendar() in pred) and not r.isCompleted()])

    def saveReminder_commit_error_(self, r, commit, err):
        self.gespeichert.append((r, None))
        if r not in self.erinnerungen:
            if r.creationDate() is None:
                r._angelegt = NSDate(time.time())  # wie EventKit: das erste Speichern setzt das Anlagedatum
            self.erinnerungen.append(r)
        return True, None


class EKEventStore:
    naechster = None  # Store, den store_with_access als nächstes bekommt

    @classmethod
    def alloc(cls):
        return cls.naechster


EventKit = types.ModuleType("EventKit")
EventKit.EKEventStore, EventKit.EKEvent, EventKit.EKReminder, EventKit.EKAlarm = EKEventStore, Termin, Erinnerung, EKAlarm
Foundation = types.ModuleType("Foundation")
Foundation.NSDate, Foundation.NSDateComponents = NSDate, NSDateComponents
sys.modules["EventKit"], sys.modules["Foundation"] = EventKit, Foundation

import eventkit_basis  # noqa: E402

# Abschnitt kalender der config.json (7.0: eine Datei mit Abschnitten), dazu der Abschnitt reminders
CFG = {"default_calendar": "Privat", "allowed_calendars": ["Privat", "T&L Kalender", "Geheim"],
       "private_calendars": ["Geheim"]}
REMINDERS = {"excluded_lists": ["Tagebuch"], "geteilte_listen": ["Einkaufsliste"]}
ABSCHNITTE = ("mail", "notizen", "reminders", "kontakte")


class KitTest(unittest.TestCase):
    """Config aus einer Temp-Datei, kein Warten in den Schleifen, Store und Aufruf mit Ausgabe und Exit-Meldung."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg_pfad = Path(tmp.name) / "config.json"
        self.config()
        for p in (mock.patch.object(eventkit_basis, "CONFIG_PATH", self.cfg_pfad),
                  mock.patch("time.sleep", lambda s: None)):
            p.start()
            self.addCleanup(p.stop)

    def config(self, **aenderungen):
        """Abschnitte (reminders, kontakte) ersetzen ihren Block, alle anderen Schlüssel gehen in den Abschnitt kalender."""
        oben = {k: v for k, v in aenderungen.items() if k in ABSCHNITTE}
        kalender = {**CFG, **{k: v for k, v in aenderungen.items() if k not in ABSCHNITTE}}
        self.cfg_pfad.write_text(json.dumps({"kalender": kalender, "reminders": REMINDERS, **oben}), encoding="utf-8")

    def store(self, **kw) -> Store:
        EKEventStore.naechster = Store(**kw)
        return EKEventStore.naechster

    def lauf(self, main, *argv):
        """(Ausgabe, Exit-Meldung oder None)."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                main(list(argv))
            except SystemExit as e:
                return out.getvalue(), e.code
        return out.getvalue(), None
