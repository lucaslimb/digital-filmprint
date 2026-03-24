# digital-filmprint

A Python tool that analyzes your [Letterboxd](https://letterboxd.com) data export and generates a self-contained HTML dashboard with stats and visualizations.

## Features

- Parses your Letterboxd export (watched history, ratings, watchlist)
- Enriches data with metadata from [TMDB](https://www.themoviedb.org/) (directors, genres, cast, posters)
- Generates a responsive HTML report with:
  - Overall stats (total watched, average rating, total runtime)
  - Ratings and activity charts
  - Top directors, genres, and actors
  - Top-rated films grid with posters
  - Rewatch history

## Requirements

- Python 3.10+
- Dependencies listed in `requirements.txt`

## Setup

```bash
pip install -r requirements.txt
```

Optionally, set a TMDB API key to enable enriched metadata (genres, cast, posters):

```bash
# Windows
set TMDB_API_KEY=your_api_key_here

# Linux/macOS
export TMDB_API_KEY=your_api_key_here
```

A free API key can be obtained at [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api).

## Usage

1. Export your data from Letterboxd: **Settings → Data → Export Your Data**
2. Place the downloaded `.zip` file in the project root
3. Run:

```bash
python generate_report.py
```

Or specify the path explicitly:

```bash
python generate_report.py path/to/letterboxd-export.zip
```

4. Open `report.html` in your browser

## Caching

TMDB responses are cached in `cache/tmdb_cache.json` so each film is only fetched once, and updating your report with new films is always faster than the first time.
