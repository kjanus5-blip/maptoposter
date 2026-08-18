#!/usr/bin/env python3
"""Lokalna aplikacja webowa do ustalania właściciela i spadkobierców nieruchomości.

Uruchomienie:
    python3 app.py
a następnie otwarcie http://127.0.0.1:5000 w przeglądarce.

Aplikacja działa wyłącznie na Twoim komputerze - nic nie jest nigdzie wysyłane
poza zapytaniami do publicznych rejestrów, które i tak wykonałbyś ręcznie.
"""

from __future__ import annotations

import datetime as dt
import io
import pathlib
import zipfile

from flask import Flask, render_template, request, send_file

import ustal_wlasciciela as uw
import zrodla

app = Flask(__name__)
KATALOG = pathlib.Path(__file__).resolve().parent

# Źródła bramkowane - wymagają jednego kliknięcia użytkownika (CAPTCHA lub zgoda
# RODO). Program przygotowuje dane do wklejenia, ale nie obchodzi bramki.
BRAMKOWANE = [
    {
        "nazwa": "Rejestr Spadkowy",
        "url": "https://rejestry-notarialne.pl/37",
        "bramka": "reCAPTCHA",
        "dlaczego": "Rozstrzyga, czy było postępowanie spadkowe i gdzie leżą akta. "
                    "Najkrótsza droga do spadkobierców. Bezpłatny.",
        "waga": "kluczowe",
    },
    {
        "nazwa": "Wyszukiwarka grobów ZCK Wrocław",
        "url": "https://groby.cui.wroclaw.pl/",
        "bramka": "oświadczenie RODO",
        "dlaczego": "253 tys. rekordów z 6 cmentarzy komunalnych. Uwaga: nie obejmuje "
                    "cmentarzy parafialnych, więc brak trafienia nie dowodzi, że osoba żyje.",
        "waga": "ważne",
    },
    {
        "nazwa": "Przeglądarka ksiąg wieczystych",
        "url": "https://przegladarka-ekw.ms.gov.pl/",
        "bramka": "CAPTCHA + zakaz w regulaminie",
        "dlaczego": "Dział II poda aktualnego właściciela. Sprawdź ponownie - księga mogła "
                    "zostać zaktualizowana przez spadkobierców.",
        "waga": "ważne",
    },
    {
        "nazwa": "Notarialny Rejestr Testamentów",
        "url": "https://rejestry-notarialne.pl/35",
        "bramka": "reCAPTCHA",
        "dlaczego": "Sprawdza, czy zmarły zostawił testament zarejestrowany u notariusza.",
        "waga": "pomocnicze",
    },
    {
        "nazwa": "Monitor Sądowy i Gospodarczy",
        "url": "https://wyszukiwarka-msig.ms.gov.pl/",
        "bramka": "interfejs JS",
        "dlaczego": "Ogłoszenia o wezwaniu spadkobierców (art. 672-673 k.p.c.). "
                    "Sygnatura prowadzi wprost do akt sprawy.",
        "waga": "pomocnicze",
    },
]


def pola_rejestru_spadkowego(f: dict) -> list[dict]:
    """Checklista danych, których wymaga formularz Rejestru Spadkowego."""
    return [
        {"etykieta": "Imię", "wartosc": f.get("imie", ""), "zrodlo": "Dział II KW"},
        {"etykieta": "Nazwisko", "wartosc": f.get("nazwisko", ""), "zrodlo": "Dział II KW"},
        {"etykieta": "Imię ojca", "wartosc": f.get("ojciec", ""), "zrodlo": "Dział II, pole 2.2.5.6"},
        {"etykieta": "Imię matki", "wartosc": f.get("matka", ""), "zrodlo": "Dział II, pole 2.2.5.7"},
        {"etykieta": "PESEL", "wartosc": "masz go w księdze" if f.get("ma_pesel") else "",
         "zrodlo": "Dział II, pole 2.2.5.8 — wpisz wprost w formularz"},
        {"etykieta": "Rok urodzenia", "wartosc": f.get("rok_urodzenia", ""), "zrodlo": "Dział II KW"},
        {"etykieta": "Rok zgonu", "wartosc": f.get("rok_zgonu", ""), "zrodlo": "jeśli znany"},
    ]


@app.route("/", methods=["GET"])
def start():
    return render_template("index.html")


@app.route("/szukaj", methods=["POST"])
def szukaj():
    f = {k: request.form.get(k, "").strip() for k in
         ("adres", "imie", "nazwisko", "ojciec", "matka", "rok_urodzenia", "rok_zgonu")}
    f["ma_pesel"] = bool(request.form.get("ma_pesel"))

    auto, geo, dzialka = [], None, None

    if f["adres"]:
        geo = zrodla.geokoduj(f["adres"])
        if geo["status"] == "ok":
            dzialka = zrodla.dzialka_po_xy(geo["dane"]["lon"], geo["dane"]["lat"])
            if dzialka["status"] == "ok":
                d = dzialka["dane"]
                auto.append({
                    "nazwa": "Działka ewidencyjna (ULDK / GUGiK)",
                    "status": "ok",
                    "podsumowanie": f"Identyfikator {d.get('id','?')}",
                    "szczegoly": [f"Obręb: {d.get('region','?')}",
                                  f"Gmina: {d.get('commune','?')}",
                                  f"Powiat: {d.get('county','?')}",
                                  f"Województwo: {d.get('voivodeship','?')}"],
                })
            else:
                auto.append({"nazwa": "Działka ewidencyjna (ULDK / GUGiK)", "status": "brak",
                             "podsumowanie": dzialka.get("opis", ""), "szczegoly": []})
        else:
            auto.append({"nazwa": "Geokodowanie adresu", "status": "brak",
                         "podsumowanie": geo.get("opis", ""),
                         "szczegoly": ["Spróbuj dokładniejszego zapisu: ulica, numer, miasto."]})

    if f["imie"] or f["nazwisko"]:
        nek = zrodla.nekrologi_szukaj(f["imie"], f["nazwisko"])
        if nek["status"] == "ok":
            auto.append({
                "nazwa": "Nekrologi",
                "status": "ok",
                "podsumowanie": f"{len(nek['dane'])} trafień — sprawdź, czy któreś pasuje",
                "linki": nek["dane"],
                "szczegoly": ["Nekrolog zwykle wymienia z imienia dzieci i wnuki — "
                              "to gotowy krąg spadkobierców."],
            })
        else:
            auto.append({"nazwa": "Nekrologi", "status": "brak",
                         "podsumowanie": nek.get("opis", ""), "szczegoly": []})

        ceidg = zrodla.ceidg_po_nazwisku(f["imie"], f["nazwisko"])
        if ceidg["status"] == "ok":
            auto.append({
                "nazwa": "CEIDG",
                "status": "ok",
                "podsumowanie": f"{len(ceidg['dane'])} wpis(ów) działalności",
                "szczegoly": [f"{x.get('nazwa','?')} — {x.get('status','?')}"
                              for x in ceidg["dane"][:8]] +
                             ["Dane kontaktowe w CEIDG przedsiębiorca podał sam — to legalny kanał."],
            })
        else:
            auto.append({"nazwa": "CEIDG", "status": "brak",
                         "podsumowanie": ceidg.get("opis", ""), "szczegoly": []})

    braki = [p["etykieta"] for p in pola_rejestru_spadkowego(f) if not p["wartosc"]]
    gotowy = not [b for b in braki if b in ("Imię", "Nazwisko")] and (
        f["ma_pesel"] or (f["ojciec"] and f["matka"] and (f["rok_urodzenia"] or f["rok_zgonu"]))
    )

    return render_template(
        "wynik.html",
        f=f, auto=auto, bramkowane=BRAMKOWANE,
        pola=pola_rejestru_spadkowego(f), gotowy=gotowy, braki=braki,
        osoba=f"{f['imie']} {f['nazwisko']}".strip() or "(nie podano)",
        dzialka=(dzialka or {}).get("dane", {}),
        data=dt.date.today().strftime("%d.%m.%Y"),
    )


@app.route("/pisma", methods=["POST"])
def pisma():
    """Generuje komplet pism i oddaje je jako jeden plik ZIP."""
    d = {k: request.form.get(k, "") for k in
         ("adres", "dzialka", "obreb", "gmina", "powiat", "wojewodztwo",
          "wnioskodawca", "kontakt", "cel", "interes_prawny")}
    d["data"] = dt.date.today().strftime("%d.%m.%Y")
    d["miejscowosc"] = d.get("gmina", "")
    pola = {k: (v if v else "........................") for k, v in d.items()}

    bufor = io.BytesIO()
    with zipfile.ZipFile(bufor, "w", zipfile.ZIP_DEFLATED) as z:
        for wzor in sorted((KATALOG / "wzory").glob("*.md")):
            tresc = wzor.read_text(encoding="utf-8").format_map(uw._Braki(pola))
            z.writestr(wzor.name, tresc)
    bufor.seek(0)
    return send_file(bufor, mimetype="application/zip",
                     as_attachment=True, download_name="pisma.zip")


if __name__ == "__main__":
    print("\n  Otwórz w przeglądarce:  http://127.0.0.1:5000\n")
    app.run(debug=False, port=5000)
