"""Wykresy jako czysty SVG generowany po stronie serwera.

Bez JavaScriptu i bez bibliotek z CDN — panel ma działać w biurze bez
internetu, ładować się natychmiast i poprawnie wychodzić na wydruku.
Kolory pochodzą ze zmiennych CSS, więc wykresy same dostosowują się do
jasnego i ciemnego motywu.
"""

from __future__ import annotations

from html import escape


def _txt(x: float, y: float, tresc: str, klasa: str = "wyk-etykieta",
         kotwica: str = "middle") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" class="{klasa}" '
            f'text-anchor="{kotwica}">{escape(str(tresc))}</text>')


def slupki(
    dane: list[tuple[str, float]],
    wysokosc: int = 130,
    szerokosc: int = 520,
    jednostka: str = "",
) -> str:
    """Pionowe słupki — rozkład godzinowy, aktywność dzień po dniu."""
    if not dane:
        return '<p class="pusto">Brak danych do wykresu.</p>'

    margines_dol, margines_gora = 22, 14
    pole = wysokosc - margines_dol - margines_gora
    maks = max((w for _, w in dane), default=0) or 1
    krok = szerokosc / len(dane)
    szer_slupka = min(krok * 0.62, 46)

    czesci = [
        f'<svg viewBox="0 0 {szerokosc} {wysokosc}" class="wykres" '
        f'role="img" preserveAspectRatio="none">'
    ]
    for i, (etykieta, wartosc) in enumerate(dane):
        h = pole * (wartosc / maks)
        x = i * krok + (krok - szer_slupka) / 2
        y = margines_gora + pole - h
        czesci.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{szer_slupka:.1f}" '
            f'height="{max(h, 1):.1f}" rx="3" class="wyk-slupek"/>'
        )
        if wartosc:
            czesci.append(_txt(x + szer_slupka / 2, y - 3, f"{wartosc:g}{jednostka}",
                               "wyk-wartosc"))
        czesci.append(_txt(x + szer_slupka / 2, wysokosc - 6, etykieta))
    czesci.append("</svg>")
    return "".join(czesci)


def pasek_pozycji(moja: float, mediana: float, minimum: float, maksimum: float,
                  wyzej_lepiej: bool = True) -> str:
    """Pozycja pracownika na tle rozrzutu grupy: min ——[mediana]—— max."""
    szerokosc, wysokosc = 210, 34
    rozpietosc = (maksimum - minimum) or 1

    def na_x(w: float) -> float:
        return 6 + (szerokosc - 12) * (w - minimum) / rozpietosc

    x_moja, x_med = na_x(moja), na_x(mediana)
    lepiej = (moja >= mediana) if wyzej_lepiej else (moja <= mediana)
    klasa = "wyk-punkt-dobry" if lepiej else "wyk-punkt-slaby"

    return (
        f'<svg viewBox="0 0 {szerokosc} {wysokosc}" class="wykres-pasek" role="img">'
        f'<line x1="6" y1="17" x2="{szerokosc - 6}" y2="17" class="wyk-os"/>'
        f'<line x1="{x_med:.1f}" y1="7" x2="{x_med:.1f}" y2="27" class="wyk-mediana"/>'
        f'<circle cx="{x_moja:.1f}" cy="17" r="6" class="{klasa}"/>'
        f'{_txt(6, 32, f"{minimum:g}", "wyk-mini", "start")}'
        f'{_txt(szerokosc - 6, 32, f"{maksimum:g}", "wyk-mini", "end")}'
        f"</svg>"
    )


def wskaznik(wartosc: int, maks: int = 100, etykieta: str = "") -> str:
    """Półkolisty wskaźnik — indeks jakości pracy."""
    promien, srodek_x, srodek_y = 52, 70, 62
    udzial = max(0.0, min(1.0, wartosc / maks))
    dlugosc_luku = 3.14159 * promien

    if udzial >= 0.75:
        klasa = "wyk-luk-dobry"
    elif udzial >= 0.5:
        klasa = "wyk-luk-sredni"
    else:
        klasa = "wyk-luk-slaby"

    luk = (f"M {srodek_x - promien} {srodek_y} "
           f"A {promien} {promien} 0 0 1 {srodek_x + promien} {srodek_y}")
    return (
        f'<svg viewBox="0 0 140 78" class="wykres-wskaznik" role="img">'
        f'<path d="{luk}" class="wyk-luk-tlo"/>'
        f'<path d="{luk}" class="{klasa}" '
        f'stroke-dasharray="{dlugosc_luku * udzial:.1f} {dlugosc_luku:.1f}"/>'
        f'{_txt(srodek_x, srodek_y - 6, wartosc, "wyk-duza")}'
        f'{_txt(srodek_x, srodek_y + 12, etykieta, "wyk-mini")}'
        f"</svg>"
    )


def paski_udzialow(dane: list[tuple[str, int]], suma: int | None = None) -> str:
    """Poziome paski — struktura wyników kontaktów."""
    if not dane:
        return '<p class="pusto">Brak danych.</p>'
    suma = suma or sum(w for _, w in dane) or 1
    wiersze = []
    for etykieta, wartosc in dane:
        proc = 100 * wartosc / suma
        wiersze.append(
            f'<div class="udzial-wiersz">'
            f'<span class="udzial-etykieta">{escape(etykieta)}</span>'
            f'<span class="udzial-tor"><span class="udzial-wypelnienie" '
            f'style="width:{proc:.1f}%"></span></span>'
            f'<span class="udzial-liczba">{wartosc} · {proc:.0f}%</span>'
            f"</div>"
        )
    return '<div class="udzialy">' + "".join(wiersze) + "</div>"
