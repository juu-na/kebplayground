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
# A few majors are taught in more than one faculty at UoA. Psychology,
# Mathematics, Statistics and Geography are also Arts subjects, and Economics
# is also an Arts subject. Each one is listed under a single faculty here, so
# that faculty_of gives one answer.
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
        # The three non-engineering degrees in the same faculty.
        "Architectural Studies",
        "Design",
        "Urban Planning",
    }),
    "Faculty of Science": frozenset({
        "Chemistry",
        "Computer Science",
        "Data Science",
        "Environmental Science",
        "Marine Science",
        "Mathematics",
        "Physics",
        "Physiology",
        "Psychology",
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
        # The thirteen BCom majors.
        "Accounting",
        "Business Analytics",
        "Commercial Law",
        "Economics",
        "Finance",
        "Information Systems",
        "Innovation and Entrepreneurship",
        "International Business",
        "Management",
        "Marketing",
        "Operations and Supply Chain Management",
        "Property",
        "Taxation",
    }),
    "Auckland Law School": frozenset({
        "Law",
    }),
    "Faculty of Arts and Education": frozenset({
        "Anthropology",
        "Communication",
        "Criminology",
        "Education",
        "English",
        "Fine Arts",
        "History",
        "Linguistics",
        "Media and Screen Studies",
        "Music",
        "Māori Studies",
        "Philosophy",
        "Politics and International Relations",
        "Sociology",
    }),
}

FACULTIES = frozenset(MAJORS)
ALL_MAJORS = frozenset().union(*MAJORS.values())

# Where in Auckland the user lives, so a commute can be worked out without
# asking anyone for a distance.
AREAS = frozenset({"North", "South", "East", "West", "Central"})

# What a user speaks besides English. Everyone is assumed to speak English, so
# it is not listed here and cannot be stated as a preference.
#
# The list follows the languages the 2023 Census counted most speakers for in
# New Zealand, weighted towards Auckland, which is home to about 70 percent of
# the country's Chinese and Korean populations.
LANGUAGES = frozenset({
    "Te Reo Māori",
    "Samoan",
    "Tongan",
    "Fijian",
    "Mandarin",
    "Cantonese",
    "Korean",
    "Japanese",
    "Hindi",
    "Punjabi",
    "Tamil",
    "Tagalog",
    "Vietnamese",
    "Thai",
    "Indonesian",
    "Malay",
    "Arabic",
    "Afrikaans",
    "Dutch",
    "Spanish",
    "French",
    "Italian",
    "German",
    "Portuguese",
    "Russian",
})

# features.interest_similarity divides shared interests by the interests either
# user lists, so a longer list here lowers the score every pair can reach. Add
# to it sparingly.
INTERESTS = frozenset({
    # Screens and games
    "Coding",
    "Gaming",
    "Board Games",
    "Chess",
    "Puzzles",
    "Anime",
    "Movies",
    "Hackathons",
    # Music and performance
    "Music",
    "Karaoke",
    "Singing",
    "Playing an Instrument",
    "Concerts",
    "Theatre",
    "Dancing",
    # Making things
    "Art",
    "Drawing",
    "Painting",
    "Pottery",
    "Design",
    "Photography",
    "Video Editing",
    "Fashion",
    "Sewing",
    "Reading",
    "Writing",
    # Food and drink
    "Cooking",
    "Baking",
    "Coffee",
    # Outdoors and travel
    "Travel",
    "Hiking",
    "Climbing",
    "Bouldering",
    "Surfing",
    "Skiing",
    "Beach",
    "Gardening",
    # Sport
    "Running",
    "Cycling",
    "Swimming",
    "Golf",
    "Ice Skating",
    "Football",
    "Basketball",
    "Netball",
    "Rugby",
    "Cricket",
    "Tennis",
    "Badminton",
    "Table Tennis",
    "Squash",
    "Martial Arts",
    "Gym",
    "Yoga",
    "Pilates",
    # Other
    "Museums",
    "Debating",
    "Volunteering",
    "Startups",
    "Investing",
    "Pets",
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


# What a user may state as a preference, and the registry each one draws
# from. A key that is left out means no restriction on that feature.
#
# The hard preferences ban a pair in constraints.py. A pair banned there
# cannot be matched whatever it scores.
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
