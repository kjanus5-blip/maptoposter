#!/usr/bin/env python3
"""Real estate agent daily/weekly activity planner generator."""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import matplotlib.gridspec as gridspec
from datetime import datetime, timedelta, date
import argparse
import os
from pathlib import Path

PLANNERS_DIR = "planners"

# --------------------------------------------------------------------------- #
# Activity categories
# --------------------------------------------------------------------------- #
ACTIVITIES = {
    "prospecting":      {"label": "Prospekting / Telefony",       "color": "#E07B39"},
    "client_meeting":   {"label": "Spotkanie z klientem",         "color": "#3A7EC6"},
    "property_viewing": {"label": "Prezentacja nieruchomości",     "color": "#4CAF6E"},
    "open_house":       {"label": "Dzień otwarty",                 "color": "#D94F4F"},
    "admin":            {"label": "Administracja / Umowy",         "color": "#888888"},
    "marketing":        {"label": "Marketing / Social Media",      "color": "#8E44AD"},
    "networking":       {"label": "Networking",                    "color": "#C0187A"},
    "team_meeting":     {"label": "Spotkanie zespołu",             "color": "#C8A000"},
    "research":         {"label": "Analiza rynku",                 "color": "#17A589"},
    "personal":         {"label": "Rozwój osobisty",               "color": "#5DADE2"},
}

DAYS_PL = [
    "Poniedziałek", "Wtorek", "Środa",
    "Czwartek", "Piątek", "Sobota", "Niedziela",
]

# --------------------------------------------------------------------------- #
# Sample schedules
# --------------------------------------------------------------------------- #
# Day index → list of (h_start, h_end, activity_key, label)
SAMPLE_WEEKLY: dict[int, list[tuple]] = {
    0: [
        (8.0,  9.0,  "team_meeting",     "Spotkanie poranne"),
        (9.0,  11.0, "prospecting",      "Zimne telefony – nowi klienci"),
        (11.0, 12.0, "marketing",        "Posty social media"),
        (13.0, 15.0, "client_meeting",   "Spotkanie z kupującym"),
        (15.0, 17.0, "property_viewing", "Prezentacja – Marszałkowska 5"),
        (17.0, 18.0, "admin",            "Raport dzienny"),
    ],
    1: [
        (8.0,  9.0,  "research",         "Analiza nowych ofert"),
        (9.0,  11.0, "prospecting",      "Follow-up – leady"),
        (11.0, 13.0, "property_viewing", "Prezentacja – os. Kabaty"),
        (14.0, 15.5, "client_meeting",   "Negocjacje – Kowalski"),
        (15.5, 17.0, "admin",            "Przygotowanie umowy"),
        (17.0, 18.0, "marketing",        "Portale ogłoszeniowe"),
    ],
    2: [
        (8.0,  10.0, "prospecting",      "Zimne telefony – Mokotów"),
        (10.0, 12.0, "property_viewing", "Przegląd ofert rynkowych"),
        (12.0, 13.0, "research",         "Ceny transakcyjne"),
        (14.0, 16.0, "client_meeting",   "Spotkanie ze sprzedającym"),
        (16.0, 18.0, "networking",       "Spotkanie branżowe PFRN"),
    ],
    3: [
        (8.0,  9.0,  "admin",            "Planowanie i organizacja"),
        (9.0,  11.0, "marketing",        "Email marketing – baza klientów"),
        (11.0, 13.0, "property_viewing", "Wilanów – 3 obiekty"),
        (14.0, 15.0, "client_meeting",   "Omówienie oferty"),
        (15.0, 17.0, "admin",            "Dokumentacja i umowy"),
        (17.0, 18.0, "personal",         "Szkolenie online"),
    ],
    4: [
        (8.0,  9.0,  "research",         "Przegląd tygodniowy rynku"),
        (9.0,  11.0, "prospecting",      "Reaktywacja starych leadów"),
        (11.0, 12.0, "admin",            "Faktury i rozliczenia"),
        (13.0, 15.0, "property_viewing", "Prezentacje – Śródmieście"),
        (15.0, 16.0, "client_meeting",   "Podsumowanie tygodnia"),
        (16.0, 17.0, "marketing",        "Plan kampanii na przyszły tydzień"),
    ],
    5: [
        (9.0,  13.0, "open_house",       "Dzień Otwarty – Puławska 88"),
        (13.0, 15.0, "client_meeting",   "Kupujący po Dniu Otwartym"),
        (15.0, 16.0, "admin",            "Notatki po Dniu Otwartym"),
    ],
    6: [
        (10.0, 12.0, "personal",         "Lektura branżowa"),
        (12.0, 13.0, "marketing",        "Planowanie postów na tydzień"),
    ],
}

# list of (h_start, h_end, activity_key, label)
SAMPLE_DAILY: list[tuple] = [
    (7.0,  8.0,  "personal",         "Poranna rutyna i przegląd emaili"),
    (8.0,  9.0,  "team_meeting",     "Spotkanie poranne z biurem"),
    (9.0,  11.0, "prospecting",      "Zimne telefony – min. 20 kontaktów"),
    (11.0, 12.0, "marketing",        "Social media i nowe ogłoszenia"),
    (12.0, 13.0, "admin",            "Lunch i korespondencja"),
    (13.0, 15.0, "client_meeting",   "Spotkanie – prezentacja oferty"),
    (15.0, 17.0, "property_viewing", "Prezentacje nieruchomości (2 obiekty)"),
    (17.0, 18.0, "research",         "Analiza rynku i raport"),
    (18.0, 19.0, "admin",            "Dokumentacja i plan na jutro"),
]

KPI_TARGETS = [
    ("Zimne telefony",    "20 / dzień"),
    ("Prezentacje",       "3–5 / tydz."),
    ("Nowe oferty",       "5 / tydz."),
    ("Follow-upy",        "10 / dzień"),
    ("Posty social media","1 / dzień"),
    ("Spotkania sprzedaż","2 / tydz."),
    ("Aktywne leady",     "30+"),
]

# --------------------------------------------------------------------------- #
# Colour palette
# --------------------------------------------------------------------------- #
BG          = "#F7F3EE"
HEADER_BG   = "#1E2D3D"
HEADER_TEXT = "#FFFFFF"
SUBTEXT     = "#8DAAB8"
GRID_MAJOR  = "#C8C2BA"
GRID_MINOR  = "#E2DDD6"
TIME_COL    = "#6B7B8A"
ACCENT      = "#1E2D3D"
STRIPE_EVEN = "#F0EBE4"
STRIPE_ODD  = "#EAE4DC"
WEEKEND_BG  = "#E8E0D5"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def fmt_time(h: float) -> str:
    hour = int(h)
    minute = int(round((h - hour) * 60))
    return f"{hour:02d}:{minute:02d}"


def activity_block(ax, x: float, y_start: float, width: float, duration: float,
                   color: str, label: str, time_str: str, cat_label: str) -> None:
    pad = 0.04
    rect = FancyBboxPatch(
        (x + pad, y_start + pad),
        width - 2 * pad, duration - 2 * pad,
        boxstyle="round,pad=0.015",
        facecolor=color,
        edgecolor="white",
        linewidth=1.8,
        alpha=0.92,
        zorder=3,
    )
    ax.add_patch(rect)

    cx = x + width / 2
    cy = y_start + duration / 2

    if duration >= 0.45:
        fs_main = 7.0 if duration < 0.8 else (8.5 if duration < 1.5 else 9.5)
        ax.text(cx, cy, label,
                ha="center", va="center",
                fontsize=fs_main, fontweight="bold", color="white",
                zorder=4, clip_on=True,
                multialignment="center")

    if duration >= 0.7:
        ax.text(x + pad + 0.02, y_start + pad + 0.08, time_str,
                ha="left", va="top",
                fontsize=6.5, color="white", alpha=0.80, zorder=4)

    if duration >= 1.0 and cat_label:
        ax.text(x + width - pad - 0.02, y_start + pad + 0.08, cat_label,
                ha="right", va="top",
                fontsize=6.5, color="white", alpha=0.80, style="italic", zorder=4)


# --------------------------------------------------------------------------- #
# Weekly planner
# --------------------------------------------------------------------------- #
def draw_weekly_planner(start_date: date, sample: bool, output_path: str) -> None:
    START_H, END_H = 7, 20
    N_DAYS = 7

    fig = plt.figure(figsize=(26, 15), facecolor=BG)
    gs = gridspec.GridSpec(
        2, 1,
        height_ratios=[0.07, 0.93],
        hspace=0.015,
        figure=fig,
    )

    # ── Header ──────────────────────────────────────────────────────────────
    ax_hdr = fig.add_subplot(gs[0])
    ax_hdr.set_facecolor(HEADER_BG)
    ax_hdr.axis("off")

    week_end = start_date + timedelta(days=6)
    ax_hdr.text(0.5, 0.60,
                "TYGODNIOWY PLAN AKTYWNOŚCI  ·  AGENT NIERUCHOMOŚCI",
                ha="center", va="center",
                fontsize=17, fontweight="bold", color=HEADER_TEXT,
                transform=ax_hdr.transAxes)
    ax_hdr.text(0.5, 0.18,
                f"{start_date.strftime('%d.%m')} – {week_end.strftime('%d.%m.%Y')}",
                ha="center", va="center",
                fontsize=11, color=SUBTEXT,
                transform=ax_hdr.transAxes)

    # ── Schedule grid ────────────────────────────────────────────────────────
    ax = fig.add_subplot(gs[1])
    ax.set_facecolor(BG)
    ax.set_xlim(0, N_DAYS)
    ax.set_ylim(END_H, START_H)  # inverted: morning at top

    ax.tick_params(which="both", length=0)
    ax.set_xticks([d + 0.5 for d in range(N_DAYS)])
    ax.set_xticklabels(
        [f"{DAYS_PL[d]}\n{(start_date + timedelta(days=d)).strftime('%d.%m')}"
         for d in range(N_DAYS)],
        fontsize=10.5, fontweight="bold", color=ACCENT,
    )
    ax.xaxis.tick_top()
    ax.xaxis.set_label_position("top")

    ax.set_yticks(range(START_H, END_H + 1))
    ax.set_yticklabels(
        [f"{h:02d}:00" for h in range(START_H, END_H + 1)],
        fontsize=8.5, color=TIME_COL,
    )
    for sp in ax.spines.values():
        sp.set_visible(False)

    # column stripes
    for d in range(N_DAYS):
        bg = WEEKEND_BG if d >= 5 else (STRIPE_EVEN if d % 2 == 0 else STRIPE_ODD)
        ax.axvspan(d, d + 1, facecolor=bg, zorder=0)

    # grid lines
    for h in range(START_H, END_H + 1):
        lw, ls = (0.8, "-") if h % 2 == 0 else (0.35, "--")
        clr = GRID_MAJOR if h % 2 == 0 else GRID_MINOR
        ax.axhline(h, color=clr, lw=lw, linestyle=ls, zorder=1)

    for d in range(N_DAYS + 1):
        ax.axvline(d, color=GRID_MAJOR, lw=1.0, zorder=1)

    # activity blocks
    schedule = SAMPLE_WEEKLY if sample else {i: [] for i in range(N_DAYS)}
    for day_idx, blocks in schedule.items():
        for (h_start, h_end, act_key, label) in blocks:
            act = ACTIVITIES[act_key]
            activity_block(
                ax,
                x=day_idx, y_start=h_start,
                width=1.0, duration=h_end - h_start,
                color=act["color"], label=label,
                time_str=f"{fmt_time(h_start)} – {fmt_time(h_end)}",
                cat_label=act["label"],
            )

    # legend
    patches = [mpatches.Patch(facecolor=v["color"], label=v["label"],
                               edgecolor="white", linewidth=1)
               for v in ACTIVITIES.values()]
    ax.legend(
        handles=patches,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.085),
        ncol=5, fontsize=8.5,
        frameon=True, framealpha=0.95,
        facecolor=BG, edgecolor=GRID_MAJOR,
        handlelength=1.6, handleheight=1.1,
    )

    Path(PLANNERS_DIR).mkdir(exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"Zapisano: {output_path}")


# --------------------------------------------------------------------------- #
# Daily planner
# --------------------------------------------------------------------------- #
def draw_daily_planner(target_date: date, sample: bool, output_path: str) -> None:
    START_H, END_H = 7, 20

    fig = plt.figure(figsize=(16, 22), facecolor=BG)
    gs = gridspec.GridSpec(
        3, 2,
        height_ratios=[0.065, 0.815, 0.12],
        width_ratios=[0.68, 0.32],
        hspace=0.025,
        wspace=0.035,
        figure=fig,
    )

    # ── Header ──────────────────────────────────────────────────────────────
    ax_hdr = fig.add_subplot(gs[0, :])
    ax_hdr.set_facecolor(HEADER_BG)
    ax_hdr.axis("off")

    day_name = DAYS_PL[target_date.weekday()]
    ax_hdr.text(0.5, 0.62,
                "DZIENNY PLAN AKTYWNOŚCI  ·  AGENT NIERUCHOMOŚCI",
                ha="center", va="center",
                fontsize=18, fontweight="bold", color=HEADER_TEXT,
                transform=ax_hdr.transAxes)
    ax_hdr.text(0.5, 0.18,
                f"{day_name.upper()}  ·  {target_date.strftime('%d.%m.%Y')}",
                ha="center", va="center",
                fontsize=11, color=SUBTEXT,
                transform=ax_hdr.transAxes)

    # ── Schedule (left) ──────────────────────────────────────────────────────
    ax = fig.add_subplot(gs[1, 0])
    ax.set_facecolor(BG)
    ax.set_xlim(0, 1)
    ax.set_ylim(END_H, START_H)
    ax.axis("off")

    # alternating hour bands
    for h in range(START_H, END_H):
        bg = STRIPE_EVEN if h % 2 == 0 else STRIPE_ODD
        ax.axhspan(h, h + 1, facecolor=bg, zorder=0)

    # grid & time labels
    for h in range(START_H, END_H + 1):
        lw, ls = (0.9, "-") if h % 2 == 0 else (0.35, "--")
        clr = GRID_MAJOR if h % 2 == 0 else GRID_MINOR
        ax.axhline(h, color=clr, lw=lw, linestyle=ls, xmin=0.0, xmax=1.0, zorder=1)
        ax.text(-0.015, h, f"{h:02d}:00",
                ha="right", va="center",
                fontsize=9.5, color=TIME_COL, fontweight="bold")

    # activity blocks
    schedule = SAMPLE_DAILY if sample else []
    for (h_start, h_end, act_key, label) in schedule:
        act = ACTIVITIES[act_key]
        activity_block(
            ax,
            x=0.0, y_start=h_start,
            width=1.0, duration=h_end - h_start,
            color=act["color"], label=label,
            time_str=f"{fmt_time(h_start)} – {fmt_time(h_end)}",
            cat_label=act["label"],
        )

    # ── KPI / Goals panel (right) ────────────────────────────────────────────
    ax_kpi = fig.add_subplot(gs[1, 1])
    ax_kpi.set_facecolor(BG)
    ax_kpi.set_xlim(0, 1)
    ax_kpi.set_ylim(0, 1)
    ax_kpi.axis("off")

    # section: daily KPIs
    ax_kpi.text(0.5, 0.985, "CELE DNIA", ha="center", va="top",
                fontsize=12, fontweight="bold", color=ACCENT)
    ax_kpi.axhline(0.955, color=GRID_MAJOR, lw=1.5, xmin=0.0, xmax=1.0)

    n = len(KPI_TARGETS)
    block_h = 0.048
    top = 0.940
    gap = 0.010

    for i, (name, target) in enumerate(KPI_TARGETS):
        y = top - i * (block_h + gap)
        bg = STRIPE_EVEN if i % 2 == 0 else STRIPE_ODD
        rect = FancyBboxPatch((0.0, y - block_h / 2), 1.0, block_h,
                               boxstyle="round,pad=0.008",
                               facecolor=bg, edgecolor="none", zorder=1)
        ax_kpi.add_patch(rect)
        ax_kpi.text(0.06, y, name,
                    ha="left", va="center",
                    fontsize=8.5, color=ACCENT, fontweight="bold")
        ax_kpi.text(0.94, y, target,
                    ha="right", va="center",
                    fontsize=8.5, color="#C0392B", fontweight="bold")

    # checkbox list
    check_top = top - n * (block_h + gap) - 0.04
    ax_kpi.text(0.5, check_top, "PRIORYTETY NA DZIŚ",
                ha="center", va="top",
                fontsize=11, fontweight="bold", color=ACCENT)
    ax_kpi.axhline(check_top - 0.035, color=GRID_MAJOR, lw=1.2, xmin=0.0, xmax=1.0)

    for j in range(6):
        y_c = check_top - 0.07 - j * 0.055
        ax_kpi.add_patch(FancyBboxPatch(
            (0.04, y_c - 0.014), 0.10, 0.028,
            boxstyle="round,pad=0.004",
            facecolor="white", edgecolor=GRID_MAJOR, linewidth=1, zorder=2,
        ))
        ax_kpi.axhline(y_c, color=GRID_MINOR, lw=0.8,
                       xmin=0.18, xmax=0.96, zorder=1)

    # notes section
    notes_top = check_top - 0.07 - 6 * 0.055 - 0.04
    ax_kpi.text(0.5, notes_top, "NOTATKI",
                ha="center", va="top",
                fontsize=11, fontweight="bold", color=ACCENT)
    ax_kpi.axhline(notes_top - 0.035, color=GRID_MAJOR, lw=1.2, xmin=0.0, xmax=1.0)

    for k in range(7):
        y_n = notes_top - 0.07 - k * 0.046
        if y_n < 0.01:
            break
        ax_kpi.axhline(y_n, color=GRID_MINOR, lw=0.8,
                       xmin=0.04, xmax=0.96, zorder=1)

    # ── Legend (bottom) ──────────────────────────────────────────────────────
    ax_leg = fig.add_subplot(gs[2, :])
    ax_leg.set_facecolor(BG)
    ax_leg.axis("off")

    patches = [mpatches.Patch(facecolor=v["color"], label=v["label"],
                               edgecolor="white", linewidth=1)
               for v in ACTIVITIES.values()]
    ax_leg.legend(
        handles=patches,
        loc="center",
        ncol=5, fontsize=8.5,
        frameon=True, framealpha=0.95,
        facecolor=BG, edgecolor=GRID_MAJOR,
        handlelength=1.6, handleheight=1.1,
    )

    Path(PLANNERS_DIR).mkdir(exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"Zapisano: {output_path}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generator planu aktywności agenta nieruchomości",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Przykłady użycia:
  python real_estate_planner.py --mode weekly --sample
  python real_estate_planner.py --mode daily --date 2026-05-06 --sample
  python real_estate_planner.py --mode weekly --date 2026-05-11
        """,
    )
    parser.add_argument(
        "--mode", choices=["daily", "weekly"], default="weekly",
        help="Tryb: dzienny (daily) lub tygodniowy (weekly) [domyślnie: weekly]",
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="Data YYYY-MM-DD (domyślnie: dziś / bieżący tydzień)",
    )
    parser.add_argument(
        "--sample", action="store_true",
        help="Wypełnij przykładowym harmonogramem",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Ścieżka wyjściowa PNG (domyślnie: planners/...)",
    )
    args = parser.parse_args()

    target_date = (
        datetime.strptime(args.date, "%Y-%m-%d").date()
        if args.date else date.today()
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "_sample" if args.sample else ""

    if args.mode == "weekly":
        monday = target_date - timedelta(days=target_date.weekday())
        output_path = args.output or os.path.join(
            PLANNERS_DIR,
            f"weekly_planner_{monday.strftime('%Y%m%d')}{suffix}_{timestamp}.png",
        )
        draw_weekly_planner(monday, args.sample, output_path)
    else:
        output_path = args.output or os.path.join(
            PLANNERS_DIR,
            f"daily_planner_{target_date.strftime('%Y%m%d')}{suffix}_{timestamp}.png",
        )
        draw_daily_planner(target_date, args.sample, output_path)


if __name__ == "__main__":
    main()
