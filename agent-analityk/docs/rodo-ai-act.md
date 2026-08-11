# RODO i AI Act — co trzeba ustawić, zanim to ruszy na produkcji

To nie jest opinia prawna, tylko lista rzeczy, które w tym konkretnym
rozwiązaniu są istotne. Przed wdrożeniem na cały zespół warto skonsultować to
z prawnikiem albo IOD — pół godziny konsultacji, nie audyt.

---

## 1. Dwie kategorie danych osobowych, nie jedna

W systemie są **dwa** zbiory danych osobowych i mają różny status:

**A. Dane pracowników.** Aktywność, wyniki, ocena. Podstawa: wykonanie umowy o
pracę / B2B i prawnie uzasadniony interes pracodawcy. Kluczowe: pracownik musi
**wiedzieć**, że jego praca jest analizowana przez system z użyciem AI, co
konkretnie jest mierzone i do czego wynik służy. Zaskoczenie na tym polu psuje
zespół szybciej, niż jakikolwiek wskaźnik go naprawi.

**B. Dane mieszkańców z notatek.** I to jest poważniejsza część. W notatkach z
Twojego pliku są: dokładne adresy z numerami lokali, informacje o statusie
własności, o tym, że ktoś jest za granicą i nie mówi po polsku, że dwie osoby
w lokalu zmarły, oceny charakteru („niemiła”, „lekko nie ogarniała”). To są
dane osób, które **nie są klientami biura** i nie miały okazji niczego wyrazić.

Co z tym zrobić realnie:

- **Minimalizacja.** Notatka ma zawierać informację o nieruchomości i o statusie
  kontaktu, a nie ocenę osoby. „Nie jest zainteresowany, prosi nie wracać” — tak.
  „Starsza pani, lekko nie ogarnia” — nie. To jest też zwykła higiena zawodowa:
  taka notatka w razie skargi wygląda źle niezależnie od RODO.
- **Retencja.** Ustal, po jakim czasie kasujesz rekordy kontaktów, które nie
  stały się klientami. 12–24 miesiące to typowy zakres — cykl powrotu w
  farmingu. Dziś system nic sam nie kasuje; to trzeba dopisać.
- **Obowiązek informacyjny.** Przy pozyskiwaniu danych nie od osoby, której
  dotyczą, informację trzeba przekazać w rozsądnym terminie (art. 14 RODO) —
  w praktyce najczęściej przy pierwszym realnym kontakcie handlowym.
- **Dostęp i sprzeciw.** Ktoś może zażądać usunięcia i sprzeciwić się dalszemu
  kontaktowi. System powinien umieć oznaczyć adres jako „nie kontaktować” —
  to zresztą przydatne operacyjnie, żeby drugi agent tam nie poszedł.

---

## 2. Ocena pracownika przez AI — miejsce, gdzie trzeba uważać

Dwie regulacje ustawiają tu granice:

**RODO, art. 22.** Człowiek ma prawo nie podlegać decyzji opartej **wyłącznie**
na zautomatyzowanym przetwarzaniu, jeśli wywołuje ona skutki prawne lub
podobnie istotne — a premia, awans i zwolnienie takie skutki wywołują. Słowo
„wyłącznie” jest tu kluczowe.

**AI Act (rozporządzenie UE 2024/1689).** Systemy AI używane do oceny
wydajności i zachowania pracowników są zaklasyfikowane jako **wysokiego
ryzyka** (Załącznik III, obszar zatrudnienia). Dla pracodawcy jako użytkownika
takiego systemu oznacza to m.in. obowiązek nadzoru ze strony człowieka,
poinformowania pracowników i utrzymywania logów.

Co z tego wynika dla tego konkretnego narzędzia — i co już jest zrobione:

| Wymóg | Jak jest zaadresowany |
|---|---|
| Człowiek w pętli | Raport jest **rekomendacją**. Każda sekcja oceny AI jest tak podpisana. Decyzję podejmuje i podpisuje przełożony |
| Wyjaśnialność | Indeks jakości pracy ma jawny, prosty wzór z wagami (`WAGI_INDEKSU`). Da się pracownikowi pokazać, skąd wzięła się liczba |
| Audytowalność | Wszystkie metryki liczy kod, nie model. Ten sam plik zawsze daje ten sam wynik. Raporty są zapisywane w bazie |
| Zakres oceny | Prompt systemowy zabrania oceniania cech osobowości, zdrowia i sytuacji życiowej — tylko praca |
| Prawo do sprzeciwu | Pracownik musi mieć realną możliwość zakwestionowania raportu i dopisania swojego stanowiska |

Czego **nie wolno** zrobić z tym systemem:

- automatycznie naliczać premii albo rozwiązywać umowy na podstawie indeksu,
- używać rozpiętości dnia (pierwsza–ostatnia aktywność) jako ewidencji czasu
  pracy — to nie jest czas pracy i nie może pełnić tej roli,
- porównywać ludzi z różnych terenów wprost i wyciągać z tego konsekwencji
  kadrowych,
- oceniać na podstawie jednego dnia.

---

## 3. Przekazywanie danych do modelu

Wywołanie `--llm` wysyła do API Anthropic metryki oraz **treść notatek** — czyli
dane osobowe mieszkańców i pracownika. To wymaga:

- umowy powierzenia przetwarzania z dostawcą (Anthropic udostępnia DPA),
- wpisu w rejestrze czynności przetwarzania,
- decyzji, czy notatki w ogóle muszą jechać w całości.

Tańsza i bezpieczniejsza alternatywa, jeśli chcesz ograniczyć zakres:
uruchamiaj raporty **bez `--llm`** (same liczby i alerty — działa w całości
lokalnie), a model wołaj tylko do raportu tygodniowego, na zanonimizowanej
próbce notatek. Pseudonimizacja adresów przed wysyłką (`Dworcowa 7/10` →
`B1/L10`) to kilkanaście linijek kodu i realnie zmniejsza ryzyko — metryki i
tak liczą się lokalnie, a model do wniosków nie potrzebuje prawdziwego adresu.

---

## 4. Minimalna lista przed uruchomieniem na zespole

1. Poinformuj zespół pisemnie: co jest mierzone, po co, kto to widzi, jak
   zakwestionować raport.
2. Ustal i zapisz okres retencji danych kontaktowych.
3. Podpisz DPA z dostawcą modelu, jeśli używasz `--llm`.
4. Wprowadź zasadę notatki: fakty o nieruchomości i statusie kontaktu, bez
   ocen osób.
5. Ustal, że żadna decyzja kadrowa nie zapada bez rozmowy z człowiekiem.
6. Zabezpiecz plik bazy (`data/analityk.db`) — to jest zbiór danych osobowych,
   nie plik roboczy. Kopie zapasowe, dostęp tylko dla Ciebie.
