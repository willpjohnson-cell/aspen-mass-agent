#!/usr/bin/env python3
"""Build index.html from hearings.json. Self-contained, no external assets."""
import html
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "hearings.json"
OUT = ROOT / "index.html"


def esc(value):
    return html.escape("" if value is None else str(value))


def cell(value):
    if value is None:
        return '<td class="missing">not on page</td>'
    return f"<td>{esc(value)}</td>"


def main():
    records = json.loads(DATA.read_text(encoding="utf-8"))
    records.sort(key=lambda r: r["id"], reverse=True)
    fetched = [r["fetched_at_utc"] for r in records if r.get("fetched_at_utc")]
    window = f"{min(fetched)} to {max(fetched)}" if fetched else "see fetch_status.tsv"
    committees = Counter(r["committee"] for r in records if r["committee"])
    types = Counter(r["event_type"] for r in records if r["event_type"])
    built = datetime.now(timezone.utc).isoformat(timespec="seconds")

    rows = []
    for r in records:
        bills = ", ".join(b["number"] for b in r["bills"]) or "—"
        name = r["committee"] or r["subject"]
        rows.append(
            f'<tr><td><a href="{esc(r["source_url"])}">{r["id"]}</a></td>'
            f'{cell(r["event_type"])}{cell(name)}{cell(r["event_date"])}{cell(r["start_time"])}'
            f'{cell(r["status"])}{cell(r["location"])}'
            f'<td class="bills">{esc(bills)}</td>'
            f'<td class="stamp">{esc(r.get("fetched_at_utc") or "")}</td></tr>'
        )

    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Massachusetts Legislature Hearing Page Archive</title>
<style>
  :root {{ color-scheme: light dark; --line:#d7d7d2; --muted:#6b6b66; --bg:#fbfbf9; --fg:#1b1b19; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --line:#3a3a36; --muted:#9a9a92; --bg:#17171a; --fg:#e9e9e4; }}
  }}
  body {{ margin:0; padding:2rem 1.25rem 4rem; background:var(--bg); color:var(--fg);
         font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif; }}
  .wrap {{ max-width:1180px; margin:0 auto; }}
  h1 {{ font-size:1.55rem; margin:0 0 .35rem; }}
  .sub {{ color:var(--muted); margin:0 0 1.5rem; }}
  .scope {{ border:1px solid var(--line); border-left:3px solid var(--muted);
            padding:.85rem 1rem; margin:0 0 1.5rem; background:transparent; }}
  .scope h2 {{ font-size:.82rem; text-transform:uppercase; letter-spacing:.07em;
               margin:0 0 .5rem; color:var(--muted); }}
  .scope p {{ margin:.4rem 0; }}
  .stats {{ display:flex; gap:2rem; flex-wrap:wrap; margin:0 0 1.25rem; }}
  .stats div span {{ display:block; font-size:1.35rem; }}
  .stats div small {{ color:var(--muted); }}
  input {{ width:100%; max-width:26rem; padding:.5rem .65rem; margin:0 0 1rem;
           border:1px solid var(--line); border-radius:4px; background:transparent; color:inherit; }}
  .tablewrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:4px; }}
  table {{ border-collapse:collapse; width:100%; font-size:13.5px; }}
  th, td {{ text-align:left; padding:.45rem .6rem; border-bottom:1px solid var(--line);
            vertical-align:top; white-space:nowrap; }}
  th {{ position:sticky; top:0; background:var(--bg); font-size:.78rem;
        text-transform:uppercase; letter-spacing:.05em; color:var(--muted); }}
  td.bills {{ white-space:normal; min-width:14rem; color:var(--muted); }}
  td.stamp {{ color:var(--muted); font-variant-numeric:tabular-nums; }}
  .missing {{ color:var(--muted); font-style:italic; }}
  footer {{ margin-top:2rem; color:var(--muted); font-size:.85rem; }}
</style>
</head>
<body>
<div class="wrap">
<h1>Massachusetts Legislature Hearing Page Archive</h1>
<p class="sub">Archived copies of <code>malegislature.gov/Events/Hearings/Detail/{{id}}</code> pages, with the fields each page displayed at the moment it was fetched. This id space carries {", ".join(f"{k} ({n})" for k, n in types.most_common())} pages; for hearings the named body is the committee, for other event types it is the subject.</p>

<div class="scope">
  <h2>What this shows</h2>
  <p><strong>Establishes:</strong> what each hearing page said when it was fetched, at the timestamp shown in the last column. The raw HTML is kept byte-for-byte and each row carries the SHA-256 of the file it came from.</p>
  <p><strong>Does not establish:</strong> when a hearing was announced or posted. The site does not publish a posting or announcement date, so this archive contains none and no notice-timing conclusion can be drawn from it. Blank cells mean the field was absent from the page, not that it was zero or unknown to the Legislature.</p>
</div>

<div class="stats">
  <div><span>{len(records)}</span><small>pages archived</small></div>
  <div><span>{len(committees)}</span><small>committees named</small></div>
  <div><span>{len(types)}</span><small>event types</small></div>
  <div><span>{sum(r["bill_count"] for r in records)}</span><small>bill references</small></div>
  <div><span>{esc(window.split(" to ")[0][:10])}</span><small>fetch window start</small></div>
</div>

<input id="q" type="search" placeholder="Filter by committee, date, status, bill number…" autocomplete="off">
<div class="tablewrap">
<table id="t">
<thead><tr><th>ID</th><th>Type</th><th>Committee / subject</th><th>Event date</th><th>Start</th><th>Status</th><th>Location</th><th>Bills</th><th>Fetched (UTC)</th></tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody>
</table>
</div>
<footer>Fetch window: {esc(window)}. Built {esc(built)} from hearings.json. Sequential fetch, 1.5s between requests.</footer>
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
    print(f"wrote {OUT.name} ({len(records)} rows, {OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
