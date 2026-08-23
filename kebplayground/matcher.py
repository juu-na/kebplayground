"""The matching algorithms.

These algorithms take S and H tables as inputs.
This module never imports User, which allows testing the
algorithms on a few made up ids instead of full user profiles.

All three put users into pairs and are meant to be compared against each
other. greedy takes the best pairs it can see. fairest looks after whoever is
hardest to place. blossom works out the highest total there is.
"""

import itertools

import networkx

from .models import AllowTable, Pair, ScoreTable, pair_key


def _everyone(scores: ScoreTable, allowed: AllowTable) -> list[str]:
    """Every id either table mentions, in a fixed order.

    Both tables are read because build_score_table leaves banned and under
    floor pairs out of S. Somebody nobody is allowed to match with appears
    only in H, and still has to turn up on the waiting list.
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


def improve(scores: ScoreTable, allowed: AllowTable, matches: list[Pair]) -> list[Pair]:
    """Repeatedly apply whichever single change raises the total most.

    A change takes two people who are not together, puts them together, and
    lets the partners they leave behind pair up with each other when that is
    allowed. It stops when no change helps.

    This is the part a single pass cannot do: undo an earlier decision.
    """
    matches = list(matches)
    while True:
        partner = {}
        for x, y in matches:
            partner[x] = y
            partner[y] = x

        best, gain = None, 1e-12
        for pair in scores:
            if not allowed.get(pair):
                continue
            x, y = pair
            if partner.get(x) == y:
                continue

            lost = sum(scores[pair_key(u, partner[u])] for u in (x, y) if u in partner)
            spare = [partner[u] for u in (x, y) if u in partner and partner[u] not in (x, y)]
            rejoin = None
            regain = 0.0
            if len(spare) == 2 and allowed.get(pair_key(*spare)):
                rejoin = pair_key(*spare)
                regain = scores[rejoin]
            elif len(spare) == 2:
                # Taking this pair would strand both of the people they left.
                continue

            delta = scores[pair] + regain - lost
            if delta > gain:
                best, gain = (pair, spare, rejoin), delta

        if best is None:
            return matches

        pair, spare, rejoin = best
        dropped = set(pair) | set(spare)
        matches = [match for match in matches if not dropped & set(match)]
        matches.append(pair)
        if rejoin:
            matches.append(rejoin)


def fairest_then_improve(scores: ScoreTable, allowed: AllowTable) -> list[Pair]:
    """fairest to place everyone it can, then improve to buy the score back."""
    return improve(scores, allowed, fairest(scores, allowed))


def blossom(scores: ScoreTable, allowed: AllowTable) -> list[Pair]:
    """The highest total there is, using Edmonds' algorithm from networkx.

    maxcardinality stays False on purpose. True would force the most pairs it
    can regardless of score, which is the goal this redesign moved away from.

    networkx hands back its pairs in whatever order it likes, so they go
    through pair_key and the list is sorted, to keep runs comparable.
    """
    graph = networkx.Graph()
    graph.add_nodes_from(_everyone(scores, allowed))
    for pair in scores:
        if allowed.get(pair):
            graph.add_edge(pair[0], pair[1], weight=scores[pair])

    chosen = networkx.max_weight_matching(graph, maxcardinality=False)
    return sorted(pair_key(x, y) for x, y in chosen)


ALGORITHMS = {
    "greedy": greedy,
    "fairest": fairest_then_improve,
    "blossom": blossom,
}
