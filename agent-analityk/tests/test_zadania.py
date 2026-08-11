"""Testy wyłapywania zadań, terminów i tematów z notatek."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

KORZEN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KORZEN / "src"))

from analityk.classify import sklasyfikuj  # noqa: E402
from analityk.models import Activity, zbuduj_id  # noqa: E402
from analityk.store import Baza  # noqa: E402
from analityk.zadania import (  # noqa: E402
    STATUS_ZROBIONE,
    ZAD_CZEKAM,
    ZAD_KONTAKT,
    ZAD_ODDZWONIC,
    ZAD_SPOTKANIE,
    ZAD_WYSLAC,
    rozwiaz_termin,
    tematy,
    wykryj_w_aktywnosciach,
    wykryj_zadania,
)

PONIEDZIALEK = date(2026, 8, 10)


def akt(notatka: str, dzien: date = PONIEDZIALEK, budynek: str = "Dworcowa 7",
        lokal: str = "1") -> Activity:
    d = datetime(dzien.year, dzien.month, dzien.day, 11, 0)
    return Activity(
        id=zbuduj_id("j", d, notatka, budynek + lokal), pracownik="j",
        pracownik_nazwa="J", data=d, kanal="bezposredni", notatka=notatka,
        budynek=budynek, lokal=lokal,
    )


class TestTerminy(unittest.TestCase):
    def test_terminy_wzgledne(self):
        przypadki = {
            "zadzwonić za tydzień": "2026-08-17",
            "za 2 tygodnie": "2026-08-24",
            "za trzy dni": "2026-08-13",
            "jutro": "2026-08-11",
            "pojutrze": "2026-08-12",
            "za miesiąc": "2026-09-09",
            "za rok": "2027-08-10",
        }
        for tekst, oczekiwana in przypadki.items():
            with self.subTest(tekst=tekst):
                self.assertEqual(rozwiaz_termin(tekst, PONIEDZIALEK)[0], oczekiwana)

    def test_tydzien_nie_jest_mylony_z_dniem(self):
        """„tydzień” zawiera w sobie „dzień” — regresja z pierwszej wersji."""
        self.assertEqual(rozwiaz_termin("za tydzień", PONIEDZIALEK)[0], "2026-08-17")

    def test_dni_tygodnia(self):
        self.assertEqual(rozwiaz_termin("w czwartek", PONIEDZIALEK)[0], "2026-08-13")
        self.assertEqual(rozwiaz_termin("na piątek", PONIEDZIALEK)[0], "2026-08-14")
        # ten sam dzień tygodnia co dziś => za tydzień, nie dziś
        self.assertEqual(rozwiaz_termin("w poniedziałek", PONIEDZIALEK)[0], "2026-08-17")

    def test_koniec_miesiaca(self):
        self.assertEqual(rozwiaz_termin("pod koniec miesiąca", PONIEDZIALEK)[0],
                         "2026-08-31")
        self.assertEqual(rozwiaz_termin("pod koniec miesiąca", date(2026, 12, 5))[0],
                         "2026-12-31")

    def test_konkretna_data(self):
        self.assertEqual(rozwiaz_termin("umówione na 15.09", PONIEDZIALEK)[0], "2026-09-15")
        # data, która w tym roku już minęła, wskazuje na przyszły rok
        self.assertEqual(rozwiaz_termin("15.03", PONIEDZIALEK)[0], "2027-03-15")

    def test_miesiac_przechodzi_na_kolejny_rok(self):
        self.assertEqual(rozwiaz_termin("we wrześniu", PONIEDZIALEK)[0], "2026-09-01")
        self.assertEqual(rozwiaz_termin("w marcu", PONIEDZIALEK)[0], "2027-03-01")

    def test_mglisty_termin_bez_daty(self):
        data, tekst = rozwiaz_termin("wrócić po świętach", PONIEDZIALEK)
        self.assertEqual(data, "")
        self.assertEqual(tekst, "po swietach")

    def test_brak_terminu(self):
        self.assertEqual(rozwiaz_termin("Pani nie chce sprzedawać", PONIEDZIALEK),
                         ("", ""))

    def test_termin_liczony_od_dnia_kontaktu(self):
        """Notatka sprzed miesiąca nie może dostać dzisiejszej daty."""
        stara = rozwiaz_termin("za tydzień", date(2026, 6, 1))[0]
        self.assertEqual(stara, "2026-06-08")


class TestWykrywanieZadan(unittest.TestCase):
    def _typy(self, notatka: str) -> set[str]:
        return {z.typ for z in wykryj_zadania(akt(notatka))}

    def test_telefon_z_terminem(self):
        zadania = wykryj_zadania(akt("Pani prosi zadzwonić w czwartek"))
        self.assertEqual(len(zadania), 1)
        z = zadania[0]
        self.assertEqual(z.typ, ZAD_ODDZWONIC)
        self.assertEqual(z.termin, "2026-08-13")
        self.assertEqual(z.strona, "agent")

    def test_kontakt_do_osoby(self):
        zadania = wykryj_zadania(akt("Zostawiła numer do siostry, ona jest właścicielką"))
        z = next(z for z in zadania if z.typ == ZAD_KONTAKT)
        self.assertIn("siostry", z.tresc)

    def test_numer_telefonu_lapany(self):
        self.assertIn(ZAD_KONTAKT, self._typy("Podał 601 202 303, prosi o kontakt"))

    def test_ma_wyslac_to_zadanie_klienta(self):
        """„Ma wysłać zdjęcia” = piłka po stronie klienta, nie nasze zadanie."""
        zadania = wykryj_zadania(akt("Pan chce sprzedać, ma wysłać zdjęcia"))
        typy = {z.typ for z in zadania}
        self.assertIn(ZAD_CZEKAM, typy)
        self.assertNotIn(ZAD_WYSLAC, typy)
        self.assertEqual(next(z for z in zadania if z.typ == ZAD_CZEKAM).strona, "klient")

    def test_mam_wyslac_to_zadanie_agenta(self):
        zadania = wykryj_zadania(akt("Prosi o ofertę mailem, mam wysłać do jutra"))
        z = next(z for z in zadania if z.typ == ZAD_WYSLAC)
        self.assertEqual(z.strona, "agent")
        self.assertEqual(z.termin, "2026-08-11")
        self.assertIn("ofertę", z.tresc)

    def test_spotkanie(self):
        z = wykryj_zadania(akt("Umówione spotkanie na wycenę w piątek"))[0]
        self.assertEqual(z.typ, ZAD_SPOTKANIE)
        self.assertEqual(z.termin, "2026-08-14")

    def test_odmowa_nie_tworzy_zadania(self):
        self.assertEqual(wykryj_zadania(akt("Pani nie chce sprzedawać, nic nie słyszała")), [])

    def test_krotka_notatka_pomijana(self):
        self.assertEqual(wykryj_zadania(akt("Najemcy")), [])

    def test_przypomnienie_nie_dubluje_konkretu(self):
        """Gdy jest konkretne zadanie, miękkie „wrócić do tematu” odpada."""
        zadania = wykryj_zadania(akt("Przemyśli sprawę, prosi zadzwonić za tydzień"))
        self.assertEqual({z.typ for z in zadania}, {ZAD_ODDZWONIC})

    def test_adres_przenoszony_do_zadania(self):
        z = wykryj_zadania(akt("Zadzwonić jutro", budynek="Kolejowa 4", lokal="12"))[0]
        self.assertEqual(z.adres, "Kolejowa 4 / 12")

    def test_przeterminowanie(self):
        z = wykryj_zadania(akt("Zadzwonić jutro"))[0]
        self.assertTrue(z.przeterminowane(date(2026, 9, 1)))
        self.assertFalse(z.przeterminowane(date(2026, 8, 10)))
        z.status = STATUS_ZROBIONE
        self.assertFalse(z.przeterminowane(date(2026, 9, 1)))


class TestZapisZadan(unittest.TestCase):
    def setUp(self):
        self.katalog = tempfile.TemporaryDirectory()
        self.baza = Baza(Path(self.katalog.name) / "t.db")

    def tearDown(self):
        self.baza.zamknij()
        self.katalog.cleanup()

    def test_odhaczenie_przezywa_ponowne_wykrycie(self):
        aktywnosci = [akt("Prosi zadzwonić za tydzień")]
        zadania = wykryj_w_aktywnosciach(aktywnosci)
        self.assertEqual(self.baza.zapisz_zadania(zadania), (1, 0))

        self.baza.ustaw_status_zadania(zadania[0].id, STATUS_ZROBIONE)
        # ponowne wczytanie tego samego pliku
        self.assertEqual(self.baza.zapisz_zadania(wykryj_w_aktywnosciach(aktywnosci)), (0, 1))
        self.assertEqual(self.baza.zadania(status="otwarte"), [])
        self.assertEqual(len(self.baza.zadania(status=STATUS_ZROBIONE)), 1)

    def test_sortowanie_po_terminie(self):
        self.baza.zapisz_zadania(wykryj_w_aktywnosciach([
            akt("Zadzwonić za miesiąc", lokal="1"),
            akt("Zadzwonić jutro", lokal="2"),
            akt("Wrócić po świętach", lokal="3"),
        ]))
        terminy = [z.termin for z in self.baza.zadania()]
        self.assertEqual(terminy[0], "2026-08-11")          # najbliższy pierwszy
        self.assertEqual(terminy[-1], "")                    # bez terminu na końcu

    def test_filtr_po_stronie(self):
        self.baza.zapisz_zadania(wykryj_w_aktywnosciach([
            akt("Mam zadzwonić jutro", lokal="1"),
            akt("Klient ma się odezwać w przyszłym tygodniu", lokal="2"),
        ]))
        self.assertTrue(all(z.strona == "agent" for z in self.baza.zadania(strona="agent")))
        self.assertTrue(all(z.strona == "klient" for z in self.baza.zadania(strona="klient")))


class TestTematy(unittest.TestCase):
    def test_grupowanie_powtarzajacych_sie_watkow(self):
        aktywnosci = sklasyfikuj([
            akt("Wygląda na puste, listy w skrzynkach", lokal="1"),
            akt("Wygląda na puste, listy w skrzynkach", lokal="2"),
            akt("Pan nie zapłaci prowizji, tylko ze strony kupującego", lokal="3"),
            akt("Pani bardzo miła, ale nie chce", lokal="4"),
        ])
        lista = tematy(aktywnosci, min_wystapien=2)
        nazwy = [t["temat"] for t in lista]
        self.assertIn("pustostan", nazwy)
        pustostany = next(t for t in lista if t["temat"] == "pustostan")
        self.assertEqual(pustostany["ile"], 2)
        self.assertEqual(pustostany["udzial_proc"], 50.0)
        self.assertTrue(pustostany["przyklady"])

    def test_prog_wystapien(self):
        aktywnosci = sklasyfikuj([akt("Wygląda na puste, listy w skrzynkach")])
        self.assertEqual(tematy(aktywnosci, min_wystapien=2), [])
        self.assertTrue(tematy(aktywnosci, min_wystapien=1))


if __name__ == "__main__":
    unittest.main()
