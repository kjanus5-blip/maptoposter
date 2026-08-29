#!/bin/bash
# Dwuklik uruchamia Ślepą Tablicę: mały serwer na tym komputerze + otwarcie przeglądarki.
# Okno terminala zostaw otwarte na czas nauki; zamknięcie go zatrzymuje aplikację.
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "Nie znalazłem Pythona 3. Zainstaluj go ze strony python.org i uruchom ponownie."
  read -r -p "Naciśnij Enter, żeby zamknąć."
  exit 1
fi

PORT=8000
while lsof -i ":$PORT" >/dev/null 2>&1; do PORT=$((PORT + 1)); done   # port zajęty? bierzemy następny

echo "Ślepa Tablica działa: http://localhost:$PORT"
echo "Zamknij to okno albo naciśnij Ctrl+C, żeby ją zatrzymać."
( sleep 1; open "http://localhost:$PORT" ) &
python3 -m http.server "$PORT" --bind 127.0.0.1
