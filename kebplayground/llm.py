"""Asking an LLM to write the message shown to a matched pair.

This runs after matching.
The model explains a decision that has already been made. It never affects
who gets matched with who. If it did, the same input would stop giving the
same result.

It only runs when the --explain flag is given and the answers are saved to a
JSON file. This is to prevent a failed API call breaking a live demo.
"""
import json
import os
import re
import sys
from pathlib import Path

from .models import User

MODEL = "gemini-3.6-flash"

# The environment variable the key is read from. Copy .env.example to .env
# and put the key there.
API_KEY = "GEMINI_API_KEY"

_already_said: set[str] = set()


def _say_once(note: str) -> None:
    """Say something on the way past, once per run.

    explain is called for every matched pair, so without this a missing key
    would print the same line a hundred times.
    """
    if note in _already_said:
        return
    _already_said.add(note)
    print(f"llm: {note}", file=sys.stderr)


def _api_key() -> str | None:
    """Read the key at the point it is needed.

    Reading it when this module is imported would mean the whole command
    line and the whole test suite stopped working without python-dotenv
    installed, since cli.py imports this module whether --explain was asked
    for or not. It would also mean a key set after the import was ignored.

    python-dotenv only copies .env into the environment, so a key exported
    some other way works just as well and its absence is not worth failing
    over.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        pass
    else:
        load_dotenv()

    return os.getenv(API_KEY)


SYSTEM_PROMPT = """\
You write a short message shown to two people who have just been matched by
an automated matching system.

You will be given both users' profiles, the score they were matched with,
and a breakdown of the separate measurements that made up that score (for
example timetable overlap, shared major, shared interests). The matching
decision has already been made. Your only job is to explain it in plain
language and give the two of them a reason to say hello.

Write one message, addressed to both of them together, that:
- points to one or two specific reasons they were matched
- suggests one simple, low-effort first step they could take

Rules:
- Only use reasons that appear in the measurements you were given. Do not
  invent a shared trait, guess at something not in the data, or mention a
  measurement you were not handed.
- Keep the tone warm and casual, like a friend making an introduction, not
  corporate or robotic.
- If the user's purpose is to seek a romantic partner, write the message in
  a flirty tone
- Two to three sentences. Stay under 300 characters.
- Output only the message itself. No greeting, no signature, no labels like
  "Message:".
"""


def describe(user: User) -> str:
    return (
        f"User {user.id}: {user.major} {user.faculty}, year {user.year}, "
        f"age {user.age}, languages {sorted(user.languages)}, "
        f"interests {sorted(user.interests)}, looking for a {user.mode}"
    )


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
    usera = describe(a)
    userb = describe(b)

    ranked = sorted(breakdown.items(), key=lambda item: item[1], reverse=True)
    measurement_lines = "\n".join(f"  - {name}: {value:.2f}" for name, value in ranked)
    top_name, top_value = ranked[0]

    return (
        f"{usera}\n"
        f"{userb}\n\n"
        f"Match score: {score:.2f}\n"
        f"Measurements:\n{measurement_lines}\n\n"
        f"The highest-scoring measurement is {top_name} ({top_value:.2f}). "
        f"Write the match message now."
    )


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
    key = "|".join(sorted((a.id, b.id)))

    saved: dict[str, str] = {}
    if cache is not None and cache.exists():
        saved = json.loads(cache.read_text())
        if key in saved:
            return saved[key]

    message = _ask_the_model(a, b, score, breakdown)
    if message is None:
        # Nothing is cached here. A plain message is what gets written when
        # the model could not be reached, and caching it would keep handing
        # it back on later runs that could have asked properly.
        return plain_message(breakdown)

    if cache is not None:
        # The cache lives in its own directory, which is not there on a first
        # run. Without this the first answer worth keeping ends the run.
        cache.parent.mkdir(parents=True, exist_ok=True)
        saved[key] = message
        cache.write_text(json.dumps(saved, indent=2))

    return message


def _ask_the_model(
    a: User,
    b: User,
    score: float,
    breakdown: dict[str, float],
) -> str | None:
    """Ask the model for one message, or return None when it cannot be had.

    None covers every way this can go wrong: no key, no package, a failed
    call, and a reply that verify turned down. The caller falls back to a
    plain message either way, so the rest of the run still finishes.
    """
    api_key = _api_key()
    if not api_key:
        _say_once(f"{API_KEY} is not set, so the messages are the plain ones.")
        return None

    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=MODEL,
            contents=build_prompt(a, b, score, breakdown),
            config={"system_instruction": SYSTEM_PROMPT},
        )
        message = (response.text or "").strip()
    except Exception as went_wrong:
        _say_once(f"the model could not be reached ({went_wrong}), so the messages are the plain ones.")
        return None

    if not verify(message, breakdown):
        _say_once("a reply was turned down by verify, so that pair gets the plain message.")
        return None

    return message


def plain_message(breakdown: dict[str, float]) -> str:
    """The message shown when the model was not used.

    Built out of the measurements alone, so it names nothing that was not
    measured.
    """
    ranked = sorted(breakdown.items(), key=lambda item: item[1], reverse=True)
    top_names = [name for name, value in ranked if value > 0][:2]
    if top_names:
        return f"You two were matched on {' and '.join(top_names)}. Say hi!"
    return "You two were matched. Say hi and see what you have in common."


# The longest message worth showing. The system prompt asks for the same
# number, so a reply past it is one that ignored the instructions.
LONGEST = 300

# The words that give away which measurement a message is leaning on, one
# entry per measurement in features.FEATURES. A message may only name a
# measurement it was handed, so naming one that is missing from the
# breakdown means the model made the reason up.
REASON_WORDS: dict[str, tuple[str, ...]] = {
    "timetable": ("free time", "schedule", "timetable", "free hour"),
    "interests": ("interest", "hobby", "hobbies"),
    "languages": ("language",),
    "major": ("major", "subject", "study the same", "both study"),
    "age": ("age", "years old"),
}


def _mentions(message: str, word: str) -> bool:
    """Whether a message uses one word, rather than merely containing it.

    Matching on the bare letters turned down any message using the word
    language, since it holds age inside it. The plural and the usual endings
    still count, so interests matches interest.
    """
    return re.search(rf"\b{re.escape(word)}(?:s|es|ed|ing)?\b", message) is not None


def verify(message: str, breakdown: dict[str, float]) -> bool:
    """Check the message the model wrote, before anyone sees it.

    Input: the model's reply, and the measurements it was given.
    Output: True when the message is safe to show.

    To implement: turn down an empty message, one that is longer than the
    limit, or one that gives a reason which is not in the measurements it
    was handed.
    """
    if not message.strip():
        return False

    if len(message) > LONGEST:
        return False

    lowered = message.lower()
    for name, words in REASON_WORDS.items():
        if name in breakdown:
            continue
        if any(_mentions(lowered, word) for word in words):
            return False

    return True
