#!/usr/bin/env python3
"""Build the door-to-door canvassing map for a set of streets.

    python3 d2d/build_map.py

Downloads OSM data for the area (cached), slices the chosen streets into
segments at every crossing street, attaches every addressed building to its
segment, and writes a single self-contained HTML page plus a printable SVG.
"""

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from extract import (BUILDING_SKIP, Osm, Projection, ROAD_TYPES, centroid, chain_ways,
                     clip_runs, crossing_nodes, house_int, house_key, norm, polyline_length,
                     project_on_polyline, rdp, ring_area, short_name, side_of_polyline,
                     split_chain)
from osm_fetch import fetch_bbox

HERE = os.path.dirname(os.path.abspath(__file__))

# Trójkąt / Przedmieście Oławskie, Wrocław
DEFAULT_BBOX = (51.0975, 17.038, 51.1105, 17.058)
DEFAULT_STREETS = [
    "Zygmunta Krasińskiego",
    "Generała Józefa Haukego-Bosaka",
    "Stanisława Worcella",
    "Komuny Paryskiej",
    "Podwale",
]


def collect_buildings(osm, proj):
    """Every addressed building in the data, as projected rings + metadata."""
    out = []
    for wid, (tags, refs) in osm.ways.items():
        if "building" not in tags or tags.get("building") in BUILDING_SKIP:
            continue
        number = tags.get("addr:housenumber")
        street = tags.get("addr:street")
        if not number or not street:
            continue
        ring = [proj(*osm.nodes[r]) for r in refs if r in osm.nodes]
        if len(ring) < 4:
            continue
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        out.append({
            "id": f"w{wid}",
            "street": street,
            "number": number,
            "ring": ring,
            "c": centroid(ring),
            "area": ring_area(ring),
            "levels": tags.get("building:levels"),
            "flats": tags.get("building:flats"),
            "name": tags.get("name"),
        })
    return out


def collect_context(osm, proj, view):
    """Background geometry: roads, water, railways, green areas, other buildings."""
    (x0, y0, x1, y1) = view
    pad = 60.0

    def visible(pts):
        return any(x0 - pad <= x <= x1 + pad and y0 - pad <= y <= y1 + pad for x, y in pts)

    roads, water, green, rail = [], [], [], []
    for tags, refs in osm.ways.values():
        pts = [proj(*osm.nodes[r]) for r in refs if r in osm.nodes]
        if len(pts) < 2 or not visible(pts):
            continue
        hw = tags.get("highway")
        if hw in ROAD_TYPES:
            cls = "major" if hw in ("primary", "secondary", "tertiary") else "minor"
            for run in clip_runs(pts, view):
                roads.append({"pts": rdp(run, 1.0), "name": tags.get("name"), "cls": cls})
        elif hw in ("footway", "path", "cycleway", "steps", "service", "track"):
            for run in clip_runs(pts, view):
                roads.append({"pts": rdp(run, 1.5), "name": None, "cls": "path"})
        elif tags.get("railway") in ("tram", "rail"):
            for run in clip_runs(pts, view):
                rail.append(rdp(run, 1.5))
        elif tags.get("natural") == "water" or tags.get("waterway") in ("riverbank", "river", "stream"):
            for run in clip_runs(pts, view):
                water.append({"pts": rdp(run, 1.5), "area": tags.get("natural") == "water"})
        elif tags.get("leisure") in ("park", "garden") or tags.get("landuse") in ("grass", "forest", "cemetery"):
            if ring_area(pts + [pts[0]]) < 150:
                continue
            for run in clip_runs(pts, view, pad=0):
                green.append(rdp(run, 2.0))
    return {"roads": roads, "water": water, "green": green, "rail": rail}


def build_streets(osm, proj, street_names):
    """Slice each requested street into segments at its crossings."""
    wanted = {norm(s): s for s in street_names}
    by_street = {k: [] for k in wanted}
    for tags, refs in osm.ways.values():
        if tags.get("highway") not in ROAD_TYPES:
            continue
        key = norm(tags.get("name"))
        if key in by_street:
            by_street[key].append(refs)

    streets = []
    for key, full_name in wanted.items():
        ways = by_street.get(key) or []
        if not ways:
            print(f"  ! nie znaleziono ulicy: {full_name}")
            continue
        crossings = crossing_nodes(osm, key)
        segments = []
        for chain in chain_ways(ways):
            pts_all = [proj(*osm.nodes[r]) for r in chain if r in osm.nodes]
            if len(pts_all) < 2 or polyline_length(pts_all) < 40:
                continue
            for pts, a, b in split_chain(chain, crossings, proj, osm.nodes):
                segments.append({"pts": pts, "from": a, "to": b})
        streets.append({"name": full_name, "short": short_name(full_name), "segments": segments})
    return streets


def prune_and_order(streets, buildings):
    """Drop segments nobody lives on, then order the rest by house number."""
    on_seg = {}
    for b in buildings:
        if b.get("seg"):
            on_seg.setdefault(b["seg"], []).append(b)
    for st in streets:
        kept = []
        for i, seg in enumerate(st["segments"]):
            here = on_seg.get((st["name"], i), [])
            if not here:
                continue
            lowest = min(house_key(b["number"]) for b in here)
            kept.append((lowest, i, seg, here))
        kept.sort()
        st["segments"] = [seg for _, _, seg, _ in kept]
        for new_i, (_, old_i, _, here) in enumerate(kept):
            for b in here:
                b["seg"] = (st["name"], new_i)


def assign_buildings(streets, buildings):
    """Attach every building to the nearest segment of its own street."""
    by_street = {norm(s["name"]): s for s in streets}
    unassigned = []
    for b in buildings:
        street = by_street.get(norm(b["street"]))
        if not street:
            unassigned.append(b)
            continue
        best = None
        for si, seg in enumerate(street["segments"]):
            d, along = project_on_polyline(b["c"], seg["pts"])
            if best is None or d < best[0]:
                best = (d, si, along, seg)
        if best is None or best[0] > 140:
            unassigned.append(b)
            continue
        b["seg"] = (street["name"], best[1])
        b["along"] = best[2]
        b["dist"] = best[0]
        b["side"] = side_of_polyline(b["c"], best[3]["pts"])
    return unassigned


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--streets", nargs="*", default=DEFAULT_STREETS)
    ap.add_argument("--bbox", nargs=4, type=float, default=DEFAULT_BBOX,
                    metavar=("S", "W", "N", "E"))
    ap.add_argument("--cache", default=os.path.join(HERE, "cache"))
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--title", default="Trójkąt D2D")
    ap.add_argument("--heading", default="Trójkąt")
    ap.add_argument("--subheading", default="Przedmieście Oławskie, Wrocław · obchód D2D")
    ap.add_argument("--slug", default="trojkat")
    args = ap.parse_args()

    print("1/5  pobieram dane OSM…")
    paths = fetch_bbox(*args.bbox, cache_dir=args.cache)

    print("2/5  parsuję…")
    osm = Osm().load(paths)
    print(f"     {len(osm.nodes)} węzłów, {len(osm.ways)} linii")

    s, w, n, e = args.bbox
    proj = Projection((s + n) / 2, (w + e) / 2)

    print("3/5  tnę ulice na odcinki…")
    streets = build_streets(osm, proj, args.streets)
    buildings = collect_buildings(osm, proj)
    unassigned = assign_buildings(streets, buildings)
    prune_and_order(streets, buildings)
    tracked = [b for b in buildings if b.get("seg")]
    print(f"     {sum(len(st['segments']) for st in streets)} odcinków, "
          f"{len(tracked)} adresów na wybranych ulicach")

    # viewport: everything we track, plus a margin
    xs = [p[0] for b in tracked for p in b["ring"]] + [p[0] for st in streets for sg in st["segments"] for p in sg["pts"]]
    ys = [p[1] for b in tracked for p in b["ring"]] + [p[1] for st in streets for sg in st["segments"] for p in sg["pts"]]
    margin = 70.0
    view = (min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin)

    print("4/5  zbieram tło…")
    context = collect_context(osm, proj, view)

    print("5/5  zapisuję…")
    os.makedirs(args.out, exist_ok=True)
    data = serialise(args, view, streets, tracked, unassigned, context, proj)
    data_path = os.path.join(args.out, "data.json")
    with open(data_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))

    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    template = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    page = template.replace("__MAP_DATA__", blob).replace("__SAVED_STATE__", "{}")
    page_path = os.path.join(args.out, "tracker.html")
    with open(page_path, "w", encoding="utf-8") as fh:
        fh.write(page)

    svg_path = os.path.join(args.out, "mapa-odcinki.svg")
    with open(svg_path, "w", encoding="utf-8") as fh:
        fh.write(render_svg(data))

    for path in (data_path, page_path, svg_path):
        print(f"     {path} ({os.path.getsize(path) / 1024:.0f} kB)")
    return data


def r1(v):
    return round(v, 1)


def serialise(args, view, streets, tracked, unassigned, context, proj):
    x0, y0, x1, y1 = view
    seg_index = {}
    out_streets = []
    for st in streets:
        segs = []
        for i, sg in enumerate(st["segments"]):
            sid = f"{norm(st['name'])}-{i}"
            seg_index[(st["name"], i)] = sid
            segs.append({
                "id": sid,
                "from": sg["from"],
                "to": sg["to"],
                "len": round(polyline_length(sg["pts"])),
                "pts": [[r1(p[0]), r1(p[1])] for p in sg["pts"]],
            })
        out_streets.append({"name": st["name"], "short": st["short"], "segments": segs})

    out_b = []
    for b in sorted(tracked, key=lambda b: (b["street"], house_key(b["number"]))):
        n = house_int(b["number"])
        out_b.append({
            "id": b["id"],
            "st": b["street"],
            "no": b["number"],
            "seg": seg_index[b["seg"]],
            "par": None if n is None else ("n" if n % 2 else "p"),
            "lv": b["levels"],
            "fl": b["flats"],
            "nm": b["name"],
            "c": [r1(b["c"][0]), r1(b["c"][1])],
            "ring": [[r1(p[0]), r1(p[1])] for p in rdp(b["ring"], 0.4)],
        })

    return {
        "title": args.title,
        "heading": args.heading,
        "subheading": args.subheading,
        "slug": args.slug,
        "view": [r1(x0), r1(y0), r1(x1), r1(y1)],
        "origin": [proj.lat0, proj.lon0],
        "scale": [proj.mx, proj.my],
        "streets": out_streets,
        "buildings": out_b,
        "other": [{"id": b["id"], "st": b["street"], "no": b["number"],
                   "c": [r1(b["c"][0]), r1(b["c"][1])],
                   "ring": [[r1(p[0]), r1(p[1])] for p in rdp(b["ring"], 0.6)]} for b in unassigned],
        "ctx": {
            "roads": [{"c": r["cls"], "n": r["name"], "p": [[r1(x), r1(y)] for x, y in r["pts"]]}
                      for r in context["roads"]],
            "water": [{"a": w["area"], "p": [[r1(x), r1(y)] for x, y in w["pts"]]} for w in context["water"]],
            "green": [[[r1(x), r1(y)] for x, y in g] for g in context["green"]],
            "rail": [[[r1(x), r1(y)] for x, y in g] for g in context["rail"]],
        },
    }




# --------------------------------------------------------------- static SVG

SVG_COLORS = {
    "paper": "#f6f2ef", "block": "#e7e0d9", "road": "#ffffff", "roadline": "#dcd1c8",
    "water": "#c6d7dd", "green": "#dfe4d5", "rail": "#c3b7ae", "other": "#e2d9d1",
    "ink": "#241c18", "muted": "#7a6c63", "brand": "#8c2f27",
}


def render_svg(data, width=1800, header=104, footer=64):
    """A printable version of the same map: outlines to fill in with a pen."""
    x0, y0, x1, y1 = data["view"]
    span_x, span_y = x1 - x0, y1 - y0
    s = width / span_x
    height = round(span_y * s)
    c = SVG_COLORS

    def pt(p):
        return f"{(p[0] - x0) * s:.1f} {(y1 - p[1]) * s:.1f}"

    def path(points, close=False):
        d = "M" + pt(points[0]) + "".join("L" + pt(p) for p in points[1:])
        return d + ("Z" if close else "")

    def joined(seq, close=False):
        return "".join(path(p, close) for p in seq if len(p) > 1)

    roads = {"major": [], "minor": [], "path": []}
    for r in data["ctx"]["roads"]:
        roads.setdefault(r["c"], roads["minor"]).append(r["p"])

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height + header + footer}" '
        f'viewBox="0 0 {width} {height + header + footer}" font-family="IBM Plex Sans, Helvetica, sans-serif">',
        f'<rect width="{width}" height="{height + header + footer}" fill="{c["paper"]}"/>',
        f'<text x="34" y="52" font-size="38" font-weight="700" fill="{c["ink"]}" '
        f'font-family="Archivo Narrow, Helvetica Neue, sans-serif" letter-spacing="0.5">'
        f'{_x(data["heading"].upper())}</text>',
        f'<text x="34" y="80" font-size="17" fill="{c["muted"]}">{_x(data["subheading"])}</text>',
        f'<clipPath id="mapclip"><rect width="{width}" height="{height}"/></clipPath>',
        f'<g transform="translate(0 {header})" clip-path="url(#mapclip)">',
        f'<rect width="{width}" height="{height}" fill="{c["block"]}"/>',
        f'<path d="{joined(data["ctx"]["green"], True)}" fill="{c["green"]}"/>',
        f'<path d="{joined([w["p"] for w in data["ctx"]["water"]], True)}" fill="{c["water"]}" '
        f'stroke="{c["water"]}" stroke-width="7" stroke-linejoin="round"/>',
        f'<path d="{joined(roads["major"])}" fill="none" stroke="{c["roadline"]}" stroke-width="19" stroke-linecap="round"/>',
        f'<path d="{joined(roads["minor"])}" fill="none" stroke="{c["roadline"]}" stroke-width="13" stroke-linecap="round"/>',
        f'<path d="{joined(roads["major"])}" fill="none" stroke="{c["road"]}" stroke-width="16" stroke-linecap="round"/>',
        f'<path d="{joined(roads["minor"])}" fill="none" stroke="{c["road"]}" stroke-width="10" stroke-linecap="round"/>',
        f'<path d="{joined(roads["path"])}" fill="none" stroke="{c["road"]}" stroke-width="3" opacity="0.6"/>',
        f'<path d="{joined(data["ctx"]["rail"])}" fill="none" stroke="{c["rail"]}" stroke-width="2" stroke-dasharray="7 5"/>',
        f'<path d="{joined([b["ring"] for b in data["other"]], True)}" fill="{c["other"]}" '
        f'stroke="{c["paper"]}" stroke-width="1"/>',
    ]

    for street in data["streets"]:
        for seg in street["segments"]:
            out.append(f'<path d="{path(seg["pts"])}" fill="none" stroke="{c["brand"]}" '
                       f'stroke-width="16" stroke-opacity="0.16" stroke-linecap="round"/>')

    out.append(f'<path d="{joined([b["ring"] for b in data["buildings"]], True)}" fill="#fffdfc" '
               f'stroke="{c["ink"]}" stroke-width="1.6"/>')

    for b in data["buildings"]:
        px, py = (b["c"][0] - x0) * s, (y1 - b["c"][1]) * s
        out.append(f'<text x="{px:.1f}" y="{py:.1f}" font-size="11" text-anchor="middle" '
                   f'dominant-baseline="central" fill="{c["ink"]}" '
                   f'font-family="IBM Plex Mono, monospace">{_x(b["no"])}</text>')

    for street in data["streets"]:
        for mid, ang in label_spots(street):
            px, py = (mid[0] - x0) * s, (y1 - mid[1]) * s
            out.append(f'<text x="{px:.1f}" y="{py:.1f}" font-size="15" text-anchor="middle" dy="-9" '
                       f'transform="rotate({ang:.1f} {px:.1f} {py:.1f})" fill="{c["muted"]}" '
                       f'font-family="Archivo Narrow, Helvetica, sans-serif" font-weight="600" '
                       f'letter-spacing="1.6">{_x(street["short"].upper())}</text>')

    out.append("</g>")

    legend = [("Zrobione", "#6d8a86"), ("Nikogo", "#c08a2e"), ("Odmowa", "#a1928a"),
              ("Brak wejścia", "#5f6f8c"), ("Temat", "#e0522f"), ("Umowa", "#2f7a55")]
    ly = height + header + 38
    x = 34
    for label, colour in legend:
        out.append(f'<rect x="{x}" y="{ly - 11}" width="13" height="13" rx="3" fill="{colour}"/>')
        out.append(f'<text x="{x + 20}" y="{ly}" font-size="14" fill="{c["muted"]}">{_x(label)}</text>')
        x += 34 + len(label) * 8
    total = len(data["buildings"])
    out.append(f'<text x="{width - 34}" y="{ly}" font-size="14" text-anchor="end" fill="{c["muted"]}">'
               f'{total} adresów · {sum(len(st["segments"]) for st in data["streets"])} odcinków · '
               f'dane © OpenStreetMap</text>')
    out.append("</svg>")
    return "\n".join(out)


def label_spots(street, min_gap=320.0, min_len=90.0):
    """One label per stretch of street, never two on top of each other."""
    placed = []
    for seg in sorted(street["segments"], key=lambda s: -s["len"]):
        if seg["len"] < min_len and placed:
            continue
        mid = seg["pts"][len(seg["pts"]) // 2]
        if any(math.dist(mid, p) < min_gap for p, _ in placed):
            continue
        a, z = seg["pts"][0], seg["pts"][-1]
        ang = math.degrees(math.atan2(-(z[1] - a[1]), z[0] - a[0]))
        if ang > 90:
            ang -= 180
        if ang < -90:
            ang += 180
        placed.append((mid, ang))
    return placed


def _x(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


if __name__ == "__main__":
    main()
