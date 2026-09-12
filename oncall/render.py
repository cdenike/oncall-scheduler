"""Draw the month as a calendar worth pinning up.

Colours and metrics sit at the top of this file in 1x units, multiplied up,
and one design comes out at whatever resolution is asked for.
Dark by intent: the page recedes, the grid is the faintest rule that
even so reads as a grid, and the names carry what brightness there is.
Names sit centred in their day, and the supervisor takes the one accent --
distinguishing the two a Monday carries without shouting either of them.
Everything spanning the full width of the picture is a rule and nothing else.
Nothing brighter crosses the page, and that is machinery as much as taste.
In reading one back, the grid is found by looking for the brightest
kind of line there is: a full-width one. A banner across the page would
efface the very grid a reader is looking for.

Copyright (C) 2026 Caden DeNike. Free software under the GNU General
Public License, version 3 or later, with no warranty. See LICENSE.
"""

import calendar
import functools
import json
import subprocess

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

W1 = 696                       # reference width, 1x
COLS1 = [3, 101, 200, 298, 397, 495, 593, 692]
TITLE_SEP1, HEADER_SEP1 = 44, 72
ROW_H1 = 92.0                  # room to let a name sit on its own

# A dark calendar, and a deliberately quiet one: the page recedes, the rules
# are the faintest thing that still reads as a grid, and the only brightness in
# it is the names -- which is what anyone opens the picture to find. The
# supervisor takes the one accent, because a Monday carries two names and they
# are not the same kind of thing.
#
# One rule to the whole grid, at one brightness, and nothing else in the
# picture drawn across its full width. That is not only taste: the reader finds
# the grid by looking for the brightest full-width lines, so a bright banner or
# an accent underline stretching the page would outshine the rules and hide
# them. The accent under the heading is a short one for that reason.
BG        = (14, 17, 22)       # the page
BG_WEEKEND = (20, 25, 34)      # Saturday and Sunday, a shade apart
BG_OUT    = (10, 12, 16)       # days belonging to the months either side
BG_HEADER = (19, 24, 32)
LINE      = (78, 90, 106)
FG        = (238, 242, 247)    # the technician: the brightest thing here
FG_DIM    = (126, 138, 154)    # day numbers, and the year beside the month
FG_OUT    = (48, 56, 68)
ACCENT    = (226, 178, 87)     # the supervisor

# Names sit in the middle of their cell rather than against its right edge.
# The reader draws candidate names the same way to compare them, so this is
# imported rather than assumed there.
ALIGN = "centre"

# The supervisor is set in the same case as everyone else. Capitals are one
# way to tell the two names apart, and the colour does that here -- but
# capitals also cost legibility at a small size, where a capital I and a
# lowercase l are the same mark: a name set in capitals and ending in one came
# back ending in the other, from a picture at full size. Imported by the
# reader, which draws candidate names to compare them and has to draw them the
# same way.
SUP_CAPS = False

CAP_TITLE, CAP_HEADER, CAP_DAYNUM, CAP_SUP, CAP_TECH = 20, 8, 9, 10, 12
CAP_PHONE = 7
OFF_DAYNUM, OFF_SUP, OFF_TECH_MON, OFF_TECH = 8, 30, 66, 48
# The number sits under the supervisor it belongs to, far enough under
# that the two are separate lines of ink: the reader finds the names in a
# cell by the blank rows between them, and a number tucked up against a
# name would be read as part of it.
OFF_PHONE = 47
PAD_DAYNUM, PAD_SUP, PAD_TECH = 10, 8, 8

# Space added between letters, in units of the cap height, for the two pieces
# of type that are labels rather than names.
TRACK_TITLE, TRACK_HEADER = 0.10, 0.18

# Candidates in preference order, tried until one opens. Liberation Sans is
# metric-compatible with Arial, which is what the reference calendar was drawn
# in and what Windows has; either gives the same design. Bare filenames are
# included on purpose -- Pillow searches the system font directories for those,
# which is how this finds a font on a machine whose layout is not listed here.
FONT_CANDIDATES = {
    "bold": ("/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
             "/usr/share/fonts/TTF/LiberationSans-Bold.ttf",
             "C:/Windows/Fonts/arialbd.ttf",
             "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
             "LiberationSans-Bold.ttf", "arialbd.ttf",
             "DejaVuSans-Bold.ttf", "FreeSansBold.ttf"),
    "regular": ("/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "/usr/share/fonts/TTF/LiberationSans-Regular.ttf",
                "C:/Windows/Fonts/arial.ttf",
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "LiberationSans-Regular.ttf", "arial.ttf",
                "DejaVuSans.ttf", "FreeSans.ttf"),
}


class FontMissing(Exception):
    """No usable font was found, which is worth saying plainly."""


@functools.lru_cache(maxsize=None)
def font_file(weight):
    """The first candidate that actually opens, remembered after the first look."""
    for candidate in FONT_CANDIDATES[weight]:
        try:
            ImageFont.truetype(candidate, 12)
            return candidate
        except OSError:
            continue
    # Nothing on the list is here, so ask the system instead of adding more
    # guesses: fontconfig knows where fonts live on a machine whose layout this
    # list has never heard of, and always answers with something usable.
    matched = _fontconfig(weight)
    if matched:
        return matched
    raise FontMissing(
        "no sans-serif font found; install Liberation Sans or DejaVu Sans")


def _fontconfig(weight):
    """Whatever fontconfig considers the closest match, on systems that have it."""
    pattern = "Liberation Sans:style=%s" % ("Bold" if weight == "bold"
                                            else "Regular")
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}", pattern],
                             **({"creationflags": subprocess.CREATE_NO_WINDOW}
                                if hasattr(subprocess, "CREATE_NO_WINDOW") else {}),
                             capture_output=True, text=True, timeout=5,
                             check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        ImageFont.truetype(out, 12)
    except OSError:
        return None
    return out

DAY_NAMES = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]

# The PNG text chunk the schedule is stored in, read back by importer.py.
METADATA_KEY = "oncall-schedule"
# Who wrote this. Kept as bytes rather than a file header, so it
# travels with the code and with everything the code draws.
PROVENANCE = "436164656e2044654e696b65"


def _font_for_cap(path, cap_px):
    """The font size whose capitals stand cap_px tall.

    Sizes are chosen by measurement rather than by ratio because the same
    nominal size gives different cap heights in different faces, and the
    reference was measured, not specified.
    """
    best, best_delta = 1, 1e9
    for size in range(4, 400):
        font = ImageFont.truetype(path, size)
        _, top, _, bottom = font.getbbox("H")
        height = bottom - top
        if abs(height - cap_px) < best_delta:
            best, best_delta = size, abs(height - cap_px)
        if height > cap_px + 6:
            break
    return ImageFont.truetype(path, best)


def dial(number):
    """A phone number as it should read on the calendar.

    Typed as 5555550144 or as 555-555-0144, it is drawn the same way either
    way: nobody should have to punctuate a phone number to get a calendar that
    looks right, and nobody who already has should see their punctuation
    doubled.

    Digits are grouped from the right -- four, then three, then three, then
    whatever is left over -- which is the shape a ten-digit number has and a
    sensible one for any other length. A leading 1 is dropped: it is the
    country code people type out of habit, and no area code begins with one,
    so eleven digits starting with a 1 are ten digits with a 1 in front.

    Anything that is not a plain string of digits and the punctuation numbers
    are written with -- a country code marked with a plus, an extension, a note
    -- is drawn exactly as typed. Its owner knows better than this does how it
    should look. Too short to be a phone number and it is left alone too.
    """
    text = (number or "").strip()
    if not text or any(c not in "0123456789 -.()" for c in text):
        return text
    digits = "".join(c for c in text if c.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) < 7:
        return text

    groups, rest = [], digits
    for size in (4, 3, 3):
        if len(rest) <= size:
            break
        groups.insert(0, rest[-size:])
        rest = rest[:-size]
    if rest:
        groups.insert(0, rest)
    return "-".join(groups)


def month_grid(year, month):
    """Weeks of (day, in_month) from Sunday, padded from the months either side."""
    days = calendar.monthrange(year, month)[1]
    lead = (calendar.weekday(year, month, 1) + 1) % 7      # 0 = Sunday
    prev_days = calendar.monthrange(*(year - 1, 12) if month == 1
                                    else (year, month - 1))[1]

    cells = [(prev_days - lead + 1 + i, False) for i in range(lead)]
    cells += [(d, True) for d in range(1, days + 1)]
    while len(cells) % 7:
        cells.append((len(cells) - lead - days + 1, False))
    return [cells[i:i + 7] for i in range(0, len(cells), 7)]


def render(schedule, path, scale=4):
    """Write the calendar PNG for a solved month. Returns (width, height)."""
    year, month = schedule["year"], schedule["month"]
    tech = {int(k): v for k, v in schedule["tech"].items()}
    sup = {int(k): v for k, v in schedule.get("sup", {}).items()}
    lead_sup = schedule.get("lead_supervisor")
    phones = schedule.get("phones") or {}

    grid = month_grid(year, month)
    s = scale
    h1 = HEADER_SEP1 + len(grid) * ROW_H1 + 1
    width, height = W1 * s, round(h1 * s)
    cols = [round(c * s) for c in COLS1]
    rows = [round((HEADER_SEP1 + i * ROW_H1) * s) for i in range(len(grid) + 1)]
    line_w = max(1, round(s / 2))

    bold, regular = font_file("bold"), font_file("regular")
    f_title = _font_for_cap(bold, CAP_TITLE * s)
    f_header = _font_for_cap(bold, CAP_HEADER * s)
    f_daynum = _font_for_cap(bold, CAP_DAYNUM * s)
    f_sup = _font_for_cap(bold, CAP_SUP * s)
    f_phone = _font_for_cap(regular, CAP_PHONE * s)
    f_tech = _font_for_cap(regular, CAP_TECH * s)

    im = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(im)

    def right(x_right, cap_top, text, font, fill):
        a, top, c, _ = font.getbbox(text)
        d.text((x_right - c, cap_top - top), text, font=font, fill=fill)

    def centre(cx, cap_top, text, font, fill):
        a, top, c, _ = font.getbbox(text)
        d.text((cx - (a + c) / 2.0, cap_top - top), text, font=font, fill=fill)

    def tracked(x, cap_top, text, font, fill, track):
        """Letters set apart from one another, drawn one at a time.

        Pillow spaces a string the way the font asks; a label wants more air
        than that. Only the heading and the weekday row are set this way --
        never a name, because the reader compares a name against the same name
        drawn its own way, and tracking here would have to be tracking there.
        """
        gap = track * font.size
        for glyph in text:
            _, top, advance, _ = font.getbbox(glyph)
            d.text((x, cap_top - top), glyph, font=font, fill=fill)
            x += advance + gap
        return x

    def tracked_width(text, font, track):
        gap = track * font.size
        return sum(font.getbbox(g)[2] + gap for g in text) - gap

    # The heading, left with the grid rather than centred over it: the month in
    # full, the year quieter beside it, both on one line so the reader can take
    # the month off a single strip.
    name = calendar.month_name[month].upper()
    left = cols[0] + 2 * s
    after = tracked(left, 10 * s, name, f_title, FG, TRACK_TITLE)
    tracked(after + 6 * s, 10 * s, str(year), f_title, FG_DIM, TRACK_TITLE)

    # An accent under the month, the width of the month. Under the month only
    # and not the whole heading: it belongs to the name of the month, and a
    # bright line drawn the width of the page would outshine the grid's own
    # rules and hide them from anything reading the picture back.
    span = tracked_width(name, f_title, TRACK_TITLE)
    d.rectangle([left, (TITLE_SEP1 - 10) * s, left + span,
                 (TITLE_SEP1 - 10) * s + max(1, round(s * 0.75))], fill=ACCENT)

    d.rectangle([cols[0], TITLE_SEP1 * s, cols[-1], HEADER_SEP1 * s],
                fill=BG_HEADER)
    for i, label in enumerate(DAY_NAMES):
        span = tracked_width(label, f_header, TRACK_HEADER)
        tracked((cols[i] + cols[i + 1]) / 2.0 - span / 2.0,
                (TITLE_SEP1 + 11) * s, label, f_header,
                ACCENT if i in (0, 6) else FG_DIM, TRACK_HEADER)

    for r, week in enumerate(grid):
        for c, (day, in_month) in enumerate(week):
            x0, x1, y0, y1 = cols[c], cols[c + 1], rows[r], rows[r + 1]
            if not in_month:
                d.rectangle([x0, y0, x1, y1], fill=BG_OUT)
            elif c in (0, 6):
                # The weekend, a shade apart from the working week.
                d.rectangle([x0, y0, x1, y1], fill=BG_WEEKEND)
            middle = (x0 + x1) / 2.0
            right(x1 - PAD_DAYNUM * s, y0 + OFF_DAYNUM * s, str(day), f_daynum,
                  FG_DIM if in_month else FG_OUT)
            if in_month:
                if c == 1 and day in sup:
                    # Monday: the supervisor in capitals above the technician,
                    # in the one colour the calendar keeps for them.
                    centre(middle, y0 + OFF_SUP * s,
                           sup[day].upper() if SUP_CAPS else sup[day],
                           f_sup, ACCENT)
                    number = dial(phones.get(sup[day]))
                    if number:
                        # In the supervisor's own colour: it is their number,
                        # and on a Monday the cell carries two people.
                        centre(middle, y0 + OFF_PHONE * s, number, f_phone,
                               ACCENT)
                    if day in tech:
                        centre(middle, y0 + OFF_TECH_MON * s, tech[day],
                               f_tech, FG)
                elif day in tech:
                    centre(middle, y0 + OFF_TECH * s, tech[day], f_tech, FG)
            elif c == 1 and r == 0 and lead_sup:
                # The Monday before the month still names who was covering it,
                # in title case: it belongs to last month's calendar, not this
                # one, and reads as a note rather than as an assignment.
                centre(middle, y0 + OFF_SUP * s, lead_sup, f_sup, FG_OUT)

    for x in cols:
        d.rectangle([x - line_w // 2, TITLE_SEP1 * s,
                     x - line_w // 2 + line_w - 1, height - 1], fill=LINE)
    for y in [TITLE_SEP1 * s, HEADER_SEP1 * s] + rows[1:-1] + [height - 1]:
        d.rectangle([cols[0], y - line_w // 2, cols[-1],
                     y - line_w // 2 + line_w - 1], fill=LINE)

    # The schedule travels inside the picture. Reading one of these back is
    # then exact rather than a matter of recognising text -- the same data that
    # drew it, not a guess at what was drawn.
    meta = PngImagePlugin.PngInfo()
    meta.add_text(METADATA_KEY, json.dumps({
        "year": year, "month": month,
        "tech": {str(k): v for k, v in tech.items()},
        "sup": {str(k): v for k, v in sup.items()},
        "lead_supervisor": lead_sup,
        "phones": phones,
        "gap": schedule.get("gap"),
        "weekend_cap": schedule.get("weekend_cap"),
    }, sort_keys=True))
    meta.add_text("oncall-provenance", PROVENANCE)
    im.save(path, pnginfo=meta)
    return width, height
