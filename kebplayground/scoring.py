"""Turning the measurements into one score, and measuring how good a run was.

Produces S, the score table that matcher.py reads.
The result of each separate measurement is kept alongside the final score,
because llm.py needs them to explain why a pair was matched.
"""

import itertools

from .models import AllowTable, ScoreTable, User, pair_key
from . import features


# How much each measurement counts, for each mode.
# The weights inside one mode are to add up to 1.0. That is what keeps the
# final score between 0.0 and 1.0 without any further adjustment.
# The numbers below are examples. Tune them to improve scoring accuracy.
WEIGHTS: dict[str, dict[str, float]] = {
    "friendship": {
        "interests": 0.35,
        "mbti": 0.15,
        "major": 0.15,
        "languages": 0.15,
        "age": 0.10,
        "year": 0.05,
        "area": 0.05,
    },
    "date": {
        "interests": 0.25,
        "mbti": 0.25,
        "age": 0.20,
        "languages": 0.15,
        "area": 0.10,
        "major": 0.05,
        "year": 0.00,
    },
}

# The lowest a pair may score and still be worth offering. A few real matches
# are better than many average ones, so a pair under this is left out and both
# users keep waiting. cli.py can override it with --min-score.
MIN_MATCH_SCORE = 0.6


def _direction(seen: dict[str, float], weights: dict[str, float]) -> float:
    """One user's view of another, as a single number.

    Divided by the weights of whatever measurements came back rather than by
    1.0, because features.view leaves area out unless somebody asked for it.
    Without the divisor every pair would quietly lose the area weight for a
    question nobody asked.
    """
    live = {name: weights[name] for name in seen}
    return sum(seen[name] * weight for name, weight in live.items()) / sum(live.values())


def score_pair(a: User, b: User) -> tuple[float, str, dict[str, float]]:
    """Score one pair, under the best kind of connection they both want.

    Input: two users.
    Output: the score, the mode it was scored under, and the measurements it
    was built from.

    Each user sees the other differently, because a stated preference lifts
    the measurements it speaks for. The pair takes the lower of the two
    views: a match one person is lukewarm about is a lukewarm match, whatever
    the other one thinks.

    The age preference bans in constraints.py and does not lift age_similarity
    here, so the age weight scores how close two people are inside a range
    that was already allowed. Somebody who said 20 to 30 has not said whether
    21 or 29 suits them better.

    Users open to nothing in common should have been banned by H, so reaching
    this with no shared mode is a mistake worth hearing about.
    """
    shared = a.modes & b.modes
    if not shared:
        raise ValueError(f"{a.id} and {b.id} want no kind of connection in common")

    best = None
    for mode in sorted(shared):
        weights = WEIGHTS[mode]
        forwards = _direction(features.view(a, b), weights)
        backwards = _direction(features.view(b, a), weights)
        # The breakdown comes from whichever side liked it less, since that
        # is the side a message has to win over.
        if forwards <= backwards:
            score, seen = forwards, features.view(a, b)
        else:
            score, seen = backwards, features.view(b, a)
        # A tie goes to date, because somebody who ticked both and found a
        # good date match is better served by the date message.
        if best is None or score > best[0] or (score == best[0] and mode == "date"):
            best = (score, mode, seen)

    return best


def build_score_table(
    users: list[User],
    allowed: AllowTable,
    floor: float = MIN_MATCH_SCORE,
) -> tuple[ScoreTable, ModeTable, AllowTable]:
    """Score the pairs that are allowed, and drop the ones not worth offering.

    Input: the full list of users, H, and the lowest score worth offering.
    Output: S, the mode each pair was scored under, and a fresh H with the
    pairs under the floor marked False.

    A new H comes back rather than the one that went in being edited, so a
    caller that still wants the unfiltered table has it. Anything reading
    either table then agrees on which pairs are live.

    The separate measurements are dropped here on purpose. Anything that
    needs them calls score_pair again for the few pairs that ended up
    matched, rather than storing them for every pair.
    """
    scores: ScoreTable = {}
    modes: ModeTable = {}
    live = dict(allowed)

    for one, other in itertools.combinations(users, 2):
        key = pair_key(one, other)
        if not allowed.get(key):
            continue

        score, mode, _ = score_pair(one, other)
        if score < floor:
            live[key] = False
            continue

        scores[key] = score
        modes[key] = mode

    return scores, modes, live


# Ways of judging a finished run.
# These are what make it possible to compare one algorithm against another,
# instead of only running them.


def average_score(matches: list[tuple[str, str]], scores: ScoreTable) -> float:
    """The average score across the pairs that were matched.

    Returns 0.0 when nothing was matched.
    """
    if not matches:
        return 0.0
    return sum(scores[pair_key(a, b)] for a, b in matches) / len(matches)


def worst_off_score(matches: list[tuple[str, str]], scores: ScoreTable) -> float:
    """The lowest score any matched user was given.

    A good average can hide one user matched at 0.1. This number shows it.
    """
    if not matches:
        return 0.0
    return min(scores[pair_key(a, b)] for a, b in matches)


def unmatched_count(users: list[User], matches: list[tuple[str, str]]) -> int:
    """How many users were left out of every match."""
    known = {user.id for user in users}
    matched_ids = {uid for pair in matches for uid in pair}
    strangers = matched_ids - known
    if strangers:
        raise ValueError(f"matched somebody who is not in the list: {sorted(strangers)}")
    return len(known - matched_ids)


def evaluate(
    users: list[User],
    matches: list[tuple[str, str]],
    scores: ScoreTable,
    modes: ModeTable,
    allowed: AllowTable,
) -> dict[str, object]:
    """Judge a finished run, one report per kind of connection.

    Output: a dict holding a block per mode, and the users still waiting.

    Waiting users are listed rather than counted against the run. Somebody
    nobody suits yet has not been failed, they are waiting for the next one,
    which is what the app promises.
    """
    for a, b in matches:
        if not allowed.get(pair_key(a, b)):
            raise ValueError(f"matcher produced a banned pair: {(a, b)}")

    per_mode: dict[str, dict[str, float]] = {}
    for mode in sorted(WEIGHTS):
        of_mode = [pair for pair in matches if modes.get(pair_key(*pair)) == mode]
        per_mode[mode] = {
            "pairs": len(of_mode),
            "total": round(sum(scores[pair_key(*pair)] for pair in of_mode), 4),
            "average": round(average_score(of_mode, scores), 4),
            "worst_off": round(worst_off_score(of_mode, scores), 4),
        }

    matched = {uid for pair in matches for uid in pair}
    return {
        "modes": per_mode,
        "waiting": sorted(user.id for user in users if user.id not in matched),
    }
