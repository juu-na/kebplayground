"""Loading users from a file, and making up users for testing.

Written second, because every later module needs a list of users to work on.
No scoring and no matching belongs in this file.
"""

import csv
import random
from pathlib import Path

from .models import User

SEPARATOR = ";"

REQUIRED_FIELDS = [
    "id",
    "major",
    "faculty",
    "year",
    "age",
    "mbti",
    "languages",
    "gender",
    "proximity_km",
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
                proximity_km=float(row["proximity_km"]),
                free_slots=_parse_frozenset(row["free_slots"]),
                interests=_parse_frozenset(row["interests"]),
                mode=str(row["mode"]),
            )
            users.append(user)

    return users


def generate_users(count: int = 100, seed: int | None = None) -> list[User]:
    rng = random.Random(seed)

    majors = ["Computer Science", "Engineering", "Business", "Psychology", "Arts", "Biology",]
    faculties = ["Science", "Engineering", "Business School", "Arts", "Medical School"]
    mbtis = ["INTJ", "ENFP", "ISTJ", "INFJ", "ENTP", "ESFP", "INTP", "ENFJ"]
    genders = ["Female", "Male", "Non-binary"]
    modes = ["lunch mate", "study buddy", "friend group", "campus couple"]

    lang_pool = ["English", "Korean", "Mandarin", "Spanish", "Japanese","chinese"]
    slot_pool = ["Mon_AM", "Mon_PM", "Tue_AM", "Tue_PM", "Wed_AM", "Wed_PM", "Thu_AM", "Thu_PM", "Fri_AM", "Fri_PM"]
    interest_pool = ["Coding", "Music", "Gaming", "Cooking", "Reading", "Sports", "Movies", "Hiking"]

    users = []
    for i in range(count):
        num_langs = rng.randint(1, 3)
        num_slots = rng.randint(1, 5)
        num_interests = rng.randint(1, 4)

        user = User(
            id=f"user_{i+1:04d}",
            major=rng.choice(majors),
            faculty=rng.choice(faculties),
            year=rng.randint(1, 4),
            age=rng.randint(18, 25),
            mbti=rng.choice(mbtis),
            languages=frozenset(rng.sample(lang_pool, k=num_langs)),
            gender=rng.choice(genders),
            proximity_km=round(rng.uniform(0.5, 25.0), 1),
            free_slots=frozenset(rng.sample(slot_pool, k=num_slots)),
            interests=frozenset(rng.sample(interest_pool, k=num_interests)),
            mode=rng.choice(modes),
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
                "proximity_km": u.proximity_km,
                "free_slots": SEPARATOR.join(sorted(u.free_slots)),
                "interests": SEPARATOR.join(sorted(u.interests)),
                "mode": u.mode,
            })