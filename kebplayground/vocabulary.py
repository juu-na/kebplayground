"""The registered options a user can be described by.

Every other module reads its lists from here.
data.py makes up users from these values, features.py measures them, and
constraints.py checks a stated preference against them.

This module knows nothing about matching. It only says which values exist,
and what a user is allowed to state as a preference.
"""

# Majors, grouped by the faculty that teaches them.
#
# The six faculties are the ones the University of Auckland runs as of 2026.
# Within each faculty the majors are a shortlist of the ones students most
# often name, not the full catalogue, so that two users matching on a major
# still means something.
#
# A few majors are taught in more than one faculty at UoA. Mathematics,
# Statistics and Economics are also Arts subjects. Each one is listed under a
# single faculty here, so that faculty_of gives one answer.
MAJORS: dict[str, frozenset[str]] = {
    "Faculty of Engineering and Design": frozenset({
        # The ten accredited BE(Hons) specialisations.
        "Biomedical Engineering",
        "Chemical and Materials Engineering",
        "Civil Engineering",
        "Computer Systems Engineering",
        "Electrical and Electronic Engineering",
        "Engineering Science",
        "Mechanical Engineering",
        "Mechatronics Engineering",
        "Software Engineering",
        "Structural Engineering",
        # The two non-engineering degrees in the same faculty.
        "Architectural Studies",
        "Design",
    }),
    "Faculty of Science": frozenset({
        "Chemistry",
        "Computer Science",
        "Data Science",
        "Mathematics",
        "Physics",
        "Statistics",
    }),
    "Faculty of Medical and Health Sciences": frozenset({
        "Biomedical Science",
        "Health Sciences",
        "Medical Imaging",
        "Medicine",
        "Nursing",
        "Optometry",
        "Pharmacy",
    }),
    "Business School": frozenset({
        # The BCom majors students most often take.
        "Accounting",
        "Economics",
        "Finance",
        "Management",
        "Marketing",
    }),
    "Auckland Law School": frozenset({
        "Law",
    }),
    "Faculty of Arts and Education": frozenset({
        "Communication",
        "Education",
        "English",
        "Fine Arts",
        "History",
        "Music",
    }),
}

FACULTIES = frozenset(MAJORS)
ALL_MAJORS = frozenset().union(*MAJORS.values())

# The departments a faculty is split into, and the majors each one teaches.
#
# Two majors in one department share most of their courses and their building,
# so they are closer than two majors that only share a faculty.
# features.major_similarity reads this as its middle step.
#
# Only Engineering is split so far. A major left out of every department is
# compared on its faculty alone.
DEPARTMENTS: dict[str, frozenset[str]] = {
    "Mechanical and Mechatronics Engineering": frozenset({
        "Mechanical Engineering",
        "Mechatronics Engineering",
    }),
    "Electrical, Computer and Software Engineering": frozenset({
        "Electrical and Electronic Engineering",
        "Computer Systems Engineering",
        "Software Engineering",
    }),
    "Engineering Science and Biomedical Engineering": frozenset({
        "Engineering Science",
        "Biomedical Engineering",
    }),
    "Civil and Environmental Engineering": frozenset({
        "Civil Engineering",
        "Structural Engineering",
    }),
    "Chemical and Materials Engineering": frozenset({
        "Chemical and Materials Engineering",
    }),
    "Architecture and Planning": frozenset({
        "Architectural Studies",
        "Design",
    }),
}

# Where in Auckland the user lives, used for same_area_only preference check.
AREAS = frozenset({"North", "South", "East", "West", "Central"})

# What a user speaks besides English. Everyone is assumed to speak English, so
# it is not listed here and cannot be stated as a preference.
LANGUAGES = frozenset({
    "Te Reo Māori",
    "Samoan",
    "Mandarin",
    "Cantonese",
    "Korean",
    "Japanese",
    "Hindi",
    "Tagalog",
    "Vietnamese",
    "Thai",
    "Indonesian",
    "Malay",
    "Arabic",
    "Spanish",
    "French",
    "Italian",
    "Russian",
})

# features.interest_similarity divides shared interests by the interests either
# user lists, so a longer list here lowers the score every pair can reach. Add
# to it sparingly.
INTERESTS = frozenset({
    # Screens and games
    "Coding",
    "Gaming",
    "Anime",
    # Music and performance
    "Music",
    "Dancing",
    # Making things
    "Painting/Drawing",
    "Design",
    "Photography",
    "Fashion",
    # Food and drink
    "Cooking/Baking",
    # Outdoors and travel
    "Travel",
    "Hiking",
    "Bouldering",
    "Skiing",
    # Sport
    "Running",
    "Cycling",
    "Swimming",
    "Golf",
    "Ice Skating",
    "Football",
    "Basketball",
    "Tennis/Squash",
    "Badminton",
    "Gym",
    "Yoga/Pilates",
})

MBTIS = frozenset({
    "INTJ", "INTP", "ENTJ", "ENTP",
    "INFJ", "INFP", "ENFJ", "ENFP",
    "ISTJ", "ISFJ", "ESTJ", "ESFJ",
    "ISTP", "ISFP", "ESTP", "ESFP",
})

GENDERS = frozenset({"Female", "Male", "Non-binary"})

# Most degrees run 3 or 4 years. Optometry and the conjoint degrees reach 5,
# and Medicine (MBChB) is the only one that reaches 6.
YEARS = frozenset({1, 2, 3, 4, 5, 6})

# The kinds of connection on offer. A user ticks one or both, and a pair is
# only considered when they share one. scoring.WEIGHTS gives each its own set
# of weights, so the two lists have to agree.
MODES = frozenset({"friendship", "date"})

# Where a user is up to. Only the waiting ones take part in a run. The rest
# are here so that Phase 2 has somewhere to put them.
STATUSES = frozenset({"waiting", "offered", "accepted", "declined", "met"})


def faculty_of(major: str) -> str:
    """Return the faculty that teaches one major."""
    for faculty, majors in MAJORS.items():
        if major in majors:
            return faculty
    raise ValueError(f"unknown major: {major}")


def department_of(major: str) -> str | None:
    """Return the department that teaches one major, or None.

    None means the faculty is not split into departments here, not that the
    major is unknown.
    """
    for department, majors in DEPARTMENTS.items():
        if major in majors:
            return department
    return None


# What a user may state as a preference, and the registry each one draws
# from. A key that is left out means no restriction on that feature.
#
# The hard preferences ban a pair in constraints.py. A pair banned there
# cannot be matched whatever it scores.
#
# The sign up form must ask both of these of every user, whichever mode they
# picked. "I do not mind" is an answer, and it is stored by leaving the key
# out, so an absent key here means answered rather than skipped.
HARD_PREFERENCES: dict[str, frozenset | None] = {
    # The other user's gender has to be one of these.
    "genders": GENDERS,
    # The other user's age has to sit inside this range, ends included.
    "age": None,
}

# The soft preferences only raise or lower the score. scoring.py is not
# written yet, so nothing reads them so far.
SOFT_PREFERENCES: dict[str, frozenset | None] = {
    "majors": ALL_MAJORS,
    "faculties": FACULTIES,
    "years": YEARS,
    "mbti": MBTIS,
    "languages": LANGUAGES,
    "interests": INTERESTS,
    # True when the user prefers the same area.
    "same_area_only": None,
}

PREFERENCE_KEYS = HARD_PREFERENCES | SOFT_PREFERENCES

# The two keys above that hold something other than a set of registered
# values, and so are checked on their own.
AGE = "age"
SAME_AREA_ONLY = "same_area_only"


def _validate_age(value: object) -> None:
    if not isinstance(value, tuple) or len(value) != 2:
        raise ValueError(f"{AGE} takes a pair, the lowest and the highest")
    low, high = value
    for end in (low, high):
        # bool is a subclass of int, so True would pass an isinstance check
        # on its own and be read as the age 1.
        if not isinstance(end, int) or isinstance(end, bool):
            raise ValueError(f"{AGE} takes two whole numbers, not {end!r}")
    if low > high:
        raise ValueError(f"{AGE} range starts after it ends: {low} to {high}")


def _validate_choice(key: str, value: object, registered: frozenset) -> None:
    if not isinstance(value, (set, frozenset)):
        raise ValueError(f"{key} takes a set, not {type(value).__name__}")
    if not value:
        raise ValueError(f"{key} is empty. Leave the key out to mean no restriction")
    unknown = set(value) - registered
    if unknown:
        raise ValueError(f"{key} is not registered: {', '.join(sorted(map(str, unknown)))}")


def validate_preferences(preferences: dict[str, object]) -> None:
    """Check one user's stated preferences.

    Input: the preferences dict of a user.
    Output: nothing. A stated preference that cannot be met raises
    ValueError naming the key and the value that caused it.

    An empty dict is fine and means the user will take anyone. An empty set
    is turned down, so that leaving a key out stays the only way of saying
    there is no restriction.
    """
    for key, value in preferences.items():
        if key not in PREFERENCE_KEYS:
            raise ValueError(f"unknown preference: {key}")
        if key == AGE:
            _validate_age(value)
        elif key == SAME_AREA_ONLY:
            if not isinstance(value, bool):
                raise ValueError(f"{SAME_AREA_ONLY} takes True or False, not {value!r}")
        else:
            registered = PREFERENCE_KEYS[key]
            assert registered is not None  # every other key draws from a registry
            _validate_choice(key, value, registered)
