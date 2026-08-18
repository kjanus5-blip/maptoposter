#!/usr/bin/env python3
"""Ustalenie właściciela lub spadkobierców niezamieszkanej nieruchomości.

Narzędzie odpytuje wyłącznie otwarte, publiczne rejestry (Nominatim, ULDK GUGiK,
KRS, Biała Lista VAT, opcjonalnie CEIDG), identyfikuje działkę ewidencyjną,
a następnie generuje raport ze ścieżką postępowania i gotowe do uzupełnienia
pisma urzędowe.

Czego narzędzie NIE robi i robić nie będzie: nie omija CAPTCHA w przeglądarce
ksiąg wieczystych ani w Rejestrze Spadkowym, nie odpytuje rejestru PESEL
(prawnie niedostępny bez wykazania interesu prawnego) i nie agreguje danych
osobowych osób prywatnych. Te kroki opisane są w raporcie jako czynności
do wykonania ręcznie.

Przykład:
    python ustal_wlasciciela.py \
        --adres "ul. Długa 12, Kraków" \
        --wnioskodawca "Jan Kowalski" \
        --kontakt "jan@example.com, tel. 600 000 000" \
        --cel "zakupu lokalu"
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

import zrodla

KATALOG = pathlib.Path(__file__).resolve().parent
WZORY = KATALOG / "wzory"

LINKI = {
    "ekw": "https://przegladarka-ekw.ms.gov.pl/",
    "rejestr_spadkowy": "https://rejestry-notarialne.pl/37",
    "nort": "https://rejestry-notarialne.pl/35",
    "geoportal": "https://mapy.geoportal.gov.pl/",
    "sad": "https://www.gov.pl/web/sprawiedliwosc/znajdz-wybrany-sad-powszechny",
    "krs_wyszukiwarka": "https://wyszukiwarka-krs.ms.gov.pl/",
    "ceidg": "https://aplikacja.ceidg.gov.pl/ceidg/ceidg.public.ui/search.aspx",
    "msig": "https://ems.ms.gov.pl/msig/przegladaniemonitorow",
}


class _Braki(dict):
    """Podstawia '.........' zamiast rzucać KeyError na brakującym polu wzoru."""

    def __missing__(self, klucz: str) -> str:
        return "........................"


def wypelnij_wzory(pola: dict, katalog_wyjscia: pathlib.Path) -> list[pathlib.Path]:
    katalog_wyjscia.mkdir(parents=True, exist_ok=True)
    zapisane = []
    for wzor in sorted(WZORY.glob("*.md")):
        tresc = wzor.read_text(encoding="utf-8").format_map(_Braki(pola))
        cel = katalog_wyjscia / wzor.name
        cel.write_text(tresc, encoding="utf-8")
        zapisane.append(cel)
    return zapisane


def _linia(wynik: dict, etykieta: str) -> str:
    if wynik["status"] == "ok":
        return f"- **{etykieta}**: znaleziono"
    return f"- **{etykieta}**: {wynik.get('opis', 'brak wyniku')}"


def zbuduj_raport(args, geo: dict, dzialka: dict, rejestry: dict, pisma: list) -> str:
    dzis = dt.date.today().isoformat()
    w = [f"# Ustalenie właściciela / spadkobierców\n", f"Raport wygenerowany: {dzis}\n"]

    w.append("## 1. Dane wejściowe\n")
    w.append(f"- Adres nieruchomości: **{args.adres}**")
    if args.imie or args.nazwisko:
        w.append(f"- Domniemany właściciel: **{(args.imie or '').strip()} {(args.nazwisko or '').strip()}**")
    w.append(f"- Cel kontaktu: {args.cel}\n")

    w.append("## 2. Identyfikacja nieruchomości\n")
    if geo["status"] == "ok":
        g = geo["dane"]
        w.append(f"- Rozpoznany adres: {g['opis']}")
        w.append(f"- Współrzędne: `{g['lat']:.6f}, {g['lon']:.6f}`")
        w.append(f"- Podgląd: {LINKI['geoportal']}?lat={g['lat']}&lon={g['lon']}")
    else:
        w.append(f"- Geokodowanie nieudane: {geo.get('opis')}")
        w.append("- Wpisz adres dokładniej (ulica, numer, miejscowość) lub podaj `--wspolrzedne LAT,LON`.")
    w.append("")

    if dzialka["status"] == "ok":
        d = dzialka["dane"]
        w.append(f"- **Identyfikator działki: `{d.get('id','?')}`**")
        w.append(f"- Obręb ewidencyjny: {d.get('region','?')}")
        w.append(f"- Gmina: {d.get('commune','?')}")
        w.append(f"- Powiat: {d.get('county','?')}")
        w.append(f"- Województwo: {d.get('voivodeship','?')}")
        w.append(
            "\n> Uwaga: identyfikator dotyczy **działki (gruntu)**, na której stoi budynek. "
            "Samodzielny lokal mieszkalny ma zwykle **własną, odrębną księgę wieczystą** - "
            "numer działki jej nie zastąpi, ale jest niezbędny do wniosków poniżej."
        )
    else:
        w.append(f"- Nie ustalono działki: {dzialka.get('opis')}")
    w.append("")

    if rejestry:
        w.append("## 3. Rejestry odpytane automatycznie\n")
        for etykieta, wynik in rejestry.items():
            w.append(_linia(wynik, etykieta))
        w.append("")

    w.append("## 4. Ścieżka postępowania - kolejność ma znaczenie\n")
    w.append(
        "### Krok 1 - zarządca budynku (najtańszy i najskuteczniejszy)\n"
        "Wspólnota mieszkaniowa, spółdzielnia lub administrator **zna właściciela** "
        "i zwykle zna numer księgi wieczystej lokalu - musi je mieć do rozliczania zaliczek. "
        "Danych osobowych Ci nie wyda, ale może **przekazać Twoje pismo** właścicielowi "
        "lub spadkobiercom. Wygenerowane pismo: `pismo_zarzadca.md`.\n"
        "Jeżeli od lat nikt nie płaci zaliczek, wspólnota jest wierzycielem i sama ma "
        "interes prawny, by ustalić spadkobierców - warto działać razem z nią.\n"
    )
    w.append(
        f"### Krok 2 - numer księgi wieczystej, potem darmowy podgląd\n"
        f"To jest wąskie gardło całej sprawy. Publiczny Geoportal i ULDK **nie udostępniają "
        f"numeru KW**. Numer zdobywa się przez:\n"
        f"- zapytanie u zarządcy / w spółdzielni (najszybciej),\n"
        f"- wniosek do wydziału ksiąg wieczystych sądu rejonowego - wzór `wniosek_kw_sad.md`, "
        f"właściwy sąd znajdziesz tu: {LINKI['sad']},\n"
        f"- wypis z ewidencji gruntów i budynków - wzór `wniosek_egib.md`,\n"
        f"- akt notarialny, jeśli masz do niego dostęp z innego tytułu.\n\n"
        f"Mając numer KW, **Dział II** poda właściciela za darmo: {LINKI['ekw']}\n"
    )
    w.append(
        f"### Krok 3 - sprawdź, czy właściciel żyje i czy było postępowanie spadkowe\n"
        f"- **Rejestr Spadkowy** (bezpłatny, formularz z CAPTCHA - wyłącznie ręcznie): "
        f"{LINKI['rejestr_spadkowy']}\n"
        f"  Pokaże, czy sporządzono akt poświadczenia dziedziczenia lub wydano postanowienie "
        f"o stwierdzeniu nabycia spadku, oraz **u którego notariusza / w którym sądzie** "
        f"szukać akt. To najkrótsza droga do spadkobierców.\n"
        f"- **Notarialny Rejestr Testamentów (NORT)**: {LINKI['nort']}\n"
        f"- Wyszukiwarki grobów prowadzone przez gminy i zarządców cmentarzy (Grobonet, "
        f"mogily.pl, wyszukiwarki miejskie) - potwierdzają datę zgonu i często pokazują "
        f"nazwiska rodziny z grobu rodzinnego.\n"
        f"- Monitor Sądowy i Gospodarczy - ogłoszenia o wezwaniu spadkobierców: "
        f"{LINKI['msig']}\n"
    )
    w.append(
        "### Krok 4 - jeżeli spadkobierców nie da się ustalić\n"
        "Zgłoś sprawę gminie - wzór `zgloszenie_gmina.md`. Gmina ma własny interes prawny "
        "(niezapłacony podatek od nieruchomości, stan techniczny budynku) i może wystąpić "
        "do sądu o **kuratora spadku nieobjętego** (art. 666 § 1 k.p.c.). Obowiązkiem "
        "kuratora jest ustalenie kręgu spadkobierców, a w braku innych spadkobierców "
        "spadek przypada gminie (art. 935 k.c.) - wtedy masz z kim rozmawiać.\n\n"
        "Jeżeli sam jesteś wierzycielem (np. wspólnota, dostawca mediów), możesz złożyć "
        "**własny wniosek o stwierdzenie nabycia spadku** - wierzycielowi przysługuje "
        "w tym interes prawny (art. 1025 § 1 k.c.).\n"
    )

    w.append("## 5. Granice prawne - warto znać przed pierwszym pismem\n")
    w.append(
        "- **PESEL i adres zameldowania**: rejestr PESEL nie jest publiczny. Dane udostępnia "
        "się na wniosek po wykazaniu interesu prawnego (art. 45-46 ustawy o ewidencji "
        "ludności) - zwykle wymaga tytułu wykonawczego lub innego dokumentu, nie samego "
        "zainteresowania zakupem.\n"
        "- **Wypis z EGiB z danymi właściciela**: tylko przy interesie prawnym "
        "(art. 24 ust. 5 Prawa geodezyjnego i kartograficznego). Zamiar nabycia "
        "nieruchomości co do zasady nie wystarcza. Wypis bez danych właściciela dostaniesz "
        "zawsze.\n"
        "- **Księgi wieczyste są jawne** (art. 2 ustawy o księgach wieczystych i hipotece) - "
        "mając numer KW, wgląd jest legalny i darmowy. Automatyczne odpytywanie przeglądarki "
        "EKW jest jednak zakazane regulaminem, dlatego to narzędzie tego nie robi.\n"
        "- **Nie kontaktuj się z rodziną z pominięciem właściciela** i nie zbieraj danych "
        "„na zapas\" - do celu, który masz, wystarczy jeden kanał kontaktu.\n"
    )

    if pisma:
        w.append("## 6. Wygenerowane pisma\n")
        for p in pisma:
            w.append(f"- `{p.name}` - uzupełnij pola oznaczone kropkami przed wysłaniem")
        w.append("")

    return "\n".join(w)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Ustalenie właściciela lub spadkobierców niezamieszkanej nieruchomości.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--adres", required=True, help="adres nieruchomości, np. 'ul. Długa 12, Kraków'")
    p.add_argument("--wspolrzedne", help="LAT,LON - pomija geokodowanie")
    p.add_argument("--imie", default="", help="imię domniemanego właściciela (opcjonalnie)")
    p.add_argument("--nazwisko", default="", help="nazwisko domniemanego właściciela (opcjonalnie)")
    p.add_argument("--nip", help="NIP do sprawdzenia w Białej Liście VAT")
    p.add_argument("--krs", help="numer KRS do pobrania odpisu aktualnego")
    p.add_argument("--wnioskodawca", default="", help="Twoje imię i nazwisko - do pism")
    p.add_argument("--kontakt", default="", help="Twój adres / e-mail / telefon - do pism")
    p.add_argument("--cel", default="nabycia nieruchomości", help="cel kontaktu, wpisywany do pism")
    p.add_argument(
        "--interes-prawny",
        default="",
        help="uzasadnienie interesu prawnego wpisywane do wniosków urzędowych",
    )
    p.add_argument("--wyjscie", default="wynik", help="katalog na raport i pisma (domyślnie: wynik)")
    p.add_argument("--json", action="store_true", help="wypisz surowe odpowiedzi rejestrów na stdout")
    args = p.parse_args(argv)

    if args.wspolrzedne:
        try:
            lat_s, lon_s = args.wspolrzedne.split(",")
            geo = {
                "status": "ok",
                "dane": {
                    "lat": float(lat_s),
                    "lon": float(lon_s),
                    "opis": args.adres,
                    "typ": "podane ręcznie",
                },
            }
        except ValueError:
            print("Błąd: --wspolrzedne oczekuje formatu LAT,LON", file=sys.stderr)
            return 2
    else:
        print(f"[1/3] Geokodowanie adresu: {args.adres}", file=sys.stderr)
        geo = zrodla.geokoduj(args.adres)

    if geo["status"] == "ok":
        print("[2/3] Odpytywanie ULDK (GUGiK) o działkę ewidencyjną", file=sys.stderr)
        dzialka = zrodla.dzialka_po_xy(geo["dane"]["lon"], geo["dane"]["lat"])
    else:
        dzialka = {"status": "brak", "opis": "pominięto - brak współrzędnych"}

    rejestry = {}
    if args.imie or args.nazwisko:
        rejestry["CEIDG (działalność gospodarcza)"] = zrodla.ceidg_po_nazwisku(
            args.imie, args.nazwisko
        )
    if args.nip:
        rejestry["Biała Lista VAT"] = zrodla.biala_lista_nip(args.nip)
    if args.krs:
        rejestry["KRS - odpis aktualny"] = zrodla.krs_odpis(args.krs)

    print("[3/3] Generowanie raportu i pism", file=sys.stderr)
    d = dzialka.get("dane", {})
    pola = {
        "data": dt.date.today().strftime("%d.%m.%Y"),
        "miejscowosc": d.get("commune", ""),
        "adres": args.adres,
        "dzialka": d.get("id", ""),
        "obreb": d.get("region", ""),
        "gmina": d.get("commune", ""),
        "powiat": d.get("county", ""),
        "wojewodztwo": d.get("voivodeship", ""),
        "wnioskodawca": args.wnioskodawca,
        "kontakt": args.kontakt,
        "cel": args.cel,
        "interes_prawny": args.interes_prawny,
    }
    pola = {k: (v if v else "........................") for k, v in pola.items()}

    katalog = pathlib.Path(args.wyjscie)
    pisma = wypelnij_wzory(pola, katalog)
    raport = zbuduj_raport(args, geo, dzialka, rejestry, pisma)
    sciezka_raportu = katalog / "raport.md"
    sciezka_raportu.write_text(raport, encoding="utf-8")

    if args.json:
        print(json.dumps({"geo": geo, "dzialka": dzialka, "rejestry": rejestry},
                         ensure_ascii=False, indent=2))

    print(f"\nRaport:  {sciezka_raportu}", file=sys.stderr)
    print(f"Pisma:   {len(pisma)} szt. w {katalog}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
