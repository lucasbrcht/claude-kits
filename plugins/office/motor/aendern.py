"""Änderungsliste (JSON) auf das Original anwenden und die Arbeitskopie in der Ablage neu schreiben. Das Original
bleibt unangetastet: Jeder Lauf liest das Original (oder die Basis) und schreibt die Arbeitskopie neu, die
arbeitskopie holen im Themen-Ordner angelegt hat. Rücknahme einer Änderung: Eintrag streichen, neu anwenden.
Prüfsummen von Original und Arbeitskopie und die Basis stehen im Zustandsordner (Zwischenordner im Datenordner von
office, je Arbeitskopie eine Datei), nie neben der Arbeitskopie.

Basis: Weicht die Arbeitskopie beim ersten Lauf vom Original ab (der Nutzer hat sie schon bearbeitet), ist sie die
Basis. Hat der Nutzer sie nach einem Lauf in PowerPoint gespeichert, wird sie zur Basis: Der Lauf schreibt dann
nichts und meldet das, die Liste enthält danach nur neue Wünsche mit den Foliennummern der Basis. Gleicht die
Arbeitskopie dem Original (übertragen oder frisch geholt), beginnt eine neue Runde. Ist die Arbeitskopie in Office
offen, schreibt der Lauf nichts.

Aufruf (der Server gibt alle Pfade vor):
  python3 -I aendern.py --original <Original> --ziel <Arbeitskopie> --zustand <Ordner> [--vergleich] <liste.json>

Liste: {"aenderungen": [{"art": "...", "folie": <Nummer in der Basis>, ...}]}
Arten (folie und form wie in lesen.py, form auch als Name, Maße in cm):
  text         alt, neu, form und folie optional, alle: true für mehrere Treffer. Format bleibt, auch über Läufe
  absaetze     form, absaetze: ["Text", {"text": "...", "ebene": 1}]. Format des ersten Absatzes
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

Reihenfolge: erst uebernehmen, dann Inhalte, zuletzt backup, verschieben, loeschen. Ergebnis: die Arbeitskopie und die
Seiten der geänderten und neuen Folien im PDF (ausgeblendete fehlen dort). Mit --vergleich zusätzlich
<Stamm> Vergleich.pptx im Themen-Ordner mit den Paaren vorher und nachher und den neuen Folien. Jeder Lauf entfernt
den Änderungsverlauf (changesInfo mit Namen der Bearbeiter) und setzt die Zähler in docProps/app.xml neu. Danach
prüft er die Arbeitskopie wie pruefen.py. Rückgabewert 0, 1 bei einem Fehler in einem Eintrag (dann ist nichts
geschrieben), einem Fund der Prüfung, offener oder vom Nutzer gespeicherter Arbeitskopie, 2 bei falschem Aufruf.
"""
import copy
import hashlib
import json
import os
import runpy
import shutil
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
import uebernehmen  # noqa: E402
from gemeinsam import offen_in_office, sha256  # noqa: E402
from lesen import (ABSCHNITTE_URI, EMU_CM, NOTIZ_PLATZHALTER, NS, absatz_text, kurz, notizen,  # noqa: E402
                   platzhalter, q)
from uebernehmen import Fehler  # noqa: E402

SICHTBAR = {"text", "absaetze", "zelle", "lage", "farbe"}  # Arten, die im Vergleich als Paar erscheinen
STRUKTUR = {"backup", "verschieben", "loeschen"}  # wirken nach allen Inhalten, Nummern bleiben die der Basis
FUELLUNGEN = ("a:solidFill", "a:noFill", "a:gradFill", "a:pattFill", "a:blipFill", "a:grpFill")
VERGLEICH = " Vergleich.pptx"


class Halt(Exception):
    """Lauf endet ohne zu schreiben, Rückgabewert 1 (offene oder vom Nutzer gespeicherte Arbeitskopie)."""


# ---------- Zustand ----------
class Zustand:
    """Prüfsummen und Basis zu einer Arbeitskopie im Zustandsordner, Name aus der Prüfsumme ihres Pfads."""

    def __init__(self, ordner: str, ziel: str):
        schluessel = hashlib.sha256(os.path.realpath(ziel).encode("utf-8")).hexdigest()[:16]
        self.json = os.path.join(ordner, schluessel + ".json")
        self.basis = os.path.join(ordner, schluessel + ".basis.pptx")
        self.ordner = ordner

    def lesen(self) -> dict:
        try:
            with open(self.json, encoding="utf-8") as f:
                daten = json.load(f)
            return daten if isinstance(daten, dict) else {}
        except (OSError, ValueError):
            return {}

    def schreiben(self, daten: dict):
        os.makedirs(self.ordner, exist_ok=True)
        tmp = self.json + ".neu"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(daten, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.json)

    def basis_aus(self, ziel: str):
        os.makedirs(self.ordner, exist_ok=True)
        shutil.copyfile(ziel, self.basis)

    def vergessen(self):
        for pfad in (self.json, self.basis):
            if os.path.isfile(pfad):
                os.remove(pfad)


def basis_holen(original: str, ziel: str, z: Zustand) -> tuple:
    """(Basis, Zustand) für diesen Lauf. Basis ist das Original oder eine Fassung der Arbeitskopie vom Nutzer."""
    if offen_in_office(ziel):
        raise Halt(f"{os.path.basename(ziel)} ist in PowerPoint offen. Den Nutzer bitten, das Fenster zu schließen "
                   "(Speichern macht die Arbeitskopie zur neuen Basis), dann erneut anwenden. Nichts geschrieben.")
    zustand = z.lesen()
    sha_o, sha_k = sha256(original), sha256(ziel)
    if zustand.get("original") != original or not zustand.get("arbeitskopie"):
        if sha_k != sha_o:  # erster Lauf, die Arbeitskopie hat schon Änderungen (oder das Original änderte sich)
            z.basis_aus(ziel)
            print("HINWEIS  Arbeitskopie weicht vom Original ab, sie ist die Basis dieser Runde")
            return z.basis, {"original": original, "sha": sha_o, "basis": z.basis}
        return original, {"original": original, "sha": sha_o}
    if sha_k == sha_o and zustand.get("sha") != sha_o:  # übertragen (Original neu) oder frisch geholt (Kopie neu)
        z.vergessen()
        raise Halt("Arbeitskopie gleicht dem Original (übertragen oder frisch geholt), eine neue Runde beginnt. "
                   "Nichts geschrieben. Liste nur mit den neuen Wünschen anlegen, Foliennummern wie folien_lesen "
                   "auf der Arbeitskopie, dann erneut anwenden.")
    if sha_k != zustand["arbeitskopie"]:
        if zustand.get("sha") != sha_o:
            raise Halt("Original und Arbeitskopie sind beide seit dem letzten Lauf geändert. Mit dem Nutzer klären, "
                       "welcher Stand gilt. Nichts geschrieben.")
        z.basis_aus(ziel)
        zustand.update(basis=z.basis, arbeitskopie=sha_k)
        z.schreiben(zustand)
        raise Halt("Arbeitskopie vom Nutzer gespeichert, sie ist ab jetzt die Basis. Nichts geschrieben. Liste nur mit "
                   "den neuen Wünschen anlegen, Foliennummern wie folien_lesen auf der Arbeitskopie, dann erneut "
                   "anwenden.")
    if zustand.get("basis") and os.path.isfile(zustand["basis"]):
        if zustand.get("sha") != sha_o:
            raise Halt("Original seit dem letzten Lauf geändert, Basis ist aber die gespeicherte Fassung des Nutzers. "
                       "Mit dem Nutzer klären, welcher Stand gilt. Nichts geschrieben.")
        return zustand["basis"], zustand
    if zustand.get("sha") != sha_o:
        print("HINWEIS  Original seit dem letzten Lauf geändert, Liste wird auf den neuen Stand angewendet. "
              "Übertragen bricht ab, bis die Arbeitskopie frisch geholt ist")
    return original, {"original": original, "sha": sha_o}


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
        if text:
            r = etree.SubElement(p, q("a:r"))
            if rpr is not None:
                r.append(copy.deepcopy(rpr))
            etree.SubElement(r, q("a:t")).text = text
        if end is not None:
            p.append(copy.deepcopy(end))
    return alt


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
    """(original, ziel, zustand, vergleich, liste) oder None bei falschem Aufruf."""
    mit_vergleich = "--vergleich" in argv
    rest, werte = [a for a in argv if a != "--vergleich"], {}
    for name in ("--original", "--ziel", "--zustand"):
        if name in rest:
            i = rest.index(name)
            if i + 1 >= len(rest):
                return None
            werte[name] = rest[i + 1]
            del rest[i:i + 2]
    if len(rest) != 1 or not rest[0].endswith(".json") or len(werte) != 3:
        return None
    return werte["--original"], werte["--ziel"], werte["--zustand"], mit_vergleich, os.path.abspath(rest[0])


def main() -> int:
    teile = aufruf(sys.argv[1:])
    if teile is None:
        print(__doc__.split("\n\n")[2], file=sys.stderr)
        return 2
    original, ziel, zustand_ordner, mit_vergleich, liste = teile
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
    z = Zustand(zustand_ordner, ziel)
    try:
        basis, zustand = basis_holen(original, ziel, z)
    except Halt as x:
        print(f"HALT  {x}", file=sys.stderr)
        return 1
    prs = Presentation(basis)
    folien = dict(enumerate(prs.slides, 1))
    sld_ids = dict(enumerate(prs.slides._sldIdLst, 1))
    protokoll, fehler, sichtbar, quellen = [], [], set(), {}
    phase = lambda ke: 0 if ke[1].get("art") == "uebernehmen" else 2 if ke[1].get("art") in STRUKTUR else 1  # noqa: E731
    for k, e in sorted(enumerate(eintraege, 1), key=phase):
        try:
            if e.get("art") == "uebernehmen":
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
    for zeile in protokoll:
        print(zeile)
    if fehler:
        print("\nNICHTS geschrieben, erst beheben:\n" + "\n".join(fehler), file=sys.stderr)
        return 1
    aufraeumen(prs)
    prs.save(ziel)
    paare = sorted((n, sld_ids[n].get("id")) for n in sichtbar
                   if isinstance(n, int) and n in folien and sld_ids[n].getparent() is not None)
    neue = [(als, sid.get("id")) for als, sid in sld_ids.items() if isinstance(als, str) and sid.getparent() is not None]
    vergleich_pfad = os.path.join(os.path.dirname(ziel), os.path.splitext(os.path.basename(ziel))[0] + VERGLEICH)
    if mit_vergleich and (paare or neue):
        vergleich(basis, paare, neue, ziel, vergleich_pfad)
    zustand["arbeitskopie"] = sha256(ziel)
    z.schreiben(zustand)
    print(f"\nArbeitskopie: {ziel} ({len(prs.slides)} Folien, Original unverändert"
          + (", Basis ist die Fassung des Nutzers" if basis != original else "") + ")")
    seiten = pruefseiten(prs, {i for _n, i in paare} | {i for _a, i in neue})
    print("Prüfseiten im PDF der Arbeitskopie: " + (", ".join(map(str, seiten)) if seiten else "keine (nichts Sichtbares)"))
    if mit_vergleich and (paare or neue):
        print(f"Vergleich: {vergleich_pfad} (" + ", ".join(
            ([f"Folien {', '.join(str(n) for n, _i in paare)} vorher und nachher"] if paare else [])
            + ([f"neu {', '.join(a for a, _i in neue)}"] if neue else [])) + ")")
    print()
    if pruefen.pruefe(ziel, basis):
        print("NICHT übertragen: Funde oben beheben")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
