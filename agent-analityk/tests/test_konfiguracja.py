"""Testy konfiguracji: staż z daty, usuwanie ludzi, status tematów,
mapowanie typów aktywności na wskaźniki."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

KORZEN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KORZEN / "src"))

from analityk.models import Activity, zbuduj_id  # noqa: E402
from analityk.org import Biuro, Pracownik  # noqa: E402
from analityk.punktacja import (  # noqa: E402
    MAPOWANIE_DOMYSLNE,
    licznosci_okresu,
    licznosci_z_aktywnosci,
    niezmapowane_typy,
)
from analityk.store import Baza  # noqa: E402


def akt(podtyp: str, kanal: str = "bezposredni", i: int = 0,
        pracownik: str = "a") -> Activity:
    d = datetime(2026, 8, 10, 9 + i % 10, 0)
    return Activity(
        id=zbuduj_id(pracownik, d, podtyp, str(i)), pracownik=pracownik,
        pracownik_nazwa=pracownik.upper(), data=d, kanal=kanal, podtyp=podtyp,
        notatka="n" * 30, budynek="Dworcowa 7", lokal=str(i),
    )


class TestStazZDaty(unittest.TestCase):
    def test_liczony_z_daty_zatrudnienia(self):
        dzis = date.today()
        rok_temu = dzis.replace(year=dzis.year - 1)
        p = Pracownik(klucz="a", imie_nazwisko="A", zatrudniony_od=rok_temu.isoformat())
        self.assertEqual(p.staz, 12)
        self.assertFalse(p.nowicjusz)

    def test_niepelny_miesiac_nie_liczy_sie(self):
        dzis = date.today()
        if dzis.day < 28:                      # test ma sens tylko w takim dniu
            prawie_miesiac = (dzis - timedelta(days=dzis.day - 1)).isoformat()
            p = Pracownik(klucz="a", imie_nazwisko="A", zatrudniony_od=prawie_miesiac)
            self.assertEqual(p.staz, 0)

    def test_bez_daty_uzywa_wartosci_recznej(self):
        p = Pracownik(klucz="a", imie_nazwisko="A", staz_miesiace=7)
        self.assertEqual(p.staz, 7)

    def test_data_ma_pierwszenstwo_przed_wartoscia_reczna(self):
        dzis = date.today()
        p = Pracownik(klucz="a", imie_nazwisko="A", staz_miesiace=99,
                      zatrudniony_od=dzis.isoformat())
        self.assertEqual(p.staz, 0)

    def test_bledna_data_nie_wywala(self):
        p = Pracownik(klucz="a", imie_nazwisko="A", zatrudniony_od="kiedyś",
                      staz_miesiace=4)
        self.assertEqual(p.staz, 4)

    def test_opis_stazu(self):
        dzis = date.today()
        dwa_lata = dzis.replace(year=dzis.year - 2)
        self.assertEqual(
            Pracownik(klucz="a", imie_nazwisko="A",
                      zatrudniony_od=dwa_lata.isoformat()).staz_opis, "2 l.")


class TestMapowanieTypow(unittest.TestCase):
    def test_domyslne_mapowanie(self):
        aktywnosci = (
            [akt("RICERCA", i=i) for i in range(5)]
            + [akt("Telefon z propozycją dzierżawy", "telefon", i=10 + i) for i in range(3)]
        )
        self.assertEqual(licznosci_z_aktywnosci(aktywnosci), {"IM3": 5, "R4": 3})

    def test_krotkie_kody_tylko_jako_osobne_slowo(self):
        """„ven” nie może łapać się w środku innego wyrazu."""
        mapowanie = {"ven": "REP17"}
        self.assertEqual(
            licznosci_z_aktywnosci([akt("Spotkanie VEN wykonane")], mapowanie),
            {"REP17": 1},
        )
        self.assertEqual(
            licznosci_z_aktywnosci([akt("Prevention")], mapowanie), {}
        )

    def test_jeden_kontakt_liczy_sie_raz(self):
        mapowanie = {"ricerca": "IM3", "bezposredni": "NO10"}
        self.assertEqual(sum(licznosci_z_aktywnosci([akt("RICERCA")], mapowanie).values()), 1)

    def test_niezmapowany_typ_nie_jest_zgadywany(self):
        licznosci = licznosci_z_aktywnosci([akt("Jakiś Nowy Typ")], {"ricerca": "IM3"})
        self.assertEqual(licznosci, {})

    def test_lista_niezmapowanych(self):
        typy = [
            {"kanal": "bezposredni", "podtyp": "RICERCA", "n": 38},
            {"kanal": "telefon", "podtyp": "Tel ogólny", "n": 4},
        ]
        mapowanie = {w: kod for w, (kod, _) in MAPOWANIE_DOMYSLNE.items()}
        braki = niezmapowane_typy(typy, mapowanie)
        self.assertEqual([t["podtyp"] for t in braki], ["Tel ogólny"])


class TestKonfiguracjaWBazie(unittest.TestCase):
    def setUp(self):
        self.katalog = tempfile.TemporaryDirectory()
        self.baza = Baza(Path(self.katalog.name) / "t.db")

    def tearDown(self):
        self.baza.zamknij()
        self.katalog.cleanup()

    def test_wlasne_mapowanie_nadpisuje_domyslne(self):
        self.baza.zapisz_aktywnosci([akt("Tel ogólny", "telefon", i=i) for i in range(4)])
        self.assertEqual(licznosci_okresu(self.baza, "a", "dzien", "2026-08-10"), {})

        self.baza.ustaw_mapowanie("tel ogólny", "R4", "telefon ogólny")
        self.assertEqual(
            licznosci_okresu(self.baza, "a", "dzien", "2026-08-10"), {"R4": 4}
        )

    def test_usuniecie_mapowania(self):
        self.baza.ustaw_mapowanie("ricerca", "IM3")
        self.assertIn("ricerca", self.baza.mapowanie_typow())
        self.baza.ustaw_mapowanie("ricerca", "")
        self.assertNotIn("ricerca", self.baza.mapowanie_typow())

    def test_wystepujace_typy(self):
        self.baza.zapisz_aktywnosci(
            [akt("RICERCA", i=i) for i in range(3)] + [akt("Tel ogólny", "telefon", i=9)]
        )
        typy = {t["podtyp"]: t["n"] for t in self.baza.wystepujace_typy()}
        self.assertEqual(typy, {"RICERCA": 3, "Tel ogólny": 1})

    def test_status_tematu(self):
        self.baza.ustaw_status_tematu("pustostan", "sledzony", "na odprawę")
        statusy = self.baza.status_tematow()
        self.assertEqual(statusy["pustostan"]["status"], "sledzony")
        self.assertEqual(statusy["pustostan"]["notatka"], "na odprawę")
        self.baza.ustaw_status_tematu("pustostan", "odrzucony")
        self.assertEqual(self.baza.status_tematow()["pustostan"]["status"], "odrzucony")

    def test_usuniecie_pracownika_bez_danych(self):
        self.baza.zapisz_pracownika(Pracownik(klucz="a", imie_nazwisko="A"))
        self.baza.zapisz_aktywnosci([akt("RICERCA", i=1)])
        self.baza.usun_pracownika("a")
        self.assertIsNone(self.baza.pracownik("a"))
        self.assertEqual(len(self.baza.pobierz(pracownik="a")), 1)   # dane zostają
        # osoba wraca przy najbliższej synchronizacji, bo nadal jest w danych
        self.assertEqual(self.baza.synchronizuj_pracownikow(), 1)

    def test_usuniecie_pracownika_z_danymi(self):
        self.baza.zapisz_pracownika(Pracownik(klucz="a", imie_nazwisko="A"))
        self.baza.zapisz_aktywnosci([akt("RICERCA", i=i) for i in range(3)])
        self.baza.zapisz_wskazniki("a", "miesiac", "2026-08", {"RS1": 1})
        self.baza.dopisz_pamiec("a", "cel", "test")

        licznik = self.baza.usun_pracownika("a", z_danymi=True)
        self.assertEqual(licznik["aktywnosci"], 3)
        self.assertIsNone(self.baza.pracownik("a"))
        self.assertEqual(self.baza.pobierz(pracownik="a"), [])
        self.assertEqual(self.baza.wskazniki("a", "miesiac", "2026-08"), {})
        self.assertEqual(self.baza.pamiec("a"), [])
        # tym razem nie wraca, bo danych już nie ma
        self.assertEqual(self.baza.synchronizuj_pracownikow(), 0)

    def test_usuniecie_biura_nie_rusza_pracownikow(self):
        biuro_id = self.baza.zapisz_biuro(Biuro(nazwa="Centrum"))
        self.baza.zapisz_pracownika(
            Pracownik(klucz="a", imie_nazwisko="A", biuro_id=biuro_id)
        )
        self.baza.usun_biuro(biuro_id)
        self.assertIsNotNone(self.baza.pracownik("a"))
        self.assertIsNone(self.baza.pracownik("a").biuro_id)


if __name__ == "__main__":
    unittest.main()
