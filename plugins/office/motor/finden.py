"""Deck finden: nach Name, SharePoint-Link oder Inhalt in einem Ordner. Den Ordner wählt der Server (ordner des
Werkzeugs oder suche.ordner der config.json von office).

Aufruf: python3 -I finden.py <Begriff oder Link> [weitere Begriffe] [--inhalt] --ordner <Ordner>

Name: alle Begriffe im Dateinamen, Groß- und Kleinschreibung egal, neueste zuerst, höchstens 15 Treffer.
Link: Dateiname aus dem SharePoint-Link (file= oder letzter Pfadteil), dann genau dieser Name.
--inhalt: alle Begriffe im Text einer Folie, Treffer je Folie. Dateien, die OneDrive nur online hält, lädt die
Suche nicht, sie zählt sie nur. Liest nur, legt nichts an. Rückgabewert 0 mit Treffer, 1 ohne, 2 bei falschem Aufruf.
"""
import html
import os
import posixpath
import re
import sys
import time
import zipfile
from datetime import datetime
from urllib.parse import parse_qs, unquote, urlparse
from xml.etree.ElementTree import fromstring

sys.dont_write_bytecode = True

NUR_ONLINE = 0x40000000  # SF_DATALESS: OneDrive hält die Datei nur online
ZEITLIMIT = 90  # Sekunden für die Inhaltssuche
TEXT_RE = re.compile(r"<a:t(?:\s[^>]*)?>([^<]*)</a:t>")


def name_aus_link(link: str) -> str:
    teile = urlparse(link)
    datei = parse_qs(teile.query).get("file", [""])[0] or posixpath.basename(unquote(teile.path))
    return datei if datei.lower().endswith((".pptx", ".potx")) else ""


def decks(ordner: list):
    for wurzel in ordner:
        for pfad, unter, dateien in os.walk(wurzel):
            unter[:] = [u for u in unter if not u.startswith(".")]
            for d in dateien:
                if d.lower().endswith((".pptx", ".potx")) and not d.startswith(("~$", ".")):
                    yield os.path.join(pfad, d)


def folientexte(pfad: str) -> list:
    """[(Nummer, Text)] je Folie in der Reihenfolge des Decks."""
    with zipfile.ZipFile(pfad) as z:
        rels = {r.get("Id"): r.get("Target") for r in fromstring(z.read("ppt/_rels/presentation.xml.rels"))}
        pres = z.read("ppt/presentation.xml").decode("utf-8", "replace")
        texte = []
        for nr, rid in enumerate(re.findall(r'<p:sldId [^>]*r:id="([^"]+)"', pres), 1):
            teil = posixpath.normpath(posixpath.join("ppt", rels.get(rid, "")))
            if teil in z.namelist():
                xml = z.read(teil).decode("utf-8", "replace")
                texte.append((nr, html.unescape(" ".join(TEXT_RE.findall(xml)))))
        return texte


def datum(pfad: str) -> str:
    return datetime.fromtimestamp(os.stat(pfad).st_mtime).strftime("%d.%m.%Y")


def main() -> int:
    args = sys.argv[1:]
    inhalt = "--inhalt" in args
    args = [a for a in args if a != "--inhalt"]
    ordner = []
    if "--ordner" in args:
        i = args.index("--ordner")
        ordner = args[i + 1:i + 2]
        del args[i:i + 2]
    if not args or not ordner:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    begriffe = args
    exakt = name_aus_link(begriffe[0]) if begriffe[0].startswith("http") else ""
    if begriffe[0].startswith("http") and not exakt:
        print("Link ohne Dateinamen (etwa Doc.aspx ohne file=), bitte den Namen des Decks nennen", file=sys.stderr)
        return 2
    klein = [b.lower() for b in begriffe]
    if not inhalt:
        treffer = [p for p in decks(ordner) if (os.path.basename(p).lower() == exakt.lower() if exakt else
                                                 all(b in os.path.basename(p).lower() for b in klein))]
        treffer.sort(key=os.path.getmtime, reverse=True)
        print(f"{len(treffer)} Treffer ({'Link: ' + exakt if exakt else 'Name: ' + ', '.join(begriffe)})"
              + (", neueste 15" if len(treffer) > 15 else "") + ":")
        for p in treffer[:15]:
            print(f"  {datum(p)}  {p}")
        return 0 if treffer else 1
    ende, online, gesucht, funde = time.monotonic() + ZEITLIMIT, 0, 0, []
    for p in decks(ordner):
        if time.monotonic() > ende:
            print(f"Zeitlimit {ZEITLIMIT} s erreicht, Suche unvollständig")
            break
        if getattr(os.stat(p), "st_flags", 0) & NUR_ONLINE:
            online += 1
            continue
        try:
            folien = [(n, t) for n, t in folientexte(p) if all(b in t.lower() for b in klein)]
        except (OSError, KeyError, zipfile.BadZipFile, ValueError):
            continue
        gesucht += 1
        if folien:
            funde.append((os.path.getmtime(p), p, folien))
    funde.sort(reverse=True)
    print(f"{len(funde)} Decks mit Treffern (Inhalt: {', '.join(begriffe)}), {gesucht} durchsucht"
          + (f", {online} nur online und nicht geladen" if online else "") + ":")
    for _t, p, folien in funde[:15]:
        print(f"  {datum(p)}  {p}")
        for n, t in folien[:5]:
            i = max(t.lower().find(klein[0]) - 40, 0)
            print(f"     Folie {n}: {'...' if i else ''}{t[i:i + 110]}")
        if len(folien) > 5:
            print(f"     und {len(folien) - 5} weitere Folien")
    return 0 if funde else 1


if __name__ == "__main__":
    sys.exit(main())
