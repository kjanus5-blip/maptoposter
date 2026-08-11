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
    suma_norm,
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
from ..konfiguracja import czy_jest_klucz, sciezka_env
from ..org import NAZWY_ROL, OPIS_ROL, ROLE, Biuro
from ..punktacja import (
    KOD_POMIJANY,
    LICZNIKI_OPERACYJNE,
    _pasuje_wzorzec,
    _reguly,
    MAPOWANIE_DOMYSLNE,
    WSKAZNIKI,
    WSKAZNIKI_POMOCNICZE,
    dopisz_punkty,
    licznosci_okresu,
    niezmapowane_typy,
    wskazniki_dla_roli,
)
from ..pdf import BrakSilnikaPDF, czym_zrobimy_pdf, html_do_pdf
from ..raport_html import zbuduj_raport_html
from ..report import ETYKIETY_WYNIKOW, zbuduj_raport
from ..zadania import (
    NAZWY_ZADAN,
    STATUS_ANULOWANE,
    STATUS_ZROBIONE,
    dostepne_etykiety,
    obserwacje,
    opis_etykiety,
    wykryj_w_aktywnosciach,
)
from ..store import Baza
from .. import charts

NAZWY_OKRESOW = {
    "dzien": "Dzień", "tydzien": "Tydzień", "miesiac": "Miesiąc",
    "kwartal": "Kwartał", "rok": "Rok",
}

#: Ile notatek pokazujemy od razu; `limit=0` w adresie zdejmuje ograniczenie.
DOMYSLNY_LIMIT_NOTATEK = 50


def _data_pl(iso: str) -> str:
    """'2026-08-11T09:12:00' -> '11.08.2026'."""
    if not iso:
        return ""
    try:
        return date.fromisoformat(iso[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return iso


def _wiek_dni(iso: str) -> int:
    if not iso:
        return 0
    try:
        return (date.today() - date.fromisoformat(iso[:10])).days
    except ValueError:
        return 0


def stworz_aplikacje(sciezka_bazy: str = "data/analityk.db") -> Flask:
    app = Flask(__name__)
    app.secret_key = secrets.token_hex(16)
    app.config["SCIEZKA_BAZY"] = sciezka_bazy
    app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024
    app.jinja_env.filters["etykieta"] = opis_etykiety
    app.jinja_env.filters["data_pl"] = _data_pl
    app.jinja_env.filters["wiek_dni"] = _wiek_dni

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

    def dostepne_okresy(b: Baza, typ: str, biezacy: str) -> list[tuple[str, str]]:
        """Okresy danego typu, w których są jakieś dane — od najnowszego.

        Bieżący dopisujemy zawsze, nawet pusty: inaczej lista wyboru
        pokazywałaby co innego niż to, co widać na ekranie.
        """
        klucze = {klucz_okresu(date.fromisoformat(d), typ) for d in b.dni_z_danymi()}
        klucze.add(biezacy)
        return [(k, etykieta_okresu(k, typ)) for k in sorted(klucze, reverse=True)]

    @app.context_processor
    def globalne():
        o = kontekst_okresu()
        return {
            "okres": o,
            "okresy_do_wyboru": dostepne_okresy(baza(), o["typ"], o["klucz"]),
            "nazwy_rol": NAZWY_ROL,
            "role": ROLE,
            "dzis": date.today().isoformat(),
            "jest_klucz_api": czy_jest_klucz(),
            "silnik_pdf": czym_zrobimy_pdf(),
            "sciezka_env": str(sciezka_env()),
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
        # norma całej sieci to suma norm ludzi — bez tego zbiorczy indeks
        # porównywał pracę wszystkich do normy jednej osoby
        lacznie = podsumowanie(wszystkie_akt, o["typ"], suma_norm(wszyscy),
                               zakres=(o["od"], o["do"]))

        # alerty dostają datę pierwszego pojawienia się; zarchiwizowane
        # chowamy, ale nadal da się je wywołać z tej samej strony
        pokaz_archiwum = request.args.get("archiwum") == "1"
        ostrzezenia, zarchiwizowane = [], []
        for k, m in per_prac.items():
            for a in b.zarejestruj_alerty(k, o["typ"], o["klucz"], alerty(m)):
                (zarchiwizowane if a["zarchiwizowany"] else ostrzezenia).append(
                    (dane_prac[k], a)
                )
        return render_template(
            "pulpit.html",
            lacznie=lacznie,
            biura=ranking_biur(b, o["typ"], o["klucz"]),
            ranking=[(dane_prac[k], per_prac[k], ind)
                     for k, ind, _ in ranking_zespolu(per_prac)],
            bez_wynikow=[p for p in wszyscy if per_prac[p.klucz].get("pusty")],
            ostrzezenia=ostrzezenia,
            zarchiwizowane=zarchiwizowane,
            pokaz_archiwum=pokaz_archiwum,
            nieprzypisani=b.nieprzypisani(),
            wykres_dni=_wykres_dni(wszystkie_akt, o),
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
            alerty=[a for a in b.zarejestruj_alerty(
                klucz, o["typ"], o["klucz"], alerty(m, m_poprz))
                if not a["zarchiwizowany"]],
            pamiec=b.pamiec(klucz, limit=12),
            zadania=b.zadania(pracownik=klucz, status="otwarte"),
            nazwy_zadan=NAZWY_ZADAN,
            leady=[a for a in akt if a.wynik in (WYNIK_LEAD, WYNIK_SYGNAL)],
            rynek=[a for a in akt if a.wynik == WYNIK_INFO_RYNKOWE],
            ocena=(zapisany or {}).get("ocena"),
            zakladki=_zakladki(b, klucz, o),
            wskaznik=charts.wskaznik(m.get("indeks_jakosci", 0), etykieta="indeks jakości"),
            wykres_godzin=charts.slupki(
                [(f"{g}", n) for g, n in (m.get("rozklad_godzinowy") or {}).items()]
            ),
            wykres_dni=_wykres_dni(akt, o),
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

    def _zakladki(b: Baza, klucz: str, o: dict) -> dict:
        """Liczniki przy zakładkach karty pracownika.

        Zadania celowo idą bez filtra okresu — follow-up sprzed dwóch tygodni
        nadal jest do zrobienia, choćby ekran pokazywał bieżący tydzień.
        """
        akt = b.pobierz(pracownik=klucz, od=o["od"], do=o["do"])
        oceny = b.oceny_notatek()
        return {
            "zadania": len(b.zadania(pracownik=klucz, status="otwarte")),
            "tematy": sum(1 for ob in obserwacje(akt)
                          if oceny.get(ob["aktywnosc"].id, {}).get("status", "nowa") == "nowa"),
        }

    @app.route("/pracownik/<klucz>/zadania")
    def zadania_pracownika(klucz: str):
        b = baza()
        o = kontekst_okresu()
        p = b.pracownik_lub_domyslny(klucz)
        status = request.args.get("status") or "otwarte"
        lista = b.zadania(pracownik=klucz, status=status)
        return render_template(
            "pracownik_zadania.html",
            p=p, koszyki=_koszyki_zadan(lista), razem=len(lista), status=status,
            nazwy_zadan=NAZWY_ZADAN, zakladki=_zakladki(b, klucz, o),
        )

    @app.route("/pracownik/<klucz>/tematy")
    def tematy_pracownika(klucz: str):
        b = baza()
        o = kontekst_okresu()
        p = b.pracownik_lub_domyslny(klucz)
        status = request.args.get("status") or "nowa"
        akt = b.pobierz(pracownik=klucz, od=o["od"], do=o["do"])
        oceny = b.oceny_notatek()

        wszystkie = obserwacje(akt)
        for ob in wszystkie:
            ocena = oceny.get(ob["aktywnosc"].id, {})
            ob["status"] = ocena.get("status", "nowa")
            ob["komentarz"] = ocena.get("komentarz", "")
        liczniki = {"wszystkie": len(wszystkie)}
        for nazwa in ("nowa", "zaakceptowana", "odrzucona"):
            liczniki[nazwa] = sum(1 for ob in wszystkie if ob["status"] == nazwa)

        lista = (wszystkie if status == "wszystkie"
                 else [ob for ob in wszystkie if ob["status"] == status])
        return render_template(
            "pracownik_tematy.html",
            p=p, lista=lista, liczniki=liczniki, wybrany_status=status,
            zakladki=_zakladki(b, klucz, o),
        )

    @app.route("/pracownik/<klucz>/raport.html")
    def raport_html(klucz: str):
        """Ładny, samodzielny raport do wydruku albo zapisania do PDF."""
        b = baza()
        o = kontekst_okresu()
        p = b.pracownik_lub_domyslny(klucz)
        akt, m = metryki_pracownika(b, p, o["typ"], o["klucz"])
        _, m_poprz = metryki_pracownika(b, p, o["typ"], o["poprzedni"])
        grupy = [] if m.get("pusty") else grupy_porownawcze(b, p, o["typ"], o["klucz"], m)
        zapisany = b.raport(klucz, o["typ"], o["klucz"]) or {}
        tresc = zbuduj_raport_html(
            p, o["typ"], o["klucz"], m, akt, m_poprz, zapisany.get("ocena"),
            b.pamiec(klucz, limit=10), grupy, etykieta_okresu_=o["etykieta"],
        )
        if request.args.get("pobierz") == "1":
            return Response(tresc, mimetype="text/html; charset=utf-8", headers={
                "Content-Disposition":
                    f'attachment; filename="{klucz}_{o["typ"]}_{o["klucz"]}.html"'})
        return Response(tresc, mimetype="text/html; charset=utf-8")

    @app.route("/pracownik/<klucz>/raport.pdf")
    def raport_pdf(klucz: str):
        """Gotowy plik PDF — bez przechodzenia przez okno druku."""
        b = baza()
        o = kontekst_okresu()
        p = b.pracownik_lub_domyslny(klucz)
        akt, m = metryki_pracownika(b, p, o["typ"], o["klucz"])
        _, m_poprz = metryki_pracownika(b, p, o["typ"], o["poprzedni"])
        grupy = [] if m.get("pusty") else grupy_porownawcze(b, p, o["typ"], o["klucz"], m)
        zapisany = b.raport(klucz, o["typ"], o["klucz"]) or {}
        html = zbuduj_raport_html(
            p, o["typ"], o["klucz"], m, akt, m_poprz, zapisany.get("ocena"),
            b.pamiec(klucz, limit=10), grupy, etykieta_okresu_=o["etykieta"],
        )
        try:
            dane = html_do_pdf(html)
        except BrakSilnikaPDF as e:
            # Wracamy na kartę pracownika, a nie na sam raport: raport jest
            # samodzielną stroną i nie wyświetla komunikatów panelu, więc
            # użytkownik zobaczyłby tylko, że „nic się nie stało”.
            flash(str(e), "blad")
            # `klucz` w adresie to pracownik, więc klucz okresu doklejamy
            # ręcznie — tak samo robi makro `q()` w szablonach.
            return redirect(url_for("widok_pracownika", klucz=klucz,
                                    okres=o["typ"]) + f"&klucz={o['klucz']}")
        return Response(dane, mimetype="application/pdf", headers={
            "Content-Disposition":
                f'attachment; filename="{klucz}_{o["typ"]}_{o["klucz"]}.pdf"'})

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

    # --- zadania i tematy -------------------------------------------------

    @app.route("/zadania")
    def widok_zadan():
        b = baza()
        pracownik = request.args.get("pracownik") or None
        strona = request.args.get("strona") or None
        status = request.args.get("status") or "otwarte"
        lista = b.zadania(pracownik=pracownik, status=status, strona=strona)
        koszyki = _koszyki_zadan(lista)

        return render_template(
            "zadania.html",
            koszyki=koszyki,
            razem=len(lista),
            status=status,
            strona=strona,
            wybrany_pracownik=pracownik,
            pracownicy=b.pracownicy(),
            nazwy_zadan=NAZWY_ZADAN,
        )

    @app.post("/zadania/<path:id_zadania>/status")
    def zmien_status_zadania(id_zadania: str):
        b = baza()
        nowy = request.form.get("status", STATUS_ZROBIONE)
        if nowy not in (STATUS_ZROBIONE, STATUS_ANULOWANE, "otwarte"):
            nowy = STATUS_ZROBIONE
        b.ustaw_status_zadania(id_zadania, nowy)
        flash("Zadanie odhaczone." if nowy == STATUS_ZROBIONE else "Status zmieniony.", "ok")
        return redirect(request.form.get("powrot") or url_for("widok_zadan"))

    @app.post("/zadania/przelicz")
    def przelicz_zadania():
        """Ponowne wykrycie zadań ze wszystkich notatek — statusy zostają."""
        b = baza()
        zadania = wykryj_w_aktywnosciach(b.pobierz())
        nowe, odswiezone = b.zapisz_zadania(zadania)
        flash(f"Wykryto {len(zadania)} zadań: {nowe} nowych, {odswiezone} odświeżonych.", "ok")
        return redirect(url_for("widok_zadan"))

    @app.route("/tematy")
    def widok_tematow():
        """Notatka po notatce — każda do zaakceptowania albo odrzucenia.

        Wcześniej strona grupowała notatki po temacie i pokazywała po kilka
        przykładów. Do liczenia to było dobre, do pracy nie: nie dało się
        odhaczyć pojedynczej notatki ani zobaczyć reszty listy.
        """
        b = baza()
        o = kontekst_okresu()
        pracownik = request.args.get("pracownik") or None
        etykieta = request.args.get("etykieta") or ""
        status = request.args.get("status") or "nowa"
        akt = b.pobierz(pracownik=pracownik, od=o["od"], do=o["do"])

        oceny = b.oceny_notatek()
        wszystkie = obserwacje(akt)
        for ob in wszystkie:
            ocena = oceny.get(ob["aktywnosc"].id, {})
            ob["status"] = ocena.get("status", "nowa")
            ob["komentarz"] = ocena.get("komentarz", "")

        # liczniki statusów liczymy przed filtrem, żeby zakładki nie znikały
        liczniki = {"wszystkie": len(wszystkie)}
        for nazwa in ("nowa", "zaakceptowana", "odrzucona"):
            liczniki[nazwa] = sum(1 for ob in wszystkie if ob["status"] == nazwa)

        lista = wszystkie
        if status != "wszystkie":
            lista = [ob for ob in lista if ob["status"] == status]
        if etykieta:
            lista = [ob for ob in lista if etykieta in ob["etykiety"]]

        # domyślnie skracamy listę, ale zawsze da się ją rozwinąć do końca
        limit = request.args.get("limit", type=int) or DOMYSLNY_LIMIT_NOTATEK
        widoczne = lista if limit <= 0 else lista[:limit]
        return render_template(
            "tematy.html",
            lista=widoczne,
            ile_pasujacych=len(lista),
            liczniki=liczniki,
            limit=limit,
            etykiety=dostepne_etykiety(akt),
            wybrana_etykieta=etykieta,
            wybrany_status=status,
            ile_aktywnosci=len(akt),
            pracownicy=b.pracownicy(),
            wybrany_pracownik=pracownik,
        )

    @app.route("/tematy/zaakceptowane")
    def widok_zaakceptowanych():
        """Robocza lista tego, co przeszło przez akceptację.

        Celowo bez filtra okresu: zaakceptowana notatka to zadanie do
        obrobienia, a nie statystyka miesiąca — nie może zniknąć tylko
        dlatego, że u góry przełączono tydzień.
        """
        b = baza()
        oceny = b.oceny_notatek("zaakceptowana")
        aktywnosci = b.aktywnosci_po_id(list(oceny))
        lista = obserwacje(list(aktywnosci.values()))
        for ob in lista:
            ob["status"] = "zaakceptowana"
            ob["komentarz"] = oceny.get(ob["aktywnosc"].id, {}).get("komentarz", "")
        # notatka mogła stracić etykiety po zmianie reguł — i tak ją pokazujemy
        znane = {ob["aktywnosc"].id for ob in lista}
        for id_akt, a in aktywnosci.items():
            if id_akt not in znane:
                lista.append({"aktywnosc": a, "etykiety": [], "status": "zaakceptowana",
                              "komentarz": oceny.get(id_akt, {}).get("komentarz", "")})
        return render_template("tematy_zaakceptowane.html", lista=lista)

    @app.post("/tematy/notatka/<path:aktywnosc_id>/ocena")
    def ocen_notatke(aktywnosc_id: str):
        b = baza()
        status = request.form.get("status", "zaakceptowana")
        if status not in ("nowa", "zaakceptowana", "odrzucona"):
            status = "nowa"
        b.ustaw_ocene_notatki(aktywnosc_id, status, request.form.get("komentarz"))
        flash({"zaakceptowana": "Notatka trafiła do zaakceptowanych.",
               "odrzucona": "Notatka odrzucona.",
               "nowa": "Notatka wróciła do przeglądu."}[status], "ok")
        return redirect(request.form.get("powrot") or url_for("widok_tematow"))

    @app.route("/typy")
    def widok_typow():
        """Mapowanie typów aktywności z CRM na wskaźniki punktacji."""
        b = baza()
        zapisane = b.mapowanie_typow()
        if not zapisane:                       # pierwsze wejście: zasiej domyślne
            _zasiej_domyslne(b)
            zapisane = b.mapowanie_typow()

        typy = b.wystepujace_typy()
        braki = {(t["kanal"], t["podtyp"]) for t in niezmapowane_typy(typy, zapisane)}
        reguly = _reguly(zapisane)
        for t in typy:
            t["nieprzypisany"] = (t["kanal"], t["podtyp"]) in braki
            typ_tekst = (t["podtyp"] or t["kanal"] or "").lower()
            pasujace = [
                r for r in reguly
                if _pasuje_wzorzec(typ_tekst, r.wzorzec)
                and (not r.kanal or r.kanal == (t["kanal"] or "").lower())
            ]
            t["kod"] = pasujace[0].kod if pasujace else ""
            # gdy para trafia do różnych wskaźników zależnie od warunku, powiedz to wprost
            t["kody"] = sorted({r.kod for r in pasujace})
            t["warunkowy"] = len(t["kody"]) > 1
        return render_template(
            "typy.html",
            typy=typy,
            mapowanie=zapisane,
            wskazniki=WSKAZNIKI,
            liczniki=LICZNIKI_OPERACYJNE,
            kod_pomijany=KOD_POMIJANY,
            kanaly=sorted({t["kanal"] for t in typy if t["kanal"]}),
            nieprzypisanych=len(braki),
        )

    @app.post("/typy/przywroc")
    def przywroc_domyslne_mapowanie():
        """Nadpisuje reguły domyślne aktualnymi z kodu, zostawiając Twoje własne.

        Potrzebne po aktualizacji programu: reguły siedzą w bazie, więc nowe
        wartości z kodu same by do niej nie trafiły.
        """
        b = baza()
        wlasne = {w for w, d in b.mapowanie_typow().items() if d["zrodlo"] != "domyslne"}
        for wzorzec, dane in b.mapowanie_typow().items():
            if dane["zrodlo"] == "domyslne":
                b.ustaw_mapowanie(wzorzec, "")          # skasuj stare domyślne
        ile = _zasiej_domyslne(b)
        flash(
            f"Przywrócono {ile} reguł domyślnych."
            + (f" Twoje własne reguły ({len(wlasne)}) zostały nietknięte." if wlasne else ""),
            "ok",
        )
        return redirect(url_for("widok_typow"))

    @app.post("/typy/zapisz")
    def zapisz_mapowanie():
        b = baza()
        wzorzec = (request.form.get("wzorzec") or "").strip()
        kod = (request.form.get("kod") or "").strip()
        if not wzorzec:
            flash("Podaj fragment nazwy typu, np. „ricerca”.", "blad")
            return redirect(url_for("widok_typow"))
        warunek = (request.form.get("warunek") or "").strip()
        kanal = (request.form.get("kanal") or "").strip()
        klucz = "|".join(
            x.lower() for x in (wzorzec, warunek, kanal) if x
        ) or wzorzec.lower()
        b.ustaw_mapowanie(klucz, kod, request.form.get("opis", ""),
                          warunek=warunek, kanal=kanal)
        if not kod:
            flash(f"Usunięto regułę dla „{wzorzec}”.", "ok")
        else:
            dodatki = []
            if kanal:
                dodatki.append(f"kanał „{kanal}”")
            if warunek:
                dodatki.append(f"warunek „{warunek}”")
            opis = f" ({', '.join(dodatki)})" if dodatki else ""
            flash(f"Zapisano: „{wzorzec}”{opis} → {kod}.", "ok")
        return redirect(url_for("widok_typow"))

    @app.post("/alert/<path:klucz>/archiwizuj")
    def archiwizuj_alert(klucz: str):
        b = baza()
        do_archiwum = request.form.get("przywroc") != "1"
        b.archiwizuj_alert(klucz, do_archiwum)
        flash("Alert zarchiwizowany." if do_archiwum else "Alert przywrócony.", "ok")
        return redirect(request.form.get("powrot") or url_for("pulpit"))

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
        # Biuro mogło zostać usunięte w innej zakładce — bez sprawdzenia
        # zapis leci na klucz obcy i użytkownik dostaje pustą stronę błędu.
        p.biuro_id = int(biuro) if biuro.isdigit() else None
        if p.biuro_id is not None and b.biuro(p.biuro_id) is None:
            p.biuro_id = None
            flash("Wybrane biuro już nie istnieje — osoba została bez przypisania.", "uwaga")
        p.rola = request.form.get("rola") or p.rola
        p.imie_nazwisko = (request.form.get("imie_nazwisko") or p.imie_nazwisko).strip()
        zatrudniony = (request.form.get("zatrudniony_od") or "").strip()
        p.zatrudniony_od = zatrudniony        # staż wyliczy się z tej daty
        staz = request.form.get("staz_miesiace") or ""
        if not zatrudniony and staz.isdigit():
            p.staz_miesiace = int(staz)
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

    @app.post("/organizacja/pracownik/<klucz>/usun")
    def usun_pracownika(klucz: str):
        b = baza()
        osoba = b.pracownik(klucz)
        nazwa = osoba.imie_nazwisko if osoba else klucz
        z_danymi = request.form.get("z_danymi") == "1"
        licznik = b.usun_pracownika(klucz, z_danymi=z_danymi)
        if z_danymi:
            flash(
                f"Usunięto {nazwa} wraz z danymi: {licznik['aktywnosci']} aktywności, "
                f"{licznik['zadania']} zadań, {licznik['raporty']} raportów.", "ok",
            )
        else:
            flash(
                f"Usunięto wpis {nazwa}. Aktywności zostały w bazie — osoba wróci "
                "na listę przy najbliższym wczytaniu pliku.", "uwaga",
            )
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
                zadan, _ = b.zapisz_zadania(wykryj_w_aktywnosciach(akt))
                podsumowania.append(
                    f"{plik.filename}: {nowe} nowych, {dupl} duplikatów, {zadan} zadań"
                )
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

def _zasiej_domyslne(b: Baza) -> int:
    """Wgrywa do bazy komplet reguł domyślnych z `punktacja.MAPOWANIE_DOMYSLNE`."""
    for wzorzec, kanal, warunek, kod, opis in MAPOWANIE_DOMYSLNE:
        klucz = "|".join(x for x in (wzorzec, warunek, kanal) if x) or wzorzec
        b.ustaw_mapowanie(klucz, kod, opis, zrodlo="domyslne",
                          warunek=warunek, kanal=kanal)
    return len(MAPOWANIE_DOMYSLNE)

def _powrot(domyslny: str) -> str:
    """Wraca na tę samą zakładkę okresu, z której przyszło żądanie."""
    okres = request.form.get("okres") or request.args.get("okres")
    klucz = request.form.get("klucz") or request.args.get("klucz")
    if okres and klucz:
        return f"{domyslny}?okres={okres}&klucz={klucz}"
    return domyslny


def _koszyki_zadan(lista) -> dict[str, list]:
    """Zadania w koszykach terminowych — od przeterminowanych po bezterminowe."""
    dzis = date.today()

    def koszyk(z):
        if not z.termin:
            return "bez_terminu"
        termin = date.fromisoformat(z.termin)
        if termin < dzis:
            return "po_terminie"
        if termin == dzis:
            return "dzis"
        if (termin - dzis).days <= 7:
            return "ten_tydzien"
        return "pozniej"

    koszyki: dict[str, list] = {k: [] for k in
                                ("po_terminie", "dzis", "ten_tydzien",
                                 "pozniej", "bez_terminu")}
    for z in lista:
        koszyki[koszyk(z)].append(z)
    return koszyki


def _szereg_dzienny(aktywnosci, o: dict) -> list[tuple[str, int]]:
    """Aktywność dzień po dniu — dla okresów dłuższych niż jeden dzień."""
    if o["typ"] == "dzien" or not aktywnosci:
        return []
    licznik: dict[str, int] = {}
    for a in aktywnosci:
        licznik[a.dzien] = licznik.get(a.dzien, 0) + 1
    return [(d[8:10] + "." + d[5:7], n) for d, n in sorted(licznik.items())]


def _wykres_dni(aktywnosci, o: dict) -> str:
    """Pusty ciąg zamiast wykresu, gdy nie ma czego rysować.

    `slupki([])` zwraca napis „Brak danych do wykresu”, a szablon traktował go
    jak gotowy wykres — przy widoku jednego dnia zostawała karta z komunikatem
    o braku danych, mimo że danych było pod dostatkiem.
    """
    szereg = _szereg_dzienny(aktywnosci, o)
    return charts.slupki(szereg) if szereg else ""


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
