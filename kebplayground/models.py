"""Shared data shapes.

Will not be modified once written and confirmed.
Every other module imports from here, so a change to this file forces a
change everywhere else.

This module only describes what a user looks like.
It does not make any decision on matching.
"""

from dataclasses import dataclass, field

# A timetable slot is a day and an hour, written as one string,
# for example "MON-09".
Slot = str

# A pair is two user ids. The two ids are always stored in sorted order,
# so that (a, b) and (b, a) point at the same entry.
Pair = tuple[str, str]

# S, the score for every pair. Scores run from 0.0 to 1.0.
ScoreTable = dict[Pair, float]

# H, whether a pair is allowed at all. True means allowed.
AllowTable = dict[Pair, bool]


@dataclass(frozen=True)
class User:
    """One participant.

    The fields below are the suggested features described in the ARCHITECTURE.
    Any change to them should be made here, not in other modules.
    """

    id: str
    major: str
    degree: str
    year: int
    age: int
    mbti: str
    languages: frozenset[str]
    gender: str
    # How far the user lives from the city campus, in km.
    proximity_km: float
    # The slots the user is free. Any slot not listed counts as busy.
    free_slots: frozenset[Slot]
    interests: frozenset[str]
    # The kind of connection the user is after, for example
    # "lunch mate", "study buddy", "friend group", "campus couple".
    mode: str
    # Anything extra, such as a preferred age range or gender preference.
    preferences: dict[str, object] = field(default_factory=dict)


def pair_key(a: User | str, b: User | str) -> Pair:
    """Return the standard key for a pair.

    Takes either two users or two ids.
    Sorting the two ids means a lookup gives the same answer no matter which
    user is passed first.

    To implement: get the id out of each argument, then return the two ids
    as a tuple, smaller id first.
    """
    raise NotImplementedError
