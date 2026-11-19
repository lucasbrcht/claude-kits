"""Folien aus einem anderen Deck (oder demselben) übernehmen, jedes Teil als eigene Kopie. aendern.py nutzt das Modul
für die Art uebernehmen und für die neuen Folien im Vergleich.

Kopiert die Folie mit allem, worauf sie zeigt: Bilder, Diagramme mit eingebetteter Arbeitsmappe, eingebettete Objekte,
SmartArt, Markierungen von Add-ins und die Notizseite, rekursiv und je Teil neu. So teilen sich nie zwei Folien ein
Teil, anders als nach add_slide.py aus dem pptx-Skill. Die Beziehungs-IDs bleiben gleich, damit auch Verweise in VML
und Erweiterungen stimmen. Das Layout kommt nach Namen aus dem Ziel. Kommentare des Quelldecks und Sprünge auf seine
Folien bleiben weg, eine ausgeblendete Folie wird eingeblendet.
"""
import re

from pptx.opc.constants import RELATIONSHIP_TARGET_MODE as RTM
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.opc.package import PartFactory, _Relationship
from pptx.opc.packuri import PackURI

from lesen import NS, RT_KOMMENTARE

NAME_RE = re.compile(r"^(.*?)(\d*)(\.[^./]+)$")


class Fehler(Exception):
    pass


def layout_suchen(prs, name: str):
    return next((lay for m in prs.slide_masters for lay in m.slide_layouts if lay.name == name), None)


class Kopierer:
    def __init__(self, prs):
        self.prs, self.paket = prs, prs.part.package
        self.belegt = {str(p.partname) for p in self.paket.iter_parts()}
        self.memo = {}

    def name(self, alt) -> PackURI:
        stamm, _nr, endung = NAME_RE.match(str(alt)).groups()
        n = 1
        while f"{stamm}{n}{endung}" in self.belegt:
            n += 1
        self.belegt.add(f"{stamm}{n}{endung}")
        return PackURI(f"{stamm}{n}{endung}")

    def neu(self, quelle):
        teil = PartFactory(self.name(quelle.partname), quelle.content_type, self.paket, quelle.blob)
        self.memo[quelle] = teil
        return teil

    def teil(self, quelle):
        """Eigene Kopie eines Teils samt allem, worauf es zeigt."""
        if quelle not in self.memo:
            self.beziehungen(quelle, self.neu(quelle), {})
        return self.memo[quelle]

    def beziehungen(self, quelle, neu, ersatz: dict) -> list:
        """Beziehungen mit gleicher ID übertragen. ersatz: {Typ: Ziel oder None (weglassen)}. Liefert die IDs der
        weggelassenen Beziehungen."""
        weg = []
        for rid, rel in quelle.rels.items():
            if rel.is_external:
                ziel = rel.target_ref
            elif rel.reltype in ersatz:
                ziel = ersatz[rel.reltype]
            else:
                ziel = self.teil(rel.target_part)
            if ziel is None:
                weg.append(rid)
                continue
            neu.rels._rels[rid] = _Relationship(neu.rels._base_uri, rid, rel.reltype,
                                                RTM.EXTERNAL if rel.is_external else RTM.INTERNAL, ziel)
        return weg


def kopieren(prs, folie, layout: str = None):
    """Kopie der Folie folie (aus einem beliebigen Deck) ans Ende von prs. Liefert (neue Folie, sldId-Element)."""
    name = layout or folie.slide_layout.name
    ziel_layout = layout_suchen(prs, name)
    if ziel_layout is None:
        raise Fehler(f"Layout {name!r} fehlt im Ziel, mit layout ein vorhandenes nennen "
                     f"({', '.join(lay.name for m in prs.slide_masters for lay in m.slide_layouts)})")
    k = Kopierer(prs)
    neu = k.neu(folie.part)
    sid = prs.slides._sldIdLst.add_sldId(prs.part.relate_to(neu, RT.SLIDE))
    ersatz = {RT.SLIDE_LAYOUT: ziel_layout.part, RT.SLIDE: None, RT.NOTES_SLIDE: None,
              **{t: None for t in RT_KOMMENTARE}}
    weg = k.beziehungen(folie.part, neu, ersatz)
    for el in list(neu._element.iter()):  # Sprünge auf Folien des Quelldecks
        if any(k_.startswith("{%s}" % NS["r"]) and v in weg for k_, v in el.attrib.items()):
            el.getparent().remove(el)
    for rid, rel in list(folie.part.rels.items()):
        if rel.reltype == RT.NOTES_SLIDE:
            notiz = k.neu(rel.target_part)
            k.beziehungen(rel.target_part, notiz, {RT.NOTES_MASTER: prs.part.notes_master_part, RT.SLIDE: neu})
            neu.rels._rels[rid] = _Relationship(neu.rels._base_uri, rid, RT.NOTES_SLIDE, RTM.INTERNAL, notiz)
    neu._element.attrib.pop("show", None)
    return neu.slide, sid
