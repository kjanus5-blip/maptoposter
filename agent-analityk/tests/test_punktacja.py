"""Testy oficjalnej punktacji sieci.

Te liczby wpływają na rankingi i premie, więc każda stawka i każdy próg
bonusu ma tu swój test.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

KORZEN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KORZEN / "src"))

from analityk.models import Activity, zbuduj_id  # noqa: E402
from analityk.org import (  # noqa: E402
    ROLA_AGENT,
    ROLA_KOORDYNATOR,
    Biuro,
    Pracownik,
)
from analityk.punktacja import (  # noqa: E402
    BONUS_BIURA_ZA_OSOBE,
    licznosci_okresu,
    licznosci_z_aktywnosci,
    punkty_biura,
    punkty_pracownika,
    punkty_zespolu,
    wskazniki_dla_roli,
)
from analityk.store import Baza  # noqa: E402


def akt(pracownik: str, podtyp: str, kanal: str = "bezposredni",
        godzina: int = 10) -> Activity:
    d = datetime(2026, 8, 10, godzina, 0)
    return Activity(
        id=zbuduj_id(pracownik, d, podtyp, str(godzina) + kanal),
        pracownik=pracownik, pracownik_nazwa=pracownik.title(), data=d,
        kanal=kanal, podtyp=podtyp, notatka="x" * 30, wynik="odmowa",
    )


class TestStawki(unittest.TestCase):
    def test_stawki_agenta_zgodne_z_tabela(self):
        oczekiwane = {
            "IM3": 4, "NT11": 30, "NT17": 10, "NT15": 100, "NT16": 12.5,
            "IN1": 500, "IN2": 75, "IN18": 30, "IN19": 50, "RS1": 2000,
            "RS2": 250, "R12": 10, "NO10": 5,
        }
        faktyczne = {w.kod: w.punkty for w in wskazniki_dla_roli(ROLA_AGENT)}
        self.assertEqual(faktyczne, oczekiwane)

    def test_stawki_koordynatorki_zgodne_z_tabela(self):
        oczekiwane = {"R4": 2, "R6": 2, "REP17": 20, "IN21": 30, "NT10": 20, "NO10": 5}
        faktyczne = {w.kod: w.punkty for w in wskazniki_dla_roli(ROLA_KOORDYNATOR)}
        self.assertEqual(faktyczne, oczekiwane)

    def test_suma_punktow_agenta(self):
        w = punkty_pracownika({"IM3": 300, "NT11": 5, "IN1": 2, "RS1": 1}, ROLA_AGENT)
        # 300*4 + 5*30 + 2*500 + 1*2000
        self.assertEqual(w["punkty_za_aktywnosc"], 4350)

    def test_suma_punktow_koordynatorki(self):
        w = punkty_pracownika({"R4": 420, "REP17": 14, "IN21": 9}, ROLA_KOORDYNATOR)
        # 420*2 + 14*20 + 9*30
        self.assertEqual(w["punkty_za_aktywnosc"], 1390)

    def test_rola_ogranicza_wskazniki(self):
        """Koordynatorce nie doliczamy sprzedaży agenta i odwrotnie."""
        w = punkty_pracownika({"RS1": 10}, ROLA_KOORDYNATOR)
        self.assertEqual(w["punkty_za_aktywnosc"], 0)
        kody = {p["kod"] for p in w["pozycje"]}
        self.assertNotIn("RS1", kody)
        self.assertNotIn("R4", {p["kod"] for p in punkty_pracownika({}, ROLA_AGENT)["pozycje"]})


class TestBonusy(unittest.TestCase):
    def test_prog_jest_ostry(self):
        """„>70%” znaczy powyżej, nie „co najmniej”."""
        rowno = punkty_pracownika({"NT32": 7, "NT13": 10}, ROLA_AGENT)
        powyzej = punkty_pracownika({"NT32": 71, "NT13": 100}, ROLA_AGENT)
        self.assertEqual(rowno["punkty_bonusowe"], 0)
        self.assertEqual(powyzej["punkty_bonusowe"], 5000)

    def test_bonus_jakosci_sprzedazy(self):
        w = punkty_pracownika({"RS1": 6, "IN1": 10}, ROLA_AGENT)   # 60% > 50%
        self.assertTrue(next(b for b in w["bonusy"] if b["kod"] == "BON_JAKOSC")["przyznany"])

    def test_bonus_koordynatorki(self):
        w = punkty_pracownika(
            {"ZL_PRZEANALIZOWANE": 96, "ZL_WSZYSTKIE": 100}, ROLA_KOORDYNATOR
        )
        self.assertEqual(w["punkty_bonusowe"], 5000)

    def test_brak_mianownika_nie_dzieli_przez_zero(self):
        w = punkty_pracownika({"NT32": 5}, ROLA_AGENT)
        bonus = next(b for b in w["bonusy"] if b["kod"] == "BON_NOTIZIA")
        self.assertTrue(bonus["brak_danych"])
        self.assertIsNone(bonus["udzial_proc"])
        self.assertEqual(bonus["punkty"], 0)


class TestBrakDanych(unittest.TestCase):
    def test_brakujacy_wskaznik_jest_oznaczony(self):
        w = punkty_pracownika({"IM3": 100}, ROLA_AGENT)
        pozycja_im3 = next(p for p in w["pozycje"] if p["kod"] == "IM3")
        pozycja_rs1 = next(p for p in w["pozycje"] if p["kod"] == "RS1")
        self.assertFalse(pozycja_im3["brak_danych"])
        self.assertTrue(pozycja_rs1["brak_danych"])
        self.assertIn("RS1", w["wskazniki_bez_danych"])
        self.assertLess(w["kompletnosc_proc"], 100)

    def test_zero_to_nie_to_samo_co_brak(self):
        z_zerem = punkty_pracownika({"RS1": 0}, ROLA_AGENT)
        bez = punkty_pracownika({}, ROLA_AGENT)
        self.assertNotIn("RS1", z_zerem["wskazniki_bez_danych"])
        self.assertIn("RS1", bez["wskazniki_bez_danych"])
        self.assertEqual(z_zerem["punkty_razem"], bez["punkty_razem"])


class TestLiczenieZAktywnosci(unittest.TestCase):
    def test_im3_z_akcji_ricerca(self):
        aktywnosci = [akt("a", "RICERCA", godzina=g) for g in range(9, 14)]
        aktywnosci.append(akt("a", "Tel ogólny", "telefon", 15))
        licznosci = licznosci_z_aktywnosci(aktywnosci)
        self.assertEqual(licznosci["IM3"], 5)      # tylko RICERCA
        self.assertNotIn("R4", licznosci)

    def test_r4_z_telefonow_z_propozycja(self):
        aktywnosci = [akt("a", "Telefon z propozycją dzierżawy", "telefon", g)
                      for g in range(9, 12)]
        self.assertEqual(licznosci_z_aktywnosci(aktywnosci)["R4"], 3)

    def test_brak_ricerki_to_brak_wpisu_a_nie_zero(self):
        licznosci = licznosci_z_aktywnosci([akt("a", "Tel ogólny", "telefon")])
        self.assertNotIn("IM3", licznosci)


class TestIntegracjaZBaza(unittest.TestCase):
    def setUp(self):
        self.katalog = tempfile.TemporaryDirectory()
        self.baza = Baza(Path(self.katalog.name) / "t.db")

    def tearDown(self):
        self.baza.zamknij()
        self.katalog.cleanup()

    def test_wpis_reczny_wygrywa_z_wyliczonym(self):
        aktywnosci = [akt("a", "RICERCA", godzina=g) for g in range(9, 14)]
        self.baza.zapisz_aktywnosci(aktywnosci)
        licznosci = licznosci_okresu(self.baza, "a", "dzien", "2026-08-10", aktywnosci)
        self.assertEqual(licznosci["IM3"], 5)

        self.baza.zapisz_wskazniki("a", "dzien", "2026-08-10", {"IM3": 42})
        licznosci = licznosci_okresu(self.baza, "a", "dzien", "2026-08-10", aktywnosci)
        self.assertEqual(licznosci["IM3"], 42)

    def test_punkty_biura_sumuja_zespol(self):
        biuro_id = self.baza.zapisz_biuro(Biuro(nazwa="Centrum"))
        zespol = []
        for klucz, rola in (("a", ROLA_AGENT), ("k", ROLA_KOORDYNATOR)):
            p = Pracownik(klucz=klucz, imie_nazwisko=klucz.upper(),
                          biuro_id=biuro_id, rola=rola)
            self.baza.zapisz_pracownika(p)
            zespol.append(p)
        self.baza.zapisz_wskazniki("a", "miesiac", "2026-08", {"RS1": 1})
        self.baza.zapisz_wskazniki("k", "miesiac", "2026-08", {"R4": 100})

        wynik = punkty_zespolu(self.baza, zespol, "miesiac", "2026-08",
                               "2026-08-01", "2026-08-31")
        # 1*2000 + 100*2 = 2200 za aktywność, plus 2 osoby * bonus zespołowy
        self.assertEqual(wynik["punkty_za_aktywnosc"], 2200)
        self.assertEqual(wynik["punkty_bonusowe"], 2 * BONUS_BIURA_ZA_OSOBE)

    def test_klasyfikacja_biura_laczy_role(self):
        """Biuro punktuje wskaźniki agentów i koordynatorek w jednej tabeli."""
        wynik = punkty_biura({"RS1": 1, "R4": 10}, liczba_osob=0)
        kody = {p["kod"] for p in wynik["pozycje"]}
        self.assertIn("RS1", kody)
        self.assertIn("R4", kody)
        self.assertEqual(wynik["punkty_za_aktywnosc"], 2000 + 20)

    def test_bonus_zespolowy_jest_oznaczony_do_potwierdzenia(self):
        wynik = punkty_biura({}, liczba_osob=3)
        zespolowy = next(b for b in wynik["bonusy"] if b["kod"] == "BON_ZESPOL")
        self.assertTrue(zespolowy.get("do_potwierdzenia"))
        self.assertEqual(zespolowy["punkty"], 3 * BONUS_BIURA_ZA_OSOBE)


if __name__ == "__main__":
    unittest.main()
