# Agent Analityk — analiza aktywności agentów biura nieruchomości

Wrzucasz codziennie eksport z CRM. Dostajesz: podsumowanie ilościowe i
jakościowe, ocenę mocnych i słabych stron, konkretny plan na kolejny okres,
listę leadów do dopilnowania i alerty dla siebie jako szefa. Osobno dla każdego
pracownika, w ujęciu dziennym / tygodniowym / miesięcznym / kwartalnym /
rocznym.

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

## Start

```bash
cd agent-analityk
pip install -r requirements.txt

# 1. wczytaj eksport (PDF z CRM albo CSV/XLSX)
PYTHONPATH=src python3 -m analityk wczytaj ~/eksporty/analiza_dzialan_2026-08-10.pdf
# szybki test na danych demonstracyjnych (fikcyjnych):
PYTHONPATH=src python3 -m analityk wczytaj przyklady/przyklad_eksport_csv.csv

# 2. ustaw profil pracownika (staż wpływa na to, jak ostro ocenia agent AI)
PYTHONPATH=src python3 -m analityk profil --pracownik jan_kowalski \
    --staz 3 --rola pozyskiwacz --obszar Dworcowa Kniaziewicza --norma-dzienna 45

# 3. raport dzienny
PYTHONPATH=src python3 -m analityk raport --pracownik jan_kowalski \
    --okres dzien --data 2026-08-10

# 4. to samo z oceną AI (wymaga ANTHROPIC_API_KEY)
export ANTHROPIC_API_KEY=sk-ant-...
PYTHONPATH=src python3 -m analityk raport --pracownik jan_kowalski \
    --okres dzien --data 2026-08-10 --llm --zapisz

# 5. widok dla szefa: ranking i alerty całego zespołu
PYTHONPATH=src python3 -m analityk zespol --okres tydzien --data 2026-08-10
```

Podgląd promptu bez płacenia za wywołanie API: dodaj `--pokaz-prompt`.

## Komendy

| Komenda | Do czego |
|---|---|
| `wczytaj PLIK...` | wczytuje eksporty (PDF/CSV/XLSX); ponowne wczytanie tego samego pliku nie tworzy duplikatów |
| `raport --pracownik X --okres dzien\|tydzien\|miesiac\|kwartal\|rok` | pełny raport pracownika |
| `metryki --pracownik X --okres ...` | surowe liczby w JSON (do Excela, BI, własnych wykresów) |
| `zespol --okres ...` | ranking zespołu + wszystkie alerty w jednym miejscu |
| `profil --pracownik X ...` | staż, rola, teren, indywidualne normy |
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

## Struktura

```
src/analityk/
  models.py            kanoniczny rekord aktywności + parsowanie adresów
  ingest/pdf_crm.py    parser wydruku PDF z CRM (siatka tabeli, sklejanie stron)
  ingest/csv_generic.py CSV/XLSX z elastycznym mapowaniem nagłówków
  classify.py          regułowa klasyfikacja notatek (PL, odporna na literówki)
  store.py             SQLite: aktywności, raporty, pamięć agenta
  metrics.py           metryki + okresy D/T/M/Kw/R + normy + alerty
  report.py            raport Markdown (działa bez LLM)
  prompts.py           prompty (system + user) — do edycji bez ruszania kodu
  llm.py               jedyne miejsce kontaktu z API Claude
  cli.py               interfejs wiersza poleceń
config/pracownicy/     profile: staż, rola, teren, normy, styl feedbacku
docs/                  koncepcja, katalog KPI, RODO i AI Act
tests/                 19 testów: python3 -m unittest discover -s tests
```

## Dokumentacja

- [`docs/koncepcja.md`](docs/koncepcja.md) — jak działa „osobny agent dla
  każdego pracownika”, dzienny obieg pracy, etapy wdrożenia, koszty
- [`docs/kpi.md`](docs/kpi.md) — co jeszcze warto mierzyć w biurze
  nieruchomości: pełny lejek od pukania do aktu notarialnego
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
- **Normy domyślne są zgadywane** (40 aktywności dziennie). Ustaw własne w
  profilu pracownika, inaczej „realizacja normy” nic nie znaczy.
- System mierzy **aktywność pozyskiwania**. Etapów po spotkaniu (umowy,
  transakcje, prowizje) w tym eksporcie nie ma — patrz `docs/kpi.md`,
  sekcja o tym, jak je dołożyć.

## Dane osobowe w repozytorium

W repo **nie ma** żadnych prawdziwych danych: eksporty z CRM, baza SQLite,
katalog raportów i profile pracowników są w `.gitignore`. `przyklady/` zawiera
wyłącznie dane fikcyjne, wygenerowane na potrzeby demonstracji. Powód
i pełna lista obowiązków: [`docs/rodo-ai-act.md`](docs/rodo-ai-act.md).
