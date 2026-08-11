"""Parser eksportu PDF z CRM ("Analiza Działań i Spotkań").

Eksport jest wydrukiem tabeli HTML do PDF-a. Nie ma w nim żadnej struktury
tabelarycznej poza cienkimi prostokątami, które rysują linie siatki — i to
one są tu jedynym pewnym punktem odniesienia:

* prostokąty o wysokości < 2 pt i szerokości > 20 pt to **poziome linie**
  rozdzielające wiersze; ich odcinki wyznaczają jednocześnie **zakresy X
  kolumn**,
* każde słowo trafia do komórki (wiersz, kolumna) na podstawie swojej pozycji.

Wiersz potrafi pęknąć na granicy stron. Fragment bez daty traktujemy jako
kontynuację i sklejamy z następnym wierszem, który datę ma.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pdfplumber

from ..models import Activity, klucz_pracownika, rozbij_adres, zbuduj_id

# Kolejność kolumn w eksporcie (po indeksie, nagłówki bywają posklejane):
# 0 Akcje | 1 Związany z | 2 Typ | 3 Podtyp | 4 Mobilny | 5 Data
# 6 Przypisany do | 7 Incarico 1 | 8 Esito incarico 1 | 9 Nota incarico 1 | 10 Opis
KOL_POWIAZANIE = 1
KOL_TYP = 2
KOL_PODTYP = 3
KOL_DATA = 5
KOL_PRACOWNIK = 6
KOL_OPIS = -1  # ostatnia kolumna

RE_DATA = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{1,2}):(\d{2})")
RE_SMIECI = re.compile(r"^(about:blank|Strona \d+ z \d+|\d{2}\.\d{2}\.\d{4},)")


def _linie_poziome(page) -> list[float]:
    """Pozycje Y poziomych linii siatki (posortowane)."""
    ys = {
        round(r["top"], 1)
        for r in page.rects
        if abs(r["bottom"] - r["top"]) < 2 and (r["x1"] - r["x0"]) > 20
    }
    return sorted(ys)


def _zakresy_kolumn(page) -> list[tuple[float, float]]:
    """Zakresy X kolumn — z odcinków pierwszej poziomej linii siatki."""
    poziome = [
        r for r in page.rects
        if abs(r["bottom"] - r["top"]) < 2 and (r["x1"] - r["x0"]) > 20
    ]
    if not poziome:
        return []
    y0 = min(round(r["top"], 1) for r in poziome)
    odcinki = sorted(
        {(round(r["x0"], 1), round(r["x1"], 1)) for r in poziome if round(r["top"], 1) == y0}
    )
    return odcinki


def _komorki_wiersza(slowa, kolumny) -> list[str]:
    """Rozdziela słowa wiersza na kolumny po współrzędnej X środka słowa."""
    kubelki: list[list[tuple[float, float, str]]] = [[] for _ in kolumny]
    for w in slowa:
        srodek = (w["x0"] + w["x1"]) / 2
        for i, (x0, x1) in enumerate(kolumny):
            if x0 - 1 <= srodek <= x1 + 1:
                kubelki[i].append((round(w["top"], 1), w["x0"], w["text"]))
                break
    komorki = []
    for kubel in kubelki:
        kubel.sort()
        komorki.append(" ".join(t for _, _, t in kubel).strip())
    return komorki


def _scal(a: list[str], b: list[str]) -> list[str]:
    return [(x + " " + y).strip() for x, y in zip(a, b)]


def _surowe_wiersze(sciezka: Path) -> Iterable[list[str]]:
    """Zwraca listy komórek — po jednej na wiersz tabeli, przez wszystkie strony.

    Wiersz przecięty granicą stron zostawia ogon na dole strony N i głowę na
    górze strony N+1. Fragment bez daty na *górze* strony dołączamy do ostatnio
    zamkniętego wiersza, fragment bez daty *niżej* — do wiersza następnego.
    """
    wiersze: list[list[str]] = []
    zawieszony: list[str] | None = None

    with pdfplumber.open(str(sciezka)) as pdf:
        for page in pdf.pages:
            pierwszy_na_stronie = True
            kolumny = _zakresy_kolumn(page)
            linie = _linie_poziome(page)
            if not kolumny or not linie:
                continue

            slowa = page.extract_words()
            # Nagłówek i stopka wydruku ("Strona 3 z 8about:blank") leżą w tych
            # samych pasmach co wiersze tabeli — kasujemy całe linie, nie słowa.
            do_wyciecia = [w["top"] for w in slowa if RE_SMIECI.match(w["text"])]
            slowa = [
                w for w in slowa
                if not any(abs(w["top"] - y) < 3 for y in do_wyciecia)
            ]
            # Pierwsza linia siatki jest *pod* pierwszym wierszem, więc pasmo
            # od góry strony też trzeba wziąć — na stronach 2+ zaczyna się tam
            # pełnoprawny rekord (na stronie 1 stoi tam nagłówek tabeli).
            granice = [0.0] + linie + [page.height]

            for i in range(len(granice) - 1):
                gora, dol = granice[i], granice[i + 1]
                w_pasie = [w for w in slowa if gora <= w["top"] < dol]
                if not w_pasie:
                    continue
                komorki = _komorki_wiersza(w_pasie, kolumny)
                if not any(komorki):
                    continue
                if "Związany" in komorki[KOL_POWIAZANIE]:  # wiersz nagłówkowy
                    continue

                ma_date = bool(RE_DATA.search(komorki[KOL_DATA] if len(komorki) > KOL_DATA else ""))
                if not ma_date:
                    if pierwszy_na_stronie and wiersze:
                        wiersze[-1] = _scal(wiersze[-1], komorki)
                    else:
                        zawieszony = komorki if zawieszony is None else _scal(zawieszony, komorki)
                    pierwszy_na_stronie = False
                    continue

                if zawieszony is not None:
                    komorki = _scal(zawieszony, komorki)
                    zawieszony = None
                wiersze.append(komorki)
                pierwszy_na_stronie = False

    yield from wiersze


def _parsuj_date(tekst: str) -> datetime | None:
    m = RE_DATA.search(tekst)
    if not m:
        return None
    d, mies, r, g, mi = m.groups()
    try:
        return datetime(int(r), int(mies), int(d), int(g), int(mi))
    except ValueError:
        return None


def _kanal(typ: str, podtyp: str) -> str:
    t = f"{typ} {podtyp}".lower()
    if "bezpośredni" in t or "bezposredni" in t or "wizyta" in t:
        return "bezposredni"
    if "telefon" in t or "połączenie" in t or "polaczenie" in t or "tel " in t:
        return "telefon"
    if "mail" in t:
        return "email"
    if "spotkanie" in t or "prezentacja" in t:
        return "spotkanie"
    return "inny"


def _sklej_nazwisko(tekst: str) -> str:
    """CRM łamie nazwisko na dwie linie: 'Julia baranowska' -> 'Julia Baranowska'."""
    czesci = [c for c in tekst.split() if c]
    return " ".join(c[:1].upper() + c[1:] for c in czesci)


def wczytaj_pdf(sciezka: str | Path) -> list[Activity]:
    """Wczytuje eksport PDF i zwraca listę aktywności (bez klasyfikacji notatek)."""
    sciezka = Path(sciezka)
    aktywnosci: list[Activity] = []

    for komorki in _surowe_wiersze(sciezka):
        data = _parsuj_date(komorki[KOL_DATA])
        if data is None:
            continue
        pracownik_nazwa = _sklej_nazwisko(komorki[KOL_PRACOWNIK])
        if not pracownik_nazwa:
            continue

        powiazanie = re.sub(r"\s+", " ", komorki[KOL_POWIAZANIE]).strip()
        notatka = re.sub(r"\s+", " ", komorki[KOL_OPIS]).strip()
        budynek, lokal = rozbij_adres(powiazanie, notatka)

        aktywnosci.append(
            Activity(
                id=zbuduj_id(pracownik_nazwa, data, powiazanie, notatka),
                pracownik=klucz_pracownika(pracownik_nazwa),
                pracownik_nazwa=pracownik_nazwa,
                data=data,
                kanal=_kanal(komorki[KOL_TYP], komorki[KOL_PODTYP]),
                podtyp=re.sub(r"\s+", " ", komorki[KOL_PODTYP]).strip(),
                powiazanie=powiazanie,
                budynek=budynek,
                lokal=lokal,
                notatka=notatka,
                zrodlo=sciezka.name,
            )
        )
    return aktywnosci
