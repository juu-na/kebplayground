"""Running the whole application from the command line.

Joins the steps together and reads the command line arguments.
None of the matching work happens here. Each step below is done by the module
it belongs to.
"""

import argparse
import json
from pathlib import Path
from typing import cast

from kebplayground import constraints, data, llm, matcher, scoring


def build_parser() -> argparse.ArgumentParser:
    """Set up the command line arguments.

    Arguments to support:
      --input PATH     a CSV of users. When left out, users are made up
      --count N        how many users to make up, 100 by default
      --seed N         the seed used when making up users, so a run can be
                       repeated exactly
      --mode NAME      the kind of connection, must be one of the modes in
                       scoring.WEIGHTS
      --algo NAME      one of the names in matcher.ALGORITHMS, or "cluster"
      --explain        also ask the LLM to write the match messages
      --output PATH    where to write the results as JSON
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--mode", choices=list(scoring.WEIGHTS), required=True)
    parser.add_argument(
        "--algo", choices=(list(matcher.ALGORITHMS) + ["cluster"]), required=True
    )
    parser.add_argument("--explain", action="store_true")
    parser.add_argument("--output")

    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    """Do one full run.

    Input: the arguments that were read from the command line.
    Output: a dict holding the matches, the numbers judging the run, and any
    messages that were written.

    This is the same shape the Phase 2 API sends back. The FastAPI layer
    calls this function instead of repeating the steps itself.
    """
    # read users from csv or generate test users
    if args.input is None:
        users = data.generate_users(args.count, args.seed)
    else:
        users = data.load_users(Path(args.input))

    # build H
    H = constraints.build_allow_table(users)

    # build S for the chosen mode
    S = scoring.build_score_table(users, args.mode, H)

    # run the chosen algorithm
    if args.algo == "cluster":
        # no evaluation for cluster matches
        return {"algo": args.algo, "matches": matcher.cluster(S, H)}

    matches = matcher.ALGORITHMS[args.algo](S, H)

    # evaluate the result
    evaluation = scoring.evaluate(users, matches, S, H)

    # when --explain was given, call llm.explain for each matched pair
    user_map = {user.id: user for user in users}
    records = []

    for a, b in matches:
        entry = {"a": a, "b": b, "score": S[(a, b)]}
        if args.explain:
            _, breakdown = scoring.score_pair(user_map[a], user_map[b], args.mode)
            entry["message"] = llm.explain(
                user_map[a], user_map[b], S[(a, b)], breakdown
            )
        records.append(entry)

    result = {"algo": args.algo, "matches": records}
    result.update(evaluation)
    return result


def print_table(result: dict[str, object]) -> None:
    """Print the matches to the screen.

    One line per match, showing both user ids, the score, and the message if
    one was written.
    """
    if result["algo"] == "cluster":
        for group in cast("list[list[str]]", result["matches"]):
            print(" ".join(group))
        return

    for entry in cast("list[dict[str, object]]", result["matches"]):
        line = f"{entry['a']} {entry['b']} {round(cast(float, entry['score']), 2)}"
        message = entry.get("message")
        if message:
            line += f" {message}"
        print(line)


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
