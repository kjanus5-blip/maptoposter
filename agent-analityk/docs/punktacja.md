# Punktacja i rankingi

System liczy dwie różne rzeczy i **nie należy ich mylić**:

| | Co mierzy | Skąd |
|---|---|---|
| **Punkty** | Oficjalna klasyfikacja sieci — to, co decyduje o rankingu i premiach | Tabele „Klasyfikacja collaboratori / koordynatorek / biur” |
| **Indeks jakości (0–100)** | Jak dobrze wykonywana jest sama praca kontaktowa: ilość, dotarcie, jakość notatek, follow-up | Wyliczany z eksportu aktywności |

Punkty mówią „ile dowiózł”. Indeks mówi „jak pracuje”. Agent może mieć zero
punktów w słabym miesiącu i wysoki indeks, bo rzetelnie puka i notuje — i to
jest dokładnie ta informacja, której nie widać w samym rankingu.

Rankingi (pracowników i biur) sortowane są **po punktach**.

**Incarico** to w tej dokumentacji umowa pośrednictwa na sprzedaż lub wynajem
nieruchomości — a zamiennie sama nieruchomość, którą na jej podstawie
sprzedajemy. Stąd IN1/IN2 to nowe podpisane umowy, IN3 to portfel
nieruchomości w ofercie, a IN18 (visita mensile) to comiesięczna wizyta
u właściciela takiej nieruchomości. Bonus IN18/IN3 mierzy więc, jaka część
portfela dostała w danym miesiącu wizytę.

---

## Tabela: agenci (collaboratori)

| Kod | Wskaźnik | Punkty | Skąd liczba |
|---|---|---|---|
| IM3 | Kontakty z ricerki | 4 | **automatycznie** z eksportu aktywności |
| NT11 | Nowe notizie | 30 | ręcznie |
| NT17 | Notizie zkontaktowane | 10 | ręcznie |
| NT15 | Spotkania acquisizione (ACQ) | 100 | ręcznie |
| NT16 | Spotkania acquisizione (AFF) | 12,5 | ręcznie |
| IN1 | Nowe umowy na sprzedaż (incarico) | 500 | ręcznie |
| IN2 | Nowe umowy na wynajem (incarico) | 75 | ręcznie |
| IN18 | Visite mensili | 30 | ręcznie |
| IN19 | Obniżka ceny | 50 | ręcznie |
| RS1 | Sprzedaż | 2000 | ręcznie |
| RS2 | Wynajem | 250 | ręcznie |
| R12 | Zlecenie z załącznikiem | 10 | ręcznie |
| NO10 | Spotkania KIRON | 5 | ręcznie |

**Bonusy:** zarządzanie notizią (NT32/NT13) > 70% → 5000 · visite mensili
(IN18/IN3) > 80% → 5000 · jakość sprzedaży (RS1/IN1) > 50% → 5000.

## Tabela: koordynatorki

| Kod | Wskaźnik | Punkty | Skąd liczba |
|---|---|---|---|
| R4 | Propozycje telefoniczne | 2 | **automatycznie** (telefony z propozycją) |
| R6 | Uaktualnianie zleceń | 2 | ręcznie |
| REP17 | Spotkania VEN umówione | 20 | ręcznie |
| IN21 | Spotkania VEN wykonane (umówione przez koordynatorkę) | 30 | ręcznie |
| NT10 | Notizie ze zleceń | 20 | ręcznie |
| NO10 | Spotkania KIRON | 5 | ręcznie |

**Bonus:** zlecenia przeanalizowane > 95% → 5000.

## Tabela: biura

Biuro punktowane jest wszystkimi wskaźnikami agentów **i** koordynatorek
razem, z tymi samymi stawkami. Liczniki sumują się po całym zespole.
Bonusy: wszystkie cztery powyższe plus pozycja za zespół.

---

## Trzy rzeczy, które wymagają Twojego potwierdzenia

Materiał źródłowy jest w tych miejscach niejednoznaczny. Zaimplementowałem
najprostszy odczyt i wyodrębniłem go tak, żeby poprawka była zmianą jednej
liczby lub jednej linijki:

1. **„Pracownicy i koordynatorki — MEDIA CADAUNO — 2.500”** (bonus biura).
   Przyjęte: `liczba osób × 2500`. Inne możliwe odczytanie: próg liczony od
   średniej punktacji na osobę. W panelu ta pozycja jest oznaczona jako
   „zasada do potwierdzenia”. Stała: `BONUS_BIURA_ZA_OSOBE` w
   `src/analityk/punktacja.py`.
2. **Progi są ostre.** „>70%” traktowane jest jako *powyżej* 70%, więc równo
   70% bonusu nie daje. Jeśli w sieci liczy się „co najmniej”, zmienia się
   jeden operator w `_bonusy`.
3. **Okres rozliczeniowy.** Klasyfikacja wygląda na miesięczną, ale system
   liczy punkty dla dowolnego okresu (dzień/tydzień/miesiąc/kwartał/rok).
   Wskaźniki wpisywane ręcznie są zapisywane **per okres**, więc wpisanie ich
   dla sierpnia nie miesza się z wrześniem. Do rankingu premiowego używaj
   widoku miesięcznego.

---

## Skąd biorą się liczby

### Automatycznie: kolumna „Typ” / „Mobilny”

Aktywności z eksportu przeliczają się na wskaźniki według **mapowania typów**,
które ustawiasz sam w panelu (zakładka **Typy aktywności**). Ekran pokazuje
wszystkie typy występujące w Twoich danych wraz z licznością i tym, na jaki
wskaźnik są przeliczane. Typ, którego nikt nie zmapował, dostaje czerwoną
etykietę **„nie liczy się”** — nic nie ginie po cichu.

Ustawione reguły. O wskaźniku decydują **obie kolumny** — „Modyfikuj kontakt”
(kanał) i „typ”:

| Modyfikuj kontakt | typ | Wskaźnik | Punkty |
|---|---|---|---|
| dowolny | `RICERCA` | IM3 | 4 |
| Spotkanie / Kontakt bezpośredni | `ACQ` | NT15 | 100 |
| Spotkanie / Kontakt bezpośredni | `ACQ` + wynajem/najem/dzierżawa w wierszu | NT16 (AFF) | 12,5 |
| Spotkanie | `VEN` | IN21 | 30 |
| dowolny | `Vendita telefoniczna` | IN21 | 30 |
| Spotkanie / Telefon | `V.M.` | IN18 | 30 |
| Telefon | `Tel na ACQ` | TEL_WYKONANE | **0** |
| Połączenie odebrane / Telefon | `Telefon z propozycją *`, `Telefon ogólny`, `Tel ogólny`, `Telefon z bazy danych` | TEL_WYKONANE | **0** |
| Telefon | `Oferta` | OFERTY | **0** |
| Spotkanie | `Cont` | CONT_SPOTKANIA | **0** |
| dowolny | `Aktualizacja richiesty` | R6 | 2 |
| Spotkanie | `personale` | świadomie pomijane | — |

Bez kanału `ACQ` byłoby nie do odróżnienia od `Tel na ACQ` — telefon w sprawie
spotkania liczyłby się jako spotkanie warte 100 punktów.

Panel rozróżnia trzy stany typu: **punktowany**, **liczony bez punktów**
i **świadomie pomijany**. Ten ostatni to nie to samo co brak reguły — typ bez
reguły świeci się na czerwono („nie liczy się”), bo nie wiemy, co z nim
zrobić; typ pomijany jest szary, bo decyzja zapadła.

**Bez reguły** czeka jeszcze: `Ogólny`.

Reguła dopasowuje się, gdy nazwa typu *zawiera* podany fragment; polskie znaki
są ignorowane po obu stronach („Telefon ogólny” pasuje do wzorca `telefon
ogolny`). Kody do czterech znaków (ACQ, AFF, VEN, V.M) muszą wystąpić jako
osobne słowo, żeby nie łapały się w środku innych wyrazów. Jeden kontakt liczy
się do jednego wskaźnika.

### Reguły warunkowe

Ten sam typ może trafiać do różnych wskaźników zależnie od kontekstu. ACQ na
sprzedaż to NT15 (100 pkt), ale ACQ na wynajem to AFF, czyli NT16 (12,5 pkt).
Reguła z **warunkiem** obsługuje to bez dublowania typów: warunek to dodatkowy
fragment tekstu szukany **w całym wierszu** (typ, powiązanie, notatka), bo CRM
może trzymać rozróżnienie w różnych kolumnach.

Kolejność sprawdzania: najpierw reguły z warunkiem, potem z kanałem, potem
najdłuższy wzorzec. Bez tego gołe `acq` przechwyciłoby wiersz wynajmu.

### Liczniki operacyjne

Nie wszystko, co robi zespół, jest punktowane. Trzy rzeczy liczymy mimo to,
bo bez nich obraz pracy jest niepełny:

| Licznik | Co obejmuje |
|---|---|
| **Wykonane telefony** | `Tel ogólny`, `Telefon z propozycją kupna/wynajmu/dzierżawy`, `Telefon z bazy danych`, `Tel na ACQ` |
| **Propozycje ofert (VEN)** | `Oferta` — propozycja mieszkania złożona kupującemu |
| **Spotkania CONT** | spotkanie z kupującym po prezentacji: omówienie procesu zakupu, może skończyć się złożeniem oferty |

Widać je na karcie pracownika, ale dają zero punktów. To celowe rozdzielenie:
praca ma być widoczna, nawet gdy klasyfikacja jej nie wycenia. `CONT` jest tu
szczególnie wart obserwacji — to ostatni krok przed ofertą kupna, więc jego
liczba zapowiada, co wydarzy się w kolejnych tygodniach.

**Uwaga:** R4 („propozycje telefoniczne”, 2 pkt) to wskaźnik **koordynatorki**
z innego eksportu — nie należy go mylić z telefonami agenta w terenie.

### Ręcznie: reszta tabeli

Wskaźniki z modułów notizie / incarichi / rapporti wpisuje się na karcie
pracownika w sekcji **„Uzupełnij wskaźniki za okres”**. Zasady:

- **puste pole ≠ zero.** Puste znaczy „nie wiem” i jest tak pokazywane —
  wskaźnik ma etykietę „do wpisania”, a raport podaje procent kompletności.
  Zero wpisane świadomie liczy się jako zero.
- **wpis ręczny ma pierwszeństwo** przed wartością wyliczoną z aktywności —
  liczba z CRM jest wiarygodniejsza niż nasze przybliżenie z eksportu.
- brakujące wskaźniki liczą się jako zero w sumie punktów, więc **wynik jest
  zaniżony do czasu uzupełnienia**. Panel mówi o tym wprost przy każdej
  niekompletnej klasyfikacji — żeby nikt nie porównał osoby z uzupełnionymi
  danymi z osobą, której nikt nie uzupełnił.

## Jak to zautomatyzować

Docelowo wskaźników nie powinno się wpisywać ręcznie. Kolejność wdrożenia:

1. Sprawdź, czy CRM eksportuje raport z licznikami NT/IN/RS za okres.
2. Jeśli tak — dopisz parser w `src/analityk/ingest/` mapujący kolumny na kody
   wskaźników i wywołaj `Baza.zapisz_wskazniki`. Reszta systemu (punkty,
   rankingi, porównania, raporty) zadziała bez żadnej dalszej zmiany.
3. Wpisy ręczne zostają jako awaryjna droga i sposób na korektę.
