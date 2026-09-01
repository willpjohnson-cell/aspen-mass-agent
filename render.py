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
import posixpath
import sys
from urllib.parse import quote
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runner  # noqa: E402

ROOT = runner.ROOT
PLATFORM = "The Monitor"
TAGLINE = "It archives government web pages and records when they change."
STYLESHEET = "assets/style.css"
FONTS = "fonts/fonts.css"


class Page:
    """One output file, and the arithmetic for linking out of it.

    Every href in a generated page is a repo-relative path resolved against the
    page's own location, so a page can be written at any depth without a link
    being rewritten by hand. Paths that arrive as data — the snapshot paths
    stored in run records — go through the same resolution.
    """

    def __init__(self, path):
        self.path = str(path).lstrip("./")
        self.dir = posixpath.dirname(self.path)

    def rel(self, target):
        """Repo-relative target -> href from this page."""
        return posixpath.relpath(str(target), self.dir or ".")

    def url(self, target):
        """As rel(), percent-encoded for characters that are legal but risky."""
        return quote(self.rel(target), safe="/")

    def head(self):
        return (f'<link rel="stylesheet" href="{self.rel(FONTS)}">\n'
                f'<link rel="stylesheet" href="{self.rel(STYLESHEET)}">')

    def write(self, doc):
        out = ROOT / self.path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(doc, encoding="utf-8")
        return out


CSS = """:root {
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

  .rule { border-top: 1px solid var(--rule); padding: 1rem 0 0.4rem; }
  .rule h3 { font-family: var(--mono); font-size: var(--t-sm); }
  .ruletext { max-width: 40rem; margin: 0 0 0.6rem; }
  .verdicts { display: flex; flex-wrap: wrap; gap: 1.5rem 2.5rem; margin: 0.8rem 0 0.4rem; }
  .verdict { display: flex; flex-direction: column; gap: 0.1rem; }
  .verdict .n { font-family: var(--mono); font-variant-numeric: tabular-nums;
                font-size: var(--t-lg); line-height: 1; }
  .verdict .k { font-size: var(--t-sm); color: var(--muted); }
  ul.reasons { margin: 0.2rem 0 0.6rem; padding-left: 0; list-style: none;
               max-width: 44rem; }
  ul.reasons li { display: flex; gap: 0.6rem; font-size: var(--t-sm);
                  color: var(--muted); padding: 0.15rem 0; }
  ul.reasons .n { font-family: var(--mono); font-variant-numeric: tabular-nums;
                  color: var(--ink); flex: 0 0 3rem; text-align: right; }
  .emptystate { border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule);
                padding: 1rem 0; max-width: 44rem; }
  .emptystate p:first-child { margin: 0 0 0.5rem; font-weight: 600; }
  .internal { border-left: 3px solid var(--rule-strong); padding-left: 1rem; }
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

  /* --- navigation and beat cards -------------------------------------- */
  .crumbs {
    padding: 1.25rem 0 0; font-size: var(--t-sm); color: var(--muted);
  }
  .crumbs a { color: inherit; }
  .crumbs [aria-current="page"] { color: var(--ink); font-weight: 600; }
  .card { border-top: 1px solid var(--rule); padding: 1.25rem 0; }
  .card:last-child { border-bottom: 1px solid var(--rule); }
  .card h3 { font-size: var(--t-md); margin: 0 0 0.15rem; }
  .cardsub { font-size: var(--t-sm); color: var(--muted); margin: 0 0 0.6rem; }
  .card .stats { margin: 0.8rem 0 0.6rem; gap: 1.25rem 2rem; }
  .card .stats .n { font-size: var(--t-md); }
"""


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


def custody(change, page):
    """Both observations, both hashes, both snapshots, beside the claim."""
    bits = []
    if change.get("observed_before_utc"):
        bits.append(f'<span>First seen {stamp(change["observed_before_utc"])}</span>')
    if change.get("observed_after_utc"):
        bits.append(f'<span>Changed by {stamp(change["observed_after_utc"])}</span>')
    prev, cur = change.get("previous_snapshot"), change.get("current_snapshot")
    if prev:
        bits.append(f'<span>Snapshot before <a href="{esc(page.rel(prev))}">'
                    f'{hashcell(change.get("raw_sha256_before"))}</a></span>')
    else:
        bits.append('<span class="flagged">The replaced bytes were not retained, so '
                    'the previous values cannot be checked against a snapshot.</span>')
    if cur:
        bits.append(f'<span>Snapshot after <a href="{esc(page.rel(cur))}">'
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


def change_entry(change, records, page, lead=False):
    body = "".join(field_block(f) for f in change.get("fields_changed", []))
    note = (f'<p class="note">{esc(change["provenance_note"])}</p>'
            if change.get("provenance_note") else "")
    when = change.get("observed_after_utc") or change.get("detected_in_run_started_utc")
    heading = describe(change, records)
    page_label = f'<span class="id">page {change["id"]}</span>'
    if lead:
        return (f'<div class="headline">'
                f'<p class="when">Detected {stamp(when)}</p>'
                f'<p class="what">{heading} {page_label}</p>'
                f'{body}{note}{custody(change, page)}</div>')
    return (f'<div class="entry">'
            f'<h3>{heading} {page_label}</h3>'
            f'<p class="when stamp">Detected {esc(when)}</p>'
            f'{body}{note}{custody(change, page)}</div>')


def archive_table(beat, records, slice_field, slice_value, page):
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
        snapshot = page.rel(f"raw/{r['id']}.html")
        rows.append(
            f'<tr data-slice="{"1" if in_slice else "0"}">'
            f'<td data-label="Page"><a class="id" href="{esc(r["source_url"])}">'
            f'{r["id"]}</a></td>'
            + "".join(cells)
            + f'<td data-label="Fetched">{stamp(r.get("fetched_at_utc"))}</td>'
            f'<td data-label="Snapshot"><a href="{esc(snapshot)}">'
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


def rules_section(report):
    """What each rule asks, and how every archived page answered it."""
    if not report:
        return ('<p class="lede">No rule evaluation has been written yet. Run '
                '<code>runner.py rules</code>.</p>')
    blocks = []
    for rule in report["rules"]:
        counts = report["tallies"][rule["id"]]
        total = sum(counts.values())
        bar = "".join(
            f'<div class="verdict"><span class="n">{counts[k]}</span>'
            f'<span class="k">{k.replace("_", " ")}</span></div>'
            for k in ("compliant", "not_compliant", "indeterminate"))
        reasons = {}
        for r in report["results"]:
            if r["rule"] == rule["id"] and r["status"] == "indeterminate":
                reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
        why = "".join(
            f'<li><span class="n">{n}</span> {esc(reason)}</li>'
            for reason, n in sorted(reasons.items(), key=lambda kv: -kv[1]))
        blocks.append(
            f'<div class="rule">'
            f'<h3>{esc(rule["id"])}</h3>'
            f'<p class="ruletext">{esc((rule.get("description") or "").strip())}</p>'
            f'<p class="note"><strong>Rule as published:</strong> '
            f'{esc((rule.get("source") or "").strip())}</p>'
            f'<p class="note"><strong>What the test actually measures:</strong> '
            f'{esc((rule.get("measures") or "").strip())}</p>'
            f'<p class="note"><strong>Exceptions the archive cannot see:</strong> '
            f'{esc((rule.get("exceptions") or "").strip())}</p>'
            f'<p class="note">Test: <span class="val">{esc(rule.get("test"))}</span> '
            f'over {total} archived pages.</p>'
            f'<div class="verdicts">{bar}</div>'
            + (f'<p class="note">Why every page is indeterminate:</p>'
               f'<ul class="reasons">{why}</ul>' if why else "")
            + '</div>')
    return "".join(blocks)


def findings_section(confirmed, unreviewed, report):
    """Confirmed findings are public. Everything else is labelled unreviewed."""
    if confirmed:
        rows = "".join(
            f'<div class="entry"><h3>{esc(f["rule"])} on page '
            f'<span class="id">{f["id"]}</span></h3>'
            f'<p class="note">{esc(f.get("latest_engine_reason", ""))}</p>'
            f'<p class="note">Confirmed {stamp(f.get("reviewed_utc"))} '
            f'{esc(f.get("reviewed_by", ""))}. {esc(f.get("reviewer_note", ""))}</p>'
            f'<div class="custody"><span><a href="{esc(f.get("source_url", ""))}">'
            f'Live page</a></span></div></div>'
            for f in confirmed)
        return rows
    n_not = sum(t.get("not_compliant", 0) for t in (report or {}).get("tallies", {}).values())
    return (
        '<div class="emptystate">'
        '<p>No finding has been confirmed, because no rule has evaluated a page as '
        'not compliant.</p>'
        f'<p class="note">Producing one takes three things in order. A run has to '
        f'discover a hearing page that an earlier run recorded as absent, which is '
        f'what makes its first-seen date bounded evidence rather than an unknown '
        f'earlier time. The rule then has to evaluate that page as not compliant, '
        f'which currently happens for {n_not} of the archived pages. A reviewer then '
        f'has to open the findings file and set that finding\'s status to confirmed. '
        f'Nothing here can perform that last step.</p>'
        '</div>')


def unreviewed_section(unreviewed):
    if not unreviewed:
        return ('<p class="note">The review queue is empty. Nothing has been flagged '
                'for a reviewer to look at.</p>')
    rows = "".join(
        f'<tr><td data-label="Rule">{esc(f["rule"])}</td>'
        f'<td data-label="Page"><a class="id" href="{esc(f.get("source_url", ""))}">'
        f'{f["id"]}</a></td>'
        f'<td data-label="Status">{esc(f.get("status"))}</td>'
        f'<td data-label="Queued">{stamp(f.get("created_utc"))}</td>'
        f'<td data-label="Engine said">{esc(f.get("latest_engine_reason", ""))}</td></tr>'
        for f in unreviewed)
    return ('<div class="scroller"><table class="rows"><thead><tr><th>Rule</th>'
            '<th>Page</th><th>Status</th><th>Queued</th><th>Engine said</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>')


def scope_box(beat):
    scope = beat.get("presentation", "scope") or {}
    if not scope.get("establishes") and not scope.get("does_not_establish"):
        return ""
    third = scope.get("notice_dates")
    extra = (f'  <p><strong>Notice dates:</strong> {third}</p>\n' if third else "")
    return (f'<div class="scope">\n'
            f'  <h2>{esc(scope.get("heading", "What this shows"))}</h2>\n'
            f'  <p><strong>Establishes:</strong> {scope["establishes"]}</p>\n'
            f'  <p><strong>Does not establish:</strong> {scope["does_not_establish"]}</p>\n'
            f'{extra}'
            f'</div>')


def lower_first(text):
    """The beat description follows 'watches' in a sentence, so it must not
    start with a capital that belongs to a standalone sentence."""
    text = (text or "").strip()
    if len(text) > 1 and text[1:2].islower():
        return text[0].lower() + text[1:]
    return text



# --- one place that knows what a beat's data looks like ------------------

class Context:
    """Everything one beat's pages need, loaded once."""

    def __init__(self, beat):
        self.beat = beat
        self.name = beat.name
        data_file = beat.data_dir / f"{beat.name}.json"
        self.records = (json.loads(data_file.read_text(encoding="utf-8"))
                        if data_file.exists() else [])
        self.by_id = {r["id"]: r for r in self.records}
        self.runs = runner.load_runs(beat.name)
        self.changes = runner.all_changes(beat.name)
        rules_path = (beat.path("storage", "rules_out")
                      or beat.data_dir / f"{beat.name}-rules.json")
        self.rules = (json.loads(rules_path.read_text(encoding="utf-8"))
                      if rules_path.exists() else None)
        findings = runner.load_findings(beat)
        self.confirmed = [f for f in findings if f.get("status") == "confirmed"]
        self.unreviewed = [f for f in findings if f.get("status") != "confirmed"]
        self.latest = self.runs[-1] if self.runs else None
        dv = beat.get("presentation", "default_view") or {}
        self.slice_field, self.slice_value = dv.get("field"), dv.get("value")
        self.slice_label = dv.get("label", "the default slice")
        self.slice_empty = dv.get("empty_note", "")
        self.slice_rows = [r for r in self.records
                           if self.slice_field and r.get(self.slice_field) == self.slice_value]

    # page locations, so nothing spells these out by hand
    @property
    def home(self):
        return f"beats/{self.name}/index.html"

    @property
    def archive(self):
        return f"beats/{self.name}/archive.html"

    @property
    def runs_page(self):
        return f"beats/{self.name}/runs/index.html"

    @property
    def last_run_utc(self):
        return self.latest["finished_utc"] if self.latest else None

    def verdicts(self):
        """Totals across every rule this beat declares."""
        totals = {"compliant": 0, "not_compliant": 0, "indeterminate": 0}
        for counts in (self.rules or {}).get("tallies", {}).values():
            for k in totals:
                totals[k] += counts.get(k, 0)
        return totals

    def last_run_sentence(self):
        if not self.latest:
            return "No run has been recorded yet."
        n = len(self.latest["changed_pages"])
        if self.latest["kind"] == "initial-collection":
            body = f'archived {len(self.latest["new_pages"])} pages'
        elif n:
            body = f'checked {self.latest["pages_checked"]} pages and found {n} changed'
        else:
            body = (f'checked {self.latest["pages_checked"]} pages, none changed since '
                    f'the previous run')
        return f"The last run {body}. It finished {self.latest['finished_utc']}."


# --- the page shell ------------------------------------------------------

def document(page, title, body, crumbs=""):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
{page.head()}
</head>
<body>
<div class="wrap">
{crumbs}
{body}
</div>
</body>
</html>
"""


def crumbs(page, trail):
    """trail: list of (label, repo-relative target or None for the current page)."""
    parts = []
    for label, target in trail:
        if target:
            parts.append(f'<a href="{page.rel(target)}">{esc(label)}</a>')
        else:
            parts.append(f'<span aria-current="page">{esc(label)}</span>')
    return f'<nav class="crumbs">{" / ".join(parts)}</nav>'


# --- landing -------------------------------------------------------------

def landing_page(contexts):
    page = Page("index.html")
    archived = sum(len(c.records) for c in contexts)
    detected = sum(len(c.changes) for c in contexts)
    verdicts = {"compliant": 0, "not_compliant": 0, "indeterminate": 0}
    for c in contexts:
        for k, v in c.verdicts().items():
            verdicts[k] += v
    confirmed = sum(len(c.confirmed) for c in contexts)
    last = max((c.last_run_utc for c in contexts if c.last_run_utc), default=None)

    cells = [(f"{len(contexts)}", f"beat{'s' if len(contexts) != 1 else ''} running"),
             (f"{archived:,}", "pages archived"),
             (f"{detected}", "changes detected"),
             (f"{confirmed}", "findings confirmed")]
    stats = "".join(f'<div><span class="n">{v}</span><span class="k">{k}</span></div>'
                    for v, k in cells)

    rows = "".join(
        f'<tr><td data-label="Beat"><a href="{page.rel(c.home)}">{esc(c.name)}</a></td>'
        f'<td data-label="Watching">{esc(c.beat.get("title", default=""))}</td>'
        f'<td data-label="Pages">{len(c.records):,}</td>'
        f'<td data-label="Last run">{stamp(c.last_run_utc) or "never"}</td></tr>'
        for c in contexts)

    body = f"""
<header>
  <h1>{PLATFORM}</h1>
  <p class="tagline">{TAGLINE}</p>
  <p class="beats">Every page a beat watches is archived byte for byte. Every run
  records what changed. Every rule returns a verdict a person can check, or says
  why it cannot.</p>
</header>

<section>
  <h2>Beats running: {len(contexts)}</h2>
  <div class="scroller"><table class="rows">
  <thead><tr><th>Beat</th><th>Watching</th><th>Pages</th><th>Last run</th></tr></thead>
  <tbody>{rows}</tbody></table></div>
  <p class="note"><a href="{page.rel("beats/index.html")}">All beats</a></p>
</section>

<section>
  <h2>How it works</h2>

  <h3>Evidence before conclusions</h3>
  <p class="prose">A beat fetches the pages it watches one at a time and stores
  exactly the bytes the server sent. Nothing is cleaned or reformatted. Every row
  of extracted data carries the SHA-256 of the file it came from, so any claim on
  these pages can be checked against the bytes behind it.</p>

  <h3>Three verdicts, and no fourth</h3>
  <p class="prose">Rules are configuration, not code. Each one is evaluated against
  every archived page and returns <strong>compliant</strong>,
  <strong>not compliant</strong>, or <strong>indeterminate</strong> with a reason.
  A rule whose evidence is missing returns indeterminate rather than a guess, and
  no page is skipped. Across every beat that is currently
  {verdicts["compliant"]:,} compliant, {verdicts["not_compliant"]:,} not compliant,
  and {verdicts["indeterminate"]:,} indeterminate.</p>

  <h3>Only a person promotes a finding</h3>
  <p class="prose">A not-compliant verdict becomes a finding with the status
  <strong>pending</strong>. It appears publicly only after someone reviews it and
  sets its status to confirmed in the findings file. There is no automatic
  promotion and no flag that creates one; exactly one line in this codebase writes
  a finding status, and it writes pending.</p>

  <h3>When a page was first seen, and how well that is known</h3>
  <p class="prose">Notice rules depend on knowing when something became visible, so
  each page carries a first-seen timestamp with a confidence.
  <strong>Bounded</strong> means an earlier run recorded the page as absent and a
  later one found it, placing its appearance inside a known window.
  <strong>Unbounded</strong> means the page was already there the first time
  anything looked; it existed at some unknown earlier time. An unbounded
  observation is never used to produce a notice figure, whatever the arithmetic
  would say.</p>
</section>

<section>
  <h2>Totals</h2>
  <div class="stats">{stats}</div>
  <p class="note">{"Last run finished " + esc(last) + "." if last else "No run recorded yet."}</p>
</section>
"""
    return page, document(page, PLATFORM, body)


# --- beats index ---------------------------------------------------------

def beats_index_page(contexts):
    page = Page("beats/index.html")
    cards = []
    for c in contexts:
        v = c.verdicts()
        cards.append(f"""<div class="card">
  <h3><a href="{page.rel(c.home)}">{esc(c.name)}</a></h3>
  <p class="cardsub">{esc(c.beat.get("title", default=""))} — {esc(c.beat.get("jurisdiction", default=""))}</p>
  <p class="prose">{esc(c.beat.get("description", default="").strip())}</p>
  <div class="stats">
    <div><span class="n">{len(c.records):,}</span><span class="k">pages archived</span></div>
    <div><span class="n">{len(c.changes)}</span><span class="k">changes detected</span></div>
    <div><span class="n">{len(c.runs)}</span><span class="k">runs recorded</span></div>
    <div><span class="n">{v["not_compliant"]}</span><span class="k">not compliant</span></div>
    <div><span class="n">{v["indeterminate"]:,}</span><span class="k">indeterminate</span></div>
  </div>
  <p class="note">{esc(c.last_run_sentence())}</p>
  <p class="note"><a href="{page.rel(c.home)}">Beat</a> ·
    <a href="{page.rel(c.archive)}">Archive</a> ·
    <a href="{page.rel(c.runs_page)}">Runs</a> ·
    <a href="{page.rel(f"beats/{c.name}/beat.yaml")}">beat.yaml</a></p>
</div>""")
    body = f"""
<header>
  <h1>Beats</h1>
  <p class="tagline">One beat is one government surface being watched.</p>
</header>
<section>{"".join(cards)}</section>
"""
    trail = crumbs(page, [(PLATFORM, "index.html"), ("Beats", None)])
    return page, document(page, f"Beats — {PLATFORM}", body, trail)


# --- one beat ------------------------------------------------------------

def beat_page(c):
    page = Page(c.home)
    beat = c.beat

    if c.changes:
        lead = change_entry(c.changes[0], c.by_id, page, lead=True)
        others = [x for x in c.changes[1:] if x["run_id"] == c.changes[0]["run_id"]]
        if others:
            lead += (f'<p class="note">{len(others)} other page'
                     f'{"s" if len(others) != 1 else ""} changed in the same run.</p>')
    else:
        lead = ('<div class="headline"><p class="what">No run has detected a change '
                'yet.</p><p class="note">Every run so far found the archived pages '
                'saying what they said before.</p></div>')

    stat = beat.get("presentation", "summary_stat") or {}
    total = (sum(r.get(stat.get("field")) or 0 for r in c.records)
             if stat.get("field") else None)
    cells = [(f"{len(c.records):,}", "pages archived"),
             (f"{len(c.runs)}", "runs recorded"),
             (f"{len(c.changes)}", "changes detected")]
    if total is not None:
        cells.append((f"{total:,}", esc(stat.get("label", stat["field"]))))
    if c.latest and c.latest.get("ids_absent") is not None:
        cells.append((f"{c.latest['ids_absent']}", "ids absent inside the range"))
    if c.rules:
        n = len(c.rules["rules"])
        cells.append((f"{n}", f"rule{'s' if n != 1 else ''} evaluated"))
    stats = "".join(f'<div><span class="n">{v}</span><span class="k">{k}</span></div>'
                    for v, k in cells)

    changes_list = ("".join(change_entry(x, c.by_id, page) for x in c.changes)
                    if c.changes else
                    '<p class="lede">No run has detected a change yet.</p>')

    body = f"""
<header>
  <h1>{esc(beat.get("title", default=c.name))}</h1>
  <p class="tagline">{esc(beat.get("description", default="").strip())}</p>
  <p class="beats"><a href="{page.rel(c.archive)}">Archive of {len(c.records):,} pages</a> ·
    <a href="{page.rel(c.runs_page)}">Run records</a> ·
    <a href="{page.rel(f"beats/{c.name}/beat.yaml")}">beat.yaml</a> ·
    <a href="{page.rel(f"data/{c.name}.json")}">data</a></p>
</header>

<section>
  <h2>Most recent change</h2>
  <p class="lede">{esc(c.last_run_sentence())}</p>
  {lead}
</section>

<hr class="divider">

<section>
  <h2>Every change detected</h2>
  <p class="lede">Newest first. Each entry links to the snapshot taken before the
  change and the one taken after.</p>
  {changes_list}
</section>

<hr class="divider">

<section>
  <h2>Rules</h2>
  <p class="lede">Each rule is evaluated against every archived page and returns one
  of three verdicts. A page whose evidence is missing, or whose first-seen date is
  unbounded, returns indeterminate with a reason rather than a guess.</p>
  {rules_section(c.rules)}
</section>

<hr class="divider">

<section>
  <h2>Confirmed findings</h2>
  <p class="lede">A finding appears here only after a person has reviewed it and set
  its status to confirmed in the findings file.</p>
  {findings_section(c.confirmed, c.unreviewed, c.rules)}
</section>

<section class="internal">
  <h2>Review queue, unreviewed</h2>
  <p class="lede">Everything the engine has flagged that no one has reviewed yet.
  Nothing in this section is a confirmed finding, and nothing here appears above.</p>
  {unreviewed_section(c.unreviewed)}
</section>

<hr class="divider">

<section>
  <h2>Run history</h2>
  <p class="lede">A run re-fetches every id in the range and compares what each page
  says against the previous run.
  <a href="{page.rel(c.runs_page)}">All run records</a>.</p>
  {runs_table(c.runs[-5:])}
</section>

<section>
  <h2>Totals</h2>
  <div class="stats">{stats}</div>
</section>

<section>
  {scope_box(beat)}
</section>

<footer>
{esc(footer_line(c))}
</footer>
"""
    trail = crumbs(page, [(PLATFORM, "index.html"), ("Beats", "beats/index.html"),
                          (c.name, None)])
    return page, document(page, f"{c.name} — {PLATFORM}", body, trail)


def footer_line(c):
    if c.latest:
        return (f"Built from the run that finished {c.latest['finished_utc']}. Pages are "
                f"fetched one at a time with {c.beat.delay} seconds between requests. Raw "
                f"HTML is stored exactly as the server sent it; when a page's content "
                f"changes, the replaced bytes are kept under raw/_superseded.")
    return (f"No run has been recorded yet. Pages are fetched one at a time with "
            f"{c.beat.delay} seconds between requests.")


# --- the archive ---------------------------------------------------------

def archive_page(c):
    page = Page(c.archive)
    placeholder = c.beat.get("presentation", "filter_placeholder", default="Filter…")
    intro = (f'Showing {len(c.slice_rows)} {esc(c.slice_label)}.' if c.slice_rows
             else esc(c.slice_empty))
    body = f"""
<header>
  <h1>Archive</h1>
  <p class="tagline">{len(c.records):,} pages archived from
  {esc(c.beat.get("title", default=c.name))}. Each row shows what a page said, when
  it was fetched, and the hash of the stored snapshot it came from.</p>
</header>

<section>
  <div class="controls">
    <input id="q" type="search" placeholder="{esc(placeholder)}" autocomplete="off"
           aria-label="Filter the archive">
    <button class="expand" id="expand" aria-expanded="false">Show all {len(c.records):,} pages</button>
    <span class="count" id="count">{intro}</span>
  </div>
  {archive_table(c.beat, c.records, c.slice_field, c.slice_value, page)}
</section>

<section>
  {scope_box(c.beat)}
</section>

<script>
(function () {{
  var q = document.getElementById('q');
  var expand = document.getElementById('expand');
  var count = document.getElementById('count');
  var rows = Array.prototype.slice.call(document.querySelectorAll('#archive tbody tr'));
  var expanded = false;
  var sliceIntro = {json.dumps(intro)};
  var sliceLabel = {json.dumps(c.slice_label)};

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
"""
    trail = crumbs(page, [(PLATFORM, "index.html"), ("Beats", "beats/index.html"),
                          (c.name, c.home), ("Archive", None)])
    return page, document(page, f"Archive — {c.name}", body, trail)


# --- the beat's run records ---------------------------------------------

def runs_page(c):
    page = Page(c.runs_page)
    rows = []
    for r in reversed(c.runs):
        n = len(r["changed_pages"])
        outcome = (f'{len(r["new_pages"])} pages archived'
                   if r["kind"] == "initial-collection" else
                   (f'{n} page{"s" if n != 1 else ""} changed' if n else
                    f'{r["pages_checked"]} pages checked, none changed since the '
                    f'previous run'))
        name = f'{r["run_id"]}.json'
        rows.append(f'<tr><td data-label="Started">{stamp(r["started_utc"])}</td>'
                    f'<td data-label="Kind">{esc(r["kind"].replace("-", " "))}</td>'
                    f'<td data-label="Outcome">{esc(outcome)}</td>'
                    f'<td data-label="Record">'
                    f'<a href="{page.url(f"runs/{name}")}">{esc(name)}</a></td></tr>')
    body = f"""
<header>
  <h1>Run records</h1>
  <p class="tagline">One JSON record per pass over the {esc(c.name)} beat, newest
  first. Each records what was checked and what changed.</p>
</header>
<div class="scroller"><table class="rows">
<thead><tr><th>Started</th><th>Kind</th><th>Outcome</th><th>Record</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table></div>
"""
    trail = crumbs(page, [(PLATFORM, "index.html"), ("Beats", "beats/index.html"),
                          (c.name, c.home), ("Runs", None)])
    return page, document(page, f"Run records — {c.name}", body, trail)


# --- build ---------------------------------------------------------------

def build():
    contexts = [Context(runner.Beat(n)) for n in runner.available()]
    if not contexts:
        sys.exit(f"no beats in {runner.BEATS}")

    pages = [landing_page(contexts), beats_index_page(contexts)]
    for c in contexts:
        pages.append(beat_page(c))
        pages.append(archive_page(c))
        pages.append(runs_page(c))

    stylesheet = ROOT / STYLESHEET
    stylesheet.parent.mkdir(parents=True, exist_ok=True)
    stylesheet.write_text(CSS, encoding="utf-8")
    print(f"wrote {STYLESHEET} ({stylesheet.stat().st_size} bytes)")
    for page, doc in pages:
        out = page.write(doc)
        print(f"wrote {page.path} ({out.stat().st_size:,} bytes)")
    print(f"{len(contexts)} beat(s), {len(pages)} pages")


if __name__ == "__main__":
    build()
