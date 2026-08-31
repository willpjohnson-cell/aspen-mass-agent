#!/usr/bin/env python3
"""Confirm the upper frontier by contiguous scan, not by a single 404.

Roughly a fifth of ids inside the archived range are absent, in runs of up to
16 consecutive ids, so one 404 above the last archived page is not evidence of
the end of the id space. This walks upward and only concludes the frontier
after CLEAR_RUN consecutive misses. Any page found is archived like any other.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect  # noqa: E402

START = 5775
CLEAR_RUN = 40
LIMIT = 6000


def main():
    collect.RAW.mkdir(exist_ok=True)
    collect.log(f"verifying frontier: scanning up from {START}, "
                f"need {CLEAR_RUN} consecutive 404s to conclude")
    highest = None
    run = 0
    hid = START
    while run < CLEAR_RUN and hid <= LIMIT:
        status = collect.get(hid)
        if status == 200:
            highest = hid
            run = 0
            collect.log(f"  {hid}: PAGE EXISTS above the assumed frontier — archived")
        elif status == 404:
            run += 1
        else:
            collect.log(f"  {hid}: status {status}; not counted as a miss")
            run = 0
        hid += 1
    if highest is None:
        collect.log(f"confirmed: no pages in {START}-{hid - 1}; frontier stands at 5774")
    else:
        collect.log(f"frontier was WRONG: pages found up to {highest}; "
                    f"{CLEAR_RUN} clear 404s follow it")


if __name__ == "__main__":
    main()
