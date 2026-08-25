"""Turn raw OSM XML into the data the D2D tracker needs.

Produces, for a chosen set of streets:
  * street centre-lines split into segments at every crossing street
  * every addressed building, snapped to the segment it belongs to
  * background geometry (other roads, water, greens) for context
"""

import math
import re
import unicodedata
import xml.etree.ElementTree as ET

BUILDING_SKIP = {"garage", "garages", "shed", "roof", "carport", "hut", "container"}


# --------------------------------------------------------------------- parsing

class Osm:
    def __init__(self):
        self.nodes = {}          # id -> (lat, lon)
        self.node_tags = {}      # id -> tags (only for tagged nodes)
        self.ways = {}           # id -> (tags, [node ids])
        self.relations = {}      # id -> (tags, [(type, ref, role)])

    def load(self, paths):
        for path in paths:
            for _, el in ET.iterparse(path, events=("end",)):
                if el.tag == "node":
                    nid = el.get("id")
                    self.nodes[nid] = (float(el.get("lat")), float(el.get("lon")))
                    tags = _tags(el)
                    if tags:
                        self.node_tags[nid] = tags
                elif el.tag == "way":
                    self.ways[el.get("id")] = (_tags(el), [n.get("ref") for n in el.findall("nd")])
                elif el.tag == "relation":
                    members = [(m.get("type"), m.get("ref"), m.get("role")) for m in el.findall("member")]
                    self.relations[el.get("id")] = (_tags(el), members)
                if el.tag in ("node", "way", "relation"):
                    el.clear()
        return self


def _tags(el):
    return {t.get("k"): t.get("v") for t in el.findall("tag")}


# ----------------------------------------------------------------- projection

class Projection:
    """Local equirectangular projection: metres east/north of an origin."""

    def __init__(self, lat0, lon0):
        self.lat0 = lat0
        self.lon0 = lon0
        self.mx = 111320.0 * math.cos(math.radians(lat0))
        self.my = 110540.0

    def __call__(self, lat, lon):
        return ((lon - self.lon0) * self.mx, (lat - self.lat0) * self.my)


# ------------------------------------------------------------------- geometry

def polyline_length(pts):
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def project_on_polyline(pt, pts):
    """Nearest point on a polyline. Returns (distance, arc length along line)."""
    best = (float("inf"), 0.0)
    travelled = 0.0
    for i in range(len(pts) - 1):
        ax, ay = pts[i]
        bx, by = pts[i + 1]
        dx, dy = bx - ax, by - ay
        seg = math.hypot(dx, dy)
        if seg == 0:
            continue
        t = max(0.0, min(1.0, ((pt[0] - ax) * dx + (pt[1] - ay) * dy) / (seg * seg)))
        px, py = ax + t * dx, ay + t * dy
        d = math.dist(pt, (px, py))
        if d < best[0]:
            best = (d, travelled + t * seg)
        travelled += seg
    return best


def side_of_polyline(pt, pts):
    """+1 / -1: which side of the (directed) line the point falls on."""
    best_d, best_sign = float("inf"), 1
    for i in range(len(pts) - 1):
        ax, ay = pts[i]
        bx, by = pts[i + 1]
        dx, dy = bx - ax, by - ay
        seg = math.hypot(dx, dy)
        if seg == 0:
            continue
        t = max(0.0, min(1.0, ((pt[0] - ax) * dx + (pt[1] - ay) * dy) / (seg * seg)))
        px, py = ax + t * dx, ay + t * dy
        d = math.dist(pt, (px, py))
        if d < best_d:
            best_d = d
            cross = dx * (pt[1] - ay) - dy * (pt[0] - ax)
            best_sign = 1 if cross >= 0 else -1
    return best_sign


def centroid(ring):
    """Area centroid of a closed ring, falling back to the mean of vertices."""
    a = cx = cy = 0.0
    for i in range(len(ring) - 1):
        x0, y0 = ring[i]
        x1, y1 = ring[i + 1]
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(a) < 1e-9:
        n = len(ring)
        return (sum(p[0] for p in ring) / n, sum(p[1] for p in ring) / n)
    a *= 0.5
    return (cx / (6 * a), cy / (6 * a))


def ring_area(ring):
    a = 0.0
    for i in range(len(ring) - 1):
        x0, y0 = ring[i]
        x1, y1 = ring[i + 1]
        a += x0 * y1 - x1 * y0
    return abs(a) * 0.5


# --------------------------------------------------------------- street names

def norm(name):
    """Fold a street name down to something matchable: 'Gen. Józefa Haukego-Bosaka' -> 'haukegobosaka'."""
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def short_name(name):
    """Drop honorifics and given names: 'Generała Romualda Traugutta' -> 'Traugutta'."""
    parts = (name or "").split()
    drop = {"generala", "gen", "aleja", "al", "plac", "pl", "ulica", "ul", "wybrzeze",
            "przejscie", "promenada", "most", "swietego", "sw", "ksiedza", "ks"}
    while parts and norm(parts[0]) in drop:
        parts.pop(0)
    if len(parts) > 1:
        # keep only the surname unless the whole thing is one token (e.g. "Komuny Paryskiej")
        tail = parts[-1]
        if len(parts) >= 2 and not tail.endswith("ej") and not tail.endswith("ie"):
            return tail
    return " ".join(parts) or name


def house_key(number):
    """Sort key for Polish house numbers: 12, 12a, 12/14, 3-5."""
    m = re.match(r"\s*(\d+)\s*(.*)", number or "")
    if not m:
        return (10 ** 6, number or "")
    return (int(m.group(1)), m.group(2).lower())


def house_int(number):
    m = re.match(r"\s*(\d+)", number or "")
    return int(m.group(1)) if m else None


# ------------------------------------------------------------ street assembly

ROAD_TYPES = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
              "residential", "living_street", "pedestrian", "road"}


def chain_ways(ways):
    """Join a set of ways (lists of node ids) into as few continuous chains as possible."""
    pending = [list(w) for w in ways if len(w) >= 2]
    chains = []
    while pending:
        chain = pending.pop(0)
        grew = True
        while grew:
            grew = False
            for i, w in enumerate(pending):
                if chain[-1] == w[0]:
                    chain += w[1:]
                elif chain[-1] == w[-1]:
                    chain += w[-2::-1]
                elif chain[0] == w[-1]:
                    chain = w[:-1] + chain
                elif chain[0] == w[0]:
                    chain = w[:0:-1] + chain
                else:
                    continue
                pending.pop(i)
                grew = True
                break
        chains.append(chain)
    chains.sort(key=len, reverse=True)
    return chains


def crossing_nodes(osm, own_name_norm):
    """node id -> set of names of the *other* named roads passing through it."""
    crossings = {}
    for tags, refs in osm.ways.values():
        hw = tags.get("highway")
        name = tags.get("name")
        if not name or hw not in ROAD_TYPES:
            continue
        if norm(name) == own_name_norm:
            continue
        for ref in refs:
            crossings.setdefault(ref, set()).add(name)
    return crossings


def split_chain(chain, crossings, proj, nodes, min_len=30.0):
    """Cut a chain of node ids at crossing streets. Returns [(pts, from_name, to_name)]."""
    last = len(chain) - 1
    cuts = [0, last]
    labels = {}
    for idx, ref in enumerate(chain):
        names = crossings.get(ref)
        if not names:
            continue
        labels[idx] = short_name(sorted(names)[0])
        if idx not in (0, last):
            cuts.append(idx)
    labels.setdefault(0, "początek")
    labels.setdefault(last, "koniec")
    cuts = sorted(set(cuts))

    # drop cuts that would make a stub shorter than min_len
    def pts_for(a, b):
        return [proj(*nodes[r]) for r in chain[a:b + 1] if r in nodes]

    kept = [cuts[0]]
    for c in cuts[1:-1]:
        if polyline_length(pts_for(kept[-1], c)) >= min_len:
            kept.append(c)
    if len(kept) > 1 and polyline_length(pts_for(kept[-1], cuts[-1])) < min_len:
        kept.pop()
    kept.append(cuts[-1])

    segments = []
    for a, b in zip(kept, kept[1:]):
        pts = pts_for(a, b)
        if len(pts) < 2:
            continue
        segments.append((pts, labels.get(a, "?"), labels.get(b, "?")))
    return segments


# ------------------------------------------------------- clipping/simplifying

def rdp(pts, eps):
    """Ramer-Douglas-Peucker line simplification."""
    if len(pts) < 3:
        return pts
    ax, ay = pts[0]
    bx, by = pts[-1]
    dx, dy = bx - ax, by - ay
    norm_len = math.hypot(dx, dy)
    worst, idx = -1.0, 0
    for i in range(1, len(pts) - 1):
        px, py = pts[i]
        if norm_len == 0:
            d = math.dist(pts[i], pts[0])
        else:
            d = abs(dx * (ay - py) - (ax - px) * dy) / norm_len
        if d > worst:
            worst, idx = d, i
    if worst <= eps:
        return [pts[0], pts[-1]]
    return rdp(pts[:idx + 1], eps)[:-1] + rdp(pts[idx:], eps)


def clip_runs(pts, box, pad=40.0):
    """Split a polyline into the runs that touch the box (keeping one point of slack)."""
    x0, y0, x1, y1 = box
    inside = [x0 - pad <= x <= x1 + pad and y0 - pad <= y <= y1 + pad for x, y in pts]
    runs, cur = [], []
    for i, p in enumerate(pts):
        near = inside[i] or (i > 0 and inside[i - 1]) or (i + 1 < len(pts) and inside[i + 1])
        if near:
            cur.append(p)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return [r for r in runs if len(r) >= 2]
