#!/usr/bin/env python3
"""Render the platform page from beats/, runs/ and data/.

Source-agnostic: field names, labels, the default archive slice and the scope
disclosure all come from a beat's config. Nothing is rendered that is not
backed by a file in this repository.

The page leads with the most recent detected change, because that is what a
beat exists to surface. The archive table is the evidence behind it, not the
headline.
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
PLATFORM = "The Monitor"
TAGLINE = ("It archives government web pages and records when they change.")

STYLE = """<link rel="stylesheet" href="fonts/fonts.css">
<style>
  :root {
    /* Neutrals carry the whole page. One accent, used only for a changed value. */
    --ground: #f7f8f7;
    --raised: #ffffff;
    --ink: #171a18;
    --muted: #5c635e;
    --faint: #868d88;
    --rule: #d8dcd8;
    --rule-strong: #b2b8b3;
    --accent: #15683f;
    --accent-bg: #e2eee8;

    --ui: "Public Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica,
          Arial, sans-serif;
    --mono: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;

    /* Type scale, 1.2 */
    --t-xs: 0.8125rem;
    --t-sm: 0.875rem;
    --t-base: 1rem;
    --t-md: 1.125rem;
    --t-lg: 1.375rem;
    --t-xl: 1.75rem;
    --t-2xl: 2.5rem;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --ground: #141614;
      --raised: #1b1e1c;
      --ink: #e8eae8;
      --muted: #9aa19c;
      --faint: #737a75;
      --rule: #2c312e;
      --rule-strong: #414743;
      --accent: #6cc397;
      --accent-bg: #17301f;
    }
  }
  :root[data-theme="dark"] {
    --ground: #141614;
    --raised: #1b1e1c;
    --ink: #e8eae8;
    --muted: #9aa19c;
    --faint: #737a75;
    --rule: #2c312e;
    --rule-strong: #414743;
    --accent: #6cc397;
    --accent-bg: #17301f;
  }

  * { box-sizing: border-box; }

  body {
    margin: 0;
    padding: 0 1.25rem 5rem;
    background: var(--ground);
    color: var(--ink);
    font-family: var(--ui);
    font-size: var(--t-base);
    line-height: 1.55;
    -webkit-font-smoothing: antialiased;
  }

  .wrap { max-width: 64rem; margin: 0 auto; }
  /* Prose stays under 80 characters. */
  .prose, .lede, p.note, .scope { max-width: 40rem; }
  p { margin: 0 0 0.8rem; }

  a { color: inherit; text-decoration: underline; text-underline-offset: 2px;
      text-decoration-color: var(--rule-strong); }
  a:hover { text-decoration-color: currentColor; }
  a:focus-visible, button:focus-visible, input:focus-visible {
    outline: 2px solid var(--ink);
    outline-offset: 2px;
  }

  /* Monospace is reserved: timestamps, hashes, page ids, diffed values. */
  .id, .stamp, .hash, .val {
    font-family: var(--mono);
    font-variant-numeric: tabular-nums;
  }
  .stamp { font-size: var(--t-xs); color: var(--muted); white-space: nowrap; }
  .hash { font-size: var(--t-xs); color: var(--faint); }
  .id { font-size: 0.9em; }

  /* --- masthead ------------------------------------------------------- */
  header { padding: 3.25rem 0 1.75rem; }
  h1 {
    font-family: var(--ui);
    font-weight: 600;
    font-size: var(--t-2xl);
    letter-spacing: -0.02em;
    line-height: 1.05;
    margin: 0 0 0.35rem;
  }
  header .tagline {
    font-size: var(--t-md);
    color: var(--muted);
    margin: 0 0 1.1rem;
    max-width: 44rem;
    text-wrap: pretty;
  }
  header .beats { font-size: var(--t-sm); color: var(--muted); margin: 0; max-width: 40rem; }
  header .beats strong { color: var(--ink); font-weight: 600; }

  h2 {
    font-size: var(--t-lg);
    font-weight: 600;
    letter-spacing: -0.01em;
    margin: 0 0 0.25rem;
  }
  h3 { font-size: var(--t-base); font-weight: 600; margin: 0 0 0.25rem; }
  .lede { color: var(--muted); margin: 0 0 1rem; font-size: var(--t-sm); }

  section { margin: 0 0 2.5rem; }
  hr.divider { border: 0; border-top: 1px solid var(--rule); margin: 0 0 2rem; }

  /* --- the change that leads the page --------------------------------- */
  .headline {
    border-top: 2px solid var(--ink);
    border-bottom: 1px solid var(--rule);
    padding: 1rem 0 1.2rem;
  }
  .headline .when { margin: 0 0 0.5rem; font-size: var(--t-sm); color: var(--muted); }
  .headline .what {
    font-size: var(--t-xl);
    font-weight: 600;
    line-height: 1.25;
    letter-spacing: -0.015em;
    margin: 0 0 0.9rem;
    max-width: 36rem;
  }
  .headline .what .id { color: var(--muted); font-weight: 400; }

  .change { padding: 0.7rem 0; }
  .change + .change { border-top: 1px solid var(--rule); }
  .entry { padding: 1.15rem 0; }
  .entry + .entry { border-top: 1px solid var(--rule); }
  .entry h3 { font-size: var(--t-md); letter-spacing: -0.005em; }
  .entry .when { margin: 0.1rem 0 0.5rem; }
  .fieldname { font-size: var(--t-sm); color: var(--muted); }
  .diff { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.4rem 0.6rem;
          margin: 0.25rem 0 0; }
  .val { font-size: var(--t-sm); padding: 0.08rem 0.3rem; }
  .val.old { color: var(--muted); text-decoration: line-through;
             text-decoration-thickness: 1px; }
  .val.new { color: var(--accent); background: var(--accent-bg); font-weight: 500; }
  .becomes { font-size: var(--t-xs); color: var(--faint); }
  .items { display: flex; flex-wrap: wrap; gap: 0.25rem; }
  p.note, .note { font-size: var(--t-sm); color: var(--muted); margin: 0.35rem 0 0; }

  .custody {
    display: flex; flex-wrap: wrap; gap: 0.3rem 1.25rem;
    margin: 0.7rem 0 0; font-size: var(--t-xs); color: var(--muted);
  }
  .custody span { display: inline-flex; gap: 0.35rem; align-items: baseline; }
  .flagged { color: var(--ink); font-weight: 600; }

  /* --- views ---------------------------------------------------------- */
  .views { display: flex; gap: 0.2rem; border-bottom: 1px solid var(--rule); margin: 0 0 1rem; }
  .views button {
    appearance: none; background: transparent; border: 0;
    border-bottom: 2px solid transparent; margin-bottom: -1px;
    color: var(--muted); font: inherit; font-size: var(--t-sm);
    padding: 0.5rem 0.7rem; cursor: pointer;
  }
  .views button[aria-selected="true"] {
    color: var(--ink); font-weight: 600; border-bottom-color: var(--ink);
  }
  .views button:hover { color: var(--ink); }

  .controls { display: flex; flex-wrap: wrap; gap: 0.6rem; align-items: center;
              margin: 0 0 0.9rem; }
  input[type="search"] {
    flex: 1 1 18rem; max-width: 24rem;
    padding: 0.4rem 0.6rem;
    border: 1px solid var(--rule-strong); background: var(--raised);
    color: inherit; font: inherit; font-size: var(--t-sm);
  }
  button.expand {
    appearance: none; background: var(--raised); border: 1px solid var(--rule-strong);
    color: var(--ink); font: inherit; font-size: var(--t-sm);
    padding: 0.4rem 0.75rem; cursor: pointer;
  }
  button.expand:hover { border-color: var(--ink); }
  .count { font-size: var(--t-sm); color: var(--muted); }

  /* --- tables --------------------------------------------------------- */
  .scroller { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; font-size: var(--t-sm); }
  th, td {
    text-align: left; padding: 0.45rem 0.7rem 0.45rem 0; vertical-align: baseline;
    font-variant-numeric: tabular-nums;
  }
  thead th {
    color: var(--muted); font-weight: 600;
    border-bottom: 1px solid var(--rule-strong); white-space: nowrap;
  }
  tbody td { border-bottom: 1px solid var(--rule); }
  tbody tr:hover td { background: var(--raised); }
  td.wrapcell { min-width: 13rem; }
  td.listcell { color: var(--muted); min-width: 10rem; }
  .runs td, .runs th { padding-right: 1.4rem; }
  .runs td:first-child { white-space: nowrap; }

  /* --- totals --------------------------------------------------------- */
  .stats { display: flex; flex-wrap: wrap; gap: 1.5rem 2.5rem; }
  .stats div { display: flex; flex-direction: column; gap: 0.1rem; }
  .stats .n {
    font-family: var(--mono); font-variant-numeric: tabular-nums;
    font-size: var(--t-lg); line-height: 1;
  }
  .stats .k { font-size: var(--t-sm); color: var(--muted); }

  .scope { border-left: 3px solid var(--rule-strong); padding: 0.1rem 0 0.1rem 1rem; }
  .scope h2 { font-size: var(--t-base); margin: 0 0 0.4rem; }
  .scope p { margin: 0.35rem 0; font-size: var(--t-sm); }

  footer {
    margin-top: 2.5rem; padding-top: 1rem; border-top: 1px solid var(--rule);
    color: var(--faint); font-size: var(--t-xs); max-width: 46rem;
  }

  [hidden] { display: none !important; }

  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
      animation-duration: 0.01ms !important;
      transition-duration: 0.01ms !important;
    }
  }

  /* --- phones: every row becomes a stacked entry ---------------------- */
  @media (max-width: 700px) {
    table.rows, table.rows tbody, table.rows tr, table.rows td { display: block; width: 100%; }
    table.rows thead { display: none; }
    table.rows tr {
      border: 1px solid var(--rule); background: var(--raised);
      padding: 0.7rem 0.85rem; margin: 0 0 0.7rem;
    }
    table.rows td { border: 0; padding: 0.12rem 0; display: flex; gap: 0.75rem; }
    table.rows td:empty { display: none; }
    table.rows td::before {
      content: attr(data-label); color: var(--muted);
      flex: 0 0 7rem; font-size: var(--t-xs);
    }
    table.rows tbody tr:hover td { background: transparent; }
    .diff { flex-direction: column; align-items: flex-start; gap: 0.15rem; }
    .becomes { display: none; }
  }
</style>"""


def esc(v):
    return html.escape("" if v is None else str(v))


def stamp(value):
    return f'<span class="stamp">{esc(value)}</span>' if value else ""


def hashcell(value):
    if not value:
        return ""
    return f'<span class="hash" title="sha-256 {esc(value)}">{esc(value[:12])}…</span>'


def scalar_diff(before, after):
    return (f'<span class="diff">'
            f'<span class="val old">{esc(before)}</span>'
            f'<span class="becomes">becomes</span>'
            f'<span class="val new">{esc(after)}</span></span>')


def list_diff(before, after):
    """Show what entered and left the list, not both lists in full."""
    before, after = list(before or []), list(after or [])
    added = [x for x in after if x not in before]
    removed = [x for x in before if x not in after]
    out = []
    if added:
        out.append('<div class="diff"><span class="items">'
                   + "".join(f'<span class="val new">{esc(x)}</span>' for x in added)
                   + f'</span><span class="note">added, taking the list from '
                     f'{len(before)} to {len(after)}</span></div>')
    if removed:
        out.append('<div class="diff"><span class="items">'
                   + "".join(f'<span class="val old">{esc(x)}</span>' for x in removed)
                   + '</span><span class="note">removed</span></div>')
    if not added and not removed:
        out.append('<p class="note">The same items in a different order. '
                   'Nothing entered or left the list.</p>')
    return "".join(out)


def field_block(field):
    before, after = field["before"], field["after"]
    if isinstance(before, list) or isinstance(after, list):
        body = list_diff(before, after)
    else:
        body = scalar_diff(before if before not in (None, "") else "nothing",
                           after if after not in (None, "") else "nothing")
    return f'<div class="change"><span class="fieldname">{esc(field["field"])}</span>{body}</div>'


def custody(change):
    """Both observations, both hashes, both snapshots, beside the claim."""
    bits = []
    if change.get("observed_before_utc"):
        bits.append(f'<span>First seen {stamp(change["observed_before_utc"])}</span>')
    if change.get("observed_after_utc"):
        bits.append(f'<span>Changed by {stamp(change["observed_after_utc"])}</span>')
    prev, cur = change.get("previous_snapshot"), change.get("current_snapshot")
    if prev:
        bits.append(f'<span>Snapshot before <a href="{esc(prev)}">'
                    f'{hashcell(change.get("raw_sha256_before"))}</a></span>')
    else:
        bits.append('<span class="flagged">The replaced bytes were not retained, so '
                    'the previous values cannot be checked against a snapshot.</span>')
    if cur:
        bits.append(f'<span>Snapshot after <a href="{esc(cur)}">'
                    f'{hashcell(change.get("raw_sha256_after"))}</a></span>')
    if change.get("url"):
        bits.append(f'<span><a href="{esc(change["url"])}">Live page</a></span>')
    if prev and not change.get("previous_snapshot_verified"):
        bits.append('<span class="flagged">The stored snapshot does not match the '
                    'recorded hash.</span>')
    return f'<div class="custody">{"".join(bits)}</div>'


def describe(change, records):
    rec = records.get(change["id"], {})
    name = rec.get("committee") or rec.get("subject") or "An archived page"
    fields = [f["field"] for f in change.get("fields_changed", [])]
    if fields == ["status"]:
        f = change["fields_changed"][0]
        return f'{esc(name)} moved from {esc(f["before"])} to {esc(f["after"])}'
    if fields == ["bills"]:
        f = change["fields_changed"][0]
        added = [x for x in (f["after"] or []) if x not in (f["before"] or [])]
        if added:
            return f'{esc(name)} added {esc(", ".join(added))} to its agenda'
    if fields:
        return f'{esc(name)} changed {esc(" and ".join(fields))}'
    return f'{esc(name)} changed'


def change_entry(change, records, lead=False):
    body = "".join(field_block(f) for f in change.get("fields_changed", []))
    note = (f'<p class="note">{esc(change["provenance_note"])}</p>'
            if change.get("provenance_note") else "")
    when = change.get("observed_after_utc") or change.get("detected_in_run_started_utc")
    heading = describe(change, records)
    page = f'<span class="id">page {change["id"]}</span>'
    if lead:
        return (f'<div class="headline">'
                f'<p class="when">Detected {stamp(when)}</p>'
                f'<p class="what">{heading} {page}</p>'
                f'{body}{note}{custody(change)}</div>')
    return (f'<div class="entry">'
            f'<h3>{heading} {page}</h3>'
            f'<p class="when stamp">Detected {esc(when)}</p>'
            f'{body}{note}{custody(change)}</div>')


def archive_table(beat, records, slice_field, slice_value):
    hidden = set(beat.get("presentation", "hide_columns") or [])
    fields = [f for f in beat.fields if f["key"] not in hidden]
    head = "".join(f'<th>{esc(f["label"])}</th>' for f in fields)
    rows = []
    for r in sorted(records, key=lambda r: r["id"], reverse=True):
        in_slice = slice_field and r.get(slice_field) == slice_value
        cells = []
        for f in fields:
            v, label = r.get(f["key"]), esc(f["label"])
            if f.get("list"):
                text = ", ".join(str(x) for x in v) if v else ""
                cells.append(f'<td class="listcell" data-label="{label}">{esc(text)}</td>')
            elif v in (None, "", []):
                cells.append(f'<td data-label="{label}"></td>')
            else:
                cls = ' class="wrapcell"' if f["key"] in ("committee", "subject") else ""
                cells.append(f'<td{cls} data-label="{label}">{esc(v)}</td>')
        rows.append(
            f'<tr data-slice="{"1" if in_slice else "0"}">'
            f'<td data-label="Page"><a class="id" href="{esc(r["source_url"])}">'
            f'{r["id"]}</a></td>'
            + "".join(cells)
            + f'<td data-label="Fetched">{stamp(r.get("fetched_at_utc"))}</td>'
            f'<td data-label="Snapshot"><a href="raw/{r["id"]}.html">'
            f'{hashcell(r.get("raw_sha256"))}</a></td></tr>')
    return (f'<div class="scroller"><table class="rows" id="archive">'
            f'<thead><tr><th>Page</th>{head}<th>Fetched</th><th>Snapshot</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def runs_table(runs):
    rows = []
    for r in reversed(runs):
        n = len(r["changed_pages"])
        if r["kind"] == "initial-collection":
            outcome = f'{len(r["new_pages"])} pages archived'
        elif n:
            outcome = f'{n} page{"s" if n != 1 else ""} changed'
        else:
            outcome = (f'{r["pages_checked"]} pages checked, none changed since the '
                       f'previous run')
        kind = esc(r["kind"].replace("-", " "))
        if r.get("reconstructed"):
            kind += ' <span class="note">(reconstructed)</span>'
        rows.append(f'<tr><td data-label="Started">{stamp(r["started_utc"])}</td>'
                    f'<td data-label="Kind">{kind}</td>'
                    f'<td data-label="Checked">{r["pages_checked"]}</td>'
                    f'<td data-label="Outcome">{esc(outcome)}</td></tr>')
    return ('<div class="scroller"><table class="rows runs">'
            '<thead><tr><th>Started</th><th>Kind</th><th>Pages checked</th>'
            '<th>Outcome</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def scope_box(beat):
    scope = beat.get("presentation", "scope") or {}
    if not scope.get("establishes") and not scope.get("does_not_establish"):
        return ""
    return (f'<div class="scope">\n'
            f'  <h2>{esc(scope.get("heading", "What this shows"))}</h2>\n'
            f'  <p><strong>Establishes:</strong> {scope["establishes"]}</p>\n'
            f'  <p><strong>Does not establish:</strong> {scope["does_not_establish"]}</p>\n'
            f'</div>')


def lower_first(text):
    """The beat description follows 'watches' in a sentence, so it must not
    start with a capital that belongs to a standalone sentence."""
    text = (text or "").strip()
    if len(text) > 1 and text[1:2].islower():
        return text[0].lower() + text[1:]
    return text


def build():
    beats = [runner.Beat(n) for n in runner.available()]
    beat = beats[0]
    data_file = beat.data_dir / f"{beat.name}.json"
    records = json.loads(data_file.read_text(encoding="utf-8")) if data_file.exists() else []
    by_id = {r["id"]: r for r in records}
    runs = runner.load_runs(beat.name)
    changes = runner.all_changes(beat.name)
    built = datetime.now(timezone.utc).isoformat(timespec="seconds")

    latest = runs[-1] if runs else None
    dv = beat.get("presentation", "default_view") or {}
    dv_field, dv_value = dv.get("field"), dv.get("value")
    slice_rows = [r for r in records if dv_field and r.get(dv_field) == dv_value]

    if changes:
        lead = change_entry(changes[0], by_id, lead=True)
        others = [c for c in changes[1:] if c["run_id"] == changes[0]["run_id"]]
        if others:
            lead += (f'<p class="note">{len(others)} other page'
                     f'{"s" if len(others) != 1 else ""} changed in the same run, '
                     f'listed under changes below.</p>')
    else:
        lead = ('<div class="headline"><p class="what">No run has detected a change '
                'yet.</p><p class="note">Every run so far found the archived pages '
                'saying what they said before.</p></div>')

    if latest:
        n = len(latest["changed_pages"])
        if latest["kind"] == "initial-collection":
            status = f'The last recorded pass archived {len(latest["new_pages"])} pages.'
        elif n:
            status = (f'The last run checked {latest["pages_checked"]} pages and found '
                      f'{n} changed.')
        else:
            status = (f'The last run checked {latest["pages_checked"]} pages, none '
                      f'changed since the previous run.')
        status += f' It started {latest["started_utc"]}.'
    else:
        status = "No run has been recorded yet."

    stat = beat.get("presentation", "summary_stat") or {}
    total = sum(r.get(stat.get("field")) or 0 for r in records) if stat.get("field") else None
    cells = [(f"{len(records)}", "pages archived"),
             (f"{len(runs)}", "runs recorded"),
             (f"{len(changes)}", "changes detected")]
    if total is not None:
        cells.append((f"{total:,}", esc(stat.get("label", stat["field"]))))
    if latest and latest.get("ids_absent") is not None:
        cells.append((f"{latest['ids_absent']}", "ids absent inside the range"))
    stats = "".join(f'<div><span class="n">{v}</span><span class="k">{k}</span></div>'
                    for v, k in cells)

    changes_panel = ("".join(change_entry(c, by_id) for c in changes) if changes else
                     '<p class="lede">No run has detected a change yet.</p>')

    placeholder = beat.get("presentation", "filter_placeholder", default="Filter…")
    slice_label = dv.get("label", "the default slice")
    slice_intro = (f'Showing {len(slice_rows)} {esc(slice_label)}.' if slice_rows
                   else esc(dv.get("empty_note", "")))

    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{PLATFORM}</title>
{STYLE}
</head>
<body>
<div class="wrap">

<header>
  <h1>{PLATFORM}</h1>
  <p class="tagline">{TAGLINE}</p>
  <p class="beats">Beats running: {len(beats)}. <strong>{esc(beat.name)}</strong> watches
  {esc(lower_first(beat.get('description', default='')))}
  Its definition is in <a href="beats/{esc(beat.name)}/beat.yaml">beat.yaml</a>, and its
  records are in <a href="runs/">runs</a> and <a href="data/{esc(beat.name)}.json">data</a>.</p>
</header>

<section>
  <h2>Most recent change</h2>
  <p class="lede">{esc(status)}</p>
  {lead}
</section>

<hr class="divider">

<section>
  <div class="views" role="tablist">
    <button id="tab-changes" role="tab" aria-selected="true" aria-controls="panel-changes">
      Changes ({len(changes)})</button>
    <button id="tab-archive" role="tab" aria-selected="false" aria-controls="panel-archive">
      Archive ({len(records)})</button>
  </div>

  <div id="panel-changes" role="tabpanel" aria-labelledby="tab-changes">
    <p class="lede">Every change any run has detected, newest first. Each entry links to
    the snapshot taken before the change and the one taken after.</p>
    {changes_panel}
  </div>

  <div id="panel-archive" role="tabpanel" aria-labelledby="tab-archive" hidden>
    <p class="lede">Each row shows what a page said, when it was fetched, and the hash of
    the stored snapshot it came from.</p>
    <div class="controls">
      <input id="q" type="search" placeholder="{esc(placeholder)}" autocomplete="off"
             aria-label="Filter the archive">
      <button class="expand" id="expand" aria-expanded="false">Show all {len(records)} pages</button>
      <span class="count" id="count">{slice_intro}</span>
    </div>
    {archive_table(beat, records, dv_field, dv_value)}
  </div>
</section>

<hr class="divider">

<section>
  <h2>Run history</h2>
  <p class="lede">A run re-fetches every id in the range and compares what each page says
  against the previous run.</p>
  {runs_table(runs)}
</section>

<section>
  <h2>Totals</h2>
  <div class="stats">{stats}</div>
</section>

<section>
  {scope_box(beat)}
</section>

<footer>
Built {esc(built)} from data/{esc(beat.name)}.json and runs/. Pages are fetched one at a
time with {esc(beat.delay)} seconds between requests. Raw HTML is stored exactly as the
server sent it; when a page's content changes, the replaced bytes are kept under
raw/_superseded.
</footer>

</div>
<script>
(function () {{
  var tabs = {{changes: document.getElementById('tab-changes'),
               archive: document.getElementById('tab-archive')}};
  var panels = {{changes: document.getElementById('panel-changes'),
                 archive: document.getElementById('panel-archive')}};
  function show(name) {{
    for (var k in tabs) {{
      var on = k === name;
      tabs[k].setAttribute('aria-selected', on ? 'true' : 'false');
      panels[k].hidden = !on;
    }}
  }}
  tabs.changes.addEventListener('click', function () {{ show('changes'); }});
  tabs.archive.addEventListener('click', function () {{ show('archive'); }});

  var q = document.getElementById('q');
  var expand = document.getElementById('expand');
  var count = document.getElementById('count');
  var rows = Array.prototype.slice.call(document.querySelectorAll('#archive tbody tr'));
  var expanded = false;
  var sliceIntro = {json.dumps(slice_intro)};
  var sliceLabel = {json.dumps(slice_label)};

  function apply() {{
    var needle = q.value.toLowerCase().trim();
    var shown = 0;
    rows.forEach(function (row) {{
      var match = !needle || row.textContent.toLowerCase().indexOf(needle) !== -1;
      var visible = needle ? match : (expanded || row.dataset.slice === '1');
      row.hidden = !visible;
      if (visible) shown++;
    }});
    if (needle) {{
      count.textContent = shown + ' of ' + rows.length + ' pages match.';
    }} else {{
      count.textContent = expanded ? 'Showing all ' + rows.length + ' pages.' : sliceIntro;
    }}
  }}
  q.addEventListener('input', apply);
  expand.addEventListener('click', function () {{
    expanded = !expanded;
    expand.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    expand.textContent = expanded ? 'Show ' + sliceLabel + ' only'
                                  : 'Show all ' + rows.length + ' pages';
    apply();
  }});
  apply();
}})();
</script>
</body>
</html>
"""
    OUT.write_text(doc, encoding="utf-8")
    print(f"wrote {OUT.name}: {len(records)} archived pages, {len(changes)} changes, "
          f"{len(runs)} runs, {len(slice_rows)} in the default slice, "
          f"{OUT.stat().st_size} bytes")


if __name__ == "__main__":
    build()
