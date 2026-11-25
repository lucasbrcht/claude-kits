"""Stand einer Arbeitskopie zwischen den Runden von Claude: erkennt Änderungen von Hand und schützt sie.

Jede Runde von excel_skript und folien_aendern läuft über Runde: Sie vergleicht die Arbeitskopie mit dem Stand nach
der letzten Runde von Claude (Merkmale je Zelle, Format, Tabelle, Form, Text, Folie, im Zustandsordner), meldet
Änderungen von Hand und merkt sie sich. Die Änderung selbst entsteht in einer Kopie im Temp-Ordner. Zurück in die
Arbeitskopie geht sie nur, wenn sie keine Änderung von Hand überschreibt und (bei Excel) openpyxl nichts verliert,
sonst HALT ohne zu schreiben. ueberschreiben lässt beides zu, nur nach ausdrücklichem Wunsch des Nutzers. Danach nennt
die Runde die geänderten Bereiche und hebt den Stand davor für zuruecknehmen auf.

Aufruf für die Rücknahme der letzten Runde (arbeitskopie mit aktion zuruecknehmen):
  python3 -I stand.py zuruecknehmen <Arbeitskopie> --zustand <Ordner>

Merkmale sind kurze Prüfsummen je Schlüssel. Excel (openpyxl): Blatt!A1#wert, Blatt!A1#format, Blatt!B#breite,
Blatt!3#hoehe, Blatt!A1:C1#verbund, Blatt!A1:A9#bedingt, Blatt!A1:A9#pruefung, Blatt!Name#tabelle (Bereich),
Blatt!Name#tabellenformat (Format, Bänderung), Blatt!*#blatt, Blatt!*#filter, Mappe!*#reihenfolge. PowerPoint (lxml):
<sldId>!<Form-ID>#text, #schrift (Absatz- und Zeichenformat), #form (Lage, Füllung, Linie, Tabelle), <sldId>!*#folie,
<sldId>!*#notizen, Deck!*#reihenfolge, Deck!*#schriften. Sprachangaben (lang) zählen nicht, die setzt sprache.
Rückgabewert 0, 1 bei HALT, 2 bei falschem Aufruf.
"""
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from collections import defaultdict

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gemeinsam import offen_in_office, sha256  # noqa: E402

MAPPEN = (".xlsx", ".xlsm")
DECKS = (".pptx",)
ZEIGEN_MAX = 12  # Bereiche je Zeile in einer Meldung
ALT = (".json", ".basis.pptx")  # Zustand aus 8.0 (Liste erneut auf das Original), fällt beim ersten Lauf weg
ARTEN_XLSX = {"wert": "Werte", "format": "Format", "breite": "Spaltenbreite", "hoehe": "Zeilenhöhe",
              "verbund": "verbundene Zellen", "bedingt": "bedingte Formatierung", "pruefung": "Datenüberprüfung",
              "tabelle": "Bereich der Tabelle", "tabellenformat": "Format der Tabelle (Bänderung, Stil)",
              "blatt": "Blatt (Registerfarbe, fixiert, sichtbar)", "filter": "Filter", "reihenfolge": "Blätter"}
ARTEN_PPTX = {"text": "Text", "schrift": "Schrift und Absatz", "form": "Form (Lage, Füllung, Linie)",
              "folie": "Folie (Layout, Hintergrund, ausgeblendet)", "notizen": "Notizen",
              "reihenfolge": "Reihenfolge der Folien", "schriften": "eingebettete Schriften"}
# Was openpyxl beim Speichern still verliert: Teile im Zip und Elemente in den Blättern
VERLUST_TEILE = (("xl/drawings/", "Zeichnungen, Formen oder Bilder"), ("xl/media/", "Bilder"),
                 ("xl/charts/", "Diagramme"), ("xl/pivotTables/", "Pivot-Tabellen"),
                 ("xl/pivotCache/", "Pivot-Tabellen"), ("xl/slicers/", "Datenschnitte"),
                 ("xl/slicerCaches/", "Datenschnitte"), ("xl/timelines/", "Zeitachsen"),
                 ("xl/threadedComments/", "Kommentare"), ("xl/comments", "Notizen in Zellen"),
                 ("xl/vbaProject.bin", "Makros"), ("xl/ctrlProps/", "Steuerelemente"),
                 ("xl/externalLinks/", "Verknüpfungen zu anderen Mappen"), ("xl/queryTables/", "Abfragen"),
                 ("xl/connections.xml", "Datenverbindungen"))
VERLUST_XML = ((re.compile(rb"<\w+:conditionalFormatting[\s>]"), "bedingte Formatierung (neuere Art)"),
               (re.compile(rb"<\w+:dataValidation[\s>]"), "Datenüberprüfung (neuere Art)"),
               (re.compile(rb"<\w+:sparklineGroup[\s>]"), "Sparklines"))
SPRACHE = {"lang", "altLang", "dirty", "err", "noProof", "smtClean", "smtId"}  # setzen sprache und PowerPoint selbst


class Halt(Exception):
    """Runde endet ohne zu schreiben."""


def kurz(text) -> str:
    return hashlib.blake2b(str(text).encode("utf-8", "surrogatepass"), digest_size=6).hexdigest()


def art_von(schluessel: str) -> str:
    return schluessel.rsplit("#", 1)[1]


def teile(schluessel: str) -> tuple:
    """(Ort, Ref, Art) aus Ort!Ref#Art. Der Ort (Blattname) kann ! enthalten, Ref und Art nie."""
    vorn, art = schluessel.rsplit("#", 1)
    ort, ref = vorn.rsplit("!", 1)
    return ort, ref, art


# ---------- Excel ----------
def _zelle_wert(v) -> str:
    text = getattr(v, "text", None)  # ArrayFormula, DataTableFormula
    return f"{type(v).__name__}:{text if text is not None else v}"


def merkmale_xlsx(pfad: str) -> dict:
    import openpyxl  # nur im Motor (.venv)
    wb = openpyxl.load_workbook(pfad, rich_text=False)
    m, formate = {}, {}
    m["Mappe!*#reihenfolge"] = kurz([ws.title for ws in wb.worksheets])
    for ws in wb.worksheets:
        b = ws.title
        for zeile in ws.iter_rows():
            for c in zeile:
                if c.value is not None:
                    m[f"{b}!{c.coordinate}#wert"] = kurz(_zelle_wert(c.value))
                if c.has_style:
                    schluessel = tuple(c._style)
                    if schluessel not in formate:
                        formate[schluessel] = kurz((repr(c.font), repr(c.fill), repr(c.border), c.number_format,
                                                    repr(c.alignment), repr(c.protection)))
                    m[f"{b}!{c.coordinate}#format"] = formate[schluessel]
        for k, dim in ws.column_dimensions.items():
            if dim.customWidth or dim.hidden or dim.outlineLevel:
                m[f"{b}!{k}#breite"] = kurz((dim.width if dim.customWidth else None, dim.hidden, dim.outlineLevel,
                                             dim.min, dim.max))
        for k, dim in ws.row_dimensions.items():
            if dim.customHeight or dim.hidden or dim.outlineLevel:
                m[f"{b}!{k}#hoehe"] = kurz((dim.ht if dim.customHeight else None, dim.hidden, dim.outlineLevel))
        for rng in ws.merged_cells.ranges:
            m[f"{b}!{rng.coord}#verbund"] = "1"
        for cf in ws.conditional_formatting:
            regeln = [(r.type, r.operator, tuple(r.formula or ()), r.text, repr(r.dxf), r.stopIfTrue,
                       repr(r.colorScale), repr(r.dataBar), repr(r.iconSet)) for r in cf.rules]
            m[f"{b}!{cf.sqref}#bedingt"] = kurz(regeln)
        for dv in ws.data_validations.dataValidation:
            m[f"{b}!{dv.sqref}#pruefung"] = kurz((dv.type, dv.operator, dv.formula1, dv.formula2, dv.allow_blank,
                                                  dv.showDropDown))
        for t in ws.tables.values():
            m[f"{b}!{t.name}#tabelle"] = kurz((t.ref, [c.name for c in t.tableColumns], t.totalsRowCount))
            m[f"{b}!{t.name}#tabellenformat"] = kurz((repr(t.tableStyleInfo), t.headerRowCount,
                                                       repr(t.autoFilter) if t.autoFilter else None))
        ansicht = ws.sheet_view
        m[f"{b}!*#blatt"] = kurz((repr(ws.sheet_properties.tabColor), ws.freeze_panes, ws.sheet_state,
                                  ansicht.showGridLines, ansicht.zoomScale))
        if ws.auto_filter and ws.auto_filter.ref:
            m[f"{b}!*#filter"] = kurz(repr(ws.auto_filter))
    return m


def _spalte(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _zahl_spalte(s: str) -> int:
    n = 0
    for ch in s:
        n = n * 26 + ord(ch) - 64
    return n


def zellbereiche(refs) -> list:
    """Zellen wie A1, B1, A2 zu Bereichen wie A1:B2 (Zeilen mit gleicher Spannweite zusammen)."""
    zeilen = defaultdict(list)
    for ref in refs:
        m = re.fullmatch(r"([A-Z]+)(\d+)", ref)
        if m:
            zeilen[int(m.group(2))].append(_zahl_spalte(m.group(1)))
    spannen = defaultdict(list)
    for z, spalten in zeilen.items():
        spalten.sort()
        start = vor = spalten[0]
        for s in spalten[1:] + [None]:
            if s is not None and s == vor + 1:
                vor = s
                continue
            spannen[(start, vor)].append(z)
            if s is not None:
                start = vor = s
    aus = []
    for (s1, s2), zs in spannen.items():
        zs.sort()
        a = b = zs[0]
        for z in zs[1:] + [None]:
            if z is not None and z == b + 1:
                b = z
                continue
            erst, letzt = f"{_spalte(s1)}{a}", f"{_spalte(s2)}{b}"
            aus.append(((a, s1), erst if erst == letzt else f"{erst}:{letzt}"))
            if z is not None:
                a = b = z
    return [r for _k, r in sorted(aus)]


def beschreiben_xlsx(schluessel) -> list:
    gruppen = defaultdict(list)
    for s in schluessel:
        ort, ref, art = teile(s)
        gruppen[(ort, art)].append(ref)
    zeilen = []
    for (ort, art), refs in sorted(gruppen.items()):
        name = ARTEN_XLSX.get(art, art)
        if art in ("wert", "format"):
            refs = zellbereiche(refs)
        elif art in ("blatt", "filter", "reihenfolge"):
            refs = []
        else:
            refs = sorted(refs)
        wo = "Mappe" if ort == "Mappe" and art == "reihenfolge" else f"Blatt {ort}"
        zeilen.append(f"{wo}: {name}" + (f" {mehr(refs)}" if refs else ""))
    return zeilen


def verluste(vorher: str, nachher: str) -> list:
    """Was beim Speichern mit openpyxl verloren ging: Teile im Zip und Elemente der Blätter, die weniger wurden."""
    def zaehlen(pfad):
        teile_, xml = defaultdict(int), defaultdict(int)
        with zipfile.ZipFile(pfad) as z:
            for n in z.namelist():
                for anfang, name in VERLUST_TEILE:
                    if n.startswith(anfang):
                        teile_[name] += 1
                if n.startswith("xl/worksheets/") and n.endswith(".xml"):
                    daten = z.read(n)
                    for muster, name in VERLUST_XML:
                        xml[name] += len(muster.findall(daten))
        return teile_, xml
    (t1, x1), (t2, x2) = zaehlen(vorher), zaehlen(nachher)
    return [name for name in list(t1) + list(x1) if {**t2, **x2}.get(name, 0) < {**t1, **x1}[name]]


# ---------- PowerPoint ----------
def _pptx_ns():
    from lxml import etree  # nur im Motor (.venv)
    ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
          "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
          "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
          "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
    return etree, ns


def _ohne_sprache(el) -> str:
    etree, _ns = _pptx_ns()
    kopie = etree.fromstring(etree.tostring(el))
    for e in kopie.iter():
        for a in [a for a in e.attrib if etree.QName(a).localname in SPRACHE]:
            del e.attrib[a]
    return etree.tostring(kopie, method="c14n").decode("utf-8")


def _rels(z, teil: str) -> dict:
    etree, ns = _pptx_ns()
    ordner, name = teil.rsplit("/", 1)
    pfad = f"{ordner}/_rels/{name}.rels"
    if pfad not in z.namelist():
        return {}
    aus = {}
    for r in etree.fromstring(z.read(pfad)).iter("{%s}Relationship" % ns["rel"]):
        ziel = r.get("Target") or ""
        if r.get("TargetMode") != "External":
            aus[r.get("Id")] = (r.get("Type") or "", os.path.normpath(os.path.join(ordner, ziel)).lstrip("/")
                                if not ziel.startswith("/") else ziel.lstrip("/"))
    return aus


def folienliste(z) -> list:
    """[(sldId, Pfad der Folie)] in der Reihenfolge des Decks."""
    etree, ns = _pptx_ns()
    pres = etree.fromstring(z.read("ppt/presentation.xml"))
    rels = _rels(z, "ppt/presentation.xml")
    rid = "{%s}id" % ns["r"]
    return [(s.get("id"), rels[s.get(rid)][1]) for s in pres.iter("{%s}sldId" % ns["p"]) if s.get(rid) in rels]


def _text(el, ns) -> str:
    return "\n".join("".join(t.text or "" for t in p.iter("{%s}t" % ns["a"])) for p in el.iter("{%s}p" % ns["a"]))


def _formen(wurzel, ns):
    """(ID, Name, Element) je Form mit eigener ID, ohne die Doppel in mc:Fallback."""
    fallback = "{%s}Fallback" % ns["mc"]
    for c in wurzel.iter():
        if not isinstance(c.tag, str) or not c.tag.endswith("}cNvPr"):
            continue
        if any(a.tag == fallback for a in c.iterancestors()):
            continue
        el = c.getparent().getparent()
        if el is not None:
            yield c.get("id") or "?", c.get("name") or "", el


def merkmale_pptx(pfad: str) -> dict:
    etree, ns = _pptx_ns()
    a = "{%s}" % ns["a"]
    m = {}
    with zipfile.ZipFile(pfad) as z:
        liste = folienliste(z)
        m["Deck!*#reihenfolge"] = kurz([s for s, _p in liste])
        pres = etree.fromstring(z.read("ppt/presentation.xml"))
        lst = pres.find("{%s}embeddedFontLst" % ns["p"])
        m["Deck!*#schriften"] = kurz((etree.tostring(lst, method="c14n") if lst is not None else b"",
                                      pres.get("embedTrueTypeFonts"), pres.get("saveSubsetFonts")))
        for sid, teil in liste:
            wurzel = etree.fromstring(z.read(teil))
            rels = _rels(z, teil)
            layout = next((ziel for typ, ziel in rels.values() if typ.endswith("/slideLayout")), "")
            rumpf = etree.fromstring(etree.tostring(wurzel))
            for baum in rumpf.iter("{%s}spTree" % ns["p"]):
                baum.getparent().remove(baum)
                break
            m[f"{sid}!*#folie"] = kurz((_ohne_sprache(rumpf), layout))
            notiz = next((ziel for typ, ziel in rels.values() if typ.endswith("/notesSlide")), None)
            if notiz and notiz in z.namelist():
                text = _text(etree.fromstring(z.read(notiz)), ns)
                if text.strip():
                    m[f"{sid}!*#notizen"] = kurz(text)
            baum = wurzel.find(".//{%s}spTree" % ns["p"])
            for fid, _name, el in (_formen(baum, ns) if baum is not None else ()):
                if el is baum or el.tag.endswith("}spTree"):
                    continue
                kopie = etree.fromstring(etree.tostring(el))
                if kopie.tag.endswith("}grpSp"):  # Gruppe: nur eigene Angaben, die Formen darin zählen selbst
                    for k in [k for k in kopie if not k.tag.endswith(("}nvGrpSpPr", "}grpSpPr"))]:
                        kopie.remove(k)
                text = _text(kopie, ns)
                if text.strip():
                    m[f"{sid}!{fid}#text"] = kurz(text)
                schrift = sorted({_ohne_sprache(e) for e in kopie.iter(a + "rPr", a + "pPr", a + "endParaRPr",
                                                                         a + "bodyPr", a + "lstStyle", a + "defRPr")})
                if schrift:
                    m[f"{sid}!{fid}#schrift"] = kurz(schrift)
                for e in list(kopie.iter("{%s}txBody" % ns["p"], a + "txBody")):
                    e.getparent().remove(e)
                for e in list(kopie.iter(a + "t", a + "rPr", a + "pPr", a + "endParaRPr")):
                    if e.getparent() is not None:
                        e.getparent().remove(e)
                m[f"{sid}!{fid}#form"] = kurz(_ohne_sprache(kopie))
    return m


def etiketten(pfad: str) -> tuple:
    """({sldId: Nummer}, {(sldId, Form-ID): Name}) für Meldungen in der Zählung des Decks."""
    if not pfad or not os.path.isfile(pfad):
        return {}, {}
    etree, ns = _pptx_ns()
    nummern, namen = {}, {}
    with zipfile.ZipFile(pfad) as z:
        for nr, (sid, teil) in enumerate(folienliste(z), 1):
            nummern[sid] = nr
            for fid, name, _el in _formen(etree.fromstring(z.read(teil)), ns):
                namen[(sid, fid)] = name
    return nummern, namen


def beschreiben_pptx(schluessel, *pfade) -> list:
    nummern, namen, jetzt = {}, {}, {}
    for p in pfade:  # spätere Pfade (nachher) gewinnen, gelöschte Folien kennt nur der Stand davor
        jetzt, f = etiketten(p)
        nummern.update(jetzt)
        namen.update(f)
    je_folie = defaultdict(list)
    for s in schluessel:
        ort, ref, art = teile(s)
        je_folie[ort].append((ref, art))
    zeilen = []
    for ort, eintraege in sorted(je_folie.items(), key=lambda x: (x[0] != "Deck", nummern.get(x[0], 10 ** 6))):
        if ort == "Deck":
            zeilen += [f"Deck: {ARTEN_PPTX.get(art, art)}" for _r, art in sorted(eintraege)]
            continue
        if jetzt and ort not in jetzt:
            zeilen.append(f"Folie {nummern[ort]} gelöscht" if ort in nummern else "eine Folie gelöscht")
            continue
        formen, folie = defaultdict(set), []
        for ref, art in eintraege:
            if ref == "*":
                folie.append(ARTEN_PPTX.get(art, art))
            else:
                formen[ref].add(ARTEN_PPTX.get(art, art).split(" (")[0])
        teile_ = folie + [f"Form {fid}" + (f" {namen[(ort, fid)]}" if namen.get((ort, fid)) else "")
                          + f" ({', '.join(sorted(a))})" for fid, a in sorted(formen.items(),
                                                                              key=lambda x: (len(x[0]), x[0]))]
        wo = f"Folie {nummern[ort]}" if ort in nummern else "gelöschte Folie"
        zeilen.append(f"{wo}: {mehr(teile_)}")
    return zeilen


# ---------- Gemeinsam ----------
def mehr(liste: list) -> str:
    return ", ".join(liste[:ZEIGEN_MAX]) + (f" und {len(liste) - ZEIGEN_MAX} weitere" if len(liste) > ZEIGEN_MAX
                                            else "")


def merkmale(pfad: str) -> dict:
    return merkmale_xlsx(pfad) if pfad.lower().endswith(MAPPEN) else merkmale_pptx(pfad)


def unterschied(alt: dict, neu: dict) -> set:
    return {k for k in set(alt) | set(neu) if alt.get(k) != neu.get(k)}


def beschreiben(schluessel, *pfade) -> list:
    if not schluessel:
        return []
    if any(p and p.lower().endswith(MAPPEN) for p in pfade):
        return beschreiben_xlsx(schluessel)
    return beschreiben_pptx(schluessel, *pfade)


class Zustand:
    """Dateien je Arbeitskopie im Zustandsordner, Name aus der Prüfsumme ihres Pfads."""

    def __init__(self, ordner: str, kopie: str):
        self.ordner = ordner
        self.stamm = os.path.join(ordner, hashlib.sha256(os.path.realpath(kopie).encode("utf-8")).hexdigest()[:16])
        self.json = self.stamm + ".stand.json"
        self.vorher = self.stamm + ".vorher" + os.path.splitext(kopie)[1].lower()

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
            json.dump(daten, f, ensure_ascii=False)
        os.replace(tmp, self.json)

    def alt_aufraeumen(self) -> bool:
        """Zustand aus 8.0 entfernen. True, wenn es ihn gab (erste Runde nach dem Update)."""
        alt = False
        for endung in ALT:
            if os.path.isfile(self.stamm + endung):
                os.remove(self.stamm + endung)
                alt = True
        return alt


def kopieren(quelle: str, ziel: str):
    """Inhalt in die vorhandene Datei schreiben (gleiche Datei für Office und iCloud), nie durch einen Verweis."""
    if os.path.islink(ziel):
        raise Halt(f"{ziel} ist ein Verweis. Nichts geschrieben.")
    shutil.copyfile(quelle, ziel)


class Runde:
    """Eine Runde von Claude auf einer Arbeitskopie (Ablauf im Docstring des Moduls)."""

    def __init__(self, kopie: str, zustand_ordner: str, original: str = None):
        if offen_in_office(kopie):
            app = "Excel" if kopie.lower().endswith(MAPPEN) else "PowerPoint"
            raise Halt(f"{os.path.basename(kopie)} ist in {app} offen. Den Nutzer bitten, das Fenster zu schließen "
                       "(gespeicherte Änderungen bleiben und gelten), dann erneut. Nichts geschrieben.")
        self.kopie, self.original = kopie, original
        self.z = Zustand(zustand_ordner, kopie)
        self.nach_update = self.z.alt_aufraeumen()
        self.stand = self.z.lesen()
        self.sha = sha256(kopie)
        try:
            self.aktuell = merkmale(kopie)
        except Exception as x:  # kaputte Datei: nichts anfassen
            raise Halt(f"{os.path.basename(kopie)} nicht lesbar ({type(x).__name__}: {x}). Mit folien_pruefen oder "
                       "excel_fertig prüfen. Nichts geschrieben.") from None
        self.hand, self.erste = set(), not self.stand.get("merkmale")
        if not self.erste and self.sha != self.stand.get("sha"):
            self.hand = unterschied(self.stand["merkmale"], self.aktuell)
        elif self.erste and original and os.path.isfile(original) and sha256(original) != self.sha:
            try:
                self.hand = unterschied(merkmale(original), self.aktuell)
            except Exception:  # Original nicht lesbar: dann nur ab jetzt
                self.hand = set()
        self.von_hand = set(self.stand.get("von_hand") or []) | self.hand
        self.ordner = tempfile.mkdtemp(prefix="runde-")
        self.arbeit = os.path.join(self.ordner, os.path.basename(kopie))
        shutil.copyfile(kopie, self.arbeit)
        self.davor = os.path.join(self.ordner, "vorher" + os.path.splitext(kopie)[1])
        shutil.copyfile(kopie, self.davor)

    def meldung_hand(self) -> list:
        if not self.hand:
            return []
        if self.erste:
            kopf = "VON HAND  Arbeitskopie weicht schon vom Original ab (von Hand oder in einer früheren Runde):"
        else:
            kopf = "VON HAND  Arbeitskopie seit der letzten Runde von Hand geändert, das gilt und bleibt:"
        return [kopf] + ["  " + z for z in beschreiben(self.hand, self.original, self.davor)]

    def merken(self, sha=None, merkmale_=None, vorher=None):
        """Stand speichern. Ohne Angaben (Runde ohne Schreiben) der aktuelle Stand, Änderungen von Hand bleiben
        gemerkt."""
        daten = {"sha": sha or self.sha, "merkmale": merkmale_ if merkmale_ is not None else self.aktuell,
                 "von_hand": sorted(self.von_hand)}
        if vorher is not None:
            daten["vorher"] = vorher
        elif self.stand.get("vorher") and self.stand.get("sha") == self.sha:
            daten["vorher"] = self.stand["vorher"]
        self.z.schreiben(daten)

    def abschliessen(self, ueberschreiben: bool = False, erlaubt=()) -> tuple:
        """(Code, Zeilen) nach der Änderung in self.arbeit: vergleichen, schützen, schreiben, merken. erlaubt sind
        Schlüssel, die der Auftrag ausdrücklich ändert (etwa reparieren die Schriften)."""
        nachher = merkmale(self.arbeit)
        claude = unterschied(self.aktuell, nachher)
        if not claude:
            self.merken()
            return 0, ["Keine Änderung an der Datei, nichts geschrieben."]
        ueber = (claude & self.von_hand) - set(erlaubt)
        verlust = verluste(self.davor, self.arbeit) if self.kopie.lower().endswith(MAPPEN) else []
        if (ueber or verlust) and not ueberschreiben:
            self.merken()
            zeilen = ["HALT  Nichts geschrieben."]
            if ueber:
                zeilen += ["Der Auftrag würde Änderungen von Hand überschreiben:"]
                zeilen += ["  " + z for z in beschreiben(ueber, self.davor, self.arbeit)]
            if verlust:
                zeilen += ["openpyxl würde beim Speichern verlieren: " + ", ".join(verlust)]
            zeilen += ["Den Code so ändern, dass er nur anfasst, was der Auftrag nennt. Will der Nutzer genau das, "
                       "erneut mit ueberschreiben und es in der Übergabe nennen."]
            return 1, zeilen
        os.makedirs(self.z.ordner, exist_ok=True)
        shutil.copyfile(self.davor, self.z.vorher)
        kopieren(self.arbeit, self.kopie)
        vorher = {"sha": self.sha, "merkmale": self.aktuell, "von_hand": sorted(self.von_hand)}
        if ueberschreiben:
            self.von_hand -= claude
        self.merken(sha256(self.kopie), nachher, vorher)
        zeilen = ["GEÄNDERT in dieser Runde (für die Übergabe):"]
        zeilen += ["  " + z for z in beschreiben(claude, self.davor, self.kopie)]
        if ueber:
            zeilen += ["ÜBERSCHRIEBEN auf Wunsch (Änderungen von Hand):"]
            zeilen += ["  " + z for z in beschreiben(ueber, self.davor, self.kopie)]
        if verlust:
            zeilen += ["VERLOREN auf Wunsch: " + ", ".join(verlust)]
        return 0, zeilen

    def aufraeumen(self):
        shutil.rmtree(self.ordner, ignore_errors=True)


def zuruecknehmen(kopie: str, zustand_ordner: str) -> int:
    """Letzte Runde von Claude zurücknehmen: Stand davor zurück in die Arbeitskopie, nur wenn sie seither niemand
    geändert hat. Nur eine Runde zurück."""
    if offen_in_office(kopie):
        print(f"HALT  {os.path.basename(kopie)} ist offen. Den Nutzer bitten, das Fenster zu schließen. Nichts "
              "geändert.", file=sys.stderr)
        return 1
    z = Zustand(zustand_ordner, kopie)
    stand = z.lesen()
    vorher = stand.get("vorher")
    if not vorher or not os.path.isfile(z.vorher) or sha256(z.vorher) != vorher.get("sha"):
        print("HALT  Keine Runde zum Zurücknehmen (nur die letzte Runde von Claude geht). Nichts geändert.",
              file=sys.stderr)
        return 1
    if sha256(kopie) != stand.get("sha"):
        print("HALT  Arbeitskopie seit der letzten Runde von Hand geändert, Zurücknehmen würde das verwerfen. "
              "Den Nutzer fragen, gezielt zurückändern. Nichts geändert.", file=sys.stderr)
        return 1
    try:
        kopieren(z.vorher, kopie)
    except Halt as x:
        print(f"HALT  {x}", file=sys.stderr)
        return 1
    z.schreiben({"sha": vorher["sha"], "merkmale": vorher.get("merkmale") or {},
                 "von_hand": vorher.get("von_hand") or []})
    os.remove(z.vorher)
    print(f"Zurückgenommen: {kopie} hat wieder den Stand vor der letzten Runde von Claude.")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if len(args) == 4 and args[0] == "zuruecknehmen" and args[2] == "--zustand" and os.path.isfile(args[1]):
        return zuruecknehmen(os.path.abspath(args[1]), args[3])
    print(__doc__.split("\n\n")[2], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
