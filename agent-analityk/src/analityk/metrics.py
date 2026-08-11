"""Metryki i agregacje okresowe (dzień / tydzień / miesiąc / kwartał / rok).

Wszystko liczone deterministycznie z bazy — LLM dostaje gotowe liczby i nie
ma czego zmyślać. To ważne: model, który sam liczy statystyki z listy 300
notatek, myli się i nie da się go potem odtworzyć.
"""

from __future__ import annotations

import statistics
from collections import Counter
from datetime import date, datetime, timedelta

from .models import (
    Activity,
    WYNIK_BRAK_KONTAKTU,
    WYNIK_INFO_RYNKOWE,
    WYNIK_LEAD,
    WYNIK_ODMOWA_TWARDA,
    WYNIK_SYGNAL,
)

TYPY_OKRESOW = ("dzien", "tydzien", "miesiac", "kwartal", "rok")

#: Domyślne normy aktywności (do nadpisania w config.yaml / profilu pracownika).
NORMY_DOMYSLNE = {
    "dzien": {"aktywnosci": 40, "rozmowy": 25, "leady": 1},
    "tydzien": {"aktywnosci": 200, "rozmowy": 120, "leady": 5},
    "miesiac": {"aktywnosci": 800, "rozmowy": 480, "leady": 20},
    "kwartal": {"aktywnosci": 2400, "rozmowy": 1440, "leady": 60},
    "rok": {"aktywnosci": 9600, "rozmowy": 5760, "leady": 240},
}

#: Waga składników indeksu jakości pracy (suma = 1.0).
WAGI_INDEKSU = {
    "realizacja_normy": 0.30,
    "dotarcie": 0.20,
    "konwersja": 0.20,
    "jakosc_notatek": 0.15,
    "follow_up": 0.15,
}

MIN_DLUGOSC_NOTATKI = 20  # znaków — poniżej notatka niczego nie wnosi


# --- okresy ---------------------------------------------------------------

def klucz_okresu(d: date | datetime, typ: str) -> str:
    if isinstance(d, datetime):
        d = d.date()
    if typ == "dzien":
        return d.isoformat()
    if typ == "tydzien":
        rok, tydz, _ = d.isocalendar()
        return f"{rok}-W{tydz:02d}"
    if typ == "miesiac":
        return f"{d.year}-{d.month:02d}"
    if typ == "kwartal":
        return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
    if typ == "rok":
        return str(d.year)
    raise ValueError(f"nieznany typ okresu: {typ}")


def zakres_okresu(klucz: str, typ: str) -> tuple[str, str]:
    """Zwraca (data_od, data_do) w formacie ISO — granice włącznie."""
    if typ == "dzien":
        return klucz, klucz
    if typ == "tydzien":
        rok, tydz = int(klucz[:4]), int(klucz.split("W")[1])
        pon = date.fromisocalendar(rok, tydz, 1)
        return pon.isoformat(), (pon + timedelta(days=6)).isoformat()
    if typ == "miesiac":
        rok, mies = int(klucz[:4]), int(klucz[5:7])
        start = date(rok, mies, 1)
        koniec = date(rok + (mies == 12), (mies % 12) + 1, 1) - timedelta(days=1)
        return start.isoformat(), koniec.isoformat()
    if typ == "kwartal":
        rok, kw = int(klucz[:4]), int(klucz.split("Q")[1])
        start = date(rok, 3 * (kw - 1) + 1, 1)
        koniec_m = 3 * kw
        koniec = date(rok + (koniec_m == 12), (koniec_m % 12) + 1, 1) - timedelta(days=1)
        return start.isoformat(), koniec.isoformat()
    if typ == "rok":
        rok = int(klucz)
        return f"{rok}-01-01", f"{rok}-12-31"
    raise ValueError(f"nieznany typ okresu: {typ}")


def poprzedni_okres(klucz: str, typ: str) -> str:
    od, _ = zakres_okresu(klucz, typ)
    dzien_przed = date.fromisoformat(od) - timedelta(days=1)
    return klucz_okresu(dzien_przed, typ)


def nastepny_okres(klucz: str, typ: str) -> str:
    _, do = zakres_okresu(klucz, typ)
    dzien_po = date.fromisoformat(do) + timedelta(days=1)
    return klucz_okresu(dzien_po, typ)


DNI_TYGODNIA = ("poniedziałek", "wtorek", "środa", "czwartek", "piątek",
                "sobota", "niedziela")
MIESIACE = ("styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec", "lipiec",
            "sierpień", "wrzesień", "październik", "listopad", "grudzień")
RZYMSKIE = {1: "I", 2: "II", 3: "III", 4: "IV"}


def etykieta_okresu(klucz: str, typ: str) -> str:
    """Czytelny opis okresu do wyświetlenia w panelu."""
    if typ == "dzien":
        d = date.fromisoformat(klucz)
        return f"{DNI_TYGODNIA[d.weekday()]}, {d.strftime('%d.%m.%Y')}"
    if typ == "tydzien":
        od, do = zakres_okresu(klucz, typ)
        o, d = date.fromisoformat(od), date.fromisoformat(do)
        return f"tydzień {klucz.split('W')[1]}: {o.strftime('%d.%m')}–{d.strftime('%d.%m.%Y')}"
    if typ == "miesiac":
        rok, mies = int(klucz[:4]), int(klucz[5:7])
        return f"{MIESIACE[mies - 1]} {rok}"
    if typ == "kwartal":
        rok, kw = int(klucz[:4]), int(klucz.split("Q")[1])
        return f"{RZYMSKIE[kw]} kwartał {rok}"
    return f"rok {klucz}"


# --- metryki --------------------------------------------------------------

def _procent(licznik: int, mianownik: int) -> float:
    return round(100 * licznik / mianownik, 1) if mianownik else 0.0


def dni_robocze(od: date, do: date, sobota_pracuje: bool = True) -> int:
    """Liczba dni roboczych w przedziale (włącznie). W nieruchomościach soboty
    zwykle są dniem pracy — stąd domyślne `sobota_pracuje=True`."""
    if do < od:
        return 0
    ostatni_dzien_tygodnia = 5 if sobota_pracuje else 4
    return sum(
        1 for i in range((do - od).days + 1)
        if (od + timedelta(days=i)).weekday() <= ostatni_dzien_tygodnia
    )


def podsumowanie(aktywnosci: list[Activity], typ_okresu: str = "dzien",
                 normy: dict | None = None,
                 zakres: tuple[str, str] | None = None,
                 dzis: date | None = None) -> dict:
    """Liczy komplet wskaźników dla zbioru aktywności.

    `zakres` (data_od, data_do) pozwala rozliczyć normę **proporcjonalnie** do
    dni, które już minęły. Bez tego tydzień oglądany we wtorek zawsze wygląda
    na katastrofę.
    """
    n = len(aktywnosci)
    norma = (normy or NORMY_DOMYSLNE).get(typ_okresu, {})

    if n == 0:
        return {"liczba_aktywnosci": 0, "pusty": True, "norma": norma}

    wyniki = Counter(a.wynik for a in aktywnosci)
    kanaly = Counter(a.kanal for a in aktywnosci)
    tagi = Counter(t for a in aktywnosci for t in a.tagi)
    godziny = Counter(a.godzina for a in aktywnosci)
    dni = sorted({a.dzien for a in aktywnosci})

    rozmowy = sum(1 for a in aktywnosci if a.byla_rozmowa)
    wartosciowe = sum(1 for a in aktywnosci if a.wartosciowa)
    leady = wyniki[WYNIK_LEAD]
    sygnaly = wyniki[WYNIK_SYGNAL]

    dlugosci = [len(a.notatka) for a in aktywnosci]
    merytoryczne = sum(1 for a in aktywnosci if len(a.notatka) >= MIN_DLUGOSC_NOTATKI)

    czasy = sorted(a.data for a in aktywnosci)
    # Rozpiętość liczona per dzień, żeby agregaty tygodniowe nie sumowały nocy.
    rozpietosci = []
    for d in dni:
        w_dniu = [a.data for a in aktywnosci if a.dzien == d]
        rozpietosci.append((max(w_dniu) - min(w_dniu)).total_seconds() / 3600)
    rozpietosc_srednia = round(statistics.fmean(rozpietosci), 1) if rozpietosci else 0.0

    budynki = Counter(a.budynek for a in aktywnosci if a.budynek)
    lokale = {(a.budynek, a.lokal) for a in aktywnosci if a.budynek and a.lokal}

    m = {
        "pusty": False,
        "typ_okresu": typ_okresu,
        "dni_z_aktywnoscia": len(dni),
        "pierwszy_dzien": dni[0],
        "ostatni_dzien": dni[-1],

        # --- ILOŚĆ ---
        "liczba_aktywnosci": n,
        "srednio_dziennie": round(n / len(dni), 1),
        "unikalne_budynki": len(budynki),
        "unikalne_lokale": len(lokale),
        "kanaly": dict(kanaly),
        "udzial_bezposrednich_proc": _procent(kanaly.get("bezposredni", 0), n),

        # --- SKUTECZNOŚĆ ---
        "rozmowy_odbyte": rozmowy,
        "wskaznik_dotarcia_proc": _procent(rozmowy, n),
        "brak_kontaktu": wyniki[WYNIK_BRAK_KONTAKTU],
        "odmowy_twarde": wyniki[WYNIK_ODMOWA_TWARDA],
        "wskaznik_odmow_twardych_proc": _procent(wyniki[WYNIK_ODMOWA_TWARDA], max(rozmowy, 1)),

        # --- WARTOŚĆ ---
        "leady": leady,
        "sygnaly": sygnaly,
        "info_rynkowe": wyniki[WYNIK_INFO_RYNKOWE],
        "wynikow_wartosciowych": wartosciowe,
        "konwersja_na_lead_proc": _procent(leady + sygnaly, max(rozmowy, 1)),
        "kontaktow_na_lead": round(n / leady, 1) if leady else None,

        # --- JAKOŚĆ PRACY W CRM ---
        "srednia_dlugosc_notatki": round(statistics.fmean(dlugosci), 1),
        "mediana_dlugosci_notatki": int(statistics.median(dlugosci)),
        "notatki_merytoryczne_proc": _procent(merytoryczne, n),
        "material_zostawiony": sum(1 for a in aktywnosci if a.zostawiono_material),
        "kolejny_krok_zaplanowany": sum(1 for a in aktywnosci if a.zaplanowany_kolejny_krok),
        "follow_up_proc": _procent(
            sum(1 for a in aktywnosci if a.zostawiono_material or a.zaplanowany_kolejny_krok), n
        ),

        # --- ORGANIZACJA CZASU ---
        "pierwsza_aktywnosc": czasy[0].strftime("%H:%M"),
        "ostatnia_aktywnosc": czasy[-1].strftime("%H:%M"),
        "rozpietosc_dnia_h": rozpietosc_srednia,
        "aktywnosci_na_godzine": round(n / max(sum(rozpietosci), 1), 1),
        "rozklad_godzinowy": dict(sorted(godziny.items())),
        "praca_w_zlotych_godzinach_proc": _procent(
            sum(v for g, v in godziny.items() if 16 <= g <= 20), n
        ),

        # --- ROZKŁADY ---
        "wyniki": dict(wyniki.most_common()),
        "tagi": dict(tagi.most_common()),
        "top_budynki": dict(budynki.most_common(10)),

        "norma": norma,
    }

    # Norma rozliczana proporcjonalnie do dni roboczych, które już minęły.
    norma_efektywna = norma.get("aktywnosci")
    if zakres:
        od, do = date.fromisoformat(zakres[0]), date.fromisoformat(zakres[1])
        dzis = dzis or date.today()
        wszystkie = dni_robocze(od, do)
        uplynelo = dni_robocze(od, min(do, max(dzis, date.fromisoformat(dni[-1]))))
        m["dni_robocze_w_okresie"] = wszystkie
        m["dni_robocze_uplynelo"] = uplynelo
        m["okres_zamkniety"] = uplynelo >= wszystkie
        m["dni_bez_aktywnosci"] = max(uplynelo - len(dni), 0)
        if norma_efektywna and wszystkie:
            norma_efektywna = round(norma_efektywna * uplynelo / wszystkie)
            m["norma_proporcjonalna"] = norma_efektywna

    m["realizacja_normy_proc"] = _procent(n, norma_efektywna) if norma_efektywna else None
    m["indeks_jakosci"] = indeks_jakosci(m)
    return m


def indeks_jakosci(m: dict, wagi: dict | None = None) -> int:
    """Jedna liczba 0–100 spinająca ilość i jakość.

    Świadomie prosty i jawny wzór — pracownik musi rozumieć, za co dostaje
    punkty, inaczej wskaźnik nie zmienia zachowań.
    """
    if m.get("pusty"):
        return 0
    w = wagi or WAGI_INDEKSU
    skladniki = {
        "realizacja_normy": min(m.get("realizacja_normy_proc") or 0, 120) / 1.2,
        "dotarcie": m["wskaznik_dotarcia_proc"],
        # 8% konwersji rozmowa -> lead/sygnał traktujemy jako wynik wzorcowy
        "konwersja": min(m["konwersja_na_lead_proc"] / 8 * 100, 100),
        "jakosc_notatek": m["notatki_merytoryczne_proc"],
        "follow_up": min(m["follow_up_proc"] / 20 * 100, 100),
    }
    return round(sum(skladniki[k] * w[k] for k in w))


def porownaj(biezacy: dict, poprzedni: dict, pola: list[str] | None = None) -> dict:
    """Delty względem poprzedniego okresu (wartość, zmiana, zmiana %)."""
    pola = pola or [
        "liczba_aktywnosci", "rozmowy_odbyte", "leady", "sygnaly",
        "wskaznik_dotarcia_proc", "konwersja_na_lead_proc",
        "notatki_merytoryczne_proc", "follow_up_proc", "indeks_jakosci",
    ]
    out = {}
    for p in pola:
        teraz = biezacy.get(p)
        bylo = poprzedni.get(p)
        if teraz is None or bylo is None:
            continue
        zmiana = round(teraz - bylo, 1)
        out[p] = {
            "teraz": teraz,
            "poprzednio": bylo,
            "zmiana": zmiana,
            "zmiana_proc": round(100 * zmiana / bylo, 1) if bylo else None,
        }
    return out


def ranking_zespolu(per_pracownik: dict[str, dict], pole: str = "punkty_razem") -> list[tuple]:
    """Sortowanie pracowników po wybranej metryce (malejąco).

    Domyślnie po punktach z oficjalnej klasyfikacji sieci — to jest ranking,
    który ludzie znają. `indeks_jakosci` zostaje jako miara jakości pracy
    (ilość + jakość kontaktu), niezależna od tego, ile kto zamknął transakcji.
    """
    pozycje = [
        (klucz, m.get(pole) or 0, m.get("liczba_aktywnosci", 0))
        for klucz, m in per_pracownik.items()
        if not m.get("pusty")
    ]
    return sorted(pozycje, key=lambda x: x[1], reverse=True)


def alerty(m: dict, poprzedni: dict | None = None) -> list[str]:
    """Sygnały ostrzegawcze — rzeczy, na które szef powinien zareagować."""
    ostrzezenia: list[str] = []
    if m.get("pusty"):
        return ["Brak jakiejkolwiek aktywności w okresie."]

    if m.get("realizacja_normy_proc") is not None and m["realizacja_normy_proc"] < 70:
        ostrzezenia.append(
            f"Realizacja normy aktywności {m['realizacja_normy_proc']}% (próg 70%)."
        )
    if m.get("dni_bez_aktywnosci", 0) >= 2:
        ostrzezenia.append(
            f"{m['dni_bez_aktywnosci']} dni roboczych bez ani jednej aktywności w CRM."
        )
    if m["notatki_merytoryczne_proc"] < 60:
        ostrzezenia.append(
            f"Tylko {m['notatki_merytoryczne_proc']}% notatek ma treść — dane w CRM tracą wartość."
        )
    if m["follow_up_proc"] < 10:
        ostrzezenia.append(
            f"Follow-up zaplanowany w {m['follow_up_proc']}% kontaktów — praca kończy się na 'nie'."
        )
    if m["wskaznik_odmow_twardych_proc"] > 25:
        ostrzezenia.append(
            f"{m['wskaznik_odmow_twardych_proc']}% rozmów kończy się twardą odmową — "
            "sprawdź pierwsze zdanie skryptu."
        )
    if m["leady"] == 0 and m["liczba_aktywnosci"] >= 30:
        ostrzezenia.append(
            f"{m['liczba_aktywnosci']} kontaktów i zero leadów — wąskie gardło w jakości rozmowy."
        )
    if m["praca_w_zlotych_godzinach_proc"] < 20 and m["kanaly"].get("bezposredni", 0) > 10:
        ostrzezenia.append(
            f"Tylko {m['praca_w_zlotych_godzinach_proc']}% kontaktów bezpośrednich w godz. 16–20, "
            "gdy ludzie są w domach."
        )
    if poprzedni and not poprzedni.get("pusty"):
        spadek = m["liczba_aktywnosci"] - poprzedni["liczba_aktywnosci"]
        if poprzedni["liczba_aktywnosci"] and spadek / poprzedni["liczba_aktywnosci"] < -0.3:
            ostrzezenia.append(
                f"Spadek liczby aktywności o {abs(round(100 * spadek / poprzedni['liczba_aktywnosci']))}% "
                "względem poprzedniego okresu."
            )
    return ostrzezenia
