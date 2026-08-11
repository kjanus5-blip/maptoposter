"""Wejście danych — jeden punkt wejścia niezależny od formatu pliku."""

from __future__ import annotations

from pathlib import Path

from ..models import Activity


def wczytaj_plik(sciezka: str | Path) -> list[Activity]:
    """Rozpoznaje format po rozszerzeniu i zwraca aktywności (bez klasyfikacji)."""
    sciezka = Path(sciezka)
    suffix = sciezka.suffix.lower()
    if suffix == ".pdf":
        from .pdf_crm import wczytaj_pdf
        return wczytaj_pdf(sciezka)
    if suffix in (".csv", ".tsv", ".txt"):
        from .csv_generic import wczytaj_csv
        return wczytaj_csv(sciezka)
    if suffix in (".xlsx", ".xls"):
        from .csv_generic import wczytaj_xlsx
        return wczytaj_xlsx(sciezka)
    raise ValueError(f"Nieobsługiwany format pliku: {sciezka.suffix}")
