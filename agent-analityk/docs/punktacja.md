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

---

## Tabela: agenci (collaboratori)

| Kod | Wskaźnik | Punkty | Skąd liczba |
|---|---|---|---|
| IM3 | Kontakty z ricerki | 4 | **automatycznie** z eksportu aktywności |
| NT11 | Nowe notizie | 30 | ręcznie |
| NT17 | Notizie zkontaktowane | 10 | ręcznie |
| NT15 | Spotkania acquisizione (ACQ) | 100 | ręcznie |
| NT16 | Spotkania acquisizione (AFF) | 12,5 | ręcznie |
| IN1 | Nowe incarichi sprzedaż | 500 | ręcznie |
| IN2 | Nowe incarichi wynajem | 75 | ręcznie |
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

Eksport „Analiza Działań i Spotkań” zawiera tylko aktywności kontaktowe,
więc automatycznie liczą się z niego **dwa** wskaźniki:

- **IM3** — aktywności z podtypem `RICERCA`,
- **R4** — telefony z podtypem zawierającym „propozycj”.

Reszta pochodzi z innych modułów CRM (notizie, incarichi, rapporti). Do czasu
podłączenia tych eksportów wpisuje się je ręcznie: karta pracownika →
sekcja **„Uzupełnij wskaźniki za okres”**. Zasady:

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
