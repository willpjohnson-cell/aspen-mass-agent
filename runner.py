#!/usr/bin/env python3
"""Source-agnostic beat runner.

Fetch, archive, hash, timestamp, diff. Nothing in this file knows about any
particular government. A beat is one government surface being watched: a directory under beats/ holding

  beat.yaml      what to fetch, how politely, and how to present it
  parse.py       one function, parse(html) -> dict, plus an optional
                 crosscheck(html) -> dict used by the check command

Commands:
  python3 runner.py collect <beat>   fill the archive (resumable)
  python3 runner.py run <beat>       a pass over the beat: re-check every page,
                                        pick up new ones, record what changed
  python3 runner.py extract <beat>   archived pages -> json + csv
  python3 runner.py check <beat>     cross-check the parser against itself
  python3 runner.py seed-run <beat>  reconstruct the first run record from
                                        the request log of the initial collection
  python3 runner.py runs <beat>      show run history
  python3 runner.py snapshots <beat> rebuild the archived-bytes ledger
  python3 runner.py changes <beat>   every change ever detected
  python3 runner.py first-seen <beat>  record when each archived page was first seen
  python3 runner.py backfill <beat>  add provenance to older change records
  python3 runner.py beats               list installed beats

A run is recorded whether or not anything moved. A pass that finds no changes
is a result about the source, not an empty state, and is written out as such.
"""
import csv
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BEATS = ROOT / "beats"
RUNS = ROOT / "runs"


# --- a small YAML subset -------------------------------------------------
# Supported: comments, nested maps by indentation, lists of scalars, lists of
# maps, inline [a, b] lists, folded '>' block scalars, and the scalar types
# below. Anything outside that raises rather than guessing.

SCALARS = {"true": True, "false": False, "yes": True, "no": False,
           "null": None, "~": None, "": None}


def _scalar(raw):
    text = raw.strip()
    if text[:1] in ("'", '"') and text[-1:] == text[:1] and len(text) > 1:
        return text[1:-1]
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        return [_scalar(x) for x in inner.split(",")] if inner else []
    low = text.lower()
    if low in SCALARS:
        return SCALARS[low]
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    return text


def _strip_comment(line):
    """Drop a trailing comment, ignoring '#' inside quotes."""
    out, quote = [], None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _lines(text):
    for n, raw in enumerate(text.splitlines(), 1):
        line = _strip_comment(raw)
        if line.strip():
            yield n, len(line) - len(line.lstrip()), line.strip()


def load_yaml(path):
    items = list(_lines(Path(path).read_text(encoding="utf-8")))

    def block(start, indent):
        """Parse items[start:] at the given indent. Returns (value, next)."""
        i = start
        if i < len(items) and items[i][2].startswith("- "):
            seq = []
            while i < len(items) and items[i][1] == indent and items[i][2].startswith("- "):
                head = items[i][2][2:].strip()
                if ":" in head and not head.startswith(("'", '"')):
                    key, _, rest = head.partition(":")
                    entry = {}
                    if rest.strip():
                        entry[key.strip()] = _scalar(rest)
                    i += 1
                    while i < len(items) and items[i][1] > indent and not items[i][2].startswith("- "):
                        sub, i = block(i, items[i][1])
                        entry.update(sub)
                    seq.append(entry)
                else:
                    seq.append(_scalar(head))
                    i += 1
            return seq, i
        mapping = {}
        while i < len(items) and items[i][1] == indent:
            _, _, line = items[i]
            if line.startswith("- "):
                break
            key, sep, rest = line.partition(":")
            if not sep:
                raise ValueError(f"{path}:{items[i][0]}: expected 'key: value'")
            key, rest = key.strip(), rest.strip()
            i += 1
            if rest in (">", "|"):
                folded, parts = rest == ">", []
                while i < len(items) and items[i][1] > indent:
                    parts.append(items[i][2])
                    i += 1
                mapping[key] = (" ".join(parts) if folded else "\n".join(parts))
            elif rest:
                mapping[key] = _scalar(rest)
            elif i < len(items) and items[i][1] > indent:
                mapping[key], i = block(i, items[i][1])
            else:
                mapping[key] = None
        return mapping, i

    value, end = block(0, items[0][1] if items else 0)
    if end != len(items):
        raise ValueError(f"{path}:{items[end][0]}: unexpected indentation")
    return value


# --- beats ------------------------------------------------------------

class Beat:
    """A beat's configuration and its parser, loaded from disk."""

    def __init__(self, name):
        self.name = name
        self.dir = BEATS / name
        if not self.dir.is_dir():
            sys.exit(f"no beat named {name!r} in {BEATS}")
        self.config = load_yaml(self.dir / "beat.yaml")
        self.parser = self._load_parser()

    def _load_parser(self):
        path = self.dir / "parse.py"
        if not path.exists():
            sys.exit(f"beat {self.name} has no parse.py")
        spec = importlib.util.spec_from_file_location(f"beats.{self.name}.parse", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not hasattr(module, "parse"):
            sys.exit(f"beat {self.name}: parse.py defines no parse(html) function")
        return module

    def get(self, *path, default=None):
        node = self.config
        for key in path:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node if node is not None else default

    def path(self, *path, default=None):
        value = self.get(*path, default=default)
        return ROOT / value if value else None

    @property
    def archive(self):
        return self.path("storage", "archive_dir", default="raw")

    @property
    def request_log(self):
        return self.path("storage", "request_log", default=f"{self.name}-requests.tsv")

    @property
    def data_dir(self):
        return self.path("storage", "data_dir", default="data")

    @property
    def first_seen_log(self):
        return (self.path("storage", "first_seen_log")
                or self.data_dir / f"{self.name}-first-seen.tsv")

    @property
    def superseded(self):
        return self.path("storage", "superseded_dir",
                         default=f"{self.get('storage', 'archive_dir', default='raw')}/_superseded")

    @property
    def delay(self):
        return float(self.get("politeness", "delay_seconds", default=1.5))

    @property
    def fields(self):
        return self.get("fields", default=[])

    def url(self, page_id):
        pattern = self.get("source", "url_pattern")
        if not pattern:
            sys.exit(f"beat {self.name}: source.url_pattern is not set")
        return pattern.replace("{id}", str(page_id))

    def user_agent(self):
        template = self.get("politeness", "user_agent", default="")
        contact = os.environ.get("ARCHIVE_CONTACT", "").strip()
        if "{contact}" in template and not contact:
            sys.exit("ARCHIVE_CONTACT is not set; refusing to send an anonymous User-Agent.")
        return template.replace("{contact}", contact)

    def archived_ids(self):
        return sorted(int(p.stem) for p in self.archive.glob("*.html") if p.stem.isdigit())


def available():
    return sorted(p.name for p in BEATS.iterdir() if (p / "beat.yaml").exists())


# --- fetching ------------------------------------------------------------

def log(msg):
    print(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}", flush=True)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class Fetcher:
    """Sequential, polite, byte-preserving retrieval for one beat."""

    def __init__(self, beat):
        self.m = beat
        self.ua = beat.user_agent()
        self.delay = beat.delay
        if beat.get("politeness", "parallel", default=False):
            sys.exit("politeness.parallel is not supported; runs are sequential by design")
        beat.archive.mkdir(parents=True, exist_ok=True)

    def record(self, page_id, status, nbytes):
        path = self.m.request_log
        new = not path.exists()
        with path.open("a", encoding="utf-8") as fh:
            if new:
                fh.write("id\thttp_status\tbytes\tfetched_at_utc\n")
            fh.write(f"{page_id}\t{status}\t{nbytes}\t{now()}\n")

    def fetch(self, page_id, attempts=3):
        """Return (status, raw bytes). Bytes are exactly what the server sent."""
        url = self.m.url(page_id)
        for attempt in range(1, attempts + 1):
            req = urllib.request.Request(url, headers={"User-Agent": self.ua})
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return resp.status, resp.read()
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return 404, b""
                if exc.code in (429, 500, 502, 503, 504) and attempt < attempts:
                    wait = self.delay * 4 * attempt
                    log(f"  {page_id}: HTTP {exc.code}, retry in {wait:.0f}s")
                    time.sleep(wait)
                    continue
                return exc.code, b""
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt < attempts:
                    wait = self.delay * 4 * attempt
                    log(f"  {page_id}: {exc.__class__.__name__}, retry in {wait:.0f}s")
                    time.sleep(wait)
                    continue
                return -1, b""
        return -1, b""

    def save(self, page_id, body):
        dest = self.m.archive / f"{page_id}.html"
        tmp = dest.with_suffix(".html.part")
        tmp.write_bytes(body)
        tmp.replace(dest)

    def probe(self, page_id):
        """Retrieve without archiving. The caller decides what to keep."""
        status, body = self.fetch(page_id)
        self.record(page_id, status, len(body))
        time.sleep(self.delay)
        return status, body

    def get(self, page_id, refetch=False):
        """Fetch one id and archive it. Without refetch, an archived id is left alone."""
        dest = self.m.archive / f"{page_id}.html"
        if dest.exists() and dest.stat().st_size > 0 and not refetch:
            return 200, None
        status, body = self.probe(page_id)
        if status == 200 and body:
            self.save(page_id, body)
        return status, body


def find_frontier(fetcher):
    """Highest id that exists, per the beat's discovery strategy."""
    m = fetcher.m
    kind = m.get("discovery", "kind", default="integer-ids")
    if kind != "integer-ids":
        sys.exit(f"discovery.kind {kind!r} is not implemented; "
                 f"add the strategy to runner.py rather than forking it")
    lo = int(m.get("discovery", "anchor"))
    hi = int(m.get("discovery", "probe"))
    if fetcher.get(lo)[0] != 200:
        sys.exit(f"anchor id {lo} did not return 200; check the source before continuing")
    while fetcher.get(hi)[0] == 200:
        log(f"frontier probe: {hi} exists, widening")
        lo, hi = hi, hi + (hi - lo)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        lo, hi = (mid, hi) if fetcher.get(mid)[0] == 200 else (lo, mid)
    log(f"frontier bracketed at {lo}; confirming with a contiguous scan")
    return confirm_frontier(fetcher, lo)


def confirm_frontier(fetcher, frontier):
    """A single 404 is not the end of a sparse id space; require a clear run."""
    need = int(fetcher.m.get("discovery", "clear_run", default=40))
    highest, run, page_id = frontier, 0, frontier + 1
    while run < need:
        status, _ = fetcher.get(page_id)
        if status == 200:
            log(f"  {page_id}: exists above the bracketed frontier")
            highest, run = page_id, 0
        elif status == 404:
            run += 1
        else:
            run = 0
        page_id += 1
    log(f"frontier confirmed at {highest} ({need} consecutive absences above it)")
    return highest


# --- extract -------------------------------------------------------------

def fetch_times(beat):
    """When the archived bytes were observed — from the snapshot ledger when it
    exists, since the request log's newest row may describe a re-fetch that was
    not archived."""
    snaps = load_snapshots(beat)
    if snaps:
        return {i: r["first_seen_utc"] for i, r in snaps.items() if r["first_seen_utc"]}
    times = {}
    path = beat.request_log
    if path and path.exists():
        with path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                if row.get("http_status") == "200":
                    times[int(row["id"])] = row["fetched_at_utc"]
    return times


def build_record(beat, page_id, raw_bytes, times=None):
    """Generic envelope around whatever the beat's parser returns."""
    doc = raw_bytes.decode("utf-8", errors="replace")
    rec = {"id": page_id, "source_url": beat.url(page_id)}
    rec.update(beat.parser.parse(doc))
    rec["raw_sha256"] = sha256(raw_bytes)
    rec["raw_bytes"] = len(raw_bytes)
    rec["fetched_at_utc"] = (times or {}).get(page_id)
    return rec


def extract(beat):
    ids = beat.archived_ids()
    if not ids:
        sys.exit(f"no archived pages in {beat.archive}")
    times = fetch_times(beat)
    records = [build_record(beat, i, (beat.archive / f"{i}.html").read_bytes(), times)
               for i in ids]

    beat.data_dir.mkdir(parents=True, exist_ok=True)
    json_out = beat.data_dir / f"{beat.name}.json"
    csv_out = beat.data_dir / f"{beat.name}.csv"
    json_out.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")

    keys = [f["key"] for f in beat.fields]
    with csv_out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id"] + keys + ["source_url", "fetched_at_utc", "raw_sha256"])
        for r in records:
            row = [r["id"]]
            for key in keys:
                value = r.get(key)
                row.append(";".join(str(v) for v in value) if isinstance(value, list)
                           else ("" if value is None else value))
            w.writerow(row + [r["source_url"], r["fetched_at_utc"] or "", r["raw_sha256"]])

    report(beat, records)
    print(f"\nextracted {len(records)} pages -> {json_out.relative_to(ROOT)}, "
          f"{csv_out.relative_to(ROOT)}")
    return records


def report(beat, records):
    """Count absent fields and say so; never let a null pass silently."""
    total = len(records)
    group_key = beat.get("report_group_by")
    groups = Counter(str(r.get(group_key)) for r in records) if group_key else Counter()
    absent, per_group = Counter(), Counter()
    for r in records:
        g = str(r.get(group_key)) if group_key else ""
        for f in beat.fields:
            value = r.get(f["key"])
            if value is None or value == [] or value == "":
                absent[f["key"]] += 1
                per_group[(g, f["key"])] += 1

    if groups:
        print(f"pages by {group_key}:")
        for name, n in groups.most_common():
            print(f"  {name:<32} {n:>4}")
    print("\nfields absent from the page (never inferred, never filled in):")
    for f in beat.fields:
        n = absent[f["key"]]
        detail = ", ".join(f"{g}: {per_group[(g, f['key'])]}/{groups[g]}"
                           for g, _ in groups.most_common() if per_group[(g, f["key"])])
        print(f"  {f['key']:<14} {n:>4} / {total}  ({100.0 * n / total if total else 0:.1f}%)"
              + (f"   [{detail}]" if detail else ""))


# --- check ---------------------------------------------------------------

def check(beat, sample_size=20):
    """Diff parse() against the beat's second reader on a spread of pages."""
    if not hasattr(beat.parser, "crosscheck"):
        sys.exit(f"beat {beat.name}: parse.py defines no crosscheck(html) function")
    ids = beat.archived_ids()
    if not ids:
        sys.exit(f"no archived pages in {beat.archive}")
    step = max(1, len(ids) // sample_size)
    sample = ids[::step][:sample_size]
    if ids[-1] not in sample:
        sample[-1] = ids[-1]

    print(f"archive holds {len(ids)} pages, ids {ids[0]}-{ids[-1]}")
    print(f"cross-checking {len(sample)}: {sample}\n")
    mismatched, absent = Counter(), Counter()
    bad = []
    for page_id in sample:
        doc = (beat.archive / f"{page_id}.html").read_bytes().decode("utf-8", errors="replace")
        got, ref = beat.parser.parse(doc), beat.parser.crosscheck(doc)
        diffs = [f"{k}: parse={got.get(k)!r} crosscheck={ref.get(k)!r}"
                 for k in sorted(set(got) | set(ref)) if got.get(k) != ref.get(k)]
        for k in set(got) | set(ref):
            if got.get(k) != ref.get(k):
                mismatched[k] += 1
            elif got.get(k) in (None, [], ""):
                absent[k] += 1
        print(f"  {page_id}  {'MISMATCH' if diffs else 'ok'}")
        for d in diffs:
            print(f"           {d}")
        if diffs:
            bad.append(page_id)
    print(f"\nover {len(sample)} sampled pages:")
    for f in beat.fields:
        k = f["key"]
        print(f"  {k:<14} mismatches {mismatched[k]:>2}   absent on page (both agree) {absent[k]:>2}")
    print("\n" + (f"pages needing attention: {bad}" if bad else
                  "no disagreements: both readers read every sampled page identically"))
    return bad


# --- when a page was first observed to exist -----------------------------
#
# This is the primitive every notice rule depends on, so it is written once per
# page and never recomputed. It carries its own confidence, because the same
# timestamp means two different things:
#
#   bounded    the id returned 404 in an earlier run and 200 in this one, so the
#              page became observable inside a known window. Real evidence.
#   unbounded  the page was already there the first time anything looked. It
#              existed at some unknown earlier time. Not evidence of posting.

FIRST_SEEN_COLUMNS = ["id", "first_seen_utc", "first_seen_confidence",
                      "observed_in_run", "window_start_utc"]


def load_first_seen(beat):
    path = beat.first_seen_log
    out = {}
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                out[int(row["id"])] = row
    return out


def save_first_seen(beat, ledger):
    path = beat.first_seen_log
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(FIRST_SEEN_COLUMNS)
        for page_id in sorted(ledger):
            row = ledger[page_id]
            w.writerow([page_id] + [row.get(c, "") for c in FIRST_SEEN_COLUMNS[1:]])


def request_history(beat):
    """Every request ever made, per id, in order. The evidence for boundedness."""
    history = {}
    if beat.request_log.exists():
        with beat.request_log.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                history.setdefault(int(row["id"]), []).append(
                    (row["fetched_at_utc"], row["http_status"]))
    for entries in history.values():
        entries.sort()
    return history


def classify_first_seen(history, page_id, observed_utc):
    """Was this page absent when something looked earlier?

    Returns (confidence, window_start). A 404 recorded for this id before the
    observation bounds the window; anything else leaves it unbounded.
    """
    absences = [t for t, status in history.get(page_id, [])
                if status == "404" and t < observed_utc]
    if absences:
        return "bounded", absences[-1]
    return "unbounded", ""


def seed_first_seen(beat):
    """Record the pages already archived. All of them are unbounded.

    Nothing looked before the initial collection, so no page in it can be shown
    to have appeared in a window. Existing entries are never overwritten.
    """
    ledger = load_first_seen(beat)
    history = request_history(beat)
    runs = load_runs(beat.name)
    first_run = runs[0]["run_id"] if runs else ""
    added = 0
    for page_id in beat.archived_ids():
        if page_id in ledger:
            continue
        seen = [t for t, status in history.get(page_id, []) if status == "200"]
        if not seen:
            continue
        confidence, window = classify_first_seen(history, page_id, seen[0])
        ledger[page_id] = {"first_seen_utc": seen[0],
                           "first_seen_confidence": confidence,
                           "observed_in_run": first_run,
                           "window_start_utc": window}
        added += 1
    save_first_seen(beat, ledger)
    counts = Counter(r["first_seen_confidence"] for r in ledger.values())
    print(f"{beat.first_seen_log.relative_to(ROOT)}: {added} added, "
          f"{len(ledger)} pages total ({dict(counts)})")
    return ledger


# --- runs and change detection -------------------------------------------

def content_hash(beat, raw_bytes):
    """Hash of what the parser reads, not of the bytes.

    Many sites carry markup that changes on every request without the page
    saying anything different: a clock, a rotating widget, a per-request form
    token. Comparing raw bytes would report every such page as changed on every
    run. Hashing the parsed fields compares what the page says instead.
    """
    parsed = beat.parser.parse(raw_bytes.decode("utf-8", errors="replace"))
    return sha256(json.dumps(parsed, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def snapshot_path(beat):
    return (beat.path("storage", "snapshot_log")
            or beat.data_dir / f"{beat.name}-snapshots.tsv")


def load_snapshots(beat):
    """id -> {raw_sha256, content_sha256, first_seen_utc} for the archived bytes."""
    path = snapshot_path(beat)
    out = {}
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                out[int(row["id"])] = row
    return out


def save_snapshots(beat, snaps):
    path = snapshot_path(beat)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["id", "raw_sha256", "content_sha256", "first_seen_utc"])
        for page_id in sorted(snaps):
            r = snaps[page_id]
            w.writerow([page_id, r["raw_sha256"], r["content_sha256"], r["first_seen_utc"]])


def seed_snapshots(beat):
    """Build the ledger from the archive, dating each page by its first 200."""
    first = {}
    log_path = beat.request_log
    if log_path.exists():
        with log_path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                if row["http_status"] == "200":
                    page_id = int(row["id"])
                    stamp = row["fetched_at_utc"]
                    if page_id not in first or stamp < first[page_id]:
                        first[page_id] = stamp
    snaps = {}
    for page_id in beat.archived_ids():
        raw = (beat.archive / f"{page_id}.html").read_bytes()
        snaps[page_id] = {
            "raw_sha256": sha256(raw),
            "content_sha256": content_hash(beat, raw),
            "first_seen_utc": first.get(page_id, ""),
        }
    save_snapshots(beat, snaps)
    print(f"wrote {snapshot_path(beat).relative_to(ROOT)} for {len(snaps)} archived pages")
    return snaps

def field_diff(beat, before_bytes, after_bytes):
    """Which of the beat's diff_fields changed between two snapshots."""
    keys = beat.get("diff_fields") or [f["key"] for f in beat.fields]
    old = beat.parser.parse(before_bytes.decode("utf-8", errors="replace"))
    new = beat.parser.parse(after_bytes.decode("utf-8", errors="replace"))
    changes = []
    for key in keys:
        if old.get(key) != new.get(key):
            changes.append({"field": key, "before": old.get(key), "after": new.get(key)})
    return changes


def supersede(beat, page_id, old_bytes, stamp):
    """Keep the bytes we are about to replace. The archive never loses a version."""
    folder = beat.superseded / str(page_id)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{stamp.replace(':', '').replace('-', '')}.html"
    dest.write_bytes(old_bytes)
    return str(dest.relative_to(ROOT))


def write_run(beat, record):
    RUNS.mkdir(exist_ok=True)
    path = RUNS / f"{record['run_id']}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return path


def run(beat):
    """One pass over the beat's whole id space, recording what moved."""
    fetcher = Fetcher(beat)
    snaps = load_snapshots(beat) or seed_snapshots(beat)
    first_seen = load_first_seen(beat)
    history = request_history(beat)
    started = now()
    log(f"beat {beat.name}; run started {started}")
    frontier = find_frontier(fetcher)
    floor = int(beat.get("discovery", "floor"))

    checked = 0
    new_pages, changed, removed, errors = [], [], [], []
    unchanged = absent = chrome_only = 0

    for page_id in range(frontier, floor - 1, -1):
        dest = beat.archive / f"{page_id}.html"
        known = dest.exists() and dest.stat().st_size > 0
        status, body = fetcher.probe(page_id)
        checked += 1

        if status == 200 and body:
            new_content = content_hash(beat, body)
            if not known:
                observed = now()
                fetcher.save(page_id, body)
                snaps[page_id] = {"raw_sha256": sha256(body),
                                  "content_sha256": new_content,
                                  "first_seen_utc": observed}
                if page_id not in first_seen:
                    confidence, window = classify_first_seen(history, page_id, observed)
                    first_seen[page_id] = {
                        "first_seen_utc": observed,
                        "first_seen_confidence": confidence,
                        "observed_in_run": started.replace(":", "").replace("-", ""),
                        "window_start_utc": window,
                    }
                    log(f"  {page_id}: new page archived, first seen {confidence}")
                new_pages.append(page_id)
                continue
            before = dest.read_bytes()
            prior = snaps.get(page_id, {})
            old_content = prior.get("content_sha256") or content_hash(beat, before)
            if new_content != old_content:
                stamp = now()
                observed_before = (snaps.get(page_id) or {}).get("first_seen_utc") or None
                kept = supersede(beat, page_id, before, stamp)
                fetcher.save(page_id, body)
                fields = field_diff(beat, before, body)
                snaps[page_id] = {"raw_sha256": sha256(body),
                                  "content_sha256": new_content,
                                  "first_seen_utc": stamp}
                changed.append({
                    "id": page_id,
                    "url": beat.url(page_id),
                    "observed_before_utc": observed_before,
                    "observed_after_utc": stamp,
                    "content_sha256_before": old_content,
                    "content_sha256_after": new_content,
                    "raw_sha256_before": sha256(before),
                    "raw_sha256_after": sha256(body),
                    "previous_snapshot": kept,
                    "current_snapshot": str((beat.archive / f"{page_id}.html").relative_to(ROOT)),
                    "fields_changed": fields,
                })
                log(f"  {page_id}: CHANGED — {', '.join(f['field'] for f in fields) or 'no diffed field'}")
            elif sha256(body) != sha256(before):
                # Same content, different bytes: per-request markup only. The
                # archived snapshot is left alone rather than churning the
                # archive with re-fetches that say nothing new.
                chrome_only += 1
            else:
                unchanged += 1
        elif status == 404:
            absent += 1
            if known:
                removed.append(page_id)
                log(f"  {page_id}: was archived, now returns 404")
        else:
            errors.append({"id": page_id, "status": status})

        done = frontier - page_id + 1
        if done % 100 == 0:
            log(f"progress {done}/{frontier - floor + 1} at id {page_id}; "
                f"{len(changed)} changed, {len(new_pages)} new, {chrome_only} chrome-only")

    save_snapshots(beat, snaps)
    save_first_seen(beat, first_seen)
    record = {
        "run_id": started.replace(":", "").replace("-", ""),
        "beat": beat.name,
        "kind": "recheck",
        "started_utc": started,
        "finished_utc": now(),
        "frontier": frontier,
        "id_range": [floor, frontier],
        "pages_checked": checked,
        "pages_archived_after_run": len(beat.archived_ids()),
        "new_pages": new_pages,
        "first_seen_recorded": [
            {"id": i, "first_seen_utc": first_seen[i]["first_seen_utc"],
             "first_seen_confidence": first_seen[i]["first_seen_confidence"],
             "window_start_utc": first_seen[i]["window_start_utc"]}
            for i in new_pages if i in first_seen],
        "changed_pages": changed,
        "removed_pages": removed,
        "unchanged_pages": unchanged,
        "chrome_only_differences": chrome_only,
        "ids_absent": absent,
        "errors": errors,
        "compared_fields": beat.get("diff_fields") or [f["key"] for f in beat.fields],
        "change_detection": (
            "A page counts as changed when the hash of its parsed fields differs from the "
            "previous run. Pages whose bytes differ while their parsed fields are identical "
            "are counted under chrome_only_differences and are not treated as changes; the "
            "bytes already archived for them are left in place."),
    }
    record["summary"] = (
        f"{checked} ids checked, {len(new_pages)} new, {len(changed)} changed, "
        f"{len(removed)} removed, {len(errors)} errors"
        if (new_pages or changed or removed or errors) else
        f"{checked} ids checked; no page changed since the previous run")
    path = write_run(beat, record)
    log(f"run recorded: {path.relative_to(ROOT)} — {record['summary']}")
    return record


def seed_run(beat):
    """Reconstruct the initial collection as a run record, from the request log.

    Marked reconstructed: it is assembled from the request log written during
    the first collection, not observed by a run of this code.
    """
    path = beat.request_log
    if not path.exists():
        sys.exit(f"no request log at {path}")
    rows = list(csv.DictReader(path.open(encoding="utf-8"), delimiter="\t"))
    ok = [r for r in rows if r["http_status"] == "200"]
    missing = [r for r in rows if r["http_status"] == "404"]
    stamps = sorted(r["fetched_at_utc"] for r in rows)
    ids = sorted({int(r["id"]) for r in ok})
    record = {
        "run_id": stamps[0].replace(":", "").replace("-", ""),
        "beat": beat.name,
        "kind": "initial-collection",
        "reconstructed": True,
        "reconstructed_from": str(path.relative_to(ROOT)),
        "started_utc": stamps[0],
        "finished_utc": stamps[-1],
        "frontier": max(ids),
        "id_range": [int(beat.get("discovery", "floor")), max(ids)],
        "pages_checked": len({int(r["id"]) for r in rows}),
        "pages_archived_after_run": len(ids),
        "new_pages": ids,
        "changed_pages": [],
        "removed_pages": [],
        "unchanged_pages": 0,
        "ids_absent": len({int(r["id"]) for r in missing}),
        "errors": [],
        "summary": (f"initial collection: {len(ids)} pages archived, "
                    f"{len({int(r['id']) for r in missing})} ids absent"),
        "note": ("Assembled from the request log, which covers the initial walk and the "
                 "contiguous scan run above the frontier to confirm it, so the id count "
                 "is larger than the walked range alone."),
    }
    p = write_run(beat, record)
    print(f"wrote {p.relative_to(ROOT)} — {record['summary']}")
    return record


def all_changes(beat_name=None):
    """Every change ever detected, newest first, each tagged with its run."""
    out = []
    for record in load_runs(beat_name):
        for change in record.get("changed_pages", []):
            entry = dict(change)
            entry["run_id"] = record["run_id"]
            entry["beat"] = record["beat"]
            entry["detected_in_run_started_utc"] = record["started_utc"]
            out.append(entry)
    out.sort(key=lambda c: (c.get("observed_after_utc") or c["detected_in_run_started_utc"],
                            c["id"]), reverse=True)
    return out


def backfill_changes(beat):
    """Add provenance to change records written before the runner stored it.

    Timestamps and hashes are read from the retained snapshot, the request log
    and the snapshot ledger. Where the replaced bytes were not retained, the
    record says so; nothing is reconstructed from what a page says now.
    """
    first_seen = {}
    if beat.request_log.exists():
        with beat.request_log.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                if row["http_status"] == "200":
                    page_id, stamp = int(row["id"]), row["fetched_at_utc"]
                    if page_id not in first_seen or stamp < first_seen[page_id]:
                        first_seen[page_id] = stamp
    snaps = load_snapshots(beat)

    touched = 0
    for path in sorted(RUNS.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("beat") != beat.name or not record.get("changed_pages"):
            continue
        dirty = False
        for change in record["changed_pages"]:
            if change.get("observed_after_utc"):
                continue
            page_id = change["id"]
            change.setdefault("url", beat.url(page_id))
            change["current_snapshot"] = str(
                (beat.archive / f"{page_id}.html").relative_to(ROOT))

            prev = change.get("previous_snapshot")
            prev_path = ROOT / prev if prev else None
            if prev_path and prev_path.exists():
                old_bytes = prev_path.read_bytes()
                change["previous_snapshot_verified"] = (
                    sha256(old_bytes) == change.get("raw_sha256_before"))
                change["observed_before_utc"] = first_seen.get(page_id)
                # Re-derive the field diff from the two retained snapshots.
                current = (beat.archive / f"{page_id}.html")
                if current.exists() and sha256(current.read_bytes()) == change.get("raw_sha256_after"):
                    change["fields_changed"] = field_diff(beat, old_bytes, current.read_bytes())
            else:
                change["previous_snapshot"] = None
                change["previous_snapshot_verified"] = False
                change["observed_before_utc"] = None
                change["provenance_note"] = (
                    "The replaced bytes were not retained for this page, so the previous "
                    "values recorded here cannot be checked against a stored snapshot.")

            ledger = snaps.get(page_id)
            if ledger and ledger.get("raw_sha256") == change.get("raw_sha256_after"):
                change["observed_after_utc"] = ledger["first_seen_utc"]
            elif prev:
                change["observed_after_utc"] = None
                change["provenance_note"] = (
                    change.get("provenance_note", "") + " The page has changed again since "
                    "this record was written, so the time these bytes were fetched is not "
                    "recoverable from the ledger.").strip()
            dirty = True
            touched += 1
        if dirty:
            path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            print(f"updated {path.relative_to(ROOT)}")
    print(f"backfilled {touched} change record{'s' if touched != 1 else ''}")


def show_changes(beat):
    changes = all_changes(beat.name)
    if not changes:
        print("no changes detected in any recorded run")
        return
    for c in changes:
        fields = ", ".join(f["field"] for f in c["fields_changed"]) or "no compared field"
        verified = "verified" if c.get("previous_snapshot_verified") else "UNVERIFIED"
        print(f"{c.get('observed_after_utc') or c['detected_in_run_started_utc']}  "
              f"id {c['id']}  {fields}  [{verified}]")
        for f in c["fields_changed"]:
            print(f"    {f['field']}: {f['before']!r} -> {f['after']!r}")


def load_runs(beat=None):
    if not RUNS.exists():
        return []
    out = []
    for p in sorted(RUNS.glob("*.json")):
        rec = json.loads(p.read_text(encoding="utf-8"))
        if beat is None or rec.get("beat") == beat:
            out.append(rec)
    out.sort(key=lambda r: r["started_utc"])
    return out


def show_runs(beat):
    runs = load_runs(beat.name)
    if not runs:
        print("no runs recorded yet")
        return
    print(f"{'started (UTC)':<27}{'kind':<20}{'checked':>8}{'new':>6}{'changed':>9}")
    for r in runs:
        print(f"{r['started_utc']:<27}{r['kind']:<20}{r['pages_checked']:>8}"
              f"{len(r['new_pages']):>6}{len(r['changed_pages']):>9}")


# --- collect -------------------------------------------------------------

def collect(beat):
    """Fill the archive down to the floor. Archived ids are left untouched."""
    fetcher = Fetcher(beat)
    log(f"beat {beat.name}; user-agent: {fetcher.ua}")
    frontier = find_frontier(fetcher)
    floor = int(beat.get("discovery", "floor"))
    log(f"walking {frontier} down to {floor}")
    counts = Counter()
    for page_id in range(frontier, floor - 1, -1):
        dest = beat.archive / f"{page_id}.html"
        if dest.exists() and dest.stat().st_size > 0:
            counts["skipped"] += 1
            continue
        status, _ = fetcher.get(page_id)
        counts["saved" if status == 200 else "absent" if status == 404 else "error"] += 1
    log(f"done: {dict(counts)}")
    return counts


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    cmd = args[0]
    if cmd == "beats":
        for name in available():
            m = Beat(name)
            print(f"{name:<16} {m.get('title', default='')}")
        return
    if len(args) < 2:
        sys.exit(f"usage: python3 runner.py {cmd} <beat>   (installed: {', '.join(available())})")
    beat = Beat(args[1])
    if cmd == "collect":
        collect(beat)
    elif cmd == "run":
        run(beat)
    elif cmd == "seed-run":
        seed_run(beat)
    elif cmd == "runs":
        show_runs(beat)
    elif cmd == "snapshots":
        seed_snapshots(beat)
    elif cmd == "changes":
        show_changes(beat)
    elif cmd == "first-seen":
        seed_first_seen(beat)
    elif cmd == "backfill":
        backfill_changes(beat)
    elif cmd == "extract":
        extract(beat)
    elif cmd == "check":
        check(beat)
    else:
        sys.exit(f"unknown command {cmd!r}")


if __name__ == "__main__":
    main()
