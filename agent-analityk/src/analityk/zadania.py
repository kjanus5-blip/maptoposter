"""Wyłapywanie zadań i follow-upów z notatek.

Notatka „Pani chce sprzedać, ma wysłać zdjęcia, prosi zadzwonić za tydzień,
zostawiła numer do siostry” zawiera trzy różne rzeczy: obietnicę klienta,
zadanie agenta z terminem i kontakt do zapamiętania. Dziś to wszystko ginie
w polu opisu. Ten moduł to wyciąga i zamienia w kolejkę do odhaczenia.

Dwie ścieżki, jak w reszcie systemu:

* **reguły** — offline, za darmo, oparte na wzorcach języka polskiego,
* **LLM** — dokładniejszy, radzi sobie z literówkami i zdaniami złożonymi
  (`analityk zadania --llm`).

Terminy względne („za tydzień”, „w czwartek”, „po wakacjach”) są zamieniane
na konkretną datę liczoną **od dnia kontaktu**, a nie od dnia uruchomienia
raportu — inaczej zadanie sprzed miesiąca dostałoby dzisiejszą datę.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .classify import normalizuj
from .models import Activity

# --- typy zadań -----------------------------------------------------------

ZAD_ODDZWONIC = "oddzwonic"
ZAD_WROCIC = "wrocic"
ZAD_WYSLAC = "wyslac"
ZAD_SPOTKANIE = "spotkanie"
ZAD_CZEKAM = "czekam_na_klienta"
ZAD_KONTAKT = "kontakt_do_osoby"
ZAD_PRZYPOMNIENIE = "przypomnienie"

NAZWY_ZADAN = {
    ZAD_ODDZWONIC: "Zadzwonić",
    ZAD_WROCIC: "Wrócić pod adres",
    ZAD_WYSLAC: "Wysłać / dostarczyć",
    ZAD_SPOTKANIE: "Spotkanie",
    ZAD_CZEKAM: "Czekam na klienta",
    ZAD_KONTAKT: "Kontakt do zapisania",
    ZAD_PRZYPOMNIENIE: "Wrócić do tematu",
}

#: Zadania po stronie agenta — te trafiają do kolejki „do zrobienia”.
ZADANIA_AGENTA = {ZAD_ODDZWONIC, ZAD_WROCIC, ZAD_WYSLAC, ZAD_SPOTKANIE,
                  ZAD_KONTAKT, ZAD_PRZYPOMNIENIE}

STATUS_OTWARTE = "otwarte"
STATUS_ZROBIONE = "zrobione"
STATUS_ANULOWANE = "anulowane"


@dataclass
class Zadanie:
    id: str
    pracownik: str
    aktywnosc_id: str
    dzien_zrodla: str
    typ: str
    tresc: str
    termin: str = ""            # ISO albo pusty, gdy nie da się ustalić
    termin_tekst: str = ""      # fragment notatki, z którego wynika termin
    strona: str = "agent"       # agent | klient
    budynek: str = ""
    lokal: str = ""
    notatka: str = ""
    zrodlo: str = "reguly"      # reguly | llm | reczne
    status: str = STATUS_OTWARTE

    @property
    def nazwa_typu(self) -> str:
        return NAZWY_ZADAN.get(self.typ, self.typ)

    @property
    def adres(self) -> str:
        return f"{self.budynek} / {self.lokal}".strip(" /")

    def przeterminowane(self, dzis: date | None = None) -> bool:
        if not self.termin or self.status != STATUS_OTWARTE:
            return False
        return date.fromisoformat(self.termin) < (dzis or date.today())


# --- terminy --------------------------------------------------------------

LICZEBNIKI = {
    "jeden": 1, "jedno": 1, "jednego": 1, "dwa": 2, "dwoch": 2, "dwie": 2,
    "trzy": 3, "trzech": 3, "cztery": 4, "czterech": 4, "piec": 5, "pieciu": 5,
    "szesc": 6, "szesciu": 6, "siedem": 7, "osiem": 8, "dziewiec": 9,
    "dziesiec": 10, "pol": 0.5, "poltora": 1.5,
}

DNI_TYGODNIA = {
    "poniedzialek": 0, "wtorek": 1, "sroda": 2, "srode": 2, "czwartek": 3,
    "piatek": 4, "sobota": 5, "sobote": 5, "niedziela": 6, "niedziele": 6,
}

MIESIACE = {
    "styczniu": 1, "lutym": 2, "marcu": 3, "kwietniu": 4, "maju": 5,
    "czerwcu": 6, "lipcu": 7, "sierpniu": 8, "wrzesniu": 9, "pazdzierniku": 10,
    "listopadzie": 11, "grudniu": 12,
}

#: Wyrażenia, które wskazują na odległą przyszłość bez konkretnej daty.
MGLISTE = ("po swietach", "po wakacjach", "na wiosne", "na jesien", "latem",
           "zima", "jak sie ociepli", "po sezonie", "kiedys")


def _dodaj_miesiace(d: date, ile: float) -> date:
    """Dodaje miesiące bez zewnętrznych bibliotek (30 dni = miesiąc)."""
    return d + timedelta(days=round(30.4 * ile))


def _liczba(tekst: str) -> float | None:
    tekst = tekst.strip()
    if tekst.isdigit():
        return float(tekst)
    return LICZEBNIKI.get(tekst)


def rozwiaz_termin(notatka: str, dzien_kontaktu: date) -> tuple[str, str]:
    """Zwraca (data ISO albo pusty string, fragment tekstu, który dał termin).

    Pusta data przy niepustym fragmencie znaczy „termin jest, ale mglisty” —
    takie zadanie trafia do kolejki bez daty, żeby nie udawać precyzji.
    """
    t = normalizuj(notatka)

    # konkretna data: 15.09, 15/09/2026
    m = re.search(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b", notatka)
    if m:
        dzien, miesiac, rok = m.group(1), m.group(2), m.group(3)
        try:
            rok_int = int(rok) if rok else dzien_kontaktu.year
            if rok_int < 100:
                rok_int += 2000
            kandydat = date(rok_int, int(miesiac), int(dzien))
            if not rok and kandydat < dzien_kontaktu:      # data bez roku w tyle
                kandydat = date(rok_int + 1, int(miesiac), int(dzien))
            return kandydat.isoformat(), m.group(0)
        except ValueError:
            pass

    if re.search(r"\bpojutrze\b", t):
        return (dzien_kontaktu + timedelta(days=2)).isoformat(), "pojutrze"
    if re.search(r"\bjutr[oa]\b", t):
        return (dzien_kontaktu + timedelta(days=1)).isoformat(), "jutro"
    if re.search(r"\bdzisiaj\b|\bdzis\b", t):
        return dzien_kontaktu.isoformat(), "dzisiaj"

    # „za tydzień”, „za 2 tygodnie”, „za pół roku”, „za 3 dni”
    # Jednostki od najdłuższej: inaczej „tydzien” dopasowałby się do „dzien”.
    m = re.search(r"\bza\s+(?:(\w+)\s+)?(tygodnie|tygodni|tydzien|miesiace|"
                  r"miesiecy|miesiac|dni|dzien|lata|roku|rok)\b", t)
    if m:
        ile = _liczba(m.group(1) or "") or 1
        jednostka = m.group(2)
        if jednostka.startswith("dz") or jednostka == "dni":
            return (dzien_kontaktu + timedelta(days=round(ile))).isoformat(), m.group(0)
        if jednostka.startswith("tydz") or jednostka.startswith("tygod"):
            return (dzien_kontaktu + timedelta(weeks=ile)).isoformat(), m.group(0)
        if jednostka.startswith("miesi"):
            return _dodaj_miesiace(dzien_kontaktu, ile).isoformat(), m.group(0)
        return _dodaj_miesiace(dzien_kontaktu, 12 * ile).isoformat(), m.group(0)

    if re.search(r"\bw przyszlym tygodniu\b|\bza tydzien\b", t):
        dni_do_poniedzialku = 7 - dzien_kontaktu.weekday()
        return (dzien_kontaktu + timedelta(days=dni_do_poniedzialku)).isoformat(), \
            "w przyszłym tygodniu"
    if re.search(r"\bw przyszlym miesiacu\b", t):
        return _dodaj_miesiace(dzien_kontaktu, 1).isoformat(), "w przyszłym miesiącu"
    if re.search(r"\bpod koniec miesiaca\b|\bdo konca miesiaca\b", t):
        pierwszy_nastepnego = date(
            dzien_kontaktu.year + (dzien_kontaktu.month == 12),
            (dzien_kontaktu.month % 12) + 1, 1,
        )
        return (pierwszy_nastepnego - timedelta(days=1)).isoformat(), "koniec miesiąca"

    # dzień tygodnia: „w czwartek”, „we wtorek”
    m = re.search(r"\b(?:we?|na)\s+(" + "|".join(DNI_TYGODNIA) + r")\b", t)
    if m:
        cel = DNI_TYGODNIA[m.group(1)]
        przesuniecie = (cel - dzien_kontaktu.weekday()) % 7 or 7
        return (dzien_kontaktu + timedelta(days=przesuniecie)).isoformat(), m.group(0)

    # miesiąc: „we wrześniu”
    m = re.search(r"\bwe?\s+(" + "|".join(MIESIACE) + r")\b", t)
    if m:
        miesiac = MIESIACE[m.group(1)]
        rok = dzien_kontaktu.year + (1 if miesiac < dzien_kontaktu.month else 0)
        return date(rok, miesiac, 1).isoformat(), m.group(0)

    for fraza in MGLISTE:
        if fraza in t:
            return "", fraza          # termin jest, ale nie da się go umiejscowić
    return "", ""


# --- wykrywanie zadań -----------------------------------------------------

@dataclass(frozen=True)
class Wzorzec:
    typ: str
    strona: str
    wzorce: tuple[str, ...]
    opis: str


WZORCE: tuple[Wzorzec, ...] = (
    Wzorzec(ZAD_KONTAKT, "agent", (
        r"\b(numer|telefon|kontakt|mail|e-?mail)\s+(do|od)\s+(\w+)",
        r"\b(zostawil|dal|podal|przekazal)\w*\s+(numer|telefon|kontakt|mail)",
        r"\b\d{3}[\s-]?\d{3}[\s-]?\d{3}\b",
    ), "kontakt do zapisania w CRM"),
    Wzorzec(ZAD_SPOTKANIE, "agent", (
        r"\bumowion\w*\s+(na|spotkani)",
        r"\bumowil\w*\s+sie",
        r"\bspotkanie\s+(w|na|za)\b",
        r"\bprzyjde\b|\bprzyjdzie\b",
        r"\bwycena\b|\bogledziny\b",
    ), "umówione spotkanie"),
    Wzorzec(ZAD_WYSLAC, "agent", (
        # „ma wysłać” = obietnica klienta, łapie to ZAD_CZEKAM — stąd lookbehind
        r"(?<!\bma )\b(wyslac|wysle|wyslem|przeslac|przesle)\b",
        r"\b(prosi|poprosil\w*|chce)\s+.{0,25}(oferte|zdjecia|wycene|umowe|prezentacje)",
        r"\bmam\s+(wyslac|przeslac|przygotowac|dostarczyc)",
        r"\b(dostarczyc|zawiezc|podrzucic)\b",
    ), "materiały do wysłania"),
    Wzorzec(ZAD_ODDZWONIC, "agent", (
        r"\b(zadzwonic|oddzwonic|zadzwonie|oddzwonie|zadzwonię)\b",
        r"\b(prosi|prosil\w*)\s+.{0,20}(o kontakt|zadzwonic|telefon)",
        r"\bmam\s+(zadzwonic|oddzwonic)",
        r"\bkontakt\s+(za|w)\b",
    ), "telefon do wykonania"),
    Wzorzec(ZAD_WROCIC, "agent", (
        r"\b(wrocic|wroce|zajrzec|podejsc|podjade|wpadne)\b",
        r"\bmam\s+(wrocic|przyjsc)",
        r"\bbedzie\s+(pozniej|wieczorem|po)\b",
        r"\bnie zastal\w*\b.{0,30}\b(wieczor|pozniej)",
    ), "powrót pod adres"),
    Wzorzec(ZAD_CZEKAM, "klient", (
        r"\bma\s+(wyslac|przeslac|zadzwonic|sie odezwac|dac znac|potwierdzic)",
        r"\b(odezwie sie|skontaktuje sie|da znac|zadzwoni)\b",
        r"\bczeka\w*\s+na\s+(decyzje|odpowiedz|zone|meza|rodzine|brata|siostre)",
        r"\bmusi\s+(sie zastanowic|porozmawiac|przemyslec)",
    ), "piłka po stronie klienta"),
    Wzorzec(ZAD_PRZYPOMNIENIE, "agent", (
        r"\bprzemysl\w*\b",
        r"\bzastanowi\w*\s+sie\b",
        r"\bmoze\s+(za|w)\b",
        r"\bna razie nie\b.{0,25}\b(pozniej|przyszlosci|roku)",
        r"\bwrocic do tematu\b",
    ), "temat do odświeżenia"),
)

#: Co konkretnie ma polecieć do klienta — dopisywane do treści zadania.
PRZEDMIOTY = (
    (r"\bzdjeci", "zdjęcia"),
    (r"\boferte|\boferta", "ofertę"),
    (r"\bwycen", "wycenę"),
    (r"\bumow", "umowę"),
    (r"\bprezentacj", "prezentację"),
    (r"\bwizytowk", "wizytówkę"),
    (r"\bulotk", "ulotkę"),
    (r"\bdokument", "dokumenty"),
    (r"\bmetraz|\bplan", "metraż / plan"),
)

#: „ma wysłać”, „ma mi przesłać” — ruch po stronie klienta…
RE_KLIENT_DOSYLA = re.compile(r"\bma\s+(?:mi\s+|nam\s+)?(wyslac|przeslac|dostarczyc|podeslac)")
#: …chyba że w tej samej notatce jest wprost zobowiązanie agenta.
RE_AGENT_WYSYLA = re.compile(
    r"\b(mam|musze|mialem|mialam|obiecalem|obiecalam)\s+(wyslac|przeslac|dostarczyc)"
    r"|\bwysle\b|\bprzesle\b"
)

RE_OSOBA = re.compile(
    r"\b(?:numer|telefon|kontakt|mail|e-?mail)\s+(?:do|od)\s+"
    r"(siostry|brata|corki|syna|zony|meza|matki|ojca|mamy|taty|"
    r"wlascciela|wlasciciela|sasiada|sasiadki|kuzyna|wnuka|wnuczki|\w+)"
)


def _tresc_zadania(typ: str, notatka: str, termin_tekst: str) -> str:
    """Krótki, czytelny opis — to on trafia na listę do odhaczenia."""
    t = normalizuj(notatka)
    czesci = [NAZWY_ZADAN.get(typ, typ)]

    if typ == ZAD_KONTAKT:
        m = RE_OSOBA.search(t)
        if m:
            czesci = [f"Zapisać kontakt do: {m.group(1)}"]
        else:
            czesci = ["Zapisać przekazany numer / kontakt"]
    elif typ in (ZAD_WYSLAC, ZAD_CZEKAM):
        przedmioty = [nazwa for wzor, nazwa in PRZEDMIOTY if re.search(wzor, t)]
        if przedmioty:
            akcja = "Wysłać" if typ == ZAD_WYSLAC else "Klient ma dosłać"
            czesci = [f"{akcja}: {', '.join(przedmioty)}"]

    if termin_tekst:
        czesci.append(f"({termin_tekst})")
    return " ".join(czesci)


def _id_zadania(aktywnosc_id: str, typ: str) -> str:
    return f"{aktywnosc_id}:{typ}"


def wykryj_zadania(aktywnosc: Activity) -> list[Zadanie]:
    """Zadania wynikające z jednej notatki. Jeden typ = jedno zadanie."""
    if not aktywnosc.notatka or len(aktywnosc.notatka) < 8:
        return []

    t = normalizuj(aktywnosc.notatka)
    dzien = aktywnosc.data.date()
    termin, termin_tekst = rozwiaz_termin(aktywnosc.notatka, dzien)

    znalezione: list[Zadanie] = []
    for wzorzec in WZORCE:
        if not any(re.search(w, t) for w in wzorzec.wzorce):
            continue
        znalezione.append(Zadanie(
            id=_id_zadania(aktywnosc.id, wzorzec.typ),
            pracownik=aktywnosc.pracownik,
            aktywnosc_id=aktywnosc.id,
            dzien_zrodla=aktywnosc.dzien,
            typ=wzorzec.typ,
            tresc=_tresc_zadania(wzorzec.typ, aktywnosc.notatka, termin_tekst),
            termin=termin,
            termin_tekst=termin_tekst,
            strona=wzorzec.strona,
            budynek=aktywnosc.budynek,
            lokal=aktywnosc.lokal,
            notatka=aktywnosc.notatka,
        ))

    # „Pan ma wysłać zdjęcia” to obietnica klienta, a nie nasze zadanie —
    # nawet jeśli złapał je wzorzec „prosi … zdjęcia”.
    if RE_KLIENT_DOSYLA.search(t) and not RE_AGENT_WYSYLA.search(t):
        znalezione = [z for z in znalezione if z.typ != ZAD_WYSLAC]

    # „Przypomnienie” to najsłabszy sygnał — nie dubluj go przy konkretach.
    if len(znalezione) > 1:
        znalezione = [z for z in znalezione if z.typ != ZAD_PRZYPOMNIENIE] or znalezione
    return znalezione


def wykryj_w_aktywnosciach(aktywnosci: list[Activity]) -> list[Zadanie]:
    zadania: list[Zadanie] = []
    for a in aktywnosci:
        zadania.extend(wykryj_zadania(a))
    return zadania


# --- tematy ---------------------------------------------------------------

#: Wyniki, które same w sobie są tematem wartym przejrzenia.
WYNIKI_TEMATYCZNE = ("lead", "sygnal", "info_rynkowe")

#: Nazwy etykiet po ludzku — w filtrach i na liście notatek.
OPISY_ETYKIET = {
    "lead": "Lead",
    "sygnal": "Sygnał sprzedaży",
    "info_rynkowe": "Informacja rynkowa",
    "kontakt_pozytywny": "Kontakt pozytywny",
    "kontakt_negatywny": "Kontakt negatywny",
    "obiekcja_prowizja": "Obiekcja: prowizja",
    "konkurencja": "Konkurencja",
    "pustostan": "Pustostan",
    "spadek": "Spadek",
    "bariera_jezykowa": "Bariera językowa",
    "odeslano_gdzie_indziej": "Odesłano gdzie indziej",
}


def opis_etykiety(etykieta: str) -> str:
    return OPISY_ETYKIET.get(etykieta, etykieta.replace("_", " ").capitalize())


def obserwacje(aktywnosci: list[Activity]) -> list[dict]:
    """Pojedyncze notatki warte przejrzenia — po jednej pozycji na notatkę.

    Grupowanie po temacie było wygodne do liczenia, ale nie do pracy: żeby
    odhaczyć jedną notatkę, trzeba było zaakceptować albo odrzucić cały wątek.
    Tutaj każda notatka jest osobną pozycją i sama nosi swoje etykiety.
    """
    wynik = []
    for a in aktywnosci:
        etykiety = list(a.tagi)
        if a.wynik in WYNIKI_TEMATYCZNE:
            etykiety.insert(0, a.wynik)
        if not etykiety:
            continue
        wynik.append({
            "aktywnosc": a,
            "etykiety": etykiety,
            "waga": (0 if a.wynik == "lead" else 1 if a.wynik == "sygnal" else 2),
        })
    # najpierw leady i sygnały, potem reszta — w każdej grupie od najnowszych
    wynik.sort(key=lambda o: (o["waga"], -o["aktywnosc"].data.timestamp()))
    return wynik


def dostepne_etykiety(aktywnosci: list[Activity]) -> list[tuple[str, int]]:
    """Wszystkie etykiety obecne w danych wraz z licznością — do filtra."""
    licznik: dict[str, int] = {}
    for o in obserwacje(aktywnosci):
        for e in o["etykiety"]:
            licznik[e] = licznik.get(e, 0) + 1
    return sorted(licznik.items(), key=lambda x: -x[1])


def tematy(aktywnosci: list[Activity], min_wystapien: int = 2) -> list[dict]:
    """Powtarzające się wątki z notatek — materiał na szkolenie i na skrypty.

    Bierze tagi nadane przy klasyfikacji i zestawia je z przykładami, żeby
    „12 × obiekcja prowizji” dało się przeczytać jako konkretne zdania,
    które ludzie naprawdę słyszą.
    """
    zbiorczo: dict[str, list[Activity]] = {}
    for a in aktywnosci:
        for tag in a.tagi:
            zbiorczo.setdefault(tag, []).append(a)

    wynik = []
    for tag, lista in sorted(zbiorczo.items(), key=lambda x: -len(x[1])):
        if len(lista) < min_wystapien:
            continue
        wynik.append({
            "temat": tag,
            "ile": len(lista),
            "udzial_proc": round(100 * len(lista) / max(len(aktywnosci), 1), 1),
            "przyklady": [
                {"adres": f"{a.budynek} {a.lokal}".strip(), "notatka": a.notatka}
                for a in lista[:5]
            ],
            "budynki": sorted({a.budynek for a in lista if a.budynek}),
        })
    return wynik
