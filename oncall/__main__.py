"""Entry point.

Copyright (C) 2026 Caden DeNike. Free software under the GNU General
Public License, version 3 or later, with no warranty. See LICENSE.
"""

import sys


def selftest(report=None, strict=False):
    """Solve, draw, read back and open the window -- on this machine, in this build.

    A packaged build can be produced on a system that has never run it, so
    "it compiled" is not the same as "it works". This exercises the parts that
    depend on the machine rather than on the code: the fonts it can find, the
    text recognition it carries, the image library underneath both, and the
    parts of Qt the window needs -- which matters because the build leaves most
    of Qt out, and a plugin left out that should not have been only shows once
    there is something on screen.

    Findings go to a file as well as to the screen, because a windowed build on
    Windows has no console: printing there reaches nobody, and a check whose
    output nobody can see is a check in name only.

    `strict` fails when recognition is unavailable. A build that bundles it and
    then cannot find it would otherwise pass exactly like one that never
    intended to have it.
    """
    import pathlib
    import tempfile

    from . import importer, render, solve

    lines = []

    def say(text):
        lines.append(text)
        try:
            print(text)
        except Exception:
            pass                    # no console; the report file is the record

    def finish(code):
        if report:
            try:
                pathlib.Path(report).write_text("\n".join(lines) + "\n")
            except OSError:
                pass
        return code

    people = ["Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"]
    schedule = solve.solve(2026, 12, people, ["Sierra", "Tango"], {}, budget=5.0)
    # Numbers, so the Monday cells carry three lines of ink rather than
    # two: that is the arrangement the reader has to pick a name out of,
    # and it is worth checking on the machine that will be doing it.
    schedule["phones"] = {"Sierra": "5550142", "Tango": "555-0199"}
    if (render.dial("5555550144") != "555-555-0144"
            or render.dial("15555550144") != "555-555-0144"):
        say("FAILED: a plain number is not punctuated as a phone number")
        return finish(1)
    say("solved: gap %d, shifts %s" % (schedule["gap"],
                                       sorted(set(schedule["shifts"].values()))))

    out = pathlib.Path(tempfile.mkdtemp()) / "selftest.png"
    size = render.render(schedule, str(out), scale=4)
    say("drew: %dx%d using %s" % (size[0], size[1], render.font_file("bold")))

    exact = importer.read(str(out))
    if exact["tech"] != schedule["tech"] or exact["source"] != "embedded":
        say("FAILED: a calendar this build wrote did not read back")
        return finish(1)
    say("read back exactly from the file")

    # The numbers travel inside the picture along with everything else, and
    # folding a calendar back into a roster has to carry them across. It did
    # not: the file held them, the reader returned them, and absorbing the
    # calendar dropped them, so every phone box came up empty on a machine
    # that had just been handed a calendar with the numbers written on it.
    if exact.get("phones") != schedule["phones"]:
        say("FAILED: the numbers did not survive being written and read")
        return finish(1)
    # Absorbing writes the roster and the month to disk, so it is pointed at a
    # temporary directory first. A check has no business adding a made-up
    # December to somebody's real records.
    landed, kept = _absorbed_numbers(exact)
    # Tidied on the way in, like any other number reaching the roster, so what
    # lands is the shape the calendar draws rather than the shape it was typed.
    from . import roster as _roster
    want = {who: _roster.tidy(n) for who, n in schedule["phones"].items()}
    if landed[0] != want or sorted(landed[1]) != ["Sierra", "Tango"]:
        say("FAILED: a calendar's numbers did not reach the roster: %s, "
            "wanted %s" % (landed[0], want))
        return finish(1)
    if kept != "555-0000":
        say("FAILED: a calendar overwrote a number the roster already held")
        return finish(1)
    say("numbers: carried from the calendar, without overwriting held ones")

    # A month read off somebody else's calendar records no gap, and the file
    # says null. Every reader of these files has to cope with that; one did
    # not, and the window stopped opening at all for anyone whose history held
    # such a month. Checked here rather than by writing one into this machine's
    # own records, which a check has no business doing.
    from . import store
    mended = store._usable({"year": 2026, "month": 9, "gap": None,
                            "tech": {"1": "Alfa"}, "sup": {}})
    if mended["gap"] != 0 or 1 not in mended["tech"]:
        say("FAILED: a month recorded without a gap is not read back usably")
        return finish(1)
    say("a month recorded without a gap reads back usably")

    # Respin, in the build, on the machine it targets. It is the one feature
    # whose whole point is that it does not give the same answer twice, and a
    # build where it silently returned the same month would look like a button
    # that does nothing.
    again = solve.reroll(2026, 12, people, ["Sierra", "Tango"], {}, budget=5.0,
                         avoid=[schedule["tech"]])
    say("respin: %s, gap %d (was %d), supervisors unchanged: %s"
        % ("a different arrangement" if again["tech"] != schedule["tech"]
           else "THE SAME ARRANGEMENT", again["gap"], schedule["gap"],
           again["sup"] == schedule["sup"]))
    if again["sup"] != schedule["sup"]:
        say("FAILED: a respin moved the supervisors")
        return finish(1)

    # Trading two days, and what the trade is reported to cost. People swap
    # shifts constantly, so the arithmetic behind the Swaps tab is checked on
    # the machine it will run on rather than assumed to travel.
    first, second = sorted(schedule["tech"])[:2]
    traded = solve.swap(schedule, first, second)
    verdict = solve.review(traded, roster=people)
    swapped = (traded["tech"][first] == schedule["tech"][second]
               and traded["tech"][second] == schedule["tech"][first])
    say("swap: the %d%s and the %d%s exchanged: %s, shortest gap now %d, %d "
        "thing%s to say about it"
        % (first, "st" if first == 1 else "th", second,
           "nd" if second == 2 else "th", "yes" if swapped else "NO",
           verdict["gap"], len(verdict["problems"]) + len(verdict["tight"]),
           "" if len(verdict["problems"]) + len(verdict["tight"]) == 1 else "s"))
    if not swapped:
        say("FAILED: swapping two days did not exchange them")
        return finish(1)

    # A calendar drawn by something else arrives at whatever size it was drawn
    # at, and the one this was built for is 696 px wide -- a sixteenth of the
    # pixels the app's own export has. That is where recognition is hardest and
    # where a difference between one machine's tesseract and another's shows
    # up, so the check reads a small one too, with nothing known in advance,
    # exactly as someone uploading an old schedule would.
    small = pathlib.Path(tempfile.mkdtemp()) / "small.png"
    render.render(schedule, str(small), scale=1)

    # And a calendar in somebody else's style: drawn dark on light, ruled,
    # names centred, headed differently. Nothing about it matches what this
    # program draws, which is the point -- a reader that only manages its own
    # output is no use for the calendar somebody is migrating from.
    foreign = pathlib.Path(tempfile.mkdtemp()) / "foreign.png"
    _draw_foreign(str(foreign), schedule)
    try:
        other = importer.read(str(foreign), known_names=[], known_supervisors=[],
                              prefer_pixels=True,
                              expect=(schedule["year"], schedule["month"]))
    except importer.Unreadable as exc:
        say("a calendar in another style could not be read: %s" % exc)
    else:
        hits = sum(1 for day, name in schedule["tech"].items()
                   if other["tech"].get(day) == name)
        say("another program's layout, nothing known: %d of %d days"
            % (hits, len(schedule["tech"])))
        if hits < len(schedule["tech"]) * 0.8:
            say("FAILED: a calendar in another style is barely readable here")
            return finish(1)

    code = 0
    try:
        cold = importer.read(str(small), known_names=[], known_supervisors=[],
                             prefer_pixels=True)
    except importer.Unreadable:
        pass                        # reported below by the 4x read
    else:
        right = sum(1 for day, name in schedule["tech"].items()
                    if cold["tech"].get(day) == name)
        sups = sum(1 for day, name in schedule["sup"].items()
                   if cold["sup"].get(day) == name)
        say("from a 1x picture with nothing known: %d of %d days, %d of %d "
            "supervisors" % (right, len(schedule["tech"]), sups,
                             len(schedule["sup"])))
        if right < len(schedule["tech"]) * 0.5:
            say("FAILED: a small calendar is barely readable on this machine")
            code = 1

    try:
        seen = importer.read(str(out), known_names=people,
                             known_supervisors=["Sierra", "Tango"],
                             prefer_pixels=True)
    except importer.Unreadable as exc:
        say("no recognition in this build: %s" % exc)
        code = 1 if strict else 0
    else:
        hits = sum(1 for day, name in schedule["tech"].items()
                   if seen["tech"].get(day) == name)
        total = len(schedule["tech"])
        say("recognised %d of %d days from the picture" % (hits, total))
        if hits < total * 0.9:
            say("FAILED: recognition is too poor to rely on")
            code = 1
    return finish(max(code, _open_window(say)))


def _draw_foreign(path, schedule):
    """A calendar of the same month drawn the way another program might.

    Dark ink on a light page, a heading of its own, weekday labels, names
    centred in the cell and the day number in the corner -- none of it the
    layout this program uses.
    """
    import calendar as _cal

    from PIL import Image, ImageDraw, ImageFont

    from . import render

    year, month = schedule["year"], schedule["month"]
    width, height, top = 900, 640, 70
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    face = ImageFont.truetype(render.font_file("bold"), 22)
    small = ImageFont.truetype(render.font_file("regular"), 13)
    draw.text((14, 8), "%s %d" % (_cal.month_name[month], year), font=face,
              fill="black")
    for index, name in enumerate(("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")):
        draw.text((index * width / 7.0 + 8, 44), name, font=small, fill="black")

    grid = render.month_grid(year, month)
    rows = len(grid)
    step = (height - top) / float(rows)
    for week, row in enumerate(grid):
        for column, (day, inside) in enumerate(row):
            if not inside:
                continue
            x0, x1 = column * width / 7.0, (column + 1) * width / 7.0
            y0 = top + week * step
            draw.text((x0 + 6, y0 + 4), str(day), font=small, fill="black")
            for offset, who in ((0.34, schedule["sup"].get(day)),
                                (0.62, schedule["tech"].get(day))):
                if not who:
                    continue
                wide = draw.textlength(who, font=small)
                draw.text(((x0 + x1) / 2 - wide / 2, y0 + step * offset), who,
                          font=small, fill="black")
    for week in range(rows + 1):
        y = top + week * step
        draw.line([0, y, width, y], fill="black")
    for column in range(8):
        x = min(column * width / 7.0, width - 1)
        draw.line([x, top, x, height], fill="black")
    image.save(path)


def _open_window(say):
    """Open the real window, draw it once, and close it again.

    Declines where there is no display, and has to decide that before asking
    Qt: with nowhere to draw, Qt ends the process rather than raise an error.
    """
    import os

    if (sys.platform.startswith("linux") and not os.environ.get("QT_QPA_PLATFORM")
            and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))):
        say("window: skipped, no display to open it on")
        return 0
    try:
        from PySide6 import QtWidgets

        from . import __author__, __version__
        from . import gui
    except ImportError as exc:
        say("FAILED: the window's toolkit is missing: %s" % exc)
        return 1

    app = (QtWidgets.QApplication.instance()
           or QtWidgets.QApplication(["oncall-scheduler"]))
    window = gui.Window()
    window.show()
    app.processEvents()
    shot = window.grab()

    # The two toolbar buttons, pressed for real. Clear runs last because it
    # empties the roster this machine is carrying -- which on a fresh machine
    # is empty anyway, and on anyone's own machine is not what a self-check
    # should touch, so it goes no further than checking the button exists.
    window.generate(respin=True)
    if window.solver is not None:
        window.solver.wait()
    for _ in range(20):
        app.processEvents()
    say("respin button: %s"
        % ("re-solved" if window.schedule else "no schedule (empty roster)"))
    # Clear is checked for, not pressed: it empties the roster on whatever
    # machine it runs on, and a self-check has no business doing that to
    # somebody's own.
    tabs = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    say("tabs: %s" % ", ".join(tabs))
    if "Swaps" not in tabs or "History" not in tabs:
        say("FAILED: a tab is missing: %s" % ", ".join(tabs))
        return 1
    missing = [name for name in ("respin_button", "clear_button", "export_button")
               if getattr(window, name, None) is None]
    if missing:
        say("FAILED: the toolbar is missing %s" % ", ".join(missing))
        return 1
    say("toolbar: generate, respin, clear and export all present")

    # The licence asks that a program say what it is and what it costs
    # somewhere a person can find it, so a build that lost the About button,
    # or shows one that says nothing, is a build that should not go out.
    about = [b for b in window.findChildren(QtWidgets.QPushButton)
             if b.text() == "About"]
    if not about:
        say("FAILED: no About button")
        return 1
    notice = _about_text(window)
    for wanted in ("General Public License", __author__, __version__):
        if wanted not in notice:
            say("FAILED: the About notice does not mention %r" % wanted)
            return 1
    say("about: names the author, the version and the licence")

    # Every number in one shape, and a number that does not move while the
    # name it belongs to stands still. Rebuilding the rows deletes the
    # editors, a deleted editor reports itself with the row number it was
    # built with, and that report used to carry the number off to a name the
    # roster does not have -- leaving a supervisor drawn on the calendar with
    # no number under them.
    from . import roster as roster_module
    shapes = {roster_module.tidy(n) for n in
              ("5555550144", "15555550144", "(555) 555-0144",
               "555.555.0144")}
    if shapes != {"555-555-0144"}:
        say("FAILED: the same number typed four ways is kept four ways: %s"
            % sorted(shapes))
        return finish(1)
    people, numbers = (["Alfa", "Bravo"],
                       {"Alfa": "555-0001", "Bravo": "555-0002"})
    rows = gui.NameList(phones=numbers)
    rows.set_names(people)
    rows._building = True
    rows._commit(1, "Charlie")         # a row reporting itself mid-rebuild
    rows._building = False
    if numbers.get("Bravo") != "555-0002" or "Charlie" in numbers:
        say("FAILED: a number moved to a name the roster does not have: %s"
            % numbers)
        return finish(1)
    rows._commit(1, "Charlie")         # and a real rename still carries it
    if numbers.get("Charlie") != "555-0002":
        say("FAILED: renaming somebody lost their number: %s" % numbers)
        return finish(1)
    say("numbers: one shape, and tied to the person rather than the row")

    if window.solver is not None:
        window.solver.wait()        # a thread left running takes the process down
    window.close()
    say("window: %dx%d on %s, style %s"
        % (shot.width(), shot.height(), app.platformName(), app.style().name()))
    return 1 if shot.isNull() else 0




def _absorbed_numbers(calendar_read):
    """Fold a read calendar into two throwaway rosters, on a throwaway disk.

    Returns what an empty roster ended up with, and what a roster that already
    held a number for Sierra still holds.
    """
    import pathlib
    import shutil
    import tempfile

    from . import importer
    from . import roster as roster_module
    from . import store

    def fresh(phones):
        return {"supervisors": [], "phones": dict(phones), "inactive": [],
                "groups": [{"id": "selftest", "name": "Selftest",
                            "technicians": []}]}

    room = pathlib.Path(tempfile.mkdtemp(prefix="oncall-selftest-"))
    was_roster, was_months = roster_module.ROSTER, store.MONTHS
    roster_module.ROSTER, store.MONTHS = room / "roster.json", room / "months"
    try:
        blank = fresh({})
        added = importer.absorb(calendar_read, blank, 0, "selftest")["numbers_added"]
        held = fresh({"Sierra": "555-0000"})
        importer.absorb(calendar_read, held, 0, "selftest")
        return (blank["phones"], added), held["phones"]["Sierra"]
    finally:
        roster_module.ROSTER, store.MONTHS = was_roster, was_months
        shutil.rmtree(room, ignore_errors=True)


def _about_text(window):
    """What the About box would say, without stopping to show it."""
    from PySide6 import QtWidgets

    said = []
    original = QtWidgets.QMessageBox.exec
    QtWidgets.QMessageBox.exec = lambda box: said.append(box.text())
    try:
        window._about()
    finally:
        QtWidgets.QMessageBox.exec = original
    return said[0] if said else ""


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("-h", "--help"):
        print("usage: oncall-scheduler             open the window\n"
              "       oncall-scheduler --version   print the version\n"
              "       oncall-scheduler --selftest  check this build works here")
        return 0
    if argv and argv[0] == "--version":
        from . import __version__
        print(__version__)
        return 0
    if argv and argv[0] == "--selftest":
        # A path to write the findings to, since a windowed build has nowhere
        # to print them; --strict makes absent recognition a failure.
        report = next((a for a in argv[1:] if not a.startswith("-")), None)
        return selftest(report, strict="--strict" in argv[1:])
    try:
        from .gui import main as gui_main
    except ImportError as exc:
        print("Could not start the window: %s" % exc, file=sys.stderr)
        print("Install PySide6 and Pillow (pip install PySide6-Essentials Pillow).",
              file=sys.stderr)
        return 1
    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
