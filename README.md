# 🏕️ Primitive Camping Finder

A web app that finds nearby **primitive / backcountry camping** spots and surfaces Reddit reviews for each one.

## Features

- 📍 **Location search** — enter any city, state, or zip code, or use GPS
- 🗺️ **Interactive map** — Leaflet + OpenStreetMap with dark mode tiles
- 🏕️ **Campsite scoring** — sites are scored for primitiveness using OpenStreetMap tags (backcountry, fee, electricity, toilets, reservations, operator, etc.)
- 🔍 **Filters** — free-only, backcountry, no-reservation
- 🔴 **Reddit integration** — searches r/camping, r/CampingandHiking, r/backpacking, r/wildernesscamping and more — **no API key required**
- 🌑 **Dark UI** — forest-green theme designed for outdoor aesthetics

## Data Sources

| Source | What it provides | Auth needed? |
|--------|-----------------|--------------|
| [OpenStreetMap / Overpass API](https://overpass-api.de/) | Campsite locations & tags | ❌ Free |
| [Nominatim](https://nominatim.openstreetmap.org/) | Geocoding (text → lat/lon) | ❌ Free |
| [Reddit JSON API](https://www.reddit.com/dev/api/) | Reviews & recommendations | ❌ No key needed |

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. (Optional) copy & edit environment variables
cp .env.example .env

# 3. Run the app
python app.py
```

Then open **http://localhost:5000** in your browser.

## How the Primitiveness Score Works

Each campsite is scored on a 0–14 scale based on OSM tags:

| Tag | Points |
|-----|--------|
| `backcountry=yes` | +5 |
| `informal=yes` | +3 |
| `fee=no` | +2 |
| Public land operator (USFS, BLM, NPS, DNR…) | +2 |
| No electricity | +1 |
| No toilets | +1 |
| No shower | +1 |
| No reservation required | +1 |
| Has hookups / power supply | −4 |

Sites are displayed sorted by score (most primitive first), then distance.

## Project Structure

```
├── app.py              # Flask backend (geocoding, Overpass, Reddit APIs)
├── requirements.txt
├── templates/
│   └── index.html      # Single-page app shell
└── static/
    ├── css/style.css   # Dark forest theme
    └── js/app.js       # Leaflet map + UI logic
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/geocode?q=Denver,CO` | Geocode a location |
| `GET /api/campsites?lat=&lon=&radius=50` | Find nearby campsites |
| `GET /api/reviews?name=&state=` | Fetch Reddit reviews |
