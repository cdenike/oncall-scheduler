"""Days people cannot be scheduled, and where that is written down.

Booked time off is an input like the roster, and like the roster it lives in
plain JSON beside the calendars: one file per group, dates in ISO form, so it
can be checked and corrected without the app.

Dates are stored individually rather than as ranges. A range is how people book
time off and how it should be read back to them, but a set of days is what the
solver needs, and keeping the stored form the same as the used form means no
range arithmetic between the two -- ranges are rebuilt for display only.

Copyright (C) 2026 Caden DeNike. Free software under the GNU General
Public License, version 3 or later, with no warranty. See LICENSE.
"""

import datetime
import json

from .roster import DATA_DIR

TIMEOFF = DATA_DIR / "timeoff"


def path(group):
    return TIMEOFF / ("%s.json" % group)


def load(group):
    try:
        data = json.loads(path(group).read_text())
    except (OSError, ValueError):
        return {}
    return {name: sorted(set(days)) for name, days in data.items() if days}


def save(group, data):
    TIMEOFF.mkdir(parents=True, exist_ok=True)
    clean = {name: sorted(set(days)) for name, days in data.items() if days}
    path(group).write_text(json.dumps(clean, indent=2, sort_keys=True) + "\n")


def add(group, name, start, end=None):
    """Book a day, or every day from start to end inclusive."""
    end = end or start
    if end < start:
        start, end = end, start
    data = load(group)
    days = set(data.get(name, []))
    day = start
    while day <= end:
        days.add(day.isoformat())
        day += datetime.timedelta(days=1)
    data[name] = sorted(days)
    save(group, data)
    return data


def remove(group, name, dates):
    data = load(group)
    if name not in data:
        return data
    data[name] = [d for d in data[name] if d not in set(dates)]
    save(group, data)
    return data


def for_month(group, year, month):
    """{name: {day numbers}} for one month, which is what the solver wants."""
    out = {}
    prefix = "%04d-%02d-" % (year, month)
    for name, days in load(group).items():
        taken = {int(d[8:10]) for d in days if d.startswith(prefix)}
        if taken:
            out[name] = taken
    return out


def spans(dates):
    """Consecutive dates folded back into (start, end) pairs, for reading."""
    out = []
    for iso in sorted(dates):
        day = datetime.date.fromisoformat(iso)
        if out and day - out[-1][1] == datetime.timedelta(days=1):
            out[-1][1] = day
        else:
            out.append([day, day])
    return [(a, b) for a, b in out]


def describe(dates):
    """"3-7 November, 21 November" -- how someone would say it aloud."""
    parts = []
    for start, end in spans(dates):
        if start == end:
            parts.append(start.strftime("%-d %B"))
        elif (start.month, start.year) == (end.month, end.year):
            parts.append("%d-%s" % (start.day, end.strftime("%-d %B")))
        else:
            parts.append("%s - %s" % (start.strftime("%-d %b"),
                                      end.strftime("%-d %b")))
    return ", ".join(parts)
