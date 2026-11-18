"""Kalender-Hilfen: erlaubte Kalender aus dem Abschnitt kalender der config.json, ein eindeutiges Schreibziel ohne
Exchange, mit --exchange genau der Arbeitskalender, und die Prüfung auf gleiche Termine.

Nur für add_event.py und move_event.py. Die gemeinsamen Apple-Hilfen (Konfiguration, Zugriff, Datum, Anzeige,
Uhrzeiten an der Zeitumstellung) stehen in eventkit_basis.py, das auch reminders.py nutzt.
"""
from __future__ import annotations

import datetime as dt
import sys

import kit_basis
from eventkit_basis import (EK_EVENT, ist_exchange, konto, load_config, namen, nsdate, ortszeit_eindeutig,  # noqa: F401
                            ts)

EINE_MINUTE = dt.timedelta(minutes=1)


def kalender_config() -> dict:
    """Abschnitt kalender der config.json im Datenordner."""
    return kit_basis.abschnitt(load_config(), "kalender", "Nichts geändert.")


def dubletten(store, cal, title: str, start: dt.datetime) -> list:
    """Termine im Kalender mit gleichem Titel (ohne Groß- und Kleinschreibung) und gleichem Start. Für add_event.py und
    für den Kalenderwechsel in move_event.py."""
    pred = store.predicateForEventsWithStartDate_endDate_calendars_(nsdate(start - EINE_MINUTE),
                                                                    nsdate(start + EINE_MINUTE), [cal])
    titel = title.strip().casefold()
    return [ev for ev in (store.eventsMatchingPredicate_(pred) or [])
            if (ev.title() or "").strip().casefold() == titel and abs(ts(ev.startDate()) - start.timestamp()) < 60]


def gewollt(ev, start: dt.datetime, ende: dt.datetime, ganz: bool, kalender: str) -> tuple:
    """Was nach dem Speichern im Termin stehen soll, für nachkontrolle. Direkt nach dem Speichern aufrufen, dann trägt
    der Termin seine ID."""
    return ev.eventIdentifier(), ev.title() or "", start, ende, ganz, kalender


def nachkontrolle(store, liste: list) -> list:
    """Termine nach dem Speichern frisch laden und mit dem Gewollten vergleichen (Etappe 4 von v7.3.0, wie bei Notizen
    und Erinnerungen): Start, Ende und Kalender. Ganztägig zählt nur der Tag, sonst eine Minute Spielraum. reset verwirft
    die Objekte im Speicher des Stores, gespeichert ist da schon alles. Eine Zeile je Abweichung."""
    if not liste:
        return []
    store.reset()
    zeilen = []
    for ident, titel, start, ende, ganz, kalender in liste:
        ev = store.eventWithIdentifier_(ident) if ident else None
        if ev is None:
            zeilen.append(f"Nachkontrolle: '{titel}' nach dem Speichern nicht wiedergefunden, bitte im Kalender prüfen.")
            continue
        ist_start, ist_ende = (dt.datetime.fromtimestamp(ts(ev.startDate())),
                               dt.datetime.fromtimestamp(ts(ev.endDate())))
        if ganz:  # das Ende eines ganztägigen Termins liefert EventKit je nach Konto auch als 0 Uhr des Folgetags
            folgetag = dt.datetime.combine(ende.date() + dt.timedelta(days=1), dt.time(0, 0))
            passt = ist_start.date() == start.date() and (ist_ende.date() == ende.date() or ist_ende == folgetag)
        else:
            passt = abs(ist_start - start) < EINE_MINUTE and abs(ist_ende - ende) < EINE_MINUTE
        ist_kal = ev.calendar().title() if ev.calendar() is not None else "?"
        if not passt:
            zeilen.append(f"Nachkontrolle: '{titel}' steht im Kalender von {ist_start:%d.%m. %H:%M} bis "
                          f"{ist_ende:%d.%m. %H:%M}, gewollt {start:%d.%m. %H:%M} bis {ende:%d.%m. %H:%M}.")
        if ist_kal != kalender:
            zeilen.append(f"Nachkontrolle: '{titel}' steht in {ist_kal}, gewollt {kalender}.")
    return zeilen


def allowed_calendars(cfg: dict) -> set:
    """Erlaubte Kalender sind allowed_calendars minus private_calendars. Private gewinnen immer."""
    return set(namen(cfg, "allowed_calendars")) - set(namen(cfg, "private_calendars"))


def kalender_name(cfg: dict, wunsch) -> str:
    """Name des Schreibziels: --calendar oder default_calendar, geprüft gegen allowed_calendars. Läuft vor dem
    Kalenderzugriff, damit ein falscher Name nie erst die Systemfreigabe braucht."""
    name = wunsch or cfg.get("default_calendar")
    if not name:
        sys.exit("Kein Kalender angegeben (--calendar) und kein default_calendar in config.json gesetzt.")
    if not isinstance(name, str):  # eine Liste endete sonst mit TypeError (Review 21.10.2026)
        sys.exit("config.json: default_calendar muss ein Kalendername als Text sein. Nichts geändert.")
    erlaubt = allowed_calendars(cfg)
    if name not in erlaubt:
        sys.exit(f"Kalender '{name}' nicht erlaubt. Erlaubt laut config.json: {', '.join(sorted(erlaubt))}")
    return name


def unique_calendar(store, cal_name: str, entity_type: int = EK_EVENT):
    """Genau ein Kalender mit diesem Titel. Fehler bei 0 oder bei Namensdubletten (mehrere Konten mit gleichem
    Kalendernamen): Bei Schreibzielen darf nichts zufällig das falsche Konto treffen."""
    matches = [c for c in store.calendarsForEntityType_(entity_type) if c.title() == cal_name]
    if not matches:
        sys.exit(f"Kalender '{cal_name}' nicht gefunden.")
    if len(matches) > 1:
        sys.exit(f"Kalender '{cal_name}' ist nicht eindeutig ({len(matches)} Treffer, Konten: "
                 f"{', '.join(konto(c) for c in matches)}). Einen davon in der Kalender-App umbenennen, sonst kann "
                 f"versehentlich der falsche beschrieben werden.")
    return matches[0]


EXCHANGE = "--exchange"


def exchange_vorn(vorn: list) -> bool:
    """--exchange: eigene Termine ohne Teilnehmer im Arbeitskalender (Exchange). Der Schalter steht
    als erstes Argument, so trifft eine Prüfung auf den Schalter jede Form, auch zusammen mit
    --ausfuehren. Der Server führt ihn nur mit dem Werkzeug termin_mit_nachfrage aus."""
    if EXCHANGE not in vorn:
        return False
    if vorn[0] != EXCHANGE:
        sys.exit(f"{EXCHANGE} steht als erstes Argument direkt hinter dem Skript, etwa <skript> {EXCHANGE} --ausfuehren "
                 f"-- <Titel> <Zeiten>. Nichts geändert.")
    return True


def exchange_name(cfg: dict, wunsch) -> str:
    """Schreibziel mit --exchange: nur arbeitskalender aus config.json (der Arbeitskalender in Apple Kalender), nie ein
    privater Kalender. Läuft vor dem Kalenderzugriff."""
    name = cfg.get("arbeitskalender")
    if not name or not isinstance(name, str):
        sys.exit(f"{EXCHANGE} braucht arbeitskalender in config.json (Name des Arbeitskalenders). Nichts geändert.")
    if wunsch and wunsch != name:
        sys.exit(f"Mit {EXCHANGE} gilt nur der Arbeitskalender aus config.json ({name}), nicht '{wunsch}'. Private Termine "
                 f"ohne {EXCHANGE}. Nichts geändert.")
    if name in namen(cfg, "private_calendars"):
        sys.exit(f"Kalender '{name}' steht unter private_calendars. Nichts geändert.")
    return name


def exchange_calendar(store, cal_name: str):
    """Genau ein Exchange-Kalender mit diesem Titel. Ein gleichnamiger Kalender in einem anderen Konto zählt nicht, er
    bleibt ohne den Schalter das Ziel nach target_calendar."""
    matches = [c for c in store.calendarsForEntityType_(EK_EVENT) if c.title() == cal_name and ist_exchange(c)]
    if not matches:
        sys.exit(f"Kein Exchange-Kalender '{cal_name}' gefunden. {EXCHANGE} gilt nur für den Arbeitskalender, private "
                 f"Termine ohne den Schalter. Nichts geändert.")
    if len(matches) > 1:
        sys.exit(f"Exchange-Kalender '{cal_name}' ist nicht eindeutig ({len(matches)} Treffer). Nichts geändert.")
    return matches[0]


def target_calendar(store, cal_name: str, cfg: dict):
    """Schreibziel für add_event.py und move_event.py: erlaubt laut config.json, genau ein Kalender mit dem Titel und
    nie ein Exchange-Kalender. Arbeitstermine laufen über den Microsoft-365-Connector (Skill /kalender), am 28.09.2026
    lagen Privat, T&L Kalender und Familie in CalDAV-Konten."""
    kalender_name(cfg, cal_name)
    cal = unique_calendar(store, cal_name)
    if ist_exchange(cal):
        sys.exit(f"Kalender '{cal_name}' liegt im Exchange-Konto {konto(cal)}. Die Skripte schreiben nur in private "
                 f"Kalender, Arbeitstermine laufen über den Microsoft-365-Connector. Nichts geändert.")
    return cal
