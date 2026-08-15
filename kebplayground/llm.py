"""Asking an LLM to write the message shown to a matched pair.

This runs after matching.
The model explains a decision that has already been made. It never affects
who gets matched with who. If it did, the same input would stop giving the
same result.

It only runs when the --explain flag is given and the answers are saved to a
JSON file. This is to prevent a failed API call breaking a live demo.
"""

from pathlib import Path

from .models import User

# Which model to call. No provider has been chosen yet, so this is left
# empty on purpose.
# Once one is picked, the package to install and the name of the environment
# variable holding the API key follow from that choice.
MODEL = ""

SYSTEM_PROMPT = """\
Placeholder.

Write the instructions that turn the details of a match into a short message
for the two users. Cover what the model is being asked to do, what tone to
use, how long the message may be, and the rule that the only reasons it may
give are the ones in the measurements it was handed.
"""


def build_prompt(
    a: User,
    b: User,
    score: float,
    breakdown: dict[str, float],
) -> str:
    """Turn one match into the message sent to the model.

    Input: the two matched users, their score, and the separate measurements
    from scoring.score_pair.
    Output: one string.

    To implement: state both profiles, the score, and the measurements.
    Pointing out which measurements came back highest gives the model
    something definite to name as the reason, rather than leaving it to
    guess.
    """
    raise NotImplementedError


def explain(
    a: User,
    b: User,
    score: float,
    breakdown: dict[str, float],
    cache: Path | None = None,
) -> str:
    """Get the message for one matched pair.

    Input: the details of the match, and an optional file of saved answers.
    Output: the text of the message.

    To implement: look in the saved answers first, and return the stored
    message if this pair is already there. Otherwise call the API with
    SYSTEM_PROMPT and the built message, check the reply with verify, save
    it, and return it.

    If the API call fails, return a plain message built from the
    measurements rather than raising an error, so the rest of the run still
    finishes.
    """
    raise NotImplementedError


def verify(message: str, breakdown: dict[str, float]) -> bool:
    """Check the message the model wrote, before anyone sees it.

    Input: the model's reply, and the measurements it was given.
    Output: True when the message is safe to show.

    To implement: turn down an empty message, one that is longer than the
    limit, or one that gives a reason which is not in the measurements it
    was handed.
    """
    raise NotImplementedError
