"""Änderungsliste (JSON) auf den aktuellen Stand der Arbeitskopie in der Ablage anwenden. Das Original bleibt
unangetastet. Jeder Lauf ist eine Runde (stand.py): Er meldet Änderungen von Hand seit der letzten Runde, ändert eine
Kopie und schreibt sie nur zurück, wenn sie keine Änderung von Hand überschreibt (sonst HALT, mit --ueberschreiben
nur auf ausdrücklichen Wunsch). Die Liste enthält darum nur die neuen Wünsche, frühere Runden stecken schon in der
Arbeitskopie. Rücknahme der letzten Runde: arbeitskopie mit aktion zuruecknehmen. Ist die Arbeitskopie in Office
offen, schreibt der Lauf nichts. Stand und Stand davor liegen im Zustandsordner (Zwischenordner im Datenordner von
office), nie neben der Arbeitskopie.

Aufruf (der Server gibt alle Pfade vor):
  python3 -I aendern.py --original <Original> --ziel <Arbeitskopie> --zustand <Ordner> [--vergleich]
                        [--ueberschreiben] <liste.json>

Liste: {"aenderungen": [{"art": "...", "folie": <Nummer wie folien_lesen auf der Arbeitskopie>, ...}]}
Arten (folie und form wie in lesen.py, form auch als Name, Maße in cm):
  text         alt, neu, form und folie optional, alle: true für mehrere Treffer. Format bleibt
  absaetze     form, absaetze: ["Text", {"text": "...", "ebene": 1, "punkt": true}]. Format des ersten Absatzes,
               punkt true setzt eine echte Aufzählung mit hängendem Einzug, false nimmt sie weg
  in_form      form (Textfeld), ziel (Form ohne Text darunter): Text in die Form, Textfeld weg, Lage des Texts
               bleibt über die Innenränder
  zelle        form, zeile, spalte (ab 1), neu (\\n gibt Absätze)
  notizen      neu, "" leert (umgesetzte Wünsche löschen)
  backup       ausblenden und ans Ende des Abschnitts Backup (legt ihn an), statt löschen
  verschieben  nach: hinter diese Folie, 0 an den Anfang
  loeschen     nur auf Zuruf des Nutzers
  lage         form, x, y, b, h (je optional), auch für Platzhalter mit Lage aus dem Layout, Markierungen von
               Add-ins nur als ganzer Rahmen oder ganze Gruppe
  farbe        form, fuellung und/oder schrift: Hex wie 1F4E79 oder Schemafarbe wie accent1
  skript       datei: Notausgang, Python-Datei mit umbau(prs), geänderte Folien erkennt der Lauf selbst
  uebernehmen  quelle (Deck, auch das Original), folie (dort), nach, als (Name für spätere Einträge, sonst neu1),
               layout (optional, sonst gleicher Name im Ziel). Jedes Teil als eigene Kopie (uebernehmen.py)
  reparieren   nur auf Wunsch: eingebettete Schriften ohne Datei aus p:embeddedFontLst entfernen, ist die Liste
               leer, auch sie und embedTrueTypeFonts. [trash]/ fällt beim Schreiben ohnehin weg

Reihenfolge: erst reparieren und uebernehmen, dann Inhalte, zuletzt backup, verschieben, loeschen. Ergebnis: die
Arbeitskopie, die geänderten Bereiche und die Seiten der geänderten und neuen Folien im PDF (ausgeblendete fehlen
dort). Mit --vergleich zusätzlich <Stamm> Vergleich.pptx im Themen-Ordner mit den Paaren vorher und nachher und den
neuen Folien. Jeder Lauf entfernt den Änderungsverlauf (changesInfo mit Namen der Bearbeiter) und setzt die Zähler in
docProps/app.xml neu. Danach prüft er die Arbeitskopie wie pruefen.py (Funde aus dem Original zählen nicht).
Rückgabewert 0, 1 bei einem Fehler in einem Eintrag (dann ist nichts geschrieben), HALT, einem Fund der Prüfung oder
offener Arbeitskopie, 2 bei falschem Aufruf.
"""
import copy
import json
import os
import runpy
import sys
import uuid

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.util import Cm, Pt

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pruefen  # noqa: E402
import stand  # noqa: E402
import uebernehmen  # noqa: E402
from lesen import (ABSCHNITTE_URI, EMU_CM, NOTIZ_PLATZHALTER, NS, absatz_text, kurz, notizen,  # noqa: E402
                   platzhalter, q)
from uebernehmen import Fehler  # noqa: E402

SICHTBAR = {"text", "absaetze", "zelle", "lage", "farbe", "in_form"}  # Arten, die im Vergleich als Paar erscheinen
STRUKTUR = {"backup", "verschieben", "loeschen"}  # wirken nach allen Inhalten, Nummern bleiben die vor dem Lauf
VORWEG = {"uebernehmen", "reparieren"}
FUELLUNGEN = ("a:solidFill", "a:noFill", "a:gradFill", "a:pattFill", "a:blipFill", "a:grpFill")
VERGLEICH = " Vergleich.pptx"


# ---------- Reparieren ----------
def reparieren(prs) -> str:
    """Eingebettete Schriften ohne Datei entfernen (leere oder unbekannte Verweise, Ziel fehlt). Bleibt keine, fallen
    die Liste und embedTrueTypeFonts weg. Gültig eingebettete Schriften bleiben."""
    pres = prs.part._element
    lst = pres.find(q("p:embeddedFontLst"))
    if lst is None:
        return "Reparieren: keine eingebetteten Schriften, nichts zu tun ([trash]/ fällt beim Schreiben weg)"
    weg = []
    for schrift in list(lst.findall(q("p:embeddedFont"))):
        font = schrift.find(q("p:font"))
        name = (font.get("typeface") if font is not None else "") or "ohne Namen"
        for art in pruefen.SCHRIFT_ARTEN:
            el = schrift.find(q(f"p:{art}"))
            if el is None:
                continue
            rid = el.get(q("r:id")) or ""
            rel = prs.part.rels.get(rid) if rid else None
            if rel is None or rel.is_external:
                schrift.remove(el)
                weg.append(name)
        if not any(schrift.find(q(f"p:{a}")) is not None for a in pruefen.SCHRIFT_ARTEN):
            lst.remove(schrift)
    if not len(lst):
        pres.remove(lst)
        for attr in ("embedTrueTypeFonts", "saveSubsetFonts"):
            pres.attrib.pop(attr, None)
        return ("Reparieren: eingebettete Schriften ohne Datei entfernt (" + ", ".join(dict.fromkeys(weg)) + "), Liste "
                "und embedTrueTypeFonts weg. In PowerPoint Schriftarten in die Datei einbetten für dieses Deck "
                "ausschalten") if weg else "Reparieren: leere Liste der Schriften entfernt"
    return ("Reparieren: Schriften ohne Datei entfernt (" + ", ".join(dict.fromkeys(weg)) + "), gültig eingebettete "
            "bleiben") if weg else "Reparieren: eingebettete Schriften in Ordnung, nichts zu tun"


# ---------- Inhalte ----------
def formen(slide, fid) -> list:
    """Alle Elemente mit dieser ID oder diesem Namen (in mc:AlternateContent stehen Choice und Fallback)."""
    treffer = [c.getparent().getparent() for c in slide.shapes._spTree.iter(q("p:cNvPr"))
               if c.get("id") == str(fid) or c.get("name") == fid]
    if not treffer:
        raise Fehler(f"Form {fid} fehlt")
    return treffer


def im_fallback(el) -> bool:
    return any(a.tag == q("mc:Fallback") for a in el.iterancestors())


def zaehlen(wurzeln, alt: str) -> int:
    return sum("".join(t.text or "" for t in p.iter(q("a:t"))).count(alt)
               for w in wurzeln for p in w.iter(q("a:p")) if not im_fallback(p))


def ersetzen(p, alt: str, neu: str):
    """alt in einem Absatz durch neu ersetzen, auch wenn alt über mehrere Läufe reicht (Rechtschreibprüfung teilt
    Läufe oft). Der neue Text übernimmt das Format des ersten Laufs, geleerte Läufe fallen weg."""
    start = 0
    while True:
        ts = [r.find(q("a:t")) for r in p if r.tag in (q("a:r"), q("a:fld")) and r.find(q("a:t")) is not None]
        ganz = "".join(t.text or "" for t in ts)
        i = ganz.find(alt, start)
        if i < 0:
            return
        pos, erster = 0, None
        for k, t in enumerate(ts):
            n = len(t.text or "")
            if erster is None and i < pos + n:
                erster, a = k, i - pos
            if erster is not None and i + len(alt) <= pos + n:
                letzter, b = k, i + len(alt) - pos
                break
            pos += n
        if erster == letzter:
            ts[erster].text = ts[erster].text[:a] + neu + ts[erster].text[b:]
        else:
            ts[erster].text = ts[erster].text[:a] + neu
            ts[letzter].text = ts[letzter].text[b:]
            for t in ts[erster + 1:letzter]:
                t.text = ""
        for t in ts:
            if not t.text and t.getparent().tag == q("a:r"):
                p.remove(t.getparent())  # leere a:t mag PowerPoint nicht
        start = i + len(neu)


def absaetze_setzen(tb, absaetze: list) -> str:
    """Absätze eines Textkörpers ersetzen, Format von erstem Absatz und erstem Lauf. Liefert den alten Text."""
    ps = tb.findall(q("a:p"))
    ppr = ps[0].find(q("a:pPr")) if ps else None
    end = ps[0].find(q("a:endParaRPr")) if ps else None
    lauf = next((r for p in ps for r in p.findall(q("a:r"))), None)
    rpr = lauf.find(q("a:rPr")) if lauf is not None else None
    alt = " / ".join(t for t in (absatz_text(p) for p in ps) if t.strip())
    for p in ps:
        tb.remove(p)
    for eintrag in absaetze or [""]:
        text, ebene = (eintrag, None) if isinstance(eintrag, str) else (eintrag.get("text", ""), eintrag.get("ebene"))
        p = etree.SubElement(tb, q("a:p"))
        if ppr is not None:
            p.append(copy.deepcopy(ppr))
        if ebene is not None:
            pp = p.find(q("a:pPr"))
            if pp is None:
                pp = etree.SubElement(p, q("a:pPr"))
            pp.set("lvl", str(ebene)) if ebene else pp.attrib.pop("lvl", None)
        if isinstance(eintrag, dict) and eintrag.get("punkt") is not None:
            pp = p.find(q("a:pPr"))
            aufzaehlung(pp if pp is not None else etree.SubElement(p, q("a:pPr")), bool(eintrag["punkt"]))
        if text:
            r = etree.SubElement(p, q("a:r"))
            if rpr is not None:
                r.append(copy.deepcopy(rpr))
            etree.SubElement(r, q("a:t")).text = text
        if end is not None:
            p.append(copy.deepcopy(end))
    return alt


BU_TAGS = ("a:buFontTx", "a:buFont", "a:buNone", "a:buAutoNum", "a:buChar", "a:buBlip")
EINZUG = 228600  # 0,635 cm hängender Einzug je Ebene


def aufzaehlung(pp, an: bool):
    """Echte Aufzählung im Absatzformat (Zeichen mit hängendem Einzug) oder keine. Getippte Zeichen braucht es dann
    nicht, die zweite Zeile steht unter dem Text."""
    for tag in BU_TAGS:
        for x in pp.findall(q(tag)):
            pp.remove(x)
    ebene = int(pp.get("lvl") or 0)
    pp.set("marL", str(EINZUG * (ebene + 1)) if an else "0")
    pp.set("indent", str(-EINZUG) if an else "0")
    neu = [element("a:buFont", typeface="Arial"), element("a:buChar", char="•")] if an else [element("a:buNone")]
    nach = next((pp.find(q(t)) for t in ("a:tabLst", "a:defRPr", "a:extLst") if pp.find(q(t)) is not None), None)
    for x in neu:
        nach.addprevious(x) if nach is not None else pp.append(x)


def element(tag: str, **attribute):
    """Neues Element mit dem üblichen Präfix (sonst schreibt lxml ns0:)."""
    return etree.Element(q(tag), nsmap={tag.split(":")[0]: NS[tag.split(":")[0]]}, **attribute)


def solid(c: str):
    s = element("a:solidFill")
    if c.startswith(("accent", "tx", "bg", "dk", "lt", "hlink", "folHlink")):
        etree.SubElement(s, q("a:schemeClr"), val=c)
    else:
        etree.SubElement(s, q("a:srgbClr"), val=c.lstrip("#").upper())
    return s


def fuellung(el, c: str):
    """Füllung ersetzen, auch eine von der Gruppe geerbte (grpFill): zwei Füllungen repariert PowerPoint."""
    sp = el.find(q("p:spPr")) if el.find(q("p:spPr")) is not None else el.find(q("p:grpSpPr"))
    if sp is None:
        raise Fehler("Form ohne Füllung (Bild, Rahmen oder Linie)")
    for tag in FUELLUNGEN:
        x = sp.find(q(tag))
        if x is not None:
            x.addprevious(solid(c))
            sp.remove(x)
            return
    vor = next((sp.find(q(t)) for t in ("a:prstGeom", "a:custGeom", "a:xfrm") if sp.find(q(t)) is not None), None)
    vor.addnext(solid(c)) if vor is not None else sp.insert(0, solid(c))  # Füllung steht vor a:ln


def schriftfarbe(el, c: str):
    for r in el.iter(q("a:r")):
        rpr = r.find(q("a:rPr"))
        if rpr is None:
            rpr = element("a:rPr")
            r.insert(0, rpr)
        for tag in FUELLUNGEN:
            for x in rpr.findall(q(tag)):
                rpr.remove(x)
        ln = rpr.find(q("a:ln"))
        ln.addnext(solid(c)) if ln is not None else rpr.insert(0, solid(c))


def lage(el, e: dict, slide) -> str:
    """Lage in cm, nur für Formen direkt auf der Folie: Formen in Gruppen wandern mit der ganzen Gruppe. Erbt ein
    Platzhalter die Lage vom Layout, bekommt er sie zuerst als eigene (python-pptx liest sie aus dem Layout)."""
    if any(a.tag == q("p:grpSp") for a in el.iterancestors()):
        raise Fehler("Form steht in einer Gruppe, die ganze Gruppe verschieben")
    xf = next((x for x in (el.find(f"{q('p:spPr')}/{q('a:xfrm')}"), el.find(f"{q('p:grpSpPr')}/{q('a:xfrm')}"),
                           el.find(q("p:xfrm"))) if x is not None), None)
    if xf is None or xf.find(q("a:off")) is None:
        form = next((s for s in slide.shapes if s._element is el), None)
        if form is None or not form.is_placeholder or None in (form.left, form.top, form.width, form.height):
            raise Fehler("Form ohne Lage, auch nicht im Layout")
        form.left, form.top, form.width, form.height = form.left, form.top, form.width, form.height
        xf = el.find(f"{q('p:spPr')}/{q('a:xfrm')}")
    werte = [(xf.find(q(t)), k) for t, ks in (("a:off", "xy"), ("a:ext", ("cx", "cy"))) for k in ks]
    alt = [int(x.get(k)) / EMU_CM for x, k in werte]
    neu = [float(e.get(k, v)) for k, v in zip("xybh", alt)]
    for (x, k), v in zip(werte, neu):
        x.set(k, str(max(round(v * EMU_CM), 0)))  # Kinder einer Gruppe skalieren mit
    zeig = lambda w: " ".join(f"{v:.1f}".replace(".", ",") for v in w)  # noqa: E731
    return f"{zeig(alt)} -> {zeig(neu)} cm"


def eine_form(slide, fid, was: str):
    els = [el for el in formen(slide, fid) if not im_fallback(el)]
    if len(els) != 1 or els[0].tag != q("p:sp"):
        raise Fehler(f"{was} {fid} muss eine einfache Form sein (kein Bild, keine Tabelle, keine Gruppe)")
    return els[0]


def lage_emu(el, was: str) -> list:
    xf = el.find(f"{q('p:spPr')}/{q('a:xfrm')}")
    if xf is None or xf.find(q("a:off")) is None or xf.find(q("a:ext")) is None:
        raise Fehler(f"{was} ohne eigene Lage (Platzhalter mit Lage aus dem Layout), erst mit lage setzen")
    return [int(xf.find(q("a:off")).get(k)) for k in "xy"] + [int(xf.find(q("a:ext")).get(k)) for k in ("cx", "cy")]


def in_form(slide, e: dict) -> str:
    """Text eines Textfelds in die Form darunter übernehmen und das Textfeld entfernen. Die Innenränder der Form
    rücken den Text dorthin, wo er im Textfeld stand. Gibt die Form eine eigene Textfarbe vor (Stil), behält der Text
    die Farbe tx1, die er im Textfeld hatte."""
    t, s = eine_form(slide, e["form"], "form"), eine_form(slide, e["ziel"], "ziel")
    if t is s:
        raise Fehler("form und ziel sind dieselbe Form")
    if t.getparent() is not s.getparent():
        raise Fehler("form und ziel liegen in verschiedenen Gruppen")
    tb, sb = t.find(q("p:txBody")), s.find(q("p:txBody"))
    if tb is None or not "".join(x.text or "" for x in tb.iter(q("a:t"))).strip():
        raise Fehler("form hat keinen Text")
    if sb is not None and "".join(x.text or "" for x in sb.iter(q("a:t"))).strip():
        raise Fehler("ziel hat schon Text, Text dort erst leeren oder mit absaetze ergänzen")
    lt, ls = lage_emu(t, "form"), lage_emu(s, "ziel")
    if pruefen.ueberdeckt(lt, ls) < 0.5:
        raise Fehler(f"Textfeld {e['form']} liegt nicht auf Form {e['ziel']}")
    neu = copy.deepcopy(tb)
    bp = neu.find(q("a:bodyPr"))
    if bp is None:
        bp = element("a:bodyPr")
        neu.insert(0, bp)
    ins = {k: int(bp.get(k) or std) for k, std in (("lIns", 91440), ("rIns", 91440), ("tIns", 45720),
                                                    ("bIns", 45720))}
    werte = {"lIns": lt[0] + ins["lIns"] - ls[0], "rIns": ls[0] + ls[2] - lt[0] - lt[2] + ins["rIns"],
             "tIns": lt[1] + ins["tIns"] - ls[1], "bIns": ls[1] + ls[3] - lt[1] - lt[3] + ins["bIns"]}
    for k, v in werte.items():
        bp.set(k, str(max(v, 0)))
    for x in bp.findall(q("a:spAutoFit")):  # passt sonst die Form an den Text an
        bp.remove(x)
    farbe = ""
    if s.find(f"{q('p:style')}/{q('a:fontRef')}") is not None and t.find(q("p:style")) is None:
        for r in neu.iter(q("a:r")):
            if r.find(q("a:rPr")) is None:
                r.insert(0, element("a:rPr"))
        for rpr in list(neu.iter(q("a:rPr"))) + list(neu.iter(q("a:endParaRPr"))):
            if not any(rpr.find(q(f)) is not None for f in FUELLUNGEN):
                ln = rpr.find(q("a:ln"))
                ln.addnext(solid("tx1")) if ln is not None else rpr.insert(0, solid("tx1"))
        farbe = ", Textfarbe tx1 wie im Textfeld"
    if sb is not None:
        s.replace(sb, neu)
    else:
        ext = s.find(q("p:extLst"))
        ext.addprevious(neu) if ext is not None else s.append(neu)
    t.getparent().remove(t)
    name = lambda el: el.find(f"./*/{q('p:cNvPr')}").get("name") or ""  # noqa: E731
    return (f"Text in Form: Textfeld {e['form']} ({name(t)}) in Form {e['ziel']} ({name(s)}) übernommen, Textfeld "
            f"entfernt{farbe}")


def notizen_setzen(slide, neu: str) -> str:
    alt = notizen(slide)
    felder = [el for el in (slide.notes_slide.shapes._spTree.iter(q("p:sp")) if slide.has_notes_slide else [])
              if el.find(q("p:txBody")) is not None
              and (platzhalter(el) is None or platzhalter(el).get("type") not in NOTIZ_PLATZHALTER)]
    if not felder:
        if neu:
            raise Fehler("keine Notizseite mit Notizfeld (manche Notizenmaster haben keins), Notiz in PowerPoint anlegen")
        return alt
    felder.sort(key=lambda el: platzhalter(el) is None or platzhalter(el).get("type") != "body")
    absaetze_setzen(felder[0].find(q("p:txBody")), neu.split("\n") if neu else [])
    for el in felder[1:]:
        absaetze_setzen(el.find(q("p:txBody")), [])
    return alt


def inhalt(e: dict, prs, folien: dict, liste: str) -> tuple:
    """Eine Inhaltsänderung anwenden. Liefert (Protokollzeile, geänderte Foliennummern)."""
    art, nr = e["art"], e.get("folie")
    if art not in SICHTBAR | {"notizen", "skript"}:
        raise Fehler(f"unbekannte Art {art!r}")
    if nr is not None and nr not in folien:
        raise Fehler(f"Folie {nr} gibt es nicht")
    slide = folien.get(nr)
    wo = f"Folie {nr}" + (f", Form {e['form']}" if "form" in e else "")
    if art == "skript":
        pfad = os.path.join(os.path.dirname(liste), os.path.expanduser(e["datei"]))
        vorher = {n: etree.tostring(s._element) for n, s in folien.items() if isinstance(n, int)}
        nummern = set(runpy.run_path(pfad)["umbau"](prs) or [])
        nummern |= {n for n, xml in vorher.items() if etree.tostring(folien[n]._element) != xml}
        return f"Skript {os.path.basename(pfad)}: Folien {', '.join(map(str, sorted(nummern))) or 'unbekannt'}", nummern
    if art == "text":
        if not e["alt"]:
            raise Fehler("alt ist leer")

        def ziel(n):  # ohne folie zählen nur die Folien, auf denen die Form steht
            if "form" not in e:
                return [folien[n].shapes._spTree]
            try:
                return formen(folien[n], e["form"])
            except Fehler:
                if nr is not None:
                    raise
                return []
        ziele = {n: ziel(n) for n in ([nr] if nr is not None else folien)}
        treffer = {n: zaehlen(w, e["alt"]) for n, w in ziele.items()}
        summe = sum(treffer.values())
        if not summe:
            raise Fehler(f"Text nicht gefunden: {e['alt']!r}")
        if summe > 1 and not e.get("alle"):
            raise Fehler(f"Text {summe}-mal gefunden: {e['alt']!r}, form angeben oder alle: true")
        for w in ziele.values():
            for p in [p for x in w for p in x.iter(q("a:p"))]:
                ersetzen(p, e["alt"], e["neu"])
        n_wo = wo if nr is not None else "Folien " + ", ".join(str(n) for n, t in treffer.items() if t)
        return f"{n_wo} Text: {e['alt']!r} -> {e['neu']!r} ({summe}-mal)", {n for n, t in treffer.items() if t}
    if slide is None:
        raise Fehler("folie fehlt")
    if art == "notizen":
        alt = notizen_setzen(slide, e["neu"])
        return f"{wo} Notizen: {kurz(alt, False, 120)!r} -> " + (f"{kurz(e['neu'], False, 120)!r}" if e["neu"] else
                                                                   "geleert"), set()
    if art == "in_form":
        return f"{wo} " + in_form(slide, e), {nr}
    els = formen(slide, e["form"])
    if art == "absaetze":
        tbs = [el.find(q("p:txBody")) for el in els if el.find(q("p:txBody")) is not None]
        if not tbs:
            raise Fehler("Form hat keinen Text")
        alt = [absaetze_setzen(tb, e["absaetze"]) for tb in tbs][0]
        neu = " / ".join(a if isinstance(a, str) else a.get("text", "") for a in e["absaetze"])
        return f"{wo} Absätze: {kurz(alt, False, 120)!r} -> {kurz(neu, False, 120)!r}", {nr}
    if art == "zelle":
        alt = None
        for el in els:
            zeilen = el.findall(f".//{q('a:tbl')}/{q('a:tr')}")
            if not zeilen:
                raise Fehler("Form ist keine Tabelle")
            try:
                tc = zeilen[e["zeile"] - 1].findall(q("a:tc"))[e["spalte"] - 1]
            except IndexError:
                raise Fehler(f"Zelle {e['zeile']}/{e['spalte']} gibt es nicht") from None
            alt = absaetze_setzen(tc.find(q("a:txBody")), e["neu"].split("\n"))
        return f"{wo} Zelle {e['zeile']}/{e['spalte']}: {kurz(alt, False, 80)!r} -> {kurz(e['neu'], False, 80)!r}", {nr}
    if art == "lage":
        return f"{wo} Lage: " + [lage(el, e, slide) for el in els][0], {nr}
    for el in els:  # farbe
        if e.get("fuellung"):
            fuellung(el, e["fuellung"])
        if e.get("schrift"):
            schriftfarbe(el, e["schrift"])
    return f"{wo} Farbe: " + ", ".join(f"{k} {e[k]}" for k in ("fuellung", "schrift") if e.get(k)), {nr}


# ---------- Struktur ----------
def abschnittsliste(prs, anlegen: bool):
    pres = prs.part._element
    lst = pres.find(f"{q('p:extLst')}/{q('p:ext')}[@uri='{ABSCHNITTE_URI}']/{q('p14:sectionLst')}")
    if lst is not None or not anlegen:
        return lst
    ext_lst = pres.find(q("p:extLst"))
    if ext_lst is None:
        ext_lst = etree.SubElement(pres, q("p:extLst"))
    ext = etree.SubElement(ext_lst, q("p:ext"), uri=ABSCHNITTE_URI)
    lst = etree.SubElement(ext, q("p14:sectionLst"), nsmap={"p14": NS["p14"]})
    abschnitt(lst, "Standardabschnitt", [s.get("id") for s in prs.slides._sldIdLst])
    return lst


def abschnitt(lst, name: str, ids=()):
    s = etree.SubElement(lst, q("p14:section"), name=name, id="{%s}" % str(uuid.uuid4()).upper())
    ids_el = etree.SubElement(s, q("p14:sldIdLst"))
    for i in ids:
        etree.SubElement(ids_el, q("p14:sldId"), id=i)
    return s


def aus_abschnitt(lst, sid):
    for x in [x for x in lst.iter(q("p14:sldId")) if x.get("id") == sid.get("id")]:
        x.getparent().remove(x)


def ordnen(prs, lst):
    """Reihenfolge der Folien nach den Abschnitten (append verschiebt ein vorhandenes Element ans Ende)."""
    sids = {s.get("id"): s for s in prs.slides._sldIdLst}
    for x in lst.iter(q("p14:sldId")):
        if x.get("id") in sids:
            prs.slides._sldIdLst.append(sids[x.get("id")])


def platzieren(prs, sid, nach_sid):
    """Folie hinter nach_sid (None: an den Anfang), mit Abschnitten im Abschnitt von nach_sid."""
    lst = abschnittsliste(prs, False)
    if lst is None:
        prs.slides._sldIdLst.remove(sid)
        nach_sid.addnext(sid) if nach_sid is not None else prs.slides._sldIdLst.insert(0, sid)
        return
    aus_abschnitt(lst, sid)
    neu = element("p14:sldId", id=sid.get("id"))
    vor = next((x for x in lst.iter(q("p14:sldId")) if nach_sid is not None and x.get("id") == nach_sid.get("id")), None)
    vor.addnext(neu) if vor is not None else lst.find(f"{q('p14:section')}/{q('p14:sldIdLst')}").insert(0, neu)
    ordnen(prs, lst)


def struktur(prs, e: dict, sld_ids: dict, slide) -> str:
    """backup, verschieben, loeschen über die Nummern der Basis (oder als einer übernommenen Folie)."""
    art, sid, nr = e["art"], sld_ids[e["folie"]], e["folie"]
    if art == "verschieben":
        nach = e["nach"]
        if (nach and nach not in sld_ids) or nach == nr:
            raise Fehler(f"nach {nach} geht nicht")
        platzieren(prs, sid, sld_ids[nach] if nach else None)
        return f"Folie {nr} hinter Folie {nach} verschoben" if nach else f"Folie {nr} an den Anfang"
    lst = abschnittsliste(prs, art == "backup")
    if lst is not None:
        aus_abschnitt(lst, sid)
    if art == "loeschen":
        prs.slides._sldIdLst.remove(sid)
        prs.part.drop_rel(sid.rId)
        return f"Folie {nr} gelöscht"
    slide._element.set("show", "0")
    ziel = next((s for s in lst.findall(q("p14:section")) if (s.get("name") or "").lower() == "backup"), None)
    ziel = ziel if ziel is not None else abschnitt(lst, "Backup")
    etree.SubElement(ziel.find(q("p14:sldIdLst")), q("p14:sldId"), id=sid.get("id"))
    ordnen(prs, lst)
    return f"Folie {nr} ausgeblendet, in Abschnitt Backup"


def uebernahme(prs, e: dict, folien: dict, sld_ids: dict, quellen: dict) -> str:
    """Folie aus quelle (auch dem Original selbst) mit eigenen Kopien aller Teile hinter nach, erreichbar als als."""
    pfad = os.path.expanduser(e["quelle"])
    if pfad not in quellen:
        if not os.path.isfile(pfad):
            raise Fehler(f"Quelle fehlt: {pfad}")
        quellen[pfad] = list(Presentation(pfad).slides)
    nr, nach = e["folie"], e["nach"]
    als = e.get("als") or next(f"neu{i}" for i in range(1, len(folien) + 2) if f"neu{i}" not in folien)
    if not 1 <= nr <= len(quellen[pfad]):
        raise Fehler(f"Folie {nr} gibt es in der Quelle nicht")
    if not isinstance(als, str) or als in folien:
        raise Fehler(f"als {als!r} geht nicht (Text, noch nicht vergeben)")
    if nach and nach not in sld_ids:
        raise Fehler(f"nach {nach} gibt es nicht")
    folie, sid = uebernehmen.kopieren(prs, quellen[pfad][nr - 1], e.get("layout"))
    platzieren(prs, sid, sld_ids[nach] if nach else None)
    folien[als], sld_ids[als] = folie, sid
    return f"Folie {als} aus {os.path.basename(pfad)} (dort Folie {nr}) " + (f"hinter Folie {nach}" if nach else
                                                                             "an den Anfang")


def aufraeumen(prs):
    """Änderungsverlauf weg (verweist sonst auf gelöschte Folien und trägt Namen der Bearbeiter), Zähler in app.xml
    neu, Titelliste weg (PowerPoint schreibt beides beim Speichern neu)."""
    for rid, rel in list(prs.part.rels.items()):
        if rel.reltype.endswith("/changesInfo"):
            prs.part.drop_rel(rid)
    try:
        app = prs.part.package.part_related_by(RT.EXTENDED_PROPERTIES)
    except KeyError:
        return
    wurzel = etree.fromstring(app.blob)
    ns = wurzel.nsmap.get(None, "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties")
    werte = {"Slides": len(prs.slides), "Notes": sum(s.has_notes_slide for s in prs.slides),
             "HiddenSlides": sum(s._element.get("show") == "0" for s in prs.slides)}
    for k, v in werte.items():
        if wurzel.find(f"{{{ns}}}{k}") is not None:
            wurzel.find(f"{{{ns}}}{k}").text = str(v)
    for k in ("HeadingPairs", "TitlesOfParts"):
        for x in wurzel.findall(f"{{{ns}}}{k}"):
            wurzel.remove(x)
    app._blob = etree.tostring(wurzel, xml_declaration=True, encoding="UTF-8", standalone=True)


def vergleich(basis: str, paare: list, neue: list, arbeitskopie: str, ziel: str):
    """Deck mit den geänderten Folien als Paare vorher und nachher, dahinter die übernommenen Folien, ausgeblendete
    eingeblendet und beschriftet. Nachher-Folien und neue kommen aus der gespeicherten Arbeitskopie mit eigenen Kopien
    aller Teile, so fehlen auch eingefügte Bilder nicht."""
    prs = Presentation(basis)
    vorher = dict(enumerate(prs.slides, 1))
    res = Presentation(arbeitskopie)
    nach_id = {sid.get("id"): s for sid, s in zip(res.slides._sldIdLst, res.slides)}
    seiten = []
    for n, i in paare:
        seiten += [(vorher[n], f"Folie {n} vorher"), (uebernehmen.kopieren(prs, nach_id[i])[0], f"Folie {n} nachher")]
    seiten += [(uebernehmen.kopieren(prs, nach_id[i])[0], f"Folie {als} neu") for als, i in neue]
    behalten = {id(s._element) for s, _t in seiten}
    lst = prs.slides._sldIdLst
    sids = {id(s._element): sid for s, sid in zip(prs.slides, list(lst))}
    for el_id, sid in sids.items():
        lst.remove(sid)
        if el_id not in behalten:
            prs.part.drop_rel(sid.rId)
    for s, text in seiten:
        lst.append(sids[id(s._element)])
        s._element.attrib.pop("show", None)
        box = s.shapes.add_textbox(Cm(0.3), Cm(0.2), Cm(6.5), Cm(0.9))
        box.fill.solid()
        box.fill.fore_color.rgb = RGBColor(0xFF, 0xF2, 0x00)
        box.text_frame.text = text
        box.text_frame.paragraphs[0].runs[0].font.size = Pt(14)
        box.text_frame.paragraphs[0].runs[0].font.bold = True
    ext = prs.part._element.find(f"{q('p:extLst')}/{q('p:ext')}[@uri='{ABSCHNITTE_URI}']")
    if ext is not None:
        ext.getparent().remove(ext)
    aufraeumen(prs)
    prs.save(ziel)


def pruefseiten(prs, ids: set) -> list:
    """Seiten im PDF der Arbeitskopie (nur eingeblendete Folien) für die Folien mit diesen sldId-Werten."""
    sichtbar = [sid.get("id") for sid, s in zip(prs.slides._sldIdLst, prs.slides) if s._element.get("show") != "0"]
    return [k for k, i in enumerate(sichtbar, 1) if i in ids]


# ---------- Ablauf ----------
def aufruf(argv: list):
    """(original, ziel, zustand, vergleich, ueberschreiben, liste) oder None bei falschem Aufruf."""
    mit_vergleich, ueberschreiben = "--vergleich" in argv, "--ueberschreiben" in argv
    rest, werte = [a for a in argv if a not in ("--vergleich", "--ueberschreiben")], {}
    for name in ("--original", "--ziel", "--zustand"):
        if name in rest:
            i = rest.index(name)
            if i + 1 >= len(rest):
                return None
            werte[name] = rest[i + 1]
            del rest[i:i + 2]
    if len(rest) != 1 or not rest[0].endswith(".json") or len(werte) != 3:
        return None
    return (werte["--original"], werte["--ziel"], werte["--zustand"], mit_vergleich, ueberschreiben,
            os.path.abspath(rest[0]))


def anwenden(prs, eintraege: list, liste: str) -> tuple:
    """Alle Einträge auf prs. (Protokoll, Fehler, sichtbar geänderte Nummern, folien, sld_ids)."""
    folien = dict(enumerate(prs.slides, 1))
    sld_ids = dict(enumerate(prs.slides._sldIdLst, 1))
    protokoll, fehler, sichtbar, quellen = [], [], set(), {}
    phase = lambda ke: 0 if ke[1].get("art") in VORWEG else 2 if ke[1].get("art") in STRUKTUR else 1  # noqa: E731
    for k, e in sorted(enumerate(eintraege, 1), key=phase):
        try:
            if e.get("art") == "reparieren":
                protokoll.append(reparieren(prs))
            elif e.get("art") == "uebernehmen":
                protokoll.append(uebernahme(prs, e, folien, sld_ids, quellen))
            elif e.get("art") in STRUKTUR:
                if e.get("folie") not in folien:
                    raise Fehler(f"Folie {e.get('folie')} gibt es nicht")
                protokoll.append(struktur(prs, e, sld_ids, folien[e["folie"]]))
            else:
                zeile, nummern = inhalt(e, prs, folien, liste)
                protokoll.append(zeile)
                sichtbar |= nummern if e.get("art") in SICHTBAR | {"skript"} else set()
        except Fehler as x:
            fehler.append(f"Eintrag {k} ({e.get('art')}): {x}")
        except (KeyError, TypeError, ValueError) as x:
            fehler.append(f"Eintrag {k} ({e.get('art')}): Angabe fehlt oder falsch ({x})")
    return protokoll, fehler, sichtbar, folien, sld_ids


def main() -> int:
    teile = aufruf(sys.argv[1:])
    if teile is None:
        print(__doc__.split("\n\n")[2], file=sys.stderr)
        return 2
    original, ziel, zustand_ordner, mit_vergleich, ueberschreiben, liste = teile
    try:
        with open(liste, encoding="utf-8") as f:
            daten = json.load(f)
        eintraege = daten["aenderungen"]
        if not isinstance(eintraege, list) or not all(isinstance(e, dict) for e in eintraege):
            raise ValueError("aenderungen als Liste von Objekten")
        for pfad, was in ((original, "Original"), (ziel, "Arbeitskopie")):
            if not os.path.isabs(pfad) or not os.path.isfile(pfad):
                raise Fehler(f"{was} fehlt: {pfad}")
        if not ziel.lower().endswith(".pptx"):
            raise ValueError("die Arbeitskopie ist keine .pptx")
    except (OSError, ValueError, KeyError, TypeError, Fehler) as fehler:
        print(f"Liste {os.path.basename(liste)}: {fehler}", file=sys.stderr)
        return 2
    try:
        runde = stand.Runde(ziel, zustand_ordner, original)
    except stand.Halt as x:
        print(f"HALT  {x}", file=sys.stderr)
        return 1
    try:
        return runde_ausfuehren(runde, original, ziel, eintraege, liste, mit_vergleich, ueberschreiben)
    finally:
        runde.aufraeumen()


UPDATE_HALT = ("Erste Runde nach dem Update: folien_aendern wendet die Liste jetzt auf den aktuellen Stand der "
               "Arbeitskopie an, nicht mehr auf das Original. Nichts geschrieben. Mit folien_lesen die Arbeitskopie "
               "lesen, dann nur die neuen Wünsche mit den Foliennummern von jetzt schicken. Frühere Einträge stecken "
               "schon in der Datei, erneut angewendet träfen verschieben, backup, loeschen und uebernehmen andere "
               "Folien.")


def runde_ausfuehren(runde, original: str, ziel: str, eintraege: list, liste: str, mit_vergleich: bool,
                     ueberschreiben: bool) -> int:
    if runde.nach_update and any(e.get("art") in STRUKTUR | {"uebernehmen"} for e in eintraege):
        runde.merken()  # einmalig: die nächste Liste läuft
        print(f"HALT  {UPDATE_HALT}", file=sys.stderr)
        return 1
    for zeile in runde.meldung_hand():
        print(zeile)
    if runde.hand:
        print()
    prs = Presentation(runde.arbeit)
    protokoll, fehler, sichtbar, folien, sld_ids = anwenden(prs, eintraege, liste)
    for zeile in protokoll:
        print(zeile)
    if fehler:
        runde.merken()
        print("\nNICHTS geschrieben, erst beheben:\n" + "\n".join(fehler), file=sys.stderr)
        return 1
    aufraeumen(prs)
    prs.save(runde.arbeit)
    erlaubt = {"Deck!*#schriften"} if any(e.get("art") == "reparieren" for e in eintraege) else set()
    try:
        code, zeilen = runde.abschliessen(ueberschreiben, erlaubt)
    except stand.Halt as x:
        print(f"HALT  {x}", file=sys.stderr)
        return 1
    print("\n" + "\n".join(zeilen), file=sys.stderr if code else sys.stdout)
    if code:
        return code
    paare = sorted((n, sld_ids[n].get("id")) for n in sichtbar
                   if isinstance(n, int) and n in folien and sld_ids[n].getparent() is not None)
    neue = [(als, sid.get("id")) for als, sid in sld_ids.items() if isinstance(als, str) and sid.getparent() is not None]
    vergleich_pfad = os.path.join(os.path.dirname(ziel), os.path.splitext(os.path.basename(ziel))[0] + VERGLEICH)
    if mit_vergleich and (paare or neue):
        vergleich(runde.davor, paare, neue, ziel, vergleich_pfad)
    zahl = len(prs.slides)
    print(f"\nArbeitskopie: {ziel} ({zahl} Folie{'' if zahl == 1 else 'n'}, Original unverändert)")
    seiten = pruefseiten(prs, {i for _n, i in paare} | {i for _a, i in neue})
    print("Prüfseiten im PDF der Arbeitskopie: " + (", ".join(map(str, seiten)) if seiten else "keine (nichts Sichtbares)"))
    if mit_vergleich and (paare or neue):
        print(f"Vergleich: {vergleich_pfad} (" + ", ".join(
            ([f"Folien {', '.join(str(n) for n, _i in paare)} vorher und nachher"] if paare else [])
            + ([f"neu {', '.join(a for a, _i in neue)}"] if neue else [])) + ")")
    print()
    if pruefen.pruefe(ziel, original if os.path.isfile(original) else None):
        print("NICHT übertragen: Funde oben beheben")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
