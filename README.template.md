# Massachusetts Legislature Hearing Page Archive

A byte-for-byte archive of `malegislature.gov/Events/Hearings/Detail/{id}` pages,
plus a parsed extract of the fields each page displayed at the moment it was
fetched.

## What is here

| Path | What it is |
| --- | --- |
| `raw/{id}.html` | The page exactly as the server sent it. Never edited, cleaned, or reformatted. |
| `fetch_status.tsv` | One row per id requested: HTTP status, byte count, UTC fetch time. |
| `hearings.json` / `hearings.csv` | Fields extracted from `raw/`, with the SHA-256 of the file each row came from. |
| `index.html` | A self-contained browsable table of the extract. |
| `collect.py` / `parse.py` / `page.py` / `spotcheck.py` | Fetch, extract, render, and cross-check. |

## How it was collected

Ids are dense integers and monotonic with event date. The collector binary-searched
the upper frontier — the largest id still returning 200 — and then walked downward
to id 5000, one request at a time.

- **Frontier found:** {{FRONTIER}}. Ids above it return a clean 404.
- **Range walked:** 5000 to {{FRONTIER}} ({{ATTEMPTED}} ids).
- **Pages archived:** {{SAVED}}. **Ids returning 404:** {{MISSING}} (gaps inside the range; recorded in `fetch_status.tsv`).
- **Fetch window:** {{WINDOW}} UTC.
- **Rate:** strictly sequential, 1.5 s between requests, no parallelism.
- **User-Agent:** `{{UA}}`
- `robots.txt` disallows nothing for this path. Pages are server-rendered, so plain
  `urllib` retrieves the same bytes a browser would; no headless browser was used.

Re-running `collect.py` is safe: an id whose file already exists is skipped, so an
interrupted run resumes where it stopped.

```bash
ARCHIVE_CONTACT="{{CONTACT}}" python3 collect.py   # fetch (resumable)
python3 parse.py                                   # -> hearings.json, hearings.csv
python3 page.py                                    # -> index.html
python3 spotcheck.py                               # cross-check the parser
```

## What the extract contains

The id space serves more than one kind of event. Titles read
`<event type> Details - <name>`, and the name means different things:

{{TYPES}}

For a hearing the name is the **committee**; for a conference committee meeting it
is the **bill subject**, and no committee is named on the page. These land in
separate columns rather than a single one, so the data never asserts a committee
that a page did not name.

Fields taken from the page: `status`, `event_date`, `start_time`, `location`
(from `<dt>`/`<dd>` pairs) and bill references (from `/Bills/{court}/{number}`
links). A field that is absent from a page is null, and every null is counted in
the report `parse.py` prints — nothing is inferred or filled in.

### Verification

`spotcheck.py` re-extracts every field with a second, structurally different
reader (`html.parser`'s tokenizer instead of regexes) on {{SAMPLE}} pages spread
across the id range and diffs the two. Result: {{SPOTCHECK}}

## What this establishes, and what it does not

**It establishes** what each archived page displayed at the timestamp recorded for
it in `fetch_status.tsv`. The raw HTML is unmodified and each parsed row carries
the SHA-256 of the file it was derived from, so any extract can be checked against
the bytes it came from.

**It does not establish when anything was posted or announced.** The site does not
publish a posting, noticing, or announcement date for these events, and this
archive therefore contains none. No column here should be read as evidence about
notice timing or notice compliance — the data needed for that claim is not present,
and it cannot be recovered by inference from event dates or id ordering.

Further limits worth stating plainly:

- **A single observation per page.** Each page was fetched once. If a page changed
  before or after that moment, this archive cannot show it. Values such as `status`
  are as of the fetch, not final.
- **Absence is page absence.** A null means the field was not on the page. It is
  not a statement that the Legislature lacked the information.
- **Linked documents were not captured.** Some pages link agenda or minutes PDFs;
  the archive stores the page, not the files it links to.
- **404s inside the range** are recorded as such. Whether an id never existed or was
  withdrawn is not something these pages reveal.
- **Ids above {{FRONTIER}}** were not yet live at the fetch window; the frontier is a
  fact about that moment, not a permanent ceiling.
