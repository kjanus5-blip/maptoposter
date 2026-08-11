"""Testy jednostkowe: python -m unittest discover -s tests"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

KORZEN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KORZEN / "src"))

from analityk.classify import sklasyfikuj_notatke  # noqa: E402
from analityk.metrics import (  # noqa: E402
    dni_robocze,
    klucz_okresu,
    podsumowanie,
    poprzedni_okres,
    zakres_okresu,
)
from analityk.models import Activity, klucz_pracownika, rozbij_adres, zbuduj_id  # noqa: E402
from analityk.store import Baza  # noqa: E402

PRZYKLAD_PDF = KORZEN / "przyklady" / "analiza_dzialan_2026-08-10.pdf"
PRZYKLAD_CSV = KORZEN / "przyklady" / "przyklad_eksport_csv.csv"


class TestOkresy(unittest.TestCase):
    def test_klucze(self):
        d = date(2026, 8, 10)  # poniedziałek, 33. tydzień
        self.assertEqual(klucz_okresu(d, "dzien"), "2026-08-10")
        self.assertEqual(klucz_okresu(d, "tydzien"), "2026-W33")
        self.assertEqual(klucz_okresu(d, "miesiac"), "2026-08")
        self.assertEqual(klucz_okresu(d, "kwartal"), "2026-Q3")
        self.assertEqual(klucz_okresu(d, "rok"), "2026")

    def test_zakresy(self):
        self.assertEqual(zakres_okresu("2026-W33", "tydzien"), ("2026-08-10", "2026-08-16"))
        self.assertEqual(zakres_okresu("2026-02", "miesiac"), ("2026-02-01", "2026-02-28"))
        self.assertEqual(zakres_okresu("2026-Q4", "kwartal"), ("2026-10-01", "2026-12-31"))
        self.assertEqual(zakres_okresu("2026", "rok"), ("2026-01-01", "2026-12-31"))

    def test_poprzedni_okres_przez_granice_roku(self):
        self.assertEqual(poprzedni_okres("2026-01", "miesiac"), "2025-12")
        self.assertEqual(poprzedni_okres("2026-Q1", "kwartal"), "2025-Q4")
        self.assertEqual(poprzedni_okres("2026", "rok"), "2025")
        self.assertEqual(poprzedni_okres("2026-08-10", "dzien"), "2026-08-09")

    def test_dni_robocze(self):
        # 10–16.08.2026 to pełny tydzień: 6 dni roboczych z sobotą, 5 bez.
        od, do = date(2026, 8, 10), date(2026, 8, 16)
        self.assertEqual(dni_robocze(od, do), 6)
        self.assertEqual(dni_robocze(od, do, sobota_pracuje=False), 5)
        self.assertEqual(dni_robocze(do, od), 0)


class TestKlasyfikacja(unittest.TestCase):
    def test_lead_kontra_odmowa(self):
        self.assertEqual(sklasyfikuj_notatke("Pani chce sprzedać!! Mówi, że przemyśli")[0], "lead")
        self.assertEqual(sklasyfikuj_notatke("Pani nie chce sprzedać mieszkania")[0], "odmowa")

    def test_tolerancja_literowek(self):
        self.assertEqual(sklasyfikuj_notatke("Nioe chce sprzedawasć")[0], "odmowa")
        self.assertEqual(sklasyfikuj_notatke("Nie chce sporzedawać")[0], "odmowa")

    def test_odmowa_twarda_i_najemca(self):
        self.assertEqual(sklasyfikuj_notatke("rozłączyła się nie chce ze mną rozmawiać")[0],
                         "odmowa_twarda")
        self.assertEqual(sklasyfikuj_notatke("wynajmują to mieszkanie")[0], "nie_wlasciciel")

    def test_pusta_notatka(self):
        self.assertEqual(sklasyfikuj_notatke("")[0], "brak_kontaktu")

    def test_material_i_kolejny_krok(self):
        _, _, material, krok = sklasyfikuj_notatke(
            "Nie chce, ale zostawiłam wizytówkę, prosi żeby odezwać się za miesiąc"
        )
        self.assertTrue(material)
        self.assertTrue(krok)

    def test_tagi(self):
        _, tagi, _, _ = sklasyfikuj_notatke("Pan mówi, że już z nami gadał i nie zapłaci prowizji")
        self.assertIn("konkurencja", tagi)
        self.assertIn("obiekcja_prowizja", tagi)


class TestAdresy(unittest.TestCase):
    def test_z_pola_powiazania(self):
        self.assertEqual(
            rozbij_adres("IM -Dworcowa 7[10] - Im -Dworcowa 7[10]"), ("Dworcowa 7", "10")
        )

    def test_z_notatki_dla_klienta_anonimowego(self):
        budynek, _ = rozbij_adres("KlientAnonimowy", "mw1 Kniaziewicza32 - Pani nie ma mieszkania")
        self.assertEqual(budynek, "Kniaziewicza 32")

    def test_klucz_pracownika(self):
        self.assertEqual(klucz_pracownika("Julia Baranowska"), "julia_baranowska")
        self.assertEqual(klucz_pracownika("Łukasz Żółć"), "lukasz_zolc")


def akt(wynik: str, godzina: int = 12, notatka: str = "x" * 40) -> Activity:
    d = datetime(2026, 8, 10, godzina, 0)
    return Activity(
        id=zbuduj_id("t", d, wynik, notatka + str(godzina)),
        pracownik="t", pracownik_nazwa="T", data=d, kanal="bezposredni",
        notatka=notatka, wynik=wynik, budynek="Dworcowa 7", lokal=str(godzina),
    )


class TestMetryki(unittest.TestCase):
    _akt = staticmethod(akt)

    def test_pusty_okres(self):
        m = podsumowanie([], "dzien")
        self.assertTrue(m["pusty"])
        self.assertEqual(m["liczba_aktywnosci"], 0)

    def test_podstawowe_wskazniki(self):
        akt = [self._akt("lead", 9), self._akt("odmowa", 10),
               self._akt("brak_kontaktu", 11), self._akt("info_rynkowe", 17)]
        m = podsumowanie(akt, "dzien")
        self.assertEqual(m["liczba_aktywnosci"], 4)
        self.assertEqual(m["leady"], 1)
        # konwersja liczona ze wszystkich kontaktów: lead + info_rynkowe nie
        # jest sygnałem, więc do licznika wchodzi tylko lead
        self.assertEqual(m["konwersja_na_lead_proc"], 25.0)
        self.assertEqual(m["praca_w_zlotych_godzinach_proc"], 25.0)
        self.assertEqual(m["notatki_merytoryczne_proc"], 100.0)
        self.assertTrue(0 <= m["indeks_jakosci"] <= 100)

    def test_norma_proporcjonalna(self):
        akt = [self._akt("lead", g) for g in range(9, 19)]
        pelny = podsumowanie(akt, "tydzien", zakres=("2026-08-10", "2026-08-16"),
                             dzis=date(2026, 8, 16))
        czesciowy = podsumowanie(akt, "tydzien", zakres=("2026-08-10", "2026-08-16"),
                                 dzis=date(2026, 8, 10))
        # Ta sama praca rozliczona po 1 dniu wygląda lepiej niż po całym tygodniu.
        self.assertGreater(czesciowy["realizacja_normy_proc"], pelny["realizacja_normy_proc"])
        self.assertTrue(pelny["okres_zamkniety"])
        self.assertFalse(czesciowy["okres_zamkniety"])


class TestBaza(unittest.TestCase):
    def test_deduplikacja(self):
        d = datetime(2026, 8, 10, 11, 0)
        a = Activity(id=zbuduj_id("Julia", d, "X", "notatka"), pracownik="julia",
                     pracownik_nazwa="Julia", data=d, kanal="telefon", notatka="notatka")
        with tempfile.TemporaryDirectory() as tmp:
            baza = Baza(Path(tmp) / "t.db")
            self.assertEqual(baza.zapisz_aktywnosci([a]), (1, 0))
            self.assertEqual(baza.zapisz_aktywnosci([a]), (0, 1))   # ten sam plik drugi raz
            self.assertEqual(len(baza.pobierz(pracownik="julia")), 1)
            baza.dopisz_pamiec("julia", "zalecenie", "Zostawiaj wizytówki")
            self.assertEqual(baza.pamiec("julia")[0]["tresc"], "Zostawiaj wizytówki")
            baza.zamknij()


@unittest.skipUnless(PRZYKLAD_PDF.exists(), "brak pliku przykładowego")
class TestParserPDF(unittest.TestCase):
    def test_wczytuje_caly_eksport(self):
        from analityk.ingest.pdf_crm import wczytaj_pdf
        akt = wczytaj_pdf(PRZYKLAD_PDF)
        self.assertEqual(len(akt), 47)
        self.assertEqual(len({a.id for a in akt}), 47)
        self.assertTrue(all(a.budynek for a in akt))
        self.assertTrue(all(a.pracownik == "julia_baranowska" for a in akt))
        # notatka sklejona przez granicę stron
        sklejona = [a for a in akt if a.budynek == "Dworcowa 16A" and a.lokal == "9"][0]
        self.assertIn("nie zna z sąsiadami", sklejona.notatka)


@unittest.skipUnless(PRZYKLAD_CSV.exists(), "brak pliku przykładowego")
class TestParserCSV(unittest.TestCase):
    def test_wczytuje_csv_ze_srednikami(self):
        from analityk.ingest.csv_generic import wczytaj_csv
        akt = wczytaj_csv(PRZYKLAD_CSV)
        self.assertGreater(len(akt), 20)
        self.assertTrue(all(a.pracownik == "marek_nowak" for a in akt))
        self.assertTrue(all(a.data.year == 2026 for a in akt))


class TestRaporty(unittest.TestCase):
    """Raport ma być kompletny i bezpieczny — w obu formatach."""

    def _dane(self, wyniki=("lead", "odmowa", "info_rynkowe", "sygnal")):
        from analityk.metrics import podsumowanie
        from analityk.org import Pracownik
        lista = [akt(w, 9 + i) for i, w in enumerate(wyniki)]
        m = podsumowanie(lista, "dzien", zakres=("2026-08-10", "2026-08-10"))
        return Pracownik(klucz="t", imie_nazwisko="Test Testowy"), m, lista

    def test_numeracja_sekcji_jest_ciagla(self):
        """Sekcje szły kiedyś 5, 6, 5b, 6b, 7 — po dołożeniu punktacji."""
        import re
        from analityk.report import zbuduj_raport
        p, m, akt = self._dane()
        numery = [int(x) for x in re.findall(r"^## (\d+)\.", zbuduj_raport(
            p, "dzien", "2026-08-10", m, akt), re.M)]
        self.assertEqual(numery, list(range(1, len(numery) + 1)))

    def test_markdown_ma_skrot_na_gorze(self):
        from analityk.report import zbuduj_raport
        p, m, akt = self._dane()
        tresc = zbuduj_raport(p, "dzien", "2026-08-10", m, akt)
        self.assertIn("**W skrócie**", tresc)
        self.assertIn("█", tresc)                      # paski postępu

    def test_html_jest_samodzielny(self):
        """Raport ma działać po wysłaniu mailem — bez internetu i bez CDN."""
        from analityk.raport_html import zbuduj_raport_html
        p, m, akt = self._dane()
        html = zbuduj_raport_html(p, "dzien", "2026-08-10", m, akt)
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn("<style>", html)
        self.assertNotIn("<script", html)      # jedyny JS to onclick druku
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)

    def test_html_ma_przycisk_zapisu_do_pdf(self):
        """Bez niego zapis do PDF wymaga szukania w menu przeglądarki."""
        from analityk.raport_html import zbuduj_raport_html
        p, m, akt = self._dane()
        html = zbuduj_raport_html(p, "dzien", "2026-08-10", m, akt)
        self.assertIn("window.print()", html)
        # pasek nie może wyjść na wydruku, bo trafiłby do PDF-a
        self.assertIn(".pasek-druku { display: none; }", html)

    def test_html_escapuje_notatki(self):
        """Notatka z CRM to tekst od użytkownika — nie może wstrzyknąć HTML-a."""
        from analityk.metrics import podsumowanie
        from analityk.org import Pracownik
        from analityk.raport_html import zbuduj_raport_html
        a = akt("lead", notatka="<script>alert(1)</script> " + "x" * 30)
        m = podsumowanie([a], "dzien", zakres=("2026-08-10", "2026-08-10"))
        html = zbuduj_raport_html(Pracownik(klucz="t", imie_nazwisko="T"),
                                  "dzien", "2026-08-10", m, [a])
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)

    def test_html_znosi_pusty_okres(self):
        from analityk.metrics import podsumowanie
        from analityk.org import Pracownik
        from analityk.raport_html import zbuduj_raport_html
        html = zbuduj_raport_html(Pracownik(klucz="t", imie_nazwisko="T"),
                                  "dzien", "2026-08-10", podsumowanie([], "dzien"), [])
        self.assertIn("Brak jakiejkolwiek aktywności", html)
        self.assertTrue(html.rstrip().endswith("</html>"))


if __name__ == "__main__":
    unittest.main()
