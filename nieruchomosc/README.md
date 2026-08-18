# Ustalenie właściciela / spadkobierców nieruchomości

Narzędzie pomocnicze do ustalenia, kto jest właścicielem niezamieszkanego lokalu
i jak nawiązać z nim (lub ze spadkobiercami) kontakt — zgodnie z polskimi
przepisami o dostępie do rejestrów.

## Co robi automatycznie

| Krok | Źródło | Klucz API |
|---|---|---|
| adres → współrzędne | Nominatim (OpenStreetMap) | nie |
| współrzędne → identyfikator działki, obręb, gmina, powiat | ULDK (GUGiK) | nie |
| nazwisko → działalność gospodarcza | CEIDG API v3 | `CEIDG_TOKEN` (darmowy) |
| NIP → dane podmiotu | Biała Lista VAT (MF) | nie |
| numer KRS → odpis aktualny | API Ministerstwa Sprawiedliwości | nie |
| gmina → lokalna wyszukiwarka grobów | wykrywanie instancji Grobonetu | nie |

Na końcu generuje `raport.md` ze ścieżką postępowania oraz cztery gotowe
do uzupełnienia pisma.

## Czego świadomie nie robi

- **nie omija CAPTCHA** w przeglądarce ksiąg wieczystych (EKW) ani w Rejestrze
  Spadkowym — automatyczne odpytywanie EKW jest zakazane regulaminem serwisu;
- **nie odpytuje rejestru PESEL** — nie jest publiczny, dane udostępnia się na
  wniosek po wykazaniu interesu prawnego (art. 45–46 ustawy o ewidencji ludności);
- **nie agreguje danych osobowych** osób prywatnych ani ich rodzin.

Te czynności raport opisuje jako kroki do wykonania ręcznie, z linkami.

## Kluczowa rzecz do zrozumienia

Wąskim gardłem jest **numer księgi wieczystej**, a nie dostęp do danych.
Publiczny Geoportal i ULDK numeru KW nie udostępniają. Gdy już go masz,
Dział II księgi wieczystej poda właściciela **za darmo i legalnie** —
księgi wieczyste są jawne (art. 2 ustawy o księgach wieczystych i hipotece).

Najszybsza droga do numeru KW to zwykle zarządca budynku lub spółdzielnia,
nie urząd.

## Dwa scenariusze

### A. Nie znasz właściciela — `ustal_wlasciciela.py`
Punkt wyjścia: sam adres. Ustala działkę ewidencyjną i prowadzi do numeru KW.

### B. Znasz nazwisko z Działu II, ale nie wiesz, czy osoba żyje — `szukaj_osoby.py`
Punkt wyjścia: imię i nazwisko właściciela z księgi wieczystej.

```bash
python szukaj_osoby.py \
    --imie Jan --nazwisko Kowalski \
    --ojciec Stanisław --matka Anna \
    --ma-pesel --rok-urodzenia 1938 \
    --gmina "Gliwice" \
    --wyjscie wynik
```

Generuje `osoba_<nazwisko>.md` z:

- **kontrolą kompletności danych do Rejestru Spadkowego** — rejestr przyjmuje PESEL
  albo imię + nazwisko + imiona rodziców + datę urodzenia lub zgonu, a Dział II KW
  podaje dokładnie te dane w polach 2.2.5.6, 2.2.5.7 i 2.2.5.8;
- **wykryciem lokalnej wyszukiwarki grobów** — Grobonet działa osobno dla każdej
  gminy (`<gmina>.grobonet.com`), bez wspólnego indeksu, więc skrypt sprawdza,
  czy instancja dla Twojej gminy istnieje;
- gotowymi linkami do baz krajowych (eCmentarze, Mogily), nekrologów, Monitora
  Sądowego i Gospodarczego, Geneteki, KRS i CEIDG;
- interpretacją każdego z czterech możliwych wyników.

`--ma-pesel` jest flagą, nie wartością — skrypt celowo nie przyjmuje numeru PESEL
jako argumentu, żeby nie zapisywać go w plikach ani w historii powłoki. PESEL
wpisuje się bezpośrednio w formularz Rejestru Spadkowego.

## Czego narzędzie nie wyszuka

Numerów telefonów, adresów e-mail ani „alternatywnych adresów" osób prywatnych.
W Polsce nie ma dla nich legalnego źródła publicznego — książki telefoniczne
zniknęły wraz z RODO, a serwisy typu „znajdź osobę po nazwisku" opierają się na
wyciekach danych albo na brokerach z szarej strefy. Przy transakcji nieruchomości
kontakt zdobyty taką drogą podważa dobrą wiarę nabywcy.

Legalne kanały kontaktu to: adres z Działu II KW (list polecony za potwierdzeniem
odbioru — jedyny kanał z mocą dowodową), dane kontaktowe z CEIDG podane
dobrowolnie przez samego przedsiębiorcę, oraz pośrednictwo zarządcy nieruchomości.

## Użycie

```bash
pip install requests

python ustal_wlasciciela.py \
    --adres "ul. Długa 12, Kraków" \
    --wnioskodawca "Jan Kowalski" \
    --kontakt "jan@example.com, tel. 600 000 000" \
    --cel "zakupu lokalu" \
    --wyjscie wynik
```

Przydatne opcje:

- `--wspolrzedne LAT,LON` — pomija geokodowanie, gdy adres nie jest w OSM
- `--imie` / `--nazwisko` — sprawdzenie w CEIDG (wymaga `CEIDG_TOKEN`)
- `--nip`, `--krs` — gdy właścicielem jest podmiot gospodarczy
- `--interes-prawny "…"` — uzasadnienie wpisywane do wniosków urzędowych
- `--json` — surowe odpowiedzi rejestrów na stdout

## Wygenerowane pisma

- `pismo_zarzadca.md` — prośba do wspólnoty/spółdzielni o **pośrednictwo**
  w kontakcie (nie o wydanie danych — dlatego nie wymaga interesu prawnego)
- `wniosek_kw_sad.md` — wniosek do wydziału ksiąg wieczystych o numer KW
- `wniosek_egib.md` — wniosek o wypis z ewidencji gruntów i budynków
- `zgloszenie_gmina.md` — zgłoszenie pustostanu + wniosek o rozważenie
  wystąpienia o kuratora spadku (art. 666 § 1 k.p.c.)

Pisma są szablonami — pola oznaczone kropkami trzeba uzupełnić samodzielnie,
w szczególności uzasadnienie interesu prawnego.

## Zastrzeżenie

To nie jest porada prawna. Przy sprawie spadkowej o realnej wartości
skonsultuj się z radcą prawnym lub notariuszem — postępowanie o stwierdzenie
nabycia spadku bywa tańsze i szybsze niż wygląda.
