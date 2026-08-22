"""Turning the measurements into one score, and measuring how good a run was.

Produces S, the score table that matcher.py reads.
The result of each separate measurement is kept alongside the final score,
because llm.py needs them to explain why a pair was matched.
"""

from .models import AllowTable, ScoreTable, User

# How much each measurement counts, for each mode.
# The weights inside one mode are to add up to 1.0. That is what keeps the
# final score between 0.0 and 1.0 without any further adjustment.
# The numbers below are examples. Tune them to improve scoring accuracy.
WEIGHTS: dict[str, dict[str, float]] = {
    "lunch mate": {
        "timetable": 0.6,
        "interests": 0.2,
        "languages": 0.1,
        "age": 0.1,
        "major": 0.0,
    },
    "study buddy": {
        "major": 0.4,
        "timetable": 0.3,
        "interests": 0.15,
        "languages": 0.1,
        "age": 0.05,
    },
    "friend group": {
        "interests": 0.45,
        "timetable": 0.2,
        "age": 0.2,
        "languages": 0.15,
        "major": 0.0,
    },
    # One close friend rather than a group. Shared free time counts for more
    # than it does in friend group because the two actually have to meet, and
    # sharing a subject counts for something because they are around each
    # other anyway. Age barely matters once somebody is a close friend.
    "besties": {
        "interests": 0.4,
        "timetable": 0.25,
        "major": 0.15,
        "languages": 0.15,
        "age": 0.05,
    },
    "campus couple": {
        "interests": 0.35,
        "age": 0.25,
        "timetable": 0.2,
        "languages": 0.2,
        "major": 0.0,
    },
}


def score_pair(a: User, b: User, mode: str) -> tuple[float, dict[str, float]]:
    """Score one pair, using the weights for one mode.

    Input: two users, and the mode whose weights apply.
    Output: the final score, and the separate measurements it was built
    from, for example (0.62, {"timetable": 0.4, "major": 1.0, ...}).

    To implement: call features.measure, look up the weights for the mode,
    then multiply each measurement by its weight and add the results
    together.

    A mode that is not in WEIGHTS is to raise an error, not fall back to a
    default set of weights. A fallback would turn a typo in the command line
    argument into a run that looks like it worked.
    """
    raise NotImplementedError


def build_score_table(
    users: list[User],
    mode: str,
    allowed: AllowTable,
) -> ScoreTable:
    """Score the pairs that are allowed.

    Input: the full list of users, the mode being used, and H.
    Output: S, a dict giving the score for each allowed pair.

    To implement: go through every pair once, the same way
    constraints.build_allow_table does, skip any pair H marks as not
    allowed, and keep only the score.

    Banned pairs are left out rather than scored and ignored later. A banned
    pair cannot be matched whatever it scores, so working out its score is
    wasted. This is why constraints.py runs first.

    The separate measurements are dropped here on purpose. Anything that
    needs them calls score_pair again for the few pairs that ended up
    matched, rather than storing them for every pair.
    """
    raise NotImplementedError


# Ways of judging a finished run.
# These are what make it possible to compare one algorithm against another,
# instead of only running them.


def average_score(matches: list[tuple[str, str]], scores: ScoreTable) -> float:
    """The average score across the pairs that were matched.

    Returns 0.0 when nothing was matched.
    """
    raise NotImplementedError


def worst_off_score(matches: list[tuple[str, str]], scores: ScoreTable) -> float:
    """The lowest score any matched user was given.

    A good average can hide one user matched at 0.1. This number shows it.
    """
    raise NotImplementedError


def unmatched_count(users: list[User], matches: list[tuple[str, str]]) -> int:
    """How many users were left out of every match."""
    raise NotImplementedError


def evaluate(
    users: list[User],
    matches: list[tuple[str, str]],
    scores: ScoreTable,
    allowed: AllowTable,
) -> dict[str, float]:
    """Run all of the above and return them together.

    Output: a dict such as
        {"average": 0.61, "worst_off": 0.22, "unmatched": 4}

    To implement: call the three functions above.

    The allow table is passed in so that a check can be added for any banned
    pair that was matched anyway. That check is what catches a mistake in
    matcher.py.
    """
    raise NotImplementedError
