#!/bin/bash
# Agent Analityk — uruchomienie na macOS przez dwuklik.
#
# Przy pierwszym razie tworzy własne środowisko Pythona (.venv) i instaluje
# zależności; potem tylko startuje panel. Port 5500 zamiast domyślnego 5000,
# bo na macOS 5000 zajmuje AirPlay Receiver.

cd "$(dirname "$0")" || exit 1
set -e

if ! command -v python3 >/dev/null 2>&1; then
  echo "Nie znaleziono Pythona. Zainstaluj go z https://www.python.org/downloads/"
  echo "Naciśnij Enter, żeby zamknąć."
  read -r
  exit 1
fi

ZNACZNIK=".venv/.zainstalowano"
if [ ! -d .venv ] || [ requirements.txt -nt "$ZNACZNIK" ]; then
  echo "Przygotowuję środowisko (to potrwa chwilę, tylko za pierwszym razem)…"
  python3 -m venv .venv
  ./.venv/bin/python -m pip install --quiet --upgrade pip
  ./.venv/bin/python -m pip install --quiet -r requirements.txt
  touch "$ZNACZNIK"
fi

echo ""
echo "  Panel startuje. Zamknij to okno albo naciśnij Ctrl+C, żeby go zatrzymać."
echo ""
exec ./.venv/bin/python uruchom.py serwer --port 5500
