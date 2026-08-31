#!/usr/bin/env python3
"""Parse archived hearing pages into hearings.json / hearings.csv.

Every extracted field is either a value found on the page or an explicit null
that is counted and reported. Nothing is inferred, defaulted, or backfilled.

The archive records what a page said at fetch time. The site does not publish a
posting/announcement date, so none is derived here.
"""
import csv
import hashlib
import html
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
MANIFEST = ROOT / "fetch_status.tsv"
JSON_OUT = ROOT / "hearings.json"
CSV_OUT = ROOT / "hearings.csv"
SOURCE_URL = "https://malegislature.gov/Events/Hearings/Detail/{}"

DT_DD = re.compile(r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", re.S | re.I)
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
BILL = re.compile(r"/Bills/(\d+)/([HSD]\d+)\b", re.I)
TAG = re.compile(r"<[^>]+>")

LABELS = {
    "status": "status",
    "event date": "event_date",
    "start time": "start_time",
    "location": "location",
}
FIELDS = ["status", "event_date", "start_time", "location"]

# The /Events/Hearings/Detail/ id space holds more than hearings: titles read
# "<event type> Details - <name>". For a hearing the name is the committee; for
# a conference committee meeting it is the bill subject, not a committee.
TITLE_SPLIT = re.compile(r"\s+-\s+")


def text(fragment):
    """HTML fragment -> collapsed plain text."""
    return re.sub(r"\s+", " ", html.unescape(TAG.sub(" ", fragment))).strip()


def parse_page(hearing_id, raw_bytes):
    doc = raw_bytes.decode("utf-8", errors="replace")
    rec = {
        "id": hearing_id,
        "source_url": SOURCE_URL.format(hearing_id),
        "event_type": None,
        "committee": None,
        "subject": None,
        "status": None,
        "event_date": None,
        "start_time": None,
        "location": None,
        "bills": [],
    }

    tm = TITLE.search(doc)
    if tm:
        title = text(tm.group(1))
        rec["page_title"] = title
        parts = TITLE_SPLIT.split(title, maxsplit=1)
        prefix = parts[0].strip()
        if prefix.lower().endswith("details"):
            rec["event_type"] = re.sub(r"\s*Details$", "", prefix, flags=re.I).strip() or None
        name = parts[1].strip() if len(parts) == 2 else ""
        if name:
            if rec["event_type"] and rec["event_type"].lower() == "hearing":
                rec["committee"] = name
            else:
                rec["subject"] = name

    for dt, dd in DT_DD.findall(doc):
        label = text(dt).rstrip(":").strip().lower()
        key = LABELS.get(label)
        if key and rec[key] is None:
            value = text(dd)
            rec[key] = value if value else None

    seen = set()
    for court, num in BILL.findall(doc):
        num = num.upper()
        if num not in seen:
            seen.add(num)
            rec["bills"].append({"number": num, "general_court": int(court)})

    rec["bill_count"] = len(rec["bills"])
    rec["raw_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
    rec["raw_bytes"] = len(raw_bytes)
    return rec


def load_fetch_times():
    times = {}
    if MANIFEST.exists():
        with MANIFEST.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                if row.get("http_status") == "200":
                    times[int(row["id"])] = row["fetched_at_utc"]
    return times


def main():
    paths = sorted(RAW.glob("*.html"), key=lambda p: int(p.stem))
    if not paths:
        sys.exit("no archived pages in raw/")
    times = load_fetch_times()

    records, failures = [], Counter()
    by_type, per_type = Counter(), Counter()
    empty_pages = []
    for path in paths:
        hearing_id = int(path.stem)
        rec = parse_page(hearing_id, path.read_bytes())
        rec["fetched_at_utc"] = times.get(hearing_id)
        kind = rec["event_type"] or "<unknown type>"
        by_type[kind] += 1
        for field in ["event_type", "committee", "subject"] + FIELDS:
            if rec[field] is None:
                failures[field] += 1
                per_type[(kind, field)] += 1
        if rec["bill_count"] == 0:
            failures["bills(empty)"] += 1
            per_type[(kind, "bills(empty)")] += 1
        if all(rec[f] is None for f in FIELDS):
            empty_pages.append(hearing_id)
        records.append(rec)

    JSON_OUT.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    with CSV_OUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "id", "event_type", "committee", "subject", "status", "event_date",
            "start_time", "location", "bill_count", "bills", "source_url",
            "fetched_at_utc", "raw_sha256",
        ])
        for r in records:
            writer.writerow([
                r["id"], r["event_type"] or "", r["committee"] or "", r["subject"] or "",
                r["status"] or "", r["event_date"] or "",
                r["start_time"] or "", r["location"] or "", r["bill_count"],
                ";".join(b["number"] for b in r["bills"]),
                r["source_url"], r["fetched_at_utc"] or "", r["raw_sha256"],
            ])

    total = len(records)
    print(f"parsed {total} pages -> {JSON_OUT.name}, {CSV_OUT.name}")
    print("\npages by event type:")
    for kind, n in by_type.most_common():
        print(f"  {kind:<32} {n:>4}")

    print("\nextraction failures (field absent / pages):")
    for field in ["event_type", "committee", "subject"] + FIELDS + ["bills(empty)"]:
        n = failures[field]
        pct = 100.0 * n / total if total else 0.0
        detail = ", ".join(
            f"{kind}: {per_type[(kind, field)]}/{by_type[kind]}"
            for kind, _ in by_type.most_common()
            if per_type[(kind, field)]
        )
        print(f"  {field:<14} {n:>4} / {total}  ({pct:.1f}%)" + (f"   [{detail}]" if detail else ""))
    print("\nnote: committee is populated only for Hearing pages and subject only for"
          "\nnon-hearing pages, so each is 'missing' on the other type by construction.")
    if empty_pages:
        print(f"\npages with no dt/dd fields at all ({len(empty_pages)}): "
              f"{empty_pages[:20]}{' ...' if len(empty_pages) > 20 else ''}")


if __name__ == "__main__":
    main()
