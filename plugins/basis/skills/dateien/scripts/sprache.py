#!/usr/bin/env python3
"""Sprache aller Textstellen einer .pptx (oder .docx) prüfen und auf eine Sprache setzen. Pflichtschritt vor jeder
Übergabe einer Arbeitskopie, damit die Rechtschreibprüfung in PowerPoint und Word nicht halb Englisch prüft.

Aufruf:
  python3 sprache.py <datei.pptx|datei.docx> [--sprache=de-DE] [--pruefen]

Ohne --sprache gilt die Sprache der Präsentation: die häufigste unter den Textstellen der Folien (bei .docx im
Haupttext), sonst die Vorgabe der Präsentation. --pruefen zeigt nur, was abweicht, und ändert nichts.

.pptx: lang an allen Textstellen (a:rPr, a:endParaRPr, a:defRPr) in Folien, Notizen, Layouts, Mastern, Diagrammen und
der Vorgabe defaultTextStyle in presentation.xml. Fehlt lang an einer Vorgabe (a:defRPr in presentation.xml und den
Mastern), ergänzt das Skript es. .docx: w:val von w:lang in Text, Formatvorlagen, Kopf- und Fußzeilen.

Geschrieben wird nur bei Änderungen, erst in eine versteckte Temp-Datei daneben, dann in einem Schritt ersetzt.
Nur Standardbibliothek, läuft in der Sandbox von Cowork und am Mac. Exit-Codes: 0 ok, 1 Fehler, 2 Aufruf falsch.
"""
import argparse
import collections
import os
import re
import sys
import zipfile
from pathlib import Path

SPRACHE_RE = re.compile(r"[a-z]{2,3}(-[A-Za-z]{2,4})?(-[A-Z]{2})?")
PPTX_TEIL = re.compile(r"ppt/(slides|notesSlides|slideLayouts|slideMasters|notesMasters|handoutMasters|charts|"
                       r"diagrams)/[^/]+\.xml|ppt/presentation\.xml")
DOCX_TEIL = re.compile(r"word/(document|styles|footnotes|endnotes|comments|header\d*|footer\d*|numbering)\.xml")
# Textstellen in DrawingML: <a:rPr .../>, <a:endParaRPr ...>, <a:defRPr ...>
A_TAG = re.compile(r"<a:(rPr|endParaRPr|defRPr)\b([^>]*?)(/?)>")
A_LANG = re.compile(r'(\slang=")([^"]*)(")')
W_LANG = re.compile(r'(<w:lang\b[^>]*?\sw:val=")([^"]*)(")')
VORGABE_TEILE = re.compile(r"ppt/(presentation|slideMasters/[^/]+)\.xml")
MAX_BYTES = 300_000_000


def fehler(text: str, code: int = 1):
    print(text, file=sys.stderr)
    sys.exit(code)


def teile_lesen(pfad: Path) -> tuple:
    """(Art pptx oder docx, Liste der ZipInfo, {Name: Bytes})."""
    art = pfad.suffix.lower().lstrip(".")
    if art not in ("pptx", "docx"):
        fehler(f"Nur .pptx oder .docx, nicht {pfad.name}.", 2)
    if not pfad.is_file():
        fehler(f"Datei nicht gefunden: {pfad}.")
    if pfad.stat().st_size > MAX_BYTES:
        fehler(f"{pfad.name} ist zu groß.")
    try:
        with zipfile.ZipFile(pfad) as z:
            infos = z.infolist()
            inhalt = {i.filename: z.read(i) for i in infos}
    except (zipfile.BadZipFile, OSError) as e:
        fehler(f"{pfad.name} ist keine gültige Office-Datei ({type(e).__name__}).")
    return art, infos, inhalt


def textteile(art: str, inhalt: dict) -> list:
    muster = PPTX_TEIL if art == "pptx" else DOCX_TEIL
    return sorted(n for n in inhalt if muster.fullmatch(n))


def haeufigste(art: str, inhalt: dict) -> str:
    """Sprache der Präsentation: häufigstes lang an Textstellen der Folien (docx: Haupttext), sonst die Vorgabe."""
    zaehler = collections.Counter()
    if art == "pptx":
        for name in inhalt:
            if re.fullmatch(r"ppt/slides/[^/]+\.xml", name):
                text = inhalt[name].decode("utf-8", "replace")
                for tag in A_TAG.finditer(text):
                    if tag.group(1) == "rPr":
                        lang = A_LANG.search(tag.group(2))
                        if lang and lang.group(2):
                            zaehler[lang.group(2)] += 1
        if not zaehler and "ppt/presentation.xml" in inhalt:
            for lang in A_LANG.finditer(inhalt["ppt/presentation.xml"].decode("utf-8", "replace")):
                zaehler[lang.group(2)] += 1
    else:
        for name in ("word/document.xml", "word/styles.xml"):
            if name in inhalt:
                for lang in W_LANG.finditer(inhalt[name].decode("utf-8", "replace")):
                    zaehler[lang.group(2)] += 1
                if zaehler:
                    break
    return zaehler.most_common(1)[0][0] if zaehler else ""


def setzen(art: str, name: str, text: str, ziel: str, abweichend: collections.Counter) -> tuple:
    """(neuer Text, Zahl der geänderten Stellen, Zahl der ergänzten Vorgaben)."""
    if art == "docx":
        zahl = 0

        def w_ersetzen(m):
            nonlocal zahl
            if m.group(2) == ziel:
                return m.group(0)
            abweichend[m.group(2)] += 1
            zahl += 1
            return m.group(1) + ziel + m.group(3)
        return W_LANG.sub(w_ersetzen, text), zahl, 0
    geaendert = ergaenzt = 0
    vorgabe = bool(VORGABE_TEILE.fullmatch(name))

    def a_ersetzen(m):
        nonlocal geaendert, ergaenzt
        element, attribute, zu = m.groups()
        lang = A_LANG.search(attribute)
        if lang:
            if lang.group(2) == ziel:
                return m.group(0)
            abweichend[lang.group(2) or "(leer)"] += 1
            geaendert += 1
            attribute = attribute[:lang.start(2)] + ziel + attribute[lang.end(2):]
        elif element == "defRPr" and vorgabe:
            ergaenzt += 1
            attribute = f' lang="{ziel}"' + attribute
        else:
            return m.group(0)
        return f"<a:{element}{attribute}{zu}>"
    return A_TAG.sub(a_ersetzen, text), geaendert, ergaenzt


def schreiben(pfad: Path, infos: list, inhalt: dict) -> None:
    temp = pfad.with_name(f".{pfad.name}.sprache")
    try:
        with zipfile.ZipFile(temp, "w") as z:
            for info in infos:  # Reihenfolge, Kompression und Zeitstempel wie im Original
                z.writestr(info, inhalt[info.filename], compress_type=info.compress_type)
        os.replace(temp, pfad)
    finally:
        if temp.exists():
            temp.unlink()


def main(argv=None):
    p = argparse.ArgumentParser(description="Sprache aller Textstellen einer .pptx oder .docx setzen.")
    p.add_argument("datei")
    p.add_argument("--sprache", default="", help="etwa de-DE oder en-US, Standard die Sprache der Präsentation")
    p.add_argument("--pruefen", action="store_true", help="nur zeigen, nichts ändern")
    a = p.parse_args(argv)
    pfad = Path(a.datei).expanduser()
    art, infos, inhalt = teile_lesen(pfad)
    ziel = a.sprache.strip() or haeufigste(art, inhalt)
    if not ziel:
        fehler("Keine Sprache in der Datei gefunden, mit --sprache angeben (etwa de-DE).", 2)
    if not SPRACHE_RE.fullmatch(ziel):
        fehler(f"--sprache wie de-DE oder en-US, nicht {ziel!r}.", 2)
    abweichend, teile, gesamt, ergaenzt_gesamt = collections.Counter(), [], 0, 0
    for name in textteile(art, inhalt):
        alt = inhalt[name].decode("utf-8")
        neu, geaendert, ergaenzt = setzen(art, name, alt, ziel, abweichend)
        if geaendert or ergaenzt:
            teile.append(name)
            gesamt += geaendert
            ergaenzt_gesamt += ergaenzt
            inhalt[name] = neu.encode("utf-8")
    quelle = "angegeben" if a.sprache.strip() else "Sprache der Präsentation" if art == "pptx" else "Sprache des Texts"
    print(f"{pfad.name}: {ziel} ({quelle})")
    if not teile:
        print("Alle Textstellen stimmen, nichts geändert.")
        return
    liste = ", ".join(f"{k} {v}" for k, v in abweichend.most_common())
    print(f"Abweichend: {gesamt} Stellen ({liste or 'keine'}), ohne Sprache in Vorgaben: {ergaenzt_gesamt}, "
          f"in {len(teile)} Teilen")
    if a.pruefen:
        print("Nur geprüft, nichts geändert.")
        return
    schreiben(pfad, infos, inhalt)
    print(f"Gesetzt auf {ziel}: {gesamt} Stellen geändert, {ergaenzt_gesamt} Vorgaben ergänzt.")


if __name__ == "__main__":
    main()
