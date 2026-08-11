"""Zamiana raportu HTML na plik PDF.

Świadomie **bez nowej zależności w `requirements.txt`**. Każda biblioteka do
PDF-a albo ciągnie za sobą systemowe pakiety (WeasyPrint: pango, cairo), albo
pobiera własną przeglądarkę (Playwright: ~150 MB) — a prawie każdy komputer
ma już zainstalowanego Chrome'a, Edge'a albo Brave'a, które potrafią to samo
z wiersza poleceń.

Kolejność prób jest podyktowana kosztem dla użytkownika:

1. **Przeglądarka znaleziona w systemie** — nic nie trzeba instalować, a
   wynik jest identyczny z tym, co widać na ekranie.
2. **Playwright** — jeśli ktoś go już ma w środowisku.
3. **WeasyPrint** — jeśli jest zainstalowany.

Gdy nie ma nic z powyższych, `html_do_pdf` podnosi `BrakSilnikaPDF` z
komunikatem, co zrobić. Panel łapie ten wyjątek i pokazuje go użytkownikowi
zamiast pustej pięćsetki.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

#: Ścieżka do przeglądarki podana ręcznie — dla nietypowych instalacji.
ZMIENNA_PRZEGLADARKI = "PRZEGLADARKA_PDF"

#: Typowe lokalizacje przeglądarek opartych na Chromium.
SCIEZKI_MACOS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Arc.app/Contents/MacOS/Arc",
)
SCIEZKI_WINDOWS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
)
NAZWY_W_PATH = (
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    "microsoft-edge", "brave-browser", "chrome",
)

CZAS_NA_RENDER_S = 60


class BrakSilnikaPDF(RuntimeError):
    """Nie ma czym wygenerować PDF-a — z podpowiedzią, co zainstalować."""


def znajdz_przegladarke() -> str | None:
    """Ścieżka do przeglądarki zdolnej wydrukować stronę do PDF-a."""
    wskazana = os.environ.get(ZMIENNA_PRZEGLADARKI, "").strip()
    if wskazana and Path(wskazana).exists():
        return wskazana
    for sciezka in SCIEZKI_MACOS + SCIEZKI_WINDOWS:
        if Path(sciezka).exists():
            return sciezka
    for nazwa in NAZWY_W_PATH:
        znaleziona = shutil.which(nazwa)
        if znaleziona:
            return znaleziona
    return None


def _przez_przegladarke(przegladarka: str, plik_html: Path, plik_pdf: Path) -> bool:
    """Chromium w trybie headless. Zwraca True, gdy powstał niepusty plik."""
    bazowe = [
        przegladarka, "--headless=new", "--disable-gpu", "--no-sandbox",
        f"--print-to-pdf={plik_pdf}", "--no-pdf-header-footer",
        plik_html.as_uri(),
    ]
    # Starsze wydania nie znają ani „=new”, ani „--no-pdf-header-footer”,
    # więc po nieudanej próbie schodzimy do wariantu bez tych przełączników.
    zapasowe = [
        przegladarka, "--headless", "--disable-gpu", "--no-sandbox",
        f"--print-to-pdf={plik_pdf}", plik_html.as_uri(),
    ]
    for polecenie in (bazowe, zapasowe):
        try:
            subprocess.run(polecenie, capture_output=True, timeout=CZAS_NA_RENDER_S)
        except (OSError, subprocess.SubprocessError):
            continue
        if plik_pdf.exists() and plik_pdf.stat().st_size > 0:
            return True
    return False


def _przez_playwright(html: str) -> bytes | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            strona = b.new_page()
            strona.set_content(html, wait_until="load")
            dane = strona.pdf(format="A4", print_background=True)
            b.close()
            return dane
    except Exception:          # brak pobranej przeglądarki, błąd startu itp.
        return None


def _przez_weasyprint(html: str) -> bytes | None:
    try:
        from weasyprint import HTML
    except ImportError:
        return None
    try:
        return HTML(string=html).write_pdf()
    except Exception:
        return None


def czym_zrobimy_pdf() -> str | None:
    """Nazwa dostępnego silnika albo None — do pokazania w panelu."""
    przegladarka = znajdz_przegladarke()
    if przegladarka:
        return Path(przegladarka).name
    try:
        import playwright  # noqa: F401
        return "Playwright"
    except ImportError:
        pass
    try:
        import weasyprint  # noqa: F401
        return "WeasyPrint"
    except ImportError:
        return None


def html_do_pdf(html: str) -> bytes:
    """Renderuje stronę HTML do PDF-a. Podnosi `BrakSilnikaPDF`, gdy nie ma czym."""
    przegladarka = znajdz_przegladarke()
    if przegladarka:
        with tempfile.TemporaryDirectory() as katalog:
            plik_html = Path(katalog) / "raport.html"
            plik_pdf = Path(katalog) / "raport.pdf"
            plik_html.write_text(html, encoding="utf-8")
            if _przez_przegladarke(przegladarka, plik_html, plik_pdf):
                return plik_pdf.read_bytes()

    for silnik in (_przez_playwright, _przez_weasyprint):
        dane = silnik(html)
        if dane:
            return dane

    raise BrakSilnikaPDF(
        "Nie znalazłem przeglądarki, która wydrukowałaby raport do PDF-a. "
        "Zainstaluj Google Chrome, Microsoft Edge lub Brave — albo otwórz "
        "raport i zapisz go przez Cmd+P → Zapisz jako PDF. Jeśli masz "
        "przeglądarkę w nietypowym miejscu, wskaż ją zmienną "
        f"{ZMIENNA_PRZEGLADARKI} w pliku .env."
    )


__all__ = ["BrakSilnikaPDF", "czym_zrobimy_pdf", "html_do_pdf", "znajdz_przegladarke"]
