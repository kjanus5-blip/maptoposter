"""Interfejs wiersza poleceń.

    python -m analityk serwer                    # panel WWW (najprostsza droga)
    python -m analityk wczytaj eksport.pdf
    python -m analityk raport --pracownik julia_baranowska --okres dzien
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from glob import glob
from pathlib import Path

from .benchmark import grupy_porownawcze, opis_dla_modelu, ranking_biur
from .classify import sklasyfikuj
from .ingest import wczytaj_plik
from .metrics import (
    TYPY_OKRESOW,
    alerty,
    klucz_okresu,
    podsumowanie,
    poprzedni_okres,
    porownaj,
    ranking_zespolu,
    zakres_okresu,
)
from .org import NAZWY_ROL, ROLE, Biuro
from .punktacja import dopisz_punkty
from .report import zbuduj_raport
from .store import Baza


def _metryki_okresu(baza: Baza, prac, typ: str, klucz: str):
    """Metryki + punkty klasyfikacji dla jednego pracownika."""
    od, do = zakres_okresu(klucz, typ)
    akt = baza.pobierz(pracownik=prac.klucz, od=od, do=do)
    m = podsumowanie(akt, typ, prac.normy_pelne, zakres=(od, do))
    return akt, dopisz_punkty(baza, prac, typ, klucz, akt, m)


def _klucz_z_argumentow(args) -> str:
    return args.okres_klucz or klucz_okresu(date.fromisoformat(args.data), args.okres)


# --- komendy --------------------------------------------------------------

def cmd_wczytaj(args) -> int:
    baza = Baza(args.baza)
    lacznie_nowe = lacznie_dupl = 0
    for wzorzec in args.pliki:
        # glob ze stdlib radzi sobie ze ścieżkami bezwzględnymi; gdy nic nie
        # pasuje, próbujemy ścieżki dosłownie, żeby dać czytelny komunikat.
        znalezione = [Path(s) for s in sorted(glob(wzorzec))] or [Path(wzorzec)]
        for sciezka in znalezione:
            if not sciezka.is_file():
                print(f"! brak pliku: {sciezka}", file=sys.stderr)
                continue
            akt = sklasyfikuj(wczytaj_plik(sciezka))
            nowe, dupl = baza.zapisz_aktywnosci(akt)
            lacznie_nowe += nowe
            lacznie_dupl += dupl
            print(f"{sciezka}: {len(akt)} rekordów → {nowe} nowych, {dupl} duplikatów")

    nowi = baza.synchronizuj_pracownikow()
    print(f"\nRazem: {lacznie_nowe} nowych, {lacznie_dupl} pominiętych.")
    if nowi:
        print(f"Nowe osoby w systemie: {nowi} — przypisz je do biur "
              f"(panel WWW albo `analityk pracownik --klucz X --biuro N`).")
    for p in baza.pracownicy():
        print(f"  {p.klucz:24} {p.imie_nazwisko:24} {NAZWY_ROL[p.rola]:15} "
              f"{p.biuro_nazwa or '— bez biura —'}")
    return 0


def cmd_metryki(args) -> int:
    baza = Baza(args.baza)
    klucz = _klucz_z_argumentow(args)
    p = baza.pracownik_lub_domyslny(args.pracownik)
    _, m = _metryki_okresu(baza, p, args.okres, klucz)
    print(json.dumps(m, ensure_ascii=False, indent=2))
    return 0


def cmd_raport(args) -> int:
    baza = Baza(args.baza)
    klucz = _klucz_z_argumentow(args)
    p = baza.pracownik_lub_domyslny(args.pracownik)

    akt, m = _metryki_okresu(baza, p, args.okres, klucz)
    _, m_poprz = _metryki_okresu(
        baza, p, args.okres, poprzedni_okres(klucz, args.okres)
    )
    pamiec = baza.pamiec(args.pracownik, limit=10)
    grupy = [] if m.get("pusty") else grupy_porownawcze(baza, p, args.okres, klucz, m)

    ocena = None
    if args.llm and not m.get("pusty"):
        from .llm import BrakKlucza, ocena_okresu
        trend = porownaj(m, m_poprz) if not m_poprz.get("pusty") else {}
        try:
            ocena = ocena_okresu(
                p, args.okres, klucz, m, trend, alerty(m, m_poprz), pamiec, akt,
                model=args.model, tylko_prompt=args.pokaz_prompt,
                porownania=opis_dla_modelu(grupy),
            )
            if args.pokaz_prompt:
                print(ocena)
                return 0
        except BrakKlucza as e:
            print(f"! {e}\n! Raport powstanie bez oceny AI.", file=sys.stderr)

    tresc = zbuduj_raport(p, args.okres, klucz, m, akt, m_poprz, ocena, pamiec, grupy)
    baza.zapisz_raport(args.pracownik, args.okres, klucz, m, tresc)

    if ocena:
        for obs in ocena.get("obserwacje_do_zapamietania", []):
            baza.dopisz_pamiec(args.pracownik, "obserwacja", obs, f"{args.okres}:{klucz}")
        for zal in ocena.get("plan_na_nastepny_okres", []):
            baza.dopisz_pamiec(args.pracownik, "zalecenie", zal, f"{args.okres}:{klucz}")

    if args.zapisz:
        katalog = Path(args.katalog_raportow) / args.pracownik
        katalog.mkdir(parents=True, exist_ok=True)
        plik = katalog / f"{args.okres}_{klucz}.md"
        plik.write_text(tresc, encoding="utf-8")
        print(f"Zapisano: {plik}")
    else:
        print(tresc)
    return 0


def cmd_zespol(args) -> int:
    baza = Baza(args.baza)
    klucz = _klucz_z_argumentow(args)

    print(f"\n# Okres {args.okres} {klucz}\n")

    biura = baza.biura()
    if biura:
        print("## Biura\n")
        naglowki = ["#", "Biuro", "Osób", "Aktywności", "Leady", "Dotarcie", "Punkty"]
        print("| " + " | ".join(naglowki) + " |")
        print("|" + "|".join(["---"] * len(naglowki)) + "|")
        for poz in ranking_biur(baza, args.okres, klucz):
            m = poz["metryki"]
            if m.get("pusty"):
                print(f"| {poz['miejsce']} | {poz['biuro'].nazwa} | "
                      f"{m.get('liczba_pracownikow', 0)} | 0 | — | — | — |")
                continue
            print(f"| {poz['miejsce']} | {poz['biuro'].nazwa} | {m['liczba_pracownikow']} | "
                  f"{m['liczba_aktywnosci']} | {m['leady']} | "
                  f"{m['wskaznik_dotarcia_proc']}% | **{m['punkty_razem']:,.0f}".replace(",", " ") + "** |")
        print()

    grupy = {b.id: b.nazwa for b in biura}
    grupy[None] = "— bez biura —"
    for biuro_id, nazwa in grupy.items():
        zespol = [p for p in baza.pracownicy() if p.biuro_id == biuro_id]
        if not zespol:
            continue
        per_prac, nazwy = {}, {}
        for p in zespol:
            _, m = _metryki_okresu(baza, p, args.okres, klucz)
            per_prac[p.klucz] = m
            nazwy[p.klucz] = f"{p.imie_nazwisko} ({NAZWY_ROL[p.rola]})"

        print(f"## {nazwa}\n")
        naglowki = ["#", "Pracownik", "Aktywności", "Rozmowy", "Leady", "Dotarcie",
                    "Notatki", "Indeks", "Punkty"]
        print("| " + " | ".join(naglowki) + " |")
        print("|" + "|".join(["---"] * len(naglowki)) + "|")
        for poz, (kl, _punkty, _) in enumerate(ranking_zespolu(per_prac), 1):
            m = per_prac[kl]
            print(f"| {poz} | {nazwy[kl]} | {m['liczba_aktywnosci']} | {m['rozmowy_odbyte']} | "
                  f"{m['leady']} | {m['wskaznik_dotarcia_proc']}% | "
                  f"{m['notatki_merytoryczne_proc']}% | {m['indeks_jakosci']} | "
                  f"**{m['punkty_razem']:,.0f}".replace(",", " ") + "** |")
        print()

    print("## Alerty\n")
    for p in baza.pracownicy():
        _, m = _metryki_okresu(baza, p, args.okres, klucz)
        for a in alerty(m):
            print(f"- **{p.imie_nazwisko}**: {a}")
    return 0


def cmd_biuro(args) -> int:
    baza = Baza(args.baza)
    if args.dodaj:
        biuro_id = baza.zapisz_biuro(
            Biuro(nazwa=args.dodaj, miasto=args.miasto or "", adres=args.adres or "")
        )
        print(f"Dodano biuro #{biuro_id}: {args.dodaj}")
        return 0
    if args.usun:
        baza.usun_biuro(args.usun)
        print(f"Usunięto biuro #{args.usun}. Pracownicy trafili do puli bez biura.")
        return 0
    for b in baza.biura():
        zespol = baza.pracownicy(biuro_id=b.id)
        role = ", ".join(f"{NAZWY_ROL[r]}: {sum(1 for p in zespol if p.rola == r)}"
                         for r in ROLE if any(p.rola == r for p in zespol))
        print(f"#{b.id:<3} {b.etykieta:36} osób: {len(zespol):<3} {role}")
    nieprzypisani = baza.nieprzypisani()
    if nieprzypisani:
        print("\nBez biura: " + ", ".join(p.imie_nazwisko for p in nieprzypisani))
    return 0


def cmd_pracownik(args) -> int:
    baza = Baza(args.baza)
    p = baza.pracownik_lub_domyslny(args.klucz)
    if args.pokaz:
        print(json.dumps(p.__dict__, ensure_ascii=False, indent=2))
        return 0
    if args.biuro is not None:
        p.biuro_id = args.biuro or None
    if args.rola:
        p.rola = args.rola
    if args.staz is not None:
        p.staz_miesiace = args.staz
    if args.obszar:
        p.obszar_farmingu = args.obszar
    if args.norma_dzienna:
        p.normy.setdefault("dzien", {})["aktywnosci"] = args.norma_dzienna
    if args.uwagi:
        p.uwagi_managera = args.uwagi
    baza.zapisz_pracownika(p)
    zapisany = baza.pracownik(p.klucz)
    print(f"Zapisano: {zapisany.imie_nazwisko} — {NAZWY_ROL[zapisany.rola]}, "
          f"biuro: {zapisany.biuro_nazwa or 'brak'}")
    return 0


def cmd_pamiec(args) -> int:
    baza = Baza(args.baza)
    if args.dodaj:
        baza.dopisz_pamiec(args.pracownik, args.typ, args.dodaj)
        print("Dopisano do pamięci agenta.")
        return 0
    for w in baza.pamiec(args.pracownik, limit=args.limit):
        print(f"[{w['data'][:16]}] {w['typ']:12} {w['tresc']}")
    return 0


def cmd_serwer(args) -> int:
    from .web import uruchom
    uruchom(args.baza, host=args.host, port=args.port, debug=args.debug)
    return 0


# --- parser ---------------------------------------------------------------

def zbuduj_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="analityk",
        description="Analiza aktywności pracowników biur nieruchomości.",
    )
    p.add_argument("--baza", default="data/analityk.db")
    pod = p.add_subparsers(dest="komenda", required=True)

    def wspolne_okresu(sp):
        sp.add_argument("--okres", choices=TYPY_OKRESOW, default="dzien")
        sp.add_argument("--data", default=date.today().isoformat(),
                        help="dowolny dzień z okresu (YYYY-MM-DD)")
        sp.add_argument("--okres-klucz", dest="okres_klucz",
                        help="klucz okresu wprost, np. 2026-W33, 2026-08, 2026-Q3")

    s = pod.add_parser("serwer", help="uruchamia panel WWW")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=5000)
    s.add_argument("--debug", action="store_true")
    s.set_defaults(func=cmd_serwer)

    w = pod.add_parser("wczytaj", help="wczytuje eksport z CRM (PDF/CSV/XLSX)")
    w.add_argument("pliki", nargs="+")
    w.set_defaults(func=cmd_wczytaj)

    m = pod.add_parser("metryki", help="surowe metryki w JSON")
    m.add_argument("--pracownik", required=True)
    wspolne_okresu(m)
    m.set_defaults(func=cmd_metryki)

    r = pod.add_parser("raport", help="raport Markdown dla pracownika")
    r.add_argument("--pracownik", required=True)
    wspolne_okresu(r)
    r.add_argument("--llm", action="store_true", help="dołącz ocenę z modelu Claude")
    r.add_argument("--model", default="claude-opus-5")
    r.add_argument("--pokaz-prompt", dest="pokaz_prompt", action="store_true",
                   help="wypisz prompt zamiast wołać API (podgląd, koszt 0)")
    r.add_argument("--zapisz", action="store_true")
    r.add_argument("--katalog-raportow", dest="katalog_raportow", default="raporty")
    r.set_defaults(func=cmd_raport)

    z = pod.add_parser("zespol", help="ranking biur i pracowników + alerty")
    wspolne_okresu(z)
    z.set_defaults(func=cmd_zespol)

    b = pod.add_parser("biuro", help="lista i zarządzanie biurami")
    b.add_argument("--dodaj", metavar="NAZWA")
    b.add_argument("--miasto")
    b.add_argument("--adres")
    b.add_argument("--usun", type=int, metavar="ID")
    b.set_defaults(func=cmd_biuro)

    pr = pod.add_parser("pracownik", help="przypisanie do biura, rola, normy")
    pr.add_argument("--klucz", required=True)
    pr.add_argument("--pokaz", action="store_true")
    pr.add_argument("--biuro", type=int, help="ID biura (0 = bez biura)")
    pr.add_argument("--rola", choices=ROLE)
    pr.add_argument("--staz", type=int, help="staż w miesiącach")
    pr.add_argument("--obszar", nargs="*")
    pr.add_argument("--norma-dzienna", dest="norma_dzienna", type=int)
    pr.add_argument("--uwagi")
    pr.set_defaults(func=cmd_pracownik)

    pm = pod.add_parser("pamiec", help="pamięć agenta: ustalenia, zalecenia, obserwacje")
    pm.add_argument("--pracownik", required=True)
    pm.add_argument("--dodaj", help="treść wpisu")
    pm.add_argument("--typ", default="ustalenie_1n1",
                    choices=["obserwacja", "zalecenie", "ustalenie_1n1", "cel"])
    pm.add_argument("--limit", type=int, default=20)
    pm.set_defaults(func=cmd_pamiec)

    return p


def main(argv: list[str] | None = None) -> int:
    args = zbuduj_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
