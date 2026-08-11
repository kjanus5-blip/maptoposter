"""Baza danych (SQLite) — jedna tabela aktywności + pamięć agentów.

Wgrywanie tego samego pliku dwa razy nie tworzy duplikatów: `Activity.id`
jest deterministycznym skrótem z (pracownik, data, powiązanie, notatka).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .models import Activity
from .org import Biuro, Pracownik, wczytaj_profil_yaml

SCHEMAT = """
CREATE TABLE IF NOT EXISTS aktywnosci (
    id TEXT PRIMARY KEY,
    pracownik TEXT NOT NULL,
    pracownik_nazwa TEXT NOT NULL,
    data TEXT NOT NULL,
    dzien TEXT NOT NULL,
    kanal TEXT,
    podtyp TEXT,
    powiazanie TEXT,
    budynek TEXT,
    lokal TEXT,
    notatka TEXT,
    wynik TEXT,
    tagi TEXT,
    zostawiono_material INTEGER,
    zaplanowany_kolejny_krok INTEGER,
    zrodlo TEXT,
    wczytano TEXT
);
CREATE INDEX IF NOT EXISTS idx_prac_dzien ON aktywnosci(pracownik, dzien);

CREATE TABLE IF NOT EXISTS raporty (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pracownik TEXT NOT NULL,
    okres_typ TEXT NOT NULL,
    okres_klucz TEXT NOT NULL,
    utworzono TEXT NOT NULL,
    metryki_json TEXT,
    tresc_md TEXT,
    UNIQUE(pracownik, okres_typ, okres_klucz)
);

CREATE TABLE IF NOT EXISTS biura (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nazwa TEXT NOT NULL UNIQUE,
    miasto TEXT DEFAULT '',
    adres TEXT DEFAULT '',
    uwagi TEXT DEFAULT '',
    utworzono TEXT
);

CREATE TABLE IF NOT EXISTS pracownicy (
    klucz TEXT PRIMARY KEY,
    imie_nazwisko TEXT NOT NULL,
    biuro_id INTEGER REFERENCES biura(id) ON DELETE SET NULL,
    rola TEXT DEFAULT 'agent',
    staz_miesiace INTEGER DEFAULT 0,
    zatrudniony_od TEXT DEFAULT '',
    obszar_json TEXT DEFAULT '[]',
    normy_json TEXT DEFAULT '{}',
    cele_json TEXT DEFAULT '[]',
    styl_feedbacku TEXT DEFAULT '',
    uwagi_managera TEXT DEFAULT '',
    aktywny INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_prac_biuro ON pracownicy(biuro_id);

CREATE TABLE IF NOT EXISTS wskazniki (
    pracownik TEXT NOT NULL,
    okres_typ TEXT NOT NULL,
    okres_klucz TEXT NOT NULL,
    kod TEXT NOT NULL,
    wartosc REAL NOT NULL,
    zaktualizowano TEXT,
    PRIMARY KEY (pracownik, okres_typ, okres_klucz, kod)
);

CREATE TABLE IF NOT EXISTS pamiec (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pracownik TEXT NOT NULL,
    data TEXT NOT NULL,
    typ TEXT NOT NULL,        -- obserwacja | zalecenie | ustalenie_1n1 | cel
    tresc TEXT NOT NULL,
    status TEXT DEFAULT 'otwarte',
    zrodlo_okres TEXT
);
CREATE INDEX IF NOT EXISTS idx_pamiec_prac ON pamiec(pracownik, data);
"""


class Baza:
    def __init__(self, sciezka: str | Path = "data/analityk.db"):
        self.sciezka = Path(sciezka)
        self.sciezka.parent.mkdir(parents=True, exist_ok=True)
        # timeout: przy panelu WWW zdarzają się równoległe zapisy;
        # WAL: czytanie nie blokuje pisania i odwrotnie.
        self.con = sqlite3.connect(self.sciezka, timeout=10)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA foreign_keys=ON")
        self.con.executescript(SCHEMAT)
        self._migruj()
        self.con.commit()

    def _migruj(self) -> None:
        """Dokłada kolumny, które pojawiły się po utworzeniu bazy.

        CREATE TABLE IF NOT EXISTS nie zmienia istniejących tabel, więc stare
        bazy trzeba douzupełnić ręcznie — inaczej aktualizacja aplikacji
        wywala się na brakującej kolumnie.
        """
        dokladki = {
            "raporty": {"ocena_json": "TEXT"},
        }
        for tabela, kolumny in dokladki.items():
            istniejace = {
                r["name"] for r in self.con.execute(f"PRAGMA table_info({tabela})")
            }
            for nazwa, typ in kolumny.items():
                if nazwa not in istniejace:
                    self.con.execute(f"ALTER TABLE {tabela} ADD COLUMN {nazwa} {typ}")

    # --- aktywności -------------------------------------------------------

    def zapisz_aktywnosci(self, aktywnosci: list[Activity]) -> tuple[int, int]:
        """Zwraca (nowe, pominięte_duplikaty)."""
        nowe = 0
        teraz = datetime.now().isoformat(timespec="seconds")
        for a in aktywnosci:
            cur = self.con.execute(
                """INSERT OR IGNORE INTO aktywnosci
                   (id, pracownik, pracownik_nazwa, data, dzien, kanal, podtyp,
                    powiazanie, budynek, lokal, notatka, wynik, tagi,
                    zostawiono_material, zaplanowany_kolejny_krok, zrodlo, wczytano)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    a.id, a.pracownik, a.pracownik_nazwa,
                    a.data.isoformat(timespec="minutes"), a.dzien,
                    a.kanal, a.podtyp, a.powiazanie, a.budynek, a.lokal,
                    a.notatka, a.wynik, ",".join(a.tagi),
                    int(a.zostawiono_material), int(a.zaplanowany_kolejny_krok),
                    a.zrodlo, teraz,
                ),
            )
            nowe += cur.rowcount
        self.con.commit()
        return nowe, len(aktywnosci) - nowe

    def pobierz(
        self,
        pracownik: str | None = None,
        od: str | None = None,
        do: str | None = None,
    ) -> list[Activity]:
        sql = "SELECT * FROM aktywnosci WHERE 1=1"
        params: list = []
        if pracownik:
            sql += " AND pracownik = ?"
            params.append(pracownik)
        if od:
            sql += " AND dzien >= ?"
            params.append(od)
        if do:
            sql += " AND dzien <= ?"
            params.append(do)
        sql += " ORDER BY data"
        return [self._na_activity(r) for r in self.con.execute(sql, params)]

    def pracownicy_z_aktywnosci(self) -> list[tuple[str, str, int]]:
        """(klucz, nazwa, liczba aktywności) — prosto z tabeli zdarzeń."""
        sql = """SELECT pracownik, pracownik_nazwa, COUNT(*) n
                 FROM aktywnosci GROUP BY pracownik ORDER BY n DESC"""
        return [(r["pracownik"], r["pracownik_nazwa"], r["n"]) for r in self.con.execute(sql)]

    # --- struktura organizacji -------------------------------------------

    def zapisz_biuro(self, biuro: Biuro) -> int:
        """Rzuca sqlite3.IntegrityError przy zduplikowanej nazwie.

        Wywołujący musi obsłużyć wyjątek — połączenie samo wycofuje
        nieudaną transakcję, żeby nie zostawić blokady na bazie.
        """
        if biuro.id:
            self.con.execute(
                "UPDATE biura SET nazwa=?, miasto=?, adres=?, uwagi=? WHERE id=?",
                (biuro.nazwa, biuro.miasto, biuro.adres, biuro.uwagi, biuro.id),
            )
            self.con.commit()
            return biuro.id
        try:
            cur = self.con.execute(
                "INSERT INTO biura (nazwa, miasto, adres, uwagi, utworzono) VALUES (?,?,?,?,?)",
                (biuro.nazwa, biuro.miasto, biuro.adres, biuro.uwagi,
                 datetime.now().isoformat(timespec="seconds")),
            )
        except sqlite3.Error:
            self.con.rollback()
            raise
        self.con.commit()
        return int(cur.lastrowid)

    def biura(self) -> list[Biuro]:
        return [
            Biuro(id=r["id"], nazwa=r["nazwa"], miasto=r["miasto"],
                  adres=r["adres"], uwagi=r["uwagi"])
            for r in self.con.execute("SELECT * FROM biura ORDER BY nazwa")
        ]

    def biuro(self, biuro_id: int) -> Biuro | None:
        r = self.con.execute("SELECT * FROM biura WHERE id=?", (biuro_id,)).fetchone()
        if not r:
            return None
        return Biuro(id=r["id"], nazwa=r["nazwa"], miasto=r["miasto"],
                     adres=r["adres"], uwagi=r["uwagi"])

    def usun_biuro(self, biuro_id: int) -> None:
        """Biuro znika, pracownicy zostają — wracają do puli nieprzypisanych."""
        self.con.execute("UPDATE pracownicy SET biuro_id=NULL WHERE biuro_id=?", (biuro_id,))
        self.con.execute("DELETE FROM biura WHERE id=?", (biuro_id,))
        self.con.commit()

    def zapisz_pracownika(self, p: Pracownik) -> None:
        self.con.execute(
            """INSERT INTO pracownicy
                 (klucz, imie_nazwisko, biuro_id, rola, staz_miesiace, zatrudniony_od,
                  obszar_json, normy_json, cele_json, styl_feedbacku, uwagi_managera, aktywny)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(klucz) DO UPDATE SET
                 imie_nazwisko=excluded.imie_nazwisko, biuro_id=excluded.biuro_id,
                 rola=excluded.rola, staz_miesiace=excluded.staz_miesiace,
                 zatrudniony_od=excluded.zatrudniony_od, obszar_json=excluded.obszar_json,
                 normy_json=excluded.normy_json, cele_json=excluded.cele_json,
                 styl_feedbacku=excluded.styl_feedbacku,
                 uwagi_managera=excluded.uwagi_managera, aktywny=excluded.aktywny""",
            (p.klucz, p.imie_nazwisko, p.biuro_id, p.rola, p.staz_miesiace,
             p.zatrudniony_od, json.dumps(p.obszar_farmingu, ensure_ascii=False),
             json.dumps(p.normy, ensure_ascii=False),
             json.dumps(p.cele_rozwojowe, ensure_ascii=False),
             p.styl_feedbacku, p.uwagi_managera, int(p.aktywny)),
        )
        self.con.commit()

    def pracownik(self, klucz: str) -> Pracownik | None:
        r = self.con.execute(
            """SELECT p.*, b.nazwa AS biuro_nazwa FROM pracownicy p
               LEFT JOIN biura b ON b.id = p.biuro_id WHERE p.klucz=?""",
            (klucz,),
        ).fetchone()
        return self._na_pracownika(r) if r else None

    def pracownicy(self, biuro_id: int | None = None, rola: str | None = None,
                   tylko_aktywni: bool = True) -> list[Pracownik]:
        sql = """SELECT p.*, b.nazwa AS biuro_nazwa FROM pracownicy p
                 LEFT JOIN biura b ON b.id = p.biuro_id WHERE 1=1"""
        params: list = []
        if biuro_id is not None:
            sql += " AND p.biuro_id = ?"
            params.append(biuro_id)
        if rola:
            sql += " AND p.rola = ?"
            params.append(rola)
        if tylko_aktywni:
            sql += " AND p.aktywny = 1"
        sql += " ORDER BY p.imie_nazwisko"
        return [self._na_pracownika(r) for r in self.con.execute(sql, params)]

    def pracownik_lub_domyslny(self, klucz: str, nazwa: str = "") -> Pracownik:
        """Kolejność źródeł: baza → plik YAML → wartości domyślne.

        Dzięki temu panel WWW (baza) i ręczna konfiguracja w plikach dają się
        używać zamiennie, a system nigdy nie wywala się na braku profilu.
        """
        z_bazy = self.pracownik(klucz)
        if z_bazy:
            return z_bazy
        if not nazwa:
            nazwa = next((n for k, n, _ in self.pracownicy_z_aktywnosci() if k == klucz), klucz)
        return (wczytaj_profil_yaml(klucz, nazwa)
                or Pracownik(klucz=klucz, imie_nazwisko=nazwa))

    def nieprzypisani(self) -> list[Pracownik]:
        return [p for p in self.pracownicy() if p.biuro_id is None]

    def synchronizuj_pracownikow(self) -> int:
        """Zakłada wpis dla każdej osoby, która pojawiła się w aktywnościach.

        Nowi ludzie trafiają do puli „bez biura” — panel pokazuje ich osobno,
        żeby nikt nie wypadł z rankingu tylko dlatego, że go nie przypisano.
        """
        nowi = 0
        for klucz, nazwa, _ in self.pracownicy_z_aktywnosci():
            if self.pracownik(klucz) is None:
                self.zapisz_pracownika(Pracownik(klucz=klucz, imie_nazwisko=nazwa))
                nowi += 1
        return nowi

    @staticmethod
    def _na_pracownika(r: sqlite3.Row) -> Pracownik:
        def js(pole: str, domyslne):
            try:
                return json.loads(r[pole]) if r[pole] else domyslne
            except (json.JSONDecodeError, TypeError):
                return domyslne

        return Pracownik(
            klucz=r["klucz"],
            imie_nazwisko=r["imie_nazwisko"],
            biuro_id=r["biuro_id"],
            biuro_nazwa=r["biuro_nazwa"] or "",
            rola=r["rola"] or "agent",
            staz_miesiace=r["staz_miesiace"] or 0,
            zatrudniony_od=r["zatrudniony_od"] or "",
            obszar_farmingu=js("obszar_json", []),
            normy=js("normy_json", {}),
            cele_rozwojowe=js("cele_json", []),
            styl_feedbacku=r["styl_feedbacku"] or
            "konkretny, bez owijania, z jednym priorytetem na okres",
            uwagi_managera=r["uwagi_managera"] or "",
            aktywny=bool(r["aktywny"]),
        )

    @staticmethod
    def _na_activity(r: sqlite3.Row) -> Activity:
        return Activity(
            id=r["id"],
            pracownik=r["pracownik"],
            pracownik_nazwa=r["pracownik_nazwa"],
            data=datetime.fromisoformat(r["data"]),
            kanal=r["kanal"] or "",
            podtyp=r["podtyp"] or "",
            powiazanie=r["powiazanie"] or "",
            budynek=r["budynek"] or "",
            lokal=r["lokal"] or "",
            notatka=r["notatka"] or "",
            wynik=r["wynik"] or "",
            tagi=[t for t in (r["tagi"] or "").split(",") if t],
            zostawiono_material=bool(r["zostawiono_material"]),
            zaplanowany_kolejny_krok=bool(r["zaplanowany_kolejny_krok"]),
            zrodlo=r["zrodlo"] or "",
        )

    # --- raporty ----------------------------------------------------------

    def zapisz_raport(self, pracownik: str, okres_typ: str, okres_klucz: str,
                      metryki: dict, tresc_md: str, ocena: dict | None = None) -> None:
        self.con.execute(
            """INSERT INTO raporty (pracownik, okres_typ, okres_klucz, utworzono,
                                    metryki_json, tresc_md, ocena_json)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(pracownik, okres_typ, okres_klucz) DO UPDATE SET
                   utworzono=excluded.utworzono,
                   metryki_json=excluded.metryki_json,
                   tresc_md=excluded.tresc_md,
                   ocena_json=COALESCE(excluded.ocena_json, raporty.ocena_json)""",
            (pracownik, okres_typ, okres_klucz,
             datetime.now().isoformat(timespec="seconds"),
             json.dumps(metryki, ensure_ascii=False), tresc_md,
             json.dumps(ocena, ensure_ascii=False) if ocena else None),
        )
        self.con.commit()

    def raport(self, pracownik: str, okres_typ: str, okres_klucz: str) -> dict | None:
        r = self.con.execute(
            """SELECT utworzono, tresc_md, ocena_json FROM raporty
               WHERE pracownik=? AND okres_typ=? AND okres_klucz=?""",
            (pracownik, okres_typ, okres_klucz),
        ).fetchone()
        if not r:
            return None
        return {
            "utworzono": r["utworzono"],
            "tresc_md": r["tresc_md"],
            "ocena": json.loads(r["ocena_json"]) if r["ocena_json"] else None,
        }

    # --- wskaźniki punktowane --------------------------------------------

    def zapisz_wskazniki(self, pracownik: str, okres_typ: str, okres_klucz: str,
                         wartosci: dict[str, float]) -> None:
        """Wartości wskaźników z CRM, których nie ma w eksporcie aktywności.

        Pusty string albo None kasuje wpis — dzięki temu „nie wiem” różni się
        od „zero”, a raport potrafi pokazać, czego brakuje.
        """
        teraz = datetime.now().isoformat(timespec="seconds")
        for kod, wartosc in wartosci.items():
            if wartosc is None or wartosc == "":
                self.con.execute(
                    """DELETE FROM wskazniki WHERE pracownik=? AND okres_typ=?
                       AND okres_klucz=? AND kod=?""",
                    (pracownik, okres_typ, okres_klucz, kod),
                )
                continue
            self.con.execute(
                """INSERT INTO wskazniki
                     (pracownik, okres_typ, okres_klucz, kod, wartosc, zaktualizowano)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(pracownik, okres_typ, okres_klucz, kod) DO UPDATE SET
                     wartosc=excluded.wartosc, zaktualizowano=excluded.zaktualizowano""",
                (pracownik, okres_typ, okres_klucz, kod, float(wartosc), teraz),
            )
        self.con.commit()

    def wskazniki(self, pracownik: str, okres_typ: str, okres_klucz: str) -> dict[str, float]:
        sql = """SELECT kod, wartosc FROM wskazniki
                 WHERE pracownik=? AND okres_typ=? AND okres_klucz=?"""
        return {
            r["kod"]: r["wartosc"]
            for r in self.con.execute(sql, (pracownik, okres_typ, okres_klucz))
        }

    # --- pamięć agenta ----------------------------------------------------

    def dopisz_pamiec(self, pracownik: str, typ: str, tresc: str,
                      zrodlo_okres: str = "") -> None:
        self.con.execute(
            "INSERT INTO pamiec (pracownik, data, typ, tresc, zrodlo_okres) VALUES (?,?,?,?,?)",
            (pracownik, datetime.now().isoformat(timespec="seconds"), typ, tresc, zrodlo_okres),
        )
        self.con.commit()

    def pamiec(self, pracownik: str, limit: int = 20) -> list[dict]:
        sql = """SELECT data, typ, tresc, status, zrodlo_okres FROM pamiec
                 WHERE pracownik = ? ORDER BY id DESC LIMIT ?"""
        return [dict(r) for r in self.con.execute(sql, (pracownik, limit))]

    def zamknij(self) -> None:
        self.con.close()

    def __enter__(self) -> "Baza":
        return self

    def __exit__(self, *_) -> None:
        self.zamknij()
