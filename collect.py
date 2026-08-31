#!/usr/bin/env python3
"""Fetch Massachusetts Legislature hearing detail pages, byte-for-byte.

Sequential, 1.5s between requests, resumable (existing raw/{id}.html is skipped).
Writes a provenance manifest (fetch_status.tsv) recording the HTTP status,
byte count, and UTC fetch time for every id touched.

Contact string for the User-Agent comes from the ARCHIVE_CONTACT env var.
"""
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://malegislature.gov/Events/Hearings/Detail/{}"
DELAY = 1.5
FLOOR = 5000
KNOWN_PRESENT = 5750   # verified to exist
PROBE_ABSENT = 5800    # expected above the frontier

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
MANIFEST = ROOT / "fetch_status.tsv"

CONTACT = os.environ.get("ARCHIVE_CONTACT", "").strip()
if not CONTACT:
    sys.exit("ARCHIVE_CONTACT is not set; refusing to send an anonymous User-Agent.")
UA = f"MA-Hearing-Archive/1.0 (public records archiving; {CONTACT})"


def log(msg):
    print(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}", flush=True)


def record(hearing_id, status, nbytes):
    new = not MANIFEST.exists()
    with MANIFEST.open("a", encoding="utf-8") as fh:
        if new:
            fh.write("id\thttp_status\tbytes\tfetched_at_utc\n")
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        fh.write(f"{hearing_id}\t{status}\t{nbytes}\t{stamp}\n")


def fetch(hearing_id, attempts=3):
    """Return (status, raw_bytes). Bytes are exactly what the server sent."""
    url = BASE.format(hearing_id)
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return 404, b""
            if exc.code in (429, 500, 502, 503, 504) and attempt < attempts:
                backoff = DELAY * 4 * attempt
                log(f"  {hearing_id}: HTTP {exc.code}, retry in {backoff:.0f}s")
                time.sleep(backoff)
                continue
            return exc.code, b""
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt < attempts:
                backoff = DELAY * 4 * attempt
                log(f"  {hearing_id}: {exc.__class__.__name__} {exc}, retry in {backoff:.0f}s")
                time.sleep(backoff)
                continue
            return -1, b""
    return -1, b""


def save(hearing_id, body):
    """Write raw bytes atomically; no decoding, no reformatting."""
    dest = RAW / f"{hearing_id}.html"
    tmp = dest.with_suffix(".html.part")
    tmp.write_bytes(body)
    tmp.replace(dest)


def get(hearing_id):
    """Fetch one id unless already archived. Returns the HTTP status."""
    dest = RAW / f"{hearing_id}.html"
    if dest.exists() and dest.stat().st_size > 0:
        return 200
    status, body = fetch(hearing_id)
    if status == 200 and body:
        save(hearing_id, body)
    record(hearing_id, status, len(body))
    time.sleep(DELAY)
    return status


def find_frontier():
    """Largest id returning 200. Pages fetched along the way are kept."""
    lo, hi = KNOWN_PRESENT, PROBE_ABSENT
    if get(lo) != 200:
        sys.exit(f"anchor id {lo} did not return 200; check the site before continuing")
    while get(hi) == 200:
        log(f"frontier probe: {hi} exists, widening")
        lo, hi = hi, hi + (hi - lo)
    log(f"frontier bracketed: present={lo} absent={hi}")
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if get(mid) == 200:
            lo = mid
        else:
            hi = mid
        log(f"  bracket now present={lo} absent={hi}")
    return lo


def main():
    RAW.mkdir(exist_ok=True)
    log(f"user-agent: {UA}")
    frontier = find_frontier()
    log(f"frontier = {frontier}; walking down to {FLOOR}")
    counts = {"saved": 0, "skipped": 0, "missing": 0, "error": 0}
    for hearing_id in range(frontier, FLOOR - 1, -1):
        dest = RAW / f"{hearing_id}.html"
        if dest.exists() and dest.stat().st_size > 0:
            counts["skipped"] += 1
            continue
        status = get(hearing_id)
        if status == 200:
            counts["saved"] += 1
        elif status == 404:
            counts["missing"] += 1
        else:
            counts["error"] += 1
            log(f"  {hearing_id}: gave up with status {status}")
        done = frontier - hearing_id + 1
        if done % 50 == 0:
            log(f"progress {done}/{frontier - FLOOR + 1} at id {hearing_id} {counts}")
    log(f"done: {counts}")


if __name__ == "__main__":
    main()
