"""Interfejs wiersza poleceń.

    python -m analityk wczytaj eksport.pdf
    python -m analityk raport --pracownik julia_baranowska --okres dzien
    python -m analityk zespol --okres tydzien
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from glob import glob
from pathlib import Path

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
from .profiles import Profil, wczytaj_profil, zapisz_profil
from .report import zbuduj_raport
from .store import Baza


def _metryki_okresu(baza: Baza, pracownik: str, typ: str, klucz: str, normy: dict):
    od, do = zakres_okresu(klucz, typ)
    akt = baza.pobierz(pracownik=pracownik, od=od, do=do)
    return akt, podsumowanie(akt, typ, normy, zakres=(od, do))


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
    print(f"\nRazem: {lacznie_nowe} nowych, {lacznie_dupl} pominiętych.")
    for klucz, nazwa, n in baza.pracownicy():
        print(f"  {klucz:24} {nazwa:24} {n} aktywności")
    return 0


def cmd_metryki(args) -> int:
    baza = Baza(args.baza)
    klucz = args.okres_klucz or klucz_okresu(date.fromisoformat(args.data), args.okres)
    profil = wczytaj_profil(args.pracownik)
    _, m = _metryki_okresu(baza, args.pracownik, args.okres, klucz, profil.normy_pelne)
    print(json.dumps(m, ensure_ascii=False, indent=2))
    return 0


def cmd_raport(args) -> int:
    baza = Baza(args.baza)
    klucz = args.okres_klucz or klucz_okresu(date.fromisoformat(args.data), args.okres)

    nazwa = next((n for k, n, _ in baza.pracownicy() if k == args.pracownik), args.pracownik)
    profil = wczytaj_profil(args.pracownik, nazwa)

    akt, m = _metryki_okresu(baza, args.pracownik, args.okres, klucz, profil.normy_pelne)
    _, m_poprz = _metryki_okresu(
        baza, args.pracownik, args.okres, poprzedni_okres(klucz, args.okres), profil.normy_pelne
    )
    pamiec = baza.pamiec(args.pracownik, limit=10)

    ocena = None
    if args.llm and not m.get("pusty"):
        from .llm import BrakKlucza, ocena_okresu
        trend = porownaj(m, m_poprz) if not m_poprz.get("pusty") else {}
        try:
            ocena = ocena_okresu(
                profil, args.okres, klucz, m, trend, alerty(m, m_poprz), pamiec, akt,
                model=args.model, tylko_prompt=args.pokaz_prompt,
            )
            if args.pokaz_prompt:
                print(ocena)
                return 0
        except BrakKlucza as e:
            print(f"! {e}\n! Raport powstanie bez oceny AI.", file=sys.stderr)

    tresc = zbuduj_raport(profil, args.okres, klucz, m, akt, m_poprz, ocena, pamiec)
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
    klucz = args.okres_klucz or klucz_okresu(date.fromisoformat(args.data), args.okres)
    per_prac = {}
    nazwy = {}
    for kl, nazwa, _ in baza.pracownicy():
        profil = wczytaj_profil(kl, nazwa)
        _, m = _metryki_okresu(baza, kl, args.okres, klucz, profil.normy_pelne)
        per_prac[kl] = m
        nazwy[kl] = nazwa

    print(f"\n# Zespół — okres {args.okres} {klucz}\n")
    naglowki = ["#", "Pracownik", "Aktywności", "Rozmowy", "Leady", "Dotarcie",
                "Notatki", "Indeks"]
    print("| " + " | ".join(naglowki) + " |")
    print("|" + "|".join(["---"] * len(naglowki)) + "|")
    for poz, (kl, indeks, _) in enumerate(ranking_zespolu(per_prac), 1):
        m = per_prac[kl]
        print(f"| {poz} | {nazwy[kl]} | {m['liczba_aktywnosci']} | {m['rozmowy_odbyte']} | "
              f"{m['leady']} | {m['wskaznik_dotarcia_proc']}% | "
              f"{m['notatki_merytoryczne_proc']}% | **{indeks}** |")

    print("\n## Alerty\n")
    for kl, m in per_prac.items():
        for a in alerty(m):
            print(f"- **{nazwy[kl]}**: {a}")
    return 0


def cmd_profil(args) -> int:
    if args.pokaz:
        p = wczytaj_profil(args.pracownik)
        print(json.dumps(p.__dict__, ensure_ascii=False, indent=2))
        return 0
    baza = Baza(args.baza)
    nazwa = next((n for k, n, _ in baza.pracownicy() if k == args.pracownik), args.pracownik)
    p = wczytaj_profil(args.pracownik, nazwa)
    if args.staz is not None:
        p.staz_miesiace = args.staz
    if args.rola:
        p.rola = args.rola
    if args.obszar:
        p.obszar_farmingu = args.obszar
    if args.norma_dzienna:
        p.normy.setdefault("dzien", {})["aktywnosci"] = args.norma_dzienna
    sciezka = zapisz_profil(p)
    print(f"Zapisano profil: {sciezka}")
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


# --- parser ---------------------------------------------------------------

def zbuduj_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="analityk",
        description="Analiza aktywności agentów biura nieruchomości.",
    )
    p.add_argument("--baza", default="data/analityk.db")
    pod = p.add_subparsers(dest="komenda", required=True)

    w = pod.add_parser("wczytaj", help="wczytuje eksport z CRM (PDF/CSV) do bazy")
    w.add_argument("pliki", nargs="+")
    w.set_defaults(func=cmd_wczytaj)

    def wspolne_okresu(sp):
        sp.add_argument("--okres", choices=TYPY_OKRESOW, default="dzien")
        sp.add_argument("--data", default=date.today().isoformat(),
                        help="dowolny dzień z okresu (YYYY-MM-DD)")
        sp.add_argument("--okres-klucz", dest="okres_klucz",
                        help="klucz okresu wprost, np. 2026-W33, 2026-08, 2026-Q3")

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

    z = pod.add_parser("zespol", help="ranking i alerty dla całego zespołu")
    wspolne_okresu(z)
    z.set_defaults(func=cmd_zespol)

    pr = pod.add_parser("profil", help="podgląd i edycja profilu pracownika")
    pr.add_argument("--pracownik", required=True)
    pr.add_argument("--pokaz", action="store_true")
    pr.add_argument("--staz", type=int, help="staż w miesiącach")
    pr.add_argument("--rola")
    pr.add_argument("--obszar", nargs="*")
    pr.add_argument("--norma-dzienna", dest="norma_dzienna", type=int)
    pr.set_defaults(func=cmd_profil)

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
