"""Solved months on disk, and what the next month needs to know about them.

One JSON file per month beside the calendars, so a schedule can be read,
corrected or diffed without the app. The reason they are kept at all is the
month boundary: a rota built from the month alone will open with whoever closed
the one before, and the only way to avoid that is to remember.

Copyright (C) 2026 Caden DeNike. Free software under the GNU General
Public License, version 3 or later, with no warranty. See LICENSE.
"""

import calendar
import json

from .roster import DATA_DIR

MONTHS = DATA_DIR / "months"

def path(year, month, group):
    return MONTHS / group / ("%04d-%02d.json" % (year, month))


def save(schedule, group):
    path(schedule["year"], schedule["month"], group).parent.mkdir(
        parents=True, exist_ok=True)
    out = dict(schedule)
    # JSON has no integer keys; days are written as strings and read back.
    out["tech"] = {str(k): v for k, v in schedule["tech"].items()}
    out["sup"] = {str(k): v for k, v in schedule.get("sup", {}).items()}
    path(schedule["year"], schedule["month"], group).write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n")


def load(year, month, group):
    try:
        data = json.loads(path(year, month, group).read_text())
    except (OSError, ValueError):
        return None
    return _usable(data)


def _usable(data):
    """A record in the shape the rest of the program expects.

    Days come back as numbers, and the gap comes back as one too. A month read
    off somebody else's calendar has no gap to record -- there is no telling
    what it was solved for, if it was solved at all -- and it is written as
    null. Every reader of these files then has to remember that a gap can be
    null, and one of them did not: it asked for a number, got null, and took
    the window down with it before it ever appeared.
    """
    data["tech"] = {int(k): v for k, v in data.get("tech", {}).items()}
    data["sup"] = {int(k): v for k, v in data.get("sup", {}).items()}
    data["gap"] = data.get("gap") or 0
    return data


def history(group):
    """Every month this group has a record of, newest first.

    The record is the app's own: the months it solved and exported, kept as
    JSON beside the roster. It is not a list of pictures found lying about --
    a calendar somebody moved, renamed or deleted is still a month that was
    worked, and a picture in a downloads folder that happens to look like one
    is not.
    """
    out = []
    for file in sorted((MONTHS / group).glob("*.json"), reverse=True):
        try:
            data = json.loads(file.read_text())
        except (OSError, ValueError):
            continue                    # a file somebody edited badly
        if not isinstance(data, dict) or "year" not in data or "month" not in data:
            continue                    # not a month record at all
        out.append(_usable(data))
    return out


def remember_export(schedule, group, where):
    """Note where a month's calendar was written, so it can be rewritten."""
    schedule = dict(schedule)
    schedule["exported"] = str(where)
    save(schedule, group)
    return schedule


def forget(group):
    """Drop every saved month for a group, and say how many that was.

    The calendars themselves are not touched: they are the user's files, in
    whatever folder they chose, and an app that deletes those because somebody
    cleared a list inside it has overstepped.
    """
    gone = 0
    for file in (MONTHS / group).glob("*.json"):
        try:
            file.unlink()
            gone += 1
        except OSError:
            pass
    return gone


def save_tail(year, month, group, tech_by_day, supervisor=None):
    """Record just the closing days of a month nobody solved here.

    A month that was scheduled before this app existed has no file, and without
    one the next month is built as though it had never happened. Its last days
    are all the boundary actually needs, so they can be entered on their own and
    are marked `partial` -- the shift counts and weekends in such a file are not
    the month's, and nothing should read them as if they were.
    """
    record = {
        "year": year, "month": month, "partial": True,
        "tech": {str(int(d)): n for d, n in tech_by_day.items() if n},
        "sup": {},
    }
    if supervisor:
        mondays = [d for d in range(1, calendar.monthrange(year, month)[1] + 1)
                   if calendar.weekday(year, month, d) == calendar.MONDAY]
        if mondays:
            record["sup"] = {str(mondays[-1]): supervisor}
    target = path(year, month, group)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record


def previous(year, month):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _thin_carry(year, month, supervisors, group):
    """What can be known about the boundary with last month unsaved.

    The supervisor cycle survives: a solved month records who was covering the
    days before it, and that is exactly the cycle position needed to carry on.
    Without it the cycle restarts at the top of the roster, which puts whoever
    closed last month back on the first Monday of this one -- a week apart when
    they should be a full cycle apart.

    Nothing can be recovered about the technicians. Their spacing is the whole
    reason these files are kept, so this says so rather than quietly scheduling
    as if the month before never happened.
    """
    carry = {"boundary_known": False}
    current = load(year, month, group)
    lead = (current or {}).get("lead_supervisor")
    if lead and supervisors and lead in supervisors:
        carry["supervisor_index"] = supervisors.index(lead)
    return carry


def carry_in(year, month, supervisors, group):
    """What last month leaves behind: spacing, loads, weekends, the sup cycle.

    Days are returned relative to the new month, so the last day of last month
    is 0 and the first of this one is 1. A gap of ten then means the same
    arithmetic on both sides of the boundary, which is the whole point.
    """
    prev_year, prev_month = previous(year, month)
    prev = load(prev_year, prev_month, group)
    if not prev:
        return _thin_carry(year, month, supervisors, group)

    prev_days = calendar.monthrange(prev_year, prev_month)[1]
    last_shift, counts, weekend = {}, {}, set()
    for day, tech in prev["tech"].items():
        counts[tech] = counts.get(tech, 0) + 1
        offset = day - prev_days          # last day of last month -> 0
        if offset > last_shift.get(tech, -10**6):
            last_shift[tech] = offset
        if calendar.weekday(prev_year, prev_month, day) in (calendar.SATURDAY,
                                                            calendar.SUNDAY):
            weekend.add(tech)

    partial = bool(prev.get("partial"))
    busiest = max(counts.values()) if counts else 0
    carry = {
        "boundary_known": True,
        "partial_previous": partial,
        "last_shift": last_shift,
        # Whoever carried the heavier load, to be spared it this time. Only
        # meaningful when the month was uneven; a month that divided exactly
        # leaves nobody to spare.
        # Both of these count a whole month. A tail is not one: three shifts
        # in its last week says nothing about the month's load, and nobody
        # should be spared or served on that basis.
        "heavy": [] if partial else sorted(
            t for t, c in counts.items()
            if c == busiest and busiest > min(counts.values())),
        "weekend": [] if partial else sorted(weekend),
    }

    mondays = [d for d in sorted(prev["sup"]) ]
    if mondays and supervisors:
        last_sup = prev["sup"][mondays[-1]]
        if last_sup in supervisors:
            carry["supervisor_index"] = supervisors.index(last_sup)
    return carry
