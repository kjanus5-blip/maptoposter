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
from .profiles import Profil
from .prompts import (
    SYSTEM_ANALITYK,
    SYSTEM_KLASYFIKATOR,
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
        raise BrakKlucza(
            "Brak zmiennej ANTHROPIC_API_KEY — uruchom bez --llm albo ustaw klucz."
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
    profil: Profil,
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
) -> dict | str:
    """Zwraca ocenę jako dict. Z `tylko_prompt=True` zwraca sam prompt (podgląd/koszt 0)."""
    notatki = [a.notatka for a in aktywnosci if a.notatka][:max_notatek]
    prompt = zbuduj_prompt(
        profil, typ_okresu, klucz_okresu, metryki, trend, ostrzezenia, pamiec, notatki
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
