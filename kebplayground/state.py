"""In-memory session state for the API layer.

There is no auth and no database in this repo — cli.py only ever reads a
CSV or makes up users for one run. So the API keeps a single demo profile
("you") in memory instead of per-user rows. Restarting the process resets
everything. That is enough to demo the real scorer and matcher end to end;
a real deployment would swap this module for a database-backed session.
"""

from dataclasses import replace

from .models import User

DEFAULT_PROFILE = User(
    id="you",
    major="Software Engineering",
    faculty="Faculty of Engineering and Design",
    year=3,
    age=21,
    mbti="INFP",
    languages=frozenset({"Korean"}),
    gender="Non-binary",
    area="Central",
    interests=frozenset(
        {"Coding", "Bouldering", "Anime", "Gaming", "Music", "Running", "Photography"}
    ),
    mode="friendship",
    preferences={},
    status="waiting",
)


class Store:
    """Everything the API needs to remember between requests."""

    def __init__(self) -> None:
        self.profile: User = DEFAULT_PROFILE
        self.signed_up: bool = False
        self.settings: dict[str, bool] = {"show_scores": True, "paused": False}
        self.history: list[dict] = []
        self.passed: set[str] = set()
        # The last computed run, so /api/profile and /api/waiting can read
        # the same cohort /api/feed just matched against, without
        # regenerating it (and getting a different set of made up people).
        self.run_cache: dict | None = None

    def reset_run(self) -> None:
        """Drop the cached run and this run's passes.

        Called whenever something that changes matching (signup,
        preferences, pause) happens, so the next feed request is not
        matched against a cohort scored under the old profile.
        """
        self.run_cache = None
        self.passed = set()

    def replace_profile(self, **fields: object) -> None:
        self.profile = replace(self.profile, **fields)
        self.signed_up = True
        self.reset_run()


store = Store()
