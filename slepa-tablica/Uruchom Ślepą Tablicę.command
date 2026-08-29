#!/bin/bash
# Dwuklik uruchamia Ślepą Tablicę: mały serwer na tym komputerze + otwarcie przeglądarki.
# Okno terminala zostaw otwarte na czas nauki; zamknięcie go zatrzymuje aplikację.
cd "$(dirname "$0")" || exit 1
PORT=8000
ADRES="http://localhost:$PORT"

koniec(){ echo; read -r -p "Naciśnij Enter, żeby zamknąć to okno."; exit "${1:-0}"; }

if ! command -v python3 >/dev/null 2>&1; then
  echo "Nie znalazłem Pythona 3."
  echo "Zainstaluj go ze strony python.org (albo wpisz: xcode-select --install) i uruchom ponownie."
  koniec 1
fi
if [ ! -f index.html ]; then
  echo "Ten plik musi leżeć w katalogu z aplikacją, obok index.html."
  koniec 1
fi

# Port jest częścią adresu, a talie są zapisane pod adresem — zmiana portu ukryłaby
# całą dotychczasową naukę. Dlatego nigdy nie przeskakujemy na inny port po cichu.
if lsof -i ":$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  if curl -fsS "$ADRES/manifest.webmanifest" 2>/dev/null | grep -q "Ślepa Tablica"; then
    echo "Ślepa Tablica już działa — otwieram ją w przeglądarce."
    open "$ADRES"
    exit 0
  fi
  echo "Port $PORT jest zajęty przez inny program."
  echo "Zamknij go i uruchom ponownie — talie są zapisane pod adresem $ADRES,"
  echo "więc uruchomienie na innym porcie pokazałoby pustą bibliotekę."
  koniec 1
fi

echo "Ślepa Tablica działa: $ADRES"
echo "Zamknij to okno albo naciśnij Ctrl+C, żeby ją zatrzymać."
( sleep 1; open "$ADRES" ) &
python3 -m http.server "$PORT" --bind 127.0.0.1
