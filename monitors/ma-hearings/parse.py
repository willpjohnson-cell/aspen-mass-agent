#!/usr/bin/env python3
"""Massachusetts Legislature event pages: the only Massachusetts-specific code.

The runner hands `parse` the raw HTML of one archived page and expects a flat
dict of scalars and lists of scalars back. Everything else — fetching, hashing,
timestamping, diffing, rendering — is the runner's job and knows nothing about
this jurisdiction.

A field that is not on the page comes back as None. Nothing is inferred,
defaulted, or backfilled; in particular the site publishes no posting or
announcement date, so none is produced here.

`crosscheck` re-reads the same page with html.parser's tokenizer instead of
regexes. The runner's `check` command diffs the two so that a null can be shown
to be an absence on the page rather than a silent extraction failure.
"""
import html
import re
from html.parser import HTMLParser

DT_DD = re.compile(r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", re.S | re.I)
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
BILL = re.compile(r"/Bills/(\d+)/([HSD]\d+)\b", re.I)
TAG = re.compile(r"<[^>]+>")
TITLE_SPLIT = re.compile(r"\s+-\s+")

# <dt> label on the page -> field name in the record.
LABELS = {
    "status": "status",
    "event date": "event_date",
    "start time": "start_time",
    "location": "location",
}


def text(fragment):
    """HTML fragment -> collapsed plain text."""
    return re.sub(r"\s+", " ", html.unescape(TAG.sub(" ", fragment))).strip()


def _split_title(title):
    """Titles read "<event type> Details - <name>".

    This id space is not only hearings: it also serves conference committee
    meetings, whose title carries a bill subject where a hearing's carries a
    committee name. Putting both in one column would assert committees the
    pages never named, so they are kept apart.
    """
    parts = TITLE_SPLIT.split(title, maxsplit=1)
    prefix = parts[0].strip()
    event_type = None
    if prefix.lower().endswith("details"):
        event_type = re.sub(r"\s*Details$", "", prefix, flags=re.I).strip() or None
    name = parts[1].strip() if len(parts) == 2 else ""
    is_hearing = bool(event_type) and event_type.lower() == "hearing"
    committee = (name or None) if is_hearing else None
    subject = None if is_hearing else (name or None)
    return event_type, committee, subject


def parse(doc):
    """Raw HTML (str) -> dict of extracted fields."""
    rec = {
        "page_title": None,
        "event_type": None,
        "committee": None,
        "subject": None,
        "status": None,
        "event_date": None,
        "start_time": None,
        "location": None,
        "general_court": None,
        "bills": [],
    }

    tm = TITLE.search(doc)
    if tm:
        title = text(tm.group(1))
        rec["page_title"] = title or None
        rec["event_type"], rec["committee"], rec["subject"] = _split_title(title)

    for dt, dd in DT_DD.findall(doc):
        label = text(dt).rstrip(":").strip().lower()
        key = LABELS.get(label)
        if key and rec[key] is None:
            rec[key] = text(dd) or None

    seen = set()
    for court, num in BILL.findall(doc):
        num = num.upper()
        if num not in seen:
            seen.add(num)
            rec["bills"].append(num)
            if rec["general_court"] is None:
                rec["general_court"] = int(court)

    rec["bill_count"] = len(rec["bills"])
    return rec


class _Reader(HTMLParser):
    """Independent walk of the same page: title, dt/dd pairs, bill anchors."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.pairs = {}
        self.bills = []
        self.court = None
        self._stack = []
        self._buf = []
        self._label = None

    def handle_starttag(self, tag, attrs):
        if tag in ("title", "dt", "dd"):
            self._stack.append(tag)
            self._buf = []
        elif tag == "a":
            m = BILL.search(dict(attrs).get("href", "") or "")
            if m and m.group(2).upper() not in self.bills:
                self.bills.append(m.group(2).upper())
                if self.court is None:
                    self.court = int(m.group(1))

    def handle_data(self, data):
        if self._stack:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if not self._stack or self._stack[-1] != tag:
            return
        value = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        self._stack.pop()
        self._buf = []
        if tag == "title":
            self.title = value
        elif tag == "dt":
            self._label = value.rstrip(":").strip().lower()
        elif tag == "dd" and self._label:
            self.pairs.setdefault(self._label, value)
            self._label = None


def crosscheck(doc):
    """Same fields, read with a tokenizer instead of regexes."""
    r = _Reader()
    r.feed(doc)
    event_type, committee, subject = _split_title(r.title)
    return {
        "page_title": r.title or None,
        "event_type": event_type,
        "committee": committee,
        "subject": subject,
        "status": r.pairs.get("status") or None,
        "event_date": r.pairs.get("event date") or None,
        "start_time": r.pairs.get("start time") or None,
        "location": r.pairs.get("location") or None,
        "general_court": r.court,
        "bills": r.bills,
        "bill_count": len(r.bills),
    }
