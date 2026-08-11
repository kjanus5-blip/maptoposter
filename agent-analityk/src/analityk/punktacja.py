"""Oficjalna punktacja sieci: klasyfikacja agentów, koordynatorek i biur.

Tabele przepisane 1:1 z materiału „KLASYFIKACJA COLLABORATORI / KOORDYNATOREK
/ BIUR”. To jest system punktowy, którego biuro faktycznie używa, więc to on —
a nie żaden wymyślony wskaźnik — jest podstawą rankingów.

## Skąd biorą się liczniki

Eksport „Analiza Działań i Spotkań” zawiera tylko część wskaźników. Reszta
siedzi w innych modułach CRM (notizie, incarichi, rapporti). Dlatego każdy
wskaźnik ma oznaczone źródło:

* ``AUTO``   — liczone automatycznie z wczytanych aktywności,
* ``RECZNE`` — wpisywane w panelu albo wgrywane osobnym plikiem, dopóki nie
  podłączymy odpowiedniego eksportu z CRM.

Wskaźnik bez danych liczy się jako zero i jest tak pokazywany — nigdy nie
zgadujemy wartości, bo od tych punktów zależą pieniądze ludzi.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Activity
from .org import ROLA_AGENT, ROLA_KIEROWNIK, ROLA_KOORDYNATOR

AUTO = "auto"
RECZNE = "reczne"


@dataclass(frozen=True)
class Wskaznik:
    kod: str
    nazwa: str
    punkty: float
    role: tuple[str, ...]
    zrodlo: str = RECZNE
    opis: str = ""


@dataclass(frozen=True)
class Bonus:
    kod: str
    nazwa: str
    licznik: str        # kod wskaźnika w liczniku ułamka
    mianownik: str      # kod wskaźnika w mianowniku
    prog: float         # udział, powyżej którego bonus się należy
    punkty: int
    role: tuple[str, ...]


ROLE_AGENT_I_BIURO = (ROLA_AGENT, ROLA_KIEROWNIK)
ROLE_KOORD_I_BIURO = (ROLA_KOORDYNATOR,)
ROLE_WSZYSTKIE = (ROLA_AGENT, ROLA_KOORDYNATOR, ROLA_KIEROWNIK)

#: Wskaźniki punktowane. Kolejność jak w materiale źródłowym.
WSKAZNIKI: tuple[Wskaznik, ...] = (
    # --- klasyfikacja agentów (collaboratori) ---
    Wskaznik("IM3", "Kontakty z ricerki", 4, ROLE_AGENT_I_BIURO, AUTO,
             "Pukanie do drzwi i telefony w ramach akcji RICERCA"),
    Wskaznik("NT11", "Nowe notizie", 30, ROLE_AGENT_I_BIURO),
    Wskaznik("NT17", "Notizie zkontaktowane", 10, ROLE_AGENT_I_BIURO),
    Wskaznik("NT15", "Spotkania acquisizione (ACQ)", 100, ROLE_AGENT_I_BIURO),
    Wskaznik("NT16", "Spotkania acquisizione (AFF)", 12.5, ROLE_AGENT_I_BIURO),
    Wskaznik("IN1", "Nowe incarichi sprzedaż", 500, ROLE_AGENT_I_BIURO),
    Wskaznik("IN2", "Nowe incarichi wynajem", 75, ROLE_AGENT_I_BIURO),
    Wskaznik("IN18", "Visite mensili", 30, ROLE_AGENT_I_BIURO),
    Wskaznik("IN19", "Obniżka ceny", 50, ROLE_AGENT_I_BIURO),
    Wskaznik("RS1", "Sprzedaż", 2000, ROLE_AGENT_I_BIURO),
    Wskaznik("RS2", "Wynajem", 250, ROLE_AGENT_I_BIURO),
    Wskaznik("R12", "Zlecenie z załącznikiem", 10, ROLE_AGENT_I_BIURO),

    # --- klasyfikacja koordynatorek ---
    Wskaznik("R4", "Propozycje telefoniczne", 2, ROLE_KOORD_I_BIURO, AUTO,
             "Telefony z propozycją — rozpoznawane po podtypie aktywności"),
    Wskaznik("R6", "Uaktualnianie zleceń", 2, ROLE_KOORD_I_BIURO),
    Wskaznik("REP17", "Spotkania VEN umówione", 20, ROLE_KOORD_I_BIURO),
    Wskaznik("IN21", "Spotkania VEN wykonane (umówione przez koordynatorkę)", 30,
             ROLE_KOORD_I_BIURO),
    Wskaznik("NT10", "Notizie ze zleceń", 20, ROLE_KOORD_I_BIURO),

    # --- wspólne ---
    Wskaznik("NO10", "Spotkania KIRON", 5, ROLE_WSZYSTKIE),
)

#: Liczniki operacyjne: mierzymy je, ale klasyfikacja ich nie punktuje.
#: Telefony to praca, którą warto widzieć w raporcie — po prostu nie dają punktów.
LICZNIKI_OPERACYJNE: tuple[Wskaznik, ...] = (
    Wskaznik("TEL_WYKONANE", "Wykonane telefony", 0, ROLE_WSZYSTKIE, AUTO,
             "Tel ogólny, tel z propozycją, tel z bazy — połączenie do osoby"),
    Wskaznik("OFERTY", "Propozycje ofert (VEN)", 0, ROLE_WSZYSTKIE, AUTO,
             "Propozycja mieszkania złożona kupującemu"),
)

KODY_OPERACYJNE = {w.kod for w in LICZNIKI_OPERACYJNE}

#: Wskaźniki pomocnicze — same nie dają punktów, ale wchodzą do ułamków bonusowych.
WSKAZNIKI_POMOCNICZE: tuple[Wskaznik, ...] = (
    Wskaznik("NT13", "Notizie do zarządzania (mianownik bonusu)", 0, ROLE_WSZYSTKIE),
    Wskaznik("NT32", "Notizie zarządzone (licznik bonusu)", 0, ROLE_WSZYSTKIE),
    Wskaznik("IN3", "Incarichi w portfelu (mianownik bonusu)", 0, ROLE_WSZYSTKIE),
    Wskaznik("ZL_WSZYSTKIE", "Zlecenia razem (mianownik bonusu)", 0, ROLE_WSZYSTKIE),
    Wskaznik("ZL_PRZEANALIZOWANE", "Zlecenia przeanalizowane (licznik bonusu)", 0,
             ROLE_WSZYSTKIE),
)

BONUSY: tuple[Bonus, ...] = (
    Bonus("BON_NOTIZIA", "Zarządzanie notizią (NT32/NT13)",
          "NT32", "NT13", 0.70, 5000, ROLE_AGENT_I_BIURO),
    Bonus("BON_VISITE", "Visite mensili (IN18/IN3)",
          "IN18", "IN3", 0.80, 5000, ROLE_AGENT_I_BIURO),
    Bonus("BON_JAKOSC", "Jakość sprzedaży (RS1/IN1)",
          "RS1", "IN1", 0.50, 5000, ROLE_AGENT_I_BIURO),
    Bonus("BON_ZLECENIA", "Zlecenia przeanalizowane",
          "ZL_PRZEANALIZOWANE", "ZL_WSZYSTKIE", 0.95, 5000, ROLE_KOORD_I_BIURO),
)

#: Bonus biura za średnią na osobę — patrz `punkty_biura`.
BONUS_BIURA_ZA_OSOBE = 2500

WSZYSTKIE_KODY = {
    w.kod: w for w in WSKAZNIKI + WSKAZNIKI_POMOCNICZE + LICZNIKI_OPERACYJNE
}


def wskazniki_dla_roli(rola: str) -> list[Wskaznik]:
    """Wskaźniki liczone w klasyfikacji danej roli."""
    return [w for w in WSKAZNIKI if rola in w.role]


def wskazniki_biura() -> list[Wskaznik]:
    """Klasyfikacja biura obejmuje wskaźniki agentów i koordynatorek razem."""
    return list(WSKAZNIKI)


def bonusy_dla_roli(rola: str) -> list[Bonus]:
    return [b for b in BONUSY if rola in b.role]


# --- liczenie punktów -----------------------------------------------------

def _pozycje(licznosci: dict[str, float], wskazniki: list[Wskaznik]) -> list[dict]:
    pozycje = []
    for w in wskazniki:
        ile = licznosci.get(w.kod, 0) or 0
        pozycje.append({
            "kod": w.kod,
            "nazwa": w.nazwa,
            "ile": ile,
            "stawka": w.punkty,
            "punkty": round(ile * w.punkty, 1),
            "zrodlo": w.zrodlo,
            "brak_danych": w.kod not in licznosci,
        })
    return pozycje


def _bonusy(licznosci: dict[str, float], bonusy: list[Bonus]) -> list[dict]:
    wynik = []
    for b in bonusy:
        licznik = licznosci.get(b.licznik, 0) or 0
        mianownik = licznosci.get(b.mianownik, 0) or 0
        udzial = (licznik / mianownik) if mianownik else None
        przyznany = udzial is not None and udzial > b.prog
        wynik.append({
            "kod": b.kod,
            "nazwa": b.nazwa,
            "udzial_proc": round(100 * udzial, 1) if udzial is not None else None,
            "prog_proc": round(100 * b.prog),
            "punkty": b.punkty if przyznany else 0,
            "przyznany": przyznany,
            "brak_danych": mianownik == 0,
        })
    return wynik


def punkty_pracownika(licznosci: dict[str, float], rola: str) -> dict:
    """Klasyfikacja jednej osoby: pozycje, bonusy i suma punktów."""
    pozycje = _pozycje(licznosci, wskazniki_dla_roli(rola))
    bonusy = _bonusy(licznosci, bonusy_dla_roli(rola))
    za_aktywnosc = round(sum(p["punkty"] for p in pozycje), 1)
    za_bonusy = sum(b["punkty"] for b in bonusy)
    return {
        "rola": rola,
        "pozycje": pozycje,
        "bonusy": bonusy,
        "punkty_za_aktywnosc": za_aktywnosc,
        "punkty_bonusowe": za_bonusy,
        "punkty_razem": round(za_aktywnosc + za_bonusy, 1),
        "wskazniki_bez_danych": [p["kod"] for p in pozycje if p["brak_danych"]],
        "kompletnosc_proc": round(
            100 * sum(1 for p in pozycje if not p["brak_danych"]) / max(len(pozycje), 1), 1
        ),
    }


def punkty_biura(licznosci: dict[str, float], liczba_osob: int = 0,
                 bonus_za_osobe: int = BONUS_BIURA_ZA_OSOBE) -> dict:
    """Klasyfikacja biura — wskaźniki agentów i koordynatorek w jednym worku.

    UWAGA co do ostatniej pozycji bonusowej („PRACOWNICY I KOORDYNATORKI —
    MEDIA CADAUNO — 2.500”): materiał źródłowy nie precyzuje, czy to punkty za
    każdą osobę, czy próg liczony od średniej na osobę. Przyjęto najprostszy
    odczyt — `liczba_osob × 2500` — i wyodrębniono go jako osobną pozycję,
    żeby dało się go poprawić jedną liczbą, gdy zasada się doprecyzuje.
    """
    pozycje = _pozycje(licznosci, wskazniki_biura())
    bonusy = _bonusy(licznosci, list(BONUSY))
    za_aktywnosc = round(sum(p["punkty"] for p in pozycje), 1)
    za_bonusy = sum(b["punkty"] for b in bonusy)
    za_zespol = liczba_osob * bonus_za_osobe

    bonusy.append({
        "kod": "BON_ZESPOL",
        "nazwa": f"Pracownicy i koordynatorki ({liczba_osob} × {bonus_za_osobe})",
        "udzial_proc": None,
        "prog_proc": None,
        "punkty": za_zespol,
        "przyznany": za_zespol > 0,
        "brak_danych": False,
        "do_potwierdzenia": True,
    })

    return {
        "rola": "biuro",
        "pozycje": pozycje,
        "bonusy": bonusy,
        "punkty_za_aktywnosc": za_aktywnosc,
        "punkty_bonusowe": za_bonusy + za_zespol,
        "punkty_razem": round(za_aktywnosc + za_bonusy + za_zespol, 1),
        "wskazniki_bez_danych": [p["kod"] for p in pozycje if p["brak_danych"]],
        "kompletnosc_proc": round(
            100 * sum(1 for p in pozycje if not p["brak_danych"]) / max(len(pozycje), 1), 1
        ),
    }


# --- co da się policzyć z eksportu aktywności -----------------------------

#: Wstępne mapowanie typów aktywności z CRM na kody wskaźników.
#: Panel („Typy aktywności") pozwala je poprawić i dopisać brakujące —
#: te wartości to tylko punkt startowy, nie prawda objawiona.
#: Domyślne reguły: wzorzec -> (kod, opis, warunek).
#: Warunek to dodatkowy fragment tekstu, który musi wystąpić w wierszu —
#: dzięki temu ten sam typ trafia do różnych wskaźników zależnie od kontekstu
#: (ACQ na wynajem to AFF/NT16, a nie NT15).
MAPOWANIE_DOMYSLNE: dict[str, tuple[str, str, str]] = {
    "ricerca":       ("IM3",  "Kontakty z akcji ricerca", ""),

    # ACQ: sprzedaż -> NT15, wynajem -> NT16. Reguła z warunkiem ma pierwszeństwo.
    "acq|wynajem":   ("NT16", "ACQ na wynajem (AFF)", "wynajem"),
    "acq|najem":     ("NT16", "ACQ na najem (AFF)", "najem"),
    "acq|affitto":   ("NT16", "ACQ na wynajem (AFF)", "affitto"),
    "acq":           ("NT15", "ACQ — spotkanie acquisizione (sprzedaż)", ""),
    "acquisizione":  ("NT15", "Acquisizione (sprzedaż)", ""),
    "aff":           ("NT16", "AFF — acquisizione na wynajem", ""),

    "ven":           ("IN21", "VEN / VEN telefoniczna — spotkanie wykonane", ""),
    "v.m":           ("IN18", "Visita mensile", ""),
    "vm":            ("IN18", "Visita mensile", ""),
    "visita mensile": ("IN18", "Visita mensile", ""),

    # Nie punktowane, ale liczone osobno:
    "tel ogolny":    ("TEL_WYKONANE", "Telefon ogólny", ""),
    "tel ogólny":    ("TEL_WYKONANE", "Telefon ogólny", ""),
    "propozycj":     ("TEL_WYKONANE", "Telefon z propozycją", ""),
    "z bazy":        ("TEL_WYKONANE", "Telefon z bazy danych", ""),
    "oferta":        ("OFERTY", "Propozycja mieszkania (VEN)", ""),
}


def _pasuje_wzorzec(tekst: str, wzorzec: str) -> bool:
    """Dopasowanie po całym słowie, żeby „ven” nie łapało się w środku wyrazu."""
    if not wzorzec:
        return False
    if len(wzorzec) <= 4:                      # krótkie kody: ACQ, AFF, VEN
        return re.search(rf"\b{re.escape(wzorzec)}\b", tekst) is not None
    return wzorzec in tekst


def _reguly(mapowanie: dict) -> list[tuple[str, str, str]]:
    """Normalizuje mapowanie do listy (wzorzec, kod, warunek).

    Reguły z warunkiem idą pierwsze — inaczej „acq” złapałoby wiersz wynajmu,
    zanim doszłoby do reguły „acq + wynajem”.
    """
    reguly = []
    for wzorzec, dane in mapowanie.items():
        if isinstance(dane, dict):
            kod, warunek = dane.get("kod", ""), dane.get("warunek", "") or ""
        elif isinstance(dane, (tuple, list)):
            kod = dane[0]
            warunek = dane[2] if len(dane) > 2 else ""
        else:
            kod, warunek = dane, ""
        if kod:
            # wzorzec „acq|wynajem” to zapis skrócony: typ | warunek
            czysty = wzorzec.split("|")[0].strip()
            reguly.append((czysty, kod, warunek.lower()))
    reguly.sort(key=lambda r: (not r[2], -len(r[0])))   # najpierw z warunkiem
    return reguly


def dopasuj_kod(aktywnosc: Activity, reguly: list[tuple[str, str, str]]) -> str:
    """Kod wskaźnika dla jednej aktywności albo pusty string."""
    tekst_typu = f"{aktywnosc.podtyp or ''} {aktywnosc.kanal or ''}".lower()
    # warunku szukamy w całym wierszu — nie wiemy z góry, w której kolumnie
    # CRM trzyma rozróżnienie sprzedaż/wynajem
    kontekst = " ".join([
        aktywnosc.podtyp or "", aktywnosc.kanal or "",
        aktywnosc.powiazanie or "", aktywnosc.notatka or "",
    ]).lower()
    for wzorzec, kod, warunek in reguly:
        if not _pasuje_wzorzec(tekst_typu, wzorzec):
            continue
        if warunek and warunek not in kontekst:
            continue
        return kod
    return ""


def licznosci_z_aktywnosci(aktywnosci: list[Activity],
                           mapowanie: dict | None = None) -> dict[str, float]:
    """Zlicza aktywności według mapowania „typ z CRM → kod wskaźnika”.

    Bez mapowania używa wartości domyślnych. Typ, którego nikt nie zmapował,
    **nie jest zgadywany** — trafia na listę nieprzypisanych w panelu, żeby
    było widać, że coś się nie liczy.
    """
    if mapowanie is None:
        mapowanie = MAPOWANIE_DOMYSLNE
    reguly = _reguly(mapowanie)

    licznosci: dict[str, float] = {}
    for a in aktywnosci:
        kod = dopasuj_kod(a, reguly)
        if kod:
            licznosci[kod] = licznosci.get(kod, 0) + 1
    return licznosci


def niezmapowane_typy(typy: list[dict], mapowanie: dict) -> list[dict]:
    """Typy obecne w danych, którym nie odpowiada żaden wskaźnik."""
    wzorce = [w for w, _, _ in _reguly(mapowanie)]
    braki = []
    for t in typy:
        tekst = f"{t.get('podtyp') or ''} {t.get('kanal') or ''}".lower()
        if not any(_pasuje_wzorzec(tekst, w) for w in wzorce):
            braki.append(t)
    return braki


def licznosci_okresu(baza, pracownik_klucz: str, typ_okresu: str, klucz_okresu: str,
                     aktywnosci: list[Activity] | None = None,
                     od: str = "", do: str = "") -> dict[str, float]:
    """Łączy liczniki policzone z aktywności z tymi wpisanymi ręcznie.

    Wartość wpisana ręcznie **wygrywa** — pochodzi wprost z CRM, a nasze
    wyliczenie z eksportu jest tylko przybliżeniem.
    """
    if aktywnosci is None:
        aktywnosci = baza.pobierz(pracownik=pracownik_klucz, od=od or None, do=do or None)
    licznosci = licznosci_z_aktywnosci(aktywnosci, baza.mapowanie_typow() or None)
    licznosci.update(baza.wskazniki(pracownik_klucz, typ_okresu, klucz_okresu))
    return licznosci


def dopisz_punkty(baza, pracownik, typ_okresu: str, klucz_okresu: str,
                  aktywnosci: list[Activity], metryki: dict) -> dict:
    """Dokłada wynik punktowy do słownika metryk (w miejscu)."""
    licznosci = licznosci_okresu(baza, pracownik.klucz, typ_okresu, klucz_okresu, aktywnosci)
    wynik = punkty_pracownika(licznosci, pracownik.rola)
    metryki["punkty"] = wynik
    metryki["punkty_razem"] = wynik["punkty_razem"]
    metryki["punkty_kompletnosc_proc"] = wynik["kompletnosc_proc"]
    metryki["liczniki_operacyjne"] = {
        w.kod: {"nazwa": w.nazwa, "ile": licznosci.get(w.kod, 0)}
        for w in LICZNIKI_OPERACYJNE if licznosci.get(w.kod)
    }
    return metryki


def punkty_zespolu(baza, zespol, typ_okresu: str, klucz_okresu: str,
                   od: str, do: str) -> dict:
    """Klasyfikacja biura: liczniki sumowane po całym zespole."""
    razem: dict[str, float] = {}
    for p in zespol:
        licznosci = licznosci_okresu(
            baza, p.klucz, typ_okresu, klucz_okresu,
            baza.pobierz(pracownik=p.klucz, od=od, do=do),
        )
        for kod, wartosc in licznosci.items():
            razem[kod] = razem.get(kod, 0) + wartosc
    return punkty_biura(razem, liczba_osob=len(zespol))
