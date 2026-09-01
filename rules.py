#!/usr/bin/env python3
"""Rule engine. Source-agnostic; rules are configuration, not code.

Every evaluation returns exactly one of three verdicts:

  compliant       the test ran on real evidence and passed
  not_compliant   the test ran on real evidence and failed
  indeterminate   the test could not be run, with a reason saying why

There is no fourth outcome. A page is never skipped, never defaulted, and never
approximated. In particular an unbounded first_seen — a page that was already
there the first time anything looked — is not evidence of when it was posted,
so it yields indeterminate no matter what its dates would compute to.
"""
import json
import re
from datetime import datetime, timezone

COMPLIANT = "compliant"
NOT_COMPLIANT = "not_compliant"
INDETERMINATE = "indeterminate"

# The only test grammar the engine understands: a difference between two date
# fields compared against a number of days. Anything else raises, so a rule
# cannot silently evaluate as something other than what it says.
TEST = re.compile(r"^\s*(\w+)\s*-\s*(\w+)\s*(>=|<=|>|<|==)\s*(\d+)\s*days?\s*$")

OPS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
}


class RuleError(ValueError):
    """A rule the engine cannot evaluate as written."""


def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).date()
    except ValueError:
        return None


def parse_with_format(value, fmt):
    if not value or not fmt:
        return None
    try:
        return datetime.strptime(value, fmt).date()
    except ValueError:
        return None


def resolve(field, record, first_seen_row, date_formats):
    """Return (date, problem). Exactly one of the two is None.

    `first_seen` is special: it comes from the ledger, not the page, and it
    carries a confidence that decides whether it may be used at all.
    """
    if field == "first_seen":
        if not first_seen_row:
            return None, "this page has no first-seen record"
        confidence = first_seen_row.get("first_seen_confidence")
        if confidence != "bounded":
            return None, ("first_seen is unbounded: the page was already present the "
                          "first time this platform looked, so the date it became "
                          "available is unknown and cannot support a finding")
        value = parse_iso(first_seen_row.get("first_seen_utc"))
        if not value:
            return None, "first_seen is recorded but not a readable timestamp"
        return value, None

    raw = record.get(field)
    if raw in (None, "", []):
        return None, f"the page does not carry {field}"
    fmt = (date_formats or {}).get(field)
    if not fmt:
        return None, f"no date format is declared for {field}, so it cannot be read as a date"
    value = parse_with_format(raw, fmt)
    if not value:
        return None, f"{field} is present but does not match the declared date format"
    return value, None


def evaluate(rule, record, first_seen_row, date_formats):
    """Evaluate one rule against one page."""
    match = TEST.match(rule.get("test") or "")
    if not match:
        raise RuleError(f"rule {rule.get('id')!r}: cannot evaluate test "
                        f"{rule.get('test')!r}; the engine understands "
                        f"'<field> - <field> >= N days'")
    left_name, right_name, op, days = match.group(1), match.group(2), match.group(3), int(match.group(4))

    required = rule.get("requires") or [left_name, right_name]
    values, problems = {}, []
    for field in required:
        value, problem = resolve(field, record, first_seen_row, date_formats)
        if problem:
            problems.append(problem)
        else:
            values[field] = value.isoformat()

    if problems:
        return {"status": INDETERMINATE, "reason": "; ".join(problems), "values": values}

    left, _ = resolve(left_name, record, first_seen_row, date_formats)
    right, _ = resolve(right_name, record, first_seen_row, date_formats)
    delta = (left - right).days
    passed = OPS[op](delta, days)
    return {
        "status": COMPLIANT if passed else NOT_COMPLIANT,
        "reason": (f"{left_name} minus {right_name} is {delta} days, "
                   f"which is {'at least' if passed else 'less than'} {days}"),
        "values": dict(values, days_between=delta),
    }


def evaluate_beat(beat, records, first_seen):
    """Evaluate every rule against every archived page."""
    rules = beat.get("rules") or []
    date_formats = beat.get("date_formats") or {}
    results, tallies = [], {}
    for rule in rules:
        counts = {COMPLIANT: 0, NOT_COMPLIANT: 0, INDETERMINATE: 0}
        for record in records:
            outcome = evaluate(rule, record, first_seen.get(record["id"]), date_formats)
            counts[outcome["status"]] += 1
            results.append({
                "id": record["id"],
                "rule": rule["id"],
                "status": outcome["status"],
                "reason": outcome["reason"],
                "values": outcome["values"],
                "source_url": record.get("source_url"),
            })
        tallies[rule["id"]] = counts
    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "beat": beat.name,
        "rules": [{k: v for k, v in rule.items()} for rule in rules],
        "tallies": tallies,
        "pages_evaluated": len(records),
        "results": results,
    }


def run(beat, records, first_seen):
    """Evaluate and write the beat's rules output."""
    report = evaluate_beat(beat, records, first_seen)
    path = (beat.path("storage", "rules_out")
            or beat.data_dir / f"{beat.name}-rules.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report, path
