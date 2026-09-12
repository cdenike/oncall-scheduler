"""Read a calendar PNG back into a schedule.

Two ways, tried in that order.

Every calendar this app exports carries its own schedule inside it, in a PNG
text chunk. Reading one of those back is exact and instant: no guessing, no
recognition, the same data that drew it.

A calendar from anywhere else -- an older tool, or one exported before this
existed -- has to be read off the picture. That is worth doing because the
layout is known: this program drew the design, so where every day number,
technician and supervisor sits is arithmetic rather than a search. Each cell is
cropped exactly and read on its own, which is a far easier problem than handing
a whole calendar to OCR and hoping.

Copyright (C) 2026 Caden DeNike. Free software under the GNU General
Public License, version 3 or later, with no warranty. See LICENSE.
"""

import calendar
import json
import os
import pathlib
import re
import subprocess
import sys

from PIL import Image, ImageChops, ImageDraw, ImageOps

from .render import (ALIGN, SUP_CAPS, CAP_SUP, CAP_TECH, COLS1, HEADER_SEP1,
                     OFF_SUP,
                     OFF_TECH, OFF_TECH_MON, PAD_SUP, PAD_TECH, ROW_H1, W1,
                     _font_for_cap, font_file, month_grid,
                     METADATA_KEY)

# Crops are blown up before they are read, because OCR handles large text far
# better than small. Four, measured: more is not better -- at six the same name
# came back a letter short, the interpolation having closed the gap between two
# adjacent strokes.
ZOOM = 4

# Every cell is read more than once, at different magnifications, and the
# readings vote. One engine's misreading of a cropped name rarely survives
# being enlarged differently, while a correct reading usually does -- so
# agreement is worth more than any single pass, and it needs no knowledge of
# which tesseract build is underneath. Targets are crop heights: the zoom for
# each is worked out from the crop in hand, because a calendar exported at 4x
# arrives four times the size of one drawn at ordinary screen scale.
ZOOM_TARGETS = (48, 96, 160)
MAX_ZOOMS = 3

# What the crop is enlarged to for the reading that decides. Recognition wants
# letters of a certain size and is worse either side of it, so the useful
# question is how tall the crop should end up, not how many times to multiply
# it: a calendar exported at four times the size arrives with its names already
# large, and multiplying those by four again turned one three-letter name into
# a different three-letter one and put a stray letter inside a four-letter
# name, while the same crops left alone read both correctly.
PRIMARY_HEIGHT = 72

# Distance in from a cell's left edge, so the grid line drawn there is outside
# the crop. Without it every name comes back with a leading pipe, the line
# itself read as a character.
INSET = 4

# How far the crop stops short of the cell's right edge, and how far above the
# text it starts. Both are needed to place a candidate rendering exactly where
# the calendar put the real one.
INSET_RIGHT = 2
CROP_ABOVE = 4

# How far the best-fitting name must beat the next best before it is believed.
# Measured on a low-resolution calendar: every correct match cleared 0.05 and
# every wrong one sat under 0.04, so the margin separates the two cleanly even
# where the picture is too coarse to read.
MATCH_MARGIN = 0.05


def _tesseract_command():
    """Where to find tesseract: bundled with the build, or on the system.

    A packaged build carries its own copy, so reading a calendar this app did
    not export works on a machine with nothing installed. Run from source it
    uses whatever is on PATH, which is what a Linux package manager provides.
    """
    if getattr(sys, "frozen", False):
        root = pathlib.Path(getattr(sys, "_MEIPASS", ""))
        for name in ("tesseract/tesseract.exe", "tesseract/tesseract"):
            bundled = root / name
            if bundled.exists():
                # Its language data travels with it and has to be pointed at,
                # or it starts and then cannot read anything.
                tessdata = bundled.parent / "tessdata"
                if tessdata.is_dir():
                    os.environ.setdefault("TESSDATA_PREFIX", str(tessdata))
                return str(bundled)
    return "tesseract"


# A windowed build has no console of its own, so every child process Windows
# starts gets one -- and reading a calendar starts one per cell. They appeared
# as several dozen black windows flashing over the app until the scan
# finished. This asks Windows not to give the child a console at all; it does
# not exist on other platforms, where nothing was ever shown.
_QUIET = ({"creationflags": subprocess.CREATE_NO_WINDOW}
          if hasattr(subprocess, "CREATE_NO_WINDOW") else {})


# Readings already taken, and -- while a scan is being planned rather than
# performed -- the list of readings it is going to want. One calendar is read
# at a time (the window reads on a worker thread, one upload at a time), so
# these belong to the scan in progress and are cleared at the start of each.
_READINGS = {}
_PLANNING = None


class Unreadable(Exception):
    """The image is not a calendar this can make sense of."""


def read(path, known_names=(), known_supervisors=(), prefer_pixels=False,
         expect=None):
    """A schedule dict from a calendar PNG.

    `known_names` and `known_supervisors` are the people already on the roster. Recognition is allowed
    to correct itself against them -- a four-letter name with one letter
    doubled is obviously that name when the roster holds it and nothing else
    close -- which is what makes reading a second month reliable once the
    first has been read.
    """
    image = Image.open(path)
    embedded = None if prefer_pixels else image.info.get(METADATA_KEY)
    if embedded:
        try:
            data = json.loads(embedded)
            data["tech"] = {int(k): v for k, v in data.get("tech", {}).items()}
            data["sup"] = {int(k): v for k, v in data.get("sup", {}).items()}
            data["source"] = "embedded"
            return data
        except (ValueError, TypeError):
            pass                    # fall through and read the picture instead
    return _from_pixels(image, known_names, known_supervisors, expect)


def _zooms(box):
    """The magnifications to read one crop at, most trusted first."""
    primary = max(1, min(10, int(round(PRIMARY_HEIGHT / max(1, box.height)))))
    zooms = [primary]
    for target in ZOOM_TARGETS:
        zoom = max(1, min(10, int(round(target / max(1, box.height)))))
        if zoom not in zooms:
            zooms.append(zoom)
    return zooms[:MAX_ZOOMS]


def _prepare(image, zoom):
    """The image as tesseract wants it: inverted, greyscale, enlarged."""
    # Inverted for dark-on-light, and left in greyscale: thresholding to black
    # and white lost thin strokes, which turned M into V.
    image = ImageOps.invert(image.convert("L"))
    return image.resize((image.width * zoom, image.height * zoom), Image.LANCZOS)


def _key(image, digits, zoom):
    return (image.tobytes(), image.size, digits, zoom)


def _batch(requests):
    """Read many crops in one tesseract, because starting it is the expensive part.

    A month is thirty-odd cells and each is read at up to three magnifications,
    which as separate processes is a hundred of them. Tesseract takes a file
    listing images and writes the pages one after another separated by a form
    feed, so the whole scan costs one start per magnification instead: eight
    cells measured here took 0.17s together against 1.18s apart, and Windows,
    where starting a process costs far more, gains by more than that.

    Anything unexpected -- a build without list support, a page count that does
    not match what was asked for -- falls back to reading them one at a time,
    which is slower and always works.
    """
    import tempfile
    out = {}
    by_pass = {}
    for key, image, digits, zoom in requests:
        by_pass.setdefault((digits, zoom), []).append((key, image))
    for (digits, zoom), items in by_pass.items():
        with tempfile.TemporaryDirectory(prefix="oncall-ocr-") as folder:
            listing = pathlib.Path(folder) / "cells.txt"
            paths = []
            for index, (_, image) in enumerate(items):
                shot = pathlib.Path(folder) / ("cell%03d.png" % index)
                _prepare(image, zoom).save(shot, "PNG")
                paths.append(str(shot))
            listing.write_text("\n".join(paths) + "\n")
            args = [_tesseract_command(), str(listing), "stdout", "--psm", "7"]
            if digits:
                args += ["-c", "tessedit_char_whitelist=0123456789"]
            pages = None
            try:
                done = subprocess.run(args, capture_output=True, timeout=180,
                                      check=True, **_QUIET)
                text = done.stdout.decode("utf-8", "replace")
                pages = text.split("\f")
                # Tesseract ends the last page with a form feed too, so an
                # empty tail is expected; anything else means the pages and the
                # cells are not lined up and the readings cannot be trusted.
                while pages and not pages[-1].strip():
                    pages.pop()
                if len(pages) != len(items):
                    pages = None
            except (OSError, subprocess.SubprocessError):
                pages = None
            if pages is None:
                for key, image in items:
                    out[key] = _single(image, digits, zoom)
            else:
                for (key, _), page in zip(items, pages):
                    out[key] = page
    return out


def _single(image, digits, zoom):
    """One crop, one process. The fallback, and what a lone read still uses."""
    args = [_tesseract_command(), "-", "-", "--psm", "7"]
    if digits:
        args += ["-c", "tessedit_char_whitelist=0123456789"]
    import io
    buf = io.BytesIO()
    _prepare(image, zoom).save(buf, "PNG")
    try:
        return subprocess.run(args, input=buf.getvalue(), capture_output=True,
                              timeout=20, check=True,
                              **_QUIET).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        raise Unreadable(
            "no text recognition available, so a calendar this app did not "
            "export cannot be read; one it did export needs none")


def _tesseract(image, digits=False, zoom=ZOOM):
    """One line of text from a cropped cell, or "" if there is none."""
    key = _key(image, digits, zoom)
    if key in _READINGS:
        return _READINGS[key]
    if _PLANNING is not None:
        # Planning: note what will be wanted and answer nothing, so the whole
        # month can be read in one go rather than a process at a time.
        _PLANNING.append((key, image, digits, zoom))
        return ""
    out = _single(image, digits, zoom)
    _READINGS[key] = out
    return " ".join(out.split())


def _clean_name(text):
    """Strip what is not part of a name: grid lines, stray marks, punctuation.

    Only applied where a name is expected. The title needs its digits, and a
    cleaner that runs everywhere would take the year off it.
    """
    return re.sub(r"^[^A-Za-z]+|[^A-Za-z.'-]+$", "", text or "")


def _match_name(crop, candidates, cap, scale, bold=False, pad=0):
    """Pick the roster name whose rendering looks most like this cell.

    Recognition reads a calendar exported at the usual resolution perfectly and
    a small one not at all: at 1x the names are eight pixels tall, and no amount
    of enlargement recovers detail that was never drawn. But the names are not
    unknown -- they are on the roster -- so the question is not "what does this
    say" but "which of these twelve does it look like", and that can be answered
    by drawing each one the way the calendar drew it and comparing.
    """
    if not candidates:
        return None, 0.0
    target = _mask(crop)
    if not any(target.getdata()):
        return None, 0.0

    best, best_score, runner_up = None, -1.0, -1.0
    for name in candidates:
        rendered = _draw_name(name, crop.size, cap, scale, bold, pad)
        score = _overlap(target, _mask(rendered))
        if score > best_score:
            best, best_score, runner_up = name, score, best_score
        elif score > runner_up:
            runner_up = score
    # A confident match is one that beats the next best by a clear margin; two
    # names that fit equally well mean neither has been recognised.
    confidence = best_score - max(runner_up, 0.0)
    return best, confidence if best_score > 0.40 else 0.0


def _mask(image):
    """The text as a 1-bit mask at its true size.

    A calendar is light text on a dark ground, so the text is the bright part.
    Inverting first -- which is right for handing a crop to OCR -- selects the
    background instead, and every candidate then scores the same because none
    of them is being compared against any ink at all.

    Not normalised to a fixed box either: a name's width is the most telling
    thing about it, and scaling every candidate to one size throws that away.
    """
    return image.convert("L").point(lambda v: 255 if v > 110 else 0).convert("1")


def _overlap(target, rendered):
    """Agreement between two masks of the same size, best over small shifts.

    The shifts absorb a pixel or two of difference between where the calendar
    put the text and where this redrew it, which is not a difference between
    one name and another.
    """
    best = 0.0
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            moved = ImageChops.offset(rendered, dx, dy)
            both = ImageChops.logical_and(target, moved)
            either = ImageChops.logical_or(target, moved)
            ink = sum(either.point(lambda v: 1 if v else 0).convert("L").getdata())
            if not ink:
                continue
            hit = sum(both.point(lambda v: 1 if v else 0).convert("L").getdata())
            best = max(best, hit / float(ink))
    return best


def _draw_name(name, size, cap, scale, bold, pad):
    """The name as the calendar drew it, in a box the size of the crop.

    Placed by the renderer's own rule rather than approximately, alignment
    included -- the calendar centres its names, and a candidate drawn against
    the right-hand edge instead would overlap nothing and score nothing. At
    eight pixels tall, three pixels of misplacement is the difference between a
    match and noise.
    """
    # Drawn the way the calendar draws: light on dark, so one mask reads both.
    image = Image.new("RGB", size, (0, 0, 0))
    draw = ImageDraw.Draw(image)
    font = _font_for_cap(font_file("bold" if bold else "regular"),
                         max(4, int(round(cap * scale))))
    text = name.upper() if (bold and SUP_CAPS) else name
    left, top, right, _ = font.getbbox(text)
    if ALIGN == "centre":
        x = (size[0] - (left + right)) / 2.0
    else:
        x = size[0] - right - int(round((pad - INSET_RIGHT) * scale))
    y = int(round(CROP_ABOVE * scale)) - top
    draw.text((x, y), text, font=font, fill=(255, 255, 255))
    return image


# How alike a reading and a roster name must be before one is taken for the
# other. Set high on purpose: at 0.6, two unrelated five-letter names on the
# same roster matched each other exactly, so a correctly read name was quietly
# replaced by somebody else's and the person it belonged to never made it onto
# the roster. Correcting a misread letter is worth having; inventing an
# identity is not.
NEAR_ENOUGH = 0.85


def _closest(text, known):
    """The roster name a reading is nearest to, when it is clearly that name."""
    if not text or not known:
        return text
    text_l = text.lower()
    for name in known:
        if name.lower() == text_l:
            return name

    # A short reading has no room to be wrong twice. Three letters with one of
    # them misread still says who it is, where the ratio below -- which counts
    # a third of the word against you -- says it says nobody: a three-letter
    # reading one letter out scores 0.67 against the name it came from and was
    # left as somebody who does not exist. Only when a single roster name is
    # that close, and only for short readings, so the mistake this threshold
    # exists to prevent -- two five-letter names taken for each other, four
    # letters apart -- stays prevented.
    if len(text_l) <= 4:
        near = [n for n in known if _one_letter_apart(text_l, n.lower())]
        if len(near) == 1:
            return near[0]

    import difflib
    scored = sorted(((difflib.SequenceMatcher(None, text_l, n.lower()).ratio(), n)
                     for n in known), reverse=True)
    best, name = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    # Close to one name and not nearly as close to another. Two roster names
    # that fit equally well mean the reading has not identified either.
    if best >= NEAR_ENOUGH and best - runner_up >= 0.1:
        return name
    return text


def _one_letter_apart(reading, name):
    """One substitution, insertion or deletion between the two, and no more."""
    if abs(len(reading) - len(name)) > 1:
        return False
    if len(reading) == len(name):
        return sum(1 for a, b in zip(reading, name) if a != b) == 1
    short, long = sorted((reading, name), key=len)
    for cut in range(len(long)):
        if long[:cut] + long[cut + 1:] == short:
            return True
    return False


def _pixels(image):
    """A flat list of one-channel pixel values, across Pillow versions."""
    reader = getattr(image, "get_flattened_data", None) or image.getdata
    return list(reader())


def _profile(image):
    """How much ink each row of an image holds, as a value per row.

    Thresholded before it is squashed, so a three-letter name counts as much as
    a seven-letter one. Averaging the greys instead let a short name disappear
    into a cell sized for a long one -- the row it sat on barely differed from
    an empty one.
    """
    binary = image.convert("L").point(lambda v: 255 if v > 110 else 0)
    return _pixels(binary.resize((1, image.height), Image.BOX))


def _rules(values, share=0.9):
    """Where the ruled lines are in a projection, as positions along it.

    A rule is the brightest thing across a whole row or column -- far brighter
    than text, which only covers part of one -- so it can be found by height
    rather than by knowing where it ought to be. A thick rule reads as a run of
    bright positions and counts once, at its start.
    """
    if not values:
        return []
    ground = sorted(values)[len(values) // 2]
    peak = max(values)
    if peak <= ground + 20:
        return []                       # nothing rule-like: not a ruled grid
    hit = [i for i, v in enumerate(values)
           if v > ground + (peak - ground) * share]
    return [y for i, y in enumerate(hit) if i == 0 or y != hit[i - 1] + 1]


def _grid_columns(image, top, scale):
    """The vertical rules, as the x edges of the seven day columns.

    Assumed until now, from the layout this program draws itself. A calendar
    from anywhere else divides the width differently -- a wider Sunday, a
    margin down one side -- and columns taken on faith crop half a name.
    Returns None when there are not eight rules to be had, and the caller falls
    back to the layout it knows.
    """
    grey = image.convert("L").crop((0, top, image.width, image.height))
    if grey.height < 4:
        return None
    edges = _rules(_pixels(grey.resize((grey.width, 1), Image.BOX)))
    # The page edge is a boundary whether or not anybody drew a line on it: a
    # calendar whose grid runs to the edge of the picture has seven rules and
    # eight columns, and waiting for an eighth rule that was never there threw
    # away the columns of a perfectly ordinary calendar.
    margin = max(2, int(round(2 * scale)))
    if edges and edges[0] > margin:
        edges = [0] + edges
    if edges and edges[-1] < grey.width - margin:
        edges = edges + [grey.width - 1]
    if len(edges) < 8:
        return None
    # Seven columns need eight edges; more than that means the rules include
    # something else, and the widest seven gaps are the days.
    spans = list(zip(edges, edges[1:]))
    spans.sort(key=lambda ab: ab[1] - ab[0], reverse=True)
    spans = sorted(spans[:7])
    return spans if len(spans) == 7 else None


def _canonical(image):
    """The calendar as light ink on a dark ground, whichever way it was drawn.

    This one is drawn light on dark, and everything downstream was written for
    that: the rules are found by being brighter than the cells, ink is counted
    as the bright pixels in a cell, and a crop is inverted on its way to
    recognition. A calendar drawn the other way round -- and most are, being
    meant for paper -- failed all three at once, which looked like three
    separate faults and is one. Turning it the right way round here means the
    rest of the reader never has to ask which sort it was given.
    """
    grey = image.convert("L")
    means = _pixels(grey.resize((1, grey.height), Image.BOX))
    if sorted(means)[len(means) // 2] > 128:
        return ImageOps.invert(image.convert("RGB"))
    return image


def _grid_rows(image, weeks, scale):
    """Where each week's row actually starts and ends, read off the picture.

    The renderer's own arithmetic gives this exactly for a calendar this
    program drew. It gives the wrong answer for one it did not: a calendar from
    the tool this replaced has rows of 79, 74, 83 and 83 pixels where the
    arithmetic expects a uniform 82, so by the second week the crop lands
    between two lines of text and reads the bottom of one and the top of the
    next. It cost every supervisor after the first, and clipped the last stroke
    off technicians -- a five-letter name came back with a stray sixth on the
    end of it.

    The horizontal rules are the brightest full-width thing in the picture, far
    brighter than any text, so they can simply be found. Returns None if there
    are not as many as the month has weeks, and the caller falls back to the
    arithmetic.
    """
    grey = image.convert("L")
    means = _pixels(grey.resize((1, grey.height), Image.BOX))
    ground = sorted(means)[len(means) // 2]
    peak = max(means)
    if peak <= ground + 20:
        return None                     # nothing rule-like: not a grid
    edge = max(2, int(round(2 * scale)))
    found = [y for y, m in enumerate(means)
             if m > ground + (peak - ground) * 0.9 and y < grey.height - edge]
    # A run of bright rows is one thick rule, or the header band; either way the
    # row below it begins where the run ends.
    rules = [y for i, y in enumerate(found) if i == 0 or y != found[i - 1] + 1]
    if len(rules) < weeks:
        return None
    tops = rules[-weeks:]
    rows = list(zip(tops, tops[1:] + [grey.height]))
    # Rules are evenly spaced; lines of text are not. Without this a calendar
    # with no rules at all had its text mistaken for them and came back with
    # rows three pixels tall, which read as nothing at all.
    heights = [b - a for a, b in rows]
    if min(heights) < 8 or max(heights) > min(heights) * 2.5:
        return None
    return rows


def _quiet(values, floor=1):
    """Stretches of a projection with no ink in them, as (start, end)."""
    runs, start = [], None
    for i, value in enumerate(values):
        if value <= floor and start is None:
            start = i
        elif value > floor and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(values)))
    return runs


def _rows_from_ink(image, weeks):
    """Week rows for a calendar drawn without any rules to measure.

    Plenty of calendars have no lines at all: the weeks are laid out by spacing
    and the eye supplies the grid. There is still a grid to find, because the
    weeks repeat -- so the blank stretches that separate them repeat too, at a
    fixed pitch, while everything else in the picture does not.

    Which of those regular stretches is the boundary is the catch. Names sit
    low in a cell, so the blank above a name can be wider than the blank
    between two weeks, and picking the widest put every row half a week out.
    The two candidates differ in what lands at the top of each row: a day
    number, which is one or two characters wide, or a name, which is not. The
    phase that puts the narrow thing on top is the right one.

    Returns None when the picture does not divide up regularly, and the caller
    falls back to the layout this program draws itself.
    """
    profile = _profile(image)
    height = len(profile)
    runs = [(a, b) for a, b in _quiet(profile) if a > 0 and b < height]
    # A row begins where its ink begins, which is the far end of the blank
    # above it -- not the middle of that blank. The middle is close enough at
    # the size this was first tried at and drifts by an eighth of a row at
    # three times it, which is enough to cut the name off the bottom of every
    # week.
    middles = sorted(b - 1 for a, b in runs if b - a >= 3)
    if len(middles) < weeks - 1:
        return None

    best = None
    for i, first in enumerate(middles):
        for second in middles[i + 1:]:
            pitch = second - first
            if pitch < 12 or pitch > height:
                continue
            wanted = [first + k * pitch for k in range(weeks - 1)]
            edges, ok = [], True
            for target in wanted:
                near = min(middles, key=lambda m: abs(m - target))
                if abs(near - target) > pitch * 0.2:
                    ok = False
                    break
                edges.append(near)
            if not ok or edges[-1] > height:
                continue
            top = max(0, edges[0] - pitch)
            rows = list(zip([top] + edges, edges + [min(height, edges[-1] + pitch)]))
            score = _tops_look_like_day_numbers(image, rows)
            if best is None or score > best[0]:
                best = (score, rows)
    if best is None or best[0] <= 0:
        return None
    return best[1]


def _tops_look_like_day_numbers(image, rows):
    """How many of these rows begin with something small, as a day number is."""
    good = 0
    for top, bottom in rows:
        band = image.crop((0, top, image.width, bottom))
        bands = [(a, b) for a, b in _quiet(_profile(band))]
        ink = _ink_spans(_profile(band))
        if len(ink) < 2:
            continue
        first, last = ink[0], ink[-1]
        if (first[1] - first[0]) <= (last[1] - last[0]):
            good += 1
    return good


def _ink_spans(profile, floor=1):
    """The stretches of a projection that do have ink in them."""
    spans, start = [], None
    for i, value in enumerate(profile):
        if value > floor and start is None:
            start = i
        elif value <= floor and start is not None:
            spans.append((start, i))
            start = None
    if start is not None:
        spans.append((start, len(profile)))
    return spans


def _text_bands(cell, scale):
    """The lines of text in a cell, top to bottom, without the day number.

    A cell holds a day number and then the name or two beneath it, separated by
    blank rows, so the names can be found rather than assumed to sit at a fixed
    offset. The day number is dropped by where it is: it is the one thing always
    drawn hard against the top of the cell.
    """
    profile = _profile(cell)
    bands, start = [], None
    for i, value in enumerate(profile):
        if value > 1 and start is None:
            start = i
        elif value <= 1 and start is not None:
            bands.append((start, i))
            start = None
    if start is not None:
        bands.append((start, len(profile)))
    least = max(3, int(round(3 * scale)))
    return [(a, b) for a, b in bands
            if b - a >= least and a > cell.height * 0.22]


def _from_pixels(image, known_names, known_supervisors=(), expect=None):
    image = _canonical(image.convert("RGB"))
    scale = image.width / float(W1)
    if scale <= 0 or abs(image.width - round(W1 * scale)) > 2:
        raise Unreadable("not a calendar of the expected proportions")

    def crop(x0, y0, x1, y1):
        return image.crop((int(x0 * scale), int(y0 * scale),
                           int(x1 * scale), int(y1 * scale)))

    # The title where this program puts it, then wherever it actually is: the
    # strip above the first ruled line, whatever that turns out to be. A
    # calendar with a taller heading, or a heading centred rather than to the
    # left, was refused outright for want of a month it could not see.
    # Where the ruled grid starts, which is both what the heading sits above
    # and what the day columns run below.
    across = _rules(_pixels(image.convert("L").resize((1, image.height),
                                                      Image.BOX)))
    columns = _grid_columns(image, across[0] if across else 0, scale)

    year = month = None
    for attempt in _title_strips(image, scale):
        try:
            year, month = _parse_title(_tesseract(attempt))
            break
        except Unreadable as exc:
            # "No recognition on this machine" is not "this heading is hard to
            # read", and swallowing the first as the second told a Linux user
            # with no tesseract installed that their calendar had a bad title.
            if "no text recognition" in str(exc):
                raise
            continue
    if year is None and expect:
        # Nothing legible: take the month the caller is asking about. Somebody
        # uploading last month's calendar has already said which month it is by
        # choosing it, and refusing the picture over a heading is unhelpful
        # when everything below the heading reads perfectly well.
        year, month = expect
    if year is None:
        raise Unreadable("could not read the month from the title")

    # Which cell holds which day is arithmetic: the month decides the grid, and
    # this is the layout the renderer draws from. Where in the cell the text
    # sits is measured instead, because a calendar drawn by something else puts
    # it somewhere else, and a crop taken on faith reads across two lines.
    grid = month_grid(year, month)
    rows = _grid_rows(image, len(grid), scale) or _rows_from_ink(image, len(grid))

    def scan():
        tech, sup, weak = {}, {}, 0
        for week, row in enumerate(grid):
            top = HEADER_SEP1 + week * ROW_H1
            for column, (day, in_month) in enumerate(row):
                if not in_month:
                    continue
                left, right = COLS1[column], COLS1[column + 1]
                # Measured edges where the picture offered them, the layout
                # this program draws where it did not.
                if columns:
                    left_px, right_px = columns[column]
                    # Just past the rule, and no further. The inset this
                    # program uses for its own layout is four units, which at
                    # three times the size is twelve pixels and takes the first
                    # letter off a name drawn close to the line: Dev came back
                    # as Jev, Grace as Srace, Bob as nothing at all. A measured
                    # edge sits on the rule, so clearing the rule is all that
                    # is wanted.
                    left_px, right_px = columns[column]
                    left_px += max(2, int(round(scale)))
                else:
                    # Barely past the line, with _trim_rule to take the line
                    # itself off, rather than a fixed inset that grows with the
                    # picture and eats the name with it.
                    left_px = int(left * scale) + max(2, int(round(scale)))
                    right_px = int(right * scale)
                right_px = max(left_px + 1, right_px)
                bands, cell_top = (), 0
                if rows:
                    row_top, row_bottom = rows[week]
                    cell_top = row_top + int(round(2 * scale))
                    cell = image.crop((left_px, cell_top, right_px,
                                       max(cell_top + 1,
                                           row_bottom - int(round(scale)))))
                    bands = _text_bands(cell, scale)

                def band_box(index):
                    """The crop for one line of text, padded as _draw_name expects.

                    A name's topmost ink is its capital, so a crop that starts
                    CROP_ABOVE above the band puts the cap line exactly where the
                    matcher redraws it.
                    """
                    start, end = bands[index]
                    top_y = max(0, cell_top + start
                                - int(round(CROP_ABOVE * scale)))
                    return image.crop(
                        (left_px, top_y, right_px,
                         max(top_y + 1, cell_top + end + int(round(2 * scale)))))

                if column == 1:
                    # A Monday holds a supervisor above its technician. With only
                    # one line there, which of the two it is follows from where it
                    # sits: the supervisor is drawn in the upper half of the cell.
                    box = None
                    if len(bands) >= 2:
                        box = band_box(0)
                    elif len(bands) == 1 and bands[0][0] < (
                            (rows[week][1] - rows[week][0]) * 0.5):
                        box = band_box(0)
                        bands = ()
                    elif not bands and rows is None:
                        box = crop(left + INSET, top + OFF_SUP - 4, right,
                                   top + OFF_SUP + CAP_SUP + 6)
                    if box is not None:
                        # Supervisors are their own list of people: matching a
                        # Monday against the technicians would compare a name with
                        # eleven it cannot be.
                        name, confidence = _read_cell(box, known_supervisors,
                                                      CAP_SUP, scale, bold=True,
                                                      pad=PAD_SUP)
                        if name:
                            sup[day] = name
                    offset = OFF_TECH_MON
                else:
                    offset = OFF_TECH

                if rows is None:
                    box = crop(left + INSET, top + offset - 4, right,
                               top + offset + CAP_TECH + 6)
                elif bands:
                    box = band_box(len(bands) - 1)
                else:
                    continue                        # an empty cell, and nothing to read
                name, confidence = _read_cell(box, known_names, CAP_TECH, scale,
                                              pad=PAD_TECH)
                if name:
                    tech[day] = name
                    weak += confidence < 0.5
        return tech, sup, weak

    # Once to find out what has to be read, then all of it at once, then again
    # to actually read it: the second pass takes every reading from the cache
    # the first one filled, and the whole month costs one tesseract per
    # magnification instead of one per cell.
    global _PLANNING, _READINGS
    _READINGS = {}
    _PLANNING = []
    try:
        scan()
        pending = _PLANNING
    finally:
        _PLANNING = None
    if pending:
        _READINGS.update(_batch(pending))
    tech, sup, weak = scan()

    tech = _agree(tech)
    sup = _agree(sup)
    return {"year": year, "month": month, "tech": tech, "sup": sup,
            "source": "recognised", "uncertain": weak}


def _trim_rule(box):
    """Drop a ruled line standing at the left edge of a crop, if there is one.

    The inset that used to do this was a fixed distance scaled up with the
    picture, which is fine for the layout this program draws and wrong for
    everyone else's: at three times the size it reached fourteen pixels in and
    took the first letter off any name drawn close to the line. A rule is ink
    down the whole height of the crop and a letter is not, so it can be found
    instead of guessed at.
    """
    look = max(2, min(box.width // 8, int(round(box.width * 0.06))))
    if look < 1 or box.height < 4:
        return box
    grey = box.convert("L").point(lambda v: 255 if v > 110 else 0)
    columns = _pixels(grey.resize((grey.width, 1), Image.BOX))

    left = 0
    for x in range(min(look, len(columns))):
        if columns[x] > 200:            # ink nearly all the way down: a rule
            left = x + 1
    right = len(columns)
    for x in range(len(columns) - 1, max(-1, len(columns) - look - 1), -1):
        if columns[x] > 200:
            right = x
    # The line down the right of a cell is read as a letter if it is left in:
    # a four-letter name came back with a stray fifth on the end, and a
    # six-letter one as nothing at all, the reading having stopped looking
    # like a name.
    if left or right < len(columns):
        return box.crop((left, 0, max(left + 1, right), box.height))
    return box


def _read_cell(box, known_names, cap, scale, bold=False, pad=0):
    """One cell's name, by reading it and by recognising its shape.

    Reading is tried first because it needs no roster and handles a name this
    rota has never seen. Where the reading is not a name on the roster, the
    shape decides instead -- which is what rescues a calendar exported at low
    resolution, where the text is too small to read but still perfectly
    distinguishable from the other eleven possibilities.
    """
    # Read from the full cell -- clipping earlier took the last stroke off a
    # name -- at each magnification in turn.
    box = _trim_rule(box)
    readings = []
    for zoom in _zooms(box):
        text = _clean_name(_tesseract(box, zoom=zoom))
        if bold and text.isupper():
            # Supervisors are drawn in capitals here, so a reading in capitals
            # is that styling and not the name. Anything else is read as it is
            # written: title-casing it turned MacLeod into Macleod.
            text = text.title()
        readings.append(text)
    if _PLANNING is not None:
        return None, 0.0            # planning: only the requests matter here

    # Match against a crop with the grid line trimmed away, since a vertical
    # rule is ink the matcher would try to account for.
    trimmed = box.crop((0, 0, max(1, box.width - int(round(INSET_RIGHT * scale))),
                        box.height))
    for text in readings:
        resolved = _closest(text, known_names) if text else ""
        if resolved and resolved in known_names:
            return resolved, 1.0

    # A reading that looks like a name wins, whatever the resolution. The shape
    # matcher can only ever answer with a name already on the roster, so where
    # the reading is of somebody not on it -- a newcomer, or a roster half
    # typed in -- the matcher is guaranteed to be wrong and confident enough to
    # say so. It replaced one technician with another twice at export
    # resolution; guarding that by scale left the same fault at every lower
    # one, where it read a name correctly off the picture and filed the day
    # under somebody else. Measured over a
    # whole month at export resolution and at half of it, the matcher scored
    # zero on every cell whose text could be read at all, so nothing it is good
    # for is being given up here.
    # The first magnification decides while it reads something name-shaped.
    # It is the one every calendar here has been measured against, and putting
    # the alternates to a vote against it made things worse rather than better:
    # a name whose last stroke the other two dropped -- four letters read as
    # three -- lost two to one to a reading that was simply shorter. Enlarging
    # differently is a way to get an answer where there was none, not a second
    # opinion worth overriding a good one.
    if _plausible(readings[0]):
        return readings[0], 0.3

    # Nothing name-shaped at the usual size, which is where the alternates earn
    # their keep: a cell one build of tesseract returns nothing for is often
    # plain at another magnification. Here agreement does count, since there is
    # no better-founded reading to defer to.
    others = [t for t in readings[1:] if _plausible(t)]
    if others:
        import collections as _c
        text, votes = _c.Counter(others).most_common(1)[0]
        return text, 0.4 if votes > 1 else 0.25

    # Nothing that reads as a name: too small, too faint, or ink that is not
    # text. This is what the matcher is for -- it needs no legible letters, only
    # a shape to compare against the roster.
    matched, confidence = _match_name(trimmed, known_names, cap, scale, bold, pad)
    if matched and confidence >= MATCH_MARGIN:
        return matched, confidence
    # Neither read nor recognised. Better an empty cell than a name someone has
    # to notice is wrong: a gap asks to be filled, a plausible mistake does not.
    return None, 0.0


def _plausible(text):
    """Does this reading look like somebody's name rather than like noise?

    One capitalised word of letters, containing a vowel. The rubbish a
    low-resolution calendar produces falls at one of those fences: "NS Tl" and
    "y aee v vTeawe ." are several fragments, "aweay" does not start with a
    capital where the calendar drew one, and "Srr" is not pronounceable.
    """
    if not text or not 2 <= len(text) <= 20:
        return False
    letters = text.replace("-", "").replace("'", "")
    if len(letters) == 2 and letters.isalpha() and text[0].isupper():
        # Plenty of real names are two letters long. They leave no room for
        # the vowel the test below asks for, and refusing them lost every one
        # of one technician's days. Three letters do leave room, so "Srr" is
        # still turned away as the noise it is.
        return True
    return (letters.isalpha() and text[0].isupper()
            and any(v in text.lower() for v in "aeiouy"))


def _agree(assignments):
    """Let repeated readings of the same name correct each other.

    Everybody appears two or three times in a month, and a misreading is
    usually one letter and usually not repeated: a name read a letter short
    once, against the whole of it twice, is the same person, and the spelling
    seen most often is the one to keep. This is what makes reading a calendar
    cold -- with no roster to check against -- nearly as good as reading one
    with the names already known.
    """
    import collections
    import difflib

    census = collections.Counter(assignments.values())
    canonical = {}
    for name, _ in census.most_common():          # commonest first, so it wins
        if name in canonical:
            continue
        canonical[name] = name
        for other in census:
            if other in canonical:
                continue
            if difflib.SequenceMatcher(None, name.lower(), other.lower()).ratio() >= 0.75:
                canonical[other] = name
    return {day: canonical.get(name, name) for day, name in assignments.items()}


def _title_strips(image, scale):
    """Crops that might hold "OCTOBER 2026", likeliest first."""
    width, height = image.size
    strips = [image.crop((int(COLS1[0] * scale), int(2 * scale),
                          int(COLS1[-1] * scale),
                          max(int(3 * scale), int((HEADER_SEP1 - 24) * scale))))]
    above = _rules(_pixels(image.convert("L").resize((1, height), Image.BOX)))
    top = above[0] if above else int(height * 0.12)
    if top > 4:
        strips.append(image.crop((0, 0, width, top)))       # the whole heading
        strips.append(image.crop((0, 0, width // 2, top)))  # its left half
    return strips


def _parse_title(text):
    """"OCTOBER 2026" -> (2026, 10)."""
    match = re.search(r"([A-Za-z]+)\s+(\d{4})", text or "")
    if not match:
        raise Unreadable("could not read the month from the title")
    wanted = match.group(1).lower()
    for number in range(1, 13):
        if calendar.month_name[number].lower() == wanted:
            return int(match.group(2)), number
    raise Unreadable("unrecognised month name %r" % match.group(1))


def absorb(schedule, data, group_index, group_id):
    """Fold a calendar that has been read into the roster and the months.

    Names are added, never removed: a calendar from six months ago is evidence
    that somebody was on the rota then, not that anyone since has left. The
    supervisor cycle is taken in the order the Mondays run, which is the order
    it actually goes in.

    Returns what changed, so the window can say so rather than silently
    rearranging somebody's roster.
    """
    from . import roster as roster_module
    from . import store

    added_techs, added_sups, ignored = [], [], []
    exact = schedule.get("source") == "embedded"

    technicians = data["groups"][group_index]["technicians"]
    for day in sorted(schedule["tech"]):
        name = schedule["tech"][day]
        if not name or name in technicians:
            continue
        # Everything that reads as a name goes on, including somebody seen only
        # once. Requiring two sightings was tried and was worse in practice: it
        # dropped real people a low-resolution calendar had only managed to
        # recognise once, and somebody who left the company still belongs on the
        # list for the month they worked. A name too many is a row to delete; a
        # name missing is a person to notice is missing and type back in.
        if not exact and not _plausible(name):
            ignored.append(name)
            continue
        technicians.append(name)
        added_techs.append(name)

    supervisors = data["supervisors"]
    for day in sorted(schedule["sup"]):
        name = schedule["sup"][day]
        if not name or name in supervisors:
            continue
        # Supervisors take one Monday in four, so a month may hold only one
        # sighting of each and the rule above would reject them all. They are
        # held to looking like a name instead.
        if not exact and not _plausible(name):
            ignored.append(name)
            continue
        supervisors.append(name)
        added_sups.append(name)

    # Whatever was not good enough for the roster is not good enough for the
    # record either: a month kept with names nobody recognises would feed the
    # next month's spacing with people who do not exist.
    rejected = set(ignored)
    schedule = dict(schedule)
    schedule["tech"] = {d: n for d, n in schedule["tech"].items()
                        if n and n not in rejected}

    # A calendar this app exported carries the supervisors' numbers inside it,
    # so a supervisor read back off one arrives with theirs and the box should
    # not be left empty for somebody to type in again. Blanks only: a number
    # already on the roster is more current than one in a calendar from six
    # months ago, and quietly overwriting it would be the wrong way round.
    # Nothing arrives this way from a picture that had to be recognised --
    # numbers are not read off pixels -- so this fills in only what is known
    # exactly.
    numbers = schedule.get("phones") or {}
    phones = data.setdefault("phones", {})
    added_numbers = []
    for name in supervisors:
        number = numbers.get(name)
        if number and not phones.get(name) and name not in rejected:
            phones[name] = roster_module.tidy(number)
            added_numbers.append(name)

    roster_module.ensure_ids(data)
    roster_module.save(data)

    days_in_month = calendar.monthrange(schedule["year"], schedule["month"])[1]
    filled = {d: n for d, n in schedule["tech"].items() if n}
    record = {
        "year": schedule["year"], "month": schedule["month"],
        "tech": filled, "sup": {d: n for d, n in schedule["sup"].items() if n},
        "lead_supervisor": schedule.get("lead_supervisor"),
        "gap": schedule.get("gap"),
        # A calendar that could not be read in full is recorded as a tail: its
        # shift counts are not the month's, and nothing should read them as if
        # they were.
        "partial": len(filled) < days_in_month,
    }
    store.save(record, group_id)
    return {
        "technicians_added": added_techs,
        "supervisors_added": added_sups,
        "year": schedule["year"], "month": schedule["month"],
        "days": len(filled), "of": days_in_month,
        "partial": record["partial"], "source": schedule.get("source"),
        "ignored": sorted(set(ignored)),
        "numbers_added": added_numbers,
    }
