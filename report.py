"""
Letterboxd Report Generator
===========================
Generates a self-contained HTML file from Letterboxd CSV data.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

from analyzer import load_data, get_all_stats

OUTPUT_FILE = Path(__file__).parent / "report.html"


# ── Entry point ────────────────────────────────────────────────────────────────

def generate_report(zip_path: str | Path | None = None) -> None:
    if zip_path is None:
        if len(sys.argv) > 1:
            zip_path = Path(sys.argv[1])
        else:
            candidates = sorted(Path(__file__).parent.glob("*.zip"))
            if not candidates:
                print("Error: no .zip file provided and none found in the project root.", file=sys.stderr)
                sys.exit(1)
            zip_path = candidates[0]
    zip_path = Path(zip_path)
    print(f"Loading data from {zip_path.name}...")
    data = load_data(zip_path)
    print("Running analysis...")
    stats = get_all_stats(data)
    print("Building HTML...")
    html = _build_html(stats)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nReport saved: {OUTPUT_FILE}")


# ── HTML builder ───────────────────────────────────────────────────────────────

def _build_html(stats: dict) -> str:
    """Assemble the full self-contained HTML page."""
    p          = stats["profile"]
    stats_json = json.dumps(stats, ensure_ascii=False)
    bio_clean  = re.sub(r"<[^>]+>", "", p.get("bio", "")).strip()
    now        = datetime.now().strftime("%B %d, %Y")
    tmdb_badge = (
        '<span class="badge badge-on">TMDB enriched</span>'
        if stats["tmdb_enabled"]
        else '<span class="badge badge-off">No TMDB key — partial data</span>'
    )

    def stat_card(value, label, orange=False):
        cls = ' orange' if orange else ''
        return (
            f'<div class="stat-card">'
            f'<div class="stat-value{cls}">{value}</div>'
            f'<div class="stat-label">{label}</div>'
            f'</div>'
        )

    avg_str = str(p["average_rating"]) if p["average_rating"] is not None else "—"
    bio_html = f'<p class="bio">{bio_clean}</p>' if bio_clean else ""

    cards_html = (
        stat_card(p["total_watched"],    "Films Watched")
        + stat_card(p["total_rated"],    "Ratings Given")
        + stat_card(p["total_reviews"],  "Reviews Written")
        + stat_card(avg_str,             "Average Rating", orange=True)
        + stat_card(p["watchlist_size"], "Watchlist")
        + stat_card(p["total_liked"],    "Liked Films")
        + stat_card(p.get("total_rewatches", 0), "Rewatches")
    )

    html = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        "<title>Film Habits – " + p["username"] + "</title>\n"
        '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>\n'
        "<style>\n" + _CSS + "\n</style>\n"
        "</head>\n"
        "<body>\n"
        '<div class="container">\n'

        # ── Header ──
        '<header class="header">\n'
        '  <h1>Film Habits &mdash; <span class="handle">@' + p["username"] + "</span>" + tmdb_badge + "</h1>\n"
        '  <p class="meta">Member since ' + p["date_joined"] + "</p>\n"
        + bio_html + "\n"
        "</header>\n"

        # ── Summary cards ──
        '<div class="cards">' + cards_html + "</div>\n"

        # ── Row 1: rating dist + activity year ──
        '<div class="grid-2">\n'
        '  <div class="section"><h2>Rating <span>Distribution</span></h2>'
        '<div class="chart-wrap"><canvas id="chartRatings" height="230"></canvas></div></div>\n'
        '  <div class="section"><h2>Activity by <span>Year</span></h2>'
        '<div class="chart-wrap"><canvas id="chartYears" height="230"></canvas></div></div>\n'
        "</div>\n"

        # ── Row 2: decades + rewatches ──
        '<div class="grid-2">\n'
        '  <div class="section"><h2>Films by <span>Decade</span></h2>'
        '<div class="chart-wrap"><canvas id="chartDecades" height="280"></canvas></div></div>\n'
        '  <div class="section"><h2>Most <span>Rewatched</span></h2>'
        '<ul class="rw-list" id="rewatchList"></ul></div>\n'
        "</div>\n"

        # ── Directors ──
        '<div class="section"><h2>Most Watched <span>Directors</span></h2>'
        '<div class="bar-list" id="directorBars"></div></div>\n'

        # ── Row 3: genres + actors ──
        '<div class="grid-2">\n'
        '  <div class="section"><h2>Favorite <span>Genres</span></h2>'
        '<div id="genreSection"></div></div>\n'
        '  <div class="section"><h2>Most Seen <span>Actors</span></h2>'
        '<div id="actorSection"></div></div>\n'
        "</div>\n"

        # ── Top-rated films ──
        '<div class="section"><h2>Top-Rated <span>Films</span></h2>'
        '<div class="films-grid" id="topFilms"></div></div>\n'

        # ── Tags ──
        '<div class="section"><h2>Diary <span>Tags</span></h2>'
        '<div class="tag-cloud" id="tagCloud"></div></div>\n'

        '<footer class="footer">Generated on ' + now + ' &nbsp;·&nbsp; letterboxd-csv-project</footer>\n'
        "</div>\n"  # .container

        "<script>\n"
        "const S = __STATS_JSON__;\n"
        + _JS +
        "\n</script>\n"
        "</body>\n</html>"
    )

    return html.replace("__STATS_JSON__", stats_json)


# ── CSS ────────────────────────────────────────────────────────────────────────

_CSS = """
:root {
  --bg:      #14181c;
  --surface: #1e2530;
  --border:  #2c3542;
  --orange:  #f5a623;
  --green:   #00c030;
  --text:    #c8d0d8;
  --muted:   #6e8090;
  --white:   #ffffff;
  --r:       10px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: "Segoe UI", system-ui, sans-serif;
  font-size: 15px;
  line-height: 1.6;
}

/* Layout */
.container { max-width: 1100px; margin: 0 auto; padding: 28px 20px; }
.grid-2    { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }

/* Header */
.header    { padding: 32px 0 22px; border-bottom: 1px solid var(--border); margin-bottom: 26px; }
.header h1 { font-size: 1.9rem; color: var(--white); font-weight: 700; }
.header .handle { color: var(--orange); }
.header .meta   { color: var(--muted); font-size: .85rem; margin-top: 3px; }
.header .bio    { color: var(--text); margin-top: 10px; max-width: 620px; font-style: italic; font-size: .93rem; }

/* Stat cards */
.cards     { display: grid; grid-template-columns: repeat(auto-fill, minmax(142px, 1fr)); gap: 14px; margin-bottom: 20px; }
.stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r); padding: 18px 14px; text-align: center; }
.stat-value        { font-size: 1.85rem; font-weight: 700; color: var(--white); }
.stat-value.orange { color: var(--orange); }
.stat-label        { font-size: .74rem; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; margin-top: 4px; }

/* Section cards */
.section      { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r); padding: 22px; margin-bottom: 20px; }
.section h2   { font-size: 1rem; font-weight: 600; color: var(--white); text-transform: uppercase; letter-spacing: .07em; margin-bottom: 18px; }
.section h2 span { color: var(--orange); }

/* Chart wrapper */
.chart-wrap { position: relative; }

/* Inline bar list (directors / genres / actors) */
.bar-list  { display: flex; flex-direction: column; gap: 9px; }
.bar-item  { display: grid; grid-template-columns: 155px 1fr 46px; align-items: center; gap: 10px; }
.bar-item .name  { font-size: .87rem; color: var(--white); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bar-track { background: var(--border); border-radius: 4px; height: 8px; overflow: hidden; }
.bar-fill  { height: 100%; background: var(--orange); border-radius: 4px; transition: width .4s ease; }
.bar-count { font-size: .8rem; color: var(--muted); text-align: right; }

/* Top-rated films grid */
.films-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 12px; }
.film-card  { background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; }
.film-name  { font-size: .9rem; color: var(--white); font-weight: 600; }
.film-year  { font-size: .77rem; color: var(--muted); }
.film-stars { color: var(--orange); font-size: .83rem; margin-top: 5px; letter-spacing: 1px; }

/* Tag cloud */
.tag-cloud { display: flex; flex-wrap: wrap; gap: 8px; }
.tag       { background: var(--bg); border: 1px solid var(--border); border-radius: 20px; padding: 3px 12px; color: var(--text); cursor: default; }

/* Rewatch list */
.rw-list    { list-style: none; }
.rw-list li { display: flex; justify-content: space-between; padding: 7px 0; border-bottom: 1px solid var(--border); font-size: .9rem; }
.rw-list li:last-child { border-bottom: none; }
.rw-count   { color: var(--orange); font-weight: 600; }
.rw-total   { color: var(--muted); }

/* Badges & notices */
.badge       { display: inline-block; border-radius: 4px; padding: 1px 8px; font-size: .72rem; font-weight: 600; margin-left: 10px; vertical-align: middle; }
.badge-on    { background: #1a3a1a; color: var(--green); border: 1px solid #00502a; }
.badge-off   { background: #2a2010; color: #c09020; border: 1px solid #5a4810; }
.notice      { color: var(--muted); font-size: .88rem; font-style: italic; padding: 18px 0; text-align: center; }

/* Footer */
.footer { text-align: center; color: var(--muted); font-size: .8rem; padding: 32px 0 10px; border-top: 1px solid var(--border); margin-top: 10px; }

@media (max-width: 680px) {
  .grid-2 { grid-template-columns: 1fr; }
  .bar-item { grid-template-columns: 110px 1fr 36px; }
}
"""

# ── JavaScript ─────────────────────────────────────────────────────────────────

_JS = """
/* ── Chart.js global defaults ── */
Chart.defaults.color       = '#c8d0d8';
Chart.defaults.borderColor = '#2c3542';
Chart.defaults.font.family = "'Segoe UI', system-ui, sans-serif";

const ORANGE = '#f5a623';
const BORDER = '#2c3542';

/* ── helpers ── */
function ratingColor(r) {
  const t = (r - 0.5) / 4.5;
  return `hsl(${Math.round(10 + t * 110)}, 75%, 52%)`;
}

function stars(rating) {
  const full = Math.floor(rating);
  const half = (rating % 1) >= 0.5;
  return '★'.repeat(full) + (half ? '½' : '');
}

function makeBarChart(id, labels, values, opts = {}) {
  const ctx = document.getElementById(id);
  if (!ctx) return;
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: opts.colors || ORANGE,
        borderRadius: 5,
        borderSkipped: false,
      }]
    },
    options: {
      indexAxis: opts.horizontal ? 'y' : 'x',
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: c => ` ${c.raw} film${c.raw !== 1 ? 's' : ''}` } }
      },
      scales: {
        x: { grid: { color: BORDER }, ticks: { color: '#c8d0d8' } },
        y: { grid: { color: BORDER }, ticks: { color: '#c8d0d8' } }
      }
    }
  });
}

function inlineBarItem(name, count, maxCount) {
  const pct = maxCount > 0 ? (count / maxCount * 100).toFixed(1) : 0;
  return `
    <div class="bar-item">
      <div class="name" title="${name}">${name}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
      <div class="bar-count">${count}</div>
    </div>`;
}

/* ── Rating distribution ── */
{
  const labels = Object.keys(S.rating_distribution);
  const values = Object.values(S.rating_distribution);
  const colors = labels.map(r => ratingColor(parseFloat(r)));
  makeBarChart('chartRatings', labels, values, { colors });
}

/* ── Activity by year ── */
{
  const labels = Object.keys(S.activity_by_year);
  const values = Object.values(S.activity_by_year);
  makeBarChart('chartYears', labels, values);
}

/* ── Decade breakdown ── */
{
  const labels = Object.keys(S.decade_breakdown);
  const values = Object.values(S.decade_breakdown);
  makeBarChart('chartDecades', labels, values, { horizontal: true });
}

/* ── Rewatch list ── */
{
  const el   = document.getElementById('rewatchList');
  const data = S.rewatch_stats.most_rewatched;
  if (!data.length) {
    el.innerHTML = '<li><span class="notice">No rewatch data found.</span></li>';
  } else {
    el.innerHTML =
      data.map(item =>
        `<li><span>${item.name}</span><span class="rw-count">×${item.count}</span></li>`
      ).join('') +
      `<li><span class="rw-total">Total rewatch events</span><span class="rw-count">${S.rewatch_stats.total_rewatches}</span></li>`;
  }
}

/* ── Directors ── */
{
  const el   = document.getElementById('directorBars');
  const dirs = S.directors;
  if (!dirs.length) {
    el.innerHTML = '<p class="notice">No director data found.</p>';
  } else {
    const max = dirs[0].count;
    el.innerHTML = dirs.map(d => inlineBarItem(d.director, d.count, max)).join('');
  }
}

/* ── Genres ── */
{
  const el = document.getElementById('genreSection');
  if (!S.tmdb_enabled || !S.genres.length) {
    el.innerHTML = '<p class="notice">Set <code>TMDB_API_KEY</code> to enable genre analysis.</p>';
  } else {
    const max = S.genres[0].count;
    el.innerHTML = '<div class="bar-list">' +
      S.genres.map(g => {
        const label = g.avg_rating != null
          ? `${g.genre} <span style="color:var(--muted);font-size:.76rem">avg ${g.avg_rating}★</span>`
          : g.genre;
        return inlineBarItem(label, g.count, max);
      }).join('') +
      '</div>';
  }
}

/* ── Actors ── */
{
  const el = document.getElementById('actorSection');
  if (!S.tmdb_enabled || !S.actors.length) {
    el.innerHTML = '<p class="notice">Set <code>TMDB_API_KEY</code> to enable actor analysis.</p>';
  } else {
    const max = S.actors[0].count;
    el.innerHTML = '<div class="bar-list">' +
      S.actors.map(a => inlineBarItem(a.actor, a.count, max)).join('') +
      '</div>';
  }
}

/* ── Top-rated films ── */
{
  const el = document.getElementById('topFilms');
  el.innerHTML = S.top_rated_films.map(f => `
    <div class="film-card">
      <div class="film-name">${f.Name}</div>
      <div class="film-year">${f.Year}</div>
      <div class="film-stars">${stars(f.Rating)}</div>
    </div>`).join('');
}

/* ── Tag cloud ── */
{
  const el      = document.getElementById('tagCloud');
  const entries = Object.entries(S.tag_breakdown);
  if (!entries.length) {
    el.innerHTML = '<p class="notice">No custom tags found.</p>';
  } else {
    const max = entries[0][1];
    const min = entries[entries.length - 1][1];
    el.innerHTML = entries.map(([tag, count]) => {
      const t     = max > min ? (count - min) / (max - min) : 1;
      const size  = (0.78 + t * 0.9).toFixed(2);
      const alpha = (0.55 + t * 0.45).toFixed(2);
      return `<span class="tag" style="font-size:${size}rem;opacity:${alpha}" title="${count} uses">${tag}</span>`;
    }).join('');
  }
}
"""


if __name__ == "__main__":
    generate_report()
