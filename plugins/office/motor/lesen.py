"""Inventar einer .pptx: Übersicht je Folie oder je Folie alle Formen mit ID, Art, Lage in cm, Schriftgrößen und Text,
dazu Kommentare und Notizen. Grundlage für die Änderungsliste von aendern.py (Formen über die ID). Legt nichts an.

Aufruf: python3 -I lesen.py <datei.pptx> [--uebersicht] [--folie 1,3-5] [--kommentare] [--notizen] [--voll]

--uebersicht  eine Zeile je Folie: Abschnitt, Titel, ausgeblendet, Zahl der Kommentare, Anfang der Notizen
--kommentare  nur Folien mit Kommentaren, --notizen nur Folien mit Notizen. --voll kürzt keine Texte.
Merkmale: [Tags] Markierung eines Add-ins (nur als Ganzes verschieben), [Platzhalter], [verborgen], [Tabelle],
[Diagramm], [OLE]. Kommentare liest der Skill nur, der Nutzer löst sie in PowerPoint. aendern.py und uebernehmen.py
nutzen die Helfer hier.
"""
import os
import sys

from lxml import etree
from pptx import Presentation

sys.dont_write_bytecode = True

EMU_CM = 360000
NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
      "p14": "http://schemas.microsoft.com/office/powerpoint/2010/main",
      "p188": "http://schemas.microsoft.com/office/powerpoint/2018/8/main"}
ABSCHNITTE_URI = "{521415D9-36F7-43E2-AB2F-B90AF26B5E84}"
RT_KOMMENTARE = ("http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments",
                 "http://schemas.microsoft.com/office/2018/10/relationships/comments")
ARTEN = {"sp": "Form", "pic": "Bild", "grpSp": "Gruppe", "graphicFrame": "Rahmen", "cxnSp": "Linie",
         "contentPart": "Freihand"}
RAHMEN = {"table": "Tabelle", "chart": "Diagramm", "ole": "OLE", "diagram": "SmartArt"}
NOTIZ_PLATZHALTER = {"sldImg", "sldNum", "hdr", "ftr", "dt"}  # alles andere mit Text auf der Notizseite ist Notiz


def q(tag: str) -> str:
    pre, t = tag.split(":")
    return "{%s}%s" % (NS[pre], t)


def zahl(emu_wert) -> str:
    return f"{emu_wert / EMU_CM:5.1f}".replace(".", ",")


def bereich(text: str, n: int) -> set:
    nummern = set()
    for teil in text.split(","):
        a, _, b = teil.partition("-")
        nummern.update(range(int(a), int(b or a) + 1))
    return {x for x in nummern if 1 <= x <= n}


def kurz(t: str, voll: bool, n: int = 90) -> str:
    return t if voll or len(t) <= n else t[:n - 3] + "..."


def absatz_text(p) -> str:
    return "".join("↵" if k.tag == q("a:br") else "".join(t.text or "" for t in k.iter(q("a:t")))
                   for k in p if k.tag in (q("a:r"), q("a:fld"), q("a:br")))


def text_von(el) -> str:
    return " / ".join(a for a in (absatz_text(p) for p in el.iter(q("a:p"))) if a.strip())


def platzhalter(el):
    return el.find("./*/" + q("p:nvPr") + "/" + q("p:ph"))


def notizen(slide) -> str:
    """Notiztext einer Folie. Hat der Notizenmaster einer Vorlage kein Notizfeld, steht der Text in einer eigenen Form."""
    if not slide.has_notes_slide:
        return ""
    teile = []
    for el in slide.notes_slide.shapes._spTree.iter(q("p:sp")):
        ph = platzhalter(el)
        if ph is None or ph.get("type") not in NOTIZ_PLATZHALTER:
            teile += [absatz_text(p) for p in el.iter(q("a:p"))]
    return "\n".join(teile).strip()


def autoren(prs_part) -> dict:
    """{authorId: Name} aus authors.xml (neue Kommentare) und commentAuthors.xml (alte)."""
    namen = {}
    for rel in prs_part.rels.values():
        if not rel.is_external and rel.reltype.endswith(("/authors", "/commentAuthors")):
            namen.update({x.get("id"): x.get("name") or "?" for x in etree.fromstring(rel.target_part.blob)})
    return namen


def kommentare(slide, namen: dict) -> list:
    """[(Autor, Datum, Text, [(Autor, Text)], erledigt)] aus alten (p:cm) und neuen Kommentaren (p188:cm)."""
    liste = []
    for rel in slide.part.rels.values():
        if rel.reltype not in RT_KOMMENTARE or rel.is_external:
            continue
        wurzel = etree.fromstring(rel.target_part.blob)
        for cm in wurzel.findall(q("p:cm")):
            liste.append((namen.get(cm.get("authorId"), "?"), (cm.get("dt") or "")[:10],
                          cm.findtext(q("p:text")) or "", [], False))
        for cm in wurzel.findall(q("p188:cm")):
            antworten = [(namen.get(r.get("authorId"), "?"), text_von(r.find(q("p188:txBody"))))
                         for r in cm.iter(q("p188:reply")) if r.find(q("p188:txBody")) is not None]
            tb = cm.find(q("p188:txBody"))
            liste.append((namen.get(cm.get("authorId"), "?"), (cm.get("created") or "")[:10],
                          text_von(tb) if tb is not None else "", antworten, cm.get("status") == "resolved"))
    return liste


def abschnitte(prs) -> list:
    """[(Name, [sldId-Elemente])] aus der Abschnittsliste in presentation.xml, [] ohne Abschnitte."""
    lst = prs.part._element.find(f"{q('p:extLst')}/{q('p:ext')}[@uri='{ABSCHNITTE_URI}']/{q('p14:sectionLst')}")
    if lst is None:
        return []
    return [(s.get("name"), list(s.iter(q("p14:sldId")))) for s in lst.findall(q("p14:section"))]


def titel(slide) -> str:
    for el in slide.shapes._spTree.iter(q("p:sp")):
        ph = platzhalter(el)
        if ph is not None and ph.get("type") in ("title", "ctrTitle"):
            return text_von(el)
    return ""


def merkmale(el) -> str:
    m = []
    if el.find(".//" + q("p:custDataLst") + "/" + q("p:tags")) is not None:
        m.append("[Tags]")
    ph = platzhalter(el)
    if ph is not None:
        m.append(f"[Platzhalter {ph.get('type') or 'body'}]")
    c = el.find("./*/" + q("p:cNvPr"))
    if c is not None and c.get("hidden") in ("1", "true"):
        m.append("[verborgen]")
    gd = el.find(".//" + q("a:graphicData"))
    if gd is not None:
        art = gd.get("uri", "").rsplit("/", 1)[-1]
        m.append(f"[{RAHMEN.get(art, art)}]")
    return " ".join(m)


def formen(baum, trafo, tiefe, voll, zeilen):
    """Kinder von spTree oder grpSp mit Lage auf der Folie. trafo: (sx, sy, tx, ty) Gruppe -> Folie."""
    for el in baum:
        if not isinstance(el.tag, str):
            continue
        name = etree.QName(el).localname
        if name == "AlternateContent":
            choice = el.find(q("mc:Choice"))
            if choice is not None:
                formen(choice, trafo, tiefe, voll, zeilen)
            continue
        if name not in ARTEN:
            continue
        c = el.find("./*/{*}cNvPr")  # Freihand (p14:contentPart) hat cNvPr im eigenen Namensraum
        if c is None:
            continue
        xf = next((x for x in (el.find(f"{q('p:spPr')}/{q('a:xfrm')}"), el.find(f"{q('p:grpSpPr')}/{q('a:xfrm')}"),
                               el.find(q("p:xfrm"))) if x is not None), None)
        sx, sy, tx, ty = trafo
        if xf is not None and xf.find(q("a:off")) is not None:
            off, ext = xf.find(q("a:off")), xf.find(q("a:ext"))
            lage = (f"{zahl(int(off.get('x')) * sx + tx)} {zahl(int(off.get('y')) * sy + ty)} "
                    f"{zahl(int(ext.get('cx')) * sx)} {zahl(int(ext.get('cy')) * sy)}")
            if xf.get("rot"):
                lage += f" ↻{int(xf.get('rot')) / 60000:g}°"
        else:
            lage = "  (Lage aus dem Layout)  "
        text = text_von(el) if name == "sp" else ""
        art = "Text" if text else ARTEN[name]
        sz = sorted({int(r.get("sz")) / 100 for r in el.iter(q("a:rPr")) if r.get("sz")})
        pt = "/".join(f"{s:g}" for s in sz) if sz else "-"
        if name == "graphicFrame" and el.find(".//" + q("a:tbl")) is not None:
            text = " | ".join(text_von(tc) for tc in el.iter(q("a:tc")) if text_von(tc))
        zeilen.append(f"{c.get('id'):>5} {'  ' * tiefe}{art:<8}{lage:<26} {pt:>9}  {merkmale(el)} "
                      f"{c.get('name')}: {kurz(text, voll)}".rstrip(": "))
        if name == "grpSp" and xf is not None and xf.find(q("a:chExt")) is not None and xf.find(q("a:off")) is not None:
            choff, chext = xf.find(q("a:chOff")), xf.find(q("a:chExt"))
            fx = int(ext.get("cx")) / max(int(chext.get("cx")), 1)
            fy = int(ext.get("cy")) / max(int(chext.get("cy")), 1)
            inner = (sx * fx, sy * fy, tx + sx * (int(off.get("x")) - int(choff.get("x")) * fx),
                     ty + sy * (int(off.get("y")) - int(choff.get("y")) * fy))
            formen(el, inner, tiefe + 1, voll, zeilen)


def main() -> int:
    args = sys.argv[1:]
    schalter = {s: s in args for s in ("--uebersicht", "--kommentare", "--notizen", "--voll")}
    args = [a for a in args if a not in schalter]
    auswahl = None
    if "--folie" in args:
        i = args.index("--folie")
        auswahl = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
    if len(args) != 1 or auswahl == "":
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    voll = schalter["--voll"]
    prs = Presentation(args[0])
    b, h, n = prs.slide_width, prs.slide_height, len(prs.slides)
    print(f"{os.path.basename(args[0])}: {n} Folie{'n' if n != 1 else ''}, {zahl(b).strip()} x {zahl(h).strip()} cm")
    nummern = bereich(auswahl, n) if auswahl else set(range(1, n + 1))
    abschnitt_von = {s.get("id"): name for name, ids in abschnitte(prs) for s in ids}
    sld_ids = [s.get("id") for s in prs.slides._sldIdLst]
    letzter, namen = None, autoren(prs.part)
    for i, slide in enumerate(prs.slides, 1):
        km, nz = kommentare(slide, namen), notizen(slide)
        if i not in nummern or (schalter["--kommentare"] and not km) or (schalter["--notizen"] and not nz):
            continue
        aus = " [ausgeblendet]" if slide._element.get("show") == "0" else ""
        abschnitt = abschnitt_von.get(sld_ids[i - 1])
        if schalter["--uebersicht"]:
            if abschnitt and abschnitt != letzter:
                print(f"\nAbschnitt {abschnitt}")
                letzter = abschnitt
            zusatz = (f" · {len(km)} Kommentar{'e' if len(km) != 1 else ''}" if km else "") + \
                     (f" · Notiz: {kurz(nz.replace(chr(10), ' / '), voll, 60)}" if nz else "")
            print(f"{i:>4}{aus} {kurz(titel(slide), voll, 70) or '(ohne Titel)'}{zusatz}")
            continue
        print(f"\nFolie {i}{aus} · Layout {slide.slide_layout.name}" + (f" · Abschnitt {abschnitt}" if abschnitt else ""))
        print(f"{'ID':>5} {'Art':<8}{'x':>5} {'y':>5} {'B':>5} {'H':>5}      {'pt':>9}  Merkmale, Name: Text")
        zeilen = []
        formen(slide.shapes._spTree, (1.0, 1.0, 0.0, 0.0), 0, voll, zeilen)
        print("\n".join(zeilen))
        for autor, datum, text, antworten, erledigt in km:
            print(f"  Kommentar {autor} {datum}{' [erledigt]' if erledigt else ''}: {kurz(text, voll, 300)}")
            for a, t in antworten:
                print(f"    Antwort {a}: {kurz(t, voll, 300)}")
        if nz:
            print(f"  Notizen: {kurz(nz.replace(chr(10), ' / '), voll, 300)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
