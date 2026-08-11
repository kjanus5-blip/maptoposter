"""Budowa raportu w Markdown.

Raport ma dwie warstwy:
1. **Liczby** — zawsze, deterministycznie, bez LLM-a.
2. **Ocena i coaching** — z LLM-a, a gdy klucza API brak, z prostej heurystyki.

Dzięki temu system jest użyteczny od pierwszego dnia i nie przestaje działać,
gdy padnie API.
"""

from __future__ import annotations

from itertools import count

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


def _pasek(proc: float | None, dlugosc: int = 12) -> str:
    """Pasek z bloków — w czystym Markdownie to jedyny sposób na wykres.

    Wygląda tak samo w każdym podglądzie Markdowna, bo to zwykłe znaki.
    """
    if proc is None:
        return "—"
    pelne = round(dlugosc * min(max(proc, 0), 100) / 100)
    return "█" * pelne + "░" * (dlugosc - pelne) + f" {proc}%"


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


def _skrot(m: dict) -> str:
    """Cztery liczby na samej górze — żeby nie trzeba było czytać całości."""
    realizacja = m.get("realizacja_normy_proc")
    punkty = m.get("punkty_razem")
    return "> **W skrócie** · " + " · ".join(filter(None, [
        f"{m['liczba_aktywnosci']} aktywności ({m['srednio_dziennie']}/dzień)",
        f"realizacja normy {realizacja}%" if realizacja is not None else None,
        f"{m['leady']} leadów i {m['sygnaly']} sygnałów "
        f"(konwersja {m['konwersja_na_lead_proc']}%)",
        f"{punkty:,.0f} pkt".replace(",", " ") if punkty is not None else None,
        f"indeks jakości {m['indeks_jakosci']}/100",
    ]))


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

    czesci = [naglowek, _skrot(m)]

    # Numer sekcji nadajemy w locie. Wcześniej były wpisane na sztywno i po
    # dołożeniu punktacji raport szedł 5, 6, 5b, 6b, 7 — czyli nijak.
    numer = count(1)

    def sekcja(tytul: str, tresc: str) -> str:
        return f"## {next(numer)}. {tytul}\n\n{tresc}"

    # --- ilość ---
    norma = m.get("norma", {})
    norma_teraz = m.get("norma_proporcjonalna", norma.get("aktywnosci"))
    czesci.append(sekcja("Ilość pracy", _tabela(
        ["Wskaźnik", "Wartość", "Norma", "Realizacja"],
        [
            ["Aktywności", m["liczba_aktywnosci"], norma_teraz,
             _pasek(m.get("realizacja_normy_proc"))],
            ["Średnio dziennie", m["srednio_dziennie"], None, None],
            ["Dni z aktywnością", m["dni_z_aktywnoscia"],
             m.get("dni_robocze_uplynelo"),
             f"{m.get('dni_bez_aktywnosci', 0)} dni pustych"],
            ["Kontakt bezpośredni", m["kanaly"].get("bezposredni", 0), None,
             f"{m['udzial_bezposrednich_proc']}% wszystkich"],
            ["Telefon", m["kanaly"].get("telefon", 0), None, None],
            ["Budynki / lokale", f"{m['unikalne_budynki']} / {m['unikalne_lokale']}",
             None, None],
        ],
    ) + (f"\n\nNorma proporcjonalna do dni, które już minęły "
         f"({norma.get('aktywnosci')} za cały okres)."
         if norma_teraz != norma.get("aktywnosci") else "")))

    # --- jakość ---
    czesci.append(sekcja("Jakość pracy", _tabela(
        ["Wskaźnik", "Wartość", "Komentarz"],
        [
            ["Konwersja na lead/sygnał", _pasek(m["konwersja_na_lead_proc"]),
             "ze wszystkich kontaktów"],
            ["Leady", m["leady"], "deklaracja chęci sprzedaży/najmu"],
            ["Sygnały", m["sygnaly"], "„przemyśli”, „może za rok”"],
            ["Informacje rynkowe", m["info_rynkowe"], "wiedza o terenie"],
            ["Odmowy twarde", m["odmowy_twarde"],
             f"{m['wskaznik_odmow_twardych_proc']}% kontaktów"],
            ["Kontaktów na 1 lead", m["kontaktow_na_lead"],
             "koszt pozyskania w aktywnościach"],
            ["Notatki z treścią", _pasek(m["notatki_merytoryczne_proc"]),
             f"średnio {m['srednia_dlugosc_notatki']} znaków"],
            ["Follow-up", _pasek(m["follow_up_proc"]),
             f"materiał: {m['material_zostawiony']}, "
             f"kolejny krok: {m['kolejny_krok_zaplanowany']}"],
            ["**Indeks jakości pracy**", f"**{m['indeks_jakosci']}/100**",
             "ilość + jakość razem"],
        ],
    )))

    # --- struktura wyników ---
    wiersze = [
        [ETYKIETY_WYNIKOW.get(w, w), n,
         _pasek(round(100 * n / m["liczba_aktywnosci"], 1))]
        for w, n in m["wyniki"].items()
    ]
    blok = _tabela(["Wynik", "Liczba", "Udział"], wiersze)
    if m["tagi"]:
        tagi = ", ".join(f"`{t}` × {n}" for t, n in m["tagi"].items())
        blok += f"\n\n**Tagi z notatek:** {tagi}"
    czesci.append(sekcja("Co wyszło z kontaktów", blok))

    # --- organizacja czasu ---
    rozklad = " ".join(f"{g}:00→{n}" for g, n in m["rozklad_godzinowy"].items())
    czesci.append(sekcja("Organizacja czasu",
        f"- Dzień od **{m['pierwsza_aktywnosc']}** do **{m['ostatnia_aktywnosc']}**, "
        f"średnio **{m['rozpietosc_dnia_h']} h** "
        f"(tempo {m['aktywnosci_na_godzine']} akt./h)\n"
        f"- Praca w „złotych godzinach” 16–20: {_pasek(m['praca_w_zlotych_godzinach_proc'])}\n"
        f"- Rozkład godzinowy: {rozklad}"))

    # --- teren ---
    if m["top_budynki"]:
        wiersze = [[b, n] for b, n in m["top_budynki"].items()]
        czesci.append(sekcja("Teren", _tabela(["Budynek", "Kontakty"], wiersze)))

    # --- punktacja ---
    if m.get("punkty"):
        czesci.append(sekcja("Klasyfikacja punktowa",
                             _sekcja_punktow(m["punkty"], m.get("liczniki_operacyjne"))))

    # --- na tle grupy ---
    if grupy:
        czesci.append(sekcja("Na tle innych na tym samym stanowisku",
                             _sekcja_porownania(grupy)))

    # --- trend ---
    if m_poprzedni and not m_poprzedni.get("pusty"):
        wiersze = [[p, d["teraz"], d["poprzednio"], _strzalka(d["zmiana"])]
                   for p, d in porownaj(m, m_poprzedni).items()]
        czesci.append(sekcja("Trend względem poprzedniego okresu",
            _tabela(["Wskaźnik", "Teraz", "Poprzednio", "Zmiana"], wiersze)))

    # --- ocena ---
    if ocena_llm:
        czesci.append(sekcja("Ocena AI", _sekcja_oceny_llm(ocena_llm)))
    else:
        mocne, slabe, plan = heurystyczna_ocena(m)
        czesci.append(sekcja("Ocena (z reguł — bez AI)",
            "**Mocne strony**\n" + ("\n".join(f"- {x}" for x in mocne) or "- (brak)") +
            "\n\n**Do poprawy**\n" + ("\n".join(f"- {x}" for x in slabe) or "- (brak)") +
            "\n\n**Plan na następny okres**\n"
            + ("\n".join(f"{i}. {x}" for i, x in enumerate(plan, 1)) or "1. (brak)")))

    # --- alerty ---
    ostrzezenia = alerty(m, m_poprzedni)
    if ostrzezenia:
        czesci.append(sekcja("Alerty",
                             "\n".join(f"- ⚠️ {o['tresc']}" for o in ostrzezenia)))

    # --- do dopilnowania ---
    do_dopilnowania = [a for a in aktywnosci if a.wynik in (WYNIK_LEAD, WYNIK_SYGNAL)]
    if do_dopilnowania:
        wiersze = [
            [a.data.strftime("%d.%m %H:%M"), f"{a.budynek} / {a.lokal}".strip(" /"),
             ETYKIETY_WYNIKOW.get(a.wynik, a.wynik), a.notatka[:120]]
            for a in do_dopilnowania
        ]
        czesci.append(sekcja("Do dopilnowania — leady i sygnały",
                             _tabela(["Kiedy", "Adres", "Typ", "Notatka"], wiersze)))

    # --- wiedza rynkowa ---
    rynek = [a for a in aktywnosci if a.wynik == WYNIK_INFO_RYNKOWE]
    if rynek:
        czesci.append(sekcja("Wiedza rynkowa zebrana w okresie",
            "\n".join(f"- **{(a.budynek + ' ' + a.lokal).strip()}** — {a.notatka[:140]}"
                      for a in rynek[:15])))

    # --- pamięć agenta ---
    if pamiec:
        czesci.append(sekcja("Ustalenia z poprzednich okresów",
            "\n".join(f"- [{w['data'][:10]}] *{w['typ']}*: {w['tresc']}"
                      for w in pamiec[:8])))

    return "\n\n".join(czesci) + "\n"


def _sekcja_punktow(punkty: dict, liczniki: dict | None = None) -> str:
    """Rozbicie punktów z oficjalnej klasyfikacji sieci.

    `liczniki` to pozycje liczone, ale nieprzynoszące punktów (telefony,
    oferty, spotkania CONT). Wchodzą do tabeli zaraz za ricerką, bo razem
    opisują objętość dnia.
    """
    wiersze = [
        [p["kod"], p["nazwa"], "—" if p["brak_danych"] else int(p["ile"]),
         p["stawka"], int(p["punkty"])]
        for p in punkty["pozycje"]
    ]
    if liczniki:
        kody = [w[0] for w in wiersze]
        gdzie = kody.index("IM3") + 1 if "IM3" in kody else len(wiersze)
        for kod, dane in reversed(list(liczniki.items())):
            wiersze.insert(gdzie, [kod, dane["nazwa"], int(dane["ile"]), "—",
                                   "nie punktowane"])
    bloki = [
        (f"**Razem: {punkty['punkty_razem']:,.0f} pkt** "
         f"(aktywność {punkty['punkty_za_aktywnosc']:,.0f} "
         f"+ bonusy {punkty['punkty_bonusowe']:,.0f})").replace(",", " "),
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
    bloki = []
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
