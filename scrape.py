#!/usr/bin/env python3
"""MVP scraper for Massachusetts Legislature hearing pages.

Usage:
  python3 scrape.py fetch          # find frontier, download all hearing pages
  python3 scrape.py parse          # raw HTML -> hearings.json + hearings.csv
  python3 scrape.py page           # hearings.json -> index.html
"""
import csv, html, json, os, re, sys, time, urllib.request, urllib.error

BASE = "https://malegislature.gov/Events/Hearings/Detail/%d"
UA = "MA-Hearing-Archive/0.1 (+https://github.com/YOURNAME/REPO)"
RAW = "raw"
DELAY = 1.5
LOW = 5000          # walk down to here; lower it if you want earlier sessions


def get(hid, timeout=30):
    """Return HTML string, or None on 404."""
    req = urllib.request.Request(BASE % hid, headers={"User-Agent": UA})
    try:
        return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def find_frontier(lo=5000, hi=9000):
    """Highest hearing id that exists."""
    while lo < hi:
        mid = (lo + hi + 1) // 2
        sys.stderr.write("probe %d\n" % mid)
        exists = get(mid) is not None
        time.sleep(DELAY)
        if exists:
            lo = mid
        else:
            hi = mid - 1
    return lo


def fetch():
    os.makedirs(RAW, exist_ok=True)
    top = find_frontier()
    print("frontier: %d" % top)
    for hid in range(top, LOW - 1, -1):
        path = os.path.join(RAW, "%d.html" % hid)
        if os.path.exists(path):
            continue
        try:
            doc = get(hid)
        except Exception as e:
            print("  %d ERROR %s" % (hid, e))
            time.sleep(5)
            continue
        if doc is None:
            print("  %d 404" % hid)
        else:
            open(path, "w", encoding="utf-8").write(doc)
            print("  %d ok (%d bytes)" % (hid, len(doc)))
        time.sleep(DELAY)


# --- parsing -------------------------------------------------------------

def field(doc, label):
    """Grab the <dd> following a <dt> containing `label`."""
    m = re.search(re.escape(label) + r"\s*:?\s*</dt>\s*<dd[^>]*>(.*?)</dd>", doc, re.S)
    if not m:
        return None
    txt = re.sub(r"<[^>]+>", " ", m.group(1))
    return html.unescape(re.sub(r"\s+", " ", txt)).strip() or None


def parse_one(hid, doc):
    t = re.search(r"<title>(.*?)</title>", doc, re.S)
    title = html.unescape(t.group(1)).strip() if t else ""
    committee = title.replace("Hearing Details -", "").strip()
    bills = sorted(set(re.findall(r"/Bills/\d+/([HSD]\d+)\b", doc)))
    return {
        "id": hid,
        "committee": committee,
        "status": field(doc, "Status"),
        "event_date": field(doc, "Event Date"),
        "start_time": field(doc, "Start Time"),
        "location": field(doc, "Location"),
        "bill_count": len(bills),
        "bills": bills,
        "url": BASE % hid,
    }


def parse():
    rows = []
    for fn in sorted(os.listdir(RAW)):
        if not fn.endswith(".html"):
            continue
        hid = int(fn[:-5])
        rows.append(parse_one(hid, open(os.path.join(RAW, fn), encoding="utf-8").read()))
    rows.sort(key=lambda r: r["id"])
    json.dump(rows, open("hearings.json", "w"), indent=1)
    cols = ["id", "committee", "status", "event_date", "start_time", "location", "bill_count", "url"]
    with open("hearings.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print("parsed %d hearings -> hearings.json, hearings.csv" % len(rows))


def page():
    rows = json.load(open("hearings.json"))
    by_comm = {}
    for r in rows:
        by_comm[r["committee"]] = by_comm.get(r["committee"], 0) + 1
    top = sorted(by_comm.items(), key=lambda kv: -kv[1])
    trs = "\n".join(
        "<tr><td>%d</td><td>%s</td><td>%s</td><td>%s</td><td>%d</td>"
        "<td><a href='%s'>src</a></td></tr>"
        % (r["id"], html.escape(r["committee"]), r["event_date"] or "",
           r["status"] or "", r["bill_count"], r["url"])
        for r in reversed(rows))
    lis = "\n".join("<li>%s &mdash; %d</li>" % (html.escape(c), n) for c, n in top[:15])
    open("index.html", "w").write(f"""<!doctype html><meta charset=utf-8>
<title>MA Legislature Hearing Archive</title>
<style>body{{font:15px/1.5 system-ui;margin:2rem auto;max-width:56rem;padding:0 1rem}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
td,th{{border-bottom:1px solid #ddd;padding:4px 8px;text-align:left}}</style>
<h1>Massachusetts Legislature &mdash; Hearing Archive</h1>
<p>{len(rows)} hearings archived from malegislature.gov.
Raw HTML snapshots and structured data in this repository.</p>
<h2>Hearings by committee</h2><ul>{lis}</ul>
<h2>All hearings</h2>
<table><tr><th>ID<th>Committee<th>Date<th>Status<th>Bills<th>Source</tr>
{trs}</table>""")
    print("wrote index.html (%d hearings)" % len(rows))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "fetch"
    {"fetch": fetch, "parse": parse, "page": page}[cmd]()
