"""Wczytywanie ustawień z pliku `.env`.

Klucz API trzeba jakoś podać programowi. Ustawianie zmiennych środowiskowych
w systemie jest niewygodne — przy uruchamianiu przez dwuklik w ogóle nie
działa, bo Finder nie czyta profilu powłoki. Dlatego wystarczy plik `.env`
w katalogu programu:

    ANTHROPIC_API_KEY=sk-ant-...

Plik jest w `.gitignore`, więc klucz nie trafi do repozytorium.
"""

from __future__ import annotations

import os
from pathlib import Path

NAZWA_PLIKU = ".env"


def wczytaj_env(katalog: str | Path | None = None) -> list[str]:
    """Wczytuje `.env` do zmiennych środowiskowych. Zwraca nazwy wczytanych kluczy.

    Zmienna już ustawiona w systemie **wygrywa** — plik jest wygodą, a nie
    nadpisywaczem świadomej konfiguracji.
    """
    korzen = Path(katalog) if katalog else Path(__file__).resolve().parents[2]
    plik = korzen / NAZWA_PLIKU
    if not plik.is_file():
        return []

    wczytane = []
    for linia in plik.read_text(encoding="utf-8").splitlines():
        linia = linia.strip()
        if not linia or linia.startswith("#") or "=" not in linia:
            continue
        nazwa, _, wartosc = linia.partition("=")
        nazwa = nazwa.strip()
        wartosc = wartosc.strip().strip('"').strip("'")
        if nazwa and wartosc and nazwa not in os.environ:
            os.environ[nazwa] = wartosc
            wczytane.append(nazwa)
    return wczytane


def sciezka_env(katalog: str | Path | None = None) -> Path:
    korzen = Path(katalog) if katalog else Path(__file__).resolve().parents[2]
    return korzen / NAZWA_PLIKU


def czy_jest_klucz() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))
