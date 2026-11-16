"""Tests für kontakte.py ohne Apple Kontakte: eine erfundene Adressbuch-Datenbank mit dem Teilschema von
AddressBook-v22.abcddb, Personen Max und Erika Mustermann, Nummern aus Nullen, Adressen unter example.invalid
(V3.1.2, Befunde 22 und 24).

Aufruf im Kit-Ordner: python3 -B -m unittest discover tests
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ersatz_eventkit import KitTest

import kontakte  # noqa: E402

SCHEMA = """
CREATE TABLE ZABCDRECORD (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, ZUNIQUEID VARCHAR, ZFIRSTNAME VARCHAR,
  ZMIDDLENAME VARCHAR, ZLASTNAME VARCHAR, ZNICKNAME VARCHAR, ZORGANIZATION VARCHAR, ZDEPARTMENT VARCHAR,
  ZJOBTITLE VARCHAR, ZBIRTHDAY TIMESTAMP, ZDISPLAYFLAGS INTEGER, ZNAME VARCHAR);
CREATE TABLE ZABCDPHONENUMBER (Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER, ZLABEL VARCHAR, ZFULLNUMBER VARCHAR,
  ZORDERINGINDEX INTEGER);
CREATE TABLE ZABCDEMAILADDRESS (Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER, ZLABEL VARCHAR, ZADDRESS VARCHAR,
  ZORDERINGINDEX INTEGER);
CREATE TABLE ZABCDPOSTALADDRESS (Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER, ZLABEL VARCHAR, ZSTREET VARCHAR,
  ZZIPCODE VARCHAR, ZCITY VARCHAR, ZSTATE VARCHAR, ZCOUNTRYNAME VARCHAR);
CREATE TABLE ZABCDCONTACTDATE (Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER, ZLABEL VARCHAR, ZDATE TIMESTAMP);
CREATE TABLE ZABCDRELATEDNAME (Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER, ZLABEL VARCHAR, ZNAME VARCHAR);
CREATE TABLE ZABCDURLADDRESS (Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER, ZLABEL VARCHAR, ZURL VARCHAR);
"""
GEB_MAX = 315576000.0 - 3600  # 01.01.2011, Mitternacht in Berlin
OHNE_JAHR = -12522646800.0  # 05.03.1604, Mitternacht in Berlin: Geburtstag ohne Jahr


def baue(pfad: Path, mit_feldern=True) -> None:
    con = sqlite3.connect(pfad)
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO ZABCDRECORD (Z_PK, ZUNIQUEID, ZFIRSTNAME, ZLASTNAME, ZNICKNAME, ZORGANIZATION, "
                    "ZJOBTITLE, ZBIRTHDAY, ZDISPLAYFLAGS, ZNAME) VALUES (?,?,?,?,?,?,?,?,?,?)", [
                        (1, "AAA-1:ABPerson", "Max", "Mustermann", "Maxi", "Beispiel GmbH", "Prüfer", GEB_MAX, 0,
                         None),
                        (2, "BBB-2:ABPerson", "Erika", "Mustermann", None, None, None, OHNE_JAHR, 0, None),
                        (3, "CCC-3:ABPerson", None, None, None, "Muster AG", None, None, 1, None),
                        (4, "DDD-4:ABGroup", None, None, None, None, None, None, 0, "Familie")])
    if mit_feldern:
        con.executemany("INSERT INTO ZABCDPHONENUMBER (ZOWNER, ZLABEL, ZFULLNUMBER, ZORDERINGINDEX) VALUES (?,?,?,?)",
                        [(1, "_$!<Mobile>!$_", "+49 000 0000001", 0), (2, "Garten", "0000 0000002", 0)])
        con.executemany("INSERT INTO ZABCDEMAILADDRESS (ZOWNER, ZLABEL, ZADDRESS, ZORDERINGINDEX) VALUES (?,?,?,?)",
                        [(1, "_$!<Work>!$_", "max@example.invalid", 0), (2, "_$!<Home>!$_", "erika@example.invalid", 0)])
        con.execute("INSERT INTO ZABCDPOSTALADDRESS (ZOWNER, ZLABEL, ZSTREET, ZZIPCODE, ZCITY, ZCOUNTRYNAME) VALUES "
                    "(1, '_$!<Home>!$_', 'Musterweg 1\nHinterhaus', '00000', 'Musterstadt', 'Deutschland')")
        con.execute("INSERT INTO ZABCDCONTACTDATE (ZOWNER, ZLABEL, ZDATE) VALUES (1, '_$!<Anniversary>!$_', ?)",
                    (GEB_MAX,))
        con.execute("INSERT INTO ZABCDRELATEDNAME (ZOWNER, ZLABEL, ZNAME) VALUES (1, '_$!<Spouse>!$_', 'Erika')")
        con.execute("INSERT INTO ZABCDURLADDRESS (ZOWNER, ZLABEL, ZURL) VALUES (1, '_$!<HomePage>!$_', "
                    "'https://example.invalid')")
    con.commit()
    con.close()


class KontakteTest(KitTest):

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.wurzel = Path(tmp.name)
        (self.wurzel / "Sources/X").mkdir(parents=True)
        baue(self.wurzel / "Sources/X" / kontakte.DATEI)
        p = mock.patch.object(kontakte, "ADRESSBUCH", self.wurzel)
        p.start()
        self.addCleanup(p.stop)
        self.config(kontakte={"eigene_mails": ["Max@Example.invalid"]})

    def lauf(self, *argv):
        return super().lauf(kontakte.main, *argv)

    def test_me_mit_allen_feldern(self):
        out, fehler = self.lauf("me")
        self.assertIsNone(fehler)
        z = out.splitlines()
        self.assertTrue(z[0].startswith("("))  # Datenhinweis
        self.assertEqual(z[1:], [
            "Max Mustermann", "ID: AAA-1:ABPerson", "Spitzname: Maxi", "Firma: Beispiel GmbH", "Position: Prüfer",
            "Telefon (Mobil): +49 000 0000001", "Mail (Arbeit): max@example.invalid",
            "Adresse (Privat): Musterweg 1, Hinterhaus, 00000 Musterstadt, Deutschland",
            "Geburtstag: 01.01.2011", "Datum (Jahrestag): 01.01.2011", "Beziehung (Ehepartner): Erika",
            "URL (Homepage): https://example.invalid"])

    def test_me_ohne_eigene_mails_und_falscher_typ(self):
        self.config(kontakte={})
        _out, fehler = self.lauf("me")
        self.assertIn("kontakte.eigene_mails", fehler)
        self.config(kontakte={"eigene_mails": "max@example.invalid"})
        _out, fehler = self.lauf("me")
        self.assertEqual(fehler, "config.json: kontakte.eigene_mails muss eine Liste sein.")

    def test_search_name_firma_mail_telefon_ohne_gruppen(self):
        for text in ("mustermann", "ERIKA@", "beispiel", "0000002", "Muster AG"):
            out, fehler = self.lauf("search", text)
            self.assertIsNone(fehler, text)
            self.assertIn("Treffer", out, text)
        out, _f = self.lauf("search", "muster")
        self.assertIn("- Erika Mustermann  (ID BBB-2:ABPerson)", out)
        self.assertIn("- Max Mustermann, Beispiel GmbH, Prüfer  (ID AAA-1:ABPerson)", out)
        self.assertIn("- Muster AG  (ID CCC-3:ABPerson)", out)
        out, _f = self.lauf("search", "Familie")
        self.assertEqual(out.strip(), "Kein Kontakt zu 'Familie'.")

    def test_show_mit_geburtstag_ohne_jahr_und_eigenem_etikett(self):
        out, fehler = self.lauf("show", "BBB-2:ABPerson")
        self.assertIsNone(fehler)
        self.assertIn("Geburtstag: 05.03.", out.splitlines())
        self.assertIn("Telefon (Garten): 0000 0000002", out)
        _out, fehler = self.lauf("show", "nichts")
        self.assertIn("Kein Kontakt mit der ID nichts", fehler)

    def test_mehrere_quellen_gleiche_karte_einmal(self):
        baue(self.wurzel / kontakte.DATEI)
        out, _f = self.lauf("search", "erika")
        self.assertEqual(out.count("Erika Mustermann"), 1)
        out, _f = self.lauf("show", "AAA-1:ABPerson")
        self.assertEqual(out.count("Max Mustermann"), 1)

    def test_fehlende_tabellen_und_spalten(self):
        for p in self.wurzel.rglob(kontakte.DATEI):
            p.unlink()
        baue(self.wurzel / kontakte.DATEI, mit_feldern=False)
        con = sqlite3.connect(self.wurzel / kontakte.DATEI)
        con.execute("DROP TABLE ZABCDURLADDRESS")
        con.commit()
        con.close()
        out, fehler = self.lauf("show", "AAA-1:ABPerson")
        self.assertIsNone(fehler)
        self.assertIn("Geburtstag: 01.01.2011", out)

    def test_ohne_datenbank_und_ohne_zugriff(self):
        with mock.patch.object(kontakte, "ADRESSBUCH", self.wurzel / "fehlt"):
            _out, fehler = self.lauf("search", "max")
        self.assertIn("Festplattenvollzugriff", fehler)
        with mock.patch.object(kontakte, "kopiere", side_effect=PermissionError):
            _out, fehler = self.lauf("me")
        self.assertIn("Kein Zugriff auf die Kontakte-Datenbank", fehler)

    def test_falsche_aufrufe(self):
        for argv in (("me", "x"), ("search",), ("show", " "), ("loeschen", "1"), ()):
            _out, code = self.lauf(*argv)
            self.assertEqual(code, 2, argv)

    def test_datum(self):
        self.assertEqual(kontakte.datum(None), "")
        self.assertEqual(kontakte.datum("kaputt"), "")
        self.assertEqual(kontakte.datum(0), "01.01.2001")


if __name__ == "__main__":
    unittest.main()
