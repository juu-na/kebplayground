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
import threading
from pathlib import Path

from . import vocabulary
from .models import User

MODEL = "gemini-3.6-flash"

# The environment variable the key is read from. Copy .env.example to .env
# and put the key there.
API_KEY = "GEMINI_API_KEY"

_already_said: set[str] = set()

# Guards the cache file. A run asks for several messages at once, and the
# cache is read and written whole, so two writers would drop each other's
# answers.
_cache_lock = threading.Lock()


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
You suggest one thing two university students could do together the first
time they meet.

Both study at the University of Auckland city campus. They have been matched
by an automated system and have never met. You will be given both profiles
and whether they were matched for friendship or for a date.

Suggest one activity, and make it specific to these two people rather than
something you would say to anybody. Draw on the whole of both profiles: what
they share, what is different and worth swapping notes on, their subjects,
their languages, their personalities and how old they are.

Rules:
- Somewhere public, on or near the city campus. Never a private home.
- Free, or under about ten dollars each. No alcohol.
- Nothing needing a booking, a membership, or gear they may not own.
- Suitable for two strangers meeting in daylight.
- Match the connection they asked for. Never suggest anything romantic to
  two people matched on friendship.
- Say what to do, not where to meet. They are told where separately.
- Two sentences at most, under 300 characters.
- Output only the suggestion. No greeting, no signature, no labels.
"""

# Words that mean the suggestion broke the rules above badly enough to throw
# away. A net rather than a guarantee: it catches the obvious misses, and
# the wording of the prompt does the rest.
UNSAFE_WORDS = (
    "alcohol", "bar", "beer", "cocktail", "drinks", "pub", "wine",
    "apartment", "flat", "home", "hotel", "my place", "your place",
)


def describe(user: User) -> str:
    """One user, as much of them as the model can use."""
    languages = ", ".join(sorted(user.languages)) or "English only"
    interests = ", ".join(sorted(user.interests)) or "none listed"
    return (
        f"{user.major} ({user.faculty}), year {user.year}, age {user.age}, "
        f"{user.mbti}. Speaks {languages}. Into {interests}."
    )


def build_prompt(
    a: User,
    b: User,
    score: float,
    mode: str,
    breakdown: dict[str, float],
) -> str:
    """Turn one match into the message sent to the model.

    Both profiles in full, plus what they already have in common. The shared
    things are spelled out so the model does not have to spot them, and the
    rest of each profile is there so it can suggest something that suits the
    two of them rather than only their overlap.
    """
    shared_interests = sorted(a.interests & b.interests)
    shared_languages = sorted(a.languages & b.languages)

    common = []
    if a.major == b.major:
        common.append(f"both study {a.major}")
    elif a.faculty == b.faculty:
        common.append(f"both in the {a.faculty}")
    if shared_interests:
        common.append("both into " + ", ".join(shared_interests))
    if shared_languages:
        common.append("both speak " + ", ".join(shared_languages))

    already = "; ".join(common) if common else "nothing obvious in common"

    return (
        f"First person: {describe(a)}\n"
        f"Second person: {describe(b)}\n\n"
        f"Matched for: {mode}\n"
        f"Already in common: {already}\n\n"
        f"Suggest what they should do."
    )


def suggest(
    a: User,
    b: User,
    score: float,
    mode: str,
    breakdown: dict[str, float],
    cache: Path | None = None,
) -> str:
    """Get the activity suggestion for one matched pair.

    Input: the details of the match, and an optional file of saved answers.
    Output: the text shown to both of them.

    Why they were matched is worked out in code, by why(), which is better at
    facts than the model is. The model is asked for the part code is bad at:
    one thing these two in particular could go and do.

    A failed call gives the written suggestion rather than raising, so the
    rest of the run still finishes.
    """
    key = "|".join(sorted((a.id, b.id)))

    if cache is not None:
        with _cache_lock:
            saved = _read_cache(cache)
        if key in saved:
            return saved[key]

    # Asked for outside the lock. This is the slow part, and holding the lock
    # across it would put the pairs back into single file.
    suggestion = _ask_the_model(a, b, score, mode, breakdown)
    if suggestion is None:
        # Nothing is cached here. This is what gets written when the model
        # could not be reached, and caching it would keep handing it back on
        # later runs that could have asked properly.
        return plain_suggestion(a, b)

    if cache is not None:
        with _cache_lock:
            # Read again rather than reusing what was read above. Another
            # pair may have written its own answer while this one was being
            # asked for, and that answer has to survive.
            saved = _read_cache(cache)
            saved[key] = suggestion
            # The cache lives in its own directory, which is not there on a
            # first run. Without this the first answer worth keeping ends
            # the run.
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(saved, indent=2))

    return suggestion


def _read_cache(cache: Path) -> dict[str, str]:
    """Read the saved answers, treating an unreadable file as empty.

    A run cut off part way through a write leaves a half written file. That
    is a reason to ask the model again, not to end the run.
    """
    if not cache.exists():
        return {}
    try:
        return json.loads(cache.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _ask_the_model(
    a: User,
    b: User,
    score: float,
    mode: str,
    breakdown: dict[str, float],
) -> str | None:
    """Ask the model for one suggestion, or None when it cannot be had.

    None covers every way this can go wrong: no key, no package, a failed
    call, and a reply that verify turned down. The caller falls back to the
    written suggestion either way, so the rest of the run still finishes.
    """
    api_key = _api_key()
    if not api_key:
        _say_once(f"{API_KEY} is not set, so the suggestions are the written ones.")
        return None

    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=MODEL,
            contents=build_prompt(a, b, score, mode, breakdown),
            config={"system_instruction": SYSTEM_PROMPT},
        )
        suggestion = (response.text or "").strip()
    except Exception as went_wrong:
        _say_once(
            f"the model could not be reached ({went_wrong}), "
            "so the suggestions are the written ones."
        )
        return None

    if not verify(suggestion):
        _say_once("a reply broke the rules, so that pair gets the written suggestion.")
        return None

    return suggestion


def plain_suggestion(a: User, b: User) -> str:
    """What to suggest when the model could not be asked.

    Nothing clever, only something the two could actually do, built from
    what they already share.
    """
    shared = sorted(a.interests & b.interests)
    if shared:
        return f"You are both into {shared[0].lower()}. Start there."
    return "Grab a coffee between lectures and compare timetables."


def plain_message(breakdown: dict[str, float]) -> str:
    """The measurements alone, in a sentence.

    The last fallback for why(), used when the pair have nothing concrete in
    common to name.
    """
    ranked = sorted(breakdown.items(), key=lambda item: item[1], reverse=True)
    top_names = [name for name, value in ranked if value > 0][:2]
    if top_names:
        return f"You two were matched on {' and '.join(top_names)}. Say hi!"
    return "You two were matched. Say hi and see what you have in common."


def why(a: User, b: User, breakdown: dict[str, float]) -> str:
    """Say what the pair actually have in common, without asking the model.

    Reads the same two users the model would have been told about, so it can
    name the shared major, interests and languages rather than only the
    measurement that scored highest. Used when the model cannot be reached.
    """
    reasons = []

    department = vocabulary.department_of(a.major)
    if a.major == b.major:
        reasons.append(f"you both study {a.major}")
    elif department is not None and department == vocabulary.department_of(b.major):
        reasons.append(f"you are both in {department}")
    elif a.faculty == b.faculty:
        reasons.append(f"you are both in the {a.faculty}")

    shared_interests = sorted(a.interests & b.interests)
    if shared_interests:
        reasons.append(f"you share {_listed(shared_interests)}")

    shared_languages = sorted(a.languages & b.languages)
    if shared_languages:
        reasons.append(f"you both speak {_listed(shared_languages)}")

    if breakdown.get("mbti", 0.0) >= 0.8:
        reasons.append(f"{a.mbti} and {b.mbti} get on")

    if not reasons:
        return plain_message(breakdown)

    said = _listed(reasons[:3])
    return said[0].upper() + said[1:] + ". Say hi!"


def _listed(things: list[str]) -> str:
    """Join for reading: "a", "a and b", "a, b and c"."""
    if len(things) == 1:
        return things[0]
    return ", ".join(things[:-1]) + " and " + things[-1]


# The longest message worth showing. The system prompt asks for the same
# number, so a reply past it is one that ignored the instructions.
LONGEST = 300

def _mentions(message: str, word: str) -> bool:
    """Whether a message uses one word, rather than merely containing it.

    Matching on the bare letters turned down any message using the word
    language, since it holds age inside it. The plural and the usual endings
    still count, so drink matches drinks.
    """
    return re.search(rf"\b{re.escape(word)}(?:s|es|ed|ing)?\b", message) is not None


def verify(suggestion: str) -> bool:
    """Check what the model wrote, before anyone sees it.

    Turns down an empty answer, one past the length limit, and one naming
    something the rules ruled out, such as a drink or somebody's flat.

    This cannot tell whether a suggestion is a good idea, only whether it
    broke a rule in a way that shows up in the words. Anything turned down
    falls back to the written suggestion.
    """
    if not suggestion.strip():
        return False

    if len(suggestion) > LONGEST:
        return False

    lowered = suggestion.lower()
    return not any(_mentions(lowered, word) for word in UNSAFE_WORDS)
