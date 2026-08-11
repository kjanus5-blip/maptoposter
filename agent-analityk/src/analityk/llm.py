"""Warstwa LLM — ocena okresu i (opcjonalnie) klasyfikacja notatek.

Cały kontakt z modelem jest tutaj. Reszta systemu działa bez tego pliku:
gdy nie ma klucza API, raport powstaje z metryk i heurystyki.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from .models import Activity
from .org import Pracownik
from .prompts import (
    SYSTEM_ANALITYK,
    SYSTEM_KLASYFIKATOR,
    SYSTEM_ZADANIA,
    zbuduj_prompt,
)

MODEL_DOMYSLNY = "claude-opus-5"
#: Do masowej klasyfikacji notatek wystarczy tańszy model.
MODEL_KLASYFIKACJI = "claude-sonnet-5"


class BrakKlucza(RuntimeError):
    pass


def _klient():
    try:
        import anthropic
    except ImportError as e:  # pragma: no cover
        raise BrakKlucza(
            "Brak pakietu `anthropic`. Zainstaluj: pip install anthropic"
        ) from e
    if not os.environ.get("ANTHROPIC_API_KEY"):
        from .konfiguracja import sciezka_env
        raise BrakKlucza(
            "Brak klucza API. Wklej go do pliku "
            f"{sciezka_env()} w postaci:  ANTHROPIC_API_KEY=sk-ant-...  "
            "i uruchom program ponownie. Klucz pobierzesz z console.anthropic.com. "
            "Wszystkie liczby, punkty i zadania działają bez klucza — wymaga go "
            "tylko ocena opisowa."
        )
    return anthropic.Anthropic()


def _wytnij_json(tekst: str) -> Any:
    """Model bywa gadatliwy — wyciągamy pierwszy sensowny blok JSON."""
    tekst = tekst.strip()
    tekst = re.sub(r"^```(?:json)?|```$", "", tekst, flags=re.M).strip()
    try:
        return json.loads(tekst)
    except json.JSONDecodeError:
        pass
    m = re.search(r"[\[{].*[\]}]", tekst, re.S)
    if not m:
        raise ValueError(f"Nie udało się odczytać JSON z odpowiedzi modelu: {tekst[:200]}")
    return json.loads(m.group(0))


def ocena_okresu(
    profil: Pracownik,
    typ_okresu: str,
    klucz_okresu: str,
    metryki: dict,
    trend: dict,
    ostrzezenia: list[str],
    pamiec: list[dict],
    aktywnosci: list[Activity],
    model: str = MODEL_DOMYSLNY,
    max_notatek: int = 120,
    tylko_prompt: bool = False,
    porownania: str = "",
) -> dict | str:
    """Zwraca ocenę jako dict. Z `tylko_prompt=True` zwraca sam prompt (podgląd/koszt 0)."""
    notatki = [a.notatka for a in aktywnosci if a.notatka][:max_notatek]
    prompt = zbuduj_prompt(
        profil, typ_okresu, klucz_okresu, metryki, trend, ostrzezenia, pamiec,
        notatki, porownania,
    )
    if tylko_prompt:
        return prompt

    klient = _klient()
    odp = klient.messages.create(
        model=model,
        max_tokens=4000,
        system=SYSTEM_ANALITYK,
        messages=[{"role": "user", "content": prompt}],
    )
    return _wytnij_json(odp.content[0].text)


def klasyfikuj_llm(
    aktywnosci: list[Activity],
    model: str = MODEL_KLASYFIKACJI,
    rozmiar_paczki: int = 40,
) -> list[Activity]:
    """Nadpisuje regułową klasyfikację wynikami z modelu (dokładniejsze, płatne)."""
    klient = _klient()
    for start in range(0, len(aktywnosci), rozmiar_paczki):
        paczka = aktywnosci[start:start + rozmiar_paczki]
        tresc = "\n".join(f"{i}. {a.notatka}" for i, a in enumerate(paczka))
        odp = klient.messages.create(
            model=model,
            max_tokens=4000,
            system=SYSTEM_KLASYFIKATOR,
            messages=[{"role": "user", "content": tresc}],
        )
        for pozycja in _wytnij_json(odp.content[0].text):
            i = pozycja.get("i")
            if not isinstance(i, int) or not 0 <= i < len(paczka):
                continue
            a = paczka[i]
            a.wynik = pozycja.get("wynik", a.wynik)
            a.tagi = pozycja.get("tagi", a.tagi)
            a.zostawiono_material = bool(pozycja.get("material", a.zostawiono_material))
            a.zaplanowany_kolejny_krok = bool(pozycja.get("krok", a.zaplanowany_kolejny_krok))
    return aktywnosci


def wykryj_zadania_llm(aktywnosci: list[Activity], model: str = MODEL_KLASYFIKACJI,
                       rozmiar_paczki: int = 30) -> list:
    """Wykrywanie zadań modelem — łapie to, czego reguły nie widzą.

    Model zwraca *tekst* terminu ("za tydzień"), a na datę przelicza go ten
    sam kod co w ścieżce regułowej. Dzięki temu model nie może pomylić się
    w arytmetyce kalendarza.
    """
    from .zadania import Zadanie, _id_zadania, rozwiaz_termin

    klient = _klient()
    wynik: list = []
    for start in range(0, len(aktywnosci), rozmiar_paczki):
        paczka = [a for a in aktywnosci[start:start + rozmiar_paczki] if a.notatka]
        if not paczka:
            continue
        tresc = "\n".join(f"{i}. {a.notatka}" for i, a in enumerate(paczka))
        odp = klient.messages.create(
            model=model, max_tokens=4000, system=SYSTEM_ZADANIA,
            messages=[{"role": "user", "content": tresc}],
        )
        for poz in _wytnij_json(odp.content[0].text):
            i = poz.get("i")
            if not isinstance(i, int) or not 0 <= i < len(paczka):
                continue
            a = paczka[i]
            termin, tekst = rozwiaz_termin(
                poz.get("termin_tekst") or a.notatka, a.data.date()
            )
            wynik.append(Zadanie(
                id=_id_zadania(a.id, poz.get("typ", "przypomnienie")),
                pracownik=a.pracownik, aktywnosc_id=a.id, dzien_zrodla=a.dzien,
                typ=poz.get("typ", "przypomnienie"),
                tresc=(poz.get("tresc") or "").strip()[:120],
                termin=termin, termin_tekst=poz.get("termin_tekst") or tekst,
                strona=poz.get("strona", "agent"),
                budynek=a.budynek, lokal=a.lokal, notatka=a.notatka, zrodlo="llm",
            ))
    return wynik
