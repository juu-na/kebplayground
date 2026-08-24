"""One full matching run over a list of users.

The steps live in their own modules. This module only joins them, so that
the command line and the Phase 2 web layer share the same run.
"""

from pathlib import Path

from . import constraints, llm, matcher, scoring
from .models import User, pair_key

# Which algorithm a run uses. There is no flag for it: picking the algorithm
# is a decision the project makes once, not something a user chooses.
ALGORITHM = "blossom"


def run_matching(
    users: list[User],
    *,
    min_score: float = scoring.MIN_MATCH_SCORE,
    explain: bool = False,
    cache: Path | None = None,
) -> dict[str, object]:
    """Do one full run over the given users.

    Output: a dict holding the matches, the numbers judging the run, and any
    messages that were written. This is the same shape the Phase 2 API sends
    back.
    """
    # only the people currently waiting take part in a run
    waiting = [user for user in users if user.status == "waiting"]

    # build H, then S over the pairs worth offering
    allowed = constraints.build_allow_table(waiting)
    scores, modes, allowed = scoring.build_score_table(waiting, allowed, min_score)

    matches = matcher.ALGORITHMS[ALGORITHM](scores, allowed)
    evaluation = scoring.evaluate(waiting, matches, scores, modes, allowed)

    # when explain was asked for, call llm.explain for each matched pair
    user_map = {user.id: user for user in waiting}
    records = []

    for a, b in matches:
        key = pair_key(a, b)
        entry = {"a": a, "b": b, "score": scores[key], "mode": modes[key]}
        if explain:
            _, _, breakdown = scoring.score_pair(user_map[a], user_map[b])
            entry["message"] = llm.explain(
                user_map[a],
                user_map[b],
                scores[key],
                modes[key],
                breakdown,
                cache=cache,
            )
        records.append(entry)

    result = {"algo": ALGORITHM, "matches": records}
    result.update(evaluation)
    return result
