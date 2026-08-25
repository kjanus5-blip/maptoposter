"""Download raw OSM XML for a bounding box, tile by tile.

The OSM main API refuses any /map request that would return more than 50k
nodes, so a dense inner-city bbox has to be split into a grid and merged.
Tiles are cached on disk; re-running only fetches what is missing.
"""

import os
import time
import urllib.request

USER_AGENT = "maptoposter-d2d/1.0 (https://github.com/kjanus5-blip/maptoposter)"
API = "https://api.openstreetmap.org/api/0.6/map"


def fetch_bbox(south, west, north, east, cache_dir, rows=4, cols=5, verbose=True):
    """Fetch the bbox as rows x cols tiles. Returns the list of tile paths."""
    os.makedirs(cache_dir, exist_ok=True)
    paths = []
    for i in range(rows):
        for j in range(cols):
            s = south + (north - south) * i / rows
            n = south + (north - south) * (i + 1) / rows
            w = west + (east - west) * j / cols
            e = west + (east - west) * (j + 1) / cols
            path = os.path.join(cache_dir, f"t_{i}_{j}.osm")
            paths.append(path)
            if os.path.exists(path) and os.path.getsize(path) > 1000:
                continue
            url = f"{API}?bbox={w:.6f},{s:.6f},{e:.6f},{n:.6f}"
            _download(url, path, verbose)
    return paths


def _download(url, path, verbose):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = resp.read()
            with open(path, "wb") as fh:
                fh.write(data)
            if verbose:
                print(f"  {os.path.basename(path)}  {len(data) / 1e6:.1f} MB")
            return
        except Exception as exc:  # network hiccup -> exponential backoff
            if verbose:
                print(f"  retry {os.path.basename(path)}: {exc}")
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"could not download {url}")
