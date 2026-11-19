"""Helfer der Motor-Skripte (aendern.py, excel.py): Prüfsumme und Sperrdatei von Office. Nur Standardbibliothek."""
import hashlib
import os


def sha256(pfad: str) -> str:
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def offen_in_office(pfad: str):
    """Sperrdatei von PowerPoint, Word oder Excel (~$Name, bei langen Namen ersetzt sie die ersten zwei Zeichen),
    solange die Datei dort offen ist, sonst None."""
    ordner, name = os.path.split(os.path.abspath(pfad))
    for kandidat in ("~$" + name, "~$" + name[2:]):
        if len(kandidat) > 2 and os.path.exists(os.path.join(ordner, kandidat)):
            return os.path.join(ordner, kandidat)
    return None
