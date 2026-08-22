"""The matching algorithms.

These algorithms take S and H tables as inputs.
This module never imports User, which allows testing the
algorithms on a few made up ids instead of full user profiles.

The first two put users into pairs and are meant to be compared against each
other. They want different things: greedy takes the best pairs it can see,
fairest looks after whoever is doing worst. The third puts users into groups
instead, and is used for friend group mode.
"""

import itertools

from .models import AllowTable, Pair, ScoreTable, pair_key


def _everyone(scores: ScoreTable, allowed: AllowTable) -> list[str]:
    """Every id either table mentions, in a fixed order.

    Both tables are read because build_score_table leaves banned pairs out
    of S. A user nobody is allowed to match with appears only in H, and
    still needs a group of their own from cluster.
    """
    return sorted({uid for pair in (*scores, *allowed) for uid in pair})


def _usable(pair: Pair, scores: ScoreTable, allowed: AllowTable) -> bool:
    """Whether a pair is one that can be matched: scored, and allowed."""
    return pair in scores and bool(allowed.get(pair))


def greedy(scores: ScoreTable, allowed: AllowTable) -> list[Pair]:
    """Take the best pair still available, again and again.

    Input: S and H.
    Output: the list of pairs that were matched.

    Nobody ends up wanting to swap. Both halves of a pair read the same
    score, so everyone agrees on which pairs are good, and the best pair
    left has to be taken or those two would rather have each other than
    whatever they were given. Taking it and repeating is this function.

    It does not give the highest total score, which is a different thing.
    Taking the best pair can strand two people who each had a good second
    choice, and over random tables it lands around 92% of the best total.

    Ties are broken on the ids, so the same tables give the same answer on
    every run.
    """
    ranked = sorted(
        (pair for pair in scores if allowed.get(pair)),
        key=lambda pair: (-scores[pair], pair),
    )

    spoken_for: set[str] = set()
    matches = []
    for pair in ranked:
        if not spoken_for & set(pair):
            spoken_for |= set(pair)
            matches.append(pair)

    return matches


def fairest(scores: ScoreTable, allowed: AllowTable) -> list[Pair]:
    """Match whoever is doing worst first.

    Input: S and H.
    Output: the list of pairs that were matched.

    Each round works out the best partner still free for each user, then
    takes the user whose best is the lowest of those and gives them it.

    What this buys is that fewer people are left out. Most pairs are banned
    by the time constraints.py has run, so somebody with only one or two
    allowed partners loses them to greedy, which spends the popular users
    first and strands whoever is left. Serving the hardest to place user
    first spends those scarce options on the people who need them.

    Measured over 125 runs of 60 made up users, it matched more pairs than
    greedy in 117 and fewer in none, leaving 6.7 users unmatched against
    greedy's 11.0. The average score comes out lower in exchange, 0.46
    against 0.50, because the extra pairs it finds are the weak ones greedy
    never got to.
    """
    free = _everyone(scores, allowed)
    matches = []

    while True:
        best_left = {}
        for uid in free:
            options = [
                other
                for other in free
                if other != uid and _usable(pair_key(uid, other), scores, allowed)
            ]
            if options:
                best_left[uid] = max(
                    options, key=lambda other: (scores[pair_key(uid, other)], other)
                )

        if not best_left:
            return matches

        worst_off = min(
            best_left, key=lambda uid: (scores[pair_key(uid, best_left[uid])], uid)
        )
        partner = best_left[worst_off]

        matches.append(pair_key(worst_off, partner))
        free = [uid for uid in free if uid not in (worst_off, partner)]


def _worst_crossing_pair(
    one: list[str],
    other: list[str],
    scores: ScoreTable,
    allowed: AllowTable,
) -> float | None:
    """The lowest score across two groups, or None when they cannot join.

    Only the pairs crossing between the two groups are looked at. The pairs
    inside each group were checked when that group formed.
    """
    lowest = None
    for uid in one:
        for another in other:
            pair = pair_key(uid, another)
            if not _usable(pair, scores, allowed):
                return None
            if lowest is None or scores[pair] < lowest:
                lowest = scores[pair]
    return lowest


def cluster(
    scores: ScoreTable,
    allowed: AllowTable,
    max_size: int = 5,
) -> list[list[str]]:
    """Build friend groups by joining small groups into bigger ones.

    Input: S, H, and the largest a group is allowed to get.
    Output: a list of groups, each one a list of user ids.

    When two groups are considered for joining, they are judged on their
    worst pair, not their average pair. Using the average would let one
    strong pairing drag in somebody who does not get on with anyone else in
    the group.

    Everyone ends up in exactly one group, including anyone who cannot be
    joined to a single other person. They keep the group of one they started
    with.
    """
    groups = [[uid] for uid in _everyone(scores, allowed)]

    while True:
        best_join = None
        best_score = None

        for one, other in itertools.combinations(range(len(groups)), 2):
            if len(groups[one]) + len(groups[other]) > max_size:
                continue
            worst = _worst_crossing_pair(groups[one], groups[other], scores, allowed)
            if worst is None:
                continue
            if best_score is None or worst > best_score:
                best_join, best_score = (one, other), worst

        if best_join is None:
            return groups

        one, other = best_join
        groups[one] = sorted(groups[one] + groups[other])
        del groups[other]


ALGORITHMS = {
    "greedy": greedy,
    "fairest": fairest,
}
