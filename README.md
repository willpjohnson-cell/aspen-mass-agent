# The Monitor

It archives government web pages and records when they change.

A **beat** is one government surface being watched. A beat archives the pages it
watches byte for byte, extracts a small set of fields from them, and records what
changed between runs. The platform supplies everything that is not specific to a
government; a beat supplies the two files that are.

**Beats running: 1** — `ma-hearings`, watching Massachusetts Legislature committee
hearing and conference committee meeting pages.

## Layout

```
runner.py                       source-agnostic: fetch, archive, hash, timestamp, diff
render.py                       renders index.html from beats/, runs/ and data/
beats/
  ma-hearings/
    beat.yaml                   what to fetch, how politely, how to present it
    parse.py                    the only Massachusetts-specific code
fonts/                          self-hosted Public Sans and IBM Plex Mono
runs/{timestamp}.json           one record per run
raw/{id}.html                   byte-for-byte page snapshots
raw/_superseded/{id}/…          prior bytes, kept when a page's content changes
data/                           extracted json + csv, and the snapshot ledger
fetch_status.tsv                every request made: id, status, bytes, UTC time
index.html                      the rendered page
```

## Commands

```bash
ARCHIVE_CONTACT="+https://github.com/you/your-repo" python3 runner.py collect ma-hearings
python3 runner.py run ma-hearings        # one pass over the beat; writes runs/{timestamp}.json
python3 runner.py extract ma-hearings    # archived pages -> data/ma-hearings.{json,csv}
python3 runner.py check ma-hearings      # cross-check the parser against a second reader
python3 runner.py runs ma-hearings       # run history
python3 runner.py beats                  # installed beats
python3 render.py                        # rebuild index.html
```

`ARCHIVE_CONTACT` is substituted into the beat's User-Agent. The runner
refuses to send an anonymous one.

## How a beat is defined

Two files. Nothing else.

### `beat.yaml`

Declares the source and how to treat it. The keys the runner reads:

| Key | Meaning |
| --- | --- |
| `source.url_pattern` | URL with `{id}` substituted per page |
| `discovery.kind` | id-space strategy; `integer-ids` is implemented |
| `discovery.floor` / `anchor` / `probe` | walk down to `floor`; bracket the frontier from `anchor` and `probe` |
| `discovery.clear_run` | consecutive absences required before calling a frontier |
| `politeness.delay_seconds` | seconds between requests |
| `politeness.parallel` | must be false; the runner refuses to parallelise |
| `politeness.user_agent` | `{contact}` is filled from `ARCHIVE_CONTACT` |
| `storage.*` | archive, superseded, request log, data, snapshot ledger paths |
| `fields` | ordered `key` / `label` pairs for the extract and the table |
| `diff_fields` | fields compared between runs to describe a change |
| `report_group_by` | groups the extraction report, so absences expected for one kind of page are legible |
| `presentation.*` | filter placeholder, hidden columns, a summary stat, the default archive slice, and the beat's scope disclosure |
| `schedule`, `title`, `jurisdiction`, `description` | shown on the page |

The scope disclosure lives in the beat's config rather than in the renderer:
only the beat knows what its source does and does not publish, so a new
jurisdiction states its own limits instead of inheriting Massachusetts'.

The page makes no external requests: Public Sans and IBM Plex Mono are checked
into `fonts/`.

Config is read by a small YAML-subset parser in `runner.py` (comments, nested
maps, lists, folded `>` blocks, scalars) so the platform needs no third-party
packages. It raises on anything outside that subset rather than guessing.

### `parse.py`

One required function:

```python
def parse(html: str) -> dict:
    """Raw HTML of one page -> flat dict of scalars and lists of scalars."""
```

A field that is not on the page must come back `None`. Do not infer, default, or
backfill anything — the runner counts every null and reports it, and that report
is only meaningful if a null means the page did not say.

One optional function:

```python
def crosscheck(html: str) -> dict:
    """The same fields, read a different way."""
```

`runner.py check` diffs `parse` against `crosscheck` over a spread of archived
pages. Two structurally different readers agreeing is what turns "this field is
null" into "this field is absent from the page" rather than "the parser missed
it". For `ma-hearings`, `parse` uses regexes and `crosscheck` uses
`html.parser`'s tokenizer.

The runner wraps whatever the parser returns with the id, source URL, raw
SHA-256, byte count, and observation timestamp. Parsers do not fetch, hash,
write files, or know that runs exist.

### Adding a jurisdiction

```bash
mkdir -p beats/<name>
$EDITOR beats/<name>/beat.yaml           # copy ma-hearings' and edit
$EDITOR beats/<name>/parse.py            # parse(html) -> dict
ARCHIVE_CONTACT="…" python3 runner.py collect <name>
python3 runner.py check <name> && python3 runner.py extract <name>
python3 render.py
```

The runner has no per-beat branches; it lists whatever is in `beats/` and
renders whatever `fields` a config declares. A source whose pages are not
addressed by integer ids needs a new `discovery.kind` in the runner — that is a
new strategy in the platform, deliberately, rather than a fork of it.

## How pages are collected

Sequentially, one request at a time, with the configured delay and no
parallelism. `robots.txt` for malegislature.gov disallows nothing on this path,
and pages are server-rendered, so plain `urllib` retrieves what a browser would.

The frontier — the highest live id — is not taken from a single 404. Roughly a
fifth of the ids in this range are absent, in runs of up to 16 consecutive, so
the runner requires `clear_run` consecutive absences before concluding.

Every request is appended to `fetch_status.tsv` with its status and UTC
timestamp, including the ones that 404. Gaps are part of the record.

## Rules and findings

Rules are configuration, not code. Each beat declares them in `beat.yaml` with an
id, the provision they come from, the evidence they require, and a test. The
engine in `rules.py` evaluates every rule against every archived page and returns
exactly one of three verdicts, each with a reason:

| Verdict | Meaning |
| --- | --- |
| `compliant` | The test ran on real evidence and passed. |
| `not_compliant` | The test ran on real evidence and failed. |
| `indeterminate` | The test could not be run. The reason says why. |

There is no fourth outcome, no default, and no skipped page.

### first_seen, and why its confidence decides everything

Every archived page carries a `first_seen` timestamp in
`data/<beat>-first-seen.tsv`, written once and never recomputed. It records the
earliest run that observed the page, and it carries a confidence:

- **bounded** — the id returned 404 in an earlier run and 200 in a later one, so
  the page became observable inside a known window. The window's start is stored
  with it. This is real evidence.
- **unbounded** — the page was already present the first time anything looked. It
  existed at some unknown earlier time. **This is not evidence of when it was
  posted**, and the engine refuses to compute a notice figure from it, whatever
  the arithmetic would say.

All 643 pages from the first collection are unbounded, so every rule currently
returns `indeterminate`. That is the correct result rather than an empty one.
Bounded evidence can only come from pages a future run discovers.

### The review queue

A `not_compliant` evaluation becomes a finding in `data/<beat>-findings.json` with
status `pending`, plus a reviewer note and timestamps. Only findings a person has
set to `confirmed` render in the public part of the page; pending and dismissed
appear in a separate section labelled unreviewed.

Nothing in this codebase writes `confirmed` — exactly one line assigns a finding
status, and it writes `pending`. Re-running the engine refreshes what it saw and
never touches a reviewer's decision or note.

```bash
python3 runner.py first-seen ma-hearings   # record when each page was first seen
python3 runner.py rules ma-hearings        # evaluate rules -> data/<beat>-rules.json
python3 runner.py findings ma-hearings     # queue not_compliant for review
```

## How change detection works

Each run re-fetches every id in the range and compares the hash of the **parsed
fields** against the previous run, not the hash of the bytes.

This matters here: every page on this source ships a weather widget and a
per-request ASP.NET verification token, so the raw bytes differ on every fetch of
every page. Comparing raw hashes would report all 643 pages as changed on every
run. Pages whose bytes differ while their content does not are counted as
`chrome_only_differences` and their archived snapshot is left alone.

When a page's content does change, the bytes being replaced move to
`raw/_superseded/{id}/{timestamp}.html` before the new ones are written, and the
run record names the fields that differ and their before and after values.

A run that finds nothing still writes a record. "No page changed since the
previous run" is an observation about the source, not an empty state.

Run records also carry new pages, pages that were archived and now return 404,
errors, and the list of fields compared.

## What this establishes, and what it does not

**It establishes** what each archived page displayed at the timestamp recorded
for it. The raw HTML is unmodified, each extracted row carries the SHA-256 of the
file it came from, and each snapshot's first-seen time is recorded:

```bash
shasum -a 256 raw/5637.html      # compare against raw_sha256 in data/ma-hearings.json
```

That ties a row to the bytes in this repository. It is not a third-party
attestation that those bytes came from the Commonwealth; for that, pair this
archive with an independent capture such as a Wayback Machine snapshot.

**It does not establish when anything was posted or announced.** The site does
not publish a posting, noticing, or announcement date for these events, and this
archive contains none. Nothing here supports a claim about notice timing or
notice compliance, and no such value is derived from event dates or id ordering.

Further limits, stated plainly:

- **Change detection begins at the first run, not at the event.** The archive can
  show that a page differs from the previous run. It cannot show what a page said
  before this beat started watching it.
- **Absence is page absence.** A null means the field was not on the page. It is
  not a statement that the government lacked the information.
- **Linked documents are not captured.** Some pages link agenda or minutes PDFs;
  the archive stores the page, not the files it links to.
- **404s inside the range** are recorded as such. Whether an id was never assigned
  or was withdrawn is not something these responses reveal.
- **The frontier is a fact about a fetch window,** not a permanent ceiling.
