# Koncepcja: agent AI do zarządzania pracą agentów nieruchomości

## 1. Główna decyzja projektowa: liczby liczy kod, nie model

Naturalny odruch to wrzucić 300 notatek do modelu i poprosić o podsumowanie.
To działa raz i przestaje działać przy trzecim pracowniku:

- model liczy „około 40 kontaktów”, gdy było 47,
- ten sam plik uruchomiony dwa razy daje dwa różne wnioski,
- nie da się porównać sierpnia z lipcem, bo obie liczby są zmyślone,
- pracownik podważa raport i **ma rację**.

Dlatego podział jest sztywny:

| Warstwa | Kto robi | Cecha |
|---|---|---|
| Parsowanie i normalizacja | kod | powtarzalne |
| Metryki, konwersje, trendy, alerty | kod | powtarzalne, audytowalne |
| Klasyfikacja notatek | reguły, opcjonalnie model | reguły za darmo, model dokładniej |
| Ocena, coaching, priorytety | model | tu model jest naprawdę dobry |

Model dostaje gotowy zestaw liczb i surowe notatki, a jego zadaniem jest
**interpretacja**: co z tego wynika, co jest przyczyną, a co skutkiem, co
powiedzieć pracownikowi jutro rano.

## 2. „Osobny agent dla każdego pracownika”

Osobny agent nie oznacza osobnego modelu ani osobnego kodu. Oznacza osobny
**kontekst**, na który składają się trzy rzeczy:

1. **Profil** (`config/pracownicy/<klucz>.yaml`) — staż, rola, teren, normy,
   cele rozwojowe, styl feedbacku, uwagi przełożonego. Agent ocenia nowicjusza
   po 3 miesiącach inaczej niż weterana po 5 latach — bo dostaje tę informację
   w promptcie.
2. **Pamięć** (tabela `pamiec`) — co zalecono w poprzednich okresach, co
   ustalono na 1:1, jakie obserwacje warto sprawdzić. Każdy raport z oceną AI
   dopisuje do niej swoje zalecenia, a następny raport je widzi. To zamienia
   ciąg niezależnych podsumowań w **prowadzenie człowieka w czasie**:
   „trzy tygodnie temu ustaliliśmy wizytówki przy każdej otwartej rozmowie —
   follow-up wzrósł z 6% do 22%, to zadziałało”.
3. **Historia metryk** — te same wskaźniki liczone tak samo od pierwszego dnia,
   więc trend jest prawdziwy.

Ten sam silnik obsługuje 3 osoby i 30 osób. Dochodzi tylko jeden plik YAML na
osobę.

## 3. Dzienny obieg pracy

```
        wieczorem                    rano
CRM ──► eksport ──► wczytaj ──► raport dzienny ──► szef czyta 2 minuty
                       │                │
                       │                ├─► lista leadów do dopilnowania
                       │                ├─► alerty (co wymaga reakcji)
                       │                └─► 1–3 konkretne akcje dla pracownika
                       │
                       └─► SQLite ──► agregaty T / M / Kw / R ──► 1:1, oceny okresowe
```

Realistycznie:

- **codziennie (2 min)** — wczytanie eksportu, przejrzenie alertów zespołu;
  raport dzienny czytasz tylko dla osób z alertem,
- **co tydzień (15 min)** — raport tygodniowy per osoba jako materiał na 1:1;
  ustalenia wpisujesz komendą `pamiec --dodaj`,
- **co miesiąc** — raport miesięczny + ranking zespołu; rozmowa o trendzie,
  nie o pojedynczym dniu,
- **kwartał / rok** — podstawa do rozmów o wynagrodzeniu, awansie, rozstaniu.

Zasada, która decyduje o tym, czy to przeżyje trzy miesiące: **dzienne dane
służą do reakcji, a nie do oceny**. Ocenia się tydzień i miesiąc. Jeden słaby
dzień to szum — deszcz, dentysta, zła klatka.

## 4. Automatyzacja wgrywania

Dziś: ręcznie jeden plik dziennie. Kolejność wdrażania automatu:

1. **Folder + cron.** CRM eksportuje do katalogu, `cron` odpala
   `analityk wczytaj eksporty/*.pdf` i wysyła raport mailem. Godzina pracy.
2. **CSV zamiast PDF.** Jeśli CRM to potrafi — od razu, parser jest odporniejszy.
3. **API CRM.** Docelowo bez plików. Ten CRM (pola `Esito incarico`, `RICERCA`,
   `Eseguito`) jest włoski — warto sprawdzić w dokumentacji dostawcy, czy
   udostępnia API do listy działań.

Warstwa `ingest/` jest po to, żeby zmiana źródła nie ruszała reszty systemu:
nowe źródło = nowy plik w `ingest/`, reszta bez zmian.

## 5. Etapy rozwoju

**Etap 1 — jest zrobiony.** Aktywność pozyskiwania: ilość, jakość, konwersja na
lead, trend, alerty, raport per osoba i per zespół, agregaty D/T/M/Kw/R.

**Etap 2 — dołożyć wynik biznesowy.** Umowy pośrednictwa, prezentacje,
transakcje, prowizje. Dopiero wtedy widać pełny lejek i można powiedzieć, ile
pukania kosztuje jedna transakcja. Wymaga drugiego eksportu z CRM. Szczegóły:
[`kpi.md`](kpi.md).

**Etap 3 — agent działający, nie tylko oceniający:**
- kolejka follow-upów: „wróć pod te 12 adresów, sygnał sprzed 90 dni”,
- baza obiekcji budowana automatycznie z notatek + skrypty odpowiedzi,
- mapa ciepła terenu: które budynki dają leady, a gdzie nie wracać przez pół roku,
- agenda na 1:1 generowana z raportu tygodniowego,
- alert wypalenia: spadek długości notatek + skrócenie dnia + spadek dotarcia.

**Etap 4 — interfejs.** Dopóki jesteś jedynym odbiorcą, CLI wystarcza. Gdy
raporty mają czytać sami agenci, potrzebny jest panel WWW albo wysyłka na
maila/WhatsAppa. Nie robi się tego przed etapem 2 — bez wyniku biznesowego
panel pokazuje ładne wykresy o niczym.

## 6. Koszty

Metryki i raport bez oceny AI: **0 zł**, wszystko liczy się lokalnie.

Ocena AI: jedno wywołanie na raport. Raport dzienny to rząd 5–15 tys. tokenów
wejścia. Przy 5 pracownikach i raporcie dziennym + tygodniowym mówimy o
kilkudziesięciu groszach do kilku złotych dziennie, zależnie od modelu.
Praktyczny układ:

- **raport dzienny** — bez LLM (same liczby + alerty), koszt zero,
- **raport tygodniowy i miesięczny** — z LLM (`--llm`), bo tam feedback ma sens,
- **klasyfikacja notatek przez LLM** — tylko gdy reguły zaczną się mylić.

## 7. Czego ten system celowo nie robi

- **Nie ocenia człowieka, tylko pracę.** Żadnych wniosków o cechach
  osobowości, motywacji, sytuacji życiowej. To jest wpisane w prompt systemowy.
- **Nie podejmuje decyzji kadrowych.** Wynik to rekomendacja dla przełożonego.
  Powód nie jest wyłącznie etyczny — patrz [`rodo-ai-act.md`](rodo-ai-act.md).
- **Nie liczy czasu pracy.** Rozpiętość dnia (pierwsza–ostatnia aktywność) to
  nie to samo co czas pracy i nie wolno jej tak używać.
- **Nie porównuje ludzi z różnych terenów wprost.** Blok z lat 70. i osiedle
  deweloperskie dają inne konwersje przy tej samej robocie. Ranking zespołu ma
  sens wewnątrz podobnego terenu.
