"""Loading users from a file, and making up users for testing.

Written second, because every later module needs a list of users to work on.
No scoring and no matching belongs in this file.
"""

from pathlib import Path

from .models import User


def load_users(path: Path) -> list[User]:
    """Read users from a CSV file.

    Input: the path to a CSV file whose column names match the User fields.
    Output: a list of User objects, one for each row of data.

    To implement: open the file with csv.DictReader and turn each row into a
    User. If a required column is missing, raise an error that says which
    one, rather than letting it fail later somewhere else.

    Columns holding more than one value, such as languages and interests,
    are to be split on a chosen separator and stored as frozensets.
    """
    raise NotImplementedError


def generate_users(count: int = 100, seed: int | None = None) -> list[User]:
    """Make up users for testing and demos.

    Input: how many users to make, and an optional seed number.
    Output: a list of that many User objects with sensible made up values.

    Passing a seed makes the function return the same users every time.
    Without that, two runs of the same algorithm give different results and
    cannot be compared.

    To implement: create a random.Random using the seed, then pick each
    field from a small list of sensible values.

    The spread of values matters more than the number of users. If every
    user has the same major, every score comes out the same and the results
    say nothing.
    """
    raise NotImplementedError


def save_users(users: list[User], path: Path) -> None:
    """Write users back to a CSV file that load_users can read.

    Input: the users, and where to write them.
    Output: nothing is returned, the file is written instead.

    To implement: do the reverse of load_users, joining the frozenset fields
    with the same separator used when reading them.
    """
    raise NotImplementedError
