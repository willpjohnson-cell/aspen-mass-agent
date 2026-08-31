# Aspen

A platform for hosting monitors that watch state and local governments.

A monitor watches one source. It archives the pages it watches byte for byte,
extracts a small set of fields from them, and records what changed between runs.
The platform supplies everything that is not specific to a government; a monitor
supplies the two files that are.

**Monitors running: 1** — `ma-hearings`, watching Massachusetts Legislature
committee hearing and conference committee meeting pages.

## Layout

```
runner.py                       source-agnostic: fetch, archive, hash, timestamp, diff
render.py                       renders index.html from monitors/, runs/ and data/
monitors/
  ma-hearings/
    monitor.yaml                what to fetch, how politely, how to present it
    parse.py                    the only Massachusetts-specific code
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
python3 runner.py run ma-hearings        # a monitoring pass; writes runs/{timestamp}.json
python3 runner.py extract ma-hearings    # archived pages -> data/ma-hearings.{json,csv}
python3 runner.py check ma-hearings      # cross-check the parser against a second reader
python3 runner.py runs ma-hearings       # run history
python3 runner.py monitors               # installed monitors
python3 render.py                        # rebuild index.html
```

`ARCHIVE_CONTACT` is substituted into the monitor's User-Agent. The runner
refuses to send an anonymous one.

## How a monitor is defined

Two files. Nothing else.

### `monitor.yaml`

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
| `presentation.*` | filter placeholder, hidden columns, a summary stat, and the monitor's scope disclosure |
| `schedule`, `title`, `jurisdiction`, `description` | shown on the page |

The scope disclosure lives in the monitor's config rather than in the renderer:
only the monitor knows what its source does and does not publish, so a new
jurisdiction states its own limits instead of inheriting Massachusetts'.

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
mkdir -p monitors/<name>
$EDITOR monitors/<name>/monitor.yaml     # copy ma-hearings' and edit
$EDITOR monitors/<name>/parse.py         # parse(html) -> dict
ARCHIVE_CONTACT="…" python3 runner.py collect <name>
python3 runner.py check <name> && python3 runner.py extract <name>
python3 render.py
```

The runner has no per-monitor branches; it lists whatever is in `monitors/` and
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
  before this monitor started watching it.
- **Absence is page absence.** A null means the field was not on the page. It is
  not a statement that the government lacked the information.
- **Linked documents are not captured.** Some pages link agenda or minutes PDFs;
  the archive stores the page, not the files it links to.
- **404s inside the range** are recorded as such. Whether an id was never assigned
  or was withdrawn is not something these responses reveal.
- **The frontier is a fact about a fetch window,** not a permanent ceiling.
