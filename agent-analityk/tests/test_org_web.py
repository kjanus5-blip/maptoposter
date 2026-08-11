"""Testy struktury organizacji, porównań i panelu WWW.

    python -m unittest discover -s tests
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

KORZEN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KORZEN / "src"))

from analityk.benchmark import (  # noqa: E402
    grupy_porownawcze,
    metryki_biura,
    ocena_pozycji,
    opis_dla_modelu,
    percentyl,
    porownaj_z_grupa,
    ranking_biur,
    statystyki,
    suma_norm,
)
from analityk.metrics import etykieta_okresu, nastepny_okres, podsumowanie  # noqa: E402
from analityk.models import Activity, zbuduj_id  # noqa: E402
from analityk.org import (  # noqa: E402
    ROLA_AGENT,
    ROLA_KIEROWNIK,
    ROLA_KOORDYNATOR,
    Biuro,
    Pracownik,
    normy_dla_roli,
)
from analityk.store import Baza  # noqa: E402


def akt(pracownik: str, dzien: str, godzina: int, wynik: str = "odmowa",
        notatka: str = "x" * 40) -> Activity:
    d = datetime.fromisoformat(f"{dzien}T{godzina:02d}:00")
    return Activity(
        id=zbuduj_id(pracownik, d, wynik, notatka + str(godzina)),
        pracownik=pracownik, pracownik_nazwa=pracownik.replace("_", " ").title(),
        data=d, kanal="bezposredni", notatka=notatka, wynik=wynik,
        budynek="Dworcowa 7", lokal=str(godzina),
    )


class TestRoleINormy(unittest.TestCase):
    def test_normy_zalezne_od_roli(self):
        agent = normy_dla_roli(ROLA_AGENT)["dzien"]["aktywnosci"]
        koordynator = normy_dla_roli(ROLA_KOORDYNATOR)["dzien"]["aktywnosci"]
        kierownik = normy_dla_roli(ROLA_KIEROWNIK)["dzien"]["aktywnosci"]
        self.assertGreater(agent, koordynator)
        self.assertGreater(koordynator, kierownik)

    def test_okresy_skaluja_sie_z_normy_dziennej(self):
        normy = normy_dla_roli(ROLA_AGENT)
        self.assertEqual(normy["tydzien"]["aktywnosci"], normy["dzien"]["aktywnosci"] * 5)
        self.assertEqual(normy["rok"]["aktywnosci"], normy["dzien"]["aktywnosci"] * 250)

    def test_indywidualna_norma_nadpisuje_role(self):
        p = Pracownik(klucz="x", imie_nazwisko="X", rola=ROLA_AGENT,
                      normy={"dzien": {"aktywnosci": 99}})
        self.assertEqual(p.normy_pelne["dzien"]["aktywnosci"], 99)
        # nienadpisane pola zostają z roli
        self.assertEqual(p.normy_pelne["dzien"]["leady"],
                         normy_dla_roli(ROLA_AGENT)["dzien"]["leady"])

    def test_nowicjusz(self):
        self.assertTrue(Pracownik(klucz="a", imie_nazwisko="A", staz_miesiace=3).nowicjusz)
        self.assertFalse(Pracownik(klucz="b", imie_nazwisko="B", staz_miesiace=24).nowicjusz)

    def test_norma_grupy_to_suma_norm_ludzi(self):
        zespol = [
            Pracownik(klucz="a", imie_nazwisko="A", rola=ROLA_AGENT),
            Pracownik(klucz="b", imie_nazwisko="B", rola=ROLA_AGENT),
            Pracownik(klucz="k", imie_nazwisko="K", rola=ROLA_KOORDYNATOR),
        ]
        dzienna = suma_norm(zespol)["dzien"]["aktywnosci"]
        self.assertEqual(
            dzienna,
            2 * normy_dla_roli(ROLA_AGENT)["dzien"]["aktywnosci"]
            + normy_dla_roli(ROLA_KOORDYNATOR)["dzien"]["aktywnosci"],
        )
        self.assertEqual(suma_norm(zespol)["miesiac"]["aktywnosci"], dzienna * 21)

    def test_norma_pustego_zespolu_nie_wywraca_liczenia(self):
        self.assertEqual(suma_norm([]), {})

    def test_pula_zespolu_nie_moze_isc_do_normy_jednej_osoby(self):
        """Regresja: zbiorczy kafel na pulpicie brał domyślną normę agenta,
        więc trzy osoby robiące dokładnie swoje normy wyglądały na 300%."""
        zespol = [Pracownik(klucz=k, imie_nazwisko=k.upper(), rola=ROLA_AGENT)
                  for k in ("a", "b", "c")]
        dzienna = suma_norm(zespol)["dzien"]["aktywnosci"]
        dzien = "2026-08-10"                                   # poniedziałek
        pula = [akt("a", dzien, 9, notatka="x" * 40 + str(i)) for i in range(dzienna)]

        zbiorczo = podsumowanie(pula, "dzien", suma_norm(zespol), zakres=(dzien, dzien))
        jednoosobowo = podsumowanie(pula, "dzien", zakres=(dzien, dzien))
        self.assertEqual(zbiorczo["realizacja_normy_proc"], 100)
        self.assertGreater(jednoosobowo["realizacja_normy_proc"], 250)


class TestStatystykiGrupy(unittest.TestCase):
    def test_statystyki(self):
        st = statystyki([10, 20, 30, 40])
        self.assertEqual(st["n"], 4)
        self.assertEqual(st["mediana"], 25.0)
        self.assertEqual(st["min"], 10)
        self.assertEqual(st["max"], 40)

    def test_pusta_grupa(self):
        self.assertEqual(statystyki([])["n"], 0)
        self.assertIsNone(percentyl(5, []))

    def test_percentyl(self):
        self.assertEqual(percentyl(50, [10, 20, 30]), 100)
        self.assertEqual(percentyl(5, [10, 20, 30]), 0)
        self.assertEqual(percentyl(20, [10, 20, 30]), 67)

    def test_kierunek_metryki(self):
        # wysoki percentyl przy metryce "im mniej tym lepiej" to wynik słaby
        self.assertEqual(ocena_pozycji(90, wyzej_lepiej=True), "powyżej grupy")
        self.assertEqual(ocena_pozycji(90, wyzej_lepiej=False), "poniżej grupy")
        self.assertEqual(ocena_pozycji(None, wyzej_lepiej=True), "brak danych")

    def test_porownanie_pomija_oceniana_osobe(self):
        moje = podsumowanie([akt("a", "2026-08-10", g) for g in range(9, 14)], "dzien")
        grupa = {
            "a": moje,
            "b": podsumowanie([akt("b", "2026-08-10", g) for g in range(9, 11)], "dzien"),
            "c": podsumowanie([akt("c", "2026-08-10", g) for g in range(9, 12)], "dzien"),
        }
        wynik = porownaj_z_grupa(moje, grupa, "a", "Agenci")
        self.assertEqual(wynik["liczebnosc"], 2)          # bez osoby ocenianej
        self.assertFalse(wynik["wiarygodne"])             # 2 < próg 3
        self.assertEqual(wynik["pola"]["liczba_aktywnosci"]["mediana_grupy"], 2.5)
        self.assertEqual(wynik["pola"]["liczba_aktywnosci"]["moja"], 5)

    def test_opis_dla_modelu_oznacza_mala_grupe(self):
        moje = podsumowanie([akt("a", "2026-08-10", 9)], "dzien")
        grupa = {"a": moje, "b": podsumowanie([akt("b", "2026-08-10", 9)], "dzien")}
        tekst = opis_dla_modelu([porownaj_z_grupa(moje, grupa, "a", "Agenci")])
        self.assertIn("grupa za mała", tekst)
        self.assertEqual(opis_dla_modelu([]), "(brak grupy porównawczej — za mało osób w tej roli)")


class TestOrganizacjaWBazie(unittest.TestCase):
    def setUp(self):
        self.katalog = tempfile.TemporaryDirectory()
        self.baza = Baza(Path(self.katalog.name) / "t.db")

    def tearDown(self):
        self.baza.zamknij()
        self.katalog.cleanup()

    def test_crud_biura(self):
        biuro_id = self.baza.zapisz_biuro(Biuro(nazwa="Centrum", miasto="Bydgoszcz"))
        self.assertEqual(self.baza.biuro(biuro_id).nazwa, "Centrum")
        self.baza.zapisz_biuro(Biuro(id=biuro_id, nazwa="Centrum II", miasto="Toruń"))
        self.assertEqual(self.baza.biuro(biuro_id).nazwa, "Centrum II")
        self.assertEqual(len(self.baza.biura()), 1)

    def test_usuniecie_biura_nie_kasuje_ludzi(self):
        biuro_id = self.baza.zapisz_biuro(Biuro(nazwa="Centrum"))
        self.baza.zapisz_pracownika(
            Pracownik(klucz="jan", imie_nazwisko="Jan", biuro_id=biuro_id)
        )
        self.baza.usun_biuro(biuro_id)
        jan = self.baza.pracownik("jan")
        self.assertIsNotNone(jan)
        self.assertIsNone(jan.biuro_id)
        self.assertEqual([p.klucz for p in self.baza.nieprzypisani()], ["jan"])

    def test_duplikat_nazwy_biura_nie_blokuje_bazy(self):
        import sqlite3
        self.baza.zapisz_biuro(Biuro(nazwa="Centrum"))
        with self.assertRaises(sqlite3.IntegrityError):
            self.baza.zapisz_biuro(Biuro(nazwa="Centrum"))
        # po nieudanym zapisie baza musi nadal przyjmować zapisy
        self.baza.zapisz_pracownika(Pracownik(klucz="jan", imie_nazwisko="Jan"))
        self.assertIsNotNone(self.baza.pracownik("jan"))

    def test_synchronizacja_z_aktywnosci(self):
        self.baza.zapisz_aktywnosci([akt("nowa_osoba", "2026-08-10", 10)])
        self.assertEqual(self.baza.synchronizuj_pracownikow(), 1)
        self.assertEqual(self.baza.synchronizuj_pracownikow(), 0)  # idempotentne
        self.assertIsNone(self.baza.pracownik("nowa_osoba").biuro_id)

    def test_filtrowanie_po_biurze_i_roli(self):
        biuro_id = self.baza.zapisz_biuro(Biuro(nazwa="Centrum"))
        self.baza.zapisz_pracownika(Pracownik(klucz="a", imie_nazwisko="A",
                                              biuro_id=biuro_id, rola=ROLA_AGENT))
        self.baza.zapisz_pracownika(Pracownik(klucz="k", imie_nazwisko="K",
                                              biuro_id=biuro_id, rola=ROLA_KOORDYNATOR))
        self.baza.zapisz_pracownika(Pracownik(klucz="z", imie_nazwisko="Z",
                                              rola=ROLA_AGENT, aktywny=False))
        self.assertEqual(len(self.baza.pracownicy(biuro_id=biuro_id)), 2)
        self.assertEqual(len(self.baza.pracownicy(rola=ROLA_AGENT)), 1)  # nieaktywny pominięty
        self.assertEqual(len(self.baza.pracownicy(tylko_aktywni=False)), 3)

    def test_metryki_biura_z_puli_aktywnosci(self):
        biuro_id = self.baza.zapisz_biuro(Biuro(nazwa="Centrum"))
        for klucz in ("a", "b"):
            self.baza.zapisz_pracownika(
                Pracownik(klucz=klucz, imie_nazwisko=klucz.upper(), biuro_id=biuro_id)
            )
            self.baza.zapisz_aktywnosci([akt(klucz, "2026-08-10", g) for g in (9, 10, 11)])
        m = metryki_biura(self.baza, biuro_id, "dzien", "2026-08-10")
        self.assertEqual(m["liczba_aktywnosci"], 6)      # suma, nie średnia
        self.assertEqual(m["liczba_pracownikow"], 2)
        self.assertEqual(m["liczba_pracujacych"], 2)
        # norma biura to suma norm indywidualnych
        self.assertEqual(m["norma"]["aktywnosci"],
                         2 * normy_dla_roli(ROLA_AGENT)["dzien"]["aktywnosci"])

    def test_grupa_porownawcza_tylko_ta_sama_rola(self):
        biuro_id = self.baza.zapisz_biuro(Biuro(nazwa="Centrum"))
        for klucz, rola in (("a", ROLA_AGENT), ("b", ROLA_AGENT), ("k", ROLA_KOORDYNATOR)):
            self.baza.zapisz_pracownika(Pracownik(klucz=klucz, imie_nazwisko=klucz.upper(),
                                                  biuro_id=biuro_id, rola=rola))
            self.baza.zapisz_aktywnosci([akt(klucz, "2026-08-10", g) for g in (9, 10)])
        p = self.baza.pracownik("a")
        moje = podsumowanie(self.baza.pobierz("a", "2026-08-10", "2026-08-10"), "dzien")
        grupy = grupy_porownawcze(self.baza, p, "dzien", "2026-08-10", moje)
        self.assertTrue(grupy)
        for g in grupy:
            self.assertEqual(g["liczebnosc"], 1)  # tylko drugi agent, bez koordynatorki

    def test_ranking_biur(self):
        for nazwa, ile in (("Centrum", 5), ("Wschód", 2)):
            biuro_id = self.baza.zapisz_biuro(Biuro(nazwa=nazwa))
            klucz = nazwa.lower()
            self.baza.zapisz_pracownika(
                Pracownik(klucz=klucz, imie_nazwisko=nazwa, biuro_id=biuro_id)
            )
            self.baza.zapisz_aktywnosci(
                [akt(klucz, "2026-08-10", 9 + i) for i in range(ile)]
            )
        ranking = ranking_biur(self.baza, "dzien", "2026-08-10")
        self.assertEqual([r["miejsce"] for r in ranking], [1, 2])
        self.assertGreaterEqual(ranking[0]["wartosc"], ranking[1]["wartosc"])


class TestEtykietyOkresow(unittest.TestCase):
    def test_etykiety(self):
        self.assertIn("poniedziałek", etykieta_okresu("2026-08-10", "dzien"))
        self.assertIn("sierpień 2026", etykieta_okresu("2026-08", "miesiac"))
        self.assertIn("III kwartał", etykieta_okresu("2026-Q3", "kwartal"))
        self.assertIn("tydzień 33", etykieta_okresu("2026-W33", "tydzien"))

    def test_nastepny_okres_przez_granice_roku(self):
        self.assertEqual(nastepny_okres("2026-12", "miesiac"), "2027-01")
        self.assertEqual(nastepny_okres("2026-Q4", "kwartal"), "2027-Q1")
        self.assertEqual(nastepny_okres("2026-08-10", "dzien"), "2026-08-11")


class TestPanelWWW(unittest.TestCase):
    """Panel ma się nie wywracać — na pustej bazie, na śmieciach w URL-u
    i na normalnych danych."""

    def setUp(self):
        try:
            from analityk.web import stworz_aplikacje
        except ImportError:
            self.skipTest("brak pakietu flask")
        self.katalog = tempfile.TemporaryDirectory()
        sciezka = Path(self.katalog.name) / "t.db"
        baza = Baza(sciezka)
        biuro_id = baza.zapisz_biuro(Biuro(nazwa="Centrum", miasto="Bydgoszcz"))
        dzis = datetime.now().date()
        for klucz, rola in (("a", ROLA_AGENT), ("b", ROLA_AGENT), ("k", ROLA_KOORDYNATOR)):
            baza.zapisz_pracownika(Pracownik(klucz=klucz, imie_nazwisko=klucz.upper(),
                                             biuro_id=biuro_id, rola=rola))
            baza.zapisz_aktywnosci([
                akt(klucz, (dzis - timedelta(days=d)).isoformat(), 9 + g,
                    "lead" if g == 0 else "odmowa")
                for d in range(3) for g in range(4)
            ])
        baza.zamknij()
        self.app = stworz_aplikacje(str(sciezka))
        self.c = self.app.test_client()

    def tearDown(self):
        self.katalog.cleanup()

    def test_wszystkie_widoki_odpowiadaja(self):
        for sciezka in ("/", "/?okres=tydzien", "/?okres=miesiac", "/?okres=kwartal",
                        "/?okres=rok", "/biuro/1", "/pracownik/a", "/pracownik/k",
                        "/organizacja", "/wczytaj", "/pracownik/a/raport.md"):
            with self.subTest(sciezka=sciezka):
                self.assertEqual(self.c.get(sciezka).status_code, 200)

    def test_smieci_w_adresie_nie_wywracaja_panelu(self):
        for sciezka in ("/?okres=bzdura&klucz=nonsens", "/?okres=tydzien&klucz=2026-W99",
                        "/biuro/1?okres=miesiac&klucz=xx", "/pracownik/nie_ma_takiego",
                        "/biuro/999"):
            with self.subTest(sciezka=sciezka):
                self.assertEqual(
                    self.c.get(sciezka, follow_redirects=True).status_code, 200
                )

    def test_porownanie_widoczne_na_karcie_pracownika(self):
        tresc = self.c.get("/pracownik/a").get_data(as_text=True)
        self.assertIn("Na tle innych", tresc)
        self.assertIn("Mediana grupy", tresc)

    def test_formularz_zapisuje_przypisanie(self):
        odp = self.c.post("/organizacja/pracownik/a",
                          data={"biuro_id": "1", "rola": "kierownik",
                                "imie_nazwisko": "Nowe Nazwisko", "staz_miesiace": "12",
                                "aktywny": "1"},
                          follow_redirects=True)
        self.assertEqual(odp.status_code, 200)
        baza = Baza(self.app.config["SCIEZKA_BAZY"])
        p = baza.pracownik("a")
        baza.zamknij()
        self.assertEqual(p.rola, "kierownik")
        self.assertEqual(p.imie_nazwisko, "Nowe Nazwisko")
        self.assertEqual(p.staz_miesiace, 12)

    def test_post_zachowuje_wybrany_okres(self):
        """POST przekazuje okres w formularzu — bez tego akcje działały na
        dzisiejszym dniu zamiast na okresie widocznym na ekranie."""
        odp = self.c.post("/pracownik/a/pamiec",
                          data={"tresc": "Ustalenie testowe", "typ": "ustalenie_1n1",
                                "okres": "tydzien", "klucz": "2026-W33"},
                          follow_redirects=False)
        self.assertIn("okres=tydzien", odp.headers["Location"])
        self.assertIn("klucz=2026-W33", odp.headers["Location"])

    def test_przywrocenie_regul_domyslnych(self):
        """Po aktualizacji programu reguły w bazie trzeba odświeżyć ręcznie —
        stare domyślne znikają, własne zostają."""
        from analityk.store import Baza as B
        baza = B(self.app.config["SCIEZKA_BAZY"])
        baza.ustaw_mapowanie("stara regula", "R4", zrodlo="domyslne")
        baza.ustaw_mapowanie("moja regula", "NO10", zrodlo="reczne")
        baza.zamknij()

        odp = self.c.post("/typy/przywroc", follow_redirects=True)
        self.assertEqual(odp.status_code, 200)

        baza = B(self.app.config["SCIEZKA_BAZY"])
        mapowanie = baza.mapowanie_typow()
        baza.zamknij()
        self.assertNotIn("stara regula", mapowanie)          # stare domyślne usunięte
        self.assertEqual(mapowanie["moja regula"]["kod"], "NO10")   # własna nietknięta
        self.assertIn("ricerca", mapowanie)                   # nowe domyślne wgrane

    def test_karta_pracownika_ma_zakladki(self):
        tresc = self.c.get("/pracownik/a?okres=miesiac").get_data(as_text=True)
        self.assertIn("/pracownik/a/zadania", tresc)
        self.assertIn("/pracownik/a/tematy", tresc)

    def test_podstrony_pracownika_odpowiadaja(self):
        for sciezka in ("/pracownik/a/zadania", "/pracownik/a/tematy",
                        "/pracownik/a/tematy?status=wszystkie",
                        "/pracownik/a/zadania?status=zrobione",
                        "/pracownik/nie_ma_takiego/tematy"):
            with self.subTest(sciezka=sciezka):
                self.assertEqual(self.c.get(sciezka).status_code, 200)

    def test_zakladka_tematow_pokazuje_tylko_swojego_pracownika(self):
        moje = self.c.get("/pracownik/a/tematy?okres=miesiac&status=wszystkie")
        tresc = moje.get_data(as_text=True)
        self.assertIn("Akceptuj", tresc)
        self.assertNotIn("/pracownik/b/tematy", tresc)   # zakładki wiodą do „a”

    def _klucze_alertow(self, adres: str = "/?okres=miesiac") -> list[str]:
        import re
        return re.findall(r"/alert/([^/]+)/archiwizuj",
                          self.c.get(adres).get_data(as_text=True))

    def test_alert_ma_date_i_da_sie_go_schowac(self):
        klucze = self._klucze_alertow()
        self.assertTrue(klucze)
        tresc = self.c.get("/?okres=miesiac").get_data(as_text=True)
        self.assertRegex(tresc, r'class="data">\s*\d\d\.\d\d\.\d{4}')

        self.c.post(f"/alert/{klucze[0]}/archiwizuj", data={"powrot": "/?okres=miesiac"})
        self.assertEqual(len(self._klucze_alertow()), len(klucze) - 1)

    def test_zarchiwizowany_alert_da_sie_przywrocic(self):
        klucze = self._klucze_alertow()
        self.c.post(f"/alert/{klucze[0]}/archiwizuj", data={"powrot": "/?okres=miesiac"})
        self.assertIn("przywróć",
                      self.c.get("/?okres=miesiac&archiwum=1").get_data(as_text=True))
        self.c.post(f"/alert/{klucze[0]}/archiwizuj",
                    data={"przywroc": "1", "powrot": "/?okres=miesiac"})
        self.assertEqual(len(self._klucze_alertow()), len(klucze))

    def test_archiwizacja_dotyczy_jednego_okresu(self):
        """Schowany alert ma wrócić, gdy problem powtórzy się w kolejnym okresie."""
        from analityk.store import Baza as B
        baza = B(self.app.config["SCIEZKA_BAZY"])
        alert = [{"kod": "norma", "tresc": "Realizacja normy 40%."}]
        klucz = baza.zarejestruj_alerty("a", "miesiac", "2026-08", alert)[0]["klucz"]
        baza.archiwizuj_alert(klucz)

        sierpien = baza.zarejestruj_alerty("a", "miesiac", "2026-08", alert)[0]
        wrzesien = baza.zarejestruj_alerty("a", "miesiac", "2026-09", alert)[0]
        inna_osoba = baza.zarejestruj_alerty("b", "miesiac", "2026-08", alert)[0]
        baza.zamknij()

        self.assertTrue(sierpien["zarchiwizowany"])
        self.assertFalse(wrzesien["zarchiwizowany"])
        self.assertFalse(inna_osoba["zarchiwizowany"])

    def test_data_alertu_sie_nie_odswieza(self):
        """Alert wiszący od tygodnia nie może wyglądać na dzisiejszy."""
        from analityk.store import Baza as B
        klucz = self._klucze_alertow()[0]
        import urllib.parse
        baza = B(self.app.config["SCIEZKA_BAZY"])
        baza.con.execute(
            "UPDATE alerty_stan SET pierwszy_raz = '2026-01-05T08:00:00' WHERE klucz = ?",
            (urllib.parse.unquote(klucz),),
        )
        baza.con.commit()
        baza.zamknij()
        self.assertIn("05.01.2026", self.c.get("/?okres=miesiac").get_data(as_text=True))

    def test_tematy_pokazuja_pojedyncze_notatki(self):
        tresc = self.c.get("/tematy?okres=miesiac").get_data(as_text=True)
        self.assertIn("Akceptuj", tresc)
        self.assertIn("Odrzuć", tresc)

    def _pierwsza_notatka(self) -> str:
        from analityk.store import Baza as B
        baza = B(self.app.config["SCIEZKA_BAZY"])
        akt_id = next(a.id for a in baza.pobierz() if a.wynik == "lead")
        baza.zamknij()
        return akt_id

    def test_akceptacja_przenosi_notatke_na_osobna_podstrone(self):
        akt_id = self._pierwsza_notatka()
        odp = self.c.post(f"/tematy/notatka/{akt_id}/ocena",
                          data={"status": "zaakceptowana", "komentarz": "oddzwonić"},
                          follow_redirects=True)
        self.assertEqual(odp.status_code, 200)
        tresc = self.c.get("/tematy/zaakceptowane").get_data(as_text=True)
        self.assertIn("oddzwonić", tresc)

    def test_odrzucona_znika_z_przegladu_ale_zostaje_pod_filtrem(self):
        akt_id = self._pierwsza_notatka()
        self.c.post(f"/tematy/notatka/{akt_id}/ocena", data={"status": "odrzucona"})
        przeglad = self.c.get("/tematy?okres=miesiac&limit=0").get_data(as_text=True)
        odrzucone = self.c.get(
            "/tematy?okres=miesiac&limit=0&status=odrzucona").get_data(as_text=True)
        self.assertNotIn(akt_id, przeglad)
        self.assertIn(akt_id, odrzucone)

    def test_limit_da_sie_zdjac(self):
        """Skrócona lista musi mieć wyjście — inaczej reszty notatek nie widać."""
        krotka = self.c.get("/tematy?okres=rok&limit=1").get_data(as_text=True)
        self.assertIn("pokaż wszystkie", krotka)
        pelna = self.c.get("/tematy?okres=rok&limit=0").get_data(as_text=True)
        self.assertGreater(pelna.count("Akceptuj"), krotka.count("Akceptuj"))

    def test_filtr_etykiety_zaweza_liste(self):
        wszystko = self.c.get("/tematy?okres=rok&limit=0").get_data(as_text=True)
        self.assertIn("Lead", wszystko)
        pusto = self.c.get(
            "/tematy?okres=rok&limit=0&etykieta=pustostan").get_data(as_text=True)
        self.assertIn("Nic tu nie ma przy tych filtrach", pusto)

    def test_pusta_baza(self):
        with tempfile.TemporaryDirectory() as pusty:
            from analityk.web import stworz_aplikacje
            c = stworz_aplikacje(str(Path(pusty) / "pusta.db")).test_client()
            for sciezka in ("/", "/organizacja", "/wczytaj"):
                self.assertEqual(c.get(sciezka).status_code, 200)


if __name__ == "__main__":
    unittest.main()
