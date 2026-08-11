"""Testy konfiguracji: staż z daty, usuwanie ludzi, status tematów,
mapowanie typów aktywności na wskaźniki."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

KORZEN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KORZEN / "src"))

from analityk.konfiguracja import czy_jest_klucz, wczytaj_env  # noqa: E402
from analityk.models import Activity, zbuduj_id  # noqa: E402
from analityk.org import Biuro, Pracownik  # noqa: E402
from analityk.org import ROLA_AGENT  # noqa: E402
from analityk.punktacja import (  # noqa: E402
    MAPOWANIE_DOMYSLNE,
    _reguly,
    dopasuj_kod,
    dopisz_punkty,
    licznosci_okresu,
    licznosci_z_aktywnosci,
    niezmapowane_typy,
    punkty_pracownika,
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


class TestPlikuEnv(unittest.TestCase):
    """Klucz API podaje się plikiem `.env` — przy uruchamianiu dwuklikiem
    zmienne środowiskowe systemu i tak nie działają."""

    def setUp(self):
        self.stara = os.environ.pop("ANTHROPIC_API_KEY", None)

    def tearDown(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        if self.stara is not None:
            os.environ["ANTHROPIC_API_KEY"] = self.stara

    def test_wczytuje_klucz(self):
        with tempfile.TemporaryDirectory() as katalog:
            (Path(katalog) / ".env").write_text(
                "# komentarz\nANTHROPIC_API_KEY=\"sk-ant-test\"\n")
            self.assertEqual(wczytaj_env(katalog), ["ANTHROPIC_API_KEY"])
            self.assertEqual(os.environ["ANTHROPIC_API_KEY"], "sk-ant-test")
            self.assertTrue(czy_jest_klucz())

    def test_zmienna_systemowa_ma_pierwszenstwo(self):
        os.environ["ANTHROPIC_API_KEY"] = "z-systemu"
        with tempfile.TemporaryDirectory() as katalog:
            (Path(katalog) / ".env").write_text("ANTHROPIC_API_KEY=z-pliku\n")
            wczytaj_env(katalog)
            self.assertEqual(os.environ["ANTHROPIC_API_KEY"], "z-systemu")

    def test_brak_pliku_nie_wywala(self):
        with tempfile.TemporaryDirectory() as katalog:
            self.assertEqual(wczytaj_env(katalog), [])
            self.assertFalse(czy_jest_klucz())

    def test_puste_i_zepsute_linie_pomijane(self):
        with tempfile.TemporaryDirectory() as katalog:
            (Path(katalog) / ".env").write_text(
                "\n\nbez_znaku_rownosci\nPUSTA=\nDOBRA=wartosc\n")
            self.assertEqual(wczytaj_env(katalog), ["DOBRA"])
            os.environ.pop("DOBRA", None)


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
        # telefony nie są punktowane — idą do licznika operacyjnego
        self.assertEqual(licznosci_z_aktywnosci(aktywnosci),
                         {"IM3": 5, "TEL_WYKONANE": 3})

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
            {"kanal": "bezposredni", "podtyp": "Zupełnie Nowy Typ", "n": 4},
        ]
        braki = niezmapowane_typy(typy, MAPOWANIE_DOMYSLNE)
        self.assertEqual([t["podtyp"] for t in braki], ["Zupełnie Nowy Typ"])

    def test_niezmapowane_widzi_kanal(self):
        """Reguła „ACQ + spotkanie” nie pokrywa „ACQ + telefon”."""
        typy = [{"kanal": "telefon", "podtyp": "Nieznany Typ", "n": 3},
                {"kanal": "spotkanie", "podtyp": "ACQ", "n": 5}]
        braki = niezmapowane_typy(typy, MAPOWANIE_DOMYSLNE)
        self.assertEqual([t["podtyp"] for t in braki], ["Nieznany Typ"])


class TestRegulyZWarunkiem(unittest.TestCase):
    """ACQ idzie na NT15 albo NT16 zależnie od tego, czy wiersz mówi o wynajmie."""

    def test_acq_sprzedaz_kontra_wynajem(self):
        sprzedaz = akt("ACQ", "spotkanie", 1)
        sprzedaz.powiazanie = "Mieszkanie sprzedaż Dworcowa 7"
        wynajem = akt("ACQ", "spotkanie", 2)
        wynajem.powiazanie = "Mieszkanie wynajem Dworcowa 9"
        licznosci = licznosci_z_aktywnosci([sprzedaz, wynajem])
        self.assertEqual(licznosci, {"NT15": 1, "NT16": 1})

    def test_regula_z_warunkiem_ma_pierwszenstwo(self):
        mapowanie = {
            "acq": {"kod": "NT15", "warunek": ""},
            "acq|wynajem": {"kod": "NT16", "warunek": "wynajem"},
        }
        a = akt("ACQ", i=3)
        a.notatka = "Umowa na wynajem, klient zdecydowany"
        self.assertEqual(licznosci_z_aktywnosci([a], mapowanie), {"NT16": 1})

    def test_warunek_szukany_w_calym_wierszu(self):
        """Nie wiemy, w której kolumnie CRM trzyma rozróżnienie — szukamy wszędzie."""
        mapowanie = {"acq": {"kod": "NT16", "warunek": "wynajem"}}
        w_notatce = akt("ACQ", i=4)
        w_notatce.notatka = "klient pyta o wynajem"
        w_powiazaniu = akt("ACQ", i=5)
        w_powiazaniu.powiazanie = "wynajem Kolejowa 4"
        self.assertEqual(licznosci_z_aktywnosci([w_notatce, w_powiazaniu], mapowanie),
                         {"NT16": 2})

    def test_ven_i_vm_z_prawdziwymi_nazwami(self):
        """Wartości dokładnie takie, jak w kolumnach eksportu."""
        aktywnosci = [
            akt("VEN", "spotkanie", 1),
            akt("Vendita telefoniczna", "spotkanie", 2),
            akt("V.M.", "spotkanie", 3),
            akt("V.M.", "telefon", 4),
        ]
        self.assertEqual(licznosci_z_aktywnosci(aktywnosci), {"IN21": 2, "IN18": 2})

    def test_kanal_odroznia_spotkanie_od_telefonu(self):
        """„Spotkanie + ACQ” to 100 pkt, „Telefon + Tel na ACQ” to sam telefon."""
        spotkanie = akt("ACQ", "spotkanie", 1)
        telefon = akt("Tel na ACQ", "telefon", 2)
        self.assertEqual(licznosci_z_aktywnosci([spotkanie, telefon]),
                         {"NT15": 1, "TEL_WYKONANE": 1})

    def test_polskie_znaki_w_nazwach_typow(self):
        """„Telefon ogólny” musi trafić w regułę zapisaną bez ogonków."""
        self.assertEqual(
            licznosci_z_aktywnosci([akt("Telefon ogólny", "telefon", 1)]),
            {"TEL_WYKONANE": 1},
        )

    def test_wszystkie_typy_z_eksportu_maja_regule(self):
        """Pełna lista par (Modyfikuj kontakt, typ) z prawdziwego CRM.

        Ten test pilnuje, żeby zmiana reguł nie wysypała po cichu żadnej
        kombinacji, która realnie występuje w eksportach.
        """
        oczekiwane = {
            ("bezposredni", "RICERCA"): "IM3",
            ("telefon", "RICERCA"): "IM3",
            ("bezposredni", "ACQ"): "NT15",
            ("spotkanie", "ACQ"): "NT15",
            ("spotkanie", "VEN"): "IN21",
            ("spotkanie", "Vendita telefoniczna"): "IN21",
            ("spotkanie", "V.M."): "IN18",
            ("telefon", "V.M."): "IN18",
            ("telefon", "Aktualizacja richiesty"): "R6",
            ("spotkanie", "Cont"): "CONT_SPOTKANIA",
            ("telefon", "Oferta"): "OFERTY",
            ("telefon", "Tel na ACQ"): "TEL_WYKONANE",
            ("telefon", "Tel ogólny"): "TEL_WYKONANE",
            ("telefon", "Telefon ogólny"): "TEL_WYKONANE",
            ("telefon", "Telefon z bazy danych"): "TEL_WYKONANE",
            ("telefon", "Telefon z propozycją kupna"): "TEL_WYKONANE",
            ("telefon", "Telefon z propozycją wynajmu"): "TEL_WYKONANE",
            ("telefon", "Telefon z propozycją dzierżawy"): "TEL_WYKONANE",
            ("spotkanie", "Ogólny"): "TEL_WYKONANE",
            ("spotkanie", "personale"): "POMIJANE",
        }
        reguly = _reguly(MAPOWANIE_DOMYSLNE)
        for (kanal, typ), kod in oczekiwane.items():
            with self.subTest(kanal=kanal, typ=typ):
                self.assertEqual(dopasuj_kod(akt(typ, kanal, 1), reguly), kod)

    def test_typy_bez_reguly_zostaja_nieprzypisane(self):
        """Nie zgadujemy — typ, którego nikt nie opisał, czeka na decyzję."""
        self.assertEqual(
            licznosci_z_aktywnosci([akt("Zupełnie Nowy Typ", "spotkanie", 1)]), {}
        )

    def test_cont_i_aktualizacja(self):
        aktywnosci = [akt("Cont", "spotkanie", 1),
                      akt("Aktualizacja richiesty", "telefon", 2)]
        self.assertEqual(licznosci_z_aktywnosci(aktywnosci),
                         {"CONT_SPOTKANIA": 1, "R6": 1})

    def test_pomijane_nie_wchodza_do_licznikow(self):
        """„personale” jest świadomie pomijane — to nie to samo co brak reguły."""
        aktywnosci = [akt("personale", "spotkanie", 1), akt("RICERCA", "bezposredni", 2)]
        self.assertEqual(licznosci_z_aktywnosci(aktywnosci), {"IM3": 1})

    def test_pomijany_typ_nie_jest_zglaszany_jako_brak(self):
        typy = [{"kanal": "spotkanie", "podtyp": "personale", "n": 3}]
        self.assertEqual(niezmapowane_typy(typy, MAPOWANIE_DOMYSLNE), [])


class TestLicznikiOperacyjne(unittest.TestCase):
    """Telefony są pracą, którą chcemy widzieć — ale klasyfikacja ich nie punktuje."""

    def test_telefony_nie_daja_punktow(self):
        aktywnosci = [
            akt("Tel ogólny", "telefon", 1),
            akt("Telefon z propozycją dzierżawy", "telefon", 2),
            akt("Tel z bazy danych", "telefon", 3),
        ]
        licznosci = licznosci_z_aktywnosci(aktywnosci)
        self.assertEqual(licznosci, {"TEL_WYKONANE": 3})

        wynik = punkty_pracownika(licznosci, ROLA_AGENT)
        self.assertEqual(wynik["punkty_razem"], 0)
        self.assertNotIn("TEL_WYKONANE", {p["kod"] for p in wynik["pozycje"]})

    def test_oferta_liczona_bez_punktow(self):
        self.assertEqual(licznosci_z_aktywnosci([akt("Oferta", i=1)]), {"OFERTY": 1})

    def test_liczniki_trafiaja_do_metryk(self):
        with tempfile.TemporaryDirectory() as katalog:
            baza = Baza(Path(katalog) / "t.db")
            baza.zapisz_aktywnosci([akt("Tel ogólny", "telefon", i) for i in range(4)])
            p = Pracownik(klucz="a", imie_nazwisko="A")
            baza.zapisz_pracownika(p)
            m = dopisz_punkty(baza, p, "dzien", "2026-08-10",
                              baza.pobierz(pracownik="a"), {})
            self.assertEqual(m["liczniki_operacyjne"]["TEL_WYKONANE"]["ile"], 4)
            self.assertEqual(m["punkty_razem"], 0)
            baza.zamknij()


class TestKonfiguracjaWBazie(unittest.TestCase):
    def setUp(self):
        self.katalog = tempfile.TemporaryDirectory()
        self.baza = Baza(Path(self.katalog.name) / "t.db")

    def tearDown(self):
        self.baza.zamknij()
        self.katalog.cleanup()

    def test_wlasne_mapowanie_nadpisuje_domyslne(self):
        self.baza.zapisz_aktywnosci([akt("Nietypowa akcja", i=i) for i in range(4)])
        self.assertEqual(licznosci_okresu(self.baza, "a", "dzien", "2026-08-10"), {})

        self.baza.ustaw_mapowanie("nietypowa akcja", "NO10", "spotkanie KIRON")
        self.assertEqual(
            licznosci_okresu(self.baza, "a", "dzien", "2026-08-10"), {"NO10": 4}
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

    def test_ocena_pojedynczej_notatki(self):
        self.baza.ustaw_ocene_notatki("akt-1", "zaakceptowana", "oddzwonić 20.08")
        oceny = self.baza.oceny_notatek()
        self.assertEqual(oceny["akt-1"]["status"], "zaakceptowana")
        self.assertEqual(oceny["akt-1"]["komentarz"], "oddzwonić 20.08")
        self.assertEqual(list(self.baza.oceny_notatek("odrzucona")), [])

    def test_zmiana_statusu_nie_gubi_komentarza(self):
        """Przyciski bez pola komentarza mają go zostawić w spokoju…"""
        self.baza.ustaw_ocene_notatki("akt-1", "zaakceptowana", "oddzwonić")
        self.baza.ustaw_ocene_notatki("akt-1", "nowa")
        self.assertEqual(self.baza.oceny_notatek()["akt-1"]["komentarz"], "oddzwonić")

    def test_pusty_komentarz_da_sie_skasowac(self):
        """…ale wyczyszczone pole formularza ma naprawdę czyścić."""
        self.baza.ustaw_ocene_notatki("akt-1", "zaakceptowana", "oddzwonić")
        self.baza.ustaw_ocene_notatki("akt-1", "zaakceptowana", "")
        self.assertEqual(self.baza.oceny_notatek()["akt-1"]["komentarz"], "")

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
