#!/usr/bin/env python3
"""Pull a course's hole geometry out of OpenStreetMap into a local JSON file.

    python course_fetch.py "Sunland Springs" sunland

Writes courses/<slug>.json with per-hole tee / fairway / green / pin / bunker
geometry in lat-lon, which is everything a yardage view needs.
"""

import json
import sys
import urllib.request
from pathlib import Path

OVERPASS = "https://overpass-api.de/api/interpreter"
OUT_DIR = Path(__file__).parent / "courses"

QUERY = """
[out:json][timeout:120];
area["leisure"="golf_course"]["name"~"{name}", i]->.a;
(
  way["golf"](area.a);
  node["golf"](area.a);
);
out geom tags;
"""


def fetch(name):
    req = urllib.request.Request(
        OVERPASS,
        data=QUERY.format(name=name).encode(),
        headers={"User-Agent": "golf-tour/1.0 (hole geometry for a private scorecard app)"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def geom_of(el):
    if el["type"] == "node":
        return [[el["lat"], el["lon"]]]
    return [[p["lat"], p["lon"]] for p in el.get("geometry", [])]


def centroid(pts):
    if not pts:
        return None
    return [sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)]


def assign_nines(holes):
    """Courses with 18+ holes reuse hole numbers per nine, and OSM rarely says
    which nine is which. Cluster centroids into groups of nine so each hole at
    least lands in the right loop."""
    n = max(1, round(len(holes) / 9))
    if n < 2:
        for h in holes:
            h["nine"] = 0
        return

    # k-means, seeded evenly through the list so it converges the same way twice
    pts = [h["center"] for h in holes]
    cents = [pts[i * len(pts) // n] for i in range(n)]
    groups = [0] * len(pts)
    for _ in range(40):
        for i, p in enumerate(pts):
            groups[i] = min(range(n), key=lambda k:
                            (p[0] - cents[k][0]) ** 2 + (p[1] - cents[k][1]) ** 2)
        for k in range(n):
            members = [p for i, p in enumerate(pts) if groups[i] == k]
            if members:
                cents[k] = centroid(members)

    for h, g in zip(holes, groups):
        h["nine"] = g

    # k-means doesn't know a nine has exactly nine holes, so it strands the odd
    # hole in a neighbouring loop. Hole numbers must be unique within a nine -
    # use that to repair it.
    def d2(h, k):
        return (h["center"][0] - cents[k][0]) ** 2 + (h["center"][1] - cents[k][1]) ** 2

    for _ in range(6):
        moved = False
        for k in range(n):
            seen = {}
            for h in [x for x in holes if x["nine"] == k]:
                seen.setdefault(h["ref"], []).append(h)
            for ref, dupes in seen.items():
                if len(dupes) < 2:
                    continue
                dupes.sort(key=lambda h: d2(h, k))
                for stray in dupes[1:]:
                    free = [j for j in range(n) if j != k and
                            not any(x["nine"] == j and x["ref"] == ref for x in holes)]
                    if free:
                        stray["nine"] = min(free, key=lambda j: d2(stray, j))
                        moved = True
        if not moved:
            break

    # label loops west-to-east so naming is stable between runs
    order = sorted(range(n), key=lambda k: cents[k][1])
    rank = {k: i for i, k in enumerate(order)}
    for h in holes:
        h["nine"] = rank[h["nine"]]


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "Sunland Springs"
    slug = sys.argv[2] if len(sys.argv) > 2 else "course"

    data = fetch(name)
    els = data.get("elements", [])
    print(f"{len(els)} golf features returned for {name!r}")

    kinds = {}
    for e in els:
        kinds.setdefault(e.get("tags", {}).get("golf", "?"), []).append(e)
    for k, v in sorted(kinds.items(), key=lambda x: -len(x[1])):
        print(f"  {k:<12} {len(v)}")

    # Hole numbers repeat across nines, so key by OSM id, not by ref.
    holes = {}
    for e in kinds.get("hole", []):
        t = e.get("tags", {})
        pts = geom_of(e)
        if not pts:
            continue
        holes[e["id"]] = {
            "id": e["id"],
            "ref": t.get("ref") or "?",
            "par": int(t["par"]) if t.get("par", "").isdigit() else None,
            "name": t.get("name"),
            "line": pts,
            "center": centroid(pts),
            "tees": [], "fairway": [], "green": [], "pin": None, "bunkers": [],
        }

    def anchor(h, end):
        """A hole's centreline runs tee -> green, so its endpoints are far
        better anchors than its midpoint for deciding what belongs to it."""
        return h["line"][-1] if end else h["line"][0]

    def nearest(pt, end):
        best, bd = None, 1e9
        for h in holes.values():
            a = anchor(h, end)
            d = (a[0] - pt[0]) ** 2 + (a[1] - pt[1]) ** 2
            if d < bd:
                best, bd = h, d
        return best, bd

    # green end of the hole
    for kind, key in (("green", "green"), ("pin", "pin")):
        claims = []
        for e in kinds.get(kind, []):
            pts = geom_of(e)
            c = centroid(pts)
            h, d = nearest(c, end=True)
            claims.append((d, h, pts, c))
        # closest claim wins each hole, so two greens can't collapse onto one
        taken = set()
        for d, h, pts, c in sorted(claims, key=lambda x: x[0]):
            if not h or h["id"] in taken:
                continue
            taken.add(h["id"])
            h[key] = c if key == "pin" else pts

    # tee end
    for e in kinds.get("tee", []):
        pts = geom_of(e)
        h, _ = nearest(centroid(pts), end=False)
        if h:
            h["tees"].append(pts)

    # hazards just go to whichever hole they sit closest to, either end
    for e in kinds.get("bunker", []):
        pts = geom_of(e)
        c = centroid(pts)
        a, da = nearest(c, end=True)
        b, db = nearest(c, end=False)
        (a if da <= db else b)["bunkers"].append(pts)

    for e in kinds.get("fairway", []):
        pts = geom_of(e)
        h, _ = nearest(centroid(pts), end=False)
        if h:
            h["fairway"] = pts

    ordered = list(holes.values())
    assign_nines(ordered)
    ordered.sort(key=lambda h: (h["nine"], int(h["ref"]) if h["ref"].isdigit() else 99))
    all_pts = [p for h in ordered for p in h["line"]]

    out = {
        "name": name,
        "slug": slug,
        "source": "OpenStreetMap contributors, ODbL",
        "center": centroid(all_pts),
        "holes": ordered,
    }
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / f"{slug}.json"
    path.write_text(json.dumps(out), encoding="utf-8")

    full = [h for h in ordered if h["green"] and h["tees"]]
    print(f"\n{len(ordered)} holes, {len(full)} with both tee and green geometry")
    print(f"pins: {sum(1 for h in ordered if h['pin'])}   "
          f"fairways: {sum(1 for h in ordered if h['fairway'])}   "
          f"bunkers: {sum(len(h['bunkers']) for h in ordered)}")
    print(f"-> {path}  ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
