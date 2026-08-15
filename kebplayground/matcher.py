"""The matching algorithms.

These algorithms take S and H tables as inputs.
This module never imports User, which allows testing the
algorithms on a few made up ids instead of full user profiles.

The first two put users into pairs and are meant to be compared against each
other. The third puts users into groups instead, and is used for friend
group mode.
"""

from .models import AllowTable, Pair, ScoreTable


def greedy(scores: ScoreTable, allowed: AllowTable) -> list[Pair]:
    """Take the best pair still available, again and again.

    Input: S and H.
    Output: the list of pairs that were matched.

    This gives the highest total score. It promises nothing else. Two people
    who were matched to each other may each prefer someone in another pair.

    To implement: sort the allowed pairs by score, highest first. Go down the
    list and accept a pair only when neither of the two is already matched.
    """
    raise NotImplementedError


def gale_shapley(scores: ScoreTable, allowed: AllowTable) -> list[Pair]:
    """Match everyone so that nobody wants to swap.

    Input: S and H.
    Output: the list of pairs that were matched.

    The total score usually comes out lower than greedy. In exchange, there
    is no pair of people who would both rather leave the partner they were
    given and take each other instead.

    To implement: give each user a list of everyone they are allowed to
    match with, sorted by score, highest first. Then repeat this until
    nobody is left over. An unmatched user asks the next person on their
    list who they have not asked yet. That person keeps whichever of their
    current partner and the new asker scores higher, and turns down the
    other.

    The usual version of this algorithm has two separate sides, such as
    students and schools. Here there is one pool, so the users have to be
    split into askers and receivers on a fixed rule, such as sorted id
    order. Using a fixed rule keeps the result the same on every run.
    """
    raise NotImplementedError


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

    To implement: start with every user alone in a group of one. Repeatedly
    join the two groups whose worst pair scores highest, skipping any join
    that would go over max_size or that would put a banned pair in the same
    group. Stop when no join is left that is allowed.
    """
    raise NotImplementedError


ALGORITHMS = {
    "greedy": greedy,
    "stable": gale_shapley,
}
