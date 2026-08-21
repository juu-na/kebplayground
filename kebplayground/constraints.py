"""Deciding which pairs are not allowed to be matched at all.

Kept apart from scoring because these rules cannot be outweighed.
A pair banned here stays banned even if it scores 1.0.

Produces H, the allow table that matcher.py reads.
"""

import itertools
from .models import AllowTable, User, pair_key


def is_allowed(a: User, b: User) -> bool:
    """Decide whether one pair is allowed to be matched.

    Input: two users.
    Output: True when the pair is allowed.

    Rules to implement. Any one of these on its own bans the pair:
    - the same user on both sides
    - the two users are looking for different modes
    - the two users share no free slot, so they could never meet
    - one user's stated preferences rule the other out

    Returning False as soon as one rule fails keeps this easy to read.
    """
    if a == b:
        return False
    if a.mode != b.mode:
        return False
    if not (set(a.free_slots) & set(b.free_slots)):
        return False
    if hasattr(a, 'allows') and not a.allows(b):
        return False
    if hasattr(b, 'allows') and not b.allows(a):
        return False

    return True




def build_allow_table(users: list[User]) -> AllowTable:
    """Run is_allowed on every pair.

    Input: the full list of users.
    Output: H, a dict giving True or False for each pair.

    To implement: go through every pair once using
    itertools.combinations(users, 2), get the key for each pair from
    models.pair_key, and call is_allowed on it.

    combinations never pairs a user with themselves, so that case never
    reaches the table.
    """
    table = {}
    for u1, u2 in itertools.combinations(users, 2):
        key = pair_key(u1, u2)
        table[key] = is_allowed(u1, u2)
    return table

 
