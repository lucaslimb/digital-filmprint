"""
generate_report.py
------------------
Reads Letterboxd export data, runs all analysis via analyzer.py, and writes
a self-contained HTML dashboard to report.html.
"""

import json
import sys
from pathlib import Path

from analyzer import load_data, get_all_stats


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _j(obj) -> str:
    """Serialize a Python object to a JSON string for embedding in HTML/JS."""
    return json.dumps(obj, default=str)


def _stars(rating: float) -> str:
    """Convert a numeric rating (0.5–5) to a UTF-8 star string."""
    full  = int(rating)
    half  = 1 if (rating - full) >= 0.5 else 0
    empty = 5 - full - half
    return "★" * full + "½" * half + "☆" * empty


def _section(title: str, icon: str, content: str, extra_class: str = "") -> str:
    return f"""
    <section class="card {extra_class}">
        <h2 class="section-title"><span class="icon">{icon}</span>{title}</h2>
        {content}
    </section>"""


def _no_data_msg(label: str = "No data") -> str:
    return f'<p class="no-data">{label} — set TMDB_API_KEY to enable this section.</p>'


def _zone_divider(title: str, icon: str, accent: str = "var(--accent)") -> str:
    """Full-width zone header that visually separates major page sections."""
    return f'<div class="zone-divider" style="--zone-accent:{accent}"><span class="zone-icon">{icon}</span><h2 class="zone-title">{title}</h2></div>'


# ── Section builders ─────────────────────────────────────────────────────────────

def _build_overview_cards(p: dict) -> str:
    cards = [
        ("Films watched",  str(p["total_watched"]),  "🎬"),
        ("Avg rating",     f"{p['average_rating']} ★" if p["average_rating"] else "—", "⭐"),
        ("Films rated",    str(p["total_rated"]),     "🗳"),
        ("Reviews",        str(p["total_reviews"]),   "✍"),
        ("Liked",          str(p["total_liked"]),     "❤"),
        ("Rewatches",      str(p["total_rewatches"]), "🔁"),
        ("On watchlist",   str(p["watchlist_size"]),  "📋"),
    ]
    items = "".join(
        f'<div class="stat-card"><span class="stat-icon">{icon}</span>'
        f'<span class="stat-value">{value}</span>'
        f'<span class="stat-label">{label}</span></div>'
        for label, value, icon in cards
    )
    return f'<div class="stat-grid">{items}</div>'


def _build_rating_chart(dist: dict) -> str:
    if not dist:
        return _no_data_msg("No ratings found")
    labels  = list(dist.keys())
    values  = list(dist.values())
    n = len(labels)
    colors = [
        f'rgba({round(60 + i/max(n-1,1)*(0-60))},{round(100 + i/max(n-1,1)*(192-100))},{round(60 + i/max(n-1,1)*(48-60))},0.85)'
        for i in range(n)
    ]
    return f"""
    <div class="chart-wrap">
        <canvas id="chartRatings"></canvas>
    </div>
    <script>
    new Chart(document.getElementById('chartRatings'), {{
        type: 'bar',
        data: {{
            labels: {_j(labels)},
            datasets: [{{
                label: 'Films',
                data: {_j(values)},
                backgroundColor: {_j(colors)},
                borderWidth: 0,
                borderRadius: 4,
            }}]
        }},
        options: {{
            responsive: true,
            plugins: {{
                legend: {{ display: false }},
                tooltip: {{ callbacks: {{ title: t => t[0].label + ' \u2605' }} }}
            }},
            scales: {{
                y: {{ beginAtZero: true, ticks: {{ color: '#888' }}, grid: {{ color: '#252525' }} }},
                x: {{ ticks: {{ color: '#888' }}, grid: {{ display: false }} }}
            }}
        }}
    }});
    </script>"""


def _build_year_chart(by_year: dict) -> str:
    if not by_year:
        return _no_data_msg("No diary dates found")
    labels = [str(y) for y in by_year.keys()]
    values = list(by_year.values())
    return f"""
    <div class="chart-wrap">
        <canvas id="chartYear"></canvas>
    </div>
    <script>
    new Chart(document.getElementById('chartYear'), {{
        type: 'bar',
        data: {{
            labels: {_j(labels)},
            datasets: [{{
                label: 'Films watched',
                data: {_j(values)},
                backgroundColor: 'rgba(0,192,48,0.75)',
                borderColor:     'rgba(0,224,84,1)',
                borderWidth: 1,
                borderRadius: 4,
            }}]
        }},
        options: {{
            responsive: true,
            plugins: {{ legend: {{ display: false }} }},
            scales: {{
                y: {{ beginAtZero: true, ticks: {{ color: '#888' }}, grid: {{ color: '#252525' }} }},
                x: {{ ticks: {{ color: '#888' }}, grid: {{ display: false }} }}
            }}
        }}
    }});
    </script>"""


def _build_decade_chart(decades: dict) -> str:
    if not decades:
        return _no_data_msg("No decade data")
    labels = list(decades.keys())
    values = list(decades.values())
    palette = [
        "#e8c04a","#e8944a","#e85a4a","#c04ae8","#4a7ae8",
        "#4ac8e8","#4ae87a","#a0e84a","#e8e84a","#e8604a",
    ]
    return f"""
    <div class="chart-wrap">
        <canvas id="chartDecade"></canvas>
    </div>
    <script>
    new Chart(document.getElementById('chartDecade'), {{
        type: 'bar',
        data: {{
            labels: {_j(labels)},
            datasets: [{{
                label: 'Films',
                data: {_j(values)},
                backgroundColor: {_j((palette * 4)[:len(labels)])},
                borderWidth: 0,
                borderRadius: 4,
            }}]
        }},
        options: {{
            indexAxis: 'y',
            responsive: true,
            plugins: {{ legend: {{ display: false }} }},
            scales: {{
                x: {{ beginAtZero: true, ticks: {{ color: '#888' }}, grid: {{ color: '#252525' }} }},
                y: {{ ticks: {{ color: '#ccc' }}, grid: {{ display: false }} }}
            }}
        }}
    }});
    </script>"""


def _build_month_chart(by_month: dict) -> str:
    if not by_month:
        return _no_data_msg("No monthly data")
    labels = list(by_month.keys())
    values = list(by_month.values())
    return f"""
    <div class="chart-wrap">
        <canvas id="chartMonth"></canvas>
    </div>
    <script>
    new Chart(document.getElementById('chartMonth'), {{
        type: 'bar',
        data: {{
            labels: {_j(labels)},
            datasets: [{{
                label: 'Films',
                data: {_j(values)},
                backgroundColor: 'rgba(232,192,74,0.8)',
                borderColor:     'rgba(232,192,74,1)',
                borderWidth: 1,
                borderRadius: 4,
            }}]
        }},
        options: {{
            responsive: true,
            plugins: {{ legend: {{ display: false }} }},
            scales: {{
                y: {{ beginAtZero: true, ticks: {{ color: '#888' }}, grid: {{ color: '#252525' }} }},
                x: {{ ticks: {{ color: '#888' }}, grid: {{ display: false }} }}
            }}
        }}
    }});
    </script>"""


def _build_directors_section(directors: list) -> str:
    if not directors:
        return _no_data_msg()
    top = directors[:12]
    labels = [d["director"] for d in top]
    values = [d["count"]    for d in top]
    return f"""
    <div class="chart-wrap chart-wrap--tall">
        <canvas id="chartDirectors"></canvas>
    </div>
    <script>
    new Chart(document.getElementById('chartDirectors'), {{
        type: 'bar',
        data: {{
            labels: {_j(labels)},
            datasets: [{{
                label: 'Films watched',
                data: {_j(values)},
                backgroundColor: 'rgba(74,160,232,0.8)',
                borderColor:     'rgba(74,160,232,1)',
                borderWidth: 1,
                borderRadius: 4,
            }}]
        }},
        options: {{
            indexAxis: 'y',
            responsive: true,
            plugins: {{ legend: {{ display: false }} }},
            scales: {{
                x: {{ beginAtZero: true, ticks: {{ color: '#888', stepSize: 1 }}, grid: {{ color: '#252525' }} }},
                y: {{ ticks: {{ color: '#ddd' }}, grid: {{ display: false }} }}
            }}
        }}
    }});
    </script>"""


def _build_genres_section(genres: list) -> str:
    if not genres:
        return _no_data_msg()
    labels   = [g["genre"]      for g in genres]
    counts   = [g["count"]      for g in genres]
    avgs     = [g["avg_rating"] or 0 for g in genres]
    palette  = ["#e8c04a","#00c030","#4a7ae8","#e85a4a","#c04ae8",
                "#4ac8e8","#e8944a","#4ae87a","#a0e84a","#e86c4a"]
    rows = "".join(
        f'<tr><td>{g["genre"]}</td><td class="num">{g["count"]}</td>'
        f'<td class="num rating-val">'
        f'{g["avg_rating"] if g["avg_rating"] else "—"}'
        f'{"★" if g["avg_rating"] else ""}</td></tr>'
        for g in genres
    )
    return f"""
    <div class="genres-layout">
        <div class="chart-wrap chart-wrap--square">
            <canvas id="chartGenres"></canvas>
        </div>
        <table class="data-table">
            <thead><tr><th>Genre</th><th>Films</th><th>Avg ★</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </div>
    <script>
    new Chart(document.getElementById('chartGenres'), {{
        type: 'doughnut',
        data: {{
            labels: {_j(labels)},
            datasets: [{{
                data: {_j(counts)},
                backgroundColor: {_j(palette[:len(labels)])},
                borderColor: '#161618',
                borderWidth: 2,
            }}]
        }},
        options: {{
            responsive: true,
            plugins: {{
                legend: {{
                    position: 'bottom',
                    labels: {{ color: '#ccc', padding: 14, boxWidth: 12 }}
                }}
            }}
        }}
    }});
    </script>"""


def _build_actors_section(actors: list) -> str:
    if not actors:
        return _no_data_msg()
    items = "".join(
        f'<div class="actor-chip">'
        f'<span class="actor-name">{a["actor"]}</span>'
        f'<span class="actor-count">{a["count"]}</span>'
        f'</div>'
        for a in actors
    )
    return f'<div class="actor-grid">{items}</div>'


def _build_top_rated_table(films: list) -> str:
    rows = "".join(
        f'<tr>'
        f'<td class="rank">#{i+1}</td>'
        f'<td class="film-name">{f["Name"]}</td>'
        f'<td class="film-year">{int(f["Year"]) if f["Year"] else "—"}</td>'
        f'<td class="stars">{_stars(float(f["Rating"]))}</td>'
        f'<td class="num">{f["Rating"]}</td>'
        f'</tr>'
        for i, f in enumerate(films)
    )
    return f"""
    <table class="data-table">
        <thead><tr><th>#</th><th>Film</th><th>Year</th><th>Stars</th><th>Rating</th></tr></thead>
        <tbody>{rows}</tbody>
    </table>"""


def _build_rewatch_section(rw: dict) -> str:
    items = "".join(
        f'<div class="rewatch-item">'
        f'<span class="film-name">{f["name"]}</span>'
        f'<span class="rewatch-badge">×{f["count"]}</span>'
        f'</div>'
        for f in rw["most_rewatched"]
    )
    return f"""
    <p class="section-sub">Total rewatch entries: <strong>{rw["total_rewatches"]}</strong></p>
    <div class="rewatch-list">{items}</div>"""


def _build_tags_section(tags: dict) -> str:
    if not tags:
        return "<p class='no-data'>No custom tags found.</p>"
    max_count = max(tags.values())
    items = "".join(
        f'<span class="tag-chip" style="font-size:{0.7 + 0.9*(c/max_count):.2f}rem;'
        f'opacity:{0.5 + 0.5*(c/max_count):.2f}">'
        f'{tag} <sup>{c}</sup></span>'
        for tag, c in tags.items()
    )
    return f'<div class="tag-cloud">{items}</div>'


def _build_liked_section(films: list) -> str:
    items = "".join(
        f'<div class="liked-item"><span class="liked-heart">❤</span>'
        f'<span class="liked-name">{f["Name"]}</span>'
        f'<span class="liked-year">{int(f["Year"]) if f["Year"] else ""}</span>'
        f'</div>'
        for f in films
    )
    return f'<div class="liked-grid">{items}</div>'


def _build_runtime_section(rt: dict) -> str:
    if not rt["total_hours"]:
        return _no_data_msg("Runtime data unavailable")
    days  = round(rt["total_hours"] / 24, 1)
    return f"""
    <div class="runtime-stats">
        <div class="runtime-card">
            <span class="runtime-value">{rt['total_hours']}h</span>
            <span class="runtime-label">Total screen time</span>
            <span class="runtime-sub">≈ {days} full days</span>
        </div>
        <div class="runtime-card">
            <span class="runtime-value">{rt['average_minutes']}m</span>
            <span class="runtime-label">Avg film length</span>
        </div>
    </div>"""


def _build_reviews_chart(reviews: dict) -> str:
    if not reviews:
        return "<p class='no-data'>No reviews found.</p>"
    labels = list(reviews.keys())
    values = list(reviews.values())
    return f"""
    <div class="chart-wrap chart-wrap--short">
        <canvas id="chartReviews"></canvas>
    </div>
    <script>
    new Chart(document.getElementById('chartReviews'), {{
        type: 'bar',
        data: {{
            labels: {_j(labels)},
            datasets: [{{
                label: 'Reviews written',
                data: {_j(values)},
                backgroundColor: 'rgba(192,74,232,0.8)',
                borderColor:     'rgba(192,74,232,1)',
                borderWidth: 1,
                borderRadius: 4,
            }}]
        }},
        options: {{
            responsive: true,
            plugins: {{ legend: {{ display: false }} }},
            scales: {{
                y: {{ beginAtZero: true, ticks: {{ color:'#888', stepSize:1 }}, grid:{{ color:'#252525' }} }},
                x: {{ ticks:{{ color:'#888' }}, grid:{{ display:false }} }}
            }}
        }}
    }});
    </script>"""


def _build_film_lengths_chart(lengths: dict | None) -> str:
    if not lengths:
        return _no_data_msg()
    labels = list(lengths.keys())
    values = list(lengths.values())
    colours = ["#4ac8e8", "#00c030", "#e8c04a"]
    total = sum(values)
    pct_items = "".join(
        f'<div class="len-item">'
        f'<span class="len-dot" style="background:{colours[i % 3]}"></span>'
        f'<span class="len-label">{lbl}</span>'
        f'<span class="len-val">{v} <span class="len-pct">({round(v/total*100) if total else 0}%)</span></span>'
        f'</div>'
        for i, (lbl, v) in enumerate(zip(labels, values))
    )
    return f"""
    <div class="lengths-layout">
        <div class="chart-wrap chart-wrap--square">
            <canvas id="chartLengths"></canvas>
        </div>
        <div class="len-legend">{pct_items}</div>
    </div>
    <script>
    new Chart(document.getElementById('chartLengths'), {{
        type: 'doughnut',
        data: {{
            labels: {_j(labels)},
            datasets: [{{
                data: {_j(values)},
                backgroundColor: {_j(colours)},
                borderColor: '#161618',
                borderWidth: 3,
            }}]
        }},
        options: {{
            responsive: true,
            cutout: '65%',
            plugins: {{
                legend: {{ display: false }},
                tooltip: {{
                    callbacks: {{
                        label: ctx => ` ${{ctx.parsed}} films (${{Math.round(ctx.parsed / {total} * 100)}}%)`
                    }}
                }}
            }}
        }}
    }});
    </script>"""


def _build_country_chart(countries: list | None) -> str:
    if not countries:
        return _no_data_msg()
    top    = countries[:15]
    labels = [c["country"] for c in top]
    values = [c["count"]   for c in top]
    return f"""
    <div class="chart-wrap chart-wrap--tall">
        <canvas id="chartCountries"></canvas>
    </div>
    <script>
    new Chart(document.getElementById('chartCountries'), {{
        type: 'bar',
        data: {{
            labels: {_j(labels)},
            datasets: [{{
                label: 'Films',
                data: {_j(values)},
                backgroundColor: 'rgba(74,200,232,0.8)',
                borderColor:     'rgba(74,200,232,1)',
                borderWidth: 1,
                borderRadius: 4,
            }}]
        }},
        options: {{
            indexAxis: 'y',
            responsive: true,
            plugins: {{ legend: {{ display: false }} }},
            scales: {{
                x: {{ beginAtZero: true, ticks: {{ color: '#888', stepSize: 1 }}, grid: {{ color: '#252525' }} }},
                y: {{ ticks: {{ color: '#ddd' }}, grid: {{ display: false }} }}
            }}
        }}
    }});
    </script>"""


def _build_gender_section(gender: dict | None) -> str:
    if not gender:
        return _no_data_msg()

    def _bar(label: str, g: dict, canvas_id: str) -> str:
        d_labels = ["Female", "Male", "Other/N.A."]
        d_values = [g["female"], g["male"], g["other"]]
        d_pcts   = [g["female_pct"], g["male_pct"], g["other_pct"]]
        d_colors = ["#e84a9a", "#4a7ae8", "#888"]
        pct_items = "".join(
            f'<div class="gender-row">'
            f'<span class="gender-dot" style="background:{d_colors[i]}"></span>'
            f'<span class="gender-label">{lbl}</span>'
            f'<div class="gender-bar-bg"><div class="gender-bar-fill" style="width:{pct}%;background:{d_colors[i]}"></div></div>'
            f'<span class="gender-pct">{pct}%</span>'
            f'<span class="gender-count">({v})</span>'
            f'</div>'
            for i, (lbl, v, pct) in enumerate(zip(d_labels, d_values, d_pcts))
        )
        return f'<div class="gender-block"><h3 class="gender-subtitle">{label}</h3>{pct_items}</div>'

    dirs  = _bar("Directors", gender["directors"], "genderDirs")
    cast  = _bar("Cast (top 10 per film)", gender["cast"], "genderCast")
    return f'<div class="gender-layout">{dirs}{cast}</div>'


def _build_current_year_section(cy: dict) -> str:
    year  = cy["year"]
    count = cy["count"]
    films = cy["films"]
    if count == 0:
        return f'<p class="no-data">No {year} releases in your watched list yet.</p>'
    rows = "".join(
        f'<tr>'
        f'<td class="rank">#{i+1}</td>'
        f'<td class="film-name">{f["Name"]}</td>'
        f'<td class="stars">{_stars(float(f["Rating"])) if f.get("Rating") and str(f["Rating"]) != "nan" else ""}</td>'
        f'<td class="num">{f["Rating"] if f.get("Rating") and str(f["Rating"]) != "nan" else "—"}</td>'
        f'</tr>'
        for i, f in enumerate(films[:20])
    )
    return f"""
    <p class="section-sub">You have watched <strong>{count}</strong> films released in {year}.</p>
    <table class="data-table">
        <thead><tr><th>#</th><th>Film</th><th>Stars</th><th>Rating</th></tr></thead>
        <tbody>{rows}</tbody>
    </table>"""



# ── Watched: deeper insight builders ────────────────────────────────────────────

def _build_top_rated_directors_table(directors: list) -> str:
    if not directors:
        return _no_data_msg()
    rows = "".join(
        f'<tr>'
        f'<td class="rank">#{i+1}</td>'
        f'<td class="film-name">{d["director"]}</td>'
        f'<td class="num">{d["films"]}</td>'
        f'<td class="num">{d["rated"]}</td>'
        f'<td class="num rating-val">'
        f'{d["avg_rating"] if d["avg_rating"] else "—"}'
        f'{"★" if d["avg_rating"] else ""}'
        f'</td>'
        f'</tr>'
        for i, d in enumerate(directors)
    )
    return f"""
    <p class="section-sub">Ranked by your average rating (min. 2 films watched). TMDB-powered.</p>
    <table class="data-table">
        <thead><tr><th>#</th><th>Director</th><th>Films</th><th>Rated</th><th>Avg ★</th></tr></thead>
        <tbody>{rows}</tbody>
    </table>"""


def _build_watched_low_popularity_table(films: list) -> str:
    if not films:
        return _no_data_msg()
    max_pop = max((f["popularity"] for f in films), default=1) or 1

    def _pop_bar(pop: float) -> str:
        width = min(100, round(pop / max_pop * 100))
        h = int(40 + (pop / max_pop) * 50)
        return (
            f'<div class="pop-bar-bg">'
            f'<div class="pop-bar-fill" style="width:{width}%;background:hsl({h},80%,45%)"></div>'
            f'</div>'
        )

    rows = "".join(
        f'<tr>'
        f'<td class="rank">#{i+1}</td>'
        f'<td class="film-name">{f["name"]}</td>'
        f'<td class="film-year">{f["year"] or "—"}</td>'
        f'<td class="pop-cell">{_pop_bar(f["popularity"])}'
        f'  <span class="pop-score">{f["popularity"]}</span></td>'
        f'<td class="num">{f["vote_average"] if f["vote_average"] else "—"}'
        f'{"★" if f["vote_average"] else ""}</td>'
        f'<td class="stars">{_stars(float(f["rating"])) if f["rating"] else ""}</td>'
        f'<td class="num">{f["rating"] if f["rating"] else "—"}</td>'
        f'</tr>'
        for i, f in enumerate(films)
    )
    return f"""
    <p class="section-sub">Sorted by TMDB popularity <strong>ascending</strong> — the most obscure films you've watched.</p>
    <table class="data-table pop-table">
        <thead>
            <tr>
                <th>#</th><th>Film</th><th>Year</th>
                <th>Popularity</th><th>TMDB Avg</th><th>Stars</th><th>Your ★</th>
            </tr>
        </thead>
        <tbody>{rows}</tbody>
    </table>"""


# ── Watchlist section builder ────────────────────────────────────────────────────

def _build_watchlist_decade_chart(decades: dict) -> str:
    labels  = list(decades.keys())
    values  = list(decades.values())
    palette = ["#e8c04a","#e8944a","#e85a4a","#c04ae8","#4a7ae8",
               "#4ac8e8","#4ae87a","#a0e84a","#e8e84a","#4ac8d0"]
    return f"""
    <div class="chart-wrap chart-wrap--short">
        <canvas id="chartWlDecade"></canvas>
    </div>
    <script>
    new Chart(document.getElementById('chartWlDecade'), {{
        type: 'bar',
        data: {{
            labels: {_j(labels)},
            datasets: [{{
                label: 'Films',
                data:  {_j(values)},
                backgroundColor: {_j((palette * 4)[:len(labels)])},
                borderWidth: 0,
                borderRadius: 4,
            }}]
        }},
        options: {{
            responsive: true,
            plugins: {{ legend: {{ display: false }} }},
            scales: {{
                y: {{ beginAtZero: true, ticks: {{ color: '#888' }}, grid: {{ color: '#252525' }} }},
                x: {{ ticks: {{ color: '#888' }}, grid: {{ display: false }} }}
            }}
        }}
    }});
    </script>"""





def _build_recently_added(films: list) -> str:
    items = "".join(
        f'<div class="recent-item">'
        f'<span class="recent-name">{f["Name"]}</span>'
        f'<span class="recent-meta">'
        f'{int(f["Year"]) if f.get("Year") and str(f["Year"]) != "nan" else ""}'
        f'{"  ·  " if f.get("Year") and str(f["Year"]) != "nan" else ""}'
        f'<span class="recent-date">{f.get("date_str", "")}</span>'
        f'</span>'
        f'</div>'
        for f in films
    )
    return f'<div class="recent-list">{items}</div>'


def _build_watchlist_section(wl: dict, tmdb_on: bool) -> str:
    total    = wl["total"]
    decades  = wl["decades"]
    recently = wl["recently_added"]

    decade_html = _build_watchlist_decade_chart(decades) if decades else "<p class='no-data'>No data.</p>"
    recent_html = _build_recently_added(recently)

    return f"""
<section id="watchlist" class="watchlist-section">
  <div class="zone-divider" style="--zone-accent:#e8944a">
    <span class="zone-icon">📋</span>
    <h2 class="zone-title">My Watchlist</h2>
    <span class="wl-total-badge">{total} films</span>
  </div>

  <div class="grid-2">
    {_section("Watchlist by Release Decade", "🗓", decade_html)}
    {_section("Recently Added", "🕐", recent_html)}
  </div>

</section>"""


# ── Master HTML assembler ────────────────────────────────────────────────────────

def generate_html(stats: dict) -> str:
    p        = stats["profile"]
    username = p["username"] or "unknown"
    given    = p.get("given_name", "")
    family   = p.get("family_name", "")
    fullname = f"{given} {family}".strip() or username
    pronoun  = p.get("pronoun", "")
    location = p.get("location", "")
    bio      = p.get("bio", "")
    website  = p.get("website", "")
    joined   = p["date_joined"][:10] if p["date_joined"] else "—"
    joined_y = p["date_joined"][:4]  if p["date_joined"] else "—"
    fav_cnt  = p.get("favorite_films_count", 0)
    tmdb_on  = stats["tmdb_enabled"]

    # Hero meta pills
    meta_pills = ""
    if pronoun:
        meta_pills += f'<span class="hero-pill">{pronoun}</span>'
    if location:
        meta_pills += f'<span class="hero-pill">📍 {location}</span>'
    if website:
        safe_site = website if website.startswith("http") else f"https://{website}"
        meta_pills += f'<a class="hero-pill hero-pill--link" href="{safe_site}" target="_blank">🔗 {website}</a>'

    bio_block = f'<p class="hero-bio">{bio}</p>' if bio else ""

    tmdb_badge = (
        '<span class="badge badge--green">TMDB enriched</span>'
        if tmdb_on else
        '<span class="badge badge--dim">Set TMDB_API_KEY for full stats</span>'
    )

    # Hero 2×2 grid data
    hero = stats.get("hero_data") or {}
    fav_films    = hero.get("fav_films", [])
    top_director = hero.get("top_director")
    top_actor    = hero.get("top_actor")

    fav_posters_html = ""
    for f in fav_films[:4]:
        poster = f.get("poster")
        yr     = f"({f['year']})" if f.get("year") else ""
        if poster:
            fav_posters_html += (
                f'<div class="hero-poster">'
                f'<img src="{poster}" alt="{f["name"]}" loading="lazy">'
                f'<span class="hero-poster-label">{f["name"]} {yr}</span>'
                f'</div>'
            )
        else:
            fav_posters_html += (
                f'<div class="hero-poster hero-poster--empty">'
                f'<span class="hero-poster-label">{f["name"]} {yr}</span>'
                f'</div>'
            )

    def _person_card(person: dict | None, role_label: str) -> str:
        if not person:
            return f'<div class="hero-person"><p class="hero-person-empty">{role_label} data unavailable</p></div>'
        img = person.get("image")
        img_tag = f'<img src="{img}" alt="{person["name"]}" loading="lazy">' if img else '<div class="hero-person-nophoto">🎬</div>'
        return (
            f'<div class="hero-person">'
            f'{img_tag}'
            f'<div class="hero-person-info">'
            f'<span class="hero-person-role">{role_label}</span>'
            f'<span class="hero-person-name">{person["name"]}</span>'
            f'<span class="hero-person-count">{person["count"]} films</span>'
            f'</div>'
            f'</div>'
        )

    director_html = _person_card(top_director, "Favorite Director")
    actor_html    = _person_card(top_actor,    "Favorite Actor")

    overview_html        = _build_overview_cards(p)
    ratings_html         = _build_rating_chart(stats["rating_distribution"])
    year_html            = _build_year_chart(stats["activity_by_year"])
    decade_html          = _build_decade_chart(stats["decade_breakdown"])
    month_html           = _build_month_chart(stats["activity_by_month"])
    directors_html       = _build_directors_section(stats["directors"])
    genres_html          = _build_genres_section(stats["genres"])
    actors_html          = _build_actors_section(stats["actors"])
    top_rated_html       = _build_top_rated_table(stats["top_rated_films"])
    rewatch_html         = _build_rewatch_section(stats["rewatch_stats"])
    tags_html            = _build_tags_section(stats["tag_breakdown"])
    liked_html           = _build_liked_section(stats["liked_films"])
    runtime_html         = _build_runtime_section(stats["runtime_stats"])
    reviews_html         = _build_reviews_chart(stats["reviews_over_time"])
    lengths_html         = _build_film_lengths_chart(stats.get("film_lengths"))
    country_html         = _build_country_chart(stats.get("countries"))
    gender_html          = _build_gender_section(stats.get("gender_distribution"))
    cy_html              = _build_current_year_section(stats["current_year_films"])
    cy_year              = stats["current_year_films"]["year"]
    top_rated_dirs_html  = _build_top_rated_directors_table(stats.get("top_rated_directors") or [])
    low_pop_watched_html = _build_watched_low_popularity_table(stats.get("low_popularity_watched") or [])
    watchlist_html       = _build_watchlist_section(stats["watchlist_analysis"], tmdb_on)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{fullname}'s Film Habits — Letterboxd Wrapped</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  /* ── Reset & base ── */
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --bg:       #0c0c0e;
    --card:     #161618;
    --border:   #2c2c2e;
    --accent:   #00c030;
    --gold:     #e8c04a;
    --blue:     #4a7ae8;
    --pink:     #e84a9a;
    --text:     #f0f0f0;
    --muted:    #888;
    --dim:      #444;
    --radius:   12px;
  }}
  html {{ scroll-behavior: smooth; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 15px;
    line-height: 1.6;
    padding: 0 0 60px;
  }}

  /* ── Header ── */
  .hero {{
    background: linear-gradient(160deg, #111116 0%, #0c0c0e 60%, #0a120a 100%);
    border-bottom: 1px solid var(--border);
    padding: 40px 24px 32px;
    position: relative;
    overflow: hidden;
  }}
  .hero::before {{
    content: "🎞";
    position: absolute;
    font-size: 200px;
    opacity: 0.03;
    top: -30px; left: 50%; transform: translateX(-50%);
    pointer-events: none;
  }}
  .hero-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 24px;
    max-width: 1100px;
    margin: 0 auto;
  }}
  @media (max-width: 740px) {{
    .hero-grid {{ grid-template-columns: 1fr; }}
  }}
  .hero-profile {{
    display: flex;
    flex-direction: column;
    justify-content: center;
  }}
  .hero-title {{
    font-size: clamp(1.6rem, 4vw, 2.6rem);
    font-weight: 800;
    letter-spacing: -1px;
    color: var(--text);
  }}
  .hero-title span {{ color: var(--accent); }}
  .hero-fullname {{
    font-size: 1rem;
    color: var(--muted);
    margin-top: 4px;
    font-weight: 400;
  }}
  .hero-fullname strong {{ color: var(--gold); font-weight: 600; }}
  .hero-bio {{
    max-width: 480px;
    margin: 10px 0 0;
    font-size: 0.88rem;
    color: var(--muted);
    font-style: italic;
    line-height: 1.5;
  }}
  .hero-pills {{
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-top: 12px;
  }}
  .hero-pill {{
    background: rgba(255,255,255,0.05);
    border: 1px solid var(--border);
    border-radius: 99px;
    padding: 4px 14px;
    font-size: 0.8rem;
    color: var(--muted);
    text-decoration: none;
  }}
  .hero-pill--link {{ color: var(--blue); border-color: rgba(74,122,232,0.3); }}
  .hero-pill--link:hover {{ background: rgba(74,122,232,0.1); }}
  .hero-joined {{
    font-size: 0.82rem;
    color: var(--dim);
    margin-top: 10px;
  }}
  .hero-joined strong {{ color: var(--muted); }}
  .hero-badges {{ margin-top: 14px; display: flex; gap: 10px; flex-wrap: wrap; }}

  /* ── Hero: favourite films ── */
  .hero-favs {{
    display: flex;
    flex-direction: column;
    gap: 10px;
  }}
  .hero-cell-title {{
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--dim);
    font-weight: 600;
    margin: 0;
  }}
  .hero-poster-row {{
    display: flex;
    gap: 10px;
  }}
  .hero-poster {{
    flex: 1;
    border-radius: 6px;
    overflow: hidden;
    background: rgba(255,255,255,0.04);
    border: 1px solid var(--border);
    display: flex;
    flex-direction: column;
  }}
  .hero-poster img {{
    width: 100%;
    aspect-ratio: 2/3;
    object-fit: cover;
    display: block;
  }}
  .hero-poster--empty {{
    aspect-ratio: 2/3;
    display: flex;
    align-items: flex-end;
    justify-content: center;
  }}
  .hero-poster-label {{
    display: block;
    padding: 4px 6px;
    font-size: 0.68rem;
    color: var(--muted);
    text-align: center;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}

  /* ── Hero: person cards ── */
  .hero-cell {{
    display: flex;
    align-items: center;
  }}
  .hero-person {{
    display: flex;
    align-items: center;
    gap: 16px;
    background: rgba(255,255,255,0.03);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px 20px;
    width: 100%;
  }}
  .hero-person img {{
    width: 72px;
    height: 72px;
    border-radius: 50%;
    object-fit: cover;
    flex-shrink: 0;
    border: 2px solid var(--border);
  }}
  .hero-person-nophoto {{
    width: 72px;
    height: 72px;
    border-radius: 50%;
    background: rgba(255,255,255,0.06);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 28px;
    flex-shrink: 0;
  }}
  .hero-person-info {{
    display: flex;
    flex-direction: column;
    gap: 2px;
  }}
  .hero-person-role {{
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--dim);
    font-weight: 600;
  }}
  .hero-person-name {{
    font-size: 1.1rem;
    font-weight: 700;
    color: var(--text);
  }}
  .hero-person-count {{
    font-size: 0.8rem;
    color: var(--muted);
  }}
  .hero-person-empty {{
    font-size: 0.85rem;
    color: var(--dim);
    font-style: italic;
  }}

  /* ── Badges ── */
  .badge {{
    display: inline-block;
    padding: 4px 12px;
    border-radius: 99px;
    font-size: 0.78rem;
    font-weight: 600;
  }}
  .badge--green {{ background: rgba(0,192,48,0.15); color: var(--accent); border: 1px solid rgba(0,192,48,0.3); }}
  .badge--dim   {{ background: rgba(255,255,255,0.05); color: var(--muted); border: 1px solid var(--border); }}

  /* ── Layout ── */
  .container {{ max-width: 1200px; margin: 0 auto; padding: 0 20px; }}
  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  .grid-3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; }}
  @media (max-width: 768px) {{
    .grid-2, .grid-3 {{ grid-template-columns: 1fr; }}
  }}

  /* ── Overview stat cards ── */
  .stat-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(130px, 160px));
    gap: 14px;
    margin-top: 30px;
    justify-content: center;
  }}
  .stat-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 20px 14px 16px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    transition: border-color .2s;
  }}
  .stat-card:hover {{ border-color: var(--accent); }}
  .stat-icon  {{ font-size: 1.4rem; }}
  .stat-value {{ font-size: 1.8rem; font-weight: 800; color: var(--gold); line-height: 1; }}
  .stat-label {{ font-size: 0.72rem; color: var(--muted); text-transform: uppercase; letter-spacing: .6px; text-align: center; }}

  /* ── Cards / sections ── */
  .card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 24px;
    margin-top: 20px;
  }}
  .card.full-width {{ grid-column: 1 / -1; }}
  .section-title {{
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--text);
    margin-bottom: 18px;
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .section-title .icon {{ font-size: 1.2rem; }}
  .section-sub {{ color: var(--muted); font-size: 0.88rem; margin-bottom: 14px; }}
  .section-sub strong {{ color: var(--text); }}

  /* ── Charts ── */
  .chart-wrap         {{ position: relative; height: 260px; }}
  .chart-wrap--tall   {{ height: 380px; }}
  .chart-wrap--short  {{ height: 180px; }}
  .chart-wrap--square {{ height: 260px; width: 260px; flex-shrink: 0; }}

  /* ── Tables ── */
  .data-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.88rem;
  }}
  .data-table th {{
    text-align: left;
    color: var(--muted);
    font-weight: 600;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: .5px;
    padding: 6px 10px;
    border-bottom: 1px solid var(--border);
  }}
  .data-table td {{
    padding: 8px 10px;
    border-bottom: 1px solid #1e1e20;
    vertical-align: middle;
  }}
  .data-table tr:last-child td {{ border-bottom: none; }}
  .data-table tr:hover td {{ background: rgba(255,255,255,0.02); }}
  .data-table .rank      {{ color: var(--dim); font-size: 0.8rem; width: 32px; }}
  .data-table .film-name {{ color: var(--text); font-weight: 500; }}
  .data-table .film-year {{ color: var(--muted); font-size: 0.82rem; width: 50px; }}
  .data-table .stars     {{ color: var(--gold); letter-spacing: 1px; font-size: 0.85rem; }}
  .data-table .num       {{ color: var(--accent); font-weight: 700; text-align: right; }}
  .data-table .rating-val {{ color: var(--gold); }}

  /* ── Directors / Genres / Actors ── */
  .genres-layout {{
    display: flex;
    gap: 28px;
    align-items: flex-start;
    flex-wrap: wrap;
  }}
  .genres-layout .data-table {{ flex: 1; min-width: 200px; }}

  .actor-grid {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 4px;
  }}
  .actor-chip {{
    background: #1e1e22;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px 14px;
    display: flex;
    align-items: center;
    gap: 10px;
    transition: border-color .15s;
  }}
  .actor-chip:hover {{ border-color: var(--blue); }}
  .actor-name  {{ color: var(--text); font-weight: 500; font-size: 0.9rem; }}
  .actor-count {{
    background: rgba(74,122,232,0.2);
    color: var(--blue);
    font-size: 0.72rem;
    font-weight: 700;
    padding: 2px 7px;
    border-radius: 99px;
  }}

  /* ── Rewatches ── */
  .rewatch-list {{ display: flex; flex-direction: column; gap: 8px; }}
  .rewatch-item {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 12px;
    background: #1a1a1e;
    border-radius: 8px;
    border: 1px solid var(--border);
  }}
  .rewatch-badge {{
    background: rgba(232,192,74,0.15);
    color: var(--gold);
    font-size: 0.78rem;
    font-weight: 700;
    padding: 2px 9px;
    border-radius: 99px;
    border: 1px solid rgba(232,192,74,0.3);
    white-space: nowrap;
  }}

  /* ── Tag cloud ── */
  .tag-cloud {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: baseline;
    padding-top: 4px;
  }}
  .tag-chip {{
    background: #1e1e22;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 4px 10px;
    color: var(--text);
    cursor: default;
    transition: border-color .15s, color .15s;
  }}
  .tag-chip:hover {{ border-color: var(--gold); color: var(--gold); }}
  .tag-chip sup {{ color: var(--muted); font-size: 0.65em; }}

  /* ── Liked films ── */
  .liked-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 10px;
  }}
  .liked-item {{
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: #1a1a1e;
    border-radius: 8px;
    border: 1px solid var(--border);
    overflow: hidden;
  }}
  .liked-heart {{ color: #e84a4a; font-size: 0.8rem; flex-shrink: 0; }}
  .liked-name  {{ color: var(--text); font-size: 0.85rem; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .liked-year  {{ color: var(--muted); font-size: 0.78rem; flex-shrink: 0; margin-left: auto; }}

  /* ── Runtime ── */
  .runtime-stats {{ display: flex; gap: 20px; flex-wrap: wrap; }}
  .runtime-card {{
    background: #1a1a1e;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 20px 28px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    flex: 1;
    min-width: 160px;
  }}
  .runtime-value {{ font-size: 2.2rem; font-weight: 800; color: var(--gold); }}
  .runtime-label {{ font-size: 0.8rem; color: var(--muted); text-transform: uppercase; letter-spacing: .5px; }}
  .runtime-sub   {{ font-size: 0.8rem; color: var(--dim); }}

  /* ── Film lengths ── */
  .lengths-layout {{
    display: flex;
    gap: 32px;
    align-items: center;
    flex-wrap: wrap;
  }}
  .len-legend {{ display: flex; flex-direction: column; gap: 12px; flex: 1; min-width: 180px; }}
  .len-item   {{ display: flex; align-items: center; gap: 10px; font-size: 0.88rem; }}
  .len-dot    {{ width: 12px; height: 12px; border-radius: 3px; flex-shrink: 0; }}
  .len-label  {{ color: var(--text); flex: 1; }}
  .len-val    {{ color: var(--gold); font-weight: 700; }}
  .len-pct    {{ color: var(--muted); font-size: 0.78rem; font-weight: 400; }}

  /* ── Countries ── (reuses chart-wrap--tall) ── */

  /* ── Gender distribution ── */
  .gender-layout {{ display: grid; grid-template-columns: 1fr 1fr; gap: 28px; }}
  @media (max-width: 600px) {{ .gender-layout {{ grid-template-columns: 1fr; }} }}
  .gender-block  {{ display: flex; flex-direction: column; gap: 10px; }}
  .gender-subtitle {{
    font-size: 0.82rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .6px;
    color: var(--muted);
    margin-bottom: 4px;
  }}
  .gender-row    {{ display: flex; align-items: center; gap: 8px; font-size: 0.85rem; }}
  .gender-dot    {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
  .gender-label  {{ color: var(--text); width: 90px; flex-shrink: 0; }}
  .gender-bar-bg {{ flex: 1; background: #222; border-radius: 4px; height: 8px; overflow: hidden; }}
  .gender-bar-fill {{ height: 100%; border-radius: 4px; transition: width .6s; }}
  .gender-pct    {{ color: var(--text); font-weight: 700; width: 42px; text-align: right; font-size: 0.82rem; }}
  .gender-count  {{ color: var(--dim); font-size: 0.78rem; width: 40px; }}

  /* ── Watchlist section ── */
  .watchlist-section {{
    margin-top: 40px;
  }}
  .wl-header {{
    display: flex;
    align-items: center;
    gap: 14px;
    margin-bottom: 4px;
  }}
  .wl-title {{
    font-size: 1.4rem;
    font-weight: 800;
    color: var(--text);
  }}
  .wl-total-badge {{
    background: rgba(232,148,74,0.15);
    color: #e8944a;
    border: 1px solid rgba(232,148,74,0.3);
    border-radius: 99px;
    padding: 4px 14px;
    font-size: 0.82rem;
    font-weight: 700;
  }}

  /* ── Recently added list ── */
  .recent-list  {{ display: flex; flex-direction: column; gap: 6px; }}
  .recent-item  {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 7px 12px;
    background: #1a1a1e;
    border-radius: 8px;
    border: 1px solid var(--border);
    gap: 10px;
  }}
  .recent-name  {{ color: var(--text); font-weight: 500; font-size: 0.88rem; flex: 1; }}
  .recent-meta  {{ color: var(--muted); font-size: 0.78rem; flex-shrink: 0; white-space: nowrap; }}
  .recent-date  {{ color: var(--dim); }}

  /* ── Popularity table ── */
  .pop-table    {{ margin-top: 8px; }}
  .pop-cell     {{ min-width: 120px; }}
  .pop-bar-bg   {{ background: #222; border-radius: 4px; height: 6px; overflow: hidden; margin-bottom: 2px; }}
  .pop-bar-fill {{ height: 100%; border-radius: 4px; }}
  .pop-score    {{ color: var(--muted); font-size: 0.72rem; }}
  .votes-dim    {{ color: var(--dim); font-size: 0.78rem; }}

  /* ── Misc ── */
  .no-data {{
    color: var(--muted);
    font-style: italic;
    font-size: 0.88rem;
    padding: 20px 0;
  }}
  .spacer {{ margin-top: 40px; }}
  footer {{
    text-align: center;
    color: var(--dim);
    font-size: 0.78rem;
    margin-top: 60px;
  }}
  footer a {{ color: var(--muted); }}

  /* ── Zone dividers ── */
  .zone-divider {{
    display: flex;
    align-items: center;
    gap: 14px;
    padding-top: 14px;
    margin: 56px 0 0;
    border-top: 2px solid var(--zone-accent, var(--accent));
  }}
  .zone-icon  {{ font-size: 1.7rem; line-height: 1; }}
  .zone-title {{
    font-size: 1.55rem;
    font-weight: 800;
    color: var(--text);
    letter-spacing: -0.5px;
  }}
</style>
</head>
<body>

<!-- ── HERO ── -->
<header class="hero">
  <div class="hero-grid">
    <!-- Top-left: profile text -->
    <div class="hero-profile">
      <h1 class="hero-title"><span>@{username}</span>'s Film Habits</h1>
      <p class="hero-fullname"><strong>{fullname}</strong></p>
      {bio_block}
      <div class="hero-pills">{meta_pills}</div>
      <p class="hero-joined">Member since <strong>{joined}</strong></p>
      <div class="hero-badges">{tmdb_badge}</div>
    </div>
    <!-- Top-right: 4 favourite film posters -->
    <div class="hero-favs">
      <h3 class="hero-cell-title">Favorite Films</h3>
      <div class="hero-poster-row">{fav_posters_html}</div>
    </div>
    <!-- Bottom-left: favourite director -->
    <div class="hero-cell">
      {director_html}
    </div>
    <!-- Bottom-right: favourite actor -->
    <div class="hero-cell">
      {actor_html}
    </div>
  </div>
</header>

<div class="container">

  <!-- ── OVERVIEW ── -->
  {overview_html}

  <!-- ════════════════════════ WATCHED FILMS ════════════════════════ -->
  {_zone_divider("Watched Films", "🎬", "var(--accent)")}

  <!-- Ratings | Activity by year -->
  <div class="grid-2">
    {_section("Rating Distribution", "⭐", ratings_html)}
    {_section("Films Watched per Year", "📅", year_html)}
  </div>

  <!-- Decades | Monthly patterns -->
  <div class="grid-2">
    {_section("Films by Release Decade", "🗓", decade_html)}
    {_section("Monthly Viewing Pattern", "📆", month_html)}
  </div>

  <!-- Current Year -->
  <div>
    {_section(f"{cy_year} Releases You've Watched", "🆕", cy_html)}
  </div>

  <!-- Film lengths | Screen time -->
  <div class="grid-2">
    {_section("Film Length Categories", "⏳", lengths_html)}
    {_section("Screen Time", "⏱", runtime_html)}
  </div>

  <!-- Genres -->
  <div>
    {_section("Favorite Genres", "🍿", genres_html)}
  </div>

  <!-- Countries -->
  <div>
    {_section("Production Countries", "🌍", country_html)}
  </div>

  <!-- Obscure Picks -->
  <div>
    {_section("Obscure Picks — Films You've Watched", "🔍", low_pop_watched_html)}
  </div>

  <!-- Top Rated Films -->
  <div>
    {_section("Top Rated Films", "⭐", top_rated_html)}
  </div>

  <!-- Rewatches | Tags -->
  <div class="grid-2">
    {_section("Most Rewatched Films", "🔁", rewatch_html)}
    {_section("Diary Tags", "🏷", tags_html)}
  </div>

  <!-- Reviews | Liked -->
  <div class="grid-2">
    {_section("Reviews Written per Year", "✍", reviews_html)}
    {_section("Recently Liked Films", "❤", liked_html)}
  </div>

  <!-- ════════════════════════ DIRECTORS & CAST ════════════════════════ -->
  {_zone_divider("Directors & Cast", "🎭", "var(--blue)")}

  <!-- Most Watched Directors | Top Rated Directors -->
  <div class="grid-2">
    {_section("Most Watched Directors", "🎬", directors_html)}
    {_section("Top Rated Directors", "🏆", top_rated_dirs_html)}
  </div>

  <!-- Actors | Gender distribution -->
  <div class="grid-2">
    {_section("Favorite Actors", "🎭", actors_html)}
    {_section("Gender Distribution", "⚧", gender_html)}
  </div>

</div>

<!-- ════════════════════════ WATCHLIST ════════════════════════ -->
<div class="container">
  {watchlist_html}
</div>

<footer>
  <p>Generated from your <a href="https://letterboxd.com" target="_blank">Letterboxd</a> data export.</p>
</footer>

</body>
</html>"""


# ── Entry point ──────────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) > 1:
        zip_path = Path(sys.argv[1])
    else:
        candidates = sorted(Path(__file__).parent.glob("*.zip"))
        if not candidates:
            print("Error: no .zip file provided and none found in the project root.", file=sys.stderr)
            sys.exit(1)
        zip_path = candidates[0]

    print(f"Loading CSV data from {zip_path.name}...")
    data = load_data(zip_path)

    print("Computing stats...")
    stats = get_all_stats(data)

    print("Generating HTML...")
    html = generate_html(stats)

    out = Path(__file__).parent / "report.html"
    out.write_text(html, encoding="utf-8")
    print(f"\nReport saved: {out.resolve()}")
    print("Open report.html in your browser to view your film habits dashboard.")


if __name__ == "__main__":
    main()
