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
        self.con = sqlite3.connect(self.sciezka)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMAT)
        self.con.commit()

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

    def pracownicy(self) -> list[tuple[str, str, int]]:
        sql = """SELECT pracownik, pracownik_nazwa, COUNT(*) n
                 FROM aktywnosci GROUP BY pracownik ORDER BY n DESC"""
        return [(r["pracownik"], r["pracownik_nazwa"], r["n"]) for r in self.con.execute(sql)]

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
                      metryki: dict, tresc_md: str) -> None:
        self.con.execute(
            """INSERT INTO raporty (pracownik, okres_typ, okres_klucz, utworzono,
                                    metryki_json, tresc_md)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(pracownik, okres_typ, okres_klucz) DO UPDATE SET
                   utworzono=excluded.utworzono,
                   metryki_json=excluded.metryki_json,
                   tresc_md=excluded.tresc_md""",
            (pracownik, okres_typ, okres_klucz,
             datetime.now().isoformat(timespec="seconds"),
             json.dumps(metryki, ensure_ascii=False), tresc_md),
        )
        self.con.commit()

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
