#!/usr/bin/env python3
"""Termine in einem privaten Kalender verschieben (die Dauer bleibt) oder in einen anderen Kalender legen (die Zeit
bleibt).

Aufruf (startet als python3 und wechselt selbst in die .venv des Kits, dort liegt EventKit):
  python3 move_event.py [--ausfuehren] [--calendar "<Kalender>"] [--mit-teilnehmern] -- "<Titel-Teil>"
      "JJJJ-MM-TT HH:MM" "JJJJ-MM-TT HH:MM" ["JJJJ-MM-TT HH:MM" "JJJJ-MM-TT HH:MM" ...]
  Nach dem Titel-Teil folgen bisheriger und neuer Start paarweise, je Paar ein Termin. Der Titel-Teil passt ohne Groß-
  und Kleinschreibung. Ganztägige Termine mit 00:00 als Uhrzeit angeben, sie bleiben ganztägig und rücken um ganze Tage.
  python3 move_event.py [--ausfuehren] [--calendar "<Kalender>"] --nach-kalender "<Kalender>" -- "<Titel-Teil>"
      "JJJJ-MM-TT HH:MM" ["JJJJ-MM-TT HH:MM" ...]
  Kalender wechseln: nach dem Titel-Teil nur die Starts. Der Termin bleibt derselbe, EventKit setzt
  nur seinen Kalender, nichts wird gelöscht oder neu angelegt.

Ohne --calendar gilt default_calendar aus config.json. Quell- und Zielkalender müssen in allowed_calendars stehen, nie
private_calendars und nie Exchange-Kalender.
  python3 move_event.py --exchange [--ausfuehren] -- "<Titel-Teil>" "JJJJ-MM-TT HH:MM" "JJJJ-MM-TT HH:MM" ...
  Eigene Termine ohne Teilnehmer im Arbeitskalender verschieben (arbeitskalender aus config.json).
  --exchange steht als erstes Argument, der Server fragt dafür immer nach. Termine mit Teilnehmern verschiebt das Skript dort nie, auch nicht mit --mit-teilnehmern, und den
  Kalender wechselt es nicht.
Termine mit Teilnehmern verschiebt das Skript nur mit --mit-teilnehmern, denn je nach Konto gehen dann Updates an
alle. Den Kalender wechselt es bei ihnen nie, auch nicht mit dem Schalter: Je nach Konto gingen Absagen und neue
Einladungen an alle. Bei Serien rückt nur dieser eine Termin, den Kalender einer Serie wechselt das Skript nicht. Steht
im Zielkalender schon ein Termin mit gleichem Titel und Start, bricht der Wechsel ab.
Die Dauer zählt in Sekunden, eine Zeitumstellung kostet keine Stunde. Eine Startzeit, die es wegen der Zeitumstellung
zweimal oder gar nicht gibt, bricht ab.
Ohne --ausfuehren zeigt das Skript nur alt und neu und speichert nichts, das läuft ohne Rückfrage. Gespeichert wird nur
mit --ausfuehren, direkt hinter dem Skript, an anderer Stelle bricht das Skript ab. Abkürzungen der Optionen gelten nicht.
Passen mehrere Termine zur gleichen Zeit und heißt genau einer wie der Titel-Teil, rückt nur dieser. Passt zu einem der
Starts nicht genau ein Termin, ändert das Skript keinen. Nach dem Speichern lädt es die Termine frisch und nennt jede
Abweichung bei Zeit oder Kalender in einer Zeile Nachkontrolle.
"""
import argparse
import datetime as dt
import sys

import kit_basis
from eventkit_basis import konto, nsdate, nsdate_ts, pydt, store_with_access, ts, venv_starten, zeitraum
from kalender_basis import (EINE_MINUTE, EXCHANGE, dubletten, exchange_calendar, exchange_name, exchange_vorn, gewollt,
                            kalender_config, kalender_name, nachkontrolle, ortszeit_eindeutig, target_calendar)


def find_event(store, cal, part: str, old: dt.datetime) -> list:
    """Termine im Kalender cal mit part im Titel, die um old beginnen (auf eine Minute genau). Passen mehrere und heißen
    welche genau wie part (ohne Groß- und Kleinschreibung), gelten nur diese: Training trifft dann nicht auch Training B."""
    pred = store.predicateForEventsWithStartDate_endDate_calendars_(nsdate(old - EINE_MINUTE),
                                                                    nsdate(old + EINE_MINUTE), [cal])
    teil = part.casefold()
    treffer = [ev for ev in (store.eventsMatchingPredicate_(pred) or [])
               if teil in (ev.title() or "").casefold() and abs(ts(ev.startDate()) - old.timestamp()) < 60]
    genau = [ev for ev in treffer if (ev.title() or "").strip().casefold() == teil.strip()]
    return genau if len(treffer) > 1 and genau else treffer


def neue_zeiten(ev, new: dt.datetime):
    """(Start, Ende) nach dem Verschieben als Wanduhrzeit. Zeitlich gebunden: Dauer in Sekunden. Ganztägig: um ganze
    Kalendertage, damit der Termin nicht in einen weiteren Tag rutscht."""
    if ev.isAllDay():
        start, ende = pydt(ev.startDate()), pydt(ev.endDate())
        tage = dt.timedelta(days=(new.date() - start.date()).days)
        return start + tage, ende + tage
    dauer = ts(ev.endDate()) - ts(ev.startDate())
    beginn = new.timestamp()
    return dt.datetime.fromtimestamp(beginn), dt.datetime.fromtimestamp(beginn + dauer)


def starts(zeiten: list, wechsel: bool) -> list:
    """[(bisheriger Start, neuer Start, Text des bisherigen)]. Beim Kalenderwechsel ist der neue Start der bisherige.
    Eine ungerade Zahl beim Verschieben, ein falsches Format oder ein Start, der zweimal vorkommt, bricht ab."""
    if not wechsel and len(zeiten) % 2:
        sys.exit("Nach dem Titel-Teil folgen bisheriger und neuer Start paarweise, mit --nach-kalender nur die Starts. "
                 "Nichts geändert.")
    paare = [(s, s) for s in zeiten] if wechsel else list(zip(zeiten[::2], zeiten[1::2]))
    try:
        liste = [(dt.datetime.strptime(o.strip(), "%Y-%m-%d %H:%M"), dt.datetime.strptime(n.strip(), "%Y-%m-%d %H:%M"),
                  o.strip()) for o, n in paare]
    except ValueError:
        sys.exit("Starts als 'JJJJ-MM-TT HH:MM', ganztägig mit 00:00. Nichts geändert.")
    for old, new, _text in liste:
        for d in (old, new):
            ortszeit_eindeutig(d, "Nichts geändert.")
    alte = [old for old, _new, _text in liste]
    doppelt = next((text for old, _new, text in liste if alte.count(old) > 1), None)
    if doppelt:
        sys.exit(f"Start {doppelt} steht zweimal im Aufruf. Nichts geändert.")
    return liste


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 allow_abbrev=False)
    ap.add_argument("part", help="Teil des Titels")
    ap.add_argument("zeiten", nargs="+", metavar="START",
                    help="bisheriger und neuer Start paarweise (JJJJ-MM-TT HH:MM), mit --nach-kalender nur die Starts")
    ap.add_argument("--calendar", default=None, help="Standard: default_calendar aus config.json")
    ap.add_argument("--nach-kalender", default=None, help="Termine in diesen Kalender legen, die Zeit bleibt")
    ap.add_argument("--mit-teilnehmern", action="store_true", help="auch Termine mit Teilnehmern verschieben")
    ap.add_argument("--ausfuehren", action="store_true", help="wirklich ändern (fragt immer nach)")
    ap.add_argument(EXCHANGE, action="store_true", help="eigene Termine ohne Teilnehmer im Arbeitskalender (Profil privat)")
    vorn, rest = kit_basis.schalter_vorn(sys.argv[1:] if argv is None else list(argv), ("--ausfuehren", EXCHANGE))
    exchange = exchange_vorn(vorn)
    a = ap.parse_args(vorn + rest)
    if not a.part.strip():
        sys.exit("Titel-Teil fehlt. Nichts geändert.")
    if exchange and (a.nach_kalender is not None or a.mit_teilnehmern):
        sys.exit(f"Mit {EXCHANGE} nur verschieben, ohne --nach-kalender und --mit-teilnehmern: Im Arbeitskalender rücken "
                 f"nur eigene Termine ohne Teilnehmer. Nichts geändert.")

    cfg = kalender_config()
    cal_name = exchange_name(cfg, a.calendar) if exchange else kalender_name(cfg, a.calendar)
    wechsel = a.nach_kalender is not None
    if wechsel:
        if not a.nach_kalender.strip():  # sonst gälte default_calendar
            sys.exit("Zielkalender fehlt (--nach-kalender). Nichts geändert.")
        ziel_name = kalender_name(cfg, a.nach_kalender)
        if ziel_name == cal_name:
            sys.exit(f"Quell- und Zielkalender sind beide {cal_name}. Nichts geändert.")
    liste = starts(a.zeiten, wechsel)
    store = store_with_access("events")
    cal = exchange_calendar(store, cal_name) if exchange else target_calendar(store, cal_name, cfg)
    quelle = f"{cal_name}, Konto {konto(cal)}"
    ziel_cal = target_calendar(store, ziel_name, cfg) if wechsel else None

    plan, fehler = [], []  # plan: (Termin, neuer Start, neues Ende, alt als Text, neu als Text)
    for old, new, text in liste:
        hits = find_event(store, cal, a.part, old)
        if len(hits) != 1:
            namen = "; ".join(ev.title() or "?" for ev in hits)
            fehler.append(f"{len(hits)} Treffer für '{a.part}' mit Start {text} in {cal_name}"
                          f"{': ' + namen if namen else ''}.")
            continue
        ev = hits[0]
        ganz = bool(ev.isAllDay())
        alt = zeitraum(pydt(ev.startDate()), pydt(ev.endDate()), ganz)
        if wechsel:
            if ev.hasAttendees():
                fehler.append(f"'{ev.title()}' ({alt}) hat Teilnehmer. Den Kalender wechselt das Skript dann nicht, je "
                              f"nach Konto gingen Absagen und neue Einladungen an alle.")
            elif ev.hasRecurrenceRules():
                fehler.append(f"'{ev.title()}' ({alt}) ist ein Serientermin. Den Kalender einer Serie in Apple Kalender "
                              f"selbst wechseln.")
            elif dubletten(store, ziel_cal, ev.title() or "", pydt(ev.startDate())):
                fehler.append(f"In {ziel_name} steht schon '{ev.title()}' mit Start {alt}.")
            else:
                plan.append((ev, pydt(ev.startDate()), pydt(ev.endDate()), alt, alt))
            continue
        if ev.hasAttendees() and exchange:
            fehler.append(f"'{ev.title()}' hat Teilnehmer. Im Arbeitskalender verschiebt das Skript nur eigene Termine "
                          f"ohne Teilnehmer, das macht der Nutzer selbst im Kalenderprogramm.")
            continue
        if ev.hasAttendees() and not a.mit_teilnehmern:
            fehler.append(f"'{ev.title()}' hat Teilnehmer, je nach Konto bekommen alle ein Update. Nur mit "
                          f"--mit-teilnehmern verschieben.")
            continue
        start, ende = neue_zeiten(ev, new)
        plan.append((ev, start, ende, alt, zeitraum(start, ende, ganz)))
    if fehler:
        sys.exit("\n".join(fehler + ["Nichts geändert."]))

    if wechsel:
        von_nach = f"von {cal_name} (Konto {konto(cal)}) nach {ziel_name} (Konto {konto(ziel_cal)})"
        if len(plan) == 1:
            kopf, zeilen = f"{plan[0][0].title()}, {plan[0][3]}, {von_nach}", []
        else:
            kopf, zeilen = f"{len(plan)} Termine {von_nach}", [f"- {ev.title()}, {alt}" for ev, _s, _e, alt, _n in plan]
    elif len(plan) == 1:
        kopf, zeilen = f"{plan[0][0].title()} ({quelle}) von {plan[0][3]} auf {plan[0][4]}", []
    else:
        kopf, zeilen = (f"{len(plan)} Termine ({quelle})",
                        [f"- {ev.title()} von {alt} auf {neu}" for ev, _s, _e, alt, neu in plan])
    serie = ("Serientermin: nur dieser eine Termin rückt, die übrigen bleiben."
             if not wechsel and any(ev.hasRecurrenceRules() for ev, *_ in plan) else "")
    if not a.ausfuehren:
        print("\n".join([f"Probelauf, nichts gespeichert: {kopf}"] + zeilen + ([serie] if serie else [])))
        return

    erledigt, kontrolle = [], []
    for ev, start, ende, alt, _neu in plan:
        if wechsel:
            ev.setCalendar_(ziel_cal)  # derselbe Termin, nur der Kalender ändert sich
        else:
            ev.setStartDate_(nsdate_ts(start.timestamp()))
            ev.setEndDate_(nsdate_ts(ende.timestamp()))
        ok, err = store.saveEvent_span_commit_error_(ev, 0, True, None)  # 0 = EKSpanThisEvent, nie die ganze Serie
        if not ok:
            schon = f"Schon geändert: {'; '.join(erledigt)}. " if erledigt else ""
            sys.exit(f"Speichern fehlgeschlagen bei {ev.title()} ({alt}): {err}. {schon}Die übrigen nicht geändert.")
        erledigt.append(f"{ev.title()} ({alt})")
        kontrolle.append(gewollt(ev, start, ende, bool(ev.isAllDay()), (ziel_cal if wechsel else cal).title()))
    print("\n".join([f"{'Kalender gewechselt' if wechsel else 'Verschoben'}: {kopf}"] + zeilen
                    + ([serie] if serie else []) + nachkontrolle(store, kontrolle)))


if __name__ == "__main__":
    venv_starten(__file__)
    kit_basis.starten(main, __file__)
