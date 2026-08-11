"""Panel WWW — warstwa wizualna nad tym samym silnikiem, co CLI.

Widok nigdy nie liczy metryk sam. Wszystko idzie przez `metrics` i
`benchmark`, więc liczba na ekranie i liczba w raporcie Markdown zawsze się
zgadzają.

Serwer domyślnie słucha tylko na 127.0.0.1 — panel pokazuje dane osobowe
i nie powinien być wystawiony do sieci bez świadomej decyzji.
"""

from __future__ import annotations

import secrets
import tempfile
from datetime import date
from pathlib import Path

from flask import (
    Flask,
    Response,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from ..benchmark import (
    ETYKIETY_POL,
    grupy_porownawcze,
    metryki_biura,
    opis_dla_modelu,
    ranking_biur,
)
from ..classify import sklasyfikuj
from ..ingest import wczytaj_plik
from ..metrics import (
    TYPY_OKRESOW,
    alerty,
    etykieta_okresu,
    klucz_okresu,
    nastepny_okres,
    podsumowanie,
    poprzedni_okres,
    porownaj,
    ranking_zespolu,
    zakres_okresu,
)
from ..models import WYNIK_INFO_RYNKOWE, WYNIK_LEAD, WYNIK_SYGNAL
from ..org import NAZWY_ROL, OPIS_ROL, ROLE, Biuro
from ..punktacja import (
    WSKAZNIKI_POMOCNICZE,
    dopisz_punkty,
    licznosci_okresu,
    wskazniki_dla_roli,
)
from ..report import ETYKIETY_WYNIKOW, zbuduj_raport
from ..store import Baza
from . import charts

NAZWY_OKRESOW = {
    "dzien": "Dzień", "tydzien": "Tydzień", "miesiac": "Miesiąc",
    "kwartal": "Kwartał", "rok": "Rok",
}


def stworz_aplikacje(sciezka_bazy: str = "data/analityk.db") -> Flask:
    app = Flask(__name__)
    app.secret_key = secrets.token_hex(16)
    app.config["SCIEZKA_BAZY"] = sciezka_bazy
    app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024

    def baza() -> Baza:
        """Jedno połączenie na żądanie, zamykane w `teardown`.

        Osobne połączenie per wywołanie zostawiało otwarte uchwyty i przy
        nieudanym zapisie potrafiło zablokować plik bazy na stałe.
        """
        if "baza" not in g:
            g.baza = Baza(app.config["SCIEZKA_BAZY"])
        return g.baza

    @app.teardown_appcontext
    def zamknij_baze(_wyjatek=None):
        polaczenie = g.pop("baza", None)
        if polaczenie is not None:
            polaczenie.zamknij()

    # --- wspólny kontekst okresu -----------------------------------------

    def kontekst_okresu() -> dict:
        # `values` łączy parametry adresu i pola formularza — bez tego POST
        # (np. przycisk generowania oceny) trafiałby w domyślny dzisiejszy
        # dzień zamiast w okres, który użytkownik ma na ekranie.
        typ = request.values.get("okres", "dzien")
        if typ not in TYPY_OKRESOW:
            typ = "dzien"
        klucz = request.values.get("klucz") or klucz_okresu(date.today(), typ)
        # Klucz okresu przychodzi z adresu URL, więc może być dowolnym śmieciem.
        # Sprawdzamy go, wykonując pełne parsowanie, a nie jego fragment.
        try:
            od, do = zakres_okresu(klucz, typ)
            etykieta = etykieta_okresu(klucz, typ)
        except (ValueError, IndexError, KeyError):
            klucz = klucz_okresu(date.today(), typ)
            od, do = zakres_okresu(klucz, typ)
            etykieta = etykieta_okresu(klucz, typ)
        return {
            "typ": typ, "klucz": klucz, "od": od, "do": do,
            "etykieta": etykieta,
            "poprzedni": poprzedni_okres(klucz, typ),
            "nastepny": nastepny_okres(klucz, typ),
            "typy": TYPY_OKRESOW, "nazwy_okresow": NAZWY_OKRESOW,
        }

    @app.context_processor
    def globalne():
        return {
            "okres": kontekst_okresu(),
            "nazwy_rol": NAZWY_ROL,
            "role": ROLE,
            "dzis": date.today().isoformat(),
        }

    def metryki_pracownika(b: Baza, p, typ: str, klucz: str):
        od, do = zakres_okresu(klucz, typ)
        akt = b.pobierz(pracownik=p.klucz, od=od, do=do)
        m = podsumowanie(akt, typ, p.normy_pelne, zakres=(od, do))
        return akt, dopisz_punkty(b, p, typ, klucz, akt, m)

    # --- pulpit -----------------------------------------------------------

    @app.route("/")
    def pulpit():
        b = baza()
        o = kontekst_okresu()
        wszyscy = b.pracownicy()

        per_prac, dane_prac = {}, {}
        for p in wszyscy:
            _, m = metryki_pracownika(b, p, o["typ"], o["klucz"])
            per_prac[p.klucz] = m
            dane_prac[p.klucz] = p

        wszystkie_akt = b.pobierz(od=o["od"], do=o["do"])
        lacznie = podsumowanie(wszystkie_akt, o["typ"], zakres=(o["od"], o["do"]))

        ostrzezenia = [
            (dane_prac[k], a) for k, m in per_prac.items() for a in alerty(m)
        ]
        return render_template(
            "pulpit.html",
            lacznie=lacznie,
            biura=ranking_biur(b, o["typ"], o["klucz"]),
            ranking=[(dane_prac[k], per_prac[k], ind)
                     for k, ind, _ in ranking_zespolu(per_prac)],
            bez_wynikow=[p for p in wszyscy if per_prac[p.klucz].get("pusty")],
            ostrzezenia=ostrzezenia,
            nieprzypisani=b.nieprzypisani(),
            wykres_dni=charts.slupki(_szereg_dzienny(wszystkie_akt, o)),
        )

    # --- biuro ------------------------------------------------------------

    @app.route("/biuro/<int:biuro_id>")
    def widok_biura(biuro_id: int):
        b = baza()
        o = kontekst_okresu()
        biuro = b.biuro(biuro_id)
        if not biuro:
            flash("Nie ma takiego biura.", "blad")
            return redirect(url_for("pulpit"))

        m = metryki_biura(b, biuro_id, o["typ"], o["klucz"])
        m_poprz = metryki_biura(b, biuro_id, o["typ"], o["poprzedni"])
        zespol = b.pracownicy(biuro_id=biuro_id)

        per_prac = {}
        for p in zespol:
            _, mp = metryki_pracownika(b, p, o["typ"], o["klucz"])
            per_prac[p.klucz] = mp

        wszystkie = ranking_biur(b, o["typ"], o["klucz"])
        moje_miejsce = next((x["miejsce"] for x in wszystkie if x["biuro"].id == biuro_id), None)

        return render_template(
            "biuro.html",
            biuro=biuro,
            m=m,
            trend=porownaj(m, m_poprz) if not (m.get("pusty") or m_poprz.get("pusty")) else {},
            zespol=[(p, per_prac[p.klucz]) for p in zespol],
            role_w_biurze=_zespol_wg_rol(zespol, per_prac),
            miejsce=moje_miejsce,
            wszystkie_biura=wszystkie,
            wykres_wynikow=charts.paski_udzialow(
                [(ETYKIETY_WYNIKOW.get(w, w), n) for w, n in (m.get("wyniki") or {}).items()],
                m.get("liczba_aktywnosci"),
            ),
            wskaznik=charts.wskaznik(m.get("indeks_jakosci", 0), etykieta="indeks biura"),
        )

    # --- pracownik --------------------------------------------------------

    @app.route("/pracownik/<klucz>")
    def widok_pracownika(klucz: str):
        b = baza()
        o = kontekst_okresu()
        p = b.pracownik_lub_domyslny(klucz)

        akt, m = metryki_pracownika(b, p, o["typ"], o["klucz"])
        _, m_poprz = metryki_pracownika(b, p, o["typ"], o["poprzedni"])
        grupy = [] if m.get("pusty") else grupy_porownawcze(b, p, o["typ"], o["klucz"], m)
        zapisany = b.raport(klucz, o["typ"], o["klucz"])

        licznosci = licznosci_okresu(b, klucz, o["typ"], o["klucz"], akt)
        return render_template(
            "pracownik.html",
            p=p,
            m=m,
            opis_roli=OPIS_ROL.get(p.rola, ""),
            wskazniki_do_wpisania=[
                w for w in wskazniki_dla_roli(p.rola) + list(WSKAZNIKI_POMOCNICZE)
            ],
            wpisane=b.wskazniki(klucz, o["typ"], o["klucz"]),
            licznosci=licznosci,
            trend=porownaj(m, m_poprz) if not (m.get("pusty") or m_poprz.get("pusty")) else {},
            grupy=grupy,
            pasek=charts.pasek_pozycji,
            alerty=alerty(m, m_poprz),
            pamiec=b.pamiec(klucz, limit=12),
            leady=[a for a in akt if a.wynik in (WYNIK_LEAD, WYNIK_SYGNAL)],
            rynek=[a for a in akt if a.wynik == WYNIK_INFO_RYNKOWE],
            ocena=(zapisany or {}).get("ocena"),
            wskaznik=charts.wskaznik(m.get("indeks_jakosci", 0), etykieta="indeks jakości"),
            wykres_godzin=charts.slupki(
                [(f"{g}", n) for g, n in (m.get("rozklad_godzinowy") or {}).items()]
            ),
            wykres_dni=charts.slupki(_szereg_dzienny(akt, o)),
            wykres_wynikow=charts.paski_udzialow(
                [(ETYKIETY_WYNIKOW.get(w, w), n) for w, n in (m.get("wyniki") or {}).items()],
                m.get("liczba_aktywnosci"),
            ),
        )

    @app.post("/pracownik/<klucz>/pamiec")
    def dodaj_pamiec(klucz: str):
        b = baza()
        tresc = (request.form.get("tresc") or "").strip()
        if tresc:
            b.dopisz_pamiec(klucz, request.form.get("typ", "ustalenie_1n1"), tresc)
            flash("Zapisano w pamięci agenta — trafi do następnego raportu.", "ok")
        return redirect(_powrot(url_for("widok_pracownika", klucz=klucz)))

    @app.post("/pracownik/<klucz>/wskazniki")
    def zapisz_wskazniki(klucz: str):
        """Ręczne uzupełnienie liczników, których nie ma w eksporcie aktywności."""
        b = baza()
        o = kontekst_okresu()
        wartosci: dict[str, float | str] = {}
        for kod in list(request.form):
            if not kod.startswith("w_"):
                continue
            surowa = (request.form.get(kod) or "").strip().replace(",", ".")
            kod_wskaznika = kod[2:]
            if surowa == "":
                wartosci[kod_wskaznika] = ""      # puste = "nie wiem", kasuje wpis
                continue
            try:
                wartosci[kod_wskaznika] = float(surowa)
            except ValueError:
                flash(f"„{surowa}” to nie liczba — pominięto {kod_wskaznika}.", "blad")
        b.zapisz_wskazniki(klucz, o["typ"], o["klucz"], wartosci)
        flash(f"Zapisano wskaźniki dla okresu {o['klucz']}.", "ok")
        return redirect(_powrot(url_for("widok_pracownika", klucz=klucz)))

    @app.post("/pracownik/<klucz>/ocena")
    def generuj_ocene(klucz: str):
        b = baza()
        o = kontekst_okresu()
        p = b.pracownik_lub_domyslny(klucz)
        akt, m = metryki_pracownika(b, p, o["typ"], o["klucz"])
        if m.get("pusty"):
            flash("Brak aktywności w tym okresie — nie ma czego oceniać.", "blad")
            return redirect(_powrot(url_for("widok_pracownika", klucz=klucz)))

        _, m_poprz = metryki_pracownika(b, p, o["typ"], o["poprzedni"])
        grupy = grupy_porownawcze(b, p, o["typ"], o["klucz"], m)

        from ..llm import BrakKlucza, ocena_okresu
        try:
            ocena = ocena_okresu(
                p, o["typ"], o["klucz"], m,
                porownaj(m, m_poprz) if not m_poprz.get("pusty") else {},
                alerty(m, m_poprz), b.pamiec(klucz, limit=10), akt,
                porownania=opis_dla_modelu(grupy),
            )
        except BrakKlucza as e:
            flash(str(e), "blad")
            return redirect(_powrot(url_for("widok_pracownika", klucz=klucz)))
        except Exception as e:  # noqa: BLE001 — komunikat trafia do użytkownika
            flash(f"Nie udało się wygenerować oceny: {e}", "blad")
            return redirect(_powrot(url_for("widok_pracownika", klucz=klucz)))

        tresc = zbuduj_raport(p, o["typ"], o["klucz"], m, akt, m_poprz, ocena,
                              b.pamiec(klucz, limit=10), grupy)
        b.zapisz_raport(klucz, o["typ"], o["klucz"], m, tresc, ocena)
        for obs in ocena.get("obserwacje_do_zapamietania", []):
            b.dopisz_pamiec(klucz, "obserwacja", obs, f"{o['typ']}:{o['klucz']}")
        for zal in ocena.get("plan_na_nastepny_okres", []):
            b.dopisz_pamiec(klucz, "zalecenie", zal, f"{o['typ']}:{o['klucz']}")
        flash("Ocena AI gotowa. Przejrzyj ją, zanim przekażesz pracownikowi.", "ok")
        return redirect(_powrot(url_for("widok_pracownika", klucz=klucz)))

    @app.route("/pracownik/<klucz>/raport.md")
    def raport_md(klucz: str):
        b = baza()
        o = kontekst_okresu()
        p = b.pracownik_lub_domyslny(klucz)
        akt, m = metryki_pracownika(b, p, o["typ"], o["klucz"])
        _, m_poprz = metryki_pracownika(b, p, o["typ"], o["poprzedni"])
        grupy = [] if m.get("pusty") else grupy_porownawcze(b, p, o["typ"], o["klucz"], m)
        zapisany = b.raport(klucz, o["typ"], o["klucz"]) or {}
        tresc = zbuduj_raport(p, o["typ"], o["klucz"], m, akt, m_poprz,
                              zapisany.get("ocena"), b.pamiec(klucz, limit=10), grupy)
        return Response(
            tresc, mimetype="text/markdown; charset=utf-8",
            headers={"Content-Disposition":
                     f'attachment; filename="{klucz}_{o["typ"]}_{o["klucz"]}.md"'},
        )

    # --- organizacja ------------------------------------------------------

    @app.route("/organizacja")
    def organizacja():
        b = baza()
        return render_template(
            "organizacja.html",
            biura=b.biura(),
            pracownicy=b.pracownicy(tylko_aktywni=False),
            liczby={bi.id: len(b.pracownicy(biuro_id=bi.id)) for bi in b.biura()},
            opisy_rol=OPIS_ROL,
        )

    @app.post("/organizacja/biuro")
    def zapisz_biuro():
        b = baza()
        nazwa = (request.form.get("nazwa") or "").strip()
        if not nazwa:
            flash("Biuro musi mieć nazwę.", "blad")
            return redirect(url_for("organizacja"))
        try:
            b.zapisz_biuro(Biuro(
                id=int(request.form["id"]) if request.form.get("id") else None,
                nazwa=nazwa,
                miasto=(request.form.get("miasto") or "").strip(),
                adres=(request.form.get("adres") or "").strip(),
                uwagi=(request.form.get("uwagi") or "").strip(),
            ))
            flash(f"Zapisano biuro „{nazwa}”.", "ok")
        except Exception:  # noqa: BLE001 — najczęściej duplikat nazwy
            flash(f"Biuro o nazwie „{nazwa}” już istnieje.", "blad")
        return redirect(url_for("organizacja"))

    @app.post("/organizacja/biuro/<int:biuro_id>/usun")
    def usun_biuro(biuro_id: int):
        b = baza()
        b.usun_biuro(biuro_id)
        flash("Biuro usunięte. Pracownicy trafili do puli bez przypisania.", "ok")
        return redirect(url_for("organizacja"))

    @app.post("/organizacja/pracownik/<klucz>")
    def zapisz_pracownika(klucz: str):
        b = baza()
        p = b.pracownik_lub_domyslny(klucz)
        biuro = request.form.get("biuro_id") or ""
        p.biuro_id = int(biuro) if biuro.isdigit() else None
        p.rola = request.form.get("rola") or p.rola
        p.imie_nazwisko = (request.form.get("imie_nazwisko") or p.imie_nazwisko).strip()
        staz = request.form.get("staz_miesiace") or ""
        p.staz_miesiace = int(staz) if staz.isdigit() else p.staz_miesiace
        norma = request.form.get("norma_dzienna") or ""
        if norma.isdigit():
            p.normy.setdefault("dzien", {})["aktywnosci"] = int(norma)
        obszar = (request.form.get("obszar") or "").strip()
        if obszar:
            p.obszar_farmingu = [x.strip() for x in obszar.split(",") if x.strip()]
        p.uwagi_managera = (request.form.get("uwagi") or "").strip()
        p.aktywny = request.form.get("aktywny") == "1"
        b.zapisz_pracownika(p)
        flash(f"Zapisano: {p.imie_nazwisko}.", "ok")
        return redirect(url_for("organizacja"))

    # --- wczytywanie danych ----------------------------------------------

    @app.route("/wczytaj", methods=["GET", "POST"])
    def wczytaj():
        b = baza()
        if request.method == "GET":
            return render_template("wczytaj.html", zrodla=_ostatnie_zrodla(b))

        pliki = [f for f in request.files.getlist("pliki") if f and f.filename]
        if not pliki:
            flash("Nie wybrano żadnego pliku.", "blad")
            return redirect(url_for("wczytaj"))

        podsumowania = []
        for plik in pliki:
            suffix = Path(plik.filename).suffix.lower()
            try:
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                    plik.save(tmp.name)
                    sciezka = Path(tmp.name)
                akt = sklasyfikuj(wczytaj_plik(sciezka))
                for a in akt:  # w bazie ma zostać nazwa oryginalna, nie tymczasowa
                    a.zrodlo = plik.filename
                nowe, dupl = b.zapisz_aktywnosci(akt)
                podsumowania.append(f"{plik.filename}: {nowe} nowych, {dupl} duplikatów")
            except Exception as e:  # noqa: BLE001 — komunikat dla użytkownika
                podsumowania.append(f"{plik.filename}: BŁĄD — {e}")
            finally:
                sciezka.unlink(missing_ok=True)

        nowi = b.synchronizuj_pracownikow()
        flash(" · ".join(podsumowania), "ok")
        if nowi:
            flash(f"Wykryto {nowi} nową osobę/osoby — przypisz je do biur.", "uwaga")
            return redirect(url_for("organizacja"))
        return redirect(url_for("pulpit"))

    return app


# --- pomocnicze -----------------------------------------------------------

def _powrot(domyslny: str) -> str:
    """Wraca na tę samą zakładkę okresu, z której przyszło żądanie."""
    okres = request.form.get("okres") or request.args.get("okres")
    klucz = request.form.get("klucz") or request.args.get("klucz")
    if okres and klucz:
        return f"{domyslny}?okres={okres}&klucz={klucz}"
    return domyslny


def _szereg_dzienny(aktywnosci, o: dict) -> list[tuple[str, int]]:
    """Aktywność dzień po dniu — dla okresów dłuższych niż jeden dzień."""
    if o["typ"] == "dzien" or not aktywnosci:
        return []
    licznik: dict[str, int] = {}
    for a in aktywnosci:
        licznik[a.dzien] = licznik.get(a.dzien, 0) + 1
    return [(d[8:10] + "." + d[5:7], n) for d, n in sorted(licznik.items())]


def _zespol_wg_rol(zespol, per_prac: dict) -> list[dict]:
    grupy = []
    for rola in ROLE:
        osoby = [p for p in zespol if p.rola == rola]
        if not osoby:
            continue
        grupy.append({
            "rola": rola,
            "nazwa": NAZWY_ROL[rola],
            "osoby": [(p, per_prac.get(p.klucz, {})) for p in osoby],
        })
    return grupy


def _ostatnie_zrodla(b: Baza, limit: int = 12) -> list[dict]:
    sql = """SELECT zrodlo, COUNT(*) n, MIN(dzien) od, MAX(dzien) do, MAX(wczytano) kiedy
             FROM aktywnosci GROUP BY zrodlo ORDER BY kiedy DESC LIMIT ?"""
    return [dict(r) for r in b.con.execute(sql, (limit,))]


def uruchom(sciezka_bazy: str = "data/analityk.db", host: str = "127.0.0.1",
            port: int = 5000, debug: bool = False) -> None:
    app = stworz_aplikacje(sciezka_bazy)
    print(f"\n  Panel działa: http://{host}:{port}\n  Baza: {sciezka_bazy}\n"
          f"  Zatrzymanie: Ctrl+C\n")
    app.run(host=host, port=port, debug=debug)
