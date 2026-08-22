"""Loading users from a file, and making up users for testing.

Written second, because every later module needs a list of users to work on.
No scoring and no matching belongs in this file.
"""

import csv
import json
import random
from pathlib import Path

from . import vocabulary
from .models import User

SEPARATOR = ";"

# Sorted copies of the registries. A frozenset of strings iterates in an
# order that depends on hash randomisation, which changes between processes,
# so drawing from one directly would break the seed without any single run
# noticing.
_FACULTIES = sorted(vocabulary.MAJORS)
_MAJORS_BY_FACULTY = {
    faculty: sorted(majors) for faculty, majors in vocabulary.MAJORS.items()
}
_YEARS = sorted(vocabulary.YEARS)
_MBTIS = sorted(vocabulary.MBTIS)
_GENDERS = sorted(vocabulary.GENDERS)
_AREAS = sorted(vocabulary.AREAS)
_MODES = sorted(vocabulary.MODES)
_LANGUAGES = sorted(vocabulary.LANGUAGES)
_SLOTS = sorted(vocabulary.SLOTS)
_INTERESTS = sorted(vocabulary.INTERESTS)

# How many of each a made up user is given, as the lowest and the highest.
# The slot range decides how many pairs share any free time at all, and
# constraints.py bans a pair that shares none. The interest range decides how
# often interest_similarity comes back as anything other than 0.0.
LANGUAGES_EACH = (1, 3)
SLOTS_EACH = (4, 9)
INTERESTS_EACH = (5, 10)

# How many preferences a made up user states, and how often each count comes
# up. Most people take anyone or nearly anyone, and a few are specific enough
# to rule out almost everybody, so the weights fall away sharply.
PREFERENCE_COUNTS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)
PREFERENCE_WEIGHTS = (30, 22, 16, 12, 8, 5, 3, 2, 1, 1)

_PREFERENCE_KEYS = sorted(vocabulary.PREFERENCE_KEYS)

# What each preference is drawn from, and the most a made up user names at
# once. The two keys left out hold something other than a set of registered
# values, so they are built on their own.
_PREFERENCE_VALUES: dict[str, tuple[list, int]] = {
    "genders": (sorted(vocabulary.GENDERS), 2),
    "majors": (sorted(vocabulary.ALL_MAJORS), 3),
    "faculties": (_FACULTIES, 2),
    "years": (_YEARS, 3),
    "mbti": (_MBTIS, 4),
    "languages": (_LANGUAGES, 2),
    "interests": (_INTERESTS, 4),
}

REQUIRED_FIELDS = [
    "id",
    "major",
    "faculty",
    "year",
    "age",
    "mbti",
    "languages",
    "gender",
    "area",
    "free_slots",
    "interests",
    "mode",
    "preferences",
]


def _encode_preferences(preferences: dict[str, object]) -> str:
    """Turn one user's preferences into the JSON that goes in the column.

    Sets are written as sorted lists and the age range as a pair, because
    JSON has neither. Sorting keeps the column the same from one save to the
    next, so two files can be compared.
    """
    plain: dict[str, object] = {}
    for key, value in preferences.items():
        if isinstance(value, (set, frozenset)):
            plain[key] = sorted(value)
        elif isinstance(value, tuple):
            plain[key] = list(value)
        else:
            plain[key] = value
    return json.dumps(plain, ensure_ascii=False, sort_keys=True)


def _decode_preferences(val: str) -> dict[str, object]:
    """Read the column back, rebuilding the sets and the age range.

    The result has to come back as the same shapes it went in as, since two
    users only count as equal when their preferences are equal.
    """
    if not val or not val.strip():
        return {}

    preferences: dict[str, object] = {}
    for key, value in json.loads(val).items():
        if vocabulary.PREFERENCE_KEYS.get(key) is not None:
            preferences[key] = frozenset(value)
        elif key == vocabulary.AGE:
            preferences[key] = tuple(value)
        else:
            # Anything else is left as it came, including a key that is not
            # in the schema at all, which validate_preferences then names.
            preferences[key] = value

    vocabulary.validate_preferences(preferences)
    return preferences


def _parse_frozenset(val: str) -> frozenset[str]:
    if not val or not val.strip():
        return frozenset()
    return frozenset(item.strip() for item in val.split(SEPARATOR) if item.strip())


def load_users(path: Path) -> list[User]:
    path = Path(path)
    users = []

    with path.open(mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        fieldnames = reader.fieldnames or []
        for required in REQUIRED_FIELDS:
            if required not in fieldnames:
                raise ValueError(f"Missing required column in CSV: '{required}'")

        for row in reader:
            user = User(
                id=str(row["id"]),
                major=str(row["major"]),
                faculty=str(row["faculty"]),
                year=int(row["year"]),
                age=int(row["age"]),
                mbti=str(row["mbti"]),
                languages=_parse_frozenset(row["languages"]),
                gender=str(row["gender"]),
                area=str(row["area"]),
                free_slots=_parse_frozenset(row["free_slots"]),
                interests=_parse_frozenset(row["interests"]),
                mode=str(row["mode"]),
                preferences=_decode_preferences(row["preferences"]),
            )
            users.append(user)

    return users


def _make_preferences(rng: random.Random) -> dict[str, object]:
    """Give one made up user anywhere from no preferences to a very specific
    set of them."""
    how_many = rng.choices(PREFERENCE_COUNTS, weights=PREFERENCE_WEIGHTS)[0]
    stated = rng.sample(_PREFERENCE_KEYS, k=how_many)

    preferences: dict[str, object] = {}
    for key in sorted(stated):
        if key == vocabulary.AGE:
            low = rng.randint(18, 24)
            preferences[key] = (low, low + rng.randint(0, 6))
        elif key == vocabulary.SAME_AREA_ONLY:
            # Stating it as False says the same as leaving the key out, so
            # the only version worth making up is True.
            preferences[key] = True
        else:
            registered, most = _PREFERENCE_VALUES[key]
            preferences[key] = frozenset(rng.sample(registered, k=rng.randint(1, most)))

    return preferences


def generate_users(count: int = 100, seed: int | None = None) -> list[User]:
    rng = random.Random(seed)

    users = []
    for i in range(count):
        num_langs = rng.randint(*LANGUAGES_EACH)
        num_slots = rng.randint(*SLOTS_EACH)
        num_interests = rng.randint(*INTERESTS_EACH)

        # The faculty comes first so that the major can be one it teaches.
        faculty = rng.choice(_FACULTIES)

        user = User(
            id=f"user_{i+1:04d}",
            major=rng.choice(_MAJORS_BY_FACULTY[faculty]),
            faculty=faculty,
            year=rng.choice(_YEARS),
            age=rng.randint(18, 25),
            mbti=rng.choice(_MBTIS),
            languages=frozenset(rng.sample(_LANGUAGES, k=num_langs)),
            gender=rng.choice(_GENDERS),
            area=rng.choice(_AREAS),
            free_slots=frozenset(rng.sample(_SLOTS, k=num_slots)),
            interests=frozenset(rng.sample(_INTERESTS, k=num_interests)),
            mode=rng.choice(_MODES),
            preferences=_make_preferences(rng),
        )
        users.append(user)

    return users


def save_users(users: list[User], path: Path) -> None:
    path = Path(path)

    with path.open(mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REQUIRED_FIELDS)
        writer.writeheader()

        for u in users:
            writer.writerow({
                "id": u.id,
                "major": u.major,
                "faculty": u.faculty,
                "year": u.year,
                "age": u.age,
                "mbti": u.mbti,
                "languages": SEPARATOR.join(sorted(u.languages)),
                "gender": u.gender,
                "area": u.area,
                "free_slots": SEPARATOR.join(sorted(u.free_slots)),
                "interests": SEPARATOR.join(sorted(u.interests)),
                "mode": u.mode,
                "preferences": _encode_preferences(u.preferences),
            })