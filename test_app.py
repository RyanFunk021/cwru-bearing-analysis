"""
Tests for Primitive Camping Finder (demo mode — no network required).
Run: DEMO_MODE=1 python -m pytest test_app.py -v
"""
import os, sys
import pytest

os.environ["DEMO_MODE"] = "1"

import app as camping_app
from app import haversine, parse_overpass_elements

@pytest.fixture
def client():
    camping_app.app.config["TESTING"] = True
    with camping_app.app.test_client() as c:
        yield c


# ── haversine ──────────────────────────────────────────────────────────────────
def test_haversine_same_point():
    assert haversine(40.0, -80.0, 40.0, -80.0) == pytest.approx(0.0)

def test_haversine_known_distance():
    # NYC to LA is roughly 2450 miles
    dist = haversine(40.7128, -74.0060, 34.0522, -118.2437)
    assert 2400 < dist < 2500

def test_haversine_symmetry():
    a = haversine(35.0, -90.0, 41.0, -87.6)
    b = haversine(41.0, -87.6, 35.0, -90.0)
    assert a == pytest.approx(b)


# ── parse_overpass_elements ────────────────────────────────────────────────────
def test_parse_backcountry_scores_high():
    elements = [
        {
            "type": "node", "id": 1, "lat": 35.0, "lon": -80.0,
            "tags": {
                "tourism": "camp_site", "name": "Test BC Camp",
                "backcountry": "yes", "fee": "no",
                "electricity": "no", "toilets": "no",
            },
        }
    ]
    results = parse_overpass_elements(elements, 35.0, -80.0)
    assert len(results) == 1
    assert results[0]["score"] >= 8  # backcountry(5)+free(2)+elec(1)
    assert "backcountry" in results[0]["flags"]
    assert "free" in results[0]["flags"]

def test_parse_developed_site_penalised():
    elements = [
        {
            "type": "node", "id": 2, "lat": 35.0, "lon": -80.0,
            "tags": {
                "tourism": "camp_site", "name": "RV Resort",
                "electricity": "yes", "power_supply": "yes",
                "shower": "yes", "fee": "yes",
            },
        }
    ]
    results = parse_overpass_elements(elements, 35.0, -80.0)
    assert results[0]["score"] < 0

def test_parse_deduplication():
    elements = [
        {"type": "node", "id": 10, "lat": 35.0, "lon": -80.0, "tags": {"name": "Repeat Camp"}},
        {"type": "node", "id": 11, "lat": 35.1, "lon": -80.1, "tags": {"name": "Repeat Camp"}},
    ]
    results = parse_overpass_elements(elements, 35.0, -80.0)
    assert len(results) == 1  # de-duplicated by name

def test_parse_sorts_by_score_then_distance():
    elements = [
        {"type": "node", "id": 20, "lat": 36.0, "lon": -80.0,  # farther, high score
         "tags": {"name": "Far BC", "backcountry": "yes", "fee": "no"}},
        {"type": "node", "id": 21, "lat": 35.1, "lon": -80.0,  # closer, low score
         "tags": {"name": "Near Dev", "electricity": "yes"}},
    ]
    results = parse_overpass_elements(elements, 35.0, -80.0)
    assert results[0]["name"] == "Far BC"


# ── /api/geocode ───────────────────────────────────────────────────────────────
def test_geocode_demo(client):
    r = client.get("/api/geocode?q=Denver,CO")
    assert r.status_code == 200
    data = r.get_json()
    assert "lat" in data and "lon" in data
    assert "(demo mode)" in data["display_name"]

def test_geocode_missing_param(client):
    r = client.get("/api/geocode")
    assert r.status_code == 400


# ── /api/campsites ─────────────────────────────────────────────────────────────
def test_campsites_demo(client):
    r = client.get("/api/campsites?lat=39.7&lon=-104.9&radius=100")
    assert r.status_code == 200
    data = r.get_json()
    assert data["demo"] is True
    sites = data["campsites"]
    assert len(sites) > 0
    # All must have required fields
    for s in sites:
        assert "name" in s
        assert "lat" in s and "lon" in s
        assert "score" in s
        assert "distance_mi" in s

def test_campsites_sorted_by_score(client):
    r = client.get("/api/campsites?lat=39.7&lon=-104.9&radius=200")
    data = r.get_json()
    scores = [s["score"] for s in data["campsites"]]
    # Should be non-increasing
    assert all(scores[i] >= scores[i+1] for i in range(len(scores)-1))

def test_campsites_missing_lat(client):
    r = client.get("/api/campsites?lon=-104.9")
    assert r.status_code == 400

def test_campsites_radius_capped(client):
    # Should not crash with huge radius
    r = client.get("/api/campsites?lat=39.7&lon=-104.9&radius=9999")
    assert r.status_code == 200


# ── /api/reviews ───────────────────────────────────────────────────────────────
def test_reviews_demo(client):
    r = client.get("/api/reviews?name=Dolly+Sods&state=WV")
    assert r.status_code == 200
    data = r.get_json()
    assert data["demo"] is True
    posts = data["posts"]
    assert len(posts) > 0
    for p in posts:
        assert "title" in p and "url" in p and "score" in p

def test_reviews_missing_name(client):
    r = client.get("/api/reviews")
    assert r.status_code == 400

def test_reviews_query_includes_name(client):
    r = client.get("/api/reviews?name=Gila+Wilderness")
    data = r.get_json()
    assert "Gila Wilderness" in data["query"]


# ── HTML ───────────────────────────────────────────────────────────────────────
def test_index_returns_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Primitive Camping Finder" in r.data
    assert b"leaflet" in r.data.lower()
