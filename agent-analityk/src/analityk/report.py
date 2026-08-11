"""Budowa raportu w Markdown.

Raport ma dwie warstwy:
1. **Liczby** — zawsze, deterministycznie, bez LLM-a.
2. **Ocena i coaching** — z LLM-a, a gdy klucza API brak, z prostej heurystyki.

Dzięki temu system jest użyteczny od pierwszego dnia i nie przestaje działać,
gdy padnie API.
"""

from __future__ import annotations

from .metrics import alerty, porownaj
from .models import (
    Activity,
    WYNIK_INFO_RYNKOWE,
    WYNIK_LEAD,
    WYNIK_SYGNAL,
)
from .org import Pracownik

NAZWY_OKRESOW = {
    "dzien": "dzienny", "tydzien": "tygodniowy", "miesiac": "miesięczny",
    "kwartal": "kwartalny", "rok": "roczny",
}

ETYKIETY_WYNIKOW = {
    "lead": "Lead (chce sprzedać / wynająć)",
    "sygnal": "Sygnał na przyszłość",
    "info_rynkowe": "Informacja rynkowa",
    "nie_wlasciciel": "Nie właściciel (najemca / po sprzedaży)",
    "odmowa": "Odmowa",
    "odmowa_twarda": "Odmowa twarda (brak rozmowy)",
    "brak_info": "Rozmowa bez treści",
    "brak_kontaktu": "Brak kontaktu",
    "nieokreslony": "Nieokreślony",
}


def _strzalka(zmiana: float) -> str:
    if zmiana > 0:
        return f"▲ +{zmiana}"
    if zmiana < 0:
        return f"▼ {zmiana}"
    return "= 0"


def _tabela(naglowki: list[str], wiersze: list[list]) -> str:
    linie = ["| " + " | ".join(naglowki) + " |",
             "|" + "|".join(["---"] * len(naglowki)) + "|"]
    for w in wiersze:
        linie.append("| " + " | ".join("" if c is None else str(c) for c in w) + " |")
    return "\n".join(linie)


def heurystyczna_ocena(m: dict) -> tuple[list[str], list[str], list[str]]:
    """Zapasowa ocena bez LLM: (mocne strony, do poprawy, plan na następny okres)."""
    mocne: list[str] = []
    slabe: list[str] = []
    plan: list[str] = []

    if (m.get("realizacja_normy_proc") or 0) >= 100:
        mocne.append(f"Norma aktywności zrobiona w {m['realizacja_normy_proc']}%.")
    elif (m.get("realizacja_normy_proc") or 0) >= 80:
        mocne.append(f"Aktywność blisko normy ({m['realizacja_normy_proc']}%).")
    else:
        slabe.append(f"Aktywność poniżej normy ({m.get('realizacja_normy_proc')}%).")
        plan.append("Dobić do normy kontaktów — zaplanuj bloki pukania z góry, nie „ile wyjdzie”.")

    if m["notatki_merytoryczne_proc"] >= 80:
        mocne.append(f"Notatki prowadzone rzetelnie ({m['notatki_merytoryczne_proc']}% z treścią).")
    else:
        slabe.append(f"Notatki ubogie — tylko {m['notatki_merytoryczne_proc']}% ma sensowną treść.")
        plan.append("W każdej notatce: kto, jaka sytuacja lokalu, jaki następny krok i kiedy.")

    if m["leady"] + m["sygnaly"] > 0:
        mocne.append(f"Wyciągnięto {m['leady']} lead(y) i {m['sygnaly']} sygnał(y) na przyszłość.")
    else:
        slabe.append("Zero leadów i sygnałów w okresie.")
        plan.append("Po usłyszeniu „nie” zadaj jedno pytanie o sąsiadów i o plany na 12 miesięcy.")

    if m["follow_up_proc"] < 15:
        slabe.append(f"Follow-up tylko w {m['follow_up_proc']}% kontaktów — nie mają ciągu dalszego.")
        plan.append("Zostawiaj wizytówkę/ulotkę zawsze, gdy ktoś otworzy drzwi, i notuj to w CRM.")
    else:
        mocne.append(f"Follow-up zaplanowany w {m['follow_up_proc']}% kontaktów.")

    if m["info_rynkowe"] >= 5:
        mocne.append(f"Zebrano {m['info_rynkowe']} informacji rynkowych — to buduje wiedzę o terenie.")

    if m["praca_w_zlotych_godzinach_proc"] < 25 and m["kanaly"].get("bezposredni", 0) > 10:
        plan.append("Przesuń część pukania na 16:00–20:00 — wtedy zastaje się mieszkańców.")

    return mocne, slabe, plan[:3]


def zbuduj_raport(
    profil: Pracownik,
    typ_okresu: str,
    klucz_okresu_: str,
    m: dict,
    aktywnosci: list[Activity],
    m_poprzedni: dict | None = None,
    ocena_llm: dict | None = None,
    pamiec: list[dict] | None = None,
    grupy: list[dict] | None = None,
) -> str:
    """Składa pełny raport Markdown."""
    naglowek = (
        f"# Raport {NAZWY_OKRESOW[typ_okresu]} — {profil.imie_nazwisko}\n\n"
        f"**Stanowisko:** {profil.nazwa_roli}  \n"
        f"**Biuro:** {profil.biuro_nazwa or 'nieprzypisane'}  \n"
        f"**Okres:** {klucz_okresu_}  \n"
        f"**Rekordów w CRM:** {m.get('liczba_aktywnosci', 0)}\n"
    )

    if m.get("pusty"):
        return naglowek + "\n> Brak aktywności w tym okresie.\n"

    czesci = [naglowek]

    # --- 1. Liczby ---
    norma = m.get("norma", {})
    czesci.append("## 1. Ilość\n\n" + _tabela(
        ["Wskaźnik", "Wartość", "Norma", "Realizacja"],
        [
            ["Aktywności", m["liczba_aktywnosci"], norma.get("aktywnosci"),
             f"{m['realizacja_normy_proc']}%" if m.get("realizacja_normy_proc") is not None else None],
            ["Średnio dziennie", m["srednio_dziennie"], None, None],
            ["Unikalne budynki", m["unikalne_budynki"], None, None],
            ["Unikalne lokale", m["unikalne_lokale"], None, None],
            ["Kontakt bezpośredni", m["kanaly"].get("bezposredni", 0), None,
             f"{m['udzial_bezposrednich_proc']}%"],
            ["Telefon", m["kanaly"].get("telefon", 0), None, None],
        ],
    ))

    # --- 2. Jakość ---
    czesci.append("## 2. Jakość\n\n" + _tabela(
        ["Wskaźnik", "Wartość", "Komentarz"],
        [
            ["Konwersja na lead/sygnał", f"{m['konwersja_na_lead_proc']}%", "ze wszystkich kontaktów"],
            ["Leady", m["leady"], "deklaracja chęci sprzedaży/najmu"],
            ["Sygnały", m["sygnaly"], "„przemyśli”, „pod 1 chyba chciała”"],
            ["Informacje rynkowe", m["info_rynkowe"], "wiedza o terenie"],
            ["Odmowy twarde", m["odmowy_twarde"],
             f"{m['wskaznik_odmow_twardych_proc']}% kontaktów"],
            ["Kontaktów na 1 lead", m["kontaktow_na_lead"], "koszt pozyskania w aktywnościach"],
            ["Notatki z treścią", f"{m['notatki_merytoryczne_proc']}%",
             f"średnio {m['srednia_dlugosc_notatki']} znaków"],
            ["Follow-up", f"{m['follow_up_proc']}%",
             f"materiał: {m['material_zostawiony']}, kolejny krok: {m['kolejny_krok_zaplanowany']}"],
            ["**Indeks jakości pracy**", f"**{m['indeks_jakosci']}/100**", "ilość + jakość razem"],
        ],
    ))

    # --- 3. Organizacja czasu ---
    rozklad = " ".join(f"{g}:00→{n}" for g, n in m["rozklad_godzinowy"].items())
    czesci.append(
        "## 3. Organizacja czasu\n\n"
        f"- Pierwsza aktywność: **{m['pierwsza_aktywnosc']}**, ostatnia: **{m['ostatnia_aktywnosc']}**\n"
        f"- Średnia rozpiętość dnia: **{m['rozpietosc_dnia_h']} h**, tempo: **{m['aktywnosci_na_godzine']} akt./h**\n"
        f"- Praca w „złotych godzinach” (16–20): **{m['praca_w_zlotych_godzinach_proc']}%**\n"
        f"- Rozkład: {rozklad}\n"
    )

    # --- 4. Struktura wyników ---
    wiersze = [
        [ETYKIETY_WYNIKOW.get(w, w), n, f"{round(100 * n / m['liczba_aktywnosci'], 1)}%"]
        for w, n in m["wyniki"].items()
    ]
    czesci.append("## 4. Co wyszło z kontaktów\n\n" + _tabela(["Wynik", "Liczba", "Udział"], wiersze))

    if m["tagi"]:
        tagi = ", ".join(f"`{t}` × {n}" for t, n in m["tagi"].items())
        czesci.append(f"**Tagi z notatek:** {tagi}\n")

    # --- 5. Teren ---
    if m["top_budynki"]:
        wiersze = [[b, n] for b, n in m["top_budynki"].items()]
        czesci.append("## 5. Teren\n\n" + _tabela(["Budynek", "Kontakty"], wiersze))

    # --- 6. Trend ---
    if m_poprzedni and not m_poprzedni.get("pusty"):
        delty = porownaj(m, m_poprzedni)
        wiersze = [[p, d["teraz"], d["poprzednio"], _strzalka(d["zmiana"])]
                   for p, d in delty.items()]
        czesci.append("## 6. Trend względem poprzedniego okresu\n\n"
                      + _tabela(["Wskaźnik", "Teraz", "Poprzednio", "Zmiana"], wiersze))

    # --- 5b. Klasyfikacja punktowa ---
    if m.get("punkty"):
        czesci.append(_sekcja_punktow(m["punkty"]))

    # --- 6b. Na tle innych ---
    if grupy:
        czesci.append(_sekcja_porownania(grupy))

    # --- 7. Alerty ---
    ostrzezenia = alerty(m, m_poprzedni)
    if ostrzezenia:
        czesci.append("## 7. Alerty\n\n"
                      + "\n".join(f"- ⚠️ {o['tresc']}" for o in ostrzezenia))

    # --- 8. Ocena ---
    if ocena_llm:
        czesci.append(_sekcja_oceny_llm(ocena_llm))
    else:
        mocne, slabe, plan = heurystyczna_ocena(m)
        czesci.append(
            "## 8. Ocena (heurystyka — bez LLM)\n\n"
            "**Mocne strony**\n" + "\n".join(f"- {x}" for x in mocne) +
            "\n\n**Do poprawy**\n" + "\n".join(f"- {x}" for x in slabe) +
            "\n\n**Plan na następny okres**\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(plan, 1))
        )

    # --- 9. Do dopilnowania ---
    do_dopilnowania = [a for a in aktywnosci if a.wynik in (WYNIK_LEAD, WYNIK_SYGNAL)]
    if do_dopilnowania:
        wiersze = [
            [a.data.strftime("%d.%m %H:%M"), f"{a.budynek} / {a.lokal}".strip(" /"),
             ETYKIETY_WYNIKOW.get(a.wynik, a.wynik), a.notatka[:120]]
            for a in do_dopilnowania
        ]
        czesci.append("## 9. Do dopilnowania (leady i sygnały)\n\n"
                      + _tabela(["Kiedy", "Adres", "Typ", "Notatka"], wiersze))

    # --- 10. Wiedza rynkowa ---
    rynek = [a for a in aktywnosci if a.wynik == WYNIK_INFO_RYNKOWE]
    if rynek:
        czesci.append(
            "## 10. Wiedza rynkowa zebrana w okresie\n\n"
            + "\n".join(f"- **{a.budynek} {a.lokal}** — {a.notatka[:140]}" for a in rynek[:15])
        )

    # --- 11. Pamięć agenta ---
    if pamiec:
        czesci.append(
            "## 11. Z poprzednich okresów\n\n"
            + "\n".join(f"- [{w['data'][:10]}] *{w['typ']}*: {w['tresc']}" for w in pamiec[:8])
        )

    return "\n\n".join(czesci) + "\n"


def _sekcja_punktow(punkty: dict) -> str:
    """Rozbicie punktów z oficjalnej klasyfikacji sieci."""
    wiersze = [
        [p["kod"], p["nazwa"], "—" if p["brak_danych"] else int(p["ile"]),
         p["stawka"], int(p["punkty"])]
        for p in punkty["pozycje"]
    ]
    bloki = [
        "## 5b. Klasyfikacja punktowa\n\n"
        f"**Razem: {punkty['punkty_razem']:,.0f} pkt** "
        f"(aktywność {punkty['punkty_za_aktywnosc']:,.0f} + bonusy {punkty['punkty_bonusowe']:,.0f})"
        .replace(",", " "),
        _tabela(["Kod", "Wskaźnik", "Ile", "Stawka", "Punkty"], wiersze),
    ]
    if punkty["kompletnosc_proc"] < 100:
        bloki.append(
            f"> Uzupełnionych wskaźników: {punkty['kompletnosc_proc']}%. "
            f"Brakuje: {', '.join(punkty['wskazniki_bez_danych'])}. "
            "Brakujące liczą się jako zero, więc wynik jest zaniżony."
        )
    wiersze_bonusow = [
        [b["nazwa"],
         "brak danych" if b.get("brak_danych") else
         (f"{b['udzial_proc']}%" if b["udzial_proc"] is not None else "—"),
         f">{b['prog_proc']}%" if b.get("prog_proc") else "—",
         b["punkty"]]
        for b in punkty["bonusy"]
    ]
    bloki.append(_tabela(["Bonus", "Wynik", "Próg", "Punkty"], wiersze_bonusow))
    return "\n\n".join(bloki)


def _sekcja_porownania(grupy: list[dict]) -> str:
    bloki = ["## 6b. Na tle innych osób na tym samym stanowisku"]
    for g in grupy:
        tytul = f"**{g['nazwa']}** — osób w grupie: {g['liczebnosc']}"
        if not g["wiarygodne"]:
            tytul += "  \n> ⚠️ Grupa za mała na wnioski — traktuj poglądowo."
        bloki.append(tytul)
        wiersze = [
            [d["etykieta"], d["moja"], d["mediana_grupy"],
             f"{'+' if d['delta'] > 0 else ''}{d['delta']}",
             f"{d['percentyl']}." if d["percentyl"] is not None else "—",
             d["ocena"]]
            for d in g["pola"].values()
        ]
        bloki.append(_tabela(
            ["Wskaźnik", "Ta osoba", "Mediana grupy", "Różnica", "Percentyl", "Ocena"],
            wiersze,
        ))
    return "\n\n".join(bloki)


def _sekcja_oceny_llm(ocena: dict) -> str:
    def lista(klucz: str) -> str:
        return "\n".join(f"- {x}" for x in ocena.get(klucz, [])) or "- (brak)"

    plan = "\n".join(
        f"{i}. {x}" for i, x in enumerate(ocena.get("plan_na_nastepny_okres", []), 1)
    ) or "1. (brak)"

    return (
        "## 8. Ocena AI\n\n"
        f"**Podsumowanie:** {ocena.get('podsumowanie', '')}\n\n"
        + (f"**Na tle grupy:** {ocena['na_tle_grupy']}\n\n"
           if ocena.get("na_tle_grupy") else "")
        +
        f"**Mocne strony**\n{lista('mocne_strony')}\n\n"
        f"**Do poprawy**\n{lista('do_poprawy')}\n\n"
        f"**Plan na następny okres**\n{plan}\n\n"
        f"**Pytania na 1:1**\n{lista('pytania_na_1n1')}\n\n"
        f"**Ryzyka**\n{lista('ryzyka')}\n\n"
        f"*Ocena wygenerowana przez model AI — wymaga akceptacji przełożonego "
        f"przed przekazaniem pracownikowi.*"
    )
