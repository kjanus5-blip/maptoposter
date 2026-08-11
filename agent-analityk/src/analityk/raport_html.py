"""Raport pracownika jako samodzielna strona HTML.

Markdown jest dobry do archiwum i do wklejenia gdziekolwiek, ale nie nadaje
się do położenia komuś na biurku przed rozmową 1:1. Ten moduł buduje z tych
samych liczb stronę, którą da się otworzyć dwuklikiem i wydrukować albo
zapisać do PDF (Cmd+P → Zapisz jako PDF).

Zasady, które trzymają ten plik w ryzach:

* **Wszystko w jednym pliku.** Style i wykresy siedzą w środku, więc raport
  wysłany mailem wygląda u odbiorcy tak samo i działa bez internetu.
* **Zero JavaScriptu.** Wykresy to SVG liczone po stronie serwera.
* **Te same liczby, co w Markdownie.** Moduł nic nie liczy sam — dostaje
  gotowe metryki, tak jak `report.py`.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from html import escape

from . import charts
from .metrics import alerty, porownaj
from .models import (
    Activity,
    WYNIK_INFO_RYNKOWE,
    WYNIK_LEAD,
    WYNIK_SYGNAL,
)
from .org import Pracownik
from .report import ETYKIETY_WYNIKOW, NAZWY_OKRESOW, heurystyczna_ocena

STYL = """
:root {
  --tlo: #ffffff; --papier: #ffffff; --tekst: #14181f; --slaby: #5d6673;
  --ramka: #e2e6ec; --akcent: #0f6b6b; --akcent-tlo: #e6f2f1;
  --dobry: #17794a; --dobry-tlo: #e6f4ec;
  --sredni: #9a6300; --sredni-tlo: #fdf1dc;
  --zly: #b3261e; --zly-tlo: #fceceb;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 28px 30px 44px; background: var(--tlo); color: var(--tekst);
  font: 14px/1.55 -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
  max-width: 940px; margin: 0 auto;
}
h1 { font-size: 25px; margin: 0 0 2px; letter-spacing: -.5px; }
h2 {
  font-size: 13px; text-transform: uppercase; letter-spacing: .6px;
  color: var(--slaby); margin: 30px 0 10px;
  padding-bottom: 6px; border-bottom: 1px solid var(--ramka);
}
h3 { font-size: 14px; margin: 18px 0 8px; }
p { margin: 0 0 8px; }

.szapka { display: flex; gap: 20px; align-items: center; justify-content: space-between;
          border-bottom: 3px solid var(--akcent); padding-bottom: 14px; }
.szapka .meta { color: var(--slaby); font-size: 13px; }
.szapka .meta strong { color: var(--tekst); }

.kafle { display: grid; gap: 10px; grid-template-columns: repeat(4, 1fr); margin: 18px 0 4px; }
.kafel { border: 1px solid var(--ramka); border-radius: 10px; padding: 11px 13px; }
.kafel .nazwa { font-size: 11px; text-transform: uppercase; letter-spacing: .4px; color: var(--slaby); }
.kafel .wartosc { font-size: 24px; font-weight: 650; letter-spacing: -.6px; margin-top: 2px; }
.kafel .opis { font-size: 12px; color: var(--slaby); }

table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: .3px;
     color: var(--slaby); padding: 7px 9px; border-bottom: 1px solid var(--ramka); }
td { padding: 7px 9px; border-bottom: 1px solid var(--ramka); vertical-align: top; }
tr:last-child td { border-bottom: 0; }
td.l, th.l { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }

/* `inline-block` jest tu konieczne: na domyślnym `inline` przeglądarka
   ignoruje wysokość i szerokość, więc pasek byłby niewidoczny. */
.tor { display: inline-block; vertical-align: middle; width: 92px; height: 8px;
       background: #eef1f4; border-radius: 5px; overflow: hidden;
       border: 1px solid var(--ramka); margin-right: 7px; }
.tor span { display: block; height: 100%; background: var(--akcent); }
.tor.dobry span { background: var(--dobry); }
.tor.sredni span { background: var(--sredni); }
.tor.zly span { background: var(--zly); }

.znacznik { display: inline-block; padding: 1px 8px; border-radius: 20px;
            font-size: 12px; font-weight: 600; white-space: nowrap; }
.znacznik.dobry { background: var(--dobry-tlo); color: var(--dobry); }
.znacznik.sredni { background: var(--sredni-tlo); color: var(--sredni); }
.znacznik.zly { background: var(--zly-tlo); color: var(--zly); }
.znacznik.neutralny { background: var(--akcent-tlo); color: var(--akcent); }

.alert { background: var(--sredni-tlo); color: var(--sredni); border-radius: 8px;
         padding: 9px 12px; margin-bottom: 7px; font-size: 13px; }
.blok { border: 1px solid var(--ramka); border-radius: 10px; padding: 14px 16px; margin-bottom: 12px; }
.blok.wyroznik { background: var(--akcent-tlo); border-color: var(--akcent); }
.kolumny { display: grid; gap: 14px; grid-template-columns: 1fr 1fr; }
ul, ol { margin: 4px 0 0; padding-left: 20px; }
li { margin-bottom: 3px; }
.notka { color: var(--slaby); font-size: 12px; }
.stopka { margin-top: 34px; padding-top: 12px; border-top: 1px solid var(--ramka);
          color: var(--slaby); font-size: 11px; }

/* wykresy SVG — te same klasy, co w panelu */
.wykres { width: 100%; max-width: 620px; height: 130px; }
.wykres-pasek { width: 190px; height: 34px; }
.wykres-wskaznik { width: 140px; height: 78px; }
.wyk-slupek { fill: var(--akcent); opacity: .85; }
.wyk-etykieta { fill: var(--slaby); font-size: 10px; }
.wyk-wartosc { fill: var(--slaby); font-size: 9px; }
.wyk-mini { fill: var(--slaby); font-size: 9px; }
.wyk-duza { fill: var(--tekst); font-size: 24px; font-weight: 650; }
.wyk-os { stroke: var(--ramka); stroke-width: 3; stroke-linecap: round; }
.wyk-mediana { stroke: var(--slaby); stroke-width: 2; }
.wyk-punkt-dobry { fill: var(--dobry); }
.wyk-punkt-slaby { fill: var(--zly); }
.wyk-luk-tlo { fill: none; stroke: var(--ramka); stroke-width: 11; stroke-linecap: round; }
.wyk-luk-dobry, .wyk-luk-sredni, .wyk-luk-slaby { fill: none; stroke-width: 11; stroke-linecap: round; }
.wyk-luk-dobry { stroke: var(--dobry); }
.wyk-luk-sredni { stroke: var(--sredni); }
.wyk-luk-slaby { stroke: var(--zly); }
.udzialy { display: flex; flex-direction: column; gap: 6px; }
.udzial-wiersz { display: grid; grid-template-columns: minmax(150px, 1.3fr) 3fr auto;
                 gap: 10px; align-items: center; font-size: 12.5px; }
.udzial-tor { background: #eef1f4; border-radius: 5px; height: 8px; overflow: hidden;
              border: 1px solid var(--ramka); }
.udzial-wypelnienie { display: block; height: 100%; background: var(--akcent); }
.udzial-liczba { color: var(--slaby); font-variant-numeric: tabular-nums; font-size: 12px; }
.udzial-etykieta { color: var(--slaby); }
.pusto { color: var(--slaby); }

@media print {
  body { padding: 0; max-width: none; font-size: 12px; }
  h2 { margin-top: 20px; }
  .blok, .kafel, table, .szapka { break-inside: avoid; }
  h2 { break-after: avoid; }
}
@page { margin: 14mm; }
"""


def _e(x) -> str:
    return escape(str(x if x is not None else ""))


def _klasa_progu(wartosc: float | None, dobry: float, sredni: float) -> str:
    if wartosc is None:
        return "neutralny"
    if wartosc >= dobry:
        return "dobry"
    if wartosc >= sredni:
        return "sredni"
    return "zly"


def _tor(proc: float | None, dobry: float = 90, sredni: float = 70) -> str:
    """Pasek postępu — czytelniejszy niż sama liczba przy realizacji normy."""
    if proc is None:
        return '<span class="notka">—</span>'
    return (f'<span class="tor {_klasa_progu(proc, dobry, sredni)}">'
            f'<span style="width:{min(proc, 100):.0f}%"></span></span>')


def _kafel(nazwa: str, wartosc, opis: str = "") -> str:
    return (f'<div class="kafel"><div class="nazwa">{_e(nazwa)}</div>'
            f'<div class="wartosc">{_e(wartosc)}</div>'
            + (f'<div class="opis">{_e(opis)}</div>' if opis else "")
            + "</div>")


def _tabela(naglowki: list[str], wiersze: list[list], liczbowe: set[int] | None = None) -> str:
    liczbowe = liczbowe or set()
    czesci = ["<table><thead><tr>"]
    for i, h in enumerate(naglowki):
        czesci.append(f'<th class="{"l" if i in liczbowe else ""}">{_e(h)}</th>')
    czesci.append("</tr></thead><tbody>")
    for w in wiersze:
        czesci.append("<tr>")
        for i, c in enumerate(w):
            # wartości oznaczone przez `_html()` wstawiamy bez escape'owania
            tresc = c[3:] if isinstance(c, str) and c.startswith("<!>") else _e(c)
            czesci.append(f'<td class="{"l" if i in liczbowe else ""}">{tresc}</td>')
        czesci.append("</tr>")
    czesci.append("</tbody></table>")
    return "".join(czesci)


def _html(surowy: str) -> str:
    """Oznacza wartość jako gotowy HTML, którego nie należy escape'ować."""
    return "<!>" + surowy


def _szereg_dzienny(aktywnosci: list[Activity]) -> list[tuple[str, int]]:
    licznik = Counter(a.dzien for a in aktywnosci)
    return [(d[8:10], n) for d, n in sorted(licznik.items())]


def zbuduj_raport_html(
    profil: Pracownik,
    typ_okresu: str,
    klucz_okresu_: str,
    m: dict,
    aktywnosci: list[Activity],
    m_poprzedni: dict | None = None,
    ocena_llm: dict | None = None,
    pamiec: list[dict] | None = None,
    grupy: list[dict] | None = None,
    etykieta_okresu_: str = "",
) -> str:
    """Składa kompletną, samodzielną stronę HTML z raportem."""
    tytul = f"Raport {NAZWY_OKRESOW[typ_okresu]} — {profil.imie_nazwisko}"
    okres_opis = etykieta_okresu_ or klucz_okresu_

    szapka = (
        '<div class="szapka"><div>'
        f"<h1>{_e(profil.imie_nazwisko)}</h1>"
        f'<div class="meta">Raport {_e(NAZWY_OKRESOW[typ_okresu])} · '
        f"<strong>{_e(okres_opis)}</strong><br>"
        f"{_e(profil.nazwa_roli)} · {_e(profil.biuro_nazwa or 'biuro nieprzypisane')}"
        + (f" · staż {_e(profil.staz_miesiace)} mies." if profil.staz_miesiace else "")
        + "</div></div>"
        + (f"<div>{charts.wskaznik(m.get('indeks_jakosci', 0), etykieta='indeks jakości')}</div>"
           if not m.get("pusty") else "")
        + "</div>"
    )

    if m.get("pusty"):
        tresc = szapka + '<p class="alert">Brak jakiejkolwiek aktywności w tym okresie.</p>'
        return _strona(tytul, tresc)

    czesci = [szapka, _sekcja_kafli(m), _sekcja_ilosci(m, aktywnosci),
              _sekcja_jakosci(m), _sekcja_wynikow(m)]

    if m.get("punkty"):
        czesci.append(_sekcja_punktow(m["punkty"]))
    if grupy:
        czesci.append(_sekcja_grup(grupy))
    if m_poprzedni and not m_poprzedni.get("pusty"):
        czesci.append(_sekcja_trendu(m, m_poprzedni))

    czesci.append(_sekcja_oceny(m, ocena_llm))
    czesci.append(_sekcja_alertow(m, m_poprzedni))
    czesci.append(_sekcja_dopilnowania(aktywnosci))
    czesci.append(_sekcja_rynku(aktywnosci))
    czesci.append(_sekcja_pamieci(pamiec))
    return _strona(tytul, "".join(c for c in czesci if c))


def _strona(tytul: str, tresc: str) -> str:
    stopka = (
        '<div class="stopka">'
        f"Wygenerowano {datetime.now().strftime('%d.%m.%Y o %H:%M')} przez Agenta Analityka. "
        "Liczby pochodzą wprost z eksportu CRM. Ocena opisowa jest materiałem "
        "pomocniczym dla przełożonego — nie stanowi automatycznej decyzji kadrowej "
        "i wymaga akceptacji człowieka przed przekazaniem pracownikowi."
        "</div>"
    )
    return (
        "<!doctype html>\n<html lang=\"pl\">\n<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_e(tytul)}</title>\n<style>{STYL}</style>\n</head>\n<body>\n"
        f"{tresc}\n{stopka}\n</body>\n</html>\n"
    )


# --- sekcje ---------------------------------------------------------------

def _sekcja_kafli(m: dict) -> str:
    realizacja = m.get("realizacja_normy_proc")
    punkty = m.get("punkty_razem")
    kafle = [
        _kafel("Aktywności", m["liczba_aktywnosci"],
               f"średnio {m['srednio_dziennie']}/dzień"),
        _kafel("Realizacja normy",
               f"{realizacja}%" if realizacja is not None else "—",
               f"norma {m.get('norma_proporcjonalna', m.get('norma', {}).get('aktywnosci', '—'))}"),
        _kafel("Leady / sygnały", f"{m['leady']} / {m['sygnaly']}",
               f"konwersja {m['konwersja_na_lead_proc']}%"),
        _kafel("Punkty", f"{punkty:,.0f}".replace(",", " ") if punkty is not None else "—",
               "klasyfikacja sieci"),
    ]
    return '<div class="kafle">' + "".join(kafle) + "</div>"


def _sekcja_ilosci(m: dict, aktywnosci: list[Activity]) -> str:
    norma = m.get("norma", {})
    realizacja = m.get("realizacja_normy_proc")
    # Procent liczy się z normy proporcjonalnej do dni, które już minęły —
    # gdyby w kolumnie stała norma za cały okres, liczby by się nie zgadzały.
    norma_teraz = m.get("norma_proporcjonalna", norma.get("aktywnosci"))
    opis_normy = str(norma_teraz if norma_teraz is not None else "—")
    if m.get("norma_proporcjonalna") and norma.get("aktywnosci") != norma_teraz:
        opis_normy = _html(f'{norma_teraz} <span class="notka">z {norma["aktywnosci"]} '
                           f'za cały okres</span>')
    wiersze = [
        ["Aktywności", m["liczba_aktywnosci"], opis_normy,
         _html(f'{_tor(realizacja)} '
               f'<span class="znacznik {_klasa_progu(realizacja, 90, 70)}">'
               f'{realizacja if realizacja is not None else "—"}%</span>')],
        ["Średnio dziennie", m["srednio_dziennie"], "—", ""],
        ["Dni z aktywnością", m["dni_z_aktywnoscia"],
         m.get("dni_robocze_uplynelo", "—"),
         _html(f'<span class="notka">{m.get("dni_bez_aktywnosci", 0)} dni pustych</span>')],
        ["Kontakt bezpośredni", m["kanaly"].get("bezposredni", 0), "—",
         _html(f'<span class="notka">{m["udzial_bezposrednich_proc"]}% wszystkich</span>')],
        ["Telefon", m["kanaly"].get("telefon", 0), "—", ""],
        ["Budynki / lokale", f"{m['unikalne_budynki']} / {m['unikalne_lokale']}", "—", ""],
    ]
    return (
        "<h2>Ilość pracy</h2>"
        + _tabela(["Wskaźnik", "Wartość", "Norma", "Realizacja"], wiersze, liczbowe={1, 2})
        + "<h3>Aktywność dzień po dniu</h3>"
        + charts.slupki(_szereg_dzienny(aktywnosci))
        + "<h3>Rozkład godzinowy</h3>"
        + charts.slupki([(str(g), n) for g, n in (m.get("rozklad_godzinowy") or {}).items()])
        + f'<p class="notka">Praca w godzinach 16–20: '
          f'<strong>{m["praca_w_zlotych_godzinach_proc"]}%</strong> kontaktów · '
          f'dzień od {m["pierwsza_aktywnosc"]} do {m["ostatnia_aktywnosc"]} '
          f'(średnio {m["rozpietosc_dnia_h"]} h, tempo {m["aktywnosci_na_godzine"]} akt./h)</p>'
    )


def _sekcja_jakosci(m: dict) -> str:
    wiersze = [
        ["Konwersja na lead/sygnał", f"{m['konwersja_na_lead_proc']}%",
         _html(_tor(m["konwersja_na_lead_proc"], 8, 4)), "ze wszystkich kontaktów"],
        ["Leady", m["leady"], "", "deklaracja chęci sprzedaży/najmu"],
        ["Sygnały na przyszłość", m["sygnaly"], "", "„przemyśli”, „może za rok”"],
        ["Informacje rynkowe", m["info_rynkowe"], "", "wiedza o terenie"],
        ["Kontaktów na 1 lead", m["kontaktow_na_lead"] or "—", "",
         "koszt pozyskania w aktywnościach"],
        ["Twarde odmowy", m["odmowy_twarde"], "",
         f"{m['wskaznik_odmow_twardych_proc']}% kontaktów"],
        ["Notatki z treścią", f"{m['notatki_merytoryczne_proc']}%",
         _html(_tor(m["notatki_merytoryczne_proc"], 80, 60)),
         f"średnio {m['srednia_dlugosc_notatki']} znaków"],
        ["Follow-up", f"{m['follow_up_proc']}%",
         _html(_tor(m["follow_up_proc"], 20, 10)),
         f"materiał: {m['material_zostawiony']}, kolejny krok: {m['kolejny_krok_zaplanowany']}"],
    ]
    return ("<h2>Jakość pracy</h2>"
            + _tabela(["Wskaźnik", "Wartość", "", "Komentarz"], wiersze, liczbowe={1}))


def _sekcja_wynikow(m: dict) -> str:
    dane = [(ETYKIETY_WYNIKOW.get(w, w), n) for w, n in (m.get("wyniki") or {}).items()]
    blok = ("<h2>Co wyszło z kontaktów</h2>"
            + charts.paski_udzialow(dane, m["liczba_aktywnosci"]))
    if m.get("top_budynki"):
        wiersze = [[b, n] for b, n in list(m["top_budynki"].items())[:10]]
        blok += "<h3>Najczęściej odwiedzane budynki</h3>" + _tabela(
            ["Budynek", "Kontakty"], wiersze, liczbowe={1})
    return blok


def _sekcja_punktow(punkty: dict) -> str:
    wiersze = [
        [p["kod"], p["nazwa"], "—" if p["brak_danych"] else int(p["ile"]),
         p["stawka"], f"{int(p['punkty']):,}".replace(",", " ")]
        for p in punkty["pozycje"]
    ]
    razem = f"{punkty['punkty_razem']:,.0f}".replace(",", " ")
    aktywnosc = f"{punkty['punkty_za_aktywnosc']:,.0f}".replace(",", " ")
    bonusy = f"{punkty['punkty_bonusowe']:,.0f}".replace(",", " ")
    blok = (
        "<h2>Klasyfikacja punktowa</h2>"
        f'<div class="blok wyroznik"><strong style="font-size:20px">{razem} pkt</strong> '
        f'<span class="notka">= {aktywnosc} za aktywność + {bonusy} z bonusów</span></div>'
        + _tabela(["Kod", "Wskaźnik", "Ile", "Stawka", "Punkty"], wiersze, liczbowe={2, 3, 4})
    )
    if punkty["kompletnosc_proc"] < 100:
        blok += (
            f'<p class="alert">Uzupełnionych wskaźników: {punkty["kompletnosc_proc"]}%. '
            f'Brakuje: {_e(", ".join(punkty["wskazniki_bez_danych"]))}. '
            "Brakujące liczą się jako zero, więc wynik jest zaniżony.</p>"
        )
    wiersze_bonusow = [
        [b["nazwa"],
         "brak danych" if b.get("brak_danych") else
         (f"{b['udzial_proc']}%" if b["udzial_proc"] is not None else "—"),
         f">{b['prog_proc']}%" if b.get("prog_proc") else "—",
         _html(f'<span class="znacznik {"dobry" if b["punkty"] else "neutralny"}">'
               f'{int(b["punkty"]):,}'.replace(",", " ") + " pkt</span>")]
        for b in punkty["bonusy"]
    ]
    if wiersze_bonusow:
        blok += "<h3>Bonusy</h3>" + _tabela(
            ["Bonus", "Wynik", "Próg", "Punkty"], wiersze_bonusow, liczbowe={1, 2, 3})
    return blok


def _sekcja_grup(grupy: list[dict]) -> str:
    bloki = ["<h2>Na tle innych na tym samym stanowisku</h2>"]
    for g in grupy:
        naglowek = f'<h3>{_e(g["nazwa"])} <span class="notka">· osób: {g["liczebnosc"]}</span></h3>'
        if not g["wiarygodne"]:
            naglowek += ('<p class="alert">Grupa za mała na wnioski — '
                         "traktuj wyłącznie poglądowo.</p>")
        wiersze = [
            [d["etykieta"], d["moja"], d["mediana_grupy"],
             f"{'+' if d['delta'] > 0 else ''}{d['delta']}",
             _html(charts.pasek_pozycji(d["moja"], d["mediana_grupy"], d["min"],
                                        d["max"], d["wyzej_lepiej"])),
             _html(f'<span class="znacznik '
                   f'{ {"powyżej grupy": "dobry", "w normie grupy": "neutralny"}.get(d["ocena"], "sredni") }">'
                   f'{_e(d["ocena"])}</span>')]
            for d in g["pola"].values()
        ]
        bloki.append(naglowek + _tabela(
            ["Wskaźnik", "Ta osoba", "Mediana grupy", "Różnica", "Pozycja w grupie", "Ocena"],
            wiersze, liczbowe={1, 2, 3}))
    return "".join(bloki)


def _sekcja_trendu(m: dict, m_poprzedni: dict) -> str:
    wiersze = []
    for pole, d in porownaj(m, m_poprzedni).items():
        if d["zmiana"] > 0:
            znacznik = f'<span class="znacznik dobry">▲ +{d["zmiana"]}</span>'
        elif d["zmiana"] < 0:
            znacznik = f'<span class="znacznik zly">▼ {d["zmiana"]}</span>'
        else:
            znacznik = '<span class="znacznik neutralny">bez zmian</span>'
        wiersze.append([pole, d["teraz"], d["poprzednio"], _html(znacznik)])
    return ("<h2>Trend względem poprzedniego okresu</h2>"
            + _tabela(["Wskaźnik", "Teraz", "Poprzednio", "Zmiana"], wiersze, liczbowe={1, 2}))


def _sekcja_oceny(m: dict, ocena_llm: dict | None) -> str:
    def lista(pozycje, numerowana: bool = False) -> str:
        if not pozycje:
            return '<p class="notka">(brak)</p>'
        znacznik = "ol" if numerowana else "ul"
        return (f"<{znacznik}>" + "".join(f"<li>{_e(x)}</li>" for x in pozycje)
                + f"</{znacznik}>")

    if ocena_llm:
        naglowek = "<h2>Ocena</h2>"
        blok = f'<div class="blok wyroznik">{_e(ocena_llm.get("podsumowanie", ""))}</div>'
        if ocena_llm.get("na_tle_grupy"):
            blok += f'<p><strong>Na tle grupy:</strong> {_e(ocena_llm["na_tle_grupy"])}</p>'
        blok += (
            '<div class="kolumny">'
            f'<div class="blok"><h3>Mocne strony</h3>{lista(ocena_llm.get("mocne_strony"))}</div>'
            f'<div class="blok"><h3>Do poprawy</h3>{lista(ocena_llm.get("do_poprawy"))}</div>'
            "</div>"
            f'<div class="blok"><h3>Plan na następny okres</h3>'
            f'{lista(ocena_llm.get("plan_na_nastepny_okres"), numerowana=True)}</div>'
            '<div class="kolumny">'
            f'<div class="blok"><h3>Pytania na 1:1</h3>{lista(ocena_llm.get("pytania_na_1n1"))}</div>'
            f'<div class="blok"><h3>Ryzyka</h3>{lista(ocena_llm.get("ryzyka"))}</div>'
            "</div>"
        )
        return naglowek + blok

    mocne, slabe, plan = heurystyczna_ocena(m)
    return (
        "<h2>Ocena (bez AI — z reguł)</h2>"
        '<div class="kolumny">'
        f'<div class="blok"><h3>Mocne strony</h3>{lista(mocne)}</div>'
        f'<div class="blok"><h3>Do poprawy</h3>{lista(slabe)}</div>'
        "</div>"
        f'<div class="blok"><h3>Plan na następny okres</h3>{lista(plan, numerowana=True)}</div>'
    )


def _sekcja_alertow(m: dict, m_poprzedni: dict | None) -> str:
    ostrzezenia = alerty(m, m_poprzedni)
    if not ostrzezenia:
        return ""
    return ("<h2>Alerty</h2>"
            + "".join(f'<div class="alert">{_e(o["tresc"])}</div>' for o in ostrzezenia))


def _sekcja_dopilnowania(aktywnosci: list[Activity]) -> str:
    lista = [a for a in aktywnosci if a.wynik in (WYNIK_LEAD, WYNIK_SYGNAL)]
    if not lista:
        return ""
    wiersze = [
        [a.data.strftime("%d.%m %H:%M"), f"{a.budynek} / {a.lokal}".strip(" /"),
         _html(f'<span class="znacznik {"dobry" if a.wynik == WYNIK_LEAD else "sredni"}">'
               f'{_e(ETYKIETY_WYNIKOW.get(a.wynik, a.wynik))}</span>'),
         a.notatka[:160]]
        for a in lista
    ]
    return ("<h2>Do dopilnowania — leady i sygnały</h2>"
            + _tabela(["Kiedy", "Adres", "Typ", "Notatka"], wiersze))


def _sekcja_rynku(aktywnosci: list[Activity]) -> str:
    rynek = [a for a in aktywnosci if a.wynik == WYNIK_INFO_RYNKOWE]
    if not rynek:
        return ""
    return ("<h2>Wiedza rynkowa zebrana w okresie</h2><ul>"
            + "".join(f"<li><strong>{_e((a.budynek + ' ' + a.lokal).strip())}</strong> — "
                      f"{_e(a.notatka[:170])}</li>" for a in rynek[:15])
            + "</ul>")


def _sekcja_pamieci(pamiec: list[dict] | None) -> str:
    if not pamiec:
        return ""
    return ("<h2>Ustalenia z poprzednich okresów</h2><ul>"
            + "".join(f"<li><span class=\"notka\">[{_e(w['data'][:10])}] {_e(w['typ'])}</span> — "
                      f"{_e(w['tresc'])}</li>" for w in pamiec[:8])
            + "</ul>")


__all__ = ["zbuduj_raport_html", "STYL"]
