"""The window, in Qt, so the same application runs on Windows and on Linux.

GTK gave a better-looking window on Linux and a packaging problem everywhere
else: bundling it for Windows means shipping its DLLs, typelibs, pixbuf loaders
and icon themes, and re-solving that every time any of them moves. Qt is built
to be shipped, so one toolkit serves both platforms and one binary can be built
for each from the same tree.

Nothing about the program changed with it. This file is the window; the rota is
still solved in solve.py, recorded in store.py and drawn in render.py.

Copyright (C) 2026 Caden DeNike. Free software under the GNU General
Public License, version 3 or later, with no warranty. See LICENSE.
"""

import calendar
import datetime
import pathlib
import sys
import tempfile

from PySide6 import QtCore, QtGui, QtWidgets

from . import __author__, __version__
from . import importer, render, roster, solve, store, timeoff

PREVIEW_SCALE = 2
EXPORT_SCALE = 4
TAIL_DAYS = 12

STYLE = """
QGroupBox {
    font-weight: 600;
    border: 1px solid palette(mid);
    border-radius: 8px;
    margin-top: 18px;
    padding: 12px 10px 10px 10px;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
QPushButton#primary { font-weight: 600; padding: 6px 18px; }
QLabel#status { color: palette(mid); }
QLabel#preview { border: 1px solid palette(mid); border-radius: 6px; }
"""


class Preview(QtWidgets.QLabel):
    """The calendar, drawn as large as the width allows.

    A label handed a scaled pixmap keeps whatever height it was given, which
    left the calendar a postage stamp at the foot of a tall window while the
    space around it went unused. This one asks for the height its picture
    actually needs at the width it has been given, so the calendar fills the
    page and stays in proportion at any window size.
    """

    def __init__(self):
        super().__init__()
        self._source = None
        self._drawn = None              # the size the picture was drawn at
        self.setObjectName("preview")
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setMinimumHeight(280)
        # The label takes the room it is given and never asks for more. A
        # picture that asks for room is a picture that changes the layout,
        # which resizes the label, which rescales the picture: inside a group
        # box -- which does not carry a height-for-width through -- the two
        # never settle and the window stops painting. The room it gets is set
        # by the window instead, in resizeEvent below.
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored,
                           QtWidgets.QSizePolicy.Ignored)

    def show_calendar(self, path):
        source = QtGui.QPixmap(str(path))
        self._source = None if source.isNull() else source
        self._drawn = None
        self.updateGeometry()
        self._draw()

    def clear_calendar(self):
        self._source = None
        self._drawn = None
        self.clear()
        self.updateGeometry()

    def room_for(self, width, spare):
        """How tall to stand, given the width it has and the room going."""
        if self._source is None or not self._source.width():
            return 280
        tall = round(width * self._source.height() / self._source.width())
        return max(280, min(tall, spare))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._draw()

    def _draw(self):
        # Only when the size has actually changed. Setting a pixmap changes
        # what the label asks for, which lays the page out again, which resizes
        # the label, which would draw it again: left unguarded the two chase
        # each other and the window never finishes painting.
        if self._source is None or self.size() == self._drawn:
            return
        self._drawn = self.size()
        self.setPixmap(self._source.scaled(self.size(),
                                           QtCore.Qt.KeepAspectRatio,
                                           QtCore.Qt.SmoothTransformation))


class NameList(QtWidgets.QWidget):
    """An editable list of names: rename, remove, add, and optionally reorder.

    Blank is how a new row starts and how a row is deleted: a name is a person,
    and an empty one is not, so clearing a row removes it rather than leaving
    somebody nameless on the rota.
    """

    changed = QtCore.Signal()

    def __init__(self, ordered=False, add_label="Add", phones=None):
        super().__init__()
        self.ordered = ordered
        self.add_label = add_label
        # When given, a {name: number} mapping edited alongside the names: the
        # number sits beside the name it belongs to, which is where anyone
        # looking for it expects it.
        self.phones = phones
        self.names = []
        self._building = False
        self.rows = QtWidgets.QVBoxLayout(self)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(4)

    def set_names(self, names):
        """Adopt a list of names -- by reference, deliberately.

        Every edit below mutates this list in place, so the caller must pass
        the list the roster actually holds, never a copy and never a literal.
        Pass `roster["supervisors"]`, not `[]` or `list(...)`: a detached list
        keeps working, keeps looking right on screen, and silently saves
        nothing.
        """
        self.names = names
        self._rebuild()

    def _rebuild(self):
        self._building = True
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for index, name in enumerate(self.names):
            row = QtWidgets.QWidget()
            line = QtWidgets.QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)

            edit = QtWidgets.QLineEdit(name)
            edit.setPlaceholderText("Name")
            edit.editingFinished.connect(
                lambda i=index, e=edit: self._commit(i, e.text().strip()))
            line.addWidget(edit, 1)

            if self.phones is not None:
                number = QtWidgets.QLineEdit(roster.tidy(self.phones.get(name, "")))
                number.setPlaceholderText("Phone")
                number.setMaximumWidth(150)
                number.editingFinished.connect(
                    lambda i=index, e=number: self._commit_phone(i, e.text().strip()))
                line.addWidget(number)

            if self.ordered:
                for arrow, delta, tip in (("▲", -1, "Earlier in the cycle"),
                                          ("▼", 1, "Later in the cycle")):
                    button = QtWidgets.QToolButton()
                    button.setText(arrow)
                    button.setToolTip(tip)
                    button.setEnabled(0 <= index + delta < len(self.names))
                    button.clicked.connect(
                        lambda _=False, i=index, d=delta: self._move(i, d))
                    line.addWidget(button)

            remove = QtWidgets.QToolButton()
            remove.setText("✕")
            remove.setToolTip("Remove from the rota")
            remove.clicked.connect(lambda _=False, i=index: self._remove(i))
            line.addWidget(remove)
            self.rows.addWidget(row)

        add = QtWidgets.QPushButton("＋  " + self.add_label)
        add.setFlat(True)
        add.clicked.connect(self._add)
        self.rows.addWidget(add)
        self._building = False

    def _commit(self, index, text):
        # Nothing before this line. Rebuilding the rows deletes the editors,
        # and an editor that had focus reports itself on the way out with the
        # row number it was built with -- which by then may mean somebody else,
        # or nobody. Every one of those is ignored here. Moving a number above
        # this guard, where it used to be, meant such a report carried the
        # number off to a name the roster does not have while leaving the name
        # it came from untouched: the calendar then drew that supervisor with
        # no number at all, and nothing on screen said why.
        if self._building or not 0 <= index < len(self.names):
            return
        if text == self.names[index]:
            return
        if text:
            if (self.phones is not None and self.names[index] in self.phones):
                # The number belongs to the person, not to the spelling.
                self.phones[text] = self.phones.pop(self.names[index])
            self.names[index] = text
        else:
            if self.phones is not None:
                self.phones.pop(self.names[index], None)
            del self.names[index]
        self.changed.emit()
        self._rebuild()

    def _commit_phone(self, index, number):
        if self._building or not 0 <= index < len(self.names):
            return
        name = self.names[index]
        if not name or self.phones.get(name, "") == number:
            return
        if number:
            self.phones[name] = roster.tidy(number)
        else:
            self.phones.pop(name, None)
        self.changed.emit()

    def _move(self, index, delta):
        target = index + delta
        if not 0 <= target < len(self.names):
            return
        self.names[index], self.names[target] = self.names[target], self.names[index]
        self.changed.emit()
        self._rebuild()

    def _remove(self, index):
        if self.phones is not None:
            # Their number goes with them. Left behind it is invisible -- there
            # is no row to show it on -- and it would attach itself to the next
            # person who happens to have the same name.
            self.phones.pop(self.names[index], None)
        del self.names[index]
        self.changed.emit()
        self._rebuild()

    def _add(self):
        # Blank, never pre-named: a placeholder that has to be typed over is
        # worse than an empty box, and "New technician" ends up on a calendar.
        self.names.append("")
        self._rebuild()
        edits = self.findChildren(QtWidgets.QLineEdit)
        if edits:
            edits[-1].setFocus()


class Solver(QtCore.QThread):
    """Solving off the UI thread: a hard month can take seconds."""

    done = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, year, month, techs, sups, carry, away, avoid=None):
        super().__init__()
        self.args = (year, month, techs, sups, carry, away, avoid)

    def run(self):
        year, month, techs, sups, carry, away, avoid = self.args
        try:
            if avoid is None:
                schedule = solve.solve(year, month, techs, sups, carry,
                                       unavailable=away)
            else:
                schedule = solve.reroll(year, month, techs, sups, carry,
                                        unavailable=away, avoid=avoid)
            self.done.emit(schedule)
        except solve.Unsolvable as exc:
            self.failed.emit(str(exc))
        except Exception as exc:                     # never leave it spinning
            self.failed.emit("%s: %s" % (type(exc).__name__, exc))


class Reader(QtCore.QThread):
    """Reading a calendar off a picture, away from the window.

    Thirty-odd cells each handed to text recognition takes seconds, and on the
    UI thread that is a window which stops answering and gets offered up to be
    killed.
    """

    done = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, path, known, supervisors, expect=None):
        super().__init__()
        self.args = (path, known, supervisors, expect)

    def run(self):
        path, known, supervisors, expect = self.args
        try:
            self.done.emit(importer.read(path, known_names=known,
                                         known_supervisors=supervisors,
                                         expect=expect))
        except importer.Unreadable as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit("%s: %s" % (type(exc).__name__, exc))


class TimeOffDialog(QtWidgets.QDialog):
    """Book a person off for a day or a span of them."""

    def __init__(self, parent, techs):
        super().__init__(parent)
        self.setWindowTitle("Book time off")
        layout = QtWidgets.QVBoxLayout(self)

        form = QtWidgets.QFormLayout()
        self.person = QtWidgets.QComboBox()
        self.person.addItems(techs)
        form.addRow("Technician", self.person)
        layout.addLayout(form)

        dates = QtWidgets.QHBoxLayout()
        self.first = QtWidgets.QCalendarWidget()
        self.last = QtWidgets.QCalendarWidget()
        for label, widget in (("First day", self.first), ("Last day", self.last)):
            column = QtWidgets.QVBoxLayout()
            caption = QtWidgets.QLabel(label)
            caption.setStyleSheet("font-weight: 600;")
            column.addWidget(caption)
            column.addWidget(widget)
            dates.addLayout(column)
        layout.addLayout(dates)
        layout.addWidget(QtWidgets.QLabel(
            "For a single day, pick the same date in both."))

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("Book")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_range(self):
        start = self.first.selectedDate().toPython()
        end = self.last.selectedDate().toPython()
        return self.person.currentText(), min(start, end), max(start, end)


class TailDialog(QtWidgets.QDialog):
    """The closing days of a month that was scheduled before this app existed.

    Only the tail, because only the tail matters: the spacing rule looks back a
    handful of days, and asking for a whole month somebody already worked would
    be asking for typing nobody will do.
    """

    def __init__(self, parent, year, month, techs, sups, existing):
        super().__init__(parent)
        self.setWindowTitle("%s %d" % (calendar.month_name[month], year))
        self.techs = ["—"] + techs
        self.sups = ["—"] + sups
        days = calendar.monthrange(year, month)[1]

        outer = QtWidgets.QVBoxLayout(self)
        outer.addWidget(QtWidgets.QLabel(
            "Who worked the last days. Leave a day blank if you do not "
            "remember it; only the days filled in constrain the new month."))

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(inner)
        self.picks = {}
        for day in range(max(1, days - TAIL_DAYS + 1), days + 1):
            weekday = calendar.day_name[calendar.weekday(year, month, day)][:3]
            box = QtWidgets.QComboBox()
            box.addItems(self.techs)
            known = existing.get("tech", {}).get(day)
            if known in techs:
                box.setCurrentIndex(self.techs.index(known))
            form.addRow("%d %s" % (day, weekday), box)
            self.picks[day] = box
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        self.supervisor = QtWidgets.QComboBox()
        self.supervisor.addItems(self.sups)
        for name in (existing.get("sup") or {}).values():
            if name in sups:
                self.supervisor.setCurrentIndex(self.sups.index(name))
        tail_form = QtWidgets.QFormLayout()
        tail_form.addRow("Last Monday's supervisor", self.supervisor)
        outer.addLayout(tail_form)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def result_tail(self):
        tail = {day: box.currentText() for day, box in self.picks.items()
                if box.currentIndex() > 0}
        sup = (self.supervisor.currentText()
               if self.supervisor.currentIndex() > 0 else None)
        return tail, sup


class Window(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("On-Call Scheduler")
        self.resize(1000, 820)

        self.roster = roster.load()
        self.group_index = 0
        self.schedule = None
        self.solver = None
        self.avoid = None
        # Arrangements already shown for the month in front of us, so Respin
        # moves on rather than circling back onto one just seen.
        self.seen = []
        self.seen_key = None
        # The month being traded around on the Swaps tab, and what it was when
        # it was loaded.
        self.edit = None
        self.edit_from = None
        self.edit_source = ""
        self.swap_reader = None
        self._preview = pathlib.Path(tempfile.mkdtemp(prefix="oncall-")) / "p.png"

        bar = self.addToolBar("Actions")
        bar.setMovable(False)
        bar.addWidget(self._button("Generate", lambda: self.generate(),
                                   primary=True))
        # Generating twice gives the same answer -- the solver is deterministic,
        # which is what makes a schedule defensible. Respin is the way to ask
        # for a different one: same month, same rules, same fairness, the
        # technicians arranged differently.
        self.respin_button = self._button("Respin",
                                          lambda: self.generate(respin=True))
        self.respin_button.setToolTip("Re-roll the technicians. The supervisor "
                                      "cycle is not touched.")
        self.respin_button.setEnabled(False)
        bar.addWidget(self.respin_button)
        self.clear_button = self._button("Clear everyone",
                                         lambda: self._confirm_clear())
        bar.addWidget(self.clear_button)
        spacer = QtWidgets.QWidget()
        spacer.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                             QtWidgets.QSizePolicy.Preferred)
        bar.addWidget(spacer)
        self.export_button = self._button("Export PNG…", self.export)
        self.export_button.setEnabled(False)
        bar.addWidget(self.export_button)
        # Who wrote it, what it costs, and where the source is. A program under
        # this licence is asked to say so somewhere a person can find it, and a
        # button on the bar is where a person looks.
        bar.addWidget(self._button("About", self._about))

        self.tabs = QtWidgets.QTabWidget()
        # Each tab is built guardedly. Building happens before anything is on
        # screen, so a tab that throws is the difference between an app and a
        # process that starts, prints nothing a windowed build can show, and
        # exits -- which is exactly what a month recorded with no gap did to
        # the history.
        for title, build in (("Schedule", self._schedule_tab),
                             ("Time off", self._timeoff_tab),
                             ("Swaps", self._swaps_tab),
                             ("History", self._history_tab)):
            try:
                self.tabs.addTab(self._scrolled(build()), title)
            except Exception as exc:      # noqa: BLE001 - the window matters more
                print("%s tab failed: %s: %s" % (title, type(exc).__name__, exc),
                      file=sys.stderr)
                broken = QtWidgets.QLabel("This tab could not be built:\n"
                                          "%s: %s" % (type(exc).__name__, exc))
                broken.setWordWrap(True)
                self.tabs.addTab(broken, title)
        self.setCentralWidget(self.tabs)
        self.setStyleSheet(STYLE)
        self.statusBar().showMessage("Ready")

        QtCore.QTimer.singleShot(0, self.generate)

    # -- building ------------------------------------------------------------

    def _scrolled(self, page):
        """A tab that can be scrolled, because tabs outgrow the window.

        The schedule alone asks for 1270 pixels -- month, roster, groups and
        the calendar under them -- in a window eight hundred tall, and a
        history grows a line per month worked. Without this the surplus is
        simply unreachable: no bar, no wheel, nothing, which reads as an app
        that has lost half its controls rather than one that needs a scroll.
        """
        area = QtWidgets.QScrollArea()
        area.setWidget(page)
        area.setWidgetResizable(True)        # the page follows the width
        area.setFrameShape(QtWidgets.QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        return area

    def resizeEvent(self, event):
        """Give the calendar the room the window can spare.

        Set from here rather than asked for by the picture, so that growing the
        window enlarges the calendar without the picture and the layout chasing
        each other.
        """
        super().resizeEvent(event)
        self._size_previews()

    def _size_previews(self):
        """Hand every calendar on screen the room the window can spare."""
        for shot in self.findChildren(Preview):
            shot.setMinimumHeight(shot.room_for(max(1, shot.width()),
                                                int(self.height() * 0.78)))

    def _about(self):
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("About On-Call Scheduler")
        box.setTextFormat(QtCore.Qt.RichText)
        box.setText(
            "<b>On-Call Scheduler %s</b>"
            "<p>Copyright \u00a9 2026 %s.</p>"
            "<p>Free software under the "
            "<a href='https://www.gnu.org/licenses/gpl-3.0.html'>GNU General "
            "Public License, version 3 or later</a>. It comes with absolutely "
            "no warranty. You may pass it on and change it, so long as the "
            "people you pass it to get the same freedom and the same source.</p>"
            "<p>A release carries other people's work as well -- Qt, Pillow, "
            "and on Windows the text recognition and the libraries under it. "
            "THIRD-PARTY-NOTICES, beside the download, says what and under "
            "which licence.</p>"
            "<p><a href='https://github.com/cdenike/oncall-scheduler'>"
            "github.com/cdenike/oncall-scheduler</a></p>"
            % (__version__, __author__))
        box.exec()

    def _button(self, text, slot, primary=False):
        button = QtWidgets.QPushButton(text)
        if primary:
            button.setObjectName("primary")
        button.clicked.connect(slot)
        return button

    def _schedule_tab(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)

        month_box = QtWidgets.QGroupBox("Month")
        row = QtWidgets.QHBoxLayout(month_box)
        # A rota can only be worked forwards, so months already past are not
        # offered and the year cannot be wound below this one.
        today = datetime.date.today()
        self.floor = (today.year, today.month)
        self.month_combo = QtWidgets.QComboBox()
        self.year_spin = QtWidgets.QSpinBox()
        self.year_spin.setRange(self.floor[0], 2099)
        self.year_spin.valueChanged.connect(lambda *_: self._sync_months())
        row.addWidget(QtWidgets.QLabel("Schedule for"))
        row.addWidget(self.month_combo)
        row.addWidget(self.year_spin)
        row.addStretch(1)
        row.addWidget(self._button("Upload a calendar…", self.upload))
        self.tail_button = self._button("Enter last month's tail…", self.enter_tail)
        self.tail_button.setVisible(False)
        row.addWidget(self.tail_button)
        layout.addWidget(month_box)

        year, month = self._next_unsolved()
        self.year_spin.setValue(year)
        self._sync_months(month)

        self.status = QtWidgets.QLabel("Not generated yet")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        sup_box = QtWidgets.QGroupBox("Supervisors — Mondays only, in this order")
        sup_layout = QtWidgets.QVBoxLayout(sup_box)
        self.sup_list = NameList(ordered=True, add_label="Add a supervisor",
                                 phones=self.roster.setdefault("phones", {}))
        self.sup_list.set_names(self.roster["supervisors"])
        self.sup_list.changed.connect(self._roster_changed)
        sup_layout.addWidget(self.sup_list)
        layout.addWidget(sup_box)

        tech_box = QtWidgets.QGroupBox("Technicians — each tab is a rota of its own")
        tech_layout = QtWidgets.QVBoxLayout(tech_box)
        self.group_tabs = QtWidgets.QTabWidget()
        self.group_tabs.currentChanged.connect(self._group_changed)
        add_group = QtWidgets.QToolButton()
        add_group.setText("＋")
        add_group.setToolTip("Add a group")
        add_group.clicked.connect(self._add_group)
        self.group_tabs.setCornerWidget(add_group)
        tech_layout.addWidget(self.group_tabs)
        layout.addWidget(tech_box)
        self._rebuild_groups()

        preview_box = QtWidgets.QGroupBox("Calendar")
        preview_layout = QtWidgets.QVBoxLayout(preview_box)
        self.preview = Preview()
        preview_layout.addWidget(self.preview)
        layout.addWidget(preview_box, 1)
        return page

    def _timeoff_tab(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        self.timeoff_box = QtWidgets.QGroupBox("Time off")
        self.timeoff_layout = QtWidgets.QVBoxLayout(self.timeoff_box)
        layout.addWidget(self.timeoff_box)
        layout.addStretch(1)
        self._rebuild_timeoff()
        return page

    # -- swapping days -------------------------------------------------------

    def _swaps_tab(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        self.swaps_box = QtWidgets.QGroupBox("Trading days")
        self.swaps_layout = QtWidgets.QVBoxLayout(self.swaps_box)
        layout.addWidget(self.swaps_box)
        self._rebuild_swaps()
        return page

    def _copy_schedule(self, schedule):
        copy = dict(schedule)
        copy["tech"] = dict(schedule["tech"])
        copy["sup"] = dict(schedule.get("sup", {}))
        return copy

    def _swap_context(self):
        """Time off and last month, so a trade is judged against both."""
        if not self.edit:
            return {}, {}
        group = self._group_id()
        year, month = self.edit["year"], self.edit["month"]
        sups = roster.active_supervisors(self.roster)
        return (timeoff.for_month(group, year, month),
                store.carry_in(year, month, sups, group))

    def _rebuild_swaps(self):
        """Where days get traded, and what the trade costs is spelled out.

        The schedule is not editable on the Schedule tab, and that is
        deliberate: the constraints interact, and a month rearranged by hand is
        how somebody ends up working either side of the first. But people trade
        shifts constantly, and a rota that cannot take that is one people work
        around instead of with. So it is allowed here, and nothing about it is
        silent -- every rule it bends is named before it is kept.
        """
        layout = self.swaps_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    inner = item.layout().takeAt(0)
                    if inner.widget():
                        inner.widget().deleteLater()

        header = QtWidgets.QHBoxLayout()
        if self.edit:
            report = solve.review(self.edit, *self._swap_context(),
                                  roster=roster.active_technicians(
                                      self.roster, self.group_index))
            spread = sorted(set(report["shifts"].values()))
            text = ("<b>%s %d — %s</b><br>%d days between anyone's shifts · "
                    "%s shifts each"
                    % (calendar.month_name[self.edit["month"]],
                       self.edit["year"], self.edit_source, report["gap"],
                       " or ".join(str(n) for n in spread) or "none"))
        else:
            text = ("<b>Nothing loaded yet</b><br>Generate a month, open a "
                    "calendar, or take one from the History tab")
        caption = QtWidgets.QLabel(text)
        caption.setWordWrap(True)
        header.addWidget(caption, 1)
        note = QtWidgets.QLabel(
            "Swapping two days changes this month as it stands: the calendar "
            "below is redrawn as you go, and what the trade costs is spelled "
            "out under it. Nothing leaves this tab until you export — and "
            "where a month has already been given out as a picture, that "
            "picture can be brought up to date in place rather than saved "
            "again somewhere new.")
        note.setWordWrap(True)
        note.setObjectName("status")
        take = self._button("Use the one on screen", self._swap_take)
        take.setEnabled(self.schedule is not None)
        header.addWidget(take)
        header.addWidget(self._button("Open a calendar…", self._swap_open))
        layout.addLayout(header)
        layout.addWidget(note)

        if not self.edit:
            return

        days = sorted(self.edit["tech"])
        labels = ["%d — %s" % (day, self.edit["tech"][day] or "nobody")
                  for day in days]
        people = sorted({n for n in self.edit["tech"].values() if n}
                        | set(roster.active_technicians(self.roster,
                                                        self.group_index)))

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Swap"))
        first = QtWidgets.QComboBox(); first.addItems(labels)
        second = QtWidgets.QComboBox(); second.addItems(labels)
        if len(labels) > 1:
            second.setCurrentIndex(1)
        row.addWidget(first, 1)
        row.addWidget(QtWidgets.QLabel("with"))
        row.addWidget(second, 1)
        swap = self._button("Swap", lambda: self._swap_days(
            days[first.currentIndex()], days[second.currentIndex()]),
            primary=True)
        row.addWidget(swap)
        layout.addLayout(row)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Give"))
        which = QtWidgets.QComboBox(); which.addItems(labels)
        whom = QtWidgets.QComboBox(); whom.addItems(people or ["nobody"])
        row.addWidget(which, 1)
        row.addWidget(QtWidgets.QLabel("to"))
        row.addWidget(whom, 1)
        give = self._button("Give", lambda: self._give_day(
            days[which.currentIndex()], people[whom.currentIndex()]))
        give.setEnabled(bool(people))
        row.addWidget(give)
        layout.addLayout(row)

        changed = self.edit["tech"] != (self.edit_from or {}).get("tech")
        if changed:
            was = solve.review(self.edit_from, *self._swap_context(),
                               roster=people)
            now = solve.review(self.edit, *self._swap_context(), roster=people)
            moved = [d for d in days
                     if self.edit["tech"][d] != self.edit_from["tech"][d]]
            lines = ["<b>%d day%s changed hands</b> — %s"
                     % (len(moved), "" if len(moved) == 1 else "s",
                        ", ".join("the %s is now %s"
                                  % (solve._ordinal(d),
                                     self.edit["tech"][d] or "nobody")
                                  for d in moved[:4])),
                     "Shortest gap between anyone's shifts: <b>%d day%s</b>, "
                     "where it was %d" % (now["gap"],
                                          "" if now["gap"] == 1 else "s",
                                          was["gap"])]
            lines += ["⚠ %s" % problem for problem in now["problems"]]
            lines += now["tight"][:4]
            if not now["problems"]:
                lines.append("No rule is broken by this: everyone is still "
                             "covered, nobody is on a day they are away, and "
                             "the weekend share holds.")
        else:
            lines = ["Nothing has been traded yet."]
        effect = QtWidgets.QLabel("<br>".join(lines))
        effect.setWordWrap(True)
        effect.setObjectName("status")
        layout.addWidget(effect)

        row = QtWidgets.QHBoxLayout()
        undo = self._button("Undo", self._swap_undo)
        undo.setEnabled(changed)
        row.addWidget(undo)
        row.addStretch(1)
        already = self.edit.get("exported")
        if already and pathlib.Path(already).exists():
            name = pathlib.Path(already).name
            update = self._button("Update %s" % name,
                                  lambda w=already: self._swap_update(w))
            update.setToolTip("Rewrites that file where it stands, so whoever "
                              "has it has the change")
            row.addWidget(update)
        row.addWidget(self._button("Export PNG…", self._swap_export,
                                   primary=True))
        layout.addLayout(row)

        preview = Preview()
        try:
            render.render(self.edit, str(self._preview), scale=PREVIEW_SCALE)
            preview.show_calendar(self._preview)
        except OSError:
            pass
        layout.addWidget(preview)
        QtCore.QTimer.singleShot(0, self._size_previews)

    def _swap_update(self, where):
        """Rewrite the picture this month was already exported as."""
        path = pathlib.Path(where)
        try:
            size = render.render(self.edit, str(path), scale=EXPORT_SCALE)
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "Could not write it", str(exc))
            return
        self.edit = store.remember_export(self.edit, self._group_id(), path)
        self.edit_from = self._copy_schedule(self.edit)
        self.statusBar().showMessage(
            "Updated %s (%d×%d)" % (path.name, *size), 6000)
        self._rebuild_swaps()
        self._rebuild_history()

    def _swap_take(self):
        if not self.schedule:
            return
        self.edit = self._copy_schedule(self.schedule)
        self.edit_from = self._copy_schedule(self.schedule)
        self.edit_source = "from the Schedule tab"
        self._rebuild_swaps()

    def _swap_open(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open a calendar to change", str(pathlib.Path.home()),
            "Calendar image (*.png)")
        if not path:
            return
        if self.swap_reader is not None and self.swap_reader.isRunning():
            return
        self.statusBar().showMessage("Reading %s…" % pathlib.Path(path).name)
        self.swap_reader = Reader(
            path,
            roster.active_technicians(self.roster, self.group_index),
            roster.active_supervisors(self.roster),
            (self.year_spin.value(), self.selected_month()))
        name = pathlib.Path(path).name
        self.swap_reader.done.connect(lambda s, n=name: self._swap_loaded(s, n))
        self.swap_reader.failed.connect(
            lambda message: QtWidgets.QMessageBox.warning(
                self, "Could not read it", message))
        self.swap_reader.start()

    def _swap_loaded(self, schedule, name):
        # A calendar read off a picture carries no record of the gap it was
        # solved for, so the month is measured as it stands and that becomes
        # the mark a trade is judged against.
        schedule = self._copy_schedule(schedule)
        schedule.setdefault("gap", 0)
        # A calendar drawn before numbers existed carries none; the roster has
        # them, and the redrawn month should show them.
        if not schedule.get("phones"):
            schedule["phones"] = roster.phones_for(
                self.roster, roster.active_supervisors(self.roster))
        report = solve.review(schedule, *self._swap_context(),
                              roster=roster.active_technicians(
                                  self.roster, self.group_index))
        schedule["gap"] = report["gap"]
        self.edit = schedule
        self.edit_from = self._copy_schedule(schedule)
        self.edit_source = "read from %s" % name
        self.statusBar().showMessage("Read %s" % name, 4000)
        self._rebuild_swaps()

    def _swap_days(self, one, other):
        if not self.edit or one == other:
            return
        self.edit = solve.swap(self.edit, one, other)
        self._rebuild_swaps()

    def _give_day(self, day, who):
        if not self.edit:
            return
        self.edit = solve.give(self.edit, day, who)
        self._rebuild_swaps()

    def _swap_undo(self):
        if not self.edit_from:
            return
        self.edit = self._copy_schedule(self.edit_from)
        self._rebuild_swaps()

    def _swap_export(self):
        if not self.edit:
            return
        several = len(self.roster["groups"]) > 1
        name = "oncall_%02d%04d%s.png" % (
            self.edit["month"], self.edit["year"],
            "_" + self._group_id() if several else "")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export the changed calendar",
            str(pathlib.Path.home() / name), "PNG image (*.png)")
        if not path:
            return
        path = pathlib.Path(path).with_suffix(".png")
        size = render.render(self.edit, str(path), scale=EXPORT_SCALE)
        self.edit = store.remember_export(self.edit, self._group_id(), path)
        self.edit_from = self._copy_schedule(self.edit)
        self.statusBar().showMessage(
            "Saved %s (%d×%d), and recorded the month" % (path.name, *size), 6000)
        self._rebuild_swaps()
        self._rebuild_history()

    # -- history -------------------------------------------------------------

    def _history_tab(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        self.history_box = QtWidgets.QGroupBox("Months worked")
        self.history_layout = QtWidgets.QVBoxLayout(self.history_box)
        layout.addWidget(self.history_box)
        layout.addStretch(1)
        self._rebuild_history()
        return page

    def _rebuild_history(self):
        """The months this group has a record of, and a way back into them.

        The record is the app's own, kept beside the roster: the months it
        solved and exported. It is deliberately not a list of pictures found on
        disk -- a calendar somebody moved, renamed or deleted is still a month
        that was worked, and a file in a downloads folder that happens to look
        like one is not.
        """
        layout = self.history_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    inner = item.layout().takeAt(0)
                    if inner.widget():
                        inner.widget().deleteLater()

        self.history_box.setTitle("Months worked — %s" % self._group()["name"])
        note = QtWidgets.QLabel(
            "Recorded here when a month is exported. Open one to trade days in "
            "it or to export it again; the pictures themselves stay wherever "
            "you saved them.")
        note.setWordWrap(True)
        layout.addWidget(note)

        months = store.history(self._group_id())
        if not months:
            empty = QtWidgets.QLabel(
                "Nothing recorded yet — a month is recorded the moment it is "
                "exported.")
            empty.setWordWrap(True)
            empty.setObjectName("status")
            layout.addWidget(empty)
            return

        for record in months:
            try:
                holder = self._history_row(record)
            except Exception as exc:
                # One unreadable record is a line saying so, never a window
                # that does not open: this runs before anything is on screen,
                # so anything thrown here is the difference between an app and
                # a process that exits quietly.
                holder = QtWidgets.QLabel("A recorded month could not be read "
                                          "— %s: %s" % (type(exc).__name__, exc))
                holder.setWordWrap(True)
            layout.addWidget(holder)

        clear = self._button("Clear history", self._confirm_clear_history)
        clear.setToolTip("Forgets the months listed above. The calendars you "
                         "exported are left alone.")
        layout.addWidget(clear)

    def _history_row(self, record):
        """One month's line in the history."""
        when = "%s %d" % (calendar.month_name[record["month"]], record["year"])
        if record.get("partial"):
            detail = "the closing days only, taken by hand for the boundary"
        else:
            counts = {}
            for name in record.get("tech", {}).values():
                counts[name] = counts.get(name, 0) + 1
            spread = sorted(set(counts.values()))
            gap = record.get("gap") or 0
            detail = ("%d people · %s shifts each · %s"
                      % (len(counts),
                         " or ".join(str(n) for n in spread) or "no",
                         "%d days between anyone's shifts" % gap if gap
                         else "read from a calendar, so no spacing recorded"))
        where = record.get("exported")
        if where:
            detail += " · exported as %s" % pathlib.Path(where).name
            if not pathlib.Path(where).exists():
                detail += " (no longer there)"
        row = QtWidgets.QHBoxLayout()
        label = QtWidgets.QLabel("<b>%s</b><br>%s" % (when, detail))
        label.setWordWrap(True)
        row.addWidget(label, 1)
        if not record.get("partial"):
            row.addWidget(self._button(
                "Open in Swaps", lambda r=record: self._history_open(r)))
        holder = QtWidgets.QWidget()
        holder.setLayout(row)
        return holder

    def _history_open(self, record):
        """Take a recorded month into the Swaps tab to be traded around."""
        schedule = self._copy_schedule(record)
        if not schedule.get("phones"):
            schedule["phones"] = roster.phones_for(
                self.roster, roster.active_supervisors(self.roster))
        self.edit = schedule
        self.edit_from = self._copy_schedule(schedule)
        self.edit_source = "from the history"
        self._rebuild_swaps()
        self.tabs.setCurrentIndex(2)

    def _confirm_clear_history(self):
        """Ask first: this is what the next month's spacing is built on."""
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle("Clear this group's history?")
        box.setText("Forget the months recorded for this group?")
        box.setInformativeText(
            "With them goes the boundary the next month is solved against — "
            "spacing across the turn of the month stops being enforced until a "
            "month is exported again.\n\nThe calendars you exported are your "
            "own files and are not touched.")
        clear = box.addButton("Clear history",
                              QtWidgets.QMessageBox.DestructiveRole)
        box.addButton(QtWidgets.QMessageBox.Cancel)
        box.setDefaultButton(QtWidgets.QMessageBox.Cancel)
        box.exec()
        if box.clickedButton() is clear:
            gone = store.forget(self._group_id())
            self.statusBar().showMessage(
                "Forgot %d month%s" % (gone, "" if gone == 1 else "s"), 6000)
            self._rebuild_history()

    # -- month ---------------------------------------------------------------

    def _sync_months(self, keep=None):
        year = self.year_spin.value()
        first = self.floor[1] if year == self.floor[0] else 1
        if keep is None:
            keep = self.selected_month()
        self.month_offset = first
        self.month_combo.blockSignals(True)
        self.month_combo.clear()
        self.month_combo.addItems([calendar.month_name[m]
                                   for m in range(first, 13)])
        self.month_combo.setCurrentIndex(
            max(0, min(12 - first, keep - first)))
        self.month_combo.blockSignals(False)

    def selected_month(self):
        return getattr(self, "month_offset", 1) + self.month_combo.currentIndex()

    def _next_unsolved(self):
        year, month = self.floor
        while store.load(year, month, self._group_id()) is not None:
            month += 1
            if month == 13:
                year, month = year + 1, 1
        return year, month

    # -- groups --------------------------------------------------------------

    def _group(self):
        return roster.group(self.roster, self.group_index)

    def _group_id(self):
        return roster.group_id(self.roster, self.group_index)

    def _rebuild_groups(self, select=None):
        self.group_tabs.blockSignals(True)
        while self.group_tabs.count():
            self.group_tabs.removeTab(0)
        for index, group in enumerate(self.roster["groups"]):
            page = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(page)
            names = NameList(add_label="Add a technician")
            names.set_names(group["technicians"])
            names.changed.connect(self._roster_changed)
            layout.addWidget(names)

            footer = QtWidgets.QHBoxLayout()
            footer.addWidget(QtWidgets.QLabel("Group name"))
            title = QtWidgets.QLineEdit(group["name"])
            title.editingFinished.connect(
                lambda i=index, e=title: self._rename_group(i, e.text().strip()))
            footer.addWidget(title, 1)
            drop = QtWidgets.QToolButton()
            drop.setText("Remove group")
            drop.clicked.connect(lambda _=False, i=index: self._remove_group(i))
            footer.addWidget(drop)
            layout.addLayout(footer)
            self.group_tabs.addTab(page, group["name"] or "Group")
        target = self.group_index if select is None else select
        self.group_index = max(0, min(target, len(self.roster["groups"]) - 1))
        self.group_tabs.setCurrentIndex(self.group_index)
        self.group_tabs.blockSignals(False)

    def _group_changed(self, index):
        if index < 0 or index == self.group_index:
            return
        self.group_index = index
        # A calendar belongs to the group it was solved for.
        self.schedule = None
        self.export_button.setEnabled(False)
        self.respin_button.setEnabled(False)
        self.preview.clear_calendar()
        self.status.setText("Press Generate to solve this group's month")
        self._rebuild_timeoff()
        self._rebuild_history()

    def _add_group(self):
        self.roster["groups"].append({"id": "", "name": "New group",
                                      "technicians": []})
        roster.ensure_ids(self.roster)
        roster.save(self.roster)
        self._rebuild_groups(len(self.roster["groups"]) - 1)

    def _remove_group(self, index):
        if len(self.roster["groups"]) <= 1:
            self.statusBar().showMessage("The last group cannot be removed", 4000)
            return
        del self.roster["groups"][index]
        roster.save(self.roster)
        self._rebuild_groups(max(0, index - 1))

    def _rename_group(self, index, name):
        if not name or self.roster["groups"][index]["name"] == name:
            return
        self.roster["groups"][index]["name"] = name
        roster.save(self.roster)
        self._rebuild_groups(index)

    def _roster_changed(self):
        roster.save(self.roster)

    # -- clearing ------------------------------------------------------------

    def _confirm_clear(self):
        """Ask first. This is the one button that throws away typing."""
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle("Clear everyone?")
        box.setText("Clear every supervisor and technician?")
        box.setInformativeText(
            "Every supervisor, and every technician in every group, is "
            "removed — along with the time off booked against them.\n\n"
            "The groups themselves stay, and so do the months already "
            "exported: this empties the roster, not the record.")
        clear = box.addButton("Clear everyone",
                              QtWidgets.QMessageBox.DestructiveRole)
        box.addButton(QtWidgets.QMessageBox.Cancel)
        box.setDefaultButton(QtWidgets.QMessageBox.Cancel)
        box.exec()
        if box.clickedButton() is clear:
            self._clear_everyone()

    def _clear_everyone(self):
        """A blank slate: no supervisors, no technicians, no time off.

        Time off goes with the people. It is booked against a name, and a name
        that is no longer on the roster would otherwise sit in the file waiting
        to surprise whoever is typed in next -- someone sharing a first name
        with whoever left would inherit their holiday.

        The groups survive, because they are the shape of the rota rather than
        the people in it, and so do the exported months: those record what was
        actually worked, and clearing a roster is no reason to forget it.
        """
        # Every one of these is emptied in place, never reassigned. The name
        # lists hold these very objects -- NameList.set_names keeps the
        # reference and edits through it -- so handing the roster a fresh list
        # leaves the widget editing the old one, and everything typed
        # afterwards is written to an orphan that is never saved.
        self.roster.setdefault("supervisors", []).clear()
        for group in self.roster["groups"]:
            group.setdefault("technicians", []).clear()
        self.roster.setdefault("inactive", []).clear()
        self.roster.setdefault("phones", {}).clear()
        roster.save(self.roster)
        for group in self.roster["groups"]:
            timeoff.save(group["id"], {})

        self.schedule = None
        self.avoid = None
        self.seen, self.seen_key = [], None
        self.preview.clear_calendar()
        self.export_button.setEnabled(False)
        self.respin_button.setEnabled(False)
        self.tail_button.setVisible(False)
        # Rebound to the roster's own list, not to a fresh one. Passing []
        # here was the bug: it detached the supervisor list from the roster, so
        # supervisors typed in after a clear went nowhere -- while a scanned
        # import looked fine, because absorbing one re-binds this very widget.
        self.sup_list.set_names(self.roster["supervisors"])
        self._rebuild_groups()
        self._rebuild_timeoff()
        self.status.setText("Add supervisors and technicians, then press Generate")
        self.statusBar().showMessage("Cleared everyone", 6000)

    # -- time off ------------------------------------------------------------

    def _rebuild_timeoff(self):
        layout = self.timeoff_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.timeoff_box.setTitle("Time off — %s" % self._group()["name"])
        note = QtWidgets.QLabel(
            "Nobody is scheduled on a day they are away. If that leaves "
            "someone unable to carry an even share, their shifts move to "
            "whoever can take them.")
        note.setWordWrap(True)
        note.setObjectName("status")
        layout.addWidget(note)

        booked = timeoff.load(self._group_id())
        techs = roster.active_technicians(self.roster, self.group_index)
        rows = 0
        for name in techs:
            for start, end in timeoff.spans(booked.get(name, [])):
                span = [d.isoformat() for d in _days_between(start, end)]
                row = QtWidgets.QHBoxLayout()
                label = QtWidgets.QLabel("<b>%s</b> — %s"
                                         % (name, timeoff.describe(span)))
                row.addWidget(label, 1)
                cancel = QtWidgets.QToolButton()
                cancel.setText("✕")
                cancel.setToolTip("Cancel this time off")
                cancel.clicked.connect(
                    lambda _=False, n=name, d=span: self._cancel_timeoff(n, d))
                row.addWidget(cancel)
                holder = QtWidgets.QWidget()
                holder.setLayout(row)
                layout.addWidget(holder)
                rows += 1

        if not rows:
            empty = QtWidgets.QLabel("Nothing booked — everyone is available.")
            empty.setObjectName("status")
            layout.addWidget(empty)

        book = self._button("Book time off…", self._book_timeoff)
        book.setEnabled(bool(techs))
        layout.addWidget(book)

    def _cancel_timeoff(self, name, days):
        timeoff.remove(self._group_id(), name, days)
        self._rebuild_timeoff()

    def _book_timeoff(self):
        techs = roster.active_technicians(self.roster, self.group_index)
        dialog = TimeOffDialog(self, techs)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        name, start, end = dialog.result_range()
        timeoff.add(self._group_id(), name, start, end)
        self._rebuild_timeoff()
        self.statusBar().showMessage("%s is off %s" % (name, timeoff.describe(
            [d.isoformat() for d in _days_between(start, end)])), 5000)

    # -- last month ----------------------------------------------------------

    def enter_tail(self):
        year, month = self.year_spin.value(), self.selected_month()
        prev_year, prev_month = store.previous(year, month)
        dialog = TailDialog(
            self, prev_year, prev_month,
            roster.active_technicians(self.roster, self.group_index),
            roster.active_supervisors(self.roster),
            store.load(prev_year, prev_month, self._group_id()) or {})
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        tail, supervisor = dialog.result_tail()
        if not tail and not supervisor:
            return
        store.save_tail(prev_year, prev_month, self._group_id(), tail, supervisor)
        self.generate()

    def upload(self):
        """Take an old calendar and learn from it.

        Everything this app exports carries its schedule inside it, so reading
        one back is exact. A calendar from anywhere else is read off the
        picture, which works well at the resolution this exports and poorly at
        a quarter of it -- so cells it cannot be sure of are left empty rather
        than filled with a guess someone has to catch.
        """
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Upload a calendar", str(pathlib.Path.home()),
            "Calendar image (*.png)")
        if not path:
            return
        self.status.setText("Reading %s… this takes a few seconds for a picture"
                            % pathlib.Path(path).name)
        self.export_button.setEnabled(False)
        self.reader = Reader(
            path,
            roster.active_technicians(self.roster, self.group_index),
            roster.active_supervisors(self.roster),
            # The month on screen, for a calendar drawn without a heading to
            # read. Only a fallback, and what was recorded is named in the
            # message afterwards, so a wrong guess is visible rather than
            # silent.
            (self.year_spin.value(), self.selected_month()))
        self.reader.done.connect(self._upload_read)
        self.reader.failed.connect(self._upload_failed)
        self.reader.start()

    def _upload_failed(self, message):
        self.export_button.setEnabled(bool(self.schedule))
        self.respin_button.setEnabled(bool(self.schedule))
        self.status.setText("Could not read that calendar: %s" % message)
        QtWidgets.QMessageBox.warning(self, "Could not read it", message)

    def _upload_read(self, schedule):
        try:
            summary = importer.absorb(schedule, self.roster, self.group_index,
                                      self._group_id())
        except Exception as exc:
            self._upload_failed("%s: %s" % (type(exc).__name__, exc))
            return

        self.sup_list.set_names(self.roster["supervisors"])
        self._rebuild_groups(self.group_index)
        self._rebuild_timeoff()

        added = []
        if summary["technicians_added"]:
            added.append("technicians: " + ", ".join(summary["technicians_added"]))
        if summary["supervisors_added"]:
            added.append("supervisors: " + ", ".join(summary["supervisors_added"]))
        if summary.get("numbers_added"):
            added.append("phone numbers for "
                         + ", ".join(summary["numbers_added"]))
        detail = ("read exactly from the file" if summary["source"] == "embedded"
                  else "recognised from the picture")
        QtWidgets.QMessageBox.information(
            self, "Calendar read",
            "%s %d: %d of %d days %s.%s%s"
            % (calendar.month_name[summary["month"]], summary["year"],
               summary["days"], summary["of"], detail,
               "\n\nAdded — " + "; ".join(added) if added else
               "\n\nNobody new; the roster already had everyone on it.",
               "\n\nRecorded as a partial month: the days it could not read are "
               "not filled in." if summary["partial"] else "")
            + ("\n\nNot confident enough to use: %s. Add anyone missing by hand."
               % ", ".join(summary["ignored"]) if summary["ignored"] else ""))
        self.generate()

    # -- solving -------------------------------------------------------------

    def generate(self, respin=False):
        """Solve the chosen month off the UI thread.

        `respin` asks for a different arrangement of the same month rather than
        the same one again, and says which one not to repeat.
        """
        if self.solver is not None and self.solver.isRunning():
            return
        year, month = self.year_spin.value(), self.selected_month()
        techs = roster.active_technicians(self.roster, self.group_index)
        if not techs:
            self.status.setText("%s has no technicians yet — add some above."
                                % self._group()["name"])
            return
        sups = roster.active_supervisors(self.roster)
        group = self._group_id()

        # Tied to the month, the group and the roster: change any of them and
        # what was shown before is about a different question.
        key = (year, month, group, tuple(techs))
        if key != self.seen_key:
            self.seen_key, self.seen = key, []
        self.avoid = list(self.seen) if respin and self.schedule else None
        self.status.setText("%s %s %d…"
                            % ("Re-rolling" if self.avoid else "Solving",
                               calendar.month_name[month], year))
        self.export_button.setEnabled(False)
        self.respin_button.setEnabled(False)
        self.solver = Solver(year, month, techs, sups,
                             store.carry_in(year, month, sups, group),
                             timeoff.for_month(group, year, month),
                             self.avoid)
        self.solver.done.connect(self._solved)
        self.solver.failed.connect(self._failed)
        self.solver.start()

    def _solved(self, schedule):
        # Not saved here: generating is looking, exporting is deciding, and it
        # is the export that records the month the next one is built against.
        schedule["phones"] = roster.phones_for(
            self.roster, roster.active_supervisors(self.roster))
        self.schedule = schedule
        render.render(schedule, str(self._preview), scale=PREVIEW_SCALE)
        self.preview.show_calendar(self._preview)
        # A calendar that has just arrived has not been through a resize, and
        # without this it would sit at its smallest until the window moved.
        self._size_previews()

        spread = sorted(set(schedule["shifts"].values()))
        gap_note = ("longest possible" if schedule.get("gap_proved_maximal")
                    else "longest found in the time allowed")
        repeats = schedule["repeats"]
        self.status.setText(
            "<b>%s %d — %s</b><br>%d days between anyone's shifts (%s) · "
            "%s shifts each · %s"
            % (calendar.month_name[schedule["month"]], schedule["year"],
               self._group()["name"], schedule["gap"], gap_note,
               " or ".join(str(n) for n in spread),
               "no repeats of last month's heavier load" if not repeats
               else "%d unavoidable repeats: %s" % (len(repeats),
                                                    ", ".join(repeats))))
        known = schedule.get("boundary_known", True)
        self.tail_button.setVisible(not known)
        if not known:
            prev_year, prev_month = store.previous(schedule["year"],
                                                   schedule["month"])
            self.statusBar().showMessage(
                "%s %d is not recorded — spacing across the month boundary is "
                "not enforced" % (calendar.month_name[prev_month], prev_year),
                8000)
        else:
            self.statusBar().showMessage("Ready", 2000)
        if schedule["tech"] not in self.seen:
            self.seen.append(schedule["tech"])
        if self.avoid and schedule["tech"] in self.avoid:
            # Not a failure, and not proof there are no others either: the
            # search gives up after a few tries, and a tight month has few
            # arrangements to find. Say what happened rather than more.
            self.statusBar().showMessage(
                "Back to an arrangement you have already seen — this month "
                "has few at this gap", 6000)
        self.export_button.setEnabled(True)
        self.respin_button.setEnabled(True)

    def _failed(self, message):
        self.schedule = None
        self.preview.clear_calendar()
        self.status.setText("<b>Could not solve this month</b><br>%s" % message)
        self.export_button.setEnabled(False)
        self.respin_button.setEnabled(False)

    # -- export --------------------------------------------------------------

    def export(self):
        if not self.schedule:
            return
        several = len(self.roster["groups"]) > 1
        name = "oncall_%02d%04d%s.png" % (
            self.schedule["month"], self.schedule["year"],
            "_" + self._group_id() if several else "")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export calendar", str(pathlib.Path.home() / name),
            "PNG image (*.png)")
        if not path:
            return
        path = pathlib.Path(path).with_suffix(".png")
        size = render.render(self.schedule, str(path), scale=EXPORT_SCALE)
        # Recorded at the moment it is published, so what the next month reads
        # back is what people are actually working to -- and where it was
        # written, so it can be brought up to date later.
        self.schedule = store.remember_export(self.schedule, self._group_id(),
                                              path)
        self._rebuild_history()
        self.statusBar().showMessage(
            "Saved %s (%d×%d), and recorded the month" % (path.name, *size), 6000)


def _days_between(start, end):
    day, out = start, []
    while day <= end:
        out.append(day)
        day += datetime.timedelta(days=1)
    return out


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("On-Call Scheduler")
    app.setApplicationDisplayName("On-Call Scheduler")
    app.setWindowIcon(QtGui.QIcon.fromTheme("io.github.cdenike.OnCallScheduler"))
    window = Window()
    window.show()
    return app.exec()
