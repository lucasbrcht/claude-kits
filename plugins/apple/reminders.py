#!/usr/bin/env python3
"""Apple-Erinnerungen lesen und schreiben (EventKit).

Aufruf (startet als python3 und wechselt selbst in die .venv des Kits, dort liegt EventKit):
  reminders.py list [--days N] [--all]     offene, überfällige und in N Tagen fällige (Standard 14, 0 bis 3650), --all
                                           auch ohne Frist
  reminders.py list --verlauf "<Liste>" [--days N]   die Liste ganz (auch ohne Frist) mit Anlagedatum, Notiz und
                                           Liegezeit, dazu die erledigten seit 0 Uhr vor 14 Tagen (15 Kalendertage mit
                                           heute). Andere Listen nur mit --days
  reminders.py list --text "<Suche>" [--days N]   Titel und Notiz in allen Listen, offene und die seit 0 Uhr vor N
                                           Tagen erledigten (Standard 30)
  reminders.py list --erledigt [--text "<Suche>"] [--days N]   nur Erledigtes seit 0 Uhr vor N Tagen (Standard 7, 0
                                           heute), alle Listen
  reminders.py lists                       alle Listen mit Konto
  reminders.py add "<Liste>" "<Titel>" [JJJJ-MM-TT [HH:MM] ...] [--notes "Text"] [--prioritaet hoch]   mehrere
                                           Fristen zum selben Titel in einem Aufruf: je Frist eine Erinnerung, ein
                                           Speichern für alle
  reminders.py done "<Titel>" [--liste "<Liste>"]   Titel, wie list ihn zeigt, sonst Kandidaten zeigen und nichts
                                           ändern, --liste bei gleichem Titel in zwei Listen
  reminders.py aendern "<Titel>" [--liste "<Liste>"] [--frist "JJJJ-MM-TT [HH:MM]" | --ohne-frist]
      [--neuer-titel "Text"] [--notes "Text"] [--nach-liste "<Liste>"] [--wieder-offen] [--prioritaet P]
                                           eine Erinnerung ändern, gefunden wie bei done. Mit --wieder-offen unter den
                                           in 365 Tagen erledigten, bei gleichem Titel in einer Liste die zuletzt
                                           erledigte. Danach neu laden und vergleichen (Zeile Nachkontrolle)
  Priorität: hoch, mittel, niedrig oder keine, list zeigt sie wie die App als !!!, !! und ! vor dem Titel.
  --ausfuehren wirkt nicht und steht, wenn überhaupt, direkt hinter dem Skript, an anderer Stelle bricht das
  Skript ab

Listen aus reminders.excluded_lists in config.json werden nie gelesen oder beschrieben.
add, done und aendern schreiben in alle Listen direkt, auch in geteilte aus reminders.geteilte_listen (die
Erinnerungen sind die eigene App des Nutzers, der Auftrag ist die Freigabe). lists markiert geteilte Listen weiter mit (geteilt).
Abkürzungen der Optionen gelten nicht. Gibt es eine Liste in zwei Konten mit gleichem Namen, liest das Skript beide
und schreibt in keine. Steht in der Liste schon eine offene Erinnerung mit gleichem Titel und gleicher Frist, legt add
nichts an, auch keine der anderen Fristen, und aendern ändert nichts. Löschen kann das Skript nicht, aendern entfernt
höchstens die Frist samt dem Wecker zu ihrer Uhrzeit.
"""
import argparse
import datetime as dt
import re
import sys
import time
import unicodedata

import kit_basis  # Nummern, Steuerzeichen, Datenhinweis, gleich in apple und chat
from eventkit_basis import (EK_REMINDER, konto, load_config, namen, nsdate, ortszeit_eindeutig, pydt, store_with_access,
                            tag, ts, uhr, venv_starten)

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
# Priorität wie EventKit (EKReminderPriority): 1 hoch, 5 mittel, 9 niedrig, 0 keine. Andere Apps setzen über CalDAV
# auch 2 bis 4 und 6 bis 8, die gelten als hoch und niedrig. Anzeige wie in der App (Etappe 4 von v7.3.0)
PRIORITAETEN = {"hoch": 1, "mittel": 5, "niedrig": 9, "keine": 0}
STUFEN = {3: "hoch", 2: "mittel", 1: "niedrig", 0: "keine"}
ZEICHEN = {3: "!!! ", 2: "!! ", 1: "! ", 0: ""}
VOR_ZEICHEN = re.compile(r"^!{1,3}\s+")  # !!! vor einem Titel aus der Ausgabe gehört nicht zum Titel
# Suche (list --text, --erledigt): Erledigtes ab 0 Uhr vor so vielen Tagen, wenn --days fehlt, höchstens so viele Zeilen
SUCHE_TAGE = 30
ERLEDIGT_TAGE = 7
SUCHE_MAX = 50
WIEDER_TAGE = 365  # aendern --wieder-offen sucht unter den in so vielen Tagen erledigten
KEINE_LISTE = ("Keine Erinnerungsliste lesbar: Erinnerungen liefert keine oder nur ausgeschlossene Listen. Nichts "
               "durchsucht, Listen in Erinnerungen und excluded_lists in der config.json prüfen.")


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


def ziel_liste(store, exclude, name: str, folge: str = "Nichts angelegt."):
    """Genau eine Liste mit dem Namen, sonst Abbruch: Bei Dubletten landet nichts zufällig im falschen Konto. Dubletten
    sind mehrdeutig und enden mit Code 2 (Prüfung 20.10.2026)."""
    alle = listen(store, exclude)
    treffer = [c for c in alle if name_norm(c.title()) == name_norm(name)]
    if not treffer:
        liste_fehlt(name, alle)
    if len(treffer) > 1:
        aufruf_falsch(f"Liste '{sauber(name)}' gibt es {len(treffer)} Mal (Konten: "
                      f"{', '.join(sauber(konto(c)) for c in treffer)}). Eine davon in Erinnerungen umbenennen, sonst "
                      f"landet der Eintrag womöglich in der falschen. {folge}")
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


def stufe_von(wert) -> int:
    """3 hoch, 2 mittel, 1 niedrig, 0 keine aus dem Wert von EventKit (1 bis 4 hoch, 5 mittel, 6 bis 9 niedrig)."""
    try:
        p = int(wert or 0)
    except (TypeError, ValueError):
        return 0
    return 3 if 1 <= p <= 4 else 2 if p == 5 else 1 if 6 <= p <= 9 else 0


def stufe(r) -> int:
    return stufe_von(r.priority())


def titel_zeile(r) -> str:
    """Titel für die Ausgabe, mit !!!, !! oder ! davor wie in der App."""
    return ZEICHEN[stufe(r)] + sauber(r.title())


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
        if due is None and not show_all:
            continue
        if due is None:
            line = f"- {titel_zeile(r)}"
        else:
            d, has_time = due
            if d.date() > horizon:
                continue
            when = tag_j(d, heute) + (f", {uhr(d)} Uhr" if has_time else "")
            line = f"- {faellig_flag(d, heute)}{when}  {titel_zeile(r)}"
        groups.setdefault(listenname(r.calendar(), doppelt), []).append((reihe(r, heute), line))
    return groups


def reihe(r, heute: dt.date, angelegt=None) -> tuple:
    """Sortierschlüssel je Liste: erst heute Fälliges und Überfälliges, Wichtiges vorn, dann später Fälliges nach Frist
    (bei gleicher Frist Wichtiges vorn), zuletzt ohne Frist, Wichtiges vorn, dann nach angelegt (Etappe 4 von
    v7.3.0)."""
    due, wichtig, titel = due_of(r), -stufe(r), sauber(r.title())
    if due is None:
        return 2, wichtig, angelegt or dt.date.max, titel
    if due[0].date() <= heute:
        return 0, wichtig, due[0], titel
    return 1, due[0], wichtig, titel


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
    """(Schlüssel, Zeile) im Verlauf: wie reihe, ohne Frist die ältesten zuerst, ohne Anlagedatum zuletzt."""
    angelegt = datum_von(r.creationDate())
    zusatz = [f"angelegt {tag_j(angelegt, heute)}"] if angelegt else []
    due = due_of(r)
    if due is None:
        when = "ohne Frist"
        liegt = werktage(angelegt, heute) if angelegt else 0
        if liegt >= LIEGT_AB:
            zusatz.append(f"liegt seit {liegt} Werktagen")
    else:
        d, has_time = due
        when = faellig_flag(d, heute) + tag_j(d, heute) + (f", {uhr(d)} Uhr" if has_time else "")
    notiz = notiz_kurz(r)
    if notiz:
        zusatz.append(f"Notiz: {notiz}")
    return reihe(r, heute, angelegt), f"- {when}  {titel_zeile(r)}" + (f"  ({', '.join(zusatz)})" if zusatz else "")


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
        print(KEINE_LISTE)
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


def wann_text(due, heute: dt.date) -> str:
    """ÜBERFÄLLIG Mo 16.11., 18 Uhr aus (Fälligkeit, mit Uhrzeit)."""
    d, has_time = due
    return faellig_flag(d, heute) + tag_j(d, heute) + (f", {uhr(d)} Uhr" if has_time else "")


def treffer_in(r, gesucht: str) -> str:
    """Wo der Suchtext steht: titel, notiz oder leer. Verglichen wie name_norm, ohne Suchtext passt jeder Eintrag."""
    if gesucht in name_norm(r.title()):
        return "titel"
    return "notiz" if gesucht in name_norm(r.notes() or "") else ""


def zeile_treffer(r, wo: str, heute: dt.date) -> str:
    """Eine Zeile der Suche: offen mit Frist oder erledigt mit Datum, Treffer nur in der Notiz steht dabei. Die Notiz
    selbst nur mit Vorsatz und ohne Nummern (notiz_kurz), auch wenn der Treffer dort liegt."""
    if r.isCompleted():
        am = datum_von(r.completionDate())
        wann = f"erledigt {tag_j(am, heute) if am else 'ohne Datum'}"
    else:
        due = due_of(r)
        wann = "offen, " + (wann_text(due, heute) if due else "ohne Frist")
    zusatz = ["Treffer in der Notiz"] if wo == "notiz" else []
    notiz = notiz_kurz(r)
    if notiz:
        zusatz.append(f"Notiz: {notiz}")
    return f"- {wann}  {titel_zeile(r)}" + (f"  ({', '.join(zusatz)})" if zusatz else "")


def cmd_suche(store, exclude, text, days, nur_erledigt: bool):
    """Suche über alle Listen: mit text in Titel und Notiz, offene (ohne Grenze der Frist) und die seit 0 Uhr vor days
    Tagen erledigten. nur_erledigt lässt die offenen weg und geht ohne text (Was habe ich geschafft?). Höchstens
    SUCHE_MAX Zeilen, offene vor erledigten, die Zahlen im Kopf zählen alle."""
    alle = listen(store, exclude)
    heute = dt.date.today()
    if not alle:
        print(KEINE_LISTE)
        return
    tage = days if days is not None else (ERLEDIGT_TAGE if nur_erledigt else SUCHE_TAGE)
    seit = dt.datetime.combine(heute - dt.timedelta(days=tage), dt.time(0, 0))
    gesucht = name_norm(text or "")
    offen = [] if nur_erledigt else [(r, wo) for r in fetch(store, alle, exclude) for wo in [treffer_in(r, gesucht)]
                                     if wo]
    erledigt = [(r, wo) for r in fetch(store, alle, exclude, erledigt_seit=seit) for wo in [treffer_in(r, gesucht)]
                if wo]
    wo_text = f"zu '{sauber(text)}' " if text else ""
    zeitraum_text = f"erledigt seit {tag_j(seit, heute)}"
    if not offen and not erledigt:
        print(f"Nichts gefunden {wo_text}in allen Listen, " + ("" if nur_erledigt else "offen und ") + zeitraum_text
              + ".")
        return
    print(HINWEIS)
    kopf = f"{len(erledigt)} {zeitraum_text}" if nur_erledigt else f"{len(offen)} offen, {len(erledigt)} {zeitraum_text}"
    print(f"Suche {wo_text}in allen Listen: {kopf}" if text else f"Alle Listen: {kopf}")
    sortiert = (sorted(offen, key=lambda t: reihe(t[0], heute))
                + sorted(erledigt, key=lambda t: -(ts(t[0].completionDate()) if t[0].completionDate() else 0)))
    doppelt = doppelte_namen(alle)
    groups = {}
    for n, (r, wo) in enumerate(sortiert[:SUCHE_MAX]):
        groups.setdefault(listenname(r.calendar(), doppelt), []).append((n, zeile_treffer(r, wo, heute)))
    drucke(groups)
    if len(sortiert) > SUCHE_MAX:
        print(f"Dazu {len(sortiert) - SUCHE_MAX} weitere Treffer, Suche oder Zeitraum eingrenzen.")


def parse_faellig(date_s, time_s, folge: str = "Nichts angelegt."):
    """(Fälligkeit, mit Uhrzeit) oder (None, False). Klare Meldung statt Traceback, bevor etwas angelegt wird."""
    if not date_s:
        return None, False
    try:
        d = dt.datetime.strptime(date_s.strip(), "%Y-%m-%d")
    except ValueError:
        sys.exit(f"Datum '{date_s}' nicht lesbar: als JJJJ-MM-TT angeben, etwa 2026-09-30. {folge}")
    if not time_s:
        return d, False
    try:
        t = dt.datetime.strptime(time_s.strip(), "%H:%M")
    except ValueError:
        sys.exit(f"Uhrzeit '{time_s}' nicht lesbar: als HH:MM angeben, etwa 18:00. {folge}")
    d = d.replace(hour=t.hour, minute=t.minute)
    ortszeit_eindeutig(d, folge)  # wie im Kalender, sonst eine Stunde versetzt
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


def cmd_add(store, exclude, list_name: str, title: str, fristen: list, notes: str, prioritaet=None):
    """Eine Erinnerung je Frist in derselben Liste. Ziel und Dublettenprüfung gelten für alle
    zusammen: Steht eine Frist schon offen in der Liste, legt add keine an. Bei einer Frist bleiben die Zeilen wie
    vorher. Geteilte Listen ohne Vorschau."""
    cal = ziel_liste(store, exclude, list_name)
    doppelt = schon_offen(store, exclude, cal, title, fristen)
    if doppelt:
        sys.exit(f"In {sauber(cal.title())} steht schon offen: {sauber(title)}, {fristen_satz(doppelt)} Ohne diese "
                 "Frist erneut aufrufen. Nichts angelegt.")
    mehrere = len(fristen) > 1
    zeichen = ZEICHEN[stufe_von(prioritaet)]
    kopf = (f"{len(fristen)} Erinnerungen {zeichen}{sauber(title)}" if mehrere
            else zeichen + sauber(title) + faellig_text(*fristen[0]))
    for n, (faellig, mit_zeit) in enumerate(fristen):
        ok, err = speichere(store, cal, title, faellig, mit_zeit, notes, prioritaet)
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


def frist_setzen(r, faellig, mit_zeit: bool) -> None:
    """Frist als Datumsteile, mit Uhrzeit samt Wecker zu genau dieser Zeit (wie die App), ohne faellig keine Frist."""
    import EventKit  # store_with_access hat es schon geladen oder mit Hinweis auf die .venv abgebrochen
    import Foundation
    if not faellig:
        r.setDueDateComponents_(None)
        return
    comp = Foundation.NSDateComponents.alloc().init()
    comp.setYear_(faellig.year)
    comp.setMonth_(faellig.month)
    comp.setDay_(faellig.day)
    if mit_zeit:
        comp.setHour_(faellig.hour)
        comp.setMinute_(faellig.minute)
        r.addAlarm_(EventKit.EKAlarm.alarmWithAbsoluteDate_(nsdate(faellig)))
    r.setDueDateComponents_(comp)


def speichere(store, cal, title: str, faellig, mit_zeit: bool, notes: str, prioritaet=None) -> tuple:
    """Eine Erinnerung anlegen, mit Uhrzeit samt Wecker. (ok, Fehler) von EventKit."""
    import EventKit
    r = EventKit.EKReminder.reminderWithEventStore_(store)
    r.setTitle_(title)
    r.setCalendar_(cal)
    if notes:
        r.setNotes_(notes)
    if prioritaet:
        r.setPriority_(prioritaet)
    if faellig:
        frist_setzen(r, faellig, mit_zeit)
    return store.saveReminder_commit_error_(r, True, None)


def suchtitel(title: str) -> set:
    """Gesuchte Titel normiert: wie übergeben und ohne !!!, !! oder ! davor, falls der Titel aus der Ausgabe stammt."""
    return {name_norm(title), name_norm(VOR_ZEICHEN.sub("", sauber(title)))} - {""}


def erledigt_am(r) -> float:
    return ts(r.completionDate()) if r.completionDate() is not None else 0.0


def waehle(store, exclude, title: str, liste=None, erledigt: bool = False):
    """Genau ein Eintrag mit dem Titel, verglichen wie list ihn zeigt (name_norm, Review 21.10.2026). Offene, mit
    erledigt die in WIEDER_TAGE Tagen erledigten: gibt es dort den Titel in einer Liste mehrmals, gilt der zuletzt
    erledigte. Bei gleichem Titel in zwei Listen grenzt liste ein, sonst nennt es die Kandidaten (Code 2)."""
    alle = listen(store, exclude)
    cals = alle if liste is None else [c for c in alle if name_norm(c.title()) == name_norm(liste)]
    if liste is not None and not cals:
        liste_fehlt(liste, alle)
    seit = dt.datetime.combine(dt.date.today() - dt.timedelta(days=WIEDER_TAGE), dt.time(0, 0))
    items = fetch(store, cals, exclude, erledigt_seit=seit) if erledigt else fetch(store, cals, exclude)
    gesucht = suchtitel(title)
    exact = [r for r in items if name_norm(r.title()) in gesucht]
    if erledigt and exact and len({(sauber(r.calendar().title()), konto(r.calendar())) for r in exact}) == 1:
        exact = [max(exact, key=erledigt_am)]
    if len(exact) == 1:
        return exact[0]
    cand = [r for r in items if any(g in name_norm(r.title()) for g in gesucht)]
    if not cand:
        if erledigt:
            sys.exit(f"Nichts Erledigtes zu '{sauber(title)}' in den letzten {WIEDER_TAGE} Tagen. Nichts geändert.")
        sys.exit(f"Nichts gefunden zu '{sauber(title)}'. Nichts geändert.")
    print(f"Nicht eindeutig, nichts geändert. Titel genau so nehmen, gleiche Titel in zwei Listen mit --liste "
          f"eingrenzen. Kandidaten {HINWEIS}:")
    for r in sorted(cand, key=erledigt_am, reverse=True) if erledigt else cand:
        am = datum_von(r.completionDate()) if erledigt else None
        zusatz = f" (erledigt {tag_j(am, dt.date.today())})" if am else ""
        print(f"  {sauber(r.calendar().title())}: {sauber(r.title())}{zusatz}")
    sys.exit(2)


def cmd_done(store, exclude, title: str, liste=None):
    """Genau ein offener Eintrag mit dem Titel (waehle) wird erledigt."""
    r = waehle(store, exclude, title, liste)
    r.setCompleted_(True)
    ok, err = store.saveReminder_commit_error_(r, True, None)
    if not ok:
        sys.exit(f"Fehler beim Speichern: {err}. Nichts geändert.")
    print(f"Erledigt: {sauber(r.title())} ({sauber(r.calendar().title())})")


def werte(r) -> dict:
    """Was aendern setzt und die Nachkontrolle vergleicht: Titel, Frist, Liste, erledigt, Priorität, Notiz. Titel und
    Notiz normiert (name_norm), die Liste als Name mit Konto."""
    cal = r.calendar()
    return {"titel": name_norm(r.title()), "frist": due_of(r), "liste": (sauber(cal.title()), sauber(konto(cal))),
            "erledigt": bool(r.isCompleted()), "prioritaet": stufe(r), "notiz": name_norm(r.notes() or "")}


def wert_text(schluessel: str, wert, titel: str = "") -> str:
    """Ein Wert aus werte für eine Meldung. Den Titel nimmt sie bereinigt, eine Notiz nie (ohne Vorsatz bleibt sie
    draußen)."""
    if schluessel == "frist":
        return frist_kurz(*wert) if wert else "ohne Frist"
    if schluessel == "liste":
        return wert[0]
    if schluessel == "erledigt":
        return "erledigt" if wert else "offen"
    if schluessel == "prioritaet":
        return STUFEN[wert]
    return titel


NAMEN = {"titel": "Titel", "frist": "Frist", "liste": "Liste", "erledigt": "Status", "prioritaet": "Priorität",
         "notiz": "Notiz"}


def frist_wecker_weg(r, alte) -> None:
    """Wecker zur alten Frist mit Uhrzeit entfernen (den legen add und die App mit an), sonst klingelte er zur alten
    Zeit. Andere Wecker bleiben."""
    if not alte or not alte[1]:
        return
    for a in list(r.alarms() or []):
        datum = a.absoluteDate()
        if datum is not None and abs(ts(datum) - alte[0].timestamp()) < 60:
            r.removeAlarm_(a)


def cmd_aendern(store, exclude, title: str, liste, neu: dict):
    """Eine Erinnerung ändern: Frist (oder keine), Titel, Notiz, Liste, wieder offen, Priorität. Findet sie wie done,
    mit wieder_offen unter den erledigten. Steht in der Zielliste schon eine offene mit gleichem Titel und gleicher
    Frist, ändert es nichts. Nach dem Speichern lädt es die Erinnerung neu und nennt jede Abweichung in einer Zeile
    Nachkontrolle."""
    r = waehle(store, exclude, title, liste, erledigt=neu["wieder_offen"])
    alt = werte(r)
    alt_titel, alt_frist = sauber(r.title()), due_of(r)
    ziel = r.calendar()
    if neu["nach_liste"] is not None:
        ziel = ziel_liste(store, exclude, neu["nach_liste"], "Nichts geändert.")
    soll = dict(alt)
    soll_titel = sauber(neu["neuer_titel"]) if neu["neuer_titel"] is not None else alt_titel
    if neu["neuer_titel"] is not None:
        soll["titel"] = name_norm(neu["neuer_titel"])
    if neu["ohne_frist"]:
        soll["frist"] = None
    elif neu["frist"] is not None:
        soll["frist"] = neu["frist"]
    soll["liste"] = (sauber(ziel.title()), sauber(konto(ziel)))
    if neu["wieder_offen"]:
        soll["erledigt"] = False
    if neu["prioritaet"] is not None:
        soll["prioritaet"] = stufe_von(neu["prioritaet"])
    if neu["notes"] is not None:
        soll["notiz"] = name_norm(neu["notes"])
    anders = [k for k in NAMEN if soll[k] != alt[k]]
    wo = f"{alt_titel} ({sauber(r.calendar().title())})"
    if not anders:
        print(f"Nichts geändert: {wo} hat diese Werte schon.")
        return
    if soll["frist"] and not soll["erledigt"] and {"titel", "frist", "liste", "erledigt"} & set(anders):
        ident = r.calendarItemIdentifier()
        doppelt = [x for x in fetch(store, [ziel], exclude) if x.calendarItemIdentifier() != ident
                   and name_norm(x.title()) == soll["titel"] and due_of(x) == soll["frist"]]
        if doppelt:
            sys.exit(f"In {sauber(ziel.title())} steht schon offen: {soll_titel}, {fristen_satz([soll['frist']])} "
                     f"Nichts geändert.")
    if "titel" in anders:
        r.setTitle_(neu["neuer_titel"])
    if "notiz" in anders:
        r.setNotes_(neu["notes"])
    if "prioritaet" in anders:
        r.setPriority_(neu["prioritaet"])
    if "liste" in anders:
        r.setCalendar_(ziel)
    if "frist" in anders:
        frist_wecker_weg(r, alt_frist)
        frist_setzen(r, *(soll["frist"] or (None, False)))
    if "erledigt" in anders:
        r.setCompleted_(False)
    ident = r.calendarItemIdentifier()
    ok, err = store.saveReminder_commit_error_(r, True, None)
    if not ok:
        sys.exit(f"Fehler beim Speichern: {err}. Nichts geändert.")
    print(f"Geändert: {wo}")
    for k in anders:
        if k == "notiz":
            print("  - Notiz ersetzt")
        elif k == "erledigt":
            print("  - wieder offen")
        else:
            print(f"  - {NAMEN[k]} {wert_text(k, soll[k], soll_titel)} statt {wert_text(k, alt[k], alt_titel)}")
    nachkontrolle(store, ident, soll, soll_titel)


def nachkontrolle(store, ident, soll: dict, soll_titel: str) -> None:
    """Erinnerung neu laden und mit dem Gewollten vergleichen (wie notiz.nachkontrolle in Etappe 3 von v7.3.0). Eine
    Zeile je Abweichung, ohne Abweichung keine. reset verwirft die Objekte im Speicher des Stores (gespeichert ist
    schon alles), so kommt die Erinnerung frisch aus der Datenbank von Erinnerungen."""
    store.reset()
    neu = store.calendarItemWithIdentifier_(ident)
    if neu is None:
        print("Nachkontrolle: Erinnerung nach dem Speichern nicht wiedergefunden, bitte in Erinnerungen prüfen.")
        return
    ist = werte(neu)
    for k in NAMEN:
        if ist[k] == soll[k]:
            continue
        if k == "notiz":
            print("Nachkontrolle: Notiz weicht ab, bitte in Erinnerungen prüfen.")
        else:
            print(f"Nachkontrolle: {NAMEN[k]} ist {wert_text(k, ist[k], sauber(neu.title()))}, gewollt "
                  f"{wert_text(k, soll[k], soll_titel)}.")


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
    p.add_argument("--notes", default=None)
    p.add_argument("--ausfuehren", action="store_true")
    p.add_argument("--liste", default=None)  # done, aendern: nur in dieser Liste, bei gleichem Titel in zwei Listen
    p.add_argument("--text", default=None)  # list: Suche in Titel und Notiz
    p.add_argument("--erledigt", action="store_true")  # list: nur Erledigtes
    p.add_argument("--prioritaet", default=None)  # add, aendern
    for name in ("--frist", "--neuer-titel", "--nach-liste"):  # aendern
        p.add_argument(name, default=None)
    p.add_argument("--ohne-frist", action="store_true")
    p.add_argument("--wieder-offen", action="store_true")
    vorn, rest = kit_basis.schalter_vorn(argv, ("--ausfuehren",))  # nur direkt hinter dem Skript
    a = p.parse_intermixed_args(vorn + rest)  # andere Schalter an beliebiger Stelle, etwa done --liste X 'Titel'
    if a.cmd in ("list", "lists") and a.args:
        aufruf_falsch(f"{a.cmd} nimmt keine Liste als Wort, für eine Liste ganz: list --verlauf '<Liste>'. "
                      "Nichts gelesen.")
    gilt = {"--verlauf": (a.verlauf is not None, ("list",)), "--text": (a.text is not None, ("list",)),
            "--erledigt": (a.erledigt, ("list",)), "--liste": (a.liste is not None, ("done", "aendern")),
            "--notes": (a.notes is not None, ("add", "aendern")),
            "--prioritaet": (a.prioritaet is not None, ("add", "aendern")),
            "--frist": (a.frist is not None, ("aendern",)), "--ohne-frist": (a.ohne_frist, ("aendern",)),
            "--neuer-titel": (a.neuer_titel is not None, ("aendern",)),
            "--nach-liste": (a.nach_liste is not None, ("aendern",)),
            "--wieder-offen": (a.wieder_offen, ("aendern",))}
    for name, (da, befehle) in gilt.items():
        if da and a.cmd not in befehle:
            aufruf_falsch(f"{name} gilt nur für {' und '.join(befehle)}. Nichts geändert.")
    if a.verlauf is not None and not a.verlauf.strip():
        aufruf_falsch("--verlauf braucht einen Listennamen, etwa --verlauf 'Aufgaben'. Nichts gelesen.")
    if a.verlauf is not None and (a.text is not None or a.erledigt):
        aufruf_falsch("--verlauf zeigt eine Liste, --text und --erledigt suchen in allen. Nur eins davon. Nichts "
                      "gelesen.")
    if a.text is not None and not a.text.strip():
        aufruf_falsch("--text braucht einen Suchtext, etwa --text 'Reifen'. Nichts gelesen.")
    if a.all and (a.text is not None or a.erledigt):
        aufruf_falsch("--text und --erledigt zeigen auch Einträge ohne Frist, --all braucht es dort nicht. Nichts "
                      "gelesen.")
    for name, wert in (("--liste", a.liste), ("--nach-liste", a.nach_liste)):
        if wert is not None and not wert.strip():
            aufruf_falsch(f"{name} braucht einen Listennamen, etwa {name} 'Aufgaben'. Nichts geändert.")
    if a.prioritaet is not None and a.prioritaet not in PRIORITAETEN:
        aufruf_falsch(f"--prioritaet ist {', '.join(PRIORITAETEN)}. Nichts geändert.")
    if a.days is not None and not 0 <= a.days <= DAYS_MAX:
        aufruf_falsch(f"--days braucht 0 bis {DAYS_MAX} Tage, etwa --days 7. Nichts gelesen.")
    prioritaet = PRIORITAETEN.get(a.prioritaet)
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
        cmd_add(store_with_access("reminders"), exclude, list_name, title, fristen, a.notes, prioritaet)
    elif a.cmd == "lists":
        cmd_lists(store_with_access("reminders"), exclude, geteilte)
    elif a.cmd == "list" and (a.text is not None or a.erledigt):
        cmd_suche(store_with_access("reminders"), exclude, a.text, a.days, a.erledigt)
    elif a.cmd == "list":
        cmd_list(store_with_access("reminders"), exclude, a.days, a.all, a.verlauf)
    elif a.cmd == "done":
        if not a.args:
            aufruf_falsch(__doc__)
        cmd_done(store_with_access("reminders"), exclude, " ".join(a.args), a.liste)
    elif a.cmd == "aendern":
        neu = aenderung(a, prioritaet)  # alles geprüft, bevor der Store aufgeht
        cmd_aendern(store_with_access("reminders"), exclude, " ".join(a.args), a.liste, neu)
    else:
        aufruf_falsch(__doc__)


def aenderung(a, prioritaet) -> dict:
    """Was aendern setzen soll, geprüft: ein Titel zum Finden, mindestens eine Änderung, Frist oder ohne Frist, kein
    leerer neuer Titel und keine leere Notiz (leeren geht nur in der App)."""
    if not a.args or not " ".join(a.args).strip():
        aufruf_falsch('Aufruf: reminders.py aendern "<Titel>" mit mindestens einer Änderung (--frist, --ohne-frist, '
                      '--neuer-titel, --notes, --nach-liste, --wieder-offen, --prioritaet). Nichts geändert.')
    if a.frist is not None and a.ohne_frist:
        aufruf_falsch("--frist und --ohne-frist schließen sich aus. Nichts geändert.")
    if a.neuer_titel is not None and not a.neuer_titel.strip():
        aufruf_falsch("--neuer-titel ist leer. Nichts geändert.")
    if a.notes is not None and not a.notes.strip():
        aufruf_falsch("--notes ist leer. Eine Notiz leert der Nutzer in Erinnerungen selbst. Nichts geändert.")
    frist = None
    if a.frist is not None:
        worte = a.frist.split()
        if not 1 <= len(worte) <= 2:
            aufruf_falsch("--frist als 'JJJJ-MM-TT' oder 'JJJJ-MM-TT HH:MM'. Nichts geändert.")
        frist = parse_faellig(worte[0], worte[1] if len(worte) == 2 else None, "Nichts geändert.")
    neu = {"frist": frist, "ohne_frist": a.ohne_frist, "neuer_titel": a.neuer_titel, "notes": a.notes,
           "nach_liste": a.nach_liste, "wieder_offen": a.wieder_offen, "prioritaet": prioritaet}
    if prioritaet is None and not any(v is not None and v is not False for v in neu.values()):
        aufruf_falsch("aendern braucht mindestens eine Änderung: --frist, --ohne-frist, --neuer-titel, --notes, "
                      "--nach-liste, --wieder-offen oder --prioritaet. Nichts geändert.")
    return neu


if __name__ == "__main__":
    venv_starten(__file__)
    kit_basis.starten(main, __file__)
