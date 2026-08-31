#!/usr/bin/env python3
"""Cross-check parse.py against an independent extraction path.

parse.py works with regexes over the raw markup. This re-extracts the same
fields with html.parser's tokenizer and diffs the two. Agreement is evidence
the fields are really on the page; disagreement localises the bug. Sampling is
spread evenly across the archived id range.
"""
import html
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse import parse_page  # noqa: E402

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
SAMPLE = 20
COMPARE = ["event_type", "committee", "subject", "status", "event_date",
           "start_time", "location", "bills"]


class Extractor(HTMLParser):
    """Independent DOM-ish walk: title, dt/dd pairs, and bill anchors."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.pairs = {}
        self.bills = []
        self._stack = []
        self._buf = []
        self._label = None

    def handle_starttag(self, tag, attrs):
        if tag in ("title", "dt", "dd"):
            self._stack.append(tag)
            self._buf = []
        elif tag == "a":
            href = dict(attrs).get("href", "")
            m = re.search(r"/Bills/\d+/([HSD]\d+)\b", href, re.I)
            if m:
                num = m.group(1).upper()
                if num not in self.bills:
                    self.bills.append(num)

    def handle_data(self, data):
        if self._stack:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if not self._stack or self._stack[-1] != tag:
            return
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        self._stack.pop()
        self._buf = []
        if tag == "title":
            self.title = text
        elif tag == "dt":
            self._label = text.rstrip(":").strip().lower()
        elif tag == "dd" and self._label:
            self.pairs.setdefault(self._label, text)
            self._label = None


def independent(raw_bytes):
    ex = Extractor()
    ex.feed(raw_bytes.decode("utf-8", errors="replace"))
    parts = re.split(r"\s+-\s+", ex.title, maxsplit=1)
    prefix = parts[0].strip()
    etype = re.sub(r"\s*Details$", "", prefix, flags=re.I).strip() if prefix.lower().endswith("details") else None
    name = parts[1].strip() if len(parts) == 2 else ""
    is_hearing = bool(etype) and etype.lower() == "hearing"
    return {
        "event_type": etype or None,
        "committee": (name or None) if is_hearing else None,
        "subject": None if is_hearing else (name or None),
        "status": ex.pairs.get("status") or None,
        "event_date": ex.pairs.get("event date") or None,
        "start_time": ex.pairs.get("start time") or None,
        "location": ex.pairs.get("location") or None,
        "bills": ex.bills,
    }


def main():
    ids = sorted(int(p.stem) for p in RAW.glob("*.html"))
    if not ids:
        sys.exit("no archived pages in raw/")
    step = max(1, len(ids) // SAMPLE)
    sample = ids[::step][:SAMPLE]
    if ids[-1] not in sample:
        sample[-1] = ids[-1]

    print(f"archive holds {len(ids)} pages, ids {ids[0]}-{ids[-1]}")
    print(f"cross-checking {len(sample)} spread across the range: {sample}\n")

    mismatches = {f: 0 for f in COMPARE}
    absent = {f: 0 for f in COMPARE}
    bad = []
    for hid in sample:
        raw = (RAW / f"{hid}.html").read_bytes()
        got = parse_page(hid, raw)
        ref = independent(raw)
        got_cmp = dict(got)
        got_cmp["bills"] = [b["number"] for b in got["bills"]]
        diffs = []
        for f in COMPARE:
            if got_cmp[f] != ref[f]:
                mismatches[f] += 1
                diffs.append(f"{f}: regex={got_cmp[f]!r} htmlparser={ref[f]!r}")
            elif got_cmp[f] in (None, [], ""):
                absent[f] += 1
        flag = "MISMATCH" if diffs else "ok"
        label = got["committee"] or got["subject"] or "?"
        print(f"  {hid}  {flag:<8} {(got['event_type'] or '?'):<28} {label[:44]}")
        for d in diffs:
            print(f"           {d}")
        if diffs:
            bad.append(hid)

    print(f"\nfield-by-field over {len(sample)} sampled pages:")
    for f in COMPARE:
        print(f"  {f:<12} mismatches {mismatches[f]:>2}   absent-on-page (both agree) {absent[f]:>2}")
    print("\n" + (f"pages needing attention: {bad}" if bad
                  else "no disagreements: both extraction paths read every sampled page identically"))


if __name__ == "__main__":
    main()
