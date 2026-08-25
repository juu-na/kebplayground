"""One full matching run over a list of users.

The steps live in their own modules. This module only joins them, so that
the command line and the Phase 2 web layer share the same run.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import constraints, llm, matcher, scoring
from .models import User, pair_key

# Which algorithm a run uses. There is no flag for it: picking the algorithm
# is a decision the project makes once, not something a user chooses.
ALGORITHM = "blossom"

# How many suggestions are asked for at once. Each one is a network call
# that spends nearly all its time waiting, so a few at a time turns a run
# from a minute into a few seconds. Kept small to stay inside the API's rate
# limit on a big run.
SUGGESTIONS_AT_ONCE = 4


def run_matching(
    users: list[User],
    *,
    min_score: float = scoring.MIN_MATCH_SCORE,
    explain: bool = False,
    cache: Path | None = None,
) -> dict[str, object]:
    """Do one full run over the given users.

    Output: a dict holding the matches, the numbers judging the run, and any
    suggestions that were written. This is the same shape the Phase 2 API
    sends back.
    """
    # only the people currently waiting take part in a run
    waiting = [user for user in users if user.status == "waiting"]

    # build H, then S over the pairs worth offering
    allowed = constraints.build_allow_table(waiting)
    scores, modes, allowed = scoring.build_score_table(waiting, allowed, min_score)

    matches = matcher.ALGORITHMS[ALGORITHM](scores, allowed)
    evaluation = scoring.evaluate(waiting, matches, scores, modes, allowed)

    # The best anyone could have done, floor or no floor. Somebody left
    # waiting is owed a reason, and "nobody cleared 0.6, your closest was
    # 0.54" is a reason. The pairs the floor dropped are gone from scores by
    # then, so this asks for them again with the floor taken off.
    unfloored, _, _ = scoring.build_score_table(
        waiting, constraints.build_allow_table(waiting), 0.0
    )
    best: dict[str, float] = {}
    for (left, right), score in unfloored.items():
        best[left] = max(best.get(left, 0.0), score)
        best[right] = max(best.get(right, 0.0), score)

    # The breakdown comes along whether or not a message was asked for, so
    # that a caller can show what the pair scored on without paying for the
    # LLM.
    user_map = {user.id: user for user in waiting}
    records = []

    for a, b in matches:
        key = pair_key(a, b)
        _, _, breakdown = scoring.score_pair(user_map[a], user_map[b])
        records.append(
            {
                "a": a,
                "b": b,
                "score": scores[key],
                "mode": modes[key],
                "breakdown": breakdown,
            }
        )

    if explain:
        def ask_for_one(entry: dict) -> str:
            return llm.suggest(
                user_map[entry["a"]],
                user_map[entry["b"]],
                entry["score"],
                entry["mode"],
                entry["breakdown"],
                cache=cache,
            )

        # map keeps the answers in the order the matches were given, so a run
        # reads the same however the threads finish.
        with ThreadPoolExecutor(max_workers=SUGGESTIONS_AT_ONCE) as pool:
            for entry, suggestion in zip(records, pool.map(ask_for_one, records)):
                entry["suggestion"] = suggestion

    result = {
        "algo": ALGORITHM,
        "matches": records,
        # What a pair had to clear to be offered at all, so that a page can
        # say how close somebody came.
        "floor": min_score,
        "best": best,
    }
    result.update(evaluation)
    return result
