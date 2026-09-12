"""Build a month's rota from the rules, rather than placing people by hand.

The constraints interact, which is why this is solved rather than arranged. The
one that bites is the month boundary: a schedule built for October alone will
happily open with the technician who worked September 30th, because nothing
inside October knows about it.

    one technician a day, every day
    supervisors on Mondays only, cycling in roster order
    shifts split as evenly as the month allows
    whoever carried the heavier load last month is spared it this month
    at most one weekend day each
    whoever had no weekend last month is served first when one is going
    and the longest achievable gap between anyone's shifts, counting
    backwards into last month

The last is maximised rather than fixed: the answer depends on the month's
length and the roster's size, and a number picked in advance is either
unreachable or leaves a better schedule on the table.

Copyright (C) 2026 Caden DeNike. Free software under the GNU General
Public License, version 3 or later, with no warranty. See LICENSE.
"""

import calendar
import time

# Wall-clock the whole solve may spend. Finding a workable gap is fast -- a
# reachable one usually falls out in a few dozen steps -- but *proving* the
# next one up impossible is not, and how long that takes depends on the size
# of the roster rather than on any one team. A fixed three seconds was enough
# for eleven people and left a nine-person roster two days short of the
# spacing it could have had, so the budget follows the roster instead.
#
# Most solves never approach it: the longest gap is settled exactly, before
# any searching, by _top_arrangement below.
TIME_BUDGET = 3.0
BUDGET_PER_TECH = 0.4
BUDGET_CEILING = 12.0


def budget_for(techs):
    """How long to allow, given how many people there are to arrange."""
    return min(BUDGET_CEILING, TIME_BUDGET + BUDGET_PER_TECH * len(techs))

# Steps between clock checks. Frequent enough to stop promptly, rare enough
# that the check is not the work.
CLOCK_EVERY = 4096

# How many different ways to break ties when handing out shifts. Each is an
# equally flat distribution with the extra days on different people, so a few
# is enough to give the search somewhere else to go when one arrangement dead
# ends -- and going further would only reshuffle names.
QUOTA_VARIANTS = 6


class Unsolvable(Exception):
    """No arrangement satisfies the constraints, even at a one-day gap."""


def _weekend_days(year, month, days):
    return {d for d in range(1, days + 1)
            if calendar.weekday(year, month, d) in (calendar.SATURDAY,
                                                    calendar.SUNDAY)}


def _allocations(days, techs, capacity, heavy, order_seed=0):
    """Hand out the month's days as evenly as the roster can carry them.

    Water-filling: the next shift always goes to whoever has fewest so far and
    can still take another. Whatever the roster size, that is the flattest
    split the month allows -- nobody more than one shift ahead of anybody else
    -- and it stays right when the split cannot be even: a small team, or
    somebody away for a fortnight who
    simply cannot carry their share. Their shifts move to whoever can, one at a
    time, so the result is the flattest distribution available rather than a
    quota nobody can work.

    Ties are broken against whoever carried the heavier load last month, so the
    extra days land on people who were spared it.
    """
    quota = {t: 0 for t in techs}
    position = {t: (i + order_seed) % len(techs) for i, t in enumerate(techs)}
    for _ in range(days):
        pool = [t for t in techs if quota[t] < capacity[t]]
        if not pool:
            return None
        pool.sort(key=lambda t: (quota[t], t in heavy, -capacity[t], position[t]))
        quota[pool[0]] += 1
    return quota


def _cycle_classes(days, gap):
    """Days grouped by where they fall in the cycle: 1, 1+gap, 1+2*gap, ..."""
    return [list(range(start, days + 1, gap)) for start in range(1, gap + 1)]


def _matching(slots, order, allowed):
    """One person per slot, or None when no such assignment exists.

    Augmenting paths, which is the simplest thing that is actually correct
    here. A month has at most thirty-one days and a roster is smaller still,
    so simple is also fast: this runs in well under a millisecond.
    """
    taken = {}                                   # person -> slot they hold

    def widen(slot, seen):
        for tech in order(slot):
            if tech in seen or not allowed(tech, slot):
                continue
            seen.add(tech)
            if tech not in taken or widen(taken[tech], seen):
                taken[tech] = slot
                return True
        return False

    for slot in slots:
        if not widen(slot, set()):
            return None
    return {slot: tech for tech, slot in taken.items()}


def _top_arrangement(days, techs, gap, weekend, weekend_cap, unavailable, last,
                     heavy, weekend_wanted):
    """The longest possible gap, settled exactly instead of searched for.

    At the longest gap a roster can support, the month has no freedom left in
    it. Every run of `gap` consecutive days must use `gap` different people,
    and there are only that many, so each run is all of them; slide the run one
    day and the same reasoning makes day d and day d + gap the same person.
    The month is therefore a cycle, and the only question is who takes each
    position in it -- which is a matching, not a search.

    That matters because this is the question the search is worst at. Eleven
    people at a gap of eleven ran twelve million steps and was still undecided
    after forty-five seconds; ten people at ten took thirty seconds to prove
    impossible. Both are settled here in a few hundred comparisons, and a
    failure is a proof rather than a timeout -- so when this says no, the
    caller drops a day knowing it gave up nothing.

    Returns (assignments, shifts each) or None when no cycle fits.
    """
    classes = _cycle_classes(days, gap)
    weekends = [sum(1 for d in c if d in weekend) for c in classes]
    # A position carrying more weekend days than one person may take is a
    # position nobody can fill, whoever else is free.
    if any(w > weekend_cap for w in weekends):
        return None

    longest = max(len(c) for c in classes)

    def allowed(tech, slot):
        if classes[slot][0] - last[tech] < gap:
            return False            # too close to their last shift last month
        away = unavailable.get(tech, ())
        return all(day not in away for day in classes[slot])

    # Ties break on where someone sits in the roster, never on their name:
    # the order handed in is what reroll varies, and a name-ordered tie-break
    # would quietly ignore it and hand back the same month every time.
    rank = {t: i for i, t in enumerate(techs)}

    def order(slot):
        # Whoever carried the heavier load last month is spared the longer
        # positions, and a weekend goes first to whoever missed one.
        heavier = len(classes[slot]) == longest
        wants = weekends[slot] > 0
        return sorted(techs, key=lambda t: ((t in heavy) if heavier
                                            else (t not in heavy),
                                            not (wants and t in weekend_wanted),
                                            rank[t]))

    # Longest positions first: they are the constrained ones, and a matching
    # that is going to fail should fail early.
    slots = sorted(range(len(classes)), key=lambda r: (-len(classes[r]), r))
    match = _matching(slots, order, allowed)
    if match is None:
        return None

    result, quota = {}, {t: 0 for t in techs}
    for slot, tech in match.items():
        for day in classes[slot]:
            result[day] = tech
        quota[tech] = len(classes[slot])
    return result, quota


def _capacity(days, techs, unavailable):
    """How many days each person is actually available to be scheduled."""
    return {t: days - len(unavailable.get(t, ())) for t in techs}


def _try(days, techs, quota, last, weekend, weekend_wanted, gap, deadline,
         weekend_cap, unavailable):
    """Fill every day, or return None. Depth-first over days, most-rested first."""
    assigned = {}
    used_weekend = {t: 0 for t in techs}
    steps = [0]
    # Weekend days from each day to the end of the month, so the count below is
    # a lookup rather than a loop.
    remaining_weekends = [0] * (days + 2)
    for d in range(days, 0, -1):
        remaining_weekends[d] = remaining_weekends[d + 1] + (1 if d in weekend else 0)

    def rec(day):
        if day > days:
            return True
        steps[0] += 1
        if steps[0] % CLOCK_EVERY == 0 and time.monotonic() > deadline:
            raise TimeoutError

        # Whoever still owes shifts has to be able to fit them in the days that
        # are left, spaced by the gap. Checking that here turns most dead ends
        # into one comparison instead of a subtree: without it the search can
        # spend its whole budget discovering by exhaustion what arithmetic
        # rules out, and then report "no answer" when it means "gave up".
        for tech in techs:
            left = quota[tech]
            if left and max(day, last[tech] + gap) + (left - 1) * gap > days:
                return False

        # Every weekend day still to come needs a different person, because
        # nobody takes two. If more weekend days remain than there are people
        # left who could take one, this branch is already lost. This is the
        # bound that makes an impossible gap provable rather than merely
        # unproductive: the weekend rule, not the spacing, is usually what
        # rules one out, and without this the search discovers that only by
        # exhausting millions of arrangements.
        free_for_weekend = sum(max(0, min(quota[t],
                                          weekend_cap - used_weekend[t]))
                               for t in techs)
        if remaining_weekends[day] > free_for_weekend:
            return False

        is_weekend = day in weekend

        pool = [t for t in techs
                if quota[t] > 0
                and day not in unavailable.get(t, ())
                and day - last[t] >= gap
                and not (is_weekend and used_weekend[t] >= weekend_cap)]
        # Whoever missed a weekend last month is served first, then the most
        # rested, then whoever has most shifts left to place: the last two push
        # the hard cases early, where a dead end is cheap to discover.
        #
        # The weekend preference orders the pool rather than replacing it. As a
        # filter it made solvable months unsolvable: two people with one away a
        # fortnight has exactly one workable split, and the rule refused to
        # consider it -- having served someone their weekend, it would not let
        # the search take that weekend back when the rest of the month turned
        # out to need it. A preference that cannot be set aside is a constraint,
        # and this one was never meant to be.
        pool.sort(key=lambda t: (is_weekend and t not in weekend_wanted,
                                 last[t], -quota[t]))

        for tech in pool:
            prev_last, prev_weekend = last[tech], used_weekend[tech]
            wanted = is_weekend and tech in weekend_wanted
            quota[tech] -= 1
            last[tech] = day
            if is_weekend:
                used_weekend[tech] += 1
                weekend_wanted.discard(tech)
            assigned[day] = tech

            if rec(day + 1):
                return True

            # Undo every part of the move, membership in weekend_wanted
            # included: a set left short after backtracking quietly stops
            # serving someone who is still owed a weekend.
            quota[tech] += 1
            last[tech] = prev_last
            used_weekend[tech] = prev_weekend
            if wanted:
                weekend_wanted.add(tech)
            del assigned[day]
        return False

    try:
        return (dict(assigned) if rec(1) else None), steps[0], False
    except TimeoutError:
        return None, steps[0], True


def solve(year, month, techs, supervisors, carry=None, budget=None,
          unavailable=None, quota_offset=0):
    """A month of assignments, with the largest gap the search can reach.

    `gap_proved_maximal` in the result says whether the gaps above the one
    returned were ruled out or merely abandoned when the budget ran out.

    `quota_offset` rotates which of the even splits is tried first. Every split
    is still tried, so the gap that comes back is the same one; what changes is
    which of the equally fair arrangements is found first. At its default of
    zero the search is exactly what it always was, which is what keeps the same
    roster and month giving the same answer twice. `reroll` is what passes
    anything else.
    """
    if not techs:
        raise Unsolvable("no technicians on the roster")
    carry = carry or {}
    unavailable = unavailable or {}
    days = calendar.monthrange(year, month)[1]

    # A day nobody is available for is not a hard search, it is an impossible
    # one, and saying which day beats letting the search grind and then report
    # that nothing worked.
    for day in range(1, days + 1):
        if all(day in unavailable.get(t, ()) for t in techs):
            raise Unsolvable(
                "everyone is off on %d %s -- someone has to cover it"
                % (day, calendar.month_name[month]))
    weekend = _weekend_days(year, month, days)
    heavy = set(carry.get("heavy", []))
    # Someone whose last shift is unknown is treated as long rested, which is
    # what an empty history means: nothing says they cannot start the month.
    last_seen = carry.get("last_shift", {})
    weekend_wanted = {t for t in techs if t not in set(carry.get("weekend", []))}

    # One weekend day each is a consequence rather than a rule: it is what the
    # month's weekend days divided by the roster comes to, rounded up. Nine
    # weekend days across eleven people is one each; four people cannot cover
    # nine one apiece, so for them it is three. The cap is always the fewest
    # weekend days anyone could be asked to take, whatever the roster size.
    weekend_cap = max(1, -(-len(weekend) // len(techs)))

    capacity = _capacity(days, techs, unavailable)
    if sum(capacity.values()) < days:
        raise Unsolvable(
            "not enough available days: %d to cover across the roster, %d needed"
            % (sum(capacity.values()), days))
    # Any run of `gap` consecutive days needs that many different people, so no
    # gap can exceed the roster. Tighter and cheaper than reasoning from how
    # many shifts have to fit in the month.
    ceiling = min(days, len(techs))
    deadline = time.monotonic() + (budget if budget is not None
                                   else budget_for(techs))

    def answer(result, shifts, gap, exhausted):
        return {
            "year": year,
            "month": month,
            "tech": result,
            "sup": _supervisors(year, month, days, supervisors, carry),
            "lead_supervisor": _lead(supervisors, carry),
            "gap": gap,
            # Whoever carried the heavier load last month and has drawn the
            # heaviest again. Counted from the shifts as handed out, not from
            # what is left of them: the search spends the quota as it goes, so
            # by the time it succeeds every entry is zero and every heavy name
            # would look like a repeat.
            "repeats": sorted(t for t, n in shifts.items()
                              if t in heavy and n == max(shifts.values())),
            "shifts": {t: shifts[t] for t in techs},
            # False when some attempt hit the step budget: the gap is still
            # valid, but a longer one may have been missed rather than ruled
            # out, and the caller should say so.
            "weekend_cap": weekend_cap,
            "time_off": {t: sorted(d) for t, d in unavailable.items() if d},
            "gap_proved_maximal": exhausted,
            # False when last month was never saved: the spacing inside the
            # month is right, but nothing checked it against the days before it.
            "boundary_known": bool(carry.get("boundary_known", False)),
        }

    exhausted = True        # every attempt so far finished, none ran out of time
    for gap in range(ceiling, 0, -1):
        if gap == ceiling:
            # The longest gap the roster can reach leaves the month no freedom,
            # so it is settled exactly rather than searched for. A failure here
            # is a proof, which is why the loop can drop a day without having
            # spent anything.
            forced = _top_arrangement(
                days, techs, gap, weekend, weekend_cap, unavailable,
                {t: last_seen.get(t, -999) for t in techs}, heavy,
                set(weekend_wanted))
            if forced is not None:
                return answer(forced[0], forced[1], gap, exhausted)
            continue
        variants = min(len(techs), QUOTA_VARIANTS)
        tried = []
        # Rotated, not reordered: the same splits in a different starting
        # place. _allocations only gives up when the roster runs out of
        # capacity, which no offset changes, so the break below still means
        # what it meant.
        for seed in ((s + quota_offset) % variants for s in range(variants)):
            quota = _allocations(days, techs, capacity, heavy, seed)
            if quota is None:
                break
            # Different starting points can land on the same split; searching
            # it twice costs the budget and finds the same thing.
            if quota in tried:
                continue
            tried.append(dict(quota))
            last = {t: last_seen.get(t, -999) for t in techs}
            quota_before = dict(quota)
            result, steps, gave_up = _try(days, list(techs), quota, last,
                                          weekend, set(weekend_wanted), gap,
                                          deadline, weekend_cap, unavailable)
            exhausted = exhausted and not gave_up
            if result is not None:
                return answer(result, quota_before, gap, exhausted)
    raise Unsolvable("no arrangement satisfies the constraints")


def reroll(year, month, techs, supervisors, carry=None, budget=None,
           unavailable=None, avoid=None, attempts=8, rng=None):
    """Another arrangement of the same month, or the same one if it stands alone.

    Only the technicians move. Supervisors are worked out from their own cycle
    and from last month, so they come back identical however often this is
    called -- which is the point: re-rolling the rota should not shuffle whose
    Monday it is.

    Two levers, because one is not enough. The order the roster is handed over
    in breaks ties, and a tight month has few ties to break -- twelve people
    over thirty days moved seven days of thirty. The offset picks a different
    even split to break them within, which moves who carries the extra shift,
    and that reaches arrangements the order alone never could. Both leave every
    rule standing and the gap unchanged.

    `avoid` is an arrangement or several. Pressing the button twice should not
    walk back onto a month already seen, so the caller passes everything it has
    shown; a month whose constraints leave one answer returns that answer, and
    the caller can see as much by finding it in what it passed.
    """
    import random as _random

    rng = rng or _random.Random()
    if avoid is None:
        seen = []
    elif isinstance(avoid, dict):
        seen = [avoid]
    else:
        seen = list(avoid)

    schedule = None
    for _ in range(max(1, attempts)):
        order = list(techs)
        rng.shuffle(order)
        schedule = solve(year, month, order, supervisors, carry, budget,
                         unavailable, quota_offset=rng.randrange(QUOTA_VARIANTS))
        if schedule["tech"] not in seen:
            break
    return schedule


def swap(schedule, one, other):
    """The same month with two days' technicians exchanged."""
    changed = dict(schedule)
    tech = dict(schedule["tech"])
    tech[one], tech[other] = tech[other], tech[one]
    changed["tech"] = tech
    return changed


def give(schedule, day, tech):
    """The same month with one day handed to somebody else."""
    changed = dict(schedule)
    days = dict(schedule["tech"])
    days[day] = tech
    changed["tech"] = days
    return changed


def review(schedule, unavailable=None, carry=None, roster=None):
    """How a month stands against the rules, after somebody has changed it.

    Trading days is a normal thing to want -- people swap shifts, and a rota
    that cannot accommodate that is a rota people work around rather than with.
    It is also how a month quietly acquires somebody on the Friday and the
    Sunday. So this decides nothing and reports everything: the shortest gap
    left in the month, what each person is carrying, and every rule the solver
    would have kept that the month no longer keeps.

    `carry` brings last month in, so a swap onto the 1st is measured against
    the 31st before it rather than treated as the start of time.
    """
    unavailable = unavailable or {}
    carry = carry or {}
    year, month = schedule["year"], schedule["month"]
    days = calendar.monthrange(year, month)[1]
    tech = schedule["tech"]
    people = list(roster or [])
    for name in tech.values():
        if name and name not in people:
            people.append(name)

    when = {}
    for day in sorted(tech):
        if tech[day]:
            when.setdefault(tech[day], []).append(day)

    weekend = _weekend_days(year, month, days)
    cap = max(1, -(-len(weekend) // len(people))) if people else 1
    shifts = {name: len(when.get(name, [])) for name in people}
    weekends = {name: sum(1 for d in when.get(name, []) if d in weekend)
                for name in people}

    problems, tight, gap = [], [], None
    last_seen = carry.get("last_shift", {})
    for name in sorted(when):
        worked = when[name]
        before = last_seen.get(name)
        if before is not None:
            span = worked[0] - before
            gap = span if gap is None else min(gap, span)
        for first, second in zip(worked, worked[1:]):
            span = second - first
            gap = span if gap is None else min(gap, span)
            if span < schedule.get("gap", 0):
                # Not a rule broken: the month was solved for the longest gap
                # it could reach, so any trade shortens it. Worth saying, and
                # worth leaving to the people doing the trading.
                tight.append((span, "%s works the %s and the %s, %d day%s apart"
                              % (name, _ordinal(first), _ordinal(second),
                                 span, "" if span == 1 else "s")))
        if weekends.get(name, 0) > cap:
            problems.append("%s has %d weekend days; the most anyone need take "
                            "is %d" % (name, weekends[name], cap))
        for day in worked:
            if day in unavailable.get(name, ()):
                problems.append("%s is away on the %s" % (name, _ordinal(day)))
    covered = [d for d in range(1, days + 1) if tech.get(d)]
    if len(covered) < days:
        missing = [d for d in range(1, days + 1) if not tech.get(d)]
        problems.append("nobody is on the %s"
                        % ", ".join(_ordinal(d) for d in missing[:5]))
    if shifts:
        spread = max(shifts.values()) - min(shifts.values())
        if spread > 1:
            heaviest = max(shifts, key=lambda n: shifts[n])
            lightest = min(shifts, key=lambda n: shifts[n])
            problems.append("%s now has %d shifts and %s has %d"
                            % (heaviest, shifts[heaviest], lightest,
                               shifts[lightest]))
    return {"gap": gap if gap is not None else 0, "shifts": shifts,
            "weekend": weekends, "weekend_cap": cap, "problems": problems,
            "tight": [line for _, line in sorted(tight)]}


def _ordinal(day):
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return "%d%s" % (day, suffix)


def _mondays(year, month, days):
    return [d for d in range(1, days + 1)
            if calendar.weekday(year, month, d) == calendar.MONDAY]


def _supervisors(year, month, days, supervisors, carry):
    """Mondays only, continuing the cycle where last month left it."""
    if not supervisors:
        return {}
    start = int(carry.get("supervisor_index", -1)) + 1
    return {day: supervisors[(start + i) % len(supervisors)]
            for i, day in enumerate(_mondays(year, month, days))}


def _lead(supervisors, carry):
    """Who covers the days of last month shown in the first row."""
    if not supervisors:
        return None
    index = carry.get("supervisor_index")
    if index is None:
        return None
    return supervisors[int(index) % len(supervisors)]
