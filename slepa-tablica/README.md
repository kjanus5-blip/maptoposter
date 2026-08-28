# Ślepa Tablica

Trener tablic anatomicznych. Wgrywasz zdjęcie tablicy z podpisami, zaznaczasz nazwy —
aplikacja zakrywa je i stawia w ich miejsce numerowane punkty, a potem odpytuje Cię
z każdego z nich i pilnuje powtórek.

Cała aplikacja to jeden plik `index.html`. Nie ma serwera, konta ani wysyłania czegokolwiek
na zewnątrz: zdjęcia i postępy siedzą w IndexedDB Twojej przeglądarki.

## Uruchomienie

```bash
cd slepa-tablica
python3 -m http.server 8000
# otwórz http://localhost:8000
```

Serwer jest potrzebny, bo przeglądarki blokują IndexedDB przy otwieraniu plików przez `file://`.

## Jak się tego używa

1. **Wgraj tablicę** — przeciągnij zdjęcie, wklej ze schowka (`Ctrl`+`V`) albo wybierz plik.
   Zdjęcie jest zmniejszane do 2400 px dłuższego boku.
2. **Opisz** — przeciągnij myszą prostokąt po podpisie. Podpis znika pod łatką w kolorze tła,
   a w jego miejscu pojawia się numerowany punkt. Wpisz prawidłową nazwę i naciśnij `Enter`.
   Linie odniesienia narysowane na tablicy zostają, więc punkt dalej wskazuje właściwą strukturę.
   - kilka poprawnych wersji rozdziel średnikiem: `biceps brachii; mięsień dwugłowy ramienia`
   - część nieobowiązkowa w nawiasie: `(musculus) deltoideus`
   - skróty `m.`, `a.`, `v.`, `n.`, `lig.`, `proc.` są rozwijane automatycznie
   - przycisk **Rozpoznaj podpisy** próbuje odczytać je automatycznie (OCR, wymaga internetu
     przy pierwszym użyciu — pobiera ~15 MB modelu języka polskiego). Wyniki zawsze warto sprawdzić.
3. **Ucz się** — trzy tryby:
   - *Wpisz nazwę* — pokazuje przybliżony punkt, wpisujesz nazwę,
   - *Wybierz z listy* — cztery odpowiedzi,
   - *Wskaż na tablicy* — podana nazwa, klikasz właściwy punkt.
4. **Postępy** — system pudełek (Leitner): 0 → 1 → 3 → 7 → 21 dni. Pomyłka cofa punkt na start.

Sprawdzanie odpowiedzi jest wyrozumiałe: literówka, inna kolejność słów, brak ogonków
i skróty przechodzą jako poprawne, ale zawsze pokazuję prawidłową pisownię.

## Kopie i dzielenie się

- **⤓ przy talii** — zapisuje całą talię (zdjęcie + nazwy + postępy) do pliku `.json`.
- **Wczytaj talię** — wczytuje taki plik z powrotem, także na innym urządzeniu.
- **⤓ PNG** w edytorze — zapisuje samą ślepą tablicę z numerami, do wydruku.

## Gotowa talia z pliku

`make-deck.mjs` składa taką talię ze zdjęcia i listy podpisów — przydatne, gdy współrzędne
podpisów masz już spisane:

```bash
node make-deck.mjs tablica.jpg podpisy.json > talia.json
```

`podpisy.json` to lista pozycji względnych (0–1) liczonych od lewego górnego rogu zdjęcia:

```json
[
  {"name": "Caput femoris", "box": [0.11, 0.15, 0.19, 0.03]},
  {"name": "Collum femoris", "box": [0.11, 0.24, 0.20, 0.03], "note": "część bliższa"}
]
```

Powstały plik wczytuje się w aplikacji przyciskiem **Wczytaj talię**.
