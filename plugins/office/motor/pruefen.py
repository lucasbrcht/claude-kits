"""PowerPoint-Fallen, die eine XSD-Prüfung nicht meldet, danach auf Wunsch die XSD-Prüfung mit validate.py aus dem
Skill pptx von Anthropic, wenn motor.pptx_validate in der config.json von office darauf zeigt (der Server reicht den
Pfad als KITS_PPTX_VALIDATE weiter). Ohne den Pfad fehlt nur die XSD-Prüfung.

Aufruf: python3 -I pruefen.py <datei.pptx> [--original <draft.pptx>] [--ohne-xsd]

Findet Markierungen von Add-ins (p:custDataLst), die sich mehrere Formen teilen, Teile (Markierungen, Diagramme,
SmartArt), auf die mehrere Folien zeigen, mehrere Füllungen in einem Element und Altlasten aus Referenzdecks: einen
Änderungsverlauf (changesInfo mit Namen der Bearbeiter) und Zähler in docProps/app.xml, die nicht zum Deck passen.
Formen in mc:AlternateContent (Choice und Fallback beschreiben dieselbe Form) zählen einmal. Mit --original zählen
Funde, die schon im Original stecken, nicht als Fehler.
Rückgabewert 0 ohne Fund, 1 mit Fund, 2 bei falschem Aufruf. Nur Standardbibliothek, läuft auch unter python3 (3.9).
"""
import os
import posixpath
import subprocess
import sys
import zipfile

try:
    from defusedxml.ElementTree import fromstring
except ImportError:  # ohne defusedxml: expat löst keine externen Entitäten auf
    from xml.etree.ElementTree import fromstring

sys.dont_write_bytecode = True

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
APP = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
VALIDATE = "KITS_PPTX_VALIDATE"
# Je Folie eine eigene Kopie nötig. Eingebettete Objekte teilt PowerPoint selbst, oft eins auf vielen Folien
GETEILT = ("ppt/tags/", "ppt/charts/", "ppt/diagrams/")

ABHILFE = {
    "tag-mehrfach": "PowerPoint öffnet die Datei dann nicht. Formen nicht mit Markierung kopieren",
    "teil-geteilt": "Änderungen an einer Folie träfen die andere. Folien mit uebernehmen kopieren, nicht mit "
                    "add_slide.py",
    "fuellung-mehrfach": "PowerPoint repariert die Datei beim Öffnen. Nur eine Füllung je Element, farbe in "
                         "folien_aendern ersetzt auch grpFill",
    "aenderungsverlauf": "verweist nach Löschen auf fehlende Folien und trägt Namen der Bearbeiter. folien_aendern "
                         "entfernt ihn",
    "app-zaehler": "Altlast aus einem Referenzdeck. folien_aendern setzt die Zähler neu",
}


def q(ns: str, tag: str) -> str:
    return "{%s}%s" % (ns, tag)


def fund(art, teil, schluessel, anzahl, text):
    return {"art": art, "teil": teil, "schluessel": (art, teil, schluessel), "anzahl": anzahl, "text": text}


CONTAINER = (q(P, "spTree"), q(P, "grpSp"))
# Elemente mit höchstens einer Füllung. Zwei (z.B. grpFill neben solidFill) meldet die XSD-Prüfung nicht.
FUELLUNGEN = {q(A, t) for t in ("noFill", "solidFill", "gradFill", "blipFill", "pattFill", "grpFill")}
FUELL_TRAEGER = (q(P, "spPr"), q(P, "grpSpPr"), q(A, "ln"), q(A, "rPr"), q(A, "endParaRPr"), q(A, "defRPr"),
                 q(A, "tcPr"))


def form_id(el, par) -> str:
    """ID der Form, zu der el gehört, sonst 'Folie'."""
    while el is not None:
        c = el.find("./*/" + q(P, "cNvPr"))
        if c is not None:
            return c.get("id") or "?"
        el = par.get(el)
    return "Folie"


def oberste(el, par):
    """Die Form direkt unter spTree oder grpSp, zu der el gehört. mc:AlternateContent dort zählt als eine Form, ebenso
    ein OLE-Rahmen mit seinem Ersatzbild, das PowerPoint mit derselben ID und denselben Tags schreibt."""
    x = el
    while x is not None:
        p = par.get(x)
        if p is not None and p.tag in CONTAINER:
            return x
        x = p
    return el


def ids_text(ids: list) -> str:
    return ", ".join(ids[:10]) + (f" und {len(ids) - 10} weitere" if len(ids) > 10 else "")


def funde_teil(teil: str, root, rels: dict) -> list:
    """Geteilte Markierungen und mehrfache Füllungen in einem XML-Teil (Folie, Layout, Master, Notizseite)."""
    par = {k: e for e in root.iter() for k in e}
    funde, tags = [], {}
    for t in root.iter(q(P, "tags")):
        if t.get(q(R, "id")):
            tags.setdefault(t.get(q(R, "id")), {}).setdefault(oberste(t, par), t)
    for rid, formen in tags.items():
        if len(formen) > 1:
            ids = [form_id(t, par) for t in formen.values()]
            name = f" ({posixpath.basename(rels[rid])})" if rid in rels else ""
            funde.append(fund("tag-mehrfach", teil, rid, len(ids),
                              f"Markierung {rid}{name} genutzt {len(ids)}-mal (Form-IDs {ids_text(ids)})"))
    traeger = [e for tag in FUELL_TRAEGER for e in root.iter(tag) if sum(1 for k in e if k.tag in FUELLUNGEN) > 1]
    if traeger:
        ids = sorted({form_id(e, par) for e in traeger}, key=lambda i: (not i.isdigit(), int(i) if i.isdigit() else 0))
        funde.append(fund("fuellung-mehrfach", teil, "", len(traeger),
                          f"{len(traeger)} Elemente mit mehreren Füllungen (Form-IDs {ids_text(ids)})"))
    return funde


def lade_rels(z: zipfile.ZipFile, teil: str) -> dict:
    """{rId: (Typ, Ziel als Paketpfad)} der internen Beziehungen eines Teils."""
    name = posixpath.join(posixpath.dirname(teil), "_rels", posixpath.basename(teil) + ".rels")
    if name not in z.namelist():
        return {}
    rels = {}
    for r in fromstring(z.read(name)).iter(q(REL, "Relationship")):
        ziel = r.get("Target") or ""
        if r.get("TargetMode") != "External" and ziel != "NULL":
            rels[r.get("Id")] = (r.get("Type") or "", ziel.lstrip("/") if ziel.startswith("/") else
                                 posixpath.normpath(posixpath.join(posixpath.dirname(teil), ziel)))
    return rels


def analyse(pfad: str):
    """(Info-Zeilen, Funde) einer .pptx."""
    funde, nutzer = [], {}
    with zipfile.ZipFile(pfad) as z:
        namen = set(z.namelist())
        pres_rels = lade_rels(z, "ppt/presentation.xml")
        pres = fromstring(z.read("ppt/presentation.xml"))
        folien = [pres_rels[s.get(q(R, "id"))][1] for s in pres.iter(q(P, "sldId")) if s.get(q(R, "id")) in pres_rels]
        notizen = versteckt = 0
        for n in sorted(namen):
            if not n.endswith(".xml") or "/_rels/" in n:
                continue
            if n.startswith(("ppt/slides/", "ppt/slideLayouts/", "ppt/slideMasters/", "ppt/notesSlides/",
                             "ppt/charts/")):
                rels = lade_rels(z, n)
                for _typ, ziel in rels.values():
                    if ziel.startswith(GETEILT) and not n.startswith("ppt/notesSlides/"):
                        nutzer.setdefault(ziel, set()).add(n)
                if not n.startswith("ppt/charts/"):
                    root = fromstring(z.read(n))
                    funde += funde_teil(n, root, {k: v[1] for k, v in rels.items()})
                    if n in folien:
                        versteckt += root.get("show") == "0"
                        notizen += any(t.endswith("/notesSlide") for t, _z in rels.values())
        for ziel, quellen in sorted(nutzer.items()):
            if len(quellen) > 1:
                funde.append(fund("teil-geteilt", ziel, "", len(quellen),
                                  f"{len(quellen)} Teile zeigen darauf ({', '.join(sorted(quellen)[:5])})"))
        verlauf = [z_ for t, z_ in pres_rels.values() if t.endswith("/changesInfo") and z_ in namen]
        for v in verlauf:
            funde.append(fund("aenderungsverlauf", v, "", 1, f"Änderungsverlauf, {z.getinfo(v).file_size // 1024} KB"))
        if "docProps/app.xml" in namen:
            app = fromstring(z.read("docProps/app.xml"))
            ist = {"Slides": len(folien), "Notes": notizen, "HiddenSlides": versteckt}
            falsch = [f"{k} {app.findtext(q(APP, k))} statt {v}" for k, v in ist.items()
                      if app.find(q(APP, k)) is not None and (app.findtext(q(APP, k)) or "").strip() != str(v)]
            if falsch:
                funde.append(fund("app-zaehler", "docProps/app.xml", "", 1, "Zähler " + ", ".join(falsch)))
    return [f"{len(folien)} Folie{'n' if len(folien) != 1 else ''}, davon {versteckt} ausgeblendet"], funde


def validate_py():
    """validate.py des pptx-Skills aus KITS_PPTX_VALIDATE, None ohne Angabe."""
    wert = os.environ.get(VALIDATE, "").strip()
    return wert or None


def xsd(pfad: str, original, ausgabe) -> int:
    """validate.py ohne -P aufrufen, sonst fehlen seine Module helpers und validators. 1 bei Fehlern."""
    v = validate_py()
    if not v:
        ausgabe("  INFO     XSD-Prüfung aus (motor.pptx_validate in der config.json von office fehlt)")
        return 0
    if not os.path.isfile(v):
        ausgabe(f"  WARNUNG  validate.py nicht gefunden ({v}), XSD-Prüfung fehlt")
        return 0
    cmd = [sys.executable, v, os.path.abspath(pfad)] + (["--original", os.path.abspath(original)] if original else [])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.dirname(v), timeout=240)
    except subprocess.TimeoutExpired:
        ausgabe("  WARNUNG  validate.py nach 4 Minuten abgebrochen, XSD-Prüfung fehlt")
        return 0
    except OSError as e:
        ausgabe(f"  WARNUNG  validate.py nicht startbar ({e.strerror or e}), XSD-Prüfung fehlt")
        return 0
    zeilen = [z for z in (r.stdout + r.stderr).splitlines() if z.strip()]
    if r.returncode == 0:
        ausgabe("  OK       XSD (validate.py" + (", nur neue Fehler gegenüber dem Original)" if original else ")"))
        return 0
    ausgabe("  FEHLER   XSD (validate.py):")
    for z in zeilen[:25]:
        ausgabe("           " + z.strip())
    if len(zeilen) > 25:
        ausgabe(f"           und {len(zeilen) - 25} weitere Zeilen")
    return 1


def pruefe(pfad: str, original: str = None, mit_xsd: bool = True, ausgabe=print) -> int:
    """Prüfung mit Ausgabe. Liefert die Zahl der Funde, die zählen (ohne die, die schon im Original stecken)."""
    infos, funde = analyse(pfad)
    basis = {f["schluessel"]: f["anzahl"] for f in analyse(original)[1]} if original else {}
    ausgabe(f"Prüfung {os.path.basename(pfad)}" + (f" (Vergleich mit {os.path.basename(original)})" if original else ""))
    for i in infos:
        ausgabe(f"  INFO     {i}")
    zaehlt = 0
    for f in funde:
        if f["schluessel"] in basis and f["anzahl"] <= basis[f["schluessel"]]:
            ausgabe(f"  ORIGINAL {f['teil']}: {f['text']} (steckt schon im Original)")
        else:
            zaehlt += 1
            ausgabe(f"  FEHLER   {f['teil']}: {f['text']}. {ABHILFE[f['art']]}")
    if not zaehlt:
        ausgabe("  OK       keine PowerPoint-Fallen")
    if mit_xsd:
        zaehlt += xsd(pfad, original, ausgabe)
    return zaehlt


def main() -> int:
    args = sys.argv[1:]
    original, mit_xsd = None, "--ohne-xsd" not in args
    args = [a for a in args if a != "--ohne-xsd"]
    if "--original" in args:
        i = args.index("--original")
        original = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
    if len(args) != 1 or not args[0].lower().endswith((".pptx", ".potx")) or original == "":
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    for p in [args[0]] + ([original] if original else []):
        if not os.path.isfile(p):
            print(f"Datei fehlt: {p}", file=sys.stderr)
            return 2
    return 1 if pruefe(args[0], original, mit_xsd) else 0


if __name__ == "__main__":
    sys.exit(main())
