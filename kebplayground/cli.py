"""Running the whole application from the command line.

Joins the steps together and reads the command line arguments.
None of the matching work happens here. Each step below is done by the module
it belongs to.
"""

import argparse
import json
from pathlib import Path
from typing import cast

from . import data, pipeline, scoring


def build_parser() -> argparse.ArgumentParser:
    """Set up the command line arguments.

    Arguments to support:
      --input PATH     a CSV of users. When left out, users are made up
      --count N        how many users to make up, 100 by default
      --seed N         the seed used when making up users, so a run can be
                       repeated exactly
      --min-score N    the lowest score worth offering, so a run can be
                       loosened or tightened without touching the code
      --explain        also ask the LLM for an activity for each pair
      --cache PATH     where the LLM answers are kept between runs,
                       .cache/llm.json by default
      --output PATH    where to write the results as JSON
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--min-score", type=float, default=scoring.MIN_MATCH_SCORE)
    parser.add_argument("--explain", action="store_true")
    parser.add_argument("--cache", default=".cache/llm.json")
    parser.add_argument("--output")

    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    """Do one full run.

    Input: the arguments that were read from the command line.
    Output: a dict holding the matches, the numbers judging the run, and any
    messages that were written.

    The matching itself lives in pipeline.run_matching, which the Phase 2
    web layer calls with the same arguments.
    """
    # read users from csv or generate test users
    if args.input is None:
        users = data.generate_users(args.count, args.seed)
    else:
        users = data.load_users(Path(args.input))

    return pipeline.run_matching(
        users,
        min_score=args.min_score,
        explain=args.explain,
        cache=Path(args.cache) if args.cache else None,
    )


def print_table(result: dict[str, object]) -> None:
    """Print the matches to the screen.

    One line per match, showing both user ids, the kind of connection, the
    score, and the message if one was written. The people still waiting get
    their own block, because waiting is a normal outcome rather than a
    failure.
    """
    for entry in cast("list[dict[str, object]]", result["matches"]):
        line = (
            f"{entry['a']} {entry['b']}  {entry['mode']:<10} "
            f"{round(cast(float, entry['score']), 2)}"
        )
        message = entry.get("suggestion")
        if message:
            line += f"  {message}"
        print(line)

    for mode, numbers in cast("dict[str, dict]", result["modes"]).items():
        print(
            f"{mode:<10} {numbers['pairs']} pairs, average {numbers['average']}, "
            f"worst off {numbers['worst_off']}"
        )

    waiting = cast("list[str]", result["waiting"])
    print(f"waiting: {len(waiting)}")
    if waiting:
        print("  " + " ".join(waiting))


def main(argv: list[str] | None = None) -> int:
    """Read the arguments, do the run, print it, and save it.

    Returns the exit code for the process, 0 when everything worked.

    main(argv)
      ├─ build_parser().parse_args(argv) → args
      ├─ run(args) → result
      ├─ print_table(result)
      └─ (write result to args.output, if given)
    """
    args = build_parser().parse_args(argv)
    result = run(args)
    print_table(result)

    if args.output:
        with open(args.output, "w") as file:
            json.dump(result, file, indent=2)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
