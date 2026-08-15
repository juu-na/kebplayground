"""Running the whole application from the command line.

Joins the steps together and reads the command line arguments.
None of the matching work happens here. Each step below is done by the module
it belongs to.
"""

import argparse


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
    raise NotImplementedError


def run(args: argparse.Namespace) -> dict[str, object]:
    """Do one full run.

    Input: the arguments that were read from the command line.
    Output: a dict holding the matches, the numbers judging the run, and any
    messages that were written.

    This is the same shape the Phase 2 API sends back. The FastAPI layer
    calls this function instead of repeating the steps itself.

    Steps to implement, in this order:
    1. read the users from --input, or make them up
    2. build H with constraints.build_allow_table
    3. build S with scoring.build_score_table, for the chosen mode, passing
       in H so that only the allowed pairs are scored
    4. run the chosen algorithm from matcher over S and H
    5. judge the result with scoring.evaluate
    6. when --explain was given, call llm.explain for each matched pair
    """
    raise NotImplementedError


def print_table(result: dict[str, object]) -> None:
    """Print the matches to the screen.

    One line per match, showing both user ids, the score, and the message if
    one was written.
    """
    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    """Read the arguments, do the run, print it, and save it.

    Returns the exit code for the process, 0 when everything worked.
    """
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
