"""Profile pracowników — "osobny agent dla każdego agenta".

Agent per pracownik nie oznacza osobnego modelu ani osobnego kodu. Oznacza
osobny **kontekst**: profil (kim jest, jaki ma staż, jakie normy, jak chce
dostawać feedback) + pamięć (co mu zalecono w poprzednich okresach i czy to
zrobił). Ten sam silnik obsługuje 3 osoby i 30 osób.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .metrics import NORMY_DOMYSLNE

KATALOG_PROFILI = Path("config/pracownicy")


@dataclass
class Profil:
    klucz: str
    imie_nazwisko: str
    rola: str = "agent"                     # agent | pozyskiwacz | sprzedawca | manager
    staz_miesiace: int = 0
    zatrudniony_od: str = ""
    obszar_farmingu: list[str] = field(default_factory=list)
    normy: dict = field(default_factory=dict)
    cele_rozwojowe: list[str] = field(default_factory=list)
    styl_feedbacku: str = "konkretny, bez owijania, z jednym priorytetem na okres"
    uwagi_managera: str = ""

    @property
    def normy_pelne(self) -> dict:
        polaczone = {typ: dict(w) for typ, w in NORMY_DOMYSLNE.items()}
        for typ, wartosci in (self.normy or {}).items():
            polaczone.setdefault(typ, {}).update(wartosci)
        return polaczone

    @property
    def nowicjusz(self) -> bool:
        return self.staz_miesiace < 6


def sciezka_profilu(klucz: str, katalog: Path | str = KATALOG_PROFILI) -> Path:
    return Path(katalog) / f"{klucz}.yaml"


def wczytaj_profil(klucz: str, imie_nazwisko: str = "",
                   katalog: Path | str = KATALOG_PROFILI) -> Profil:
    """Wczytuje profil z YAML-a; gdy go nie ma, zwraca sensowne domyślne."""
    p = sciezka_profilu(klucz, katalog)
    if not p.exists():
        return Profil(klucz=klucz, imie_nazwisko=imie_nazwisko or klucz)
    dane = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    dane.setdefault("klucz", klucz)
    dane.setdefault("imie_nazwisko", imie_nazwisko or klucz)
    znane = Profil.__dataclass_fields__.keys()
    return Profil(**{k: v for k, v in dane.items() if k in znane})


def zapisz_profil(profil: Profil, katalog: Path | str = KATALOG_PROFILI) -> Path:
    p = sciezka_profilu(profil.klucz, katalog)
    p.parent.mkdir(parents=True, exist_ok=True)
    dane = {
        "klucz": profil.klucz,
        "imie_nazwisko": profil.imie_nazwisko,
        "rola": profil.rola,
        "staz_miesiace": profil.staz_miesiace,
        "zatrudniony_od": profil.zatrudniony_od,
        "obszar_farmingu": profil.obszar_farmingu,
        "normy": profil.normy,
        "cele_rozwojowe": profil.cele_rozwojowe,
        "styl_feedbacku": profil.styl_feedbacku,
        "uwagi_managera": profil.uwagi_managera,
    }
    p.write_text(
        yaml.safe_dump(dane, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return p
