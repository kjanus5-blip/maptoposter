"""Porównania: pracownik do grupy, biuro do biura.

„Julia zrobiła 47 kontaktów” nic nie znaczy. „47 kontaktów przy medianie 52
w tej samej roli i 3. miejsce na 7 osób w sieci” — znaczy. Ten moduł dostarcza
punkt odniesienia, bez którego ocena pojedynczej osoby jest zgadywaniem.

Dwie zasady, które są tu wbudowane:

1. **Porównujemy tylko w obrębie tej samej roli.** Kierownik z 12 kontaktami
   dziennie nie jest gorszy od agenta z 40 — ma inną pracę.
2. **Mała grupa to nie statystyka.** Przy mniej niż trzech osobach w grupie
   wynik jest oznaczany jako niewiarygodny i nie powinien iść do oceny.
"""

from __future__ import annotations

import statistics

from .metrics import podsumowanie, zakres_okresu
from .org import Pracownik
from .punktacja import dopisz_punkty, punkty_zespolu

MIN_GRUPY = 3  # poniżej tego progu porównanie jest szumem

#: Metryki brane do porównań + czy wyższa wartość znaczy lepiej.
POLA_PORONAWCZE = {
    "punkty_razem": True,
    "srednio_dziennie": True,
    "liczba_aktywnosci": True,
    "konwersja_na_lead_proc": True,
    "leady": True,
    "notatki_merytoryczne_proc": True,
    "follow_up_proc": True,
    "praca_w_zlotych_godzinach_proc": True,
    "wskaznik_odmow_twardych_proc": False,
    "indeks_jakosci": True,
}

ETYKIETY_POL = {
    "punkty_razem": "Punkty (klasyfikacja)",
    "srednio_dziennie": "Aktywności dziennie",
    "liczba_aktywnosci": "Aktywności w okresie",
    "konwersja_na_lead_proc": "Konwersja na lead",
    "leady": "Leady",
    "notatki_merytoryczne_proc": "Jakość notatek",
    "follow_up_proc": "Follow-up",
    "praca_w_zlotych_godzinach_proc": "Praca 16–20",
    "wskaznik_odmow_twardych_proc": "Twarde odmowy",
    "indeks_jakosci": "Indeks jakości",
}


# --- statystyki grupy -----------------------------------------------------

def statystyki(wartosci: list[float]) -> dict:
    czyste = [w for w in wartosci if w is not None]
    if not czyste:
        return {"n": 0}
    czyste.sort()
    return {
        "n": len(czyste),
        "mediana": round(statistics.median(czyste), 1),
        "srednia": round(statistics.fmean(czyste), 1),
        "min": round(czyste[0], 1),
        "max": round(czyste[-1], 1),
        "p25": round(czyste[max(0, int(0.25 * (len(czyste) - 1)))], 1),
        "p75": round(czyste[min(len(czyste) - 1, int(0.75 * (len(czyste) - 1)))], 1),
    }


def percentyl(wartosc: float, wartosci: list[float]) -> int | None:
    """Ile procent grupy ma wynik nie lepszy niż `wartosc` (0–100)."""
    czyste = [w for w in wartosci if w is not None]
    if not czyste:
        return None
    nie_lepsze = sum(1 for w in czyste if w <= wartosc)
    return round(100 * nie_lepsze / len(czyste))


def ocena_pozycji(percent: int | None, wyzej_lepiej: bool) -> str:
    if percent is None:
        return "brak danych"
    skala = percent if wyzej_lepiej else 100 - percent
    if skala >= 75:
        return "powyżej grupy"
    if skala >= 40:
        return "w normie grupy"
    return "poniżej grupy"


# --- zbieranie metryk -----------------------------------------------------

def metryki_grupy(baza, pracownicy: list[Pracownik], typ_okresu: str,
                  klucz_okresu: str) -> dict[str, dict]:
    """Metryki okresu dla listy pracowników: {klucz_pracownika: metryki}."""
    od, do = zakres_okresu(klucz_okresu, typ_okresu)
    wynik = {}
    for p in pracownicy:
        akt = baza.pobierz(pracownik=p.klucz, od=od, do=do)
        m = podsumowanie(akt, typ_okresu, p.normy_pelne, zakres=(od, do))
        wynik[p.klucz] = dopisz_punkty(baza, p, typ_okresu, klucz_okresu, akt, m)
    return wynik


def _wartosci(metryki: dict[str, dict], pole: str, pomin: str | None = None) -> list[float]:
    return [
        m.get(pole) for k, m in metryki.items()
        if k != pomin and not m.get("pusty") and m.get(pole) is not None
    ]


def porownaj_z_grupa(moje: dict, metryki_grupy_: dict[str, dict],
                     klucz_pracownika: str, nazwa_grupy: str) -> dict:
    """Porównanie jednej osoby z grupą — pole po polu."""
    pola = {}
    for pole, wyzej_lepiej in POLA_PORONAWCZE.items():
        wartosci = _wartosci(metryki_grupy_, pole, pomin=klucz_pracownika)
        moja = moje.get(pole)
        if moja is None or not wartosci:
            continue
        st = statystyki(wartosci)
        pct = percentyl(moja, wartosci)
        pola[pole] = {
            "etykieta": ETYKIETY_POL.get(pole, pole),
            "moja": moja,
            "mediana_grupy": st["mediana"],
            "delta": round(moja - st["mediana"], 1),
            "percentyl": pct,
            "ocena": ocena_pozycji(pct, wyzej_lepiej),
            "wyzej_lepiej": wyzej_lepiej,
            "min": st["min"],
            "max": st["max"],
        }

    liczebnosc = len({k for k, m in metryki_grupy_.items()
                      if k != klucz_pracownika and not m.get("pusty")})
    return {
        "nazwa": nazwa_grupy,
        "liczebnosc": liczebnosc,
        "wiarygodne": liczebnosc >= MIN_GRUPY,
        "pola": pola,
    }


def grupy_porownawcze(baza, pracownik: Pracownik, typ_okresu: str,
                      klucz_okresu: str, moje_metryki: dict) -> list[dict]:
    """Dwie grupy odniesienia: ta sama rola w biurze i ta sama rola w sieci."""
    grupy = []

    if pracownik.biuro_id is not None:
        w_biurze = baza.pracownicy(biuro_id=pracownik.biuro_id, rola=pracownik.rola)
        if len(w_biurze) > 1:
            m = metryki_grupy(baza, w_biurze, typ_okresu, klucz_okresu)
            grupy.append(porownaj_z_grupa(
                moje_metryki, m, pracownik.klucz,
                f"{pracownik.nazwa_roli} w biurze {pracownik.biuro_nazwa}",
            ))

    w_sieci = baza.pracownicy(rola=pracownik.rola)
    if len(w_sieci) > 1:
        m = metryki_grupy(baza, w_sieci, typ_okresu, klucz_okresu)
        grupy.append(porownaj_z_grupa(
            moje_metryki, m, pracownik.klucz,
            f"{pracownik.nazwa_roli} we wszystkich biurach",
        ))
    return grupy


# --- poziom biura ---------------------------------------------------------

def suma_norm(zespol: list) -> dict:
    """Norma grupy = suma norm indywidualnych.

    Zbiorczą pulę aktywności wolno porównywać tylko do zsumowanej normy.
    Zestawienie jej z normą jednej osoby daje procenty rzędu kilkuset i
    wygląda jak sukces, choć nie znaczy nic.
    """
    normy: dict = {}
    for p in zespol:
        for okres, wartosci in p.normy_pelne.items():
            cel = normy.setdefault(okres, {})
            for k, v in wartosci.items():
                cel[k] = cel.get(k, 0) + v
    return normy


def metryki_biura(baza, biuro_id: int | None, typ_okresu: str,
                  klucz_okresu: str) -> dict:
    """Metryki biura liczone ze **wspólnej puli aktywności** wszystkich jego
    pracowników — a nie jako średnia ze średnich, która potrafi kłamać."""
    od, do = zakres_okresu(klucz_okresu, typ_okresu)
    zespol = ([p for p in baza.pracownicy() if p.biuro_id is None]
              if biuro_id is None else baza.pracownicy(biuro_id=biuro_id))
    aktywnosci = []
    for p in zespol:
        aktywnosci.extend(baza.pobierz(pracownik=p.klucz, od=od, do=do))

    m = podsumowanie(aktywnosci, typ_okresu, suma_norm(zespol), zakres=(od, do))
    wynik_punktowy = punkty_zespolu(baza, zespol, typ_okresu, klucz_okresu, od, do)
    m["punkty"] = wynik_punktowy
    m["punkty_razem"] = wynik_punktowy["punkty_razem"]
    m["liczniki_operacyjne"] = wynik_punktowy.get("liczniki_operacyjne", {})
    m["liczba_pracownikow"] = len(zespol)
    m["liczba_pracujacych"] = len({a.pracownik for a in aktywnosci})
    m["role"] = {
        rola: sum(1 for p in zespol if p.rola == rola)
        for rola in sorted({p.rola for p in zespol})
    }
    return m


def ranking_biur(baza, typ_okresu: str, klucz_okresu: str,
                 pole: str = "punkty_razem") -> list[dict]:
    """Zestawienie biur posortowane po wybranej metryce."""
    pozycje = []
    for b in baza.biura():
        m = metryki_biura(baza, b.id, typ_okresu, klucz_okresu)
        pozycje.append({"biuro": b, "metryki": m, "wartosc": m.get(pole) or 0})
    pozycje.sort(key=lambda x: x["wartosc"], reverse=True)
    for i, poz in enumerate(pozycje, 1):
        poz["miejsce"] = i
    return pozycje


def opis_dla_modelu(grupy: list[dict]) -> str:
    """Porównania w formie tekstowej — trafia wprost do promptu."""
    if not grupy:
        return "(brak grupy porównawczej — za mało osób w tej roli)"
    linie = []
    for g in grupy:
        naglowek = f"### {g['nazwa']} (osób w grupie: {g['liczebnosc']})"
        if not g["wiarygodne"]:
            naglowek += "  [UWAGA: grupa za mała, traktuj poglądowo]"
        linie.append(naglowek)
        for dane in g["pola"].values():
            znak = "+" if dane["delta"] > 0 else ""
            linie.append(
                f"- {dane['etykieta']}: {dane['moja']} vs mediana {dane['mediana_grupy']} "
                f"({znak}{dane['delta']}), percentyl {dane['percentyl']} — {dane['ocena']}"
            )
    return "\n".join(linie)
