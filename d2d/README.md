# Mapa obchodu D2D

Tnie wybrane ulice na odcinki (od przecznicy do przecznicy), przypina do nich
wszystkie zaadresowane budynki z OpenStreetMap i buduje z tego dwie rzeczy:

* `out/tracker.html` — klikalna mapa: każdy dom ma status (zrobione / nikogo /
  odmowa / brak wejścia / temat / umowa) i notatkę. Stan siedzi w `localStorage`
  przeglądarki, a przycisk **Zapisz** wgrywa go do opublikowanej wersji strony,
  więc obchód przeżywa zmianę urządzenia.
* `out/mapa-odcinki.svg` (i `.png`) — ta sama mapa do druku, budynki puste w
  środku, z numerami, do zaznaczania długopisem.

## Użycie

```bash
python3 d2d/build_map.py                      # domyślnie Trójkąt we Wrocławiu
python3 d2d/build_map.py \
    --bbox 51.0975 17.038 51.1105 17.058 \
    --streets "Komuny Paryskiej" "Stanisława Worcella" \
    --heading "Trójkąt" --subheading "Wrocław" --slug trojkat
```

Nazwy ulic muszą się zgadzać z `addr:street` w OSM (pełne, z imieniem:
`Zygmunta Krasińskiego`, nie `Krasińskiego`) — skrypt wypisze, której nie
znalazł. Dane OSM lądują w `d2d/cache/` i są pobierane tylko raz.

Bez zależności zewnętrznych — sam Python 3.

## Jak powstaje podział na odcinki

1. `osm_fetch.py` ściąga bbox kaflami (API OSM odrzuca zapytania powyżej 50 tys.
   węzłów).
2. Wszystkie linie o tej samej nazwie sklejane są w ciągłe łamane.
3. Każdy węzeł wspólny z inną **nazwaną** drogą to cięcie — stąd odcinki
   „Pułaskiego → Krasińskiego”. Odcinki krótsze niż 30 m doklejają się do sąsiada.
4. Budynek trafia do odcinka, do którego ma najbliżej (rzut na łamaną), i dostaje
   stronę ulicy z parzystości numeru.
5. Odcinki bez żadnego adresu wypadają, reszta ustawia się po numerach domów.

Dane mapowe: © współtwórcy OpenStreetMap, licencja ODbL.
