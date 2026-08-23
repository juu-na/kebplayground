"""Run the pipeline over a made up demo cohort.

scripts/compare.py draws evenly from every registry. A real cohort is
narrower, and narrower cohorts score higher, so a floor tuned on an even
spread lets through more pairs than expected.

The shape below is an assumption. It is not measured.

    python -m scripts.keb_demo
    python -m scripts.keb_demo --count 60 --seed 4

Run as a module rather than by path. The package is not installed, so only
the working directory puts it on the import path.
"""

import argparse
import statistics

from kebplayground import constraints, data, matcher, scoring
from kebplayground.models import pair_key

# What the demo cohort is taken to look like.
#
# One faculty, so every pair pays major_similarity's faculty weight in full
# and only the specialisation separates them. Ages 18 to 24, weighted on 19 to
# 21. Mostly Korean. Mostly friendship, with a few after a date.
KEB = data.Cohort(
    faculties=("Faculty of Engineering and Design",),
    years=(1, 2, 3),
    ages=(18, 24),
    age_weights=(2, 12, 24, 24, 16, 8, 4),
    language_weights={
        "Korean": 55,
        "Mandarin": 12,
        "Cantonese": 8,
        "Indonesian": 5,
        "Arabic": 4,
        "Japanese": 3,
        "Hindi": 3,
    },
    mode_weights={"friendship": 9, "date": 1},
)

# The floors reported, MIN_MATCH_SCORE among them.
FLOORS = (0.50, 0.55, 0.60, 0.65, 0.70)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--runs", type=int, default=20,
                        help="how many seeds the floor sweep averages over")
    return parser


def sweep(count: int, runs: int) -> None:
    """Print what each floor would do, averaged over several runs.

    One run says very little at this size.
    """
    every_score: list[float] = []
    matched: dict[float, list[int]] = {floor: [] for floor in FLOORS}

    for seed in range(runs):
        users = data.generate_users(count, seed, cohort=KEB)
        allowed = constraints.build_allow_table(users)

        scores, _, _ = scoring.build_score_table(users, allowed, 0.0)
        every_score.extend(scores.values())

        for floor in FLOORS:
            kept, _, live = scoring.build_score_table(users, allowed, floor)
            matched[floor].append(len(matcher.blossom(kept, live)))

    every_score.sort()
    at = lambda q: every_score[int(q * len(every_score))]
    print(f"{len(every_score)} scored pairs over {runs} runs of {count}")
    print(f"  mean {statistics.mean(every_score):.3f}  median {at(0.5):.3f}  "
          f"p90 {at(0.9):.3f}  p95 {at(0.95):.3f}  p99 {at(0.99):.3f}")

    print("\nfloor   kept    pairs   waiting")
    for floor in FLOORS:
        kept = sum(1 for score in every_score if score >= floor)
        pairs = statistics.mean(matched[floor])
        chosen = " <- MIN_MATCH_SCORE" if floor == scoring.MIN_MATCH_SCORE else ""
        print(f"{floor:.2f}  {100 * kept / len(every_score):5.2f}%  "
              f"{pairs:6.1f}  {count - 2 * pairs:8.1f}{chosen}")


def one_run(count: int, seed: int) -> None:
    """Print the matches from a single run, to be read rather than counted."""
    users = data.generate_users(count, seed, cohort=KEB)
    allowed = constraints.build_allow_table(users)
    scores, modes, live = scoring.build_score_table(users, allowed, scoring.MIN_MATCH_SCORE)
    matches = matcher.blossom(scores, live)

    print(f"\nseed {seed}, floor {scoring.MIN_MATCH_SCORE}")
    for pair in sorted(matches, key=lambda pair: -scores[pair_key(*pair)]):
        key = pair_key(*pair)
        a, b = (user for user in users if user.id in key)
        print(f"    {key[0]} {key[1]}  {modes[key]:<10} {scores[key]:.2f}  "
              f"{a.major} / {b.major}")

    paired = {uid for pair in matches for uid in pair}
    print(f"    still waiting: {sum(1 for user in users if user.id not in paired)}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sweep(args.count, args.runs)
    one_run(args.count, args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
