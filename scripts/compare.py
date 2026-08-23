"""Run every matching algorithm over the same users and print what each one did.

The three are judged by reading the pairs, not by a number. blossom returns
the highest total by construction, so ranking on total score would record a
property of the algorithm rather than find anything out. What matters is
whether the pairs look like the ones a person would expect.

    python -m scripts.compare
    python -m scripts.compare --input users.csv --min-score 0.5

Run as a module rather than by path. The package is not installed, so only
the working directory puts it on the import path.
"""

import argparse
import time
from pathlib import Path

from kebplayground import constraints, data, matcher, scoring
from kebplayground.models import pair_key


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", help="a CSV of users. When left out, users are made up")
    parser.add_argument("--count", type=int, default=40)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--min-score", type=float, default=scoring.MIN_MATCH_SCORE)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.input is None:
        users = data.generate_users(args.count, args.seed)
    else:
        users = data.load_users(Path(args.input))
    waiting = [user for user in users if user.status == "waiting"]

    allowed = constraints.build_allow_table(waiting)
    scores, modes, allowed = scoring.build_score_table(waiting, allowed, args.min_score)

    print(f"{len(waiting)} waiting, {sum(allowed.values())} pairs allowed, "
          f"{len(scores)} of them at or above {args.min_score}")

    for name, algorithm in matcher.ALGORITHMS.items():
        started = time.perf_counter()
        matches = algorithm(scores, allowed)
        took = time.perf_counter() - started

        total = sum(scores[pair_key(*pair)] for pair in matches)
        print(f"\n{name}  {len(matches)} pairs, total {total:.3f}, {took * 1000:.1f}ms")
        for pair in sorted(matches, key=lambda pair: -scores[pair_key(*pair)]):
            key = pair_key(*pair)
            print(f"    {key[0]} {key[1]}  {modes[key]:<10} {scores[key]:.2f}")

        left = sorted(user.id for user in waiting
                      if user.id not in {uid for match in matches for uid in match})
        print(f"    still waiting: {len(left)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
