#!/usr/bin/env python3
"""Source-agnostic monitor runner.

Fetch, archive, hash, timestamp, diff. Nothing in this file knows about any
particular government. A monitor is a directory under monitors/ holding:

  monitor.yaml   what to fetch, how politely, and how to present it
  parse.py       one function, parse(html) -> dict, plus an optional
                 crosscheck(html) -> dict used by the check command

Commands:
  python3 runner.py collect <monitor>   fill the archive (resumable)
  python3 runner.py run <monitor>       a monitoring pass: re-check every page,
                                        pick up new ones, record what changed
  python3 runner.py extract <monitor>   archived pages -> json + csv
  python3 runner.py check <monitor>     cross-check the parser against itself
  python3 runner.py seed-run <monitor>  reconstruct the first run record from
                                        the request log of the initial collection
  python3 runner.py runs <monitor>      show run history
  python3 runner.py monitors            list installed monitors

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
MONITORS = ROOT / "monitors"
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


# --- monitors ------------------------------------------------------------

class Monitor:
    """A monitor's configuration and its parser, loaded from disk."""

    def __init__(self, name):
        self.name = name
        self.dir = MONITORS / name
        if not self.dir.is_dir():
            sys.exit(f"no monitor named {name!r} in {MONITORS}")
        self.config = load_yaml(self.dir / "monitor.yaml")
        self.parser = self._load_parser()

    def _load_parser(self):
        path = self.dir / "parse.py"
        if not path.exists():
            sys.exit(f"monitor {self.name} has no parse.py")
        spec = importlib.util.spec_from_file_location(f"monitors.{self.name}.parse", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not hasattr(module, "parse"):
            sys.exit(f"monitor {self.name}: parse.py defines no parse(html) function")
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
            sys.exit(f"monitor {self.name}: source.url_pattern is not set")
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
    return sorted(p.name for p in MONITORS.iterdir() if (p / "monitor.yaml").exists())


# --- fetching ------------------------------------------------------------

def log(msg):
    print(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}", flush=True)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class Fetcher:
    """Sequential, polite, byte-preserving retrieval for one monitor."""

    def __init__(self, monitor):
        self.m = monitor
        self.ua = monitor.user_agent()
        self.delay = monitor.delay
        if monitor.get("politeness", "parallel", default=False):
            sys.exit("politeness.parallel is not supported; runs are sequential by design")
        monitor.archive.mkdir(parents=True, exist_ok=True)

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

    def get(self, page_id, refetch=False):
        """Fetch one id. Without refetch, an archived id is left alone."""
        dest = self.m.archive / f"{page_id}.html"
        if dest.exists() and dest.stat().st_size > 0 and not refetch:
            return 200, None
        status, body = self.fetch(page_id)
        if status == 200 and body:
            self.save(page_id, body)
        self.record(page_id, status, len(body))
        time.sleep(self.delay)
        return status, body


def find_frontier(fetcher):
    """Highest id that exists, per the monitor's discovery strategy."""
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

def fetch_times(monitor):
    times = {}
    path = monitor.request_log
    if path and path.exists():
        with path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                if row.get("http_status") == "200":
                    times[int(row["id"])] = row["fetched_at_utc"]
    return times


def build_record(monitor, page_id, raw_bytes, times=None):
    """Generic envelope around whatever the monitor's parser returns."""
    doc = raw_bytes.decode("utf-8", errors="replace")
    rec = {"id": page_id, "source_url": monitor.url(page_id)}
    rec.update(monitor.parser.parse(doc))
    rec["raw_sha256"] = sha256(raw_bytes)
    rec["raw_bytes"] = len(raw_bytes)
    rec["fetched_at_utc"] = (times or {}).get(page_id)
    return rec


def extract(monitor):
    ids = monitor.archived_ids()
    if not ids:
        sys.exit(f"no archived pages in {monitor.archive}")
    times = fetch_times(monitor)
    records = [build_record(monitor, i, (monitor.archive / f"{i}.html").read_bytes(), times)
               for i in ids]

    monitor.data_dir.mkdir(parents=True, exist_ok=True)
    json_out = monitor.data_dir / f"{monitor.name}.json"
    csv_out = monitor.data_dir / f"{monitor.name}.csv"
    json_out.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")

    keys = [f["key"] for f in monitor.fields]
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

    report(monitor, records)
    print(f"\nextracted {len(records)} pages -> {json_out.relative_to(ROOT)}, "
          f"{csv_out.relative_to(ROOT)}")
    return records


def report(monitor, records):
    """Count absent fields and say so; never let a null pass silently."""
    total = len(records)
    group_key = monitor.get("report_group_by")
    groups = Counter(str(r.get(group_key)) for r in records) if group_key else Counter()
    absent, per_group = Counter(), Counter()
    for r in records:
        g = str(r.get(group_key)) if group_key else ""
        for f in monitor.fields:
            value = r.get(f["key"])
            if value is None or value == [] or value == "":
                absent[f["key"]] += 1
                per_group[(g, f["key"])] += 1

    if groups:
        print(f"pages by {group_key}:")
        for name, n in groups.most_common():
            print(f"  {name:<32} {n:>4}")
    print("\nfields absent from the page (never inferred, never filled in):")
    for f in monitor.fields:
        n = absent[f["key"]]
        detail = ", ".join(f"{g}: {per_group[(g, f['key'])]}/{groups[g]}"
                           for g, _ in groups.most_common() if per_group[(g, f["key"])])
        print(f"  {f['key']:<14} {n:>4} / {total}  ({100.0 * n / total if total else 0:.1f}%)"
              + (f"   [{detail}]" if detail else ""))


# --- check ---------------------------------------------------------------

def check(monitor, sample_size=20):
    """Diff parse() against the monitor's second reader on a spread of pages."""
    if not hasattr(monitor.parser, "crosscheck"):
        sys.exit(f"monitor {monitor.name}: parse.py defines no crosscheck(html) function")
    ids = monitor.archived_ids()
    if not ids:
        sys.exit(f"no archived pages in {monitor.archive}")
    step = max(1, len(ids) // sample_size)
    sample = ids[::step][:sample_size]
    if ids[-1] not in sample:
        sample[-1] = ids[-1]

    print(f"archive holds {len(ids)} pages, ids {ids[0]}-{ids[-1]}")
    print(f"cross-checking {len(sample)}: {sample}\n")
    mismatched, absent = Counter(), Counter()
    bad = []
    for page_id in sample:
        doc = (monitor.archive / f"{page_id}.html").read_bytes().decode("utf-8", errors="replace")
        got, ref = monitor.parser.parse(doc), monitor.parser.crosscheck(doc)
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
    for f in monitor.fields:
        k = f["key"]
        print(f"  {k:<14} mismatches {mismatched[k]:>2}   absent on page (both agree) {absent[k]:>2}")
    print("\n" + (f"pages needing attention: {bad}" if bad else
                  "no disagreements: both readers read every sampled page identically"))
    return bad


# --- runs and change detection -------------------------------------------

def field_diff(monitor, before_bytes, after_bytes):
    """Which of the monitor's diff_fields changed between two snapshots."""
    keys = monitor.get("diff_fields") or [f["key"] for f in monitor.fields]
    old = monitor.parser.parse(before_bytes.decode("utf-8", errors="replace"))
    new = monitor.parser.parse(after_bytes.decode("utf-8", errors="replace"))
    changes = []
    for key in keys:
        if old.get(key) != new.get(key):
            changes.append({"field": key, "before": old.get(key), "after": new.get(key)})
    return changes


def supersede(monitor, page_id, old_bytes, stamp):
    """Keep the bytes we are about to replace. The archive never loses a version."""
    folder = monitor.superseded / str(page_id)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{stamp.replace(':', '').replace('-', '')}.html"
    dest.write_bytes(old_bytes)
    return str(dest.relative_to(ROOT))


def write_run(monitor, record):
    RUNS.mkdir(exist_ok=True)
    path = RUNS / f"{record['run_id']}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return path


def run(monitor):
    """One monitoring pass over the whole id space, recording what moved."""
    fetcher = Fetcher(monitor)
    started = now()
    log(f"monitor {monitor.name}; run started {started}")
    frontier = find_frontier(fetcher)
    floor = int(monitor.get("discovery", "floor"))

    checked = 0
    new_pages, changed, removed, errors = [], [], [], []
    unchanged = absent = 0

    for page_id in range(frontier, floor - 1, -1):
        dest = monitor.archive / f"{page_id}.html"
        known = dest.exists() and dest.stat().st_size > 0
        before = dest.read_bytes() if known else None
        status, body = fetcher.get(page_id, refetch=True)
        checked += 1

        if status == 200 and body:
            if not known:
                new_pages.append(page_id)
            elif sha256(body) != sha256(before):
                stamp = now()
                kept = supersede(monitor, page_id, before, stamp)
                changed.append({
                    "id": page_id,
                    "sha256_before": sha256(before),
                    "sha256_after": sha256(body),
                    "previous_snapshot": kept,
                    "fields_changed": field_diff(monitor, before, body),
                })
                log(f"  {page_id}: CHANGED ({len(changed[-1]['fields_changed'])} fields)")
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
                f"{len(changed)} changed, {len(new_pages)} new")

    record = {
        "run_id": started.replace(":", "").replace("-", ""),
        "monitor": monitor.name,
        "kind": "recheck",
        "started_utc": started,
        "finished_utc": now(),
        "frontier": frontier,
        "id_range": [floor, frontier],
        "pages_checked": checked,
        "pages_archived_after_run": len(monitor.archived_ids()),
        "new_pages": new_pages,
        "changed_pages": changed,
        "removed_pages": removed,
        "unchanged_pages": unchanged,
        "ids_absent": absent,
        "errors": errors,
    }
    record["summary"] = (
        f"{checked} pages checked, {len(new_pages)} new, {len(changed)} changed, "
        f"{len(removed)} removed, {len(errors)} errors"
        if (new_pages or changed or removed or errors) else
        f"{checked} pages checked; no page changed since the previous run"
    )
    path = write_run(monitor, record)
    log(f"run recorded: {path.relative_to(ROOT)} — {record['summary']}")
    return record


def seed_run(monitor):
    """Reconstruct the initial collection as a run record, from the request log.

    Marked reconstructed: it is assembled from the request log written during
    the first collection, not observed by a run of this code.
    """
    path = monitor.request_log
    if not path.exists():
        sys.exit(f"no request log at {path}")
    rows = list(csv.DictReader(path.open(encoding="utf-8"), delimiter="\t"))
    ok = [r for r in rows if r["http_status"] == "200"]
    missing = [r for r in rows if r["http_status"] == "404"]
    stamps = sorted(r["fetched_at_utc"] for r in rows)
    ids = sorted({int(r["id"]) for r in ok})
    record = {
        "run_id": stamps[0].replace(":", "").replace("-", ""),
        "monitor": monitor.name,
        "kind": "initial-collection",
        "reconstructed": True,
        "reconstructed_from": str(path.relative_to(ROOT)),
        "started_utc": stamps[0],
        "finished_utc": stamps[-1],
        "frontier": max(ids),
        "id_range": [int(monitor.get("discovery", "floor")), max(ids)],
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
    p = write_run(monitor, record)
    print(f"wrote {p.relative_to(ROOT)} — {record['summary']}")
    return record


def load_runs(monitor=None):
    if not RUNS.exists():
        return []
    out = []
    for p in sorted(RUNS.glob("*.json")):
        rec = json.loads(p.read_text(encoding="utf-8"))
        if monitor is None or rec.get("monitor") == monitor:
            out.append(rec)
    out.sort(key=lambda r: r["started_utc"])
    return out


def show_runs(monitor):
    runs = load_runs(monitor.name)
    if not runs:
        print("no runs recorded yet")
        return
    print(f"{'started (UTC)':<27}{'kind':<20}{'checked':>8}{'new':>6}{'changed':>9}")
    for r in runs:
        print(f"{r['started_utc']:<27}{r['kind']:<20}{r['pages_checked']:>8}"
              f"{len(r['new_pages']):>6}{len(r['changed_pages']):>9}")


# --- collect -------------------------------------------------------------

def collect(monitor):
    """Fill the archive down to the floor. Archived ids are left untouched."""
    fetcher = Fetcher(monitor)
    log(f"monitor {monitor.name}; user-agent: {fetcher.ua}")
    frontier = find_frontier(fetcher)
    floor = int(monitor.get("discovery", "floor"))
    log(f"walking {frontier} down to {floor}")
    counts = Counter()
    for page_id in range(frontier, floor - 1, -1):
        dest = monitor.archive / f"{page_id}.html"
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
    if cmd == "monitors":
        for name in available():
            m = Monitor(name)
            print(f"{name:<16} {m.get('title', default='')}")
        return
    if len(args) < 2:
        sys.exit(f"usage: python3 runner.py {cmd} <monitor>   (installed: {', '.join(available())})")
    monitor = Monitor(args[1])
    if cmd == "collect":
        collect(monitor)
    elif cmd == "run":
        run(monitor)
    elif cmd == "seed-run":
        seed_run(monitor)
    elif cmd == "runs":
        show_runs(monitor)
    elif cmd == "extract":
        extract(monitor)
    elif cmd == "check":
        check(monitor)
    else:
        sys.exit(f"unknown command {cmd!r}")


if __name__ == "__main__":
    main()
