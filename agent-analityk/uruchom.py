#!/usr/bin/env python3
"""Najprostsze wejście do systemu — działa tak samo na Windows, macOS i Linuksie.

    python uruchom.py                      # panel WWW + otwarcie przeglądarki
    python uruchom.py wczytaj plik.pdf     # dowolna komenda z wiersza poleceń
    python uruchom.py zespol --okres miesiac

Ten plik istnieje po to, żeby nie trzeba było ustawiać PYTHONPATH — na
Windowsie robi się to inaczej niż na macOS i to jest najczęstsze miejsce,
w którym ludzie się zacinają przy pierwszym uruchomieniu.
"""

from __future__ import annotations

import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from analityk.cli import main  # noqa: E402


def _otworz_przegladarke(adres: str, opoznienie: float = 1.5) -> None:
    """Otwiera panel w przeglądarce chwilę po starcie serwera."""
    threading.Timer(opoznienie, lambda: webbrowser.open(adres)).start()


if __name__ == "__main__":
    argumenty = sys.argv[1:] or ["serwer"]
    if argumenty[0] == "serwer" and "--bez-przegladarki" not in argumenty:
        port = "5000"
        if "--port" in argumenty:
            port = argumenty[argumenty.index("--port") + 1]
        _otworz_przegladarke(f"http://127.0.0.1:{port}")
    argumenty = [a for a in argumenty if a != "--bez-przegladarki"]
    raise SystemExit(main(argumenty))
