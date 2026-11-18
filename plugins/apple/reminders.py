#!/usr/bin/env python3
"""Apple-Erinnerungen lesen und schreiben (EventKit).

Aufruf (startet als python3 und wechselt selbst in die .venv des Kits, dort liegt EventKit):
  reminders.py list [--days N] [--all]     offene, überfällige und in N Tagen fällige (Standard 14, 0 bis 3650), --all
                                           auch ohne Frist
  reminders.py list --verlauf "<Liste>" [--days N]   die Liste ganz (auch ohne Frist) mit Anlagedatum, Notiz und
                                           Liegezeit, dazu die erledigten seit 0 Uhr vor 14 Tagen (15 Kalendertage mit
                                           heute). Andere Listen nur mit --days
  reminders.py lists                       alle Listen mit Konto
  reminders.py add "<Liste>" "<Titel>" [JJJJ-MM-TT [HH:MM] ...] [--notes "Text"]   mehrere Fristen zum selben Titel
                                           in einem Aufruf: je Frist eine Erinnerung, ein
                                           Speichern für alle
  reminders.py done "<Titel>" [--liste "<Liste>"]   Titel, wie list ihn zeigt, sonst Kandidaten zeigen und nichts
                                           ändern, --liste bei gleichem Titel in zwei Listen
  --ausfuehren wirkt nicht und steht, wenn überhaupt, direkt hinter dem Skript, an anderer Stelle bricht das
  Skript ab

Listen aus reminders.excluded_lists in config.json werden nie gelesen oder beschrieben.
add und done schreiben in alle Listen direkt, auch in geteilte aus reminders.geteilte_listen (die
Erinnerungen sind die eigene App des Nutzers, der Auftrag ist die Freigabe). lists markiert geteilte Listen weiter mit (geteilt).
Abkürzungen der Optionen gelten nicht. Gibt es eine Liste in zwei Konten mit gleichem Namen, liest das Skript beide
und schreibt in keine. Steht in der Liste schon eine offene Erinnerung mit gleichem Titel und gleicher Frist, legt add
nichts an, auch keine der anderen Fristen.
"""
import argparse
import datetime as dt
import re
import sys
import time
import unicodedata

import kit_basis  # Nummern, Steuerzeichen, Datenhinweis, gleich in apple und chat
from eventkit_basis import (EK_REMINDER, konto, load_config, namen, nsdate, ortszeit_eindeutig, pydt, store_with_access,
                            tag, uhr, venv_starten)

UNDEFINIERT = 9000  # NSDateComponentUndefined ist NSIntegerMax, echte Werte liegen weit darunter
HINWEIS = f"({kit_basis.daten_hinweis('Inhalte von Erinnerungen')})"
# --verlauf (Aufgaben-Screening im Tagesstart): Erledigtes ab 0 Uhr vor so vielen Tagen (mit heute ein
# Kalendertag mehr), damit der Tagesstart nichts erneut vorschlägt, ab so vielen Werktagen ohne Frist gilt ein Eintrag
# als liegen geblieben (älter als 5), Notizen werden auf so viele Zeichen gekürzt
VERLAUF_TAGE = 14
LIEGT_AB = 6
NOTIZ_MAX = 80
DAYS_MAX = 3650  # --days höchstens zehn Jahre, darüber endete list mit OverflowError (Review 21.10.2026)
# Notizen zeigt --verlauf nur bei Einträgen mit Vorsatz (Konvention der Liste Aufgaben im Skill /erinnerungen, dort
# steht die Quelle in eigenen Worten). Eigene Notizen ohne Vorsatz bleiben draußen (am 20.10.2026 stand in einer eine
# Kontonummer), Nummern werden auch mit Vorsatz maskiert (kit_basis.NUMMER: IBAN, ab 6 Zeichen aus Ziffern und
# Trennern, Zifferngruppen mit Punkten ab 3 Ziffern vorn, ein Datum wie 20.10.2026 bleibt)
VORSAETZE = ("arbeit:", "privat:")
# add: ein Wort, das wie ein Datum aussieht (2026-09-30, auch deutsch 30.09.2026), gilt als neue Frist, sonst als
# Uhrzeit der vorigen. So meldet 30.09.2026 das Datumsformat und 18 Uhr das Format der Uhrzeit
DATUM_ARTIG = re.compile(r"\s*(\d{4}-|\d{1,2}\.\d{1,2}\.)")


def sauber(s) -> str:
    """Titel, Listennamen und Notizen für die Ausgabe: ohne Terminalsteuerfolgen, Steuer- und Richtungszeichen
    (kit_basis, Prüfung 20.10.2026), ohne unsichtbare Formatzeichen der Unicode-Kategorie Cf wie Nullbreite (Review
    20.10.2026), eine Zeile. Anders als kit_basis.ohne_formatzeichen fällt auch der Verbinder U+200D weg:
    Zwischen Ziffern trennte er eine Nummer vor dem Maskieren ab, in einem Titel fände done ihn sonst nie."""
    return " ".join(kit_basis.ohne_formatzeichen(s).replace("\N{ZERO WIDTH JOINER}", "").split())


def name_norm(s) -> str:
    """Listennamen und Titel vergleichen ohne Groß- und Kleinschreibung und Unicode-Form (Prüfung 20.10.2026):
    Ausschlüsse und geteilte Listen gelten auch in anderer Schreibweise. Verglichen wird, was die Ausgabe zeigt (sauber,
    Review 21.10.2026): Zwei Leerzeichen, eines am Ende oder ein unsichtbares Zeichen ließen done sonst nie abhaken."""
    return " ".join(unicodedata.normalize("NFC", sauber(s)).casefold().split())


def listen(store, exclude) -> list:
    """Alle Erinnerungslisten außer den ausgeschlossenen (normierte Namen), gleichnamige aus Konten einzeln."""
    return [c for c in store.calendarsForEntityType_(EK_REMINDER) if name_norm(c.title()) not in exclude]


def liste_fehlt(name: str, alle) -> None:
    """Unbekannte und gesperrte Liste melden sich gleich, damit kein Name einen Ausschluss bestätigt (Review
    21.10.2026), alle Namen bereinigt."""
    sys.exit(f"Liste '{sauber(name)}' nicht gefunden oder gesperrt. Vorhanden: "
             f"{', '.join(sorted({sauber(c.title()) for c in alle}))}")


def ziel_liste(store, exclude, name: str):
    """Genau eine Liste mit dem Namen, sonst Abbruch: Bei Dubletten landet nichts zufällig im falschen Konto. Dubletten
    sind mehrdeutig und enden mit Code 2 (Prüfung 20.10.2026)."""
    alle = listen(store, exclude)
    treffer = [c for c in alle if name_norm(c.title()) == name_norm(name)]
    if not treffer:
        liste_fehlt(name, alle)
    if len(treffer) > 1:
        aufruf_falsch(f"Liste '{sauber(name)}' gibt es {len(treffer)} Mal (Konten: "
                      f"{', '.join(sauber(konto(c)) for c in treffer)}). Eine davon in Erinnerungen umbenennen, sonst "
                      f"landet der Eintrag womöglich in der falschen. Nichts angelegt.")
    return treffer[0]


def fetch(store, cals, exclude, erledigt_seit=None) -> list:
    """Offene Erinnerungen der Listen, mit erledigt_seit (datetime) stattdessen die seitdem erledigten. Eine
    Zeitüberschreitung ist ein Fehler, nie eine leere Liste."""
    if not cals:
        return []  # EventKit läse mit einer leeren Auswahl womöglich alle Listen, auch ausgeschlossene
    if erledigt_seit is None:
        pred = store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(None, None, cals)
    else:
        pred = store.predicateForCompletedRemindersWithCompletionDateStarting_ending_calendars_(
            nsdate(erledigt_seit), None, cals)
    state = {"done": False, "items": []}

    def cb(items):
        state["items"] = list(items or [])
        state["done"] = True
    store.fetchRemindersMatchingPredicate_completion_(pred, cb)
    for _ in range(600):
        if state["done"]:
            break
        time.sleep(0.05)
    if not state["done"]:
        sys.exit("Erinnerungen nicht geladen: keine Antwort nach 30 Sekunden. Nichts geändert, bitte erneut versuchen.")
    erledigt = erledigt_seit is not None
    return [r for r in state["items"]
            if bool(r.isCompleted()) == erledigt and name_norm(r.calendar().title()) not in exclude]


def due_of(r):
    """(Fälligkeit, mit Uhrzeit) oder None."""
    c = r.dueDateComponents()
    if c is None:
        return None
    y, m, d = c.year(), c.month(), c.day()
    if y > UNDEFINIERT or m > UNDEFINIERT or d > UNDEFINIERT:
        return None
    h, mi = c.hour(), c.minute()
    has_time = h < UNDEFINIERT and mi < UNDEFINIERT
    return dt.datetime(y, m, d, h if has_time else 0, mi if has_time else 0), has_time


def listenname(cal, doppelt) -> str:
    """Listenname für die Ausgabe, bei gleichen Namen mit Konto, beides bereinigt (Review 21.10.2026)."""
    return f"{sauber(cal.title())} ({sauber(konto(cal))})" if cal.title() in doppelt else sauber(cal.title())


def doppelte_namen(cals) -> set:
    gesehen, doppelt = set(), set()
    for c in cals:
        (doppelt if c.title() in gesehen else gesehen).add(c.title())
    return doppelt


def cmd_lists(store, exclude, geteilte):
    for c in listen(store, exclude):  # ausgeschlossene Listen gibt es für Claude nicht, auch nicht als Name
        flag = "  (geteilt)" if name_norm(c.title()) in geteilte else ""
        print(f"{sauber(c.title()):30s} {sauber(konto(c))}{flag}")
    vorhanden = {name_norm(c.title()) for c in store.calendarsForEntityType_(EK_REMINDER)}
    ohne = [x for x in exclude | geteilte if x not in vorhanden]
    if ohne:  # wie whatsapp.py check: nur die Zahl, kein Name
        print(f"Hinweis: {len(ohne)} Einträge in config.json (excluded_lists, geteilte_listen) passen zu keiner Liste.")


def aufruf_falsch(text: str):
    """Falscher Aufruf: Text auf stderr, Exit 2 wie bei allen Kits (Fehler mit nichts geändert ist 1)."""
    print(text, file=sys.stderr)
    sys.exit(2)


def faellig_flag(d: dt.datetime, heute: dt.date) -> str:
    return "ÜBERFÄLLIG " if d.date() < heute else ("HEUTE " if d.date() == heute else "")


def gruppen(store, exclude, cals, horizon: dt.date, show_all: bool, heute: dt.date) -> dict:
    """{Listenname: [(Schlüssel, Zeile)]}: offene Einträge mit Frist bis horizon, ohne Frist nur mit show_all."""
    doppelt = doppelte_namen(cals)
    groups = {}
    for r in fetch(store, cals, exclude):
        due = due_of(r)
        if due is None:
            if not show_all:
                continue
            key, line = (1, dt.datetime.max, sauber(r.title())), f"- {sauber(r.title())}"
        else:
            d, has_time = due
            if d.date() > horizon:
                continue
            when = tag_j(d, heute) + (f", {uhr(d)} Uhr" if has_time else "")
            key, line = (0, d, sauber(r.title())), f"- {faellig_flag(d, heute)}{when}  {sauber(r.title())}"
        groups.setdefault(listenname(r.calendar(), doppelt), []).append((key, line))
    return groups


def drucke(groups: dict):
    for name in sorted(groups):
        print(f"{sauber(name)}:")
        for _, line in sorted(groups[name], key=lambda t: t[0]):
            print("  " + line)


def werktage(von: dt.date, bis: dt.date) -> int:
    """Werktage (Mo bis Fr, ohne Feiertage) nach von bis einschließlich bis, 0 wenn bis nicht später liegt."""
    tage = (bis - von).days
    if tage <= 0:
        return 0
    wochen, rest = divmod(tage, 7)
    return wochen * 5 + sum(1 for i in range(1, rest + 1) if (von + dt.timedelta(days=wochen * 7 + i)).weekday() < 5)


def datum_von(nsd):
    """Lokales Datum eines NSDate, None bleibt None (EventKit liefert nicht für jeden Eintrag eins)."""
    return pydt(nsd).date() if nsd is not None else None


def tag_j(d, heute: dt.date) -> str:
    """Wie tag, aus einem anderen Jahr mit Jahreszahl (Fr 24.10.2025), sonst sähe es nach diesem Jahr aus."""
    return tag(d) + (str(d.year) if d.year != heute.year else "")


def notiz_kurz(r) -> str:
    """Notiz nur bei Einträgen mit Vorsatz: eine Zeile ohne Steuerzeichen und Nummern, höchstens NOTIZ_MAX Zeichen,
    gekürzt am Wortende. Zeilenumbrüche werden zu Leerzeichen, sonst klebten die Wörter zweier Zeilen aneinander."""
    if not sauber(r.title()).casefold().startswith(VORSAETZE):
        return ""
    n = kit_basis.maskiere_nummern(sauber(re.sub(r"[\r\n\t\v\f  ]+", " ", r.notes() or "")))
    if len(n) <= NOTIZ_MAX:
        return n
    kurz = n[:NOTIZ_MAX]
    return (kurz.rsplit(" ", 1)[0] if " " in kurz else kurz) + " [gekürzt]"


def verlauf_listen(alle, name: str) -> list:
    """Alle freien Listen mit diesem Namen (in zwei Konten beide, lesen schadet nicht). Gesperrte fehlen schon in alle
    und melden sich wie unbekannte, damit ein geratener Name nicht verrät, dass es die Liste gibt."""
    treffer = [c for c in alle if name_norm(c.title()) == name_norm(name)]
    if not treffer:
        sys.exit(f"Liste '{sauber(name)}' nicht gefunden oder gesperrt, nichts gelesen. Vorhanden: "
                 f"{', '.join(sorted({sauber(c.title()) for c in alle}))}")
    return treffer


def zeile_offen(r, heute: dt.date) -> tuple:
    """(Schlüssel, Zeile) im Verlauf: Fälliges nach Frist, ohne Frist die ältesten zuerst, ohne Anlagedatum zuletzt."""
    angelegt = datum_von(r.creationDate())
    zusatz = [f"angelegt {tag_j(angelegt, heute)}"] if angelegt else []
    due = due_of(r)
    if due is None:
        when, key = "ohne Frist", (1, angelegt or dt.date.max, sauber(r.title()))
        liegt = werktage(angelegt, heute) if angelegt else 0
        if liegt >= LIEGT_AB:
            zusatz.append(f"liegt seit {liegt} Werktagen")
    else:
        d, has_time = due
        when = faellig_flag(d, heute) + tag_j(d, heute) + (f", {uhr(d)} Uhr" if has_time else "")
        key = (0, d, sauber(r.title()))
    notiz = notiz_kurz(r)
    if notiz:
        zusatz.append(f"Notiz: {notiz}")
    return key, f"- {when}  {sauber(r.title())}" + (f"  ({', '.join(zusatz)})" if zusatz else "")


def zeile_erledigt(r, heute: dt.date) -> tuple:
    am = datum_von(r.completionDate())
    notiz = notiz_kurz(r)
    zeile = f"- erledigt {tag_j(am, heute) if am else 'ohne Datum'}  {sauber(r.title())}"
    return (am or dt.date.min, sauber(r.title())), zeile + (f"  (Notiz: {notiz})" if notiz else "")


def drucke_verlauf(store, exclude, cal, doppelt, heute: dt.date):
    """Eine Liste ganz: offene Einträge mit Anlagedatum, Liegezeit und Notiz, dann die erledigten seit 0 Uhr vor
    VERLAUF_TAGE Tagen (VERLAUF_TAGE + 1 Kalendertage mit heute), neueste zuerst. Kopf und Zahlen auch, wenn nichts
    offen ist."""
    seit = dt.datetime.combine(heute - dt.timedelta(days=VERLAUF_TAGE), dt.time(0, 0))
    offen = sorted((zeile_offen(r, heute) for r in fetch(store, [cal], exclude)), key=lambda t: t[0])
    erledigt = sorted((zeile_erledigt(r, heute) for r in fetch(store, [cal], exclude, erledigt_seit=seit)),
                      key=lambda t: t[0], reverse=True)
    print(f"{sauber(listenname(cal, doppelt))}, Verlauf: {len(offen)} offen, {len(erledigt)} erledigt seit "
          f"{tag_j(seit, heute)}")
    for _, zeile in offen + erledigt:
        print("  " + zeile)
    if not offen:
        print("  keine offenen Einträge")


def cmd_list(store, exclude, days, show_all: bool, verlauf=None):
    """Ohne verlauf wie bisher (days ohne Angabe 14). Mit verlauf erst diese Liste ganz, andere Listen nur, wenn days
    ausdrücklich dasteht (der Tagesstart nimmt 0 für heute und überfällig)."""
    alle = listen(store, exclude)
    heute = dt.date.today()
    if not alle:  # sonst hieße es keine offenen Erinnerungen, obwohl keine Liste gelesen wurde (Etappe 2 von v7.3.0)
        print("Keine Erinnerungsliste lesbar: Erinnerungen liefert keine oder nur ausgeschlossene Listen. Nichts "
              "durchsucht, Listen in Erinnerungen und excluded_lists in der config.json prüfen.")
        return
    if verlauf is None:
        horizon = heute + dt.timedelta(days=14 if days is None else days)
        groups = gruppen(store, exclude, alle, horizon, show_all, heute)
        if not groups:
            print(f"Keine offenen Erinnerungen mit Frist bis {tag(horizon)}"
                  + (" und keine ohne Frist" if show_all else ""))
            return
        print(HINWEIS)
        drucke(groups)
        return
    cals = verlauf_listen(alle, verlauf)
    print(HINWEIS)
    doppelt = doppelte_namen(alle)
    for cal in cals:
        drucke_verlauf(store, exclude, cal, doppelt, heute)
    if days is None:
        return
    horizon = heute + dt.timedelta(days=days)
    groups = gruppen(store, exclude, [c for c in alle if c not in cals], horizon, show_all, heute)
    if not groups:
        print(f"Andere Listen: nichts fällig bis {tag(horizon)}")
        return
    print(f"Andere Listen, fällig bis {tag(horizon)}:")
    drucke(groups)


def parse_faellig(date_s, time_s):
    """(Fälligkeit, mit Uhrzeit) oder (None, False). Klare Meldung statt Traceback, bevor etwas angelegt wird."""
    if not date_s:
        return None, False
    try:
        d = dt.datetime.strptime(date_s.strip(), "%Y-%m-%d")
    except ValueError:
        sys.exit(f"Datum '{date_s}' nicht lesbar: als JJJJ-MM-TT angeben, etwa 2026-09-30. Nichts angelegt.")
    if not time_s:
        return d, False
    try:
        t = dt.datetime.strptime(time_s.strip(), "%H:%M")
    except ValueError:
        sys.exit(f"Uhrzeit '{time_s}' nicht lesbar: als HH:MM angeben, etwa 18:00. Nichts angelegt.")
    d = d.replace(hour=t.hour, minute=t.minute)
    ortszeit_eindeutig(d, "Nichts angelegt.")  # wie im Kalender, sonst eine Stunde versetzt
    return d, True


def parse_fristen(worte) -> list:
    """[(Fälligkeit, mit Uhrzeit)] aus den Worten hinter dem Titel: je Frist ein Datum, dahinter wahlweise die Uhrzeit
    Ein Wort, das nicht wie ein Datum aussieht (DATUM_ARTIG), gilt hinter einem Datum als dessen
    Uhrzeit. Ohne Worte eine Erinnerung ohne Frist. Alles wird geprüft, bevor etwas angelegt wird, auch die
    Zeitumstellung je Frist (parse_faellig)."""
    fristen, i = [], 0
    while i < len(worte):
        zeit = worte[i + 1] if i + 1 < len(worte) and not DATUM_ARTIG.match(worte[i + 1]) else None
        fristen.append(parse_faellig(worte[i], zeit))
        i += 1 if zeit is None else 2
    if not fristen:
        return [(None, False)]
    if len(fristen) > 1 and any(f is None for f, _ in fristen):
        aufruf_falsch("Bei mehreren Fristen braucht jede ein Datum. Nichts angelegt.")
    for n, frist in enumerate(fristen):
        if frist in fristen[:n]:
            aufruf_falsch(f"Frist {frist_kurz(*frist)} steht zweimal im Aufruf. Nichts angelegt.")
    return fristen


def frist_kurz(faellig, mit_zeit: bool) -> str:
    """Mi 30.09., 18 Uhr oder Mi 30.09., ohne Datum ohne Frist."""
    if not faellig:
        return "ohne Frist"
    return tag(faellig) + (f", {uhr(faellig)} Uhr" if mit_zeit else "")


def faellig_text(faellig, mit_zeit: bool) -> str:
    return f", fällig {frist_kurz(faellig, mit_zeit)}" if faellig else ""


def fristen_satz(fristen) -> str:
    """Fristen für eine Meldung, mit und verbunden (in einer Frist steht schon ein Komma), mit genau einem Punkt am
    Ende, auch hinter einem Datum wie Mi 30.09."""
    text = " und ".join(frist_kurz(*f) for f in fristen)
    return text if text.endswith(".") else text + "."


def schon_offen(store, exclude, cal, title: str, fristen: list) -> list:
    """Fristen, zu denen in der Liste schon eine offene Erinnerung mit gleichem Titel (wie list ihn zeigt, name_norm)
    und gleicher Frist steht (wie die Dublettenprüfung im Kalender). Ohne Frist prüft es nicht,
    eine Einkaufsliste darf denselben Eintrag zweimal haben."""
    if not any(f[0] for f in fristen):
        return []
    gesucht = name_norm(title)
    vorhanden = [due_of(r) for r in fetch(store, [cal], exclude) if name_norm(r.title()) == gesucht]
    return [f for f in fristen if f[0] and f in vorhanden]


def cmd_add(store, exclude, list_name: str, title: str, fristen: list, notes: str):
    """Eine Erinnerung je Frist in derselben Liste. Ziel und Dublettenprüfung gelten für alle
    zusammen: Steht eine Frist schon offen in der Liste, legt add keine an. Bei einer Frist bleiben die Zeilen wie
    vorher. Geteilte Listen ohne Vorschau."""
    cal = ziel_liste(store, exclude, list_name)
    doppelt = schon_offen(store, exclude, cal, title, fristen)
    if doppelt:
        sys.exit(f"In {sauber(cal.title())} steht schon offen: {sauber(title)}, {fristen_satz(doppelt)} Ohne diese "
                 "Frist erneut aufrufen. Nichts angelegt.")
    mehrere = len(fristen) > 1
    kopf = f"{len(fristen)} Erinnerungen {sauber(title)}" if mehrere else sauber(title) + faellig_text(*fristen[0])
    for n, (faellig, mit_zeit) in enumerate(fristen):
        ok, err = speichere(store, cal, title, faellig, mit_zeit, notes)
        if not ok:  # EventKit speichert je Erinnerung: was schon steht, bleibt, und die Meldung nennt beides
            folge = (f"Schon angelegt: {fristen_satz(fristen[:n])} Nicht angelegt: {fristen_satz(fristen[n:])}"
                     if n else "Nichts angelegt.")
            sys.exit(f"Fehler beim Speichern: {err}. {folge}")
    print(f"Angelegt in {sauber(cal.title())}: {kopf}")
    drucke_fristen(fristen)


def drucke_fristen(fristen: list) -> None:
    """Bei mehreren Fristen je Frist eine Zeile unter der Kopfzeile, bei einer steht sie schon dort."""
    if len(fristen) > 1:
        for f in fristen:
            print(f"  - fällig {frist_kurz(*f)}")


def speichere(store, cal, title: str, faellig, mit_zeit: bool, notes: str) -> tuple:
    """Eine Erinnerung anlegen, mit Uhrzeit samt Wecker. (ok, Fehler) von EventKit."""
    import EventKit  # store_with_access hat es schon geladen oder mit Hinweis auf die .venv abgebrochen
    import Foundation
    r = EventKit.EKReminder.reminderWithEventStore_(store)
    r.setTitle_(title)
    r.setCalendar_(cal)
    if notes:
        r.setNotes_(notes)
    if faellig:
        comp = Foundation.NSDateComponents.alloc().init()
        comp.setYear_(faellig.year)
        comp.setMonth_(faellig.month)
        comp.setDay_(faellig.day)
        if mit_zeit:
            comp.setHour_(faellig.hour)
            comp.setMinute_(faellig.minute)
            r.addAlarm_(EventKit.EKAlarm.alarmWithAbsoluteDate_(nsdate(faellig)))
        r.setDueDateComponents_(comp)
    return store.saveReminder_commit_error_(r, True, None)


def cmd_done(store, exclude, title: str, liste=None):
    """Genau ein offener Eintrag mit dem Titel, verglichen wie list ihn zeigt (name_norm, Review 21.10.2026). Bei
    gleichem Titel in zwei Listen grenzt --liste ein, sonst nennt es die Kandidaten (Code 2)."""
    alle = listen(store, exclude)
    cals = alle if liste is None else [c for c in alle if name_norm(c.title()) == name_norm(liste)]
    if liste is not None and not cals:
        liste_fehlt(liste, alle)
    items = fetch(store, cals, exclude)
    gesucht = name_norm(title)
    exact = [r for r in items if name_norm(r.title()) == gesucht]
    if len(exact) == 1:
        r = exact[0]
        r.setCompleted_(True)
        ok, err = store.saveReminder_commit_error_(r, True, None)
        if not ok:
            sys.exit(f"Fehler beim Speichern: {err}. Nichts geändert.")
        print(f"Erledigt: {sauber(r.title())} ({sauber(r.calendar().title())})")
        return
    cand = [r for r in items if gesucht in name_norm(r.title())]
    if not cand:
        sys.exit(f"Nichts gefunden zu '{sauber(title)}'. Nichts geändert.")
    print(f"Nicht eindeutig, nichts geändert. Titel genau so nehmen, gleiche Titel in zwei Listen mit --liste "
          f"eingrenzen. Kandidaten {HINWEIS}:")
    for r in cand:
        print(f"  {sauber(r.calendar().title())}: {sauber(r.title())}")
    sys.exit(2)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] and argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    p = argparse.ArgumentParser(add_help=False, allow_abbrev=False)  # sonst gälte etwa --aus als --ausfuehren
    p.add_argument("cmd", nargs="?", default="list")
    p.add_argument("args", nargs="*")
    p.add_argument("--days", type=int, default=None)  # ohne Angabe 14, mit --verlauf dann keine anderen Listen
    p.add_argument("--all", action="store_true")
    p.add_argument("--verlauf", default=None)
    p.add_argument("--notes", default="")
    p.add_argument("--ausfuehren", action="store_true")
    p.add_argument("--liste", default=None)  # done: nur in dieser Liste, bei gleichem Titel in zwei Listen
    vorn, rest = kit_basis.schalter_vorn(argv, ("--ausfuehren",))  # nur direkt hinter dem Skript
    a = p.parse_intermixed_args(vorn + rest)  # andere Schalter an beliebiger Stelle, etwa done --liste X 'Titel'
    if a.cmd in ("list", "lists") and a.args:
        aufruf_falsch(f"{a.cmd} nimmt keine Liste als Wort, für eine Liste ganz: list --verlauf '<Liste>'. "
                      "Nichts gelesen.")
    if a.verlauf is not None and a.cmd != "list":
        aufruf_falsch("--verlauf gilt nur für list. Nichts geändert.")
    if a.verlauf is not None and not a.verlauf.strip():
        aufruf_falsch("--verlauf braucht einen Listennamen, etwa --verlauf 'Aufgaben'. Nichts gelesen.")
    if a.liste is not None and a.cmd != "done":
        aufruf_falsch("--liste gilt nur für done. Nichts geändert.")
    if a.liste is not None and not a.liste.strip():
        aufruf_falsch("--liste braucht einen Listennamen, etwa --liste 'Aufgaben'. Nichts geändert.")
    if a.days is not None and not 0 <= a.days <= DAYS_MAX:
        aufruf_falsch(f"--days braucht 0 bis {DAYS_MAX} Tage, etwa --days 7. Nichts gelesen.")
    cfg = load_config()
    block = cfg.get("reminders", {})
    if not isinstance(block, dict):
        sys.exit("config.json: reminders muss ein Objekt sein.")
    exclude = {name_norm(x) for x in namen(block, "excluded_lists")}
    geteilte = {name_norm(x) for x in namen(block, "geteilte_listen")}
    if a.cmd == "add":
        if len(a.args) < 2:
            aufruf_falsch('Aufruf: reminders.py add "<Liste>" "<Titel>" [JJJJ-MM-TT [HH:MM] ...], mehrere Fristen '
                          'hintereinander. Titel mit Leerzeichen in Anführungszeichen, ein Titel mit - vorn hinter --. '
                          'Nichts angelegt.')
        list_name, title = a.args[0], a.args[1]
        if not title.strip():
            aufruf_falsch("Titel fehlt. Nichts angelegt.")
        # eine gesperrte Liste meldet ziel_liste wie eine unbekannte, ohne den Ausschluss zu bestätigen (Review
        # 21.10.2026), listen() lässt sie nie durch
        fristen = parse_fristen(a.args[2:])  # alle Fristen geprüft, bevor der Store aufgeht
        cmd_add(store_with_access("reminders"), exclude, list_name, title, fristen, a.notes)
    elif a.cmd == "lists":
        cmd_lists(store_with_access("reminders"), exclude, geteilte)
    elif a.cmd == "list":
        cmd_list(store_with_access("reminders"), exclude, a.days, a.all, a.verlauf)
    elif a.cmd == "done":
        if not a.args:
            aufruf_falsch(__doc__)
        cmd_done(store_with_access("reminders"), exclude, " ".join(a.args), a.liste)
    else:
        aufruf_falsch(__doc__)


if __name__ == "__main__":
    venv_starten(__file__)
    kit_basis.starten(main, __file__)
