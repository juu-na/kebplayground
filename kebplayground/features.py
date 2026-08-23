"""Measuring how alike two users are.

This module only measures. It does not decide whether a pair is a good match,
and it does not know that matching exists at all.

Each function below takes two users and returns a number from 0.0 to 1.0,
where 1.0 means the two are the same on that one thing, and 0.0 means they
have nothing in common on it.

Every function uses the same 0.0 to 1.0 range on purpose. That is what makes
it possible for scoring.py to weigh one measurement against another.
"""

from . import vocabulary
from .models import User

# How major_similarity is split. The three add up to 1.0, so two people on the
# same major score 1.0, two in the same department 0.8, and two who only share
# a faculty 0.6.
#
# The department step is what stops a single faculty cohort collapsing. Every
# pair there pays the faculty weight in full, so without it Mechatronics sits
# exactly as far from Mechanical as from Structural.
FACULTY_WEIGHT = 0.6
DEPARTMENT_WEIGHT = 0.2
MAJOR_WEIGHT = 0.2

#이과 = 1, 문과 = 0 ??
# One entry for every faculty in vocabulary.FACULTIES. A faculty missing here
# makes major_similarity raise on anyone studying in it.
FACULTY_TECHINESS = {
    "Faculty of Engineering and Design": 1.0,
    "Faculty of Science": 0.8,
    "Faculty of Medical and Health Sciences": 0.6,
    "Business School": 0.4,
    "Auckland Law School": 0.2,
    "Faculty of Arts and Education": 0.0,
}


def major_similarity(a: User, b: User) -> float:
    """How close the two subjects of study are.

    Three steps, from the widest to the narrowest: the faculty, the
    department inside it, and the major itself. Two people in different
    faculties get part of the faculty weight, scaled by how far apart the two
    faculties sit on FACULTY_TECHINESS.
    """
    score = 0.0

    if a.faculty == b.faculty:
        score += FACULTY_WEIGHT
    else:
        a_score = FACULTY_TECHINESS.get(a.faculty)
        b_score = FACULTY_TECHINESS.get(b.faculty)
        if a_score is None or b_score is None:
            unknown = a.faculty if a_score is None else b.faculty
            raise ValueError(f"no teachiness score for faculty: {unknown}")
        score += FACULTY_WEIGHT * (1 - abs(a_score - b_score))

    # The same major counts as the same department, so that a faculty with no
    # departments listed can still reach 1.0.
    department = vocabulary.department_of(a.major)
    if a.major == b.major or (
        department is not None and department == vocabulary.department_of(b.major)
    ):
        score += DEPARTMENT_WEIGHT

    if a.major == b.major:
        score += MAJOR_WEIGHT

    return score


def interest_similarity(a: User, b: User) -> float:
    """How many interests the two users share.

    To implement: count the interests both users list, then divide by the
    count of interests either of them lists. This is the same sum as
    timetable_overlap.
    """

    shared_interest = a.interests & b.interests
    num_shared_interest = len(shared_interest)
    total_interest = a.interests | b.interests
    num_total_interest = len(total_interest)
    if not num_shared_interest:
        return 0.0
    return num_shared_interest/num_total_interest


# vocabulary.LANGUAGES leaves English out because everyone is taken to speak
# it. Two users who list nothing in common therefore still have English, and
# that one shared language is what ENGLISH_ONLY stands for.
ENGLISH_ONLY = 0.4
# What each further shared language adds, in order. The steps get smaller
# because the first language two people share does most of the work, and they
# run out after three, so a fifth shared language counts for nothing.
FURTHER_LANGUAGES = (0.3, 0.2, 0.1)


def language_similarity(a: User, b: User) -> float:
    """How many languages the two users can talk in.

    Sharing a language on top of English is worth something, and a second and
    a third are worth a little less each time. The steps stop after that, so
    a long list cannot outweigh everything else.
    """
    shared = len(a.languages & b.languages)
    # The steps add up to exactly 1.0, but only to within the rounding error
    # of adding floats, so the result is held to the top of the range.
    return min(1.0, ENGLISH_ONLY + sum(FURTHER_LANGUAGES[:shared]))


def age_similarity(a: User, b: User) -> float:
    """How close the two users are in age.

    Ten years apart or more counts as nothing in common. Anything closer
    than that scores higher the smaller the gap is.
    """
    difference = abs(a.age - b.age)
    if difference > 10:
        return 0.0
    else:
        score = (10 - difference)/10
        return score

def mbti_similarity(a: User, b: User) -> float:
    """Score MBTI compatibility from 0.0 (worst) to 1.0 (best)."""
    a, b = a.mbti.upper(), b.mbti.upper()
    score = 0
    score += 2 if a[1] == b[1] else 0   # S/N: same is best (weighted x2, most important)
    score += 1 if a[0] != b[0] else 0   # E/I: opposite is best
    score += 1 if a[2] == b[2] else 0   # T/F: same is best
    score += 1 if a[3] != b[3] else 0   # J/P: opposite is best
    score /= 5
    return score

def year_similarity(a: User, b: User) -> float:
    """How close the two are in their degree.

    The year above or below is close enough to have something in common.
    Any further apart and they are not really at the same point.
    """
    difference = abs(a.year - b.year)
    if difference == 0:
        return 1.0
    if difference == 1:
        return 0.5
    return 0.0


def area_similarity(a: User, b: User) -> float:
    """Whether the two live in the same part of Auckland.

    Only ever read when somebody asked for it. view leaves it out otherwise,
    because where a person lives says nothing about whether they get on.
    """
    return 1.0 if a.area == b.area else 0.0


# Every measurement, listed by the name used in the score breakdown and in
# the weights in scoring.py.
# Adding a function to this list makes it apply to every mode at once.
FEATURES = {
    "major": major_similarity,
    "interests": interest_similarity,
    "languages": language_similarity,
    "age": age_similarity,
    "mbti": mbti_similarity,
    "year": year_similarity,
    "area": area_similarity,
}

# The measurement that is only scored when somebody asked for it.
AREA = "area"

# Which measurement each stated preference speaks for. Two of them speak for
# the same one, and then both have to be satisfied.
PREFERENCE_FEATURE = {
    "majors": "major",
    "faculties": "major",
    "mbti": "mbti",
    "languages": "languages",
    "interests": "interests",
    "years": "year",
    "same_area_only": AREA,
}


def _stated(key: str, preferences: dict[str, object]) -> bool:
    """Whether the user actually asked for something under this key.

    same_area_only set to False says the same as leaving it out, so it does
    not count as asking.
    """
    if key not in preferences:
        return False
    if key == "same_area_only":
        return preferences[key] is True
    return True


def _met(key: str, a: User, b: User) -> bool:
    """Whether b satisfies what a asked for under one key."""
    wanted = a.preferences[key]
    if key == "majors":
        return b.major in wanted
    if key == "faculties":
        return b.faculty in wanted
    if key == "mbti":
        return b.mbti in wanted
    if key == "languages":
        return bool(b.languages & wanted)
    if key == "interests":
        return bool(b.interests & wanted)
    if key == "years":
        return b.year in wanted
    if key == "same_area_only":
        return a.area == b.area
    raise ValueError(f"no rule for the preference: {key}")


def _bumped(name: str, a: User, b: User) -> bool:
    """Whether a asked for something about this measurement and b meets it.

    majors and faculties both speak for major, so when a stated both, b has
    to satisfy both to earn the bump.
    """
    asked = [
        key
        for key, feature in PREFERENCE_FEATURE.items()
        if feature == name and _stated(key, a.preferences)
    ]
    return bool(asked) and all(_met(key, a, b) for key in asked)


def view(a: User, b: User) -> dict[str, float]:
    """How a sees b, one number per measurement.

    A stated preference lifts its measurement to 1.0 when b satisfies it.
    When b does not, the measurement falls back to what it would have scored
    anyway, so asking for something can only ever help the person asking.

    Area is the one exception. Living in the same part of town says nothing
    about whether two people get on, so it is left out entirely unless a
    asked for it and b is there. scoring.py divides by the weights of
    whatever came back, so leaving it out costs nobody anything.

    This is the function that makes a pair's two directions differ.
    """
    seen = {}
    for name, rule in FEATURES.items():
        if name == AREA:
            continue
        seen[name] = 1.0 if _bumped(name, a, b) else rule(a, b)

    if _bumped(AREA, a, b):
        seen[AREA] = 1.0

    return seen


def measure(a: User, b: User) -> dict[str, float]:
    """Run every measurement on one pair.

    Input: two users.
    Output: the name of each measurement and its result, for example
        {"timetable": 0.4, "major": 1.0, "interests": 0.25, ...}

    To implement: call each function in FEATURES and collect the answers
    into one dict.
    """
    output = {}

    for features, fn in FEATURES.items():
        output[features] = fn(a, b)
    return output
