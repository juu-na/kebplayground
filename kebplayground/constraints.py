"""Deciding which pairs are not allowed to be matched at all.

Kept apart from scoring because these rules cannot be outweighed.
A pair banned here stays banned even if it scores 1.0.

Produces H, the allow table that matcher.py reads.
"""

import itertools

from .models import AllowTable, User, pair_key


def _preferences_allow(a: User, b: User) -> bool:
    """Whether one user's stated preferences accept the other.

    Only the hard preferences are read, the ones vocabulary.HARD_PREFERENCES
    lists. The soft ones move the score in scoring.py, and reading them here
    would ban a pair that is a worse match rather than an impossible one.

    A key that is left out means no restriction, so a user who states nothing
    accepts anybody.
    """
    genders = a.preferences.get("genders")
    if genders is not None and b.gender not in genders:
        return False

    lowest_highest = a.preferences.get("age")
    if lowest_highest is not None:
        lowest, highest = lowest_highest
        if not lowest <= b.age <= highest:
            return False

    return True


def is_allowed(a: User, b: User) -> bool:
    """Decide whether one pair is allowed to be matched.

    Input: two users.
    Output: True when the pair is allowed.

    Any one of these on its own bans the pair:
    - the same user on both sides
    - the two users are open to no kind of connection in common
    - one user's stated preferences rule the other out

    Returning False as soon as one rule fails keeps this easy to read.

    The first rule goes on the id rather than on the whole user. Two users
    who happen to agree on every other field are a real pair, and a file
    holding one id twice is not.
    """
    if a.id == b.id:
        return False

    if a.modes.isdisjoint(b.modes):
        return False

    # Both ways round. A preference stated by either user bans the pair.
    return _preferences_allow(a, b) and _preferences_allow(b, a)


def build_allow_table(users: list[User]) -> AllowTable:
    """Run is_allowed on every pair.

    Input: the full list of users.
    Output: H, a dict giving True or False for each pair.

    combinations never pairs a user with themselves, so that case never
    reaches the table.
    """
    return {
        pair_key(x, y): is_allowed(x, y)
        for x, y in itertools.combinations(users, 2)
    }
