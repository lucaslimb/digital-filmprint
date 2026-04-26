"""
analyzer.py
-----------
Analyzes Letterboxd CSV exports from the data/ directory.

Enriched metadata is cached in data/cache/tmdb_cache.json so each
film is only requested from the API once.
"""

import json
import os
import re
import threading
import time
import warnings
import zipfile
from collections import Counter
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

# ── Paths ───────────────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).parent
_ROOT_DIR   = _SCRIPT_DIR.parent
CACHE_FILE  = _ROOT_DIR / "cache" / "tmdb_cache.json"
TMDB_BASE   = "https://api.themoviedb.org/3"


# ── TMDB key resolution ─────────────────────────────────────────────────────────

def get_tmdb_api_key() -> str:
    return os.environ.get("TMDB_API_KEY", "").strip()


# ── TMDB cache (module-level singleton) ─────────────────────────────────────────

_cache: dict        = {}
_cache_loaded: bool = False
_cache_lock          = threading.Lock()
_rate_lock           = threading.Lock()
_tmdb_request_times: deque[float] = deque()


def _wait_for_tmdb_slot(max_requests: int = 40, window_seconds: float = 1.0) -> None:
    with _rate_lock:
        now = time.monotonic()
        cutoff = now - window_seconds

        while _tmdb_request_times and _tmdb_request_times[0] <= cutoff:
            _tmdb_request_times.popleft()

        if len(_tmdb_request_times) >= max_requests:
            sleep_for = _tmdb_request_times[0] + window_seconds - now
            if sleep_for > 0:
                _rate_lock.release()
                time.sleep(sleep_for)
                _rate_lock.acquire()

            now = time.monotonic()
            cutoff = now - window_seconds
            while _tmdb_request_times and _tmdb_request_times[0] <= cutoff:
                _tmdb_request_times.popleft()

        _tmdb_request_times.append(time.monotonic())


def _load_cache() -> None:
    global _cache, _cache_loaded
    with _cache_lock:
        if _cache_loaded:
            return
        if CACHE_FILE.exists():
            with open(CACHE_FILE, encoding="utf-8") as f:
                _cache = json.load(f)
        _cache_loaded = True


def _save_cache() -> None:
    with _cache_lock:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False, indent=2)


# ── TMDB fetch ──────────────────────────────────────────────────────────────────

def _fetch_tmdb(name: str, year, api_key: str) -> dict | None:
    """
    Return TMDB metadata for a single film using a local disk cache.
    Keys: directors (list), genres (list), cast (list, up to 10), runtime (int|None).
    Returns None when the film is not found or an error occurs.
    """
    _load_cache()
    cache_key = f"{name}|||{year}"
    with _cache_lock:
        hit = _cache.get(cache_key)
        # Return cached hit if it's a complete dict (has poster_path).
        # Stale dicts missing "poster_path" or bare None entries without
        # the "_v2" marker are re-fetched to pick up new fields / retries.
        if cache_key in _cache:
            if isinstance(hit, dict) and "poster_path" in hit:
                return hit
            if hit is None and _cache.get(cache_key + "::v") == 2:
                return None

    params: dict = {"api_key": api_key, "query": name, "language": "en-US"}
    if pd.notna(year):
        params["year"] = int(year)

    try:
        # ── Movie search (3-step fallback) ──
        _wait_for_tmdb_slot()
        resp = requests.get(f"{TMDB_BASE}/search/movie", params=params, timeout=8)
        resp.raise_for_status()
        results = resp.json().get("results", [])

        # Fallback chain when the primary search returns nothing:
        #  1) Drop the language filter (matches original-language titles).
        #  2) Drop the year filter too (handles year mismatches between
        #     Letterboxd and TMDB).
        if not results:
            fb1 = {k: v for k, v in params.items() if k != "language"}
            _wait_for_tmdb_slot()
            resp = requests.get(f"{TMDB_BASE}/search/movie", params=fb1, timeout=8)
            resp.raise_for_status()
            results = resp.json().get("results", [])

        # ── TV search with year (before dropping year on movie search,
        #    since some Letterboxd "films" are TV on TMDB and a year-
        #    matched TV result is better than a year-less movie result) ──
        tv_results: list = []
        if not results and pd.notna(year):
            tv_params = {"api_key": api_key, "query": name,
                         "first_air_date_year": int(year)}
            _wait_for_tmdb_slot()
            resp = requests.get(f"{TMDB_BASE}/search/tv", params=tv_params, timeout=8)
            resp.raise_for_status()
            tv_results = resp.json().get("results", [])

        # Movie search dropping year (last-resort movie fallback).
        # Accept only if the release year is close (±1) to the expected year.
        if not results and not tv_results and "year" in params:
            fb2 = {"api_key": api_key, "query": name}
            _wait_for_tmdb_slot()
            resp = requests.get(f"{TMDB_BASE}/search/movie", params=fb2, timeout=8)
            resp.raise_for_status()
            noyear_results = resp.json().get("results", [])
            if noyear_results and pd.notna(year):
                rd = noyear_results[0].get("release_date", "")
                try:
                    ry = int(rd[:4])
                    if abs(ry - int(year)) <= 1:
                        results = noyear_results
                except (ValueError, IndexError):
                    pass
            elif noyear_results:
                results = noyear_results

        # TV search without year (last-resort TV fallback)
        if not results and not tv_results:
            _wait_for_tmdb_slot()
            resp = requests.get(
                f"{TMDB_BASE}/search/tv",
                params={"api_key": api_key, "query": name},
                timeout=8,
            )
            resp.raise_for_status()
            tv_results = resp.json().get("results", [])

        # ── Fetch movie detail ──
        if results:
            movie_id = results[0]["id"]
            _wait_for_tmdb_slot()
            detail = requests.get(
                f"{TMDB_BASE}/movie/{movie_id}",
                params={"api_key": api_key, "append_to_response": "credits"},
                timeout=8,
            )
            detail.raise_for_status()
            d = detail.json()

            crew      = d.get("credits", {}).get("crew", [])
            cast_list = d.get("credits", {}).get("cast", [])

            meta = {
                "directors":        [c["name"]          for c in crew      if c.get("job") == "Director"],
                "director_genders": [c.get("gender", 0) for c in crew      if c.get("job") == "Director"],
                "genres":           [g["name"]           for g in d.get("genres", [])],
                "cast":             [c["name"]           for c in cast_list[:10]],
                "cast_genders":     [c.get("gender", 0)  for c in cast_list[:10]],
                "runtime":          d.get("runtime"),
                "countries":        [c["name"]           for c in d.get("production_countries", [])],
                "poster_path":      d.get("poster_path"),
                "popularity":       d.get("popularity"),
                "vote_average":     d.get("vote_average"),
                "vote_count":       d.get("vote_count"),
            }
            with _cache_lock:
                _cache[cache_key] = meta
            return meta

        # ── Fetch TV detail ──
        if tv_results:
            tv_id = tv_results[0]["id"]
            _wait_for_tmdb_slot()
            detail = requests.get(
                f"{TMDB_BASE}/tv/{tv_id}",
                params={"api_key": api_key, "append_to_response": "credits"},
                timeout=8,
            )
            detail.raise_for_status()
            d = detail.json()

            crew      = d.get("credits", {}).get("crew", [])
            cast_list = d.get("credits", {}).get("cast", [])
            creators  = d.get("created_by", [])

            directors = ([c["name"] for c in crew if c.get("job") == "Director"]
                         or [c["name"] for c in creators])
            dir_genders = ([c.get("gender", 0) for c in crew if c.get("job") == "Director"]
                           or [c.get("gender", 0) for c in creators])

            ep_runtimes = d.get("episode_run_time", [])
            runtime = ep_runtimes[0] if ep_runtimes else None

            meta = {
                "directors":        directors,
                "director_genders": dir_genders,
                "genres":           [g["name"]           for g in d.get("genres", [])],
                "cast":             [c["name"]           for c in cast_list[:10]],
                "cast_genders":     [c.get("gender", 0)  for c in cast_list[:10]],
                "runtime":          runtime,
                "countries":        [c["name"]           for c in d.get("production_countries", d.get("origin_country", []))],
                "poster_path":      d.get("poster_path"),
                "popularity":       d.get("popularity"),
                "vote_average":     d.get("vote_average"),
                "vote_count":       d.get("vote_count"),
            }
            with _cache_lock:
                _cache[cache_key] = meta
            return meta

        # Genuinely not found anywhere
        with _cache_lock:
            _cache[cache_key] = None
            _cache[cache_key + "::v"] = 2
        return None

    except Exception:
        with _cache_lock:
            _cache[cache_key] = None
        return None


def _enrich(watched: pd.DataFrame, api_key: str) -> list[dict | None]:
    """
    Fetch TMDB metadata for every film in *watched* using concurrent requests.
    Up to 20 threads run in parallel while the shared rate-limiter keeps
    total throughput at 40 TMDB requests per second.
    """
    total = len(watched)
    rows  = list(watched.iterrows())
    result: list[dict | None] = [None] * total
    done   = 0
    done_lock = threading.Lock()

    def _task(idx: int, row: pd.Series) -> tuple[int, dict | None]:
        return idx, _fetch_tmdb(row["Name"], row.get("Year"), api_key)

    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {
            pool.submit(_task, i, row): i
            for i, (_, row) in enumerate(rows)
        }
        for future in as_completed(futures):
            idx, meta = future.result()
            result[idx] = meta
            with done_lock:
                done += 1
                if done % 50 == 0:
                    print(f"  [TMDB] {done}/{total} films fetched...")
                    _save_cache()

    _save_cache()
    return result


TMDB_IMG_BASE = "https://image.tmdb.org/t/p/"


def _fetch_person_image(name: str, api_key: str) -> str | None:
    """Return the TMDB profile image URL for a person, or None."""
    _load_cache()
    cache_key = f"person|||{name}"
    with _cache_lock:
        if cache_key in _cache:
            path = _cache[cache_key]
            return f"{TMDB_IMG_BASE}w185{path}" if path else None

    try:
        _wait_for_tmdb_slot()
        resp = requests.get(
            f"{TMDB_BASE}/search/person",
            params={"api_key": api_key, "query": name, "language": "en-US"},
            timeout=8,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        path = results[0].get("profile_path") if results else None
        with _cache_lock:
            _cache[cache_key] = path
        _save_cache()
        return f"{TMDB_IMG_BASE}w185{path}" if path else None
    except Exception:
        with _cache_lock:
            _cache[cache_key] = None
        return None


def get_hero_data(data: dict) -> dict:
    """
    Build the hero-section payload: profile favourite films (with posters),
    top director (with photo) and top actor (with photo).
    """
    api_key = get_tmdb_api_key()

    # ── Resolve favourite films from profile short-URLs ──
    profile  = data["profile"].iloc[0]
    fav_raw  = str(profile.get("Favorite Films", ""))
    fav_urls = [u.strip() for u in fav_raw.split(",") if u.strip()] if fav_raw != "nan" else []

    watched  = data["watched"]
    uri_map  = dict(zip(watched["Letterboxd URI"], watched.index))  # short-URL → row idx

    fav_films: list[dict] = []
    for url in fav_urls[:4]:
        idx = uri_map.get(url)
        if idx is not None:
            row = watched.loc[idx]
            name, year = row["Name"], row.get("Year")
        else:
            # URL not in watched list – resolve slug as a fallback
            try:
                r = requests.head(url, allow_redirects=True, timeout=10)
                slug = r.url.rstrip("/").split("/")[-1]
                # strip trailing year like -1973
                import re as _re
                m = _re.match(r"^(.+)-(\d{4})$", slug)
                if m:
                    name = m.group(1).replace("-", " ").title()
                    year = int(m.group(2))
                else:
                    name = slug.replace("-", " ").title()
                    year = None
            except Exception:
                continue

        poster_url = None
        if api_key:
            meta = _fetch_tmdb(name, year, api_key)
            if meta and meta.get("poster_path"):
                poster_url = f"{TMDB_IMG_BASE}w300{meta['poster_path']}"
        fav_films.append({"name": str(name), "year": int(year) if pd.notna(year) else None, "poster": poster_url})

    # ── Top director & top actor (with images) ──
    top_director: dict | None = None
    top_actor:    dict | None = None

    if api_key:
        metas = _enrich(watched, api_key)

        dir_counter: Counter = Counter()
        for meta in metas:
            if meta:
                dir_counter.update(meta["directors"])
        if dir_counter:
            dname, dcount = dir_counter.most_common(1)[0]
            top_director = {"name": dname, "count": dcount, "image": _fetch_person_image(dname, api_key)}

        act_counter: Counter = Counter()
        for meta in metas:
            if meta:
                act_counter.update(meta["cast"])
        if act_counter:
            aname, acount = act_counter.most_common(1)[0]
            top_actor = {"name": aname, "count": acount, "image": _fetch_person_image(aname, api_key)}

    return {
        "fav_films":    fav_films,
        "top_director": top_director,
        "top_actor":    top_actor,
    }


# ── Raw CSV loaders ─────────────────────────────────────────────────────────────

def load_data(zip_path: str | Path) -> dict[str, pd.DataFrame]:
    """Load all relevant Letterboxd CSV exports from a zip file.

    TMDB cache is stored in ``cache/tmdb_cache.json`` next to this script,
    shared across all zip exports.
    """
    zip_path = Path(zip_path)

    with zipfile.ZipFile(zip_path) as zf:
        def _read(member: str) -> pd.DataFrame:
            with zf.open(member) as f:
                return pd.read_csv(f)

        return {
            "watched":     _read("watched.csv"),
            "ratings":     _read("ratings.csv"),
            "diary":       _read("diary.csv"),
            "reviews":     _read("reviews.csv"),
            "watchlist":   _read("watchlist.csv"),
            "liked_films": _read("likes/films.csv"),
            "profile":     _read("profile.csv"),
        }


# ── Individual stat functions ───────────────────────────────────────────────────

def get_profile_info(data: dict) -> dict:
    """Profile metadata and top-level aggregate counts."""
    p       = data["profile"].iloc[0]
    ratings = data["ratings"]["Rating"].dropna()
    avg     = round(float(ratings.mean()), 2) if not ratings.empty else None
    rewatches = data["diary"][
        data["diary"]["Rewatch"].astype(str).str.strip().str.lower() == "yes"
    ]
    # Count non-empty favorite film URLs in the Favorite Films field
    fav_raw = str(p.get("Favorite Films", ""))
    fav_count = len([u for u in fav_raw.split(",") if u.strip()]) if fav_raw != "nan" else 0
    # Strip HTML tags from bio
    bio_raw = str(p.get("Bio", ""))
    bio_clean = re.sub(r"<[^>]+>", "", bio_raw).strip() if bio_raw != "nan" else ""
    return {
        "username":            str(p.get("Username", "")),
        "given_name":          str(p.get("Given Name", "")) if str(p.get("Given Name", "")) != "nan" else "",
        "family_name":         str(p.get("Family Name", "")) if str(p.get("Family Name", "")) != "nan" else "",
        "date_joined":         str(p.get("Date Joined", "")),
        "bio":                 bio_clean,
        "pronoun":             str(p.get("Pronoun", "")) if str(p.get("Pronoun", "")) != "nan" else "",
        "location":            str(p.get("Location", "")) if str(p.get("Location", "")) != "nan" else "",
        "website":             str(p.get("Website", "")) if str(p.get("Website", "")) != "nan" else "",
        "favorite_films_count":fav_count,
        "total_watched":       int(len(data["watched"])),
        "total_rated":         int(len(data["ratings"])),
        "total_reviews":       int(len(data["reviews"])),
        "watchlist_size":      int(len(data["watchlist"])),
        "total_liked":         int(len(data["liked_films"])),
        "total_rewatches":     int(len(rewatches)),
        "average_rating":      avg,
    }


def get_rating_distribution(data: dict) -> dict[str, int]:
    """Count of each rating value (0.5–5.0), sorted low→high."""
    counts = data["ratings"]["Rating"].dropna().value_counts().sort_index()
    return {str(k): int(v) for k, v in counts.items()}


def get_activity_by_year(data: dict) -> dict[int, int]:
    """Number of films logged per calendar year (from diary Watched Date)."""
    diary = data["diary"].copy()
    diary["_year"] = pd.to_datetime(diary["Watched Date"], errors="coerce").dt.year
    counts = diary.dropna(subset=["_year"]).groupby("_year").size()
    return {int(y): int(c) for y, c in counts.items()}


def get_favorite_years(data: dict, n: int = 5, min_films_rating: int = 4) -> dict:
    """
    Top-n release years by:
      - most_watched: release years with the most films watched.
      - best_rated:   release years with the highest avg user rating (min *min_films_rating* rated).
    """
    watched = data["watched"].dropna(subset=["Year"]).copy()
    watched["_year"] = watched["Year"].astype(int)
    count_by_year = (
        watched.groupby("_year").size()
        .sort_values(ascending=False)
        .head(n)
    )
    most_watched = [{"year": int(y), "count": int(c)} for y, c in count_by_year.items()]

    ratings = data["ratings"].dropna(subset=["Rating", "Year"]).copy()
    ratings["_year"] = ratings["Year"].astype(int)
    agg = ratings.groupby("_year")["Rating"].agg(["mean", "count"])
    agg = agg[agg["count"] >= min_films_rating]
    agg = agg.sort_values("mean", ascending=False).head(n)
    best_rated = [
        {"year": int(y), "avg": round(float(row["mean"]), 2), "count": int(row["count"])}
        for y, row in agg.iterrows()
    ]

    return {"most_watched": most_watched, "best_rated": best_rated}


def get_activity_by_month(data: dict) -> dict[str, int]:
    """
    Number of films logged per month across all years (Jan–Dec totals).
    Useful for spotting seasonal viewing patterns.
    """
    diary = data["diary"].copy()
    diary["_month"] = pd.to_datetime(diary["Watched Date"], errors="coerce").dt.month
    month_abbr = ["Jan","Feb","Mar","Apr","May","Jun",
                  "Jul","Aug","Sep","Oct","Nov","Dec"]
    counts = diary.dropna(subset=["_month"]).groupby("_month").size()
    return {month_abbr[int(m) - 1]: int(c) for m, c in counts.items()}


def get_decade_breakdown(data: dict) -> dict[str, int]:
    """Count of watched films grouped by release decade (e.g. '1980s')."""
    watched = data["watched"].dropna(subset=["Year"]).copy()
    watched["_decade"] = (watched["Year"].astype(int) // 10 * 10).astype(str) + "s"
    counts = watched.groupby("_decade").size().sort_index()
    return {k: int(v) for k, v in counts.items()}


def get_top_rated_films(data: dict, n: int = 20) -> list[dict]:
    """Top-n highest-rated films, sorted by rating descending."""
    ratings = (
        data["ratings"]
        .dropna(subset=["Rating"])
        .sort_values(["Rating", "Name"], ascending=[False, True])
        .head(n)
    )
    return ratings[["Name", "Year", "Rating"]].to_dict(orient="records")


def get_lowest_rated_films(data: dict, n: int = 10) -> list[dict]:
    """Bottom-n lowest-rated films, sorted by rating ascending."""
    ratings = (
        data["ratings"]
        .dropna(subset=["Rating"])
        .sort_values(["Rating", "Name"], ascending=[True, True])
        .head(n)
    )
    return ratings[["Name", "Year", "Rating"]].to_dict(orient="records")


def get_rewatch_stats(data: dict) -> dict:
    """Total rewatch count and the films rewatched the most."""
    diary     = data["diary"]
    rewatches = diary[diary["Rewatch"].astype(str).str.strip().str.lower() == "yes"]
    top       = rewatches["Name"].value_counts().head(10)
    return {
        "total_rewatches": int(len(rewatches)),
        "most_rewatched":  [{"name": n, "count": int(c)} for n, c in top.items()],
    }


def get_tag_breakdown(data: dict, n: int = 30) -> dict[str, int]:
    """Most-used diary tags, including decade markers."""
    diary    = data["diary"].dropna(subset=["Tags"])
    all_tags: list[str] = []
    for raw in diary["Tags"]:
        for tag in str(raw).split(","):
            tag = tag.strip().strip("'\"")
            if tag:
                all_tags.append(tag)
    return dict(Counter(all_tags).most_common(n))


def get_liked_films(data: dict, n: int = 24) -> list[dict]:
    """Most recently liked films."""
    liked = (
        data["liked_films"]
        .sort_values("Date", ascending=False)
        .head(n)
    )
    return liked[["Name", "Year"]].to_dict(orient="records")


def get_reviews_over_time(data: dict) -> dict[str, int]:
    """Number of reviews written per year."""
    reviews = data["reviews"].copy()
    reviews["_year"] = pd.to_datetime(reviews["Date"], errors="coerce").dt.year
    counts = reviews.dropna(subset=["_year"]).groupby("_year").size()
    return {str(int(y)): int(c) for y, c in counts.items()}


def get_watchlist_by_decade(data: dict) -> dict[str, int]:
    """Decade distribution of films on the watchlist."""
    wl = data["watchlist"].dropna(subset=["Year"]).copy()
    wl["_decade"] = (wl["Year"].astype(int) // 10 * 10).astype(str) + "s"
    counts = wl.groupby("_decade").size().sort_index()
    return {k: int(v) for k, v in counts.items()}


# ── TMDB-powered stats ──────────────────────────────────────────────────────────

def get_most_watched_directors(data: dict, n: int = 15) -> list[dict]:
    """
    Top-n directors by number of watched films.
    Requires TMDB_API_KEY; returns an empty list otherwise.
    """
    api_key = get_tmdb_api_key()
    if not api_key:
        warnings.warn("TMDB_API_KEY not set — director stats unavailable.", stacklevel=2)
        return []

    metas   = _enrich(data["watched"], api_key)
    counter: Counter = Counter()
    for meta in metas:
        if meta:
            counter.update(meta["directors"])
    return [{"director": d, "count": c} for d, c in counter.most_common(n)]


def get_favorite_genres(data: dict, n: int = 10) -> list[dict]:
    """
    Top-n genres by watch count, each annotated with the user's average rating
    for films in that genre.
    Requires TMDB_API_KEY; returns an empty list otherwise.
    """
    api_key = get_tmdb_api_key()
    if not api_key:
        warnings.warn("TMDB_API_KEY not set — genre stats unavailable.", stacklevel=2)
        return []

    watched  = data["watched"]
    ratings  = data["ratings"].set_index(["Name", "Year"])["Rating"]
    metas    = _enrich(watched, api_key)

    genre_counts:  Counter        = Counter()
    genre_ratings: dict[str, list] = {}

    for (_, row), meta in zip(watched.iterrows(), metas):
        if not meta:
            continue
        key = (row["Name"], row.get("Year"))
        for g in meta["genres"]:
            genre_counts[g] += 1
            if key in ratings.index:
                genre_ratings.setdefault(g, []).append(float(ratings[key]))

    result = []
    for genre, count in genre_counts.most_common(n):
        rs  = genre_ratings.get(genre, [])
        avg = round(sum(rs) / len(rs), 2) if rs else None
        result.append({"genre": genre, "count": count, "avg_rating": avg})
    return result


def get_favorite_actors(data: dict, n: int = 15) -> list[dict]:
    """
    Top-n actors by number of watched films they appear in (top-10 cast per film).
    Requires TMDB_API_KEY; returns an empty list otherwise.
    """
    api_key = get_tmdb_api_key()
    if not api_key:
        warnings.warn("TMDB_API_KEY not set — actor stats unavailable.", stacklevel=2)
        return []

    metas   = _enrich(data["watched"], api_key)
    counter: Counter = Counter()
    for meta in metas:
        if meta:
            counter.update(meta["cast"])
    return [{"actor": a, "count": c} for a, c in counter.most_common(n)]


def get_runtime_stats(data: dict) -> dict:
    """
    Average and total runtime across watched films.
    Requires TMDB_API_KEY; returns None values otherwise.
    """
    api_key = get_tmdb_api_key()
    if not api_key:
        return {"average_minutes": None, "total_hours": None}

    metas    = _enrich(data["watched"], api_key)
    runtimes = [m["runtime"] for m in metas if m and m.get("runtime")]
    if not runtimes:
        return {"average_minutes": None, "total_hours": None}
    return {
        "average_minutes": round(sum(runtimes) / len(runtimes), 1),
        "total_hours":     round(sum(runtimes) / 60, 1),
    }


def get_film_length_categories(data: dict) -> dict | None:
    """
    Breaks watched films into Short / Medium / Long by runtime.
      Short  : < 60 min
      Medium : 60–120 min
      Long   : > 120 min
    Requires TMDB_API_KEY; returns None otherwise.
    """
    api_key = get_tmdb_api_key()
    if not api_key:
        return None

    metas = _enrich(data["watched"], api_key)
    cats: dict[str, int] = {"Short (< 60 min)": 0, "Medium (60-120 min)": 0, "Long (> 120 min)": 0}
    for meta in metas:
        if not meta or not meta.get("runtime"):
            continue
        rt = meta["runtime"]
        if rt < 60:
            cats["Short (< 60 min)"]   += 1
        elif rt <= 120:
            cats["Medium (60-120 min)"] += 1
        else:
            cats["Long (> 120 min)"]   += 1
    return cats


def get_country_distribution(data: dict, n: int = 15) -> list[dict] | None:
    """
    Top-n production countries across watched films.
    Requires TMDB_API_KEY; returns None otherwise.
    """
    api_key = get_tmdb_api_key()
    if not api_key:
        return None

    metas   = _enrich(data["watched"], api_key)
    counter: Counter = Counter()
    for meta in metas:
        if meta and meta.get("countries"):
            counter.update(meta["countries"])
    return [{"country": c, "count": v} for c, v in counter.most_common(n)]


def get_gender_distribution(data: dict) -> dict | None:
    """
    Gender split across directors and cast of watched films.
    TMDB gender codes: 1 = female, 2 = male, 0/3 = other / not specified.
    Requires TMDB_API_KEY; returns None otherwise.
    """
    api_key = get_tmdb_api_key()
    if not api_key:
        return None

    metas = _enrich(data["watched"], api_key)
    dir_g: Counter  = Counter()
    cast_g: Counter = Counter()
    for meta in metas:
        if not meta:
            continue
        for g in meta.get("director_genders", []):
            dir_g[g] += 1
        for g in meta.get("cast_genders", []):
            cast_g[g] += 1

    def _breakdown(counter: Counter) -> dict:
        total = sum(counter.values())
        female = counter.get(1, 0)
        male   = counter.get(2, 0)
        other  = total - female - male
        return {
            "female":     female,
            "male":       male,
            "other":      other,
            "total":      total,
            "female_pct": round(female / total * 100, 1) if total else 0,
            "male_pct":   round(male   / total * 100, 1) if total else 0,
            "other_pct":  round(other  / total * 100, 1) if total else 0,
        }

    return {
        "directors": _breakdown(dir_g),
        "cast":      _breakdown(cast_g),
    }


def get_current_year_films(data: dict) -> dict:
    """
    Films released in the current calendar year that the user has watched.
    Works offline (no TMDB needed).
    """
    import datetime
    year    = datetime.date.today().year
    watched = data["watched"]
    current = watched[watched["Year"] == year][["Name", "Year"]].copy()

    ratings = data["ratings"][["Name", "Year", "Rating"]]
    merged  = current.merge(ratings, on=["Name", "Year"], how="left")
    merged  = merged.sort_values("Rating", ascending=False)

    return {
        "year":  year,
        "count": int(len(current)),
        "films": merged.to_dict(orient="records"),
    }



# ── Watched: deeper insights ────────────────────────────────────────────────────

def get_top_rated_directors(data: dict, n: int = 12, min_films: int = 4) -> list[dict]:
    """
    Directors ranked by the user's own average rating for their films.
    Only directors with at least *min_films* entries are included.
    Requires TMDB_API_KEY; returns an empty list otherwise.
    """
    api_key = get_tmdb_api_key()
    if not api_key:
        return []

    watched  = data["watched"]
    ratings  = data["ratings"].set_index(["Name", "Year"])["Rating"]
    metas    = _enrich(watched, api_key)

    dir_films:   dict[str, int]         = {}
    dir_ratings: dict[str, list[float]] = {}

    for (_, row), meta in zip(watched.iterrows(), metas):
        if not meta:
            continue
        key = (row["Name"], row.get("Year"))
        film_rating = ratings.get(key)
        for director in meta.get("directors", []):
            dir_films[director] = dir_films.get(director, 0) + 1
            if pd.notna(film_rating):
                dir_ratings.setdefault(director, []).append(float(film_rating))

    result = []
    for director, film_count in dir_films.items():
        if film_count < min_films:
            continue
        rs  = dir_ratings.get(director, [])
        avg = round(sum(rs) / len(rs), 2) if rs else None
        result.append({
            "director":   director,
            "films":      film_count,
            "rated":      len(rs),
            "avg_rating": avg,
        })

    result.sort(key=lambda x: (-(x["avg_rating"] or 0), -x["films"]))
    return result[:n]


def get_low_popularity_watched(data: dict, n: int = 20) -> list[dict]:
    """
    Watched films sorted by TMDB popularity ascending — the most obscure picks.
    Includes the user's own rating and TMDB vote average for each film.
    Requires TMDB_API_KEY; returns an empty list otherwise.
    """
    api_key = get_tmdb_api_key()
    if not api_key:
        return []

    watched = data["watched"]
    ratings = data["ratings"].set_index(["Name", "Year"])["Rating"]
    metas   = _enrich(watched, api_key)

    films: list[dict] = []
    for (_, row), meta in zip(watched.iterrows(), metas):
        if not meta or meta.get("popularity") is None:
            continue
        key         = (row["Name"], row.get("Year"))
        user_rating = ratings.get(key)
        films.append({
            "name":         str(row["Name"]),
            "year":         int(row["Year"]) if pd.notna(row.get("Year")) else None,
            "popularity":   round(float(meta["popularity"]), 2),
            "vote_average": round(float(meta.get("vote_average") or 0), 1),
            "rating":       round(float(user_rating), 1) if pd.notna(user_rating) else None,
        })

    films.sort(key=lambda x: x["popularity"])
    return films[:n]


# ── Watchlist deep analysis ─────────────────────────────────────────────────────

def get_watchlist_analysis(data: dict) -> dict:
    """
    Offline-only watchlist analysis.

    Returned keys
    -------------
    total               int
    decades             {decade_str: count}
    recently_added      [{Name, Year, date_str}]   (last 15 added)
    """
    wl = data["watchlist"].copy()

    total = int(len(wl))

    wl["_date"] = pd.to_datetime(wl["Date"], errors="coerce")
    recently_added = (
        wl.sort_values("_date", ascending=False)
        .head(15)
        .assign(date_str=lambda d: d["_date"].dt.strftime("%Y-%m-%d"))
        [["Name", "Year", "date_str"]]
        .to_dict(orient="records")
    )

    wl_yr = wl.dropna(subset=["Year"]).copy()
    wl_yr["_decade"] = (wl_yr["Year"].astype(int) // 10 * 10).astype(str) + "s"
    decade_counts = wl_yr.groupby("_decade").size().sort_index()
    decades = {k: int(v) for k, v in decade_counts.items()}

    return {
        "total":          total,
        "decades":        decades,
        "recently_added": recently_added,
    }


# ── Diary-year helpers ──────────────────────────────────────────────────────────

def get_diary_years(data: dict) -> list[int]:
    """Return a descending list of calendar years present in the diary."""
    diary = data["diary"].copy()
    diary["_year"] = pd.to_datetime(diary["Watched Date"], errors="coerce").dt.year
    years = sorted(diary["_year"].dropna().unique().astype(int), reverse=True)
    return [int(y) for y in years]


def filter_data_by_diary_year(data: dict, year: int) -> dict:
    """Return a copy of *data* scoped to diary entries logged in *year*."""
    diary = data["diary"].copy()
    diary["_date"] = pd.to_datetime(diary["Watched Date"], errors="coerce")
    diary_yr = diary[diary["_date"].dt.year == year].drop(columns=["_date"]).reset_index(drop=True)

    # Deduplicated (Name, Year) keys watched in this diary year
    keys = diary_yr[["Name", "Year"]].drop_duplicates()
    watched_yr = data["watched"].merge(keys, on=["Name", "Year"], how="inner").reset_index(drop=True)
    ratings_yr = data["ratings"].merge(keys, on=["Name", "Year"], how="inner").reset_index(drop=True)

    rev = data["reviews"].copy()
    rev["_y"] = pd.to_datetime(rev["Date"], errors="coerce").dt.year
    reviews_yr = rev[rev["_y"] == year].drop(columns=["_y"]).reset_index(drop=True)

    return {
        **data,
        "diary":   diary_yr,
        "watched": watched_yr,
        "ratings": ratings_yr,
        "reviews": reviews_yr,
    }


# ── Master aggregator ───────────────────────────────────────────────────────────

def get_all_stats(data: dict) -> dict:
    """
    Run all analysis functions and return a single JSON-serialisable dict.
    TMDB sections are populated only when TMDB_API_KEY is available.
    """
    steps = [
        ("Profile",              lambda: get_profile_info(data)),
        ("Rating distribution",  lambda: get_rating_distribution(data)),
        ("Activity by year",     lambda: get_activity_by_year(data)),
        ("Favorite years",       lambda: get_favorite_years(data)),
        ("Activity by month",    lambda: get_activity_by_month(data)),
        ("Decade breakdown",     lambda: get_decade_breakdown(data)),
        ("Top-rated films",      lambda: get_top_rated_films(data)),
        ("Lowest-rated films",   lambda: get_lowest_rated_films(data)),
        ("Rewatch stats",        lambda: get_rewatch_stats(data)),
        ("Tags",                 lambda: get_tag_breakdown(data)),
        ("Liked films",          lambda: get_liked_films(data)),
        ("Reviews over time",    lambda: get_reviews_over_time(data)),
        ("Watchlist decades",    lambda: get_watchlist_by_decade(data)),
        ("Current year films",   lambda: get_current_year_films(data)),
        ("Directors (TMDB)",     lambda: get_most_watched_directors(data)),
        ("Genres (TMDB)",        lambda: get_favorite_genres(data)),
        ("Actors (TMDB)",        lambda: get_favorite_actors(data)),
        ("Runtimes (TMDB)",      lambda: get_runtime_stats(data)),
        ("Film lengths (TMDB)",  lambda: get_film_length_categories(data)),
        ("Countries (TMDB)",     lambda: get_country_distribution(data)),
        ("Gender split (TMDB)",  lambda: get_gender_distribution(data)),
        ("Watchlist analysis",         lambda: get_watchlist_analysis(data)),
        ("Top-rated directors (TMDB)", lambda: get_top_rated_directors(data)),
        ("Low-popularity watched (TMDB)", lambda: get_low_popularity_watched(data)),
        ("Hero data (TMDB)",               lambda: get_hero_data(data)),
    ]

    results: dict = {}
    keys = [
        "profile", "rating_distribution", "activity_by_year", "favorite_years", "activity_by_month",
        "decade_breakdown", "top_rated_films", "lowest_rated_films", "rewatch_stats",
        "tag_breakdown", "liked_films", "reviews_over_time", "watchlist_by_decade",
        "current_year_films",
        "directors", "genres", "actors", "runtime_stats",
        "film_lengths", "countries", "gender_distribution",
        "watchlist_analysis", "top_rated_directors", "low_popularity_watched",
        "hero_data",
    ]

    for (label, fn), key in zip(steps, keys):
        print(f"{label}...")
        results[key] = fn()

    results["tmdb_enabled"] = bool(get_tmdb_api_key())

    # ── Per-year stats (used by year-filter buttons in the HTML report) ─────────
    diary_years = get_diary_years(data)
    results["diary_years"] = diary_years
    per_year: dict = {}
    for yr in diary_years:
        print(f"  Year {yr}...")
        yd = filter_data_by_diary_year(data, yr)
        per_year[str(yr)] = {
            "profile":                get_profile_info(yd),
            "rating_distribution":    get_rating_distribution(yd),
            "activity_by_year":       get_activity_by_year(yd),
            "activity_by_month":      get_activity_by_month(yd),
            "decade_breakdown":       get_decade_breakdown(yd),
            "top_rated_films":        get_top_rated_films(yd),
            "rewatch_stats":          get_rewatch_stats(yd),
            "tag_breakdown":          get_tag_breakdown(yd),
            "reviews_over_time":      get_reviews_over_time(yd),
            "favorite_years":         get_favorite_years(yd),
            "directors":              get_most_watched_directors(yd),
            "genres":                 get_favorite_genres(yd),
            "actors":                 get_favorite_actors(yd),
            "runtime_stats":          get_runtime_stats(yd),
            "film_lengths":           get_film_length_categories(yd),
            "countries":              get_country_distribution(yd),
            "gender_distribution":    get_gender_distribution(yd),
            "low_popularity_watched": get_low_popularity_watched(yd),
            "top_rated_directors":    get_top_rated_directors(yd),
            "tmdb_enabled":           bool(get_tmdb_api_key()),
        }
    results["per_year_stats"] = per_year

    print("Done.")
    return results


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        candidates = sorted((_ROOT_DIR / "data").glob("*.zip"))
        if not candidates:
            print("Usage: python -m src.analyzer <export.zip>", file=sys.stderr)
            sys.exit(1)
        _zip = candidates[0]
    else:
        _zip = Path(sys.argv[1])
    data  = load_data(_zip)
    stats = get_all_stats(data)
    out   = _ROOT_DIR / "output" / "stats.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(stats, indent=2, default=str), encoding="utf-8")
    print(f"\nStats written to {out}")
