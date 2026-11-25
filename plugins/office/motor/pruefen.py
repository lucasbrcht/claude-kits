"""PowerPoint-Fallen, die eine XSD-Prüfung nicht meldet, danach auf Wunsch die XSD-Prüfung mit validate.py aus dem
Skill pptx von Anthropic. Den Pfad reicht der Server als KITS_PPTX_VALIDATE weiter (motor.pptx_validate in der
config.json von office, leer sucht der Server den Skill am Mac selbst). Ohne den Pfad fehlt nur die XSD-Prüfung.

Aufruf: python3 -I pruefen.py <datei.pptx> [--original <draft.pptx>] [--ohne-xsd]

Prüft in dieser Reihenfolge, woran PowerPoint beim Öffnen scheitert: Zip lesbar, jedes XML-Teil wohlgeformt, jedes
Teil mit Inhaltstyp in [Content_Types].xml, jeder Verweis (r:id, r:embed, r:link, r:pict und alle anderen Attribute im
Namensraum der Beziehungen) in allen XML-Teilen mit Eintrag in der .rels des Teils, leere Verweise dort, wo PowerPoint
ein Ziel braucht (ZIEL_NOETIG, anderswo erlaubt sie der Standard), jede interne Beziehung mit vorhandenem Ziel,
eingebettete Schriften (p:embeddedFontLst) mit Dateien unter ppt/fonts/.
Einträge unter [trash]/ legt PowerPoint für Mac selbst an, sie sind harmlos und zählen nie.
Dazu Markierungen von Add-ins (p:custDataLst), die sich mehrere Formen teilen, Teile (Markierungen, Diagramme,
SmartArt), auf die mehrere Folien zeigen, mehrere Füllungen in einem Element und Altlasten aus Referenzdecks: einen
Änderungsverlauf (changesInfo mit Namen der Bearbeiter) und Zähler in docProps/app.xml, die nicht zum Deck passen.
Formen in mc:AlternateContent (Choice und Fallback beschreiben dieselbe Form) zählen einmal. Mit --original zählen
Funde, die schon im Original stecken, nicht als Fehler.
Dazu Hinweise zur Gestaltung je Folie als WARNUNG, die nicht als Fund zählen: getippte Aufzählungszeichen (zweite Zeile
ohne Einzug, gemischtes Fett), Schrift unter SCHRIFT_MIN, Formen über den Folienrand und Textfelder auf einer Form ohne
eigenen Text (Text gehört in die Form, sonst trennt Verschieben beides). Hinweise aus dem Original fallen weg.
Rückgabewert 0 ohne Fund, 1 mit Fund, 2 bei falschem Aufruf. Nur Standardbibliothek, läuft auch unter python3 (3.9).
"""
import os
import posixpath
import re
import subprocess
import sys
import zipfile
from urllib.parse import unquote

try:
    from defusedxml.ElementTree import ParseError, fromstring
except ImportError:  # ohne defusedxml: expat löst keine externen Entitäten auf
    from xml.etree.ElementTree import ParseError, fromstring

sys.dont_write_bytecode = True

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
R_STRIKT = "http://purl.oclc.org/ooxml/officeDocument/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
APP = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
VALIDATE = "KITS_PPTX_VALIDATE"
TRASH = "[trash]/"  # legt PowerPoint für Mac selbst an, ohne Inhaltstyp, harmlos
# Je Folie eine eigene Kopie nötig. Eingebettete Objekte teilt PowerPoint selbst, oft eins auf vielen Folien
GETEILT = ("ppt/tags/", "ppt/charts/", "ppt/diagrams/")
SCHRIFT_ARTEN = ("regular", "bold", "italic", "boldItalic")
# Leere Verweise erlaubt der Standard an vielen Stellen (Aktions-Links, SmartArt-Layouts, Bilder ohne Inhalt). Ein
# Fehler sind sie nur dort, wo PowerPoint ein Ziel braucht. Eine unbekannte Id ist überall ein Fehler.
ZIEL_NOETIG = {"sldId", "sldMasterId", "notesMasterId", "handoutMasterId", "sldLayoutId", "tags", "chart", "oleObj",
               "relIds", "externalData", "control", "contentPart", "custData"}
SCHRIFT_HINWEIS = "Eingebettete Schriften fehlen, PowerPoint kann die Datei nicht öffnen"
LISTE_MAX = 6

ABHILFE = {
    "zip": "Keine lesbare PowerPoint-Datei (beschädigt, altes Format oder nur in der Cloud). Bei einer "
           "Arbeitskopie mit arbeitskopie holen und neu frisch holen",
    "xml": "PowerPoint kann die Datei so nicht öffnen. Das Teil stammt aus der letzten Änderung, sie zurücknehmen",
    "inhaltstyp": "PowerPoint meldet ein Problem mit dem Inhalt. Eintrag in [Content_Types].xml fehlt",
    "verweis": "PowerPoint meldet ein Problem mit dem Inhalt oder kann die Datei nicht reparieren. Das Element "
               "verweist auf keine Beziehung des Teils",
    "ziel-fehlt": "PowerPoint meldet ein Problem mit dem Inhalt. Die Beziehung zeigt auf ein Teil, das fehlt",
    "schriften": "Behebung: folien_aendern mit {\"art\": \"reparieren\"} entfernt die Liste und embedTrueTypeFonts. "
                 "Der Nutzer schaltet in PowerPoint für dieses Deck Schriftarten in die Datei einbetten aus "
                 "(Einstellungen > Speichern), sonst schreibt PowerPoint die leere Liste beim nächsten Speichern neu",
    "tag-mehrfach": "PowerPoint öffnet die Datei dann nicht. Formen nicht mit Markierung kopieren",
    "teil-geteilt": "Änderungen an einer Folie träfen die andere. Folien mit uebernehmen kopieren, nicht mit "
                    "add_slide.py",
    "fuellung-mehrfach": "PowerPoint repariert die Datei beim Öffnen. Nur eine Füllung je Element, farbe in "
                         "folien_aendern ersetzt auch grpFill",
    "aenderungsverlauf": "verweist nach Löschen auf fehlende Folien und trägt Namen der Bearbeiter. folien_aendern "
                         "entfernt ihn",
    "app-zaehler": "Altlast aus einem Referenzdeck. folien_aendern setzt die Zähler neu",
    # Gestaltung: nur WARNUNG, zählt nicht als Fund
    "aufzaehlung-text": "Die zweite Zeile rutscht unter das Zeichen, beim Markieren mischt sich Fett. Echte Aufzählung "
                        "über das Absatzformat: absaetze in folien_aendern mit {\"text\": \"...\", \"punkt\": true} "
                        "und Text ohne Zeichen",
    "schrift-klein": "Auf Folien zum Zeigen schlecht lesbar",
    "ausserhalb": "Sie fehlt dann in der Präsentation oder im Druck teilweise",
    "textfeld-ueber-form": "Verschieben und Bearbeiten trennt Text und Form. Besser Text direkt in der Form: "
                           "folien_aendern mit {\"art\": \"in_form\", \"folie\": N, \"form\": <Textfeld>, \"ziel\": "
                           "<Form>}",
}
GESTALTUNG = {"aufzaehlung-text", "schrift-klein", "ausserhalb", "textfeld-ueber-form"}
SCHRIFT_MIN = 10  # pt, darunter WARNUNG
# getipptes Aufzählungszeichen am Absatzanfang, Striche nur mit Leerzeichen danach
GETIPPT = re.compile("^\\s*(?:[•▪◦‣●■◆►✓·]\\s*|[-–]\\s+)\\S")
LINIEN = {"line", "straightConnector1", "bentConnector2", "bentConnector3", "curvedConnector3"}
SICHTBAR = ("solidFill", "gradFill", "pattFill", "blipFill")


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


def rels_name(teil: str) -> str:
    return posixpath.join(posixpath.dirname(teil), "_rels", posixpath.basename(teil) + ".rels")


def ziel_pfad(teil: str, ziel: str) -> str:
    """Ziel einer internen Beziehung als Paketpfad, ohne Sprungmarke."""
    ziel = ziel.split("#", 1)[0]
    if ziel.startswith("/"):
        return posixpath.normpath(ziel.lstrip("/"))
    return posixpath.normpath(posixpath.join(posixpath.dirname(teil), ziel))


class Paket:
    """Zip einer .pptx ohne [trash]/, XML-Teile werden einmal gelesen. Nicht lesbare Teile landen in defekt."""

    def __init__(self, z: zipfile.ZipFile):
        self.z = z
        self.namen = {n for n in z.namelist() if not n.startswith(TRASH) and not n.endswith("/")}
        self._xml, self._rels, self.defekt = {}, {}, {}

    def xml(self, name: str):
        if name not in self._xml:
            try:
                self._xml[name] = fromstring(self.z.read(name))
            except (ParseError, ValueError, KeyError, zipfile.BadZipFile) as x:
                self._xml[name] = None
                self.defekt[name] = str(x) or type(x).__name__
        return self._xml[name]

    def alle_rels(self, teil: str) -> dict:
        """{rId: (Typ, Ziel, extern)} aller Beziehungen eines Teils, Ziel bei internen als Paketpfad. Ein Ziel NULL
        schreibt PowerPoint für leere Verweise selbst, es zählt wie ein externes."""
        if teil not in self._rels:
            rels, name = {}, rels_name(teil)
            wurzel = self.xml(name) if name in self.namen else None
            for r in (wurzel.iter(q(REL, "Relationship")) if wurzel is not None else ()):
                ziel, extern = r.get("Target") or "", r.get("TargetMode") == "External"
                extern = extern or ziel == "NULL"
                rels[r.get("Id") or ""] = (r.get("Type") or "", ziel if extern else ziel_pfad(teil, ziel), extern)
            self._rels[teil] = rels
        return self._rels[teil]


def lade_rels(paket: Paket, teil: str) -> dict:
    """{rId: (Typ, Ziel als Paketpfad)} der internen Beziehungen eines Teils."""
    return {k: (t, z_) for k, (t, z_, extern) in paket.alle_rels(teil).items() if not extern}


def vorhanden(paket: Paket, pfad: str) -> bool:
    return pfad in paket.namen or unquote(pfad) in paket.namen


def mehr(liste: list) -> str:
    return ", ".join(liste[:LISTE_MAX]) + (f" und {len(liste) - LISTE_MAX} weitere" if len(liste) > LISTE_MAX else "")


def inhaltstypen(paket: Paket) -> list:
    """Teile ohne Inhaltstyp (weder Default nach Endung noch Override nach Name)."""
    if "[Content_Types].xml" not in paket.namen:
        return [fund("inhaltstyp", "[Content_Types].xml", "", 1, "[Content_Types].xml fehlt")]
    ct = paket.xml("[Content_Types].xml")
    if ct is None:
        return []
    endungen = {(d.get("Extension") or "").lower() for d in ct.iter(q(CT, "Default"))}
    namen = {(o.get("PartName") or "").lstrip("/").lower() for o in ct.iter(q(CT, "Override"))}
    def endung(n):  # auch für _rels/.rels, das splitext als Datei ohne Endung liest
        name = posixpath.basename(n)
        return name.rsplit(".", 1)[1].lower() if "." in name else ""
    ohne = sorted(n for n in paket.namen if n != "[Content_Types].xml" and n.lower() not in namen
                  and unquote(n).lower() not in namen and endung(n) not in endungen)
    if not ohne:
        return []
    return [fund("inhaltstyp", "[Content_Types].xml", "", len(ohne), f"{len(ohne)} Teile ohne Inhaltstyp "
                 f"({mehr(ohne)})")]


def kurzname(tag: str) -> str:
    ns, _, lokal = tag[1:].partition("}") if tag.startswith("{") else ("", "", tag)
    praefix = {P: "p", A: "a", R: "r", R_STRIKT: "r", A.replace("/main", "/chart"): "c",
               A.replace("/main", "/diagram"): "dgm"}.get(ns)
    if praefix is None:
        praefix = ns.rstrip("/").rsplit("/", 1)[-1] if ns else ""
    return f"{praefix}:{lokal}" if praefix else lokal


def verweise(paket: Paket) -> list:
    """Je Teil ein Fund für Verweise ohne Beziehung (leer oder unbekannte Id), je .rels ein Fund für interne Ziele,
    die fehlen. Die Liste der eingebetteten Schriften prüft schriften()."""
    funde = []
    for n in sorted(paket.namen):
        if n.endswith(".rels"):
            teil = "" if n == "_rels/.rels" else posixpath.join(posixpath.dirname(posixpath.dirname(n)),
                                                                 posixpath.basename(n)[:-5])
            fehlt = sorted({ziel for _t, ziel, extern in paket.alle_rels(teil).values()
                            if not extern and not vorhanden(paket, ziel)})
            if fehlt:
                funde.append(fund("ziel-fehlt", n, "", len(fehlt), f"{len(fehlt)} Beziehungen zeigen auf fehlende "
                                  f"Teile ({mehr(fehlt)})"))
            continue
        if not n.endswith(".xml") or n == "[Content_Types].xml":
            continue
        wurzel = paket.xml(n)
        if wurzel is None:
            continue
        ids = paket.alle_rels(n)
        schriften_ = {id(e) for lst in wurzel.iter(q(P, "embeddedFontLst")) for e in lst.iter()}
        falsch = []
        for el in wurzel.iter():
            if id(el) in schriften_:
                continue
            for attr, wert in el.attrib.items():
                if not wert and (not isinstance(el.tag, str) or el.tag.rsplit("}", 1)[-1] not in ZIEL_NOETIG):
                    continue
                if attr.startswith(("{%s}" % R, "{%s}" % R_STRIKT)) and wert not in ids:
                    falsch.append(f"{kurzname(el.tag)} {kurzname(attr)}=\"{wert}\" "
                                  + ("leer" if not wert else "unbekannt"))
        if falsch:
            funde.append(fund("verweis", n, "", len(falsch), f"{len(falsch)} Verweise ohne Beziehung "
                              f"({mehr(list(dict.fromkeys(falsch)))})"))
    return funde


def schriften(paket: Paket, pres) -> list:
    """p:embeddedFontLst mit Schriften, aber leeren oder unbekannten Verweisen oder ohne Dateien unter ppt/fonts/.
    PowerPoint schreibt das, wenn es Schriften einbetten soll, die nicht eingebettet werden dürfen."""
    lst = pres.find(q(P, "embeddedFontLst"))
    if lst is None:
        return []
    rels, betroffen, schnitte = paket.alle_rels("ppt/presentation.xml"), [], 0
    for schrift in lst.findall(q(P, "embeddedFont")):
        font = schrift.find(q(P, "font"))
        name = (font.get("typeface") if font is not None else "") or "ohne Namen"
        for art in SCHRIFT_ARTEN:
            el = schrift.find(q(P, art))
            if el is None:
                continue
            schnitte += 1
            ziel = rels.get(el.get(q(R, "id")) or "")
            if ziel is None or ziel[2] or not vorhanden(paket, ziel[1]):
                betroffen.append(name)
    dateien = any(n.startswith("ppt/fonts/") for n in paket.namen)
    if not betroffen and (dateien or not schnitte):
        return []
    namen = list(dict.fromkeys(betroffen)) or ["keine Dateien unter ppt/fonts/"]
    return [fund("schriften", "ppt/presentation.xml", "", 1, f"{SCHRIFT_HINWEIS} ({', '.join(namen)})")]


# ---------- Gestaltung ----------
def lage_von(el):
    """(x, y, b, h) in EMU aus spPr, grpSpPr oder p:xfrm, sonst None."""
    for pfad in (f"{q(P, 'spPr')}/{q(A, 'xfrm')}", f"{q(P, 'grpSpPr')}/{q(A, 'xfrm')}", q(P, "xfrm")):
        x = el.find(pfad)
        if x is not None and x.find(q(A, "off")) is not None and x.find(q(A, "ext")) is not None:
            try:
                return (int(x.find(q(A, "off")).get("x")), int(x.find(q(A, "off")).get("y")),
                        int(x.find(q(A, "ext")).get("cx")), int(x.find(q(A, "ext")).get("cy")))
            except (TypeError, ValueError):
                return None
    return None


def kennung(el) -> str:
    c = el.find("./*/" + q(P, "cNvPr"))
    return f"Form {c.get('id') or '?'} ({c.get('name') or ''})" if c is not None else "Form ?"


def form_nr(el) -> str:
    c = el.find("./*/" + q(P, "cNvPr"))
    return (c.get("id") or "?") if c is not None else "?"


def text_von(el) -> str:
    return "".join(t.text or "" for t in el.iter(q(A, "t")))


def textfeld(sp) -> bool:
    """Textfeld: als solches angelegt oder ohne sichtbare Füllung und Linie."""
    c = sp.find(f"{q(P, 'nvSpPr')}/{q(P, 'cNvSpPr')}")
    if c is not None and c.get("txBox") == "1":
        return True
    sppr = sp.find(q(P, "spPr"))
    return sppr is not None and sp.find(q(P, "style")) is None and not any(sppr.find(q(A, f)) is not None
                                                                          for f in SICHTBAR + ("ln",))


def flaeche(sp) -> bool:
    """Sichtbare Form ohne eigenen Text: Geometrie (keine Linie) mit Füllung oder Linie, auch aus dem Stil."""
    sppr = sp.find(q(P, "spPr"))
    if sppr is None or text_von(sp).strip() or textfeld(sp):
        return False
    geo = sppr.find(q(A, "prstGeom"))
    if geo is not None and geo.get("prst") in LINIEN:
        return False
    if geo is None and sppr.find(q(A, "custGeom")) is None:
        return False
    if any(sppr.find(q(A, f)) is not None for f in SICHTBAR):
        return True
    fill = sp.find(f"{q(P, 'style')}/{q(A, 'fillRef')}")
    return sppr.find(q(A, "noFill")) is None and fill is not None and fill.get("idx") not in (None, "0")


def ueberdeckt(innen, aussen) -> float:
    """Anteil der Fläche von innen, der in aussen liegt."""
    x1, y1 = max(innen[0], aussen[0]), max(innen[1], aussen[1])
    x2, y2 = min(innen[0] + innen[2], aussen[0] + aussen[2]), min(innen[1] + innen[3], aussen[1] + aussen[3])
    if x2 <= x1 or y2 <= y1 or innen[2] <= 0 or innen[3] <= 0:
        return 0.0
    return (x2 - x1) * (y2 - y1) / (innen[2] * innen[3])


def gestaltung(teil: str, nr: int, root, groesse) -> list:
    """Hinweise zur Gestaltung einer Folie: getippte Aufzählungszeichen, zu kleine Schrift, Formen über den Rand,
    Textfelder auf Formen ohne eigenen Text."""
    funde, wo = [], f"Folie {nr}"
    for el in list(root.iter(q(P, "sp"))) + list(root.iter(q(P, "graphicFrame"))):
        getippt = sum(1 for p in el.iter(q(A, "p")) if GETIPPT.match(text_von(p)))
        if getippt:
            funde.append(fund("aufzaehlung-text", teil, form_nr(el), getippt,
                              f"{wo}, {kennung(el)}: {getippt} Absätze mit getipptem Aufzählungszeichen"))
        groessen = [int(r.find(q(A, "rPr")).get("sz")) for r in el.iter(q(A, "r"))
                    if (r.findtext(q(A, "t")) or "").strip() and r.find(q(A, "rPr")) is not None
                    and (r.find(q(A, "rPr")).get("sz") or "").isdigit()]
        if groessen and min(groessen) < SCHRIFT_MIN * 100:
            pt = f"{min(groessen) / 100:g}".replace(".", ",")
            funde.append(fund("schrift-klein", teil, form_nr(el), 1,
                              f"{wo}, {kennung(el)}: Schrift {pt} pt, unter {SCHRIFT_MIN} pt"))
    baum = root.find(f"{q(P, 'cSld')}/{q(P, 'spTree')}")
    if baum is None:
        return funde
    formen = (q(P, "sp"), q(P, "pic"), q(P, "graphicFrame"), q(P, "grpSp"), q(P, "cxnSp"))
    if groesse:
        rand_b, rand_h = groesse[0] * 1.005, groesse[1] * 1.005
        for el in (k for k in baum if k.tag in formen):
            lage = lage_von(el)
            if lage and (lage[0] < 0 or lage[1] < 0 or lage[0] + lage[2] > rand_b or lage[1] + lage[3] > rand_h):
                funde.append(fund("ausserhalb", teil, form_nr(el), 1, f"{wo}, {kennung(el)} ragt über den Folienrand"))
    for behaelter in [baum] + list(baum.iter(q(P, "grpSp"))):  # Lagen gelten je Ebene
        kinder = [k for k in behaelter if k.tag == q(P, "sp")]
        for i, t in enumerate(kinder):
            lage_t = lage_von(t)
            if lage_t is None or not text_von(t).strip() or not textfeld(t):
                continue
            unter_t = [(s, lage_von(s)) for s in kinder[:i] if flaeche(s) and lage_von(s)]
            treffer = [(s, l_s) for s, l_s in unter_t if ueberdeckt(lage_t, l_s) >= 0.8]
            if treffer:
                s, _l = min(treffer, key=lambda x: x[1][2] * x[1][3])
                funde.append(fund("textfeld-ueber-form", teil, form_nr(t), 1,
                                  f"{wo}: Textfeld{kennung(t)[4:]} liegt auf {kennung(s)} ohne eigenen Text"))
    return funde


def analyse(pfad: str):
    """(Info-Zeilen, Funde) einer .pptx. Funde der Gestaltung (GESTALTUNG) sind nur Hinweise."""
    funde, nutzer = [], {}
    try:
        z = zipfile.ZipFile(pfad)
    except (zipfile.BadZipFile, OSError) as x:
        return ["Datei nicht lesbar"], [fund("zip", os.path.basename(pfad), "", 1, f"keine Zip-Datei ({x})")]
    with z:
        paket = Paket(z)
        try:
            defekt = z.testzip()
        except (zipfile.BadZipFile, OSError, RuntimeError, EOFError) as x:
            defekt = str(x)
        if defekt:
            return ["Datei nicht lesbar"], [fund("zip", os.path.basename(pfad), "", 1, f"Zip-Teil defekt: {defekt}")]
        pres = paket.xml("ppt/presentation.xml") if "ppt/presentation.xml" in paket.namen else None
        if pres is None:
            return ["Datei nicht lesbar"], [fund("xml", "ppt/presentation.xml", "", 1, "fehlt oder nicht lesbar")]
        pres_rels = lade_rels(paket, "ppt/presentation.xml")
        folien = [pres_rels[s.get(q(R, "id"))][1] for s in pres.iter(q(P, "sldId")) if s.get(q(R, "id")) in pres_rels]
        notizen = versteckt = 0
        sld_sz = pres.find(q(P, "sldSz"))
        try:
            groesse = (int(sld_sz.get("cx")), int(sld_sz.get("cy"))) if sld_sz is not None else None
        except (TypeError, ValueError):
            groesse = None
        hinweise = []
        funde += inhaltstypen(paket) + verweise(paket) + schriften(paket, pres)
        for n in sorted(paket.namen):
            if not n.endswith(".xml") or "/_rels/" in n:
                continue
            if n.startswith(("ppt/slides/", "ppt/slideLayouts/", "ppt/slideMasters/", "ppt/notesSlides/",
                             "ppt/charts/")):
                rels = lade_rels(paket, n)
                for _typ, ziel in rels.values():
                    if ziel.startswith(GETEILT) and not n.startswith("ppt/notesSlides/"):
                        nutzer.setdefault(ziel, set()).add(n)
                root = None if n.startswith("ppt/charts/") else paket.xml(n)
                if root is not None:
                    funde += funde_teil(n, root, {k: v[1] for k, v in rels.items()})
                    if n in folien:
                        versteckt += root.get("show") == "0"
                        notizen += any(t.endswith("/notesSlide") for t, _z in rels.values())
                        hinweise += gestaltung(n, folien.index(n) + 1, root, groesse)
        for ziel, quellen in sorted(nutzer.items()):
            if len(quellen) > 1:
                funde.append(fund("teil-geteilt", ziel, "", len(quellen),
                                  f"{len(quellen)} Teile zeigen darauf ({', '.join(sorted(quellen)[:5])})"))
        verlauf = [z_ for t, z_ in pres_rels.values() if t.endswith("/changesInfo") and z_ in paket.namen]
        for v in verlauf:
            funde.append(fund("aenderungsverlauf", v, "", 1, f"Änderungsverlauf, {z.getinfo(v).file_size // 1024} KB"))
        app = paket.xml("docProps/app.xml") if "docProps/app.xml" in paket.namen else None
        if app is not None:
            ist = {"Slides": len(folien), "Notes": notizen, "HiddenSlides": versteckt}
            falsch = [f"{k} {app.findtext(q(APP, k))} statt {v}" for k, v in ist.items()
                      if app.find(q(APP, k)) is not None and (app.findtext(q(APP, k)) or "").strip() != str(v)]
            if falsch:
                funde.append(fund("app-zaehler", "docProps/app.xml", "", 1, "Zähler " + ", ".join(falsch)))
        for n, grund in sorted(paket.defekt.items()):
            funde.append(fund("xml", n, "", 1, f"XML nicht wohlgeformt ({grund})"))
        funde += hinweise
    return [f"{len(folien)} Folie{'n' if len(folien) != 1 else ''}, davon {versteckt} ausgeblendet"], funde


def validate_py():
    """validate.py des pptx-Skills aus KITS_PPTX_VALIDATE, None ohne Angabe."""
    wert = os.environ.get(VALIDATE, "").strip()
    return wert or None


def xsd(pfad: str, original, ausgabe) -> int:
    """validate.py ohne -P aufrufen, sonst fehlen seine Module helpers und validators. 1 bei Fehlern."""
    v = validate_py()
    if not v:
        ausgabe("  INFO     XSD-Prüfung aus (Skill pptx am Mac nicht gefunden, motor.pptx_validate in der config.json "
                "von office nennt den Pfad zu validate.py)")
        return 0
    if not os.path.isfile(v):
        ausgabe(f"  WARNUNG  validate.py nicht gefunden ({v}), XSD-Prüfung fehlt")
        return 0
    cmd = [sys.executable, "-B", v, os.path.abspath(pfad)] + (["--original", os.path.abspath(original)] if original
                                                              else [])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.dirname(v), timeout=240)
    except subprocess.TimeoutExpired:
        ausgabe("  WARNUNG  validate.py nach 4 Minuten abgebrochen, XSD-Prüfung fehlt")
        return 0
    except OSError as e:
        ausgabe(f"  WARNUNG  validate.py nicht startbar ({e.strerror or e}), XSD-Prüfung fehlt")
        return 0
    zeilen = [z for z in (r.stdout + r.stderr).splitlines() if z.strip()]
    fehlt = next((z.split("No module named", 1)[1].strip(" '\"") for z in zeilen if "No module named" in z), "")
    if r.returncode != 0 and fehlt:
        pip = os.path.join(os.path.dirname(sys.executable), "pip")
        ausgabe(f"  INFO     XSD-Prüfung aus, optional: Paket {fehlt} fehlt in der .venv des Motors. Alle anderen "
                f"Prüfungen laufen. Einmal im Terminal: \"{pip}\" install {fehlt}")
        return 0
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
    zaehlt = schon = 0
    hinweise = []
    for f in funde:
        alt = f["schluessel"] in basis and f["anzahl"] <= basis[f["schluessel"]]
        if f["art"] in GESTALTUNG:
            schon += alt
            hinweise += [] if alt else [f]
        elif alt:
            ausgabe(f"  ORIGINAL {f['teil']}: {f['text']} (steckt schon im Original)")
        else:
            zaehlt += 1
            ausgabe(f"  FEHLER   {f['teil']}: {f['text']}. {ABHILFE[f['art']]}")
    if not zaehlt:
        ausgabe("  OK       keine PowerPoint-Fallen")
    for art in sorted({f["art"] for f in hinweise}, key=list(ABHILFE).index):  # je Art die Abhilfe einmal
        gruppe = [f for f in hinweise if f["art"] == art]
        for f in gruppe[:LISTE_MAX * 2]:
            ausgabe(f"  WARNUNG  {f['text']}")
        if len(gruppe) > LISTE_MAX * 2:
            ausgabe(f"  WARNUNG  und {len(gruppe) - LISTE_MAX * 2} weitere dieser Art")
        ausgabe(f"           {ABHILFE[art]}")
    if schon:
        ausgabe(f"  INFO     {schon} Hinweise zur Gestaltung stecken schon im Original")
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
