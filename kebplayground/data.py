"""Loading users from a file, and making up users for testing.

Written second, because every later module needs a list of users to work on.
No scoring and no matching belongs in this file.
"""

import csv
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
]


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
            )
            users.append(user)

    return users


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
            })