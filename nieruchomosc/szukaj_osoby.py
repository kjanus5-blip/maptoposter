#!/usr/bin/env python3
"""Ustalenie, czy właściciel z Działu II księgi wieczystej żyje, i jak dotrzeć do spadkobierców.

Punkt wyjścia: masz już imię i nazwisko właściciela z Działu II KW. Skrypt:

1. sprawdza, czy masz komplet danych wymagany przez Rejestr Spadkowy,
2. wykrywa działające instancje wyszukiwarek grobów dla wskazanej gminy,
3. buduje gotowe, wypełnione linki do wyszukiwarek pochówków, nekrologów,
   ogłoszeń spadkowych i rejestrów gospodarczych,
4. odpytuje automatycznie te rejestry, które mają otwarte API.

Skrypt NIE zbiera numerów telefonów, adresów e-mail ani "alternatywnych adresów"
osób prywatnych - w Polsce nie ma dla nich legalnego źródła publicznego, a jedyne
adresy kontaktowe o mocy dowodowej to adres z Działu II KW i adres z CEIDG.
Nie przyjmuje też numeru PESEL jako argumentu, żeby nie zapisywać go na dysku;
PESEL wpisuje się bezpośrednio w formularz Rejestru Spadkowego.
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys
import unicodedata
import urllib.parse as up

import requests

import zrodla

# Wyszukiwarki pochówków o zasięgu ogólnopolskim.
BAZY_KRAJOWE = {
    "eCmentarze (ok. 3,4 mln rekordów)": "https://www.ecmentarze.pl/wyszukaj-pochowanego?nazwisko={nazwisko}&imie={imie}",
    "Mogily.pl": "http://mogily.pl/szukaj?nazwisko={nazwisko}&imie={imie}",
}

NEKROLOGI = {
    "Nekrologi.net": "https://www.nekrologi.net/znajdz-nekrologi?query={imie}+{nazwisko}",
    "Nekrologi Wyborczej": "https://nekrologi.wyborcza.pl/0,0.html?query={imie}+{nazwisko}",
}

# Wyszukiwarka grobów Zarządu Cmentarzy Komunalnych we Wrocławiu.
# Obejmuje 6 cmentarzy komunalnych (ok. 253 tys. rekordów). NIE obejmuje
# cmentarzy parafialnych, więc brak trafienia nie dowodzi, że osoba żyje.
ZCK_WROCLAW = "https://groby.cui.wroclaw.pl/"

REJESTRY = {
    "Rejestr Spadkowy (formularz z CAPTCHA - ręcznie)": "https://rejestry-notarialne.pl/37",
    "Notarialny Rejestr Testamentów (NORT)": "https://rejestry-notarialne.pl/35",
    "Monitor Sądowy i Gospodarczy": "https://wyszukiwarka-msig.ms.gov.pl/",
    "Wyszukiwarka KRS": "https://wyszukiwarka-krs.ms.gov.pl/",
    "CEIDG": "https://aplikacja.ceidg.gov.pl/ceidg/ceidg.public.ui/search.aspx",
    "Geneteka (indeksy metrykalne)": "https://geneteka.genealodzy.pl/index.php?op=gt&lang=pol&bdm=D&search_lastname={nazwisko}&search_name={imie}",
    "Przeglądarka ksiąg wieczystych": "https://przegladarka-ekw.ms.gov.pl/",
}


def bez_ogonkow(tekst: str) -> str:
    """'Zielona Góra (miasto)' -> 'zielonagora' - kandydat na subdomenę Grobonetu."""
    tekst = tekst.split("(")[0]
    tekst = tekst.replace("ł", "l").replace("Ł", "L")
    tekst = unicodedata.normalize("NFKD", tekst)
    tekst = "".join(z for z in tekst if not unicodedata.combining(z))
    return "".join(z for z in tekst.lower() if z.isalnum())


def znajdz_grobonet(gmina: str) -> list[tuple[str, str]]:
    """Sprawdza, czy gmina ma własną instancję Grobonetu.

    Grobonet działa jako osobny serwis per gmina (<gmina>.grobonet.com) - nie ma
    jednego wspólnego indeksu, więc trzeba trafić we właściwą instancję.
    """
    if not gmina:
        return []
    kandydat = bez_ogonkow(gmina)
    if not kandydat:
        return []

    znalezione = []
    for host in (f"{kandydat}.grobonet.com", f"cmentarz.{kandydat}.pl"):
        url = f"https://{host}/grobonet/start.php"
        try:
            r = requests.head(url, timeout=10, allow_redirects=True,
                              headers={"User-Agent": zrodla.UA})
            if r.status_code == 200:
                znalezione.append((host, url))
        except requests.RequestException:
            continue
    return znalezione


def kompletnosc_danych(args) -> tuple[list[str], list[str]]:
    """Czy da się już skorzystać z Rejestru Spadkowego."""
    mam, brakuje = [], []
    (mam if args.imie else brakuje).append("imię")
    (mam if args.nazwisko else brakuje).append("nazwisko")
    (mam if args.ojciec else brakuje).append("imię ojca (Dział II, pole 2.2.5.6)")
    (mam if args.matka else brakuje).append("imię matki (Dział II, pole 2.2.5.7)")
    if args.ma_pesel:
        mam.append("PESEL (Dział II, pole 2.2.5.8)")
    else:
        brakuje.append("PESEL (Dział II, pole 2.2.5.8) - jeśli księga go ujawnia")
    if args.rok_urodzenia or args.rok_zgonu:
        mam.append("rok urodzenia lub zgonu")
    else:
        brakuje.append("data urodzenia albo data zgonu")
    return mam, brakuje


def zbuduj_karte(args, grobonety, ceidg) -> str:
    imie_q = up.quote(args.imie)
    nazw_q = up.quote(args.nazwisko)
    mam, brakuje = kompletnosc_danych(args)
    osoba = f"{args.imie} {args.nazwisko}".strip()

    w = [f"# Karta osoby: {osoba}\n", f"Wygenerowano: {dt.date.today().isoformat()}\n"]
    if args.gmina:
        w.append(f"Nieruchomość w gminie: **{args.gmina}**\n")

    w.append("## 1. Czy możesz już odpytać Rejestr Spadkowy\n")
    w.append(
        "To jest najkrótsza droga do spadkobierców i jest bezpłatna. Rejestr przyjmuje "
        "**PESEL** albo **imię + nazwisko + imiona rodziców + datę urodzenia lub zgonu**. "
        "Dokładnie te dane Dział II księgi wieczystej podaje w polach 2.2.5.6 (imię ojca), "
        "2.2.5.7 (imię matki) i 2.2.5.8 (PESEL) - jeśli masz wgląd w księgę, masz komplet.\n"
    )
    if mam:
        w.append("Masz:\n" + "\n".join(f"- ✅ {p}" for p in mam))
    if brakuje:
        w.append("\nBrakuje:\n" + "\n".join(f"- ⬜ {p}" for p in brakuje))
    w.append(
        f"\n{'**Możesz wypełnić formularz teraz:**' if not brakuje else 'Uzupełnij braki z Działu II, potem:'} "
        f"{REJESTRY['Rejestr Spadkowy (formularz z CAPTCHA - ręcznie)']}\n"
        "\nWynik powie Ci, czy sporządzono akt poświadczenia dziedziczenia lub wydano "
        "postanowienie o stwierdzeniu nabycia spadku - **oraz u którego notariusza albo "
        "w którym sądzie** leżą akta. Rejestr nie poda nazwisk spadkobierców; poda adres, "
        "pod którym o nie zapytać.\n"
        "\n> Starsze księgi wieczyste bywają bez PESEL - wpisu nigdy nie aktualizowano. "
        "Wtedy zostaje komplet: imiona rodziców + data urodzenia lub zgonu.\n"
    )

    w.append("## 2. Czy osoba żyje - miejsce pochówku\n")
    if grobonety:
        w.append(f"Wykryto instancję Grobonetu dla gminy **{args.gmina}**:\n")
        for host, url in grobonety:
            w.append(f"- [{host}]({url}?id=wyniki&imie={imie_q}&nazwisko={nazw_q})")
        w.append("")
    elif args.gmina:
        w.append(
            f"Nie wykryto instancji Grobonetu pod `{bez_ogonkow(args.gmina)}.grobonet.com`. "
            "Grobonet działa osobno dla każdej gminy i nie ma wspólnego indeksu - poszukaj "
            "frazy „wyszukiwarka grobów \" + nazwa gminy, albo zapytaj wprost zarząd cmentarza "
            "komunalnego. Zarządy cmentarzy udzielają takiej informacji telefonicznie.\n"
        )
    else:
        w.append("Podaj `--gmina`, żeby wykryć lokalną wyszukiwarkę grobów.\n")

    w.append("Bazy o zasięgu krajowym:\n")
    for nazwa, wzor in BAZY_KRAJOWE.items():
        w.append(f"- [{nazwa}]({wzor.format(imie=imie_q, nazwisko=nazw_q)})")
    w.append("\nNekrologi (często podają imiona dzieci i wnuków - to gotowa lista spadkobierców):\n")
    for nazwa, wzor in NEKROLOGI.items():
        w.append(f"- [{nazwa}]({wzor.format(imie=imie_q, nazwisko=nazw_q)})")
    w.append(
        "\n> Grób rodzinny to najtańsze źródło kręgu spadkobierców: nagrobek podaje nazwiska "
        "po mężu, czyli to, czego brakuje przy córkach. Zdjęcie nagrobka bywa w bazie.\n"
    )

    w.append("## 3. Pozostałe rejestry\n")
    for nazwa, url in REJESTRY.items():
        if "Rejestr Spadkowy" in nazwa:
            continue
        w.append(f"- [{nazwa}]({url.format(imie=imie_q, nazwisko=nazw_q)})")
    w.append(
        "\nW Monitorze Sądowym i Gospodarczym szukaj ogłoszeń o **wezwaniu spadkobierców** "
        "(art. 672-673 k.p.c.) - jeżeli sąd takie wydał, sygnatura sprawy prowadzi prosto "
        "do akt.\n"
    )

    if ceidg:
        w.append("## 4. CEIDG - odpytane automatycznie\n")
        if ceidg["status"] == "ok":
            w.append(
                f"Znaleziono {len(ceidg['dane'])} wpis(ów). CEIDG ujawnia adres wykonywania "
                "działalności i często telefon oraz e-mail - **podane tam dobrowolnie przez "
                "samego przedsiębiorcę do kontaktu**, więc to legalny kanał.\n"
            )
            for f in ceidg["dane"][:10]:
                w.append(f"- `{f.get('nazwa','?')}` — status: {f.get('status','?')}, "
                         f"NIP: {f.get('nip','?')}")
        else:
            w.append(f"- {ceidg.get('opis')}")
        w.append("")

    w.append("## 5. Jak zinterpretować wynik\n")
    w.append(
        "**Właściciel żyje** → pisz listem poleconym za potwierdzeniem odbioru na adres "
        "z Działu II KW. To nie jest gorszy kanał niż telefon - to jedyny, który daje dowód "
        "doręczenia, gdyby doszło do transakcji. Równolegle poproś zarządcę o przekazanie "
        "pisma (wzór `pismo_zarzadca.md`).\n\n"
        "**Właściciel nie żyje, postępowanie spadkowe BYŁO** → Rejestr Spadkowy wskaże "
        "notariusza lub sąd. Spadkobiercy zwykle ujawniają się w Dziale II - sprawdź księgę "
        "ponownie, bo mogła zostać zaktualizowana po Twoim ostatnim wglądzie.\n\n"
        "**Właściciel nie żyje, postępowania NIE BYŁO** → nie ma komu sprzedać nieruchomości "
        "i nikt tego za Ciebie nie załatwi. Realne wyjścia: znaleźć choć jednego spadkobiercę "
        "(nekrologi, grób rodzinny, sąsiedzi, parafia) i to on przeprowadza stwierdzenie "
        "nabycia spadku, albo zgłoszenie do gminy o kuratora spadku "
        "(wzór `zgloszenie_gmina.md`).\n\n"
        "**Nie da się ustalić niczego** → zostaje gmina i art. 666 § 1 k.p.c.\n"
    )

    w.append("## 6. Czego tu nie ma i dlaczego\n")
    w.append(
        "Nie ma wyszukiwania numeru telefonu, e-maila ani „innych adresów\" osoby prywatnej. "
        "W Polsce nie istnieje dla nich legalne źródło publiczne - książki telefoniczne "
        "zniknęły wraz z RODO, a serwisy obiecujące „znajdź osobę po nazwisku\" opierają się "
        "na wyciekach danych albo na brokerach z szarej strefy. Poza tym, że to niezgodne "
        "z prawem, jest praktycznie ryzykowne: przy transakcji nieruchomości kontakt zdobyty "
        "taką drogą podważa Twoją dobrą wiarę i daje drugiej stronie argument przeciw Tobie.\n\n"
        "Legalne kanały kontaktu do osoby prywatnej są dokładnie trzy: adres z Działu II KW, "
        "dane kontaktowe z CEIDG (jeśli prowadziła działalność) i pośrednictwo zarządcy "
        "nieruchomości. W praktyce wystarczają.\n"
    )
    return "\n".join(w)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Sprawdzenie, czy właściciel z Działu II KW żyje, i droga do spadkobierców.",
    )
    p.add_argument("--imie", required=True, help="imię właściciela z Działu II KW")
    p.add_argument("--nazwisko", required=True, help="nazwisko właściciela z Działu II KW")
    p.add_argument("--ojciec", default="", help="imię ojca (Dział II, pole 2.2.5.6)")
    p.add_argument("--matka", default="", help="imię matki (Dział II, pole 2.2.5.7)")
    p.add_argument("--ma-pesel", action="store_true",
                   help="zaznacz, jeśli księga ujawnia PESEL (nie podawaj go - nie zapisujemy go na dysk)")
    p.add_argument("--rok-urodzenia", default="", help="rok urodzenia, jeśli znany")
    p.add_argument("--rok-zgonu", default="", help="rok zgonu, jeśli znany")
    p.add_argument("--gmina", default="", help="gmina nieruchomości - do wykrycia lokalnej wyszukiwarki grobów")
    p.add_argument("--wyjscie", default="wynik", help="katalog wyjściowy (domyślnie: wynik)")
    args = p.parse_args(argv)

    print(f"[1/3] Szukanie lokalnej wyszukiwarki grobów dla: {args.gmina or '(nie podano)'}",
          file=sys.stderr)
    grobonety = znajdz_grobonet(args.gmina)

    print("[2/3] CEIDG", file=sys.stderr)
    ceidg = zrodla.ceidg_po_nazwisku(args.imie, args.nazwisko)

    print("[3/3] Budowanie karty osoby", file=sys.stderr)
    katalog = pathlib.Path(args.wyjscie)
    katalog.mkdir(parents=True, exist_ok=True)
    sciezka = katalog / f"osoba_{bez_ogonkow(args.nazwisko) or 'nn'}.md"
    sciezka.write_text(zbuduj_karte(args, grobonety, ceidg), encoding="utf-8")

    print(f"\nKarta osoby: {sciezka}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
