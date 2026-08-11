"""Klasyfikacja notatek z CRM — warstwa regułowa (offline, deterministyczna).

Notatki agentów są krótkie, pisane w biegu i pełne literówek ("nie chce
sporzedawać", "Nioe chce sprzedawasć"). Reguły działają na tekście
znormalizowanym (bez ogonków, małe litery), a wzorce są celowo luźne —
dopasowują rdzeń słowa, nie całą formę.

To jest szybka i darmowa warstwa bazowa. Dokładniejszą klasyfikację robi
opcjonalny przebieg LLM (`analityk klasyfikuj --llm`), który nadpisuje wynik
tam, gdzie reguły nie dały pewnej odpowiedzi.
"""

from __future__ import annotations

import re

from .models import (
    Activity,
    WYNIK_BRAK_INFO,
    WYNIK_BRAK_KONTAKTU,
    WYNIK_INFO_RYNKOWE,
    WYNIK_LEAD,
    WYNIK_NIE_WLASCICIEL,
    WYNIK_NIEOKRESLONY,
    WYNIK_ODMOWA,
    WYNIK_ODMOWA_TWARDA,
    WYNIK_SYGNAL,
)

_OGONKI = str.maketrans("ąćęłńóśźż", "acelnoszz")


def normalizuj(tekst: str) -> str:
    t = (tekst or "").lower().translate(_OGONKI)
    return re.sub(r"[^a-z0-9 ]+", " ", re.sub(r"\s+", " ", t)).strip()


# Kolejność ma znaczenie tylko wewnątrz jednej kategorii — o wyniku decyduje
# PRIORYTET poniżej, a nie kolejność dopasowania.
REGULY: dict[str, list[str]] = {
    WYNIK_LEAD: [
        r"(?<!nie )\bchce sprzedac",
        r"(?<!nie )\bchcialaby sprzedac",
        r"(?<!nie )\bchcialby sprzedac",
        r"(?<!nie )\bjest zainteresowan",
        r"\bprosi o kontakt",
        r"\bumowion\w* spotkani",
        r"\bmoge przyjsc",
        r"\bpodal\w* numer",
    ],
    WYNIK_SYGNAL: [
        r"\bprzemysl",
        r"\bsie odezwie",
        r"\bchyba chciala",
        r"\bchyba chcial\b",
        r"\bmoze za rok",
        r"\bw przyszlosci",
        r"\bpod \d+ .{0,20}chcial",
        r"\bzastanowi",
        r"\bkiedys\b",
    ],
    WYNIK_NIE_WLASCICIEL: [
        r"\bnajemc",
        r"\bwynajmuj",
        r"\bwynajmowan",
        r"\bnie jest (juz )?wlascic",
        r"\bnie ma zadnego mieszkania",
        r"\bod swojego wujka",
    ],
    WYNIK_INFO_RYNKOWE: [
        r"\bsie sprzedalo",
        r"\bktos kupil",
        r"\bsprzedawal",
        r"\bwyglada na puste",
        r"\blisty w skrzynkach",
        r"\bremontuj",
        r"\bdwie osoby .{0,15}zmarly",
        r"\bzmarl",
        r"\bktos do niej dzwonil",
        r"\bz nami gadal",
        r"\bsa ulotki",
        r"\bogloszen",
        r"\bbeda wisiec kartki",
    ],
    WYNIK_ODMOWA_TWARDA: [
        r"\brozlaczyl",
        r"\bnie chc\w* (ze mna|z nami|dalej)",
        r"\bnie chcial\w* (ze mna|z nami)",
        r"\bnie chcial\w* mi otworzyc",
        r"\bnie otworzyl",
        r"\bnie chcial\w* (za bardzo )?(gadac|rozmawiac)",
        r"\bzebym poszla sobie",
        r"\bniemila",
        r"\bnie ufna",
    ],
    WYNIK_ODMOWA: [
        r"\bnie chc",
        r"\bnie bedzie chcial",
        r"\bnie sprzedaje",
        r"\bnie sprzedaj\w*\b",
        r"\bna pewno nie",
        r"\bnie ma sie w planach",
        r"\bnie w planach",
        r"\bnie te czasy",
        r"\bnie jest zainteresowan",
        r"\bn\w{0,3}e chce\b",  # tolerancja na literówki: "nioe chce", "nei chce"
    ],
    WYNIK_BRAK_INFO: [
        r"\bnic nie slysz",
        r"\bnie slyszal",
        r"\bnie slyszel",
        r"\bnic nie wie",
        r"\bnic jej nie wiadomo",
        r"\bnic tu(taj)? nie",
        r"\bnikt nic",
        r"\bblad w numerze",
    ],
    WYNIK_BRAK_KONTAKTU: [
        r"\bnie zastal",
        r"\bnikogo nie bylo",
        r"\bnie odebra",
        r"\bbrak kontaktu",
        r"\bpoczta glosowa",
    ],
}

#: Od najcenniejszego dla biznesu do najmniej wnoszącego.
PRIORYTET = [
    WYNIK_LEAD,
    WYNIK_SYGNAL,
    WYNIK_NIE_WLASCICIEL,
    WYNIK_INFO_RYNKOWE,
    WYNIK_ODMOWA_TWARDA,
    WYNIK_ODMOWA,
    WYNIK_BRAK_INFO,
    WYNIK_BRAK_KONTAKTU,
]

TAGI = {
    "kontakt_pozytywny": [r"\bmila\b", r"\bbardzo mila", r"\bdziekuje", r"\bsympatyczn"],
    "kontakt_negatywny": [r"\bniemila", r"\brozlaczyl", r"\budawal", r"\bnie ufna"],
    "obiekcja_prowizja": [r"\bprowizj", r"\bze strony kupujacego"],
    "konkurencja": [r"\bktos do niej dzwonil", r"\bz nami gadal", r"\binna agencj", r"\bbiuro juz"],
    "pustostan": [r"\bwyglada na puste", r"\blisty w skrzynkach", r"\bpustostan"],
    "spadek": [r"\bzmarl", r"\bspadk"],
    "bariera_jezykowa": [r"\bnie mowi po polsku", r"\bz zagranicy"],
    "odeslano_gdzie_indziej": [r"\bspoldziel", r"\bzarzad\w* wspolnot"],
}

MATERIAL = [r"\bzostawi\w* .{0,20}wizytowk", r"\bwizytowk\w* w sms", r"\bzostawi\w* ulotk",
            r"\bwizytowka przed klatka", r"\bzawisi na tablicy"]

KOLEJNY_KROK = [r"\bwroce\b", r"\bodezwe sie", r"\boddzwoni", r"\bumowi\w* sie",
                r"\bza tydzien", r"\bza miesiac", r"\bmam wrocic", r"\bzadzwoni\w* pozniej",
                r"\bsie odezwie", r"\bprzemysl"]


def _pasuje(tekst: str, wzorce: list[str]) -> bool:
    return any(re.search(w, tekst) for w in wzorce)


def sklasyfikuj_notatke(notatka: str) -> tuple[str, list[str], bool, bool]:
    """Zwraca (wynik, tagi, zostawiono_material, zaplanowany_kolejny_krok)."""
    t = normalizuj(notatka)
    if len(t) < 3:
        return WYNIK_BRAK_KONTAKTU, [], False, False

    trafienia = {w for w, wzorce in REGULY.items() if _pasuje(t, wzorce)}
    wynik = next((w for w in PRIORYTET if w in trafienia), WYNIK_NIEOKRESLONY)

    tagi = sorted(nazwa for nazwa, wzorce in TAGI.items() if _pasuje(t, wzorce))
    return wynik, tagi, _pasuje(t, MATERIAL), _pasuje(t, KOLEJNY_KROK)


def sklasyfikuj(aktywnosci: list[Activity]) -> list[Activity]:
    """Uzupełnia pola pochodne w miejscu i zwraca tę samą listę."""
    for a in aktywnosci:
        wynik, tagi, material, krok = sklasyfikuj_notatke(a.notatka)
        a.wynik = wynik
        a.tagi = tagi
        a.zostawiono_material = material
        a.zaplanowany_kolejny_krok = krok
    return aktywnosci
