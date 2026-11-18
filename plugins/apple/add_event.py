#!/usr/bin/env python3
"""Termine in einen privaten Kalender schreiben (Apple Kalender über EventKit), einen oder mehrere zum selben Titel.

Aufruf (startet als python3 und wechselt selbst in die .venv des Kits, dort liegt EventKit):
  python3 add_event.py [--ausfuehren] [--calendar "<Kalender>"] [--ort "<Ort>"] [--notiz "<Notiz>"] -- "<Titel>"
      "JJJJ-MM-TT HH:MM" "JJJJ-MM-TT HH:MM" ["JJJJ-MM-TT HH:MM" "JJJJ-MM-TT HH:MM" ...]
  Nach dem Titel folgen Start und Ende paarweise, je Paar ein Termin (etwa fünf Samstage in einem
  Aufruf und einer Rückfrage). Ort und Notiz gelten für alle Termine des Aufrufs.
  Ganztägig: Start und Ende als "JJJJ-MM-TT" ohne Uhrzeit. Das Ende ist der letzte Tag (inklusiv), anders als beim
  Microsoft-365-Connector, dort ist das Ende 00:00 Uhr des Folgetags (exklusiv).
  Optionen stehen vor "--", danach darf der Titel auch mit einem Bindestrich beginnen.

Ohne --calendar gilt default_calendar aus config.json. Erlaubt sind nur Kalender aus allowed_calendars, nie
private_calendars und nie Exchange-Kalender (Arbeitstermine laufen über den Connector, Skill /kalender).
  python3 add_event.py --exchange [--ausfuehren] [--ort "<Ort>"] [--notiz "<Notiz>"] -- "<Titel>" "<Start>" "<Ende>" ...
  Eigene Termine ohne Teilnehmer im Arbeitskalender (arbeitskalender aus config.json). --exchange
  steht als erstes Argument, der Server fragt dafür immer nach (Werkzeug termin_mit_nachfrage).
  Teilnehmer setzt das Skript nie.
Ohne --ausfuehren zeigt das Skript nur die Vorschau (Kalender mit Konto und alle Zeiten) und speichert nichts, das läuft
ohne Rückfrage. Gespeichert wird nur mit --ausfuehren. Der
Schalter steht direkt hinter dem Skript, an anderer Stelle bricht das Skript ab. Abkürzungen der Optionen
gelten nicht.
Steht im Zielkalender schon ein Termin mit gleichem Titel und Start, steht ein Start zweimal im Aufruf oder gibt es eine
Uhrzeit wegen der Zeitumstellung zweimal oder gar nicht, bricht das Skript ab, bevor es etwas anlegt. Nach dem Speichern
lädt es die Termine frisch und nennt jede Abweichung bei Zeit oder Kalender in einer Zeile Nachkontrolle.
"""
import argparse
import datetime as dt
import sys

import kit_basis
from eventkit_basis import konto, nsdate, store_with_access, venv_starten, zeitraum
from kalender_basis import (EXCHANGE, dubletten, exchange_calendar, exchange_name, exchange_vorn, gewollt,
                            kalender_config, kalender_name, nachkontrolle, ortszeit_eindeutig, target_calendar)


def parse_range(start_s: str, end_s: str):
    """(Start, Ende, ganztägig). Ganztägig: beide als JJJJ-MM-TT, das Ende wird 23:59 des letzten Tags. Sonst beide mit
    Uhrzeit, als Wanduhrzeit in der Zeitzone des Macs, die es dort genau einmal geben muss. Ein gemischtes Format bricht
    ab."""
    start_s, end_s = start_s.strip(), end_s.strip()
    try:
        if len(start_s) == 10 and len(end_s) == 10:
            start = dt.datetime.strptime(start_s, "%Y-%m-%d")
            end = dt.datetime.strptime(end_s, "%Y-%m-%d") + dt.timedelta(hours=23, minutes=59)
            ganz = True
        else:
            start = dt.datetime.strptime(start_s, "%Y-%m-%d %H:%M")
            end = dt.datetime.strptime(end_s, "%Y-%m-%d %H:%M")
            ganz = False
    except ValueError:
        sys.exit(f"'{start_s}' '{end_s}': Start und Ende als 'JJJJ-MM-TT HH:MM', ganztägig beide als 'JJJJ-MM-TT'. Ort "
                 f"und Notiz stehen als --ort und --notiz vor --. Nichts angelegt.")
    if end <= start:
        sys.exit(f"Ende ({end_s}) liegt nicht nach dem Start ({start_s}). Nichts angelegt.")
    if not ganz:  # ganztägig zählt nur der Tag
        for d in (start, end):
            ortszeit_eindeutig(d, "Nichts angelegt.")
    return start, end, ganz


def zeitraeume(zeiten: list) -> list:
    """[(Start, Ende, ganztägig)] aus den Paaren nach dem Titel. Eine ungerade Zahl oder ein Start, der zweimal vorkommt,
    bricht ab."""
    if len(zeiten) % 2:
        sys.exit("Nach dem Titel folgen Start und Ende paarweise, je Paar ein Termin. Ort und Notiz stehen als --ort und "
                 "--notiz vor --. Nichts angelegt.")
    liste = [parse_range(s, e) for s, e in zip(zeiten[::2], zeiten[1::2])]
    starts = [s for s, _e, _g in liste]
    doppelt = next((x for x in liste if starts.count(x[0]) > 1), None)
    if doppelt:
        sys.exit(f"Start {zeitraum(*doppelt)} steht zweimal im Aufruf. Nichts angelegt.")
    return liste


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 allow_abbrev=False)
    ap.add_argument("title")
    ap.add_argument("zeiten", nargs="+", metavar="START ENDE",
                    help="paarweise: JJJJ-MM-TT HH:MM oder JJJJ-MM-TT für ganztägig (Ende ist der letzte Tag)")
    ap.add_argument("--calendar", default=None, help="Standard: default_calendar aus config.json")
    ap.add_argument("--ort", default="", help="Ort für alle Termine des Aufrufs")
    ap.add_argument("--notiz", default="", help="Notiz für alle Termine des Aufrufs")
    ap.add_argument("--ausfuehren", action="store_true", help="wirklich speichern (fragt immer nach)")
    ap.add_argument(EXCHANGE, action="store_true", help="eigener Termin ohne Teilnehmer im Arbeitskalender (Profil privat)")
    vorn, rest = kit_basis.schalter_vorn(sys.argv[1:] if argv is None else list(argv), ("--ausfuehren", EXCHANGE))
    exchange = exchange_vorn(vorn)
    a = ap.parse_args(vorn + rest)
    if not a.title.strip():
        sys.exit("Titel fehlt. Nichts angelegt.")

    cfg = kalender_config()
    cal_name = exchange_name(cfg, a.calendar) if exchange else kalender_name(cfg, a.calendar)
    termine = zeitraeume(a.zeiten)
    store = store_with_access("events")
    cal = exchange_calendar(store, cal_name) if exchange else target_calendar(store, cal_name, cfg)
    ziel = f"Kalender {cal_name} (Konto {konto(cal)})"
    schon = [f"In {ziel} steht schon '{a.title}' mit Start {zeitraum(*t)}." for t in termine
             if dubletten(store, cal, a.title, t[0])]
    if schon:
        sys.exit("\n".join(schon + ["Nichts angelegt."]))
    ort = f", Ort {a.ort}" if a.ort else ""
    if len(termine) == 1:
        kopf, zeilen = f"{a.title}, {zeitraum(*termine[0])}{ort}, {ziel}", []
    else:
        kopf, zeilen = f"{len(termine)} Termine {a.title}{ort}, {ziel}", [f"- {zeitraum(*t)}" for t in termine]
    if not a.ausfuehren:
        print("\n".join([f"Probelauf, nichts gespeichert: {kopf}"] + zeilen))
        return

    import EventKit  # erst hier: store_with_access hat es schon geladen oder mit Hinweis auf .venv abgebrochen
    angelegt, kontrolle = [], []
    for start, end, ganz in termine:
        ev = EventKit.EKEvent.eventWithEventStore_(store)
        ev.setCalendar_(cal)
        ev.setTitle_(a.title)
        ev.setStartDate_(nsdate(start))
        ev.setEndDate_(nsdate(end))
        if ganz:
            ev.setAllDay_(True)
        if a.ort:
            ev.setLocation_(a.ort)
        if a.notiz:
            ev.setNotes_(a.notiz)
        ok, err = store.saveEvent_span_commit_error_(ev, 0, True, None)
        if not ok:
            schon_da = f"Schon angelegt: {'; '.join(angelegt)}. " if angelegt else ""
            sys.exit(f"Fehler beim Speichern von {zeitraum(start, end, ganz)}: {err}. {schon_da}Die übrigen nicht "
                     f"angelegt.")
        angelegt.append(zeitraum(start, end, ganz))
        kontrolle.append(gewollt(ev, start, end, ganz, cal.title()))
    print("\n".join([f"Angelegt: {kopf}"] + zeilen + nachkontrolle(store, kontrolle)))


if __name__ == "__main__":
    venv_starten(__file__)
    kit_basis.starten(main, __file__)
