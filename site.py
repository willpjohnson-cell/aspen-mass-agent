#!/usr/bin/env python3
"""Render the platform page. Source-agnostic: everything shown is read from
monitors/, runs/ and data/.

Nothing here is a placeholder. The page describes the monitors that exist and
the runs that happened, and shows no control for anything the platform cannot
currently do.
"""
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runner  # noqa: E402

ROOT = runner.ROOT
OUT = ROOT / "index.html"
PLATFORM = "Aspen"
TAGLINE = ("A platform for hosting monitors that watch state and local governments. "
           "Each monitor archives the pages it watches, byte for byte, and records "
           "what changed between runs.")

# Preserved verbatim from the first version of this page.
SCOPE_BOX = """<div class="scope">
  <h2>What this shows</h2>
  <p><strong>Establishes:</strong> what each hearing page said when it was fetched, at the timestamp shown in the last column. The raw HTML is kept byte-for-byte and each row carries the SHA-256 of the file it came from.</p>
  <p><strong>Does not establish:</strong> when a hearing was announced or posted. The site does not publish a posting or announcement date, so this archive contains none and no notice-timing conclusion can be drawn from it. Blank cells mean the field was absent from the page, not that it was zero or unknown to the Legislature.</p>
</div>"""

STYLE = """<style>
  :root { color-scheme: light dark; --line:#d7d7d2; --muted:#6b6b66; --bg:#fbfbf9; --fg:#1b1b19; }
  @media (prefers-color-scheme: dark) {
    :root { --line:#3a3a36; --muted:#9a9a92; --bg:#17171a; --fg:#e9e9e4; }
  }
  body { margin:0; padding:2rem 1.25rem 4rem; background:var(--bg); color:var(--fg);
         font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif; }
  .wrap { max-width:1180px; margin:0 auto; }
  h1 { font-size:1.55rem; margin:0 0 .35rem; }
  .sub { color:var(--muted); margin:0 0 1.5rem; }
  h2.section { font-size:.82rem; text-transform:uppercase; letter-spacing:.07em;
               margin:2rem 0 .75rem; color:var(--muted); }
  .scope { border:1px solid var(--line); border-left:3px solid var(--muted);
            padding:.85rem 1rem; margin:0 0 1.5rem; background:transparent; }
  .scope h2 { font-size:.82rem; text-transform:uppercase; letter-spacing:.07em;
               margin:0 0 .5rem; color:var(--muted); }
  .scope p { margin:.4rem 0; }
  .card { border:1px solid var(--line); border-radius:4px; padding:1rem 1.1rem; margin:0 0 1rem; }
  .card h3 { margin:0 0 .2rem; font-size:1.05rem; }
  .card .where { color:var(--muted); margin:0 0 .9rem; font-size:.9rem; }
  .card .desc { margin:0 0 1rem; }
  .card .links a { margin-right:1rem; font-size:.9rem; }
  .stats { display:flex; gap:2rem; flex-wrap:wrap; margin:0 0 1.25rem; }
  .stats div span { display:block; font-size:1.35rem; }
  .stats div small { color:var(--muted); }
  input { width:100%; max-width:26rem; padding:.5rem .65rem; margin:0 0 1rem;
           border:1px solid var(--line); border-radius:4px; background:transparent; color:inherit; }
  .tablewrap { overflow-x:auto; border:1px solid var(--line); border-radius:4px; }
  table { border-collapse:collapse; width:100%; font-size:13.5px; }
  th, td { text-align:left; padding:.45rem .6rem; border-bottom:1px solid var(--line);
            vertical-align:top; white-space:nowrap; }
  th { position:sticky; top:0; background:var(--bg); font-size:.78rem;
        text-transform:uppercase; letter-spacing:.05em; color:var(--muted); }
  td.bills { white-space:normal; min-width:14rem; color:var(--muted); }
  td.stamp { color:var(--muted); font-variant-numeric:tabular-nums; }
  .missing { color:var(--muted); font-style:italic; }
  .runs td.n { font-variant-numeric:tabular-nums; }
  .quiet { color:var(--muted); }
  footer { margin-top:2rem; color:var(--muted); font-size:.85rem; }
</style>"""


def esc(v):
    return html.escape("" if v is None else str(v))


def cell(v):
    if v is None or v == "" or v == []:
        return '<td class="missing">not on page</td>'
    return f"<td>{esc(v)}</td>"


def monitor_card(m, records, runs):
    bill_refs = sum(r.get("bill_count") or 0 for r in records)
    since = runs[0]["started_utc"][:10] if runs else None
    last = runs[-1] if runs else None
    data_json = f"data/{m.name}.json"
    data_csv = f"data/{m.name}.csv"
    cfg = f"monitors/{m.name}/monitor.yaml"
    stats = [
        (f"{len(records)}", "pages archived"),
        (f"{bill_refs:,}", "bill references"),
        (esc(since or "—"), "running since"),
        (esc(m.get("schedule", default="—")), "schedule"),
    ]
    stat_html = "".join(f"<div><span>{v}</span><small>{k}</small></div>" for v, k in stats)
    last_line = (f"Last run {esc(last['started_utc'])} — {esc(last['summary'])}."
                 if last else "No runs recorded yet.")
    return f"""<div class="card">
  <h3>{esc(m.name)}</h3>
  <p class="where">{esc(m.get('title', default=''))} · {esc(m.get('jurisdiction', default=''))}</p>
  <p class="desc">{esc(m.get('description', default=''))}</p>
  <div class="stats">{stat_html}</div>
  <p class="quiet">{last_line}</p>
  <p class="links"><a href="{data_json}">data (JSON)</a><a href="{data_csv}">data (CSV)</a>
     <a href="{cfg}">monitor.yaml</a><a href="runs/">run records</a></p>
</div>"""


def runs_table(runs, limit=10):
    recent = list(reversed(runs))[:limit]
    rows = []
    for r in recent:
        changed = len(r["changed_pages"])
        detail = (f"{changed} changed" if changed else
                  ("—" if r["kind"] == "initial-collection" else "no changes"))
        if r.get("new_pages") and r["kind"] != "initial-collection":
            detail += f", {len(r['new_pages'])} new"
        if r.get("removed_pages"):
            detail += f", {len(r['removed_pages'])} removed"
        flag = ' <span class="quiet">(reconstructed)</span>' if r.get("reconstructed") else ""
        rows.append(
            f"<tr><td>{esc(r['started_utc'])}</td><td>{esc(r['kind'])}{flag}</td>"
            f"<td class='n'>{r['pages_checked']}</td>"
            f"<td class='n'>{len(r['new_pages'])}</td>"
            f"<td class='n'>{changed}</td><td>{detail}</td></tr>")
    return f"""<div class="tablewrap"><table class="runs">
<thead><tr><th>Started (UTC)</th><th>Kind</th><th>Checked</th><th>New</th><th>Changed</th><th>Result</th></tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody></table></div>
<p class="quiet">Showing the {len(recent)} most recent of {len(runs)} recorded
run{'s' if len(runs) != 1 else ''}. One JSON record per run lives in <code>runs/</code>.</p>"""


def data_table(m, records):
    fields = [f for f in m.fields if f["key"] not in ("bill_count", "general_court")]
    head = "".join(f"<th>{esc(f['label'])}</th>" for f in fields)
    rows = []
    for r in sorted(records, key=lambda r: r["id"], reverse=True):
        cells = []
        for f in fields:
            v = r.get(f["key"])
            if f.get("list"):
                cells.append(f'<td class="bills">{esc(", ".join(v))}</td>' if v
                             else '<td class="missing">none listed</td>')
            else:
                cells.append(cell(v))
        rows.append(f'<tr><td><a href="{esc(r["source_url"])}">{r["id"]}</a></td>'
                    + "".join(cells)
                    + f'<td class="stamp">{esc(r.get("fetched_at_utc") or "")}</td></tr>')
    return f"""<input id="q" type="search" placeholder="Filter by committee, date, status, bill number…" autocomplete="off">
<div class="tablewrap">
<table id="t">
<thead><tr><th>ID</th>{head}<th>Fetched (UTC)</th></tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody>
</table>
</div>"""


def build():
    names = runner.available()
    monitors = [runner.Monitor(n) for n in names]
    built = datetime.now(timezone.utc).isoformat(timespec="seconds")

    cards, tables = [], []
    for m in monitors:
        data_file = m.data_dir / f"{m.name}.json"
        records = json.loads(data_file.read_text(encoding="utf-8")) if data_file.exists() else []
        runs = runner.load_runs(m.name)
        cards.append(monitor_card(m, records, runs))
        tables.append((m, records, runs))

    all_runs = runner.load_runs()
    m, records, runs = tables[0]
    fetched = [r["fetched_at_utc"] for r in records if r.get("fetched_at_utc")]
    window = f"{min(fetched)} to {max(fetched)}" if fetched else "see the request log"

    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{PLATFORM} — government monitors</title>
{STYLE}
</head>
<body>
<div class="wrap">
<h1>{PLATFORM}</h1>
<p class="sub">{TAGLINE}</p>

<h2 class="section">Monitors running: {len(monitors)}</h2>
{chr(10).join(cards)}

<h2 class="section">Run history</h2>
{runs_table(all_runs)}

<h2 class="section">{esc(m.get('title', default=m.name))}</h2>
{SCOPE_BOX}
{data_table(m, records)}
<footer>Fetch window for the archived pages: {esc(window)}.
Built {esc(built)} from data/{esc(m.name)}.json and runs/.
Sequential fetching, {esc(m.delay)}s between requests.</footer>
</div>
<script>
const q = document.getElementById('q');
const rows = Array.from(document.querySelectorAll('#t tbody tr'));
q.addEventListener('input', () => {{
  const needle = q.value.toLowerCase().trim();
  for (const row of rows) {{
    row.style.display = !needle || row.textContent.toLowerCase().includes(needle) ? '' : 'none';
  }}
}});
</script>
</body>
</html>
"""
    OUT.write_text(doc, encoding="utf-8")
    print(f"wrote {OUT.name} ({len(records)} rows, {len(all_runs)} runs, "
          f"{len(monitors)} monitor{'s' if len(monitors) != 1 else ''}, {OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    build()
