"""Shared data shapes.

Will not be modified once written and confirmed.
Every other module imports from here, so a change to this file forces a
change everywhere else.

This module only describes what a user looks like.
It does not make any decision on matching.
"""

from dataclasses import dataclass, field

# A pair is two user ids. The two ids are always stored in sorted order,
# so that (a, b) and (b, a) point at the same entry.
Pair = tuple[str, str]

# S, the score for every pair. Scores run from 0.0 to 1.0.
ScoreTable = dict[Pair, float]

# H, whether a pair is allowed at all. True means allowed.
AllowTable = dict[Pair, bool]

# The mode each pair was scored under. Kept apart from S so that S stays a
# plain table of floats, which the matcher and the metrics read unchanged.
ModeTable = dict[Pair, str]


@dataclass(frozen=True)
class User:
    """One participant.

    The fields below are the suggested features described in the ARCHITECTURE.
    Any change to them should be made here, not in other modules.
    """

    id: str
    major: str
    faculty: str
    year: int
    age: int
    mbti: str
    languages: frozenset[str]
    gender: str
    # Which part of Auckland the user lives in. Only ever read to work out
    # whether two users live in the same one.
    area: str
    interests: frozenset[str]
    # The kinds of connection the user is open to, one or both of
    # "friendship" and "date". A pair is only considered when they share one.
    modes: frozenset[str]
    # Anything extra, such as a preferred age range or gender preference.
    preferences: dict[str, object] = field(default_factory=dict)
    # Where the user is up to. Only "waiting" users take part in a run.
    # The rest exist so that Phase 2 does not have to change this file again.
    status: str = "waiting"


def pair_key(a: User | str, b: User | str) -> Pair:
    """Return the standard key for a pair.

    Takes either two users or two ids.
    Sorting the two ids means a lookup gives the same answer no matter which
    user is passed first.

    To implement: get the id out of each argument, then return the two ids
    as a tuple, smaller id first.
    """
    if isinstance(a, User):
        a = a.id
    if isinstance(b, User):
        b = b.id 
    
    if a < b:
        return(a, b)
    else:
        return(b, a)
