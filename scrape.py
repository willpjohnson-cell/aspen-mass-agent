#!/usr/bin/env python3
"""MA Legislature hearing archive — command dispatcher.

Usage:
  ARCHIVE_CONTACT="+https://github.com/you/repo" python3 scrape.py fetch
  python3 scrape.py parse          # raw HTML -> hearings.json + hearings.csv
  python3 scrape.py page           # hearings.json -> index.html
  python3 scrape.py check          # cross-check the parser against a second reader

This keeps the original MVP's command surface. The implementations live in
collect.py, parse.py, page.py, and spotcheck.py, which differ from the MVP in
four ways that matter for an evidence archive:

1. Raw HTML is written as bytes, not decoded to str and re-written as text.
   The MVP's round trip happens to be byte-identical for this server's output,
   but it is not byte-preserving by construction: it substitutes U+FFFD for any
   byte that is not valid UTF-8 and applies newline translation on write.

2. Titles are split into an event type plus either a committee (hearings) or a
   subject (everything else). About 14% of pages in this id space are Conference
   Committee Meetings, where the MVP's title.replace() left the whole string
   "Conference Committee Meeting Details - Cannabis Laws" sitting in a column
   labelled "committee".

3. The frontier search brackets from a known-present anchor and the result is
   confirmed by a contiguous scan above it. Roughly a third of ids inside the
   range 404, so a plain binary search over a sparse space can land on a gap and
   report a frontier below the true one.

4. Every request is recorded in fetch_status.tsv with its HTTP status and UTC
   timestamp, and every parsed row carries the SHA-256 of the file it came from,
   so an extract can always be tied back to the bytes that produced it.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMMANDS = {
    "fetch": "collect.py",
    "parse": "parse.py",
    "page": "page.py",
    "check": "spotcheck.py",
}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "fetch"
    if cmd not in COMMANDS:
        sys.exit(f"unknown command {cmd!r}; expected one of {', '.join(COMMANDS)}")
    raise SystemExit(subprocess.call([sys.executable, str(ROOT / COMMANDS[cmd])] + sys.argv[2:]))


if __name__ == "__main__":
    main()
