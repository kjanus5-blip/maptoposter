"""Kanoniczny model danych dla aktywności pracownika biura nieruchomości.

Wszystko, co wpada do systemu (eksport PDF z CRM, CSV, wpis ręczny), jest
sprowadzane do jednej płaskiej struktury `Activity`. Dzięki temu metryki i
raporty nie wiedzą nic o źródle danych.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

# --- Kanał kontaktu -------------------------------------------------------

KANAL_BEZPOSREDNI = "bezposredni"   # pukanie do drzwi / spotkanie w terenie
KANAL_TELEFON = "telefon"
KANAL_EMAIL = "email"
KANAL_SPOTKANIE = "spotkanie"       # umówione spotkanie / prezentacja
KANAL_INNY = "inny"

# --- Wynik kontaktu (klasyfikacja notatki) --------------------------------

WYNIK_LEAD = "lead"                     # deklaracja zainteresowania sprzedażą/najmem
WYNIK_SYGNAL = "sygnal"                 # miękki sygnał: "przemyśli", "może za rok"
WYNIK_INFO_RYNKOWE = "info_rynkowe"     # wiedza o rynku: ktoś sprzedał, pustostan
WYNIK_ODMOWA = "odmowa"                 # jasne "nie chcę sprzedawać"
WYNIK_ODMOWA_TWARDA = "odmowa_twarda"   # odmowa rozmowy, rozłączenie, nie otworzył
WYNIK_BRAK_INFO = "brak_info"           # rozmowa była, ale nic nie wniosła
WYNIK_NIE_WLASCICIEL = "nie_wlasciciel" # najemca / nie jest już właścicielem
WYNIK_BRAK_KONTAKTU = "brak_kontaktu"   # nikogo nie zastał / nie odebrał
WYNIK_NIEOKRESLONY = "nieokreslony"

#: Wyniki, które budują pipeline (są coś warte na przyszłość).
WYNIKI_WARTOSCIOWE = {WYNIK_LEAD, WYNIK_SYGNAL, WYNIK_INFO_RYNKOWE}


@dataclass
class Activity:
    """Pojedyncza aktywność pracownika."""

    id: str
    pracownik: str                    # znormalizowany klucz, np. "julia_baranowska"
    pracownik_nazwa: str              # nazwa jak w CRM
    data: datetime
    kanal: str
    podtyp: str = ""                  # np. RICERCA, "Tel ogólny", "Połączenie odebrane"
    powiazanie: str = ""              # surowa wartość kolumny "Związany z"
    budynek: str = ""                 # np. "Dworcowa 7"
    lokal: str = ""                   # np. "10"
    notatka: str = ""
    wynik: str = WYNIK_NIEOKRESLONY
    tagi: list[str] = field(default_factory=list)
    zostawiono_material: bool = False  # wizytówka, ulotka, SMS z kontaktem
    zaplanowany_kolejny_krok: bool = False
    zrodlo: str = ""                   # nazwa pliku wejściowego

    # --- pochodne ---------------------------------------------------------

    @property
    def dzien(self) -> str:
        return self.data.strftime("%Y-%m-%d")

    @property
    def godzina(self) -> int:
        return self.data.hour

    @property
    def wartosciowa(self) -> bool:
        return self.wynik in WYNIKI_WARTOSCIOWE

    def to_row(self) -> dict:
        d = asdict(self)
        d["data"] = self.data.isoformat(timespec="minutes")
        d["tagi"] = ",".join(self.tagi)
        return d


def klucz_pracownika(nazwa: str) -> str:
    """'Julia baranowska' -> 'julia_baranowska' (stabilny klucz techniczny)."""
    s = nazwa.strip().lower()
    zamiany = {
        "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n",
        "ó": "o", "ś": "s", "ź": "z", "ż": "z",
    }
    for k, v in zamiany.items():
        s = s.replace(k, v)
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "nieznany"


def zbuduj_id(pracownik: str, data: datetime, powiazanie: str, notatka: str) -> str:
    """Deterministyczny identyfikator — pozwala wgrywać ten sam plik wielokrotnie
    bez tworzenia duplikatów."""
    surowe = f"{pracownik}|{data.isoformat()}|{powiazanie}|{notatka}".encode("utf-8")
    return hashlib.sha1(surowe).hexdigest()[:16]


_RE_ADRES = re.compile(
    r"([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)?)"
    r"\s*(\d{1,3}[A-Za-z]?)"
)


def rozbij_adres(powiazanie: str, notatka: str = "") -> tuple[str, str]:
    """Wyciąga (budynek, lokal) z pola 'Związany z', a w razie potrzeby z notatki.

    Przykłady z CRM:
        'IM -Dworcowa 7[10] - Im -Dworcowa 7[10]' -> ('Dworcowa 7', '10')
        'KlientAnonimowy' + notatka 'mw1Kniaziewicza 32- Pani...' -> ('Kniaziewicza 32', '')
    """
    tekst = powiazanie or ""
    lokal = ""
    m_lokal = re.search(r"\[(\d+[A-Za-z]?)\]", tekst)
    if m_lokal:
        lokal = m_lokal.group(1)

    kandydat = re.sub(r"^\s*IM\s*-\s*", "", tekst, flags=re.I)
    kandydat = re.split(r"\s+-\s+", kandydat)[0]
    kandydat = re.sub(r"\[.*?\]", " ", kandydat)
    m = _RE_ADRES.search(kandydat)
    if m:
        return f"{m.group(1)} {m.group(2).upper()}", lokal

    # Telefony do klienta anonimowego mają adres w notatce ("mw1Kniaziewicza 32- ...").
    if notatka:
        oczyszczona = re.sub(r"^\s*mw\d*\s*", "", notatka.strip(), flags=re.I)
        m = _RE_ADRES.search(oczyszczona[:60])
        if m:
            return f"{m.group(1)} {m.group(2)}", lokal
    return "", lokal
