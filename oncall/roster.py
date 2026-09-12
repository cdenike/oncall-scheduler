"""Who is on the rota, and where that is written down.

The roster is a plain JSON file beside the calendars it produces, so it can be
read, diffed and corrected by hand -- which matters for a file that changes when
someone joins, leaves or moves between the technician and supervisor lists.

Technicians belong to a group, and there can be several: separate teams keeping
separate rotas, each solved and exported on its own. Supervisors are shared,
because the Monday cycle covers the operation rather than any one team; if that
ever stops being true they move into the group alongside the technicians.

A supervisor and a technician may share a first name and still be two different
people. They are kept in separate lists precisely so nothing can confuse them,
and a supervisor's Monday is not part of any technician's spacing.

Copyright (C) 2026 Caden DeNike. Free software under the GNU General
Public License, version 3 or later, with no warranty. See LICENSE.
"""

import json
import os
import pathlib
import re
import sys

def _data_dir():
    """Where this platform keeps an application's own files.

    The roster, the solved months and the booked time off live together here.
    Exports do not: those go wherever the save dialog is pointed, because they
    are the user's rather than the app's.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or (pathlib.Path.home()
                                                  / "AppData/Local")
    elif sys.platform == "darwin":
        base = pathlib.Path.home() / "Library/Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME") or (pathlib.Path.home()
                                                   / ".local/share")
    return pathlib.Path(base) / "oncall-scheduler"


DATA_DIR = _data_dir()
ROSTER = DATA_DIR / "roster.json"

# What a fresh install starts from: one empty group and nobody in it. Names are
# a customer's, not the program's, and an app that arrives already knowing a
# team is wrong for everyone who is not that team -- including the same team
# a year later. What is typed in is kept, in roster.json beside the calendars,
# so this shape is only ever seen once.
DEFAULT = {
    "supervisors": [],
    "groups": [{"id": "team-1", "name": "Team 1", "technicians": []}],
    "inactive": [],
    "phones": {},
}


def slug(name):
    """A directory-safe name for a group, stable enough to store months under."""
    out = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return out or "group"


def load():
    """The roster, seeded from DEFAULT the first time."""
    try:
        data = json.loads(ROSTER.read_text())
    except (OSError, ValueError):
        return json.loads(json.dumps(DEFAULT))      # a fresh deep copy
    data.setdefault("supervisors", [])
    data.setdefault("inactive", [])
    # Numbers are kept against the name rather than beside it in the list, so
    # a roster written before this existed still loads, and so a name that
    # moves up or down the cycle takes its number with it.
    data.setdefault("phones", {})
    # In one shape, whatever shape they were typed in. Numbers reaching the
    # roster come from three places now -- typed into a box, carried in with a
    # calendar somebody uploaded, or written by an older version that kept them
    # exactly as typed -- and a column showing 5555550144 above (555) 555-0119
    # above 555.555.0111 looks like a mistake even though every one of them is
    # right. The calendar has always drawn them one way; this is the list
    # agreeing with the calendar.
    data["phones"] = {name: tidy(number)
                      for name, number in data["phones"].items()}
    if not data.get("groups"):
        data["groups"] = [{"name": DEFAULT["groups"][0]["name"],
                           "technicians": []}]
    return ensure_ids(data)


def ensure_ids(data):
    """Give every group a stable id, keeping any it already has."""
    used = set()
    for index, group in enumerate(data["groups"]):
        group.setdefault("name", "Group")
        group.setdefault("technicians", [])
        # A group's files are keyed on its id, never its name. Naming the
        # folder after the group meant renaming a team orphaned its months --
        # the app looked under the new name while the history sat under the old
        # one. Existing groups take an id from their name once, and keep it.
        ident = group.get("id") or slug(group["name"]) or "group"
        while ident in used:
            index += 1
            ident = "%s-%d" % (slug(group["name"]), index)
        group["id"] = ident
        used.add(ident)
    return data


def save(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ROSTER.write_text(json.dumps(data, indent=2) + "\n")


def group_id(data, index):
    return group(data, index)["id"]


def group(data, index):
    index = max(0, min(index, len(data["groups"]) - 1))
    return data["groups"][index]


def active_technicians(data, index=0):
    """Technicians in one group available to be scheduled, in roster order.

    Order is kept rather than sorted: it is the order someone typed them in,
    and a solver that walks it in a stable order gives the same answer twice.

    Blank names are dropped rather than trusted: a row added in the window and
    not yet typed into is an empty string until it is, and a nameless person on
    the rota would be scheduled and then printed on the calendar.
    """
    inactive = data.get("inactive", [])
    return [t for t in group(data, index)["technicians"]
            if t.strip() and t not in inactive]


def phone(data, name):
    """The number for one supervisor, or "" when there is none."""
    return data.get("phones", {}).get(name, "")


def tidy(number):
    """A number in the shape the calendar draws it in.

    Imported here rather than at the top because it lives with the drawing,
    which is what decides the shape, and because the roster is otherwise
    readable without an image library present.
    """
    from .render import dial

    return dial(number)


def set_phone(data, name, number):
    phones = data.setdefault("phones", {})
    if number:
        phones[name] = tidy(number)
    else:
        phones.pop(name, None)


def rename_phone(data, old, new):
    """Carry a number across when its owner is renamed."""
    phones = data.setdefault("phones", {})
    if old in phones and old != new:
        number = phones.pop(old)
        if new:
            phones[new] = number


def phones_for(data, names):
    """The numbers for these people, leaving out anyone who has none."""
    phones = data.get("phones", {})
    return {name: phones[name] for name in names if phones.get(name)}


def active_supervisors(data):
    return [s for s in data["supervisors"]
            if s.strip() and s not in data.get("inactive", [])]
