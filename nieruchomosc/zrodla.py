"""Klienci publicznych rejestrów używanych przy ustalaniu właściciela nieruchomości.

Każda funkcja zwraca słownik z kluczem ``status`` ("ok" / "brak" / "blad")
i - przy powodzeniu - kluczem ``dane``. Żadna z nich nie obchodzi CAPTCHA
ani nie loguje się do serwisów wymagających uwierzytelnienia.
"""

from __future__ import annotations

import os
import time
from typing import Any

import requests

UA = "ustal-wlasciciela/1.0 (kontakt w sprawie nieruchomosci)"
TIMEOUT = 30

# Nominatim wymaga max 1 zapytania na sekundę - pilnujemy tego globalnie.
_ostatnie_nominatim = 0.0


def _get(url: str, **kwargs: Any) -> requests.Response:
    naglowki = {"User-Agent": UA}
    naglowki.update(kwargs.pop("headers", {}))
    return requests.get(url, headers=naglowki, timeout=TIMEOUT, **kwargs)


def geokoduj(adres: str) -> dict:
    """Adres -> współrzędne WGS84 (OpenStreetMap / Nominatim)."""
    global _ostatnie_nominatim
    odstep = time.monotonic() - _ostatnie_nominatim
    if odstep < 1.0:
        time.sleep(1.0 - odstep)
    _ostatnie_nominatim = time.monotonic()

    try:
        r = _get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": adres,
                "format": "jsonv2",
                "limit": 1,
                "countrycodes": "pl",
                "addressdetails": 1,
            },
        )
        r.raise_for_status()
        trafienia = r.json()
    except (requests.RequestException, ValueError) as e:
        return {"status": "blad", "opis": f"Nominatim: {e}"}

    if not trafienia:
        return {"status": "brak", "opis": "Nominatim nie rozpoznał adresu"}

    t = trafienia[0]
    return {
        "status": "ok",
        "dane": {
            "lat": float(t["lat"]),
            "lon": float(t["lon"]),
            "opis": t.get("display_name", ""),
            "typ": t.get("addresstype", ""),
        },
    }


# Pola zwracane przez ULDK w podanej kolejności.
_POLA_ULDK = ["id", "voivodeship", "county", "commune", "region", "parcel"]


def dzialka_po_xy(lon: float, lat: float) -> dict:
    """Współrzędne -> identyfikator ewidencyjny działki (ULDK, GUGiK).

    Uwaga: ULDK nie udostępnia numeru księgi wieczystej ani danych właściciela.
    """
    try:
        r = _get(
            "https://uldk.gugik.gov.pl/",
            params={
                "request": "GetParcelByXY",
                "xy": f"{lon},{lat},4326",
                "result": ",".join(_POLA_ULDK),
            },
        )
        r.raise_for_status()
    except requests.RequestException as e:
        return {"status": "blad", "opis": f"ULDK: {e}"}

    linie = [w.strip() for w in r.text.splitlines() if w.strip()]
    if not linie or linie[0] != "0":
        return {"status": "brak", "opis": f"ULDK: {' '.join(linie) or 'pusta odpowiedź'}"}
    if len(linie) < 2:
        return {"status": "brak", "opis": "ULDK: brak rekordu działki"}

    wartosci = linie[1].split("|")
    dane = dict(zip(_POLA_ULDK, wartosci))
    return {"status": "ok", "dane": dane}


def ceidg_po_nazwisku(imie: str, nazwisko: str) -> dict:
    """Szukanie osoby w CEIDG. Wymaga darmowego tokenu w CEIDG_TOKEN.

    Znajdzie kogoś tylko jeśli prowadzi lub prowadził jednoosobową działalność.
    """
    token = os.environ.get("CEIDG_TOKEN")
    if not token:
        return {"status": "brak", "opis": "brak CEIDG_TOKEN w środowisku - pominięto"}

    try:
        r = _get(
            "https://dane.biznes.gov.pl/api/ceidg/v3/firmy",
            params={"imie": imie, "nazwisko": nazwisko},
            headers={"Authorization": f"Bearer {token}"},
        )
        if r.status_code == 401:
            return {"status": "blad", "opis": "CEIDG: token odrzucony (401)"}
        r.raise_for_status()
        tresc = r.json()
    except (requests.RequestException, ValueError) as e:
        return {"status": "blad", "opis": f"CEIDG: {e}"}

    firmy = tresc.get("firmy", [])
    if not firmy:
        return {"status": "brak", "opis": "CEIDG: brak wpisów"}
    return {"status": "ok", "dane": firmy}


def krs_odpis(numer_krs: str) -> dict:
    """Odpis aktualny z KRS po numerze KRS (otwarte API, bez klucza).

    API nie pozwala szukać po nazwisku - numer trzeba znać z innego źródła.
    """
    numer = numer_krs.strip().zfill(10)
    for rejestr in ("P", "S"):  # przedsiębiorcy, potem stowarzyszenia
        try:
            r = _get(
                f"https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/{numer}",
                params={"rejestr": rejestr, "format": "json"},
            )
            if r.status_code == 404:
                continue
            r.raise_for_status()
            return {"status": "ok", "dane": r.json()}
        except (requests.RequestException, ValueError) as e:
            return {"status": "blad", "opis": f"KRS: {e}"}
    return {"status": "brak", "opis": f"KRS: nie znaleziono numeru {numer}"}


def biala_lista_nip(nip: str) -> dict:
    """Wykaz podatników VAT (Ministerstwo Finansów) - po NIP."""
    nip = "".join(c for c in nip if c.isdigit())
    data = time.strftime("%Y-%m-%d")
    try:
        r = _get(f"https://wl-api.mf.gov.pl/api/search/nip/{nip}", params={"date": data})
        r.raise_for_status()
        podmiot = r.json().get("result", {}).get("subject")
    except (requests.RequestException, ValueError) as e:
        return {"status": "blad", "opis": f"Biała lista: {e}"}

    if not podmiot:
        return {"status": "brak", "opis": f"Biała lista: brak podmiotu o NIP {nip}"}
    return {"status": "ok", "dane": podmiot}
