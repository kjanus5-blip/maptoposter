"""Struktura organizacji: biura, pracownicy, role.

Źródłem prawdy jest baza (SQLite) — dzięki temu strukturę da się edytować
z panelu WWW. Pliki `config/pracownicy/*.yaml` nadal działają jako
**zapasowe źródło**: gdy pracownika nie ma jeszcze w bazie, ustawienia
wczytują się z YAML-a. Wygodne przy pierwszym uruchomieniu i przy
wersjonowaniu ustawień poza panelem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

KATALOG_PROFILI = Path("config/pracownicy")

# --- role -----------------------------------------------------------------

ROLA_AGENT = "agent"
ROLA_KOORDYNATOR = "koordynator"
ROLA_KIEROWNIK = "kierownik"

ROLE = (ROLA_AGENT, ROLA_KOORDYNATOR, ROLA_KIEROWNIK)

NAZWY_ROL = {
    ROLA_AGENT: "Agent",
    ROLA_KOORDYNATOR: "Koordynator/ka",
    ROLA_KIEROWNIK: "Kierownik",
}

OPIS_ROL = {
    ROLA_AGENT: (
        "Pozyskuje i obsługuje klientów. Oceniany po aktywności w terenie, "
        "konwersji na leady i wyniku."
    ),
    ROLA_KOORDYNATOR: (
        "Obsługa biura i telefonów przychodzących, umawianie spotkań, "
        "prowadzenie ogłoszeń. Mniej kontaktów własnych, ale wyższy udział "
        "realnych rozmów i wyższe wymagania wobec jakości danych w CRM."
    ),
    ROLA_KIEROWNIK: (
        "Zarządza zespołem. Własna aktywność jest z natury niższa — ocenia "
        "się go przede wszystkim przez wynik biura."
    ),
}

#: Dzienna norma bazowa dla każdej roli. Pozostałe okresy skalują się z niej.
NORMY_DZIENNE_ROL = {
    ROLA_AGENT: {"aktywnosci": 40, "leady": 1},
    ROLA_KOORDYNATOR: {"aktywnosci": 25, "leady": 1},
    ROLA_KIEROWNIK: {"aktywnosci": 12, "leady": 0},
}

#: Mnożniki okresów — dni robocze z sobotami (5,5 dnia/tydzień w praktyce).
MNOZNIKI_OKRESOW = {
    "dzien": 1, "tydzien": 5, "miesiac": 21, "kwartal": 63, "rok": 250,
}


def normy_dla_roli(rola: str) -> dict:
    """Pełen zestaw norm (wszystkie okresy) wyliczony z normy dziennej roli."""
    baza = NORMY_DZIENNE_ROL.get(rola, NORMY_DZIENNE_ROL[ROLA_AGENT])
    return {
        okres: {k: v * mnoznik for k, v in baza.items()}
        for okres, mnoznik in MNOZNIKI_OKRESOW.items()
    }


# --- encje ----------------------------------------------------------------

@dataclass
class Biuro:
    id: int | None = None
    nazwa: str = ""
    miasto: str = ""
    adres: str = ""
    uwagi: str = ""

    @property
    def etykieta(self) -> str:
        return f"{self.nazwa} ({self.miasto})" if self.miasto else self.nazwa


@dataclass
class Pracownik:
    """Profil pracownika = kontekst, w którym agent AI go ocenia."""

    klucz: str
    imie_nazwisko: str = ""
    biuro_id: int | None = None
    biuro_nazwa: str = ""
    rola: str = ROLA_AGENT
    staz_miesiace: int = 0
    zatrudniony_od: str = ""
    obszar_farmingu: list[str] = field(default_factory=list)
    normy: dict = field(default_factory=dict)
    cele_rozwojowe: list[str] = field(default_factory=list)
    styl_feedbacku: str = "konkretny, bez owijania, z jednym priorytetem na okres"
    uwagi_managera: str = ""
    aktywny: bool = True

    @property
    def normy_pelne(self) -> dict:
        """Normy roli nadpisane indywidualnymi ustawieniami pracownika."""
        polaczone = {typ: dict(w) for typ, w in normy_dla_roli(self.rola).items()}
        for typ, wartosci in (self.normy or {}).items():
            polaczone.setdefault(typ, {}).update(wartosci)
        return polaczone

    @property
    def staz(self) -> int:
        """Staż w miesiącach.

        Liczony z daty zatrudnienia, żeby nie trzeba go było ręcznie
        podbijać co miesiąc. Pole `staz_miesiace` zostaje jako wartość
        zapasowa dla osób, którym daty nie wpisano.
        """
        if not self.zatrudniony_od:
            return self.staz_miesiace
        try:
            od = date.fromisoformat(self.zatrudniony_od)
        except ValueError:
            return self.staz_miesiace
        dzis = date.today()
        miesiace = (dzis.year - od.year) * 12 + (dzis.month - od.month)
        if dzis.day < od.day:
            miesiace -= 1
        return max(miesiace, 0)

    @property
    def staz_opis(self) -> str:
        m = self.staz
        if m < 1:
            return "poniżej miesiąca"
        if m < 12:
            return f"{m} mies."
        lata, reszta = divmod(m, 12)
        return f"{lata} l. {reszta} mies." if reszta else f"{lata} l."

    @property
    def nowicjusz(self) -> bool:
        return self.staz < 6

    @property
    def nazwa_roli(self) -> str:
        return NAZWY_ROL.get(self.rola, self.rola)


# --- YAML (zapasowe źródło ustawień) --------------------------------------

def sciezka_profilu(klucz: str, katalog: Path | str = KATALOG_PROFILI) -> Path:
    return Path(katalog) / f"{klucz}.yaml"


def wczytaj_profil_yaml(klucz: str, imie_nazwisko: str = "",
                        katalog: Path | str = KATALOG_PROFILI) -> Pracownik | None:
    p = sciezka_profilu(klucz, katalog)
    if not p.exists():
        return None
    dane = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    dane.setdefault("klucz", klucz)
    dane.setdefault("imie_nazwisko", imie_nazwisko or klucz)
    znane = Pracownik.__dataclass_fields__.keys()
    return Pracownik(**{k: v for k, v in dane.items() if k in znane})


def zapisz_profil_yaml(p: Pracownik, katalog: Path | str = KATALOG_PROFILI) -> Path:
    sciezka = sciezka_profilu(p.klucz, katalog)
    sciezka.parent.mkdir(parents=True, exist_ok=True)
    sciezka.write_text(
        yaml.safe_dump(
            {
                "klucz": p.klucz,
                "imie_nazwisko": p.imie_nazwisko,
                "rola": p.rola,
                "staz_miesiace": p.staz_miesiace,
                "zatrudniony_od": p.zatrudniony_od,
                "obszar_farmingu": p.obszar_farmingu,
                "normy": p.normy,
                "cele_rozwojowe": p.cele_rozwojowe,
                "styl_feedbacku": p.styl_feedbacku,
                "uwagi_managera": p.uwagi_managera,
            },
            allow_unicode=True, sort_keys=False,
        ),
        encoding="utf-8",
    )
    return sciezka
