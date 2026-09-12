# On-Call Scheduler

An on-call rota: pick a month, solve it, export the calendar.

```
Generate  Respin  Clear everyone      On-Call Scheduler      Export PNG…

Month
  Schedule for                              [ November ▾ ] [ 2026 ]
  November 2026
  10 days between anyone's shifts (longest possible) · 2 or 3 shifts each
  · 6 unavoidable repeats: Alfa, Bravo, Charlie, Delta, Echo, Foxtrot
```

## Respin, and starting over

The solver is deterministic: **Generate** twice on the same roster and month
gives the same rota, which is what makes it defensible — the answer comes from
the rules rather than from luck. **Respin** is how to ask for a different one.
It hands the solver the same people in a different order, and that order is only
what breaks ties, so the result obeys every rule the first one did, keeps the
same spacing and the same share of shifts each, and leaves the supervisor cycle
untouched. A month whose constraints leave a single arrangement says so, rather
than looking like the button did nothing.

**Clear everyone** empties the roster: every supervisor, every technician in
every group, and the time off booked against them — that goes with the people,
because it is booked against a name, and a name typed in later should not
inherit someone else's holiday. It asks before it does it. The groups
themselves stay, and so do the months already exported: those are the record of
what was actually worked.

## Why it solves rather than lets you place

The constraints interact, and the one that catches people is the month
boundary. A rota built for October alone will happily open with whoever worked
September 30th, because nothing inside October knows about it. That is not a
hypothetical: it is what happened, and it is why the schedule is not editable
by hand here. The roster is the input; if an assignment looks wrong, correct
the roster and solve again.

The rules:

- one technician every day, and a supervisor on Mondays
- nobody on a day they have booked off
- supervisors cycle in roster order, carrying on from where last month ended
- shifts split as evenly as the roster can carry — 31 days across 11
  technicians forces nine of them onto three
- whoever carried the heavier load last month is spared it this month, as far
  as the arithmetic allows
- at most one weekend day each, and whoever had no weekend last month is
  served first when one is going
- the longest achievable gap between anyone's shifts, counted across the month
  boundary

**There are two different Blaires.** The supervisor who takes Mondays and
the technician who takes ordinary days are separate people, kept in separate
lists so nothing can confuse them. A supervisor's Monday is not part of any
technician's spacing.

## The gap is maximised, not fixed

A number picked in advance is either unreachable or leaves a better schedule on
the table, so the solver searches downward from the largest gap the roster
could support and takes the first that works. Any run of *n* consecutive days
needs *n* different people, so no gap can exceed the roster size — a tighter
ceiling than reasoning from how many shifts must fit in the month.

The longest gap is not searched for at all, because at that spacing the month
has no freedom left in it. Every run of *gap* consecutive days must use *gap*
different people and there are only that many, so each run is all of them —
slide it one day and the same reasoning makes day *d* and day *d + gap* the
same person. The month is therefore a repeating cycle, and all that remains is
deciding who takes each position in it: a matching, not a search.

That matters because it is the question the search is worst at. Eleven people
at a gap of eleven ran twelve million steps and was still undecided after
forty-five seconds; ten people at ten took thirty seconds to prove impossible.
As a matching both are settled in a few hundred comparisons, and a failure is
a proof rather than a timeout — so the solver drops a day knowing it gave up
nothing.

Below that, the search is bounded by a clock that scales with the roster
rather than a constant, and it says which it did — "longest possible" when the
gaps above were ruled out, "longest found in the time allowed" when they were
merely abandoned.

## Files

Everything lives beside the calendars, as plain JSON:

```
~/.local/share/oncall-scheduler/
  roster.json                    groups, technicians, supervisors in cycle order
  months/<group>/2026-11.json    one per solved month, per group
  timeoff/<group>.json           booked days off
```

A solved month is saved as soon as it is generated, because the next month's
boundary depends on it. Where a month has been worked already, uploading its
calendar seeds the record, so the first month solved here has a predecessor to
respect rather than starting from nothing.

## The calendar

A dark calendar, and a deliberately quiet one. The page recedes to near-black,
the grid is the faintest rule that still reads as a grid, and the only
brightness in the picture is the names — which is what anyone opens it to find.

- the month set large and letter-spaced, the year quieter beside it, with a
  short accent rule under the month it names
- the weekend a shade apart from the working week, columns and labels both
- day numbers small and dim in the corner, behind the name rather than beside
  it in weight
- the technician centred in the day, and on Mondays the supervisor above them
  in the one accent the calendar keeps for that — a Monday carries two names
  and they are not the same kind of thing
- the supervisor's phone number under their name, in the same colour, when the
  roster has one: a calendar that says who is on should also say how to reach
  them. Typed as `5555550144`, `555-555-0144` or `1-555-555-0144`, it is drawn
  as `555-555-0144` every time: digits are grouped from the right in fours and
  threes, and a leading 1 is dropped, since no area code starts with one.
  Anything that is not plain digits — a number marked with a plus, an
  extension, a note — is drawn exactly as typed, its owner knowing better than
  this does how it should look
- the days either side of the month darker still: present, plainly not part of
  it

The design is fixed. The same schedule drawn twice is the same picture, and
every month looks like the last one — the point of a calendar people recognise
at a glance is that it does not surprise them.

Nothing spans the full width except the grid's own rules, which is taste and
also machinery: the reader finds the grid by looking for the brightest
full-width lines, so a banner or an accent drawn across the page would outshine
the rules and hide them.

The number of weeks follows the month, and the image grows by a row rather than
the rows shrinking to fit — the row height is part of the design.

## Getting it

**Windows and Linux, no Python needed:** download the binary for your system
from [Releases](https://github.com/cdenike/oncall-scheduler/releases).
`OnCallScheduler.exe` on Windows, `OnCallScheduler` on Linux — one file, no
installer, nothing to unpack.

Those are built on the machines they target, because PyInstaller cannot
cross-compile: pushing a `v*` tag builds both and attaches them to the release.

**From source**, if you would rather:

```bash
pip install PySide6-Essentials Pillow
python3 -m oncall
```

## Installing on Linux

```bash
./install.sh
```

No root, nothing outside `$HOME`: the command lands in `~/.local/bin`, the icon
and desktop entry under `~/.local/share`, and the desktop and icon caches are
refreshed so it appears without a session restart. This route runs from the
checkout rather than from a bundled binary.

- **`oncall-scheduler`** opens the window
- **On-Call Scheduler** appears in the app launcher, the Omarchy menu included

The command points at the checkout it was installed from, so `git pull` updates
it with no reinstall. Needs Python 3.9 or newer, PySide6 and Pillow -- of PySide6, only the
`PySide6-Essentials` half, which is a fraction of the download. The same code runs
on Windows and on Linux.

## Time off

The second tab books it: a person and a span of dates, stored per group as
plain days and read back as ranges. Nobody is scheduled on a day they are away,
and a day nobody is available for is refused by name rather than after a long
search that finds nothing.

Time off also changes the arithmetic, which is why it is an input rather than a
filter applied afterwards. Shifts are handed out by water-filling: the next one
always goes to whoever has fewest so far and can still take another. Nothing
here is tuned to a particular roster size — whatever the number on it, the
split is the flattest the month allows, and nobody ends up more than one shift
ahead of anybody else:

| roster (31-day month) | shifts each | longest gap |
|---|---|---|
| 3 people | 10–11 | 2 days |
| 4 people | 7–8 | 4 days |
| 6 people | 5–6 | 6 days |
| 9 people | 3–4 | 8 days |
| 11 people | 2–3 | 10 days |
| 12 people | 2–3 | 12 days |
| 20 people | 1–2 | 19 days |
| 31 people | 1 each | 31 days |
| 40 people | 1 each | 31 days — nine spare |
| 11 people, one away a fortnight | 2–3 — the others absorb it |
| 4 people, one away a fortnight | 7–8 |

Somebody who cannot carry an even share passes their days to whoever can, one
at a time, so the result is the flattest distribution the roster allows rather
than a quota nobody can work. Ties go against whoever carried the heavier load
last month.

## Trading days

People swap shifts, constantly. The Schedule tab will not let a month be
rearranged by hand — the constraints interact, and that is how somebody ends up
working either side of the first — but the Swaps tab exists for exactly that
trade, and it makes the cost visible instead of deciding for anyone.

Take the month from the Schedule tab, or open a calendar that already exists,
including one this program did not draw. Then swap two days, or hand a single
day to somebody else. What comes back is what it did:

- the shortest gap left between anyone's shifts, and what it was before
- anybody now on a day they are away, over their weekend share, or missing
  from the month altogether
- whether the shifts still come out even

The calendar below is redrawn as you go, so a trade is something you can see
before you keep it. Nothing is refused: a trade that takes the longest gap from
twelve days to eleven is ordinary and says so; one that puts somebody on the
8th and the 9th says that too, and then it is a person's call rather than the
program's. Undo puts it back.

Nothing leaves the tab until you export. Where a month has already been given
out as a picture, that picture can be **brought up to date in place** — the
same file, rewritten, so whoever has it has the change — rather than saved
again somewhere new for people to confuse with the first one.

## History

Every month is recorded when it is exported, and the History tab lists them:
who was on, how the shifts fell, how far apart anyone's days were, and which
file it went out as.

The record is the app's own, kept beside the roster. It is deliberately not a
list of pictures found on disk — a calendar somebody moved, renamed or deleted
is still a month that was worked, and a file in a downloads folder that happens
to look like one is not.

Open any month from there and it goes straight into the Swaps tab, which is the
quick way back into a month somebody wants changed: no hunting for the picture
and no waiting for it to be read back off its own pixels.

**Clear history** forgets the months listed. It asks first, because the most
recent of them is what next month's spacing is measured against — clear it and
spacing across the turn of the month stops being enforced until a month is
exported again. The calendars you exported are your own files and are left
alone.

## Groups

Technicians belong to a group, and there can be several: separate teams keeping
separate rotas, each with its own months on disk and its own export. The tabs
are the groups; the month, the calendar and the export act on whichever is in
front. Each supervisor can carry a phone number, typed in beside their name,
and it is drawn under them on their Mondays — the number belongs to the person,
so correcting a spelling carries it across rather than orphaning it.

Supervisors are shared, because the Monday cycle covers the operation
rather than any one team.

One weekend day each is a consequence rather than a rule. The cap is the
fewest weekend days anyone could be asked to take: the month's weekend days
divided by the roster, rounded up. Nine weekend days across eleven people is
one each; across four people it is three each; across forty it is one each
with most taking none. A team too small to honour one apiece is not refused,
it is told what the arithmetic actually allows.

## Reading an old calendar back in

Upload a month that was scheduled before — exported by this app or by whatever
came before it — and it fills in the technicians, the supervisors in cycle
order, and the month itself, so the next month has a boundary to respect
without anybody typing it.

Every calendar this exports carries its schedule inside it, in a PNG text
chunk, so reading one of those back is exact: the same data that drew it.

Anything else is read off the picture, and the calendar is measured rather
than assumed. Four things vary between one program's calendar and another's,
and each is found rather than taken on trust:

- **Which way round it is drawn.** This one is light ink on a dark ground;
  most are the other way about. That single difference defeated the rules, the
  ink counting and the recognition all at once, which looked like three faults
  and was one. The picture is turned the right way round before anything else
  looks at it.
- **Where the columns are.** Found from the vertical rules, so a wider Sunday
  or a margin down one side costs nothing. The page edge counts as a rule,
  since plenty of grids run right to it.
- **Where the weeks are.** Found from the horizontal rules — and where there
  are none, from the spacing, because the blank stretches between weeks repeat
  at a fixed pitch while nothing else in the picture does.
- **Where the heading is.** Read where this program puts it, then wherever it
  actually is; and a calendar with no heading at all is read as the month you
  have chosen in the window.

Each cell is then cropped to its own text, with any rule down either side
trimmed off it — left in, a rule reads as a letter and a four-letter name
comes back with a stray fifth on the end. Where the reading is not a name on
the roster, the cell is compared against each name drawn the way the calendar
drew it, which settles what recognition cannot.

Measured across five unrelated layouts — ruled and unruled, serif and mono,
even columns and uneven, light and dark — at four sizes each, eighteen of the
twenty read every day and every supervisor correctly.

| the calendar | result |
|---|---|
| exported by this app | exact, instant, no recognition |
| someone else's, at this resolution | 31 of 31 days, 4 of 4 supervisors |
| someone else's, at a quarter of it | 17 of 30 days filled — 3 right, none wrong |

It declines rather than inventing: a gap asks to be filled, a plausible mistake
does not. Reading one this app exported needs no recognition at all — the
schedule travels inside the picture.

Reading anybody else's does, and that is the one place the two builds differ.
The Windows build carries recognition, because a Windows machine has no package
manager to ask. The Linux build does not: bundling it there meant a second copy
of ICU, 35 MB of it, beside the one Qt already brings, to spare a single

    sudo apt install tesseract-ocr        # or your distribution's equivalent

Without it everything else works and the app says plainly that it cannot read a
picture, rather than blaming the calendar.

## A month that was scheduled elsewhere

If the month before has no record, the window offers to take its tail: the last
dozen days and whoever covered the final Monday. That is all the boundary needs,
and it beats asking for a whole month somebody already worked. Those files are
marked `partial`, so their shift counts and weekends are not read as a month's —
three shifts in a week says nothing about a month's load.

## Licence

Copyright (C) 2026 Caden DeNike. Free software under the
[GNU General Public License, version 3 or later](LICENSE): use it, read it,
change it, pass it on. What the licence asks in return is that a copy you pass
on stays free -- the notice stays, and whoever receives it can get the source
and the same rights you had. Running it inside a company is use, not
distribution, and asks nothing.

The licence is what keeps your name on it. Section 5 requires a modified
version to say plainly that it was changed and to keep the notices already in
it; section 8 ends the rights of anyone who strips them. Every source file
carries the notice, [AUTHORS](AUTHORS) says whose work it is, and releases
are signed -- a history signed by somebody else did not come from here.

A release carries other people's work too -- Qt, Pillow, and on Windows
tesseract and the libraries under it. [THIRD-PARTY-NOTICES](THIRD-PARTY-NOTICES.md)
lists what, under which licence, and what that asks of anyone redistributing a
build. It was written from the contents of a release rather than from a
dependency list.
