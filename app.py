"""
Primitive Camping Finder
Finds nearby primitive/backcountry camping spots using:
  - OpenStreetMap (Overpass API) for campsite locations
  - Nominatim for geocoding
  - Reddit JSON API for reviews & recommendations (no key needed)

Set DEMO_MODE=1 to use bundled sample data (no network required).
"""

import os
import math
import time
import requests
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

DEMO_MODE = os.environ.get("DEMO_MODE", "0") == "1"

# ─── Constants ────────────────────────────────────────────────────────────────

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
NOMINATIM_URL = "https://nominatim.openstreetmap.org"
REDDIT_BASE = "https://www.reddit.com"

HEADERS = {
    "User-Agent": "PrimitiveCampingFinder/1.0 (github.com/ryanfunk021/cwru-bearing-analysis)"
}

REDDIT_CAMPING_SUBS = [
    "camping",
    "CampingandHiking",
    "wildernesscamping",
    "backpacking",
    "overlanding",
    "boondocking",
]

# ─── Utility ──────────────────────────────────────────────────────────────────

def haversine(lat1, lon1, lat2, lon2):
    """Return distance in miles between two lat/lon points."""
    R = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _safe_get(url, params=None, timeout=10):
    """GET with a simple retry on transient failures."""
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            if attempt == 2:
                raise
            time.sleep(1.5 ** attempt)


# ─── Geocoding ────────────────────────────────────────────────────────────────

@app.route("/api/geocode")
def geocode():
    """Convert a place name → {lat, lon, display_name}."""
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "Missing query parameter 'q'"}), 400

    if DEMO_MODE:
        # Return a central US fallback so demo campsites are reachable
        return jsonify({"lat": 37.5, "lon": -96.0, "display_name": f"{query} (demo mode)"})

    try:
        r = _safe_get(
            f"{NOMINATIM_URL}/search",
            params={"q": query, "format": "json", "limit": 1, "addressdetails": 1},
        )
        results = r.json()
        if not results:
            return jsonify({"error": f"Location not found: {query}"}), 404
        best = results[0]
        return jsonify(
            {
                "lat": float(best["lat"]),
                "lon": float(best["lon"]),
                "display_name": best.get("display_name", query),
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


# ─── Campsite Search (Overpass / OSM) ─────────────────────────────────────────

def build_overpass_query(lat, lon, radius_m):
    """
    Build an Overpass QL query that fetches primitive / backcountry campsites.
    Tags targeted:
      - tourism=camp_site  with  backcountry=yes | access=yes | informal=yes
      - tourism=wilderness_hut
      - amenity=camping  (fallback)
    We also pull any camp_site within radius and let the scoring filter later.
    """
    return f"""
[out:json][timeout:30];
(
  node["tourism"="camp_site"](around:{radius_m},{lat},{lon});
  way["tourism"="camp_site"](around:{radius_m},{lat},{lon});
  node["tourism"="wilderness_hut"](around:{radius_m},{lat},{lon});
  node["leisure"="nature_reserve"]["camping"="yes"](around:{radius_m},{lat},{lon});
  node["amenity"="camping"](around:{radius_m},{lat},{lon});
);
out body center;
"""


def parse_overpass_elements(elements, user_lat, user_lon):
    """
    Convert raw Overpass elements to dicts, score primitiveness, add distance.
    Returns list sorted by (primitiveness_score DESC, distance ASC).
    """
    results = []
    seen = set()

    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name") or tags.get("ref") or "Unnamed Site"

        # De-duplicate by name+approx-location
        key = name.lower()[:30]
        if key in seen:
            continue
        seen.add(key)

        # Determine centre coordinates
        if el["type"] == "node":
            lat, lon = el["lat"], el["lon"]
        elif "center" in el:
            lat, lon = el["center"]["lat"], el["center"]["lon"]
        else:
            continue

        distance_mi = haversine(user_lat, user_lon, lat, lon)

        # ── Primitiveness score ───────────────────────────────────────────
        score = 0
        flags = []

        backcountry = tags.get("backcountry", "").lower()
        access = tags.get("access", "").lower()
        informal = tags.get("informal", "").lower()
        fee = tags.get("fee", "").lower()
        electricity = tags.get("electricity", "").lower()
        toilets = tags.get("toilets", "").lower()
        shower = tags.get("shower", "").lower()
        reservation = tags.get("reservation", "").lower()
        ttype = tags.get("tourism", "")

        if backcountry == "yes":
            score += 5
            flags.append("backcountry")
        if informal == "yes":
            score += 3
            flags.append("informal")
        if fee in ("no", "none", ""):
            score += 2
            flags.append("free")
        if electricity in ("no", "none", ""):
            score += 1
        if toilets in ("no", "none", ""):
            score += 1
        if shower in ("no", "none", ""):
            score += 1
        if reservation in ("no", "none", ""):
            score += 1
            flags.append("no reservation")
        if ttype == "wilderness_hut":
            score += 3
            flags.append("wilderness hut")

        # Penalise clearly developed sites
        if tags.get("hook_up") or tags.get("power_supply") or electricity == "yes":
            score -= 4

        # Operator hints
        operator = tags.get("operator", "").lower()
        for kw in ("forest service", "blm", "usfs", "nps", "dnr", "state forest"):
            if kw in operator:
                score += 2
                flags.append("public land")
                break

        website = tags.get("website") or tags.get("url") or ""
        description = tags.get("description") or tags.get("note") or ""

        results.append(
            {
                "id": el.get("id"),
                "name": name,
                "lat": lat,
                "lon": lon,
                "distance_mi": round(distance_mi, 1),
                "score": score,
                "flags": flags,
                "tags": {
                    k: v
                    for k, v in tags.items()
                    if k in ("backcountry", "fee", "access", "operator",
                             "toilets", "shower", "electricity", "reservation",
                             "informal", "capacity", "description", "note",
                             "tourism", "website", "url", "addr:city",
                             "addr:state", "addr:country")
                },
                "website": website,
                "description": description,
            }
        )

    results.sort(key=lambda x: (-x["score"], x["distance_mi"]))
    return results


@app.route("/api/campsites")
def campsites():
    """
    GET /api/campsites?lat=&lon=&radius=50
    radius in miles (default 50, max 200)
    Returns up to 30 primitive-ish campsites, scored + sorted.
    """
    try:
        lat = float(request.args.get("lat"))
        lon = float(request.args.get("lon"))
    except (TypeError, ValueError):
        return jsonify({"error": "lat and lon are required numeric parameters"}), 400

    radius_mi = min(float(request.args.get("radius", 50)), 200)
    radius_m = int(radius_mi * 1609.34)

    if DEMO_MODE:
        from demo_data import DEMO_CAMPSITES
        # Recalculate distances from the requested location
        demo = []
        for s in DEMO_CAMPSITES:
            s2 = dict(s)
            s2["distance_mi"] = round(haversine(lat, lon, s["lat"], s["lon"]), 1)
            demo.append(s2)
        demo.sort(key=lambda x: (-x["score"], x["distance_mi"]))
        return jsonify({"campsites": demo, "total_found": len(demo),
                        "demo": True, "demo_note": "Demo mode — showing sample data. In production, live OSM data is used."})

    query = build_overpass_query(lat, lon, radius_m)
    try:
        r = _safe_get(OVERPASS_URL, params={"data": query}, timeout=35)
        data = r.json()
    except Exception as exc:
        return jsonify({"error": f"Overpass API error: {exc}"}), 502

    parsed = parse_overpass_elements(data.get("elements", []), lat, lon)
    # Return top 30
    return jsonify({"campsites": parsed[:30], "total_found": len(parsed)})


# ─── Reddit Reviews ───────────────────────────────────────────────────────────

def search_reddit(query, limit=5):
    """
    Search Reddit for posts matching `query` across camping-related subreddits.
    Uses the public JSON search endpoint — no OAuth needed.
    Returns a list of post dicts with title, url, score, snippet, subreddit.
    """
    posts = []
    seen_ids = set()

    subreddits_str = "+".join(REDDIT_CAMPING_SUBS)
    endpoints = [
        f"{REDDIT_BASE}/r/{subreddits_str}/search.json",
        f"{REDDIT_BASE}/search.json",
    ]

    for endpoint in endpoints:
        if len(posts) >= limit:
            break
        params = {
            "q": query,
            "sort": "top",
            "t": "all",
            "limit": 10,
            "restrict_sr": "1" if "r/" in endpoint and endpoint != f"{REDDIT_BASE}/search.json" else "0",
        }
        try:
            r = _safe_get(endpoint, params=params, timeout=10)
            data = r.json()
            children = data.get("data", {}).get("children", [])
            for child in children:
                p = child.get("data", {})
                pid = p.get("id")
                if pid in seen_ids:
                    continue
                seen_ids.add(pid)

                selftext = p.get("selftext", "") or ""
                snippet = selftext[:300].replace("\n", " ").strip()
                if not snippet and p.get("url"):
                    snippet = p.get("url", "")

                posts.append(
                    {
                        "id": pid,
                        "title": p.get("title", ""),
                        "url": f"https://reddit.com{p.get('permalink', '')}",
                        "score": p.get("score", 0),
                        "num_comments": p.get("num_comments", 0),
                        "subreddit": p.get("subreddit", ""),
                        "snippet": snippet,
                        "created_utc": p.get("created_utc", 0),
                    }
                )
        except Exception:
            continue  # Don't fail the whole request if Reddit is flaky

        time.sleep(0.5)  # Be a polite Reddit citizen

    posts.sort(key=lambda x: -x["score"])
    return posts[:limit]


@app.route("/api/reviews")
def reviews():
    """
    GET /api/reviews?name=&state=
    Fetches Reddit posts about a campsite.
    """
    name = request.args.get("name", "").strip()
    state = request.args.get("state", "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    query_parts = [name]
    if state:
        query_parts.append(state)
    query_parts.append("primitive camping")
    query = " ".join(query_parts)

    if DEMO_MODE:
        from demo_data import DEMO_REDDIT_POSTS
        return jsonify({"posts": DEMO_REDDIT_POSTS["default"], "query": query, "demo": True})

    posts = search_reddit(query, limit=6)
    return jsonify({"posts": posts, "query": query})


# ─── Main ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
