# Agent Analityk — analiza aktywności agentów biura nieruchomości

Wrzucasz codziennie eksport z CRM. Dostajesz: podsumowanie ilościowe i
jakościowe, punkty z oficjalnej klasyfikacji sieci, ocenę mocnych i słabych
stron, porównanie z innymi osobami na tym samym stanowisku, listę leadów do
dopilnowania i alerty dla siebie jako szefa. Osobno dla każdego pracownika,
w podziale na biura i role, w ujęciu dziennym / tygodniowym / miesięcznym /
kwartalnym / rocznym.

Wszystko przez **panel WWW** — albo z wiersza poleceń, jeśli wolisz.

Zbudowane i przetestowane na prawdziwym eksporcie „Analiza Działań i Spotkań”
(47 rekordów z jednego dnia pracy).

---

## Jak to działa w jednym akapicie

Eksport z CRM → parser (PDF albo CSV/XLSX) → jednolita tabela aktywności w
SQLite → **twarde metryki liczone w Pythonie** → raport Markdown. Ocena
opisowa i coaching pochodzą z modelu Claude, ale **model nigdy nie liczy
statystyk** — dostaje gotowe liczby. Dzięki temu raport jest powtarzalny, da
się go obronić przed pracownikiem i nie zmienia się przy każdym uruchomieniu.

Bez klucza API system nadal działa: liczby są zawsze, a ocena spada do prostej
heurystyki regułowej.

---

## Start — panel WWW

### macOS: dwuklik

Kliknij dwukrotnie **`start-mac.command`**. Przy pierwszym uruchomieniu skrypt
sam przygotuje środowisko Pythona i doinstaluje zależności (chwilę to trwa),
potem od razu startuje panel na `http://127.0.0.1:5500`.

Port 5500, a nie domyślny 5000, bo na macOS 5000 zajmuje AirPlay Receiver.

Gdy system pokaże ostrzeżenie o nieznanym deweloperze: kliknij plik prawym
przyciskiem → **Otwórz** → **Otwórz**. Wystarczy raz.

Potrzebny jest Python 3.11+ — sprawdzisz komendą `python3 --version`;
jeśli go nie ma, pobierz z [python.org/downloads](https://www.python.org/downloads/).

### Windows i Linux

Potrzebny Python 3.11 lub nowszy ([python.org/downloads](https://www.python.org/downloads/);
przy instalacji na Windowsie zaznacz **„Add python.exe to PATH"**).

```bash
cd agent-analityk
python -m pip install -r requirements.txt
python uruchom.py
```

Panel wystartuje i sam otworzy się w przeglądarce pod `http://127.0.0.1:5000`.
Zatrzymanie: `Ctrl+C` w oknie terminala. Na Linuksie wpisuj `python3`
zamiast `python`.

`uruchom.py` przyjmuje wszystkie komendy z wiersza poleceń, np.
`python uruchom.py wczytaj eksport.pdf` albo `python uruchom.py zespol --okres miesiac`.

Dalej klikaj:

1. **Wczytaj dane** — przeciągnij eksport z CRM (PDF, CSV albo XLSX). Ten sam
   plik można wgrać wielokrotnie, duplikaty nie powstają.
2. **Biura i ludzie** — dodaj biura, przypisz osoby, ustaw role
   (agent / koordynator/ka / kierownik) i staż. Od tego zależy, z kim ktoś
   jest porównywany i jakie ma normy.
3. **Pulpit** — ranking biur i ludzi, punkty, alerty. Przełącznik okresu
   dzień/tydzień/miesiąc/kwartał/rok jest na górze każdej strony.
4. **Do zrobienia** — kolejka follow-upów wyłapanych automatycznie z notatek,
   pogrupowana: po terminie / na dziś / ten tydzień / później / bez terminu.
5. **Tematy** — powtarzające się wątki i obiekcje z notatek; każdy można
   wziąć na śledzenie (z własną notatką) albo ukryć.
6. **Typy aktywności** — decydujesz, które typy z kolumny „Typ”/„Mobilny”
   liczą się do których wskaźników punktacji. Typy niezmapowane są wyraźnie
   oznaczone, żeby ich punkty nie przepadały niezauważone.
7. **Karta pracownika** — pełne rozbicie punktów, porównanie z grupą,
   wykresy, zadania, leady do dopilnowania, pamięć agenta i przycisk
   generowania oceny AI.

Panel słucha tylko na `127.0.0.1` — nie jest wystawiony do sieci.

## To samo z wiersza poleceń

```bash
python uruchom.py wczytaj ~/eksporty/analiza_2026-08-10.pdf
python uruchom.py biuro --dodaj "Biuro Centrum" --miasto Bydgoszcz
python uruchom.py pracownik --klucz jan_kowalski \
    --biuro 1 --rola agent --staz 3 --obszar Dworcowa Kniaziewicza

python uruchom.py zespol --okres miesiac --data 2026-08-01
python uruchom.py zadania --strona agent
python uruchom.py raport --pracownik jan_kowalski \
    --okres tydzien --data 2026-08-10 --llm --zapisz     # --llm: ANTHROPIC_API_KEY
```

Podgląd promptu bez płacenia za wywołanie API: dodaj `--pokaz-prompt`.

## Komendy

| Komenda | Do czego |
|---|---|
| `wczytaj PLIK...` | wczytuje eksporty (PDF/CSV/XLSX); ponowne wczytanie tego samego pliku nie tworzy duplikatów |
| `raport --pracownik X --okres dzien\|tydzien\|miesiac\|kwartal\|rok` | pełny raport pracownika |
| `metryki --pracownik X --okres ...` | surowe liczby w JSON (do Excela, BI, własnych wykresów) |
| `zespol --okres ...` | ranking biur i pracowników + wszystkie alerty |
| `serwer` | panel WWW (`--host`, `--port`) |
| `biuro --dodaj NAZWA` / `biuro` | dodanie i lista biur |
| `pracownik --klucz X --biuro N --rola ...` | przypisanie do biura, rola, początek pracy, normy |
| `zadania [--strona agent\|klient] [--wykryj] [--llm]` | kolejka follow-upów; `--zrobione ID` odhacza |
| `tematy --okres ...` | powtarzające się wątki i obiekcje z notatek |
| `pamiec --pracownik X --dodaj "..."` | ustalenia z 1:1 — agent pamięta je przy następnym raporcie |

Okres wskazujesz przez `--data 2026-08-10` (dowolny dzień z okresu) albo
wprost: `--okres-klucz 2026-W33`, `2026-08`, `2026-Q3`, `2026`.

---

## Co realnie wyszło z Twojego pliku (jeden dzień pracy, 10.08.2026)

| | |
|---|---|
| Aktywności | 47 (38 pukania + 9 telefonów), 16 budynków, 40 lokali |
| Wskaźnik dotarcia | 85,1% — bardzo wysoko, prawie każde drzwi się otworzyły |
| Leady / sygnały | 1 / 1 → konwersja 5,0% z odbytych rozmów |
| Informacje rynkowe | 12 (2 sprzedaże w okolicy, pustostan, spadek, konkurencja) |
| Notatki z treścią | 97,9% (średnio 59 znaków) |
| **Follow-up** | **6,4%** — wizytówka zostawiona 2 razy na 47 kontaktów |
| Praca 16–20 | 25,5% kontaktów |
| Indeks jakości pracy | **78/100** |

Wniosek, który system wyciąga sam: to nie jest problem z ilością ani z
odwagą — norma zrobiona w 117%, dotarcie świetne. Wąskie gardło jest **za**
rozmową: 44 kontakty kończą się na „nie” i nie zostaje po nich nic — ani
wizytówka, ani zaplanowany powrót. Drugi wniosek: 12 informacji rynkowych
zebranych przy okazji jest w tej chwili wyrzucanych do notatek i nikt z nich
nie korzysta.

---

## Zadania i follow-upy

Notatka „Pan chce sprzedać za tydzień, ma wysłać zdjęcia, numer do siostry
601 202 303” zawiera trzy różne rzeczy. System rozbija ją na:

| Termin | Kto | Typ | Zadanie |
|---|---|---|---|
| 17.08 | my | Kontakt do zapisania | Zapisać kontakt do: siostry |
| 17.08 | klient | Czekam na klienta | Klient ma dosłać: zdjęcia |

Wyłapywanie działa automatycznie przy każdym wczytaniu pliku. Siedem typów
zadań: zadzwonić, wrócić pod adres, wysłać/dostarczyć, spotkanie, kontakt do
zapisania, czekam na klienta, wrócić do tematu.

Trzy rzeczy, które to rozwiązanie robi świadomie:

- **Termin liczy się od dnia kontaktu, nie od dzisiaj.** „Za tydzień”
  w notatce z 10.08 to 17.08, także gdy raport otwierasz miesiąc później.
  Rozpoznawane są formy względne („za 2 tygodnie”, „za pół roku”), dni
  tygodnia („w czwartek”, „na piątek”), miesiące, konkretne daty i końce
  miesiąca. Mgliste („po świętach”, „na wiosnę”) trafiają do kolejki **bez
  daty** — system nie udaje precyzji, której nie ma.
- **Rozróżnia, po czyjej stronie jest ruch.** „Ma wysłać zdjęcia” to
  obietnica klienta, „mam wysłać ofertę” to Twoje zadanie. Filtr `strona`
  pozwala oddzielić „do zrobienia” od „czekamy”.
- **Odhaczenie jest trwałe.** Ponowne wczytanie tego samego eksportu nie
  odkopie zamkniętego zadania.

Ścieżka regułowa działa offline i za darmo. `analityk zadania --wykryj --llm`
przelicza to samo modelem — łapie zdania złożone i literówki, ale terminy
i tak przelicza kod, żeby model nie mógł pomylić się w kalendarzu.

---

## Struktura

```
src/analityk/
  models.py            kanoniczny rekord aktywności + parsowanie adresów
  org.py               biura, pracownicy, role, normy zależne od roli
  ingest/pdf_crm.py    parser wydruku PDF z CRM (siatka tabeli, sklejanie stron)
  ingest/csv_generic.py CSV/XLSX z elastycznym mapowaniem nagłówków
  classify.py          regułowa klasyfikacja notatek (PL, odporna na literówki)
  store.py             SQLite: aktywności, organizacja, wskaźniki, raporty, pamięć
  metrics.py           metryki + okresy D/T/M/Kw/R + normy + alerty
  punktacja.py         oficjalna klasyfikacja sieci: stawki, bonusy, punkty
  benchmark.py         porównania: osoba do grupy, biuro do biura
  report.py            raport Markdown (działa bez LLM)
  prompts.py           prompty (system + user) — do edycji bez ruszania kodu
  llm.py               jedyne miejsce kontaktu z API Claude
  zadania.py           wyłapywanie follow-upów, terminów i tematów z notatek
  cli.py               interfejs wiersza poleceń
  web/                 panel WWW: trasy, szablony, wykresy SVG, styl
uruchom.py             jedno wejście dla Windows / macOS / Linux
start-mac.command      uruchomienie na macOS przez dwuklik
docs/                  koncepcja, KPI, punktacja, RODO i AI Act
tests/                 88 testów: python3 -m unittest discover -s tests
```

## Dokumentacja

- [`docs/koncepcja.md`](docs/koncepcja.md) — jak działa „osobny agent dla
  każdego pracownika”, dzienny obieg pracy, etapy wdrożenia, koszty
- [`docs/kpi.md`](docs/kpi.md) — co jeszcze warto mierzyć w biurze
  nieruchomości: pełny lejek od pukania do aktu notarialnego
- [`docs/punktacja.md`](docs/punktacja.md) — oficjalna klasyfikacja sieci:
  stawki, bonusy, co liczy się automatycznie, a co trzeba wpisać, oraz trzy
  miejsca wymagające Twojego potwierdzenia
- [`docs/rodo-ai-act.md`](docs/rodo-ai-act.md) — ocena pracownika przez AI:
  co wolno, czego nie, i jak to ustawić, żeby było legalne

## Ograniczenia, o których warto wiedzieć

- **Klasyfikacja regułowa jest przybliżeniem.** Na Twoim pliku radzi sobie
  dobrze, ale notatka typu „Pani nie chce, ale sąsiadka pod 12 pyta” bywa
  zaklasyfikowana jako odmowa zamiast sygnału. Przebieg LLM (`--llm`) łapie
  takie niuanse; reguły są po to, żeby system działał za darmo i offline.
- **PDF to droga awaryjna.** Parser trzyma się siatki tabeli i sklejania
  wierszy przeciętych granicą stron — działa, ale zmiana układu wydruku w CRM
  go zepsuje. Jeśli CRM eksportuje CSV/XLSX, używaj tego.
- **Normy domyślne są zgadywane** (40 aktywności dziennie dla agenta, mniej
  dla koordynatorki i kierownika). Ustaw własne przy pracowniku, inaczej
  „realizacja normy” nic nie znaczy.
- **Punkty są niekompletne, dopóki nie uzupełnisz wskaźników.** Z eksportu
  aktywności liczą się automatycznie tylko IM3 i R4 — reszta tabeli pochodzi
  z innych modułów CRM. Panel pokazuje procent kompletności przy każdej
  klasyfikacji, żeby nikt nie porównywał uzupełnionych z nieuzupełnionymi.
- **Porównania przy małej grupie są oznaczane jako niewiarygodne** (próg: 3
  osoby w tej samej roli) i nie powinny iść do oceny.
- System mierzy **aktywność pozyskiwania**. Etapów po spotkaniu (umowy,
  transakcje, prowizje) w tym eksporcie nie ma — patrz `docs/kpi.md`,
  sekcja o tym, jak je dołożyć.

## Dane osobowe w repozytorium

W repo **nie ma** żadnych prawdziwych danych: eksporty z CRM, baza SQLite,
katalog raportów i profile pracowników są w `.gitignore`. `przyklady/` zawiera
wyłącznie dane fikcyjne, wygenerowane na potrzeby demonstracji. Powód
i pełna lista obowiązków: [`docs/rodo-ai-act.md`](docs/rodo-ai-act.md).
