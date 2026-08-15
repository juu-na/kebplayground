"""Measuring how alike two users are.

This module only measures. It does not decide whether a pair is a good match,
and it does not know that matching exists at all.

Each function below takes two users and returns a number from 0.0 to 1.0,
where 1.0 means the two are the same on that one thing, and 0.0 means they
have nothing in common on it.

Every function uses the same 0.0 to 1.0 range on purpose. That is what makes
it possible for scoring.py to weigh one measurement against another.
"""

from .models import User


def timetable_overlap(a: User, b: User) -> float:
    """How much of their free time the two users share.

    To implement: count the slots both users have free, then divide by the
    count of slots either of them has free.

    If neither user has any free slot, return 0.0 instead of dividing by
    zero.
    """
    raise NotImplementedError


def major_similarity(a: User, b: User) -> float:
    """How close the two subjects of study are.

    To implement: return 1.0 when the two majors are the same.

    Returning 0.0 for everything else is a fine first version. Giving a
    middle value to two different majors in the same faculty is optional.
    """
    raise NotImplementedError


def interest_similarity(a: User, b: User) -> float:
    """How many interests the two users share.

    To implement: count the interests both users list, then divide by the
    count of interests either of them lists. This is the same sum as
    timetable_overlap.
    """
    raise NotImplementedError


def language_similarity(a: User, b: User) -> float:
    """Whether the two users share a language they can talk in.

    To implement: having one language in common is what matters, having
    three in common is not three times better. Returning either 1.0 or 0.0
    is reasonable here.
    """
    raise NotImplementedError


def proximity_similarity(a: User, b: User) -> float:
    """How similar the two commutes are.

    To implement: take the difference between the two proximity_km values,
    ignoring the sign, then turn it into a number from 0.0 to 1.0 where a
    smaller difference gives a higher result.

    This needs a cut-off distance, past which the result is simply 0.0.
    Choosing that distance is part of the task.
    """
    raise NotImplementedError


def age_similarity(a: User, b: User) -> float:
    """How close the two users are in age.

    To implement: the same approach as proximity_similarity, using age
    instead of distance.
    """
    raise NotImplementedError


# Every measurement, listed by the name used in the score breakdown and in
# the weights in scoring.py.
# Adding a function to this list makes it apply to every mode at once.
FEATURES = {
    "timetable": timetable_overlap,
    "major": major_similarity,
    "interests": interest_similarity,
    "languages": language_similarity,
    "proximity": proximity_similarity,
    "age": age_similarity,
}


def measure(a: User, b: User) -> dict[str, float]:
    """Run every measurement on one pair.

    Input: two users.
    Output: the name of each measurement and its result, for example
        {"timetable": 0.4, "major": 1.0, "interests": 0.25, ...}

    To implement: call each function in FEATURES and collect the answers
    into one dict.
    """
    raise NotImplementedError
